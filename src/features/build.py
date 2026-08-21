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

from dataclasses import dataclass, replace

import numpy as np
import polars as pl
import structlog

from . import _sources, support
from ._constants import load_constant
from .groups import group_a, group_b, group_c, group_d, group_e
from .support import FloatArray

logger = structlog.get_logger(__name__)

T1_FEATURE_IDS: tuple[str, ...] = (
    "A05_ret_vol_norm_4",
    "A13_dist_ema48_atr",
    "B01_rsi_14",
    "E27f_cost_atr_ratio",
    "C06_vol_ratio_12_96",
    "C07_vol_pctile_expanding",
    "D03f_volume_z_expanding",
    "D06f_taker_imbalance_z_48",
    "E02f_funding_z_expanding",
    "E10f_oi_change_z_48",
)

# T2 calculadas neste Sprint por serem insumo de outra camada (Regime
# Engine, §4.2, Sprint 5) ou insumo direto de features T1 acima — não
# entram no vetor de treino do Alpha V1, mas têm entrada de registry.
SUPPORT_FEATURE_IDS: tuple[str, ...] = (
    "C01_atr_20",
    "C02_atr_20_pct",
    "B07_efficiency_ratio_48",
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


@dataclass(frozen=True, slots=True)
class FeatureWindows:
    """Todas as janelas de lookback de `constants.yaml` lidas uma única vez
    — evita 10 chamadas repetidas a `load_constant` espalhadas pelo corpo
    de `compute_t1_features`."""

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
    def from_constants(cls) -> FeatureWindows:
        return cls(
            atr_window=int(load_constant("atr_window")),
            ema_window=int(load_constant("feature_a13_ema_window")),
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


def compute_t1_features(
    bars_15m: pl.DataFrame,
    funding_last_aligned: pl.Series | FloatArray,
    oi_contracts_aligned: pl.Series | FloatArray,
    *,
    windows: FeatureWindows | None = None,
    apply_warmup_mask: bool = True,
    vol_estimator_id: str | None = None,
) -> pl.DataFrame:
    """Núcleo puro (sem IO) do Feature Engine T1.

    `bars_15m` precisa estar ordenado por `open_time` e conter
    `open/high/low/close/volume/taker_buy_volume/open_time/close_time`
    (schema de `src.data.resample.resample_klines`). `funding_last_aligned`
    e `oi_contracts_aligned` já vêm alinhados barra a barra (mesmo
    comprimento de `bars_15m`) — tipicamente produzidos por
    `_sources.asof_align_backward`, que faz o asof-join causal ANTES desta
    função ser chamada; esta função não sabe nada sobre asof-join, só
    consome os arrays já alinhados.

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
    volume = bars_15m["volume"].cast(pl.Float64).to_numpy()
    taker_buy_volume = bars_15m["taker_buy_volume"].cast(pl.Float64).to_numpy()

    funding_arr = _to_numpy(funding_last_aligned)
    oi_arr = _to_numpy(oi_contracts_aligned)

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

    columns: dict[str, object] = {
        "open_time": bars_15m["open_time"],
        "close_time": bars_15m["close_time"],
        "A05_ret_vol_norm_4": group_a.a05_ret_vol_norm_4(close, atr_20_pct, windows.ret_lookback),
        "A13_dist_ema48_atr": group_a.a13_dist_ema48_atr(close, ema_48, atr_20_abs),
        "B01_rsi_14": group_b.b01_rsi_14(close, windows.rsi_window),
        "E27f_cost_atr_ratio": group_e.e27f_cost_atr_ratio(
            atr_20_pct, windows.maker_fee, windows.taker_fee
        ),
        "C06_vol_ratio_12_96": group_c.c06_vol_ratio_12_96(
            log_return_1, windows.vol_ratio_short_window, windows.vol_ratio_long_window
        ),
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
    }
    df = pl.DataFrame(columns)

    if apply_warmup_mask:
        df = apply_min_warmup_mask(df, min_warmup_bars=windows.min_warmup_bars)
    return df


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
    comparabilidade cross-asset fora desse uso padrão."""
    bars_15m = _sources.load_bars(symbol, start, end, bar_source=bar_source)
    funding_aligned = _sources.load_funding_aligned(bars_15m, symbol, start, end)
    oi_aligned = _sources.load_oi_aligned(bars_15m, symbol, start, end)
    windows = FeatureWindows.from_constants()
    if bar_source != "time_15m":
        windows = replace(windows, min_common_history_bars=None)
    logger.info(
        "features.build_t1_features",
        symbol=symbol,
        start=str(start),
        end=str(end),
        bar_source=bar_source,
        vol_estimator_id=vol_estimator_id,
        n_bars=bars_15m.height,
    )
    return compute_t1_features(
        bars_15m,
        funding_aligned,
        oi_aligned,
        windows=windows,
        apply_warmup_mask=apply_warmup_mask,
        vol_estimator_id=vol_estimator_id,
    )
