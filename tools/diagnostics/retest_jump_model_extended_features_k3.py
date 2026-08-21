"""Reteste do Jump Model com espaço de observação ESTENDIDO + `n_states=3`
-- `AG-119` (`audit/architecture_gaps_log.yaml`), 2026-08-20.

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python -m tools.diagnostics.retest_jump_model_extended_features_k3

**Problema que motiva este script.** `AG-117` mediu que SOLUSDT/BNBUSDT/
XRPUSDT não produzem 2 estados genuínos OOS em NENHUM ponto do grid de λ
testado, e que recalibrar λ pra ETHUSDT piora/empata a saturação nas
janelas críticas reais. Pesquisa de literatura dedicada (2º adendo de
`AG-117`, mesma sessão) achou que esse achado é CONFUNDIDO -- nosso
`obs_2d = [log_return_1, realized_vol_short]` (2 features cruas, 1
horizonte) e `jump_n_states=2` fixo divergem, SIMULTANEAMENTE, de toda
aplicação bem-sucedida publicada de Jump Model (Nystrup, Shu/Kolm/
Mulvey, Cortese/Kolm/Lindström -- o único paper cripto-específico, que
valida BTC/ETH/XRP/LTC/BCH e acha K=3 melhor que K=2 pra cripto
especificamente). Este script isola essas 2 variáveis (espaço de
features, `n_states`) mantendo tudo o resto idêntico à calibração
original (`tools/diagnostics/calibrate_jump_model_penalty_per_asset.py`)
-- mesmo grid de λ, mesma janela/split, mesmo critério de leitura.

**O que muda vs. `calibrate_jump_model_penalty_per_asset.py`:**

1. **Espaço de observação -- 4 features, não 2.** `[log_return_1,
   realized_vol_short, realized_vol_long, downside_deviation]`.
   `realized_vol_long` reusa `feature_c06_vol_ratio_long_window`
   (constante já em produção no Feature Engine, `src/features/build.py`
   -- não é uma janela nova inventada). `downside_deviation`
   (`src/features/support.py`, novo, `AG-119`) é a métrica que a
   literatura de Jump Model usa e que não tinha equivalente no repo --
   mesma janela `feature_c06_vol_ratio_short_window` de
   `realized_vol_short`, pra não introduzir uma 2ª janela livre sem
   justificativa. **Deliberadamente SEM normalização/z-score das 4
   colunas** -- isola o efeito de adicionar features + testar K=3, sem
   confundir com uma mudança de escala ao mesmo tempo (se este reteste
   ainda falhar, normalização é o próximo candidato óbvio, não testado
   aqui).
2. **`n_states` testado em {2, 3}**, não só 2 -- grid de λ roda pra
   CADA valor de `n_states`, tabela completa impressa pros 2.
3. **Tudo o resto idêntico**: mesmo grid de λ (`_GRID`), mesma janela
   (50.000 barras, 40k treino/10k teste), mesmo critério de leitura
   (maior λ com >=2 estados genuínos OOS -- adaptado pra 3 quando
   `n_states=3`, ver `_min_states_for_genuine`), mesmos 3 ativos
   (SOLUSDT/BNBUSDT/XRPUSDT -- ETHUSDT fica de fora aqui porque já tem
   um λ genuíno conhecido no espaço de features antigo; se este reteste
   mudar o quadro pros 3 outros, ETHUSDT entra numa rodada separada).

**O que este script NÃO faz.** Não escreve em `constants.yaml` (B20).
Não decide se o critério de seleção de λ em si deveria mudar (item (c)
do `AG-119`, "se (a)/(b) não resolverem") -- isso é um script separado,
só faz sentido depois de ver o resultado deste. É busca de
hiperparâmetro classe B -- se os números aqui mudarem a decisão de
excluir Jump Model, incrementar `N_lifetime` fica pendente de decisão do
Manager (mesma disciplina do script irmão)."""

from __future__ import annotations

import numpy as np
import structlog

from src.analysis import m4_regime_comparison as m4
from src.data import lake
from src.data._constants import load_constant as load_data_constant
from src.features import support as features_support
from src.features._constants import load_constant as load_feature_constant
from src.regime.jump_model import fit_jump_model, predict_jump_model
from src.validation.regime_utility import segment_boundaries

logger = structlog.get_logger(__name__)

# AG-119 -- só os 3 ativos sem NENHUM λ genuíno no espaço de features
# antigo (AG-117). ETHUSDT já tem um λ que funciona no espaço antigo;
# fica fora desta rodada, ver docstring do módulo.
_SYMBOLS: tuple[str, ...] = ("SOLUSDT", "BNBUSDT", "XRPUSDT")
_RESOLUTION_ID: str = m4.RESOLUTION_ID  # "R1"

_GRID: tuple[float, ...] = (0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02)  # noqa: magic-number -- mesmo grid do script original, ver docstring
_N_STATES_GRID: tuple[int, ...] = (2, 3)  # noqa: magic-number -- AG-119, item (b)
_SEED: int = 0

_WINDOW_BARS: int = 50_000  # noqa: magic-number -- mesma janela do script original
_TEST_BARS: int = 10_000  # noqa: magic-number
_TRAIN_BARS: int = _WINDOW_BARS - _TEST_BARS

_PERCENTILES: tuple[int, ...] = (5, 10, 25, 75, 90, 95, 99)


