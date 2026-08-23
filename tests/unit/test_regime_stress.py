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
# S6 dollar-bar (D-01, causal/expansiva,
# docs/regime_feature_engine_design_doc_2026-08-23.md §3)
# ============================================================================

_S6_DOLLAR_STEP = 900_000


def test_s06_bar_gap_dollar_serie_curta_e_not_computable() -> None:
    out0 = stress.s06_bar_gap_dollar(np.array([], dtype=np.int64))
    out1 = stress.s06_bar_gap_dollar(np.array([0], dtype=np.int64))
    assert len(out0) == 0
    assert list(out1) == [stress.TriggerState.NOT_COMPUTABLE]


def test_s06_bar_gap_dollar_menos_de_3_gaps_anteriores_e_not_computable() -> None:
    step = _S6_DOLLAR_STEP
    ts = np.array([i * step for i in range(5)], dtype=np.int64)  # 4 gaps uniformes
    out = stress.s06_bar_gap_dollar(ts)
    assert out[0] == stress.TriggerState.NOT_TRIGGERED  # barra 0 nunca fecha gap
    assert out[1] == stress.TriggerState.NOT_COMPUTABLE  # gap idx0 -- 0 priors
    assert out[2] == stress.TriggerState.NOT_COMPUTABLE  # gap idx1 -- 1 prior
    assert out[3] == stress.TriggerState.NOT_COMPUTABLE  # gap idx2 -- 2 priors
    assert out[4] == stress.TriggerState.NOT_TRIGGERED  # gap idx3 -- 3 priors, igual à mediana


def test_s06_bar_gap_dollar_nao_monotonico_e_triggered_mesmo_sem_3_priors() -> None:
    """Gap `<=0` dispara incondicional -- inclusive quando ainda não há
    `_S6_MIN_PRIOR_POSITIVE_GAPS` gaps positivos anteriores (problema de
    integridade de dado é ortogonal ao julgamento estatístico, mesma
    semântica de `hmm_gap_check.py`)."""
    step = _S6_DOLLAR_STEP
    ts = np.array([0, step, 2 * step, step, 4 * step, 5 * step], dtype=np.int64)
    # gaps: [step, step, -step, 3*step, step] -- gap idx2 (<=0) fecha na barra 3
    out = stress.s06_bar_gap_dollar(ts)
    assert out[3] == stress.TriggerState.TRIGGERED  # não-monotônico, só 2 priors positivos


def test_s06_bar_gap_dollar_mad_zero_cadencia_quase_toda_identica_detecta_outlier() -> None:
    """Mesmo achado real documentado em `hmm_gap_check.py`
    (`test_gap_anomalo_detectado_com_cadencia_quase_toda_identica`):
    cadência quase perfeitamente regular -> MAD expansivo cai pra 0 antes
    do outlier aparecer -- fallback pro desvio absoluto MÉDIO não pode
    "esconder" o outlier. Valores calculados à mão (ver comentário
    inline)."""
    step = _S6_DOLLAR_STEP
    close_time = [0, step, 2 * step, 3 * step, 4 * step, 5 * step]
    close_time.append(close_time[-1] + 5 * step)  # gap idx5 = 5*step (outlier)
    close_time += [close_time[-1] + step, close_time[-1] + 2 * step, close_time[-1] + 3 * step]
    ts = np.array(close_time, dtype=np.int64)
    out = stress.s06_bar_gap_dollar(ts)

    # gap idx0..2 (barras 1-3): <3 priors -> NOT_COMPUTABLE
    assert out[1] == stress.TriggerState.NOT_COMPUTABLE
    assert out[2] == stress.TriggerState.NOT_COMPUTABLE
    assert out[3] == stress.TriggerState.NOT_COMPUTABLE
    # gap idx3,4 (barras 4,5): 3-4 priors, todos == step -> scale=0, gap==mediana -> NOT_TRIGGERED
    assert out[4] == stress.TriggerState.NOT_TRIGGERED
    assert out[5] == stress.TriggerState.NOT_TRIGGERED
    # gap idx5 (barra 6): 5 priors, todos == step -> scale=0, gap=5*step != mediana -> TRIGGERED
    assert out[6] == stress.TriggerState.TRIGGERED
    # gap idx6,7,8 (barras 7,8,9): outlier já incorporado à referência (1 entre 6/7/8
    # positivos), mediana continua == step, MAD continua 0 (outlier não afeta a mediana
    # com >=6 elementos), fallback pro desvio médio (>0) -- gap==mediana -> z=0 -> NOT_TRIGGERED
    assert out[7] == stress.TriggerState.NOT_TRIGGERED
    assert out[8] == stress.TriggerState.NOT_TRIGGERED
    assert out[9] == stress.TriggerState.NOT_TRIGGERED


