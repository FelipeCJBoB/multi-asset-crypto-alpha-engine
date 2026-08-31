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
import json

import structlog

from src.io import artifact as io_artifact

from . import hyperparams_optuna
from ._constants import load_constant
from ._paths import ARTIFACT_ROOT, EXPERIMENTS_DIR
from .alpha import LGBMHyperparams

logger = structlog.get_logger(__name__)

_HYPER_FIELD_NAMES: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(LGBMHyperparams))


def load_production_override(
    symbol: str, resolution_id: str, variant: str, *, base: LGBMHyperparams | None = None
) -> LGBMHyperparams | None:
    """Override MANUAL, fora do mecanismo automático content-addressed —
    decisão explícita do Manager registrada em
    `alpha_production_hyperparam_override` (`constants.yaml`, proveniência
    completa lá). Checado pelo CALLER (`pipeline.run_layer1_sprint_all_
    combinations`) ANTES de `load_hyperparams_by_combo`: um combo aqui
    presente vence a descoberta automática; um combo ausente devolve
    `None` e cai pro próximo nível do mesmo fallback chain (mecanismo
    automático, depois `LGBMHyperparams.from_constants()`) — mesmo
    contrato de "ausente" que `load_hyperparams_by_combo` já usa, não um
    novo tipo de falha silenciosa.

    Lê o vencedor CONFIRMADO (não o de screening) direto do JSON real de
    `hyperparams_optuna.py --confirm` (`AG-383`-addendum, gate duplo) —
    nunca recalcula, nunca gera novo dado, só aponta pro `run_stamp` já
    registrado na constante. `variant` (`alpha.VARIANT_CAMADA1`/
    `VARIANT_CAMADA0`, valores `"camada1"`/`"camada0"`) bate 1:1 com a
    chave de topo do JSON — sem tradução necessária."""
    overrides: dict[str, str] = load_constant("alpha_production_hyperparam_override")
    run_stamp = overrides.get(f"{symbol}_{resolution_id}")
    if run_stamp is None:
        return None
    path = (
        EXPERIMENTS_DIR
        / f"alpha_optuna_confirmation_{symbol}_{resolution_id}_{run_stamp}.json"
    )
    if not path.exists():
        raise FileNotFoundError(
            f"load_production_override: {path} não existe -- "
            "alpha_production_hyperparam_override (constants.yaml) aponta "
            "pra um run_stamp que não tem JSON de confirmação real gravado"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    overrides_hyper = data[variant]["winner"]["hyper"]
    base_hyper = base if base is not None else LGBMHyperparams.from_constants()
    logger.info(
        "models.hyperparams_by_combo.production_override_aplicado",
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        run_stamp=run_stamp,
    )
    return dataclasses.replace(base_hyper, **overrides_hyper)


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
