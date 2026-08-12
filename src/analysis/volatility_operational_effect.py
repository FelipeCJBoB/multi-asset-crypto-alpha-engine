"""M1 — efeito operacional de cada estimador de volatilidade sobre
`stop_pct`/`custo_atr`/janela viável (R1+R2), por ativo (PRD_V4_1.md §3.2,
linha 354: "Emitir também: efeito de cada estimador sobre `stop_pct`
mediano, sobre `custo_atr` e sobre a fração de barras dentro da janela
viável, por ativo"). Também serve o pedido da linha 356 ("refazer a
medição de ATR de 4 meses sobre a série completa com o estimador
vencedor") — a linha do vencedor (Garman-Klass) nesta mesma tabela É essa
remedição, sobre a série completa de cada ativo em vez da amostra de
conveniência de 4 meses do §0.2.

**Escopo: os 4 candidatos ATUAIS, não os 6 originais de M1.** ATRWilder/
HAR-RV/EGARCH(1,1)/RealizedVol já perderam decisivamente em QLIKE (métrica
primária declarada no PRD) e foram amputados do harness de comparação
(`volatility_comparison.py`, decisão do Manager 2026-08-11) — recalcular o
efeito operacional deles não muda nenhuma decisão pendente, e o código/
resultado deles continua recuperável no git (commit `2410bc1`) se precisar.
Este módulo usa `current_estimator_lineup()` (GK baseline + Parkinson +
Rogers-Satchell + Yang-Zhang).

**TF único: 15m.** §0.2 do PRD já é implicitamente 15m ("ATR 15m" no
cabeçalho da tabela) — é o `decision_tf` de produção (CLAUDE.md). Não
repete em M30/H1: o efeito operacional (stop_pct/custo_atr/viabilidade)
que interessa pra essa tabela é o da decisão real, não uma varredura de
TF (isso é M3, que consome o vencedor de M1 depois).

**Série completa por ativo, não os folds OOS do walk-forward.** Este não é
um teste de acurácia de forecast (isso já é `volatility_comparison.py`) —
é uma caracterização de como o estimador se comporta sobre o histórico
real inteiro. Mesma janela por símbolo de `SYMBOL_START_DATE`/`END_DATE`
(medida do disco, ver docstring de `volatility_comparison.py`).

**R1 (quantização) reusa `src.risk.sizing.compute_sizing` +
`src.risk.limits.control_09a_erro_quantizacao`/`control_09b_resolucao_
sizing` — os controles REAIS de produção, não uma reimplementação.** Mas
por volume (até ~230mil barras × 4 estimadores × 5 ativos), rodar
`compute_sizing` em `Decimal` puro por barra seria proibitivamente lento
pra um script exploratório — este módulo reimplementa a MESMA álgebra em
`numpy`/`float64` vetorizado (`_r1_vectorized`), com precisão de ponta
flutuante em vez de `Decimal`. Isso é aceitável para uma estatística
agregada (mediana/fração), nunca seria para uma ordem real (`sizing.py`
já documenta por que `Decimal` importa lá — divergência de 1 `step_size`
numa ordem individual é silenciosa e cara; aqui o erro de float é
desprezível diante do tamanho da amostra). `_r1_vectorized` é testado
contra `compute_sizing` bar-a-bar numa amostra pequena para confirmar que
as duas concordam antes de rodar a série inteira.

**R2 (custo/stop) não tem um `control_NN` dedicado em `src.risk.limits`**
(os 18 controles cobrem regime/sistema/kill-switch/sizing/margem/perdas/
liquidez — nenhum é "custo vs distância de stop" isolado). R2 é a
definição literal do PRD (§0.2): `custo_round_trip <= cost_stop_ratio_max
× stop_pct`, ou seja `(round_trip_cost_bps/10000) / stop_pct <=
cost_stop_ratio_max`. Reusa `group_e.round_trip_cost_bps` (mesma fórmula
de `E27f_cost_atr_ratio`), só troca o denominador de `atr_pct` bruto para
`stop_pct` (`= sl_atr_mult × atr_pct`).

**Gap de proveniência encontrado, não escondido:** `equity` em USD (US$
196,85, citado em CLAUDE.md a partir de `capital_inicial_brl=1000,00`
BRL, `constants.yaml`) NUNCA foi formalizado como constante própria —
não existe `equity_usd`/`usdbrl_reference_rate` em `constants.yaml`. Este
módulo usa `_EQUITY_USD_FALLBACK` (valor da prosa do CLAUDE.md,
comentado explicitamente como não-canônico) só porque `compute_sizing`
exige `equity` em USD e não há outra fonte -- reportado aqui como achado
de proveniência, não uma correção silenciosa: alguém devia decidir e
registrar `equity_usd`/a taxa de câmbio em `constants.yaml` (§16.10 Regra
Zero), este script não decide isso por conta própria."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.analysis.volatility_comparison import (
    END_DATE,
    SYMBOL_START_DATE,
    current_estimator_lineup,
)
from src.core.provenance import report_provenance
from src.data import lake
from src.exchange.filters import load_filters_asof
from src.features._constants import load_constant as load_feature_constant
from src.features.groups.group_e import round_trip_cost_bps
from src.features.volatility import Bars
from src.risk._constants import load_constant as load_risk_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "volatility_operational_effect_report.json"

DECISION_TF: Final[str] = "15m"
DECISION_TF_MINUTES: Final[int] = 15

# Ver "Gap de proveniência" na docstring do módulo -- NÃO é constants.yaml,
# é a prosa de CLAUDE.md ("capital de R$ 1.000 (US$ 196,85)"), sem taxa de
# câmbio nem `equity_usd` formalizados em nenhum lugar canônico do repo.
_EQUITY_USD_FALLBACK: Final[float] = 196.85


@dataclass(frozen=True, slots=True)
class OperationalEffectMetrics:
    """Resumo por (symbol, estimator) sobre a série completa em `decision_tf`."""

    symbol: str
    estimator_id: str
    n_bars: int
    n_valid: int
    estimator_pct_median: float
    stop_pct_median: float
    custo_atr_median: float
    r1_pass_fraction: float
    r2_pass_fraction: float
    janela_viavel_fraction: float


def _r1_vectorized(
    *,
    estimator_pct: FloatArray,
    mark_price: FloatArray,
    equity_usd: float,
    risk_per_trade: float,
    sl_atr_mult: float,
    step_size: float,
    quantization_tolerance: float,
    min_sizing_resolution_units: float,
) -> tuple[FloatArray, FloatArray]:
    """Mesma álgebra de `src.risk.sizing.compute_sizing` +
    `control_09a_erro_quantizacao`/`control_09b_resolucao_sizing`, em
    `float64` vetorizado -- ver docstring do módulo sobre por que não é
    `Decimal` aqui. Retorna `(quant_error, n_req_over_unit)`; NaN onde
    `estimator_pct`/`mark_price` são NaN ou `stop_pct` é zero (mesma
    disciplina de "nunca inventar zero" de `qlike_loss`/`bias`)."""
    stop_pct = sl_atr_mult * estimator_pct
    risk_usd = equity_usd * risk_per_trade
    with np.errstate(divide="ignore", invalid="ignore"):
        notional_req = np.where(stop_pct > 0, risk_usd / stop_pct, np.nan)
        qty_raw = notional_req / mark_price
    qty = np.floor(qty_raw / step_size) * step_size
    notional_real = qty * mark_price
    with np.errstate(divide="ignore", invalid="ignore"):
        quant_error = np.where(
            notional_req > 0, np.abs(notional_real - notional_req) / notional_req, np.nan
        )
        unit_notional = step_size * mark_price
        n_req_over_unit = np.where(unit_notional > 0, notional_req / unit_notional, np.nan)
    return quant_error, n_req_over_unit


def _r1_pass(quant_error: FloatArray, n_req_over_unit: FloatArray, *, tolerance: float, min_units: float) -> FloatArray:
    return (quant_error <= tolerance) & (n_req_over_unit >= min_units)


def compute_operational_effect_for_symbol(symbol: str) -> list[OperationalEffectMetrics]:
    """Núcleo puro de IO — carrega `bars` reais em `DECISION_TF` (história
    completa medida, `SYMBOL_START_DATE`/`END_DATE`) e computa as métricas
    de todos os estimadores do lineup atual para este símbolo."""
    window = int(load_feature_constant("atr_window"))
    bars_df = lake.query_bars(
        symbol, DECISION_TF, SYMBOL_START_DATE[symbol], END_DATE, source="klines_1m", cast_prices=True
    )
    bars = Bars(frame=bars_df, timeframe_minutes=DECISION_TF_MINUTES)
    mark_price = bars_df["close"].cast(pl.Float64).to_numpy()

    filters = load_filters_asof(END_DATE, symbol=symbol)
    step_size = float(filters.step_size)

    equity_usd = _EQUITY_USD_FALLBACK
    risk_per_trade = float(load_risk_constant("risk_per_trade"))
    sl_atr_mult = float(load_risk_constant("sl_atr_mult"))
    quantization_tolerance = float(load_risk_constant("quantization_tolerance"))
    min_sizing_resolution_units = float(load_risk_constant("min_sizing_resolution_units"))
    cost_stop_ratio_max = float(load_risk_constant("cost_stop_ratio_max"))
    maker_fee = float(load_risk_constant("maker_fee"))
    taker_fee = float(load_risk_constant("taker_fee"))
    cost_bps = round_trip_cost_bps(maker_fee, taker_fee)

    results: list[OperationalEffectMetrics] = []
    for estimator in current_estimator_lineup(window=window):
        estimator_pct = estimator.estimate(bars, horizon_minutes=DECISION_TF_MINUTES)
        stop_pct = sl_atr_mult * estimator_pct
        with np.errstate(divide="ignore", invalid="ignore"):
            custo_atr = cost_bps / (estimator_pct * 10000.0)
            r2_ratio = (cost_bps / 10000.0) / stop_pct

        quant_error, n_req_over_unit = _r1_vectorized(
            estimator_pct=estimator_pct,
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

        valid = np.isfinite(estimator_pct) & (estimator_pct > 0) & np.isfinite(r2_ratio) & np.isfinite(quant_error)
        n_valid = int(np.sum(valid))
        janela_viavel = r1_pass & r2_pass & valid

        results.append(
            OperationalEffectMetrics(
                symbol=symbol,
                estimator_id=estimator.estimator_id,
                n_bars=bars_df.height,
                n_valid=n_valid,
                estimator_pct_median=float(np.median(estimator_pct[valid])) if n_valid else float("nan"),
                stop_pct_median=float(np.median(stop_pct[valid])) if n_valid else float("nan"),
                custo_atr_median=float(np.median(custo_atr[valid])) if n_valid else float("nan"),
                r1_pass_fraction=float(np.mean(r1_pass[valid])) if n_valid else float("nan"),
                r2_pass_fraction=float(np.mean(r2_pass[valid])) if n_valid else float("nan"),
                janela_viavel_fraction=float(np.sum(janela_viavel) / n_valid) if n_valid else float("nan"),
            )
        )
        logger.info(
            "analysis.volatility_operational_effect.estimator_done",
            symbol=symbol,
            estimator_id=estimator.estimator_id,
            stop_pct_median=round(results[-1].stop_pct_median, 6),
            janela_viavel_fraction=round(results[-1].janela_viavel_fraction, 4),
        )
    return results


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão de `volatility_comparison._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("analysis.volatility_operational_effect.report_written", path=str(dest_path))


def run_and_save_operational_effect_report(
    *,
    symbols: tuple[str, ...] = tuple(SYMBOL_START_DATE),
    dest_path: Path | None = None,
    max_workers: int | None = None,
) -> Path:
    """Ponto de entrada MANUAL -- roda os 5 ativos (paralelo entre
    símbolos, cada um independente) e persiste o relatório, atômico (B29).

    Chame manualmente:
    `uv run python -c "from src.analysis.volatility_operational_effect import run_and_save_operational_effect_report as r; r()"`
    ou `uv run python -m src.analysis.volatility_operational_effect`."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    logger.info(
        "analysis.volatility_operational_effect.starting", n_symbols=len(symbols), max_workers=workers
    )

    results_by_symbol: dict[str, list[OperationalEffectMetrics]] = {}
    with ProcessPoolExecutor(max_workers=min(workers, len(symbols))) as executor:
        future_to_symbol = {
            executor.submit(compute_operational_effect_for_symbol, symbol): symbol for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            results_by_symbol[symbol] = future.result()

    payload: dict[str, Any] = {
        **report_provenance(),
        "decision_tf": DECISION_TF,
        "equity_usd_source": "CLAUDE.md prosa -- NAO e constants.yaml, ver docstring do modulo",
        "equity_usd": _EQUITY_USD_FALLBACK,
        "symbols": {
            symbol: [asdict(m) for m in sorted(metrics, key=lambda m: m.estimator_id)]
            for symbol, metrics in sorted(results_by_symbol.items())
        },
    }
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info("analysis.volatility_operational_effect.done", n_symbols=len(results_by_symbol), dest=str(dest))
    return dest


if __name__ == "__main__":
    run_and_save_operational_effect_report()
