"""Runner de VALIDAÇÃO de dollar bar canônico (`config/constants.yaml::
canonical_bar_type=dollar`, decisão fechada em M2) — não é o pipeline de
produção. `config/constants.yaml::canonical_bar_type` foi decidido, mas
nenhum código de produção construía dollar bar e alimentava `features`/
`labels` a partir dela antes deste módulo; o único código que já construía
dollar bar (`src.analysis.m2_worker`) é medição pós-hoc, fora do contrato de
camada (`data não importa analysis`, `pyproject.toml::[tool.importlinter]`).
Este módulo é a peça mínima de `src/data/` que fecha essa lacuna — o
suficiente para PROVAR A FIAÇÃO ponta a ponta (calibrar -> construir ->
escrever -> ler -> alimentar `features.build.build_t1_features`), não para
decidir a calibração congelada de produção nem para reprocessar o histórico
inteiro em escala.

**Escopo desta leva, explícito (autocrítica registrada em sessão, não
decisão silenciosa):**

1. **3 resoluções, `"R1"`/`"R2"`/`"R3"`** — equivalentes aos antigos
   baselines de 15m/30m/1h de M2 (`m2_worker.RESOLUTION_ID_BY_TF`,
   duplicado aqui como `CALIBRATION_TF_BY_RESOLUTION` porque `src.data`
   não pode importar `src.analysis`). Remediação de M1 (`AG-036`) exige
   as 3, não só R1 — R2/R3 adicionadas em 2026-08-17 (histórico: só R1
   existia até então, ver `git log -- src/data/build_dollar_bars.py`).
2. **`calibration_scope` é sempre `"validation"`, NUNCA `"frozen_
   production"`.** O threshold é calibrado sobre a MESMA janela sendo
   validada — decidir uma calibração congelada pra produção real (que
   janela usar, com que cadência recalibrar) é decisão de negócio do
   Manager ainda não tomada (AG-042, itens 2/3, continuam deferidos). Este
   módulo nunca escreve `"frozen_production"` em `DollarBarCalibration.
   calibration_scope` — só `calibrate_dollar_threshold_for_validation`
   constrói o objeto, e ela é literal nisso.
3. **Sem checkpoint incremental** — `write_dollar_bars_and_calibration`
   escreve tudo de uma vez, no fim; não é retomável entre execuções. Janela
   pequena (dias a poucos meses) não precisa disso; resumabilidade fica
   pra quando o reprocessamento real de produção em escala completa
   (histórico inteiro, todos os símbolos) for decidido — fora de escopo
   aqui.
4. **Zero treino de modelo, zero consumo de `N_lifetime`.** O que sai de
   `build_t1_features(..., bar_source="dollar_r1")` sobre essas barras é
   conferência de shape/sanidade de `DataFrame`, não uma rodada de Alpha.

**Isto é teste de FIAÇÃO, não de validade estatística.** `AG-043`
(`sqrt(window)` em `src.features.support.realized_vol`, gap overnight do
estimador Yang-Zhang, defasagem do asof-join OI/funding) continua
DELIBERADAMENTE deferido — os números que saem de `features.build` sobre
dollar bar VÃO RODAR sem crashar, mas não devem ser tratados como
estatisticamente válidos pra treino real até AG-043 ser resolvido.

**AG-124 (2026-08-21) — addendum ao item 2/3 acima, não os invalida.**
`calibrate_dollar_threshold_for_validation` continua calibrando sobre a
MESMA janela sendo validada (item 2 continua verdadeiro PRA ELA) — o
vazamento que isso implica quando `[start, end]` é longo (deriva de 18,18x
medida entre 2020-01 e 2024-03, BTCUSDT,
`experiments/dollar_threshold_drift.json`) é remediado por uma função NOVA,
`build_dollar_bars_walkforward`, que reusa `calibrate_dollar_threshold_for_
validation`/`build_dollar_bars_for_window` SEM modificá-las, só trocando o
argumento de janela por período — ela SIM tem checkpoint incremental (item
3 acima descrevia só `write_dollar_bars_and_calibration` isolada, que
continua não-transacional dentro de 1 chamada, mas agora é chamada 1x por
período, não 1x pro range inteiro). Continua NÃO sendo a decisão de
calibração congelada de produção — `cadence_days`/`trailing_window_days`
são parâmetros obrigatórios do caller, nunca um default embutido aqui (ver
`build_dollar_bars_walkforward`)."""

from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import orjson
import polars as pl
import structlog

from . import _chunked_scan, bars, lake
from ._constants import load_constant
from ._paths import CAPACITY_DIR

logger = structlog.get_logger(__name__)

#: Resoluções suportadas de dollar bar, mapeadas ao TF de calibração --
#: equivalente a `m2_worker.RESOLUTION_ID_BY_TF` invertido, duplicado aqui
#: (não importado) porque `src.data` não pode importar `src.analysis`
#: (contrato `importlinter` "data não importa analysis").
CALIBRATION_TF_BY_RESOLUTION: Final[dict[str, str]] = {
    "R1": "15m",
    "R2": "30m",
    "R3": "1h",
}

#: Resolução default pros callers que não passam `resolution_id`
#: explicitamente -- mantido por compatibilidade (import existente em
#: `src.analysis.volatility_comparison`).
RESOLUTION_ID: Final[str] = "R1"

#: `DollarBarCalibration.calibration_scope` -- ver docstring do módulo,
#: item 2. O único valor que este módulo escreve; `"frozen_production"`
#: nunca aparece aqui (decisão de negócio não tomada, AG-042 itens 2/3).
CALIBRATION_SCOPE_VALIDATION: Final[str] = "validation"

#: `WalkforwardCalibrationIdentity.calibration_scope` (AG-124, 2026-08-21)
#: -- distinto de `CALIBRATION_SCOPE_VALIDATION`: o threshold NÃO é
#: calibrado sobre a mesma janela sendo construída (isso seria o vazamento
#: medido em AG-124), é calibrado sobre `[app_start - trailing_window_days,
#: app_start)`, estritamente anterior a cada período de aplicação --
#: "causal" no sentido estrito de "nunca olha pra frente". Ainda NÃO é
#: `"frozen_production"` (decisão de negócio de congelar UM threshold pra
#: produção continua não tomada, AG-042 itens 2/3) -- é só a família de
#: calibração usada por `build_dollar_bars_walkforward`.
CALIBRATION_SCOPE_WALKFORWARD_CAUSAL: Final[str] = "walkforward_causal"

