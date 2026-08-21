"""Fila completa de diagnósticos D2-D5/R1/R3 do parecer de auditoria
externa (`docs/parecer_auditoria_externa_2026-08-20_ag114_ag118.md`,
seção 4) -- D1 já rodou em `crosscheck_stress_bucket_vs_atr_decile.py`
(confirmou colinearidade forte com ATR, ver `AG-122`).

Reusa 100% da mecânica já validada (`gate_efficiency.py`/
`m4_critical_windows.py`) -- zero fit novo. Roda pra `hmm_gaussian_
k2_v1`/`k3_v1`/`k4_v1` (R1 do parecer -- `RawLabels` dos 3 já persistidos
pela rodada real do AG-114).

**D3 -- método escolhido: ponderação por unicidade de label, não
bootstrap em bloco.** O parecer ofereceu as 2 opções; unicidade já é
infraestrutura existente do projeto (`labels.parquet::uniqueness`,
média de 1/concorrência, López de Prado -- usada em todo o pipeline de
pesos, não uma fórmula nova aqui). `n_eff = Σ uniqueness` por grupo (SL
total, SL-em-stress, TP total, TP-em-stress); IC de `lift` via método de
Katz (delta method em log-taxa, padrão pra razão de 2 proporções),
usando `n_eff` em vez do `n` bruto -- desconta diretamente a
sobreposição de barreira tripla que o parecer aponta como o motivo de
`n` nominal superestimar a amostra independente.

**D4 -- tail loss fora de unidade de ATR.** `ret_net` bruto (fração,
não dividido por `atr_at_t0`), p05/p01/p005, comparação PAREADA dentro
de cada (símbolo, janela, side, resolução) -- evita o problema de
comparar medianas de conjuntos de tamanho diferente que o parecer
apontou no item 9.

**D2 -- `lift` por janela**, não pooled -- LUNA/FTX (BTC-only, únicas
com choque abrupto) reportadas separadas das outras 3.

**D5 -- `lift` por side** -- já é uma dimensão nativa de
`GateEfficiencyResult`/desta tabela, só precisa ser mantida desagregada
na apresentação (não é um cálculo novo)."""

from __future__ import annotations

import math
from typing import Final

import polars as pl
import structlog

from src.analysis import gate_efficiency as ge
from src.analysis import m4_critical_windows as mcw
from src.validation.regime_utility import identify_stress_state_by_volatility

logger = structlog.get_logger(__name__)

_CLASSIFIERS: Final[tuple[str, ...]] = (
    "hmm_gaussian_k2_v1",
    "hmm_gaussian_k3_v1",
    "hmm_gaussian_k4_v1",
)
_Z_95: Final[float] = 1.959963984540054  # noqa: magic-number -- percentil 97,5% da normal padrão, constante matemática (não hiperparâmetro do projeto)


def _collect_joined_labels(classifier_id: str) -> pl.DataFrame:
    """1 linha por label sobrevivente ao as-of join, através das 3
    resoluções x 5 janelas x símbolos válidos -- colunas: resolution_id,
    window_name, symbol, side, barrier_hit, ret_net, atr_at_t0,
    n_bars_held, uniqueness, regime_bucket, _is_stress."""
    windows = mcw.CRITICAL_WINDOWS
    all_symbols = tuple(sorted({s for w in windows for s in w.symbols}))
    labels_by_symbol = mcw._load_labels_by_symbol(all_symbols)

    frames: list[pl.DataFrame] = []
    for resolution_id in mcw.RESOLUTIONS:
        vol_history_cache: dict[str, mcw._SymbolForwardVolHistory] = {}
        for window in windows:
            for symbol in window.symbols:
                labels_full = labels_by_symbol.get(symbol)
                if labels_full is None:
                    continue
                regime_raw = ge._load_raw_labels_from_parquet(
                    resolution_id, window.name, symbol, classifier_id
                )
                if regime_raw is None:
                    continue
                if symbol not in vol_history_cache:
                    vol_history_cache[symbol] = mcw._compute_symbol_forward_vol_history(
                        symbol, resolution_id
                    )
                vol_history = vol_history_cache[symbol]

                canonical_id, _c, realized_vol_short, _f = mcw._join_candidate_with_vol_history(
                    regime_raw, vol_history
                )
                if canonical_id.shape[0] == 0:
                    continue
                stress_state_id = identify_stress_state_by_volatility(
                    canonical_id, realized_vol_short
                )

                start_ms = mcw._iso_date_to_epoch_ms(window.start)
                end_ms = mcw._iso_date_to_epoch_ms(window.end)
                window_labels = labels_full.filter(
                    (pl.col("t0").dt.epoch(time_unit="ms") >= start_ms)
                    & (pl.col("t0").dt.epoch(time_unit="ms") < end_ms)
                )
                joined = mcw._asof_join_regime_onto_labels(window_labels, regime_raw)
                if joined.height == 0:
                    continue
                joined = joined.with_columns(
                    (pl.col("regime_bucket") == stress_state_id).alias("_is_stress")
                )
                frames.append(
                    joined.select(
                        pl.lit(resolution_id).alias("resolution_id"),
                        pl.lit(window.name).alias("window_name"),
                        pl.lit(symbol).alias("symbol"),
                        pl.col("side"),
                        pl.col("barrier_hit"),
                        pl.col("ret_net"),
                        pl.col("atr_at_t0"),
                        pl.col("n_bars_held"),
                        pl.col("uniqueness"),
                        pl.col("regime_bucket"),
                        pl.col("_is_stress"),
                    )
                )
    return pl.concat(frames)


