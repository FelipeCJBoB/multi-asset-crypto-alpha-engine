"""M2 — comparação de tipo de barra (PRD_V4_1.md §3.2, linhas 382-388):
"Candidatos: tempo (baseline) · dollar bars · volume bars · tick imbalance
bars, calibradas para a mesma frequência média. Métricas: Jarque-Bera ·
curtose · Ljung-Box em `r` e `r²` · ADF · razão de amostra efetiva
(unicidade média com `time_stop` equivalente em relógio)." Zero trials —
medição, não busca.

**Multi-timeframe, PRD_V4_1.md §0.4: "Três timeframes — M15, M30, H1 —
obrigatórios ponta a ponta."** Iterado sobre `TIMEFRAMES = ("15m", "30m",
"1h")` (`src.analysis.volatility_comparison`, mesma constante que
`m3_timeframe_choice.py` já consome) — cada (symbol, tf) tem seu próprio
baseline, `target_n_bars` e calibração de threshold/`exp_num_ticks_init`,
porque dollar/volume/tick-imbalance bars calibradas pra 15m não são
"reagregáveis" em 30m/1h como barras de tempo seriam (roll-up hierárquico
não existe pra barra particionada por threshold — precisa reparticionar
os trades crus do zero por TF). Achado de auditoria (2026-08-15): este
módulo foi escrito nesta sessão SEM essa iteração — hardcodava
`BASELINE_TF = "15m"` — apesar de `TIMEFRAMES` estar um `import` de
distância (mesmo `from src.analysis.volatility_comparison import ...` já
em uso) e de `PLANO_MESTRE_PRINCE2.md` §15.6 item 1 já ter previsto esse
risco por nome ("...se M2/M3 rodarem antes disso ser corrigido") antes
deste módulo existir. Registrado como `AG-017`,
`audit/architecture_gaps_log.yaml`.

**Hipótese testável, não assumida (nota multi-ativo do PRD):** dollar bars
normalizam por atividade — com volume variando 3.700x entre os 5 ativos
(I1), podem tornar os cinco mais comparáveis que barras de tempo. Este
módulo MEDE se isso é verdade (JB/curtose/Ljung-Box mais "bem
comportados", i.e. mais perto de ruído branco gaussiano, em dollar bars
do que em barras de tempo, consistentemente nos 5 ativos E nos 3 TFs) —
não presume.

**A partir de `aggTrades`, não de `klines_1m`.** `klines_1m` já É uma
agregação temporal — usar klines pra medir "a barra de tempo é pior que
outra coisa" seria circular (o próprio dado de entrada já tem a
propriedade sendo testada). `src.data.bars` constrói as 3 barras
alternativas trade-a-trade real, TF-agnóstico por natureza (só enxerga
trades crus, nunca um conceito de "timeframe") — só a camada de
calibração/comparação aqui em `m2_bar_comparison.py` tem dimensão de TF.
O baseline usa `lake.query_bars` (mesma fonte de M1/M3) pra ficar
consistente com o resto da Camada 1.

**Calibração — mesma frequência média que o baseline DAQUELE TF, medida
não suposta.** `target_n_bars` = nº de barras do baseline NO TF sendo
medido, no mesmo período; `threshold` de dollar/volume bars = volume
total (em $ ou unidades) dividido por `target_n_bars`; `exp_num_ticks_init`
de tick imbalance bars = nº total de ticks dividido por `target_n_bars`
(mesma lógica: barra "típica" do TIB deveria consumir, em média, tantos
ticks quantos a barra daquele TF consome em relógio). O volume
total/nº de ticks (`_scan_trades_totals`) NÃO depende de TF — é somado
1x por símbolo e reusado nos 3 TFs (ver `compute_trades_dependent_bars_
for_symbol`); só o `target_n_bars` (e portanto o `threshold` calibrado)
muda por TF.

**"Razão de amostra efetiva" reusa `src.labels.weights.
compute_concurrency_and_uniqueness`** (produção real, testada, mesma
função que calcula `sample_weight` do Label Engine) — não uma
reimplementação. `t0` = `close_time` de cada barra, `t1` = `close_time +
time_stop_bars×15min`. **`time_stop_ms` é FIXO, calculado 1x via
`step_ms("15m")` — nunca recalculado por TF.** `time_stop_bars=32`
(`constants.yaml`) é justificado como "uma janela de funding"
(32×15min = 8h exatas) — é uma constante em UNIDADES DE BARRA DE 15M, não
um nº de barras TF-agnóstico. Recalcular como `time_stop_bars × step_ms(tf)`
mudaria o horizonte de "amostra efetiva" a cada TF (16h em 30m, 32h em
1h) — exatamente a classe de erro silencioso de unidade que
`PLANO_MESTRE_PRINCE2.md` §15.6 item 1 já tinha previsto pra este módulo.
`TIME_STOP_REFERENCE_TF` abaixo existe só pra deixar essa invariância
explícita, não é o TF sendo medido em cada iteração. Import de
`src.labels` a partir de `src.analysis` NÃO viola a hierarquia de camadas
(`pyproject.toml::[tool.importlinter]`, contrato "labels só é lido por
models, validation, backtest" lista só `exchange/data/features/regime/
risk/execution/live/monitoring` como proibidos — `analysis` fica de fora
deliberadamente, mesmo padrão já usado em `m6_common_factor_hypothesis.py`).

**Memória domina o desenho, não CPU.** Achado de auditoria (2026-08-15,
medido antes de mudar qualquer coisa): `aggTrades` de BTCUSDT/ETHUSDT são
27GB/20GB *comprimidos* em disco — descompactado como `DataFrame` tipado,
isso não cabe na RAM inteira de uma vez, em NENHUMA concorrência (nem 1
processo sozinho). `compute_trades_dependent_bars_for_symbol` processa
cada símbolo em streaming, chunk-a-chunk (`bars_streaming_chunk_days` dias
por vez — ver `src.data.bars`, que mantém só o estado necessário entre
chunks, nunca o histórico inteiro), em 2 passadas: 1ª só soma totais pra
calibrar `threshold`/`exp_num_ticks_init`, 2ª constrói as barras de fato.
Duas tentativas anteriores (reduzir de 15 pra 5 cargas concorrentes,
depois travar threads BLAS pra 1) atacavam CONCORRÊNCIA e continuaram
falhando com `duckdb.OutOfMemoryException` — o problema real nunca foi
quantos processos rodavam ao mesmo tempo, era que uma única carga do
histórico completo de 1 símbolo já não cabia.

**4º achado (2026-08-14) — chunking sozinho não bastou: era o orçamento
default do DuckDB, não o tamanho da query.** Mesmo com `bars_streaming_
chunk_days` limitando cada query a ~30 dias, uma execução real ainda
produziu `duckdb.OutOfMemoryException` em 3 dos 5 símbolos. Pesquisa web
(duckdb.org/docs/current/guides/performance/oom; GitHub `duckdb/duckdb`
discussion #11155) confirmou: `duckdb.connect(":memory:")` sem `SET
memory_limit`/`SET threads` explícitos assume por padrão até ~80% da RAM
TOTAL da máquina e várias threads *por conexão*, sem coordenação entre
processos — cada um dos até `n_tasks=10` processos concorrentes
(`ProcessPoolExecutor`) abre sua PRÓPRIA conexão via `lake._read_files`
com esse mesmo orçamento otimista, e a soma estoura a RAM real disponível
mesmo com cada query individual pequena. `_duckdb_throttle()` aplica `SET
memory_limit`/`SET threads` explícitos (`constants.yaml::m2_duckdb_
memory_limit_gb`/`m2_duckdb_threads`, derivados de `28GB livres / 10
tasks` com margem de segurança) em toda chamada a `lake.query_bars`/
`lake.query_agg_trades` deste módulo — `lake.py` continua com os defaults
do DuckDB pra todo resto do repo (parâmetros opcionais, `None` por
padrão, zero mudança de comportamento fora daqui).

**Paralelismo entre símbolos continua por processo, topologia do pool NÃO
muda com os 3 TFs** (`run_and_save_bar_comparison_report`,
`ProcessPoolExecutor` dimensionado por `os.cpu_count()`, ainda `2 ×
len(symbols)` tasks) — `tick_imbalance_bars_step` é sequencial dentro de
cada processo (ver docstring de `src.data.bars`), mas os 5 símbolos
processam em paralelo entre si, cada um com memória limitada ao tamanho
de 1 chunk, não ao histórico inteiro. `compute_time_bar_for_symbol`/
`compute_trades_dependent_bars_for_symbol` passam a devolver
`list[BarComparisonMetrics]` (3 e 9 itens, um por TF/[TF×bar_type]) em
vez de 1 item — o loop dos 3 TFs fica DENTRO da task por símbolo (mesmo
padrão de `m3_timeframe_choice.py::compute_timeframe_choice_for_symbol`),
não um novo eixo de fan-out do pool — preserva a contagem de tasks
concorrentes que `m2_duckdb_memory_limit_gb`/`m2_duckdb_threads` já foram
derivados para. Custo real: o path pesado (`aggTrades`) passa de 1 pass-1
+ 1 pass-2 por símbolo para 1 pass-1 (compartilhado, TF-independente) + 3
pass-2 (1 por TF, threshold diferente) — ~4x o I/O de `aggTrades` do
desenho de 1 TF só, runtime esperado maior. Ponto de entrada manual, não
é testado de ponta a ponta no pytest (mesma convenção de M1/M3/M6 — IO
real fica fora da suíte automatizada; a propriedade crítica de
streaming↔lote é testada em `test_data_bars.py`, que não depende de IO
real)."""

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
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy import stats as scipy_stats
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import adfuller

