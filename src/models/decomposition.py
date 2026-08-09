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

from src.core.metric import Metric, Unit, safe_ratio

from . import backtest_lite
from ._constants import load_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

# Fator bps -> fração — definição matemática (mesma categoria de
# `_BPS_PER_UNIT` em `src.labels.triple_barrier`), não constante de domínio.
_BPS_PER_UNIT = 10_000  # noqa: magic-number

# `Metric.source` para todo campo produzido por `decompose()` — a função é
# pura (não sabe se `trades` veio do pooled de 15 splits ou de um
# `path_id` isolado; essa distinção é responsabilidade de quem chama, ver
# `src.models.pipeline`), então o `source` aponta para o CÓDIGO que
# calculou o valor, não para o artefato upstream. `decompose()` aceita
# `source` como override explícito (kwarg com default, não quebra a
# chamada posicional existente em `src.models.pipeline.run_layer1_sprint`)
# para quando o chamador tiver contexto melhor (ex. "alpha_layer1_report::
# pooled_all_15_splits").
_DEFAULT_SOURCE = "models.decomposition.decompose"

_N_SEMANTICS_TRADES = "trades"


@dataclass(frozen=True, slots=True)
class DecompositionResult:
    n_trades: int
    pnl_total: Metric
    pnl_direcional: Metric
    pnl_carry: Metric
    pnl_execucao: Metric
    carry_share: Metric
    total_sharpe: Metric
    directional_sharpe: Metric
    side_carry_asymmetry: Metric
    gate3_directional_positive: bool
    gate3_carry_share_ok: bool


def _empty_metric(unit: Unit, source: str, *, reason: str) -> Metric:
    return Metric(
        value=float("nan"),
        unit=unit,
        n=0,
        n_semantics=_N_SEMANTICS_TRADES,
        source=source,
        valid=False,
        invalid_reason=reason,
    )


def decompose(trades: pl.DataFrame, *, source: str = _DEFAULT_SOURCE) -> DecompositionResult:
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
    sobrevivente muda.

    `source` identifica a origem do `Metric` resultante (ex.
    `"experiments/alpha_layer1_report.json::pooled_all_15_splits"`) — por
    padrão aponta para esta própria função, já que `decompose()` não tem
    como saber se `trades` é o pooled de 15 splits ou um `path_id` isolado
    (essa distinção é de quem chama)."""
    if trades.is_empty():
        empty_reason = "trades vazio — nenhum trade executado na amostra"
        return DecompositionResult(
            n_trades=0,
            pnl_total=_empty_metric(Unit.FRACTION_OF_NOTIONAL, source, reason=empty_reason),
            pnl_direcional=_empty_metric(Unit.FRACTION_OF_NOTIONAL, source, reason=empty_reason),
            pnl_carry=_empty_metric(Unit.FRACTION_OF_NOTIONAL, source, reason=empty_reason),
            pnl_execucao=_empty_metric(Unit.FRACTION_OF_NOTIONAL, source, reason=empty_reason),
            carry_share=_empty_metric(Unit.RATIO, source, reason=empty_reason),
            total_sharpe=_empty_metric(Unit.SHARPE_ANNUALIZED, source, reason=empty_reason),
            directional_sharpe=_empty_metric(Unit.SHARPE_ANNUALIZED, source, reason=empty_reason),
            side_carry_asymmetry=_empty_metric(
                Unit.FRACTION_OF_NOTIONAL, source, reason=empty_reason
            ),
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

    n_trades = int(trades.height)

    def _pnl_metric(value: float) -> Metric:
        return Metric(
            value=value,
            unit=Unit.FRACTION_OF_NOTIONAL,
            n=n_trades,
            n_semantics=_N_SEMANTICS_TRADES,
            source=source,
        )

    pnl_direcional = _pnl_metric(float(np.sum(pnl_direcional_series)))
    pnl_carry = _pnl_metric(float(np.sum(pnl_carry_series)))
    pnl_execucao = _pnl_metric(float(np.sum(pnl_execucao_series)))
    pnl_total = _pnl_metric(float(np.sum(ret_net)))

    # Achado nº1 da auditoria: `carry_share = pnl_carry / pnl_total` sem
    # checar o sinal de `pnl_total` "passa" o gate3 por acidente quando
    # `pnl_total` é negativo (é, nos dados reais de hoje) — a razão de dois
    # negativos fica positiva e pequena mesmo quando o funding domina o
    # resultado, testando o sinal errado do que o gate pretende. `safe_ratio`
    # com `require_den_positive=True` torna isso `valid=False` em vez de um
    # número que passa por acaso — NÃO redefine a fórmula (correção da
    # fórmula em si, ex. `pnl_carry / (pnl_direcional + pnl_carry)`, é
    # deliberadamente adiada para outra rodada; só o guard de validade
    # entra agora).
    carry_share = safe_ratio(
        pnl_carry,
        pnl_total,
        require_den_positive=True,
        unit=Unit.RATIO,
        n_semantics=_N_SEMANTICS_TRADES,
        source=source,
    )

    span = backtest_lite.span_seconds(trades["t0"])
    directional_sharpe_value, _ = backtest_lite.sharpe_naive(
        pnl_direcional_series, span_seconds=span
    )
    total_sharpe_value, _ = backtest_lite.sharpe_naive(ret_net, span_seconds=span)
    directional_sharpe = Metric(
        value=directional_sharpe_value,
        unit=Unit.SHARPE_ANNUALIZED,
        n=n_trades,
        n_semantics=_N_SEMANTICS_TRADES,
        source=source,
    )
    total_sharpe = Metric(
        value=total_sharpe_value,
        unit=Unit.SHARPE_ANNUALIZED,
        n=n_trades,
        n_semantics=_N_SEMANTICS_TRADES,
        source=source,
    )

    long_carry = pnl_carry_series[side > 0]
    short_carry = pnl_carry_series[side < 0]
    side_carry_asymmetry_value = (
        float(np.mean(long_carry) - np.mean(short_carry))
        if long_carry.size and short_carry.size
        else float("nan")
    )
    side_carry_asymmetry = _pnl_metric(side_carry_asymmetry_value)

    carry_share_max = float(load_constant("alpha_gate3_carry_share_max"))
    gate3_directional_positive = bool(
        np.isfinite(directional_sharpe.value) and directional_sharpe.value > 0.0
    )
    # B3 do escopo desta task ("gate que recebe Metric inválido FALHA, não
    # passa"): `carry_share.valid` é `False` quando `pnl_total <= 0`
    # (guard de `safe_ratio` acima) — o gate3 nunca mais "passa por
    # acidente" nesse caso. Decisão explícita (documentada aqui e no
    # relatório da task): estado binário, não um terceiro valor
    # None/"indeterminado" — `gate3_carry_share_ok` continua `bool` no
    # dataclass; Metric inválido reprova o gate em vez de indeterminá-lo,
    # coerente com a postura de risco do resto do repo (nunca "passa" por
    # ausência de evidência).
    gate3_carry_share_ok = bool(carry_share.valid and abs(carry_share.value) < carry_share_max)

    result = DecompositionResult(
        n_trades=n_trades,
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
        carry_share=result.carry_share.value,
        carry_share_valid=result.carry_share.valid,
        directional_sharpe=result.directional_sharpe.value,
        total_sharpe=result.total_sharpe.value,
        gate3_directional_positive=result.gate3_directional_positive,
        gate3_carry_share_ok=result.gate3_carry_share_ok,
    )
    return result
