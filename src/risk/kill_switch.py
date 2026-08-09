"""Kill Switch — §10.2 do PRD, os 13 gatilhos, e Estados do Sistema — §10.3.

**Achado do Sprint 9 (mesmo método do Sprint 5 para os gatilhos de stress —
medir/investigar antes de implementar, CLAUDE.md "meça antes de afirmar"):
dos 13 gatilhos, 5 são computáveis hoje com o que o repo tem; 8 são "sensor
pronto, sem fonte de dado real ainda"** — a lógica está implementada e
testada, mas o pipeline real (Sprint 12+ live) ainda não tem o processo que
alimenta o parâmetro, então o parâmetro chega `None` e a função devolve
`TriggerState.NOT_COMPUTABLE`, nunca um `False`/`NOT_TRIGGERED` silencioso.

| # | gatilho | hoje? | por quê (resumo — detalhe completo na docstring de cada `kNN_*`) |
|---|---|---|---|
| K01 | perda diária > 2% equity | **sim** | fórmula sobre estado injetado (mesmo padrão B17) |
| K02 | drawdown > 10% do pico | **sim** | idem, sobre `equity_peak_usd` injetado |
| K03 | perdas consecutivas > 5 | **sim** | contador inteiro injetado |
| K04 | desconexão exchange > 120s | não (hoje) | sem client WS live; ver `EventWatchdog` |
| K05 | divergência de posição crítica | não (hoje) | reconciliação (Sprint 14) não existe |
| K06 | ordem inesperada (`client_order_id` desconhecido) | não (hoje) | sem rastreio live |
| K07 | tempestade de erros de API (>10/60s) | não (hoje) | sem contador de erro ao vivo |
| K08 | corrupção de dado (Quality Gate falha em dado live) | não (hoje) | sem streaming |
| K09 | modelo indisponível | não (hoje) | Alpha real é Sprint 8, em paralelo |
| K10 | falha do Risk Engine (exceção não tratada) | não, meta-circular | ver função abaixo |
| K11 | execução `UNKNOWN` não resolvida em 120s | não (hoje) | sem estado de ordem live |
| K12 | `filters_hash` mudou e não revalidado | **sim** | REUSA `compute_filters_hash` (Sprint 5) |
| K13 | equity abaixo de US$150 | **sim** | fórmula direta — específico deste capital |

Cada gatilho é uma função pura, testável isoladamente, que devolve
`TriggerState` — REUSADO diretamente de `src.regime.stress` (não
reimplementado): a semântica tri-valorada (disparou / não disparou / não sei)
é EXATAMENTE a mesma nos dois módulos (ao contrário de `src.risk.limits`, que
usa um `Enum` próprio porque lá os polos são invertidos — PASS/FAIL versus
TRIGGERED/NOT_TRIGGERED). `NOT_COMPUTABLE` nunca conta como `TRIGGERED` na
composição de `evaluate_kill_switch` — mesma regra de `stress.py`.

**Sem retorno automático.** `evaluate_kill_switch` só pode levar o sistema
NA DIREÇÃO de `KillSwitchDecision.KILLED` — nunca de volta. O único caminho
de volta é `reset_kill_switch`, que EXIGE um `KillSwitchResetRecord`
(operador + motivo + timestamp) como parâmetro obrigatório: não existe
overload, default nem caminho de código que transicione de `KILLED` sem um
registro humano explícito (§10.2: "requer intervenção humana explícita, com
registro de quem, quando e por quê"). `reset_kill_switch` devolve sempre
`SystemState.PAUSED`, nunca `RUNNING` diretamente — o procedimento do PRD é
`diagnosticar -> reconciliar -> resetar contadores -> PAUSED -> observação de
1h -> RUNNING`; a transição final `PAUSED -> RUNNING` é operacional, fora do
escopo deste módulo (nenhuma lógica de "observação de 1h" existe aqui — seria
inventar um relógio que este módulo não tem como isolar/testar de forma pura).

`SystemState` cobre só os 9 estados nomeados em §10.3 (trading permitido
SÓ em `RUNNING`, usado por `src.risk.limits.control_02_estado_sistema`) — a
VALIDAÇÃO de transições entre eles (o grafo completo do diagrama de §10.3)
fica fora do escopo deste Sprint: é responsabilidade de um orquestrador de
processo vivo (Sprint 12+), não de um módulo de funções puras. Mesma decisão
de escopo já registrada em `pyproject.toml` (comentário do bloco
`[tool.importlinter]`: "risk/execution/live" ganham conteúdo real em
Sprints futuros).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

import structlog

from src.exchange.filters import Filters
from src.regime.stress import TriggerState, compute_filters_hash

from ._constants import load_constant

logger = structlog.get_logger(__name__)


def _to_decimal(value: Decimal | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class SystemState(Enum):
    """§10.3 — `BOOT -> INITIALIZING -> SYNCING -> READY -> RUNNING <-> PAUSED`,
    com `PAUSED -> ERROR -> HALTED -> KILLED` no caminho de falha. Trading
    permitido apenas em `RUNNING`."""

    BOOT = "BOOT"
    INITIALIZING = "INITIALIZING"
    SYNCING = "SYNCING"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    HALTED = "HALTED"
    KILLED = "KILLED"


# ============================================================================
# K01-K03 — perdas/drawdown, computáveis hoje (fórmula sobre estado injetado,
# mesmos limiares REUSADOS de src.risk.limits controles 14/15/16 — §8.3/§10.2
# citam o mesmo número duas vezes no PRD, uma constante cada, não duplicada).
# ============================================================================


def k01_daily_loss(daily_loss_usd: Decimal, equity: Decimal) -> TriggerState:
    """K01 — §10.2 gatilho 1: perda diária > 2% do equity."""
    if equity <= 0:
        return TriggerState.NOT_COMPUTABLE
    threshold = _to_decimal(load_constant("daily_loss_limit_pct_equity"))
    ratio = daily_loss_usd / equity
    return TriggerState.TRIGGERED if ratio > threshold else TriggerState.NOT_TRIGGERED


def k02_max_drawdown(equity: Decimal, equity_peak_usd: Decimal) -> TriggerState:
    """K02 — §10.2 gatilho 2: drawdown do pico > 10%. Pico ainda não
    estabelecido (`equity_peak_usd <= 0`, primeira observação do processo) é
    `NOT_COMPUTABLE`, não `NOT_TRIGGERED` — não há base para afirmar "não
    disparou" sem um pico de referência real."""
    if equity_peak_usd <= 0:
        return TriggerState.NOT_COMPUTABLE
    threshold = _to_decimal(load_constant("max_drawdown_pct_peak"))
    drawdown = (equity_peak_usd - equity) / equity_peak_usd
    return TriggerState.TRIGGERED if drawdown > threshold else TriggerState.NOT_TRIGGERED


