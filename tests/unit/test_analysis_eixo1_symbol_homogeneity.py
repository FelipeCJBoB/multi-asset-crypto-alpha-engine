"""Testes do teste de homogeneidade entre símbolos do eixo 1
(`src.analysis.eixo1_symbol_homogeneity`, `AG-328`).

Cobrem o NÚCLEO PURO (`discovery_matrix_from_report`, `test_symbol_
homogeneity`) -- nenhum toca disco. A casca (`run_symbol_homogeneity_
report`) lê o relatório real -- fora do escopo deste arquivo (mesmo padrão
de `test_analysis_feature_promotion_criterion.py`)."""

from __future__ import annotations

import math

import pytest

from src.analysis import eixo1_symbol_homogeneity as esh

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


# ============================================================================
# discovery_matrix_from_report
# ============================================================================


def test_discovery_matrix_from_report_reconstroi_corretamente() -> None:
    por_feature = [
        {"feature": "A", "symbols_discovery": ["BTCUSDT", "ETHUSDT"]},
        {"feature": "B", "symbols_discovery": []},
    ]
    matrix = esh.discovery_matrix_from_report(por_feature, SYMBOLS)
    assert matrix["A"] == {
        "BTCUSDT": True,
        "ETHUSDT": True,
        "SOLUSDT": False,
        "BNBUSDT": False,
        "XRPUSDT": False,
    }
    assert matrix["B"] == dict.fromkeys(SYMBOLS, False)


def test_discovery_matrix_from_report_lista_vazia() -> None:
    assert esh.discovery_matrix_from_report([], SYMBOLS) == {}


# ============================================================================
# test_symbol_homogeneity
# ============================================================================


def test_symbol_homogeneity_levanta_com_matriz_vazia() -> None:
    with pytest.raises(esh.Eixo1SymbolHomogeneityError, match="vazio"):
        esh.test_symbol_homogeneity({}, symbols=SYMBOLS, alpha=0.05)


def test_symbol_homogeneity_levanta_com_alpha_fora_do_intervalo() -> None:
    matrix = {"A": dict.fromkeys(SYMBOLS, False)}
    with pytest.raises(esh.Eixo1SymbolHomogeneityError, match="alpha"):
        esh.test_symbol_homogeneity(matrix, symbols=SYMBOLS, alpha=1.5)


def test_symbol_homogeneity_taxas_iguais_nao_rejeita() -> None:
    """20 features, cada simbolo descobre em exatamente 4 delas (taxa
    identica) -- deve ficar bem longe de rejeitar homogeneidade."""
    n = 20
    matrix = {}
    for i in range(n):
        # cada simbolo descobre em features {0,5,10,15} + deslocamento por simbolo,
        # mas a CONTAGEM total por simbolo fica igual (4 de 20) pra todos.
        matrix[f"f{i}"] = dict.fromkeys(SYMBOLS, False)
    for sym_idx, sym in enumerate(SYMBOLS):
        for k in range(4):
            feature_idx = (sym_idx * 4 + k) % n
            matrix[f"f{feature_idx}"][sym] = True
    resultado = esh.test_symbol_homogeneity(matrix, symbols=SYMBOLS, alpha=0.05)
    assert resultado.n_features == n
    assert all(v == 4 for v in resultado.discoveries_by_symbol.values())
    assert resultado.p_value == pytest.approx(1.0, abs=1e-9)
    assert resultado.homogeneo is True


def test_symbol_homogeneity_um_simbolo_dominante_rejeita() -> None:
    """72 features, 1 simbolo (BNBUSDT) descobre em 15 delas, os outros 4
    descobrem em 1 cada -- reproduz a assimetria medida nos dados reais
    (AG-328) e deve rejeitar homogeneidade com folga."""
    n = 72
    matrix = {f"f{i}": dict.fromkeys(SYMBOLS, False) for i in range(n)}
    for i in range(15):
        matrix[f"f{i}"]["BNBUSDT"] = True
    for i, sym in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")):
        matrix[f"f{15 + i}"][sym] = True
    resultado = esh.test_symbol_homogeneity(matrix, symbols=SYMBOLS, alpha=0.05)
    assert resultado.discoveries_by_symbol["BNBUSDT"] == 15
    assert resultado.p_value < 0.05
    assert resultado.homogeneo is False


def test_symbol_homogeneity_descobertas_esparsas_nao_quebra() -> None:
    """Tabela esparsa (so 1 simbolo com poucas descobertas, resto zero, mas
    coluna 'descoberta' nao totalmente zero -- evita o 0/0 degenerado da
    tabela inteiramente vazia, que deixaria expected_freq indefinido)."""
    n = 10
    matrix = {f"f{i}": dict.fromkeys(SYMBOLS, False) for i in range(n)}
    matrix["f0"]["BNBUSDT"] = True
    matrix["f1"]["BNBUSDT"] = True
    resultado = esh.test_symbol_homogeneity(matrix, symbols=SYMBOLS, alpha=0.05)
    assert resultado.discoveries_by_symbol["BNBUSDT"] == 2
    assert all(
        v == 0 for sym, v in resultado.discoveries_by_symbol.items() if sym != "BNBUSDT"
    )
    assert math.isfinite(resultado.p_value)
