"""Busca real de hiperparâmetro LightGBM do Alpha via Optuna — produção,
escopo `src/models/` (decisão do Manager, 2026-08-29: `src/validation/` é
outra frente, medição, não tocada/importada aqui).

`optuna>=4.0` é dependência declarada em `pyproject.toml` desde sempre, mas
nunca foi importada em nenhum lugar do `src/` até este módulo — toda busca
de hiperparâmetro até aqui (ADR-002/ADR-003) foi grade manual + coordinate
descent, cujo resultado virou `config/alpha_hyperparams_by_combo.yaml`
(aposentado por este módulo — ver `hyperparams_by_combo.py`). Esse YAML já
quebrou de verdade uma vez (`AG-371`): ficou stale quando `T1_FEATURE_IDS`
mudou de conteúdo (7→22→29→36) sem recalibração. Este módulo fecha essa
classe de bug por CONSTRUÇÃO — o resultado vencedor é gravado como
artefato content-addressed (`src.io.artifact`, mesmo mecanismo que
predictions/labels já usam), então um vetor de features (ou espaço de
busca) diferente é literalmente outro artefato; nunca dá pra ler um stale
por engano, sem exceção/flag de escape checada em runtime.

**Camada1 e Camada0 recebem studies independentes** (`variant` é parâmetro
obrigatório de `run_search_for_combo`, nunca um herdando do outro). A
comparação Camada1-vs-Camada0 é estruturalmente um teste de ablação
(feature set completo vs. baseline restrito), e hiperparâmetro precisa ser
reotimizado nos dois lados pra isolar o efeito que está sendo medido —
ver Probst et al., *Tunability*, JMLR 20(53) — não é reprise de um achado
antigo deste projeto (o Manager pediu explicitamente para não ancorar
nisso), é a mesma exigência de qualquer comparação de ablação válida.

**Espaço de busca — introspecção dinâmica, não lista Python paralela.**
Um campo de `LGBMHyperparams` entra na busca sse a constante
`alpha_lgbm_{campo}` correspondente declara `class: B` + `sweep_range` em
`constants.yaml` — mesma disciplina que fechou o `AG-371` (duas fontes de
verdade sobre "o que varia" é exatamente a classe de bug já vista aqui).

**Padrão de retrain vs. campanha de HPO** segue a prática de
champion-challenger de MLOps de produção: a campanha Optuna (cara, ~8h
pior caso, disparada manualmente via CLI deste módulo) é um evento
OCASIONAL que produz/atualiza o artefato; o retreino de rotina
(`pipeline.run_layer1_sprint_all_combinations`) continua barato e não
dispara busca nova — só lê o artefato mais recente pelo hash da
configuração ativa (`hyperparams_by_combo.load_hyperparams_by_combo`)."""

from __future__ import annotations

import dataclasses
import functools
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import optuna
import polars as pl
import structlog

from src.data import download
from src.features import build as features_build
from src.io import artifact as io_artifact
from src.io.schema import ArtifactSchema, ColumnSpec
from src.validation import cpcv
from src.validation import dsr as dsr_mod

from . import alpha, backtest_lite, monotonic
from . import dataset as ds
from ._constants import load_constant, load_constant_entry
from ._paths import ARTIFACT_ROOT, OPTUNA_STUDIES_DIR

logger = structlog.get_logger(__name__)

OPTUNA_HYPERPARAMS_STAGE = "alpha_hyperparams_optuna"

# Duplicado deliberadamente de `pipeline.ALL_SYMBOLS`/`ALL_RESOLUTIONS`
# (mesma fonte real — `ds.SYMBOL_DEFAULT`/`download.DEFAULT_SYMBOLS` — não
# um literal hardcoded que possa divergir) em vez de importado de lá:
# `pipeline.py` já importa `hyperparams_by_combo`, que importa este módulo
# — importar `pipeline` daqui fecharia um ciclo. Mesma tática já usada
# entre os `_paths.py` de cada pacote (ver docstring de `_paths.py`).
ALL_SYMBOLS: tuple[str, ...] = (ds.SYMBOL_DEFAULT, *download.DEFAULT_SYMBOLS)
ALL_RESOLUTIONS: tuple[str, ...] = ("R1", "R2", "R3")
ALL_VARIANTS: tuple[str, ...] = (alpha.VARIANT_CAMADA1, alpha.VARIANT_CAMADA0)

_SEARCH_SPACE_VERSION = "v1"

# Campo elegível <=> `alpha_lgbm_{campo}` existe em constants.yaml com
# `class: B` + `sweep_range` (checado em `build_search_space`) — este dict
# só declara o TIPO de cada campo numérico de `LGBMHyperparams` (pra saber
# `suggest_int` vs `suggest_float`), nunca se ele de fato entra na busca.
# Campos de `LGBMHyperparams` de propósito ausentes daqui (nunca elegíveis,
# mesmo que alguém adicione `sweep_range` à constante por engano):
# `regularization_basis`/`early_stopping_mode` (seletor de modo de código,
# já promovido a default de produção por decisão do Manager 2026-08-27 —
# buscar sobre eles reabriria uma decisão travada por porta lateral) e
# `ic_magnitude_floor_k` (idem, e é `float | None`, não numérico puro).
_FIELD_KIND: dict[str, str] = {
    "n_estimators": "int",
    "learning_rate": "float",
    "subsample": "float",
    "subsample_freq": "int",
    "feature_fraction": "float",
    "lambda_l2": "float",
    "min_child_samples": "int",
    "num_leaves": "int",
    "min_sum_hessian_in_leaf": "float",
    "max_bin": "int",
    "ess_regularization_n_obs_independentes_alvo": "float",
    "ess_regularization_fator_conservador": "float",
}

# Ordem 1:1 com os campos de `LGBMHyperparams` (`alpha.py:191-243`) --
# usado pra montar o schema do artefato E a linha gravada por
# `write_search_artifact` a partir de `dataclasses.asdict(best_hyper)`.
_HYPER_COLUMN_SPECS: tuple[ColumnSpec, ...] = (
    ColumnSpec(name="max_depth", dtype="Int64", nullable=False),
    ColumnSpec(name="n_estimators", dtype="Int64", nullable=False),
    ColumnSpec(name="learning_rate", dtype="Float64", nullable=False),
    ColumnSpec(name="subsample", dtype="Float64", nullable=False),
    ColumnSpec(name="subsample_freq", dtype="Int64", nullable=False),
    ColumnSpec(name="feature_fraction", dtype="Float64", nullable=False),
    ColumnSpec(name="lambda_l2", dtype="Float64", nullable=False),
    ColumnSpec(name="min_child_samples", dtype="Int64", nullable=False),
    ColumnSpec(name="num_leaves", dtype="Int64", nullable=False),
    ColumnSpec(name="min_sum_hessian_in_leaf", dtype="Float64", nullable=False),
    ColumnSpec(name="max_bin", dtype="Int64", nullable=False),
    ColumnSpec(
        name="ess_regularization_n_obs_independentes_alvo", dtype="Float64", nullable=False
    ),
    ColumnSpec(name="ess_regularization_fator_conservador", dtype="Float64", nullable=False),
    ColumnSpec(name="regularization_basis", dtype="Utf8", nullable=False),
    ColumnSpec(name="early_stopping_mode", dtype="Utf8", nullable=False),
    ColumnSpec(name="ic_magnitude_floor_k", dtype="Float64", nullable=True),
)

ALPHA_HYPERPARAMS_OPTUNA_SCHEMA = ArtifactSchema(
    schema_version="1.0.0",
    primary_key=("variant",),
    columns=(
        ColumnSpec(name="symbol", dtype="Utf8", nullable=False, role="partition"),
        ColumnSpec(name="resolution_id", dtype="Utf8", nullable=False, role="partition"),
        ColumnSpec(name="variant", dtype="Utf8", nullable=False, role="key"),
        ColumnSpec(name="device_type", dtype="Utf8", nullable=False),
        ColumnSpec(name="best_value", dtype="Float64", nullable=False),
        ColumnSpec(name="n_trials_run", dtype="Int64", nullable=False),
        ColumnSpec(name="sampler_name", dtype="Utf8", nullable=False),
        ColumnSpec(name="sampler_seed", dtype="Int64", nullable=False),
        ColumnSpec(name="study_name", dtype="Utf8", nullable=False),
        ColumnSpec(name="dsr", dtype="Float64", nullable=True),
        ColumnSpec(name="dsr_n_trials", dtype="Int64", nullable=True),
        *_HYPER_COLUMN_SPECS,
    ),
)

