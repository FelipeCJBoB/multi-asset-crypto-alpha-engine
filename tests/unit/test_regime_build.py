"""Testes de `src/regime/build.py` — o ponto de entrada com IO do Regime
Engine, contra dado real de `data/capacity/klines_1m/BTCUSDT/` (via as
features do Sprint 4, reusadas — não recalculadas).

`_FIXTURE_START`/`_FIXTURE_END` são a mesma janela de
`tests/unit/test_features_build.py` (41 dias, 3.936 barras de 15m, >> 2000
de warmup) — reuso deliberado da mesma fixture para não introduzir uma
terceira janela de referência no repo. `_FULL_START`/`_FULL_END` cobrem o
histórico completo medido no Sprint 5 (231.552 barras de 15m) para o teste
mais caro (distribuição real dos 5 regimes — o achado pedido pela task),
mesma classe de custo de `test_t1_ortogonalidade_spearman_2anos` em
`test_features_build.py`."""

from __future__ import annotations

import shutil
from typing import cast

import polars as pl
import pytest

from src.data._paths import CAPACITY_DIR
from src.regime import build, classifier
from src.regime._paths import REGIME_OUTPUT_DIR

_FIXTURE_START = "2024-01-01"
_FIXTURE_END = "2024-02-10"

_FULL_START = "2019-12-31"
_FULL_END = "2026-08-07"

_EXPECTED_COLUMNS = (
    "t0",
    "regime",
    "regime_raw",
    "er_48",
    "er_quantile",
    "vol_pctile",
    "bars_in_regime",
    "stress_triggers",
    "tradeable",
    "engine_version",
    "cost_atr_ratio",
    "econ_regime",
    "classifier_id",
)


def _skip_if_missing(day: str) -> None:
    path = CAPACITY_DIR / "klines_1m" / "BTCUSDT" / f"{day}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


def _assert_invariantes_484(df: pl.DataFrame) -> None:
    """§4.8, tradução literal para Polars."""
    assert df["regime"].cast(pl.Utf8).is_in(list(classifier.REGIME_LABELS)).all()
    assert (
        df["tradeable"] == df["regime"].cast(pl.Utf8).is_in(list(classifier.TRADEABLE_REGIMES))
    ).all()
    assert not df.filter(df["regime"] == "R5")["tradeable"].any()
    non_r5 = df.filter(df["regime"] != "R5")
    assert (non_r5["bars_in_regime"] >= 2).all()


# ============================================================================
# Schema / dtypes — §4.6
# ============================================================================


@pytest.mark.integration
def test_build_regimes_colunas_e_dtypes() -> None:
    _skip_if_missing(_FIXTURE_START)
    df = build.build_regimes("BTCUSDT", _FIXTURE_START, _FIXTURE_END)

    assert df.columns == list(_EXPECTED_COLUMNS)
    assert df.schema["t0"] == pl.Datetime("ns", "UTC")
    assert df.schema["regime"] == pl.Enum(list(classifier.REGIME_LABELS))
    assert df.schema["regime_raw"] == pl.Enum(list(classifier.REGIME_LABELS))
    assert df.schema["er_48"] == pl.Float64
    assert df.schema["er_quantile"] == pl.Float64
    assert df.schema["vol_pctile"] == pl.Float64
    assert df.schema["bars_in_regime"] == pl.Int32
    assert df.schema["stress_triggers"] == pl.List(pl.Utf8)
    assert df.schema["tradeable"] == pl.Boolean
    assert df.schema["engine_version"] == pl.Utf8
    assert (df["engine_version"] == classifier.ENGINE_VERSION).all()
    assert df.schema["classifier_id"] == pl.Utf8
    qrc = classifier.QuantileRegimeClassifier(symbol="BTCUSDT")
    assert (df["classifier_id"] == qrc.classifier_id).all()
    assert df.height == 3936


