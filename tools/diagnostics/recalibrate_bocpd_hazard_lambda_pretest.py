"""Recalibração de `m4_bocpd_hazard_lambda` restrita a dado PRÉ-TESTE --
item 4 autorizado pelo Manager, 2026-08-20 (`docs/m4_regime_auditoria_
externa_2026-08-19_validacao_cruzada.md`, comentário 22 da seção 1.1 / V2
P5(i)(ii): "hazard_lambda foi calibrado 1x sobre o histórico completo
2019-2026 -- que inclui as janelas de teste -- problema real").

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python tools/diagnostics/recalibrate_bocpd_hazard_lambda_pretest.py

**Problema que motiva este script.** `config/constants.yaml::
m4_bocpd_hazard_lambda` (valor atual: 65,0) foi calibrado sobre BTCUSDT
2019-12-31/2026-08-07 -- o histórico COMPLETO, que inclui as 5 janelas
críticas de teste do M4 (LUNA/FTX/CRYPTO_WINTER/ETF_HALVING/RECENTE,
`src.analysis.m4_critical_windows.CRITICAL_WINDOWS`). Calibrar um
hiperparâmetro de candidato usando dado que inclui o próprio período que
depois vai avaliá-lo é uma forma de vazamento de informação -- não B02
clássico (não é quantil/z-score point-in-time dentro de uma feature),
mas a mesma classe de problema em espírito: o valor escolhido "conhece"
a estrutura de segmento (inclusive das 5 janelas) antes de qualquer
candidato ser julgado sobre elas.

**Corte pré-teste.** A janela crítica mais antiga (LUNA) começa em
`2021-04-01` (ver `m4_critical_windows.CRITICAL_WINDOWS`/docstring do
módulo, tabela de janelas). Todo dado ANTES disso nunca toca nenhuma das
5 janelas -- é o maior período pré-teste disponível para BTCUSDT
(`SYMBOL_START_DATE["BTCUSDT"]="2019-12-31"`), ~1 ano e 3 meses de dado
real.

**Metodologia -- mesmos 2 passos já documentados em `config/
constants.yaml::m4_bocpd_hazard_lambda.source` (2026-08-18), restrita a
[2019-12-31, 2021-04-01) em vez do histórico completo 2019-2026:**

  PASSO 1 -- âncora: duração mediana de segmento do BASELINE
  (`QuantileRegimeClassifier`) real, só no período pré-teste, R0
  (warmup) excluído (`regime_persistence`, `src.validation.
  regime_utility`).

  PASSO 2 -- grid de `hazard_lambda` = múltiplos dessa nova âncora (1x/
  5x/6.67x/10x -- MESMOS multiplicadores do grid original; 6.67x
  preserva a razão já validada no teste sintético de `bocpd.py`,
  `test_detecta_changepoint_unico_injetado_no_ponto_certo`), cada ponto
  rodando `run_bocpd` sobre `log_return_1` REAL do MESMO período
  pré-teste, medindo a distribuição de duração de segmento resultante
  (`bocpd_out.segment_id`, mesma metodologia de `regime_persistence`).

**O que este script NÃO faz.** Não escreve em `constants.yaml` sozinho
-- imprime a tabela completa (mediana/média/desvio/percentis por ponto
do grid) e devolve ao Manager a mesma decisão qualitativa já documentada
pro valor atual ("o ponto do grid que reproduz a ORDEM DE GRANDEZA real
do fenômeno, nem o valor bruto patológico nem um múltiplo grosseiro
demais") -- threshold escolhido a partir de medição, nunca escolhido
programaticamente depois de ver o resultado de um candidato (B20)."""

from __future__ import annotations

import numpy as np
import polars as pl
import structlog

from src.analysis import m4_regime_comparison as m4
from src.data import lake
from src.data._constants import load_constant as load_data_constant
from src.regime.bocpd import run_bocpd
from src.regime.build import build_regimes
from src.validation.regime_utility import regime_persistence, segment_boundaries

logger = structlog.get_logger(__name__)

_PRETEST_END: str = "2021-04-01"  # LUNA -- janela crítica mais antiga do M4
_SYMBOL: str = "BTCUSDT"
_BAR_SOURCE: str = "dollar_r1"
_RESOLUTION_ID: str = "R1"

# Mesmos multiplicadores do grid original (constants.yaml::
# m4_bocpd_hazard_lambda.source) -- 6.67x = 20/3, razão já validada no
# teste sintético de bocpd.py. Menu de comparação exploratório, não valor
# calibrado -- mesmo status de hmm_states_grid/_TRANSITION_FAILURE_
# HORIZONS_BARS (m4_critical_windows.py), não pertence a constants.yaml.
_GRID_MULTIPLES: dict[str, float] = {"1x": 1.0, "5x": 5.0, "6.67x": 20.0 / 3.0, "10x": 10.0}  # noqa: magic-number,E501

