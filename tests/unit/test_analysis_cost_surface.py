"""Testes de `src/analysis/cost_surface.py` — superfície de custo round-trip
por (`tp_atr_mult`, `sl_atr_mult`). Módulo PÓS-HOC (ver docstring de lá):
lê `cost_entry_bps`/`cost_exit_bps`/`barrier_hit` REALIZADOS do Label
Engine, nunca insumo de treino.

Seis blocos:
1. `cost_axis_values`/`default_grid_axes` — aritmética do grid, conferida à
   mão, mais o eixo real de `constants.yaml` ficando dentro do
   `sweep_range` já declarado (não coincidência, ver `GRID_FACTORS`).
2. `cost_surface_cell` — fixture sintética pequena com `cost_entry_bps`/
   `cost_exit_bps`/`barrier_hit` escolhidos à mão, números conferidos.
3. `build_cost_surface_grid` — fixture sintética de `bars_15m`/`mark_1m`
   (mesmo padrão de `tests/unit/test_labels_triple_barrier.py`) rodando o
   Label Engine de verdade sobre um recorte MINÚSCULO — mecânica da
   orquestração, não o grid real (esse fica em
   `run_and_save_cost_surface_report`, chamado manualmente, ver DoD da
   task).
4. `pivot_cost_surface` — reshape puro.
5. `_atomic_write_json` — B29, `.tmp` não sobrevive.
6. `build_cost_surface_grid_for_symbol` — AG-011: `tf`/`mark_end` não são
   mais hardcode independente de `"15m"`/`+1 dia` fixo (mesma classe de bug
   do AG-005 em `triple_barrier.build_labels_for_symbol`, replicada aqui
   porque este ponto de entrada tinha sua própria cópia). `lake.query_bars`/
   `lake.query_funding`/`build_cost_surface_grid` são monkeypatchados por
   spies — testa só a WIRING (quais argumentos chegam em cada chamada), não
   o grid em si (já coberto no bloco 3 com Label Engine real); rodar IO real
   aqui exigiria backfill local ou um snapshot histórico de filtros só para
   um teste de wiring, custo desproporcional ao que está sendo verificado."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import orjson
import polars as pl
import pytest
import yaml

from src.analysis import cost_surface as cs
from src.core.metric import Unit
from src.data import lake
from src.data.resample import step_ms
from src.features.groups.group_e import round_trip_cost_bps
from src.labels import triple_barrier as tb
from src.labels._paths import CONSTANTS_PATH

# ============================================================================
# 1. cost_axis_values / default_grid_axes
# ============================================================================


def test_cost_axis_values_fatores_default_conferidos_a_mao() -> None:
    assert cs.cost_axis_values(2.0) == pytest.approx((1.4, 2.0, 2.6))
    assert cs.cost_axis_values(1.5) == pytest.approx((1.05, 1.5, 1.95))


def test_cost_axis_values_aceita_fatores_customizados() -> None:
    assert cs.cost_axis_values(10.0, factors=(0.5, 1.0)) == pytest.approx((5.0, 10.0))


def test_cost_axis_values_deduplica_e_ordena() -> None:
    # dois fatores que colidem no mesmo valor -> 1 ponto só, não 2 repetidos
    assert cs.cost_axis_values(1.0, factors=(1.0, 1.0, 2.0)) == pytest.approx((1.0, 2.0))


def test_default_grid_axes_usa_tp_sl_do_config_passado() -> None:
    cfg = tb.LabelConfig(
        tp_atr_mult=4.0,
        sl_atr_mult=2.0,
        time_stop_bars=32,
        fill_timeout_bars=1,
        atr_window=20,
        maker_fee=0.0002,
        taker_fee=0.0005,
        estimator_id="atr_wilder_w20",
    )
    tp_axis, sl_axis = cs.default_grid_axes(cfg)
    assert tp_axis == pytest.approx((2.8, 4.0, 5.2))
    assert sl_axis == pytest.approx((1.4, 2.0, 2.6))


def test_default_grid_axes_fica_dentro_do_sweep_range_declarado() -> None:
    """`GRID_FACTORS` (±30%) foi escolhido pra caber dentro do
    `sweep_range` que `constants.yaml` já declara pra `tp_atr_mult`/
    `sl_atr_mult` (§16.10 Regra 4) — conferido contra o arquivo real, não
    reafirmado de memória."""
    raw = yaml.safe_load(CONSTANTS_PATH.read_text(encoding="utf-8"))
    tp_range = raw["tp_atr_mult"]["sweep_range"]
    sl_range = raw["sl_atr_mult"]["sweep_range"]

    tp_axis, sl_axis = cs.default_grid_axes()
    assert tp_range[0] <= min(tp_axis) and max(tp_axis) <= tp_range[1]
    assert sl_range[0] <= min(sl_axis) and max(sl_axis) <= sl_range[1]


# ============================================================================
# 2. cost_surface_cell — fixture sintética, números conferidos à mão
# ============================================================================


def _labels_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "side": pl.Series([r["side"] for r in rows], dtype=pl.Int8),
            "barrier_hit": pl.Series([r["barrier_hit"] for r in rows], dtype=pl.Utf8),
            "cost_entry_bps": pl.Series([r["cost_entry_bps"] for r in rows], dtype=pl.Float64),
            "cost_exit_bps": pl.Series([r["cost_exit_bps"] for r in rows], dtype=pl.Float64),
        }
    )


def _mixed_fixture() -> pl.DataFrame:
    # long (side=1): 2x TP (round_trip=4.0), 1x SL (round_trip=7.0), 1x NOFILL
    # short (side=-1): 1x TIME (round_trip=7.0) -- TIME também paga taker (ver
    # docstring do módulo: só TP tem saída maker).
    rows = [
        {"side": 1, "barrier_hit": "TP", "cost_entry_bps": 2.0, "cost_exit_bps": 2.0},
        {"side": 1, "barrier_hit": "TP", "cost_entry_bps": 2.0, "cost_exit_bps": 2.0},
        {"side": 1, "barrier_hit": "SL", "cost_entry_bps": 2.0, "cost_exit_bps": 5.0},
        {"side": 1, "barrier_hit": "NOFILL", "cost_entry_bps": 0.0, "cost_exit_bps": 0.0},
        {"side": -1, "barrier_hit": "TIME", "cost_entry_bps": 2.0, "cost_exit_bps": 5.0},
    ]
    return _labels_frame(rows)


def test_cost_surface_cell_long_conferido_a_mao() -> None:
    out = cs.cost_surface_cell(
        _mixed_fixture(),
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        source="test",
        reference_round_trip_bps_5050=5.5,
    )
    long_row = out.filter(pl.col("side") == "long").row(0, named=True)

    assert long_row["n_total"] == 4
    assert long_row["n_filled"] == 3
    assert long_row["frac_tp"] == pytest.approx(0.5)
    assert long_row["frac_sl"] == pytest.approx(0.25)
    assert long_row["frac_time"] == pytest.approx(0.0)
    assert long_row["frac_nofill"] == pytest.approx(0.25)
    # taker (SL+TIME) = 1 dos 3 preenchidos
    assert long_row["taker_exit_share_of_filled"] == pytest.approx(1.0 / 3.0)
    assert long_row["entry_leg_bps_mean"] == pytest.approx(2.0)
    assert long_row["exit_leg_bps_mean"] == pytest.approx((2.0 + 2.0 + 5.0) / 3.0)
    # round_trip médio: (4.0 + 4.0 + 7.0) / 3
    assert long_row["cost_value"] == pytest.approx((4.0 + 4.0 + 7.0) / 3.0)
    assert long_row["cost_unit"] == Unit.BPS_PER_TRADE.value
    assert long_row["cost_n"] == 3
    assert long_row["cost_n_semantics"] == "trades"
    assert long_row["cost_valid"] is True
    assert long_row["tp_atr_mult"] == pytest.approx(2.0)
    assert long_row["sl_atr_mult"] == pytest.approx(1.5)
    assert long_row["reference_round_trip_bps_5050"] == pytest.approx(5.5)


def test_cost_surface_cell_short_time_conta_como_taker() -> None:
    """Achado do módulo: TIME também sai taker — a saída maker é EXCLUSIVA
    de TP. `taker_exit_share_of_filled` do lado short (só 1 trade, TIME)
    tem que ser 1.0, não 0.0."""
    out = cs.cost_surface_cell(
        _mixed_fixture(),
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        source="test",
        reference_round_trip_bps_5050=5.5,
    )
    short_row = out.filter(pl.col("side") == "short").row(0, named=True)
    assert short_row["n_total"] == 1
    assert short_row["n_filled"] == 1
    assert short_row["frac_time"] == pytest.approx(1.0)
    assert short_row["taker_exit_share_of_filled"] == pytest.approx(1.0)
    assert short_row["cost_value"] == pytest.approx(7.0)


def test_cost_surface_cell_sem_trade_preenchido_vira_not_computable() -> None:
    rows = [
        {"side": 1, "barrier_hit": "NOFILL", "cost_entry_bps": 0.0, "cost_exit_bps": 0.0},
        {"side": -1, "barrier_hit": "NOFILL", "cost_entry_bps": 0.0, "cost_exit_bps": 0.0},
    ]
    out = cs.cost_surface_cell(
        _labels_frame(rows),
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        source="test",
        reference_round_trip_bps_5050=5.5,
    )
    long_row = out.filter(pl.col("side") == "long").row(0, named=True)
    assert long_row["n_filled"] == 0
    assert long_row["cost_valid"] is False
    assert math.isnan(long_row["cost_value"])
    assert long_row["cost_invalid_reason"] is not None
    # sem trade preenchido, taker_exit_share não é calculável -> nan
    assert math.isnan(long_row["taker_exit_share_of_filled"])


def test_cost_surface_cell_coluna_ausente_levanta_valueerror() -> None:
    bad = pl.DataFrame({"side": pl.Series([1], dtype=pl.Int8)})
    with pytest.raises(ValueError, match="coluna"):
        cs.cost_surface_cell(
            bad, tp_atr_mult=2.0, sl_atr_mult=1.5, source="test", reference_round_trip_bps_5050=5.5
        )


# ============================================================================
# 3. build_cost_surface_grid — fixture sintética, Label Engine real, grid
#    minúsculo (mecânica da orquestração, não o grid de produção)
# ============================================================================

_BAR_MS = 900_000
_BASE_MS = int(datetime(2026, 8, 8, 0, 0, tzinfo=UTC).timestamp() * 1000)
_CLOSES = [100.0, 100.2, 99.9]  # atr_window=3 -> só a última barra tem ATR válido
_BASE_CFG = tb.LabelConfig(
    tp_atr_mult=1.0,  # sobrescrito por célula do grid, valor aqui é irrelevante
    sl_atr_mult=1.0,
    time_stop_bars=4,
    fill_timeout_bars=1,
    atr_window=3,
    maker_fee=0.0002,
    taker_fee=0.0005,
    estimator_id="atr_wilder_w3",
)
_EMPTY_FUNDING = pl.DataFrame(schema={"calc_time": pl.Int64, "last_funding_rate": pl.Float64})


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
    t0 = _synthetic_bars()["close_time"][-1]
    assert isinstance(t0, int)
    return t0


def _crash_mark() -> pl.DataFrame:
    """Mesmo cenário de `test_build_labels_sl_long`/`..._tp_short...` em
    `test_labels_triple_barrier.py`: um crash bem abaixo de qualquer
    barreira plausível dentro do grid — dispara SL pro long e TP pro short
    de forma DETERMINÍSTICA, qualquer que seja `tp_atr_mult`/`sl_atr_mult`
    nos valores pequenos usados no grid deste teste (o crash é ~45% do
    preço; mesmo `sl_atr_mult`/`tp_atr_mult` até dezenas de ATR não
    alcançaria essa distância)."""
    t0 = _t0()
    horizon = t0 + _BASE_CFG.time_stop_bars * _BAR_MS
    rows = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        (t0 + 5 * 60_000, 60.0, 65.0, 50.0, 55.0),
        (horizon, 55.0, 55.1, 54.9, 55.0),
    ]
    return pl.DataFrame(
        {
            "open_time": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
        }
    )


def test_build_cost_surface_grid_mecanica_2x2() -> None:
    tp_axis = (1.0, 2.0)
    sl_axis = (1.0, 2.0)
    grid = cs.build_cost_surface_grid(
        _synthetic_bars(),
        _crash_mark(),
        _EMPTY_FUNDING,
        tp_axis=tp_axis,
        sl_axis=sl_axis,
        base_config=_BASE_CFG,
    )

    # 2x2 combinações x 2 lados = 8 linhas
    assert grid.height == 8
    assert set(grid.columns) == {
        "tp_atr_mult", "sl_atr_mult", "side", "n_total", "n_filled",
        "frac_tp", "frac_sl", "frac_time", "frac_nofill",
        "taker_exit_share_of_filled", "entry_leg_bps_mean", "exit_leg_bps_mean",
        "cost_value", "cost_unit", "cost_n", "cost_n_semantics", "cost_source",
        "cost_valid", "cost_invalid_reason", "reference_round_trip_bps_5050",
    }
    assert set(grid["tp_atr_mult"].unique().to_list()) == {1.0, 2.0}
    assert set(grid["sl_atr_mult"].unique().to_list()) == {1.0, 2.0}

    # crash determinístico: long sempre SL, short sempre TP, em toda célula
    long_rows = grid.filter(pl.col("side") == "long")
    short_rows = grid.filter(pl.col("side") == "short")
    assert long_rows.height == 4
    assert short_rows.height == 4
    assert (long_rows["frac_sl"] == 1.0).all()
    assert (short_rows["frac_tp"] == 1.0).all()

    # custo round-trip: long = maker(entrada) + taker(SL) = 2.0 + 5.0 bps
    assert long_rows["cost_value"].to_list() == pytest.approx([7.0] * 4)
    # short = maker(entrada) + maker(TP) = 2.0 + 2.0 bps
    assert short_rows["cost_value"].to_list() == pytest.approx([4.0] * 4)

    # referência 50/50 é CONSTANTE (não depende de tp/sl) e bate com
    # group_e.round_trip_cost_bps reusada, não reimplementada
    expected_ref = round_trip_cost_bps(_BASE_CFG.maker_fee, _BASE_CFG.taker_fee)
    assert grid["reference_round_trip_bps_5050"].to_list() == pytest.approx([expected_ref] * 8)


def test_build_cost_surface_grid_usa_default_grid_axes_quando_eixo_nao_passado() -> None:
    """Sem `tp_axis`/`sl_axis`, usa `default_grid_axes(base_config)` — 3x3."""
    grid = cs.build_cost_surface_grid(
        _synthetic_bars(), _crash_mark(), _EMPTY_FUNDING, base_config=_BASE_CFG
    )
    assert grid.height == 3 * 3 * 2
    expected_tp, expected_sl = cs.default_grid_axes(_BASE_CFG)
    assert set(grid["tp_atr_mult"].unique().to_list()) == set(expected_tp)
    assert set(grid["sl_atr_mult"].unique().to_list()) == set(expected_sl)


def test_build_cost_surface_grid_vazio_sem_eixos_devolve_frame_vazio() -> None:
    grid = cs.build_cost_surface_grid(
        _synthetic_bars(),
        _crash_mark(),
        _EMPTY_FUNDING,
        tp_axis=(),
        sl_axis=(),
        base_config=_BASE_CFG,
    )
    assert grid.height == 0
    assert "cost_value" in grid.columns
    assert "tp_atr_mult" in grid.columns


# ============================================================================
# 4. pivot_cost_surface — reshape puro
# ============================================================================


def _tiny_grid() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "tp_atr_mult": [1.0, 1.0, 2.0, 2.0],
            "sl_atr_mult": [1.0, 2.0, 1.0, 2.0],
            "side": ["long", "long", "long", "long"],
            "cost_value": [10.0, 11.0, 12.0, 13.0],
        }
    )


def test_pivot_cost_surface_reshape_conferido_a_mao() -> None:
    pivoted = cs.pivot_cost_surface(_tiny_grid(), side="long")
    row_tp1 = pivoted.filter(pl.col("tp_atr_mult") == 1.0).row(0, named=True)
    row_tp2 = pivoted.filter(pl.col("tp_atr_mult") == 2.0).row(0, named=True)
    assert row_tp1["1.0"] == pytest.approx(10.0)
    assert row_tp1["2.0"] == pytest.approx(11.0)
    assert row_tp2["1.0"] == pytest.approx(12.0)
    assert row_tp2["2.0"] == pytest.approx(13.0)


def test_pivot_cost_surface_side_invalido_levanta_valueerror() -> None:
    with pytest.raises(ValueError, match="side"):
        cs.pivot_cost_surface(_tiny_grid(), side="both")


def test_pivot_cost_surface_side_ausente_devolve_vazio() -> None:
    pivoted = cs.pivot_cost_surface(_tiny_grid(), side="short")
    assert pivoted.height == 0


# ============================================================================
# 5. _atomic_write_json — B29
# ============================================================================


def test_atomic_write_json_tmp_nao_sobrevive(tmp_path: Path) -> None:
    dest = tmp_path / "sub" / "report.json"
    payload = {"a": 1, "b": [1.0, 2.0, float("nan")]}
    cs._atomic_write_json(payload, dest)

    assert dest.exists()
    assert not dest.with_name(dest.name + ".tmp").exists()

    loaded = orjson.loads(dest.read_bytes())
    assert loaded["a"] == 1
    assert loaded["b"][0] == 1.0
    assert loaded["b"][2] is None  # NaN -> null (orjson), não quebra o round-trip


# ============================================================================
# 6. build_cost_surface_grid_for_symbol — AG-011 (tf/mark_end não mais
#    hardcode independente de "15m"/+1 dia fixo)
# ============================================================================


def _patch_lake_and_grid_spies(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[Any, ...]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Substitui `lake.query_bars`/`lake.query_funding` por spies que só
    registram os argumentos recebidos (devolvendo `DataFrame`s vazios) e
    `build_cost_surface_grid` por um spy que registra o `kwargs` recebido
    (devolvendo um grid vazio no schema real) — isola o teste da wiring de
    IO/orquestração do Label Engine real, já coberto no bloco 3 e nos testes
    de `triple_barrier.build_labels_for_symbol` (AG-005).

    Patcheia o módulo `src.data.lake` diretamente (importado aqui como
    `lake`, o MESMO objeto de módulo que `cs.lake` referencia — `from X
    import Y` só cria um segundo nome pro mesmo objeto, não uma cópia) em
    vez de `cs.lake`: mypy strict (`no_implicit_reexport`) rejeita acessar
    `cs.lake` como atributo não reexportado explicitamente do módulo
    `cost_surface`."""
    query_bars_calls: list[tuple[Any, ...]] = []
    query_funding_calls: list[dict[str, Any]] = []
    grid_calls: list[dict[str, Any]] = []

    def fake_query_bars(
        symbol: str, tf: str, start: Any, end: Any, *, source: str, cast_prices: bool
    ) -> pl.DataFrame:
        query_bars_calls.append((symbol, tf, start, end, source, cast_prices))
        return pl.DataFrame()

    def fake_query_funding(symbol: str, start: Any, end: Any) -> pl.DataFrame:
        query_funding_calls.append({"symbol": symbol, "start": start, "end": end})
        return pl.DataFrame()

    def fake_build_cost_surface_grid(
        bars_15m: pl.DataFrame,
        mark_1m: pl.DataFrame,
        funding: pl.DataFrame,
        **kwargs: Any,
    ) -> pl.DataFrame:
        grid_calls.append(kwargs)
        return pl.DataFrame(schema=cs._GRID_OUTPUT_SCHEMA)

    monkeypatch.setattr(lake, "query_bars", fake_query_bars)
    monkeypatch.setattr(lake, "query_funding", fake_query_funding)
    monkeypatch.setattr(cs, "build_cost_surface_grid", fake_build_cost_surface_grid)
    return query_bars_calls, query_funding_calls, grid_calls


