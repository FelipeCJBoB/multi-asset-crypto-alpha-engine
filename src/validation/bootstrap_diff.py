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
    pontas).

    **Vetorizado (AG-241-ADDENDUM/ADR-004 Fase 0, `docs/prompts/
    execucao_adr004_fases_1_a_3_2026-08-25.md` Passo 2, risco 2).** A
    versão original tinha um loop Python de `n` iterações -- sobre o
    universo completo de barras, com `n_boot` na casa do milhar, isso é
    ~1e8 iterações Python DENTRO do treino (achado real da revisão, não
    hipotético). Reescrito para sortear os comprimentos de bloco em
    LOTE (`rng.geometric`, vetorizado) em vez de um sorteio Bernoulli por
    posição -- o número de blocos amostrados é ~`n/block_length`, não
    `n`, e a montagem final via `np.repeat`/aritmética de índice também é
    vetorizada. Distribuição idêntica à versão original: comprimento de
    bloco ~ Geometric(1/block_length) suporte {1,2,...}, início uniforme
    em `[0,n)`, wrap circular -- só a IMPLEMENTAÇÃO mudou, não o método.
    Testado contra a versão original via propriedade estatística (ver
    `tests/unit/test_validation_bootstrap_diff.py`), não byte-a-byte
    (RNG consome em ordem diferente, resultado NÃO é bit-exato contra a
    versão anterior -- só contra si mesma, mesma seed)."""
    p = 1.0 / float(block_length)
    # sorteia blocos em lote suficiente para cobrir n com folga (2x o
    # número esperado de blocos + 1, nunca menos que 1) -- se a soma
    # ainda não cobrir n (caudas raras do geométrico), completa em outra
    # rodada; loop aqui é sobre ROD RODADAS de sorteio em lote, não sobre
    # posições -- tipicamente 1 iteração.
    lengths = np.empty(0, dtype=np.int64)
    total = 0
    while total < n:
        batch_size = max(1, int(np.ceil((n - total) / block_length)) * 2)
        batch = rng.geometric(p, size=batch_size).astype(np.int64)
        lengths = np.concatenate([lengths, batch])
        total = int(lengths.sum())
    cum = np.cumsum(lengths)
    n_blocks = int(np.searchsorted(cum, n) + 1)
    lengths = lengths[:n_blocks]
    cum = cum[:n_blocks]
    starts = rng.integers(0, n, size=n_blocks)
    block_id = np.repeat(np.arange(n_blocks), lengths)
    offsets = np.arange(int(lengths.sum())) - np.repeat(cum - lengths, lengths)
    idx = (starts[block_id] + offsets) % n
    return idx[:n].astype(np.int64)


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
