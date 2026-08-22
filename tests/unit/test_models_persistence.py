"""Testes de `src.models.persistence` — AG-141 (persistência de
modelo/calibrador). Round-trip real com `xgboost`/`sklearn.isotonic`,
não mocks — o achado central deste módulo (booster/calibrador
recarregados reproduzem inferência bit-exata) só é provado com objetos
reais."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
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


def _df(x: np.ndarray, *, columns: tuple[str, ...] = _FEATURE_IDS) -> pl.DataFrame:
    return pl.DataFrame(x, schema=list(columns))


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
    actual = loaded.predict_proba_calibrated(_df(x))
    assert np.max(np.abs(expected - actual)) == 0.0
    assert loaded.manifest == manifest
    # write_model_bundle não deve mutar o booster do caller (achado de
    # revisão corrigido com booster.copy()) -- confirma que o objeto
    # original segue sem feature_names.
    assert booster.feature_names is None


def test_write_read_round_trip_calibrador_fora_do_range_treinado(tmp_path: Path) -> None:
    """AG-148 -- fecha a lacuna entre a alegação "verificado
    empiricamente" e o que o teste original de fato exercitava (só
    pontos DENTRO do range de treino). Constrói ATIVAMENTE scores fora
    de `[X_thresholds_[0], X_thresholds_[-1]]` -- `np.interp` precisa
    reproduzir a extrapolação constante de `out_of_bounds="clip"` do
    sklearn, não só interpolar corretamente no interior."""
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
    loaded = read_model_bundle(
        tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
    )

    x_min = calibrator.X_thresholds_[0]
    x_max = calibrator.X_thresholds_[-1]
    raw_scores = np.array([x_min - 10.0, x_min - 0.01, x_max + 0.01, x_max + 10.0])  # noqa: magic-number

    expected = calibrator.predict(raw_scores)
    actual = loaded.calibrator.predict(raw_scores)
    assert np.max(np.abs(expected - actual)) == 0.0


def test_write_read_round_trip_calibrador_degenerado(tmp_path: Path) -> None:
    """AG-148 -- calibrador com um único threshold (todas as
    observações de calibração colapsam num só valor de score bruto).
    `sklearn` usa `lambda x: y.repeat(x.shape)` nesse caso;
    `np.interp` com `xp` de tamanho 1 precisa reproduzir o mesmo
    (retorna sempre `fp[0]`, independente da query)."""
    x_calib = np.array([0.5, 0.5, 0.5, 0.5])  # noqa: magic-number
    y_calib = np.array([1, 0, 1, 0])
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(x_calib, y_calib)
    assert len(calibrator.X_thresholds_) == 1  # confirma que o caso é de fato degenerado

    booster, _cal_unused, _x = _fit_real_side_model()
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
    loaded = read_model_bundle(
        tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
    )

    raw_scores = np.array([-5.0, 0.0, 0.5, 1.0, 5.0])  # noqa: magic-number
    expected = calibrator.predict(raw_scores)
    actual = loaded.calibrator.predict(raw_scores)
    assert np.max(np.abs(expected - actual)) == 0.0


def test_predict_proba_calibrated_rejeita_coluna_faltando(tmp_path: Path) -> None:
    """AG-146 -- `df` sem uma das colunas de `manifest.feature_ids`
    levanta erro explícito do Polars (`ColumnNotFoundError`), nunca
    produz predição sobre dado incompleto em silêncio."""
    booster, calibrator, x = _fit_real_side_model()
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
    loaded = read_model_bundle(
        tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
    )
    df_faltando_coluna = _df(x).drop(_FEATURE_IDS[-1])
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        loaded.predict_proba_calibrated(df_faltando_coluna)


def test_predict_proba_calibrated_ignora_ordem_de_coluna_do_dataframe(tmp_path: Path) -> None:
    """AG-146 -- achado real corrigido: a versão original desta função
    recebia `NDArray` cru e a "guarda de ordem" nunca disparava de
    verdade (o `DMatrix` interno sempre era rotulado com o mesmo
    `manifest.feature_ids`, nunca podia divergir de si mesmo -- ver
    docstring de `LoadedSideModel.predict_proba_calibrated`). O fix
    real é `df.select(feature_ids)` -- seleciona por NOME, então a
    ORDEM das colunas em `df` nunca importa. Prova isso ativamente:
    embaralha as colunas do DataFrame e confirma que a predição é
    IDÊNTICA à do DataFrame na ordem original."""
    booster, calibrator, x = _fit_real_side_model()
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
    loaded = read_model_bundle(
        tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
    )
    df_ordem_original = _df(x)
    df_colunas_embaralhadas = df_ordem_original.select(list(reversed(_FEATURE_IDS)))
    assert df_colunas_embaralhadas.columns != list(_FEATURE_IDS)  # confirma que embaralhou de fato

    pred_original = loaded.predict_proba_calibrated(df_ordem_original)
    pred_embaralhado = loaded.predict_proba_calibrated(df_colunas_embaralhadas)
    assert np.array_equal(pred_original, pred_embaralhado)


def test_write_model_bundle_nao_muta_booster_do_caller(tmp_path: Path) -> None:
    """AG-146 -- achado real corrigido: a primeira versão de
    write_model_bundle setava `booster.feature_names` no objeto
    RECEBIDO do caller (mutação de efeito colateral surpreendente).
    Fix: `booster.copy()` antes de mutar -- o objeto do caller nunca
    muda de estado."""
    booster, calibrator, _x = _fit_real_side_model()
    assert booster.feature_names is None
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
    assert booster.feature_names is None


def test_write_model_bundle_grava_feature_names_no_booster(tmp_path: Path) -> None:
    """AG-146 -- confirma que write_model_bundle de fato grava
    feature_names no booster PERSISTIDO (o da cópia, não o do caller --
    ver teste acima) -- não confia só no teste de erro, verifica o
    estado positivo também."""
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
    loaded = read_model_bundle(
        tmp_path, model_id="alpha_c1_v1", fold_id="fold0", side=1, variant="camada1"
    )
    assert loaded.booster.feature_names == list(_FEATURE_IDS)


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
