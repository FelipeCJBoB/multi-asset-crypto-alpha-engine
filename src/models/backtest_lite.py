"""Harness de avaliação mínimo para esta rodada — NÃO é o motor de
backtest do projeto (§11.1/§14.1: "não escreva motor próprio antes de
avaliar o de prateleira", CLAUDE.md). Este módulo faz só o suficiente para
comparar Camada 1 vs Camada 0 e os 5 baselines nulos do §16.1 sobre os
MESMOS trades já materializados em `labels/v1/labels.parquet` (barreiras,
custos, quantização e funding já aplicados por `src.labels.triple_barrier`
— este módulo não resimula nada disso, só agrega `ret_net` já calculado).

**Sharpe "ingênuo" (não corrigido por autocorrelação, §16.5, nem por DSR,
§11.6) — ambos fora de escopo desta rodada por instrução explícita da
task.** `sharpe_naive = mean(ret_net) / std(ret_net) * sqrt(trades/ano)`,
anualizado pela frequência REAL de trade observada na amostra (não um
fator fixo) — mesma fórmula aplicada a Alpha e a TODOS os baselines
(§16.1: "rodando no mesmo motor... idênticos"), então a comparação relativa
é válida mesmo sem a correção de Lo(2002)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence, cast

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from src.validation import bootstrap_diff

from .alpha import FoldResult

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

# Dias por ano (calendário Gregoriano médio) — constante matemática de
# calendário, não de domínio (mesma categoria de `_BPS_PER_UNIT` em
# `triple_barrier.py`, `24 * 60 * 60 * 1000` em `test_validation_cpcv.py`).
# Públicas (sem `_`) — reusadas por `src.models.baselines` e
# `src.models.decomposition`, que precisam da MESMA convenção de
# anualização que este módulo usa para Alpha (§16.1: "mesmo motor").
DAYS_PER_YEAR = 365.25  # noqa: magic-number
SECONDS_PER_DAY = 86_400  # noqa: magic-number
_MIN_TRADES_FOR_SHARPE = 2  # noqa: magic-number — desvio padrão amostral exige >= 2 pontos


def sharpe_naive(trade_returns: FloatArray, *, span_seconds: float) -> tuple[float, float]:
    """`span_seconds` é o intervalo de calendário coberto pela AMOSTRA de
    trades (não um horizonte arbitrário) — `trades_per_year` é derivado
    disso, nunca de uma constante fixa. Retorna `(sharpe, trades_per_year)`;
    `nan` se não houver dados suficientes para desvio padrão."""
    n = trade_returns.shape[0]
    if n < _MIN_TRADES_FOR_SHARPE or span_seconds <= 0.0:
        return float("nan"), float("nan")
    span_years = span_seconds / (DAYS_PER_YEAR * SECONDS_PER_DAY)
    trades_per_year = n / span_years if span_years > 0 else float("nan")
    mean = float(np.mean(trade_returns))
    std = float(np.std(trade_returns, ddof=1))
    if std == 0.0 or not np.isfinite(trades_per_year):
        return float("nan"), trades_per_year
    return mean / std * float(np.sqrt(trades_per_year)), trades_per_year


def span_seconds(t0_series: pl.Series) -> float:
    """Segundos de calendário entre o primeiro e o último `t0` da série —
    pública porque `src.models.baselines`/`src.models.decomposition`
    precisam da mesma definição de "janela coberta" que este módulo usa
    para `sharpe_naive`."""
    if t0_series.len() < _MIN_TRADES_FOR_SHARPE:
        return 0.0
    # `pl.Series.min()`/`.max()` devolvem um union amplo nos stubs do
    # polars (qualquer literal Python possível, não o dtype real da
    # série) — `cast` para `datetime` é seguro aqui porque o contrato do
    # módulo (`t0_series` vem sempre de uma coluna `Datetime`) já é
    # verificado pelos chamadores reais (`realize_trades`/labels reais).
    t_min = cast(datetime, t0_series.min())
    t_max = cast(datetime, t0_series.max())
    return float((t_max - t_min).total_seconds())


# `ret_gross`/`cost_entry_bps`/`cost_exit_bps`/`funding_bps` entram além
# de `ret_net`/`sample_weight` porque `src.models.decomposition` (§16.6)
# precisa dos três termos ORIGINAIS do label, não só o líquido — ver
# docstring daquele módulo. `t0`/`side` são as duas chaves do join.
# Promovida de local de `realize_trades` a constante de módulo em F0
# (`docs/meta_model_design_doc_2026-08-22.md` §12/§15.2) — o Meta precisa
# das MESMAS colunas base, e duas cópias divergiriam em silêncio.
JOIN_BASE_COLUMNS: tuple[str, ...] = (
    "t0",
    "side",
    "barrier_hit",
    "ret_net",
    "sample_weight",
    "ret_gross",
    "cost_entry_bps",
    "cost_exit_bps",
    "funding_bps",
)


def join_signals_to_labels(
    signals: pl.DataFrame, df_all: pl.DataFrame, *, carry: Sequence[str] = ()
) -> pl.DataFrame:
    """Núcleo puro do join sinal→label: liga cada `(t0, side_hat)` ao
    resultado REAL daquele lado em `df_all`. Extraído de `realize_trades`
    (F0 de `docs/meta_model_design_doc_2026-08-22.md` §12, critério de
    refator puro em §14.5) pelo mesmo motivo estrutural que levou
    `alpha.decide_side` a ser extraída de `run_fold`: o Meta precisa juntar
    sinal e label com EXATAMENTE a mesma semântica que o harness de
    avaliação usa, não com uma segunda cópia que pode divergir sem aviso.

    `carry` — colunas ADICIONAIS de `df_all` a trazer junto, além de
    `JOIN_BASE_COLUMNS`. O `meta_training_set` (§3.2) precisa de `t1`,
    `atr_at_t0` e `uniqueness`; `t1` entra para purge e unicidade e
    **nunca** como feature (`META_FORBIDDEN_FEATURES`). Default `()`
    reproduz o comportamento anterior de `realize_trades` byte a byte —
    nenhum chamador existente passa este argumento.

    Left join: linhas cujo lado sinalizado deu `NOFILL` são PRESERVADAS
    (`barrier_hit == "NOFILL"`), nunca descartadas aqui — quem quer só
    trades executados filtra explicitamente, quem mede taxa de
    preenchimento precisa do denominador completo. É também o que o §3.3
    item 4 do design doc do Meta exige (NOFILL fica no frame com
    `y_meta = null`; o denominador do ablation precisa da população
    completa), ao contrário de `dataset.side_subset`, que descarta NOFILL.

    **`side` NÃO sai no resultado.** Polars descarta a chave da direita
    (`right_on`) num left join, então o frame devolvido carrega `side_hat`
    e não `side`. O early-return de `realize_trades` declara `side` no
    schema literal e diverge disto — divergência PRESERVADA aqui de
    propósito: este é um refator puro (§14.5), o defeito é anterior a ele
    e foi registrado como achado em vez de corrigido de carona."""
    duplicadas = tuple(c for c in carry if c in JOIN_BASE_COLUMNS)
    if duplicadas:
        raise ValueError(
            f"join_signals_to_labels: carry={duplicadas} já está em "
            "JOIN_BASE_COLUMNS — pedir a mesma coluna duas vezes produz um "
            "select inválido. Remova da lista de carry."
        )
    ausentes = tuple(c for c in carry if c not in df_all.columns)
    if ausentes:
        raise ValueError(
            f"join_signals_to_labels: carry={ausentes} não existe em df_all "
            f"— colunas disponíveis: {sorted(df_all.columns)}."
        )
    colididas = tuple(c for c in carry if c in signals.columns)
    if colididas:
        raise ValueError(
            f"join_signals_to_labels: carry={colididas} também existe em "
            "signals — polars sufixaria a coluna da direita com '_right' e o "
            "chamador leria a errada sem erro nenhum. Renomeie antes de juntar."
        )
    joined = signals.join(
        df_all.select([*JOIN_BASE_COLUMNS, *carry]),
        left_on=["t0", "side_hat"],
        right_on=["t0", "side"],
        how="left",
    )
    return joined.with_columns(pl.col("barrier_hit").cast(pl.Utf8))


def realize_trades(fold_results: list[FoldResult], df_all: pl.DataFrame) -> pl.DataFrame:
    """Junta os sinais (`side_hat != 0`) de todos os `fold_results` ao
    resultado REAL do lado sinalizado em `df_all` (`labels/v1/labels.parquet`
    já enriquecido, `src.models.dataset.build_modeling_frame`). Linhas cujo
    lado sinalizado deu `NOFILL` são preservadas com `barrier_hit ==
    "NOFILL"` (não descartadas aqui) — quem quiser só os trades
    EXECUTADOS filtra explicitamente, quem quer medir taxa de preenchimento
    do sinal precisa do denominador completo.

    O join em si vive em `join_signals_to_labels` desde F0 — esta função
    ficou com o que é específico do harness: achatar `fold_results` em um
    frame de sinais e o early-return de schema literal."""
    parts: list[pl.DataFrame] = []
    for fr in fold_results:
        sig = fr.predictions.filter(pl.col("side_hat") != 0).select(
            pl.col("t0"),
            pl.col("side_hat"),
            pl.col("fold_id"),
            pl.lit(fr.path_id, dtype=pl.Int64).alias("path_id"),
            pl.lit(fr.variant, dtype=pl.Utf8).alias("variant"),
        )
        parts.append(sig)
    if not parts:
        return pl.DataFrame(
            schema={
                "t0": pl.Datetime("ms", "UTC"),
                "side_hat": pl.Int8,
                "fold_id": pl.Int16,
                "path_id": pl.Int64,
                "variant": pl.Utf8,
                "side": pl.Int8,
                "barrier_hit": pl.Utf8,
                "ret_net": pl.Float64,
                "sample_weight": pl.Float64,
                "ret_gross": pl.Float64,
                "cost_entry_bps": pl.Float64,
                "cost_exit_bps": pl.Float64,
                "funding_bps": pl.Float64,
            }
        )
    all_signals = pl.concat(parts, how="vertical")
    return join_signals_to_labels(all_signals, df_all)


@dataclass(frozen=True, slots=True)
class PathBacktestResult:
    path_id: int
    n_signals: int
    n_filled_trades: int
    fill_rate: float
    sharpe_naive: float
    mean_trade_ret: float
    std_trade_ret: float
    trades_per_year: float


def backtest_by_path(
    fold_results: list[FoldResult], df_all: pl.DataFrame
) -> dict[int, PathBacktestResult]:
    """Um `PathBacktestResult` por caminho de backtest do CPCV (5, §11.4) —
    cada caminho reconstrói o dataset inteiro exatamente uma vez (união dos
    3 splits daquele `path_id`, sem sobreposição de barra, ver docstring de
    `src.validation.cpcv`), então é uma trajetória OOS completa e válida."""
    realized_all = realize_trades(fold_results, df_all)
    path_ids = sorted({fr.path_id for fr in fold_results})
    out: dict[int, PathBacktestResult] = {}
    for path_id in path_ids:
        sub = realized_all.filter(pl.col("path_id") == path_id).sort("t0")
        n_signals = sub.height
        filled = sub.filter(pl.col("barrier_hit") != "NOFILL")
        n_filled = filled.height
        fill_rate = float(n_filled) / float(n_signals) if n_signals > 0 else float("nan")
        span = span_seconds(filled["t0"])
        rets = filled["ret_net"].to_numpy().astype(np.float64)
        sharpe, tpy = sharpe_naive(rets, span_seconds=span)
        mean_ret = float(np.mean(rets)) if rets.size else float("nan")
        std_ret = (
            float(np.std(rets, ddof=1)) if rets.size >= _MIN_TRADES_FOR_SHARPE else float("nan")
        )
        out[path_id] = PathBacktestResult(
            path_id=path_id,
            n_signals=n_signals,
            n_filled_trades=n_filled,
            fill_rate=fill_rate,
            sharpe_naive=sharpe,
            mean_trade_ret=mean_ret,
            std_trade_ret=std_ret,
            trades_per_year=tpy,
        )
    logger.info(
        "models.backtest_lite.backtest_by_path",
        n_paths=len(out),
        sharpe_by_path={pid: r.sharpe_naive for pid, r in out.items()},
    )
    return out


@dataclass(frozen=True, slots=True)
class PathDispersionStats:
    """AG-214 — dispersão do Sharpe ENTRE caminhos do CPCV.

    **Achado (`lgbm-crypto-quant`, 2026-08-25).** O relatório do Sprint 8
    reporta `camada1_sharpe_mean`/`camada0_sharpe_mean` e a contagem de
    caminhos em que a Camada 1 supera a Camada 0 — mas **nenhuma medida de
    dispersão**. Sem σ, "a Camada 1 ganhou em 4 de 5 caminhos" não tem
    como ser lido: toda diferença menor que σ é ruído, e σ não estava
    sendo calculado em lugar nenhum.

    **Leitura obrigatória junto com o número (não é rodapé).** Os 5
    caminhos do CPCV NÃO são 5 amostras independentes: pela construção
    documentada em `src.validation.cpcv` (item 3 da docstring do módulo),
    cada caminho cobre os `n_groups` grupos EXATAMENTE UMA VEZ — ou seja,
    os 5 reconstroem o MESMO dataset, com modelos treinados em partições
    diferentes. Logo `std_between_paths` mede variabilidade de TREINO
    (sensibilidade do modelo à partição), **não** erro amostral do dado.
    É o número certo para responder "esse resultado é estável à
    partição?" e o número errado para responder "esse Sharpe é
    distinguível de zero?" — para a segunda pergunta é preciso DSR sobre
    `N_lifetime` (`src.validation.dsr`) e o ESS de `AG-211`."""

    n_paths: int
    mean: float
    std_between_paths: float
    min: float
    max: float


def path_dispersion_stats(by_path: dict[int, PathBacktestResult]) -> PathDispersionStats:
    """Núcleo puro (Idioma A) — `PathDispersionStats` de um dicionário
    `{path_id: PathBacktestResult}`. `NaN` (caminho sem trades
    suficientes) é descartado antes de agregar, nunca propagado como se
    fosse um Sharpe zero."""
    finite = np.asarray(
        [r.sharpe_naive for r in by_path.values()], dtype=np.float64
    )
    finite = finite[np.isfinite(finite)]
    n = int(finite.shape[0])
    if n == 0:
        return PathDispersionStats(0, float("nan"), float("nan"), float("nan"), float("nan"))
    std = float(np.std(finite, ddof=1)) if n >= _MIN_TRADES_FOR_SHARPE else float("nan")
    return PathDispersionStats(
        n_paths=n,
        mean=float(np.mean(finite)),
        std_between_paths=std,
        min=float(np.min(finite)),
        max=float(np.max(finite)),
    )


@dataclass(frozen=True, slots=True)
class PermutationNullResult:
    """ADR-005 §13.13 (item 5 de §13.17) — o Sharpe REAL (`alpha_sharpe_
    headline`) lido contra a distribuição do mesmo pipeline treinado
    sobre `label`/`ret_net` embaralhados (`null_permutation_seed`,
    `k` réplicas). Sem isto, `§13.13` mede: 69 features de ruído
    gaussiano puro, `y`/`w` REAIS, dispara sinal a 1,77%-1,94% do alvo —
    "uma probabilidade calibrada com dispersão própria" que não distingue
    sinal real de artefato do pipeline. `headline_percentile` é a fração
    dos `k` nulos que o Sharpe real supera -- `1.0` = supera todos,
    `0.0` = não supera nenhum (pior que todo o nulo)."""

    k_replicas: int
    headline: float
    null_sharpes: tuple[float, ...]
    headline_percentile: float


def percentile_rank(headline: float, null_distribution: FloatArray) -> float:
    """Núcleo puro (Idioma A) — fração de `null_distribution` que o
    `headline` real SUPERA (`<=`, não `<`: um nulo empatado conta a
    favor do nulo, leitura conservadora -- não infla o percentual do
    real por causa de empates). `NaN` em `null_distribution` (réplica
    degenerada, caminho sem trades suficientes) é descartado antes de
    contar, nunca tratado como se o real o tivesse batido."""
    finite = null_distribution[np.isfinite(null_distribution)]
    if finite.shape[0] == 0:
        return float("nan")
    if not np.isfinite(headline):
        return float("nan")
    return float(np.mean(finite <= headline))


# AG-214 — política de desempate do critério de permanência (§5.11).
# `TIE_REQUIRES_MARGIN`/`min_margin` (a 2ª opção que existia aqui) foram
# APOSENTADOS 2026-08-27 (handoff de `src/models/`, item 2, `ADR-004`
# §6): o próprio `ADR-004` decidiu que "empate" não é um margin escalar
# estipulado sobre `sharpe_naive` -- é "o IC de 95% da diferença exclui
# zero" (`permanence_significance_by_path`, `AG-220`, já implementado e
# consumido em `permanence_pass_criterion` abaixo). `min_margin` nunca
# teve default (B23 -- não havia base pra estipular um número) e nunca
# teve caller de produção; não recebeu calibração nova, foi substituído
# pelo instrumento que o `ADR-004` já escolheu.
TIE_LEGACY_COUNTS_AS_BETTER = "legacy_tie_counts_as_better"


def permanence_count(
    camada1_by_path: dict[int, PathBacktestResult],
    camada0_by_path: dict[int, PathBacktestResult],
) -> tuple[int, int]:
    """`(n_paths_melhores, n_paths_total)` — quantos dos caminhos a Camada 1
    supera a Camada 0 conceitual (mesmo `path_id` nos dois dicionários,
    §5.11 adaptado). `NaN` (sem trades suficientes) nunca conta como
    melhora.

    **Achado (`lgbm-crypto-quant`, 2026-08-25, `AG-214`).** A comparação é
    `s1 >= s0`: **empate exato conta como "Camada 1 melhor"**. Isso
    contraria diretamente a diretriz do `CLAUDE.md` de que toda regra
    travada a priori precisa de DEFINIÇÃO OPERACIONAL de cada termo — em
    particular de "empate" —, que existe justamente porque `AG-114`/
    `AG-118`/`AG-122` já queimaram este projeto uma vez com um gate cujo
    termo não estava definido. E o viés não é neutro: ele aponta sempre
    para a mesma conclusão (manter a Camada 1), que é o desfecho que
    custa mais `N_lifetime`. **Por isso esta contagem NUNCA decide
    sozinha** — `permanence_pass_criterion` abaixo exige também que a
    diferença seja estatisticamente distinguível de ruído
    (`permanence_significance_by_path`), fechando exatamente o viés que
    este parágrafo descreve."""
    common = sorted(set(camada1_by_path) & set(camada0_by_path))
    n_better = 0
    for pid in common:
        s1 = camada1_by_path[pid].sharpe_naive
        s0 = camada0_by_path[pid].sharpe_naive
        if not (np.isfinite(s1) and np.isfinite(s0)):
            continue
        if s1 >= s0:
            n_better += 1
    return n_better, len(common)


def permanence_pass_criterion(
    *, n_better: int, min_paths_required: int, n_paths_significant: int
) -> bool:
    """Critério de permanência (§5.11 adaptado) — `ADR-004` §6, achado
    real 2026-08-27 (handoff de `src/models/`, item 2): `n_better >=
    min_paths_required` sozinho repete o defeito que `AG-214`/`AG-220`
    já documentaram (empate favorece sempre manter a Camada 1, contagem
    de caminhos que reconstroem o MESMO dataset tem `n` efetivo ≈ 1) —
    `permanence_pass` ignorava `n_paths_significant`
    (`permanence_significance_by_path`, IC bootstrap por blocos) apesar
    dele já estar calculado no relatório.

    **Definição operacional (`CLAUDE.md`, "toda regra travada a priori
    precisa de definição operacional"):** passa sse `n_better >=
    min_paths_required` E `n_paths_significant >= min_paths_required` --
    o MESMO piso pros dois lados (nenhum número novo inventado, B23; o
    piso já é uma constante com proveniência declarada,
    `alpha_layer1_permanence_min_paths`). Não é o veredito de três
    estados que o `ADR-004` §6 descreve como ideal ("indeterminado" ≠
    "false") -- é a forma booleana mais simples que fecha o viés
    descrito, decisão de implementação registrada aqui, não uma
    reinterpretação do ADR."""
    return n_better >= min_paths_required and n_paths_significant >= min_paths_required


# ADR-004 Fase 0 (docs/ADR-004_reformulacao_alvo_regra_decisao_e_
# inferencia_2026-08-25.md §5/§7) -- companion de `permanence_count`
# motivado por AG-220/AG-220-ADDENDUM: 3 rodadas pareadas reais de
# BTCUSDT/R1 mostraram |delta(sharpe)| < sigma nas 3, e o veredito
# binário do gate oscilou FALSO->VERDADEIRO->FALSO só por escolha de
# calibração de threshold -- o gate atual conta caminhos vencedores sem
# nunca perguntar se a diferença é distinguível de ruído. Isto responde
# a segunda pergunta via bootstrap por blocos (`src.validation.
# bootstrap_diff`, núcleo genérico) sobre os `ret_net` JÁ MATERIALIZADOS
# nesta mesma rodada -- zero retreino extra.


def path_bar_indices(path_id: int, splits: Sequence[Any]) -> NDArray[np.int64]:
    """União das posições de teste (`test_idx`) de todos os splits que
    pertencem a `path_id` -- casca fina sobre `CPCVSplit`
    (`src.validation.cpcv`), duck-typed via `.path_id`/`.test_idx` pra
    não criar dependência de tipo só pra isso."""
    idx = np.concatenate([np.asarray(s.test_idx) for s in splits if s.path_id == path_id])
    return np.unique(idx).astype(np.int64)


def camada_diff_series(
    c1_folds: list[FoldResult],
    c0_folds: list[FoldResult],
    df_all: pl.DataFrame,
    path_id: int,
    bar_idx: NDArray[np.int64],
) -> tuple[FloatArray, NDArray[np.bool_]]:
    """`(r1_t - r0_t, has_signal_t)` sobre TODO o universo de barras do
    path (`bar_idx`), não só as barras com sinal -- barra sem sinal em
    uma camada entra como `0.0` (estratégia flat), nunca excluída nem
    NaN: excluir mudaria a base de comparação exatamente quando as duas
    camadas discordam sobre QUAL barra sinalizar, que é parte do que o
    teste precisa capturar. `has_signal_t` (`True` se QUALQUER camada
    sinalizou naquela barra) é o que permite ao chamador (`permanence_
    significance_by_path`) montar a leitura signal-only sem recomputar
    `realize_trades` -- achado real (`AG-252`): a versão zero-filled DILUI
    a magnitude do `point_estimate` (~20-60x menor, medido em BTCUSDT/R1,
    96-98% das barras são zero-zero) — nunca deve ser lida como o efeito
    econômico POR TRADE, só como o efeito por BARRA do backtest. Ordenado
    por `t0` -- o bootstrap por blocos precisa da ordem cronológica real,
    não da ordem de `bar_idx`.

    **Correção (AG-252, achada ao escrever o teste unitário desta
    função).** `bar_idx` vem de `path_bar_indices`, que por sua vez usa
    `CPCVSplit.test_idx` -- posições em `df_all`, que tem DUAS linhas por
    barra (`side=1` e `side=-1`, mesmo contrato de `alpha._unique_test_
    bars`). Sem deduplicar, `bars` continha as DUAS linhas de cada barra
    (mesmo `t0` duplicado), inflando `n_total_bars` ~2x e criando um par
    adjacente artificial após `.sort("t0")` que distorcia a ACF/block_
    length medidos (a mesma classe de erro que `_unique_test_bars` já
    existe para evitar, aplicada agora aqui também)."""

    def _ret_by_bar(folds: list[FoldResult]) -> pl.DataFrame:
        trades = realize_trades([fr for fr in folds if fr.path_id == path_id], df_all)
        filled = trades.filter(pl.col("barrier_hit") != "NOFILL").select("t0", "ret_net")
        return bars.join(filled, on="t0", how="left").with_columns(pl.col("ret_net").fill_null(0.0))

    bars = (
        df_all[bar_idx]
        .filter(pl.col("side") == 1)
        .unique(subset=["t0"], keep="first")
        .select("t0")
        .sort("t0")
    )
    r1_df = _ret_by_bar(c1_folds)
    r0_df = _ret_by_bar(c0_folds)
    r1 = r1_df["ret_net"].to_numpy().astype(np.float64)
    r0 = r0_df["ret_net"].to_numpy().astype(np.float64)
    has_signal = (r1 != 0.0) | (r0 != 0.0)
    return r1 - r0, has_signal


@dataclass(frozen=True, slots=True)
class PermanenceSignificanceResult:
    """Duas leituras, nunca reduzidas a uma só (mesmo princípio de
    `TauPathRealization` pré/pós-fill em `src.analysis.tau_diagnostics`)
    -- achado real (`AG-252`, medido em BTCUSDT/R1): `zero_filled` dilui
    o `point_estimate` em ~20-60x contra `signal_only` (96-98% das barras
    são zero-zero nesse combo), então `zero_filled` NUNCA deve ser lido
    como magnitude econômica por trade -- só `signal_only` responde essa
    pergunta. O `significant` (True/False) dos dois CONCORDOU nos 5
    caminhos medidos, mas isso é UMA medição, não uma prova geral -- leia
    os dois, não presuma que sempre concordam."""

    zero_filled: bootstrap_diff.BootstrapDiffResult
    signal_only: bootstrap_diff.BootstrapDiffResult


def permanence_significance_by_path(
    c1_folds: list[FoldResult],
    c0_folds: list[FoldResult],
    df_all: pl.DataFrame,
    splits: Sequence[Any],
    *,
    n_boot: int,
    confidence_level: float,
    seed: int,
) -> dict[int, PermanenceSignificanceResult]:
    """Por `path_id`, IC bootstrap da diferença Camada1-Camada0 sobre o
    universo completo de barras do path (`zero_filled`) E sobre a
    subsérie onde pelo menos uma camada sinalizou (`signal_only`, AG-252).
    Companion de `permanence_count`, não substituto: onde aquele conta
    "quantos caminhos venceram", este responde "a diferença em CADA
    caminho é distinguível de ruído" — AG-220 mostrou que nenhuma das duas
    perguntas é redundante com a outra. `seed + path_id` mantém
    reprodutibilidade determinística sem reamostrar os 5 caminhos com o
    mesmo padrão; `signal_only` usa `seed + path_id + 1_000_000` (mesma
    convenção de derivação determinística de seed do resto do projeto,
    offset grande o bastante pra nunca colidir com nenhum `path_id`
    real)."""
    path_ids = sorted({fr.path_id for fr in c1_folds} & {fr.path_id for fr in c0_folds})
    out: dict[int, PermanenceSignificanceResult] = {}
    for path_id in path_ids:
        bar_idx = path_bar_indices(path_id, splits)
        diff, has_signal = camada_diff_series(c1_folds, c0_folds, df_all, path_id, bar_idx)
        zero_filled = bootstrap_diff.stationary_bootstrap_ci(
            diff, n_boot=n_boot, confidence_level=confidence_level, seed=seed + path_id
        )
        signal_only = bootstrap_diff.stationary_bootstrap_ci(
            diff[has_signal],
            n_boot=n_boot,
            confidence_level=confidence_level,
            seed=seed + path_id + 1_000_000,
        )
        out[path_id] = PermanenceSignificanceResult(zero_filled=zero_filled, signal_only=signal_only)
    return out