#: Versão do "schema" de identidade de recalibração rolante -- entra no
#: hash (`WalkforwardCalibrationIdentity.config_hash`) pra que uma mudança
#: futura no ALGORITMO de recalibração (não só nos parâmetros) invalide o
#: hash mesmo com os mesmos `trailing_window_days`/`cadence_days`. Mesmo
#: papel que `schema_version` já cumpre em outras identidades hasheadas do
#: projeto -- incrementar manualmente se a fórmula de `_trailing_window`/
#: a ordem de iteração de período mudar de um jeito que reprocessamento
#: silencioso seria incorreto.
_WALKFORWARD_CALIBRATION_SCHEMA_VERSION: Final[int] = 1

_CALIBRATION_FILENAME: Final[str] = "_calibration.json"


def _source_name(resolution_id: str) -> str:
    """`dollar_bars_r1`/`dollar_bars_r2`/`dollar_bars_r3` -- nome do
    dataset em `data/capacity/{name}/{symbol}/*.parquet`, um por
    resolução (mesmo padrão de `schemas._dollar_bars_schema`)."""
    return f"dollar_bars_{resolution_id.lower()}"


@dataclass(frozen=True, slots=True)
class DollarBarCalibration:
    """Metadado de calibração de UMA janela de validação de dollar bar --
    persistido ao lado das barras (`write_dollar_bars_and_calibration`,
    `.../{symbol}/_calibration.json`) pra que ninguém leia `dollar_bars_r1`
    sem saber sob qual `threshold_usdt`/janela ele foi calibrado.

    `max_leftover_trades` (achado de revisão pessoal, 2026-08-16, ao ler
    este módulo depois de implementado): mesma fórmula de
    `m2_worker._max_leftover_trades` (`n_trades/target_n_bars *
    bars_threshold_leftover_safety_multiplier`) -- o circuit breaker de
    `ThresholdBarsCarry.leftover` (`AG-034` addendum, achado MEDIUM) existe
    exatamente pra proteger um runner como este, que chama
    `threshold_bars_step` de verdade sobre `aggTrades` real. Ficar de fora
    aqui seria deixar a proteção só em M2, não no primeiro caller de
    produção-adjacente que de fato existe. `None` só se `target_n_bars`
    não puder ser derivado (não deveria acontecer no caminho real, ver
    `calibrate_dollar_threshold_for_validation` -- sempre popula)."""

    symbol: str
    resolution_id: str  # "R1"/"R2"/"R3" -- ver CALIBRATION_TF_BY_RESOLUTION
    threshold_usdt: float
    calibration_scope: str  # sempre "validation" aqui -- NUNCA "frozen_production"
    calibration_window_start: str
    calibration_window_end: str
    n_trades: int
    calibrated_at: str  # datetime.now(UTC).isoformat()
    max_leftover_trades: float | None = None


@dataclass(frozen=True, slots=True)
class WalkforwardCalibrationIdentity:
    """Metadado persistido ao lado das barras (`write_dollar_bars_and_
    calibration`, `.../{symbol}/_calibration.json`) quando o diretório é
    construído por `build_dollar_bars_walkforward` (AG-124, 2026-08-21) --
    NÃO por `calibrate_dollar_threshold_for_validation`/`DollarBarCalibration`
    (essa continua existindo inalterada, para o caminho de janela única).

    **Por que não é `DollarBarCalibration` com um campo a mais.** Sob
    recalibração rolante, `threshold_usdt` varia por PERÍODO de aplicação
    (`build_dollar_bars_walkforward` chama `write_dollar_bars_and_
    calibration` uma vez por período, todos gravando no MESMO diretório de
    símbolo) — um único escalar `threshold_usdt` por `_calibration.json`
    deixou de fazer sentido (é exatamente por isso que `threshold_quote`
    passa a viver EM CADA BARRA, ver `schemas._DOLLAR_BARS_COLUMNS`). Este
    objeto documenta a RECEITA do algoritmo (janela causal em dias,
    cadência, `resolution_id`) — invariante entre períodos de uma mesma
    rodada, então gravá-lo de novo a cada período é idempotente, nunca um
    "threshold divergente" (a guarda que rejeitava isso foi removida de
    `write_dollar_bars_and_calibration` exatamente porque deixou de haver
    uma noção de "o" threshold do diretório).

    `config_hash` é a MESMA fórmula de `src.labels.triple_barrier.
    LabelConfig.config_hash` (sha256 truncado a 16 hex, `orjson.dumps(...,
    OPT_SORT_KEYS)`) sobre os 5 campos que definem o algoritmo —
    `LabelConfig.bars_calibration_hash` (AG-124, mesmo achado) é populado
    com este valor pelo caller que sabe qual recalibração gerou as barras
    consumidas."""

    symbol: str
    resolution_id: str  # "R1"/"R2"/"R3" -- ver CALIBRATION_TF_BY_RESOLUTION
    trailing_window_days: int
    cadence_days: int
    calibration_scope: str = CALIBRATION_SCOPE_WALKFORWARD_CAUSAL
    schema_version: int = _WALKFORWARD_CALIBRATION_SCHEMA_VERSION

    @property
    def config_hash(self) -> str:
        payload = {
            "resolution_id": self.resolution_id,
            "symbol": self.symbol,
            "trailing_window_days": self.trailing_window_days,
            "cadence_days": self.cadence_days,
            "schema_version": self.schema_version,
        }
        blob = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
        return hashlib.sha256(blob).hexdigest()[:16]


