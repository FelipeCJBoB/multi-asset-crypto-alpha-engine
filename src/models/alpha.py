"""Núcleo de treino do Alpha (§5.2, §5.9, §5.10) — dois binários LightGBM
por fold do CPCV (Sprint 7, reusado como harness desta rodada — walk-
forward de 14 janelas é Sprint 11, §5.9), Camada 1 (restrições
monotônicas, §5.3) e a variante Camada 0 conceitual (mesmo pipeline, sem
`monotone_constraints`) para o critério de permanência do §5.11.

**Migração XGBoost -> LightGBM (D-01, `docs/alpha_model_design_doc_
2026-08-22.md`)**: learner trocado por decisão já travada com o Manager
(`PLANO_MESTRE_PRINCE2.md §15.14`), não reaberta aqui. `monotone_
constraints`/calibração isotônica/CPCV reusados sem mudança de arquitetura
(D-07/D-09/D-10); extração de importância reescrita para a API do
LightGBM (D-08, ver `fit_side_model`); hiperparâmetros novos declarados em
`constants.yaml::alpha_lgbm_*` (D-11).

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
daquele lado. `tau_long`/`tau_short` agora são persistidos em
`predictions.parquet` (D-05, fecha `AG-150`) — antes calculados e
descartados."""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import train_test_split

from src.features.build import T1_FEATURE_IDS
from src.io.schema import ArtifactSchema, ColumnSpec
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

# Regime SAIU do vetor de treino do Alpha (2026-08-21) -- ADR-001 §2.7
# decide "regime = gate de risco, não feature preditiva" (ratificado
# pelo Manager); o one-hot de 4 colunas que existia aqui (R2-R5, R1
# como referência drop-first) implementava a leitura ANTIGA (regime
# como feature), nunca corrigida no código até este wiring de HMM k=4
# como candidato canônico (PLANO_MESTRE_PRINCE2.md §15.13). O papel de
# gate agora é consumido por src.risk.limits::control_01_regime_
# tradeavel (bool pré-computado pelo builder de regime, candidato-
# agnóstico), não por este módulo. DESIGN_COLUMNS mantém o NOME (usado
# por src.analysis.faixa2_caminho_b e pelos testes) mas o conteúdo
# passa a ser só as 7 features T1. D-04 (design doc do Alpha,
# 2026-08-22): esta remoção NÃO é reaberta pela migração LightGBM --
# o Meta-model v3 depende estruturalmente dela (§2.2 do doc do Meta).
DESIGN_COLUMNS: tuple[str, ...] = T1_FEATURE_IDS

VARIANT_CAMADA1 = "camada1"
VARIANT_CAMADA0 = "camada0"

# Legado de path/schema (D-03/D-05, `predictions.parquet`) -- valor da
# coluna `resolution_id` quando o caller não passa uma grade dollar-bar
# explícita (mesmo sentinela `None` que `pipeline.run_layer1_sprint` já
# usa para `tf`/`resolution_id`, ver docstring de lá).
_LEGACY_RESOLUTION_LABEL = "time_15m"


