"""Testes de `src/analysis/m2_worker.py` -- tudo que roda dentro de 1
processo filho do `ProcessPoolExecutor` (calibração + construção de barra
via streaming de `aggTrades`), sem IO real (`lake.query_bars`/
`lake.query_agg_trades` são monkeypatchados na fronteira, nunca chamados
de verdade aqui). Extraído de `test_analysis_m2_bar_comparison.py` no
desmembramento de 2026-08-15 (ver docstring de
`src/analysis/m2_bar_comparison.py` pro histórico completo).

Redesenho multi-TF (2026-08-15, PRD_V4_1.md §0.4 -- "Três timeframes
obrigatórios ponta a ponta", achado de gap registrado em `AG-017`) +
redesenho de fan-out (2026-08-15, `n_tasks` 10→20 por `(symbol, tf)` pra
usar os 12 núcleos de verdade): testes provam, via monkeypatch NA
FRONTEIRA de IO (`_scan_trades_totals`/`_query_baseline`/
`_build_trades_dependent_bars`), as propriedades de correção mais
importantes: `compute_trades_dependent_bars_for_symbol_tf` é autocontida
(1 scan de totais + 1 build por chamada, devolve só o TF pedido);
`time_stop_ms` é idêntico nas 3 iterações de TF do path leve, nunca
recalculado por TF.

**Testes de integração real (achado de auditoria `project_assurance`,
2026-08-15): a alegação "mesma convenção de M1/M3/M6 -- IO real fica fora
da suíte automatizada" era FALSA para M1 e M3 (ambos têm teste
`integration`+`slow` de ponta a ponta contra backfill local; só M6
bate).** `test_compute_time_bar_for_symbol_btcusdt_sobre_dado_real` chama
a função de produção sem scoping (mesmo padrão de M1/M3 -- barato porque
"time" só lê `klines_1m`). `test_trades_dependent_bars_btcusdt_sobre_
dado_real_janela_curta` NÃO chama `compute_trades_dependent_bars_for_
symbol_tf` diretamente -- essa função hardcoda o histórico COMPLETO
(`SYMBOL_START_DATE`..`END_DATE`), e `aggTrades` de BTCUSDT são 27GB
comprimidos: rodar sem scoping levaria a mesma escala de tempo que já
causou os travamentos multi-hora desta sessão, inviável num teste
automatizado. Em vez disso, replica a mesma lógica (`_scan_trades_totals`/
`_build_trades_dependent_bars`/`_build_tick_imbalance_config`) sobre uma
janela real pequena (3 dias) -- ainda IO real, ainda prova a integração
completa (DuckDB -> Numba -> `BarComparisonMetrics`), sem o custo de
tempo do histórico inteiro."""

from __future__ import annotations

import polars as pl
import pytest

import src.analysis.m2_worker as m2_worker
from src.analysis.m2_stats import BarComparisonMetrics, compute_bar_statistics
from src.analysis.m2_stats import compute_bar_statistics as real_compute_bar_statistics
from src.analysis.volatility_comparison import TIMEFRAMES
from src.data import lake
from src.data._paths import CAPACITY_DIR


def _bars(*, close: list[float], close_time: list[int]) -> pl.DataFrame:
    n = len(close)
    assert len(close_time) == n
    return pl.DataFrame({"close": close, "close_time": close_time})


