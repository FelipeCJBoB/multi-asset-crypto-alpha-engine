"""Testes de `src/regime/hmm_gap_check.py` -- triagem de gap de dado ANTES
de `build_hmm.build_hmm_regimes` (achado F3, cluster de fixes mecânicos
2026-08-21, ver docstring do módulo pra decisão de design completa: gap
ANÔMALO relativo à distribuição empírica de intervalos entre `close_time`
consecutivos, mediana+MAD/modified z-score, não grade fixa como
`check_grid_completeness`/`stress.s06_bar_gap`)."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.regime.hmm_gap_check import GapCheckResult, check_bars_gap_before_hmm

_STEP_MS = 60_000  # 1 minuto, valor arbitrário só pra granularidade legível do teste


def _bars_df_from_close_time(close_time_ms: np.ndarray) -> pl.DataFrame:
    return pl.DataFrame({"close_time": close_time_ms.astype(np.int64)})


# ============================================================================
# Série curta demais -- não computável, não "0 gaps"
# ============================================================================


@pytest.mark.parametrize("n_bars", [0, 1, 2])
def test_serie_curta_demais_nao_computavel(n_bars: int) -> None:
    close_time = np.arange(n_bars, dtype=np.int64) * _STEP_MS
    result = check_bars_gap_before_hmm(_bars_df_from_close_time(close_time))

    assert result.n_bars == n_bars
    assert result.computable is False
    assert result.n_gaps_anomalous == 0
    assert result.n_gaps_non_monotonic == 0
    assert result.anomalous_gap_close_time_ms == ()
    assert result.has_anomalous_gap is False


# ============================================================================
# Cadência perfeitamente regular -- MAD=0, nenhum gap anômalo
# ============================================================================


def test_cadencia_regular_nenhum_gap_anomalo() -> None:
    n_bars = 200
    close_time = np.arange(n_bars, dtype=np.int64) * _STEP_MS
    result = check_bars_gap_before_hmm(_bars_df_from_close_time(close_time))

    assert result.computable is True
    assert result.n_gaps_anomalous == 0
    assert result.n_gaps_non_monotonic == 0
    assert result.median_gap_ms == pytest.approx(float(_STEP_MS))
    assert result.mad_gap_ms == pytest.approx(0.0)
    assert result.max_gap_ms == pytest.approx(float(_STEP_MS))
    assert result.has_anomalous_gap is False


# ============================================================================
# Gap anômalo real -- MAD > 0 (caso "normal", jitter pequeno em torno da
# cadência típica) -- valores escolhidos pra dar mediana/MAD exatos e
# verificáveis à mão (ver comentário inline), não aproximados por RNG.
# ============================================================================


def test_gap_anomalo_detectado_com_mad_positivo() -> None:
    """99 gaps: 49x59900 (índices pares, exceto o 50) + 49x60100 (índices
    ímpares) + 1 outlier (`_STEP_MS*50`) no índice 50. Mediana/MAD
    calculados à mão (não aproximados): ordenando os 99 valores,
    mediana = valor na posição 49 (0-indexed) = 60100; desvio absoluto de
    cada grupo em relação a 60100 é {0 (49x, o grupo de 60100), 200 (49x,
    o grupo de 59900), 2939900 (1x, o outlier)} -- mediana desses desvios
    (posição 49) = 200 = MAD. `modified_z` do outlier =
    0.6745*2939900/200 ~ 9922 (>> 3.5, anômalo); `modified_z` do grupo de
    59900 (desvio 200) = 0.6745*200/200 = 0.6745 (< 3.5, NÃO anômalo --
    prova que jitter normal não dispara falso positivo)."""
    n_bars = 100
    gaps = np.empty(n_bars - 1, dtype=np.int64)
    for i in range(n_bars - 1):
        if i == 50:
            gaps[i] = _STEP_MS * 50  # outlier -- claramente fora da cadência típica
        elif i % 2 == 0:
            gaps[i] = _STEP_MS - 100
        else:
            gaps[i] = _STEP_MS + 100

    close_time = np.concatenate([[0], np.cumsum(gaps)]).astype(np.int64)
    result = check_bars_gap_before_hmm(_bars_df_from_close_time(close_time))

    assert result.computable is True
    assert result.n_gaps_non_monotonic == 0
    assert result.median_gap_ms == pytest.approx(float(_STEP_MS + 100))
    assert result.mad_gap_ms == pytest.approx(200.0)
    assert result.n_gaps_anomalous == 1
    assert result.has_anomalous_gap is True
    # `close_time` da barra que FECHA o gap (a barra de retomada, mesma
    # convenção de `stress.s06_bar_gap`) -- índice 50 do array de gaps
    # corresponde à barra 51 de `close_time`.
    assert result.anomalous_gap_close_time_ms == (int(close_time[51]),)
    assert result.max_gap_ms == pytest.approx(float(gaps[50]))


# ============================================================================
# Gap anômalo real -- MAD == 0 (cadência quase toda IDÊNTICA, achado real
# desta sessão: a 1a versão desta função escondia o outlier atrás de uma
# divisão indefinida quando a maioria dos gaps positivos é exatamente
# igual -- ver docstring do módulo, fallback pra desvio absoluto médio)
# ============================================================================


def test_gap_anomalo_detectado_com_cadencia_quase_toda_identica() -> None:
    """97 gaps EXATAMENTE `_STEP_MS`, 1 gap com pequeno desvio legítimo
    (`_STEP_MS + 300`) e 1 outlier (`_STEP_MS * 50`) -- MAD da série
    positiva é 0.0 (97/99 valores idênticos à mediana), então a função
    precisa cair no fallback de desvio absoluto médio pra não perder o
    outlier (a versão anterior, sem fallback, retornava `n_gaps_
    anomalous=0` aqui -- bug real, corrigido antes deste teste existir)."""
    n_bars = 100
    gaps = np.full(n_bars - 1, _STEP_MS, dtype=np.int64)
    gaps[10] = _STEP_MS + 300  # desvio pequeno, legítimo -- não deve disparar
    gaps[50] = _STEP_MS * 50  # outlier -- claramente fora da cadência típica

    close_time = np.concatenate([[0], np.cumsum(gaps)]).astype(np.int64)
    result = check_bars_gap_before_hmm(_bars_df_from_close_time(close_time))

    assert result.computable is True
    assert result.n_gaps_non_monotonic == 0
    assert result.median_gap_ms == pytest.approx(float(_STEP_MS))
    assert result.mad_gap_ms == pytest.approx(0.0)
    assert result.n_gaps_anomalous == 1, (
        "MAD=0 não pode fazer a checagem 'desistir' -- o outlier real "
        "precisa continuar detectável via fallback de desvio absoluto médio"
    )
    assert result.has_anomalous_gap is True
    assert result.anomalous_gap_close_time_ms == (int(close_time[51]),)
    assert result.max_gap_ms == pytest.approx(float(gaps[50]))


# ============================================================================
# close_time não-monotônico -- sinalizado incondicionalmente
# ============================================================================


def test_close_time_duplicado_conta_como_nao_monotonico() -> None:
    n_bars = 50
    close_time = np.arange(n_bars, dtype=np.int64) * _STEP_MS
    close_time[20] = close_time[19]  # timestamp duplicado -- gap == 0 nesse ponto

    result = check_bars_gap_before_hmm(_bars_df_from_close_time(close_time))

    assert result.computable is True
    assert result.n_gaps_non_monotonic == 1
    assert result.has_anomalous_gap is True
    assert int(close_time[20]) in result.anomalous_gap_close_time_ms


def test_close_time_fora_de_ordem_conta_como_nao_monotonico() -> None:
    n_bars = 50
    close_time = np.arange(n_bars, dtype=np.int64) * _STEP_MS
    close_time[30] = close_time[28]  # retrocede -- gap negativo em close_time[30]-close_time[29]

    result = check_bars_gap_before_hmm(_bars_df_from_close_time(close_time))

    assert result.n_gaps_non_monotonic == 1
    assert result.has_anomalous_gap is True


def test_todo_close_time_identico_nao_computavel_mas_sinaliza_nao_monotonico() -> None:
    """Caso extremo -- nenhum intervalo positivo (`positive_gaps.size == 0`):
    sem cadência típica pra comparar, `computable=False` (B23, não "0 gaps
    anômalos"), mas a não-monotonicidade em si continua sinalizada
    incondicionalmente (é um achado de integridade de dado, não uma
    ausência de sinal)."""
    n_bars = 10
    close_time = np.zeros(n_bars, dtype=np.int64)

    result = check_bars_gap_before_hmm(_bars_df_from_close_time(close_time))

    assert result.computable is False
    assert result.n_gaps_non_monotonic == n_bars - 1
    assert result.has_anomalous_gap is True
    assert result.median_gap_ms == pytest.approx(0.0)
    assert result.mad_gap_ms == pytest.approx(0.0)


# ============================================================================
# Precondição de schema -- ValueError, não KeyError silencioso
# ============================================================================


def test_bars_df_sem_close_time_levanta_value_error() -> None:
    bars_df = pl.DataFrame({"open_time": [0, 1, 2], "close": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="close_time"):
        check_bars_gap_before_hmm(bars_df)


# ============================================================================
# Determinismo -- puro, sem IO nem estado -- mesma entrada, mesmo resultado
# ============================================================================


def test_determinismo_mesma_entrada_mesmo_resultado() -> None:
    rng = np.random.default_rng(3)
    n_bars = 80
    gaps = np.full(n_bars - 1, _STEP_MS, dtype=np.int64) + rng.integers(-200, 200, size=n_bars - 1)
    gaps[40] = _STEP_MS * 30
    close_time = np.concatenate([[0], np.cumsum(gaps)]).astype(np.int64)
    bars_df = _bars_df_from_close_time(close_time)

    result_a = check_bars_gap_before_hmm(bars_df)
    result_b = check_bars_gap_before_hmm(bars_df)

    assert result_a == result_b
    assert isinstance(result_a, GapCheckResult)
