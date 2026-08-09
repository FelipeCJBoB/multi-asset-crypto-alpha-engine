"""Os 18 controles do Risk Engine, em ordem de avaliação — §8.3 do PRD.

O PRD numera 18 "controles" mas o #9 tem duas verificações distintas (9a
erro de quantização, 9b resolução de sizing — §8.3 explica por que são
separados: `quant_error` sozinho deixava passar o caso de 2h onde
`N_req/unit = 1,14` arredondava para 1 unidade "por sorte", com erro de
apenas 12,6%), então este módulo expõe 19 funções de controle mapeadas aos
18 números do PRD (`9a`/`9b` sob o mesmo `9`).

**Cada controle é uma função pura, testável isoladamente** — recebe só os
valores de que precisa (não um blob de estado do sistema inteiro), devolve
um `ControlOutcome`. `evaluate_all` é o único lugar que conhece a ORDEM e
agrega.

**Desenho tri-valorado, mesma filosofia de `src.regime.stress.TriggerState`
(Sprint 5), reaproveitada aqui por consistência entre módulos — mas como um
`Enum` PRÓPRIO (`ControlOutcome`), não uma reimportação direta.** Os polos
são invertidos entre os dois módulos: em `stress.py`, `TRIGGERED` é o estado
de alerta; aqui, `PASS` é o estado "seguro". Misturar os dois vocabulários
sob o mesmo `Enum` (ex. usar `TriggerState.NOT_TRIGGERED` para significar
"controle passou") inverteria a leitura em um dos dois módulos silenciosamente
— por isso um `Enum` novo, com nomes que descrevem o próprio domínio
(controle passa/falha), preservando só a IDEIA de três estados (nunca colapsar
"não sei" em "não disparou"/"passou").

**Decisão de desenho (a task pediu para decidir e documentar): parar no
primeiro `FAIL`.** O PRD lista os controles "em ordem de avaliação" — parar no
primeiro que falha é mais simples de auditar (a razão de rejeição é sempre
única e determinística) do que rodar os 19 e agregar todas as falhas; o custo
é que uma rejeição não revela se HAVERIA outras falhas mais à frente — aceitável
porque o próximo candidato reavalia do zero na próxima barra, e cada avaliação
já é barata (aritmética Decimal, sem I/O na maioria dos controles).

**`NOT_COMPUTABLE` nunca bloqueia.** Um controle cujo sensor não tem fonte de
dado real hoje (17-depth, 18) não é "passou" nem "falhou" — é "não sei", e a
task foi explícita: não implementar como sempre-passa SILENCIOSO. A resolução
aqui é a mesma de `stress.py`: `NOT_COMPUTABLE` não interrompe a avaliação
(o motor segue para o próximo controle, e no fim `RiskDecision.APPROVED` ainda
é possível), mas fica registrado em `RiskDecision.controls_not_computable` —
visível na auditoria (§10.6), nunca escondido dentro de um `True` genérico.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, StrEnum

import numpy as np
import structlog

from src.features.groups.group_e import round_trip_cost_bps
from src.regime.classifier import TRADEABLE_REGIMES

from ._constants import load_constant
from .kill_switch import SystemState
from .sizing import SizingResult

logger = structlog.get_logger(__name__)


def _to_decimal(value: Decimal | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class ControlOutcome(Enum):
    """Ver docstring do módulo — tri-valorado, `Enum` puro (não `str, Enum`;
    aqui não há comparação vetorizada numpy em cima destes valores como em
    `stress.TriggerState`, então o hazard de mixin `str` documentado lá não
    se aplica diretamente, mas manter `Enum` puro custa nada e evita
    reabrir a mesma classe de bug se algum dia isto virar array)."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_COMPUTABLE = "NOT_COMPUTABLE"