def calibrate_dollar_threshold_for_validation(
    symbol: str, start: str, end: str, *, resolution_id: str = RESOLUTION_ID
) -> DollarBarCalibration:
    """Calibra `threshold_usdt` pra `[start, end]` -- MESMA fórmula que
    `src.analysis.m2_worker.compute_trades_dependent_bars_for_symbol_tf`
    usa (`threshold = totals.total_dollar / target_n_bars`, baseline de
    `klines_1m` no TF de calibração de `resolution_id` --
    `CALIBRATION_TF_BY_RESOLUTION` -- pro `target_n_bars`), reusando as
    funções movidas de lá em 2026-08-16 (`src.data._chunked_scan`) -- não
    reimplementada. `calibration_scope` sai sempre `"validation"` (ver
    docstring do módulo)."""
    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:
        raise ValueError(
            f"resolution_id={resolution_id!r} não suportado -- esperado um de "
            f"{sorted(CALIBRATION_TF_BY_RESOLUTION)}"
        )
    calibration_tf = CALIBRATION_TF_BY_RESOLUTION[resolution_id]
    chunk_days = int(load_constant("bars_streaming_chunk_days"))
    chunks = _chunked_scan.date_chunks(start, end, chunk_days=chunk_days)

    totals = _chunked_scan.scan_trades_totals(symbol, calibration_tf, chunks)
    if totals.n_ticks == 0:
        raise ValueError(
            f"aggTrades vazio para {symbol} no período {start}..{end} -- não dá pra "
            "calibrar dollar bar de validação sem trades"
        )

    baseline = _chunked_scan.query_baseline(symbol, calibration_tf, start=start, end=end)
    n_bars = _chunked_scan.target_n_bars(symbol, calibration_tf, baseline, start=start, end=end)
    threshold_usdt = totals.total_dollar / n_bars  # noqa: unguarded-ratio -- target_n_bars levanta ValueError se <=0

    # Mesma fórmula/constante de `m2_worker._max_leftover_trades` -- ver
    # docstring de `DollarBarCalibration.max_leftover_trades`. `n_bars`
    # (target_n_bars) já validado > 0 acima (a divisão de threshold_usdt
    # não teria rodado se não fosse).
    avg_trades_per_bar = float(totals.n_ticks) / n_bars  # noqa: unguarded-ratio -- n_bars>0, ver acima
    safety_mult = float(load_constant("bars_threshold_leftover_safety_multiplier"))
    if safety_mult <= 0:
        raise ValueError(
            "bars_threshold_leftover_safety_multiplier precisa ser > 0, constants.yaml tem "
            f"{safety_mult}"
        )
    max_leftover_trades = avg_trades_per_bar * safety_mult

    calibration = DollarBarCalibration(
        symbol=symbol,
        resolution_id=resolution_id,
        threshold_usdt=threshold_usdt,
        calibration_scope=CALIBRATION_SCOPE_VALIDATION,
        calibration_window_start=start,
        calibration_window_end=end,
        n_trades=totals.n_ticks,
        calibrated_at=datetime.now(UTC).isoformat(),
        max_leftover_trades=max_leftover_trades,
    )
    logger.info(
        "data.build_dollar_bars.calibrated",
        symbol=symbol,
        resolution_id=resolution_id,
        start=start,
        end=end,
        threshold_usdt=threshold_usdt,
        n_trades=totals.n_ticks,
        n_bars=n_bars,
        max_leftover_trades=max_leftover_trades,
    )
    return calibration


def build_dollar_bars_for_window(
    symbol: str,
    start: str,
    end: str,
    *,
    threshold_usdt: float,
    max_leftover_trades: float | None = None,
) -> pl.DataFrame:
    """Constrói dollar bars pra `[start, end]` via streaming
    (`lake.query_agg_trades` em chunks de `date_chunks`) -- chama SÓ
    `bars.dollar_bars_carry`/`bars.threshold_bars_step`/`bars.
    threshold_bars_finish` (`src.data.bars`), NUNCA o helper de 3 tipos de
    `m2_worker.py` (`_build_trades_dependent_bars`) -- exatamente o que o
    contrato `importlinter` "data não importa analysis" já impede de
    acontecer por acidente. Log estruturado por chunk (mesmo padrão de
    `_chunked_scan.scan_trades_totals`/`m2_worker._build_trades_dependent_
    bars`): `n_trades`, `leftover_trade_count` do carry.

    `max_leftover_trades` (achado de revisão pessoal, ver docstring de
    `DollarBarCalibration.max_leftover_trades`) -- default `None` preserva
    bit-exato quem chama sem esse argumento (callers de teste existentes);
    `main()`/o caminho real sempre passa `calibration.max_leftover_trades`."""
    chunk_days = int(load_constant("bars_streaming_chunk_days"))
    chunks = _chunked_scan.date_chunks(start, end, chunk_days=chunk_days)
    throttle = _chunked_scan.duckdb_throttle()
    carry = bars.dollar_bars_carry(
        threshold=threshold_usdt, max_leftover_trades=max_leftover_trades
    )

    n_chunks = len(chunks)
    for i, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        chunk = lake.query_agg_trades(
            symbol,
            chunk_start,
            chunk_end,
            duckdb_memory_limit_gb=throttle.memory_limit_gb,
            duckdb_threads=throttle.threads,
        )
        if not chunk.is_empty():
            bars.threshold_bars_step(carry, chunk)
        logger.info(
            "data.build_dollar_bars.chunk_done",
            symbol=symbol,
            chunk=i,
            n_chunks=n_chunks,
            chunk_start=str(chunk_start),
            chunk_end=str(chunk_end),
            n_trades=chunk.height,
            leftover_trade_count=carry.leftover_trade_count,
        )

    result = bars.threshold_bars_finish(carry)
    logger.info(
        "data.build_dollar_bars.built",
        symbol=symbol,
        start=start,
        end=end,
        threshold_usdt=threshold_usdt,
        n_bars=result.height,
    )
    return result


