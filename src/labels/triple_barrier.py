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
8. **Assimetria de fee no exit (`cost_exit_frac`) não é escolha deste
   módulo — é `§9.1` (PARTE IX, Execution Engine) traduzida.** `take_profit`
   é `LIMIT`/`GTC`/`reduce_only` (maker); `stop_loss` é `STOP_MARKET`/
   `working_type: MARK_PRICE` (taker — ordem algorítmica que não consome
   liquidez RPI, §9.5.1); `time_stop` é `MARKET reduce_only` (taker
   explícito). `barrier_hit == "TP"` mapeia para `maker_fee`; `SL` e `TIME`
   caem no mesmo ramo `else` porque os dois exigem execução garantida via
   ordem agressiva — não porque compartilham qualquer outra semântica.

**Reuso, não reimplementação — e injetável (2026-08-12).** O estimador de
volatilidade que dimensiona TP/SL não é mais hardcoded em `group_c.
c01_atr_20`/`c02_atr_20_pct` — `build_labels`/`build_labels_both_sides`
recebem um `estimator: VolatilityEstimator | None` opcional
(`src.features.volatility`), default `ATRWilderEstimator(window=cfg.
atr_window)` (bit-idêntico ao comportamento anterior a esta mudança — o
golden test `test_atr_wilder_estimator_bate_bit_exato_com_labels_v1`
continua batendo `labels/v1/labels.parquet::atr_at_t0` sem alteração).
Isto fecha a lacuna que `src/features/volatility.py` (T0.1) deixou aberta
desde a criação da interface: "a migração completa dos 135 pontos de
fan-in (G-C0-2) é trabalho subsequente" — este é o ponto de fan-in de
maior criticidade (dimensiona `tp_price`/`sl_price`/`mfe_atr_units`/
`atr_at_t0` de PRODUÇÃO), agora migrado.

**`LabelConfig.estimator_id` é campo OBRIGATÓRIO, sem default mágico.**
Cogitei um default auto-derivado de `atr_window` (`f"atr_wilder_w
{atr_window}"`), mas isso quebra silenciosamente sob `dataclasses.
replace(cfg, atr_window=novo)` — o `estimator_id` ficaria desatualizado
(ainda citando o `atr_window` antigo) sem nenhum erro, exatamente o tipo
de drift silencioso que B15 existe para impedir. Melhor exigir explícito
(mesma disciplina de `tp_atr_mult`/`sl_atr_mult`/etc.) do que inventar
conveniência que esconde um bug depois. `build_labels` valida em runtime
que `estimator.estimator_id == cfg.estimator_id` -- se um chamador passar
um `GarmanKlassEstimator` mas esquecer de atualizar `cfg.estimator_id`,
o hash persistido MENTIRIA sobre qual estimador gerou o label (B15); isso
levanta `ValueError` em vez de deixar passar.

`load_filters_asof` vem de `src.exchange.filters`, inalterado.
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
from src.features.volatility import ATRWilderEstimator, Bars, VolatilityEstimator

from . import fill_model, weights
from ._constants import load_constant
from ._paths import LABELS_OUTPUT_DIR

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]

DateLike = date | str

# AG-005 (audit/architecture_gaps_log.yaml) — até esta correção, `_BAR_MS`
# era uma constante de MÓDULO fixa em `step_ms("15m")`, usada em TODA a
# aritmética de horizonte/fill/n_bars_held, mesmo já existindo
# `LabelConfig.decision_tf_minutes` (que só alimentava o estimador de
# volatilidade, ver `atr_pct` abaixo — nunca fill/horizonte). Rodar M2/M3
# (PRD_V4_1.md §3.2, 30m/1h) mudando só `decision_tf_minutes` produziria
# fill/horizonte calculados em milissegundos de 15m — bug silencioso, mesma
# classe do AG-004 já corrigido em `src.validation.cpcv` (ver esse arquivo,
# padrão de referência). Correção: `decision_tf_minutes: int` (minutos,
# sem validação — nada impedia `decision_tf_minutes=45`, que não
# corresponde a TF real algum) vira `LabelConfig.tf: str` (mesmo padrão de
# `CPCVConfig.tf`), validado por `step_ms` no `__post_init__` — reconstruir
# a string a partir do int seria frágil (`1h` != `60m`, `_TIMEFRAME_MINUTES`
# não é bijetivo por nome). `_BAR_MS` de módulo é substituído por
# `bar_ms = step_ms(cfg.tf)`, calculado por chamada em `build_labels`.
# Default "15m" preserva todo caller existente bit-exato.
_DEFAULT_TF: Final[str] = "15m"

