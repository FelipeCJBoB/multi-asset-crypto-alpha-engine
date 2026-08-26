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
  célula em `experiments/s1_tp_sl_sensitivity_report_{R}.json`, média
  long/short. **AG-317b/B8 (2026-08-26): overrides por combo aplicados**
  -- por símbolo, se `config/barrier_geometry_by_combo.yaml` tem geometria
  calibrada pra `(symbol, resolution_id)`, a célula usada é a DAQUELE
  combo (`_cell_key_for`); símbolo sem override cai na célula GLOBAL
  (`sanidade_centro_da_grade.celula_de_producao_na_grade[0]`), igual
  antes. Ver `_load_production_stop_pct`.
- `step_size`/`min_notional` reais por ativo: `src.exchange.filters.
  load_filters_asof` (snapshot de `exchangeInfo`), não o escalar
  BTC-único de `constants.yaml` (`AG-165`/`AG-190`).
- Preço: ÚLTIMO `close` real numa janela `[asof - price_lookback_days_gate0,
  asof]` (`config/constants.yaml`) via `src.data.lake.query_dollar_bars` —
  dado real, escopado a `asof` (B01). Não é mediana/média: uma estatística
  suavizada sobre semanas SUBESTIMA sistematicamente um ativo em tendência
  de alta (achado real, ver docstring de `_load_reference_price`) — o
  teto de quantização precisa do preço mais recente, não histórico.
- Demanda (taxa de sinal medida): opcional, de um relatório com o schema
  PRÓPRIO deste módulo (`--demand-report`, `{"by_cell": [...]}` — nenhum
  artefato existente no repo tem esse schema hoje, precisa de um
  adaptador dedicado); se ausente, a linha reporta
  `demanda_trades_mes_medida: null` em vez de inventar um número (B23).

