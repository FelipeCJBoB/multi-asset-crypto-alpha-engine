"""Decomposição de PnL carry vs direcional — §16.6, RF-029.

```
PnL_direcional = qty x (P_exit - P_entry) x side        # movimento puro
PnL_carry      = - sum(funding_rate x notional x side)   # carregamento
PnL_execucao   = (P_fill - P_ref) x qty - fees            # slippage + fees
```

**Simplificação de escopo, documentada, não escondida: esta rodada não tem
Risk Engine (`qty`/`notional` são de `src/risk/`, Sprint 12, agente
paralelo — fora de alcance aqui).** A decomposição abaixo é feita
POR UNIDADE (equivalente a `qty = notional = 1`), usando diretamente as
colunas fracionárias já calculadas por `src.labels.triple_barrier`:

- `PnL_direcional_unit = ret_gross` (`side x (exit/fill - 1)`, já a
  fórmula do §16.6 por unidade)
- `PnL_carry_unit = -funding_bps/1e4` (`funding_bps` já é
  `sum(funding_rate) x side`, mesmo sinal do §16.6)
- `PnL_execucao_unit = -(cost_entry_bps + cost_exit_bps)/1e4`

Não há termo de `(P_fill - P_ref)` separado: `src.labels.triple_barrier`
documenta explicitamente (docstring, item 3) que ordens são LIMIT/maker —
preenchem exatamente no preço postado ou não preenchem (`NOFILL`), sem
slippage de execução além das taxas; `adverse_selection_bps` é reportado
mas deliberadamente NÃO subtraído de `ret_net` (mesma docstring, item 4) —
não pode reentrar aqui como se fosse.

**Reconciliação exata**, verificada como invariante/teste:
`PnL_direcional_unit + PnL_carry_unit + PnL_execucao_unit == ret_net`
(dentro de tolerância de ponto flutuante) — não é uma decomposição
aproximada, é a mesma soma que `triple_barrier.build_labels` já faz,
só separada em três termos em vez de um."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from . import backtest_lite
from ._constants import load_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

# Fator bps -> fração — definição matemática (mesma categoria de
# `_BPS_PER_UNIT` em `src.labels.triple_barrier`), não constante de domínio.
_BPS_PER_UNIT = 10_000  # noqa: magic-number


@dataclass(frozen=True, slots=True)
class DecompositionResult:
    n_trades: int
    pnl_total: float
    pnl_direcional: float
    pnl_carry: float
    pnl_execucao: float
    carry_share: float
    total_sharpe: float
    directional_sharpe: float
    side_carry_asymmetry: float
    gate3_directional_positive: bool
    gate3_carry_share_ok: bool


def decompose(trades: pl.DataFrame) -> DecompositionResult:
    """`trades` precisa ter `ret_gross, funding_bps, cost_entry_bps,
    cost_exit_bps, ret_net, side_hat, t0` — já restrito aos trades
    EXECUTADOS (`barrier_hit != "NOFILL"`; NOFILL tem `ret_*` e `*_bps`
    todos zero por construção, §3.2, então incluí-los não mudaria a soma,
    mas diluiria o Sharpe com "trades" que não aconteceram — filtrar é
    responsabilidade de quem chama, mesmo padrão de
    `src.models.backtest_lite`). `side_hat` (não `side`) porque
    `src.models.backtest_lite.realize_trades` junta por `[t0, side_hat] ==
    [t0, side]` e o polars descarta a coluna direita do join quando os
    nomes de chave diferem — o valor é o mesmo (o lado REALIZADO é sempre
    igual ao lado sinalizado, por construção do join), só o nome da coluna
    sobrevivente muda."""
    if trades.is_empty():
        return DecompositionResult(
            n_trades=0,
            pnl_total=float("nan"),
            pnl_direcional=float("nan"),
            pnl_carry=float("nan"),
            pnl_execucao=float("nan"),
            carry_share=float("nan"),
            total_sharpe=float("nan"),
            directional_sharpe=float("nan"),
            side_carry_asymmetry=float("nan"),
            gate3_directional_positive=False,
            gate3_carry_share_ok=False,
        )

    ret_gross = trades["ret_gross"].to_numpy().astype(np.float64)
    funding_frac = trades["funding_bps"].to_numpy().astype(np.float64) / _BPS_PER_UNIT
    cost_frac = (
        trades["cost_entry_bps"].to_numpy().astype(np.float64)
        + trades["cost_exit_bps"].to_numpy().astype(np.float64)
    ) / _BPS_PER_UNIT
    ret_net = trades["ret_net"].to_numpy().astype(np.float64)
    side = trades["side_hat"].to_numpy().astype(np.float64)

    pnl_direcional_series = ret_gross
    pnl_carry_series = -funding_frac
    pnl_execucao_series = -cost_frac

    reconciled = pnl_direcional_series + pnl_carry_series + pnl_execucao_series
    max_abs_diff = float(np.max(np.abs(reconciled - ret_net))) if ret_net.size else 0.0
    if max_abs_diff > 1e-6:  # noqa: magic-number — tolerância de ponto flutuante, mesma de §3.8
        logger.warning(
            "models.decomposition.reconciliation_gap",
            max_abs_diff=max_abs_diff,
            n_trades=int(trades.height),
        )

    pnl_direcional = float(np.sum(pnl_direcional_series))
    pnl_carry = float(np.sum(pnl_carry_series))
    pnl_execucao = float(np.sum(pnl_execucao_series))
    pnl_total = float(np.sum(ret_net))

    carry_share = pnl_carry / pnl_total if pnl_total != 0.0 else float("nan")

    span = backtest_lite.span_seconds(trades["t0"])
    directional_sharpe, _ = backtest_lite.sharpe_naive(pnl_direcional_series, span_seconds=span)
    total_sharpe, _ = backtest_lite.sharpe_naive(ret_net, span_seconds=span)

    long_carry = pnl_carry_series[side > 0]
    short_carry = pnl_carry_series[side < 0]
    side_carry_asymmetry = (
        float(np.mean(long_carry) - np.mean(short_carry))
        if long_carry.size and short_carry.size
        else float("nan")
    )

    carry_share_max = float(load_constant("alpha_gate3_carry_share_max"))
    gate3_directional_positive = bool(np.isfinite(directional_sharpe) and directional_sharpe > 0.0)
    gate3_carry_share_ok = bool(np.isfinite(carry_share) and abs(carry_share) < carry_share_max)

    result = DecompositionResult(
        n_trades=int(trades.height),
        pnl_total=pnl_total,
        pnl_direcional=pnl_direcional,
        pnl_carry=pnl_carry,
        pnl_execucao=pnl_execucao,
        carry_share=carry_share,
        total_sharpe=total_sharpe,
        directional_sharpe=directional_sharpe,
        side_carry_asymmetry=side_carry_asymmetry,
        gate3_directional_positive=gate3_directional_positive,
        gate3_carry_share_ok=gate3_carry_share_ok,
    )
    logger.info(
        "models.decomposition.decompose",
        n_trades=result.n_trades,
        carry_share=result.carry_share,
        directional_sharpe=result.directional_sharpe,
        total_sharpe=result.total_sharpe,
        gate3_directional_positive=result.gate3_directional_positive,
        gate3_carry_share_ok=result.gate3_carry_share_ok,
    )
    return result
