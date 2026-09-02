"""Testes do cruzamento eixo 1 x gain em producao (`src.analysis.
eixo1_gain_cross_check`, `AG-330`, addendum 2026-08-27).

Cobrem o NUCLEO PURO (`gain_shares_by_block`, `cross_check_features`) --
nenhum toca disco. A casca (`run_gain_eixo1_cross_check_report`) le
artefatos reais -- fora do escopo deste arquivo (mesmo padrao dos modulos
irmaos eixo1_*)."""

from __future__ import annotations

import pytest

from src.analysis import eixo1_gain_cross_check as gxc

_FEATURES = ("A", "B", "C")

# ============================================================================
# gain_shares_by_block
# ============================================================================


def test_gain_shares_by_block_normaliza_um_bloco() -> None:
    blocks = [{"A": 10.0, "B": 30.0, "C": 60.0}]
    shares = gxc.gain_shares_by_block(blocks, feature_ids=_FEATURES)
    assert len(shares) == 1
    assert shares[0]["A"] == pytest.approx(0.1)
    assert shares[0]["B"] == pytest.approx(0.3)
    assert shares[0]["C"] == pytest.approx(0.6)


def test_gain_shares_by_block_feature_ausente_do_bloco_vira_zero() -> None:
    blocks = [{"A": 10.0, "B": 30.0}]  # "C" nunca teve gain>0 nesse bloco
    shares = gxc.gain_shares_by_block(blocks, feature_ids=_FEATURES)
    assert shares[0]["C"] == 0.0
    assert shares[0]["A"] == pytest.approx(0.25)
    assert shares[0]["B"] == pytest.approx(0.75)


def test_gain_shares_by_block_multiplos_blocos_independentes() -> None:
    blocks = [
        {"A": 10.0, "B": 10.0, "C": 10.0},
        {"A": 90.0, "B": 5.0, "C": 5.0},
    ]
    shares = gxc.gain_shares_by_block(blocks, feature_ids=_FEATURES)
    assert len(shares) == 2
    assert shares[0]["A"] == pytest.approx(1.0 / 3.0)
    assert shares[1]["A"] == pytest.approx(0.9)


def test_gain_shares_by_block_lista_vazia_devolve_lista_vazia() -> None:
    assert gxc.gain_shares_by_block([], feature_ids=_FEATURES) == []


# ============================================================================
# cross_check_features
# ============================================================================


def test_cross_check_features_marca_contradicao_zero_descoberta_gain_alto() -> None:
    # "A" domina o gain (0.7 >> 1/3) mas nunca foi descoberto no eixo 1 --
    # exatamente o padrao real de E27f_cost_atr_ratio (AG-330).
    shares_by_block = [{"A": 0.7, "B": 0.2, "C": 0.1}]
    discovery = {"A": 0, "B": 0, "C": 1}
    results = gxc.cross_check_features(shares_by_block, discovery, feature_ids=_FEATURES)
    by_feature = {r.feature: r for r in results}
    assert by_feature["A"].contradiction_flag is True
    assert by_feature["A"].above_uniform_baseline is True
    assert by_feature["A"].n_symbols_discovery == 0


def test_cross_check_features_nao_marca_contradicao_zero_descoberta_gain_baixo() -> None:
    # "C" tem 0 descobertas E gain baixo -- padrao real de B01/D06f/C06,
    # sem a "desculpa de papel" que AG-330 da a E27f.
    shares_by_block = [{"A": 0.7, "B": 0.2, "C": 0.1}]
    discovery = {"A": 1, "B": 1, "C": 0}
    results = gxc.cross_check_features(shares_by_block, discovery, feature_ids=_FEATURES)
    by_feature = {r.feature: r for r in results}
    assert by_feature["C"].contradiction_flag is False
    assert by_feature["C"].above_uniform_baseline is False


