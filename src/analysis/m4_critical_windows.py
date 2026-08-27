"""M4 -- orquestrador de janelas históricas críticas x resoluções
(`PRD_V4_1.md` §3.2, Fase B do plano `wise-exploring-panda.md`,
`docs/m4_regime_plano_execucao.md`). Módulo COMPANHEIRO de
`src.analysis.m4_regime_comparison` (harness da Fase 3), não uma extensão
dele -- decisão de estrutura desta fase, motivo abaixo.

**Por que módulo novo, não extensão de `m4_regime_comparison.py`.**
`m4_regime_comparison.py` já tinha ~1650 linhas antes desta fase (agora
~1750, só com o parâmetro `resolution_id` novo). O que falta implementar
aqui -- 5 janelas críticas x 3 resoluções x até 5 símbolos, agregação por
mediana com detalhe por janela, isolamento de falha por célula (AG-019),
+ um relatório JSON próprio -- é um NOVO nível de orquestração (chama
`m4.run_regime_comparison_for_symbol` repetidamente, uma vez por célula),
não uma peça a mais dentro do núcleo puro/harness de símbolo único que já
existe lá. Mesma separação de responsabilidade já usada no resto do
projeto (`m2_bar_comparison.py` é o harness de 1 combinação, `m2_worker.py`
é quem itera/paraleliza -- aqui a divisão é harness-de-1-símbolo
(`m4_regime_comparison.py`) vs. orquestrador-de-grade (este módulo), não
exatamente a mesma fronteira do M2 mas o mesmo princípio: reusar o núcleo
sem inchar o arquivo que já o contém). REUSA `m4.run_regime_comparison_
for_symbol`/`m4.compare_regime_candidates_for_symbol` sem duplicar
NENHUMA lógica de fold/candidato -- este módulo só sabe iterar
(janela, resolução, símbolo) e agregar `m4.SymbolResult`/`m4.
CandidateResult` já prontos.

**As 5 janelas críticas -- datas REAIS, verificadas nesta sessão contra
`generate_anchored_walk_forward_splits` (não a aritmética ingênua do
plano original, que estava OFF por 1 fold -- achado já registrado em
`docs/m4_regime_plano_execucao.md`/instrução desta fase, RE-VERIFICADO
aqui sobre R1 **e** R2 **e** R3, todos os símbolos válidos de cada
janela, não só BTCUSDT/R1 como a verificação anterior).** Script ad-hoc
(não commitado, mesma disciplina dos scripts de calibração de
`m4_bocpd_hazard_lambda`/`m4_jump_model_penalty` em `constants.yaml`)
rodou `lake.query_dollar_bars(symbol, start, end, resolution_id=...)` +
`generate_anchored_walk_forward_splits(open_time_ms, initial_train_years=
1)` de verdade, pra CADA (janela, resolução, símbolo válido). Achado
confirmado, uniforme em toda a grade: a primeira barra real devolvida por
`query_dollar_bars` cai SEMPRE 1 dia antes do `start` pedido (efeito de
fronteira de dia civil, independente de resolução -- R1/R2/R3 têm
`first_bar` idêntico a R1 pra cada `(symbol, start)`, confirmado, não só
suposto), o que empurra a ancoragem trimestral 1 posição pra trás em
TODOS os casos -- o fold que cobre o mês-alvo é sempre o **fold 1**
(segundo fold produzido), nunca o fold 0, e isso vale igualmente pra
LUNA/FTX (BTC-only) e pros 5 símbolos das outras 3 janelas, em R1/R2/R3.
Ver `_TARGET_FOLD_CAVEAT` abaixo -- documentado no relatório, não
escondido (mesmo achado já citado na instrução desta fase, aqui
re-confirmado, não presumido de novo).

**CORREÇÃO, 2026-08-18 (2 auditorias céticas independentes, reprodução
real de `generate_anchored_walk_forward_splits` sobre dado real -- ver
`_TARGET_FOLD_CAVEAT` abaixo e `audit/architecture_gaps_log.yaml`
AG-084/AG-087): o parágrafo acima e a tabela abaixo estão ERRADOS.**
Cada janela produz EXATAMENTE 2 folds de teste, não 3 -- o fold-alvo é
o **fold 0** (primeiro), não o fold 1. Não muda nenhum número agregado
(agregação é agnóstica a índice de fold), só a narrativa de cobertura.
Texto original preservado abaixo como registro histórico do que foi
medido na Fase B, não corrigido numericamente linha a linha -- ler
`_TARGET_FOLD_CAVEAT` como a versão de referência.

| janela | evento-alvo | `start`/`end` | símbolos | fold que cobre o alvo |
|---|---|---|---|---|
| LUNA | 2022-05, colapso UST/LUNA | `2021-04-01`/`2022-07-01` | BTCUSDT | fold 1 (2022Q2) |
| FTX | 2022-11, cascata de crédito | `2021-10-01`/`2023-01-01` | BTCUSDT | fold 1 (2022Q4) |
| CRYPTO_WINTER | 2023-06, faixa lateral | `2022-04-01`/`2023-07-01` | 5/5 | fold 1 (2023Q2) |
| ETF_HALVING | 2024-03, ATH BTC | `2023-01-01`/`2024-04-01` | 5/5 | fold 1 (2024Q1) |
| RECENTE | regime atual (sem evento) | `2025-04-01`/`2026-08-07` | 5/5 | fold1+2 (Q2,Q3 parcial) |

Cada janela produz 3 folds de walk-forward (não só o fold-alvo) --
`fold0` (trimestre anterior ao alvo, treino puro do ponto de vista do
evento mas ainda um fold de TESTE do walk-forward) e um `fold2` quase
vazio (poucas dezenas de barras, resto do trimestre seguinte cortado pelo
`end` da janela) em TODAS as janelas exceto RECENTE -- mesmo achado já
documentado na instrução desta fase ("mais dado, não menos, então
estatisticamente aceitável"): o harness agrega TODOS os folds de teste da
janela (via `m4.run_regime_comparison_for_symbol`, que não recorta só o
fold-alvo), não só o mês exato do evento.

**RECENTE -- escolha nova desta fase, verificada, não copiada do plano
original (que só listava `"a confirmar"`).** `start="2025-04-01"`
(mesmo efeito de fronteira de dia -- primeira barra real em
`2025-03-31`, Q1 2025) produz 3 folds de teste NÃO-degenerados
(`2026Q1`/`2026Q2`/`2026Q3` parcial até `END_DATE="2026-08-07"`,
confirmado sobre R1/R2/R3 x 5 símbolos: o menor fold real medido tem 362
barras -- BNBUSDT R3 (reverificado 2026-08-18) -- ordens de grandeza maior que o `fold2` quase
vazio (dezenas de barras) das outras 4 janelas) -- diferente das 4
janelas históricas, aqui NÃO há 1 evento único a mirar, então os 3 folds
representam genuinamente "o regime mais recente coberto pelo backfill",
não uma tentativa de acertar um mês específico.

**Agregação -- mediana de medianas, não pooling direto (decisão desta
fase, não determinada pelo plano/Manager -- documentada aqui como
julgamento de engenharia, não escondida).** Pra cada (`classifier_id`,
`resolution_id`): passo 1, mediana das métricas ENTRE OS SÍMBOLOS válidos
de uma mesma janela (`WindowCandidateSummary`) -- símbolo não multiplica
trial em NENHUM lugar do M4 (mesma convenção de `AG-039`, repetida em
`compare_regime_candidates_for_symbol`), então tratar 5 pontos de LUNA...
não, tratar os 5 símbolos de CRYPTO_WINTER/ETF_HALVING/RECENTE como 5
observações independentes que multiplicam o peso da janela seria
inconsistente com essa convenção; passo 2, mediana das medianas de janela
(`AggregatedCandidateResult`) -- garante que LUNA/FTX (1 símbolo cada)
pesem o MESMO que CRYPTO_WINTER/ETF_HALVING/RECENTE (5 símbolos cada) no
agregado final, em vez de serem afogadas 5:1 num pooling direto de todas
as células (janela, símbolo). Mediana (não média) em AMBOS os níveis --
mesma escolha do plano ("mais robusta a 1 janela degenerada"), estendida
ao nível de símbolo pelo mesmo motivo (1 símbolo degenerado numa janela
de 5 não deveria dominar a mediana daquela janela). `NaN` explícito (não
0/erro) quando não sobra nenhuma observação finita em qualquer nível --
mesma disciplina de `_anova_or_degenerate`/`_persistence_or_degenerate`
em `m4_regime_comparison.py`. **Detalhe NUNCA escondido**: `Aggregated
CandidateResult.per_window` carrega os `WindowCandidateSummary` de TODAS
as 5 janelas (inclusive as com 0 símbolos OK), e cada `WindowCandidate
Summary.per_symbol` carrega o `SymbolCandidateDetail` de cada símbolo
individual -- quem só lê o agregado final vê 1 número, mas o relatório
persistido (`run_and_save_critical_windows_report`) sempre inclui os 2
níveis de detalhe, serializados via `dataclasses.asdict` (nenhum campo
descartado na serialização).

**AG-019 (1 falha isolada não derruba o resto) -- 2 camadas de defesa.**
`_run_one_cell` captura QUALQUER exceção de `m4.run_regime_comparison_
for_symbol` (dado ausente, erro de IO, candidato degenerado que escapou
de `_anova_or_degenerate` por algum caminho não previsto -- isso não
deveria acontecer, mas o harness não aposta nisso) e devolve um `CellOutcome` com
`error` preenchido, nunca propaga -- tanto no caminho sequencial quanto
dentro de cada worker do `ProcessPoolExecutor`. Uma 2ª camada (`future.
result()` dentro de `try/except` em `run_critical_windows_comparison`)
cobre o caso ainda mais raro de o PRÓPRIO processo filho morrer (OOM/
segfault -- `BrokenProcessPool`), que `_run_one_cell` não pode capturar
porque nunca retorna nesse caso -- mesmo padrão de defesa em 2 camadas já
usado em `m4_regime_comparison.run_and_save_m4_report`.

**Paralelismo -- `ProcessPoolExecutor` por célula (janela, símbolo),
1 resolução por vez (não aninha pool dentro de pool).** `resolution_id`
já é o eixo mais caro (equivalente a um trial inteiro novo, decisão do
Manager 2026-08-18) -- `run_and_save_critical_windows_report` itera as
3 resoluções SEQUENCIALMENTE, cada uma abrindo seu próprio
`ProcessPoolExecutor` (fecha antes de abrir o próximo) via `run_critical_
windows_comparison(resolution_id, ...)`. Dentro de 1 resolução, as
células (janela, símbolo) -- até 17 por resolução (1+1+5+5+5) -- rodam em
paralelo, mesmo padrão de `spawn` explícito + throttle BLAS/JAX de
`m4_regime_comparison.py` (reusado por importação, ver nota de import
abaixo -- este módulo não redeclara `os.environ`). `max_workers=1` força
caminho SEQUENCIAL (mesma função `_run_one_cell`, só sem `ProcessPool
Executor`) -- usado pelos testes (evita multiprocessing real em CI/
unit) e disponível pra debug manual.

**Nota de import -- por que `from src.analysis import m4_regime_
comparison as m4` precisa ser a PRIMEIRA importação deste arquivo.**
`m4_regime_comparison.py` seta `os.environ.setdefault(...)` (throttle
BLAS/polars/`XLA_FLAGS`) ANTES de importar `numpy`/`jax`/`dynamax` --
crítico pra rodar sob `ProcessPoolExecutor(mp_context="spawn")` no
Windows, onde cada processo filho reimporta o módulo do zero (ver
docstring de `m4_regime_comparison.py`, seção "Throttle de threads").
Este módulo REUSA esse efeito colateral em vez de duplicar o bloco
`os.environ` -- funciona porque importar `m4_regime_comparison` executa
o corpo do módulo inteiro (env vars primeiro, depois os imports pesados)
antes de qualquer `numpy`/`jax` deste arquivo ser resolvido -- mas SÓ se
a importação de `m4_regime_comparison` vier ANTES de qualquer outra
importação que pudesse carregar `numpy`/`jax` primeiro. Por isso ela é a
primeira linha de import abaixo, antes até de `numpy`.

**`run_and_save_critical_windows_report` NÃO É CHAMADA POR ESTE
MÓDULO** -- mesma disciplina de `m4_regime_comparison.run_and_save_m4_
report`: hiperparâmetros de candidato sem default, `if __name__ ==
"__main__":` levanta `SystemExit` em vez de rodar a execução real (18
trials, Fase D do plano, autorização separada do Manager)."""

from __future__ import annotations

# isort: off
# Ver docstring do módulo, seção "Nota de import" -- precisa vir ANTES de
# numpy/orjson/structlog/etc., porque importar m4_regime_comparison é o
# que efetivamente aplica o throttle de threads BLAS/JAX (os.environ.
# setdefault lá, executado antes dos imports pesados internos dele).
# `# isort: off`/`# isort: on` (compatibilidade isort que o ruff respeita)
# -- preserva esta ordem intencional, não um lapso de organização.
from src.analysis import m4_regime_comparison as m4
# isort: on

import datetime as dt
import io
import multiprocessing
import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog

from src.analysis import m6_common_factor_hypothesis as m6
from src.analysis._pool_heartbeat import iter_completed_with_heartbeat
from src.core.provenance import report_provenance
from src.data import lake
from src.data._constants import load_constant as load_data_constant
from src.features._constants import load_constant as load_feature_constant
from src.labels.triple_barrier import LabelConfig
from src.regime.bocpd import run_bocpd, segments_to_canonical_states
from src.regime.build import build_regimes
from src.regime.canonicalization import canonicalize_states
from src.risk._constants import load_constant as load_risk_constant
from src.validation.cpcv import load_labels_v1
from src.validation.regime_utility import (
    adjusted_rand,
    identify_stress_state_by_volatility,
    occupancy_metrics,
    transition_failure_rate,
)

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "m4_critical_windows_report.json"

RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")


# ============================================================================
# As 5 janelas críticas -- constante módulo-level (ver docstring do
# módulo pra proveniência de cada start/end/símbolos)
# ============================================================================


@dataclass(frozen=True, slots=True)
class CriticalWindow:
    """`symbols`: só BTCUSDT pra LUNA/FTX (decisão do Manager, 2026-08-18
    -- os 4 alts só têm backfill desde 2021-12-01, sem runway suficiente
    pra `initial_train_years=1` de treino antes desses 2 eventos). `note`
    carrega o achado real medido nesta sessão sobre qual fold cobre o
    mês-alvo (ver docstring do módulo) -- texto, não recalculado em
    runtime (a verificação real já foi feita; recalcular a cada import
    seria IO desnecessário)."""

    name: str
    event: str
    start: str
    end: str
    symbols: tuple[str, ...]
    note: str


CRITICAL_WINDOWS: Final[tuple[CriticalWindow, ...]] = (
    CriticalWindow(
        name="LUNA",
        event="2022-05, colapso UST/LUNA",
        start="2021-04-01",
        end="2022-07-01",
        symbols=("BTCUSDT",),
        note=(
            "fold 1 (test 2022-04-01..2022-07-01, 2022Q2) cobre maio inteiro -- "
            "verificado 2026-08-18 sobre R1/R2/R3 (generate_anchored_walk_forward_splits "
            "real, initial_train_years=1). fold0=2022Q1 (trimestre anterior), fold2=2022Q3 "
            "quase vazio (~130 barras R1 / ~31 R3, resto cortado pelo end da janela)."
        ),
    ),
    CriticalWindow(
        name="FTX",
        event="2022-11, cascata de crédito FTX/Alameda",
        start="2021-10-01",
        end="2023-01-01",
        symbols=("BTCUSDT",),
        note=(
            "fold 1 (test 2022-10-01..2023-01-01, 2022Q4) cobre novembro inteiro -- "
            "verificado 2026-08-18 sobre R1/R2/R3. fold0=2022Q3, fold2=2023Q1 quase vazio "
            "(~12 barras R1 / ~2 R3)."
        ),
    ),
    CriticalWindow(
        name="CRYPTO_WINTER",
        event="2023-06, faixa lateral prolongada",
        start="2022-04-01",
        end="2023-07-01",
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"),
        note=(
            "fold 1 (test 2023-04-01..2023-07-01, 2023Q2) cobre junho inteiro -- "
            "verificado 2026-08-18 sobre R1/R2/R3 x 5 símbolos. fold0=2023Q1, fold2=2023Q3 "
            "quase vazio (~29 barras BTCUSDT R1 / ~5 SOLUSDT R3)."
        ),
    ),
    CriticalWindow(
        name="ETF_HALVING",
        event="2024-03, ATH BTC pré-halving + aprovação ETF spot",
        start="2023-01-01",
        end="2024-04-01",
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"),
        note=(
            "fold 1 (test 2024-01-01..2024-04-01, 2024Q1) cobre março inteiro -- "
            "verificado 2026-08-18 sobre R1/R2/R3 x 5 símbolos. fold0=2023Q4, fold2=2024Q2 "
            "quase vazio (~143 barras BTCUSDT R1 / ~16 XRPUSDT R3)."
        ),
    ),
    CriticalWindow(
        name="RECENTE",
        event="regime atual, sem evento único -- cobertura mais recente do backfill",
        start="2025-04-01",
        end=m4.END_DATE,
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"),
        note=(
            "3 folds de teste NÃO-degenerados (2026Q1/2026Q2/2026Q3-parcial-até-08-07) -- "
            "verificado 2026-08-18 sobre R1/R2/R3 x 5 símbolos, menor fold real medido = "
            "362 barras (BNBUSDT R3, 2026Q3) -- ordens de grandeza maior que o fold2 quase "
            "vazio das outras 4 janelas. Sem mês-alvo único: os 3 folds representam o "
            "regime mais recente coberto pelo backfill, não uma tentativa de acertar 1 "
            "evento. end=m4.END_DATE ('2026-08-07', cobertura real confirmada) -- não há "
            "dado além disso pra processar."
        ),
    ),
)


# ============================================================================
# Dataclasses de detalhe/agregação -- ver docstring do módulo, seção
# "Agregação -- mediana de medianas"
# ============================================================================


@dataclass(frozen=True, slots=True)
class SymbolCandidateDetail:
    """1 (janela, resolução, símbolo, candidato) -- espelha os campos de
    `m4.CandidateResult` que entram na agregação (omite `separation`/
    `orthogonality`/`persistence` como sub-dataclasses aninhadas -- achata
    pra `omega_squared`/`median_duration_bars`/`switch_rate` direto, único
    subconjunto usado pela mediana).

    `is_saturated` (AG-087, achado real: Jump Model colapsa a 1 estado
    único em ~25-29% das células com `jump_penalty` calibrado numa única
    fatia de BTC) -- `True` quando `persistence_switch_rate == 0.0`
    (nenhuma troca de estado na janela OOS inteira, célula degenerada,
    não "regime persistente genuíno"). Aplicável a QUALQUER candidato
    (não só Jump Model) -- transparência genérica, não um caso especial
    hardcoded. NUNCA excluída da mediana (mudar a fórmula de agregação
    não fazia parte do escopo desta correção, ver AG-087 resolution) --
    só torna a taxa de saturação visível, em vez de escondida atrás de
    um número agregado plausível."""

    symbol: str
    n_states: int
    separation_omega_squared: float
    orthogonality_omega_squared: float
    persistence_median_duration_bars: float
    persistence_switch_rate: float
    fold_stability_adjusted_rand_mean: float
    fold_stability_adjusted_rand_min: float
    fold_stability_by_construction: bool
    n_oos_obs: int
    n_folds_evaluated: int
    is_saturated: bool


@dataclass(frozen=True, slots=True)
class WindowCandidateSummary:
    """1 (janela, resolução, candidato) -- mediana ENTRE OS SÍMBOLOS
    válidos daquela janela (passo 1 da agregação de 2 níveis, ver
    docstring do módulo). `n_symbols_ok < n_symbols_requested` é o
    sintoma de AG-019 em ação (1+ símbolo falhou/foi pulado nesta janela,
    sem derrubar os outros) -- nunca um crash. `per_symbol` carrega o
    detalhe INDIVIDUAL de cada símbolo OK -- nunca escondido atrás da
    mediana. `n_symbols_saturated` (AG-087) -- quantos dos `n_symbols_ok`
    tinham `is_saturated=True`."""

    window_name: str
    event: str
    n_symbols_requested: int
    n_symbols_ok: int
    n_symbols_saturated: int
    separation_omega_squared: float
    orthogonality_omega_squared: float
    persistence_median_duration_bars: float
    persistence_switch_rate: float
    fold_stability_adjusted_rand_mean: float
    n_oos_obs_total: int
    per_symbol: tuple[SymbolCandidateDetail, ...]


