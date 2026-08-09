"""Camada 2 — triagem de estabilidade entre ambientes, in-fold (§5.4):

    estabilidade[f] = forca[f] * consistencia[f]**2

Reusa `src.models.environments` (6 ambientes = RANGE/TREND x tercil de
`E27f_cost_atr_ratio`, já resolvido/testado para §5.3) e
`src.models.monotonic.compute_ic_by_env` (mesmo IC de Spearman por
ambiente que a triagem de restrições monotônicas já calcula — método
igual, pergunta diferente: §5.3 decide SINAL de uma restrição; §5.4
decide se a feature sobrevive à triagem).

**`forca`/`consistencia` usam denominador FIXO 6** (não o subconjunto de
ambientes com dado suficiente) — mesma convenção já investigada e
resolvida em `monotonic.py` para `alpha_monotonic_consistency_min_envs`
("6 de 6", ver `config/constants.yaml`), estendida aqui aos dois termos
por simetria: um ambiente sem dado não deve inflar `forca` (não é "IC
forte", é "sem medição") nem `consistencia` (não é "concorda", é "não
vota"). Sem essa convenção, uma feature medida em só 2 dos 6 ambientes
com IC alto nesses dois poderia parecer mais estável que uma medida nos
6 com IC moderado — o oposto do que "estabilidade ENTRE ambientes" quer
dizer.

**`rpi_regime` (PRE/POST, §2.7.1) NÃO entra nesta fórmula** — decisão do
Manager (2026-08-09), revertendo a leitura literal "cruzando as seis
células acima" do PRD v3.3: a dimensão foi desenhada para capturar
features do Grupo F (microestrutura, `bookTicker`/`bookDepth`), cuja
definição quebrou em 2025-11-20; o Grupo F saiu de T1 na v3.3 (§2.7.1) e
nenhuma das 10 candidatas do E2 é microestrutura — a dimensão perdeu o
alvo. Cruzar mesmo assim fragmentaria os ~8,5 meses de POST em fatias
pequenas demais para Spearman estável, e o alcance combinado com
`alpha_monotonic_consistency_min_envs` já exigir 6/6 (unanimidade, P sob
ruído = 3,125%) tornaria 12 células (P sob ruído = 0,049%, 64x mais
restritivo) uma barra que praticamente nenhuma feature real passaria —
ver `docs/SPRINT_LOG.md`, seção "Ambientes do E3" para o cálculo
completo. `ic_by_rpi_regime` abaixo cobre o objetivo original (achar
feature cuja definição mudou no meio da amostra) como DIAGNÓSTICO de
relatório, fora da fórmula de estabilidade."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy.stats import spearmanr

from ._constants import load_constant
from .environments import ENVIRONMENTS, assign_environments
from .monotonic import compute_ic_by_env

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_N_ENVS = len(ENVIRONMENTS)  # denominador FIXO da formula -- ver docstring do modulo


@dataclass(frozen=True, slots=True)
class FeatureStabilityResult:
    feature: str
    ic_by_env: dict[str, float]
    n_envs_with_data: int
    forca: float
    consistencia: float
    estabilidade: float
    survives: bool


def _score_from_ic(ic_by_env: dict[str, float]) -> tuple[float, float, float, int]:
    valid = {e: v for e, v in ic_by_env.items() if not math.isnan(v)}
    n_with_data = len(valid)
    if not valid:
        return 0.0, 0.0, 0.0, 0
    mean_ic = sum(valid.values()) / len(valid)
    dominant = 1 if mean_ic > 0 else (-1 if mean_ic < 0 else 0)
    if dominant == 0:
        return 0.0, 0.0, 0.0, n_with_data
    n_consistent = sum(1 for v in valid.values() if (v > 0) == (dominant > 0))
    consistencia = n_consistent / _N_ENVS
    forca = sum(abs(v) for v in valid.values()) / _N_ENVS
    estabilidade = forca * consistencia**2
    return forca, consistencia, estabilidade, n_with_data


def stability_screen(
    df_train_side: pl.DataFrame,
    feature_ids: tuple[str, ...],
    *,
    target_col: str = "ret_net",
    limiar: float | None = None,
) -> dict[str, FeatureStabilityResult]:
    """`df_train_side` já filtrado por `src.models.dataset.side_subset`
    (NOFILL fora, warmup fora) — nunca o teste do fold, nunca o dataset
    inteiro (mesma disciplina de `monotonic.screen_monotone_
    constraints`). `limiar` -- constante classe A
    (`alpha_stability_screen_limiar`, `config/constants.yaml`), varrida
    antes do Gate 3, não escolhida nesta chamada."""
    if limiar is None:
        limiar = float(load_constant("alpha_stability_screen_limiar"))
    df_env = assign_environments(df_train_side)

    results: dict[str, FeatureStabilityResult] = {}
    for feature in feature_ids:
        ic_by_env = compute_ic_by_env(df_env, feature, target_col)
        forca, consistencia, estabilidade, n_with_data = _score_from_ic(ic_by_env)
        results[feature] = FeatureStabilityResult(
            feature=feature,
            ic_by_env=ic_by_env,
            n_envs_with_data=n_with_data,
            forca=forca,
            consistencia=consistencia,
            estabilidade=estabilidade,
            survives=estabilidade >= limiar,
        )

    logger.info(
        "models.stability.stability_screen",
        n_rows_train=df_train_side.height,
        limiar=limiar,
        survives={f: r.survives for f, r in results.items()},
    )
    return results


# Minimo de observacoes validas por perna (PRE ou POST) para Spearman nao
# degenerar -- mesmo criterio/mesmo valor de `monotonic._MIN_OBS_PER_ENV`
# (< 3 pontos ou variancia nula nao produz correlacao com sentido; 5 da
# folga sem custar amostra real).
_MIN_OBS_PER_LEG = 5  # noqa: magic-number
# Data do evento §2.7.1 (quebra de definicao do Grupo F), nao hiperparametro.
# `np.datetime64` (nao um literal polars) de proposito -- compara contra
# `t0.to_numpy()` sem depender da unidade/timezone exata que o dtype
# polars de `t0` carrega em cada chamador (`Datetime("ms","UTC")` em
# producao, mas o contrato desta funcao nao deveria travar nisso).
_RPI_BREAK_NP: np.datetime64 = np.datetime64("2025-11-20")  # noqa: magic-number
RPI_REGIMES: tuple[str, ...] = ("PRE", "POST")


def _spearman_or_nan(x: FloatArray, y: FloatArray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < _MIN_OBS_PER_LEG or np.std(x[mask]) == 0.0 or np.std(y[mask]) == 0.0:
        return float("nan")
    rho, _p = spearmanr(x[mask], y[mask])
    return float(rho) if np.isfinite(rho) else float("nan")


def ic_by_rpi_regime(
    df_train_side: pl.DataFrame,
    feature_ids: tuple[str, ...],
    *,
    target_col: str = "ret_net",
    t0_col: str = "t0",
) -> dict[str, dict[str, float]]:
    """Diagnóstico PRE/POST (`rpi_regime`, §2.7.1) — NÃO entra em
    `stability_screen` (ver docstring do módulo). Retorna
    `{feature: {"PRE": ic, "POST": ic}}`. Comparação de data feita em
    numpy (`to_numpy()`), não em expressão polars — evita casar
    timezone/unidade do dtype de `t0_col` (varia entre chamadores)."""
    t0_np = df_train_side[t0_col].to_numpy()
    is_pre = t0_np < _RPI_BREAK_NP

    out: dict[str, dict[str, float]] = {}
    for feature in feature_ids:
        x_all = df_train_side[feature].to_numpy().astype(np.float64)
        y_all = df_train_side[target_col].to_numpy().astype(np.float64)
        out[feature] = {
            "PRE": _spearman_or_nan(x_all[is_pre], y_all[is_pre]),
            "POST": _spearman_or_nan(x_all[~is_pre], y_all[~is_pre]),
        }
    return out
