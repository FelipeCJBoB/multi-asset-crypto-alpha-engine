"""Max-T (Westfall-Young 1993) para o pico entre horizontes — primeira
correção de `AG-327`, escopo deliberadamente limitado.

**Por que existe.** `AG-327` achou que `pico_abs_t` (o máximo de `|t|` entre
6 horizontes, `ic_by_horizon.peak_horizon`) é tratado por `two_sided_p_
from_t` como se viesse de um único teste pré-especificado — um viés de
seleção conhecido (winner's curse/look-elsewhere/data snooping —
`docs/investigacao_falso_negativo_eixo1_2026-08-26.md` §3.1) que infla a
significância aparente de CADA feature antes mesmo do BH entre-feature
rodar. O precedente do projeto irmão (`Laplace_Quant_V17/pipeline/features/
leakage_gate.py`) resolve exatamente essa classe de problema com max-T por
permutação (Westfall & Young 1993): em vez de uma fórmula fechada sobre o
máximo, constrói-se a distribuição nula do PRÓPRIO máximo por reamostragem,
que embute a busca (e a correlação entre horizontes) na calibração, ao
invés de ignorá-la.

**Escopo desta primeira versão — deliberadamente limitado à dimensão
HORIZONTE, não à dimensão SÍMBOLO.** `AG-328` (número efetivo de testes
entre símbolos correlacionados) tem uma segunda dependência não resolvida:
tratar os 5 símbolos como i.i.d. no `binomial` é factualmente falso
(`eixo1_symbol_homogeneity.py`), mas a correção certa (pooling correto vs.
residualizar o fator de mercado comum, Fama-MacBeth/GLS) depende de RODAR o
teste de homogeneidade contra dado real primeiro — decidir isso aqui seria
estipular um número sem medir (B23). Este módulo resolve a dependência de
horizonte (bem definida, sem essa ambiguidade) e deixa a extensão conjunta
horizonte×símbolo como próximo passo explícito, condicionado ao resultado
real de `eixo1_symbol_homogeneity.run_symbol_homogeneity_report`.

**O método.** Nulo por deslocamento circular do RETORNO FUTURO (não da
feature) por um deslocamento aleatório `|shift| >= min_shift_bars` — evita
sobreposição trivial entre a janela observada e a deslocada, mesmo
princípio do `min_shift_sessions` de Westfall-Young/V17, adaptado para
índice de barra inteiro porque dollar bar não tem fronteira de sessão
natural (a série não é 288 barras/dia constante, mesma razão que levou o
V17 a abandonar o shift por dia de calendário). Para cada sorteio, recalcula
`max_h |Spearman(feature, retorno_deslocado_h)|` sobre os 6 horizontes — a
MESMA estatística de interesse, sob H0. `p_value = (#{shift : T_shift >=
T_observado} + 1) / (n_permutations + 1)` (Westfall-Young add-one).

**Custo.** `n_permutations` sorteios, cada um com 6 chamadas a `spearman_
ic` (via `max_abs_spearman_over_horizons`) sobre séries de ~150-170 mil
barras. Rodar sobre as 72×15 células custaria `72 × 15 × n_permutations`
chamadas — caro; recomenda-se rodar SELETIVAMENTE (features que já
mostraram algum sinal sob o pipeline atual), não em varredura cega, até o
custo real ser medido.

Núcleo puro (Idioma A): `max_abs_spearman_over_horizons`, `horizon_maxt_
p_value` (o segundo tem loop de permutação mas continua zero-IO — recebe
arrays já em memória). Não há casca de relatório persistido nesta primeira
versão -- ver docstring do módulo sobre o escopo.

Referências: `docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md`
§14.9-§14.10; `docs/investigacao_falso_negativo_eixo1_2026-08-26.md` §3.1,
§3.5, §8 (item 3 da ordem de correção recomendada);
`Laplace_Quant_V17/pipeline/features/leakage_gate.py` (precedente)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Final

import numpy as np
from numpy.typing import NDArray

from src.analysis.ic_by_horizon import spearman_ic

FloatArray = NDArray[np.float64]

#: Piso prático de sorteios para uma cauda superior estável (mesma ordem de
#: grandeza do mínimo declarado por `Laplace_Quant_V17/pipeline/features/
#: leakage_gate.py::_N_PERMUTATIONS_MIN`, mas mais baixo aqui porque este é
#: um diagnóstico por feature individual sob demanda, não um gate de
#: produção corrido em lote sobre as 72x15 células -- custo de rodar em
#: lote com 1000 permutações seria proibitivo sem medir primeiro. Subir
#: para produção real deve vir DEPOIS do diagnóstico de custo, não antes.
DEFAULT_N_PERMUTATIONS: Final[int] = 200

#: Deslocamento mínimo em barras para o nulo por circular-shift -- mesmo
#: princípio do `min_shift_sessions` de Westfall-Young/V17 (evita que o
#: deslocamento sorteado reproduza trivialmente a janela observada), mas em
#: unidade de BARRA (não sessão -- dollar bar não tem fronteira de sessão
#: natural). `ASSUMED`, não `DERIVED` -- calibração de instrumento, mesma
#: classe de `feature_temporal_stability_max_ratio` (`constants.yaml`).
DEFAULT_MIN_SHIFT_BARS: Final[int] = 96


class Eixo1MaxTError(RuntimeError):
    """Erro estrutural -- série curta demais para o deslocamento mínimo, ou
    entrada inválida."""


# ============================================================================
# Núcleo puro — zero IO (Idioma A)
# ============================================================================


def max_abs_spearman_over_horizons(
    feature: FloatArray, fwd_by_horizon: Mapping[int, FloatArray]
) -> float:
    """`max_h |Spearman(feature, fwd_by_horizon[h])|` -- a MESMA estatística
    que `pico_abs_t` busca encontrar, mas em escala de correlação (não `t`),
    porque o null por permutação dispensa a normalização por erro-padrão
    fechado: a variabilidade de amostragem já está embutida na própria
    distribuição empírica do máximo sob H0, não precisa ser aproximada por
    `1/sqrt(n_s-1)`.

    `NaN` se nenhum horizonte tiver `>= 2` pontos válidos (feature e retorno
    finitos simultaneamente).

    Raises:
        Eixo1MaxTError: `fwd` de algum horizonte tem shape diferente de
            `feature` (achado da revisão independente, 2026-08-26: sem essa
            checagem, `np.isfinite(feature) & np.isfinite(fwd)` falharia com
            um `ValueError` de broadcast do numpy, não uma mensagem legível
            com contexto)."""
    best = 0.0
    found = False
    for fwd in fwd_by_horizon.values():
        if fwd.shape != feature.shape:
            raise Eixo1MaxTError(
                f"shape de fwd_return ({fwd.shape}) != shape de feature "
                f"({feature.shape})"
            )
        valid = np.isfinite(feature) & np.isfinite(fwd)
        if int(valid.sum()) < 2:
            continue
        ic = spearman_ic(feature[valid], fwd[valid])
        if math.isfinite(ic):
            found = True
            best = max(best, abs(ic))
    return best if found else float("nan")


def horizon_maxt_p_value(
    feature: FloatArray,
    fwd_by_horizon: Mapping[int, FloatArray],
    *,
    n_permutations: int = DEFAULT_N_PERMUTATIONS,
    min_shift_bars: int = DEFAULT_MIN_SHIFT_BARS,
    seed: int,
) -> tuple[float, float]:
    """P-valor calibrado por permutação (max-T, Westfall-Young 1993) para
    "o pico de `|Spearman|` sobre os horizontes testados é distinguível de
    ruído?" -- substitui a normalização fechada de `pico_abs_t`/`two_sided_
    p_from_t` (`AG-327`: peak-hunting não corrigido) por um null empírico
    que embute a própria seleção do máximo.

    Nulo: desloca CICLICAMENTE cada série de retorno futuro (`np.roll`) por
    um deslocamento aleatório comum `|shift| >= min_shift_bars`, sorteado
    uniformemente em `[min_shift_bars, n - min_shift_bars]`. O MESMO
    deslocamento é aplicado a todos os horizontes num sorteio (preserva a
    estrutura de correlação ENTRE horizontes que a fórmula fechada ignora —
    é exatamente essa correlação, não modelada, que o max-T por permutação
    existe para incorporar).

    Retorna `(observado, p_value)`: `observado` = `max_abs_spearman_over_
    horizons` real; `p_value` = fração de sorteios do nulo com estatística
    `>= observado`, com a correção add-one de Westfall-Young
    (`(#{...} + 1) / (n_permutations + 1)` -- nunca zero, mesmo que nenhum
    sorteio iguale ou exceda o observado).

    Raises:
        Eixo1MaxTError: série curta demais para comportar o deslocamento
            mínimo dos dois lados (`n < 2 * min_shift_bars`).
    """
    observado = max_abs_spearman_over_horizons(feature, fwd_by_horizon)
    n = feature.shape[0]
    max_shift = n - min_shift_bars
    if max_shift < min_shift_bars:
        raise Eixo1MaxTError(
            f"série curta demais para o deslocamento mínimo: n={n}, "
            f"min_shift_bars={min_shift_bars} (precisa n >= 2*min_shift_bars)"
        )
    if not math.isfinite(observado):
        return observado, float("nan")

    rng = np.random.default_rng(seed)
    count_ge = 0
    for _ in range(n_permutations):
        shift = int(rng.integers(min_shift_bars, max_shift + 1))
        shifted_by_h = {h: np.roll(fwd, shift) for h, fwd in fwd_by_horizon.items()}
        stat = max_abs_spearman_over_horizons(feature, shifted_by_h)
        if math.isfinite(stat) and stat >= observado:
            count_ge += 1
    p_value = (count_ge + 1) / (n_permutations + 1)  # noqa: unguarded-ratio -- n_permutations>=0, denominador nunca <=0
    return observado, p_value
