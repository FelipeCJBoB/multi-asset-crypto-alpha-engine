"""PBO via CSCV (Combinatorially Symmetric Cross-Validation) — Bailey,
Borwein, López de Prado & Zhu (2017), "The Probability of Backtest
Overfitting", Journal of Computational Finance. Não existia neste repo
(`ADR-004 §6`: "❌ ausente"; `docs/prompts/execucao_adr004_fases_1_a_3_
2026-08-25.md` Passo 3: "não existe nada; escrever do zero").

**A pergunta que isto responde, diferente de tudo que já existe no
repo.** `resolve_joint_tau`/`resolve_joint_lambda` calibram um
threshold; `bootstrap_diff`/`dsr.sharpe_difference_block_bootstrap`
testam se DUAS séries diferem; DSR deflaciona UM Sharpe por `N_lifetime`
trials. Nenhum dos três responde: "se eu escolher o MELHOR de N
candidatos por performance IN-SAMPLE, esse candidato generaliza
OUT-OF-SAMPLE, ou a escolha foi overfitting ao ruído da amostra
específica?" — exatamente a pergunta por trás de toda seleção de
hiperparâmetro/feature-set/combinação já feita neste projeto (ADR-002,
ADR-003, o sweep de 15 combinações).

**Algoritmo (fiel ao paper, não uma variante).** Dada uma matriz de
retornos `T × N` (T períodos de tempo, N candidatos/configurações já
avaliadas sobre a MESMA linha do tempo): particiona os T períodos em `S`
blocos contíguos (`S` par); para cada uma das `C(S, S/2)` formas de
escolher metade dos blocos como IS (in-sample) e a outra metade como OOS
(out-of-sample): (1) mede o Sharpe de cada um dos N candidatos sobre o
IS; (2) `n* = argmax` do Sharpe IS — o "vencedor" que a seleção
real teria escolhido; (3) mede o Sharpe de TODOS os N candidatos sobre o
OOS; (4) `ω_c` = posto relativo de `n*` no ranking OOS, em `(0,1)`; (5)
`λ_c = ln(ω_c / (1-ω_c))` (logit). `PBO = P(λ_c ≤ 0)` — fração das
combinações em que o vencedor IS ficou ABAIXO da mediana OOS (a marca
central de overfitting: se a seleção IS carregasse informação real, o
vencedor deveria ficar consistentemente ACIMA da mediana OOS, não
espalhado 50/50).

**Núcleo puro (Idioma A)** — `compute_pbo` opera sobre uma matriz de
retornos já materializada, não sabe de onde os candidatos vieram (pode
ser Sharpe de hiperparâmetro, de combinação símbolo×resolução, de
qualquer eixo de seleção). `S=16` (default) é o valor que o próprio
paper usa como referência de equilíbrio entre cobertura combinatória
(`C(16,8)=12.870` combinações) e custo computacional -- `provenance:
LITERATURE`, não estipulado por conveniência deste repo."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

_DEFAULT_N_BLOCKS = 16  # noqa: magic-number -- Bailey et al. 2017, valor de referência do paper (C(16,8)=12870)
_MIN_N_CANDIDATES = 2  # noqa: magic-number -- PBO não tem sentido com 1 candidato só (não há "escolha")


def _period_sharpe_per_column(returns: FloatArray) -> FloatArray:
    """Sharpe por-período (não anualizado — mesma convenção de
    `src.validation.dsr`, escala per-trade/per-period na fórmula
    interna), uma coluna por candidato. `NaN` quando desvio-padrão é
    zero ou não há observações — nunca `0.0` inventado."""
    n = returns.shape[0]
    if n < 2:
        return np.full(returns.shape[1], np.nan)
    mean = np.mean(returns, axis=0)
    std = np.std(returns, axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = np.where(std > 0.0, mean / std, np.nan)
    return sharpe


def _relative_rank(values: FloatArray, index: int) -> float:
    """`ω_c` -- posto relativo de `values[index]` dentro de `values`,
    em `(0,1)` (nunca exatamente 0 ou 1 -- fórmula `rank/(N+1)` do
    paper, evita o logit divergir em `ln(0)`/`ln(inf)`). Empates
    recebem o posto MÉDIO (`scipy`-style), não o pior nem o melhor —
    não inventa uma ordem que o dado não tem."""
    n = values.shape[0]
    val = values[index]
    less = int(np.sum(values < val))
    equal = int(np.sum(values == val))
    # posto médio dentro do grupo de empates (1-indexado): less + (equal+1)/2
    rank = less + (equal + 1) / 2.0
    return rank / (n + 1)


@dataclass(frozen=True, slots=True)
class PBOResult:
    """`pbo` = `P(λ_c ≤ 0)` -- fração das combinações IS/OOS em que o
    vencedor in-sample ficou abaixo da mediana out-of-sample. `pbo=0.5`
    é o valor de "moeda honesta" (seleção IS não carrega informação
    nenhuma sobre OOS); `pbo` bem abaixo de 0.5 é o resultado saudável
    esperado de uma seleção real; `pbo` bem ACIMA de 0.5 (raro, mas
    possível) indicaria que o critério IS está sistematicamente
    ANTICORRELACIONADO com OOS -- achado tão preocupante quanto
    overfitting puro, nunca descartado como "impossível" a priori.
    `logits` preservado por inteiro para diagnóstico (distribuição, não
    só a média)."""

    pbo: float
    logits: tuple[float, ...]
    n_combinations: int
    n_blocks: int
    n_candidates: int
    n_periods: int
    mean_logit: float
    degradation_mean: float


def compute_pbo(returns_matrix: FloatArray, *, n_blocks: int = _DEFAULT_N_BLOCKS) -> PBOResult:
    """Núcleo puro (Idioma A). `returns_matrix` shape `(T, N)` — T
    períodos (mesma linha do tempo pros N candidatos, alinhados pelo
    CHAMADOR), N candidatos (`N >= 2`). `n_blocks` deve ser par e
    `<= T` (cada bloco precisa de pelo menos 1 período)."""
    if returns_matrix.ndim != 2:
        raise ValueError(f"compute_pbo: returns_matrix.ndim={returns_matrix.ndim}, esperado 2")
    n_periods, n_candidates = returns_matrix.shape
    if n_candidates < _MIN_N_CANDIDATES:
        raise ValueError(
            f"compute_pbo: n_candidates={n_candidates} < {_MIN_N_CANDIDATES} "
            "-- PBO exige pelo menos 2 candidatos pra medir uma escolha"
        )
    if n_blocks % 2 != 0:
        raise ValueError(f"compute_pbo: n_blocks={n_blocks} precisa ser par (IS/OOS = metade cada)")
    if n_blocks > n_periods:
        raise ValueError(
            f"compute_pbo: n_blocks={n_blocks} > n_periods={n_periods} -- bloco vazio"
        )

    block_idx = np.array_split(np.arange(n_periods), n_blocks)
    half = n_blocks // 2
    all_blocks = tuple(range(n_blocks))

    logits: list[float] = []
    is_sharpes_at_winner: list[float] = []
    oos_sharpes_at_winner: list[float] = []
    for is_blocks in itertools.combinations(all_blocks, half):
        oos_blocks = tuple(b for b in all_blocks if b not in is_blocks)
        is_rows = np.concatenate([block_idx[b] for b in is_blocks])
        oos_rows = np.concatenate([block_idx[b] for b in oos_blocks])

        is_sharpe = _period_sharpe_per_column(returns_matrix[is_rows])
        if not np.any(np.isfinite(is_sharpe)):
            continue  # combinação degenerada (todo candidato sem desvio no IS) -- pula, não inventa vencedor
        n_star = int(np.nanargmax(is_sharpe))

        oos_sharpe = _period_sharpe_per_column(returns_matrix[oos_rows])
        if not np.isfinite(oos_sharpe[n_star]) or not np.all(np.isfinite(oos_sharpe)):
            continue  # ranking OOS indefinido pra esta combinação -- pula, não inventa posto

        omega = _relative_rank(oos_sharpe, n_star)
        logits.append(math.log(omega / (1.0 - omega)))
        is_sharpes_at_winner.append(float(is_sharpe[n_star]))
        oos_sharpes_at_winner.append(float(oos_sharpe[n_star]))

    if not logits:
        return PBOResult(
            pbo=float("nan"),
            logits=(),
            n_combinations=0,
            n_blocks=n_blocks,
            n_candidates=n_candidates,
            n_periods=n_periods,
            mean_logit=float("nan"),
            degradation_mean=float("nan"),
        )

    logits_arr = np.asarray(logits, dtype=np.float64)
    pbo = float(np.mean(logits_arr <= 0.0))
    degradation = float(
        np.mean(np.asarray(is_sharpes_at_winner) - np.asarray(oos_sharpes_at_winner))
    )
    return PBOResult(
        pbo=pbo,
        logits=tuple(logits),
        n_combinations=len(logits),
        n_blocks=n_blocks,
        n_candidates=n_candidates,
        n_periods=n_periods,
        mean_logit=float(np.mean(logits_arr)),
        degradation_mean=degradation,
    )