def _build_dollar_bars_for_period_carried(
    symbol: str,
    start: str,
    end: str,
    *,
    carry: bars.ThresholdBarsCarry,
) -> pl.DataFrame:
    """Mesmo loop de chunks de `build_dollar_bars_for_window`, mas reusa um
    `ThresholdBarsCarry` já existente (caller já setou `carry.threshold`/
    `carry.max_leftover_trades` pro período atual antes de chamar) e NUNCA
    fecha o stream (`bars.threshold_bars_drain`, não `threshold_bars_
    finish`) -- usado só por `build_dollar_bars_walkforward` (AG-124/item
    14) pra manter `leftover`/`base_value` vivos através da fronteira de
    período, em vez de cada período fechar sua própria barra final
    truncada.

    Duplica ~15 linhas do loop de chunks de `build_dollar_bars_for_window`
    deliberadamente -- generalizar uma função pra servir os dois contratos
    (cria-carry-e-finish vs. reusa-carry-e-drena) trocaria o tipo de
    retorno de `build_dollar_bars_for_window` (usada por `main()`/CLI e
    testada isoladamente há várias sessões) por algo condicional, maior
    risco que uma duplicação pequena e documentada -- mesmo precedente já
    usado no repo (`_paths.py`/`_constants.py`)."""
    chunk_days = int(load_constant("bars_streaming_chunk_days"))
    chunks = _chunked_scan.date_chunks(start, end, chunk_days=chunk_days)
    throttle = _chunked_scan.duckdb_throttle()

    n_chunks = len(chunks)
    for i, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        chunk = lake.query_agg_trades(
            symbol,
            chunk_start,
            chunk_end,
            duckdb_memory_limit_gb=throttle.memory_limit_gb,
            duckdb_threads=throttle.threads,
        )
        if not chunk.is_empty():
            bars.threshold_bars_step(carry, chunk)
        logger.info(
            "data.build_dollar_bars.period_carried_chunk_done",
            symbol=symbol,
            chunk=i,
            n_chunks=n_chunks,
            chunk_start=str(chunk_start),
            chunk_end=str(chunk_end),
            n_trades=chunk.height,
            leftover_trade_count=carry.leftover_trade_count,
        )

    result = bars.threshold_bars_drain(carry)
    logger.info(
        "data.build_dollar_bars.period_carried_built",
        symbol=symbol,
        start=start,
        end=end,
        threshold_usdt=carry.threshold,
        n_bars=result.height,
    )
    return result


def _split_bars_by_day(bars_df: pl.DataFrame) -> dict[date, pl.DataFrame]:
    """Particiona por dia CALENDÁRIO de `close_time` (não `open_time` --
    `schemas.DOLLAR_BARS_R1.timestamp_column`) -- mesmo padrão de
    `src.data.download._split_klines_by_day` (que particiona `klines_1m`
    por `open_time`, coluna equivalente pro schema de klines)."""
    with_day = bars_df.with_columns(
        pl.from_epoch(pl.col("close_time"), time_unit="ms").dt.date().alias("_day")
    )
    parts = with_day.partition_by("_day", as_dict=True, include_key=False)
    out: dict[date, pl.DataFrame] = {}
    for key, frame in parts.items():
        day = key[0] if isinstance(key, tuple) else key
        out[day] = frame
    return out


def _write_parquet_atomic(df: pl.DataFrame, dest_path: Path) -> None:
    """B29 — mesmo padrão exato de `src.regime.build.write_regimes_atomic`
    (`pl.write_parquet` não expõe o file handle usado internamente, então o
    `fsync` reabre o `.tmp` recém-escrito por descritor)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    df.write_parquet(tmp_path, compression="zstd")
    fd = os.open(tmp_path, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp_path, dest_path)


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 — mesmo padrão de `src.analysis.m2_bar_comparison._atomic_write_
    json` (não reusado por import: `data não importa analysis`)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)


def write_dollar_bars_and_calibration(
    bars_df: pl.DataFrame,
    calibration: DollarBarCalibration | WalkforwardCalibrationIdentity,
    *,
    dest_root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Escreve `bars_df` particionado por dia calendário de `close_time`
    (`(dest_root ou CAPACITY_DIR)/dollar_bars_r1/{symbol}/{yyyy-mm-dd}.
    parquet`, B29) + `calibration` como JSON atômico no mesmo diretório
    (`_calibration.json`). Retorna um dict com todos os caminhos escritos
    (`{"YYYY-MM-DD": Path, ..., "calibration": Path}`).

    **AG-124 (2026-08-21) — guarda de threshold divergente REMOVIDA.** Até
    esta mudança, se `_calibration.json` já existisse com `threshold_usdt`
    DIFERENTE do que estava sendo escrito agora, a função levantava
    `ValueError` antes de escrever qualquer arquivo, a menos que
    `overwrite=True` fosse passado — desenhada para um cenário onde
    `threshold_usdt` é um ÚNICO escalar imutável por diretório de símbolo.
    Isso deixou de ser verdade com `build_dollar_bars_walkforward`: cada
    período de aplicação é calibrado com um threshold PRÓPRIO (recalibração
    causal rolante, AG-124) e todos os períodos de uma mesma rodada
    escrevem no MESMO diretório — múltiplas chamadas com `threshold_usdt`
    divergente entre si são agora o caminho ESPERADO, não um erro a
    prevenir. A proteção contra misturar séries incompatíveis não
    desapareceu — migrou para dado: `threshold_quote` (Camada 0,
    `schemas._DOLLAR_BARS_COLUMNS`) faz cada BARRA carregar o threshold que
    a fechou, então "qual threshold gerou esta barra" é uma pergunta que o
    parquet responde sozinho, sem depender de um único escalar em
    `_calibration.json` nem de uma guarda em tempo de escrita.
    `_calibration.json`, quando `calibration` é `WalkforwardCalibrationIdentity`,
    passa a registrar a IDENTIDADE do algoritmo de recalibração (janela
    causal, cadência, `resolution_id`) — invariante entre períodos da mesma
    rodada, então sobrescrevê-lo a cada chamada é idempotente, nunca perda
    de informação (ver docstring de `WalkforwardCalibrationIdentity`).

    `overwrite=True` continua existindo e com o mesmo efeito de antes —
    TODOS os `*.parquet` já presentes no diretório do símbolo são apagados
    ANTES de escrever o conjunto novo (achado MEDIUM de revisão
    independente, `project_assurance`, 2026-08-16: protege contra dias
    órfãos de uma rodada anterior ficarem silenciosamente misturados com o
    conjunto novo). Continua sendo o mecanismo certo para "começar do zero"
    (ex.: re-rodar `build_dollar_bars_walkforward` inteiro sobre o mesmo
    diretório) — só a guarda de MISMATCH entre chamadas sem `overwrite` foi
    removida, não o `overwrite` em si.

    **Não é transacional.** Cada arquivo individual é atômico (B29), mas
    a operação inteira não é -- um crash no meio do loop de dias sob
    `overwrite=True` pode deixar o diretório com um subconjunto dos dias
    novos e `_calibration.json` ainda não reescrito (ele é escrito por
    último). Aceitável no escopo desta leva (rodada manual, um operador,
    janela pequena) -- se isso acontecer, apague `{symbol_dir}` inteiro e
    rode de novo em vez de tentar consertar o estado parcial à mão.
    Também sem lock entre processos (TOCTOU entre ler `_calibration.json`
    e escrever) -- aceitável pelo mesmo motivo, não seguro pra execução
    paralela do mesmo símbolo."""
    root = dest_root if dest_root is not None else CAPACITY_DIR
    symbol_dir = root / _source_name(calibration.resolution_id) / calibration.symbol
    calibration_path = symbol_dir / _CALIBRATION_FILENAME

    if overwrite and symbol_dir.is_dir():
        for stale in symbol_dir.glob("*.parquet"):
            stale.unlink()

    written: dict[str, Path] = {}
    for day, day_df in sorted(_split_bars_by_day(bars_df).items()):
        dest_path = symbol_dir / f"{day.isoformat()}.parquet"
        _write_parquet_atomic(day_df, dest_path)
        written[day.isoformat()] = dest_path

    _atomic_write_json(asdict(calibration), calibration_path)
    written["calibration"] = calibration_path

    logger.info(
        "data.build_dollar_bars.written",
        symbol=calibration.symbol,
        n_days=len(written) - 1,
        calibration_scope=calibration.calibration_scope,
        # `threshold_usdt` só existe em DollarBarCalibration (janela única) --
        # WalkforwardCalibrationIdentity não tem "o" threshold do diretório
        # (ver docstring, AG-124); getattr com default preserva o log de
        # sempre pro caminho antigo sem quebrar pro caminho novo.
        threshold_usdt=getattr(calibration, "threshold_usdt", None),
        dest_dir=str(symbol_dir),
    )
    return written