@dataclass(frozen=True, slots=True)
class AggregatedCandidateResult:
    """1 (candidato, resolução) -- mediana ENTRE AS 5 JANELAS (passo 2 da
    agregação, cada janela já reduzida a 1 número pelo passo 1) + detalhe
    completo por janela em `per_window` (SEMPRE as 5, inclusive as com
    `n_symbols_ok=0` -- nunca filtradas silenciosamente). `n_states`
    tomado do primeiro `SymbolCandidateDetail` que existir em qualquer
    janela (deveria ser constante entre janelas/símbolos pro MESMO
    `classifier_id` -- não um valor por janela).

    `n_cells_saturated_total`/`saturation_rate` (AG-087) -- soma/fração
    de `SymbolCandidateDetail.is_saturated=True` entre TODAS as células
    OK deste candidato/resolução (não só as 5 janelas -- soma direta
    sobre `n_symbols_ok` de cada janela). `persistence_median_duration_
    bars_median`/`persistence_switch_rate_median` continuam calculados
    IGUAL a antes (mediana sem filtrar saturadas) -- este campo é
    transparência adicional, não uma correção da fórmula de agregação."""

    classifier_id: str
    resolution_id: str
    n_states: int
    n_windows_requested: int
    n_windows_ok: int
    n_cells_saturated_total: int
    saturation_rate: float
    separation_omega_squared_median: float
    orthogonality_omega_squared_median: float
    persistence_median_duration_bars_median: float
    persistence_switch_rate_median: float
    fold_stability_adjusted_rand_mean_median: float
    n_oos_obs_total: int
    per_window: tuple[WindowCandidateSummary, ...]


@dataclass(frozen=True, slots=True)
class Q3AssetDetail:
    """Q3 (Terceira via), 1 ativo não-BTC dentro de 1 janela/resolução/
    candidato: Rand ajustado entre a classificação PRÓPRIA do ativo e a
    classificação DERIVADA de BTC via as-of join causal (mesma semântica
    de `m4.Q3AssetResult`/`m4._asof_join_btc_labels` -- backward, nunca
    timestamp futuro). `adjusted_rand` é `NaN` (não um valor inventado)
    se `n_bars_compared` for pequeno demais pra ter sentido estatístico
    (mesmo limiar de `m4._Q3_MIN_BARS_COMPARED`)."""

    symbol: str
    n_bars_compared: int
    adjusted_rand: float


@dataclass(frozen=True, slots=True)
class Q3WindowSummary:
    """Q3, 1 (janela, resolução, candidato) -- mediana ENTRE OS ATIVOS
    não-BTC dessa janela (passo 1, mesmo padrão de `WindowCandidateSummary`).
    Só janelas com >1 símbolo (`len(window.symbols) > 1`) são elegíveis --
    LUNA/FTX (só BTCUSDT) não aparecem aqui, ver `Q3AggregatedResult.
    n_windows_applicable` vs. `n_windows_requested_total`."""

    window_name: str
    event: str
    n_assets_requested: int
    n_assets_ok: int
    adjusted_rand_median: float
    per_asset: tuple[Q3AssetDetail, ...]


@dataclass(frozen=True, slots=True)
class Q3AggregatedResult:
    """Q3, 1 (candidato, resolução) -- mediana ENTRE AS JANELAS ELEGÍVEIS
    (passo 2, mesmo padrão de `AggregatedCandidateResult`). Rand ALTO ->
    BTC como fator comum de regime basta pra esse candidato; Rand baixo
    -> regime idiossincrático por ativo (ou a correlação BTC-ativo em si
    varia por regime -- os 2 cenários dão o mesmo sintoma, caveat já
    citado em `m4.Q3AssetResult`).

    **Custo: ZERO fits adicionais.** Ao contrário de `m4.run_q3_common_
    factor_regime` (que rechama `run_regime_comparison_for_symbol` por
    ativo, refazendo fits), esta agregação reusa os `RawLabels` que
    `_run_one_cell` já coleta pra TODOS os símbolos de toda janela (pedidos
    via `return_raw_labels=True`, custo desprezível -- ver docstring de
    `m4.compare_regime_candidates_for_symbol`, "só fatiamento de array já
    calculado, nunca refit"). Rodar Q3 não exige nenhuma célula nova nem
    `ProcessPoolExecutor` adicional -- só espera os 6 candidatos-trial
    já rodarem (baseline + HMM k=2/3/4 + Jump Model + BOCPD) e faz o
    as-of join sobre o que já foi calculado."""

    classifier_id: str
    resolution_id: str
    n_windows_requested_total: int
    n_windows_applicable: int
    n_windows_ok: int
    adjusted_rand_median: float
    per_window: tuple[Q3WindowSummary, ...]


@dataclass(frozen=True, slots=True)
class HeterogeneitySymbolDetail:
    """G-C1-2 revisado (decisão do Manager, 2026-08-18, após 2 auditorias
    céticas convergirem na mesma proposta -- AG-084/AG-087, PRD_V4_1.md
    §3.2): Cochran's Q/I² de `edge_bruto_atr` (DerSimonian & Laird 1986,
    MESMO instrumento que `m6_common_factor_hypothesis` já usa e validou
    -- reuso direto de `m6.stratum_metrics`/`m6.cochrans_q_heterogeneity`,
    zero fórmula nova), estratos = buckets de regime de 1 candidato
    dentro do período de 1 janela crítica -- substitui "separação a 1
    barra via ANOVA de Welch" como eixo primário (rebaixado a diagnóstico
    secundário, não removido).

    `n_buckets=0`/`df=-1`: nenhuma barra de label caiu dentro da janela
    (sem overlap entre `labels.parquet` e o período) -- `NaN` explícito,
    nunca inventado. `n_buckets=1`/`df=0`: só 1 bucket apareceu (ex.
    Jump Model saturado, AG-087) -- **corrigido 2026-08-19**:
    `i_squared_pct` (e `q_statistic`/`p_value`) vem `NaN` de
    `m6.cochrans_q_heterogeneity` (não mais `0.0` "por convenção" -- essa
    convenção nunca foi de fato garantida em ponto flutuante, achado real
    de auditoria, ver docstring de `cochrans_q_heterogeneity`). `NaN`
    aqui é o correto: `Q`/`I²` são indefinidos com 1 único grupo, não
    "medidos como zero".

    **`p_value_permutation`/`n_episodes`/`n_permutations_*` -- AG-092,
    2026-08-19.** `p_value` (acima) vem do `chi²(k-1)` assintótico de
    `cochrans_q_heterogeneity` -- ASSUME estratos independentes, premissa
    violada aqui: trades do MESMO bucket formam episódios contíguos de
    regime persistente (autocorrelacionados), então essa `p_value` NÃO É
    CONFIÁVEL como teste de significância (`I²` satura 70-99% quase
    universalmente no relatório real, padrão consistente com inflação
    por SE subestimada, não heterogeneidade genuína tão extrema) -- ver
    `audit/architecture_gaps_log.yaml::AG-092`. `p_value_permutation` é
    o substituto válido: p-valor EMPÍRICO de um teste de permutação em
    BLOCO por episódio de regime (`m6.permutation_heterogeneity_test`),
    que preserva a autocorrelação intra-episódio em toda permutação da
    distribuição nula -- comparação `Q_observado` vs. essa distribuição
    cancela o viés de SE subestimada sem precisar corrigi-la. `n_episodes
    < 2` (não há episódios suficientes pra permutar, mesmo caso
    degenerado de `n_buckets<2`) -> `NaN` explícito. `n_permutations_
    valid <= n_permutations_requested` -- permutações que degeneram
    (bucket pseudo-atribuído com `SE=0`) são descartadas, não contam pro
    denominador do p-valor, nunca um crash."""

    symbol: str
    side: int
    n_buckets: int
    n_obs_total: int
    pooled_edge_bruto_atr: float
    q_statistic: float
    df: int
    p_value: float
    i_squared_pct: float
    p_value_permutation: float
    n_episodes: int
    n_permutations_requested: int
    n_permutations_valid: int


@dataclass(frozen=True, slots=True)
class HeterogeneityWindowSummary:
    """1 (janela, resolução, candidato, lado) -- mediana de `i_squared_pct`
    ENTRE OS SÍMBOLOS válidos da janela (passo 1, mesmo padrão de
    `WindowCandidateSummary`). `per_symbol` sempre tem TODOS os símbolos
    pedidos, inclusive `n_buckets=0` -- nunca escondido atrás da
    mediana. `p_value_permutation_median` -- AG-092, mesma agregação
    (mediana entre símbolos OK, `NaN` filtrado) aplicada ao p-valor
    empírico em vez do assintótico."""

    window_name: str
    event: str
    side: int
    n_symbols_requested: int
    n_symbols_ok: int
    i_squared_pct_median: float
    p_value_permutation_median: float
    per_symbol: tuple[HeterogeneitySymbolDetail, ...]


@dataclass(frozen=True, slots=True)
class AggregatedHeterogeneityResult:
    """1 (candidato, resolução, lado) -- mediana ENTRE AS JANELAS (passo
    2, mesmo padrão de `AggregatedCandidateResult`). `side` sempre
    separado (long/short nunca fundidos -- mesma convenção de
    `m6_common_factor_hypothesis`, que trata os 2 lados como testes
    independentes, nunca pooled). `p_value_permutation_median` -- AG-092,
    mesma agregação de 2 níveis aplicada ao p-valor empírico."""

    classifier_id: str
    resolution_id: str
    side: int
    n_windows_requested: int
    n_windows_ok: int
    i_squared_pct_median: float
    p_value_permutation_median: float
    per_window: tuple[HeterogeneityWindowSummary, ...]


# ============================================================================
# Qualidade-de-gate (AG-114, 2026-08-20, PLANO_MESTRE_PRINCE2.md §15.12.1)
# -- ADR-001 (ratificado) decide regime como GATE de risco, não FEATURE
# preditiva, na v1. As dataclasses acima (separation/orthogonality via
# Welch F, heterogeneity via Cochran's Q sobre TP/SL) medem utilidade
# como FEATURE. As duas famílias abaixo medem utilidade como GATE --
# regra de decisão completa (3 gates + 1 métrica primária de ranking)
# travada ANTES de qualquer execução em `audit/architecture_gaps_
# log.yaml::AG-114`/`PLANO_MESTRE_PRINCE2.md §15.12.1`. Nenhum limiar é
# aplicado aqui -- só medição; os 2 limiares numéricos (Gate 1/Gate 2)
# seguem `TBD -- medir`, decisão deliberada (B20).
# ============================================================================


@dataclass(frozen=True, slots=True)
class GateQualitySymbolDetail:
    """1 (janela, símbolo, candidato) -- Gates 1/2/3 de `AG-114`, medidos,
    nunca aplicados (sem corte/desqualificação aqui). `stress_state_rule`:
    `"baseline_r5"` (baseline tem rótulo semântico, `m4._BASELINE_R5_
    PHYSICAL_ID`) ou `"max_mean_realized_vol_short"` (HMM/Jump Model/
    BOCPD, convenção de `identify_stress_state_by_volatility`) ou
    `"no_data"` (célula sem observação -- todo o resto do detail vira
    `NaN`/vazio, mesma disciplina AG-019 do resto do módulo).

    `state_ids`/`state_occupancy`: distribuição completa (não só o estado
    de stress) -- nunca esconde o resto atrás do número principal, mesma
    disciplina de `per_window`/`per_symbol` no resto do arquivo.

    `transition_failure_rate_n{3,5,10}`: Gate 2, grid de horizonte fixo
    (`_TRANSITION_FAILURE_HORIZONS_BARS`, não calibrado -- menu de
    comparação, mesmo status de `hmm_states_grid`).

    `detection_delay_*`: Gate 3 (papel = DESEMPATE, decidido pelo Manager
    2026-08-20 -- não desqualifica sozinho). `detection_delay_computable
    =False` pra janelas sem data de evento conhecida (CRYPTO_WINTER/
    ETF_HALVING/RECENTE -- decisão do Manager, 2026-08-20: sem instante
    único de "início do evento", inventar seria estipular, não medir).
    `detection_delay_detected=False` (com `computable=True`) significa
    que o candidato NUNCA entrou no estado de stress depois do evento,
    dentro dos dados disponíveis -- achado real, não ausência de
    medição."""

    symbol: str
    n_obs_total: int
    stress_state_id: int
    stress_state_rule: str
    n_states_present: int
    effective_number_of_states: float
    stress_state_occupancy: float
    state_ids: tuple[int, ...]
    state_occupancy: tuple[float, ...]
    transition_failure_rate_n3: float
    n_transitions_evaluable_n3: int
    transition_failure_rate_n5: float
    n_transitions_evaluable_n5: int
    transition_failure_rate_n10: float
    n_transitions_evaluable_n10: int
    detection_delay_computable: bool
    detection_delay_detected: bool
    detection_delay_ms: float
    detection_delay_onset_ts_ms: int | None


@dataclass(frozen=True, slots=True)
class GateQualityWindowSummary:
    """1 (janela, resolução, candidato) -- mediana ENTRE OS SÍMBOLOS
    válidos da janela (passo 1, mesmo padrão de `WindowCandidateSummary`/
    `HeterogeneityWindowSummary`). `n_symbols_ok` = símbolos com
    `n_obs_total > 0` (teve observação, não necessariamente detectou
    stress). `n_symbols_detection_delay_computable` -- contagem separada,
    só relevante nas janelas LUNA/FTX."""

    window_name: str
    event: str
    n_symbols_requested: int
    n_symbols_ok: int
    effective_number_of_states_median: float
    stress_state_occupancy_median: float
    transition_failure_rate_n3_median: float
    transition_failure_rate_n5_median: float
    transition_failure_rate_n10_median: float
    detection_delay_ms_median: float
    n_symbols_detection_delay_computable: int
    per_symbol: tuple[GateQualitySymbolDetail, ...]


@dataclass(frozen=True, slots=True)
class AggregatedGateQualityResult:
    """1 (candidato, resolução) -- mediana ENTRE AS JANELAS (passo 2,
    mesmo padrão de `AggregatedCandidateResult`). Sem dimensão de `side`
    -- estas métricas são sobre BARRAS (occupancy/transição/detecção),
    não sobre trades TP/SL."""

    classifier_id: str
    resolution_id: str
    n_windows_requested: int
    n_windows_ok: int
    effective_number_of_states_median: float
    stress_state_occupancy_median: float
    transition_failure_rate_n3_median: float
    transition_failure_rate_n5_median: float
    transition_failure_rate_n10_median: float
    detection_delay_ms_median: float
    n_windows_detection_delay_computable: int
    per_window: tuple[GateQualityWindowSummary, ...]


@dataclass(frozen=True, slots=True)
class VolatilityHeterogeneitySymbolDetail:
    """1 (janela, símbolo, candidato) -- métrica PRIMÁRIA de ranking de
    `AG-114`: heterogeneidade de VOLATILIDADE futura entre buckets de
    regime (não retorno -- `HeterogeneitySymbolDetail` acima continua
    medindo retorno via TP/SL, propositalmente intocada). Mesma família
    estatística (Cochran's Q/DerSimonian-Laird + permutação em bloco por
    episódio, AG-092) generalizada pra resposta contínua e ponderada por
    EPISÓDIO desde a estatística observada -- ver
    `m6_common_factor_hypothesis.cochrans_q_heterogeneity_continuous`/
    `permutation_heterogeneity_test_continuous` e
    `PLANO_MESTRE_PRINCE2.md §15.12.1` item 4 pra justificativa completa
    do peso por episódio. `p_value_permutation` é o que decide o ranking
    -- `p_value`/`i_squared_pct` (assintóticos) ficam como diagnóstico,
    mesma ressalva AG-092 de não confiar neles sob autocorrelação
    intra-episódio."""

    symbol: str
    n_buckets: int
    n_episodes: int
    n_obs_total: int
    pooled_forward_realized_vol: float
    q_statistic: float
    df: int
    p_value: float
    i_squared_pct: float
    p_value_permutation: float
    n_permutations_requested: int
    n_permutations_valid: int


@dataclass(frozen=True, slots=True)
class VolatilityHeterogeneityWindowSummary:
    window_name: str
    event: str
    n_symbols_requested: int
    n_symbols_ok: int
    i_squared_pct_median: float
    p_value_permutation_median: float
    per_symbol: tuple[VolatilityHeterogeneitySymbolDetail, ...]


@dataclass(frozen=True, slots=True)
class AggregatedVolatilityHeterogeneityResult:
    classifier_id: str
    resolution_id: str
    n_windows_requested: int
    n_windows_ok: int
    i_squared_pct_median: float
    p_value_permutation_median: float
    per_window: tuple[VolatilityHeterogeneityWindowSummary, ...]


@dataclass(frozen=True, slots=True)
class CellOutcome:
    """Resultado de 1 célula (janela, símbolo) sob 1 resolução --
    `symbol_result=None, error=None` é "folds insuficientes" (`m4.run_
    regime_comparison_for_symbol` devolveu `None`, dado real mas
    insuficiente pra `initial_train_years`); `error is not None` é uma
    EXCEÇÃO real (IO, bug, processo filho morto) -- os 2 casos são
    DIFERENTES (`skipped_cells` vs. `failed_cells` no relatório final),
    nunca colapsados num só.

    `raw_labels`: rótulos brutos por barra, por `classifier_id`
    (`m4.RawLabels`, mesmo dict que `return_raw_labels=True` expõe em
    `m4.compare_regime_candidates_for_symbol`) -- coletado SEMPRE (custo
    desprezível, ver `Q3AggregatedResult`), usado só pela agregação de Q3;
    `None` sempre que `symbol_result is None` (célula sem folds/com erro
    não tem rótulo nenhum pra oferecer)."""

    window_name: str
    symbol: str
    resolution_id: str
    symbol_result: m4.SymbolResult | None
    error: str | None = None
    raw_labels: dict[str, m4.RawLabels] | None = None


@dataclass(frozen=True, slots=True)
class FailedCell:
    window_name: str
    symbol: str
    resolution_id: str
    error: str


@dataclass(frozen=True, slots=True)
class SkippedCell:
    window_name: str
    symbol: str
    resolution_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class CriticalWindowsReport:
    """1 resolução completa -- `baseline` + os candidatos que apareceram
    em pelo menos 1 célula OK (ordem: a mesma em que apareceram pela
    primeira vez em `m4.SymbolResult.candidates`, tipicamente HMM k2/k3/k4,
    Jump Model, BOCPD -- mas não hardcoded, ver `_collect_classifier_ids`).
    `failed_cells`/`skipped_cells` -- nunca escondidos, AG-019.

    `q3`: Terceira via, 1 `Q3AggregatedResult` por `classifier_id` que
    apareceu em `baseline`/`candidates` (mesmo conjunto, mesma ordem --
    baseline primeiro) -- pronta pra ler assim que uma execução real
    rodar, sem exigir nenhum passo/flag adicional (ver docstring de
    `Q3AggregatedResult`, "custo zero").

    `heterogeneity`: G-C1-2 revisado, 2 `AggregatedHeterogeneityResult`
    (long + short) por `classifier_id` -- vazio (`()`) se `aggregate_
    critical_windows_results` foi chamada sem `labels_by_symbol` (ver
    docstring da função, preserva contrato antigo por default).

    `gate_quality`/`volatility_heterogeneity` -- extensão de qualidade-
    de-gate (AG-114, 2026-08-20, `PLANO_MESTRE_PRINCE2.md §15.12.1`), 1
    `AggregatedGateQualityResult`/`AggregatedVolatilityHeterogeneityResult`
    por `classifier_id` (sem dimensão de `side` -- computados sobre
    BARRAS, não trades). Vazios (`()`) se `aggregate_critical_windows_
    results` foi chamada sem `forward_vol_by_symbol` (mesmo default
    preserva-contrato de `heterogeneity`)."""

    resolution_id: str
    baseline: AggregatedCandidateResult
    candidates: tuple[AggregatedCandidateResult, ...]
    failed_cells: tuple[FailedCell, ...]
    skipped_cells: tuple[SkippedCell, ...]
    q3: tuple[Q3AggregatedResult, ...]
    heterogeneity: tuple[AggregatedHeterogeneityResult, ...] = ()
    gate_quality: tuple[AggregatedGateQualityResult, ...] = ()
    volatility_heterogeneity: tuple[AggregatedVolatilityHeterogeneityResult, ...] = ()


# ============================================================================
# Núcleo puro -- agregação, sem IO (recebe CellOutcome já calculados)
# ============================================================================


def _median_or_nan(values: list[float]) -> float:
    """Mediana só das observações FINITAS -- filtra `NaN` explicitamente
    em vez de `np.nanmedian` (que emite `RuntimeWarning` quando TODAS as
    entradas são `NaN`, mesmo sendo um cenário real/esperado aqui --
    candidato degenerado em toda uma janela/todo o estudo -- CLAUDE.md
    proíbe silenciar warning sem tratar a causa; filtrar explicitamente
    evita o warning por NÃO produzir a situação que o dispara, não por
    escondê-lo). Lista vazia (nenhuma observação finita) -> `NaN`
    explícito, mesma disciplina de `_anova_or_degenerate`/`_persistence_
    or_degenerate` em `m4_regime_comparison.py` -- ausência de medição,
    não erro, não zero inventado."""
    finite = [v for v in values if np.isfinite(v)]
    if not finite:
        return float("nan")
    return float(np.median(np.asarray(finite, dtype=np.float64)))


def _symbol_detail_from_candidate(
    symbol: str, candidate: m4.CandidateResult
) -> SymbolCandidateDetail:
    return SymbolCandidateDetail(
        symbol=symbol,
        n_states=candidate.n_states,
        separation_omega_squared=candidate.separation.omega_squared,
        orthogonality_omega_squared=candidate.orthogonality.omega_squared,
        persistence_median_duration_bars=candidate.persistence.median_duration_bars,
        persistence_switch_rate=candidate.persistence.switch_rate,
        fold_stability_adjusted_rand_mean=candidate.fold_stability_adjusted_rand_mean,
        fold_stability_adjusted_rand_min=candidate.fold_stability_adjusted_rand_min,
        fold_stability_by_construction=candidate.fold_stability_by_construction,
        n_oos_obs=candidate.n_oos_obs,
        n_folds_evaluated=candidate.n_folds_evaluated,
        is_saturated=candidate.persistence.switch_rate == 0.0,
    )