def test_compute_trades_dependent_bars_for_symbol_tf_e_autocontida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado de desenho (2026-08-15): `compute_trades_dependent_bars_
    for_symbol_tf` é 1 task AUTOCONTIDA por `(symbol, tf)` -- refaz a 1ª
    passada (`_scan_trades_totals`, TF-independente mas barata) a cada
    chamada, deliberadamente, pra permitir fan-out flat de `len(symbols) ×
    (1 + len(TIMEFRAMES))` tasks sem orquestração em 2 estágios (ver
    docstring da função e de `run_and_save_bar_comparison_report` em
    `m2_bar_comparison.py`) -- troca de I/O redundante barato por
    paralelismo real da parte cara (construção) nos 12 núcleos. Este teste
    prova: 1 chamada = 1 scan de totais + 1 build, com `tf` propagado
    corretamente pros dois (achado real desta sessão: o desmembramento em
    `m2_worker.py` expôs um mismatch de assinatura entre este teste e
    `_scan_trades_totals`/`_build_trades_dependent_bars`, que já recebiam
    `tf` desde o redesenho multi-TF mas os fakes deste teste não -- nunca
    pego porque o teste não tinha sido rodado de novo depois daquela
    mudança), devolvendo as 3 métricas (dollar/volume/tick_imbalance) do
    TF pedido -- não mistura TFs."""
    scan_calls: list[tuple[str, str]] = []
    build_calls: list[tuple[str, str, float, float]] = []
    small_bars = _bars(close=[1.0, 2.0, 3.0], close_time=[0, 1_000, 2_000])

    def _fake_scan(symbol: str, tf: str, chunks: object) -> m2_worker._TradesTotals:
        scan_calls.append((symbol, tf))
        return m2_worker._TradesTotals(total_dollar=1_000.0, total_volume=100.0, n_ticks=500)

    def _fake_query_baseline(symbol: str, tf: str) -> pl.DataFrame:
        return small_bars

    def _fake_build(
        symbol: str,
        tf: str,
        chunks: object,
        *,
        dollar_threshold: float,
        volume_threshold: float,
        tib_config: object,
    ) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        build_calls.append((symbol, tf, dollar_threshold, volume_threshold))
        return small_bars, small_bars, small_bars

    monkeypatch.setattr(m2_worker, "_date_chunks", lambda start, end, *, chunk_days: [])
    monkeypatch.setattr(m2_worker, "_scan_trades_totals", _fake_scan)
    monkeypatch.setattr(m2_worker, "_query_baseline", _fake_query_baseline)
    monkeypatch.setattr(m2_worker, "_build_trades_dependent_bars", _fake_build)

    results = m2_worker.compute_trades_dependent_bars_for_symbol_tf(
        "BTCUSDT", "30m", time_stop_ms=1_000, ljung_box_lags=10
    )

    assert scan_calls == [("BTCUSDT", "30m")]
    assert len(build_calls) == 1
    assert build_calls[0][:2] == ("BTCUSDT", "30m")
    assert {metrics.tf for metrics in results} == {"30m"}
    assert {metrics.bar_type for metrics in results} == set(m2_worker._TRADES_DEPENDENT_BAR_TYPES)
    assert len(results) == len(m2_worker._TRADES_DEPENDENT_BAR_TYPES)


def test_time_stop_ms_e_invariante_entre_tfs(monkeypatch: pytest.MonkeyPatch) -> None:
    """`time_stop_bars=32` (`constants.yaml`) é justificado como "1 janela
    de funding" em UNIDADES DE BARRA DE 15M (32×15min=8h) -- recalcular
    via `step_ms(tf)` por TF mudaria o horizonte de 8h pra 16h/32h a cada
    TF, um erro silencioso de unidade (a classe que `PLANO_MESTRE_
    PRINCE2.md` §15.6 item 1 já tinha previsto pra este módulo).
    `compute_time_bar_for_symbol` recebe `time_stop_ms` já calculado (não
    recalcula por TF) -- este teste prova, via spy, que o MESMO valor
    chega em `compute_bar_statistics` nas 3 iterações de TF."""
    received_time_stop_ms: list[int] = []
    small_bars = _bars(close=[1.0, 2.0, 3.0], close_time=[0, 1_000, 2_000])

    def _spy_compute_bar_statistics(
        symbol: str,
        tf: str,
        bar_type: str,
        bars: pl.DataFrame,
        *,
        time_stop_ms: int,
        ljung_box_lags: int,
    ) -> BarComparisonMetrics:
        received_time_stop_ms.append(time_stop_ms)
        return real_compute_bar_statistics(
            symbol, tf, bar_type, bars, time_stop_ms=time_stop_ms, ljung_box_lags=ljung_box_lags
        )

    monkeypatch.setattr(m2_worker, "compute_bar_statistics", _spy_compute_bar_statistics)
    monkeypatch.setattr(m2_worker, "_query_baseline", lambda symbol, tf: small_bars)

    m2_worker.compute_time_bar_for_symbol("BTCUSDT", time_stop_ms=123_456, ljung_box_lags=10)

    assert len(received_time_stop_ms) == len(TIMEFRAMES)
    assert len(set(received_time_stop_ms)) == 1
    assert received_time_stop_ms[0] == 123_456


# ============================================================================
# Integração real (achado de auditoria `project_assurance`, 2026-08-15) --
# ver docstring do módulo pro porquê da diferença de scoping entre os 2
# testes abaixo.
# ============================================================================


def _skip_if_no_backfill_klines(symbol: str) -> None:
    if not (CAPACITY_DIR / "klines_1m" / symbol / "2020-01-01.parquet").exists():
        pytest.skip("backfill local de klines_1m ausente -- rode o download primeiro")


def _skip_if_no_backfill_agg_trades(symbol: str, day: str) -> None:
    if not (CAPACITY_DIR / "agg_trades" / symbol / f"{day}.parquet").exists():
        pytest.skip(f"backfill local de agg_trades/{symbol}/{day} ausente")


@pytest.mark.integration
@pytest.mark.slow
def test_compute_time_bar_for_symbol_btcusdt_sobre_dado_real() -> None:
    """Mesmo padrão de M1 (`test_analysis_volatility_comparison.py`) e M3
    (`test_analysis_m3_timeframe_choice.py`) -- chama a função de produção
    sem scoping, contra backfill local real. Barato porque `"time"` só lê
    `klines_1m` (bem menor que `aggTrades`)."""
    _skip_if_no_backfill_klines("BTCUSDT")

    results = m2_worker.compute_time_bar_for_symbol(
        "BTCUSDT", time_stop_ms=8 * 60 * 60 * 1_000, ljung_box_lags=10
    )

    assert [r.tf for r in results] == list(TIMEFRAMES)
    for r in results:
        assert r.symbol == "BTCUSDT"
        assert r.bar_type == "time"
        assert r.n_bars > 0


@pytest.mark.integration
@pytest.mark.slow
def test_trades_dependent_bars_btcusdt_sobre_dado_real_janela_curta() -> None:
    """Prova a integração completa do caminho pesado (DuckDB -> streaming
    -> Numba -> `BarComparisonMetrics`) contra `aggTrades` real -- mas
    numa janela de 3 dias, não o histórico completo (ver docstring do
    módulo pro porquê). Replica a lógica de
    `compute_trades_dependent_bars_for_symbol_tf`, só que com `chunks`
    manualmente restritos.

    Vai além de "não crasha, `n_bars>0`" (achado de auditoria: o único
    teste unitário existente capturava `dollar_threshold`/`volume_
    threshold` calculados mas a asserção ignorava esses 2 índices --
    a matemática central de calibração do módulo nunca era verificada
    numericamente). Aqui: `dollar_threshold * target_n_bars` precisa
    bater com `total_dollar` de verdade (é a própria definição de
    `dollar_threshold`, mas só vale a pena como teste se computado a
    partir de totais e threshold obtidos por 2 caminhos honestos -- aqui
    o total vem de somar os chunks direto, o threshold vem da função de
    produção)."""
    symbol = "BTCUSDT"
    tf = "15m"
    start, end = "2026-07-01", "2026-07-03"
    _skip_if_no_backfill_agg_trades(symbol, start)

    chunks = m2_worker._date_chunks(start, end, chunk_days=5)
    totals = m2_worker._scan_trades_totals(symbol, tf, chunks)
    assert totals.n_ticks > 0, "aggTrades vazio na janela -- ajustar start/end do teste"

    # Achado de auditoria 2026-08-15 (Manager): `m2_worker._query_baseline`
    # varre o histórico COMPLETO (`SYMBOL_START_DATE`..`END_DATE`, ~231 mil
    # barras de 15m pro BTC) -- usar isso aqui calibra `dollar_threshold`/
    # `volume_threshold`/`tib_config` pra densidade do histórico INTEIRO
    # aplicada a só 3 dias de trades, produzindo um threshold ~800x menor
    # do que a janela precisa e fazendo o teste tentar construir dezenas de
    # milhares de barras a partir de 3 dias de dado (minutos de execução,
    # não segundos -- travou um run real). Baseline escopado à MESMA janela
    # dos `chunks` corrige a calibração pro que o teste já promete ("janela
    # curta"), sem tocar `m2_worker.py`: em produção real
    # (`compute_trades_dependent_bars_for_symbol_tf`), `chunks` e baseline
    # SEMPRE cobrem a mesma janela (histórico completo) -- esse mismatch é
    # exclusivo deste teste, não existe fora dele.
    throttle = m2_worker._duckdb_throttle()
    baseline = lake.query_bars(
        symbol,
        tf,
        start,
        end,
        source="klines_1m",
        cast_prices=True,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    target_n_bars = m2_worker._target_n_bars(symbol, tf, baseline, start=start, end=end)
    dollar_threshold = totals.total_dollar / target_n_bars
    volume_threshold = totals.total_volume / target_n_bars
    tib_config = m2_worker._build_tick_imbalance_config(totals.n_ticks, target_n_bars)

    dollar_df, volume_df, tib_df = m2_worker._build_trades_dependent_bars(
        symbol,
        tf,
        chunks,
        dollar_threshold=dollar_threshold,
        volume_threshold=volume_threshold,
        tib_config=tib_config,
    )

    bars_by_type = {"dollar": dollar_df, "volume": volume_df, "tick_imbalance": tib_df}
    for bar_type, bars in bars_by_type.items():
        assert bars.height > 0, f"{bar_type}: nenhuma barra fechada na janela de 3 dias"
        metrics = compute_bar_statistics(
            symbol, tf, bar_type, bars, time_stop_ms=8 * 60 * 60 * 1_000, ljung_box_lags=10
        )
        assert metrics.n_bars > 0
        assert metrics.symbol == symbol and metrics.tf == tf and metrics.bar_type == bar_type

    # matemática de calibração central do módulo, verificada de verdade
    # (não só "roda sem erro") -- reconstrói o total consumido a partir
    # das próprias barras produzidas e confere contra o total real da
    # janela dentro de tolerância pequena (a última barra de cada tipo
    # pode ficar parcial -- ver docstring de threshold_bars_finish).
    dollar_consumed = float((dollar_df["quote_volume"]).sum())
    assert dollar_consumed == pytest.approx(totals.total_dollar, rel=1e-6)
    volume_consumed = float((volume_df["volume"]).sum())
    assert volume_consumed == pytest.approx(totals.total_volume, rel=1e-6)
    assert dollar_threshold > 0.0
    assert volume_threshold > 0.0
