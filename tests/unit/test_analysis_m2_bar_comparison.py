"""Testes de `src/analysis/m2_bar_comparison.py` -- núcleo puro
(`compute_bar_statistics`), sem IO real (`compute_bar_comparison_for_symbol`/
`run_and_save_bar_comparison_report` fazem IO real via `lake.query_bars`/
`lake.query_agg_trades`, não exercitados aqui — mesma convenção de M1/M3/M6
sobre funções orquestradoras com IO). JB/Ljung-Box/ADF vêm de scipy/
statsmodels (bibliotecas de terceiros testadas fora deste repo) — o que
vale testar aqui é a ORQUESTRAÇÃO: amostra pequena não crasha, tipos/faixas
saem sãos em amostra grande, e a reutilização de `compute_concurrency_and_
uniqueness` está corretamente calibrada (t0/t1), não uma reimplementação
das próprias fórmulas estatísticas.

Redesenho multi-TF (2026-08-15, PRD_V4_1.md §0.4 -- "Três timeframes
obrigatórios ponta a ponta", achado de gap registrado em `AG-017`) +
redesenho de fan-out (2026-08-15, `n_tasks` 10→20 por `(symbol, tf)` pra
usar os 12 núcleos de verdade): testes novos provam, via monkeypatch NA
FRONTEIRA de IO (`_scan_trades_totals`/`_query_baseline`/
`_build_trades_dependent_bars`, não `lake.*` direto -- mesmo padrão já
usado nos testes de `_run_adfuller` abaixo), as propriedades de correção
mais importantes: `compute_trades_dependent_bars_for_symbol_tf` é
autocontida (1 scan de totais + 1 build por chamada, devolve só o TF
pedido); `time_stop_ms` é idêntico nas 3 iterações de TF do path leve,
nunca recalculado por TF."""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest
from statsmodels.tsa.stattools import adfuller as real_adfuller

import src.analysis.m2_bar_comparison as m2
from src.analysis.m2_bar_comparison import compute_bar_statistics
from src.analysis.volatility_comparison import TIMEFRAMES

AdfullerResult = tuple[float, float, int, int, dict[str, float], float]


def _bars(*, close: list[float], close_time: list[int]) -> pl.DataFrame:
    n = len(close)
    assert len(close_time) == n
    return pl.DataFrame({"close": close, "close_time": close_time})


def test_amostra_pequena_devolve_nan_sem_levantar() -> None:
    bars = _bars(close=[100.0, 101.0, 99.0, 102.0, 98.0], close_time=list(range(5)))
    metrics = compute_bar_statistics(
        "BTCUSDT", "15m", "time", bars, time_stop_ms=1_000, ljung_box_lags=10
    )

    assert metrics.n_bars == 5
    assert metrics.n_returns == 4
    assert math.isnan(metrics.jarque_bera_pvalue)
    assert math.isnan(metrics.ljung_box_r_pvalue)
    assert math.isnan(metrics.adf_pvalue)
    assert math.isnan(metrics.avg_uniqueness)


def test_amostra_grande_produz_valores_finitos_e_em_faixa_valida() -> None:
    # sequencia pseudo-variavel determinística (sem RNG) -- só precisa de
    # variância real, não de aleatoriedade de verdade.
    close = [100.0 + 0.5 * ((i * 37) % 11) for i in range(101)]
    close_time = list(range(101))
    bars = _bars(close=close, close_time=close_time)

    metrics = compute_bar_statistics(
        "BTCUSDT", "15m", "dollar", bars, time_stop_ms=1_000, ljung_box_lags=10
    )

    assert metrics.n_bars == 101
    assert metrics.n_returns == 100
    assert not math.isnan(metrics.jarque_bera_pvalue)
    assert not math.isnan(metrics.kurtosis_excess)
    assert not math.isnan(metrics.ljung_box_r_pvalue)
    assert not math.isnan(metrics.ljung_box_r2_pvalue)
    assert not math.isnan(metrics.adf_pvalue)
    assert not math.isnan(metrics.avg_uniqueness)
    assert 0.0 <= metrics.jarque_bera_pvalue <= 1.0
    assert 0.0 <= metrics.ljung_box_r_pvalue <= 1.0
    assert 0.0 <= metrics.ljung_box_r2_pvalue <= 1.0
    assert 0.0 <= metrics.adf_pvalue <= 1.0
    assert 0.0 < metrics.avg_uniqueness <= 1.0


