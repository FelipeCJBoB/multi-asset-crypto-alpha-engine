"""Persistência de modelo/calibrador por (symbol, resolution_id) × fold ×
lado × variante — AG-141 (`audit/architecture_gaps_log.yaml`). Sem isto,
`run_layer1_sprint` produzia só `predictions.parquet` (probabilidades já
calibradas de um conjunto de teste fixo) + JSONs de diagnóstico —
bloqueava por construção qualquer inferência fora do processo de treino
(`13_EXECUCAO` ao vivo, paper-trading).

**Desenho AGNÓSTICO AO LEARNER** (decisão registrada em
`PLANO_MESTRE_PRINCE2.md §15.18`): reusa as primitivas de `src.io.
artifact` (`atomic_write_bytes`/`atomic_rename_dir`/`sha256_bytes`,
mesma disciplina de proveniência-por-hash e imutabilidade — V-05) sem
forçar o formato DataFrame-centric de `write_artifact` (esse fica como
está, escopo do action item 2 do ADR-001 preservado). Só as chamadas de
(des)serialização do booster em `write_model_bundle`/`read_model_bundle`
conhecem o formato específico do learner — quando a migração pra
LightGBM (`§15.14`) aconteceu (D-12, `docs/alpha_model_design_doc_
2026-08-22.md`), foi exatamente essa a ÚNICA peça que mudou; o resto
(calibrador, manifest, escrita atômica, `ModelBundleManifest.
booster_format` já versionado) foi 100% reusado.

**`model_dir` chaveado por `(symbol, resolution_id, model_id, fold_id,
side, variant)`** (D-12, fecha `AG-158`) — antes só `(model_id, fold_id,
side, variant)`, sem eixo de grade/ativo, inconsistente com `_paths.py`
(`predictions_symbol_tf_dir`/`models_diagnostics_symbol_tf_dir`, que já
usavam esse eixo) e com risco real de colisão sob as 15 combinações
(5 símbolos × 3 resoluções) que a migração LightGBM introduz.

**Formato do booster: texto, não binário** (D-12) — `booster_.
save_model(path)`/`booster_.model_to_string()` (LightGBM) em vez de
`.save_raw(raw_format="ubj")` (XGBoost). `_BOOSTER_FORMAT =
"lightgbm_txt_v1"` versiona o MECANISMO, não só o schema de dado —
`read_model_bundle` recusa desserializar um formato desconhecido às
cegas, nunca tenta.

**Tensão declarada, não resolvida aqui (D-12/D-18):** a garantia de
reload bit-exato (`test_write_read_round_trip_reproduz_inferencia_
bit_exata`, `golden`) depende de `deterministic=True` no construtor do
`LGBMClassifier` (ver `src.models.alpha.fit_side_model`) — sem isso, soma
de gradiente em histograma multi-thread não é bit-exata por padrão. D-18
implementado (`device_type`, default `"cpu"` em `fit_side_model`/
`run_fold`/`run_all_folds`, `"cuda"` só no caller de produção real,
`pipeline.run_layer1_sprint`) -- mas se `deterministic=True` também
garante bit-exato sob GPU (redução paralela de histograma pode não seguir
a mesma disciplina do caminho CPU) **não foi medido** (TBD -- design doc
§3 D-18 já nomeia a saída se não garantir: trocar a igualdade exata por
tolerância numérica, documentando a mudança). Os testes deste módulo
(`_fit_real_side_model`) treinam sob `device_type="cpu"` (default) --
não exercitam GPU, então não provam nem refutam essa garantia.

**Achado real durante o desenho original (AG-141)**: `docs/ADR-001_
arquitetura_artefatos_e_contratos_2026-08-19_base.md` §4.9 assume
calibração via Platt scaling ("aplicação ao vivo é `1/(1+exp(A*p+B))`,
três linhas, sem sklearn no runtime"). O código real (`src.models.alpha.
fit_side_model`) usa `sklearn.isotonic.IsotonicRegression`, não Platt —
não reduz a 2 coeficientes. Persistido como os dois arrays fitted
(`X_thresholds_`/`y_thresholds_`); reconstrução em produção via
`np.interp(x, X_thresholds_, y_thresholds_)`. Ainda sem sklearn no
runtime de inferência, só o MECANISMO difere do que o ADR previu —
divergência registrada aqui e em `PLANO_MESTRE_PRINCE2.md`, não
escondida. Este mecanismo é agnóstico ao learner e não mudou com D-12.

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
diretamente, fechando a lacuna entre alegação e prova."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import orjson
import polars as pl
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

_BOOSTER_NAME = "booster.txt"
_CALIBRATOR_NAME = "calibrator.json"
_MANIFEST_NAME = "manifest.json"
_SUCCESS_NAME = "_SUCCESS"

# Tag de formato versionada -- não o formato em si (isso é o que muda
# quando o learner mudar de novo). read_model_bundle despacha por este
# campo; um formato desconhecido levanta erro explícito, nunca tenta
# desserializar às cegas. "xgboost_ubj_v1" (formato anterior, pré-D-12)
# não é mais produzido por este código -- um bundle nesse formato agora
# levanta UnsupportedBundleFormatError, mesmo tratamento que qualquer
# outro formato desconhecido.
_BOOSTER_FORMAT = "lightgbm_txt_v1"
_CALIBRATOR_FORMAT = "isotonic_interp_v1"


def model_dir(
    root: Path,
    *,
    symbol: str,
    resolution_id: str,
    model_id: str,
    fold_id: str,
    side: int,
    variant: str,
) -> Path:
    """`{root}/models/{symbol}/{resolution_id}/{model_id}/fold={fold_id}/
    side={side}/variant={variant}/` -- `side{N}` (não "long"/"short") pra
    bater com a convenção já em produção de `calibrator_id`
    (`src/models/alpha.py`: `f"{model_id}_side1_fold{split.split_id}_
    calibrator"`). `symbol`/`resolution_id` (D-12, fecha `AG-158`) --
    mesma convenção de segmento de path que `_paths.py` já usa para
    `predictions_symbol_tf_dir`/`models_diagnostics_symbol_tf_dir`;
    sem esses dois eixos, (BTC, R1) e (ETH, R1) treinados com o mesmo
    `model_id` textual colidiriam no mesmo diretório."""
    return (
        root
        / "models"
        / symbol
        / resolution_id
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


class ManifestFeatureMismatchError(Exception):
    """`manifest.feature_ids` (ordenado) diverge de `booster.feature_name()`
    -- item 10 de `ADR-005 §13.17` (`§13.5-5`). Sem esta checagem, um
    booster carregado com nomes de feature diferentes do manifest
    produziria inferência SILENCIOSAMENTE errada (`LoadedSideModel.
    predict_proba_calibrated` seleciona colunas por `manifest.feature_ids`,
    não pelo booster) -- falha alto em vez disso."""


@dataclass(frozen=True, slots=True)
class ModelBundleManifest:
    """Proveniência do bundle (mesma disciplina de `src.io.artifact.
    ArtifactManifest`, INV-B) -- `symbol`/`resolution_id`/`model_id`/
    `fold_id`/`side`/`variant` identificam a partição; `booster_format`/
    `calibrator_format` versionam o MECANISMO de serialização, não só o
    schema de dado.

    **`ess`/`purge_ms_effective`/`min_child_samples`/`feature_set_hash`**
    (item 10 de `ADR-005 §13.17`, `§13.5-5`) -- a célula é a unidade de
    configuração, e o manifest declara o que ela de fato usou:
    `ess` é `Σ uniqueness` do TREINO deste fold/lado (`SideModelResult.
    sum_uniqueness_train`, já medido — AG-211 — nunca uma das fórmulas
    fechadas que B24 proíbe); `purge_ms_effective` é a saída de
    `features.build.compute_max_feature_lookback_ms` para o vetor
    REAL deste treino (item 1, AG-298); `feature_set_hash` é
    `sha256` do CONJUNTO ordenado alfabeticamente de `feature_ids`
    (join por `,`) -- "conjunto", não "vetor": não se destina a
    substituir a checagem de ORDEM abaixo, só a detectar troca de
    QUAIS features entraram, célula a célula, sem abrir o JSON.

    **`min_child_samples` não é "derivado por ESS" ainda** (`§13.5-3`/
    item 8 de `§13.17` seguem `ASSUMED`, não implementados -- bloqueados
    atrás do retreino represado, decisão do Manager 2026-08-26): o campo
    grava o valor REALMENTE usado no treino (`LGBMHyperparams.
    min_child_samples`), o que já é proveniência honesta hoje, e passa a
    refletir a fórmula de `§13.5-3` no dia em que o item 8 for
    implementado -- sem precisar de outra migração de schema.

    **Verificação na carga** (a outra metade do item 10): `read_model_
    bundle` levanta `ManifestFeatureMismatchError` se `manifest.
    feature_ids != tuple(booster.feature_name())` -- ORDENADO, não como
    conjunto. A ordem importa de verdade: `LoadedSideModel.
    predict_proba_calibrated` seleciona colunas por `manifest.
    feature_ids` (não por `booster.feature_name()`) antes de virar array
    posicional para o booster cru -- se os dois divergissem em ordem
    (não só em conteúdo), a inferência ficaria SILENCIOSAMENTE errada
    (colunas permutadas entregues a um booster que só respeita posição).
    Este é exatamente o bug que a checagem existe para impedir antes que
    aconteça, não depois."""

    symbol: str
    resolution_id: str
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
    ess: float
    purge_ms_effective: int
    min_child_samples: int
    feature_set_hash: str

    def to_json_bytes(self) -> bytes:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "resolution_id": self.resolution_id,
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
            "ess": self.ess,
            "purge_ms_effective": self.purge_ms_effective,
            "min_child_samples": self.min_child_samples,
            "feature_set_hash": self.feature_set_hash,
        }
        return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2)

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ModelBundleManifest:
        payload = orjson.loads(raw)
        return cls(
            symbol=payload["symbol"],
            resolution_id=payload["resolution_id"],
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
            ess=payload["ess"],
            purge_ms_effective=payload["purge_ms_effective"],
            min_child_samples=payload["min_child_samples"],
            feature_set_hash=payload["feature_set_hash"],
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
    inferência fora do processo de treino, sem `LGBMClassifier` nem
    sklearn no runtime (só `lgb.Booster` cru + `IsotonicCalibratorView`)."""

    manifest: ModelBundleManifest
    booster: lgb.Booster
    calibrator: IsotonicCalibratorView

    def predict_proba_calibrated(self, df: pl.DataFrame) -> FloatArray:
        """`df` precisa conter todas as colunas de `manifest.feature_ids`
        -- em QUALQUER ordem. Reproduz `calibrator.predict(model.
        predict_proba(x)[:, 1])` do treino, sem `LGBMClassifier`/sklearn
        no runtime (verificado empiricamente com os pontos do fit -- ver
        ressalva de `AG-148` no docstring do módulo).

        **Herdado de `AG-146` (era XGBoost, mesma disciplina sob
        LightGBM):** seleção por NOME via `df.select(feature_ids)` --
        garante que a ORDEM de `df` nunca importa (o `lgb.Booster.
        predict` cru sobre um array numpy só respeita ORDEM POSICIONAL,
        não nomes -- ao contrário do `XGBClassifier`/`DMatrix` anterior,
        não há guarda de nome embutida no `Booster` na hora de prever;
        a correção vem inteira de selecionar as colunas de `df` nesta
        ordem, ANTES de virar array). Coluna faltando/com nome errado
        levanta `polars.exceptions.ColumnNotFoundError` explícito, nunca
        produz predição sobre dado errado em silêncio."""
        x = df.select(list(self.manifest.feature_ids)).to_numpy().astype(np.float64)
        raw = self.booster.predict(x)
        return self.calibrator.predict(np.asarray(raw, dtype=np.float64))


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
    symbol: str,
    resolution_id: str,
    model_id: str,
    fold_id: str,
    side: int,
    variant: str,
    booster: lgb.Booster,
    calibrator: IsotonicRegression,
    tau: float,
    feature_ids: tuple[str, ...],
    monotone_constraints: tuple[int, ...],
    ess: float,
    purge_ms_effective: int,
    min_child_samples: int,
) -> ModelBundleManifest:
    """Escreve o bundle (booster + calibrador + manifest) de forma
    imutável -- mesmo padrão `.tmp` → `fsync` → `os.rename` de
    `src.io.artifact.write_artifact` (V-05), reusando as primitivas de
    lá em vez de reimplementar. Levanta `ModelBundleExistsError` se a
    partição já existir (booster/calibrador de um fold treinado não são
    sobrescritos silenciosamente -- reduz o risco de "código não bate
    com o que está rodando" que motivou adiar este item originalmente).

    `booster` é o `lgb.Booster` cru (`LGBMClassifier.booster_`) -- já
    carrega `feature_name` real (D-08/D-12: `src.models.alpha.
    fit_side_model` passa `feature_name=list(DESIGN_COLUMNS)` no `.fit`),
    então, ao contrário do XGBoost anterior, esta função NÃO precisa
    copiar/mutar o booster para injetar nomes de feature antes de
    serializar -- `model_to_string()` já embute o que foi passado no
    treino. A garantia de ORDEM correta na inferência continua vindo de
    `LoadedSideModel.predict_proba_calibrated` selecionar por NOME via
    `pl.DataFrame.select` (AG-146), não deste embutimento isoladamente."""
    dest_dir = model_dir(
        root,
        symbol=symbol,
        resolution_id=resolution_id,
        model_id=model_id,
        fold_id=fold_id,
        side=side,
        variant=variant,
    )
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
        booster_bytes = booster.model_to_string().encode("utf-8")
        atomic_write_bytes(tmp_dir / _BOOSTER_NAME, booster_bytes)

        calibrator_bytes = _serialize_calibrator(calibrator)
        atomic_write_bytes(tmp_dir / _CALIBRATOR_NAME, calibrator_bytes)

        # Hash do CONJUNTO (ordenado alfabeticamente, não na ordem de
        # treino) -- deriva sempre de `feature_ids`, nunca aceito do
        # caller, mesma disciplina de `booster_sha256`/`calibrator_sha256`
        # abaixo (evita drift entre o hash gravado e o conteúdo real).
        feature_set_hash = sha256_bytes(
            ",".join(sorted(feature_ids)).encode("utf-8")
        )

        manifest = ModelBundleManifest(
            symbol=symbol,
            resolution_id=resolution_id,
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
            ess=ess,
            purge_ms_effective=purge_ms_effective,
            min_child_samples=min_child_samples,
            feature_set_hash=feature_set_hash,
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
    root: Path,
    *,
    symbol: str,
    resolution_id: str,
    model_id: str,
    fold_id: str,
    side: int,
    variant: str,
) -> LoadedSideModel:
    """Carrega o bundle de 1 partição -- falha alto (`Unsupported
    BundleFormatError`) se `booster_format`/`calibrator_format` do
    manifest não forem reconhecidos por esta versão do código, nunca
    tenta desserializar um formato desconhecido às cegas."""
    dest_dir = model_dir(
        root,
        symbol=symbol,
        resolution_id=resolution_id,
        model_id=model_id,
        fold_id=fold_id,
        side=side,
        variant=variant,
    )
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
    booster = lgb.Booster(model_str=booster_bytes.decode("utf-8"))

    # Item 10 (`ADR-005 §13.17`, `§13.5-5`) -- ORDENADO, não como conjunto
    # (ver docstring de `ManifestFeatureMismatchError`): `predict_proba_
    # calibrated` seleciona colunas por `manifest.feature_ids`, então uma
    # divergência de ORDEM (não só de conteúdo) produziria inferência
    # silenciosamente errada se não fosse pega aqui.
    booster_feature_names = tuple(booster.feature_name())
    if manifest.feature_ids != booster_feature_names:
        raise ManifestFeatureMismatchError(
            f"read_model_bundle: manifest.feature_ids={manifest.feature_ids} != "
            f"booster.feature_name()={booster_feature_names} em {dest_dir} -- bundle "
            "corrompido ou gerado por um caminho de escrita que não passou por "
            "write_model_bundle; recusando inferência sobre correspondência incerta"
        )

    calibrator = _deserialize_calibrator((dest_dir / _CALIBRATOR_NAME).read_bytes())

    return LoadedSideModel(manifest=manifest, booster=booster, calibrator=calibrator)


def model_bundle_exists(
    root: Path,
    *,
    symbol: str,
    resolution_id: str,
    model_id: str,
    fold_id: str,
    side: int,
    variant: str,
) -> bool:
    dest_dir = model_dir(
        root,
        symbol=symbol,
        resolution_id=resolution_id,
        model_id=model_id,
        fold_id=fold_id,
        side=side,
        variant=variant,
    )
    return (dest_dir / _SUCCESS_NAME).exists()


__all__ = [
    "IsotonicCalibratorView",
    "LoadedSideModel",
    "ManifestFeatureMismatchError",
    "ModelBundleExistsError",
    "ModelBundleManifest",
    "ModelBundleNotFoundError",
    "UnsupportedBundleFormatError",
    "model_bundle_exists",
    "model_dir",
    "read_model_bundle",
    "write_model_bundle",
]
