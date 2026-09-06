"""AG-464 — a geometria de barreira fora da caixa do grid do S1.

**Por que este script existe.** Eu afirmei ao Manager que a geometria era
uma via FECHADA por medicao (AG-450/454). Errado, e a retratacao esta no
AG-464. O grid do S1 e `SL_MULT in {3/4, 3/2, 9/4}` x `R in {1, 4/3, 2}`;
a maior celula SIMETRICA que ele contem e `2,25/2,25` -- que foi o 1o
colocado em R2 e R3 depois da correcao do TP. O vencedor encostou na
parede do grid no eixo `sl`, e a docstring de `barrier_geometry.py`
declara o desenho: "verificacao de robustez AO REDOR do valor de producao
ja escolhido -- nao busca de novo otimo".

**A aritmetica que motiva olhar fora.** O custo e ~fixo em bps e a
barreira escala com `m`, entao o breakeven cai com `m` enquanto a win
rate INCONDICIONAL nao cai (P(TP) de martingale = 0,50 sob barreiras
simetricas, independente de `m` -- criterio ja usado no AG-229, e medido
aqui: SOLUSDT/R3 tem frac_TP = 50,76%). Breakeven calculado para
SOLUSDT/R3: 52,71% em m=1,5 | 51,81% em m=2,25 | 51,36% em m=3 |
51,02% em m=4 | 50,68% em m=6, contra alvo de 51,99%.

**A ressalva que este script existe pra testar, nao pra assumir.** Nada
disso vale se a barreira distante deixar de ser tocada dentro do
horizonte: saida `TIME` sai TAKER e nao e 50/50 de vencedores. Hoje
`TIME` e 0,05% dos trades (44 de 80.934) e o holding mediano e 1 barra
contra horizonte de 32 -- ha folga, mas folga medida em m=1,5, nao em
m=6. Por isso o grid aqui e CONJUNTO em (m, horizon_bars): as duas
constantes sao classe A e nunca foram varridas juntas.

**Defeito de janela corrigido aqui (ver AG-465).** `window_bars` de
`resolve_barriers_vectorized` deriva de `time_stop_ms` (540 min com o
valor de producao), mas sob dollar bar o horizonte real e `horizon_end_ms`
-- 32 barras R3, mediana 1.724 min, maximo 10.781. O `valid_mask` so
corta o que passa de `horizon_end`; ele nao detecta que a janela acabou
ANTES. Com `m` grande a busca seria truncada em 540 min e o resto viraria
`TIME` espurio -- mediria o proprio defeito. Aqui a janela e dimensionada
pelo span REAL do horizonte, por chunk de trades (memoria).

NAO altera nada de producao: escreve so
`experiments/ag464_geometria_fora_da_caixa.json`.

Uso:

    uv run python -m scripts.measure_ag464_geometria_fora_da_caixa
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from typing import Any

import numpy as np
import polars as pl
import structlog

from src.analysis.feasibility import breakeven_win_rate
from src.data import lake
from src.labels.barrier_geometry import SL_MULT_GRID
from src.labels.barrier_sweep import resolve_barriers_vectorized
from src.labels.triple_barrier import TP_TOUCH_SOURCE_MARK_1M, LabelConfig
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_SYMBOL = "SOLUSDT"
_RESOLUTION = "R3"
_SIDES: tuple[int, ...] = (1, -1)

#: Grade CONJUNTA declarada a priori. `m` simetrico (tp=sl=m): 1,50 e
#: producao, 2,25 e o teto do grid do S1, o resto e o territorio que
#: nunca foi olhado. `horizon_bars`: 32 e producao; 64/128 testam se a
#: barreira distante ainda e alcancada dentro do horizonte.
_M_GRID: tuple[float, ...] = (1.5, 2.25, 3.0, 4.0, 6.0)  # noqa: magic-number -- grade a priori, §16.10 regra 4
_HORIZON_GRID: tuple[int, ...] = (32, 64, 128)  # noqa: magic-number -- grade a priori, §16.10 regra 4

#: Trades por chunk. So controla memoria: a janela vetorizada e
#: `chunk x window_bars` floats, e `window_bars` chega a ~11k minutos sob
#: horizonte de 128 barras. Nao afeta resultado -- cada trade resolve na
#: sua propria janela, chunks sao independentes por construcao.
_CHUNK: int = 1500  # noqa: magic-number -- controle de memoria, nao parametro de dominio

_MARGIN_DAYS: int = 3  # noqa: magic-number -- mesma margem de s1_tp_sl_sensitivity
_MINUTE_MS: int = 60_000  # noqa: magic-number -- definicao de calendario
_BPS: float = 10_000.0  # noqa: magic-number -- definicao matematica
_PP: float = 100.0  # noqa: magic-number -- fracao -> ponto percentual, definicao matematica


def _resolve_chunked(
    filled: pl.DataFrame,
    mark_1m: pl.DataFrame,
    funding: pl.DataFrame,
    *,
    side: int,
    m: float,
    cfg: LabelConfig,
    horizon_end: np.ndarray,
    decision_close_ms: np.ndarray,
    last_1m: pl.DataFrame | None,
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """`(barrier_hit, ret_net, n_bars_held)` concatenados sobre chunks."""
    t_entry = filled["t_entry"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    hits: list[str] = []
    rets: list[np.ndarray] = []
    held: list[np.ndarray] = []
    for ini in range(0, filled.height, _CHUNK):
        fim = min(ini + _CHUNK, filled.height)
        sub = filled.slice(ini, fim - ini)
        h_sub = horizon_end[ini:fim]
        # Janela dimensionada pelo span REAL deste chunk (AG-465): sem
        # isto a busca trunca em `cfg.time_stop_ms` e fabrica `TIME`.
        span_ms = int(np.max(h_sub - t_entry[ini:fim]))
        res = resolve_barriers_vectorized(
            sub,
            mark_1m,
            funding,
            side=side,
            tp_atr_mult=m,
            sl_atr_mult=m,
            time_stop_ms=span_ms + _MINUTE_MS,
            maker_fee=cfg.maker_fee,
            taker_fee=cfg.taker_fee,
            adverse_selection_bps=cfg.adverse_selection_bps,
            last_1m=last_1m,
            tf=_RESOLUTION,
            decision_bar_close_time_ms=decision_close_ms,
            horizon_end_ms=h_sub,
        )
        hits.extend(res.barrier_hit)
        rets.append(res.ret_net)
        held.append(res.n_bars_held)
    return hits, np.concatenate(rets), np.concatenate(held)


def main(argv: list[str] | None = None) -> int:
    configure_logging(json_output=False)
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
    cfg = LabelConfig.from_constants(estimator_id=vol_estimator_id, resolution_id=_RESOLUTION)

    labels = pl.read_parquet(f"data/labels/{_SYMBOL}/{_RESOLUTION}/v1/labels.parquet")
    t0_min, t0_max = labels["t0"].min(), labels["t0"].max()
    start = (t0_min.date() - timedelta(days=_MARGIN_DAYS)).isoformat()  # type: ignore[union-attr]
    end = (t0_max.date() + timedelta(days=_MARGIN_DAYS)).isoformat()  # type: ignore[union-attr]
    mark_1m = lake.query_bars(
        _SYMBOL, "1m", start, end, source="mark_price_klines_1m", cast_prices=True
    )
    last_1m = (
        lake.query_bars(_SYMBOL, "1m", start, end, source="klines_1m", cast_prices=True)
        if cfg.tp_touch_source != TP_TOUCH_SOURCE_MARK_1M
        else None
    )
    funding = lake.query_funding(_SYMBOL, start, end)
    bars = lake.query_dollar_bars(_SYMBOL, start, end, resolution_id=_RESOLUTION)
    decision_close_ms = bars["close_time"].cast(pl.Int64).to_numpy().astype(np.int64)
    t0_grid = np.sort(labels["t0"].unique().dt.epoch(time_unit="ms").to_numpy().astype(np.int64))

    celulas: list[dict[str, Any]] = []
    for horizon_bars in _HORIZON_GRID:
        for m in _M_GRID:
            por_lado: dict[str, Any] = {}
            hits_all: list[str] = []
            rets_all: list[np.ndarray] = []
            held_all: list[np.ndarray] = []
            atrs: list[float] = []
            for side in _SIDES:
                filled = labels.filter(
                    (pl.col("side") == side) & (pl.col("barrier_hit") != "NOFILL")
                ).select(["t0", "t_entry", "entry_price_fill", "atr_at_t0"])
                if filled.is_empty():
                    continue
                _t0 = filled["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
                _idx = np.searchsorted(t0_grid, _t0, side="left") + horizon_bars
                _ok = _idx < t0_grid.shape[0]
                if not bool(_ok.all()):
                    filled = filled.filter(pl.Series(_ok))
                    _idx = _idx[_ok]
                horizon_end = t0_grid[_idx]

                hits, rets, held = _resolve_chunked(
                    filled,
                    mark_1m,
                    funding,
                    side=side,
                    m=m,
                    cfg=cfg,
                    horizon_end=horizon_end,
                    decision_close_ms=decision_close_ms,
                    last_1m=last_1m,
                )
                arr_lado = np.array(hits)
                por_lado[str(side)] = {
                    "n": int(arr_lado.size),
                    "frac_tp": float((arr_lado == "TP").mean()),
                    "frac_time": float((arr_lado == "TIME").mean()),
                    "ret_net_bps": float(rets.mean()) * _BPS,
                    "holding_mediano_bars": float(np.median(held)),
                }
                hits_all.extend(hits)
                rets_all.append(rets)
                held_all.append(held)
                atrs.append(float(filled["atr_at_t0"].to_numpy().mean()))

            arr = np.array(hits_all)
            ret_all = np.concatenate(rets_all)
            held_arr = np.concatenate(held_all)
            atr_med = float(np.mean(atrs))
            frac_tp = float((arr == "TP").mean())
            be = breakeven_win_rate(
                atr_pct=atr_med,
                tp_atr_mult=m,
                sl_atr_mult=m,
                maker_fee=cfg.maker_fee,
                taker_fee=cfg.taker_fee,
                adverse_selection_bps=cfg.adverse_selection_bps,
            )
            hold_med = float(np.median(held_arr))
            cel: dict[str, Any] = {
                "m": m,
                "horizon_bars": horizon_bars,
                "n": int(arr.size),
                "frac_tp": frac_tp,
                "frac_time": float((arr == "TIME").mean()),
                "breakeven": be,
                "gap_pp": (frac_tp - be) * _PP,
                "ret_net_bps_por_trade": float(ret_all.mean()) * _BPS,
                "holding_mediano_bars": hold_med,
                # AG-445 -- edge por unidade de TEMPO, nao so por trade: as
                # celulas resolvem em prazos muito diferentes e o custo e
                # pago por trade.
                "ret_net_bps_por_barra": (
                    float(ret_all.mean()) * _BPS / hold_med if hold_med > 0 else float("nan")
                ),
                "por_lado": por_lado,
            }
            celulas.append(cel)
            logger.info(
                "ag464.celula",
                m=m,
                horizon_bars=horizon_bars,
                n=cel["n"],
                frac_tp=round(frac_tp, 5),
                frac_time=round(float(cel["frac_time"]), 5),
                ret_trade=round(float(cel["ret_net_bps_por_trade"]), 3),
                ret_barra=round(float(cel["ret_net_bps_por_barra"]), 3),
                hold=hold_med,
            )

    destino = EXPERIMENTS_DIR / "ag464_geometria_fora_da_caixa.json"
    payload = {
        "task": "AG-464 -- geometria simetrica FORA da caixa do grid do S1, conjunta com horizonte",
        "symbol": _SYMBOL,
        "resolution_id": _RESOLUTION,
        "m_grid": list(_M_GRID),
        "horizon_grid": list(_HORIZON_GRID),
        # Lidos da FONTE, nunca reescritos como literal aqui: a geometria
        # de producao vem de `constants.yaml` e o teto simetrico do grid do
        # S1 e o maior `SL_MULT_GRID` (celula simetrica exige R=1). Assim o
        # artefato nao pode divergir do que o repo de fato usa.
        "producao": {
            "tp_atr_mult": float(load_constant("tp_atr_mult")),
            "sl_atr_mult": float(load_constant("sl_atr_mult")),
            "horizon_bars": int(load_constant("horizon_bars")),
        },
        "teto_do_grid_s1_simetrico": float(max(SL_MULT_GRID)),
        "nota": (
            "frac_tp e a win rate INCONDICIONAL da celula (piso de mercado, sem modelo). "
            "gap_pp = frac_tp - breakeven: quanto o modelo AINDA precisa adicionar. "
            "O lift medido out-of-time e +1,25pp (AG-461) -- celula com gap_pp > -1,25 "
            "e alcancavel pelo modelo que ja existe. ret_net_bps_por_barra e a funcao "
            "objetivo do AG-445 (edge por unidade de tempo), nao por trade."
        ),
        "celulas": celulas,
    }
    destino.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("ag464.gravado", path=str(destino), n_celulas=len(celulas))
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
