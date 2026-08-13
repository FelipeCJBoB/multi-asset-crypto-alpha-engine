"""Testes de `src/labels/backfill_multi_symbol.py` — só o ROTEAMENTO de
argumentos (`symbol`/`tf`/`version`/`historical_filters_fallback`) até
`build_labels_for_symbol`/`write_labels_atomic`, via monkeypatch (sem IO
real — `build_labels_for_symbol` já é testada a fundo em
`test_labels_triple_barrier.py`, não precisa ser reexercitada aqui)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from src.labels import backfill_multi_symbol as bms
from src.labels import triple_barrier as tb
from src.labels._paths import labels_symbol_tf_dir


def _empty_labels() -> pl.DataFrame:
    return pl.DataFrame({"t0": pl.Series([], dtype=pl.Datetime("ms"))})


def test_build_and_write_labels_for_symbol_roteia_ate_build_e_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    build_calls: list[dict[str, Any]] = []
    write_calls: list[dict[str, Any]] = []

    def _fake_build_labels_for_symbol(
        symbol: str,
        start: Any,
        end: Any,
        *,
        config: tb.LabelConfig | None = None,
        estimator: Any = None,
        historical_filters_fallback: bool = False,
    ) -> pl.DataFrame:
        build_calls.append(
            {
                "symbol": symbol,
                "start": start,
                "end": end,
                "tf": config.tf if config is not None else None,
                "historical_filters_fallback": historical_filters_fallback,
            }
        )
        return _empty_labels()

    def _fake_write_labels_atomic(
        labels: pl.DataFrame, *, version: str = "v1", dest_dir: Path | None = None
    ) -> Path:
        write_calls.append({"version": version, "dest_dir": dest_dir})
        assert dest_dir is not None
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / "labels.parquet"

    monkeypatch.setattr(bms, "build_labels_for_symbol", _fake_build_labels_for_symbol)
    monkeypatch.setattr(bms, "write_labels_atomic", _fake_write_labels_atomic)

    bms.build_and_write_labels_for_symbol(
        "ETHUSDT", "2021-12-01", "2026-08-07", version="v1", tf="15m"
    )

    assert build_calls == [
        {
            "symbol": "ETHUSDT",
            "start": "2021-12-01",
            "end": "2026-08-07",
            "tf": "15m",
            "historical_filters_fallback": True,
        }
    ]
    assert write_calls == [
        {"version": "v1", "dest_dir": labels_symbol_tf_dir("ETHUSDT", "v1", tf="15m")}
    ]


def test_run_and_write_labels_for_alts_cobre_os_4_alts_sem_btc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BTCUSDT não entra em `ALT_SYMBOLS` -- já tem `labels/v1/` completo,
    esta rodada é especificamente sobre os 4 que nunca tiveram (ver
    docstring do módulo).

    `ProcessPoolExecutor` real spawnaria um subprocesso que reimporta
    `bms` do zero -- o monkeypatch deste processo não alcançaria lá
    dentro, e o teste tentaria IO real (dado ausente pros alts hoje,
    ver docstring do módulo). Troca por `ThreadPoolExecutor` (mesma
    interface `submit`/`as_completed`, executa na mesma memória de
    processo) só pra este teste -- suficiente pra provar o roteamento
    (quais símbolos são chamados, resultado agregado), não uma alegação
    sobre paralelismo real entre processos."""
    assert bms.ALT_SYMBOLS == ("ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    assert "BTCUSDT" not in bms.ALT_SYMBOLS

    seen_symbols: list[str] = []

    def _fake_build_and_write(
        symbol: str,
        start: Any,
        end: Any,
        *,
        version: str = "v1",
        tf: str = "15m",
        config: Any = None,
    ) -> Path:
        seen_symbols.append(symbol)
        return Path(f"/fake/{symbol}/labels.parquet")

    monkeypatch.setattr(bms, "build_and_write_labels_for_symbol", _fake_build_and_write)
    monkeypatch.setattr(bms, "ProcessPoolExecutor", ThreadPoolExecutor)

    results = bms.run_and_write_labels_for_alts(max_workers=1)

    assert set(results) == set(bms.ALT_SYMBOLS)
    assert set(seen_symbols) == set(bms.ALT_SYMBOLS)