# Grid fino adicional, 2026-08-20 -- achado real da 1ª rodada (dado
# pré-teste, período diferente do histórico completo usado na
# calibração original): 5x undershoot (median=4,0, âncora=13,0) e 6.67x
# overshoot (median=59,0) -- o ponto que reproduziria a âncora fica
# ENTRE os 2 multiplicadores originais, diferente do histórico completo
# (onde 5x já batia quase exato). Preenche o intervalo, não substitui o
# grid original -- mesma disciplina de menu exploratório, não valor
# calibrado.
_FINE_GRID_MULTIPLES: dict[str, float] = {  # noqa: magic-number
    "5.3x": 5.3,
    "5.6x": 5.6,
    "5.9x": 5.9,
    "6.2x": 6.2,
    "6.4x": 6.4,
}

_PERCENTILES: tuple[int, ...] = (5, 10, 25, 75, 90, 95, 99)


def _duration_stats(group_labels: np.ndarray) -> dict[str, float | int]:
    """Réplica a riqueza descritiva da calibração original (median/mean/
    std/percentis/min/max), a partir de `segment_boundaries` -- não só o
    `median_duration_bars` que `regime_persistence` expõe."""
    starts, ends = segment_boundaries(group_labels)
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
    stats.update({f"p{p}_duration_bars": float(v) for p, v in zip(_PERCENTILES, pcts, strict=True)})
    return stats


def step1_baseline_median_duration_pretest() -> float:
    start = m4.SYMBOL_START_DATE[_SYMBOL]
    logger.info(
        "recalibrate_bocpd_hazard_lambda_pretest.step1_starting",
        start=start,
        end=_PRETEST_END,
        symbol=_SYMBOL,
        bar_source=_BAR_SOURCE,
    )

    regime_df = build_regimes(_SYMBOL, start, _PRETEST_END, bar_source=_BAR_SOURCE)
    physical = regime_df["regime"].to_physical().cast(pl.Int64).to_numpy()
    n_total = physical.shape[0]
    non_r0 = physical[physical != m4._BASELINE_R0_PHYSICAL_ID]
    logger.info(
        "recalibrate_bocpd_hazard_lambda_pretest.step1_warmup_trimmed",
        n_bars_total=n_total,
        n_bars_pos_warmup=int(non_r0.shape[0]),
    )

    metrics = regime_persistence(non_r0)
    logger.info(
        "recalibrate_bocpd_hazard_lambda_pretest.step1_baseline_stats",
        switch_rate=metrics.switch_rate,
        **_duration_stats(non_r0),
    )
    logger.info(
        "recalibrate_bocpd_hazard_lambda_pretest.step1_anchor",
        median_duration_bars_pretest=metrics.median_duration_bars,
    )
    return metrics.median_duration_bars


def step2_grid_search_pretest(anchor_median: float) -> None:
    start = m4.SYMBOL_START_DATE[_SYMBOL]
    logger.info(
        "recalibrate_bocpd_hazard_lambda_pretest.step2_starting",
        start=start,
        end=_PRETEST_END,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        anchor_median_duration_bars=anchor_median,
    )

    throttle = lake.DuckDBThrottle(
        memory_limit_gb=float(load_data_constant("m4_duckdb_memory_limit_gb")),
        threads=int(load_data_constant("m4_duckdb_threads")),
    )
    bars_df = lake.query_dollar_bars(
        _SYMBOL,
        start,
        _PRETEST_END,
        resolution_id=_RESOLUTION_ID,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    log_return_1_full, obs_2d_full = m4._input_obs(bars_df)
    valid_start_idx = m4._valid_start_idx(log_return_1_full, obs_2d_full[:, 1])
    log_return_1 = log_return_1_full[valid_start_idx:]
    logger.info(
        "recalibrate_bocpd_hazard_lambda_pretest.step2_valid_bars",
        n_bars_validas=int(log_return_1.shape[0]),
        valid_start_idx=valid_start_idx,
    )

    all_multiples = {**_GRID_MULTIPLES, **_FINE_GRID_MULTIPLES}
    for label, mult in sorted(all_multiples.items(), key=lambda kv: kv[1]):
        hazard_lambda = anchor_median * mult
        bocpd_out = run_bocpd(log_return_1, hazard_lambda=hazard_lambda)
        logger.info(
            "recalibrate_bocpd_hazard_lambda_pretest.step2_grid_point",
            multiple=label,
            hazard_lambda=hazard_lambda,
            **_duration_stats(bocpd_out.segment_id),
        )

    logger.info(
        "recalibrate_bocpd_hazard_lambda_pretest.step2_done",
        criterio_de_escolha=(
            "mesmo do valor atual (constants.yaml::m4_bocpd_hazard_lambda.source): "
            "o ponto do grid cujo median_duration_bars resultante melhor reproduz a "
            "ordem de grandeza da âncora do PASSO 1 -- nem o valor bruto (tende a "
            "ficar patológico, prior dominando e resetando por ruído barra-a-barra) "
            "nem um múltiplo grosseiro demais (duração muito acima do fenômeno "
            "real). Decisão do Manager sobre os grid_point acima -- não "
            "automatizada aqui (B20, threshold nunca escolhido programaticamente "
            "depois de ver o resultado)."
        ),
    )


if __name__ == "__main__":
    anchor = step1_baseline_median_duration_pretest()
    step2_grid_search_pretest(anchor)
