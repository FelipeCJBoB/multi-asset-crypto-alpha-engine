"""Testes de `src/analysis/faixa1_5_prerequisites.py` — foco na PLUMBING
mecânica nova (join predictions+mf.data+path_id, aritmética do sweep,
rank intra-fold, orquestração do E02f in-fold), não nas funções
estatísticas reusadas (`decompose`, `compute_ic_by_env`,
`_rank_correlations`, etc. — já testadas em seus próprios módulos)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.analysis import faixa1_5_prerequisites as f15
from src.features.build import T1_FEATURE_IDS
from src.validation.cpcv import CPCVSplit

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")


# ============================================================================
# fold_to_path_map — puramente combinatório
# ============================================================================


@dataclass(frozen=True)
class _FakeSplit:
    split_id: int
    path_id: int


def test_fold_to_path_map_le_direto_de_split_id_path_id() -> None:
    splits = (_FakeSplit(0, 0), _FakeSplit(1, 1), _FakeSplit(2, 0))
    out = f15.fold_to_path_map(splits)  # type: ignore[arg-type]
    assert out == {0: 0, 1: 1, 2: 0}


# ============================================================================
# build_realized_trades — join predictions + mf.data + path_id
# ============================================================================


def _fake_predictions() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": [1, 1, 2, 3, 4],
            "fold_id": [0, 1, 0, 1, 0],
            "side_hat": [1, -1, 0, 1, -1],
            "confidence": [0.6, 0.7, 0.5, 0.8, 0.55],
            "score_long_raw": [0.6, 0.4, 0.5, 0.8, 0.3],
            "score_short_raw": [0.4, 0.7, 0.5, 0.2, 0.55],
            "is_oof": [True, True, True, True, True],
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))


def _fake_mf_data() -> pl.DataFrame:
    rows = []
    for t0 in (1, 2, 3, 4):
        for side in (1, -1):
            rows.append(
                {
                    "t0": t0,
                    "side": side,
                    "barrier_hit": "TP" if side == 1 else "SL",
                    "ret_net": 0.01 * side,
                    "ret_gross": 0.012 * side,
                    "cost_entry_bps": 2.0,
                    "cost_exit_bps": 2.0,
                    "funding_bps": 0.5,
                    "regime": "R1" if t0 < 3 else "R2",
                    "E27f_cost_atr_ratio": 0.1 * t0,
                    "E02f_funding_z_expanding": 0.2 * t0,
                }
            )
    return pl.DataFrame(rows).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))


def test_build_realized_trades_junta_side_hat_com_side_e_marca_path_id() -> None:
    realized = f15.build_realized_trades(_fake_predictions(), _fake_mf_data(), {0: 0, 1: 1})
    # side_hat == 0 (t0=2) descartado
    assert realized.height == 4
    assert set(realized["t0"].dt.epoch(time_unit="ms").to_list()) == {1, 3, 4}
    row_t0_1_long = realized.filter(
        (pl.col("t0").dt.epoch(time_unit="ms") == 1) & (pl.col("side_hat") == 1)
    ).row(0, named=True)
    assert row_t0_1_long["path_id"] == 0
    assert row_t0_1_long["barrier_hit"] == "TP"
    row_t0_1_short = realized.filter(
        (pl.col("t0").dt.epoch(time_unit="ms") == 1) & (pl.col("side_hat") == -1)
    ).row(0, named=True)
    assert row_t0_1_short["path_id"] == 1
    assert row_t0_1_short["barrier_hit"] == "SL"


def test_build_realized_trades_nao_filtra_nofill() -> None:
    preds = pl.DataFrame(
        {
            "t0": [10],
            "fold_id": [0],
            "side_hat": [1],
            "confidence": [0.6],
            "score_long_raw": [0.6],
            "score_short_raw": [0.4],
            "is_oof": [True],
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    mf = pl.DataFrame(
        {
            "t0": [10],
            "side": [1],
            "barrier_hit": ["NOFILL"],
            "ret_net": [0.0],
            "ret_gross": [0.0],
            "cost_entry_bps": [0.0],
            "cost_exit_bps": [0.0],
            "funding_bps": [0.0],
            "regime": ["R1"],
            "E27f_cost_atr_ratio": [0.1],
            "E02f_funding_z_expanding": [0.1],
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    realized = f15.build_realized_trades(preds, mf, {0: 0})
    assert realized.height == 1
    assert realized["barrier_hit"].to_list() == ["NOFILL"]


# ============================================================================
# _barrier_rates
# ============================================================================


def test_barrier_rates_soma_um() -> None:
    df = pl.DataFrame({"barrier_hit": ["TP", "TP", "SL", "TIME", "NOFILL"]})
    rates = f15._barrier_rates(df)
    total = rates["rate_tp"] + rates["rate_sl"] + rates["rate_time"] + rates["rate_nofill"]
    assert total == pytest.approx(1.0)
    assert rates["rate_tp"] == pytest.approx(2 / 5)


def test_barrier_rates_vazio_devolve_nan() -> None:
    rates = f15._barrier_rates(pl.DataFrame({"barrier_hit": pl.Series([], dtype=pl.Utf8)}))
    assert all(math.isnan(v) for v in rates.values())


# ============================================================================
# fee_budget_sweep — aritmética do orçamento implicado
# ============================================================================


def test_fee_budget_sweep_no_ponto_central_scale_e_um(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_load_constant(name: str) -> float:
        return {"fee_budget_monthly": 0.03, "target_signal_rate": 0.0189}[name]

    monkeypatch.setattr(f15, "load_constant", fake_load_constant)
    realized = f15.build_realized_trades(_fake_predictions(), _fake_mf_data(), {0: 0, 1: 1})
    result = f15.fee_budget_sweep(realized)
    central = result["points"]["0.030"]
    assert central["scale_vs_current"] == pytest.approx(1.0)
    assert central["target_signal_rate_adjusted"] == pytest.approx(0.0189)
    # SEM fator de lado (Faixa 1.6, Bloco 3) -- target_signal_rate ja e uma
    # taxa TOTAL, derivada de §0.2 R3 sem termo de lado
    assert central["implied_trades_per_year"] == pytest.approx(0.0189 * f15.BARS_PER_YEAR)
    assert central["implied_trades_per_year"] != pytest.approx(0.0189 * 2.0 * f15.BARS_PER_YEAR)


def test_fee_budget_sweep_grid_cobre_o_sweep_range_inteiro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load_constant(name: str) -> float:
        return {"fee_budget_monthly": 0.03, "target_signal_rate": 0.0189}[name]

    monkeypatch.setattr(f15, "load_constant", fake_load_constant)
    realized = f15.build_realized_trades(_fake_predictions(), _fake_mf_data(), {0: 0, 1: 1})
    result = f15.fee_budget_sweep(realized)
    assert result["sweep_grid"][0] == pytest.approx(0.015)
    assert result["sweep_grid"][-1] == pytest.approx(0.045)
    assert len(result["sweep_grid"]) == 7


def test_bars_per_year_bate_com_365_25_x_96() -> None:
    assert pytest.approx(365.25 * 96) == f15.BARS_PER_YEAR


# ============================================================================
# path_dispersion — threshold_effective_confidence_quantile (Bloco 2 Fase A)
# ============================================================================


def test_path_dispersion_threshold_usa_populacao_scored_completa_nao_so_selecionada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regressão (Faixa 1.6, Bloco 2 Fase A) — `threshold_effective_
    confidence_quantile` precisa ser medido sobre TODO bar OOF scored do
    path (via `predictions`), não só os sinais já selecionados
    (`side_hat != 0`, o que `realized` contém). O bug antigo tomava o
    quantil de uma população já filtrada por seleção (quantil-de-um-
    quantil) — 10 bars scored, só 2 viram sinal (confidence 0.9/1.0);
    com `target_signal_rate=0.5` (mediana), a população completa dá
    mediana ~0.55, a população só-selecionada (o bug) dava ~0.95."""
    monkeypatch.setattr(f15, "load_constant", lambda name: 0.5)
    n = 10
    confidences = [0.1 * (i + 1) for i in range(n)]  # 0.1..1.0
    side_hats = [0] * 8 + [1, 1]  # só os 2 últimos (conf 0.9, 1.0) viram sinal
    predictions = pl.DataFrame(
        {
            "t0": list(range(1, n + 1)),
            "fold_id": [0] * n,
            "side_hat": side_hats,
            "confidence": confidences,
            "score_long_raw": confidences,
            "score_short_raw": [0.0] * n,
            "is_oof": [True] * n,
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    mf_rows = [
        {
            "t0": t0,
            "side": 1,
            "barrier_hit": "TP",
            "ret_net": 0.01,
            "ret_gross": 0.01,
            "cost_entry_bps": 0.0,
            "cost_exit_bps": 0.0,
            "funding_bps": 0.0,
            "regime": "R1",
            "E27f_cost_atr_ratio": 0.1,
            "E02f_funding_z_expanding": 0.1,
        }
        for t0 in (9, 10)
    ]
    mf_data = pl.DataFrame(mf_rows).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))

    fold_to_path = {0: 0}
    realized = f15.build_realized_trades(predictions, mf_data, fold_to_path)
    splits = (_FakeSplit(split_id=0, path_id=0),)

    result = f15.path_dispersion(realized, splits, predictions)  # type: ignore[arg-type]
    entry = result["per_path"]["0"]

    assert entry["n_all_scored_bars_this_path"] == n
    # populacao completa (10 bars, 0.1..1.0), mediana ~0.55 -- longe de 1.0
    assert entry["threshold_effective_confidence_quantile"] == pytest.approx(0.55, abs=0.06)
    # nunca deve reproduzir o valor do bug antigo (quantil só dos 2 selecionados, ~0.95)
    assert entry["threshold_effective_confidence_quantile"] < 0.8


