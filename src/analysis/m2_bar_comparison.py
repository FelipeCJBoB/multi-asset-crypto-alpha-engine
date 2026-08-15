"""M2 — comparação de tipo de barra (PRD_V4_1.md §3.2, linhas 382-388):
"Candidatos: tempo (baseline) · dollar bars · volume bars · tick imbalance
bars, calibradas para a mesma frequência média. Métricas: Jarque-Bera ·
curtose · Ljung-Box em `r` e `r²` · ADF · razão de amostra efetiva
(unicidade média com `time_stop` equivalente em relógio)." Zero trials —
medição, não busca.

**Hipótese testável, não assumida (nota multi-ativo do PRD):** dollar bars
normalizam por atividade — com volume variando 3.700x entre os 5 ativos
(I1), podem tornar os cinco mais comparáveis que barras de tempo. Este
módulo MEDE se isso é verdade (JB/curtose/Ljung-Box mais "bem
comportados", i.e. mais perto de ruído branco gaussiano, em dollar bars
do que em barras de tempo, consistentemente nos 5 ativos) — não presume.

**A partir de `aggTrades`, não de `klines_1m`.** `klines_1m` já É uma
agregação temporal — usar klines pra medir "a barra de tempo é pior que
outra coisa" seria circular (o próprio dado de entrada já tem a
propriedade sendo testada). `src.data.bars` constrói as 3 barras
alternativas trade-a-trade real; o baseline usa `lake.query_bars` (mesma
fonte de M1/M3) pra ficar consistente com o resto da Camada 1.

**Calibração — mesma frequência média que o baseline, medida não
suposta.** `target_n_bars` = nº de barras de 15m do baseline no mesmo
período; `threshold` de dollar/volume bars = volume total (em $ ou
unidades) dividido por `target_n_bars`; `exp_num_ticks_init` de tick
imbalance bars = nº total de ticks dividido por `target_n_bars` (mesma
lógica: barra "típica" do TIB deveria consumir, em média, tantos ticks
quantos a barra de 15m consome em relógio).

**"Razão de amostra efetiva" reusa `src.labels.weights.
compute_concurrency_and_uniqueness`** (produção real, testada, mesma
função que calcula `sample_weight` do Label Engine) — não uma
reimplementação. `t0` = `close_time` de cada barra, `t1` = `close_time +
time_stop_bars×15min` (mesmo horizonte de `time_stop_bars`,
`constants.yaml`, convertido pra relógio) — "unicidade média com
time_stop equivalente em relógio", literal do PRD. Import de
`src.labels` a partir de `src.analysis` NÃO viola a hierarquia de camadas
(`pyproject.toml::[tool.importlinter]`, contrato "labels só é lido por
models, validation, backtest" lista só `exchange/data/features/regime/
risk/execution/live/monitoring` como proibidos — `analysis` fica de fora
deliberadamente, mesmo padrão já usado em `m6_common_factor_hypothesis.py`).

**Performance — granularidade de paralelismo é por (symbol, bar_type), não
por symbol.** `tick_imbalance_bars` é sequencial (ver docstring de
`src.data.bars`), single-thread, e é o item mais lento da Camada 1 até
agora — com só 5 símbolos, paralelizar por símbolo (1 task cada) usa no
máximo 5 núcleos, não importa quantos existam. `run_and_save_bar_
comparison_report` fatia o trabalho em `len(symbols) × len(BAR_TYPES)`
tasks independentes (até 20, com os 5 ativos), cada uma um processo do
`ProcessPoolExecutor` dimensionado por `os.cpu_count()` — usa os núcleos
disponíveis de verdade, não só 5. Custo aceito conscientemente: cada task
de `dollar`/`volume`/`tick_imbalance` recarrega `aggTrades` do disco de
forma independente (`lake.query_agg_trades`, sem cache entre tasks) em
vez de reusar um `DataFrame` já carregado — serializar um `DataFrame` de
milhões de linhas entre processos custaria mais que reler do parquet, e a
E/S de disco é pequena perto do loop Python de `tick_imbalance_bars`
mesmo assim. Ponto de entrada manual, não é testado de ponta a ponta no
pytest (mesma convenção de M1/M3/M6 — IO real fica fora da suíte
automatizada)."""

from __future__ import annotations

import os

