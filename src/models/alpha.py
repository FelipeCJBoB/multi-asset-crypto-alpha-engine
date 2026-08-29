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

import math
from dataclasses import asdict, dataclass
from typing import Any

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
BoolArray = NDArray[np.bool_]
# `side_hat` é Int8 pelo schema oficial de `predictions.parquet` (§5.12,
# `PREDICTIONS_ARTIFACT_SCHEMA`) — alias próprio para `decide_side` não
# ter que mentir o tipo de retorno como int64.
SideArray = NDArray[np.int8]

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

# AG-371 (2026-08-28, decisão do Manager, MEDIDO antes de promover --
# AG-371-ADDENDUM-6/7/8) -- Camada0 SEM restrição nenhuma (`monotone_
# constraints=0` em toda feature) deixa `E27f_cost_atr_ratio` dominar
# 57-97% do gain do ensemble inteiro (5 células zeradas, 15 folds
# amostrados, `AG-371-ADDENDUM-6`) -- 3 eixos de hiperparâmetro puro
# (`num_leaves`/`min_child_samples`, `feature_fraction`, `lambda_l2`)
# testados e REFUTADOS como correção (`AG-371-ADDENDUM-3/7`); a raiz é
# estrutural (busca gulosa de split sem freio de forma sobre uma feature
# contínua de alta correlação marginal), não hiperparâmetro. Restringir
# SÓ esta feature (mesma direção que a triagem de IC já aplica em
# Camada1, `screen_monotone_constraints` abaixo -- não um valor
# hardcoded) resolve o defeito mecânico por completo, medido em
# BNBUSDT/R1 CPCV completo (`AG-371-ADDENDUM-8`): `n_signals` 0->2407,
# `camada0_sharpe_mean` NaN->-4,54 (número real), `hhi` 0,87->0,069,
# `E27f` sai do top-6 de gain. NÃO torna Camada0 lucrativo (nem deveria
# -- baseline fraco por desenho) -- torna o gate de permanência
# MENSURÁVEL (Camada1 vs número real, não Camada1 vs NaN/zero mecânico).
# Lista de 1 elemento hoje -- estrutura pronta pra crescer se outra
# feature mostrar o mesmo padrão de dominância no futuro, mas cada
# adição exige a MESMA disciplina de medição (nunca por suspeita).
CAMADA0_CONSTRAINED_FEATURES: frozenset[str] = frozenset({"E27f_cost_atr_ratio"})

# Legado de path/schema (D-03/D-05, `predictions.parquet`) -- valor da
# coluna `resolution_id` quando o caller não passa uma grade dollar-bar
# explícita (mesmo sentinela `None` que `pipeline.run_layer1_sprint` já
# usa para `tf`/`resolution_id`, ver docstring de lá).
_LEGACY_RESOLUTION_LABEL = "time_15m"

# ADR-005 §13.14.1 (item 8 de §13.17) -- base do piso de folha
# (`min_child_samples`/`min_sum_hessian_in_leaf`). `fixed` = comportamento
# legado (os dois vêm direto de `LGBMHyperparams`, bit-exato); `ess_derived`
# = derivados de `Σ uniqueness`/`w̄`/`scale_pos_weight` pela fórmula emendada
# de `§13.5-3` (ver `derive_ess_regularization`). Parâmetro hoje INERTE sob
# `num_leaves ∈ {2,3}` (§13.9.3) -- promover a produção só passa a importar
# se `max_depth` subir, decisão separada. Movida pra antes de `LGBMHyper
# params` (2026-08-27, handoff de `src/models/`, item 1) -- vira default de
# campo do dataclass, referência direta em vez de literal duplicado.
REGULARIZATION_FIXED = "fixed"
REGULARIZATION_ESS_DERIVED = "ess_derived"

# ADR-005 §13.14.3 (item 9 de §13.17) -- `fixed` = comportamento legado
# (2 partições fit/calib, sem early stopping, `n_estimators` fixo de
# `LGBMHyperparams`); `three_way` = 3 partições fit/stop/calib com purge
# por `t1` nas duas fronteiras (`_temporal_purged_three_way_split`),
# `eval_set=stop` e `lgb.early_stopping`. Só compatível com
# `calib_split_mode=CALIB_SPLIT_TEMPORAL_PURGED` -- um split aleatório não
# tem noção de fronteira temporal para purgar. Movida pelo mesmo motivo de
# `REGULARIZATION_FIXED` acima.
EARLY_STOPPING_FIXED = "fixed"
EARLY_STOPPING_THREE_WAY = "three_way"


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
    por árvore que o XGBoost já fazia) ativa o parâmetro de verdade.

    **`min_sum_hessian_in_leaf`/`max_bin` (achado `lgbm-crypto-quant`,
    2026-08-25, `AG-208`):** nenhum dos dois existia -- nem aqui, nem em
    `constants.yaml`, nem como argumento de `LGBMClassifier` --, então
    rodavam no default de biblioteca sem entrada de proveniência (§16.10).
    `min_sum_hessian_in_leaf` é o que mais importa dos dois, e era o que
    estava efetivamente desligado: sob `objective="binary"` a hessiana por
    amostra é `p(1-p)*w <= 0,25*w`, e `sample_weight` aqui é `uniqueness *
    |ret_net|` normalizado (`src.labels.weights.apply_weights`) -- cauda
    longa, massa concentrada nos desfechos de barreira. O default `1e-3`
    não restringe nada nesse regime, e `min_child_samples=20` limita
    CONTAGEM, não MASSA: uma folha pode ter 20 amostras cuja hessiana
    somada é fração de uma observação típica -- memorização de ruído
    exatamente no cenário de sinal fraco que o projeto declara ter
    (§17.2, IC ~0,04).

    Os dois entram com o valor de default da PRÓPRIA biblioteca (LightGBM
    4.7.0, `uv.lock`), portanto **bit-exato** com todo artefato já
    treinado: a correção é de PROVENIÊNCIA (o número passa a ser
    declarado, varrível e auditável), não de valor. Mudar o valor é
    decisão separada, pendente de sweep (`sweep_required: true` nas duas
    entradas de `constants.yaml`)."""

    max_depth: int
    n_estimators: int
    learning_rate: float
    subsample: float
    subsample_freq: int
    feature_fraction: float
    lambda_l2: float
    min_child_samples: int
    num_leaves: int
    # AG-208 -- defaults de biblioteca agora DECLARADOS. Campos com valor
    # default para não quebrar nenhuma construção parcial existente de
    # `LGBMHyperparams`; `from_constants` sempre os preenche do YAML.
    # `AG-272` (2026-08-26) -- MEDIDO que este guardrail e INERTE no regime
    # deste projeto, e o numero fica registrado para que uma escolha futura
    # seja informada em vez de estipulada (B23). A hessiana da binary
    # logloss por amostra e `p(1-p)*w <= 0,25*w`; `sample_weight` aqui e
    # normalizado com media ~1,015 (medido nos 5 simbolos em R1). Logo uma
    # folha no piso de `min_child_samples=20` carrega massa ~5,08 -- 5.080x
    # o valor abaixo. Quem restringe folha hoje e `min_child_samples`
    # sozinho; este parametro nao morde em nenhum ponto.
    # NAO alterado aqui de proposito: mexer nele mudaria o modelo, e e
    # classe B com `sweep_required` -- escolher um valor sem sweep seria
    # trocar um guardrail inerte por um numero inventado, que e pior.
    min_sum_hessian_in_leaf: float = 1e-3  # noqa: magic-number -- default LightGBM 4.7.0
    max_bin: int = 255  # noqa: magic-number -- default LightGBM 4.7.0
    # ADR-005 §13.14.1 (item 8 de §13.17) -- os dois termos declarados a
    # priori que a fórmula de regularização derivada de ESS pede.
    # Lidos SEMPRE (custo desprezível), mas só CONSOMEM efeito quando
    # `regularization_basis=REGULARIZATION_ESS_DERIVED` em `fit_side_
    # model` -- default `REGULARIZATION_FIXED` ignora os dois, bit-exato.
    ess_regularization_n_obs_independentes_alvo: float = 30.0  # noqa: magic-number -- default de biblioteca não existe aqui; valor real vem sempre de from_constants, este é só o default de dataclass
    ess_regularization_fator_conservador: float = 0.5  # noqa: magic-number -- idem
    # 2026-08-27 (handoff de `src/models/`, item 1) -- `regularization_
    # basis`/`early_stopping_mode`/`ic_magnitude_floor_k` eram parâmetros
    # de `fit_side_model` sem NENHUM caller acima (`run_fold`/`run_all_
    # folds`/`run_layer1_sprint`) capaz de setá-los -- presos no mesmo
    # teto apesar de implementados/testados (`AG-324`/`AG-325`/`AG-326`).
    # Entram aqui (não como parâmetro novo em cada uma das 3 camadas)
    # porque `hyper` já atravessa as 3 intacto via `hyper=hyper` -- mesmo
    # padrão dos dois campos ESS acima.
    # **[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27, decisão do Manager --
    # ver CLAUDE.md "Diretrizes de comportamento"]** Os 3 já tinham decisão
    # tomada e mecanismo testado (`AG-324`/`AG-325`/`AG-326`) -- ficavam só
    # esperando alguém "ligar". `REGULARIZATION_ESS_DERIVED` é hoje
    # documentado como INERTE sob `num_leaves ∈ {2,3}` (`AG-325` -- promover
    # não muda nenhum artefato real até `max_depth` subir, decisão
    # separada). `EARLY_STOPPING_THREE_WAY` é diferente em natureza: nunca
    # foi exercitado contra dado real (só RNG sintético em `tests/unit/
    # test_models_alpha_item6_8_9.py`) -- promover o default É a 1ª corrida
    # real, não uma decisão já validada por medição prévia.
    regularization_basis: str = REGULARIZATION_ESS_DERIVED
    early_stopping_mode: str = EARLY_STOPPING_THREE_WAY
    ic_magnitude_floor_k: float | None = None

    @classmethod
    def from_constants(cls, *, use_ic_magnitude_floor: bool = True) -> LGBMHyperparams:
        """`use_ic_magnitude_floor` (`AG-324`) -- **[PROMOVIDO A DEFAULT DE
        PRODUÇÃO 2026-08-27, decisão do Manager]** `True` (default) lê
        `alpha_monotonic_ic_magnitude_floor_k` (`constants.yaml`, valor
        `2,0`, medido: `|mean_ic| ~= 0,007` contra `SE ~= 0,005` -- ~1,4
        desvio-padrão, indistinguível de ruído sob esse piso) e passa a
        exigir magnitude, não só sinal+consistência, pra uma feature manter
        `monotone_constraints`. `False` preserva o comportamento anterior
        (`ic_magnitude_floor_k=None`, sinal+consistência puro) -- passe
        explicitamente se quiser reproduzir o legado. `regularization_
        basis`/`early_stopping_mode` não têm constante equivalente (são
        seletor de modo de código, não valor medido) -- ficam no default do
        campo do dataclass (`REGULARIZATION_ESS_DERIVED`/`EARLY_STOPPING_
        THREE_WAY`, também promovidos) sem precisar de parâmetro aqui."""
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
            min_sum_hessian_in_leaf=float(load_constant("alpha_lgbm_min_sum_hessian_in_leaf")),
            max_bin=int(load_constant("alpha_lgbm_max_bin")),
            ess_regularization_n_obs_independentes_alvo=float(
                load_constant("alpha_lgbm_ess_regularization_n_obs_independentes_alvo")
            ),
            ess_regularization_fator_conservador=float(
                load_constant("alpha_lgbm_ess_regularization_fator_conservador")
            ),
            ic_magnitude_floor_k=(
                float(load_constant("alpha_monotonic_ic_magnitude_floor_k"))
                if use_ic_magnitude_floor
                else None
            ),
        )


def build_design_matrix(
    df: pl.DataFrame, *, feature_ids: tuple[str, ...] = T1_FEATURE_IDS
) -> FloatArray:
    """`DESIGN_COLUMNS` = 7 features T1, sem regime (regime saiu do
    vetor de treino, ADR-001 §2.7 -- ver nota em `DESIGN_COLUMNS`).
    Numpy puro (sem pandas, B26) — `monotone_constraints` do LightGBM
    aceita uma lista posicional na mesma ordem quando o `fit` recebe um
    array, não um DataFrame com nomes (D-07, mesma convenção do XGBoost
    anterior).

    `feature_ids` (2026-08-24, `docs/t2_t1_promotion_ablation_design_doc_
    2026-08-24.md` §5.2) — default `T1_FEATURE_IDS` preserva bit-exato
    todo call site existente. Existe pra ablação T2→T1 poder montar a
    matriz sobre um vetor de k features candidatas em vez do T1 fixo, sem
    duplicar esta função."""
    return df.select(feature_ids).to_numpy().astype(np.float64)


def _t1_correlation_matrix(
    df: pl.DataFrame, *, feature_ids: tuple[str, ...] = T1_FEATURE_IDS
) -> FloatArray:
    """Matriz de correlação de Pearson das features de treino
    (`feature_ids`, default `T1_FEATURE_IDS` — NUNCA `DESIGN_COLUMNS`,
    exclui as 4 dummies de regime por padrão, ver
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
    decisão de negócio embutida).

    `feature_ids` (2026-08-24, `docs/t2_t1_promotion_ablation_design_doc_
    2026-08-24.md` §5.2) — default preserva bit-exato o nome/uso atual
    ("matriz T1"); ablação T2→T1 passa o vetor de k features candidatas do
    trial em vez do T1 fixo."""
    t1_arr = df.select(feature_ids).to_numpy().astype(np.float64)
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


def _permute_label_and_ret_net(df: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Núcleo puro (sem IO) da Fase 0b (`docs/t2_t1_ablation_veredito_
    duas_analises_2026-08-24.md` §4) — embaralha `label` e `ret_net`
    JUNTOS, mesmo índice de permutação por linha: quebra o pareamento
    X↔y, preserva a relação interna label↔ret_net daquela linha original
    (o que o nulo testa é "o modelo aprende algo real da relação X→
    resultado", não "label e ret_net deixam de fazer sentido juntos").
    Todas as outras colunas (features, `sample_weight`, `t0`) ficam
    intocadas na linha original — só o CONTEÚDO de `label`/`ret_net` se
    move entre linhas, não a ordem das linhas em si."""
    perm = np.random.default_rng(seed).permutation(df.height)
    return df.with_columns(
        pl.Series("label", df["label"].to_numpy()[perm]),
        pl.Series("ret_net", df["ret_net"].to_numpy()[perm]),
    )


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


