"""Núcleo de treino do Alpha (§5.2, §5.9, §5.10) — dois binários XGBoost
por fold do CPCV (Sprint 7, reusado como harness desta rodada — walk-
forward de 14 janelas é Sprint 11, §5.9), Camada 1 (restrições
monotônicas, §5.3) e a variante Camada 0 conceitual (mesmo pipeline, sem
`monotone_constraints`) para o critério de permanência do §5.11.

**Design decisivo, resolvido aqui e documentado (§5.12 exige `p_long` E
`p_short` na MESMA linha por `t0`):** `M_long` e `M_short` são treinados
sobre sub-populações DIFERENTES (`side_subset(..., side=+1)` descarta
NOFILL do lado long; `side=-1` descarta NOFILL do lado short — os dois
conjuntos de linhas descartadas não coincidem, porque o resultado de
preenchimento é simulado por lado). Mas a INFERÊNCIA roda sobre a barra
(features não dependem de lado), não sobre a linha de label — cada modelo
prediz em TODAS as barras do teste do fold que têm feature T1 válida
(sem filtrar por NOFILL daquele lado: um sinal de M_long numa barra cujo
lado long deu NOFILL ainda é uma predição legítima de "o mercado parecia
favorável a comprar" — NOFILL é ruído de EXECUÇÃO, não housing de FEATURE,
§3.7). O acasalamento com o resultado realizado (para Sharpe/backtest, não
para `predictions.parquet`) é feito à parte, em `src.models.backtest_lite`.

`tau` (limiar de decisão) é fixado IN-FOLD, a priori, pela taxa de sinal
orçada (`target_signal_rate`, já existente em `constants.yaml`, §0.2 R3) —
nunca escolhido por métrica OOS (B20): é o quantil `1 - target_signal_rate`
da distribuição de probabilidade calibrada do PRÓPRIO conjunto de treino
daquele lado."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
import xgboost as xgb
from numpy.typing import NDArray
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import train_test_split

from src.features.build import T1_FEATURE_IDS
from src.validation.cpcv import CPCVSplit

from . import dataset as ds
from . import monotonic
from ._constants import load_constant
from .hhi import (
    ConcentrationDiagnostics,
    EffectiveConcentrationDiagnostics,
    compute_concentration,
    compute_effective_concentration,
)

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

# R1 é a referência (drop-first) do one-hot de regime — categoria mais
# frequente (~46% das barras, Sprint 5), convenção padrão de codificação
# categórica. §2.13: "one-hot de 5 níveis... consome mais 4 graus de
# liberdade" — R1 fora, R2/R3/R4/R5 como as 4 colunas indicadoras.
REGIME_ONEHOT_LEVELS: tuple[str, ...] = ("R2", "R3", "R4", "R5")
REGIME_DUMMY_COLUMNS: tuple[str, ...] = tuple(f"regime_{r}" for r in REGIME_ONEHOT_LEVELS)
DESIGN_COLUMNS: tuple[str, ...] = (*T1_FEATURE_IDS, *REGIME_DUMMY_COLUMNS)

VARIANT_CAMADA1 = "camada1"
VARIANT_CAMADA0 = "camada0"


@dataclass(frozen=True, slots=True)
class XGBHyperparams:
    """§5.10, todos ASSUMED/citados textualmente — ver `constants.yaml`."""

    max_depth: int
    n_estimators: int
    learning_rate: float
    subsample: float
    colsample_bytree: float
    min_child_weight: int
    reg_lambda: float

    @classmethod
    def from_constants(cls) -> XGBHyperparams:
        return cls(
            max_depth=int(load_constant("alpha_xgb_max_depth")),
            n_estimators=int(load_constant("alpha_xgb_n_estimators")),
            learning_rate=float(load_constant("alpha_xgb_learning_rate")),
            subsample=float(load_constant("alpha_xgb_subsample")),
            colsample_bytree=float(load_constant("alpha_xgb_colsample_bytree")),
            min_child_weight=int(load_constant("alpha_xgb_min_child_weight")),
            reg_lambda=float(load_constant("alpha_xgb_reg_lambda")),
        )


def build_design_matrix(df: pl.DataFrame) -> FloatArray:
    """`DESIGN_COLUMNS` = 10 features T1 + 4 dummies de regime (§2.13, 14
    colunas). Numpy puro (sem pandas, B26) — `monotone_constraints` do
    XGBoost aceita uma tupla posicional na mesma ordem quando o `fit` recebe
    um array, não um DataFrame com nomes."""
    t1_arr = df.select(T1_FEATURE_IDS).to_numpy().astype(np.float64)
    regime_col = df["regime"]
    dummies = np.column_stack(
        [(regime_col == level).to_numpy().astype(np.float64) for level in REGIME_ONEHOT_LEVELS]
    )
    return np.hstack([t1_arr, dummies])


def _t1_correlation_matrix(df: pl.DataFrame) -> FloatArray:
    """Matriz de correlação de Pearson das 10 features T1 (`T1_FEATURE_IDS`,
    NUNCA `DESIGN_COLUMNS` — exclui as 4 dummies de regime por padrão, ver
    `src.models.hhi.compute_effective_concentration`) — insumo de D1 (task
    HHI efetivo, CLAUDE.md). `df` PRECISA já ser o subconjunto de TREINO do
    fold (`train_side_df` em `fit_side_model`, já filtrado por
    `src.models.dataset.side_subset` — NOFILL e warmup fora), nunca o
    dataset inteiro — mesma disciplina B02/B04/B06 de `src.models.monotonic`/
    `src.models.environments`.

    `np.corrcoef` produz `NaN` para uma feature com variância zero no fold
    (divisão por zero no denominador do coeficiente) — não tratado aqui
    (deixado passar); a sanitização (`NaN` -> `0.0` fora da diagonal, `1.0`
    na diagonal) é responsabilidade de `compute_effective_concentration`,
    não desta função (mantém esta função uma leitura direta do dado, sem
    decisão de negócio embutida)."""
    t1_arr = df.select(T1_FEATURE_IDS).to_numpy().astype(np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(t1_arr, rowvar=False)
    return np.asarray(corr, dtype=np.float64)


def _derived_seed(base_seed: int, *parts: int) -> int:
    """Seed determinística por (fold, lado, variante) — mesma semente base
    de `constants.yaml`, deslocada de forma reprodutível. Não é uma
    constante de domínio nova (é aritmética de composição de seed, mesma
    categoria de `_BPS_PER_UNIT` em `triple_barrier.py`)."""
    seed = base_seed
    for i, p in enumerate(parts):
        seed = (seed * 1_000_003 + (p + 1) * (i + 7)) % 2_147_483_647  # noqa: magic-number
    return seed


def _stratified_calib_split(
    y: IntArray, *, holdout_frac: float, seed: int
) -> tuple[IntArray, IntArray]:
    """Sub-split interno do treino (§5.9 passo 9, B08) — nunca toca o teste
    do fold. Estratificado por `y` quando possível; cai para split
    não-estratificado (com aviso logado) se alguma classe tiver menos de 2
    membros — evitar crash em folds degenerados é mais seguro que propagar
    a exceção do sklearn."""
    idx = np.arange(y.shape[0])
    try:
        fit_idx, calib_idx = train_test_split(
            idx, test_size=holdout_frac, random_state=seed, stratify=y
        )
    except ValueError:
        logger.warning("models.alpha.calib_split_fallback_nao_estratificado", n=int(y.shape[0]))
        fit_idx, calib_idx = train_test_split(idx, test_size=holdout_frac, random_state=seed)
    return fit_idx.astype(np.int64), calib_idx.astype(np.int64)


@dataclass(frozen=True, slots=True)
class SideModelResult:
    side: int
    variant: str
    model: xgb.XGBClassifier
    calibrator: IsotonicRegression
    monotone: dict[str, monotonic.FeatureICResult]
    monotone_constraints: tuple[int, ...]
    tau: float
    concentration: ConcentrationDiagnostics
    # HHI EFETIVO (D1/D2 da task HHI efetivo, CLAUDE.md) — irmão de
    # `concentration`, NUNCA a substitui. Mede concentração no espaço de
    # FATORES DE INFORMAÇÃO (após remover redundância de features
    # correlacionadas — ver `src.models.hhi.compute_effective_concentration`),
    # calculado sobre a matriz de correlação das 10 features T1 do MESMO
    # `train_side_df` deste fold/lado (in-fold, nunca vazando).
    concentration_effective: EffectiveConcentrationDiagnostics
    # `total_gain` bruto por coluna (`booster.get_score(importance_type=
    # "total_gain")` remapeado para nome real de coluna), ANTES da
    # normalização que `compute_concentration` aplica em `concentration.
    # shares`. Persistido à parte porque a investigação de auditoria que deu
    # origem a este campo (ver `models/{model_id}/diagnostics/`, escrito por
    # `src.models.pipeline`) precisa do gain bruto, não só do share — colunas
    # sem nenhuma divisão pelo booster ficam ausentes deste dict (mesma
    # convenção de `gain_by_column` em `fit_side_model`), não aparecem como
    # `0.0` como acontece em `concentration.shares`.
    gain_by_column_raw: dict[str, float]
    n_train_fit: int
    n_train_calib: int


def fit_side_model(
    train_side_df: pl.DataFrame,
    *,
    side: int,
    variant: str,
    hyper: XGBHyperparams,
    seed: int,
    target_signal_rate: float,
) -> SideModelResult:
    """Treina UM binário (`M_long` se `side=1`, `M_short` se `side=-1`)
    sobre `train_side_df` — já filtrado por `src.models.dataset.
    side_subset` (NOFILL fora, warmup fora), já restrito ao TREINO do fold
    (nunca o teste). `y = 1` sse `barrier_hit == "TP"` (leitura literal de
    §5.2 "P(TP antes de SL)" — SL e TIME viram `y=0`, ver docstring do
    módulo `dataset.py` e o relatório do Sprint 8 para a justificativa
    completa desta escolha)."""
    ic_results = monotonic.screen_monotone_constraints(train_side_df, T1_FEATURE_IDS)
    if variant == VARIANT_CAMADA1:
        t1_constraints = tuple(ic_results[f].constraint for f in T1_FEATURE_IDS)
    elif variant == VARIANT_CAMADA0:
        t1_constraints = tuple(0 for _ in T1_FEATURE_IDS)
    else:
        raise ValueError(f"fit_side_model: variant desconhecida {variant!r}")
    monotone_constraints = t1_constraints + tuple(0 for _ in REGIME_DUMMY_COLUMNS)

    X_all = build_design_matrix(train_side_df)
    y_all = (train_side_df["label"].cast(pl.Int64) == 1).to_numpy().astype(np.int64)
    w_all = train_side_df["sample_weight"].to_numpy().astype(np.float64)

    holdout_frac = float(load_constant("alpha_calibration_holdout_frac"))
    fit_idx, calib_idx = _stratified_calib_split(
        y_all, holdout_frac=holdout_frac, seed=_derived_seed(seed, side, 1)
    )
    X_fit, y_fit, w_fit = X_all[fit_idx], y_all[fit_idx], w_all[fit_idx]
    X_calib, y_calib, w_calib = X_all[calib_idx], y_all[calib_idx], w_all[calib_idx]

    n_pos = int(y_fit.sum())
    n_neg = int(y_fit.shape[0] - n_pos)
    scale_pos_weight = float(n_neg) / float(n_pos) if n_pos > 0 else 1.0

    model = xgb.XGBClassifier(
        objective="binary:logistic",
        max_depth=hyper.max_depth,
        n_estimators=hyper.n_estimators,
        learning_rate=hyper.learning_rate,
        subsample=hyper.subsample,
        colsample_bytree=hyper.colsample_bytree,
        min_child_weight=hyper.min_child_weight,
        reg_lambda=hyper.reg_lambda,
        monotone_constraints=monotone_constraints,
        scale_pos_weight=scale_pos_weight,
        tree_method="hist",
        eval_metric="logloss",
        random_state=_derived_seed(seed, side, 2),
        n_jobs=-1,
    )
    model.fit(X_fit, y_fit, sample_weight=w_fit)

    raw_calib = model.predict_proba(X_calib)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(raw_calib, y_calib, sample_weight=w_calib)

    raw_train_all = model.predict_proba(X_all)[:, 1]
    calibrated_train_all = calibrator.predict(raw_train_all)
    tau = float(np.quantile(calibrated_train_all, 1.0 - target_signal_rate))

    booster = model.get_booster()
    # `importance_type="total_gain"` sempre devolve `dict[str, float]` — o
    # stub do xgboost declara `dict[str, float | list[float]]` porque
    # outros `importance_type` (ex. SHAP) podem devolver lista; `float()`
    # explícito satisfaz o mypy sem mascarar um erro real.
    gain_by_fidx = booster.get_score(importance_type="total_gain")
    gain_by_column = {
        DESIGN_COLUMNS[int(k[1:])]: float(v)  # type: ignore[arg-type]
        for k, v in gain_by_fidx.items()
        if k.startswith("f")
    }
    concentration = compute_concentration(gain_by_column, DESIGN_COLUMNS)

    # HHI efetivo (D1/D2, CLAUDE.md) — matriz de correlação das 10 features
    # T1 sobre o MESMO `train_side_df` deste fold/lado (in-fold, nunca o
    # dataset inteiro — mesma disciplina de `monotonic.screen_monotone_
    # constraints` logo acima, que também recebe só `train_side_df`).
    correlation_t1 = _t1_correlation_matrix(train_side_df)
    concentration_effective = compute_effective_concentration(
        correlation_t1, gain_by_column, T1_FEATURE_IDS
    )

    return SideModelResult(
        side=side,
        variant=variant,
        model=model,
        calibrator=calibrator,
        monotone=ic_results,
        monotone_constraints=monotone_constraints,
        tau=tau,
        concentration=concentration,
        concentration_effective=concentration_effective,
        gain_by_column_raw=gain_by_column,
        n_train_fit=int(fit_idx.shape[0]),
        n_train_calib=int(calib_idx.shape[0]),
    )


@dataclass(frozen=True, slots=True)
class FoldResult:
    fold_id: int
    path_id: int
    variant: str
    model_id: str
    predictions: pl.DataFrame  # schema oficial §5.12 (colunas OFICIAIS)
    long_result: SideModelResult
    short_result: SideModelResult
    n_train_long: int
    n_train_short: int
    n_test_bars: int


def _unique_test_bars(test_bars_all_sides: pl.DataFrame) -> pl.DataFrame:
    """Uma linha por `t0` (feature não depende de lado) — usa as linhas de
    `side=1` como referência de deduplicação (toda barra tem exatamente uma
    linha `side=1` E uma `side=-1` em `labels.parquet`, ver
    `src.labels.triple_barrier.build_labels_both_sides`), mantém só barras
    com T1 válido (fora do warmup) — NÃO filtra por NOFILL (ver docstring
    do módulo: inferência roda em toda barra, NOFILL só importa para
    treino/backtest)."""
    out = test_bars_all_sides.filter(
        (pl.col("side") == 1) & pl.col(T1_FEATURE_IDS[0]).is_not_null()
    )
    for fid in T1_FEATURE_IDS[1:]:
        out = out.filter(pl.col(fid).is_not_null())
    return out.sort("t0")


def run_fold(
    df_all: pl.DataFrame,
    split: CPCVSplit,
    *,
    variant: str,
    hyper: XGBHyperparams,
    model_id: str,
    seed: int,
    feature_version: str = "t1_v1",
) -> FoldResult:
    train_bars = df_all[split.train_idx]
    test_bars = df_all[split.test_idx]

    train_long = ds.side_subset(train_bars, side=1)
    train_short = ds.side_subset(train_bars, side=-1)
    target_signal_rate = float(load_constant("target_signal_rate"))

    long_result = fit_side_model(
        train_long,
        side=1,
        variant=variant,
        hyper=hyper,
        seed=_derived_seed(seed, split.split_id),
        target_signal_rate=target_signal_rate,
    )
    short_result = fit_side_model(
        train_short,
        side=-1,
        variant=variant,
        hyper=hyper,
        seed=_derived_seed(seed, split.split_id),
        target_signal_rate=target_signal_rate,
    )

    test_bars_unique = _unique_test_bars(test_bars)
    X_test = build_design_matrix(test_bars_unique)

    raw_long = long_result.model.predict_proba(X_test)[:, 1]
    p_long = long_result.calibrator.predict(raw_long)
    raw_short = short_result.model.predict_proba(X_test)[:, 1]
    p_short = short_result.calibrator.predict(raw_short)

    is_long = (p_long > long_result.tau) & (p_long > p_short)
    is_short = (p_short > short_result.tau) & (p_short > p_long) & ~is_long
    side_hat = np.zeros(p_long.shape[0], dtype=np.int8)
    side_hat[is_long] = 1
    side_hat[is_short] = -1
    confidence = np.maximum(p_long, p_short)

    calibrator_id_long = f"{model_id}_side1_fold{split.split_id}_calibrator"
    calibrator_id_short = f"{model_id}_side-1_fold{split.split_id}_calibrator"
    calibrator_id = np.where(side_hat == 1, calibrator_id_long, calibrator_id_short)
    calibrator_id = np.where(side_hat == 0, "n/a", calibrator_id)

    # média simples entre os dois binários do fold — diagnóstico único por
    # linha (§5.12 tem uma coluna `hhi_importancia`, não duas). `.value` —
    # `ConcentrationDiagnostics.hhi` virou `Metric` (`src.core.metric`,
    # refatoração concorrente de `src/models/hhi.py`, fora do escopo desta
    # task) durante esta mesma rodada; `Metric` não define `__truediv__`
    # (só soma/subtração de mesma unidade e multiplicação por escalar, ver
    # docstring do módulo), então a divisão por 2 precisa do float
    # extraído, não do `Metric` em si. A coluna `hhi_importancia` de
    # `predictions` continua `pl.Float64` (schema §5.12 inalterado).
    hhi_importancia_fold = (
        long_result.concentration.hhi.value + short_result.concentration.hhi.value
    ) / 2

    predictions = pl.DataFrame(
        {
            "t0": test_bars_unique["t0"],
            "p_long": p_long,
            "p_short": p_short,
            "score_long_raw": raw_long,
            "score_short_raw": raw_short,
            "side_hat": side_hat,
            "confidence": confidence,
            "ensemble_std": pl.Series([None] * len(p_long), dtype=pl.Float64),
            "n_models_agree": pl.Series([1] * len(p_long), dtype=pl.Int8),
            "model_id": pl.Series([model_id] * len(p_long), dtype=pl.Utf8),
            "calibrator_id": pl.Series(calibrator_id),
            "feature_version": pl.Series([feature_version] * len(p_long), dtype=pl.Utf8),
            "features_selecionadas": pl.Series([list(T1_FEATURE_IDS)] * len(p_long)),
            "hhi_importancia": pl.Series(
                [hhi_importancia_fold] * len(p_long),
                dtype=pl.Float64,
            ),
            "wf_window_id": pl.Series([None] * len(p_long), dtype=pl.Int16),
            "fold_id": pl.Series([split.split_id] * len(p_long), dtype=pl.Int16),
            "is_oof": pl.Series([True] * len(p_long), dtype=pl.Boolean),
        }
    )

    return FoldResult(
        fold_id=split.split_id,
        path_id=split.path_id,
        variant=variant,
        model_id=model_id,
        predictions=predictions,
        long_result=long_result,
        short_result=short_result,
        n_train_long=train_long.height,
        n_train_short=train_short.height,
        n_test_bars=test_bars_unique.height,
    )


def run_all_folds(
    df_all: pl.DataFrame,
    splits: tuple[CPCVSplit, ...],
    *,
    variant: str,
    model_id: str,
    hyper: XGBHyperparams | None = None,
    seed: int | None = None,
) -> list[FoldResult]:
    hyper = hyper if hyper is not None else XGBHyperparams.from_constants()
    seed = seed if seed is not None else int(load_constant("alpha_random_seed"))

    results: list[FoldResult] = []
    for split in splits:
        logger.info(
            "models.alpha.run_fold_start",
            split_id=split.split_id,
            path_id=split.path_id,
            variant=variant,
        )
        result = run_fold(df_all, split, variant=variant, hyper=hyper, model_id=model_id, seed=seed)
        logger.info(
            "models.alpha.run_fold_done",
            split_id=split.split_id,
            variant=variant,
            n_train_long=result.n_train_long,
            n_train_short=result.n_train_short,
            n_test_bars=result.n_test_bars,
            hhi_long=result.long_result.concentration.hhi.value,
            hhi_short=result.short_result.concentration.hhi.value,
        )
        results.append(result)
    return results


def assemble_predictions_table(fold_results: list[FoldResult]) -> pl.DataFrame:
    """§5.12 — concatena as predições OOF de todos os folds passados (a
    task pede explicitamente 'agregue as predições OOF de todos os 15
    splits', §5.9 passo 7). Cada barra aparece em até 5 folds distintos
    (uma vez por caminho de backtest do CPCV, §11.4) — isso é esperado e
    documentado, não duplicata a remover: cada aparição vem de um modelo
    fold-treinado DIFERENTE, distinguido por `fold_id`."""
    tables = [fr.predictions for fr in fold_results]
    return pl.concat(tables, how="vertical").sort(["t0", "fold_id"])


PREDICTIONS_SCHEMA_COLUMNS: tuple[str, ...] = (
    "t0",
    "p_long",
    "p_short",
    "score_long_raw",
    "score_short_raw",
    "side_hat",
    "confidence",
    "ensemble_std",
    "n_models_agree",
    "model_id",
    "calibrator_id",
    "feature_version",
    "features_selecionadas",
    "hhi_importancia",
    "wf_window_id",
    "fold_id",
    "is_oof",
)