# Tipado pelo sampler concreto (não `BaseSampler`) de propósito -- só
# "tpe" é suportado hoje (ValueError explícito em `run_search_for_combo`
# pra qualquer outro nome), e `BaseSampler.__init__` não declara `seed`
# (é específico de cada sampler concreto); tipar largo aqui esconderia
# esse mismatch do mypy em vez de sinalizá-lo se um sampler sem `seed`
# for adicionado no futuro sem ajustar a chamada em `run_search_for_combo`.
_SAMPLER_BY_NAME: dict[str, type[optuna.samplers.TPESampler]] = {
    "tpe": optuna.samplers.TPESampler,
}

# Regra explícita, não hardcode por nome de campo: um `sweep_range` cujo
# `high/low` passa desta razão vira busca em escala log (`min_sum_hessian_
# in_leaf [0.001, 5.0]`, razão ~3700x, é o caso que motivou a regra — mas
# ela se aplica a QUALQUER campo, incluindo os 4 novos abertos nesta rodada,
# sem lista de exceção mantida à mão).
_LOG_SCALE_RATIO_THRESHOLD = 10.0  # noqa: magic-number -- engenharia (heurística de forma do espaço de busca), não parâmetro de domínio quant

# Fator de conversão fração -> pontos-base -- definição matemática, mesma
# categoria/valor de `src.labels.triple_barrier._BPS_PER_UNIT` (não
# importado de lá -- é `_`-privado daquele módulo, e o fator em si é
# aritmética pura, não estado compartilhado). `PathBacktestResult.
# mean_trade_ret` vem de `ret_net`, que É FRAÇÃO (`ret_gross = side *
# (exit_price/fill_px - 1.0)`, sem nenhum `* 10_000` em `triple_barrier.py`
# -- só `cost_entry_bps`/`cost_exit_bps`/`funding_bps` são convertidos pra
# bps explicitamente lá). Sem esta conversão, `alpha_layer1_permanence_
# min_edge_bps`/`median_pooled_edge_bps` estariam nomeados "bps" mas
# carregando fração (achado real, corrigido nesta sessão -- valores follow-
# up direto da campanha real: -0,000516 de fração vira -5,16 bps, não
# -0,000516 bps).
_BPS_PER_UNIT: Final[int] = 10_000


@dataclass(frozen=True, slots=True)
class _SearchDim:
    kind: str  # "int" | "float"
    low: float
    high: float
    log: bool


def build_search_space() -> dict[str, _SearchDim]:
    """Introspecção dinâmica: um campo de `LGBMHyperparams` entra sse a
    constante `alpha_lgbm_{campo}` existe, `class == "B"`, e `sweep_range`
    está declarado. Não depende de `feature_ids`/dataset algum — função
    pura sobre `constants.yaml`, testável sem Optuna."""
    space: dict[str, _SearchDim] = {}
    for field_name, kind in _FIELD_KIND.items():
        try:
            entry = load_constant_entry(f"alpha_lgbm_{field_name}")
        except KeyError:
            continue
        if entry.get("class") != "B":
            continue
        sweep_range = entry.get("sweep_range")
        if sweep_range is None:
            continue
        low, high = float(sweep_range[0]), float(sweep_range[1])
        ratio = high / low if low > 0.0 else 0.0  # noqa: unguarded-ratio -- guardado pelo `if low>0.0`
        log = low > 0.0 and ratio > _LOG_SCALE_RATIO_THRESHOLD
        space[field_name] = _SearchDim(kind=kind, low=low, high=high, log=log)
    return space


def _search_config_payload(
    feature_ids_effective: tuple[str, ...],
    *,
    variant: str,
    n_trials: int,
    sampler_name: str,
    sampler_seed: int,
) -> dict[str, Any]:
    """Payload hasheado por `compute_search_config_hash`/`write_search_
    artifact` — a MESMA função dos dois lados (escrita e leitura) garante
    que o hash nunca diverge por um dict montado de dois jeitos diferentes.
    `search_space` entra por VALOR (não só `_SEARCH_SPACE_VERSION`): se
    `constants.yaml::alpha_lgbm_*.sweep_range` mudar sem ninguém lembrar de
    bumpar a versão, o hash muda sozinho -- mesmo mecanismo que já fecha
    staleness de `feature_ids` (`compute_feature_ids_hash`, YAML aposentado
    por este módulo)."""
    space = build_search_space()
    return {
        "feature_ids": sorted(feature_ids_effective),
        "search_space_version": _SEARCH_SPACE_VERSION,
        "search_space": {
            name: [dim.kind, dim.low, dim.high, dim.log] for name, dim in sorted(space.items())
        },
        "variant": variant,
        "n_trials": n_trials,
        "sampler_name": sampler_name,
        "sampler_seed": sampler_seed,
    }


def compute_search_config_hash(
    feature_ids_effective: tuple[str, ...],
    *,
    variant: str,
    n_trials: int,
    sampler_name: str,
    sampler_seed: int,
) -> str:
    """`device_type`/`(symbol, resolution_id)` ficam FORA do hash --
    partição de path (symbol/resolution_id) ou coluna de payload
    (device_type, ver `write_search_artifact`), não identidade da busca: o
    vencedor numérico é portável entre devices, só o PROCESSO de busca em
    si carrega a ressalva de determinismo de `AG-196` (device_type != "cpu"
    já loga warning dentro de `alpha.fit_side_model`)."""
    payload = _search_config_payload(
        feature_ids_effective,
        variant=variant,
        n_trials=n_trials,
        sampler_name=sampler_name,
        sampler_seed=sampler_seed,
    )
    return io_artifact.compute_config_hash(
        payload, schema_version=ALPHA_HYPERPARAMS_OPTUNA_SCHEMA.schema_version
    )


def build_search_frame(
    symbol: str,
    resolution_id: str,
    *,
    vol_estimator_id: str | None = None,
    feature_ids: tuple[str, ...] | None = None,
) -> tuple[ds.ModelingFrame, tuple[cpcv.CPCVSplit, ...], tuple[str, ...]]:
    """Replica `pipeline.run_layer1_sprint` (linhas ~895-971: resolve
    `feature_ids_effective`, valida `defeito_construcao`, resolve
    `vol_estimator_id_effective`, monta `mf`/`splits`) -- NÃO importada de
    `src/validation/` (escopo desta rodada é só `src/models/`, decisão do
    Manager). Chamada 1x por combinação por `run_search_for_combo`, reusada
    entre todos os trials da mesma campanha (mesmo padrão de custo já
    medido em `AG-371-ADDENDUM-17`: setup ~28s pago 1x, treino 10-33s por
    trial, repetido)."""
    extra_feature_ids = (
        tuple(f for f in feature_ids if f not in features_build.T1_FEATURE_IDS)
        if feature_ids is not None
        else ()
    )
    feature_ids_effective = features_build.resolve_feature_ids(feature_ids)
    features_build.assert_no_defeito_construcao_in_active_set(feature_ids_effective)
    vol_estimator_id_effective = (
        vol_estimator_id
        if vol_estimator_id is not None
        else str(load_constant("canonical_volatility_estimator"))
    )
    mf = ds.build_modeling_frame(
        symbol=symbol,
        tf="15m",
        resolution_id=resolution_id,
        vol_estimator_id=vol_estimator_id_effective,
        t0_start=None,
        t0_end=None,
        extra_feature_ids=extra_feature_ids,
    )
    max_feature_lookback_ms = features_build.compute_max_feature_lookback_ms(
        "15m", feature_ids_effective, resolution_id=resolution_id
    )
    cpcv_config = cpcv.CPCVConfig.from_constants(
        tf="15m", grade_id=resolution_id, max_feature_lookback_ms=max_feature_lookback_ms
    )
    cpcv_result = cpcv.generate_splits(mf.data, config=cpcv_config, symbol=symbol)
    return mf, cpcv_result.splits, feature_ids_effective