def k03_consecutive_losses(consecutive_losses: int) -> TriggerState:
    """K03 — §10.2 gatilho 3: perdas consecutivas > 5. Sempre computável —
    um contador inteiro injetado nunca é "desconhecido" (0 é um valor válido,
    não um sentinela de ausência)."""
    threshold = int(load_constant("max_consecutive_losses"))
    return TriggerState.TRIGGERED if consecutive_losses > threshold else TriggerState.NOT_TRIGGERED


# ============================================================================
# K04-K11 — sensor pronto, sem fonte de dado real ainda (ver tabela do
# docstring do módulo). Cada função implementa a comparação de verdade;
# só o parâmetro `None` (o caso real do pipeline hoje) produz NOT_COMPUTABLE.
# ============================================================================


def k04_exchange_disconnected(seconds_since_last_contact: float | None) -> TriggerState:
    """K04 — §10.2 gatilho 4: desconexão > 120s sem WebSocket nem REST.
    `src.exchange.ws.EventWatchdog` (Sprint 2) já mede o sinal bruto
    ("segundos desde o último evento") — este módulo não a importa
    diretamente porque `EventWatchdog` é um objeto com estado/temporizador
    (`_now_fn`, `_last_event_at`), e `kill_switch.py` só aceita valores já
    resolvidos, mesma fronteira de responsabilidade do resto do módulo. Um
    loop live (Sprint 13) é quem chamaria `EventWatchdog` e passaria o
    resultado aqui."""
    if seconds_since_last_contact is None:
        return TriggerState.NOT_COMPUTABLE
    threshold = float(load_constant("exchange_disconnect_kill_switch_s"))
    triggered = seconds_since_last_contact > threshold
    return TriggerState.TRIGGERED if triggered else TriggerState.NOT_TRIGGERED