class RejectionReason(StrEnum):
    """Motivo de rejeição nomeado — um por controle (19 valores para os 18
    números do PRD, `9a`/`9b` distintos). `StrEnum` DELIBERADO aqui —
    diferente de `stress.TriggerState`, que evita o mixin manual `(str, Enum)`
    por causa de um bug real de comparação vetorizada numpy (`np.asarray` de
    um membro `str`-mixed usa `str(member)`, truncado). `RejectionReason`
    nunca entra em um array numpy — é sempre um valor escalar por decisão —
    então o comportamento `str` nativo do `StrEnum` (3.11+, `ruff` UP042
    recomenda sobre `(str, Enum)` explícito) é seguro aqui e ganha
    serialização JSON direta (`orjson.dumps`/`json.dumps` de
    `RejectionReason.REGIME_BLOCKED` vira `"REGIME_BLOCKED"` sem `.value`
    explícito), útil para o evento de auditoria §10.6
    (`risk.controls_failed`)."""

    REGIME_BLOCKED = "REGIME_BLOCKED"
    STATE_NOT_RUNNING = "STATE_NOT_RUNNING"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    STALE_RECONCILIATION = "STALE_RECONCILIATION"
    DATA_STALE = "DATA_STALE"
    BELOW_MIN_QTY = "BELOW_MIN_QTY"
    BELOW_MIN_NOTIONAL = "BELOW_MIN_NOTIONAL"
    INSUFFICIENT_GRANULARITY = "INSUFFICIENT_GRANULARITY"
    QUANTIZATION_LIMIT = "QUANTIZATION_LIMIT"
    INSUFFICIENT_RESOLUTION = "INSUFFICIENT_RESOLUTION"
    RISK_OVERSHOOT = "RISK_OVERSHOOT"
    MAX_NOTIONAL = "MAX_NOTIONAL"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    FEE_BUDGET_EXHAUSTED = "FEE_BUDGET_EXHAUSTED"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    LIQUIDITY_INSUFFICIENT = "LIQUIDITY_INSUFFICIENT"
    EVENT_WINDOW = "EVENT_WINDOW"


# ============================================================================
# Controles 1-5 — estado/candidato, anteriores ao sizing
# ============================================================================


def control_01_regime_tradeavel(regime: str) -> ControlOutcome:
    """#1 — `regime ∈ {R1..R4}`. REUSA `TRADEABLE_REGIMES` de
    `src.regime.classifier` (Sprint 5) — não redeclara o conjunto aqui."""
    return ControlOutcome.PASS if regime in TRADEABLE_REGIMES else ControlOutcome.FAIL


def control_02_estado_sistema(system_state: SystemState) -> ControlOutcome:
    """#2 — trading permitido só em `RUNNING` (§10.3)."""
    return ControlOutcome.PASS if system_state == SystemState.RUNNING else ControlOutcome.FAIL


def control_03_kill_switch(kill_switch_active: bool) -> ControlOutcome:
    """#3 — `killed == False`."""
    return ControlOutcome.FAIL if kill_switch_active else ControlOutcome.PASS


def control_04_reconciliacao_fresca(reconciliation_age_s: float) -> ControlOutcome:
    """#4 — idade da última reconciliação < 60s (§10.1/§8.3 c4). Sprint 14
    (reconciliação real) não existe neste repo — `reconciliation_age_s` é
    SEMPRE injetado pelo chamador (B17: nunca cache local de equity nem do
    que prova que ele é fresco)."""
    max_age_s = float(load_constant("reconciliation_max_age_s"))
    return ControlOutcome.PASS if reconciliation_age_s < max_age_s else ControlOutcome.FAIL


def control_05_frescor_dados(bar_staleness_s: float, book_staleness_s: float) -> ControlOutcome:
    """#5 — barra < 90s, book < 5s (§8.3 c5). Mesma natureza de "sensor
    ao vivo" já documentada em `src.regime.stress.s05_stale_data` (staleness
    só existe em operação contínua, não em histórico) — aqui os valores
    chegam sempre injetados, o controle só compara contra o limiar."""
    bar_max_s = float(load_constant("data_staleness_bar_max_s"))
    book_max_s = float(load_constant("data_staleness_book_max_s"))
    if bar_staleness_s < bar_max_s and book_staleness_s < book_max_s:
        return ControlOutcome.PASS
    return ControlOutcome.FAIL


