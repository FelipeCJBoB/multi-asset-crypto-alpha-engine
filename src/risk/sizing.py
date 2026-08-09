"""Position sizing quantizado — §8.2 do PRD.

Traduz `risk_usd` (`equity x risk_per_trade`) e a distância de stop
(`sl_atr_mult x atr_pct`) numa quantidade de contratos quantizada ao
`step_size` vigente NA DATA (`load_filters_asof`, Sprint 2) — nunca o filtro
"de hoje" aplicado a uma decisão histórica (B01).

`equity` é SEMPRE parâmetro injetado pelo chamador — nunca lido de cache
local (B17). A reconciliação de equity (Sprint 14) não existe neste repo
ainda; quem chama este módulo (backtest, paper, live) é responsável por
resolver `equity` pela fonte correta e passá-lo aqui.

**Decisão de design resolvida sozinho (ambiguidade da task):** a instrução
pede para "implementar `floor_to_step` corretamente com `Decimal`, seguindo o
mesmo padrão de `src/exchange/filters.py`". Mas `src.exchange.filters.Filters`
JÁ implementa exatamente isso — `Filters.floor_to_step(quantity)` usa
`Decimal` + `ROUND_FLOOR` (ver `src/exchange/filters.py:81-88`). Reimplementar
a mesma mecânica de quantização aqui duplicaria uma lógica que pode divergir
silenciosamente das duas cópias com o tempo — exatamente o tipo de bug de
arredondamento que a task pediu para evitar. Decisão: REUSAR
`Filters.floor_to_step` diretamente, não reimplementar. Este módulo só monta
a sequência de operações Decimal ao redor dela (§8.2, passo a passo, mesmos
nomes de variável do PRD para auditoria linha a linha).

Todo o cálculo em `Decimal`, nunca `float` puro: um erro de arredondamento de
`float` no quociente `notional_req/mark_price` pode empurrar `floor_to_step`
para o step errado silenciosamente, quantizando `qty` errado sem nenhum sinal
de erro (§0.2 R1 é a restrição dominante do projeto — errar aqui por 1
`step_size` é o tipo de falha silenciosa que a task pediu para nunca deixar
passar).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import structlog

from src.exchange.filters import Filters, load_filters_asof

from ._constants import load_constant

logger = structlog.get_logger(__name__)


class ZeroStopDistanceError(ValueError):
    """`stop_pct` resolveu para 0 (atr_pct nulo/zero) — `notional_req`
    seria infinito. Não é um caso de negócio válido; é erro de entrada."""


def _to_decimal(value: Decimal | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True, slots=True)
class SizingResult:
    """Saída do cálculo §8.2 — cada campo nomeado explicitamente como na
    fórmula do PRD, nada implícito. Consumido por `src.risk.limits`
    (controles 6-11) e pelo evento de auditoria de §10.6 (`risk.qty`,
    `risk.notional_usd`, etc.)."""

    t0: datetime
    equity: Decimal
    risk_usd: Decimal
    atr_pct: Decimal
    stop_pct: Decimal
    mark_price: Decimal
    notional_req: Decimal
    qty_raw: Decimal
    qty: Decimal
    notional_real: Decimal
    risk_real: Decimal
    quant_error: Decimal
    leverage_eff: Decimal
    unit_notional: Decimal
    filters: Filters


def compute_sizing(
    *,
    t0: datetime,
    equity: Decimal | float,
    atr_pct: Decimal | float,
    mark_price: Decimal | float,
    filters: Filters,
) -> SizingResult:
    """§8.2, passo a passo — mesma sequência e mesmos nomes de variável do
    PRD. Função PURA: `filters` já resolvido pelo chamador (via
    `load_filters_asof` ou `compute_sizing_asof` abaixo) — isolar a
    aritmética Decimal do I/O de disco torna este o caminho testável com os
    exemplos numéricos do próprio PRD (§8.3), sem precisar de snapshot de
    `exchangeInfo` em disco.

    `risk_per_trade`/`sl_atr_mult` vêm de `constants.yaml` (Sprints 1/6),
    REUSADOS aqui, não redeclarados (CLAUDE.md: "nunca otimize de volta o que
    foi derivado")."""
    equity_d = _to_decimal(equity)
    atr_pct_d = _to_decimal(atr_pct)
    mark_price_d = _to_decimal(mark_price)

    risk_per_trade = _to_decimal(load_constant("risk_per_trade"))
    sl_atr_mult = _to_decimal(load_constant("sl_atr_mult"))

    # 1. orçamento de risco em dólares
    risk_usd = equity_d * risk_per_trade

    # 2. distância de stop
    stop_pct = sl_atr_mult * atr_pct_d
    if stop_pct == 0:
        raise ZeroStopDistanceError(
            f"stop_pct == 0 em t0={t0.isoformat()} (atr_pct={atr_pct_d}) — "
            "notional_req seria infinito; sinal deve ser rejeitado antes de chegar aqui"
        )

    # 3. nocional exigido
    notional_req = risk_usd / stop_pct

    # 4. quantização pelo filtro VIGENTE NA DATA (já resolvido pelo chamador)
    qty_raw = notional_req / mark_price_d
    qty = filters.floor_to_step(qty_raw)
    notional_real = qty * mark_price_d

    # 5. verificações duras
    risk_real = notional_real * stop_pct
    quant_error = (
        abs(notional_real - notional_req) / notional_req if notional_req != 0 else Decimal("0")
    )
    leverage_eff = notional_real / equity_d if equity_d != 0 else Decimal("0")
    unit_notional = filters.step_size * mark_price_d

    result = SizingResult(
        t0=t0,
        equity=equity_d,
        risk_usd=risk_usd,
        atr_pct=atr_pct_d,
        stop_pct=stop_pct,
        mark_price=mark_price_d,
        notional_req=notional_req,
        qty_raw=qty_raw,
        qty=qty,
        notional_real=notional_real,
        risk_real=risk_real,
        quant_error=quant_error,
        leverage_eff=leverage_eff,
        unit_notional=unit_notional,
        filters=filters,
    )
    logger.debug(
        "risk.sizing.compute_sizing",
        t0=t0.isoformat(),
        qty=str(qty),
        notional_real=str(notional_real),
        risk_real=str(risk_real),
        quant_error=str(quant_error),
        leverage_eff=str(leverage_eff),
    )
    return result


def compute_sizing_asof(
    *,
    t0: datetime,
    equity: Decimal | float,
    atr_pct: Decimal | float,
    mark_price: Decimal | float,
    symbol: str = "BTCUSDT",
    snapshots_dir: Path | None = None,
) -> SizingResult:
    """Wrapper "real" de `compute_sizing`: resolve `filters` via
    `load_filters_asof(t0)` (§1.4, REUSA `src.exchange.filters`, B01-safe —
    nunca "o filtro de hoje" aplicado a uma decisão histórica) e delega o
    resto. É este o entry point que o Risk Engine (ou um backtest) chama de
    verdade; `compute_sizing` fica isolado para teste unitário puro."""
    filters = load_filters_asof(t0, symbol=symbol, snapshots_dir=snapshots_dir)
    return compute_sizing(
        t0=t0, equity=equity, atr_pct=atr_pct, mark_price=mark_price, filters=filters
    )


__all__ = [
    "SizingResult",
    "ZeroStopDistanceError",
    "compute_sizing",
    "compute_sizing_asof",
]
