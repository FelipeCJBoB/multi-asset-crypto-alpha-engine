"""Testes dos itens 6, 8 e 9 de `ADR-005 §13.17` (persona `lgbm-crypto-
quant`, 2026-08-26) -- "fix mecânico" validado e aplicado, cada um como
política opt-in (mesmo padrão de `calib_weight_basis`/`class_balance_basis`/
`tau_policy`): o default de `fit_side_model` continua bit-exato para todo
call site/teste existente; só quem pede a política nova paga o custo.

Item 6 (`§13.14.2`) -- piso de magnitude nas constraints monotônicas: os
núcleos puros (`se_spearman_fisher`/`_assign_from_ic`/`screen_monotone_
constraints`) já são testados em `test_models_monotonic.py`; aqui só a
wiring por `fit_side_model` (`ic_magnitude_floor_k`).

Item 8 (`§13.14.1`) -- regularização de folha derivada de `ESS`
(`derive_ess_regularization`), wireada por `regularization_basis`.

Item 9 (`§13.14.3`) -- `early_stopping` em três partições (`fit`/`stop`/
`calib`), `_temporal_purged_three_way_split` + `early_stopping_mode`."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
import pytest

from src.features.build import T1_FEATURE_IDS
from src.models import alpha

# ============================================================================
# item 8 -- derive_ess_regularization (núcleo puro)
# ============================================================================


def test_derive_ess_regularization_formula_fechada() -> None:
    # ess=1000, n_rows=2000 -> linhas/ess = 2.0; n_obs_alvo=30 ->
    # min_child_samples = ceil(30*2.0) = 60. w_mean=1.2, spw=1.5,
    # fator=0.5 -> hessian = 60*1.2*0.25/1.5*0.5 = 6.0.
    mcs, mshl = alpha.derive_ess_regularization(
        ess=1000.0,
        n_rows=2000,
        w_mean=1.2,  # noqa: magic-number
        scale_pos_weight=1.5,  # noqa: magic-number
        n_obs_independentes_alvo=30.0,  # noqa: magic-number
        fator_conservador=0.5,  # noqa: magic-number
    )
    assert mcs == 60  # noqa: magic-number
    assert mshl == pytest.approx(6.0)  # noqa: magic-number


def test_derive_ess_regularization_ess_nao_positivo_levanta() -> None:
    with pytest.raises(ValueError, match="ess"):
        alpha.derive_ess_regularization(
            ess=0.0, n_rows=100, w_mean=1.0, scale_pos_weight=1.0,
            n_obs_independentes_alvo=30.0, fator_conservador=0.5,  # noqa: magic-number
        )


def test_derive_ess_regularization_scale_pos_weight_nao_positivo_levanta() -> None:
    with pytest.raises(ValueError, match="scale_pos_weight"):
        alpha.derive_ess_regularization(
            ess=100.0, n_rows=200, w_mean=1.0, scale_pos_weight=0.0,  # noqa: magic-number
            n_obs_independentes_alvo=30.0, fator_conservador=0.5,  # noqa: magic-number
        )


# ============================================================================
# item 9 -- _temporal_purged_three_way_split (núcleo puro), mesmo padrão de
# test_models_alpha_ag208_217.py::_temporal_purged_calib_split
# ============================================================================


def test_three_way_split_calib_e_stop_sao_blocos_contiguos_do_fim() -> None:
    t0 = np.arange(0, 100, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = t0 + 500  # noqa: magic-number -- nenhum label cruza o vizinho, purge não remove nada
    fit_idx, stop_idx, calib_idx = alpha._temporal_purged_three_way_split(
        t0, t1, stop_frac=0.15, calib_frac=0.25  # noqa: magic-number
    )
    assert calib_idx.shape[0] == 25  # noqa: magic-number
    assert stop_idx.shape[0] == 15  # noqa: magic-number
    assert fit_idx.shape[0] == 60  # noqa: magic-number
    # ordem cronológica: fit < stop < calib, sem overlap de índice
    assert t0[stop_idx].min() > t0[fit_idx].max()
    assert t0[calib_idx].min() > t0[stop_idx].max()
    todos = set(fit_idx.tolist()) | set(stop_idx.tolist()) | set(calib_idx.tolist())
    assert len(todos) == 100  # noqa: magic-number -- partição, nada duplicado nem perdido


def test_three_way_split_purga_stop_que_cruza_a_fronteira_de_calib() -> None:
    t0 = np.arange(0, 100, dtype=np.int64) * 1_000  # noqa: magic-number
    # horizonte que purga PARTE de stop (não o esvazia): calib_start=75000,
    # stop candidato tem t0 em [60000,74000] -- t1=t0+8000 cruza 75000 pra
    # t0>=67000, sobrevive pra t0<67000.
    t1 = t0 + 8_000  # noqa: magic-number
    _fit_idx, stop_idx, calib_idx = alpha._temporal_purged_three_way_split(
        t0, t1, stop_frac=0.15, calib_frac=0.25  # noqa: magic-number
    )
    calib_start = int(t0[calib_idx].min())
    assert stop_idx.shape[0] < 15  # noqa: magic-number -- purge removeu algo
    assert stop_idx.shape[0] > 0  # mas não esvaziou
    assert bool((t1[stop_idx] < calib_start).all())


def test_three_way_split_purga_fit_que_cruza_a_fronteira_de_stop() -> None:
    t0 = np.arange(0, 100, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = t0 + 8_000  # noqa: magic-number -- mesmo horizonte do teste acima, purga parcial nos dois níveis
    fit_idx, stop_idx, _calib_idx = alpha._temporal_purged_three_way_split(
        t0, t1, stop_frac=0.15, calib_frac=0.25  # noqa: magic-number
    )
    stop_start = int(t0[stop_idx].min())
    assert fit_idx.shape[0] < 60  # noqa: magic-number -- purge removeu algo do fit também
    assert bool((t1[fit_idx] < stop_start).all())


def test_three_way_split_falha_alto_quando_purge_esvazia_stop() -> None:
    t0 = np.arange(0, 20, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = t0 + 10_000_000  # noqa: magic-number -- todo label aberto até o fim da série
    with pytest.raises(ValueError, match="esvaziou 'stop'"):
        alpha._temporal_purged_three_way_split(t0, t1, stop_frac=0.15, calib_frac=0.25)  # noqa: magic-number


def test_three_way_split_n_menor_que_3_levanta() -> None:
    t0 = np.array([0, 1000], dtype=np.int64)  # noqa: magic-number
    t1 = t0 + 100  # noqa: magic-number
    with pytest.raises(ValueError, match=">= 3"):
        alpha._temporal_purged_three_way_split(t0, t1, stop_frac=0.15, calib_frac=0.25)  # noqa: magic-number


def test_three_way_split_fracoes_invalidas_levanta() -> None:
    t0 = np.arange(0, 10, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = t0 + 100  # noqa: magic-number
    with pytest.raises(ValueError, match="stop_frac"):
        alpha._temporal_purged_three_way_split(t0, t1, stop_frac=0.6, calib_frac=0.6)  # noqa: magic-number
    with pytest.raises(ValueError, match="stop_frac"):
        alpha._temporal_purged_three_way_split(t0, t1, stop_frac=0.0, calib_frac=0.25)  # noqa: magic-number


# ============================================================================
# fit_side_model -- wiring de item 6/8/9, dado sintético pequeno mas REAL
# (LightGBM de verdade, mesmo padrão de test_models_alpha.py)
# ============================================================================


def _frame_com_t0_t1_uniqueness(n: int = 200, *, seed: int = 7) -> pl.DataFrame:
    """`t0` estritamente crescente (necessário pro purge temporal fazer
    sentido), `t1` com horizonte curto (não teria por que purgar nada
    aqui -- os testes de purge de verdade já vivem nos núcleos puros
    acima), `uniqueness` presente (item 6/8 exigem a coluna quando a
    política nova é pedida)."""
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
    }
    for fid in T1_FEATURE_IDS:
        cols[fid] = pl.Series(rng.normal(size=n))
    return pl.DataFrame(cols)


def _base_kwargs() -> dict[str, Any]:
    return {
        "side": 1,
        "variant": alpha.VARIANT_CAMADA1,
        "hyper": alpha.LGBMHyperparams.from_constants(),
        "seed": 1,
        "target_signal_rate": 0.02,  # noqa: magic-number
    }


# --- item 8 ---


def test_regularization_basis_default_e_fixed() -> None:
    import inspect

    sig = inspect.signature(alpha.fit_side_model)
    assert sig.parameters["regularization_basis"].default == alpha.REGULARIZATION_FIXED


def test_regularization_ess_derived_sem_uniqueness_falha_alto() -> None:
    df = _frame_com_t0_t1_uniqueness().drop("uniqueness")
    with pytest.raises(ValueError, match="uniqueness"):
        alpha.fit_side_model(
            df, **_base_kwargs(), regularization_basis=alpha.REGULARIZATION_ESS_DERIVED
        )


def test_regularization_ess_derived_treina_com_uniqueness_presente() -> None:
    df = _frame_com_t0_t1_uniqueness()
    result = alpha.fit_side_model(
        df, **_base_kwargs(), regularization_basis=alpha.REGULARIZATION_ESS_DERIVED
    )
    assert result.model.booster_ is not None


def test_regularization_basis_desconhecido_levanta() -> None:
    df = _frame_com_t0_t1_uniqueness()
    with pytest.raises(ValueError, match="regularization_basis desconhecido"):
        alpha.fit_side_model(df, **_base_kwargs(), regularization_basis="chute")


# --- item 6 ---


def test_ic_magnitude_floor_k_default_e_none() -> None:
    import inspect

    sig = inspect.signature(alpha.fit_side_model)
    assert sig.parameters["ic_magnitude_floor_k"].default is None


def test_ic_magnitude_floor_k_sem_uniqueness_falha_alto() -> None:
    df = _frame_com_t0_t1_uniqueness().drop("uniqueness")
    with pytest.raises(ValueError, match="uniqueness"):
        alpha.fit_side_model(df, **_base_kwargs(), ic_magnitude_floor_k=2.0)  # noqa: magic-number


def test_ic_magnitude_floor_k_treina_com_uniqueness_presente() -> None:
    df = _frame_com_t0_t1_uniqueness()
    result = alpha.fit_side_model(df, **_base_kwargs(), ic_magnitude_floor_k=2.0)  # noqa: magic-number
    assert result.model.booster_ is not None


# --- item 9 ---


def test_early_stopping_mode_default_e_fixed() -> None:
    import inspect

    sig = inspect.signature(alpha.fit_side_model)
    assert sig.parameters["early_stopping_mode"].default == alpha.EARLY_STOPPING_FIXED


def test_early_stopping_mode_default_n_train_stop_e_zero() -> None:
    """Caminho legado (default) -- sem bloco de `stop`, `SideModelResult`
    reporta isso explicitamente (`0`/`None`), não um valor inventado."""
    df = _frame_com_t0_t1_uniqueness()
    result = alpha.fit_side_model(df, **_base_kwargs())
    assert result.n_train_stop == 0
    assert result.best_iteration is None


def test_three_way_com_calib_split_legado_falha_alto() -> None:
    """`early_stopping_mode=THREE_WAY` exige `calib_split_mode=TEMPORAL_
    PURGED` -- um split aleatório não tem fronteira temporal pra purgar."""
    df = _frame_com_t0_t1_uniqueness()
    with pytest.raises(ValueError, match="calib_split_mode"):
        alpha.fit_side_model(
            df,
            **_base_kwargs(),
            early_stopping_mode=alpha.EARLY_STOPPING_THREE_WAY,
            calib_split_mode=alpha.CALIB_SPLIT_LEGACY_RANDOM,
        )


def test_three_way_treina_de_verdade_e_popula_n_train_stop() -> None:
    df = _frame_com_t0_t1_uniqueness(n=300)  # noqa: magic-number -- 3 blocos pedem mais linhas
    result = alpha.fit_side_model(
        df,
        **_base_kwargs(),
        early_stopping_mode=alpha.EARLY_STOPPING_THREE_WAY,
        calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
    )
    assert result.model.booster_ is not None
    assert result.n_train_stop > 0
    # best_iteration só é None se o boosting NUNCA melhorou no eval_set
    # (0 é falsy em Python -- `model.best_iteration_ == 0` também vira
    # None pela mesma checagem que popula o campo) -- qualquer um dos
    # dois é um resultado válido sob dado sintético de ruído, o que
    # importa é que o campo existe e é int quando setado.
    assert result.best_iteration is None or isinstance(result.best_iteration, int)


def test_three_way_n_train_fit_stop_calib_somam_o_total() -> None:
    df = _frame_com_t0_t1_uniqueness(n=300)  # noqa: magic-number
    result = alpha.fit_side_model(
        df,
        **_base_kwargs(),
        early_stopping_mode=alpha.EARLY_STOPPING_THREE_WAY,
        calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
    )
    # sem overlap entre os 3 blocos (partição), mas PODE haver purge --
    # a soma é <= n, nunca >.
    assert result.n_train_fit + result.n_train_stop + result.n_train_calib <= df.height


# ============================================================================
# ADR-008 Fase 3 -- `InSampleSegmentScores` (`fit_segment`/`stop_segment`/
# `calib_segment`) -- score CALIBRADO + `label` + `ret_net` de cada
# sub-split in-sample, nunca exposto antes (só a CONTAGEM -- `n_train_fit`/
# `n_train_calib`/`n_train_stop`, testada acima -- já existia). Existe pra
# `score_quality.compute_train_val_test_gap` medir o generalization gap
# sem precisar re-treinar.
# ============================================================================


def test_default_fixed_popula_fit_e_calib_segment_stop_none() -> None:
    """Caminho legado (`EARLY_STOPPING_FIXED` + `CALIB_SPLIT_LEGACY_RANDOM`,
    default de `_base_kwargs`) -- `fit`/`calib` existem, `stop` não (mesma
    condição de `n_train_stop==0`/`best_iteration is None`, já testada
    acima)."""
    df = _frame_com_t0_t1_uniqueness()
    result = alpha.fit_side_model(df, **_base_kwargs())

    assert result.fit_segment is not None
    assert result.calib_segment is not None
    assert result.stop_segment is None
    assert result.fit_segment.n == result.n_train_fit
    assert result.calib_segment.n == result.n_train_calib


def test_segment_arrays_tem_shape_n_e_dtype_certo() -> None:
    df = _frame_com_t0_t1_uniqueness()
    result = alpha.fit_side_model(df, **_base_kwargs())

    seg = result.fit_segment
    assert seg is not None
    assert seg.calibrated_score.shape == (seg.n,)
    assert seg.label.shape == (seg.n,)
    assert seg.ret_net.shape == (seg.n,)
    assert set(np.unique(seg.label).tolist()) <= {0, 1}
    # saída do calibrador isotônico (`y_min=0.0, y_max=1.0`) -- sempre
    # dentro do intervalo, nunca fora.
    assert bool((seg.calibrated_score >= 0.0).all())
    assert bool((seg.calibrated_score <= 1.0).all())


def test_fit_e_calib_segment_particionam_o_ret_net_sob_split_legado() -> None:
    """Split legado (`CALIB_SPLIT_LEGACY_RANDOM`, default) não purga nada
    -- `fit`+`calib` é uma partição EXATA de todas as linhas de
    `train_side_df`, sem overlap, sem sobra. Reconstrói o multiset
    completo de `ret_net` pra provar que os valores de cada segmento vêm
    das linhas certas, não um array inventado/desalinhado."""
    df = _frame_com_t0_t1_uniqueness(n=120)  # noqa: magic-number
    result = alpha.fit_side_model(df, **_base_kwargs())

    assert result.fit_segment is not None
    assert result.calib_segment is not None
    combined = np.concatenate([result.fit_segment.ret_net, result.calib_segment.ret_net])
    esperado = df["ret_net"].to_numpy().astype(np.float64)
    np.testing.assert_array_equal(np.sort(combined), np.sort(esperado))


def test_three_way_popula_os_3_segmentos_com_n_certo() -> None:
    df = _frame_com_t0_t1_uniqueness(n=300)  # noqa: magic-number
    result = alpha.fit_side_model(
        df,
        **_base_kwargs(),
        early_stopping_mode=alpha.EARLY_STOPPING_THREE_WAY,
        calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
    )

    assert result.fit_segment is not None
    assert result.stop_segment is not None
    assert result.calib_segment is not None
    assert result.fit_segment.n == result.n_train_fit
    assert result.stop_segment.n == result.n_train_stop
    assert result.calib_segment.n == result.n_train_calib

    # cada valor de `ret_net` de cada segmento veio de fato de uma linha
    # real de `df` -- purge pode remover linhas (soma <= n, já provado
    # acima), mas nunca inventa um valor que não estava lá.
    universo = set(df["ret_net"].to_numpy().astype(np.float64).tolist())
    for seg in (result.fit_segment, result.stop_segment, result.calib_segment):
        assert set(seg.ret_net.tolist()) <= universo