CALIB_SPLIT_LEGACY_RANDOM = "legacy_random_stratified"
CALIB_SPLIT_TEMPORAL_PURGED = "temporal_purged"

# AG-212 -- base do rebalanceamento de classe. `count` = comportamento
# legado (`n_neg/n_pos`, bit-exato); `weight` = razão de MASSA
# (`Σw_neg/Σw_pos`), coerente com o fato de o gradiente do LightGBM já ser
# ponderado por `sample_weight`. Ver `SideModelResult.scale_pos_weight_*`.
CLASS_BALANCE_COUNT = "count"
CLASS_BALANCE_WEIGHT = "weight"

# AG-312 (ADR-005 §13 v2 §13.10) -- base do peso do CALIBRADOR isotonico.
# `sample_weight` = comportamento legado (`uniqueness * |ret_net|`, o mesmo
# peso da PERDA); `uniqueness` = so a correcao de redundancia estatistica.
#
# Isotonica ponderada devolve `E_w[y|x]`, e `|ret_net|` no SL e 1,25-1,29x
# o do TP (o custo subtrai do ganho e soma a perda), entao o peso legado
# sub-pondera exatamente a classe positiva. MEDIDO em 5 celulas: sob o peso
# legado a saida do calibrador estima 0,4323 quando `P(TP)` real e 0,4967
# -- vies de -6,45 pp (-13,0%). Sob `uniqueness` sozinho o vies cai para
# +0,0004, e nas 5 celulas fica em [-0,0012, +0,0030] -- duas ordens de
# grandeza menor, e sem sinal sistematico (3 para cima, 2 para baixo).
#
# O principio, e ele decide qual dos dois pertence aqui: `uniqueness`
# corrige REDUNDANCIA ESTATISTICA (quantas observacoes independentes
# existem) e pertence a qualquer estimador; `|ret_net|` codifica
# IMPORTANCIA ECONOMICA e pertence a uma funcao de DECISAO, nao a uma
# estimativa de probabilidade. A perda do LightGBM segue com o peso
# completo (B10/§3.5 intactos) -- o que muda e so o calibrador.
CALIB_WEIGHT_SAMPLE_WEIGHT = "sample_weight"
CALIB_WEIGHT_UNIQUENESS = "uniqueness"

# AG-210 -- política de resolução de `tau`. Ver `resolve_joint_tau` e
# `run_fold`.
TAU_POLICY_LEGACY_PER_SIDE = "legacy_per_side"
TAU_POLICY_TOTAL_COMMON_OOF = "total_common_oof"


def _temporal_purged_calib_split(
    t0_ms: IntArray, t1_ms: IntArray, *, holdout_frac: float
) -> tuple[IntArray, IntArray]:
    """Núcleo puro (Idioma A) — sub-split interno do treino com PURGE por
    `t1`, alternativa a `_stratified_calib_split` (`AG-209`).

    **Achado (`lgbm-crypto-quant`, 2026-08-25).** `_stratified_calib_split`
    usa `train_test_split` ALEATÓRIO. Com rótulo de triple barrier, dois
    labels vizinhos no tempo compartilham `[t0, t1]` -- um split aleatório
    põe quase-cópias dos dois lados da fronteira, então o calibrador
    isotônico é ajustado sobre observações que o `fit` já viu em
    substância. B08 ("calibrador ajustado sobre o próprio OOF") é cumprido
    na LETRA (o sub-split existe) e violado no ESPÍRITO (o sub-split não
    isola informação). É literalmente o fenômeno que B09 existe pra
    impedir, aplicado no CPCV externo e não no sub-split interno --
    mesmo pipeline, dois níveis de rigor diferentes.

    Consequência mensurável: o calibrador fica otimista, e `tau` (o
    quantil da distribuição calibrada) herda esse otimismo inteiro.

    Desenho: `calib` é o BLOCO TEMPORAL CONTÍGUO final do treino
    (`holdout_frac` das linhas, por `t0` ordenado); `fit` é o prefixo,
    MENOS toda linha cujo `t1` alcance `min(t0)` do bloco de calibração --
    mesma condição de overlap de intervalo de `src.validation.cpcv.
    generate_splits` (B09), aplicada aqui dentro.

    Levanta `ValueError` se o purge esvaziar o `fit` (fold degenerado):
    falhar alto, nunca devolver um `fit` vazio que só quebraria mais
    tarde dentro do LightGBM sem contexto."""
    n = int(t0_ms.shape[0])
    if n < 2:  # noqa: magic-number -- 1 linha não comporta dois lados de split
        raise ValueError(
            f"_temporal_purged_calib_split: n={n} linhas -- sub-split precisa de >= 2"
        )
    order = np.argsort(t0_ms, kind="stable")
    n_calib = round(n * holdout_frac)
    n_calib = max(1, min(n_calib, n - 1))
    calib_positions = order[n - n_calib :]
    fit_candidates = order[: n - n_calib]

    calib_start = int(t0_ms[calib_positions].min())
    # purge (B09): descarta do fit toda linha cujo intervalo de label
    # ainda esteja ABERTO quando o bloco de calibração começa.
    keep = t1_ms[fit_candidates] < calib_start
    fit_positions = fit_candidates[keep]
    if fit_positions.shape[0] == 0:
        raise ValueError(
            "_temporal_purged_calib_split: purge por t1 esvaziou o conjunto de fit "
            f"(n={n}, n_calib={n_calib}, calib_start={calib_start}) -- fold degenerado, "
            "horizonte de label cobre todo o prefixo de treino"
        )
    return fit_positions.astype(np.int64), calib_positions.astype(np.int64)


def _temporal_purged_three_way_split(
    t0_ms: IntArray, t1_ms: IntArray, *, stop_frac: float, calib_frac: float
) -> tuple[IntArray, IntArray, IntArray]:
    """ADR-005 §13.14.3 (item 9 de §13.17) -- extensão de `_temporal_
    purged_calib_split` para TRÊS blocos temporais contíguos, cada um
    purgado por `t1` contra a fronteira seguinte: `fit` (prefixo) / `stop`
    (bloco do meio, `eval_set` do early stopping) / `calib` (bloco final,
    calibrador isotônico -- MESMO papel que já tinha no split de 2).

    Ordem cronológica fit -> stop -> calib (`calib` continua sendo o
    sufixo mais recente, mesma convenção de `_temporal_purged_calib_
    split`). Purge só precisa comparar `fit` contra o INÍCIO de `stop` --
    `stop` já é anterior a `calib` por construção (bloco contíguo), então
    `t1[fit] < stop_start < calib_start` vale transitivamente sem checar
    `fit` contra `calib_start` de novo. `stop` é purgado contra o início
    de `calib` pelo mesmo motivo que `fit` é purgado hoje contra `calib`
    no split de 2: `stop` alimenta uma decisão (quando parar de treinar)
    que não pode enxergar rótulo cujo `[t0,t1]` ainda esteja aberto
    quando `calib` começa.

    Levanta `ValueError` se o purge esvaziar `fit` OU `stop` -- mesma
    disciplina de falha alta de `_temporal_purged_calib_split`, nunca um
    conjunto vazio que só quebraria mais tarde dentro do LightGBM."""
    n = int(t0_ms.shape[0])
    if n < 3:  # noqa: magic-number -- 3 blocos não cabem em menos de 3 linhas
        raise ValueError(
            f"_temporal_purged_three_way_split: n={n} linhas -- split de 3 precisa de >= 3"
        )
    if stop_frac <= 0.0 or calib_frac <= 0.0 or stop_frac + calib_frac >= 1.0:
        raise ValueError(
            f"_temporal_purged_three_way_split: stop_frac={stop_frac}, calib_frac={calib_frac} "
            "-- os dois precisam ser > 0 e somar < 1 (sobra pra 'fit')"
        )
    order = np.argsort(t0_ms, kind="stable")
    n_calib = round(n * calib_frac)
    n_calib = max(1, min(n_calib, n - 2))
    n_stop = round(n * stop_frac)
    n_stop = max(1, min(n_stop, n - n_calib - 1))

    calib_positions = order[n - n_calib :]
    stop_candidates = order[n - n_calib - n_stop : n - n_calib]
    fit_candidates = order[: n - n_calib - n_stop]

    calib_start = int(t0_ms[calib_positions].min())
    stop_keep = t1_ms[stop_candidates] < calib_start
    stop_positions = stop_candidates[stop_keep]
    if stop_positions.shape[0] == 0:
        raise ValueError(
            "_temporal_purged_three_way_split: purge por t1 esvaziou 'stop' "
            f"(n={n}, n_stop={n_stop}, n_calib={n_calib}, calib_start={calib_start})"
        )
    stop_start = int(t0_ms[stop_positions].min())
    fit_keep = t1_ms[fit_candidates] < stop_start
    fit_positions = fit_candidates[fit_keep]
    if fit_positions.shape[0] == 0:
        raise ValueError(
            "_temporal_purged_three_way_split: purge por t1 esvaziou 'fit' "
            f"(n={n}, n_stop={n_stop}, n_calib={n_calib}, stop_start={stop_start})"
        )
    return (
        fit_positions.astype(np.int64),
        stop_positions.astype(np.int64),
        calib_positions.astype(np.int64),
    )


def derive_ess_regularization(
    *,
    ess: float,
    n_rows: int,
    w_mean: float,
    scale_pos_weight: float,
    n_obs_independentes_alvo: float,
    fator_conservador: float,
) -> tuple[int, float]:
    """ADR-005 §13.14.1 (item 8 de §13.17) -- `min_child_samples`/`min_
    sum_hessian_in_leaf` derivados de `ESS` em vez de estipulados. Núcleo
    puro (Idioma A). Emenda à fórmula original de `§13.5-3` com os dois
    termos que o reexame (`§13.19` FP2) confirmou faltarem -- `w̄` (a
    MÉDIA, não um quantil inferior: o reexame retratou minha primeira
    correção, a média já pegava a folha de peso baixo corretamente):

        min_child_samples = ceil(n_obs_independentes_alvo * linhas/ESS)
        min_sum_hessian_in_leaf = min_child_samples * w̄ * 0,25
                                   / scale_pos_weight * fator_conservador

    `0,25` é `p(1-p)` no pior caso (`p=0,5`), não uma constante de
    domínio -- é a cota MATEMÁTICA do produto, válida para qualquer
    problema binário, mesma categoria de `_BPS_PER_UNIT`.
    `÷ scale_pos_weight` (defeito i de §13.14.1): a hessiana real inclui
    `label_weight` -- que É `scale_pos_weight` na classe positiva
    (verificado na fonte do LightGBM) -- e a fórmula original omitia.
    `fator_conservador` (defeito ii): `p(1-p)` cai conforme o boosting
    avança; um piso derivado de `p=0,5` descreve só a iteração 0."""
    if ess <= 0.0:
        raise ValueError(f"derive_ess_regularization: ess={ess} precisa ser > 0")
    if scale_pos_weight <= 0.0:
        raise ValueError(
            f"derive_ess_regularization: scale_pos_weight={scale_pos_weight} precisa ser > 0"
        )
    linhas_por_obs_independente = n_rows / ess
    min_child_samples = math.ceil(n_obs_independentes_alvo * linhas_por_obs_independente)
    p_vezes_1_menos_p_pior_caso = 0.25  # noqa: magic-number -- cota matemática de p(1-p), não constante de domínio
    min_sum_hessian_in_leaf = (
        min_child_samples
        * w_mean
        * p_vezes_1_menos_p_pior_caso
        / scale_pos_weight
        * fator_conservador
    )
    return min_child_samples, min_sum_hessian_in_leaf