# ============================================================================
# Controles 6-11 — núcleo desta versão do PRD (§8.3): tradução operacional
# de R1/R2, todos operando sobre a saída já computada de
# `src.risk.sizing.compute_sizing` (SizingResult).
# ============================================================================


def control_06_qty_minima(sizing: SizingResult) -> ControlOutcome:
    """#6 — `qty >= filters.min_qty`."""
    return ControlOutcome.PASS if sizing.qty >= sizing.filters.min_qty else ControlOutcome.FAIL


def control_07_notional_minimo(sizing: SizingResult) -> ControlOutcome:
    """#7 — `notional_real >= filters.min_notional`."""
    ok = sizing.notional_real >= sizing.filters.min_notional
    return ControlOutcome.PASS if ok else ControlOutcome.FAIL


def control_08_granularidade(sizing: SizingResult) -> ControlOutcome:
    """#8 — `notional_real >= 3 x unit_notional` (`min_granularity_units`,
    §8.3 c8, citado literalmente do texto atual do PRD v3.3).

    **Não confundir com o "≥3 unidades" do V2, já invalidado (erro corrigido
    #5, PARTE XIX / `constants.yaml::quantization_tolerance`).** Aquele era
    um corte sobre `N_req` (o nocional TEÓRICO exigido, antes de quantizar) —
    sem base, corrigido pela dupla `quantization_tolerance` (9a) +
    `min_sizing_resolution_units` (9b). Este controle #8 opera sobre
    `notional_real` (o nocional JÁ quantizado, pós-`floor_to_step`) — mede se
    a posição REALMENTE executável tem massa discreta suficiente para um
    preenchimento parcial fazer sentido (§9.3: 1-2 unidades preenchidas no
    timeout viola este controle e fecha a mercado, `PARTIAL_BELOW_MIN`). É um
    número diferente, com uma pergunta diferente, ambos vivos no PRD v3.3
    simultaneamente — não é o bug antigo ressuscitado."""
    min_units = _to_decimal(load_constant("min_granularity_units"))
    ok = sizing.notional_real >= min_units * sizing.unit_notional
    return ControlOutcome.PASS if ok else ControlOutcome.FAIL


def control_09a_erro_quantizacao(sizing: SizingResult) -> ControlOutcome:
    """#9a — `quant_error <= quantization_tolerance` (já existe em
    `constants.yaml`, Sprint 1)."""
    tolerance = _to_decimal(load_constant("quantization_tolerance"))
    return ControlOutcome.PASS if sizing.quant_error <= tolerance else ControlOutcome.FAIL


def control_09b_resolucao_sizing(sizing: SizingResult) -> ControlOutcome:
    """#9b — `N_req/unit >= 2,0` (`min_sizing_resolution_units`). Existe
    separado de 9a porque `quant_error` sozinho deixa passar o caso da barra
    de 2h onde `N_req/unit = 1,14` arredonda para 1 unidade "por sorte" com
    erro de só 12,6% (§8.3, tabela de dispersão risco p90/p10 por TF — a 2h,
    p90/p10 = 3,05x; a 15m, 1,33x). `N_req` é o nocional TEÓRICO
    (`sizing.notional_req`, pré-quantização) — não `notional_real`."""
    min_units = _to_decimal(load_constant("min_sizing_resolution_units"))
    if sizing.unit_notional == 0:
        return ControlOutcome.FAIL
    n_req_over_unit = sizing.notional_req / sizing.unit_notional
    return ControlOutcome.PASS if n_req_over_unit >= min_units else ControlOutcome.FAIL