def test_build_cost_surface_grid_for_symbol_default_tf_bate_com_hardcode_anterior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paridade bit-exata do default: sem `base_config`, `LabelConfig.
    from_constants()` resolve `tf="15m"` (mesmo valor que estava hardcoded
    antes do AG-011) — `lake.query_bars` da barra de decisão continua
    recebendo literalmente `"15m"`, callers reais (nenhum passa `base_config`
    hoje, ver grep na task) veem exatamente a mesma chamada de antes."""
    query_bars_calls, query_funding_calls, grid_calls = _patch_lake_and_grid_spies(monkeypatch)

    cs.build_cost_surface_grid_for_symbol("BTCUSDT", "2024-01-01", "2024-01-02")

    cfg = tb.LabelConfig.from_constants()
    assert cfg.tf == "15m"

    # 1ª chamada: bars_15m no TF de decisão, com o mesmo literal "15m" de
    # antes do AG-011 -- comportamento do default inalterado.
    assert query_bars_calls[0] == ("BTCUSDT", "15m", "2024-01-01", "2024-01-02", "klines_1m", True)

    # mark_1m/funding: a folga MUDA de propósito (essa é a correção AG-011,
    # não um efeito colateral) -- de "+1 dia" fixo para
    # "+ max(time_stop_bars, fill_timeout_bars)*step_ms(tf) + 1 dia", mesma
    # fórmula do AG-005 em triple_barrier.build_labels_for_symbol.
    horizon_ms = max(cfg.time_stop_bars, cfg.fill_timeout_bars) * step_ms(cfg.tf)
    expected_mark_end = date(2024, 1, 2) + timedelta(milliseconds=horizon_ms, days=1)

    assert query_bars_calls[1][:2] == ("BTCUSDT", "1m")
    assert query_bars_calls[1][3] == expected_mark_end
    assert query_funding_calls[0]["end"] == expected_mark_end

    # o núcleo recebe o mesmo cfg resolvido (base_config=cfg), não um valor
    # solto -- é essa mesma instância que determina tf/horizonte acima.
    assert grid_calls[0]["base_config"] == cfg


def test_build_cost_surface_grid_for_symbol_tf_customizado_muda_query_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passar `base_config` com `tf` diferente de `"15m"` muda o TF usado em
    `lake.query_bars` para a barra de decisão -- prova de que a linha 391
    (antes `"15m"` literal) agora lê `cfg.tf`, não um valor fixo."""
    query_bars_calls, query_funding_calls, _grid_calls = _patch_lake_and_grid_spies(monkeypatch)

    base_cfg = replace(tb.LabelConfig.from_constants(), tf="30m")
    assert base_cfg.tf == "30m"  # __post_init__ já validou via step_ms

    cs.build_cost_surface_grid_for_symbol(
        "ETHUSDT", "2024-01-01", "2024-01-02", base_config=base_cfg
    )

    assert query_bars_calls[0] == ("ETHUSDT", "30m", "2024-01-01", "2024-01-02", "klines_1m", True)

    # horizonte em "30m" é maior em ms que em "15m" para o mesmo
    # time_stop_bars/fill_timeout_bars (step_ms("30m") == 2 * step_ms("15m"))
    # -- a folga cresce de acordo, não fica presa ao valor calibrado pra 15m.
    horizon_ms = max(base_cfg.time_stop_bars, base_cfg.fill_timeout_bars) * step_ms("30m")
    expected_mark_end = date(2024, 1, 2) + timedelta(milliseconds=horizon_ms, days=1)
    assert query_bars_calls[1][3] == expected_mark_end
    assert query_funding_calls[0]["end"] == expected_mark_end


