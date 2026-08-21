"""Diagnóstico D1 do parecer de auditoria externa (2026-08-20,
`docs/parecer_auditoria_externa_ag114_ag118.md` — colado pelo Manager,
não persistido ainda como arquivo próprio neste momento). Pergunta:
`is_stress_bucket` (HMM k=4, via `identify_stress_state_by_volatility`)
é redundante com decil de `atr_at_t0`?

Reusa 100% da mecânica já validada de `src/analysis/gate_efficiency.py`
(mesmos joins, mesma identificação de bucket de stress) -- zero fit novo,
zero fórmula nova, só uma tabulação cruzada em cima do que já foi
computado pra medir `GateEfficiencyResult`.

PENDENTE-DE-EXECUÇÃO-HUMANA normalmente (protocolo do projeto) -- mas
executado diretamente nesta sessão sob a autorização ampla já concedida
("Pode autorizar executar uv e .py")."""

from __future__ import annotations

import polars as pl
import structlog

from src.analysis import gate_efficiency as ge
from src.analysis import m4_critical_windows as mcw
from src.labels.triple_barrier import LabelConfig
from src.validation.regime_utility import identify_stress_state_by_volatility

logger = structlog.get_logger(__name__)


def run(classifier_id: str = "hmm_gaussian_k4_v1") -> None:
    windows = mcw.CRITICAL_WINDOWS
    all_symbols = tuple(sorted({s for w in windows for s in w.symbols}))
    labels_by_symbol = mcw._load_labels_by_symbol(all_symbols)
    label_cfg = LabelConfig.from_constants(tf=mcw._HETEROGENEITY_LABELS_TF)
    del label_cfg  # não usado aqui -- só precisamos de labels_full cru, não de StratumMetrics

    rows: list[pl.DataFrame] = []
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
                rows.append(
                    joined.select(
                        pl.lit(resolution_id).alias("resolution_id"),
                        pl.lit(window.name).alias("window_name"),
                        pl.lit(symbol).alias("symbol"),
                        pl.col("atr_at_t0"),
                        pl.col("_is_stress"),
                    )
                )

    pooled = pl.concat(rows)
    # stub de pl.Series.mean() devolve união ampla demais (int|float|Decimal|
    # date|...) -- o dtype real da coluna é Boolean, valor é sempre float.
    frac_stress_global = pooled["_is_stress"].mean()
    assert frac_stress_global is not None  # pooled não-vazio, sem nulls em _is_stress
    logger.info(
        "crosscheck.pooled_rows",
        classifier_id=classifier_id,
        n_total_labels=pooled.height,
        n_stress=int(pooled["_is_stress"].sum()),
        frac_stress_global=float(frac_stress_global),  # type: ignore[arg-type]
    )

    deciles = pooled.select(
        pl.col("atr_at_t0").qcut(10, labels=[str(i) for i in range(1, 11)]).alias("atr_decile")
    )
    with_decile = pooled.with_columns(deciles["atr_decile"])
    summary = (
        with_decile.group_by("atr_decile")
        .agg(
            pl.len().alias("n"),
            pl.col("_is_stress").mean().alias("frac_stress"),
            pl.col("atr_at_t0").min().alias("atr_min"),
            pl.col("atr_at_t0").max().alias("atr_max"),
        )
        .sort("atr_decile")
    )
    for row in summary.iter_rows(named=True):
        logger.info(
            "crosscheck.decile",
            decile=row["atr_decile"],
            atr_min=row["atr_min"],
            atr_max=row["atr_max"],
            n=row["n"],
            frac_stress=row["frac_stress"],
        )

    # Resposta direta a D1: qual fração dos labels em is_stress=True cai
    # nos 2 decis superiores de ATR? Esperado ~0,20 se independente.
    top2_atr_quantile = pooled["atr_at_t0"].quantile(0.8)
    assert top2_atr_quantile is not None  # pooled não-vazio, sem nulls em atr_at_t0
    top2_atr_threshold = float(top2_atr_quantile)
    stress_rows = pooled.filter(pl.col("_is_stress"))
    frac_in_top2 = (stress_rows["atr_at_t0"] >= top2_atr_threshold).mean()
    assert frac_in_top2 is not None  # stress_rows não-vazio (n_stress>0 confirmado no D1 original)
    frac_stress_in_top2_atr = float(frac_in_top2)  # type: ignore[arg-type]
    logger.info(
        "crosscheck.d1_answer",
        frac_stress_in_top2_atr_decile=frac_stress_in_top2_atr,
        expected_if_independent=0.20,
    )


if __name__ == "__main__":
    run()
