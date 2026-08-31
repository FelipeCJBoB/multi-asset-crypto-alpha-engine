"""Testes de `src.analysis.label_audit` — distribuição do label/target,
ADR-008 Fase 2."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from src.analysis import label_audit as la

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_BASE = datetime(2024, 1, 1, tzinfo=UTC)


def _t0s(n: int) -> list[datetime]:
    return [_BASE + timedelta(hours=i) for i in range(n)]


def _labels_df(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=_T0_DTYPE),
            "side": pl.Series([r["side"] for r in rows], dtype=pl.Int8),
            "label": pl.Series([r["label"] for r in rows], dtype=pl.Int8),
            "ret_net": pl.Series([r["ret_net"] for r in rows], dtype=pl.Float64),
        }
    )


def test_distribuicao_ternaria_e_binaria_conferidas_a_mao() -> None:
    """10 trades long: 5 TP, 3 TIME, 2 SL -- frac_tp=0,5, frac_time=0,3,
    frac_sl=0,2. Binário: positivo=TP=5, negativo=TIME+SL=5,
    frac_positive=0,5."""
    t0s = _t0s(10)
    labels = [1] * 5 + [0] * 3 + [-1] * 2
    rows = [
        {"t0": t0s[i], "side": 1, "label": labels[i], "ret_net": 0.001 * (i + 1)}
        for i in range(10)
    ]
    out = la.compute_label_distribution_stats(_labels_df(rows))

    assert len(out) == 1
    s = out[0]
    assert s.side == 1
    assert s.n_total == 10
    assert s.n_tp == 5
    assert s.n_time == 3
    assert s.n_sl == 2
    assert s.frac_tp == pytest.approx(0.5)
    assert s.frac_time == pytest.approx(0.3)
    assert s.frac_sl == pytest.approx(0.2)
    assert s.n_positive == 5
    assert s.n_negative == 5
    assert s.frac_positive == pytest.approx(0.5)


def test_momentos_ret_net_conferidos_a_mao() -> None:
    """`ret_net` = [1,2,3,4,5] (bps ficticios, fracao aqui) -- mean=3,0,
    std(ddof=1)=sqrt(2,5), mediana=3,0 -- valores de livro-texto."""
    t0s = _t0s(5)
    rows = [
        {"t0": t0s[i], "side": 1, "label": 1, "ret_net": float(i + 1)} for i in range(5)
    ]
    out = la.compute_label_distribution_stats(_labels_df(rows))
    s = out[0]
    assert s.ret_net_mean == pytest.approx(3.0)
    assert s.ret_net_std == pytest.approx(2.5**0.5)
    assert s.ret_net_p50 == pytest.approx(3.0)


def test_autocorrelacao_lag1_perfeita_positiva() -> None:
    """label binario alternando 0,1,0,1,... -- autocorrelacao lag-1
    perfeita NEGATIVA (-1,0, cada valor sempre oposto ao seguinte)."""
    t0s = _t0s(6)
    labels = [1, -1, 1, -1, 1, -1]  # binario alterna 1,0,1,0,1,0 (TP vs SL)
    rows = [
        {"t0": t0s[i], "side": 1, "label": labels[i], "ret_net": 0.001 * (i + 1)}
        for i in range(6)
    ]
    out = la.compute_label_distribution_stats(_labels_df(rows))
    s = out[0]
    assert s.label_autocorr_lag1 == pytest.approx(-1.0)


def test_autocorrelacao_lag1_constante_e_nan() -> None:
    """Todos os labels iguais -- binario constante -- autocorrelacao
    indefinida (NaN), nao 1,0/erro de divisao por zero."""
    t0s = _t0s(5)
    rows = [
        {"t0": t0s[i], "side": 1, "label": 1, "ret_net": 0.001 * (i + 1)} for i in range(5)
    ]
    out = la.compute_label_distribution_stats(_labels_df(rows))
    assert np.isnan(out[0].label_autocorr_lag1)


def test_dois_lados_saem_como_duas_entradas() -> None:
    t0s = _t0s(4)
    rows = [
        {"t0": t0s[0], "side": 1, "label": 1, "ret_net": 0.001},
        {"t0": t0s[1], "side": 1, "label": 0, "ret_net": 0.002},
        {"t0": t0s[2], "side": -1, "label": 1, "ret_net": 0.001},
        {"t0": t0s[3], "side": -1, "label": -1, "ret_net": 0.002},
    ]
    out = la.compute_label_distribution_stats(_labels_df(rows))
    by_side = {s.side: s for s in out}
    assert set(by_side) == {1, -1}
    assert by_side[1].n_total == 2
    assert by_side[-1].n_total == 2


def test_lado_ausente_do_frame_nao_aparece_na_saida() -> None:
    t0s = _t0s(2)
    rows = [
        {"t0": t0s[i], "side": 1, "label": 1, "ret_net": 0.001 * (i + 1)} for i in range(2)
    ]
    out = la.compute_label_distribution_stats(_labels_df(rows))
    assert {s.side for s in out} == {1}


def test_coluna_ausente_levanta_valueerror() -> None:
    df = _labels_df(
        [{"t0": _t0s(1)[0], "side": 1, "label": 1, "ret_net": 0.001}]
    ).drop("ret_net")
    with pytest.raises(ValueError, match="ret_net"):
        la.compute_label_distribution_stats(df)


def test_um_ponto_so_momentos_nan_mas_n_total_correto() -> None:
    df = _labels_df([{"t0": _t0s(1)[0], "side": 1, "label": 1, "ret_net": 0.001}])
    out = la.compute_label_distribution_stats(df)
    s = out[0]
    assert s.n_total == 1
    assert np.isnan(s.ret_net_std)
    assert np.isnan(s.label_autocorr_lag1)
