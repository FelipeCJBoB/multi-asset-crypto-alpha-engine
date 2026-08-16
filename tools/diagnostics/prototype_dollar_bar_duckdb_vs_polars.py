"""Protótipo de MEDIÇÃO, não decisão -- compara 2 formas de ir de `aggTrades`
em disco até um `DataFrame` de dollar bars: (1) caminho de produção atual,
`lake.query_agg_trades` (Polars/DuckDB) + `src.data.bars.dollar_bars_carry`/
`threshold_bars_step`/`finish` (`bar_id = floor(cumsum/threshold)`,
vetorizado, sem loop Python); (2) candidato levantado na resposta à pergunta
"otimização de reprocessamento" (2026-08-16, ver `docs/refactor_dollar_bar_
canonico.md` §5.3): empurrar cumsum+threshold pra dentro do DuckDB via
window function nativa (`SUM() OVER (ORDER BY transact_time ROWS UNBOUNDED
PRECEDING)` + `GROUP BY floor(cum/threshold)`), na hipótese de que o buffer
manager do DuckDB (spill-to-disk) segura a memória em vez de Polars/Python
-- possível mitigação de AG-034 (esgotamento de memória sob concorrência
plena, `audit/architecture_gaps_log.yaml`, nunca corrigido).

**Aviso de proveniência ANTES de rodar (CLAUDE.md, Regra zero: medir antes
de afirmar).** Existe relato real de cumsum via window function do DuckDB
sendo MAIS LENTO que a alternativa vetorizada em algumas cargas
(github.com/duckdb/duckdb/issues/3453) -- este script mede se isso se
confirma NESTE caso (`aggTrades` real, ordenado por `transact_time`, já no
formato que a produção usa), sem assumir uma direção a priori.

**Caveat de memória, explícito.** `tracemalloc` só enxerga alocações do heap
do CPython -- o buffer interno do DuckDB (onde a hipótese de mitigação de
AG-034 realmente aposta) é C++ nativo e não aparece aqui. Se a abordagem
DuckDB vencer em TEMPO mas os dois picos de `tracemalloc` ficarem
parecidos, isso NÃO refuta a hipótese de memória -- só significa que este
script não consegue medir aquele eixo; ficaria para observação manual de
RSS do processo (Task Manager / `Get-Process` no PowerShell) durante o run
com um recorte bem maior que os poucos dias reais usados aqui.

**Comparação fim-a-fim, de propósito.** A pergunta real não é "qual cumsum
é mais rápido isoladamente" -- é "vale trocar (ler parquet -> Polars ->
construir barra) por (1 query DuckDB só)". Por isso o tempo de
`lake.query_agg_trades` entra na medição Polars, não só o tempo de
`threshold_bars_step`.

Roda sobre um recorte REAL pequeno (`--symbol`/`--start`/`--end`, default
BTCUSDT/3 dias reais de `data/capacity/agg_trades/<symbol>/`) -- rápido o
bastante pra prototipar, real o bastante pra não ser sintético. Ambas as
abordagens usam o MESMO threshold, calibrado pela mesma fórmula de
`m2_worker.py:437` (`total_dollar / target_n_bars`) sobre o total real do
recorte, pra produzir aproximadamente o mesmo número de barras nas duas.

Saída: `experiments/prototype_dollar_bar_duckdb_vs_polars.json` (escrita
atômica, B29, mesmo padrão de `m2_bar_comparison._atomic_write_json`) + log
estruturado com o resumo legível."""

from __future__ import annotations

import argparse
import os
import time
import tracemalloc
from pathlib import Path
from typing import Any

# Mesma disciplina de m2_worker.py -- sem isso, Polars abre pool de threads
# interno e compete consigo mesmo dentro do mesmo processo, distorcendo a
# comparação de tempo contra o DuckDB (que tem seu próprio `SET threads`
# explícito abaixo, controlado).
os.environ.setdefault("POLARS_MAX_THREADS", "1")

