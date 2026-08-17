"""M2 — comparação de tipo de barra (PRD_V4_1.md §3.2, linhas 382-388):
"Candidatos: tempo (baseline) · dollar bars · volume bars · tick imbalance
bars, calibradas para a mesma frequência média. Métricas: Jarque-Bera ·
curtose · Ljung-Box em `r` e `r²` · ADF · razão de amostra efetiva
(unicidade média com `time_stop` equivalente em relógio)." Zero trials —
medição, não busca.

**Decisão do Manager (2026-08-16): dollar bars é o vencedor de M2**,
travada em `config/constants.yaml::canonical_bar_type`. Medido sobre 5
janelas de regime deliberadamente distintas (LUNA/UST 2022-05, FTX
2022-11, crypto winter 2023-06, ETF/halving 2024-03, recente 2026-07 —
não o histórico completo, ver AG-034 abaixo) — dollar bars venceu tempo
(baseline) em 4/5 janelas + no pooled, em toda métrica exceto ADF
(empate, ADF passa 100% em qualquer tipo de barra testado). `tick_imbalance`
falhou em 5/5 janelas por uma causa raiz confirmada (AG-035, aberto) —
calibração da harness quebrada, não evidência de que o método seja ruim
pra este universo de ativos; a vitória de dollar sobre TEMPO não depende
disso. Resultado completo, por janela e pooled: artefato "Biblioteca de
Testes" (aba M2). Reprocessamento do pipeline (Feature/Regime/Label
Engine) pra grade dollar-bar **não iniciado** — decisão registrada, não
deployment.

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

**`resolution_id` substitui "M15/M30/H1" como identidade do resultado
(AG-042, 2026-08-16, docs/refactor_dollar_bar_canonico.md §3.5, Opção D).**
`tf`/`TIMEFRAMES` continuam existindo -- ainda é o parâmetro real de
CALIBRAÇÃO (decide qual baseline de `klines_1m` define `target_n_bars` pra
cada `(symbol, tf)`, ver parágrafo acima). Mas "M15/30/H1" nunca foi a
identidade REAL de `dollar`/`volume`/`tick_imbalance` -- essas barras não
têm relógio nenhum, só um nº de barras calibrado pra bater com o baseline
de tempo. Cada linha do payload carrega os dois campos agora:
`resolution_id` (R1/R2/R3, `m2_worker.RESOLUTION_ID_BY_TF`) é a identidade
honesta; `tf` é só o rótulo do baseline usado na calibração. Pra
`bar_type="time"` os dois significam a mesma coisa (R1 É 15 minutos); pra
qualquer outro `bar_type`, só `resolution_id` deve ser lido como
identidade -- ler `tf` como duração de relógio nesse caso é a "mentira
operacional" que motivou este achado.

**Desmembrado em 3 arquivos (2026-08-15) — brainstorm próprio + validação
por auditoria externa, Opção 3: cortar por FRONTEIRA DE PROCESSO, não por
camada nem por estágio de pipeline.** `src.analysis.m2_stats` — núcleo
estatístico puro (`BarComparisonMetrics`, `compute_bar_statistics`, JB/
curtose/Ljung-Box/ADF), zero IO. `src.analysis.m2_worker` — TUDO que roda
DENTRO de 1 processo filho do `ProcessPoolExecutor` abaixo: calibração +
construção de barra via streaming de `aggTrades`
(`compute_time_bar_for_symbol`, `compute_trades_dependent_bars_for_
symbol_tf`, e o `initializer` `warm_numba_cache_in_worker`), incluindo o
bloco de env vars de BLAS que precisa rodar antes de qualquer import
pesado. Este arquivo (`m2_bar_comparison.py`) fica só com orquestração:
`ProcessPoolExecutor`, fan-out, montagem e persistência do relatório —
mantém esta docstring narrativa completa por ser o ponto de entrada real
(`uv run python -m src.analysis.m2_bar_comparison`); `m2_stats.py`/
`m2_worker.py` têm docstrings curtas que apontam de volta pra cá.
Razão da fronteira: `__module__` de uma função é o módulo onde ela foi
DEFINIDA — as duas funções submetidas ao pool, definidas agora em
`m2_worker.py` e importadas aqui, resolvem `__module__` como
`"src.analysis.m2_worker"` (caminho de import absoluto de verdade) em vez
de `"__main__"` (que dependia da maquinaria de reconstrução do
`multiprocessing.spawn` no Windows, funcionando só porque a invocação é
sempre via `-m`). Ver `PLANO_MESTRE_PRINCE2.md` §15 pro registro formal.

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
calibração (`m2_worker.py`) e comparação/relatório (aqui) tem dimensão de
TF. O baseline usa `lake.query_bars` (mesma fonte de M1/M3) pra ficar
consistente com o resto da Camada 1.

**Calibração — mesma frequência média que o baseline DAQUELE TF, medida
não suposta.** `target_n_bars` = nº de barras do baseline NO TF sendo
medido, no mesmo período; `threshold` de dollar/volume bars = volume
total (em $ ou unidades) dividido por `target_n_bars`; `exp_num_ticks_init`
de tick imbalance bars = nº total de ticks dividido por `target_n_bars`
(mesma lógica: barra "típica" do TIB deveria consumir, em média, tantos
ticks quantos a barra daquele TF consome em relógio). O volume
total/nº de ticks (`m2_worker._scan_trades_totals`) NÃO depende de TF — é
somado 1x por símbolo e reusado nos 3 TFs dentro de cada chamada de
`compute_trades_dependent_bars_for_symbol_tf`; só o `target_n_bars` (e
portanto o `threshold` calibrado) muda por TF.

**"Razão de amostra efetiva" reusa `src.labels.weights.
compute_concurrency_and_uniqueness`** (produção real, testada, mesma
função que calcula `sample_weight` do Label Engine) — não uma
reimplementação; chamada de dentro de `m2_stats.compute_bar_statistics`,
não aqui. `t0` = `close_time` de cada barra, `t1` = `close_time +
time_stop_bars×15min`. **`time_stop_ms` é FIXO, calculado 1x via
`step_ms("15m")` — nunca recalculado por TF.** `time_stop_bars=32`
(`constants.yaml`) é justificado como "uma janela de funding"
(32×15min = 8h exatas) — é uma constante em UNIDADES DE BARRA DE 15M, não
um nº de barras TF-agnóstico. Recalcular como `time_stop_bars × step_ms(tf)`
mudaria o horizonte de "amostra efetiva" a cada TF (16h em 30m, 32h em
1h) — exatamente a classe de erro silencioso de unidade que
`PLANO_MESTRE_PRINCE2.md` §15.6 item 1 já tinha previsto pra este módulo.
`TIME_STOP_REFERENCE_TF` abaixo existe só pra deixar essa invariância
explícita, não é o TF sendo medido em cada iteração.

**Memória domina o desenho, não CPU.** Achado de auditoria (2026-08-15,
medido antes de mudar qualquer coisa): `aggTrades` de BTCUSDT/ETHUSDT são
27GB/20GB *comprimidos* em disco, descompactado como `DataFrame` tipado,
isso não cabe na RAM inteira de uma vez, em NENHUMA concorrência (nem 1
processo sozinho). `m2_worker.compute_trades_dependent_bars_for_symbol_tf`
processa cada `(símbolo, TF)` em streaming, chunk-a-chunk (`bars_streaming_
chunk_days` dias por vez — ver `src.data.bars`, que mantém só o estado
necessário entre chunks, nunca o histórico inteiro), em 2 passadas: 1ª só
soma totais pra calibrar `threshold`/`exp_num_ticks_init`, 2ª constrói as
barras de fato.
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
mesmo com cada query individual pequena. `m2_worker._duckdb_throttle()`
aplica `SET memory_limit`/`SET threads` explícitos (`constants.yaml::m2_
duckdb_memory_limit_gb`/`m2_duckdb_threads`, derivados de `28GB livres /
10 tasks` com margem de segurança) em toda chamada a `lake.query_bars`/
`lake.query_agg_trades` — `lake.py` continua com os defaults do DuckDB
pra todo resto do repo (parâmetros opcionais, `None` por padrão, zero
mudança de comportamento fora daqui).

**Achado externo (auditoria, 2026-08-15) — cache Numba concorrente sob
`spawn` no Windows.** `@numba.njit(cache=True)` em `src.data.bars.
_tick_imbalance_loop` tem um risco documentado e confirmado
(`numba/numba#8755`): `ensure_cache_path()` pode entrar em loop infinito
no Windows checando gravabilidade do diretório de cache, se múltiplos
processos disputarem a 1ª compilação/checagem ao mesmo tempo. Corrigido
estruturalmente, não por convenção: `ProcessPoolExecutor(initializer=
m2_worker.warm_numba_cache_in_worker)` força cada worker a compilar
isoladamente, na criação do processo, antes de aceitar qualquer task —
ver `run_and_save_bar_comparison_report` abaixo.

**Paralelismo fatiado por `(symbol, tf)` na parte pesada, não por
símbolo só** (`run_and_save_bar_comparison_report`, `ProcessPoolExecutor`
dimensionado por `os.cpu_count()`, `len(symbols) × (1 + len(TIMEFRAMES))`
= 20 tasks). `tick_imbalance_bars_step` é sequencial dentro de cada
processo (ver docstring de `src.data.bars`), mas cada `(symbol, tf)`
processa em paralelo com os outros 14, teto real de 12 concorrentes
(`os.cpu_count()`), cada um com memória limitada ao tamanho de 1 chunk,
não ao histórico inteiro. **2º achado de desenho (2026-08-15):** a
1ª versão (loop de TF DENTRO de cada task pesada, `n_tasks=10`) travava
a concorrência real em `min(12, 10)=10` e rodava os 3 TFs de cada
símbolo em SÉRIE — deixando núcleos ociosos.
`m2_worker.compute_trades_dependent_bars_for_symbol_tf` (autocontida, 1
por `(symbol, tf)`) corrige isso ao custo de refazer a 1ª passada
(totais, barata) 3x por símbolo em vez de 1x — troca deliberada, ver
docstring da função. `m2_worker.compute_time_bar_for_symbol` continua
leve e itera os 3 TFs internamente (não vale a pena fatiar mais uma parte
já barata). Ponto de entrada manual, não é testado de ponta a ponta no
pytest (mesma convenção de M1/M3/M6 — IO real fica fora da suíte
automatizada; a propriedade crítica de streaming↔lote é testada em
`test_data_bars.py`, que não depende de IO real)."""