`equity` é parâmetro OBRIGATÓRIO, nunca constante/cache (B17 — "cache
local de equity" é banido; reconciliação é a única fonte). Este módulo não
lê saldo de lugar nenhum: quem chama fornece o último equity reconciliado."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

import polars as pl
import structlog
from scipy.stats import norm

from src.analysis.s1_tp_sl_sensitivity import _RR_MAX_DENOMINATOR
from src.data import lake
from src.exchange.filters import load_filters_asof
from src.features.groups.group_e import round_trip_cost_bps
from src.labels._constants import load_constant
from src.labels.geometry_by_combo import load_barrier_geometry

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
    price_referencia: float
    unit_notional: float
    stop_pct_producao: float
    stop_max_pct: float
    r1_teto_violado: bool
    cost_usd_por_trade: float
    capacidade_trades_mes: float
    demanda_trades_mes_medida: float | None
    veredito: str


def aggregate_grade_capacity(rows: Sequence[GradeGateRow]) -> dict[str, Any]:
    """Agrega capacidade/demanda de UMA grade a partir das linhas por
    símbolo já filtradas pra essa grade (SEM as excluídas por teto R1).

    **ACHADO CRITICAL, `project_assurance` 2026-08-26.** A v1 desta
    agregação fazia `sum(r.capacidade_trades_mes for r in elegiveis)` --
    errado. Cada `r.capacidade_trades_mes` (`capacity_trades_per_month`)
    já assume que AQUELE símbolo sozinho tem o orçamento MENSAL
    COMPARTILHADO inteiro (`fee_budget_monthly * equity`, mesmo `equity`
    pros 5 ativos). Somar N dessas linhas reconta o mesmo orçamento N
    vezes -- reintroduz, na agregação, o erro-v1 "orçamento × N" que
    `capacity_trades_per_month` corrige na função pura (§12.7). Medido
    contra dado real: R1 somava 248,8 contra os 48,0 corretos de §12.4
    (~5,18×, ≈ n_símbolos).

    **Correção**, sob a suposição de DIVISÃO IGUAL do orçamento entre os
    símbolos elegíveis: `capacidade_símbolo_real = (B/n) / custo_i`,
    `capacidade_total = Σ (B/n)/custo_i = (B/n) · Σ(1/custo_i) =
    média_i(B/custo_i)` -- algebricamente IDÊNTICA à média das
    `capacidade_trades_mes` por símbolo já computadas (cada uma assume
    `B` inteiro). Por isso a agregação correta é a MÉDIA, não a soma --
    matematicamente equivalente a dividir o orçamento em partes iguais
    antes de calcular. É aproximação de primeira ordem (divisão igual,
    não a alocação ótima por custo entre símbolos) -- reportado, não
    escondido, mesmo espírito da ressalva de `feasibility.py::
    trades_per_year_budget`."""
    demandas_medidas = [
        r.demanda_trades_mes_medida for r in rows if r.demanda_trades_mes_medida is not None
    ]
    capacidades = [r.capacidade_trades_mes for r in rows]
    media_capacidade = (sum(capacidades) / len(capacidades)) if capacidades else None
    return {
        "capacidade_trades_mes_grade": media_capacidade,
        "demanda_trades_mes_soma_medida": sum(demandas_medidas) if demandas_medidas else None,
        "n_simbolos_com_demanda_medida": len(demandas_medidas),
    }


def build_grade_gate_row(
    *,
    symbol: str,
    resolution_id: str,
    step_size: float,
    price_referencia: float,
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
    unit_notional = step_size * price_referencia
    smax = stop_max_pct(
        equity=equity, risk_per_trade=risk_per_trade, step_size=step_size, price=price_referencia
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
        price_referencia=price_referencia,
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


def _cell_key_for(tp_atr_mult: float, sl_atr_mult: float) -> str:
    """`"R{reward_risk}_S{sl_mult}"` -- MESMA convenção de célula usada por
    `s1_tp_sl_sensitivity.py` (`_production_cell_from_constants`,
    `_valid_cells_for_symbol`): `Fraction` limitada ao mesmo denominador
    máximo do grid (`_RR_MAX_DENOMINATOR`, reusado por import, não
    reimplementado com valor solto -- se o grid mudar de precisão, esta
    função acompanha automaticamente)."""
    rr = Fraction(tp_atr_mult / sl_atr_mult).limit_denominator(  # noqa: unguarded-ratio -- sl_atr_mult vem de constants.yaml/barrier_geometry_by_combo.yaml, multiplicador de ATR sempre > 0 por construção de domínio (mesma divisão sem guarda em s1_tp_sl_sensitivity.py::_production_cell_from_constants)
        _RR_MAX_DENOMINATOR
    )
    sl_frac = Fraction(sl_atr_mult).limit_denominator(_RR_MAX_DENOMINATOR)
    return f"R{rr}_S{sl_frac}"


def _load_production_stop_pct(resolution_id: str, *, out_dir: Path) -> dict[str, float]:
    """`stop_pct_cell` médio (long/short) na célula de produção, por
    símbolo, de `s1_tp_sl_sensitivity_report_{R}.json`.

    **AG-317b/B8 (2026-08-26): overrides por combo aplicados.** Antes,
    usava sempre a célula de produção GLOBAL (`sanidade_centro_da_grade`)
    -- limitação registrada em §12.8. Agora, por símbolo: se
    `config/barrier_geometry_by_combo.yaml` tem override pra
    `(symbol, resolution_id)` (`src.labels.geometry_by_combo.
    load_barrier_geometry`), a célula usada é a DAQUELE combo (mesma
    convenção de cell_key, `_cell_key_for`); símbolo sem override cai no
    cell_key GLOBAL, igual antes -- nunca inventa geometria pra combo
    ausente (mesmo contrato que `geometry_by_combo.py` já documenta)."""
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
    global_cell_key = cell_keys[0]

    by_symbol = report.get("by_symbol") or {}
    out: dict[str, float] = {}
    for symbol, sym_block in by_symbol.items():
        override = load_barrier_geometry(str(symbol), resolution_id)
        cell_key = (
            _cell_key_for(override.tp_atr_mult, override.sl_atr_mult)
            if override is not None
            else global_cell_key
        )
        stops: list[float] = []
        for side_block in (sym_block.get("by_side") or {}).values():
            cell = (side_block.get("cells") or {}).get(cell_key)
            if cell is not None and "stop_pct_cell" in cell:
                stops.append(float(cell["stop_pct_cell"]))
        if not stops:
            raise ProductionGradeGateError(
                f"{path}: símbolo {symbol!r} sem célula {cell_key!r} em nenhum lado"
                + (" (override por combo)" if override is not None else "")
            )
        out[str(symbol)] = sum(stops) / len(stops)
    return out


def _load_reference_price(
    symbol: str, resolution_id: str, *, asof: date, lookback_days: int
) -> float:
    """Último `close` REAL conhecido em `[asof - lookback_days, asof]`
    (`data.lake.query_dollar_bars`) -- não suposto, não vindo de
    `PRICE_FILTER` (que é faixa permitida, não preço de mercado).
    `lookback_days` é só a margem de segurança pra achar pelo menos uma
    barra (folga contra fim de semana/gap de dado); o preço usado é o
    ÚLTIMO da janela, não uma média/mediana sobre ela.

    **ACHADO HIGH, `project_assurance` 2026-08-26, com uma 2ª volta.** A
    v1 chamava `query_dollar_bars` SEM `start`/`end` -- lia o histórico
    INTEIRO (desde 2021-12), ignorando `asof` (violava B01). Corrigido
    pra MEDIANA sobre uma janela de `lookback_days`, mas isso ainda
    produzia um resultado ERRADO na prática: rodando ao vivo com
    `lookback_days=30`, a mediana de 30 dias de BTCUSDT saiu ~US$ 64.150
    -- deixando `BTCUSDT/R3` NA MARGEM de não violar o teto R1
    (diferença de ~0,0005pp), quando a intenção de §12.2/§12.6 é o preço
    ATUAL, não uma estatística suavizada sobre um mês. Uma mediana
    multi-semanal SUBESTIMA sistematicamente um ativo em tendência de
    alta (exatamente o caso do BTC nesta série) -- o teto de quantização
    precisa do preço mais recente disponível, que é o que decide o
    nocional de uma ordem HOJE, não uma média histórica. Trocado para
    "último close da janela"."""
    start = asof - timedelta(days=lookback_days)
    bars = lake.query_dollar_bars(symbol, start, asof, resolution_id=resolution_id)
    if bars.height == 0:
        raise ProductionGradeGateError(
            f"query_dollar_bars({symbol}, {start}..{asof}, {resolution_id}) devolveu 0 barras -- "
            "janela sem dado, ou asof anterior ao início da série"
        )
    return float(bars.sort("close_time").select(pl.col("close").last()).item())


def _load_demand_by_symbol_resolution(path: Path | None) -> dict[tuple[str, str], float]:
    """Taxa de sinal medida (trades/mês) -- schema PRÓPRIO deste módulo,
    `{"by_cell": [{"symbol", "resolution_id", "trades_per_month"}, ...]}`.
    Ausente/`None` => dict vazio, cada célula reporta
    `demanda_trades_mes_medida: null` (§12.8: 'ρ real do modelo por
    célula' é medição pendente, não fabricada aqui).

    **ACHADO HIGH, `project_assurance` 2026-08-26.** Este schema NÃO é
    compatível com `experiments/alpha_deep_analysis_2026-08-24.json`
    (schema real: array top-level de `{"symbol", "resolution",
    "decomposition": {"n_trades", ...}, "auc_real": {"n_eval_long"}}`) --
    apesar da v1 desta docstring implicar que era. Não existe hoje,
    neste repo, nenhuma função que derive trades/mês a partir de
    `n_trades`/`n_eval_long`; os números de demanda de §12.4
    (314,4/153,2/65,1) foram calculados por processo não versionado.
    Passar `alpha_deep_analysis_2026-08-24.json` direto em
    `--demand-report` HOJE levanta `ProductionGradeGateError` (schema
    inesperado) -- não mais um `AttributeError` não tratado (v1). Um
    adaptador que produza o schema `by_cell` a partir daquele relatório
    ainda precisa ser escrito -- TBD, não fabricado aqui (B23)."""
    if path is None or not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        payload: Any = json.load(fh)
    if not isinstance(payload, Mapping) or "by_cell" not in payload:
        raise ProductionGradeGateError(
            f"{path}: schema inesperado -- esperado {{'by_cell': [...]}} no nível "
            "superior. Este arquivo pode ser de outro relatório (schema diferente) -- "
            "precisa de um adaptador dedicado, não é lido diretamente por este módulo."
        )
    out: dict[tuple[str, str], float] = {}
    for row in payload["by_cell"]:
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
    lookback_days = int(load_constant("price_lookback_days_gate0"))
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
            price = _load_reference_price(
                symbol, resolution_id, asof=asof, lookback_days=lookback_days
            )
            row = build_grade_gate_row(
                symbol=symbol,
                resolution_id=resolution_id,
                step_size=float(filters.step_size),
                price_referencia=price,
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
        excluidos = sorted(r.symbol for r in grade_rows if r.veredito == "excluida_teto_r1")
        resumo_por_grade[resolution_id] = {
            "n_simbolos": len(grade_rows),
            "n_excluidos_teto_r1": len(grade_rows) - len(elegiveis),
            "simbolos_excluidos_teto_r1": excluidos,
            **aggregate_grade_capacity(elegiveis),
        }

    payload = {
        "task": "production_grade_gate",
        "pergunta": "ADR-005 §12 como artefato: teto R1 por ativo, capacidade vs. demanda sob "
        "orcamento compartilhado, por (symbol, resolution_id).",
        "adr_ref": "docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md §12",
        "formula_stop_max": "stop_max = (equity * risk_per_trade) / (2 * step_size * price)",
        "formula_custo_trade": "custo = (equity * risk_per_trade / stop_pct) * (cost_bps / 10000)",
        "formula_capacidade": "capacidade_trades_mes = (fee_budget_monthly * equity) / custo_trade "
        "por simbolo; capacidade_trades_mes_grade em resumo_por_grade e a MEDIA entre os "
        "simbolos elegiveis, nao a soma -- cada capacidade por simbolo ja assume o orcamento "
        "MENSAL COMPARTILHADO inteiro (ver aggregate_grade_capacity, ACHADO CRITICAL "
        "project_assurance 2026-08-26).",
        "ressalva_stop_pct": "AG-317b/B8 (2026-08-26): overrides por combo de "
        "config/barrier_geometry_by_combo.yaml aplicados por simbolo quando existentes; "
        "simbolo sem override cai na celula de producao GLOBAL de cada sweep S1 "
        "(sanidade_centro_da_grade), igual ao comportamento antigo.",
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
