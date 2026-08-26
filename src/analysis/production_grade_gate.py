"""Gate 0 de produção — ADR-005 §12, virando artefato reproduzível.

**Por que este módulo existe.** `docs/ADR-005_arquitetura_do_feature_engine_
2026-08-26.md` §12 decide a grade de produção (R3 em 4 ativos, BTCUSDT/R3
excluída) com matemática financeira real — mas até aqui essa matemática
existia só em prosa/tabela do documento, calculada à mão. §12.8 registra
isso como o gap de maior retorno: "`src/analysis/feasibility.py` tem
`trades_per_year_budget` e `breakeven_win_rate` e não tem `__main__` — a
aritmética de §12.4 existe em código e nunca virou artefato." Este módulo
fecha esse gap: as MESMAS três contas de §12 (teto R1 por ativo, capacidade
vs. demanda sob orçamento compartilhado, `ρ` mínimo exigido), como núcleo
puro testável + casca que lê os artefatos JÁ MEDIDOS do repo.

**Isto NÃO decide nada novo.** Reproduz §12 a partir de dado real; não
recalibra critério, não promove/aposenta feature (isso é §1-§9, REPROVADO
em §11) e não é consumido por nenhum pipeline de treino/execução — mesmo
status DECISION-SUPPORT de `feasibility.py` (nenhum `src/execution/`/
backtest lê este número pra decidir uma ordem).

**Fontes, todas já persistidas (nenhuma medição nova aqui):**
- `stop_pct` de produção por (symbol, resolution_id): `stop_pct_cell` da
  célula em `sanidade_centro_da_grade.celula_de_producao_na_grade[0]` de
  `experiments/s1_tp_sl_sensitivity_report_{R}.json`, média long/short.
  Mesma limitação que o próprio §12.8 já registra: usa a geometria GLOBAL
  de produção, não overrides por combo de
  `config/barrier_geometry_by_combo.yaml` — reportado, não escondido.
- `step_size`/`min_notional` reais por ativo: `src.exchange.filters.
  load_filters_asof` (snapshot de `exchangeInfo`), não o escalar
  BTC-único de `constants.yaml` (`AG-165`/`AG-190`).
- Preço: mediana de `close` em `src.data.lake.query_dollar_bars` — dado
  real, não suposto.
- Demanda (taxa de sinal medida): opcional, de um relatório de análise já
  gerado (`--demand-report`); se ausente, a linha reporta
  `demanda_trades_mes_medida: null` em vez de inventar um número (B23).

`equity` é parâmetro OBRIGATÓRIO, nunca constante/cache (B17 — "cache
local de equity" é banido; reconciliação é a única fonte). Este módulo não
lê saldo de lugar nenhum: quem chama fornece o último equity reconciliado."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import polars as pl
import structlog
from scipy.stats import norm

from src.data import lake
from src.exchange.filters import load_filters_asof
from src.features.groups.group_e import round_trip_cost_bps
from src.labels._constants import load_constant

logger = structlog.get_logger(__name__)

EXPERIMENTS_DIR: Final[Path] = Path("experiments")

#: Universo de 5 ativos do projeto (PLANO_MESTRE_PRINCE2.md §15).
SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")

RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")

_BPS_PER_UNIT: Final[float] = 10_000.0  # noqa: magic-number -- conversão de unidade


class ProductionGradeGateError(RuntimeError):
    """Erro estrutural — artefato de origem ausente ou schema inesperado.
    Nunca cai num número inventado (Regra Zero)."""


# ============================================================================
# Núcleo puro — zero IO (Idioma A)
# ============================================================================


def stop_max_pct(*, equity: float, risk_per_trade: float, step_size: float, price: float) -> float:
    """Teto R1 do stop (§0.2 R1, §12.2): acima deste `stop_pct`, o lote
    mínimo (`step_size`) já viola `N_req/unit >= 2` para o `risk_per_trade`
    orçado.

        unit_notional = step_size * price
        stop_max      = (equity * risk_per_trade) / (2 * unit_notional)
    """
    unit_notional = step_size * price
    if unit_notional <= 0.0:
        raise ProductionGradeGateError(
            f"unit_notional={unit_notional!r} não positivo (step_size={step_size!r}, "
            f"price={price!r}) -- stop_max indefinido"
        )
    return (equity * risk_per_trade) / (2.0 * unit_notional)


def r1_ceiling_violated(*, stop_pct: float, stop_max: float) -> bool:
    """`True` se a geometria de produção desta célula excede o teto R1
    deste ativo -- a célula sai da grade (§12.2), não o ativo inteiro."""
    return stop_pct > stop_max


def cost_usd_per_trade(
    *, equity: float, risk_per_trade: float, stop_pct: float, cost_bps: float
) -> float:
    """Custo round-trip em USD de UM trade nesta célula (§12.1).

    Erro-v1 corrigido em §12.7: custo NÃO é fixo entre grades. `notional`
    é função de `stop_pct` (mesmo `risk_per_trade`, stop maior => nocional
    menor => menos fee por trade):

        notional = equity * risk_per_trade / stop_pct
        custo    = notional * (cost_bps / 10_000)
    """
    if stop_pct <= 0.0:
        raise ProductionGradeGateError(
            f"stop_pct={stop_pct!r} não positivo -- custo/trade indefinido"
        )
    notional = (equity * risk_per_trade) / stop_pct
    return notional * (cost_bps / _BPS_PER_UNIT)


def capacity_trades_per_month(
    *, fee_budget_monthly: float, equity: float, cost_per_trade_usd: float
) -> float:
    """Quantos trades cabem no orçamento MENSAL de fee (§0.2 R3), dado o
    custo/trade desta célula. `fee_budget_monthly * equity` é o orçamento
    em USD -- COMPARTILHADO pelos 5 ativos (erro-v1 #2 de §12.7: não
    multiplicar por `n_symbols`, é o mesmo `equity`)."""
    if cost_per_trade_usd <= 0.0:
        raise ProductionGradeGateError(f"cost_per_trade_usd={cost_per_trade_usd!r} não positivo")
    return (fee_budget_monthly * equity) / cost_per_trade_usd


def inverse_mills_ratio(q: float) -> float:
    """`λ(q) = φ(Φ⁻¹(1−q)) / q` -- razão de Mills inversa, retorno esperado
    (em desvios-padrão) de selecionar o top-`q` de uma normal padrão.
    `q` é a fração de barras selecionadas (§12.5)."""
    if not 0.0 < q < 1.0:
        raise ProductionGradeGateError(f"q={q!r} fora de (0, 1) -- fração de seleção indefinida")
    cutoff = norm.ppf(1.0 - q)
    return float(norm.pdf(cutoff) / q)


def rho_minimo(*, mu: float, sigma: float, q: float) -> float:
    """`ρ_mínimo = −μ / (σ · λ(q))` (§12.5) -- correlação score↔retorno
    mínima para que `E[r | top q] = μ + σ·ρ·λ(q)` cruze zero. `μ` é o
    retorno médio bruto por trade (comum entre grades, §12.3); `σ` é o
    desvio da grade -- é o que muda a conta entre R1/R2/R3."""
    if sigma <= 0.0:
        raise ProductionGradeGateError(f"sigma={sigma!r} não positivo -- rho_minimo indefinido")
    lam = inverse_mills_ratio(q)
    return -mu / (sigma * lam)


# ============================================================================
# Linha por (symbol, resolution_id) -- ainda núcleo puro, recebe dado já
# extraído pela casca.
# ============================================================================


@dataclass(frozen=True, slots=True)
class GradeGateRow:
    symbol: str
    resolution_id: str
    step_size: float
    price_mediano: float
    unit_notional: float
    stop_pct_producao: float
    stop_max_pct: float
    r1_teto_violado: bool
    cost_usd_por_trade: float
    capacidade_trades_mes: float
    demanda_trades_mes_medida: float | None
    veredito: str


def build_grade_gate_row(
    *,
    symbol: str,
    resolution_id: str,
    step_size: float,
    price_mediano: float,
    stop_pct_producao: float,
    equity: float,
    risk_per_trade: float,
    fee_budget_monthly: float,
    cost_bps: float,
    demanda_trades_mes_medida: float | None,
) -> GradeGateRow:
    """Compõe as três contas de §12 (teto R1, custo/capacidade, veredito)
    para UMA célula (symbol, resolution_id). `demanda_trades_mes_medida`
    vem de fora -- este módulo não mede taxa de sinal, só compõe o que já
    foi medido em outro lugar; `None` quando não há medição disponível
    (nunca um número inventado, B23)."""
    unit_notional = step_size * price_mediano
    smax = stop_max_pct(
        equity=equity, risk_per_trade=risk_per_trade, step_size=step_size, price=price_mediano
    )
    violado = r1_ceiling_violated(stop_pct=stop_pct_producao, stop_max=smax)

    cost = cost_usd_per_trade(
        equity=equity, risk_per_trade=risk_per_trade, stop_pct=stop_pct_producao, cost_bps=cost_bps
    )
    capacidade = capacity_trades_per_month(
        fee_budget_monthly=fee_budget_monthly, equity=equity, cost_per_trade_usd=cost
    )

    if violado:
        veredito = "excluida_teto_r1"
    elif demanda_trades_mes_medida is None:
        veredito = "sem_demanda_medida"
    elif demanda_trades_mes_medida <= capacidade:
        veredito = "cabe"
    else:
        veredito = "estoura_orcamento"

    return GradeGateRow(
        symbol=symbol,
        resolution_id=resolution_id,
        step_size=step_size,
        price_mediano=price_mediano,
        unit_notional=unit_notional,
        stop_pct_producao=stop_pct_producao,
        stop_max_pct=smax,
        r1_teto_violado=violado,
        cost_usd_por_trade=cost,
        capacidade_trades_mes=capacidade,
        demanda_trades_mes_medida=demanda_trades_mes_medida,
        veredito=veredito,
    )


# ============================================================================
# Casca -- resolve arquivo, lê e persiste.
# ============================================================================


def _load_production_stop_pct(resolution_id: str, *, out_dir: Path) -> dict[str, float]:
    """`stop_pct_cell` médio (long/short) na célula de produção, por
    símbolo, de `s1_tp_sl_sensitivity_report_{R}.json`. Mesma limitação já
    registrada em §12.8: usa a célula de produção GLOBAL
    (`sanidade_centro_da_grade`), não overrides por combo."""
    path = out_dir / f"s1_tp_sl_sensitivity_report_{resolution_id}.json"
    if not path.exists():
        raise ProductionGradeGateError(
            f"relatório S1 de {resolution_id} não encontrado em {path.resolve()} -- "
            "rode src.analysis.s1_tp_sl_sensitivity para esta resolução antes."
        )
    with path.open(encoding="utf-8") as fh:
        report: dict[str, Any] = json.load(fh)

    sanidade = report.get("sanidade_centro_da_grade") or {}
    cell_keys = sanidade.get("celula_de_producao_na_grade")
    if not cell_keys:
        raise ProductionGradeGateError(
            f"{path}: 'sanidade_centro_da_grade.celula_de_producao_na_grade' vazio -- "
            "geometria de produção vigente não está coberta pelo grid deste sweep S1"
        )
    cell_key = cell_keys[0]

    by_symbol = report.get("by_symbol") or {}
    out: dict[str, float] = {}
    for symbol, sym_block in by_symbol.items():
        stops: list[float] = []
        for side_block in (sym_block.get("by_side") or {}).values():
            cell = (side_block.get("cells") or {}).get(cell_key)
            if cell is not None and "stop_pct_cell" in cell:
                stops.append(float(cell["stop_pct_cell"]))
        if not stops:
            raise ProductionGradeGateError(
                f"{path}: símbolo {symbol!r} sem célula {cell_key!r} em nenhum lado"
            )
        out[str(symbol)] = sum(stops) / len(stops)
    return out


def _load_median_price(symbol: str, resolution_id: str) -> float:
    """Preço mediano REAL (`close`, `data.lake.query_dollar_bars`) -- não
    suposto, não vindo de `PRICE_FILTER` (que é faixa permitida, não
    preço de mercado)."""
    bars = lake.query_dollar_bars(symbol, resolution_id=resolution_id)
    if bars.height == 0:
        raise ProductionGradeGateError(
            f"query_dollar_bars({symbol}, {resolution_id}) devolveu 0 barras"
        )
    return float(bars.select(pl.col("close").median()).item())


def _load_demand_by_symbol_resolution(path: Path | None) -> dict[tuple[str, str], float]:
    """Taxa de sinal medida (trades/mês), de um relatório de análise já
    gerado -- schema `{"by_cell": [{"symbol", "resolution_id",
    "trades_per_month"}, ...]}`. Ausente/`None` => dict vazio, cada célula
    reporta `demanda_trades_mes_medida: null` (§12.8: 'ρ real do modelo
    por célula' é medição pendente, não fabricada aqui)."""
    if path is None or not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        payload: dict[str, Any] = json.load(fh)
    out: dict[tuple[str, str], float] = {}
    for row in payload.get("by_cell", []):
        out[(str(row["symbol"]), str(row["resolution_id"]))] = float(row["trades_per_month"])
    return out


def _write_atomic(path: Path, content: str) -> Path:
    """B29 -- `.tmp` -> `fsync` -> `rename`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    fd = os.open(tmp, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


def run_production_grade_gate_report(
    *,
    equity: float,
    asof: date,
    symbols: Sequence[str] = SYMBOLS,
    resolutions: Sequence[str] = RESOLUTIONS,
    out_dir: Path = EXPERIMENTS_DIR,
    demand_report_path: Path | None = None,
) -> Path:
    """Casca: monta as 15 células (symbol, resolution_id), persiste
    `experiments/production_grade_gate_report.json`. `equity` e `asof` são
    OBRIGATÓRIOS e vêm de quem chama (último equity reconciliado, B17;
    data explícita, B01) -- este módulo nunca presume nenhum dos dois."""
    risk_per_trade = float(load_constant("risk_per_trade"))
    fee_budget_monthly = float(load_constant("fee_budget_monthly"))
    maker_fee = float(load_constant("maker_fee"))
    taker_fee = float(load_constant("taker_fee"))
    cost_bps = round_trip_cost_bps(maker_fee, taker_fee)

    demand = _load_demand_by_symbol_resolution(demand_report_path)

    rows: list[GradeGateRow] = []
    for resolution_id in resolutions:
        stop_pct_by_symbol = _load_production_stop_pct(resolution_id, out_dir=out_dir)
        for symbol in symbols:
            if symbol not in stop_pct_by_symbol:
                raise ProductionGradeGateError(
                    f"{symbol}/{resolution_id}: sem stop_pct_cell no relatório S1 -- "
                    "símbolo ausente do sweep dessa resolução"
                )
            filters = load_filters_asof(asof, symbol=symbol)
            price = _load_median_price(symbol, resolution_id)
            row = build_grade_gate_row(
                symbol=symbol,
                resolution_id=resolution_id,
                step_size=float(filters.step_size),
                price_mediano=price,
                stop_pct_producao=stop_pct_by_symbol[symbol],
                equity=equity,
                risk_per_trade=risk_per_trade,
                fee_budget_monthly=fee_budget_monthly,
                cost_bps=cost_bps,
                demanda_trades_mes_medida=demand.get((symbol, resolution_id)),
            )
            rows.append(row)
            logger.info(
                "analysis.production_grade_gate.row",
                symbol=symbol,
                resolution_id=resolution_id,
                stop_pct_producao=round(row.stop_pct_producao, 6),
                stop_max_pct=round(row.stop_max_pct, 6),
                veredito=row.veredito,
            )

    resumo_por_grade: dict[str, dict[str, Any]] = {}
    for resolution_id in resolutions:
        grade_rows = [r for r in rows if r.resolution_id == resolution_id]
        elegiveis = [r for r in grade_rows if r.veredito != "excluida_teto_r1"]
        demandas_medidas = [
            r.demanda_trades_mes_medida
            for r in elegiveis
            if r.demanda_trades_mes_medida is not None
        ]
        excluidos = sorted(r.symbol for r in grade_rows if r.veredito == "excluida_teto_r1")
        resumo_por_grade[resolution_id] = {
            "n_simbolos": len(grade_rows),
            "n_excluidos_teto_r1": len(grade_rows) - len(elegiveis),
            "simbolos_excluidos_teto_r1": excluidos,
            "capacidade_trades_mes_soma_elegiveis": sum(r.capacidade_trades_mes for r in elegiveis),
            "demanda_trades_mes_soma_medida": sum(demandas_medidas) if demandas_medidas else None,
            "n_simbolos_com_demanda_medida": len(demandas_medidas),
        }

    payload = {
        "task": "production_grade_gate",
        "pergunta": "ADR-005 §12 como artefato: teto R1 por ativo, capacidade vs. demanda sob "
        "orcamento compartilhado, por (symbol, resolution_id).",
        "adr_ref": "docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md §12",
        "formula_stop_max": "stop_max = (equity * risk_per_trade) / (2 * step_size * price)",
        "formula_custo_trade": "custo = (equity * risk_per_trade / stop_pct) * (cost_bps / 10000)",
        "formula_capacidade": "capacidade_trades_mes = (fee_budget_monthly * equity) / custo_trade",
        "ressalva_stop_pct": "usa a celula de producao GLOBAL de cada sweep S1 "
        "(sanidade_centro_da_grade), nao overrides por combo de "
        "config/barrier_geometry_by_combo.yaml -- mesma limitacao ja registrada em ADR-005 §12.8.",
        "equity_usd": equity,
        "asof": asof.isoformat(),
        "risk_per_trade": risk_per_trade,
        "fee_budget_monthly": fee_budget_monthly,
        "cost_bps_round_trip": cost_bps,
        "rows": [asdict(r) for r in rows],
        "resumo_por_grade": resumo_por_grade,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    report_path = _write_atomic(
        out_dir / "production_grade_gate_report.json",
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    logger.info(
        "analysis.production_grade_gate.done",
        report_path=str(report_path.resolve()),
        n_rows=len(rows),
        n_excluidas_teto_r1=sum(1 for r in rows if r.veredito == "excluida_teto_r1"),
    )
    return report_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Gate 0 de produção (ADR-005 §12) -- teto R1, capacidade vs. demanda."
    )
    parser.add_argument(
        "--equity",
        type=float,
        required=True,
        help="Equity reconciliado (USD) -- NUNCA um valor cacheado (B17).",
    )
    parser.add_argument(
        "--asof",
        type=str,
        required=True,
        help="Data (YYYY-MM-DD) p/ filtros de instrumento vigentes (B01) -- não presume 'hoje'.",
    )
    parser.add_argument(
        "--demand-report",
        type=str,
        default=None,
        help="Relatório opcional com taxa de sinal medida por célula (schema 'by_cell').",
    )
    args = parser.parse_args()

    out_path = run_production_grade_gate_report(
        equity=args.equity,
        asof=date.fromisoformat(args.asof),
        demand_report_path=Path(args.demand_report) if args.demand_report else None,
    )
    logger.info("analysis.production_grade_gate.cli_done", report_path=str(out_path.resolve()))
