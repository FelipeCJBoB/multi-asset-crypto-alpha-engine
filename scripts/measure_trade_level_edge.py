"""`edge_bps`/`sharpe` por TRADE individual, não só por fold — fecha o
item P2 do roadmap "Caso 0/20" (Exhibit VIII). Hoje só existe a média
por fold (`fold_result.edge_bps`); esta análise pool TODOS os trades
individuais (via as predições OOS reais com `keep_predictions=True`,
`scripts/run_walk_forward_with_predictions.py`, commit `c3547a0`) pra
revelar se o agregado por fold esconde heterogeneidade — poucos trades
grandes carregando a média, ou uma distribuição ampla e consistente.

**Método**: mesmo join que `score_quality._join_oof_predictions_to_
labels` usa internamente (`is_oof & side_hat==side`, join com `labels`
por `(t0, side)`, `NOFILL` descartado) — reimplementado aqui porque a
função é privada do módulo e a granularidade exigida (trade a trade, não
agregada por fold) é diferente de qualquer consumidor existente.
"""

from __future__ import annotations

import sys

import numpy as np
import polars as pl
import structlog

from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.dataset import build_modeling_frame
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_VARIANTS: tuple[str, ...] = ("camada1", "camada0")
_SIDE_LABEL: dict[int, str] = {1: "long", -1: "short"}
_BPS_PER_UNIT = 10_000  # noqa: magic-number -- mesma constante nomeada de score_quality.py
_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_NOFILL = "NOFILL"


def _trades_for_combo(
    symbol: str, resolution_id: str, variant: str, mf_data: pl.DataFrame
) -> pl.DataFrame:
    pred_filename = f"alpha_walk_forward_predictions_{symbol}_{resolution_id}_{variant}.parquet"
    pred_path = EXPERIMENTS_DIR / pred_filename
    predictions = pl.read_parquet(pred_path)
    labels_small = mf_data.select(["t0", "side", "barrier_hit", "ret_net"]).with_columns(
        pl.col("t0").cast(_T0_DTYPE)
    )
    all_trades: list[pl.DataFrame] = []
    for side_value in (1, -1):
        preds_side = (
            predictions.filter(pl.col("is_oof") & (pl.col("side_hat") == side_value))
            .select(["t0", "side_hat", "fold_id"])
            .with_columns(pl.col("t0").cast(_T0_DTYPE))
        )
        joined = (
            preds_side.join(
                labels_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
            )
            .filter(pl.col("barrier_hit").cast(pl.Utf8) != _NOFILL)
            .with_columns(
                (pl.col("ret_net") * _BPS_PER_UNIT).alias("edge_bps"),
                pl.lit(_SIDE_LABEL[side_value]).alias("side_label"),
            )
        )
        all_trades.append(joined)
    return pl.concat(all_trades, how="vertical_relaxed") if all_trades else pl.DataFrame()


_PERCENTIL_CAUDA_BAIXA = 0.10  # noqa: magic-number -- definicao padrao de cauda (P10/P90)
_PERCENTIL_CAUDA_ALTA = 0.90  # noqa: magic-number


def _report_distribution(trades: pl.DataFrame, *, label: str) -> None:
    if trades.height == 0:
        logger.info("scripts.measure_trade_level_edge.sem_trades", label=label)
        return
    edge = trades["edge_bps"].to_numpy().astype(np.float64)
    n = edge.shape[0]
    mean = float(edge.mean())
    std = float(edge.std(ddof=1)) if n > 1 else float("nan")  # noqa: magic-number -- grau de liberdade minimo pro desvio-padrao amostral
    sharpe_per_trade = (
        mean / std if np.isfinite(std) and std != 0.0 else float("nan")  # noqa: unguarded-ratio -- guardado pelo ternario: so divide quando std finito e != 0
    )
    frac_positivos = float((edge > 0).mean())
    logger.info(
        "scripts.measure_trade_level_edge.distribuicao",
        label=label,
        n_trades=n,
        edge_bps_mean=round(mean, 3),
        edge_bps_median=round(float(np.median(edge)), 3),
        edge_bps_std=round(std, 3) if np.isfinite(std) else None,
        edge_bps_p10=round(float(np.quantile(edge, _PERCENTIL_CAUDA_BAIXA)), 3),
        edge_bps_p90=round(float(np.quantile(edge, _PERCENTIL_CAUDA_ALTA)), 3),
        edge_bps_min=round(float(edge.min()), 3),
        edge_bps_max=round(float(edge.max()), 3),
        sharpe_per_trade_nao_anualizado=(
            round(sharpe_per_trade, 4) if np.isfinite(sharpe_per_trade) else None
        ),
        frac_trades_positivos=round(frac_positivos, 4),
    )


def main() -> int:
    configure_logging(json_output=False)
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))

    for symbol, resolution_id in _CANDIDATOS:
        mf = build_modeling_frame(
            symbol=symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
        )
        for variant in _VARIANTS:
            trades = _trades_for_combo(symbol, resolution_id, variant, mf.data)
            _report_distribution(trades, label=f"{symbol}/{resolution_id} {variant} (pooled)")
            for side_label in ("long", "short"):
                side_trades = trades.filter(pl.col("side_label") == side_label)
                _report_distribution(
                    side_trades, label=f"{symbol}/{resolution_id} {variant} {side_label}"
                )

    logger.info("scripts.measure_trade_level_edge.concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