def decide_side(
    p_long: FloatArray, p_short: FloatArray, *, tau_long: float, tau_short: float
) -> SideArray:
    """Núcleo puro da REGRA DE DECISÃO (§5.6) — `+1`/`-1`/`0` por linha.

    Extraída de `run_fold` (2026-08-25, `AG-210`) pelo mesmo motivo
    estrutural de `src.validation.cpcv._embargo_ms`/`_g_end_effective`:
    o solver de `tau` (`resolve_joint_tau`) e a inferência precisam usar
    literalmente a MESMA linha de código, não duas cópias que podem
    divergir silenciosamente. Um solver que resolvesse `tau` contra uma
    regra ligeiramente diferente da aplicada produziria uma taxa de
    sinal que não bate com a orçada -- e o erro seria invisível."""
    is_long = (p_long > tau_long) & (p_long > p_short)
    is_short = (p_short > tau_short) & (p_short > p_long) & ~is_long
    side_hat = np.zeros(p_long.shape[0], dtype=np.int8)
    side_hat[is_long] = 1
    side_hat[is_short] = -1
    return side_hat


# Tolerância e teto de iteração da bisseção de `resolve_joint_tau`. Não são
# constantes de domínio (não mudam nenhuma decisão econômica): são o
# critério de parada de uma busca numérica determinística, mesma categoria
# de `leakage.py::tolerance = 1e-6` e `_GRADE_CONSISTENCY_RTOL`.
_JOINT_TAU_RATE_TOL = 1e-6  # noqa: magic-number
_JOINT_TAU_MAX_ITER = 64  # noqa: magic-number


def resolve_joint_tau(
    p_long: FloatArray,
    p_short: FloatArray,
    *,
    target_signal_rate: float,
) -> tuple[float, float, float]:
    """Núcleo puro (Idioma A) — resolve o PAR `(tau_long, tau_short)` para
    que a taxa de sinal TOTAL, sob `decide_side` completa (dominância
    inclusa), bata `target_signal_rate`. Devolve
    `(tau_long, tau_short, taxa_realizada)`.

    **Achado (`lgbm-crypto-quant`, 2026-08-25, `AG-210`) -- o motor
    contradiz uma constante classe A já declarada.**
    `config/constants.yaml::fee_budget_is_per_side` tem `value: false`,
    `provenance: DERIVED`, e a fonte diz textualmente que o orçamento
    (§0.2 R3, `trades/mês <= (fee_budget_monthly × equity) / (N × c)`, com
    `c` = custo POR TRADE, sem termo de lado) produz `661/ano · 1,89% das
    barras` como contagem **TOTAL** -- e que `target_signal_rate = 0,0189`
    foi derivado desse total (`661 / 35.064`). Mas `fit_side_model` aplica
    o quantil `1 - target_signal_rate` a CADA LADO independentemente:
    `tau_long` produz 1,89% no lado long E `tau_short` produz 1,89% no
    lado short, sobre populações diferentes.

    Este repo JÁ corrigiu esse mesmo erro uma vez: `src/analysis/
    tau_diagnostics.py` tinha introduzido um fator `×2.0` ("2 lados"),
    propagado por citação para `faixa1_5_prerequisites::fee_budget_sweep`;
    os dois foram corrigidos e a constante `fee_budget_is_per_side` foi
    criada exatamente para registrar a semântica. A correção, porém, foi
    feita nos DIAGNÓSTICOS -- um grep por `fee_budget_is_per_side` em
    `src/` só encontra docstrings e comentários: **nenhum módulo de
    produção lê essa constante**, e o motor que de fato escolhe o
    threshold nunca foi tocado.

    Desenho do solver -- 2 incógnitas, 1 restrição, então o grau de
    liberdade extra precisa ser fechado por uma regra declarada a priori
    (B20: nunca por métrica OOS). A regra escolhida é **quantil comum**:
    procura o escalar `q` tal que `tau_side = quantile(p_side, 1 - q)`
    nos DOIS lados produza taxa total `= target_signal_rate`. Isso
    preserva a simetria long/short do desenho atual (nenhum lado ganha
    threshold mais frouxo por construção) e é determinístico. `rate(q)` é
    monotônica não-decrescente em `q`, então bisseção converge.

    `p_long`/`p_short` precisam vir da MESMA população de linhas (mesmo
    `t0` na mesma posição) -- ver `run_fold`, que os avalia sobre as
    barras comuns de treino, não sobre as sub-populações por lado."""
    if not 0.0 < target_signal_rate < 1.0:
        raise ValueError(
            f"resolve_joint_tau: target_signal_rate={target_signal_rate} fora de (0, 1)"
        )
    if p_long.shape != p_short.shape:
        raise ValueError(
            f"resolve_joint_tau: p_long.shape={p_long.shape} != p_short.shape={p_short.shape} "
            "-- os dois precisam vir da MESMA população de linhas"
        )

    def _rate_for_q(q: float) -> tuple[float, float, float]:
        tau_l = float(np.quantile(p_long, 1.0 - q))
        tau_s = float(np.quantile(p_short, 1.0 - q))
        side_hat = decide_side(p_long, p_short, tau_long=tau_l, tau_short=tau_s)
        return tau_l, tau_s, float(np.mean(side_hat != 0))

    lo, hi = 0.0, 1.0
    tau_l, tau_s, rate = _rate_for_q(target_signal_rate)
    for _ in range(_JOINT_TAU_MAX_ITER):
        if abs(rate - target_signal_rate) <= _JOINT_TAU_RATE_TOL:
            break
        mid = (lo + hi) / 2.0
        tau_l, tau_s, rate = _rate_for_q(mid)
        if rate < target_signal_rate:
            lo = mid
        else:
            hi = mid
    return tau_l, tau_s, rate


# ADR-004 Fase 2 (docs/ADR-004_reformulacao_alvo_regra_decisao_e_
# inferencia_2026-08-25.md §4, docs/prompts/execucao_adr004_fases_1_a_3_
# 2026-08-25.md Passo 1) -- fronteira de decisao |mu| > lambda,
# lambda_t = max(c_t, lambda_B), substituindo o fechamento do grau de
# liberdade por TAXA DE SINAL ORÇADA (resolve_joint_tau acima) por
# fechamento por CUSTO. Implementado como medição opt-in (`evaluate_
# cost_derived_lambda` em `run_fold`), NÃO como novo default de
# `tau_policy` -- decide_side/predictions.parquet continuam bit-exatos
# até o Manager decidir promover isto a política real de produção.
#
# Ponte pré-Fase-1: a Fase 1 (mu de uma regressao real) ainda não existe
# -- `implied_mu_from_prob` traduz a probabilidade calibrada JÁ
# existente em retorno esperado IMPLICADO, em unidades de múltiplo de
# ATR (mesma escala de `E27f_cost_atr_ratio`), usando exatamente o
# argumento do ADR-004 §0: sob payoff SIMÉTRICO (`tp_atr_mult ==
# sl_atr_mult`, confirmado em `constants.yaml` desde a correção do S1,
# 2026-08-24), P(TP) ordena quase idêntico a E[r] -- então
#     mu = P(TP)*payoff*sigma - (1-P(TP))*payoff*sigma = payoff*(2P(TP)-1)
# em unidades de sigma=ATR. Isto NÃO é a Fase 1 (não há regressão real,
# não fecha AG-212/AG-213) -- é o degrau intermediário que deixa a Fase 2
# medível sem depender da Fase 1 primeiro, exatamente a ordem de execução
# que o prompt pede (2 -> 0 -> 3 -> 1).
def implied_mu_from_prob(p: FloatArray, *, payoff_atr_mult: float) -> FloatArray:
    """Núcleo puro -- ver bloco de comentário acima para a derivação e a
    ressalva de validade (só correta sob payoff simétrico)."""
    return payoff_atr_mult * (2.0 * p - 1.0)


def decide_side_cost_derived(
    p_long: FloatArray,
    p_short: FloatArray,
    cost_atr_ratio: FloatArray,
    *,
    payoff_atr_mult: float,
    lambda_b: float,
) -> SideArray:
    """Núcleo puro -- irmã de `decide_side`, mesma estrutura de dominância
    (`is_long`/`is_short` mutuamente exclusivos), critério de aceitação
    substituído: em vez de `p_side > tau_side` (escalar fixo), usa
    `mu_side > max(cost_atr_ratio, lambda_b)` -- o limiar cresce com o
    custo REAL daquela barra em vez de ser o mesmo para toda barra."""
    mu_long = implied_mu_from_prob(p_long, payoff_atr_mult=payoff_atr_mult)
    mu_short = implied_mu_from_prob(p_short, payoff_atr_mult=payoff_atr_mult)
    lambda_t = np.maximum(cost_atr_ratio, lambda_b)
    is_long = (mu_long > lambda_t) & (mu_long > mu_short)
    is_short = (mu_short > lambda_t) & (mu_short > mu_long) & ~is_long
    side_hat = np.zeros(p_long.shape[0], dtype=np.int8)
    side_hat[is_long] = 1
    side_hat[is_short] = -1
    return side_hat


_LAMBDA_B_RATE_TOL = 1e-6  # noqa: magic-number -- mesma tolerância de _JOINT_TAU_RATE_TOL, critério de parada numérico
_LAMBDA_B_MAX_ITER = 64  # noqa: magic-number -- mesmo teto de _JOINT_TAU_MAX_ITER


def resolve_joint_lambda(
    p_long: FloatArray,
    p_short: FloatArray,
    cost_atr_ratio: FloatArray,
    *,
    payoff_atr_mult: float,
    target_signal_rate: float,
) -> tuple[float, float]:
    """Núcleo puro -- bisseciona `lambda_B` (ADR-004 §4 ponto 3) até a taxa
    de sinal TOTAL sob `decide_side_cost_derived` bater
    `target_signal_rate`. Retorna `(lambda_b, taxa_realizada)`.

    Direção da busca é invertida em relação a `resolve_joint_tau`:
    `rate` é DEcrescente em `lambda_b` (limiar mais alto -> menos sinal),
    não crescente. Faixa de busca `[-payoff_atr_mult, payoff_atr_mult]` --
    `mu` nunca sai desse intervalo (`p` ∈ [0,1]), então é a faixa inteira
    de valores que `lambda_b` pode influenciar de fato.

    Se `target_signal_rate` não for atingível dentro da faixa (o piso de
    custo `cost_atr_ratio` já domina em todo o espectro, ou o modelo não
    produz `mu` alto o bastante em lugar nenhum), a bisseção converge para
    a borda mais próxima e LOGA o achado -- nunca falha silenciosamente
    fingindo ter batido o alvo (mesmo espírito do fallback explícito de
    `_resolve_tau_on_common_bars`)."""
    if not 0.0 < target_signal_rate < 1.0:
        raise ValueError(
            f"resolve_joint_lambda: target_signal_rate={target_signal_rate} fora de (0, 1)"
        )
    if p_long.shape != p_short.shape or p_long.shape != cost_atr_ratio.shape:
        raise ValueError(
            f"resolve_joint_lambda: p_long.shape={p_long.shape}, p_short.shape="
            f"{p_short.shape}, cost_atr_ratio.shape={cost_atr_ratio.shape} -- as três "
            "precisam vir da MESMA população de linhas"
        )

    def _rate_for_lambda_b(lb: float) -> float:
        side_hat = decide_side_cost_derived(
            p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff_atr_mult, lambda_b=lb
        )
        return float(np.mean(side_hat != 0))

    lo, hi = -payoff_atr_mult, payoff_atr_mult
    rate_lo, rate_hi = _rate_for_lambda_b(lo), _rate_for_lambda_b(hi)
    if target_signal_rate > rate_lo:
        logger.warning(
            "models.alpha.resolve_joint_lambda_alvo_inatingivel_piso_custo",
            target_signal_rate=target_signal_rate,
            max_rate_atingivel=rate_lo,
            detail="piso de custo (cost_atr_ratio) ja domina lambda_b=-payoff em toda a "
            "populacao -- taxa maxima possivel sob este regime de custo/modelo e menor "
            "que o orcamento; retornando lambda_b=-payoff (o mais permissivo)",
        )
        return lo, rate_lo
    if target_signal_rate < rate_hi:
        logger.warning(
            "models.alpha.resolve_joint_lambda_alvo_inatingivel_teto_payoff",
            target_signal_rate=target_signal_rate,
            min_rate_atingivel=rate_hi,
            detail="mesmo no lambda_b mais restritivo (=payoff) a taxa realizada excede "
            "o alvo -- modelo produz mu alto para uma fracao da populacao maior que o "
            "orcamento; retornando lambda_b=+payoff (o mais restritivo)",
        )
        return hi, rate_hi
    lb, rate = lo, rate_lo
    for _ in range(_LAMBDA_B_MAX_ITER):
        if abs(rate - target_signal_rate) <= _LAMBDA_B_RATE_TOL:
            break
        mid = (lo + hi) / 2.0
        rate = _rate_for_lambda_b(mid)
        lb = mid
        if rate < target_signal_rate:
            hi = mid  # rate decrescente em lambda_b -- para AUMENTAR rate, DIMINUI lambda_b
        else:
            lo = mid
    return lb, rate


