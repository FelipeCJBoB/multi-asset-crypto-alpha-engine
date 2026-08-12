"""Gate 0 — economia de viabilidade por ativo (PRD_V4_1.md §0.2/§1.4/§1.5).

Duas famílias de função, ambas DECISION-SUPPORT — nenhuma consumida em
runtime de execução (não existe `src/execution/`/backtest ainda que leia
estes números pra decidir uma ordem). O consumidor é humano/Gate 0: decidir
ANTES de gastar `N_lifetime` (trials) se um (ativo, geometria de barreira)
tem edge geometricamente possível.

**1. `breakeven_win_rate` / `trades_per_year_budget`** — "que taxa de
acerto eu preciso, e quantos trades cabem no orçamento de fee, dado
`custo_atr` deste ativo". Nenhuma das duas tinha implementação em código
antes (achado 2026-08-12, ver `PRD_V4_1.md` §0.2) — só existiam calculadas
à mão quando o PRD foi escrito. Duas variantes de `breakeven_win_rate`
declaradas explicitamente por rigor decrescente-mas-honesto:

- `breakeven_win_rate_naive`: usa `custo_atr` (custo médio 50/50 maker/
  taker) — derivação EV=0 literal de §1.5 ("edge_bruto_atr mínimo para EV
  zero é exatamente custo_atr"). **Medido, não suposto (achado
  2026-08-12):** reproduz 2 dos 5 números originais do §0.2 (SOL/XRP)
  dentro de ~0,10pp, mas ETH/BTC/BNB ficam entre 0,16 e 0,24pp de
  distância — gap real, sem nota de derivação recuperável no repo pra
  explicá-lo, então não dá pra saber se está na fórmula ou na conta
  manual original (este mesmo PRD já precisou corrigir número calculado
  à mão duas vezes, §0.2 ressalva). Ver
  `tests/unit/test_analysis_feasibility.py` pro gap exato por ativo.
- `breakeven_win_rate`: separa o custo por DESFECHO (`TP` sempre sai
  maker; `SL`/`TIME` sempre saem taker — §9.1, `triple_barrier.py` item 8
  da docstring do módulo). Mais correto porque a saída NÃO é 50/50 de
  verdade — `cost_surface.py` já mediu isso sobre dado real: a perna
  taker é 53% do custo total round-trip, não 50%. Diverge da versão
  naive por ~0,1-0,3pp nos números medidos deste projeto (R:R grande
  o suficiente que a assimetria maker/taker quase não move o breakeven)
  mas é a formulação tecnicamente correta, não uma aproximação.

**2. `edge_bruto_atr` / `edge_liq_atr` / `captura`** — a álgebra que
PRD_V4_1.md §1.4 declara invariante obrigatória ("todo relatório emite...")
e §1.2 dá a fórmula exata:

    edge_bruto_atr = frac_TP × tp_mult − frac_SL × sl_mult
    edge_liq_atr   = edge_bruto_atr − custo_atr
    captura        = edge_liq_atr / edge_bruto_atr

`edge_bruto_atr` precisa de `frac_TP`/`frac_SL` — a distribuição REAL de
`barrier_hit` em `labels.parquet`, estratificada por (symbol, tf, side,
regime) por mandato do §1.4. `frac_tp_sl_from_labels` faz essa agregação;
não fabrica a distribuição, lê o dado real.

Nenhuma constante nova aqui — tudo REUSA `constants.yaml` via os módulos
que já leem essas chaves (`src.risk._constants`, `src.features.groups.
group_e.round_trip_cost_bps`)."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from src.features.groups.group_e import round_trip_cost_bps


def breakeven_win_rate_naive(*, custo_atr: float, tp_atr_mult: float, sl_atr_mult: float) -> float:
    """Versão blended (custo médio 50/50 maker/taker via `custo_atr`).
    `WR = (sl_atr_mult + custo_atr) / (tp_atr_mult + sl_atr_mult)` —
    derivação: `EV=0` <=> `WR*tp - (1-WR)*sl - custo_atr = 0` (tudo em
    unidades de ATR, `custo_atr` já é custo/ATR por definição), resolvendo
    para `WR`. Reproduz os números do §0.2 original (SOL 46,5%, BTC 48,3%
    etc.) dentro de ~0,1pp usando os `custo_atr` originais daquela tabela."""
    return (sl_atr_mult + custo_atr) / (tp_atr_mult + sl_atr_mult)


def breakeven_win_rate(
    *,
    atr_pct: float,
    tp_atr_mult: float,
    sl_atr_mult: float,
    maker_fee: float,
    taker_fee: float,
) -> float:
    """Versão correta por desfecho — TP sempre sai maker, SL/TIME sempre
    saem taker (§9.1, `triple_barrier.py` item 8 da docstring do módulo,
    `cost_exit_frac`). Entrada é SEMPRE maker (GTX/post-only, B12).

        c_win  = maker_fee + maker_fee   (entrada + saída em TP)
        c_lose = maker_fee + taker_fee   (entrada + saída em SL/TIME)
        R      = tp_atr_mult * atr_pct * 10000   (ganho em bps se TP)
        Risk   = sl_atr_mult * atr_pct * 10000   (perda em bps se SL)

    `EV=0`: `WR*(R - c_win) - (1-WR)*(Risk + c_lose) = 0`, resolvendo:

        WR = (Risk + c_lose) / (R + Risk + c_lose - c_win)

    Diferente de `breakeven_win_rate_naive`: não assume a saída 50/50
    maker/taker que `custo_atr`/`round_trip_cost_bps` assumem por
    conveniência (a própria docstring de `round_trip_cost_bps` admite:
    "sem estimativa melhor da probabilidade condicional... 50/50 é a
    leitura mais simples"). `cost_surface.py` já mediu que a saída real
    é ~53% taker, não 50% -- esta versão não precisa dessa suposição
    porque separa o custo por desfecho de forma exata, não probabilística."""
    c_win_bps = (maker_fee + maker_fee) * 10000.0
    c_lose_bps = (maker_fee + taker_fee) * 10000.0
    reward_bps = tp_atr_mult * atr_pct * 10000.0
    risk_bps = sl_atr_mult * atr_pct * 10000.0
    denom = reward_bps + risk_bps + c_lose_bps - c_win_bps
    return (risk_bps + c_lose_bps) / denom


def trades_per_year_budget(
    *, custo_atr: float, sl_atr_mult: float, fee_budget_monthly: float, risk_per_trade: float
) -> float:
    """Quantos trades/ano cabem no orçamento de fee (`fee_budget_monthly ×
    equity`, §0.2 R3) antes de estourá-lo -- derivação a partir do zero
    (nenhuma função equivalente existia em código, achado 2026-08-12):

        c_usd_por_trade = (cost_bps/10000) × notional_real
        notional_real  ≈ equity × risk_per_trade / stop_pct   (pré-quantização,
                          nível de precisão de orçamento, não de execução)
        stop_pct        = sl_atr_mult × atr_pct
        trades/mês      = (fee_budget_monthly × equity) / c_usd_por_trade

    `equity` se CANCELA da razão (aparece em cima e embaixo) — o
    orçamento de trades não depende do tamanho do capital, só da
    geometria (`sl_atr_mult`) e da economia (`custo_atr`, que já embute
    `cost_bps`/`atr_pct`). Substituindo `cost_bps/10000 = custo_atr ×
    atr_pct` (definição de `custo_atr`) e simplificando, `atr_pct`
    TAMBÉM cancela:

        trades/mês = (fee_budget_monthly × sl_atr_mult) / (custo_atr × risk_per_trade)
        trades/ano = 12 × trades/mês

    **Reconciliação parcial, não perfeita — reportado, não escondido.**
    Aplicada aos `custo_atr` ORIGINAIS do §0.2 (SOL 0,131 → 824,4;
    BTC 0,199 → 542,7), esta fórmula fica ~4,6% ABAIXO dos números
    publicados na tabela original (862; 568) -- consistente nos dois
    pontos checados, o que sugere um fator constante faltando (o "N" da
    fórmula literal do PRD, `trades/mês <= (fee_budget_monthly × equity)
    / (N × c)`, citada em `constants.yaml::fee_budget_is_per_side`, cujo
    valor exato de N não está recuperável a partir da documentação hoje
    disponível) e não um erro de sinal ou de unidade. Usar esta função
    para ORDEM DE GRANDEZA e comparação RELATIVA entre ativos -- não
    tratar o valor absoluto como exato até essa reconciliação fechar."""
    trades_per_month = (fee_budget_monthly * sl_atr_mult) / (custo_atr * risk_per_trade)
    return 12.0 * trades_per_month


def custo_atr(*, atr_pct: float, maker_fee: float, taker_fee: float) -> float:
    """Wrapper fino sobre `round_trip_cost_bps` -- mesma fórmula de
    `group_e.e27f_cost_atr_ratio`, reexposta aqui por conveniência de
    quem já está no módulo de feasibility (não uma segunda
    implementação: chama a mesma função)."""
    cost_bps = round_trip_cost_bps(maker_fee, taker_fee)
    return cost_bps / (atr_pct * 10000.0)


def edge_bruto_atr(*, frac_tp: float, frac_sl: float, tp_atr_mult: float, sl_atr_mult: float) -> float:
    """PRD_V4_1.md §1.2: `frac_TP × tp_mult − frac_SL × sl_mult` —
    geometria de acerto normalizada por ATR, adimensional, SEM custo.
    `frac_TP`/`frac_SL` vêm de `frac_tp_sl_from_labels` (dado real de
    `labels.parquet::barrier_hit`), nunca inventadas aqui."""
    return frac_tp * tp_atr_mult - frac_sl * sl_atr_mult


def edge_liq_atr(*, edge_bruto: float, custo_atr_value: float) -> float:
    """§1.2: `edge_bruto_atr − custo_atr`."""
    return edge_bruto - custo_atr_value


def captura(*, edge_liq: float, edge_bruto: float) -> float:
    """§1.2: `edge_liq_atr / edge_bruto_atr` — fração do sinal bruto que
    sobrevive ao custo. `edge_bruto=0` não tem "fração de si mesma"
    definida -- NaN explícito, nunca `0/0` silencioso violando divisão
    sem guarda (achado de classe já catalogado, `audit/
    division_guard_audit.md`)."""
    if edge_bruto == 0:
        return float("nan")
    return edge_liq / edge_bruto


@dataclass(frozen=True, slots=True)
class BarrierFractions:
    """Distribuição real de `barrier_hit` para UM corte (symbol, tf, side,
    regime) — `n` é o denominador de todas as frações, reportado para que
    "0,0%" por amostra vazia nunca seja confundido com "0,0% medido"."""

    n: int
    frac_tp: float
    frac_sl: float
    frac_time: float
    frac_nofill: float


def frac_tp_sl_from_labels(labels: pl.DataFrame) -> BarrierFractions:
    """Agrega `barrier_hit` (`"TP"`/`"SL"`/`"TIME"`/`"NOFILL"`) de um
    `labels.parquet` (ou fatia dele, já filtrada por symbol/tf/side/regime
    pelo chamador — esta função não filtra, só agrega o que recebeu,
    §1.4 exige estratificação, não uma média cega). `n=0` devolve frações
    `NaN`, nunca `0.0` -- "não computável" não é o mesmo que "medido zero"
    (mesma disciplina de `NOT_COMPUTABLE`/`Metric.valid`, `src.core.metric`)."""
    n = labels.height
    if n == 0:
        nan = float("nan")
        return BarrierFractions(n=0, frac_tp=nan, frac_sl=nan, frac_time=nan, frac_nofill=nan)
    counts = labels.group_by("barrier_hit").agg(pl.len().alias("n")).to_dicts()
    by_label = {row["barrier_hit"]: row["n"] for row in counts}
    return BarrierFractions(
        n=n,
        frac_tp=by_label.get("TP", 0) / n,
        frac_sl=by_label.get("SL", 0) / n,
        frac_time=by_label.get("TIME", 0) / n,
        frac_nofill=by_label.get("NOFILL", 0) / n,
    )
