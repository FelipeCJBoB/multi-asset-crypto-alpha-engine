"""Testes de `src/risk/limits.py` — os 19 controles (§8.3 do V3.2 + #19 de
`AG-081`), cada um passando e falhando isoladamente, mais a orquestração
(`evaluate_all`): ordem fixa, parar no primeiro `FAIL`, `NOT_COMPUTABLE`
nunca bloqueia."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.exchange.filters import Filters
from src.risk import limits
from src.risk._constants import load_constant
from src.risk.kill_switch import SystemState
from src.risk.limits import ControlOutcome, RejectionReason, RiskEngineInputs, evaluate_all
from src.risk.sizing import SizingResult

_T0 = datetime(2026, 8, 8, 14, 30, tzinfo=UTC)


def _make_filters(
    *, min_qty: str = "0.001", min_notional: str = "50", step_size: str = "0.001"
) -> Filters:
    return Filters(
        symbol="BTCUSDT",
        snapshot_date=_T0.date(),
        is_reconstructed=False,
        status="TRADING",
        tick_size=Decimal("0.10"),
        min_price=Decimal("556.80"),
        max_price=Decimal("4529764"),
        step_size=Decimal(step_size),
        min_qty=Decimal(min_qty),
        max_qty=Decimal("1000"),
        market_step_size=Decimal(step_size),
        market_min_qty=Decimal(min_qty),
        market_max_qty=Decimal("1000"),
        min_notional=Decimal(min_notional),
        max_num_orders=200,
        price_precision=2,
        quantity_precision=3,
        multiplier_up=Decimal("1.05"),
        multiplier_down=Decimal("0.95"),
    )


def _make_sizing(**overrides: object) -> SizingResult:
    """Baseline consistente com a linha "stop 0,50%" da tabela §8.3: equity
    US$196,85, 3 unidades, notional_real=$194,82, risco_real/equity=0,495%.
    Cada teste sobrescreve só o(s) campo(s) que quer estressar."""
    defaults: dict[str, object] = {
        "t0": _T0,
        "equity": Decimal("196.85"),
        "risk_usd": Decimal("0.98425"),
        "atr_pct": Decimal("0.0033333333333333333333333333"),
        "stop_pct": Decimal("0.005"),
        "mark_price": Decimal("64940"),
        "notional_req": Decimal("196.85"),
        "qty_raw": Decimal("0.003031259624268555589775177087"),
        "qty": Decimal("0.003"),
        "notional_real": Decimal("194.820"),
        "risk_real": Decimal("0.9741000"),
        "quant_error": Decimal("0.01031242062484124968249936500"),
        "leverage_eff": Decimal("0.9896870078486410973075945644"),
        "unit_notional": Decimal("64.940"),
        "filters": _make_filters(),
    }
    defaults.update(overrides)
    return SizingResult(**defaults)  # type: ignore[arg-type]


# ============================================================================
# Controle 1 — regime tradeável
# ============================================================================


def test_control_01_passa_quando_regime_tradeable() -> None:
    """Candidato-agnóstico (2026-08-21, Fase C do plano `wise-exploring-
    panda.md`) -- `control_01_regime_tradeavel` recebe o `bool` já
    resolvido pelo builder de regime (baseline `R1..R4` via
    `TRADEABLE_REGIMES`, ou HMM via `is_stress_state`), nunca decodifica
    vocabulário aqui."""
    assert limits.control_01_regime_tradeavel(True) == ControlOutcome.PASS


def test_control_01_falha_quando_regime_nao_tradeable() -> None:
    assert limits.control_01_regime_tradeavel(False) == ControlOutcome.FAIL


# ============================================================================
# Controle 2 — estado do sistema
# ============================================================================


def test_control_02_passa_so_em_running() -> None:
    assert limits.control_02_estado_sistema(SystemState.RUNNING) == ControlOutcome.PASS


def test_control_02_falha_em_qualquer_outro_estado() -> None:
    for state in SystemState:
        if state == SystemState.RUNNING:
            continue
        assert limits.control_02_estado_sistema(state) == ControlOutcome.FAIL


# ============================================================================
# Controle 3 — kill switch
# ============================================================================


def test_control_03_passa_quando_inativo() -> None:
    assert limits.control_03_kill_switch(False) == ControlOutcome.PASS


def test_control_03_falha_quando_ativo() -> None:
    assert limits.control_03_kill_switch(True) == ControlOutcome.FAIL


# ============================================================================
# Controle 4 — reconciliação fresca
# ============================================================================


def test_control_04_passa_abaixo_do_limiar() -> None:
    max_age = float(load_constant("reconciliation_max_age_s"))
    assert limits.control_04_reconciliacao_fresca(max_age - 1) == ControlOutcome.PASS


def test_control_04_falha_no_limiar_e_acima() -> None:
    max_age = float(load_constant("reconciliation_max_age_s"))
    assert limits.control_04_reconciliacao_fresca(max_age) == ControlOutcome.FAIL
    assert limits.control_04_reconciliacao_fresca(max_age + 1) == ControlOutcome.FAIL


# ============================================================================
# Controle 5 — frescor de dados
# ============================================================================


def test_control_05_passa_quando_ambos_frescos() -> None:
    assert limits.control_05_frescor_dados(10.0, 1.0) == ControlOutcome.PASS


def test_control_05_falha_se_barra_velha() -> None:
    bar_max = float(load_constant("data_staleness_bar_max_s"))
    assert limits.control_05_frescor_dados(bar_max, 1.0) == ControlOutcome.FAIL


def test_control_05_falha_se_book_velho() -> None:
    book_max = float(load_constant("data_staleness_book_max_s"))
    assert limits.control_05_frescor_dados(10.0, book_max) == ControlOutcome.FAIL


# ============================================================================
# Controle 6 — quantidade mínima
# ============================================================================


def test_control_06_passa_no_exemplo_do_prd() -> None:
    assert limits.control_06_qty_minima(_make_sizing()) == ControlOutcome.PASS


def test_control_06_falha_abaixo_do_min_qty() -> None:
    sizing = _make_sizing(qty=Decimal("0.0005"), filters=_make_filters(min_qty="0.001"))
    assert limits.control_06_qty_minima(sizing) == ControlOutcome.FAIL


# ============================================================================
# Controle 7 — nocional mínimo
# ============================================================================


def test_control_07_passa_no_exemplo_do_prd() -> None:
    assert limits.control_07_notional_minimo(_make_sizing()) == ControlOutcome.PASS


def test_control_07_falha_abaixo_do_min_notional() -> None:
    sizing = _make_sizing(notional_real=Decimal("10"), filters=_make_filters(min_notional="50"))
    assert limits.control_07_notional_minimo(sizing) == ControlOutcome.FAIL


# ============================================================================
# Controle 8 — granularidade (3 x unit_notional)
# ============================================================================


def test_control_08_passa_no_limiar_exato_3x() -> None:
    # notional_real=194.82 == 3 * unit_notional(64.94) -- exatamente no limiar, >=.
    assert limits.control_08_granularidade(_make_sizing()) == ControlOutcome.PASS


def test_control_08_falha_com_2_unidades() -> None:
    sizing = _make_sizing(notional_real=Decimal("129.880"), qty=Decimal("0.002"))
    assert limits.control_08_granularidade(sizing) == ControlOutcome.FAIL


# ============================================================================
# Controle 9a — erro de quantização
# ============================================================================


def test_control_09a_passa_no_exemplo_do_prd() -> None:
    # quant_error ~= 0.0103 (1,03%), bem abaixo de quantization_tolerance (25%)
    assert limits.control_09a_erro_quantizacao(_make_sizing()) == ControlOutcome.PASS


def test_control_09a_falha_acima_da_tolerancia() -> None:
    tolerance = Decimal(str(load_constant("quantization_tolerance")))
    sizing = _make_sizing(quant_error=tolerance + Decimal("0.01"))
    assert limits.control_09a_erro_quantizacao(sizing) == ControlOutcome.FAIL


def test_control_09a_passa_exatamente_no_limiar() -> None:
    tolerance = Decimal(str(load_constant("quantization_tolerance")))
    sizing = _make_sizing(quant_error=tolerance)
    assert limits.control_09a_erro_quantizacao(sizing) == ControlOutcome.PASS


# ============================================================================
# Controle 9b — resolução de sizing (N_req/unit >= 2,0)
# ============================================================================


def test_control_09b_passa_no_exemplo_do_prd() -> None:
    # notional_req(196.85)/unit_notional(64.94) ~= 3,03 >= 2,0
    assert limits.control_09b_resolucao_sizing(_make_sizing()) == ControlOutcome.PASS


def test_control_09b_falha_no_caso_2h_do_prd() -> None:
    """§8.3: a 2h, N_req/unit ~= 1,14 — o caso que "passava por sorte" só com
    quant_error e motivou a separação 9a/9b."""
    sizing = _make_sizing(notional_req=Decimal("74.2716"), unit_notional=Decimal("64.94"))
    assert limits.control_09b_resolucao_sizing(sizing) == ControlOutcome.FAIL


def test_control_09b_passa_exatamente_em_2_0() -> None:
    sizing = _make_sizing(notional_req=Decimal("129.88"), unit_notional=Decimal("64.94"))
    assert limits.control_09b_resolucao_sizing(sizing) == ControlOutcome.PASS


# ============================================================================
# Controle 10 — risco real (risk_real/equity <= 0,006)
# ============================================================================


def test_control_10_passa_no_exemplo_do_prd() -> None:
    # risk_real/equity ~= 0,495% < 0,6%
    assert limits.control_10_risco_real(_make_sizing()) == ControlOutcome.PASS


def test_control_10_falha_acima_do_teto() -> None:
    sizing = _make_sizing(risk_real=Decimal("2.0"), equity=Decimal("196.85"))
    assert limits.control_10_risco_real(sizing) == ControlOutcome.FAIL


def test_control_10_falha_com_equity_negativo() -> None:
    """Achado de auditoria (`audit/division_guard_audit.md`): a guarda antiga
    era `equity == 0`, então `equity=-1` deixava `risk_real/equity` sair
    negativo e passar o teto trivialmente. Mesmo cenário de
    `test_k01_not_computable_com_equity_nao_positivo` em
    `test_risk_kill_switch.py`, adaptado ao tri-estado deste controle
    (`FAIL`, não `NOT_COMPUTABLE` — ver docstring de `control_10_risco_real`)."""
    sizing = _make_sizing(equity=Decimal("-1"))
    assert limits.control_10_risco_real(sizing) == ControlOutcome.FAIL


# ============================================================================
# Controle 11 — nocional máximo (leverage_eff <= max_notional_multiple)
# ============================================================================


def test_control_11_passa_no_exemplo_do_prd() -> None:
    assert limits.control_11_nocional_maximo(_make_sizing()) == ControlOutcome.PASS


def test_control_11_falha_acima_de_3x() -> None:
    sizing = _make_sizing(leverage_eff=Decimal("3.5"))
    assert limits.control_11_nocional_maximo(sizing) == ControlOutcome.FAIL


# ============================================================================
# Controle 12 — margem disponível
# ============================================================================


def test_control_12_passa_com_margem_folgada() -> None:
    sizing = _make_sizing()
    result = limits.control_12_margem_disponivel(sizing, im_required_usd=Decimal("25.98"))
    assert result == ControlOutcome.PASS


def test_control_12_falha_acima_de_60pct_equity() -> None:
    sizing = _make_sizing(equity=Decimal("196.85"))
    im_required = Decimal("0.60") * sizing.equity + Decimal("1")
    result = limits.control_12_margem_disponivel(sizing, im_required_usd=im_required)
    assert result == ControlOutcome.FAIL


# ============================================================================
# Controle 13 — orçamento de fees
# ============================================================================


def test_control_13_passa_sem_fees_acumuladas() -> None:
    sizing = _make_sizing()
    result = limits.control_13_orcamento_fees(sizing, fees_mtd_usd=Decimal("0"))
    assert result == ControlOutcome.PASS


def test_control_13_falha_quando_fees_ja_estouram_o_orcamento() -> None:
    sizing = _make_sizing()
    budget = Decimal(str(load_constant("fee_budget_monthly"))) * sizing.equity
    result = limits.control_13_orcamento_fees(sizing, fees_mtd_usd=budget + Decimal("1"))
    assert result == ControlOutcome.FAIL


def test_control_13_estimated_cost_bate_com_reconstrucao_independente() -> None:
    """Corrigido 2026-08-24 (AG-027 fechado de verdade) -- o exemplo original
    do PRD §8.5 (estimated_cost_usd=0,143) assumia 50/50 de qual barreira
    toca primeiro, premissa já refutada por medição real (42,06% pooled,
    `round_trip_cost_bps_maker_prob` em `constants.yaml`). Reconstrução
    manual mantida (mesma fórmula de `round_trip_cost_bps`, independente
    da implementação real) pra continuar validando `control_13_orcamento_
    fees` contra um cálculo isolado -- só o `half=0.5` hardcoded foi
    substituído pela constante medida real."""
    sizing = _make_sizing(notional_real=Decimal("259.76"), equity=Decimal("196.85"))
    # reconstrução manual do custo estimado, mesma fórmula de round_trip_cost_bps
    maker_fee = Decimal(str(load_constant("maker_fee")))
    taker_fee = Decimal(str(load_constant("taker_fee")))
    maker_prob = Decimal(str(load_constant("round_trip_cost_bps_maker_prob")))
    cost_bps = (maker_fee + maker_prob * maker_fee + (1 - maker_prob) * taker_fee) * Decimal(10000)
    estimated_cost_usd = sizing.notional_real * cost_bps / Decimal(10000)
    # AG-222 (2026-08-25) -- comparar contra a IMPLEMENTACAO real, nunca
    # contra um literal. A versao anterior fixava Decimal("0.149"), valor
    # derivado de maker_prob=0,4206; quando a constante foi remedida para
    # 0,4597 (geometria tp=sl=1,5 sob dollar bar) o teste quebrou apesar de
    # a formula continuar correta -- o literal era um numero DERIVADO
    # hardcoded, exatamente o padrao de dessincronizacao que AG-123
    # cataloga. Agora o teste valida o que a docstring promete: que a
    # reconstrucao independente bate com round_trip_cost_bps, seja qual for
    # o valor da constante.
    from src.features.groups.group_e import round_trip_cost_bps

    cost_bps_impl = Decimal(str(round_trip_cost_bps(float(maker_fee), float(taker_fee))))
    assert cost_bps.quantize(Decimal("0.000001")) == cost_bps_impl.quantize(Decimal("0.000001"))
    # sanidade de ordem de grandeza, independente do valor exato da constante:
    # o custo tem que ficar entre o extremo 100% maker e o extremo 100% taker
    piso = sizing.notional_real * (maker_fee + maker_fee) * Decimal(10000) / Decimal(10000)
    teto = sizing.notional_real * (maker_fee + taker_fee) * Decimal(10000) / Decimal(10000)
    assert piso <= estimated_cost_usd <= teto
    # e o controle passa com folga (fees_mtd=0, orçamento ~ $5,9)
    result = limits.control_13_orcamento_fees(sizing, fees_mtd_usd=Decimal("0"))
    assert result == ControlOutcome.PASS


# ============================================================================
# Controle 14 — perda diária
# ============================================================================


def test_control_14_passa_sem_perda() -> None:
    sizing = _make_sizing()
    result = limits.control_14_perda_diaria(sizing, daily_loss_usd=Decimal("0"))
    assert result == ControlOutcome.PASS


def test_control_14_falha_acima_de_2pct_equity() -> None:
    sizing = _make_sizing(equity=Decimal("196.85"))
    loss = Decimal("0.02") * sizing.equity + Decimal("0.01")
    assert limits.control_14_perda_diaria(sizing, daily_loss_usd=loss) == ControlOutcome.FAIL


# ============================================================================
# Controle 15 — drawdown do pico
# ============================================================================


def test_control_15_not_computable_sem_pico_estabelecido() -> None:
    sizing = _make_sizing()
    result = limits.control_15_max_drawdown(sizing, equity_peak_usd=Decimal("0"))
    assert result == ControlOutcome.NOT_COMPUTABLE


def test_control_15_passa_sem_drawdown() -> None:
    sizing = _make_sizing(equity=Decimal("200"))
    result = limits.control_15_max_drawdown(sizing, equity_peak_usd=Decimal("200"))
    assert result == ControlOutcome.PASS


def test_control_15_falha_acima_de_10pct_do_pico() -> None:
    sizing = _make_sizing(equity=Decimal("170"))
    result = limits.control_15_max_drawdown(sizing, equity_peak_usd=Decimal("200"))
    assert result == ControlOutcome.FAIL  # dd = 15% > 10%


# ============================================================================
# Controle 16 — perdas consecutivas
# ============================================================================


def test_control_16_passa_ate_o_limite() -> None:
    assert limits.control_16_perdas_consecutivas(0) == ControlOutcome.PASS
    assert limits.control_16_perdas_consecutivas(5) == ControlOutcome.PASS


def test_control_16_falha_acima_do_limite() -> None:
    assert limits.control_16_perdas_consecutivas(6) == ControlOutcome.FAIL


# ============================================================================
# Controle 17 — liquidez (spread quantil + depth NOT_COMPUTABLE)
# ============================================================================


def test_control_17_not_computable_sem_nenhum_dado() -> None:
    result = limits.control_17_liquidez(
        spread_bps=None, spread_history_bps=None, depth_20bps_usd=None, unit_notional=None
    )
    assert result == ControlOutcome.NOT_COMPUTABLE


def test_control_17_spread_acima_do_p95_falha_mesmo_com_depth_desconhecido() -> None:
    history = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0]
    result = limits.control_17_liquidez(
        spread_bps=Decimal("100"),  # muito acima de qualquer p95 desta amostra
        spread_history_bps=history,
        depth_20bps_usd=None,
        unit_notional=None,
    )
    assert result == ControlOutcome.FAIL  # FAIL domina, mesmo com depth NOT_COMPUTABLE


def test_control_17_spread_ok_mas_depth_desconhecido_e_not_computable() -> None:
    history = [1.0 + i * 0.1 for i in range(50)]
    result = limits.control_17_liquidez(
        spread_bps=Decimal("0.5"),  # bem abaixo do p95 desta amostra
        spread_history_bps=history,
        depth_20bps_usd=None,
        unit_notional=None,
    )
    assert result == ControlOutcome.NOT_COMPUTABLE


def test_control_17_passa_quando_spread_e_depth_ambos_ok() -> None:
    history = [1.0 + i * 0.1 for i in range(50)]
    result = limits.control_17_liquidez(
        spread_bps=Decimal("0.5"),
        spread_history_bps=history,
        depth_20bps_usd=Decimal("1000"),
        unit_notional=Decimal("64.94"),
    )
    assert result == ControlOutcome.PASS


def test_control_17_falha_se_depth_insuficiente_mesmo_com_spread_ok() -> None:
    history = [1.0 + i * 0.1 for i in range(50)]
    result = limits.control_17_liquidez(
        spread_bps=Decimal("0.5"),
        spread_history_bps=history,
        depth_20bps_usd=Decimal("1"),  # bem abaixo de 4x unit_notional
        unit_notional=Decimal("64.94"),
    )
    assert result == ControlOutcome.FAIL


# ============================================================================
# Controle 18 — janela de evento (sempre NOT_COMPUTABLE hoje)
# ============================================================================


def test_control_18_e_sempre_not_computable() -> None:
    assert limits.control_18_janela_evento() == ControlOutcome.NOT_COMPUTABLE


# ============================================================================
# Controle 19 — risco agregado por correlação (AG-081)
# ============================================================================


def test_control_19_not_computable_sem_nenhum_dado() -> None:
    result = limits.control_19_risco_agregado(position_risks=None, correlation_matrix=None)
    assert result == ControlOutcome.NOT_COMPUTABLE


def test_control_19_not_computable_com_position_risks_vazio() -> None:
    result = limits.control_19_risco_agregado(position_risks=[], correlation_matrix=[])
    assert result == ControlOutcome.NOT_COMPUTABLE


def test_control_19_not_computable_com_matriz_de_dimensao_incompativel() -> None:
    result = limits.control_19_risco_agregado(
        position_risks=[Decimal("0.005"), Decimal("0.005")],
        correlation_matrix=[[1.0, 0.91]],  # 1 linha para 2 posições -- malformado
    )
    assert result == ControlOutcome.NOT_COMPUTABLE


def test_control_19_uma_posicao_passa_sigma_agg_igual_ao_risco_unitario() -> None:
    # w=[0.005], Corr=[[1]] -> sigma_agg = 0.005, abaixo de aggregate_risk_max=0.01
    result = limits.control_19_risco_agregado(
        position_risks=[Decimal("0.005")], correlation_matrix=[[1.0]]
    )
    assert result == ControlOutcome.PASS


def test_control_19_cinco_posicoes_correlacionadas_rho_091_falha() -> None:
    """Reproduz a tabela do PRD_V4_1.md §5.3: 5 posições de risco unitário
    0,50% com rho=0,91 entre todos os pares -> sigma_agg ~= 2,408% (4,82x),
    acima de aggregate_risk_max=1,00%."""
    n = 5
    risk = Decimal("0.005")
    corr = [[1.0 if i == j else 0.91 for j in range(n)] for i in range(n)]
    result = limits.control_19_risco_agregado(
        position_risks=[risk] * n, correlation_matrix=corr
    )
    assert result == ControlOutcome.FAIL


def test_control_19_duas_posicoes_correlacionadas_rho_091_passa() -> None:
    """Mesma tabela do PRD: 2 posições -> sigma_agg ~= 0,977%, ainda abaixo
    de aggregate_risk_max=1,00% -- confirma o cap efetivo de 2 posições
    citado em §5.3 ('3 já violam')."""
    n = 2
    risk = Decimal("0.005")
    corr = [[1.0 if i == j else 0.91 for j in range(n)] for i in range(n)]
    result = limits.control_19_risco_agregado(
        position_risks=[risk] * n, correlation_matrix=corr
    )
    assert result == ControlOutcome.PASS


def test_control_19_tres_posicoes_correlacionadas_rho_091_falha() -> None:
    """§5.3: 'Três já violam' -- 3 posições -> sigma_agg ~= 1,454%, acima do
    limite de 1,00%."""
    n = 3
    risk = Decimal("0.005")
    corr = [[1.0 if i == j else 0.91 for j in range(n)] for i in range(n)]
    result = limits.control_19_risco_agregado(
        position_risks=[risk] * n, correlation_matrix=corr
    )
    assert result == ControlOutcome.FAIL


# ============================================================================
# Orquestração — evaluate_all
# ============================================================================


def _make_inputs(**overrides: object) -> RiskEngineInputs:
    defaults: dict[str, object] = {
        "regime_tradeable": True,
        "system_state": SystemState.RUNNING,
        "kill_switch_active": False,
        "reconciliation_age_s": 1.0,
        "bar_staleness_s": 1.0,
        "book_staleness_s": 1.0,
        "sizing": _make_sizing(),
        "im_required_usd": Decimal("25.98"),
        "fees_mtd_usd": Decimal("0"),
        "daily_loss_usd": Decimal("0"),
        "equity_peak_usd": Decimal("196.85"),
        "consecutive_losses": 0,
        # AG-431 -- o #19 e OBRIGATORIO (`CONTROLS_MANDATORY`): sem
        # `position_risks`/`correlation_matrix` ele devolve NOT_COMPUTABLE e
        # `evaluate_all` REJEITA. O caso base de um Risk Engine tem que ser
        # o conjunto COMPLETO de insumos -- 1 posicao candidata com risco
        # fracionario 0,005 e Corr=[[1,0]] da sigma_agg=0,005 <=
        # `aggregate_risk_max`=0,01 -> PASS. A ausencia desses dois campos
        # virou um caso de teste PROPRIO (ver
        # `test_evaluate_all_rejeita_quando_controle_obrigatorio_nao_computavel`).
        "position_risks": [0.005],
        "correlation_matrix": [[1.0]],
    }
    defaults.update(overrides)
    return RiskEngineInputs(**defaults)  # type: ignore[arg-type]


def test_evaluate_all_aprova_o_caso_base() -> None:
    decision = evaluate_all(_make_inputs())
    assert decision.approved is True
    assert decision.rejection_reason is None
    # controles 17 (spread/history None) e 18 (sempre) ficam NOT_COMPUTABLE
    # -- nenhum dos dois e obrigatorio, entao nao bloqueiam.
    assert "17" in decision.controls_not_computable
    assert "18" in decision.controls_not_computable
    # AG-431 -- o #19 agora PASSA de verdade (dado injetado), nao fica
    # NOT_COMPUTABLE como antes desta correcao.
    assert "19" in decision.controls_passed
    assert "19" not in decision.controls_not_computable
    assert decision.controls_evaluated[-1] == "19"  # rodou todos, nenhum FAIL


def test_evaluate_all_ignora_regime_tradeavel_false_controle_1_desligado() -> None:
    """Controle #1 desligado de `evaluate_all()` desde 2026-08-22
    (`AG-114`/`AG-118`, evidência negativa e definitiva de sinal
    econômico -- ver docstring de `control_01_regime_tradeavel`).
    `regime_tradeable=False` NÃO bloqueia mais a decisão -- o campo
    continua obrigatório em `RiskEngineInputs` (reversão futura barata),
    mas não é consultado no caminho de decisão real."""
    decision = evaluate_all(_make_inputs(regime_tradeable=False))
    assert decision.approved is True
    assert decision.rejection_reason is None
    assert "1" not in decision.controls_evaluated


def test_evaluate_all_para_no_primeiro_fail_kill_switch() -> None:
    decision = evaluate_all(_make_inputs(kill_switch_active=True))
    assert decision.approved is False
    assert decision.rejection_reason == RejectionReason.KILL_SWITCH_ACTIVE
    assert decision.controls_evaluated == ("2", "3")
    assert decision.controls_passed == ("2",)


def test_evaluate_all_rejeita_por_below_min_qty_apos_passar_controles_2_a_5() -> None:
    sizing = _make_sizing(qty=Decimal("0.0005"))
    decision = evaluate_all(_make_inputs(sizing=sizing))
    assert decision.approved is False
    assert decision.rejection_reason == RejectionReason.BELOW_MIN_QTY
    assert decision.controls_passed == ("2", "3", "4", "5")


def test_evaluate_all_not_computable_nao_obrigatorio_nao_impede_approved() -> None:
    """Controles 17/18 `NOT_COMPUTABLE` (sensores cuja fonte de dado ao vivo
    ainda não existe) continuam NÃO bloqueando — este é o comportamento
    deliberado e correto do módulo, preservado pelo AG-431."""
    decision = evaluate_all(_make_inputs())
    assert decision.approved is True
    assert set(decision.controls_not_computable) == {"17", "18"}


def test_evaluate_all_rejeita_quando_controle_obrigatorio_nao_computavel() -> None:
    """AG-431 (auditoria externa 2026-09-03, achado N1) — o #19 é o ÚNICO
    controle de nível PORTFOLIO (I4/§5.3: rho~0,91 entre os 5 ativos faz 5
    posições simultâneas entregarem 4,82x o risco unitário declarado). Antes
    desta correção ele era também o único que NUNCA era computável em
    produção, e `evaluate_all` seguia em frente aprovando — fail-open
    exatamente onde mora o risco de ruína. Agora rejeita.

    Este teste é o que trava a regressão: se alguém remover o #19 de
    `CONTROLS_MANDATORY`, ele quebra."""
    decision = evaluate_all(_make_inputs(position_risks=None, correlation_matrix=None))
    assert decision.approved is False
    assert decision.rejection_reason == RejectionReason.MANDATORY_CONTROL_NOT_COMPUTABLE
    assert "19" in decision.controls_not_computable
    # rejeitou NO #19, não antes -- todos os outros foram de fato avaliados
    assert decision.controls_evaluated[-1] == "19"


def test_evaluate_all_controle_obrigatorio_computavel_e_estourado_usa_razao_especifica() -> None:
    """Contraprova do teste acima: quando o #19 É computável e o risco
    agregado ESTOURA, o motivo tem que ser `AGGREGATE_RISK_LIMIT` (medi e
    estourou), nunca `MANDATORY_CONTROL_NOT_COMPUTABLE` (não consegui
    medir). São diagnósticos diferentes e não podem colapsar num só."""
    # 5 posições de risco 0,005 com rho=0,91 entre todas -> sigma_agg bem
    # acima de `aggregate_risk_max`=0,01 (é o cenário I4 do PRD).
    n = 5
    corr = [[1.0 if i == j else 0.91 for j in range(n)] for i in range(n)]
    decision = evaluate_all(_make_inputs(position_risks=[0.005] * n, correlation_matrix=corr))
    assert decision.approved is False
    assert decision.rejection_reason == RejectionReason.AGGREGATE_RISK_LIMIT
