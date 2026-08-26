"""AG-221 — validação empírica: o viés de granularidade do fill de entrada
é recuperável trocando `mark_1m` por `agg_trades`?

**Medição PÓS-HOC** (`src/analysis/`, fora do contrato `importlinter` —
nunca insumo de treino/seleção de feature). Não reprocessa nenhum artefato
de produção, não escreve label nenhum: lê `labels.parquet` já materializado
e RECOMPUTA, sobre uma amostra de dias, o que teria acontecido se o fill de
ENTRADA tivesse sido resolvido com granularidade de trade.

**A pergunta.** `t_post` é o `close_time` da dollar bar (instante
arbitrário); `fill_model.simulate_fill_arrays` só oferece oportunidade de
fill em candles de `mark_1m` com `open_time` estritamente posterior. Isso
cria uma espera forçada uniformemente distribuída em `[0, 60s]` que não
existe em produção. `AG-221` mediu que `ret_gross` é função monotônica
dessa espera (-2,64 bps na faixa 0-10s contra -6,94 bps na faixa 50-60s) e
extrapolou `~-2,2 bps` para espera zero. **Extrapolação não é medição** —
este módulo mede.

**O que muda e o que NÃO muda.** Só a fonte do fill de ENTRADA. A
avaliação de barreira continua em `mark_1m` (B12: `working_type` é
`MARK_PRICE`, a barreira é sobre mark, não sobre trade). As barreiras
continuam derivadas de `fill_px` com os mesmos multiplicadores. As
simplificações do modelo de fill continuam idênticas (sem fila, sem
profundidade, `fill_price == limit_price`) — a ÚNICA variável que muda é a
granularidade temporal, para que a diferença medida seja atribuível a ela.

**Amostragem por DIA, não por barra** — deliberado. Barras amostradas
individualmente exigiriam carregar quase todos os 2.412 dias de
`agg_trades`; amostrar dias inteiros dá blocos contíguos (melhor para
dependência serial, mesma lógica de bootstrap por blocos do ADR-004 §5) e
reduz o IO por duas ordens de magnitude."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import structlog

from src.labels.fill_model import simulate_fill_from_trades
from src.labels.triple_barrier import _first_barrier_touch

logger = structlog.get_logger(__name__)

CAPACITY_DIR = Path("data/capacity")
LABELS_DIR = Path("data/labels")

# Amostra default. 200 dias x ~93 barras/dia x 2 lados ~ 37k observacoes;
# com std(ret_gross) ~ 37 bps (payoff +-1,5 ATR), o erro-padrao fica em
# ~0,2 bps -- uma ordem de magnitude abaixo do efeito de ~2 bps que se quer
# detectar. Nao e constante de dominio (nao entra em nenhuma decisao
# economica): e dimensionamento de amostra, derivado do efeito-alvo.
_DEFAULT_N_DAYS = 200
_DEFAULT_SEED = 42


@dataclass(frozen=True, slots=True)
class GranularityComparison:
    n_days: int
    n_barras: int
    # --- baseline: o que esta em labels.parquet (fill via mark_1m) ---
    base_n_fill: int
    base_pct_nofill: float
    base_delay_mediano_ms: float
    base_p_tp: float
    base_p_sl: float
    base_p_time: float
    base_ret_gross_bps: float
    # --- recomputado: fill via agg_trades ---
    novo_n_fill: int
    novo_pct_nofill: float
    novo_delay_mediano_ms: float
    novo_p_tp: float
    # `p_sl`/`p_time` NAO sao cosmeticos -- sao o diagnostico que pegou um
    # bug real deste proprio modulo (2026-08-25): a 1a versao usava
    # `t_post + time_stop_ms` como horizonte, mas sob resolution_id o
    # horizonte de producao e CONTAGEM DE BARRA (`t0_arr[i +
    # horizon_bars]`, AG-116). Sob R3 (barras lentas) 32 barras >> 8h,
    # entao o horizonte ficava truncado e gerava TIME artificial. O
    # sintoma visivel era P(TP) CAIR enquanto ret_gross MELHORAVA -- algo
    # quase impossivel sob payoff simetrico, e que so foi detectavel
    # porque as tres probabilidades sao reportadas juntas.
    novo_p_sl: float
    novo_p_time: float
    novo_ret_gross_bps: float
    # --- veredito ---
    delta_ret_gross_bps: float
    delta_p_tp: float


def _load_day_arrays(symbol: str, day: dt.date) -> tuple[Any, ...] | None:
    """`(trade_time, trade_price, mark_open_time, mark_open, mark_high,
    mark_low, mark_close)` para um dia, ou `None` se qualquer uma das duas
    fontes faltar. Carrega D e D+1 do mark (a janela de barreira atravessa
    a meia-noite) -- sem isso, toda barra do fim do dia cairia em janela
    vazia e sairia da amostra, enviesando por hora do dia."""
    agg_path = CAPACITY_DIR / "agg_trades" / symbol / f"{day.isoformat()}.parquet"
    if not agg_path.exists():
        return None
    trades = pl.read_parquet(agg_path, columns=["transact_time", "price"])

    mark_frames: list[pl.DataFrame] = []
    for offset in (0, 1):
        p = (
            CAPACITY_DIR
            / "mark_price_klines_1m"
            / symbol
            / f"{(day + dt.timedelta(days=offset)).isoformat()}.parquet"
        )
        if p.exists():
            mark_frames.append(
                pl.read_parquet(p, columns=["open_time", "open", "high", "low", "close"])
            )
    if not mark_frames:
        return None
    mark = pl.concat(mark_frames, how="vertical").sort("open_time")

    return (
        trades["transact_time"].to_numpy().astype(np.int64),
        trades["price"].to_numpy().astype(np.float64),
        mark["open_time"].to_numpy().astype(np.int64),
        mark["open"].cast(pl.Float64).to_numpy(),
        mark["high"].cast(pl.Float64).to_numpy(),
        mark["low"].cast(pl.Float64).to_numpy(),
        mark["close"].cast(pl.Float64).to_numpy(),
    )


def compare_fill_granularity(
    symbol: str = "BTCUSDT",
    resolution_id: str = "R1",
    *,
    n_days: int = _DEFAULT_N_DAYS,
    seed: int = _DEFAULT_SEED,
    fill_timeout_ms: int | None = None,
    tp_atr_mult: float | None = None,
    sl_atr_mult: float | None = None,
    time_stop_ms: int | None = None,
) -> GranularityComparison:
    """Recomputa o fill de entrada via `agg_trades` sobre uma amostra de
    dias e compara com o que está em `labels.parquet`.

    Os quatro parâmetros de config default para `constants.yaml` — passá-los
    explicitamente serve só para teste com fixture sintética."""
    from src.labels._constants import load_constant

    fill_timeout_ms = (
        fill_timeout_ms if fill_timeout_ms is not None else int(load_constant("fill_timeout_ms"))
    )
    tp_atr_mult = tp_atr_mult if tp_atr_mult is not None else float(load_constant("tp_atr_mult"))
    sl_atr_mult = sl_atr_mult if sl_atr_mult is not None else float(load_constant("sl_atr_mult"))
    time_stop_ms = (
        time_stop_ms if time_stop_ms is not None else int(load_constant("time_stop_ms"))
    )

    horizon_bars = int(load_constant("horizon_bars"))

    labels = pl.read_parquet(LABELS_DIR / symbol / resolution_id / "v1" / "labels.parquet")
    labels = labels.with_columns(pl.col("t_post").dt.date().alias("_day"))

    # AG-116 -- sob `resolution_id` o horizonte da barreira TIME e CONTAGEM
    # DE BARRA (`t0_arr[i + horizon_bars]`), NUNCA `t0 + time_stop_ms`.
    # Reconstroi aqui o MESMO grid de barras de decisao que
    # `triple_barrier.build_labels` usa (t0 unico e ordenado, uma entrada
    # por barra -- os dois lados compartilham o grid) para poder resolver o
    # horizonte por indice. Sem isto, sob R3 (barras lentas) 32 barras
    # valem muito mais que 8h e o horizonte sairia truncado, gerando TIME
    # artificial -- bug real desta funcao, corrigido 2026-08-25.
    t0_grid = np.sort(labels["t0"].unique().dt.timestamp("ms").to_numpy().astype(np.int64))
    t0_to_idx = {int(v): i for i, v in enumerate(t0_grid)}

    all_days = sorted(labels["_day"].unique().to_list())
    rng = np.random.default_rng(seed)
    chosen = sorted(rng.choice(np.array(all_days), size=min(n_days, len(all_days)), replace=False))

    base_ret: list[float] = []
    base_tp: list[int] = []
    base_sl: list[int] = []
    base_time: list[int] = []
    base_delay: list[float] = []
    novo_ret: list[float] = []
    novo_tp: list[int] = []
    novo_sl: list[int] = []
    novo_time: list[int] = []
    novo_delay: list[float] = []
    n_barras = 0
    n_base_fill = 0
    n_novo_fill = 0
    n_days_used = 0

    for day in chosen:
        arrays = _load_day_arrays(symbol, day)
        if arrays is None:
            continue
        n_days_used += 1
        tt, tpx, mot, mo, mh, ml, mc = arrays
        sub = labels.filter(pl.col("_day") == day)

        t0_ms_col = sub["t0"].dt.timestamp("ms").to_numpy().astype(np.int64)
        t_post = sub["t_post"].dt.timestamp("ms").to_numpy().astype(np.int64)
        t_entry_base = sub["t_entry"].dt.timestamp("ms").to_numpy()
        sides = sub["side"].to_numpy().astype(np.int64)
        limits = sub["entry_price_limit"].to_numpy().astype(np.float64)
        atrs = sub["atr_at_t0"].to_numpy().astype(np.float64)
        barriers = sub["barrier_hit"].to_numpy()
        rets = sub["ret_gross"].to_numpy()

        for i in range(sub.height):
            n_barras += 1
            # --- baseline, direto do artefato (nada recomputado) ---
            if barriers[i] != "NOFILL":
                n_base_fill += 1
                base_ret.append(float(rets[i]))
                base_tp.append(1 if barriers[i] == "TP" else 0)
                base_sl.append(1 if barriers[i] == "SL" else 0)
                base_time.append(1 if barriers[i] == "TIME" else 0)
                base_delay.append(float(t_entry_base[i]) - float(t_post[i]))

            # --- recomputado com granularidade de trade ---
            horizon_fill = int(t_post[i]) + fill_timeout_ms
            fill = simulate_fill_from_trades(
                tt,
                tpx,
                t_post_ms=int(t_post[i]),
                horizon_ms=horizon_fill,
                limit_price=float(limits[i]),
                side=int(sides[i]),
            )
            if fill.t_entry_ms is None or fill.fill_price is None:
                continue

            side = int(sides[i])
            fill_px = float(fill.fill_price)
            tp_price = fill_px * (1 + side * tp_atr_mult * float(atrs[i]))
            sl_price = fill_px * (1 - side * sl_atr_mult * float(atrs[i]))
            # AG-116 -- horizonte por CONTAGEM DE BARRA sob resolution_id,
            # exatamente como triple_barrier.build_labels. `continue` na
            # cauda incompleta reproduz o mesmo descarte de producao.
            grid_idx = t0_to_idx.get(int(t0_ms_col[i]))
            if grid_idx is None or grid_idx + horizon_bars >= t0_grid.shape[0]:
                continue
            horizon_end = int(t0_grid[grid_idx + horizon_bars])

            lo = int(np.searchsorted(mot, fill.t_entry_ms, side="left"))
            hi = int(np.searchsorted(mot, horizon_end, side="right"))
            if hi <= lo:
                continue

            touch = _first_barrier_touch(
                mot[lo:hi],
                mo[lo:hi],
                mh[lo:hi],
                ml[lo:hi],
                mc[lo:hi],
                tp_price=tp_price,
                sl_price=sl_price,
                side=side,
                horizon_end_ms=horizon_end,
            )
            n_novo_fill += 1
            novo_tp.append(1 if touch.barrier == "TP" else 0)
            novo_sl.append(1 if touch.barrier == "SL" else 0)
            novo_time.append(1 if touch.barrier == "TIME" else 0)
            novo_delay.append(float(fill.t_entry_ms) - float(t_post[i]))
            novo_ret.append(side * (float(touch.exit_price) - fill_px) / fill_px)

    def _mean_bps(xs: list[float]) -> float:
        return float(np.mean(xs)) * 10_000 if xs else float("nan")

    def _mean(xs: list[int] | list[float]) -> float:
        return float(np.mean(xs)) if xs else float("nan")

    result = GranularityComparison(
        n_days=n_days_used,
        n_barras=n_barras,
        base_n_fill=n_base_fill,
        base_pct_nofill=1.0 - (n_base_fill / n_barras) if n_barras else float("nan"),
        base_delay_mediano_ms=float(np.median(base_delay)) if base_delay else float("nan"),
        base_p_tp=_mean(base_tp),
        base_p_sl=_mean(base_sl),
        base_p_time=_mean(base_time),
        base_ret_gross_bps=_mean_bps(base_ret),
        novo_n_fill=n_novo_fill,
        novo_pct_nofill=1.0 - (n_novo_fill / n_barras) if n_barras else float("nan"),
        novo_delay_mediano_ms=float(np.median(novo_delay)) if novo_delay else float("nan"),
        novo_p_tp=_mean(novo_tp),
        novo_p_sl=_mean(novo_sl),
        novo_p_time=_mean(novo_time),
        novo_ret_gross_bps=_mean_bps(novo_ret),
        delta_ret_gross_bps=_mean_bps(novo_ret) - _mean_bps(base_ret),
        delta_p_tp=_mean(novo_tp) - _mean(base_tp),
    )
    logger.info("analysis.ag221.compare_fill_granularity", **asdict(result))
    return result


if __name__ == "__main__":  # pragma: no cover — execução manual
    import argparse
    import sys

    import orjson

    def _run() -> int:
        ap = argparse.ArgumentParser(description="AG-221 -- validacao de granularidade de fill")
        ap.add_argument("--symbol", default="BTCUSDT")
        ap.add_argument("--resolution-id", default="R1")
        ap.add_argument("--n-days", type=int, default=_DEFAULT_N_DAYS)
        ap.add_argument("--seed", type=int, default=_DEFAULT_SEED)
        args = ap.parse_args()

        res = compare_fill_granularity(
            args.symbol, args.resolution_id, n_days=args.n_days, seed=args.seed
        )
        out = (
            Path("experiments")
            / f"ag221_fill_granularity_{args.symbol}_{args.resolution_id}.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(orjson.dumps(asdict(res), option=orjson.OPT_INDENT_2))
        # B28 -- só structlog, nunca print(). `compare_fill_granularity` já
        # emitiu o resultado completo via logger.info; aqui só o destino.
        logger.info("analysis.ag221.cli_done", report_path=str(out))
        return 0

    sys.exit(_run())