def control_10_risco_real(sizing: SizingResult) -> ControlOutcome:
    """#10 — `risk_real/equity <= 0,006` (`risk_overshoot_max_pct_equity`).
    **Diferente de `risk_per_trade` (0,005, Sprint 1).** `risk_per_trade` é o
    ALVO usado no passo 1 do sizing (§8.2) para calcular `risk_usd` antes da
    quantização; `risk_overshoot_max_pct_equity` é o TETO pós-quantização —
    depois que `qty` é arredondado para baixo ao `step_size`, `risk_real`
    pode (e no caso mediano, deve — ver tabela §8.3) ficar um pouco ACIMA do
    alvo de 0,5%, nunca exatamente nele. 0,6% é a margem que o desenho tolera
    antes de rejeitar; 0,5% nunca é reparametrizado a partir daqui (CLAUDE.md:
    "nunca otimize de volta o que foi derivado").

    **`equity <= 0`, não `== 0`** (achado de auditoria, `audit/
    division_guard_audit.md`): com `equity` negativo a guarda antiga não
    disparava e `risk_real/equity` saía negativo, passando o teto
    trivialmente — o controle aprovava exatamente o caso em que deveria
    bloquear com mais força. `FAIL`, não `NOT_COMPUTABLE`, porque este é um
    controle pré-trade que bloqueia a ordem (mesmo padrão de
    `control_09b_resolucao_sizing` acima), diferente de
    `kill_switch.k01_daily_loss`, que monitora estado e usa
    `NOT_COMPUTABLE` para distinguir "não sei" de "confirmado seguro"."""
    max_ratio = _to_decimal(load_constant("risk_overshoot_max_pct_equity"))
    if sizing.equity <= 0:
        return ControlOutcome.FAIL
    ratio = sizing.risk_real / sizing.equity
    return ControlOutcome.PASS if ratio <= max_ratio else ControlOutcome.FAIL


def control_11_nocional_maximo(sizing: SizingResult) -> ControlOutcome:
    """#11 — `leverage_eff <= max_notional_multiple` (3,0, herdado do V2 —
    §8.6, changelog V2->V3 #6: "`max_leverage: 3` -> `max_notional_multiple:
    3.0`" — a alavancagem CONFIGURADA na exchange não é controle de risco
    (§8.6); este é o controle real)."""
    max_mult = _to_decimal(load_constant("max_notional_multiple"))
    return ControlOutcome.PASS if sizing.leverage_eff <= max_mult else ControlOutcome.FAIL


# ============================================================================
# Controles 12-16 — margem, orçamento de fees, perdas (estado de conta;
# reconciliação/ledger de Sprint 14 não existe — tudo injetado pelo chamador,
# igual a `equity`, B17).
# ============================================================================


def control_12_margem_disponivel(
    sizing: SizingResult, *, im_required_usd: Decimal
) -> ControlOutcome:
    """#12 — `IM_req <= 0,60 x equity` (`im_required_max_pct_equity`).
    `im_required_usd` é injetado pelo chamador (cálculo de margem inicial
    depende de `leverage`/`MMR` da exchange — fora do escopo de `risk/`,
    §8.6 nota que a alavancagem configurada só afeta margem travada, não
    liquidação relevante neste desenho)."""
    max_ratio = _to_decimal(load_constant("im_required_max_pct_equity"))
    ok = im_required_usd <= max_ratio * sizing.equity
    return ControlOutcome.PASS if ok else ControlOutcome.FAIL


def control_13_orcamento_fees(sizing: SizingResult, *, fees_mtd_usd: Decimal) -> ControlOutcome:
    """#13 — fees do mês corrente + custo estimado deste trade <= orçamento
    mensal (`fee_budget_monthly`, já existe). Custo estimado REUSA
    `src.features.groups.group_e.round_trip_cost_bps` (Sprint 4, mesma
    fórmula de E27f: maker na entrada, 50/50 maker-TP/taker-SL na saída,
    §9.1) em vez de reimplementar a mistura de fees aqui — verificado contra
    o exemplo do PRD §8.5 (`notional=259,76` -> `estimated_cost_usd=0,143`).
    `fees_mtd_usd` é contador vivo injetado pelo chamador (§8.3 c13: "não é
    uma aspiração" — mas o ledger que soma `fills.fee` do mês é
    responsabilidade de outra camada, não existe em `risk/`)."""
    maker_fee = float(load_constant("maker_fee"))
    taker_fee = float(load_constant("taker_fee"))
    cost_bps = round_trip_cost_bps(maker_fee, taker_fee)
    estimated_cost_usd = sizing.notional_real * _to_decimal(cost_bps) / Decimal(10000)

    budget_ratio = _to_decimal(load_constant("fee_budget_monthly"))
    budget = budget_ratio * sizing.equity
    ok = (fees_mtd_usd + estimated_cost_usd) <= budget
    return ControlOutcome.PASS if ok else ControlOutcome.FAIL


