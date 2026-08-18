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

import multiprocessing
import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import structlog

from src.core.provenance import report_provenance

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
    subconjunto usado pela mediana)."""

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


@dataclass(frozen=True, slots=True)
class WindowCandidateSummary:
    """1 (janela, resolução, candidato) -- mediana ENTRE OS SÍMBOLOS
    válidos daquela janela (passo 1 da agregação de 2 níveis, ver
    docstring do módulo). `n_symbols_ok < n_symbols_requested` é o
    sintoma de AG-019 em ação (1+ símbolo falhou/foi pulado nesta janela,
    sem derrubar os outros) -- nunca um crash. `per_symbol` carrega o
    detalhe INDIVIDUAL de cada símbolo OK -- nunca escondido atrás da
    mediana."""

    window_name: str
    event: str
    n_symbols_requested: int
    n_symbols_ok: int
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
    `classifier_id` -- não um valor por janela)."""

    classifier_id: str
    resolution_id: str
    n_states: int
    n_windows_requested: int
    n_windows_ok: int
    separation_omega_squared_median: float
    orthogonality_omega_squared_median: float
    persistence_median_duration_bars_median: float
    persistence_switch_rate_median: float
    fold_stability_adjusted_rand_mean_median: float
    n_oos_obs_total: int
    per_window: tuple[WindowCandidateSummary, ...]


@dataclass(frozen=True, slots=True)
class CellOutcome:
    """Resultado de 1 célula (janela, símbolo) sob 1 resolução --
    `symbol_result=None, error=None` é "folds insuficientes" (`m4.run_
    regime_comparison_for_symbol` devolveu `None`, dado real mas
    insuficiente pra `initial_train_years`); `error is not None` é uma
    EXCEÇÃO real (IO, bug, processo filho morto) -- os 2 casos são
    DIFERENTES (`skipped_cells` vs. `failed_cells` no relatório final),
    nunca colapsados num só."""

    window_name: str
    symbol: str
    resolution_id: str
    symbol_result: m4.SymbolResult | None
    error: str | None = None


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
    `failed_cells`/`skipped_cells` -- nunca escondidos, AG-019."""

    resolution_id: str
    baseline: AggregatedCandidateResult
    candidates: tuple[AggregatedCandidateResult, ...]
    failed_cells: tuple[FailedCell, ...]
    skipped_cells: tuple[SkippedCell, ...]


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
    )


def _window_summary(
    window: CriticalWindow, details: list[SymbolCandidateDetail]
) -> WindowCandidateSummary:
    return WindowCandidateSummary(
        window_name=window.name,
        event=window.event,
        n_symbols_requested=len(window.symbols),
        n_symbols_ok=len(details),
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

    return AggregatedCandidateResult(
        classifier_id=classifier_id,
        resolution_id=resolution_id,
        n_states=n_states,
        n_windows_requested=len(window_summaries),
        n_windows_ok=len(ok_summaries),
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


def aggregate_critical_windows_results(
    resolution_id: str,
    cells: tuple[CellOutcome, ...],
    *,
    windows: tuple[CriticalWindow, ...] = CRITICAL_WINDOWS,
) -> CriticalWindowsReport:
    """Núcleo puro (sem IO) -- recebe `CellOutcome` já calculados (de
    `run_critical_windows_comparison` ou de um teste com fixture
    sintética) e produz `CriticalWindowsReport`. AG-019: células com
    `error is not None` viram `FailedCell`; células com `symbol_result is
    None, error is None` viram `SkippedCell`; nenhuma das duas classes
    participa da agregação (mediana só sobre células OK) -- mas ambas
    ficam listadas no relatório, nunca escondidas."""
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

    return CriticalWindowsReport(
        resolution_id=resolution_id,
        baseline=baseline_agg,
        candidates=candidates_agg,
        failed_cells=failed,
        skipped_cells=skipped,
    )


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
    filho."""
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
        )
    except Exception as exc:  # AG-019 -- 1 célula falhando não derruba as outras
        logger.error(
            "analysis.m4_critical_windows.cell_failed",
            window=window.name,
            symbol=symbol,
            resolution_id=resolution_id,
            error=repr(exc),
        )
        return CellOutcome(window.name, symbol, resolution_id, None, repr(exc))
    if result is None:
        logger.warning(
            "analysis.m4_critical_windows.cell_folds_insuficientes",
            window=window.name,
            symbol=symbol,
            resolution_id=resolution_id,
        )
    return CellOutcome(window.name, symbol, resolution_id, result, None)


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
) -> CriticalWindowsReport:
    """1 resolução completa -- todas as células (janela, símbolo) de
    `windows`, agregadas. `max_workers=1` roda SEQUENCIAL (mesma função
    `_run_one_cell`, sem `ProcessPoolExecutor`) -- usado pelos testes
    (`monkeypatch` em `m4.run_regime_comparison_for_symbol` não alcança
    processos filhos gerados via `spawn`, então o caminho testável é o
    sequencial). `max_workers=None` (default) usa `os.cpu_count()`,
    mesma convenção de `m4_regime_comparison.run_and_save_m4_report`.

    **Custo não medido nesta fase** (Fase D, execução real de 18 trials,
    autorização separada do Manager) -- só smoke test de 1-2 células. Ver
    docstring do módulo, seção "Paralelismo", pro raciocínio de não
    aninhar `ProcessPoolExecutor` entre resoluções."""
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
            for future in as_completed(future_to_cell):
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

    return aggregate_critical_windows_results(resolution_id, tuple(outcomes), windows=windows)


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

_TARGET_FOLD_CAVEAT: Final[str] = (
    "Em TODAS as 4 janelas historicas com evento-alvo unico (LUNA/FTX/CRYPTO_WINTER/"
    "ETF_HALVING), o mes-alvo cai no FOLD 1 (segundo fold de teste produzido), NAO no fold 0 "
    "-- verificado real (generate_anchored_walk_forward_splits) sobre R1/R2/R3 e todos os "
    "simbolos validos de cada janela, 2026-08-18. Causa: a primeira barra real devolvida por "
    "query_dollar_bars cai sempre 1 dia ANTES do start pedido (efeito de fronteira de dia "
    "civil, uniforme entre resolucoes), empurrando a ancoragem trimestral 1 posicao para tras. "
    "Isso NAO invalida o desenho -- o harness agrega TODOS os folds de teste da janela (fold0 "
    "+ fold1 + fold2, nao so o fold-alvo) -- so significa que cada janela cobre ~9 meses de "
    "teste (3 trimestres civis, o 3o quase vazio na maioria dos casos), nao so o mes exato do "
    "evento. Ver CriticalWindow.note por janela para os numeros reais medidos."
)


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
) -> Path:
    """Ponto de entrada real -- itera as `resolutions` (default as 3, R1/
    R2/R3) SEQUENCIALMENTE, cada uma via `run_critical_windows_comparison`
    (que paraleliza internamente por célula), persiste o relatório
    combinado atômico (B29) -- inclusive um CHECKPOINT parcial (`partial:
    true`) a cada resolução concluída, não só no final (ver docstring de
    `_build_report_payload`, achado `project_assurance` 2026-08-18, HIGH).

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