def _suggest_value(trial: optuna.Trial, field_name: str, dim: _SearchDim) -> int | float:
    if dim.kind == "int":
        return trial.suggest_int(field_name, round(dim.low), round(dim.high), log=dim.log)
    return trial.suggest_float(field_name, dim.low, dim.high, log=dim.log)


def _precompute_monotone_screens(
    mf: ds.ModelingFrame,
    splits: tuple[cpcv.CPCVSplit, ...],
    feature_ids_effective: tuple[str, ...],
    base_hyper: alpha.LGBMHyperparams,
) -> dict[tuple[int, int], dict[str, monotonic.FeatureICResult]]:
    """AG-380 (2026-08-29, `cProfile` real) -- `alpha.compute_monotone_
    screen` NÃO depende de nenhum campo buscado pelo Optuna
    (`ic_magnitude_floor_k` fica sempre em `base_hyper`, nunca em
    `_SEARCH_SPACE`/`_FIELD_KIND`; `unforce_features_by_side` é sempre
    `None` em produção) -- então o resultado é IDÊNTICO em todo trial de
    uma mesma campanha. Medido: ~0,56s/chamada, ~39% do custo de UM
    trial completo (`run_all_folds`, 15 splits × 2 lados = 30 chamadas).
    Pré-computa 1x aqui (fora do loop de trials) em vez de deixar cada
    trial recalcular -- reduz o custo por trial em ~39%, em QUALQUER
    `device_type` (não é uma otimização de GPU, é eliminar trabalho
    redundante puro). Replica a mesma sequência `side_subset` que
    `alpha.run_fold` já faz internamente (train_bars -> side_subset por
    lado) -- duplicação deliberada de 2 linhas, não vale importar/expor
    um helper novo de `alpha.py` só pra isso."""
    cache: dict[tuple[int, int], dict[str, monotonic.FeatureICResult]] = {}
    for split in splits:
        train_bars = mf.data[split.train_idx]
        for side in (1, -1):
            train_side_df = ds.side_subset(
                train_bars, side=side, feature_ids=feature_ids_effective, enforce_r2=True
            )
            cache[(split.split_id, side)] = alpha.compute_monotone_screen(
                train_side_df,
                feature_ids_effective,
                side=side,
                ic_magnitude_floor_k=base_hyper.ic_magnitude_floor_k,
            )
    return cache


def _objective(
    trial: optuna.Trial,
    *,
    mf: ds.ModelingFrame,
    splits: tuple[cpcv.CPCVSplit, ...],
    symbol: str,
    resolution_id: str,
    variant: str,
    feature_ids_effective: tuple[str, ...],
    base_hyper: alpha.LGBMHyperparams,
    seed: int,
    device_type: str,
    search_space: dict[str, _SearchDim],
    monotone_screen_cache: dict[tuple[int, int], dict[str, monotonic.FeatureICResult]],
) -> float:
    """`seed` FIXO por study inteiro (nunca `trial.suggest_int` sobre
    seed) -- ruído de seed já medido neste projeto
    (`audit/n_lifetime.yaml` id=20: `pooled_sharpe std~=0,31` variando só
    seed com hiperparâmetro fixo); sortear seed por trial contaminaria a
    superfície de resposta que o sampler TPE aprende. `tau_policy`/
    `calib_split_mode`/`class_balance_basis`/`calib_weight_basis`/
    `enforce_r2` passados EXPLÍCITOS -- nunca herdados dos bare defaults de
    `alpha.run_all_folds`, que são o regime LEGADO pré-`AG-272`, não o de
    produção (herdar silenciosamente otimizaria hiperparâmetro pro
    problema errado).

    `monotone_screen_cache` (AG-380) -- `_precompute_monotone_screens`,
    calculado 1x por `run_search_for_combo` antes do loop de trials,
    reusado aqui em TODO trial (a triagem de monotonicidade não muda com
    o hiperparâmetro buscado)."""
    # `dict[str, Any]`, não `dict[str, int | float]` -- mypy não consegue
    # verificar `**kwargs` heterogêneo contra os tipos por campo de
    # `dataclasses.replace` de qualquer forma (mesmo idioma já usado em
    # `hyperparams_by_combo.py::load_hyperparams_by_combo`'s `overrides`).
    suggested: dict[str, Any] = {
        name: _suggest_value(trial, name, dim) for name, dim in search_space.items()
    }
    hyper = dataclasses.replace(base_hyper, **suggested)
    folds = alpha.run_all_folds(
        mf.data,
        splits,
        variant=variant,
        model_id="hyperparam_optuna_trial",
        symbol=symbol,
        resolution_id=resolution_id,
        hyper=hyper,
        seed=seed,
        feature_ids=feature_ids_effective,
        device_type=device_type,
        tau_policy=alpha.TAU_POLICY_LEGACY_PER_SIDE,
        calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
        class_balance_basis=alpha.CLASS_BALANCE_WEIGHT,
        calib_weight_basis=alpha.CALIB_WEIGHT_UNIQUENESS,
        enforce_r2=True,
        monotone_screen_override_by_split_side=monotone_screen_cache,
    )
    by_path = backtest_lite.backtest_by_path(folds, mf.data)
    sharpes = [r.sharpe_naive for r in by_path.values() if math.isfinite(r.sharpe_naive)]
    pooled = (
        sum(sharpes) / len(sharpes)  # noqa: unguarded-ratio -- guardado pelo `if sharpes` abaixo
        if sharpes
        else float("nan")
    )
    trial.set_user_attr("sharpe_by_path", {str(pid): r.sharpe_naive for pid, r in by_path.items()})
    trial.set_user_attr("n_signals_total", sum(r.n_signals for r in by_path.values()))
    # `pooled` pode ser NaN (todos os paths sem trade preenchido) -- Optuna
    # já marca o trial como FAIL automaticamente quando o objective devolve
    # NaN (comportamento nativo da lib desde 2.x), não reinventado aqui.
    return pooled


def _compute_dsr_post_hoc(
    *,
    mf: ds.ModelingFrame,
    splits: tuple[cpcv.CPCVSplit, ...],
    symbol: str,
    resolution_id: str,
    variant: str,
    feature_ids_effective: tuple[str, ...],
    best_hyper: alpha.LGBMHyperparams,
    seed: int,
    device_type: str,
    dsr_n_trials: int,
) -> float | None:
    """Leitura PÓS-HOC do vencedor, nunca objective ao vivo -- otimizar por
    DSR ao vivo seria circular (a paisagem de `n_trials` muda a cada trial
    desta própria campanha). Retreina 1x sob `best_hyper` (custo aceito,
    ~10-33s) porque `study.best_trial` só guarda o valor escalar do
    objective, não os retornos por trade que `compute_dsr` exige."""
    folds = alpha.run_all_folds(
        mf.data,
        splits,
        variant=variant,
        model_id="hyperparam_optuna_best_dsr",
        symbol=symbol,
        resolution_id=resolution_id,
        hyper=best_hyper,
        seed=seed,
        feature_ids=feature_ids_effective,
        device_type=device_type,
        tau_policy=alpha.TAU_POLICY_LEGACY_PER_SIDE,
        calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
        class_balance_basis=alpha.CLASS_BALANCE_WEIGHT,
        calib_weight_basis=alpha.CALIB_WEIGHT_UNIQUENESS,
        enforce_r2=True,
    )
    realized = backtest_lite.realize_trades(folds, mf.data)
    filled = realized.filter(pl.col("barrier_hit") != "NOFILL")
    rets = filled["ret_net"].to_numpy().astype(np.float64)
    span = backtest_lite.span_seconds(filled["t0"])
    _, trades_per_year = backtest_lite.sharpe_naive(rets, span_seconds=span)
    try:
        dsr_result = dsr_mod.compute_dsr(
            rets, n_trials=dsr_n_trials, trades_per_year=trades_per_year
        )
    except ValueError as exc:
        logger.warning(
            "models.hyperparams_optuna.dsr_pos_hoc_falhou",
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            error=str(exc),
        )
        return None
    return float(dsr_result.dsr)