def k05_position_divergence(critical_divergence: bool | None) -> TriggerState:
    """K05 — §10.2 gatilho 5: qualquer divergência crítica de reconciliação
    (posição, quantidade, ordens abertas, modo de margem — §10.1). Sprint 14
    (reconciliação real) não existe neste repo; `None` é o caso real hoje."""
    if critical_divergence is None:
        return TriggerState.NOT_COMPUTABLE
    return TriggerState.TRIGGERED if critical_divergence else TriggerState.NOT_TRIGGERED


def k06_unexpected_order(unexpected_order_detected: bool | None) -> TriggerState:
    """K06 — §10.2 gatilho 6: ordem na exchange sem `client_order_id`
    conhecido. Depende de rastreamento de ordens ao vivo — `src.execution`
    ainda só tem `fill_simulator.py` (backtest), sem consumidor live."""
    if unexpected_order_detected is None:
        return TriggerState.NOT_COMPUTABLE
    return TriggerState.TRIGGERED if unexpected_order_detected else TriggerState.NOT_TRIGGERED


def k07_api_error_storm(api_errors_last_60s: int | None) -> TriggerState:
    """K07 — §10.2 gatilho 7: > 10 erros de API em 60s. `src.exchange.rest`/
    `rate_limit` não expõem um contador de erros vivo consumível por este
    módulo ainda — `None` é o caso real hoje."""
    if api_errors_last_60s is None:
        return TriggerState.NOT_COMPUTABLE
    threshold = int(load_constant("api_error_storm_threshold_count"))
    triggered = api_errors_last_60s > threshold
    return TriggerState.TRIGGERED if triggered else TriggerState.NOT_TRIGGERED


def k08_data_corruption(quality_gate_failed_live: bool | None) -> TriggerState:
    """K08 — §10.2 gatilho 8: Quality Gate falha em dado AO VIVO.
    `src.data.validate` (Sprint 2/3) valida lotes/histórico — não há
    consumidor de streaming que rode o Quality Gate por barra ainda."""
    if quality_gate_failed_live is None:
        return TriggerState.NOT_COMPUTABLE
    return TriggerState.TRIGGERED if quality_gate_failed_live else TriggerState.NOT_TRIGGERED


def k09_model_unavailable(model_unavailable: bool | None) -> TriggerState:
    """K09 — §10.2 gatilho 9: falha de carga ou inferência do modelo. Alpha
    real é Sprint 8, em paralelo a este — sem modelo carregado em produção,
    não há inferência para falhar. `None` é o caso real hoje."""
    if model_unavailable is None:
        return TriggerState.NOT_COMPUTABLE
    return TriggerState.TRIGGERED if model_unavailable else TriggerState.NOT_TRIGGERED


def k10_risk_engine_failure(risk_engine_exception_caught: bool | None) -> TriggerState:
    """K10 — §10.2 gatilho 10: exceção não tratada do Risk Engine.

    **Meta-circular por desenho — resolvido explicitamente, não ignorado.**
    Uma função pura DENTRO do Risk Engine não pode reportar a própria falha
    do Risk Engine: se o motor quebrou, a exceção já propagou e nenhuma
    função sua está mais rodando para computar `TRIGGERED`. O sinal real é
    ESTRUTURAL, não algébrico — pertence ao LOOP CHAMADOR (fora do escopo
    deste Sprint, Sprint 12+ live): esse loop envolve toda invocação a
    `src.risk.sizing`/`limits`/`kill_switch` num `try/except`, e se uma
    exceção não tratada escapar, o PRÓPRIO `except` seta
    `risk_engine_exception_caught=True` antes de chamar esta função de novo
    na próxima iteração (o kill switch da iteração N reporta a falha da
    iteração N-1). Esta função só computa a metade "depois da captura" —
    `None` (nenhuma exceção foi capturada ainda, ou não há loop reportando)
    é o caso real hoje."""
    if risk_engine_exception_caught is None:
        return TriggerState.NOT_COMPUTABLE
    return TriggerState.TRIGGERED if risk_engine_exception_caught else TriggerState.NOT_TRIGGERED


