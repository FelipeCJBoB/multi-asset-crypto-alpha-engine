"""AG-008 (`audit/architecture_gaps_log.yaml`) — medição shadow-mode do
deslocamento de `econ_regime` se `ATRWilderEstimator` (legado, ainda o
único caminho em `features/build.py`/`group_c.py`) for trocado por
`GarmanKlassEstimator` (M1, vencedor travado em `constants.yaml`, mas hoje
só consumido por `labels/triple_barrier.py`).

**Por que este módulo existe e o que ele NÃO faz.** A investigação de
AG-008 (2026-08-13) achou uma lacuna real: o M1 mede QLIKE — qualidade da
PREVISÃO de variância do próximo bar — não a diferença de NÍVEL entre os
dois estimadores calculados sobre o MESMO bar `t`. `econ_regime`
(`src.regime.classifier::_economics_regime`) usa o NÍVEL de
`cost_atr_ratio` (E27f), rankeado em percentil expansivo e cortado em
tercis — dois estimadores podem discordar em nível mesmo prevendo
igualmente bem o próximo bar. Esta lacuna motivou este módulo. Ele mede,
não promove: **não escreve em `config/constants.yaml`, não regrava
`labels/`/`features/` de produção, não retreina nenhum modelo.** Por essa
razão não consome `audit/n_lifetime.yaml` — mesma categoria de
"pesquisa/decisão de desenho" já usada pela extensão RS/YZ pós-M1
(`volatility_comparison.py`), que também rodou sem gastar um trial. A
decisão de PROMOÇÃO (reprocessar `labels/`+`features/`, retreinar os 5
modelos já em disco) continua represada até M2/M3 (tipo de barra/
timeframe, PRD_V4_1.md §3.2) fecharem — decisão já registrada em
`docs/refactor_gk_canonico.md`, não revista aqui.

**O que é medido, e por quê exatamente isso.** Para cada símbolo, calcula
`ATRWilderEstimator`/`GarmanKlassEstimator` sobre a MESMA série de barras
em `DECISION_TF` (15m, único TF de produção hoje), aplica o pipeline REAL
de `econ_regime` — `e27f_cost_atr_ratio` (`src.features.groups.group_e`)
→ `expanding_percentile_rank_strict` (`src.features.support`) →
`_economics_regime` (`src.regime.classifier`) — separadamente para cada
estimador (não força os dois lados a compartilhar um único ranking; é
exatamente o que `classify_regimes` faria de verdade se GK virasse
produção), e mede três coisas:

1. **`median_abs_relative_diff`** — a lacuna que faltava: diferença
   relativa de NÍVEL entre `GK` e `ATRWilder` no mesmo bar, nunca medida
   antes (nem pelo M1 original, nem pela extensão RS/YZ — os dois
   avaliaram previsão, não nível).
2. **`fraction_econ_regime_changed`** — fração de barras (onde os dois
   lados são computáveis) em que a classificação `FAVORABLE/NEUTRAL/
   HOSTILE` muda entre os dois estimadores.
3. **`adjusted_rand_index`** (`sklearn.metrics.adjusted_rand_score`,
   `>=1.5` já é dependência do projeto, mesmo pacote de
   `models/alpha.py`/`models/baselines.py`) — mesmo instrumento que
   PRD_V4_1.md §4.5 já propõe para decidir se "regime derivado do BTC" é
   equivalente ao regime próprio de cada ativo ("a medição decide");
   reaplicado aqui pra decidir se o estimador de ATR muda a classificação
   de `econ_regime` de forma substancial (ARI perto de 1) ou desprezível
   (ARI baixo).

`R2-R5`/`trend_state`/`vol_state` (as duas dimensões *core* de regime,
`efficiency_ratio`/`realized_vol` de retorno) **não são afetadas** por
esta troca — confirmado por leitura de `regime/classifier.py`, nenhuma
usa ATR/GK. Só `econ_regime` (eixo separado, §4.3.1) depende de
`cost_atr_ratio`.

**TF único: 15m**, mesmo racional de `volatility_operational_effect.py`
— é o `decision_tf` de produção hoje, não uma varredura de TF (isso é
M3)."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import structlog
from numpy.typing import NDArray
from sklearn.metrics import adjusted_rand_score

from src.analysis.volatility_comparison import END_DATE, SYMBOL_START_DATE
from src.core.provenance import report_provenance
from src.data import lake
from src.data._constants import load_constant as load_data_constant
from src.features._constants import load_constant as load_feature_constant
from src.features.groups.group_e import e27f_cost_atr_ratio
from src.features.support import expanding_percentile_rank_strict
from src.features.volatility import ATRWilderEstimator, Bars, GarmanKlassEstimator
from src.regime.classifier import _economics_regime
from src.risk._constants import load_constant as load_risk_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "gk_vs_wilder_econ_regime_shift_report.json"

DECISION_TF: Final[str] = "15m"
DECISION_TF_MINUTES: Final[int] = 15

_ECON_REGIME_LABELS: Final[tuple[str, ...]] = (
    "ECONOMICS_FAVORABLE",
    "ECONOMICS_NEUTRAL",
    "ECONOMICS_HOSTILE",
)


@dataclass(frozen=True, slots=True)
class EconRegimeShiftMetrics:
    """Resultado de UM símbolo — ver docstring do módulo pro que cada
    campo mede e por quê."""

    symbol: str
    n_bars: int
    n_valid_both: int
    median_abs_relative_diff: float
    fraction_econ_regime_changed: float
    adjusted_rand_index: float
    counts_wilder: dict[str, int]
    counts_gk: dict[str, int]


def _econ_regime_shift_metrics(
    symbol: str,
    atr_pct_wilder: FloatArray,
    atr_pct_gk: FloatArray,
    *,
    maker_fee: float,
    taker_fee: float,
) -> EconRegimeShiftMetrics:
    """Núcleo puro (sem IO) — dados dois vetores de ATR% já calculados
    sobre a MESMA série de barras (Wilder vs GK), reproduz o pipeline real
    de `econ_regime` separadamente para cada um e mede a divergência.
    Testado isoladamente (`tests/unit/test_analysis_gk_vs_wilder_econ_
    regime_shift.py`) com séries sintéticas pequenas, sem precisar de
    dado real."""
    n = atr_pct_wilder.shape[0]
    if atr_pct_gk.shape[0] != n:
        raise ValueError(
            f"atr_pct_wilder (n={n}) e atr_pct_gk (n={atr_pct_gk.shape[0]}) precisam "
            "ser a mesma série de barras"
        )

    cost_ratio_wilder = e27f_cost_atr_ratio(atr_pct_wilder, maker_fee, taker_fee)
    cost_ratio_gk = e27f_cost_atr_ratio(atr_pct_gk, maker_fee, taker_fee)

    econ_quantile_wilder = expanding_percentile_rank_strict(cost_ratio_wilder)
    econ_quantile_gk = expanding_percentile_rank_strict(cost_ratio_gk)

    econ_regime_wilder = _economics_regime(econ_quantile_wilder)
    econ_regime_gk = _economics_regime(econ_quantile_gk)

    # "válido nos dois lados" -- UNKNOWN é NaN de warmup do RANKING
    # expansivo (não do ATR em si), não conta como divergência real de
    # classificação -- mesmo racional de `valid`/`janela_viavel` em
    # `volatility_operational_effect.py`.
    valid = (econ_regime_wilder != "ECONOMICS_UNKNOWN") & (econ_regime_gk != "ECONOMICS_UNKNOWN")
    n_valid = int(np.sum(valid))

    # atr_pct_wilder=0 exigiria open=high=low=close idênticos em toda a
    # janela (dado real nunca observado); NaN de warmup e o eventual
    # +-inf de denominador zero são removidos pelo filtro np.isfinite
    # logo abaixo, nunca entram no median_abs_relative_diff reportado.
    with np.errstate(divide="ignore", invalid="ignore"):
        rel_diff = np.abs(atr_pct_gk - atr_pct_wilder) / atr_pct_wilder  # noqa: unguarded-ratio -- filtrado por np.isfinite abaixo
    rel_diff_valid = rel_diff[valid & np.isfinite(rel_diff)]

    changed = econ_regime_wilder[valid] != econ_regime_gk[valid]
    ari = (
        float(adjusted_rand_score(econ_regime_wilder[valid], econ_regime_gk[valid]))
        if n_valid
        else float("nan")
    )

    counts_wilder = {
        label: int(np.sum(econ_regime_wilder[valid] == label)) for label in _ECON_REGIME_LABELS
    }
    counts_gk = {
        label: int(np.sum(econ_regime_gk[valid] == label)) for label in _ECON_REGIME_LABELS
    }

    return EconRegimeShiftMetrics(
        symbol=symbol,
        n_bars=n,
        n_valid_both=n_valid,
        median_abs_relative_diff=(
            float(np.median(rel_diff_valid)) if rel_diff_valid.size else float("nan")
        ),
        fraction_econ_regime_changed=(float(np.mean(changed)) if n_valid else float("nan")),
        adjusted_rand_index=ari,
        counts_wilder=counts_wilder,
        counts_gk=counts_gk,
    )


# ============================================================================
# Ponto de entrada com IO — um símbolo, ou os 5
# ============================================================================


def compute_econ_regime_shift_for_symbol(symbol: str) -> EconRegimeShiftMetrics:
    """Carrega `bars` reais em `DECISION_TF` (história completa medida,
    `SYMBOL_START_DATE`/`END_DATE` de `volatility_comparison.py`) e roda
    os dois estimadores sobre a MESMA série."""
    window = int(load_feature_constant("atr_window"))
    maker_fee = float(load_risk_constant("maker_fee"))
    taker_fee = float(load_risk_constant("taker_fee"))

    # achado de auditoria 2026-08-15 (project_assurance): mesmo gap
    # estrutural de m2_bar_comparison.py (DuckDB sem SET memory_limit/
    # threads sob ProcessPoolExecutor concorrente) -- ver
    # constants.yaml::gk_vs_wilder_duckdb_memory_limit_gb.
    throttle = lake.DuckDBThrottle(
        memory_limit_gb=float(load_data_constant("gk_vs_wilder_duckdb_memory_limit_gb")),
        threads=int(load_data_constant("gk_vs_wilder_duckdb_threads")),
    )
    bars_df = lake.query_bars(
        symbol,
        DECISION_TF,
        SYMBOL_START_DATE[symbol],
        END_DATE,
        source="klines_1m",
        cast_prices=True,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    bars = Bars(frame=bars_df, timeframe_minutes=DECISION_TF_MINUTES)

    wilder = ATRWilderEstimator(window=window)
    gk = GarmanKlassEstimator(window=window)
    atr_pct_wilder = wilder.estimate(bars, horizon_minutes=DECISION_TF_MINUTES)
    atr_pct_gk = gk.estimate(bars, horizon_minutes=DECISION_TF_MINUTES)

    metrics = _econ_regime_shift_metrics(
        symbol, atr_pct_wilder, atr_pct_gk, maker_fee=maker_fee, taker_fee=taker_fee
    )
    logger.info(
        "analysis.gk_vs_wilder_econ_regime_shift.symbol_done",
        symbol=symbol,
        n_bars=metrics.n_bars,
        n_valid_both=metrics.n_valid_both,
        median_abs_relative_diff=round(metrics.median_abs_relative_diff, 4),
        fraction_econ_regime_changed=round(metrics.fraction_econ_regime_changed, 4),
        adjusted_rand_index=round(metrics.adjusted_rand_index, 4),
    )
    return metrics


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 — mesmo padrão de `volatility_comparison._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info(
        "analysis.gk_vs_wilder_econ_regime_shift.report_written", path=str(dest_path)
    )


def run_and_save_econ_regime_shift_report(
    *,
    symbols: tuple[str, ...] = tuple(SYMBOL_START_DATE),
    dest_path: Path | None = None,
    max_workers: int | None = None,
) -> Path:
    """Ponto de entrada MANUAL — roda os 5 ativos (paralelo entre
    símbolos, cada um independente) e persiste o relatório, atômico
    (B29). Ver docstring do módulo: isto é medição pura (shadow mode,
    AG-008), não escreve `constants.yaml`, não regrava `labels/`/
    `features/` de produção, não retreina nada, não consome
    `N_lifetime`.

    Chame manualmente:
    `uv run python -m src.analysis.gk_vs_wilder_econ_regime_shift`
    ou `uv run python -c "from src.analysis.gk_vs_wilder_econ_regime_shift
    import run_and_save_econ_regime_shift_report as r; r()"`."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    logger.info(
        "analysis.gk_vs_wilder_econ_regime_shift.starting",
        n_symbols=len(symbols),
        max_workers=workers,
    )

    results: dict[str, EconRegimeShiftMetrics] = {}
    failed_tasks: list[str] = []
    with ProcessPoolExecutor(max_workers=min(workers, len(symbols))) as executor:
        future_to_symbol = {
            executor.submit(compute_econ_regime_shift_for_symbol, symbol): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            # AG-019: future.result() isolado em try/except -- 1 símbolo
            # falhando não pode derrubar os outros já concluídos com
            # sucesso (ver m2_bar_comparison.run_and_save_bar_comparison_report).
            try:
                results[symbol] = future.result()
            except Exception as exc:
                failed_tasks.append(symbol)
                logger.error(
                    "analysis.gk_vs_wilder_econ_regime_shift.task_failed",
                    symbol=symbol,
                    error=repr(exc),
                )

    if failed_tasks:
        logger.warning(
            "analysis.gk_vs_wilder_econ_regime_shift.tasks_failed",
            n_failed=len(failed_tasks),
            n_symbols=len(symbols),
            failed=failed_tasks,
        )

    payload: dict[str, Any] = {
        **report_provenance(),
        "decision_tf": DECISION_TF,
        "purpose": (
            "AG-008 shadow-mode: mede o deslocamento de econ_regime (tercil "
            "expansivo de cost_atr_ratio) se ATRWilder for trocado por "
            "Garman-Klass em features/build.py -- medicao pura, nao promove "
            "nada em producao, nao consome N_lifetime."
        ),
        "failed_symbols": failed_tasks,
        "symbols": {symbol: asdict(m) for symbol, m in sorted(results.items())},
    }
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info(
        "analysis.gk_vs_wilder_econ_regime_shift.done",
        n_symbols=len(results),
        n_failed=len(failed_tasks),
        dest=str(dest),
    )
    return dest


if __name__ == "__main__":
    run_and_save_econ_regime_shift_report()
