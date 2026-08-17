"""Camada analítica fina sobre os parquets de `data/capacity/` (§1.2:
"Camada analítica: DuckDB sobre os arquivos. Nunca carregar `raw` inteiro em
memória.").

Duas podas acontecem antes de qualquer byte de parquet ser lido:

1. **Poda de arquivo** — os arquivos são um por dia (`yyyy-mm-dd.parquet`,
   exceto `funding`, mensal). O intervalo `[start, end]` pedido primeiro
   filtra a LISTA de arquivos pelo nome, em Python, e só os arquivos que
   intersectam o intervalo chegam ao DuckDB.
2. **Poda de predicado** — dentro dos arquivos selecionados, o DuckDB aplica
   o filtro de timestamp com pushdown a nível de row-group do Parquet, sem
   materializar o arquivo inteiro em memória Python antes de filtrar.

O resultado final vira um `pl.DataFrame` (`.pl()`) — é isso, e só isso, que
é materializado por completo; o "raw inteiro" nunca é.

Cobre as 4 fontes mais usadas (klines-like, agg_trades, metrics, funding).
Estender para uma 5ª fonte é: adicionar o `DatasetSchema` em `schemas.py` e,
se ela não for "um arquivo por dia", um caso em `_list_files_in_range`.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import polars as pl
import structlog

from . import schemas
from ._paths import capacity_symbol_dir
from ._util import cast_price_columns

logger = structlog.get_logger(__name__)

DateLike = date | datetime | str


@dataclass(frozen=True, slots=True)
class DuckDBThrottle:
    """`memory_limit_gb`/`threads` pra passar a `_read_files`/`query_bars`/
    `query_agg_trades` -- ver docstring de `_read_files` pro achado de
    auditoria que motiva (DuckDB assume até ~80% da RAM TOTAL por conexão
    sem `SET` explícito, sem coordenação entre processos concorrentes).
    Tipo compartilhado (achado de auditoria 2026-08-15, `project_assurance`:
    o mesmo bug corrigido só em M2 existia estruturalmente em M1/M3/
    `gk_vs_wilder_econ_regime_shift`/`volatility_operational_effect`, cada
    um sob `ProcessPoolExecutor` sem nenhum throttle -- em vez de cada
    módulo duplicar a própria dataclass, todos importam esta).

    **Sem loader genérico de propósito** (achado de auditoria 2026-08-15,
    `check_constants_referenced.py`: uma 1ª versão desta mudança tinha
    `load_duckdb_throttle(memory_limit_constant: str, ...)` recebendo o
    NOME da constante como parâmetro -- isso quebra a rastreabilidade
    estática do script, que escaneia por `load_constant("literal")` no
    texto-fonte de cada arquivo; um nome passado por variável nunca é
    visto). Cada módulo chama `load_constant(...)` com o literal direto
    E constrói `DuckDBThrottle(...)` ele mesmo -- mais repetição de 2
    linhas por módulo, mas cada constante continua auditável pelo script
    mecânico."""

    memory_limit_gb: float
    threads: int


def _as_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _list_day_files(symbol_dir: Path, start: date | None, end: date | None) -> list[Path]:
    files = []
    for p in sorted(symbol_dir.glob("*.parquet")):
        try:
            file_date = date.fromisoformat(p.stem)
        except ValueError:
            # arquivo fora do padrão yyyy-mm-dd.parquet — ignora (ex.: artefato solto na pasta)
            continue
        if start is not None and file_date < start:
            continue
        if end is not None and file_date > end:
            continue
        files.append(p)
    return files


def _list_month_files(symbol_dir: Path, start: date | None, end: date | None) -> list[Path]:
    files = []
    for p in sorted(symbol_dir.glob("*.parquet")):
        parts = p.stem.split("-")
        if len(parts) != 2:
            continue  # não é yyyy-mm.parquet
        try:
            year, month = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        month_start = date(year, month, 1)
        month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        if start is not None and month_end <= start:
            continue
        if end is not None and month_start > end:
            continue
        files.append(p)
    return files


def _list_files_in_range(
    source: str, symbol: str, start: DateLike | None, end: DateLike | None
) -> list[Path]:
    symbol_dir = capacity_symbol_dir(source, symbol)
    start_d = _as_date(start) if start is not None else None
    end_d = _as_date(end) if end is not None else None
    schema = schemas.get_schema(source)
    if schema.name == "funding":
        return _list_month_files(symbol_dir, start_d, end_d)
    return _list_day_files(symbol_dir, start_d, end_d)


def _read_files(
    files: list[Path],
    *,
    ts_col: str | None,
    start_ms: int | None,
    end_ms: int | None,
    duckdb_memory_limit_gb: float | None = None,
    duckdb_threads: int | None = None,
) -> pl.DataFrame:
    """DuckDB relation sobre exatamente `files` (já podados por nome), com
    filtro de timestamp e ordenação delegados ao motor — não ao Python.

    `duckdb_memory_limit_gb`/`duckdb_threads` (default `None` = defaults do
    próprio DuckDB, sem mudança de comportamento pra quem já chama sem
    esses argumentos). Achado de auditoria (2026-08-14): sem `SET
    memory_limit`/`SET threads` explícitos, cada `duckdb.connect(":memory:")`
    assume por padrão até ~80% da RAM TOTAL da máquina e várias threads,
    achando que é o único processo rodando nela — sob `ProcessPoolExecutor`
    com N processos concorrentes (caso de `m2_bar_comparison.py`), cada um
    abre sua própria conexão com esse mesmo orçamento otimista, e a soma
    estoura a RAM real disponível mesmo quando cada query individual é
    pequena (`duckdb.OutOfMemoryException`, não é sobre tamanho de query).
    Ver `constants.yaml::m2_duckdb_memory_limit_gb`/`m2_duckdb_threads`."""
    if not files:
        return pl.DataFrame()

    con = duckdb.connect(database=":memory:")
    try:
        # Achado de auditoria 2026-08-15 (run real de M2, 12 workers
        # concorrentes): duckdb.connect(":memory:") sem `temp_directory`
        # explícito usa por padrão um caminho RELATIVO ao cwd
        # (".tmp/duckdb_temp_storage_<classe-de-tamanho>-<n>.tmp"), e o
        # NOME do arquivo de overflow é fixo pela classe de tamanho do
        # buffer, não único por conexão. Sob ProcessPoolExecutor, todo
        # worker herda o mesmo cwd -- 12 processos sem relação entre si
        # compartilham fisicamente o mesmo diretório e podem escolher o
        # MESMO nome de arquivo de overflow simultaneamente. Resultado
        # observado: `IOException: Failed to delete file
        # ".tmp\duckdb_temp_storage_S32K-0.tmp"` -- um processo apaga o
        # arquivo que outro processo (usando o mesmo nome por coincidência
        # de classe de tamanho) ainda considerava seu. Mesma classe de bug
        # já corrigida para memory_limit/threads (cada conexão assumindo
        # orçamento otimista sem coordenar com as outras) -- aqui o recurso
        # em disputa é o NOME DO ARQUIVO de overflow, não RAM. Isolado por
        # PID: cada processo grava em seu próprio diretório, sem
        # coordenação entre processos necessária (mesmo espírito de
        # DuckDBThrottle, um nível abaixo).
        temp_dir = Path(tempfile.gettempdir()) / f"duckdb_lake_pid{os.getpid()}"
        con.execute(f"SET temp_directory='{temp_dir.as_posix()}'")
        if duckdb_memory_limit_gb is not None:
            con.execute(f"SET memory_limit='{duckdb_memory_limit_gb}GB'")
        if duckdb_threads is not None:
            con.execute(f"SET threads={duckdb_threads}")
        rel = con.read_parquet([str(f) for f in files])
        if ts_col is not None:
            conditions = []
            if start_ms is not None:
                conditions.append(f'"{ts_col}" >= {start_ms}')
            if end_ms is not None:
                conditions.append(f'"{ts_col}" <= {end_ms}')
            if conditions:
                rel = rel.filter(" AND ".join(conditions))
            rel = rel.order(f'"{ts_col}"')
        return rel.pl()
    finally:
        con.close()


def _day_bounds_ms(start: DateLike | None, end: DateLike | None) -> tuple[int | None, int | None]:
    """`start`/`end` (datas) -> limites em epoch ms UTC cobrindo o dia
    inteiro de `end` (00:00:00.000 de `start` até 23:59:59.999 de `end`).
    Todos os timestamps das fontes (`open_time`, `transact_time`,
    `calc_time`) são epoch ms UTC — construir os limites via `datetime`
    ingênuo (sem `tzinfo`) usaria o fuso LOCAL da máquina em `.timestamp()`,
    um bug de deslocamento silencioso; por isso `tzinfo=timezone.utc`
    explícito abaixo, sempre."""
    start_ms = None
    end_ms = None
    if start is not None:
        d = _as_date(start)
        start_ms = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)
    if end is not None:
        d = _as_date(end)
        end_ms = (
            int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000) + 86_400_000 - 1
        )
    return start_ms, end_ms


def query_bars(
    symbol: str = "BTCUSDT",
    tf: str = "1m",
    start: DateLike | None = None,
    end: DateLike | None = None,
    *,
    source: str = "klines_1m",
    cast_prices: bool = True,
    duckdb_memory_limit_gb: float | None = None,
    duckdb_threads: int | None = None,
) -> pl.DataFrame:
    """Barras OHLCV de `source` (`klines_1m`, `mark_price_klines_1m` ou
    `premium_index_klines_1m` — todas 1m no disco), reamostradas para `tf`
    se `tf != "1m"` via `resample.resample_klines`. Import de `resample`
    feito dentro da função para não criar um ciclo de import a nível de
    módulo (`resample` não precisa saber de `lake`, mas `lake` compõe
    `resample` neste único ponto). `duckdb_memory_limit_gb`/`duckdb_threads`
    -- ver `_read_files`."""
    schema = schemas.get_schema(source)
    if not schema.is_klines_like:
        raise ValueError(
            f"source='{source}' não é um dataset klines-like (candidatos: klines_1m, "
            "mark_price_klines_1m, premium_index_klines_1m)"
        )

    files = _list_files_in_range(source, symbol, start, end)
    start_ms, end_ms = _day_bounds_ms(start, end)
    df = _read_files(
        files,
        ts_col="open_time",
        start_ms=start_ms,
        end_ms=end_ms,
        duckdb_memory_limit_gb=duckdb_memory_limit_gb,
        duckdb_threads=duckdb_threads,
    )

    if cast_prices or tf != "1m":
        df = cast_price_columns(df, ("open", "high", "low", "close"))

    if tf == "1m" or df.is_empty():
        return df

    from . import resample  # import local — ver docstring

    return resample.resample_klines(df, tf)


def query_agg_trades(
    symbol: str = "BTCUSDT",
    start: DateLike | None = None,
    end: DateLike | None = None,
    *,
    duckdb_memory_limit_gb: float | None = None,
    duckdb_threads: int | None = None,
) -> pl.DataFrame:
    """`duckdb_memory_limit_gb`/`duckdb_threads` -- ver `_read_files`."""
    files = _list_files_in_range("agg_trades", symbol, start, end)
    start_ms, end_ms = _day_bounds_ms(start, end)
    return _read_files(
        files,
        ts_col="transact_time",
        start_ms=start_ms,
        end_ms=end_ms,
        duckdb_memory_limit_gb=duckdb_memory_limit_gb,
        duckdb_threads=duckdb_threads,
    )


def query_dollar_bars(
    symbol: str,
    start: DateLike | None = None,
    end: DateLike | None = None,
    *,
    duckdb_memory_limit_gb: float | None = None,
    duckdb_threads: int | None = None,
) -> pl.DataFrame:
    """Barras `dollar_bars_r1` (`schemas.DOLLAR_BARS_R1`) escritas por
    `src.data.build_dollar_bars.write_dollar_bars_and_calibration` --
    MESMO padrão de `query_agg_trades` (poda de arquivo por dia + filtro de
    timestamp via DuckDB), sem lógica nova. Filtra/ordena por `close_time`
    (`timestamp_column` do schema — não `open_time`, ver docstring de
    `schemas.DOLLAR_BARS_R1`). `duckdb_memory_limit_gb`/`duckdb_threads` --
    ver `_read_files`.

    Só lê de `_paths.CAPACITY_DIR` (via `capacity_symbol_dir`, mesmo
    caminho de todo `query_*` desta camada) — sem parâmetro de root
    alternativo, porque nenhum outro `query_*` daqui tem um (ver docstring
    de `_read_files`/`_list_files_in_range`). Teste que precisa ler de um
    diretório alternativo (`tmp_path`) monkeypatcha `_paths.CAPACITY_DIR`
    (ou, quando outras fontes reais precisam continuar acessíveis no mesmo
    teste, `lake.capacity_symbol_dir` com um wrapper que só redireciona
    `source="dollar_bars_r1"`) — mesmo padrão já usado em
    `tests/unit/test_features_sources.py::metrics_dir`."""
    files = _list_files_in_range("dollar_bars_r1", symbol, start, end)
    start_ms, end_ms = _day_bounds_ms(start, end)
    return _read_files(
        files,
        ts_col="close_time",
        start_ms=start_ms,
        end_ms=end_ms,
        duckdb_memory_limit_gb=duckdb_memory_limit_gb,
        duckdb_threads=duckdb_threads,
    )


def query_metrics(
    symbol: str = "BTCUSDT",
    start: DateLike | None = None,
    end: DateLike | None = None,
) -> pl.DataFrame:
    """`create_time` é string (`"YYYY-MM-DD HH:MM:SS"`, medido — ver
    `schemas.METRICS`), não epoch — a poda fina por timestamp dentro do
    DuckDB não é aplicada aqui (comparação lexical de string funciona para
    ordenar, mas complicaria o filtro sem ganho real: a poda por ARQUIVO já
    é por dia). Quem precisa de epoch ms usa
    `_util.metrics_timestamp_to_ms` no resultado."""
    files = _list_files_in_range("metrics", symbol, start, end)
    return _read_files(files, ts_col=None, start_ms=None, end_ms=None).sort("create_time")


def query_funding(
    symbol: str = "BTCUSDT",
    start: DateLike | None = None,
    end: DateLike | None = None,
) -> pl.DataFrame:
    files = _list_files_in_range("funding", symbol, start, end)
    start_ms, end_ms = _day_bounds_ms(start, end)
    return _read_files(files, ts_col="calc_time", start_ms=start_ms, end_ms=end_ms)
