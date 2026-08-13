"""Testes de `src/analysis/gk_vs_wilder_econ_regime_shift.py` (AG-008,
shadow-mode). Eixo: `_econ_regime_shift_metrics` — o núcleo puro, sem IO
— está com a fiação certa (as funções reais de `group_e`/`support`/
`classifier` compostas na ordem certa) e o mascaramento/ARI fazem sentido.
Não reproduz a correção das primitivas (`expanding_percentile_rank_strict`,
`_economics_regime`) por hand-computation — isso já é coberto pelos testes
delas próprias; aqui o que importa é o COMPORTAMENTO da medição de
divergência em si."""

from __future__ import annotations

import numpy as np
import pytest

from src.analysis.gk_vs_wilder_econ_regime_shift import _econ_regime_shift_metrics

_MAKER_FEE = 0.0002
_TAKER_FEE = 0.0005


def test_series_identicas_dao_ari_1_e_zero_mudanca() -> None:
    """Wilder == GK (mesma série) -- o pipeline de econ_regime rodado duas
    vezes sobre o MESMO input tem que concordar perfeitamente consigo
    mesmo: ARI=1,0 exato (partição comparada a si mesma), fração mudada
    0,0, diferença relativa de nível 0,0. Não é uma medição sobre dado
    real -- é uma prova de que o pipeline não introduz ruído artificial
    quando os dois lados são idênticos."""
    n = 40
    rng = np.random.default_rng(7)
    atr_pct = rng.uniform(0.001, 0.02, size=n)

    metrics = _econ_regime_shift_metrics(
        "BTCUSDT", atr_pct, atr_pct.copy(), maker_fee=_MAKER_FEE, taker_fee=_TAKER_FEE
    )

    assert metrics.n_bars == n
    assert metrics.n_valid_both > 0, "fixture precisa gerar barras válidas pro teste valer algo"
    assert metrics.median_abs_relative_diff == 0.0
    assert metrics.fraction_econ_regime_changed == 0.0
    assert metrics.adjusted_rand_index == pytest.approx(1.0)
    assert metrics.counts_wilder == metrics.counts_gk


def test_series_divergentes_mudam_classificacao_e_derrubam_ari() -> None:
    """GK deliberadamente reordenado em relação a Wilder (não só
    escalado -- escalar por uma constante preserva o RANKING, que é o
    que decide o tercil, então não mudaria econ_regime nenhum). Espera-se
    fração de mudança > 0 e ARI < 1 -- não trava um valor exato (isso
    exigiria reproduzir `expanding_percentile_rank_strict` à mão, já
    coberto pelo teste da própria primitiva), só confirma que a medição
    REAGE a divergência real de ranking, não é uma função constante."""
    n = 60
    atr_pct_wilder = np.linspace(0.001, 0.02, n)
    # embaralha a METADE final da série -- muda o ranking relativo dessas
    # barras sem tocar a primeira metade (que ainda deve concordar em boa
    # parte, evitando um teste degenerado onde tudo muda por acidente)
    atr_pct_gk = atr_pct_wilder.copy()
    rng = np.random.default_rng(11)
    half = n // 2
    atr_pct_gk[half:] = rng.permutation(atr_pct_gk[half:])

    metrics = _econ_regime_shift_metrics(
        "ETHUSDT", atr_pct_wilder, atr_pct_gk, maker_fee=_MAKER_FEE, taker_fee=_TAKER_FEE
    )

    assert metrics.n_valid_both > 0
    assert metrics.fraction_econ_regime_changed > 0.0
    assert metrics.adjusted_rand_index < 1.0
    assert metrics.median_abs_relative_diff > 0.0


def test_tamanhos_diferentes_levanta_valueerror() -> None:
    with pytest.raises(ValueError, match="mesma série"):
        _econ_regime_shift_metrics(
            "BTCUSDT",
            np.array([0.01, 0.02]),
            np.array([0.01]),
            maker_fee=_MAKER_FEE,
            taker_fee=_TAKER_FEE,
        )


def test_tudo_nan_nao_quebra_e_devolve_nan() -> None:
    """Série inteira em warmup (todo `atr_pct` NaN) -- `n_valid_both`
    fica 0, e as métricas derivadas devolvem NaN em vez de levantar
    (ZeroDivisionError/erro de índice), mesmo racional de `EstimatorMetrics.
    qlike_mean`/`OperationalEffectMetrics` nos módulos irmãos: ausência de
    medição não é erro, é um resultado explícito."""
    n = 10
    all_nan = np.full(n, np.nan)

    metrics = _econ_regime_shift_metrics(
        "SOLUSDT", all_nan, all_nan.copy(), maker_fee=_MAKER_FEE, taker_fee=_TAKER_FEE
    )

    assert metrics.n_valid_both == 0
    assert np.isnan(metrics.median_abs_relative_diff)
    assert np.isnan(metrics.fraction_econ_regime_changed)
    assert np.isnan(metrics.adjusted_rand_index)
