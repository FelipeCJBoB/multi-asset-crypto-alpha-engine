"""Testes de `src/labels/triple_barrier.py`.

Duas camadas: (1) fixtures SINTÉTICAS pequenas, com números conferidos à
mão (script de prototipagem do Sprint 6 — valores no corpo dos testes
abaixo batem exatamente com o que `build_labels` calcula, não são só
"passou, então tá certo"); (2) um recorte REAL de `data/capacity/`
(2024-01-01 a 2024-01-15), rodando o pipeline ponta a ponta e verificando
as seis invariantes do §3.8."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import polars as pl
import pytest

from src.data._paths import CAPACITY_DIR
from src.exchange.filters import NoFiltersAvailableError
from src.labels import triple_barrier as tb

_FIXTURE_START = "2024-01-01"
_FIXTURE_END = "2024-01-15"


def _skip_if_missing(day: str) -> None:
    path = CAPACITY_DIR / "klines_1m" / "BTCUSDT" / f"{day}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


# ============================================================================
# round_to_tick
# ============================================================================


def test_round_to_tick_compra_arredonda_para_baixo() -> None:
    assert tb.round_to_tick(100.07, 1, Decimal("0.10")) == pytest.approx(100.0)


def test_round_to_tick_venda_arredonda_para_cima() -> None:
    assert tb.round_to_tick(100.07, -1, Decimal("0.10")) == pytest.approx(100.1)


def test_round_to_tick_multiplo_exato_fica_igual() -> None:
    assert tb.round_to_tick(100.10, 1, Decimal("0.10")) == pytest.approx(100.10)
    assert tb.round_to_tick(100.10, -1, Decimal("0.10")) == pytest.approx(100.10)


def test_round_to_tick_side_invalido_levanta_erro() -> None:
    with pytest.raises(ValueError):
        tb.round_to_tick(100.0, 0, Decimal("0.10"))


def test_round_to_tick_size_zero_devolve_preco_original() -> None:
    assert tb.round_to_tick(100.123, 1, Decimal("0")) == 100.123


# ============================================================================
# LabelConfig.config_hash — B15
# ============================================================================


def test_config_hash_deterministico() -> None:
    cfg1 = tb.LabelConfig(2.0, 1.5, 32, 1, 20, 0.0002, 0.0005)
    cfg2 = tb.LabelConfig(2.0, 1.5, 32, 1, 20, 0.0002, 0.0005)
    assert cfg1.config_hash == cfg2.config_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("tp_atr_mult", 2.5),
        ("sl_atr_mult", 1.0),
        ("time_stop_bars", 16),
        ("fill_timeout_bars", 2),
        ("atr_window", 14),
        ("maker_fee", 0.0003),
        ("taker_fee", 0.0006),
        ("decision_tf_minutes", 30),
    ],
)
def test_config_hash_muda_se_qualquer_parametro_mudar(field: str, value: float) -> None:
    """B15 — a garantia central: mudar QUALQUER parâmetro do bloco de
    barreiras muda o hash. Sem isso, labels calculados com uma config
    diferente da execução passariam despercebidos."""
    base = tb.LabelConfig(2.0, 1.5, 32, 1, 20, 0.0002, 0.0005)
    changed = replace(base, **{field: value})
    assert base.config_hash != changed.config_hash


def test_config_hash_de_constants_yaml_e_estavel() -> None:
    cfg1 = tb.LabelConfig.from_constants()
    cfg2 = tb.LabelConfig.from_constants()
    assert cfg1.config_hash == cfg2.config_hash
    assert cfg1 == cfg2


# ============================================================================
# verify_config_hash — B15, "teste que quebra se mudar um parâmetro sem
# recalcular labels"
# ============================================================================


def _one_row_labels(config_hash: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "config_hash": [config_hash],
            "ret_net": [0.01],
        }
    )


def test_verify_config_hash_passa_quando_bate() -> None:
    cfg = tb.LabelConfig(2.0, 1.5, 32, 1, 20, 0.0002, 0.0005)
    labels = _one_row_labels(cfg.config_hash)
    tb.verify_config_hash(labels, cfg)  # não levanta


def test_verify_config_hash_quebra_se_parametro_mudou_sem_recalcular() -> None:
    """O cenário real que B15 proíbe: labels calculados com `tp_atr_mult=2.0`,
    execução rodando com `tp_atr_mult=2.5` — tem que quebrar, não passar
    silenciosamente."""
    labels_config = tb.LabelConfig(2.0, 1.5, 32, 1, 20, 0.0002, 0.0005)
    execution_config = tb.LabelConfig(2.5, 1.5, 32, 1, 20, 0.0002, 0.0005)  # só tp_atr_mult mudou
    labels = _one_row_labels(labels_config.config_hash)
    with pytest.raises(tb.ConfigHashMismatchError):
        tb.verify_config_hash(labels, execution_config)


def test_verify_config_hash_quebra_se_dataset_mistura_configs() -> None:
    cfg_a = tb.LabelConfig(2.0, 1.5, 32, 1, 20, 0.0002, 0.0005)
    cfg_b = tb.LabelConfig(2.5, 1.5, 32, 1, 20, 0.0002, 0.0005)
    labels = pl.DataFrame(
        {"config_hash": [cfg_a.config_hash, cfg_b.config_hash], "ret_net": [0.01, -0.01]}
    )
    with pytest.raises(tb.ConfigHashMismatchError):
        tb.verify_config_hash(labels, cfg_a)


def test_verify_config_hash_dataset_vazio_levanta_erro() -> None:
    cfg = tb.LabelConfig(2.0, 1.5, 32, 1, 20, 0.0002, 0.0005)
    empty = pl.DataFrame(schema={"config_hash": pl.Utf8, "ret_net": pl.Float64})
    with pytest.raises(tb.ConfigHashMismatchError):
        tb.verify_config_hash(empty, cfg)


# ============================================================================
# build_labels — fixtures sintéticas, números conferidos à mão
# ============================================================================

_BAR_MS = 900_000
_BASE_MS = int(datetime(2026, 8, 8, 0, 0, tzinfo=UTC).timestamp() * 1000)
# 3 barras -> com atr_window=3, só a ÚLTIMA tem ATR válido (seed_idx =
# 0+3-1=2) -- exatamente 1 linha de decisão por chamada, fixture mínima.
_CLOSES = [100.0, 100.2, 99.9]
_CFG = tb.LabelConfig(
    tp_atr_mult=2.0, sl_atr_mult=1.5, time_stop_bars=4, fill_timeout_bars=1, atr_window=3,
    maker_fee=0.0002, taker_fee=0.0005,
)
_EMPTY_FUNDING = pl.DataFrame(schema={"calc_time": pl.Int64, "last_funding_rate": pl.Float64})


# (open_time_ms, open, high, low, close) -- uma linha de mark_1m sintética
_Row = tuple[int, float, float, float, float]


def _synthetic_bars() -> pl.DataFrame:
    open_time = [_BASE_MS + i * _BAR_MS for i in range(len(_CLOSES))]
    close_time = [t + _BAR_MS - 1 for t in open_time]
    high = [c + 0.2 for c in _CLOSES]
    low = [c - 0.2 for c in _CLOSES]
    return pl.DataFrame(
        {
            "open_time": open_time,
            "close_time": close_time,
            "close": _CLOSES,
            "high": high,
            "low": low,
        }
    )


def _t0() -> int:
    return _synthetic_bars()["close_time"][-1]


def _mark(rows: list[_Row]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "open_time": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
        }
    )


def _with_horizon_coverage(rows: list[_Row]) -> list[_Row]:
    """Garante que `mark_1m` cobre até `horizon_end_ms` — sem isso
    `build_labels` descarta a linha por "cauda incompleta" mesmo quando o
    evento de interesse acontece bem antes do fim do horizonte (medido no
    Sprint 6 prototipando este teste — comportamento correto e
    intencional: não dá pra saber de antemão que o resto do horizonte não
    importava)."""
    horizon = _t0() + _CFG.time_stop_bars * _BAR_MS
    last_px = rows[-1][4]
    return [*rows, (horizon, last_px, last_px, last_px, last_px)]


def test_build_labels_tp_long() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),  # preenche a 99.9
                # spike bem acima de qualquer TP plausível
                (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            ]
        )
    )
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TP"
    assert row["label"] == 1
    assert row["entry_price_fill"] == pytest.approx(99.9)
    assert row["exit_price"] == pytest.approx(row["tp_price"])
    assert row["ret_gross"] == pytest.approx(_CFG.tp_atr_mult * row["atr_at_t0"], rel=1e-9)
    expected_net = row["ret_gross"] - _CFG.maker_fee - _CFG.maker_fee
    assert row["ret_net"] == pytest.approx(expected_net, rel=1e-9)


def test_build_labels_sl_long() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                # crash bem abaixo de qualquer SL plausível
                (t0 + 5 * 60_000, 60.0, 65.0, 50.0, 55.0),
            ]
        )
    )
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "SL"
    assert row["label"] == -1
    assert row["exit_price"] == pytest.approx(row["sl_price"])
    assert row["ret_gross"] == pytest.approx(-_CFG.sl_atr_mult * row["atr_at_t0"], rel=1e-9)
    # SL sai a mercado -> taker na saída (§3.4 regra dura 3)
    expected_net = row["ret_gross"] - _CFG.maker_fee - _CFG.taker_fee
    assert row["ret_net"] == pytest.approx(expected_net, rel=1e-9)


def test_build_labels_tp_short_quando_preco_cai() -> None:
    """Para `side=-1`, o desfecho FAVORÁVEL é o preço CAIR — direção
    invertida em relação ao long, testada explicitamente."""
    t0 = _t0()
    rows: list[_Row] = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        (t0 + 5 * 60_000, 55.0, 60.0, 50.0, 52.0),
    ]
    mark = _mark(_with_horizon_coverage(rows))
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=-1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TP"
    assert row["label"] == 1


def test_build_labels_sl_short_quando_preco_sobe() -> None:
    t0 = _t0()
    rows: list[_Row] = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
    ]
    mark = _mark(_with_horizon_coverage(rows))
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=-1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "SL"
    assert row["label"] == -1


def test_build_labels_time_quando_nunca_toca_barreira() -> None:
    t0 = _t0()
    horizon = t0 + _CFG.time_stop_bars * _BAR_MS
    mark = _mark([(t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9), (horizon, 99.9, 99.95, 99.85, 99.9)])
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TIME"
    assert row["label"] == 0
    assert row["n_bars_held"] == _CFG.time_stop_bars
    assert row["exit_price"] == pytest.approx(99.9)
    assert row["ret_net"] == pytest.approx(-_CFG.maker_fee - _CFG.taker_fee, rel=1e-9)


def test_build_labels_nofill_quando_nunca_toca_limite() -> None:
    """§3.2 — NOFILL é desfecho de primeira classe, `label=-2`, `ret=0.0`."""
    t0 = _t0()
    mark = _mark([(t0 + m * 60_000, 100.5, 101.0, 100.5, 100.8) for m in range(1, 16)])
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "NOFILL"
    assert row["label"] == -2
    assert row["t_entry"] is None
    assert row["entry_price_fill"] is None
    assert row["ret_net"] == 0.0
    assert row["n_bars_held"] == 0


def test_build_labels_side_invalido_levanta_erro() -> None:
    with pytest.raises(ValueError):
        tb.build_labels(_synthetic_bars(), _mark([]), _EMPTY_FUNDING, side=0, config=_CFG)


def test_build_labels_bars_vazio_devolve_frame_vazio() -> None:
    empty_bars = pl.DataFrame(
        schema={
            "open_time": pl.Int64,
            "close_time": pl.Int64,
            "close": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
        }
    )
    out = tb.build_labels(empty_bars, _mark([]), _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 0


# ============================================================================
# assert_label_invariants — §3.8, unidade
# ============================================================================


def test_assert_label_invariants_passa_em_frame_valido() -> None:
    t0 = _t0()
    rows: list[_Row] = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
    ]
    mark = _mark(_with_horizon_coverage(rows))
    out = tb.build_labels_both_sides(_synthetic_bars(), mark, _EMPTY_FUNDING, config=_CFG)
    tb.assert_label_invariants(out, time_stop_bars=_CFG.time_stop_bars)


def _ms_utc(values: list[int]) -> pl.Series:
    return pl.Series(values, dtype=pl.Int64).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")


def test_assert_label_invariants_detecta_t1_menor_que_t0() -> None:
    bad = pl.DataFrame(
        {
            "t0": _ms_utc([1000]),
            "t1": _ms_utc([500]),
            "t_entry": _ms_utc([500]),
            "barrier_hit": pl.Series(["TP"], dtype=pl.Categorical),
            "config_hash": ["abc"],
            "sample_weight": [1.0],
            "n_bars_held": [1],
            "uniqueness": [1.0],
        }
    )
    with pytest.raises(AssertionError):
        tb.assert_label_invariants(bad, time_stop_bars=32)


# ============================================================================
# Integração com dado real — 2024-01-01 a 2024-01-15
# ============================================================================


@pytest.mark.integration
def test_build_labels_for_symbol_strict_levanta_sem_snapshot_historico() -> None:
    """B01 real, não só documentado: por padrão (`historical_filters_fallback`
    não passado), datas anteriores a 2026-08-08 levantam
    `NoFiltersAvailableError` — só existe 1 snapshot no disco (ver
    known_gaps.exchange_info_snapshot_coverage_gap em constants.yaml)."""
    _skip_if_missing(_FIXTURE_START)
    with pytest.raises(NoFiltersAvailableError):
        tb.build_labels_for_symbol("BTCUSDT", _FIXTURE_START, "2024-01-02")


@pytest.mark.integration
def test_build_labels_for_symbol_real_dado_invariantes() -> None:
    _skip_if_missing(_FIXTURE_START)
    cfg = tb.LabelConfig.from_constants()
    out = tb.build_labels_for_symbol(
        "BTCUSDT", _FIXTURE_START, _FIXTURE_END, config=cfg, historical_filters_fallback=True
    )
    assert out.height > 0
    assert list(out.columns) == list(tb.LABEL_COLUMNS)

    tb.assert_label_invariants(out, time_stop_bars=cfg.time_stop_bars)
    tb.verify_config_hash(out, cfg)

    # side só ±1 (item 1 da docstring do módulo — nunca 0)
    assert set(out["side"].unique().to_list()) <= {1, -1}
    # os dois lados presentes (M_long/M_short, B18)
    assert set(out["side"].unique().to_list()) == {1, -1}


@pytest.mark.integration
def test_build_labels_for_symbol_determinismo() -> None:
    _skip_if_missing(_FIXTURE_START)
    cfg = tb.LabelConfig.from_constants()
    out1 = tb.build_labels_for_symbol(
        "BTCUSDT", _FIXTURE_START, "2024-01-05", config=cfg, historical_filters_fallback=True
    )
    out2 = tb.build_labels_for_symbol(
        "BTCUSDT", _FIXTURE_START, "2024-01-05", config=cfg, historical_filters_fallback=True
    )
    assert out1.equals(out2, null_equal=True)


@pytest.mark.integration
def test_build_labels_for_symbol_barrier_hit_cobre_os_quatro_desfechos() -> None:
    """Não é uma garantia estrutural (poderia, em teoria, não ocorrer um dos
    quatro num recorte pequeno) — mas sobre 2 semanas reais de BTCUSDT os
    quatro desfechos aparecem, o que é o comportamento esperado e vale a
    pena travar como regressão."""
    _skip_if_missing(_FIXTURE_START)
    out = tb.build_labels_for_symbol(
        "BTCUSDT", _FIXTURE_START, _FIXTURE_END, historical_filters_fallback=True
    )
    observed = set(out["barrier_hit"].cast(pl.Utf8).unique().to_list())
    assert observed == {"TP", "SL", "TIME", "NOFILL"}
