"""Testes de `src/models/hhi.py` — diagnóstico de concentração (§5.8)."""

from __future__ import annotations

from src.core.metric import Unit
from src.models import hhi


def test_hhi_uniforme_com_10_features() -> None:
    """HHI de importância uniforme entre 10 features == 0,10 (texto literal
    do §5.8: 'com 10 features, HHI uniforme = 0,10')."""
    cols = tuple(f"f{i}" for i in range(10))
    gain = dict.fromkeys(cols, 1.0)
    result = hhi.compute_concentration(gain, cols)
    assert abs(result.hhi.value - 0.10) < 1e-9
    assert abs(result.max_share.value - 0.10) < 1e-9
    assert result.n_features_over_1pct == 10


def test_hhi_campos_metric_tem_unit_ratio_n_e_source_corretos() -> None:
    cols = tuple(f"f{i}" for i in range(10))
    gain = dict.fromkeys(cols, 1.0)
    result = hhi.compute_concentration(gain, cols)
    assert result.hhi.unit == Unit.RATIO
    assert result.max_share.unit == Unit.RATIO
    assert result.hhi.n == 10
    assert result.hhi.n_semantics == "features"
    assert result.hhi.source == "models.hhi.compute_concentration"
    assert result.hhi.valid is True


def test_hhi_aceita_source_override_sem_quebrar_chamada_posicional() -> None:
    """`source` é kwarg com default — chamada posicional existente em
    `src.models.alpha` (`compute_concentration(gain_by_column, DESIGN_COLUMNS)`)
    continua funcionando; quem tem contexto melhor pode sobrescrever."""
    cols = ("a", "b")
    gain = {"a": 1.0}
    result = hhi.compute_concentration(gain, cols, source="alpha_c1_v1::fold3::long")
    assert result.hhi.source == "alpha_c1_v1::fold3::long"


def test_hhi_uma_feature_domina() -> None:
    """Uma feature com 100% do ganho — HHI == 1.0, max_share == 1.0."""
    cols = ("a", "b", "c")
    gain = {"a": 100.0}
    result = hhi.compute_concentration(gain, cols)
    assert abs(result.hhi.value - 1.0) < 1e-9
    assert abs(result.max_share.value - 1.0) < 1e-9
    assert result.shares["b"] == 0.0
    assert result.shares["c"] == 0.0


def test_hhi_colunas_ausentes_do_dict_viram_share_zero() -> None:
    """Coluna sem entrada em `gain_by_column` (booster nunca dividiu nela)
    entra no denominador do HHI com share 0.0, não é omitida."""
    cols = ("used", "never_used")
    gain = {"used": 5.0}
    result = hhi.compute_concentration(gain, cols)
    assert result.shares["never_used"] == 0.0
    assert abs(result.hhi.value - 1.0) < 1e-9  # toda a massa em "used"


def test_hhi_gain_total_zero_nao_quebra() -> None:
    cols = ("a", "b")
    result = hhi.compute_concentration({}, cols)
    assert result.hhi.value == 0.0
    assert result.max_share.value == 0.0
    assert result.n_features_over_1pct == 0
    assert result.hhi.valid is True  # total_gain==0 é um valor legítimo (0.0), não inválido


def test_hhi_all_columns_vazio_marca_invalido() -> None:
    result = hhi.compute_concentration({}, ())
    assert result.hhi.valid is False
    assert result.hhi.n == 0
    assert result.shares == {}


def test_hhi_gate_3_4_thresholds() -> None:
    """§5.8: HHI < 0,25, maior share < 0,30, >= 6 features com share > 1% —
    verificado sobre um caso realista de 14 colunas (10 T1 + 4 dummy de
    regime) com concentração moderada, batendo com o padrão medido no
    Sprint 8 (mean_hhi ~ 0,11, ver `experiments/alpha_layer1_report.json`)."""
    cols = tuple(f"f{i}" for i in range(14))
    gain = dict.fromkeys(cols[:10], 1.0) | {cols[10]: 0.5}
    result = hhi.compute_concentration(gain, cols)
    assert result.hhi.value < 0.25
    assert result.max_share.value < 0.30
    assert result.n_features_over_1pct >= 6
