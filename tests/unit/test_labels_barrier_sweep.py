"""Testes de `src/labels/barrier_sweep.py` — vetorização via
`sliding_window_view` (§18.7.1, Faixa 2 E1).

Duas camadas: (1) fixtures sintéticas, reproduzindo byte-a-byte os mesmos
cenários já testados em `test_labels_triple_barrier.py` (TP/SL/TIME/
desempate) contra o resultado do motor ESCALAR (`triple_barrier.
build_labels`) — a garantia central deste arquivo: vetorizar não pode
mudar o resultado; (2) um recorte REAL (1 ano, 2024), comparando a
distribuição TP/SL/TIME da versão vetorizada contra `build_labels` sobre o
mesmo intervalo — sanidade "a grade reproduz o motor de produção" em
escala menor que os 6,5 anos completos (caro demais para rodar em todo
`pytest`)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from src.data._paths import CAPACITY_DIR
from src.labels import barrier_sweep as bs
from src.labels import triple_barrier as tb

_BAR_MS = 900_000
_BASE_MS = int(datetime(2026, 8, 8, 0, 0, tzinfo=UTC).timestamp() * 1000)
_CLOSES = [100.0, 100.2, 99.9]
_CFG = tb.LabelConfig(
    tp_atr_mult=2.0,
    sl_atr_mult=1.5,
    time_stop_ms=4 * _BAR_MS,
    fill_timeout_ms=_BAR_MS,
    atr_window_ms=3 * _BAR_MS,
    maker_fee=0.0002,
    taker_fee=0.0005,
    estimator_id="atr_wilder_w3",
)
_EMPTY_FUNDING = pl.DataFrame(schema={"calc_time": pl.Int64, "last_funding_rate": pl.Float64})

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
    horizon = _t0() + _CFG.time_stop_ms
    last_px = rows[-1][4]
    return [*rows, (horizon, last_px, last_px, last_px, last_px)]


def _synthetic_bars_close_time() -> np.ndarray:
    return _synthetic_bars()["close_time"].cast(pl.Int64).to_numpy().astype(np.int64)


def _scalar_and_vectorized(
    mark: pl.DataFrame, *, side: int, funding: pl.DataFrame = _EMPTY_FUNDING
) -> tuple[dict[str, object], bs.ResolvedBarriers]:
    """Roda o motor escalar (fonte da verdade) e o vetorizado sobre o
    MESMO cenário, devolve `(linha_escalar, resultado_vetorizado)` prontos
    pra comparar campo a campo. `decision_bar_close_time_ms` passado (AG-031/
    B1) -- a fixture mínima (3 barras) não estende até o horizonte, então
    os dois motores caem no MESMO fallback aritmético (idêntico em ambos),
    mantendo a paridade significativa mesmo sem exercer o ramo de busca
    real (ver `test_resolve_barriers_vectorized_n_bars_held_contagem_real_
    quando_array_cobre_o_horizonte` para esse ramo)."""
    scalar_out = tb.build_labels(_synthetic_bars(), mark, funding, side=side, config=_CFG)
    filled = scalar_out.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    assert filled.height == 1, "cenário de teste tem que produzir exatamente 1 trade preenchido"
    vec_out = bs.resolve_barriers_vectorized(
        filled,
        mark,
        funding,
        side=side,
        tp_atr_mult=_CFG.tp_atr_mult,
        sl_atr_mult=_CFG.sl_atr_mult,
        time_stop_ms=_CFG.time_stop_ms,
        maker_fee=_CFG.maker_fee,
        taker_fee=_CFG.taker_fee,
        adverse_selection_bps=_CFG.adverse_selection_bps,
        decision_bar_close_time_ms=_synthetic_bars_close_time(),
    )
    return filled.row(0, named=True), vec_out


def _assert_reproduces(scalar_row: dict[str, object], vec: bs.ResolvedBarriers) -> None:
    assert vec.barrier_hit[0] == scalar_row["barrier_hit"]
    assert vec.exit_price[0] == pytest.approx(scalar_row["exit_price"], rel=1e-9)
    assert vec.ret_gross[0] == pytest.approx(scalar_row["ret_gross"], rel=1e-9)
    assert vec.ret_net[0] == pytest.approx(scalar_row["ret_net"], rel=1e-9)
    assert vec.cost_entry_bps[0] == pytest.approx(scalar_row["cost_entry_bps"], rel=1e-9)
    assert vec.cost_exit_bps[0] == pytest.approx(scalar_row["cost_exit_bps"], rel=1e-9)
    assert vec.funding_bps[0] == pytest.approx(scalar_row["funding_bps"], rel=1e-9)
    assert int(vec.n_bars_held[0]) == scalar_row["n_bars_held"]
    scalar_t1_ms = scalar_row["t1"].timestamp() * 1000  # type: ignore[union-attr]
    assert int(vec.t1_ms[0]) == pytest.approx(scalar_t1_ms, abs=1.0)


def test_reproduz_build_labels_tp_long() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            ]
        )
    )
    scalar_row, vec = _scalar_and_vectorized(mark, side=1)
    assert scalar_row["barrier_hit"] == "TP"
    _assert_reproduces(scalar_row, vec)
    # D4/AG-205 (2026-08-24) -- candle que tocou abriu em 145.0, muito além
    # do tp_price nominal (spike) -- TP nunca ganha ajuste de gap (ordem
    # passiva/maker), então o nível nominal continua o fill em ambos os
    # motores.
    assert vec.exit_price[0] == pytest.approx(scalar_row["tp_price"])
    assert not bool(vec.gap_fill_used[0])


def test_selecao_adversa_cobrada_so_nas_pernas_maker() -> None:
    """AG-432 (auditoria externa 2026-09-03, achado N8) — `adverse_
    selection_bps` deixou de ser coluna informativa e passou a ser COBRADO
    de `ret_net`, mas só nas pernas PASSIVAS: entrada (`LIMIT`/post-only,
    sempre) e saída por TP (`LIMIT`/`GTC`). SL e TIME saem a mercado
    (taker) — não há ordem em repouso pra ser adversamente selecionada, e
    o custo adverso do SL já é modelado por `_gap_aware_sl_fill`; cobrar
    ali contaria o mesmo efeito duas vezes.

    Trava as DUAS metades: quanto foi cobrado, e em que pernas. Os dois
    motores (escalar e vetorizado) são checados no mesmo teste, porque foi
    justamente a divergência entre eles que revelou que existiam duas
    implementações de custo pra manter em sincronia."""
    t0 = _t0()
    adv_bps = 1.5  # noqa: magic-number -- valor de produção de constants.yaml, fixado aqui pra o teste ser legível
    cfg_com_adv = dataclasses.replace(_CFG, adverse_selection_bps=adv_bps)

    cenarios = {
        "TP": [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
        ],
        "SL": [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            (t0 + 5 * 60_000, 60.0, 65.0, 50.0, 55.0),
        ],
    }
    # TP paga selecao adversa nas 2 pernas (entrada maker + saida maker);
    # SL paga so na entrada (saida e STOP_MARKET, taker).
    esperado_bps = {"TP": 2.0 * adv_bps, "SL": 1.0 * adv_bps}

    for barreira, rows in cenarios.items():
        mark = _mark(_with_horizon_coverage(rows))
        escalar = tb.build_labels(
            _synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=cfg_com_adv
        )
        filled = escalar.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
        assert filled.height == 1
        row = filled.row(0, named=True)
        assert row["barrier_hit"] == barreira

        # 1. quanto foi cobrado, e em quais pernas
        assert row["adverse_selection_bps"] == pytest.approx(esperado_bps[barreira])
        assert row["cost_entry_bps"] == pytest.approx(
            _CFG.maker_fee * 10_000 + adv_bps  # noqa: magic-number -- bps por unidade
        )
        if barreira == "TP":
            assert row["cost_exit_bps"] == pytest.approx(_CFG.maker_fee * 10_000 + adv_bps)  # noqa: magic-number
        else:
            # saida taker: NENHUMA selecao adversa somada ao fee
            assert row["cost_exit_bps"] == pytest.approx(_CFG.taker_fee * 10_000)  # noqa: magic-number

        # 2. `ret_net` de fato encolheu exatamente o cobrado (contraprova
        #    contra "cobrei na coluna mas esqueci de subtrair")
        sem_adv = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
        row_sem = sem_adv.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL").row(
            0, named=True
        )
        delta_bps = (row_sem["ret_net"] - row["ret_net"]) * 10_000  # noqa: magic-number
        assert delta_bps == pytest.approx(esperado_bps[barreira])

        # 3. o motor vetorizado cobra igual
        vec = bs.resolve_barriers_vectorized(
            filled,
            mark,
            _EMPTY_FUNDING,
            side=1,
            tp_atr_mult=cfg_com_adv.tp_atr_mult,
            sl_atr_mult=cfg_com_adv.sl_atr_mult,
            time_stop_ms=cfg_com_adv.time_stop_ms,
            maker_fee=cfg_com_adv.maker_fee,
            taker_fee=cfg_com_adv.taker_fee,
            adverse_selection_bps=cfg_com_adv.adverse_selection_bps,
            decision_bar_close_time_ms=_synthetic_bars_close_time(),
        )
        assert vec.ret_net[0] == pytest.approx(row["ret_net"], rel=1e-9)
        assert vec.cost_entry_bps[0] == pytest.approx(row["cost_entry_bps"], rel=1e-9)
        assert vec.cost_exit_bps[0] == pytest.approx(row["cost_exit_bps"], rel=1e-9)


def test_config_hash_muda_quando_politica_de_custo_muda() -> None:
    """AG-432 — o furo que `cost_policy_id`/`adverse_selection_bps` no
    payload fecham: sem eles, um `labels.parquet` gerado sob a fórmula
    antiga de `ret_net` passaria por `verify_config_hash` (B15) como se
    nada tivesse mudado. Mesmo papel que `barrier_fill_policy_id` cumpre
    pra lógica de fill."""
    base = _CFG
    outra_taxa = dataclasses.replace(base, adverse_selection_bps=1.5)  # noqa: magic-number
    outra_politica = dataclasses.replace(base, cost_policy_id="hipotetica_v2")

    assert base.config_hash != outra_taxa.config_hash
    assert base.config_hash != outra_politica.config_hash
    assert outra_taxa.config_hash != outra_politica.config_hash


def test_reproduz_build_labels_sl_long() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 60.0, 65.0, 50.0, 55.0),
            ]
        )
    )
    scalar_row, vec = _scalar_and_vectorized(mark, side=1)
    assert scalar_row["barrier_hit"] == "SL"
    _assert_reproduces(scalar_row, vec)
    # D4/AG-205 (2026-08-24) -- candle que tocou abriu em 60.0, já além do
    # sl_price nominal (crash) -- os dois motores (escalar e vetorizado)
    # têm que concordar no fill gap-aware, não só concordar entre si (daí o
    # valor numérico travado, não só a paridade via _assert_reproduces).
    assert vec.exit_price[0] == pytest.approx(60.0)
    assert bool(vec.gap_fill_used[0])


def test_reproduz_build_labels_sl_long_sem_gap() -> None:
    """D4/AG-205 -- contraponto vetorizado de `test_reproduz_build_labels_
    sl_long`: candle que toca o SL NÃO abriu além do nível (só o `low`
    rompe intra-candle) -- os dois motores concordam no fill nominal
    (comportamento anterior a esta correção preservado), `gap_fill_used`
    fica `False` nos dois."""
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 99.85, 99.9, 90.0, 91.0),
            ]
        )
    )
    scalar_row, vec = _scalar_and_vectorized(mark, side=1)
    assert scalar_row["barrier_hit"] == "SL"
    assert scalar_row["sl_price"] < 99.85, (
        "fixture-sanity: open tem que ficar do lado seguro do nível"
    )
    _assert_reproduces(scalar_row, vec)
    assert not bool(vec.gap_fill_used[0])


def test_reproduz_build_labels_tp_short() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 55.0, 60.0, 50.0, 52.0),
            ]
        )
    )
    scalar_row, vec = _scalar_and_vectorized(mark, side=-1)
    assert scalar_row["barrier_hit"] == "TP"
    _assert_reproduces(scalar_row, vec)


def test_reproduz_build_labels_time() -> None:
    t0 = _t0()
    rows: list[_Row] = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        (t0 + 5 * 60_000, 100.3, 100.5, 100.2, 100.4),
        (t0 + 9 * 60_000, 100.1, 100.2, 99.8, 99.9),
    ]
    mark = _mark(_with_horizon_coverage(rows))
    scalar_row, vec = _scalar_and_vectorized(mark, side=1)
    assert scalar_row["barrier_hit"] == "TIME"
    _assert_reproduces(scalar_row, vec)


def test_reproduz_build_labels_tie_break_mesmo_candle() -> None:
    """TP e SL tocados no MESMO candle de 1m -- desempate por proximidade
    ao `open` (item 5 da docstring de `triple_barrier.py`). `tp_price`/
    `sl_price` da fixture ficam em ~100,77/~99,25 (ver debug prévio) — um
    candle com `low` abaixo de `sl_price` E `high` acima de `tp_price`
    força os dois toques no mesmo índice."""
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 99.9, 101.0, 99.0, 100.0),
            ]
        )
    )
    scalar_row, vec = _scalar_and_vectorized(mark, side=1)
    assert scalar_row["barrier_hit"] in ("TP", "SL")
    assert bool(vec.tie_break_used[0])
    _assert_reproduces(scalar_row, vec)


def test_vetorizado_processa_multiplos_trades_de_uma_vez() -> None:
    """`resolve_barriers_vectorized` roda sobre um DataFrame de N trades —
    monta 3 trades sintéticos independentes (índices diferentes de
    `t_entry`/`fill_px`/`atr_at_t0`, um TP/um SL/um TIME) num único
    `filled` e confere que os 3 resultados batem com 3 chamadas escalares
    separadas -- pega bug de indexação entre linhas (`idx_range`,
    `np.where(tie_mask, tp_idx, 0)`) que um teste de n=1 não pegaria."""
    rows: list[dict[str, object]] = []
    for i, (fill_px, atr_pct, exit_hint) in enumerate(
        [(100.0, 0.004, "tp"), (100.0, 0.004, "sl"), (100.0, 0.004, "time")]
    ):
        t0_i = _BASE_MS + i * 10 * _BAR_MS
        rows.append(
            {
                "t0": t0_i,
                "t_entry": t0_i + 60_000,
                "entry_price_fill": fill_px,
                "atr_at_t0": atr_pct,
                "_exit_hint": exit_hint,
            }
        )
    filled = pl.DataFrame(rows).with_columns(
        pl.col("t0").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
        pl.col("t_entry").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
    )

    mark_rows: list[_Row] = []
    horizon_bars = _CFG.time_stop_ms // 60_000 + 5  # == 4*15+5 (AG-031/B1, mesmo valor)
    for i, exit_hint in enumerate(("tp", "sl", "time")):
        t0_i = _BASE_MS + i * 10 * _BAR_MS
        base_open = t0_i + 60_000
        if exit_hint == "tp":
            mark_rows.append((base_open, 100.0, 100.0, 99.9, 100.0))
            mark_rows.append((base_open + 60_000, 145.0, 150.0, 140.0, 148.0))
        elif exit_hint == "sl":
            mark_rows.append((base_open, 100.0, 100.0, 99.9, 100.0))
            mark_rows.append((base_open + 60_000, 60.0, 65.0, 50.0, 55.0))
        else:
            mark_rows.append((base_open, 100.0, 100.0, 99.9, 100.0))
        for m in range(2, horizon_bars):
            mark_rows.append((base_open + m * 60_000, 100.0, 100.1, 99.9, 100.0))
    mark = _mark(mark_rows).sort("open_time")

    vec = bs.resolve_barriers_vectorized(
        filled,
        mark,
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=_CFG.tp_atr_mult,
        sl_atr_mult=_CFG.sl_atr_mult,
        time_stop_ms=_CFG.time_stop_ms,
        maker_fee=_CFG.maker_fee,
        taker_fee=_CFG.taker_fee,
        adverse_selection_bps=_CFG.adverse_selection_bps,
    )
    assert vec.barrier_hit == ["TP", "SL", "TIME"]


# ============================================================================
# tf — AG-005 (audit/architecture_gaps_log.yaml)
# ============================================================================


def test_resolve_barriers_vectorized_tf_default_bate_bit_exato_com_explicito() -> None:
    """AG-005 — `tf` omitido (default `"15m"`) tem que produzir EXATAMENTE
    o mesmo resultado que `tf="15m"` explícito — preserva todo caller
    existente (`src.analysis.faixa2_caminho_b`, testes acima) bit-exato."""
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            ]
        )
    )
    scalar_out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    filled = scalar_out.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    out_default = bs.resolve_barriers_vectorized(
        filled,
        mark,
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=_CFG.tp_atr_mult,
        sl_atr_mult=_CFG.sl_atr_mult,
        time_stop_ms=_CFG.time_stop_ms,
        maker_fee=_CFG.maker_fee,
        taker_fee=_CFG.taker_fee,
        adverse_selection_bps=_CFG.adverse_selection_bps,
    )
    out_explicit = bs.resolve_barriers_vectorized(
        filled,
        mark,
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=_CFG.tp_atr_mult,
        sl_atr_mult=_CFG.sl_atr_mult,
        time_stop_ms=_CFG.time_stop_ms,
        maker_fee=_CFG.maker_fee,
        taker_fee=_CFG.taker_fee,
        adverse_selection_bps=_CFG.adverse_selection_bps,
        tf="15m",
    )
    assert out_default.barrier_hit == out_explicit.barrier_hit
    assert np.array_equal(out_default.t1_ms, out_explicit.t1_ms)
    assert np.array_equal(out_default.n_bars_held, out_explicit.n_bars_held)
    assert np.allclose(out_default.ret_net, out_explicit.ret_net)


def test_resolve_barriers_vectorized_tf_invalido_levanta_unsupportedtimeframeerror() -> None:
    """AG-005 — `step_ms(tf)` roda ANTES de qualquer acesso a `filled`/
    `mark_1m`/`funding` (primeira linha da função), então falha alto mesmo
    com DataFrames vazios/placeholder."""
    from src.data.resample import UnsupportedTimeframeError

    with pytest.raises(UnsupportedTimeframeError):
        bs.resolve_barriers_vectorized(
            pl.DataFrame(),
            pl.DataFrame(),
            pl.DataFrame(),
            side=1,
            tp_atr_mult=2.0,
            sl_atr_mult=1.5,
            time_stop_ms=4 * _BAR_MS,
            maker_fee=0.0002,
            taker_fee=0.0005,
            adverse_selection_bps=0.0,  # AG-432 -- ver nota nos outros casos sintéticos
            tf="45m",
        )


def test_resolve_barriers_vectorized_horizon_e_invariante_a_tf_nao_escala_mais() -> None:
    """AG-031/B1 — substitui `test_resolve_barriers_vectorized_horizon_
    escala_com_tf_diferente_de_15m` (travava exatamente a convenção que
    este achado corrige). Cenário TIME (mark plano, nunca toca TP/SL),
    `filled` construído diretamente para isolar só o efeito de `tf`. Com
    `time_stop_ms` fixo, `t1_ms` tem que ser o MESMO valor absoluto em
    qualquer `tf` — `n_bars_held`, ao contrário, diverge (mesmo relógio,
    `bar_ms` diferente), efeito colateral esperado, não bug."""
    from src.data.resample import step_ms

    t0_i = _BASE_MS
    fill_px = 100.0
    atr_pct = 0.004  # tp=100.8/sl=99.4 (tp_atr_mult=2.0/sl_atr_mult=1.5) -- mark plano nunca toca
    filled = pl.DataFrame(
        {
            "t0": [t0_i],
            "t_entry": [t0_i + 60_000],
            "entry_price_fill": [fill_px],
            "atr_at_t0": [atr_pct],
        }
    ).with_columns(
        pl.col("t0").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
        pl.col("t_entry").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
    )

    def _flat_mark(time_stop_ms: int) -> pl.DataFrame:
        horizon = t0_i + time_stop_ms
        n_1m_bars = (horizon - (t0_i + 60_000)) // 60_000 + 1
        rows: list[_Row] = [
            (t0_i + 60_000 + m * 60_000, fill_px, fill_px + 0.05, fill_px - 0.05, fill_px)
            for m in range(int(n_1m_bars))
        ]
        return _mark(rows)

    time_stop_ms = 4 * step_ms("15m")  # 3_600_000ms -- mesmo relógio para os dois TFs abaixo
    vec_15m = bs.resolve_barriers_vectorized(
        filled,
        _flat_mark(time_stop_ms),
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        time_stop_ms=time_stop_ms,
        maker_fee=0.0002,
        taker_fee=0.0005,
        # AG-432 -- 0,0 explicito: estes casos sinteticos afirmam sobre
        # RESOLUCAO DE BARREIRA, nao sobre politica de custo. A cobranca de
        # selecao adversa tem teste proprio
        # (`test_selecao_adversa_cobrada_so_nas_pernas_maker`).
        adverse_selection_bps=0.0,
        tf="15m",
    )
    vec_30m = bs.resolve_barriers_vectorized(
        filled,
        _flat_mark(time_stop_ms),
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        time_stop_ms=time_stop_ms,
        maker_fee=0.0002,
        taker_fee=0.0005,
        # AG-432 -- 0,0 explicito: estes casos sinteticos afirmam sobre
        # RESOLUCAO DE BARREIRA, nao sobre politica de custo. A cobranca de
        # selecao adversa tem teste proprio
        # (`test_selecao_adversa_cobrada_so_nas_pernas_maker`).
        adverse_selection_bps=0.0,
        tf="30m",
    )
    assert vec_15m.barrier_hit == ["TIME"]
    assert vec_30m.barrier_hit == ["TIME"]
    # n_bars_held diverge por construção -- mesmo relógio, bar_ms diferente.
    assert int(vec_15m.n_bars_held[0]) == time_stop_ms // step_ms("15m")
    assert int(vec_30m.n_bars_held[0]) == time_stop_ms // step_ms("30m")

    expected_t1 = t0_i + time_stop_ms
    assert int(vec_15m.t1_ms[0]) == expected_t1
    assert int(vec_30m.t1_ms[0]) == expected_t1
    # a garantia central de AG-031/B1: o horizonte NÃO escala mais com tf.
    assert int(vec_15m.t1_ms[0]) == int(vec_30m.t1_ms[0])


def test_resolve_barriers_vectorized_n_bars_held_contagem_real_detecta_gap() -> None:
    """AG-031/B1 -- `decision_bar_close_time_ms` fornecido faz `n_bars_held`
    virar contagem REAL (busca no array), mesma lógica de `triple_barrier.
    build_labels`, sensível a gaps reais -- não é só uma reformulação
    equivalente da aritmética antiga `ceil((t1-t0)/bar_ms)`."""
    t0_i = _BASE_MS
    fill_px = 100.0
    atr_pct = 0.004  # tp=100.8/sl=99.4 -- mark plano nunca toca
    filled = pl.DataFrame(
        {
            "t0": [t0_i],
            "t_entry": [t0_i + 60_000],
            "entry_price_fill": [fill_px],
            "atr_at_t0": [atr_pct],
        }
    ).with_columns(
        pl.col("t0").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
        pl.col("t_entry").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
    )
    time_stop_ms = 4 * _BAR_MS
    horizon = t0_i + time_stop_ms
    n_1m_bars = (horizon - (t0_i + 60_000)) // 60_000 + 1
    mark_rows: list[_Row] = [
        (t0_i + 60_000 + m * 60_000, fill_px, fill_px + 0.05, fill_px - 0.05, fill_px)
        for m in range(int(n_1m_bars))
    ]
    mark = _mark(mark_rows)

    # GAP deliberado -- pula o slot de t0_i + 3*_BAR_MS, então o horizonte
    # (t0_i + 4*_BAR_MS) cai no índice 3 do array, não no índice 4 que a
    # aritmética presumiria.
    decision_bar_close_time_ms = np.array(
        [t0_i, t0_i + 1 * _BAR_MS, t0_i + 2 * _BAR_MS, t0_i + 4 * _BAR_MS],
        dtype=np.int64,
    )

    vec = bs.resolve_barriers_vectorized(
        filled,
        mark,
        _EMPTY_FUNDING,
        side=1,
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        time_stop_ms=time_stop_ms,
        maker_fee=0.0002,
        taker_fee=0.0005,
        # AG-432 -- 0,0 explicito: estes casos sinteticos afirmam sobre
        # RESOLUCAO DE BARREIRA, nao sobre politica de custo. A cobranca de
        # selecao adversa tem teste proprio
        # (`test_selecao_adversa_cobrada_so_nas_pernas_maker`).
        adverse_selection_bps=0.0,
        tf="15m",
        decision_bar_close_time_ms=decision_bar_close_time_ms,
    )
    assert vec.barrier_hit == ["TIME"]
    naive_arithmetic = -(-time_stop_ms // _BAR_MS)  # ceil division, mesma fórmula antiga
    assert naive_arithmetic == 4
    assert int(vec.n_bars_held[0]) == 3, "contagem real tem que refletir o gap"
    assert int(vec.n_bars_held[0]) != naive_arithmetic


# ============================================================================
# Reprodução sobre dado real — 2024, um ano, side=1 (mais barato que os
# 6,5 anos completos do E1 de verdade).
# ============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_reproduz_distribuicao_real_2024_long() -> None:
    from datetime import timedelta

    from src.data import lake

    _skip_path = CAPACITY_DIR / "klines_1m" / "BTCUSDT" / "2024-06-01.parquet"
    if not _skip_path.exists():
        pytest.skip(f"fixture ausente no backfill local: {_skip_path}")

    # `AG-257` -- `from_constants()` resolve `entry_fill_source` de
    # `constants.yaml`, hoje "agg_trades" (`AG-236`). Este teste exercita o
    # caminho de CANDLE sobre barras de 15m e não tem `agg_trades` para
    # oferecer -- nem deveria: o que ele afirma é sobre a distribuição de
    # barreira do motor escalar, não sobre a fonte do fill. Declarar
    # `mark_1m` explicitamente mantém o que o teste sempre testou; herdar o
    # default de produção o faria falhar por um motivo que não é o dele.
    cfg = dataclasses.replace(
        tb.LabelConfig.from_constants(),
        entry_fill_source=tb.ENTRY_FILL_SOURCE_MARK_1M,
    )
    start, end = "2024-01-01", "2024-12-31"
    bars_15m = lake.query_bars("BTCUSDT", "15m", start, end, source="klines_1m", cast_prices=True)
    mark_end = (datetime.fromisoformat(end) + timedelta(days=1)).date().isoformat()
    mark_1m = lake.query_bars(
        "BTCUSDT", "1m", start, mark_end, source="mark_price_klines_1m", cast_prices=True
    )
    funding = lake.query_funding("BTCUSDT", start, mark_end)

    scalar_labels = tb.build_labels(
        bars_15m, mark_1m, funding, side=1, config=cfg, historical_filters_fallback=True
    )
    scalar_filled = scalar_labels.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")

    decision_bar_close_time_ms = bars_15m["close_time"].cast(pl.Int64).to_numpy().astype(np.int64)
    vec = bs.resolve_barriers_vectorized(
        scalar_filled,
        mark_1m,
        funding,
        side=1,
        tp_atr_mult=cfg.tp_atr_mult,
        sl_atr_mult=cfg.sl_atr_mult,
        time_stop_ms=cfg.time_stop_ms,
        maker_fee=cfg.maker_fee,
        taker_fee=cfg.taker_fee,
        # AG-432 -- vem do MESMO `cfg` que gerou os labels escalares acima.
        # Foi exatamente esta linha faltando que fez o teste pegar a
        # divergencia de 3 bps (2 x 1,5) quando so o motor escalar tinha
        # sido corrigido: a paridade entre os 2 motores e o guarda-corpo.
        adverse_selection_bps=cfg.adverse_selection_bps,
        decision_bar_close_time_ms=decision_bar_close_time_ms,
    )
    scalar_barrier = scalar_filled["barrier_hit"].cast(pl.Utf8).to_list()
    n_mismatch = sum(1 for a, b in zip(scalar_barrier, vec.barrier_hit, strict=True) if a != b)
    assert n_mismatch == 0, f"{n_mismatch}/{len(scalar_barrier)} trades divergem do motor escalar"

    ret_net_scalar = scalar_filled["ret_net"].to_numpy().astype(np.float64)
    max_abs_diff = float(np.max(np.abs(ret_net_scalar - vec.ret_net)))
    assert max_abs_diff < 1e-6

    # AG-031/B1 -- n_bars_held (contagem real) tem que bater EXATO entre os
    # dois motores sobre dado real de 1 ano inteiro (exercita tanto o ramo
    # de busca real quanto o fallback aritmético da cauda, sem distinção
    # especial -- os dois motores usam a mesma lógica para os dois).
    n_bars_held_scalar = scalar_filled["n_bars_held"].to_numpy().astype(np.int64)
    assert np.array_equal(n_bars_held_scalar, vec.n_bars_held), (
        "n_bars_held diverge entre build_labels e resolve_barriers_vectorized "
        "sobre dado real -- paridade quebrada"
    )