# ============================================================================
# build_dollar_bars_walkforward -- orquestrador de recalibração rolante
# CAUSAL (AG-124, 2026-08-21). Camada 1 da remediação do vazamento medido em
# `calibrate_dollar_threshold_for_validation` (threshold calibrado sobre a
# MESMA janela sendo construída -- deriva de 18,18x medida entre 2020-01 e
# 2024-03, BTCUSDT, `experiments/dollar_threshold_drift.json`). NÃO chamada
# contra dado real de produção nesta leva (autorização explícita do Manager
# limitada a código testado + medição mensal, reprocessamento real fica pra
# um "go" separado).
# ============================================================================


@dataclass(frozen=True, slots=True)
class WalkforwardPeriodResult:
    """1 período de aplicação dentro de `build_dollar_bars_walkforward` --
    resultado estruturado por período (mesmo padrão de `LabelBuildStats`,
    `src.labels.triple_barrier`, AG-128), não só um `DataFrame` anônimo
    perdido dentro do loop.

    `threshold_usdt`/`written` são `None` sse `is_cold_start=True` -- o 1º
    período de cada chamada nunca é calibrado nem construído (ver docstring
    de `build_dollar_bars_walkforward`)."""

    app_start: str
    app_end: str
    is_cold_start: bool
    threshold_usdt: float | None
    n_bars: int
    written: dict[str, Path] | None


@dataclass(frozen=True, slots=True)
class WalkforwardBarsStats:
    """Resumo estruturado de 1 rodada de `build_dollar_bars_walkforward` --
    mesmo padrão de `LabelBuildStats` (`src.labels.triple_barrier`, AG-128):
    contadores que o caller loga/persiste sem precisar reconstruir a rodada
    inteira pra saber quantos períodos foram cold-start."""

    symbol: str
    resolution_id: str
    trailing_window_days: int
    cadence_days: int
    n_periods: int
    n_cold_start_dropped: int
    n_periods_written: int
    calibration_identity: WalkforwardCalibrationIdentity
    periods: tuple[WalkforwardPeriodResult, ...]


def _trailing_calibration_window(app_start: str, *, trailing_window_days: int) -> tuple[str, str]:
    """Janela de calibração ESTRITAMENTE anterior a `app_start` (AG-124) --
    `[app_start - trailing_window_days, app_start - 1 dia]`, ambos
    inclusive (mesma convenção ISO-date inclusive de `calibrate_dollar_
    threshold_for_validation`/`_chunked_scan.date_chunks`). NUNCA inclui
    `app_start` em diante -- fazer isso seria reproduzir o vazamento medido
    em AG-124 (threshold calibrado sobre a mesma janela sendo construída),
    não corrigi-lo."""
    app_start_date = date.fromisoformat(app_start)
    calib_end = app_start_date - timedelta(days=1)
    calib_start = app_start_date - timedelta(days=trailing_window_days)
    return calib_start.isoformat(), calib_end.isoformat()


