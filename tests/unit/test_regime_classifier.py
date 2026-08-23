"""Testes de `src/regime/classifier.py` — classificador determinístico por
quantis expansivos (§4), histerese + confirmação (§4.5), e as 5 invariantes
literais de §4.8.

Os testes de histerese/confirmação/assimetria de R5 usam séries sintéticas
pequenas e controladas (o ponto é provar a MECÂNICA do laço de estado, não
medir distribuição real — isso fica para `test_regime_build.py`, que roda
contra dado real via `src.regime.build`)."""

from __future__ import annotations

import dataclasses

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
    # min_warmup_bars DIVERGE do PRD (§18.5.2 cita 2000) de propósito --
    # AG-027 (2026-08-15, config/constants.yaml) recalculou por fórmula
    # (max lookback fixo + convergência de suavização) pra 200, DERIVED,
    # substituindo a convenção herdada nunca testada. Teste nunca tinha
    # sido re-rodado desde essa mudança (achado via pytest do usuário,
    # 2026-08-16) -- ficou hardcoded no valor antigo do PRD.
    assert th.min_warmup_bars == 200
    assert th.confirmation_bars == 2
    assert th.stress_exit_confirmation_bars == 4
    # AG-030 (T0.5): min_common_history_bars_15m, config/constants.yaml
    assert th.min_common_history_bars == 164256


def test_thresholds_min_common_history_bars_default_e_none() -> None:
    """Construção manual (sem `from_constants()`) sem o campo novo -- mesmo
    caminho que `_THRESHOLDS` deste arquivo já usa -- preserva o
    comportamento anterior ao AG-030 (sem cap)."""
    th = classifier.RegimeThresholds(
        er_cutoff_enter=0.60,
        er_cutoff_exit=0.55,
        vol_cutoff_enter=0.70,
        vol_cutoff_exit=0.65,
        min_warmup_bars=5,
        confirmation_bars=2,
        stress_exit_confirmation_bars=4,
    )
    assert th.min_common_history_bars is None


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


def test_quantile_regime_classifier_bar_source_dollar_inspeciona_stress_regime_e_raw() -> None:
    """D-01 (`docs/regime_feature_engine_design_doc_2026-08-23.md` §3) --
    `QuantileRegimeClassifier(bar_source="dollar_r1")` precisa propagar
    `close_time` (já presente em `features`,
    `src.features.build.ALL_OUTPUT_COLUMNS`) pra `StressInputs` e S6
    precisa de fato mudar `stress_triggers`/`regime`/`regime_raw` sob um
    gap real conhecido -- não só `tradeable` (achado do design doc §7
    item 6: `regime` alimenta `monotone_constraints` do Alpha em produção
    real via `environments.py`/`monotonic.py`, precisa estar CORRETO, não
    só "não quebrar"). `er_48` estritamente decrescente mantém
    `er_quantile == 0` (abaixo do cutoff de tendência) em toda a série --
    isola o efeito de S6 sem interferência do eixo tendência/volatilidade."""
    step = 900_000
    close_time = [
        0, step, 2 * step, 3 * step, 4 * step, 5 * step,
        10 * step, 11 * step, 12 * step, 13 * step,
    ]  # fmt: skip -- gap idx5 (fecha na barra 6) = 5*step, o resto uniforme
    n = len(close_time)
    close_time_ms = np.array(close_time, dtype=np.int64)
    er_48 = np.array([1.0 - 0.1 * i for i in range(n)])  # estritamente decrescente
    features = pl.DataFrame(
        {
            "open_time": close_time_ms,
            "close_time": close_time_ms,
            "B07_efficiency_ratio_48": er_48,
            "C07_vol_pctile_expanding": np.full(n, 0.1),
            "E02f_funding_z_expanding": np.full(n, 0.0),
            "E27f_cost_atr_ratio": np.full(n, 0.1),
        }
    )
    qrc = classifier.QuantileRegimeClassifier(
        symbol="BTCUSDT", thresholds=_THRESHOLDS, bar_source="dollar_r1"
    )
    df = qrc.classify(features)

    regime = df["regime"].to_list()
    regime_raw = df["regime_raw"].to_list()
    tradeable = df["tradeable"].to_list()
    stress_triggers = df["stress_triggers"].to_list()

    assert regime[:5] == ["R0"] * 5  # warmup (min_warmup_bars=5)
    assert regime_raw[:5] == ["R0"] * 5
    assert regime[5] == "R1"  # não-warmup, sem stress, trend/vol raw ambos baixos
    assert regime_raw[5] == "R1"
    assert stress_triggers[5] == []
    assert regime[6] == "R5"  # S6 dispara aqui -- gap 5x o típico
    assert regime_raw[6] == "R5"
    assert stress_triggers[6] == ["S6"]
    # entrada em R5 é imediata; saída exige stress_exit_confirmation_bars
    # (4) barras consecutivas sem stress -- só restam 3 barras após a
    # entrada, então o regime CONFIRMADO nunca sai de R5 até o fim da série
    assert regime[7:] == ["R5", "R5", "R5"]
    assert regime_raw[7:] == ["R1", "R1", "R1"]  # raw não tem histerese -- S6 não dispara mais
    assert not any(tradeable[:5])
    assert tradeable[5]
    assert not any(tradeable[6:])


