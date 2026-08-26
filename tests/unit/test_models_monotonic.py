"""Testes de `src/models/monotonic.py` — Camada 1, IC de Spearman in-fold
por ambiente e atribuição de `monotone_constraints` (§5.3)."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.models import monotonic
from src.models.environments import ENVIRONMENTS


def _synthetic_df(*, feature_sign: int, n_envs_consistent: int, n_per_env: int = 40) -> pl.DataFrame:
    """Monta um frame com as 6 células de ambiente já povoadas e uma
    feature (`feat`) cujo IC contra `ret_net` tem sinal `feature_sign` em
    exatamente `n_envs_consistent` das 6 células (as demais têm sinal
    oposto) — controle direto sobre o resultado esperado da triagem."""
    rng = np.random.default_rng(0)
    rows: list[pl.DataFrame] = []
    for i, env in enumerate(ENVIRONMENTS):
        sign = feature_sign if i < n_envs_consistent else -feature_sign
        x = rng.normal(size=n_per_env)
        noise = rng.normal(scale=0.01, size=n_per_env)
        y = sign * x + noise  # ret_net cresce/decresce com x conforme `sign`
        rows.append(
            pl.DataFrame(
                {
                    "env": [env] * n_per_env,
                    "feat": x,
                    "ret_net": y,
                }
            )
        )
    return pl.concat(rows, how="vertical")


def test_compute_ic_by_env_sinal_correto() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=6)
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    assert set(ic.keys()) == set(ENVIRONMENTS)
    assert all(v > 0 for v in ic.values())


def test_compute_ic_by_env_ambiente_sem_dado_vira_nan() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=6).filter(pl.col("env") != ENVIRONMENTS[0])
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    assert np.isnan(ic[ENVIRONMENTS[0]])


def test_assign_constraint_consistente_em_6_de_6() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=6)
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    constraint, mean_ic, n_consistent, n_with_data = monotonic._assign_from_ic(
        ic, min_consistent_envs=6
    )
    assert constraint == 1
    assert n_consistent == 6
    assert n_with_data == 6


def test_assign_constraint_5_de_6_nao_passa_no_limiar_6() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=5)
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    constraint, _mean_ic, n_consistent, _n = monotonic._assign_from_ic(ic, min_consistent_envs=6)
    assert n_consistent == 5
    assert constraint == 0  # limiar de 6 exige unanimidade


def test_assign_constraint_5_de_6_passa_no_limiar_5() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=5)
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    constraint, _mean_ic, n_consistent, _n = monotonic._assign_from_ic(ic, min_consistent_envs=5)
    assert n_consistent == 5
    assert constraint == 1


def _synthetic_screen_df(
    feature_col: str, *, feature_sign: int = 1, n_envs_consistent: int = 6,
    n_per_env: int = 40, seed: int = 1,
) -> pl.DataFrame:
    """Frame COMPLETO (`regime` + `E27f_cost_atr_ratio` + `feature_col` +
    `ret_net`) que passa pelo `assign_environments` de verdade (não um
    `env` pré-calculado) — necessário para os testes de
    `screen_monotone_constraints`, que chama `assign_environments`
    internamente. Os valores de `E27f_cost_atr_ratio` ficam em 3 grupos bem
    separados (~10/~50/~90) para que o corte de tercil global caia sempre
    entre os grupos, e a ordem dos 6 blocos bate exatamente com
    `environments.ENVIRONMENTS` (RANGE via R1, depois TREND via R3, cada um
    LOW/MID/HIGH nessa ordem) — os primeiros `n_envs_consistent` blocos têm
    IC(feature_col, ret_net) com sinal `feature_sign`; o resto, sinal
    oposto."""
    rng = np.random.default_rng(seed)
    cost_reps = (10.0, 50.0, 90.0)  # noqa: magic-number
    blocks: list[pl.DataFrame] = []
    env_i = 0
    for regime in ("R1", "R3"):
        for cost_val in cost_reps:
            sign = feature_sign if env_i < n_envs_consistent else -feature_sign
            x = rng.normal(size=n_per_env)
            y = sign * x + rng.normal(scale=0.01, size=n_per_env)  # noqa: magic-number
            cost_series = cost_val + rng.normal(scale=0.5, size=n_per_env)  # noqa: magic-number
            data: dict[str, object] = {
                "regime": [regime] * n_per_env,
                "E27f_cost_atr_ratio": cost_series,
                "ret_net": y,
            }
            if feature_col != "E27f_cost_atr_ratio":
                data[feature_col] = x
            blocks.append(pl.DataFrame(data))
            env_i += 1
    return pl.concat(blocks, how="vertical")


def test_screen_monotone_constraints_e27f_forcado_menos_1_mesmo_sem_sinal() -> None:
    """`E27f_cost_atr_ratio` recebe -1 por argumento econômico (§5.3),
    independente do IC medido — construído aqui SEM controle de sinal
    (n_envs_consistent=0, todo mundo "inconsistente") e o resultado ainda
    é -1."""
    df = _synthetic_screen_df("E27f_cost_atr_ratio", n_envs_consistent=0)
    results = monotonic.screen_monotone_constraints(
        df, ("E27f_cost_atr_ratio",), side=1, min_consistent_envs=6
    )
    assert results["E27f_cost_atr_ratio"].constraint == -1
    assert results["E27f_cost_atr_ratio"].forced_economic is True


def test_screen_monotone_constraints_e27f_forcado_menos_1_no_short_tambem() -> None:
    """`E27f_cost_atr_ratio` é MESMO sinal nos dois lados (§5.3) — -1
    independente de `side`, ao contrário do mecanismo side-dependent
    (ver testes dedicados abaixo, `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE`)."""
    df = _synthetic_screen_df("E27f_cost_atr_ratio", n_envs_consistent=0)
    results = monotonic.screen_monotone_constraints(
        df, ("E27f_cost_atr_ratio",), side=-1, min_consistent_envs=6
    )
    assert results["E27f_cost_atr_ratio"].constraint == -1
    assert results["E27f_cost_atr_ratio"].forced_economic is True


# ============================================================================
# _ECONOMIC_FORCED_CONSTRAINT_BY_SIDE -- mecanismo genérico (feature com
# identidade contábil de sinal OPOSTO por lado). `E02f_funding_z_expanding`
# era o único exemplo real (funding: custo pro long, receita pro short) --
# saiu do conjunto ativo de treino (AG-032, 2026-08-23), dict vazio hoje em
# `monotonic.py`. Testes abaixo usam um nome de feature SINTÉTICO,
# injetado via `monkeypatch` diretamente no dict do módulo -- testam o
# MECANISMO (side-dependent forcing funciona corretamente), não uma
# instância específica que pode não existir mais no conjunto ativo real.
# ============================================================================

_SYNTH_SIDE_FEATURE = "SYNTH_side_dependent_cost"


def test_screen_monotone_constraints_side_dependente_forcado_no_long(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identidade contábil de sinal OPOSTO por lado (mesma categoria de
    `E27f_cost_atr_ratio`, mas o sinal inverte por `side`). Construído aqui
    SEM controle de sinal (n_envs_consistent=0, todo mundo "inconsistente"
    do ponto de vista estatístico) — a restrição forçada -1 no long
    prevalece mesmo assim."""
    monkeypatch.setattr(
        monotonic, "_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE", {_SYNTH_SIDE_FEATURE: {1: -1, -1: 1}}
    )
    df = _synthetic_screen_df(_SYNTH_SIDE_FEATURE, n_envs_consistent=0)
    results = monotonic.screen_monotone_constraints(
        df, (_SYNTH_SIDE_FEATURE,), side=1, min_consistent_envs=6
    )
    assert results[_SYNTH_SIDE_FEATURE].constraint == -1
    assert results[_SYNTH_SIDE_FEATURE].forced_economic is True


