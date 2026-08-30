"""Testes do cache de triagem monotônica pré-computado (AG-380, achado
real via `cProfile`, 2026-08-29 -- ~0,56s/chamada de `screen_monotone_
constraints`, ~39% do custo de um trial completo do Optuna, recomputado
sem necessidade porque `ic_magnitude_floor_k` nunca é buscado).

Propriedade central testada: `monotone_screen_override` (`fit_side_
model`) e `monotone_screen_override_by_split_side` (`run_all_folds`) tem
que produzir resultado BIT-IDÊNTICO ao caminho sem override, quando o
override é exatamente o que `compute_monotone_screen` computaria de
qualquer forma -- é otimização de custo, nunca mudança de semântica."""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import polars as pl
import pytest

from src.features.build import T1_FEATURE_IDS
from src.models import alpha
from src.models import dataset as ds
from src.validation.cpcv import CPCVSplit


def _frame_com_t0_t1_uniqueness(n: int = 200, *, seed: int = 11) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    t0 = pl.Series(list(range(n))).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    t1 = (
        pl.Series([i + 1 for i in range(n)])
        .cast(pl.Datetime("ms"))
        .dt.replace_time_zone("UTC")
    )
    cols: dict[str, object] = {
        "t0": t0,
        "t1": t1,
        "regime": pl.Series(rng.choice(["R1", "R2", "R3", "R4", "R5"], size=n)),
        "label": pl.Series(rng.choice([1, 0], size=n)).cast(pl.Int8),
        "ret_net": pl.Series(rng.normal(scale=0.01, size=n)),
        "sample_weight": pl.Series(np.abs(rng.normal(loc=1.0, scale=0.1, size=n))),
        "uniqueness": pl.Series(rng.uniform(0.2, 1.0, size=n)),  # noqa: magic-number
        # `side`/`barrier_hit` -- só usados por `ds.side_subset` (teste de
        # roteamento abaixo); os outros testes deste arquivo chamam `fit_
        # side_model` direto, que nunca olha essas 2 colunas -- presença
        # inofensiva pros dois.
        "side": pl.Series([1 if i % 2 == 0 else -1 for i in range(n)]).cast(pl.Int8),
        "barrier_hit": pl.Series(rng.choice(["TP", "SL", "TIME"], size=n)),
    }
    for fid in T1_FEATURE_IDS:
        cols[fid] = pl.Series(rng.normal(size=n))
    return pl.DataFrame(cols)


def _fixed_hyper() -> alpha.LGBMHyperparams:
    """`.from_constants()` puro tem `early_stopping_mode=THREE_WAY`/
    `ic_magnitude_floor_k=2.0` (defaults promovidos 2026-08-27) -- exigem
    `calib_split_mode=TEMPORAL_PURGED` e threading explícito de `hyper.
    ic_magnitude_floor_k` em CADA call site (`fit_side_model` nunca deriva
    isso de `hyper` sozinho, é responsabilidade de quem chama -- mesmo
    padrão que `run_fold` já segue). Fixado aqui em `FIXED`/`None` pra
    testar só o mecanismo do cache, sem precisar replicar o wiring de
    3-way/purged split mode inteiro."""
    return dataclasses.replace(
        alpha.LGBMHyperparams.from_constants(),
        early_stopping_mode=alpha.EARLY_STOPPING_FIXED,
        ic_magnitude_floor_k=None,
        regularization_basis=alpha.REGULARIZATION_FIXED,
    )


def _base_kwargs() -> dict[str, Any]:
    return {
        "side": 1,
        "variant": alpha.VARIANT_CAMADA1,
        "hyper": _fixed_hyper(),
        "seed": 3,
        "target_signal_rate": 0.2,  # noqa: magic-number -- alto, dataset sintético pequeno
    }


# ============================================================================
# compute_monotone_screen -- extração pura, sem mudança de comportamento
# ============================================================================


def test_compute_monotone_screen_bate_com_o_que_fit_side_model_ja_produzia() -> None:
    """`fit_side_model` sem override chama `compute_monotone_screen`
    internamente -- os `constraint` reportados em `SideModelResult.
    monotone` têm que ser IDÊNTICOS a uma chamada direta e independente
    da função extraída, com os mesmos argumentos."""
    df = _frame_com_t0_t1_uniqueness()
    kwargs = _base_kwargs()
    hyper: alpha.LGBMHyperparams = kwargs["hyper"]

    result = alpha.fit_side_model(df, **kwargs)

    direct = alpha.compute_monotone_screen(
        df, T1_FEATURE_IDS, side=1, ic_magnitude_floor_k=hyper.ic_magnitude_floor_k
    )
    for feature_id in T1_FEATURE_IDS:
        assert result.monotone[feature_id].constraint == direct[feature_id].constraint
        assert result.monotone[feature_id].mean_ic == pytest.approx(direct[feature_id].mean_ic)