@dataclass(frozen=True, slots=True)
class LGBMHyperparams:
    """§5.10, todos ASSUMED/citados textualmente — ver `constants.yaml`.

    D-11 (`docs/alpha_model_design_doc_2026-08-22.md`): `max_depth`/
    `n_estimators`/`learning_rate`/`subsample`/`feature_fraction`/
    `lambda_l2` são renomeações diretas dos hiperparâmetros XGBoost
    equivalentes (mesmo valor, `provenance: DERIVED` em `constants.yaml`
    -- ver `alpha_xgb_*`, removidas, órfãs pós-migração). `min_child_
    samples`/`num_leaves` são conceitos NOVOS sem conversão numérica 1:1
    do XGBoost (`min_child_weight` é soma de hessian; `min_child_samples`
    é contagem) -- `provenance: ASSUMED`, `sweep_required: true`.

    **`subsample_freq` (achado real, `audit_engineering`, 2026-08-23):**
    o design doc/D-11 tratava `subsample` como renomeação direta e
    completa do `subsample` do XGBoost -- FALSO. No LightGBM,
    `subsample` (alias `bagging_fraction`) só tem efeito quando
    `subsample_freq` (alias `bagging_freq`) é um inteiro positivo
    (default `0` = "no enable", confirmado na doc oficial do LightGBM)
    -- sem essa peça companheira, `subsample=0.8` era um no-op
    silencioso, toda árvore treinava sobre 100% dos dados. `subsample_
    freq=1` (bag a cada iteração, mesmo espírito do row-subsampling
    por árvore que o XGBoost já fazia) ativa o parâmetro de verdade."""

    max_depth: int
    n_estimators: int
    learning_rate: float
    subsample: float
    subsample_freq: int
    feature_fraction: float
    lambda_l2: float
    min_child_samples: int
    num_leaves: int

    @classmethod
    def from_constants(cls) -> LGBMHyperparams:
        return cls(
            max_depth=int(load_constant("alpha_lgbm_max_depth")),
            n_estimators=int(load_constant("alpha_lgbm_n_estimators")),
            learning_rate=float(load_constant("alpha_lgbm_learning_rate")),
            subsample=float(load_constant("alpha_lgbm_subsample")),
            subsample_freq=int(load_constant("alpha_lgbm_subsample_freq")),
            feature_fraction=float(load_constant("alpha_lgbm_feature_fraction")),
            lambda_l2=float(load_constant("alpha_lgbm_lambda_l2")),
            min_child_samples=int(load_constant("alpha_lgbm_min_child_samples")),
            num_leaves=int(load_constant("alpha_lgbm_num_leaves")),
        )


def build_design_matrix(df: pl.DataFrame) -> FloatArray:
    """`DESIGN_COLUMNS` = 7 features T1, sem regime (regime saiu do
    vetor de treino, ADR-001 §2.7 -- ver nota em `DESIGN_COLUMNS`).
    Numpy puro (sem pandas, B26) — `monotone_constraints` do LightGBM
    aceita uma lista posicional na mesma ordem quando o `fit` recebe um
    array, não um DataFrame com nomes (D-07, mesma convenção do XGBoost
    anterior)."""
    return df.select(T1_FEATURE_IDS).to_numpy().astype(np.float64)


