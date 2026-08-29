"""Testes de `src.models.hyperparams_by_combo` -- loader por `(symbol,
resolution_id, variant)` lendo do artefato Optuna content-addressed
(`AG-371`, 2026-08-29), não mais do YAML estático `config/alpha_
hyperparams_by_combo.yaml` (aposentado) nem de uma checagem de hash em
runtime (`HyperparamFeatureMismatchError`/`allow_feature_mismatch`,
removidos -- ver docstring do módulo pra por quê essa classe de bug deixa
de ser alcançável por construção sob content-addressing).

`io_artifact.artifact_exists`/`read_artifact` monkeypatchados direto --
nenhum teste aqui toca disco real nem `config/constants.yaml` é mockado
(os 3 metaparâmetros Optuna e os `sweep_range` que `compute_search_config_
hash` lê já existem de verdade no arquivo real; o valor exato do hash não
importa aqui, só se `artifact_exists`/`read_artifact` foram chamados)."""

from __future__ import annotations

import dataclasses
from typing import Any

import polars as pl
import pytest

from src.io import artifact as io_artifact
from src.models import hyperparams_by_combo as mod
from src.models.alpha import LGBMHyperparams

_FEATURE_IDS = ("A01", "A02", "A03")

# Conjunto COMPLETO de 16 campos de LGBMHyperparams + 11 colunas de
# metadado -- mesmo formato que `hyperparams_optuna.write_search_artifact`
# grava de verdade (ver `ALPHA_HYPERPARAMS_OPTUNA_SCHEMA`).
_HYPER_ROW: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "resolution_id": "R1",
    "variant": "camada1",
    "device_type": "cpu",
    "best_value": 1.23,
    "n_trials_run": 30,
    "sampler_name": "tpe",
    "sampler_seed": 42,
    "study_name": "alpha_hyperparams_BTCUSDT_R1_camada1_deadbeef",
    "dsr": None,
    "dsr_n_trials": None,
    "max_depth": 2,
    "n_estimators": 300,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "subsample_freq": 1,
    "feature_fraction": 1.0,
    "lambda_l2": 5.0,
    "min_child_samples": 2000,
    "num_leaves": 3,
    "min_sum_hessian_in_leaf": 0.001,
    "max_bin": 255,
    "ess_regularization_n_obs_independentes_alvo": 30.0,
    "ess_regularization_fator_conservador": 0.5,
    "regularization_basis": "ess_derived",
    "early_stopping_mode": "three_way",
    "ic_magnitude_floor_k": 2.0,
}


def _fake_manifest() -> io_artifact.ArtifactManifest:
    return io_artifact.ArtifactManifest(
        stage="alpha_hyperparams_optuna",
        schema_version="1.0.0",
        producer_version="test",
        producer_entrypoint="test",
        symbol="BTCUSDT",
        resolution="R1",
        config_hash="deadbeefdeadbeef",
        input_manifest_hash=None,
        upstream=(),
        created_at_ns=0,
        n_rows=1,
        primary_key=("variant",),
        files=(),
        content_hash="deadbeefdeadbeef",
    )


def test_combo_sem_artefato_retorna_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nenhum artefato sob o hash ativo -- cobre TANTO 'nunca rodou
    campanha' QUANTO 'rodou sob outro vetor de features/espaço de busca'
    (indistinguíveis de propósito, ver docstring do módulo)."""
    monkeypatch.setattr(io_artifact, "artifact_exists", lambda **kwargs: False)

    result = mod.load_hyperparams_by_combo(
        "BTCUSDT", "R1", "camada1", feature_ids_effective=_FEATURE_IDS
    )

    assert result is None


def test_combo_com_artefato_retorna_hyper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(io_artifact, "artifact_exists", lambda **kwargs: True)
    monkeypatch.setattr(
        io_artifact,
        "read_artifact",
        lambda **kwargs: (pl.DataFrame([_HYPER_ROW]), _fake_manifest()),
    )

    result = mod.load_hyperparams_by_combo(
        "BTCUSDT", "R1", "camada1", feature_ids_effective=_FEATURE_IDS
    )

    assert isinstance(result, LGBMHyperparams)
    assert result.num_leaves == 3
    assert result.learning_rate == 0.03
    assert result.ic_magnitude_floor_k == 2.0


def test_base_explicito_e_sobreposto_pelos_campos_do_artefato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`base` fornece só o ponto de partida -- `write_search_artifact`
    grava os 16 campos COMPLETOS (não só os historicamente buscados), então
    todo campo do artefato sobrepõe `base`, nunca o contrário."""
    monkeypatch.setattr(io_artifact, "artifact_exists", lambda **kwargs: True)
    monkeypatch.setattr(
        io_artifact,
        "read_artifact",
        lambda **kwargs: (pl.DataFrame([_HYPER_ROW]), _fake_manifest()),
    )
    custom_base = dataclasses.replace(LGBMHyperparams.from_constants(), max_depth=99)

    result = mod.load_hyperparams_by_combo(
        "BTCUSDT", "R1", "camada1", feature_ids_effective=_FEATURE_IDS, base=custom_base
    )

    assert isinstance(result, LGBMHyperparams)
    assert result.max_depth == 2


def test_lookup_usa_stage_e_partition_corretos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plumbing real: `stage`/`symbol`/`resolution` chegam em `artifact_
    exists` exatamente como `hyperparams_optuna.OPTUNA_HYPERPARAMS_STAGE`
    declara -- não um literal duplicado que pudesse divergir."""
    from src.models import hyperparams_optuna

    captured: dict[str, Any] = {}

    def _fake_exists(**kwargs: Any) -> bool:
        captured.update(kwargs)
        return False

    monkeypatch.setattr(io_artifact, "artifact_exists", _fake_exists)

    mod.load_hyperparams_by_combo(
        "BTCUSDT", "R1", "camada1", feature_ids_effective=_FEATURE_IDS
    )

    assert captured["stage"] == hyperparams_optuna.OPTUNA_HYPERPARAMS_STAGE
    assert captured["symbol"] == "BTCUSDT"
    assert captured["resolution"] == "R1"
    assert isinstance(captured["config_hash"], str)
