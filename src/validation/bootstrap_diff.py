"""Bootstrap estacionário por blocos para diferença de duas séries
pareadas -- núcleo genérico (Idioma A, zero I/O, zero conhecimento de
trading) por trás do `ADR-004` Fase 0
(`docs/ADR-004_reformulacao_alvo_regra_decisao_e_inferencia_2026-08-25.md`
§5/§7), motivado por `AG-220`/`AG-220-ADDENDUM`: o critério de
permanência atual (`backtest_lite.permanence_count`) mostrou
`|delta| < sigma` nas 3 rodadas pareadas medidas em BTCUSDT/R1 -- ou
seja, o gate conta caminhos vencedores sem nunca perguntar se a
diferença é distinguível de ruído.

**Por que bootstrap em vez do teste fechado de Ledoit & Wolf (2008)
(ADR-004 §6 cita os dois).** A fórmula HAC de Ledoit-Wolf exige estimar
a variância de longo-prazo da diferença de Sharpe via um kernel de
Newey-West com bandwidth escolhida -- várias constantes internas onde um
erro de sinal ou de índice produz um veredito estatístico confiantemente
ERRADO, e este projeto nunca executa `.py` (protocolo de execução,
`CLAUDE.md`) -- não há como validar a fórmula empiricamente antes do
Manager rodar em produção. O bootstrap por blocos é o método que o
próprio `ADR-004 §5` já chama de "a saída moderna" para o problema
irmão (ESS): sem fórmula fechada pra errar o sinal, cobre dependência de
forma desconhecida por reamostragem, e é testável com dado SINTÉTICO
(gaussiano i.i.d., onde o IC deveria conter zero por construção) antes
de qualquer uso real -- ver `tests/unit/test_validation_bootstrap_diff.py`.

Referência: Politis & Romano (1994), "The Stationary Bootstrap", JASA
89(428) -- blocos de comprimento geométrico (média `block_length`),
reamostragem circular. Comprimento de bloco MEDIDO via função de
autocorrelação (mesmo espírito de Politis & White 2004, "Automatic
Block-Length Selection for the Dependent Bootstrap"), nunca estipulado
(B23)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from statsmodels.tsa.stattools import acf

FloatArray = NDArray[np.float64]

_MIN_OBS_BOOTSTRAP = 8  # noqa: magic-number -- abaixo disso ACF/bootstrap não têm base amostral defensável
_ACF_STOP_RUN = 2  # noqa: magic-number -- exige 2 lags consecutivos abaixo do limiar antes de aceitar "morreu" (1 lag isolado pode ser sorte)


def select_block_length(x: FloatArray, *, max_lag: int | None = None) -> int:
    """Comprimento de bloco MEDIDO pela função de autocorrelação de `x`
    -- menor lag `k >= 1` tal que `|acf(k)|` fica abaixo do limiar de
    significância `1.96/sqrt(n)` por `_ACF_STOP_RUN` lags consecutivos.
    Sem esse ponto dentro de `max_lag`, usa `max_lag` (série ainda
    dependente na maior escala medida -- conservador, nunca inventa um
    número menor que o que foi de fato observado). `max_lag` default
    `min(50, n // 4)` -- função de `n`, não constante de negócio."""
    n = x.shape[0]
    if n < _MIN_OBS_BOOTSTRAP:
        return 1
    eff_max_lag = max_lag if max_lag is not None else min(50, n // 4)
    eff_max_lag = max(1, eff_max_lag)
    acf_vals = acf(x, nlags=eff_max_lag, fft=True)
    bound = 1.96 / np.sqrt(n)
    run = 0
    for k in range(1, eff_max_lag + 1):
        if abs(acf_vals[k]) < bound:
            run += 1
            if run >= _ACF_STOP_RUN:
                return max(1, k - _ACF_STOP_RUN + 1)
        else:
            run = 0
    return eff_max_lag


def _stationary_bootstrap_indices(n: int, block_length: float, rng: np.random.Generator) -> NDArray[np.int64]:
    """Um resample do bootstrap estacionário (Politis & Romano 1994):
    blocos de comprimento geométrico (média `block_length`), início
    aleatório, wrap circular em `n` (série tratada como um ciclo -- a
    correção de borda padrão do método, evita viés de sub-amostrar as
    pontas)."""
    p = 1.0 / float(block_length)
    idx = np.empty(n, dtype=np.int64)
    pos = int(rng.integers(0, n))
    for i in range(n):
        idx[i] = pos
        pos = (pos + 1) % n
        if rng.random() < p:
            pos = int(rng.integers(0, n))
    return idx


@dataclass(frozen=True, slots=True)
class BootstrapDiffResult:
    """`significant` = IC exclui zero. `n_obs < _MIN_OBS_BOOTSTRAP`
    retorna tudo `NaN`/`significant=False` -- amostra pequena demais
    pra bootstrap ter base, nunca um resultado inventado."""

    n_obs: int
    block_length: int
    n_boot: int
    point_estimate: float
    ci_low: float
    ci_high: float
    confidence_level: float
    significant: bool


def stationary_bootstrap_ci(
    diff_series: FloatArray,
    *,
    n_boot: int,
    confidence_level: float,
    seed: int,
    block_length: int | None = None,
) -> BootstrapDiffResult:
    """Núcleo puro (Idioma A) -- `diff_series` já é a diferença pareada
    (`r1_t - r0_t`, mesmo `t`), a casca resolve o alinhamento temporal.
    `NaN` é removido antes (barra sem informação sobre a diferença nas
    duas séries não deveria influenciar nem o ponto nem o IC)."""
    x = diff_series[np.isfinite(diff_series)]
    n = int(x.shape[0])
    if n < _MIN_OBS_BOOTSTRAP:
        return BootstrapDiffResult(
            n_obs=n,
            block_length=0,
            n_boot=n_boot,
            point_estimate=float("nan"),
            ci_low=float("nan"),
            ci_high=float("nan"),
            confidence_level=confidence_level,
            significant=False,
        )
    bl = block_length if block_length is not None else select_block_length(x)
    bl = max(1, min(bl, max(1, n // 4)))
    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = _stationary_bootstrap_indices(n, bl, rng)
        boot_means[b] = float(np.mean(x[idx]))
    alpha = 1.0 - confidence_level
    lo, hi = np.quantile(boot_means, [alpha / 2.0, 1.0 - alpha / 2.0])
    point = float(np.mean(x))
    significant = bool(lo > 0.0 or hi < 0.0)
    return BootstrapDiffResult(
        n_obs=n,
        block_length=bl,
        n_boot=n_boot,
        point_estimate=point,
        ci_low=float(lo),
        ci_high=float(hi),
        confidence_level=confidence_level,
        significant=significant,
    )