import duckdb
import orjson
import structlog

from src.data import lake
from src.data._constants import load_constant as load_data_constant
from src.data.bars import dollar_bars_carry, threshold_bars_finish, threshold_bars_step

logger = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEST_PATH = _REPO_ROOT / "experiments" / "prototype_dollar_bar_duckdb_vs_polars.json"


def _duckdb_throttle() -> lake.DuckDBThrottle:
    """Mesma constante/mesmo raciocínio de `m2_worker._duckdb_throttle` --
    nunca abrir conexão DuckDB sem `SET memory_limit`/`SET threads`
    explícitos (achado de auditoria 2026-08-14, ver docstring de origem)."""
    return lake.DuckDBThrottle(
        memory_limit_gb=float(load_data_constant("m2_duckdb_memory_limit_gb")),
        threads=int(load_data_constant("m2_duckdb_threads")),
    )


def _partition_files(symbol: str, start: str, end: str) -> list[Path]:
    """Glob direto da partição, mesmo padrão de
    `measure_btcusdt_trade_rate.py` -- não usa `lake._list_files_in_range`
    (privada) de propósito, evita depender de internals de outro módulo
    pra um script de prototipagem."""
    partition_dir = _REPO_ROOT / "data" / "capacity" / "agg_trades" / symbol
    files = sorted(partition_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"nenhum parquet em {partition_dir}")
    window_files = [f for f in files if start <= f.stem <= end]
    if not window_files:
        raise FileNotFoundError(
            f"nenhum arquivo de {symbol} no intervalo {start}..{end} "
            f"(primeiro disponível: {files[0].stem}, último: {files[-1].stem})"
        )
    return window_files


def _measure_polars(symbol: str, start: str, end: str, threshold: float) -> dict[str, Any]:
    throttle = _duckdb_throttle()
    tracemalloc.start()
    t0 = time.perf_counter()
    trades = lake.query_agg_trades(
        symbol,
        start,
        end,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    t_loaded = time.perf_counter()
    carry = dollar_bars_carry(threshold=threshold)
    threshold_bars_step(carry, trades)
    bars = threshold_bars_finish(carry)
    t_done = time.perf_counter()
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "approach": "polars_vectorized_cumsum",
        "n_trades": trades.height,
        "n_bars": bars.height,
        "elapsed_load_s": round(t_loaded - t0, 4),
        "elapsed_construct_s": round(t_done - t_loaded, 4),
        "elapsed_total_s": round(t_done - t0, 4),
        "tracemalloc_peak_mb": round(peak_bytes / 1e6, 2),
    }