def _weighted_rate_and_ci(n_success_eff: float, n_total_eff: float) -> tuple[float, float, float]:
    """`(rate, ci_lo, ci_hi)` via aproximação normal simples sobre `n_eff`
    -- usado como insumo do IC de `lift` (método de Katz, log-escala)."""
    if n_total_eff <= 0:
        nan = float("nan")
        return nan, nan, nan
    rate = n_success_eff / n_total_eff
    if rate <= 0 or rate >= 1:
        return rate, float("nan"), float("nan")
    se = math.sqrt(rate * (1 - rate) / n_total_eff)
    return rate, max(0.0, rate - _Z_95 * se), min(1.0, rate + _Z_95 * se)


def _lift_with_ci(
    n_sl_stress_eff: float, n_sl_eff: float, n_tp_stress_eff: float, n_tp_eff: float
) -> dict[str, float]:
    """Método de Katz -- IC de razão de 2 proporções via delta method em
    log-escala, usando `n_eff` (ponderado por `uniqueness`) em vez de `n`
    bruto (D3). `p1`=bad_event_capture_rate, `p2`=good_event_cost_rate."""
    nan = float("nan")
    if n_sl_eff <= 0 or n_tp_eff <= 0:
        return {
            "bad_event_capture_rate": nan,
            "good_event_cost_rate": nan,
            "lift": nan,
            "lift_ci_lo": nan,
            "lift_ci_hi": nan,
            "n_sl_eff": n_sl_eff,
            "n_tp_eff": n_tp_eff,
        }
    p1 = n_sl_stress_eff / n_sl_eff
    p2 = n_tp_stress_eff / n_tp_eff
    if p1 <= 0 or p2 <= 0:
        lift = p1 / p2 if p2 > 0 else nan
        return {
            "bad_event_capture_rate": p1,
            "good_event_cost_rate": p2,
            "lift": lift,
            "lift_ci_lo": nan,
            "lift_ci_hi": nan,
            "n_sl_eff": n_sl_eff,
            "n_tp_eff": n_tp_eff,
        }
    lift = p1 / p2
    var_log_p1 = (1 - p1) / (p1 * n_sl_eff)  # noqa: unguarded-ratio -- p1>0 garantido pelo if acima
    var_log_p2 = (1 - p2) / (p2 * n_tp_eff)  # noqa: unguarded-ratio -- p2>0 garantido pelo if acima
    se_log_lift = math.sqrt(var_log_p1 + var_log_p2)
    ci_lo = lift * math.exp(-_Z_95 * se_log_lift)
    ci_hi = lift * math.exp(_Z_95 * se_log_lift)
    return {
        "bad_event_capture_rate": p1,
        "good_event_cost_rate": p2,
        "lift": lift,
        "lift_ci_lo": ci_lo,
        "lift_ci_hi": ci_hi,
        "n_sl_eff": n_sl_eff,
        "n_tp_eff": n_tp_eff,
    }


