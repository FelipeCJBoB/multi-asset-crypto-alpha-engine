"""Testes de `src/regime/classifier.py` — classificador determinístico por
quantis expansivos (§4), histerese + confirmação (§4.5), e as 5 invariantes
literais de §4.8.

Os testes de histerese/confirmação/assimetria de R5 usam séries sintéticas
pequenas e controladas (o ponto é provar a MECÂNICA do laço de estado, não
medir distribuição real — isso fica para `test_regime_build.py`, que roda
contra dado real via `src.regime.build`)."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.regime import classifier, stress

# alias curto — usado nos testes de mecânica de histerese/confirmação
# abaixo, que chamam o laço de estado diretamente (ver docstring da seção
# "Histerese + confirmação" mais adiante para o motivo)
_run_state_machine = classifier._run_state_machine

_THRESHOLDS = classifier.RegimeThresholds(
    er_cutoff_enter=0.60,
    er_cutoff_exit=0.55,
    vol_cutoff_enter=0.70,
    vol_cutoff_exit=0.65,
    min_warmup_bars=5,
    confirmation_bars=2,
    stress_exit_confirmation_bars=4,
)


def _empty_stress_result(n: int) -> stress.StressResult:
    """`StressResult` sem nenhum gatilho ativo — usado nos testes de
    histerese/warmup que não são sobre R5."""
    not_computable = np.full(n, stress.TriggerState.NOT_COMPUTABLE, dtype=object)
    return stress.StressResult(
        triggers={sid: not_computable.copy() for sid in stress.TRIGGER_IDS},
        triggered_mask=np.zeros(n, dtype=bool),
        stress_triggers_list=tuple(() for _ in range(n)),
    )


def _stress_result_with_triggers(n: int, triggered_at: set[int]) -> stress.StressResult:
    mask = np.zeros(n, dtype=bool)
    for i in triggered_at:
        mask[i] = True
    lists = tuple((("S1",) if i in triggered_at else ()) for i in range(n))
    not_computable = np.full(n, stress.TriggerState.NOT_COMPUTABLE, dtype=object)
    triggers = {sid: not_computable.copy() for sid in stress.TRIGGER_IDS}
    s1 = np.full(n, stress.TriggerState.NOT_TRIGGERED, dtype=object)
    for i in triggered_at:
        s1[i] = stress.TriggerState.TRIGGERED
    triggers["S1"] = s1
    return stress.StressResult(triggers=triggers, triggered_mask=mask, stress_triggers_list=lists)


def _open_time(n: int) -> stress.TimeArray:
    return (np.arange(n, dtype=np.int64) * 900_000) + 1_600_000_000_000


# ============================================================================
# RegimeThresholds.from_constants() — leitura real de constants.yaml
# ============================================================================


def test_thresholds_from_constants_bate_com_prd() -> None:
    th = classifier.RegimeThresholds.from_constants()
    assert th.er_cutoff_enter == pytest.approx(0.60)
    assert th.er_cutoff_exit == pytest.approx(0.55)
    assert th.vol_cutoff_enter == pytest.approx(0.70)
    assert th.vol_cutoff_exit == pytest.approx(0.65)
    assert th.min_warmup_bars == 2000
    assert th.confirmation_bars == 2
    assert th.stress_exit_confirmation_bars == 4


# ============================================================================
# R0 — warmup por índice
# ============================================================================


def test_r0_para_todas_as_barras_antes_do_warmup() -> None:
    n = 20
    rng = np.random.default_rng(1)
    er_48 = rng.uniform(0, 1, n)
    vol_pctile = rng.uniform(0, 1, n)
    cost_atr = rng.uniform(0.05, 0.3, n)
    df = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, _empty_stress_result(n), thresholds=_THRESHOLDS
    )
    head = df.head(_THRESHOLDS.min_warmup_bars)
    assert (head["regime"] == "R0").all()
    assert (head["regime_raw"] == "R0").all()
    assert not head["tradeable"].any()
    assert (df.tail(n - _THRESHOLDS.min_warmup_bars)["regime"] != "R0").all()


# ============================================================================
# QuantileRegimeClassifier (PRD_V4_1.md T0.2) — properties (IO real fica em
# test_regime_build.py::test_build_regimes_colunas_e_dtypes)
# ============================================================================


def test_quantile_regime_classifier_n_states_e_classifier_id() -> None:
    qrc = classifier.QuantileRegimeClassifier(symbol="BTCUSDT")
    assert qrc.n_states == 6  # R0..R5
    assert qrc.classifier_id == "quantile_regime_v1"


def test_regime_symbol_tf_dir_layout_chaveado() -> None:
    from src.regime._paths import DATA_ROOT, regime_symbol_tf_dir

    path = regime_symbol_tf_dir("ETHUSDT", classifier.ENGINE_VERSION)
    assert path == DATA_ROOT / "regimes" / "ETHUSDT" / "15m" / classifier.ENGINE_VERSION


# ============================================================================
# I-d (PRD_V4_1.md T0.2) — ponto de injeção para er_quantile/econ_quantile
# ============================================================================


def test_er_quantile_econ_quantile_default_none_recomputa_como_antes() -> None:
    n = 20
    rng = np.random.default_rng(2)
    er_48 = rng.uniform(0, 1, n)
    vol_pctile = rng.uniform(0, 1, n)
    cost_atr = rng.uniform(0.05, 0.3, n)
    stress_result = _empty_stress_result(n)

    default = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, stress_result, thresholds=_THRESHOLDS
    )
    from src.features import support

    explicit = classifier.classify_regimes(
        _open_time(n),
        er_48,
        vol_pctile,
        cost_atr,
        stress_result,
        thresholds=_THRESHOLDS,
        er_quantile=support.expanding_percentile_rank_strict(er_48),
        econ_quantile=support.expanding_percentile_rank_strict(cost_atr),
    )
    assert default.equals(explicit)


def test_er_quantile_injetado_e_usado_em_vez_de_recomputado() -> None:
    # er_quantile injetado, TODO 0.99 (>= er_cutoff_enter=0.60) -- força
    # regime de tendência mesmo com er_48 bruto apontando pra outro lado
    # (valores baixos, que produziriam er_quantile baixo se recomputado).
    n = 20
    er_48 = np.linspace(0.01, 0.02, n)  # bruto todo baixo, de propósito
    vol_pctile = np.zeros(n)
    cost_atr = np.full(n, 0.1)
    forced_er_quantile = np.full(n, 0.99)
    stress_result = _empty_stress_result(n)

    df = classifier.classify_regimes(
        _open_time(n),
        er_48,
        vol_pctile,
        cost_atr,
        stress_result,
        thresholds=_THRESHOLDS,
        er_quantile=forced_er_quantile,
    )
    tail = df.tail(n - _THRESHOLDS.min_warmup_bars)
    assert tail["er_quantile"].to_numpy() == pytest.approx(0.99)
    assert (tail["regime"] == "R3").all()  # trend alto, vol baixo -- R3 (§4.3)


# ============================================================================
# Histerese + confirmação — eixo volatilidade (mesma mecânica do eixo ER)
#
# Estes 3 testes chamam `classifier._run_state_machine` diretamente (não
# `classify_regimes`), passando `er_quantile`/`vol_pctile` já como postos
# em [0,1] — não valores brutos de `er_48`/`vol_pctile` "achatados"
# artificialmente. Motivo medido, não estético: `er_48` CONSTANTE alimentado
# em `classify_regimes` (que recalcula o posto percentil expansivo
# internamente via `expanding_percentile_rank_strict`) não produz um
# `er_quantile` constante — a convenção de desempate por ordem de chegada
# (documentada em `support.expanding_percentile_rank_strict`) trata cada
# nova observação empatada como "maior" que as anteriores, então uma série
# 100% constante deriva assintoticamente para posto 1.0, contaminando
# exatamente o teste de histerese que precisa de um posto ESTÁVEL. Testar
# `_run_state_machine` isolado evita essa armadilha e testa a mecânica de
# §4.5 diretamente; a integração com o posto percentil real (dados não
# empatados) já é coberta por `test_causalidade_perturbar_futuro_nao_muda_
# passado`/`test_invariantes_484_sobre_serie_sintetica` abaixo.
# ============================================================================


def test_troca_de_1_barra_isolada_nao_efetiva_mudanca_de_regime() -> None:
    """Um único pico acima do corte de entrada (sem persistir por
    `confirmation_bars`) NÃO deve trocar o regime confirmado — só
    `regime_raw` reage instantaneamente."""
    n = 10
    er_quantile = np.full(n, 0.30)  # sempre RANGE (er < 0.60)
    vol_pctile = np.full(n, 0.30)  # sempre LOW_VOL
    spike_idx = n - 5
    vol_pctile[spike_idx] = 0.90  # 1 barra isolada acima de 0.70, depois volta
    stress_triggered = np.zeros(n, dtype=bool)
    regime, regime_raw = classifier._run_state_machine(
        er_quantile, vol_pctile, stress_triggered, _THRESHOLDS
    )
    assert (regime[_THRESHOLDS.min_warmup_bars :] == "R1").all()  # confirmado nunca sai de R1
    assert regime_raw[spike_idx] == "R2"  # mas o raw reage na hora


def test_troca_persistente_por_confirmation_bars_efetiva_mudanca() -> None:
    """Vol alto por >= `confirmation_bars` barras consecutivas troca o
    regime confirmado para R2 (RANGE_HIGH_VOL, já que ER continua baixo)."""
    n = 16
    er_quantile = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.30)
    start = 10
    vol_pctile[start:] = 0.90  # 6 barras consecutivas acima do corte de entrada
    stress_triggered = np.zeros(n, dtype=bool)
    regime, _ = _run_state_machine(er_quantile, vol_pctile, stress_triggered, _THRESHOLDS)
    regimes = regime[_THRESHOLDS.min_warmup_bars :].tolist()
    rel_start = start - _THRESHOLDS.min_warmup_bars
    assert regimes[: rel_start - 1] == ["R1"] * (rel_start - 1)
    # confirmação leva `confirmation_bars` barras propondo a troca antes de
    # efetivar — a troca aparece na 2a barra consecutiva de vol alto
    assert regimes[rel_start] == "R1"
    assert regimes[rel_start + 1] == "R2"
    assert regimes[-1] == "R2"


def test_histerese_impede_saida_prematura_na_zona_morta() -> None:
    """Depois de confirmar HIGH_VOL (entrada > 0.70), um valor entre 0.65 e
    0.70 (a "zona morta" da histerese) NÃO deve propor saída — só abaixo de
    0.65 propõe, e só troca depois de `confirmation_bars`."""
    n = 20
    er_quantile = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.90)  # já confirmado em HIGH_VOL bem antes do fim
    vol_pctile[-5:] = 0.68  # dentro da zona morta [0.65, 0.70) -- não é saída nem entrada
    stress_triggered = np.zeros(n, dtype=bool)
    regime, _ = _run_state_machine(er_quantile, vol_pctile, stress_triggered, _THRESHOLDS)
    post_warmup = regime[_THRESHOLDS.min_warmup_bars :]
    assert (post_warmup == "R2").all()  # nunca sai de HIGH_VOL dentro da zona morta


# ============================================================================
# R5 — entrada imediata, saída com stress_exit_confirmation_bars barras
# ============================================================================


def test_r5_entra_imediatamente_numa_unica_barra_de_gatilho() -> None:
    n = _THRESHOLDS.min_warmup_bars + 5
    er_48 = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.30)
    cost_atr = np.full(n, 0.15)
    trigger_idx = n - 3
    stress_result = _stress_result_with_triggers(n, {trigger_idx})
    df = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, stress_result, thresholds=_THRESHOLDS
    )
    assert df["regime"][trigger_idx] == "R5"
    assert df["regime"][trigger_idx - 1] != "R5"  # sem confirmação prévia — não precisa
    assert df["bars_in_regime"][trigger_idx] == 1  # R5 fica de fora do piso de 2


def test_r5_so_sai_apos_stress_exit_confirmation_bars_barras_sem_gatilho() -> None:
    n = _THRESHOLDS.min_warmup_bars + 10
    er_48 = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.30)
    cost_atr = np.full(n, 0.15)
    trigger_idx = n - 8
    stress_result = _stress_result_with_triggers(n, {trigger_idx})
    df = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, stress_result, thresholds=_THRESHOLDS
    )
    regimes = df["regime"].to_list()
    # R5 persiste por stress_exit_confirmation_bars barras depois do gatilho
    # (a barra do gatilho + as N-1 seguintes ainda contam como "confirmando saída")
    for k in range(_THRESHOLDS.stress_exit_confirmation_bars):
        assert regimes[trigger_idx + k] == "R5", f"k={k}"
    assert regimes[trigger_idx + _THRESHOLDS.stress_exit_confirmation_bars] != "R5"


def test_r5_tem_precedencia_sobre_trend_e_vol() -> None:
    """Mesmo com ER/vol claramente em TREND_HIGH_VOL, um gatilho de stress
    ativo força R5."""
    n = _THRESHOLDS.min_warmup_bars + 3
    er_48 = np.full(n, 0.95)  # TREND
    vol_pctile = np.full(n, 0.95)  # HIGH_VOL
    cost_atr = np.full(n, 0.15)
    trigger_idx = n - 1
    stress_result = _stress_result_with_triggers(n, {trigger_idx})
    df = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, stress_result, thresholds=_THRESHOLDS
    )
    assert df["regime"][trigger_idx] == "R5"
    assert df["regime_raw"][trigger_idx] == "R5"


def test_r0_tem_precedencia_sobre_r5_durante_warmup() -> None:
    """Resolução deste Sprint (documentada em classifier.py): um gatilho de
    stress ativo DURANTE o warmup não produz R5 — os quantis usados por
    quase todo gatilho ainda não são confiáveis nesse trecho (mesma razão
    de R0 existir), então R0 vence. `stress_triggers` continua reportando
    o gatilho internamente (informativo), só a label muda."""
    n = _THRESHOLDS.min_warmup_bars
    er_48 = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.30)
    cost_atr = np.full(n, 0.15)
    trigger_idx = 2
    stress_result = _stress_result_with_triggers(n, {trigger_idx})
    df = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, stress_result, thresholds=_THRESHOLDS
    )
    assert df["regime"][trigger_idx] == "R0"
    assert df["regime_raw"][trigger_idx] == "R0"
    assert df["stress_triggers"][trigger_idx].to_list() == ["S1"]


# ============================================================================
# Eixo econômico (§4.3.1) — tercil expansivo, sem histerese
# ============================================================================


def test_economics_regime_tercis_aproximados_em_serie_grande() -> None:
    n = 3000
    rng = np.random.default_rng(7)
    er_48 = rng.uniform(0, 1, n)
    vol_pctile = rng.uniform(0, 1, n)
    cost_atr = rng.uniform(0, 1, n)  # uniforme -> tercis ~ 1/3 cada, exceto cauda inicial
    df = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, _empty_stress_result(n), thresholds=_THRESHOLDS
    )
    counts = df["econ_regime"].value_counts().to_dict(as_series=False)
    by_label = dict(zip(counts["econ_regime"], counts["count"], strict=True))
    favorable = by_label.get("ECONOMICS_FAVORABLE", 0)
    neutral = by_label.get("ECONOMICS_NEUTRAL", 0)
    hostile = by_label.get("ECONOMICS_HOSTILE", 0)
    for count in (favorable, neutral, hostile):
        assert count == pytest.approx(n / 3, rel=0.25)


# ============================================================================
# §4.8 — invariantes literais, sobre série sintética grande
# ============================================================================


def test_invariantes_484_sobre_serie_sintetica() -> None:
    n = 4000
    rng = np.random.default_rng(11)
    er_48 = rng.uniform(0, 1, n)
    vol_pctile = rng.uniform(0, 1, n)
    cost_atr = rng.uniform(0.05, 0.3, n)
    triggered_at = set(rng.choice(n, size=40, replace=False).tolist())
    stress_result = _stress_result_with_triggers(n, triggered_at)
    df = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, stress_result, thresholds=_THRESHOLDS
    )

    assert df["regime"].cast(pl.Utf8).is_in(list(classifier.REGIME_LABELS)).all()
    assert (
        df["tradeable"] == df["regime"].cast(pl.Utf8).is_in(list(classifier.TRADEABLE_REGIMES))
    ).all()
    assert not df.filter(df["regime"] == "R5")["tradeable"].any()
    non_r5 = df.filter(df["regime"] != "R5")
    assert (non_r5["bars_in_regime"] >= 2).all()


def test_bars_in_regime_piso_2_nao_esconde_regressao_de_confirmacao() -> None:
    """O piso de 2 não deveria mascarar um bug em que a confirmação nunca
    dispara (ex.: contador de pending quebrado) — verifica que barras BEM
    depois de uma transição real acumulam além de 2."""
    n = _THRESHOLDS.min_warmup_bars + 30
    er_48 = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.30)
    vol_pctile[n - 20 :] = 0.90
    cost_atr = np.full(n, 0.15)
    df = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, _empty_stress_result(n), thresholds=_THRESHOLDS
    )
    assert df["bars_in_regime"][-1] > 10


# ============================================================================
# Causalidade — perturbar o futuro não muda o passado (B01/B02, quantis
# expansivos SEMPRE usam índice < t, nunca >= t)
# ============================================================================


def test_causalidade_perturbar_futuro_nao_muda_passado() -> None:
    n = _THRESHOLDS.min_warmup_bars + 200
    cutoff = _THRESHOLDS.min_warmup_bars + 100
    rng = np.random.default_rng(42)
    er_48 = rng.uniform(0, 1, n)
    vol_pctile = rng.uniform(0, 1, n)
    cost_atr = rng.uniform(0.05, 0.3, n)
    triggered_at = set(rng.choice(n, size=20, replace=False).tolist())
    stress_result = _stress_result_with_triggers(n, triggered_at)

    df_base = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, stress_result, thresholds=_THRESHOLDS
    )

    er_48_p = er_48.copy()
    vol_pctile_p = vol_pctile.copy()
    cost_atr_p = cost_atr.copy()
    er_48_p[cutoff + 1 :] = rng.uniform(0, 1, n - cutoff - 1)
    vol_pctile_p[cutoff + 1 :] = rng.uniform(0, 1, n - cutoff - 1)
    cost_atr_p[cutoff + 1 :] = rng.uniform(0.05, 0.3, n - cutoff - 1)
    # gatilhos de stress também só podem mudar depois do cutoff
    triggered_at_p = {i for i in triggered_at if i <= cutoff} | {cutoff + 5, cutoff + 6}
    stress_result_p = _stress_result_with_triggers(n, triggered_at_p)

    df_perturbed = classifier.classify_regimes(
        _open_time(n), er_48_p, vol_pctile_p, cost_atr_p, stress_result_p, thresholds=_THRESHOLDS
    )

    for col in ("regime", "regime_raw", "bars_in_regime", "econ_regime", "er_quantile"):
        left = df_base[col].head(cutoff + 1)
        right = df_perturbed[col].head(cutoff + 1)
        assert left.equals(right, null_equal=True), f"coluna {col} mudou no passado"
