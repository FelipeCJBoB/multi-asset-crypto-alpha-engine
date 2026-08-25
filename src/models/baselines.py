"""Cinco baselines nulos — §16.1, RF-024. Mesmo motor que o Alpha
(`ret_net` já calculado por `src.labels.triple_barrier` — barreiras,
custos, quantização e funding idênticos; `backtest_lite.sharpe_naive`
idêntico em todos): B1 aleatório (1.000 sementes), B2 buy-and-hold, B3 só
regime, B4 features embaralhadas (AUC), B5 short permanente (§16.6).

**Refinamento estatístico do B1 (pós Sprint 8, ver
`experiments/alpha_b1_refinement_report.json`):** o relatório original
compara `camada1_sharpe_mean` (MÉDIA dos Sharpe de 5 caminhos de CPCV — já
tem variância reduzida por promediação) contra sorteios ÚNICOS de
`sample_size` (variância de UMA amostra, não reduzida). Isso infla o
percentil a favor do Alpha mesmo que as duas distribuições subjacentes
fossem idênticas — não é prova de que o Alpha bate o nulo, é prova de que
essa comparação isolada não é rigorosa o bastante. Três testes adicionais
corrigem isso, todos reusando o mesmo pool/RNG determinístico de
`run_b1_random_entry`:

1. `run_b1_per_path` — cada caminho contra um nulo do PRÓPRIO tamanho de
   amostra (não a média entre os 5).
2. `run_b1_paired_variance_null` — nulo com a MESMA estrutura de
   promediação do Alpha (5 sorteios independentes por réplica, média dos 5
   Sharpes), variância comparável à do Alpha.
3. Pool total (30.623 trades pooled) — chamar `run_b1_random_entry` de novo
   com `sample_size`/`alpha_sharpe` do agregado total
   (`decomposition_pnl.pooled_all_15_splits.total_sharpe`), não um novo
   caminho de código — pergunta complementar, não substituta.

**T2/T3 (pós auditoria de decomposição carry vs direcional):** o carry do
Alpha (+2,07 pooled, `decomposition_pnl.pooled_all_15_splits.pnl_carry`) é
~115 desvios-padrão do que um sorteio aleatório de mesmo tamanho
produziria — boa parte da vantagem do Alpha sobre B1 (percentil 100, usando
`ret_net` completo) pode vir do carry (timing de regime de funding), não de
direção. Dois testes adicionais, reusando a MESMA mecânica de sorteio/Sharpe
já existente:

- `run_b1_carry_stripped` (T2) — chama `run_b1_random_entry` de novo, mas
  com o pool e o `alpha_sharpe` recalculados sobre `ret_net_sem_carry =
  ret_gross - cost_entry_frac - cost_exit_frac` (`strip_carry`, mesma
  decomposição de `src.models.decomposition.decompose`:
  `pnl_direcional + pnl_execucao`, sem `pnl_carry` — reconstruída aqui a
  partir das colunas de `labels/v1/labels.parquet` para não importar
  `decomposition.py` sem necessidade).
- `run_b1_side_shuffle` (T3, "B1'") — isola só a escolha de LADO: para cada
  barra onde o Alpha REALMENTE disparou um sinal (`side_hat != 0`,
  `is_oof=True`), sorteia um lado (+1/-1) em vez do lado escolhido pelo
  modelo, mantendo a MESMA barra/timing REAL. Separa "o modelo sabe
  escolher O MOMENTO" (isolado por construção — a barra nunca é sorteada)
  de "o modelo sabe escolher A DIREÇÃO" (o que este teste mede)."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray
from sklearn.metrics import roc_auc_score

from src.data import lake
from src.features.build import T1_FEATURE_IDS
from src.validation.cpcv import CPCVSplit

from . import backtest_lite
from . import dataset as ds
from ._constants import load_constant
from ._paths import EXPERIMENTS_DIR
from .alpha import FoldResult, build_design_matrix

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

_MIN_CLASSES_FOR_AUC = 2  # noqa: magic-number — roc_auc_score exige as 2 classes presentes

# bps -> fração — definição matemática (mesma categoria de `_BPS_PER_UNIT`
# em `src.models.decomposition`/`src.labels.triple_barrier`), não constante
# de domínio. Duplicada aqui (em vez de importada de `decomposition.py`)
# porque `strip_carry` reconstrói a MESMA fórmula direto das colunas de
# `labels/v1/labels.parquet` para não acoplar `baselines` a `decomposition`
# por um único fator de conversão — ver docstring do módulo, T2.
_BPS_PER_UNIT = 10_000  # noqa: magic-number


# ============================================================================
# B1 — entrada aleatória, 1.000 sementes (§16.1)
# ============================================================================


@dataclass(frozen=True, slots=True)
class B1Result:
    n_seeds: int
    sample_size: int
    null_sharpes: FloatArray
    alpha_sharpe: float
    percentile: float


def _non_nofill_pool(df_all: pl.DataFrame) -> tuple[FloatArray, pl.Series, int]:
    """Pool = todos os trades NÃO-NOFILL do dataset inteiro (os dois lados,
    §16.1) — extraído de `run_b1_random_entry` para reuso pelo nulo de
    variância pareada (`run_b1_paired_variance_null`) sem duplicar a
    definição do pool. Mesmo resultado, mesma ordem de linhas."""
    pool = df_all.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    ret_arr = pool["ret_net"].to_numpy().astype(np.float64)
    t0_col = pool["t0"]
    return ret_arr, t0_col, ret_arr.shape[0]


def _draw_sample_sharpe(
    rng: np.random.Generator,
    ret_arr: FloatArray,
    t0_col: pl.Series,
    n_pool: int,
    size: int,
) -> float:
    """Um sorteio sem reposição de `size` trades do pool + Sharpe ingênuo
    sobre a amostra — mesmo cálculo por sorteio de `run_b1_random_entry`,
    extraído para reuso pelo nulo de variância pareada (consome a MESMA
    quantidade de estado do `rng` por chamada que o laço original, então um
    `run_b1_random_entry` chamado isoladamente com o mesmo `base_seed`
    continua bit-a-bit idêntico ao comportamento pré-refatoração)."""
    idx = rng.choice(n_pool, size=size, replace=False)
    sample_rets = ret_arr[idx]
    sample_t0 = t0_col[idx]
    span = backtest_lite.span_seconds(sample_t0)
    sharpe, _ = backtest_lite.sharpe_naive(sample_rets, span_seconds=span)
    return sharpe


def b1_sample_size(n_filled_c1: int, n_paths: int) -> int:
    """Núcleo funcional (2026-08-23, `docs/nucleo_casca_design_doc_
    2026-08-23.md`) — fórmula de tamanho de amostra do baseline B1,
    extraída de `pipeline.py::run_layer1_sprint` pra virar testável sem
    rodar o pipeline CPCV/XGBoost inteiro: trades preenchidos da Camada 1
    (pooled sobre todos os paths) divididos pelo nº de paths, arredondado,
    piso 1 (nunca amostra vazia). `n_paths=0` (nenhum path, caso
    degenerado) cai no mesmo piso via `max(n_paths, 1)` no denominador."""
    return max(1, round(n_filled_c1 / max(n_paths, 1)))  # noqa: unguarded-ratio -- denominador clampado a >=1 na própria expressão


def run_b1_random_entry(
    df_all: pl.DataFrame,
    *,
    sample_size: int,
    alpha_sharpe: float,
    n_seeds: int | None = None,
    base_seed: int | None = None,
) -> B1Result:
    """`sample_size` deve ser o número REAL de trades preenchidos que o
    Alpha produziu (mesma taxa de sinal, texto literal do §16.1) — o
    chamador passa isso, este módulo não decide sozinho o tamanho da
    amostra nula. Pool = todos os trades NÃO-NOFILL do dataset inteiro
    (os dois lados), porque uma "entrada aleatória" não sabe escolher lado
    — sortear dentre os dois lados já realizados é a leitura mais direta de
    "lado sorteado" (texto do §16.1).

    **Nulo de sorteio ÚNICO** — cada uma das `n_seeds` réplicas é UMA
    amostra de `sample_size` trades, variância de uma amostra só. Válido
    para comparar contra o Sharpe de UM caminho (`run_b1_per_path`) ou
    contra uma estatística pooled (item 3 do refinamento, ver docstring do
    módulo); NÃO é a comparação certa contra uma MÉDIA de vários Sharpes —
    para isso ver `run_b1_paired_variance_null`."""
    n_seeds = n_seeds if n_seeds is not None else int(load_constant("alpha_b1_n_seeds"))
    base_seed = base_seed if base_seed is not None else int(load_constant("alpha_random_seed"))

    ret_arr, t0_col, n_pool = _non_nofill_pool(df_all)

    effective_size = min(sample_size, n_pool)
    if effective_size < sample_size:
        logger.warning(
            "models.baselines.b1_sample_clamped", requested=sample_size, pool_size=n_pool
        )

    rng = np.random.default_rng(base_seed)
    null_sharpes = np.empty(n_seeds, dtype=np.float64)
    for i in range(n_seeds):
        null_sharpes[i] = _draw_sample_sharpe(rng, ret_arr, t0_col, n_pool, effective_size)

    valid = null_sharpes[np.isfinite(null_sharpes)]
    # 100.0 é conversão fração -> percentual (definição matemática, não
    # constante de domínio) — mesma categoria de `_BPS_PER_UNIT` em
    # `src.labels.triple_barrier`.
    percentile = float(np.mean(valid < alpha_sharpe) * 100.0) if valid.size else float("nan")  # noqa: magic-number

    result = B1Result(
        n_seeds=n_seeds,
        sample_size=effective_size,
        null_sharpes=null_sharpes,
        alpha_sharpe=alpha_sharpe,
        percentile=percentile,
    )
    logger.info(
        "models.baselines.run_b1_random_entry",
        n_seeds=n_seeds,
        sample_size=effective_size,
        alpha_sharpe=alpha_sharpe,
        percentile=percentile,
        null_mean=float(np.nanmean(null_sharpes)),
        null_p95=float(np.nanpercentile(valid, 95)) if valid.size else float("nan"),
    )
    return result


# ============================================================================
# B1 refinamento item 1 — comparação caminho-a-caminho (percentil próprio
# por caminho, não a média entre os 5). Ver docstring do módulo.
# ============================================================================


@dataclass(frozen=True, slots=True)
class B1PerPathResult:
    path_id: int
    b1: B1Result


def run_b1_per_path(
    df_all: pl.DataFrame,
    *,
    path_sample_sizes: Mapping[int, int],
    path_alpha_sharpes: Mapping[int, float],
    n_seeds: int | None = None,
    base_seed: int | None = None,
) -> dict[int, B1PerPathResult]:
    """Um `run_b1_random_entry` por caminho de backtest do CPCV (5, §11.4)
    — cada caminho compara SEU PRÓPRIO Sharpe real (`path_alpha_sharpes[
    path_id]`) contra um nulo de sorteios do MESMO tamanho de amostra
    daquele caminho especificamente (`path_sample_sizes[path_id]`,
    `n_filled_trades` real do caminho — não a média entre os 5 usada no
    relatório original). Reusa 100% da lógica estatística de
    `run_b1_random_entry` (mesmo pool, mesmo RNG determinístico, mesma
    fórmula de percentil) — a única coisa nova aqui é a orquestração por
    `path_id`."""
    if set(path_sample_sizes) != set(path_alpha_sharpes):
        raise ValueError(
            "run_b1_per_path: path_sample_sizes e path_alpha_sharpes precisam "
            "cobrir exatamente os mesmos path_id"
        )
    out: dict[int, B1PerPathResult] = {}
    for path_id in sorted(path_sample_sizes):
        b1 = run_b1_random_entry(
            df_all,
            sample_size=path_sample_sizes[path_id],
            alpha_sharpe=path_alpha_sharpes[path_id],
            n_seeds=n_seeds,
            base_seed=base_seed,
        )
        out[path_id] = B1PerPathResult(path_id=path_id, b1=b1)
    logger.info(
        "models.baselines.run_b1_per_path",
        n_paths=len(out),
        percentile_by_path={pid: r.b1.percentile for pid, r in out.items()},
    )
    return out


# ============================================================================
# B1 refinamento item 2 — nulo de variância pareada: cada réplica sorteia 5
# amostras independentes (uma por caminho, do tamanho REAL daquele caminho)
# e tira a MÉDIA dos 5 Sharpes, mesma estrutura de promediação que produz
# `alpha_sharpe` (`camada1_sharpe_mean`) — variância comparável, ao
# contrário do nulo de sorteio único de `run_b1_random_entry`. Ver
# docstring do módulo para a motivação estatística completa.
# ============================================================================


@dataclass(frozen=True, slots=True)
class B1PairedVarianceResult:
    n_seeds: int
    path_sample_sizes: tuple[int, ...]
    null_replicate_means: FloatArray
    alpha_sharpe: float
    percentile: float


def run_b1_paired_variance_null(
    df_all: pl.DataFrame,
    *,
    path_sample_sizes: Sequence[int],
    alpha_sharpe: float,
    n_seeds: int | None = None,
    base_seed: int | None = None,
) -> B1PairedVarianceResult:
    """`alpha_sharpe` é a MÉDIA real dos Sharpe dos `len(path_sample_sizes)`
    caminhos do Alpha (`camada1_sharpe_mean`) — cada uma das `n_seeds`
    réplicas do nulo sorteia, na MESMA ordem de `path_sample_sizes`, uma
    amostra independente por tamanho (sem reposição dentro de cada sorteio;
    os sorteios entre si PODEM se sobrepor — são independentes, não uma
    partição do pool, mesma leitura de "caminho" usada pelo CPCV real, cujos
    caminhos também compartilham trades subjacentes entre si), calcula o
    Sharpe de cada sorteio e tira a média dos 5. O nulo resultante
    (`null_replicate_means`) tem variância reduzida por promediação — a
    MESMA redução estrutural que `alpha_sharpe` já tem — então comparar
    `alpha_sharpe` contra ele é a comparação estatisticamente correta
    (ao contrário de compará-lo contra `run_b1_random_entry`, cujo nulo é
    de UMA amostra só). Reusa o mesmo pool NÃO-NOFILL e o mesmo RNG
    determinístico de `run_b1_random_entry` via `_non_nofill_pool`/
    `_draw_sample_sharpe`."""
    if len(path_sample_sizes) == 0:
        raise ValueError("run_b1_paired_variance_null: path_sample_sizes vazio")
    n_seeds = n_seeds if n_seeds is not None else int(load_constant("alpha_b1_n_seeds"))
    base_seed = base_seed if base_seed is not None else int(load_constant("alpha_random_seed"))

    ret_arr, t0_col, n_pool = _non_nofill_pool(df_all)

    clamped_sizes: list[int] = []
    for size in path_sample_sizes:
        effective = min(size, n_pool)
        if effective < size:
            logger.warning(
                "models.baselines.b1_paired_sample_clamped",
                requested=size,
                pool_size=n_pool,
            )
        clamped_sizes.append(effective)

    rng = np.random.default_rng(base_seed)
    null_replicate_means = np.empty(n_seeds, dtype=np.float64)
    for i in range(n_seeds):
        path_sharpes = np.empty(len(clamped_sizes), dtype=np.float64)
        for j, size in enumerate(clamped_sizes):
            path_sharpes[j] = _draw_sample_sharpe(rng, ret_arr, t0_col, n_pool, size)
        null_replicate_means[i] = float(np.mean(path_sharpes))

    valid = null_replicate_means[np.isfinite(null_replicate_means)]
    # 100.0 é conversão fração -> percentual (definição matemática, não
    # constante de domínio) — mesma categoria da conversão idêntica em
    # `run_b1_random_entry`.
    percentile = float(np.mean(valid < alpha_sharpe) * 100.0) if valid.size else float("nan")  # noqa: magic-number

    result = B1PairedVarianceResult(
        n_seeds=n_seeds,
        path_sample_sizes=tuple(clamped_sizes),
        null_replicate_means=null_replicate_means,
        alpha_sharpe=alpha_sharpe,
        percentile=percentile,
    )
    logger.info(
        "models.baselines.run_b1_paired_variance_null",
        n_seeds=n_seeds,
        path_sample_sizes=clamped_sizes,
        alpha_sharpe=alpha_sharpe,
        percentile=percentile,
        null_mean=float(np.nanmean(null_replicate_means)),
        null_std=float(np.std(valid, ddof=1)) if valid.size >= 2 else float("nan"),
    )
    return result


# ============================================================================
# Escrita atômica do relatório de refinamento (B29 — `.tmp` -> `fsync` ->
# `rename`, mesmo padrão de `src.models.pipeline.write_report_atomic`/
# `src.validation.leakage.write_leakage_report_atomic`).
# ============================================================================


def write_b1_refinement_report_atomic(
    payload: dict[str, Any], dest_path: Path | None = None
) -> Path:
    """Escreve por padrão em
    `experiments/alpha_b1_refinement_report.json` — os 3 testes do
    refinamento estatístico do B1 (comparação caminho-a-caminho, nulo de
    variância pareada, pool total), ver docstring do módulo."""
    default_path = EXPERIMENTS_DIR / "alpha_b1_refinement_report.json"
    out_path = dest_path if dest_path is not None else default_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("models.baselines.b1_refinement_report_written", path=str(out_path))
    return out_path


# ============================================================================
# T2 — percentil carry-stripped. `strip_carry` reconstrói `ret_net_sem_carry`
# das colunas cruas de `labels/v1/labels.parquet`; `run_b1_carry_stripped`
# reusa `run_b1_random_entry` tal como já existe (nenhum caminho de código
# novo de sorteio/Sharpe), só troca O QUE é passado. Ver docstring do
# módulo.
# ============================================================================


def strip_carry(df: pl.DataFrame) -> pl.DataFrame:
    """Devolve `df` com a coluna `ret_net` SUBSTITUÍDA por
    `ret_gross - cost_entry_frac - cost_exit_frac` (retorno sem o termo de
    carry — mesma decomposição de `src.models.decomposition.decompose`:
    `pnl_direcional + pnl_execucao`, excluindo `pnl_carry =
    -funding_bps/1e4`; equivalente a `ret_net + funding_bps/1e4`, já que
    `ret_net == pnl_direcional + pnl_carry + pnl_execucao` por construção
    de `src.labels.triple_barrier`). Reconstrói a fórmula direto das
    colunas de `labels/v1/labels.parquet` (`ret_gross, cost_entry_bps,
    cost_exit_bps`) em vez de importar `decomposition.py` — evita
    acoplamento novo por um único fator de conversão; a fórmula é testada
    por reconciliação contra `ret_net` original em
    `tests/unit/test_models_baselines.py` (mesma tolerância de
    `decomposition.py`, 1e-6).

    Todas as OUTRAS colunas de `df` são preservadas intactas — só `ret_net`
    muda. `df` precisa ter `ret_gross, cost_entry_bps, cost_exit_bps,
    ret_net` (schema de `labels/v1/labels.parquet`/`src.models.dataset.
    build_modeling_frame`)."""
    cost_frac = (pl.col("cost_entry_bps") + pl.col("cost_exit_bps")) / _BPS_PER_UNIT
    return df.with_columns((pl.col("ret_gross") - cost_frac).alias("ret_net"))


def run_b1_carry_stripped(
    df_all: pl.DataFrame,
    alpha_trades: pl.DataFrame,
    *,
    n_seeds: int | None = None,
    base_seed: int | None = None,
) -> B1Result:
    """T2 — mesma pergunta de `run_b1_random_entry`, mas com o carry
    removido dos DOIS lados da comparação: o pool nulo (sorteios também sem
    carry) E o `alpha_sharpe` comparado (Sharpe do Alpha sem carry).
    Motivação: achado da auditoria de decomposição de que o carry pooled do
    Alpha (+2,07, `decomposition_pnl.pooled_all_15_splits.pnl_carry`) é
    ~115 desvios-padrão do que um sorteio aleatório de mesmo tamanho
    produziria — parte da vantagem de B1 (percentil 100 com `ret_net`
    completo) pode vir de timing de funding, não de direção.

    `df_all` é o MESMO pool completo que `run_b1_random_entry` já recebe
    (todos os trades NÃO-NOFILL, ambos os lados, dataset inteiro).
    `alpha_trades` são os trades REALIZADOS e PREENCHIDOS do Alpha
    (`barrier_hit != "NOFILL"`, ex. `filled_c1` pooled do pipeline —
    `backtest_lite.realize_trades(...).filter(barrier_hit != "NOFILL")`) —
    `sample_size` sai de `alpha_trades.height` (mesma convenção de "número
    REAL de trades preenchidos" que `run_b1_random_entry` já documenta).

    Não duplica a mecânica de sorteio/Sharpe: chama `run_b1_random_entry`
    tal como já existe, só troca o QUE é passado (pool e `alpha_sharpe`
    recalculados via `strip_carry`)."""
    pool_stripped = strip_carry(df_all)
    alpha_stripped = strip_carry(alpha_trades)
    alpha_rets = alpha_stripped["ret_net"].to_numpy().astype(np.float64)
    span = backtest_lite.span_seconds(alpha_stripped["t0"])
    alpha_sharpe_stripped, _ = backtest_lite.sharpe_naive(alpha_rets, span_seconds=span)

    result = run_b1_random_entry(
        pool_stripped,
        sample_size=alpha_trades.height,
        alpha_sharpe=alpha_sharpe_stripped,
        n_seeds=n_seeds,
        base_seed=base_seed,
    )
    logger.info(
        "models.baselines.run_b1_carry_stripped",
        alpha_sharpe_sem_carry=alpha_sharpe_stripped,
        sample_size=result.sample_size,
        percentile=result.percentile,
    )
    return result


# ============================================================================
# T3 — B1' (side shuffle): sorteia só o LADO, mantém a barra/timing REAL do
# Alpha fixa. Isola "o modelo sabe escolher o MOMENTO" (nunca sorteado aqui
# — a barra é sempre real) de "o modelo sabe escolher A DIREÇÃO" (o que
# `side_hat` real vs. sorteado testa). Reusa `backtest_lite.span_seconds`/
# `sharpe_naive` — a mesma dupla que `_draw_sample_sharpe` já usa para
# calcular Sharpe sobre uma amostra — mas o que é sorteado por réplica não é
# MAIS trades de um pool, é o LADO de um conjunto de barras já fixo.
# ============================================================================


@dataclass(frozen=True, slots=True)
class B1SideShuffleResult:
    n_seeds: int
    n_signals: int
    long_prob: float
    side_distribution: str
    mean_sample_size: float
    null_sharpes: FloatArray
    alpha_sharpe: float
    percentile: float


# Duas leituras defensáveis para a distribuição do lado sorteado (texto da
# task, T3) — "uniform" é a usada na medição real reportada: o pool de
# `run_b1_random_entry` já é implicitamente 50/50 (toda barra de
# `labels.parquet` tem exatamente uma linha `side=1` e uma `side=-1`, §3.2),
# então manter 50/50 aqui preserva a MESMA convenção de "lado sorteado" do
# B1 original. Usar a proporção observada do Alpha ("empirical") importaria
# de volta o viés direcional do PRÓPRIO modelo no "nulo" — disponível para
# quem quiser essa leitura, mas confundiria de novo a pergunta que B1'
# tenta isolar.
_SIDE_DISTRIBUTIONS = ("uniform", "empirical")


def _signal_side_outcomes(
    df_all: pl.DataFrame, signals: pl.DataFrame
) -> tuple[FloatArray, FloatArray, BoolArray, BoolArray, pl.Series]:
    """Para cada linha de `signals` (uma barra/fold onde o Alpha disparou),
    junta os DOIS resultados possíveis da MESMA barra em `df_all` — LONG
    (`side=1`) e SHORT (`side=-1`), não só o lado que o modelo escolheu.
    `signals` pode ter `t0` repetido (mesma barra aparece em folds/caminhos
    diferentes do CPCV, cada aparição é um "sinal" independente, mesma
    contagem que `backtest_lite.realize_trades` produz) — o join preserva
    essa multiplicidade porque `long_side`/`short_side` têm exatamente uma
    linha por `t0` (uma barra tem exatamente um label `side=1` e um
    `side=-1` em `labels.parquet`).

    Retorna `(ret_long, ret_short, filled_long, filled_short, t0)`, os 4
    arrays alinhados posicionalmente com `signals` (ordem de entrada
    preservada) — `run_b1_side_shuffle`/`_draw_side_shuffle_sharpe` sorteiam
    QUAL dos dois lados usar por réplica, sem tocar em `t0`."""
    long_side = df_all.filter(pl.col("side") == 1).select(
        "t0",
        pl.col("ret_net").alias("ret_long"),
        (pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL").alias("filled_long"),
    )
    short_side = df_all.filter(pl.col("side") == -1).select(
        "t0",
        pl.col("ret_net").alias("ret_short"),
        (pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL").alias("filled_short"),
    )
    joined = (
        signals.select("t0")
        .join(long_side, on="t0", how="left")
        .join(short_side, on="t0", how="left")
    )
    n_missing = int(joined["ret_long"].null_count() + joined["ret_short"].null_count())
    if n_missing > 0:
        logger.warning("models.baselines.b1_side_shuffle_missing_outcomes", n_missing=n_missing)
        joined = joined.drop_nulls(["ret_long", "ret_short"])
    ret_long = joined["ret_long"].to_numpy().astype(np.float64)
    ret_short = joined["ret_short"].to_numpy().astype(np.float64)
    filled_long = joined["filled_long"].to_numpy().astype(np.bool_)
    filled_short = joined["filled_short"].to_numpy().astype(np.bool_)
    return ret_long, ret_short, filled_long, filled_short, joined["t0"]


def _draw_side_shuffle_sharpe(
    rng: np.random.Generator,
    ret_long: FloatArray,
    ret_short: FloatArray,
    filled_long: BoolArray,
    filled_short: BoolArray,
    t0_col: pl.Series,
    long_prob: float,
) -> tuple[float, int]:
    """Um sorteio de LADO por barra (barra/timing sempre REAL e fixo — só o
    lado é decidido por `rng`, com probabilidade `long_prob` de LONG),
    seguido do Sharpe ingênuo sobre os resultados PREENCHIDOS (NOFILL
    descartado, mesmo critério do resto do módulo) — papel equivalente a
    `_draw_sample_sharpe` (mesma dupla `span_seconds`/`sharpe_naive`), mas o
    que é sorteado aqui é o LADO de uma barra fixa, não a barra em si."""
    n = ret_long.shape[0]
    is_long = rng.random(n) < long_prob
    ret = np.where(is_long, ret_long, ret_short)
    filled = np.where(is_long, filled_long, filled_short)
    sample_rets = ret[filled]
    sample_t0 = t0_col.filter(pl.Series(filled))
    span = backtest_lite.span_seconds(sample_t0)
    sharpe, _ = backtest_lite.sharpe_naive(sample_rets, span_seconds=span)
    return sharpe, int(sample_rets.shape[0])


def run_b1_side_shuffle(
    df_all: pl.DataFrame,
    signals: pl.DataFrame,
    *,
    alpha_sharpe: float,
    side_distribution: str = "uniform",
    n_seeds: int | None = None,
    base_seed: int | None = None,
) -> B1SideShuffleResult:
    """T3 (B1') — para cada barra onde o Alpha REALMENTE disparou um sinal
    (`side_hat != 0`, `is_oof=True` — filtrado aqui dentro, defensivamente:
    por construção de `src.models.alpha.run_fold`, `is_oof` já é sempre
    `True` em `predictions`, então o filtro é um no-op esperado sobre dado
    real, não decoração), sorteia um lado (+1/-1) em vez do lado que o
    modelo escolheu, mantendo a MESMA barra/timing — isola "o modelo sabe
    ESCOLHER O MOMENTO" (nunca sorteado aqui) de "o modelo sabe escolher A
    DIREÇÃO" (o que este teste mede).

    `df_all` é o pool completo de labels (mesmo argumento de
    `run_b1_random_entry` — precisa ter `t0, side, barrier_hit, ret_net`
    para AMBOS os lados de cada barra, não só o lado sinalizado).
    `signals` é a tabela de predições do Alpha (schema §5.12, ex.
    `predictions/alpha/{model_id}/predictions.parquet` OU a tabela de
    `backtest_lite.realize_trades(...)` ANTES do filtro de NOFILL — este
    módulo filtra `side_hat != 0`/`is_oof` sozinho, então passar a tabela
    bruta é o uso esperado).

    `alpha_sharpe` é passado pelo chamador (mesmo padrão de
    `run_b1_random_entry` — este módulo não decide sozinho qual Sharpe do
    Alpha é "o real", pooled total vs. média por caminho; ver
    `src.models.pipeline`/relatório para a escolha concreta).
    `side_distribution` controla a proporção LONG/SHORT do sorteio — ver
    comentário de `_SIDE_DISTRIBUTIONS` acima para a justificativa de cada
    opção."""
    if side_distribution not in _SIDE_DISTRIBUTIONS:
        raise ValueError(
            "run_b1_side_shuffle: side_distribution deve ser um de "
            f"{_SIDE_DISTRIBUTIONS}, recebido {side_distribution!r}"
        )
    n_seeds = n_seeds if n_seeds is not None else int(load_constant("alpha_b1_n_seeds"))
    base_seed = base_seed if base_seed is not None else int(load_constant("alpha_random_seed"))

    sig = signals.filter(pl.col("side_hat") != 0)
    if "is_oof" in sig.columns:
        sig = sig.filter(pl.col("is_oof"))
    if sig.height == 0:
        raise ValueError(
            "run_b1_side_shuffle: nenhum sinal (side_hat != 0, is_oof=True) em `signals`"
        )

    if side_distribution == "uniform":
        long_prob = 0.5
    else:
        side_hat_arr = sig["side_hat"].to_numpy()
        long_prob = float(np.mean(side_hat_arr == 1))

    ret_long, ret_short, filled_long, filled_short, t0_col = _signal_side_outcomes(df_all, sig)

    rng = np.random.default_rng(base_seed)
    null_sharpes = np.empty(n_seeds, dtype=np.float64)
    sample_sizes = np.empty(n_seeds, dtype=np.int64)
    for i in range(n_seeds):
        sharpe, n_filled = _draw_side_shuffle_sharpe(
            rng, ret_long, ret_short, filled_long, filled_short, t0_col, long_prob
        )
        null_sharpes[i] = sharpe
        sample_sizes[i] = n_filled

    valid = null_sharpes[np.isfinite(null_sharpes)]
    # 100.0 é conversão fração -> percentual (definição matemática, não
    # constante de domínio) — mesma categoria da conversão idêntica em
    # `run_b1_random_entry`.
    percentile = float(np.mean(valid < alpha_sharpe) * 100.0) if valid.size else float("nan")  # noqa: magic-number

    result = B1SideShuffleResult(
        n_seeds=n_seeds,
        n_signals=int(ret_long.shape[0]),
        long_prob=long_prob,
        side_distribution=side_distribution,
        mean_sample_size=float(np.mean(sample_sizes)),
        null_sharpes=null_sharpes,
        alpha_sharpe=alpha_sharpe,
        percentile=percentile,
    )
    logger.info(
        "models.baselines.run_b1_side_shuffle",
        n_seeds=n_seeds,
        n_signals=result.n_signals,
        long_prob=long_prob,
        side_distribution=side_distribution,
        alpha_sharpe=alpha_sharpe,
        percentile=percentile,
        null_mean=float(np.nanmean(null_sharpes)),
        mean_sample_size=result.mean_sample_size,
    )
    return result


# ============================================================================
# B2 — buy-and-hold BTCUSDT sem alavancagem (§16.1)
# ============================================================================


@dataclass(frozen=True, slots=True)
class B2Result:
    sharpe_naive: float
    n_days: int
    mean_daily_log_ret: float
    std_daily_log_ret: float


def run_b2_buy_and_hold(symbol: str, start: str, end: str) -> B2Result:
    """Retorno diário (log) do close do perpétuo, sem alavancagem, sem
    funding/fees — o "prêmio direcional do ativo" puro (§16.1: "contexto,
    não meta"). `sharpe_naive` aplicado sobre retornos DIÁRIOS, não sobre
    trades — anualização por `sqrt(365,25)` (dias corridos, não dias
    úteis, consistente com um ativo 24/7)."""
    daily = lake.query_bars(symbol, "1d", start, end, source="klines_1m", cast_prices=True)
    close = daily.sort("open_time")["close"].cast(pl.Float64).to_numpy()
    if close.shape[0] < 2:  # noqa: magic-number — mínimo para 1 log-retorno existir
        return B2Result(
            sharpe_naive=float("nan"), n_days=int(close.shape[0]),
            mean_daily_log_ret=float("nan"), std_daily_log_ret=float("nan"),
        )
    log_ret = np.diff(np.log(close))
    mean = float(np.mean(log_ret))
    std = float(np.std(log_ret, ddof=1))
    sharpe = mean / std * float(np.sqrt(backtest_lite.DAYS_PER_YEAR)) if std > 0.0 else float("nan")
    result = B2Result(
        sharpe_naive=sharpe, n_days=int(close.shape[0]),
        mean_daily_log_ret=mean, std_daily_log_ret=std,
    )
    logger.info("models.baselines.run_b2_buy_and_hold", **asdict(result))
    return result


# ============================================================================
# B3 (regra estática, só regime) / B5 (short permanente) — §16.1/§16.6
# ============================================================================


@dataclass(frozen=True, slots=True)
class StaticRuleResult:
    name: str
    n_signals: int
    n_filled_trades: int
    fill_rate: float
    sharpe_naive: float
    mean_trade_ret: float
    trades_per_year: float


def _static_rule_result(name: str, trades: pl.DataFrame) -> StaticRuleResult:
    n_signals = trades.height
    filled = trades.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    n_filled = filled.height
    fill_rate = float(n_filled) / float(n_signals) if n_signals > 0 else float("nan")
    span = backtest_lite.span_seconds(filled["t0"])
    rets = filled["ret_net"].to_numpy().astype(np.float64)
    sharpe, tpy = backtest_lite.sharpe_naive(rets, span_seconds=span)
    mean_ret = float(np.mean(rets)) if rets.size else float("nan")
    result = StaticRuleResult(
        name=name, n_signals=n_signals, n_filled_trades=n_filled, fill_rate=fill_rate,
        sharpe_naive=sharpe, mean_trade_ret=mean_ret, trades_per_year=tpy,
    )
    logger.info("models.baselines.static_rule", **asdict(result))
    return result


def run_b3_regime_only(df_all: pl.DataFrame) -> StaticRuleResult:
    """Long em R3/R4 com `A13_dist_ema48_atr > 0`, sem Alpha (§16.1) — regra
    estática aplicada sobre o dataset INTEIRO (não há ajuste/fit nenhum
    aqui, então não há fold de CPCV a respeitar — a regra não "aprende"
    nada da amostra)."""
    trades = df_all.filter(
        (pl.col("side") == 1)
        & pl.col("regime").is_in(["R3", "R4"])
        & (pl.col("A13_dist_ema48_atr") > 0.0)
        & pl.col("A13_dist_ema48_atr").is_not_null()
    ).sort("t0")
    return _static_rule_result("B3_regime_only", trades)


def run_b5_short_permanent(df_all: pl.DataFrame) -> StaticRuleResult:
    """Short permanente, mesmo sizing conceitual (§16.6) — isola o carry
    puro: todo `t0` com label do lado curto (exceto warmup, já fora de
    `df_all` via `build_modeling_frame`)."""
    trades = df_all.filter(pl.col("side") == -1).sort("t0")
    return _static_rule_result("B5_short_permanent", trades)


# ============================================================================
# B4 — Alpha com features embaralhadas (§16.1) — AUC deve colapsar a ~0,5
# ============================================================================


@dataclass(frozen=True, slots=True)
class B4Result:
    auc_real_long: float
    auc_permuted_long: float
    auc_real_short: float
    auc_permuted_short: float
    auc_real_pooled: float
    auc_permuted_pooled: float
    n_eval_long: int
    n_eval_short: int


def _pool_auc(y_parts: list[IntArray], s_parts: list[FloatArray]) -> float:
    if not y_parts:
        return float("nan")
    y_cat = np.concatenate(y_parts)
    s_cat = np.concatenate(s_parts)
    if np.unique(y_cat).shape[0] < _MIN_CLASSES_FOR_AUC:
        return float("nan")
    return float(roc_auc_score(y_cat, s_cat))


def run_b4_feature_shuffle(
    df_all: pl.DataFrame,
    splits: tuple[CPCVSplit, ...],
    camada1_fold_results: list[FoldResult],
    *,
    seed: int | None = None,
    feature_ids: tuple[str, ...] = T1_FEATURE_IDS,
) -> B4Result:
    """Reusa os modelos JÁ TREINADOS da Camada 1 (nenhum retreino — B4 é um
    teste de AVALIAÇÃO, não um variante de treino) — embaralha cada uma das
    colunas de `feature_ids` INDEPENDENTEMENTE, dentro do conjunto de teste
    de cada fold (mantém a marginal de cada coluna, destrói a associação
    linha a linha entre feature e alvo, texto literal do §16.1). Colunas de
    regime (one-hot) NÃO são embaralhadas — não são "as features" no
    sentido do vetor de treino (§2.13), são o estado conhecido da barra.

    `feature_ids` (2026-08-25, `AG-207`/`ADR-003`) — default `T1_FEATURE_
    IDS` preserva bit-exato todo call site existente. Precisa ser
    EXATAMENTE o vetor usado pra treinar `camada1_fold_results` — os
    modelos já treinados esperam essa forma de entrada (`predict_proba`
    levanta `ValueError` de shape se divergir), não é opcional em par com
    `run_all_folds(feature_ids=...)` do mesmo treino."""
    seed = seed if seed is not None else int(load_constant("alpha_random_seed"))
    rng = np.random.default_rng(seed)
    n_features = len(feature_ids)

    split_by_id = {s.split_id: s for s in splits}
    y_real_long: list[IntArray] = []
    s_real_long: list[FloatArray] = []
    s_perm_long: list[FloatArray] = []
    y_real_short: list[IntArray] = []
    s_real_short: list[FloatArray] = []
    s_perm_short: list[FloatArray] = []

    for fr in camada1_fold_results:
        split = split_by_id[fr.fold_id]
        test_bars = df_all[split.test_idx]
        for side, model, y_acc, sreal_acc, sperm_acc in (
            (1, fr.long_result.model, y_real_long, s_real_long, s_perm_long),
            (-1, fr.short_result.model, y_real_short, s_real_short, s_perm_short),
        ):
            test_side = ds.side_subset(test_bars, side=side)
            if test_side.height == 0:
                continue
            X = build_design_matrix(test_side, feature_ids=feature_ids)
            y = (test_side["label"].cast(pl.Int64) == 1).to_numpy().astype(np.int64)
            # `np.asarray(...)` explícito -- stubs do LightGBM tipam
            # `predict_proba` como `list` (imprecisão da biblioteca), quebra
            # mypy --strict no fancy-indexing `[:, 1]`. Sem mudança de valor
            # em runtime (já era ndarray).
            p_real = np.asarray(model.predict_proba(X))[:, 1]

            X_perm = X.copy()
            for j in range(n_features):
                perm_idx = rng.permutation(X_perm.shape[0])
                X_perm[:, j] = X_perm[perm_idx, j]
            p_perm = np.asarray(model.predict_proba(X_perm))[:, 1]

            y_acc.append(y)
            sreal_acc.append(p_real)
            sperm_acc.append(p_perm)

    auc_real_long = _pool_auc(y_real_long, s_real_long)
    auc_perm_long = _pool_auc(y_real_long, s_perm_long)
    auc_real_short = _pool_auc(y_real_short, s_real_short)
    auc_perm_short = _pool_auc(y_real_short, s_perm_short)
    auc_real_pooled = _pool_auc(y_real_long + y_real_short, s_real_long + s_real_short)
    auc_perm_pooled = _pool_auc(y_real_long + y_real_short, s_perm_long + s_perm_short)

    result = B4Result(
        auc_real_long=auc_real_long,
        auc_permuted_long=auc_perm_long,
        auc_real_short=auc_real_short,
        auc_permuted_short=auc_perm_short,
        auc_real_pooled=auc_real_pooled,
        auc_permuted_pooled=auc_perm_pooled,
        n_eval_long=int(sum(a.shape[0] for a in y_real_long)),
        n_eval_short=int(sum(a.shape[0] for a in y_real_short)),
    )
    logger.info("models.baselines.run_b4_feature_shuffle", **asdict(result))
    return result
