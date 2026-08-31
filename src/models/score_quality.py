"""ADR-008 Fase 1 — qualidade do SCORE final do Alpha: métricas de
classificação formal (ROC-AUC/PR-AUC/LogLoss/Brier) e de qualidade de
Alpha (Pearson IC/Spearman Rank IC/IC IR, Q10-Q1) sobre o `confidence`
calibrado — nunca calculadas antes neste motor para o output final do
modelo.

**Diferente de `src.models.monotonic.compute_ic_by_env` e de
`src.analysis.attribution.ic_by_regime`** — ambos medem IC de cada
FEATURE INDIVIDUAL contra `ret_net` (o primeiro decide o sinal de
`monotone_constraints` in-fold; o segundo é diagnóstico pós-hoc por
feature). Aqui o "x" é o SCORE FINAL calibrado do modelo (`confidence`),
não uma feature de entrada — mesma fórmula estatística, propósito
diferente (auditoria `docs/ADR-008_...md`, bloco 2/consultor: "não
confunda 'o classificador funciona' com 'o sinal tem valor econômico'").

**Por que vive em `src.models`, não `src.analysis`** — precisa ser
chamado de dentro de `src.models.pipeline.run_layer1_sprint` (report de
produção, não relatório exploratório separado), e o import-linter do
projeto proíbe `src.models` de importar `src.analysis`
(`pyproject.toml::"models não importa analysis"`). `_spearman_ic` abaixo
é uma cópia PEQUENA e deliberada de `src.analysis.ic_by_horizon.
spearman_ic` (mesmo contrato: `NaN` se qualquer lado for constante) —
duplicar 8 linhas é mais barato que promover a função pra uma camada
compartilhada só por isso; mesmo padrão de `src.models.baselines`, que já
importa `sklearn.metrics.roc_auc_score` direto em vez de reusar
`src.analysis`.

**Mesma convenção de join de `attribution.py::confidence_deciles_by_side`**
— por lado (`is_oof & side_hat==side`), `barrier_hit != NOFILL`
descartado — população IDÊNTICA, resultado comparável linha a linha com
o decile profile já existente (não chamado daqui pelo mesmo motivo de
layering; `q10_minus_q1_bps` abaixo é um bucketing por rank muito mais
simples, só a métrica de spread, não o perfil completo com CI95/t-stat
que `attribution.py` já cobre para uso exploratório). Long e short nunca
são pooled num único número: são classificadores/calibradores distintos,
misturar os dois inventaria uma população que não existe."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
from scipy.stats import rankdata
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

logger = structlog.get_logger(__name__)

_N_DECILES_Q_SPREAD = 10  # noqa: magic-number -- Q10-Q1, terminologia padrão do consultor/literatura de decile analysis
_BPS_PER_UNIT = 10_000  # mesma constante nomeada de hyperparams_optuna.py

_RET_NET_COL = "ret_net"
_BARRIER_HIT_COL = "barrier_hit"
_NOFILL = "NOFILL"
_CONFIDENCE_COL = "confidence"
_SIDE_LABEL_BY_HAT: dict[int, str] = {1: "long", -1: "short"}
_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_MIN_CLASSES_FOR_AUC = 2  # noqa: magic-number -- roc_auc_score exige as 2 classes presentes
_MIN_FOLDS_FOR_DISPERSION = 2  # noqa: magic-number -- desvio-padrão amostral (ddof=1) exige >=2 pontos


@dataclass(frozen=True, slots=True)
class ScoreQualityResult:
    side: str
    n_trades: int
    n_folds_com_ic: int
    roc_auc: float
    pr_auc: float
    log_loss: float
    brier_score: float
    pearson_ic: float
    spearman_ic_pooled: float
    spearman_ic_mean_por_fold: float
    spearman_ic_median_por_fold: float
    spearman_ic_std_por_fold: float
    ic_ir: float
    pct_ic_positive: float
    ic_tstat: float
    q10_minus_q1_bps: float


def _classification_metrics(
    y_true: np.ndarray, y_score: np.ndarray
) -> tuple[float, float, float, float]:
    """`NaN` se só 1 classe estiver presente (AUC/PR-AUC/LogLoss
    indefinidos, não "ruins") — mesma convenção já usada em
    `src.models.baselines._pool_auc`, não inventada aqui."""
    if np.unique(y_true).shape[0] < _MIN_CLASSES_FOR_AUC:
        return float("nan"), float("nan"), float("nan"), float("nan")
    auc = float(roc_auc_score(y_true, y_score))
    pr_auc = float(average_precision_score(y_true, y_score))
    ll = float(log_loss(y_true, y_score, labels=[0, 1]))
    brier = float(brier_score_loss(y_true, y_score))
    return auc, pr_auc, ll, brier


def _pearson_ic(x: np.ndarray, y: np.ndarray) -> float:
    """`NaN` se qualquer lado for constante — mesma convenção de
    `_spearman_ic` (correlação indefinida, não zero)."""
    if x.std() == 0.0 or y.std() == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _spearman_ic(x: np.ndarray, y: np.ndarray) -> float:
    """Cópia deliberada de `src.analysis.ic_by_horizon.spearman_ic` (ver
    docstring do módulo pra por quê não é importada) — mesmo contrato
    byte a byte: `NaN` se qualquer lado for constante, `rankdata` com
    empates resolvidos por média."""
    if x.shape[0] < 2:
        return float("nan")
    rx = rankdata(x)
    ry = rankdata(y)
    if float(rx.std()) == 0.0 or float(ry.std()) == 0.0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def _q10_minus_q1_bps(confidence: np.ndarray, ret_net: np.ndarray) -> float:
    """Bucketing por RANK (não `qcut` por valor — mesmo motivo de
    `attribution.confidence_deciles_by_side`: platôs de `confidence`
    idêntica do calibrador isotônico colapsariam decis sob `qcut`).
    `NaN` se `n < N_DECILES` (decil 1 ou 10 ficaria vazio)."""
    n = confidence.shape[0]
    if n < _N_DECILES_Q_SPREAD:
        return float("nan")
    order = np.argsort(confidence, kind="stable")
    decile_idx = (np.arange(n) * _N_DECILES_Q_SPREAD) // n
    ret_sorted = ret_net[order]
    q1_mean = float(ret_sorted[decile_idx == 0].mean())
    q10_mean = float(ret_sorted[decile_idx == _N_DECILES_Q_SPREAD - 1].mean())
    return (q10_mean - q1_mean) * _BPS_PER_UNIT


def _ic_dispersion_stats(fold_ics: list[float]) -> tuple[float, float, float, float, float, float]:
    """`(mean, median, std, ic_ir, pct_positive, tstat)` sobre os IC por
    fold já filtrados de `NaN`. `std`/`ic_ir`/`tstat` exigem `>=2` folds
    (desvio-padrão amostral indefinido com 1 ponto) — `NaN`, não
    `ZeroDivisionError`/`inf` silencioso, mesma convenção de
    `attribution.py::_decile_cell` (`t_stat`)."""
    n = len(fold_ics)
    if n == 0:
        nan = float("nan")
        return nan, nan, nan, nan, nan, nan
    arr = np.asarray(fold_ics, dtype=np.float64)
    mean = float(arr.mean())
    median = float(np.median(arr))
    pct_positive = float((arr > 0.0).mean())
    if n < _MIN_FOLDS_FOR_DISPERSION:
        return mean, median, float("nan"), float("nan"), pct_positive, float("nan")
    std = float(arr.std(ddof=1))
    if std == 0.0:
        return mean, median, std, float("nan"), pct_positive, float("nan")
    ic_ir = mean / std
    tstat = mean / (std / np.sqrt(n))
    return mean, median, std, ic_ir, pct_positive, tstat


def compute_score_quality(
    predictions: pl.DataFrame, labels: pl.DataFrame
) -> tuple[ScoreQualityResult, ...]:
    """`predictions` — `alpha.assemble_predictions_table(fold_results)`,
    precisa de `t0`, `side_hat`, `is_oof`, `fold_id`, `confidence`.
    `labels` — `mf.data` (`dataset.build_modeling_frame`), precisa de
    `t0`, `side`, `barrier_hit`, `ret_net`. Um `ScoreQualityResult` por
    lado com pelo menos 1 trade preenchido (`NOFILL` descartado, mesma
    população de `win_rate`/`sharpe_naive`) — lado sem trade nenhum fica
    ausente da tupla, não aparece com `NaN` (mesmo contrato de
    `confidence_deciles_by_side`)."""
    required_pred = ("t0", "side_hat", "is_oof", "fold_id", _CONFIDENCE_COL)
    ausentes_pred = tuple(c for c in required_pred if c not in predictions.columns)
    if ausentes_pred:
        raise ValueError(
            f"compute_score_quality: predictions sem {ausentes_pred} -- "
            f"colunas disponíveis: {sorted(predictions.columns)}"
        )
    # Sem nenhuma predição (0 folds -- ex. permutation_null_replicas>0
    # interrompe antes de treinar, mesmo cenário de teste de
    # `backtest_lite.realize_trades`), não há o que juntar contra
    # `labels` -- mesmo early-return de `realize_trades` (nunca toca
    # `df_all` quando `fold_results` está vazio), evita validar colunas
    # de um `labels` que pode legitimamente ser um stub mínimo neste
    # caso degenerado.
    if predictions.height == 0:
        return ()
    required_labels = ("t0", "side", _BARRIER_HIT_COL, _RET_NET_COL)
    ausentes_labels = tuple(c for c in required_labels if c not in labels.columns)
    if ausentes_labels:
        raise ValueError(
            f"compute_score_quality: labels sem {ausentes_labels} -- "
            f"colunas disponíveis: {sorted(labels.columns)}"
        )

    labels_small = labels.select(["t0", "side", _BARRIER_HIT_COL, _RET_NET_COL]).with_columns(
        pl.col("t0").cast(_T0_DTYPE)
    )

    results: list[ScoreQualityResult] = []
    for side_value, side_label in _SIDE_LABEL_BY_HAT.items():
        preds_side = (
            predictions.filter(pl.col("is_oof") & (pl.col("side_hat") == side_value))
            .select(["t0", "side_hat", "fold_id", _CONFIDENCE_COL])
            .with_columns(pl.col("t0").cast(_T0_DTYPE))
        )
        joined = preds_side.join(
            labels_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
        ).filter(pl.col(_BARRIER_HIT_COL).cast(pl.Utf8) != _NOFILL)

        if joined.height == 0:
            logger.warning("analysis.score_quality.sem_trades_no_lado", side=side_label)
            continue

        ret_net = joined[_RET_NET_COL].to_numpy().astype(np.float64)
        confidence = joined[_CONFIDENCE_COL].to_numpy().astype(np.float64)
        # win economico -- ret_net > 0, nao barrier_hit == "TP" (TIME pode
        # fechar positivo/negativo, SL raro pode fechar melhor -- mesma
        # convencao de backtest_lite.backtest_by_path::win_rate).
        y_true = (ret_net > 0.0).astype(np.int64)

        auc, pr_auc, ll, brier = _classification_metrics(y_true, confidence)
        pearson_ic = _pearson_ic(confidence, ret_net)
        spearman_pooled = _spearman_ic(confidence, ret_net)
        q_spread = _q10_minus_q1_bps(confidence, ret_net)

        fold_ics: list[float] = []
        for fold_id in sorted(joined["fold_id"].unique().to_list()):
            sub = joined.filter(pl.col("fold_id") == fold_id)
            ic = _spearman_ic(
                sub[_CONFIDENCE_COL].to_numpy().astype(np.float64),
                sub[_RET_NET_COL].to_numpy().astype(np.float64),
            )
            if not np.isnan(ic):
                fold_ics.append(ic)

        ic_mean, ic_median, ic_std, ic_ir, pct_positive, ic_tstat = _ic_dispersion_stats(fold_ics)

        result = ScoreQualityResult(
            side=side_label,
            n_trades=joined.height,
            n_folds_com_ic=len(fold_ics),
            roc_auc=auc,
            pr_auc=pr_auc,
            log_loss=ll,
            brier_score=brier,
            pearson_ic=pearson_ic,
            spearman_ic_pooled=spearman_pooled,
            spearman_ic_mean_por_fold=ic_mean,
            spearman_ic_median_por_fold=ic_median,
            spearman_ic_std_por_fold=ic_std,
            ic_ir=ic_ir,
            pct_ic_positive=pct_positive,
            ic_tstat=ic_tstat,
            q10_minus_q1_bps=q_spread,
        )
        results.append(result)
        logger.info(
            "analysis.score_quality.computed",
            side=side_label,
            n_trades=result.n_trades,
            n_folds_com_ic=result.n_folds_com_ic,
            roc_auc=result.roc_auc,
            spearman_ic_pooled=result.spearman_ic_pooled,
            ic_ir=result.ic_ir,
        )

    return tuple(results)