@dataclass(frozen=True, slots=True)
class OptunaSearchResult:
    symbol: str
    resolution_id: str
    variant: str
    best_hyper: alpha.LGBMHyperparams
    best_value: float
    n_trials_run: int
    sampler_name: str
    sampler_seed: int
    device_type: str
    study_name: str
    dsr: float | None
    dsr_n_trials: int | None


def write_search_artifact(
    result: OptunaSearchResult,
    *,
    feature_ids_effective: tuple[str, ...],
    root: Path = ARTIFACT_ROOT,
    scratch: bool = False,
) -> io_artifact.ArtifactManifest:
    """Grava via `io_artifact.write_artifact` -- content-addressed,
    imutável (V-05), `scratch=True` pra iteração exploratória. Payload tem
    os 16 campos COMPLETOS de `best_hyper` (não só os buscados) -- torna o
    artefato autocontido: se o hiperparâmetro global de `constants.yaml`
    mudar depois, um artefato antigo não herda silenciosamente um valor
    novo."""
    config = _search_config_payload(
        feature_ids_effective,
        variant=result.variant,
        n_trials=result.n_trials_run,
        sampler_name=result.sampler_name,
        sampler_seed=result.sampler_seed,
    )
    row: dict[str, Any] = {
        "symbol": result.symbol,
        "resolution_id": result.resolution_id,
        "variant": result.variant,
        "device_type": result.device_type,
        "best_value": result.best_value,
        "n_trials_run": result.n_trials_run,
        "sampler_name": result.sampler_name,
        "sampler_seed": result.sampler_seed,
        "study_name": result.study_name,
        "dsr": result.dsr,
        "dsr_n_trials": result.dsr_n_trials,
        **dataclasses.asdict(result.best_hyper),
    }
    # `schema=` explícito (não inferido) -- colunas nullable com valor
    # `None` único (`dsr`/`dsr_n_trials`, quando a campanha não pediu DSR
    # pós-hoc) fariam Polars inferir `Null`, não `Float64`/`Int64`, e
    # `validate_schema` recusaria (achado real, suíte de testes desta
    # rodada). `ALPHA_HYPERPARAMS_OPTUNA_SCHEMA.polars_schema()` é a MESMA
    # fonte que `validate_schema` usa para comparar -- nunca diverge.
    df = pl.DataFrame([row], schema=ALPHA_HYPERPARAMS_OPTUNA_SCHEMA.polars_schema())
    return io_artifact.write_artifact(
        df,
        root=root,
        stage=OPTUNA_HYPERPARAMS_STAGE,
        symbol=result.symbol,
        resolution=result.resolution_id,
        config=config,
        schema=ALPHA_HYPERPARAMS_OPTUNA_SCHEMA,
        producer_entrypoint="src.models.hyperparams_optuna.run_search_for_combo",
        scratch=scratch,
    )