def _window_summary(
    window: CriticalWindow, details: list[SymbolCandidateDetail]
) -> WindowCandidateSummary:
    return WindowCandidateSummary(
        window_name=window.name,
        event=window.event,
        n_symbols_requested=len(window.symbols),
        n_symbols_ok=len(details),
        n_symbols_saturated=sum(1 for d in details if d.is_saturated),
        separation_omega_squared=_median_or_nan([d.separation_omega_squared for d in details]),
        orthogonality_omega_squared=_median_or_nan(
            [d.orthogonality_omega_squared for d in details]
        ),
        persistence_median_duration_bars=_median_or_nan(
            [d.persistence_median_duration_bars for d in details]
        ),
        persistence_switch_rate=_median_or_nan([d.persistence_switch_rate for d in details]),
        fold_stability_adjusted_rand_mean=_median_or_nan(
            [d.fold_stability_adjusted_rand_mean for d in details]
        ),
        n_oos_obs_total=sum(d.n_oos_obs for d in details),
        per_symbol=tuple(details),
    )


def _find_candidate(
    symbol_result: m4.SymbolResult, classifier_id: str
) -> m4.CandidateResult | None:
    """Lookup por `classifier_id` (não índice posicional) -- robusto a
    `symbol_result.candidates` ter uma ordem/composição diferente entre
    células por algum motivo real (não deveria acontecer com `hmm_states_
    grid`/hiperparâmetros fixos entre chamadas, mas "confirme, não
    presuma" é a disciplina do resto do módulo `m4_regime_comparison.py`,
    reaplicada aqui)."""
    for candidate in symbol_result.candidates:
        if candidate.classifier_id == classifier_id:
            return candidate
    return None


def _baseline_getter(symbol_result: m4.SymbolResult) -> m4.CandidateResult | None:
    return symbol_result.baseline


def _make_candidate_getter(
    classifier_id: str,
) -> Callable[[m4.SymbolResult], m4.CandidateResult | None]:
    """Fábrica de `get_candidate` fechada sobre `classifier_id` -- mesmo
    motivo de `m4_regime_comparison._make_hmm_fit_fn`: mypy não infere o
    tipo de uma `lambda` definida dentro de uma expressão geradora sem
    essa indireção, e a captura tardia de `classifier_id` por `lambda`
    sem parâmetro default seria um bug clássico de closure (todas as
    lambdas fechando sobre o MESMO `classifier_id` final do loop)."""

    def _get(symbol_result: m4.SymbolResult) -> m4.CandidateResult | None:
        return _find_candidate(symbol_result, classifier_id)

    return _get


#: Fallback só usado quando NENHUMA célula rodou com sucesso (todas
#: falharam/foram puladas) -- `QuantileRegimeClassifier.classifier_id` é
#: uma constante fixa (`"quantile_regime_v1"`, não depende de `symbol`,
#: ver `src.regime.classifier`), citada aqui literal em vez de instanciar
#: o classificador só para ler uma property constante.
_BASELINE_CLASSIFIER_ID_FALLBACK: Final[str] = "quantile_regime_v1"


def _collect_classifier_ids(ok_cells: list[CellOutcome]) -> tuple[str, list[str]]:
    """`(baseline_classifier_id, candidate_classifier_ids)` -- une o
    conjunto de `classifier_id` que apareceu em QUALQUER célula OK,
    preservando a ordem de primeira aparição (não um `set` -- ordem
    determinística no relatório final)."""
    baseline_classifier_id = _BASELINE_CLASSIFIER_ID_FALLBACK
    if ok_cells:
        first_symbol_result = ok_cells[0].symbol_result
        assert first_symbol_result is not None  # ok_cells já filtrado
        baseline_classifier_id = first_symbol_result.baseline.classifier_id
    candidate_ids: list[str] = []
    seen: set[str] = set()
    for cell in ok_cells:
        assert cell.symbol_result is not None  # ok_cells já filtrado
        for candidate in cell.symbol_result.candidates:
            if candidate.classifier_id not in seen:
                seen.add(candidate.classifier_id)
                candidate_ids.append(candidate.classifier_id)
    return baseline_classifier_id, candidate_ids


def _aggregate_one_candidate(
    classifier_id: str,
    resolution_id: str,
    windows: tuple[CriticalWindow, ...],
    ok_cells: list[CellOutcome],
    get_candidate: Callable[[m4.SymbolResult], m4.CandidateResult | None],
) -> AggregatedCandidateResult:
    window_summaries: list[WindowCandidateSummary] = []
    for window in windows:
        details: list[SymbolCandidateDetail] = []
        for cell in ok_cells:
            if cell.window_name != window.name:
                continue
            assert cell.symbol_result is not None
            candidate = get_candidate(cell.symbol_result)
            if candidate is None:
                continue
            details.append(_symbol_detail_from_candidate(cell.symbol, candidate))
        window_summaries.append(_window_summary(window, details))

    ok_summaries = [w for w in window_summaries if w.n_symbols_ok > 0]
    n_states = ok_summaries[0].per_symbol[0].n_states if ok_summaries else 0
    n_cells_ok_total = sum(w.n_symbols_ok for w in window_summaries)
    n_cells_saturated_total = sum(w.n_symbols_saturated for w in window_summaries)
    saturation_rate = (
        n_cells_saturated_total / n_cells_ok_total  # noqa: unguarded-ratio -- guardado por n_cells_ok_total>0 no if/else desta expressão
        if n_cells_ok_total > 0
        else float("nan")
    )

    return AggregatedCandidateResult(
        classifier_id=classifier_id,
        resolution_id=resolution_id,
        n_states=n_states,
        n_windows_requested=len(window_summaries),
        n_windows_ok=len(ok_summaries),
        n_cells_saturated_total=n_cells_saturated_total,
        saturation_rate=saturation_rate,
        separation_omega_squared_median=_median_or_nan(
            [w.separation_omega_squared for w in ok_summaries]
        ),
        orthogonality_omega_squared_median=_median_or_nan(
            [w.orthogonality_omega_squared for w in ok_summaries]
        ),
        persistence_median_duration_bars_median=_median_or_nan(
            [w.persistence_median_duration_bars for w in ok_summaries]
        ),
        persistence_switch_rate_median=_median_or_nan(
            [w.persistence_switch_rate for w in ok_summaries]
        ),
        fold_stability_adjusted_rand_mean_median=_median_or_nan(
            [w.fold_stability_adjusted_rand_mean for w in ok_summaries]
        ),
        n_oos_obs_total=sum(w.n_oos_obs_total for w in window_summaries),
        per_window=tuple(window_summaries),
    )


def _q3_asset_detail(
    btc_raw: m4.RawLabels, asset_symbol: str, asset_raw: m4.RawLabels
) -> Q3AssetDetail:
    """1 ativo não-BTC -- as-of join causal (`m4._asof_join_btc_labels`,
    MESMA função usada por `m4.run_q3_common_factor_regime`, não uma
    reimplementação -- reusar em vez de duplicar a lógica de join
    backward é deliberado, essa lógica já tem teste dedicado de
    causalidade em `tests/unit/test_analysis_m4_regime_comparison.py`)."""
    labels_own, labels_btc_derived = m4._asof_join_btc_labels(btc_raw, asset_raw)
    n_compared = int(labels_own.shape[0])
    ari = (
        float("nan")
        if n_compared < m4._Q3_MIN_BARS_COMPARED
        else adjusted_rand(labels_own, labels_btc_derived)
    )
    return Q3AssetDetail(symbol=asset_symbol, n_bars_compared=n_compared, adjusted_rand=ari)


def _q3_window_summary(
    window: CriticalWindow,
    classifier_id: str,
    cells_by_symbol: dict[str, CellOutcome],
) -> Q3WindowSummary | None:
    """`None` se a janela não é elegível pra Q3 (`len(window.symbols) <= 1`
    -- LUNA/FTX, só BTCUSDT, não têm nenhum ativo pra comparar contra o
    rótulo derivado de BTC). Célula de BTC ou de um ativo específico
    ausente/sem `raw_labels`/sem este `classifier_id` -- mesma disciplina
    AG-019 do resto do módulo: aquele ativo fica de fora de `per_asset`,
    nunca derruba a janela inteira nem o resto do estudo."""
    other_symbols = tuple(s for s in window.symbols if s != "BTCUSDT")
    if not other_symbols:
        return None

    details: list[Q3AssetDetail] = []
    btc_cell = cells_by_symbol.get("BTCUSDT")
    btc_raw = (
        btc_cell.raw_labels.get(classifier_id)
        if btc_cell is not None and btc_cell.raw_labels is not None
        else None
    )
    if btc_raw is not None:
        for symbol in other_symbols:
            asset_cell = cells_by_symbol.get(symbol)
            asset_raw = (
                asset_cell.raw_labels.get(classifier_id)
                if asset_cell is not None and asset_cell.raw_labels is not None
                else None
            )
            if asset_raw is not None:
                details.append(_q3_asset_detail(btc_raw, symbol, asset_raw))

    return Q3WindowSummary(
        window_name=window.name,
        event=window.event,
        n_assets_requested=len(other_symbols),
        n_assets_ok=len(details),
        adjusted_rand_median=_median_or_nan([d.adjusted_rand for d in details]),
        per_asset=tuple(details),
    )


def _aggregate_q3_for_classifier(
    classifier_id: str,
    resolution_id: str,
    windows: tuple[CriticalWindow, ...],
    ok_cells: list[CellOutcome],
) -> Q3AggregatedResult:
    """Q3 pra 1 candidato -- mesma mediana-de-medianas de
    `_aggregate_one_candidate`, mas só sobre as janelas ELEGÍVEIS
    (`n_windows_applicable <= n_windows_requested_total`; LUNA/FTX nunca
    entram). Custo zero em fits -- só reusa `CellOutcome.raw_labels` já
    coletado (ver docstring de `Q3AggregatedResult`)."""
    window_summaries: list[Q3WindowSummary] = []
    for window in windows:
        cells_by_symbol = {c.symbol: c for c in ok_cells if c.window_name == window.name}
        summary = _q3_window_summary(window, classifier_id, cells_by_symbol)
        if summary is not None:
            window_summaries.append(summary)

    ok_summaries = [w for w in window_summaries if w.n_assets_ok > 0]
    return Q3AggregatedResult(
        classifier_id=classifier_id,
        resolution_id=resolution_id,
        n_windows_requested_total=len(windows),
        n_windows_applicable=len(window_summaries),
        n_windows_ok=len(ok_summaries),
        adjusted_rand_median=_median_or_nan([w.adjusted_rand_median for w in ok_summaries]),
        per_window=tuple(window_summaries),
    )


def _asof_join_regime_onto_labels(labels: pl.DataFrame, regime_raw: m4.RawLabels) -> pl.DataFrame:
    """As-of BACKWARD (causal) -- cada linha de `labels` (grade
    15m-calendário, `t0`) recebe o bucket de regime (grade dollar-bar
    R1/R2/R3, `close_time_ms`) ATIVO no seu `t0`, NUNCA um bucket com
    timestamp futuro. Mesma prova de causalidade central de `m4._asof_
    join_btc_labels`/Q3, reaplicada a label em vez de ativo -- as duas
    grades são DIFERENTES (calendário vs. volume-triggered), por isso
    join por TIMESTAMP, nunca índice posicional. Labels sem bucket de
    regime disponível (antes da primeira barra do candidato) são
    excluídos, nunca um crash -- mesmo tratamento de `_asof_join_btc_
    labels` pra sobreposição parcial.

    **`close_time_ms`, não `open_time_ms` -- corrigido 2026-08-19, AG-090
    (achado de auditoria cética, mesma classe do fix em `m4._asof_join_
    btc_labels`):** confirmado que `t0` de `labels.parquet`
    (`src/labels/triple_barrier.py:913`, `t0_arr = bars["close_time"]`) JÁ
    é o `close_time` da barra de decisão -- comparar contra `regime_raw.
    open_time_ms` (a versão antiga desta função) chaveava um rótulo de
    regime pelo INÍCIO da barra que o gerou, um timestamp anterior ao
    `close_time` em que esse rótulo de fato ficou disponível. Pra
    resoluções de dollar-bar mais lentas (R2/R3, duração mediana
    ~30min/~1h, cauda p99 até ~1-2h -- `experiments/dollar_bar_duration_
    distribution.json`), esse gap inflava artificialmente quantos buckets
    de regime "já existiam" num dado `t0` de label -- vazamento temporal,
    mesma classe de B02."""
    regime_df = pl.DataFrame(
        {"_regime_close_ms": regime_raw.close_time_ms, "regime_bucket": regime_raw.canonical_id}
    ).sort("_regime_close_ms")
    labels_sorted = labels.with_columns(
        pl.col("t0").dt.epoch(time_unit="ms").alias("_t0_ms")
    ).sort("_t0_ms")
    joined = labels_sorted.join_asof(
        regime_df, left_on="_t0_ms", right_on="_regime_close_ms", strategy="backward"
    )
    return joined.filter(pl.col("regime_bucket").is_not_null())


def _heterogeneity_for_symbol_window(
    symbol: str,
    window: CriticalWindow,
    regime_raw: m4.RawLabels,
    labels_full: pl.DataFrame,
    *,
    tp_atr_mult: float,
    sl_atr_mult: float,
    maker_fee: float,
    taker_fee: float,
    n_permutations: int,
    permutation_seed: int,
) -> tuple[HeterogeneitySymbolDetail, HeterogeneitySymbolDetail]:
    """`(long, short)` -- `labels_full` é o `labels.parquet` INTEIRO do
    símbolo (chamador carrega 1x, reusado pelas 3 resoluções -- labels
    não dependem de resolução de regime); recortado aqui pro período
    `[window.start, window.end)` por `t0`, depois as-of joinado contra
    `regime_raw`. `n_buckets=0` (sem overlap nenhum entre labels e
    janela, ou nenhuma linha sobreviveu ao as-of join) devolve `NaN`
    explícito, nunca chama `m6.cochrans_q_heterogeneity` sobre strata
    vazia (levantaria `IndexError` -- guard aqui, não lá).

    **Achado real (Fase D re-run, 2026-08-18): comparar `t0` contra um
    literal `pl.lit(...).str.to_datetime()` quebra em produção** --
    `labels.parquet` real tem `t0: Datetime('ms', 'UTC')` (timezone-aware,
    precisão ms), mas `str.to_datetime()` sem argumentos produz
    `Datetime('μs')` (naive, precisão μs) -- `polars.exceptions.SchemaError`
    ao comparar os dois dtypes, só descoberto depois de ~2h de fit real de
    R1 já ter rodado (o bug só dispara na agregação, no FIM da resolução).
    Corrigido comparando por EPOCH MS (`.dt.epoch(time_unit="ms")`,
    mesmo padrão já usado em `_asof_join_regime_onto_labels`) em vez de
    literal de data -- nunca depende de dtype/timezone do literal
    bater com a coluna real.

    **`n_permutations`/`permutation_seed` -- AG-092, 2026-08-19.**
    Repassados pra `m6.permutation_heterogeneity_test`, que exige as
    linhas de `side_df` ORDENADAS POR TEMPO -- garantido aqui porque
    `_asof_join_regime_onto_labels` preserva a ordem de `labels_sorted`
    (`.sort("_t0_ms")`) e `.filter(pl.col("side") == side)` preserva a
    ordem relativa das linhas que sobrevivem (Polars nunca reordena num
    `filter`)."""
    start_ms = _iso_date_to_epoch_ms(window.start)
    end_ms = _iso_date_to_epoch_ms(window.end)
    window_labels = labels_full.filter(
        (pl.col("t0").dt.epoch(time_unit="ms") >= start_ms)
        & (pl.col("t0").dt.epoch(time_unit="ms") < end_ms)
    )
    joined = _asof_join_regime_onto_labels(window_labels, regime_raw)

    details: list[HeterogeneitySymbolDetail] = []
    for side in (1, -1):
        side_df = joined.filter(pl.col("side") == side)
        buckets = sorted(side_df["regime_bucket"].unique().to_list())
        if not buckets:
            details.append(
                HeterogeneitySymbolDetail(
                    symbol=symbol,
                    side=side,
                    n_buckets=0,
                    n_obs_total=side_df.height,
                    pooled_edge_bruto_atr=float("nan"),
                    q_statistic=float("nan"),
                    df=-1,
                    p_value=float("nan"),
                    i_squared_pct=float("nan"),
                    p_value_permutation=float("nan"),
                    n_episodes=0,
                    n_permutations_requested=n_permutations,
                    n_permutations_valid=0,
                )
            )
            continue
        strata = tuple(
            m6.stratum_metrics(
                side_df.filter(pl.col("regime_bucket") == bucket),
                symbol=symbol,
                side=side,
                regime=str(bucket),
                tp_atr_mult=tp_atr_mult,
                sl_atr_mult=sl_atr_mult,
                maker_fee=maker_fee,
                taker_fee=taker_fee,
            )
            for bucket in buckets
        )
        het = m6.cochrans_q_heterogeneity(strata)

        # AG-092 (achado de auditoria independente, F1, 2026-08-19):
        # m6.permutation_heterogeneity_test EXIGE bucket_ids/is_tp/is_sl
        # ordenados por tempo -- extração de episódio é puramente
        # posicional (regime_utility.segment_boundaries não olha
        # timestamp nenhum). `.filter()`/`join_asof` deveriam preservar
        # essa ordem (join_asof é sort-merge sobre 2 lados já ordenados;
        # `.filter()` tem garantia documentada da própria API do
        # Polars), mas confirmado por pesquisa que essa garantia NÃO é
        # um contrato público com a mesma força pra `join_asof` -- o
        # próprio Polars já teve uma regressão real dessa exata
        # propriedade (corrigida jan/2026, PR #25990, escopada a
        # pipelines lazy/streaming, não ao uso eager simples daqui, mas
        # prova que a propriedade não era tratada como garantia formal
        # até então). Confirmar em RUNTIME em vez de confiar cegamente
        # numa propriedade que poderia quebrar silenciosamente num
        # upgrade futuro de `polars` -- falha ruidosa aqui, nunca um
        # episódio artificial silencioso.
        t0_ms_ordered = side_df["_t0_ms"].to_numpy()
        if not np.all(np.diff(t0_ms_ordered) >= 0):
            raise ValueError(
                f"_heterogeneity_for_symbol_window({symbol!r}, {window.name!r}, side={side}): "
                "side_df não está ordenado por tempo (_t0_ms não monotônico) -- "
                "m6.permutation_heterogeneity_test exige ordenação cronológica estrita pra "
                "extrair episódios corretamente (AG-092)"
            )

        bucket_ids = side_df["regime_bucket"].cast(pl.Int64).to_numpy()
        is_tp = (side_df["barrier_hit"] == "TP").cast(pl.Int64).to_numpy()
        is_sl = (side_df["barrier_hit"] == "SL").cast(pl.Int64).to_numpy()
        perm = m6.permutation_heterogeneity_test(
            bucket_ids,
            is_tp,
            is_sl,
            tp_mult=tp_atr_mult,
            sl_mult=sl_atr_mult,
            n_permutations=n_permutations,
            seed=permutation_seed,
        )

        details.append(
            HeterogeneitySymbolDetail(
                symbol=symbol,
                side=side,
                n_buckets=len(strata),
                n_obs_total=side_df.height,
                pooled_edge_bruto_atr=het.pooled_edge_bruto_atr,
                q_statistic=het.q_statistic,
                df=het.df,
                p_value=het.p_value,
                i_squared_pct=het.i_squared_pct,
                p_value_permutation=perm.p_value,
                n_episodes=perm.n_episodes,
                n_permutations_requested=n_permutations,
                n_permutations_valid=perm.n_permutations_valid,
            )
        )
    return details[0], details[1]


def _window_heterogeneity_summary(
    window: CriticalWindow, side: int, details: tuple[HeterogeneitySymbolDetail, ...]
) -> HeterogeneityWindowSummary:
    ok_details = [d for d in details if d.n_buckets > 0]
    return HeterogeneityWindowSummary(
        window_name=window.name,
        event=window.event,
        side=side,
        n_symbols_requested=len(window.symbols),
        n_symbols_ok=len(ok_details),
        i_squared_pct_median=_median_or_nan([d.i_squared_pct for d in ok_details]),
        p_value_permutation_median=_median_or_nan(
            [d.p_value_permutation for d in ok_details]
        ),
        per_symbol=details,
    )