# Oversubscription de threads BLAS/polars -- ProcessPoolExecutor já
# paraleliza no nível de PROCESSO (até `os.cpu_count()` workers, ver
# `run_and_save_bar_comparison_report`). Sem isso, cada um dos N processos
# TAMBÉM deixa numpy/scipy/statsmodels (BLAS) e polars abrirem seu próprio
# pool de threads interno -- N processos x M threads cada competem pelos
# mesmos N núcleos. Causa raiz confirmada na prática (não hipotética): rodar
# `run_and_save_bar_comparison_report` com `max_workers=12` produziu
# `numpy._core._exceptions._ArrayMemoryError` dentro de `statsmodels.
# adfuller`/`_autolag` (2026-08-15) -- contenção de alocação sob 12
# processos concorrentes cada um multi-thread, não falta de memória real
# (o array que falhou tinha 36 MiB, trivial pra qualquer máquina com RAM
# disponível). Precisa ser setado ANTES de importar numpy/polars/scipy/
# statsmodels -- no Windows (spawn, não fork) cada worker do pool
# reexecuta o módulo inteiro do zero, então isso vale em CADA processo,
# não só no principal.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("POLARS_MAX_THREADS", "1")

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy import stats as scipy_stats
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import adfuller

from src.analysis.volatility_comparison import END_DATE, SYMBOL_START_DATE
from src.core.provenance import report_provenance
from src.data import lake
from src.data._constants import load_constant as load_data_constant
from src.data.bars import TickImbalanceBarsConfig, dollar_bars, tick_imbalance_bars, volume_bars
from src.data.resample import step_ms
from src.labels.weights import compute_concurrency_and_uniqueness
from src.risk._constants import load_constant as load_risk_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "m2_bar_comparison_report.json"

BASELINE_TF: Final[str] = "15m"
BAR_TYPES: Final[tuple[str, ...]] = ("time", "dollar", "volume", "tick_imbalance")

# Ljung-Box/ADF exigem amostra bem maior que o número de lags -- 4x é uma
# folga de engenharia (não domínio), evita crash de statsmodels em barras
# degeneradas sem inventar mais uma constante de constants.yaml.
_MIN_OBS_FOR_TESTS_MULTIPLIER: Final[int] = 4


@dataclass(frozen=True, slots=True)
class BarComparisonMetrics:
    """Resumo por (symbol, bar_type) -- `NaN` explícito onde a amostra é
    pequena demais pros testes (nunca um zero fabricado)."""

    symbol: str
    bar_type: str
    n_bars: int
    n_returns: int
    jarque_bera_stat: float
    jarque_bera_pvalue: float
    kurtosis_excess: float
    ljung_box_r_pvalue: float
    ljung_box_r2_pvalue: float
    adf_stat: float
    adf_pvalue: float
    avg_uniqueness: float


def _log_returns(close: FloatArray) -> FloatArray:
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(close))
    return r


