"""Triple barrier ponta a ponta (§3.4) — núcleo do Label Engine, Sprint 6.

**Regra dura B11 — barreiras avaliadas em `mark_1m`, nunca em high/low da
barra de 15m.** `entry_ref` (o preço de referência da entrada) vem do
`close` da barra de 15m (klines regulares — o preço que o Alpha de fato viu
em `t0`); TUDO que decide TP/SL/fill vem de `mark_1m`, em ordem cronológica
real (§3.4, motivo 2: "numa barra de 30m [aqui, 15m] que tocou TP e SL, o
high/low não diz qual veio primeiro").

**Ambiguidades do PRD resolvidas neste módulo, documentadas em vez de
deixadas implícitas** (task explícita: reportar toda interpretação):

1. **`side` no schema §3.5 diz "−1/0/+1"** — leitura mais defensável é que
   isso é um artefato de copy-paste da coluna `label` adjacente (que tem
   +1/0/-1/-2 de verdade). `side` só pode ser ±1 aqui: a direção da barreira
   tem que ser escolhida ANTES de avaliar TP/SL. `build_labels` recebe
   `side` como parâmetro obrigatório; `build_labels_both_sides` roda os dois
   (M_long/M_short, B18).
2. **`t_post = t0`** — o PRD define `t_post = t0 + latência_decisão`, mas
   nenhuma constante de latência de decisão existe em `constants.yaml` (não
   inventada aqui — Regra Zero, CLAUDE.md "não invente faixas/números").
   Simplificação Sprint 6, documentada, não escondida: latência assumida
   zero. Quando uma medição real de latência existir (execução real,
   Sprints 12+), isto muda para `t0 + measured_latency`.
3. **`exit_price` em TP/SL = o próprio preço da barreira** (`tp_price`/
   `sl_price`), não o close do candle de 1m que tocou — convenção padrão de
   triple barrier (o stop/take-profit executa no nível, não no OHLC do
   candle que o disparou). Para `TIME`, não há nível — `exit_price` é o
   `close` do candle de mark_1m em `horizon_end`.
4. **`adverse_selection_bps` é reportado, NÃO subtraído de `ret_net`.** A
   fórmula literal do §3.4 (`ret_net = ret_gross - c_entry - c_exit -
   funding/notional`) não tem termo de seleção adversa; o §3.5 chama
   `ret_net` de "líquido de tudo", o que é ambíguo com a fórmula do §3.4.
   Escolha conservadora: reportar o placeholder (`constants.yaml
   adverse_selection_bps`, classe A ASSUMED) como coluna informativa, não
   fabricar um desconto que a Label Engine não pode medir sozinha a partir
   de `mark_1m` — o markout real só é medível ao vivo (§9.5.1, Paper).
5. **Ambiguidade TP-e-SL-no-mesmo-candle-de-1m** (residual de B11 em escala
   menor — 1 minuto em vez de 15): resolvida por proximidade ao `open` do
   candle (assume que o preço viajou do open em direção à barreira mais
   próxima primeiro). Contada e logada (`n_tie_break`), não escondida.
6. **Gap de cobertura de `exchangeInfo` histórico** — só existe 1 snapshot
   no disco (2026-08-08); `load_filters_asof(t)` levanta
   `NoFiltersAvailableError` para qualquer `t` anterior. Ver
   `known_gaps.exchange_info_snapshot_coverage_gap` em `constants.yaml` e
   `historical_filters_fallback` abaixo.
7. **Concorrência/unicidade calculadas POR LADO** (`side=+1` e `side=-1`
   separadamente — cada um alimenta um modelo binário distinto, B18), mas
   `sample_weight` é normalizado para média 1 sobre o dataset COMBINADO
   (os dois lados juntos), porque §3.8 verifica a média sobre
   `labels/{version}/labels.parquet` inteiro, um arquivo só.

**Reuso, não reimplementação:** ATR vem de
`src.features.groups.group_c.c01_atr_20`/`c02_atr_20_pct` (Wilder,
`src.features.support`) — mesmo código do Feature Engine (Sprint 4), não
uma segunda implementação. `load_filters_asof` vem de
`src.exchange.filters`, inalterado.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.data import lake
from src.data.resample import step_ms
from src.exchange.filters import Filters, NoFiltersAvailableError, load_filters_asof
from src.features.groups import group_c

from . import fill_model, weights
from ._constants import load_constant
from ._paths import LABELS_OUTPUT_DIR

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]

DateLike = date | str

# Fato de calendário do TF de decisão atual (§0.1 decision_tf=15m), não um
# hiperparâmetro — mesmo raciocínio de `resample._TIMEFRAME_MINUTES`. Entra
# no `config_hash` (LabelConfig.decision_tf_minutes) porque uma mudança
# futura de TF mudaria a semântica do label inteira, mesmo não sendo
# "sweepable" como tp_atr_mult/sl_atr_mult.
_BAR_MS: Final[int] = step_ms("15m")

# Fator de conversão fração -> pontos-base — definição matemática, não
# constante de domínio (mesma categoria de "60s por minuto" em resample.py).
_BPS_PER_UNIT: Final[int] = 10_000

_LABEL_BY_BARRIER: Final[dict[str, int]] = {"TP": 1, "TIME": 0, "SL": -1}


def _as_date(value: DateLike) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _ms_to_date(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date()


def _ms_epoch_to_utc(expr: pl.Expr) -> pl.Expr:
    return expr.cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")


# ============================================================================
# LabelConfig — bloco de barreiras + hash determinístico (B15)
# ============================================================================


@dataclass(frozen=True, slots=True)
class LabelConfig:
    """Todo parâmetro que, se mudar, invalida labels já calculados (B15).
    `tp_atr_mult`/`sl_atr_mult`/`time_stop_bars`/`atr_window`/`maker_fee`/
    `taker_fee` já existem em `constants.yaml` (§0.2 R1/R2) — REUSADOS aqui,
    não redeclarados. `fill_timeout_bars` é a única constante nova do
    Sprint 6 (ver `constants.yaml`)."""

    tp_atr_mult: float
    sl_atr_mult: float
    time_stop_bars: int
    fill_timeout_bars: int
    atr_window: int
    maker_fee: float
    taker_fee: float
    decision_tf_minutes: int = 15

    @classmethod
    def from_constants(cls) -> LabelConfig:
        return cls(
            tp_atr_mult=float(load_constant("tp_atr_mult")),
            sl_atr_mult=float(load_constant("sl_atr_mult")),
            time_stop_bars=int(load_constant("time_stop_bars")),
            fill_timeout_bars=int(load_constant("fill_timeout_bars")),
            atr_window=int(load_constant("atr_window")),
            maker_fee=float(load_constant("maker_fee")),
            taker_fee=float(load_constant("taker_fee")),
        )

    @property
    def config_hash(self) -> str:
        """Hash determinístico (sha256, truncado a 16 hex) do bloco de
        barreiras — muda se QUALQUER campo mudar. `orjson` com chaves
        ordenadas garante que o mesmo conjunto de valores sempre produz o
        mesmo hash, independente da ordem de construção do dataclass."""
        payload = {
            "tp_atr_mult": self.tp_atr_mult,
            "sl_atr_mult": self.sl_atr_mult,
            "time_stop_bars": self.time_stop_bars,
            "fill_timeout_bars": self.fill_timeout_bars,
            "atr_window": self.atr_window,
            "maker_fee": self.maker_fee,
            "taker_fee": self.taker_fee,
            "decision_tf_minutes": self.decision_tf_minutes,
        }
        blob = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
        return hashlib.sha256(blob).hexdigest()[:16]


class ConfigHashMismatchError(Exception):
    """B15 — `config_hash` do label difere do hash da configuração de
    execução, ou o dataset mistura mais de uma config."""


def verify_config_hash(labels: pl.DataFrame, execution_config: LabelConfig) -> None:
    """Operacionaliza as duas primeiras linhas do §3.8 como função
    reusável (não só um `assert` solto em teste) — pensada para ser chamada
    também no caminho real de backtest/execução antes de consumir
    `labels.parquet` (B15: "teste de CI que quebra o build, não item de
    checklist")."""
    if labels.is_empty():
        raise ConfigHashMismatchError("labels vazio — nada para verificar")
    unique_hashes = labels["config_hash"].unique().to_list()
    if len(unique_hashes) != 1:
        raise ConfigHashMismatchError(
            f"labels.config_hash não é único ({unique_hashes}) — dataset combina "
            "execuções com config diferente; recalcule os labels do zero"
        )
    if unique_hashes[0] != execution_config.config_hash:
        raise ConfigHashMismatchError(
            f"config_hash do label ({unique_hashes[0]}) != config_hash da execução "
            f"({execution_config.config_hash}) — B15: o modelo aprendeu sobre um trade "
            "que a execução não faz. Recalcule os labels com a config atual."
        )


def assert_label_invariants(labels: pl.DataFrame, *, time_stop_bars: int) -> None:
    """§3.8 — as seis invariantes do PRD, como função reusável em vez de
    `assert` solto: chamada pelos testes E disponível para o caminho real
    (validation/backtest) validar um `labels.parquet` antes de consumir."""
    assert bool((labels["t1"] > labels["t0"]).all()), "t1 <= t0 em alguma linha"

    entry_null = labels["t_entry"].is_null()
    is_nofill = labels["barrier_hit"].cast(pl.Utf8) == "NOFILL"
    assert bool((entry_null == is_nofill).all()), "t_entry nulo != (barrier_hit == NOFILL)"

    assert labels["config_hash"].n_unique() == 1, "config_hash não é único"

    # `.to_numpy()` antes do `float()` — o retorno agregado de `pl.Series.mean()`
    # é uma união ampla nos stubs de tipo do polars (mypy strict reclama de
    # `float(...)` sobre ela); convertendo pra numpy primeiro o tipo fica
    # concreto (`np.float64`) sem mudar o valor calculado.
    weights_arr = labels["sample_weight"].to_numpy().astype(np.float64)
    mean_w = float(np.mean(weights_arr)) if weights_arr.size else float("nan")
    tolerance = 1e-6  # literal do próprio §3.8 do PRD, não escolha nova  # noqa: magic-number
    assert abs(mean_w - 1.0) < tolerance, f"sample_weight.mean() = {mean_w}, esperado ~1.0"

    assert bool((labels["n_bars_held"] <= time_stop_bars).all()), "n_bars_held > time_stop_bars"

    uniq = labels["uniqueness"]
    assert bool(((uniq >= 0.0) & (uniq <= 1.0)).all()), "uniqueness fora de [0, 1]"


# ============================================================================
# Arredondamento de tick (B12/GTX — a ordem tem que ficar passiva)
# ============================================================================


def round_to_tick(price: float, side: int, tick_size: Decimal) -> float:
    """Arredonda `price` para um múltiplo válido de `tick_size`, na direção
    que mantém a ordem PASSIVA (maker/post-only — B12/GTX, execução real em
    `time_in_force: GTX`): compra (`side=1`) arredonda para BAIXO — nunca
    cruza o book pagando o ask; venda (`side=-1`) arredonda para CIMA —
    nunca cruza pagando o bid. O pseudocódigo do §3.4
    (`round_to_tick(entry_ref, side, filters_asof(t0))`) não detalha a
    direção de arredondamento — resolvida e documentada aqui, não deixada
    implícita."""
    if side not in (1, -1):
        raise ValueError(f"side deve ser 1 (compra) ou -1 (venda), recebido {side}")
    if tick_size <= 0:
        return price
    price_dec = Decimal(str(price))
    steps = price_dec / tick_size
    rounding = ROUND_FLOOR if side == 1 else ROUND_CEILING
    quantized = steps.to_integral_value(rounding=rounding)
    return float(quantized * tick_size)


# ============================================================================
# Resolução de filtros de instrumento por data — REUSA load_filters_asof.
# Ver known_gaps.exchange_info_snapshot_coverage_gap em constants.yaml: só
# existe 1 snapshot no disco (2026-08-08); fallback é OPT-IN, nunca default.
# ============================================================================


@dataclass(frozen=True, slots=True)
class _ResolvedFilters:
    tick_size: Decimal
    filters_hash: str
    is_fallback: bool


def _hash_filters(symbol: str, snapshot_date: date, tick_size: Decimal, *, fallback: bool) -> str:
    payload = f"{symbol}|{snapshot_date.isoformat()}|{tick_size}|fallback={fallback}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _earliest_available_filters(symbol: str) -> Filters:
    """Só chamado sob fallback EXPLÍCITO (`historical_filters_fallback=True`).
    Reusa `load_filters_asof` com a referência "agora" (não uma data futura
    fixa no código) — pega o snapshot mais recente no disco; hoje isso é o
    único que existe, mas a chamada não hardcoda essa data, então continua
    correta se mais snapshots forward forem coletados depois."""
    return load_filters_asof(datetime.now(tz=UTC), symbol=symbol)


def _resolve_filters_cached(
    t0_date: date,
    symbol: str,
    cache: dict[date, _ResolvedFilters],
    *,
    historical_filters_fallback: bool,
) -> _ResolvedFilters:
    cached = cache.get(t0_date)
    if cached is not None:
        return cached

    try:
        filters = load_filters_asof(t0_date, symbol=symbol)
        resolved = _ResolvedFilters(
            tick_size=filters.tick_size,
            filters_hash=_hash_filters(
                symbol, filters.snapshot_date, filters.tick_size, fallback=False
            ),
            is_fallback=False,
        )
    except NoFiltersAvailableError:
        if not historical_filters_fallback:
            raise
        fallback_filters = _earliest_available_filters(symbol)
        logger.warning(
            "labels.filters_fallback_used",
            symbol=symbol,
            requested_date=t0_date.isoformat(),
            fallback_snapshot_date=fallback_filters.snapshot_date.isoformat(),
            reason=(
                "nenhum snapshot exchangeInfo cobre esta data (B01/§1.4) — ver "
                "known_gaps.exchange_info_snapshot_coverage_gap em constants.yaml. "
                "Fallback explícito, só ativo com historical_filters_fallback=True."
            ),
        )
        resolved = _ResolvedFilters(
            tick_size=fallback_filters.tick_size,
            filters_hash=_hash_filters(
                symbol, fallback_filters.snapshot_date, fallback_filters.tick_size, fallback=True
            ),
            is_fallback=True,
        )
    cache[t0_date] = resolved
    return resolved


# ============================================================================
# Primeiro toque de barreira (§3.4, B11) — mark_1m, ordem cronológica real
# ============================================================================


@dataclass(frozen=True, slots=True)
class _BarrierTouch:
    barrier: str  # "TP" | "SL" | "TIME"
    t1_ms: int
    exit_price: float
    tie_break_used: bool


def _first_barrier_touch(
    path_time: IntArray,
    path_open: FloatArray,
    path_high: FloatArray,
    path_low: FloatArray,
    path_close: FloatArray,
    *,
    tp_price: float,
    sl_price: float,
    side: int,
    horizon_end_ms: int,
) -> _BarrierTouch:
    """`path_*` são o recorte de `mark_1m` de `t_entry` (inclusive) até
    `horizon_end_ms` (inclusive), já em ordem cronológica. `np.argmax` sobre
    um array booleano devolve o índice do primeiro `True` — "primeiro toque
    em ordem cronológica real", não high/low de uma barra maior (B11)."""
    if side == 1:
        tp_touch = path_high >= tp_price
        sl_touch = path_low <= sl_price
    else:
        tp_touch = path_low <= tp_price
        sl_touch = path_high >= sl_price

    tp_idx = int(np.argmax(tp_touch)) if bool(tp_touch.any()) else -1
    sl_idx = int(np.argmax(sl_touch)) if bool(sl_touch.any()) else -1

    if tp_idx == -1 and sl_idx == -1:
        return _BarrierTouch("TIME", horizon_end_ms, float(path_close[-1]), False)

    if sl_idx == -1 or (tp_idx != -1 and tp_idx < sl_idx):
        return _BarrierTouch("TP", int(path_time[tp_idx]), tp_price, False)

    if tp_idx == -1 or (sl_idx != -1 and sl_idx < tp_idx):
        return _BarrierTouch("SL", int(path_time[sl_idx]), sl_price, False)

    # tp_idx == sl_idx: TP e SL tocados no MESMO candle de 1m — resíduo de
    # B11 em escala menor (ver docstring do módulo, item 5). Resolvido por
    # proximidade ao `open` do candle.
    k = tp_idx
    dist_tp = abs(path_open[k] - tp_price)
    dist_sl = abs(path_open[k] - sl_price)
    if dist_tp <= dist_sl:
        return _BarrierTouch("TP", int(path_time[k]), tp_price, True)
    return _BarrierTouch("SL", int(path_time[k]), sl_price, True)


# ============================================================================
# Schema pré-pesos (concurrency/uniqueness/sample_weight entram depois, em
# weights.apply_weights — precisam do conjunto POR LADO inteiro).
# ============================================================================

_PRE_WEIGHT_SCHEMA: dict[str, Any] = {
    "t0": pl.Int64,
    "t_post": pl.Int64,
    "t_entry": pl.Int64,
    "t1": pl.Int64,
    "side": pl.Int8,
    "label": pl.Int8,
    "barrier_hit": pl.Utf8,
    "entry_price_limit": pl.Float64,
    "entry_price_fill": pl.Float64,
    "tp_price": pl.Float64,
    "sl_price": pl.Float64,
    "exit_price": pl.Float64,
    "ret_gross": pl.Float64,
    "cost_entry_bps": pl.Float64,
    "cost_exit_bps": pl.Float64,
    "funding_bps": pl.Float64,
    "adverse_selection_bps": pl.Float64,
    "ret_net": pl.Float64,
    "atr_at_t0": pl.Float64,
    "n_bars_held": pl.Int16,
    "n_funding_events": pl.Int8,
    "filters_hash": pl.Utf8,
    "config_hash": pl.Utf8,
}

LABEL_COLUMNS: Final[tuple[str, ...]] = (
    "t0",
    "t_post",
    "t_entry",
    "t1",
    "side",
    "label",
    "barrier_hit",
    "entry_price_limit",
    "entry_price_fill",
    "tp_price",
    "sl_price",
    "exit_price",
    "ret_gross",
    "cost_entry_bps",
    "cost_exit_bps",
    "funding_bps",
    "adverse_selection_bps",
    "ret_net",
    "atr_at_t0",
    "n_bars_held",
    "n_funding_events",
    "concurrency",
    "uniqueness",
    "sample_weight",
    "filters_hash",
    "config_hash",
)


def _empty_pre_weight_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_PRE_WEIGHT_SCHEMA)


