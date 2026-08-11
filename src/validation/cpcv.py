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

# Fato de calendário do TF de decisão atual (§0.1 decision_tf=15m) — mesmo
# raciocínio de `_BAR_MS` em `src.labels.triple_barrier`: não é hiperparâmetro,
# é a própria definição de barra do pipeline corrente.
_BAR_MS: Final[int] = step_ms("15m")


class CPCVError(Exception):
    """Base para erros de configuração/geração do CPCV."""


# ============================================================================
# Config — bloco de constantes de constants.yaml, lido uma única vez.
# ============================================================================


@dataclass(frozen=True, slots=True)
class CPCVConfig:
    n_groups: int
    n_test_groups: int
    embargo_bars: int

    @classmethod
    def from_constants(cls) -> CPCVConfig:
        return cls(
            n_groups=int(load_constant("cpcv_n_groups")),
            n_test_groups=int(load_constant("cpcv_n_test_groups")),
            embargo_bars=int(load_constant("cpcv_embargo_bars")),
        )

    def __post_init__(self) -> None:
        if self.n_groups < 2:
            raise CPCVError(f"n_groups precisa ser >= 2, recebido {self.n_groups}")
        if not (1 <= self.n_test_groups < self.n_groups):
            raise CPCVError(
                f"n_test_groups precisa estar em [1, n_groups), recebido "
                f"{self.n_test_groups} com n_groups={self.n_groups}"
            )
        if self.embargo_bars < 0:
            raise CPCVError(f"embargo_bars precisa ser >= 0, recebido {self.embargo_bars}")

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
    do módulo)."""
    cfg = config if config is not None else CPCVConfig.from_constants()
    if labels.is_empty():
        raise CPCVError("generate_splits: labels vazio")
    if cfg.n_test_groups != 2:
        raise CPCVError(
            "generate_splits: atribuição de n_backtest_paths só implementada para "
            f"n_test_groups=2 (1-fatoração de pares) — recebido {cfg.n_test_groups}"
        )

    t0_ms = labels["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    t1_ms = labels["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    n = t0_ms.shape[0]

    group_id, edges_ms = assign_time_groups(t0_ms, cfg.n_groups)
    embargo_ms = cfg.embargo_bars * _BAR_MS
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
            # purge (B09) — qualquer [t0, t1] que CRUZE [g_start, g_end]
            purge_mask |= (t0_ms <= g_end) & (t1_ms >= g_start)
            # embargo — barras extras removidas nas DUAS bordas do bloco de teste
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
        embargo_bars=cfg.embargo_bars,
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
    violações POR split na primeira falha; nunca ignora silenciosamente."""
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
            bad = (train_t0 <= g_end) & (train_t1 >= g_start)
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
    embargo_ms = result.config.embargo_bars * _BAR_MS

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


def load_labels_v1(version: str = "v1", *, symbol: str = "BTCUSDT") -> pl.DataFrame:
    """`data/labels/{symbol}/15m/{version}/labels.parquet` — insumo real do
    CPCV (Sprint 6). Levanta `FileNotFoundError` com mensagem acionável se
    ainda não foi gerado (nunca inventa um dataset sintético no caminho
    real).

    Layout chaveado (T0.3, PRD_V4_1.md §3.1) — migrado de `labels/v1/
    labels.parquet` (caminho legado pré-V4.1) para
    `data/labels/BTCUSDT/15m/v1/` nesta mesma rodada; `symbol` default
    preserva o artefato real já existente no novo local."""
    path = labels_symbol_tf_dir(symbol, version) / "labels.parquet"
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
