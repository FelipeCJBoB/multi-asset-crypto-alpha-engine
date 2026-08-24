"""Teste de paridade lote/streaming do Feature Engine T1 — §2.15 invariante
4 ("a mais cara e a mais importante").

Design deliberado, ligado ao princípio 3 do §2.0 ("caminho único... não
existem duas implementações"): `src.features.build.compute_t1_features` é
uma função pura, sem estado, estritamente causal (toda janela olha só para
`<= t` ou `< t`, nunca para o futuro — provado feature a feature em
`tests/unit/test_features_support.py` e `test_features_groups.py`). Isso
significa que processar "em streaming, barra a barra" e processar "em
lote" não precisam de duas implementações: bastam chamadas SUCESSIVAS da
MESMA função sobre PREFIXOS CRESCENTES de `bars_15m` — a chamada na barra
`t` só pode enxergar `bars_15m[:t+1]`, exatamente a mesma informação que a
chamada em lote tem disponível até `t`.

Consequência que este teste também aproveita: se qualquer feature tivesse
um bug de lookahead (ex.: um scaler ajustado no dataset inteiro em vez de
expansivo), o valor calculado sobre o prefixo truncado divergiria do valor
calculado em lote sobre a série completa — a paridade streaming/lote aqui
funciona como uma segunda prova de causalidade, independente dos testes
unitários de `support.py`/`groups/`."""

from __future__ import annotations

import numpy as np
import pytest

from src.data._paths import CAPACITY_DIR
from src.features import _sources, build

_FIXTURE_START = "2024-01-01"
_FIXTURE_END = "2024-02-10"  # 41 dias -> 3936 barras de 15m
_N_TAIL = 500  # §16.10 DoD: "Teste de paridade lote<->streaming < 1e-8 nas últimas 500 barras"
_TOLERANCE = 1e-8

# 5 símbolos do universo (Binance USDⓈ-M, PLANO_MESTRE_PRINCE2.md §15) --
# mesmo conjunto de `src.labels.backfill_multi_symbol.ALL_SYMBOLS`. Testes
# de paridade abaixo parametrizam sobre estes 5 (achado F4,
# audit_engineering): rodam de verdade contra qualquer símbolo com backfill
# local presente, skip individual (não a suíte inteira) pros ausentes --
# nunca dado sintético no lugar do backfill real ausente.
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def _skip_if_missing(symbol: str) -> None:
    path = CAPACITY_DIR / "klines_1m" / symbol / f"{_FIXTURE_START}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