def test_screen_monotone_constraints_side_dependente_forcado_no_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mesma identidade contábil do teste acima, lado oposto: restrição
    forçada +1 no short, também independente do IC medido nos dados
    sintéticos (sem sinal controlado)."""
    monkeypatch.setattr(
        monotonic, "_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE", {_SYNTH_SIDE_FEATURE: {1: -1, -1: 1}}
    )
    df = _synthetic_screen_df(_SYNTH_SIDE_FEATURE, n_envs_consistent=0)
    results = monotonic.screen_monotone_constraints(
        df, (_SYNTH_SIDE_FEATURE,), side=-1, min_consistent_envs=6
    )
    assert results[_SYNTH_SIDE_FEATURE].constraint == 1
    assert results[_SYNTH_SIDE_FEATURE].forced_economic is True


def test_unforce_features_by_side_libera_so_o_lado_pedido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Faixa 1.6, Bloco 4 — `unforce_features_by_side` remove a restrição
    forçada SÓ no lado passado; a triagem estatística normal decide.
    `n_envs_consistent=3` (3 de 6 blocos com sinal oposto) — diferente de
    `n_envs_consistent=0` (que dá sinal UNÂNIME nos 6 blocos, só invertido,
    e portanto constraint estatístico igual ao forçado por coincidência),
    aqui a consistência não bate >= 6 e a triagem estatística cai em
    `constraint=0` — o único jeito de discriminar "caiu pra estatística" de
    "o forçado ainda valia de qualquer jeito". O long, fora do override,
    continua forçado -1 — exatamente a garantia que o Bloco 4 precisa
    (variante experimental isolada por lado, produção intocada)."""
    monkeypatch.setattr(
        monotonic, "_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE", {_SYNTH_SIDE_FEATURE: {1: -1, -1: 1}}
    )
    df = _synthetic_screen_df(_SYNTH_SIDE_FEATURE, n_envs_consistent=3)
    unforce = {_SYNTH_SIDE_FEATURE: frozenset({-1})}

    short_results = monotonic.screen_monotone_constraints(
        df, (_SYNTH_SIDE_FEATURE,), side=-1, min_consistent_envs=6,
        unforce_features_by_side=unforce,
    )
    assert short_results[_SYNTH_SIDE_FEATURE].constraint == 0
    assert short_results[_SYNTH_SIDE_FEATURE].forced_economic is False

    long_results = monotonic.screen_monotone_constraints(
        df, (_SYNTH_SIDE_FEATURE,), side=1, min_consistent_envs=6,
        unforce_features_by_side=unforce,
    )
    assert long_results[_SYNTH_SIDE_FEATURE].constraint == -1
    assert long_results[_SYNTH_SIDE_FEATURE].forced_economic is True