def _duration_stats(labels: np.ndarray) -> dict[str, float | int]:
    """Idêntica ao helper de `calibrate_jump_model_penalty_per_asset.py`
    -- reimplementada aqui (script irmão autocontido, mesma disciplina)."""
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
    if labels.shape[0] < 2:
        return float("nan")
    n_switches = int(np.sum(labels[1:] != labels[:-1]))
    n_transitions = int(labels.shape[0]) - 1
    return float(n_switches) / float(n_transitions)  # noqa: unguarded-ratio -- guardado por shape[0]>=2 acima


def _load_last_window_obs_extended(symbol: str) -> np.ndarray:
    """4 colunas -- [log_return_1, realized_vol_short, realized_vol_long,
    downside_deviation]. Reusa `m4._input_obs`/`m4._valid_start_idx`
    (mesmo corte de warmup causal do resto do M4) só pra obter
    `log_return_1`/`realized_vol_short` já corretos -- as 2 colunas
    novas são computadas aqui, direto sobre o `log_return_1` já
    recortado, mesma disciplina de causalidade (janela rolante fixa,
    B02 não se aplica -- ver docstrings de `realized_vol`/
    `downside_deviation`)."""
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
    log_return_1 = log_return_1_full[valid_start_idx:]
    realized_vol_short = obs_2d_full[valid_start_idx:, 1]

    short_window = int(load_feature_constant("feature_c06_vol_ratio_short_window"))
    long_window = int(load_feature_constant("feature_c06_vol_ratio_long_window"))
    realized_vol_long_full = features_support.realized_vol(log_return_1_full, long_window)
    realized_vol_long = realized_vol_long_full[valid_start_idx:]
    downside_dev_full = features_support.downside_deviation(log_return_1_full, short_window)
    downside_dev = downside_dev_full[valid_start_idx:]

    obs_4d = np.column_stack(
        [log_return_1, realized_vol_short, realized_vol_long, downside_dev]
    ).astype(np.float64)

    # realized_vol_long/downside_deviation têm warmup PRÓPRIO (long_window
    # pode ser > short_window) -- corte adicional pra garantir as 4
    # colunas finitas desde a 1ª linha, mesma disciplina de
    # _valid_start_idx (nunca propagar NaN de warmup pro fit).
    valid_extra = np.all(np.isfinite(obs_4d), axis=1)
    if not np.any(valid_extra):
        raise ValueError(
            f"retest_jump_model_extended_features_k3: {symbol} sem nenhuma barra com as 4 "
            "colunas finitas -- long_window/downside_deviation maiores que o histórico "
            "disponível?"
        )
    extra_start_idx = int(np.argmax(valid_extra))
    obs_4d = obs_4d[extra_start_idx:]

    n_valid = int(obs_4d.shape[0])
    logger.info(
        "retest_jump_model_extended_features_k3.bars_loaded",
        symbol=symbol,
        resolution_id=_RESOLUTION_ID,
        n_bars_total=bars_df.height,
        n_bars_validas=n_valid,
        extra_warmup_dropped=extra_start_idx,
        short_window=short_window,
        long_window=long_window,
    )
    if n_valid < _WINDOW_BARS:
        raise ValueError(
            f"retest_jump_model_extended_features_k3: {symbol} só tem {n_valid} barras "
            f"válidas (4 colunas), esperado >= {_WINDOW_BARS}"
        )
    return obs_4d[-_WINDOW_BARS:]


def calibrate_for_symbol(symbol: str) -> None:
    obs_window = _load_last_window_obs_extended(symbol)
    obs_test = obs_window[_TRAIN_BARS:]

    for n_states in _N_STATES_GRID:
        logger.info(
            "retest_jump_model_extended_features_k3.symbol_n_states_starting",
            symbol=symbol,
            resolution_id=_RESOLUTION_ID,
            n_states=n_states,
            grid=list(_GRID),
            seed=_SEED,
            n_features=obs_window.shape[1],
        )
        largest_valid_penalty: float | None = None
        for penalty in _GRID:
            fit = fit_jump_model(
                obs_window,
                n_states=n_states,
                jump_penalty=penalty,
                train_end_idx=_TRAIN_BARS,
                seed=_SEED,
            )
            if fit is None:
                logger.warning(
                    "retest_jump_model_extended_features_k3.fit_failed",
                    symbol=symbol,
                    n_states=n_states,
                    jump_penalty=penalty,
                )
                continue

            train_labels = np.asarray(fit.model.labels_, dtype=np.int64)
            n_states_train = int(np.unique(train_labels).shape[0])
            train_state_counts = np.bincount(train_labels).tolist()

            test_labels = predict_jump_model(fit, obs_test)
            n_states_test = int(np.unique(test_labels).shape[0])
            is_genuine_oos = n_states_test >= 2  # noqa: magic-number -- mesmo critério do script original (AG-087): pelo menos 2 estados sobrevivem, mesmo quando n_states pedido é 3

            logger.info(
                "retest_jump_model_extended_features_k3.grid_point",
                symbol=symbol,
                n_states=n_states,
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
            "retest_jump_model_extended_features_k3.symbol_n_states_done",
            symbol=symbol,
            n_states=n_states,
            maior_penalty_com_2_mais_estados_oos=largest_valid_penalty,
        )


if __name__ == "__main__":
    for _symbol in _SYMBOLS:
        calibrate_for_symbol(_symbol)
