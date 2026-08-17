"""Utilitários de streaming/chunking sobre `aggTrades`/`klines_1m` — extraídos
de `src.analysis.m2_worker` (2026-08-16, validação de fiação de dollar bar
canônico, ver `src.data.build_dollar_bars`) porque as peças abaixo (chunking
de data, soma streaming de totais, query de baseline de tempo, contagem de
barra-alvo, throttle de DuckDB) nunca foram específicas de M2 — são concerns
genéricos de camada `data`: como varrer `aggTrades` em chunks sem estourar
RAM, como calibrar contra um baseline de barra de tempo. `src.analysis.
m2_worker` continua reexportando os nomes originais (`_date_chunks`/
`_TradesTotals`/`_scan_trades_totals`/`_query_baseline`/`_target_n_bars`/
`_duckdb_throttle`) como alias de compatibilidade (`from src.data.
_chunked_scan import X as _x`) — mesmo comportamento de sempre pra quem já
chama `m2_worker._date_chunks(...)` etc., inclusive em teste com
`monkeypatch.setattr(m2_worker, "_date_chunks", ...)`.

`duckdb_throttle` é uma 6ª peça (o pedido original que gerou este módulo
citava só 5 por nome) — movida junto porque `query_baseline`/
`scan_trades_totals` chamam ela internamente: deixá-la em `m2_worker.py`
criaria um import circular (`_chunked_scan` -> `m2_worker`), e `m2_worker`
(`src.analysis`) não pode ser importado por `src.data` de qualquer forma —
contrato `importlinter` "data não importa analysis" (`pyproject.toml`,
AG-034 addendum)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl
import structlog

from . import lake
from ._constants import load_constant

logger = structlog.get_logger(__name__)


def duckdb_throttle() -> lake.DuckDBThrottle:
    """`memory_limit`/`threads` por conexão DuckDB — achado de auditoria
    (2026-08-14): `duckdb.connect(":memory:")` sem `SET` explícito assume
    até ~80% da RAM TOTAL da máquina e várias threads por conexão, achando
    que é o único processo rodando nela. Sob `ProcessPoolExecutor` com até
    `os.cpu_count()` processos concorrentes (M2, `m2_bar_comparison.py`),
    cada um abrindo sua própria conexão via `lake._read_files`, o orçamento
    otimista somado estourava a RAM real disponível mesmo com
    `bars_streaming_chunk_days` já limitando o tamanho de CADA query
    individual — `duckdb.OutOfMemoryException` recorrente em produção
    (2026-08-14) não era sobre tamanho de query, era sobre orçamento
    default assumido por conexão × nº de conexões concorrentes.
    `constants.yaml::m2_duckdb_memory_limit_gb`/`m2_duckdb_threads` foram
    derivados com `28GB livres / 10 tasks` (provenance original) — nomes
    herdados de M2 (única chamadora até esta extração), mas o concern é
    genérico de camada `data`: qualquer leitura em streaming de
    `aggTrades`/`klines_1m` sob concorrência se beneficia do mesmo
    throttle, inclusive `src.data.build_dollar_bars` (validação de dollar
    bar, não M2).

    Sem loader genérico de propósito (achado de auditoria 2026-08-15,
    `check_constants_referenced.py`: um nome de constante passado por
    variável nunca é visto pelo scanner estático que procura
    `load_constant("literal")` no texto-fonte) — o literal fica direto
    aqui."""
    return lake.DuckDBThrottle(
        memory_limit_gb=float(load_constant("m2_duckdb_memory_limit_gb")),
        threads=int(load_constant("m2_duckdb_threads")),
    )


def query_baseline(symbol: str, tf: str, *, start: str, end: str) -> pl.DataFrame:
    throttle = duckdb_throttle()
    return lake.query_bars(
        symbol,
        tf,
        start,
        end,
        source="klines_1m",
        cast_prices=True,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )


def target_n_bars(symbol: str, tf: str, baseline: pl.DataFrame, *, start: str, end: str) -> int:
    n = baseline.height
    if n == 0:
        raise ValueError(
            f"baseline vazio para {symbol}/{tf} -- sem klines_1m no período "
            f"{start}..{end}, não dá pra calibrar dollar/volume/tick "
            "imbalance bars pra frequência média nenhuma"
        )
    return n


def date_chunks(start: str, end: str, *, chunk_days: int) -> list[tuple[date, date]]:
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
class TradesTotals:
    """Saída da 1ª passada (só somas, nunca materializa o histórico
    inteiro de uma vez -- ver `scan_trades_totals`)."""

    total_dollar: float = 0.0
    total_volume: float = 0.0
    n_ticks: int = 0


def scan_trades_totals(symbol: str, tf: str, chunks: list[tuple[date, date]]) -> TradesTotals:
    """1ª passada: só soma `price*quantity`/`quantity`/contagem por chunk,
    descartando cada chunk assim que somado -- memória limitada ao tamanho
    de 1 chunk (`bars_streaming_chunk_days`), nunca ao histórico inteiro.
    Necessária pra calibrar `threshold`/`exp_num_ticks_init` (§3.2 M2: "mesma
    frequência média que o baseline") ANTES de construir as barras de
    verdade na 2ª passada -- custo aceito conscientemente: cada dia de
    `aggTrades` é lido do disco 2x, não 1x, mas isso troca E/S (barata,
    arquivos locais) por memória (o recurso que realmente estourou, ver
    docstring do módulo).

    Achado de auditoria (2026-08-15): um run real de M2 travou 16h+ sem UMA
    linha de log -- o único log da task pesada acontecia depois de TODOS
    os chunks das duas passadas processados, então uma task presa em
    qualquer chunk era invisível até terminar ou ser morta manualmente.
    Log por chunk aqui -- não impede travamento, mas garante que apareça
    DENTRO de minutos, não depois de um dia inteiro (DoD de script novo:
    output autoexplicativo o suficiente pra diagnosticar sem re-rodar,
    CLAUDE.md). Usado por M2 (`m2_worker.compute_trades_dependent_bars_
    for_symbol_tf`) e pelo runner de validação de dollar bar
    (`src.data.build_dollar_bars.calibrate_dollar_threshold_for_validation`)."""
    totals = TradesTotals()
    throttle = duckdb_throttle()
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
            totals.total_dollar += float((chunk["price"] * chunk["quantity"]).sum())
            totals.total_volume += float(chunk["quantity"].sum())
            totals.n_ticks += chunk.height
        logger.info(
            "data.chunked_scan.totals_chunk_done",
            symbol=symbol,
            tf=tf,
            chunk=i,
            n_chunks=n_chunks,
            chunk_start=str(chunk_start),
            chunk_end=str(chunk_end),
            n_trades=chunk.height,
        )
    return totals
