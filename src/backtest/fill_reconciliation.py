"""Reconciliação honesta entre o gate OTIMISTA do Label Engine (Sprint 6,
`barrier_hit != NOFILL`, `src.labels.triple_barrier`/`src.labels.fill_model`)
e o gate REAL do simulador de fila (Sprint 9, `src.execution.fill_simulator`,
coluna `filled`) — restrita à ÚNICA janela onde o fill real foi de fato
medido (`BOOK_TICKER_WINDOW_START`/`_END`, importados de
`src.execution.fill_simulator`, nunca reescritos aqui — Regra Zero, §16.10).

**Por que este módulo existe.** `src.models.backtest_lite` mede execução
como -17,71 (pooled, 5 caminhos de CPCV — `experiments/alpha_layer1_report.json`
:: `decomposition_pnl.pooled_all_15_splits`) contra direção+carry de +3,67,
mas usa `barrier_hit != NOFILL` como gate de preenchimento — a convenção
OTIMISTA do Label Engine (Sprint 6, "toque do intervalo = preenchimento",
limite SUPERIOR, ver docstring de `src.execution.fill_simulator`, item 2 da
lista "Limitações do modelo simplificado"), não o simulador de fila real
(fila FIFO + `aggTrades`, limite INFERIOR, `p_fill` medido de 37,3% numa
janela específica). Comparar o -17,71 contra qualquer coisa sem isolar o
efeito do GATE (mantendo tudo o resto — janela, sinais, `ret_net` de
`labels.parquet` — idêntico) é comparar peras com maçãs. Módulo A abaixo
isola exatamente esse efeito; Módulo B mede se o fill real é seletivo em
relação ao desfecho (adverse selection), sobre TODOS os candidatos do
simulador, não só os sinais do Alpha.

**Primeiro achado empírico, não previsto pela task original que gerou este
módulo — documentado aqui em vez de escondido (mesma prática do resto do
repo).** `orders.parquet.t_post` NÃO corresponde a `predictions.parquet.t0`
nem a `labels.parquet.t0` diretamente (uma junção ingênua nessas colunas
devolve ZERO linhas, verificado antes de escrever qualquer junção abaixo)
— corresponde a `labels.parquet.t_entry`. `labels.t0` é o timestamp de
FECHAMENTO da barra de decisão (convenção `bar_close - 1ms` do Label
Engine — `labels.t_post == labels.t0` sempre, o que explica por que a task
original leu esse nome e presumiu, incorretamente, que seria a chave certa
contra `orders.t_post`); `labels.t_entry` é o timestamp de ABERTURA da
barra seguinte, onde a ordem limite é de fato postada — exatamente o ponto
de grade que `fill_simulator._day_grid_ms` usa como `t_post`.

**Segundo achado, mais sutil, também tratado explicitamente (não
silenciado).** Toda linha de `labels.parquet` com `barrier_hit == "NOFILL"`
tem `t_entry` NULO por construção (`src.labels.triple_barrier`: o modelo de
preenchimento OTIMISTA do Sprint 6 já decidiu, para aquela barra, que a
ENTRADA nunca aconteceria — não há barreira para avaliar, logo não há
`t_entry`). Uma junção ingênua por `t_entry` excluiria essas linhas da
amostra como se fossem "sem dado" (mesma categoria dos
`n_skipped_no_book_state` genuínos do simulador de fila) — mas não são:
são uma decisão estrutural do gate OTIMISTA, e a implicação lógica é
direta e verificada empiricamente nesta janela (zero contra-exemplos, ver
`tests/backtest/test_fill_reconciliation.py`): `filled_real == True` nunca
ocorre quando `barrier_hit == "NOFILL"` — um fill real exige que o preço
tenha de fato negociado no nível, o que implica ter ao menos TOCADO o
nível, a condição mais fraca que o Sprint 6 já exige para não dar NOFILL.
Por isso essas linhas entram na amostra-base com `filled = False POR
CONSTRUÇÃO` (não via junção, nunca teriam par), contadas separadamente
(`n_signals_nofill_by_construction`) de `n_signals_missing_order_data_gap`
(a lacuna genuína de cobertura de `bookTicker` — ausência de DADO)."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, cast

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.execution.fill_simulator import (
    BOOK_TICKER_WINDOW_END,
    BOOK_TICKER_WINDOW_START,
    RPI_BREAK_DATE,
)
from src.models import backtest_lite, decomposition
from src.models.pipeline import MODEL_ID_CAMADA1
from src.validation import cpcv

from ._paths import (
    EXPERIMENTS_DIR,
    FILL_SIMULATOR_OUTPUT_DIR,
    LABELS_OUTPUT_DIR,
    PREDICTIONS_OUTPUT_DIR,
)

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

# Colunas de `labels.parquet` necessárias para reproduzir o que
# `src.models.backtest_lite.realize_trades` já faz (`ret_gross`/
# `cost_entry_bps`/`cost_exit_bps`/`funding_bps` para `src.models.decomposition`,
# além de `ret_net`/`sample_weight`) mais `t_entry` — a chave real contra
# `orders.t_post` (ver docstring do módulo, primeiro achado).
_LABEL_JOIN_COLUMNS: Final[tuple[str, ...]] = (
    "t0",
    "side",
    "t_entry",
    "barrier_hit",
    "ret_net",
    "sample_weight",
    "ret_gross",
    "cost_entry_bps",
    "cost_exit_bps",
    "funding_bps",
)

_GATE_OPTIMISTA: Final[str] = "otimista_label_engine"
_GATE_OPTIMISTA_DESC: Final[str] = (
    "barrier_hit != NOFILL (src.labels.triple_barrier / fill_model, Sprint 6 — "
    "toque do intervalo [low, high] = preenchimento, limite SUPERIOR)"
)
_GATE_REALISTA: Final[str] = "realista_fill_simulator"
_GATE_REALISTA_DESC: Final[str] = (
    "filled == True (src.execution.fill_simulator, Sprint 9 — fila FIFO + aggTrades, "
    "cancelamento não modelado, limite INFERIOR)"
)


# ============================================================================
# IO — carrega os 3 artefatos já existentes (Sprint 6/8/9); nunca fabrica
# nada fora deles.
# ============================================================================


def load_predictions(model_id: str = MODEL_ID_CAMADA1) -> pl.DataFrame:
    path = PREDICTIONS_OUTPUT_DIR / "alpha" / model_id / "predictions.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"predictions não encontrado em {path} — rode "
            "`uv run python -m src.models.pipeline` primeiro (Sprint 8, "
            "src.models.pipeline.run_layer1_sprint)"
        )
    return pl.read_parquet(path)


def load_labels(version: str = "v1") -> pl.DataFrame:
    path = LABELS_OUTPUT_DIR / version / "labels.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"labels não encontrado em {path} — rode `uv run quant labels build` primeiro "
            "(src.labels.triple_barrier)"
        )
    return pl.read_parquet(path)


def load_orders(version: str = "v1") -> pl.DataFrame:
    path = FILL_SIMULATOR_OUTPUT_DIR / version / "orders.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"orders não encontrado em {path} — rode "
            "`uv run python -m src.execution.fill_simulator` primeiro (Sprint 9)"
        )
    return pl.read_parquet(path)


def _assert_window_within_measured_coverage(window_start: date, window_end: date) -> None:
    """Mesmo guard-rail de `src.execution.fill_simulator.simulate_window` —
    este módulo nunca extrapola fill real além de `RPI_BREAK_DATE` (§9.5
    v3.3); janela fora da cobertura REAL medida do bookTicker é permitida
    (produz amostra vazia/menor, não erro), mas logada."""
    if window_end >= RPI_BREAK_DATE:
        raise ValueError(
            f"window_end={window_end.isoformat()} >= {RPI_BREAK_DATE.isoformat()} "
            "(quebra RPI, §9.5 v3.3) — mesmo limite que "
            "src.execution.fill_simulator.simulate_window respeita; este módulo não "
            "extrapola fill real além dele (ver docstring de fill_simulator)."
        )
    if window_start < BOOK_TICKER_WINDOW_START or window_end > BOOK_TICKER_WINDOW_END:
        logger.warning(
            "backtest.fill_reconciliation.window_outside_measured_coverage",
            requested_start=window_start.isoformat(),
            requested_end=window_end.isoformat(),
            coverage_start=BOOK_TICKER_WINDOW_START.isoformat(),
            coverage_end=BOOK_TICKER_WINDOW_END.isoformat(),
        )


# ============================================================================
# Reconstrução determinística fold_id -> path_id (§11.4, "1-fatoração de
# K6") — puramente combinatória, NÃO depende do conteúdo de `labels`, só de
# `cpcv_n_groups`/`cpcv_n_test_groups` (constants.yaml). Ver docstring de
# `src.validation.cpcv.generate_splits`/`_path_assignment`.
# ============================================================================


class PathReconstructionError(Exception):
    """`fold_id` observado em `predictions.parquet` sem entrada na
    reconstrução CPCV atual — sinal de que `cpcv_n_groups`/`cpcv_n_test_groups`
    mudaram em `constants.yaml` desde o treino do modelo. Não fatal para
    quem chama: cai para o pooled agregado (ver `_by_path_breakdown`)."""


def reconstruct_fold_to_path_id(
    labels_all: pl.DataFrame, *, known_fold_ids: set[int]
) -> dict[int, int]:
    """`{split_id: path_id}` via `src.validation.cpcv.generate_splits` — a
    MESMA função que gera os splits usados no treino
    (`src.models.pipeline.run_layer1_sprint`; `fold_id == split.split_id`
    sempre, ver `src.models.alpha.run_fold`/`FoldResult`). O mapeamento em
    si é puramente combinatório (1-fatoração de K_n_groups sobre
    `cpcv_n_groups`) — não depende de QUAL `labels` é passado, só precisa
    ser não-vazio o bastante para `generate_splits` rodar; usar
    `labels/v1/labels.parquet` real (não um recorte) é o caminho mais
    barato e correto, sem retreinar nada."""
    result = cpcv.generate_splits(labels_all)
    mapping = {s.split_id: s.path_id for s in result.splits}
    missing = known_fold_ids - set(mapping)
    if missing:
        raise PathReconstructionError(
            f"fold_id(s) {sorted(missing)} observados em predictions.parquet sem entrada "
            f"na reconstrução CPCV (n_splits={len(mapping)} de cpcv_n_groups="
            f"{result.config.n_groups}/cpcv_n_test_groups={result.config.n_test_groups} "
            "atuais em constants.yaml — podem ter mudado desde o treino do modelo)."
        )
    return mapping


# ============================================================================
# Módulo A — reconciliação otimista vs realista, amostra-base comum.
# ============================================================================


@dataclass(frozen=True, slots=True)
class JoinDiagnostics:
    n_signals_window: int
    n_signals_nofill_by_construction: int
    n_signals_missing_order_data_gap: int
    n_signals_common_base: int


def build_reconciliation_base(
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
    orders: pl.DataFrame,
    *,
    window_start: date,
    window_end: date,
) -> tuple[pl.DataFrame, JoinDiagnostics]:
    """Reproduz o que `src.models.backtest_lite.realize_trades` faz (junta
    sinais disparados ao resultado real do lado sinalizado), restrito à
    janela real do simulador de fila, e adiciona o gate `filled` real — ver
    docstring do módulo para os dois achados empíricos que moldam esta
    junção (chave `t_entry`; NOFILL com `t_entry` nulo tratado por
    construção, não como lacuna de dado)."""
    signals = predictions.filter(
        pl.col("is_oof")
        & (pl.col("side_hat") != 0)
        & (pl.col("t0").dt.date() >= window_start)
        & (pl.col("t0").dt.date() <= window_end)
    )
    n_signals_window = signals.height

    joined_labels = signals.join(
        labels.select(list(_LABEL_JOIN_COLUMNS)),
        left_on=["t0", "side_hat"],
        right_on=["t0", "side"],
        how="left",
    ).with_columns(pl.col("barrier_hit").cast(pl.Utf8))

    n_missing_label = int(joined_labels["barrier_hit"].is_null().sum())
    if n_missing_label:
        raise AssertionError(
            f"{n_missing_label} sinal(is) de predictions.parquet (is_oof=True, "
            "side_hat!=0) sem par em labels.parquet dentro da janela — não deveria "
            "acontecer (toda barra do universo de modelagem existe em "
            "labels/v1/labels.parquet); investigar antes de confiar em qualquer número "
            "desta reconciliação."
        )

    nofill = joined_labels.filter(pl.col("barrier_hit") == "NOFILL")
    non_nofill = joined_labels.filter(pl.col("barrier_hit") != "NOFILL")
    n_nofill_by_construction = nofill.height

    joined_orders = non_nofill.join(
        orders.select(["t_post", "side", "filled"]),
        left_on=["t_entry", "side_hat"],
        right_on=["t_post", "side"],
        how="left",
    )
    n_missing_order_data_gap = int(joined_orders["filled"].is_null().sum())
    if n_missing_order_data_gap:
        logger.warning(
            "backtest.fill_reconciliation.signals_missing_order_row",
            n_missing=n_missing_order_data_gap,
            n_non_nofill_signals=non_nofill.height,
            likely_cause=(
                "fill_simulator.n_skipped_no_book_state (ausência de estado de book "
                "conhecido em t_post — ver docstring de src.execution.fill_simulator, "
                "item 5) — não é um NOFILL, é ausência de DADO; excluído da amostra-base."
            ),
        )

    base_matched = joined_orders.filter(pl.col("filled").is_not_null())
    base_nofill = nofill.with_columns(pl.lit(False).alias("filled"))
    base = pl.concat([base_matched, base_nofill], how="diagonal_relaxed")

    diagnostics = JoinDiagnostics(
        n_signals_window=n_signals_window,
        n_signals_nofill_by_construction=n_nofill_by_construction,
        n_signals_missing_order_data_gap=n_missing_order_data_gap,
        n_signals_common_base=base.height,
    )
    logger.info("backtest.fill_reconciliation.base_built", **asdict(diagnostics))
    return base, diagnostics


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: str
    gate_description: str
    n_base_signals: int
    n_filled: int
    fill_rate: float
    sharpe_naive: float
    trades_per_year: float
    mean_trade_ret_net: float
    std_trade_ret_net: float
    decomposition: decomposition.DecompositionResult


def _evaluate_gate(
    base: pl.DataFrame, *, gate_expr: pl.Expr, gate: str, gate_description: str
) -> GateResult:
    n_base = base.height
    executed = base.filter(gate_expr)
    n_filled = executed.height
    fill_rate = float(n_filled) / float(n_base) if n_base > 0 else float("nan")

    rets: FloatArray = executed["ret_net"].to_numpy().astype(np.float64)
    span = backtest_lite.span_seconds(executed["t0"])
    sharpe, trades_per_year = backtest_lite.sharpe_naive(rets, span_seconds=span)
    mean_ret = float(np.mean(rets)) if rets.size else float("nan")
    std_ret = float(np.std(rets, ddof=1)) if rets.size >= 2 else float("nan")

    decomp = decomposition.decompose(executed)

    return GateResult(
        gate=gate,
        gate_description=gate_description,
        n_base_signals=n_base,
        n_filled=n_filled,
        fill_rate=fill_rate,
        sharpe_naive=sharpe,
        trades_per_year=trades_per_year,
        mean_trade_ret_net=mean_ret,
        std_trade_ret_net=std_ret,
        decomposition=decomp,
    )


def _by_path_breakdown(
    base: pl.DataFrame, labels_all: pl.DataFrame
) -> tuple[dict[str, dict[str, GateResult]] | None, str]:
    """Bônus (não exigido para a reconciliação pooled): `path_id` por
    caminho de CPCV, reconstruído deterministicamente — ver
    `reconstruct_fold_to_path_id`. Cai para `None` com nota explicativa se
    algum `fold_id` observado não bater com a reconstrução (não finge
    granularidade que não tem)."""
    known_fold_ids = {int(v) for v in base["fold_id"].unique().to_list()}
    try:
        mapping = reconstruct_fold_to_path_id(labels_all, known_fold_ids=known_fold_ids)
    except PathReconstructionError as exc:
        logger.warning("backtest.fill_reconciliation.path_reconstruction_failed", error=str(exc))
        return None, str(exc)

    base_with_path = base.with_columns(
        pl.col("fold_id").cast(pl.Int64).replace_strict(mapping).alias("path_id")
    )
    by_path: dict[str, dict[str, GateResult]] = {}
    for path_id in sorted(set(mapping.values())):
        sub = base_with_path.filter(pl.col("path_id") == path_id)
        by_path[str(path_id)] = {
            "optimistic": _evaluate_gate(
                sub,
                gate_expr=pl.col("barrier_hit") != "NOFILL",
                gate=_GATE_OPTIMISTA,
                gate_description=_GATE_OPTIMISTA_DESC,
            ),
            "realistic": _evaluate_gate(
                sub,
                gate_expr=pl.col("filled"),
                gate=_GATE_REALISTA,
                gate_description=_GATE_REALISTA_DESC,
            ),
        }
    note = (
        "path_id reconstruído deterministicamente via "
        "src.validation.cpcv.generate_splits (split_id -> path_id não depende do "
        "conteúdo de labels, só de cpcv_n_groups/cpcv_n_test_groups — verificado "
        f"n_splits={len(mapping)}/n_paths={len(set(mapping.values()))} batendo com "
        "fold_id observado em predictions.parquet). Amostra por caminho é pequena "
        "dentro desta janela (dezenas a centenas de sinais/caminho) — mais ruidosa "
        "que o pooled; não confundir com camada1_backtest_by_path do Sprint 8 (aquele "
        "é sobre os 6,5 anos completos, este é só a janela do bookTicker)."
    )
    return by_path, note


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    window_start: str
    window_end: str
    join_diagnostics: JoinDiagnostics
    optimistic: GateResult
    realistic: GateResult
    by_path: dict[str, dict[str, GateResult]] | None
    by_path_note: str


def run_fill_reconciliation(
    *,
    model_id: str | None = None,
    window_start: date = BOOK_TICKER_WINDOW_START,
    window_end: date = BOOK_TICKER_WINDOW_END,
) -> ReconciliationResult:
    _assert_window_within_measured_coverage(window_start, window_end)

    resolved_model_id = model_id if model_id is not None else MODEL_ID_CAMADA1
    predictions = load_predictions(resolved_model_id)
    labels = load_labels()
    orders = load_orders()

    base, diagnostics = build_reconciliation_base(
        predictions, labels, orders, window_start=window_start, window_end=window_end
    )
    optimistic = _evaluate_gate(
        base,
        gate_expr=pl.col("barrier_hit") != "NOFILL",
        gate=_GATE_OPTIMISTA,
        gate_description=_GATE_OPTIMISTA_DESC,
    )
    realistic = _evaluate_gate(
        base,
        gate_expr=pl.col("filled"),
        gate=_GATE_REALISTA,
        gate_description=_GATE_REALISTA_DESC,
    )
    by_path, by_path_note = _by_path_breakdown(base, labels)

    result = ReconciliationResult(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        join_diagnostics=diagnostics,
        optimistic=optimistic,
        realistic=realistic,
        by_path=by_path,
        by_path_note=by_path_note,
    )
    logger.info(
        "backtest.fill_reconciliation.module_a_done",
        window_start=result.window_start,
        window_end=result.window_end,
        optimistic_sharpe=optimistic.sharpe_naive,
        realistic_sharpe=realistic.sharpe_naive,
        optimistic_fill_rate=optimistic.fill_rate,
        realistic_fill_rate=realistic.fill_rate,
    )
    return result


# ============================================================================
# Módulo B — seletividade do fill real sobre TODOS os candidatos do
# simulador (não só os sinais do Alpha).
# ============================================================================


def _fraction_true(mask: pl.Series) -> float:
    return float(mask.sum()) / float(mask.len()) if mask.len() else float("nan")


def _mean_bps(series: pl.Series) -> float:
    """`series.mean()` devolve um union amplo nos stubs do polars (qualquer
    literal Python possível, não o dtype real da série) — `cast` para
    `float` é seguro aqui porque o contrato desta função (`series` vem
    sempre de uma coluna `Float64`, `ret_net`) já é garantido pelos
    chamadores reais, mesmo raciocínio de `src.models.backtest_lite.
    span_seconds`."""
    if series.len() == 0:
        return float("nan")
    mean = series.mean()
    return cast(float, mean) * 10_000 if mean is not None else float("nan")


def _barrier_distribution(df: pl.DataFrame) -> dict[str, float]:
    if df.height == 0:
        return {}
    total = df.height
    counts = df.group_by("barrier_hit").agg(pl.len().alias("n"))
    return {str(row[0]): float(row[1]) / float(total) for row in counts.iter_rows()}


@dataclass(frozen=True, slots=True)
class SelectivityResult:
    window_start: str
    window_end: str
    n_orders_total: int
    n_orders_unmatched: int
    n_orders_matched: int
    n_filled: int
    n_notfilled: int
    p_tp_given_filled: float
    p_tp_given_notfilled: float
    gap_pp: float
    mean_ret_net_bps_given_filled: float
    mean_ret_net_bps_given_notfilled: float
    mean_ret_net_bps_unconditional: float
    selectivity_cost_bps: float
    barrier_hit_distribution_given_filled: dict[str, float]
    barrier_hit_distribution_given_notfilled: dict[str, float]


def compute_fill_selectivity(
    labels: pl.DataFrame,
    orders: pl.DataFrame,
    *,
    window_start: date,
    window_end: date,
) -> SelectivityResult:
    """Núcleo puro (sem IO) de `run_fill_selectivity` — separado para ser
    testável com dado sintético pequeno (mesmo padrão de
    `build_reconciliation_base` no Módulo A). Sobre TODOS os pontos de
    `orders` (não só sinais do Alpha): `filled` real como GATE booleano
    (nunca `markout_*_bps` como retorno — isso é mark-to-market em
    horizonte fixo, não o retorno de barreira tripla; `ret_net` de
    `labels` é a única fonte de retorno usada aqui, mesma fonte do resto
    do pipeline)."""
    labels_window = labels.filter(
        (pl.col("t0").dt.date() >= window_start) & (pl.col("t0").dt.date() <= window_end)
    ).with_columns(pl.col("barrier_hit").cast(pl.Utf8))

    joined = orders.join(
        labels_window.select(["t_entry", "side", "barrier_hit", "ret_net"]),
        left_on=["t_post", "side"],
        right_on=["t_entry", "side"],
        how="left",
    )
    n_total = joined.height
    n_unmatched = int(joined["barrier_hit"].is_null().sum())
    if n_unmatched:
        logger.warning(
            "backtest.fill_selectivity.orders_unmatched_to_labels",
            n_unmatched=n_unmatched,
            n_total=n_total,
            causes=(
                "duas causas possíveis, não separadas aqui: (1) "
                "fill_simulator.n_skipped_no_book_state — lacuna genuína de bookTicker; "
                "(2) o ponto de grade coincide com o t_entry implícito de uma barra cujo "
                "barrier_hit já é NOFILL sob a convenção do Label Engine (t_entry nulo "
                "por construção, nunca casa com nada) — não há barrier_hit de "
                "referência para comparar nesse ponto, de qualquer forma."
            ),
        )
    matched = joined.filter(pl.col("barrier_hit").is_not_null())

    filled_grp = matched.filter(pl.col("filled"))
    notfilled_grp = matched.filter(~pl.col("filled"))

    p_tp_filled = _fraction_true(filled_grp["barrier_hit"] == "TP")
    p_tp_notfilled = _fraction_true(notfilled_grp["barrier_hit"] == "TP")
    gap_pp = (p_tp_filled - p_tp_notfilled) * 100

    mean_bps_filled = _mean_bps(filled_grp["ret_net"])
    mean_bps_notfilled = _mean_bps(notfilled_grp["ret_net"])
    mean_bps_unconditional = _mean_bps(matched["ret_net"])
    selectivity_cost_bps = mean_bps_filled - mean_bps_unconditional

    result = SelectivityResult(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        n_orders_total=n_total,
        n_orders_unmatched=n_unmatched,
        n_orders_matched=matched.height,
        n_filled=filled_grp.height,
        n_notfilled=notfilled_grp.height,
        p_tp_given_filled=p_tp_filled,
        p_tp_given_notfilled=p_tp_notfilled,
        gap_pp=gap_pp,
        mean_ret_net_bps_given_filled=mean_bps_filled,
        mean_ret_net_bps_given_notfilled=mean_bps_notfilled,
        mean_ret_net_bps_unconditional=mean_bps_unconditional,
        selectivity_cost_bps=selectivity_cost_bps,
        barrier_hit_distribution_given_filled=_barrier_distribution(filled_grp),
        barrier_hit_distribution_given_notfilled=_barrier_distribution(notfilled_grp),
    )
    logger.info(
        "backtest.fill_selectivity.done",
        n_matched=result.n_orders_matched,
        p_tp_given_filled=result.p_tp_given_filled,
        p_tp_given_notfilled=result.p_tp_given_notfilled,
        gap_pp=result.gap_pp,
        selectivity_cost_bps=result.selectivity_cost_bps,
    )
    return result


def run_fill_selectivity(
    *,
    window_start: date = BOOK_TICKER_WINDOW_START,
    window_end: date = BOOK_TICKER_WINDOW_END,
) -> SelectivityResult:
    """IO + guard-rail de janela em torno de `compute_fill_selectivity`
    (núcleo puro) — carrega `labels/v1/labels.parquet` e
    `execution/fill_simulator/v1/orders.parquet` reais."""
    _assert_window_within_measured_coverage(window_start, window_end)
    labels = load_labels()
    orders = load_orders()
    return compute_fill_selectivity(
        labels, orders, window_start=window_start, window_end=window_end
    )


# ============================================================================
# Relatório combinado — escrita atômica (.tmp -> fsync -> rename, B29),
# mesmo padrão de src.execution.fill_simulator.write_orders_atomic /
# src.models.pipeline.write_report_atomic.
# ============================================================================


@dataclass(frozen=True, slots=True)
class FillReconciliationReport:
    schema_version: int
    generated_at_utc: str
    model_id: str
    window_start: str
    window_end: str
    module_a_fill_reconciliation: ReconciliationResult
    module_b_fill_selectivity: SelectivityResult
    limitations: tuple[str, ...]


def build_report(
    *,
    model_id: str | None = None,
    window_start: date = BOOK_TICKER_WINDOW_START,
    window_end: date = BOOK_TICKER_WINDOW_END,
) -> FillReconciliationReport:
    resolved_model_id = model_id if model_id is not None else MODEL_ID_CAMADA1
    reconciliation = run_fill_reconciliation(
        model_id=resolved_model_id, window_start=window_start, window_end=window_end
    )
    selectivity = run_fill_selectivity(window_start=window_start, window_end=window_end)

    by_path_limitation = (
        reconciliation.by_path_note
        if reconciliation.by_path is not None
        else f"by_path não reconstruído: {reconciliation.by_path_note}"
    )

    limitations: tuple[str, ...] = (
        "Reconciliação restrita à janela onde bookTicker existe "
        f"({BOOK_TICKER_WINDOW_START.isoformat()}..{BOOK_TICKER_WINDOW_END.isoformat()}) "
        "— não extrapola fill real além dela; mesmo limite que "
        "src.execution.fill_simulator.simulate_window respeita (RPI_BREAK_DATE).",
        "predictions.parquet repete cada barra até 5x (uma por caminho de CPCV cujo "
        "teste OOF a cobriu) — os números 'otimista'/'realista' aqui são pooled sobre "
        "os caminhos que caem dentro desta janela reduzida, não os 6,5 anos completos "
        "do -17,71 original (experiments/alpha_layer1_report.json); a comparação "
        "válida é OTIMISTA vs REALISTA dentro desta MESMA janela, não janela-reduzida "
        "vs 6,5-anos completos.",
        by_path_limitation,
        (
            f"{reconciliation.join_diagnostics.n_signals_nofill_by_construction} de "
            f"{reconciliation.join_diagnostics.n_signals_window} sinais na janela têm "
            "barrier_hit==NOFILL sob a convenção do Label Engine (t_entry nulo por "
            "construção) — tratados como filled=False POR CONSTRUÇÃO na amostra-base "
            "(zero contra-exemplos medidos do oposto: filled_real==True com "
            "barrier_hit==NOFILL)."
        ),
        (
            f"{reconciliation.join_diagnostics.n_signals_missing_order_data_gap} sinais "
            "(não-NOFILL) dentro da janela não têm linha correspondente em "
            "orders.parquet (fill_simulator.n_skipped_no_book_state — ausência "
            "genuína de estado de book, não um NOFILL) — excluídos da amostra-base "
            "comum para manter o mesmo denominador nos dois gates."
        ),
        "calibrate_against_real_fills (src.execution.fill_simulator) não está "
        "implementado — este módulo reconcilia os dois gates já existentes, não "
        "calibra nenhum dos dois contra fill real de Testnet/Paper (Sprints 15-16).",
        "Direção+carry medidos DENTRO desta janela específica (~10,5 meses, "
        "2023-05..2024-03) são negativos nos dois gates (ver "
        "module_a_fill_reconciliation.optimistic/realistic.decomposition."
        "pnl_direcional) — não reproduzem o sinal do pooled_all_15_splits sobre os "
        "6,5 anos completos; a janela pode não ser representativa do regime médio do "
        "modelo. A comparação otimista-vs-realista continua válida (mesma janela nos "
        "dois lados), mas não deve ser lida como 'o efeito de execução medido sobre o "
        "resultado de 6,5 anos'.",
    )

    return FillReconciliationReport(
        schema_version=1,
        generated_at_utc=datetime.now(UTC).isoformat(),
        model_id=resolved_model_id,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        module_a_fill_reconciliation=reconciliation,
        module_b_fill_selectivity=selectivity,
        limitations=limitations,
    )


def write_report_atomic(report: FillReconciliationReport, dest_path: Path | None = None) -> Path:
    out_path = (
        dest_path
        if dest_path is not None
        else (EXPERIMENTS_DIR / "backtest_fill_reconciliation_report.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")

    blob = orjson.dumps(asdict(report), option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("backtest.fill_reconciliation.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    report = build_report()
    write_report_atomic(report)
    logger.info(
        "backtest.fill_reconciliation.cli_done",
        optimistic_sharpe=report.module_a_fill_reconciliation.optimistic.sharpe_naive,
        realistic_sharpe=report.module_a_fill_reconciliation.realistic.sharpe_naive,
        selectivity_gap_pp=report.module_b_fill_selectivity.gap_pp,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — execução manual
    import sys

    sys.exit(_run_cli())
