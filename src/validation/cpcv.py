"""CPCV — validação primária combinatória, purge por `t1` e embargo (§11.4).

**Splitter de verdade, não esqueleto.** Gera os `C(n_groups, n_test_groups)`
splits combinatórios sobre os `t0` reais de `labels/{version}/labels.parquet`
(462.682 linhas, 2020-01→2026-08 nos dois lados — Sprint 6), aplica purge
(remove do treino qualquer observação cujo `[t0, t1]` cruze o período de
teste) e embargo (barras extras removidas nas duas bordas de cada bloco de
teste), e monta os `n_backtest_paths` caminhos de reconstrução do §11.4.

Três decisões de design não triviais, resolvidas aqui e documentadas (não
escondidas):

1. **Grupos são partição CRONOLÓGICA (por tempo), não por contagem de
   linhas.** O PRD anota "`n_groups: 6  # ~1 ano por grupo`" — uma divisão
   de calendário. `assign_time_groups` particiona `[min(t0), max(t0)]` em
   `n_groups` blocos de largura de tempo igual; como a densidade de barras
   de 15m é ~constante ao longo dos ~6,6 anos do dataset (poucos gaps
   reais, ver `known_gaps` em `constants.yaml`), os dois critérios
   coincidem na prática, mas o código implementa literalmente o que o PRD
   descreve, não uma aproximação por contagem.

2. **Purge usa o `t1` REAL de cada linha, não o `purge.min_bars:
   time_stop_bars` do bloco YAML do PRD como margem fixa.** `time_stop_bars`
   (32 barras) é o horizonte MÁXIMO possível de um label — já é o que
   limita `n_bars_held` por construção em `src.labels.triple_barrier`
   (invariante testada em `assert_label_invariants`). Usar o `t1` exato de
   cada observação para decidir overlap com o período de teste é
   estritamente mais correto que aplicar uma margem fixa de 32 barras a
   TODA linha (a maioria dos labels fecha bem antes do `time_stop`, ver
   `n_bars_held` mediano ~7 no dataset real) — banned pattern B09 pede
   "purge por `t1`", que é exatamente isto, não "purge por uma margem
   conservadora".

   **2b. AG-032/E4 (2026-08-16) — a fronteira direita do purge é `g_end_
   effective`, não `g_end` cru.** `g_end` (fim do grupo de teste) vem só
   da partição de `t0` (`assign_time_groups`) — mas o `t1` REAL das linhas
   de TESTE daquele grupo pode esticar além dele (horizonte do label,
   "componente 32"). `g_end_effective = max(g_end, max(t1 das linhas cujo
   t0 caiu no grupo))` fecha esse resíduo. Isto é diferente — e não
   resolve sozinho — o "componente 96": a janela de LOOKBACK de uma
   feature de TREINO (ex. `feature_c06_vol_ratio_long_window`, 96 barras)
   alcançando pra TRÁS, através de `g_end_effective`, pra dentro do
   território de teste. Overlap de intervalo de LABEL (o que o purge
   sempre checou) e alcance de JANELA DE FEATURE são mecanicamente
   diferentes — por isso `max_feature_lookback_ms` (`CPCVConfig`, default
   `0` = comportamento de sempre) existe como parâmetro à parte, nunca
   inferido. Teste que isola só o componente 96, sem nenhum overlap de
   label envolvido:
   `test_generate_splits_purge_cobre_lookback_de_feature_de_treino_apos_g_end`
   (`tests/unit/test_validation_cpcv.py`). O EMBARGO (`embargo_mask`,
   `generate_splits`) deliberadamente NÃO usa `g_end_effective` — continua
   em `g_end` cru; redesenho do embargo (E1, AG-032) é passo separado,
   pendente do resultado deste fix. Efeito colateral esperado sobre dado
   real: `purge_mask` mais abrangente pode realocar linhas que antes
   contavam como `n_embargoed` pra `n_purged` (nunca o contrário) — leia
   os dois números juntos, não isoladamente, ao comparar `summarize_
   splits()` antes/depois desta correção.

3. **`n_backtest_paths` via 1-fatoração de K_n_groups (round-robin/"circle
   method"), não hardcoded.** Com `n_groups=6` e `n_test_groups=2`, há
   `C(6,2)=15` splits e `phi=C(5,1)=5` caminhos completos de reconstrução
   (cada caminho cobre os 6 grupos exatamente uma vez, encadeando as
   previsões OOS dos splits que o compõem) — a mesma estrutura combinatória
   de um calendário de torneio round-robin (K6 tem uma 1-fatoração clássica
   em 5 emparelhamentos perfeitos). Implementado só para `n_test_groups=2`
   (o caso do PRD); generalizar para outro `k` exigiria um desenho
   combinatório diferente, não construído aqui por falta de caso de uso
   real a testar contra.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb
from typing import Final

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from src.data.resample import step_ms

from ._constants import load_constant
from ._paths import labels_symbol_tf_dir

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]

# AG-004 (audit/architecture_gaps_log.yaml) — até a correção original,
# `_BAR_MS` era uma constante de MÓDULO fixa em `step_ms("15m")`, usada pra
# converter um embargo em CONTAGEM DE BARRA pra milissegundos. Rodar CPCV
# para M30/H1 com essa constante fixa em 15m produzia embargo em UNIDADE DE
# TEMPO ERRADA silenciosamente. `tf` virou campo de `CPCVConfig` (default
# "15m" — bit-exato pra todo caller existente) pra resolver `step_ms(cfg.tf)`
# corretamente.
#
# AG-032/E1 (2026-08-16) — SUPERSEDE o parágrafo acima pro embargo
# especificamente: `embargo_bars * step_ms(tf)` foi trocado por `embargo_ms`
# direto (medido, não mais contagem de barra). O bug de AG-004 (escalar por
# TF errado) deixa de poder existir pra embargo, por construção — não porque
# foi corrigido de novo, mas porque a unidade de origem não é mais barra.
# `tf` continua existindo em `CPCVConfig` -- `grade_id` (AG-037, implementado
# 2026-08-16) é quem agora governa `__post_init__`/`assert_grade_consistent`;
# `tf` vira só a base de derivação default de `grade_id` pra grade de tempo.
_DEFAULT_TF: Final[str] = "15m"

# AG-009 (audit/architecture_gaps_log.yaml) — `load_labels_v1(tf=...)` (que
# resolve QUAL arquivo de dado é lido) e `CPCVConfig(tf=...)` (que resolve
# `step_ms` no cálculo do embargo) são dois parâmetros passados
# INDEPENDENTEMENTE pelo caller — nada os ligava estruturalmente até esta
# correção. `assert_grade_consistent` (renomeada de `assert_tf_consistent`,
# AG-037, 2026-08-16) fecha o gap medindo o espaçamento REAL de `t0` no
# `labels` carregado contra `step_ms(config.grade_id)`; `_GRADE_CONSISTENCY_
# RTOL` é a tolerância dessa medição — folgada o bastante para não reagir a
# gaps reais do dataset (poucos, ver `known_gaps`), apertada o bastante para
# pegar qualquer TF suportado hoje trocado por outro (15m/30m/1h diferem
# entre si por um fator >= 2x, bem acima de 5%). Tolerância de MEDIÇÃO/
# checagem estrutural, não hiperparâmetro de domínio — mesma classe de
# `leakage.py::tolerance = 1e-6` (marcado `noqa: magic-number`, não
# `constants.yaml`).
_GRADE_CONSISTENCY_RTOL: Final[float] = 0.05  # noqa: magic-number


class CPCVError(Exception):
    """Base para erros de configuração/geração do CPCV."""


# ============================================================================
# Config — bloco de constantes de constants.yaml, lido uma única vez.
# ============================================================================


@dataclass(frozen=True, slots=True)
class CPCVConfig:
    n_groups: int
    n_test_groups: int
    embargo_ms: int
    """AG-032/E1 (2026-08-16) — distância de relógio (ms) removida nas duas
    bordas de cada bloco de teste, protegendo só correlação serial (fenômeno
    de relógio, por isso relógio, não contagem de barra — E2/E3 rejeitados).
    Substitui `embargo_bars` (aposentado): não depende mais de `step_ms(tf)`
    nem de quantas barras "cabem" numa duração — imune à densidade de
    dollar bar, e não precisa saber o que uma "barra" significa sob a nova
    grade. Valor de produção vem de `cpcv_embargo_ms` (constants.yaml,
    MEASURED — 1% da largura real de cada grupo cronológico do CPCV,
    medido via `tools/diagnostics/measure_cpcv_embargo_clock_candidate.py`
    sobre o dataset real). Depende de E4 (`max_feature_lookback_ms`) estar
    de fato cabeado num caller real de produção pra cobrir o componente 96
    — sem isso, este valor protege só correlação serial, não o lookback de
    feature de treino (ver item 2b da docstring do módulo)."""
    tf: str = _DEFAULT_TF
    """Timeframe de decisão desta rodada — NÃO é constante de domínio
    (não vem de `constants.yaml`, por isso `from_constants()` a recebe como
    parâmetro em vez de carregá-la): é um parâmetro de execução, como
    `symbol` em `load_labels_v1`. Determina `step_ms(tf)` no cálculo do
    embargo (AG-004). Default preserva todo caller existente bit-exato."""
    grade_id: str | None = None
    """AG-037 (2026-08-16) — identidade REAL da grade sob a qual `labels`
    foi gerado (docs/refactor_dollar_bar_canonico.md §3.6 item 2, AG-042).
    `tf` conflava dois papéis: "qual grade" E "como converter pra
    milissegundos" — `grade_id` separa o primeiro papel do segundo.
    `None` (default) deriva pra `self.tf` em `__post_init__`
    (`object.__setattr__`, dataclass `frozen`) — bit-exato pra TODO caller
    existente, já que nenhum passa `grade_id` hoje e `grade_id == tf` pra
    qualquer grade de TEMPO. Só grade de tempo existe em produção
    (`canonical_bar_type=dollar` decidido, deployment não iniciado) — um
    `grade_id` explícito fora do dict fechado de `step_ms` faz
    `assert_grade_consistent` levantar `NotImplementedError`, não fingir
    verificar o que não tem mecanismo ainda."""
    max_feature_lookback_ms: int = 0
    """AG-032/E4 (2026-08-16) — maior janela de LOOKBACK entre as features
    do vetor de treino (ex. `feature_c06_vol_ratio_long_window`=96 barras),
    convertida pra duração de relógio pelo CALLER (`96 * step_ms(tf)` sob
    grade de tempo hoje; sob dollar bar, exigiria uma medição própria —
    fora do escopo desta correção). NÃO é lida de `constants.yaml` aqui de
    propósito: `validation/` não conhece `features/registry.yaml`
    (hierarquia de camada, CLAUDE.md) — quem monta o `CPCVConfig` real
    decide o valor. Default `0` preserva bit-exato todo caller existente
    (a condição de purge que este parâmetro habilita vira sempre-falsa com
    `0`, ver `generate_splits`). Cobre o "componente 96" do achado AG-032 —
    ver item 2b da docstring do módulo."""

    @classmethod
    def from_constants(
        cls,
        *,
        tf: str = _DEFAULT_TF,
        grade_id: str | None = None,
        max_feature_lookback_ms: int = 0,
    ) -> CPCVConfig:
        return cls(
            n_groups=int(load_constant("cpcv_n_groups")),
            n_test_groups=int(load_constant("cpcv_n_test_groups")),
            embargo_ms=int(load_constant("cpcv_embargo_ms")),
            tf=tf,
            grade_id=grade_id,
            max_feature_lookback_ms=max_feature_lookback_ms,
        )

    def __post_init__(self) -> None:
        if self.n_groups < 2:
            raise CPCVError(f"n_groups precisa ser >= 2, recebido {self.n_groups}")
        if not (1 <= self.n_test_groups < self.n_groups):
            raise CPCVError(
                f"n_test_groups precisa estar em [1, n_groups), recebido "
                f"{self.n_test_groups} com n_groups={self.n_groups}"
            )
        if self.embargo_ms < 0:
            raise CPCVError(f"embargo_ms precisa ser >= 0, recebido {self.embargo_ms}")
        if self.max_feature_lookback_ms < 0:
            raise CPCVError(
                "max_feature_lookback_ms precisa ser >= 0, recebido "
                f"{self.max_feature_lookback_ms}"
            )
        # step_ms levanta KeyError/ValueError pra tf desconhecido — falha alto
        # aqui, na construção, em vez de silenciosamente mais tarde dentro de
        # generate_splits (mesma disciplina de "falhar cedo e alto" do resto
        # do módulo, ver assign_time_groups).
        step_ms(self.tf)
        # AG-037 — grade_id=None deriva pra tf (retrocompatível, bit-exato:
        # todo caller existente tem grade_id==tf). object.__setattr__ porque
        # o dataclass é frozen -- mesmo padrão que seria necessário em
        # qualquer derivação de default no __post_init__ de um frozen.
        if self.grade_id is None:
            object.__setattr__(self, "grade_id", self.tf)

    @property
    def n_splits(self) -> int:
        """`C(n_groups, n_test_groups)` — puramente combinatório, NÃO uma
        constante própria de `constants.yaml` (ver nota no bloco YAML do
        arquivo: declarar os dois separadamente arriscaria inconsistência)."""
        return comb(self.n_groups, self.n_test_groups)

    @property
    def n_backtest_paths(self) -> int:
        """`C(n_groups - 1, n_test_groups - 1)` = phi do §11.4 — número de
        caminhos completos de reconstrução do backtest. Para
        `n_groups=6, n_test_groups=2`: `C(5,1)=5`, batendo com o
        `n_backtest_paths: 5` citado no bloco YAML do PRD."""
        return comb(self.n_groups - 1, self.n_test_groups - 1)


# ============================================================================
# Grupos cronológicos — partição de [min(t0), max(t0)] em n_groups blocos.
# ============================================================================


def assign_time_groups(t0_ms: IntArray, n_groups: int) -> tuple[IntArray, IntArray]:
    """Partição CRONOLÓGICA (não por contagem) de `t0_ms` em `n_groups`
    blocos de largura de tempo igual — ver item 1 da docstring do módulo.

    Retorna `(group_id, edges_ms)`: `group_id[i]` em `[0, n_groups)` para
    cada linha; `edges_ms` tem `n_groups + 1` fronteiras em epoch-ms, onde
    o grupo `g` cobre `[edges_ms[g], edges_ms[g+1])` (a última fronteira é
    `max(t0_ms) + 1` para incluir o próprio máximo no último grupo)."""
    if t0_ms.shape[0] == 0:
        raise CPCVError("assign_time_groups: t0_ms vazio")

    t_min = int(t0_ms.min())
    t_max = int(t0_ms.max())
    if t_min == t_max:
        raise CPCVError("assign_time_groups: t0_ms tem um único instante — não particionável")

    edges = np.linspace(t_min, t_max, n_groups + 1)
    edges_ms = np.round(edges).astype(np.int64)
    edges_ms[0] = t_min
    edges_ms[-1] = t_max + 1  # fronteira direita exclusiva cobre o próprio máximo
    # linspace pode produzir fronteiras não estritamente crescentes se
    # n_groups > número de valores distintos de t_ms — não é o caso real
    # (462k linhas, 6 grupos), mas falha alto em vez de produzir grupos
    # vazios silenciosamente caso alguém chame isto com um recorte minúsculo.
    if not np.all(np.diff(edges_ms) > 0):
        raise CPCVError(
            f"assign_time_groups: fronteiras não estritamente crescentes para n_groups="
            f"{n_groups} sobre {t0_ms.shape[0]} observações — intervalo de tempo "
            "insuficiente para esta granularidade"
        )

    group_id = np.searchsorted(edges_ms, t0_ms, side="right") - 1
    group_id = np.clip(group_id, 0, n_groups - 1)
    return group_id.astype(np.int64), edges_ms


# ============================================================================
# 1-fatoração de K_n (round-robin/"circle method") — atribuição de splits a
# n_backtest_paths. Puramente combinatório (não é parâmetro de domínio, não
# precisa de proveniência em constants.yaml — §16.10 é sobre constantes de
# domínio, não sobre estrutura matemática determinística).
# ============================================================================


def _round_robin_1_factorization(n: int) -> list[list[tuple[int, ...]]]:
    """1-fatoração de K_n (n par, n >= 2) em `n - 1` emparelhamentos
    perfeitos disjuntos — "circle method" clássico de escalonamento
    round-robin. Cada rodada (caminho) é uma lista de `n / 2` pares
    disjuntos que juntos cobrem `{0, .., n-1}` exatamente uma vez; ao longo
    das `n - 1` rodadas, os `C(n, 2)` pares distintos aparecem cada um
    exatamente uma vez (propriedade padrão do algoritmo, verificada em
    `tests/unit/test_validation_cpcv.py`)."""
    if n < 2 or n % 2 != 0:
        raise CPCVError(f"1-fatoração de K_n requer n par >= 2, recebido {n}")

    fixed = 0
    rotating = list(range(1, n))
    rounds: list[list[tuple[int, ...]]] = []
    for _ in range(n - 1):
        pairs = [(fixed, rotating[0])]
        left, right = 1, len(rotating) - 1
        while left < right:
            pairs.append((rotating[left], rotating[right]))
            left += 1
            right -= 1
        rounds.append([(min(a, b), max(a, b)) for a, b in pairs])
        rotating = rotating[1:] + rotating[:1]
    return rounds


def _path_assignment(n_groups: int) -> dict[tuple[int, ...], int]:
    """`{par_de_grupos_de_teste: path_id}` — só definido para
    `n_test_groups == 2` (ver item 3 da docstring do módulo)."""
    rounds = _round_robin_1_factorization(n_groups)
    mapping: dict[tuple[int, ...], int] = {}
    for path_id, pairs in enumerate(rounds):
        for pair in pairs:
            mapping[pair] = path_id
    return mapping


# ============================================================================
# AG-009 — guarda cruzada entre o `tf` real de `labels` e `CPCVConfig.tf`.
# ============================================================================


def _embargo_ms(config: CPCVConfig) -> int:
    """Retorna `config.embargo_ms` diretamente — extraído em função própria
    (antes inline, duplicado em `generate_splits` e `assert_embargo_
    respected`) pra que os dois caminhos usem literalmente a MESMA linha de
    código, não duas cópias que podem divergir silenciosamente uma da outra.

    AG-032/E1 (2026-08-16): até esta correção, retornava `config.embargo_
    bars * step_ms(config.tf)` — mantida como função (não inlined de volta
    pro campo direto) porque o histórico de por que ela existe (AG-004,
    duas cópias divergindo) continua valendo como razão estrutural, mesmo
    a fórmula tendo simplificado."""
    return config.embargo_ms


def assert_grade_consistent(labels: pl.DataFrame, config: CPCVConfig) -> None:
    """AG-009/AG-037 (audit/architecture_gaps_log.yaml) — guarda cruzada
    entre a grade REAL de `labels` (hoje sempre um TF — o TF em que os `t0`
    foram gerados, ex. via `load_labels_v1(tf=...)`) e `config.grade_id`.
    Renomeada de `assert_tf_consistent` (AG-037, 2026-08-16) -- `tf`
    conflava dois papéis (qual grade + como converter pra ms);
    `config.grade_id` (deriva de `config.tf` por default, retrocompatível)
    é agora a identidade que esta guarda verifica. Os dois (`tf` de
    `labels` e `grade_id`/`tf` de `config`) são hoje parâmetros passados
    INDEPENDENTEMENTE pelo caller — `load_labels_v1` não conhece o
    `CPCVConfig` que vai rodar depois — então nada os liga estruturalmente
    sem esta checagem. Sem ela, um caller poderia escrever
    `load_labels_v1(tf="30m")` + `CPCVConfig.from_constants()` (default
    `tf="15m"`) e computar o embargo na unidade ERRADA silenciosamente —
    mesma classe de bug que AG-004 fechou, um nível acima (composição de
    duas funções em vez de uma constante única).

    Mede o espaçamento real de `t0` como a MEDIANA do diff entre valores
    ordenados e deduplicados — não o mínimo, não uma checagem de
    uniformidade estrita. Dado real tem gaps (poucos — ver `known_gaps`
    em `constants.yaml`; item 1 da docstring do módulo: "densidade ~
    constante ao longo dos ~6,6 anos, poucos gaps reais"), então exigir
    espaçamento perfeitamente uniforme quebraria o caso normal; a mediana
    é robusta a uma MINORIA de gaps maiores que o step nominal, desde que
    a maioria das barras seja consecutiva.

    Levanta `CPCVError` se a mediana do diff não bate com
    `step_ms(config.grade_id)` dentro de `_GRADE_CONSISTENCY_RTOL` —
    calibrada pra pegar o caso real (TF trocado por outro suportado, que
    difere por um fator >= 2x), não pra exigir precisão maior que o
    necessário. Não levanta se `labels` tiver menos de 2 `t0` distintos —
    não há diff pra medir; `assign_time_groups`, chamada logo depois dentro
    de `generate_splits`, já rejeita esse caso com uma mensagem própria.

    Levanta `NotImplementedError` se `config.grade_id` não for uma grade de
    TEMPO conhecida por `step_ms` (ex. uma futura grade dollar/`R1`/`R2`) —
    verificar identidade de grade não-tempo por mediana de espaçamento não
    funciona (dollar bars não têm espaçamento constante por desenho) e
    NENHUM mecanismo alternativo existe ainda, porque não há caller de
    produção real (`canonical_bar_type=dollar` decidido,
    docs/refactor_dollar_bar_canonico.md, deployment não iniciado). Falhar
    explícito aqui é mais honesto que fingir que a checagem de hoje
    generaliza."""
    t0_ms = labels["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    t0_unique_sorted = np.unique(t0_ms)
    if t0_unique_sorted.shape[0] < 2:
        return

    grade_id = config.grade_id
    assert grade_id is not None  # __post_init__ sempre resolve pra str
    try:
        expected_ms = float(step_ms(grade_id))
    except (KeyError, ValueError) as exc:
        raise NotImplementedError(
            f"assert_grade_consistent: grade_id={grade_id!r} não é uma grade de "
            "TEMPO conhecida -- verificação de identidade pra grade dollar/volume "
            "ainda não tem mecanismo implementado (AG-037/AG-042), porque não há "
            "caller de produção real até dollar bar ser implantado."
        ) from exc

    median_diff_ms = float(np.median(np.diff(t0_unique_sorted)))
    if abs(median_diff_ms - expected_ms) > _GRADE_CONSISTENCY_RTOL * expected_ms:
        raise CPCVError(
            "AG-009: espaçamento real de `t0` em `labels` (mediana="
            f"{median_diff_ms:.0f}ms) não bate com step_ms(config.grade_id="
            f"{grade_id!r})={expected_ms:.0f}ms — `labels` provavelmente foi "
            "carregado com um `tf` diferente do usado em `CPCVConfig` (ex. "
            "`load_labels_v1(tf=\"30m\")` combinado com o default `tf=\"15m\"` de "
            "`CPCVConfig`/`CPCVConfig.from_constants()`). Passe o MESMO `tf` "
            "(ou `grade_id` explícito) nos dois lados."
        )


# ============================================================================
# Splits — purge por t1 real + embargo simétrico nas bordas do bloco de teste.
# ============================================================================


@dataclass(frozen=True, slots=True)
class CPCVSplit:
    split_id: int
    path_id: int
    test_groups: tuple[int, ...]
    train_groups: tuple[int, ...]  # os n_groups - n_test_groups grupos candidatos, antes do purge
    train_idx: IntArray  # posições em `labels`, JÁ com purge + embargo aplicados
    test_idx: IntArray  # posições em `labels` dos grupos de teste, sem alteração
    n_train_candidate: int  # tamanho do treino ANTES de purge/embargo (referência)
    n_purged: int
    n_embargoed: int


@dataclass(frozen=True, slots=True)
class CPCVResult:
    config: CPCVConfig
    group_id: IntArray
    edges_ms: IntArray
    splits: tuple[CPCVSplit, ...]


def generate_splits(labels: pl.DataFrame, config: CPCVConfig | None = None) -> CPCVResult:
    """Núcleo do CPCV (§11.4). `labels` precisa ter `t0`/`t1` (datetime,
    UTC) — mesmo schema de `labels/{version}/labels.parquet`
    (`src.labels.triple_barrier.LABEL_COLUMNS`). Não filtra por `side`: o
    chamador decide se quer rodar sobre os dois lados juntos (como este
    módulo é testado, contra o arquivo real) ou sobre um lado de cada vez
    (como o Alpha vai consumir no Sprint 8, um modelo binário por lado,
    B18) — a lógica de purge/embargo não depende de `side`, só de
    `t0`/`t1`.

    Levanta `CPCVError` se `n_test_groups != 2` (reconstrução de
    `n_backtest_paths` só implementada para pares, ver item 3 da docstring
    do módulo). Levanta `CPCVError` (AG-009) se o espaçamento real de `t0`
    em `labels` não bater com `step_ms(config.grade_id)` — roda SEMPRE, sem
    opt-out, porque é aqui (não em `load_labels_v1`, que não conhece o
    `CPCVConfig` usado depois) que as duas metades da informação — dado
    carregado e config declarada — finalmente se encontram; ver
    `assert_grade_consistent`.

    Purge (item 2b): fronteira direita usa `g_end_effective` (cobre o `t1`
    real de teste esticando além de `g_end`) e, se `config.max_feature_
    lookback_ms > 0`, também cobre a janela de lookback de features de
    treino alcançando pra trás através de `g_end_effective` — AG-032/E4."""
    cfg = config if config is not None else CPCVConfig.from_constants()
    if labels.is_empty():
        raise CPCVError("generate_splits: labels vazio")
    if cfg.n_test_groups != 2:
        raise CPCVError(
            "generate_splits: atribuição de n_backtest_paths só implementada para "
            f"n_test_groups=2 (1-fatoração de pares) — recebido {cfg.n_test_groups}"
        )
    assert_grade_consistent(labels, cfg)

    t0_ms = labels["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    t1_ms = labels["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    n = t0_ms.shape[0]

    group_id, edges_ms = assign_time_groups(t0_ms, cfg.n_groups)
    embargo_ms = _embargo_ms(cfg)
    path_by_pair = _path_assignment(cfg.n_groups)

    row_idx_all = np.arange(n, dtype=np.int64)
    splits: list[CPCVSplit] = []

    for split_id, test_groups in enumerate(combinations(range(cfg.n_groups), cfg.n_test_groups)):
        test_mask = np.isin(group_id, test_groups)
        train_groups = tuple(g for g in range(cfg.n_groups) if g not in test_groups)
        train_candidate_mask = np.isin(group_id, train_groups)

        purge_mask = np.zeros(n, dtype=bool)
        embargo_mask = np.zeros(n, dtype=bool)
        for g in test_groups:
            g_start = int(edges_ms[g])
            g_end = int(edges_ms[g + 1]) - 1  # fronteira direita é exclusiva

            # AG-032/E4, componente 32 — g_end vem só da partição de t0
            # (assign_time_groups), mas o t1 REAL das linhas de TESTE deste
            # grupo pode esticar além dele (horizonte do label). g_end_
            # effective fecha esse resíduo; sem ele, uma linha de treino
            # com t0 no intervalo (g_end, g_end_effective] escaparia do
            # purge (ver item 2b da docstring do módulo).
            group_rows_mask = group_id == g
            g_end_effective = g_end
            if group_rows_mask.any():
                g_end_effective = max(g_end, int(t1_ms[group_rows_mask].max()))

            # purge (B09) — qualquer [t0, t1] que CRUZE [g_start, g_end_effective]
            purge_mask |= (t0_ms <= g_end_effective) & (t1_ms >= g_start)
            if cfg.max_feature_lookback_ms > 0:
                # AG-032/E4, componente 96 — linha de treino já depois de
                # g_end_effective (não pega pelo check acima) cuja janela
                # de LOOKBACK de feature (t0 - max_feature_lookback_ms)
                # alcança pra dentro do território de teste. Mecanicamente
                # diferente do componente 32 (overlap de intervalo de
                # LABEL) — é alcance de JANELA DE FEATURE, por isso é uma
                # condição própria, não uma extensão do g_end_effective
                # acima.
                purge_mask |= (t0_ms > g_end_effective) & (
                    (t0_ms - cfg.max_feature_lookback_ms) <= g_end_effective
                )

            # embargo — barras extras removidas nas DUAS bordas do bloco de
            # teste. Fronteira NÃO muda pra g_end_effective aqui de
            # propósito — redesenho do embargo (E1, AG-032) é passo
            # separado, depende do resultado empírico deste fix (ver
            # docstring do módulo); mudar as duas coisas juntas
            # confundiria qual delas fechou o quê.
            embargo_mask |= (t0_ms > g_end) & (t0_ms <= g_end + embargo_ms)
            embargo_mask |= (t0_ms < g_start) & (t0_ms >= g_start - embargo_ms)

        exclude_mask = purge_mask | embargo_mask
        train_mask = train_candidate_mask & ~exclude_mask

        n_purged = int((train_candidate_mask & purge_mask).sum())
        # embargoed contado só onde NÃO já purgado, pra não contar a mesma
        # linha duas vezes quando as duas janelas se sobrepõem perto da borda
        n_embargoed = int((train_candidate_mask & embargo_mask & ~purge_mask).sum())

        splits.append(
            CPCVSplit(
                split_id=split_id,
                path_id=path_by_pair[test_groups],
                test_groups=test_groups,
                train_groups=train_groups,
                train_idx=row_idx_all[train_mask],
                test_idx=row_idx_all[test_mask],
                n_train_candidate=int(train_candidate_mask.sum()),
                n_purged=n_purged,
                n_embargoed=n_embargoed,
            )
        )

    result = CPCVResult(
        config=cfg, group_id=group_id, edges_ms=edges_ms, splits=tuple(splits)
    )
    logger.info(
        "validation.cpcv.generate_splits",
        n_rows=n,
        n_groups=cfg.n_groups,
        n_test_groups=cfg.n_test_groups,
        n_splits=cfg.n_splits,
        n_backtest_paths=cfg.n_backtest_paths,
        embargo_ms=cfg.embargo_ms,
    )
    return result


# ============================================================================
# Teste 6 do §11.5 — a checagem central: nenhum t1 de treino cruza o teste.
# ============================================================================


def assert_no_train_t1_leaks_into_test(labels: pl.DataFrame, result: CPCVResult) -> None:
    """§11.5 teste 6 ("contaminação de label — `t1` de treino nunca cruza
    janela de teste") como função reusável — chamada pelos testes E
    disponível para `src.validation.leakage` reportar como PASS/FAIL real,
    não um `assert` solto. Levanta `AssertionError` com a contagem de
    violações POR split na primeira falha; nunca ignora silenciosamente.

    AG-032/E4 (2026-08-16) — usa `g_end_effective` (mesma correção de
    `generate_splits`, item 2b da docstring do módulo), não `g_end` cru:
    do contrário este verificador validaria contra uma fronteira mais
    fraca que a que o purge de fato aplica, e não pegaria uma regressão se
    o fix de `g_end_effective` fosse revertido em `generate_splits` sem
    tocar aqui."""
    t0_ms = labels["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    t1_ms = labels["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)

    violations: list[str] = []
    for split in result.splits:
        if split.train_idx.shape[0] == 0:
            continue
        train_t0 = t0_ms[split.train_idx]
        train_t1 = t1_ms[split.train_idx]
        for g in split.test_groups:
            g_start = int(result.edges_ms[g])
            g_end = int(result.edges_ms[g + 1]) - 1
            group_rows_mask = result.group_id == g
            g_end_effective = g_end
            if group_rows_mask.any():
                g_end_effective = max(g_end, int(t1_ms[group_rows_mask].max()))
            bad = (train_t0 <= g_end_effective) & (train_t1 >= g_start)
            n_bad = int(bad.sum())
            if n_bad:
                violations.append(
                    f"split {split.split_id} (test_groups={split.test_groups}): "
                    f"{n_bad} linha(s) de treino com [t0,t1] cruzando o grupo de teste {g}"
                )

    if violations:
        raise AssertionError(
            f"{len(violations)} violação(ões) de purge (B09/§11.5 teste 6) — treino vaza "
            "para dentro do período de teste:\n" + "\n".join(violations)
        )


def assert_embargo_respected(labels: pl.DataFrame, result: CPCVResult) -> None:
    """Checagem complementar (não um dos 14 testes do §11.5, mas parte
    direta da especificação `embargo:` do bloco YAML do PRD): nenhuma linha
    de treino tem `t0` dentro da janela de embargo nas bordas de qualquer
    grupo de teste do split."""
    t0_ms = labels["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    embargo_ms = _embargo_ms(result.config)

    violations: list[str] = []
    for split in result.splits:
        if split.train_idx.shape[0] == 0:
            continue
        train_t0 = t0_ms[split.train_idx]
        for g in split.test_groups:
            g_start = int(result.edges_ms[g])
            g_end = int(result.edges_ms[g + 1]) - 1
            bad = ((train_t0 > g_end) & (train_t0 <= g_end + embargo_ms)) | (
                (train_t0 < g_start) & (train_t0 >= g_start - embargo_ms)
            )
            n_bad = int(bad.sum())
            if n_bad:
                violations.append(
                    f"split {split.split_id} (test_groups={split.test_groups}): "
                    f"{n_bad} linha(s) de treino dentro da janela de embargo do grupo {g}"
                )

    if violations:
        raise AssertionError(
            f"{len(violations)} violação(ões) de embargo — treino cai nas barras de "
            "embargo ao redor do bloco de teste:\n" + "\n".join(violations)
        )


# ============================================================================
# Relatório — tabela por split, para o runner de leakage/CLI.
# ============================================================================


def summarize_splits(result: CPCVResult) -> pl.DataFrame:
    """Uma linha por split: grupos de teste/treino, tamanhos, purge/embargo."""
    rows = [
        {
            "split_id": s.split_id,
            "path_id": s.path_id,
            "test_groups": list(s.test_groups),
            "train_groups": list(s.train_groups),
            "n_train_candidate": s.n_train_candidate,
            "n_train": int(s.train_idx.shape[0]),
            "n_test": int(s.test_idx.shape[0]),
            "n_purged": s.n_purged,
            "n_embargoed": s.n_embargoed,
        }
        for s in result.splits
    ]
    return pl.DataFrame(rows)


# ============================================================================
# IO — labels/v1/labels.parquet real.
# ============================================================================


def load_labels_v1(
    version: str = "v1", *, symbol: str = "BTCUSDT", tf: str = _DEFAULT_TF
) -> pl.DataFrame:
    """`data/labels/{symbol}/{tf}/{version}/labels.parquet` — insumo real do
    CPCV (Sprint 6). Levanta `FileNotFoundError` com mensagem acionável se
    ainda não foi gerado (nunca inventa um dataset sintético no caminho
    real).

    Layout chaveado (T0.3, PRD_V4_1.md §3.1) — migrado de `labels/v1/
    labels.parquet` (caminho legado pré-V4.1) para
    `data/labels/BTCUSDT/15m/v1/` nesta mesma rodada; `symbol`/`tf` default
    preservam o artefato real já existente no local atual. `tf` adicionado
    junto da correção AG-004 — o caller que passar `tf` não-default aqui
    também precisa passar o MESMO `tf` em `CPCVConfig`, senão o embargo é
    calculado numa unidade diferente da dos dados carregados. Isto já NÃO
    é mais só responsabilidade documentada do caller (AG-009): o
    `DataFrame` retornado por esta função, se passado para
    `generate_splits` com um `CPCVConfig.tf` divergente, agora levanta
    `CPCVError` (`assert_grade_consistent`, medindo o espaçamento real de
    `t0` contra `step_ms(config.grade_id)`) em vez de calcular o embargo
    silenciosamente errado."""
    path = labels_symbol_tf_dir(symbol, version, tf=tf) / "labels.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"labels não encontrado em {path} — rode `uv run quant labels build` primeiro "
            "(src.labels.triple_barrier.build_labels_for_symbol + write_labels_atomic)"
        )
    return pl.read_parquet(path)


if __name__ == "__main__":  # pragma: no cover — execução manual
    # Mesmo padrão de `src.data.validate`: este bloco é para
    # `python -m src.validation.cpcv`; um entry point real
    # (`scripts/run_validation_cpcv.py`) chamaria `configure_logging()`
    # antes de invocar o núcleo.
    import sys

    def _run_cli() -> int:
        labels_df = load_labels_v1()
        cpcv_result = generate_splits(labels_df)
        assert_no_train_t1_leaks_into_test(labels_df, cpcv_result)
        assert_embargo_respected(labels_df, cpcv_result)
        summary = summarize_splits(cpcv_result)
        logger.info(
            "validation.cpcv.cli_done",
            n_splits=cpcv_result.config.n_splits,
            n_backtest_paths=cpcv_result.config.n_backtest_paths,
            summary=summary.to_dicts(),
        )
        return 0

    sys.exit(_run_cli())