# Fato de calendário (ms por minuto) — mesma categoria de
# `resample._MS_PER_MINUTE` (privada lá; duplicada aqui, mesmo padrão de
# `barrier_sweep._MINUTE_MS`, em vez de expor uma constante só para isto).
# Único uso: `VolatilityEstimator.estimate`/`Bars` (`src.features.
# volatility`) exigem `timeframe_minutes: int`, não falam a linguagem de
# string de TF que `step_ms` fala.
_MINUTE_MS: Final[int] = 60_000

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
    Sprint 6 (ver `constants.yaml`).

    `estimator_id` (2026-08-12) identifica qual `VolatilityEstimator`
    dimensiona TP/SL — OBRIGATÓRIO, sem default (ver docstring do módulo
    sobre por que um default auto-derivado de `atr_window` seria inseguro
    sob `dataclasses.replace`). `build_labels` valida em runtime que o
    `estimator` de fato passado bate com este campo.

    `tf` (AG-005, substitui `decision_tf_minutes: int`) é o TF de decisão —
    NÃO é constante de domínio (não vem de `constants.yaml`, mesmo
    raciocínio de `CPCVConfig.tf`): é parâmetro de execução. Determina
    `step_ms(tf)` em TODA a aritmética de horizonte/fill/n_bars_held de
    `build_labels`, e `timeframe_minutes` passado ao `VolatilityEstimator`.
    Validado (`UnsupportedTimeframeError` se desconhecido) no
    `__post_init__`. Default `"15m"` preserva todo caller existente
    bit-exato."""

    tp_atr_mult: float
    sl_atr_mult: float
    time_stop_bars: int
    fill_timeout_bars: int
    atr_window: int
    maker_fee: float
    taker_fee: float
    estimator_id: str
    tf: str = _DEFAULT_TF

    def __post_init__(self) -> None:
        # step_ms levanta UnsupportedTimeframeError pra tf desconhecido --
        # falha alto aqui, na construção, em vez de silenciosamente mais
        # tarde dentro de build_labels (mesma disciplina de
        # CPCVConfig.__post_init__, AG-004).
        step_ms(self.tf)

    @classmethod
    def from_constants(
        cls, *, estimator_id: str | None = None, tf: str = _DEFAULT_TF
    ) -> LabelConfig:
        """`estimator_id=None` (default) resolve para `ATRWilderEstimator`
        no `atr_window` lido de `constants.yaml` — o estimador de produção
        atual, comportamento inalterado desde antes desta classe existir.
        Passar um `estimator_id` explícito (e o `estimator` correspondente
        para `build_labels`) é como um chamador optaria por outro
        estimador (ex. `GarmanKlassEstimator`, vencedor de M1 — ainda não
        promovido a canônico, ver `docs/refactor_gk_canonico.md`).

        `tf` (AG-005) não vem de `constants.yaml` — mesmo raciocínio de
        `CPCVConfig.from_constants(*, tf=...)`, é parâmetro de execução do
        chamador (M2/M3 rodando 30m/1h passam `tf="30m"`/`tf="1h"` aqui),
        não um valor medido/otimizado do domínio."""
        atr_window = int(load_constant("atr_window"))
        resolved_estimator_id = (
            estimator_id if estimator_id is not None else f"atr_wilder_w{atr_window}"
        )
        return cls(
            tp_atr_mult=float(load_constant("tp_atr_mult")),
            sl_atr_mult=float(load_constant("sl_atr_mult")),
            time_stop_bars=int(load_constant("time_stop_bars")),
            fill_timeout_bars=int(load_constant("fill_timeout_bars")),
            atr_window=atr_window,
            maker_fee=float(load_constant("maker_fee")),
            taker_fee=float(load_constant("taker_fee")),
            estimator_id=resolved_estimator_id,
            tf=tf,
        )

    @property
    def config_hash(self) -> str:
        """Hash determinístico (sha256, truncado a 16 hex) do bloco de
        barreiras — muda se QUALQUER campo mudar. `orjson` com chaves
        ordenadas garante que o mesmo conjunto de valores sempre produz o
        mesmo hash, independente da ordem de construção do dataclass.

        **Muda de valor pra configs pré-2026-08-12** (mesmo com
        `ATRWilderEstimator`/`atr_window` idênticos) porque `estimator_id`
        é campo novo no payload — intencional, não regressão: antes desta
        mudança o hash não tinha como capturar "qual estimador" porque só
        existia um. `labels/v1/labels.parquet` (gerado sob o hash antigo)
        continua válido como está; precisa de reprocessamento só se for
        recombinado com uma config nova para verificação B15.

        **Muda de valor de novo com AG-005** (payload key
        `decision_tf_minutes` -> `tf`, mesmo default `"15m"`/`15`
        semanticamente) — mesma categoria de mudança intencional, mesmo
        motivo: um `config_hash` antigo comparado contra um novo já
        divergiria por `estimator_id`; este campo não reabre nenhuma
        janela de comparação que já não estivesse fechada."""
        payload = {
            "tp_atr_mult": self.tp_atr_mult,
            "sl_atr_mult": self.sl_atr_mult,
            "time_stop_bars": self.time_stop_bars,
            "fill_timeout_bars": self.fill_timeout_bars,
            "atr_window": self.atr_window,
            "maker_fee": self.maker_fee,
            "taker_fee": self.taker_fee,
            "estimator_id": self.estimator_id,
            "tf": self.tf,
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
    mfe_price: float  # melhor preço favorável até o toque (inclusive) — ver mfe_atr_units


def _mfe_price(
    path_high: FloatArray, path_low: FloatArray, side: int, end_idx_inclusive: int
) -> float:
    """Excursão favorável máxima, em PREÇO bruto (não normalizado por ATR
    ainda — isso é responsabilidade de `build_labels`, que tem `fill_px`/
    `atr_pct_i` em escopo). `side=1` (long): o melhor preço é o MAIOR high
    até `end_idx_inclusive`; `side=-1` (short): o MENOR low. MESMA janela
    de `path_high`/`path_low` que `_first_barrier_touch` já varreu para
    achar o toque — reuso do laço, não recomputação à parte (D3, Faixa 2)."""
    if side == 1:
        return float(np.max(path_high[: end_idx_inclusive + 1]))
    return float(np.min(path_low[: end_idx_inclusive + 1]))


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
        mfe = _mfe_price(path_high, path_low, side, path_high.shape[0] - 1)
        return _BarrierTouch("TIME", horizon_end_ms, float(path_close[-1]), False, mfe)

    if sl_idx == -1 or (tp_idx != -1 and tp_idx < sl_idx):
        mfe = _mfe_price(path_high, path_low, side, tp_idx)
        return _BarrierTouch("TP", int(path_time[tp_idx]), tp_price, False, mfe)

    if tp_idx == -1 or (sl_idx != -1 and sl_idx < tp_idx):
        mfe = _mfe_price(path_high, path_low, side, sl_idx)
        return _BarrierTouch("SL", int(path_time[sl_idx]), sl_price, False, mfe)

    # tp_idx == sl_idx: TP e SL tocados no MESMO candle de 1m — resíduo de
    # B11 em escala menor (ver docstring do módulo, item 5). Resolvido por
    # proximidade ao `open` do candle.
    k = tp_idx
    dist_tp = abs(path_open[k] - tp_price)
    dist_sl = abs(path_open[k] - sl_price)
    mfe = _mfe_price(path_high, path_low, side, k)
    if dist_tp <= dist_sl:
        return _BarrierTouch("TP", int(path_time[k]), tp_price, True, mfe)
    return _BarrierTouch("SL", int(path_time[k]), sl_price, True, mfe)


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
    "mfe_atr_units": pl.Float64,
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
    "mfe_atr_units",
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
    cols["mfe_atr_units"].append(None)
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
    estimator: VolatilityEstimator | None = None,
    historical_filters_fallback: bool = False,
) -> pl.DataFrame:
    """Núcleo do Label Engine (§3.4) para UM lado (`side=1` long, `side=-1`
    short — ver item 1 da docstring do módulo).

    `bars_15m`: klines REGULARES (não mark) a 15m — schema de
    `src.data.resample.resample_klines` (`open_time`, `close_time`, `open`,
    `high`, `low`, `close`, ...). `close` vira `entry_ref`; `open`/`high`/
    `low`/`close` alimentam o `estimator` (§0.2 R1/R2) que dimensiona TP/SL
    — NUNCA usados para decidir toque de barreira (isso é só `mark_1m`, B11).

    `mark_1m`: schema `MARK_PRICE_KLINES_1M` (klines-like, `open_time`
    epoch ms, `open`/`high`/`low`/`close`) — fonte OBRIGATÓRIA de toque de
    barreira e de fill (B11).

    `funding`: schema `FUNDING` (`calc_time` epoch ms, `last_funding_rate`).

    `estimator` (`None` default) resolve para `ATRWilderEstimator(window=
    cfg.atr_window)` — comportamento de produção inalterado. Passar outro
    `VolatilityEstimator` (`src.features.volatility`) exige que
    `cfg.estimator_id` bata com `estimator.estimator_id`, ou levanta
    `ValueError` (ver docstring do módulo/`LabelConfig`) — nunca deixa o
    `config_hash` persistido mentir sobre qual estimador rodou.

    Retorna o schema pré-pesos (sem `concurrency`/`uniqueness`/
    `sample_weight` — essas exigem o conjunto completo do lado, calculadas
    em `weights.apply_weights` por `build_labels_both_sides`)."""
    if side not in (1, -1):
        raise ValueError(f"side deve ser 1 (long) ou -1 (short), recebido {side}")
    cfg = config if config is not None else LabelConfig.from_constants()
    resolved_estimator = (
        estimator if estimator is not None else ATRWilderEstimator(window=cfg.atr_window)
    )
    if resolved_estimator.estimator_id != cfg.estimator_id:
        raise ValueError(
            f"estimator.estimator_id ({resolved_estimator.estimator_id!r}) != "
            f"cfg.estimator_id ({cfg.estimator_id!r}) -- o config_hash persistido "
            "mentiria sobre qual estimador gerou estes labels (B15). Passe um "
            "LabelConfig com estimator_id igual ao de `estimator`."
        )

    bars = bars_15m.sort("open_time")
    n = bars.height
    if n == 0:
        return _empty_pre_weight_frame()

    close = bars["close"].cast(pl.Float64).to_numpy()
    high = bars["high"].cast(pl.Float64).to_numpy()
    low = bars["low"].cast(pl.Float64).to_numpy()
    t0_arr = bars["close_time"].cast(pl.Int64).to_numpy().astype(np.int64)

    # AG-005 -- `bar_ms` substitui a antiga constante de módulo `_BAR_MS`
    # (fixa em 15m); TODA a aritmética de horizonte/fill/n_bars_held abaixo
    # usa isto, não mais um literal. `tf_minutes` é só pra falar a
    # linguagem (`timeframe_minutes: int`) que `Bars`/`VolatilityEstimator`
    # exigem (src.features.volatility) -- mesmo `cfg.tf`, unidade diferente.
    bar_ms = step_ms(cfg.tf)
    tf_minutes = bar_ms // _MINUTE_MS  # noqa: unguarded-ratio -- _MINUTE_MS é Final[int]=60_000, nunca 0

    # `estimator.estimate()` já retorna fração do preço (mesma escala que
    # `atr_pct` sempre teve) -- 2026-08-12, ver docstring do módulo.
    atr_pct = resolved_estimator.estimate(
        Bars(frame=bars, timeframe_minutes=tf_minutes),
        horizon_minutes=tf_minutes,
    )
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

        fill_horizon_ms = t_post + cfg.fill_timeout_bars * bar_ms
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

        horizon_end_ms = t0 + cfg.time_stop_bars * bar_ms
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
        n_bars_held = int(np.ceil((t1 - t0) / bar_ms)) if t1 > t0 else 0

        # D3 (Faixa 2) — excursão favorável máxima, em unidades de ATR (mesma
        # normalização de tp_price/sl_price: `fill_px * mult * atr_pct_i`).
        # Sanidade esperada: se barrier=="TP", mfe_atr_units >= tp_atr_mult
        # por construção (o toque QUE definiu TP já é >= tp_price).
        atr_unit_price = fill_px * atr_pct_i
        mfe_atr_units = (
            side * (touch.mfe_price - fill_px) / atr_unit_price
            if atr_unit_price > 0
            else float("nan")
        )

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
        cols["mfe_atr_units"].append(mfe_atr_units)
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
    estimator: VolatilityEstimator | None = None,
    historical_filters_fallback: bool = False,
) -> pl.DataFrame:
    """Roda `build_labels` para os dois lados (M_long `side=1`, M_short
    `side=-1` — B18) e aplica `weights.apply_weights` sobre o conjunto
    combinado (concorrência/unicidade por lado, peso normalizado
    globalmente — item 7 da docstring do módulo). Retorna já no schema
    final exato de `labels/{version}/labels.parquet` (`LABEL_COLUMNS`).

    `estimator` (ver `build_labels`) é resolvido UMA vez aqui e passado
    IDÊNTICO aos dois lados -- long e short compartilham o mesmo
    dimensionamento de volatilidade por construção (§3.4), nunca
    estimadores diferentes por lado."""
    cfg = config if config is not None else LabelConfig.from_constants()

    long_labels = build_labels(
        bars_15m,
        mark_1m,
        funding,
        side=1,
        symbol=symbol,
        config=cfg,
        estimator=estimator,
        historical_filters_fallback=historical_filters_fallback,
    )
    short_labels = build_labels(
        bars_15m,
        mark_1m,
        funding,
        side=-1,
        symbol=symbol,
        config=cfg,
        estimator=estimator,
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
    estimator: VolatilityEstimator | None = None,
    historical_filters_fallback: bool = False,
) -> pl.DataFrame:
    """Ponto de entrada com IO — análogo a
    `features.build.build_t1_features(symbol, start, end)`. Carrega klines
    regulares no TF de decisão (`cfg.tf`, `entry_ref`/estimador de
    volatilidade), `mark_1m` e `funding` via `src.data.lake` (reuso, não
    reimplementação).

    **AG-005** — não existe parâmetro `tf` separado aqui de propósito: o TF
    já entra pela config (`config.tf`, default `"15m"`), a mesma fonte que
    `build_labels` usa pra toda a aritmética de horizonte. Um segundo
    parâmetro `tf` paralelo a `config.tf` recriaria exatamente a classe de
    bug que este achado corrige (duas fontes de verdade pro mesmo TF que
    podem divergir) — `lake.query_bars(symbol, cfg.tf, ...)` usa
    `cfg.tf` diretamente, não mais `"15m"` literal.

    `bars_15m` continua carregado no TF de DECISÃO (`cfg.tf`) — o nome do
    parâmetro é histórico (mantido por compat com `build_labels`/
    `build_labels_both_sides`, que também o chamam assim), não significa
    literalmente 15 minutos.

    `mark_1m` continua SEMPRE carregado em granularidade nativa de 1
    minuto, independente de `cfg.tf` — isto NÃO é o mesmo hardcode do
    AG-005: B11 exige que o toque de barreira seja resolvido na resolução
    mais fina disponível, em ordem cronológica real (docstring do módulo,
    regra dura B11), nunca na resolução da barra de decisão. Mudar `cfg.tf`
    muda QUANDO uma decisão é tomada e o horizonte em ms de fill/time-stop
    — nunca a granularidade em que TP/SL são detectados. Fora de escopo
    desta correção, documentado explicitamente em vez de deixado implícito.

    `mark_1m`/`funding` são buscados com folga ALÉM de `end` — o suficiente
    pra cobrir `max(time_stop_bars, fill_timeout_bars) * step_ms(cfg.tf)`
    (o maior horizonte possível no TF pedido) MAIS 1 dia de margem extra.
    Antes do AG-005 a folga era um "1 dia" fixo, calibrado só pro caso 15m
    (`time_stop_bars=32 * 15m = 8h`, bem abaixo de 24h) — em 1h
    (`32 * 1h = 32h`) essa folga fixa seria insuficiente e descartaria
    labels reais por "cauda incompleta" silenciosamente (bloqueador real
    pra M2/M3, PRD_V4_1.md §3.2). Sem isso, os últimos labels do intervalo
    pedido seriam descartados apesar do dado existir logo depois de `end`.

    `estimator=None` (default) preserva o comportamento de produção atual
    (`ATRWilderEstimator`, ver `build_labels`). Este é o ÚNICO ponto de
    entrada real com IO deste módulo -- é aqui que promover GK a canônico
    de fato aconteceria (`docs/refactor_gk_canonico.md`), passando
    `estimator=GarmanKlassEstimator(window=cfg.atr_window)` e um `config`
    com `estimator_id="garman_klass_w{window}"` -- NÃO feito por padrão
    aqui, decisão explícita pendente de quem chama."""
    cfg = config if config is not None else LabelConfig.from_constants()

    bars_15m = lake.query_bars(symbol, cfg.tf, start, end, source="klines_1m", cast_prices=True)

    horizon_ms = max(cfg.time_stop_bars, cfg.fill_timeout_bars) * step_ms(cfg.tf)
    mark_end = _as_date(end) + timedelta(milliseconds=horizon_ms, days=1)
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
        estimator=estimator,
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
