"""Testes de `src/analysis/attribution.py` — `ic_by_regime`/`gain_by_side`/
`feature_agreement`. Módulo PÓS-HOC (ver docstring do módulo): lê
`ret_net`/`barrier_hit` REALIZADOS e diagnóstico já persistido, nunca
insumo de treino.

Três blocos, mesmo padrão do resto do repo (`test_models_monotonic.py`,
`test_models_pipeline.py`):

1. `ic_by_regime` — fixture sintética com correlação PERFEITA e sinal
   conhecido por regime (`featA` positivamente correlacionada com
   `ret_net` em R1, negativamente em R2 — a MESMA estrutura do achado real
   que motivou este módulo, `E02f_funding_z_expanding` trocando de sinal
   entre regime de faixa e de tendência), mais casos de filtro
   (`is_oof=False`, `side_hat=0`, `NOFILL`, amostra insuficiente).
2. `gain_by_side` — JSON sintéticos escritos em `tmp_path` no schema real
   de `src.models.pipeline.write_fold_diagnostics_atomic`, média/desvio
   conferidos à mão.
3. `feature_agreement` — rankings sintéticos com correlação de rank
   conhecida.
4. Integração real — `skip` a menos que
   `predictions/alpha/{model_id}/predictions.parquet`,
   `labels/v1/labels.parquet` e `models/{model_id}/diagnostics/` já
   existam (mesmo padrão skip de `test_models_alpha.py`/
   `test_models_pipeline.py`). Usa `src.models.dataset.build_modeling_frame`
   só AQUI (teste, não `src/analysis`) para montar `regimes` — import
   permitido em teste, é `src.models` que não pode importar `src.analysis`
   (ver contratos de import-linter), não o contrário."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import orjson
import polars as pl
import pytest

from src.analysis import attribution as attr

_T0_DTYPE_MS = pl.Datetime(time_unit="ms", time_zone="UTC")
_T0_DTYPE_NS = pl.Datetime(time_unit="ns", time_zone="UTC")

_BASE = datetime(2024, 1, 1, tzinfo=UTC)


def _t0s(n: int, *, offset_days: int = 0) -> list[datetime]:
    return [_BASE + timedelta(days=offset_days + i) for i in range(n)]


# ============================================================================
# ic_by_regime — correlação perfeita, sinal conhecido por regime
# ============================================================================


def _predictions_df(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=_T0_DTYPE_MS),
            "side_hat": pl.Series([r["side_hat"] for r in rows], dtype=pl.Int8),
            "is_oof": pl.Series([r["is_oof"] for r in rows], dtype=pl.Boolean),
            "model_id": pl.Series([r.get("model_id", "test_model") for r in rows], dtype=pl.Utf8),
        }
    )


def _labels_df(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=_T0_DTYPE_MS),
            "side": pl.Series([r["side"] for r in rows], dtype=pl.Int8),
            "barrier_hit": pl.Series([r["barrier_hit"] for r in rows], dtype=pl.Utf8),
            "ret_net": pl.Series([r["ret_net"] for r in rows], dtype=pl.Float64),
        }
    )


def _regimes_df(
    rows: list[dict[str, object]], *, t0_dtype: pl.Datetime = _T0_DTYPE_MS
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=t0_dtype),
            "regime": pl.Series([r["regime"] for r in rows], dtype=pl.Utf8),
            "featA": pl.Series([r["featA"] for r in rows], dtype=pl.Float64),
        }
    )


def _build_fixture(
    *, n_per_regime: int = 10
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """R1: `featA` cresce junto com `ret_net` (Spearman = +1). R2: `featA`
    cresce, `ret_net` decresce (Spearman = -1) — mesma estrutura do achado
    real (`E02f_funding_z_expanding` trocando de sinal entre regimes de
    faixa e de tendência, ver docstring do módulo/CLAUDE.md desta task).
    Mais 3 t0's extras, um por filtro (`is_oof=False`/`side_hat=0`/
    `NOFILL`), cujos valores de featA/ret_net QUEBRARIAM a correlação
    perfeita se entrassem por engano — o teste depende disso para provar
    que o filtro de fato excluiu a linha, não só que o resultado "parece"
    certo."""
    r1_t0 = _t0s(n_per_regime, offset_days=0)
    r2_t0 = _t0s(n_per_regime, offset_days=100)
    extra_oof_false_t0 = _BASE + timedelta(days=200)
    extra_side0_t0 = _BASE + timedelta(days=201)
    extra_nofill_t0 = _BASE + timedelta(days=202)

    pred_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    regime_rows: list[dict[str, object]] = []

    for i, t0 in enumerate(r1_t0):
        featA = float(i + 1)
        ret_net = 0.01 * (i + 1)  # cresce junto com featA -> Spearman +1
        pred_rows.append({"t0": t0, "side_hat": 1, "is_oof": True})
        label_rows.append({"t0": t0, "side": 1, "barrier_hit": "TP", "ret_net": ret_net})
        label_rows.append(
            {"t0": t0, "side": -1, "barrier_hit": "NOFILL", "ret_net": 0.0}
        )  # lado não escolhido — não deve entrar
        regime_rows.append({"t0": t0, "regime": "R1", "featA": featA})

    for i, t0 in enumerate(r2_t0):
        featA = float(i + 1)
        ret_net = 0.01 * (n_per_regime - i)  # decresce enquanto featA cresce -> Spearman -1
        pred_rows.append({"t0": t0, "side_hat": 1, "is_oof": True})
        label_rows.append({"t0": t0, "side": 1, "barrier_hit": "SL", "ret_net": ret_net})
        label_rows.append({"t0": t0, "side": -1, "barrier_hit": "NOFILL", "ret_net": 0.0})
        regime_rows.append({"t0": t0, "regime": "R2", "featA": featA})

    # is_oof=False — excluído; se entrasse, featA=1/ret_net=-1 quebraria o +1 perfeito de R1
    pred_rows.append({"t0": extra_oof_false_t0, "side_hat": 1, "is_oof": False})
    label_rows.append(
        {"t0": extra_oof_false_t0, "side": 1, "barrier_hit": "TP", "ret_net": -1.0}
    )
    regime_rows.append({"t0": extra_oof_false_t0, "regime": "R1", "featA": 1.0})

    # side_hat=0 (sem decisão) — excluído
    pred_rows.append({"t0": extra_side0_t0, "side_hat": 0, "is_oof": True})
    label_rows.append({"t0": extra_side0_t0, "side": 1, "barrier_hit": "TP", "ret_net": -1.0})
    label_rows.append({"t0": extra_side0_t0, "side": -1, "barrier_hit": "TP", "ret_net": -1.0})
    regime_rows.append({"t0": extra_side0_t0, "regime": "R1", "featA": 1.0})

    # barrier_hit == NOFILL no lado escolhido — excluído
    pred_rows.append({"t0": extra_nofill_t0, "side_hat": 1, "is_oof": True})
    label_rows.append(
        {"t0": extra_nofill_t0, "side": 1, "barrier_hit": "NOFILL", "ret_net": -1.0}
    )
    regime_rows.append({"t0": extra_nofill_t0, "regime": "R1", "featA": 1.0})

    return _predictions_df(pred_rows), _labels_df(label_rows), _regimes_df(regime_rows)


def test_ic_by_regime_sinal_oposto_entre_regimes() -> None:
    predictions, labels, regimes = _build_fixture()
    out = attr.ic_by_regime(predictions, labels, regimes, ("featA",))

    r1 = out.filter((pl.col("feature") == "featA") & (pl.col("regime") == "R1")).row(
        0, named=True
    )
    r2 = out.filter((pl.col("feature") == "featA") & (pl.col("regime") == "R2")).row(
        0, named=True
    )

    assert r1["ic_value"] == pytest.approx(1.0)
    assert r1["ic_n"] == 10
    assert r1["ic_valid"] is True
    assert r1["ic_n_semantics"] == "trades"
    assert r1["ic_unit"] == "ratio"
    assert r1["ic_source"] == "predictions/alpha/test_model/predictions.parquet"

    assert r2["ic_value"] == pytest.approx(-1.0)
    assert r2["ic_n"] == 10
    assert r2["ic_valid"] is True


def test_ic_by_regime_filtros_excluem_is_oof_false_side0_e_nofill() -> None:
    """Se qualquer um dos 3 filtros falhasse, o IC de R1 deixaria de ser
    exatamente +1.0 (os valores extras foram desenhados para quebrar a
    correlação) — a asserção acima (`test_ic_by_regime_sinal_oposto_entre_
    regimes`) já cobre isso implicitamente, este teste só torna explícito
    QUE linha cada filtro remove."""
    predictions, labels, regimes = _build_fixture()

    joined_no_filter_count = (
        predictions.join(
            labels, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
        )
    ).height
    # 10 (R1, side_hat=1 casa só com o label side=1) + 10 (R2, idem) +
    # 1 (is_oof=False, side_hat=1 casa com side=1) + 0 (side_hat=0 não casa
    # com side=1 nem side=-1 — labels só tem side em {-1,1}, junção por
    # igualdade não pode "casar com os dois") + 1 (NOFILL, side_hat=1 casa
    # com side=1) = 22 antes de qualquer filtro de ic_by_regime; confirma
    # que a fixture de fato contém as linhas "armadilha" (a linha
    # side_hat=0 é excluída pelo PRÓPRIO join de side, não pelo filtro
    # `side_hat != 0` — os dois mecanismos coincidem aqui por construção).
    assert joined_no_filter_count == 22

    out = attr.ic_by_regime(predictions, labels, regimes, ("featA",))
    total_n = out.filter(pl.col("regime") == "R1")["ic_n"][0]
    assert total_n == 10  # não 11, 12 ou 13 — as 3 armadilhas foram excluídas


def test_ic_by_regime_amostra_insuficiente_marca_invalido() -> None:
    t0s = _t0s(3)
    pred_rows = [{"t0": t0, "side_hat": 1, "is_oof": True} for t0 in t0s]
    label_rows = [
        {"t0": t0, "side": 1, "barrier_hit": "TP", "ret_net": 0.01 * i}
        for i, t0 in enumerate(t0s)
    ]
    regime_rows = [{"t0": t0, "regime": "R1", "featA": float(i)} for i, t0 in enumerate(t0s)]

    predictions = _predictions_df(pred_rows)
    labels = _labels_df(label_rows)
    regimes = _regimes_df(regime_rows)

    out = attr.ic_by_regime(predictions, labels, regimes, ("featA",))
    row = out.row(0, named=True)
    assert row["ic_n"] == 3
    assert row["ic_valid"] is False
    assert math.isnan(row["ic_value"])
    assert row["ic_invalid_reason"] is not None and "3" in row["ic_invalid_reason"]


def test_ic_by_regime_regimes_com_t0_em_nanossegundos_ainda_junta() -> None:
    """`regimes` vindo de `src.regime.build.build_regimes()` diretamente
    (não de `build_modeling_frame`) tem `t0` em `Datetime(ns, UTC)`
    (`classify_regimes`, `.dt.cast_time_unit('ns')`) — a normalização de
    dtype interna precisa lidar com isso sem perder nenhuma linha."""
    predictions, labels, regimes_ms = _build_fixture(n_per_regime=5)
    regimes_ns = regimes_ms.with_columns(pl.col("t0").cast(_T0_DTYPE_NS))
    assert regimes_ns.schema["t0"] == _T0_DTYPE_NS

    out = attr.ic_by_regime(predictions, labels, regimes_ns, ("featA",))
    r1 = out.filter((pl.col("feature") == "featA") & (pl.col("regime") == "R1")).row(
        0, named=True
    )
    assert r1["ic_value"] == pytest.approx(1.0)
    assert r1["ic_n"] == 5


def test_ic_by_regime_dedup_regimes_com_2_linhas_por_t0_nao_infla_n() -> None:
    """`regimes` construído a partir de `build_modeling_frame().data` tem
    2 linhas por `t0` (uma por lado do label) com o MESMO `regime`/
    `featA` — sem dedup, o join produziria `n` em dobro."""
    predictions, labels, regimes = _build_fixture(n_per_regime=5)
    regimes_duplicado = pl.concat([regimes, regimes], how="vertical")

    out = attr.ic_by_regime(predictions, labels, regimes_duplicado, ("featA",))
    r1 = out.filter((pl.col("feature") == "featA") & (pl.col("regime") == "R1")).row(
        0, named=True
    )
    assert r1["ic_n"] == 5  # não 10


def test_ic_by_regime_features_vazio_levanta_valueerror() -> None:
    predictions, labels, regimes = _build_fixture(n_per_regime=1)
    with pytest.raises(ValueError, match="features vazio"):
        attr.ic_by_regime(predictions, labels, regimes, ())


def test_ic_by_regime_coluna_obrigatoria_ausente_levanta_valueerror() -> None:
    predictions, labels, regimes = _build_fixture(n_per_regime=1)
    with pytest.raises(ValueError, match="predictions"):
        attr.ic_by_regime(predictions.drop("is_oof"), labels, regimes, ("featA",))


def test_ic_by_regime_frame_vazio_retorna_schema_correto_sem_erro() -> None:
    predictions, labels, regimes = _build_fixture(n_per_regime=1)
    out = attr.ic_by_regime(
        predictions.filter(pl.lit(False)),
        labels,
        regimes,
        ("featA",),
    )
    assert out.height == 0
    assert out.schema == attr._IC_OUTPUT_SCHEMA


# ============================================================================
# gain_by_side — JSON sintéticos, média/desvio conferidos à mão
# ============================================================================


def _write_fold_json(
    out_dir: Path,
    *,
    fold_id: int,
    side_label: str,
    model_id: str,
    gain_by_column: dict[str, float],
    concentration_shares: dict[str, float],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_id": model_id,
        "fold_id": fold_id,
        "side_label": side_label,
        "side": 1 if side_label == "long" else -1,
        "gain_by_column": gain_by_column,
        "concentration_shares": concentration_shares,
    }
    (out_dir / f"fold_{fold_id}_{side_label}.json").write_bytes(orjson.dumps(payload))


def test_gain_by_side_media_e_desvio_conferidos_a_mao(tmp_path: Path) -> None:
    model_id = "test_model"
    diag_dir = tmp_path / model_id / "diagnostics"
    # 3 folds, lado long: featA gain = [10, 20, 30] -> media 20, std amostral (ddof=1) = 10
    for fold_id, gain in enumerate([10.0, 20.0, 30.0]):
        _write_fold_json(
            diag_dir,
            fold_id=fold_id,
            side_label="long",
            model_id=model_id,
            gain_by_column={"featA": gain},
            concentration_shares={"featA": gain / 60.0},
        )
    out = attr.gain_by_side(diag_dir, model_id)
    row = out.filter((pl.col("feature") == "featA") & (pl.col("side") == "long")).row(
        0, named=True
    )
    assert row["gain_mean"] == pytest.approx(20.0)
    assert row["gain_std"] == pytest.approx(10.0)
    assert row["n_folds"] == 3
    assert row["model_id"] == model_id


def test_gain_by_side_coluna_ausente_em_um_fold_vira_zero(tmp_path: Path) -> None:
    """`gain_by_column` só precisa conter as colunas que o booster de fato
    usou (mesma convenção de `src.models.hhi.compute_concentration`) —
    ausência num fold específico entra como `0.0` nesse fold, não é
    omitida da média."""
    model_id = "test_model"
    diag_dir = tmp_path / model_id / "diagnostics"
    _write_fold_json(
        diag_dir,
        fold_id=0,
        side_label="long",
        model_id=model_id,
        gain_by_column={"featA": 100.0, "featB": 5.0},
        concentration_shares={"featA": 0.95, "featB": 0.05},
    )
    _write_fold_json(
        diag_dir,
        fold_id=1,
        side_label="long",
        model_id=model_id,
        gain_by_column={"featA": 100.0},  # featB nao usada neste fold
        concentration_shares={"featA": 1.0, "featB": 0.0},
    )
    out = attr.gain_by_side(diag_dir, model_id)
    row_b = out.filter((pl.col("feature") == "featB") & (pl.col("side") == "long")).row(
        0, named=True
    )
    assert row_b["gain_mean"] == pytest.approx(2.5)  # (5.0 + 0.0) / 2


def test_gain_by_side_um_fold_so_desvio_e_zero(tmp_path: Path) -> None:
    model_id = "test_model"
    diag_dir = tmp_path / model_id / "diagnostics"
    _write_fold_json(
        diag_dir,
        fold_id=0,
        side_label="short",
        model_id=model_id,
        gain_by_column={"featA": 42.0},
        concentration_shares={"featA": 1.0},
    )
    out = attr.gain_by_side(diag_dir, model_id)
    row = out.row(0, named=True)
    assert row["gain_std"] == 0.0
    assert row["n_folds"] == 1


def test_gain_by_side_model_id_divergente_levanta_valueerror(tmp_path: Path) -> None:
    diag_dir = tmp_path / "model_a" / "diagnostics"
    _write_fold_json(
        diag_dir,
        fold_id=0,
        side_label="long",
        model_id="model_a",
        gain_by_column={"featA": 1.0},
        concentration_shares={"featA": 1.0},
    )
    with pytest.raises(ValueError, match="model_id"):
        attr.gain_by_side(diag_dir, "model_b")


def test_gain_by_side_diretorio_sem_arquivos_levanta_filenotfound(tmp_path: Path) -> None:
    empty_dir = tmp_path / "vazio"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        attr.gain_by_side(empty_dir, "qualquer_model")


def test_gain_by_side_so_um_lado_presente_nao_quebra(tmp_path: Path) -> None:
    model_id = "test_model"
    diag_dir = tmp_path / model_id / "diagnostics"
    _write_fold_json(
        diag_dir,
        fold_id=0,
        side_label="long",
        model_id=model_id,
        gain_by_column={"featA": 1.0},
        concentration_shares={"featA": 1.0},
    )
    out = attr.gain_by_side(diag_dir, model_id)
    assert set(out["side"].unique().to_list()) == {"long"}


# ============================================================================
# feature_agreement — rankings sintéticos, correlação de rank conhecida
# ============================================================================


def test_feature_agreement_ranking_identico_da_1() -> None:
    gain_ranking = pl.DataFrame(
        {"feature": ["a", "b", "c", "d", "e"], "gain_mean": [5, 4, 3, 2, 1]}
    )
    ic_ranking = pl.DataFrame(
        {"feature": ["a", "b", "c", "d", "e"], "ic_value": [0.5, 0.4, 0.3, 0.2, 0.1]}
    )
    metric = attr.feature_agreement(gain_ranking, ic_ranking)
    assert metric.value == pytest.approx(1.0)
    assert metric.valid is True
    assert metric.n == 5
    assert metric.n_semantics == "features"
    assert metric.unit.value == "ratio"


def test_feature_agreement_ranking_invertido_da_menos_1() -> None:
    gain_ranking = pl.DataFrame(
        {"feature": ["a", "b", "c", "d", "e"], "gain_mean": [5, 4, 3, 2, 1]}
    )
    ic_ranking = pl.DataFrame(
        {"feature": ["a", "b", "c", "d", "e"], "ic_value": [0.1, 0.2, 0.3, 0.4, 0.5]}
    )
    metric = attr.feature_agreement(gain_ranking, ic_ranking)
    assert metric.value == pytest.approx(-1.0)


def test_feature_agreement_so_features_em_comum_entram() -> None:
    gain_ranking = pl.DataFrame(
        {"feature": ["a", "b", "c", "d", "e", "f"], "gain_mean": [6, 5, 4, 3, 2, 1]}
    )
    ic_ranking = pl.DataFrame(
        {"feature": ["a", "b", "c", "d", "e"], "ic_value": [0.5, 0.4, 0.3, 0.2, 0.1]}
    )
    metric = attr.feature_agreement(gain_ranking, ic_ranking)
    assert metric.n == 5  # "f" só está em gain_ranking, não entra


def test_feature_agreement_colunas_extras_levanta_valueerror() -> None:
    gain_ranking = pl.DataFrame(
        {
            "feature": ["a", "b", "c", "d", "e"],
            "gain_mean": [5, 4, 3, 2, 1],
            "extra": [1, 2, 3, 4, 5],
        }
    )
    ic_ranking = pl.DataFrame(
        {"feature": ["a", "b", "c", "d", "e"], "ic_value": [0.5, 0.4, 0.3, 0.2, 0.1]}
    )
    with pytest.raises(ValueError, match="gain_ranking"):
        attr.feature_agreement(gain_ranking, ic_ranking)


def test_feature_agreement_feature_duplicada_levanta_valueerror() -> None:
    gain_ranking = pl.DataFrame({"feature": ["a", "a", "b"], "gain_mean": [5, 4, 3]})
    ic_ranking = pl.DataFrame({"feature": ["a", "b"], "ic_value": [0.5, 0.4]})
    with pytest.raises(ValueError, match="repetidos"):
        attr.feature_agreement(gain_ranking, ic_ranking)


def test_feature_agreement_amostra_insuficiente_marca_invalido() -> None:
    gain_ranking = pl.DataFrame({"feature": ["a", "b", "c"], "gain_mean": [3, 2, 1]})
    ic_ranking = pl.DataFrame({"feature": ["a", "b", "c"], "ic_value": [0.3, 0.2, 0.1]})
    metric = attr.feature_agreement(gain_ranking, ic_ranking)
    assert metric.valid is False
    assert math.isnan(metric.value)


# ============================================================================
# Integração real — skip se predictions/labels/diagnostics ainda não existem
# ============================================================================


def _skip_if_real_artifacts_missing(model_id: str) -> None:
    from src.models._paths import PREDICTIONS_OUTPUT_DIR
    from src.models.pipeline import MODELS_DIR
    from src.validation._paths import LABELS_OUTPUT_DIR

    preds_path = PREDICTIONS_OUTPUT_DIR / "alpha" / model_id / "predictions.parquet"
    labels_path = LABELS_OUTPUT_DIR / "v1" / "labels.parquet"
    diag_dir = MODELS_DIR / model_id / "diagnostics"
    missing = [
        str(p) for p in (preds_path, labels_path) if not p.exists()
    ]
    if not diag_dir.exists() or not list(diag_dir.glob("fold_*_long.json")):
        missing.append(str(diag_dir))
    if missing:
        pytest.skip(f"artefato(s) real(is) ausente(s), rode o pipeline primeiro: {missing}")


def test_integracao_real_ic_by_regime_e_gain_by_side_e_feature_agreement() -> None:
    from src.features.build import T1_FEATURE_IDS
    from src.models import dataset as ds
    from src.models._paths import PREDICTIONS_OUTPUT_DIR
    from src.models.pipeline import MODEL_ID_CAMADA1, MODELS_DIR
    from src.validation._paths import LABELS_OUTPUT_DIR

    model_id = MODEL_ID_CAMADA1
    _skip_if_real_artifacts_missing(model_id)

    predictions = pl.read_parquet(
        PREDICTIONS_OUTPUT_DIR / "alpha" / model_id / "predictions.parquet"
    )
    labels = pl.read_parquet(LABELS_OUTPUT_DIR / "v1" / "labels.parquet")
    mf = ds.build_modeling_frame()  # ~14s medido (ver test_models_dataset.py)
    regimes = mf.data.select(["t0", "regime", *T1_FEATURE_IDS])

    ic_df = attr.ic_by_regime(predictions, labels, regimes, T1_FEATURE_IDS)
    assert ic_df.height == len(T1_FEATURE_IDS) * ic_df["regime"].n_unique()
    assert ic_df.schema == attr._IC_OUTPUT_SCHEMA
    assert set(ic_df["ic_valid"].to_list()) <= {True, False}
    valid_ic = ic_df.filter(pl.col("ic_valid"))
    assert (valid_ic["ic_value"] >= -1.0).all()
    assert (valid_ic["ic_value"] <= 1.0).all()
    assert (valid_ic["ic_n"] > 0).all()

    gain_df = attr.gain_by_side(MODELS_DIR / model_id / "diagnostics", model_id)
    assert gain_df.height > 0
    assert set(gain_df["side"].unique().to_list()) <= {"long", "short"}

    gain_ranking_long = (
        gain_df.filter(pl.col("side") == "long")
        .select(["feature", "gain_mean"])
        .filter(pl.col("feature").is_in(T1_FEATURE_IDS))
    )
    ic_ranking_long = ic_df.group_by("feature").agg(pl.col("ic_value").mean().alias("ic_value"))
    agreement = attr.feature_agreement(gain_ranking_long, ic_ranking_long)
    assert agreement.n_semantics == "features"
    assert agreement.n == len(T1_FEATURE_IDS)
    if agreement.valid:
        assert -1.0 <= agreement.value <= 1.0
