"""Loader de hiperparâmetro LightGBM por `(symbol, resolution_id, variant)`
— fonte trocada de `config/alpha_hyperparams_by_combo.yaml` (YAML estático,
aposentado) para o artefato Optuna content-addressed produzido por
`src.models.hyperparams_optuna` (decisão do Manager, 2026-08-29).

**Por que o YAML foi aposentado, não só recalibrado de novo.** O arquivo
estático calibrado em 25/08 (`ADR-003`) já ficou stale uma vez de verdade
(`AG-371`): `T1_FEATURE_IDS` mudou de conteúdo (7→22→29→36) sem ninguém
recalibrar, e só uma trava de hash checada em runtime
(`HyperparamFeatureMismatchError`) impediu o hiperparâmetro errado de
entrar num retreino canônico. Sob o artefato content-addressed, essa
classe de bug deixa de ser um ESTADO alcançável em runtime: um vetor de
features (ou espaço de busca) diferente produz um `config_hash` diferente
— ou seja, literalmente outro artefato. `entry ausente` (hash não bate)
mapeia 1:1 pro mesmo fallback de sempre ("sem calibração pra essa
combinação, cai pro hiperparâmetro global"), sem precisar de exceção nem
flag de escape.

Cache simples em memória — `constants.yaml` (que `compute_search_config_
hash` lê) não muda durante a vida do processo, mesmo padrão do resto do
pacote."""

from __future__ import annotations

import dataclasses

import structlog

from src.io import artifact as io_artifact

from . import hyperparams_optuna
from ._constants import load_constant
from ._paths import ARTIFACT_ROOT
from .alpha import LGBMHyperparams

logger = structlog.get_logger(__name__)

_HYPER_FIELD_NAMES: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(LGBMHyperparams))


def load_hyperparams_by_combo(
    symbol: str,
    resolution_id: str,
    variant: str,
    *,
    feature_ids_effective: tuple[str, ...],
    base: LGBMHyperparams | None = None,
) -> LGBMHyperparams | None:
    """Retorna `None` se esta combinação `(symbol, resolution_id, variant)`
    nunca teve uma campanha Optuna real gravar um artefato sob o hash de
    configuração ATIVO (feature vector + espaço de busca + n_trials +
    sampler + seed, ver `hyperparams_optuna.compute_search_config_hash`) —
    o chamador decide o fallback (`LGBMHyperparams.from_constants()`), não
    decidido silenciosamente aqui. Isso cobre TANTO "nunca rodou campanha
    pra esta combinação" QUANTO "rodou, mas sob um vetor de features (ou
    espaço de busca) diferente do atual" — as duas situações são
    indistinguíveis de propósito (o hash simplesmente não bate), mesma
    disciplina fail-closed que a versão anterior deste loader tinha, só
    que garantida pela imutabilidade content-addressed do artefato em vez
    de uma exceção checada em runtime.

    `base` (default `None` → `LGBMHyperparams.from_constants()`) fornece
    valor de partida antes de aplicar os campos do artefato — na prática
    quase vestigial hoje (`write_search_artifact` grava os 16 campos
    completos de `LGBMHyperparams`, não só os buscados), mantido por
    compatibilidade de assinatura/testabilidade."""
    n_trials = int(load_constant("alpha_optuna_n_trials"))
    sampler_name = str(load_constant("alpha_optuna_sampler"))
    sampler_seed = int(load_constant("alpha_random_seed"))
    config_hash = hyperparams_optuna.compute_search_config_hash(
        feature_ids_effective,
        variant=variant,
        n_trials=n_trials,
        sampler_name=sampler_name,
        sampler_seed=sampler_seed,
    )
    exists = io_artifact.artifact_exists(
        root=ARTIFACT_ROOT,
        stage=hyperparams_optuna.OPTUNA_HYPERPARAMS_STAGE,
        config_hash=config_hash,
        symbol=symbol,
        resolution=resolution_id,
    )
    if not exists:
        return None
    df, _manifest = io_artifact.read_artifact(
        root=ARTIFACT_ROOT,
        stage=hyperparams_optuna.OPTUNA_HYPERPARAMS_STAGE,
        config_hash=config_hash,
        symbol=symbol,
        resolution=resolution_id,
    )
    row = df.row(0, named=True)
    overrides = {name: row[name] for name in _HYPER_FIELD_NAMES if name in row}
    base_hyper = base if base is not None else LGBMHyperparams.from_constants()
    return dataclasses.replace(base_hyper, **overrides)
