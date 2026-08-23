"""Testes de `src.models.persistence` — AG-141 (persistência de
modelo/calibrador). Round-trip real com `lightgbm`/`sklearn.isotonic`,
não mocks — o achado central deste módulo (booster/calibrador
recarregados reproduzem inferência bit-exata) só é provado com objetos
reais.

Migração XGBoost -> LightGBM (D-12, `docs/alpha_model_design_doc_
2026-08-22.md`) -- fixture `_fit_real_side_model()` reescrita para
`lgb.LGBMClassifier`/`lgb.Booster`; `symbol`/`resolution_id` (D-12, fecha
`AG-158`) passam a ser argumentos obrigatórios de `model_dir`/
`write_model_bundle`/`read_model_bundle`/`model_bundle_exists`."""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
import pytest
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
_SYMBOL = "BTCUSDT"
_RESOLUTION_ID = "R1"


def _fit_real_side_model() -> tuple[lgb.Booster, IsotonicRegression, np.ndarray]:
    """Treina um booster + calibrador REAIS sobre dado sintético
    determinístico (seed fixa) — não é fixture de propósito estatístico,
    só precisa ser um objeto real de cada classe pra provar o round-trip
    de serialização. `feature_name=` explícito no `.fit` (mesmo fix de
    `src.models.alpha.fit_side_model`, achado de implementação D-08/D-12):
    sem isso, `booster.feature_name()` devolveria "Column_0"/"Column_1"/...
    em vez do nome real da feature."""
    rng = np.random.default_rng(7)
    n = 200
    x = rng.random((n, len(_FEATURE_IDS)))
    y = (x[:, 0] + 0.3 * x[:, 1] - 0.2 * x[:, 2] > 0.5).astype(np.int64)  # noqa: magic-number

    model = lgb.LGBMClassifier(
        n_estimators=10,
        max_depth=3,
        objective="binary",
        monotone_constraints=list(_MONOTONE),
        random_state=0,
        deterministic=True,
        verbosity=-1,
    )
    model.fit(x, y, feature_name=list(_FEATURE_IDS))
    booster = model.booster_

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
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
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
    assert manifest.symbol == _SYMBOL
    assert manifest.resolution_id == _RESOLUTION_ID
    assert manifest.feature_ids == _FEATURE_IDS
    assert manifest.monotone_constraints == _MONOTONE
    assert manifest.tau == tau

    loaded = read_model_bundle(
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
    )

    expected = calibrator.predict(np.asarray(booster.predict(x), dtype=np.float64))
    actual = loaded.predict_proba_calibrated(_df(x))
    assert np.max(np.abs(expected - actual)) == 0.0
    assert loaded.manifest == manifest


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
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
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
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
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
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
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
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
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
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
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
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
    )
    df_faltando_coluna = _df(x).drop(_FEATURE_IDS[-1])
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        loaded.predict_proba_calibrated(df_faltando_coluna)


def test_predict_proba_calibrated_ignora_ordem_de_coluna_do_dataframe(tmp_path: Path) -> None:
    """AG-146 -- `LoadedSideModel.predict_proba_calibrated` seleciona por
    NOME (`df.select(feature_ids)`), então a ORDEM das colunas em `df`
    nunca importa -- prova isso ativamente: embaralha as colunas do
    DataFrame e confirma que a predição é IDÊNTICA à do DataFrame na
    ordem original. Sob LightGBM isso é ainda mais importante que sob
    XGBoost: `lgb.Booster.predict` sobre um array numpy cru só respeita
    ORDEM POSICIONAL, não nomes -- toda a garantia de correção vem de
    `df.select(...)` reordenar ANTES de virar array, não de nenhuma
    guarda interna do booster."""
    booster, calibrator, x = _fit_real_side_model()
    write_model_bundle(
        root=tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
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
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
    )
    df_ordem_original = _df(x)
    df_colunas_embaralhadas = df_ordem_original.select(list(reversed(_FEATURE_IDS)))
    assert df_colunas_embaralhadas.columns != list(_FEATURE_IDS)  # confirma que embaralhou de fato

    pred_original = loaded.predict_proba_calibrated(df_ordem_original)
    pred_embaralhado = loaded.predict_proba_calibrated(df_colunas_embaralhadas)
    assert np.array_equal(pred_original, pred_embaralhado)