def _finalize_pre_weight_frame(cols: dict[str, list[Any]]) -> pl.DataFrame:
    df = pl.DataFrame(cols, schema=_PRE_WEIGHT_SCHEMA)
    df = df.with_columns([_ms_epoch_to_utc(pl.col(c)) for c in ("t0", "t_post", "t_entry", "t1")])
    df = df.with_columns(pl.col("barrier_hit").cast(pl.Categorical))
    return df


def _append_nofill_row(
    cols: dict[str, list[Any]],
    *,
    t0: int,
    t_post: int,
    t1: int,
    side: int,
    limit_px: float,
    atr_pct_i: float,
    filters_hash: str,
    config_hash: str,
) -> None:
    """§3.2 — `NOFILL` é desfecho de primeira classe, `label=-2`. `ret=0.0`
    literal do pseudocódigo §3.4 (`emit(label=-2, barrier_hit="NOFILL",
    t1=t_post+timeout, ret=0.0)`)."""
    cols["t0"].append(t0)
    cols["t_post"].append(t_post)
    cols["t_entry"].append(None)
    cols["t1"].append(t1)
    cols["side"].append(side)
    cols["label"].append(-2)
    cols["barrier_hit"].append("NOFILL")
    cols["entry_price_limit"].append(limit_px)
    cols["entry_price_fill"].append(None)
    cols["tp_price"].append(None)
    cols["sl_price"].append(None)
    cols["exit_price"].append(None)
    cols["ret_gross"].append(0.0)
    cols["cost_entry_bps"].append(0.0)
    cols["cost_exit_bps"].append(0.0)
    cols["funding_bps"].append(0.0)
    cols["adverse_selection_bps"].append(0.0)
    cols["ret_net"].append(0.0)
    cols["atr_at_t0"].append(atr_pct_i)
    cols["n_bars_held"].append(0)
    cols["n_funding_events"].append(0)
    cols["filters_hash"].append(filters_hash)
    cols["config_hash"].append(config_hash)


