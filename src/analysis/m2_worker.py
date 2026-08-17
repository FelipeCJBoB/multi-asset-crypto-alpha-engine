"""M2 — tudo que roda DENTRO de 1 processo filho do `ProcessPoolExecutor`
de `m2_bar_comparison.py`: calibração + construção de barra via streaming
de `aggTrades`. Extraído no desmembramento de 2026-08-15 (brainstorm +
validação por auditoria externa) especificamente por ESTA fronteira, não
por camada nem por estágio de pipeline -- ver docstring completa de
`m2_bar_comparison.py` pro histórico de achados/decisões, e
`PLANO_MESTRE_PRINCE2.md` §15 pro registro formal.

**Por que fronteira de processo, e não outra coisa.** `__module__` de uma
função é o módulo onde ela foi DEFINIDA. Antes do split,
`compute_time_bar_for_symbol`/`compute_trades_dependent_bars_for_symbol_tf`
eram definidas dentro do arquivo executado via
`uv run python -m src.analysis.m2_bar_comparison` -- seu `__module__` no
processo pai era `"__main__"`, e a reconstrução disso no processo filho
(Windows `spawn`, não `fork`) dependia da maquinaria de
`multiprocessing.spawn` (`_fixup_main_from_path`/`_fixup_main_from_name`),
funcionando só porque a invocação é sempre via `-m`. Aqui, `__module__`
vira `"src.analysis.m2_worker"` -- um caminho de import absoluto de
verdade, resolvido por `import src.analysis.m2_worker` comum, sem
depender de como o script foi invocado.

**Bloco de env vars abaixo é a PRIMEIRA coisa do arquivo, antes de
qualquer import de terceiro** -- ver comentário inline. Duplicado
(idempotente, `os.environ.setdefault`) no topo de `m2_bar_comparison.py`
também, de propósito -- nenhum dos dois arquivos depende da ordem de
import do outro pra ficar correto."""

from __future__ import annotations

import os

# Oversubscription de threads BLAS/polars -- ProcessPoolExecutor já
# paraleliza no nível de PROCESSO (até `os.cpu_count()` workers, ver
# `run_and_save_bar_comparison_report` em `m2_bar_comparison.py`). Sem
# isso, cada um dos N processos TAMBÉM deixa numpy/scipy/statsmodels
# (BLAS) e polars abrirem seu próprio pool de threads interno -- N
# processos x M threads cada competem pelos mesmos N núcleos. Causa raiz
# confirmada na prática (não hipotética): rodar
# `run_and_save_bar_comparison_report` com `max_workers=12` produziu
# `numpy._core._exceptions._ArrayMemoryError` dentro de `statsmodels.
# adfuller`/`_autolag` (2026-08-15) -- contenção de alocação sob 12
# processos concorrentes cada um multi-thread, não falta de memória real
# (o array que falhou tinha 36 MiB, trivial pra qualquer máquina com RAM
# disponível). Precisa ser setado ANTES de importar numpy/polars/scipy/
# statsmodels -- no Windows (spawn, não fork) cada worker do pool
# reexecuta o módulo inteiro do zero, então isso vale em CADA processo,
# não só no principal. `warm_numba_cache_in_worker` (abaixo) reforça isso
# como 2ª linha de defesa via `ProcessPoolExecutor(initializer=...)`, mas
# NÃO substitui este bloco -- só ele roda cedo o bastante.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("POLARS_MAX_THREADS", "1")

import time
from datetime import date
from typing import Final

import duckdb
import numpy as np
import polars as pl
import structlog

from src.analysis.m2_stats import (
    BAR_TYPES,
    BarComparisonMetrics,
    _nan_metrics,
    compute_bar_statistics,
)
from src.analysis.volatility_comparison import END_DATE, SYMBOL_START_DATE, TIMEFRAMES
from src.data import lake

# `combine_as_imports` é `False` (default do ruff/isort, sem override em
# pyproject.toml) -- múltiplos `X as Y` do MESMO módulo não combinam num
# `import (...)` só, precisam de 1 linha por alias.
from src.data._chunked_scan import TradesTotals as _TradesTotals
from src.data._chunked_scan import date_chunks as _date_chunks
from src.data._chunked_scan import duckdb_throttle as _duckdb_throttle
from src.data._chunked_scan import query_baseline as _query_baseline
from src.data._chunked_scan import scan_trades_totals as _scan_trades_totals
from src.data._chunked_scan import target_n_bars as _target_n_bars
from src.data._constants import load_constant as load_data_constant
from src.data.bars import (
    TickImbalanceBarsCarry,
    TickImbalanceBarsConfig,
    dollar_bars_carry,
    threshold_bars_finish,
    threshold_bars_step,
    tick_imbalance_bars_carry,
    tick_imbalance_bars_finish,
    tick_imbalance_bars_step,
    volume_bars_carry,
)

