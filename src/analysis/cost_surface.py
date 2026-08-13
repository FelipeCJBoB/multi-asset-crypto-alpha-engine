"""Superfície de custo round-trip por (`tp_atr_mult`, `sl_atr_mult`) — varre
o grid classe A **nunca varrido** de `constants.yaml` (§16.10, Regra Zero) e
mede, por lado (long/short), quanto do custo round-trip vem da perna maker
(entrada, sempre; saída se `TP`) vs taker (saída se `SL`/`TIME`) — ligação
direta ao achado já citado no repo: a perna taker é 3,06 dos 5,78bps totais
do custo round-trip (53%).

**PÓS-HOC, EXPLORATÓRIO, NUNCA INSUMO DE TREINO.** Mesma classe de módulo
que `src.analysis.attribution` (ver docstring de lá): lê resultado
REALIZADO do Label Engine (`cost_entry_bps`/`cost_exit_bps`/`barrier_hit`,
já calculados por `src.labels.triple_barrier.build_labels`) para
DIAGNOSTICAR a geometria de payoff atual sob barreiras alternativas — nunca
para retreinar, selecionar feature, ou decidir `tp_atr_mult`/`sl_atr_mult`
automaticamente (isso continua sendo decisão humana registrada em
`constants.yaml`, §16.10 Regra 4: classe A exige varredura de
sensibilidade, não escolha automática pelo pico).

**`src.analysis` -> `src.labels` é permitido.** O contrato real de
`import-linter` (`pyproject.toml [tool.importlinter]`, contrato "labels só
é lido por models, validation, backtest") restringe só `src.exchange`,
`src.data`, `src.features`, `src.regime`, `src.risk`, `src.execution`,
`src.live`, `src.monitoring` — `src.analysis` não está nessa lista
(verificado contra o contrato tal como escrito no `pyproject.toml`, não
contra a leitura mais estrita do CLAUDE.md §"Layer hierarchy", que o
próprio comentário acima de `[tool.importlinter]` explica ser "ordem de
pipeline", não direção de import — só 4 regras sem ambiguidade viraram
contrato automatizado). Este módulo CHAMA a API pública do Label Engine
(`triple_barrier.LabelConfig`/`triple_barrier.build_labels_both_sides`) com
`tp_atr_mult`/`sl_atr_mult` diferentes — nunca edita
`src/labels/triple_barrier.py`.

**Reuso, não reimplementação.** `round_trip_cost_bps`
(`src.features.groups.group_e`, a fórmula `maker + 0,5·maker + 0,5·taker`)
é chamada aqui só como REFERÊNCIA fixa — a própria docstring dela declara
que 0,5/0,5 é "a leitura mais simples", não uma medição. O custo MEDIDO por
célula do grid não reimplementa essa fórmula: usa `cost_entry_bps`/
`cost_exit_bps` já calculados por `triple_barrier.build_labels` com a
fração REAL de saídas maker/taker daquela combinação de barreiras —
estritamente melhor que a suposição 50/50 porque `tp_atr_mult`/
`sl_atr_mult` são exatamente os parâmetros que mudam essa fração.

**Achado ao ler `triple_barrier.py` para este módulo (não estava no pedido
original, medido no código-fonte, não assumido):** `barrier_hit == "TIME"`
TAMBÉM paga taker na saída — `cost_exit_frac = maker_fee if barrier ==
"TP" else taker_fee` (única barreira com saída maker é `TP`). "TP fecha
maker, SL fecha taker" é uma simplificação de duas barreiras; a perna taker
de verdade agrupa `SL` **e** `TIME`. Reportado explicitamente como
`taker_exit_share_of_filled` abaixo — não silenciar essa nuance é
exatamente o tipo de coisa que CLAUDE.md pede pra medir antes de afirmar.

**Custo de rotular o grid inteiro — medido, não estimado.** Rotular a série
completa (~231 mil barras de 15m, 2020-01→2026-08, os dois lados) leva
~50-60s por combinação de barreiras (medido isoladamente antes de escrever
este módulo). O grid 3×3 completo (9 combinações) rodou de ponta a ponta em
**426,5s** (~7,1min) via `run_and_save_cost_surface_report()`, persistido em
`experiments/cost_surface_report.json` — bem abaixo do orçamento de tempo
disponível, por isso o grid final usou os 9 pontos cheios sobre a série
COMPLETA, não uma amostra (ver aviso de custo da task que originou este
módulo). `build_cost_surface_grid_for_symbol` carrega `bars_15m`/
`mark_1m`/`funding` do disco UMA VEZ e reusa para todas as células do grid
— eles não dependem de `tp_atr_mult`/`sl_atr_mult`, só o bloco de
barreiras muda por célula (`dataclasses.replace`)."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.core.metric import Metric, Unit, not_computable
from src.core.provenance import report_provenance
from src.data import lake
from src.data.resample import step_ms
from src.features.groups.group_e import round_trip_cost_bps
from src.labels import triple_barrier
from src.labels.triple_barrier import DateLike, LabelConfig

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

# src/analysis/cost_surface.py -> parents[0]=src/analysis, [1]=src,
# [2]=raiz do repo — mesmo padrão de src/labels/_paths.py (REPO_ROOT via
# __file__, não cwd(), pra rodar de qualquer diretório), duplicado aqui em
# vez de importado de `src.labels._paths` (privado ao pacote `labels`,
# mesma tática de não-acoplamento já documentada nos `_paths.py`
# existentes: cada pacote resolve seu próprio caminho de saída).
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "cost_surface_report.json"

_NOFILL = "NOFILL"
_TP = "TP"
_SL = "SL"
_TIME = "TIME"
_N_SEMANTICS_TRADES = "trades"

_SIDE_LABELS: Final[dict[int, str]] = {1: "long", -1: "short"}

# Variação do grid em torno do valor ATUAL de tp_atr_mult/sl_atr_mult em
# constants.yaml — decisão de VARREDURA EXPLORATÓRIA, não uma constante de
# domínio (essas continuam vivendo só em constants.yaml, §16.10 Regra
# Zero; este módulo só LÊ os dois valores de lá pra centrar o grid, nunca
# escreve de volta nem decide automaticamente um novo valor). ±30% em 3
# pontos, simétrico em FATOR multiplicativo (não em unidades absolutas) —
# a mesma variação relativa vale tanto pra tp_atr_mult=2.0 quanto pra
# sl_atr_mult=1.5, e os dois extremos ficam dentro do `sweep_range`
# declarado de cada constante ([1.0,3.0] e [0.75,2.25] respectivamente) —
# conferido manualmente contra `config/constants.yaml`, não coincidência.
GRID_FACTORS: Final[tuple[float, ...]] = (0.7, 1.0, 1.3)  # noqa: magic-number

_GRID_OUTPUT_SCHEMA: pl.Schema = pl.Schema(
    {
        "tp_atr_mult": pl.Float64,
        "sl_atr_mult": pl.Float64,
        "side": pl.Utf8,
        "n_total": pl.Int64,
        "n_filled": pl.Int64,
        "frac_tp": pl.Float64,
        "frac_sl": pl.Float64,
        "frac_time": pl.Float64,
        "frac_nofill": pl.Float64,
        "taker_exit_share_of_filled": pl.Float64,
        "entry_leg_bps_mean": pl.Float64,
        "exit_leg_bps_mean": pl.Float64,
        "cost_value": pl.Float64,
        "cost_unit": pl.Utf8,
        "cost_n": pl.Int64,
        "cost_n_semantics": pl.Utf8,
        "cost_source": pl.Utf8,
        "cost_valid": pl.Boolean,
        "cost_invalid_reason": pl.Utf8,
        "reference_round_trip_bps_5050": pl.Float64,
    }
)


def _as_date(value: DateLike) -> date:
    """Mesmo padrão de `triple_barrier._as_date`/`src.data.lake._as_date` —
    duplicado, não importado (ver docstring do módulo/convenção já usada
    nos `_paths.py` do repo: cada pacote resolve seus próprios detalhes
    triviais em vez de acoplar a uma função privada de outro pacote)."""
    return value if isinstance(value, date) else date.fromisoformat(value)


def _require_columns(df: pl.DataFrame, required: tuple[str, ...], *, df_name: str) -> None:
    missing = sorted(set(required) - set(df.columns))
    if missing:
        raise ValueError(f"{df_name}: coluna(s) obrigatória(s) ausente(s): {missing}")


def _mean_or_nan(arr: FloatArray) -> float:
    return float(np.mean(arr)) if arr.size else float("nan")


# ============================================================================
# Eixos do grid
# ============================================================================


def cost_axis_values(
    center: float, *, factors: tuple[float, ...] = GRID_FACTORS
) -> tuple[float, ...]:
    """3 pontos do eixo do grid centrados em `center` (o valor ATUAL de
    `tp_atr_mult`/`sl_atr_mult` lido de `constants.yaml` via
    `LabelConfig.from_constants()`) — `center × factors`, únicos e
    ordenados. `factors` default `GRID_FACTORS = (0.7, 1.0, 1.3)`."""
    values = sorted({round(center * f, 6) for f in factors})
    return tuple(values)


def default_grid_axes(
    base_config: LabelConfig | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """`(tp_axis, sl_axis)` centrados no `tp_atr_mult`/`sl_atr_mult` de
    `base_config` (ou de `constants.yaml` se `base_config` não for
    passado) — separado de `build_cost_surface_grid` pra ser testável sem
    precisar rodar o grid inteiro."""
    cfg = base_config if base_config is not None else LabelConfig.from_constants()
    return cost_axis_values(cfg.tp_atr_mult), cost_axis_values(cfg.sl_atr_mult)


# ============================================================================
# Uma célula do grid -> uma linha por lado
# ============================================================================


def cost_surface_cell(
    labels_both_sides: pl.DataFrame,
    *,
    tp_atr_mult: float,
    sl_atr_mult: float,
    source: str,
    reference_round_trip_bps_5050: float,
) -> pl.DataFrame:
    """Uma célula do grid (`tp_atr_mult`, `sl_atr_mult`) -> uma linha por
    lado (`long`/`short`) com o custo round-trip REALIZADO (`Metric`,
    `Unit.BPS_PER_TRADE`, colunas prefixadas `cost_`) e a decomposição
    maker/taker que o gera.

    `labels_both_sides` precisa ter `side`/`barrier_hit`/`cost_entry_bps`/
    `cost_exit_bps` — schema de saída de
    `triple_barrier.build_labels`/`build_labels_both_sides`
    (subconjunto de `triple_barrier.LABEL_COLUMNS`; `concurrency`/
    `uniqueness`/`sample_weight` não são usados aqui, não precisa ser o
    frame pós-pesos completo).

    `NOFILL` é EXCLUÍDO do custo médio (`_append_nofill_row` em
    `triple_barrier.py` grava `cost_entry_bps=cost_exit_bps=0.0` como
    placeholder de "não entrou", não custo real de trade) mas CONTA para
    `frac_nofill` — §3.2, NOFILL é desfecho de primeira classe, não deve
    desaparecer do denominador de `n_total`."""
    _require_columns(
        labels_both_sides,
        ("side", "barrier_hit", "cost_entry_bps", "cost_exit_bps"),
        df_name="labels_both_sides",
    )
    rows: list[dict[str, Any]] = []
    for side_value, side_label in _SIDE_LABELS.items():
        sub = labels_both_sides.filter(pl.col("side") == side_value)
        n_total = sub.height
        barrier = sub["barrier_hit"].cast(pl.Utf8)
        n_tp = int((barrier == _TP).sum())
        n_sl = int((barrier == _SL).sum())
        n_time = int((barrier == _TIME).sum())
        n_nofill = int((barrier == _NOFILL).sum())

        filled = sub.filter(barrier != _NOFILL)
        n_filled = filled.height
        entry_bps = filled["cost_entry_bps"].to_numpy().astype(np.float64)
        exit_bps = filled["cost_exit_bps"].to_numpy().astype(np.float64)
        round_trip = entry_bps + exit_bps

        cell_source = f"{source} side={side_label}"
        if n_filled > 0:
            metric = Metric(
                value=_mean_or_nan(round_trip),
                unit=Unit.BPS_PER_TRADE,
                n=n_filled,
                n_semantics=_N_SEMANTICS_TRADES,
                source=cell_source,
                valid=True,
            )
        else:
            metric = not_computable(
                Unit.BPS_PER_TRADE,
                _N_SEMANTICS_TRADES,
                cell_source,
                "nenhum trade preenchido (barrier_hit != NOFILL) nesta célula/lado",
            )

        taker_exit_share = float(n_sl + n_time) / n_filled if n_filled > 0 else float("nan")

        rows.append(
            {
                "tp_atr_mult": tp_atr_mult,
                "sl_atr_mult": sl_atr_mult,
                "side": side_label,
                "n_total": n_total,
                "n_filled": n_filled,
                "frac_tp": n_tp / n_total if n_total > 0 else float("nan"),
                "frac_sl": n_sl / n_total if n_total > 0 else float("nan"),
                "frac_time": n_time / n_total if n_total > 0 else float("nan"),
                "frac_nofill": n_nofill / n_total if n_total > 0 else float("nan"),
                "taker_exit_share_of_filled": taker_exit_share,
                "entry_leg_bps_mean": _mean_or_nan(entry_bps),
                "exit_leg_bps_mean": _mean_or_nan(exit_bps),
                **_prefixed_metric(metric),
                "reference_round_trip_bps_5050": reference_round_trip_bps_5050,
            }
        )
    return pl.DataFrame(rows, schema=_GRID_OUTPUT_SCHEMA)


def _prefixed_metric(metric: Metric) -> dict[str, Any]:
    return {f"cost_{k}": v for k, v in metric.to_json().items()}


# ============================================================================
# Grid completo — núcleo puro-ish (bars/mark/funding já em memória)
# ============================================================================


def build_cost_surface_grid(
    bars_15m: pl.DataFrame,
    mark_1m: pl.DataFrame,
    funding: pl.DataFrame,
    *,
    tp_axis: tuple[float, ...] | None = None,
    sl_axis: tuple[float, ...] | None = None,
    symbol: str = "BTCUSDT",
    base_config: LabelConfig | None = None,
    historical_filters_fallback: bool = False,
) -> pl.DataFrame:
    """Núcleo puro-ish (só IO indireto dentro de
    `triple_barrier.build_labels`, via `load_filters_asof` memoizado por
    chamada) — roda o Label Engine UMA VEZ POR CÉLULA do grid
    (`len(tp_axis) × len(sl_axis)` combinações, default 3×3=9,
    `GRID_FACTORS`), reusando `bars_15m`/`mark_1m`/`funding` já carregados
    em memória em vez de recarregar do disco a cada célula — eles não
    mudam com `tp_atr_mult`/`sl_atr_mult`, só o bloco de barreiras muda
    (`dataclasses.replace` sobre `base_config`, B15: cada célula tem seu
    próprio `config_hash`).

    Retorna a concatenação de `cost_surface_cell(...)` por célula — uma
    linha por `(tp_atr_mult, sl_atr_mult, side)`, a "superfície 2D" em
    formato longo (use `pivot_cost_surface` pra reshape em tabela
    tp×sl)."""
    cfg = base_config if base_config is not None else LabelConfig.from_constants()
    default_tp, default_sl = default_grid_axes(cfg)
    tp_values = tp_axis if tp_axis is not None else default_tp
    sl_values = sl_axis if sl_axis is not None else default_sl

    reference_5050 = round_trip_cost_bps(cfg.maker_fee, cfg.taker_fee)

    cells: list[pl.DataFrame] = []
    for tp in tp_values:
        for sl in sl_values:
            cell_cfg = replace(cfg, tp_atr_mult=tp, sl_atr_mult=sl)
            t_cell = time.perf_counter()
            labels = triple_barrier.build_labels_both_sides(
                bars_15m,
                mark_1m,
                funding,
                symbol=symbol,
                config=cell_cfg,
                historical_filters_fallback=historical_filters_fallback,
            )
            elapsed_s = time.perf_counter() - t_cell
            source = (
                f"{symbol} tp_atr_mult={tp} sl_atr_mult={sl} "
                f"config_hash={cell_cfg.config_hash}"
            )
            cells.append(
                cost_surface_cell(
                    labels,
                    tp_atr_mult=tp,
                    sl_atr_mult=sl,
                    source=source,
                    reference_round_trip_bps_5050=reference_5050,
                )
            )
            logger.info(
                "analysis.cost_surface.cell_done",
                tp_atr_mult=tp,
                sl_atr_mult=sl,
                n_labels=labels.height,
                elapsed_s=round(elapsed_s, 1),
            )
    if not cells:
        return pl.DataFrame(schema=_GRID_OUTPUT_SCHEMA)
    return pl.concat(cells, how="vertical")


# ============================================================================
# Ponto de entrada com IO — carrega bars/mark/funding 1x, roda o grid
# ============================================================================


def build_cost_surface_grid_for_symbol(
    symbol: str,
    start: DateLike,
    end: DateLike,
    *,
    tp_axis: tuple[float, ...] | None = None,
    sl_axis: tuple[float, ...] | None = None,
    base_config: LabelConfig | None = None,
    historical_filters_fallback: bool = False,
) -> pl.DataFrame:
    """Ponto de entrada com IO, análogo a
    `triple_barrier.build_labels_for_symbol` — MAS carrega `bars_15m`/
    `mark_1m`/`funding` do disco UMA VEZ (não uma vez por célula do grid):
    ver docstring do módulo, "custo de rotular o grid inteiro". Chame esta
    função (não `build_cost_surface_grid` diretamente) quando não tiver
    `bars_15m`/`mark_1m`/`funding` já em memória.

    **AG-011** — `bars_15m` carrega no TF de DECISÃO (`cfg.tf`, default
    `"15m"`), não mais `"15m"` literal — mesma correção de AG-005 em
    `triple_barrier.build_labels_for_symbol`, replicada aqui porque este
    ponto de entrada tinha sua própria cópia independente do hardcode.

    `mark_1m`/`funding` buscados com folga ALÉM de `end` — o suficiente pra
    cobrir `max(time_stop_bars, fill_timeout_bars) * step_ms(cfg.tf)` (o
    maior horizonte possível no TF pedido) MAIS 1 dia de margem extra, mesmo
    padrão de `triple_barrier.build_labels_for_symbol` (AG-005). Antes da
    correção a folga era um "1 dia" fixo calibrado só pro caso 15m — em TF
    maior (`time_stop_bars`/`fill_timeout_bars` expressos em barras, não em
    tempo) essa folga fixa poderia ser insuficiente e descartar labels reais
    por "cauda incompleta" silenciosamente."""
    cfg = base_config if base_config is not None else LabelConfig.from_constants()

    bars_15m = lake.query_bars(symbol, cfg.tf, start, end, source="klines_1m", cast_prices=True)

    horizon_ms = max(cfg.time_stop_bars, cfg.fill_timeout_bars) * step_ms(cfg.tf)
    mark_end = _as_date(end) + timedelta(milliseconds=horizon_ms, days=1)
    mark_1m = lake.query_bars(
        symbol, "1m", start, mark_end, source="mark_price_klines_1m", cast_prices=True
    )
    funding = lake.query_funding(symbol, start, mark_end)

    logger.info(
        "analysis.cost_surface.data_loaded",
        symbol=symbol,
        start=str(start),
        end=str(end),
        n_bars_15m=bars_15m.height,
        n_mark_1m=mark_1m.height,
        n_funding=funding.height,
    )

    return build_cost_surface_grid(
        bars_15m,
        mark_1m,
        funding,
        tp_axis=tp_axis,
        sl_axis=sl_axis,
        symbol=symbol,
        base_config=cfg,
        historical_filters_fallback=historical_filters_fallback,
    )


# ============================================================================
# Reshape pra leitura — tp_atr_mult x sl_atr_mult, um lado por vez
# ============================================================================


def pivot_cost_surface(
    grid: pl.DataFrame, *, side: str, value_col: str = "cost_value"
) -> pl.DataFrame:
    """Pivot (`tp_atr_mult` × `sl_atr_mult`) de `grid` (saída de
    `build_cost_surface_grid`/`build_cost_surface_grid_for_symbol`) para UM
    lado — `tp_atr_mult` nas linhas, `sl_atr_mult` nas colunas, `value_col`
    (default `cost_value`, o `Metric.value` do custo round-trip médio) na
    célula. Só reshape pra leitura — não recalcula nada, não agrega (o grid
    de entrada já tem no máximo uma linha por `(tp_atr_mult, sl_atr_mult,
    side)`)."""
    if side not in _SIDE_LABELS.values():
        raise ValueError(f"side deve ser um de {sorted(_SIDE_LABELS.values())}, recebido {side!r}")
    sub = grid.filter(pl.col("side") == side)
    return sub.pivot(on="sl_atr_mult", index="tp_atr_mult", values=value_col).sort("tp_atr_mult")


# ============================================================================
# Escrita atômica do relatório (B29) + ponto de entrada manual
# ============================================================================


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 — `.tmp` -> `fsync` -> `rename`, mesmo padrão de
    `triple_barrier.write_labels_atomic`/`src.data.validate.write_report_atomic`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("analysis.cost_surface.report_written", path=str(dest_path))


def run_and_save_cost_surface_report(
    symbol: str = "BTCUSDT",
    start: DateLike = "2020-01-01",
    end: DateLike = "2026-08-08",
    *,
    dest_path: Path | None = None,
    historical_filters_fallback: bool = True,
) -> Path:
    """Ponto de entrada MANUAL — NÃO roda dentro da suíte automatizada de
    testes (ver aviso de custo na tarefa que originou este módulo: rotular
    a série completa 9 vezes é caro o bastante pra não pagar esse custo a
    cada `pytest`). Roda o grid 3×3 completo sobre a série real
    (2020-01-01 a 2026-08-08 por default, o mesmo intervalo do
    `labels/v1/labels.parquet` do Sprint 6) e persiste
    `experiments/cost_surface_report.json` (B29, atômico).

    Chame manualmente: `uv run python -c
    "from src.analysis.cost_surface import run_and_save_cost_surface_report as r; r()"`
    ou rode este módulo como script (`uv run python -m
    src.analysis.cost_surface`)."""
    cfg = LabelConfig.from_constants()
    tp_axis, sl_axis = default_grid_axes(cfg)

    t0 = time.perf_counter()
    grid = build_cost_surface_grid_for_symbol(
        symbol,
        start,
        end,
        tp_axis=tp_axis,
        sl_axis=sl_axis,
        base_config=cfg,
        historical_filters_fallback=historical_filters_fallback,
    )
    elapsed_s = time.perf_counter() - t0

    payload: dict[str, Any] = {
        **report_provenance(),
        "symbol": symbol,
        "start": str(start),
        "end": str(end),
        "tp_axis": list(tp_axis),
        "sl_axis": list(sl_axis),
        "grid_factors": list(GRID_FACTORS),
        "n_grid_points": len(tp_axis) * len(sl_axis),
        "baseline_tp_atr_mult": cfg.tp_atr_mult,
        "baseline_sl_atr_mult": cfg.sl_atr_mult,
        "reference_round_trip_bps_5050": round_trip_cost_bps(cfg.maker_fee, cfg.taker_fee),
        "elapsed_seconds_total": elapsed_s,
        "rows": grid.to_dicts(),
    }
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info(
        "analysis.cost_surface.grid_done",
        n_grid_points=payload["n_grid_points"],
        elapsed_seconds_total=round(elapsed_s, 1),
        dest=str(dest),
    )
    return dest


if __name__ == "__main__":
    run_and_save_cost_surface_report()