# ============================================================================
# build_labels — núcleo puro-ish (só IO indireto: load_filters_asof por
# data, memoizado). UM lado por chamada.
# ============================================================================


def build_labels(
    bars_15m: pl.DataFrame,
    mark_1m: pl.DataFrame,
    funding: pl.DataFrame,
    *,
    side: int,
    symbol: str = "BTCUSDT",
    config: LabelConfig | None = None,
    historical_filters_fallback: bool = False,
) -> pl.DataFrame:
    """Núcleo do Label Engine (§3.4) para UM lado (`side=1` long, `side=-1`
    short — ver item 1 da docstring do módulo).

    `bars_15m`: klines REGULARES (não mark) a 15m — schema de
    `src.data.resample.resample_klines` (`open_time`, `close_time`, `open`,
    `high`, `low`, `close`, ...). `close` vira `entry_ref`; `high`/`low`/
    `close` alimentam o ATR (§0.2 R1/R2) que dimensiona TP/SL — NUNCA usados
    para decidir toque de barreira (isso é só `mark_1m`, B11).

    `mark_1m`: schema `MARK_PRICE_KLINES_1M` (klines-like, `open_time`
    epoch ms, `open`/`high`/`low`/`close`) — fonte OBRIGATÓRIA de toque de
    barreira e de fill (B11).

    `funding`: schema `FUNDING` (`calc_time` epoch ms, `last_funding_rate`).

    Retorna o schema pré-pesos (sem `concurrency`/`uniqueness`/
    `sample_weight` — essas exigem o conjunto completo do lado, calculadas
    em `weights.apply_weights` por `build_labels_both_sides`)."""
    if side not in (1, -1):
        raise ValueError(f"side deve ser 1 (long) ou -1 (short), recebido {side}")
    cfg = config if config is not None else LabelConfig.from_constants()

    bars = bars_15m.sort("open_time")
    n = bars.height
    if n == 0:
        return _empty_pre_weight_frame()

    close = bars["close"].cast(pl.Float64).to_numpy()
    high = bars["high"].cast(pl.Float64).to_numpy()
    low = bars["low"].cast(pl.Float64).to_numpy()
    t0_arr = bars["close_time"].cast(pl.Int64).to_numpy().astype(np.int64)

    # ATR reusado do Feature Engine (Sprint 4) — não reimplementado aqui.
    atr_abs = group_c.c01_atr_20(high, low, close, cfg.atr_window)
    atr_pct = group_c.c02_atr_20_pct(atr_abs, close)
    valid_atr = ~np.isnan(atr_pct)
    n_warmup_dropped = int((~valid_atr).sum())

    mark = mark_1m.sort("open_time")
    mark_open_time = mark["open_time"].cast(pl.Int64).to_numpy().astype(np.int64)
    mark_open = mark["open"].cast(pl.Float64).to_numpy()
    mark_high = mark["high"].cast(pl.Float64).to_numpy()
    mark_low = mark["low"].cast(pl.Float64).to_numpy()
    mark_close = mark["close"].cast(pl.Float64).to_numpy()
    max_mark_open_time = int(mark_open_time[-1]) if mark_open_time.size else -1

    fund = funding.sort("calc_time")
    fund_time = fund["calc_time"].cast(pl.Int64).to_numpy().astype(np.int64)
    fund_rate = fund["last_funding_rate"].cast(pl.Float64).to_numpy()

    adverse_selection_bps_const = float(load_constant("adverse_selection_bps"))

    filters_cache: dict[date, _ResolvedFilters] = {}
    cols: dict[str, list[Any]] = {c: [] for c in _PRE_WEIGHT_SCHEMA}

    n_incomplete_tail = 0
    n_tie_break = 0

    for i in range(n):
        if not valid_atr[i]:
            continue

        t0 = int(t0_arr[i])
        t_post = t0  # simplificação Sprint 6 — ver item 2 da docstring do módulo
        entry_ref = float(close[i])
        atr_pct_i = float(atr_pct[i])

        t0_date = _ms_to_date(t0)
        resolved_filters = _resolve_filters_cached(
            t0_date,
            symbol,
            filters_cache,
            historical_filters_fallback=historical_filters_fallback,
        )
        limit_px = round_to_tick(entry_ref, side, resolved_filters.tick_size)

        fill_horizon_ms = t_post + cfg.fill_timeout_bars * _BAR_MS
        if fill_horizon_ms > max_mark_open_time:
            n_incomplete_tail += 1
            continue

        fill = fill_model.simulate_fill_arrays(
            mark_open_time,
            mark_low,
            mark_high,
            t_post_ms=t_post,
            horizon_ms=fill_horizon_ms,
            limit_price=limit_px,
            side=side,
        )

        if fill.t_entry_ms is None:
            _append_nofill_row(
                cols,
                t0=t0,
                t_post=t_post,
                t1=fill_horizon_ms,
                side=side,
                limit_px=limit_px,
                atr_pct_i=atr_pct_i,
                filters_hash=resolved_filters.filters_hash,
                config_hash=cfg.config_hash,
            )
            continue

        t_entry = fill.t_entry_ms
        fill_px = fill.fill_price
        if fill_px is None:
            # Inalcançável — FillResult garante o par (t_entry_ms, fill_price)
            # sempre juntos. Só documenta o contrato pro mypy (Optional).
            raise AssertionError(
                "fill_price None com t_entry_ms definido — contrato de FillResult quebrado"
            )

        horizon_end_ms = t0 + cfg.time_stop_bars * _BAR_MS
        if horizon_end_ms > max_mark_open_time:
            n_incomplete_tail += 1
            continue

        tp_price = fill_px * (1 + side * cfg.tp_atr_mult * atr_pct_i)
        sl_price = fill_px * (1 - side * cfg.sl_atr_mult * atr_pct_i)

        lo_idx = int(np.searchsorted(mark_open_time, t_entry, side="left"))
        hi_idx = int(np.searchsorted(mark_open_time, horizon_end_ms, side="right"))

        touch = _first_barrier_touch(
            mark_open_time[lo_idx:hi_idx],
            mark_open[lo_idx:hi_idx],
            mark_high[lo_idx:hi_idx],
            mark_low[lo_idx:hi_idx],
            mark_close[lo_idx:hi_idx],
            tp_price=tp_price,
            sl_price=sl_price,
            side=side,
            horizon_end_ms=horizon_end_ms,
        )
        if touch.tie_break_used:
            n_tie_break += 1

        t1 = touch.t1_ms
        exit_price = touch.exit_price
        barrier = touch.barrier
        label = _LABEL_BY_BARRIER[barrier]

        ret_gross = side * (exit_price / fill_px - 1.0)
        cost_entry_frac = cfg.maker_fee
        cost_exit_frac = cfg.maker_fee if barrier == "TP" else cfg.taker_fee

        f_lo = int(np.searchsorted(fund_time, t_entry, side="left"))
        f_hi = int(np.searchsorted(fund_time, t1, side="right"))
        events_rate = fund_rate[f_lo:f_hi]
        n_funding_events = int(events_rate.shape[0])
        funding_frac = float(np.nansum(events_rate)) * side

        ret_net = ret_gross - cost_entry_frac - cost_exit_frac - funding_frac
        n_bars_held = int(np.ceil((t1 - t0) / _BAR_MS)) if t1 > t0 else 0

        cols["t0"].append(t0)
        cols["t_post"].append(t_post)
        cols["t_entry"].append(t_entry)
        cols["t1"].append(t1)
        cols["side"].append(side)
        cols["label"].append(label)
        cols["barrier_hit"].append(barrier)
        cols["entry_price_limit"].append(limit_px)
        cols["entry_price_fill"].append(fill_px)
        cols["tp_price"].append(tp_price)
        cols["sl_price"].append(sl_price)
        cols["exit_price"].append(exit_price)
        cols["ret_gross"].append(ret_gross)
        cols["cost_entry_bps"].append(cost_entry_frac * _BPS_PER_UNIT)
        cols["cost_exit_bps"].append(cost_exit_frac * _BPS_PER_UNIT)
        cols["funding_bps"].append(funding_frac * _BPS_PER_UNIT)
        cols["adverse_selection_bps"].append(adverse_selection_bps_const)
        cols["ret_net"].append(ret_net)
        cols["atr_at_t0"].append(atr_pct_i)
        cols["n_bars_held"].append(n_bars_held)
        cols["n_funding_events"].append(n_funding_events)
        cols["filters_hash"].append(resolved_filters.filters_hash)
        cols["config_hash"].append(cfg.config_hash)

    logger.info(
        "labels.build_labels",
        symbol=symbol,
        side=side,
        n_input_bars=n,
        n_warmup_dropped=n_warmup_dropped,
        n_incomplete_tail=n_incomplete_tail,
        n_tie_break=n_tie_break,
        n_emitted=len(cols["t0"]),
    )

    return _finalize_pre_weight_frame(cols)


