"""Testes de `src/features/build.py` — invariantes §2.15 do PRD que operam
sobre o vetor T1 inteiro (não uma feature isolada): determinismo (1),
warmup uniforme (5) e ortogonalidade de T1 (6). Também valida
`src/features/registry.yaml` contra o formato §2.14 e contra o conjunto
real de features implementadas.

`test_t1_ortogonalidade_spearman_2anos` é o teste mais caro (roda sobre
~2 anos de dado real, dezenas de milhares de barras de 15m) — reporta a
matriz completa via `-s`/log em caso de violação, não só falha muda."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
import structlog
import yaml

from src.data._paths import CAPACITY_DIR
from src.data.resample import step_ms
from src.features import _sources, build
from src.features import registry as features_registry
from src.features.groups import group_e

_FIXTURE_START = "2024-01-01"
_FIXTURE_END = "2024-02-10"  # 41 dias -> 3936 barras de 15m, >> 200 de warmup

_CORR_START = "2024-08-08"
_CORR_END = "2026-08-07"  # ~2 anos, janela pedida pela task para ortogonalidade real

# 5 símbolos do universo (Binance USDⓈ-M, PLANO_MESTRE_PRINCE2.md §15) --
# mesmo conjunto de `src.labels.backfill_multi_symbol.ALL_SYMBOLS`. Testes
# de integração abaixo parametrizam sobre estes 5 (achado F4,
# audit_engineering): rodam de verdade contra qualquer símbolo com backfill
# local presente, skip individual (não a suíte inteira) pros ausentes --
# nunca dado sintético no lugar do backfill real ausente.
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def _skip_if_missing(symbol: str, day: str) -> None:
    path = CAPACITY_DIR / "klines_1m" / symbol / f"{day}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


# ============================================================================
# 1. Determinismo
# ============================================================================


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_determinismo_bit_a_bit(symbol: str) -> None:
    _skip_if_missing(symbol, _FIXTURE_START)
    out1 = build.build_t1_features(symbol, _FIXTURE_START, _FIXTURE_END)
    out2 = build.build_t1_features(symbol, _FIXTURE_START, _FIXTURE_END)
    assert out1.equals(out2, null_equal=True)


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_determinismo_hash(symbol: str) -> None:
    """`hash(build(data, cfg, v1)) == hash(build(data, cfg, v1))` — §2.15
    invariante 3, literal: hash sobre os bytes do resultado."""
    _skip_if_missing(symbol, _FIXTURE_START)
    out1 = build.build_t1_features(symbol, _FIXTURE_START, _FIXTURE_END)
    out2 = build.build_t1_features(symbol, _FIXTURE_START, _FIXTURE_END)
    h1 = hash(out1.hash_rows(seed=0).to_list().__repr__())
    h2 = hash(out2.hash_rows(seed=0).to_list().__repr__())
    assert h1 == h2


# ============================================================================
# 5. Warmup uniforme
# ============================================================================


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_warmup_uniforme_todas_nulas_antes_do_corte(symbol: str) -> None:
    """`warmup=200` -- `min_warmup_bars` recalculado por fórmula (AG-027,
    2026-08-15, `config/constants.yaml`), não mais os 2000 herdados do PRD
    sem justificativa. Este teste nunca tinha sido re-rodado desde essa
    mudança (achado real via pytest do usuário, 2026-08-16) -- ficou
    hardcoded no valor antigo por uma sessão inteira sem ninguém notar."""
    _skip_if_missing(symbol, _FIXTURE_START)
    out = build.build_t1_features(symbol, _FIXTURE_START, _FIXTURE_END)
    warmup = 200
    assert out.height > warmup
    feature_cols = [c for c in out.columns if c not in ("open_time", "close_time")]
    head = out.head(warmup).select(feature_cols)
    for col in feature_cols:
        assert head[col].null_count() == warmup, f"{col} tem valor não-null antes do warmup"


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_warmup_uniforme_maioria_valida_depois_do_corte(symbol: str) -> None:
    """Depois do warmup, a esmagadora maioria das linhas deve ter todas as
    features T1 válidas — algumas poucas exceções pontuais são esperadas e
    documentadas (ex.: gap real de 45min com volume=0 em 2024-10-28,
    blips de sum_open_interest<=0 em metrics — ver relatório do Sprint 4),
    mas não devem dominar a amostra."""
    _skip_if_missing(symbol, _FIXTURE_START)
    out = build.build_t1_features(symbol, _FIXTURE_START, _FIXTURE_END)
    tail = out.tail(out.height - 200)  # min_warmup_bars real, ver AG-027
    t1_cols = list(build.T1_FEATURE_IDS)
    n_fully_valid = tail.select(t1_cols).drop_nulls().height
    assert n_fully_valid / tail.height > 0.95

    # Lote A (H5, 2026-08-24, achado do audit_engineering): este teste só
    # cobria T1_FEATURE_IDS -- as 47 T2 novas (e as 3 T2 pré-existentes,
    # C01/C02/B07) nunca tinham essa checagem, mesmo warmup-mask sendo
    # aplicado uniformemente (build.py::apply_min_warmup_mask) a TODA
    # coluna de feature, não só T1. Reusa o mesmo agrupamento do teste de
    # paridade (tests/parity/test_features_parity.py), não uma tupla nova.
    support_cols = list(build.SUPPORT_FEATURE_IDS)
    n_fully_valid_support = tail.select(support_cols).drop_nulls().height
    assert n_fully_valid_support / tail.height > 0.95


def test_feature_windows_min_common_history_bars_from_constants() -> None:
    """AG-030 (T0.5): min_common_history_bars_15m, config/constants.yaml --
    ~164.256 barras de 15m = histórico comum mínimo entre os 5 ativos
    (2021-12-01 -> 2026-08-07, teto do alt mais novo; ver AG-030 no
    architecture_gaps_log.yaml e o comentário da constante)."""
    windows = build.FeatureWindows.from_constants()
    assert windows.min_common_history_bars == 164256


# ============================================================================
# `feature_a13_ema_window` (`scaling_invariant: clock`, AG-043 F3) --
# conversão clock<->bar-count, único campo de `FeatureWindows` afetado por
# `bar_source`. 2026-08-23.
# ============================================================================


def test_clock_reference_bar_duration_ms_time_15m_e_bit_exato() -> None:
    assert build._clock_reference_bar_duration_ms("time_15m") == step_ms("15m")


@pytest.mark.parametrize(
    ("bar_source", "calibration_tf"),
    [("dollar_r1", "15m"), ("dollar_r2", "30m"), ("dollar_r3", "1h")],
)
def test_clock_reference_bar_duration_ms_usa_calibration_tf_by_resolution(
    bar_source: str, calibration_tf: str
) -> None:
    """Usa `CALIBRATION_TF_BY_RESOLUTION` (alvo FIXO de calibração) -- NUNCA
    uma duração medida (AG-043 F2, rejeitado pelo Manager). Cross-checa
    contra o mesmo dict que `src.data.build_dollar_bars` já expõe, não
    duplica o valor esperado como literal solto."""
    assert build._clock_reference_bar_duration_ms(bar_source) == step_ms(calibration_tf)


def test_clock_reference_bar_duration_ms_bar_source_desconhecido_levanta_valueerror() -> None:
    with pytest.raises(ValueError, match="time_15m"):
        build._clock_reference_bar_duration_ms("dollar_r4")


def test_scale_clock_window_bars_ratio_1_e_bit_exato() -> None:
    assert build._scale_clock_window_bars(48, step_ms("15m")) == 48


def test_scale_clock_window_bars_escala_conforme_formula_do_manager() -> None:
    """`96@15m -> 48@30m -> 24@1h` (constants.yaml::feature_a13_ema_window,
    2026-08-16) -- aqui com o valor real de A13 (48, não o 96 ilustrativo
    do comentário original): 48@15m -> 24@30m -> 12@1h."""
    assert build._scale_clock_window_bars(48, step_ms("30m")) == 24
    assert build._scale_clock_window_bars(48, step_ms("1h")) == 12


def test_scale_clock_window_bars_piso_de_1_barra() -> None:
    assert build._scale_clock_window_bars(1, step_ms("1h") * 100) == 1


def test_feature_windows_from_constants_bar_source_time_15m_ema_window_bit_exato() -> None:
    windows = build.FeatureWindows.from_constants(bar_source="time_15m")
    assert windows.ema_window == 48


@pytest.mark.parametrize(
    ("bar_source", "expected_ema_window"),
    [("dollar_r1", 48), ("dollar_r2", 24), ("dollar_r3", 12)],
)
def test_feature_windows_from_constants_escala_ema_window_sob_resolution(
    bar_source: str, expected_ema_window: int
) -> None:
    windows = build.FeatureWindows.from_constants(bar_source=bar_source)
    assert windows.ema_window == expected_ema_window


@pytest.mark.parametrize("bar_source", ["dollar_r1", "dollar_r2", "dollar_r3"])
def test_feature_windows_from_constants_so_ema_window_muda_sob_resolution(
    bar_source: str,
) -> None:
    """As outras 9 janelas de `FeatureWindows` são `scaling_invariant:
    bar_count`/normalização -- decisão deliberada e específica de cada uma
    (AG-043), não escalam com `bar_source`. Prova campo a campo, não só
    `ema_window`, pra pegar regressão se um refactor futuro generalizar a
    conversão sem querer."""
    baseline = build.FeatureWindows.from_constants(bar_source="time_15m")
    scaled = build.FeatureWindows.from_constants(bar_source=bar_source)
    for field in dataclasses.fields(build.FeatureWindows):
        if field.name == "ema_window":
            continue
        assert getattr(scaled, field.name) == getattr(baseline, field.name), field.name


def test_feature_windows_from_constants_bar_source_desconhecido_levanta_valueerror() -> None:
    with pytest.raises(ValueError, match="time_15m"):
        build.FeatureWindows.from_constants(bar_source="dollar_r4")


def test_compute_t1_features_min_common_history_bars_capa_c07_d03f_e02f() -> None:
    """AG-030 (T0.5): com um cap menor que `n`, as primeiras `n - cap`
    barras de C07/D03f/E02f ficam nulas (janela expansiva recomeça no novo
    "início") -- as outras 9 colunas T1/T2 não são afetadas (não usam
    `min_common_history_bars`), provado comparando byte-a-byte contra uma
    rodada sem cap (`windows` default de `from_constants()`).

    `n=200`/`cap=100` (não um par pequeno tipo 40/15): `C07` depende de
    `realized_vol(window=48)` computada ANTES do posto expansivo -- com
    `n` pequeno essa janela de 48 barras nem teria convergido ainda,
    contaminando o teste (toda a coluna já sairia NaN mesmo sem cap nenhum,
    e o teste "passaria" sem provar nada sobre o mecanismo do AG-030).
    `offset = n - cap = 100 > 48` garante que a janela de 48 já convergiu
    bem antes do ponto de corte do cap."""
    n = 200
    cap = 100
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(83)
    # variância real de propósito (não constante) -- E02f é z-score expansivo
    # de Welford, que fica NaN o tempo todo (var==0) sobre série constante,
    # o que mascararia o efeito do cap sendo testado aqui.
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)

    windows_sem_cap = build.FeatureWindows.from_constants()
    windows_com_cap = dataclasses.replace(windows_sem_cap, min_common_history_bars=cap)

    out_sem_cap = build.compute_t1_features(
        bars, funding, oi, windows=windows_sem_cap, apply_warmup_mask=False
    )
    out_com_cap = build.compute_t1_features(
        bars, funding, oi, windows=windows_com_cap, apply_warmup_mask=False
    )

    # **Mudou em 2026-08-26 (AG-300).** Ate aqui a asserção usava
    # `.is_nan()`: os arrays numpy entravam em `pl.DataFrame(columns)` com
    # `np.nan` cru, e `NaN`/`null` coexistiam no mesmo Float64. Desde a
    # correcao de fronteira (`nan_to_null=True`) so existe `null` -- que e
    # exatamente o ponto: `is_not_null()`, o filtro de warmup, passa a
    # filtrar de verdade. `.is_nan()` sobre uma coluna sem NaN devolve
    # `null`, e `.sum()` ignora nulls, entao a asserção antiga daria 0.
    for col in ("C07_vol_pctile_expanding", "D03f_volume_z_expanding", "E02f_funding_z_expanding"):
        head_null_count = out_com_cap.head(n - cap)[col].null_count()
        assert head_null_count == n - cap, f"{col}: esperava {n - cap} null no início do cap"
        # sem cap, o mesmo trecho inicial NÃO deve estar 100% nulo (prova
        # de que o cap muda o resultado, não é um no-op)
        assert out_sem_cap.head(n - cap)[col].null_count() < n - cap

    # todas as outras colunas T1/T2 (não usam min_common_history_bars) têm
    # que sair IDÊNTICAS com ou sem cap -- prova de isolamento do efeito
    cols_afetadas = {
        "C07_vol_pctile_expanding",
        "D03f_volume_z_expanding",
        "E02f_funding_z_expanding",
        # Lote A (H5, 2026-08-24) -- C09/C10/C11 também repassam
        # min_common_history_bars pra expanding_percentile_rank_strict
        # (mesmo mecanismo de C07), ver build.py::compute_t1_features.
        "C09_range_pctile_expanding",
        "C10_vol_expansion_flag",
        "C11_vol_compression_flag",
    }
    outros_cols = [c for c in build.ALL_OUTPUT_COLUMNS if c not in cols_afetadas]
    assert out_sem_cap.select(outros_cols).equals(out_com_cap.select(outros_cols), null_equal=True)


def _make_synthetic_bars_for_cap_test(n: int) -> pl.DataFrame:
    rng = np.random.default_rng(81)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.5, n)
    volume = rng.uniform(10, 100, n)
    taker_buy_volume = volume * rng.uniform(0.3, 0.7, n)
    count = rng.uniform(10, 100, n)  # Lote A (H5, 2026-08-24) -- D08f/D09f exigem number_of_trades
    open_time = np.arange(n, dtype=np.int64) * 900_000
    close_time = open_time + 899_999
    return pl.DataFrame(
        {
            "open_time": open_time,
            "close_time": close_time,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "taker_buy_volume": taker_buy_volume,
            "count": count,
        }
    )


# ============================================================================
# vol_estimator_id — C01 sob Parkinson (2026-08-17, Fase 2, AG-036/065/074)
# ============================================================================


def test_compute_t1_features_vol_estimator_id_none_e_atr_wilder_explicito_sao_bit_exatos() -> None:
    """`vol_estimator_id=None` (default) e o id explícito equivalente
    (`f"atr_wilder_w{atr_window}"`) têm que produzir o MESMO resultado --
    o id explícito existe pra simetria com o caminho Parkinson, não pra
    mudar comportamento."""
    n = 200
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(71)
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)
    windows = build.FeatureWindows.from_constants()

    out_default = build.compute_t1_features(
        bars, funding, oi, windows=windows, apply_warmup_mask=False
    )
    out_explicito = build.compute_t1_features(
        bars,
        funding,
        oi,
        windows=windows,
        apply_warmup_mask=False,
        vol_estimator_id=f"atr_wilder_w{windows.atr_window}",
    )
    assert out_default.equals(out_explicito, null_equal=True)


def test_compute_t1_features_vol_estimator_id_parkinson_muda_c01_preserva_resto() -> None:
    """`vol_estimator_id="parkinson_w{N}"` muda C01_atr_20 (e, por herança,
    toda feature que consome `atr_20_abs`/`atr_20_pct` -- C02/A05/A13/E27f
    do vetor T1, mais A06/A14/B04/B05/B06 do Lote A, H5/2026-08-24), mas
    NÃO muda nenhuma outra coluna T1/T2 (B01, B07, C06, C07, D03f, D06f,
    E02f, E10f não dependem de C01)."""
    n = 200
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(72)
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)
    windows = build.FeatureWindows.from_constants()

    out_wilder = build.compute_t1_features(
        bars, funding, oi, windows=windows, apply_warmup_mask=False
    )
    out_parkinson = build.compute_t1_features(
        bars,
        funding,
        oi,
        windows=windows,
        apply_warmup_mask=False,
        vol_estimator_id=f"parkinson_w{windows.atr_window}",
    )

    cols_afetadas = {
        "C01_atr_20",
        "C02_atr_20_pct",
        "A05_ret_vol_norm_4",
        "A13_dist_ema48_atr",
        "E27f_cost_atr_ratio",
        # Lote A (H5, 2026-08-24) -- também consomem atr_20_abs/atr_20_pct
        "A06_ret_vol_norm_12",
        "A14_dist_ema12_atr",
        "B04_macd_hist_norm",
        "B05_ema_slope_24",
        "B06_momentum_accel",
        # Lote B (H5, 2026-08-24) -- idem
        "A15_dist_vwap_d_atr",
    }
    for col in cols_afetadas:
        valid = ~out_wilder[col].is_nan() & ~out_parkinson[col].is_nan()
        assert valid.sum() > 0
        assert not out_wilder[col].filter(valid).equals(out_parkinson[col].filter(valid)), col

    outros_cols = [c for c in build.ALL_OUTPUT_COLUMNS if c not in cols_afetadas]
    assert out_wilder.select(outros_cols).equals(
        out_parkinson.select(outros_cols), null_equal=True
    )


def test_compute_t1_features_vol_estimator_id_invalido_levanta_valueerror() -> None:
    n = 50
    bars = _make_synthetic_bars_for_cap_test(n)
    funding = pl.Series("f", [None] * n, dtype=pl.Float64)
    oi = pl.Series("oi", [None] * n, dtype=pl.Float64)
    with pytest.raises(ValueError, match="vol_estimator_id"):
        build.compute_t1_features(
            bars, funding, oi, apply_warmup_mask=False, vol_estimator_id="garman_klass_w20"
        )


def test_build_t1_features_desabilita_min_common_history_bars_sob_bar_source_nao_time15m(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fase 2 (2026-08-17), decisão registrada na docstring de
    `build_t1_features`: `min_common_history_bars_15m` (AG-030, calibrado
    em contagem de barra de TEMPO) não é comparável cross-asset sob dollar
    bar -- `build_t1_features` desabilita o cap
    (`windows.min_common_history_bars = None`) sempre que `bar_source !=
    "time_15m"`, em vez de herdar o número silenciosamente. Monkeypatch de
    IO (`_sources.load_bars`/etc.) e de `FeatureWindows.from_constants`
    (cap pequeno o bastante pra ser observável em `n=200`) -- não depende
    de backfill local nem é `integration`."""
    n = 200
    cap = 100
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(73)
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)

    windows_com_cap = dataclasses.replace(
        build.FeatureWindows.from_constants(), min_common_history_bars=cap
    )
    monkeypatch.setattr(
        build.FeatureWindows,
        "from_constants",
        staticmethod(lambda *, bar_source="time_15m": windows_com_cap),
    )
    monkeypatch.setattr(build._sources, "load_bars", lambda *a, **k: bars)
    monkeypatch.setattr(build._sources, "load_funding_aligned", lambda *a, **k: funding)
    monkeypatch.setattr(build._sources, "load_oi_aligned", lambda *a, **k: oi)

    out_time15m = build.build_t1_features(
        "BTCUSDT", "2024-01-01", "2024-01-01", apply_warmup_mask=False, bar_source="time_15m"
    )
    out_dollar = build.build_t1_features(
        "BTCUSDT", "2024-01-01", "2024-01-01", apply_warmup_mask=False, bar_source="dollar_r1"
    )

    for col in ("C07_vol_pctile_expanding", "D03f_volume_z_expanding", "E02f_funding_z_expanding"):
        # AG-300 -- `null_count()` em vez de `is_nan()`: a fronteira converte
        # NaN -> null (`nan_to_null=True`), ver nota no teste do cap acima.
        assert out_time15m.head(n - cap)[col].null_count() == n - cap, col
        assert out_dollar.head(n - cap)[col].null_count() < n - cap, col