def _aggregate_heterogeneity_for_classifier(
    classifier_id: str,
    resolution_id: str,
    side: int,
    windows: tuple[CriticalWindow, ...],
    ok_cells: list[CellOutcome],
    labels_by_symbol: dict[str, pl.DataFrame],
    *,
    tp_atr_mult: float,
    sl_atr_mult: float,
    maker_fee: float,
    taker_fee: float,
    n_permutations: int,
    permutation_seed: int,
) -> AggregatedHeterogeneityResult:
    """Mesma mediana-de-medianas de `_aggregate_one_candidate`/`_aggregate_
    q3_for_classifier` -- só reusa `CellOutcome.raw_labels` já coletado
    (zero fits novos) + `labels_by_symbol` já carregado pelo chamador
    (zero IO novo por candidato/resolução -- `labels.parquet` é lido 1x
    por símbolo, fora do loop de candidato/resolução, ver docstring de
    `aggregate_critical_windows_results`)."""
    window_summaries: list[HeterogeneityWindowSummary] = []
    for window in windows:
        details: list[HeterogeneitySymbolDetail] = []
        for symbol in window.symbols:
            cell = next(
                (c for c in ok_cells if c.window_name == window.name and c.symbol == symbol),
                None,
            )
            labels_full = labels_by_symbol.get(symbol)
            regime_raw = (
                cell.raw_labels.get(classifier_id)
                if cell is not None and cell.raw_labels is not None
                else None
            )
            if regime_raw is None or labels_full is None:
                # célula/labels ausentes -- placeholder explícito, NUNCA
                # omitido de per_symbol (mesma disciplina AG-019 do resto
                # do módulo: falha vira NaN visível, não desaparece).
                details.append(
                    HeterogeneitySymbolDetail(
                        symbol=symbol,
                        side=side,
                        n_buckets=0,
                        n_obs_total=0,
                        pooled_edge_bruto_atr=float("nan"),
                        q_statistic=float("nan"),
                        df=-1,
                        p_value=float("nan"),
                        i_squared_pct=float("nan"),
                        p_value_permutation=float("nan"),
                        n_episodes=0,
                        n_permutations_requested=n_permutations,
                        n_permutations_valid=0,
                    )
                )
                continue
            long_detail, short_detail = _heterogeneity_for_symbol_window(
                symbol,
                window,
                regime_raw,
                labels_full,
                tp_atr_mult=tp_atr_mult,
                sl_atr_mult=sl_atr_mult,
                maker_fee=maker_fee,
                taker_fee=taker_fee,
                n_permutations=n_permutations,
                permutation_seed=permutation_seed,
            )
            details.append(long_detail if side == 1 else short_detail)
        window_summaries.append(_window_heterogeneity_summary(window, side, tuple(details)))

    ok_summaries = [w for w in window_summaries if w.n_symbols_ok > 0]
    return AggregatedHeterogeneityResult(
        classifier_id=classifier_id,
        resolution_id=resolution_id,
        side=side,
        n_windows_requested=len(window_summaries),
        n_windows_ok=len(ok_summaries),
        i_squared_pct_median=_median_or_nan([w.i_squared_pct_median for w in ok_summaries]),
        p_value_permutation_median=_median_or_nan(
            [w.p_value_permutation_median for w in ok_summaries]
        ),
        per_window=tuple(window_summaries),
    )


# ============================================================================
# Qualidade-de-gate -- núcleo de cálculo (AG-114, 2026-08-20). Bloco
# contíguo por decisão de organização: `_compute_symbol_forward_vol_
# history` não precisa ficar perto de `_compute_bocpd_full_history` (são
# computações independentes -- esta não roda BOCPD nenhum, só extrai o
# observável `realized_vol_short`, candidato-independente); manter todo o
# bloco de AG-114 junto (núcleo -> agregação) é mais fácil de revisar como
# unidade do que espalhado pelas seções já existentes do arquivo.
# ============================================================================

_TRANSITION_FAILURE_HORIZONS_BARS: Final[tuple[int, ...]] = (3, 5, 10)


@dataclass(frozen=True, slots=True)
class _SymbolForwardVolHistory:
    """`realized_vol_short`/`forward_realized_vol` do histórico causal
    COMPLETO do símbolo -- CANDIDATO-INDEPENDENTE (só depende do OHLC da
    dollar-bar, não de qual dos 6 candidatos está sendo avaliado),
    computado 1x por (símbolo, resolução) e reusado por todos eles via
    `_join_candidate_with_vol_history` (join por `close_time_ms` contra o
    `RawLabels` de cada candidato -- já coletado sem custo extra por
    `_run_one_cell`, ver `Q3AggregatedResult`). Diferente de
    `_BocpdFullHistory` (que roda BOCPD sobre o histórico completo e
    carrega o `canonical_id` DELE especificamente) -- esta estrutura não
    tem `canonical_id` nenhum, é pura observação de mercado."""

    close_time_ms: m4.IntArray
    realized_vol_short: m4.FloatArray
    forward_realized_vol: m4.FloatArray