def build_labels_both_sides(
    bars_15m: pl.DataFrame,
    mark_1m: pl.DataFrame,
    funding: pl.DataFrame,
    *,
    symbol: str = "BTCUSDT",
    config: LabelConfig | None = None,
    historical_filters_fallback: bool = False,
) -> pl.DataFrame:
    """Roda `build_labels` para os dois lados (M_long `side=1`, M_short
    `side=-1` — B18) e aplica `weights.apply_weights` sobre o conjunto
    combinado (concorrência/unicidade por lado, peso normalizado
    globalmente — item 7 da docstring do módulo). Retorna já no schema
    final exato de `labels/{version}/labels.parquet` (`LABEL_COLUMNS`)."""
    cfg = config if config is not None else LabelConfig.from_constants()

    long_labels = build_labels(
        bars_15m,
        mark_1m,
        funding,
        side=1,
        symbol=symbol,
        config=cfg,
        historical_filters_fallback=historical_filters_fallback,
    )
    short_labels = build_labels(
        bars_15m,
        mark_1m,
        funding,
        side=-1,
        symbol=symbol,
        config=cfg,
        historical_filters_fallback=historical_filters_fallback,
    )
    combined = pl.concat([long_labels, short_labels], how="vertical")
    weighted = weights.apply_weights(combined)
    return weighted.select(list(LABEL_COLUMNS))