def k11_unknown_order_state(unknown_order_state_age_s: float | None) -> TriggerState:
    """K11 — §10.2 gatilho 11: estado de execução `UNKNOWN` não resolvido em
    120s (§9.2: `UNKNOWN` é terminal até resolução por reconciliação — nenhuma
    ordem nova é enviada enquanto existir uma em `UNKNOWN`). Depende da
    máquina de estados de ordem ao vivo, que não existe em `src.execution`
    ainda — `None` é o caso real hoje."""
    if unknown_order_state_age_s is None:
        return TriggerState.NOT_COMPUTABLE
    threshold = float(load_constant("unknown_order_state_kill_switch_s"))
    triggered = unknown_order_state_age_s > threshold
    return TriggerState.TRIGGERED if triggered else TriggerState.NOT_TRIGGERED


# ============================================================================
# K12-K13 — computáveis hoje.
# ============================================================================


def k12_filters_hash_changed(
    filters: Filters, last_revalidated_filters_hash: str | None
) -> TriggerState:
    """K12 — §10.2 gatilho 12: `filters_hash` mudou e não foi revalidado.
    REUSA `src.regime.stress.compute_filters_hash` (Sprint 5) sobre um
    `Filters` real (`src.exchange.filters.load_filters_asof`) — genuinamente
    computável, não um sensor ausente. `last_revalidated_filters_hash=None`
    (processo recém-iniciado, sem hash de referência ainda confirmado por um
    operador) é `NOT_COMPUTABLE`, não `NOT_TRIGGERED` — sem referência, não
    há base para afirmar que nada mudou."""
    if last_revalidated_filters_hash is None:
        return TriggerState.NOT_COMPUTABLE
    current_hash = compute_filters_hash(filters)
    triggered = current_hash != last_revalidated_filters_hash
    return TriggerState.TRIGGERED if triggered else TriggerState.NOT_TRIGGERED


def k13_equity_floor(equity: Decimal) -> TriggerState:
    """K13 — §10.2 gatilho 13: equity abaixo do piso operacional de US$150
    (~2,3 unidades). "Gatilho específico deste capital" (texto do PRD):
    abaixo do piso, o controle 8 (granularidade, `src.risk.limits`) reprova
    essencialmente todo trade — o sistema para antes de ficar preso numa
    configuração sem trade executável dentro do orçamento de risco. Sempre
    computável — `equity` é sempre injetado (B17)."""
    floor = _to_decimal(load_constant("equity_floor_usd"))
    return TriggerState.TRIGGERED if equity < floor else TriggerState.NOT_TRIGGERED


# ============================================================================
# Composição — KillSwitchInputs/KillSwitchResult, um valor por gatilho.
# ============================================================================


KILL_SWITCH_TRIGGER_IDS: tuple[str, ...] = (
    "K01", "K02", "K03", "K04", "K05", "K06",
    "K07", "K08", "K09", "K10", "K11", "K12", "K13",
)  # fmt: skip


class KillSwitchDecision(Enum):
    OK = "OK"
    KILLED = "KILLED"


@dataclass(frozen=True, slots=True)
class KillSwitchInputs:
    """Entradas dos 13 gatilhos. Campos `| None` (K04-K11) correspondem aos
    gatilhos "sensor pronto, sem fonte de dado real ainda" — o default
    `None` reproduz o estado real do pipeline hoje; um chamador futuro (loop
    live, Sprint 12+) passa o valor real assim que a fonte existir."""

    equity: Decimal
    daily_loss_usd: Decimal
    equity_peak_usd: Decimal
    consecutive_losses: int
    filters: Filters
    last_revalidated_filters_hash: str | None
    seconds_since_last_exchange_contact: float | None = None
    critical_reconciliation_divergence: bool | None = None
    unexpected_order_detected: bool | None = None
    api_errors_last_60s: int | None = None
    quality_gate_failed_live: bool | None = None
    model_unavailable: bool | None = None
    risk_engine_exception_caught: bool | None = None
    unknown_order_state_age_s: float | None = None


@dataclass(frozen=True, slots=True)
class KillSwitchResult:
    decision: KillSwitchDecision
    triggers: dict[str, TriggerState]
    triggered_ids: tuple[str, ...]
    not_computable_ids: tuple[str, ...]