from __future__ import annotations

import os

# m2_worker seta os env vars de BLAS (OMP_NUM_THREADS/etc) na 1ª linha de
# código do módulo -- importar `m2_worker` ANTES de qualquer numpy/duckdb/
# polars/scipy/statsmodels TAMBÉM neste arquivo garante que isso rode cedo
# o bastante aqui também, já que o Windows (spawn) reimporta
# `m2_bar_comparison.py` inteiro como `__main__` em cada worker. Mesmo
# assim, o bloco abaixo é DUPLICADO (idempotente) como defesa redundante
# -- nenhum dos dois arquivos depende da ordem de import do outro.
from src.analysis.m2_worker import (
    RESOLUTION_ID_BY_TF,
    compute_time_bar_for_symbol,
    compute_trades_dependent_bars_for_symbol_tf,
    warm_numba_cache_in_worker,
)

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("POLARS_MAX_THREADS", "1")

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import orjson
import structlog

from src.analysis.m2_stats import BAR_TYPES, BarComparisonMetrics, _nan_metrics
from src.analysis.volatility_comparison import SYMBOL_START_DATE, TIMEFRAMES
from src.core.provenance import report_provenance
from src.data._constants import load_constant as load_data_constant
from src.data.resample import step_ms
from src.risk._constants import load_constant as load_risk_constant

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "m2_bar_comparison_report.json"