# ============================================================================
# E10f_oi_change_z_48 -- correção AG-295 adotada em produção (2026-08-26):
# `oi_change_native_aligned` troca o caminho antigo (diferencia a série de
# OI já alinhada/repetida por barra) pelo novo (diferencia na cadência
# nativa da fonte, alinha o delta). `None` preserva bit-exato o antigo.
# ============================================================================


def test_compute_t1_features_oi_change_native_aligned_none_preserva_bit_exato() -> None:
    """Sem o argumento novo, `E10f` continua exatamente igual ao caminho
    antigo (`group_e.e10f_oi_change_z_48` sobre `oi_contracts_aligned`) --
    nenhum caller existente (que não passa o argumento) é afetado."""
    n = 300
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(91)
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)

    out = build.compute_t1_features(bars, funding, oi, apply_warmup_mask=False)
    esperado = group_e.e10f_oi_change_z_48(
        oi.to_numpy(), build.FeatureWindows.from_constants().e10f_window
    )
    got = out["E10f_oi_change_z_48"].to_numpy()
    np.testing.assert_allclose(got, esperado, equal_nan=True)


def test_compute_t1_features_oi_change_native_aligned_usa_caminho_novo_quando_passado() -> None:
    """Com o argumento novo, `E10f` usa `e10f_oi_change_z_48_from_native_
    delta` sobre o array passado -- NÃO diferencia `oi_contracts_aligned`
    de novo (o delta já vem pronto)."""
    n = 300
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(92)
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)
    oi_change_native = pl.Series("oi_change", rng.normal(0, 0.01, n), dtype=pl.Float64)

    out = build.compute_t1_features(
        bars, funding, oi, apply_warmup_mask=False, oi_change_native_aligned=oi_change_native
    )
    esperado = group_e.e10f_oi_change_z_48_from_native_delta(
        oi_change_native.to_numpy(), build.FeatureWindows.from_constants().e10f_window
    )
    got = out["E10f_oi_change_z_48"].to_numpy()
    np.testing.assert_allclose(got, esperado, equal_nan=True)
    # e diferente do caminho antigo, pra provar que a troca de fato aconteceu
    antigo = group_e.e10f_oi_change_z_48(
        oi.to_numpy(), build.FeatureWindows.from_constants().e10f_window
    )
    assert not np.allclose(got, antigo, equal_nan=True)