def _skip_if_missing_dollar_bars(symbol: str) -> None:
    path = CAPACITY_DIR / "dollar_bars_r1" / symbol / f"{_FIXTURE_START}.parquet"
    if not path.exists():
        pytest.skip(f"fixture dollar-bar ausente no backfill local: {path}")


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_paridade_lote_streaming_ultimas_500_barras(symbol: str) -> None:
    _skip_if_missing(symbol)

    bars = _sources.load_bars_15m(symbol, _FIXTURE_START, _FIXTURE_END)
    funding = _sources.load_funding_aligned(bars, symbol, _FIXTURE_START, _FIXTURE_END)
    oi = _sources.load_oi_aligned(bars, symbol, _FIXTURE_START, _FIXTURE_END)
    assert bars.height > 2000 + _N_TAIL  # margem de warmup + cauda comparada

    windows = build.FeatureWindows.from_constants()
    batch = build.compute_t1_features(bars, funding, oi, windows=windows, apply_warmup_mask=False)

    feature_cols = list(build.T1_FEATURE_IDS) + list(build.SUPPORT_FEATURE_IDS)
    max_abs_dev = 0.0
    worst: tuple[str, int, float, float] | None = None

    for row_idx in range(bars.height - _N_TAIL, bars.height):
        sub_bars = bars.slice(0, row_idx + 1)
        sub_funding = funding.slice(0, row_idx + 1)
        sub_oi = oi.slice(0, row_idx + 1)
        stream_row = build.compute_t1_features(
            sub_bars, sub_funding, sub_oi, windows=windows, apply_warmup_mask=False
        ).row(-1, named=True)
        batch_row = batch.row(row_idx, named=True)

        for col in feature_cols:
            a = stream_row[col]
            b = batch_row[col]
            if a is None and b is None:
                continue
            assert a is not None and b is not None, (
                f"{col} em row {row_idx}: streaming={a!r} vs lote={b!r} (um é null e outro não)"
            )
            # achado Lote B (H5, 2026-08-24): `dev = abs(nan - nan)` é NaN,
            # e `nan > max_abs_dev` é sempre False -- SEM esta checagem
            # explícita, um par (NaN, NaN) legítimo (D07f_taker_imbalance_
            # 1m_agg sem `taker_imbalance_1m_agg_aligned` passado, como
            # aqui) e um par (NaN, valor_real) genuinamente DIVERGENTE
            # ficariam indistinguíveis -- os dois silenciosamente nunca
            # atualizam `max_abs_dev`. Trata NaN explicitamente: os dois
            # lados NaN é OK (mesmo espírito do `is None`, "nenhum dos
            # dois tem valor"); só um lado NaN é falha real, não silenciada.
            a_is_nan = isinstance(a, float) and np.isnan(a)
            b_is_nan = isinstance(b, float) and np.isnan(b)
            if a_is_nan or b_is_nan:
                assert a_is_nan and b_is_nan, (
                    f"{col} em row {row_idx}: streaming={a!r} vs lote={b!r} (um é NaN e outro não)"
                )
                continue
            dev = abs(float(a) - float(b))
            if dev > max_abs_dev:
                max_abs_dev = dev
                worst = (col, row_idx, float(a), float(b))

    assert max_abs_dev < _TOLERANCE, (
        f"desvio máximo {max_abs_dev} >= tolerância {_TOLERANCE} (pior caso: {worst})"
    )


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_paridade_streaming_bate_com_recompute_do_zero_em_prefixo_arbitrario(symbol: str) -> None:
    """Complemento pontual do teste acima, mais barato: pega UM prefixo
    arbitrário no meio da série (não só a cauda) e confirma que rodar
    `compute_t1_features` sobre ele produz exatamente a última linha que o
    lote completo produziria naquele mesmo índice — a MESMA propriedade,
    verificada num ponto isolado para detectar rápido se algo quebrou sem
    pagar o custo das 500 chamadas do teste principal."""
    _skip_if_missing(symbol)

    bars = _sources.load_bars_15m(symbol, _FIXTURE_START, _FIXTURE_END)
    funding = _sources.load_funding_aligned(bars, symbol, _FIXTURE_START, _FIXTURE_END)
    oi = _sources.load_oi_aligned(bars, symbol, _FIXTURE_START, _FIXTURE_END)

    windows = build.FeatureWindows.from_constants()
    batch = build.compute_t1_features(bars, funding, oi, windows=windows, apply_warmup_mask=False)

    row_idx = 2500
    sub_bars = bars.slice(0, row_idx + 1)
    sub_funding = funding.slice(0, row_idx + 1)
    sub_oi = oi.slice(0, row_idx + 1)
    stream_row = build.compute_t1_features(
        sub_bars, sub_funding, sub_oi, windows=windows, apply_warmup_mask=False
    ).row(-1, named=True)
    batch_row = batch.row(row_idx, named=True)

    for col in list(build.T1_FEATURE_IDS) + list(build.SUPPORT_FEATURE_IDS):
        a, b = stream_row[col], batch_row[col]
        if a is None and b is None:
            continue
        assert a is not None and b is not None
        # equal_nan=True (achado Lote B, H5, 2026-08-24): D07f_taker_
        # imbalance_1m_agg é a 1ª feature de SUPPORT_FEATURE_IDS que fica
        # NaN o tempo TODO quando compute_t1_features é chamada sem
        # taker_imbalance_1m_agg_aligned (aqui não é passado) -- NaN
        # legítimo dos dois lados não é divergência de paridade, mas
        # np.isclose(nan, nan) sem equal_nan retorna False por padrão.
        assert np.isclose(a, b, atol=_TOLERANCE, rtol=0, equal_nan=True), (
            f"{col}: streaming={a} lote={b}"
        )