#: TF usado SÓ pra calcular `time_stop_ms` (ver docstring do módulo --
#: `time_stop_bars=32` é "1 janela de funding" em unidades de barra de
#: 15m, fixo independente de qual TF está sendo medido na iteração de
#: `TIMEFRAMES`). Não é o baseline de bar comparison -- esse é `tf`,
#: iterado dentro de `m2_worker.compute_time_bar_for_symbol`/
#: `compute_trades_dependent_bars_for_symbol_tf`.
TIME_STOP_REFERENCE_TF: Final[str] = "15m"


def compute_bar_comparison_for_symbol(
    symbol: str, *, start: str | None = None, end: str | None = None
) -> list[BarComparisonMetrics]:
    """Conveniência pra depuração manual de UM símbolo, sequencial -- o
    caminho de produção real é `run_and_save_bar_comparison_report`, que
    roda a task leve (`"time"`, 1/símbolo) e as 3 tasks pesadas
    (`compute_trades_dependent_bars_for_symbol_tf`, 1 por TF, autocontidas)
    em paralelo entre TODAS as combinações -- ver docstring do módulo.
    `start`/`end` opcionais, mesmo suporte de janela -- ver docstring de
    `run_and_save_bar_comparison_report`."""
    time_stop_bars_n = int(load_risk_constant("time_stop_bars"))
    time_stop_ms = time_stop_bars_n * step_ms(TIME_STOP_REFERENCE_TF)
    ljung_box_lags = int(load_data_constant("bars_comparison_ljung_box_lags"))
    time_metrics = compute_time_bar_for_symbol(
        symbol, time_stop_ms=time_stop_ms, ljung_box_lags=ljung_box_lags, start=start, end=end
    )
    trades_metrics: list[BarComparisonMetrics] = []
    for tf in TIMEFRAMES:
        trades_metrics.extend(
            compute_trades_dependent_bars_for_symbol_tf(
                symbol,
                tf,
                time_stop_ms=time_stop_ms,
                ljung_box_lags=ljung_box_lags,
                start=start,
                end=end,
            )
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


def _build_payload(
    results_by_symbol: dict[str, dict[tuple[str, str], BarComparisonMetrics]],
    symbols: tuple[str, ...],
    *,
    partial: bool,
) -> dict[str, Any]:
    """Monta o payload achatado (3 TF × 4 bar_types por símbolo) --
    qualquer célula `(symbol, tf, bar_type)` ainda não presente em
    `results_by_symbol` (task não terminou ainda, OU terminou com falha
    não tratada -- achado de auditoria 2026-08-15, ver
    `run_and_save_bar_comparison_report`) vira `NaN` explícito via
    `_nan_metrics`, nunca um `KeyError` nem uma ausência silenciosa --
    mesma disciplina FCN do resto do módulo. `partial=True` marca o
    payload como checkpoint intermediário (chamado a cada task concluída,
    não só no fim) -- `partial=False` só depois que TODAS as tasks
    resolveram (com sucesso ou falha registrada)."""
    return {
        **report_provenance(),
        "partial": partial,
        "timeframes": list(TIMEFRAMES),
        "bar_types": list(BAR_TYPES),
        "symbols": {
            symbol: [
                asdict(
                    results_by_symbol[symbol][(tf, bar_type)]
                    if (tf, bar_type) in results_by_symbol[symbol]
                    else _nan_metrics(symbol, tf, RESOLUTION_ID_BY_TF[tf], bar_type, 0, 0)
                )
                for tf in TIMEFRAMES
                for bar_type in BAR_TYPES
            ]
            for symbol in sorted(symbols)
        },
    }


def run_and_save_bar_comparison_report(
    *,
    symbols: tuple[str, ...] = tuple(SYMBOL_START_DATE),
    dest_path: Path | None = None,
    max_workers: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> Path:
    """Ponto de entrada MANUAL -- `len(symbols) × (1 + len(TIMEFRAMES))`
    tasks (20, com os 5 ativos × 3 TFs padrão): 1 task leve por símbolo
    (`"time"`, só `klines_1m`, itera os 3 TFs internamente -- barato,
    não precisa fatiar mais) + 1 task pesada por `(symbol, tf)`
    (`compute_trades_dependent_bars_for_symbol_tf`, autocontida, 15 no
    total), ambas definidas em `m2_worker.py` (ver docstring do módulo
    pra por quê essa fronteira de arquivo importa pro `spawn` do
    Windows). Achado de auditoria (2026-08-15): a versão anterior (loop de
    TF DENTRO de cada task pesada, `n_tasks=10`) travava a concorrência
    real em `min(os.cpu_count()=12, n_tasks=10)=10` e rodava os 3 TFs de
    cada símbolo em SÉRIE -- fatiar por `(symbol, tf)` sobe o teto real
    pra 12 (agora limitado só por `os.cpu_count()`, não mais por
    `n_tasks`), paralelizando a parte cara (construção de barra) entre os
    3 TFs, ao custo de cada task pesada refazer a 1ª passada (totais,
    barata -- ver docstring de `m2_worker.compute_trades_dependent_bars_
    for_symbol_tf`) sozinha. `m2_duckdb_memory_limit_gb`/`m2_duckdb_threads`
    continuam válidos sem re-derivação -- `12 × 2,0GB = 24GB`, ainda
    dentro dos ~28GB livres medidos (a constante já foi derivada com
    margem, o teto real de 12 sempre foi menor que o assumido na
    provenance original de 10). `initializer=warm_numba_cache_in_worker`
    fecha a janela de compilação Numba concorrente (achado de auditoria
    externa, ver docstring do módulo). Persiste o relatório, atômico (B29).

    **Isolamento de falha por task + checkpoint incremental (achado de
    auditoria `project_assurance`, 2026-08-15, HIGH -- confirmado por 3
    revisores independentes).** Versão anterior só capturava
    `duckdb.OutOfMemoryException`, e só DENTRO de cada task -- qualquer
    outra exceção (`ValueError` de `_target_n_bars`/`totals.n_ticks==0`,
    `MemoryError` de numpy, bug de programação) subia sem tratamento
    nenhum até este loop, abortava o `with ProcessPoolExecutor(...)`
    inteiro e descartava os resultados de TODAS as outras tasks já
    concluídas -- contradizendo a garantia que a docstring de
    `compute_trades_dependent_bars_for_symbol_tf` já fazia. Agora: cada
    `future.result()` roda em `try/except Exception` próprio (linha de
    defesa mais externa, complementar às blindagens específicas de OOM
    dentro de `m2_worker.py` -- não substitui, generaliza); o payload é
    reescrito atomicamente a CADA task resolvida (sucesso ou falha), não
    só no fim -- dado o histórico real de runs multi-hora e falhas
    tardias já observadas nesta sessão (OOM 3x, travamento de 16h+), 1
    falha na task 17/20 agora perde só a célula dela, não as 19 anteriores
    já persistidas em disco.

    **`start`/`end` (ISO date, opcionais, AG-034/discovery de período
    2026-08-16):** sobrescrevem `SYMBOL_START_DATE`/`END_DATE` pra TODOS os
    `symbols` desta chamada -- pensado pra rodar UMA VEZ POR JANELA
    escolhida (Manager passa `dest_path` diferente por janela), nunca pra
    concatenar janelas descontínuas num único relatório: ADF/Ljung-Box
    (`m2_stats.compute_bar_statistics`) assumem série CONTÍGUA -- juntar
    trechos de datas não-adjacentes introduziria quebras artificiais que
    corrompem os dois testes. Omitido (default), comportamento idêntico ao
    histórico completo de sempre -- não muda nada pra quem já chama sem
    esses argumentos.

    Chame manualmente: `uv run python -m src.analysis.m2_bar_comparison`."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    time_stop_bars_n = int(load_risk_constant("time_stop_bars"))
    time_stop_ms = time_stop_bars_n * step_ms(TIME_STOP_REFERENCE_TF)
    ljung_box_lags = int(load_data_constant("bars_comparison_ljung_box_lags"))

    n_tasks = len(symbols) * (1 + len(TIMEFRAMES))
    logger.info(
        "analysis.m2_bar_comparison.starting",
        n_symbols=len(symbols),
        n_timeframes=len(TIMEFRAMES),
        n_tasks=n_tasks,
        max_workers=workers,
    )

    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    results_by_symbol: dict[str, dict[tuple[str, str], BarComparisonMetrics]] = {
        symbol: {} for symbol in symbols
    }
    failed_tasks: list[tuple[str, str | None]] = []

    with ProcessPoolExecutor(
        max_workers=min(workers, n_tasks), initializer=warm_numba_cache_in_worker
    ) as executor:
        task_identity: dict[Any, tuple[str, str | None]] = {
            executor.submit(
                compute_time_bar_for_symbol,
                symbol,
                time_stop_ms=time_stop_ms,
                ljung_box_lags=ljung_box_lags,
                start=start,
                end=end,
            ): (symbol, None)
            for symbol in symbols
        }
        task_identity.update(
            {
                executor.submit(
                    compute_trades_dependent_bars_for_symbol_tf,
                    symbol,
                    tf,
                    time_stop_ms=time_stop_ms,
                    ljung_box_lags=ljung_box_lags,
                    start=start,
                    end=end,
                ): (symbol, tf)
                for symbol in symbols
                for tf in TIMEFRAMES
            }
        )

        for n_done, future in enumerate(as_completed(task_identity), start=1):
            symbol, tf = task_identity[future]
            try:
                for metrics in future.result():
                    results_by_symbol[symbol][(metrics.tf, metrics.bar_type)] = metrics
            # linha de defesa mais externa (ver docstring) -- não silenciosa,
            # registrada em failed_tasks + logger.error logo abaixo
            except Exception as exc:
                failed_tasks.append((symbol, tf))
                logger.error(
                    "analysis.m2_bar_comparison.task_failed",
                    symbol=symbol,
                    tf=tf,
                    n_done=n_done,
                    n_tasks=n_tasks,
                    error=repr(exc),
                )
            _atomic_write_json(_build_payload(results_by_symbol, symbols, partial=True), dest)
            logger.info(
                "analysis.m2_bar_comparison.checkpoint", n_done=n_done, n_tasks=n_tasks
            )

    if failed_tasks:
        logger.warning(
            "analysis.m2_bar_comparison.tasks_failed",
            n_failed=len(failed_tasks),
            n_tasks=n_tasks,
            failed=failed_tasks,
        )

    _atomic_write_json(_build_payload(results_by_symbol, symbols, partial=False), dest)
    logger.info(
        "analysis.m2_bar_comparison.done",
        n_symbols=len(results_by_symbol),
        n_failed=len(failed_tasks),
        dest=str(dest),
    )
    return dest


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "M2 -- comparação de tipo de barra. Sem argumentos, roda o histórico "
            "completo de sempre (comportamento idêntico a antes de 2026-08-16). "
            "--start/--end restringem a UMA janela (AG-034/discovery de período) "
            "-- rode 1x por janela, com --dest-path diferente cada vez; nunca "
            "concatena janelas descontínuas (ver docstring de "
            "run_and_save_bar_comparison_report)."
        )
    )
    parser.add_argument("--start", default=None, help="ISO date, ex. 2022-05-01")
    parser.add_argument("--end", default=None, help="ISO date, ex. 2022-05-31")
    parser.add_argument(
        "--dest-path",
        default=None,
        help="caminho do relatório -- default: experiments/m2_bar_comparison_report.json",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="default: os.cpu_count() (AG-034: considere reduzir)",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help=(
            "lista separada por vírgula (ex. BTCUSDT), default: os 5 símbolos "
            "(AG-034 addendum, 2026-08-16 -- reprocessamento real escalonado: "
            "1 símbolo por vez reduz concorrência efetiva sem mudar código, "
            "`run_and_save_bar_comparison_report` já aceitava `symbols=`, só "
            "não estava exposto na CLI)"
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    _args = _parse_cli_args()
    run_and_save_bar_comparison_report(
        symbols=tuple(_args.symbols.split(",")) if _args.symbols is not None else tuple(
            SYMBOL_START_DATE
        ),
        dest_path=Path(_args.dest_path) if _args.dest_path is not None else None,
        max_workers=_args.max_workers,
        start=_args.start,
        end=_args.end,
    )
