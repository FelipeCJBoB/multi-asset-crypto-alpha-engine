"""Condicionamento por regime BARRA-A-BARRA — upgrade do proxy fold-a-
fold do item 16 (`AG-415`) para a granularidade ideal, usando as
predições OOS reais (`keep_predictions=True`, commit `c3547a0`). `R10`
(documento-fonte) sinaliza que a janela de teste é um único regime
macro; `AG-415` já mediu heterogeneidade REAL entre folds em
`E16f_global_ls_ratio` (as 2 features SHAP-dominantes), mas sem
correlação detectável na granularidade de fold (n=36-46, poder baixo).
Esta versão usa TODAS as barras OOS (milhares, não dezenas) — poder
estatístico ordens de magnitude maior.

**Método**: tercis GLOBAIS (pooled entre os 5 combos) de `E05f_time_to_
funding_h`/`E16f_global_ls_ratio` sobre as barras OOS, definindo 3
buckets de regime (baixo/médio/alto) por feature. Para cada bucket:

- **AUC condicional** — MESMO join de `score_quality._join_full_
  population_to_labels` (`AG-394`): `p_long`/`p_short` vs. vitória
  econômica (`ret_net>0`) sobre TODA barra OOS (não só as operadas) —
  testa se o modelo discrimina melhor DENTRO de algum regime.
- **`edge_bps` condicional** — só trades realizados (`side_hat!=0`,
  `NOFILL` descartado, mesmo join de `_join_oof_predictions_to_labels`/
  `scripts/measure_trade_level_edge.py`) — testa se o edge realizado é
  maior num regime específico.
"""

from __future__ import annotations

import sys

import numpy as np
import polars as pl
import structlog
from sklearn.metrics import roc_auc_score

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
_REGIME_FEATURES: tuple[str, ...] = ("E05f_time_to_funding_h", "E16f_global_ls_ratio")
_N_BUCKETS = 3  # noqa: magic-number -- tercis, mesma granularidade grosseira do proxy fold-a-fold AG-415
_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_NOFILL = "NOFILL"
_BPS_PER_UNIT = 10_000  # noqa: magic-number -- mesma constante nomeada de score_quality.py
_MIN_OBS_FOR_AUC = 30  # noqa: magic-number -- piso pratico pra roc_auc_score nao degenerar em bucket pequeno


def _full_population_rows(
    predictions: pl.DataFrame, labels_small: pl.DataFrame, side_value: int
) -> pl.DataFrame:
    """Réplica de `score_quality._join_full_population_to_labels` (AG-394)
    -- 1 linha por barra OOS (não só as operadas), score contínuo do lado
    pedido vs. outcome REALIZADO desse lado."""
    score_col = "p_long" if side_value == 1 else "p_short"
    preds_side = (
        predictions.filter(pl.col("is_oof"))
        .select(["t0", score_col])
        .rename({score_col: "score"})
        .with_columns(pl.lit(side_value, dtype=pl.Int8).alias("side_hat"))
    )
    return (
        preds_side.join(
            labels_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
        )
        .filter(pl.col("barrier_hit").cast(pl.Utf8) != _NOFILL)
        .drop("side_hat")
    )


def _realized_trade_rows(predictions: pl.DataFrame, labels_small: pl.DataFrame) -> pl.DataFrame:
    """Réplica de `score_quality._join_oof_predictions_to_labels`
    (`scripts/measure_trade_level_edge.py`) -- só trades de fato
    decididos pelo modelo (`side_hat!=0`)."""
    frames = []
    for side_value in (1, -1):
        preds_side = predictions.filter(
            pl.col("is_oof") & (pl.col("side_hat") == side_value)
        ).select(["t0", "side_hat"])
        joined = preds_side.join(
            labels_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
        ).filter(pl.col("barrier_hit").cast(pl.Utf8) != _NOFILL)
        frames.append(joined)
    return pl.concat(frames, how="vertical_relaxed")