def test_unforce_features_by_side_default_none_preserva_producao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default `None` -- comportamento idêntico a antes do parâmetro
    existir (regressão contra o Bloco 4 mudar produção por acidente)."""
    monkeypatch.setattr(
        monotonic, "_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE", {_SYNTH_SIDE_FEATURE: {1: -1, -1: 1}}
    )
    df = _synthetic_screen_df(_SYNTH_SIDE_FEATURE, n_envs_consistent=0)
    with_default = monotonic.screen_monotone_constraints(
        df, (_SYNTH_SIDE_FEATURE,), side=-1, min_consistent_envs=6
    )
    with_explicit_none = monotonic.screen_monotone_constraints(
        df, (_SYNTH_SIDE_FEATURE,), side=-1, min_consistent_envs=6,
        unforce_features_by_side=None,
    )
    assert with_default[_SYNTH_SIDE_FEATURE].constraint == 1
    assert with_default[_SYNTH_SIDE_FEATURE].forced_economic is True
    assert (
        with_explicit_none[_SYNTH_SIDE_FEATURE].constraint
        == with_default[_SYNTH_SIDE_FEATURE].constraint
    )


def test_screen_monotone_constraints_side_invalido_leva_a_value_error() -> None:
    df = _synthetic_screen_df("B01_rsi_14", n_envs_consistent=6)
    with pytest.raises(ValueError, match="side"):
        monotonic.screen_monotone_constraints(df, ("B01_rsi_14",), side=0, min_consistent_envs=6)


def test_screen_monotone_constraints_le_limiar_de_constants_yaml_por_padrao() -> None:
    """Sem `min_consistent_envs` explícito, lê `alpha_monotonic_consistency_
    min_envs` de `constants.yaml` (valor atual: 6, ver a entrada para a
    investigação completa do '6 de 7' vs '6 de 6')."""
    df = _synthetic_screen_df("B01_rsi_14", feature_sign=-1, n_envs_consistent=6)
    results = monotonic.screen_monotone_constraints(df, ("B01_rsi_14",), side=1)
    assert results["B01_rsi_14"].constraint == -1


def test_min_obs_por_ambiente_insuficiente_vira_nan() -> None:
    tiny = pl.DataFrame(
        {"env": [ENVIRONMENTS[0]] * 2, "feat": [0.1, 0.2], "ret_net": [0.01, 0.02]}
    )
    ic = monotonic.compute_ic_by_env(tiny, "feat", "ret_net")
    assert np.isnan(ic[ENVIRONMENTS[0]])


# ============================================================================
# se_spearman_fisher / piso de magnitude (ic_magnitude_floor_k) --
# ADR-005 §13.14.2, item 6 de §13.17
# ============================================================================


def test_se_spearman_fisher_formula_fechada() -> None:
    # SE = 1/sqrt(ess-3) -- valor calculado à mão, não só reproduzido.
    assert monotonic.se_spearman_fisher(103.0) == pytest.approx(0.1, abs=1e-9)  # noqa: magic-number


def test_se_spearman_fisher_ess_pequeno_leva_a_value_error() -> None:
    with pytest.raises(ValueError, match="ess"):
        monotonic.se_spearman_fisher(3.0)  # noqa: magic-number
    with pytest.raises(ValueError, match="ess"):
        monotonic.se_spearman_fisher(1.0)


def test_assign_from_ic_sem_floor_preserva_comportamento_legado() -> None:
    """`ic_magnitude_floor_k=None` (default) -- comportamento idêntico a
    antes do parâmetro existir, mesmo com `ess` minúsculo (que faria o
    piso zerar tudo se estivesse ativo)."""
    df = _synthetic_df(feature_sign=1, n_envs_consistent=6)  # noqa: magic-number
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    constraint, _mean_ic, _n_consistent, _n = monotonic._assign_from_ic(
        ic, min_consistent_envs=6, ic_magnitude_floor_k=None, ess=4.0  # noqa: magic-number
    )
    assert constraint == 1


def test_assign_from_ic_floor_zera_constraint_consistente_mas_fraco() -> None:
    """Sinal fraco (ret_net quase todo ruído, IC baixo) mas ainda
    consistente nos 6 ambientes -- passa no teste de sinal+consistência,
    mas `ess` baixo (SE grande) faz o piso de magnitude zerar."""
    rng = np.random.default_rng(3)  # noqa: magic-number
    rows: list[pl.DataFrame] = []
    for env in ENVIRONMENTS:
        x = rng.normal(size=200)  # noqa: magic-number
        y = 0.001 * x + rng.normal(scale=1.0, size=200)  # noqa: magic-number -- IC fraco de propósito
        rows.append(pl.DataFrame({"env": [env] * 200, "feat": x, "ret_net": y}))  # noqa: magic-number
    df = pl.concat(rows, how="vertical")
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")

    sem_floor, mean_ic, n_consistent, _n = monotonic._assign_from_ic(ic, min_consistent_envs=1)
    assert n_consistent >= 1  # ao menos consistente o bastante pra passar sem piso
    assert sem_floor != 0  # confirma que É a consistência que passa, sozinha

    com_floor, _mean_ic2, _n_consistent2, _n2 = monotonic._assign_from_ic(
        ic, min_consistent_envs=1, ic_magnitude_floor_k=2.0, ess=4.0  # noqa: magic-number
    )
    assert abs(mean_ic) < 2.0 * monotonic.se_spearman_fisher(4.0)  # noqa: magic-number -- confirma a premissa
    assert com_floor == 0  # o piso, não a consistência, é quem derruba aqui


def test_assign_from_ic_floor_nao_zera_sinal_forte_com_ess_grande() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=6)  # noqa: magic-number
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    constraint, _mean_ic, _n, _nw = monotonic._assign_from_ic(
        ic, min_consistent_envs=6, ic_magnitude_floor_k=2.0, ess=100_000.0  # noqa: magic-number
    )
    assert constraint == 1


def test_assign_from_ic_floor_sem_ess_levanta_value_error() -> None:
    df = _synthetic_df(feature_sign=1, n_envs_consistent=6)  # noqa: magic-number
    ic = monotonic.compute_ic_by_env(df, "feat", "ret_net")
    with pytest.raises(ValueError, match="ess"):
        monotonic._assign_from_ic(ic, min_consistent_envs=6, ic_magnitude_floor_k=2.0, ess=None)  # noqa: magic-number


def test_screen_monotone_constraints_floor_default_none_preserva_producao() -> None:
    df = _synthetic_screen_df("B01_rsi_14", feature_sign=1, n_envs_consistent=6)  # noqa: magic-number
    results = monotonic.screen_monotone_constraints(
        df, ("B01_rsi_14",), side=1, min_consistent_envs=6  # noqa: magic-number
    )
    assert results["B01_rsi_14"].constraint == 1


def test_screen_monotone_constraints_forcado_ignora_o_piso_de_magnitude() -> None:
    """Restrição forçada por identidade contábil (`E27f_cost_atr_ratio`)
    nunca passa pelo teste estatístico -- inclusive o piso novo. `ess`
    minúsculo (zeraria qualquer constraint estatístico) não muda o -1
    forçado."""
    df = _synthetic_screen_df("E27f_cost_atr_ratio", n_envs_consistent=0)
    results = monotonic.screen_monotone_constraints(
        df, ("E27f_cost_atr_ratio",), side=1, min_consistent_envs=6,  # noqa: magic-number
        ic_magnitude_floor_k=2.0, ess=4.0,  # noqa: magic-number
    )
    assert results["E27f_cost_atr_ratio"].constraint == -1
    assert results["E27f_cost_atr_ratio"].forced_economic is True
