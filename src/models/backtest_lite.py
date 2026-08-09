"""Harness de avaliação mínimo para esta rodada — NÃO é o motor de
backtest do projeto (§11.1/§14.1: "não escreva motor próprio antes de
avaliar o de prateleira", CLAUDE.md). Este módulo faz só o suficiente para
comparar Camada 1 vs Camada 0 e os 5 baselines nulos do §16.1 sobre os
MESMOS trades já materializados em `labels/v1/labels.parquet` (barreiras,
custos, quantização e funding já aplicados por `src.labels.triple_barrier`
— este módulo não resimula nada disso, só agrega `ret_net` já calculado).

**Sharpe "ingênuo" (não corrigido por autocorrelação, §16.5, nem por DSR,
§11.6) — ambos fora de escopo desta rodada por instrução explícita da
task.** `sharpe_naive = mean(ret_net) / std(ret_net) * sqrt(trades/ano)`,
anualizado pela frequência REAL de trade observada na amostra (não um
fator fixo) — mesma fórmula aplicada a Alpha e a TODOS os baselines
(§16.1: "rodando no mesmo motor... idênticos"), então a comparação relativa
é válida mesmo sem a correção de Lo(2002)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from .alpha import FoldResult

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

# Dias por ano (calendário Gregoriano médio) — constante matemática de
# calendário, não de domínio (mesma categoria de `_BPS_PER_UNIT` em
# `triple_barrier.py`, `24 * 60 * 60 * 1000` em `test_validation_cpcv.py`).
# Públicas (sem `_`) — reusadas por `src.models.baselines` e
# `src.models.decomposition`, que precisam da MESMA convenção de
# anualização que este módulo usa para Alpha (§16.1: "mesmo motor").
DAYS_PER_YEAR = 365.25  # noqa: magic-number
SECONDS_PER_DAY = 86_400  # noqa: magic-number
_MIN_TRADES_FOR_SHARPE = 2  # noqa: magic-number — desvio padrão amostral exige >= 2 pontos


def sharpe_naive(trade_returns: FloatArray, *, span_seconds: float) -> tuple[float, float]:
    """`span_seconds` é o intervalo de calendário coberto pela AMOSTRA de
    trades (não um horizonte arbitrário) — `trades_per_year` é derivado
    disso, nunca de uma constante fixa. Retorna `(sharpe, trades_per_year)`;
    `nan` se não houver dados suficientes para desvio padrão."""
    n = trade_returns.shape[0]
    if n < _MIN_TRADES_FOR_SHARPE or span_seconds <= 0.0:
        return float("nan"), float("nan")
    span_years = span_seconds / (DAYS_PER_YEAR * SECONDS_PER_DAY)
    trades_per_year = n / span_years if span_years > 0 else float("nan")
    mean = float(np.mean(trade_returns))
    std = float(np.std(trade_returns, ddof=1))
    if std == 0.0 or not np.isfinite(trades_per_year):
        return float("nan"), trades_per_year
    return mean / std * float(np.sqrt(trades_per_year)), trades_per_year


def span_seconds(t0_series: pl.Series) -> float:
    """Segundos de calendário entre o primeiro e o último `t0` da série —
    pública porque `src.models.baselines`/`src.models.decomposition`
    precisam da mesma definição de "janela coberta" que este módulo usa
    para `sharpe_naive`."""
    if t0_series.len() < _MIN_TRADES_FOR_SHARPE:
        return 0.0
    # `pl.Series.min()`/`.max()` devolvem um union amplo nos stubs do
    # polars (qualquer literal Python possível, não o dtype real da
    # série) — `cast` para `datetime` é seguro aqui porque o contrato do
    # módulo (`t0_series` vem sempre de uma coluna `Datetime`) já é
    # verificado pelos chamadores reais (`realize_trades`/labels reais).
    t_min = cast(datetime, t0_series.min())
    t_max = cast(datetime, t0_series.max())
    return float((t_max - t_min).total_seconds())


def realize_trades(fold_results: list[FoldResult], df_all: pl.DataFrame) -> pl.DataFrame:
    """Junta os sinais (`side_hat != 0`) de todos os `fold_results` ao
    resultado REAL do lado sinalizado em `df_all` (`labels/v1/labels.parquet`
    já enriquecido, `src.models.dataset.build_modeling_frame`). Linhas cujo
    lado sinalizado deu `NOFILL` são preservadas com `barrier_hit ==
    "NOFILL"` (não descartadas aqui) — quem quiser só os trades
    EXECUTADOS filtra explicitamente, quem quer medir taxa de preenchimento
    do sinal precisa do denominador completo."""
    parts: list[pl.DataFrame] = []
    for fr in fold_results:
        sig = fr.predictions.filter(pl.col("side_hat") != 0).select(
            pl.col("t0"),
            pl.col("side_hat"),
            pl.col("fold_id"),
            pl.lit(fr.path_id, dtype=pl.Int64).alias("path_id"),
            pl.lit(fr.variant, dtype=pl.Utf8).alias("variant"),
        )
        parts.append(sig)
    # `ret_gross`/`cost_entry_bps`/`cost_exit_bps`/`funding_bps` entram além
    # de `ret_net`/`sample_weight` porque `src.models.decomposition` (§16.6)
    # precisa dos três termos ORIGINAIS do label, não só o líquido — ver
    # docstring daquele módulo.
    _JOIN_COLUMNS = (
        "t0", "side", "barrier_hit", "ret_net", "sample_weight",
        "ret_gross", "cost_entry_bps", "cost_exit_bps", "funding_bps",
    )
    if not parts:
        return pl.DataFrame(
            schema={
                "t0": pl.Datetime("ms", "UTC"),
                "side_hat": pl.Int8,
                "fold_id": pl.Int16,
                "path_id": pl.Int64,
                "variant": pl.Utf8,
                "side": pl.Int8,
                "barrier_hit": pl.Utf8,
                "ret_net": pl.Float64,
                "sample_weight": pl.Float64,
                "ret_gross": pl.Float64,
                "cost_entry_bps": pl.Float64,
                "cost_exit_bps": pl.Float64,
                "funding_bps": pl.Float64,
            }
        )
    all_signals = pl.concat(parts, how="vertical")
    joined = all_signals.join(
        df_all.select(list(_JOIN_COLUMNS)),
        left_on=["t0", "side_hat"],
        right_on=["t0", "side"],
        how="left",
    )
    return joined.with_columns(pl.col("barrier_hit").cast(pl.Utf8))


@dataclass(frozen=True, slots=True)
class PathBacktestResult:
    path_id: int
    n_signals: int
    n_filled_trades: int
    fill_rate: float
    sharpe_naive: float
    mean_trade_ret: float
    std_trade_ret: float
    trades_per_year: float


def backtest_by_path(
    fold_results: list[FoldResult], df_all: pl.DataFrame
) -> dict[int, PathBacktestResult]:
    """Um `PathBacktestResult` por caminho de backtest do CPCV (5, §11.4) —
    cada caminho reconstrói o dataset inteiro exatamente uma vez (união dos
    3 splits daquele `path_id`, sem sobreposição de barra, ver docstring de
    `src.validation.cpcv`), então é uma trajetória OOS completa e válida."""
    realized_all = realize_trades(fold_results, df_all)
    path_ids = sorted({fr.path_id for fr in fold_results})
    out: dict[int, PathBacktestResult] = {}
    for path_id in path_ids:
        sub = realized_all.filter(pl.col("path_id") == path_id).sort("t0")
        n_signals = sub.height
        filled = sub.filter(pl.col("barrier_hit") != "NOFILL")
        n_filled = filled.height
        fill_rate = float(n_filled) / float(n_signals) if n_signals > 0 else float("nan")
        span = span_seconds(filled["t0"])
        rets = filled["ret_net"].to_numpy().astype(np.float64)
        sharpe, tpy = sharpe_naive(rets, span_seconds=span)
        mean_ret = float(np.mean(rets)) if rets.size else float("nan")
        std_ret = (
            float(np.std(rets, ddof=1)) if rets.size >= _MIN_TRADES_FOR_SHARPE else float("nan")
        )
        out[path_id] = PathBacktestResult(
            path_id=path_id,
            n_signals=n_signals,
            n_filled_trades=n_filled,
            fill_rate=fill_rate,
            sharpe_naive=sharpe,
            mean_trade_ret=mean_ret,
            std_trade_ret=std_ret,
            trades_per_year=tpy,
        )
    logger.info(
        "models.backtest_lite.backtest_by_path",
        n_paths=len(out),
        sharpe_by_path={pid: r.sharpe_naive for pid, r in out.items()},
    )
    return out


def permanence_count(
    camada1_by_path: dict[int, PathBacktestResult],
    camada0_by_path: dict[int, PathBacktestResult],
) -> tuple[int, int]:
    """`(n_paths_melhores, n_paths_total)` — quantos dos caminhos a Camada 1
    supera a Camada 0 conceitual (mesmo `path_id` nos dois dicionários,
    §5.11 adaptado). `NaN` (sem trades suficientes) nunca conta como
    melhora."""
    common = sorted(set(camada1_by_path) & set(camada0_by_path))
    n_better = 0
    for pid in common:
        s1 = camada1_by_path[pid].sharpe_naive
        s0 = camada0_by_path[pid].sharpe_naive
        if np.isfinite(s1) and np.isfinite(s0) and s1 >= s0:
            n_better += 1
    return n_better, len(common)