def test_s06_bar_gap_dollar_gap_curto_nao_dispara_criterio_unilateral() -> None:
    """Achado do `project_assurance` independente (2026-08-23): critério é
    UNILATERAL (só gap MAIOR que o esperado dispara), não bilateral -- S6
    detecta AUSÊNCIA de barra; um intervalo anomalamente CURTO é o oposto
    disso (atividade/liquidez densa, não problema de dado). Valores
    calculados à mão -- mesma estrutura de
    `test_s06_bar_gap_dollar_mad_zero_cadencia_quase_toda_identica_detecta_outlier`,
    mas o outlier aqui é 10x MENOR que o típico, não 5x maior."""
    step = _S6_DOLLAR_STEP
    close_time = [0, step, 2 * step, 3 * step, 4 * step, 5 * step]
    close_time.append(close_time[-1] + step // 10)  # gap idx5 = 0,1*step (curto, não longo)
    close_time += [close_time[-1] + step, close_time[-1] + 2 * step, close_time[-1] + 3 * step]
    ts = np.array(close_time, dtype=np.int64)
    out = stress.s06_bar_gap_dollar(ts)

    assert out[4] == stress.TriggerState.NOT_TRIGGERED
    assert out[5] == stress.TriggerState.NOT_TRIGGERED
    # gap curto (idx5): scale=0 (cadência uniforme até aqui), gap < mediana
    # -- critério bilateral antigo dispararia aqui (gap != mediana); o
    # critério unilateral correto não dispara (gap não é MAIOR, não indica
    # ausência de barra)
    assert out[6] == stress.TriggerState.NOT_TRIGGERED
    assert out[7] == stress.TriggerState.NOT_TRIGGERED
    assert out[8] == stress.TriggerState.NOT_TRIGGERED
    assert out[9] == stress.TriggerState.NOT_TRIGGERED


def test_s06_bar_gap_dollar_determinismo() -> None:
    step = _S6_DOLLAR_STEP
    rng_gaps = [step, step, step, 4 * step, step, step, step, 2 * step, step]
    ts = np.cumsum(np.array([0, *rng_gaps], dtype=np.int64))
    out1 = stress.s06_bar_gap_dollar(ts)
    out2 = stress.s06_bar_gap_dollar(ts)
    assert list(out1) == list(out2)


def test_s06_bar_gap_dollar_prova_causalidade_gap_futuro_nao_muda_passado() -> None:
    """Prova direta de causalidade (§10 do design doc,
    docs/regime_feature_engine_design_doc_2026-08-23.md): um gap anômalo
    que aparece SÓ no futuro (barras tardias) não pode mudar a
    classificação de nenhuma barra ANTERIOR a ele -- a saída pro prefixo
    comum entre as duas séries tem que ser bit-idêntica."""
    step = _S6_DOLLAR_STEP
    close_time_sem_futuro = [i * step for i in range(8)]
    close_time_com_futuro_anomalo = [*close_time_sem_futuro, close_time_sem_futuro[-1] + 5 * step]

    ts_sem = np.array(close_time_sem_futuro, dtype=np.int64)
    ts_com = np.array(close_time_com_futuro_anomalo, dtype=np.int64)

    out_sem = stress.s06_bar_gap_dollar(ts_sem)
    out_com = stress.s06_bar_gap_dollar(ts_com)

    assert len(out_sem) == 8
    assert len(out_com) == 9
    assert list(out_sem) == list(out_com[:8])


# ============================================================================
# compute_stress_triggers — despacho de S6 por bar_source (D-01)
# ============================================================================


def test_compute_stress_triggers_bar_source_dollar_sem_close_time_ms_levanta_valueerror() -> None:
    n = 5
    ts = np.arange(0, n * 900_000, 900_000, dtype=np.int64)
    inputs = stress.StressInputs(
        n=n,
        open_time_ms=ts,
        vol_pctile_expanding=np.full(n, 0.1),
        funding_z_expanding=np.full(n, 0.0),
        bar_source="dollar_r1",
        close_time_ms=None,
    )
    with pytest.raises(ValueError, match="close_time_ms"):
        stress.compute_stress_triggers(inputs)


def test_compute_stress_triggers_bar_source_dollar_despacha_s06_dollar() -> None:
    """Grade IRREGULAR (dollar-bar real) faria `s06_bar_gap` (grade fixa)
    disparar em quase toda barra -- `bar_source='dollar_r1'` precisa
    despachar pra `s06_bar_gap_dollar` (que não assume `step_ms` fixo) e
    NÃO disparar nas mesmas barras, provando que o despacho real
    aconteceu, não só que o default (`s06_bar_gap`) continuou rodando."""
    n = 6
    close_time_ms = np.array(
        [0, 900_000, 2_100_000, 2_400_000, 3_600_000, 5_400_000], dtype=np.int64
    )  # gaps irregulares por construção (dollar-bar real nunca tem step_ms fixo)
    inputs = stress.StressInputs(
        n=n,
        open_time_ms=close_time_ms,
        vol_pctile_expanding=np.full(n, 0.1),
        funding_z_expanding=np.full(n, 0.0),
        bar_source="dollar_r1",
        close_time_ms=close_time_ms,
    )
    result = stress.compute_stress_triggers(inputs)
    expected = stress.s06_bar_gap_dollar(close_time_ms)
    assert list(result.triggers["S6"]) == list(expected)


def test_compute_stress_triggers_bar_source_time_15m_continua_usando_s06_bar_gap() -> None:
    """`bar_source='time_15m'` (default) preserva bit-exato o caminho
    legado -- S6 despacha pra `s06_bar_gap`, não `s06_bar_gap_dollar`,
    mesmo se `close_time_ms` for passado por acidente."""
    n = 5
    ts = np.arange(0, n * 900_000, 900_000, dtype=np.int64)
    inputs = stress.StressInputs(
        n=n,
        open_time_ms=ts,
        vol_pctile_expanding=np.full(n, 0.1),
        funding_z_expanding=np.full(n, 0.0),
        bar_source="time_15m",
        close_time_ms=ts,
    )
    result = stress.compute_stress_triggers(inputs)
    assert all(s == stress.TriggerState.NOT_TRIGGERED for s in result.triggers["S6"])


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