def _run_adfuller(
    symbol: str, bar_type: str, r: FloatArray, *, maxlag: int
) -> tuple[float, float]:
    """ADF sobre `r`, com duas correções sobre `adfuller(r, autolag="AIC")`
    ingênuo -- achado real de auditoria (`audit_engineering`, 2026-08-15,
    pesquisa web antes de codar, não hipótese):

    1. **`autolag=None` (lag FIXO em `maxlag`, não busca 1..maxlag').**
       `adfuller(autolag="AIC")` sem `maxlag` explícito usa o default
       `12*(nobs/100)^0.25` -- para `nobs≈164 mil` (o tamanho típico de
       barra de 15m dos 5 ativos), isso é `maxlag≈76`, e a busca AIC ajusta
       UMA regressão OLS (logo, UMA SVD via `np.linalg.svd` dentro de
       `pinv_extended`) por cada lag testado -- até 76 SVDs por chamada,
       cada uma sobre uma matriz de desenho `(nobs, lag+2)`. Isso é um
       problema conhecido e documentado da própria `statsmodels`
       (`autolag` "wasting memory", issue #1849, aberta desde 2014, ainda
       sem fix definitivo em 0.14.6) -- não uma suposição. Fixar
       `maxlag=ljung_box_lags` (mesma constante do Ljung-Box, mesma
       justificativa de "nº de lags relevante pra retorno financeiro
       intradiário") faz UMA única regressão em vez de até 76 -- reduz o
       nº de SVDs por task em ~76x e o tamanho da MAIOR matriz testada de
       `(nobs, 78)` pra `(nobs, ljung_box_lags+2)`.
    2. **Blindagem contra falha conhecida do driver LAPACK `gesdd`.** Mesmo
       com (1), `np.linalg.svd` sobre matriz alta-e-estreita (`nobs` linhas
       × poucas colunas) usa por padrão o driver `gesdd` (divide-and-
       conquer) do backend BLAS dos wheels do NumPy pro Windows/PyPI
       (OpenBLAS, confirmado por pesquisa -- não presumido) -- `gesdd` tem
       histórico documentado de falhar/vazar memória sob concorrência ou
       matrizes grandes independente do nº de threads (numpy#20384 "init_
       dgesdd failed init for large SVD"; OpenBLAS#3044 "GESDD fails when
       GESVD succeeds, depends on number of threads"; múltiplos issues de
       crash em matriz alta-e-estreita no próprio OpenBLAS). `numpy.linalg.
       svd` não expõe parâmetro de driver (diferente de `scipy.linalg.svd
       (..., lapack_driver=...)`), então não dá pra forçar `gesvd` sem
       monkey-patch frágil -- a defesa correta é capturar a falha (
       `MemoryError`/`numpy.linalg.LinAlgError`, ambas observadas em
       produção nesta sessão) e devolver NaN explícito pra ESSA célula, não
       deixar 1 task ruim derrubar as outras 19 do batch (mesma disciplina
       FCN de `_nan_metrics` -- não computável ≠ zero)."""
    try:
        adf_result = adfuller(r, maxlag=maxlag, autolag=None)
        return float(adf_result[0]), float(adf_result[1])
    except (MemoryError, np.linalg.LinAlgError) as exc:
        logger.warning(
            "analysis.m2_bar_comparison.adf_failed",
            symbol=symbol,
            bar_type=bar_type,
            n_returns=len(r),
            error=repr(exc),
        )
        return float("nan"), float("nan")


def _nan_metrics(symbol: str, bar_type: str, n_bars: int, n_returns: int) -> BarComparisonMetrics:
    nan = float("nan")
    return BarComparisonMetrics(
        symbol=symbol,
        bar_type=bar_type,
        n_bars=n_bars,
        n_returns=n_returns,
        jarque_bera_stat=nan,
        jarque_bera_pvalue=nan,
        kurtosis_excess=nan,
        ljung_box_r_pvalue=nan,
        ljung_box_r2_pvalue=nan,
        adf_stat=nan,
        adf_pvalue=nan,
        avg_uniqueness=nan,
    )


def compute_bar_statistics(
    symbol: str, bar_type: str, bars: pl.DataFrame, *, time_stop_ms: int, ljung_box_lags: int
) -> BarComparisonMetrics:
    """Núcleo puro (sem IO) -- JB/curtose/Ljung-Box(r,r²)/ADF sobre
    log-retorno de `close`, e unicidade média via `compute_concurrency_and_
    uniqueness` sobre `close_time`. Testável isoladamente com `bars`
    sintético, ao contrário de `compute_bar_comparison_for_symbol` (IO
    real)."""
    n_bars = bars.height
    close = bars["close"].cast(pl.Float64).to_numpy()
    r = _log_returns(close)
    n_returns = int(np.sum(np.isfinite(r)))
    min_obs = _MIN_OBS_FOR_TESTS_MULTIPLIER * ljung_box_lags
    if n_returns < min_obs:
        return _nan_metrics(symbol, bar_type, n_bars, n_returns)
    r_finite = r[np.isfinite(r)]

    jb = scipy_stats.jarque_bera(r_finite)
    kurt = float(scipy_stats.kurtosis(r_finite, fisher=True))
    lb_r = acorr_ljungbox(r_finite, lags=[ljung_box_lags], return_df=True)
    lb_r2 = acorr_ljungbox(r_finite**2, lags=[ljung_box_lags], return_df=True)
    adf_stat, adf_pvalue = _run_adfuller(symbol, bar_type, r_finite, maxlag=ljung_box_lags)

    close_time = bars["close_time"].cast(pl.Int64).to_numpy()
    t0 = close_time.astype(np.int64)
    t1 = t0 + time_stop_ms
    _, uniqueness = compute_concurrency_and_uniqueness(t0, t1)

    return BarComparisonMetrics(
        symbol=symbol,
        bar_type=bar_type,
        n_bars=n_bars,
        n_returns=n_returns,
        jarque_bera_stat=float(jb.statistic),
        jarque_bera_pvalue=float(jb.pvalue),
        kurtosis_excess=kurt,
        ljung_box_r_pvalue=float(lb_r["lb_pvalue"].iloc[0]),
        ljung_box_r2_pvalue=float(lb_r2["lb_pvalue"].iloc[0]),
        adf_stat=adf_stat,
        adf_pvalue=adf_pvalue,
        avg_uniqueness=float(np.mean(uniqueness)) if uniqueness.size else float("nan"),
    )