from src.analysis.volatility_comparison import END_DATE, SYMBOL_START_DATE, TIMEFRAMES
from src.core.provenance import report_provenance
from src.data import lake
from src.data._constants import load_constant as load_data_constant
from src.data.bars import (
    TickImbalanceBarsConfig,
    dollar_bars_carry,
    threshold_bars_finish,
    threshold_bars_step,
    tick_imbalance_bars_carry,
    tick_imbalance_bars_finish,
    tick_imbalance_bars_step,
    volume_bars_carry,
)
from src.data.resample import step_ms
from src.labels.weights import compute_concurrency_and_uniqueness
from src.risk._constants import load_constant as load_risk_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "m2_bar_comparison_report.json"

#: TF usado SÓ pra calcular `time_stop_ms` (ver docstring do módulo --
#: `time_stop_bars=32` é "1 janela de funding" em unidades de barra de
#: 15m, fixo independente de qual TF está sendo medido na iteração de
#: `TIMEFRAMES`). Não é o baseline de bar comparison -- esse é `tf`,
#: iterado, ver `compute_time_bar_for_symbol`/`compute_trades_dependent_
#: bars_for_symbol`.
TIME_STOP_REFERENCE_TF: Final[str] = "15m"
BAR_TYPES: Final[tuple[str, ...]] = ("time", "dollar", "volume", "tick_imbalance")

