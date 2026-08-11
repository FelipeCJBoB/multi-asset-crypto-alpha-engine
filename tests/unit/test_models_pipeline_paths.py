"""Testes de layout de caminho (PRD_V4_1.md T0.3) — `predictions_symbol_tf_dir`
e o override `dest_dir` de `write_predictions_atomic`. Não exercita o resto
de `src/models/pipeline.py` (treino real, `run_layer1_sprint`) — isso já é
coberto por `tests/golden/test_sprint8_reproducibility.py`/
`tests/unit/test_models_alpha.py`."""

from __future__ import annotations

import polars as pl

from src.models import pipeline
from src.models._paths import PREDICTIONS_OUTPUT_DIR, predictions_symbol_tf_dir


def test_predictions_symbol_tf_dir_layout_chaveado() -> None:
    path = predictions_symbol_tf_dir("ETHUSDT", "alpha_c1_v1")
    assert path == PREDICTIONS_OUTPUT_DIR / "alpha" / "ETHUSDT" / "15m" / "alpha_c1_v1"


def test_predictions_symbol_tf_dir_aceita_tf_explicito() -> None:
    path = predictions_symbol_tf_dir("ETHUSDT", "alpha_c1_v1", tf="30m")
    assert path == PREDICTIONS_OUTPUT_DIR / "alpha" / "ETHUSDT" / "30m" / "alpha_c1_v1"


def test_write_predictions_atomic_dest_dir_override_usa_layout_chaveado(tmp_path) -> None:
    predictions = pl.DataFrame(
        {c: [] for c in pipeline.alpha.PREDICTIONS_SCHEMA_COLUMNS},
        schema={c: pl.Float64 for c in pipeline.alpha.PREDICTIONS_SCHEMA_COLUMNS},
    )
    keyed_dir = tmp_path / "ETHUSDT" / "15m" / "alpha_c1_v1"
    dest = pipeline.write_predictions_atomic(predictions, "alpha_c1_v1", dest_dir=keyed_dir)
    assert dest == keyed_dir / "predictions.parquet"
    assert dest.exists()
