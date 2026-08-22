"""Persistência de modelo/calibrador por fold × lado × variante — AG-141
(`audit/architecture_gaps_log.yaml`). Sem isto, `run_layer1_sprint`
produzia só `predictions.parquet` (probabilidades já calibradas de um
conjunto de teste fixo) + JSONs de diagnóstico — bloqueava por
construção qualquer inferência fora do processo de treino
(`13_EXECUCAO` ao vivo, paper-trading).

**Desenho AGNÓSTICO AO LEARNER** (decisão registrada em
`PLANO_MESTRE_PRINCE2.md §15.18`): reusa as primitivas de `src.io.
artifact` (`atomic_write_bytes`/`atomic_rename_dir`/`sha256_bytes`,
mesma disciplina de proveniência-por-hash e imutabilidade — V-05) sem
forçar o formato DataFrame-centric de `write_artifact` (esse fica como
está, escopo do action item 2 do ADR-001 preservado). Só as chamadas
`booster.save_raw(raw_format="ubj")`/`xgb.Booster().load_model(...)`
em `write_model_bundle`/`read_model_bundle` conhecem o formato binário
específico do learner (`.ubj` do XGBoost hoje) — quando a migração pra
LightGBM (`§15.14`, represada) acontecer, é a ÚNICA peça que muda; o
resto (calibrador, manifest, escrita atômica, `ModelBundleManifest.
booster_format` já versionado) é 100% reusável. Isso resolve o motivo
original do adiamento de `AG-141` ("junto da migração LightGBM, pra não
abrir 2 janelas de código não bate com o que está rodando") sem
precisar esperar a migração acontecer primeiro.

**Achado real durante o desenho**: `docs/ADR-001_arquitetura_
artefatos_e_contratos_2026-08-19_base.md` §4.9 assume calibração via
Platt scaling ("aplicação ao vivo é `1/(1+exp(A*p+B))`, três linhas,
sem sklearn no runtime"). O código real (`src.models.alpha.
fit_side_model`) usa `sklearn.isotonic.IsotonicRegression`, não Platt —
não reduz a 2 coeficientes. Persistido como os dois arrays fitted
(`X_thresholds_`/`y_thresholds_`); reconstrução em produção via
`np.interp(x, X_thresholds_, y_thresholds_)`. Ainda sem sklearn no
runtime de inferência, só o MECANISMO difere do que o ADR previu —
divergência registrada aqui e em `PLANO_MESTRE_PRINCE2.md`, não
escondida.

**Precisão de proveniência (achado de revisão `project_assurance`,
AG-148 — o texto anterior desta docstring dizia "verificado
empiricamente" para tudo, o que era impreciso):** MEDIDO
empiricamente, com teste real (`tests/unit/test_models_persistence.py`)
— pontos DENTRO do range de treino (nos próprios `X_thresholds_` e nos
patamares entre eles): `np.interp` reproduz `IsotonicRegression.
predict` com `max abs diff = 0.0`. DEDUZIDO por leitura do código-fonte
do sklearn (não medido por teste dedicado) — comportamento nas PONTAS
(`x` fora de `[X_thresholds_[0], X_thresholds_[-1]]`) e no caso
degenerado (calibrador com 1 único threshold): `IsotonicRegression.
fit` define `X_min_`/`X_max_` como os extremos do array já deduplicado
(que também vira `X_thresholds_`), e `predict()` faz `clip(T, X_min_,
X_max_)` ANTES de interpolar sob `out_of_bounds="clip"` — semântica
idêntica à extrapolação constante que `np.interp` já aplica por
padrão fora de `[xp[0], xp[-1]]`; para 1 único threshold, sklearn usa
`lambda x: y.repeat(x.shape)` e `np.interp` com `xp` de tamanho 1
também devolve sempre `fp[0]` — equivalente. Testes de caso de borda
(`test_write_read_round_trip_calibrador_fora_do_range_treinado`,
`test_write_read_round_trip_calibrador_degenerado`) MEDEM essa dedução
diretamente, fechando a lacuna entre alegação e prova.

Booster reload também MEDIDO bit-exato: `Booster.save_raw(raw_
format="ubj")` → `Booster().load_model(bytearray(...))` reproduz
`predict()` idêntico (`max abs diff = 0.0`, testado com dado
sintético). `booster.predict(DMatrix(X))` também bate bit-exato com
`XGBClassifier.predict_proba(X)[:, 1]` pra `objective="binary:
logistic"` — a classe wrapper não é necessária pra inferência, só o
`Booster` cru + `DMatrix`."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
import xgboost as xgb
from numpy.typing import NDArray
from sklearn.isotonic import IsotonicRegression

from src.core.provenance import report_provenance
from src.io.artifact import (
    ArtifactExistsError,
    ArtifactNotFoundError,
    atomic_rename_dir,
    atomic_write_bytes,
    sha256_bytes,
)

FloatArray = NDArray[np.float64]

_BOOSTER_NAME = "booster.ubj"
_CALIBRATOR_NAME = "calibrator.json"
_MANIFEST_NAME = "manifest.json"
_SUCCESS_NAME = "_SUCCESS"

# Tag de formato versionada -- não o formato em si (isso é o que muda
# quando o learner mudar, ex. "xgboost_ubj_v1" -> "lightgbm_txt_v1").
# read_model_bundle despacha por este campo; um formato desconhecido
# levanta erro explícito, nunca tenta desserializar às cegas.
_BOOSTER_FORMAT = "xgboost_ubj_v1"
_CALIBRATOR_FORMAT = "isotonic_interp_v1"


def model_dir(root: Path, *, model_id: str, fold_id: str, side: int, variant: str) -> Path:
    """`{root}/models/{model_id}/fold={fold_id}/side={side}/variant={variant}/`
    -- `side{N}` (não "long"/"short") pra bater com a convenção já em
    produção de `calibrator_id` (`src/models/alpha.py`:
    `f"{model_id}_side1_fold{split.split_id}_calibrator"`)."""
    return (
        root
        / "models"
        / model_id
        / f"fold={fold_id}"
        / f"side={side}"
        / f"variant={variant}"
    )


class ModelBundleExistsError(ArtifactExistsError):
    """Bundle de modelo já existe e é imutável -- nunca sobrescrito."""


class ModelBundleNotFoundError(ArtifactNotFoundError):
    """Nenhum bundle completo (`_SUCCESS` presente) na partição pedida."""


class UnsupportedBundleFormatError(Exception):
    """`booster_format`/`calibrator_format` do manifest não é reconhecido
    por esta versão do código -- nunca tenta desserializar às cegas."""


@dataclass(frozen=True, slots=True)
class ModelBundleManifest:
    """Proveniência do bundle (mesma disciplina de `src.io.artifact.
    ArtifactManifest`, INV-B) -- `model_id`/`fold_id`/`side`/`variant`
    identificam a partição; `booster_format`/`calibrator_format`
    versionam o MECANISMO de serialização, não só o schema de dado."""

    model_id: str
    fold_id: str
    side: int
    variant: str
    producer_version: str
    created_at_ns: int
    feature_ids: tuple[str, ...]
    monotone_constraints: tuple[int, ...]
    tau: float
    booster_format: str
    booster_sha256: str
    calibrator_format: str
    calibrator_sha256: str

    def to_json_bytes(self) -> bytes:
        payload: dict[str, Any] = {
            "model_id": self.model_id,
            "fold_id": self.fold_id,
            "side": self.side,
            "variant": self.variant,
            "producer_version": self.producer_version,
            "created_at_ns": self.created_at_ns,
            "feature_ids": list(self.feature_ids),
            "monotone_constraints": list(self.monotone_constraints),
            "tau": self.tau,
            "booster_format": self.booster_format,
            "booster_sha256": self.booster_sha256,
            "calibrator_format": self.calibrator_format,
            "calibrator_sha256": self.calibrator_sha256,
        }
        return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2)

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ModelBundleManifest:
        payload = orjson.loads(raw)
        return cls(
            model_id=payload["model_id"],
            fold_id=payload["fold_id"],
            side=payload["side"],
            variant=payload["variant"],
            producer_version=payload["producer_version"],
            created_at_ns=payload["created_at_ns"],
            feature_ids=tuple(payload["feature_ids"]),
            monotone_constraints=tuple(payload["monotone_constraints"]),
            tau=payload["tau"],
            booster_format=payload["booster_format"],
            booster_sha256=payload["booster_sha256"],
            calibrator_format=payload["calibrator_format"],
            calibrator_sha256=payload["calibrator_sha256"],
        )


class IsotonicCalibratorView:
    """Reconstrução do calibrador isotônico SEM sklearn no runtime --
    `np.interp` sobre os thresholds fitted, verificado bit-exato contra
    `IsotonicRegression.predict` (ver docstring do módulo)."""

    __slots__ = ("_x_thresholds", "_y_thresholds")

    def __init__(self, x_thresholds: FloatArray, y_thresholds: FloatArray) -> None:
        self._x_thresholds = x_thresholds
        self._y_thresholds = y_thresholds

    def predict(self, raw_scores: FloatArray) -> FloatArray:
        return np.interp(raw_scores, self._x_thresholds, self._y_thresholds)


@dataclass(frozen=True, slots=True)
class LoadedSideModel:
    """Devolvido por `read_model_bundle` -- tudo que é necessário pra
    inferência fora do processo de treino, sem `XGBClassifier` nem
    sklearn no runtime (só `xgb.Booster` cru + `IsotonicCalibratorView`)."""

    manifest: ModelBundleManifest
    booster: xgb.Booster
    calibrator: IsotonicCalibratorView

    def predict_proba_calibrated(self, df: pl.DataFrame) -> FloatArray:
        """`df` precisa conter todas as colunas de `manifest.feature_ids`
        -- em QUALQUER ordem. Reproduz `calibrator.predict(model.
        predict_proba(x)[:, 1])` do treino, sem `XGBClassifier`/sklearn
        no runtime (verificado empiricamente com os pontos do fit -- ver
        ressalva de `AG-148` no docstring do módulo).

        **Achado real de revisão (`project_assurance`, `AG-146`), e
        AUTOCORREÇÃO no mesmo achado**: a primeira versão desta função
        recebia `NDArray` cru e tentava validar ordem via
        `xgb.DMatrix(x, feature_names=...)` -- não funcionava de
        verdade (o `DMatrix` sempre era rotulado com o MESMO
        `manifest.feature_ids`, então nunca podia divergir de si mesmo
        -- guarda morta, achado durante a correção, não pela revisão
        original). Fix real: `df.select(feature_ids)` -- seleciona por
        NOME, não por posição, então a ORDEM de `df` nunca importa, e
        uma coluna faltando/com nome errado levanta
        `polars.exceptions.ColumnNotFoundError` explícito, nunca produz
        predição sobre dado errado em silêncio."""
        x = df.select(list(self.manifest.feature_ids)).to_numpy().astype(np.float64)
        dmatrix = xgb.DMatrix(x, feature_names=list(self.manifest.feature_ids))
        raw = self.booster.predict(dmatrix)
        return self.calibrator.predict(raw)


def _serialize_calibrator(calibrator: IsotonicRegression) -> bytes:
    payload = {
        "x_thresholds": calibrator.X_thresholds_.tolist(),
        "y_thresholds": calibrator.y_thresholds_.tolist(),
    }
    return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)


def _deserialize_calibrator(raw: bytes) -> IsotonicCalibratorView:
    payload = orjson.loads(raw)
    return IsotonicCalibratorView(
        x_thresholds=np.asarray(payload["x_thresholds"], dtype=np.float64),
        y_thresholds=np.asarray(payload["y_thresholds"], dtype=np.float64),
    )


def write_model_bundle(
    *,
    root: Path,
    model_id: str,
    fold_id: str,
    side: int,
    variant: str,
    booster: xgb.Booster,
    calibrator: IsotonicRegression,
    tau: float,
    feature_ids: tuple[str, ...],
    monotone_constraints: tuple[int, ...],
) -> ModelBundleManifest:
    """Escreve o bundle (booster + calibrador + manifest) de forma
    imutável -- mesmo padrão `.tmp` → `fsync` → `os.rename` de
    `src.io.artifact.write_artifact` (V-05), reusando as primitivas de
    lá em vez de reimplementar. Levanta `ModelBundleExistsError` se a
    partição já existir (booster/calibrador de um fold treinado não são
    sobrescritos silenciosamente -- reduz o risco de "código não bate
    com o que está rodando" que motivou adiar este item originalmente)."""
    dest_dir = model_dir(root, model_id=model_id, fold_id=fold_id, side=side, variant=variant)
    if (dest_dir / _SUCCESS_NAME).exists():
        raise ModelBundleExistsError(
            f"bundle de modelo já existe em {dest_dir} -- imutável, nunca sobrescrito"
        )

    # os.getpid() no nome -- achado de revisão (project_assurance, AG-147):
    # sem pid, time.monotonic_ns() sozinho pode colidir entre PROCESSOS no
    # Windows (contador de sistema compartilhado, resolução real pode não
    # ser nanossegundo) -- mesma classe de risco que AG-145 corrigiu nesta
    # mesma sessão, aqui reintroduzida de forma mais fraca. Mesmo padrão de
    # `src.io.artifact.write_artifact`.
    tmp_dir = dest_dir.parent / f".tmp-{dest_dir.name}-{os.getpid()}-{time.monotonic_ns()}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # feature_names gravado no booster ANTES de serializar -- metadado
        # útil pra quem inspecionar o .ubj fora deste módulo (ex.
        # ferramenta externa, dump manual). A garantia REAL de ordem
        # correta vem de LoadedSideModel.predict_proba_calibrated
        # selecionar por NOME via `pl.DataFrame.select` (AG-146) -- não
        # deste atributo isoladamente (achado de revisão: uma versão
        # anterior confiava só no `DMatrix(feature_names=...)` pra
        # detectar mismatch, mas isso nunca dispara sozinho porque o
        # DMatrix é rotulado com o MESMO `manifest.feature_ids`,
        # não pode divergir de si mesmo -- guarda morta, corrigida).
        #
        # `booster.copy()` -- NUNCA mutar o objeto do caller. `model.fit`
        # (XGBClassifier, achado de revisão) não seta feature_names
        # sozinho quando X é NDArray puro (é o caso real de
        # `fit_side_model`), então setar aqui é necessário -- mas fazer
        # isso no booster ORIGINAL do caller seria efeito colateral
        # surpreendente (quem chama write_model_bundle e continua usando
        # `booster` depois não deveria ver o objeto mudar de estado).
        booster_to_save = booster.copy()
        booster_to_save.feature_names = list(feature_ids)
        booster_bytes = bytes(booster_to_save.save_raw(raw_format="ubj"))
        atomic_write_bytes(tmp_dir / _BOOSTER_NAME, booster_bytes)

        calibrator_bytes = _serialize_calibrator(calibrator)
        atomic_write_bytes(tmp_dir / _CALIBRATOR_NAME, calibrator_bytes)

        manifest = ModelBundleManifest(
            model_id=model_id,
            fold_id=fold_id,
            side=side,
            variant=variant,
            producer_version=report_provenance()["code_version"],
            created_at_ns=time.time_ns(),
            feature_ids=feature_ids,
            monotone_constraints=monotone_constraints,
            tau=tau,
            booster_format=_BOOSTER_FORMAT,
            booster_sha256=sha256_bytes(booster_bytes),
            calibrator_format=_CALIBRATOR_FORMAT,
            calibrator_sha256=sha256_bytes(calibrator_bytes),
        )
        atomic_write_bytes(tmp_dir / _MANIFEST_NAME, manifest.to_json_bytes())

        # _SUCCESS por último -- autoridade (V-05), leitor ignora
        # diretório sem ele.
        (tmp_dir / _SUCCESS_NAME).touch()
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    atomic_rename_dir(tmp_dir, dest_dir)
    return manifest


def read_model_bundle(
    root: Path, *, model_id: str, fold_id: str, side: int, variant: str
) -> LoadedSideModel:
    """Carrega o bundle de 1 partição -- falha alto (`Unsupported
    BundleFormatError`) se `booster_format`/`calibrator_format` do
    manifest não forem reconhecidos por esta versão do código, nunca
    tenta desserializar um formato desconhecido às cegas."""
    dest_dir = model_dir(root, model_id=model_id, fold_id=fold_id, side=side, variant=variant)
    if not (dest_dir / _SUCCESS_NAME).exists():
        raise ModelBundleNotFoundError(f"nenhum bundle completo em {dest_dir} (sem _SUCCESS)")

    manifest = ModelBundleManifest.from_json_bytes((dest_dir / _MANIFEST_NAME).read_bytes())

    if manifest.booster_format != _BOOSTER_FORMAT:
        raise UnsupportedBundleFormatError(
            f"booster_format={manifest.booster_format!r} não suportado por esta versão "
            f"do código -- esperado {_BOOSTER_FORMAT!r}"
        )
    if manifest.calibrator_format != _CALIBRATOR_FORMAT:
        raise UnsupportedBundleFormatError(
            f"calibrator_format={manifest.calibrator_format!r} não suportado por esta "
            f"versão do código -- esperado {_CALIBRATOR_FORMAT!r}"
        )

    booster_bytes = (dest_dir / _BOOSTER_NAME).read_bytes()
    booster = xgb.Booster()
    booster.load_model(bytearray(booster_bytes))

    calibrator = _deserialize_calibrator((dest_dir / _CALIBRATOR_NAME).read_bytes())

    return LoadedSideModel(manifest=manifest, booster=booster, calibrator=calibrator)


def model_bundle_exists(
    root: Path, *, model_id: str, fold_id: str, side: int, variant: str
) -> bool:
    dest_dir = model_dir(root, model_id=model_id, fold_id=fold_id, side=side, variant=variant)
    return (dest_dir / _SUCCESS_NAME).exists()


__all__ = [
    "IsotonicCalibratorView",
    "LoadedSideModel",
    "ModelBundleExistsError",
    "ModelBundleManifest",
    "ModelBundleNotFoundError",
    "UnsupportedBundleFormatError",
    "model_bundle_exists",
    "model_dir",
    "read_model_bundle",
    "write_model_bundle",
]