def run_search_for_combo(
    *,
    symbol: str,
    resolution_id: str,
    variant: str,
    vol_estimator_id: str | None = None,
    feature_ids: tuple[str, ...] | None = None,
    device_type: str = "cpu",
    n_trials: int | None = None,
    sampler_seed: int | None = None,
    dsr_n_trials: int | None = None,
    storage_dir: Path | None = None,
    scratch: bool = False,
) -> OptunaSearchResult:
    """Executa (ou retoma) 1 study Optuna real e persiste o vencedor.
    `n_trials`/`sampler_seed` sentinela `None` resolve de `constants.yaml`
    (`alpha_optuna_n_trials`/`alpha_random_seed`) -- mesmo padrão sentinela
    já usado em `pipeline.run_layer1_sprint`. `storage_dir` sentinela
    `None` resolve pra `OPTUNA_STUDIES_DIR` (sqlite local, um arquivo por
    `symbol_resolution_id_variant`, `load_if_exists=True` -- resumível após
    crash, custo pior-caso medido ~8h CPU serial pra campanha completa,
    `AG-371-ADDENDUM-17`). Trials rodam SEQUENCIAIS (`n_jobs=1`) de
    propósito: `alpha.fit_side_model` já usa `n_jobs=-1` dentro do
    LightGBM -- paralelizar trials por cima oversubscreveria CPU (ou
    disputaria a única GPU, depois do WSL2)."""
    if variant not in ALL_VARIANTS:
        raise ValueError(
            f"run_search_for_combo: variant={variant!r} desconhecido -- "
            f"esperado um de {ALL_VARIANTS}"
        )

    mf, splits, feature_ids_effective = build_search_frame(
        symbol, resolution_id, vol_estimator_id=vol_estimator_id, feature_ids=feature_ids
    )

    n_trials_resolved = (
        n_trials if n_trials is not None else int(load_constant("alpha_optuna_n_trials"))
    )
    seed = int(load_constant("alpha_random_seed"))
    sampler_seed_resolved = sampler_seed if sampler_seed is not None else seed
    sampler_name = str(load_constant("alpha_optuna_sampler"))
    sampler_cls = _SAMPLER_BY_NAME.get(sampler_name)
    if sampler_cls is None:
        raise ValueError(
            f"alpha_optuna_sampler={sampler_name!r} não suportado -- "
            f"esperado um de {sorted(_SAMPLER_BY_NAME)}"
        )
    storage_backend = str(load_constant("alpha_optuna_storage_backend"))
    if storage_backend != "sqlite":
        raise ValueError(
            f"alpha_optuna_storage_backend={storage_backend!r} não suportado -- "
            "só 'sqlite' implementado nesta rodada"
        )

    search_space = build_search_space()
    if not search_space:
        raise ValueError(
            "build_search_space() vazio -- nenhum alpha_lgbm_* com class='B' + "
            "sweep_range declarado em constants.yaml"
        )
    base_hyper = alpha.LGBMHyperparams.from_constants()

    config_hash = compute_search_config_hash(
        feature_ids_effective,
        variant=variant,
        n_trials=n_trials_resolved,
        sampler_name=sampler_name,
        sampler_seed=sampler_seed_resolved,
    )
    # `device_type` ENTRA aqui (study_name/sqlite), mesmo NÃO entrando no
    # config_hash do artefato final (ver compute_search_config_hash) --
    # achado real rodando o benchmark CPU-vs-GPU desta sessão: sem isso,
    # `load_if_exists=True` faz um study já completo sob CPU ser "resumido"
    # (0 trials novos) quando alguém roda de novo só trocando device_type,
    # devolvendo os MESMOS resultados sem treinar nada no device novo --
    # silencioso, sem erro. O artefato vencedor continua device-portável
    # (é só o NÚMERO final); o processo de EXPLORAÇÃO (quais trials já
    # rodaram) não é -- misturar trials CPU/GPU no mesmo study também
    # violaria a ressalva de determinismo do AG-196 (GPU não é bit-exato
    # ao CPU) dentro da própria história de otimização do sampler.
    study_name = (
        f"alpha_hyperparams_{symbol}_{resolution_id}_{variant}_{device_type}_{config_hash[:8]}"
    )

    storage_dir_resolved = storage_dir if storage_dir is not None else OPTUNA_STUDIES_DIR
    storage_dir_resolved.mkdir(parents=True, exist_ok=True)
    db_name = f"{symbol}_{resolution_id}_{variant}_{device_type}.db"
    db_path = storage_dir_resolved / db_name  # noqa: unguarded-ratio -- Path.__truediv__, não divisão

    study = optuna.create_study(
        direction="maximize",
        sampler=sampler_cls(seed=sampler_seed_resolved),
        storage=f"sqlite:///{db_path.resolve()}",
        study_name=study_name,
        load_if_exists=True,
    )
    n_already_run = len(study.trials)
    n_remaining = max(0, n_trials_resolved - n_already_run)
    logger.info(
        "models.hyperparams_optuna.study_start",
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        study_name=study_name,
        n_already_run=n_already_run,
        n_remaining=n_remaining,
        device_type=device_type,
    )
    if n_remaining > 0:
        # AG-380 (2026-08-29) -- calculado 1x aqui, fora do loop de
        # `n_remaining` trials -- `_precompute_monotone_screens` explica o
        # motivo (a triagem não muda com o hiperparâmetro buscado; medido
        # ~39% do custo de um trial completo via `cProfile`).
        monotone_screen_cache = _precompute_monotone_screens(
            mf, splits, feature_ids_effective, base_hyper
        )
        objective = functools.partial(
            _objective,
            mf=mf,
            splits=splits,
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            feature_ids_effective=feature_ids_effective,
            base_hyper=base_hyper,
            seed=seed,
            device_type=device_type,
            search_space=search_space,
            monotone_screen_cache=monotone_screen_cache,
        )
        # `catch=(alpha.CudaMaxBinUnsupportedError,)` -- achado real
        # (2026-08-29, bisecado neste projeto até o campo/valor exato):
        # `device_type="cuda"` + `max_bin > 256` mata o PROCESSO inteiro
        # via `std::terminate` (bug upstream aberto, LightGBM#6512) se
        # deixado chegar em `LGBMClassifier.fit()`. `alpha.fit_side_model`
        # já converte isso num `CudaMaxBinUnsupportedError` ANTES de
        # chamar `fit()` -- aqui, `catch=` diz ao Optuna pra tratar essa
        # exceção especifica como "trial falhou" (mesmo mecanismo que já
        # existe pra objective retornando NaN) e seguir pro próximo trial,
        # em vez de propagar e derrubar a campanha inteira por um valor de
        # `max_bin` que o sampler só ia aprender a evitar se sobrevivesse
        # pra ver o resultado.
        study.optimize(
            objective, n_trials=n_remaining, n_jobs=1, catch=(alpha.CudaMaxBinUnsupportedError,)
        )

    # Achado real (2026-08-29, ao validar o fix de `CudaMaxBinUnsupportedError`
    # acima): capturar a exceção corretamente TORNA alcançável um estado que
    # antes nunca acontecia (o processo crashava antes de qualquer trial
    # terminar) -- "todos os N trials falharam" (nan/`CudaMaxBinUnsupported
    # Error`/outro). Sem esta guarda, `study.best_trial` levanta `ValueError:
    # Record does not exist` (SQLAlchemy, de dentro do storage do Optuna) --
    # tecnicamente correto, mas opaco: não diz QUANTOS trials rodaram nem
    # POR QUE nenhum completou. FCN -- nunca deixar esse diagnóstico pra
    # quem lê o traceback decifrar sozinho.
    n_complete = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE)
    if n_complete == 0:
        n_fail = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.FAIL)
        raise ValueError(
            f"run_search_for_combo: 0 de {len(study.trials)} trials completaram "
            f"com sucesso para {symbol}/{resolution_id}/{variant} ({n_fail} "
            "falharam) -- nenhum hiperparâmetro válido pra reportar. Motivos "
            "de falha (nan / CudaMaxBinUnsupportedError / outro) estão no log "
            "de cada trial acima, não resumidos aqui -- study_name="
            f"{study_name!r} em {db_path}."
        )
    best_trial = study.best_trial
    best_hyper = dataclasses.replace(base_hyper, **best_trial.params)

    dsr_value: float | None = None
    if dsr_n_trials is not None:
        dsr_value = _compute_dsr_post_hoc(
            mf=mf,
            splits=splits,
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            feature_ids_effective=feature_ids_effective,
            best_hyper=best_hyper,
            seed=seed,
            device_type=device_type,
            dsr_n_trials=dsr_n_trials,
        )

    # `FrozenTrial.value` é `float | None` nos stubs do Optuna (cobre
    # trials PRUNED/FAILED) -- `study.best_trial` é sempre COMPLETE por
    # contrato da própria lib (só considera trials com valor real pra
    # decidir o "melhor"), então `None` aqui seria bug do Optuna, não
    # estado esperado -- assert explícito, não silenciado com `or 0.0`.
    assert best_trial.value is not None, "study.best_trial sem value -- contrato do Optuna violado"
    result = OptunaSearchResult(
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        best_hyper=best_hyper,
        best_value=float(best_trial.value),
        n_trials_run=len(study.trials),
        sampler_name=sampler_name,
        sampler_seed=sampler_seed_resolved,
        device_type=device_type,
        study_name=study_name,
        dsr=dsr_value,
        dsr_n_trials=dsr_n_trials,
    )
    write_search_artifact(result, feature_ids_effective=feature_ids_effective, scratch=scratch)
    logger.info(
        "models.hyperparams_optuna.study_done",
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        best_value=result.best_value,
        n_trials_run=result.n_trials_run,
        dsr=result.dsr,
    )
    return result


# ============================================================================
# Confirmação multi-seed (2026-08-30) -- mesma disciplina do ADR-002/ADR-003
# (screen 1 seed -> confirma top-K por MEDIANA de N seeds -> gate de
# permanência pareado), aplicada ao resultado da campanha Optuna real em vez
# de repetir a busca. `best_value` de `run_search_for_combo` é o MÁXIMO de
# `n_trials` sob 1 seed só -- winner's-curse medido real neste projeto
# (ADR-002: +0,772 de viés) exige confirmação antes de qualquer promoção.
# ============================================================================


def _load_existing_study(
    *,
    symbol: str,
    resolution_id: str,
    variant: str,
    feature_ids_effective: tuple[str, ...],
    device_type: str,
    n_trials: int,
    sampler_name: str,
    sampler_seed: int,
    storage_dir: Path,
) -> optuna.Study:
    """Reconstrói o MESMO `study_name`/`db_path` que `run_search_for_combo`
    já usou pra gravar -- nunca globa por padrão de nome (`compute_search_
    config_hash` é a única fonte de verdade do nome, mesma disciplina de
    `AG-371`: 2 formas de achar "o mesmo" study é a classe de bug que já
    mordeu este projeto)."""
    config_hash = compute_search_config_hash(
        feature_ids_effective,
        variant=variant,
        n_trials=n_trials,
        sampler_name=sampler_name,
        sampler_seed=sampler_seed,
    )
    study_name = (
        f"alpha_hyperparams_{symbol}_{resolution_id}_{variant}_{device_type}_{config_hash[:8]}"
    )
    db_path = storage_dir / f"{symbol}_{resolution_id}_{variant}_{device_type}.db"  # noqa: unguarded-ratio -- Path.__truediv__
    if not db_path.exists():
        raise FileNotFoundError(
            f"_load_existing_study: {db_path} não existe -- rode run_search_for_combo "
            f"pra {symbol}/{resolution_id}/{variant}/{device_type} antes de confirmar"
        )
    return optuna.load_study(study_name=study_name, storage=f"sqlite:///{db_path.resolve()}")


