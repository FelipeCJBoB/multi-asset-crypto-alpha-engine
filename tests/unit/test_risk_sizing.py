"""Testes de `src/risk/sizing.py` — o cálculo de sizing quantizado (§8.2).

Casos numéricos REAIS do PRD (§8.3, tabela "Controle 9 explicado"), não
inventados — `equity=US$196,85` (capital do projeto), `mark_price=US$64.940`
(`unit_notional_usd: 64,94` citado em §0.2), `step_size=0,001`.

**Achado deste Sprint, medido e documentado, não escondido:** reconstruindo a
tabela linha a linha com `floor_to_step` (o algoritmo que §8.2 e a própria
task mandam usar), só as linhas de stop 0,30%/0,50%/1,50% batem exatamente
com "unidades"/"N real"/"risco real"/"erro" da tabela. As linhas de stop
0,41%/0,80%/2,00% só reproduzem se "unidades" for computado por
ARREDONDAMENTO PARA O MAIS PRÓXIMO (`round(qty_raw/step_size)`), não por
floor — ex.: stop 0,80% dá `qty_raw/step = 1,8945`; a tabela mostra 2
unidades (consistente com round-nearest), `floor_to_step` dá 1 (consistente
com floor). Isso é uma INCONSISTÊNCIA da própria tabela ilustrativa do PRD
contra a fórmula que o PRD declara three parágrafos acima dela (§8.2:
"`qty = floor_to_step(...)`") — não um bug deste código. Resolvido a favor
de `floor_to_step` (mandado duas vezes: pelo §8.2 do PRD e pela instrução
explícita da task), por ser também o lado seguro (round-nearest pode
ARREDONDAR PARA CIMA e assumir MAIS risco que o pretendido — exatamente o
tipo de erro silencioso que R1/R2 existem para prevenir). Ver
`test_stop_2pct_floor_rejeita_em_vez_de_arredondar_para_cima` abaixo para o
caso mais nítido dessa divergência, documentado como teste, não como
comentário solto."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.exchange.filters import Filters
from src.risk.sizing import SizingResult, ZeroStopDistanceError, compute_sizing

_T0 = datetime(2026, 8, 8, 14, 30, tzinfo=UTC)
_MARK_PRICE = Decimal("64940")
_EQUITY = Decimal("196.85")  # capital do projeto, §0.1


def _make_filters(*, step_size: str = "0.001", min_notional: str = "50") -> Filters:
    return Filters(
        symbol="BTCUSDT",
        snapshot_date=_T0.date(),
        is_reconstructed=False,
        status="TRADING",
        tick_size=Decimal("0.10"),
        min_price=Decimal("556.80"),
        max_price=Decimal("4529764"),
        step_size=Decimal(step_size),
        min_qty=Decimal(step_size),
        max_qty=Decimal("1000"),
        market_step_size=Decimal(step_size),
        market_min_qty=Decimal(step_size),
        market_max_qty=Decimal("1000"),
        min_notional=Decimal(min_notional),
        max_num_orders=200,
        price_precision=2,
        quantity_precision=3,
        multiplier_up=Decimal("1.05"),
        multiplier_down=Decimal("0.95"),
    )


def _atr_pct_for_stop(stop_pct: Decimal) -> Decimal:
    """`stop_pct = sl_atr_mult x atr_pct` (§8.2 passo 2); `sl_atr_mult=1,5`
    vem de `constants.yaml`. Resolve o `atr_pct` de entrada que reproduz um
    `stop_pct` alvo, para testar contra a tabela do PRD (que tabula por
    stop, não por atr_pct)."""
    return stop_pct / Decimal("1.5")


# ============================================================================
# Caso âncora do PRD — stop 0,50% (citado literalmente na task)
# ============================================================================


def test_stop_0_50pct_bate_exatamente_com_a_tabela_do_prd() -> None:
    """§8.3: stop 0,50% -> N exigido $196,8 -> 3 unidades -> N real $194,8 ->
    risco real 0,495%, erro -1,0%."""
    filters = _make_filters()
    result = compute_sizing(
        t0=_T0,
        equity=_EQUITY,
        atr_pct=_atr_pct_for_stop(Decimal("0.005")),
        mark_price=_MARK_PRICE,
        filters=filters,
    )

    assert result.stop_pct.quantize(Decimal("0.0001")) == Decimal("0.0050")
    assert result.notional_req == Decimal("196.85")  # risk_usd(0,98425)/stop_pct(0,005)
    assert result.qty == Decimal("0.003")  # 3 unidades
    assert result.notional_real == Decimal("194.820")
    assert (result.risk_real / result.equity * 100).quantize(Decimal("0.001")) == Decimal("0.495")
    quant_error_signed = (result.notional_real - result.notional_req) / result.notional_req
    assert (quant_error_signed * 100).quantize(Decimal("0.1")) == Decimal("-1.0")


# ============================================================================
# Linhas adicionais da tabela que TAMBÉM reproduzem sob floor (0,30% e 1,50%)
# ============================================================================


def test_stop_0_30pct_bate_com_a_tabela_do_prd() -> None:
    """§8.3: stop 0,30% -> N exigido $328,1 -> 5 unidades -> N real $324,7 ->
    risco real 0,495%, erro -1,0%."""
    filters = _make_filters()
    result = compute_sizing(
        t0=_T0,
        equity=_EQUITY,
        atr_pct=_atr_pct_for_stop(Decimal("0.003")),
        mark_price=_MARK_PRICE,
        filters=filters,
    )
    assert result.qty == Decimal("0.005")  # 5 unidades
    assert result.notional_real == Decimal("324.700")
    assert (result.risk_real / result.equity * 100).quantize(Decimal("0.001")) == Decimal("0.495")


def test_stop_1_50pct_bate_com_a_tabela_do_prd() -> None:
    """§8.3: stop 1,50% -> N exigido $65,6 -> 1 unidade -> N real $64,9 ->
    risco real 0,495%, erro -1,0%."""
    filters = _make_filters()
    result = compute_sizing(
        t0=_T0,
        equity=_EQUITY,
        atr_pct=_atr_pct_for_stop(Decimal("0.015")),
        mark_price=_MARK_PRICE,
        filters=filters,
    )
    assert result.qty == Decimal("0.001")  # 1 unidade
    assert result.notional_real == Decimal("64.940")
    assert (result.risk_real / result.equity * 100).quantize(Decimal("0.001")) == Decimal("0.495")


# ============================================================================
# Divergência documentada: stop 2,00% — a tabela do PRD mostra "1 unidade"
# (consistente com ARREDONDAR pra cima 0,7578 -> 1), floor_to_step (o
# algoritmo mandado por §8.2 e pela task) dá 0 unidades — corretamente
# rejeitável por BELOW_MIN_QTY em vez de assumir 31,9% mais risco que o
# pretendido (o próprio "erro" que a tabela do PRD marca com "✗").
# ============================================================================


def test_stop_2pct_floor_rejeita_em_vez_de_arredondar_para_cima() -> None:
    filters = _make_filters()
    result = compute_sizing(
        t0=_T0,
        equity=_EQUITY,
        atr_pct=_atr_pct_for_stop(Decimal("0.02")),
        mark_price=_MARK_PRICE,
        filters=filters,
    )
    # qty_raw/step_size ~= 0,7578 — menos de 1 step inteiro.
    assert result.qty_raw < filters.step_size
    assert result.qty == Decimal("0")  # floor_to_step: nunca arredonda pra cima
    assert result.notional_real == Decimal("0")
    # a tabela do PRD, lida como "1 unidade", implicaria notional_real=$64,94
    # e risco_real/equity=0,660% (+31,9% acima do exigido) — floor evita
    # silenciosamente assumir esse excesso de risco.


# ============================================================================
# Passos intermediários e invariantes (§8.7)
# ============================================================================


def test_passo_1_risk_usd_igual_equity_vezes_risk_per_trade() -> None:
    filters = _make_filters()
    result = compute_sizing(
        t0=_T0, equity=Decimal("1000"), atr_pct=Decimal("0.003"),
        mark_price=_MARK_PRICE, filters=filters,
    )
    assert result.risk_usd == Decimal("1000") * Decimal("0.005")  # risk_per_trade = 0,005


def test_passo_2_stop_pct_igual_sl_atr_mult_vezes_atr_pct() -> None:
    filters = _make_filters()
    atr_pct = Decimal("0.002")
    result = compute_sizing(
        t0=_T0, equity=_EQUITY, atr_pct=atr_pct, mark_price=_MARK_PRICE, filters=filters
    )
    assert result.stop_pct == Decimal("1.5") * atr_pct  # sl_atr_mult = 1,5


def test_invariante_qty_e_multiplo_exato_do_step_size() -> None:
    filters = _make_filters()
    result = compute_sizing(
        t0=_T0, equity=_EQUITY, atr_pct=Decimal("0.0033333333333333333333333333"),
        mark_price=_MARK_PRICE, filters=filters,
    )
    steps = result.qty / filters.step_size
    assert steps == steps.to_integral_value()  # §8.7: qty % step_size == 0


def test_invariante_notional_real_maior_ou_igual_min_notional() -> None:
    filters = _make_filters(min_notional="50")
    result = compute_sizing(
        t0=_T0, equity=_EQUITY, atr_pct=_atr_pct_for_stop(Decimal("0.005")),
        mark_price=_MARK_PRICE, filters=filters,
    )
    assert result.notional_real >= filters.min_notional


def test_leverage_eff_e_notional_real_sobre_equity() -> None:
    filters = _make_filters()
    result = compute_sizing(
        t0=_T0, equity=_EQUITY, atr_pct=_atr_pct_for_stop(Decimal("0.005")),
        mark_price=_MARK_PRICE, filters=filters,
    )
    assert result.leverage_eff == result.notional_real / result.equity


def test_unit_notional_e_step_size_vezes_mark_price() -> None:
    filters = _make_filters()
    result = compute_sizing(
        t0=_T0, equity=_EQUITY, atr_pct=Decimal("0.003"), mark_price=_MARK_PRICE, filters=filters
    )
    assert result.unit_notional == filters.step_size * _MARK_PRICE
    assert result.unit_notional == Decimal("64.940")  # citado em §0.2: unit_notional_usd = 64,94


def test_quant_error_zero_quando_quantizacao_e_exata() -> None:
    """Quando `notional_req` já cai exatamente num múltiplo de `unit_notional`,
    `quant_error` é 0 — caso degenerado, sem arredondamento algum. Construído
    para fechar exato: `equity=150`, `atr_pct=0,01` -> `stop_pct=0,015` ->
    `risk_usd=0,75` -> `notional_req=50`; `mark_price=1000`, `step_size=0,01`
    -> `unit_notional=10` -> `qty_raw=0,05` já é múltiplo exato do step."""
    filters = _make_filters(step_size="0.01")
    result = compute_sizing(
        t0=_T0, equity=Decimal("150"), atr_pct=Decimal("0.01"), mark_price=Decimal("1000"),
        filters=filters,
    )
    assert result.notional_req == Decimal("50")
    assert result.qty == Decimal("0.05")
    assert result.notional_real == Decimal("50")
    assert result.quant_error == Decimal("0")


# ============================================================================
# Erros de entrada
# ============================================================================


def test_atr_pct_zero_levanta_zero_stop_distance_error() -> None:
    filters = _make_filters()
    with pytest.raises(ZeroStopDistanceError):
        compute_sizing(
            t0=_T0, equity=_EQUITY, atr_pct=Decimal("0"), mark_price=_MARK_PRICE, filters=filters
        )


def test_sizing_result_e_frozen() -> None:
    filters = _make_filters()
    result = compute_sizing(
        t0=_T0, equity=_EQUITY, atr_pct=Decimal("0.003"), mark_price=_MARK_PRICE, filters=filters
    )
    with pytest.raises(AttributeError):
        result.qty = Decimal("999")  # type: ignore[misc]
    assert isinstance(result, SizingResult)
