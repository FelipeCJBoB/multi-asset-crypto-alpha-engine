"""Builder de produção do candidato de regime canônico
`hmm_gaussian_k{n}_v1` — Fase B do plano `wise-exploring-panda.md`
(2026-08-21, `PLANO_MESTRE_PRINCE2.md §15.13`). Decisão do Manager: HMM
k=4 autorizado como candidato canônico de produção, apesar de `AG-114`
(regra de decisão de 3 gates + métrica primária, `audit/architecture_gaps
_log.yaml`) permanecer ABERTO quanto à fragilidade do Gate 1 (occupancy) —
ver `canonical_regime_hmm_n_states` em `config/constants.yaml` pra
narrativa completa. Este módulo entrega o CÓDIGO, não decide/fecha essa
metodologia.

**Mecânica de fold deliberadamente DUPLICADA de
`src.analysis.m4_regime_comparison._run_fold_refit_candidate`, não
refatorada pra compartilhar.** Aquela função mistura fit/decode com
cálculo de métricas de COMPARAÇÃO (separation/orthogonality/persistence/
fold_stability) específicas do harness M4, já auditadas 3 vezes (AG-114/
118/119/120/121/122) — acoplar este builder de produção a ela arriscaria
essa superfície auditada por um ganho de DRY pequeno. Mesmo precedente já
usado no repo (`src/regime/_paths.py`/`_constants.py`, duplicação
deliberada pra não acoplar a uma cadeia de imports).

**Sem persistência em disco nesta fase** — não há orquestrador vivo
consumindo ainda (`src/live/__init__.py` vazio, confirmado). Escrever um
artefato aqui seria artefato sem consumidor, decisão deliberadamente
adiada (ver plano, Fase B).

**Contrato de saída candidato-agnóstico** (a peça que já resolve a parte
mais delicada do design, achado do mapeamento de produção): a coluna
`tradeable: bool` tem o MESMO nome/semântica que `src.regime.classifier.
classify_regimes` já produz pro baseline (`TRADEABLE_COL`,
`src.models.dataset`) — `src.risk.limits.control_01_regime_tradeavel`
consome `regime_tradeable: bool` sem precisar traduzir vocabulário de
candidato nenhum (baseline R1-R4 vs. HMM k=4 sem rótulo semântico)."""

from __future__ import annotations

from typing import Final

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from src.data import lake
from src.validation import volatility_walkforward as vwf
from src.validation._constants import load_constant as load_validation_constant
from src.validation.regime_utility import identify_stress_state_by_volatility

from . import hmm_features
from ._constants import load_constant as load_regime_constant
from .hmm_gaussian import fit_hmm_gaussian, hmm_gaussian_classifier_id, predict_hmm_gaussian

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

logger = structlog.get_logger(__name__)

ENGINE_VERSION: Final[str] = "regime_hmm_v1"

# Bar sem decode (antes do 1o fold OOS, ou fold cujo fit degenerou —
# `fit_hmm_gaussian` devolve `None`, mesmo sentinela conceitual de
# `m4_regime_comparison._FOLD_FIT_FAILURE_SENTINEL`, não compartilhado
# por import porque o dtype/uso aqui é local a este módulo). Nunca um
# `canonical_id`/`fold_id` real — real sempre >= 0.
_NO_DECODE_SENTINEL: Final[int] = -1

__all__ = ["ENGINE_VERSION", "build_hmm_regimes"]


def _assemble_output(
    *,
    open_time_ms: IntArray,
    canonical_id: IntArray,
    is_stress_state: NDArray[np.bool_],
    tradeable: NDArray[np.bool_],
    fold_id: IntArray,
    classifier_id: str,
) -> pl.DataFrame:
    return (
        pl.DataFrame(
            {
                "_open_time_ms": open_time_ms,
                "canonical_id": canonical_id,
                "is_stress_state": is_stress_state,
                "tradeable": tradeable,
                "fold_id": fold_id,
            }
        )
        .with_columns(
            pl.from_epoch(pl.col("_open_time_ms"), time_unit="ms")
            .dt.replace_time_zone("UTC")
            .dt.cast_time_unit("ns")
            .alias("t0"),
            pl.lit(classifier_id).alias("classifier_id"),
            pl.lit(ENGINE_VERSION).alias("engine_version"),
        )
        .drop("_open_time_ms")
        .select(
            [
                "t0",
                "canonical_id",
                "is_stress_state",
                "tradeable",
                "fold_id",
                "classifier_id",
                "engine_version",
            ]
        )
    )