def _query_baseline(symbol: str) -> pl.DataFrame:
    return lake.query_bars(
        symbol,
        BASELINE_TF,
        SYMBOL_START_DATE[symbol],
        END_DATE,
        source="klines_1m",
        cast_prices=True,
    )


def _target_n_bars(symbol: str, baseline: pl.DataFrame) -> int:
    n = baseline.height
    if n == 0:
        raise ValueError(
            f"baseline vazio para {symbol} -- sem klines_1m no período "
            f"{SYMBOL_START_DATE[symbol]}..{END_DATE}, não dá pra calibrar dollar/volume/tick "
            "imbalance bars pra frequência média nenhuma"
        )
    return n


def _build_tick_imbalance_config(
    trades: pl.DataFrame, target_n_bars: int
) -> TickImbalanceBarsConfig:
    # target_n_bars > 0 garantido pelo caller (_target_n_bars).
    exp_num_ticks_init = float(trades.height) / target_n_bars  # noqa: unguarded-ratio
    clip_mult = float(load_data_constant("bars_tick_imbalance_clip_multiplier"))
    if clip_mult <= 0:
        raise ValueError(
            f"bars_tick_imbalance_clip_multiplier precisa ser > 0, constants.yaml tem {clip_mult}"
        )
    return TickImbalanceBarsConfig(
        num_prev_bars=int(load_data_constant("bars_tick_imbalance_num_prev_bars")),
        expected_imbalance_window=int(
            load_data_constant("bars_tick_imbalance_expected_imbalance_window")
        ),
        exp_num_ticks_init=exp_num_ticks_init,
        exp_num_ticks_min=exp_num_ticks_init / clip_mult,  # noqa: unguarded-ratio -- clip_mult>0 acima
        exp_num_ticks_max=exp_num_ticks_init * clip_mult,
    )


def compute_bar_type_for_symbol(
    symbol: str, bar_type: str, *, time_stop_ms: int, ljung_box_lags: int
) -> BarComparisonMetrics:
    """Núcleo de IO pra EXATAMENTE um (symbol, bar_type) -- desenhado pra
    rodar como task independente num pool grande (ver `run_and_save_bar_
    comparison_report`), não presume que outro `bar_type` do mesmo símbolo
    já rodou ou vai rodar no mesmo processo (ver "Performance" na
    docstring do módulo sobre o custo de releitura de `aggTrades`)."""
    if bar_type not in BAR_TYPES:
        raise ValueError(f"bar_type desconhecido: {bar_type!r} (válidos: {BAR_TYPES})")

    if bar_type == "time":
        bars = _query_baseline(symbol)
        return compute_bar_statistics(
            symbol, "time", bars, time_stop_ms=time_stop_ms, ljung_box_lags=ljung_box_lags
        )

    target_n_bars = _target_n_bars(symbol, _query_baseline(symbol))
    trades = lake.query_agg_trades(symbol, SYMBOL_START_DATE[symbol], END_DATE)

    if bar_type == "dollar":
        total_dollar = float((trades["price"] * trades["quantity"]).sum())
        threshold = total_dollar / target_n_bars  # noqa: unguarded-ratio -- target_n_bars>0 acima
        bars = dollar_bars(trades, threshold=threshold)
    elif bar_type == "volume":
        total_volume = float(trades["quantity"].sum())
        threshold = total_volume / target_n_bars  # noqa: unguarded-ratio -- target_n_bars>0 acima
        bars = volume_bars(trades, threshold=threshold)
    else:  # "tick_imbalance"
        config = _build_tick_imbalance_config(trades, target_n_bars)
        bars = tick_imbalance_bars(trades, config)

    metrics = compute_bar_statistics(
        symbol, bar_type, bars, time_stop_ms=time_stop_ms, ljung_box_lags=ljung_box_lags
    )
    logger.info(
        "analysis.m2_bar_comparison.task_done",
        symbol=symbol,
        bar_type=bar_type,
        n_bars=metrics.n_bars,
        jarque_bera_pvalue=metrics.jarque_bera_pvalue,
        ljung_box_r_pvalue=metrics.ljung_box_r_pvalue,
        avg_uniqueness=metrics.avg_uniqueness,
    )
    return metrics


