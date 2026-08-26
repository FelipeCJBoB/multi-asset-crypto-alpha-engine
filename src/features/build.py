"""Núcleo de orquestração do Feature Engine T1 (§2 do PRD, Sprint 4).

Princípio 3 do §2.0 ("caminho único... não existem duas implementações") é
satisfeito de um jeito específico aqui: `compute_t1_features` é uma função
PURA (sem IO), determinística, estritamente causal por construção — toda
janela (rolante ou expansiva) só olha para `<= t` ou `< t`, nunca para o
futuro. Isso significa que "processar em streaming, barra a barra" e
"processar em lote" não precisam de duas implementações: bastam chamadas
sucessivas da MESMA função sobre prefixos crescentes de `bars_15m`. O
teste de paridade (`tests/parity/test_features_parity.py`) explora
exatamente essa propriedade — ver o motivo detalhado lá.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final

import numpy as np
import polars as pl
import structlog

from src.data.build_dollar_bars import CALIBRATION_TF_BY_RESOLUTION
from src.data.resample import step_ms

from . import _sources, support
from ._constants import load_constant
from .groups import group_a, group_b, group_c, group_d, group_e, group_k
from .registry import feature_lookback_bars
from .support import FloatArray

logger = structlog.get_logger(__name__)

#: AG-032 (2026-08-23, decisão do Manager): `C07_vol_pctile_expanding`/
#: `D03f_volume_z_expanding`/`E02f_funding_z_expanding` SAÍRAM do conjunto
#: ativo -- têm `lookback_bars: expanding` no registry (sem valor finito
#: honesto pra proteger via purge de CPCV, `ExpandingFeatureLookbackError`,
#: ver `assert_no_expanding_lookback_in_active_set` abaixo). As 3 CONTINUAM
#: sendo calculadas por `compute_t1_features` (núcleo não filtra por esta
#: tupla) e continuam disponíveis pra quem precisar delas fora do papel de
#: feature de treino do Alpha -- `C07_vol_pctile_expanding` é insumo real
#: do Regime Engine (`src.regime.classifier.QuantileRegimeClassifier`,
#: leitura direta da coluna, independente desta tupla). Consumidor de
#: análise pós-hoc que precise ler as 3 sobre `ModelingFrame` real usa
#: `build_modeling_frame(..., extra_feature_ids=(...))`
#: (`src.models.dataset`), nunca reintroduzindo-as aqui.
T1_FEATURE_IDS: tuple[str, ...] = (
    "A05_ret_vol_norm_4",
    "A13_dist_ema48_atr",
    "B01_rsi_14",
    "E27f_cost_atr_ratio",
    "C06_vol_ratio_12_96",
    "D06f_taker_imbalance_z_48",
    "E10f_oi_change_z_48",
)

# T2 calculadas neste Sprint por serem insumo de outra camada (Regime
# Engine, §4.2, Sprint 5) ou insumo direto de features T1 acima — não
# entram no vetor de treino do Alpha V1, mas têm entrada de registry.
SUPPORT_FEATURE_IDS: tuple[str, ...] = (
    "C01_atr_20",
    "C02_atr_20_pct",
    "B07_efficiency_ratio_48",
    # Lote A da liberação de features (H5, 2026-08-24) -- 47 T2, nenhuma
    # promovida a T1 por esta implementação (§0.2 R4/§2.13). Entrar aqui
    # (não só em ALL_OUTPUT_COLUMNS) é o que dá a cada uma cobertura
    # AUTOMÁTICA do teste de paridade lote<->streaming global (tests/
    # parity/test_features_parity.py) -- é a mesma razão de B07/C01/C02
    # estarem nesta tupla acima.
    "A01_log_return_1",
    "A02_log_return_2",
    "A03_log_return_4",
    "A04_log_return_12",
    "A06_ret_vol_norm_12",
    "A07_body_ratio",
    "A08_upper_wick_ratio",
    "A09_lower_wick_ratio",
    "A10_close_location",
    "A11_true_range_pct",
    "A12_gap_pct",
    "A14_dist_ema12_atr",
    "B02_rsi_48",
    "B03_roc_12",
    "B04_macd_hist_norm",
    "B05_ema_slope_24",
    "B06_momentum_accel",
    "B08_efficiency_ratio_16",
    "B09_zscore_close_48",
    "B11_bb_position_20",
    "C03_realized_vol_48",
    "C04_parkinson_vol_48",
    "C05_garman_klass_48",
    "C09_range_pctile_expanding",
    "C10_vol_expansion_flag",
    "C11_vol_compression_flag",
    "C12_vol_of_vol_48",
    "D01f_volume_z_96",
    "D02f_rel_volume_48",
    "D04f_volume_accel",
    "D05f_taker_buy_ratio",
    "D08f_trade_count_z_48",
    "D09f_avg_trade_size_z",
    "E01f_funding_last",
    "E05f_time_to_funding_h",
    "E09f_oi_contracts",
    "E11f_oi_change_1d",
    "E12f_price_oi_divergence",
    "K01_hour_sin",
    "K01_hour_cos",
    "K02_dow_sin",
    "K02_dow_cos",
    "K03_is_weekend",
    "K04_session_asia",
    "K04_session_europe",
    "K04_session_us",
    "K08_days_since_halving",
    # Lote B da liberação de features (H5, 2026-08-24) -- 6 T2, cada uma
    # precisando de primitiva nova (support.rolling_correlation/rolling_
    # percentile_rank_strict, min/max rolante, reset por dia, soma por
    # evento) ou fonte nova (D07f, klines_1m bruto) -- nenhuma promovida
    # a T1.
    "A15_dist_vwap_d_atr",
    "B10_stoch_k_14",
    "C08_vol_pctile_rolling_1y",
    "D07f_taker_imbalance_1m_agg",
    "D10f_vol_price_divergence",
    "E03f_funding_cum_3d",
    # Lote C da liberação de features (H5, 2026-08-24) -- 6 T2, extensão
    # fina de _sources.py (mesmo arquivo `metrics` de E08f/E09f/E10f,
    # colunas antes não lidas) -- zero primitiva nova.
    "E08f_oi_notional",
    "E14f_toptrader_ls_ratio",
    "E15f_toptrader_ls_z",
    "E16f_global_ls_ratio",
    "E17f_retail_vs_top_spread",
    "E18f_taker_ls_vol_ratio",
)

ALL_OUTPUT_COLUMNS: tuple[str, ...] = (
    "open_time",
    "close_time",
    *T1_FEATURE_IDS,
    *SUPPORT_FEATURE_IDS,
)

_NON_FEATURE_COLUMNS = frozenset({"open_time", "close_time"})


def _to_numpy(series: pl.Series | FloatArray) -> FloatArray:
    if isinstance(series, pl.Series):
        return series.cast(pl.Float64).to_numpy()
    return series


#: `bar_source` (`_sources.load_bars`) -> `resolution_id` (`CALIBRATION_TF_
#: BY_RESOLUTION`) -- só as 3 variantes dollar-bar precisam de tradução;
#: `"time_15m"` é tratado à parte (ver `_clock_reference_bar_duration_ms`).
_RESOLUTION_ID_BY_BAR_SOURCE: dict[str, str] = {
    "dollar_r1": "R1",
    "dollar_r2": "R2",
    "dollar_r3": "R3",
}


def _clock_reference_bar_duration_ms(bar_source: str) -> int:
    """Duração de referência usada SÓ pra escalar `feature_a13_ema_window`
    (`scaling_invariant: clock`, `AG-043` F3) — as outras 9 janelas de
    `FeatureWindows` são `bar_count`/normalização e ficam intocadas sob
    qualquer `bar_source` (decisão deliberada e específica por feature,
    `config/constants.yaml`, não generalizável).

    Usa `CALIBRATION_TF_BY_RESOLUTION` — o alvo FIXO de calibração
    (`R1->"15m"`, já importado por 10+ módulos do repo), NUNCA uma duração
    MEDIDA. `AG-043` já registra que um mecanismo automático dirigido por
    duração medida (F2) foi avaliado e REJEITADO pelo Manager ("reintroduz
    a não-estacionariedade do Bloqueador 2 dentro da própria feature") —
    usar uma constante nova MEASURED aqui repetiria esse erro. `bar_source
    ="time_15m"` retorna `step_ms("15m")` (ratio=1 em `_scale_clock_
    window_bars`) — bit-exato, nenhum caller existente muda de
    comportamento."""
    if bar_source == "time_15m":
        return step_ms("15m")
    resolution_id = _RESOLUTION_ID_BY_BAR_SOURCE.get(bar_source)
    if resolution_id is None:
        raise ValueError(
            f"bar_source={bar_source!r} sem duração de referência para escalar "
            f"janelas clock -- esperado 'time_15m' ou um de "
            f"{sorted(_RESOLUTION_ID_BY_BAR_SOURCE)}"
        )
    return step_ms(CALIBRATION_TF_BY_RESOLUTION[resolution_id])


def _scale_clock_window_bars(window_bars_at_15m: int, bar_duration_ms: int) -> int:
    """`96@15m -> 48@30m -> 24@1h` — fórmula já especificada pelo Manager
    no comentário de `feature_a13_ema_window` (`config/constants.yaml`,
    2026-08-16), generalizada pra qualquer duração de referência (`bar_
    duration_ms`, de `_clock_reference_bar_duration_ms`). `bar_duration_ms
    = step_ms('15m')` -> ratio=1, bit-exato. Piso de 1 barra."""
    ratio = step_ms("15m") / bar_duration_ms  # noqa: unguarded-ratio -- bar_duration_ms vem só de step_ms(tf real) (_clock_reference_bar_duration_ms), sempre > 0 por construção
    return max(1, round(window_bars_at_15m * ratio))


@dataclass(frozen=True, slots=True)
class FeatureWindows:
    """Todas as janelas de lookback de `constants.yaml` lidas uma única vez
    — evita 10 chamadas repetidas a `load_constant` espalhadas pelo corpo
    de `compute_t1_features`.

    `ema_window` é o ÚNICO campo `scaling_invariant: clock` do vetor T1
    (`feature_a13_ema_window`, `AG-043` F3 — A13 é deliberadamente
    ancorado ao horizonte real do Label Engine (`time_stop_ms`), não é um
    indicador técnico genérico; ver `constants.yaml` pra justificativa
    completa e por que os outros 9 campos NÃO recebem esse tratamento).
    Todos os outros 9 são `bar_count`/normalização, fixos entre grades por
    decisão própria e separada de cada um (RSI/B07/vol_ratio/C07/D06f/E10f
    já foram reclassificados de `clock` para `bar_count` em 2026-08-16 com
    justificativa individual — não são omissão)."""

    atr_window: int
    ema_window: int
    rsi_window: int
    ret_lookback: int
    vol_ratio_short_window: int
    vol_ratio_long_window: int
    c07_window: int
    d06f_window: int
    e10f_window: int
    b07_window: int
    maker_fee: float
    taker_fee: float
    min_warmup_bars: int
    min_common_history_bars: int | None = None

    @classmethod
    def from_constants(cls, *, bar_source: str = "time_15m") -> FeatureWindows:
        """`bar_source` (2026-08-23, fecha o débito de `AG-043` sobre
        `feature_a13_ema_window`) escala só `ema_window` — via `_scale_
        clock_window_bars`/`_clock_reference_bar_duration_ms`, nunca uma
        medição nova (ver docstring de `_clock_reference_bar_duration_
        ms` sobre por que F2 foi rejeitado). Default `"time_15m"` produz
        `ema_window=48` bit-exato, idêntico a todo caller anterior a esta
        mudança."""
        ema_window_at_15m = int(load_constant("feature_a13_ema_window"))
        bar_duration_ms = _clock_reference_bar_duration_ms(bar_source)
        return cls(
            atr_window=int(load_constant("atr_window")),
            ema_window=_scale_clock_window_bars(ema_window_at_15m, bar_duration_ms),
            rsi_window=int(load_constant("feature_b01_rsi_window")),
            ret_lookback=int(load_constant("feature_a05_ret_lookback_bars")),
            vol_ratio_short_window=int(load_constant("feature_c06_vol_ratio_short_window")),
            vol_ratio_long_window=int(load_constant("feature_c06_vol_ratio_long_window")),
            c07_window=int(load_constant("feature_c07_vol_pctile_window")),
            d06f_window=int(load_constant("feature_d06f_taker_imbalance_window")),
            e10f_window=int(load_constant("feature_e10f_oi_change_window")),
            b07_window=int(load_constant("feature_b07_efficiency_ratio_window")),
            maker_fee=float(load_constant("maker_fee")),
            taker_fee=float(load_constant("taker_fee")),
            min_warmup_bars=int(load_constant("min_warmup_bars")),
            min_common_history_bars=int(load_constant("min_common_history_bars_15m")),
        )


@dataclass(frozen=True, slots=True)
class LoteAWindows:
    """Janelas/parâmetros das 47 features T2 do Lote A da liberação de
    features (H5, 2026-08-24) — carregadas uma única vez, mesmo padrão de
    `FeatureWindows`. Deliberadamente uma dataclass SEPARADA (não um
    apêndice de `FeatureWindows`): `FeatureWindows` é o vetor T1 ATIVO
    (histórico, Sprint 4, consumido pelo Alpha hoje); estas 47 são T2
    (nenhuma promovida a T1 por esta implementação, §0.2 R4/§2.13) —
    misturar as duas infla `FeatureWindows` sem necessidade e confunde o
    que é de fato consumido pelo Alpha hoje vs. o que é candidato T2
    disponível para ablação futura."""

    a01_log_return_lag: int
    a02_log_return_lag: int
    a03_log_return_lag: int
    a04_log_return_lag: int
    a05_vol_norm_divisor: float
    a06_ret_lookback_bars: int
    a14_ema_window: int
    b02_rsi_window: int
    b03_roc_lookback_bars: int
    b04_macd_fast_window: int
    b04_macd_slow_window: int
    b04_macd_signal_window: int
    b05_ema_window: int
    b05_slope_lag_bars: int
    b06_momentum_lookback_bars: int
    b08_efficiency_ratio_window: int
    b09_zscore_close_window: int
    b11_bb_window: int
    b11_bb_std_multiplier: float
    c03_realized_vol_window: int
    c04_parkinson_vol_window: int
    c05_garman_klass_window: int
    c10_vol_expansion_threshold: float
    c11_vol_compression_threshold: float
    c12_vol_of_vol_inner_window: int
    c12_vol_of_vol_outer_window: int
    d01f_volume_z_window: int
    d02f_rel_volume_window: int
    d04f_rel_volume_window: int
    d08f_trade_count_z_window: int
    d09f_avg_trade_size_z_window: int
    e05f_funding_interval_hours: int
    e11f_oi_change_lag_bars: int
    e12f_oi_change_lag_bars: int
    k04_asia_start_hour: float
    k04_asia_end_hour: float
    k04_europe_start_hour: float
    k04_europe_end_hour: float
    k04_us_start_hour: float
    k04_us_end_hour: float
    k08_halving_dates_ms: tuple[int, ...]

    @classmethod
    def from_constants(cls) -> LoteAWindows:
        halving_date_names = (
            "feature_k08_halving_1_date_utc",
            "feature_k08_halving_2_date_utc",
            "feature_k08_halving_3_date_utc",
            "feature_k08_halving_4_date_utc",
        )
        ms_per_second = 1000.0  # noqa: magic-number -- conversão de unidade (s -> ms), não hiperparâmetro de negócio
        halving_dates_ms = tuple(
            int(
                datetime.strptime(load_constant(name), "%Y-%m-%d")
                .replace(tzinfo=UTC)
                .timestamp()
                * ms_per_second
            )
            for name in halving_date_names
        )
        return cls(
            a01_log_return_lag=int(load_constant("feature_a01_log_return_lag")),
            a02_log_return_lag=int(load_constant("feature_a02_log_return_lag")),
            a03_log_return_lag=int(load_constant("feature_a03_log_return_lag")),
            a04_log_return_lag=int(load_constant("feature_a04_log_return_lag")),
            a05_vol_norm_divisor=float(load_constant("feature_a05_vol_norm_divisor")),
            a06_ret_lookback_bars=int(load_constant("feature_a06_ret_lookback_bars")),
            a14_ema_window=int(load_constant("feature_a14_ema_window")),
            b02_rsi_window=int(load_constant("feature_b02_rsi_window")),
            b03_roc_lookback_bars=int(load_constant("feature_b03_roc_lookback_bars")),
            b04_macd_fast_window=int(load_constant("feature_b04_macd_fast_window")),
            b04_macd_slow_window=int(load_constant("feature_b04_macd_slow_window")),
            b04_macd_signal_window=int(load_constant("feature_b04_macd_signal_window")),
            b05_ema_window=int(load_constant("feature_b05_ema_window")),
            b05_slope_lag_bars=int(load_constant("feature_b05_slope_lag_bars")),
            b06_momentum_lookback_bars=int(load_constant("feature_b06_momentum_lookback_bars")),
            b08_efficiency_ratio_window=int(load_constant("feature_b08_efficiency_ratio_window")),
            b09_zscore_close_window=int(load_constant("feature_b09_zscore_close_window")),
            b11_bb_window=int(load_constant("feature_b11_bb_window")),
            b11_bb_std_multiplier=float(load_constant("feature_b11_bb_std_multiplier")),
            c03_realized_vol_window=int(load_constant("feature_c03_realized_vol_window")),
            c04_parkinson_vol_window=int(load_constant("feature_c04_parkinson_vol_window")),
            c05_garman_klass_window=int(load_constant("feature_c05_garman_klass_window")),
            c10_vol_expansion_threshold=float(load_constant("feature_c10_vol_expansion_threshold")),
            c11_vol_compression_threshold=float(
                load_constant("feature_c11_vol_compression_threshold")
            ),
            c12_vol_of_vol_inner_window=int(load_constant("feature_c12_vol_of_vol_inner_window")),
            c12_vol_of_vol_outer_window=int(load_constant("feature_c12_vol_of_vol_outer_window")),
            d01f_volume_z_window=int(load_constant("feature_d01f_volume_z_window")),
            d02f_rel_volume_window=int(load_constant("feature_d02f_rel_volume_window")),
            d04f_rel_volume_window=int(load_constant("feature_d04f_rel_volume_window")),
            d08f_trade_count_z_window=int(load_constant("feature_d08f_trade_count_z_window")),
            d09f_avg_trade_size_z_window=int(
                load_constant("feature_d09f_avg_trade_size_z_window")
            ),
            e05f_funding_interval_hours=int(load_constant("feature_e05f_funding_interval_hours")),
            e11f_oi_change_lag_bars=int(load_constant("feature_e11f_oi_change_lag_bars")),
            e12f_oi_change_lag_bars=int(load_constant("feature_e12f_oi_change_lag_bars")),
            k04_asia_start_hour=float(load_constant("feature_k04_asia_start_hour")),
            k04_asia_end_hour=float(load_constant("feature_k04_asia_end_hour")),
            k04_europe_start_hour=float(load_constant("feature_k04_europe_start_hour")),
            k04_europe_end_hour=float(load_constant("feature_k04_europe_end_hour")),
            k04_us_start_hour=float(load_constant("feature_k04_us_start_hour")),
            k04_us_end_hour=float(load_constant("feature_k04_us_end_hour")),
            k08_halving_dates_ms=halving_dates_ms,
        )


@dataclass(frozen=True, slots=True)
class LoteBWindows:
    """Janelas/parâmetros das 6 features T2 do Lote B da liberação de
    features (H5, 2026-08-24) — mesmo padrão de `LoteAWindows`/
    `FeatureWindows`, dataclass SEPARADA (motivo idêntico ao de
    `LoteAWindows`). A15/D07f não têm campo aqui: A15 (VWAP) não usa
    janela, só reset por fronteira de dia; D07f usa `step_ms("15m")`
    (infraestrutura de grid, não hiperparâmetro de negócio — mesmo
    tratamento que `step_ms(...)` já recebe em outros pontos de
    `build.py`), não uma constante de `constants.yaml`."""

    b10_stoch_window: int
    c08_inner_window: int
    c08_outer_window: int
    d10f_window: int
    e03f_n_events: int

    @classmethod
    def from_constants(cls) -> LoteBWindows:
        return cls(
            b10_stoch_window=int(load_constant("feature_b10_stoch_window")),
            c08_inner_window=int(load_constant("feature_c08_vol_pctile_inner_window")),
            c08_outer_window=int(load_constant("feature_c08_vol_pctile_outer_window")),
            d10f_window=int(load_constant("feature_d10f_window")),
            e03f_n_events=int(load_constant("feature_e03f_funding_cum_n_events")),
        )


# ============================================================================
# AG-032 item 8 (Fix A, 2026-08-21) — `max_feature_lookback_ms` compartilhado
# entre `src.models.pipeline.run_layer1_sprint` e `src.validation.leakage.
# run_all_leakage_tests`, mesma disciplina de `cpcv._embargo_ms`/AG-009: os
# dois call-sites usam literalmente ESTA função, nunca duas cópias da
# fórmula que podem divergir silenciosamente.
# ============================================================================


class ExpandingFeatureLookbackError(ValueError):
    """Fail-fast (AG-032 item 8, decisão do Manager: opção A, 2026-08-21) —
    o conjunto de features ATIVO contém pelo menos uma feature com
    `lookback_bars: expanding` no registry (`src.features.registry`).
    `expanding` não tem um valor finito honesto pra proteger via purge de
    CPCV (`CPCVConfig.max_feature_lookback_ms`) — a feature listada
    precisa ser removida do conjunto ativo (`T1_FEATURE_IDS`) OU o CPCV
    precisa rodar CONSCIENTEMENTE sem proteção de purge pra ela (não é
    esta exceção que decide qual das duas — só força a decisão a ser
    tomada, opção B (exclusão automática silenciosa) foi rejeitada)."""


_WINDOW_FIELD_NAMES: tuple[str, ...] = (
    "atr_window",
    "ema_window",
    "rsi_window",
    "ret_lookback",
    "vol_ratio_short_window",
    "vol_ratio_long_window",
    "c07_window",
    "d06f_window",
    "e10f_window",
    "b07_window",
)
"""Campos de `FeatureWindows` que são de fato janelas de lookback em barras
(contagem finita que uma feature em `t` alcança pra trás) — exclui
`maker_fee`/`taker_fee` (não são janela) e `min_warmup_bars`/`min_common_
history_bars` (cortes de warmup/cap, não a distância que UMA feature em `t`
olha pra trás; `min_common_history_bars_15m=164256`, AG-030, é justamente o
número que uma rodada de correção anterior mediu como QUEBRANDO o CPCV
(5/15 splits com treino vazio) se usado cru como `max_feature_lookback_ms`
— ver addendum AG-032 item 8, "não re-meça, reuse")."""


class StaleFeatureWindowConstantError(RuntimeError):
    """`max_consecutive_bar_window_duration_ms` foi MEDIDO para uma janela
    de `N` barras; o conjunto ativo de features hoje exige uma janela MAIOR
    que `N`, então a constante persistida **sub-protege** o purge do CPCV.

    **Por que isto falha em vez de avisar (`AG-296`/`ADR-005 §13 v2 §13.1`).**
    Até 2026-08-26 esta condição emitia `structlog.warning` e devolvia a
    constante mesmo assim, com a justificativa de que ela "ainda protege, só
    deixa de ser o máximo exato". Isso valia enquanto a divergência era
    marginal. Medido agora com o vetor real de produção (69 features): o
    registry declara `C08_vol_pctile_rolling_1y` com `lookback_bars: 17520`
    contra as `96` barras para as quais a constante foi medida — **182×**.
    Uma sub-cobertura de purge dessa ordem não é "menos exata", é vazamento
    de janela de feature (B02/B09) entregue como se fosse proteção.

    Remediação: rodar
    `tools/diagnostics/measure_max_consecutive_bar_window_duration.py` sob o
    conjunto ativo atual e atualizar a constante, **ou** tirar do vetor a
    feature que estourou a janela. Nenhuma das duas é escolhida aqui."""


def assert_no_expanding_lookback_in_active_set(
    feature_ids: tuple[str, ...],
) -> None:
    """Levanta `ExpandingFeatureLookbackError` se QUALQUER id em
    `feature_ids` tiver `lookback_bars: expanding` no registry real
    (`src.features.registry.feature_lookback_bars`). Chamada por
    `compute_max_feature_lookback_ms` ANTES de calcular qualquer número —
    nunca exclui a feature ofensora silenciosamente (ver docstring de
    `ExpandingFeatureLookbackError`).

    **Decisão tomada 2026-08-23** (Manager, `AG-032` item pendente/`08_SPLIT`):
    as 3 features expanding SAÍRAM de `T1_FEATURE_IDS` — chamada com o
    default hoje NÃO dispara mais. Continua existindo (não é código morto)
    porque `feature_ids` é parametrizável — qualquer chamador que passe um
    subconjunto customizado incluindo `C07_vol_pctile_expanding`/`D03f_
    volume_z_expanding`/`E02f_funding_z_expanding` (ex. análise pós-hoc via
    `extra_feature_ids`, `src.models.dataset.build_modeling_frame`) segue
    protegido pelo mesmo fail-fast — a opção B (exclusão automática
    silenciosa) continua rejeitada."""
    lookback_by_id = feature_lookback_bars()
    offenders = sorted(fid for fid in feature_ids if lookback_by_id.get(fid) == "expanding")
    if offenders:
        raise ExpandingFeatureLookbackError(
            "max_feature_lookback_ms (CPCV, AG-032 item 8) exige lookback FINITO "
            f"para toda feature do conjunto ativo -- ofensora(s): {offenders}. Cada uma tem "
            "lookback_bars='expanding' no registry (src/features/registry.yaml): janela "
            "expansiva desde t0_dataset, sem valor finito honesto pra proteger via purge de "
            "CPCV. Decisão necessária (NÃO tomada automaticamente aqui): remover essas "
            "features do conjunto ativo (T1_FEATURE_IDS) OU rodar o CPCV conscientemente SEM "
            "proteção de purge para elas (max_feature_lookback_ms=0 passado deliberadamente, "
            "não por omissão)."
        )


def max_feature_lookback_bars(feature_ids: tuple[str, ...]) -> int:
    """Maior `lookback_bars` FINITO declarado no **registry** para as
    `feature_ids` dadas — o alcance real que uma feature em `t` tem para
    trás, por feature, lido da fonte que o declara.

    **Substitui `max_feature_window_bars` no cálculo do purge
    (`ADR-005 §13 v2 §13.1`/`AG-296`).** `max_feature_window_bars` lê os 10
    campos de `_WINDOW_FIELD_NAMES` (constantes de `FeatureWindows`) e
    **não olha para o registry nem para o conjunto ativo**. Isso a torna
    cega a toda feature cuja janela não é uma daquelas 10 constantes —
    medido no vetor real de produção (69 features): `C08_vol_pctile_
    rolling_1y` (17.520), `E03f_funding_cum_3d` (288) e `B10_stoch_k_14`
    não estão cobertas, e a função devolve `96`. O purge era dimensionado
    para 1/182 do alcance real.

    Levanta `ExpandingFeatureLookbackError` (via
    `assert_no_expanding_lookback_in_active_set`) antes de qualquer conta se
    alguma feature for `expanding` — não existe máximo finito honesto nesse
    caso, e escolher um seria inventar proteção."""
    assert_no_expanding_lookback_in_active_set(feature_ids)
    lookback_by_id = feature_lookback_bars()
    faltando = sorted(fid for fid in feature_ids if fid not in lookback_by_id)
    if faltando:
        raise KeyError(
            "max_feature_lookback_bars: feature(s) sem entrada no registry "
            f"(src/features/registry.yaml): {faltando}. O purge do CPCV não pode ser "
            "dimensionado sobre um alcance não declarado -- registre a feature ou tire-a "
            "do conjunto ativo (nenhuma das duas é escolhida aqui)"
        )
    finitos = [v for fid in feature_ids if isinstance(v := lookback_by_id[fid], int)]
    if not finitos:
        raise ValueError(
            "max_feature_lookback_bars: nenhuma feature com lookback finito em "
            f"feature_ids={feature_ids!r} -- não há janela a proteger nem número a devolver"
        )
    return max(finitos)


def max_feature_window_bars(windows: FeatureWindows | None = None) -> int:
    """Maior janela FINITA (em barras) entre os campos de lookback de
    `FeatureWindows` (`_WINDOW_FIELD_NAMES`) — não olha pro registry nem
    pro conjunto ativo de features, só pros valores já carregados de
    `constants.yaml` (`FeatureWindows.from_constants()` se `windows` não
    for passado). Hoje: max(20, 48, 14, 4, 12, 96, 48, 48, 48, 48) = 96
    (`feature_c06_vol_ratio_long_window`) — medido, não hardcoded aqui."""
    w = windows if windows is not None else FeatureWindows.from_constants()
    window_values: tuple[int, ...] = tuple(int(getattr(w, name)) for name in _WINDOW_FIELD_NAMES)
    return max(window_values)


#: `window_bars` sob o qual `max_consecutive_bar_window_duration_ms`
#: (`config/constants.yaml`) foi medido -- metadado do PRÓPRIO valor
#: MEASURED daquela constante (ver `source` completo no yaml), não uma
#: constante de negócio nova. `96` == `max_feature_window_bars()` hoje
#: (`C06_vol_ratio_12_96`) -- duplicado aqui só pra permitir a checagem
#: de staleness sem reabrir constants.yaml em runtime.
_MAX_CONSECUTIVE_BAR_WINDOW_DURATION_WINDOW_BARS: Final[int] = 96  # noqa: magic-number -- metadado de proveniência da constante MEASURED, não constante de negócio


def compute_max_feature_lookback_ms(
    tf: str,
    feature_ids: tuple[str, ...],
    *,
    resolution_id: str | None = None,
) -> int:
    """`None` (default de `resolution_id`) preserva bit-exato
    `max_feature_window_bars(windows) * step_ms(tf)` — valor pronto pra
    `CPCVConfig.from_constants(max_feature_lookback_ms=...)` (AG-032
    item 8, componente 96 da docstring de `src.validation.cpcv`). Helper
    COMPARTILHADO entre `src.models.pipeline.run_layer1_sprint` e
    `src.validation.leakage.run_all_leakage_tests` — os dois chamam
    literalmente esta função, nunca duas cópias da fórmula (mesma
    disciplina de `cpcv._embargo_ms`/AG-009).

    **`resolution_id` setado (D-02, `AG-159`) — solução corrigida
    2026-08-23, não mais o proxy de prefetch reaproveitado.** Retorna
    `max_consecutive_bar_window_duration_ms` (`config/constants.yaml`,
    `MEASURED` direto — máximo REAL, não p99, das 15 combinações
    símbolo×resolução, medido especificamente pra este uso). Achado do
    `project_assurance` (2026-08-23) que motivou a correção:
    `label_prefetch_p99_bar_duration_ms` (usado antes aqui) foi medido
    pro modelo de custo de PREFETCH (sub-cobertura tolerável, falha
    visível) — reaproveitá-lo pro PURGE (sub-cobertura = vazamento
    silencioso, B02/B09) era emprestar uma constante calibrada pra outro
    propósito, funcionando hoje só por coincidência (medição real,
    2026-08-23: proxy de prefetch cobria com folga de ~2,1x no pior
    caso — seguro na prática, mas não por garantia declarada). Constante
    dedicada fecha essa lacuna formalmente, sem inventar número novo
    (B23 — é o máximo já medido).

    **Guarda de staleness**: `max_consecutive_bar_window_duration_ms` foi
    medido pra `max_feature_window_bars()=96`. Se o conjunto ativo de
    features mudar de forma que essa janela cresça (nova feature com
    lookback maior), a constante persistida fica desatualizada — esta
    função detecta isso e emite `structlog.warning` (não falha, a
    constante ainda é uma proteção real, só deixa de ser o máximo exato)
    pedindo remedição via
    `tools/diagnostics/measure_max_consecutive_bar_window_duration.py`.

    Chama `assert_no_expanding_lookback_in_active_set(feature_ids)`
    PRIMEIRO, mesmo quando `resolution_id` é passado — se qualquer
    feature do conjunto ativo tiver `lookback_bars: expanding`, levanta
    `ExpandingFeatureLookbackError` antes de calcular qualquer número
    (opção A, ver docstring daquela função) — protege qualquer chamador
    que passe um `feature_ids` customizado incluindo as 3 expanding, não
    só o caminho default (que não dispara mais desde 2026-08-23). Ordem
    verificada em
    `test_compute_max_feature_lookback_ms_gate_dispara_mesmo_com_
    resolution_id_setado` (`tests/unit/test_features_build.py`, AG-181):
    um refactor que trocasse essa ordem reintroduziria silenciosamente o
    risco que o gate existe pra prevenir."""
    # `feature_ids` deixou de ter default (`ADR-005 §13 v2 §13.1`/`AG-296`):
    # os 3 call sites de produção passavam por omissão o `T1_FEATURE_IDS` de
    # 7 features enquanto o treino usava 69. O default ERA o defeito.
    # A janela agora sai do REGISTRY sobre o conjunto ativo, não dos 10
    # campos de `_WINDOW_FIELD_NAMES` -- ver `max_feature_lookback_bars`.
    window_bars = max_feature_lookback_bars(feature_ids)
    if resolution_id is None:
        return window_bars * step_ms(tf)

    if window_bars > _MAX_CONSECUTIVE_BAR_WINDOW_DURATION_WINDOW_BARS:
        raise StaleFeatureWindowConstantError(
            "max_consecutive_bar_window_duration_ms foi MEDIDO para uma janela de "
            f"{_MAX_CONSECUTIVE_BAR_WINDOW_DURATION_WINDOW_BARS} barras, mas o conjunto "
            f"ativo ({len(feature_ids)} features) exige {window_bars} barras "
            f"({window_bars / _MAX_CONSECUTIVE_BAR_WINDOW_DURATION_WINDOW_BARS:.0f}x maior) "
            "-- a constante persistida SUB-PROTEGE o purge do CPCV, o que e vazamento de "
            "janela de feature (B02/B09), nao uma aproximacao. Remediacao (nenhuma "
            "escolhida aqui): rodar tools/diagnostics/measure_max_consecutive_bar_window_"
            "duration.py sob o conjunto ativo e atualizar config/constants.yaml, OU tirar "
            "do vetor a feature que estourou a janela. Ver ADR-005 §13 v2 §13.1/AG-296."
        )
    if window_bars != _MAX_CONSECUTIVE_BAR_WINDOW_DURATION_WINDOW_BARS:
        logger.warning(
            "features.build.compute_max_feature_lookback_ms.constant_stale",
            resolution_id=resolution_id,
            tf=tf,
            window_bars_atual=window_bars,
            window_bars_medido=_MAX_CONSECUTIVE_BAR_WINDOW_DURATION_WINDOW_BARS,
            reason=(
                "max_consecutive_bar_window_duration_ms foi medido para "
                f"window_bars={_MAX_CONSECUTIVE_BAR_WINDOW_DURATION_WINDOW_BARS}, mas o "
                f"conjunto ativo de features hoje produz window_bars={window_bars} -- MENOR "
                "que o medido, entao a constante SOBRE-protege (seguro, so nao e mais o "
                "maximo exato; o caso MAIOR falha alto em StaleFeatureWindowConstantError, "
                "logo acima). Remedir com tools/diagnostics/measure_max_consecutive_bar_"
                "window_duration.py."
            ),
            see="AG-159",
        )
    return int(load_constant("max_consecutive_bar_window_duration_ms"))


def compute_t1_features(
    bars_15m: pl.DataFrame,
    funding_last_aligned: pl.Series | FloatArray,
    oi_contracts_aligned: pl.Series | FloatArray,
    *,
    windows: FeatureWindows | None = None,
    apply_warmup_mask: bool = True,
    vol_estimator_id: str | None = None,
    taker_imbalance_1m_agg_aligned: pl.Series | FloatArray | None = None,
    futures_positioning_aligned: Mapping[str, pl.Series | FloatArray] | None = None,
) -> pl.DataFrame:
    """Núcleo puro (sem IO) do Feature Engine T1.

    `bars_15m` precisa estar ordenado por `open_time` e conter
    `open/high/low/close/volume/taker_buy_volume/count/open_time/close_time`
    (schema de `src.data.resample.resample_klines` — `count` = número de
    trades da barra, exigido desde o Lote A da liberação de features,
    H5/2026-08-24, insumo de `D08f_trade_count_z_48`/`D09f_avg_trade_
    size_z`). `funding_last_aligned`
    e `oi_contracts_aligned` já vêm alinhados barra a barra (mesmo
    comprimento de `bars_15m`) — tipicamente produzidos por
    `_sources.asof_align_backward`, que faz o asof-join causal ANTES desta
    função ser chamada; esta função não sabe nada sobre asof-join, só
    consome os arrays já alinhados.

    `taker_imbalance_1m_agg_aligned` (Lote B, H5, 2026-08-24) — mesmo
    contrato de `funding_last_aligned`/`oi_contracts_aligned` (array já
    alinhado, produzido por `_sources.load_taker_imbalance_1m_agg_
    aligned`), mas OPCIONAL (`None` por default) — diferente das duas
    acima, que são exigidas desde o Sprint 4 (T1 depende delas).
    `D07f_taker_imbalance_1m_agg` é T2 e exige uma fonte de dado NOVA
    (`klines_1m` bruto, não o já-resampled-pra-15m que todo o resto do
    Feature Engine consome) — tornar isso obrigatório quebraria TODO
    chamador existente (testes com `bars_15m` sintético, sem klines_1m
    correspondente) sem necessidade real, já que D07f não é T1. `None`
    produz a coluna inteira `NaN` (warmup-masked igual a qualquer outra,
    nunca um valor inventado) — `build_t1_features` (casca de IO) passa
    o array real por padrão.

    `futures_positioning_aligned` (Lote C, H5, 2026-08-24) — E08f_oi_
    notional/E14f_toptrader_ls_ratio/E16f_global_ls_ratio/E18f_taker_
    ls_vol_ratio, mesmo contrato de `taker_imbalance_1m_agg_aligned`
    (dict com 4 arrays já alinhados, produzido por `_sources.load_
    futures_positioning_aligned`; `None` por default). Diferente de
    D07f, não precisa de `bar_source` especial — usa `asof_align_
    backward` (mesmo mecanismo causal de funding/OI), que funciona sob
    qualquer grid de barra, não só `time_15m`. `build_t1_features`
    passa o dict real por padrão, sem flag de opt-out (custo de IO
    comparável ao de OI, que já é sempre carregado).

    `vol_estimator_id` (2026-08-17, AG-036/065) escolhe qual estimador
    calcula C01 (`atr_20_abs`, insumo de A05/A13/C02/E27f) — `None`
    (default) preserva bit-exato todo caller existente (`group_c.
    c01_atr_20`, ATR de Wilder). Só dois valores são aceitos hoje, ambos
    amarrados a `windows.atr_window` (não existe conversão de janela entre
    estimadores ainda medida — mesma disciplina de `LabelConfig.
    estimator_id`, CLAUDE.md B23): `f"atr_wilder_w{windows.atr_window}"`
    (equivalente explícito ao default) ou `f"parkinson_w{windows.
    atr_window}"` (`group_c.c01_atr_20_parkinson` — muda a distribuição
    numérica de C01 de verdade, ver docstring daquela função). Qualquer
    outro valor levanta `ValueError` — nunca cai num estimador não
    solicitado silenciosamente.
    """
    if windows is None:
        windows = FeatureWindows.from_constants()

    close = bars_15m["close"].cast(pl.Float64).to_numpy()
    high = bars_15m["high"].cast(pl.Float64).to_numpy()
    low = bars_15m["low"].cast(pl.Float64).to_numpy()
    open_ = bars_15m["open"].cast(pl.Float64).to_numpy()
    volume = bars_15m["volume"].cast(pl.Float64).to_numpy()
    taker_buy_volume = bars_15m["taker_buy_volume"].cast(pl.Float64).to_numpy()
    trade_count = bars_15m["count"].cast(pl.Float64).to_numpy()
    close_time_ms = bars_15m["close_time"].cast(pl.Float64).to_numpy()

    funding_arr = _to_numpy(funding_last_aligned)
    oi_arr = _to_numpy(oi_contracts_aligned)
    n_bars = close.shape[0]
    taker_imbalance_1m_agg_arr = (
        np.full(n_bars, np.nan, dtype=np.float64)
        if taker_imbalance_1m_agg_aligned is None
        else _to_numpy(taker_imbalance_1m_agg_aligned)
    )
    if futures_positioning_aligned is None:
        oi_notional_arr = np.full(n_bars, np.nan, dtype=np.float64)
        toptrader_ls_ratio_arr = np.full(n_bars, np.nan, dtype=np.float64)
        global_ls_ratio_arr = np.full(n_bars, np.nan, dtype=np.float64)
        taker_ls_vol_ratio_arr = np.full(n_bars, np.nan, dtype=np.float64)
    else:
        oi_notional_arr = _to_numpy(futures_positioning_aligned["oi_notional"])
        toptrader_ls_ratio_arr = _to_numpy(futures_positioning_aligned["toptrader_ls_ratio"])
        global_ls_ratio_arr = _to_numpy(futures_positioning_aligned["global_ls_ratio"])
        taker_ls_vol_ratio_arr = _to_numpy(futures_positioning_aligned["taker_ls_vol_ratio"])
    lote_a = LoteAWindows.from_constants()
    lote_b = LoteBWindows.from_constants()

    n = close.shape[0]
    log_return_1 = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            log_return_1[1:] = np.log(close[1:] / close[:-1])

    atr_wilder_id = f"atr_wilder_w{windows.atr_window}"
    parkinson_id = f"parkinson_w{windows.atr_window}"
    if vol_estimator_id is None or vol_estimator_id == atr_wilder_id:
        atr_20_abs = group_c.c01_atr_20(high, low, close, windows.atr_window)
    elif vol_estimator_id == parkinson_id:
        atr_20_abs = group_c.c01_atr_20_parkinson(high, low, close, windows.atr_window)
    else:
        raise ValueError(
            f"vol_estimator_id={vol_estimator_id!r} não suportado -- esperado None, "
            f"{atr_wilder_id!r} ou {parkinson_id!r}"
        )
    atr_20_pct = group_c.c02_atr_20_pct(atr_20_abs, close)
    ema_48 = support.ema(close, windows.ema_window)

    # Lote A da liberação de features (H5, 2026-08-24) -- intermediários
    # reaproveitados por mais de uma coluna abaixo (evita recomputar):
    # A04/A11/C06 são, respectivamente, insumo direto de E12f/C09/C10+C11.
    a14_ema_12 = support.ema(close, lote_a.a14_ema_window)
    a04_log_return_12 = group_a.a04_log_return_12(close, lote_a.a04_log_return_lag)
    a11_true_range_pct = group_a.a11_true_range_pct(high, low, close)
    c06_vol_ratio_12_96 = group_c.c06_vol_ratio_12_96(
        log_return_1, windows.vol_ratio_short_window, windows.vol_ratio_long_window
    )
    e15f_toptrader_ls_z = group_e.e15f_toptrader_ls_z(
        toptrader_ls_ratio_arr, min_common_history_bars=windows.min_common_history_bars
    )

    columns: dict[str, object] = {
        "open_time": bars_15m["open_time"],
        "close_time": bars_15m["close_time"],
        "A05_ret_vol_norm_4": group_a.a05_ret_vol_norm_4(
            close, atr_20_pct, windows.ret_lookback, vol_norm_divisor=lote_a.a05_vol_norm_divisor
        ),
        "A13_dist_ema48_atr": group_a.a13_dist_ema48_atr(close, ema_48, atr_20_abs),
        "B01_rsi_14": group_b.b01_rsi_14(close, windows.rsi_window),
        "E27f_cost_atr_ratio": group_e.e27f_cost_atr_ratio(
            atr_20_pct, windows.maker_fee, windows.taker_fee
        ),
        "C06_vol_ratio_12_96": c06_vol_ratio_12_96,
        "C07_vol_pctile_expanding": group_c.c07_vol_pctile_expanding(
            log_return_1,
            windows.c07_window,
            min_common_history_bars=windows.min_common_history_bars,
        ),
        "D03f_volume_z_expanding": group_d.d03f_volume_z_expanding(
            volume, min_common_history_bars=windows.min_common_history_bars
        ),
        "D06f_taker_imbalance_z_48": group_d.d06f_taker_imbalance_z_48(
            taker_buy_volume, volume, windows.d06f_window
        ),
        "E02f_funding_z_expanding": group_e.e02f_funding_z_expanding(
            funding_arr, min_common_history_bars=windows.min_common_history_bars
        ),
        "E10f_oi_change_z_48": group_e.e10f_oi_change_z_48(oi_arr, windows.e10f_window),
        "C01_atr_20": atr_20_abs,
        "C02_atr_20_pct": atr_20_pct,
        "B07_efficiency_ratio_48": group_b.b07_efficiency_ratio_48(close, windows.b07_window),
        # Lote A da liberação de features (H5, 2026-08-24) -- 47 T2,
        # nenhuma promovida a T1 por esta implementação (§0.2 R4/§2.13).
        "A01_log_return_1": group_a.a01_log_return_1(close, lote_a.a01_log_return_lag),
        "A02_log_return_2": group_a.a02_log_return_2(close, lote_a.a02_log_return_lag),
        "A03_log_return_4": group_a.a03_log_return_4(close, lote_a.a03_log_return_lag),
        "A04_log_return_12": a04_log_return_12,
        "A06_ret_vol_norm_12": group_a.a06_ret_vol_norm_12(
            close,
            atr_20_pct,
            lote_a.a06_ret_lookback_bars,
            variance_ref_lookback_bars=windows.ret_lookback,
            vol_norm_divisor=lote_a.a05_vol_norm_divisor,
        ),
        "A07_body_ratio": group_a.a07_body_ratio(open_, high, low, close),
        "A08_upper_wick_ratio": group_a.a08_upper_wick_ratio(open_, high, low, close),
        "A09_lower_wick_ratio": group_a.a09_lower_wick_ratio(open_, high, low, close),
        "A10_close_location": group_a.a10_close_location(high, low, close),
        "A11_true_range_pct": a11_true_range_pct,
        "A12_gap_pct": group_a.a12_gap_pct(open_, close),
        "A14_dist_ema12_atr": group_a.a14_dist_ema12_atr(close, a14_ema_12, atr_20_abs),
        "B02_rsi_48": group_b.b02_rsi_48(close, lote_a.b02_rsi_window),
        "B03_roc_12": group_b.b03_roc_12(close, lote_a.b03_roc_lookback_bars),
        "B04_macd_hist_norm": group_b.b04_macd_hist_norm(
            close,
            atr_20_abs,
            lote_a.b04_macd_fast_window,
            lote_a.b04_macd_slow_window,
            lote_a.b04_macd_signal_window,
        ),
        "B05_ema_slope_24": group_b.b05_ema_slope_24(
            close, atr_20_abs, lote_a.b05_ema_window, lote_a.b05_slope_lag_bars
        ),
        "B06_momentum_accel": group_b.b06_momentum_accel(
            close, atr_20_pct, lote_a.b06_momentum_lookback_bars
        ),
        "B08_efficiency_ratio_16": group_b.b08_efficiency_ratio_16(
            close, lote_a.b08_efficiency_ratio_window
        ),
        "B09_zscore_close_48": group_b.b09_zscore_close_48(close, lote_a.b09_zscore_close_window),
        "B11_bb_position_20": group_b.b11_bb_position_20(
            close, lote_a.b11_bb_window, lote_a.b11_bb_std_multiplier
        ),
        "C03_realized_vol_48": group_c.c03_realized_vol_48(
            log_return_1, lote_a.c03_realized_vol_window
        ),
        "C04_parkinson_vol_48": group_c.c04_parkinson_vol_48(
            high, low, lote_a.c04_parkinson_vol_window
        ),
        "C05_garman_klass_48": group_c.c05_garman_klass_48(
            high, low, open_, close, lote_a.c05_garman_klass_window
        ),
        "C09_range_pctile_expanding": group_c.c09_range_pctile_expanding(
            a11_true_range_pct, min_common_history_bars=windows.min_common_history_bars
        ),
        "C10_vol_expansion_flag": group_c.c10_vol_expansion_flag(
            c06_vol_ratio_12_96,
            lote_a.c10_vol_expansion_threshold,
            min_common_history_bars=windows.min_common_history_bars,
        ),
        "C11_vol_compression_flag": group_c.c11_vol_compression_flag(
            c06_vol_ratio_12_96,
            lote_a.c11_vol_compression_threshold,
            min_common_history_bars=windows.min_common_history_bars,
        ),
        "C12_vol_of_vol_48": group_c.c12_vol_of_vol_48(
            log_return_1, lote_a.c12_vol_of_vol_inner_window, lote_a.c12_vol_of_vol_outer_window
        ),
        "D01f_volume_z_96": group_d.d01f_volume_z_96(volume, lote_a.d01f_volume_z_window),
        "D02f_rel_volume_48": group_d.d02f_rel_volume_48(volume, lote_a.d02f_rel_volume_window),
        "D04f_volume_accel": group_d.d04f_volume_accel(volume, lote_a.d04f_rel_volume_window),
        "D05f_taker_buy_ratio": group_d.d05f_taker_buy_ratio(taker_buy_volume, volume),
        "D08f_trade_count_z_48": group_d.d08f_trade_count_z_48(
            trade_count, lote_a.d08f_trade_count_z_window
        ),
        "D09f_avg_trade_size_z": group_d.d09f_avg_trade_size_z(
            volume, trade_count, lote_a.d09f_avg_trade_size_z_window
        ),
        "E01f_funding_last": group_e.e01f_funding_last(funding_arr),
        "E05f_time_to_funding_h": group_e.e05f_time_to_funding_h(
            close_time_ms, lote_a.e05f_funding_interval_hours
        ),
        "E09f_oi_contracts": group_e.e09f_oi_contracts(oi_arr),
        "E11f_oi_change_1d": group_e.e11f_oi_change_1d(oi_arr, lote_a.e11f_oi_change_lag_bars),
        "E12f_price_oi_divergence": group_e.e12f_price_oi_divergence(
            a04_log_return_12, oi_arr, lote_a.e12f_oi_change_lag_bars
        ),
        "K01_hour_sin": group_k.k01_hour_sin(close_time_ms),
        "K01_hour_cos": group_k.k01_hour_cos(close_time_ms),
        "K02_dow_sin": group_k.k02_dow_sin(close_time_ms),
        "K02_dow_cos": group_k.k02_dow_cos(close_time_ms),
        "K03_is_weekend": group_k.k03_is_weekend(close_time_ms),
        "K04_session_asia": group_k.k04_session_asia(
            close_time_ms, lote_a.k04_asia_start_hour, lote_a.k04_asia_end_hour
        ),
        "K04_session_europe": group_k.k04_session_europe(
            close_time_ms, lote_a.k04_europe_start_hour, lote_a.k04_europe_end_hour
        ),
        "K04_session_us": group_k.k04_session_us(
            close_time_ms, lote_a.k04_us_start_hour, lote_a.k04_us_end_hour
        ),
        "K08_days_since_halving": group_k.k08_days_since_halving(
            close_time_ms, lote_a.k08_halving_dates_ms
        ),
        # Lote B da liberação de features (H5, 2026-08-24) -- 6 T2.
        "A15_dist_vwap_d_atr": group_a.a15_dist_vwap_d_atr(
            high, low, close, volume, close_time_ms, atr_20_abs
        ),
        "B10_stoch_k_14": group_b.b10_stoch_k_14(high, low, close, lote_b.b10_stoch_window),
        "C08_vol_pctile_rolling_1y": group_c.c08_vol_pctile_rolling_1y(
            log_return_1, lote_b.c08_inner_window, lote_b.c08_outer_window
        ),
        "D07f_taker_imbalance_1m_agg": taker_imbalance_1m_agg_arr,
        "D10f_vol_price_divergence": group_d.d10f_vol_price_divergence(
            log_return_1, volume, lote_b.d10f_window
        ),
        "E03f_funding_cum_3d": group_e.e03f_funding_cum_3d(
            funding_arr, close_time_ms, lote_a.e05f_funding_interval_hours, lote_b.e03f_n_events
        ),
        # Lote C da liberação de features (H5, 2026-08-24) -- 6 T2.
        "E08f_oi_notional": group_e.e08f_oi_notional(oi_notional_arr),
        "E14f_toptrader_ls_ratio": group_e.e14f_toptrader_ls_ratio(toptrader_ls_ratio_arr),
        "E15f_toptrader_ls_z": e15f_toptrader_ls_z,
        "E16f_global_ls_ratio": group_e.e16f_global_ls_ratio(global_ls_ratio_arr),
        "E17f_retail_vs_top_spread": group_e.e17f_retail_vs_top_spread(
            global_ls_ratio_arr,
            e15f_toptrader_ls_z,
            min_common_history_bars=windows.min_common_history_bars,
        ),
        "E18f_taker_ls_vol_ratio": group_e.e18f_taker_ls_vol_ratio(taker_ls_vol_ratio_arr),
    }
    # ADR-005 §13 v2 §13.5-2 / AG-300 -- `nan_to_null=True` na FRONTEIRA
    # numpy->Polars. Sem isto, `NaN` e `null` coexistem no mesmo Float64 e
    # `is_not_null()` (o filtro de warmup de `src.models.dataset.
    # side_subset`) deixa `NaN` passar -- verificado por execucao:
    # `pl.Series([1.0, NaN, None, 3.0]).is_not_null() -> [T, T, F, T]`.
    # A guarda nao guardava, e uma coluna 100% NaN atravessava o pipeline
    # inteiro sem erro, warning ou gate.
    df = pl.DataFrame(columns, nan_to_null=True)

    if apply_warmup_mask:
        df = apply_min_warmup_mask(df, min_warmup_bars=windows.min_warmup_bars)
    return df


class DeadFeatureColumnError(ValueError):
    """Uma coluna de feature saiu **100% nula** depois do warmup.

    Isso nao e "feature com muito NaN" -- e ausencia de dado entregue com
    nome de feature. Achado que motivou a guarda (`ADR-005 §13 v2 §13.2`,
    `AG-300`): `D07f_taker_imbalance_1m_agg` e 100% morta sob dollar bar
    por construcao (`build.py` so carrega `klines_1m` quando
    `bar_source == "time_15m"`), atravessava o pipeline inteiro e chegava
    ao relatorio como `{"constraint": 0, "mean_ic": null, "n_consistent": 0}`
    -- uma coluna inexistente ocupando um lugar do vetor, sem erro, warning
    ou gate. Passava porque o filtro de warmup usava `is_not_null()` sobre
    um Float64 que ainda continha `NaN`; com a fronteira corrigida
    (`nan_to_null=True`), o conjunto de teste ficaria VAZIO -- e um conjunto
    vazio e um sintoma pior de diagnosticar do que esta excecao."""


def assert_no_dead_feature_columns(
    df: pl.DataFrame, *, contexto: str, min_warmup_bars: int
) -> None:
    """Levanta `DeadFeatureColumnError` para toda coluna de feature 100%
    nula FORA do prefixo de warmup.

    O recorte pelo warmup e o ponto: `apply_min_warmup_mask` nula o prefixo
    de proposito, entao olhar o frame inteiro acusaria toda coluna de uma
    serie curta. `contexto` (ex. `"BTCUSDT/dollar_r1"`) entra na mensagem
    porque a mesma coluna pode ser viva numa celula e morta em outra --
    dizer QUAL celula e a diferenca entre um erro acionavel e um enigma.

    Nucleo puro (Idioma A): recebe o frame em memoria, nao le nada."""
    if df.height <= min_warmup_bars:
        return
    corpo = df.slice(min_warmup_bars)
    feature_cols = [c for c in df.columns if c not in _NON_FEATURE_COLUMNS]
    mortas = sorted(c for c in feature_cols if corpo[c].null_count() == corpo.height)
    if mortas:
        raise DeadFeatureColumnError(
            f"{contexto}: coluna(s) de feature 100% nula(s) fora do warmup "
            f"({corpo.height} linhas avaliadas): {mortas}. Uma coluna sem nenhum valor "
            "finito nao e uma feature -- e ausencia de dado com nome de feature, e ocupa "
            "um lugar do vetor de treino sem contribuir nada. Decisao necessaria (NAO "
            "tomada aqui): tirar a coluna do conjunto ativo para esta fonte de barra, OU "
            "prover a fonte que falta. Ver ADR-005 §13 v2 §13.2 / AG-300."
        )


def apply_min_warmup_mask(df: pl.DataFrame, *, min_warmup_bars: int) -> pl.DataFrame:
    """§2.15 invariante 5 — `features.iloc[:min_warmup].isna().all()`.
    Aplicado como um corte UNIFORME sobre todas as colunas de feature
    (não sobre `open_time`/`close_time`), independente do warmup natural
    individual de cada uma — a feature mais lenta a convergir (janela
    expansiva, `realized_vol_96`, EMA48) define o corte para o vetor T1
    inteiro, porque o Alpha precisa de todas simultaneamente válidas."""
    feature_cols = [c for c in df.columns if c not in _NON_FEATURE_COLUMNS]
    df = df.with_row_index("_row_idx")
    exprs = [
        pl.when(pl.col("_row_idx") < min_warmup_bars).then(None).otherwise(pl.col(c)).alias(c)
        for c in feature_cols
    ]
    return df.with_columns(exprs).drop("_row_idx")


def build_t1_features(
    symbol: str,
    start: str,
    end: str,
    *,
    apply_warmup_mask: bool = True,
    bar_source: str = "time_15m",
    vol_estimator_id: str | None = None,
    load_taker_imbalance_1m: bool = True,
    load_futures_positioning: bool = True,
) -> pl.DataFrame:
    """Ponto de entrada com IO: carrega barras + fontes auxiliares
    alinhadas e chama `compute_t1_features`. `start`/`end` devem incluir
    folga suficiente ANTES do início real de interesse para que
    `min_warmup_bars` (e, para C07/D03f/E02f, o histórico expansivo desde
    o início do dataset) tenham dado real por trás — esta função não
    estende o intervalo pedido automaticamente.

    `bar_source` (validação de fiação de dollar bar canônico, 2026-08-16):
    default `"time_15m"` preserva bit-exato TODO caller existente antes
    desta mudança — delega pra `_sources.load_bars(..., bar_source=
    bar_source)`, que por sua vez chama `_sources.load_bars_15m` sem
    alteração nenhuma nesse caso (ver docstring de `_sources.load_bars`).
    `"dollar_r1"` troca a fonte por `lake.query_dollar_bars` (calibração de
    VALIDAÇÃO, não a congelada de produção — ver `src.data.
    build_dollar_bars`); `funding_aligned`/`oi_aligned` (via `_sources.
    asof_align_backward`) não precisam de nenhuma mudança pra isso — dependem
    só de `bars["open_time"]`/`bars["close_time"]`, presentes no schema de
    dollar bar (`schemas.DOLLAR_BARS_R1`) também. `AG-043` (`sqrt(window)`
    em `support.realized_vol`, gap overnight do Yang-Zhang, defasagem do
    asof-join OI/funding) continua pendente — as features saem sem
    crashar sobre dollar bar, mas isso é teste de FIAÇÃO, não prova de
    validade estatística.

    **Decisão registrada 2026-08-17 (Fase 2 da migração Parkinson+dollar-bar,
    fecha o achado de revisão independente `project_assurance` de
    2026-08-16 citado acima em versões anteriores desta docstring):**
    `min_common_history_bars_15m=164256` (AG-030) foi calibrado como "nº de
    barras de 15m entre `SYMBOL_START_DATE` e `END_DATE`" — uma contagem em
    TEMPO DE RELÓGIO. Sob dollar bar a densidade de barras/dia varia por
    símbolo/threshold, então essa contagem não corresponde ao mesmo período
    de calendário entre ativos. Medir um equivalente nativo ("nº de dollar
    bars comparável cross-asset") é trabalho novo de medição, não
    estipulado (B23) — fora do escopo desta migração, que aplica uma
    decisão já medida, não abre uma nova. Decisão: sob `bar_source !=
    "time_15m"`, o corte é DESABILITADO (`windows.min_common_history_bars
    = None` — ver corpo da função abaixo), explicitamente, em vez de herdar
    silenciosamente um número calibrado pra outra grade. C07/D03f/E02f
    ficam expansivas desde a origem do ativo sob dollar bar, sem cap —
    dívida registrada (`audit/architecture_gaps_log.yaml`, addendum
    AG-030), não bloqueia esta fase.

    AG-030 (T0.5, Opção A): sob `bar_source="time_15m"`,
    `windows.min_common_history_bars` (default `FeatureWindows.
    from_constants()` → `min_common_history_bars_15m`, `config/
    constants.yaml`) capa a janela expansiva de C07/D03f/E02f no histórico
    MÍNIMO comum entre os 5 ativos, contado a partir do FIM de `bars_15m`
    — ou seja, relativo a `start`/`end` passados aqui, não a uma data
    absoluta hardcoded. Chamar com `start = SYMBOL_START_DATE[symbol]`
    (histórico completo do ativo, convenção já usada pelo pipeline real)
    produz o efeito pretendido (BTC trunca as barras mais antigas; os 4
    alts, já dentro do orçamento, ficam inalterados); chamar com um `start`
    mais recente que a origem do ativo simplesmente não aciona o corte (`n`
    já cabe no orçamento), sem quebrar nada — mas também sem garantir
    comparabilidade cross-asset fora desse uso padrão.

    **Decisão registrada 2026-08-23 (fecha o débito de `AG-043` sobre
    `feature_a13_ema_window`, pesquisa de literatura em `AG-043` addendum
    — López de Prado 2018, Grądzki/Wójcik/Lessmann 2025):** `windows`
    passa a ser resolvido via `FeatureWindows.from_constants(bar_source=
    bar_source)`, não mais `from_constants()` sem argumento — escala só
    `ema_window` (A13), a ÚNICA janela `scaling_invariant: clock` do vetor
    T1. As outras 9 janelas (RSI/B07/vol_ratio/C07/D06f/E10f/ATR)
    permanecem `bar_count` fixo entre `bar_source` — decisão deliberada e
    específica de cada uma, não omissão (ver `constants.yaml`): a
    literatura sobre barras de informação (dollar/volume bars) confirma
    que manter contagem de barra fixa é o comportamento correto para
    indicadores técnicos genéricos nesse contexto — cada barra carrega
    peso de informação aproximadamente igual, não tempo igual. A13 é
    exceção deliberada porque sua intenção declarada amarra o span ao
    horizonte REAL do label (`time_stop_ms`), não a uma janela de
    estimação genérica. Sob `bar_source="time_15m"`, `ema_window=48`
    continua bit-exato.

    `load_taker_imbalance_1m` (Lote B, H5, 2026-08-24, default `True`):
    carrega `klines_1m` bruto e agrega `D07f_taker_imbalance_1m_agg`
    (`_sources.load_taker_imbalance_1m_agg_aligned`) — real custo de IO
    extra (~15-60x mais linhas que `bars_15m`, dependendo de `bar_
    source`), pago por padrão porque é o comportamento de PRODUÇÃO
    correto (T2 disponível de verdade, não uma coluna sempre-NaN por
    omissão). `False` pula esse carregamento (coluna sai `NaN`, mesmo
    efeito de não passar o argumento em `compute_t1_features`) — usar
    quando o custo extra não se justifica (ex. teste rápido que não
    toca D07f). Sob `bar_source != "time_15m"` o carregamento é SEMPRE
    pulado, independente deste argumento: o mapeamento de `bucket_id`
    de `load_taker_imbalance_1m_agg_aligned` (`open_time // step_ms
    ("15m")`) assume grid de relógio FIXO — sob dollar bar, `bars_15m`
    não tem essa propriedade (barras irregulares, disparadas por
    threshold), o bucket sairia incorreto silenciosamente se calculado
    do mesmo jeito; `NaN` honesto é preferível a um número errado.

    `futures_positioning_aligned` (Lote C, H5, 2026-08-24) — E08f/E14f/
    E16f/E18f, sempre carregado (`_sources.load_futures_positioning_
    aligned`, sem flag de opt-out) — usa `asof_align_backward`, mesmo
    mecanismo causal de funding/OI, seguro sob qualquer `bar_source`
    (diferente de `load_taker_imbalance_1m_agg_aligned`, que depende de
    grid de relógio fixo). Custo de IO comparável ao de OI (mesmo
    arquivo `metrics`, colunas adicionais), carregado quando
    `load_futures_positioning=True` (default abaixo).

    **Achado real (audit_engineering, 2026-08-24, pedido do usuario --
    "auditar se o LightGBM esta pronto pra receber a totalidade das
    features"): `load_taker_imbalance_1m`/`load_futures_positioning`
    DEFAULT `True` aqui, combinado com `src.models.dataset.build_
    modeling_frame` chamando `build_t1_features` SEM passar nenhum dos
    dois (e `src.regime.build.build_regimes` reusando `build_t1_
    features` internamente, MESMA omissao) -- o caminho real de treino
    do Alpha pagava o custo de IO de D07f (`klines_1m` bruto, ~15-96x
    mais linhas que `bars_15m`) e das 4 colunas de `metrics` de E08f-
    E18f DUAS VEZES por chamada (uma na chamada direta aqui dentro de
    `build_modeling_frame`, outra dentro de `build_regimes`), pra
    features que nem `T1_FEATURE_IDS` (so 7) nem o Regime Engine (B07/
    C07/E02f/E27f) consomem -- descartadas no `join_cols` de `build_
    modeling_frame` a menos que pedidas via `extra_feature_ids`.
    Corrigido: `build_modeling_frame` so ativa os dois carregamentos
    quando `extra_feature_ids` de fato referencia D07f/alguma das 4
    futures-positioning; `build_regimes` passa `False` pros dois
    SEMPRE (nunca precisa) -- ver docstring/corpo dos dois
    chamadores."""
    bars_15m = _sources.load_bars(symbol, start, end, bar_source=bar_source)
    funding_aligned = _sources.load_funding_aligned(bars_15m, symbol, start, end)
    oi_aligned = _sources.load_oi_aligned(bars_15m, symbol, start, end)
    windows = FeatureWindows.from_constants(bar_source=bar_source)
    if bar_source != "time_15m":
        windows = replace(windows, min_common_history_bars=None)
    taker_imbalance_1m_agg_aligned = None
    if load_taker_imbalance_1m and bar_source == "time_15m":
        taker_imbalance_1m_agg_aligned = _sources.load_taker_imbalance_1m_agg_aligned(
            bars_15m, symbol, start, end
        )
    futures_positioning_aligned = None
    if load_futures_positioning:
        futures_positioning_aligned = _sources.load_futures_positioning_aligned(
            bars_15m, symbol, start, end
        )
    logger.info(
        "features.build_t1_features",
        symbol=symbol,
        start=str(start),
        end=str(end),
        bar_source=bar_source,
        vol_estimator_id=vol_estimator_id,
        n_bars=bars_15m.height,
        load_taker_imbalance_1m=load_taker_imbalance_1m,
        load_futures_positioning=load_futures_positioning,
    )
    return compute_t1_features(
        bars_15m,
        funding_aligned,
        oi_aligned,
        windows=windows,
        apply_warmup_mask=apply_warmup_mask,
        vol_estimator_id=vol_estimator_id,
        taker_imbalance_1m_agg_aligned=taker_imbalance_1m_agg_aligned,
        futures_positioning_aligned=futures_positioning_aligned,
    )