def test_write_model_bundle_nao_muta_booster_do_caller(tmp_path: Path) -> None:
    """Herdado de `AG-146` (era XGBoost: `write_model_bundle` setava
    `booster.feature_names` no objeto RECEBIDO do caller, mutação de
    efeito colateral surpreendente, corrigida com `booster.copy()`).
    Sob LightGBM (D-12) o booster já carrega `feature_name` real desde o
    `.fit()` (ver `_fit_real_side_model`) -- `write_model_bundle` não
    precisa copiar/mutar nada, só lê `booster.model_to_string()`. Este
    teste confirma que `feature_name()` do objeto do caller continua
    idêntico depois da chamada -- guarda de regressão caso uma mutação
    seja reintroduzida no futuro."""
    booster, calibrator, _x = _fit_real_side_model()
    feature_name_antes = booster.feature_name()
    write_model_bundle(
        root=tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
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
    assert booster.feature_name() == feature_name_antes


def test_write_model_bundle_grava_feature_names_no_booster(tmp_path: Path) -> None:
    """AG-146 -- confirma que o booster PERSISTIDO e recarregado mantém
    os `feature_name` reais (D-08/D-12: `feature_name=list(_FEATURE_IDS)`
    no `.fit`, não um remapeamento pós-hoc como no XGBoost anterior) --
    não confia só no teste de não-mutação acima, verifica o estado
    positivo também."""
    booster, calibrator, _x = _fit_real_side_model()
    write_model_bundle(
        root=tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
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
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
    )
    assert loaded.booster.feature_name() == list(_FEATURE_IDS)


def test_write_model_bundle_imutavel_recusa_sobrescrita(tmp_path: Path) -> None:
    booster, calibrator, _x = _fit_real_side_model()
    kwargs = {
        "root": tmp_path,
        "symbol": _SYMBOL,
        "resolution_id": _RESOLUTION_ID,
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
            tmp_path,
            symbol=_SYMBOL,
            resolution_id=_RESOLUTION_ID,
            model_id="nao_existe",
            fold_id="fold0",
            side=1,
            variant="camada1",
        )


def test_model_bundle_exists(tmp_path: Path) -> None:
    booster, calibrator, _x = _fit_real_side_model()
    assert not model_bundle_exists(
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
    )
    write_model_bundle(
        root=tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
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
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
    )


def test_model_dir_usa_side_numerico_nao_long_short(tmp_path: Path) -> None:
    """Convenção de path bate com calibrator_id já em produção
    (`src/models/alpha.py`, f"{model_id}_side1_fold..._calibrator")."""
    d_long = model_dir(
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="m",
        fold_id="f0",
        side=1,
        variant="camada1",
    )
    d_short = model_dir(
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="m",
        fold_id="f0",
        side=-1,
        variant="camada1",
    )
    assert "side=1" in str(d_long)
    assert "side=-1" in str(d_short)
    assert d_long != d_short


def test_model_dir_chaveado_por_symbol_e_resolution_id(tmp_path: Path) -> None:
    """D-12 (fecha `AG-158`) -- (BTC, R1) e (ETH, R1) com o MESMO
    `model_id` textual não podem colidir no mesmo diretório (mesma classe
    de risco já corrigida uma vez em `dataset.py:138-160`, agora em escala
    15x maior sob 5 símbolos x 3 resoluções)."""
    d_btc = model_dir(
        tmp_path, symbol="BTCUSDT", resolution_id="R1", model_id="m", fold_id="f0", side=1,
        variant="camada1",
    )
    d_eth = model_dir(
        tmp_path, symbol="ETHUSDT", resolution_id="R1", model_id="m", fold_id="f0", side=1,
        variant="camada1",
    )
    d_r2 = model_dir(
        tmp_path, symbol="BTCUSDT", resolution_id="R2", model_id="m", fold_id="f0", side=1,
        variant="camada1",
    )
    assert d_btc != d_eth
    assert d_btc != d_r2
    assert "BTCUSDT" in str(d_btc) and "R1" in str(d_btc)


def test_read_model_bundle_formato_de_booster_desconhecido_levanta_erro(
    tmp_path: Path,
) -> None:
    """Achado de desenho: manifest com booster_format desconhecido nunca
    deve tentar desserializar às cegas. D-12: `"xgboost_ubj_v1"` era o
    formato REAL antes da migração LightGBM -- pós-migração, é exatamente
    o tipo de formato "de uma versão anterior/desconhecida" que este
    teste simula (inversão da premissa: antes o teste usava
    "lightgbm_txt_v1" como exemplo de formato futuro; agora é o formato
    real, `_BOOSTER_FORMAT`, e "xgboost_ubj_v1" é o desconhecido)."""
    booster, calibrator, _x = _fit_real_side_model()
    write_model_bundle(
        root=tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
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
        tmp_path,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        model_id="alpha_c1_v1",
        fold_id="fold0",
        side=1,
        variant="camada1",
    )
    manifest_path = dest_dir / "manifest.json"
    corrupted = manifest_path.read_text(encoding="utf-8").replace(
        "lightgbm_txt_v1", "xgboost_ubj_v1"
    )
    manifest_path.write_text(corrupted, encoding="utf-8")

    with pytest.raises(UnsupportedBundleFormatError):
        read_model_bundle(
            tmp_path,
            symbol=_SYMBOL,
            resolution_id=_RESOLUTION_ID,
            model_id="alpha_c1_v1",
            fold_id="fold0",
            side=1,
            variant="camada1",
        )