def _t1_correlation_matrix(df: pl.DataFrame) -> FloatArray:
    """Matriz de correlação de Pearson das 7 features T1 (`T1_FEATURE_IDS`,
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
    model: lgb.LGBMClassifier
    calibrator: IsotonicRegression
    monotone: dict[str, monotonic.FeatureICResult]
    monotone_constraints: tuple[int, ...]
    tau: float
    concentration: ConcentrationDiagnostics
    # HHI EFETIVO (D1/D2 da task HHI efetivo, CLAUDE.md) — irmão de
    # `concentration`, NUNCA a substitui. Mede concentração no espaço de
    # FATORES DE INFORMAÇÃO (após remover redundância de features
    # correlacionadas — ver `src.models.hhi.compute_effective_concentration`),
    # calculado sobre a matriz de correlação das 7 features T1 do MESMO
    # `train_side_df` deste fold/lado (in-fold, nunca vazando).
    concentration_effective: EffectiveConcentrationDiagnostics
    # gain BRUTO por coluna (`booster_.feature_importance(importance_type=
    # "gain")` remapeado por nome real via `booster_.feature_name()`, D-08),
    # ANTES da normalização que `compute_concentration` aplica em
    # `concentration.shares`. Persistido à parte porque a investigação de
    # auditoria que deu origem a este campo (ver `models/{model_id}/
    # diagnostics/`, escrito por `src.models.pipeline`) precisa do gain
    # bruto, não só do share — colunas sem nenhuma divisão pelo booster
    # (gain 0.0) ficam ausentes deste dict (mesma convenção do XGBoost
    # anterior, `booster.get_score` também só devolvia colunas usadas),
    # não aparecem como `0.0` como acontece em `concentration.shares`.
    gain_by_column_raw: dict[str, float]
    n_train_fit: int
    n_train_calib: int


def fit_side_model(
    train_side_df: pl.DataFrame,
    *,
    side: int,
    variant: str,
    hyper: LGBMHyperparams,
    seed: int,
    target_signal_rate: float,
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
    device_type: str = "cpu",
) -> SideModelResult:
    """Treina UM binário (`M_long` se `side=1`, `M_short` se `side=-1`)
    sobre `train_side_df` — já filtrado por `src.models.dataset.
    side_subset` (NOFILL fora, warmup fora), já restrito ao TREINO do fold
    (nunca o teste). `y = 1` sse `barrier_hit == "TP"` (leitura literal de
    §5.2 "P(TP antes de SL)" — SL e TIME viram `y=0`, ver docstring do
    módulo `dataset.py` e o relatório do Sprint 8 para a justificativa
    completa desta escolha).

    `unforce_features_by_side` — repassado a `monotonic.
    screen_monotone_constraints` sem alteração; default `None` (produção,
    ver `src.models.monotonic._forced_constraint_for`). Existe só para
    `src.analysis.faixa1_6_reconciliation` (Bloco 4) treinar uma variante
    experimental sem restrição forçada de uma feature num lado.

    `device_type` (D-18, `docs/alpha_model_design_doc_2026-08-22.md`) --
    default `"cpu"` preserva bit-exato o comportamento de toda chamada
    existente (testes com dado sintético pequeno não precisam de GPU, e
    não devem quebrar numa máquina/CI sem uma disponível). `src.models.
    pipeline.run_layer1_sprint` (o ÚNICO caller de produção real) passa
    `"cuda"` explicitamente -- GPU é obrigatória em produção (pedido do
    Manager), mas opt-in por parâmetro, não hardcoded aqui, pelo mesmo
    motivo que `tf`/`resolution_id`/`dest_dir` em outros pontos do
    pipeline usam sentinela de default: uma mudança de comportamento real
    (aqui, requisito de hardware) nunca deve ser silenciosa pra quem já
    chama a função hoje."""
    ic_results = monotonic.screen_monotone_constraints(
        train_side_df,
        T1_FEATURE_IDS,
        side=side,
        unforce_features_by_side=unforce_features_by_side,
    )
    if variant == VARIANT_CAMADA1:
        t1_constraints = tuple(ic_results[f].constraint for f in T1_FEATURE_IDS)
    elif variant == VARIANT_CAMADA0:
        t1_constraints = tuple(0 for _ in T1_FEATURE_IDS)
    else:
        raise ValueError(f"fit_side_model: variant desconhecida {variant!r}")
    monotone_constraints = t1_constraints

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

    if device_type != "cpu":
        # Achado real (`audit_engineering`, 2026-08-23): a doc oficial do
        # LightGBM restringe `deterministic=True` a "works only with CPU
        # device type" -- não é uma incógnita empírica (B23/TBD), é um
        # FATO já documentado pela biblioteca, verificável sem treinar
        # nada (construção de histograma sob CUDA usa atomicAdd, soma de
        # ponto flutuante não-associativa sob paralelismo). O LightGBM
        # emite um warning nativo nesse cenário, mas `verbosity=-1`
        # (abaixo) suprime esse warning junto com todo o resto -- este
        # log explícito via structlog substitui esse sinal perdido, não
        # deixa a lacuna silenciosa.
        logger.warning(
            "models.alpha.deterministic_sem_garantia_sob_gpu",
            device_type=device_type,
            detail=(
                "deterministic=True só garante bit-exatidão sob CPU "
                "(doc oficial LightGBM) -- reload bit-a-bit não é "
                "garantido neste device_type; ver D-18 §3 do design doc "
                "para o plano de tolerância numérica se isso quebrar"
            ),
        )
    model = lgb.LGBMClassifier(
        objective="binary",
        max_depth=hyper.max_depth,
        num_leaves=hyper.num_leaves,
        n_estimators=hyper.n_estimators,
        learning_rate=hyper.learning_rate,
        subsample=hyper.subsample,
        # Achado real (`audit_engineering`, 2026-08-23): `subsample`
        # (alias `bagging_fraction`) só tem efeito quando `subsample_freq`
        # (alias `bagging_freq`) é inteiro positivo -- default `0` da
        # própria lib = "no enable" (confirmado na doc oficial). Sem
        # isso, `subsample=0.8` era um no-op silencioso (ver docstring de
        # `LGBMHyperparams`). `subsample_freq=1` bag a cada iteração.
        subsample_freq=hyper.subsample_freq,
        feature_fraction=hyper.feature_fraction,
        min_child_samples=hyper.min_child_samples,
        lambda_l2=hyper.lambda_l2,
        monotone_constraints=list(monotone_constraints),
        scale_pos_weight=scale_pos_weight,
        random_state=_derived_seed(seed, side, 2),
        n_jobs=-1,
        # D-18: GPU obrigatória em produção (device_type="cuda", passado
        # por run_layer1_sprint) -- CUDA preferido sobre o backend "gpu"
        # (OpenCL, mais antigo) por desempenho. Testes usam o default
        # "cpu" (ver docstring do parâmetro acima). A garantia de reload
        # bit-exato SÓ vale sob "cpu" -- ver warning explícito acima.
        device_type=device_type,
        # D-12 (docs/alpha_model_design_doc_2026-08-22.md): default do
        # LightGBM é `deterministic=False` -- soma de gradiente em
        # histograma multi-thread não é bit-exata por padrão (soma de
        # ponto flutuante não é associativa sob paralelismo). Exigido
        # explicitamente para o teste de reload bit-a-bit (`golden`,
        # `test_write_read_round_trip_reproduz_inferencia_bit_exata`) ter
        # garantia teórica de passar sob CPU -- não opcional, mesma
        # disciplina de B29/determinismo global do projeto.
        deterministic=True,
        # Achado real (`audit_engineering`, 2026-08-23): a doc oficial do
        # LightGBM recomenda explicitamente setar `force_row_wise` OU
        # `force_col_wise` junto de `deterministic=True` -- sem um dos
        # dois, a lib testa os dois modos de construção de histograma e
        # escolhe o mais rápido a cada treino, reintroduzindo a mesma
        # instabilidade numérica que `deterministic=True` existe pra
        # eliminar. `force_row_wise=True`: dataset é "alto e magro" (7
        # features T1, centenas de milhares de barras) -- exatamente o
        # perfil que a doc do LightGBM recomenda row-wise.
        force_row_wise=True,
        # Suprime log nativo do LightGBM em stdout/stderr (B28 -- só
        # structlog, nunca print()/output de biblioteca não estruturado).
        verbosity=-1,
    )
    # `feature_name=` explícito -- achado de implementação (não estava no
    # design doc): sem isso, `LGBMClassifier.fit` sobre um `NDArray` puro
    # (sem nomes de coluna) grava `booster_.feature_name()` como
    # "Column_0", "Column_1", ... em vez do nome real da feature --
    # `fit_side_model` abaixo (D-08) precisaria desses nomes reais para
    # remapear `gain_by_column`/`concentration`/`monotone_constraints`
    # corretamente. Ordem idêntica a `DESIGN_COLUMNS`/`T1_FEATURE_IDS`
    # (mesma que `build_design_matrix` usa para montar `X_fit`).
    model.fit(X_fit, y_fit, sample_weight=w_fit, feature_name=list(DESIGN_COLUMNS))

    # `np.asarray(...)` explícito -- os stubs do LightGBM tipam
    # `predict_proba` como `list` (imprecisão conhecida da biblioteca, não
    # do nosso código), o que quebra `mypy --strict` no fancy-indexing
    # `[:, 1]` (só `ndarray` suporta). Runtime já devolvia `ndarray`
    # sempre; a conversão é só correção de tipo estático, sem mudança de
    # valor.
    raw_calib = np.asarray(model.predict_proba(X_calib))[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(raw_calib, y_calib, sample_weight=w_calib)

    raw_train_all = np.asarray(model.predict_proba(X_all))[:, 1]
    calibrated_train_all = calibrator.predict(raw_train_all)
    tau = float(np.quantile(calibrated_train_all, 1.0 - target_signal_rate))

    # D-08 (docs/alpha_model_design_doc_2026-08-22.md §4): API do LightGBM
    # substitui `booster.get_score(importance_type="total_gain")` (parsing
    # de "f0"/"f1"/... específico do XGBoost). `feature_importance()`/
    # `feature_name()` devolvem arrays PARALELOS de tamanho fixo (uma
    # entrada por feature, mesmo as não usadas, gain=0.0) -- diferente do
    # XGBoost, que só incluía features com split real no dict. Filtro
    # `> 0.0` explícito preserva a convenção "só colunas realmente usadas"
    # que `gain_by_column_raw`/`compute_concentration` já assumiam.
    booster_ = model.booster_
    names = booster_.feature_name()
    gains = booster_.feature_importance(importance_type="gain")
    gain_by_column = {
        name: float(gain) for name, gain in zip(names, gains, strict=True) if gain > 0.0
    }
    concentration = compute_concentration(gain_by_column, DESIGN_COLUMNS)

    # HHI efetivo (D1/D2, CLAUDE.md) — matriz de correlação das 7 features
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
    predictions: pl.DataFrame  # schema oficial §5.12/D-03/D-05 (colunas OFICIAIS)
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
    treino/backtest).

    **`t0` genuinamente único, não só assumido (achado real, 2026-08-23,
    1ª execução real de `run_layer1_sprint` contra R1).** O filtro
    `side == 1` sozinho SUPUNHA 1 linha por `t0` (a garantia real de
    `labels.parquet`, confirmada), mas `test_bars_all_sides` já passou
    pelo JOIN de features/regime em `build_modeling_frame` -- e esse join
    duplicou 2 de 223.172 barras de BTCUSDT/R1 (`t0` idêntico, todas as
    colunas idênticas, causa raiz upstream não fechada aqui, ver
    `AG-202`). `verify_config_hash`/`write_predictions_versioned` só
    detectaram isso na PRIMEIRA vez que `predictions.parquet` foi
    validado contra schema real (`primary_key=(t0, fold_id)` duplicado) --
    o writer antigo nunca validava nada. `.unique(subset=["t0"], keep=
    "first")` fecha o sintoma aqui (join de feature é determinístico,
    "first" é estável) COM aviso alto -- nunca silencioso -- pra não
    mascarar `AG-202` se a taxa de duplicação crescer."""
    out = test_bars_all_sides.filter(
        (pl.col("side") == 1) & pl.col(T1_FEATURE_IDS[0]).is_not_null()
    )
    for fid in T1_FEATURE_IDS[1:]:
        out = out.filter(pl.col(fid).is_not_null())
    out = out.sort("t0")
    n_before = out.height
    out = out.unique(subset=["t0"], keep="first", maintain_order=True)
    n_duplicates = n_before - out.height
    if n_duplicates > 0:
        logger.warning(
            "models.alpha.unique_test_bars_t0_duplicado",
            n_duplicates=n_duplicates,
            n_before=n_before,
            detail="AG-202 -- join de feature/regime upstream produziu t0 "
            "duplicado, causa raiz nao fechada",
        )
    return out


