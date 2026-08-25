"""Testes do núcleo de `ordering_fragility` (`AG-246`).

Todos sintéticos e com resposta conhecida a priori — o ponto deste módulo é
decidir se uma ordenação é ruído, então ele próprio não pode ter um núcleo
validado por inspeção do resultado que ele produz.
"""

from __future__ import annotations

import math

import pytest

from src.analysis.ordering_fragility import (
    kendall_tau_b,
    log_ratio_ci,
    separation_ratio,
    sigma_from_range,
)


# ---------------------------------------------------------------------------
# log_ratio_ci — IC de razão de proporções (delta method)
# ---------------------------------------------------------------------------


def test_log_ratio_ci_razao_unitaria_nao_exclui_um() -> None:
    """Duas proporções idênticas: razão 1, IC obrigatoriamente contém 1."""
    ci = log_ratio_ci(100, 1000, 100, 1000)
    assert ci is not None
    assert ci.point == pytest.approx(1.0)
    assert ci.ci_low < 1.0 < ci.ci_high
    assert not ci.excludes_one


def test_log_ratio_ci_e_simetrico_em_log_nao_em_nivel() -> None:
    """A propriedade que justifica construir o IC em log: o ponto é a média
    GEOMÉTRICA dos limites, não a aritmética. Se alguém "simplificar" para um
    IC simétrico em nível, este teste quebra."""
    ci = log_ratio_ci(200, 1000, 100, 1000)
    assert ci is not None
    assert math.sqrt(ci.ci_low * ci.ci_high) == pytest.approx(ci.point, rel=1e-9)
    media_aritmetica = (ci.ci_low + ci.ci_high) / 2
    assert media_aritmetica > ci.point  # assimetria real, não arredondamento


def test_log_ratio_ci_amostra_grande_com_efeito_exclui_um() -> None:
    """20% contra 10% com n grande é inequívoco."""
    ci = log_ratio_ci(2000, 10000, 1000, 10000)
    assert ci is not None
    assert ci.point == pytest.approx(2.0)
    assert ci.excludes_one
    assert ci.ci_low > 1.0


def test_log_ratio_ci_mesma_razao_amostra_menor_pode_nao_excluir() -> None:
    """MESMA razão pontual, n 100x menor -> IC alarga e o efeito deixa de ser
    distinguível. É exatamente o mecanismo que o módulo existe para expor:
    estimativa pontual idêntica, conclusão oposta."""
    grande = log_ratio_ci(2000, 10000, 1000, 10000)
    pequena = log_ratio_ci(20, 100, 10, 100)
    assert grande is not None and pequena is not None
    assert grande.point == pytest.approx(pequena.point)
    assert grande.excludes_one
    assert pequena.log_se > grande.log_se


@pytest.mark.parametrize(
    "args",
    [(0, 100, 10, 100), (10, 100, 0, 100), (10, 0, 10, 100), (101, 100, 10, 100)],
)
def test_log_ratio_ci_devolve_none_em_entrada_degenerada(args: tuple[int, ...]) -> None:
    """Contagem zero, n zero ou k>n: o log não existe. Devolve None em vez de
    aplicar correção de continuidade por conta própria."""
    assert log_ratio_ci(*args) is None


# ---------------------------------------------------------------------------
# sigma_from_range
# ---------------------------------------------------------------------------


def test_sigma_from_range_usa_d2_tabelado() -> None:
    assert sigma_from_range(3.078, 10) == pytest.approx(1.0)
    assert sigma_from_range(2.326, 5) == pytest.approx(1.0)


def test_sigma_from_range_levanta_para_n_fora_da_tabela() -> None:
    """Não interpola -- inventaria precisão que a tabela não tem (B23)."""
    with pytest.raises(ValueError, match="d2 não tabelado"):
        sigma_from_range(1.0, 50)


def test_sigma_from_range_rejeita_range_negativo() -> None:
    with pytest.raises(ValueError, match="range negativo"):
        sigma_from_range(-1.0, 10)


# ---------------------------------------------------------------------------
# separation_ratio
# ---------------------------------------------------------------------------


def test_separation_ratio_alto_quando_itens_bem_separados() -> None:
    """Médias distantes, erros pequenos -> ordenação carrega informação."""
    assert separation_ratio([0.0, 10.0, 20.0], [0.1, 0.1, 0.1]) > 50


def test_separation_ratio_perto_de_um_quando_spread_e_do_tamanho_do_erro() -> None:
    """O caso que o módulo existe para detectar: os itens 'diferem', mas por
    uma distância da ordem do erro com que foram medidos."""
    sr = separation_ratio([0.0, 1.0, 2.0], [1.0, 1.0, 1.0])
    assert 0.5 < sr < 1.5


def test_separation_ratio_nan_com_menos_de_dois_itens() -> None:
    assert math.isnan(separation_ratio([1.0], [0.1]))
    assert math.isnan(separation_ratio([1.0, 2.0], [0.1]))


# ---------------------------------------------------------------------------
# kendall_tau_b
# ---------------------------------------------------------------------------


def test_kendall_tau_concordancia_perfeita() -> None:
    assert kendall_tau_b([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]) == pytest.approx(1.0)


def test_kendall_tau_inversao_perfeita() -> None:
    """O caso observado entre R1 e R3 na geometria: a ordem se inverte."""
    assert kendall_tau_b([1.0, 2.0, 3.0, 4.0], [40.0, 30.0, 20.0, 10.0]) == pytest.approx(-1.0)


def test_kendall_tau_trata_empates_sem_estourar() -> None:
    tau = kendall_tau_b([1.0, 1.0, 2.0], [5.0, 5.0, 9.0])
    assert not math.isnan(tau)
    assert tau == pytest.approx(1.0)


def test_kendall_tau_todos_empatados_devolve_nan() -> None:
    """Sem nenhum par ordenável o denominador é zero -- NaN, nunca 0.0, que
    seria confundido com 'independentes'."""
    assert math.isnan(kendall_tau_b([1.0, 1.0, 1.0], [2.0, 2.0, 2.0]))


def test_kendall_tau_nan_com_tamanhos_diferentes() -> None:
    assert math.isnan(kendall_tau_b([1.0, 2.0, 3.0], [1.0, 2.0]))