def _load_all(vol_estimator_id: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Retorna (full_population_rows, realized_trade_rows), ambas com as
    2 features de regime já anexadas, pooled entre os 5 combos x 2
    camadas."""
    full_pop_frames = []
    realized_frames = []
    for symbol, resolution_id in _CANDIDATOS:
        mf = build_modeling_frame(
            symbol=symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
        )
        labels_small = mf.data.select(
            ["t0", "side", "barrier_hit", "ret_net", *_REGIME_FEATURES]
        ).with_columns(pl.col("t0").cast(_T0_DTYPE))
        for variant in _VARIANTS:
            pred_filename = (
                f"alpha_walk_forward_predictions_{symbol}_{resolution_id}_{variant}.parquet"
            )
            predictions = pl.read_parquet(EXPERIMENTS_DIR / pred_filename).with_columns(
                pl.col("t0").cast(_T0_DTYPE)
            )
            for side_value, side_label in ((1, "long"), (-1, "short")):
                rows = _full_population_rows(predictions, labels_small, side_value)
                full_pop_frames.append(
                    rows.with_columns(
                        pl.lit(f"{symbol}/{resolution_id}").alias("combo"),
                        pl.lit(variant).alias("variant"),
                        pl.lit(side_label).alias("side_label"),
                    )
                )
            realized = _realized_trade_rows(predictions, labels_small)
            realized_frames.append(
                realized.with_columns(
                    pl.lit(f"{symbol}/{resolution_id}").alias("combo"),
                    pl.lit(variant).alias("variant"),
                )
            )
            logger.info(
                "scripts.measure_bar_level_regime_conditioning.carregado",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
            )
    full_pop = pl.concat(full_pop_frames, how="vertical_relaxed")
    realized = pl.concat(realized_frames, how="vertical_relaxed")
    return full_pop, realized


def _bucket_labels(values: pl.Series, boundaries: list[float]) -> pl.Series:
    return values.cut(boundaries, labels=[f"b{i}" for i in range(len(boundaries) + 1)])


def _tercil_boundaries(values: pl.Series) -> list[float]:
    fracoes = (
        1.0 / _N_BUCKETS,  # noqa: unguarded-ratio -- _N_BUCKETS=3, constante fixa do modulo, nunca 0
        2.0 / _N_BUCKETS,  # noqa: unguarded-ratio -- idem
    )
    return [float(values.quantile(q)) for q in fracoes]  # type: ignore[arg-type]


def _report_auc_by_bucket(full_pop: pl.DataFrame, feature: str) -> None:
    boundaries = _tercil_boundaries(full_pop[feature])
    bucketed = full_pop.with_columns(_bucket_labels(full_pop[feature], boundaries).alias("bucket"))
    for bucket in sorted(bucketed["bucket"].unique().to_list()):
        for side_label in ("long", "short"):
            sub = bucketed.filter(
                (pl.col("bucket") == bucket) & (pl.col("side_label") == side_label)
            )
            y_true = (sub["ret_net"] > 0.0).to_numpy().astype(np.int64)
            y_score = sub["score"].to_numpy().astype(np.float64)
            n = y_true.shape[0]
            if n < _MIN_OBS_FOR_AUC or len(np.unique(y_true)) < 2:  # noqa: magic-number -- roc_auc_score exige as 2 classes presentes
                logger.info(
                    "scripts.measure_bar_level_regime_conditioning.auc_bucket_insuficiente",
                    feature=feature,
                    bucket=bucket,
                    side=side_label,
                    n=n,
                )
                continue
            auc = float(roc_auc_score(y_true, y_score))
            logger.info(
                "scripts.measure_bar_level_regime_conditioning.auc_por_bucket",
                feature=feature,
                bucket=bucket,
                side=side_label,
                n=n,
                roc_auc=round(auc, 4),
            )


def _report_edge_by_bucket(realized: pl.DataFrame, feature: str) -> None:
    boundaries = _tercil_boundaries(realized[feature])
    trades = realized.with_columns(
        (pl.col("ret_net") * _BPS_PER_UNIT).alias("edge_bps"),
        _bucket_labels(realized[feature], boundaries).alias("bucket"),
    )
    for bucket in sorted(trades["bucket"].unique().to_list()):
        sub = trades.filter(pl.col("bucket") == bucket)
        if sub.height == 0:
            continue
        edge = sub["edge_bps"].to_numpy().astype(np.float64)
        logger.info(
            "scripts.measure_bar_level_regime_conditioning.edge_por_bucket",
            feature=feature,
            bucket=bucket,
            n_trades=edge.shape[0],
            edge_bps_mean=round(float(edge.mean()), 3),
            edge_bps_median=round(float(np.median(edge)), 3),
            frac_positivos=round(float((edge > 0).mean()), 4),
        )


def main() -> int:
    configure_logging(json_output=False)
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))

    full_pop, realized = _load_all(vol_estimator_id)
    logger.info(
        "scripts.measure_bar_level_regime_conditioning.total_carregado",
        n_full_population=full_pop.height,
        n_trades_realizados=realized.height,
    )

    for feature in _REGIME_FEATURES:
        _report_auc_by_bucket(full_pop, feature)
        _report_edge_by_bucket(realized, feature)

    logger.info("scripts.measure_bar_level_regime_conditioning.concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