# Ljung-Box/ADF exigem amostra bem maior que o número de lags -- 4x é uma
# folga de engenharia (não domínio), evita crash de statsmodels em barras
# degeneradas sem inventar mais uma constante de constants.yaml.
_MIN_OBS_FOR_TESTS_MULTIPLIER: Final[int] = 4


@dataclass(frozen=True, slots=True)
class BarComparisonMetrics:
    """Resumo por (symbol, tf, bar_type) -- `NaN` explícito onde a amostra
    é pequena demais pros testes (nunca um zero fabricado)."""

    symbol: str
    tf: str
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
    symbol: str, tf: str, bar_type: str, r: FloatArray, *, maxlag: int
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
            tf=tf,
            bar_type=bar_type,
            n_returns=len(r),
            error=repr(exc),
        )
        return float("nan"), float("nan")


def _nan_metrics(
    symbol: str, tf: str, bar_type: str, n_bars: int, n_returns: int
) -> BarComparisonMetrics:
    nan = float("nan")
    return BarComparisonMetrics(
        symbol=symbol,
        tf=tf,
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
    symbol: str,
    tf: str,
    bar_type: str,
    bars: pl.DataFrame,
    *,
    time_stop_ms: int,
    ljung_box_lags: int,
) -> BarComparisonMetrics:
    """Núcleo puro (sem IO) -- JB/curtose/Ljung-Box(r,r²)/ADF sobre
    log-retorno de `close`, e unicidade média via `compute_concurrency_and_
    uniqueness` sobre `close_time`. Testável isoladamente com `bars`
    sintético, ao contrário de `compute_bar_comparison_for_symbol` (IO
    real). `time_stop_ms` é FIXO entre chamadas com `tf` diferente -- ver
    docstring do módulo (`TIME_STOP_REFERENCE_TF`) -- este núcleo só
    recebe o valor já calculado, não recalcula por `tf`."""
    n_bars = bars.height
    close = bars["close"].cast(pl.Float64).to_numpy()
    r = _log_returns(close)
    n_returns = int(np.sum(np.isfinite(r)))
    min_obs = _MIN_OBS_FOR_TESTS_MULTIPLIER * ljung_box_lags
    if n_returns < min_obs:
        return _nan_metrics(symbol, tf, bar_type, n_bars, n_returns)
    r_finite = r[np.isfinite(r)]

    jb = scipy_stats.jarque_bera(r_finite)
    kurt = float(scipy_stats.kurtosis(r_finite, fisher=True))
    lb_r = acorr_ljungbox(r_finite, lags=[ljung_box_lags], return_df=True)
    lb_r2 = acorr_ljungbox(r_finite**2, lags=[ljung_box_lags], return_df=True)
    adf_stat, adf_pvalue = _run_adfuller(symbol, tf, bar_type, r_finite, maxlag=ljung_box_lags)

    close_time = bars["close_time"].cast(pl.Int64).to_numpy()
    t0 = close_time.astype(np.int64)
    t1 = t0 + time_stop_ms
    _, uniqueness = compute_concurrency_and_uniqueness(t0, t1)

    return BarComparisonMetrics(
        symbol=symbol,
        tf=tf,
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


@dataclass(frozen=True, slots=True)
class _DuckDBThrottle:
    memory_limit_gb: float
    threads: int


def _duckdb_throttle() -> _DuckDBThrottle:
    """`memory_limit`/`threads` por conexão DuckDB -- achado de auditoria
    (2026-08-14): `duckdb.connect(":memory:")` sem `SET` explícito assume
    até ~80% da RAM TOTAL da máquina e várias threads por conexão, achando
    que é o único processo rodando nela. Sob `ProcessPoolExecutor` com até
    `n_tasks=10` processos concorrentes (`run_and_save_bar_comparison_
    report`), cada um abrindo sua própria conexão via `lake._read_files`,
    o orçamento otimista somado estourava a RAM real disponível mesmo com
    `bars_streaming_chunk_days` já limitando o tamanho de CADA query
    individual -- `duckdb.OutOfMemoryException` recorrente em produção
    (2026-08-14) não era sobre tamanho de query, era sobre orçamento
    default assumido por conexão × nº de conexões concorrentes. Ver
    `constants.yaml::m2_duckdb_memory_limit_gb`/`m2_duckdb_threads` e
    docstring de `lake._read_files`."""
    return _DuckDBThrottle(
        memory_limit_gb=float(load_data_constant("m2_duckdb_memory_limit_gb")),
        threads=int(load_data_constant("m2_duckdb_threads")),
    )


def _query_baseline(symbol: str, tf: str) -> pl.DataFrame:
    throttle = _duckdb_throttle()
    return lake.query_bars(
        symbol,
        tf,
        SYMBOL_START_DATE[symbol],
        END_DATE,
        source="klines_1m",
        cast_prices=True,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )


def _target_n_bars(symbol: str, tf: str, baseline: pl.DataFrame) -> int:
    n = baseline.height
    if n == 0:
        raise ValueError(
            f"baseline vazio para {symbol}/{tf} -- sem klines_1m no período "
            f"{SYMBOL_START_DATE[symbol]}..{END_DATE}, não dá pra calibrar dollar/volume/tick "
            "imbalance bars pra frequência média nenhuma"
        )
    return n


def _build_tick_imbalance_config(n_ticks: int, target_n_bars: int) -> TickImbalanceBarsConfig:
    # target_n_bars > 0 garantido pelo caller (_target_n_bars).
    exp_num_ticks_init = float(n_ticks) / target_n_bars  # noqa: unguarded-ratio
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


def _date_chunks(start: str, end: str, *, chunk_days: int) -> list[tuple[date, date]]:
    """Fatia `[start, end]` em janelas de `chunk_days` dias (última pode
    ser menor) -- `lake.query_agg_trades` já aceita `date` diretamente
    (`DateLike = date | datetime | str`), sem precisar formatar string."""
    if chunk_days <= 0:
        raise ValueError(f"chunk_days precisa ser > 0, recebido {chunk_days}")
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date > end_date:
        raise ValueError(f"start ({start}) posterior a end ({end})")

    chunks: list[tuple[date, date]] = []
    cursor = start_date
    step = timedelta(days=chunk_days)
    one_day = timedelta(days=1)
    while cursor <= end_date:
        chunk_end = min(cursor + step - one_day, end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + one_day
    return chunks


@dataclass(slots=True)
class _TradesTotals:
    """Saída da 1ª passada (só somas, nunca materializa o histórico
    inteiro de uma vez -- ver `_scan_trades_totals`)."""

    total_dollar: float = 0.0
    total_volume: float = 0.0
    n_ticks: int = 0


def _scan_trades_totals(symbol: str, chunks: list[tuple[date, date]]) -> _TradesTotals:
    """1ª passada: só soma `price*quantity`/`quantity`/contagem por chunk,
    descartando cada chunk assim que somado -- memória limitada ao tamanho
    de 1 chunk (`bars_streaming_chunk_days`), nunca ao histórico inteiro.
    Necessária pra calibrar `threshold`/`exp_num_ticks_init` (§3.2 M2: "mesma
    frequência média que o baseline") ANTES de construir as barras de
    verdade na 2ª passada (`_build_trades_dependent_bars`) -- custo aceito
    conscientemente: cada dia de `aggTrades` é lido do disco 2x, não 1x,
    mas isso troca E/S (barata, arquivos locais) por memória (o recurso que
    realmente estourou, ver docstring do módulo)."""
    totals = _TradesTotals()
    throttle = _duckdb_throttle()
    for chunk_start, chunk_end in chunks:
        chunk = lake.query_agg_trades(
            symbol,
            chunk_start,
            chunk_end,
            duckdb_memory_limit_gb=throttle.memory_limit_gb,
            duckdb_threads=throttle.threads,
        )
        if chunk.is_empty():
            continue
        totals.total_dollar += float((chunk["price"] * chunk["quantity"]).sum())
        totals.total_volume += float(chunk["quantity"].sum())
        totals.n_ticks += chunk.height
    return totals


def _build_trades_dependent_bars(
    symbol: str,
    chunks: list[tuple[date, date]],
    *,
    dollar_threshold: float,
    volume_threshold: float,
    tib_config: TickImbalanceBarsConfig,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """2ª passada: relê os mesmos chunks e alimenta os 3 acumuladores de
    barra (`dollar`/`volume`/`tick_imbalance`) num loop só -- 1x de E/S por
    chunk aqui, não 3x (os 3 tipos compartilham o mesmo chunk já carregado
    em memória, só o estado carregado entre chunks é que é por tipo)."""
    dollar_carry = dollar_bars_carry(threshold=dollar_threshold)
    volume_carry = volume_bars_carry(threshold=volume_threshold)
    tib_carry = tick_imbalance_bars_carry(tib_config)

    throttle = _duckdb_throttle()
    for chunk_start, chunk_end in chunks:
        chunk = lake.query_agg_trades(
            symbol,
            chunk_start,
            chunk_end,
            duckdb_memory_limit_gb=throttle.memory_limit_gb,
            duckdb_threads=throttle.threads,
        )
        if chunk.is_empty():
            continue
        threshold_bars_step(dollar_carry, chunk)
        threshold_bars_step(volume_carry, chunk)
        tick_imbalance_bars_step(tib_carry, chunk)

    return (
        threshold_bars_finish(dollar_carry),
        threshold_bars_finish(volume_carry),
        tick_imbalance_bars_finish(tib_carry),
    )


_TRADES_DEPENDENT_BAR_TYPES: Final[tuple[str, ...]] = tuple(bt for bt in BAR_TYPES if bt != "time")


def _log_task_done(metrics: BarComparisonMetrics) -> None:
    logger.info(
        "analysis.m2_bar_comparison.task_done",
        symbol=metrics.symbol,
        tf=metrics.tf,
        bar_type=metrics.bar_type,
        n_bars=metrics.n_bars,
        jarque_bera_pvalue=metrics.jarque_bera_pvalue,
        ljung_box_r_pvalue=metrics.ljung_box_r_pvalue,
        avg_uniqueness=metrics.avg_uniqueness,
    )


def compute_time_bar_for_symbol(
    symbol: str, *, time_stop_ms: int, ljung_box_lags: int
) -> list[BarComparisonMetrics]:
    """Núcleo de IO pro tipo `"time"` -- só `klines_1m`, leve, roda numa
    task própria pra não competir por memória com as tasks de `aggTrades`
    (ver `compute_trades_dependent_bars_for_symbol`). Itera `TIMEFRAMES`
    internamente (mesmo padrão de `m3_timeframe_choice.py::compute_
    timeframe_choice_for_symbol`) -- não é um eixo novo de fan-out do
    pool, ver docstring do módulo."""
    results: list[BarComparisonMetrics] = []
    for tf in TIMEFRAMES:
        bars = _query_baseline(symbol, tf)
        metrics = compute_bar_statistics(
            symbol, tf, "time", bars, time_stop_ms=time_stop_ms, ljung_box_lags=ljung_box_lags
        )
        _log_task_done(metrics)
        results.append(metrics)
    return results


def compute_trades_dependent_bars_for_symbol(
    symbol: str, *, time_stop_ms: int, ljung_box_lags: int
) -> list[BarComparisonMetrics]:
    """Constrói `dollar`/`volume`/`tick_imbalance` bars pra 1 símbolo, nos
    3 TFs de `TIMEFRAMES`, em STREAMING -- achado de auditoria
    (2026-08-15, medido antes de mudar qualquer coisa): `aggTrades` de
    BTCUSDT/ETHUSDT são 27GB/20GB *comprimidos* em disco, não cabem em
    memória de uma vez em NENHUMA concorrência (nem 1 processo sozinho).

    A 1ª passada (`_scan_trades_totals`, totais de $/unidades/ticks) NÃO
    depende de TF -- roda 1x aqui, reusada nos 3 TFs. A 2ª passada
    (`_build_trades_dependent_bars`, threshold calibrado + construção de
    fato) DEPENDE de TF (`target_n_bars` diferente por TF -> threshold
    diferente -> partição diferente dos mesmos trades crus, barras
    calibradas por threshold não são "reagregáveis" hierarquicamente como
    barras de tempo) -- roda 1x POR TF, 3x no total por símbolo. Cada
    iteração de TF é blindada contra `duckdb.OutOfMemoryException`
    residual de forma independente (mesma disciplina FCN de
    `_run_adfuller`/`_nan_metrics`) -- um chunk ruim num TF vira `NaN` só
    pros 3 `bar_types` DAQUELE TF, não derruba os outros 2 TFs nem os
    outros símbolos do batch. Se a 1ª passada (totais, compartilhada)
    falhar, os 3 TFs × 3 bar_types (9 linhas) desse símbolo viram `NaN`
    de uma vez -- sem totais não há como calibrar threshold nenhum."""
    chunk_days = int(load_data_constant("bars_streaming_chunk_days"))
    chunks = _date_chunks(SYMBOL_START_DATE[symbol], END_DATE, chunk_days=chunk_days)

    try:
        totals = _scan_trades_totals(symbol, chunks)
    except duckdb.OutOfMemoryException as exc:
        logger.warning(
            "analysis.m2_bar_comparison.trades_totals_failed", symbol=symbol, error=repr(exc)
        )
        return [
            _nan_metrics(symbol, tf, bar_type, 0, 0)
            for tf in TIMEFRAMES
            for bar_type in _TRADES_DEPENDENT_BAR_TYPES
        ]
    if totals.n_ticks == 0:
        raise ValueError(
            f"aggTrades vazio para {symbol} no período "
            f"{SYMBOL_START_DATE[symbol]}..{END_DATE} -- não dá pra calibrar bars"
        )

    results: list[BarComparisonMetrics] = []
    for tf in TIMEFRAMES:
        target_n_bars = _target_n_bars(symbol, tf, _query_baseline(symbol, tf))
        dollar_threshold = totals.total_dollar / target_n_bars  # noqa: unguarded-ratio -- target_n_bars>0 acima
        volume_threshold = totals.total_volume / target_n_bars  # noqa: unguarded-ratio -- target_n_bars>0 acima
        tib_config = _build_tick_imbalance_config(totals.n_ticks, target_n_bars)

        try:
            dollar_df, volume_df, tib_df = _build_trades_dependent_bars(
                symbol,
                chunks,
                dollar_threshold=dollar_threshold,
                volume_threshold=volume_threshold,
                tib_config=tib_config,
            )
        except duckdb.OutOfMemoryException as exc:
            logger.warning(
                "analysis.m2_bar_comparison.trades_build_failed",
                symbol=symbol,
                tf=tf,
                error=repr(exc),
            )
            results.extend(
                _nan_metrics(symbol, tf, bar_type, 0, 0)
                for bar_type in _TRADES_DEPENDENT_BAR_TYPES
            )
            continue

        bars_by_type = {"dollar": dollar_df, "volume": volume_df, "tick_imbalance": tib_df}
        for bar_type in _TRADES_DEPENDENT_BAR_TYPES:
            metrics = compute_bar_statistics(
                symbol,
                tf,
                bar_type,
                bars_by_type[bar_type],
                time_stop_ms=time_stop_ms,
                ljung_box_lags=ljung_box_lags,
            )
            _log_task_done(metrics)
            results.append(metrics)
    return results


def compute_bar_comparison_for_symbol(symbol: str) -> list[BarComparisonMetrics]:
    """Conveniência pra depuração manual de UM símbolo, sequencial -- o
    caminho de produção real é `run_and_save_bar_comparison_report`, que
    roda a task leve (`"time"`) e a task pesada (dollar/volume/tick_
    imbalance, `aggTrades` carregado uma vez pra totais + 3x pra
    construção, um por TF) em paralelo entre símbolos (ver docstring do
    módulo)."""
    time_stop_bars_n = int(load_risk_constant("time_stop_bars"))
    time_stop_ms = time_stop_bars_n * step_ms(TIME_STOP_REFERENCE_TF)
    ljung_box_lags = int(load_data_constant("bars_comparison_ljung_box_lags"))
    time_metrics = compute_time_bar_for_symbol(
        symbol, time_stop_ms=time_stop_ms, ljung_box_lags=ljung_box_lags
    )
    trades_metrics = compute_trades_dependent_bars_for_symbol(
        symbol, time_stop_ms=time_stop_ms, ljung_box_lags=ljung_box_lags
    )
    return [*time_metrics, *trades_metrics]


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
    """Ponto de entrada MANUAL -- `2 × len(symbols)` tasks (até 10, com os
    5 ativos padrão): 1 task leve por símbolo (`"time"`, só `klines_1m`,
    itera os 3 TFs internamente) + 1 task pesada por símbolo (`aggTrades`
    carregado uma vez pra totais + 3x pra construção, um por TF, ver
    `compute_trades_dependent_bars_for_symbol`). A topologia do pool NÃO
    cresce com os 3 TFs -- o loop de TF fica DENTRO de cada task (mesmo
    padrão de `m3_timeframe_choice.py`), preservando a contagem de
    processos concorrentes que `m2_duckdb_memory_limit_gb`/
    `m2_duckdb_threads` já foram derivados pra suportar (nenhuma constante
    de throttle precisa mudar por causa do multi-TF). Um único
    `ProcessPoolExecutor` dimensionado por `os.cpu_count()` -- como só
    existem `len(symbols)` tasks pesadas no total, o pool nunca roda mais
    que isso concorrentemente mesmo com mais slots livres, que é
    exatamente o nível de concorrência de carga de `aggTrades` já
    confirmado seguro (ver docstring de `compute_trades_dependent_bars_
    for_symbol` -- achado de auditoria 2026-08-15: fatiar por bar_type
    além de symbol multiplicava essa carga 3x e estourava memória). Não
    precisa de dois pools separados por esse motivo. Persiste o
    relatório, atômico (B29).

    Chame manualmente: `uv run python -m src.analysis.m2_bar_comparison`."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    time_stop_bars_n = int(load_risk_constant("time_stop_bars"))
    time_stop_ms = time_stop_bars_n * step_ms(TIME_STOP_REFERENCE_TF)
    ljung_box_lags = int(load_data_constant("bars_comparison_ljung_box_lags"))

    n_tasks = 2 * len(symbols)
    logger.info(
        "analysis.m2_bar_comparison.starting",
        n_symbols=len(symbols),
        n_timeframes=len(TIMEFRAMES),
        n_tasks=n_tasks,
        max_workers=workers,
    )

    results_by_symbol: dict[str, dict[tuple[str, str], BarComparisonMetrics]] = {
        symbol: {} for symbol in symbols
    }
    with ProcessPoolExecutor(max_workers=min(workers, n_tasks)) as executor:
        time_futures = {
            executor.submit(
                compute_time_bar_for_symbol,
                symbol,
                time_stop_ms=time_stop_ms,
                ljung_box_lags=ljung_box_lags,
            ): symbol
            for symbol in symbols
        }
        trades_futures = {
            executor.submit(
                compute_trades_dependent_bars_for_symbol,
                symbol,
                time_stop_ms=time_stop_ms,
                ljung_box_lags=ljung_box_lags,
            ): symbol
            for symbol in symbols
        }
        for time_future in as_completed(time_futures):
            symbol = time_futures[time_future]
            for metrics in time_future.result():
                results_by_symbol[symbol][(metrics.tf, metrics.bar_type)] = metrics
        for trades_future in as_completed(trades_futures):
            symbol = trades_futures[trades_future]
            for metrics in trades_future.result():
                results_by_symbol[symbol][(metrics.tf, metrics.bar_type)] = metrics

    payload: dict[str, Any] = {
        **report_provenance(),
        "timeframes": list(TIMEFRAMES),
        "bar_types": list(BAR_TYPES),
        "symbols": {
            symbol: [
                asdict(results_by_symbol[symbol][(tf, bar_type)])
                for tf in TIMEFRAMES
                for bar_type in BAR_TYPES
            ]
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
