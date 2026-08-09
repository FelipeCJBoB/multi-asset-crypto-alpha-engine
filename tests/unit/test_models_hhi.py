"""Testes de `src/models/hhi.py` — diagnóstico de concentração (§5.8)."""

from __future__ import annotations

import numpy as np
import pytest

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


# ============================================================================
# compute_effective_concentration — D1 da task (CLAUDE.md, achado do Sprint 4:
# E27f_cost_atr_ratio x C07_vol_pctile_expanding rho=-0,913, A13_dist_ema48_atr
# x B01_rsi_14 rho=0,947 — dois "slots" de gain quase redundantes).
# ============================================================================


def test_effective_concentration_dois_correlacionados_um_independente() -> None:
    """Caso canônico pedido pela task: 2 features PERFEITAMENTE
    correlacionadas (rho=1) + 1 independente, pesos iguais (gain uniforme) —
    deve dar N_eff perto de 2 (o par correlacionado só carrega ~1 fator de
    informação + a feature independente), bem longe de 3 (que seria o
    resultado se as 3 fossem tratadas como graus de liberdade independentes,
    o erro que o HHI nominal comete).

    Valor exato (participation ratio com pesos iguais 1/3, autovalores de C
    = {2, 0, 1} para o bloco perfeitamente correlacionado + a feature
    isolada): N_eff = (Σλ)²/Σλ² = 9/5 = 1,8 — muito mais perto de 2 que de
    3, verificado exatamente (não só por range) para travar a fórmula."""
    cols = ("a", "b", "c")
    gain = {"a": 1.0, "b": 1.0, "c": 1.0}  # pesos iguais -> 1/3 cada
    corr = np.array(
        [
            [1.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    result = hhi.compute_effective_concentration(corr, gain, cols)

    assert result.n_eff_factors.value == pytest.approx(1.8, abs=1e-9)
    assert 1.5 < result.n_eff_factors.value < 2.2  # perto de 2, longe de 3
    assert result.hhi_effective.value == pytest.approx(5.0 / 9.0, abs=1e-9)

    # o HHI NOMINAL sobre os mesmos pesos (1/3 cada) é uniforme = 0,333 —
    # o efetivo (0,556) é maior: a correlação faz a concentração real ficar
    # subestimada pelo nominal, exatamente o achado que motiva D1.
    nominal = hhi.compute_concentration(gain, cols)
    assert result.hhi_effective.value > nominal.hhi.value


def test_effective_concentration_sem_correlacao_reduz_ao_hhi_nominal() -> None:
    """Prova da docstring de `compute_effective_concentration`: quando a
    matriz de correlação é a identidade (features não-correlacionadas),
    `hhi_effective` == `hhi` nominal EXATAMENTE (o termo cruzado
    `Σ_{i!=j} w_i w_j rho_ij²` da derivação zera). Este é o caso degenerado
    em que os dois diagnósticos DEVEM coincidir — se não coincidirem, a
    fórmula está errada."""
    cols = ("a", "b", "c", "d")
    gain = {"a": 4.0, "b": 3.0, "c": 2.0, "d": 1.0}  # pesos desiguais de propósito
    identity = np.eye(4)

    effective = hhi.compute_effective_concentration(identity, gain, cols)
    nominal = hhi.compute_concentration(gain, cols)

    assert effective.hhi_effective.value == pytest.approx(nominal.hhi.value, abs=1e-9)


def test_effective_concentration_uma_feature_domina_o_gain() -> None:
    """Uma feature concentra 100% do gain, sem correlação com as outras —
    N_eff deve ser 1 (toda a massa num único eixo), hhi_effective == 1.0,
    mesmo comportamento do caso degenerado de `compute_concentration`."""
    cols = ("a", "b", "c")
    gain = {"a": 100.0}
    corr = np.eye(3)
    result = hhi.compute_effective_concentration(corr, gain, cols)
    assert result.n_eff_factors.value == pytest.approx(1.0, abs=1e-9)
    assert result.hhi_effective.value == pytest.approx(1.0, abs=1e-9)


def test_effective_concentration_pesos_somam_um_no_subconjunto() -> None:
    cols = ("a", "b", "c")
    gain = {"a": 3.0, "b": 1.0}  # "c" ausente -> share 0.0, mas ainda no denominador
    corr = np.eye(3)
    result = hhi.compute_effective_concentration(corr, gain, cols)
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert result.weights["c"] == pytest.approx(0.0, abs=1e-9)
    assert result.weights["a"] == pytest.approx(0.75, abs=1e-9)


def test_effective_concentration_total_gain_zero_cai_para_peso_uniforme() -> None:
    """`total_gain <= 0` no subconjunto (nenhuma feature recebeu gain) —
    mesma disciplina de `compute_concentration` (branch `total_gain <= 0`):
    produz um valor DEFINIDO (peso uniforme), não `NaN`."""
    cols = ("a", "b")
    corr = np.eye(2)
    result = hhi.compute_effective_concentration(corr, {}, cols)
    assert result.weights == {"a": pytest.approx(0.5), "b": pytest.approx(0.5)}
    assert result.n_eff_factors.value == pytest.approx(2.0, abs=1e-9)
    assert result.hhi_effective.value == pytest.approx(0.5, abs=1e-9)


def test_effective_concentration_all_columns_vazio_marca_invalido() -> None:
    result = hhi.compute_effective_concentration(np.zeros((0, 0)), {}, ())
    assert result.hhi_effective.valid is False
    assert result.n_eff_factors.valid is False
    assert result.weights == {}
    assert result.eigenvalues == ()


def test_effective_concentration_shape_incompativel_levanta_value_error() -> None:
    cols = ("a", "b", "c")
    gain = dict.fromkeys(cols, 1.0)
    corr_errada = np.eye(2)  # 2x2 para 3 colunas
    with pytest.raises(ValueError):
        hhi.compute_effective_concentration(corr_errada, gain, cols)


def test_effective_concentration_nan_por_variancia_zero_nao_quebra() -> None:
    """Feature constante no fold produz NaN em `np.corrcoef` (variância
    zero) — `compute_effective_concentration` sanitiza para 0.0 fora da
    diagonal / 1.0 na diagonal em vez de propagar NaN para o autovalor."""
    cols = ("a", "b")
    gain = {"a": 1.0, "b": 1.0}
    corr_com_nan = np.array([[1.0, float("nan")], [float("nan"), 1.0]])
    result = hhi.compute_effective_concentration(corr_com_nan, gain, cols)
    assert np.isfinite(result.hhi_effective.value)
    assert np.isfinite(result.n_eff_factors.value)
    # NaN sanitizado -> 0.0 fora da diagonal -> equivalente a features
    # não-correlacionadas -> N_eff == 2 (== n_features, sem redundância).
    assert result.n_eff_factors.value == pytest.approx(2.0, abs=1e-9)


def test_effective_concentration_campos_metric_unit_e_source() -> None:
    cols = ("a", "b")
    gain = {"a": 1.0, "b": 1.0}
    corr = np.eye(2)
    result = hhi.compute_effective_concentration(corr, gain, cols, source="fold3::long")
    assert result.hhi_effective.unit == Unit.RATIO
    assert result.n_eff_factors.unit == Unit.COUNT
    assert result.hhi_effective.source == "fold3::long"
    assert result.n_eff_factors.source == "fold3::long"
    assert result.hhi_effective.n == 2
    assert result.hhi_effective.n_semantics == "features"