# ADR-005 §13 v2 -- item 11 de §13.17 (`§13.16.4`): trocar `p̂ > tau`
# (limiar global, quantil) por `p̂ > breakeven(linha)` (identidade
# contábil, conhecida em t0) -- que É a restrição R2 (`CLAUDE.md` §0.2)
# reescrita por linha em vez de por célula.
#
# Achado real ao implementar isto (`lgbm-crypto-quant`, 2026-08-26): o
# GATE já existe em código, sem ter sido reconhecido como tal. Sob payoff
# simétrico (`tp_atr_mult == sl_atr_mult == payoff_atr_mult`, a geometria
# de produção vigente -- ver `src.analysis.r2_admissibility_census.
# payoff_simetrico`), `decide_side_cost_derived` já compara `mu_side >
# max(cost_atr_ratio, lambda_b)`; com `lambda_b = -payoff_atr_mult` (o
# valor mais permissivo -- nunca vincula, pois `cost_atr_ratio >= 0 >
# -payoff_atr_mult` sempre), o piso vira `cost_atr_ratio` puro, e:
#
#     mu > cost_atr_ratio
#     payoff*(2p-1) > cost_atr_ratio
#     p > 0,5 + cost_atr_ratio/(2*payoff)
#     p > breakeven(linha)                    <- exatamente a fórmula acima
#
# O que NÃO pré-existe é o TETO DE CAPACIDADE que `§13.16.4` propõe:
# "entre os que passam, os top-q por margem". `resolve_joint_lambda`
# (mecanismo ADR-004 Fase 2 já em produção-de-medição) resolve um `lambda_
# b` ESCALAR que vira um segundo limiar sobre `mu` -- não um ranking por
# MARGEM (`mu - cost_atr_ratio`). Os dois mecanismos DIVERGEM quando
# `cost_atr_ratio` varia entre linhas: um limiar escalar em `mu` trata
# igual duas linhas de `mu` idêntico e custo diferente, mesmo que a
# margem delas seja diferente (`test_decide_side_breakeven_topq_diverge_
# de_lambda_threshold_quando_custo_varia` prova isso com número real, não
# só descreve). `decide_side_breakeven_topq` abaixo é a leitura literal
# de `§13.16.4`: gate absoluto (breakeven) + ranking por margem (não por
# `mu` bruto) para o teto.
#
# Nenhuma das duas funções abaixo é chamada por `run_fold` ainda --
# mesmo status de "medição opt-in, nunca reescreve side_hat/predictions.
# parquet" que `evaluate_cost_derived_lambda` teve antes de `resolve_
# joint_lambda` existir. QUAL mecanismo de teto (limiar em mu vs. ranking
# por margem) vira produção é decisão do Manager -- item 11 é listado
# como "decisão, não modelo" em `§13.17`, e as duas opções continuam
# testáveis e medíveis lado a lado até essa decisão.


def breakeven_from_cost_atr_ratio(
    cost_atr_ratio: FloatArray, *, payoff_atr_mult: float
) -> FloatArray:
    """`P(TP)` de breakeven por linha, direto de `cost_atr_ratio`
    (`E27f_cost_atr_ratio`, custo/ATR -- conhecido em `t0`, já uma
    feature T1 de produção). Ver derivação completa no bloco de
    comentário acima desta seção.

    Mesma IDENTIDADE que `src.analysis.r2_admissibility_census.
    breakeven_probability` mede sobre `labels.parquet` (preço) -- as duas
    não podem compartilhar código (`models/` não importa `analysis/`,
    `CLAUDE.md` Layer hierarchy), mas são a MESMA fórmula, sob a MESMA
    premissa de payoff simétrico. Não verifica simetria aqui (a feature
    de entrada já é `cost/ATR`, agnóstica a `tp_atr_mult`/`sl_atr_mult`
    individuais) -- a premissa é de quem chama, mesma disciplina de
    `implied_mu_from_prob`."""
    be = 0.5 + cost_atr_ratio / (2.0 * payoff_atr_mult)  # noqa: unguarded-ratio -- payoff_atr_mult é tp_atr_mult/sl_atr_mult (classe A, sempre > 0 por construção; mesma premissa não guardada de implied_mu_from_prob)
    return np.asarray(be, dtype=np.float64)


def decide_side_breakeven(
    p_long: FloatArray,
    p_short: FloatArray,
    cost_atr_ratio: FloatArray,
    *,
    payoff_atr_mult: float,
) -> SideArray:
    """`p̂ > breakeven(linha)` puro, SEM teto de capacidade -- ver
    `decide_side_breakeven_topq` para a versão completa do item 11.

    Deliberadamente o caso degenerado de `decide_side_cost_derived` com
    `lambda_b = -payoff_atr_mult`, não uma reimplementação -- mesmo
    princípio já declarado em `decide_side`/`resolve_joint_tau` ("a mesma
    LINHA de código, não duas cópias que podem divergir silenciosamente").
    `test_decide_side_breakeven_bate_formula_fechada_independente` prova a
    equivalência contra `p > breakeven` calculado à parte, não só contra
    esta função irmã."""
    return decide_side_cost_derived(
        p_long,
        p_short,
        cost_atr_ratio,
        payoff_atr_mult=payoff_atr_mult,
        lambda_b=-payoff_atr_mult,
    )


def select_top_q_by_margin(margin: FloatArray, *, q: float) -> BoolArray:
    """Núcleo puro do teto de capacidade do item 11. Entre linhas
    ADMISSÍVEIS (margem `> 0`; inadmissíveis chegam com margem `-inf` e
    nunca são selecionadas), mantém as top `ceil(q*n)` por MARGEM
    (`mu - cost_atr_ratio`, equivalente a `p̂ - breakeven(linha)` em
    unidades de probabilidade).

    `q` vem do orçamento de fees (`target_signal_rate`, `§12.6` condição
    1), nunca de métrica OOS (B20) -- mesma disciplina de `resolve_joint_
    tau`/`resolve_joint_lambda`, só que aqui a seleção é por RANKING, não
    por um segundo limiar escalar (ver bloco de comentário acima para a
    diferença medida contra `resolve_joint_lambda`)."""
    if not 0.0 < q <= 1.0:
        raise ValueError(f"select_top_q_by_margin: q={q} fora de (0, 1]")
    n = margin.shape[0]
    keep = np.zeros(n, dtype=np.bool_)
    if n == 0:
        return keep
    k = int(np.ceil(q * n))
    ranked = np.argsort(-margin, kind="stable")[:k]
    keep[ranked] = True
    # Linhas inadmissíveis (margem <= 0, inclusive -inf) nunca contam,
    # mesmo se `q` for generoso o bastante para incluí-las no top-k.
    keep &= margin > 0.0
    return keep


def decide_side_breakeven_topq(
    p_long: FloatArray,
    p_short: FloatArray,
    cost_atr_ratio: FloatArray,
    *,
    payoff_atr_mult: float,
    target_signal_rate: float,
) -> SideArray:
    """Item 11 completo (`§13.16.4`): gate = `decide_side_breakeven` (R2
    por linha, absoluto, conhecido em `t0`); teto de capacidade =
    `select_top_q_by_margin` sobre a margem do LADO ESCOLHIDO, com
    `q = target_signal_rate`. Núcleo puro -- ver bloco de comentário
    desta seção para o status (opt-in, não chamado por `run_fold` ainda)
    e a diferença medida contra o mecanismo `resolve_joint_lambda` já
    existente."""
    admiss = decide_side_breakeven(
        p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff_atr_mult
    )
    mu_long = implied_mu_from_prob(p_long, payoff_atr_mult=payoff_atr_mult)
    mu_short = implied_mu_from_prob(p_short, payoff_atr_mult=payoff_atr_mult)
    margin_long = mu_long - cost_atr_ratio
    margin_short = mu_short - cost_atr_ratio
    margin_chosen = np.where(
        admiss == 1, margin_long, np.where(admiss == -1, margin_short, -np.inf)
    )
    keep = select_top_q_by_margin(margin_chosen, q=target_signal_rate)
    return np.where(keep, admiss, 0).astype(np.int8)


@dataclass(frozen=True, slots=True)
class CapMechanismComparisonResult:
    """Item 11 -- comparação lado a lado dos dois mecanismos de teto de
    capacidade (limiar escalar em `mu`, via `resolve_joint_lambda`, vs.
    ranking por margem, via `decide_side_breakeven_topq`) sobre a MESMA
    população de linhas. Núcleo puro: só MEDE a divergência, não decide
    qual promover a produção — `§13.17` já lista o item 11 como "decisão,
    não modelo"."""

    lambda_b_resolved: float
    signal_rate_lambda: float
    signal_rate_topq: float
    n_rows: int
    n_agree: int
    n_disagree: int
    frac_agree: float


