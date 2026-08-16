"""Mede `sample_weight` (`src.labels.weights.apply_weights`) agrupado por
`econ_regime` (`src.regime.classifier._economics_regime`), pros 5 ativos --
resposta direta à hipótese (ainda não testada) de que o Alpha é treinado com
peso sistematicamente MENOR justamente nos períodos que o Regime Engine
classifica como `ECONOMICS_HOSTILE`.

**A cadeia de hipótese, por completo:** `uniqueness` (AFML cap. 4, `src.
labels.weights.compute_concurrency_and_uniqueness`) penaliza labels que
ocupam posições de alta concorrência -- muitos labels "abertos"
simultaneamente. Concorrência alta tende a acontecer quando trades resolvem
DEVAGAR (mais tempo entre `t0` e `t1`, mais overlap). Resolução lenta tende a
acontecer em mercado com pouco movimento realizado (poucas barras tocam TP/SL
cedo). Pouco movimento realizado eleva `cost_atr_ratio` (E27f, custo
round-trip relativo ao ATR) -- e `cost_atr_ratio` alto no tercil superior é
literalmente a definição de `ECONOMICS_HOSTILE` (§4.3.1, `_economics_regime`).
Se essa cadeia for real, `sample_weight` médio (que já embute `uniqueness`)
seria menor exatamente nos períodos hostis -- um descasamento treino/operação
nunca medido. Este script SÓ mede a última pergunta da cadeia (`sample_weight`
por `econ_regime`); não testa os elos intermediários (concorrência vs
`cost_atr_ratio`), e não deveria ser lido como confirmação da cadeia inteira
-- só do sintoma final que ela prevê.

**Descritivo, 0 trials.** Não deriva nem propõe nenhuma constante nova, não
retreina nada, não escreve em `config/constants.yaml`. Mesma categoria de
`measure_time_stop_slack.py` (script irmão neste mesmo diretório) -- conta
uma coluna que já existe (`sample_weight`) contra outra que já existe
(`econ_regime`), não computa nenhuma métrica de desempenho preditivo, então
não é instância do banned pattern B06.

**Achado que determina o desenho deste script -- por que ele NÃO lê
`data/regimes/regime_v1/regimes.parquet` do disco.** A investigação prévia
(`src/models/dataset.py`, docstring do módulo, Sprint 8) já registrou que
esse artefato está DESATUALIZADO: cobre só 2019-12-31->2024-03-30
(148.992 linhas), enquanto `labels/{symbol}/15m/v1/labels.parquet` cobre
2020-01-01->2026-08-06 nos 5 símbolos. Além disso o layout em disco é o
LEGADO pré-V4.1 (`data/regimes/{version}/regimes.parquet`, um arquivo só,
sem chave de símbolo -- `src/regime/_paths.py::regime_symbol_tf_dir`
existe para o layout chaveado `data/regimes/{symbol}/{tf}/{version}/`, mas
nada foi escrito lá ainda; conferido nesta sessão, só o caminho legado existe
no disco). Ler esse arquivo direto teria dois problemas reais: (a) cobriria
só uma fração dos labels de UM símbolo, forçando descartar a maior parte do
dataset; (b) não haveria como saber a qual símbolo ele pertence, porque
`classify_regimes` não emite coluna `symbol`. `src.models.dataset.
build_modeling_frame` já resolveu esse mesmo problema de forma auditada:
`src.regime.build.build_regimes` é determinístico e causal (quantis
expansivos, §4) -- reexecutá-lo em memória sobre o intervalo completo de cada
símbolo reproduz os MESMOS valores que estariam em disco se o artefato
tivesse sido mantido atualizado, sem o custo/risco de reescrever o artefato
canônico. Este script segue o MESMO padrão (recompute em memória,
~poucos segundos por símbolo), só que também extrai `econ_regime` -- que
`build_modeling_frame` não expõe (seleciona só `regime`/`tradeable` de
`regimes_df`, propositalmente fora do escopo daquele módulo).

**Convenção de tempo -- duas coexistem, resolvidas aqui exatamente como em
`src.models.dataset.build_modeling_frame` (mesma docstring, mesmo motivo):**
`src.labels.triple_barrier` usa `t0 = close_time` da barra de 15m;
`src.regime.classifier` usa `t0 = open_time` da MESMA barra. A ponte é
`src.features.build.build_t1_features(symbol, start, end)`, que devolve
`open_time`/`close_time` por barra -- junta regime (chave `open_time`) com a
tabela de barras, depois junta essa tabela com `labels` via
`close_time == labels.t0`. Cada `t0` de regime (uma barra) corresponde a
exatamente 2 linhas de `labels` (side=+1 e side=-1) -- as duas devem herdar o
MESMO `econ_regime`; este script confirma isso (não assume), contando
`econ_regime` distintos por `t0` pós-join.

**NOFILL (`barrier_hit == "NOFILL"`, `label == -2`) tem `ret_net == 0.0`
literal por construção** (§3.4 pseudocódigo, `triple_barrier.
_emit_nofill_row`) -- então `sample_weight` dessas linhas é sempre 0,
qualquer que seja o regime. Incluir essas linhas dilui a média de forma
desigual SE a taxa de NOFILL variar por regime (plausível -- preenchimento de
ordem limite pode depender de volatilidade/spread, os mesmos eixos que
alimentam `econ_regime`), sem in-formar nada sobre o peso que o Alpha
realmente vê em treino (peso 0 não contribui gradiente, presente ou ausente
do agrupamento). Por isso este script reporta DUAS visões, lado a lado, nunca
uma escondendo a outra: população completa (`sample_weight` como a coluna
existe em disco, é o que a invariante §3.8 mede) e população sem NOFILL
(o que de fato entra no treino com peso não-nulo)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Script standalone -- sem isto, `from src...` abaixo falha com
# `ModuleNotFoundError: No module named 'src'` quando invocado por caminho
# direto (`uv run python tools/diagnostics/<este arquivo>.py`), já que só o
# diretório do script entra em sys.path[0] nesse modo (diferente de `-m`, que
# usa o cwd). Achado real (2026-08-16): os 8 scripts de tools/diagnostics/
# que importam de `src.*` tinham este mesmo bug.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import polars as pl
import structlog

from src.features import build as features_build
from src.models.dataset import date_bounds
from src.regime import build as regime_build
from src.validation.cpcv import load_labels_v1

logger = structlog.get_logger(__name__)

_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT")

_ECON_REGIME_ORDER: tuple[str, ...] = (
    "ECONOMICS_FAVORABLE",
    "ECONOMICS_NEUTRAL",
    "ECONOMICS_HOSTILE",
    "ECONOMICS_UNKNOWN",
)

# Limiares de LEITURA do achado (não de decisão de modelo/pipeline) -- os
# mesmos valores que a task pediu para decidir "problema real" vs "ruído":
# razão FAVORABLE/HOSTILE > _RATIO_LARGE_THRESHOLD é grande o bastante para
# priorizar investigar a cadeia completa; < _RATIO_SMALL_THRESHOLD é pequena
# o bastante para não priorizar agora. Faixa intermediária = inconclusivo,
# reportado como tal, não arredondado para um dos dois lados.
_RATIO_LARGE_THRESHOLD: float = 1.5  # noqa: magic-number
_RATIO_SMALL_THRESHOLD: float = 1.2  # noqa: magic-number

# Fração mínima de linhas de `labels` que precisam casar com um `econ_regime`
# não-nulo pós-join para o join ser considerado íntegro; abaixo disso o
# resultado é reportado mas marcado como suspeito em vez de aceito calado.
_MIN_JOIN_MATCH_RATE: float = 0.99  # noqa: magic-number


@dataclass(frozen=True, slots=True)
class SymbolJoinResult:
    symbol: str
    labels_with_regime: pl.DataFrame
    n_labels: int
    n_matched: int
    n_t0_with_side_mismatch: int


def _attach_econ_regime(symbol: str, labels: pl.DataFrame) -> SymbolJoinResult:
    """Recomputa o Regime Engine em memória (ver docstring do módulo) e
    junta `econ_regime` a `labels` pela ponte `open_time`/`close_time` de
    `build_t1_features` -- mesmo padrão de `src.models.dataset.
    build_modeling_frame`, estendido para também carregar `econ_regime`
    (que aquele módulo não expõe)."""
    start, end = date_bounds(labels)

    features_df = features_build.build_t1_features(symbol, start, end)
    regimes_df = regime_build.build_regimes(symbol, start, end)

    bar_bridge = features_df.select(
        pl.col("open_time").cast(pl.Int64).alias("_open_time_ms"),
        pl.col("close_time").cast(pl.Int64).alias("_close_time_ms"),
    )
    n_bars_before_join = bar_bridge.height

    regime_small = regimes_df.select(
        pl.col("t0").dt.epoch(time_unit="ms").alias("_open_time_ms"),
        pl.col("econ_regime").cast(pl.Utf8).alias("econ_regime"),
    )
    # `regimes_df` é uma barra por `t0` por construção (`classify_regimes`
    # emite uma linha por posição de entrada) -- checado, não assumido,
    # porque um fan-out aqui silenciosamente duplicaria linhas de `labels`
    # no join seguinte.
    n_regime_rows = regime_small.height
    n_regime_t0_unique = regime_small["_open_time_ms"].n_unique()
    if n_regime_t0_unique != n_regime_rows:
        raise ValueError(
            f"measure_sample_weight_by_econ_regime: {symbol} -- regimes_df tem "
            f"{n_regime_rows} linhas mas só {n_regime_t0_unique} `t0` únicos; "
            "join por open_time faria fan-out silencioso em labels"
        )

    bar_bridge = bar_bridge.join(regime_small, on="_open_time_ms", how="left")
    if bar_bridge.height != n_bars_before_join:
        raise ValueError(
            f"measure_sample_weight_by_econ_regime: {symbol} -- join bar_bridge x "
            f"regime mudou a contagem de linhas ({n_bars_before_join} -> "
            f"{bar_bridge.height}); fan-out inesperado"
        )

    labels_keyed = labels.with_columns(
        pl.col("t0").dt.epoch(time_unit="ms").alias("_close_time_ms")
    )
    n_labels_before_join = labels_keyed.height
    merged = labels_keyed.join(
        bar_bridge.select(["_close_time_ms", "econ_regime"]), on="_close_time_ms", how="left"
    )
    if merged.height != n_labels_before_join:
        raise ValueError(
            f"measure_sample_weight_by_econ_regime: {symbol} -- join labels x "
            f"bar_bridge mudou a contagem de linhas ({n_labels_before_join} -> "
            f"{merged.height}); fan-out inesperado (bar_bridge deveria ter "
            "close_time único por construção de build_t1_features)"
        )

    n_matched = merged.filter(pl.col("econ_regime").is_not_null()).height

    # Confirma que os dois lados (side=+1/-1) do MESMO t0 herdam o MESMO
    # econ_regime -- não assumido, contado: qualquer t0 com >1 econ_regime
    # distinto entre suas linhas seria um bug de join (ex. duplicidade de
    # close_time entre barras), não um resultado válido.
    per_t0_distinct = (
        merged.filter(pl.col("econ_regime").is_not_null())
        .group_by("t0")
        .agg(pl.col("econ_regime").n_unique().alias("n_distinct_econ_regime"))
    )
    n_t0_mismatch = per_t0_distinct.filter(pl.col("n_distinct_econ_regime") > 1).height

    merged = merged.drop("_close_time_ms")

    return SymbolJoinResult(
        symbol=symbol,
        labels_with_regime=merged,
        n_labels=n_labels_before_join,
        n_matched=n_matched,
        n_t0_with_side_mismatch=n_t0_mismatch,
    )


def _weight_stats(df: pl.DataFrame, *, group_col: str) -> pl.DataFrame:
    """`mean`/`median`/`n` de `sample_weight` por `group_col`, mais o total
    pooled sobre `df` inteiro como uma linha extra `group_col="ALL"` -- para
    ler a média geral sem precisar somar manualmente as linhas por bucket."""
    by_group = (
        df.group_by(group_col)
        .agg(
            pl.col("sample_weight").mean().alias("mean_sample_weight"),
            pl.col("sample_weight").median().alias("median_sample_weight"),
            pl.len().alias("n"),
        )
        .sort(group_col)
    )
    total = df.select(
        pl.lit("ALL").alias(group_col),
        pl.col("sample_weight").mean().alias("mean_sample_weight"),
        pl.col("sample_weight").median().alias("median_sample_weight"),
        pl.len().alias("n"),
    )
    return pl.concat([by_group, total], how="vertical")


def _log_stats_table(*, symbol: str, population: str, stats: pl.DataFrame) -> None:
    for row in stats.iter_rows(named=True):
        logger.info(
            "diagnostics.measure_sample_weight_by_econ_regime.bucket",
            symbol=symbol,
            population=population,
            econ_regime=row["econ_regime"],
            n=row["n"],
            mean_sample_weight=round(row["mean_sample_weight"], 6),
            median_sample_weight=round(row["median_sample_weight"], 6),
        )


def _favorable_hostile_ratio(stats: pl.DataFrame) -> float | None:
    """`mean(FAVORABLE) / mean(HOSTILE)`; `None` se algum dos dois buckets
    não existir na amostra (não força um valor a partir de um bucket
    ausente)."""
    means = dict(
        zip(stats["econ_regime"].to_list(), stats["mean_sample_weight"].to_list(), strict=True)
    )
    favorable = means.get("ECONOMICS_FAVORABLE")
    hostile = means.get("ECONOMICS_HOSTILE")
    if favorable is None or hostile is None or hostile == 0.0:
        return None
    return float(favorable / hostile)


def _classify_ratio(ratio: float | None) -> str:
    if ratio is None:
        return "N/A -- bucket FAVORABLE ou HOSTILE ausente/vazio"
    if ratio >= _RATIO_LARGE_THRESHOLD or ratio <= 1.0 / _RATIO_LARGE_THRESHOLD:  # noqa: unguarded-ratio -- constante de módulo 1.5, nunca 0
        return "GRANDE -- prioriza investigar a cadeia completa"
    if 1.0 / _RATIO_SMALL_THRESHOLD <= ratio <= _RATIO_SMALL_THRESHOLD:  # noqa: unguarded-ratio -- constante de módulo 1.2, nunca 0
        # janela simétrica em torno de 1.0: sem viés a priori de qual bucket "deveria" ser maior
        return "PEQUENA -- consistente com ruído"
    return "INTERMEDIÁRIA -- inconclusivo, nem claramente ruído nem claramente grande"


def main() -> None:
    pooled_all: list[pl.DataFrame] = []
    pooled_non_nofill: list[pl.DataFrame] = []
    per_symbol_ratios: dict[str, float | None] = {}

    for symbol in _SYMBOLS:
        try:
            labels = load_labels_v1(symbol=symbol)
        except FileNotFoundError as exc:
            logger.warning(
                "diagnostics.measure_sample_weight_by_econ_regime.labels_missing_skip",
                symbol=symbol,
                error=repr(exc),
            )
            continue

        try:
            join_result = _attach_econ_regime(symbol, labels)
        except FileNotFoundError as exc:
            logger.warning(
                "diagnostics.measure_sample_weight_by_econ_regime.regime_upstream_missing_skip",
                symbol=symbol,
                error=repr(exc),
                note=(
                    "features/regime precisam de klines/funding/OI já no lake -- "
                    "ausência tratada como skip, não erro fatal"
                ),
            )
            continue

        match_rate = (
            join_result.n_matched / join_result.n_labels  # noqa: unguarded-ratio -- guardado pelo ternário: n_labels==0 cai no else antes de dividir
            if join_result.n_labels
            else 0.0
        )
        join_ok = match_rate >= _MIN_JOIN_MATCH_RATE and join_result.n_t0_with_side_mismatch == 0
        logger.info(
            "diagnostics.measure_sample_weight_by_econ_regime.join_qa",
            symbol=symbol,
            n_labels=join_result.n_labels,
            n_matched_econ_regime=join_result.n_matched,
            match_rate=round(match_rate, 6),
            n_t0_with_side_mismatch=join_result.n_t0_with_side_mismatch,
            join_considered_ok=join_ok,
        )
        if not join_ok:
            logger.warning(
                "diagnostics.measure_sample_weight_by_econ_regime.join_suspect",
                symbol=symbol,
                match_rate=round(match_rate, 6),
                min_required=_MIN_JOIN_MATCH_RATE,
                n_t0_with_side_mismatch=join_result.n_t0_with_side_mismatch,
                note=(
                    "resultado deste símbolo reportado mesmo assim, mas marcado "
                    "suspeito -- não travar o script inteiro por um símbolo"
                ),
            )

        matched = join_result.labels_with_regime.filter(pl.col("econ_regime").is_not_null())
        non_nofill = matched.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")

        stats_all = _weight_stats(matched, group_col="econ_regime")
        stats_non_nofill = _weight_stats(non_nofill, group_col="econ_regime")

        _log_stats_table(symbol=symbol, population="all_rows", stats=stats_all)
        _log_stats_table(symbol=symbol, population="non_nofill", stats=stats_non_nofill)

        ratio_non_nofill = _favorable_hostile_ratio(stats_non_nofill)
        per_symbol_ratios[symbol] = ratio_non_nofill
        logger.info(
            "diagnostics.measure_sample_weight_by_econ_regime.symbol_ratio",
            symbol=symbol,
            population="non_nofill",
            favorable_over_hostile_mean_ratio=(
                round(ratio_non_nofill, 4) if ratio_non_nofill is not None else None
            ),
            reading=_classify_ratio(ratio_non_nofill),
        )

        pooled_all.append(matched)
        pooled_non_nofill.append(non_nofill)

    if not pooled_all:
        logger.warning(
            "diagnostics.measure_sample_weight_by_econ_regime.no_data",
            note=(
                "nenhum símbolo tinha labels.parquet + regime reconstruível -- "
                "rode Label/Feature Engine primeiro"
            ),
        )
        return

    pooled_all_df = pl.concat(pooled_all, how="vertical")
    pooled_non_nofill_df = pl.concat(pooled_non_nofill, how="vertical")

    pooled_stats_all = _weight_stats(pooled_all_df, group_col="econ_regime")
    pooled_stats_non_nofill = _weight_stats(pooled_non_nofill_df, group_col="econ_regime")

    _log_stats_table(symbol="POOLED_5_SYMBOLS", population="all_rows", stats=pooled_stats_all)
    _log_stats_table(
        symbol="POOLED_5_SYMBOLS", population="non_nofill", stats=pooled_stats_non_nofill
    )

    pooled_ratio_all = _favorable_hostile_ratio(pooled_stats_all)
    pooled_ratio_non_nofill = _favorable_hostile_ratio(pooled_stats_non_nofill)

    logger.info(
        "diagnostics.measure_sample_weight_by_econ_regime.pooled_done",
        n_symbols_with_data=len(per_symbol_ratios),
        n_symbols_requested=len(_SYMBOLS),
        pooled_favorable_over_hostile_ratio_all_rows=(
            round(pooled_ratio_all, 4) if pooled_ratio_all is not None else None
        ),
        pooled_favorable_over_hostile_ratio_non_nofill=(
            round(pooled_ratio_non_nofill, 4) if pooled_ratio_non_nofill is not None else None
        ),
        reading_all_rows=_classify_ratio(pooled_ratio_all),
        reading_non_nofill=_classify_ratio(pooled_ratio_non_nofill),
        per_symbol_ratio_non_nofill={
            k: (round(v, 4) if v is not None else None) for k, v in per_symbol_ratios.items()
        },
        note=(
            "leitura: ratio >= 1.5x (ou <= 0.67x) e' GRANDE o bastante pra "
            "priorizar investigar a cadeia completa (concorrencia -> "
            "resolucao lenta -> cost_atr_ratio -> econ_regime); ratio entre "
            "0.83x e 1.2x e' PEQUENO o bastante pra tratar como ruido; faixa "
            "intermediaria fica inconclusiva por design, nao arredondada pra "
            "nenhum dos dois lados. So mede sample_weight x econ_regime -- "
            "NAO confirma os elos intermediarios da cadeia (concorrencia vs "
            "cost_atr_ratio), que exigiriam medicao a parte."
        ),
    )


if __name__ == "__main__":
    main()
