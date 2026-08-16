"""Mede `n_bars_held` (tempo de resolução TP/SL, `src.labels.triple_barrier`)
contra `cost_atr_ratio` (E27f) e `econ_regime` (`src.regime.classifier.
_economics_regime`), pros 5 ativos -- resposta direta a DUAS perguntas
levantadas na mesma sessão que pareciam independentes mas compartilham o
mesmo elo causal não testado:

1. **Canal 3** (`measure_sample_weight_by_econ_regime.py`, script irmão neste
   diretório) mediu que `sample_weight` médio é 3,08x maior em
   `ECONOMICS_FAVORABLE` que em `ECONOMICS_HOSTILE` -- e propôs uma cadeia
   causal de 4 elos (concorrência -> resolução lenta -> `cost_atr_ratio` alto
   -> `ECONOMICS_HOSTILE`) sem testar nenhum elo intermediário, só o sintoma
   final. Este script testa o elo do MEIO da cadeia direto: trades em regime
   hostil de fato demoram mais barras pra resolver?

2. **Horizonte × ambiente** (discussão da mesma sessão, sem medição): se
   `ECONOMICS_HOSTILE` (tercil superior de `cost_atr_ratio`, volatilidade
   atual baixa relativa ao custo fixo) também significa que as barreiras
   (dimensionadas em unidades de ATR) demoram mais barras pra serem tocadas,
   então "ambiente hostil" e "horizonte longo" seriam, empiricamente, quase a
   mesma coisa vista por dois ângulos -- o que teria implicação direta pra
   validade de qualquer triagem de feature que cruze IC por horizonte com
   IC por ambiente como se fossem eixos independentes.

Uma única medição resolve as duas: correlação (`n_bars_held`,
`cost_atr_ratio`) e `n_bars_held` estratificado por `econ_regime`, ambos
restritos a trades que resolveram por TP/SL (ver exclusão de TIME/NOFILL
abaixo, mesma lógica de `measure_time_stop_slack.py`).

**Descritivo, 0 trials.** Não deriva nem propõe nenhuma constante nova, não
retreina nada, não escreve em `config/constants.yaml`, não computa IC contra
retorno (não é instância do banned pattern B06 -- conta duas colunas que já
existem uma contra a outra, não mede desempenho preditivo).

**Reaproveita o padrão de junção já validado em
`measure_sample_weight_by_econ_regime.py`** (mesma docstring da função
`_attach_regime_and_cost`, adaptada aqui pra também carregar
`E27f_cost_atr_ratio` do lado de `features_df`, que aquele script não
precisava): `src.features.build.build_t1_features(symbol, start, end)`
como ponte `open_time`/`close_time`, `src.regime.build.build_regimes`
recomputado em memória (mesmo motivo -- `data/regimes/regime_v1/
regimes.parquet` em disco é legado, cobre só até 2024-03-30). Convenção de
tempo idêntica: regime usa `open_time` da barra, labels usa `t0 ==
close_time` da MESMA barra.

**Exclusão TIME/NOFILL, mesma justificativa de `measure_time_stop_slack.py`:**
`n_bars_held` é censurado no teto por construção quando a barreira que
"vence" é o tempo (`n_bars_held == time_stop_bars` sempre), e é 0 literal
quando a ordem nunca encheu (NOFILL). Incluir qualquer um dos dois
corromperia tanto a correlação quanto a estratificação por regime -- não é
tempo de retenção real em nenhum dos dois casos."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
from scipy.stats import spearmanr

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

_COST_COL = "E27f_cost_atr_ratio"

# Convenção de leitura de |rho| (Cohen 1988, regra de bolso -- não é
# constante de pipeline, não vai pra constants.yaml, só rotula o output
# deste diagnóstico pra ficar legível sem precisar decorar a escala).
_RHO_WEAK_MAX: float = 0.10  # noqa: magic-number
_RHO_MODERATE_MAX: float = 0.30  # noqa: magic-number

_MIN_JOIN_MATCH_RATE: float = 0.99  # noqa: magic-number


@dataclass(frozen=True, slots=True)
class SymbolJoinResult:
    symbol: str
    labels_with_regime_and_cost: pl.DataFrame
    n_labels: int
    n_matched: int
    n_t0_with_side_mismatch: int


def _attach_regime_and_cost(symbol: str, labels: pl.DataFrame) -> SymbolJoinResult:
    """Mesma ponte de `measure_sample_weight_by_econ_regime.py::
    _attach_econ_regime`, estendida pra também carregar `E27f_cost_atr_ratio`
    do lado de `features_df` (aquele script só precisava de `econ_regime`)."""
    start, end = date_bounds(labels)

    features_df = features_build.build_t1_features(symbol, start, end)
    regimes_df = regime_build.build_regimes(symbol, start, end)

    bar_bridge = features_df.select(
        pl.col("open_time").cast(pl.Int64).alias("_open_time_ms"),
        pl.col("close_time").cast(pl.Int64).alias("_close_time_ms"),
        pl.col(_COST_COL).cast(pl.Float64).alias(_COST_COL),
    )
    n_bars_before_join = bar_bridge.height

    regime_small = regimes_df.select(
        pl.col("t0").dt.epoch(time_unit="ms").alias("_open_time_ms"),
        pl.col("econ_regime").cast(pl.Utf8).alias("econ_regime"),
    )
    n_regime_rows = regime_small.height
    n_regime_t0_unique = regime_small["_open_time_ms"].n_unique()
    if n_regime_t0_unique != n_regime_rows:
        raise ValueError(
            f"measure_n_bars_held_vs_cost_and_regime: {symbol} -- regimes_df tem "
            f"{n_regime_rows} linhas mas só {n_regime_t0_unique} `t0` únicos; "
            "join por open_time faria fan-out silencioso em labels"
        )

    bar_bridge = bar_bridge.join(regime_small, on="_open_time_ms", how="left")
    if bar_bridge.height != n_bars_before_join:
        raise ValueError(
            f"measure_n_bars_held_vs_cost_and_regime: {symbol} -- join bar_bridge x "
            f"regime mudou a contagem de linhas ({n_bars_before_join} -> "
            f"{bar_bridge.height}); fan-out inesperado"
        )

    labels_keyed = labels.with_columns(
        pl.col("t0").dt.epoch(time_unit="ms").alias("_close_time_ms")
    )
    n_labels_before_join = labels_keyed.height
    merged = labels_keyed.join(
        bar_bridge.select(["_close_time_ms", _COST_COL, "econ_regime"]),
        on="_close_time_ms",
        how="left",
    )
    if merged.height != n_labels_before_join:
        raise ValueError(
            f"measure_n_bars_held_vs_cost_and_regime: {symbol} -- join labels x "
            f"bar_bridge mudou a contagem de linhas ({n_labels_before_join} -> "
            f"{merged.height}); fan-out inesperado"
        )

    n_matched = merged.filter(pl.col("econ_regime").is_not_null()).height

    per_t0_distinct = (
        merged.filter(pl.col("econ_regime").is_not_null())
        .group_by("t0")
        .agg(pl.col("econ_regime").n_unique().alias("n_distinct_econ_regime"))
    )
    n_t0_mismatch = per_t0_distinct.filter(pl.col("n_distinct_econ_regime") > 1).height

    merged = merged.drop("_close_time_ms")

    return SymbolJoinResult(
        symbol=symbol,
        labels_with_regime_and_cost=merged,
        n_labels=n_labels_before_join,
        n_matched=n_matched,
        n_t0_with_side_mismatch=n_t0_mismatch,
    )


def _classify_rho(rho: float) -> str:
    abs_rho = abs(rho)
    if abs_rho < _RHO_WEAK_MAX:
        return "FRACA -- consistente com nao haver elo mecanico relevante"
    if abs_rho < _RHO_MODERATE_MAX:
        return "MODERADA -- elo mecanico plausivel, nao dominante"
    return "FORTE -- elo mecanico provavelmente domina o sintoma do Canal 3"


def _n_bars_held_stats_by_regime(df: pl.DataFrame) -> pl.DataFrame:
    by_group = (
        df.group_by("econ_regime")
        .agg(
            pl.col("n_bars_held").mean().alias("mean_n_bars_held"),
            pl.col("n_bars_held").median().alias("median_n_bars_held"),
            pl.len().alias("n"),
        )
        .sort("econ_regime")
    )
    total = df.select(
        pl.lit("ALL").alias("econ_regime"),
        pl.col("n_bars_held").mean().alias("mean_n_bars_held"),
        pl.col("n_bars_held").median().alias("median_n_bars_held"),
        pl.len().alias("n"),
    )
    return pl.concat([by_group, total], how="vertical")


def _hostile_over_favorable_median_ratio(stats: pl.DataFrame) -> float | None:
    medians = dict(
        zip(stats["econ_regime"].to_list(), stats["median_n_bars_held"].to_list(), strict=True)
    )
    hostile = medians.get("ECONOMICS_HOSTILE")
    favorable = medians.get("ECONOMICS_FAVORABLE")
    if hostile is None or favorable is None or favorable == 0.0:
        return None
    return float(hostile / favorable)


def main() -> None:
    pooled_resolved: list[pl.DataFrame] = []
    per_symbol_rho: dict[str, float | None] = {}

    for symbol in _SYMBOLS:
        try:
            labels = load_labels_v1(symbol=symbol)
        except FileNotFoundError as exc:
            logger.warning(
                "diagnostics.measure_n_bars_held_vs_cost_and_regime.labels_missing_skip",
                symbol=symbol,
                error=repr(exc),
            )
            continue

        try:
            join_result = _attach_regime_and_cost(symbol, labels)
        except FileNotFoundError as exc:
            logger.warning(
                "diagnostics.measure_n_bars_held_vs_cost_and_regime.upstream_missing_skip",
                symbol=symbol,
                error=repr(exc),
            )
            continue

        match_rate = (
            join_result.n_matched / join_result.n_labels  # noqa: unguarded-ratio -- guardado pelo ternário: n_labels==0 cai no else antes de dividir
            if join_result.n_labels
            else 0.0
        )
        join_ok = match_rate >= _MIN_JOIN_MATCH_RATE and join_result.n_t0_with_side_mismatch == 0
        logger.info(
            "diagnostics.measure_n_bars_held_vs_cost_and_regime.join_qa",
            symbol=symbol,
            n_labels=join_result.n_labels,
            n_matched=join_result.n_matched,
            match_rate=round(match_rate, 6),
            n_t0_with_side_mismatch=join_result.n_t0_with_side_mismatch,
            join_considered_ok=join_ok,
        )
        if not join_ok:
            logger.warning(
                "diagnostics.measure_n_bars_held_vs_cost_and_regime.join_suspect",
                symbol=symbol,
                match_rate=round(match_rate, 6),
                min_required=_MIN_JOIN_MATCH_RATE,
                n_t0_with_side_mismatch=join_result.n_t0_with_side_mismatch,
                note="resultado deste simbolo reportado mesmo assim, mas marcado suspeito",
            )

        matched = join_result.labels_with_regime_and_cost.filter(
            pl.col("econ_regime").is_not_null()
        )
        resolved = matched.filter(pl.col("barrier_hit").cast(pl.Utf8).is_in(["TP", "SL"]))
        n_resolved = resolved.height
        if n_resolved == 0:
            logger.warning(
                "diagnostics.measure_n_bars_held_vs_cost_and_regime.no_tp_sl",
                symbol=symbol,
            )
            continue

        n_bars_held = resolved["n_bars_held"].cast(pl.Float64).to_numpy()
        cost_atr_ratio = resolved[_COST_COL].to_numpy()
        valid_mask = np.isfinite(n_bars_held) & np.isfinite(cost_atr_ratio)
        n_valid = int(valid_mask.sum())
        rho: float | None
        if n_valid < 3:
            rho = None
        else:
            rho_val, _p = spearmanr(n_bars_held[valid_mask], cost_atr_ratio[valid_mask])
            rho = float(rho_val) if np.isfinite(rho_val) else None
        per_symbol_rho[symbol] = rho

        stats_by_regime = _n_bars_held_stats_by_regime(resolved)
        for row in stats_by_regime.iter_rows(named=True):
            logger.info(
                "diagnostics.measure_n_bars_held_vs_cost_and_regime.bucket",
                symbol=symbol,
                econ_regime=row["econ_regime"],
                n=row["n"],
                mean_n_bars_held=round(row["mean_n_bars_held"], 3),
                median_n_bars_held=round(row["median_n_bars_held"], 3),
            )
        hostile_over_favorable = _hostile_over_favorable_median_ratio(stats_by_regime)

        logger.info(
            "diagnostics.measure_n_bars_held_vs_cost_and_regime.symbol_done",
            symbol=symbol,
            n_resolved_tp_sl=n_resolved,
            n_valid_for_correlation=n_valid,
            spearman_rho_n_bars_held_vs_cost_atr_ratio=(round(rho, 4) if rho is not None else None),
            reading=_classify_rho(rho) if rho is not None else "N/A -- amostra insuficiente",
            hostile_over_favorable_median_n_bars_held=(
                round(hostile_over_favorable, 4) if hostile_over_favorable is not None else None
            ),
        )

        pooled_resolved.append(resolved)

    if not pooled_resolved:
        logger.warning(
            "diagnostics.measure_n_bars_held_vs_cost_and_regime.no_data",
            note="nenhum simbolo tinha labels+features+regime reconstruiveis",
        )
        return

    pooled_df = pl.concat(pooled_resolved, how="vertical")
    pooled_n_bars_held = pooled_df["n_bars_held"].cast(pl.Float64).to_numpy()
    pooled_cost = pooled_df[_COST_COL].to_numpy()
    pooled_valid_mask = np.isfinite(pooled_n_bars_held) & np.isfinite(pooled_cost)
    pooled_rho_val, _p = spearmanr(
        pooled_n_bars_held[pooled_valid_mask], pooled_cost[pooled_valid_mask]
    )
    pooled_rho = float(pooled_rho_val) if np.isfinite(pooled_rho_val) else None

    pooled_stats_by_regime = _n_bars_held_stats_by_regime(pooled_df)
    for row in pooled_stats_by_regime.iter_rows(named=True):
        logger.info(
            "diagnostics.measure_n_bars_held_vs_cost_and_regime.bucket",
            symbol="POOLED_5_SYMBOLS",
            econ_regime=row["econ_regime"],
            n=row["n"],
            mean_n_bars_held=round(row["mean_n_bars_held"], 3),
            median_n_bars_held=round(row["median_n_bars_held"], 3),
        )
    pooled_hostile_over_favorable = _hostile_over_favorable_median_ratio(pooled_stats_by_regime)

    logger.info(
        "diagnostics.measure_n_bars_held_vs_cost_and_regime.pooled_done",
        n_symbols_with_data=len(per_symbol_rho),
        n_symbols_requested=len(_SYMBOLS),
        pooled_n_resolved_tp_sl=pooled_df.height,
        pooled_spearman_rho=(round(pooled_rho, 4) if pooled_rho is not None else None),
        pooled_reading=(_classify_rho(pooled_rho) if pooled_rho is not None else "N/A"),
        pooled_hostile_over_favorable_median_n_bars_held=(
            round(pooled_hostile_over_favorable, 4)
            if pooled_hostile_over_favorable is not None
            else None
        ),
        per_symbol_rho={
            k: (round(v, 4) if v is not None else None) for k, v in per_symbol_rho.items()
        },
        note=(
            "leitura: rho forte E hostile_over_favorable >> 1 confirmam o elo "
            "mecanico do Canal 3 (regime hostil resolve mais devagar -> "
            "concorrencia -> peso menor) e confirmam a hipotese horizonte~=ambiente "
            "(testar IC contra um horizonte fixo estaria testando principalmente "
            "um dos dois lados de econ_regime). rho fraco OU ratio ~1 refuta o elo "
            "mecanico -- o sintoma do Canal 3 teria outra causa, e horizonte/"
            "ambiente seriam eixos de fato independentes."
        ),
    )


if __name__ == "__main__":
    main()