@pytest.mark.integration
def test_build_regimes_t0_e_open_time_alinhado() -> None:
    _skip_if_missing(_FIXTURE_START)
    df = build.build_regimes("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    # t0 estritamente crescente e sem duplicata — mesma grade de 15m das features
    diffs = df["t0"].diff().drop_nulls()
    assert (diffs.dt.total_milliseconds() == 900_000).all()


# ============================================================================
# Invariantes §4.8 — dado real
# ============================================================================


@pytest.mark.integration
def test_build_regimes_invariantes_484_dado_real() -> None:
    _skip_if_missing(_FIXTURE_START)
    df = build.build_regimes("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    _assert_invariantes_484(df)


@pytest.mark.integration
def test_build_regimes_determinismo() -> None:
    _skip_if_missing(_FIXTURE_START)
    out1 = build.build_regimes("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    out2 = build.build_regimes("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    assert out1.equals(out2, null_equal=True)


# ============================================================================
# Escrita atômica — B29
# ============================================================================


@pytest.mark.integration
def test_write_regimes_atomic_roundtrip() -> None:
    _skip_if_missing(_FIXTURE_START)
    df = build.build_regimes("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    version = "test_sprint5_roundtrip_tmp"
    dest_dir = REGIME_OUTPUT_DIR / version
    try:
        path = build.write_regimes_atomic(df, version=version)
        assert path.exists()
        assert not path.with_name(path.name + ".tmp").exists()  # .tmp não sobra
        reloaded = pl.read_parquet(path)
        assert reloaded.equals(df, null_equal=True)
    finally:
        shutil.rmtree(dest_dir, ignore_errors=True)


def test_write_regimes_atomic_dest_dir_override_usa_layout_chaveado(tmp_path) -> None:
    df = pl.DataFrame({"t0": [1], "regime": ["R0"]})
    keyed_dir = tmp_path / "ETHUSDT" / "15m" / classifier.ENGINE_VERSION
    dest = build.write_regimes_atomic(df, dest_dir=keyed_dir)
    assert dest == keyed_dir / "regimes.parquet"
    assert dest.exists()


# ============================================================================
# Histórico completo — achado pedido pela task: distribuição real dos 5
# regimes. Também é a validação mais forte das invariantes (231.552 barras
# reais, não sintéticas).
# ============================================================================


@pytest.mark.slow
@pytest.mark.integration
def test_build_regimes_distribuicao_historico_completo() -> None:
    _skip_if_missing(_FULL_START)
    df = build.build_regimes("BTCUSDT", _FULL_START, _FULL_END)
    assert df.height == 231_552

    _assert_invariantes_484(df)

    # UMA chamada só a `value_counts()`, depois extrai as duas colunas do
    # MESMO DataFrame resultante — duas chamadas separadas não têm ordem de
    # linha garantida entre si (agregação hash paralela do Polars: medido
    # neste Sprint, a mesma série produz ordens de linha DIFERENTES em
    # chamadas sucessivas), então `zip` de duas chamadas separadas pode
    # emparelhar rótulo com contagem errada silenciosamente.
    regime_vc = df["regime"].value_counts()
    regime_labels = regime_vc["regime"].cast(pl.Utf8).to_list()
    counts = dict(zip(regime_labels, regime_vc["count"].to_list(), strict=True))
    print("\nDistribuição real dos regimes — histórico completo (2019-12-31 a 2026-08-07):")
    for label in classifier.REGIME_LABELS:
        n = counts.get(label, 0)
        print(f"  {label}: {n} barras ({n / df.height:.4%})")

    # R0 é exatamente min_warmup_bars — não uma medição, uma consequência
    # direta do corte por índice.
    assert counts.get("R0", 0) == 2000
    # regimes tradeáveis (R1-R4) dominam a série — sanity check de que a
    # máquina de estado não degenerou (ex.: travada num único regime, ou
    # R5 dominando por um bug de histerese assimétrica invertida).
    tradeable_frac_raw = df["tradeable"].mean()
    assert tradeable_frac_raw is not None
    tradeable_frac = float(cast(float, tradeable_frac_raw))
    assert tradeable_frac > 0.80

    # Achado do Sprint 5 (medido, ver src/regime/stress.py::s06_bar_gap):
    # a grade de 15m derivada de klines_1m não tem NENHUMA barra ausente
    # em toda a história do projeto — trava esse resultado como regressão.
    n_s6_triggered = sum(1 for row in df["stress_triggers"] if "S6" in row)
    assert n_s6_triggered == 0

    max_bars_in_regime = cast(int, df["bars_in_regime"].max())
    print(f"\nfração tradeable: {tradeable_frac:.4%}")
    print(f"bars_in_regime máximo: {max_bars_in_regime}")
    econ_vc = df["econ_regime"].value_counts()
    econ_labels = econ_vc["econ_regime"].cast(pl.Utf8).to_list()
    econ_counts = dict(zip(econ_labels, econ_vc["count"].to_list(), strict=True))
    print("Distribuição do eixo econômico (§4.3.1):")
    for label, n in econ_counts.items():
        print(f"  {label}: {n} ({n / df.height:.4%})")
