"""Testes de `src/regime/stress.py` — os 10 gatilhos de STRESS (§4.4).

Cobre, por gatilho: (1) o valor numérico/threshold correto quando
computável; (2) que `NOT_COMPUTABLE` é um estado real, distinguível de
`NOT_TRIGGERED` (nunca um `False` silencioso); (3) para S6/S10, o caminho
de dado real do repo (Data Quality Engine / snapshots de `exchangeInfo`).

Inclui um teste de regressão dedicado (`test_trigger_state_nao_mistura_str`)
para o bug real encontrado neste Sprint: um `Enum` misturado com `str`
quebra silenciosamente a comparação vetorizada `array == TriggerState.X`
via numpy (`np.asarray` de um membro `str`-mixed usa `str(member)`,
truncado, não `.value`) — `TriggerState` é `Enum` puro por causa disso."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from src.regime import stress
from src.regime._constants import load_constant

# ============================================================================
# TriggerState — regressão do bug str-mixin
# ============================================================================


def test_trigger_state_nao_mistura_str() -> None:
    assert not issubclass(stress.TriggerState, str)


def test_comparacao_vetorizada_numpy_funciona() -> None:
    """Regressão direta do bug: um array `dtype=object` de `TriggerState`
    comparado a um escalar via `==` tem que dar o resultado elemento a
    elemento certo — não `False` em toda barra."""
    triggered, not_triggered = stress.TriggerState.TRIGGERED, stress.TriggerState.NOT_TRIGGERED
    arr = np.array([triggered, not_triggered, triggered], dtype=object)
    result = arr == stress.TriggerState.TRIGGERED
    np.testing.assert_array_equal(result, [True, False, True])


def test_not_computable_e_distinguivel_de_not_triggered_e_triggered() -> None:
    """Os 3 estados são valores distintos — sentinela real, não `False`."""
    states = list(stress.TriggerState)
    assert len(states) == 3
    assert len({id(s) for s in states}) == 3  # os 3 membros são objetos distintos entre si


# ============================================================================
# S1 — vol_pctile_expanding > 0.98 (computável)
# ============================================================================


def test_s01_dispara_acima_do_threshold_e_nao_abaixo() -> None:
    threshold = float(load_constant("stress_vol_pctile_threshold"))
    values = np.array([0.5, threshold + 0.001, threshold - 0.001, threshold])
    out = stress.s01_vol_extreme(values)
    assert out[0] == stress.TriggerState.NOT_TRIGGERED
    assert out[1] == stress.TriggerState.TRIGGERED
    assert out[2] == stress.TriggerState.NOT_TRIGGERED
    assert out[3] == stress.TriggerState.NOT_TRIGGERED  # ">" estrito, não ">="


def test_s01_nan_e_not_computable_nao_not_triggered() -> None:
    out = stress.s01_vol_extreme(np.array([np.nan, 0.5]))
    assert out[0] == stress.TriggerState.NOT_COMPUTABLE
    assert out[1] == stress.TriggerState.NOT_TRIGGERED


# ============================================================================
# S2 — spread_pctile_expanding > 0.95 (dependente de injeção — F02f não existe)
# ============================================================================


def test_s02_sem_array_e_not_computable_em_toda_barra() -> None:
    out = stress.s02_spread_extreme(None, n=10)
    assert len(out) == 10
    assert all(s == stress.TriggerState.NOT_COMPUTABLE for s in out)


def test_s02_com_array_real_funciona_como_threshold_normal() -> None:
    """Se/quando F02f existir e alguém injetar a série real, o gatilho
    funciona normalmente — só o caminho `None` (pipeline real de hoje,
    `src.regime.build`) é `NOT_COMPUTABLE`."""
    out = stress.s02_spread_extreme(np.array([0.99, 0.10]), n=2)
    assert out[0] == stress.TriggerState.TRIGGERED
    assert out[1] == stress.TriggerState.NOT_TRIGGERED


# ============================================================================
# S3 — |funding_z| > 3.0 (computável, gatilho absoluto)
# ============================================================================


def test_s03_dispara_nos_dois_lados_do_zero() -> None:
    out = stress.s03_funding_extreme(np.array([3.5, -3.5, 0.0, 2.9, -2.9]))
    assert out[0] == stress.TriggerState.TRIGGERED
    assert out[1] == stress.TriggerState.TRIGGERED
    assert out[2] == stress.TriggerState.NOT_TRIGGERED
    assert out[3] == stress.TriggerState.NOT_TRIGGERED
    assert out[4] == stress.TriggerState.NOT_TRIGGERED


# ============================================================================
# S4, S5, S7, S8, S9 — NOT_COMPUTABLE sempre (dado não existe/não aplicável)
# ============================================================================


_NOT_COMPUTABLE_TRIGGERS = (
    stress.s04_basis_break,
    stress.s05_stale_data,
    stress.s07_shallow_liquidity,
    stress.s08_event_window,
    stress.s09_liquidation_cascade,
)


@pytest.mark.parametrize("fn", _NOT_COMPUTABLE_TRIGGERS)
def test_gatilhos_nao_computaveis_sao_not_computable_em_toda_barra(fn) -> None:  # type: ignore[no-untyped-def]
    n = 137
    out = fn(n)
    assert len(out) == n
    assert all(s == stress.TriggerState.NOT_COMPUTABLE for s in out)
    # nunca é bool puro, nunca é NOT_TRIGGERED (que pareceria "não disparou")
    assert not any(s == stress.TriggerState.TRIGGERED for s in out)
    assert not any(s == stress.TriggerState.NOT_TRIGGERED for s in out)


# ============================================================================
# S6 — gap de barra (reusa data.checks.check_grid_completeness)
# ============================================================================


def test_s06_sem_gap_tudo_not_triggered() -> None:
    step = 900_000
    ts = np.arange(0, 10 * step, step, dtype=np.int64)
    out = stress.s06_bar_gap(ts, step)
    assert all(s == stress.TriggerState.NOT_TRIGGERED for s in out)


def test_s06_marca_a_barra_de_retomada_apos_um_gap() -> None:
    step = 900_000
    # 0,1,2, [gap em 3], 4,5 -- barra de retomada é o timestamp 4*step
    ts = np.array([0, step, 2 * step, 4 * step, 5 * step], dtype=np.int64)
    out = stress.s06_bar_gap(ts, step)
    assert out[0] == stress.TriggerState.NOT_TRIGGERED
    assert out[1] == stress.TriggerState.NOT_TRIGGERED
    assert out[2] == stress.TriggerState.NOT_TRIGGERED
    assert out[3] == stress.TriggerState.TRIGGERED  # retomada após o gap
    assert out[4] == stress.TriggerState.NOT_TRIGGERED


def test_s06_gap_multiplo_ainda_marca_so_a_retomada() -> None:
    step = 900_000
    ts = np.array([0, step, 5 * step], dtype=np.int64)  # faltam 3 barras (2,3,4)
    out = stress.s06_bar_gap(ts, step)
    assert out[0] == stress.TriggerState.NOT_TRIGGERED
    assert out[1] == stress.TriggerState.NOT_TRIGGERED
    assert out[2] == stress.TriggerState.TRIGGERED


@pytest.mark.integration
def test_s06_serie_real_klines_15m_nao_tem_gap() -> None:
    """Achado do Sprint 5 (medido, não presumido): a grade de 15m derivada
    de `klines_1m` (2019-12-31 -> 2026-08-07, 231.552 barras) não tem
    NENHUMA barra ausente — `check_grid_completeness` confirma isso
    independentemente (ver relatório do Sprint 5). Este teste evita
    reconstruir a série inteira (custoso); usa uma fatia real pequena para
    confirmar que S6 concorda com o Data Quality Engine no caminho feliz."""
    import polars as pl

    from src.data._paths import CAPACITY_DIR
    from src.features import _sources

    if not (CAPACITY_DIR / "klines_1m" / "BTCUSDT" / "2024-01-01.parquet").exists():
        pytest.skip("fixture ausente no backfill local")
    bars = _sources.load_bars_15m("BTCUSDT", "2024-01-01", "2024-01-10")
    ts = bars["open_time"].cast(pl.Int64).to_numpy()
    out = stress.s06_bar_gap(ts, 900_000)
    assert all(s == stress.TriggerState.NOT_TRIGGERED for s in out)


# ============================================================================
# S10 — filters_hash mudou nas últimas 24h (precisa >= 2 snapshots)
# ============================================================================


def test_s10_menos_de_2_snapshots_e_not_computable() -> None:
    ts = np.array([0, 900_000, 1_800_000], dtype=np.int64)
    out_sem_snapshot = stress.s10_filters_hash_changed(ts, None)
    out_1_snapshot = stress.s10_filters_hash_changed(ts, ((0, "h1"),))
    assert all(s == stress.TriggerState.NOT_COMPUTABLE for s in out_sem_snapshot)
    assert all(s == stress.TriggerState.NOT_COMPUTABLE for s in out_1_snapshot)


def test_s10_com_2_snapshots_dispara_dentro_da_janela_de_24h() -> None:
    hour = 3_600_000
    change_at = 100 * hour
    snapshots = ((0, "hash_a"), (change_at, "hash_b"))
    ts = np.array(
        [change_at - hour, change_at, change_at + 23 * hour, change_at + 25 * hour],
        dtype=np.int64,
    )
    out = stress.s10_filters_hash_changed(ts, snapshots)
    assert out[0] == stress.TriggerState.NOT_TRIGGERED  # antes da mudança
    assert out[1] == stress.TriggerState.TRIGGERED  # na mudança
    assert out[2] == stress.TriggerState.TRIGGERED  # 23h depois, ainda dentro da janela
    assert out[3] == stress.TriggerState.NOT_TRIGGERED  # 25h depois, fora da janela de 24h


def test_s10_hash_estavel_nunca_dispara() -> None:
    snapshots = ((0, "hash_a"), (1_000_000, "hash_a"), (2_000_000, "hash_a"))
    ts = np.array([0, 1_000_000, 2_000_000, 3_000_000], dtype=np.int64)
    out = stress.s10_filters_hash_changed(ts, snapshots)
    assert all(s == stress.TriggerState.NOT_TRIGGERED for s in out)


def test_discover_filters_hash_snapshots_estado_real_do_repo() -> None:
    """Medido neste Sprint: só existe 1 snapshot canônico
    (`data/raw/snapshots/exchange_info/2026-08-08.json`) — este teste
    documenta o estado atual como uma asserção viva, não um número
    inventado. Quando um 2º snapshot existir (coleta forward diária), este
    teste passa a falhar de propósito (`>= 1`), sinalizando que
    `s10_filters_hash_changed` já pode ficar computável — não é um teste
    frágil por acidente, é um lembrete acionável."""
    snaps = stress.discover_filters_hash_snapshots("BTCUSDT")
    assert len(snaps) == 1
    ts_ms, h = snaps[0]
    assert datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date().isoformat() == "2026-08-08"
    assert isinstance(h, str) and len(h) == 64  # sha256 hexdigest


@pytest.mark.integration
def test_compute_filters_hash_determinismo_e_sensibilidade() -> None:
    from dataclasses import replace

    from src.exchange import filters as exchange_filters

    snaps_dir_hashes = stress.discover_filters_hash_snapshots("BTCUSDT")
    if not snaps_dir_hashes:
        pytest.skip("sem snapshot local de exchangeInfo")

    f = exchange_filters.load_filters_asof(datetime(2026, 8, 8, tzinfo=UTC), symbol="BTCUSDT")
    h1 = stress.compute_filters_hash(f)
    h2 = stress.compute_filters_hash(f)
    assert h1 == h2  # determinístico

    from decimal import Decimal

    f_changed = replace(f, min_notional=f.min_notional + Decimal("1"))
    h3 = stress.compute_filters_hash(f_changed)
    assert h3 != h1  # sensível a mudança de campo relevante


# ============================================================================
# compute_stress_triggers — composição
# ============================================================================


def test_compute_stress_triggers_agrega_ids_triggered_em_ordem() -> None:
    n = 5
    ts = np.arange(0, n * 900_000, 900_000, dtype=np.int64)
    vol = np.array([0.5, 0.99, 0.5, 0.5, 0.5])  # S1 dispara em t=1
    funding = np.array([0.0, 0.0, 3.5, 0.0, 0.0])  # S3 dispara em t=2
    inputs = stress.StressInputs(
        n=n,
        open_time_ms=ts,
        vol_pctile_expanding=vol,
        funding_z_expanding=funding,
        spread_pctile_expanding=None,
        filters_hash_snapshots=None,
    )
    result = stress.compute_stress_triggers(inputs)
    assert result.stress_triggers_list[0] == ()
    assert result.stress_triggers_list[1] == ("S1",)
    assert result.stress_triggers_list[2] == ("S3",)
    assert result.triggered_mask.tolist() == [False, True, True, False, False]


def test_compute_stress_triggers_step_ms_default_e_15m() -> None:
    from src.data.resample import step_ms as resample_step_ms

    n = 3
    ts = np.arange(0, n * 900_000, 900_000, dtype=np.int64)
    inputs = stress.StressInputs(
        n=n,
        open_time_ms=ts,
        vol_pctile_expanding=np.full(n, 0.1),
        funding_z_expanding=np.full(n, 0.0),
    )
    result = stress.compute_stress_triggers(inputs)
    # nenhum gap na grade sintética de 15m -> S6 nunca dispara, confirmando
    # que o step_ms resolvido foi de fato 900_000 (15m), não outro TF
    assert resample_step_ms("15m") == 900_000
    assert all(s == stress.TriggerState.NOT_TRIGGERED for s in result.triggers["S6"])
