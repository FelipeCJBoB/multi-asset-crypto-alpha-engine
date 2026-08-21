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
    """1 linha MÍNIMA VÁLIDA (não 0 linhas) que satisfaz as 6 invariantes de
    `tb.assert_label_invariants` -- chamada real dentro de `build_and_write_
    labels_for_symbol` desde a correção de AG-029 (`src/labels/backfill_
    multi_symbol.py:103`), "falha alto de propósito". Um DataFrame de 0
    linhas não serve: `config_hash.n_unique() == 1` (§3.8) é sempre falso
    sobre uma coluna vazia (`n_unique()` de série vazia é 0, não 1) --
    não dá pra simplesmente completar o schema faltante (`t1`/`t_entry`/
    `barrier_hit`/`config_hash`/`sample_weight`/`uniqueness`) mantendo 0
    linhas, como uma 1ª tentativa desta correção fez e ainda falhava.
    `held_ms=60_000` (1min) fica bem abaixo de qualquer `time_stop_ms` real
    configurado (ordem de horas) -- não hardcoda o valor real, só garante
    folga. Mantém o nome `_empty_labels` (não `_minimal_labels`) porque o
    propósito do teste continua sendo "roteamento de argumentos", não
    conteúdo de label -- só o suficiente pra passar pela validação real que
    o caminho de produção agora aplica.

    `n_bars_held=0` (AG-116, 2026-08-20) -- `assert_label_invariants` sob
    `resolution_id` (dollar bar) agora lê esta coluna pro teto `n_bars_
    held <= horizon_bars` (em vez de `held_ms <= time_stop_ms`, ver
    `build_and_write_labels_for_symbol`). `0` é seguro contra QUALQUER
    `horizon_bars >= 1` real (a validação de `LabelConfig.__post_init__`
    já garante `horizon_bars >= 1`), sem hardcodar o valor real -- mesmo
    espírito de `held_ms=60_000` acima."""
    tz_ms = pl.Datetime("ms", time_zone="UTC")
    return pl.DataFrame(
        {
            "t0": pl.Series([0], dtype=pl.Int64).cast(tz_ms),
            "t1": pl.Series([60_000], dtype=pl.Int64).cast(tz_ms),
            "t_entry": pl.Series([0], dtype=pl.Int64).cast(tz_ms),
            "barrier_hit": pl.Series(["TP"], dtype=pl.Categorical),
            "config_hash": ["fake_routing_test"],
            "sample_weight": [1.0],
            "n_bars_held": [0],
            "uniqueness": [1.0],
        }
    )


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
        # Sem IO real de propósito (achado ao rodar o smoke test da Fase 5,
        # 2026-08-17): a versão anterior deste fake fazia `dest_dir.mkdir(...)`
        # sobre o path de PRODUÇÃO real (`data/labels/{symbol}/{grade}/v1/`),
        # deixando diretório vazio pra trás quando o path ainda não existia --
        # inofensivo pro grade de tempo (path já existia, mkdir virava no-op),
        # mas poluiu `data/labels/BTCUSDT/R1/v1/` de verdade, exatamente o
        # path que o backfill real (Fase 5) ia escrever depois. Este teste só
        # precisa provar ROTEAMENTO (dest_dir correto), não criar nada no
        # disco real.
        write_calls.append({"version": version, "dest_dir": dest_dir})
        assert dest_dir is not None
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


# ============================================================================
# Fase 5 (2026-08-17) -- resolution_id/estimator, run_and_write_labels_
# dollar_bar_parkinson
# ============================================================================


def test_build_and_write_labels_for_symbol_resolution_id_usa_path_novo_e_repassa_estimator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resolution_id="R1"` produz um `dest_dir` DIFERENTE de `tf="15m"`
    (guarda anti-colisão, Fase 1) -- e `estimator` chega de fato até
    `build_labels_for_symbol`, não é descartado."""
    from src.features.volatility import ParkinsonEstimator

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
                "resolution_id": config.resolution_id if config is not None else None,
                "estimator_id": estimator.estimator_id if estimator is not None else None,
            }
        )
        return _empty_labels()

    def _fake_write_labels_atomic(
        labels: pl.DataFrame, *, version: str = "v1", dest_dir: Path | None = None
    ) -> Path:
        # Sem IO real de propósito -- ver comentário do fake irmão acima
        # (achado do smoke test da Fase 5: mkdir sobre path de produção real
        # deixa diretório vazio pra trás).
        write_calls.append({"dest_dir": dest_dir})
        assert dest_dir is not None
        return dest_dir / "labels.parquet"

    monkeypatch.setattr(bms, "build_labels_for_symbol", _fake_build_labels_for_symbol)
    monkeypatch.setattr(bms, "write_labels_atomic", _fake_write_labels_atomic)

    estimator = ParkinsonEstimator(window=20)
    cfg = tb.LabelConfig.from_constants(estimator_id=estimator.estimator_id, resolution_id="R1")
    bms.build_and_write_labels_for_symbol(
        "BTCUSDT", "2020-01-01", "2026-08-06", resolution_id="R1", config=cfg, estimator=estimator
    )

    assert build_calls == [{"resolution_id": "R1", "estimator_id": "parkinson_w20"}]
    dest_dir = write_calls[0]["dest_dir"]
    assert "R1" in dest_dir.parts
    assert "15m" not in dest_dir.parts
    assert dest_dir == labels_symbol_tf_dir("BTCUSDT", "v1", resolution_id="R1")


def test_run_and_write_labels_dollar_bar_parkinson_cobre_os_5_simbolos_incluindo_btc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diferente de `run_and_write_labels_for_alts` (exclui BTCUSDT de
    propósito), esta função cobre os 5 -- nenhum símbolo tem `labels/`
    sob R1 ainda."""
    assert bms.ALL_SYMBOLS == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    assert set(bms.SYMBOL_START_DATE) == set(bms.ALL_SYMBOLS)
    assert bms.SYMBOL_START_DATE["BTCUSDT"] == "2020-01-01"
    for alt in bms.ALT_SYMBOLS:
        assert bms.SYMBOL_START_DATE[alt] == bms.ALT_START_DATE

    calls: list[dict[str, Any]] = []

    def _fake_build_and_write(
        symbol: str,
        start: Any,
        end: Any,
        *,
        version: str = "v1",
        resolution_id: str | None = None,
        config: Any = None,
        estimator: Any = None,
    ) -> Path:
        calls.append(
            {
                "symbol": symbol,
                "start": start,
                "resolution_id": resolution_id,
                "estimator_id": estimator.estimator_id if estimator is not None else None,
                "grade_id": config.resolution_id if config is not None else None,
            }
        )
        return Path(f"/fake/{symbol}/labels.parquet")

    monkeypatch.setattr(bms, "build_and_write_labels_for_symbol", _fake_build_and_write)
    monkeypatch.setattr(bms, "ProcessPoolExecutor", ThreadPoolExecutor)

    results = bms.run_and_write_labels_dollar_bar_parkinson(max_workers=1)

    assert set(results) == set(bms.ALL_SYMBOLS)
    calls_by_symbol = {c["symbol"]: c for c in calls}
    assert set(calls_by_symbol) == set(bms.ALL_SYMBOLS)
    for symbol, call in calls_by_symbol.items():
        assert call["start"] == bms.SYMBOL_START_DATE[symbol]
        assert call["resolution_id"] == "R1"
        assert call["grade_id"] == "R1"
        assert call["estimator_id"] == "parkinson_w20"
