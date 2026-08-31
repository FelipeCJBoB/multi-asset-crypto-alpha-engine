"""ADR-008 Fase 4 — walk-forward real sobre o Alpha (fecha o Item 6 da
`ADR-007`). `generate_anchored_walk_forward_splits`
(`src.validation.volatility_walkforward`) já existe pro M1 (comparação de
estimadores de volatilidade formula-fechada, causais por construção, sem
`fit` de modelo nenhum — por isso nunca precisou de purge por `t1`).
Reusado aqui pro Alpha, que AJUSTA um LightGBM real sobre o treino de cada
fold — diferente do M1, a fronteira treino/teste passa a carregar risco de
vazamento por `t1` (B09) que não existia lá: sem purge, uma barra de
TREINO cujo `t1` (fim da barreira tripla) cai DENTRO ou DEPOIS do início
do bloco de TESTE tem seu label determinado por preço que só existe no
futuro em relação ao corte de treino.

`walk_forward_split_to_cpcv_split` — adaptador fino: `WalkForwardSplit`
(índices por trimestre civil ancorado) -> `CPCVSplit` (o contrato mínimo
que `alpha.run_fold` de fato lê — só `train_idx`/`test_idx`/`split_id`/
`path_id`, ver docstring de `run_fold`; os outros 5 campos de `CPCVSplit`
nunca são tocados por `run_fold`). Escrever um adaptador fino em vez de
generalizar a assinatura de `run_fold` (a alternativa que o ADR-008
também considerava) evita qualquer edição na função mais testada do
motor — zero risco novo pra ela.

**Achado real (execução real contra `BTCUSDT/R2`, não hipotético):**
`generate_anchored_walk_forward_splits` exige `open_time_ms` estritamente
crescente (`np.searchsorted`), mas `mf.data`/`labels` (o `df_all` que
`alpha.run_fold` de fato fatia) tem DUAS linhas por barra — uma por lado
(`side=1`/`side=-1`, mesma garantia de `labels.parquet` já documentada em
`alpha._unique_test_bars`) — `t0` REPETE e não é globalmente monótono.
Por isso os índices de `WalkForwardSplit` (posições numa timeline
ÚNICA/ordenada, `unique_t0_ms`, gerada pelo chamador via `np.unique`) são
traduzidos aqui em FRONTEIRAS DE TEMPO (timestamp), aplicadas como filtro
booleano sobre `t0_ms`/`t1_ms` do `df_all` de 2 linhas/barra — nunca como
posição direta (as duas timelines têm tamanhos diferentes). Mesmo idioma
de `src.validation.cpcv.generate_splits`, que já resolve purge por
comparação de VALOR (`t0_ms`/`t1_ms`), não por posição.

Campos de `CPCVSplit` sem equivalente sob uma única fronteira cronológica
contígua (CPCV tem grupos combinatórios espalhados no tempo, com purge E
embargo nos dois sentidos; walk-forward ancorado tem só 1 fronteira, teste
sempre estritamente POSTERIOR ao treino, nunca embaralhado) — documentados
como vazio abaixo, não improvisados: `test_groups=()`, `train_groups=()`,
`n_embargoed=0`. `path_id=wf_split.fold_id` (não `0` fixo) É deliberado,
não sobra do vocabulário CPCV: `backtest_lite.backtest_by_path` agrupa
resultado por `path_id` — usar `fold_id` como `path_id` faz cada fold de
walk-forward virar seu próprio "caminho" de 1 fold, reusando essa função
JÁ TESTADA pra métrica por fold (sharpe/win_rate/edge) em vez de duplicar
a lógica de `realize_trades`/agregação aqui."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from src.validation.cpcv import CPCVSplit
from src.validation.volatility_walkforward import (
    WalkForwardSplit,
    generate_anchored_walk_forward_splits,
)

from . import alpha, backtest_lite, score_quality
from ._constants import load_constant

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]
_BPS_PER_UNIT = 10_000  # mesma constante nomeada de score_quality.py/hyperparams_optuna.py
_MIN_FOLDS_FOR_STD = 2  # noqa: magic-number -- desvio-padrão amostral (ddof=1) exige >=2 pontos
_AGGREGATE_STAT_NAMES: tuple[str, ...] = ("sharpe", "edge_bps", "win_rate")


def walk_forward_split_to_cpcv_split(
    wf_split: WalkForwardSplit,
    unique_t0_ms: IntArray,
    t0_ms: IntArray,
    t1_ms: IntArray,
) -> CPCVSplit:
    """`unique_t0_ms` — timeline ÚNICA e ordenada de `t0` (1 valor por
    barra, `np.unique` sobre o `t0` de `df_all`) usada pra GERAR
    `wf_split` (`generate_anchored_walk_forward_splits` exige índice
    estritamente crescente). `t0_ms`/`t1_ms` — arrays paralelos ao
    `df_all` REAL de 2 linhas/barra que `alpha.run_fold` vai fatiar
    (mesma convenção de `alpha._temporal_purged_calib_split`: núcleo
    puro, a extração de `df_all["t0"]`/`df_all["t1"]` fica a cargo do
    chamador, computada uma vez fora do loop de folds).

    Purge (B09, mesmo idioma de `_temporal_purged_calib_split`): descarta
    do treino toda linha cujo `t1` ainda esteja ABERTO quando o bloco de
    teste começa. Levanta `ValueError` se o purge esvaziar o treino
    inteiro — fold degenerado, falha alta em vez de treinar sobre 0
    linhas."""
    n_unique = unique_t0_ms.shape[0]
    test_start_time = int(unique_t0_ms[wf_split.test_start_idx])
    # `test_end_idx` pode ser o comprimento da timeline única (último
    # fold, "até o fim da série") -- sem entrada em `unique_t0_ms` pra
    # ler; `t0_ms.max() + 1` fecha o intervalo à direita sem excluir a
    # última barra real (comparação é `< test_end_time`, exclusiva).
    test_end_time = (
        int(unique_t0_ms[wf_split.test_end_idx])
        if wf_split.test_end_idx < n_unique
        else int(t0_ms.max()) + 1
    )

    train_candidates = np.flatnonzero(t0_ms < test_start_time)
    keep = t1_ms[train_candidates] < test_start_time
    train_idx = train_candidates[keep]
    if train_idx.shape[0] == 0:
        raise ValueError(
            "walk_forward_split_to_cpcv_split: purge por t1 esvaziou o treino do "
            f"fold_id={wf_split.fold_id} (test_start_time={test_start_time}) -- fold "
            "degenerado, horizonte de label cobre todo o prefixo de treino"
        )
    test_idx = np.flatnonzero((t0_ms >= test_start_time) & (t0_ms < test_end_time))
    return CPCVSplit(
        split_id=wf_split.fold_id,
        path_id=wf_split.fold_id,
        test_groups=(),
        train_groups=(),
        train_idx=train_idx,
        test_idx=test_idx,
        n_train_candidate=int(train_candidates.shape[0]),
        n_purged=int(train_candidates.shape[0] - train_idx.shape[0]),
        n_embargoed=0,
    )


def min_test_bars_for_non_degenerate_fold(target_signal_rate: float) -> int:
    """Piso de barras de TESTE válidas (pós `alpha._unique_test_bars`,
    mesma contagem de `FoldResult.n_test_bars`) pra um fold de
    walk-forward não ser degenerado — critério operacional definido a
    priori (Manager, 2026-08-31, ADR-008 Fase 4): "fold degenerado" =
    `n_test_bars < min_test_bars_for_non_degenerate_fold(target_signal_
    rate)`.

    Reusa `alpha.MIN_OCCURRENCES_ABOVE_TAU` (10 — o mesmo piso de
    "amostra grande o bastante pra ver o percentil de interesse com ~10
    ocorrências" já usado por `alpha._resolve_tau_on_common_bars`),
    aplicado aqui ao número ESPERADO de SINAIS no fold (`n_test_bars *
    target_signal_rate`) em vez de ocorrências acima de um quantil —
    mesmo princípio estatístico ("preciso de ~10 pontos pra uma leitura
    de cauda ter sentido"), população diferente. DERIVADO de `target_
    signal_rate` (nunca uma contagem fixa de barras) pela mesma razão
    que a constante que reusa já é derivada — dois `target_signal_rate`
    diferentes (ex. combos com risco/custo diferente) produzem pisos de
    barra DIFERENTES, corretamente."""
    return int(np.ceil(alpha.MIN_OCCURRENCES_ABOVE_TAU / target_signal_rate))


def _aggregate_stats(values: list[float]) -> dict[str, float]:
    """mean/median/std/min/max sobre `values`, `NaN` descartado antes de
    agregar (nunca propagado como se fosse zero) — mesma convenção de
    `backtest_lite.path_dispersion_stats`. `std` exige `>=2` pontos
    finitos (desvio-padrão amostral indefinido com 1 ponto)."""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.shape[0] == 0:
        nan = float("nan")
        return {"n": 0.0, "mean": nan, "median": nan, "std": nan, "min": nan, "max": nan}
    std = (
        float(np.std(finite, ddof=1)) if finite.shape[0] >= _MIN_FOLDS_FOR_STD else float("nan")
    )
    return {
        "n": float(finite.shape[0]),
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "std": std,
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
    }


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


@dataclass(frozen=True, slots=True)
class WalkForwardFoldMetrics:
    fold_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    n_train_bars: int
    n_purged: int
    n_test_bars: int
    degenerado: bool
    sharpe: float
    edge_bps: float
    win_rate: float
    n_signals: int
    n_filled_trades: int
    # 1 entrada por lado com trade válido (mesmo contrato de
    # `score_quality.compute_score_quality`) -- lado sem trade fica
    # ausente do dict, não aparece com `NaN`.
    score_quality_by_side: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    symbol: str
    resolution_id: str
    variant: str
    n_folds_total: int
    n_folds_degenerados: int
    n_folds_usados: int
    min_test_bars_threshold: int
    fold_results: tuple[WalkForwardFoldMetrics, ...]
    aggregate: dict[str, dict[str, float]]


def run_walk_forward_for_combo(
    mf_data: pl.DataFrame,
    *,
    symbol: str,
    resolution_id: str,
    variant: str,
    hyper: alpha.LGBMHyperparams,
    seed: int,
    target_signal_rate: float,
    device_type: str = "cpu",
    tau_policy: str = alpha.TAU_POLICY_LEGACY_PER_SIDE,
    calib_split_mode: str = alpha.CALIB_SPLIT_TEMPORAL_PURGED,
    class_balance_basis: str = alpha.CLASS_BALANCE_WEIGHT,
    calib_weight_basis: str = alpha.CALIB_WEIGHT_UNIQUENESS,
    initial_train_years: int | None = None,
    model_id_prefix: str = "walk_forward",
) -> WalkForwardResult:
    """Walk-forward real (RETREINO, um `alpha.run_fold` por fold ancorado)
    sobre `mf_data` já carregado pelo chamador — `build_modeling_frame`
    (~20s) fica FORA desta função de propósito, pra ser chamado 1 vez só
    e reusado entre Camada1/Camada0 do mesmo combo (esta função é
    per-`variant`, mesmo padrão de `alpha.run_fold`/`run_all_folds`).

    `initial_train_years=None` (default) resolve pra `constants.yaml::
    m1_walkforward_initial_train_years` (protocolo M1, PRD_V4_1.md §3.2 —
    mesmo valor que `src.regime.build_hmm`/`src.analysis.m4_*` já usam).

    Levanta `ValueError` se `generate_anchored_walk_forward_splits`
    devolver 0 folds (série curta demais) — falha alta, nunca um
    resultado vazio silencioso."""
    initial_train_years_eff = (
        initial_train_years
        if initial_train_years is not None
        else int(load_constant("m1_walkforward_initial_train_years"))
    )
    t0_ms = mf_data["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    t1_ms = mf_data["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    unique_t0_ms = np.unique(t0_ms)
    wf_splits = generate_anchored_walk_forward_splits(
        unique_t0_ms, initial_train_years=initial_train_years_eff
    )
    if not wf_splits:
        raise ValueError(
            f"run_walk_forward_for_combo: {symbol}/{resolution_id} -- 0 folds gerados "
            f"(série curta demais pra initial_train_years={initial_train_years_eff})"
        )

    min_test_bars = min_test_bars_for_non_degenerate_fold(target_signal_rate)
    model_id = f"{model_id_prefix}_{symbol}_{resolution_id}_{variant}"

    def _fold_boundaries_iso(wf_split: WalkForwardSplit) -> tuple[str, str, str, str]:
        test_end_bar_idx = min(wf_split.test_end_idx, unique_t0_ms.shape[0]) - 1
        return (
            _ms_to_iso(int(unique_t0_ms[0])),
            _ms_to_iso(int(unique_t0_ms[wf_split.train_end_idx - 1])),
            _ms_to_iso(int(unique_t0_ms[wf_split.test_start_idx])),
            _ms_to_iso(int(unique_t0_ms[test_end_bar_idx])),
        )

    fold_metrics: list[WalkForwardFoldMetrics] = []
    pending: list[tuple[WalkForwardSplit, CPCVSplit, alpha.FoldResult]] = []
    for wf_split in wf_splits:
        cpcv_split = walk_forward_split_to_cpcv_split(wf_split, unique_t0_ms, t0_ms, t1_ms)
        train_start_iso, train_end_iso, test_start_iso, test_end_iso = _fold_boundaries_iso(
            wf_split
        )

        # Achado real (BTCUSDT/R2, fold_id=2, 2026-08-31, primeira execução
        # real da campanha): um fold com 0 barras de teste válidas
        # (`alpha.unique_test_bars` vazio -- ex. gap de dado real numa
        # feature específica, ver E14f_toptrader_ls_ratio) faz `alpha.
        # run_fold` quebrar dentro do `predict_proba` do LightGBM
        # (`ValueError` de array vazio) DEPOIS de já ter treinado os dois
        # lados -- checar aqui evita o treino desperdiçado e trata como
        # degenerado direto, sem chamar `run_fold`.
        test_bars_check = alpha.unique_test_bars(mf_data[cpcv_split.test_idx])
        if test_bars_check.height == 0:
            logger.warning(
                "models.walk_forward.fold_sem_barra_de_teste_valida",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                fold_id=wf_split.fold_id,
                detail="0 barras de teste com feature valida -- fold pulado (run_fold "
                "quebraria no predict_proba), tratado como degenerado direto",
            )
            fold_metrics.append(
                WalkForwardFoldMetrics(
                    fold_id=wf_split.fold_id,
                    train_start=train_start_iso,
                    train_end=train_end_iso,
                    test_start=test_start_iso,
                    test_end=test_end_iso,
                    n_train_bars=int(cpcv_split.train_idx.shape[0]),
                    n_purged=int(cpcv_split.n_purged),
                    n_test_bars=0,
                    degenerado=True,
                    sharpe=float("nan"),
                    edge_bps=float("nan"),
                    win_rate=float("nan"),
                    n_signals=0,
                    n_filled_trades=0,
                    score_quality_by_side={},
                )
            )
            continue

        fold_result = alpha.run_fold(
            mf_data,
            cpcv_split,
            variant=variant,
            hyper=hyper,
            model_id=model_id,
            seed=seed,
            symbol=symbol,
            resolution_id=resolution_id,
            device_type=device_type,
            tau_policy=tau_policy,
            calib_split_mode=calib_split_mode,
            class_balance_basis=class_balance_basis,
            calib_weight_basis=calib_weight_basis,
        )
        pending.append((wf_split, cpcv_split, fold_result))
        logger.info(
            "models.walk_forward.fold_concluido",
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            fold_id=wf_split.fold_id,
            n_folds_total=len(wf_splits),
            n_train_bars=int(cpcv_split.train_idx.shape[0]),
            n_test_bars=fold_result.n_test_bars,
        )

    fold_results_ok = [fr for _, _, fr in pending]
    by_path = backtest_lite.backtest_by_path(fold_results_ok, mf_data) if fold_results_ok else {}

    for wf_split, cpcv_split, fold_result in pending:
        path_result = by_path.get(cpcv_split.path_id)
        sq = score_quality.compute_score_quality(fold_result.predictions, mf_data)
        sq_by_side = {r.side: asdict(r) for r in sq}
        degenerado = fold_result.n_test_bars < min_test_bars
        train_start_iso, train_end_iso, test_start_iso, test_end_iso = _fold_boundaries_iso(
            wf_split
        )
        fold_metrics.append(
            WalkForwardFoldMetrics(
                fold_id=wf_split.fold_id,
                train_start=train_start_iso,
                train_end=train_end_iso,
                test_start=test_start_iso,
                test_end=test_end_iso,
                n_train_bars=int(cpcv_split.train_idx.shape[0]),
                n_purged=int(cpcv_split.n_purged),
                n_test_bars=fold_result.n_test_bars,
                degenerado=degenerado,
                sharpe=path_result.sharpe_naive if path_result else float("nan"),
                edge_bps=(
                    path_result.mean_trade_ret * _BPS_PER_UNIT if path_result else float("nan")
                ),
                win_rate=path_result.win_rate if path_result else float("nan"),
                n_signals=path_result.n_signals if path_result else 0,
                n_filled_trades=path_result.n_filled_trades if path_result else 0,
                score_quality_by_side=sq_by_side,
            )
        )
        if degenerado:
            logger.warning(
                "models.walk_forward.fold_degenerado",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                fold_id=wf_split.fold_id,
                n_test_bars=fold_result.n_test_bars,
                min_test_bars_threshold=min_test_bars,
                detail="barras de teste validas insuficientes pro target_signal_rate "
                "deste combo -- fold excluido do agregado, mantido no artefato",
            )

    fold_metrics.sort(key=lambda fm: fm.fold_id)
    usaveis = [fm for fm in fold_metrics if not fm.degenerado]
    stat_lists = {name: [getattr(fm, name) for fm in usaveis] for name in _AGGREGATE_STAT_NAMES}
    per_stat = {name: _aggregate_stats(values) for name, values in stat_lists.items()}
    aggregate = {
        stat_key: {name: per_stat[name][stat_key] for name in _AGGREGATE_STAT_NAMES}
        for stat_key in ("mean", "median", "std", "min", "max")
    }

    logger.info(
        "models.walk_forward.combo_concluido",
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        n_folds_total=len(fold_metrics),
        n_folds_degenerados=len(fold_metrics) - len(usaveis),
        sharpe_mean=aggregate["mean"]["sharpe"],
        edge_bps_mean=aggregate["mean"]["edge_bps"],
    )

    return WalkForwardResult(
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        n_folds_total=len(fold_metrics),
        n_folds_degenerados=len(fold_metrics) - len(usaveis),
        n_folds_usados=len(usaveis),
        min_test_bars_threshold=min_test_bars,
        fold_results=tuple(fold_metrics),
        aggregate=aggregate,
    )