# ============================================================================
# vol_estimator_id="parkinson_w20" / bar_source="dollar_r1" -- Fase 2 da
# migração Parkinson+dollar-bar (2026-08-17). Achado de auditoria
# (audit_engineering, mesma data): o DoD de "código de feature" (CLAUDE.md,
# §16.10) exige paridade lote<->streaming pra QUALQUER código de feature
# novo -- `c01_atr_20_parkinson` (mecanismo diferente de `atr_wilder`,
# `pl.Series.rolling_mean` em vez de suavização recursiva) e o carregamento
# de dollar bar nunca tinham sido exercidos por este teste, só pela suíte
# unitária (causal/dimensional, não full-pipeline lote<->streaming).
# ============================================================================


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_paridade_lote_streaming_parkinson_ultimas_500_barras(symbol: str) -> None:
    """Mesmo teste de `test_paridade_lote_streaming_ultimas_500_barras`,
    só trocando `vol_estimator_id` -- mesma grade (time_15m), mesmo
    fixture. Prova que o mecanismo de `c01_atr_20_parkinson`
    (`rolling_mean` sobre janela fixa) é tão causal/prefix-invariante
    quanto `atr_wilder` (recursivo), apesar de ser uma primitiva Polars
    diferente."""
    _skip_if_missing(symbol)

    bars = _sources.load_bars_15m(symbol, _FIXTURE_START, _FIXTURE_END)
    funding = _sources.load_funding_aligned(bars, symbol, _FIXTURE_START, _FIXTURE_END)
    oi = _sources.load_oi_aligned(bars, symbol, _FIXTURE_START, _FIXTURE_END)
    assert bars.height > 2000 + _N_TAIL

    windows = build.FeatureWindows.from_constants()
    vol_estimator_id = f"parkinson_w{windows.atr_window}"
    batch = build.compute_t1_features(
        bars,
        funding,
        oi,
        windows=windows,
        apply_warmup_mask=False,
        vol_estimator_id=vol_estimator_id,
    )

    feature_cols = list(build.T1_FEATURE_IDS) + list(build.SUPPORT_FEATURE_IDS)
    max_abs_dev = 0.0
    worst: tuple[str, int, float, float] | None = None

    for row_idx in range(bars.height - _N_TAIL, bars.height):
        sub_bars = bars.slice(0, row_idx + 1)
        sub_funding = funding.slice(0, row_idx + 1)
        sub_oi = oi.slice(0, row_idx + 1)
        stream_row = build.compute_t1_features(
            sub_bars,
            sub_funding,
            sub_oi,
            windows=windows,
            apply_warmup_mask=False,
            vol_estimator_id=vol_estimator_id,
        ).row(-1, named=True)
        batch_row = batch.row(row_idx, named=True)

        for col in feature_cols:
            a = stream_row[col]
            b = batch_row[col]
            if a is None and b is None:
                continue
            assert a is not None and b is not None, (
                f"{col} em row {row_idx}: streaming={a!r} vs lote={b!r} (um é null e outro não)"
            )
            # achado Lote B (H5, 2026-08-24): `dev = abs(nan - nan)` é NaN,
            # e `nan > max_abs_dev` é sempre False -- SEM esta checagem
            # explícita, um par (NaN, NaN) legítimo (D07f_taker_imbalance_
            # 1m_agg sem `taker_imbalance_1m_agg_aligned` passado, como
            # aqui) e um par (NaN, valor_real) genuinamente DIVERGENTE
            # ficariam indistinguíveis -- os dois silenciosamente nunca
            # atualizam `max_abs_dev`. Trata NaN explicitamente: os dois
            # lados NaN é OK (mesmo espírito do `is None`, "nenhum dos
            # dois tem valor"); só um lado NaN é falha real, não silenciada.
            a_is_nan = isinstance(a, float) and np.isnan(a)
            b_is_nan = isinstance(b, float) and np.isnan(b)
            if a_is_nan or b_is_nan:
                assert a_is_nan and b_is_nan, (
                    f"{col} em row {row_idx}: streaming={a!r} vs lote={b!r} (um é NaN e outro não)"
                )
                continue
            dev = abs(float(a) - float(b))
            if dev > max_abs_dev:
                max_abs_dev = dev
                worst = (col, row_idx, float(a), float(b))

    assert max_abs_dev < _TOLERANCE, (
        f"desvio máximo {max_abs_dev} >= tolerância {_TOLERANCE} (pior caso: {worst})"
    )


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _SYMBOLS)
def test_paridade_streaming_bate_com_recompute_do_zero_sob_dollar_bar(symbol: str) -> None:
    """Complemento pontual (mesmo padrão de `..._prefixo_arbitrario` acima)
    -- prova que carregar via `bar_source="dollar_r1"` (fonte de barras
    diferente, `lake.query_dollar_bars` em vez de `load_bars_15m`) não
    quebra a invariante prefix-causal do Feature Engine. Não cobre as 500
    barras completas (custo menor, dado dollar-bar tem volume real maior
    por partição) -- um ponto isolado já detecta regressão de mecanismo,
    mesmo racional do teste irmão pra grade de tempo."""
    _skip_if_missing_dollar_bars(symbol)

    bars = _sources.load_bars(symbol, _FIXTURE_START, _FIXTURE_END, bar_source="dollar_r1")
    funding = _sources.load_funding_aligned(bars, symbol, _FIXTURE_START, _FIXTURE_END)
    oi = _sources.load_oi_aligned(bars, symbol, _FIXTURE_START, _FIXTURE_END)
    assert bars.height > 100  # margem mínima de warmup pro ponto testado abaixo

    windows = build.FeatureWindows.from_constants()
    batch = build.compute_t1_features(bars, funding, oi, windows=windows, apply_warmup_mask=False)

    row_idx = min(100, bars.height - 1)
    sub_bars = bars.slice(0, row_idx + 1)
    sub_funding = funding.slice(0, row_idx + 1)
    sub_oi = oi.slice(0, row_idx + 1)
    stream_row = build.compute_t1_features(
        sub_bars, sub_funding, sub_oi, windows=windows, apply_warmup_mask=False
    ).row(-1, named=True)
    batch_row = batch.row(row_idx, named=True)

    for col in list(build.T1_FEATURE_IDS) + list(build.SUPPORT_FEATURE_IDS):
        a, b = stream_row[col], batch_row[col]
        if a is None and b is None:
            continue
        assert a is not None and b is not None
        # equal_nan=True (achado Lote B, H5, 2026-08-24): D07f_taker_
        # imbalance_1m_agg é a 1ª feature de SUPPORT_FEATURE_IDS que fica
        # NaN o tempo TODO quando compute_t1_features é chamada sem
        # taker_imbalance_1m_agg_aligned (aqui não é passado) -- NaN
        # legítimo dos dois lados não é divergência de paridade, mas
        # np.isclose(nan, nan) sem equal_nan retorna False por padrão.
        assert np.isclose(a, b, atol=_TOLERANCE, rtol=0, equal_nan=True), (
            f"{col}: streaming={a} lote={b}"
        )