def control_14_perda_diaria(sizing: SizingResult, *, daily_loss_usd: Decimal) -> ControlOutcome:
    """#14 — perda do dia <= 2% do equity (`daily_loss_limit_pct_equity`,
    mesmo limiar do gatilho 1 do kill switch, §10.2 — reusado, não
    duplicado). `daily_loss_usd` é magnitude positiva de perda acumulada no
    dia corrente, injetada pelo chamador."""
    max_ratio = _to_decimal(load_constant("daily_loss_limit_pct_equity"))
    ok = daily_loss_usd <= max_ratio * sizing.equity
    return ControlOutcome.PASS if ok else ControlOutcome.FAIL


def control_15_max_drawdown(sizing: SizingResult, *, equity_peak_usd: Decimal) -> ControlOutcome:
    """#15 — drawdown do pico <= 10% (`max_drawdown_pct_peak`, mesmo limiar
    do gatilho 2 do kill switch, §10.2). `equity_peak_usd <= 0` é tratado
    como `NOT_COMPUTABLE` (pico ainda não estabelecido — primeira observação
    de equity do processo), não como falha nem como aprovação automática."""
    if equity_peak_usd <= 0:
        return ControlOutcome.NOT_COMPUTABLE
    max_dd = _to_decimal(load_constant("max_drawdown_pct_peak"))
    drawdown = (equity_peak_usd - sizing.equity) / equity_peak_usd
    return ControlOutcome.PASS if drawdown <= max_dd else ControlOutcome.FAIL


def control_16_perdas_consecutivas(consecutive_losses: int) -> ControlOutcome:
    """#16 — perdas consecutivas <= 5 (`max_consecutive_losses`, mesmo
    limiar do gatilho 3 do kill switch, §10.2)."""
    max_losses = int(load_constant("max_consecutive_losses"))
    return ControlOutcome.PASS if consecutive_losses <= max_losses else ControlOutcome.FAIL


# ============================================================================
# Controle 17 — spread e liquidez. Guardrail classe C: QUANTIL da
# distribuição observada, não número redondo (§16.10.2 regra 3) — o PRD §8.3
# literal cita "spread_bps <= 3,0", mas a task pediu EXPLICITAMENTE para não
# usar esse número redondo aqui e implementar como quantil de verdade.
# ============================================================================


def _spread_p95_threshold_bps(spread_history_bps: Sequence[Decimal | float]) -> Decimal:
    """Quantil REAL (`numpy.quantile`) sobre uma amostra observada — nunca um
    número fixo. REUSA `stress_spread_pctile_threshold` (0,95, já existe em
    `constants.yaml`, citado do PRD §4.4 S2) como o NÍVEL do quantil: mesma
    grandeza física (`spread_bps`), mesmo corte estatístico (p95) já
    estabelecido no Regime Engine (Sprint 5) para "spread extremo" — reusar
    em vez de declarar uma segunda constante com o mesmo valor e proveniência
    redundante.

    A JANELA da amostra (`spread_history_bps`) é responsabilidade de quem
    chama — o mesmo limite de confiança que `stress.py` já assume para
    `vol_pctile_expanding`/`funding_z_expanding` (a causalidade — janela
    estritamente `< t0`, B02 — é garantida por quem monta a série, não por
    esta função)."""
    quantile_level = float(load_constant("stress_spread_pctile_threshold"))
    values = np.array([float(v) for v in spread_history_bps], dtype=np.float64)
    return _to_decimal(float(np.quantile(values, quantile_level)))


