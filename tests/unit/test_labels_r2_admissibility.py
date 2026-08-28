"""Testes de `src.labels.r2_admissibility` -- núcleo puro de R2 (`CLAUDE.md`
§0.2), movido de `src.analysis.r2_admissibility_census` em 2026-08-27
(handoff de `src/models/`, `AG-296`/`AG-297`) pra ficar acessível também a
`src.models.dataset.side_subset` (`models/` não pode importar `analysis/`).

`tests/unit/test_analysis_r2_admissibility_census.py` continua cobrindo
estas mesmas funções via o reexport (`census.cost_fraction`/`census.
viola_r2`) e o resto do censo (`gain_fraction`/`breakeven_probability`,
que não migraram). Este arquivo cobre a fórmula na origem, sem depender
do reexport."""

from __future__ import annotations

import numpy as np
import pytest

from src.labels import r2_admissibility as r2

# Mesma geometria de teste de test_analysis_r2_admissibility_census.py:
# entrada 100, stop a 1%, custo de 10 bps ida-e-volta -> custo/stop = 0,10.
_ENTRY = np.full(3, 100.0)
_SL = np.full(3, 99.0)
_COST_BPS = np.full(3, 5.0)  # 5 + 5 = 10 bps


def test_cost_fraction_soma_entry_e_exit_e_converte_bps_para_fracao() -> None:
    out = r2.cost_fraction(np.full(2, 5.0), np.full(2, 5.0))
    assert out == pytest.approx(np.full(2, 0.001))


def test_cost_fraction_funding_bps_none_preserva_bit_exato() -> None:
    """`AG-249` Problema A -- default `funding_bps=None` não pode mudar
    nenhum resultado de caller existente (ex. `side_subset`)."""
    sem_funding = r2.cost_fraction(np.full(2, 5.0), np.full(2, 5.0))
    com_none_explicito = r2.cost_fraction(np.full(2, 5.0), np.full(2, 5.0), None)
    assert sem_funding == pytest.approx(com_none_explicito)


def test_cost_fraction_funding_bps_positivo_soma_ao_custo() -> None:
    out = r2.cost_fraction(np.full(1, 5.0), np.full(1, 5.0), np.full(1, 2.0))
    # 5 + 5 + |2| = 12 bps -> 0.0012
    assert out == pytest.approx(np.full(1, 0.0012))


def test_cost_fraction_funding_bps_negativo_soma_valor_absoluto_nao_subtrai() -> None:
    """Definição operacional de `AG-249` Problema A: funding entra por
    `abs()`, nunca com sinal -- funding "a favor" (negativo aqui) não pode
    reduzir o custo abaixo do que `cost_entry_bps + cost_exit_bps` já é."""
    sem_funding = r2.cost_fraction(np.full(1, 5.0), np.full(1, 5.0))
    com_funding_negativo = r2.cost_fraction(np.full(1, 5.0), np.full(1, 5.0), np.full(1, -2.0))
    assert com_funding_negativo > sem_funding
    # 5 + 5 + |-2| = 12 bps -> 0.0012, igual ao caso positivo
    assert com_funding_negativo == pytest.approx(np.full(1, 0.0012))


def test_stop_fraction_e_o_modulo_da_distancia_relativa() -> None:
    out = r2.stop_fraction(_ENTRY, _SL)
    assert out == pytest.approx(np.full(3, 0.01))


def test_stop_fraction_e_simetrico_entre_sl_acima_e_abaixo() -> None:
    """`side=-1` tem SL ACIMA da entrada -- o módulo tem que dar a mesma
    grandeza que `side=+1` (SL abaixo), mesma geometria espelhada."""
    long_stop = r2.stop_fraction(np.full(1, 100.0), np.full(1, 99.0))
    short_stop = r2.stop_fraction(np.full(1, 100.0), np.full(1, 101.0))
    assert long_stop == pytest.approx(short_stop)


def test_viola_r2_fronteira_e_admissivel() -> None:
    """R2 é `<=`, não `<` (`CLAUDE.md` §0.2) -- custo == ratio*stop PASSA."""
    cost = r2.cost_fraction(_COST_BPS, _COST_BPS)  # 0,001
    stop = r2.stop_fraction(_ENTRY, _SL)  # 0,01
    # custo/stop = 0,10 -- ratio=0,10 é exatamente a fronteira
    mask = r2.viola_r2(cost, stop, cost_stop_ratio_max=0.10)
    assert not mask.any()


def test_viola_r2_acima_do_ratio_viola() -> None:
    cost = r2.cost_fraction(_COST_BPS, _COST_BPS)  # 0,001
    stop = r2.stop_fraction(_ENTRY, _SL)  # 0,01
    # custo/stop = 0,10 > ratio=0,05 -> viola
    mask = r2.viola_r2(cost, stop, cost_stop_ratio_max=0.05)
    assert mask.all()


def test_viola_r2_abaixo_do_ratio_nao_viola() -> None:
    cost = r2.cost_fraction(_COST_BPS, _COST_BPS)  # 0,001
    stop = r2.stop_fraction(_ENTRY, _SL)  # 0,01
    # custo/stop = 0,10 < ratio=0,20 -> não viola
    mask = r2.viola_r2(cost, stop, cost_stop_ratio_max=0.20)
    assert not mask.any()