@dataclass(frozen=True, slots=True)
class ConfirmedCandidate:
    """1 combinação de hiperparâmetro FIXA (top-K do screening), testada sob
    N seeds novas. `selection_bias_estimate` = `screening_value` (1 seed,
    otimista) menos `median_pooled_sharpe` (N seeds) -- réplica direta da
    métrica que o ADR-002 mediu como +0,772 no pior caso.

    `seed_pooled_edge_bps`/`median_pooled_edge_bps` (AG-383-ADDENDUM, gate
    duplo pedido pelo Manager 2026-08-30) -- `PathBacktestResult.mean_trade_
    ret` é FRAÇÃO (`ret_net`/`ret_gross` de `triple_barrier.py` nunca
    passam por `* _BPS_PER_UNIT`, só `cost_entry_bps`/`cost_exit_bps`/
    `funding_bps` são convertidos lá), escalado aqui por `_BPS_PER_UNIT`
    (10_000) pra virar bps de verdade -- achado real corrigido nesta
    sessão. Pooled entre paths pela MESMA convenção do Sharpe (média
    simples entre paths, não ponderada por nº de trade). `seed_pooled_
    trade_count` é o denominador de cobertura (soma de
    `n_filled_trades` entre paths) -- existe só pra impedir que o gate de
    edge seja "vencido" por um hiperparâmetro que fica seletivo demais
    (poucos trades, média dominada por outlier de cauda); FILTRAR sinal é
    papel do Meta-model (`§15.19`, ainda não implementado), não do Alpha --
    este piso é só confiabilidade estatística da média, não um mecanismo de
    seleção novo."""

    hyper: alpha.LGBMHyperparams
    screening_value: float
    seed_pooled_sharpe: dict[int, float]
    seed_path_sharpe: dict[int, dict[int, float]]
    median_pooled_sharpe: float
    selection_bias_estimate: float
    seed_pooled_edge_bps: dict[int, float]
    seed_pooled_trade_count: dict[int, int]
    median_pooled_edge_bps: float
    median_trade_count: float


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    symbol: str
    resolution_id: str
    variant: str
    top_k: int
    confirmation_seeds: tuple[int, ...]
    candidates: tuple[ConfirmedCandidate, ...]
    winner: ConfirmedCandidate


def confirm_top_k_multi_seed(
    *,
    symbol: str,
    resolution_id: str,
    variant: str,
    top_k: int,
    confirmation_seeds: tuple[int, ...],
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
    feature_ids: tuple[str, ...] | None = None,
    n_trials: int | None = None,
    sampler_seed: int | None = None,
    storage_dir: Path | None = None,
) -> ConfirmationResult:
    """Estágio 2+3 do ADR-002/ADR-003, adaptado: pega os `top_k` trials
    COMPLETE já gravados por `run_search_for_combo` (leitura, zero treino
    novo) e re-treina CADA um sob `confirmation_seeds` (hiperparâmetro FIXO
    -- não é busca, é reavaliação de um ponto já escolhido). Vencedor
    decidido pela MEDIANA entre seeds, não pelo `best_value` de 1 seed que
    o screening reportou. `seed_path_sharpe` (Sharpe por caminho do CPCV,
    por seed) fica disponível pra `confirm_combo_paired` computar o gate de
    permanência SEM precisar de um "Estágio 3" com treino novo -- mesma
    rodada de confirmação serve pros dois propósitos."""
    mf, splits, feature_ids_effective = build_search_frame(
        symbol, resolution_id, vol_estimator_id=vol_estimator_id, feature_ids=feature_ids
    )
    n_trials_resolved = (
        n_trials if n_trials is not None else int(load_constant("alpha_optuna_n_trials"))
    )
    base_seed = int(load_constant("alpha_random_seed"))
    sampler_seed_resolved = sampler_seed if sampler_seed is not None else base_seed
    sampler_name = str(load_constant("alpha_optuna_sampler"))
    storage_dir_resolved = storage_dir if storage_dir is not None else OPTUNA_STUDIES_DIR
    base_hyper = alpha.LGBMHyperparams.from_constants()

    study = _load_existing_study(
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        feature_ids_effective=feature_ids_effective,
        device_type=device_type,
        n_trials=n_trials_resolved,
        sampler_name=sampler_name,
        sampler_seed=sampler_seed_resolved,
        storage_dir=storage_dir_resolved,
    )
    complete_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if not complete_trials:
        raise ValueError(
            f"confirm_top_k_multi_seed: study {study.study_name!r} não tem nenhum trial "
            "COMPLETE -- nada pra confirmar"
        )
    complete_trials.sort(key=lambda t: t.value, reverse=True)  # type: ignore[arg-type, return-value]
    top_trials = complete_trials[:top_k]

    monotone_screen_cache = _precompute_monotone_screens(
        mf, splits, feature_ids_effective, base_hyper
    )

    candidates: list[ConfirmedCandidate] = []
    for trial in top_trials:
        hyper = dataclasses.replace(base_hyper, **trial.params)
        seed_pooled: dict[int, float] = {}
        seed_paths: dict[int, dict[int, float]] = {}
        seed_pooled_edge: dict[int, float] = {}
        seed_trade_count: dict[int, int] = {}
        for seed in confirmation_seeds:
            folds = alpha.run_all_folds(
                mf.data,
                splits,
                variant=variant,
                model_id="hyperparam_optuna_confirm",
                symbol=symbol,
                resolution_id=resolution_id,
                hyper=hyper,
                seed=seed,
                feature_ids=feature_ids_effective,
                device_type=device_type,
                tau_policy=alpha.TAU_POLICY_LEGACY_PER_SIDE,
                calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
                class_balance_basis=alpha.CLASS_BALANCE_WEIGHT,
                calib_weight_basis=alpha.CALIB_WEIGHT_UNIQUENESS,
                enforce_r2=True,
                monotone_screen_override_by_split_side=monotone_screen_cache,
            )
            by_path = backtest_lite.backtest_by_path(folds, mf.data)
            sharpes = [r.sharpe_naive for r in by_path.values() if math.isfinite(r.sharpe_naive)]
            pooled = (
                sum(sharpes) / len(sharpes)  # noqa: unguarded-ratio -- guardado pelo `if sharpes`
                if sharpes
                else float("nan")
            )
            seed_pooled[seed] = pooled
            seed_paths[seed] = {pid: r.sharpe_naive for pid, r in by_path.items()}
            edges = [
                r.mean_trade_ret * _BPS_PER_UNIT
                for r in by_path.values()
                if math.isfinite(r.mean_trade_ret)
            ]
            pooled_edge = (
                sum(edges) / len(edges)  # noqa: unguarded-ratio -- guardado pelo `if edges`
                if edges
                else float("nan")
            )
            seed_pooled_edge[seed] = pooled_edge
            seed_trade_count[seed] = sum(r.n_filled_trades for r in by_path.values())
        finite_pooled = [v for v in seed_pooled.values() if math.isfinite(v)]
        median_pooled = float(np.median(finite_pooled)) if finite_pooled else float("nan")
        finite_edge = [v for v in seed_pooled_edge.values() if math.isfinite(v)]
        median_pooled_edge = float(np.median(finite_edge)) if finite_edge else float("nan")
        median_trade_count = (
            float(np.median(list(seed_trade_count.values()))) if seed_trade_count else 0.0
        )
        screening_value = float(trial.value) if trial.value is not None else float("nan")
        candidates.append(
            ConfirmedCandidate(
                hyper=hyper,
                screening_value=screening_value,
                seed_pooled_sharpe=seed_pooled,
                seed_path_sharpe=seed_paths,
                median_pooled_sharpe=median_pooled,
                selection_bias_estimate=screening_value - median_pooled,
                seed_pooled_edge_bps=seed_pooled_edge,
                seed_pooled_trade_count=seed_trade_count,
                median_pooled_edge_bps=median_pooled_edge,
                median_trade_count=median_trade_count,
            )
        )
        logger.info(
            "models.hyperparams_optuna.confirmation_candidate_done",
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            screening_value=screening_value,
            median_pooled_sharpe=median_pooled,
            selection_bias_estimate=screening_value - median_pooled,
            median_pooled_edge_bps=median_pooled_edge,
            median_trade_count=median_trade_count,
        )

    def _sort_key(c: ConfirmedCandidate) -> float:
        return c.median_pooled_sharpe if math.isfinite(c.median_pooled_sharpe) else -math.inf

    candidates.sort(key=_sort_key, reverse=True)
    winner = candidates[0]
    logger.info(
        "models.hyperparams_optuna.confirmation_done",
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        top_k=top_k,
        n_seeds=len(confirmation_seeds),
        winner_median_pooled_sharpe=winner.median_pooled_sharpe,
        winner_screening_value=winner.screening_value,
        winner_selection_bias=winner.selection_bias_estimate,
        winner_median_pooled_edge_bps=winner.median_pooled_edge_bps,
        winner_median_trade_count=winner.median_trade_count,
    )
    return ConfirmationResult(
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        top_k=top_k,
        confirmation_seeds=confirmation_seeds,
        candidates=tuple(candidates),
        winner=winner,
    )


