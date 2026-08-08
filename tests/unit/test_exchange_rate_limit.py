"""Testes de src/exchange/rate_limit.py — fila de prioridade P0 > P1 > P2 > P3
e reserva de 30% para execução (§9.4)."""

from __future__ import annotations

from src.exchange.rate_limit import Budget, Priority, RateLimitManager, priority_of


def _manager(
    *,
    ip_weight_limit: int = 100,
    order_count_limit_10s: int = 100,
    order_count_limit_1m: int = 100,
    reserve_pct: float = 0.30,
) -> RateLimitManager:
    return RateLimitManager(
        ip_weight_limit=ip_weight_limit,
        order_count_limit_10s=order_count_limit_10s,
        order_count_limit_1m=order_count_limit_1m,
        reserve_pct=reserve_pct,
    )


def test_priority_of_mapeia_conforme_prd() -> None:
    assert priority_of("cancel_order") is Priority.P0
    assert priority_of("reconcile") is Priority.P0
    assert priority_of("close_position") is Priority.P0
    assert priority_of("create_order") is Priority.P1
    assert priority_of("query_order") is Priority.P1
    assert priority_of("account_info") is Priority.P2
    assert priority_of("position_risk") is Priority.P2
    assert priority_of("backfill") is Priority.P3
    assert priority_of("research") is Priority.P3
    # tipo desconhecido nunca furta prioridade de execução
    assert priority_of("chamada_desconhecida") is Priority.P3


def test_budget_reserva_30_por_cento_para_execucao() -> None:
    budget = Budget(limit=100, reserve_pct=0.30)
    assert budget.cap_for(Priority.P0) == 100
    assert budget.cap_for(Priority.P1) == 100
    assert budget.cap_for(Priority.P2) == 70
    assert budget.cap_for(Priority.P3) == 70

    budget.used = 65
    # 65+10=75 > 70 (reserva) x 65+10=75 <= 100 (execução usa o teto cheio)
    assert budget.can_admit(Priority.P2, 10) is False
    assert budget.can_admit(Priority.P0, 10) is True


def test_fila_prioriza_p0_sobre_p1_p2_p3_sob_orcamento_apertado() -> None:
    manager = _manager()

    # ordem de submissão deliberadamente invertida (menor prioridade primeiro)
    manager.enqueue("research", weight=50)  # P3
    manager.enqueue("account_info", weight=30)  # P2
    manager.enqueue("create_order", weight=50)  # P1 — também consome order_count
    manager.enqueue("cancel_order", weight=10)  # P0 — também consome order_count

    admitted, deferred = manager.process_queue()

    assert admitted == ["cancel_order", "create_order"]
    assert deferred == ["account_info", "research"]
    # a reserva de 30% barrou os P2/P3 mesmo sobrando banda bruta (100-60=40 > 30)
    assert manager.ip_weight.used == 60


def test_reserva_de_30_por_cento_bloqueia_p2_mesmo_com_banda_bruta_livre() -> None:
    manager = _manager()
    manager.enqueue("account_info", weight=75)  # P2, teto efetivo = 70

    admitted, deferred = manager.process_queue()

    assert admitted == []
    assert deferred == ["account_info"]


def test_fifo_dentro_da_mesma_prioridade() -> None:
    manager = _manager(ip_weight_limit=1000, order_count_limit_10s=1000, order_count_limit_1m=1000)
    manager.enqueue("account_info", weight=1)
    manager.enqueue("position_risk", weight=1)

    admitted, _deferred = manager.process_queue()

    assert admitted == ["account_info", "position_risk"]  # ambas P2 — ordem de chegada


def test_order_count_e_ip_weight_sao_orcamentos_independentes() -> None:
    """Regra 2 (§9.4): esgotar order_count NÃO impede uma chamada que só
    consome peso de IP (ex.: account_info não conta contra ORDERS)."""
    manager = _manager(ip_weight_limit=1000, order_count_limit_10s=1, order_count_limit_1m=1)

    manager.enqueue("cancel_order", weight=1)  # esgota order_count (limite=1)
    manager.process_queue()

    manager.enqueue("cancel_order", weight=1)  # order_count esgotado -> deve ser adiada
    manager.enqueue("account_info", weight=1)  # só peso de IP -> deve passar
    admitted, deferred = manager.process_queue()

    assert admitted == ["account_info"]
    assert deferred == ["cancel_order"]


def test_update_from_headers_e_fonte_de_verdade_sobrescreve_reserva_local() -> None:
    manager = _manager()
    manager.enqueue("cancel_order", weight=10)
    manager.process_queue()
    assert manager.ip_weight.used == 10  # reserva otimista local

    manager.update_from_headers({"X-MBX-USED-WEIGHT-1M": "42"})
    # header sobrescreve — nunca confia só na própria contagem
    assert manager.ip_weight.used == 42


def test_update_from_headers_e_case_insensitive_e_atualiza_os_tres_orcamentos() -> None:
    manager = _manager()
    manager.update_from_headers(
        {
            "x-mbx-used-weight-1m": "11",
            "X-MBX-ORDER-COUNT-10S": "2",
            "x-mbx-order-count-1m": "3",
        }
    )
    assert manager.ip_weight.used == 11
    assert manager.order_count_10s.used == 2
    assert manager.order_count_1m.used == 3


def test_pending_reflete_fila_apos_deferimento() -> None:
    manager = _manager(ip_weight_limit=10, order_count_limit_10s=10, order_count_limit_1m=10)
    manager.enqueue("research", weight=100)  # nunca cabe
    manager.process_queue()
    assert manager.pending() == ["research"]
