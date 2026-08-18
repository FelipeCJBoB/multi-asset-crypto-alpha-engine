"""Testes de `src/validation/regime_utility.py` — M4 (`PRD_V4_1.md` §3.2).
Casos sintéticos com resultado calculável à mão, mesmo padrão de
`test_validation_volatility_walkforward.py` (M1).

`anova_by_group` usa Welch's ANOVA F desde 2026-08-18 (decisão do Manager,
achado de auditoria `audit_engineering`: `scipy.stats.f_oneway` clássica
assume homocedasticidade, violada por construção no M4 -- ver docstring de
`anova_by_group`). Os testes de comparação direta Welch-vs-clássica
(`test_anova_welch_diverge_da_classica_sob_heterocedasticidade_desbalanceada`/
`test_anova_welch_e_classica_convergem_sob_homocedasticidade`) importam
`scipy.stats.f_oneway` só pra comparação -- não é o método em produção."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats as scipy_stats

from src.validation.regime_utility import (
    adjusted_rand,
    anova_by_group,
    regime_persistence,
)

# ============================================================================
# anova_by_group
# ============================================================================


def test_anova_grupos_bem_separados_da_f_alto_omega_alto_p_baixo() -> None:
    rng = np.random.default_rng(1)
    labels = np.concatenate([np.zeros(200, dtype=np.int64), np.ones(200, dtype=np.int64)])
    response = np.concatenate([rng.normal(-5.0, 0.5, 200), rng.normal(5.0, 0.5, 200)])
    result = anova_by_group(labels, response)
    assert result.f_stat > 100.0
    assert result.omega_squared > 0.8
    assert result.p_value < 1e-6
    assert result.k_groups == 2
    assert result.n == 400


def test_anova_grupos_identicos_da_f_baixo_omega_perto_de_zero() -> None:
    rng = np.random.default_rng(2)
    labels = np.concatenate([np.zeros(300, dtype=np.int64), np.ones(300, dtype=np.int64)])
    response = rng.normal(0.0, 1.0, 600)  # mesma distribuição pros 2 grupos
    result = anova_by_group(labels, response)
    assert result.omega_squared < 0.05
    assert result.p_value > 0.01


def test_anova_filtra_nan_da_response_antes_de_calcular() -> None:
    """Achado real desta sessão (troca pra Welch): o dado original deste
    teste (`[1.0, 1.0]`/`[5.0, 5.0]` pós-filtro) tinha variância EXATAMENTE
    0 nos 2 grupos -- inofensivo pra F clássica (só reduz a soma de
    quadrados dentro do grupo a 0, sem dividir por variância nenhuma), mas
    Welch pondera cada grupo por `n_i/var_i` -- `var_i=0` é divisão por
    zero literal, e o teste original NUNCA reparou porque só afirmava
    `result.n == 4`. Dado trocado aqui pra ter variância > 0 nos 2 grupos
    (preserva o propósito do teste -- filtro de NaN -- sem tropeçar no
    guard novo de variância 0, testado em separado abaixo)."""
    labels = np.array([0, 0, 0, 1, 1, 1], dtype=np.int64)
    response = np.array([1.0, np.nan, 1.2, 5.0, 5.3, np.nan], dtype=np.float64)
    result = anova_by_group(labels, response)
    assert result.n == 4  # 2 NaN filtrados
    assert np.isfinite(result.f_stat)
    assert np.isfinite(result.omega_squared)


def test_anova_levanta_value_error_grupo_com_menos_de_2_observacoes() -> None:
    """Achado real desta sessão: diferente da F clássica (só precisa da
    variância PARTILHADA/pooled, `n_total - k` graus de liberdade), Welch
    precisa da variância de CADA grupo (`ddof=1`, exige `n_i>=2`); sem este
    guard explícito, `statsmodels` devolve `NaN` silencioso com
    `RuntimeWarning` interno em vez de um erro claro."""
    labels = np.array([0, 1, 1, 1, 1, 1], dtype=np.int64)  # grupo 0 com só 1 obs
    response = np.array([1.0, 5.0, 5.1, 4.9, 5.2, 4.8], dtype=np.float64)
    with pytest.raises(ValueError, match=">=2 observações por grupo"):
        anova_by_group(labels, response)


def test_anova_levanta_value_error_grupo_com_variancia_zero() -> None:
    """Achado real desta sessão: Welch pondera cada grupo por `n_i/var_i` --
    um grupo com todas as observações idênticas (`var_i=0`) é divisão por
    zero literal, que `statsmodels` deixa passar como `NaN` silencioso
    (`RuntimeWarning: divide by zero`) em vez de erro -- mesma classe do
    guard de `n_i<2` acima, achada ao rodar a suíte pré-existente após a
    troca pra Welch (ver docstring de
    `test_anova_filtra_nan_da_response_antes_de_calcular`)."""
    labels = np.array([0, 0, 0, 1, 1, 1], dtype=np.int64)
    response = np.array([1.0, 1.0, 1.0, 5.0, 5.3, 4.8], dtype=np.float64)  # grupo 0 sem variância
    with pytest.raises(ValueError, match="variância 0"):
        anova_by_group(labels, response)


def test_anova_welch_diverge_da_classica_sob_heterocedasticidade_desbalanceada() -> None:
    """Prova que a troca pra Welch muda o comportamento de verdade, não só
    o nome da função por baixo (instrução explícita da task). Cenário
    desenhado pra ser exatamente o que a auditoria M4 apontou: grupos
    DESBALANCEADOS (n muito diferente) com variância bem diferente --
    homocedasticidade violada por construção, mesma situação de
    "ortogonalidade contra volatilidade" (regimes de vol diferem em
    variância por definição). Sob desbalanceamento + heterocedasticidade,
    ANOVA F clássica infla o F-stat (a variância pequena do grupo grande
    domina o MSW pooled, tornando a diferença de média do grupo pequeno
    "artificialmente" significativa) -- Welch corrige isso.

    Medido nesta sessão (seed fixa, determinístico): F clássico ~43 com
    p~1e-10 (states "achado altamente significativo"); Welch F~1.5 com
    p~0.23 (states "sem evidência de diferença de média") -- p-valor
    literalmente do lado oposto de um alfa=0.05 entre os 2 métodos, exemplo
    concreto do porquê a F clássica é enganosa aqui."""
    rng = np.random.default_rng(42)
    group_a = rng.normal(0.0, 0.2, 800)  # grande, variância baixa
    group_b = rng.normal(0.15, 3.0, 25)  # pequeno, variância alta, média perto

    labels = np.concatenate(
        [np.zeros(800, dtype=np.int64), np.ones(25, dtype=np.int64)]
    )
    response = np.concatenate([group_a, group_b])

    f_classic, p_classic = scipy_stats.f_oneway(group_a, group_b)
    result = anova_by_group(labels, response)

    # F clássico "acha" separação forte e espúria; Welch não.
    assert f_classic > 20.0
    assert p_classic < 1e-6
    assert result.f_stat < 5.0
    assert result.p_value > 0.05
    # Confirma que são medidas DIFERENTES, não coincidência de arredondamento.
    assert abs(result.f_stat - f_classic) > 10.0
    assert result.k_groups == 2
    assert result.n == 825


def test_anova_welch_e_classica_convergem_sob_homocedasticidade() -> None:
    """Contraparte do teste acima: quando a suposição de variância igual
    NÃO é violada (grupos balanceados, mesma variância), Welch's F deveria
    ficar perto da F clássica -- mesmo poder estatístico nesse regime,
    não uma penalidade sistemática por usar o método mais robusto."""
    rng = np.random.default_rng(7)
    group_a = rng.normal(-1.0, 1.0, 150)
    group_b = rng.normal(0.0, 1.0, 150)
    group_c = rng.normal(1.0, 1.0, 150)

    labels = np.concatenate(
        [
            np.zeros(150, dtype=np.int64),
            np.ones(150, dtype=np.int64),
            np.full(150, 2, dtype=np.int64),
        ]
    )
    response = np.concatenate([group_a, group_b, group_c])

    f_classic, p_classic = scipy_stats.f_oneway(group_a, group_b, group_c)
    result = anova_by_group(labels, response)

    assert p_classic < 1e-6
    assert result.p_value < 1e-6
    # F-stats próximos (< 10% de diferença relativa) sob homocedasticidade real.
    assert abs(result.f_stat - f_classic) / f_classic < 0.10
    assert result.omega_squared > 0.3  # efeito grande nos 2 métodos


def test_anova_levanta_value_error_shape_diferente() -> None:
    with pytest.raises(ValueError, match="mesmo shape"):
        anova_by_group(np.array([0, 1]), np.array([1.0, 2.0, 3.0]))


def test_anova_levanta_value_error_menos_de_2_grupos() -> None:
    labels = np.zeros(10, dtype=np.int64)
    response = np.arange(10, dtype=np.float64)
    with pytest.raises(ValueError, match=">=2 grupos"):
        anova_by_group(labels, response)


def test_anova_levanta_value_error_n_insuficiente() -> None:
    labels = np.array([0, 1], dtype=np.int64)
    response = np.array([1.0, 2.0], dtype=np.float64)
    with pytest.raises(ValueError, match="graus de liberdade"):
        anova_by_group(labels, response)


# ============================================================================
# regime_persistence
# ============================================================================


def test_persistence_segmentos_conhecidos_a_mao() -> None:
    # 3 segmentos: [0,0,0,0] [1,1] [0,0,0] -> durações 4, 2, 3
    labels = np.array([0, 0, 0, 0, 1, 1, 0, 0, 0], dtype=np.int64)
    result = regime_persistence(labels)
    assert result.n_segments == 3
    assert result.median_duration_bars == pytest.approx(3.0)  # mediana de [4,2,3]
    # 2 trocas em 8 transições possíveis (n-1=8)
    assert result.switch_rate == pytest.approx(2.0 / 8.0)


def test_persistence_serie_constante_1_segmento_switch_rate_zero() -> None:
    labels = np.zeros(50, dtype=np.int64)
    result = regime_persistence(labels)
    assert result.n_segments == 1
    assert result.median_duration_bars == pytest.approx(50.0)
    assert result.switch_rate == pytest.approx(0.0)


def test_persistence_single_bar_switch_rate_zero() -> None:
    result = regime_persistence(np.array([0], dtype=np.int64))
    assert result.n_segments == 1
    assert result.switch_rate == 0.0


def test_persistence_levanta_value_error_vazio() -> None:
    with pytest.raises(ValueError, match="vazio"):
        regime_persistence(np.array([], dtype=np.int64))


# ============================================================================
# adjusted_rand
# ============================================================================


def test_adjusted_rand_particoes_identicas_e_1() -> None:
    labels = np.array([0, 0, 1, 1, 2, 2, 0, 1], dtype=np.int64)
    assert adjusted_rand(labels, labels) == pytest.approx(1.0)


def test_adjusted_rand_particoes_identicas_com_rotulo_permutado_e_1() -> None:
    """ARI é invariante a permutação de rótulo -- mesma propriedade que
    justifica reusar sklearn em vez de comparar rótulo bruto diretamente."""
    labels_a = np.array([0, 0, 1, 1, 2, 2], dtype=np.int64)
    labels_b = np.array([2, 2, 0, 0, 1, 1], dtype=np.int64)  # mesma partição, outros nomes
    assert adjusted_rand(labels_a, labels_b) == pytest.approx(1.0)


def test_adjusted_rand_levanta_value_error_shape_diferente() -> None:
    with pytest.raises(ValueError, match="mesmo shape"):
        adjusted_rand(np.array([0, 1, 2]), np.array([0, 1]))