def test_avg_uniqueness_e_um_quando_janelas_de_time_stop_nao_se_sobrepoem() -> None:
    """close_time bem espaçados (1_000_000ms) contra um time_stop pequeno
    (100ms) -> nenhuma janela [close_time, close_time+time_stop) cobre a
    próxima barra -- concorrência 1 em toda posição, uniqueness exato 1.0
    (comportamento já garantido por `compute_concurrency_and_uniqueness`,
    aqui só confirmando que t0/t1 foram passados na conta certa)."""
    n = 50
    close = [100.0 + 0.5 * ((i * 37) % 11) for i in range(n)]
    close_time = [i * 1_000_000 for i in range(n)]
    bars = _bars(close=close, close_time=close_time)

    metrics = compute_bar_statistics(
        "BTCUSDT", "15m", "tick_imbalance", bars, time_stop_ms=100, ljung_box_lags=10
    )

    assert metrics.avg_uniqueness == pytest.approx(1.0)


def test_run_adfuller_usa_maxlag_fixo_nao_busca_ate_default_grande(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado de auditoria (`audit_engineering`, 2026-08-15, pesquisa web):
    `adfuller(autolag="AIC")` sem `maxlag` explícito ajusta até ~76
    regressões (cada uma uma SVD) pra nobs~164mil -- issue conhecido da
    statsmodels desde 2014 (#1849, "wasting memory"). `_run_adfuller` DEVE
    chamar com `autolag=None` (lag fixo, 1 regressão só) -- este teste
    prova isso via spy no `adfuller` real, não confia só na leitura do
    código."""
    calls: list[dict[str, object]] = []

    def _spy(*args: object, **kwargs: object) -> AdfullerResult:
        calls.append(kwargs)
        result: AdfullerResult = real_adfuller(*args, **kwargs)
        return result

    monkeypatch.setattr(m2, "adfuller", _spy)

    close = [100.0 + 0.5 * ((i * 37) % 11) for i in range(101)]
    r = np.diff(np.log(np.array(close)))
    m2._run_adfuller("BTCUSDT", "15m", "dollar", r, maxlag=10)

    assert len(calls) == 1
    assert calls[0]["autolag"] is None
    assert calls[0]["maxlag"] == 10


def test_run_adfuller_captura_memoryerror_e_devolve_nan_sem_derrubar_o_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado de auditoria: `np.linalg.svd`/LAPACK `gesdd` tem histórico
    documentado de `MemoryError`/`LinAlgError` sob concorrência mesmo com
    matriz pequena (numpy#20384, OpenBLAS#3044) -- uma célula ruim não pode
    derrubar as outras 19 do batch. Simula a falha via monkeypatch em vez
    de tentar reproduzir a condição de corrida real (não determinística)."""

    def _boom(*args: object, **kwargs: object) -> AdfullerResult:
        raise MemoryError("Unable to allocate 36.2 MiB (simulado)")

    monkeypatch.setattr(m2, "adfuller", _boom)

    stat, pvalue = m2._run_adfuller(
        "BTCUSDT", "15m", "dollar", np.array([0.01, -0.02, 0.03, -0.01]), maxlag=2
    )

    assert math.isnan(stat)
    assert math.isnan(pvalue)


# ============================================================================
# Redesenho multi-TF -- as duas propriedades de correção mais importantes
# (PRD_V4_1.md §0.4, achado de gap AG-017): reuso de totais entre TFs e
# invariância de time_stop_ms. Monkeypatch na fronteira de IO
# (`_scan_trades_totals`/`_query_baseline`/`_build_trades_dependent_bars`),
# não `lake.*` direto -- mesmo padrão dos testes de `_run_adfuller` acima.
# ============================================================================


def test_compute_trades_dependent_bars_for_symbol_tf_e_autocontida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado de desenho (2026-08-15): `compute_trades_dependent_bars_
    for_symbol_tf` é 1 task AUTOCONTIDA por `(symbol, tf)` -- refaz a 1ª
    passada (`_scan_trades_totals`, TF-independente mas barata) a cada
    chamada, deliberadamente, pra permitir fan-out flat de `len(symbols) ×
    (1 + len(TIMEFRAMES))` tasks sem orquestração em 2 estágios (ver
    docstring da função e de `run_and_save_bar_comparison_report`) --
    troca de I/O redundante barato por paralelismo real da parte cara
    (construção) nos 12 núcleos. Este teste prova: 1 chamada = 1 scan de
    totais + 1 build, devolvendo as 3 métricas (dollar/volume/tick_
    imbalance) do TF pedido -- não mistura TFs."""
    scan_calls: list[str] = []
    build_calls: list[tuple[str, float, float]] = []
    small_bars = _bars(close=[1.0, 2.0, 3.0], close_time=[0, 1_000, 2_000])

    def _fake_scan(symbol: str, chunks: object) -> m2._TradesTotals:
        scan_calls.append(symbol)
        return m2._TradesTotals(total_dollar=1_000.0, total_volume=100.0, n_ticks=500)

    def _fake_query_baseline(symbol: str, tf: str) -> pl.DataFrame:
        return small_bars

    def _fake_build(
        symbol: str,
        chunks: object,
        *,
        dollar_threshold: float,
        volume_threshold: float,
        tib_config: object,
    ) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        build_calls.append((symbol, dollar_threshold, volume_threshold))
        return small_bars, small_bars, small_bars

    monkeypatch.setattr(m2, "_date_chunks", lambda start, end, *, chunk_days: [])
    monkeypatch.setattr(m2, "_scan_trades_totals", _fake_scan)
    monkeypatch.setattr(m2, "_query_baseline", _fake_query_baseline)
    monkeypatch.setattr(m2, "_build_trades_dependent_bars", _fake_build)

    results = m2.compute_trades_dependent_bars_for_symbol_tf(
        "BTCUSDT", "30m", time_stop_ms=1_000, ljung_box_lags=10
    )

    assert len(scan_calls) == 1
    assert len(build_calls) == 1
    assert {metrics.tf for metrics in results} == {"30m"}
    assert {metrics.bar_type for metrics in results} == set(m2._TRADES_DEPENDENT_BAR_TYPES)
    assert len(results) == len(m2._TRADES_DEPENDENT_BAR_TYPES)


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
    real_compute_bar_statistics = m2.compute_bar_statistics
    small_bars = _bars(close=[1.0, 2.0, 3.0], close_time=[0, 1_000, 2_000])

    def _spy_compute_bar_statistics(
        symbol: str,
        tf: str,
        bar_type: str,
        bars: pl.DataFrame,
        *,
        time_stop_ms: int,
        ljung_box_lags: int,
    ) -> m2.BarComparisonMetrics:
        received_time_stop_ms.append(time_stop_ms)
        return real_compute_bar_statistics(
            symbol, tf, bar_type, bars, time_stop_ms=time_stop_ms, ljung_box_lags=ljung_box_lags
        )

    monkeypatch.setattr(m2, "compute_bar_statistics", _spy_compute_bar_statistics)
    monkeypatch.setattr(m2, "_query_baseline", lambda symbol, tf: small_bars)

    m2.compute_time_bar_for_symbol("BTCUSDT", time_stop_ms=123_456, ljung_box_lags=10)

    assert len(received_time_stop_ms) == len(TIMEFRAMES)
    assert len(set(received_time_stop_ms)) == 1
    assert received_time_stop_ms[0] == 123_456


def test_time_stop_reference_tf_e_15m() -> None:
    """Trava o TF de referência -- `time_stop_bars=32` só significa "1
    janela de funding" (8h) se convertido via `step_ms("15m")`. Mudar
    esta constante sem reavaliar `time_stop_bars` quebraria essa
    equivalência silenciosamente."""
    assert m2.TIME_STOP_REFERENCE_TF == "15m"
