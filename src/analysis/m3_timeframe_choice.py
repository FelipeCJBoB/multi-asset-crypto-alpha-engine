"""M3 — escolha de timeframe (PRD_V4_1.md §3.2, linhas 390-394): "Refazer o
§0.5 do V3.2 com ATR da série completa e o estimador vencedor de M1, por
ativo. Avaliar M15/M30/H1 contra R1 (quantização), R2 (custo), R3
(orçamento)." Zero trials — é medição, não busca.

**Reusa a infraestrutura de M1 (`volatility_operational_effect.py`),
generalizada de TF único (15m) para os 3 TFs de `TIMEFRAMES`
(`volatility_comparison.py`).** `lake.query_bars`/`GarmanKlassEstimator`
já são agnósticos de TF (confirmado antes de escrever este módulo —
`volatility_comparison.py` já roda as 15 combinações reais pra QLIKE); o
único ponto hardcoded em 15m era o RUNNER de `volatility_operational_
effect.py` (`DECISION_TF`), não a infra por baixo — por isso este módulo
não toca naquele (M1 já fechou, artefato congelado), só reusa as mesmas
peças (`_r1_vectorized`/`_r1_pass`, já testados contra `compute_sizing`
de produção em `test_analysis_volatility_operational_effect.py`) num
runner novo, tf-parametrizado.

**Primeiro caller real de `feasibility.breakeven_win_rate`/
`trades_per_year_budget` (R3)** — existiam desde 2026-08-12 (achado do
PRD_V4_1.md §0.2) mas nenhum runner as chamava ainda; M3 é exatamente o
"orçamento" (R3) que o PRD pede, então é o lugar certo pra conectá-las.

**Só `GarmanKlassEstimator` — o vencedor único de M1, não o lineup
inteiro.** M2/M3 não repetem a comparação entre estimadores (isso já
fechou); M3 avalia timeframe SOB o estimador já escolhido.

**`atr_window` (20 barras) idêntico nos 3 TFs — I2 (PRD §2.7) continua
não resolvido, mesma ressalva já documentada em `volatility_comparison.py`
(20 barras em M15/M30/H1 são 3 janelas de relógio diferentes: 5h/10h/
20h). Não é um erro novo introduzido aqui, é a mesma limitação conhecida
herdada."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog

from src.analysis.feasibility import breakeven_win_rate as compute_breakeven_win_rate
from src.analysis.feasibility import trades_per_year_budget as compute_trades_per_year_budget
from src.analysis.volatility_comparison import END_DATE, SYMBOL_START_DATE, TIMEFRAMES
from src.analysis.volatility_operational_effect import _r1_pass, _r1_vectorized
from src.core.provenance import report_provenance
from src.data import lake
from src.exchange.filters import load_filters_asof
from src.features._constants import load_constant as load_feature_constant
from src.features.groups.group_e import round_trip_cost_bps
from src.features.volatility import Bars, GarmanKlassEstimator
from src.risk._constants import load_constant as load_risk_constant

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "m3_timeframe_choice_report.json"

# Minutos por TF nomeado -- mesma duplicação local já usada em
# `volatility_comparison.py:404` (definição de calendário, não
# hiperparâmetro; ver `src.data.resample._TIMEFRAME_MINUTES` pra fonte
# canônica). Testado contra ela em `test_analysis_m3_timeframe_choice.py`
# pra impedir divergência silenciosa entre as duas cópias.
_TF_TO_MINUTES: Final[dict[str, int]] = {"15m": 15, "30m": 30, "1h": 60}

# Mesmo gap de proveniência de `volatility_operational_effect.py` -- ver
# docstring daquele módulo. Não formalizado em `constants.yaml` ainda.
_EQUITY_USD_FALLBACK: Final[float] = 196.85


@dataclass(frozen=True, slots=True)
class TimeframeChoiceMetrics:
    """Resumo por (symbol, tf) sobre a série completa do símbolo, com
    Garman-Klass (vencedor de M1)."""

    symbol: str
    tf: str
    n_bars: int
    n_valid: int
    atr_pct_p25: float
    atr_pct_median: float
    atr_pct_p75: float
    stop_pct_median: float
    custo_atr_median: float
    r1_pass_fraction: float
    r2_pass_fraction: float
    janela_viavel_fraction: float
    breakeven_win_rate: float
    trades_per_year_budget: float


def compute_timeframe_choice_for_symbol(symbol: str) -> list[TimeframeChoiceMetrics]:
    """Núcleo puro de IO -- carrega `bars` reais em cada TF de `TIMEFRAMES`
    (história completa medida, `SYMBOL_START_DATE`/`END_DATE` de
    `volatility_comparison.py`) e computa R1/R2/R3 com Garman-Klass."""
    window = int(load_feature_constant("atr_window"))
    estimator = GarmanKlassEstimator(window=window)

    equity_usd = _EQUITY_USD_FALLBACK
    risk_per_trade = float(load_risk_constant("risk_per_trade"))
    tp_atr_mult = float(load_risk_constant("tp_atr_mult"))
    sl_atr_mult = float(load_risk_constant("sl_atr_mult"))
    quantization_tolerance = float(load_risk_constant("quantization_tolerance"))
    min_sizing_resolution_units = float(load_risk_constant("min_sizing_resolution_units"))
    cost_stop_ratio_max = float(load_risk_constant("cost_stop_ratio_max"))
    maker_fee = float(load_risk_constant("maker_fee"))
    taker_fee = float(load_risk_constant("taker_fee"))
    fee_budget_monthly = float(load_risk_constant("fee_budget_monthly"))
    cost_bps = round_trip_cost_bps(maker_fee, taker_fee)

    # Mesma convenção de `volatility_operational_effect.py` -- filtro
    # VIGENTE (não point-in-time), caracterização "com a economia de
    # hoje", não backtest.
    filters = load_filters_asof(date.today(), symbol=symbol)
    step_size = float(filters.step_size)

    results: list[TimeframeChoiceMetrics] = []
    for tf in TIMEFRAMES:
        tf_minutes = _TF_TO_MINUTES[tf]
        bars_df = lake.query_bars(
            symbol, tf, SYMBOL_START_DATE[symbol], END_DATE, source="klines_1m", cast_prices=True
        )
        bars = Bars(frame=bars_df, timeframe_minutes=tf_minutes)
        mark_price = bars_df["close"].cast(pl.Float64).to_numpy()

        atr_pct = estimator.estimate(bars, horizon_minutes=tf_minutes)
        stop_pct = sl_atr_mult * atr_pct
        # atr_pct e' desvio-padrao (>=0 por construcao, GK/sqrt); 0/NaN so'
        # no warmup, propaga NaN/Inf e e' removido pelo filtro `valid`
        # abaixo antes de qualquer uso -- estruturalmente seguro.
        with np.errstate(divide="ignore", invalid="ignore"):
            custo_atr_arr = cost_bps / (atr_pct * 10000.0)  # noqa: unguarded-ratio
            r2_ratio = (cost_bps / 10000.0) / stop_pct  # noqa: unguarded-ratio

        quant_error, n_req_over_unit = _r1_vectorized(
            estimator_pct=atr_pct,
            mark_price=mark_price,
            equity_usd=equity_usd,
            risk_per_trade=risk_per_trade,
            sl_atr_mult=sl_atr_mult,
            step_size=step_size,
            quantization_tolerance=quantization_tolerance,
            min_sizing_resolution_units=min_sizing_resolution_units,
        )
        r1_pass = _r1_pass(
            quant_error,
            n_req_over_unit,
            tolerance=quantization_tolerance,
            min_units=min_sizing_resolution_units,
        )
        r2_pass = r2_ratio <= cost_stop_ratio_max

        valid = (
            np.isfinite(atr_pct) & (atr_pct > 0) & np.isfinite(r2_ratio) & np.isfinite(quant_error)
        )
        n_valid = int(np.sum(valid))
        janela_viavel = r1_pass & r2_pass & valid
        # n_valid>0 garantido pelo `if n_valid` -- guarda de sinal na mesma
        # expressão, o script estático so' não reconhece o ternário.
        janela_viavel_fraction = (
            float(np.sum(janela_viavel) / n_valid) if n_valid else float("nan")  # noqa: unguarded-ratio
        )

        atr_pct_median = float(np.median(atr_pct[valid])) if n_valid else float("nan")
        custo_atr_median = float(np.median(custo_atr_arr[valid])) if n_valid else float("nan")

        breakeven_wr = (
            compute_breakeven_win_rate(
                atr_pct=atr_pct_median,
                tp_atr_mult=tp_atr_mult,
                sl_atr_mult=sl_atr_mult,
                maker_fee=maker_fee,
                taker_fee=taker_fee,
            )
            if n_valid
            else float("nan")
        )
        trades_year = (
            compute_trades_per_year_budget(
                custo_atr=custo_atr_median,
                sl_atr_mult=sl_atr_mult,
                fee_budget_monthly=fee_budget_monthly,
                risk_per_trade=risk_per_trade,
            )
            if n_valid
            else float("nan")
        )

        results.append(
            TimeframeChoiceMetrics(
                symbol=symbol,
                tf=tf,
                n_bars=bars_df.height,
                n_valid=n_valid,
                atr_pct_p25=float(np.percentile(atr_pct[valid], 25)) if n_valid else float("nan"),
                atr_pct_median=atr_pct_median,
                atr_pct_p75=float(np.percentile(atr_pct[valid], 75)) if n_valid else float("nan"),
                stop_pct_median=float(np.median(stop_pct[valid])) if n_valid else float("nan"),
                custo_atr_median=custo_atr_median,
                r1_pass_fraction=float(np.mean(r1_pass[valid])) if n_valid else float("nan"),
                r2_pass_fraction=float(np.mean(r2_pass[valid])) if n_valid else float("nan"),
                janela_viavel_fraction=janela_viavel_fraction,
                breakeven_win_rate=breakeven_wr,
                trades_per_year_budget=trades_year,
            )
        )
        logger.info(
            "analysis.m3_timeframe_choice.tf_done",
            symbol=symbol,
            tf=tf,
            atr_pct_median=round(results[-1].atr_pct_median, 6),
            janela_viavel_fraction=round(results[-1].janela_viavel_fraction, 4),
        )
    return results


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão de `volatility_operational_effect._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("analysis.m3_timeframe_choice.report_written", path=str(dest_path))


def run_and_save_timeframe_choice_report(
    *,
    symbols: tuple[str, ...] = tuple(SYMBOL_START_DATE),
    dest_path: Path | None = None,
    max_workers: int | None = None,
) -> Path:
    """Ponto de entrada MANUAL -- roda os 5 ativos (paralelo entre
    símbolos) e persiste o relatório, atômico (B29).

    Chame manualmente: `uv run python -m src.analysis.m3_timeframe_choice`."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    logger.info(
        "analysis.m3_timeframe_choice.starting", n_symbols=len(symbols), max_workers=workers
    )

    results_by_symbol: dict[str, list[TimeframeChoiceMetrics]] = {}
    with ProcessPoolExecutor(max_workers=min(workers, len(symbols))) as executor:
        future_to_symbol = {
            executor.submit(compute_timeframe_choice_for_symbol, symbol): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            results_by_symbol[symbol] = future.result()

    payload: dict[str, Any] = {
        **report_provenance(),
        "timeframes": list(TIMEFRAMES),
        "equity_usd_source": "CLAUDE.md prosa -- NAO e constants.yaml, ver docstring do modulo",
        "equity_usd": _EQUITY_USD_FALLBACK,
        "symbols": {
            symbol: [asdict(m) for m in sorted(metrics, key=lambda m: TIMEFRAMES.index(m.tf))]
            for symbol, metrics in sorted(results_by_symbol.items())
        },
    }
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info(
        "analysis.m3_timeframe_choice.done", n_symbols=len(results_by_symbol), dest=str(dest)
    )
    return dest


if __name__ == "__main__":
    run_and_save_timeframe_choice_report()
