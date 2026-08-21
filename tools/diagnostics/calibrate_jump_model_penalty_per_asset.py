"""Calibração de `m4_jump_model_penalty` POR ATIVO (ETHUSDT/SOLUSDT/
BNBUSDT/XRPUSDT) -- experimento de transferibilidade de λ (AG-087,
`audit/architecture_gaps_log.yaml`), item 2 autorizado pelo Manager,
2026-08-20.

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python tools/diagnostics/calibrate_jump_model_penalty_per_asset.py

**Problema que motiva este script.** `config/constants.yaml::
m4_jump_model_penalty` (valor atual: 0,002) foi calibrado SÓ sobre
BTCUSDT (últimas 50.000 barras válidas de R1, ver `constants.yaml::
m4_jump_model_penalty.source`) e é aplicado sem reteste aos outros 4
símbolos do M4 -- `AG-087` mede ~25-29% de saturação (colapso a 1 estado,
`switch_rate=0,0`) nas células não-BTC sob esse λ fixo. Este script
replica a MESMA metodologia da calibração original, independentemente,
para cada um dos 4 ativos -- Condição B do experimento de
transferibilidade (`src.analysis.m4_critical_windows.run_jump_model_
transferability_comparison`, que consome o resultado desta medição via
`jump_penalty_by_symbol`).

**Metodologia -- idêntica a `constants.yaml::m4_jump_model_penalty.
source` (2026-08-18), 1x por ativo em vez de só BTC:**

  Grid (mesmo grid ampliado já usado na calibração original de BTC):
  `[0,0001; 0,0005; 0,001; 0,002; 0,005; 0,01; 0,02]`.

  Fatia: últimas `_WINDOW_BARS` (50.000) barras VÁLIDAS do PRÓPRIO ativo
  (`obs_2d=[log_return_1, realized_vol_short]`, mesma convenção/escala do
  M4, `_RESOLUTION_ID="R1"` -- mesma resolução implícita da calibração
  original de BTC, `m4.RESOLUTION_ID` default do módulo, não documentada
  explicitamente em `constants.yaml::m4_jump_model_penalty.source` mas
  inferida por ser a única resolução em uso quando essa calibração
  aconteceu, 2026-08-18, antes da Fase B/multi-resolução) -- `_TRAIN_BARS`
  (40.000) treino + `_TEST_BARS` (10.000) teste.

  Pra cada ponto do grid: `fit_jump_model`/`predict_jump_model` DIRETOS
  (mesmo caminho de código do harness real, não reimplementado), n_states=2,
  seed=0 -- mesmos hiperparâmetros fixos da calibração original. Medido:
  nº de estados sobreviventes no FIT (treino, via `fit.model.labels_` --
  atributo público confirmado por smoke test, `src/regime/jump_model.py`
  docstring item 3: rótulo DURO mesmo com `cont=True`) E no DECODE do
  fold de teste (o que importa de verdade -- é o que `anova_by_group`/
  `regime_persistence` do harness M4 usariam), duração mediana de
  segmento e `switch_rate` no teste.

**Critério (idêntico ao original, não automatizado -- B20):** o MAIOR
valor do grid que ainda produz >=2 estados GENUÍNOS na decodificação OOS
(teste) -- decisão do Manager sobre a tabela impressa abaixo, este
script só mede e reporta (via `structlog`, nunca `print()`, B28), nunca
escreve em `constants.yaml` sozinho."""

from __future__ import annotations

import numpy as np
import structlog

from src.analysis import m4_regime_comparison as m4
from src.data import lake
from src.data._constants import load_constant as load_data_constant
from src.regime.jump_model import fit_jump_model, predict_jump_model
from src.validation.regime_utility import segment_boundaries

logger = structlog.get_logger(__name__)