def control_17_liquidez(
    *,
    spread_bps: Decimal | float | None,
    spread_history_bps: Sequence[Decimal | float] | None,
    depth_20bps_usd: Decimal | None = None,
    unit_notional: Decimal | None = None,
) -> ControlOutcome:
    """#17 — `spread <= p95(spread_observado)` E `depth_20bps >= 4 x unit`.

    **Metade "depth" documentada como NOT_COMPUTABLE hoje — mesmo achado do
    Sprint 5 (`src.regime.stress.s07_shallow_liquidity`).** O bucket mais
    fino em `data/capacity/book_depth/` é +-100bp; não existe bucket de 20bp,
    e usar o de 100bp como proxy SEMPRE resultaria em "não disparou" (a
    implicação `depth_100bp alto -> depth_20bps alto` não vale, só a inversa
    — ver docstring de `s07_shallow_liquidity` para a análise completa, não
    reproduzida aqui). Por isso `depth_20bps_usd` é sempre `None` no
    pipeline real hoje; o parâmetro existe para quando o dado existir.

    **Metade "spread" É computável, genuinamente, quando o chamador injeta
    histórico** (`_spread_p95_threshold_bps`, quantil real, não número
    redondo). No pipeline real de hoje, sem um feed de mercado ao vivo
    integrado ao Risk Engine ainda, `spread_history_bps=None` também produz
    `NOT_COMPUTABLE` para essa metade — mas a função funciona de verdade assim
    que a série for injetada (mesmo padrão de "sensor pronto, sem fonte de
    dado real ainda" usado no resto do módulo).

    **Composição de três valores (lógica de Kleene: FAIL domina, depois
    NOT_COMPUTABLE, só então PASS)** — porque a condição é uma conjunção
    (E): se a metade computável (spread) já viola o limiar, o controle FALHA
    independente do estado da metade não-computável (depth) — `False AND
    desconhecido = False`. Se spread passa mas depth é desconhecido, o
    resultado é `NOT_COMPUTABLE` (não dá para afirmar que a conjunção inteira
    é verdadeira), nunca `PASS` silencioso."""
    depth_outcome = _control_17_depth(depth_20bps_usd, unit_notional)
    spread_outcome = _control_17_spread(spread_bps, spread_history_bps)

    not_computable = ControlOutcome.NOT_COMPUTABLE
    if spread_outcome == ControlOutcome.FAIL or depth_outcome == ControlOutcome.FAIL:
        return ControlOutcome.FAIL
    if spread_outcome == not_computable or depth_outcome == not_computable:
        return ControlOutcome.NOT_COMPUTABLE
    return ControlOutcome.PASS


def _control_17_spread(
    spread_bps: Decimal | float | None, spread_history_bps: Sequence[Decimal | float] | None
) -> ControlOutcome:
    if spread_bps is None or not spread_history_bps:
        return ControlOutcome.NOT_COMPUTABLE
    threshold = _spread_p95_threshold_bps(spread_history_bps)
    return ControlOutcome.PASS if _to_decimal(spread_bps) <= threshold else ControlOutcome.FAIL


def _control_17_depth(
    depth_20bps_usd: Decimal | None, unit_notional: Decimal | None
) -> ControlOutcome:
    """Sempre `NOT_COMPUTABLE` com o dado disponível hoje (ver docstring de
    `control_17_liquidez`) — `depth_20bps_usd` nunca chega preenchido do
    pipeline real; o ramo `is not None` existe só para não travar um teste ou
    um chamador futuro que já tenha o dado certo. Limiar `min_liquidity_depth_units`
    (4x, §8.3 c17) é distinto de `min_granularity_units` (3x, controle 8) —
    dois números diferentes do PRD, não o mesmo constante reaproveitada."""
    if depth_20bps_usd is None or unit_notional is None:
        return ControlOutcome.NOT_COMPUTABLE
    threshold_units = _to_decimal(load_constant("min_liquidity_depth_units"))
    min_depth = threshold_units * unit_notional
    return ControlOutcome.PASS if depth_20bps_usd >= min_depth else ControlOutcome.FAIL