def run_fold(
    df_all: pl.DataFrame,
    split: CPCVSplit,
    *,
    variant: str,
    hyper: LGBMHyperparams,
    model_id: str,
    seed: int,
    symbol: str,
    resolution_id: str | None = None,
    feature_version: str = "t1_v1",
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
    device_type: str = "cpu",
) -> FoldResult:
    """`symbol`/`resolution_id` (D-03, `docs/alpha_model_design_doc_
    2026-08-22.md`) — colunas explícitas no schema de saída, mesma classe
    de risco já corrigida uma vez em `dataset.py:138-160` (features de um
    ativo casadas com label de outro), agora endereçada por construção em
    vez de convenção de nome/caminho. `symbol` é obrigatório (sem default
    -- sempre conhecido no call site real, `pipeline.run_layer1_sprint`).
    `resolution_id=None` (default) grava `"time_15m"` na coluna (grade de
    relógio legada), mesmo sentinela que `pipeline.py` já usa para `tf`/
    `resolution_id`."""
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
        unforce_features_by_side=unforce_features_by_side,
        device_type=device_type,
    )
    short_result = fit_side_model(
        train_short,
        side=-1,
        variant=variant,
        hyper=hyper,
        seed=_derived_seed(seed, split.split_id),
        target_signal_rate=target_signal_rate,
        unforce_features_by_side=unforce_features_by_side,
        device_type=device_type,
    )

    test_bars_unique = _unique_test_bars(test_bars)
    X_test = build_design_matrix(test_bars_unique)

    raw_long = np.asarray(long_result.model.predict_proba(X_test))[:, 1]
    p_long = long_result.calibrator.predict(raw_long)
    raw_short = np.asarray(short_result.model.predict_proba(X_test))[:, 1]
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

    resolution_id_value = resolution_id if resolution_id is not None else _LEGACY_RESOLUTION_LABEL
    n_rows = len(p_long)

    predictions = pl.DataFrame(
        {
            "t0": test_bars_unique["t0"],
            "symbol": pl.Series([symbol] * n_rows, dtype=pl.Utf8),
            "resolution_id": pl.Series([resolution_id_value] * n_rows, dtype=pl.Utf8),
            "p_long": p_long,
            "p_short": p_short,
            "tau_long": pl.Series([long_result.tau] * n_rows, dtype=pl.Float64),
            "tau_short": pl.Series([short_result.tau] * n_rows, dtype=pl.Float64),
            "score_long_raw": raw_long,
            "score_short_raw": raw_short,
            "side_hat": side_hat,
            "confidence": confidence,
            "ensemble_std": pl.Series([None] * n_rows, dtype=pl.Float64),
            "n_models_agree": pl.Series([1] * n_rows, dtype=pl.Int8),
            "model_id": pl.Series([model_id] * n_rows, dtype=pl.Utf8),
            "calibrator_id": pl.Series(calibrator_id),
            "feature_version": pl.Series([feature_version] * n_rows, dtype=pl.Utf8),
            "features_selecionadas": pl.Series([list(T1_FEATURE_IDS)] * n_rows),
            "hhi_importancia": pl.Series(
                [hhi_importancia_fold] * n_rows,
                dtype=pl.Float64,
            ),
            "wf_window_id": pl.Series([None] * n_rows, dtype=pl.Int16),
            "fold_id": pl.Series([split.split_id] * n_rows, dtype=pl.Int16),
            "is_oof": pl.Series([True] * n_rows, dtype=pl.Boolean),
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
    symbol: str,
    resolution_id: str | None = None,
    hyper: LGBMHyperparams | None = None,
    seed: int | None = None,
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
    device_type: str = "cpu",
) -> list[FoldResult]:
    hyper = hyper if hyper is not None else LGBMHyperparams.from_constants()
    seed = seed if seed is not None else int(load_constant("alpha_random_seed"))

    results: list[FoldResult] = []
    for split in splits:
        logger.info(
            "models.alpha.run_fold_start",
            split_id=split.split_id,
            path_id=split.path_id,
            variant=variant,
            symbol=symbol,
            resolution_id=resolution_id,
        )
        result = run_fold(
            df_all,
            split,
            variant=variant,
            hyper=hyper,
            model_id=model_id,
            seed=seed,
            symbol=symbol,
            resolution_id=resolution_id,
            unforce_features_by_side=unforce_features_by_side,
            device_type=device_type,
        )
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
    "symbol",  # D-03 -- novo
    "resolution_id",  # D-03 -- novo
    "p_long",
    "p_short",
    "tau_long",  # D-05 -- novo, fecha AG-150 (ver AG-162: tau_alpha vira
    "tau_short",  # derivada no Meta, não física aqui -- reconciliação)
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

# D-06 (docs/alpha_model_design_doc_2026-08-22.md, fecha AG-154) --
# contrato de schema versionado (ADR-001, `src.io.schema`) pra
# `predictions.parquet`, usado por `src.models.pipeline.
# write_predictions_versioned`. `primary_key=(t0, fold_id)`: uma barra
# aparece em até 5 folds (`assemble_predictions_table`), então `t0`
# sozinho não é único -- (t0, fold_id) é. `symbol`/`resolution_id` já são
# o segmento de partição de `io.artifact.artifact_dir` (redundante com o
# path por desenho, D-03 quer os dois como coluna explícita TAMBÉM, não
# só implícito no path -- mesma razão que motivou D-03: convenção de
# path sozinha já causou 1 bug real de symbol-mismatch, `dataset.py:
# 138-160`). Achado real durante esta implementação: `io.schema` nunca
# tinha um consumidor real antes de D-06 -- precisou ganhar suporte a
# `List[Utf8]` (`features_selecionadas`) e `Datetime[ms,UTC]` (`t0`,
# NUNCA Int64 nanoseconds como a convenção `*_ts_ns` do docstring de
# `io/artifact.py` sugeria) que `v1` não cobria (nenhum artefato real
# tinha exercitado isso ainda).
PREDICTIONS_ARTIFACT_SCHEMA = ArtifactSchema(
    schema_version="1.0.0",
    primary_key=("t0", "fold_id"),
    columns=(
        ColumnSpec(name="t0", dtype="Datetime[ms,UTC]", nullable=False, role="key"),
        ColumnSpec(name="symbol", dtype="Utf8", nullable=False, role="partition"),
        ColumnSpec(name="resolution_id", dtype="Utf8", nullable=False, role="partition"),
        ColumnSpec(name="p_long", dtype="Float64", nullable=False),
        ColumnSpec(name="p_short", dtype="Float64", nullable=False),
        ColumnSpec(name="tau_long", dtype="Float64", nullable=False),
        ColumnSpec(name="tau_short", dtype="Float64", nullable=False),
        ColumnSpec(name="score_long_raw", dtype="Float64", nullable=False),
        ColumnSpec(name="score_short_raw", dtype="Float64", nullable=False),
        ColumnSpec(name="side_hat", dtype="Int8", nullable=False),
        ColumnSpec(name="confidence", dtype="Float64", nullable=False),
        # `ensemble_std`/`wf_window_id` sempre `None` hoje (sem ensemble
        # multi-seed nem walk-forward implementados nesta rodada, ver
        # `run_fold`) -- nullable=True reflete o dado real, não estipula
        # um valor que ainda não existe.
        ColumnSpec(name="ensemble_std", dtype="Float64", nullable=True),
        ColumnSpec(name="n_models_agree", dtype="Int8", nullable=False),
        # `model_id` é constante dentro de UM write (uma chamada cobre só
        # `camada1` OU `camada0`) -- mesmo papel de `symbol`/`resolution_id`
        # (broadcast por partição, não identidade por linha), não faz parte
        # de `primary_key`.
        ColumnSpec(name="model_id", dtype="Utf8", nullable=False, role="partition"),
        ColumnSpec(name="calibrator_id", dtype="Utf8", nullable=False),
        ColumnSpec(name="feature_version", dtype="Utf8", nullable=False),
        ColumnSpec(name="features_selecionadas", dtype="List[Utf8]", nullable=False),
        ColumnSpec(name="hhi_importancia", dtype="Float64", nullable=False),
        ColumnSpec(name="wf_window_id", dtype="Int16", nullable=True),
        ColumnSpec(name="fold_id", dtype="Int16", nullable=False, role="key"),
        ColumnSpec(name="is_oof", dtype="Boolean", nullable=False),
    ),
)