_SYMBOLS: tuple[str, ...] = ("ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
_RESOLUTION_ID: str = m4.RESOLUTION_ID  # "R1" -- ver docstring do módulo

# Mesmo grid ampliado já usado/validado na calibração original de BTC
# (constants.yaml::m4_jump_model_penalty.source) -- menu de medição, não
# valor calibrado (mesmo status de hmm_states_grid/_GRID_MULTIPLES do
# script irmão de BOCPD).
_GRID: tuple[float, ...] = (0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02)  # noqa: magic-number

_N_STATES: int = 2  # noqa: magic-number -- mesmo n_states=2 da calibração original
_SEED: int = 0

# Mesma janela/split da calibração original de BTC (50.000 barras, 40k
# treino + 10k teste) -- ver constants.yaml::m4_jump_model_penalty.source.
_WINDOW_BARS: int = 50_000  # noqa: magic-number
_TEST_BARS: int = 10_000  # noqa: magic-number
_TRAIN_BARS: int = _WINDOW_BARS - _TEST_BARS  # 40_000

_PERCENTILES: tuple[int, ...] = (5, 10, 25, 75, 90, 95, 99)


def _duration_stats(labels: np.ndarray) -> dict[str, float | int]:
    """Réplica a riqueza descritiva da calibração original de BTC
    (median/mean/std/percentis/min/max) a partir de `segment_boundaries`
    -- mesmo helper de `recalibrate_bocpd_hazard_lambda_pretest.py`
    (`tools/diagnostics/`), reimplementado aqui (não importado de lá, é
    um script irmão independente, não um módulo de biblioteca) pra manter
    os 2 scripts de calibração autocontidos."""
    starts, ends = segment_boundaries(labels)
    durations = (ends - starts).astype(np.float64)
    pcts = np.percentile(durations, _PERCENTILES)
    stats: dict[str, float | int] = {
        "n_segments": int(durations.shape[0]),
        "median_duration_bars": float(np.median(durations)),
        "mean_duration_bars": float(np.mean(durations)),
        "std_duration_bars": float(np.std(durations)),
        "min_duration_bars": float(np.min(durations)),
        "max_duration_bars": float(np.max(durations)),
    }
    stats.update(
        {f"p{p}_duration_bars": float(v) for p, v in zip(_PERCENTILES, pcts, strict=True)}
    )
    return stats


def _switch_rate(labels: np.ndarray) -> float:
    """Mesma fórmula de `regime_persistence` (`src.validation.regime_
    utility`) -- fração de barras onde o estado muda em relação à
    anterior. Reimplementada aqui (em vez de chamar `regime_persistence`
    direto) só porque este script já extrai `segment_boundaries`
    separadamente pra `_duration_stats` -- a fórmula é idêntica, não uma
    definição nova."""
    if labels.shape[0] < 2:
        return float("nan")
    n_switches = int(np.sum(labels[1:] != labels[:-1]))
    n_transitions = int(labels.shape[0]) - 1
    return float(n_switches) / float(n_transitions)  # noqa: unguarded-ratio -- guardado por shape[0]>=2 acima


def _load_last_window_obs(symbol: str) -> np.ndarray:
    """Últimas `_WINDOW_BARS` barras VÁLIDAS (pós-`_valid_start_idx`) do
    histórico causal completo do ativo -- mesma mecânica de carga/trim de
    `m4.compare_regime_candidates_for_symbol` (reusa os helpers PRIVADOS
    `m4._input_obs`/`m4._valid_start_idx`, mesma fórmula exata, não uma
    reimplementação)."""
    start = m4.SYMBOL_START_DATE[symbol]
    end = m4.END_DATE
    throttle = lake.DuckDBThrottle(
        memory_limit_gb=float(load_data_constant("m4_duckdb_memory_limit_gb")),
        threads=int(load_data_constant("m4_duckdb_threads")),
    )
    bars_df = lake.query_dollar_bars(
        symbol,
        start,
        end,
        resolution_id=_RESOLUTION_ID,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    log_return_1_full, obs_2d_full = m4._input_obs(bars_df)
    valid_start_idx = m4._valid_start_idx(log_return_1_full, obs_2d_full[:, 1])
    obs_2d = obs_2d_full[valid_start_idx:]
    n_valid = int(obs_2d.shape[0])
    logger.info(
        "calibrate_jump_model_penalty_per_asset.bars_loaded",
        symbol=symbol,
        resolution_id=_RESOLUTION_ID,
        n_bars_total=bars_df.height,
        n_bars_validas=n_valid,
    )
    if n_valid < _WINDOW_BARS:
        raise ValueError(
            f"calibrate_jump_model_penalty_per_asset: {symbol} só tem {n_valid} barras "
            f"válidas, esperado >= {_WINDOW_BARS} (mesma janela da calibração original de "
            "BTC) -- ajuste _WINDOW_BARS ou aguarde mais backfill antes de calibrar este ativo"
        )
    return obs_2d[-_WINDOW_BARS:]


def calibrate_for_symbol(symbol: str) -> None:
    logger.info(
        "calibrate_jump_model_penalty_per_asset.symbol_starting",
        symbol=symbol,
        resolution_id=_RESOLUTION_ID,
        grid=list(_GRID),
        n_states=_N_STATES,
        seed=_SEED,
        window_bars=_WINDOW_BARS,
        train_bars=_TRAIN_BARS,
        test_bars=_TEST_BARS,
    )
    obs_window = _load_last_window_obs(symbol)
    obs_test = obs_window[_TRAIN_BARS:]

    largest_valid_penalty: float | None = None
    for penalty in _GRID:
        fit = fit_jump_model(
            obs_window,
            n_states=_N_STATES,
            jump_penalty=penalty,
            train_end_idx=_TRAIN_BARS,
            seed=_SEED,
        )
        if fit is None:
            logger.warning(
                "calibrate_jump_model_penalty_per_asset.fit_failed",
                symbol=symbol,
                jump_penalty=penalty,
            )
            continue

        train_labels = np.asarray(fit.model.labels_, dtype=np.int64)
        n_states_train = int(np.unique(train_labels).shape[0])
        train_state_counts = np.bincount(train_labels).tolist()

        test_labels = predict_jump_model(fit, obs_test)
        n_states_test = int(np.unique(test_labels).shape[0])
        is_genuine_oos = n_states_test >= 2  # noqa: magic-number -- critério do experimento (AG-087), não um limiar de produção

        logger.info(
            "calibrate_jump_model_penalty_per_asset.grid_point",
            symbol=symbol,
            jump_penalty=penalty,
            n_states_train=n_states_train,
            train_state_counts=train_state_counts,
            n_states_test=n_states_test,
            is_genuine_oos=is_genuine_oos,
            switch_rate_test=_switch_rate(test_labels),
            **_duration_stats(test_labels),
        )
        if is_genuine_oos:
            largest_valid_penalty = penalty

    logger.info(
        "calibrate_jump_model_penalty_per_asset.symbol_done",
        symbol=symbol,
        maior_penalty_com_2_mais_estados_oos=largest_valid_penalty,
        criterio=(
            "mesmo da calibracao original (constants.yaml::m4_jump_model_penalty.source): "
            "o MAIOR valor do grid que ainda produz >=2 estados genuinos na decodificacao "
            "OOS -- decisao do Manager sobre a tabela acima, nao escrita em constants.yaml "
            "por este script (B20)"
        ),
    )


if __name__ == "__main__":
    for _symbol in _SYMBOLS:
        calibrate_for_symbol(_symbol)
