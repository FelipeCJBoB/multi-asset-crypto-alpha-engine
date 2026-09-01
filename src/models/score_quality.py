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
misturar os dois inventaria uma população que não existe.

**`compute_train_val_test_gap` (ADR-008 Fase 3)** — mesmas métricas
aplicadas aos 3 sub-splits IN-SAMPLE que treinaram o modelo
(`fit`/`stop`/`calib`, via `alpha.SideModelResult.fit_segment`/
`stop_segment`/`calib_segment`), pooled entre folds do combo. Nunca a
mesma população de `compute_score_quality` (OOF) — existe só para medir
o generalization gap (`gap_fit_minus_stop`) contra o número OOF, nunca
consumida por decisão de produção/gate. `y_true` usa a MESMA convenção
de vitória econômica (`ret_net > 0`, não `label` bruto) que
`compute_score_quality` — necessário pra `fit`/`stop`/`calib` e OOF
serem comparáveis pela mesma definição.

**`compute_decile_profile` (ADR-008 Fase 5)** — perfil COMPLETO de 10
decis (não só o spread `Q10-Q1` que `ScoreQualityResult.q10_minus_q1_
bps` já expõe) — eixo "decile returns" da stability matrix
(`src.analysis.stability_matrix`, cruza Fold × {IC, AUC/LogLoss, feature
gain, decile returns}). MESMA população/join que `compute_score_quality`
(`_join_oof_predictions_to_labels`, extraído pra não divergir entre as
duas) — os dois resultados são comparáveis linha a linha."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
from scipy.stats import rankdata
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from .alpha import FoldResult, InSampleSegmentScores

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
_MIN_OBS_FOR_SMALL_SAMPLE_METRICS = 5  # noqa: magic-number -- mesmo piso de src.models.monotonic._MIN_OBS_PER_ENV (correção 2026-08-31, audit_engineering/ADR-008): n<5 produz correlação/AUC degenerada (n=2 sempre dá ±1,0/1,0), achado real materializado em experiments/alpha_walk_forward_BTCUSDT_R2.json (fold_id=10, n_trades=2, spearman_ic=0,9999.../roc_auc=1.0/pr_auc=1.0)
_GAP_FIELDS: tuple[str, ...] = (
    "roc_auc",
    "pr_auc",
    "log_loss",
    "brier_score",
    "pearson_ic",
    "spearman_ic_pooled",
    "ic_ir",
    "q10_minus_q1_bps",
)


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
    `src.models.baselines._pool_auc`, não inventada aqui. `NaN` também
    se `n < _MIN_OBS_FOR_SMALL_SAMPLE_METRICS` — com amostra minúscula
    (ex. n=2) o AUC tende a ser exatamente 0,0/1,0 por separação
    perfeita ao acaso, não por poder discriminativo real (correção
    2026-08-31, ver docstring da constante)."""
    if y_true.shape[0] < _MIN_OBS_FOR_SMALL_SAMPLE_METRICS:
        return float("nan"), float("nan"), float("nan"), float("nan")
    if np.unique(y_true).shape[0] < _MIN_CLASSES_FOR_AUC:
        return float("nan"), float("nan"), float("nan"), float("nan")
    auc = float(roc_auc_score(y_true, y_score))
    pr_auc = float(average_precision_score(y_true, y_score))
    ll = float(log_loss(y_true, y_score, labels=[0, 1]))
    brier = float(brier_score_loss(y_true, y_score))
    return auc, pr_auc, ll, brier


def _pearson_ic(x: np.ndarray, y: np.ndarray) -> float:
    """`NaN` se qualquer lado for constante — mesma convenção de
    `_spearman_ic` (correlação indefinida, não zero). `NaN` também se
    `n < _MIN_OBS_FOR_SMALL_SAMPLE_METRICS` — com 2-4 pontos a
    correlação de Pearson é quase sempre ±1,0 (linha por 2 pontos),
    não informativa (correção 2026-08-31, mesmo piso de `_spearman_ic`
    abaixo)."""
    if x.shape[0] < _MIN_OBS_FOR_SMALL_SAMPLE_METRICS:
        return float("nan")
    if x.std() == 0.0 or y.std() == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _spearman_ic(x: np.ndarray, y: np.ndarray) -> float:
    """Cópia deliberada de `src.analysis.ic_by_horizon.spearman_ic` (ver
    docstring do módulo pra por quê não é importada) — mesmo contrato
    byte a byte: `NaN` se qualquer lado for constante, `rankdata` com
    empates resolvidos por média. Piso `n < _MIN_OBS_FOR_SMALL_SAMPLE_
    METRICS` (correção 2026-08-31) — mesmo piso já adotado em
    `src.models.monotonic._MIN_OBS_PER_ENV` pro mesmo tipo de
    correlação: com `n=2-4`, Spearman degenera pra exatamente ±1,0
    (ou empate), contaminando estatísticas agregadas por fold/segmento
    sem carregar informação real (achado real de auditoria, ver
    constante)."""
    if x.shape[0] < _MIN_OBS_FOR_SMALL_SAMPLE_METRICS:
        return float("nan")
    rx = rankdata(x)
    ry = rankdata(y)
    if float(rx.std()) == 0.0 or float(ry.std()) == 0.0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def _decile_buckets(confidence: np.ndarray, ret_net: np.ndarray) -> list[tuple[int, float]] | None:
    """`[(n_trades, mean_ret_net), ...]` por decil (1..10, rank-based).
    Bucketing por RANK (não `qcut` por valor — mesmo motivo de
    `attribution.confidence_deciles_by_side`: platôs de `confidence`
    idêntica do calibrador isotônico colapsariam decis sob `qcut`).
    `None` se `n < N_DECILES` (decil 1 ou 10 ficaria vazio) — núcleo
    compartilhado de `_q10_minus_q1_bps` (só os extremos) e
    `compute_decile_profile` (perfil completo, ADR-008 Fase 5)."""
    n = confidence.shape[0]
    if n < _N_DECILES_Q_SPREAD:
        return None
    order = np.argsort(confidence, kind="stable")
    decile_idx = (np.arange(n) * _N_DECILES_Q_SPREAD) // n  # noqa: unguarded-ratio -- n>=_N_DECILES_Q_SPREAD ja garantido pelo early-return acima nesta funcao
    ret_sorted = ret_net[order]
    return [
        (int((decile_idx == d).sum()), float(ret_sorted[decile_idx == d].mean()))
        for d in range(_N_DECILES_Q_SPREAD)
    ]


def _q10_minus_q1_bps(confidence: np.ndarray, ret_net: np.ndarray) -> float:
    buckets = _decile_buckets(confidence, ret_net)
    if buckets is None:
        return float("nan")
    return (buckets[-1][1] - buckets[0][1]) * _BPS_PER_UNIT


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
    # `np.sqrt(n)` devolve numpy.float64 -- sem o `float(...)` explicito
    # aqui, `tstat` vaza numpy.float64 pro dataclass (`ScoreQualityResult.
    # ic_tstat: float`, violado em runtime) e `orjson.dumps` quebra com
    # "Type is not JSON serializable: numpy.float64" (orjson despacha por
    # `type(x) is float`, nao `isinstance` -- numpy.float64 falha mesmo
    # sendo subclasse). Achado real: nunca disparou em `score_quality_by_
    # side` (poucos folds tipicamente sob o piso de dispersao), mas
    # `train_val_test_gap` pooled entre MUITOS folds por segmento
    # atravessa o piso quase sempre -- so apareceu ao escrever o artefato
    # com esse campo novo pela primeira vez.
    tstat = float(mean / (std / np.sqrt(n)))  # noqa: unguarded-ratio -- std!=0.0 e n>=_MIN_FOLDS_FOR_DISPERSION ja garantidos pelos 2 early-return acima nesta funcao
    return mean, median, std, ic_ir, pct_positive, tstat


def _validate_predictions_columns(predictions: pl.DataFrame, fn_name: str) -> None:
    required_pred = ("t0", "side_hat", "is_oof", "fold_id", _CONFIDENCE_COL)
    ausentes_pred = tuple(c for c in required_pred if c not in predictions.columns)
    if ausentes_pred:
        raise ValueError(
            f"{fn_name}: predictions sem {ausentes_pred} -- "
            f"colunas disponíveis: {sorted(predictions.columns)}"
        )


def _validate_predictions_columns_full_population(predictions: pl.DataFrame, fn_name: str) -> None:
    """AG-394 — colunas exigidas por `compute_score_quality_full_
    population`: diferente de `_validate_predictions_columns`, não exige
    `side_hat`/`confidence` (construídos sinteticamente aqui a partir de
    `p_long`/`p_short`, que existem por barra independente de qual lado
    o modelo decidiu operar)."""
    required_pred = ("t0", "is_oof", "fold_id", "p_long", "p_short")
    ausentes_pred = tuple(c for c in required_pred if c not in predictions.columns)
    if ausentes_pred:
        raise ValueError(
            f"{fn_name}: predictions sem {ausentes_pred} -- "
            f"colunas disponíveis: {sorted(predictions.columns)}"
        )


def _validate_labels_columns(labels: pl.DataFrame, fn_name: str) -> None:
    required_labels = ("t0", "side", _BARRIER_HIT_COL, _RET_NET_COL)
    ausentes_labels = tuple(c for c in required_labels if c not in labels.columns)
    if ausentes_labels:
        raise ValueError(
            f"{fn_name}: labels sem {ausentes_labels} -- "
            f"colunas disponíveis: {sorted(labels.columns)}"
        )


def _join_oof_predictions_to_labels(
    predictions: pl.DataFrame, labels_small: pl.DataFrame, side_value: int
) -> pl.DataFrame:
    """Join `predictions` (`is_oof & side_hat==side_value`) contra
    `labels_small` por `(t0, side_hat=side)`, `NOFILL` descartado —
    núcleo compartilhado de `compute_score_quality`/`compute_decile_
    profile` (a MESMA população nas duas, nunca diverge).

    `.sort([_CONFIDENCE_COL, "t0"])` no final (correção 2026-08-31) —
    Polars não garante ordem de linha em `.join()` (hash join, ordem
    pode variar entre execuções/máquinas), e `_decile_buckets` desempata
    platôs de `confidence` idêntica (comuns sob calibrador isotônico,
    função-degrau) via `np.argsort(..., kind="stable")`, que só preserva
    a ordem que as linhas JÁ tinham na entrada — sem este sort, o
    resultado do desempate (e portanto `q10_minus_q1_bps`) não é
    reprodutível entre execuções. Mesmo padrão de
    `attribution.py::_deciles_for_side` (`joined.sort([_CONFIDENCE_COL,
    "t0"])`), citado como convenção-espelho na docstring do módulo mas
    até esta correção não replicado aqui."""
    preds_side = (
        predictions.filter(pl.col("is_oof") & (pl.col("side_hat") == side_value))
        .select(["t0", "side_hat", "fold_id", _CONFIDENCE_COL])
        .with_columns(pl.col("t0").cast(_T0_DTYPE))
    )
    return (
        preds_side.join(
            labels_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
        )
        .filter(pl.col(_BARRIER_HIT_COL).cast(pl.Utf8) != _NOFILL)
        .sort([_CONFIDENCE_COL, "t0"])
    )


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
    _validate_predictions_columns(predictions, "compute_score_quality")
    # Sem nenhuma predição (0 folds -- ex. permutation_null_replicas>0
    # interrompe antes de treinar, mesmo cenário de teste de
    # `backtest_lite.realize_trades`), não há o que juntar contra
    # `labels` -- mesmo early-return de `realize_trades` (nunca toca
    # `df_all` quando `fold_results` está vazio), evita validar colunas
    # de um `labels` que pode legitimamente ser um stub mínimo neste
    # caso degenerado.
    if predictions.height == 0:
        return ()
    _validate_labels_columns(labels, "compute_score_quality")

    labels_small = labels.select(["t0", "side", _BARRIER_HIT_COL, _RET_NET_COL]).with_columns(
        pl.col("t0").cast(_T0_DTYPE)
    )

    results: list[ScoreQualityResult] = []
    for side_value, side_label in _SIDE_LABEL_BY_HAT.items():
        joined = _join_oof_predictions_to_labels(predictions, labels_small, side_value)

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


def _join_full_population_to_labels(
    predictions: pl.DataFrame, labels_small: pl.DataFrame, side_value: int
) -> pl.DataFrame:
    """AG-394 — mesmo núcleo de `_join_oof_predictions_to_labels`, mas SEM
    o filtro `side_hat == side_value`: junta TODA barra de teste
    (`is_oof`), não só as que o modelo decidiu operar (`confidence > tau`
    E venceu a competição long-vs-short, `alpha.py:625-629`). Usa
    `p_long`/`p_short` — o score calibrado CONTÍNUO, sempre presente por
    barra (`alpha.py:2304-2305`) — em vez de `confidence`, que já colapsa
    pro lado vencedor via `np.maximum(p_long, p_short)` (`alpha.py:2224`)
    e por isso não existe fora da população selecionada.

    `barrier_hit != NOFILL` continua descartado — precisa de outcome
    realizado pra existir `y_true`, mesmo requisito de `_join_oof_
    predictions_to_labels`. Resultado: mesma pergunta estatística
    (`ret_net > 0` como rótulo), população MAIOR e sem o corte por
    `tau`/competição de lado — mede poder discriminativo POPULACIONAL,
    não informação marginal dentro da cauda já selecionada (ver docstring
    do módulo e `docs/adendo_angulos_7_8_..._2026-08-31.md`)."""
    score_col = "p_long" if side_value == 1 else "p_short"
    preds_side = (
        predictions.filter(pl.col("is_oof"))
        .select(["t0", "fold_id", score_col])
        .rename({score_col: _CONFIDENCE_COL})
        .with_columns(
            pl.col("t0").cast(_T0_DTYPE),
            pl.lit(side_value, dtype=pl.Int8).alias("side_hat"),
        )
    )
    return (
        preds_side.join(
            labels_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
        )
        .filter(pl.col(_BARRIER_HIT_COL).cast(pl.Utf8) != _NOFILL)
        .sort([_CONFIDENCE_COL, "t0"])
    )


def compute_score_quality_full_population(
    predictions: pl.DataFrame, labels: pl.DataFrame
) -> tuple[ScoreQualityResult, ...]:
    """AG-394 (auditoria adversarial externa, prova D1;
    docs/prompts/REFUTACAO_CONSOLIDADA_0de20_20260831.md) — MESMA forma
    de `compute_score_quality`, população DIFERENTE: aqui é toda barra de
    teste com outcome realizado, não só as que cruzaram `tau` e venceram
    a competição long-vs-short. `compute_score_quality` mede informação
    marginal residual DENTRO da cauda que o modelo já selecionou (útil
    pra saber se o corte foi bem colocado); esta função mede poder
    discriminativo do score sobre a população de teste inteira (a
    pergunta que o gate Model da ADR-008 tentava responder e, por medir
    a população errada, não respondia — ver `AG-394`).

    As duas funções NUNCA devem ser confundidas por nome: mantidas
    deliberadamente com prefixos distintos (`compute_score_quality` vs
    `compute_score_quality_full_population`) e campos de report distintos
    (`score_quality_by_side` vs `score_quality_full_population_by_side`
    em `WalkForwardFoldMetrics`), não uma flag booleana no mesmo
    caminho — a diferença é a PERGUNTA respondida, não uma variação de
    implementação da mesma pergunta."""
    _validate_predictions_columns_full_population(
        predictions, "compute_score_quality_full_population"
    )
    if predictions.height == 0:
        return ()
    _validate_labels_columns(labels, "compute_score_quality_full_population")

    labels_small = labels.select(["t0", "side", _BARRIER_HIT_COL, _RET_NET_COL]).with_columns(
        pl.col("t0").cast(_T0_DTYPE)
    )

    results: list[ScoreQualityResult] = []
    for side_value, side_label in _SIDE_LABEL_BY_HAT.items():
        joined = _join_full_population_to_labels(predictions, labels_small, side_value)

        if joined.height == 0:
            logger.warning(
                "analysis.score_quality.full_population_sem_trades_no_lado", side=side_label
            )
            continue

        ret_net = joined[_RET_NET_COL].to_numpy().astype(np.float64)
        confidence = joined[_CONFIDENCE_COL].to_numpy().astype(np.float64)
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
            "analysis.score_quality.full_population_computed",
            side=side_label,
            n_trades=result.n_trades,
            roc_auc=result.roc_auc,
            spearman_ic_pooled=result.spearman_ic_pooled,
        )

    return tuple(results)


@dataclass(frozen=True, slots=True)
class DecileBucket:
    decile: int  # 1..10, 1 = confidence mais baixa, 10 = mais alta
    n_trades: int
    mean_ret_net_bps: float


@dataclass(frozen=True, slots=True)
class DecileProfileResult:
    side: str
    n_trades: int
    buckets: tuple[DecileBucket, ...]  # sempre 10, decile 1..10 em ordem
    q10_minus_q1_bps: float


def compute_decile_profile(
    predictions: pl.DataFrame, labels: pl.DataFrame
) -> tuple[DecileProfileResult, ...]:
    """Perfil COMPLETO de 10 decis de `confidence` × `ret_net` médio
    (ADR-008 Fase 5 — eixo "decile returns" da stability matrix,
    `src.analysis.stability_matrix`) — não só o spread `Q10-Q1` que
    `ScoreQualityResult.q10_minus_q1_bps` já expõe. MESMA
    população/join/contrato de colunas de `compute_score_quality`
    (`_join_oof_predictions_to_labels`) — os dois resultados são
    comparáveis linha a linha, incluindo `q10_minus_q1_bps` (mesmo
    valor, calculado sobre o mesmo `_decile_buckets`).

    Um `DecileProfileResult` por lado com pelo menos `_N_DECILES_Q_
    SPREAD` (10) trades preenchidos — lado sem trade suficiente pro
    bucketing fica ausente da tupla, mesmo contrato de `compute_score_
    quality` (nunca aparece com decis `NaN`)."""
    _validate_predictions_columns(predictions, "compute_decile_profile")
    if predictions.height == 0:
        return ()
    _validate_labels_columns(labels, "compute_decile_profile")

    labels_small = labels.select(["t0", "side", _BARRIER_HIT_COL, _RET_NET_COL]).with_columns(
        pl.col("t0").cast(_T0_DTYPE)
    )

    results: list[DecileProfileResult] = []
    for side_value, side_label in _SIDE_LABEL_BY_HAT.items():
        joined = _join_oof_predictions_to_labels(predictions, labels_small, side_value)
        if joined.height == 0:
            logger.warning(
                "analysis.score_quality.decile_profile_sem_trades_no_lado", side=side_label
            )
            continue

        ret_net = joined[_RET_NET_COL].to_numpy().astype(np.float64)
        confidence = joined[_CONFIDENCE_COL].to_numpy().astype(np.float64)
        buckets_raw = _decile_buckets(confidence, ret_net)
        if buckets_raw is None:
            logger.warning(
                "analysis.score_quality.decile_profile_amostra_insuficiente",
                side=side_label,
                n_trades=joined.height,
                n_deciles=_N_DECILES_Q_SPREAD,
                detail="menos de 10 trades -- decil 1 ou 10 ficaria vazio, perfil indefinido",
            )
            continue

        buckets = tuple(
            DecileBucket(decile=i + 1, n_trades=n, mean_ret_net_bps=mean * _BPS_PER_UNIT)
            for i, (n, mean) in enumerate(buckets_raw)
        )
        result = DecileProfileResult(
            side=side_label,
            n_trades=joined.height,
            buckets=buckets,
            q10_minus_q1_bps=buckets[-1].mean_ret_net_bps - buckets[0].mean_ret_net_bps,
        )
        results.append(result)
        logger.info(
            "analysis.score_quality.decile_profile_computed",
            side=side_label,
            n_trades=result.n_trades,
            q10_minus_q1_bps=result.q10_minus_q1_bps,
        )

    return tuple(results)


@dataclass(frozen=True, slots=True)
class TrainValTestGapResult:
    """ADR-008 Fase 3 — mesma forma de `ScoreQualityResult`, mas sobre os
    3 sub-splits IN-SAMPLE (`fit`/`stop`/`calib`) do MESMO fold/lado que
    treinou o modelo — nunca o OOF (`compute_score_quality`). `stop` é
    `None` fora de `EARLY_STOPPING_THREE_WAY` (nenhum fold do combo usou
    o modo three-way). `gap_fit_minus_stop` mede o "generalization gap"
    clássico train-vs-holdout: positivo em `roc_auc`/`ic_ir` = o modelo
    performa melhor no que ele viu direto no gradiente (`fit`) do que no
    bloco reservado pro early stopping (`stop`) — sinal de overfit;
    dict vazio (não `NaN` por campo) se `stop` é `None`."""

    side: str
    fit: ScoreQualityResult | None
    stop: ScoreQualityResult | None
    calib: ScoreQualityResult | None
    gap_fit_minus_stop: dict[str, float]


def _score_quality_from_segments(
    segments: list[InSampleSegmentScores], *, side: str
) -> ScoreQualityResult | None:
    """Pool de N segmentos in-sample (1 por fold, mesmo lado, mesmo
    sub-split fit/stop/calib) na MESMA forma de `ScoreQualityResult` que
    `compute_score_quality` produz para OOF — permite comparação direta
    campo a campo entre `report["score_quality"]` e
    `report["train_val_test_gap"]`. `None` se nenhum segmento tem `n>0`
    (ex. `stop` fora de `EARLY_STOPPING_THREE_WAY`)."""
    segments_nao_vazios = [s for s in segments if s.n > 0]
    if not segments_nao_vazios:
        return None

    calibrated_score = np.concatenate([s.calibrated_score for s in segments_nao_vazios])
    ret_net = np.concatenate([s.ret_net for s in segments_nao_vazios]).astype(np.float64)
    # vitória ECONÔMICA (`ret_net > 0`), nunca `label` bruto -- mesma
    # convenção de `compute_score_quality` acima (ver docstring do
    # módulo), necessária pra OOF e in-sample serem comparáveis pela
    # MESMA definição de "acerto".
    y_true = (ret_net > 0.0).astype(np.int64)

    auc, pr_auc, ll, brier = _classification_metrics(y_true, calibrated_score)
    pearson_ic = _pearson_ic(calibrated_score, ret_net)
    spearman_pooled = _spearman_ic(calibrated_score, ret_net)
    q_spread = _q10_minus_q1_bps(calibrated_score, ret_net)

    fold_ics: list[float] = []
    for s in segments_nao_vazios:
        ic = _spearman_ic(s.calibrated_score.astype(np.float64), s.ret_net.astype(np.float64))
        if not np.isnan(ic):
            fold_ics.append(ic)

    ic_mean, ic_median, ic_std, ic_ir, pct_positive, ic_tstat = _ic_dispersion_stats(fold_ics)

    return ScoreQualityResult(
        side=side,
        n_trades=int(calibrated_score.shape[0]),
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


def compute_train_val_test_gap(
    fold_results: list[FoldResult],
) -> tuple[TrainValTestGapResult, ...]:
    """Aplica as métricas de `compute_score_quality` aos 3 sub-splits
    in-sample já existentes (`alpha.py::_temporal_purged_three_way_split`,
    via `SideModelResult.fit_segment`/`stop_segment`/`calib_segment`),
    pooled entre TODOS os folds do combo — mesmo padrão de pooling entre
    folds que `compute_score_quality` já usa. Um resultado por lado com
    pelo menos 1 sub-split não-vazio; lado totalmente ausente (não
    deveria acontecer — todo fold treina os 2 lados) fica fora da
    tupla."""
    results: list[TrainValTestGapResult] = []
    for side_value, side_label in _SIDE_LABEL_BY_HAT.items():
        side_results = [
            fr.long_result if side_value == 1 else fr.short_result for fr in fold_results
        ]
        fit_segments = [r.fit_segment for r in side_results if r.fit_segment is not None]
        stop_segments = [r.stop_segment for r in side_results if r.stop_segment is not None]
        calib_segments = [r.calib_segment for r in side_results if r.calib_segment is not None]

        fit_result = _score_quality_from_segments(fit_segments, side=side_label)
        stop_result = _score_quality_from_segments(stop_segments, side=side_label)
        calib_result = _score_quality_from_segments(calib_segments, side=side_label)

        if fit_result is None and stop_result is None and calib_result is None:
            continue

        gap: dict[str, float] = {}
        if fit_result is not None and stop_result is not None:
            for field_name in _GAP_FIELDS:
                fit_v = getattr(fit_result, field_name)
                stop_v = getattr(stop_result, field_name)
                gap[field_name] = (
                    float("nan")
                    if (np.isnan(fit_v) or np.isnan(stop_v))
                    else float(fit_v - stop_v)
                )

        results.append(
            TrainValTestGapResult(
                side=side_label,
                fit=fit_result,
                stop=stop_result,
                calib=calib_result,
                gap_fit_minus_stop=gap,
            )
        )
        logger.info(
            "analysis.train_val_test_gap.computed",
            side=side_label,
            n_fit=fit_result.n_trades if fit_result else 0,
            n_stop=stop_result.n_trades if stop_result else 0,
            n_calib=calib_result.n_trades if calib_result else 0,
            gap_roc_auc=gap.get("roc_auc"),
        )

    return tuple(results)