def test_regime_symbol_tf_dir_layout_chaveado() -> None:
    from src.regime._paths import DATA_ROOT, regime_symbol_tf_dir

    path = regime_symbol_tf_dir("ETHUSDT", classifier.ENGINE_VERSION)
    assert path == DATA_ROOT / "regimes" / "ETHUSDT" / "15m" / classifier.ENGINE_VERSION


def test_regime_symbol_tf_dir_aceita_resolution_id() -> None:
    """Achado real (mapa de dívida técnica multi-ativo, 2026-08-22):
    `regime_symbol_tf_dir` nunca tinha suporte a `resolution_id`
    (dollar-bar), ao contrário de `labels_symbol_tf_dir` (AG-042).
    `resolution_id` vence sobre `tf` -- mesma guarda anti-colisão."""
    from src.regime._paths import DATA_ROOT, regime_symbol_tf_dir

    path = regime_symbol_tf_dir("ETHUSDT", classifier.ENGINE_VERSION, resolution_id="R3")
    assert path == DATA_ROOT / "regimes" / "ETHUSDT" / "R3" / classifier.ENGINE_VERSION


def test_regime_symbol_tf_dir_resolution_id_nao_reconhecido_levanta_valueerror() -> None:
    from src.regime._paths import regime_symbol_tf_dir

    with pytest.raises(ValueError, match="resolution_id"):
        regime_symbol_tf_dir("ETHUSDT", classifier.ENGINE_VERSION, resolution_id="R99")


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


def test_er_quantile_econ_quantile_respeita_min_common_history_bars_do_threshold() -> None:
    """AG-030 (T0.5, escopo ampliado): quando `er_quantile`/`econ_quantile`
    NÃO são injetados, `thresholds.min_common_history_bars` tem que chegar
    até a recomputação interna (`classify_regimes` linhas ~321-330) --
    mesma constante que já capa C07/D03f/E02f no Feature Engine."""
    n = 20
    rng = np.random.default_rng(3)
    er_48 = rng.uniform(0, 1, n)
    vol_pctile = rng.uniform(0, 1, n)
    cost_atr = rng.uniform(0.05, 0.3, n)
    stress_result = _empty_stress_result(n)
    cap = 12

    from src.features import support

    thresholds_com_cap = classifier.RegimeThresholds(
        er_cutoff_enter=_THRESHOLDS.er_cutoff_enter,
        er_cutoff_exit=_THRESHOLDS.er_cutoff_exit,
        vol_cutoff_enter=_THRESHOLDS.vol_cutoff_enter,
        vol_cutoff_exit=_THRESHOLDS.vol_cutoff_exit,
        min_warmup_bars=_THRESHOLDS.min_warmup_bars,
        confirmation_bars=_THRESHOLDS.confirmation_bars,
        stress_exit_confirmation_bars=_THRESHOLDS.stress_exit_confirmation_bars,
        min_common_history_bars=cap,
    )

    out = classifier.classify_regimes(
        _open_time(n), er_48, vol_pctile, cost_atr, stress_result, thresholds=thresholds_com_cap
    )
    expected_er_quantile = support.expanding_percentile_rank_strict(
        er_48, min_common_history_bars=cap
    )
    expected_econ_quantile = support.expanding_percentile_rank_strict(
        cost_atr, min_common_history_bars=cap
    )
    np.testing.assert_array_equal(out["er_quantile"].to_numpy(), expected_er_quantile)
    # econ_quantile não é coluna de saída direta -- confere via `econ_regime`,
    # que é função determinística de econ_quantile (`_economics_regime`).
    # `.to_list()` (não `.to_numpy()`) porque a coluna é `pl.Enum` -- forma
    # mais direta de comparar contra a lista Python de `expected_econ_regime`.
    expected_econ_regime = classifier._economics_regime(expected_econ_quantile)
    assert out["econ_regime"].to_list() == list(expected_econ_regime)
    # o cap tem que ter mudado ALGO em relação ao _THRESHOLDS sem cap (senão
    # o teste não prova nada) -- n=20 > cap=12, então a região [0, n-cap) fica
    # NaN em er_quantile só com o cap ativo.
    assert np.isnan(expected_er_quantile[: n - cap]).all()


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
        er_quantile, vol_pctile, stress_triggered, _THRESHOLDS, _open_time(n)
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
    regime, _ = _run_state_machine(
        er_quantile, vol_pctile, stress_triggered, _THRESHOLDS, _open_time(n)
    )
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
    regime, _ = _run_state_machine(
        er_quantile, vol_pctile, stress_triggered, _THRESHOLDS, _open_time(n)
    )
    post_warmup = regime[_THRESHOLDS.min_warmup_bars :]
    assert (post_warmup == "R2").all()  # nunca sai de HIGH_VOL dentro da zona morta