@dataclass(frozen=True, slots=True)
class PairedGateResult:
    """Gate de permanência real (Camada1 vs. Camada0, pareado por caminho do
    CPCV), calculado das MESMAS rodadas de `confirm_top_k_multi_seed` --
    `n_better` por seed = nº de caminhos onde o vencedor confirmado da
    Camada1 supera o vencedor confirmado da Camada0 em Sharpe; veredito
    pela MEDIANA entre seeds (nunca de 1 seed isolada). RESSALVA `AG-220`
    (não corrigida aqui): este gate já foi medido oscilando FALSE→TRUE→
    FALSE só por calibração — um `permanence_pass=True` aqui é mais
    confiável que o de 1 seed (viés de seleção removido), mas não resolve
    o poder estatístico questionado pelo `AG-220`.

    `edge_gate_pass`/`dual_gate_pass` (AG-383-ADDENDUM, pedido do Manager
    2026-08-30) -- `permanence_pass` é RELATIVO (Camada1 bate Camada0 em
    Sharpe, consistência sob variância); um hiperparâmetro pode passar
    nisso com edge bruto nulo/negativo (baixa variância, média perto de 0).
    `edge_gate_pass` exige ABSOLUTO: a Camada1 vencedora (candidata real a
    promoção -- Camada0 é só referência, nunca promovida sozinha) precisa
    de `median_pooled_edge_bps > alpha_layer1_permanence_min_edge_bps`
    (break-even é o piso, não magnitude arbitrária) SOB cobertura mínima
    (`median_trade_count >= alpha_layer1_permanence_min_trades`, piso de
    confiabilidade estatística da média, não seleção de sinal). O piso de
    cobertura existe deliberadamente pra não deixar o gate ser vencido por
    um hiperparâmetro que fica seletivo demais -- decidir QUAIS sinais
    valem a pena executar é papel do Meta-model (`§15.19`, ainda travado em
    desenho, zero implementado), não do Alpha; o Alpha continua sendo
    julgado só pela qualidade do score bruto (`score_alpha_raw`) sob a
    MESMA regra de entrada fixa (`tau_policy=TAU_POLICY_LEGACY_PER_SIDE`)
    já usada no Sharpe -- nenhum mecanismo de seletividade novo é
    introduzido pelo gate de edge. `dual_gate_pass = permanence_pass AND
    edge_gate_pass` -- só combos que sobrevivem aos dois testes (relativo E
    absoluto) são candidatos reais a promoção."""

    symbol: str
    resolution_id: str
    camada1: ConfirmationResult
    camada0: ConfirmationResult
    n_better_by_seed: dict[int, int]
    median_n_better: float
    permanence_min_paths: int
    permanence_pass: bool
    edge_min_bps: float
    edge_min_trades: int
    winner_median_pooled_edge_bps: float
    winner_median_trade_count: float
    edge_gate_pass: bool
    dual_gate_pass: bool


def confirm_combo_paired(
    *,
    symbol: str,
    resolution_id: str,
    top_k: int | None = None,
    confirmation_seeds: tuple[int, ...] | None = None,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
    feature_ids: tuple[str, ...] | None = None,
    n_trials: int | None = None,
    sampler_seed: int | None = None,
    storage_dir: Path | None = None,
) -> PairedGateResult:
    """Confirma Camada1 e Camada0 independentemente (`confirm_top_k_multi_
    seed` 2x — nunca uma herdando o vencedor da outra, mesma exigência de
    ablação válida do módulo inteiro) e computa o gate de permanência
    pareado sobre os 2 vencedores confirmados.

    `top_k`/`confirmation_seeds` (ADR-007 Item 2, 2026-08-30) -- default
    `None` resolve de `alpha_optuna_confirm_top_k`/`alpha_optuna_confirm_
    seeds` (`constants.yaml`), mesmo padrão sentinela de `n_trials`/
    `sampler_seed` já usado aqui. Passar explícito sempre funciona --
    testes existentes (valores fixos passados direto) preservados
    bit-a-bit."""
    top_k_resolved = (
        top_k if top_k is not None else int(load_constant("alpha_optuna_confirm_top_k"))
    )
    confirmation_seeds_resolved = (
        confirmation_seeds
        if confirmation_seeds is not None
        else tuple(int(s) for s in load_constant("alpha_optuna_confirm_seeds"))
    )
    kwargs: dict[str, Any] = {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "top_k": top_k_resolved,
        "confirmation_seeds": confirmation_seeds_resolved,
        "device_type": device_type,
        "vol_estimator_id": vol_estimator_id,
        "feature_ids": feature_ids,
        "n_trials": n_trials,
        "sampler_seed": sampler_seed,
        "storage_dir": storage_dir,
    }
    camada1 = confirm_top_k_multi_seed(variant=alpha.VARIANT_CAMADA1, **kwargs)
    camada0 = confirm_top_k_multi_seed(variant=alpha.VARIANT_CAMADA0, **kwargs)

    permanence_min_paths = int(load_constant("alpha_layer1_permanence_min_paths"))
    n_better_by_seed: dict[int, int] = {}
    for seed in confirmation_seeds_resolved:
        c1_paths = camada1.winner.seed_path_sharpe[seed]
        c0_paths = camada0.winner.seed_path_sharpe[seed]
        common = set(c1_paths) & set(c0_paths)
        n_better_by_seed[seed] = sum(1 for p in common if c1_paths[p] > c0_paths[p])
    median_n_better = float(np.median(list(n_better_by_seed.values())))
    permanence_pass = median_n_better >= permanence_min_paths

    edge_min_bps = float(load_constant("alpha_layer1_permanence_min_edge_bps"))
    edge_min_trades = int(load_constant("alpha_layer1_permanence_min_trades"))
    winner_edge = camada1.winner.median_pooled_edge_bps
    winner_trades = camada1.winner.median_trade_count
    edge_gate_pass = (
        math.isfinite(winner_edge)
        and winner_edge > edge_min_bps
        and winner_trades >= edge_min_trades
    )
    dual_gate_pass = permanence_pass and edge_gate_pass

    logger.info(
        "models.hyperparams_optuna.confirm_combo_paired_done",
        symbol=symbol,
        resolution_id=resolution_id,
        n_better_by_seed=n_better_by_seed,
        median_n_better=median_n_better,
        permanence_min_paths=permanence_min_paths,
        permanence_pass=permanence_pass,
        winner_median_pooled_edge_bps=winner_edge,
        winner_median_trade_count=winner_trades,
        edge_min_bps=edge_min_bps,
        edge_min_trades=edge_min_trades,
        edge_gate_pass=edge_gate_pass,
        dual_gate_pass=dual_gate_pass,
    )
    return PairedGateResult(
        symbol=symbol,
        resolution_id=resolution_id,
        camada1=camada1,
        camada0=camada0,
        n_better_by_seed=n_better_by_seed,
        median_n_better=median_n_better,
        permanence_min_paths=permanence_min_paths,
        permanence_pass=permanence_pass,
        edge_min_bps=edge_min_bps,
        edge_min_trades=edge_min_trades,
        winner_median_pooled_edge_bps=winner_edge,
        winner_median_trade_count=winner_trades,
        edge_gate_pass=edge_gate_pass,
        dual_gate_pass=dual_gate_pass,
    )