def control_18_janela_evento() -> ControlOutcome:
    """#18 — `is_event_window == False`. NÃO COMPUTÁVEL: nenhum calendário
    de eventos (FOMC/CPI/NFP) existe no repo — mesmo achado do Sprint 5 para
    o gatilho S8 do Regime Engine (`src.regime.stress.s08_event_window`).

    A task pediu explicitamente para "retornar sempre 'não bloqueado' com
    nota explícita de que este controle está inativo por falta de dado, não
    implementar como sempre-passa silencioso" — a resolução é a mesma usada
    no resto deste módulo: `NOT_COMPUTABLE` nunca bloqueia (`evaluate_all`
    segue em frente), mas fica registrado como tal em
    `RiskDecision.controls_not_computable`, nunca reportado como
    `ControlOutcome.PASS`. Sem parâmetros — não há nenhum dado real para
    receber ainda; quando K06 (calendário) existir, esta função ganha um
    parâmetro `is_event_window: bool` e passa a computar de verdade, mesmo
    padrão de `s02_spread_extreme`."""
    return ControlOutcome.NOT_COMPUTABLE


# ============================================================================
# Orquestração — ordem fixa, para no primeiro FAIL (decisão documentada acima)
# ============================================================================


@dataclass(frozen=True, slots=True)
class RiskEngineInputs:
    """Todo o estado externo de que os 18 controles precisam. `sizing` é
    SEMPRE pré-computado pelo chamador via `src.risk.sizing` (responsabilidade
    de sizing e de controle são módulos separados) — os controles 6-11 só
    leem os campos já calculados."""

    regime: str
    system_state: SystemState
    kill_switch_active: bool
    reconciliation_age_s: float
    bar_staleness_s: float
    book_staleness_s: float
    sizing: SizingResult
    im_required_usd: Decimal
    fees_mtd_usd: Decimal
    daily_loss_usd: Decimal
    equity_peak_usd: Decimal
    consecutive_losses: int
    spread_bps: Decimal | float | None = None
    spread_history_bps: Sequence[Decimal | float] | None = None
    depth_20bps_usd: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    rejection_reason: RejectionReason | None
    controls_passed: tuple[str, ...]
    controls_not_computable: tuple[str, ...]
    controls_evaluated: tuple[str, ...] = field(default_factory=tuple)