def _lift_table(df: pl.DataFrame, group_cols: list[str]) -> pl.DataFrame:
    """D2/D3/D5 -- `lift` + IC por `group_cols` (ex.: [resolution_id,
    symbol, side] pra pooled-por-resolução; +[window_name] pra D2)."""
    sl = df.filter(pl.col("barrier_hit") == "SL")
    tp = df.filter(pl.col("barrier_hit") == "TP")
    sl_agg = sl.group_by(group_cols).agg(
        pl.col("uniqueness").sum().alias("n_sl_eff"),
        (pl.col("uniqueness") * pl.col("_is_stress").cast(pl.Float64))
        .sum()
        .alias("n_sl_stress_eff"),
        pl.len().alias("n_sl_nominal"),
    )
    tp_agg = tp.group_by(group_cols).agg(
        pl.col("uniqueness").sum().alias("n_tp_eff"),
        (pl.col("uniqueness") * pl.col("_is_stress").cast(pl.Float64))
        .sum()
        .alias("n_tp_stress_eff"),
        pl.len().alias("n_tp_nominal"),
    )
    merged = sl_agg.join(tp_agg, on=group_cols, how="full", coalesce=True)

    results = []
    for row in merged.iter_rows(named=True):
        stats = _lift_with_ci(
            row.get("n_sl_stress_eff") or 0.0,
            row.get("n_sl_eff") or 0.0,
            row.get("n_tp_stress_eff") or 0.0,
            row.get("n_tp_eff") or 0.0,
        )
        out = {c: row[c] for c in group_cols}
        out["n_sl_nominal"] = row.get("n_sl_nominal") or 0
        out["n_tp_nominal"] = row.get("n_tp_nominal") or 0
        out.update(stats)
        results.append(out)
    return pl.DataFrame(results)


def _paired_tail_loss_raw(df: pl.DataFrame) -> pl.DataFrame:
    """D4 -- p05/p01/p005 de `ret_net` BRUTO (não dividido por ATR),
    pareado dentro de (resolution_id, window_name, symbol, side): só
    células com >=1 observação em AMBOS os buckets (stress/não-stress)
    entram na comparação pareada."""
    cell_cols = ["resolution_id", "window_name", "symbol", "side"]

    def _pctl_by_group(sub: pl.DataFrame, is_stress: bool) -> pl.DataFrame:
        filtered = sub.filter(pl.col("_is_stress") == is_stress)
        return filtered.group_by(cell_cols).agg(
            pl.len().alias("n"),
            pl.col("ret_net").quantile(0.05).alias("p05_ret_net"),
            pl.col("ret_net").quantile(0.01).alias("p01_ret_net"),
            pl.col("ret_net").quantile(0.005).alias("p005_ret_net"),
        )

    stress_stats = _pctl_by_group(df, True).rename(
        {
            "n": "n_stress",
            "p05_ret_net": "p05_stress",
            "p01_ret_net": "p01_stress",
            "p005_ret_net": "p005_stress",
        }
    )
    nonstress_stats = _pctl_by_group(df, False).rename(
        {
            "n": "n_nonstress",
            "p05_ret_net": "p05_nonstress",
            "p01_ret_net": "p01_nonstress",
            "p005_ret_net": "p005_nonstress",
        }
    )
    paired = stress_stats.join(nonstress_stats, on=cell_cols, how="inner")
    return paired.with_columns(
        (pl.col("p05_stress") - pl.col("p05_nonstress")).alias("diff_p05"),
        (pl.col("p01_stress") - pl.col("p01_nonstress")).alias("diff_p01"),
        (pl.col("p005_stress") - pl.col("p005_nonstress")).alias("diff_p005"),
    )


def run() -> dict[str, dict[str, pl.DataFrame]]:
    out: dict[str, dict[str, pl.DataFrame]] = {}
    for classifier_id in _CLASSIFIERS:
        logger.info(
            "gate_efficiency_full_diagnostics.classifier_starting", classifier_id=classifier_id
        )
        df = _collect_joined_labels(classifier_id)

        # D3 -- pooled por resolução (mesma unidade de agregação do relatório original)
        d3_pooled = _lift_table(df, ["resolution_id", "symbol", "side"])
        # D2 -- por janela, LUNA/FTX explicitamente separadas
        d2_by_window = _lift_table(df, ["resolution_id", "window_name", "symbol", "side"])
        # D4 -- tail loss bruto, pareado por célula
        d4_paired = _paired_tail_loss_raw(df)

        out[classifier_id] = {
            "pooled": d3_pooled,
            "by_window": d2_by_window,
            "paired_tail_loss": d4_paired,
        }

        n_stress_global = int(df["_is_stress"].sum())
        logger.info(
            "gate_efficiency_full_diagnostics.classifier_done",
            classifier_id=classifier_id,
            n_labels=df.height,
            n_stress=n_stress_global,
            frac_stress=n_stress_global / df.height if df.height > 0 else float("nan"),
        )
    return out


if __name__ == "__main__":
    run()