# ============================================================================
# fit_side_model -- override produz resultado bit-idêntico
# ============================================================================


def test_monotone_screen_override_produz_modelo_bit_identico_ao_sem_override() -> None:
    df = _frame_com_t0_t1_uniqueness()
    kwargs = _base_kwargs()
    hyper: alpha.LGBMHyperparams = kwargs["hyper"]

    result_sem_override = alpha.fit_side_model(df, **kwargs)

    override = alpha.compute_monotone_screen(
        df, T1_FEATURE_IDS, side=1, ic_magnitude_floor_k=hyper.ic_magnitude_floor_k
    )
    result_com_override = alpha.fit_side_model(
        df, **kwargs, monotone_screen_override=override
    )

    assert result_com_override.monotone_constraints == result_sem_override.monotone_constraints
    assert result_com_override.tau == pytest.approx(result_sem_override.tau)
    X_all = alpha.build_design_matrix(df, feature_ids=T1_FEATURE_IDS)
    pred_sem = np.asarray(result_sem_override.model.predict_proba(X_all))[:, 1]
    pred_com = np.asarray(result_com_override.model.predict_proba(X_all))[:, 1]
    np.testing.assert_array_equal(pred_sem, pred_com)


def test_monotone_screen_override_pula_o_calculo_interno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prova que o override de fato PULA `compute_monotone_screen` (não só
    que o resultado bate por coincidência) -- monkeypatch faz a função
    real levantar se for chamada; só passa se o override for honrado."""
    df = _frame_com_t0_t1_uniqueness()
    kwargs = _base_kwargs()
    hyper: alpha.LGBMHyperparams = kwargs["hyper"]
    override = alpha.compute_monotone_screen(
        df, T1_FEATURE_IDS, side=1, ic_magnitude_floor_k=hyper.ic_magnitude_floor_k
    )

    def _raise(*args: Any, **kwargs_inner: Any) -> Any:
        raise AssertionError("compute_monotone_screen não deveria ser chamado com override")

    monkeypatch.setattr(alpha, "compute_monotone_screen", _raise)
    result = alpha.fit_side_model(df, **kwargs, monotone_screen_override=override)
    assert result.model.booster_ is not None


# ============================================================================
# run_fold / run_all_folds -- roteamento por (split, side)
# ============================================================================


def test_run_fold_roteia_override_por_side(monkeypatch: pytest.MonkeyPatch) -> None:
    """`monotone_screen_override_by_side={1: X, -1: Y}` -- o lado `+1`
    recebe `X`, o lado `-1` recebe `Y`, nunca trocados. Override REAL (não
    sentinela vazio) -- `fit_side_model` real roda por trás da captura,
    então o override precisa ser um `ic_results` de verdade."""
    df = _frame_com_t0_t1_uniqueness(n=300)  # noqa: magic-number -- CPCV split real precisa de mais linhas
    hyper = _fixed_hyper()

    train_long = ds.side_subset(df, side=1, feature_ids=T1_FEATURE_IDS, enforce_r2=False)
    train_short = ds.side_subset(df, side=-1, feature_ids=T1_FEATURE_IDS, enforce_r2=False)
    override_long = alpha.compute_monotone_screen(
        train_long, T1_FEATURE_IDS, side=1, ic_magnitude_floor_k=hyper.ic_magnitude_floor_k
    )
    override_short = alpha.compute_monotone_screen(
        train_short, T1_FEATURE_IDS, side=-1, ic_magnitude_floor_k=hyper.ic_magnitude_floor_k
    )

    captured: dict[int, Any] = {}
    real_fit = alpha.fit_side_model

    def _capturing_fit_side_model(*args: Any, **kwargs: Any) -> Any:
        captured[kwargs["side"]] = kwargs.get("monotone_screen_override")
        return real_fit(*args, **kwargs)

    monkeypatch.setattr(alpha, "fit_side_model", _capturing_fit_side_model)

    split = CPCVSplit(
        split_id=0,
        path_id=0,
        test_groups=(0,),
        train_groups=(1,),
        train_idx=np.arange(0, 200),
        test_idx=np.arange(200, 300),
        n_train_candidate=200,
        n_purged=0,
        n_embargoed=0,
    )
    alpha.run_fold(
        df,
        split,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        model_id="teste_roteamento",
        seed=1,
        symbol="TESTE",
        feature_ids=T1_FEATURE_IDS,
        enforce_r2=False,
        monotone_screen_override_by_side={1: override_long, -1: override_short},
    )
    assert captured[1] is override_long
    assert captured[-1] is override_short