# ordem fixa §8.3 — (id_pro_log, RejectionReason, thunk sem argumento)
def evaluate_all(inputs: RiskEngineInputs) -> RiskDecision:
    """Roda os 18/19 controles NA ORDEM do PRD §8.3, parando no primeiro
    `FAIL` (decisão documentada no docstring do módulo). `NOT_COMPUTABLE`
    nunca interrompe — é registrado e a avaliação continua."""
    checks: tuple[tuple[str, RejectionReason, ControlOutcome], ...] = (
        ("1", RejectionReason.REGIME_BLOCKED, control_01_regime_tradeavel(inputs.regime)),
        ("2", RejectionReason.STATE_NOT_RUNNING, control_02_estado_sistema(inputs.system_state)),
        (
            "3",
            RejectionReason.KILL_SWITCH_ACTIVE,
            control_03_kill_switch(inputs.kill_switch_active),
        ),
        (
            "4",
            RejectionReason.STALE_RECONCILIATION,
            control_04_reconciliacao_fresca(inputs.reconciliation_age_s),
        ),
        (
            "5",
            RejectionReason.DATA_STALE,
            control_05_frescor_dados(inputs.bar_staleness_s, inputs.book_staleness_s),
        ),
        ("6", RejectionReason.BELOW_MIN_QTY, control_06_qty_minima(inputs.sizing)),
        ("7", RejectionReason.BELOW_MIN_NOTIONAL, control_07_notional_minimo(inputs.sizing)),
        ("8", RejectionReason.INSUFFICIENT_GRANULARITY, control_08_granularidade(inputs.sizing)),
        ("9a", RejectionReason.QUANTIZATION_LIMIT, control_09a_erro_quantizacao(inputs.sizing)),
        (
            "9b",
            RejectionReason.INSUFFICIENT_RESOLUTION,
            control_09b_resolucao_sizing(inputs.sizing),
        ),
        ("10", RejectionReason.RISK_OVERSHOOT, control_10_risco_real(inputs.sizing)),
        ("11", RejectionReason.MAX_NOTIONAL, control_11_nocional_maximo(inputs.sizing)),
        (
            "12",
            RejectionReason.INSUFFICIENT_MARGIN,
            control_12_margem_disponivel(inputs.sizing, im_required_usd=inputs.im_required_usd),
        ),
        (
            "13",
            RejectionReason.FEE_BUDGET_EXHAUSTED,
            control_13_orcamento_fees(inputs.sizing, fees_mtd_usd=inputs.fees_mtd_usd),
        ),
        (
            "14",
            RejectionReason.DAILY_LOSS_LIMIT,
            control_14_perda_diaria(inputs.sizing, daily_loss_usd=inputs.daily_loss_usd),
        ),
        (
            "15",
            RejectionReason.MAX_DRAWDOWN,
            control_15_max_drawdown(inputs.sizing, equity_peak_usd=inputs.equity_peak_usd),
        ),
        (
            "16",
            RejectionReason.CONSECUTIVE_LOSSES,
            control_16_perdas_consecutivas(inputs.consecutive_losses),
        ),
        (
            "17",
            RejectionReason.LIQUIDITY_INSUFFICIENT,
            control_17_liquidez(
                spread_bps=inputs.spread_bps,
                spread_history_bps=inputs.spread_history_bps,
                depth_20bps_usd=inputs.depth_20bps_usd,
                unit_notional=inputs.sizing.unit_notional,
            ),
        ),
        ("18", RejectionReason.EVENT_WINDOW, control_18_janela_evento()),
    )

    passed: list[str] = []
    not_computable: list[str] = []
    evaluated: list[str] = []

    for control_id, reason, outcome in checks:
        evaluated.append(control_id)
        if outcome == ControlOutcome.FAIL:
            logger.info(
                "risk.limits.rejected",
                control_id=control_id,
                reason=reason.value,
                controls_passed=tuple(passed),
                controls_not_computable=tuple(not_computable),
            )
            return RiskDecision(
                approved=False,
                rejection_reason=reason,
                controls_passed=tuple(passed),
                controls_not_computable=tuple(not_computable),
                controls_evaluated=tuple(evaluated),
            )
        if outcome == ControlOutcome.NOT_COMPUTABLE:
            not_computable.append(control_id)
        else:
            passed.append(control_id)

    logger.info(
        "risk.limits.approved",
        controls_passed=tuple(passed),
        controls_not_computable=tuple(not_computable),
    )
    return RiskDecision(
        approved=True,
        rejection_reason=None,
        controls_passed=tuple(passed),
        controls_not_computable=tuple(not_computable),
        controls_evaluated=tuple(evaluated),
    )


__all__ = [
    "ControlOutcome",
    "RejectionReason",
    "RiskDecision",
    "RiskEngineInputs",
    "control_01_regime_tradeavel",
    "control_02_estado_sistema",
    "control_03_kill_switch",
    "control_04_reconciliacao_fresca",
    "control_05_frescor_dados",
    "control_06_qty_minima",
    "control_07_notional_minimo",
    "control_08_granularidade",
    "control_09a_erro_quantizacao",
    "control_09b_resolucao_sizing",
    "control_10_risco_real",
    "control_11_nocional_maximo",
    "control_12_margem_disponivel",
    "control_13_orcamento_fees",
    "control_14_perda_diaria",
    "control_15_max_drawdown",
    "control_16_perdas_consecutivas",
    "control_17_liquidez",
    "control_18_janela_evento",
    "evaluate_all",
]