def _compute_symbol_forward_vol_history(
    symbol: str, resolution_id: str
) -> _SymbolForwardVolHistory:
    """Mesma mecânica de carga/trim de `_compute_bocpd_full_history`
    (reusa `m4._input_obs`/`m4._valid_start_idx`, mesmos helpers PRIVADOS,
    mesma fórmula exata -- não uma reimplementação), mas SEM rodar BOCPD:
    só extrai `realized_vol_short` (já calculado por `m4._input_obs`) e
    desloca pra `forward_realized_vol` via `m4._forward_realized_vol`,
    usando o MESMO `window` que `_input_obs` já usou pra computar
    `realized_vol_short` (`feature_c06_vol_ratio_short_window`) -- desloca
    a mesma janela pra frente, não inventa um horizonte novo."""
    throttle = lake.DuckDBThrottle(
        memory_limit_gb=float(load_data_constant("m4_duckdb_memory_limit_gb")),
        threads=int(load_data_constant("m4_duckdb_threads")),
    )
    start = m4.SYMBOL_START_DATE[symbol]
    end = m4.END_DATE
    bars_df = lake.query_dollar_bars(
        symbol,
        start,
        end,
        resolution_id=resolution_id,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    log_return_1_full, obs_2d_full = m4._input_obs(bars_df)
    valid_start_idx = m4._valid_start_idx(log_return_1_full, obs_2d_full[:, 1])
    close_time_ms = bars_df["close_time"].cast(pl.Int64).to_numpy()[valid_start_idx:]
    realized_vol_short = obs_2d_full[:, 1][valid_start_idx:]

    short_window = int(load_feature_constant("feature_c06_vol_ratio_short_window"))
    forward_realized_vol = m4._forward_realized_vol(realized_vol_short, short_window)

    logger.info(
        "analysis.m4_critical_windows.forward_vol_history_bars_loaded",
        symbol=symbol,
        resolution_id=resolution_id,
        n_bars=int(realized_vol_short.shape[0]),
    )

    return _SymbolForwardVolHistory(
        close_time_ms=close_time_ms,
        realized_vol_short=realized_vol_short,
        forward_realized_vol=forward_realized_vol,
    )


def _join_candidate_with_vol_history(
    regime_raw: m4.RawLabels, vol_history: _SymbolForwardVolHistory
) -> tuple[m4.IntArray, m4.IntArray, m4.FloatArray, m4.FloatArray]:
    """`(canonical_id, close_time_ms, realized_vol_short, forward_realized_vol)`
    alinhados por interseção EXATA de `close_time_ms` (join, não asof) --
    as 2 séries vêm da MESMA grade de dollar-bar (mesmo símbolo/resolução);
    `regime_raw` é sempre um SUBCONJUNTO de barras (exclusão de R0 no
    baseline, fold de teste específico pros demais candidatos), nunca uma
    grade diferente, então toda barra de `regime_raw` tem exatamente 0 ou
    1 match. `.sort("_close_ms")` explícito depois do join -- mesma
    disciplina de `_heterogeneity_for_symbol_window` (AG-092): não confiar
    cegamente em ordem preservada por join, os consumidores
    (`segment_boundaries` via `permutation_heterogeneity_test_continuous`)
    exigem ordenação cronológica estrita pra extrair episódio
    corretamente -- verificado em runtime, não só assumido."""
    regime_df = pl.DataFrame(
        {"_close_ms": regime_raw.close_time_ms, "canonical_id": regime_raw.canonical_id}
    )
    vol_df = pl.DataFrame(
        {
            "_close_ms": vol_history.close_time_ms,
            "realized_vol_short": vol_history.realized_vol_short,
            "forward_realized_vol": vol_history.forward_realized_vol,
        }
    )
    joined = regime_df.join(vol_df, on="_close_ms", how="inner").sort("_close_ms")
    close_time_ms = joined["_close_ms"].cast(pl.Int64).to_numpy()
    if close_time_ms.shape[0] > 0 and not np.all(np.diff(close_time_ms) >= 0):
        raise ValueError(
            "_join_candidate_with_vol_history: resultado não está ordenado por tempo -- "
            "invariante violado (deveria ser garantido pelo .sort() acima, AG-092)"
        )
    return (
        joined["canonical_id"].cast(pl.Int64).to_numpy(),
        close_time_ms,
        joined["realized_vol_short"].cast(pl.Float64).to_numpy(),
        joined["forward_realized_vol"].cast(pl.Float64).to_numpy(),
    )


def _detection_delay_ms(
    close_time_ms: m4.IntArray, canonical_id: m4.IntArray, stress_state_id: int, onset_ts_ms: int
) -> tuple[bool, float]:
    """`(detected, delay_ms)` -- primeira barra com `close_time_ms >=
    onset_ts_ms` E `canonical_id == stress_state_id`. `delay_ms` sempre
    `>=0` (mede REAÇÃO ao evento, nunca antecipação -- barras antes do
    onset nunca contam, mesmo que já estivessem em `stress_state_id` por
    outro motivo). `(False, NaN)` se nenhuma barra pós-onset atingir
    stress -- achado real ("nunca detectou"), não ausência de medição.
    Assume `close_time_ms` já ordenado (contrato do chamador, garantido
    por `_join_candidate_with_vol_history`)."""
    post_onset_mask = close_time_ms >= onset_ts_ms
    stress_mask = canonical_id == stress_state_id
    detected_mask = post_onset_mask & stress_mask
    if not np.any(detected_mask):
        return False, float("nan")
    first_detected_idx = int(np.argmax(detected_mask))
    return True, float(close_time_ms[first_detected_idx] - onset_ts_ms)


def _gate_quality_for_symbol_window(
    symbol: str,
    classifier_id: str,
    baseline_classifier_id: str,
    canonical_id: m4.IntArray,
    close_time_ms: m4.IntArray,
    realized_vol_short: m4.FloatArray,
    *,
    onset_ts_ms: int | None,
) -> GateQualitySymbolDetail:
    """Gates 1/2/3 de `AG-114` pra 1 (símbolo, janela, candidato) --
    `canonical_id`/`close_time_ms`/`realized_vol_short` já JOINADOS
    (`_join_candidate_with_vol_history`), mesma barra em todos os 3
    arrays."""
    n_obs_total = int(canonical_id.shape[0])
    if n_obs_total == 0:
        return GateQualitySymbolDetail(
            symbol=symbol,
            n_obs_total=0,
            stress_state_id=-1,
            stress_state_rule="no_data",
            n_states_present=0,
            effective_number_of_states=float("nan"),
            stress_state_occupancy=float("nan"),
            state_ids=(),
            state_occupancy=(),
            transition_failure_rate_n3=float("nan"),
            n_transitions_evaluable_n3=0,
            transition_failure_rate_n5=float("nan"),
            n_transitions_evaluable_n5=0,
            transition_failure_rate_n10=float("nan"),
            n_transitions_evaluable_n10=0,
            detection_delay_computable=onset_ts_ms is not None,
            detection_delay_detected=False,
            detection_delay_ms=float("nan"),
            detection_delay_onset_ts_ms=onset_ts_ms,
        )

    if classifier_id == baseline_classifier_id:
        stress_state_id = m4._BASELINE_R5_PHYSICAL_ID
        stress_state_rule = "baseline_r5"
    else:
        stress_state_id = identify_stress_state_by_volatility(canonical_id, realized_vol_short)
        stress_state_rule = "max_mean_realized_vol_short"

    occ = occupancy_metrics(canonical_id)
    stress_occupancy = (
        occ.occupancy[occ.state_ids.index(stress_state_id)]
        if stress_state_id in occ.state_ids
        else 0.0
    )
    failure = {
        h: transition_failure_rate(canonical_id, horizon_bars=h)
        for h in _TRANSITION_FAILURE_HORIZONS_BARS
    }

    detection_delay_computable = onset_ts_ms is not None
    detected, delay_ms = (
        _detection_delay_ms(close_time_ms, canonical_id, stress_state_id, onset_ts_ms)
        if onset_ts_ms is not None
        else (False, float("nan"))
    )

    return GateQualitySymbolDetail(
        symbol=symbol,
        n_obs_total=n_obs_total,
        stress_state_id=stress_state_id,
        stress_state_rule=stress_state_rule,
        n_states_present=occ.n_states_present,
        effective_number_of_states=occ.effective_number_of_states,
        stress_state_occupancy=stress_occupancy,
        state_ids=occ.state_ids,
        state_occupancy=occ.occupancy,
        transition_failure_rate_n3=failure[3].failure_rate,
        n_transitions_evaluable_n3=failure[3].n_transitions_evaluable,
        transition_failure_rate_n5=failure[5].failure_rate,
        n_transitions_evaluable_n5=failure[5].n_transitions_evaluable,
        transition_failure_rate_n10=failure[10].failure_rate,
        n_transitions_evaluable_n10=failure[10].n_transitions_evaluable,
        detection_delay_computable=detection_delay_computable,
        detection_delay_detected=detected,
        detection_delay_ms=delay_ms,
        detection_delay_onset_ts_ms=onset_ts_ms,
    )


def _volatility_heterogeneity_for_symbol_window(
    symbol: str,
    canonical_id: m4.IntArray,
    close_time_ms: m4.IntArray,
    forward_realized_vol: m4.FloatArray,
    *,
    n_permutations: int,
    permutation_seed: int,
) -> VolatilityHeterogeneitySymbolDetail:
    """Métrica PRIMÁRIA de ranking de `AG-114` pra 1 (símbolo, janela,
    candidato) -- arrays já JOINADOS (`_join_candidate_with_vol_history`),
    ordenados por tempo (contrato exigido por `permutation_heterogeneity_
    test_continuous`, verificado aqui em runtime, mesma disciplina de
    `_heterogeneity_for_symbol_window`)."""
    n_obs_total = int(canonical_id.shape[0])
    if n_obs_total == 0:
        return VolatilityHeterogeneitySymbolDetail(
            symbol=symbol,
            n_buckets=0,
            n_episodes=0,
            n_obs_total=0,
            pooled_forward_realized_vol=float("nan"),
            q_statistic=float("nan"),
            df=-1,
            p_value=float("nan"),
            i_squared_pct=float("nan"),
            p_value_permutation=float("nan"),
            n_permutations_requested=n_permutations,
            n_permutations_valid=0,
        )
    if not np.all(np.diff(close_time_ms) >= 0):
        raise ValueError(
            f"_volatility_heterogeneity_for_symbol_window({symbol!r}): close_time_ms não "
            "ordenado por tempo -- permutation_heterogeneity_test_continuous exige ordenação "
            "cronológica estrita pra extrair episódio corretamente (AG-092)"
        )

    het = m6.cochrans_q_heterogeneity_continuous(canonical_id, forward_realized_vol)
    perm = m6.permutation_heterogeneity_test_continuous(
        canonical_id, forward_realized_vol, n_permutations=n_permutations, seed=permutation_seed
    )

    return VolatilityHeterogeneitySymbolDetail(
        symbol=symbol,
        n_buckets=het.k,
        n_episodes=perm.n_episodes,
        n_obs_total=n_obs_total,
        pooled_forward_realized_vol=het.pooled_response,
        q_statistic=het.q_statistic,
        df=het.df,
        p_value=het.p_value,
        i_squared_pct=het.i_squared_pct,
        p_value_permutation=perm.p_value,
        n_permutations_requested=n_permutations,
        n_permutations_valid=perm.n_permutations_valid,
    )


def _window_gate_quality_summary(
    window: CriticalWindow, details: tuple[GateQualitySymbolDetail, ...]
) -> GateQualityWindowSummary:
    ok_details = [d for d in details if d.n_obs_total > 0]
    return GateQualityWindowSummary(
        window_name=window.name,
        event=window.event,
        n_symbols_requested=len(window.symbols),
        n_symbols_ok=len(ok_details),
        effective_number_of_states_median=_median_or_nan(
            [d.effective_number_of_states for d in ok_details]
        ),
        stress_state_occupancy_median=_median_or_nan(
            [d.stress_state_occupancy for d in ok_details]
        ),
        transition_failure_rate_n3_median=_median_or_nan(
            [d.transition_failure_rate_n3 for d in ok_details]
        ),
        transition_failure_rate_n5_median=_median_or_nan(
            [d.transition_failure_rate_n5 for d in ok_details]
        ),
        transition_failure_rate_n10_median=_median_or_nan(
            [d.transition_failure_rate_n10 for d in ok_details]
        ),
        detection_delay_ms_median=_median_or_nan([d.detection_delay_ms for d in ok_details]),
        n_symbols_detection_delay_computable=sum(
            1 for d in ok_details if d.detection_delay_computable
        ),
        per_symbol=details,
    )


def _aggregate_gate_quality_for_classifier(
    classifier_id: str,
    baseline_classifier_id: str,
    resolution_id: str,
    windows: tuple[CriticalWindow, ...],
    ok_cells: list[CellOutcome],
    forward_vol_by_symbol: dict[str, _SymbolForwardVolHistory],
    event_onset_ts_ms_by_window: dict[str, int],
) -> AggregatedGateQualityResult:
    """Mesma mediana-de-medianas de `_aggregate_heterogeneity_for_
    classifier` -- reusa `CellOutcome.raw_labels` já coletado (zero fits
    novos) + `forward_vol_by_symbol` já calculado pelo chamador (1x por
    símbolo/resolução, fora do loop de candidato -- ver
    `run_critical_windows_comparison`)."""
    window_summaries: list[GateQualityWindowSummary] = []
    for window in windows:
        onset_ts_ms = event_onset_ts_ms_by_window.get(window.name)
        details: list[GateQualitySymbolDetail] = []
        for symbol in window.symbols:
            cell = next(
                (c for c in ok_cells if c.window_name == window.name and c.symbol == symbol),
                None,
            )
            vol_history = forward_vol_by_symbol.get(symbol)
            regime_raw = (
                cell.raw_labels.get(classifier_id)
                if cell is not None and cell.raw_labels is not None
                else None
            )
            if regime_raw is None or vol_history is None:
                details.append(
                    GateQualitySymbolDetail(
                        symbol=symbol,
                        n_obs_total=0,
                        stress_state_id=-1,
                        stress_state_rule="no_data",
                        n_states_present=0,
                        effective_number_of_states=float("nan"),
                        stress_state_occupancy=float("nan"),
                        state_ids=(),
                        state_occupancy=(),
                        transition_failure_rate_n3=float("nan"),
                        n_transitions_evaluable_n3=0,
                        transition_failure_rate_n5=float("nan"),
                        n_transitions_evaluable_n5=0,
                        transition_failure_rate_n10=float("nan"),
                        n_transitions_evaluable_n10=0,
                        detection_delay_computable=onset_ts_ms is not None,
                        detection_delay_detected=False,
                        detection_delay_ms=float("nan"),
                        detection_delay_onset_ts_ms=onset_ts_ms,
                    )
                )
                continue
            canonical_id, close_time_ms, realized_vol_short, _forward_vol = (
                _join_candidate_with_vol_history(regime_raw, vol_history)
            )
            details.append(
                _gate_quality_for_symbol_window(
                    symbol,
                    classifier_id,
                    baseline_classifier_id,
                    canonical_id,
                    close_time_ms,
                    realized_vol_short,
                    onset_ts_ms=onset_ts_ms,
                )
            )
        window_summaries.append(_window_gate_quality_summary(window, tuple(details)))

    ok_summaries = [w for w in window_summaries if w.n_symbols_ok > 0]
    return AggregatedGateQualityResult(
        classifier_id=classifier_id,
        resolution_id=resolution_id,
        n_windows_requested=len(window_summaries),
        n_windows_ok=len(ok_summaries),
        effective_number_of_states_median=_median_or_nan(
            [w.effective_number_of_states_median for w in ok_summaries]
        ),
        stress_state_occupancy_median=_median_or_nan(
            [w.stress_state_occupancy_median for w in ok_summaries]
        ),
        transition_failure_rate_n3_median=_median_or_nan(
            [w.transition_failure_rate_n3_median for w in ok_summaries]
        ),
        transition_failure_rate_n5_median=_median_or_nan(
            [w.transition_failure_rate_n5_median for w in ok_summaries]
        ),
        transition_failure_rate_n10_median=_median_or_nan(
            [w.transition_failure_rate_n10_median for w in ok_summaries]
        ),
        detection_delay_ms_median=_median_or_nan(
            [w.detection_delay_ms_median for w in ok_summaries]
        ),
        n_windows_detection_delay_computable=sum(
            1 for w in ok_summaries if w.n_symbols_detection_delay_computable > 0
        ),
        per_window=tuple(window_summaries),
    )


def _window_volatility_heterogeneity_summary(
    window: CriticalWindow, details: tuple[VolatilityHeterogeneitySymbolDetail, ...]
) -> VolatilityHeterogeneityWindowSummary:
    ok_details = [d for d in details if d.n_buckets > 0]
    return VolatilityHeterogeneityWindowSummary(
        window_name=window.name,
        event=window.event,
        n_symbols_requested=len(window.symbols),
        n_symbols_ok=len(ok_details),
        i_squared_pct_median=_median_or_nan([d.i_squared_pct for d in ok_details]),
        p_value_permutation_median=_median_or_nan(
            [d.p_value_permutation for d in ok_details]
        ),
        per_symbol=details,
    )


def _aggregate_volatility_heterogeneity_for_classifier(
    classifier_id: str,
    resolution_id: str,
    windows: tuple[CriticalWindow, ...],
    ok_cells: list[CellOutcome],
    forward_vol_by_symbol: dict[str, _SymbolForwardVolHistory],
    *,
    n_permutations: int,
    permutation_seed: int,
) -> AggregatedVolatilityHeterogeneityResult:
    window_summaries: list[VolatilityHeterogeneityWindowSummary] = []
    for window in windows:
        details: list[VolatilityHeterogeneitySymbolDetail] = []
        for symbol in window.symbols:
            cell = next(
                (c for c in ok_cells if c.window_name == window.name and c.symbol == symbol),
                None,
            )
            vol_history = forward_vol_by_symbol.get(symbol)
            regime_raw = (
                cell.raw_labels.get(classifier_id)
                if cell is not None and cell.raw_labels is not None
                else None
            )
            if regime_raw is None or vol_history is None:
                details.append(
                    VolatilityHeterogeneitySymbolDetail(
                        symbol=symbol,
                        n_buckets=0,
                        n_episodes=0,
                        n_obs_total=0,
                        pooled_forward_realized_vol=float("nan"),
                        q_statistic=float("nan"),
                        df=-1,
                        p_value=float("nan"),
                        i_squared_pct=float("nan"),
                        p_value_permutation=float("nan"),
                        n_permutations_requested=n_permutations,
                        n_permutations_valid=0,
                    )
                )
                continue
            canonical_id, close_time_ms, _realized_vol, forward_vol = (
                _join_candidate_with_vol_history(regime_raw, vol_history)
            )
            details.append(
                _volatility_heterogeneity_for_symbol_window(
                    symbol,
                    canonical_id,
                    close_time_ms,
                    forward_vol,
                    n_permutations=n_permutations,
                    permutation_seed=permutation_seed,
                )
            )
        window_summaries.append(_window_volatility_heterogeneity_summary(window, tuple(details)))

    ok_summaries = [w for w in window_summaries if w.n_symbols_ok > 0]
    return AggregatedVolatilityHeterogeneityResult(
        classifier_id=classifier_id,
        resolution_id=resolution_id,
        n_windows_requested=len(window_summaries),
        n_windows_ok=len(ok_summaries),
        i_squared_pct_median=_median_or_nan([w.i_squared_pct_median for w in ok_summaries]),
        p_value_permutation_median=_median_or_nan(
            [w.p_value_permutation_median for w in ok_summaries]
        ),
        per_window=tuple(window_summaries),
    )


def aggregate_critical_windows_results(
    resolution_id: str,
    cells: tuple[CellOutcome, ...],
    *,
    windows: tuple[CriticalWindow, ...] = CRITICAL_WINDOWS,
    labels_by_symbol: dict[str, pl.DataFrame] | None = None,
    tp_atr_mult: float | None = None,
    sl_atr_mult: float | None = None,
    maker_fee: float | None = None,
    taker_fee: float | None = None,
    n_permutations: int | None = None,
    permutation_seed: int | None = None,
    forward_vol_by_symbol: dict[str, _SymbolForwardVolHistory] | None = None,
    event_onset_ts_ms_by_window: dict[str, int] | None = None,
) -> CriticalWindowsReport:
    """Núcleo quase-puro (SEM IO própria -- `labels_by_symbol` é
    INJETADO pelo chamador, já carregado; esta função só agrega o que
    recebeu, mesmo espírito de `CellOutcome` já vir pronto) -- recebe
    `CellOutcome` já calculados (de `run_critical_windows_comparison` ou
    de um teste com fixture sintética) e produz `CriticalWindowsReport`.

    `forward_vol_by_symbol`/`event_onset_ts_ms_by_window` -- extensão de
    qualidade-de-gate (AG-114, 2026-08-20). `forward_vol_by_symbol=None`
    (default) preserva o contrato exato de antes -- `gate_quality=()`,
    `volatility_heterogeneity=()`. Passar `forward_vol_by_symbol` ativa
    os 2 blocos novos pra cada `classifier_id` descoberto -- exige
    `n_permutations`/`permutation_seed` também (reusa o MESMO teste de
    permutação em bloco que a heterogeneidade TP/SL, generalizado pra
    resposta contínua). `event_onset_ts_ms_by_window` é opcional mesmo
    com `forward_vol_by_symbol` ativo -- ausente/vazio só desativa Gate 3
    (detection delay) por janela, nunca os outros 2 gates + métrica
    primária (`{}`/`None` tratados igual, "nenhuma janela tem onset
    conhecido").

    AG-019: células com `error is not None` viram `FailedCell`; células
    com `symbol_result is None, error is None` viram `SkippedCell`;
    nenhuma das duas classes participa da agregação (mediana só sobre
    células OK) -- mas ambas ficam listadas no relatório, nunca
    escondidas.

    `labels_by_symbol=None` (default) preserva o contrato exato de antes
    da adição do G-C1-2 revisado -- `heterogeneity=()`, nenhum teste
    novo roda, TODOS os testes/chamadores existentes continuam
    funcionando sem alteração. Passar `labels_by_symbol` (+ os 4
    multiplicadores/fees + `n_permutations`/`permutation_seed`, AG-092 --
    7 no total, todos obrigatórios juntos -- `ValueError` se só parte for
    passada) ativa o cálculo de Cochran's Q/I² + teste de permutação em
    bloco (`heterogeneity`) pra cada `classifier_id` descoberto, nos 2
    lados."""
    # Achado real desta sessão (rodando a suíte pela 1ª vez): a checagem
    # original agrupava n_permutations/permutation_seed DENTRO do grupo
    # "tudo ou nada" da heterogeneidade TP/SL -- mas AG-114 passou a
    # reusar os 2 pra volatility_heterogeneity TAMBÉM, independente de
    # labels_by_symbol estar ativo. Um chamador que só quer gate_quality/
    # volatility_heterogeneity (forward_vol_by_symbol, sem labels_by_
    # symbol) levantava ValueError incorretamente -- corrigido separando
    # os 2 grupos: (a) os 5 campos exclusivos da heterogeneidade TP/SL
    # continuam "tudo ou nada" entre si; (b) n_permutations/permutation_
    # seed são exigidos se QUALQUER UM dos 2 blocos (TP/SL OU gate-
    # quality/volatilidade) estiver ativo, não amarrados a um só.
    tp_sl_heterogeneity_params = (tp_atr_mult, sl_atr_mult, maker_fee, taker_fee)
    if labels_by_symbol is not None and any(p is None for p in tp_sl_heterogeneity_params):
        raise ValueError(
            "aggregate_critical_windows_results: labels_by_symbol exige tp_atr_mult/"
            "sl_atr_mult/maker_fee/taker_fee também -- G-C1-2 revisado exige os 5 pra "
            "computar heterogeneidade TP/SL (Cochran's Q/I², AG-092), ativação parcial "
            "seria silenciosamente incompleta"
        )
    if labels_by_symbol is None and any(p is not None for p in tp_sl_heterogeneity_params):
        raise ValueError(
            "aggregate_critical_windows_results: tp_atr_mult/sl_atr_mult/maker_fee/"
            "taker_fee só fazem sentido junto de labels_by_symbol (heterogeneidade TP/SL)"
        )
    if (labels_by_symbol is not None or forward_vol_by_symbol is not None) and (
        n_permutations is None or permutation_seed is None
    ):
        raise ValueError(
            "aggregate_critical_windows_results: n_permutations/permutation_seed exigidos "
            "quando labels_by_symbol OU forward_vol_by_symbol está ativo -- reusados pelos 2 "
            "testes de permutação em bloco (heterogeneidade TP/SL e volatilidade contínua, "
            "AG-092/AG-114)"
        )
    failed = tuple(
        FailedCell(
            window_name=c.window_name,
            symbol=c.symbol,
            resolution_id=c.resolution_id,
            error=c.error,
        )
        for c in cells
        if c.error is not None
    )
    skipped = tuple(
        SkippedCell(
            window_name=c.window_name,
            symbol=c.symbol,
            resolution_id=c.resolution_id,
            reason="folds_insuficientes",
        )
        for c in cells
        if c.error is None and c.symbol_result is None
    )
    ok_cells = [c for c in cells if c.error is None and c.symbol_result is not None]

    baseline_classifier_id, candidate_ids = _collect_classifier_ids(ok_cells)

    baseline_agg = _aggregate_one_candidate(
        baseline_classifier_id, resolution_id, windows, ok_cells, _baseline_getter
    )
    candidates_agg = tuple(
        _aggregate_one_candidate(
            classifier_id,
            resolution_id,
            windows,
            ok_cells,
            _make_candidate_getter(classifier_id),
        )
        for classifier_id in candidate_ids
    )
    # Q3 (Terceira via) -- mesmo conjunto/ordem de classifier_id que
    # baseline+candidates (baseline primeiro), custo zero (ver docstring
    # de Q3AggregatedResult) -- pronta assim que uma execução real rodar,
    # não precisa de nenhum parâmetro/flag novo em run_and_save_
    # critical_windows_report.
    #
    # AG-019 reaplicado aqui, achado real (Fase D re-run, 2026-08-18): um
    # bug na agregação de heterogeneidade (dtype de datetime) derrubou a
    # resolução INTEIRA depois de ~2h de fit real de HMM/Jump Model já
    # concluído -- baseline/candidates já estavam prontos em memória, mas
    # nada foi persistido porque a exceção propagou até fora desta função,
    # sem checkpoint. Q3/heterogeneidade são camadas ADICIONAIS sobre o
    # que já foi computado (baseline_agg/candidates_agg) -- uma exceção
    # nelas nunca deveria destruir o que já é conhecido bom; cada uma
    # isolada em seu próprio try/except, resultado parcial explícito
    # (tupla vazia) em vez de propagar.
    try:
        q3_agg = tuple(
            _aggregate_q3_for_classifier(classifier_id, resolution_id, windows, ok_cells)
            for classifier_id in (baseline_classifier_id, *candidate_ids)
        )
    except Exception as exc:
        logger.error(
            "analysis.m4_critical_windows.q3_aggregation_failed",
            resolution_id=resolution_id,
            error=repr(exc),
        )
        q3_agg = ()

    heterogeneity_agg: tuple[AggregatedHeterogeneityResult, ...] = ()
    if labels_by_symbol is not None:
        assert tp_atr_mult is not None  # guard acima já garantiu os 7 juntos
        assert sl_atr_mult is not None
        assert maker_fee is not None
        assert taker_fee is not None
        assert n_permutations is not None
        assert permutation_seed is not None
        try:
            heterogeneity_agg = tuple(
                _aggregate_heterogeneity_for_classifier(
                    classifier_id,
                    resolution_id,
                    side,
                    windows,
                    ok_cells,
                    labels_by_symbol,
                    tp_atr_mult=tp_atr_mult,
                    sl_atr_mult=sl_atr_mult,
                    maker_fee=maker_fee,
                    taker_fee=taker_fee,
                    n_permutations=n_permutations,
                    permutation_seed=permutation_seed,
                )
                for classifier_id in (baseline_classifier_id, *candidate_ids)
                for side in (1, -1)
            )
        except Exception as exc:
            logger.error(
                "analysis.m4_critical_windows.heterogeneity_aggregation_failed",
                resolution_id=resolution_id,
                error=repr(exc),
            )
            heterogeneity_agg = ()

    # Qualidade-de-gate (AG-114, 2026-08-20) -- mesmo padrão de isolamento
    # de falha em 2 blocos independentes que heterogeneity_agg acima (uma
    # exceção num bloco nunca destrói baseline_agg/candidates_agg/
    # q3_agg/heterogeneity_agg já computados).
    gate_quality_agg: tuple[AggregatedGateQualityResult, ...] = ()
    volatility_heterogeneity_agg: tuple[AggregatedVolatilityHeterogeneityResult, ...] = ()
    if forward_vol_by_symbol is not None:
        if n_permutations is None or permutation_seed is None:
            raise ValueError(
                "aggregate_critical_windows_results: forward_vol_by_symbol exige "
                "n_permutations/permutation_seed também (AG-114) -- volatility_heterogeneity "
                "reusa o mesmo teste de permutação em bloco que a heterogeneidade TP/SL"
            )
        onset_by_window = event_onset_ts_ms_by_window or {}
        try:
            gate_quality_agg = tuple(
                _aggregate_gate_quality_for_classifier(
                    classifier_id,
                    baseline_classifier_id,
                    resolution_id,
                    windows,
                    ok_cells,
                    forward_vol_by_symbol,
                    onset_by_window,
                )
                for classifier_id in (baseline_classifier_id, *candidate_ids)
            )
        except Exception as exc:
            logger.error(
                "analysis.m4_critical_windows.gate_quality_aggregation_failed",
                resolution_id=resolution_id,
                error=repr(exc),
            )
            gate_quality_agg = ()
        try:
            volatility_heterogeneity_agg = tuple(
                _aggregate_volatility_heterogeneity_for_classifier(
                    classifier_id,
                    resolution_id,
                    windows,
                    ok_cells,
                    forward_vol_by_symbol,
                    n_permutations=n_permutations,
                    permutation_seed=permutation_seed,
                )
                for classifier_id in (baseline_classifier_id, *candidate_ids)
            )
        except Exception as exc:
            logger.error(
                "analysis.m4_critical_windows.volatility_heterogeneity_aggregation_failed",
                resolution_id=resolution_id,
                error=repr(exc),
            )
            volatility_heterogeneity_agg = ()

    return CriticalWindowsReport(
        resolution_id=resolution_id,
        baseline=baseline_agg,
        candidates=candidates_agg,
        failed_cells=failed,
        skipped_cells=skipped,
        q3=q3_agg,
        heterogeneity=heterogeneity_agg,
        gate_quality=gate_quality_agg,
        volatility_heterogeneity=volatility_heterogeneity_agg,
    )


# ============================================================================
# AG-084 -- BOCPD sobre o histórico causal COMPLETO do símbolo, não
# fatiado por janela crítica (que resetava o prior bayesiano a cada
# janela -- achado real, reproduzido: mesma janela ETF_HALVING vai de
# persistência mediana 2 barras (fatiado) pra 450+ barras (contínuo) com
# o MESMO hazard_lambda). HMM/Jump Model continuam vindo do cálculo por
# janela (_run_one_cell) sem alteração -- só eles são refit por fold, o
# corte por janela é a unidade certa pra eles; BOCPD é o único candidato
# que precisa de série causal ÚNICA, ininterrupta.
# ============================================================================


def _iso_date_to_epoch_ms(iso_date: str) -> int:
    """`CriticalWindow.start`/`.end` são strings `"YYYY-MM-DD"` -- convertidas
    aqui pra epoch ms UTC (`replace(tzinfo=dt.UTC)` explícito, nunca hora
    local, mesma disciplina de timestamp do resto do projeto)."""
    return int(dt.datetime.fromisoformat(iso_date).replace(tzinfo=dt.UTC).timestamp() * 1000)


@dataclass(frozen=True, slots=True)
class _BocpdFullHistory:
    """5 arrays alinhados por POSIÇÃO, cobrindo o histórico causal
    COMPLETO do símbolo (`m4.SYMBOL_START_DATE[symbol]` -> `m4.END_DATE`)
    -- fatiado por janela crítica depois, em `_bocpd_metrics_for_window`,
    nunca refeito por janela.

    `close_time_ms` -- adicionado 2026-08-19 (AG-090, mesmo achado de
    `m4.RawLabels`): o filtro de pertencimento à janela crítica em
    `_bocpd_metrics_for_window` usa `close_time_ms`, não `open_time_ms`
    -- uma barra só está "dentro" do período coberto pela janela quando
    ela FECHA dentro dele, consistente com `RawLabels.close_time_ms` ser
    o timestamp de referência em todo `join_asof` causal deste módulo."""

    open_time_ms: m4.IntArray
    close_time_ms: m4.IntArray
    canonical_id: m4.IntArray
    forward_return: m4.FloatArray
    vol_pctile: m4.FloatArray


def _compute_bocpd_full_history(
    symbol: str,
    resolution_id: str,
    *,
    hazard_lambda: float,
    n_canonical_buckets: int,
) -> _BocpdFullHistory:
    """AG-084 -- roda BOCPD 1x sobre TODO o histórico causal do símbolo,
    mesma mecânica de carga/trim de `m4.compare_regime_candidates_for_
    symbol` (reusa os helpers PRIVADOS `m4._input_obs`/`m4._valid_start_
    idx`/`m4._forward_return` -- mesma fórmula exata, não uma
    reimplementação) mas SÓ a parte de BOCPD (HMM/Jump Model continuam
    vindo do cálculo por janela -- refazê-los sobre o histórico completo
    aqui seria refit redundante e caro, sem necessidade -- só BOCPD
    precisa da série contínua)."""
    throttle = lake.DuckDBThrottle(
        memory_limit_gb=float(load_data_constant("m4_duckdb_memory_limit_gb")),
        threads=int(load_data_constant("m4_duckdb_threads")),
    )
    start = m4.SYMBOL_START_DATE[symbol]
    end = m4.END_DATE
    bars_df = lake.query_dollar_bars(
        symbol,
        start,
        end,
        resolution_id=resolution_id,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    baseline_df = build_regimes(symbol, start, end, bar_source=f"dollar_{resolution_id.lower()}")
    m4._assert_bars_baseline_aligned(bars_df, baseline_df, symbol=symbol)

    log_return_1_full, obs_2d_full = m4._input_obs(bars_df)
    valid_start_idx = m4._valid_start_idx(log_return_1_full, obs_2d_full[:, 1])
    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()[valid_start_idx:]
    close_time_ms = bars_df["close_time"].cast(pl.Int64).to_numpy()[valid_start_idx:]
    log_return_1 = log_return_1_full[valid_start_idx:]
    forward_return = m4._forward_return(log_return_1)
    vol_pctile = baseline_df["vol_pctile"].cast(pl.Float64).to_numpy()[valid_start_idx:]

    logger.info(
        "analysis.m4_critical_windows.bocpd_full_history_bars_loaded",
        symbol=symbol,
        resolution_id=resolution_id,
        n_bars=int(log_return_1.shape[0]),
    )

    bocpd_out = run_bocpd(log_return_1, hazard_lambda=hazard_lambda)
    bucket_by_bar = segments_to_canonical_states(
        bocpd_out.segment_id, log_return_1, n_buckets=n_canonical_buckets
    )
    canonical_id = canonicalize_states(bucket_by_bar, log_return_1).canonical_id

    return _BocpdFullHistory(
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        canonical_id=canonical_id,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
    )


def _bocpd_metrics_for_window(
    oos_start_ms: int, oos_end_ms: int, full: _BocpdFullHistory, n_canonical_buckets: int
) -> tuple[m4.CandidateResult, m4.RawLabels]:
    """Fatia `full` (histórico completo já rodado 1x, ver `_compute_bocpd_
    full_history`) pro período `[oos_start_ms, oos_end_ms)` por
    TIMESTAMP (nunca por fold de walk-forward -- BOCPD não tem
    treino/teste nesse desenho, o fit inteiro já é causal por
    construção, então toda barra do período é OOS válida por definição,
    mesmo espírito de `fold_stability_by_construction=True` já usado
    antes) e calcula as métricas de comparação (mesmas 3 de sempre)
    sobre essa fatia.

    **`[oos_start_ms, oos_end_ms)`, não `[window.start, window.end)` --
    corrigido 2026-08-19 (AG-093, `audit/architecture_gaps_log.yaml`).**
    A versão anterior (AG-084) avaliava o BOCPD sobre a JANELA CRÍTICA
    INTEIRA (~15 meses de calendário) em vez do slice OOS que os outros
    5 candidatos usam (~1 trimestre, `SymbolResult.oos_start_ms`/`.
    oos_end_ms` -- ver docstring de `SymbolResult` em `m4_regime_
    comparison.py`) -- violava o princípio de desenho original do
    próprio módulo ("mesma janela temporal que HMM/Jump Model/baseline,
    pra comparação justa"). Reprodução real confirmou amostra ~5x maior
    pro BOCPD numa mesma célula, inflando artificialmente seu Cochran's
    Q/I² (I² aumenta com precisão amostral a heterogeneidade real
    constante) -- principal fator medido por trás da liderança suspeita
    do BOCPD sob a métrica nova. `oos_start_ms`/`oos_end_ms` chegam
    prontos do `SymbolResult` da MESMA célula (calculados 1x dentro do
    walk-forward ancorado que já roda pra HMM/Jump Model/baseline,
    nenhuma IO/fit adicional) -- caller (`run_critical_windows_
    comparison`) repassa `outcome.symbol_result.oos_start_ms`/`.
    oos_end_ms`, nunca mais deriva de `window.start`/`window.end`.

    **Filtro por `close_time_ms`, não `open_time_ms` -- 2026-08-19
    (AG-090):** uma barra só pertence de fato ao período quando ela
    FECHA dentro dele -- mesma disciplina causal de `RawLabels.
    close_time_ms`."""
    mask = (full.close_time_ms >= oos_start_ms) & (full.close_time_ms < oos_end_ms)

    labels_window = full.canonical_id[mask]
    open_time_window = full.open_time_ms[mask]
    close_time_window = full.close_time_ms[mask]
    forward_return_window = full.forward_return[mask]
    vol_pctile_window = full.vol_pctile[mask]

    separation = m4._anova_or_degenerate(labels_window, forward_return_window)
    orthogonality = m4._anova_or_degenerate(labels_window, vol_pctile_window)
    persistence = m4._persistence_or_degenerate(labels_window)

    result = m4.CandidateResult(
        classifier_id=m4.BOCPD_CLASSIFIER_ID,
        n_states=n_canonical_buckets,
        separation=separation,
        orthogonality=orthogonality,
        persistence=persistence,
        fold_stability_adjusted_rand_mean=1.0,
        fold_stability_adjusted_rand_min=1.0,
        fold_stability_by_construction=True,
        n_oos_obs=separation.n,
        n_folds_evaluated=0,
    )
    raw_labels = m4.RawLabels(
        open_time_ms=open_time_window, close_time_ms=close_time_window, canonical_id=labels_window
    )
    return result, raw_labels


def _replace_bocpd_candidate(
    symbol_result: m4.SymbolResult,
    raw_labels: dict[str, m4.RawLabels] | None,
    corrected_result: m4.CandidateResult,
    corrected_raw: m4.RawLabels,
) -> tuple[m4.SymbolResult, dict[str, m4.RawLabels] | None]:
    """Substitui o `CandidateResult`/`RawLabels` do BOCPD (calculado por
    `_run_one_cell` de forma fatiada por janela, com o bug AG-084) pelo
    calculado sobre o histórico completo (`_bocpd_metrics_for_window`).
    Os outros 5 candidatos (baseline + HMM x3 + Jump Model) em
    `symbol_result.candidates`/`symbol_result.baseline` continuam
    INTOCADOS -- só o slot de `classifier_id == BOCPD_CLASSIFIER_ID` é
    trocado. Dataclasses `frozen`, por isso `dataclasses.replace` em vez
    de mutação."""
    new_candidates = tuple(
        corrected_result if c.classifier_id == m4.BOCPD_CLASSIFIER_ID else c
        for c in symbol_result.candidates
    )
    new_symbol_result = replace(symbol_result, candidates=new_candidates)
    new_raw_labels = None
    if raw_labels is not None:
        new_raw_labels = dict(raw_labels)
        new_raw_labels[m4.BOCPD_CLASSIFIER_ID] = corrected_raw
    return new_symbol_result, new_raw_labels


# ============================================================================
# Orquestração com IO -- 1 resolução, todas as janelas/símbolos válidos
# ============================================================================


def _iter_cells(windows: tuple[CriticalWindow, ...]) -> Iterator[tuple[CriticalWindow, str]]:
    for window in windows:
        for symbol in window.symbols:
            yield window, symbol


def _run_one_cell(
    window: CriticalWindow,
    symbol: str,
    resolution_id: str,
    *,
    initial_train_years: int,
    hmm_states_grid: tuple[int, ...],
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int,
    jump_seed: int,
) -> CellOutcome:
    """Roda `m4.run_regime_comparison_for_symbol` pra 1 célula (janela,
    símbolo, resolução) -- AG-019: qualquer exceção vira `CellOutcome.
    error`, nunca propaga (isolamento de falha por célula). Função
    module-level (não closure/lambda) -- precisa ser PICKLABLE pra
    `ProcessPoolExecutor(mp_context="spawn")` submeter em processo
    filho.

    `return_raw_labels=True` sempre (literal, não repassado) -- mesmo
    motivo/custo de `m4.compare_regime_candidates_for_symbol` (a função
    interna SEMPRE calcula os rótulos brutos, expor custa só o
    fatiamento já feito, nunca um refit) -- alimenta a agregação de Q3
    (`Q3AggregatedResult`) sem exigir nenhuma célula/fit adicional.

    **`include_jump_model = (symbol == "BTCUSDT")` -- AG-117, 2026-08-20
    (decisão do Manager).** Experimento de transferibilidade de λ
    (`audit/architecture_gaps_log.yaml::AG-117`) mostrou que Jump Model
    não tem estrutura de 2 regimes detectável em NENHUM ponto de grid
    testado pra SOLUSDT/BNBUSDT/XRPUSDT (mesmo in-sample), e recalibrar
    λ pra ETHUSDT (único não-BTC com λ genuíno no grid) piora ou empata
    a saturação nas janelas críticas -- nunca melhora. BTC continua
    elegível (`m4_jump_model_penalty=0,002` é seu próprio λ local, nunca
    transplantado). Economiza ~1/4 do tempo de fit por célula não-BTC
    (Jump Model é 1 dos 4 candidatos que passam por refit por fold)."""
    include_jump_model = symbol == "BTCUSDT"
    try:
        result = m4.run_regime_comparison_for_symbol(
            symbol,
            window.start,
            window.end,
            initial_train_years=initial_train_years,
            resolution_id=resolution_id,
            hmm_states_grid=hmm_states_grid,
            jump_n_states=jump_n_states,
            jump_penalty=jump_penalty,
            bocpd_hazard_lambda=bocpd_hazard_lambda,
            bocpd_n_canonical_buckets=bocpd_n_canonical_buckets,
            hmm_seed=hmm_seed,
            jump_seed=jump_seed,
            include_jump_model=include_jump_model,
            return_raw_labels=True,
        )
    except Exception as exc:  # AG-019 -- 1 célula falhando não derruba as outras
        logger.error(
            "analysis.m4_critical_windows.cell_failed",
            window=window.name,
            symbol=symbol,
            resolution_id=resolution_id,
            error=repr(exc),
        )
        return CellOutcome(window.name, symbol, resolution_id, None, repr(exc), None)
    if result is None:
        logger.warning(
            "analysis.m4_critical_windows.cell_folds_insuficientes",
            window=window.name,
            symbol=symbol,
            resolution_id=resolution_id,
        )
        return CellOutcome(window.name, symbol, resolution_id, None, None, None)
    symbol_result, raw_labels = result
    return CellOutcome(window.name, symbol, resolution_id, symbol_result, None, raw_labels)


def run_critical_windows_comparison(
    resolution_id: str,
    *,
    windows: tuple[CriticalWindow, ...] = CRITICAL_WINDOWS,
    initial_train_years: int = 1,
    hmm_states_grid: tuple[int, ...] = (2, 3, 4),
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = 0,
    jump_seed: int = 0,
    max_workers: int | None = None,
    labels_by_symbol: dict[str, pl.DataFrame] | None = None,
    tp_atr_mult: float | None = None,
    sl_atr_mult: float | None = None,
    maker_fee: float | None = None,
    taker_fee: float | None = None,
    n_permutations: int | None = None,
    permutation_seed: int | None = None,
    compute_gate_quality: bool = False,
    event_onset_ts_ms_by_window: dict[str, int] | None = None,
    persist_raw_labels: bool = False,
) -> CriticalWindowsReport:
    """1 resolução completa -- todas as células (janela, símbolo) de
    `windows`, agregadas. `max_workers=1` roda SEQUENCIAL (mesma função
    `_run_one_cell`, sem `ProcessPoolExecutor`) -- usado pelos testes
    (`monkeypatch` em `m4.run_regime_comparison_for_symbol` não alcança
    processos filhos gerados via `spawn`, então o caminho testável é o
    sequencial). `max_workers=None` (default) usa `os.cpu_count()`,
    mesma convenção de `m4_regime_comparison.run_and_save_m4_report`.

    `compute_gate_quality=False` (default NESTA função de nível baixo --
    o default `True` fica em `run_and_save_critical_windows_report`,
    mesma assimetria já existente entre `labels_by_symbol=None` aqui vs.
    `compute_heterogeneity=True` lá) -- AG-114, 2026-08-20. Quando
    `True`, calcula `_SymbolForwardVolHistory` 1x por símbolo (união dos
    símbolos de `windows`), mesmo padrão sequencial/paralelo do bloco
    BOCPD logo abaixo, e repassa pra `aggregate_critical_windows_results`
    via `forward_vol_by_symbol` -- ativa `gate_quality`/
    `volatility_heterogeneity` no relatório. `n_permutations`/
    `permutation_seed` (já parâmetros desta função) são reusados pro
    teste de permutação contínuo -- exigidos se `compute_gate_quality=
    True`, mesma checagem em `aggregate_critical_windows_results`.

    **Custo não medido nesta fase** (Fase D, execução real de 18 trials,
    autorização separada do Manager) -- só smoke test de 1-2 células. Ver
    docstring do módulo, seção "Paralelismo", pro raciocínio de não
    aninhar `ProcessPoolExecutor` entre resoluções.

    `labels_by_symbol`/`tp_atr_mult`/`sl_atr_mult`/`maker_fee`/`taker_fee`/
    `n_permutations`/`permutation_seed` -- repassados direto pra
    `aggregate_critical_windows_results` (G-C1-2 revisado, Cochran's Q/I²
    + permutação em bloco, AG-092). `None` (default) preserva o contrato
    de antes, `heterogeneity=()`.

    **AG-084**: antes das células, roda `_compute_bocpd_full_history` 1x
    por símbolo (união de todos os símbolos de `windows`) -- BOCPD sobre
    a série causal COMPLETA, nunca fatiada por janela. Depois que as
    células (janela, símbolo) terminam (HMM/Jump Model/baseline, cálculo
    por janela sem alteração), o BOCPD de cada célula OK é SUBSTITUÍDO
    pelo fatiado do histórico completo (`_bocpd_metrics_for_window`) --
    símbolo sem full-history disponível (falha isolada, AG-019) mantém o
    BOCPD fatiado por janela como fallback, nunca derruba a célula.

    **AG-093, 2026-08-19**: o fatiamento de `_bocpd_metrics_for_window`
    usa `outcome.symbol_result.oos_start_ms`/`.oos_end_ms` (fronteira do
    MESMO walk-forward ancorado que HMM/Jump Model/baseline já usaram
    pra essa célula) -- nunca mais `[window.start, window.end)`, que
    dava ao BOCPD ~5x mais amostra que os outros 5 candidatos na mesma
    célula, inflando artificialmente seu Cochran's Q/I².

    `persist_raw_labels=False` (default) -- quando `True`, grava em disco
    (B29, `_write_parquet_atomic`) o `CellOutcome.raw_labels` de toda
    célula OK (`_persist_raw_labels`, `experiments/m4_raw_labels/`) e,
    se `compute_gate_quality=True` também, o `_SymbolForwardVolHistory`
    de cada símbolo (`_persist_forward_vol_history`, `experiments/
    m4_forward_vol_history/`) -- follow-up de AG-114 (2026-08-20): elimina
    a necessidade de re-rodar o fit completo (~3h) toda vez que uma
    métrica nova precisar do mesmo rótulo bruto/observável causal."""
    all_symbols = tuple(sorted({symbol for w in windows for symbol in w.symbols}))
    bocpd_full_by_symbol: dict[str, _BocpdFullHistory] = {}
    if max_workers == 1:
        for symbol in all_symbols:
            try:
                bocpd_full_by_symbol[symbol] = _compute_bocpd_full_history(
                    symbol,
                    resolution_id,
                    hazard_lambda=bocpd_hazard_lambda,
                    n_canonical_buckets=bocpd_n_canonical_buckets,
                )
            except Exception as exc:  # AG-019 -- 1 símbolo falhando não derruba os outros
                logger.error(
                    "analysis.m4_critical_windows.bocpd_full_history_failed",
                    symbol=symbol,
                    resolution_id=resolution_id,
                    error=repr(exc),
                )
    else:
        bocpd_workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
        mp_context_bocpd = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=min(bocpd_workers, len(all_symbols)), mp_context=mp_context_bocpd
        ) as executor:
            bocpd_future_to_symbol = {
                executor.submit(
                    _compute_bocpd_full_history,
                    symbol,
                    resolution_id,
                    hazard_lambda=bocpd_hazard_lambda,
                    n_canonical_buckets=bocpd_n_canonical_buckets,
                ): symbol
                for symbol in all_symbols
            }
            for bocpd_future in iter_completed_with_heartbeat(
                bocpd_future_to_symbol,
                event_prefix="analysis.m4_critical_windows.bocpd_full_history",
                heartbeat_s=float(load_data_constant("ag071_process_pool_heartbeat_s")),
                resolution_id=resolution_id,
            ):
                symbol = bocpd_future_to_symbol[bocpd_future]
                try:
                    bocpd_full_by_symbol[symbol] = bocpd_future.result()
                except Exception as exc:
                    logger.error(
                        "analysis.m4_critical_windows.bocpd_full_history_failed",
                        symbol=symbol,
                        resolution_id=resolution_id,
                        error=repr(exc),
                    )
    logger.info(
        "analysis.m4_critical_windows.bocpd_full_history_done",
        resolution_id=resolution_id,
        n_symbols_requested=len(all_symbols),
        n_symbols_ok=len(bocpd_full_by_symbol),
    )

    # AG-114, 2026-08-20 -- mesmo padrão sequencial/paralelo do bloco
    # BOCPD acima, computação independente (não roda BOCPD, só extrai o
    # observável realized_vol_short/forward_realized_vol, candidato-
    # independente).
    forward_vol_by_symbol: dict[str, _SymbolForwardVolHistory] = {}
    if compute_gate_quality:
        if max_workers == 1:
            for symbol in all_symbols:
                try:
                    forward_vol_by_symbol[symbol] = _compute_symbol_forward_vol_history(
                        symbol, resolution_id
                    )
                except Exception as exc:  # AG-019 -- 1 símbolo falhando não derruba os outros
                    logger.error(
                        "analysis.m4_critical_windows.forward_vol_history_failed",
                        symbol=symbol,
                        resolution_id=resolution_id,
                        error=repr(exc),
                    )
        else:
            vol_workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
            mp_context_vol = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=min(vol_workers, len(all_symbols)), mp_context=mp_context_vol
            ) as executor:
                vol_future_to_symbol = {
                    executor.submit(
                        _compute_symbol_forward_vol_history, symbol, resolution_id
                    ): symbol
                    for symbol in all_symbols
                }
                for vol_future in iter_completed_with_heartbeat(
                    vol_future_to_symbol,
                    event_prefix="analysis.m4_critical_windows.forward_vol_history",
                    heartbeat_s=float(load_data_constant("ag071_process_pool_heartbeat_s")),
                    resolution_id=resolution_id,
                ):
                    symbol = vol_future_to_symbol[vol_future]
                    try:
                        forward_vol_by_symbol[symbol] = vol_future.result()
                    except Exception as exc:
                        logger.error(
                            "analysis.m4_critical_windows.forward_vol_history_failed",
                            symbol=symbol,
                            resolution_id=resolution_id,
                            error=repr(exc),
                        )
        logger.info(
            "analysis.m4_critical_windows.forward_vol_history_done",
            resolution_id=resolution_id,
            n_symbols_requested=len(all_symbols),
            n_symbols_ok=len(forward_vol_by_symbol),
        )

    cells_spec = list(_iter_cells(windows))
    outcomes: list[CellOutcome] = []

    if max_workers == 1:
        for window, symbol in cells_spec:
            outcomes.append(
                _run_one_cell(
                    window,
                    symbol,
                    resolution_id,
                    initial_train_years=initial_train_years,
                    hmm_states_grid=hmm_states_grid,
                    jump_n_states=jump_n_states,
                    jump_penalty=jump_penalty,
                    bocpd_hazard_lambda=bocpd_hazard_lambda,
                    bocpd_n_canonical_buckets=bocpd_n_canonical_buckets,
                    hmm_seed=hmm_seed,
                    jump_seed=jump_seed,
                )
            )
    else:
        workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
        mp_context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp_context) as executor:
            future_to_cell = {
                executor.submit(
                    _run_one_cell,
                    window,
                    symbol,
                    resolution_id,
                    initial_train_years=initial_train_years,
                    hmm_states_grid=hmm_states_grid,
                    jump_n_states=jump_n_states,
                    jump_penalty=jump_penalty,
                    bocpd_hazard_lambda=bocpd_hazard_lambda,
                    bocpd_n_canonical_buckets=bocpd_n_canonical_buckets,
                    hmm_seed=hmm_seed,
                    jump_seed=jump_seed,
                ): (window, symbol)
                for window, symbol in cells_spec
            }
            cell_labels = {f: (w.name, s) for f, (w, s) in future_to_cell.items()}
            for future in iter_completed_with_heartbeat(
                cell_labels,
                event_prefix="analysis.m4_critical_windows.run_critical_windows_comparison",
                heartbeat_s=float(load_data_constant("ag071_process_pool_heartbeat_s")),
                resolution_id=resolution_id,
            ):
                window, symbol = future_to_cell[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    # 2ª camada de defesa -- processo filho morreu antes de
                    # _run_one_cell conseguir capturar a própria exceção
                    # (OOM/segfault/BrokenProcessPool). Ver docstring do
                    # módulo, seção AG-019.
                    logger.error(
                        "analysis.m4_critical_windows.cell_process_crashed",
                        window=window.name,
                        symbol=symbol,
                        resolution_id=resolution_id,
                        error=repr(exc),
                    )
                    outcomes.append(
                        CellOutcome(window.name, symbol, resolution_id, None, repr(exc))
                    )

    # AG-084 -- substitui o BOCPD fatiado-por-janela (outcomes, calculado
    # acima) pelo fatiado do histórico completo (bocpd_full_by_symbol).
    # Célula sem symbol_result (falhou/pulada) ou símbolo sem full-history
    # disponível passa direto, sem alteração -- fallback AG-019, nunca
    # crash.
    patched_outcomes: list[CellOutcome] = []
    for outcome in outcomes:
        full = bocpd_full_by_symbol.get(outcome.symbol)
        if outcome.symbol_result is None or outcome.error is not None or full is None:
            patched_outcomes.append(outcome)
            continue
        # AG-093 -- fronteira OOS da MESMA célula (mesmo walk-forward
        # ancorado que HMM/Jump Model/baseline já usaram), nunca mais
        # o range calendário da janela crítica inteira.
        corrected_result, corrected_raw = _bocpd_metrics_for_window(
            outcome.symbol_result.oos_start_ms,
            outcome.symbol_result.oos_end_ms,
            full,
            bocpd_n_canonical_buckets,
        )
        new_symbol_result, new_raw_labels = _replace_bocpd_candidate(
            outcome.symbol_result, outcome.raw_labels, corrected_result, corrected_raw
        )
        patched_outcomes.append(
            CellOutcome(
                outcome.window_name,
                outcome.symbol,
                outcome.resolution_id,
                new_symbol_result,
                None,
                new_raw_labels,
            )
        )

    if persist_raw_labels:
        _persist_raw_labels(tuple(patched_outcomes))
        if forward_vol_by_symbol:
            _persist_forward_vol_history(resolution_id, forward_vol_by_symbol)

    return aggregate_critical_windows_results(
        resolution_id,
        tuple(patched_outcomes),
        windows=windows,
        labels_by_symbol=labels_by_symbol,
        tp_atr_mult=tp_atr_mult,
        sl_atr_mult=sl_atr_mult,
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        n_permutations=n_permutations,
        permutation_seed=permutation_seed,
        forward_vol_by_symbol=forward_vol_by_symbol if compute_gate_quality else None,
        event_onset_ts_ms_by_window=event_onset_ts_ms_by_window,
    )


# ============================================================================
# AG-087 -- experimento de transferibilidade de `m4_jump_model_penalty`
# POR ATIVO (`audit/architecture_gaps_log.yaml`, 2026-08-18/20). Condição A
# (status quo, λ=0,002 fixo aplicado aos 5 símbolos) já existe em
# `experiments/m4_critical_windows_report.json` -- custo zero, só lido de
# lá pelo script de comparação (`tools/diagnostics/compare_jump_model_
# lambda_transferability.py`). Este bloco produz a Condição B (λ calibrado
# INDEPENDENTEMENTE por ETH/SOL/BNB/XRP -- BTC não entra, já é seu próprio
# "λ local"): laço fino sobre `m4.compare_jump_model_only_for_symbol`/
# `m4.run_jump_model_only_for_symbol` (só baseline + Jump Model, pula os 3
# HMM e o BOCPD -- eles não dependem de `jump_penalty`, recomputá-los por
# célula seria custo puro), alimentando a MESMA maquinaria de agregação já
# usada pelo relatório principal (`aggregate_critical_windows_results`/
# `_aggregate_one_candidate`) -- `is_saturated`/`saturation_rate` (AG-087)
# ficam de graça, sem nenhuma fórmula nova.
# ============================================================================

#: LUNA/FTX excluídas -- só BTCUSDT (`CriticalWindow.symbols`), sem ativo
#: não-BTC pra recalibrar nelas. As outras 3 janelas têm os 5 símbolos.
JUMP_TRANSFERABILITY_WINDOWS: Final[tuple[CriticalWindow, ...]] = tuple(
    w for w in CRITICAL_WINDOWS if len(w.symbols) > 1
)

#: Os 4 ativos não-BTC -- mesmo conjunto de AG-087 (BTC é seu próprio "λ
#: local", `m4_jump_model_penalty` já foi calibrado nele).
JUMP_TRANSFERABILITY_SYMBOLS: Final[tuple[str, ...]] = tuple(
    s for s in m4.ALL_SYMBOLS if s != "BTCUSDT"
)


def _run_jump_model_only_one_cell(
    window: CriticalWindow,
    symbol: str,
    resolution_id: str,
    *,
    initial_train_years: int,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int,
) -> CellOutcome:
    """Variante de `_run_one_cell` pro experimento de transferibilidade de
    λ (AG-087) -- chama `m4.run_jump_model_only_for_symbol` (baseline +
    Jump Model, pula HMM/BOCPD) em vez de `m4.run_regime_comparison_for_
    symbol`. Mesmo `CellOutcome` de saída (compatível com toda a
    maquinaria de agregação já existente -- `aggregate_critical_windows_
    results` nunca assumiu quantidade fixa de candidatos dentro de
    `symbol_result.candidates`), mesma disciplina AG-019 (exceção vira
    `CellOutcome.error`, nunca propaga) e mesma exigência de ser
    module-level (picklable, `ProcessPoolExecutor(mp_context="spawn")`)."""
    try:
        result = m4.run_jump_model_only_for_symbol(
            symbol,
            window.start,
            window.end,
            initial_train_years=initial_train_years,
            resolution_id=resolution_id,
            jump_n_states=jump_n_states,
            jump_penalty=jump_penalty,
            jump_seed=jump_seed,
            return_raw_labels=True,
        )
    except Exception as exc:  # AG-019 -- 1 célula falhando não derruba as outras
        logger.error(
            "analysis.m4_critical_windows.jump_transferability_cell_failed",
            window=window.name,
            symbol=symbol,
            resolution_id=resolution_id,
            error=repr(exc),
        )
        return CellOutcome(window.name, symbol, resolution_id, None, repr(exc), None)
    if result is None:
        logger.warning(
            "analysis.m4_critical_windows.jump_transferability_cell_folds_insuficientes",
            window=window.name,
            symbol=symbol,
            resolution_id=resolution_id,
        )
        return CellOutcome(window.name, symbol, resolution_id, None, None, None)
    symbol_result, raw_labels = result
    return CellOutcome(window.name, symbol, resolution_id, symbol_result, None, raw_labels)


def run_jump_model_transferability_comparison(
    resolution_id: str,
    *,
    jump_penalty_by_symbol: dict[str, float],
    windows: tuple[CriticalWindow, ...] = JUMP_TRANSFERABILITY_WINDOWS,
    symbols: tuple[str, ...] = JUMP_TRANSFERABILITY_SYMBOLS,
    initial_train_years: int = 1,
    jump_n_states: int = 2,
    jump_seed: int = 0,
    max_workers: int | None = None,
    compute_volatility_heterogeneity: bool = False,
) -> CriticalWindowsReport:
    """Condição B do experimento de transferibilidade de λ (AG-087) -- 1
    resolução, todas as células (janela, símbolo) de `windows` × `symbols`,
    cada uma com o λ CALIBRADO daquele símbolo (`jump_penalty_by_symbol`,
    saída de `tools/diagnostics/calibrate_jump_model_penalty_per_asset.py`
    -- este módulo nunca inventa esses valores, `ValueError` se algum
    símbolo de `symbols` não tiver entrada).

    Devolve um `CriticalWindowsReport` ESTRUTURALMENTE IDÊNTICO ao do
    relatório principal (`run_critical_windows_comparison`/`aggregate_
    critical_windows_results`, mesmos dataclasses) -- pronto pra diff
    direto contra a Condição A (`experiments/m4_critical_windows_report.
    json`, λ=0,002 fixo) via `tools/diagnostics/compare_jump_model_lambda_
    transferability.py`, sem formato novo. `baseline_classifier_id`/
    `candidate_ids` são descobertos por `_collect_classifier_ids` a partir
    de `SymbolResult.candidates` (que aqui só tem `jump_model_cjm_v1`, 1
    elemento) -- mesma maquinaria, nenhuma mudança nela.

    `windows` default exclui LUNA/FTX (`JUMP_TRANSFERABILITY_WINDOWS`,
    BTC-only -- sem ativo não-BTC pra recalibrar nelas, mesma decisão do
    desenho autorizado pelo Manager). `max_workers=1` força sequencial
    (mesmo padrão de `run_critical_windows_comparison`, usado por testes).

    `compute_volatility_heterogeneity=False` (default NESTA função de
    nível baixo -- mesma assimetria já existente entre `run_critical_
    windows_comparison.compute_gate_quality=False` vs. o `True` do
    `run_and_save_critical_windows_report` que a chama; o script de
    comparação final, `tools/diagnostics/compare_jump_model_lambda_
    transferability.py`, passa `True` explicitamente). Quando `True`,
    calcula `_SymbolForwardVolHistory` 1x por símbolo (candidato-
    independente, reusa `_compute_symbol_forward_vol_history` já
    existente, custo IO puro, sem fit) e repassa pra `aggregate_critical_
    windows_results` via
    `forward_vol_by_symbol` -- ativa `volatility_heterogeneity`
    (`i_squared_pct`/`p_value_permutation`, AG-114) como sinal secundário/
    corroborante do experimento (não o critério primário, que é
    `is_saturated`/`saturation_rate`). **Efeito colateral aceito, não
    escondido**: `aggregate_critical_windows_results` acopla `gate_
    quality` (occupancy/transition-failure/detection-delay) ao mesmo
    parâmetro `forward_vol_by_symbol` -- não há como pedir só a
    heterogeneidade de volatilidade sem também computar gate_quality
    sem duplicar lógica de agregação (fora do escopo desta extensão,
    "reuse não duplique"). `gate_quality` fica no relatório B, mas
    `compare_jump_model_lambda_transferability.py` não o consome como
    critério -- decisão do desenho autorizado ("NÃO usar o framework de
    gate-quality... limiares ainda TBD"), só ignorado, nunca desligado à
    força (desligar exigiria reescrever `aggregate_critical_windows_
    results`, não vale o custo pra um campo extra simplesmente ignorado).
    `n_permutations`/`permutation_seed` vêm de `constants.yaml` (`m4_
    heterogeneity_n_permutations`/`m4_heterogeneity_permutation_seed`,
    já existentes -- nenhuma constante nova)."""
    missing = [s for s in symbols if s not in jump_penalty_by_symbol]
    if missing:
        raise ValueError(
            f"run_jump_model_transferability_comparison: jump_penalty_by_symbol não tem "
            f"valor calibrado para {missing} -- rode tools/diagnostics/calibrate_jump_model_"
            "penalty_per_asset.py primeiro (item 2 do experimento AG-087); este módulo nunca "
            "inventa jump_penalty (B20)"
        )

    cells_spec = [
        (window, symbol)
        for window in windows
        for symbol in symbols
        if symbol in window.symbols
    ]

    outcomes: list[CellOutcome] = []
    if max_workers == 1:
        for window, symbol in cells_spec:
            outcomes.append(
                _run_jump_model_only_one_cell(
                    window,
                    symbol,
                    resolution_id,
                    initial_train_years=initial_train_years,
                    jump_n_states=jump_n_states,
                    jump_penalty=jump_penalty_by_symbol[symbol],
                    jump_seed=jump_seed,
                )
            )
    else:
        workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
        mp_context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp_context) as executor:
            future_to_cell = {
                executor.submit(
                    _run_jump_model_only_one_cell,
                    window,
                    symbol,
                    resolution_id,
                    initial_train_years=initial_train_years,
                    jump_n_states=jump_n_states,
                    jump_penalty=jump_penalty_by_symbol[symbol],
                    jump_seed=jump_seed,
                ): (window, symbol)
                for window, symbol in cells_spec
            }
            cell_labels = {f: (w.name, s) for f, (w, s) in future_to_cell.items()}
            for future in iter_completed_with_heartbeat(
                cell_labels,
                event_prefix="analysis.m4_critical_windows.jump_transferability",
                heartbeat_s=float(load_data_constant("ag071_process_pool_heartbeat_s")),
                resolution_id=resolution_id,
            ):
                window, symbol = future_to_cell[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    # 2ª camada de defesa -- processo filho morreu antes de
                    # _run_jump_model_only_one_cell conseguir capturar a
                    # própria exceção (mesmo padrão AG-019 de
                    # run_critical_windows_comparison).
                    logger.error(
                        "analysis.m4_critical_windows.jump_transferability_cell_process_crashed",
                        window=window.name,
                        symbol=symbol,
                        resolution_id=resolution_id,
                        error=repr(exc),
                    )
                    outcomes.append(
                        CellOutcome(window.name, symbol, resolution_id, None, repr(exc))
                    )

    forward_vol_by_symbol: dict[str, _SymbolForwardVolHistory] = {}
    n_permutations: int | None = None
    permutation_seed: int | None = None
    if compute_volatility_heterogeneity:
        n_permutations = int(load_data_constant("m4_heterogeneity_n_permutations"))
        permutation_seed = int(load_data_constant("m4_heterogeneity_permutation_seed"))
        for symbol in symbols:
            try:
                forward_vol_by_symbol[symbol] = _compute_symbol_forward_vol_history(
                    symbol, resolution_id
                )
            except Exception as exc:  # AG-019 -- 1 símbolo falhando não derruba os outros
                logger.error(
                    "analysis.m4_critical_windows.jump_transferability_forward_vol_failed",
                    symbol=symbol,
                    resolution_id=resolution_id,
                    error=repr(exc),
                )

    logger.info(
        "analysis.m4_critical_windows.jump_transferability_resolution_done",
        resolution_id=resolution_id,
        n_cells_requested=len(cells_spec),
        n_cells_ok=sum(1 for o in outcomes if o.error is None and o.symbol_result is not None),
        n_symbols_forward_vol_ok=len(forward_vol_by_symbol),
    )

    return aggregate_critical_windows_results(
        resolution_id,
        tuple(outcomes),
        windows=windows,
        forward_vol_by_symbol=forward_vol_by_symbol if compute_volatility_heterogeneity else None,
        n_permutations=n_permutations,
        permutation_seed=permutation_seed,
    )


# ============================================================================
# "Condição C" -- Jump Model com espaço de observação ESTENDIDO (AG-119,
# 2026-08-20). Reteste isolado (`tools/diagnostics/retest_jump_model_
# extended_features_k3.py`) mostrou que SOLUSDT/BNBUSDT/XRPUSDT -- excluídos
# do ranking do AG-114 por AG-117 (nenhum λ dava ≥2 estados OOS genuínos no
# espaço de 2 features + K=2) -- mostram estrutura de regime genuína quando
# testados com espaço de 4 features (log_return_1/realized_vol_short/
# realized_vol_long/downside_deviation) + jump_n_states=3, alinhado à
# literatura cripto-específica (Cortese/Kolm/Lindström 2023). Este bloco
# reproduz a MESMA mecânica da Condição B (AG-087) -- laço fino sobre o
# harness de símbolo único, mesma agregação (`aggregate_critical_windows_
# results`), mesmo isolamento de falha por célula (AG-019) -- só troca o
# candidato-fonte de `m4.run_jump_model_only_for_symbol` (2 features, K
# fixo do experimento B) para `m4.run_jump_model_extended_features_for_
# symbol` (4 features, K explícito do caller, sem hardcode -- decisão de
# calibração Classe B, nunca decidida por este módulo).
# ============================================================================


def _run_jump_model_extended_features_one_cell(
    window: CriticalWindow,
    symbol: str,
    resolution_id: str,
    *,
    initial_train_years: int,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int,
) -> CellOutcome:
    """Variante de `_run_jump_model_only_one_cell` pra "Condição C" (AG-119)
    -- chama `m4.run_jump_model_extended_features_for_symbol` (baseline +
    Jump Model com observação 4D) em vez de `m4.run_jump_model_only_for_
    symbol` (2D). Mesmo `CellOutcome` de saída, mesma disciplina AG-019
    (exceção vira `CellOutcome.error`, nunca propaga) e mesma exigência de
    ser module-level (picklable, `ProcessPoolExecutor(mp_context="spawn")`)."""
    try:
        result = m4.run_jump_model_extended_features_for_symbol(
            symbol,
            window.start,
            window.end,
            initial_train_years=initial_train_years,
            resolution_id=resolution_id,
            jump_n_states=jump_n_states,
            jump_penalty=jump_penalty,
            jump_seed=jump_seed,
            return_raw_labels=True,
        )
    except Exception as exc:  # AG-019 -- 1 célula falhando não derruba as outras
        logger.error(
            "analysis.m4_critical_windows.jump_extended_features_cell_failed",
            window=window.name,
            symbol=symbol,
            resolution_id=resolution_id,
            error=repr(exc),
        )
        return CellOutcome(window.name, symbol, resolution_id, None, repr(exc), None)
    if result is None:
        logger.warning(
            "analysis.m4_critical_windows.jump_extended_features_cell_folds_insuficientes",
            window=window.name,
            symbol=symbol,
            resolution_id=resolution_id,
        )
        return CellOutcome(window.name, symbol, resolution_id, None, None, None)
    symbol_result, raw_labels = result
    return CellOutcome(window.name, symbol, resolution_id, symbol_result, None, raw_labels)


def run_jump_model_extended_features_comparison(
    resolution_id: str,
    *,
    jump_penalty_by_symbol: dict[str, float],
    jump_n_states: int,
    windows: tuple[CriticalWindow, ...] = JUMP_TRANSFERABILITY_WINDOWS,
    symbols: tuple[str, ...] = JUMP_TRANSFERABILITY_SYMBOLS,
    initial_train_years: int = 1,
    jump_seed: int = 0,
    max_workers: int | None = None,
    compute_volatility_heterogeneity: bool = False,
) -> CriticalWindowsReport:
    """"Condição C" do experimento de transferibilidade de Jump Model
    (`AG-119`, `audit/architecture_gaps_log.yaml`) -- 1 resolução, todas as
    células (janela, símbolo) de `windows` × `symbols`, cada uma com o λ
    CALIBRADO daquele símbolo no espaço de 4 features
    (`jump_penalty_by_symbol`, saída de `tools/diagnostics/retest_jump_
    model_extended_features_k3.py` -- este módulo nunca inventa esses
    valores, `ValueError` se algum símbolo de `symbols` não tiver entrada,
    mesma disciplina B20 de `run_jump_model_transferability_comparison`).

    `jump_n_states` é OBRIGATÓRIO, sem default -- ao contrário da Condição
    B (`jump_n_states: int = 2`), aqui não existe "padrão" já estabelecido:
    o próprio achado do AG-119 é que K=3 (não K=2) é o que revela estrutura
    genuína pra SOLUSDT/BNBUSDT/XRPUSDT no espaço estendido -- decisão de
    calibração Classe B, sempre explícita do caller, nunca hardcoded aqui.

    Devolve um `CriticalWindowsReport` ESTRUTURALMENTE IDÊNTICO ao da
    Condição B/relatório principal (mesmos dataclasses) -- pronto pra diff
    direto contra `experiments/m4_critical_windows_report.json` (Condição
    A, Jump Model excluído dos 4 ativos não-BTC) e contra a Condição B, sem
    formato novo.

    `windows`/`symbols` default = os mesmos da Condição B
    (`JUMP_TRANSFERABILITY_WINDOWS`/`JUMP_TRANSFERABILITY_SYMBOLS` --
    LUNA/FTX BTC-only, os 4 ativos não-BTC) -- mesma razão: sem backfill
    suficiente dos altcoins antes de mai/nov-2022 pra treino inicial de 1
    ano.

    `compute_volatility_heterogeneity=False` (default nesta função de
    nível baixo, mesma assimetria de `run_jump_model_transferability_
    comparison`) -- quando `True`, reusa `_compute_symbol_forward_vol_
    history` (candidato-independente, custo IO puro) e ativa
    `volatility_heterogeneity` como sinal secundário/corroborante, não o
    critério primário do experimento (que é `is_saturated`/
    `saturation_rate`, já embutido em `CandidateResult` por
    `_run_fold_refit_candidate`)."""
    missing = [s for s in symbols if s not in jump_penalty_by_symbol]
    if missing:
        raise ValueError(
            f"run_jump_model_extended_features_comparison: jump_penalty_by_symbol não tem "
            f"valor calibrado para {missing} -- rode tools/diagnostics/retest_jump_model_"
            "extended_features_k3.py primeiro (AG-119); este módulo nunca inventa jump_penalty "
            "(B20)"
        )

    cells_spec = [
        (window, symbol)
        for window in windows
        for symbol in symbols
        if symbol in window.symbols
    ]

    outcomes: list[CellOutcome] = []
    if max_workers == 1:
        for window, symbol in cells_spec:
            outcomes.append(
                _run_jump_model_extended_features_one_cell(
                    window,
                    symbol,
                    resolution_id,
                    initial_train_years=initial_train_years,
                    jump_n_states=jump_n_states,
                    jump_penalty=jump_penalty_by_symbol[symbol],
                    jump_seed=jump_seed,
                )
            )
    else:
        workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
        mp_context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp_context) as executor:
            future_to_cell = {
                executor.submit(
                    _run_jump_model_extended_features_one_cell,
                    window,
                    symbol,
                    resolution_id,
                    initial_train_years=initial_train_years,
                    jump_n_states=jump_n_states,
                    jump_penalty=jump_penalty_by_symbol[symbol],
                    jump_seed=jump_seed,
                ): (window, symbol)
                for window, symbol in cells_spec
            }
            cell_labels = {f: (w.name, s) for f, (w, s) in future_to_cell.items()}
            for future in iter_completed_with_heartbeat(
                cell_labels,
                event_prefix="analysis.m4_critical_windows.jump_extended_features",
                heartbeat_s=float(load_data_constant("ag071_process_pool_heartbeat_s")),
                resolution_id=resolution_id,
            ):
                window, symbol = future_to_cell[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    # 2ª camada de defesa -- processo filho morreu antes de
                    # _run_jump_model_extended_features_one_cell conseguir
                    # capturar a própria exceção (mesmo padrão AG-019).
                    logger.error(
                        "analysis.m4_critical_windows.jump_extended_features_cell_process_crashed",
                        window=window.name,
                        symbol=symbol,
                        resolution_id=resolution_id,
                        error=repr(exc),
                    )
                    outcomes.append(
                        CellOutcome(window.name, symbol, resolution_id, None, repr(exc))
                    )

    forward_vol_by_symbol: dict[str, _SymbolForwardVolHistory] = {}
    n_permutations: int | None = None
    permutation_seed: int | None = None
    if compute_volatility_heterogeneity:
        n_permutations = int(load_data_constant("m4_heterogeneity_n_permutations"))
        permutation_seed = int(load_data_constant("m4_heterogeneity_permutation_seed"))
        for symbol in symbols:
            try:
                forward_vol_by_symbol[symbol] = _compute_symbol_forward_vol_history(
                    symbol, resolution_id
                )
            except Exception as exc:  # AG-019 -- 1 símbolo falhando não derruba os outros
                logger.error(
                    "analysis.m4_critical_windows.jump_extended_features_forward_vol_failed",
                    symbol=symbol,
                    resolution_id=resolution_id,
                    error=repr(exc),
                )

    logger.info(
        "analysis.m4_critical_windows.jump_extended_features_resolution_done",
        resolution_id=resolution_id,
        jump_n_states=jump_n_states,
        n_cells_requested=len(cells_spec),
        n_cells_ok=sum(1 for o in outcomes if o.error is None and o.symbol_result is not None),
        n_symbols_forward_vol_ok=len(forward_vol_by_symbol),
    )

    return aggregate_critical_windows_results(
        resolution_id,
        tuple(outcomes),
        windows=windows,
        forward_vol_by_symbol=forward_vol_by_symbol if compute_volatility_heterogeneity else None,
        n_permutations=n_permutations,
        permutation_seed=permutation_seed,
    )


# ============================================================================
# Relatório -- JSON atômico, mesmo padrão de m4_regime_comparison.py
# ============================================================================

_AG043_CAVEAT: Final[str] = (
    "AG-043 (audit/architecture_gaps_log.yaml, status 'parcialmente fechado') -- todas as "
    "janelas do Feature/Regime Engine (min_warmup_bars, regime_confirmation_bars, "
    "regime_stress_exit_confirmation_bars em src/regime/, feature_c06_vol_ratio_short_window "
    "em src/features/) sao em contagem de BARRA, nao tempo real -- sob R2 (~30min/barra) e R3 "
    "(~1h/barra) o mesmo numero de barras representa um horizonte de tempo real DIFERENTE de "
    "R1 (~15min/barra). Correcao de codigo esta DEFERIDA (docs/refactor_dollar_bar_canonico.md "
    "§8, bloqueada ate medicao de duracao real de dollar-bar) -- fora de escopo desta extensao. "
    "Resultado sob R2/R3 tem essa limitacao conhecida: warmup/histerese nao sao "
    "resolucao-calibrados, entao comparar diretamente 'quantos folds sobreviveram' ou "
    "'quantas barras de warmup foram cortadas' entre R1 e R2/R3 nao e uma comparacao justa na "
    "dimensao de TIMING -- so na dimensao de separacao/persistencia/ortogonalidade do "
    "candidato em si, dentro da mesma resolucao."
)

_LUNA_FTX_BTC_ONLY_CAVEAT: Final[str] = (
    "Janelas LUNA e FTX rodam SO com BTCUSDT (decisao do Manager, 2026-08-18) -- os 4 "
    "altcoins (ETHUSDT/SOLUSDT/BNBUSDT/XRPUSDT) so tem backfill desde 2021-12-01, sem runway "
    "suficiente antes desses 2 eventos (mai/2022 e nov/2022) para initial_train_years=1 de "
    "treino inicial. Resultado dessas 2 janelas NAO tem leitura cross-asset, so valido para "
    "BTC -- nao inferir generalizacao para os outros 4 ativos a partir delas."
)

_JUMP_MODEL_EXCLUDED_FROM_RANKING_CAVEAT: Final[str] = (
    "AG-117, 2026-08-20 (audit/architecture_gaps_log.yaml) -- jump_model_cjm_v1 roda SO pra "
    "BTCUSDT (`_run_one_cell` seta include_jump_model=(symbol=='BTCUSDT') -- experimento de "
    "transferibilidade de lambda mostrou ausencia de estrutura de 2 regimes detectavel em "
    "SOLUSDT/BNBUSDT/XRPUSDT em qualquer ponto do grid testado, e recalibrar lambda pra "
    "ETHUSDT piora/empata a saturacao nas janelas criticas). ACHADO IMPORTANTE, nao so uma "
    "reducao de cobertura: como CRYPTO_WINTER/ETF_HALVING/RECENTE tem ate 5 simbolos pros "
    "outros candidatos (mediana entre simbolos) mas SO 1 (BTC) pro Jump Model, o agregado de "
    "jump_model_cjm_v1 neste relatorio NAO E COMPARAVEL ao de HMM/BOCPD -- composicao de "
    "amostra diferente, nao so tamanho menor. Jump Model esta DESQUALIFICADO da comparacao/"
    "ranking do AG-114 (gates + metrica primaria) por essa evidencia separada e controlada "
    "(AG-117), nao pelo resultado deste relatorio -- qualquer implementacao futura da etapa "
    "gates->ranking->desempate DEVE excluir jump_model_cjm_v1 da disputa pelo candidato "
    "vencedor. Os numeros de jump_model_cjm_v1 aqui persistidos sao SO diagnostico/BTC, nunca "
    "elegiveis pra vencer -- nao promover Jump Model a partir de um numero bom neste relatorio "
    "sem cruzar contra AG-117 primeiro."
)

_TARGET_FOLD_CAVEAT: Final[str] = (
    "CORRIGIDO 2026-08-18 (2 auditorias céticas independentes, reprodução direta de "
    "generate_anchored_walk_forward_splits sobre dado real -- ver AG-084/AG-087, "
    "audit/architecture_gaps_log.yaml): a alegação original desta constante (mes-alvo no "
    "FOLD 1 de 3 folds totais) estava ERRADA. O real, medido: cada janela crítica produz "
    "EXATAMENTE 2 folds de teste (indices 0 e 1), não 3 -- o mes-alvo cai no FOLD 0 (primeiro "
    "fold de teste), não no fold 1. Confirmado por 2 agentes independentes sobre LUNA/"
    "CRYPTO_WINTER/ETF_HALVING/RECENTE (FTX não testado diretamente, mesmo mecanismo "
    "provável mas não reproduzido). Causa provável do erro original: a verificação anterior "
    "não aplicou o mesmo corte de warmup (_valid_start_idx, ~12 barras) antes de contar "
    "trimestres únicos, deslocando a contagem por 1 posição. Isso NÃO muda nenhum número "
    "agregado do relatório (a agregação em aggregate_critical_windows_results é agnóstica a "
    "índice de fold -- soma/mediana sobre TODOS os folds OOS de cada símbolo, nunca filtra "
    "por índice) -- só corrige a narrativa de cobertura: cada janela cobre a extensão real de "
    "2 folds de teste, não 3. Os textos individuais em CriticalWindow.note (abaixo) ainda "
    "citam a contagem antiga (fold1/fold2) e não foram reescritos numericamente -- preservados "
    "como registro histórico do que foi originalmente medido, com esta nota como a correção "
    "de referência."
)


#: G-C1-2 revisado -- grade de `labels.parquet` usada pra Cochran's Q/I²,
#: INDEPENDENTE da resolução de regime (R1/R2/R3) que está sendo
#: comparada -- mesma convenção de `m6_common_factor_hypothesis.
#: DECISION_TF`, constante de módulo (identificador de schema), não
#: `constants.yaml` (não é parâmetro numérico ajustável).
_HETEROGENEITY_LABELS_TF: Final[str] = "15m"
_HETEROGENEITY_LABELS_VERSION: Final[str] = "v1"


def _load_labels_by_symbol(
    symbols: tuple[str, ...],
    *,
    labels_version: str = _HETEROGENEITY_LABELS_VERSION,
    tf: str = _HETEROGENEITY_LABELS_TF,
) -> dict[str, pl.DataFrame]:
    """G-C1-2 revisado -- carrega `labels.parquet` 1x por símbolo (grade
    15m-calendário, INDEPENDENTE de resolução de regime -- reusada pelas
    3 chamadas de R1/R2/R3 em `run_and_save_critical_windows_report`,
    nunca recarregada por resolução). Símbolo sem labels ainda gerados
    (`FileNotFoundError`, `load_labels_v1` já dá mensagem acionável) --
    log + excluído do dict, mesma disciplina AG-019 do resto do módulo:
    nunca derruba os símbolos que TÊM labels."""
    result: dict[str, pl.DataFrame] = {}
    for symbol in symbols:
        try:
            result[symbol] = load_labels_v1(labels_version, symbol=symbol, tf=tf)
        except FileNotFoundError as exc:
            logger.warning(
                "analysis.m4_critical_windows.heterogeneity_labels_ausentes",
                symbol=symbol,
                error=repr(exc),
            )
    return result


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão de `m4_regime_comparison._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("analysis.m4_critical_windows.report_written", path=str(dest_path))


# ============================================================================
# Persistência de raw_labels/forward_vol_history -- follow-up de AG-114,
# 2026-08-20 (decisão do Manager). Antes desta extensão, `CellOutcome.
# raw_labels`/`_SymbolForwardVolHistory` só existiam em memória durante 1
# execução de `run_critical_windows_comparison` -- QUALQUER métrica nova
# sobre o MESMO fit (não só gate_quality/volatility_heterogeneity, já
# cobertas por `CriticalWindowsReport`) exigiria re-rodar a extração
# completa (~3h, refit real de HMM/Jump Model/BOCPD x 6 candidatos x 3
# resoluções x 5 janelas) de novo -- exatamente a preocupação de
# sequenciamento levantada pelo Manager antes de autorizar a rodada real.
# Persistir aqui resolve isso de vez, não só para esta rodada.
# ============================================================================

RAW_LABELS_OUTPUT_DIR: Final[Path] = EXPERIMENTS_DIR / "m4_raw_labels"
FORWARD_VOL_HISTORY_OUTPUT_DIR: Final[Path] = EXPERIMENTS_DIR / "m4_forward_vol_history"


def _write_parquet_atomic(df: pl.DataFrame, dest_path: Path) -> None:
    """B29 -- mesmo padrão de `src.labels.triple_barrier.write_labels_
    atomic`: serializa pra um buffer em memória primeiro (`write_parquet`
    não devolve um file descriptor que dê pra `fsync` diretamente), escreve
    os bytes através de um handle `wb` normal e faz `fsync` NESSE MESMO
    handle -- reabrir o `.tmp` como `O_RDONLY` só pra `fsync` falha no
    Windows com "Bad file descriptor" (medido no Sprint 6)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    with tmp_path.open("wb") as fh:
        fh.write(buffer.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)


def _raw_labels_path(
    resolution_id: str, window_name: str, symbol: str, classifier_id: str
) -> Path:
    return (
        RAW_LABELS_OUTPUT_DIR
        / resolution_id
        / window_name
        / symbol
        / f"{classifier_id}.parquet"
    )


def _forward_vol_history_path(resolution_id: str, symbol: str) -> Path:
    return FORWARD_VOL_HISTORY_OUTPUT_DIR / resolution_id / f"{symbol}.parquet"


def _persist_raw_labels(outcomes: tuple[CellOutcome, ...]) -> None:
    """1 parquet por (`resolution_id`, `window_name`, `symbol`,
    `classifier_id`) -- `open_time_ms`/`close_time_ms`/`canonical_id` de
    `m4.RawLabels`, já coletado SEM custo extra por `_run_one_cell` (ver
    docstring de `CellOutcome`, "custo desprezível"). Célula sem
    `raw_labels` (falhou/pulada, AG-019) não escreve nada -- mesma
    disciplina do resto do módulo, nunca inventa dado que não existe.
    Sobrescreve em toda chamada (mesma semântica de `experiments/
    m4_critical_windows_report.json` -- artefato experimental, não label
    canônico versionado como `labels/{version}/labels.parquet`)."""
    n_written = 0
    for outcome in outcomes:
        if outcome.raw_labels is None:
            continue
        for classifier_id, raw in outcome.raw_labels.items():
            df = pl.DataFrame(
                {
                    "open_time_ms": raw.open_time_ms,
                    "close_time_ms": raw.close_time_ms,
                    "canonical_id": raw.canonical_id,
                }
            )
            dest = _raw_labels_path(
                outcome.resolution_id, outcome.window_name, outcome.symbol, classifier_id
            )
            _write_parquet_atomic(df, dest)
            n_written += 1
    logger.info(
        "analysis.m4_critical_windows.raw_labels_persisted",
        n_cells=len(outcomes),
        n_files_written=n_written,
    )


def _persist_forward_vol_history(
    resolution_id: str, forward_vol_by_symbol: dict[str, _SymbolForwardVolHistory]
) -> None:
    """1 parquet por (`resolution_id`, `symbol`) -- candidato-independente
    (mesma observação de mercado reusada pelos 6 candidatos via
    `_join_candidate_with_vol_history`), persistido separado de
    `_persist_raw_labels` pra não repetir a mesma série 6x (1 por
    classifier_id seria redundante -- `realized_vol_short`/
    `forward_realized_vol` não dependem de qual candidato está sendo
    avaliado)."""
    for symbol, hist in forward_vol_by_symbol.items():
        df = pl.DataFrame(
            {
                "close_time_ms": hist.close_time_ms,
                "realized_vol_short": hist.realized_vol_short,
                "forward_realized_vol": hist.forward_realized_vol,
            }
        )
        _write_parquet_atomic(df, _forward_vol_history_path(resolution_id, symbol))
    logger.info(
        "analysis.m4_critical_windows.forward_vol_history_persisted",
        resolution_id=resolution_id,
        n_symbols=len(forward_vol_by_symbol),
    )


def _build_report_payload(
    resolutions: tuple[str, ...],
    windows: tuple[CriticalWindow, ...],
    reports: list[CriticalWindowsReport],
    elapsed_seconds_total: float,
    *,
    partial: bool,
) -> dict[str, Any]:
    """Payload do relatório combinado. `partial=True` é um CHECKPOINT
    intermediário (achado `project_assurance`, 2026-08-18, HIGH -- mesma
    classe de gap já corrigida em `m2_bar_comparison._build_payload`/
    `run_and_save_bar_comparison_report`, AG-019, emenda 2026-08-15,
    "isolamento de falha por task + checkpoint incremental"): antes desta
    correção, `run_and_save_critical_windows_report` só persistia depois
    que as 3 resoluções (`R1`/`R2`/`R3`) tivessem terminado -- uma falha
    tardia (processo PAI morto, exceção não prevista escapando de
    `aggregate_critical_windows_results`, `KeyboardInterrupt`) depois de
    R1+R2 já terem rodado horas de fit real de HMM/Jump Model/BOCPD
    (1 célula sozinha já mediu 732,8s no smoke test do commit `32171f9`)
    descartava os 2 resultados já concluídos, nada no disco. `by_resolution`
    de um payload parcial só contém as resoluções JÁ concluídas (lista
    crescente) -- `resolutions_evaluated` continua a lista completa
    pedida, então `len(by_resolution) < len(resolutions_evaluated)` já
    sinaliza "ainda incompleto" sem precisar do campo `partial` pra isso,
    mesmo padrão de honestidade sobre estado incompleto já usado em
    `per_window`/`per_symbol` no resto do módulo."""
    return {
        **report_provenance(),
        "partial": partial,
        "resolutions_evaluated": list(resolutions),
        "elapsed_seconds_total": elapsed_seconds_total,
        "ag043_barra_vs_tempo_real_caveat": _AG043_CAVEAT,
        "luna_ftx_btc_only_caveat": _LUNA_FTX_BTC_ONLY_CAVEAT,
        "jump_model_excluded_from_ranking_caveat": _JUMP_MODEL_EXCLUDED_FROM_RANKING_CAVEAT,
        "target_fold_is_fold1_not_fold0_caveat": _TARGET_FOLD_CAVEAT,
        "windows": [asdict(w) for w in windows],
        "by_resolution": [asdict(r) for r in reports],
    }


def run_and_save_critical_windows_report(
    *,
    resolutions: tuple[str, ...] = RESOLUTIONS,
    windows: tuple[CriticalWindow, ...] = CRITICAL_WINDOWS,
    dest_path: Path | None = None,
    initial_train_years: int = 1,
    hmm_states_grid: tuple[int, ...] = (2, 3, 4),
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = 0,
    jump_seed: int = 0,
    max_workers: int | None = None,
    compute_heterogeneity: bool = True,
    compute_gate_quality: bool = True,
    persist_raw_labels: bool = True,
) -> Path:
    """Ponto de entrada real -- itera as `resolutions` (default as 3, R1/
    R2/R3) SEQUENCIALMENTE, cada uma via `run_critical_windows_comparison`
    (que paraleliza internamente por célula), persiste o relatório
    combinado atômico (B29) -- inclusive um CHECKPOINT parcial (`partial:
    true`) a cada resolução concluída, não só no final (ver docstring de
    `_build_report_payload`, achado `project_assurance` 2026-08-18, HIGH).

    `persist_raw_labels=True` (default, follow-up de AG-114, 2026-08-20,
    decisão do Manager) -- grava `raw_labels`/`_SymbolForwardVolHistory`
    em `experiments/m4_raw_labels/`/`experiments/m4_forward_vol_history/`
    a cada resolução concluída (dentro do mesmo `run_critical_windows_
    comparison`, mesmo timing do checkpoint parcial do relatório JSON) --
    resolve de vez a preocupação de sequenciamento levantada antes desta
    rodada real ("não faz sentido rodar agora pra depois... rodar de
    novo"): qualquer métrica futura sobre o MESMO fit passa a ler parquet
    já persistido, nunca mais exige re-fit completo (~3h).

    `compute_gate_quality=True` (default, AG-114, 2026-08-20) -- carrega
    `m4_luna_event_onset_ts_ms`/`m4_ftx_event_onset_ts_ms` (independentes
    de resolução, carregados 1x fora do loop) e propaga
    `compute_gate_quality=True` pra cada `run_critical_windows_comparison`
    (que calcula `_SymbolForwardVolHistory` por resolução, dentro do loop
    -- diferente de `labels_by_symbol`, que não depende de resolução).
    `compute_gate_quality=False` preserva `gate_quality=()`/
    `volatility_heterogeneity=()`, mesmo espírito de
    `compute_heterogeneity=False`.

    `compute_heterogeneity=True` (default, G-C1-2 revisado, decisão do
    Manager 2026-08-18) -- carrega `labels.parquet` 1x por símbolo (união
    de todos os símbolos de `windows`, ANTES do loop de resolução --
    `labels.parquet` não depende de R1/R2/R3, recarregar por resolução
    seria IO redundante) e propaga pra cada `run_critical_windows_
    comparison`, que ativa Cochran's Q/I² em `CriticalWindowsReport.
    heterogeneity`. `compute_heterogeneity=False` preserva o
    comportamento anterior a esta revisão (`heterogeneity=()`, útil pra
    reproduzir bit-a-bit um relatório anterior à mudança de critério, ou
    pra rodar sem `labels.parquet` disponível).

    **NÃO CHAME esta função sem autorização explícita do Manager** (Fase
    D do plano `wise-exploring-panda.md`) -- consome orçamento de trial
    (`G-C1-2` revisado para `<=18 trials`, `audit/n_lifetime.yaml` -- essa
    revisão de gate NÃO está sincronizada em `PRD_V4_1.md`/`docs/m4_regime_
    plano_execucao.md`, que ainda dizem `<=6`; achado `project_assurance`
    2026-08-18, HIGH, `PENDENTE DECISÃO MANAGER` sobre qual número é o
    vigente -- não corrigido aqui).
    Hiperparâmetros de candidato sem default, mesma disciplina de
    `m4_regime_comparison.run_and_save_m4_report`.

    Chame manualmente (só depois da autorização):
    `uv run python -c "from src.analysis.m4_critical_windows import "
    "run_and_save_critical_windows_report as r; r(jump_n_states=2, "
    "jump_penalty=0.002, bocpd_hazard_lambda=65.0, "
    "bocpd_n_canonical_buckets=3)"`"""
    t0 = time.perf_counter()
    reports: list[CriticalWindowsReport] = []
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH

    labels_by_symbol: dict[str, pl.DataFrame] | None = None
    het_tp_atr_mult: float | None = None
    het_sl_atr_mult: float | None = None
    het_maker_fee: float | None = None
    het_taker_fee: float | None = None
    het_n_permutations: int | None = None
    het_permutation_seed: int | None = None
    # AG-092 -- teste de permutação em bloco por episódio. Carregado se
    # QUALQUER um dos 2 blocos que o usam estiver ativo (heterogeneidade
    # TP/SL OU volatility_heterogeneity contínua, AG-114) -- os 2 podem
    # ser ligados/desligados independentemente.
    if compute_heterogeneity or compute_gate_quality:
        het_n_permutations = int(load_data_constant("m4_heterogeneity_n_permutations"))
        het_permutation_seed = int(load_data_constant("m4_heterogeneity_permutation_seed"))
    if compute_heterogeneity:
        all_symbols = tuple(sorted({symbol for w in windows for symbol in w.symbols}))
        labels_by_symbol = _load_labels_by_symbol(all_symbols)
        het_cfg = LabelConfig.from_constants(tf=_HETEROGENEITY_LABELS_TF)
        het_tp_atr_mult = het_cfg.tp_atr_mult
        het_sl_atr_mult = het_cfg.sl_atr_mult
        het_maker_fee = float(load_risk_constant("maker_fee"))
        het_taker_fee = float(load_risk_constant("taker_fee"))
        logger.info(
            "analysis.m4_critical_windows.heterogeneity_labels_loaded",
            n_symbols_requested=len(all_symbols),
            n_symbols_ok=len(labels_by_symbol),
        )

    # AG-114, 2026-08-20 -- datas de onset dos 2 eventos de colapso abrupto
    # com instante localizável (LUNA/FTX); independentes de resolução,
    # carregadas 1x fora do loop. Gate 3 (desempate only) fica
    # NOT_COMPUTABLE nas outras 3 janelas (sem instante único de evento),
    # nunca inventado -- ver docstring de GateQualitySymbolDetail.
    event_onset_ts_ms_by_window: dict[str, int] = {}
    if compute_gate_quality:
        event_onset_ts_ms_by_window = {
            "LUNA": int(load_data_constant("m4_luna_event_onset_ts_ms")),
            "FTX": int(load_data_constant("m4_ftx_event_onset_ts_ms")),
        }

    for resolution_id in resolutions:
        logger.info(
            "analysis.m4_critical_windows.resolution_starting", resolution_id=resolution_id
        )
        report = run_critical_windows_comparison(
            resolution_id,
            windows=windows,
            initial_train_years=initial_train_years,
            hmm_states_grid=hmm_states_grid,
            jump_n_states=jump_n_states,
            jump_penalty=jump_penalty,
            bocpd_hazard_lambda=bocpd_hazard_lambda,
            bocpd_n_canonical_buckets=bocpd_n_canonical_buckets,
            hmm_seed=hmm_seed,
            jump_seed=jump_seed,
            max_workers=max_workers,
            labels_by_symbol=labels_by_symbol,
            tp_atr_mult=het_tp_atr_mult,
            sl_atr_mult=het_sl_atr_mult,
            maker_fee=het_maker_fee,
            taker_fee=het_taker_fee,
            n_permutations=het_n_permutations,
            permutation_seed=het_permutation_seed,
            compute_gate_quality=compute_gate_quality,
            event_onset_ts_ms_by_window=event_onset_ts_ms_by_window,
            persist_raw_labels=persist_raw_labels,
        )
        reports.append(report)
        logger.info(
            "analysis.m4_critical_windows.resolution_done",
            resolution_id=resolution_id,
            n_failed=len(report.failed_cells),
            n_skipped=len(report.skipped_cells),
        )
        # Checkpoint -- ver docstring de _build_report_payload. Persiste o
        # que já terminou ANTES de seguir pra próxima resolução, não só no
        # fim da função inteira.
        _atomic_write_json(
            _build_report_payload(
                resolutions, windows, reports, time.perf_counter() - t0, partial=True
            ),
            dest,
        )
        logger.info(
            "analysis.m4_critical_windows.checkpoint",
            n_resolutions_done=len(reports),
            n_resolutions_requested=len(resolutions),
        )

    elapsed_s = time.perf_counter() - t0
    _atomic_write_json(
        _build_report_payload(resolutions, windows, reports, elapsed_s, partial=False), dest
    )
    logger.info(
        "analysis.m4_critical_windows.done",
        elapsed_seconds_total=round(elapsed_s, 1),
        dest=str(dest),
    )
    return dest


if __name__ == "__main__":
    raise SystemExit(
        "src.analysis.m4_critical_windows: run_and_save_critical_windows_report requer "
        "hiperparâmetros calibrados (jump_n_states, jump_penalty, bocpd_hazard_lambda, "
        "bocpd_n_canonical_buckets) e consome orçamento de trial (G-C1-2, <=18 trials) -- "
        "não rode este módulo como script sem autorização explícita do Manager (Fase D do "
        "plano wise-exploring-panda.md). Ver docstring de run_and_save_critical_windows_report "
        "para como chamar manualmente depois da autorização."
    )
