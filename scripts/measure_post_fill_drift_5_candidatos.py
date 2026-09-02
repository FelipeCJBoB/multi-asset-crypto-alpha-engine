"""Item 5 do roadmap "Caso 0/20" (AG-425): mede `post_fill_drift_by_decile`
(`src.analysis.post_fill_drift`) pros 5 candidatos, condicionado por decil
de `A11_true_range_pct` — testa a tese da própria feature ("quem fornece
liquidez em barra de alto impacto sofre seleção adversa"), com o fill de
entrada corrigido via `agg_trades` (evita confundir com o viés de
latência sintética já documentado em `AG-221`, ver docstring do módulo).

Lê `alpha_walk_forward_predictions_{symbol}_{res}_{variant}.parquet` (já
regenerado por `scripts/run_walk_forward_with_predictions.py` — não
retreina nada aqui) + `ModelingFrame.data` (features/labels, leitura, sem
GPU). Escreve `experiments/alpha_walk_forward_post_fill_drift_{symbol}_
{res}_{variant}.parquet` — mesmo ciclo de vida dos demais artefatos AG-424/
AG-425, não side-file solto.

Uso:

    uv run python -m scripts.measure_post_fill_drift_5_candidatos
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import polars as pl
import structlog

from src.analysis import post_fill_drift
from src.models import alpha, dataset
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)


def _write_parquet_atomic(df: pl.DataFrame, out_path: Path) -> None:
    """Mesmo padrão tmp -> fsync -> rename de
    `scripts.run_walk_forward_with_predictions`/`hyperparams_optuna.
    export_trial_trajectory` -- B29."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    with tmp_path.open("wb") as fh:
        fh.write(buffer.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)

_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_VARIANTS: tuple[str, ...] = (alpha.VARIANT_CAMADA1, alpha.VARIANT_CAMADA0)
_FEATURE = "A11_true_range_pct"
# Janela curta, imediatamente após o fill -- "seleção adversa" no sentido
# clássico de microestrutura é um efeito de minutos, não do horizonte de
# holding completo do trade (~1-2 barras medido, AG-372). Não é constante
# de domínio econômico (não entra em nenhum gate/decisão de produção) --
# é dimensionamento de janela de MEDIÇÃO exploratória, mesma categoria de
# `ag221_fill_granularity_validation._DEFAULT_N_DAYS`.
_HORIZON_MINUTES = 5


def main() -> int:
    configure_logging(json_output=False)
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
    fill_timeout_ms = int(load_constant("fill_timeout_ms"))

    for symbol, resolution_id in _CANDIDATOS:
        mf = dataset.build_modeling_frame(
            symbol=symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
        )
        for variant in _VARIANTS:
            preds_path = (
                EXPERIMENTS_DIR
                / f"alpha_walk_forward_predictions_{symbol}_{resolution_id}_{variant}.parquet"
            )
            if not preds_path.exists():
                raise FileNotFoundError(
                    f"measure_post_fill_drift_5_candidatos: {preds_path} não existe -- rode "
                    "scripts.run_walk_forward_with_predictions antes"
                )
            predictions = pl.read_parquet(preds_path)
            logger.info(
                "scripts.measure_post_fill_drift_5_candidatos.iniciando",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                n_predictions=predictions.height,
            )
            out = post_fill_drift.post_fill_drift_by_decile(
                symbol,
                predictions,
                mf.data,
                _FEATURE,
                horizon_minutes=_HORIZON_MINUTES,
                fill_timeout_ms=fill_timeout_ms,
            )
            out_path = (
                EXPERIMENTS_DIR
                / f"alpha_walk_forward_post_fill_drift_{symbol}_{resolution_id}_"
                f"{variant}.parquet"
            )
            _write_parquet_atomic(out, out_path)
            logger.info(
                "scripts.measure_post_fill_drift_5_candidatos.concluido_combo",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                n_rows=out.height,
                path=str(out_path),
            )

    logger.info("scripts.measure_post_fill_drift_5_candidatos.tudo_concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
