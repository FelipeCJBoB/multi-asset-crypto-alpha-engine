"""Ponto de entrada com IO do Regime Engine (§4, Sprint 5) — análogo a
`src.features.build`: carrega as features T1/T2 já prontas (Sprint 4),
compõe os gatilhos de stress (`stress.py`) e o classificador
(`classifier.py`), e escreve `data/regimes/{version}/regimes.parquet`
(§4.6) de forma atômica (B29 — `.tmp` -> `fsync` -> `rename`, mesmo padrão
de `src.data.validate.write_report_atomic`/`src.exchange.filters.
write_snapshot_atomic`)."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import polars as pl
import structlog

from src.features import build as features_build

from . import classifier
from ._paths import REGIME_OUTPUT_DIR

logger = structlog.get_logger(__name__)


def build_regimes(
    symbol: str,
    start: str,
    end: str,
    *,
    thresholds: classifier.RegimeThresholds | None = None,
    bar_source: str = "time_15m",
    vol_estimator_id: str | None = None,
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
    `NOT_COMPUTABLE` em toda barra deste pipeline, por design.

    Extração de colunas + wiring de stress delegados a
    `classifier.QuantileRegimeClassifier` (PRD_V4_1.md T0.2) — este
    módulo só cuida de IO (carregar `features_df`), não duplica a lógica
    de classificação.

    `bar_source`/`vol_estimator_id` (2026-08-17, Fase 3 da migração
    Parkinson+dollar-bar, AG-036/065) — repassados bit-a-bit pra
    `build_t1_features`, mesmo contrato/default de lá (`bar_source=
    "time_15m"` e `vol_estimator_id=None` preservam todo caller existente
    bit-exato). Antes desta mudança não havia NENHUM caminho de código pra
    computar regime sobre dollar bar — achado de revisão independente
    (`project_assurance`, G3, 2026-08-16) que contradisse a suposição
    original de "Regime Engine não muda".

    `min_common_history_bars_15m` (AG-030) — mesma decisão da Fase 2
    (`src.features.build.build_t1_features`): a constante foi calibrada em
    contagem de barra de TEMPO, não é comparável cross-asset sob dollar
    bar. Quando `bar_source != "time_15m"` E `thresholds` não foi passado
    explicitamente pelo chamador, `RegimeThresholds.from_constants()` é
    construído aqui e `min_common_history_bars` é desabilitado (`None`)
    antes de repassar pro classificador — `er_quantile`/`econ_quantile`
    (`classifier.classify_regimes`) ficam expansivos desde a origem do
    ativo sob dollar bar, sem cap, mesma dívida registrada da Fase 2. Um
    `thresholds` explícito do chamador NUNCA é sobrescrito — a decisão
    automática só se aplica ao caminho default."""
    features_df = features_build.build_t1_features(
        symbol,
        start,
        end,
        apply_warmup_mask=False,
        bar_source=bar_source,
        vol_estimator_id=vol_estimator_id,
    )

    resolved_thresholds = thresholds
    if bar_source != "time_15m" and resolved_thresholds is None:
        resolved_thresholds = replace(
            classifier.RegimeThresholds.from_constants(), min_common_history_bars=None
        )

    regimes = classifier.QuantileRegimeClassifier(
        symbol=symbol, thresholds=resolved_thresholds
    ).classify(features_df)
    logger.info(
        "regime.build.build_regimes",
        symbol=symbol,
        start=start,
        end=end,
        bar_source=bar_source,
        vol_estimator_id=vol_estimator_id,
        n_bars=regimes.height,
    )
    return regimes


def write_regimes_atomic(
    df: pl.DataFrame,
    version: str = classifier.ENGINE_VERSION,
    *,
    dest_dir: Path | None = None,
) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`. `polars.write_parquet` não
    expõe o file handle usado internamente, então o `fsync` é feito
    reabrindo o `.tmp` recém-escrito por descritor (`os.open`/`os.fsync`),
    mesma garantia de durabilidade do padrão já usado em
    `src.data.validate.write_report_atomic` (que fecha o handle que
    escreveu, porque ali a escrita é feita à mão via `orjson`/`open`).

    `dest_dir` (T0.3): default `None` preserva o caminho legado
    `REGIME_OUTPUT_DIR/{version}`. Passar `_paths.regime_symbol_tf_dir(
    symbol, version)` grava no layout chaveado novo."""
    dest_dir = dest_dir if dest_dir is not None else (REGIME_OUTPUT_DIR / version)
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
