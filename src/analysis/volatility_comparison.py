"""M1 — comparação real dos candidatos de volatilidade sobre as 15
combinações (5 ativos × 3 TFs), PRD_V4_1.md §3.2. Orquestração com IO:
carrega `bars` reais via `src.data.lake.query_bars`, roda cada
`VolatilityEstimator` (T0.1, `src.features.volatility`) através do
walk-forward ancorado de `src.validation.volatility_walkforward`, e aplica
os dois eixos de validação do "vencedor" (taxa de vitória por fold +
Diebold-Mariano) — mesma classe de módulo que `src.analysis.cost_surface`
(ponto de entrada manual, nunca dentro da suíte automatizada de testes).

**5 dos 6 candidatos de M1 rodam aqui — só falta `EGARCH(1,1)`.**
`ATRWilderEstimator` é o BASELINE (já em produção, T0.1), nunca um
candidato — os outros 5 (`Parkinson`, `GarmanKlass`, `RealizedVol`, mais
`HAR-RV`) competem contra ele. `HAR-RV` (Corsi 2009,
`src.features.volatility_models`) é o primeiro candidato FOLD-AWARE —
diferente dos 3 fechados (mesmo `estimate()` pra série inteira), ele
reajusta coeficientes por OLS a cada fold, só sobre o próprio treino, e
prevê só a própria região de teste (`_har_rv_forecast_var`). `EGARCH(1,1)`
(MLE) segue a mesma ideia mas ainda não está escrito — infraestrutura de
otimização numérica é escopo maior, deixado pra próxima rodada.

**`window` idêntico entre os 3 candidatos e o baseline — `atr_window`
(`constants.yaml`, valor 20) reusado, não uma constante nova.** Isso NÃO
resolve I2 (PRD §2.7: `atr_window` não tem conversão clock-based entre
TFs) — usar 20 barras em M15/M30/H1 significa 3 janelas de relógio
diferentes (5h/10h/20h). É exatamente a pergunta que I2 deixa em aberto;
esta rodada mede os candidatos na mesma convenção "20 barras" que já está
em produção em 15m, sem fingir que resolve a calibração por TF — isso
fica para uma iteração seguinte de M1 se o resultado desta justificar.

**Escala do forecast — `estimate()**2`.** Todo `VolatilityEstimator`
retorna uma fração do preço (`ATR/close`, `Parkinson`, `Garman-Klass`,
`sigma(log_return)*sqrt(window)`) — escala de DESVIO-PADRÃO, não
variância. `next_bar_realized_variance` (o alvo) é `r_{t+1}^2`, escala de
VARIÂNCIA. Elevar `estimate()` ao quadrado é a única forma de comparar as
duas na mesma escala sem inventar um fator de conversão — não é uma
medição, é a definição de variância a partir de um proxy de desvio-padrão
(mesma convenção de toda a literatura de QLIKE, Patton 2011).

**Janela de dado por símbolo — medida do disco, não presumida.**
`klines_1m` cobre BTCUSDT desde 2019-12-31 e os 4 alts desde 2021-12-01,
todos até 2026-08-07 (checado via `ls data/capacity/klines_1m/<symbol>`
antes de escrever este módulo). Cada símbolo usa sua própria história
completa — não corta BTCUSDT pra bater com os alts, porque mais dado de
treino/teste é estritamente melhor para o walk-forward, e o objetivo aqui
é medir cada candidato o mais precisamente possível, não uma janela comum
entre ativos (isso é outra pergunta, do T0.5).

**Risco reconhecido, não resolvido nesta rodada — decisão explícita do
Manager.** BTCUSDT roda 20 folds (2019-12-31→2026-08-07) contra 12 dos
4 alts (2021-12-01→2026-08-07) — não é só "mais dado", é uma janela de
CALENDÁRIO parcialmente diferente: os 8 folds extras de BTC cobrem
2020-2021, regime que nenhum alt vive. Se um candidato bate o baseline em
BTC mas o efeito vem majoritariamente desses 8 folds extras, "vence em
5/5 ativos" não são 5 votos independentes na mesma condição. Perguntado
explicitamente ao Manager se valeria rodar uma segunda passada com janela
comum (2021-12-01→2026-08-07 pros 5) pra checar se a conclusão sobrevive
-- resposta: não agora, história completa de cada ativo basta por
enquanto; checagem de janela comum fica para uma iteração futura do M1
se o resultado precisar de mais escrutínio (mesma classe de risco que
já mudou conclusão neste projeto antes -- CLAUDE.md, "Comportamento
esperado")."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.core.provenance import report_provenance
from src.data import lake
from src.data.lake import DateLike
from src.features._constants import load_constant
from src.features import volatility_models
from src.features.volatility import (
    ATRWilderEstimator,
    Bars,
    GarmanKlassEstimator,
    ParkinsonEstimator,
    RealizedVolEstimator,
    VolatilityEstimator,
)
from src.validation import volatility_walkforward as vwf
from src.validation._constants import load_constant as load_validation_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "volatility_comparison_report.json"

TIMEFRAMES: Final[tuple[str, ...]] = ("15m", "30m", "1h")

# Data disponível medida do disco (ver docstring do módulo) -- não é
# constante de domínio (§16.10), é fato de cobertura de backfill.
SYMBOL_START_DATE: Final[dict[str, str]] = {
    "BTCUSDT": "2019-12-31",
    "ETHUSDT": "2021-12-01",
    "SOLUSDT": "2021-12-01",
    "BNBUSDT": "2021-12-01",
    "XRPUSDT": "2021-12-01",
}
END_DATE: Final[str] = "2026-08-07"

# Barras por dia corrido (24h, cripto 24/7 -- não a convenção de 5/22
# dias úteis de bolsa tradicional que HAR-RV normalmente usa) por TF --
# insumo de HAR-RV pras janelas dia/semana/mês (volatility_models.py).
TF_BARS_PER_DAY: Final[dict[str, int]] = {"15m": 96, "30m": 48, "1h": 24}


def _baseline_estimator() -> VolatilityEstimator:
    return ATRWilderEstimator.from_constants()


def _candidate_estimators(*, window: int) -> tuple[VolatilityEstimator, ...]:
    return (
        ParkinsonEstimator(window=window),
        GarmanKlassEstimator(window=window),
        RealizedVolEstimator(window=window),
    )


# ============================================================================
# Núcleo — uma (symbol, tf) combinação, `bars` já em memória
# ============================================================================


@dataclass(frozen=True, slots=True)
class EstimatorMetrics:
    """Métricas OOS agregadas (pooled, sobre toda a região de teste do
    walk-forward) de UM estimador em UMA combinação (symbol, tf).

    `qlike_mean` é a média sobre observações FINITAS apenas -- QLIKE
    (Patton 2011) não é robusto a forecast quase-zero: um único bar onde
    `forecast_var` é minúsculo (mas `> 0`, então não vira NaN) faz
    `qlike_loss` explodir pra `inf`, e com centenas de milhares de barras
    reais SEMPRE existe pelo menos um desses -- medido: entre 9 e 1882
    bars por combinação, de ~25k a 170k. Incluir esses pontos faz a média
    pooled virar `inf` em TODA combinação testada (baseline E candidatos
    igualmente), o que tornaria `qlike_mean < baseline.qlike_mean` sempre
    falso por construção e o vencedor indeterminável -- não é uma escolha
    de deixar a métrica "bonita", é a diferença entre a métrica comparar
    alguma coisa ou nunca comparar nada. `n_inf_qlike` reporta quantos
    pontos foram excluídos, pra isso ficar auditável em vez de
    escondido."""

    estimator_id: str
    qlike_mean: float
    mse_mean: float
    bias: float
    mz_intercept: float
    mz_slope: float
    mz_r_squared: float
    mz_n: int
    n_oos_obs: int
    n_inf_qlike: int


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    """Validação do candidato contra o baseline — fold_win_rate (robustez
    por trimestre) + Diebold-Mariano (significância)."""

    metrics: EstimatorMetrics
    fold_win_rate: float
    dm_stat: float
    dm_p_value: float
    beats_baseline_qlike: bool


@dataclass(frozen=True, slots=True)
class CombinationResult:
    symbol: str
    tf: str
    n_bars: int
    n_folds: int
    baseline: EstimatorMetrics
    candidates: tuple[CandidateValidation, ...]
    any_candidate_beats_baseline: bool


def _forecast_var(estimator: VolatilityEstimator, bars: Bars) -> FloatArray:
    sigma_like = estimator.estimate(bars, horizon_minutes=bars.timeframe_minutes)
    forecast_var: FloatArray = sigma_like**2
    return forecast_var


def _oos_slice(splits: tuple[vwf.WalkForwardSplit, ...]) -> tuple[int, int]:
    return splits[0].test_start_idx, splits[-1].test_end_idx


def _per_fold_qlike(
    splits: tuple[vwf.WalkForwardSplit, ...], qlike: FloatArray
) -> FloatArray:
    """Média por fold sobre observações FINITAS -- mesmo racional de
    `_estimator_metrics`/`EstimatorMetrics.qlike_mean`: um `inf` isolado
    dentro de um fold (forecast quase-zero pontual) não pode contaminar o
    fold inteiro, senão `fold_win_rate` vira ruído de qual lado teve o
    `inf` primeiro em vez de medir robustez real."""
    out = np.full(len(splits), np.nan, dtype=np.float64)
    for i, s in enumerate(splits):
        fold_vals = qlike[s.test_start_idx : s.test_end_idx]
        valid = fold_vals[np.isfinite(fold_vals)]
        if valid.size:
            out[i] = float(np.mean(valid))
    return out


def _har_rv_forecast_var(
    realized_var: FloatArray,
    splits: tuple[vwf.WalkForwardSplit, ...],
    *,
    bars_per_day: int,
) -> FloatArray:
    """HAR-RV é fold-aware -- ao contrário dos `VolatilityEstimator`
    fechados (mesmo `estimate()` pra toda a série), cada fold reajusta os
    coeficientes só sobre o próprio treino (`fit_har_rv`) antes de prever
    a própria região de teste. Retorna `forecast_var` NaN fora de toda
    região de teste (não coberta por fold nenhum) -- só a união dos
    `[test_start_idx, test_end_idx)` de todos os folds é preenchida."""
    n = realized_var.shape[0]
    forecast_var = np.full(n, np.nan, dtype=np.float64)
    for split in splits:
        fit = volatility_models.fit_har_rv(
            realized_var, bars_per_day=bars_per_day, train_end_idx=split.train_end_idx
        )
        if fit is None:
            continue
        pred = volatility_models.predict_har_rv(fit, realized_var, bars_per_day=bars_per_day)
        forecast_var[split.test_start_idx : split.test_end_idx] = pred[
            split.test_start_idx : split.test_end_idx
        ]
    return forecast_var


def _estimator_metrics(
    estimator_id: str,
    forecast_var: FloatArray,
    realized_var: FloatArray,
    *,
    oos_start: int,
    oos_end: int,
) -> tuple[EstimatorMetrics, FloatArray]:
    """Retorna as métricas pooled + o array de QLIKE por barra na região
    OOS inteira (reusado por fold_win_rate/diebold_mariano do chamador)."""
    f_oos = forecast_var[oos_start:oos_end]
    r_oos = realized_var[oos_start:oos_end]
    qlike = vwf.qlike_loss(f_oos, r_oos)
    mse = vwf.mse_loss(f_oos, r_oos)
    b = vwf.bias(f_oos, r_oos)
    mz = vwf.mincer_zarnowitz(f_oos, r_oos)
    n_valid = int(np.sum(~np.isnan(qlike)))
    n_inf = int(np.sum(np.isinf(qlike)))
    qlike_finite = qlike[np.isfinite(qlike)]
    metrics = EstimatorMetrics(
        estimator_id=estimator_id,
        qlike_mean=float(np.mean(qlike_finite)) if qlike_finite.size else float("nan"),
        mse_mean=float(np.nanmean(mse)) if n_valid else float("nan"),
        bias=b,
        mz_intercept=mz.intercept,
        mz_slope=mz.slope,
        mz_r_squared=mz.r_squared,
        mz_n=mz.n,
        n_oos_obs=n_valid,
        n_inf_qlike=n_inf,
    )
    return metrics, qlike


def compare_estimators_for_combination(
    symbol: str,
    tf: str,
    bars_df: pl.DataFrame,
    *,
    timeframe_minutes: int,
    candidate_window: int,
    initial_train_years: int,
) -> CombinationResult | None:
    """Núcleo puro de comparação para UMA combinação (symbol, tf), `bars_df`
    já carregado. Retorna `None` se não houver folds suficientes (dado
    insuficiente para o treino inicial de `initial_train_years`) — sinal
    explícito pro chamador pular a combinação, não um resultado fabricado."""
    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()
    splits = vwf.generate_anchored_walk_forward_splits(
        open_time_ms, initial_train_years=initial_train_years
    )
    if not splits:
        logger.warning(
            "analysis.volatility_comparison.folds_insuficientes",
            symbol=symbol,
            tf=tf,
            n_bars=bars_df.height,
        )
        return None

    oos_start, oos_end = _oos_slice(splits)
    bars = Bars(frame=bars_df, timeframe_minutes=timeframe_minutes)
    close = bars_df["close"].cast(pl.Float64).to_numpy()
    realized_var = vwf.next_bar_realized_variance(close)

    baseline = _baseline_estimator()
    baseline_forecast_var = _forecast_var(baseline, bars)
    baseline_metrics, baseline_qlike_oos = _estimator_metrics(
        baseline.estimator_id,
        baseline_forecast_var,
        realized_var,
        oos_start=oos_start,
        oos_end=oos_end,
    )
    baseline_per_fold_qlike = _per_fold_qlike(
        splits, vwf.qlike_loss(baseline_forecast_var, realized_var)
    )

    candidate_forecasts: list[tuple[str, FloatArray]] = [
        (estimator.estimator_id, _forecast_var(estimator, bars))
        for estimator in _candidate_estimators(window=candidate_window)
    ]
    har_rv_forecast_var = _har_rv_forecast_var(
        realized_var, splits, bars_per_day=TF_BARS_PER_DAY[tf]
    )
    candidate_forecasts.append((f"har_rv_d{TF_BARS_PER_DAY[tf]}", har_rv_forecast_var))

    candidates: list[CandidateValidation] = []
    any_beats = False
    for cand_estimator_id, cand_forecast_var in candidate_forecasts:
        cand_metrics, cand_qlike_oos = _estimator_metrics(
            cand_estimator_id,
            cand_forecast_var,
            realized_var,
            oos_start=oos_start,
            oos_end=oos_end,
        )
        cand_per_fold_qlike = _per_fold_qlike(
            splits, vwf.qlike_loss(cand_forecast_var, realized_var)
        )
        win_rate = vwf.fold_win_rate(cand_per_fold_qlike, baseline_per_fold_qlike)
        dm = vwf.diebold_mariano(cand_qlike_oos, baseline_qlike_oos)
        beats = (
            not np.isnan(cand_metrics.qlike_mean)
            and not np.isnan(baseline_metrics.qlike_mean)
            and cand_metrics.qlike_mean < baseline_metrics.qlike_mean
        )
        any_beats = any_beats or beats
        candidates.append(
            CandidateValidation(
                metrics=cand_metrics,
                fold_win_rate=win_rate,
                dm_stat=dm.dm_stat,
                dm_p_value=dm.p_value,
                beats_baseline_qlike=beats,
            )
        )

    return CombinationResult(
        symbol=symbol,
        tf=tf,
        n_bars=bars_df.height,
        n_folds=len(splits),
        baseline=baseline_metrics,
        candidates=tuple(candidates),
        any_candidate_beats_baseline=any_beats,
    )


# ============================================================================
# Ponto de entrada com IO — uma combinação, ou as 15
# ============================================================================


def run_volatility_comparison_for_symbol_tf(
    symbol: str,
    tf: str,
    *,
    start: DateLike | None = None,
    end: DateLike | None = None,
    candidate_window: int | None = None,
    initial_train_years: int | None = None,
) -> CombinationResult | None:
    """Carrega `bars` reais do disco (`lake.query_bars`, `source=klines_1m`)
    e roda `compare_estimators_for_combination`. `start`/`end` default para
    `SYMBOL_START_DATE[symbol]`/`END_DATE` (história completa medida)."""
    resolved_start = start if start is not None else SYMBOL_START_DATE[symbol]
    resolved_end = end if end is not None else END_DATE
    window = (
        candidate_window if candidate_window is not None else int(load_constant("atr_window"))
    )
    train_years = (
        initial_train_years
        if initial_train_years is not None
        else int(load_validation_constant("m1_walkforward_initial_train_years"))
    )

    bars_df = lake.query_bars(
        symbol, tf, resolved_start, resolved_end, source="klines_1m", cast_prices=True
    )
    tf_minutes = {"15m": 15, "30m": 30, "1h": 60}[tf]
    logger.info(
        "analysis.volatility_comparison.bars_loaded",
        symbol=symbol,
        tf=tf,
        n_bars=bars_df.height,
        start=str(resolved_start),
        end=str(resolved_end),
    )
    return compare_estimators_for_combination(
        symbol,
        tf,
        bars_df,
        timeframe_minutes=tf_minutes,
        candidate_window=window,
        initial_train_years=train_years,
    )


def stopping_criterion_1_from_results(results: list[CombinationResult]) -> bool:
    """§6.5 critério de parada #1: se NENHUM candidato bate o baseline em
    QLIKE em NENHUMA combinação avaliada, a linha de busca se encerra
    inteira. `results` vazio -> `False` (ausência de medição não é
    "nenhum candidato venceu", é "nada foi medido ainda")."""
    return bool(results) and not any(r.any_candidate_beats_baseline for r in results)


def _combination_to_dict(result: CombinationResult) -> dict[str, Any]:
    return {
        "symbol": result.symbol,
        "tf": result.tf,
        "n_bars": result.n_bars,
        "n_folds": result.n_folds,
        "baseline": asdict(result.baseline),
        "candidates": [
            {
                "metrics": asdict(c.metrics),
                "fold_win_rate": c.fold_win_rate,
                "dm_stat": c.dm_stat,
                "dm_p_value": c.dm_p_value,
                "beats_baseline_qlike": c.beats_baseline_qlike,
            }
            for c in result.candidates
        ],
        "any_candidate_beats_baseline": result.any_candidate_beats_baseline,
    }


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 — mesmo padrão de `cost_surface._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("analysis.volatility_comparison.report_written", path=str(dest_path))


def run_and_save_volatility_comparison_report(
    *,
    symbols: tuple[str, ...] = tuple(SYMBOL_START_DATE),
    timeframes: tuple[str, ...] = TIMEFRAMES,
    dest_path: Path | None = None,
) -> Path:
    """Ponto de entrada MANUAL — roda as `len(symbols) * len(timeframes)`
    combinações (15 por default) e persiste o relatório completo, atômico
    (B29). NÃO roda dentro da suíte automatizada (custo de IO + cálculo em
    15 combinações não paga a cada `pytest`).

    Chame manualmente:
    `uv run python -c "from src.analysis.volatility_comparison import run_and_save_volatility_comparison_report as r; r()"`
    ou `uv run python -m src.analysis.volatility_comparison`."""
    t0 = time.perf_counter()
    results: list[CombinationResult] = []
    skipped: list[dict[str, str]] = []
    for symbol in symbols:
        for tf in timeframes:
            result = run_volatility_comparison_for_symbol_tf(symbol, tf)
            if result is None:
                skipped.append({"symbol": symbol, "tf": tf, "reason": "folds_insuficientes"})
                continue
            results.append(result)
            logger.info(
                "analysis.volatility_comparison.combination_done",
                symbol=symbol,
                tf=tf,
                n_folds=result.n_folds,
                baseline_qlike=round(result.baseline.qlike_mean, 6),
                any_candidate_beats_baseline=result.any_candidate_beats_baseline,
            )
    elapsed_s = time.perf_counter() - t0

    # Combinações puladas (dado insuficiente) não contam nem a favor nem
    # contra -- não são medição, são ausência de medição.
    stopping_criterion_1_triggered = stopping_criterion_1_from_results(results)

    payload: dict[str, Any] = {
        **report_provenance(),
        "n_combinations_requested": len(symbols) * len(timeframes),
        "n_combinations_evaluated": len(results),
        "skipped": skipped,
        "elapsed_seconds_total": elapsed_s,
        "stopping_criterion_1_triggered": stopping_criterion_1_triggered,
        "combinations": [_combination_to_dict(r) for r in results],
    }
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info(
        "analysis.volatility_comparison.done",
        n_combinations_evaluated=len(results),
        n_skipped=len(skipped),
        elapsed_seconds_total=round(elapsed_s, 1),
        stopping_criterion_1_triggered=stopping_criterion_1_triggered,
        dest=str(dest),
    )
    return dest


if __name__ == "__main__":
    run_and_save_volatility_comparison_report()