logger = structlog.get_logger(__name__)

# mypy strict (`no_implicit_reexport`, implícito em `strict = true`) só
# considera um import RENOMEADO (`from mod import X as Y`, Y != X)
# re-exportado se `Y` estiver em `__all__` -- sem isso,
# `tests/unit/test_analysis_m2_worker.py` (que referencia
# `m2_worker._TradesTotals`/`._date_chunks`/etc. diretamente, ver docstring
# do arquivo de teste) falha mypy com `attr-defined`/`name-defined`, achado
# real ao rodar mypy nesta sessão -- antes da extração pra `_chunked_scan`
# essas 6 peças eram DEFINIDAS aqui (não importadas), então a restrição não
# se aplicava. `_TradesTotals` não é usado dentro DESTE arquivo (só
# `_date_chunks`/`_duckdb_throttle`/`_query_baseline`/`_scan_trades_totals`/
# `_target_n_bars` são chamados aqui) -- listar em `__all__` também
# satisfaz o F401 do ruff pra ela, sem precisar de suprimir a regra à parte.
__all__ = [
    "_TradesTotals",
    "_date_chunks",
    "_duckdb_throttle",
    "_query_baseline",
    "_scan_trades_totals",
    "_target_n_bars",
]

# `_date_chunks`/`_TradesTotals`/`_scan_trades_totals`/`_query_baseline`/
# `_target_n_bars`/`_duckdb_throttle` -- extraídos para `src.data.
# _chunked_scan` (2026-08-16, validação de fiação de dollar bar canônico,
# ver `src.data.build_dollar_bars`): nunca eram específicas de M2, são
# concerns genéricos de camada `data` (chunking de aggTrades, query de
# baseline de tempo, throttle de DuckDB). Reexportadas aqui com os NOMES
# ORIGINAIS via import-as -- compatibilidade total, zero-diff pra todo
# caller/teste existente que chama `m2_worker._date_chunks(...)` etc., ou
# monkeypatcha `m2_worker._scan_trades_totals` (o resto deste arquivo
# continua chamando pelo nome local, só a ORIGEM da definição muda).

_TRADES_DEPENDENT_BAR_TYPES: Final[tuple[str, ...]] = tuple(bt for bt in BAR_TYPES if bt != "time")

# AG-042 (2026-08-16, docs/refactor_dollar_bar_canonico.md §3.5, Opção D) --
# "M15/M30/H1" é uma mentira operacional pra dollar/volume/tick_imbalance
# bars: não há relógio nenhum ali, só um nº de barras herdado do baseline de
# tempo usado pra calibrar (`_target_n_bars`). `RESOLUTION_ID_BY_TF` nomeia a
# identidade REAL do resultado (R1/R2/R3) -- posicionalmente pareada com
# `TIMEFRAMES`, não uma constante de domínio numérica (mesmo tratamento já
# dado a `BAR_TYPES`), por isso vive aqui como código, não em
# `constants.yaml`. `tf` continua existindo em todo caller abaixo -- ainda é
# o parâmetro real de CALIBRAÇÃO (decide qual baseline de klines definiu
# `target_n_bars`), só deixa de ser tratado como identidade do resultado.
# dict(zip(a, b)) usa o 1o argumento como CHAVE -- precisa ser
# zip(TIMEFRAMES, ("R1",...)), não o inverso (bug real desta sessão: a
# ordem trocada produzia {"R1": "15m", ...}, invertido do que todo
# `RESOLUTION_ID_BY_TF[tf]` abaixo precisa; achado pelo próprio teste de
# regressão, test_analysis_m2_worker.py, no primeiro pytest real).
RESOLUTION_ID_BY_TF: Final[dict[str, str]] = dict(zip(TIMEFRAMES, ("R1", "R2", "R3"), strict=True))


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


