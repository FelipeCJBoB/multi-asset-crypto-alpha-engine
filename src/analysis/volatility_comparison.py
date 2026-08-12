"""Comparação real de estimadores de volatilidade sobre as 15 combinações
(5 ativos × 3 TFs). Orquestração com IO: carrega `bars` reais via
`src.data.lake.query_bars`, roda cada `VolatilityEstimator` (T0.1,
`src.features.volatility`) através do walk-forward ancorado de
`src.validation.volatility_walkforward`, e aplica os dois eixos de
validação do "vencedor" (taxa de vitória por fold + Diebold-Mariano) —
mesma classe de módulo que `src.analysis.cost_surface` (ponto de entrada
manual, nunca dentro da suíte automatizada de testes).

**M1 (PRD_V4_1.md §3.2) já fechou com os 6 candidatos declarados no
texto do PRD** (`ATRWilder`, `EGARCH(1,1)`, `HAR-RV`, `Parkinson`,
`GarmanKlass`, `RealizedVol`) — resultado congelado em
`experiments/volatility_comparison_report.json` (commit `2410bc1`,
histórico, não regenerado por este módulo). `§6.5` critério 1 NÃO
disparou: Parkinson e Garman-Klass bateram `ATRWilder` em QLIKE em
14/15 combinações (Garman-Klass venceu a comparação direta Parkinson×GK
em 9 das 14), HAR-RV venceu 1 (ETHUSDT×H1), EGARCH(1,1) e RealizedVol
nunca venceram. **Decisão do Manager (2026-08-11): Garman-Klass é o
vencedor.**

**Este módulo, a partir daqui, é a extensão PÓS-M1** (não texto do PRD):
`ATRWilderEstimator` (baseline antigo), `HAR-RV` e `EGARCH(1,1)` foram
amputados do harness — perderam a comparação e não têm mais papel aqui
(a classe `ATRWilderEstimator` continua existindo em
`src.features.volatility`, intocada: é bit-idêntica ao que roda em
produção e tem golden test contra `labels/v1/labels.parquet`, só não é
mais o baseline DESTE harness). `RealizedVol` também saiu (pior candidato
em 15/15, sem indício de que voltaria a competir). **O baseline agora é
`GarmanKlass`** (o vencedor de M1) e os candidatos são `Parkinson`
(mantido, quase empatado com GK) + os 2 novos: `RogersSatchell` (1991,
remove a suposição de drift zero que Parkinson/GK carregam) e
`YangZhang` (2000, soma o componente overnight/gap que GK ignora) — ver
docstrings de `support.rogers_satchell_vol`/`support.yang_zhang_vol` para
as fórmulas. Os 2 novos são candidatos de fórmula fechada, mesma classe
computacional de Parkinson/GK (sem MLE/OLS por fold) — por isso não são
`FOLD-AWARE`: `estimate()` sozinho já é a resposta pra série inteira,
igual aos 3 candidatos fechados do M1 original.

**`window` idêntico entre os candidatos e o baseline — `atr_window`
(`constants.yaml`, valor 20) reusado, não uma constante nova.** Isso NÃO
resolve I2 (PRD §2.7: `atr_window` não tem conversão clock-based entre
TFs) — usar 20 barras em M15/M30/H1 significa 3 janelas de relógio
diferentes (5h/10h/20h). Mesma ressalva do M1 original, não resolvida
aqui.

**Escala do forecast — `estimate()**2`.** Todo `VolatilityEstimator`
retorna uma fração do preço (`Garman-Klass`, `Parkinson`,
`Rogers-Satchell`, `Yang-Zhang`) — escala de DESVIO-PADRÃO, não
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
from concurrent.futures import ProcessPoolExecutor, as_completed
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
from src.features.volatility import (
    Bars,
    GarmanKlassEstimator,
    ParkinsonEstimator,
    RogersSatchellEstimator,
    VolatilityEstimator,
    YangZhangEstimator,
)
from src.validation import volatility_walkforward as vwf
from src.validation._constants import load_constant as load_validation_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
# Nome distinto do artefato histórico do M1 original
# (`volatility_comparison_report.json`, commit `2410bc1`, 6 candidatos
# contra baseline ATRWilder) -- essa rodada compara uma família diferente
# de candidatos contra um baseline diferente (GK), não é o mesmo
# experimento regravado por cima.
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "volatility_rs_yz_vs_gk_report.json"

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


def _baseline_estimator(*, window: int) -> VolatilityEstimator:
    """Garman-Klass -- vencedor de M1 (ver docstring do módulo). Antes de
    2026-08-11 este papel era `ATRWilderEstimator.from_constants()`; a
    classe continua existindo em `src.features.volatility` (golden test
    contra produção), só não é mais o baseline DESTE harness."""
    return GarmanKlassEstimator(window=window)


def _candidate_estimators(*, window: int) -> tuple[VolatilityEstimator, ...]:
    return (
        ParkinsonEstimator(window=window),
        RogersSatchellEstimator(window=window),
        YangZhangEstimator(window=window),
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

    baseline = _baseline_estimator(window=candidate_window)
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
    """Checagem genérica "nenhum candidato bateu o baseline em QLIKE em
    NENHUMA combinação avaliada" -- mesmo mecanismo do `§6.5` critério de
    parada #1 do PRD, mas **não é mais literalmente esse gate**: o gate
    formal já resolveu (`False`) na rodada original de M1 contra
    `ATRWilder` (`experiments/volatility_comparison_report.json`, commit
    `2410bc1`, histórico congelado). Aqui o "baseline" é `GarmanKlass` (o
    vencedor de M1) -- reaplicar o mesmo mecanismo pra decidir se vale a
    pena promover Rogers-Satchell/Yang-Zhang, não pra reabrir o gate do
    PRD. `results` vazio -> `False` (ausência de medição não é "nenhum
    candidato venceu", é "nada foi medido ainda")."""
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
    max_workers: int | None = None,
) -> Path:
    """Ponto de entrada MANUAL — roda as `len(symbols) * len(timeframes)`
    combinações (15 por default) e persiste o relatório completo, atômico
    (B29). NÃO roda dentro da suíte automatizada (custo de IO + cálculo em
    15 combinações não paga a cada `pytest`).

    **Paralelo entre combinações, não dentro de uma combinação.** Cada
    (symbol, tf) é totalmente independente das outras 14 -- os 4
    candidatos atuais (Garman-Klass baseline + Parkinson/Rogers-Satchell/
    Yang-Zhang) são todos fórmula fechada (sem MLE/OLS por fold, muito
    mais baratos que o EGARCH/HAR-RV que rodavam aqui antes), mas o
    paralelismo entre combinações continua valendo a pena no volume de
    IO (15 × até 230k barras). `max_workers=None` usa `os.cpu_count()`
    (todos os núcleos disponíveis) -- explícito por padrão, não
    conservador. `ProcessPoolExecutor`, não threads.

    Chame manualmente:
    `uv run python -c "from src.analysis.volatility_comparison import run_and_save_volatility_comparison_report as r; r()"`
    ou `uv run python -m src.analysis.volatility_comparison`."""
    combos = [(symbol, tf) for symbol in symbols for tf in timeframes]
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    logger.info(
        "analysis.volatility_comparison.starting",
        n_combinations=len(combos),
        max_workers=workers,
    )

    t0 = time.perf_counter()
    results: list[CombinationResult] = []
    skipped: list[dict[str, str]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_to_combo = {
            executor.submit(run_volatility_comparison_for_symbol_tf, symbol, tf): (symbol, tf)
            for symbol, tf in combos
        }
        for future in as_completed(future_to_combo):
            symbol, tf = future_to_combo[future]
            result = future.result()
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
    # ProcessPoolExecutor.as_completed devolve em ordem de conclusão, não
    # de submissão -- ordena pra o relatório final ser determinístico
    # (mesmo conteúdo sempre na mesma posição, independente de qual
    # worker terminou primeiro).
    results.sort(key=lambda r: (r.symbol, r.tf))

    # Combinações puladas (dado insuficiente) não contam nem a favor nem
    # contra -- não são medição, são ausência de medição.
    no_candidate_beats_gk_anywhere = stopping_criterion_1_from_results(results)

    payload: dict[str, Any] = {
        **report_provenance(),
        "n_combinations_requested": len(symbols) * len(timeframes),
        "n_combinations_evaluated": len(results),
        "skipped": skipped,
        "elapsed_seconds_total": elapsed_s,
        "no_candidate_beats_gk_anywhere": no_candidate_beats_gk_anywhere,
        "combinations": [_combination_to_dict(r) for r in results],
    }
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info(
        "analysis.volatility_comparison.done",
        n_combinations_evaluated=len(results),
        n_skipped=len(skipped),
        elapsed_seconds_total=round(elapsed_s, 1),
        no_candidate_beats_gk_anywhere=no_candidate_beats_gk_anywhere,
        dest=str(dest),
    )
    return dest


if __name__ == "__main__":
    run_and_save_volatility_comparison_report()