def compare_cap_mechanisms(
    p_long: FloatArray,
    p_short: FloatArray,
    cost_atr_ratio: FloatArray,
    *,
    payoff_atr_mult: float,
    target_signal_rate: float,
) -> CapMechanismComparisonResult:
    """Roda os DOIS mecanismos de teto do item 11 sobre a mesma população
    e reporta a divergência — não decide qual promover.
    `resolve_joint_lambda` resolve o `lambda_b` escalar que bate
    `target_signal_rate`; `decide_side_breakeven_topq` usa o MESMO
    `target_signal_rate` como `q` do ranking por margem — a comparação é
    sobre taxa de sinal EQUIVALENTE, não arbitrária entre os dois.

    Núcleo puro (Idioma A) — roda em memória sobre arrays já calculados
    (predições de um fold real, ou sintéticas em teste), nunca treina nem
    lê disco. Pronto pra rodar assim que `predictions.parquet` de um
    retreino real existir — o retreino segue represado hoje (`AG-298`,
    `ExpandingFeatureLookbackError`); nenhuma célula real foi medida por
    esta função ainda. Ver `test_decide_side_breakeven_topq_diverge_de_
    lambda_threshold_quando_custo_varia` (`tests/unit/test_models_alpha_
    breakeven_item11.py`) para o caso mínimo que prova a divergência
    estrutural que esta função quantifica em população real.

    Raises:
        ValueError: os três arrays não têm o mesmo `shape` (mesma
            população de linhas, precondição de todas as funções de item
            11 já existentes)."""
    if p_long.shape != p_short.shape or p_long.shape != cost_atr_ratio.shape:
        raise ValueError(
            f"compare_cap_mechanisms: p_long.shape={p_long.shape}, p_short.shape="
            f"{p_short.shape}, cost_atr_ratio.shape={cost_atr_ratio.shape} -- as três "
            "precisam vir da MESMA população de linhas"
        )
    n_rows = p_long.shape[0]
    lambda_b, rate_lambda = resolve_joint_lambda(
        p_long,
        p_short,
        cost_atr_ratio,
        payoff_atr_mult=payoff_atr_mult,
        target_signal_rate=target_signal_rate,
    )
    side_lambda = decide_side_cost_derived(
        p_long, p_short, cost_atr_ratio, payoff_atr_mult=payoff_atr_mult, lambda_b=lambda_b
    )
    side_topq = decide_side_breakeven_topq(
        p_long,
        p_short,
        cost_atr_ratio,
        payoff_atr_mult=payoff_atr_mult,
        target_signal_rate=target_signal_rate,
    )
    n_agree = int(np.sum(side_lambda == side_topq))
    rate_topq = float(np.mean(side_topq != 0)) if n_rows else float("nan")
    return CapMechanismComparisonResult(
        lambda_b_resolved=lambda_b,
        signal_rate_lambda=rate_lambda,
        signal_rate_topq=rate_topq,
        n_rows=n_rows,
        n_agree=n_agree,
        n_disagree=n_rows - n_agree,
        frac_agree=(n_agree / n_rows) if n_rows else float("nan"),  # noqa: unguarded-ratio -- n_rows==0 tratado no ternário
    )


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
    # --- AG-211: ESS (tamanho amostral EFETIVO) do treino deste fold/lado.
    # `Σ uniqueness`, a leitura literal de B24/§0.2 R4 ("medir Σ
    # uniqueness") -- soma MEDIDA, nunca uma das duas fórmulas fechadas
    # que B24 proíbe. Achado (`lgbm-crypto-
    # quant`, 2026-08-25): o número JÁ era calculado no repo
    # (`src.labels.experiment_log.summarize_labels`, campo
    # `sum_uniqueness`, marcado "N_eff medido (B24)") e gravado em
    # `data/label_engine_runs/label_engine_runs.parquet` -- mas um grep
    # por `sum_uniqueness` devolve 3 ocorrências, TODAS dentro do módulo
    # que o escreve: nenhum consumidor. Em particular, ele nunca chegava
    # ao `alpha_layer1_report.json`, que é onde `permanence_pass` é
    # decidido -- ou seja, a decisão de permanência da Camada 1 era
    # tomada sem que nada no relatório soubesse dizer quantas observações
    # INDEPENDENTES a sustentam. Aqui é por fold x lado (o `n` que de
    # fato treinou), não global por `labels.parquet`.
    sum_uniqueness_train: float = float("nan")
    # --- AG-212: os DOIS balanceamentos de classe, lado a lado.
    # `scale_pos_weight` é passado ao LightGBM em CONTAGEM (`n_neg/n_pos`),
    # mas o gradiente é ponderado por `sample_weight` (massa). O
    # rebalanceamento EFETIVO é `scale_pos_weight * Σw_pos/Σw_neg`, que
    # não é 1 e nunca foi medido. Não é fatal (a isotônica corrige o
    # NÍVEL da probabilidade), mas o que a árvore vê ao CRESCER (ganho de
    # split, `min_child_samples`, `min_sum_hessian_in_leaf`) é a
    # distribuição ponderada, não a contagem -- então a forma aprendida
    # depende do desalinhamento. Reportar os dois torna o desalinhamento
    # mensurável sem mudar nada por default.
    scale_pos_weight_count: float = float("nan")
    scale_pos_weight_weight: float = float("nan")
    # AG-312 -- INSTRUMENTACAO do nivel do calibrador. `p_calibrada_media`
    # e a media da saida do calibrador sobre o proprio split de calibracao;
    # `p_tp_contagem_calib` e a `P(TP)` por CONTAGEM no mesmo split. Sob um
    # calibrador nao enviesado os dois batem -- isotonica (ponderada ou
    # nao) preserva a soma ponderada por bloco, entao a divergencia entre
    # eles E o vies induzido pelo peso, medido em cada fold e cada lado em
    # vez de argumentado. Reportar os dois torna o defeito de §13.10
    # observavel para sempre, mesmo se a politica for revertida.
    p_calibrada_media: float = float("nan")
    p_tp_contagem_calib: float = float("nan")
    # `t0` (epoch ms) das linhas que entraram no FIT deste lado -- insumo
    # do modo `TAU_POLICY_TOTAL_COMMON_OOF` em `run_fold`, que precisa
    # saber quais barras o modelo já viu para tirar `tau` das que ele não
    # viu. `None` no caminho legado (não calculado, não usado).
    fit_t0_ms: IntArray | None = None
    # ADR-005 §13.14.3 (item 9 de §13.17) -- tamanho do bloco `stop`
    # (eval_set do early stopping) e a iteração real em que o boosting
    # parou. `0`/`None` no caminho legado (`early_stopping_mode=
    # EARLY_STOPPING_FIXED`) -- sem bloco de stop, `n_estimators` de
    # `hyper` é a contagem exata, não um teto.
    n_train_stop: int = 0
    best_iteration: int | None = None