def _max_leftover_trades(n_ticks: int, target_n_bars: int) -> float:
    """Circuit breaker de `ThresholdBarsCarry.leftover` (`src/data/bars.py`,
    `LeftoverOverflowError`) -- achado MEDIUM de AG-034 addendum
    (`audit/architecture_gaps_log.yaml`, 2026-08-16): threshold único
    global sob volume não-estacionário de 6+ anos de histórico, sem teto
    pro leftover crescer sob um sub-período de liquidez muito mais baixa
    que a média calibrada. `n_ticks/target_n_bars` (mesma quantidade que
    já calibra `exp_num_ticks_init` em `_build_tick_imbalance_config`,
    linhas acima) é a média de trades por barra MEDIDA nesta janela/
    símbolo/TF -- Regra Zero (`CLAUDE.md`) proíbe estipular uma contagem
    absoluta de trades; o teto é DERIVADO desse dado real, multiplicado
    por `bars_threshold_leftover_safety_multiplier` (constants.yaml,
    classe C, `ASSUMED` -- margem de segurança generosa, não uma
    contagem, mesmo padrão de `bars_streaming_chunk_days`/`m2_duckdb_
    memory_limit_gb`, guardrails desta mesma família)."""
    # target_n_bars > 0 garantido pelo caller (_target_n_bars).
    avg_trades_per_bar = float(n_ticks) / target_n_bars  # noqa: unguarded-ratio
    safety_mult = float(load_data_constant("bars_threshold_leftover_safety_multiplier"))
    if safety_mult <= 0:
        raise ValueError(
            "bars_threshold_leftover_safety_multiplier precisa ser > 0, constants.yaml tem "
            f"{safety_mult}"
        )
    return avg_trades_per_bar * safety_mult


