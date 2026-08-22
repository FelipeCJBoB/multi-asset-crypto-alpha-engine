"""Testes de `src.models.persistence` — AG-141 (persistência de
modelo/calibrador). Round-trip real com `xgboost`/`sklearn.isotonic`,
não mocks — o achado central deste módulo (booster/calibrador
recarregados reproduzem inferência bit-exata) só é provado com objetos
reais."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression

from src.models.persistence import (
    ModelBundleExistsError,
    ModelBundleNotFoundError,
    UnsupportedBundleFormatError,
    model_bundle_exists,
    model_dir,
    read_model_bundle,
    write_model_bundle,
)

_FEATURE_IDS = ("A05_ret_vol_norm_4", "B01_placeholder", "C07_vol_pctile_expanding")
_MONOTONE = (0, 1, -1)


def _fit_real_side_model() -> tuple[xgb.Booster, IsotonicRegression, np.ndarray]:
    """Treina um booster + calibrador REAIS sobre dado sintético
    determinístico (seed fixa) — não é fixture de propósito estatístico,
    só precisa ser um objeto real de cada classe pra provar o round-trip
    de serialização."""
    rng = np.random.default_rng(7)
    n = 200
    x = rng.random((n, len(_FEATURE_IDS)))
    y = (x[:, 0] + 0.3 * x[:, 1] - 0.2 * x[:, 2] > 0.5).astype(np.int64)  # noqa: magic-number

    model = xgb.XGBClassifier(
        n_estimators=10,
        max_depth=3,
        tree_method="hist",
        objective="binary:logistic",
        monotone_constraints=_MONOTONE,
        random_state=0,
    )
    model.fit(x, y)
    booster = model.get_booster()

    raw = model.predict_proba(x)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(raw, y)

    return booster, calibrator, x


def test_write_read_round_trip_reproduz_inferencia_bit_exata(tmp_path: Path) -> None:
    booster, calibrator, x = _fit_real_side_model()
    tau = 0.42  # noqa: magic-number

    manifest = write_model_bundle(
        root=tmp_path,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
        booster=booster,
        calibrator=calibrator,
        tau=tau,
        feature_ids=_FEATURE_IDS,
        monotone_constraints=_MONOTONE,
    )
    assert manifest.feature_ids == _FEATURE_IDS
    assert manifest.monotone_constraints == _MONOTONE
    assert manifest.tau == tau

    loaded = read_model_bundle(
        tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
    )

    expected = calibrator.predict(booster.predict(xgb.DMatrix(x)))
    actual = loaded.predict_proba_calibrated(x)
    assert np.max(np.abs(expected - actual)) == 0.0
    assert loaded.manifest == manifest


def test_write_model_bundle_imutavel_recusa_sobrescrita(tmp_path: Path) -> None:
    booster, calibrator, _x = _fit_real_side_model()
    kwargs = {
        "root": tmp_path,
        "model_id": "alpha_c1_v1",
        "fold_id": "fold0",
        "side": 1,
        "variant": "camada1",
        "booster": booster,
        "calibrator": calibrator,
        "tau": 0.5,
        "feature_ids": _FEATURE_IDS,
        "monotone_constraints": _MONOTONE,
    }
    write_model_bundle(**kwargs)
    with pytest.raises(ModelBundleExistsError):
        write_model_bundle(**kwargs)


def test_read_model_bundle_inexistente_levanta_not_found(tmp_path: Path) -> None:
    with pytest.raises(ModelBundleNotFoundError):
        read_model_bundle(
            tmp_path, model_id="nao_existe", fold_id="fold0", side=1, variant="camada1"
        )


def test_model_bundle_exists(tmp_path: Path) -> None:
    booster, calibrator, _x = _fit_real_side_model()
    assert not model_bundle_exists(
        tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
    )
    write_model_bundle(
        root=tmp_path,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
        booster=booster,
        calibrator=calibrator,
        tau=0.5,
        feature_ids=_FEATURE_IDS,
        monotone_constraints=_MONOTONE,
    )
    assert model_bundle_exists(
        tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
    )


def test_model_dir_usa_side_numerico_nao_long_short(tmp_path: Path) -> None:
    """Convenção de path bate com calibrator_id já em produção
    (`src/models/alpha.py`, f"{model_id}_side1_fold..._calibrator")."""
    d_long = model_dir(tmp_path, model_id="m", fold_id="f0", side=1, variant="camada1")
    d_short = model_dir(tmp_path, model_id="m", fold_id="f0", side=-1, variant="camada1")
    assert "side=1" in str(d_long)
    assert "side=-1" in str(d_short)
    assert d_long != d_short


def test_read_model_bundle_formato_de_booster_desconhecido_levanta_erro(
    tmp_path: Path,
) -> None:
    """Achado de desenho: manifest com booster_format desconhecido nunca
    deve tentar desserializar às cegas -- simula um bundle escrito por
    uma versão futura do código (ex. pós-migração LightGBM) sendo lido
    por esta versão."""
    booster, calibrator, _x = _fit_real_side_model()
    write_model_bundle(
        root=tmp_path,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
        booster=booster,
        calibrator=calibrator,
        tau=0.5,
        feature_ids=_FEATURE_IDS,
        monotone_constraints=_MONOTONE,
    )
    dest_dir = model_dir(
        tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
    )
    manifest_path = dest_dir / "manifest.json"
    corrupted = manifest_path.read_text(encoding="utf-8").replace(
        "xgboost_ubj_v1", "lightgbm_txt_v1"
    )
    manifest_path.write_text(corrupted, encoding="utf-8")

    with pytest.raises(UnsupportedBundleFormatError):
        read_model_bundle(
            tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
        )