# ============================================================================
# D-04 (AG-180, decisão do Manager 2026-08-23) — piso de tempo real híbrido:
# confirmação exige `pending >= confirmation_bars` E `tempo_real_decorrido >=
# confirmation_min_real_ms` (o mais restritivo dos dois). Sob dollar-bar,
# barras podem fechar em segundos numa rajada de liquidez -- sem o piso, a
# histerese confirmaria rápido demais exatamente na hora de mais incerteza
# (medido, experiments/regime_hysteresis_bar_window_duration.json).
# ============================================================================


def test_confirmation_min_real_ms_deriva_de_confirmation_bars_menos_1() -> None:
    """`(confirmation_bars - 1) * step_ms("15m")`, não `confirmation_bars *
    step_ms(...)` -- N barras consecutivas cobrem N-1 intervalos de
    open_time a open_time, não N (ver docstring da property)."""
    assert _THRESHOLDS.confirmation_min_real_ms == 900_000  # (2-1) * 15min
    assert _THRESHOLDS.stress_exit_confirmation_min_real_ms == 2_700_000  # (4-1) * 15min


def test_confirmation_min_real_ms_nao_fica_negativo_com_confirmation_bars_1() -> None:
    th = dataclasses.replace(_THRESHOLDS, confirmation_bars=1, stress_exit_confirmation_bars=1)
    assert th.confirmation_min_real_ms == 0
    assert th.stress_exit_confirmation_min_real_ms == 0


def test_confirmation_min_real_ms_a_partir_de_constants_reais() -> None:
    from src.data.resample import step_ms

    th = classifier.RegimeThresholds.from_constants()
    assert th.confirmation_min_real_ms == (th.confirmation_bars - 1) * step_ms("15m")
    assert th.stress_exit_confirmation_min_real_ms == (
        th.stress_exit_confirmation_bars - 1
    ) * step_ms("15m")


def _burst_open_time(n: int, warmup: int, *, burst_step_ms: int) -> stress.TimeArray:
    """Grade de 15m até `warmup` (o que acontece antes não importa --
    histerese só começa a contar depois do warmup nestes testes), depois
    passo `burst_step_ms` constante -- simula dollar-bar fechando muito
    mais rápido (rajada) ou mais devagar (baixa liquidez) que 15m."""
    return np.array(
        [i * 900_000 for i in range(warmup)]
        + [warmup * 900_000 + k * burst_step_ms for k in range(n - warmup)],
        dtype=np.int64,
    )


def test_confirmacao_atrasada_pelo_piso_de_tempo_real_sob_burst_de_barras_rapidas() -> None:
    """Burst sintético de barras espaçadas 100s -- contagem de barra (2)
    seria satisfeita já na 2ª barra do burst, mas o piso de tempo real
    (900_000ms, `_THRESHOLDS.confirmation_bars=2`) só é atingido 9
    intervalos de 100_000ms depois do início do burst."""
    warmup = _THRESHOLDS.min_warmup_bars
    n = warmup + 12
    er_quantile = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.30)
    vol_pctile[warmup:] = 0.90  # HIGH_VOL a partir do fim do warmup
    stress_triggered = np.zeros(n, dtype=bool)
    open_time = _burst_open_time(n, warmup, burst_step_ms=100_000)

    regime, _ = _run_state_machine(
        er_quantile, vol_pctile, stress_triggered, _THRESHOLDS, open_time
    )
    post_warmup = regime[warmup:].tolist()
    assert post_warmup[0] == "R1"  # k=0: pending=1<2
    assert post_warmup[1] == "R1"  # k=1: pending=2>=2, mas elapsed=100_000<900_000
    assert post_warmup[8] == "R1"  # k=8: elapsed=800_000<900_000 -- ainda não confirma
    assert post_warmup[9] == "R2"  # k=9: elapsed=900_000>=900_000 -- confirma aqui
    assert all(r == "R2" for r in post_warmup[9:])


