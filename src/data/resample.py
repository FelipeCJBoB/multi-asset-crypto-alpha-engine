"""Agregação causal de `klines_1m` para timeframes maiores (5m/15m/30m/1h/2h/1d).

Regra dura do Sprint 2: uma barra agregada fecha em `close_time` e nenhuma
barra usa timestamp >= seu próprio `close_time` — nenhuma constituinte de 1m
com `close_time` posterior ao `close_time` da barra agregada que a contém.
Como o bucket é `floor(open_time / step_ms) * step_ms`, isso vale por
construção (a última barra de 1m de um bucket sempre fecha em
`bucket + step_ms - 1`, que é exatamente o `close_time` da barra agregada) —
mas `resample_klines` reafirma isso com um `assert` interno, e
`assert_no_lookahead` existe para o teste de paridade (§1.3 check 16)
verificar barra a barra em vez de confiar só na construção.

Convenção de `close_time = open_time + intervalo - 1ms` herdada de
klines_1m — verificada empiricamente contra 60 dias reais no Sprint 2 (zero
violação, ver `data/quality_reports/`), não presumida da documentação.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl
import structlog

from ._constants import load_constant
from ._paths import CAPACITY_DIR, RAW_DIR
from ._util import cast_price_columns

logger = structlog.get_logger(__name__)

# Minutos por timeframe suportado. Não é hiperparâmetro nem constante de
# domínio — é a própria definição de calendário do timeframe nomeado (1h
# SEMPRE tem 60 minutos), por isso não entra em constants.yaml pela mesma
# razão que "60 segundos por minuto" não entra.
_TIMEFRAME_MINUTES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "1d": 1440,
}

_MS_PER_MINUTE = 60_000

_OHLCV_COLUMN_ORDER: tuple[str, ...] = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
)


class UnsupportedTimeframeError(ValueError):
    """Timeframe pedido não está em `_TIMEFRAME_MINUTES`."""


def supported_timeframes() -> tuple[str, ...]:
    return tuple(_TIMEFRAME_MINUTES)


def step_ms(timeframe: str) -> int:
    try:
        return _TIMEFRAME_MINUTES[timeframe] * _MS_PER_MINUTE
    except KeyError as exc:
        raise UnsupportedTimeframeError(
            f"timeframe '{timeframe}' não suportado — use um de {sorted(_TIMEFRAME_MINUTES)}"
        ) from exc


def resample_klines(
    df_1m: pl.DataFrame,
    timeframe: str,
    *,
    drop_incomplete_tail: bool = True,
) -> pl.DataFrame:
    """Reagrega barras de 1 minuto (schema `schemas.KLINES_1M`, ou qualquer
    dataset com o mesmo formato — `mark_price_klines_1m`,
    `premium_index_klines_1m`) para `timeframe`.

    Determinístico: mesma entrada produz sempre a mesma saída, bit a bit —
    não há aleatoriedade nem dependência de estado externo.

    `drop_incomplete_tail`: descarta o último bucket se ele não tiver o
    número completo de barras de 1m constituintes (ex.: dado termina às
    14:37 ao reagregar para 1h — o bucket 14:00-15:00 não fechou de verdade).
    Sem isso, o consumidor recebe uma barra "fechada" que na verdade é
    parcial — não é look-ahead (nenhum dado futuro entra nela), mas é um gap
    de completude mascarado como barra válida, que o §1.2 trata como
    inaceitável em `processed/`.
    """
    if df_1m.is_empty():
        return df_1m

    target_step_ms = step_ms(timeframe)
    expected_bars_per_bucket = target_step_ms // _MS_PER_MINUTE

    df = cast_price_columns(df_1m, ("open", "high", "low", "close")).sort("open_time")
    df = df.with_columns((pl.col("open_time") // target_step_ms * target_step_ms).alias("_bucket"))

    agg = (
        df.group_by("_bucket", maintain_order=True)
        .agg(
            open=pl.col("open").first(),
            high=pl.col("high").max(),
            low=pl.col("low").min(),
            close=pl.col("close").last(),
            volume=pl.col("volume").sum(),
            quote_volume=pl.col("quote_volume").sum(),
            count=pl.col("count").sum(),
            taker_buy_volume=pl.col("taker_buy_volume").sum(),
            taker_buy_quote_volume=pl.col("taker_buy_quote_volume").sum(),
            _n_constituent_bars=pl.len(),
            _max_constituent_close_time=pl.col("close_time").max(),
        )
        .rename({"_bucket": "open_time"})
        .sort("open_time")
        .with_columns((pl.col("open_time") + target_step_ms - 1).alias("close_time"))
    )

    # Assert de causalidade em linha — deveria ser impossível por construção
    # (a última constituinte de um bucket fecha exatamente em
    # bucket + step - 1), mas um assert barato aqui documenta a garantia e
    # falha ruidosamente se a lógica de bucket acima algum dia mudar de um
    # jeito que a quebre.
    lookahead = agg.filter(pl.col("_max_constituent_close_time") > pl.col("close_time"))
    if lookahead.height:
        raise AssertionError(
            f"resample_klines: {lookahead.height} bucket(s) com constituinte de 1m cujo "
            "close_time é posterior ao close_time da barra agregada — violação de causalidade"
        )

    if drop_incomplete_tail:
        incomplete = agg.filter(pl.col("_n_constituent_bars") < expected_bars_per_bucket)
        if incomplete.height:
            logger.info(
                "resample.dropped_incomplete_buckets",
                timeframe=timeframe,
                n_dropped=incomplete.height,
                first_dropped_open_time=int(incomplete["open_time"].min()),  # type: ignore[arg-type]
            )
        agg = agg.filter(pl.col("_n_constituent_bars") == expected_bars_per_bucket)

    return agg.select(list(_OHLCV_COLUMN_ORDER))


def assert_no_lookahead(df_1m: pl.DataFrame, df_resampled: pl.DataFrame, timeframe: str) -> None:
    """Helper de teste (§1.3 check 16 / instrução do Sprint 2): para cada
    barra agregada, confirma que NENHUMA constituinte de 1m tem `close_time`
    posterior ao `close_time` da própria barra agregada. Levanta
    `AssertionError` com a contagem de violações se encontrar alguma —
    `resample_klines` já faz este assert internamente, mas este helper
    reexecuta a verificação a partir dos dados brutos, sem reusar nenhum
    estado interno de `resample_klines`, para que o teste de paridade não
    vire um teste de "a função concorda consigo mesma"."""
    target_step_ms = step_ms(timeframe)
    df = cast_price_columns(df_1m, ("open", "high", "low", "close")).with_columns(
        (pl.col("open_time") // target_step_ms * target_step_ms).alias("_bucket")
    )
    max_close_by_bucket = df.group_by("_bucket").agg(pl.col("close_time").max().alias("_max_close"))

    joined = df_resampled.join(
        max_close_by_bucket, left_on="open_time", right_on="_bucket", how="left"
    )
    violations = joined.filter(pl.col("_max_close") > pl.col("close_time"))
    if violations.height:
        raise AssertionError(
            f"{violations.height} barra(s) agregada(s) usam close_time futuro em relação "
            "às constituintes de 1m — violação de causalidade"
        )


# ============================================================================
# §1.3 check 16 — bars_30m reagregado bate com o kline nativo de 30m dentro
# de 1e-8. Procura um dataset nativo já baixado; se não existir, documenta
# PENDING em vez de inventar o comparador (instrução explícita do Sprint 2).
# ============================================================================

_NATIVE_SEARCH_ROOTS: tuple[Path, ...] = (CAPACITY_DIR, RAW_DIR)
_NATIVE_DIR_NAME_CANDIDATES: tuple[str, ...] = ("klines_{tf}", "klines_native_{tf}", "bars_{tf}")


def find_native_klines(symbol: str, timeframe: str) -> Path | None:
    """Procura um dataset de klines NATIVO (baixado direto da Binance, não
    reagregado por este módulo) de `timeframe` em `data/capacity/` ou
    `data/raw/`. Retorna `None` se não existir — no Sprint 2, medido em
    2026-08-08, só `klines_1m` foi baixado nativamente para BTCUSDT
    perpétuo (ver `known_gaps` em `config/constants.yaml`); klines_30m
    nativo não existe no disco. Isso não é um erro deste módulo, é o estado
    real do backfill — quando D0x nativo de 30m for baixado, este helper
    passa a encontrá-lo sem que `compare_resample_to_native` precise mudar."""
    for root in _NATIVE_SEARCH_ROOTS:
        for name_template in _NATIVE_DIR_NAME_CANDIDATES:
            candidate = root / name_template.format(tf=timeframe) / symbol
            if candidate.is_dir() and any(candidate.glob("*.parquet")):
                return candidate
    return None


@dataclass(frozen=True, slots=True)
class ParityResult:
    compared: bool
    rows_compared: int
    max_abs_deviation: float | None
    passed: bool | None
    tolerance: float
    reason_not_compared: str | None


_PARITY_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


def compare_resample_to_native(df_resampled: pl.DataFrame, native_dir: Path) -> ParityResult:
    """Compara `df_resampled` (saída de `resample_klines`) contra o dataset
    nativo encontrado por `find_native_klines`, coluna a coluna em
    `_PARITY_COLUMNS`, dentro de `resample_cross_source_parity_tolerance`
    (`config/constants.yaml`, 1e-8 — PRD §1.3 check 16 / bloco INVARIANTES).
    """
    tolerance = float(load_constant("resample_cross_source_parity_tolerance"))

    native_files = sorted(native_dir.glob("*.parquet"))
    if not native_files:
        return ParityResult(False, 0, None, None, tolerance, "diretório nativo vazio")

    native = pl.concat([pl.read_parquet(f) for f in native_files])
    native = cast_price_columns(native, ("open", "high", "low", "close")).sort("open_time")

    joined = df_resampled.join(native, on="open_time", how="inner", suffix="_native")
    if joined.is_empty():
        return ParityResult(
            False, 0, None, None, tolerance, "sem open_time em comum entre resample e nativo"
        )

    max_dev = 0.0
    for col in _PARITY_COLUMNS:
        dev = joined.select((pl.col(col) - pl.col(f"{col}_native")).abs().max()).item()
        if dev is not None:
            max_dev = max(max_dev, float(dev))

    return ParityResult(
        compared=True,
        rows_compared=joined.height,
        max_abs_deviation=max_dev,
        passed=max_dev < tolerance,
        tolerance=tolerance,
        reason_not_compared=None,
    )