def build_labels_for_symbol(
    symbol: str,
    start: DateLike,
    end: DateLike,
    *,
    config: LabelConfig | None = None,
    historical_filters_fallback: bool = False,
) -> pl.DataFrame:
    """Ponto de entrada com IO — análogo a
    `features.build.build_t1_features(symbol, start, end)`. Carrega klines
    regulares de 15m (`entry_ref`/ATR), `mark_1m` e `funding` via
    `src.data.lake` (reuso, não reimplementação).

    `mark_1m`/`funding` são buscados com 1 dia de folga ALÉM de `end` — sem
    isso, os últimos `time_stop_bars` labels do intervalo pedido seriam
    descartados por "cauda incompleta" apesar do dado existir logo depois
    de `end` (1 dia cobre time_stop_bars*15m e fill_timeout_bars*15m com
    folga, já que ambos ficam bem abaixo de 24h com os valores atuais de
    `constants.yaml`)."""
    cfg = config if config is not None else LabelConfig.from_constants()

    bars_15m = lake.query_bars(symbol, "15m", start, end, source="klines_1m", cast_prices=True)

    mark_end = _as_date(end) + timedelta(days=1)
    mark_1m = lake.query_bars(
        symbol, "1m", start, mark_end, source="mark_price_klines_1m", cast_prices=True
    )
    funding = lake.query_funding(symbol, start, mark_end)

    logger.info(
        "labels.build_labels_for_symbol",
        symbol=symbol,
        start=str(start),
        end=str(end),
        n_bars_15m=bars_15m.height,
        n_mark_1m=mark_1m.height,
        n_funding=funding.height,
    )

    return build_labels_both_sides(
        bars_15m,
        mark_1m,
        funding,
        symbol=symbol,
        config=cfg,
        historical_filters_fallback=historical_filters_fallback,
    )


def write_labels_atomic(
    labels: pl.DataFrame, *, version: str = "v1", dest_dir: Path | None = None
) -> Path:
    """§3.5 — `labels/{version}/labels.parquet`. B29: `.tmp` -> `fsync` ->
    `rename`, mesmo padrão de `src.exchange.filters.write_snapshot_atomic`
    e `src.data.validate.write_report_atomic` — adaptado para parquet:
    serializa para um buffer em memória primeiro (`write_parquet` não
    devolve um file descriptor que dê pra `fsync` diretamente), depois
    escreve os bytes através de um handle `wb` normal e faz `fsync` NESSE
    MESMO handle (reabrir o `.tmp` como `O_RDONLY` só para `fsync`, como uma
    versão anterior deste código fazia, falha no Windows com "Bad file
    descriptor" — medido no Sprint 6 rodando a série completa)."""
    out_dir = dest_dir if dest_dir is not None else (LABELS_OUTPUT_DIR / version)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_path = out_dir / "labels.parquet"
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")

    buffer = io.BytesIO()
    labels.write_parquet(buffer)
    with tmp_path.open("wb") as fh:
        fh.write(buffer.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("labels.written", path=str(dest_path), n_rows=labels.height)
    return dest_path
