"""Testes de `src/models/dataset.py` — `side_subset` (NOFILL fora, warmup
fora, §3.7). `build_modeling_frame`/`date_bounds` fazem IO real (Sprint
4/5/6) e são exercitados na integração de `test_models_alpha.py` (skip se
`labels/v1/labels.parquet` ausente), não aqui."""

from __future__ import annotations

import polars as pl
import pytest

from src.features.build import T1_FEATURE_IDS
from src.models import dataset as ds


def _synthetic_frame() -> pl.DataFrame:
    n = 6
    cols: dict[str, object] = {
        "side": pl.Series([1, 1, 1, -1, -1, -1], dtype=pl.Int8),
        "barrier_hit": pl.Series(["TP", "SL", "NOFILL", "TP", "TIME", "NOFILL"]),
    }
    for i, fid in enumerate(T1_FEATURE_IDS):
        # última linha do lado long (índice 2, que já é NOFILL) e uma
        # extra (índice 0) com feature nula para provar o filtro de warmup
        # independente do filtro de NOFILL.
        values = [0.1 * i + j for j in range(n)]  # noqa: magic-number
        if i == 0:
            values[0] = None
        cols[fid] = pl.Series(values, dtype=pl.Float64)
    return pl.DataFrame(cols)


def test_side_subset_descarta_nofill() -> None:
    df = _synthetic_frame()
    out = ds.side_subset(df, side=1)
    assert "NOFILL" not in out["barrier_hit"].to_list()


def test_side_subset_descarta_warmup_feature_nula() -> None:
    df = _synthetic_frame()
    out = ds.side_subset(df, side=1)
    # a linha 0 (side=1, TP, mas feature nula) tem que sumir
    assert out.height == 1  # só a linha 1 (side=1, SL, sem null) sobrevive
    assert out["barrier_hit"].to_list() == ["SL"]


def test_side_subset_lado_short() -> None:
    df = _synthetic_frame()
    out = ds.side_subset(df, side=-1)
    assert set(out["barrier_hit"].to_list()) <= {"TP", "TIME"}
    assert "NOFILL" not in out["barrier_hit"].to_list()


def test_side_subset_side_invalido_levanta_erro() -> None:
    df = _synthetic_frame()
    with pytest.raises(ValueError):
        ds.side_subset(df, side=0)