# ============================================================================
# add_confidence_rank — invariante intra-fold
# ============================================================================


def test_add_confidence_rank_preserva_ordem_do_score_cru_dentro_do_fold() -> None:
    preds = pl.DataFrame(
        {
            "t0": [1, 2, 3, 4],
            "fold_id": [0, 0, 0, 1],
            "side_hat": [1, 1, 1, 1],
            "score_long_raw": [0.2, 0.9, 0.5, 0.1],
            "score_short_raw": [0.1, 0.1, 0.1, 0.1],
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    out = f15.add_confidence_rank(preds)
    fold0 = out.filter(pl.col("fold_id") == 0).sort("score_long_raw")
    ranks = fold0["confidence_rank"].to_list()
    assert ranks == sorted(ranks)
    assert max(ranks) <= 1.0
    assert min(ranks) > 0.0
    # fold 1 tem só 1 linha -> rank sempre 1.0 (único elemento do próprio fold)
    fold1 = out.filter(pl.col("fold_id") == 1)
    assert fold1["confidence_rank"].to_list() == [1.0]


def test_add_confidence_rank_nao_remove_confidence() -> None:
    preds = pl.DataFrame(
        {
            "t0": [1],
            "fold_id": [0],
            "side_hat": [1],
            "confidence": [0.77],
            "score_long_raw": [0.5],
            "score_short_raw": [0.5],
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    out = f15.add_confidence_rank(preds)
    assert "confidence" in out.columns
    assert out["confidence"].to_list() == [0.77]


def test_add_confidence_rank_side_zero_vira_null() -> None:
    preds = pl.DataFrame(
        {
            "t0": [1],
            "fold_id": [0],
            "side_hat": [0],
            "score_long_raw": [0.5],
            "score_short_raw": [0.5],
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    out = f15.add_confidence_rank(preds)
    assert out["confidence_rank"].to_list() == [None]


# ============================================================================
# e02f_in_fold — orquestração (train_idx -> side_subset -> assign_environments
# -> compute_ic_by_env -> _assign_from_ic), sem retreinar
# ============================================================================


def test_e02f_in_fold_roda_um_fold_pequeno_sem_levantar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f15, "load_constant", lambda name: 6)
    n = 60
    rng = np.random.default_rng(0)
    columns: dict[str, object] = {
        "t0": list(range(n)),
        "side": [1] * (n // 2) + [-1] * (n // 2),
        "barrier_hit": ["TP"] * n,
        "ret_net": rng.normal(size=n),
        "regime": (["R1", "R2", "R3", "R4"] * (n // 4 + 1))[:n],
    }
    for fid in T1_FEATURE_IDS:
        columns[fid] = rng.normal(size=n)
    mf_data = pl.DataFrame(columns).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))
    split = CPCVSplit(
        split_id=0,
        path_id=0,
        test_groups=(0,),
        train_groups=(1, 2, 3, 4, 5),
        train_idx=np.arange(n),
        test_idx=np.array([], dtype=np.int64),
        n_train_candidate=n,
        n_purged=0,
        n_embargoed=0,
    )
    out = f15.e02f_in_fold(mf_data, (split,))
    assert set(out.keys()) == {"0"}
    assert set(out["0"].keys()) == {"long", "short"}
    for side_label in ("long", "short"):
        entry = out["0"][side_label]
        assert set(entry["ic_by_env"].keys()) == set(f15.ENVIRONMENTS)
        assert entry["forced_sign_actual"] in (1, -1)


# ============================================================================
# run_and_save_faixa1_5 — ponta a ponta, dado real
# ============================================================================


def _skip_if_missing() -> None:
    from src.models._paths import PREDICTIONS_OUTPUT_DIR
    from src.models.pipeline import MODEL_ID_CAMADA1
    from src.validation._paths import LABELS_OUTPUT_DIR

    preds_path = PREDICTIONS_OUTPUT_DIR / "alpha" / MODEL_ID_CAMADA1 / "predictions.parquet"
    labels_path = LABELS_OUTPUT_DIR / "v1" / "labels.parquet"
    if not preds_path.exists() or not labels_path.exists():
        pytest.skip(f"artefato(s) real(is) ausente(s): {preds_path}, {labels_path}")


@pytest.mark.slow
@pytest.mark.integration
def test_run_and_save_faixa1_5_ponta_a_ponta_dado_real(tmp_path: Path) -> None:
    """Roda o pipeline inteiro (5 blocos) contra `predictions.parquet`/
    `labels.parquet` reais — confirma que a orquestração não quebra e que
    o JSON tem os 5 grupos de campos exigidos pelo Bloco 6, sem nenhum
    campo de veredito (`passed`/`ok`/`recommendation`/`conclusion`)."""
    _skip_if_missing()
    dest = tmp_path / "faixa1_5_prerequisites.json"
    path = f15.run_and_save_faixa1_5(dest_path=dest)
    assert path == dest

    import orjson

    payload = orjson.loads(path.read_bytes())
    assert set(payload.keys()) >= {
        "generated_at",
        "code_version",
        "fee_budget_sweep",
        "stratified_headlines",
        "path_dispersion",
        "confidence_variants",
        "e02f_in_fold",
    }
    forbidden_keys = {"passed", "ok", "recommendation", "conclusion"}
    blob = orjson.dumps(payload).decode("utf-8").lower()
    for key in forbidden_keys:
        assert f'"{key}"' not in blob, f"campo de veredito proibido encontrado: {key}"
