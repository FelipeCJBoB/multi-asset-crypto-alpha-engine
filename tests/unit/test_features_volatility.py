"""Testes de `src/features/volatility.py` -- `VolatilityEstimator`
(PRD_V4_1.md T0.1) e o lineup atual do harness de comparação (GK baseline +
Parkinson/Rogers-Satchell/Yang-Zhang, decisão do Manager 2026-08-11 -- ver
docstring de `src.analysis.volatility_comparison`), mais `Bars`
(grade de tempo vs. grade dollar-bar, AG-036) e `RealizedVolEstimator`
(resgatado, AG-036 -- primeiro dos 3 candidatos amputados readaptado pra
grade dollar-bar). Eixos: (1) unit puro com barras sintéticas, comparando
cada `*Estimator` contra a primitiva `support.*` chamada direto (garante
que o wrapper não introduz nenhuma transformação além do que o docstring
declara); (2) golden bit-exato de `ATRWilderEstimator` contra
`data/labels/BTCUSDT/15m/v1/labels.parquet::atr_at_t0` (G-C0-1) --
recomputa ATR das mesmas `bars_15m` (BTCUSDT, `close_time == t0`,
`triple_barrier.py:573/576-577`) que o Label Engine usou e compara com
tolerância zero. `ATRWilderEstimator` continua no lineup só por causa
deste golden test (é bit-idêntica ao que roda em produção); não é mais o
baseline do harness de M1. Nenhum dos 4 estimadores do lineup atual tem
golden -- não são produção ainda, não existe artefato de referência pra
comparar; (3) `Bars.__post_init__` (exatamente 1 entre `timeframe_minutes`/
`resolution_id`) e a guarda `NotImplementedError` que as 5 implementações
de fórmula fechada levantam sob `resolution_id` (AG-036) -- prova que
`RealizedVolEstimator` é a exceção documentada.

Caminho migrado do legado `labels/v1/labels.parquet` pro layout chaveado
(T0.3, PRD_V4_1.md §3.1) nesta mesma rodada -- via
`src.validation.cpcv.load_labels_v1()`, o loader canônico único."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.data import lake
from src.features import support
from src.features.volatility import (
    ATRWilderEstimator,
    Bars,
    GarmanKlassEstimator,
    ParkinsonEstimator,
    RealizedVolEstimator,
    RogersSatchellEstimator,
    VolatilityEstimator,
    YangZhangEstimator,
)
from src.validation._paths import labels_symbol_tf_dir

_LABELS_PATH = labels_symbol_tf_dir("BTCUSDT", "v1") / "labels.parquet"


def _synthetic_bars(n: int = 40) -> pl.DataFrame:
    rng = np.random.default_rng(7)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = close + rng.normal(0, 0.1, n)
    return pl.DataFrame({"open": open_, "high": high, "low": low, "close": close})


# ============================================================================
# Bars.__post_init__ (AG-036 -- separação grade de TEMPO (timeframe_minutes)
# vs. grade DOLLAR-BAR (resolution_id), exatamente 1 dos 2 obrigatório)
# ============================================================================


def test_bars_rejeita_timeframe_minutes_e_resolution_id_ambos_none() -> None:
    with pytest.raises(ValueError, match="exatamente um"):
        Bars(frame=_synthetic_bars())


def test_bars_rejeita_timeframe_minutes_e_resolution_id_ambos_setados() -> None:
    with pytest.raises(ValueError, match="exatamente um"):
        Bars(frame=_synthetic_bars(), timeframe_minutes=15, resolution_id="R1")


def test_bars_aceita_so_timeframe_minutes() -> None:
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    assert bars.timeframe_minutes == 15
    assert bars.resolution_id is None


def test_bars_aceita_so_resolution_id() -> None:
    bars = Bars(frame=_synthetic_bars(), resolution_id="R1")
    assert bars.resolution_id == "R1"
    assert bars.timeframe_minutes is None


def test_bars_timeframe_minutes_15_continua_funcionando_identico() -> None:
    # Regressão de retrocompatibilidade -- todo caller real de Bars(...) no
    # repo hoje (volatility_comparison.py, triple_barrier.py,
    # m3_timeframe_choice.py, gk_vs_wilder_econ_regime_shift.py,
    # volatility_operational_effect.py) passa só timeframe_minutes=<int>
    # posicionalmente equivalente a este padrão -- precisa continuar
    # aceito sem erro, idêntico ao comportamento pré-AG-036.
    frame = _synthetic_bars()
    bars = Bars(frame=frame, timeframe_minutes=15)
    estimator = ATRWilderEstimator(window=5)
    got = estimator.estimate(bars, horizon_minutes=15)
    assert got.shape[0] == frame.height


def test_atr_wilder_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    estimator = ATRWilderEstimator(window=window)
    got = estimator.estimate(bars, horizon_minutes=15)

    high = frame["high"].to_numpy()
    low = frame["low"].to_numpy()
    close = frame["close"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        expected = support.atr_wilder(high, low, close, window) / close

    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_atr_wilder_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = ATRWilderEstimator(window=20)
    assert estimator.warmup_bars == 20
    assert estimator.estimator_id == "atr_wilder_w20"


def test_atr_wilder_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    # I2 (PRD §2.7): conversão clock-based entre TFs é escopo do M1, não
    # implementada aqui -- deve levantar, não fabricar um número.
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    estimator = ATRWilderEstimator(window=5)
    with pytest.raises(NotImplementedError):
        estimator.estimate(bars, horizon_minutes=30)


def test_from_constants_le_atr_window_de_constants_yaml() -> None:
    from src.features._constants import load_constant

    estimator = ATRWilderEstimator.from_constants()
    assert estimator.window == int(load_constant("atr_window"))


# ============================================================================
# ParkinsonEstimator / GarmanKlassEstimator
# (PRD_V4_1.md §3.2 M1 -- 2 dos 6 candidatos originais, ainda no lineup
# atual; wrappers finos sobre support.py; mesma disciplina de
# horizon_minutes/warmup_bars/estimator_id do ATRWilderEstimator)
# ============================================================================


def test_parkinson_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    got = ParkinsonEstimator(window=window).estimate(bars, horizon_minutes=15)
    expected = support.parkinson_vol(
        frame["high"].to_numpy(), frame["low"].to_numpy(), window
    )
    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_parkinson_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = ParkinsonEstimator(window=20)
    assert estimator.warmup_bars == 20
    assert estimator.estimator_id == "parkinson_w20"


def test_parkinson_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    with pytest.raises(NotImplementedError):
        ParkinsonEstimator(window=5).estimate(bars, horizon_minutes=30)


def test_garman_klass_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    got = GarmanKlassEstimator(window=window).estimate(bars, horizon_minutes=15)
    expected = support.garman_klass_vol(
        frame["high"].to_numpy(),
        frame["low"].to_numpy(),
        frame["open"].to_numpy(),
        frame["close"].to_numpy(),
        window,
    )
    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_garman_klass_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = GarmanKlassEstimator(window=20)
    assert estimator.warmup_bars == 20
    assert estimator.estimator_id == "garman_klass_w20"


def test_garman_klass_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    with pytest.raises(NotImplementedError):
        GarmanKlassEstimator(window=5).estimate(bars, horizon_minutes=30)


# ============================================================================
# RealizedVolEstimator (resgatado, AG-036 -- primeiro dos 3 candidatos
# amputados readaptado pra suportar as duas grades: os 3 testes originais
# abaixo, IDÊNTICOS ao pré-remoção (commit aec7b59), provam grade de TEMPO
# bit-exata; o 4º teste é NOVO, prova grade DOLLAR-BAR sem erro)
# ============================================================================


def test_realized_vol_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    got = RealizedVolEstimator(window=window).estimate(bars, horizon_minutes=15)

    close = frame["close"].to_numpy()
    n = close.shape[0]
    log_return = np.full(n, np.nan, dtype=np.float64)
    log_return[1:] = np.log(close[1:] / close[:-1])
    expected = support.realized_vol(log_return, window)

    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_realized_vol_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = RealizedVolEstimator(window=20)
    assert estimator.warmup_bars == 21  # +1: log_return[0] sempre NaN
    assert estimator.estimator_id == "realized_vol_w20"


def test_realized_vol_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    with pytest.raises(NotImplementedError):
        RealizedVolEstimator(window=5).estimate(bars, horizon_minutes=30)


@pytest.mark.parametrize("horizon_minutes", [1, 15, 30, 60, 9999])
def test_realized_vol_estimator_sob_grade_dollar_bar_nao_levanta(
    horizon_minutes: int,
) -> None:
    # AG-036 -- RealizedVolEstimator é a exceção documentada: sob
    # resolution_id (grade dollar-bar), a guarda de horizon_minutes não se
    # aplica (forecast é sempre "1 barra à frente", ver docstring da
    # classe) -- deve retornar forecast válido pra QUALQUER horizon_minutes,
    # sem levantar, ao contrário das 5 implementações de fórmula fechada.
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, resolution_id="R1")
    got = RealizedVolEstimator(window=window).estimate(bars, horizon_minutes=horizon_minutes)
    assert got.shape[0] == frame.height
    assert np.isfinite(got[~np.isnan(got)]).all()


# ============================================================================
# RogersSatchellEstimator / YangZhangEstimator (extensão PÓS-M1, decisão do
# Manager 2026-08-11 -- não são texto de PRD_V4_1.md §3.2, avaliados contra
# o vencedor de M1, Garman-Klass; mesma disciplina de wrapper fino sobre
# support.py dos 3 candidatos originais)
# ============================================================================


def test_rogers_satchell_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    got = RogersSatchellEstimator(window=window).estimate(bars, horizon_minutes=15)
    expected = support.rogers_satchell_vol(
        frame["high"].to_numpy(),
        frame["low"].to_numpy(),
        frame["open"].to_numpy(),
        frame["close"].to_numpy(),
        window,
    )
    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_rogers_satchell_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = RogersSatchellEstimator(window=20)
    assert estimator.warmup_bars == 20
    assert estimator.estimator_id == "rogers_satchell_w20"


def test_rogers_satchell_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    with pytest.raises(NotImplementedError):
        RogersSatchellEstimator(window=5).estimate(bars, horizon_minutes=30)


def test_rogers_satchell_bar_sem_pavio_contra_tendencia_da_termo_zero() -> None:
    # Propriedade que define Rogers-Satchell (1991): drift-independente --
    # uma barra que abre na mínima e fecha na máxima (sem pavio "contra a
    # tendência") contribui EXATAMENTE zero pro termo por barra, mesmo com
    # drift grande. `ln(H/C)*ln(H/O) + ln(L/C)*ln(L/O)` com O=L e C=H:
    # `ln(H/H)*ln(H/L) + ln(L/H)*ln(L/L) = 0*x + y*0 = 0`. Janela inteira
    # assim -> média zero -> sigma_RS = 0, valor exato, não aproximado.
    n = 6
    low = np.full(n, 100.0)
    high = np.full(n, 105.0)
    open_ = low.copy()  # abre na mínima
    close = high.copy()  # fecha na máxima -- tendência de alta pura, sem pavio contrário
    out = support.rogers_satchell_vol(high, low, open_, close, window=5)
    valid = out[~np.isnan(out)]
    assert valid.size > 0
    assert np.allclose(valid, 0.0, atol=1e-12)


def test_yang_zhang_estimator_bate_com_support_direto() -> None:
    frame = _synthetic_bars()
    window = 5
    bars = Bars(frame=frame, timeframe_minutes=15)
    got = YangZhangEstimator(window=window).estimate(bars, horizon_minutes=15)
    expected = support.yang_zhang_vol(
        frame["high"].to_numpy(),
        frame["low"].to_numpy(),
        frame["open"].to_numpy(),
        frame["close"].to_numpy(),
        window,
    )
    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(got[~both_nan], expected[~both_nan])
    assert np.array_equal(np.isnan(got), np.isnan(expected))


def test_yang_zhang_estimator_warmup_bars_e_estimator_id() -> None:
    estimator = YangZhangEstimator(window=20)
    assert estimator.warmup_bars == 21  # +1: overnight[0] sempre NaN (sem C_{-1})
    assert estimator.estimator_id == "yang_zhang_w20"


def test_yang_zhang_estimator_horizonte_diferente_do_nativo_levanta() -> None:
    bars = Bars(frame=_synthetic_bars(), timeframe_minutes=15)
    with pytest.raises(NotImplementedError):
        YangZhangEstimator(window=5).estimate(bars, horizon_minutes=30)


def test_yang_zhang_sem_gap_overnight_reduz_a_v_c_e_v_rs_ponderados() -> None:
    # Quando open[i] == close[i-1] pra toda barra (sem gap entre barras,
    # caso comum em kline contínuo), overnight_i = ln(O_i/C_{i-1}) = 0
    # sempre -> V_o = 0 -> sigma_YZ^2 = k*V_c + (1-k)*V_rs, sem o termo
    # overnight. Constrói `open` A PARTIR de `close` (caminho independente
    # de `yang_zhang_vol`) pra não ser um reteste tautológico da mesma
    # implementação.
    window = 6
    rng = np.random.default_rng(23)
    n = 30
    close = 100.0 + np.cumsum(rng.normal(0, 0.4, n))
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]  # open[i] == close[i-1] -- gap zero por construção
    high = np.maximum(open_, close) + rng.uniform(0, 0.5, n)
    low = np.minimum(open_, close) - rng.uniform(0, 0.5, n)

    got = support.yang_zhang_vol(high, low, open_, close, window)

    rs = np.log(high / close) * np.log(high / open_) + np.log(low / close) * np.log(low / open_)
    oc = np.log(close / open_)
    # `overnight` reconstrói o MESMO deslocamento de `yang_zhang_vol`
    # (overnight[0] sempre NaN, sem C_{-1}) -- necessário pro padrão de NaN
    # bater com `got` mesmo com V_o valendo 0 em todo índice válido: o
    # warmup de V_o (janela fecha 1 índice DEPOIS de V_c/V_rs, por causa do
    # NaN inicial) ainda governa onde `got` é NaN, independente do valor.
    overnight = np.full(n, np.nan, dtype=np.float64)
    overnight[1:] = np.log(open_[1:] / close[:-1])
    v_o = (
        pl.Series(overnight)
        .rolling_std(window_size=window, min_samples=window, ddof=1)
        .to_numpy()
        ** 2
    )
    assert np.allclose(v_o[~np.isnan(v_o)], 0.0, atol=1e-12)  # sem gap -> overnight sempre 0
    v_c = (
        pl.Series(oc).rolling_std(window_size=window, min_samples=window, ddof=1).to_numpy() ** 2
    )
    v_rs = pl.Series(rs).rolling_mean(window_size=window, min_samples=window).to_numpy()
    k = 0.34 / (1.34 + (window + 1) / (window - 1))
    expected = np.sqrt(v_o + k * v_c + (1.0 - k) * v_rs)

    both_nan = np.isnan(got) & np.isnan(expected)
    assert np.array_equal(np.isnan(got), np.isnan(expected))
    assert np.allclose(got[~both_nan], expected[~both_nan], atol=1e-12)


# ============================================================================
# Guarda compartilhada de grade dollar-bar (AG-036) -- as 5 implementações
# de fórmula fechada (ATRWilder/Parkinson/GarmanKlass/RogersSatchell/
# YangZhang) ainda não foram readaptadas; devem levantar NotImplementedError
# citando AG-036/resolution_id sob Bars(resolution_id=...). Contraste direto
# com RealizedVolEstimator (seção acima), que NÃO levanta.
# ============================================================================


@pytest.mark.parametrize(
    "estimator",
    [
        ATRWilderEstimator(window=5),
        ParkinsonEstimator(window=5),
        GarmanKlassEstimator(window=5),
        RogersSatchellEstimator(window=5),
        YangZhangEstimator(window=5),
    ],
    ids=["atr_wilder", "parkinson", "garman_klass", "rogers_satchell", "yang_zhang"],
)
def test_estimadores_grade_de_tempo_levantam_sob_resolution_id(
    estimator: VolatilityEstimator,
) -> None:
    bars = Bars(frame=_synthetic_bars(), resolution_id="R1")
    with pytest.raises(NotImplementedError, match="AG-036"):
        estimator.estimate(bars, horizon_minutes=15)


def _skip_if_labels_missing() -> None:
    if not _LABELS_PATH.exists():
        pytest.skip(f"{_LABELS_PATH} ausente -- rode o Label Engine (Sprint 6) primeiro")


@pytest.mark.golden
@pytest.mark.integration
@pytest.mark.slow
def test_atr_wilder_estimator_bate_bit_exato_com_labels_v1() -> None:
    """G-C0-1 -- golden bit-exato contra o artefato persistido. Reconstrói
    a MESMA `bars_15m` (BTCUSDT) que o Label Engine usou e junta por `t0`
    (== `close_time`) em vez de confiar em alinhamento posicional entre
    dois DataFrames carregados de fontes diferentes.

    `t0` em `labels.parquet` já foi convertido pra `Datetime("ms")` UTC
    (`triple_barrier.py::_finalize_pre_weight_frame`, via `_ms_epoch_to_utc`)
    -- não é mais o Int64 ms epoch do schema pré-conversão. `close_time`
    de `bars_15m` (klines cru) ainda é Int64 ms epoch; convertido aqui do
    mesmo jeito pra bater tipo no join."""
    _skip_if_labels_missing()
    labels = pl.read_parquet(_LABELS_PATH, columns=["t0", "atr_at_t0"])
    start = labels["t0"].min().date()
    end = labels["t0"].max().date()

    bars_15m = lake.query_bars("BTCUSDT", "15m", start, end, source="klines_1m", cast_prices=True)
    estimator = ATRWilderEstimator.from_constants()
    bars = Bars(frame=bars_15m, timeframe_minutes=15)
    atr_pct = estimator.estimate(bars, horizon_minutes=15)

    t0_from_bars = (
        bars_15m["close_time"].cast(pl.Int64).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    )
    recomputed = pl.DataFrame({"t0": t0_from_bars, "atr_at_t0_recomputed": atr_pct})
    joined = labels.join(recomputed, on="t0", how="inner")
    assert joined.height > 0, "nenhum t0 de labels.parquet bateu com bars_15m reconstruído"

    left = joined["atr_at_t0"].to_numpy()
    right = joined["atr_at_t0_recomputed"].to_numpy()
    both_nan = np.isnan(left) & np.isnan(right)
    assert np.array_equal(left[~both_nan], right[~both_nan]), (
        "ATRWilderEstimator diverge bit-a-bit de atr_at_t0 persistido em labels/v1/labels.parquet"
    )
