"""Ponto de entrada com IO do Regime Engine (§4, Sprint 5) — análogo a
`src.features.build`: carrega as features T1/T2 já prontas (Sprint 4),
compõe os gatilhos de stress (`stress.py`) e o classificador
(`classifier.py`), e escreve `data/regimes/{version}/regimes.parquet`
(§4.6) de forma atômica (B29 — `.tmp` -> `fsync` -> `rename`, mesmo padrão
de `src.data.validate.write_report_atomic`/`src.exchange.filters.
write_snapshot_atomic`)."""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import structlog

from src.features import build as features_build

from . import classifier, stress
from ._paths import REGIME_OUTPUT_DIR

logger = structlog.get_logger(__name__)


def build_regimes(
    symbol: str,
    start: str,
    end: str,
    *,
    thresholds: classifier.RegimeThresholds | None = None,
) -> pl.DataFrame:
    """Núcleo com IO: carrega `B07_efficiency_ratio_48`,
    `C07_vol_pctile_expanding`, `E02f_funding_z_expanding` e
    `E27f_cost_atr_ratio` via `src.features.build.build_t1_features`
    (REUSO — nenhuma das quatro é recalculada aqui), SEM a máscara uniforme
    de `min_warmup_bars` (`apply_warmup_mask=False` — ver docstring de
    `classifier.py` para o porquê), monta os gatilhos de stress e
    classifica.

    `spread_pctile_expanding` (S2) não é passado — F02f não existe como
    feature hoje (ver `stress.s02_spread_extreme`); resolve para
    `NOT_COMPUTABLE` em toda barra deste pipeline, por design."""
    features_df = features_build.build_t1_features(symbol, start, end, apply_warmup_mask=False)

    open_time_ms = features_df["open_time"].cast(pl.Int64).to_numpy()
    er_48 = features_df["B07_efficiency_ratio_48"].cast(pl.Float64).to_numpy()
    vol_pctile = features_df["C07_vol_pctile_expanding"].cast(pl.Float64).to_numpy()
    funding_z = features_df["E02f_funding_z_expanding"].cast(pl.Float64).to_numpy()
    cost_atr_ratio = features_df["E27f_cost_atr_ratio"].cast(pl.Float64).to_numpy()

    filters_snapshots = stress.discover_filters_hash_snapshots(symbol)
    stress_inputs = stress.StressInputs(
        n=features_df.height,
        open_time_ms=open_time_ms,
        vol_pctile_expanding=vol_pctile,
        funding_z_expanding=funding_z,
        spread_pctile_expanding=None,
        filters_hash_snapshots=filters_snapshots,
    )
    stress_result = stress.compute_stress_triggers(stress_inputs)

    regimes = classifier.classify_regimes(
        open_time_ms,
        er_48,
        vol_pctile,
        cost_atr_ratio,
        stress_result,
        thresholds=thresholds,
    )
    logger.info(
        "regime.build.build_regimes",
        symbol=symbol,
        start=start,
        end=end,
        n_bars=regimes.height,
    )
    return regimes


def write_regimes_atomic(
    df: pl.DataFrame, version: str = classifier.ENGINE_VERSION
) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`. `polars.write_parquet` não
    expõe o file handle usado internamente, então o `fsync` é feito
    reabrindo o `.tmp` recém-escrito por descritor (`os.open`/`os.fsync`),
    mesma garantia de durabilidade do padrão já usado em
    `src.data.validate.write_report_atomic` (que fecha o handle que
    escreveu, porque ali a escrita é feita à mão via `orjson`/`open`)."""
    dest_dir = REGIME_OUTPUT_DIR / version
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "regimes.parquet"
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")

    df.write_parquet(tmp_path, compression="zstd")
    fd = os.open(tmp_path, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp_path, dest_path)

    logger.info("regime.build.write_regimes_atomic", path=str(dest_path), n_rows=df.height)
    return dest_path
