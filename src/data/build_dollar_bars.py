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

1. **1 resolução só, `"R1"`** — equivalente ao antigo baseline de 15m de M2
   (`m2_worker.RESOLUTION_ID_BY_TF["15m"] == "R1"`, duplicado aqui como
   `_CALIBRATION_TF`/`RESOLUTION_ID` porque `src.data` não pode importar
   `src.analysis`). `"R2"`/`"R3"` (30m/1h) ficam fora — não pedidos nesta
   leva.
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
estatisticamente válidos pra treino real até AG-043 ser resolvido."""

from __future__ import annotations

import argparse
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import orjson
import polars as pl
import structlog

from . import _chunked_scan, bars, lake
from ._constants import load_constant
from ._paths import CAPACITY_DIR

logger = structlog.get_logger(__name__)

#: Único par (resolution_id, tf de calibração) suportado nesta leva --
#: equivalente a `m2_worker.RESOLUTION_ID_BY_TF["15m"] == "R1"`, duplicado
#: aqui (não importado) porque `src.data` não pode importar `src.analysis`
#: (contrato `importlinter` "data não importa analysis").
RESOLUTION_ID: Final[str] = "R1"
_CALIBRATION_TF: Final[str] = "15m"

#: `DollarBarCalibration.calibration_scope` -- ver docstring do módulo,
#: item 2. O único valor que este módulo escreve; `"frozen_production"`
#: nunca aparece aqui (decisão de negócio não tomada, AG-042 itens 2/3).
CALIBRATION_SCOPE_VALIDATION: Final[str] = "validation"

_SOURCE_NAME: Final[str] = "dollar_bars_r1"
_CALIBRATION_FILENAME: Final[str] = "_calibration.json"

# Epsilon de comparação float pra guarda de calibração divergente (não é
# constante de domínio -- mesma classe de `src.labels.triple_barrier.
# tolerance = 1e-6` -- literal do §3.8 do PRD, não escolha nova; aqui é só
# "threshold_usdt bate com o já gravado dentro do erro de ponto flutuante").
_CALIBRATION_MISMATCH_REL_TOLERANCE: Final[float] = 1e-9  # noqa: magic-number -- epsilon de comparação float, não constante de domínio


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
    resolution_id: str  # sempre "R1" nesta leva (RESOLUTION_ID)
    threshold_usdt: float
    calibration_scope: str  # sempre "validation" aqui -- NUNCA "frozen_production"
    calibration_window_start: str
    calibration_window_end: str
    n_trades: int
    calibrated_at: str  # datetime.now(UTC).isoformat()
    max_leftover_trades: float | None = None


def calibrate_dollar_threshold_for_validation(
    symbol: str, start: str, end: str
) -> DollarBarCalibration:
    """Calibra `threshold_usdt` pra `[start, end]` -- MESMA fórmula que
    `src.analysis.m2_worker.compute_trades_dependent_bars_for_symbol_tf`
    usa (`threshold = totals.total_dollar / target_n_bars`, baseline de
    `klines_1m` em `tf="15m"` pro `target_n_bars`), reusando as funções
    movidas de lá em 2026-08-16 (`src.data._chunked_scan`) -- não
    reimplementada. `calibration_scope` sai sempre `"validation"` (ver
    docstring do módulo)."""
    chunk_days = int(load_constant("bars_streaming_chunk_days"))
    chunks = _chunked_scan.date_chunks(start, end, chunk_days=chunk_days)

    totals = _chunked_scan.scan_trades_totals(symbol, _CALIBRATION_TF, chunks)
    if totals.n_ticks == 0:
        raise ValueError(
            f"aggTrades vazio para {symbol} no período {start}..{end} -- não dá pra "
            "calibrar dollar bar de validação sem trades"
        )

    baseline = _chunked_scan.query_baseline(symbol, _CALIBRATION_TF, start=start, end=end)
    n_bars = _chunked_scan.target_n_bars(symbol, _CALIBRATION_TF, baseline, start=start, end=end)
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
        resolution_id=RESOLUTION_ID,
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
    calibration: DollarBarCalibration,
    *,
    dest_root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Escreve `bars_df` particionado por dia calendário de `close_time`
    (`(dest_root ou CAPACITY_DIR)/dollar_bars_r1/{symbol}/{yyyy-mm-dd}.
    parquet`, B29) + `calibration` como JSON atômico no mesmo diretório
    (`_calibration.json`). Retorna um dict com todos os caminhos escritos
    (`{"YYYY-MM-DD": Path, ..., "calibration": Path}`).

    **Guarda de segurança real, não cosmética.** Se `_calibration.json` já
    existir com `threshold_usdt` DIFERENTE (tolerância relativa
    `_CALIBRATION_MISMATCH_REL_TOLERANCE`) do que está sendo escrito agora,
    levanta `ValueError` ANTES de escrever qualquer arquivo novo — sem
    isso, rodar a validação 2x com janelas diferentes sobre o mesmo
    `(dest_root, symbol)` misturaria barras calibradas com thresholds
    incompatíveis no mesmo diretório, silenciosamente (um dia calibrado a
    `threshold_A`, outro a `threshold_B`, ambos lidos de volta por
    `lake.query_dollar_bars` como se fossem a mesma série). Passe
    `overwrite=True` se a substituição for intencional -- quando passado,
    TODOS os `*.parquet` já presentes no diretório do símbolo são
    apagados ANTES de escrever o conjunto novo (achado MEDIUM de revisão
    independente, `project_assurance`, 2026-08-16: sem isto, dias órfãos
    de uma janela mais larga calibrada sob outro threshold ficariam
    silenciosamente misturados com o conjunto novo, mesmo com
    `overwrite=True` -- a guarda original só protegia o caminho SEM
    `overwrite`, onde thresholds iguais dentro da tolerância são o único
    jeito de passar, e nesse caso a acumulação entre rodadas É o
    comportamento pretendido, não um bug -- por isso a limpeza acontece
    só no ramo `overwrite=True`, não sempre).

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
    symbol_dir = root / _SOURCE_NAME / calibration.symbol
    calibration_path = symbol_dir / _CALIBRATION_FILENAME

    if overwrite and symbol_dir.is_dir():
        for stale in symbol_dir.glob("*.parquet"):
            stale.unlink()

    if calibration_path.exists() and not overwrite:
        existing_payload: dict[str, Any] = orjson.loads(calibration_path.read_bytes())
        existing_threshold = float(existing_payload["threshold_usdt"])
        if existing_threshold <= 0:
            raise ValueError(
                f"{calibration_path} tem threshold_usdt não positivo "
                f"({existing_threshold!r}) -- arquivo corrompido, não dá pra comparar "
                "com a calibração nova"
            )
        rel_diff = (
            calibration.threshold_usdt - existing_threshold
        ) / existing_threshold  # noqa: unguarded-ratio -- existing_threshold>0 checado acima
        if abs(rel_diff) > _CALIBRATION_MISMATCH_REL_TOLERANCE:
            raise ValueError(
                f"{calibration_path} já existe com threshold_usdt={existing_threshold!r}, "
                f"divergente do novo threshold_usdt={calibration.threshold_usdt!r} "
                f"(rel_diff={rel_diff!r}) -- rodar a validação 2x com janelas diferentes "
                "misturaria barras calibradas com thresholds incompatíveis no mesmo "
                "diretório; passe overwrite=True se a substituição for intencional"
            )

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
        threshold_usdt=calibration.threshold_usdt,
        dest_dir=str(symbol_dir),
    )
    return written


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Runner de VALIDAÇÃO de dollar bar canônico (R1) -- calibra sobre a "
            "própria janela, constrói, escreve. NÃO é a decisão de calibração "
            "congelada de produção (AG-042 itens 2/3 continuam deferidos); NÃO "
            "prova validade estatística (AG-043 continua pendente) -- ver "
            "docstring do módulo."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--symbol", required=True, help="ex. BTCUSDT")
    parser.add_argument("--start", required=True, help="ISO date, ex. 2026-07-01")
    parser.add_argument("--end", required=True, help="ISO date, ex. 2026-07-07")
    parser.add_argument(
        "--dest-root",
        default=None,
        help="default: data/capacity/ (CAPACITY_DIR) -- diretório-raiz de dollar_bars_r1/",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_cli_args()
    dest_root = Path(args.dest_root) if args.dest_root is not None else None

    calibration = calibrate_dollar_threshold_for_validation(args.symbol, args.start, args.end)
    bars_df = build_dollar_bars_for_window(
        args.symbol,
        args.start,
        args.end,
        threshold_usdt=calibration.threshold_usdt,
        max_leftover_trades=calibration.max_leftover_trades,
    )
    written = write_dollar_bars_and_calibration(bars_df, calibration, dest_root=dest_root)

    logger.info(
        "data.build_dollar_bars.done",
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        n_bars=bars_df.height,
        threshold_usdt=calibration.threshold_usdt,
        n_files=len(written),
        dest_root=str(dest_root) if dest_root is not None else str(CAPACITY_DIR),
    )


if __name__ == "__main__":
    main()