def _build_trades_dependent_bars(
    symbol: str,
    tf: str,
    chunks: list[tuple[date, date]],
    *,
    dollar_threshold: float,
    volume_threshold: float,
    tib_config: TickImbalanceBarsConfig,
    max_leftover_trades: float,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """2ª passada: relê os mesmos chunks e alimenta os 3 acumuladores de
    barra (`dollar`/`volume`/`tick_imbalance`) num loop só -- 1x de E/S por
    chunk aqui, não 3x (os 3 tipos compartilham o mesmo chunk já carregado
    em memória, só o estado carregado entre chunks é que é por tipo). Log
    por chunk -- ver docstring de `_scan_trades_totals` pro achado que
    motivou (run real travado 16h+ sem nenhum log intermediário).

    `max_leftover_trades` (`_max_leftover_trades`, ver docstring lá) é o
    circuit breaker de `ThresholdBarsCarry.leftover` -- mesmo teto pros
    dois acumuladores dollar/volume (`LeftoverOverflowError` propaga pro
    chamador de `compute_trades_dependent_bars_for_symbol_tf`, achado
    MEDIUM de AG-034 addendum). `dollar_carry.leftover_trade_count`/
    `volume_carry.leftover_trade_count` logados por chunk abaixo -- achado
    MEDIUM irmão: "nenhum sinal diagnóstico pro crescimento de
    `leftover`", mesma disciplina de `tib_bars_closed` já existente."""
    dollar_carry = dollar_bars_carry(
        threshold=dollar_threshold, max_leftover_trades=max_leftover_trades
    )
    volume_carry = volume_bars_carry(
        threshold=volume_threshold, max_leftover_trades=max_leftover_trades
    )
    tib_carry = tick_imbalance_bars_carry(tib_config)

    throttle = _duckdb_throttle()
    n_chunks = len(chunks)
    for i, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        chunk = lake.query_agg_trades(
            symbol,
            chunk_start,
            chunk_end,
            duckdb_memory_limit_gb=throttle.memory_limit_gb,
            duckdb_threads=throttle.threads,
        )
        if not chunk.is_empty():
            threshold_bars_step(dollar_carry, chunk)
            threshold_bars_step(volume_carry, chunk)
            tick_imbalance_bars_step(tib_carry, chunk)
        logger.info(
            "analysis.m2_worker.build_chunk_done",
            symbol=symbol,
            tf=tf,
            chunk=i,
            n_chunks=n_chunks,
            chunk_start=str(chunk_start),
            chunk_end=str(chunk_end),
            n_trades=chunk.height,
            dollar_leftover_trades=dollar_carry.leftover_trade_count,
            volume_leftover_trades=volume_carry.leftover_trade_count,
            tib_bars_closed=len(tib_carry.bar_frames),
        )

    return (
        threshold_bars_finish(dollar_carry),
        threshold_bars_finish(volume_carry),
        tick_imbalance_bars_finish(tib_carry),
    )


def _log_task_done(metrics: BarComparisonMetrics) -> None:
    logger.info(
        "analysis.m2_worker.task_done",
        symbol=metrics.symbol,
        tf=metrics.tf,
        resolution_id=metrics.resolution_id,
        bar_type=metrics.bar_type,
        n_bars=metrics.n_bars,
        jarque_bera_pvalue=metrics.jarque_bera_pvalue,
        ljung_box_r_pvalue=metrics.ljung_box_r_pvalue,
        avg_uniqueness=metrics.avg_uniqueness,
    )


def compute_time_bar_for_symbol(
    symbol: str,
    *,
    time_stop_ms: int,
    ljung_box_lags: int,
    start: str | None = None,
    end: str | None = None,
) -> list[BarComparisonMetrics]:
    """Núcleo de IO pro tipo `"time"` -- só `klines_1m`, leve, roda numa
    task própria pra não competir por memória com as tasks de `aggTrades`
    (ver `compute_trades_dependent_bars_for_symbol_tf`). Itera
    `TIMEFRAMES` internamente (mesmo padrão de `m3_timeframe_choice.py::
    compute_timeframe_choice_for_symbol`) -- barato o bastante pra não
    valer a pena fatiar mais, ver docstring de `m2_bar_comparison.py`.

    `start`/`end` (ISO date, opcionais) sobrescrevem `SYMBOL_START_DATE`/
    `END_DATE` pra ESTE símbolo -- suporte a janelas específicas
    (AG-034/discovery de período 2026-08-16), não muda o comportamento
    default (histórico completo) quando omitidos.

    Blindada por TF, não só por símbolo (achado de auditoria 2026-08-15,
    `project_assurance`: versão anterior não tinha proteção NENHUMA aqui)
    -- uma falha de `duckdb.OutOfMemoryException` num TF vira `NaN` só
    pra esse TF, sem perder os outros 2 já computados nesta mesma task."""
    resolved_start = start if start is not None else SYMBOL_START_DATE[symbol]
    resolved_end = end if end is not None else END_DATE
    results: list[BarComparisonMetrics] = []
    for tf in TIMEFRAMES:
        resolution_id = RESOLUTION_ID_BY_TF[tf]
        try:
            bars = _query_baseline(symbol, tf, start=resolved_start, end=resolved_end)
        except duckdb.OutOfMemoryException as exc:
            logger.warning(
                "analysis.m2_worker.time_baseline_failed", symbol=symbol, tf=tf, error=repr(exc)
            )
            metrics = _nan_metrics(symbol, tf, resolution_id, "time", 0, 0)
            _log_task_done(metrics)
            results.append(metrics)
            continue
        metrics = compute_bar_statistics(
            symbol,
            tf,
            resolution_id,
            "time",
            bars,
            time_stop_ms=time_stop_ms,
            ljung_box_lags=ljung_box_lags,
        )
        _log_task_done(metrics)
        results.append(metrics)
    return results


def compute_trades_dependent_bars_for_symbol_tf(
    symbol: str,
    tf: str,
    *,
    time_stop_ms: int,
    ljung_box_lags: int,
    start: str | None = None,
    end: str | None = None,
) -> list[BarComparisonMetrics]:
    """Constrói `dollar`/`volume`/`tick_imbalance` bars pra 1 (símbolo, TF)
    em STREAMING -- task AUTOCONTIDA, uma por combinação de
    `run_and_save_bar_comparison_report` (achado de auditoria 2026-08-15:
    com o loop de TF DENTRO da task -- desenho anterior -- `n_tasks=10`
    travava a concorrência real em `min(os.cpu_count()=12, n_tasks=10)=10`,
    e os 3 TFs de cada símbolo pesado rodavam em SÉRIE dentro do mesmo
    processo; fatiar por `(symbol, tf)` sobe o teto real pra 12, limitado
    só por `os.cpu_count()`, paralelizando a parte cara -- construção de
    barra, inclui o loop sequencial de tick imbalance -- entre os 3 TFs).

    `aggTrades` de BTCUSDT/ETHUSDT são 27GB/20GB *comprimidos* em disco,
    não cabem em memória de uma vez em NENHUMA concorrência (nem 1
    processo sozinho) -- daí o streaming em 2 passadas por chamada.

    **Custo aceito conscientemente:** a 1ª passada (`_scan_trades_totals`,
    totais de $/unidades/ticks) NÃO depende de TF -- mas como cada task
    agora é autocontida (sem orquestração em 2 estágios, sem IPC entre
    processos pra compartilhar `totals`), ela roda de novo aqui a cada
    chamada, 3x por símbolo no total (1x por TF) em vez de 1x. Isso é
    aceitável porque a 1ª passada é só soma (`price*quantity`/`quantity`/
    contagem), sem o loop sequencial de tick imbalance que domina o custo
    da 2ª -- repetir a parte barata pra paralelizar de verdade a parte
    cara é a troca certa aqui, mesmo racional de "E/S barata por memória"
    já usado no desenho de streaming original (ver docstring de
    `m2_bar_comparison.py`).

    Blindada contra `duckdb.OutOfMemoryException` de forma independente em
    CADA UMA das 3 chamadas de IO (totais, baseline pro `target_n_bars`,
    construção -- achado de auditoria 2026-08-15, `project_assurance`: a
    versão anterior deixava a chamada de baseline fora das duas blindagens
    existentes, quebrando a garantia abaixo pra essa chamada especificamente)
    -- mesma disciplina FCN de `m2_stats._run_adfuller`/`_nan_metrics`: uma
    falha nesta (symbol, tf) vira `NaN` só pros 3 `bar_types` desta
    combinação, não derruba as outras 14 tasks do batch.

    `start`/`end` (ISO date, opcionais) sobrescrevem `SYMBOL_START_DATE`/
    `END_DATE` -- mesmo suporte de `compute_time_bar_for_symbol`, ver ali
    pra motivação (AG-034/discovery de período 2026-08-16).

    **`tf` aqui é só o parâmetro de CALIBRAÇÃO** (AG-042, 2026-08-16) --
    decide qual baseline de `klines_1m` define `target_n_bars` (linha
    acima) e, por tabela, `dollar_threshold`/`volume_threshold`/
    `tib_config`. NÃO é a identidade do resultado: os 3 `bar_type` desta
    função (dollar/volume/tick_imbalance) não têm 15/30/60 minutos em
    lugar nenhum -- `resolution_id = RESOLUTION_ID_BY_TF[tf]` (R1/R2/R3) é
    o rótulo honesto, calibrado só pra dar o mesmo nº de barras que o
    baseline de TEMPO deu nesta janela. Ler `resolution_id="R1"` como "15
    minutos" pra estes `bar_type` é exatamente a "mentira operacional"
    que motivou AG-042 (docs/refactor_dollar_bar_canonico.md §3.5)."""
    resolution_id = RESOLUTION_ID_BY_TF[tf]
    resolved_start = start if start is not None else SYMBOL_START_DATE[symbol]
    resolved_end = end if end is not None else END_DATE
    chunk_days = int(load_data_constant("bars_streaming_chunk_days"))
    chunks = _date_chunks(resolved_start, resolved_end, chunk_days=chunk_days)

    try:
        totals = _scan_trades_totals(symbol, tf, chunks)
    except duckdb.OutOfMemoryException as exc:
        logger.warning(
            "analysis.m2_worker.trades_totals_failed", symbol=symbol, tf=tf, error=repr(exc)
        )
        return [
            _nan_metrics(symbol, tf, resolution_id, bar_type, 0, 0)
            for bar_type in _TRADES_DEPENDENT_BAR_TYPES
        ]
    if totals.n_ticks == 0:
        raise ValueError(
            f"aggTrades vazio para {symbol} no período "
            f"{resolved_start}..{resolved_end} -- não dá pra calibrar bars"
        )

    try:
        baseline = _query_baseline(symbol, tf, start=resolved_start, end=resolved_end)
        target_n_bars = _target_n_bars(symbol, tf, baseline, start=resolved_start, end=resolved_end)
    except duckdb.OutOfMemoryException as exc:
        logger.warning(
            "analysis.m2_worker.trades_baseline_failed", symbol=symbol, tf=tf, error=repr(exc)
        )
        return [
            _nan_metrics(symbol, tf, resolution_id, bar_type, 0, 0)
            for bar_type in _TRADES_DEPENDENT_BAR_TYPES
        ]
    dollar_threshold = totals.total_dollar / target_n_bars  # noqa: unguarded-ratio -- target_n_bars>0 acima
    volume_threshold = totals.total_volume / target_n_bars  # noqa: unguarded-ratio -- target_n_bars>0 acima
    tib_config = _build_tick_imbalance_config(totals.n_ticks, target_n_bars)
    max_leftover_trades = _max_leftover_trades(totals.n_ticks, target_n_bars)

    try:
        dollar_df, volume_df, tib_df = _build_trades_dependent_bars(
            symbol,
            tf,
            chunks,
            dollar_threshold=dollar_threshold,
            volume_threshold=volume_threshold,
            tib_config=tib_config,
            max_leftover_trades=max_leftover_trades,
        )
    except duckdb.OutOfMemoryException as exc:
        logger.warning(
            "analysis.m2_worker.trades_build_failed", symbol=symbol, tf=tf, error=repr(exc)
        )
        return [
            _nan_metrics(symbol, tf, resolution_id, bar_type, 0, 0)
            for bar_type in _TRADES_DEPENDENT_BAR_TYPES
        ]

    bars_by_type = {"dollar": dollar_df, "volume": volume_df, "tick_imbalance": tib_df}
    results: list[BarComparisonMetrics] = []
    for bar_type in _TRADES_DEPENDENT_BAR_TYPES:
        metrics = compute_bar_statistics(
            symbol,
            tf,
            resolution_id,
            bar_type,
            bars_by_type[bar_type],
            time_stop_ms=time_stop_ms,
            ljung_box_lags=ljung_box_lags,
        )
        _log_task_done(metrics)
        results.append(metrics)
    return results


def warm_numba_cache_in_worker() -> None:
    """`ProcessPoolExecutor(initializer=...)` -- roda 1x por worker, na
    criação do processo, ANTES de qualquer task ser aceita.

    **Correção de proveniência sobre uma citação anterior (achado de
    auditoria `project_assurance`, 2026-08-15, WebFetch da issue real):**
    `numba/numba#8755` ("ensure_cache_path() for Windows directory
    permission check may cause infinite loop") documenta um hang de
    **PROCESSO ÚNICO** -- reprodução é "toggle the privileges of the
    __pycache__ folder" e o script trava sozinho, sem nenhuma menção a
    concorrência entre processos como gatilho. A caracterização anterior
    ("múltiplos workers disputando a 1ª compilação ao mesmo tempo") é
    extrapolação própria razoável (mais workers tocando o mesmo diretório
    de cache aumenta a superfície de exposição ao mesmo bug de permissão),
    NÃO algo que a issue em si confirma. Se a causa real for permissão
    (não corrida), compilar aqui não ELIMINA o hang -- move ele pra mais
    cedo (na criação do worker, mais fácil de diagnosticar/atribuir a um
    PID específico do que no meio de uma task real) e o mantém isolado por
    processo (1 worker travado por permissão não impede os outros 11 de
    seguir). Mitigação defensiva continua válida por esse motivo -- só a
    causa raiz citada foi corrigida. Reforça também os env vars de BLAS
    (2ª linha de defesa -- não substitui o bloco no topo do módulo, que
    roda mais cedo)."""
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("POLARS_MAX_THREADS", "1")

    # literais abaixo são só parâmetros de dado sintético pra exercitar o
    # compilador JIT 1x -- não são constante de domínio, não entram em
    # constants.yaml (mesma classe do # noqa: magic-number já usado em
    # src/validation/leakage.py pra epsilon numérico)
    n = 500
    rng = np.random.default_rng(seed=0)
    price = 60_000.0 + rng.normal(0.0, 10.0, n).cumsum()  # noqa: magic-number -- dado sintético, não domínio
    quantity = rng.uniform(0.001, 1.0, n)  # noqa: magic-number -- dado sintético, não domínio
    transact_time = np.arange(n, dtype=np.int64) * 100
    is_buyer_maker = rng.uniform(size=n) > 0.5
    chunk = pl.DataFrame(
        {
            "transact_time": transact_time,
            "price": price,
            "quantity": quantity,
            "is_buyer_maker": is_buyer_maker,
        }
    )
    config = TickImbalanceBarsConfig(
        num_prev_bars=3,
        expected_imbalance_window=100,
        exp_num_ticks_init=50.0,  # noqa: magic-number -- dado sintético, não domínio
        exp_num_ticks_min=10.0,  # noqa: magic-number -- dado sintético, não domínio
        exp_num_ticks_max=200.0,  # noqa: magic-number -- dado sintético, não domínio
    )
    carry = TickImbalanceBarsCarry(config=config)

    t0 = time.perf_counter()
    tick_imbalance_bars_step(carry, chunk)
    elapsed = time.perf_counter() - t0

    logger.info(
        "analysis.m2_worker.numba_cache_warm",
        pid=os.getpid(),
        elapsed_s=round(elapsed, 3),
        n_bars_closed=len(carry.bar_frames),
    )
