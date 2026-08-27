"""Testes do número efetivo de símbolos (`src.analysis.
eixo1_effective_symbol_count`, `AG-328`).

Cobrem o NÚCLEO PURO (`build_symbol_statistic_matrix`, `effective_number_
of_tests_galwey`) -- nenhum toca disco. A casca (`run_effective_symbol_
count_report`) lê relatórios reais -- fora do escopo deste arquivo (mesmo
padrão dos módulos irmãos)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.analysis import eixo1_effective_symbol_count as esc

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def _report(por_simbolo: dict[str, dict[str, float | None]]) -> dict[str, object]:
    return {
        "por_simbolo": {
            symbol: {"por_feature": {name: {"pico_abs_t": t} for name, t in features.items()}}
            for symbol, features in por_simbolo.items()
        }
    }


# ============================================================================
# build_symbol_statistic_matrix
# ============================================================================


def test_build_symbol_statistic_matrix_reconstroi_e_ordena_features() -> None:
    report = _report(
        {
            "BTCUSDT": {"B_feat": 2.0, "A_feat": 1.0},
            "ETHUSDT": {"B_feat": 2.5, "A_feat": 1.5},
        }
    )
    names, matrix = esc.build_symbol_statistic_matrix(report, ("BTCUSDT", "ETHUSDT"))
    assert names == ("A_feat", "B_feat")
    assert matrix.shape == (2, 2)
    assert matrix[0].tolist() == [1.0, 2.0]
    assert matrix[1].tolist() == [1.5, 2.5]


def test_build_symbol_statistic_matrix_dropa_feature_com_nan_em_qualquer_simbolo() -> None:
    report = _report(
        {
            "BTCUSDT": {"ok": 1.0, "dead": None},
            "ETHUSDT": {"ok": 1.2, "dead": float("nan")},
        }
    )
    names, matrix = esc.build_symbol_statistic_matrix(report, ("BTCUSDT", "ETHUSDT"))
    assert names == ("ok",)
    assert matrix.shape == (2, 1)


def test_build_symbol_statistic_matrix_levanta_com_simbolo_ausente() -> None:
    report = _report({"BTCUSDT": {"ok": 1.0}})
    with pytest.raises(esc.Eixo1EffectiveSymbolCountError, match=r"BTCUSDT|ETHUSDT"):
        esc.build_symbol_statistic_matrix(report, ("BTCUSDT", "ETHUSDT"))


def test_build_symbol_statistic_matrix_levanta_sem_feature_comum_finita() -> None:
    report = _report(
        {
            "BTCUSDT": {"dead": None},
            "ETHUSDT": {"dead": None},
        }
    )
    with pytest.raises(esc.Eixo1EffectiveSymbolCountError, match="finito"):
        esc.build_symbol_statistic_matrix(report, ("BTCUSDT", "ETHUSDT"))


# ============================================================================
# effective_number_of_tests_galwey
# ============================================================================


def test_effective_number_of_tests_galwey_matriz_identidade_da_n_completo() -> None:
    """Correlacao 0 entre todos os pares (matriz identidade) -- M_eff deve
    bater exatamente com N (todos os N ensaios sao de fato independentes)."""
    corr = np.eye(5)
    m_eff = esc.effective_number_of_tests_galwey(corr)
    assert m_eff == pytest.approx(5.0, abs=1e-9)


def test_effective_number_of_tests_galwey_correlacao_perfeita_da_1() -> None:
    """Todos os pares com correlacao 1,0 (matriz de uns) -- so ha 1 ensaio
    efetivamente independente, apesar de N=5 nominal."""
    corr = np.ones((5, 5))
    m_eff = esc.effective_number_of_tests_galwey(corr)
    assert m_eff == pytest.approx(1.0, abs=1e-6)


def test_effective_number_of_tests_galwey_fica_entre_1_e_n_para_correlacao_parcial() -> None:
    n = 5
    rho = 0.5
    corr = np.full((n, n), rho)
    np.fill_diagonal(corr, 1.0)
    m_eff = esc.effective_number_of_tests_galwey(corr)
    assert 1.0 < m_eff < float(n)


def test_effective_number_of_tests_galwey_levanta_sem_autovalor_positivo() -> None:
    corr = np.zeros((3, 3))
    with pytest.raises(esc.Eixo1EffectiveSymbolCountError, match="autovalor"):
        esc.effective_number_of_tests_galwey(corr)


def test_effective_number_of_tests_galwey_e_simetrico_a_permutacao() -> None:
    """M_eff nao deveria depender da ORDEM dos simbolos na matriz -- e uma
    propriedade agregada dos autovalores, invariante a permutacao de
    linhas/colunas simultaneas."""
    rng = np.random.default_rng(0)
    a = rng.standard_normal((5, 40))
    corr = np.corrcoef(a)
    m_eff_original = esc.effective_number_of_tests_galwey(corr)
    perm = [3, 1, 4, 0, 2]
    corr_permutada = corr[np.ix_(perm, perm)]
    m_eff_permutada = esc.effective_number_of_tests_galwey(corr_permutada)
    assert m_eff_original == pytest.approx(m_eff_permutada, abs=1e-9)


def test_effective_number_of_tests_galwey_e_finito_para_matriz_real_aleatoria() -> None:
    rng = np.random.default_rng(1)
    a = rng.standard_normal((5, 100))
    corr = np.corrcoef(a)
    m_eff = esc.effective_number_of_tests_galwey(corr)
    assert math.isfinite(m_eff)
    assert 1.0 <= m_eff <= 5.0 + 1e-9
