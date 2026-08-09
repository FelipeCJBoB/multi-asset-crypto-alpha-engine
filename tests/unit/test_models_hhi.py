"""Testes de `src/models/hhi.py` — diagnóstico de concentração (§5.8)."""

from __future__ import annotations

from src.models import hhi


def test_hhi_uniforme_com_10_features() -> None:
    """HHI de importância uniforme entre 10 features == 0,10 (texto literal
    do §5.8: 'com 10 features, HHI uniforme = 0,10')."""
    cols = tuple(f"f{i}" for i in range(10))
    gain = dict.fromkeys(cols, 1.0)
    result = hhi.compute_concentration(gain, cols)
    assert abs(result.hhi - 0.10) < 1e-9
    assert abs(result.max_share - 0.10) < 1e-9
    assert result.n_features_over_1pct == 10


def test_hhi_uma_feature_domina() -> None:
    """Uma feature com 100% do ganho — HHI == 1.0, max_share == 1.0."""
    cols = ("a", "b", "c")
    gain = {"a": 100.0}
    result = hhi.compute_concentration(gain, cols)
    assert abs(result.hhi - 1.0) < 1e-9
    assert abs(result.max_share - 1.0) < 1e-9
    assert result.shares["b"] == 0.0
    assert result.shares["c"] == 0.0


def test_hhi_colunas_ausentes_do_dict_viram_share_zero() -> None:
    """Coluna sem entrada em `gain_by_column` (booster nunca dividiu nela)
    entra no denominador do HHI com share 0.0, não é omitida."""
    cols = ("used", "never_used")
    gain = {"used": 5.0}
    result = hhi.compute_concentration(gain, cols)
    assert result.shares["never_used"] == 0.0
    assert abs(result.hhi - 1.0) < 1e-9  # toda a massa em "used"


def test_hhi_gain_total_zero_nao_quebra() -> None:
    cols = ("a", "b")
    result = hhi.compute_concentration({}, cols)
    assert result.hhi == 0.0
    assert result.max_share == 0.0
    assert result.n_features_over_1pct == 0


def test_hhi_gate_3_4_thresholds() -> None:
    """§5.8: HHI < 0,25, maior share < 0,30, >= 6 features com share > 1% —
    verificado sobre um caso realista de 14 colunas (10 T1 + 4 dummy de
    regime) com concentração moderada, batendo com o padrão medido no
    Sprint 8 (mean_hhi ~ 0,11, ver `experiments/alpha_layer1_report.json`)."""
    cols = tuple(f"f{i}" for i in range(14))
    gain = {c: 1.0 for c in cols[:10]} | {cols[10]: 0.5}
    result = hhi.compute_concentration(gain, cols)
    assert result.hhi < 0.25
    assert result.max_share < 0.30
    assert result.n_features_over_1pct >= 6