def build_hmm_regimes(
    symbol: str,
    start: str,
    end: str,
    *,
    n_states: int | None = None,
    resolution_id: str = "R1",
    initial_train_years: int | None = None,
    seed: int = 0,
) -> pl.DataFrame:
    """Walk-forward ancorado trimestral (`B05` — refit expansivo, mesmo
    `WalkForwardSplit` do M1/M4: `fit_hmm_gaussian(obs, train_end_idx=...)`
    → decodifica só `obs[test_start_idx:test_end_idx]`), sobre o espaço de
    observação `[log_return_1, realized_vol_short]` direto do OHLC da
    dollar-bar (`hmm_features`, mesma convenção do M4).

    `n_states=None` (default) resolve pra `canonical_regime_hmm_n_states`
    (`config/constants.yaml` — ver docstring do módulo pra proveniência
    completa dessa escolha). `initial_train_years=None` resolve pra
    `m1_walkforward_initial_train_years` (mesmo protocolo de `src.analysis.
    m4_regime_comparison.run_regime_comparison_for_symbol`) — nenhuma
    constante de cadência NOVA é criada aqui (decisão do plano: inventar
    uma só pra "documentar" cadência falharia `check_constants_referenced.
    py`, órfã sem chamador real).

    `t0` = `open_time` da barra (convenção de `src.regime.classifier.
    classify_regimes`/`src.regime.build.build_regimes`, não `close_time`
    de `src.labels.triple_barrier` — mesma dualidade já documentada em
    `src.models.dataset`), pra que este builder componha com o mesmo
    padrão de junção do baseline se um consumidor futuro precisar.

    Histórico curto demais pra `initial_train_years` de treino inicial
    (sem folds) — mesmo sentinela de `run_regime_comparison_for_symbol`
    (`splits` vazio) — devolve TODAS as barras com `tradeable=False`
    (`canonical_id`/`fold_id` = -1, sentinela "sem decode"), sem
    exceção; um fold individual que degenera (`fit_hmm_gaussian` retorna
    `None`) é tratado do mesmo jeito, só pra aquele fold — o resto do
    walk-forward segue normal."""
    resolved_n_states = (
        n_states
        if n_states is not None
        else int(load_regime_constant("canonical_regime_hmm_n_states"))
    )
    resolved_train_years = (
        initial_train_years
        if initial_train_years is not None
        else int(load_validation_constant("m1_walkforward_initial_train_years"))
    )
    classifier_id = hmm_gaussian_classifier_id(resolved_n_states)

    bars_df = lake.query_dollar_bars(symbol, start, end, resolution_id=resolution_id)

    log_return_1_full, obs_2d_full = hmm_features.input_obs(bars_df)
    start_idx = hmm_features.valid_start_idx(log_return_1_full, obs_2d_full[:, 1])

    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()[start_idx:]
    obs_2d = obs_2d_full[start_idx:]
    n_bars = obs_2d.shape[0]

    canonical_id = np.full(n_bars, _NO_DECODE_SENTINEL, dtype=np.int64)
    fold_id = np.full(n_bars, _NO_DECODE_SENTINEL, dtype=np.int64)
    is_stress_state = np.zeros(n_bars, dtype=np.bool_)

    splits = vwf.generate_anchored_walk_forward_splits(
        open_time_ms, initial_train_years=resolved_train_years
    )
    if not splits:
        logger.warning(
            "regime.build_hmm.folds_insuficientes",
            symbol=symbol,
            classifier_id=classifier_id,
            n_bars=n_bars,
        )
        return _assemble_output(
            open_time_ms=open_time_ms,
            canonical_id=canonical_id,
            is_stress_state=is_stress_state,
            tradeable=np.zeros(n_bars, dtype=np.bool_),
            fold_id=fold_id,
            classifier_id=classifier_id,
        )

    for split in splits:
        fit = fit_hmm_gaussian(
            obs_2d, n_states=resolved_n_states, train_end_idx=split.train_end_idx, seed=seed
        )
        if fit is None:
            logger.warning(
                "regime.build_hmm.fold_fit_none",
                symbol=symbol,
                classifier_id=classifier_id,
                fold_id=split.fold_id,
                train_end_idx=split.train_end_idx,
            )
            continue
        # AG-127 Ângulo 1: `stress_state_id` identificado LOCALMENTE a este
        # fold -- a partir do próprio TREINO decodificado (`obs_2d[
        # :train_end_idx]`, o mesmo fit já ajustado, nunca o array OOS do
        # símbolo/período inteiro) -- e aplicado só na fatia de TESTE do
        # mesmo fold. A canonicalização antiga (uma única
        # `identify_stress_state_by_volatility` global, pós-loop, sobre o
        # OOS concatenado inteiro) vazava informação de folds futuros pra
        # dentro da rotulagem "stress" de folds passados; mover pra dentro
        # do loop fecha o vazamento sem mudar a semântica de
        # `is_stress_state`/`tradeable` (mesmo critério, só escopo local).
        train_slice = slice(0, split.train_end_idx)
        test_slice = slice(split.test_start_idx, split.test_end_idx)
        train_canonical_id = predict_hmm_gaussian(fit, obs_2d[train_slice])
        canonical_id[test_slice] = predict_hmm_gaussian(fit, obs_2d[test_slice])
        fold_id[test_slice] = split.fold_id

        stress_state_id = identify_stress_state_by_volatility(
            train_canonical_id, obs_2d[train_slice, 1]
        )
        is_stress_state[test_slice] = canonical_id[test_slice] == stress_state_id

    decoded_mask = canonical_id != _NO_DECODE_SENTINEL
    if not np.any(decoded_mask):
        logger.warning(
            "regime.build_hmm.nenhum_fold_decodificado",
            symbol=symbol,
            classifier_id=classifier_id,
            n_folds=len(splits),
        )
    tradeable = decoded_mask & ~is_stress_state

    logger.info(
        "regime.build_hmm.build_hmm_regimes",
        symbol=symbol,
        classifier_id=classifier_id,
        resolution_id=resolution_id,
        n_bars=n_bars,
        n_folds=len(splits),
        n_decoded=int(np.sum(decoded_mask)),
        n_tradeable=int(np.sum(tradeable)),
    )
    return _assemble_output(
        open_time_ms=open_time_ms,
        canonical_id=canonical_id,
        is_stress_state=is_stress_state,
        tradeable=tradeable,
        fold_id=fold_id,
        classifier_id=classifier_id,
    )
