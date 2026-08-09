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


def _skip_if_missing() -> None:
    path = CAPACITY_DIR / "klines_1m" / "BTCUSDT" / f"{_FIXTURE_START}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


@pytest.mark.slow
@pytest.mark.integration
def test_paridade_lote_streaming_ultimas_500_barras() -> None:
    _skip_if_missing()

    bars = _sources.load_bars_15m("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    funding = _sources.load_funding_aligned(bars, "BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    oi = _sources.load_oi_aligned(bars, "BTCUSDT", _FIXTURE_START, _FIXTURE_END)
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
            dev = abs(float(a) - float(b))
            if dev > max_abs_dev:
                max_abs_dev = dev
                worst = (col, row_idx, float(a), float(b))

    assert max_abs_dev < _TOLERANCE, (
        f"desvio máximo {max_abs_dev} >= tolerância {_TOLERANCE} (pior caso: {worst})"
    )


@pytest.mark.integration
def test_paridade_streaming_bate_com_recompute_do_zero_em_prefixo_arbitrario() -> None:
    """Complemento pontual do teste acima, mais barato: pega UM prefixo
    arbitrário no meio da série (não só a cauda) e confirma que rodar
    `compute_t1_features` sobre ele produz exatamente a última linha que o
    lote completo produziria naquele mesmo índice — a MESMA propriedade,
    verificada num ponto isolado para detectar rápido se algo quebrou sem
    pagar o custo das 500 chamadas do teste principal."""
    _skip_if_missing()

    bars = _sources.load_bars_15m("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    funding = _sources.load_funding_aligned(bars, "BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    oi = _sources.load_oi_aligned(bars, "BTCUSDT", _FIXTURE_START, _FIXTURE_END)

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
        assert np.isclose(a, b, atol=_TOLERANCE, rtol=0), f"{col}: streaming={a} lote={b}"
