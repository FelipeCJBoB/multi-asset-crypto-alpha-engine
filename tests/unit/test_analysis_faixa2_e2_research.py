"""Testes de `src/analysis/faixa2_e2_research.py` — lógica pura de
correlação/seleção gulosa, com fixtures sintéticas pequenas (o carregamento
real de ~70 candidatas sobre 6,5 anos já foi verificado manualmente:
`experiments/faixa2_e2_research.json`, 71,7s, n_eff 6,48→15,83)."""

from __future__ import annotations

import numpy as np
import pytest

from src.analysis import faixa2_e2_research as e2r


def test_pairwise_corr_matrix_recupera_correlacoes_conhecidas() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(size=500)
    data = {
        "x": x,
        "y_igual": x.copy(),
        "y_oposto": -x,
        "z_independente": rng.normal(size=500),
    }
    mat, names = e2r.pairwise_corr_matrix(data)
    idx = {n: i for i, n in enumerate(names)}
    assert mat[idx["x"], idx["x"]] == pytest.approx(1.0)
    assert mat[idx["x"], idx["y_igual"]] == pytest.approx(1.0, abs=1e-9)
    assert mat[idx["x"], idx["y_oposto"]] == pytest.approx(-1.0, abs=1e-9)
    assert abs(mat[idx["x"], idx["z_independente"]]) < 0.15


def test_pairwise_corr_matrix_lida_com_cobertura_parcial_nan() -> None:
    """Simula o caso BVOL (cobertura ~3,1 de 6,5 anos) -- pares com poucos
    pontos em comum (`< 30`) ficam NaN em vez de um número instável."""
    rng = np.random.default_rng(2)
    n = 500
    x = rng.normal(size=n)
    y_curto = np.full(n, np.nan)
    y_curto[-10:] = rng.normal(size=10)  # só 10 pontos em comum -- abaixo do mínimo de 30
    mat, names = e2r.pairwise_corr_matrix({"x": x, "y_curto": y_curto})
    idx = {n_: i for i, n_ in enumerate(names)}
    assert np.isnan(mat[idx["x"], idx["y_curto"]])


def test_n_eff_for_subset_reduz_com_features_redundantes() -> None:
    """3 features idênticas colapsam pra n_eff=1 (peso uniforme); 3
    ortogonais dão n_eff=3 -- caso degenerado que a própria docstring de
    `compute_effective_concentration` usa como prova."""
    identical = np.array(
        [[1.0, 0.999, 0.999], [0.999, 1.0, 0.999], [0.999, 0.999, 1.0]]
    )
    orthogonal = np.eye(3)
    name_to_idx = {"a": 0, "b": 1, "c": 2}
    n_eff_identical = e2r._n_eff_for_subset(identical, name_to_idx, ["a", "b", "c"])
    n_eff_orthogonal = e2r._n_eff_for_subset(orthogonal, name_to_idx, ["a", "b", "c"])
    assert n_eff_identical == pytest.approx(1.0, abs=0.01)
    assert n_eff_orthogonal == pytest.approx(3.0, abs=1e-9)


def test_greedy_select_para_quando_atinge_alvo_alto() -> None:
    """4 candidatas MUTUAMENTE ORTOGONAIS entre si e com o T1 -- cada uma
    adiciona +1 exato a n_eff. T1 de 2 (ortogonais) + 4 candidatas
    ortogonais -> alvo [3,4] atingido em 2 passos, não consome as 2
    restantes."""
    names = ("t1_a", "t1_b", "c1", "c2", "c3", "c4")
    corr = np.eye(len(names))
    out = e2r.greedy_select_by_orthogonality(
        corr,
        names,
        current_t1=("t1_a", "t1_b"),
        vol_proxy="t1_a",
        target_low=3.0,
        target_high=4.0,
    )
    assert out["reached_target"] is True
    assert len(out["selected_beyond_t1"]) == 2
    assert out["final_n_eff_factors"] == pytest.approx(4.0, abs=1e-6)


def test_greedy_select_prefere_candidata_mais_ortogonal() -> None:
    """`c1` correlaciona 0,9 com `t1_a` (quase redundante); `c2` é
    ortogonal -- o algoritmo tem que escolher `c2` primeiro."""
    names = ("t1_a", "c1", "c2")
    corr = np.array(
        [
            [1.0, 0.9, 0.0],
            [0.9, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    out = e2r.greedy_select_by_orthogonality(
        corr, names, current_t1=("t1_a",), vol_proxy="t1_a", target_low=1.5, target_high=1.9
    )
    assert out["selection_history"][1]["feature_added"] == "c2"


def test_greedy_select_exclui_features_ja_decididas_contra() -> None:
    """`E27f`/`A13` nunca podem ser re-selecionadas mesmo que pareçam
    ortogonais -- decisão de pré-E2 (2) já fechada."""
    names = ("t1_a", "E27f_cost_atr_ratio", "c1")
    corr = np.eye(len(names))
    out = e2r.greedy_select_by_orthogonality(
        corr, names, current_t1=("t1_a",), vol_proxy="t1_a", target_low=1.5, target_high=1.9
    )
    assert "E27f_cost_atr_ratio" not in out["selected_beyond_t1"]
    assert out["selected_beyond_t1"] == ["c1"]


def test_flag_vol_saturated_selections_sinaliza_alta_correlacao() -> None:
    selection = {
        "selected_beyond_t1": ["feat_vol", "feat_ortogonal"],
        "vol_proxy_correlation_by_candidate": {"feat_vol": 0.75, "feat_ortogonal": 0.05},
    }
    flags = e2r.flag_vol_saturated_selections(selection)
    assert len(flags) == 1
    assert flags[0]["feature"] == "feat_vol"


def test_flag_vol_saturated_selections_vazio_quando_tudo_ortogonal() -> None:
    selection = {
        "selected_beyond_t1": ["feat_a", "feat_b"],
        "vol_proxy_correlation_by_candidate": {"feat_a": 0.1, "feat_b": -0.2},
    }
    assert e2r.flag_vol_saturated_selections(selection) == []