def evaluate_kill_switch(inputs: KillSwitchInputs) -> KillSwitchResult:
    """Roda os 13 gatilhos. `KILLED` se QUALQUER um disparar — nenhum
    gatilho é "soft" (§10.2, sem gradação de severidade). `NOT_COMPUTABLE`
    nunca conta como `TRIGGERED` (mesma regra de `src.regime.stress`)."""
    triggers: dict[str, TriggerState] = {
        "K01": k01_daily_loss(inputs.daily_loss_usd, inputs.equity),
        "K02": k02_max_drawdown(inputs.equity, inputs.equity_peak_usd),
        "K03": k03_consecutive_losses(inputs.consecutive_losses),
        "K04": k04_exchange_disconnected(inputs.seconds_since_last_exchange_contact),
        "K05": k05_position_divergence(inputs.critical_reconciliation_divergence),
        "K06": k06_unexpected_order(inputs.unexpected_order_detected),
        "K07": k07_api_error_storm(inputs.api_errors_last_60s),
        "K08": k08_data_corruption(inputs.quality_gate_failed_live),
        "K09": k09_model_unavailable(inputs.model_unavailable),
        "K10": k10_risk_engine_failure(inputs.risk_engine_exception_caught),
        "K11": k11_unknown_order_state(inputs.unknown_order_state_age_s),
        "K12": k12_filters_hash_changed(inputs.filters, inputs.last_revalidated_filters_hash),
        "K13": k13_equity_floor(inputs.equity),
    }

    triggered_ids = tuple(
        k for k in KILL_SWITCH_TRIGGER_IDS if triggers[k] == TriggerState.TRIGGERED
    )
    not_computable_ids = tuple(
        k for k in KILL_SWITCH_TRIGGER_IDS if triggers[k] == TriggerState.NOT_COMPUTABLE
    )
    decision = KillSwitchDecision.KILLED if triggered_ids else KillSwitchDecision.OK

    log = logger.warning if decision == KillSwitchDecision.KILLED else logger.debug
    log(
        "risk.kill_switch.evaluate_kill_switch",
        decision=decision.value,
        triggered_ids=triggered_ids,
        not_computable_ids=not_computable_ids,
    )

    return KillSwitchResult(
        decision=decision,
        triggers=triggers,
        triggered_ids=triggered_ids,
        not_computable_ids=not_computable_ids,
    )


@dataclass(frozen=True, slots=True)
class KillSwitchResetRecord:
    """Registro humano obrigatório para sair de `KILLED` (§10.2: "requer
    intervenção humana explícita, com registro de quem, quando e por
    quê"). Sem valores default em `operator`/`reason` — não existe reset
    "silencioso"."""

    reset_at: datetime
    operator: str
    reason: str


def reset_kill_switch(record: KillSwitchResetRecord) -> SystemState:
    """Único caminho de `KILLED` para fora — sempre para `PAUSED`, nunca
    direto a `RUNNING` (§10.2: "diagnosticar -> reconciliar manualmente ->
    resetar contadores -> PAUSED -> observação de 1h -> RUNNING"; a
    transição final `PAUSED -> RUNNING` é operacional, fora deste módulo).
    Recusa (`ValueError`) se `operator`/`reason` vierem vazios — o registro
    tem que ser real, não um placeholder passando pela validação de tipo."""
    if not record.operator.strip() or not record.reason.strip():
        raise ValueError(
            "reset do kill switch exige 'operator' e 'reason' não vazios — §10.2, "
            "intervenção humana explícita, nunca automática"
        )
    logger.warning(
        "risk.kill_switch.reset",
        operator=record.operator,
        reason=record.reason,
        reset_at=record.reset_at.isoformat(),
    )
    return SystemState.PAUSED


__all__ = [
    "KILL_SWITCH_TRIGGER_IDS",
    "KillSwitchDecision",
    "KillSwitchInputs",
    "KillSwitchResetRecord",
    "KillSwitchResult",
    "SystemState",
    "evaluate_kill_switch",
    "k01_daily_loss",
    "k02_max_drawdown",
    "k03_consecutive_losses",
    "k04_exchange_disconnected",
    "k05_position_divergence",
    "k06_unexpected_order",
    "k07_api_error_storm",
    "k08_data_corruption",
    "k09_model_unavailable",
    "k10_risk_engine_failure",
    "k11_unknown_order_state",
    "k12_filters_hash_changed",
    "k13_equity_floor",
    "reset_kill_switch",
]
