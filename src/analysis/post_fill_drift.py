"""AG-425 — deslocamento de preço realizado nos minutos após o fill,
condicionado por decil de feature (item 5 do roadmap "Caso 0/20": proxy
MEDIDO de seleção adversa, já que `adverse_selection_bps` é um placeholder
`ASSUMED`, classe A, nunca medido de fato — `sweep_required: true`,
travado pro Sprint 16 com metodologia própria via Testnet, §9.5).

**Por que reconstrói o fill via `agg_trades` em vez de usar `t_entry` de
`labels.parquet` direto.** `AG-221` mediu que o `t_entry` atual (via
`mark_1m`) carrega uma espera sintética de 0-60s que **escala com
volatilidade** (-1,82bps no quintil mais calmo, -5,74 no mais volátil,
`AG-221-ADDENDUM`) — correlacionada DIRETAMENTE com qualquer feature de
impacto/volatilidade (`A11_true_range_pct` é exatamente isso). Usar o
`t_entry` não corrigido pra condicionar por decil de `A11` confundiria o
artefato já documentado de latência sintética com seleção adversa
genuína — o mesmo mecanismo, na mesma direção, tornaria impossível
separar os dois sem a correção. `simulate_fill_from_trades`
(`src.labels.fill_model`, `AG-221-ADDENDUM`, já validado — +3,09bps
medido numa amostra real de BTCUSDT/R1, `P(TP)` convergindo pro teórico
0,50) remove essa confusão na origem — reusado aqui, não reimplementado.

**PÓS-HOC, leitura de dado já materializado** (`agg_trades`/`mark_1m` em
`data/capacity/`, predictions/labels já em disco) — não retreina, não
escreve produção. Mesma fronteira/disciplina de `src.analysis.
attribution` (nunca insumo de treino/seleção de feature) e do resto de
`src.analysis` — `pyproject.toml [tool.importlinter]` já proíbe
`src.models`/`src.features` de importar `src.analysis`.

**Escopo desta versão**: só trades REALIZADOS sob o `labels.parquet`
atual (`barrier_hit != NOFILL`) — recomputa o INSTANTE/preço de fill pra
esses trades com mais precisão, não muda QUAIS trades entram na amostra
(um relabel completo, que mudaria a população via a queda de NOFILL de
9,54% pra 2,18% medida em `AG-221-ADDENDUM`, é decisão separada, fora do
escopo deste diagnóstico)."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from src.labels.fill_model import simulate_fill_from_trades

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]

CAPACITY_DIR = Path("data/capacity")

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_NOFILL = "NOFILL"
_SIDE_LABEL_BY_HAT: dict[int, str] = {1: "long", -1: "short"}
_N_DECILES_DEFAULT = 10
_BPS_PER_UNIT = 10_000
# Mesmo valor/mesma categoria de src.analysis.attribution._MIN_OBS_T_STAT
# (AG-424) -- duplicado aqui por design, ver docstring do módulo irmão
# sobre não compartilhar código de análise entre módulos.
_MIN_OBS_T_STAT = 5  # noqa: magic-number


def _load_day_arrays(
    symbol: str, day: dt.date
) -> tuple[IntArray, FloatArray, IntArray, FloatArray] | None:
    """`(trade_time_ms, trade_price, mark_open_time_ms, mark_close)` pra um
    dia, ou `None` se `agg_trades` do dia faltar. Carrega `mark_1m` de D,
    D+1 e D+2 (janela de deriva pode passar da meia-noite 2x sob
    `horizon_minutes` alto) -- mesmo padrão de
    `src.analysis.ag221_fill_granularity_validation._load_day_arrays`,
    não importado de lá (privado, e essa função só carrega o necessário
    pra avaliar BARREIRA/fill, não pra medir deriva alguns minutos à
    frente)."""
    agg_path = CAPACITY_DIR / "agg_trades" / symbol / f"{day.isoformat()}.parquet"
    if not agg_path.exists():
        return None
    trades = pl.read_parquet(agg_path, columns=["transact_time", "price"])

    mark_frames: list[pl.DataFrame] = []
    for offset in (0, 1, 2):
        p = (
            CAPACITY_DIR
            / "mark_price_klines_1m"
            / symbol
            / f"{(day + dt.timedelta(days=offset)).isoformat()}.parquet"
        )
        if p.exists():
            mark_frames.append(pl.read_parquet(p, columns=["open_time", "close"]))
    if not mark_frames:
        return None
    mark = pl.concat(mark_frames, how="vertical").sort("open_time")

    return (
        trades["transact_time"].to_numpy().astype(np.int64),
        trades["price"].to_numpy().astype(np.float64),
        mark["open_time"].to_numpy().astype(np.int64),
        mark["close"].cast(pl.Float64).to_numpy(),
    )


def _mark_price_at_or_after(
    mark_open_time_ms: IntArray, mark_close: FloatArray, target_ms: int
) -> float | None:
    """`close` do 1o candle de `mark_1m` com `open_time >= target_ms`, ou
    `None` se a janela carregada não alcançar (trade perto do fim do
    horizonte de dados carregado)."""
    idx = int(np.searchsorted(mark_open_time_ms, target_ms, side="left"))
    if idx >= mark_open_time_ms.shape[0]:
        return None
    return float(mark_close[idx])


@dataclass(frozen=True, slots=True)
class _DriftObservation:
    feature_value: float
    side_label: str
    drift_bps: float  # sinal: positivo = preço moveu A FAVOR da posição


def _drift_for_trade(
    *,
    trade_time_ms: IntArray,
    trade_price: FloatArray,
    mark_open_time_ms: IntArray,
    mark_close: FloatArray,
    t_post_ms: int,
    fill_timeout_ms: int,
    limit_price: float,
    side: int,
    horizon_ms: int,
) -> float | None:
    """`None` se o fill (via `agg_trades`) não ocorreu dentro do timeout,
    ou se a janela de `mark_1m` carregada não alcança `fill_ms +
    horizon_ms` (trade perto do fim dos dias carregados)."""
    fill = simulate_fill_from_trades(
        trade_time_ms,
        trade_price,
        t_post_ms=t_post_ms,
        horizon_ms=t_post_ms + fill_timeout_ms,
        limit_price=limit_price,
        side=side,
    )
    if fill.t_entry_ms is None or fill.fill_price is None:
        return None
    future_price = _mark_price_at_or_after(
        mark_open_time_ms, mark_close, fill.t_entry_ms + horizon_ms
    )
    if future_price is None:
        return None
    # side=1 (long): favorável se o preço SOBE depois do fill.
    # side=-1 (short): favorável se o preço DESCE depois do fill.
    raw_drift = (future_price / fill.fill_price) - 1.0
    return float(side) * raw_drift * _BPS_PER_UNIT


def post_fill_drift_by_decile(
    symbol: str,
    predictions: pl.DataFrame,
    trade_data: pl.DataFrame,
    feature: str,
    *,
    horizon_minutes: int,
    fill_timeout_ms: int,
    n_deciles: int = _N_DECILES_DEFAULT,
) -> pl.DataFrame:
    """Mede `drift_bps` (deslocamento de preço, sinal positivo = favorável
    à posição) no instante `fill + horizon_minutes`, pra cada trade
    REALIZADO (`barrier_hit != NOFILL` em `trade_data`), condicionado por
    decil de `feature` (rank DENTRO do lado — mesma disciplina de
    `src.analysis.attribution.feature_deciles_by_side`: long e short
    nunca pooled, populações de classificador/calibrador distintas).

    **Junção**: `predictions` (`is_oof=True`, `side_hat!=0`) com
    `trade_data` por `(t0, side_hat==side)` — `trade_data` precisa ter
    `t0` (=`t_post`, close_time da dollar bar), `side`, `barrier_hit`,
    `entry_price_limit` e a coluna de `feature`; tipicamente
    `src.models.dataset.build_modeling_frame().data`. Trades são
    processados em lotes POR DIA (`t0.date()`) pra reusar
    `agg_trades`/`mark_1m` carregados uma vez por dia, mesma economia de
    IO de `ag221_fill_granularity_validation.compare_fill_granularity`.
    Dias sem `agg_trades` local são pulados (contados em `n_dias_sem_
    dado`, logado, nunca silenciosos).

    Retorna uma linha por `(side, decile)` — schema análogo ao de
    `confidence_deciles_by_side`/`feature_deciles_by_side`: `n`,
    `mean_drift_bps`, `std_drift_bps`, `t_stat` (`nan` se `n <
    _MIN_OBS_T_STAT` ou `std==0` — mesmo piso de 3 módulos irmãos, AG-424).
    """
    if n_deciles < 1:
        raise ValueError(f"post_fill_drift_by_decile: n_deciles={n_deciles} — precisa ser >= 1")
    required_predictions = ("t0", "side_hat", "is_oof")
    missing_p = sorted(set(required_predictions) - set(predictions.columns))
    if missing_p:
        raise ValueError(f"predictions: coluna(s) obrigatória(s) ausente(s): {missing_p}")
    required_trade = ("t0", "side", "barrier_hit", "entry_price_limit", feature)
    missing_t = sorted(set(required_trade) - set(trade_data.columns))
    if missing_t:
        raise ValueError(f"trade_data: coluna(s) obrigatória(s) ausente(s): {missing_t}")

    horizon_ms = horizon_minutes * 60_000

    rows: list[dict[str, Any]] = []
    for side_value, side_label in _SIDE_LABEL_BY_HAT.items():
        preds_side = (
            predictions.filter(pl.col("is_oof") & (pl.col("side_hat") == side_value))
            .select(["t0", "side_hat"])
            .with_columns(pl.col("t0").cast(_T0_DTYPE))
        )
        joined = preds_side.join(
            trade_data.select(["t0", "side", "barrier_hit", "entry_price_limit", feature]).rename(
                {feature: "_feature_value"}
            ),
            left_on=["t0", "side_hat"],
            right_on=["t0", "side"],
            how="inner",
        ).filter(pl.col("barrier_hit").cast(pl.Utf8) != _NOFILL)

        if joined.height == 0:
            logger.warning("analysis.post_fill_drift.sem_trades_no_lado", side=side_label)
            continue

        joined = joined.with_columns(pl.col("t0").dt.date().alias("_day")).sort("t0")
        observations: list[_DriftObservation] = []
        n_dias_sem_dado = 0
        for day, day_df in joined.group_by("_day", maintain_order=True):
            arrays = _load_day_arrays(symbol, day[0])
            if arrays is None:
                n_dias_sem_dado += 1
                continue
            tt, tpx, mot, mc = arrays
            for row in day_df.iter_rows(named=True):
                drift_bps = _drift_for_trade(
                    trade_time_ms=tt,
                    trade_price=tpx,
                    mark_open_time_ms=mot,
                    mark_close=mc,
                    t_post_ms=int(row["t0"].timestamp() * 1000),
                    fill_timeout_ms=fill_timeout_ms,
                    limit_price=float(row["entry_price_limit"]),
                    side=side_value,
                    horizon_ms=horizon_ms,
                )
                if drift_bps is None:
                    continue
                observations.append(
                    _DriftObservation(
                        feature_value=float(row["_feature_value"]),
                        side_label=side_label,
                        drift_bps=drift_bps,
                    )
                )

        logger.info(
            "analysis.post_fill_drift.lado_processado",
            side=side_label,
            n_trades_candidatos=joined.height,
            n_observacoes_validas=len(observations),
            n_dias_sem_dado=n_dias_sem_dado,
        )
        rows.extend(_decile_rows(observations, side_label=side_label, n_deciles=n_deciles))

    if not rows:
        return pl.DataFrame(schema=_OUTPUT_SCHEMA)
    return pl.DataFrame(rows, schema=_OUTPUT_SCHEMA)


_OUTPUT_SCHEMA: pl.Schema = pl.Schema(
    {
        "side": pl.Utf8,
        "decile": pl.Int64,
        "n": pl.Int64,
        "value_min": pl.Float64,
        "value_max": pl.Float64,
        "mean_drift_bps": pl.Float64,
        "std_drift_bps": pl.Float64,
        "t_stat": pl.Float64,
    }
)


def _decile_rows(
    observations: list[_DriftObservation], *, side_label: str, n_deciles: int
) -> list[dict[str, Any]]:
    if not observations:
        return []
    ordered = sorted(observations, key=lambda o: o.feature_value)
    n_total = len(ordered)
    rows: list[dict[str, Any]] = []
    for decile in range(1, n_deciles + 1):
        lo = ((decile - 1) * n_total) // n_deciles
        hi = (decile * n_total) // n_deciles
        bucket = ordered[lo:hi]
        n = len(bucket)
        if n == 0:
            rows.append(
                {
                    "side": side_label,
                    "decile": decile,
                    "n": 0,
                    "value_min": float("nan"),
                    "value_max": float("nan"),
                    "mean_drift_bps": float("nan"),
                    "std_drift_bps": float("nan"),
                    "t_stat": float("nan"),
                }
            )
            continue
        drifts = np.array([o.drift_bps for o in bucket], dtype=np.float64)
        values = np.array([o.feature_value for o in bucket], dtype=np.float64)
        mean_bps = float(np.mean(drifts))
        std_bps = float(np.std(drifts, ddof=1)) if n > 1 else 0.0
        # AG-425 -- mesmo piso de AG-424 (_MIN_OBS_T_STAT=5): t_stat só é
        # confiável com amostra suficiente, "definido" != "confiável".
        t_stat = (
            mean_bps / (std_bps / math.sqrt(n))
            if n >= _MIN_OBS_T_STAT and std_bps > 0.0
            else float("nan")
        )
        rows.append(
            {
                "side": side_label,
                "decile": decile,
                "n": n,
                "value_min": float(np.min(values)),
                "value_max": float(np.max(values)),
                "mean_drift_bps": mean_bps,
                "std_drift_bps": std_bps,
                "t_stat": t_stat,
            }
        )
    return rows