def _paired_gate_to_json(result: PairedGateResult) -> dict[str, Any]:
    def _confirmation_to_json(c: ConfirmationResult) -> dict[str, Any]:
        return {
            "top_k": c.top_k,
            "confirmation_seeds": list(c.confirmation_seeds),
            "winner": {
                "hyper": dataclasses.asdict(c.winner.hyper),
                "screening_value": c.winner.screening_value,
                "median_pooled_sharpe": c.winner.median_pooled_sharpe,
                "selection_bias_estimate": c.winner.selection_bias_estimate,
                "seed_pooled_sharpe": c.winner.seed_pooled_sharpe,
                "median_pooled_edge_bps": c.winner.median_pooled_edge_bps,
                "median_trade_count": c.winner.median_trade_count,
                "seed_pooled_edge_bps": c.winner.seed_pooled_edge_bps,
                "seed_pooled_trade_count": c.winner.seed_pooled_trade_count,
            },
            "candidates": [
                {
                    "hyper": dataclasses.asdict(cand.hyper),
                    "screening_value": cand.screening_value,
                    "median_pooled_sharpe": cand.median_pooled_sharpe,
                    "selection_bias_estimate": cand.selection_bias_estimate,
                    "median_pooled_edge_bps": cand.median_pooled_edge_bps,
                    "median_trade_count": cand.median_trade_count,
                }
                for cand in c.candidates
            ],
        }

    return {
        "symbol": result.symbol,
        "resolution_id": result.resolution_id,
        "n_better_by_seed": result.n_better_by_seed,
        "median_n_better": result.median_n_better,
        "permanence_min_paths": result.permanence_min_paths,
        "permanence_pass": result.permanence_pass,
        "edge_min_bps": result.edge_min_bps,
        "edge_min_trades": result.edge_min_trades,
        "winner_median_pooled_edge_bps": result.winner_median_pooled_edge_bps,
        "winner_median_trade_count": result.winner_median_trade_count,
        "edge_gate_pass": result.edge_gate_pass,
        "dual_gate_pass": result.dual_gate_pass,
        "camada1": _confirmation_to_json(result.camada1),
        "camada0": _confirmation_to_json(result.camada0),
    }


def _run_confirmation_cli(args: Any) -> None:
    """AG-382-ADDENDUM (2026-08-30) -- confirmação multi-seed (top-K,
    mediana, gate pareado) sobre os resultados já gravados pela campanha
    real. Nunca sob `--all-combinations` implícito: cada (symbol,
    resolution_id) roda os 2 braços (Camada1+Camada0) via `confirm_combo_
    paired`. Escreve 1 JSON por combo em `experiments/` (mesma convenção já
    usada por `t2_t1_capacity_map_*.json`/`noise_floor_diagnostics_*.json`)
    -- nunca sobrescreve silenciosamente um relatório existente do mesmo
    dia (achado real: sem timestamp no nome, uma rodada abortada e
    re-lançada perderia o relatório da rodada anterior sem aviso)."""
    import json
    from datetime import UTC, datetime

    # ADR-007 Item 2 -- None (default do CLI) deixa confirm_combo_paired
    # resolver de alpha_optuna_confirm_seeds/alpha_optuna_confirm_top_k
    # (constants.yaml); só materializa a tupla aqui quando o usuário passou
    # valor explícito no CLI.
    confirmation_seeds = tuple(args.confirmation_seeds) if args.confirmation_seeds else None
    if args.all_combinations:
        symbols: tuple[str, ...] = ALL_SYMBOLS
        resolutions: tuple[str, ...] = ALL_RESOLUTIONS
    else:
        if args.symbol is None or args.resolution_id is None:
            raise SystemExit("--symbol e --resolution-id são obrigatórios sem --all-combinations")
        symbols = (args.symbol,)
        resolutions = (args.resolution_id,)

    out_dir = Path("experiments")
    out_dir.mkdir(parents=True, exist_ok=True)
    run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    results: list[PairedGateResult] = []
    for symbol in symbols:
        for resolution_id in resolutions:
            result = confirm_combo_paired(
                symbol=symbol,
                resolution_id=resolution_id,
                top_k=args.top_k,
                confirmation_seeds=confirmation_seeds,
                device_type=args.device_type,
                vol_estimator_id=args.vol_estimator_id,
                n_trials=args.n_trials,
                sampler_seed=args.sampler_seed,
            )
            results.append(result)
            out_path = (
                out_dir
                / f"alpha_optuna_confirmation_{symbol}_{resolution_id}_{run_stamp}.json"
            )
            out_path.write_text(
                json.dumps(_paired_gate_to_json(result), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(
                "models.hyperparams_optuna.confirmation_report_written",
                symbol=symbol,
                resolution_id=resolution_id,
                path=str(out_path),
                permanence_pass=result.permanence_pass,
                median_n_better=result.median_n_better,
            )

    summary_path = out_dir / f"alpha_optuna_confirmation_summary_{run_stamp}.json"
    summary_path.write_text(
        json.dumps([_paired_gate_to_json(r) for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "models.hyperparams_optuna.confirmation_campaign_done",
        n_combos=len(results),
        n_permanence_pass=sum(1 for r in results if r.permanence_pass),
        n_edge_gate_pass=sum(1 for r in results if r.edge_gate_pass),
        n_dual_gate_pass=sum(1 for r in results if r.dual_gate_pass),
        summary_path=str(summary_path),
    )


def _run_cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Campanha Optuna real de busca de hiperparametro LightGBM do Alpha -- "
            "substitui config/alpha_hyperparams_by_combo.yaml (AG-371). Escreve o "
            "vencedor como artefato content-addressed (artifacts/alpha_hyperparams_optuna/)."
        )
    )
    parser.add_argument("--symbol", type=str, default=None, choices=ALL_SYMBOLS)
    parser.add_argument("--resolution-id", type=str, default=None, choices=ALL_RESOLUTIONS)
    parser.add_argument("--variant", type=str, default=None, choices=ALL_VARIANTS)
    parser.add_argument("--all-combinations", action="store_true")
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--device-type", type=str, default="cpu", choices=["cpu", "cuda", "gpu"])
    parser.add_argument("--sampler-seed", type=int, default=None)
    parser.add_argument("--dsr-n-trials", type=int, default=None)
    parser.add_argument("--scratch", action="store_true")
    parser.add_argument("--vol-estimator-id", type=str, default=None)
    # AG-382-ADDENDUM -- confirmação multi-seed (top-K + mediana + gate
    # pareado) sobre uma campanha JÁ RODADA -- nunca junto de uma busca
    # nova na mesma invocação (2 responsabilidades distintas, mesmo CLI).
    parser.add_argument("--confirm", action="store_true")
    # ADR-007 Item 2 (2026-08-30) -- default None resolve de
    # alpha_optuna_confirm_top_k/alpha_optuna_confirm_seeds (constants.yaml)
    # dentro de confirm_combo_paired, mesmo padrão sentinela de --n-trials
    # acima. Literal antigo (3 / 5 seeds) promovido pra constants.yaml.
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument(
        "--confirmation-seeds",
        type=int,
        nargs="+",
        default=None,
        help=(
            "Seeds novas pra confirmação -- NUNCA reusa alpha_random_seed da "
            "busca original. Default: alpha_optuna_confirm_seeds (constants.yaml)."
        ),
    )
    args = parser.parse_args()

    if args.confirm:
        _run_confirmation_cli(args)
        return

    if args.all_combinations:
        symbols: tuple[str, ...] = ALL_SYMBOLS
        resolutions: tuple[str, ...] = ALL_RESOLUTIONS
        variants: tuple[str, ...] = ALL_VARIANTS
    else:
        if args.symbol is None or args.resolution_id is None:
            parser.error("--symbol e --resolution-id são obrigatórios sem --all-combinations")
        symbols = (args.symbol,)
        resolutions = (args.resolution_id,)
        variants = (args.variant,) if args.variant is not None else ALL_VARIANTS

    for symbol in symbols:
        for resolution_id in resolutions:
            for variant in variants:
                run_search_for_combo(
                    symbol=symbol,
                    resolution_id=resolution_id,
                    variant=variant,
                    vol_estimator_id=args.vol_estimator_id,
                    device_type=args.device_type,
                    n_trials=args.n_trials,
                    sampler_seed=args.sampler_seed,
                    dsr_n_trials=args.dsr_n_trials,
                    scratch=args.scratch,
                )


if __name__ == "__main__":
    _run_cli()
