"""Resolução de barreira vetorizada via `sliding_window_view` — §18.7.1,
Faixa 2 E1 ("nunca implementado" até esta rodada).

**Por que isto existe, separado de `triple_barrier.build_labels`.**
`build_labels` resolve TP/SL/TIME num laço Python por barra (rápido o
bastante para RODAR uma vez — medido em `src.analysis.cost_surface`,
~50-60s por lado por configuração completa —, mas o pseudocódigo §18.7.1
pede especificamente vetorização via `sliding_window_view` para a
VARREDURA de grade, não só velocidade: é dívida técnica registrada, paga
aqui). `build_labels` continua sendo o motor canônico de produção
(`labels/v1/labels.parquet`) — este módulo não o substitui, é usado só
pela Faixa 2 E1 para varrer `tp_atr_mult`/`sl_atr_mult` sem re-rodar o
Label Engine inteiro 18 vezes.

**O insight que torna a varredura barata: o FILL não depende de
`tp_atr_mult`/`sl_atr_mult`.** Em `triple_barrier.build_labels`, a chamada
a `fill_model.simulate_fill_arrays` (decide SE/QUANDO a ordem limite
preenche) acontece ANTES de qualquer referência a `tp_price`/`sl_price` —
depende só de `limit_price` (função de `entry_ref`/tick, não de barreira)
e `fill_timeout_bars`. Logo, para varrer um grid de tp/sl com
`fill_timeout_bars`/`time_stop_ms`/`atr_window` FIXOS (o caso de E1), o
fill de cada trade só precisa existir UMA VEZ — reusado de
`labels/v1/labels.parquet` (a config de produção atual já tem essa
informação: `t_entry`, `entry_price_fill`, `atr_at_t0`, `barrier_hit ==
"NOFILL"`). Este módulo resolve SÓ a barreira (TP/SL/TIME) para cada
célula do grid, vetorizado sobre TODOS os trades preenchidos de uma vez —
`NOFILL` e sua contagem são IDÊNTICOS em todas as células do grid (mesmo
fill, qualquer tp/sl), não recalculados aqui.

**Correção que a vetorização precisa preservar** (mesma semântica de
`triple_barrier._first_barrier_touch`, verificada por
`tests/unit/test_labels_barrier_sweep.py::test_reproduz_build_labels_*`):
primeiro toque em ORDEM CRONOLÓGICA real (B11), desempate TP=SL no mesmo
candle por proximidade ao `open`, `TIME` quando nenhum toca, `t1` de
`TIME` é `horizon_end_ms` exato (não o último bar da janela).

**AG-005 (audit/architecture_gaps_log.yaml)** — até esta correção, `_BAR_MS`
era uma constante de MÓDULO fixa em `15 * 60_000` (15m), CÓPIA independente
da mesma constante que existia em `triple_barrier.py` — as duas hardcodavam
o mesmo fato de calendário em dois lugares, sem nenhum campo de TF em
`resolve_barriers_vectorized`. Rodar a varredura de grade sobre labels de
M2/M3 (30m/1h, PRD_V4_1.md §3.2) produziria `horizon_end`/`n_bars_held`
calculados em milissegundos de 15m — bug silencioso, mesma classe do AG-004
já corrigido em `src.validation.cpcv` (padrão de referência). Correção:
`resolve_barriers_vectorized` ganha `tf: str = "15m"` (mesmo default de
`LabelConfig.tf`/`CPCVConfig.tf` — bit-exato pra todo caller existente,
nenhum passa `tf` hoje), validado via `step_ms(tf)` no início da função
(falha alto, `UnsupportedTimeframeError`, antes de qualquer cálculo).

**AG-031/B1 (audit/architecture_gaps_log.yaml)** — `time_stop_bars`
(contagem de barra) vira `time_stop_ms` (relógio fixo), mesmo motivo/mesma
correção de `triple_barrier.build_labels` (ver comentário de módulo lá):
duas interpretações incompatíveis do mesmo parâmetro coexistiam no repo,
PRD já decidia relógio fixo 3x antes do bug. `horizon_end = t0 +
time_stop_ms` direto. `window_bars` (tamanho da janela vetorizada, em
barras de 1m de `mark_1m`) deixa de passar por `time_stop_bars *
bars_per_decision_bar` — deriva direto de `time_stop_ms // _MINUTE_MS`,
sem depender de `bar_ms`/contagem de barra de decisão nenhuma.
`n_bars_held` ganha o parâmetro OPCIONAL `decision_bar_close_time_ms` —
quando fornecido, vira contagem real (busca, paridade com
`build_labels`); `None` (default) mantém a aritmética antiga, usada pelo
único caller real hoje (`faixa2_caminho_b.py`, que não carrega `bars_15m`
nem consome esse campo).

**AG-042 (2026-08-17) — fora do escopo da migração dollar-bar,
explicitamente, não por esquecimento.** Confirmado por grep: o único
caller real de `resolve_barriers_vectorized` continua sendo
`src.analysis.faixa2_caminho_b` — `src/analysis/` não pode virar insumo
de treino/validação (`CLAUDE.md`, contrato de camada) e está fora do
plano de migração de produção (`docs/refactor_parkinson_canonico.md`).
Este módulo não ganha `resolution_id`/suporte a dollar bar nesta leva —
se um caller de produção real precisar dele sob grade dollar-bar no
futuro, aplica-se o mesmo tratamento já dado a `triple_barrier.py`
(`tf`/`resolution_id` XOR), não antes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import polars as pl
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from src.data.resample import step_ms

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

_MINUTE_MS: Final[int] = 60_000
_BPS_PER_UNIT: Final[int] = 10_000
_TP = "TP"
_SL = "SL"
_TIME = "TIME"

# Margem de segurança do tamanho da janela (em barras de 1m) além de
# `time_stop_ms // _MINUTE_MS` (AG-031/B1) — cobre gaps eventuais do mark_1m (já documentados
# em outras partes do repo, ex. Data Quality Engine) sem mudar o resultado:
# a janela em si é MASCARADA por comparação de timestamp real
# (`horizon_end_ms`), não por contagem de barra — a margem só garante que
# a janela vetorizada tenha barras suficientes pra cobrir o horizonte de
# tempo mesmo com alguma barra faltante no meio. Decisão de engenharia,
# não parâmetro de domínio (mesma categoria de `_DATE_BUFFER_DAYS` em
# `src.models.dataset`).
_WINDOW_SAFETY_MARGIN_BARS: Final[int] = 60  # noqa: magic-number


@dataclass(frozen=True, slots=True)
class ResolvedBarriers:
    """Uma célula do grid, um lado — resultado alinhado posicionalmente à
    `filled` de entrada (mesma ordem de linhas)."""

    barrier_hit: list[str]
    t1_ms: IntArray
    exit_price: FloatArray
    ret_gross: FloatArray
    cost_entry_bps: FloatArray
    cost_exit_bps: FloatArray
    funding_bps: FloatArray
    ret_net: FloatArray
    n_bars_held: IntArray
    tie_break_used: BoolArray


def _pad_for_windows(arr: FloatArray, *, pad_bars: int, fill_value: float) -> FloatArray:
    return np.concatenate([arr, np.full(pad_bars, fill_value, dtype=np.float64)])


def _pad_int_for_windows(arr: IntArray, *, pad_bars: int, fill_value: int) -> IntArray:
    return np.concatenate([arr, np.full(pad_bars, fill_value, dtype=np.int64)])


def resolve_barriers_vectorized(
    filled: pl.DataFrame,
    mark_1m: pl.DataFrame,
    funding: pl.DataFrame,
    *,
    side: int,
    tp_atr_mult: float,
    sl_atr_mult: float,
    time_stop_ms: int,
    maker_fee: float,
    taker_fee: float,
    tf: str = "15m",
    decision_bar_close_time_ms: IntArray | None = None,
) -> ResolvedBarriers:
    """`filled`: trades JÁ preenchidos de UM lado (`barrier_hit != "NOFILL"`
    numa config qualquer — `t_entry`/`entry_price_fill`/`atr_at_t0`/`t0` não
    dependem de tp/sl, ver docstring do módulo), colunas `t0`, `t_entry`,
    `entry_price_fill`, `atr_at_t0`, todas não-nulas. `mark_1m`/`funding`:
    mesmo schema de `triple_barrier.build_labels`. Vetorizado via
    `sliding_window_view` sobre `mark_1m` — sem laço Python por trade.

    `time_stop_ms` (AG-031/B1) é o horizonte do label em RELÓGIO fixo —
    mesma convenção de `LabelConfig.time_stop_ms`, precisa ser o MESMO
    valor usado para gerar `filled`.

    `tf` (AG-005, default `"15m"`) é o TF de DECISÃO de `filled` — precisa
    ser o MESMO `LabelConfig.tf` usado para gerar `filled` (`t0`/`t1`/
    `n_bars_held` de `filled` já foram calculados sob esse TF por
    `triple_barrier.build_labels`); nenhuma validação cruzada automática
    entre os dois hoje, responsabilidade do chamador, mesma ressalva já
    documentada em `CPCVConfig`/`load_labels_v1` (`src.validation.cpcv`).
    `mark_1m` continua granularidade nativa de 1 minuto independente de
    `tf` — mesmo raciocínio de B11 em `triple_barrier.build_labels_for_
    symbol` (toque de barreira sempre na resolução mais fina disponível).

    `decision_bar_close_time_ms` (AG-031/B1, opcional) é o array de
    `close_time` (ms) das barras de DECISÃO (`bars_15m`, mesmas que geraram
    `filled`) — quando fornecido, `n_bars_held` vira contagem REAL (busca
    neste array), mesma lógica de `triple_barrier.build_labels`, com
    paridade garantida (`test_reproduz_build_labels_*` passa este array).
    `None` (default) cai pra aritmética `ceil((t1-t0)/bar_ms)` — usada por
    `src.analysis.faixa2_caminho_b`, que não carrega `bars_15m` (só reusa
    `t_entry`/`atr_at_t0` já persistidos) e não consome `n_bars_held` do
    resultado; nesse caller a aproximação é aceitável.

    Levanta `ValueError` se qualquer trade não tiver janela completa até
    `horizon_end_ms` no `mark_1m` fornecido (equivalente ao
    `n_incomplete_tail` de `build_labels` — aqui é erro, não skip
    silencioso, porque `filled` já deveria vir de trades com cauda
    completa, dado que se originam de `labels/v1/labels.parquet`)."""
    bar_ms = step_ms(tf)  # UnsupportedTimeframeError falha alto se tf desconhecido
    n = filled.height
    t0 = filled["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    t_entry = filled["t_entry"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    fill_px = filled["entry_price_fill"].to_numpy().astype(np.float64)
    atr_pct = filled["atr_at_t0"].to_numpy().astype(np.float64)
    horizon_end = t0 + time_stop_ms  # AG-031/B1 -- relógio fixo, não mais * bar_ms

    mark = mark_1m.sort("open_time")
    mark_open_time = mark["open_time"].cast(pl.Int64).to_numpy().astype(np.int64)
    mark_open = mark["open"].cast(pl.Float64).to_numpy().astype(np.float64)
    mark_high = mark["high"].cast(pl.Float64).to_numpy().astype(np.float64)
    mark_low = mark["low"].cast(pl.Float64).to_numpy().astype(np.float64)
    mark_close = mark["close"].cast(pl.Float64).to_numpy().astype(np.float64)

    # AG-031/B1 -- janela em barras de 1m derivada direto do relógio
    # (`time_stop_ms // _MINUTE_MS`), sem passar por contagem de barra de
    # decisão nenhuma (`bars_per_decision_bar` não existe mais aqui).
    window_bars = -(-time_stop_ms // _MINUTE_MS) + _WINDOW_SAFETY_MARGIN_BARS  # noqa: unguarded-ratio -- _MINUTE_MS é Final[int]=60_000, nunca 0
    start_idx = np.searchsorted(mark_open_time, t_entry, side="left")
    if start_idx.size and int(np.max(start_idx)) + window_bars > mark_open_time.shape[0]:
        # janela tocaria além do fim do array disponível -- preenche com
        # sentinelas seguros (tempo no "futuro distante", preço que nunca
        # dispara TP/SL) em vez de deixar sliding_window_view estourar.
        pad = window_bars
        mark_open_time_p = _pad_int_for_windows(
            mark_open_time, pad_bars=pad, fill_value=np.iinfo(np.int64).max
        )
        mark_open_p = _pad_for_windows(mark_open, pad_bars=pad, fill_value=float("nan"))
        mark_high_p = _pad_for_windows(mark_high, pad_bars=pad, fill_value=float("-inf"))
        mark_low_p = _pad_for_windows(mark_low, pad_bars=pad, fill_value=float("inf"))
        mark_close_p = _pad_for_windows(mark_close, pad_bars=pad, fill_value=float("nan"))
    else:
        mark_open_time_p, mark_open_p = mark_open_time, mark_open
        mark_high_p, mark_low_p, mark_close_p = mark_high, mark_low, mark_close

    time_w = sliding_window_view(mark_open_time_p, window_bars)[start_idx]
    open_w = sliding_window_view(mark_open_p, window_bars)[start_idx]
    high_w = sliding_window_view(mark_high_p, window_bars)[start_idx]
    low_w = sliding_window_view(mark_low_p, window_bars)[start_idx]
    close_w = sliding_window_view(mark_close_p, window_bars)[start_idx]

    valid_mask = time_w <= horizon_end[:, None]
    n_valid_bars = valid_mask.sum(axis=1)
    if n_valid_bars.size and int(np.min(n_valid_bars)) < 1:
        raise ValueError(
            "resolve_barriers_vectorized: pelo menos um trade não tem janela "
            "completa ate horizon_end_ms no mark_1m fornecido (cauda incompleta) "
            "-- filled deveria vir só de trades ja com cauda completa"
        )

    tp_price = fill_px * (1 + side * tp_atr_mult * atr_pct)
    sl_price = fill_px * (1 - side * sl_atr_mult * atr_pct)

    if side == 1:
        tp_touch = (high_w >= tp_price[:, None]) & valid_mask
        sl_touch = (low_w <= sl_price[:, None]) & valid_mask
    else:
        tp_touch = (low_w <= tp_price[:, None]) & valid_mask
        sl_touch = (high_w >= sl_price[:, None]) & valid_mask

    tp_any = tp_touch.any(axis=1)
    sl_any = sl_touch.any(axis=1)
    tp_idx = np.where(tp_any, np.argmax(tp_touch, axis=1), -1)
    sl_idx = np.where(sl_any, np.argmax(sl_touch, axis=1), -1)

    idx_range = np.arange(n)
    tie_mask = tp_any & sl_any & (tp_idx == sl_idx)
    open_at_tie = open_w[idx_range, np.where(tie_mask, tp_idx, 0)]
    tie_favors_tp = np.abs(open_at_tie - tp_price) <= np.abs(open_at_tie - sl_price)

    time_mask = (~tp_any) & (~sl_any)
    tie_tp_mask = tie_mask & tie_favors_tp
    tie_sl_mask = tie_mask & (~tie_favors_tp)
    remaining = (~time_mask) & (~tie_mask)
    tp_wins_mask = remaining & (~sl_any | (tp_any & (tp_idx < sl_idx)))
    sl_wins_mask = remaining & (~tp_wins_mask)

    touch_idx = np.select(
        [time_mask, tie_tp_mask, tie_sl_mask, tp_wins_mask, sl_wins_mask],
        [n_valid_bars - 1, tp_idx, sl_idx, tp_idx, sl_idx],
        default=-1,
    )
    barrier_code = np.select(
        [time_mask, tie_tp_mask | tp_wins_mask, tie_sl_mask | sl_wins_mask],
        [0, 1, 2],
        default=-1,
    )
    if int(np.min(barrier_code)) < 0:
        raise AssertionError(
            "resolve_barriers_vectorized: barrier_code nao coberto pelos 5 "
            "ramos mutuamente exclusivos -- bug de particionamento"
        )
    barrier_hit = np.select(
        [barrier_code == 0, barrier_code == 1, barrier_code == 2],
        [_TIME, _TP, _SL],
        default="",
    )

    t1 = np.where(time_mask, horizon_end, time_w[idx_range, touch_idx])
    exit_price = np.select(
        [barrier_code == 0, barrier_code == 1, barrier_code == 2],
        [close_w[idx_range, touch_idx], tp_price, sl_price],
    )
    tie_break_used = tie_mask

    ret_gross = side * (exit_price / fill_px - 1.0)
    cost_entry_frac = np.full(n, maker_fee, dtype=np.float64)
    cost_exit_frac = np.where(barrier_hit == _TP, maker_fee, taker_fee)

    fund = funding.sort("calc_time")
    fund_time = fund["calc_time"].cast(pl.Int64).to_numpy().astype(np.int64)
    fund_rate = fund["last_funding_rate"].cast(pl.Float64).fill_null(0.0).to_numpy().astype(
        np.float64
    )
    prefix = np.concatenate([[0.0], np.cumsum(fund_rate)])
    f_lo = np.searchsorted(fund_time, t_entry, side="left")
    f_hi = np.searchsorted(fund_time, t1, side="right")
    funding_frac = (prefix[f_hi] - prefix[f_lo]) * side

    ret_net = ret_gross - cost_entry_frac - cost_exit_frac - funding_frac

    if decision_bar_close_time_ms is not None and decision_bar_close_time_ms.size:
        # AG-031/B1 -- contagem REAL via busca em decision_bar_close_time_ms
        # (mesma lógica de triple_barrier.build_labels), com fallback
        # aritmético pra cauda além do último decision bar carregado.
        dbc = decision_bar_close_time_ms
        idx0 = np.searchsorted(dbc, t0, side="left")
        idx1_within = np.searchsorted(dbc, t1, side="right") - 1
        last_close = int(dbc[-1])
        within_range = t1 <= last_close
        real_count = np.where(
            within_range,
            idx1_within - idx0,
            (dbc.size - 1 - idx0) + np.ceil((t1 - last_close) / bar_ms).astype(np.int64),
        )
        n_bars_held = np.where(t1 > t0, real_count, 0)
    else:
        n_bars_held = np.where(t1 > t0, np.ceil((t1 - t0) / bar_ms).astype(np.int64), 0)

    return ResolvedBarriers(
        barrier_hit=list(barrier_hit),
        t1_ms=t1,
        exit_price=exit_price,
        ret_gross=ret_gross,
        cost_entry_bps=cost_entry_frac * _BPS_PER_UNIT,
        cost_exit_bps=cost_exit_frac * _BPS_PER_UNIT,
        funding_bps=funding_frac * _BPS_PER_UNIT,
        ret_net=ret_net,
        n_bars_held=n_bars_held,
        tie_break_used=tie_break_used,
    )