def test_confirmacao_nao_atrasa_alem_da_contagem_de_barra_sob_barras_lentas() -> None:
    """Sob barras mais ESPAÇADAS que 15m (dollar-bar em baixa liquidez), o
    piso de tempo real já está satisfeito muito antes da contagem de
    barra -- confirma exatamente quando `pending` atinge
    `confirmation_bars`, sem atraso adicional (mesmo comportamento do
    bar-count puro, preservado)."""
    warmup = _THRESHOLDS.min_warmup_bars
    n = warmup + 4
    er_quantile = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.30)
    vol_pctile[warmup:] = 0.90
    stress_triggered = np.zeros(n, dtype=bool)
    open_time = _burst_open_time(n, warmup, burst_step_ms=3_600_000)  # 1h -- mais devagar que 15m

    regime, _ = _run_state_machine(
        er_quantile, vol_pctile, stress_triggered, _THRESHOLDS, open_time
    )
    post_warmup = regime[warmup:].tolist()
    assert post_warmup[0] == "R1"  # pending=1<2
    assert post_warmup[1] == "R2"  # pending=2>=2 E elapsed=3_600_000>=900_000 -- sem atraso extra


def test_bit_exato_sob_grade_de_15m_com_a_logica_hibrida() -> None:
    """Prova de regressão direta: sob grade de 15m real (`_open_time`), a
    lógica híbrida confirma NO MESMO índice que a lógica antiga (só
    contagem de barra) confirmava -- o piso de tempo real nunca é o
    fator limitante quando a barra já tem duração fixa de 15m, por
    construção (ver docstring de `confirmation_min_real_ms`)."""
    n = 16
    er_quantile = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.30)
    start = 10
    vol_pctile[start:] = 0.90
    stress_triggered = np.zeros(n, dtype=bool)
    regime, _ = _run_state_machine(
        er_quantile, vol_pctile, stress_triggered, _THRESHOLDS, _open_time(n)
    )
    regimes = regime[_THRESHOLDS.min_warmup_bars :].tolist()
    rel_start = start - _THRESHOLDS.min_warmup_bars
    # idêntico ao teste original test_troca_persistente_por_confirmation_
    # bars_efetiva_mudanca -- mesma asserção, mesmo índice de confirmação
    assert regimes[rel_start] == "R1"
    assert regimes[rel_start + 1] == "R2"


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


def test_r5_saida_atrasada_pelo_piso_de_tempo_real_sob_burst_de_barras_rapidas() -> None:
    """D-04 (AG-180) -- mesmo racional dos testes de tendência/
    volatilidade, pro eixo de stress: sob burst de barras rápidas (100s),
    a saída de R5 exige TAMBÉM `stress_exit_confirmation_min_real_ms`
    decorrido (2_700_000ms, `_THRESHOLDS.stress_exit_confirmation_bars=4`),
    não só as 4 barras -- que sob o burst passariam em 400_000ms, bem
    antes do piso de tempo real."""
    warmup = _THRESHOLDS.min_warmup_bars
    n_burst = 35
    n = warmup + 1 + n_burst
    er_quantile = np.full(n, 0.30)
    vol_pctile = np.full(n, 0.30)
    stress_triggered = np.zeros(n, dtype=bool)
    trigger_idx = warmup
    stress_triggered[trigger_idx] = True

    burst_step_ms = 100_000
    open_time = np.array(
        [i * 900_000 for i in range(trigger_idx + 1)]
        + [(trigger_idx + 1) * 900_000 + k * burst_step_ms for k in range(n_burst)],
        dtype=np.int64,
    )
    regime, _ = _run_state_machine(
        er_quantile, vol_pctile, stress_triggered, _THRESHOLDS, open_time
    )
    regimes = regime.tolist()
    assert regimes[trigger_idx] == "R5"  # entrada imediata
    # bar-count(4) sozinho já teria saído aqui (k=3) -- não sai mais
    assert regimes[trigger_idx + 4] == "R5"
    assert regimes[trigger_idx + 1 + 26] == "R5"  # k=26: elapsed=2_600_000 < 2_700_000
    assert regimes[trigger_idx + 1 + 27] != "R5"  # k=27: elapsed=2_700_000 >= piso -- sai


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
