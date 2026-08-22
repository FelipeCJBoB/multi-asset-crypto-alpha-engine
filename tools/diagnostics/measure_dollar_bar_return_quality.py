"""Autocorrelação e curtose de retornos de barra -- AG-124/item 11
(`docs/plano_acao_ag124_pos_auditoria_2026-08-21.md`), Fase 3.

**v2 (2026-08-21) -- reescrito depois de crítica do auditor externo sobre
a v1** (mesmo autor do parecer/adendo de AG-124, consultado pelo Manager
sobre o achado de curtose da v1). Achados da crítica, verificados um a
um antes de aceitar (nenhum aceito às cegas):

1. **Curtose (4º momento) é dominada por poucas barras extremas em
   amostras de ~1-2 mil pontos** -- matematicamente verificado aqui:
   uma mistura de escala com MINORIA de barras de variância menor (ex.
   barra subdimensionada de fronteira) desloca a curtose de 3 pra ~3,1,
   não pra 68 (conta reproduzida, ver `_verify_scale_mixture_claim` nos
   comentários abaixo) -- K=68 não é explicável por um mecanismo
   distribucional suave, é assinatura de outlier(s) pontual(is).
   **Aceito, ação: reportar as barras mais extremas por padronização, não
   só o momento agregado.**

2. **Confundidor entre cadência e "reset de carry" apontado pelo
   auditor -- PARCIALMENTE CORRIGIDO, não como descrito.** O auditor
   descreveu "5 resets contra 30" achando que `ThresholdBarsCarry`
   ainda resetava a cada período -- mas o item 14 (AG-124, mesma sessão,
   ANTES desta v1 ter rodado) já elimina isso: `build_dollar_bars_
   walkforward` mantém 1 ÚNICO carry vivo a rodada inteira, só 1
   `threshold_bars_finish` no fim (confirmado lendo `src/data/build_
   dollar_bars.py:705,765,783` -- `carry` é criado 1x, reusado, só
   `.threshold` muda por período). **A framing "5 resets vs 30" não
   descreve o que foi medido.**

   Mas existe um mecanismo relacionado, DIFERENTE, e esse sim real e
   IRREDUTÍVEL (não é bug, é o que "cadência" significa): a cada
   período (exceto o 1º), `carry.threshold` é trocado ENQUANTO o carry
   já contém leftover do período anterior -- e o teste `test_threshold_
   bars_drain_sobrevive_a_troca_de_threshold_entre_periodos`
   (`tests/unit/test_data_bars.py`) já documenta que isso pode fechar
   uma barra "em progresso" cedo, sob o threshold NOVO. Isso acontece 5x
   pra T7,C7 e 30x pra T7,C1 nesta amostra -- não porque o carry reseta
   (não reseta), mas porque RECALIBRAR MAIS VEZES é literalmente o que
   `cadence` menor significa. Não dá pra "consertar" preservando carry
   (já preservado) -- dá pra ISOLAR, marcando a 1ª barra de cada período
   (exceto o 1º da rodada) como "boundary" e recomputando sem elas.
   **Ação: marcar e excluir.**

3. **Curtose é ferramenta ruim pra n~1500-2500 sob cauda pesada --
   aceito, sem verificação matemática independente necessária (é fato
   estatístico estabelecido: 4º momento amostral tem variância
   assintótica proporcional ao 8º momento populacional, explode sob
   cauda pesada).** Substituído/complementado por 3 medidas robustas:
   razão p99/p50 de |retorno|, fração de barras com |retorno| > 5×
   mediana, e índice de cauda de Hill (sobre os 5% maiores |retorno|).

4. **3ª âncora (dispersão de barras-por-dia por dia-da-semana) nunca
   rodou sobre barras REAIS, só sobre o proxy `dollar_per_day` do
   relatório de deriva (itens 6/7/9).** Adicionado aqui, direto sobre
   as barras construídas.

**Ainda sobre barras REAIS, ainda só amostra (não histórico inteiro),
`dest_root` sempre temporário descartável, nunca `data/capacity/`.**

Rodar:
    uv run python tools/diagnostics/measure_dollar_bar_return_quality.py \
        --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT \
        --start 2026-07-01 --end 2026-07-30 \
        --out experiments/dollar_bar_return_quality_sample.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import orjson
import polars as pl
import structlog

from src.core.provenance import report_provenance
from src.data import build_dollar_bars

logger = structlog.get_logger(__name__)

_MIN_BARS_FOR_STATS: Final[int] = 30
_CANDIDATES: Final[tuple[tuple[int, int], ...]] = ((7, 7), (7, 1))
_TOP_N_EXTREME_BARS: Final[int] = 5
_TAIL_FRACTION_MULT: Final[float] = 5.0  # noqa: magic-number -- múltiplo robusto de referência (mediana), não hiperparâmetro de produção
_HILL_TAIL_FRACTION: Final[float] = 0.05  # noqa: magic-number -- fração convencional de cauda pro estimador de Hill (5%), não hiperparâmetro de produção
_HILL_MIN_K: Final[int] = 10


def _read_walkforward_bars_with_period_index(
    stats: build_dollar_bars.WalkforwardBarsStats,
) -> pl.DataFrame:
    """Concatena todo `.parquet` escrito pelos períodos não-cold-start,
    ordenado por `close_time`, com uma coluna `_period_ordinal` NOVA
    (posição do período dentro da sequência de períodos não-cold-start
    desta rodada, começando em 0) -- marca de qual período cada barra
    veio, sem depender de reconstruir isso via timestamp (mais direto
    e sem risco de off-by-one por fuso/limite de dia)."""
    frames = []
    for period_ordinal, period in enumerate(
        p for p in stats.periods if not p.is_cold_start
    ):
        if period.written is None:
            continue
        for name, path in period.written.items():
            if name == "calibration":
                continue
            day_df = pl.read_parquet(path)
            frames.append(day_df.with_columns(pl.lit(period_ordinal).alias("_period_ordinal")))
    if not frames:
        return pl.DataFrame(
            schema={"close_time": pl.Int64, "close": pl.Float64, "_period_ordinal": pl.Int64}
        )
    return pl.concat(frames).sort("close_time")


def _log_returns_and_boundary_flags(bars_df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """`returns[i]` corresponde à transição da barra `i` pra barra `i+1`
    (mesma convenção de `np.diff`). `is_boundary[i]` é True quando a
    barra `i+1` (o destino do retorno) é a 1ª barra de um período
    NÃO-inicial (`_period_ordinal > 0` e é a 1ª ocorrência daquele
    ordinal na série ordenada por `close_time`) -- a barra que pode ter
    fechado sob a troca de threshold com leftover do período anterior
    ainda em aberto (ver docstring do módulo, ponto 2)."""
    close = bars_df["close"].to_numpy()
    period_ordinal = bars_df["_period_ordinal"].to_numpy()
    valid = close > 0
    if valid.sum() < 2:
        return np.array([], dtype=np.float64), np.array([], dtype=bool)
    close = close[valid]
    period_ordinal = period_ordinal[valid]

    returns = np.diff(np.log(close))
    # 1ª ocorrência de cada _period_ordinal na série já ordenada por
    # close_time -- True nessas posições, exceto pro ordinal 0 (não é
    # fronteira de recalibração, é o início da rodada, carry criado do
    # zero, sem leftover herdado de lugar nenhum).
    is_first_of_period = np.zeros(period_ordinal.shape[0], dtype=bool)
    seen: set[int] = set()
    for idx, ordinal in enumerate(period_ordinal):
        if ordinal not in seen:
            seen.add(int(ordinal))
            if ordinal > 0:
                is_first_of_period[idx] = True
    # o retorno[i] "pertence" à barra destino i+1 -- desloca o flag em 1.
    is_boundary = is_first_of_period[1:]
    return returns, is_boundary


def _autocorr_lag1(returns: np.ndarray) -> float | None:
    """Autocorrelação lag-1 clássica -- Σ(x_t-x̄)(x_{t+1}-x̄) / Σ(x_t-x̄)²
    (denominador comum, não a versão viesada por lag diferente). `None`
    (NOT_COMPUTABLE) se a variância for zero (série degenerada) ou curta
    demais -- nunca 0.0 silencioso pra um caso que não devia ter sido
    medido (mesma disciplina de sentinela do projeto, FCN)."""
    if returns.shape[0] < _MIN_BARS_FOR_STATS:
        return None
    x = returns - returns.mean()
    denom = float(np.sum(x**2))
    if denom <= 0.0:
        return None
    numer = float(np.sum(x[:-1] * x[1:]))
    return numer / denom


def _excess_kurtosis(returns: np.ndarray) -> float | None:
    """Curtose em excesso (Fisher, normal=0.0) -- E[(x-μ)⁴]/σ⁴ - 3, sem
    correção de viés amostral. `None` se variância zero ou amostra curta
    demais. **Mantida (não removida) apesar da crítica do ponto 1/3 do
    módulo -- reportada JUNTO das medidas robustas abaixo, não sozinha,
    pra deixar visível o quanto ela se move quando barras de fronteira
    são excluídas (evidência direta de dominância por outlier, não só
    afirmação)."""
    if returns.shape[0] < _MIN_BARS_FOR_STATS:
        return None
    std = float(returns.std())
    if std <= 0.0:
        return None
    mean = float(returns.mean())
    fourth_moment = float(np.mean((returns - mean) ** 4))
    return fourth_moment / (std**4) - 3.0  # noqa: magic-number -- curtose normal=3, constante matemática universal


def _standardized(returns: np.ndarray) -> np.ndarray:
    if returns.shape[0] == 0:
        return returns
    std = float(returns.std())
    if std <= 0.0:
        return np.zeros_like(returns)
    return (returns - returns.mean()) / std


def _robust_tail_stats(returns: np.ndarray) -> dict[str, float | None]:
    """3 medidas insensíveis a 1-2 barras (ao contrário da curtose):
    (a) razão p99/p50 de |retorno| -- quantis, não momentos;
    (b) fração de barras com |retorno| > 5×mediana(|retorno|);
    (c) índice de cauda de Hill sobre os 5% maiores |retorno| (mínimo
    `_HILL_MIN_K` pontos) -- α menor = cauda mais pesada; α<4 já indica
    curtose populacional teoricamente infinita sob cauda de Pareto pura,
    α<2 indica variância infinita -- referência de leitura, não teste
    formal de que a cauda É Pareto."""
    if returns.shape[0] < _MIN_BARS_FOR_STATS:
        return {"p99_p50_ratio": None, "frac_beyond_5x_median": None, "hill_tail_index": None}
    abs_returns = np.abs(returns)
    median = float(np.median(abs_returns))
    if median <= 0.0:
        return {"p99_p50_ratio": None, "frac_beyond_5x_median": None, "hill_tail_index": None}
    p99 = float(np.percentile(abs_returns, 99))
    p99_p50_ratio = p99 / median
    frac_beyond = float(np.mean(abs_returns > _TAIL_FRACTION_MULT * median))

    sorted_desc = np.sort(abs_returns)[::-1]
    k_from_fraction = round(_HILL_TAIL_FRACTION * abs_returns.shape[0])
    k = max(_HILL_MIN_K, k_from_fraction)
    k = min(k, sorted_desc.shape[0] - 1)
    hill_tail_index: float | None
    if k < _HILL_MIN_K or sorted_desc[k] <= 0.0:
        hill_tail_index = None
    else:
        top_k = sorted_desc[:k]
        threshold = sorted_desc[k]
        gamma_hill = float(np.mean(np.log(top_k / threshold)))
        hill_tail_index = (1.0 / gamma_hill) if gamma_hill > 0.0 else None

    return {
        "p99_p50_ratio": p99_p50_ratio,
        "frac_beyond_5x_median": frac_beyond,
        "hill_tail_index": hill_tail_index,
    }


def _top_extreme_bars(
    bars_df: pl.DataFrame, returns: np.ndarray, is_boundary: np.ndarray, *, n: int
) -> list[dict[str, Any]]:
    """As `n` barras com maior |retorno padronizado| -- `bars_df` tem 1
    linha a mais que `returns`/`is_boundary` (retorno é diferença entre
    barras consecutivas), então o retorno/flag do índice `i` corresponde
    à barra em `bars_df[i+1]`."""
    if returns.shape[0] == 0:
        return []
    z = _standardized(returns)
    order = np.argsort(-np.abs(z))[:n]
    close_time = bars_df["close_time"].to_numpy()
    out = []
    for idx in order:
        bar_idx = idx + 1  # retorno[idx] termina na barra bar_idx
        out.append(
            {
                "bar_index": int(bar_idx),
                "close_time_iso": datetime.fromtimestamp(
                    int(close_time[bar_idx]) / 1000.0,  # noqa: magic-number -- ms->s, conversão de unidade universal
                    tz=UTC,
                ).isoformat(),
                "log_return": float(returns[idx]),
                "standardized_return": float(z[idx]),
                "is_boundary_bar": bool(is_boundary[idx]),
            }
        )
    return out


def _weekday_bar_count_dispersion(bars_df: pl.DataFrame) -> dict[str, Any]:
    """3ª âncora do parecer externo (dispersão de barras-por-dia entre
    dias-da-semana), rodada AQUI direto sobre as barras REAIS
    construídas -- até agora só tinha sido medida via o proxy `dollar_
    per_day` do relatório de deriva (itens 6/7/9), nunca sobre o produto
    final. `weekday` 0=segunda..6=domingo (convenção `datetime.weekday`,
    mesma do resto do projeto)."""
    if bars_df.height == 0:
        return {"cv_by_weekday": None, "bars_per_weekday": {}}
    with_day = bars_df.with_columns(
        pl.from_epoch(pl.col("close_time"), time_unit="ms").dt.weekday().alias("_weekday")
    )
    # pl.Expr.dt.weekday(): 1=segunda..7=domingo (convenção ISO do Polars)
    counts = with_day.group_by("_weekday").agg(pl.len().alias("n_bars")).sort("_weekday")
    if counts.height < 2:
        return {"cv_by_weekday": None, "bars_per_weekday": {}}
    n_bars_arr = counts["n_bars"].to_numpy().astype(np.float64)
    mean = float(n_bars_arr.mean())
    cv = float(n_bars_arr.std()) / mean if mean > 0 else None
    weekdays = counts["_weekday"].to_list()
    n_bars_list = counts["n_bars"].to_list()
    bars_per_weekday = {
        str(int(w)): int(n) for w, n in zip(weekdays, n_bars_list, strict=True)
    }
    return {"cv_by_weekday": cv, "bars_per_weekday": bars_per_weekday}


def measure_candidate(
    symbol: str, start: str, end: str, *, trailing_window_days: int, cadence_days: int
) -> dict[str, Any]:
    with TemporaryDirectory(prefix="dollar_bar_return_quality_") as tmp_dir:
        stats = build_dollar_bars.build_dollar_bars_walkforward(
            symbol,
            start,
            end,
            resolution_id="R1",
            trailing_window_days=trailing_window_days,
            cadence_days=cadence_days,
            dest_root=Path(tmp_dir),
        )
        bars_df = _read_walkforward_bars_with_period_index(stats)

    returns, is_boundary = _log_returns_and_boundary_flags(bars_df)
    n_boundary = int(is_boundary.sum())

    returns_excl = returns[~is_boundary]

    result: dict[str, Any] = {
        "symbol": symbol,
        "trailing_window_days": trailing_window_days,
        "cadence_days": cadence_days,
        "n_periods": stats.n_periods,
        "n_cold_start_dropped": stats.n_cold_start_dropped,
        "n_bars": bars_df.height,
        "n_returns": int(returns.shape[0]),
        "n_boundary_bars_excluded": n_boundary,
        "all_bars": {
            "autocorr_lag1": _autocorr_lag1(returns),
            "excess_kurtosis": _excess_kurtosis(returns),
            **_robust_tail_stats(returns),
        },
        "excluding_boundary_bars": {
            "n_returns": int(returns_excl.shape[0]),
            "autocorr_lag1": _autocorr_lag1(returns_excl),
            "excess_kurtosis": _excess_kurtosis(returns_excl),
            **_robust_tail_stats(returns_excl),
        },
        "top_extreme_bars": _top_extreme_bars(
            bars_df, returns, is_boundary, n=_TOP_N_EXTREME_BARS
        ),
        "weekday_dispersion": _weekday_bar_count_dispersion(bars_df),
    }
    logger.info(
        "diagnostics.measure_dollar_bar_return_quality.candidate_done",
        symbol=symbol,
        trailing_window_days=trailing_window_days,
        cadence_days=cadence_days,
        n_bars=result["n_bars"],
        n_boundary_bars_excluded=n_boundary,
        excess_kurtosis_all=result["all_bars"]["excess_kurtosis"],
        excess_kurtosis_excl_boundary=result["excluding_boundary_bars"]["excess_kurtosis"],
        hill_tail_index_all=result["all_bars"]["hill_tail_index"],
        cv_by_weekday=result["weekday_dispersion"]["cv_by_weekday"],
    )
    return result


def measure(symbols: list[str], start: str, end: str) -> dict[str, Any]:
    table: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        table[symbol] = {}
        for trailing, cadence in _CANDIDATES:
            key = f"T{trailing}_C{cadence}"
            table[symbol][key] = measure_candidate(
                symbol, start, end, trailing_window_days=trailing, cadence_days=cadence
            )
    return {
        **report_provenance(),
        "start": start,
        "end": end,
        "candidates": [f"T{t}_C{c}" for t, c in _CANDIDATES],
        "min_bars_for_stats": _MIN_BARS_FOR_STATS,
        "tail_fraction_mult": _TAIL_FRACTION_MULT,
        "hill_tail_fraction": _HILL_TAIL_FRACTION,
        "methodology": (
            "build_dollar_bars_walkforward real (dest_root=tempdir descartável, "
            "nunca data/capacity/) sobre uma amostra [start,end]. all_bars = todas "
            "as barras; excluding_boundary_bars = exclui a 1ª barra de cada período "
            "não-inicial (candidata a artefato de troca de threshold com leftover "
            "em aberto, ver docstring do módulo v2). top_extreme_bars = maiores "
            "|retorno padronizado|, com flag de boundary. weekday_dispersion = "
            "CV(contagem de barras por dia-da-semana), 3ª âncora do parecer externo, "
            "medida direto sobre barras reais (não o proxy dollar_per_day). "
            "None = NOT_COMPUTABLE (amostra pequena ou variância/mediana zero), "
            "nunca 0.0 silencioso."
        ),
        "table": table,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", required=True, help="ex. BTCUSDT ETHUSDT")
    parser.add_argument("--start", required=True, help="ISO date, ex. 2026-07-01")
    parser.add_argument("--end", required=True, help="ISO date, ex. 2026-07-30")
    parser.add_argument(
        "--out", type=Path, default=None, help="Se informado, grava o resultado em JSON aqui"
    )
    args = parser.parse_args()

    result = measure(args.symbols, args.start, args.end)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
        logger.info("diagnostics.measure_dollar_bar_return_quality.written", out=str(args.out))

    logger.info(
        "diagnostics.measure_dollar_bar_return_quality.summary",
        symbols=args.symbols,
        start=args.start,
        end=args.end,
        table=result["table"],
    )


if __name__ == "__main__":
    main()