def build_dollar_bars_walkforward(
    symbol: str,
    start: str,
    end: str,
    *,
    resolution_id: str,
    trailing_window_days: int,
    cadence_days: int,
    dest_root: Path | None = None,
) -> WalkforwardBarsStats:
    """Recalibração rolante CAUSAL de `threshold_usdt` (AG-124) -- em vez de
    UM threshold pra `[start, end]` inteiro (o vazamento medido: o
    threshold "sabe" o volume do fim da janela ao fechar barras do início),
    particiona `[start, end]` em períodos de aplicação de `cadence_days`
    dias cada (`_chunked_scan.date_chunks`, REUSADA sem modificação -- mesma
    primitiva de particionamento já usada por `calibrate_dollar_threshold_
    for_validation`/M2, não uma segunda implementação) e calibra CADA
    período só sobre os `trailing_window_days` dias ESTRITAMENTE ANTERIORES
    a ele (`_trailing_calibration_window`), via `calibrate_dollar_threshold_
    for_validation` REUSADA sem modificação (só o argumento de janela
    muda). Constrói cada período via `build_dollar_bars_for_window`
    REUSADA sem modificação.

    `trailing_window_days`/`cadence_days` são OBRIGATÓRIOS (sem default,
    B23 -- CLAUDE.md "não invente faixas/números") -- qual valor minimiza
    deriva dentro de cada vintage é decisão do Manager, informada pelo
    relatório mensal de deriva (`tools/diagnostics/measure_dollar_
    threshold_drift_monthly.py`), não algo pra inventar aqui.

    **Lead-in buffer -- todo período TENTA ser calibrado, mesmo o 1º
    (AG-124/item 15, 2026-08-21, corrige o desenho original).** A janela
    de calibração de qualquer período pode cair ANTES de `start` (`_
    trailing_calibration_window`) -- isso é permitido: só a leitura de
    TRADES pra calibração pode olhar antes de `start` (histórico real do
    símbolo no lake), a escrita de BARRAS continua estritamente dentro de
    `[start, end]`. O desenho original (até 2026-08-21) descartava o 1º
    período incondicionalmente, mesmo quando havia trade real disponível
    antes de `start` pra calibrá-lo -- descartava ~1 semana real por
    símbolo sem necessidade (medido: recuperável sem violar causalidade,
    já que ler ANTES de `t` pra decidir o threshold de `t` continua sendo
    só passado). Um período só é descartado (cold-start) quando não existe
    trade NENHUM no lake pra sua janela de calibração -- início genuíno de
    histórico do símbolo (ou um gap real de dado no meio da série, tratado
    igual). Mesmo padrão de `n_warmup_dropped` do Label Engine
    (`LabelBuildStats`, AG-128): log estruturado (`walkforward_cold_start_
    dropped`) + contador em `WalkforwardBarsStats.n_cold_start_dropped`,
    NUNCA exceção não-tratada -- é warmup esperado, não erro.

    **`ThresholdBarsCarry` PERSISTE através da fronteira de período
    (AG-124/item 14, 2026-08-21 -- corrige o desenho original desta
    função, que recriava o carry a cada período e fechava/truncava a
    barra em aberto em toda fronteira).** Um único `ThresholdBarsCarry` é
    criado no 1º período real (pós cold-start) e reusado por
    `_build_dollar_bars_for_period_carried` em todos os períodos
    seguintes -- só `threshold`/`max_leftover_trades` são atualizados por
    período (a nova calibração), `leftover`/`base_value` continuam vivos.
    `threshold_bars_drain` (não `finish`) é chamado a cada período --
    devolve as barras fechadas, sem tocar o leftover em aberto. Só o
    ÚLTIMO período chama `threshold_bars_finish` (flush final, concatenado
    ao `bars_df` desse período antes de escrever) -- resultado: **1 barra
    subdimensionada por rodada inteira** (símbolo × resolução), não 1 por
    período. Sob `cadence_days=1`, isso é a diferença entre ~365
    fronteiras truncadas/ano (desenho original) e ~1 barra parcial no fim
    de todo o range medido (achado de auditoria externa 2026-08-21,
    `docs/plano_acao_ag124_pos_auditoria_2026-08-21.md` item 14 -- pré-
    condição pra `T=7,C=1`, ver `AG-124` addendum de desacoplamento).
    Pico de memória continua limitado (leftover é só o "resto" de UMA
    barra em aberto, nunca o histórico `[start, end]` inteiro) -- o que
    mudou é só o fechamento/truncamento por período, não o volume de dado
    retido.

    **Semântica de troca de threshold com barra em aberto -- formalizada
    aqui (AG-124, 2026-08-21), antes tratada como "não trivial"/
    implicitamente indefinida em discussão de auditoria externa.**
    `carry.threshold` muda a cada período (linha ~770 abaixo) ENQUANTO o
    carry pode já conter `leftover` do período anterior -- comportamento
    determinístico, verificado em teste
    (`tests/unit/test_data_bars.py::
    test_threshold_bars_drain_sobrevive_a_troca_de_threshold_entre_periodos`),
    não mais "undefined":

    1. `cum_value` (valor bruto acumulado desde a criação do carry) NUNCA
       reseta na troca de threshold -- só o DIVISOR (`threshold`) muda.
    2. `bar_id = cum_value // threshold` é recalculado do zero a cada
       `threshold_bars_step`, usando o `threshold` ATUAL -- ou seja, a
       troca de threshold REINTERPRETA retroativamente todo o `leftover`
       acumulado sob o threshold ANTERIOR, não só o valor futuro.
    3. Consequência prática: um trade "em progresso" rumo ao threshold
       ANTIGO pode fechar como sua própria barra, menor que o threshold
       NOVO, assim que o primeiro trade do período seguinte chega e
       `cum_value` cruza um múltiplo do threshold novo. Nenhum trade é
       perdido ou duplicado (conservação de valor provada no teste) -- só
       a fronteira exata de onde uma barra fecha pode mudar em função de
       QUANDO a recalibração acontece, não só de QUANTO volume real
       ocorreu.
    4. Isto acontece 1x por período não-inicial -- `cadence_days` menor
       significa mais recalibrações, logo mais vezes que este caminho de
       código roda (5x sob `cadence_days=7` vs. 30x sob `cadence_days=1`
       numa janela de 30 dias) -- um caminho de código pouco exercitado
       historicamente (o desenho de janela única, pré-AG-124, nunca trocava
       threshold em produção) rodando proporcionalmente mais sob cadência
       curta. **Efeito estatístico agregado na cauda de distribuição de
       retornos de barra permanece objeto de investigação aberta** --
       ver `docs/plano_acao_ag124_pos_auditoria_2026-08-21.md` §11/§12: uma
       medição real encontrou concentração de retornos extremos numa janela
       estreita (~1h) em torno de 00:00 UTC, mais pronunciada sob
       `cadence_days=1`, mas descartou microestrutura de funding genérica
       como explicação única (não há excesso comparável às 08h/16h UTC,
       outros horários de funding da Binance) -- causa raiz exata (dado vs.
       algoritmo vs. mercado) NÃO isolada, tratar como achado confundido,
       não como propriedade estabelecida de `cadence_days` curto.

    **Checkpoint incremental.** Cada período (exceto cold-start) é escrito
    via `write_dollar_bars_and_calibration` (guarda de mismatch já removida,
    Camada 0) assim que construído -- não acumula todos os períodos em
    memória antes de escrever. A `calibration` passada é sempre a MESMA
    `WalkforwardCalibrationIdentity` (não `DollarBarCalibration`) em toda
    chamada desta rodada -- escrevê-la de novo a cada período é idempotente
    (mesmo conteúdo), nunca um "threshold divergente" (ver docstring da
    classe). O `threshold_usdt` de CADA período vive em `threshold_quote`,
    por barra (Camada 0) -- não em `_calibration.json`."""
    if trailing_window_days <= 0:
        raise ValueError(
            f"trailing_window_days precisa ser > 0, recebido {trailing_window_days}"
        )
    if cadence_days <= 0:
        raise ValueError(f"cadence_days precisa ser > 0, recebido {cadence_days}")
    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:
        raise ValueError(
            f"resolution_id={resolution_id!r} não suportado -- esperado um de "
            f"{sorted(CALIBRATION_TF_BY_RESOLUTION)}"
        )

    identity = WalkforwardCalibrationIdentity(
        symbol=symbol,
        resolution_id=resolution_id,
        trailing_window_days=trailing_window_days,
        cadence_days=cadence_days,
    )

    period_chunks = _chunked_scan.date_chunks(start, end, chunk_days=cadence_days)
    n_periods = len(period_chunks)
    results: list[WalkforwardPeriodResult] = []
    n_cold_start_dropped = 0
    carry: bars.ThresholdBarsCarry | None = None

    for i, (period_start, period_end) in enumerate(period_chunks):
        app_start = period_start.isoformat()
        app_end = period_end.isoformat()

        calib_start, calib_end = _trailing_calibration_window(
            app_start, trailing_window_days=trailing_window_days
        )
        try:
            calibration = calibrate_dollar_threshold_for_validation(
                symbol, calib_start, calib_end, resolution_id=resolution_id
            )
        except ValueError:
            # AG-124/item 15 (lead-in buffer, 2026-08-21) -- tenta calibrar
            # TODO período, mesmo quando calib_start cai ANTES de `start`
            # (histórico real do símbolo dentro do lake, nunca fora dele --
            # só fora do range [start,end] que o CALLER pediu pra
            # CONSTRUIR). Antes desta mudança, só o 1º período (i==0) era
            # descartado incondicionalmente, mesmo quando havia trade real
            # disponível antes de `start` pra calibrá-lo -- desenho
            # original tratava "olhar antes de start" como fora do
            # contrato; medição confirmou que isso descartava ~1 semana
            # real por símbolo sem necessidade (a leitura de calibração
            # nunca escreve barra fora de [start,end], só LÊ trade de antes
            # pra calibrar o 1º período real). Só cai neste except quando
            # não há trade NENHUM no lake pra [calib_start, calib_end] --
            # início genuíno de histórico do símbolo (usualmente só possível
            # no 1º período; um gap real no meio do histórico também cai
            # aqui, tratado da mesma forma -- warmup descartável, não erro).
            n_cold_start_dropped += 1
            logger.info(
                "data.build_dollar_bars.walkforward_cold_start_dropped",
                symbol=symbol,
                resolution_id=resolution_id,
                app_start=app_start,
                app_end=app_end,
                calib_start=calib_start,
                calib_end=calib_end,
                trailing_window_days=trailing_window_days,
                reason=(
                    "sem trade algum no lake para [calib_start, calib_end] -- "
                    "início real de histórico do símbolo (ou gap real de dado) "
                    "dentro da janela de calibração; warmup descartável, mesmo "
                    "padrão de n_warmup_dropped (LabelBuildStats, AG-128)"
                ),
            )
            results.append(
                WalkforwardPeriodResult(
                    app_start=app_start,
                    app_end=app_end,
                    is_cold_start=True,
                    threshold_usdt=None,
                    n_bars=0,
                    written=None,
                )
            )
            continue

        if carry is None:
            carry = bars.dollar_bars_carry(
                threshold=calibration.threshold_usdt,
                max_leftover_trades=calibration.max_leftover_trades,
            )
        else:
            carry.threshold = calibration.threshold_usdt
            carry.max_leftover_trades = calibration.max_leftover_trades

        bars_df = _build_dollar_bars_for_period_carried(
            symbol, app_start, app_end, carry=carry
        )

        is_last_period = i == n_periods - 1
        if is_last_period:
            # Único ponto da rodada inteira que fecha o stream (AG-124/item
            # 14) -- flush do leftover em aberto vira 1 barra parcial,
            # concatenada ao bars_df deste período antes de escrever, em
            # vez de cada período truncar a própria barra final.
            final_leftover_df = bars.threshold_bars_finish(carry)
            if not final_leftover_df.is_empty():
                bars_df = pl.concat([bars_df, final_leftover_df])

        written = write_dollar_bars_and_calibration(bars_df, identity, dest_root=dest_root)

        results.append(
            WalkforwardPeriodResult(
                app_start=app_start,
                app_end=app_end,
                is_cold_start=False,
                threshold_usdt=calibration.threshold_usdt,
                n_bars=bars_df.height,
                written=written,
            )
        )
        logger.info(
            "data.build_dollar_bars.walkforward_period_done",
            symbol=symbol,
            resolution_id=resolution_id,
            period=i + 1,
            n_periods=n_periods,
            app_start=app_start,
            app_end=app_end,
            calibration_window_start=calib_start,
            calibration_window_end=calib_end,
            threshold_usdt=calibration.threshold_usdt,
            n_bars=bars_df.height,
        )

    n_periods_written = n_periods - n_cold_start_dropped
    stats = WalkforwardBarsStats(
        symbol=symbol,
        resolution_id=resolution_id,
        trailing_window_days=trailing_window_days,
        cadence_days=cadence_days,
        n_periods=n_periods,
        n_cold_start_dropped=n_cold_start_dropped,
        n_periods_written=n_periods_written,
        calibration_identity=identity,
        periods=tuple(results),
    )
    logger.info(
        "data.build_dollar_bars.walkforward_done",
        symbol=symbol,
        resolution_id=resolution_id,
        n_periods=n_periods,
        n_cold_start_dropped=n_cold_start_dropped,
        n_periods_written=n_periods_written,
        calibration_hash=identity.config_hash,
    )
    return stats


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Runner de VALIDAÇÃO de dollar bar canônico. NÃO é a decisão de "
            "calibração congelada de produção (AG-042 itens 2/3 continuam "
            "deferidos); NÃO prova validade estatística (AG-043 continua "
            "pendente) -- ver docstring do módulo. --mode single_window "
            "(default, LEGADO) calibra threshold sobre a MESMA janela sendo "
            "construída -- vazamento de 18,18x medido (AG-124). --mode "
            "walkforward aciona a recalibração causal rolante "
            "(build_dollar_bars_walkforward) -- ver AG-138."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--symbol", required=True, help="ex. BTCUSDT")
    parser.add_argument("--start", required=True, help="ISO date, ex. 2026-07-01")
    parser.add_argument("--end", required=True, help="ISO date, ex. 2026-07-07")
    parser.add_argument(
        "--resolution",
        default=RESOLUTION_ID,
        choices=sorted(CALIBRATION_TF_BY_RESOLUTION),
        help="resolution_id da grade dollar-bar -- R1=15m/R2=30m/R3=1h (AG-042)",
    )
    parser.add_argument(
        "--mode",
        default="single_window",
        choices=["single_window", "walkforward"],
        help=(
            "single_window (default, LEGADO): calibra threshold sobre a MESMA "
            "janela [--start, --end] -- vazamento medido de 18,18x, AG-124. "
            "Emite logger.warning ao rodar. walkforward: recalibração causal "
            "rolante (AG-124) -- threshold de cada período calibrado só sobre "
            "dado ESTRITAMENTE anterior a ele; exige --trailing-window-days e "
            "--cadence-days. Ver AG-138."
        ),
    )
    parser.add_argument(
        "--trailing-window-days",
        type=int,
        default=None,
        help=(
            "obrigatório sob --mode walkforward -- dias de histórico ANTES de "
            "cada período de aplicação usados pra calibrar o threshold desse "
            "período (AG-124). Sem default (B23) -- decisão do Manager, "
            "informada pelo relatório mensal de deriva."
        ),
    )
    parser.add_argument(
        "--cadence-days",
        type=int,
        default=None,
        help=(
            "obrigatório sob --mode walkforward -- tamanho em dias de cada "
            "período de aplicação (recalibração a cada N dias). Sem default "
            "(B23)."
        ),
    )
    parser.add_argument(
        "--dest-root",
        default=None,
        help="default: data/capacity/ (CAPACITY_DIR) -- diretório-raiz de dollar_bars_{r1,r2,r3}/",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "só se aplica a --mode single_window (build_dollar_bars_walkforward "
            "não aceita este parâmetro -- cada período escreve incrementalmente "
            "por desenho). Substitui _calibration.json/*.parquet já existentes "
            "no diretório do símbolo, mesmo com threshold_usdt divergente do "
            "gravado antes -- ver guarda de segurança em "
            "write_dollar_bars_and_calibration."
        ),
    )
    args = parser.parse_args()
    if args.mode == "walkforward" and (
        args.trailing_window_days is None or args.cadence_days is None
    ):
        parser.error(
            "--mode walkforward exige --trailing-window-days e --cadence-days "
            "(AG-124/AG-138 -- sem default, B23)"
        )
    return args