def compute_bar_comparison_for_symbol(symbol: str) -> list[BarComparisonMetrics]:
    """Conveniência pra depuração manual de UM símbolo, sequencial (os 4
    `bar_type` no mesmo processo) -- o caminho de produção real é
    `run_and_save_bar_comparison_report`, que fatia por (symbol, bar_type)
    pra paralelismo de verdade (ver docstring do módulo)."""
    time_stop_bars_n = int(load_risk_constant("time_stop_bars"))
    time_stop_ms = time_stop_bars_n * step_ms(BASELINE_TF)
    ljung_box_lags = int(load_data_constant("bars_comparison_ljung_box_lags"))
    return [
        compute_bar_type_for_symbol(
            symbol, bar_type, time_stop_ms=time_stop_ms, ljung_box_lags=ljung_box_lags
        )
        for bar_type in BAR_TYPES
    ]


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
    logger.info("analysis.m2_bar_comparison.report_written", path=str(dest_path))


def run_and_save_bar_comparison_report(
    *,
    symbols: tuple[str, ...] = tuple(SYMBOL_START_DATE),
    dest_path: Path | None = None,
    max_workers: int | None = None,
) -> Path:
    """Ponto de entrada MANUAL -- fatia o trabalho em `len(symbols) ×
    len(BAR_TYPES)` tasks independentes (até 20, com os 5 ativos padrão) e
    roda num `ProcessPoolExecutor` dimensionado por `os.cpu_count()` --
    não por `len(symbols)` (ver "Performance" na docstring do módulo:
    paralelizar só por símbolo deixaria núcleo ocioso, já que só há 5
    símbolos mas potencialmente muito mais núcleos disponíveis). Persiste
    o relatório, atômico (B29).

    Chame manualmente: `uv run python -m src.analysis.m2_bar_comparison`."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    time_stop_bars_n = int(load_risk_constant("time_stop_bars"))
    time_stop_ms = time_stop_bars_n * step_ms(BASELINE_TF)
    ljung_box_lags = int(load_data_constant("bars_comparison_ljung_box_lags"))

    tasks = [(symbol, bar_type) for symbol in symbols for bar_type in BAR_TYPES]
    logger.info(
        "analysis.m2_bar_comparison.starting",
        n_symbols=len(symbols),
        n_tasks=len(tasks),
        max_workers=workers,
    )

    results_by_symbol: dict[str, dict[str, BarComparisonMetrics]] = {
        symbol: {} for symbol in symbols
    }
    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_to_task = {
            executor.submit(
                compute_bar_type_for_symbol,
                symbol,
                bar_type,
                time_stop_ms=time_stop_ms,
                ljung_box_lags=ljung_box_lags,
            ): (symbol, bar_type)
            for symbol, bar_type in tasks
        }
        for future in as_completed(future_to_task):
            symbol, bar_type = future_to_task[future]
            results_by_symbol[symbol][bar_type] = future.result()

    payload: dict[str, Any] = {
        **report_provenance(),
        "baseline_tf": BASELINE_TF,
        "bar_types": list(BAR_TYPES),
        "symbols": {
            symbol: [asdict(results_by_symbol[symbol][bar_type]) for bar_type in BAR_TYPES]
            for symbol in sorted(symbols)
        },
    }
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info(
        "analysis.m2_bar_comparison.done", n_symbols=len(results_by_symbol), dest=str(dest)
    )
    return dest


if __name__ == "__main__":
    run_and_save_bar_comparison_report()
