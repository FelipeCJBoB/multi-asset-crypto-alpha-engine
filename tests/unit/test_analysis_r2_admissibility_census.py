"""Testes de `src/analysis/r2_admissibility_census.py` — censo de
admissibilidade R2 por linha (ADR-005 §13 v2, `§13.16.3`).

Todo o núcleo é puro (Idioma A, `CLAUDE.md` §Núcleo funcional): recebe
arrays em memória e devolve dado em memória. Nenhum teste aqui toca em
disco — não há `_skip_if_*`, não há marcador `integration`.

Quatro blocos:

1. **Aritmética verificável à mão.** Geometria simétrica com números
   redondos, em que `R2`, o breakeven e a razão `custo/stop` têm resposta
   fechada. Se a fórmula divergir, o teste diz de quanto.
2. **Simetria entre lados.** `side=+1` (SL abaixo da entrada) e `side=-1`
   (SL acima) precisam produzir o MESMO censo sobre a mesma geometria
   espelhada — é o que `stop_fraction`/`gain_fraction` prometem ao usar
   `abs`, e o motivo pelo qual o módulo não tem um ramo por lado.
3. **Fronteira de R2.** `custo == ratio * stop` **passa** (a restrição é
   `<=`, `CLAUDE.md` §0.2). Testado exatamente no ponto, não perto dele.
4. **Degenerescência falha alto.** `stop == 0` e `custo >= ganho` levantam
   `ValueError` com contexto, em vez de produzir `inf`/`NaN` silencioso —
   mesma disciplina de `apply_weights` (`src/labels/weights.py`).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.analysis import r2_admissibility_census as census

# Geometria de teste: entrada 100, TP/SL a 1% (simétrico), custo de 10 bps
# ida-e-volta. Então: stop = 0,01; custo = 0,001; custo/stop = 0,10.
# Com `cost_stop_ratio_max = 0,20`: 0,10 <= 0,20 -> PASSA em R2.
# breakeven = (0,01 + 0,001) / ((0,01 - 0,001) + (0,01 + 0,001)) = 0,011/0,020 = 0,55
_ENTRY = 100.0
_TP_LONG = 101.0
_SL_LONG = 99.0
_COST_BPS_LADO = 5.0  # 5 + 5 = 10 bps ida-e-volta
_RATIO = 0.20


def _arr(value: float, n: int = 4) -> census.FloatArray:
    return np.full(n, value, dtype=np.float64)


def _censo_long(**over: float) -> census.R2CellCensus:
    return census.census_from_arrays(
        symbol="TESTUSDT",
        resolution_id="R1",
        side=1,
        entry_price=_arr(over.get("entry", _ENTRY)),
        tp_price=_arr(over.get("tp", _TP_LONG)),
        sl_price=_arr(over.get("sl", _SL_LONG)),
        cost_entry_bps=_arr(over.get("cost_bps", _COST_BPS_LADO)),
        cost_exit_bps=_arr(over.get("cost_bps", _COST_BPS_LADO)),
        cost_stop_ratio_max=over.get("ratio", _RATIO),
    )


# ============================================================================
# 1. Aritmética verificável à mão
# ============================================================================


def test_censo_reproduz_a_aritmetica_fechada_da_geometria_simetrica() -> None:
    c = _censo_long()
    assert c.n_linhas == 4
    assert c.n_viola_r2 == 0
    assert c.frac_viola_r2 == pytest.approx(0.0)
    assert c.payoff_simetrico is True
    # custo/stop = 0,001/0,01 = 0,10 em toda linha
    assert c.cost_over_stop_q["p50"] == pytest.approx(0.10)
    # breakeven = 0,011/0,020 = 0,55
    assert c.breakeven_q["p50"] == pytest.approx(0.55)
    assert c.breakeven_admissivel_q["p50"] == pytest.approx(0.55)


def test_sob_payoff_simetrico_o_breakeven_bate_com_a_identidade_do_docstring() -> None:
    """`breakeven = 0,5 + custo/(2*stop)` só vale sob `ganho == stop`. O
    módulo NÃO usa essa identidade (usa a fórmula geral); este teste
    confirma que as duas coincidem onde a identidade se aplica — é o que
    autoriza a docstring a citá-la."""
    c = _censo_long()
    custo, stop = 0.001, 0.01
    assert c.breakeven_q["p50"] == pytest.approx(0.5 + custo / (2 * stop))


def test_geometria_assimetrica_diverge_da_identidade_e_a_formula_geral_vence() -> None:
    """TP a 2%, SL a 1%: `ganho != stop`, a identidade deixa de valer e
    `payoff_simetrico` precisa reportar `False` em vez de mentir."""
    c = _censo_long(tp=102.0)
    assert c.payoff_simetrico is False
    # geral: (0,01 + 0,001) / ((0,02 - 0,001) + (0,01 + 0,001)) = 0,011/0,030
    assert c.breakeven_q["p50"] == pytest.approx(0.011 / 0.030)
    # a identidade daria 0,55 — confirmando que ela NÃO foi usada
    assert c.breakeven_q["p50"] != pytest.approx(0.55)


# ============================================================================
# 2. Simetria entre lados
# ============================================================================


def test_long_e_short_espelhados_produzem_censo_identico() -> None:
    """`side=-1` tem TP abaixo e SL acima da entrada (verificado contra
    `labels.parquet`). Como as duas grandezas econômicas são módulos de
    diferença, o censo precisa ser idêntico — se não for, há um ramo por
    lado escondido em algum lugar."""
    longo = _censo_long()
    curto = census.census_from_arrays(
        symbol="TESTUSDT",
        resolution_id="R1",
        side=-1,
        entry_price=_arr(_ENTRY),
        tp_price=_arr(_SL_LONG),  # espelhado
        sl_price=_arr(_TP_LONG),  # espelhado
        cost_entry_bps=_arr(_COST_BPS_LADO),
        cost_exit_bps=_arr(_COST_BPS_LADO),
        cost_stop_ratio_max=_RATIO,
    )
    assert curto.n_viola_r2 == longo.n_viola_r2
    assert curto.breakeven_q == longo.breakeven_q
    assert curto.cost_over_stop_q == longo.cost_over_stop_q
    assert curto.side == -1 and longo.side == 1


# ============================================================================
# 3. Fronteira de R2 — a restrição é `<=`, não `<`
# ============================================================================


def test_custo_exatamente_no_teto_de_r2_PASSA() -> None:
    """`custo == ratio * stop` satisfaz `custo <= ratio * stop`. Testado no
    ponto exato: stop = 1%, ratio = 0,20 -> teto de custo = 20 bps, ou seja
    10 bps por lado."""
    c = _censo_long(cost_bps=10.0)  # 10 + 10 = 20 bps = 0,002 = 0,20 * 0,01
    assert c.cost_over_stop_q["p50"] == pytest.approx(_RATIO)
    assert c.n_viola_r2 == 0, "a fronteira precisa PASSAR (R2 é <=), não violar"


def test_um_bps_acima_do_teto_de_r2_VIOLA() -> None:
    c = _censo_long(cost_bps=10.05)
    assert c.n_viola_r2 == c.n_linhas


def test_mascara_de_violacao_separa_as_linhas_certas() -> None:
    """Metade das linhas com stop grande (passa) e metade com stop pequeno
    (viola) — confere `frac_viola_r2` e que `breakeven_admissivel_q` olha
    SÓ para as que passam."""
    entry = np.full(4, 100.0)
    # duas linhas com SL a 1% (passa), duas com SL a 0,2% (viola: 0,001/0,002 = 0,5)
    sl = np.array([99.0, 99.0, 99.8, 99.8])
    tp = np.array([101.0, 101.0, 100.2, 100.2])
    c = census.census_from_arrays(
        symbol="TESTUSDT",
        resolution_id="R1",
        side=1,
        entry_price=entry,
        tp_price=tp,
        sl_price=sl,
        cost_entry_bps=_arr(_COST_BPS_LADO),
        cost_exit_bps=_arr(_COST_BPS_LADO),
        cost_stop_ratio_max=_RATIO,
    )
    assert c.n_viola_r2 == 2
    assert c.frac_viola_r2 == pytest.approx(0.5)
    # entre as admissíveis, todo breakeven é 0,55 (as duas linhas de stop 1%)
    assert c.breakeven_admissivel_q["p01"] == pytest.approx(0.55)
    assert c.breakeven_admissivel_q["p99"] == pytest.approx(0.55)
    # na população TODA, a mediana está entre 0,55 e o breakeven das ruins
    assert c.breakeven_q["p99"] > c.breakeven_admissivel_q["p99"]


# ============================================================================
# 4. Degenerescência falha alto
# ============================================================================


def test_stop_zero_levanta_em_vez_de_produzir_razao_infinita() -> None:
    with pytest.raises(ValueError, match="stop <= 0"):
        _censo_long(sl=_ENTRY)


def test_breakeven_com_custo_maior_que_o_ganho_levanta_em_vez_de_devolver_p_maior_que_1() -> None:
    """A função de CÁLCULO falha alto: se `ganho <= custo`, não existe `p`
    em [0,1] que zere `E[r]`.

    **Este teste pegou um defeito real na primeira versão da guarda**
    (2026-08-26): ela validava o DENOMINADOR (`g_tp + g_sl > 0`), condição
    fraca demais. Com ganho 5 bps / stop 5 bps / custo 60 bps o denominador
    dá `+0,001`, a guarda passava, e o breakeven saía **6,5** — uma
    "probabilidade" maior que 1, entregue sem erro."""
    gain = np.array([5e-4], dtype=np.float64)
    stop = np.array([5e-4], dtype=np.float64)
    cost = np.array([6e-3], dtype=np.float64)
    assert (gain - cost) + (stop + cost) > 0, "o denominador é positivo — a guarda antiga passava"
    with pytest.raises(ValueError, match="geometria degenerada"):
        census.breakeven_probability(gain, stop, cost)


def test_censo_CONTA_a_linha_impossivel_em_vez_de_abortar_a_celula() -> None:
    """O CENSO não pode abortar por causa dela — contar patologia é o
    trabalho dele. Achado real: existem 177 linhas assim nas 15 células de
    produção (0,006%), concentradas em SOLUSDT/R1-R2. Se esta função
    levantasse, a célula inteira ficaria sem censo por causa de 0,006%."""
    entry = np.full(4, 100.0)
    # 3 linhas normais (TP/SL a 1%) + 1 impossível (TP/SL a 5 bps, custo 60 bps)
    tp = np.array([101.0, 101.0, 101.0, 100.05])
    sl = np.array([99.0, 99.0, 99.0, 99.95])
    cost_bps = np.array([5.0, 5.0, 5.0, 30.0])
    c = census.census_from_arrays(
        symbol="TESTUSDT",
        resolution_id="R1",
        side=1,
        entry_price=entry,
        tp_price=tp,
        sl_price=sl,
        cost_entry_bps=cost_bps,
        cost_exit_bps=cost_bps,
        cost_stop_ratio_max=_RATIO,
    )
    assert c.n_linhas == 4
    assert c.n_tp_nao_cobre_custo == 1
    assert c.frac_tp_nao_cobre_custo == pytest.approx(0.25)
    # a linha impossível VIOLA R2 por construção (custo/stop = 12 >> 0,20)
    assert c.n_viola_r2 == 1
    # e fica FORA dos quantis de breakeven — as 3 restantes dão 0,55 exato
    assert c.breakeven_q["p50"] == pytest.approx(0.55)
    assert c.breakeven_q["p99"] == pytest.approx(0.55)
    assert c.breakeven_admissivel_q["p50"] == pytest.approx(0.55)


def test_celula_vazia_devolve_nan_em_vez_de_estourar() -> None:
    """Uma célula sem linha de um lado não é erro (pode acontecer numa
    janela recortada) — os quantis viram `NaN`, que é o valor honesto."""
    vazio = np.zeros(0, dtype=np.float64)
    c = census.census_from_arrays(
        symbol="TESTUSDT",
        resolution_id="R1",
        side=1,
        entry_price=vazio,
        tp_price=vazio,
        sl_price=vazio,
        cost_entry_bps=vazio,
        cost_exit_bps=vazio,
        cost_stop_ratio_max=_RATIO,
    )
    assert c.n_linhas == 0
    assert c.n_viola_r2 == 0
    assert math.isnan(c.frac_viola_r2)
    assert math.isnan(c.breakeven_q["p50"])


# ============================================================================
# 5. Funções elementares do núcleo, isoladas
# ============================================================================


def test_cost_fraction_converte_bps_para_fracao() -> None:
    out = census.cost_fraction(_arr(2.0, 1), _arr(5.0, 1))
    assert out[0] == pytest.approx(7e-4)


def test_viola_r2_e_a_restricao_literal_do_claude_md() -> None:
    cost = np.array([0.0019, 0.0020, 0.0021], dtype=np.float64)
    stop = np.full(3, 0.01, dtype=np.float64)
    mask = census.viola_r2(cost, stop, cost_stop_ratio_max=0.20)
    assert mask.tolist() == [False, False, True]
