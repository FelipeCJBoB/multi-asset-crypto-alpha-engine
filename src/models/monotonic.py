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
- `E02f_funding_z_expanding` — funding rate alto (z positivo) é custo de
  carregamento para quem está COMPRADO (paga funding -> prejudica o long,
  -1) e é receita para quem está VENDIDO (recebe funding -> favorece o
  short, +1) — sinal OPOSTO por lado (`_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE`).
  Por isso `screen_monotone_constraints` agora recebe `side` explicitamente:
  a restrição forçada de uma feature side-dependent só pode ser resolvida
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
# `E02f_funding_z_expanding`: funding alto (z positivo) é custo de
# carregamento para quem está COMPRADO (paga funding — prejudica o long,
# -1) e é receita para quem está VENDIDO (recebe funding — favorece o
# short, +1). Mesma categoria de `E27f_cost_atr_ratio` (aritmética de custo,
# não padrão a aprender/testar por consistência de IC) — só que aqui a
# identidade contábil inverte de sinal conforme o lado.
_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE: dict[str, dict[int, int]] = {
    "E02f_funding_z_expanding": {1: -1, -1: 1},
}


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


def _assign_from_ic(
    ic_by_env: dict[str, float], *, min_consistent_envs: int
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
    return constraint, mean_ic, n_consistent, n_envs_with_data


def screen_monotone_constraints(
    df_train_side: pl.DataFrame,
    feature_ids: tuple[str, ...],
    *,
    side: int,
    target_col: str = "ret_net",
    min_consistent_envs: int | None = None,
    unforce_features_by_side: dict[str, frozenset[int]] | None = None,
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
    default `None` preserva o comportamento de produção exatamente."""
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
            ic_by_env, min_consistent_envs=min_consistent_envs
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