def fit_side_model(
    train_side_df: pl.DataFrame,
    *,
    side: int,
    variant: str,
    hyper: LGBMHyperparams,
    seed: int,
    target_signal_rate: float,
    feature_ids: tuple[str, ...] = T1_FEATURE_IDS,
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
    device_type: str = "cpu",
    null_permutation_seed: int | None = None,
    calib_split_mode: str = CALIB_SPLIT_LEGACY_RANDOM,
    class_balance_basis: str = CLASS_BALANCE_COUNT,
    calib_weight_basis: str = CALIB_WEIGHT_SAMPLE_WEIGHT,
    regularization_basis: str = REGULARIZATION_FIXED,
    ic_magnitude_floor_k: float | None = None,
    early_stopping_mode: str = EARLY_STOPPING_FIXED,
) -> SideModelResult:
    """Treina UM binário (`M_long` se `side=1`, `M_short` se `side=-1`)
    sobre `train_side_df` — já filtrado por `src.models.dataset.
    side_subset` (NOFILL fora, warmup fora), já restrito ao TREINO do fold
    (nunca o teste). `y = 1` sse `barrier_hit == "TP"` (leitura literal de
    §5.2 "P(TP antes de SL)" — SL e TIME viram `y=0`, ver docstring do
    módulo `dataset.py` e o relatório do Sprint 8 para a justificativa
    completa desta escolha).

    `feature_ids` (2026-08-24, `docs/t2_t1_promotion_ablation_design_doc_
    2026-08-24.md` §5.2) — default `T1_FEATURE_IDS` preserva bit-exato
    todo call site de produção existente. Substitui as 7 referências
    hardcoded a `T1_FEATURE_IDS`/`DESIGN_COLUMNS` que existiam neste corpo
    (screening de monotonicidade ×2 -- CAMADA1 e CAMADA0 --, matriz de
    desenho, `feature_name` do booster, HHI, HHI-efetivo ×2) — achado real
    de auditoria: o conjunto de features estava fixo dentro desta função,
    não era parâmetro em lugar nenhum, apesar de `hyper: LGBMHyperparams`
    já ser injetável. Existe pra ablação T2→T1 treinar sobre um vetor de k
    features candidatas sem duplicar esta função.

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
    chama a função hoje.

    `null_permutation_seed` (2026-08-24, `docs/t2_t1_ablation_veredito_
    duas_analises_2026-08-24.md` §4, Fase 0b) — default `None` preserva
    produção bit-exato. Quando setado, embaralha `label` E `ret_net`
    JUNTOS (mesmo índice de permutação por linha) dentro de `train_side_
    df` antes de qualquer uso — quebra o pareamento X↔y, preserva a
    relação interna label↔ret_net daquela linha original. As DUAS
    colunas precisam mover juntas: `screen_monotone_constraints` deriva a
    direção de cada restrição monotônica de `ret_net` (`target_col`
    default), não de `label` — permutar só `label` deixaria a Camada1
    "trapacear" com informação econômica real via `monotone_constraints`
    mesmo treinada sobre rótulo de classificação puro ruído, contaminando
    o nulo que este parâmetro existe pra construir. `sample_weight` NUNCA
    é permutado — reflete unicidade/sobreposição temporal de `t1`
    (propriedade estrutural do label, não do resultado econômico),
    ortogonal ao que o nulo testa. Ponto de injeção único (aqui, não em
    `run_fold`/`run_all_folds`) porque `train_side_df` já chega aqui
    filtrado por `side_subset` — permutar depois disso é o que garante
    permutação POR LADO independente (a proporção de cada lado, e por
    consequência `scale_pos_weight` computado abaixo, sai igual ao run
    real). Escopo é só TREINO — o lado de teste de `run_fold` nunca passa
    por esta função, preservando o resultado econômico real na
    inferência/backtest por construção, não por caso especial."""
    if null_permutation_seed is not None:
        train_side_df = _permute_label_and_ret_net(train_side_df, null_permutation_seed)

    # ADR-005 §13.14.2 (item 6 de §13.17) -- ESS precisa estar disponível
    # ANTES da triagem de monotonicidade, só quando o piso de magnitude é
    # pedido. `uniqueness` opcional pelo mesmo motivo de sempre (AG-209/
    # AG-210/AG-312): chamadores de teste montam `train_side_df` sintético
    # sem ela. Pedir o piso sem a coluna FALHA ALTO -- um fallback
    # silencioso pro sinal puro reintroduziria exatamente o defeito que o
    # piso existe pra corrigir, sem deixar rastro.
    ess_for_ic_floor: float | None = None
    if ic_magnitude_floor_k is not None:
        if "uniqueness" not in train_side_df.columns:
            raise ValueError(
                "fit_side_model: ic_magnitude_floor_k setado exige a coluna 'uniqueness' "
                "em train_side_df (ESS para o piso de magnitude, §13.14.2) -- recebido um "
                "frame sem ela"
            )
        ess_for_ic_floor = float(
            train_side_df["uniqueness"].to_numpy().astype(np.float64).sum()
        )

    ic_results = monotonic.screen_monotone_constraints(
        train_side_df,
        feature_ids,
        side=side,
        unforce_features_by_side=unforce_features_by_side,
        ic_magnitude_floor_k=ic_magnitude_floor_k,
        ess=ess_for_ic_floor,
    )
    if variant == VARIANT_CAMADA1:
        t1_constraints = tuple(ic_results[f].constraint for f in feature_ids)
    elif variant == VARIANT_CAMADA0:
        # AG-371 (2026-08-28, decisão do Manager, promovido a default de
        # produção -- AG-371-ADDENDUM-8) -- Camada0 continua sem
        # restrição de forma em 21 das 22 features (baseline fraco por
        # desenho, intocado); `CAMADA0_CONSTRAINED_FEATURES` (hoje só
        # `E27f_cost_atr_ratio`) usa a MESMA direção que a triagem de IC
        # já calculou pra Camada1 acima (`ic_results`, não um valor
        # hardcoded) -- não é um modelo econômico novo sendo injetado em
        # Camada0, é o mesmo freio que já existiria se a feature também
        # estivesse sujeita à triagem normal.
        t1_constraints = tuple(
            ic_results[f].constraint if f in CAMADA0_CONSTRAINED_FEATURES else 0
            for f in feature_ids
        )
    else:
        raise ValueError(f"fit_side_model: variant desconhecida {variant!r}")
    monotone_constraints = t1_constraints

    X_all = build_design_matrix(train_side_df, feature_ids=feature_ids)
    y_all = (train_side_df["label"].cast(pl.Int64) == 1).to_numpy().astype(np.int64)
    w_all = train_side_df["sample_weight"].to_numpy().astype(np.float64)

    # `t0`/`t1` são OPCIONAIS aqui, de propósito: o caminho legado desta
    # função nunca precisou deles (o split de calibração é aleatório, o
    # `tau` é per-side), e há chamadores de teste que montam um
    # `train_side_df` sintético sem essas colunas. Exigi-las
    # incondicionalmente ao introduzir AG-209/AG-210 quebrou 5 testes
    # existentes -- achado da primeira execução real desta correção, não
    # um contrato novo que eu possa impor de fora. As duas features novas
    # que dependem delas falham alto e explicitamente se forem pedidas sem
    # a coluna; o default não paga nada por elas existirem.
    t0_ms_all = (
        train_side_df["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        if "t0" in train_side_df.columns
        else None
    )

    holdout_frac = float(load_constant("alpha_calibration_holdout_frac"))
    stop_idx: IntArray | None = None
    if early_stopping_mode == EARLY_STOPPING_THREE_WAY:
        # ADR-005 §13.14.3 (item 9 de §13.17) -- 3 partições em vez de 2,
        # SUBSTITUI o split acima inteiro (não compõe com ele). Só faz
        # sentido purgado por tempo -- um split aleatório não tem
        # fronteira temporal pra purgar contra `stop`/`calib`.
        if calib_split_mode != CALIB_SPLIT_TEMPORAL_PURGED:
            raise ValueError(
                f"fit_side_model: early_stopping_mode={EARLY_STOPPING_THREE_WAY!r} exige "
                f"calib_split_mode={CALIB_SPLIT_TEMPORAL_PURGED!r} -- um split aleatório não "
                "tem fronteira temporal para purgar contra o bloco de stop"
            )
        if t0_ms_all is None or "t1" not in train_side_df.columns:
            raise ValueError(
                f"fit_side_model: early_stopping_mode={EARLY_STOPPING_THREE_WAY!r} exige as "
                "colunas 't0' e 't1' em train_side_df (purge por t1 nas duas fronteiras, "
                "§13.14.3) -- recebido apenas "
                f"{sorted(set(train_side_df.columns) & {'t0', 't1'})}"
            )
        t1_ms_all = train_side_df["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        stop_frac = float(load_constant("alpha_early_stopping_stop_frac"))
        fit_idx, stop_idx, calib_idx = _temporal_purged_three_way_split(
            t0_ms_all, t1_ms_all, stop_frac=stop_frac, calib_frac=holdout_frac
        )
    elif calib_split_mode == CALIB_SPLIT_LEGACY_RANDOM:
        fit_idx, calib_idx = _stratified_calib_split(
            y_all, holdout_frac=holdout_frac, seed=_derived_seed(seed, side, 1)
        )
    elif calib_split_mode == CALIB_SPLIT_TEMPORAL_PURGED:
        # AG-209 -- ver `_temporal_purged_calib_split`.
        if t0_ms_all is None or "t1" not in train_side_df.columns:
            raise ValueError(
                f"fit_side_model: calib_split_mode={CALIB_SPLIT_TEMPORAL_PURGED!r} exige as "
                "colunas 't0' e 't1' em train_side_df (o purge por t1 é o ponto inteiro do "
                "modo, AG-209) -- recebido apenas "
                f"{sorted(set(train_side_df.columns) & {'t0', 't1'})}"
            )
        t1_ms_all = train_side_df["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        fit_idx, calib_idx = _temporal_purged_calib_split(
            t0_ms_all, t1_ms_all, holdout_frac=holdout_frac
        )
    else:
        raise ValueError(
            f"fit_side_model: calib_split_mode desconhecido {calib_split_mode!r} "
            f"(esperado {CALIB_SPLIT_LEGACY_RANDOM!r} ou {CALIB_SPLIT_TEMPORAL_PURGED!r})"
        )
    X_fit, y_fit, w_fit = X_all[fit_idx], y_all[fit_idx], w_all[fit_idx]
    X_calib, y_calib, w_calib = X_all[calib_idx], y_all[calib_idx], w_all[calib_idx]
    X_stop, y_stop, w_stop = (
        (X_all[stop_idx], y_all[stop_idx], w_all[stop_idx])
        if stop_idx is not None
        else (None, None, None)
    )

    # AG-312 -- peso do calibrador, resolvido por politica. `uniqueness` e
    # coluna OPCIONAL aqui pelo mesmo motivo que `t0`/`t1` (AG-209/AG-210):
    # ha chamadores de teste que montam `train_side_df` sintetico sem ela.
    # Pedir a politica nova sem a coluna falha ALTO e explicitamente, em vez
    # de cair em silencio no peso legado -- um fallback silencioso aqui
    # reintroduziria exatamente o vies que esta politica existe pra remover.
    if calib_weight_basis == CALIB_WEIGHT_SAMPLE_WEIGHT:
        w_calib_iso = w_calib
    elif calib_weight_basis == CALIB_WEIGHT_UNIQUENESS:
        if "uniqueness" not in train_side_df.columns:
            raise ValueError(
                f"fit_side_model: calib_weight_basis={CALIB_WEIGHT_UNIQUENESS!r} exige a "
                "coluna 'uniqueness' em train_side_df (e o ponto inteiro da politica, "
                "AG-312) -- recebido um frame sem ela"
            )
        u_all = train_side_df["uniqueness"].to_numpy().astype(np.float64)
        w_calib_iso = u_all[calib_idx]
    else:
        raise ValueError(
            f"fit_side_model: calib_weight_basis desconhecido {calib_weight_basis!r} "
            f"(esperado {CALIB_WEIGHT_SAMPLE_WEIGHT!r} ou {CALIB_WEIGHT_UNIQUENESS!r})"
        )

    # AG-212 -- os dois balanceamentos calculados SEMPRE (custo desprezível,
    # duas somas), mas só um alimenta o LightGBM: quem decide é
    # `class_balance_basis`, default `count` (bit-exato). Ver
    # `SideModelResult.scale_pos_weight_*` para o achado completo.
    n_pos = int(y_fit.sum())
    n_neg = int(y_fit.shape[0] - n_pos)
    scale_pos_weight_count = float(n_neg) / float(n_pos) if n_pos > 0 else 1.0
    w_pos = float(w_fit[y_fit == 1].sum())
    w_neg = float(w_fit[y_fit == 0].sum())
    scale_pos_weight_weight = (w_neg / w_pos) if w_pos > 0.0 else 1.0
    if class_balance_basis == CLASS_BALANCE_COUNT:
        scale_pos_weight = scale_pos_weight_count
    elif class_balance_basis == CLASS_BALANCE_WEIGHT:
        scale_pos_weight = scale_pos_weight_weight
    else:
        raise ValueError(
            f"fit_side_model: class_balance_basis desconhecido {class_balance_basis!r} "
            f"(esperado {CLASS_BALANCE_COUNT!r} ou {CLASS_BALANCE_WEIGHT!r})"
        )

    # ADR-005 §13.14.1 (item 8 de §13.17) -- piso de folha, resolvido por
    # política igual a `calib_weight_basis`/`class_balance_basis` acima.
    # `FIXED` (default, produção hoje) usa os dois valores literais de
    # `hyper` sem tocar neles -- bit-exato. `ESS_DERIVED` recalcula os
    # dois pela fórmula emendada (`derive_ess_regularization`); pedir
    # sem a coluna `uniqueness` FALHA ALTO, mesma disciplina de AG-312.
    # Parâmetro hoje INERTE em produção sob `num_leaves ∈ {2,3}`
    # (§13.9.3) -- ativar a política não muda nenhum artefato já
    # treinado até `max_depth` subir, decisão separada.
    if regularization_basis == REGULARIZATION_FIXED:
        min_child_samples_resolved = hyper.min_child_samples
        min_sum_hessian_in_leaf_resolved = hyper.min_sum_hessian_in_leaf
    elif regularization_basis == REGULARIZATION_ESS_DERIVED:
        if "uniqueness" not in train_side_df.columns:
            raise ValueError(
                f"fit_side_model: regularization_basis={REGULARIZATION_ESS_DERIVED!r} exige "
                "a coluna 'uniqueness' em train_side_df (ESS, §13.14.1) -- recebido um frame "
                "sem ela"
            )
        ess_reg = float(train_side_df["uniqueness"].to_numpy().astype(np.float64).sum())
        min_child_samples_resolved, min_sum_hessian_in_leaf_resolved = derive_ess_regularization(
            ess=ess_reg,
            n_rows=train_side_df.height,
            w_mean=float(w_fit.mean()),
            scale_pos_weight=scale_pos_weight,
            n_obs_independentes_alvo=hyper.ess_regularization_n_obs_independentes_alvo,
            fator_conservador=hyper.ess_regularization_fator_conservador,
        )
    else:
        raise ValueError(
            f"fit_side_model: regularization_basis desconhecido {regularization_basis!r} "
            f"(esperado {REGULARIZATION_FIXED!r} ou {REGULARIZATION_ESS_DERIVED!r})"
        )

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
        min_child_samples=min_child_samples_resolved,
        # AG-208 -- os dois entram com o default da própria biblioteca
        # (bit-exato com todo artefato já treinado); o que muda é que
        # agora são DECLARADOS em `constants.yaml` com proveniência e
        # `sweep_required`, em vez de herdados implicitamente. Ver
        # docstring de `LGBMHyperparams`: `min_child_samples` limita
        # CONTAGEM por folha, `min_sum_hessian_in_leaf` limita MASSA --
        # com `sample_weight` de cauda longa, só o segundo restringe o
        # que importa, e ele estava no default inerte.
        min_sum_hessian_in_leaf=min_sum_hessian_in_leaf_resolved,
        max_bin=hyper.max_bin,
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
    # corretamente. Ordem idêntica a `feature_ids` (mesma que
    # `build_design_matrix` usa para montar `X_fit`).
    # ADR-005 §13.14.3 (item 9 de §13.17) -- `eval_set`/`callbacks` só
    # entram sob `early_stopping_mode=EARLY_STOPPING_THREE_WAY`; caminho
    # legado (default) chama `.fit` exatamente como sempre, bit-exato.
    # `n_estimators` de `hyper` vira TETO de iterações, não contagem
    # exata -- `LGBMClassifier.predict_proba` já usa `best_iteration_`
    # automaticamente quando o early stopping disparou (comportamento
    # nativo do wrapper sklearn do LightGBM, não algo que este código
    # precise fazer à mão).
    fit_kwargs: dict[str, Any] = {"sample_weight": w_fit, "feature_name": list(feature_ids)}
    if early_stopping_mode == EARLY_STOPPING_THREE_WAY:
        stopping_rounds = int(load_constant("alpha_early_stopping_rounds"))
        # `eval_X`/`eval_y` (não `eval_set=[(X,y)]`) -- achado de
        # implementação: `eval_set` está DEPRECATED no LightGBM 4.7.0
        # (`uv.lock`), emite `LGBMDeprecationWarning` em runtime.
        # Verificado empiricamente que a API nova não emite warning
        # nenhum sob `warnings.simplefilter("error")`. Never silence a
        # warning without finding the root cause (CLAUDE.md) -- a causa
        # aqui era literalmente "existe uma API mais nova", não algo pra
        # suprimir.
        fit_kwargs["eval_X"] = X_stop
        fit_kwargs["eval_y"] = y_stop
        fit_kwargs["eval_sample_weight"] = [w_stop]
        fit_kwargs["callbacks"] = [
            lgb.early_stopping(stopping_rounds=stopping_rounds, verbose=False)
        ]
    model.fit(X_fit, y_fit, **fit_kwargs)

    # `np.asarray(...)` explícito -- os stubs do LightGBM tipam
    # `predict_proba` como `list` (imprecisão conhecida da biblioteca, não
    # do nosso código), o que quebra `mypy --strict` no fancy-indexing
    # `[:, 1]` (só `ndarray` suporta). Runtime já devolvia `ndarray`
    # sempre; a conversão é só correção de tipo estático, sem mudança de
    # valor.
    raw_calib = np.asarray(model.predict_proba(X_calib))[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    # AG-312 -- o peso do CALIBRADOR nao e o mesmo peso da PERDA. Ver o
    # bloco de `CALIB_WEIGHT_*` para a medicao e o principio. `w_fit` (com
    # `|ret_net|`) segue alimentando `model.fit` acima: B10/§3.5 intactos.
    calibrator.fit(raw_calib, y_calib, sample_weight=w_calib_iso)

    p_calibrada_media = float(calibrator.predict(raw_calib).mean())

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
    concentration = compute_concentration(gain_by_column, feature_ids)

    # HHI efetivo (D1/D2, CLAUDE.md) — matriz de correlação das
    # `feature_ids` deste trial sobre o MESMO `train_side_df` deste
    # fold/lado (in-fold, nunca o dataset inteiro — mesma disciplina de
    # `monotonic.screen_monotone_constraints` logo acima, que também
    # recebe só `train_side_df`). Sob ablação T2→T1 isso mede concentração
    # no vetor de k features REALMENTE treinado neste trial, não sempre no
    # T1 de produção — é o mesmo critério do CLAUDE.md (HHI efetivo <0,25)
    # aplicado ao vetor que está sendo avaliado.
    correlation_t1 = _t1_correlation_matrix(train_side_df, feature_ids=feature_ids)
    concentration_effective = compute_effective_concentration(
        correlation_t1, gain_by_column, feature_ids
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
        # AG-211 -- ESS medido (Σ uniqueness), não estipulado (B24).
        # Sobre `train_side_df` inteiro (fit + calib): é o conjunto que
        # este lado deste fold de fato consumiu.
        sum_uniqueness_train=float(
            train_side_df["uniqueness"].to_numpy().astype(np.float64).sum()
        )
        if "uniqueness" in train_side_df.columns
        else float("nan"),
        scale_pos_weight_count=scale_pos_weight_count,
        scale_pos_weight_weight=scale_pos_weight_weight,
        p_calibrada_media=p_calibrada_media,
        p_tp_contagem_calib=float(y_calib.mean()) if y_calib.shape[0] else float("nan"),
        # `None` quando `train_side_df` não trouxe `t0` (ver nota acima) --
        # `_resolve_tau_on_common_bars` trata `None` como "este lado não
        # informa quais barras viu", nunca como "não viu nenhuma".
        fit_t0_ms=t0_ms_all[fit_idx] if t0_ms_all is not None else None,
        n_train_stop=int(stop_idx.shape[0]) if stop_idx is not None else 0,
        best_iteration=(
            int(model.best_iteration_)
            if early_stopping_mode == EARLY_STOPPING_THREE_WAY and model.best_iteration_
            else None
        ),
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
    # ADR-004 Fase 2 -- diagnóstico opt-in (`evaluate_cost_derived_lambda`
    # em `run_fold`), `None` no caminho legado (produção, custo zero).
    cost_derived_lambda_diag: CostDerivedLambdaDiagnostic | None = None


def _unique_test_bars(
    test_bars_all_sides: pl.DataFrame, *, feature_ids: tuple[str, ...] = T1_FEATURE_IDS
) -> pl.DataFrame:
    """Uma linha por `t0` (feature não depende de lado) — usa as linhas de
    `side=1` como referência de deduplicação (toda barra tem exatamente uma
    linha `side=1` E uma `side=-1` em `labels.parquet`, ver
    `src.labels.triple_barrier.build_labels_both_sides`), mantém só barras
    com `feature_ids` válido (fora do warmup) — NÃO filtra por NOFILL (ver
    docstring do módulo: inferência roda em toda barra, NOFILL só importa
    para treino/backtest).

    `feature_ids` (2026-08-24, `docs/t2_t1_promotion_ablation_design_doc_
    2026-08-24.md` §5.2) — default `T1_FEATURE_IDS` preserva bit-exato o
    comportamento atual. Achado de correção (não só plumbing): sob ablação
    T2→T1, filtrar warmup pelas 7 features T1 fixas deixaria passar barras
    ainda NULL numa feature T2 candidata com lookback mais longo — o
    `build_design_matrix` do trial receberia `NaN` silencioso. Por isso o
    filtro de warmup usa as MESMAS `feature_ids` que o trial vai treinar,
    nunca um conjunto fixo diferente do que está sendo avaliado.

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
        (pl.col("side") == 1) & pl.col(feature_ids[0]).is_not_null()
    )
    for fid in feature_ids[1:]:
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


# Ocorrências mínimas ACIMA do quantil de corte para `tau` ser estimável
# com sentido. Não é constante de domínio (não muda nenhuma decisão
# econômica): é o piso amostral de um quantil extremo — o mesmo critério
# de "amostra grande o bastante para ver o percentil de interesse com
# ~10 ocorrências" que já governa a leitura de cauda neste projeto. O
# mínimo REAL de barras é DERIVADO daqui e de `target_signal_rate`
# (`ceil(10 / r)`), nunca estipulado como contagem fixa.
_MIN_OCCURRENCES_ABOVE_TAU = 10  # noqa: magic-number


def _resolve_tau_on_common_bars(
    train_bars: pl.DataFrame,
    long_result: SideModelResult,
    short_result: SideModelResult,
    *,
    feature_ids: tuple[str, ...],
    target_signal_rate: float,
) -> tuple[float, float, float]:
    """Ponto de entrada com IO-zero (recebe frame em memória) do modo
    `TAU_POLICY_TOTAL_COMMON_OOF` — resolve `(tau_long, tau_short)` sobre
    a população que fecha os DOIS achados de `tau` de uma vez (`AG-210`):

    **(1) População comum, não sub-população por lado.** `fit_side_model`
    tira `tau` de `train_side_df`, que já passou por `side_subset`
    (NOFILL FORA). Mas a inferência roda sobre `_unique_test_bars`, que
    NÃO filtra NOFILL — decisão correta e documentada (§3.7: NOFILL é
    ruído de execução, não de feature). O efeito colateral é que o
    quantil era tirado de uma população e aplicado a outra: P(NOFILL)
    correlaciona com volatilidade/spread, e `E27f_cost_atr_ratio`/
    `C06_vol_ratio_12_96` estão no vetor de features — as duas populações
    não têm a mesma distribuição de `p`. Aqui `tau` sai de
    `_unique_test_bars(train_bars)`: MESMO filtro, MESMA função, aplicada
    ao treino em vez do teste.

    **(2) Fora do fit.** Dentro da população comum, barras cujo `t0`
    entrou no `fit` de qualquer um dos dois lados são descartadas — o
    modelo é otimista nelas, e um quantil tirado de probabilidades
    otimistas não transfere. Sobram as barras que nenhum dos dois modelos
    ajustou (as de calibração de cada lado, mais as descartadas por
    NOFILL de ambos os lados).

    Fallback explícito e LOGADO (nunca silencioso): se a população
    out-of-fit não comportar o quantil `1 - r` com pelo menos
    `_MIN_OCCURRENCES_ABOVE_TAU` ocorrências acima do corte, cai para a
    população comum inteira — um `tau` levemente otimista é melhor que um
    `tau` estimado sobre uma dezena de pontos."""
    common = _unique_test_bars(train_bars, feature_ids=feature_ids)
    if common.height == 0:
        raise ValueError(
            "_resolve_tau_on_common_bars: nenhuma barra de treino com feature válida "
            "-- não há população sobre a qual resolver tau"
        )

    # Guard obrigatório: `fit_t0_ms=None` significa "este lado não sabe
    # informar quais barras viu" (o `train_side_df` daquele lado não trazia
    # `t0`), NUNCA "não viu nenhuma". Tratar `None` como conjunto vazio
    # marcaria barras já ajustadas como out-of-fit e produziria exatamente
    # o `tau` otimista que este modo existe pra evitar -- silenciosamente.
    fit_t0_long, fit_t0_short = long_result.fit_t0_ms, short_result.fit_t0_ms
    if fit_t0_long is None or fit_t0_short is None:
        raise ValueError(
            "_resolve_tau_on_common_bars: fit_t0_ms ausente em pelo menos um lado -- "
            "TAU_POLICY_TOTAL_COMMON_OOF exige a coluna 't0' no train_side_df dos dois "
            "lados para saber quais barras cada modelo ajustou (AG-210)"
        )
    t0_common = common["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    seen_in_fit = np.isin(t0_common, fit_t0_long) | np.isin(t0_common, fit_t0_short)
    oof_idx = np.flatnonzero(~seen_in_fit)

    min_bars = int(np.ceil(_MIN_OCCURRENCES_ABOVE_TAU / target_signal_rate))
    if oof_idx.shape[0] < min_bars:
        logger.warning(
            "models.alpha.tau_oof_insuficiente_fallback_populacao_comum",
            n_oof=int(oof_idx.shape[0]),
            n_common=int(common.height),
            min_bars_required=min_bars,
            detail="AG-210 -- população out-of-fit não comporta o quantil "
            "1-target_signal_rate com ocorrências suficientes acima do corte; "
            "tau resolvido sobre a população comum INTEIRA (inclui barras vistas "
            "no fit, portanto levemente otimista)",
        )
        tau_frame = common
    else:
        tau_frame = common[oof_idx]

    X_tau = build_design_matrix(tau_frame, feature_ids=feature_ids)
    p_long = long_result.calibrator.predict(
        np.asarray(long_result.model.predict_proba(X_tau))[:, 1]
    )
    p_short = short_result.calibrator.predict(
        np.asarray(short_result.model.predict_proba(X_tau))[:, 1]
    )
    return resolve_joint_tau(
        np.asarray(p_long, dtype=np.float64),
        np.asarray(p_short, dtype=np.float64),
        target_signal_rate=target_signal_rate,
    )


_COST_ATR_RATIO_FEATURE_ID = "E27f_cost_atr_ratio"


def _resolve_lambda_on_common_bars(
    train_bars: pl.DataFrame,
    long_result: SideModelResult,
    short_result: SideModelResult,
    *,
    feature_ids: tuple[str, ...],
    target_signal_rate: float,
    payoff_atr_mult: float,
) -> tuple[float, float]:
    """Ponto de entrada com IO-zero do modo `TAU_POLICY_COST_DERIVED_
    LAMBDA` (ADR-004 §4, medição opt-in — ver bloco de comentário acima
    de `implied_mu_from_prob`) — resolve `lambda_b` sobre a MESMA
    população que `_resolve_tau_on_common_bars` usa (população comum,
    fora do fit dos dois lados quando comportável — duplicado aqui em
    vez de fatorado, de propósito: este arquivo está sob edição
    concorrente ativa nesta mesma data por outra sessão, e um refactor
    da função existente é mais arriscado que ~15 linhas repetidas).

    `_COST_ATR_RATIO_FEATURE_ID` já é uma feature T1 (`E27f_cost_atr_
    ratio`) — sempre presente em `common` sem cálculo adicional."""
    common = _unique_test_bars(train_bars, feature_ids=feature_ids)
    if common.height == 0:
        raise ValueError(
            "_resolve_lambda_on_common_bars: nenhuma barra de treino com feature válida "
            "-- não há população sobre a qual resolver lambda_b"
        )
    fit_t0_long, fit_t0_short = long_result.fit_t0_ms, short_result.fit_t0_ms
    if fit_t0_long is None or fit_t0_short is None:
        raise ValueError(
            "_resolve_lambda_on_common_bars: fit_t0_ms ausente em pelo menos um lado -- "
            "exige a coluna 't0' no train_side_df dos dois lados (mesmo motivo de AG-210)"
        )
    t0_common = common["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    seen_in_fit = np.isin(t0_common, fit_t0_long) | np.isin(t0_common, fit_t0_short)
    oof_idx = np.flatnonzero(~seen_in_fit)

    min_bars = int(np.ceil(_MIN_OCCURRENCES_ABOVE_TAU / target_signal_rate))
    if oof_idx.shape[0] < min_bars:
        logger.warning(
            "models.alpha.lambda_oof_insuficiente_fallback_populacao_comum",
            n_oof=int(oof_idx.shape[0]),
            n_common=int(common.height),
            min_bars_required=min_bars,
            detail="população out-of-fit não comporta o quantil com ocorrências "
            "suficientes; lambda_b resolvido sobre a população comum INTEIRA",
        )
        lambda_frame = common
    else:
        lambda_frame = common[oof_idx]

    X_lambda = build_design_matrix(lambda_frame, feature_ids=feature_ids)
    p_long = long_result.calibrator.predict(
        np.asarray(long_result.model.predict_proba(X_lambda))[:, 1]
    )
    p_short = short_result.calibrator.predict(
        np.asarray(short_result.model.predict_proba(X_lambda))[:, 1]
    )
    cost_atr_ratio = lambda_frame[_COST_ATR_RATIO_FEATURE_ID].to_numpy().astype(np.float64)
    return resolve_joint_lambda(
        np.asarray(p_long, dtype=np.float64),
        np.asarray(p_short, dtype=np.float64),
        cost_atr_ratio,
        payoff_atr_mult=payoff_atr_mult,
        target_signal_rate=target_signal_rate,
    )


@dataclass(frozen=True, slots=True)
class CostDerivedLambdaDiagnostic:
    """Resultado da medição opt-in do ADR-004 §4 sobre UM fold — nunca
    realimenta `predictions`/`side_hat` de produção (ver bloco de
    comentário acima de `implied_mu_from_prob`: é medição, não novo
    default). `signal_rate_oos` sob a política cost-derived, ao lado de
    `signal_rate_oos_legacy` (a política ATIVA neste fold, qualquer que
    seja) — a comparação direta é o ponto inteiro da medição."""

    lambda_b: float
    payoff_atr_mult: float
    signal_rate_in_sample: float
    signal_rate_oos: float
    signal_rate_oos_legacy: float
    n_test_bars: int


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
    feature_ids: tuple[str, ...] = T1_FEATURE_IDS,
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
    device_type: str = "cpu",
    null_permutation_seed: int | None = None,
    tau_policy: str = TAU_POLICY_LEGACY_PER_SIDE,
    calib_split_mode: str = CALIB_SPLIT_LEGACY_RANDOM,
    class_balance_basis: str = CLASS_BALANCE_COUNT,
    calib_weight_basis: str = CALIB_WEIGHT_SAMPLE_WEIGHT,
    evaluate_cost_derived_lambda: bool = False,
    enforce_r2: bool = True,
) -> FoldResult:
    """`symbol`/`resolution_id` (D-03, `docs/alpha_model_design_doc_
    2026-08-22.md`) — colunas explícitas no schema de saída, mesma classe
    de risco já corrigida uma vez em `dataset.py:138-160` (features de um
    ativo casadas com label de outro), agora endereçada por construção em
    vez de convenção de nome/caminho. `symbol` é obrigatório (sem default
    -- sempre conhecido no call site real, `pipeline.run_layer1_sprint`).
    `resolution_id=None` (default) grava `"time_15m"` na coluna (grade de
    relógio legada), mesmo sentinela que `pipeline.py` já usa para `tf`/
    `resolution_id`.

    `feature_ids` (2026-08-24, `docs/t2_t1_promotion_ablation_design_doc_
    2026-08-24.md` §5.2) — default `T1_FEATURE_IDS` preserva bit-exato
    todo call site de produção; repassado sem alteração pros dois
    `fit_side_model` (treino) E pro filtro de warmup/`build_design_matrix`
    do lado de TESTE (`_unique_test_bars`/`X_test` abaixo) — os dois lados
    (treino/teste) têm que usar o MESMO vetor de features, senão o modelo
    treinado com k colunas recebe um `X_test` de shape errado na
    inferência.

    `null_permutation_seed` (2026-08-24, Fase 0b) — default `None`
    preserva produção bit-exato; repassado a `fit_side_model` (ver
    docstring de lá pro desenho completo), derivado por (`split.split_id`,
    `side`) via `_derived_seed` — permutação INDEPENDENTE por split E por
    lado a partir de um único seed base, nunca embaralhado antes do split
    (vazaria estrutura entre folds do CPCV, quebraria o purge).

    `enforce_r2` (achado real 2026-08-27, handoff de `src/models/`,
    `AG-296`/`AG-297`) -- repassado sem alteração pro `side_subset` do
    TREINO (`train_long`/`train_short` abaixo; o lado de TESTE não muda --
    filtrar R2 fora do treino não deveria alterar o que o modelo é
    avaliado contra). **[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27]**
    `False` reproduz o comportamento anterior. Ver docstring de `src.
    models.dataset.side_subset` pro que `True` faz.

    `regularization_basis`/`ic_magnitude_floor_k`/`early_stopping_mode`
    (2026-08-27, handoff de `src/models/`, item 1, `AG-324`/`AG-325`/
    `AG-326`) -- NÃO são parâmetros desta função. Vêm de `hyper.
    regularization_basis`/`hyper.ic_magnitude_floor_k`/`hyper.early_
    stopping_mode`, repassados pros dois `fit_side_model` abaixo -- `hyper`
    já atravessa `run_layer1_sprint` -> `run_all_folds` -> `run_fold`
    intacto, então os 3 chegam aqui de graça, sem precisar de mais um
    parâmetro nesta assinatura (mesmo padrão dos campos ESS, já em `hyper`
    há mais tempo). **[PROMOVIDOS A DEFAULT DE PRODUÇÃO 2026-08-27]** os
    defaults de `LGBMHyperparams` já não são mais os legados -- ver
    docstring da classe."""
    train_bars = df_all[split.train_idx]
    test_bars = df_all[split.test_idx]

    # AG-299 -- `feature_ids` explicito: o filtro de warmup precisa usar as
    # MESMAS colunas que o trial vai treinar. Antes era `T1_FEATURE_IDS`
    # hardcoded (7) enquanto `_unique_test_bars` (o lado de TESTE) ja
    # recebia o conjunto real -- treino e teste filtrados por criterios
    # diferentes, que e a assimetria de §13.2.
    train_long = ds.side_subset(train_bars, side=1, feature_ids=feature_ids, enforce_r2=enforce_r2)
    train_short = ds.side_subset(
        train_bars, side=-1, feature_ids=feature_ids, enforce_r2=enforce_r2
    )
    target_signal_rate = float(load_constant("target_signal_rate"))

    perm_seed_long = (
        _derived_seed(null_permutation_seed, split.split_id, 1)
        if null_permutation_seed is not None
        else None
    )
    perm_seed_short = (
        _derived_seed(null_permutation_seed, split.split_id, -1)
        if null_permutation_seed is not None
        else None
    )

    long_result = fit_side_model(
        train_long,
        side=1,
        variant=variant,
        hyper=hyper,
        seed=_derived_seed(seed, split.split_id),
        target_signal_rate=target_signal_rate,
        feature_ids=feature_ids,
        unforce_features_by_side=unforce_features_by_side,
        device_type=device_type,
        null_permutation_seed=perm_seed_long,
        calib_split_mode=calib_split_mode,
        class_balance_basis=class_balance_basis,
        calib_weight_basis=calib_weight_basis,
        regularization_basis=hyper.regularization_basis,
        ic_magnitude_floor_k=hyper.ic_magnitude_floor_k,
        early_stopping_mode=hyper.early_stopping_mode,
    )
    short_result = fit_side_model(
        train_short,
        side=-1,
        variant=variant,
        hyper=hyper,
        seed=_derived_seed(seed, split.split_id),
        target_signal_rate=target_signal_rate,
        feature_ids=feature_ids,
        unforce_features_by_side=unforce_features_by_side,
        device_type=device_type,
        null_permutation_seed=perm_seed_short,
        calib_split_mode=calib_split_mode,
        class_balance_basis=class_balance_basis,
        calib_weight_basis=calib_weight_basis,
        regularization_basis=hyper.regularization_basis,
        ic_magnitude_floor_k=hyper.ic_magnitude_floor_k,
        early_stopping_mode=hyper.early_stopping_mode,
    )

    # AG-210 -- resolução de `tau`. No caminho legado, cada lado usa o
    # `tau` que `fit_side_model` já computou (quantil `1 - r` da própria
    # sub-população daquele lado). No caminho corrigido, os dois `tau` são
    # resolvidos JUNTOS sobre a população COMUM de barras de treino -- a
    # mesma população que a inferência vai ver -- de forma que a taxa de
    # sinal TOTAL bata `target_signal_rate`. Ver `resolve_joint_tau`.
    tau_long, tau_short = long_result.tau, short_result.tau
    tau_realized_rate = float("nan")
    if tau_policy == TAU_POLICY_TOTAL_COMMON_OOF:
        tau_long, tau_short, tau_realized_rate = _resolve_tau_on_common_bars(
            train_bars,
            long_result,
            short_result,
            feature_ids=feature_ids,
            target_signal_rate=target_signal_rate,
        )
    elif tau_policy != TAU_POLICY_LEGACY_PER_SIDE:
        raise ValueError(
            f"run_fold: tau_policy desconhecido {tau_policy!r} (esperado "
            f"{TAU_POLICY_LEGACY_PER_SIDE!r} ou {TAU_POLICY_TOTAL_COMMON_OOF!r})"
        )

    test_bars_unique = _unique_test_bars(test_bars, feature_ids=feature_ids)
    X_test = build_design_matrix(test_bars_unique, feature_ids=feature_ids)

    raw_long = np.asarray(long_result.model.predict_proba(X_test))[:, 1]
    p_long = long_result.calibrator.predict(raw_long)
    raw_short = np.asarray(short_result.model.predict_proba(X_test))[:, 1]
    p_short = short_result.calibrator.predict(raw_short)

    # `decide_side` (AG-210) -- a MESMA função que `resolve_joint_tau` usa
    # internamente, nunca uma segunda cópia da regra. Bit-exato com o
    # bloco inline que existia aqui antes.
    side_hat = decide_side(p_long, p_short, tau_long=tau_long, tau_short=tau_short)
    confidence = np.maximum(p_long, p_short)

    # ADR-004 Fase 2 -- medição opt-in (`evaluate_cost_derived_lambda`),
    # NUNCA realimenta `side_hat`/`predictions` acima (produção segue
    # bit-exata sob a política ativa de `tau_policy`, qualquer que seja).
    cost_derived_lambda_diag: CostDerivedLambdaDiagnostic | None = None
    if evaluate_cost_derived_lambda:
        payoff_atr_mult = float(load_constant("tp_atr_mult"))
        lambda_b, lambda_realized_rate = _resolve_lambda_on_common_bars(
            train_bars,
            long_result,
            short_result,
            feature_ids=feature_ids,
            target_signal_rate=target_signal_rate,
            payoff_atr_mult=payoff_atr_mult,
        )
        cost_atr_ratio_test = (
            test_bars_unique[_COST_ATR_RATIO_FEATURE_ID].to_numpy().astype(np.float64)
        )
        side_hat_lambda = decide_side_cost_derived(
            p_long, p_short, cost_atr_ratio_test, payoff_atr_mult=payoff_atr_mult, lambda_b=lambda_b
        )
        cost_derived_lambda_diag = CostDerivedLambdaDiagnostic(
            lambda_b=lambda_b,
            payoff_atr_mult=payoff_atr_mult,
            signal_rate_in_sample=lambda_realized_rate,
            signal_rate_oos=(
                float(np.mean(side_hat_lambda != 0)) if side_hat_lambda.shape[0] else float("nan")
            ),
            signal_rate_oos_legacy=(
                float(np.mean(side_hat != 0)) if side_hat.shape[0] else float("nan")
            ),
            n_test_bars=int(side_hat.shape[0]),
        )
        logger.info(
            "models.alpha.run_fold_cost_derived_lambda_medido",
            split_id=split.split_id,
            **asdict(cost_derived_lambda_diag),
        )

    logger.info(
        "models.alpha.run_fold_tau_resolvido",
        split_id=split.split_id,
        tau_policy=tau_policy,
        tau_long=tau_long,
        tau_short=tau_short,
        target_signal_rate=target_signal_rate,
        # taxa in-sample da resolução conjunta (NaN no caminho legado --
        # não é medida lá, ver AG-210) e taxa OOS de fato realizada neste
        # fold: a segunda é diagnóstico, nunca realimenta a escolha (B20).
        signal_rate_in_sample=tau_realized_rate,
        signal_rate_oos=float(np.mean(side_hat != 0)) if side_hat.shape[0] else float("nan"),
    )

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
            # AG-210 -- os `tau` EFETIVAMENTE aplicados neste fold (iguais
            # a `long_result.tau`/`short_result.tau` sob a política legada;
            # resolvidos conjuntamente sob `TAU_POLICY_TOTAL_COMMON_OOF`).
            # Persistir o aplicado, não o per-side, é o que mantém
            # `predictions.parquet` autoexplicativo (D-05/AG-150).
            "tau_long": pl.Series([tau_long] * n_rows, dtype=pl.Float64),
            "tau_short": pl.Series([tau_short] * n_rows, dtype=pl.Float64),
            "score_long_raw": raw_long,
            "score_short_raw": raw_short,
            "side_hat": side_hat,
            "confidence": confidence,
            "ensemble_std": pl.Series([None] * n_rows, dtype=pl.Float64),
            "n_models_agree": pl.Series([1] * n_rows, dtype=pl.Int8),
            "model_id": pl.Series([model_id] * n_rows, dtype=pl.Utf8),
            "calibrator_id": pl.Series(calibrator_id),
            "feature_version": pl.Series([feature_version] * n_rows, dtype=pl.Utf8),
            "features_selecionadas": pl.Series([list(feature_ids)] * n_rows),
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
        cost_derived_lambda_diag=cost_derived_lambda_diag,
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
    feature_ids: tuple[str, ...] = T1_FEATURE_IDS,
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
    device_type: str = "cpu",
    null_permutation_seed: int | None = None,
    tau_policy: str = TAU_POLICY_LEGACY_PER_SIDE,
    calib_split_mode: str = CALIB_SPLIT_LEGACY_RANDOM,
    class_balance_basis: str = CLASS_BALANCE_COUNT,
    calib_weight_basis: str = CALIB_WEIGHT_SAMPLE_WEIGHT,
    evaluate_cost_derived_lambda: bool = False,
    enforce_r2: bool = True,
) -> list[FoldResult]:
    """`feature_ids` (2026-08-24, `docs/t2_t1_promotion_ablation_design_doc_
    2026-08-24.md` §5.2) — default `T1_FEATURE_IDS` preserva bit-exato
    todo call site de produção (`pipeline.run_layer1_sprint`); repassado
    sem alteração pra `run_fold` em cada split. Ponto de entrada real do
    harness de ablação T2→T1 (`src/validation/t2_t1_ablation.py`, ainda
    não implementado) pra treinar os 15 splits do CPCV sobre um vetor de
    k features candidatas em vez do T1 fixo.

    `null_permutation_seed` (2026-08-24, `docs/t2_t1_ablation_veredito_
    duas_analises_2026-08-24.md` §4, Fase 0b) — default `None` preserva
    produção bit-exato; repassado sem alteração pra `run_fold` em cada
    split, que deriva o seed real por (split, lado). Chamar esta função
    2× com o MESMO `null_permutation_seed` (uma vez `variant=
    VARIANT_CAMADA1`, outra `variant=VARIANT_CAMADA0`) produz a MESMA
    permutação nos dois braços — condição necessária pro nulo testar "as
    duas camadas são equivalentes", não "uma é lixo, a outra é real".

    `enforce_r2` (achado real 2026-08-27, handoff de `src/models/`,
    `AG-296`/`AG-297`) -- repassado sem alteração pra `run_fold` em cada
    split. **[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27]** `False`
    reproduz o comportamento anterior. Ver docstring de `src.models.
    dataset.side_subset` pro que `True` faz."""
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
            feature_ids=feature_ids,
            unforce_features_by_side=unforce_features_by_side,
            device_type=device_type,
            null_permutation_seed=null_permutation_seed,
            tau_policy=tau_policy,
            calib_split_mode=calib_split_mode,
            class_balance_basis=class_balance_basis,
            calib_weight_basis=calib_weight_basis,
            evaluate_cost_derived_lambda=evaluate_cost_derived_lambda,
            enforce_r2=enforce_r2,
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