def main() -> None:
    args = _parse_cli_args()
    dest_root = Path(args.dest_root) if args.dest_root is not None else None

    if args.mode == "walkforward":
        stats = build_dollar_bars_walkforward(
            args.symbol,
            args.start,
            args.end,
            resolution_id=args.resolution,
            trailing_window_days=args.trailing_window_days,
            cadence_days=args.cadence_days,
            dest_root=dest_root,
        )
        logger.info(
            "data.build_dollar_bars.done",
            mode="walkforward",
            symbol=args.symbol,
            resolution_id=args.resolution,
            start=args.start,
            end=args.end,
            trailing_window_days=args.trailing_window_days,
            cadence_days=args.cadence_days,
            n_periods=stats.n_periods,
            n_periods_written=stats.n_periods_written,
            n_cold_start_dropped=stats.n_cold_start_dropped,
            calibration_hash=stats.calibration_identity.config_hash,
            dest_root=str(dest_root) if dest_root is not None else str(CAPACITY_DIR),
        )
        return

    logger.warning(
        "data.build_dollar_bars.legacy_non_causal_calibration",
        symbol=args.symbol,
        resolution_id=args.resolution,
        start=args.start,
        end=args.end,
        reason=(
            "--mode single_window calibra threshold sobre a MESMA janela sendo "
            "construída -- vazamento de 18,18x medido entre 2020-01 e 2024-03, "
            "BTCUSDT (AG-124). Uso pretendido: validação pontual de janela curta "
            "(ver docstring do módulo). Para regenerar/estender uma janela real, "
            "use --mode walkforward."
        ),
        alternative="--mode walkforward --trailing-window-days N --cadence-days M",
        see="AG-124, AG-138",
    )

    calibration = calibrate_dollar_threshold_for_validation(
        args.symbol, args.start, args.end, resolution_id=args.resolution
    )
    bars_df = build_dollar_bars_for_window(
        args.symbol,
        args.start,
        args.end,
        threshold_usdt=calibration.threshold_usdt,
        max_leftover_trades=calibration.max_leftover_trades,
    )
    written = write_dollar_bars_and_calibration(
        bars_df, calibration, dest_root=dest_root, overwrite=args.overwrite
    )

    logger.info(
        "data.build_dollar_bars.done",
        mode="single_window",
        symbol=args.symbol,
        resolution_id=args.resolution,
        start=args.start,
        end=args.end,
        n_bars=bars_df.height,
        threshold_usdt=calibration.threshold_usdt,
        n_files=len(written),
        overwrite=args.overwrite,
        dest_root=str(dest_root) if dest_root is not None else str(CAPACITY_DIR),
    )


if __name__ == "__main__":
    main()
