"""Mede a taxa real de trades/dia do BTCUSDT direto do parquet em disco --
resposta ao Achado 0 da auditoria externa (2026-08-15): o número que
motivou o Numba em `src/data/bars.py` (~1,29M trades/dia, extrapolado pra
"BTCUSDT... da ordem de bilhões de trades") veio de
`data/quality_reports/quality_report_agg_trades_v1.json`, que não declara
`symbol` -- e é o único `quality_report_agg_trades_*` que existe no repo.
Extrapolar aquele número especificamente para BTCUSDT era estimativa, não
medição (Regra Zero, CLAUDE.md).

Este script mede BTCUSDT direto de `data/capacity/agg_trades/BTCUSDT/`
(2.412 arquivos diários, 2019-12-31 em diante) de duas formas:
(1) taxa média sobre o histórico completo -- `COUNT(*)` via metadado
    parquet, não decodifica linha a linha, roda em segundos mesmo sobre a
    partição inteira;
(2) taxa na MESMA janela de calendário do quality_report -- comparação
    direta, apples-to-apples, com o número que já circula no código.

Se (2) ficar perto de 1,0x o número do quality_report, o achado da
auditoria era sobre rastreabilidade/documentação (o número provavelmente
era BTCUSDT mesmo, só não estava declarado). Se (2) desviar muito, o
achado é sobre a estimativa em si estar errada por escala.

`rows`/`start`/`end` da janela de comparação são LIDOS do próprio
`quality_report_agg_trades_v1.json` (achado de auditoria 2026-08-15,
`audit_engineering`: versão anterior transcrevia esses valores como
literais fixos no código -- corretos na ocasião, mas sem proteção contra
o relatório ser regenerado e o script não acompanhar, produzindo uma
comparação "apples-to-apples" silenciosamente incorreta)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import structlog

logger = structlog.get_logger(__name__)

_PARTITION_DIR = Path("data/capacity/agg_trades/BTCUSDT")
_QUALITY_REPORT_PATH = Path("data/quality_reports/quality_report_agg_trades_v1.json")


def _load_quality_report_window() -> tuple[int, str, str, int]:
    """Lê `rows`/`start`/`end` do próprio JSON -- nunca hardcoded (ver
    docstring do módulo)."""
    report = json.loads(_QUALITY_REPORT_PATH.read_text(encoding="utf-8"))
    rows = int(report["rows"])
    start = str(report["start"])[:10]  # "2026-06-09T00:00:00Z" -> "2026-06-09"
    end = str(report["end"])[:10]
    n_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return rows, start, end, n_days


def main() -> None:
    files = sorted(_PARTITION_DIR.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"nenhum parquet em {_PARTITION_DIR}")

    quality_report_rows, window_start, window_end, quality_report_n_days = (
        _load_quality_report_window()
    )

    first_day = files[0].stem
    last_day = files[-1].stem
    n_days_total = len(files)

    con = duckdb.connect(":memory:")
    try:
        con.execute("SET memory_limit='2GB'")
        con.execute("SET threads=4")

        # `con.read_parquet([...])` (API relacional, mesmo padrão de
        # `lake.py::_read_files`) em vez de interpolar caminhos em SQL --
        # elimina separador de caminho inconsistente entre plataformas e
        # qualquer necessidade de quoting manual (achado de auditoria
        # `audit_engineering`, 2026-08-15).
        total_rows_row = (
            con.read_parquet([str(f) for f in files]).aggregate("COUNT(*) AS n").fetchone()
        )
        assert total_rows_row is not None
        total_rows = total_rows_row[0]
        # n_days_total = len(files), já garantido >=1 pelo `if not files: raise` acima
        rate_full_history = total_rows / n_days_total  # noqa: unguarded-ratio -- ver comentário acima

        window_files = [f for f in files if window_start <= f.stem <= window_end]
        if window_files:
            window_rows_row = (
                con.read_parquet([str(f) for f in window_files])
                .aggregate("COUNT(*) AS n")
                .fetchone()
            )
            assert window_rows_row is not None
            window_rows = window_rows_row[0]
            # denominador é len(window_files), guardado pelo `if window_files:` acima
            rate_same_window = window_rows / len(window_files)  # noqa: unguarded-ratio -- guardado pelo if acima
        else:
            window_rows = None
            rate_same_window = None
    finally:
        con.close()

    # quality_report_n_days deriva de datas reais do JSON, sempre >=1
    quality_report_rate = quality_report_rows / quality_report_n_days  # noqa: unguarded-ratio -- sempre >=1 acima

    logger.info(
        "diagnostics.measure_btcusdt_trade_rate.done",
        symbol="BTCUSDT",
        n_files_total=n_days_total,
        first_day=first_day,
        last_day=last_day,
        total_rows=total_rows,
        rate_per_day_full_history=round(rate_full_history, 0),
        n_files_same_window=len(window_files),
        rows_same_window=window_rows,
        rate_per_day_same_window=(
            round(rate_same_window, 0) if rate_same_window is not None else None
        ),
        quality_report_rows=quality_report_rows,
        quality_report_window=f"{window_start}..{window_end}",
        quality_report_rate_per_day=round(quality_report_rate, 0),
        # quality_report_rate deriva de valores reais do JSON, sempre > 0
        ratio_full_history_vs_quality_report=round(
            rate_full_history / quality_report_rate, 2  # noqa: unguarded-ratio -- ver comentário acima
        ),
        ratio_same_window_vs_quality_report=(
            round(rate_same_window / quality_report_rate, 2)  # noqa: unguarded-ratio -- idem
            if rate_same_window is not None
            else None
        ),
    )


if __name__ == "__main__":
    main()