def test_cross_check_features_gain_alto_com_descoberta_nao_e_contradicao() -> None:
    # gain acima do uniforme, mas a feature TEM descoberta no eixo 1 --
    # nao ha contradicao pra explicar (E10f_oi_change_z_48, n=1).
    shares_by_block = [{"A": 0.7, "B": 0.2, "C": 0.1}]
    discovery = {"A": 3, "B": 0, "C": 0}
    results = gxc.cross_check_features(shares_by_block, discovery, feature_ids=_FEATURES)
    by_feature = {r.feature: r for r in results}
    assert by_feature["A"].contradiction_flag is False


def test_cross_check_features_agrega_media_min_max() -> None:
    shares_by_block = [
        {"A": 0.1, "B": 0.3, "C": 0.6},
        {"A": 0.5, "B": 0.3, "C": 0.2},
        {"A": 0.9, "B": 0.05, "C": 0.05},
    ]
    discovery = {"A": 0, "B": 0, "C": 0}
    results = gxc.cross_check_features(shares_by_block, discovery, feature_ids=_FEATURES)
    by_feature = {r.feature: r for r in results}
    assert by_feature["A"].mean_gain_share == pytest.approx((0.1 + 0.5 + 0.9) / 3.0)
    assert by_feature["A"].min_gain_share == pytest.approx(0.1)
    assert by_feature["A"].max_gain_share == pytest.approx(0.9)
    assert by_feature["A"].n_blocks == 3
    assert by_feature["A"].uniform_baseline == pytest.approx(1.0 / 3.0)


def test_cross_check_features_levanta_com_shares_by_block_vazio() -> None:
    with pytest.raises(gxc.Eixo1GainCrossCheckError, match="vazio"):
        gxc.cross_check_features([], {"A": 0}, feature_ids=_FEATURES)


def test_cross_check_features_levanta_quando_feature_t1_ausente_da_descoberta() -> None:
    shares_by_block = [{"A": 0.5, "B": 0.3, "C": 0.2}]
    discovery = {"A": 0, "B": 0}  # "C" faltando de propósito
    with pytest.raises(gxc.Eixo1GainCrossCheckError, match="'C'"):
        gxc.cross_check_features(shares_by_block, discovery, feature_ids=_FEATURES)


# ============================================================================
# _extract_gain_blocks / _extract_discovery_by_feature (casca, mas puras --
# so transformam dict ja carregado, nao fazem IO por si)
# ============================================================================


def test_extract_gain_blocks_le_pooled_de_cada_variante_presente() -> None:
    alpha_full_analysis = [
        {
            "symbol": "BTCUSDT",
            "resolution": "R1",
            "variants": {
                "camada1": {"feature_gain": {"mean_gain": {"pooled": {"A": 1.0, "B": 2.0}}}},
                "camada0": {"feature_gain": {"mean_gain": {"pooled": {"A": 3.0, "B": 4.0}}}},
            },
        }
    ]
    blocks = gxc._extract_gain_blocks(alpha_full_analysis)
    assert blocks == [{"A": 1.0, "B": 2.0}, {"A": 3.0, "B": 4.0}]


def test_extract_gain_blocks_ignora_variante_sem_feature_gain() -> None:
    alpha_full_analysis = [
        {
            "symbol": "BTCUSDT",
            "resolution": "R1",
            "variants": {"camada1": {"overall": {}}},  # sem feature_gain persistido
        }
    ]
    with pytest.raises(gxc.Eixo1GainCrossCheckError, match="nenhum bloco"):
        gxc._extract_gain_blocks(alpha_full_analysis)


def test_extract_discovery_by_feature_le_por_feature() -> None:
    promotion_report = {
        "por_feature": [
            {"feature": "A", "n_symbols_discovery": 0},
            {"feature": "B", "n_symbols_discovery": 2},
        ]
    }
    assert gxc._extract_discovery_by_feature(promotion_report) == {"A": 0, "B": 2}