def test_build_cost_surface_grid_for_symbol_tf_maior_amplia_folga_vs_15m(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado que motivou o AG-011 (mesmo do AG-005): a folga fixa de "+1
    dia" era calibrada só pro caso 15m -- em TF maior o horizonte de
    `time_stop_bars`/`fill_timeout_bars` (expresso em BARRAS, não em tempo)
    pode ultrapassar 24h. Usa `tf="1h"` (não `"30m"`) de propósito: com os
    valores REAIS de `constants.yaml` (`time_stop_bars=32`,
    `fill_timeout_bars=1`), o horizonte em 30m é 16h -- ainda `< 24h`, então
    `date.__add__` (que ignora `timedelta.seconds`/`.microseconds`, só soma
    `.days` -- comportamento documentado do `datetime` da stdlib, medido
    aqui, não presumido) trunca 15m e 30m pro MESMO `mark_end` (+1 dia); só
    em 1h (horizonte 32h, cruza a fronteira de 24h) a folga realmente muda
    de dia. Achado reportado à parte (não é bug desta correção nem do AG-005
    que ela replica: `lake.query_bars` trata `end` como fronteira de DIA
    inteiro inclusiva, o que já cobre a folga que a truncagem de sub-dia
    perde -- ver relatório final da task)."""
    cfg_15m = tb.LabelConfig.from_constants()
    cfg_1h = replace(cfg_15m, tf="1h")

    query_bars_calls_15m, _, _ = _patch_lake_and_grid_spies(monkeypatch)
    cs.build_cost_surface_grid_for_symbol(
        "BTCUSDT", "2024-01-01", "2024-01-02", base_config=cfg_15m
    )
    mark_end_15m = query_bars_calls_15m[1][3]

    query_bars_calls_1h, _, _ = _patch_lake_and_grid_spies(monkeypatch)
    cs.build_cost_surface_grid_for_symbol(
        "BTCUSDT", "2024-01-01", "2024-01-02", base_config=cfg_1h
    )
    mark_end_1h = query_bars_calls_1h[1][3]

    assert mark_end_1h > mark_end_15m