def test_build_t1_features_passa_oi_change_native_aligned_por_padrao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`build_t1_features` (casca de IO, produção real) SEMPRE carrega e
    passa `oi_change_native_aligned` -- é onde o corte de AG-295 acontece
    de fato, não em `compute_t1_features` isolada."""
    n = 200
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(93)
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)
    oi_change_native = pl.Series("oi_change", rng.normal(0, 0.01, n), dtype=pl.Float64)

    chamadas: dict[str, object] = {}
    original_compute = build.compute_t1_features

    def _spy_compute_t1_features(*args: Any, **kwargs: Any) -> pl.DataFrame:
        chamadas["oi_change_native_aligned"] = kwargs.get("oi_change_native_aligned")
        return original_compute(*args, **kwargs)

    monkeypatch.setattr(build, "compute_t1_features", _spy_compute_t1_features)
    monkeypatch.setattr(build._sources, "load_bars", lambda *a, **k: bars)
    monkeypatch.setattr(build._sources, "load_funding_aligned", lambda *a, **k: funding)
    monkeypatch.setattr(build._sources, "load_oi_aligned", lambda *a, **k: oi)
    monkeypatch.setattr(build._sources, "load_oi_change_aligned", lambda *a, **k: oi_change_native)

    build.build_t1_features("BTCUSDT", "2024-01-01", "2024-01-01", apply_warmup_mask=False)

    assert chamadas["oi_change_native_aligned"] is oi_change_native


# ============================================================================
# D07f_taker_imbalance_1m_agg -- Lote B da liberação de features (H5,
# 2026-08-24), única feature de SUPPORT_FEATURE_IDS com fonte de dado
# PRÓPRIA (klines_1m bruto). Os testes de paridade gerais (tests/parity/
# test_features_parity.py) chamam compute_t1_features SEM passar
# taker_imbalance_1m_agg_aligned (a coluna sai NaN o tempo todo ali, de
# propósito) -- este teste, escopo menor, exercita o caminho REAL
# (build_t1_features com load_taker_imbalance_1m=True, default de
# produção) contra dado real.
# ============================================================================


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_d07f_paridade_lote_streaming_prefixo_arbitrario(symbol: str) -> None:
    """Mesma técnica de `test_paridade_streaming_bate_com_recompute_do_
    zero_em_prefixo_arbitrario` (tests/parity/test_features_parity.py),
    escopo reduzido só a D07f -- janela curta (5 dias) pra controlar o
    custo real de IO de klines_1m (~15-60× mais linhas que bars_15m)."""
    _skip_if_missing(symbol, _FIXTURE_START)
    start, end = _FIXTURE_START, "2024-01-05"

    batch = build.build_t1_features(symbol, start, end, apply_warmup_mask=False)

    bars = _sources.load_bars(symbol, start, end, bar_source="time_15m")
    row_idx = min(300, bars.height - 1)
    assert row_idx > 200  # margem real de warmup

    sub_bars = bars.slice(0, row_idx + 1)
    funding = _sources.load_funding_aligned(sub_bars, symbol, start, end)
    oi = _sources.load_oi_aligned(sub_bars, symbol, start, end)
    taker_1m = _sources.load_taker_imbalance_1m_agg_aligned(sub_bars, symbol, start, end)
    windows = build.FeatureWindows.from_constants()
    stream_row = build.compute_t1_features(
        sub_bars,
        funding,
        oi,
        windows=windows,
        apply_warmup_mask=False,
        taker_imbalance_1m_agg_aligned=taker_1m,
    ).row(-1, named=True)
    batch_row = batch.row(row_idx, named=True)

    a = stream_row["D07f_taker_imbalance_1m_agg"]
    b = batch_row["D07f_taker_imbalance_1m_agg"]
    assert a is not None and b is not None
    assert not np.isnan(a)  # prova que o caminho real (klines_1m carregado) produz valor de verdade
    assert np.isclose(a, b, atol=1e-8, rtol=0), f"streaming={a} lote={b}"


def test_warmup_zero_barras_nao_quebra() -> None:
    windows = build.FeatureWindows.from_constants()
    bars = pl.DataFrame(
        {
            "open_time": [0, 900_000],
            "close_time": [899_999, 1_799_999],
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10.0, 12.0],
            "taker_buy_volume": [5.0, 6.0],
            "count": [7.0, 8.0],
        }
    )
    funding = pl.Series("f", [None, None], dtype=pl.Float64)
    oi = pl.Series("oi", [None, None], dtype=pl.Float64)
    out = build.compute_t1_features(bars, funding, oi, windows=windows)
    assert out.height == 2
    for c in build.T1_FEATURE_IDS:
        assert out[c].null_count() == 2


# ============================================================================
# 6. Ortogonalidade T1 — Spearman |corr| <= 0.70 fora da diagonal
# ============================================================================


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_t1_ortogonalidade_spearman_2anos(symbol: str) -> None:
    """§2.13: 'nenhum par em T1 pode ter |correlação de Spearman| > 0,70 na
    janela de treino'. Calculado aqui sobre ~2 anos reais (2024-08-08 a
    2026-08-07), não sintético — é exatamente o que a task pede para o
    relatório final. Reporta a matriz inteira via `pytest -s`, sempre.

    NÃO faz o teste falhar se houver violação — §2.13 já prevê o caso
    explicitamente: "Par que violar → o de menor importância por
    permutação sai e o próximo T2 candidato entra", e importância por
    permutação exige um modelo treinado (Sprint 6+, fora de escopo do
    Sprint 4). Medido em 2026-08-08 (BTCUSDT): 2 pares violam
    (`A13_dist_ema48_atr` x `B01_rsi_14` = 0,947; `E27f_cost_atr_ratio` x
    `C07_vol_pctile_expanding` = -0,913) — ambos plausíveis (A13/B01 são
    dois jeitos de medir força de tendência; E27f/C07 são duas leituras do
    mesmo regime de volatilidade por construção, custo/ATR e percentil de
    vol realizada). Reportado no relatório do Sprint 4 como resultado, não
    escondido — a resolução (ablação por importância de permutação) é
    tarefa do Sprint 6+. Parametrizado pros 5 símbolos (F4,
    audit_engineering) — violações por símbolo não são asserção travada
    aqui, só reportadas via print, mesma disciplina do caso BTCUSDT."""
    _skip_if_missing(symbol, _CORR_START)
    out = build.build_t1_features(symbol, _CORR_START, _CORR_END)
    t1_cols = list(build.T1_FEATURE_IDS)
    clean = out.select(t1_cols).drop_nulls()
    assert clean.height > 10_000  # amostra grande o bastante pra correlação ser informativa

    n = len(t1_cols)
    corr = np.eye(n)
    ranks = {c: clean[c].rank(method="average").to_numpy() for c in t1_cols}
    for i in range(n):
        for j in range(i + 1, n):
            r = np.corrcoef(ranks[t1_cols[i]], ranks[t1_cols[j]])[0, 1]
            corr[i, j] = corr[j, i] = r

    # sanidade estrutural da matriz em si (isto SIM tem que passar sempre —
    # uma falha aqui seria bug de cálculo, não achado de pesquisa)
    assert np.allclose(np.diag(corr), 1.0)
    assert np.allclose(corr, corr.T)
    assert np.nanmax(np.abs(corr)) <= 1.0 + 1e-9

    print(f"\nMatriz de correlação de Spearman — T1, {symbol}, 2024-08-08 a 2026-08-07:")
    header = "".ljust(28) + "".join(c[:10].rjust(11) for c in t1_cols)
    print(header)
    for i, ci in enumerate(t1_cols):
        row = ci.ljust(28) + "".join(f"{corr[i, j]:11.3f}" for j in range(n))
        print(row)

    violations = [
        (t1_cols[i], t1_cols[j], corr[i, j])
        for i in range(n)
        for j in range(i + 1, n)
        if abs(corr[i, j]) > 0.70
    ]
    for a, b, r in violations:
        print(
            f"VIOLACAO ORTOGONALIDADE (Sprint 6+ resolve por permutacao) [{symbol}]: "
            f"{a} x {b} = {r:.4f}"
        )
    if not violations:
        print(f"Nenhuma violação de ortogonalidade nesta janela [{symbol}].")


# ============================================================================
# registry.yaml — formato §2.14 + cobertura do conjunto implementado
# ============================================================================

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "src" / "features" / "registry.yaml"
_REQUIRED_FIELDS = {
    "id",
    "tier",
    "group",
    "formula",
    "sources",
    "lookback_bars",
    "min_warmup_bars",
    "tf",
    "dtype",
    "range",
    "nan_policy",
    "causal_proof",
    "parity_tested",
    "version",
    "added",
}


def _load_registry() -> list[dict[str, object]]:
    with _REGISTRY_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list)
    return data


def test_registry_existe_e_e_lista() -> None:
    entries = _load_registry()
    assert len(entries) > 0


def test_registry_todos_os_campos_obrigatorios_presentes() -> None:
    entries = _load_registry()
    for entry in entries:
        missing = _REQUIRED_FIELDS - entry.keys()
        assert not missing, f"{entry.get('id')}: faltam campos {missing}"


def test_registry_cobre_todo_o_vetor_t1() -> None:
    entries = _load_registry()
    ids_t1 = {e["id"] for e in entries if e["tier"] == "T1"}
    assert ids_t1 == set(build.T1_FEATURE_IDS)


def test_registry_tf_e_15m_em_todas_as_entradas() -> None:
    """Decisão de TF do Sprint 4 (ver NOTA DE TF no topo de registry.yaml e
    o relatório do Sprint 4): todas as entradas devem estar a 15m, batendo
    com `decision_tf` de §0.1 do PRD."""
    entries = _load_registry()
    for entry in entries:
        assert entry["tf"] == "15m", f"{entry['id']}: tf={entry['tf']}, esperado 15m"


def test_registry_parity_tested_true_em_todas_as_entradas() -> None:
    entries = _load_registry()
    for entry in entries:
        assert entry["parity_tested"] is True, entry["id"]


def test_registry_min_warmup_bars_bate_com_constants_yaml() -> None:
    """Doc-drift real corrigido 2026-08-23: as 13 entradas diziam
    `min_warmup_bars: 2000` (valor herdado do PRD, nunca lido em runtime --
    ver `registry.py::FeatureRegistryEntry.min_warmup_bars`, campo
    puramente documental), enquanto o valor real usado por
    `FeatureWindows.from_constants` é 200 (`constants.yaml`, recalculado
    por fórmula, AG-027 2026-08-15) desde antes do registry ter sido
    atualizado. Guarda mecânica pra não repetir -- se `min_warmup_bars` em
    `constants.yaml` mudar de novo sem atualizar `registry.yaml`, este
    teste pega."""
    entries = _load_registry()
    real_min_warmup_bars = build.FeatureWindows.from_constants().min_warmup_bars
    for entry in entries:
        assert entry["min_warmup_bars"] == real_min_warmup_bars, entry["id"]


# ============================================================================
# AG-032 item 8 (Fix A, 2026-08-21) -- max_feature_lookback_ms compartilhado
# (`compute_max_feature_lookback_ms`) + fail-fast de `lookback_bars:
# expanding` no conjunto ativo (opção A, decisão do Manager: nunca excluir
# a feature ofensora silenciosamente -- só forçar a decisão a ser tomada).
# ============================================================================


def _synthetic_windows_max_96() -> build.FeatureWindows:
    """Janelas sintéticas com um único campo (`vol_ratio_long_window=96`)
    maior que todos os outros -- inclusive maior que `min_warmup_bars`/
    `min_common_history_bars`, que `max_feature_window_bars` PRECISA
    ignorar (`min_common_history_bars=164_256`, AG-030, é justamente o
    número que uma rodada de correção anterior mediu como QUEBRANDO o CPCV
    -- 5/15 splits com treino vazio -- se usado cru como `max_feature_
    lookback_ms`, addendum AG-032 item 8). Se a exclusão de campos
    estivesse errada, este teste pegaria: 164_256 > 96."""
    return build.FeatureWindows(
        atr_window=1,
        ema_window=2,
        rsi_window=3,
        ret_lookback=4,
        vol_ratio_short_window=5,
        vol_ratio_long_window=96,
        c07_window=6,
        d06f_window=7,
        e10f_window=8,
        b07_window=9,
        maker_fee=0.0002,
        taker_fee=0.0005,
        min_warmup_bars=200,
        min_common_history_bars=164_256,
    )


def test_max_feature_window_bars_ignora_fees_e_warmup_usa_so_janelas() -> None:
    windows = _synthetic_windows_max_96()
    assert build.max_feature_window_bars(windows=windows) == 96


@pytest.mark.parametrize("tf", ["15m", "30m", "1h"])
def test_compute_max_feature_lookback_ms_converte_bars_via_step_ms(tf: str) -> None:
    """Conversão bars->ms para o `tf` testado.

    **Mudou em 2026-08-26 (`AG-296`):** a janela deixou de vir de
    `FeatureWindows` (os 10 campos de `_WINDOW_FIELD_NAMES`) e passa a vir
    do **registry**, sobre o conjunto ativo. O parâmetro `windows` saiu da
    assinatura por estar morto. O número não mudou: `T1_FEATURE_IDS` declara
    máximo 96 no registry (`C06_vol_ratio_12_96`), o mesmo 96 que
    `max_feature_window_bars()` devolvia — **o caminho legado é bit-exato**,
    e é isso que este teste agora trava."""
    assert build.max_feature_lookback_bars(build.T1_FEATURE_IDS) == 96
    assert build.max_feature_window_bars() == 96, "coincidência que preserva o legado bit-exato"
    got = build.compute_max_feature_lookback_ms(tf, build.T1_FEATURE_IDS)
    assert got == 96 * step_ms(tf)


def test_compute_max_feature_lookback_ms_resolution_id_usa_max_consecutive_constant() -> None:
    """D-02 (`AG-159`) -- `resolution_id` setado retorna
    `max_consecutive_bar_window_duration_ms` (`constants.yaml`, MEASURED
    direto, já é a duração TOTAL medida da janela). `tf` continua na
    assinatura mas não converte unidade sob dollar-bar."""
    max_window_duration_ms = int(build.load_constant("max_consecutive_bar_window_duration_ms"))
    got = build.compute_max_feature_lookback_ms(
        "15m", build.T1_FEATURE_IDS, resolution_id="R2"
    )
    assert got == max_window_duration_ms
    assert got != 96 * step_ms("15m")


def test_compute_max_feature_lookback_ms_sem_warning_quando_window_bars_bate() -> None:
    """`max_consecutive_bar_window_duration_ms` foi medido pra
    `window_bars=96`, e o `T1_FEATURE_IDS` real declara exatamente 96 no
    registry (`C06_vol_ratio_12_96`) -- não deve disparar staleness."""
    assert build.max_feature_lookback_bars(build.T1_FEATURE_IDS) == 96
    with structlog.testing.capture_logs() as logs:
        build.compute_max_feature_lookback_ms("15m", build.T1_FEATURE_IDS, resolution_id="R2")
    assert not [e for e in logs if e.get("log_level") == "warning"]


def test_compute_max_feature_lookback_ms_warning_quando_janela_e_MENOR_que_a_medida() -> None:
    """Conjunto ativo com janela MENOR que as 96 medidas: a constante
    SOBRE-protege (seguro), então avisa e devolve mesmo assim."""
    curto = ("A01_log_return_1", "A07_body_ratio")
    assert build.max_feature_lookback_bars(curto) < 96
    with structlog.testing.capture_logs() as logs:
        got = build.compute_max_feature_lookback_ms("15m", curto, resolution_id="R2")
    warnings = [e for e in logs if e.get("log_level") == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["event"] == "features.build.compute_max_feature_lookback_ms.constant_stale"
    assert got == int(build.load_constant("max_consecutive_bar_window_duration_ms"))


def test_compute_max_feature_lookback_ms_FALHA_quando_janela_e_MAIOR_que_a_medida() -> None:
    """**ADR-005 §13 v2 §13.1 / AG-296 -- o comportamento que mudou.**
    Até 2026-08-26 este caso emitia warning e devolvia a constante mesmo
    assim ("ainda protege, só não é o máximo exato"). Medido com o vetor
    real de produção: `C08_vol_pctile_rolling_1y` declara 17.520 barras
    contra as 96 para as quais a constante foi medida -- 182x. Uma
    sub-cobertura dessa ordem é vazamento de janela de feature (B02/B09),
    não imprecisão, e passa a falhar alto."""
    com_c08 = (*build.T1_FEATURE_IDS, "C08_vol_pctile_rolling_1y")
    assert build.max_feature_lookback_bars(com_c08) == 17_520
    with pytest.raises(build.StaleFeatureWindowConstantError) as exc:
        build.compute_max_feature_lookback_ms("15m", com_c08, resolution_id="R2")
    msg = str(exc.value)
    assert "17520" in msg and "182x" in msg
    assert "measure_max_consecutive_bar_window_duration.py" in msg


def test_max_feature_lookback_bars_ve_o_que_max_feature_window_bars_nao_ve() -> None:
    """O defeito de `§13.1`, travado: `max_feature_window_bars` lê os 10
    campos de `_WINDOW_FIELD_NAMES` e é cega a toda feature cuja janela
    não é uma daquelas constantes. `C08` (17.520), `E03f_funding_cum_3d`
    (288) e `B10_stoch_k_14` são exatamente esse caso."""
    vetor_producao = build.T1_FEATURE_IDS + build.SUPPORT_FEATURE_IDS
    assert build.max_feature_window_bars() == 96
    # o vetor real dispara antes de chegar ao número (5 features expanding)
    with pytest.raises(build.ExpandingFeatureLookbackError):
        build.max_feature_lookback_bars(vetor_producao)
    # sem as expanding, o alcance real aparece -- 182x o que a outra devolve
    sem_expanding = tuple(
        f for f in vetor_producao if features_registry.feature_lookback_bars()[f] != "expanding"
    )
    assert build.max_feature_lookback_bars(sem_expanding) == 17_520


def test_compute_max_feature_lookback_ms_gate_dispara_mesmo_com_resolution_id_setado() -> None:
    """Achado do `project_assurance` independente (2026-08-23, AG-181):
    nenhum teste provava que `assert_no_expanding_lookback_in_active_set`
    ainda dispara PRIMEIRO quando `resolution_id` é passado junto com um
    conjunto ativo que contém feature expanding. Um refactor futuro que
    reordenasse o cálculo de `bar_duration_ms` pra antes do gate passaria
    despercebido sem este teste. **Atualizado 2026-08-23 (AG-032):** o
    conjunto ativo REAL (`T1_FEATURE_IDS`, default) deixou de conter
    features expanding -- passa explicitamente um `feature_ids` que
    contém uma (mesmo padrão de `test_assert_no_expanding_lookback_
    dispara_para_feature_expanding_conhecida`) pra continuar provando a
    ORDEM (gate antes do cálculo de unidade), não mais o estado do
    default."""
    with pytest.raises(build.ExpandingFeatureLookbackError):
        build.compute_max_feature_lookback_ms(
            "15m", feature_ids=("C07_vol_pctile_expanding",), resolution_id="R2"
        )


def test_assert_no_expanding_lookback_passa_para_subconjunto_finito() -> None:
    """Nenhuma das duas features abaixo é `expanding` no registry real --
    não deve levantar."""
    build.assert_no_expanding_lookback_in_active_set(("C06_vol_ratio_12_96", "B01_rsi_14"))


def test_assert_no_expanding_lookback_dispara_para_feature_expanding_conhecida() -> None:
    with pytest.raises(build.ExpandingFeatureLookbackError, match="C07_vol_pctile_expanding"):
        build.assert_no_expanding_lookback_in_active_set(
            ("C06_vol_ratio_12_96", "C07_vol_pctile_expanding")
        )


def test_compute_max_feature_lookback_ms_nao_dispara_para_t1_feature_ids_real() -> None:
    """AG-032 item 8 -- **invertido 2026-08-23** (decisão do Manager: as 3
    features expanding conhecidas, C07/D03f/E02f, SAÍRAM de
    `T1_FEATURE_IDS`). Até 2026-08-23 este teste provava o oposto (que o
    mecanismo disparava contra o default) -- comportamento ANTIGO,
    intencionalmente mudado, não regressão. Prova agora que o conjunto
    ativo REAL (`T1_FEATURE_IDS`, default) roda de verdade sem levantar
    `ExpandingFeatureLookbackError` -- o caminho que `pipeline.py`/
    `leakage.py` usam de verdade deixou de estar bloqueado."""
    got = build.compute_max_feature_lookback_ms("15m", build.T1_FEATURE_IDS)
    assert got == build.max_feature_lookback_bars(build.T1_FEATURE_IDS) * step_ms("15m")


def test_compute_max_feature_lookback_ms_dispara_para_feature_ids_customizado_expanding() -> None:
    """O gate continua protegendo qualquer chamador que passe um
    `feature_ids` customizado incluindo uma das 3 expanding (ex. análise
    pós-hoc via `extra_feature_ids`, `src.models.dataset.
    build_modeling_frame`) -- só o caminho DEFAULT parou de disparar."""
    with pytest.raises(build.ExpandingFeatureLookbackError) as exc_info:
        build.compute_max_feature_lookback_ms(
            "15m", feature_ids=(*build.T1_FEATURE_IDS, "E02f_funding_z_expanding")
        )
    msg = str(exc_info.value)
    assert "E02f_funding_z_expanding" in msg
