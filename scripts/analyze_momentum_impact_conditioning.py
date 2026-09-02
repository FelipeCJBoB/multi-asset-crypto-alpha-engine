"""Junta `ModelingFrame.data` (features T1 + labels reais, `A04_log_
return_12`/`A11_true_range_pct`/`n_bars_held`/`barrier_hit`/`ret_net`/
`cost_entry_bps`/`cost_exit_bps`) com as predictions OOS reais
(`alpha_walk_forward_predictions_{symbol}_{resolution_id}_camada1.
parquet`, `run_walk_forward_with_predictions`) pra medir, por decil de
`A04`/`A11` no momento do sinal:

(4) holding period / horizonte -- `n_bars_held` e `ret_net` realizados
    por decil de |A04_log_return_12|, checando se o horizonte de 12
    barras da feature bate com o holding period real (~1-3 barras,
    AG-372).
(5) fill rate / custo -- `fill_rate` e `cost_entry_bps+cost_exit_bps`
    (só nos preenchidos) por decil de `A11_true_range_pct`, checando a
    tese da própria feature ("quem fornece liquidez em barra de alto
    impacto pode sofrer seleção adversa").

Leitura pura de artefatos já em disco (`ModelingFrame` não retreina
nada -- só monta features+labels) + `build_modeling_frame`, que
recomputa features/labels a partir do lake (não usa GPU, não treina
LightGBM). Não escreve nada em produção -- só imprime/grava um relatório
em `experiments/`.

Uso:

    uv run python -m scripts.analyze_momentum_impact_conditioning
"""

from __future__ import annotations

import orjson
import polars as pl
import structlog

from src.models import dataset as ds
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_N_DECILES = 10


def _decile_report(
    joined: pl.DataFrame, *, feature: str, value_cols: tuple[str, ...]
) -> list[dict[str, object]]:
    ranked = joined.with_columns(
        (pl.col(feature).rank(method="ordinal") / pl.len() * _N_DECILES)
        .ceil()
        .clip(1, _N_DECILES)
        .cast(pl.Int64)
        .alias("decile")
    )
    agg_exprs = [pl.len().alias("n")]
    for col in value_cols:
        agg_exprs.append(pl.col(col).mean().alias(f"{col}_mean"))
    out = ranked.group_by("decile").agg(agg_exprs).sort("decile")
    return out.to_dicts()


def main() -> int:
    configure_logging(json_output=False)
    report: dict[str, object] = {}

    for symbol, resolution_id in _CANDIDATOS:
        key = f"{symbol}/{resolution_id}"
        preds_path = (
            EXPERIMENTS_DIR
            / f"alpha_walk_forward_predictions_{symbol}_{resolution_id}_camada1.parquet"
        )
        preds = pl.read_parquet(preds_path).filter(
            (pl.col("is_oof")) & (pl.col("side_hat") != 0)
        )
        vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
        mf = ds.build_modeling_frame(
            symbol=symbol,
            tf="15m",
            resolution_id=resolution_id,
            vol_estimator_id=vol_estimator_id,
        )

        joined = preds.select("t0", "side_hat", "fold_id").join(
            mf.data.select(
                "t0",
                "side",
                "A04_log_return_12",
                "A11_true_range_pct",
                "barrier_hit",
                "ret_net",
                "n_bars_held",
                "cost_entry_bps",
                "cost_exit_bps",
                "adverse_selection_bps",
            ),
            left_on=["t0", "side_hat"],
            right_on=["t0", "side"],
            how="inner",
        )
        n_signals = joined.height
        filled = joined.filter(pl.col("barrier_hit") != "NOFILL")
        n_filled = filled.height
        fill_rate = n_filled / n_signals if n_signals else float("nan")

        joined_abs_a04 = joined.with_columns(pl.col("A04_log_return_12").abs().alias("abs_a04"))
        holding_report = _decile_report(
            joined_abs_a04.filter(pl.col("barrier_hit") != "NOFILL"),
            feature="abs_a04",
            value_cols=("n_bars_held", "ret_net"),
        )

        cost_report_rows: list[dict[str, object]] = []
        ranked_a11 = joined.with_columns(
            (pl.col("A11_true_range_pct").rank(method="ordinal") / pl.len() * _N_DECILES)
            .ceil()
            .clip(1, _N_DECILES)
            .cast(pl.Int64)
            .alias("decile")
        )
        for d in range(1, _N_DECILES + 1):
            bucket = ranked_a11.filter(pl.col("decile") == d)
            n_bucket = bucket.height
            bucket_filled = bucket.filter(pl.col("barrier_hit") != "NOFILL")
            n_bucket_filled = bucket_filled.height
            bucket_fill_rate = n_bucket_filled / n_bucket if n_bucket else float("nan")
            fee_series = bucket_filled["cost_entry_bps"] + bucket_filled["cost_exit_bps"]
            fee_mean_raw = fee_series.mean()
            fee_mean = (
                float(fee_mean_raw)  # type: ignore[arg-type]
                if n_bucket_filled and fee_mean_raw is not None
                else float("nan")
            )
            adverse_raw = bucket_filled["adverse_selection_bps"].mean()
            adverse_mean = (
                float(adverse_raw)  # type: ignore[arg-type]
                if n_bucket_filled and adverse_raw is not None
                else float("nan")
            )
            cost_report_rows.append(
                {
                    "decile": d,
                    "n": n_bucket,
                    "fill_rate": bucket_fill_rate,
                    "fee_bps_mean": fee_mean,
                    "adverse_selection_bps_mean": adverse_mean,
                }
            )

        report[key] = {
            "n_signals": n_signals,
            "n_filled": n_filled,
            "fill_rate_geral": fill_rate,
            "holding_por_decil_abs_a04": holding_report,
            "custo_fill_por_decil_a11": cost_report_rows,
        }
        logger.info(
            "analyze_momentum_impact_conditioning.combo_ok",
            key=key,
            n_signals=n_signals,
            fill_rate=fill_rate,
        )

    dest = EXPERIMENTS_DIR / "momentum_impact_conditioning_5_candidatos_20260902.json"
    dest.write_bytes(orjson.dumps(report, option=orjson.OPT_INDENT_2))
    logger.info("analyze_momentum_impact_conditioning.escrito", dest=str(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
