"""Camada 1 — restrições monotônicas por sinal medido (§5.3), triagem
in-fold. Para cada feature T1 (exceto as forçadas por identidade contábil,
não por padrão estatístico — ver `_ECONOMIC_FORCED_CONSTRAINT` e
`_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` abaixo), calcula o IC de Spearman
contra `ret_net` (o "retorno futuro" realizado daquele lado, já líquido de
custo — §3.4) dentro de cada um dos 6 ambientes de `src.models.environments`
(só treino do fold, nunca vazando — B02/B06).

Sinal dominante = sinal da MÉDIA dos ICs válidos (ambientes sem dado
suficiente contam como NaN, não como zero). Consistência = quantos dos 6
ambientes (denominador SEMPRE 6, não o subconjunto com dado — task
explícita) concordam em sinal com o dominante. Atribui a restrição só se
consistência >= `alpha_monotonic_consistency_min_envs` (constants.yaml —
ver a entrada para a investigação completa do "6 de 7" vs "6 de 6" do
§5.3/§5.4); senão, `0` (sem restrição).

**Restrições forçadas por identidade contábil** (não passam pelo teste de
consistência acima — o IC medido ainda é calculado e reportado em
`FeatureICResult` para transparência, mas não decide):

- `E27f_cost_atr_ratio` — custo alto nunca pode melhorar o resultado
  esperado, MESMO sinal (-1) nos dois lados (`_ECONOMIC_FORCED_CONSTRAINT`).
- Mecanismo `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` (sinal OPOSTO por lado,
  ex. funding rate: custo de carregamento pro long, receita pro short) —
  vazio hoje (`E02f_funding_z_expanding`, o único exemplo real, saiu do
  conjunto ativo de treino, `AG-032`, 2026-08-23), pronto pra qualquer
  feature futura com essa mesma assinatura contábil. `screen_monotone_
  constraints` recebe `side` explicitamente por causa deste mecanismo: a
  restrição forçada de uma feature side-dependent só pode ser resolvida
  sabendo de qual binário (M_long ou M_short) se trata."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
from scipy.stats import spearmanr

from ._constants import load_constant
from .environments import ENV_COL, ENVIRONMENTS, assign_environments

logger = structlog.get_logger(__name__)

# Feature com restrição -1 por ARGUMENTO ECONÔMICO direto (§5.3): custo alto
# não pode melhorar o resultado esperado — identidade contábil, não padrão
# aprendido. Não passa pelo teste de consistência (mas o IC medido ainda é
# reportado, só não decide). MESMO sinal nos dois lados — por isso um `int`
# simples basta aqui (contraste com `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE`
# logo abaixo, para features cuja identidade contábil inverte por lado).
_ECONOMIC_FORCED_CONSTRAINT: dict[str, int] = {"E27f_cost_atr_ratio": -1}

# Feature com restrição forçada por identidade contábil cujo SINAL depende
# do lado (§5.3): `{feature: {side: constraint}}`. Decisão de forma — dict
# duplo (este + `_ECONOMIC_FORCED_CONSTRAINT` acima) em vez de generalizar
# um único dict para `dict[str, int | dict[int, int]]`: cada dict fica
# homogêneo no seu próprio tipo (um é "constante nos dois lados", o outro é
# "por lado"), o que evita um `isinstance`/`match` por feature no ponto de
# leitura (`_forced_constraint_for` abaixo) só para descobrir qual forma
# aquela entrada tem. Custa uma segunda constante de módulo; ganha em
# legibilidade no call site — trade-off intencional, não descuido.
#
# `E02f_funding_z_expanding` (funding alto = custo de carregamento pro long,
# receita pro short) era a única entrada real deste dict -- saiu do conjunto
# ativo de treino (AG-032, 2026-08-23, `T1_FEATURE_IDS`). Vazio por ora, não
# removido -- mecanismo genérico (`_forced_constraint_for` abaixo), pronto
# pra qualquer feature FUTURA cuja identidade contábil inverta por lado
# (padrão comum em cripto: funding, basis, custo de carrego), sem precisar
# reintroduzir o dict duplo se/quando isso acontecer.
_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE: dict[str, dict[int, int]] = {}


def _forced_constraint_for(
    feature: str,
    *,
    side: int,
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
) -> int | None:
    """`None` se `feature` não tem restrição forçada por identidade
    contábil (nem constante-nos-dois-lados nem por-lado) — nesse caso
    `screen_monotone_constraints` cai para a triagem estatística normal.
    Caso contrário, devolve o inteiro da restrição já resolvido para o
    `side` pedido (`+1`/`-1`, mesma convenção de
    `src.models.dataset.side_subset`).

    `unforce_features_by_side` (Faixa 1.6, Bloco 4) — override EXPLÍCITO e
    ADITIVO, default `None` em toda a cadeia de chamada (`screen_monotone_
    constraints` -> `fit_side_model` -> `run_fold` -> `run_all_folds`), nunca
    passado por `src.models.pipeline.run_layer1_sprint` (o treino de
    produção de `alpha_c1_v1`/`alpha_c0_baseline_v1`): produção continua
    bit-a-bit idêntica. Só usado por
    `src.analysis.faixa1_6_reconciliation` para medir uma VARIANTE
    experimental (E02f sem restrição forçada num lado específico) sem
    mexer em `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` nem em nenhum outro
    ponto do desenho de produção."""
    if unforce_features_by_side is not None:
        unforced_sides = unforce_features_by_side.get(feature)
        if unforced_sides is not None and side in unforced_sides:
            return None
    if feature in _ECONOMIC_FORCED_CONSTRAINT:
        return _ECONOMIC_FORCED_CONSTRAINT[feature]
    by_side = _ECONOMIC_FORCED_CONSTRAINT_BY_SIDE.get(feature)
    return by_side[side] if by_side is not None else None


# Mínimo de observações válidas (não-NaN, variância > 0 nos dois lados) para
# calcular Spearman num ambiente — abaixo disso o IC daquele ambiente é NaN
# e não entra nem no sinal dominante nem na contagem de consistência. Não é
# constante de domínio (é o mínimo matemático para spearmanr não degenerar:
# < 3 pontos ou variância nula não produz correlação com sentido); mesma
# categoria de `valid_cost.len() < 3` em `environments.py`.
_MIN_OBS_PER_ENV = 5  # noqa: magic-number


@dataclass(frozen=True, slots=True)
class FeatureICResult:
    feature: str
    ic_by_env: dict[str, float]
    mean_ic: float
    n_consistent_envs: int
    n_envs_with_data: int
    constraint: int
    forced_economic: bool


def compute_ic_by_env(
    df_env: pl.DataFrame, feature_col: str, target_col: str = "ret_net"
) -> dict[str, float]:
    """`df_env` já precisa ter a coluna `env` (ver `assign_environments`).
    Retorna `{ambiente: IC de Spearman}` para os 6 ambientes fixos —
    `float("nan")` se o ambiente não tiver dado suficiente no fold."""
    out: dict[str, float] = {}
    for env in ENVIRONMENTS:
        sub = df_env.filter(pl.col(ENV_COL) == env)
        x = sub[feature_col].to_numpy().astype(np.float64)
        y = sub[target_col].to_numpy().astype(np.float64)
        mask = np.isfinite(x) & np.isfinite(y)
        n_valid = int(mask.sum())
        if n_valid < _MIN_OBS_PER_ENV or np.std(x[mask]) == 0.0 or np.std(y[mask]) == 0.0:
            out[env] = float("nan")
            continue
        rho, _p = spearmanr(x[mask], y[mask])
        out[env] = float(rho) if np.isfinite(rho) else float("nan")
    return out


def se_spearman_fisher(ess: float) -> float:
    """ADR-005 §13.14.2 (item 6 de §13.17) -- erro-padrão assintótico de
    Spearman via aproximação de Fisher, `SE(ρ) ≈ 1/sqrt(ESS − 3)`
    (padrão de livro-texto para o `z`-transform de uma correlação;
    mesma família de aproximação que `§13.16.3` já usa para `SE(p)` de
    uma proporção). `ESS` é `Σ uniqueness` do treino (AG-211, B24 --
    soma MEDIDA, não uma das fórmulas fechadas que B24 proíbe), não a
    contagem bruta de linhas.

    Levanta `ValueError` para `ESS <= 3` -- a aproximação é indefinida
    ali (raiz de número não-positivo), e devolver `inf`/`nan` em
    silêncio deixaria o piso de magnitude sempre passar ou sempre
    falhar sem que ninguém percebesse a causa."""
    if ess <= 3.0:  # noqa: magic-number -- limite matemático da aproximação (n-3), não constante de domínio
        raise ValueError(
            f"se_spearman_fisher: ess={ess} <= 3 -- aproximação de Fisher indefinida "
            "(1/sqrt(ess-3) exige ess > 3)"
        )
    return float(1.0 / math.sqrt(ess - 3.0))  # noqa: magic-number -- idem


def _assign_from_ic(
    ic_by_env: dict[str, float],
    *,
    min_consistent_envs: int,
    ic_magnitude_floor_k: float | None = None,
    ess: float | None = None,
) -> tuple[int, float, int, int]:
    valid = {e: v for e, v in ic_by_env.items() if not math.isnan(v)}
    n_envs_with_data = len(valid)
    if not valid:
        return 0, float("nan"), 0, n_envs_with_data

    mean_ic = float(sum(valid.values()) / len(valid))
    dominant = 1 if mean_ic > 0 else (-1 if mean_ic < 0 else 0)
    if dominant == 0:
        return 0, mean_ic, 0, n_envs_with_data

    n_consistent = sum(1 for v in valid.values() if (v > 0) == (dominant > 0))
    constraint = dominant if n_consistent >= min_consistent_envs else 0

    # ADR-005 §13.14.2 (item 6) -- piso de magnitude, ADICIONAL ao teste
    # de sinal+consistência acima, nunca no lugar dele: uma feature só
    # ganha restrição se as DUAS condições seguram. `ess is None` quando
    # `ic_magnitude_floor_k is None` (opt-in não pedido) -- núcleo puro,
    # a validação "pediu o piso sem ESS" é responsabilidade do CALLER
    # (`fit_side_model`), que é quem sabe se `uniqueness` existe.
    if constraint != 0 and ic_magnitude_floor_k is not None:
        if ess is None:
            raise ValueError(
                "_assign_from_ic: ic_magnitude_floor_k setado exige ess (Σ uniqueness) -- "
                "responsabilidade do caller (fit_side_model) resolver antes de chamar aqui"
            )
        se = se_spearman_fisher(ess)
        if abs(mean_ic) < ic_magnitude_floor_k * se:
            constraint = 0

    return constraint, mean_ic, n_consistent, n_envs_with_data


def screen_monotone_constraints(
    df_train_side: pl.DataFrame,
    feature_ids: tuple[str, ...],
    *,
    side: int,
    target_col: str = "ret_net",
    min_consistent_envs: int | None = None,
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
    ic_magnitude_floor_k: float | None = None,
    ess: float | None = None,
) -> dict[str, FeatureICResult]:
    """Núcleo da Camada 1 para UM lado, UM fold: `df_train_side` é o
    subconjunto de TREINO já filtrado por `src.models.dataset.side_subset`
    (NOFILL descartado, warmup descartado) — nunca o teste do fold, nunca o
    dataset inteiro. `side` (`+1`/`-1`, mesma convenção de `side_subset`) é
    obrigatório porque resolve o sinal das restrições forçadas por
    identidade contábil que DEPENDEM do lado (`E02f_funding_z_expanding` —
    ver `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE`); as constantes-nos-dois-lados
    (`E27f_cost_atr_ratio`) não precisam dele, mas o parâmetro é o mesmo
    para as duas categorias — quem chama não precisa saber qual feature é
    qual. Retorna `{feature_id: FeatureICResult}` para todas as
    `feature_ids`, incluindo as forçadas (IC medido sempre reportado para
    transparência, mesmo quando não decide a restrição).

    `unforce_features_by_side` — ver docstring de `_forced_constraint_for`;
    default `None` preserva o comportamento de produção exatamente.

    `ic_magnitude_floor_k`/`ess` (ADR-005 §13.14.2, item 6 de §13.17) --
    default `None` preserva o teste de sinal+consistência puro, bit-exato.
    Quando `ic_magnitude_floor_k` é setado, uma feature só mantém a
    restrição se ALÉM de consistente, `|mean_ic| >= k * SE(ess)`
    (`se_spearman_fisher`) -- `ess` vira obrigatório nesse caso (falha
    alto em `_assign_from_ic` se vier `None`). Restrições FORÇADAS por
    identidade contábil (`_forced_constraint_for`) nunca passam por este
    piso -- não passam pelo teste estatístico de jeito nenhum, forçado é
    forçado."""
    if side not in (1, -1):
        raise ValueError(f"screen_monotone_constraints: side deve ser 1 ou -1, recebido {side}")
    if min_consistent_envs is None:
        min_consistent_envs = int(load_constant("alpha_monotonic_consistency_min_envs"))

    df_env = assign_environments(df_train_side)

    results: dict[str, FeatureICResult] = {}
    for feature in feature_ids:
        ic_by_env = compute_ic_by_env(df_env, feature, target_col)
        forced_constraint = _forced_constraint_for(
            feature, side=side, unforce_features_by_side=unforce_features_by_side
        )
        forced = forced_constraint is not None
        constraint, mean_ic, n_consistent, n_with_data = _assign_from_ic(
            ic_by_env,
            min_consistent_envs=min_consistent_envs,
            ic_magnitude_floor_k=ic_magnitude_floor_k,
            ess=ess,
        )
        if forced_constraint is not None:
            constraint = forced_constraint
        results[feature] = FeatureICResult(
            feature=feature,
            ic_by_env=ic_by_env,
            mean_ic=mean_ic,
            n_consistent_envs=n_consistent,
            n_envs_with_data=n_with_data,
            constraint=constraint,
            forced_economic=forced,
        )

    logger.info(
        "models.monotonic.screen_monotone_constraints",
        n_rows_train=df_train_side.height,
        side=side,
        min_consistent_envs=min_consistent_envs,
        constraints={f: r.constraint for f, r in results.items()},
    )
    return results


# ============================================================================
# AG-213 — concordância entre os DOIS alvos do pipeline. Diagnóstico puro:
# não altera nenhuma restrição, não entra em nenhum caminho de treino.
# ============================================================================

_TP_TARGET_COL = "_y_tp_indicator"


@dataclass(frozen=True, slots=True)
class TargetAgreementResult:
    feature: str
    constraint_ret_net: int
    constraint_tp: int
    mean_ic_ret_net: float
    mean_ic_tp: float
    agree: bool
    forced_economic: bool


def screen_target_agreement(
    df_train_side: pl.DataFrame,
    feature_ids: tuple[str, ...],
    *,
    side: int,
    min_consistent_envs: int | None = None,
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
) -> dict[str, TargetAgreementResult]:
    """Mede se as restrições monotônicas da Camada 1 seriam AS MESMAS se
    derivadas do alvo que o modelo de fato treina.

    **Achado (`lgbm-crypto-quant`, 2026-08-25, `AG-213`) — dois alvos no
    mesmo pipeline.** `screen_monotone_constraints` mede IC de Spearman
    contra `ret_net` (contínuo, líquido de custo — `target_col` default).
    `src.models.alpha.fit_side_model` treina `y = 1 sse barrier_hit ==
    "TP"` — binário, com `SL` e `TIME` colapsando os dois em `y = 0`
    (`src.labels.triple_barrier._LABEL_BY_BARRIER = {"TP": 1, "TIME": 0,
    "SL": -1}`, e `y_all = (label == 1)`). A restrição `+1`/`-1` derivada
    da relação `feature -> ret_net` é então IMPOSTA sobre `feature ->
    P(TP)`.

    Mecanismo de falha concreto: uma feature que melhora `ret_net`
    sobretudo tornando os desfechos `TIME` menos ruins, sem mover P(TP),
    recebe restrição `+1` sobre P(TP) — uma forma que pode não existir,
    ou existir invertida. `monotone_constraints` é uma restrição DURA: se
    o sinal estiver errado, ela não degrada o modelo suavemente, ela
    proíbe a forma correta. E o critério de permanência do §5.11 (Camada 1
    vs Camada 0) passaria a medir o custo de uma restrição errada em vez
    do benefício de uma certa — `permanence_pass` deixaria de significar
    o que declara significar.

    Isto NÃO decide qual alvo é o certo (é decisão de desenho, do
    Manager): mede se a pergunta importa neste dataset. `agree=False` em
    qualquer feature não-forçada é o sinal de que importa.

    Features com restrição forçada por identidade contábil
    (`_ECONOMIC_FORCED_CONSTRAINT`) aparecem com `forced_economic=True` e
    `agree=True` por construção — a restrição delas não vem de IC nenhum,
    então a linha não informa nada sobre concordância e não deve ser
    contada como evidência a favor."""
    if _TP_TARGET_COL in df_train_side.columns:
        raise ValueError(
            f"screen_target_agreement: coluna reservada {_TP_TARGET_COL!r} já existe "
            "em df_train_side -- renomeie antes de chamar"
        )
    df_with_tp = df_train_side.with_columns(
        (pl.col("label").cast(pl.Int64) == 1).cast(pl.Float64).alias(_TP_TARGET_COL)
    )

    by_ret_net = screen_monotone_constraints(
        df_train_side,
        feature_ids,
        side=side,
        target_col="ret_net",
        min_consistent_envs=min_consistent_envs,
        unforce_features_by_side=unforce_features_by_side,
    )
    by_tp = screen_monotone_constraints(
        df_with_tp,
        feature_ids,
        side=side,
        target_col=_TP_TARGET_COL,
        min_consistent_envs=min_consistent_envs,
        unforce_features_by_side=unforce_features_by_side,
    )

    out: dict[str, TargetAgreementResult] = {}
    for feature in feature_ids:
        a, b = by_ret_net[feature], by_tp[feature]
        out[feature] = TargetAgreementResult(
            feature=feature,
            constraint_ret_net=a.constraint,
            constraint_tp=b.constraint,
            mean_ic_ret_net=a.mean_ic,
            mean_ic_tp=b.mean_ic,
            agree=a.constraint == b.constraint,
            forced_economic=a.forced_economic,
        )

    n_disagree = sum(1 for r in out.values() if not r.agree and not r.forced_economic)
    logger.info(
        "models.monotonic.screen_target_agreement",
        side=side,
        n_rows_train=df_train_side.height,
        n_features=len(feature_ids),
        n_disagree_nao_forcadas=n_disagree,
        detail="AG-213 -- IC medido contra ret_net vs contra indicador de TP",
    )
    return out