def _measure_duckdb(files: list[Path], threshold: float) -> dict[str, Any]:
    throttle = _duckdb_throttle()
    tracemalloc.start()
    t0 = time.perf_counter()
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"SET memory_limit='{throttle.memory_limit_gb}GB'")
        con.execute(f"SET threads={throttle.threads}")
        # `read_parquet([...])` via API relacional (lista de paths Python),
        # não interpolação de string em SQL -- mesmo achado de auditoria
        # 2026-08-15 documentado em measure_btcusdt_trade_rate.py (separador
        # de caminho inconsistente entre plataformas + quoting manual).
        con.read_parquet([str(f) for f in files]).create_view("trades")
        query = f"""
            WITH cum AS (
                SELECT
                    transact_time,
                    price,
                    quantity,
                    SUM(price * quantity) OVER (
                        ORDER BY transact_time
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS cum_dollar
                FROM trades
            )
            SELECT
                CAST(cum_dollar // {threshold} AS BIGINT) AS bar_id,
                COUNT(*) AS n_trades,
                MIN(price) AS low,
                MAX(price) AS high,
                FIRST(price ORDER BY transact_time) AS open,
                LAST(price ORDER BY transact_time) AS close,
                SUM(quantity) AS volume
            FROM cum
            GROUP BY bar_id
            ORDER BY bar_id
        """
        result = con.execute(query).pl()
        n_trades_row = con.execute("SELECT COUNT(*) FROM trades").fetchone()
    finally:
        con.close()
    t_done = time.perf_counter()
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert n_trades_row is not None
    return {
        "approach": "duckdb_window_function",
        "n_trades": int(n_trades_row[0]),
        "n_bars": result.height,
        "elapsed_load_s": None,  # não separável -- 1 query só, ver docstring do módulo
        "elapsed_construct_s": None,
        "elapsed_total_s": round(t_done - t0, 4),
        "tracemalloc_peak_mb": round(peak_bytes / 1e6, 2),
    }


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão de `m2_bar_comparison._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2026-07-01", help="ISO date, inclusive")
    parser.add_argument("--end", default="2026-07-03", help="ISO date, inclusive")
    parser.add_argument(
        "--target-n-bars",
        type=int,
        default=300,
        help="mesma fórmula de m2_worker.py:437 -- threshold = total_dollar/target_n_bars",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_cli_args()
    files = _partition_files(args.symbol, args.start, args.end)

    logger.info(
        "diagnostics.prototype_dollar_bar.calibrating",
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        n_files=len(files),
    )
    throttle = _duckdb_throttle()
    trades_for_calibration = lake.query_agg_trades(
        args.symbol,
        args.start,
        args.end,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    total_dollar = float(
        (trades_for_calibration["price"] * trades_for_calibration["quantity"]).sum()
    )
    # total_dollar > 0 -- garantido por trades reais com price/quantity > 0;
    # target_n_bars > 0 -- argparse type=int, validado abaixo antes de dividir
    if args.target_n_bars <= 0:
        raise ValueError(f"--target-n-bars precisa ser > 0, recebido {args.target_n_bars}")
    threshold = total_dollar / args.target_n_bars  # noqa: unguarded-ratio -- guardado pelo if acima

    polars_result = _measure_polars(args.symbol, args.start, args.end, threshold)
    duckdb_result = _measure_duckdb(files, threshold)

    n_bars_diff = abs(polars_result["n_bars"] - duckdb_result["n_bars"])
    speedup = (
        polars_result["elapsed_total_s"] / duckdb_result["elapsed_total_s"]  # noqa: unguarded-ratio -- guardado pelo `if` da própria expressão ternária
        if duckdb_result["elapsed_total_s"] > 0
        else None
    )

    payload = {
        "symbol": args.symbol,
        "window": f"{args.start}..{args.end}",
        "n_files": len(files),
        "target_n_bars": args.target_n_bars,
        "threshold_usd": threshold,
        "total_dollar_volume": total_dollar,
        "polars": polars_result,
        "duckdb": duckdb_result,
        "n_bars_diff_abs": n_bars_diff,
        "duckdb_speedup_factor": round(speedup, 3) if speedup is not None else None,
    }
    _atomic_write_json(payload, _DEST_PATH)

    logger.info(
        "diagnostics.prototype_dollar_bar.done",
        symbol=args.symbol,
        window=f"{args.start}..{args.end}",
        n_bars_polars=polars_result["n_bars"],
        n_bars_duckdb=duckdb_result["n_bars"],
        n_bars_diff_abs=n_bars_diff,
        elapsed_total_s_polars=polars_result["elapsed_total_s"],
        elapsed_total_s_duckdb=duckdb_result["elapsed_total_s"],
        duckdb_speedup_factor=round(speedup, 3) if speedup is not None else None,
        tracemalloc_peak_mb_polars=polars_result["tracemalloc_peak_mb"],
        tracemalloc_peak_mb_duckdb=duckdb_result["tracemalloc_peak_mb"],
        dest_path=str(_DEST_PATH),
        caveat="tracemalloc nao mede buffer nativo do DuckDB -- ver docstring do modulo",
    )


if __name__ == "__main__":
    main()
