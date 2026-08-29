"""Orquestração ponta a ponta do Sprint 8 — Alpha Camada 1 (§5, §16.1,
§16.6). Roda os 15 splits do CPCV (Sprint 7) para as duas variantes
(Camada 1 monotônica e Camada 0 conceitual sem restrição), os 5 baselines
nulos, a decomposição de PnL, e decide o critério de permanência do §5.11
adaptado (`alpha_layer1_permanence_min_paths`, ver `constants.yaml`).

Escreve `predictions.parquet` (§5.12/PRD_V4_1.md T0.3, um arquivo por
variante) em `predictions/alpha/{model_id}/` por default (`tf=None`,
caminho legado plano — ver docstring de `run_layer1_sprint` pro porquê:
7 leitores de produção reais ainda dependem dele) ou em
`predictions/alpha/{symbol}/{tf}/{model_id}/` (layout chaveado) quando
`tf` é passado explicitamente; e `experiments/alpha_layer1_report.json`
(números desta rodada — HHI, baselines, decomposição, decisão de
permanência)."""

from __future__ import annotations

import io
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.data import download
from src.data.resample import step_ms
from src.features import build as features_build
from src.io import artifact as io_artifact
from src.validation import cpcv
from src.validation import dsr as dsr_mod

from . import (
    alpha,
    backtest_lite,
    baselines,
    decomposition,
    economic_gate,
    hhi,
    hyperparams_by_combo,
    monotonic,
    persistence,
)
from . import dataset as ds
from ._constants import load_constant

# Reexport explícito (`as ARTIFACT_ROOT`/`as MODELS_DIR`, não só `import
# ARTIFACT_ROOT`/`import MODELS_DIR`) — `mypy --strict`/`no_implicit_
# reexport` (`pyproject.toml`) trata um import simples como privado ao
# módulo; testes/chamadores fazem `pipeline.ARTIFACT_ROOT` (D-06,
# 2026-08-23, fecha AG-154) e `from src.models.pipeline import MODELS_DIR`
# (`faixa1_5_prerequisites.py`, ver AG-013) e precisam continuar
# funcionando sob checagem estrita, não só em runtime.
from ._paths import ARTIFACT_ROOT as ARTIFACT_ROOT
from ._paths import (
    EXPERIMENTS_DIR,
    PREDICTIONS_OUTPUT_DIR,
    REPO_ROOT,
    models_diagnostics_symbol_tf_dir,
    predictions_symbol_tf_dir,
)
from ._paths import MODELS_DIR as MODELS_DIR

logger = structlog.get_logger(__name__)

MODEL_ID_CAMADA1 = "alpha_c1_v1"
MODEL_ID_CAMADA0 = "alpha_c0_baseline_v1"

SYMBOL = ds.SYMBOL_DEFAULT

# `MODELS_DIR` (AG-013) — importado de `._paths` acima, não redefinido
# aqui. Vivia neste módulo até AG-013 (`models/{model_id}/diagnostics/`,
# task A1 do CLAUDE.md, diretório de DADO no topo do repo, irmão de
# `data/`/`predictions/`/`experiments/`, não o pacote de código
# `src/models/`); movido para `_paths.py` porque agora existe um layout
# chaveado (`models_diagnostics_symbol_tf_dir`) que precisa viver junto —
# ver docstring de `MODELS_DIR` em `_paths.py` para o porquê completo.
# `pipeline.MODELS_DIR` continua existindo (mesmo objeto `Path`) para não
# quebrar nenhum `monkeypatch.setattr(pipeline, "MODELS_DIR", ...)`
# existente nem nenhum `from src.models.pipeline import MODELS_DIR`.


def write_predictions_atomic(
    predictions: pl.DataFrame, model_id: str, *, dest_dir: Path | None = None
) -> Path:
    """§5.12 — `predictions/alpha/{model_id}/predictions.parquet`. Mesmo
    padrão `.tmp -> fsync -> rename` (B29) de
    `src.labels.triple_barrier.write_labels_atomic`.

    `dest_dir` (T0.3): default `None` preserva o caminho legado
    `PREDICTIONS_OUTPUT_DIR/alpha/{model_id}`. Passar
    `_paths.predictions_symbol_tf_dir(symbol, model_id)` grava no layout
    chaveado novo.

    **Risco residual aceito, registrado (`AG-194`, achado `project_
    assurance` da migração LightGBM, 2026-08-23):** esta função já
    escreve o schema NOVO de 21 colunas (`alpha.PREDICTIONS_SCHEMA_
    COLUMNS`, D-03/D-05) incondicionalmente, inclusive no CAMINHO
    legado (`dest_dir=None`) — sem trava técnica que force o cutover
    coordenado que D-06 (`docs/alpha_model_design_doc_2026-08-22.md
    §13`) descreve ("regenerar as 15 combinações + atualizar os 2
    consumidores reais + descartar os 5 legados, no mesmo PR"). Se
    `run_layer1_sprint()` rodar antes desse PR coordenado, o parquet
    resultante no caminho legado teria 21 colunas onde os 2 consumidores
    reais incondicionais (`src/backtest/fill_reconciliation.py`,
    `src/analysis/calibration_diagnostics.py`) esperam 17 -- risco
    mecanicamente pequeno hoje (nenhum lê por posição/contagem de
    coluna, ambos selecionam por nome) mas não verificado
    exaustivamente. Aceito sem trava de código porque o gate real
    ("Data Layer 100%") é uma questão de DADO ausente (labels/features
    R2/R3), não algo que só um lock em código evitaria -- ninguém roda
    isto sem querer. Não escondido: se o gate abrir e este PR coordenado
    não acontecer junto, revisitar aqui primeiro."""
    out_dir = dest_dir if dest_dir is not None else (PREDICTIONS_OUTPUT_DIR / "alpha" / model_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_path = out_dir / "predictions.parquet"
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")

    buffer = io.BytesIO()
    predictions.select(list(alpha.PREDICTIONS_SCHEMA_COLUMNS)).write_parquet(buffer)
    with tmp_path.open("wb") as fh:
        fh.write(buffer.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info(
        "models.pipeline.predictions_written", path=str(dest_path), n_rows=predictions.height
    )
    return dest_path


PREDICTIONS_ARTIFACT_STAGE = "predictions_alpha"


def write_predictions_versioned(
    predictions: pl.DataFrame,
    *,
    root: Path,
    symbol: str,
    resolution_id: str,
    model_id: str,
    config: dict[str, Any],
    scratch: bool = False,
) -> io_artifact.ArtifactManifest:
    """D-06 (docs/alpha_model_design_doc_2026-08-22.md, fecha `AG-154`) --
    escreve `predictions.parquet` via `src.io.artifact.write_artifact`
    (schema versionado + manifest com `config_hash`, camada ADR-001) em
    vez do caminho ad-hoc de `write_predictions_atomic` acima. `config`
    deve incluir pelo menos `model_id`/`variant` (o `stage` sozinho não
    distingue Camada 1 de Camada 0 -- `config_hash` distingue).

    **INTEGRADA em `run_layer1_sprint` 2026-08-23 (fecha `AG-154`), escopo
    ESTREITO -- correção do plano original acima.** Chamada só quando
    `resolution_id` é setado (o ramo dollar-bar, as 15 combinações reais) --
    esta função EXIGE `resolution_id: str` (não opcional), então nunca
    poderia servir o ramo legado (`tf`/`resolution_id=None`) de qualquer
    forma. Achado ao investigar o cutover completo que o parágrafo anterior
    descrevia: os "2 consumidores reais incondicionais" (`fill_
    reconciliation.py::load_predictions`, `calibration_diagnostics.py`) NEM
    ACEITAM `symbol`/`resolution_id` como parâmetro -- são cegos ao
    multi-resolução com QUALQUER writer, sempre foram, e só leem o caminho
    legado plano (nunca tocado por esta função). Não há, portanto,
    "atualizar os 2 consumidores"/"descartar os 5 legados" como
    pré-requisito de correção -- o caminho legado não muda, os consumidores
    que dependem dele não são afetados. Dar a esses 2 consumidores
    capacidade de ler predições multi-resolução fica registrado como
    trabalho ADITIVO separado (não bloqueante), não parte deste fechamento."""
    return io_artifact.write_artifact(
        predictions.select(list(alpha.PREDICTIONS_SCHEMA_COLUMNS)),
        root=root,
        stage=PREDICTIONS_ARTIFACT_STAGE,
        symbol=symbol,
        resolution=resolution_id,
        config={"model_id": model_id, **config},
        schema=alpha.PREDICTIONS_ARTIFACT_SCHEMA,
        producer_entrypoint="src.models.pipeline.run_layer1_sprint",
        scratch=scratch,
    )


def write_report_atomic(payload: dict[str, Any], dest_path: Path | None = None) -> Path:
    default_path = EXPERIMENTS_DIR / "alpha_layer1_report.json"
    out_path = dest_path if dest_path is not None else default_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("models.pipeline.report_written", path=str(out_path))
    return out_path


# Texto exato pedido pela task A1 (CLAUDE.md) — `best_iteration` não tem
# significado sem early stopping implementado; reportar `null` com esta nota
# em vez de inventar um número (mesma disciplina de B23/"TBD — medir no
# Sprint N").
_BEST_ITERATION_NOTE = "early stopping nao implementado nesta rodada, ver docstring alpha.py"


def _side_label(side: int) -> str:
    """+1 -> "long", -1 -> "short" — nome de arquivo legível (task A1 do
    CLAUDE.md pede explicitamente isso em vez de `+1`/`-1` cru)."""
    if side == 1:
        return "long"
    if side == -1:
        return "short"
    raise ValueError(f"_side_label: side desconhecido {side!r} (esperado +1 ou -1)")


def _fold_diagnostics_payload(
    fold_result: alpha.FoldResult,
    side_result: alpha.SideModelResult,
    *,
    model_id: str,
    expected_n_trees: int,
) -> dict[str, Any]:
    """Diagnóstico por fold x lado — a investigação que motivou a task A1
    encontrou que `gain_by_column` (bruto) e `concentration.shares`
    (normalizado) só viviam em memória dentro de `fit_side_model`/
    `run_layer1_sprint`: recuperá-los depois do fato custou um retreino
    completo (~117s, ver CLAUDE.md, contexto desta task). Este dict é
    serializado 1:1 em `models/{model_id}/diagnostics/fold_{fold_id}_
    {side_label}.json` por `write_fold_diagnostics_atomic`.

    `n_trees` vem de `booster.num_trees()` (LightGBM, D-12 -- era
    `booster.num_boosted_rounds()` do XGBoost) — como early stopping
    não está implementado nesta rodada (ver docstring do módulo
    `src.models.alpha` e `constants.yaml:alpha_lgbm_n_estimators`), o
    esperado é `n_trees == alpha_lgbm_n_estimators` (300) sempre; um desvio
    é logado como warning aqui em vez de silenciosamente ignorado.
    `best_iteration` não tem significado sem early stopping — reportado
    como `null` com uma nota explícita, nunca inventado (mesma disciplina
    de `TBD — medir no Sprint N`, B23)."""
    booster = side_result.model.booster_
    n_trees = int(booster.num_trees())
    if n_trees != expected_n_trees:
        logger.warning(
            "models.pipeline.diagnostics_n_trees_diverge_de_n_estimators",
            n_trees=n_trees,
            alpha_lgbm_n_estimators=expected_n_trees,
            fold_id=fold_result.fold_id,
            side=side_result.side,
            model_id=model_id,
        )

    return {
        "schema_version": 1,
        "model_id": model_id,
        "variant": fold_result.variant,
        "fold_id": fold_result.fold_id,
        "path_id": fold_result.path_id,
        "side": side_result.side,
        "side_label": _side_label(side_result.side),
        "gain_by_column": side_result.gain_by_column_raw,
        "concentration_shares": side_result.concentration.shares,
        # `.value` — `hhi`/`max_share` são `Metric` (`src.core.metric`,
        # ver nota em `hhi_values_long` acima); mantido como float plano
        # aqui para não quebrar o schema já gravado nos 30+30 arquivos
        # reais desta rodada (ver DoD/relatório da task A1/A2) — a
        # proveniência completa do Metric (unit/n/source/valid) continua
        # disponível em `side_result.concentration.hhi`/`.max_share` para
        # quem precisar, só não duplicada neste JSON.
        "hhi": side_result.concentration.hhi.value,
        "max_share": side_result.concentration.max_share.value,
        "n_features_over_1pct": side_result.concentration.n_features_over_1pct,
        # HHI EFETIVO (D1/D2, CLAUDE.md) — irmão do "hhi" nominal acima,
        # NUNCA o substitui. Mede concentração no espaço de FATORES DE
        # INFORMAÇÃO das 10 features T1 (após remover redundância de
        # features correlacionadas no fold), ver
        # `src.models.hhi.compute_effective_concentration` para a derivação
        # exata. `.value` pelo mesmo motivo do `hhi`/`max_share` acima —
        # proveniência completa (`unit`/`n`/`source`/`valid`) continua
        # disponível em `side_result.concentration_effective` para quem
        # precisar.
        "hhi_effective": side_result.concentration_effective.hhi_effective.value,
        "n_eff_factors_t1": side_result.concentration_effective.n_eff_factors.value,
        "concentration_effective_weights": side_result.concentration_effective.weights,
        "concentration_effective_eigenvalues": list(
            side_result.concentration_effective.eigenvalues
        ),
        "n_trees": n_trees,
        "best_iteration": None,
        "best_iteration_note": _BEST_ITERATION_NOTE,
        "n_amostras": {
            "n_train_fit": side_result.n_train_fit,
            "n_train_calib": side_result.n_train_calib,
        },
    }


def write_fold_diagnostics_atomic(
    fold_result: alpha.FoldResult,
    *,
    model_id: str,
    expected_n_trees: int,
    dest_dir: Path | None = None,
) -> list[Path]:
    """`models/{model_id}/diagnostics/fold_{fold_id}_{side_label}.json` —
    um arquivo por fold x lado (long e short), B29: `.tmp` -> `fsync` ->
    `rename`, mesmo padrão de `write_predictions_atomic`/
    `write_report_atomic` acima. Ver `.gitignore`: `models/*/diagnostics/`
    é intencionalmente versionado (evidência de auditoria pequena e
    legível, mesma categoria de `data/quality_reports/`), não é o artefato
    binário de modelo que `models/*.bin`/`models/*.json` (raiz de
    `models/{model_id}/`) ignoram.

    `dest_dir` (AG-013, mesmo sentinela `Path | None = None` de
    `write_predictions_atomic`/`run_layer1_sprint`, AG-006/AG-012): default
    `None` preserva o caminho legado `MODELS_DIR/{model_id}/diagnostics/`,
    bit-exato com todo chamador/teste existente — nenhum passa este
    argumento hoje. Passar `src.models._paths.
    models_diagnostics_symbol_tf_dir(symbol, model_id, tf=tf)` grava no
    layout chaveado novo (`models/{symbol}/{tf}/{model_id}/diagnostics/`)
    em vez do plano — ver docstring desse helper para por que o default
    NÃO migra (JSON versionado no git, migrar o default orfanaria os 30+
    arquivos já commitados)."""
    out_dir = dest_dir if dest_dir is not None else (MODELS_DIR / model_id / "diagnostics")
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for side_result in (fold_result.long_result, fold_result.short_result):
        payload = _fold_diagnostics_payload(
            fold_result, side_result, model_id=model_id, expected_n_trees=expected_n_trees
        )
        side_label = _side_label(side_result.side)
        dest_path = out_dir / f"fold_{fold_result.fold_id}_{side_label}.json"
        tmp_path = dest_path.with_name(dest_path.name + ".tmp")

        blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
        with tmp_path.open("wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, dest_path)
        written.append(dest_path)

    logger.info(
        "models.pipeline.fold_diagnostics_written",
        model_id=model_id,
        fold_id=fold_result.fold_id,
        n_files=len(written),
    )
    return written


def write_all_fold_diagnostics(
    fold_results: list[alpha.FoldResult],
    *,
    model_id: str,
    hyper: alpha.LGBMHyperparams,
    dest_dir: Path | None = None,
) -> list[Path]:
    """Escreve o diagnóstico de todos os folds de uma variante (Camada 1 OU
    Camada 0) — chamada duas vezes por `run_layer1_sprint`, uma por
    variante, cada uma com seu próprio `model_id`.

    `dest_dir` (AG-013) — repassado sem alteração a
    `write_fold_diagnostics_atomic` para cada fold, mesmo sentinela
    (`None` preserva o caminho legado plano)."""
    written: list[Path] = []
    for fr in fold_results:
        written.extend(
            write_fold_diagnostics_atomic(
                fr, model_id=model_id, expected_n_trees=hyper.n_estimators, dest_dir=dest_dir
            )
        )
    return written


def write_all_fold_model_bundles(
    fold_results: list[alpha.FoldResult],
    *,
    symbol: str,
    resolution_id: str,
    hyper: alpha.LGBMHyperparams,
    feature_ids: tuple[str, ...],
    purge_ms_effective: int,
    root: Path = REPO_ROOT,
) -> list[persistence.ModelBundleManifest]:
    """Fecha `AG-141` (item 10 de `ADR-005 §13.17`, `§13.5-5`) — a metade
    de INTEGRAÇÃO que faltava: `src.models.persistence.write_model_bundle`
    existia desde 2026-08-22, testado e revisado, mas nenhum caminho de
    produção o chamava (`alpha.py::run_fold` nunca invocava). Chamada aqui,
    NA CASCA (`pipeline.py`), não dentro de `run_fold` — os campos que o
    manifesto precisa (`hyper`, `purge_ms_effective`, `feature_ids`) já
    estão todos resolvidos UMA VEZ em `run_layer1_sprint`, e persistir em
    disco é efeito colateral de IO, não parte do NÚCLEO de treino
    (`Núcleo funcional, casca imperativa`, `CLAUDE.md`).

    Opt-in (`persist_model_bundles` em `run_layer1_sprint`) -- chamador
    explícito, nunca default. `tau` gravado é o EFETIVAMENTE APLICADO
    (`predictions["tau_long"/"tau_short"][0]`, constante dentro do fold),
    não `long_result.tau`/`short_result.tau` -- os dois só coincidem sob
    `TAU_POLICY_LEGACY_PER_SIDE`; sob `TAU_POLICY_TOTAL_COMMON_OOF` o
    per-side fica stale (`run_fold` resolve os dois juntos DEPOIS de
    computar `long_result`/`short_result`). Mesmo motivo pelo qual
    `predictions.parquet` persiste o aplicado, não o per-side.

    `ModelBundleExistsError` propaga sem tratamento -- um bundle já
    escrito para a mesma `(symbol, resolution_id, model_id, fold_id, side,
    variant)` é imutável por desenho (AG-141); reexecutar
    `run_layer1_sprint` com `persist_model_bundles=True` sobre uma
    partição já persistida deve FALHAR, não sobrescrever nem pular em
    silêncio."""
    written: list[persistence.ModelBundleManifest] = []
    for fr in fold_results:
        fold_id = f"fold{fr.fold_id}"
        tau_long = float(fr.predictions["tau_long"][0])
        tau_short = float(fr.predictions["tau_short"][0])
        for side_result, side, tau in (
            (fr.long_result, 1, tau_long),
            (fr.short_result, -1, tau_short),
        ):
            manifest = persistence.write_model_bundle(
                root=root,
                symbol=symbol,
                resolution_id=resolution_id,
                model_id=fr.model_id,
                fold_id=fold_id,
                side=side,
                variant=fr.variant,
                booster=side_result.model.booster_,
                calibrator=side_result.calibrator,
                tau=tau,
                feature_ids=feature_ids,
                monotone_constraints=side_result.monotone_constraints,
                ess=side_result.sum_uniqueness_train,
                purge_ms_effective=purge_ms_effective,
                min_child_samples=hyper.min_child_samples,
            )
            written.append(manifest)
    return written


def _path_results_to_dict(by_path: dict[int, backtest_lite.PathBacktestResult]) -> dict[str, Any]:
    return {str(pid): asdict(r) for pid, r in sorted(by_path.items())}


def _finite(values: list[float]) -> NDArray[np.float64]:
    arr = np.asarray(values, dtype=np.float64)
    return arr[np.isfinite(arr)]


def _mean_finite(values: list[float]) -> float:
    finite = _finite(values)
    return float(np.mean(finite)) if finite.size else float("nan")


def _percentile_finite(values: list[float], pct: float) -> float:
    finite = _finite(values)
    return float(np.percentile(finite, pct)) if finite.size else float("nan")


def _summarize_b1_result(b1: baselines.B1Result) -> dict[str, Any]:
    """`B1Result.null_sharpes` é `numpy.ndarray` -- não serializa via
    `asdict()` cru (`write_report_atomic`/`orjson` não sabe converter).
    Mesmo achatamento em resumo que já era feito à mão só pra `b1`
    (`report["baselines"]["b1_random_entry"]`) antes deste helper existir
    -- extraído aqui 2026-08-27 (handoff de `src/models/`, item 3) porque
    o refinamento B1 (opt-in, `run_b1_refinement`) precisa do MESMO
    achatamento em 2 lugares novos (por caminho, carry-stripped), e
    duplicar a fórmula 3x arriscaria as cópias divergirem."""
    return {
        "n_seeds": b1.n_seeds,
        "sample_size": b1.sample_size,
        "alpha_sharpe": b1.alpha_sharpe,
        "percentile_of_alpha": b1.percentile,
        "null_mean": _mean_finite(list(b1.null_sharpes)),
        "null_p50": _percentile_finite(list(b1.null_sharpes), 50.0),  # noqa: magic-number
        "null_p95": _percentile_finite(list(b1.null_sharpes), 95.0),  # noqa: magic-number
    }


def compute_permutation_null_headline(
    df_all: pl.DataFrame,
    splits: tuple[cpcv.CPCVSplit, ...],
    *,
    symbol: str,
    resolution_id: str | None,
    model_id: str,
    hyper: alpha.LGBMHyperparams,
    seed: int,
    feature_ids: tuple[str, ...],
    device_type: str,
    tau_policy: str,
    calib_split_mode: str,
    class_balance_basis: str,
    calib_weight_basis: str,
    k_replicas: int,
    headline: float,
) -> backtest_lite.PermutationNullResult:
    """ADR-005 §13.13 (item 5 de §13.17) -- `k_replicas` réplicas da
    Camada 1 sobre os MESMOS `splits`, com `label`/`ret_net` embaralhados
    (`null_permutation_seed`, herda a garantia de `fit_side_model` de
    permutar por lado e nunca vazar estrutura entre folds do CPCV). O
    `headline` real (`alpha_sharpe_headline`, já calculado pelo caller)
    é reportado como PERCENTIL contra essa distribuição, nunca como
    número absoluto -- sem isto, `1,02` de Sharpe é indistinguível, no
    artefato, do que 69 features de ruído gaussiano puro já produzem por
    construção do pipeline (medido em `§13.13`: dispara sinal a
    1,77%-1,94% do alvo, `y`/`w` REAIS).

    Só a Camada 1 recebe réplica de nulo -- a Camada 0 já É a variante-
    controle (sem constraint monotônica), não precisa de um nulo próprio
    para responder "o pipeline distingue sinal real de ruído?".

    Extraída de `run_layer1_sprint` como função própria (Idioma A, só
    que com IO -- `alpha.run_all_folds` treina de verdade) para ser
    testável sem orquestrar o resto do pipeline: quem testa o roteamento
    (`k=0` nunca chama, `k>0` chama com seeds distintos) faz isso
    chamando ESTA função com `alpha.run_all_folds`/`backtest_lite.
    backtest_by_path` stubados, não o `run_layer1_sprint` inteiro."""
    null_sharpes: list[float] = []
    for replica_i in range(k_replicas):
        # Deriva um seed distinto por réplica sem repetir nenhum
        # `seed`/`side`/`fold` já usado pelo treino real (mesma
        # disciplina de composição de `alpha._derived_seed`, cópia local
        # porque a necessidade aqui é mais simples -- só "um seed
        # diferente por índice de réplica", não combinar (fold, side,
        # propósito) como o núcleo de `alpha.py` faz).
        null_seed = (seed * 1_000_003 + (replica_i + 1) * 97) % 2_147_483_647  # noqa: magic-number
        null_folds = alpha.run_all_folds(
            df_all,
            splits,
            variant=alpha.VARIANT_CAMADA1,
            model_id=model_id,
            symbol=symbol,
            resolution_id=resolution_id,
            hyper=hyper,
            seed=seed,
            feature_ids=feature_ids,
            device_type=device_type,
            tau_policy=tau_policy,
            calib_split_mode=calib_split_mode,
            class_balance_basis=class_balance_basis,
            calib_weight_basis=calib_weight_basis,
            null_permutation_seed=null_seed,
        )
        null_by_path = backtest_lite.backtest_by_path(null_folds, df_all)
        null_sharpes.append(_mean_finite([r.sharpe_naive for r in null_by_path.values()]))
    percentile = backtest_lite.percentile_rank(headline, np.asarray(null_sharpes, dtype=np.float64))
    return backtest_lite.PermutationNullResult(
        k_replicas=k_replicas,
        headline=headline,
        null_sharpes=tuple(null_sharpes),
        headline_percentile=percentile,
    )


def _economic_gate_verdicts_by_side(
    filled_trades: pl.DataFrame,
    *,
    symbol: str,
    resolution_id: str | None,
    threshold: economic_gate.GateRow | None,
) -> dict[str, Any] | None:
    """Núcleo puro (Idioma A) -- `threshold` é resolvido pelo CALLER
    (reaproveita o `pre_trial_gate` já buscado antes do treino, não lê
    `config/min_alpha_lift_by_combo.yaml` de novo aqui: uma só leitura por
    chamada de `run_layer1_sprint`, não duas). Lê `filled_trades` (pooled
    já materializado nesta rodada, MESMA convenção de `decomp_pooled`/
    §16.6: cada bar do dataset aparece uma vez por caminho de backtest do
    CPCV, não é amostra independente -- ver `PathDispersionStats` em
    `backtest_lite.py`) e compara o `p_tp` ACHIEVED por lado (`side_hat`,
    a aposta do MODELO, não o `side` do label) contra `threshold`.

    **Ressalva de proveniência do erro-padrão, explícita (não escondida,
    mesma disciplina do `caveat_anualizacao` do bloco DSR acima):**
    `n_candidate` é a contagem POOLED sobre os 5 caminhos de backtest, não
    um N de trades independentes -- `evaluate_economic_gate` usa esse N
    cru na fórmula binomial de `candidate_p_tp_stderr`, então o erro-padrão
    aqui SUBESTIMA a incerteza real (o N efetivo, ponderado por
    `uniqueness`, é menor). Como este campo é soft-flag/só-log (nunca
    decide nada), o impacto é limitado -- mas não confundir
    `distinguishable=True` aqui com o mesmo rigor de `is_distinguishable`
    em `src.analysis.economic_gate` (que usa erro pré-calculado sobre a
    amostra medida do S1).

    `None` (o dict inteiro) se `resolution_id` ou `threshold` é `None` --
    a tabela é por grade R1/R2/R3, não existe pra grade de relógio legada
    nem pra uma célula sem entrada em `min_alpha_lift_by_combo.yaml` (o
    log de "sem tabela" já aconteceu no ponto pré-treino, que resolveu
    `threshold`; não repetido aqui). Por lado, `None` sem nenhum trade
    preenchido daquele lado -- nunca inventa. `EconomicGateError` de
    `evaluate_economic_gate` (ex. `candidate_p_tp==0.0`, zero TP naquele
    lado) vira `None` com log de aviso, nunca interrompe o treino real --
    este parâmetro só informa."""
    if resolution_id is None or threshold is None:
        return None
    out: dict[str, Any] = {}
    for side_str, side_int in (("long", 1), ("short", -1)):
        side_trades = filled_trades.filter(pl.col("side_hat") == side_int)
        n_candidate = side_trades.height
        if n_candidate == 0:
            out[side_str] = None
            continue
        n_tp = side_trades.filter(pl.col("barrier_hit") == "TP").height
        candidate_p_tp = n_tp / n_candidate  # noqa: unguarded-ratio -- n_candidate==0 guardado (continue) acima
        try:
            verdict = economic_gate.evaluate_economic_gate(
                candidate_p_tp, n_candidate, threshold, side=side_str
            )
        except economic_gate.EconomicGateError as exc:
            logger.warning(
                "models.pipeline.economic_gate_post_trial_erro",
                symbol=symbol,
                resolution_id=resolution_id,
                side=side_str,
                error=str(exc),
            )
            out[side_str] = None
            continue
        out[side_str] = asdict(verdict)
        logger.info(
            "models.pipeline.economic_gate_post_trial",
            symbol=symbol,
            resolution_id=resolution_id,
            side=side_str,
            candidate_p_tp=candidate_p_tp,
            n_candidate=n_candidate,
            passes=verdict.passes,
            distinguishable=verdict.distinguishable,
        )
    return out


def run_layer1_sprint(
    *,
    symbol: str = SYMBOL,
    tf: str | None = None,
    resolution_id: str | None = None,
    vol_estimator_id: str | None = None,
    t0_start: str | None = None,
    t0_end: str | None = None,
    model_id_camada1: str = MODEL_ID_CAMADA1,
    model_id_camada0: str = MODEL_ID_CAMADA0,
    report_path: Path | None = None,
    device_type: str = "cpu",
    # `AG-272` (2026-08-26) -- DEFAULTS REVISTOS ANTES DO RETREINO EM R1.
    # Enquanto nao havia retreino a horizonte, manter os tres no caminho
    # legado era preservacao bit-exata e estava certo. Num retreino deixa de
    # ser conservador e passa a ser a escolha errada: o artefato novo herdaria
    # defeitos que ja tem correcao pronta no repo.
    #
    # `tau_policy` NAO foi flipado, e a razao esta medida: `AG-251` executou a
    # verificacao que `AG-210` exigia antes do flip e achou 2x de dispersao
    # sob a politica nova, com o `bars_per_year` corrigido. Manter o legado
    # aqui e seguir a medicao, nao a inercia.
    tau_policy: str = alpha.TAU_POLICY_LEGACY_PER_SIDE,
    # `calib_split_mode` -- B08 era cumprido na LETRA (o sub-split existia) e
    # violado no ESPIRITO: `train_test_split` aleatorio sobre labels de triple
    # barrier poe no conjunto de calibracao vizinhos que compartilham
    # `[t0, t1]` com o treino. `_temporal_purged_calib_split` corta por tempo
    # com purge por `t1`.
    calib_split_mode: str = alpha.CALIB_SPLIT_TEMPORAL_PURGED,
    # `class_balance_basis` -- inconsistencia interna MEDIDA: a perda pondera
    # cada amostra por `sample_weight` (unicidade, §3.5/B10) mas o
    # `scale_pos_weight` era contado por CABECA. Medido em R1 pos-relabel:
    # P(y=1) por contagem 0,4967 contra 0,4323 por massa de peso em
    # BTCUSDT/long -- `scale_pos_weight` 1,0132 contra 1,3134, 30% de
    # divergencia. A classe positiva ficava sub-ponderada em ~23%.
    class_balance_basis: str = alpha.CLASS_BALANCE_WEIGHT,
    # `calib_weight_basis` -- AG-312 / ADR-005 §13.10, item 4 de §13.17.
    # DECISAO DO MANAGER (2026-08-26), opcao (b): o calibrador isotonico
    # pondera so por `uniqueness`, nao por `uniqueness * |ret_net|`. Sob o
    # peso legado a saida do calibrador estimava 0,4323 quando `P(TP)` real
    # e 0,4967 -- vies de -13,0%, da MESMA ORDEM do lift que a regua exige
    # (+7,6% a +15,1%). Sob `uniqueness` o vies medido cai para [-0,0012,
    # +0,0030] em 5 celulas. A perda do LightGBM segue com o peso completo
    # (B10/§3.5 intactos) -- muda so o calibrador.
    calib_weight_basis: str = alpha.CALIB_WEIGHT_UNIQUENESS,
    dsr_n_trials: int | None = None,
    feature_ids: tuple[str, ...] | None = None,
    hyper: alpha.LGBMHyperparams | None = None,
    # `AG-141`/item 10 de `ADR-005 §13.17` -- opt-in, default `False`
    # preserva bit-exato todo call site/teste existente (nenhum grava
    # bundle de modelo hoje). Ver `write_all_fold_model_bundles`: gate
    # adicional `path_tf is not None` (mesmo sentinela de `dest_dir_diag_
    # c1`/`c0` abaixo) -- caminho legado plano nunca persiste bundle,
    # mesmo se `True`, porque `symbol`/`resolution_id` não bastam pra
    # nomear a partição sem colisão sob a grade de tempo legada.
    persist_model_bundles: bool = False,
    # ADR-005 §13.13 (item 5 de §13.17) -- opt-in, default `0` preserva
    # bit-exato todo call site/teste existente (nenhum treina réplica de
    # nulo hoje). `k > 0` custa `k` treinos completos da Camada 1 (mesmo
    # custo de `run_all_folds` sobre os mesmos splits) -- zero
    # `N_lifetime` novo (é nulo de permutação, não busca de hiperparâmetro).
    permutation_null_replicas: int = 0,
    # AG-260 ponto (b) / `/redesign_workflow` 2026-08-27 -- orquestrador de
    # trial SOFT-FLAG (só LOGA/REPORTA, `report["economic_gate"]` -- nunca
    # bloqueia nem pula treino; tornar isto BINDING continua decisão
    # FUTURA do Manager, essa parte NÃO promovida). **[Default promovido a
    # `True` 2026-08-27, decisão do Manager -- CLAUDE.md "Diretrizes de
    # comportamento"]** `False` reproduz o comportamento anterior (nenhum
    # log novo, nenhuma chave nova no report).
    use_economic_gate: bool = True,
    # 2026-08-27 (handoff de `src/models/`, item 3) -- diagnóstico opt-in,
    # mesmo padrão de `persist_model_bundles` acima. `True` roda as 4
    # funções de refinamento estatístico do B1 (já implementadas/testadas,
    # órfãs até aqui) e escreve `report["baselines"]["b1_refinement"]` --
    # NÃO substitui `report["baselines"]["b1_random_entry"]` (schema
    # inalterado, decisão de substituir é maior/separada, do Manager).
    # Custo medido: ~19s (histórico, n_seeds=1000, dataset menor) contra
    # ~700-960s de runtime total por combo -- baixo o bastante pra não
    # precisar de flag de performance própria. **[Default promovido a
    # `True` 2026-08-27, decisão do Manager]** `False` reproduz o
    # comportamento anterior.
    run_b1_refinement: bool = True,
    # AG-368 (2026-08-27) -- achado ao vivo rodando medição comparativa
    # (`src/analysis/ag362_incremental_value_report.py`): 2 designs
    # diferentes (`use_hyperparams_by_combo` on/off) podem resolver pro
    # MESMO `hyper` efetivo numa célula sem calibração própria em
    # `config/alpha_hyperparams_by_combo.yaml` (5 das 15) -- mesmo
    # `config_hash`, `ArtifactExistsError` na 2ª escrita. `write_artifact`
    # (`src/io/artifact.py`) já resolve exatamente isso via `scratch=True`
    # ("iteração exploratória", ADR-001) -- só não estava threaded até
    # aqui. Default `False` preserva bit-exato todo call site/teste
    # existente (predições de produção continuam imutáveis).
    scratch: bool = False,
) -> dict[str, Any]:
    """`device_type` (D-18, `docs/alpha_model_design_doc_2026-08-22.md`).
    **[CORRIGIDO 2026-08-24, AG-201]** default era `"cuda"` -- GPU
    obrigatória em produção é decisão real do Manager, mas `AG-201`
    confirmou bloqueio ESTRUTURAL, não contornável: LightGBM 4.7.0 exige
    NCCL incondicionalmente sob `USE_CUDA=ON` (`CMakeLists.txt:243`), e
    NCCL não tem build nativo Windows -- toda chamada real desta sessão já
    precisava passar `device_type="cpu"` manualmente pra não quebrar com
    `LightGBMError`. Default agora `"cpu"` NESTE AMBIENTE (Windows nativo)
    -- se o treino de produção migrar pra um ambiente Linux/cloud onde
    LightGBM+CUDA+NCCL de fato compila, este default precisa ser
    revisitado por decisão explícita do Manager, não reflipado por
    engano. Passe `device_type="cuda"` explicitamente se/quando essa
    migração acontecer.

    `t0_start`/`t0_end`/`model_id_camada{0,1}`/`report_path` default para
    o comportamento anterior byte a byte (janela cheia, `MODEL_ID_CAMADA1`/
    `MODEL_ID_CAMADA0`, `experiments/alpha_layer1_report.json`). Passados
    explicitamente, permitem reprocessar um subintervalo (PRD_V4_1.md T0.5)
    SEM sobrescrever os artefatos já gravados da rodada de janela cheia.

    `tf` (PRD_V4_1.md T0.3, §3.1, AG-006) — sentinela `None`, NÃO `"15m"`:

    - `tf=None` (default, o que TODO chamador/teste existente faz hoje —
      nunca ninguém passou este argumento porque ele não existia antes
      desta mudança): comportamento bit-exato de antes, sem exceção.
      `write_predictions_atomic` é chamado SEM `dest_dir`, gravando no
      caminho legado plano `PREDICTIONS_OUTPUT_DIR/alpha/{model_id}`; `tf`
      não é validado (`step_ms` não é chamado).
    - `tf="15m"`/`"30m"`/... explícito: grava no layout chaveado
      `_paths.predictions_symbol_tf_dir(symbol, model_id, tf=tf)` e valida
      `tf` via `step_ms(tf)` ANTES de qualquer trabalho caro
      (`build_modeling_frame`, CPCV, treino XGBoost) — mesma disciplina de
      `CPCVConfig.__post_init__` (`src/validation/cpcv.py`): falhar cedo e
      alto em vez de deixar um `tf` desconhecido virar silenciosamente um
      nome de diretório qualquer (`predictions_symbol_tf_dir` não valida
      `tf` sozinho).

    Por que o sentinela e não `tf: str = "15m"` com propagação incondicional
    (a primeira versão desta mudança fazia isso, revertido em code review):
    `predictions_symbol_tf_dir(symbol, model_id, tf="15m")` produz um
    CAMINHO DIFERENTE do fallback `dest_dir=None` legado, mesmo sendo o
    "mesmo timeframe" — não é o mesmo lugar no disco. Migrar o destino de
    escrita do default silenciosamente orfanaria leitores de produção reais
    que leem `PREDICTIONS_OUTPUT_DIR/alpha/{model_id}/predictions.parquet`
    direto, sem noção de `symbol`/`tf` (grep `load_predictions|
    PREDICTIONS_OUTPUT_DIR` em `src/`, 2026-08-13):
    `src/backtest/fill_reconciliation.py:126-127`,
    `src/analysis/faixa1_5_prerequisites.py:105-106`,
    `src/analysis/faixa1_6_reconciliation.py:711,716,1066` (via
    `f15.load_predictions`), `src/analysis/faixa1_7_edge_or_beta.py:563`,
    `src/analysis/faixa2_caminho_b.py:1019,1118,1325`,
    `src/analysis/faixa2_vol_accelerator_test.py:84,290,400`,
    `src/analysis/calibration_diagnostics.py:905-910`. Nenhum desses
    módulos erraria de forma visível — os arquivos antigos no caminho
    legado continuam existindo, então eles silenciosamente leriam artefato
    cada vez mais desatualizado, sem nenhum erro. Migrar esses 7 leitores
    pro layout chaveado é um trabalho coordenado à parte, fora do escopo
    desta mudança.

    **Bug real corrigido aqui (2026-08-17, Fase 4 da migração
    Parkinson+dollar-bar, achado independente de 2 rodadas de investigação
    — `tf` era validado acima mas NUNCA repassado adiante):** antes desta
    correção, `build_modeling_frame`/`generate_splits` eram chamados sem
    `tf`/`config`/`symbol` — mesmo com `tf="30m"` explícito e validado,
    labels/features/regime/CPCV caíam sempre no default `"15m"`
    silenciosamente. Sem efeito prático até agora porque nenhum caller
    real passava `tf` != `None`/`"15m"` (só o layout de PATH usava `tf`);
    passa a importar de verdade a partir desta migração, que depende de
    `generate_splits` aceitar `symbol` (Fase 0, Bloqueador 2) pra validar
    grade dollar-bar.

    `vol_estimator_id` **[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27,
    handoff do Manager]** — `None` já NÃO preserva mais ATRWilder
    bit-exato aqui: resolve pra `constants.yaml::canonical_volatility_
    estimator` (hoje `parkinson_w20`, decisão do Manager em
    2026-08-17/2026-08-27). Achado real que motivou a correção: a
    constante virou registro de decisão em `constants.yaml`, mas nenhum
    código a lia por nome — rodar `--all-combinations` sem `--vol-
    estimator-id parkinson_w20` explícito treinava com ATRWilder legado,
    silenciosamente, revertendo a decisão de flip do mesmo commit que a
    declarou (mesma classe de bug de `AG-272`, achada numa varredura
    imediatamente posterior ao flip). O núcleo que de fato escolhe o
    estimador (`features.build`, seleção de `c01_atr_20` vs.
    `c01_atr_20_parkinson`) continua com `None`→ATRWilder intocado —
    aqui na CASCA de produção é onde `None` deixa de significar "não
    escolhido" e passa a significar "use o que `constants.yaml` decidiu",
    resolvido em `vol_estimator_id_effective` antes de `build_modeling_
    frame` ser chamado; os ~20 call sites de pesquisa/validação que
    chamam `build_modeling_frame`/o núcleo direto continuam recebendo
    ATRWilder sob `None`, sem mudança de comportamento pra eles. Passar
    `vol_estimator_id` explícito (produção ou pesquisa) sempre vence,
    igual antes.

    `resolution_id` (Fase 4, AG-030/036/065) —
    `resolution_id=None` (default) preserva bit-exato: `tf_effective =
    tf ou "15m"`, `grade_id = tf_effective`, mesmo caminho de sempre.
    `resolution_id="R1"` propaga a MESMA grade pra `build_modeling_frame`
    (que por sua vez propaga pra labels/features/regime, Fase 4 item 15) E
    pro `CPCVConfig.grade_id` do CPCV — um único parâmetro de grade, não
    dois que pudessem divergir. `path_tf` (destino em disco de predictions/
    diagnostics) usa `resolution_id` quando setado, MESMO que `tf` continue
    `None` — nunca cai no caminho legado plano que colidiria com os 5
    `model_id` de produção já treinados sob grade de tempo (mesma guarda
    de path-collision de `labels_symbol_tf_dir`, Fase 1).

    `feature_ids`/`hyper` (2026-08-25, `AG-207`/`AG-234`/`ADR-003`) —
    sentinela `None` em ambos preserva bit-exato o comportamento de
    sempre (`T1_FEATURE_IDS`, `LGBMHyperparams.from_constants()`) pra
    todo call site/teste existente. `feature_ids`, quando não-`None`, é o
    vetor de treino COMPLETO desejado — em produção, `T1_FEATURE_IDS +
    features_build.SUPPORT_FEATURE_IDS` (69), ADITIVO ("T2 promove a T1"
    é literal: T2 ganha o status de T1, T1 não sai do vetor — `AG-234`
    corrige a leitura substitutiva que a campanha de pesquisa T2→T1
    (Fase 1/Fase 2/ADR-002/ADR-003, `run_all_folds`/`build_design_
    matrix`) sempre usou, mas que era metodologia de PESQUISA
    exploratória, nunca mandato de produção). Internamente,
    `extra_feature_ids` pra `build_modeling_frame` é calculado por
    DIFERENÇA (`feature_ids` menos o que já está em `T1_FEATURE_IDS`,
    que `mf.data` sempre inclui) — o chamador passa o vetor completo que
    quer treinar, não precisa saber dessa distinção interna.

    `use_economic_gate` (AG-260 ponto (b), `/redesign_workflow` 2026-08-27)
    -- orquestrador de trial pro gate econômico (`src.models.economic_
    gate`). Default `False` preserva bit-exato: nenhum log novo, nenhuma
    chave nova em `report`. `True` faz esta função LOGAR (nunca bloquear)
    duas vezes: antes do treino, o `required_lift`/`breakeven_wr` exigido
    pra esta célula (`(symbol, resolution_id)`, se existir em `config/
    min_alpha_lift_by_combo.yaml`); depois, `report["economic_gate"]` com
    o veredito por lado (`long`/`short`) comparando o `p_tp` ACHIEVED
    pooled desta rodada (mesma convenção de `decomp_pooled`/§16.6, ver
    `_economic_gate_verdicts_by_side`) contra aquele limiar, e `report[
    "n_lifetime_suggested_delta"]` (sempre `1` quando alcançado -- esta
    função sempre treina de verdade se chegar até aqui, nunca escreve em
    `audit/n_lifetime.yaml` sozinha). Sem tabela pra esta célula, ou sem
    trade preenchido de um lado, ou `resolution_id=None` (a tabela é por
    grade R1/R2/R3, não existe pra grade de relógio legada): `None`,
    nunca inventado. Tornar isto BINDING (bloquear um trial de verdade) é
    decisão FUTURA do Manager, não tomada aqui -- este parâmetro só
    informa."""
    if tf is not None:
        step_ms(tf)  # UnsupportedTimeframeError cedo — antes do trabalho caro abaixo
    # `resolution_id`/`tf` sem bar_source de Feature/Regime Engine mapeado:
    # validado dentro de `ds.build_modeling_frame` (achado de auditoria,
    # 2026-08-17) -- NÃO duplicado aqui de propósito. Um gate próprio aqui
    # checando contra `CALIBRATION_TF_BY_RESOLUTION` (={R1,R2,R3}, mais
    # largo que `dataset._BAR_SOURCE_BY_RESOLUTION`={R1}) permitiria
    # resolution_id="R2"/"R3" passar por ESTE gate com mensagem de erro
    # que lista {R1,R2,R3} como "esperado", pra só falhar depois dentro de
    # build_modeling_frame com mensagem contraditória ("R2/R3 são só
    # pesquisa") -- exatamente o padrão "valide largo aqui, use estreito
    # ali" já catalogado várias vezes neste repo (AG-004/005/017/027).
    # Nenhum trabalho caro acontece entre aqui e a chamada de
    # build_modeling_frame abaixo, então não há custo real de fail-fast
    # perdido ao não duplicar o check.
    t_start = time.time()
    tf_effective = tf if tf is not None else "15m"
    grade_id = resolution_id if resolution_id is not None else tf_effective
    path_tf = resolution_id if resolution_id is not None else tf
    # `feature_ids` (quando setado) é o vetor de treino COMPLETO desejado
    # (ex. T1_FEATURE_IDS + SUPPORT_FEATURE_IDS, 69 -- AG-207/AG-234: "T2
    # promove a T1" é ADITIVO, T1 nunca sai do vetor de treino, correção
    # sobre a convenção da campanha de pesquisa T2->T1, que era
    # deliberadamente substitutiva e nunca foi mandato de produção).
    # `build_modeling_frame` já inclui T1 sempre -- `extra_feature_ids`
    # só pode conter o que FALTA (T1 causaria `ValueError` de coluna
    # duplicada), calculado aqui por diferença de conjunto.
    extra_feature_ids = (
        tuple(f for f in feature_ids if f not in features_build.T1_FEATURE_IDS)
        if feature_ids is not None
        else ()
    )
    # AG-371 (2026-08-28) -- resolução extraída pra `features_build.
    # resolve_feature_ids`, única fonte de verdade: `run_layer1_sprint_
    # all_combinations` precisa do vetor JÁ RESOLVIDO antes de chamar esta
    # função (pra validar `hyperparams_by_combo` contra o vetor certo,
    # nunca contra um `feature_ids=None` cru) -- duplicar esta linha lá
    # seria a mesma classe de descompasso que causou o AG-371 original.
    feature_ids_effective = features_build.resolve_feature_ids(feature_ids)
    # Achado real 2026-08-27 (handoff de src/models/, AG-296/AG-297/item 3)
    # -- fail-fast ANTES de build_modeling_frame (trabalho caro de IO),
    # mesmo espírito de step_ms(tf) acima: uma feature com
    # defeito_construcao=true (§14.3, ex. E11f_oi_change_1d) já entrou
    # num LightGBM real sem gate nenhum (experiments/alpha_layer1_
    # report_BTCUSDT_R1_ag207_k62.json). Ver docstring de
    # assert_no_defeito_construcao_in_active_set.
    features_build.assert_no_defeito_construcao_in_active_set(feature_ids_effective)
    # `vol_estimator_id_effective` -- [PROMOVIDO A DEFAULT DE PRODUÇÃO
    # 2026-08-27] `None` aqui na CASCA de produção resolve pra
    # `constants.yaml::canonical_volatility_estimator`, não mais pro
    # ATRWilder legado do núcleo (ver docstring acima). `build_modeling_
    # frame` recebe sempre um valor explícito a partir daqui.
    vol_estimator_id_effective = (
        vol_estimator_id
        if vol_estimator_id is not None
        else str(load_constant("canonical_volatility_estimator"))
    )
    mf = ds.build_modeling_frame(
        symbol=symbol,
        tf=tf_effective,
        resolution_id=resolution_id,
        vol_estimator_id=vol_estimator_id_effective,
        t0_start=t0_start,
        t0_end=t0_end,
        extra_feature_ids=extra_feature_ids,
    )
    # AG-032 item 8 (Fix A, 2026-08-21) -- max_feature_lookback_ms cobre o
    # "componente 96" (janela de lookback de feature de treino alcançando
    # pra trás através de g_end_effective, ver docstring de src.validation.
    # cpcv) usando o mesmo helper compartilhado que src.validation.leakage.
    # run_all_leakage_tests (evita a formula duplicar/divergir, AG-009).
    # Levanta features_build.ExpandingFeatureLookbackError se o conjunto
    # ativo (T1_FEATURE_IDS) tiver feature com lookback_bars='expanding'
    # no registry -- hoje DISPARA (3 features expanding conhecidas); ver
    # docstring de assert_no_expanding_lookback_in_active_set.
    # D-02 (AG-159, docs/regime_feature_engine_design_doc_2026-08-23.md
    # §3) -- resolution_id propagado pra usar bar_duration_ms correto sob
    # dollar-bar (label_prefetch_p99_bar_duration_ms), não step_ms(tf).
    # leakage.run_all_leakage_tests precisa do MESMO resolution_id -- ver
    # comentário equivalente lá, os dois call sites mudam juntos.
    # ADR-005 §13 v2 §13.1 / AG-296 -- `feature_ids_effective` (calculado
    # acima) passa a ser passado de verdade. Antes caia no default
    # `T1_FEATURE_IDS` (7) por OMISSAO, enquanto `run_all_folds` treinava
    # sobre 69: o purge era dimensionado para um decimo do vetor.
    max_feature_lookback_ms = features_build.compute_max_feature_lookback_ms(
        tf_effective, feature_ids_effective, resolution_id=resolution_id
    )
    cpcv_config = cpcv.CPCVConfig.from_constants(
        tf=tf_effective, grade_id=grade_id, max_feature_lookback_ms=max_feature_lookback_ms
    )
    cpcv_result = cpcv.generate_splits(mf.data, config=cpcv_config, symbol=symbol)
    splits = cpcv_result.splits
    logger.info(
        "models.pipeline.run_layer1_sprint_start",
        n_rows=mf.data.height,
        n_splits=cpcv_result.config.n_splits,
        n_backtest_paths=cpcv_result.config.n_backtest_paths,
    )

    # Resolvido uma vez aqui, reaproveitado no bloco pós-treino
    # (`_economic_gate_verdicts_by_side`, mais abaixo) -- nunca uma
    # segunda leitura de `config/min_alpha_lift_by_combo.yaml` pra mesma
    # chamada de `run_layer1_sprint`.
    pre_trial_gate: economic_gate.GateRow | None = None
    if use_economic_gate and resolution_id is not None:
        pre_trial_gate = economic_gate.lookup_pre_trial_gate(symbol, resolution_id)
        if pre_trial_gate is None:
            logger.info(
                "models.pipeline.economic_gate_pre_trial_sem_tabela",
                symbol=symbol,
                resolution_id=resolution_id,
            )
        else:
            logger.info(
                "models.pipeline.economic_gate_pre_trial",
                symbol=symbol,
                resolution_id=resolution_id,
                side_threshold=pre_trial_gate.side,
                required_lift=pre_trial_gate.required_lift,
                breakeven_wr=pre_trial_gate.breakeven_wr,
                p_tp_base=pre_trial_gate.p_tp,
            )

    hyper_explicit = hyper is not None
    hyper = hyper if hyper is not None else alpha.LGBMHyperparams.from_constants()
    seed = int(load_constant("alpha_random_seed"))

    camada1_folds = alpha.run_all_folds(
        mf.data,
        splits,
        variant=alpha.VARIANT_CAMADA1,
        model_id=model_id_camada1,
        symbol=symbol,
        resolution_id=resolution_id,
        hyper=hyper,
        seed=seed,
        feature_ids=feature_ids_effective,
        device_type=device_type,
        tau_policy=tau_policy,
        calib_split_mode=calib_split_mode,
        class_balance_basis=class_balance_basis,
        calib_weight_basis=calib_weight_basis,
    )
    camada0_folds = alpha.run_all_folds(
        mf.data,
        splits,
        variant=alpha.VARIANT_CAMADA0,
        model_id=model_id_camada0,
        symbol=symbol,
        resolution_id=resolution_id,
        hyper=hyper,
        seed=seed,
        feature_ids=feature_ids_effective,
        device_type=device_type,
        tau_policy=tau_policy,
        calib_split_mode=calib_split_mode,
        class_balance_basis=class_balance_basis,
        calib_weight_basis=calib_weight_basis,
    )

    # --- diagnóstico por fold x lado (task A1 do CLAUDE.md) — persiste o
    # que antes só existia em memória dentro de FoldResult/SideModelResult
    # e nunca saía do processo (gain_by_column bruto, shares normalizados,
    # HHI, n_trees, tamanho de amostra). Escrito para as DUAS variantes,
    # cada uma no seu próprio model_id, antes de qualquer agregação em
    # médias no relatório final.
    # `tf=None`/`resolution_id=None` (default): SEM dest_dir -> caminho
    # legado plano `MODELS_DIR/{model_id}/diagnostics/`, bit-exato (AG-013
    # preserva os ~30 arquivos já commitados). `tf` explícito OU
    # `resolution_id` explícito: layout chaveado por symbol/`path_tf`
    # (AG-016) — `path_tf` usa `resolution_id` quando setado, MESMO se
    # `tf` continuar `None` (Fase 4, 2026-08-17): nunca deixa uma rodada
    # dollar-bar cair no caminho legado plano que colidiria com os 5
    # `model_id` de produção já treinados sob grade de tempo. Mesmo
    # sentinela de `dest_dir_c1`/`dest_dir_c0` usado abaixo para
    # `write_predictions_atomic`.
    dest_dir_diag_c1 = (
        models_diagnostics_symbol_tf_dir(
            symbol, model_id_camada1, tf=tf_effective, resolution_id=resolution_id
        )
        if path_tf is not None
        else None
    )
    dest_dir_diag_c0 = (
        models_diagnostics_symbol_tf_dir(
            symbol, model_id_camada0, tf=tf_effective, resolution_id=resolution_id
        )
        if path_tf is not None
        else None
    )
    write_all_fold_diagnostics(
        camada1_folds, model_id=model_id_camada1, hyper=hyper, dest_dir=dest_dir_diag_c1
    )
    write_all_fold_diagnostics(
        camada0_folds, model_id=model_id_camada0, hyper=hyper, dest_dir=dest_dir_diag_c0
    )

    # `AG-141`/item 10 de `ADR-005 §13.17` -- opt-in (`persist_model_
    # bundles`), mesmo gate `path_tf is not None` dos dois blocos de
    # diagnóstico acima: o caminho legado plano não persiste bundle
    # (`symbol`/`resolution_id` não bastam pra nomear a partição sem
    # colisão sob a grade de tempo legada, mesma razão de `dest_dir_diag_
    # c1`/`c0`). `grade_id` (já resolvido acima) é o `resolution_id` que
    # `write_model_bundle` grava -- `resolution_id` explícito quando a
    # grade é dollar-bar, `tf_effective` ("15m") quando é a legada com
    # `tf` explícito.
    if persist_model_bundles and path_tf is not None:
        write_all_fold_model_bundles(
            camada1_folds,
            symbol=symbol,
            resolution_id=grade_id,
            hyper=hyper,
            feature_ids=feature_ids_effective,
            purge_ms_effective=max_feature_lookback_ms,
        )
        write_all_fold_model_bundles(
            camada0_folds,
            symbol=symbol,
            resolution_id=grade_id,
            hyper=hyper,
            feature_ids=feature_ids_effective,
            purge_ms_effective=max_feature_lookback_ms,
        )

    preds_c1 = alpha.assemble_predictions_table(camada1_folds)
    preds_c0 = alpha.assemble_predictions_table(camada0_folds)
    # `tf=None`/`resolution_id=None` (default): SEM dest_dir -> caminho
    # legado plano, bit-exato com o comportamento anterior a esta mudança
    # (ver docstring da função — 7 leitores de produção reais ainda
    # dependem disso). `tf`/`resolution_id` explícito: layout chaveado por
    # symbol/`path_tf` (mesma guarda contra colisão do bloco acima).
    if resolution_id is not None:
        # D-06 (docs/alpha_model_design_doc_2026-08-22.md, fecha AG-154) --
        # grade dollar-bar grava via write_artifact (schema versionado +
        # manifest, ADR-001) em vez do writer ad-hoc. Escopo deliberadamente
        # ESTREITO (achado desta rodada, 2026-08-23, não a leitura literal
        # do docstring de write_predictions_versioned abaixo):
        # write_predictions_versioned exige resolution_id: str (não
        # opcional) -- só pode servir ESTE ramo, nunca o legado (tf/
        # resolution_id=None) que os 2 consumidores reais incondicionais
        # (src/backtest/fill_reconciliation.py::load_predictions,
        # src/analysis/calibration_diagnostics.py) leem. Esses 2 nem aceitam
        # symbol/resolution_id como parâmetro -- são cegos ao multi-
        # resolução com QUALQUER writer, sempre foram -- esta troca não os
        # afeta (nunca leram este ramo). Caminho legado abaixo (`else`)
        # continua intocado, mesmo writer de sempre. Dar a esses 2
        # consumidores capacidade de ler o multi-resolução é trabalho
        # aditivo separado, não pré-requisito de correção desta troca.
        # AG-207/ADR-003 (2026-08-25) -- `config_hash` (src.io.artifact.
        # write_artifact) precisa capturar a config de treino do PRÓPRIO
        # Alpha (feature_ids/hyper), não só `variant` -- senão um retreino
        # real sob `SUPPORT_FEATURE_IDS`/hiperparâmetro por combo colide no
        # MESMO caminho de artefato do treino legado (T1/hiperparâmetro
        # global) e `ArtifactExistsError` bloqueia a escrita (medido: smoke
        # test real, BTCUSDT/R3, achado ao integrar). Mesma disciplina já
        # usada em `LabelConfig.config_hash`/`AG-140`/B15 -- todo campo que
        # muda a lógica de geração entra no hash. `feature_ids`/`hyper_
        # explicit` (sentinelas `None`/`False`) preservam bit-exato
        # `config={"variant": ...}` -- e portanto o MESMO `config_hash` dos
        # 15 artefatos já persistidos -- pra todo caller que não passa os
        # 2 parâmetros novos.
        #
        # AG-371-ADDENDUM-5/10 (2026-08-28) -- achado colateral da mesma
        # disciplina: `tau_policy`/`calib_split_mode`/`class_balance_
        # basis`/`calib_weight_basis` mudam calibração/peso/tau de fato
        # (afetam `predictions.parquet`), mas NUNCA entravam no hash, em
        # NENHUMA circunstância -- diferente de `feature_ids`/`hyper`, os
        # 4 não têm sentinela `None`/opt-in (são sempre uma string
        # concreta, `run_layer1_sprint` já os resolve com default antes
        # daqui), então entram SEMPRE, sem gate condicional -- não existe
        # "não especificado" pra eles pra preservar bit-exato. Efeito
        # colateral aceito e esperado: todo config_hash writeable a partir
        # daqui muda em relação aos artefatos já persistidos (mesmo pra
        # quem roda com os defaults de sempre) -- é a MESMA disciplina de
        # `schema_version` em `compute_config_hash` (V-08: mudança de
        # schema nunca reusa artefato antigo em silêncio), aplicada aqui
        # como mudança de CONTEÚDO do dict de config, não de schema_
        # version formal (o schema do parquet em si não mudou).
        alpha_train_config_extra: dict[str, Any] = {
            "tau_policy": tau_policy,
            "calib_split_mode": calib_split_mode,
            "class_balance_basis": class_balance_basis,
            "calib_weight_basis": calib_weight_basis,
        }
        if feature_ids is not None:
            alpha_train_config_extra["feature_ids"] = sorted(feature_ids)
        if hyper_explicit:
            alpha_train_config_extra["hyper"] = asdict(hyper)
        try:
            write_predictions_versioned(
                preds_c1,
                root=ARTIFACT_ROOT,
                symbol=symbol,
                resolution_id=resolution_id,
                model_id=model_id_camada1,
                config={"variant": alpha.VARIANT_CAMADA1, **alpha_train_config_extra},
                scratch=scratch,
            )
        except io_artifact.ArtifactExistsError:
            # AG-371-ADDENDUM-8 (2026-08-28) -- Camada1 não muda com a
            # promoção de `CAMADA0_CONSTRAINED_FEATURES` (só Camada0 é
            # afetada); pra célula onde a config de Camada1 já é idêntica
            # à de um retreino canônico anterior, `config_hash` bate e
            # `write_artifact` recusa por desenho (V-05, imutabilidade).
            # Mesma disciplina de confiança já usada pelo AG-368
            # (`config_hash` igual => config de treino declarada igual =>
            # mesmo artefato sob determinismo) -- não é silenciar erro,
            # é o comportamento ESPERADO quando só Camada0 precisa de
            # artefato novo. `scratch=True` nunca cai aqui (write_artifact
            # já limpa e sobrescreve antes do rename nesse modo).
            logger.info(
                "models.pipeline.camada1_artifact_ja_existe_reusado",
                symbol=symbol,
                resolution_id=resolution_id,
                detail="config de Camada1 inalterada pela promocao de "
                "CAMADA0_CONSTRAINED_FEATURES -- artefato canonico ja "
                "existente reusado, nao regravado",
            )
        write_predictions_versioned(
            preds_c0,
            root=ARTIFACT_ROOT,
            symbol=symbol,
            resolution_id=resolution_id,
            model_id=model_id_camada0,
            config={
                "variant": alpha.VARIANT_CAMADA0,
                **alpha_train_config_extra,
                # AG-371-ADDENDUM-8 (2026-08-28) -- só na config de
                # Camada0 (Camada1 acima fica intocada de propósito,
                # preserva o config_hash/artefato dela) -- entra no hash
                # pra um retreino sob a correção nunca colidir com um
                # artefato pré-correção sob o MESMO feature_ids/hyper
                # (mesma disciplina AG-207/ADR-003 documentada acima:
                # "todo campo que muda a lógica de geração entra no
                # hash"). Lista vazia é impossível hoje (`CAMADA0_
                # CONSTRAINED_FEATURES` sempre tem >=1 elemento), mas
                # `sorted()` de um frozenset garante ordem estável pro
                # hash mesmo se a lista crescer.
                "camada0_constrained_features": sorted(alpha.CAMADA0_CONSTRAINED_FEATURES),
            },
            scratch=scratch,
        )
    else:
        # tf=None (legado, caminho plano) ou tf explícito sob grade de
        # TEMPO (resolution_id continua None) -- write_predictions_versioned
        # não se aplica (exige resolution_id: str), writer ad-hoc de sempre.
        dest_dir_c1 = (
            predictions_symbol_tf_dir(
                symbol, model_id_camada1, tf=tf_effective, resolution_id=resolution_id
            )
            if path_tf is not None
            else None
        )
        dest_dir_c0 = (
            predictions_symbol_tf_dir(
                symbol, model_id_camada0, tf=tf_effective, resolution_id=resolution_id
            )
            if path_tf is not None
            else None
        )
        write_predictions_atomic(preds_c1, model_id_camada1, dest_dir=dest_dir_c1)
        write_predictions_atomic(preds_c0, model_id_camada0, dest_dir=dest_dir_c0)

    # --- backtest por caminho + critério de permanência (§5.11 adaptado) ---
    c1_by_path = backtest_lite.backtest_by_path(camada1_folds, mf.data)
    c0_by_path = backtest_lite.backtest_by_path(camada0_folds, mf.data)
    n_better, n_total = backtest_lite.permanence_count(c1_by_path, c0_by_path)
    min_paths_required = int(load_constant("alpha_layer1_permanence_min_paths"))
    # `permanence_pass` só é atribuído depois de `n_paths_significant` mais
    # abaixo (`ADR-004` §6, achado real 2026-08-27, handoff de `src/
    # models/`, item 2) -- ver `backtest_lite.permanence_pass_criterion`.

    c1_sharpes = [r.sharpe_naive for r in c1_by_path.values()]
    c0_sharpes = [r.sharpe_naive for r in c0_by_path.values()]
    alpha_sharpe_headline = _mean_finite(c1_sharpes)

    # ADR-005 §13.13 (item 5 de §13.17) -- nulo de permutação do MESMO
    # pipeline, ver docstring de `compute_permutation_null_headline`.
    permutation_null_result: backtest_lite.PermutationNullResult | None = None
    if permutation_null_replicas > 0:
        permutation_null_result = compute_permutation_null_headline(
            mf.data,
            splits,
            symbol=symbol,
            resolution_id=resolution_id,
            model_id=model_id_camada1,
            hyper=hyper,
            seed=seed,
            feature_ids=feature_ids_effective,
            device_type=device_type,
            tau_policy=tau_policy,
            calib_split_mode=calib_split_mode,
            class_balance_basis=class_balance_basis,
            calib_weight_basis=calib_weight_basis,
            k_replicas=permutation_null_replicas,
            headline=alpha_sharpe_headline,
        )
        logger.info(
            "models.pipeline.permutation_null_medido",
            k_replicas=permutation_null_replicas,
            headline=alpha_sharpe_headline,
            headline_percentile=permutation_null_result.headline_percentile,
        )

    # --- AG-214: dispersão ENTRE caminhos. Sem isto, "4 de 5 caminhos"
    # não tem escala de leitura -- toda diferença menor que sigma é ruído, e sigma
    # não era calculado em lugar nenhum. Ver `PathDispersionStats` para a
    # ressalva obrigatória: os 5 caminhos reconstroem o MESMO dataset
    # (`src.validation.cpcv`, item 3), então sigma aqui mede sensibilidade à
    # PARTIÇÃO de treino, não erro amostral do dado.
    c1_dispersion = backtest_lite.path_dispersion_stats(c1_by_path)
    c0_dispersion = backtest_lite.path_dispersion_stats(c0_by_path)

    # --- AG-220/ADR-004 Fase 0: companion do gate de permanencia acima --
    # "quantos caminhos venceram" (permanence_count) nao responde "a
    # diferenca e distinguivel de ruido". IC bootstrap por blocos sobre
    # os ret_net JA MATERIALIZADOS nesta rodada, zero retreino extra.
    permanence_significance = backtest_lite.permanence_significance_by_path(
        camada1_folds,
        camada0_folds,
        mf.data,
        splits,
        n_boot=int(load_constant("alpha_permanence_bootstrap_n_boot")),
        confidence_level=float(load_constant("alpha_permanence_bootstrap_confidence_level")),
        seed=seed,
    )
    n_paths_significant = sum(
        1 for r in permanence_significance.values() if r.zero_filled.significant
    )
    # AG-252 -- companion signal-only, magnitude correta (zero_filled dilui
    # point_estimate ~20-60x, medido em BTCUSDT/R1, ver PermanenceSignificanceResult).
    n_paths_significant_signal_only = sum(
        1 for r in permanence_significance.values() if r.signal_only.significant
    )
    # `ADR-004` §6 / achado real 2026-08-27 (handoff de `src/models/`,
    # item 2) -- `permanence_pass` passa a exigir também que a diferença
    # seja estatisticamente distinguível de ruído, não só `n_better >=
    # min_paths_required` (que sozinho repete o viés de `AG-214`: empate
    # favorece sempre manter a Camada 1). Ver docstring de `backtest_
    # lite.permanence_pass_criterion` pra definição operacional completa.
    permanence_pass = backtest_lite.permanence_pass_criterion(
        n_better=n_better,
        min_paths_required=min_paths_required,
        n_paths_significant=n_paths_significant,
    )

    # --- AG-211: ESS (Σ uniqueness) por fold x lado, agregado. O número
    # que faltava para qualquer leitura honesta do Sharpe acima: `n_rows`
    # do frame não é o `n` estatístico quando os rótulos se sobrepõem
    # (B24/§0.2 R4). Já era calculado no repo
    # (`src.labels.experiment_log.summarize_labels`) e não tinha nenhum
    # consumidor -- agora chega ao relatório onde a decisão acontece.
    ess_long = [fr.long_result.sum_uniqueness_train for fr in camada1_folds]
    ess_short = [fr.short_result.sum_uniqueness_train for fr in camada1_folds]
    n_rows_train_long = [fr.n_train_long for fr in camada1_folds]
    n_rows_train_short = [fr.n_train_short for fr in camada1_folds]

    # --- AG-212: os dois balanceamentos de classe lado a lado. A razão
    # entre eles é o desalinhamento efetivo (1,0 = alinhados).
    spw_count = [fr.long_result.scale_pos_weight_count for fr in camada1_folds] + [
        fr.short_result.scale_pos_weight_count for fr in camada1_folds
    ]
    spw_weight = [fr.long_result.scale_pos_weight_weight for fr in camada1_folds] + [
        fr.short_result.scale_pos_weight_weight for fr in camada1_folds
    ]

    # --- AG-213: concordância entre os dois alvos, medida no fold 0 (o
    # mesmo fold que o relatório já usa como amostra para
    # `monotone_constraints_example_fold0`). Diagnóstico puro -- não muda
    # nenhuma restrição, não realimenta nada.
    target_agreement: dict[str, Any] = {}
    try:
        fold0 = camada1_folds[0]
        train_bars_fold0 = mf.data[splits[fold0.fold_id].train_idx]
        for side_value, side_label in ((1, "long"), (-1, "short")):
            agreement = monotonic.screen_target_agreement(
                ds.side_subset(
                    train_bars_fold0, side=side_value, feature_ids=feature_ids_effective
                ),
                features_build.T1_FEATURE_IDS,
                side=side_value,
            )
            target_agreement[side_label] = {
                f: {
                    "constraint_ret_net": r.constraint_ret_net,
                    "constraint_tp": r.constraint_tp,
                    "mean_ic_ret_net": r.mean_ic_ret_net,
                    "mean_ic_tp": r.mean_ic_tp,
                    "agree": r.agree,
                    "forced_economic": r.forced_economic,
                }
                for f, r in agreement.items()
            }
            target_agreement[f"{side_label}_n_disagree_nao_forcadas"] = sum(
                1 for r in agreement.values() if not r.agree and not r.forced_economic
            )
    except (KeyError, ValueError) as exc:
        # Diagnóstico nunca derruba a rodada de treino -- mas a falha
        # aparece no relatório, jamais como campo silenciosamente ausente.
        logger.warning("models.pipeline.target_agreement_falhou", error=str(exc))
        target_agreement = {"erro": str(exc)}

    # --- AG-215: DSR sobre os trades reais da Camada 1. `dsr_n_trials`
    # é OBRIGATORIAMENTE explícito (default `None` = não calcula): o `N`
    # correto é `N_lifetime` auditado (`audit/n_lifetime.yaml`), decisão
    # do Manager -- inventar um número aqui produziria um DSR
    # tranquilizador e falso, que é pior que DSR nenhum.
    dsr_block: dict[str, Any] = {
        "computed": False,
        "reason": (
            "dsr_n_trials nao informado -- N_lifetime auditado e decisao do Manager "
            "(audit/n_lifetime.yaml), nunca inventado aqui (B23/AG-215)"
        ),
    }

    # --- HHI agregado (§5.8) — média por fold, camada 1 ---
    # `.value` — `ConcentrationDiagnostics.hhi`/`.max_share` viraram
    # `Metric` (`src.core.metric`, refatoração concorrente de
    # `src/models/hhi.py` fora do escopo desta task) durante esta mesma
    # rodada; `_mean_finite`/`_percentile_finite` abaixo esperam
    # `list[float]` (fazem `np.asarray(..., dtype=np.float64)`), não
    # `Metric`. Extrai o valor numérico aqui, no ponto de consumo — não
    # muda `hhi.py` (fora do escopo), só adapta o lado que já é meu.
    hhi_values_long = [fr.long_result.concentration.hhi.value for fr in camada1_folds]
    hhi_values_short = [fr.short_result.concentration.hhi.value for fr in camada1_folds]
    max_share_long = [fr.long_result.concentration.max_share.value for fr in camada1_folds]
    max_share_short = [fr.short_result.concentration.max_share.value for fr in camada1_folds]
    max_share_values = max_share_long + max_share_short
    n_over_1pct_long = [fr.long_result.concentration.n_features_over_1pct for fr in camada1_folds]
    n_over_1pct_short = [fr.short_result.concentration.n_features_over_1pct for fr in camada1_folds]
    n_features_over_1pct = n_over_1pct_long + n_over_1pct_short

    # --- HHI EFETIVO (D1/D3, CLAUDE.md) — mesmo padrão acima, mas para
    # `concentration_effective` (fatores de informação, não features cruas
    # — ver `src.models.hhi.compute_effective_concentration`). O NOMINAL
    # acima continua existindo e sendo reportado (D2: nunca substituído);
    # isto só ADICIONA a série efetiva ao lado.
    hhi_effective_values_long = [
        fr.long_result.concentration_effective.hhi_effective.value for fr in camada1_folds
    ]
    hhi_effective_values_short = [
        fr.short_result.concentration_effective.hhi_effective.value for fr in camada1_folds
    ]
    n_eff_factors_long = [
        fr.long_result.concentration_effective.n_eff_factors.value for fr in camada1_folds
    ]
    n_eff_factors_short = [
        fr.short_result.concentration_effective.n_eff_factors.value for fr in camada1_folds
    ]
    mean_hhi_nominal = _mean_finite(hhi_values_long + hhi_values_short)
    mean_hhi_effective = _mean_finite(hhi_effective_values_long + hhi_effective_values_short)

    # --- baselines nulos (§16.1) ---
    realized_c1 = backtest_lite.realize_trades(camada1_folds, mf.data)
    n_filled_c1 = realized_c1.filter(pl.col("barrier_hit") != "NOFILL").height
    sample_size_b1 = baselines.b1_sample_size(n_filled_c1, len(c1_by_path))

    b1 = baselines.run_b1_random_entry(
        mf.data, sample_size=sample_size_b1, alpha_sharpe=alpha_sharpe_headline
    )
    start_bound, end_bound = ds.date_bounds(mf.data)
    b2 = baselines.run_b2_buy_and_hold(symbol, start_bound, end_bound)
    b3 = baselines.run_b3_regime_only(mf.data)
    b4 = baselines.run_b4_feature_shuffle(
        mf.data, splits, camada1_folds, feature_ids=feature_ids_effective
    )
    b5 = baselines.run_b5_short_permanent(mf.data)
    filled_c1 = realized_c1.filter(pl.col("barrier_hit") != "NOFILL")

    # 2026-08-27 (handoff de `src/models/`, item 3) -- diagnóstico opt-in
    # complementar a `b1` acima. Achado real: `b1` compara `alpha_sharpe_
    # headline` (MÉDIA de `len(c1_by_path)` Sharpes, variância JÁ reduzida
    # por promediação) contra um nulo de sorteio ÚNICO (`run_b1_random_
    # entry`, variância de UMA amostra) -- exatamente o viés que a
    # docstring do módulo `baselines.py` (linhas 9-16) documenta e que
    # `run_b1_paired_variance_null` existe pra corrigir, mas nunca era
    # chamada. As 4 funções abaixo reusam 100% da mecânica de sorteio/
    # Sharpe já testada (`tests/unit/test_models_baselines.py`) -- nenhum
    # caminho de código novo, só orquestração.
    b1_refinement: dict[str, Any] | None = None
    if run_b1_refinement:
        path_sample_sizes = {pid: r.n_filled_trades for pid, r in c1_by_path.items()}
        path_alpha_sharpes = {pid: r.sharpe_naive for pid, r in c1_by_path.items()}
        b1_per_path = baselines.run_b1_per_path(
            mf.data,
            path_sample_sizes=path_sample_sizes,
            path_alpha_sharpes=path_alpha_sharpes,
        )
        b1_paired_variance_null = baselines.run_b1_paired_variance_null(
            mf.data,
            path_sample_sizes=list(path_sample_sizes.values()),
            alpha_sharpe=alpha_sharpe_headline,
        )
        b1_carry_stripped = baselines.run_b1_carry_stripped(mf.data, filled_c1)
        b1_side_shuffle = baselines.run_b1_side_shuffle(
            mf.data, realized_c1, alpha_sharpe=alpha_sharpe_headline
        )
        b1_refinement = {
            "per_path": {
                str(pid): _summarize_b1_result(r.b1) for pid, r in b1_per_path.items()
            },
            "paired_variance_null": {
                "n_seeds": b1_paired_variance_null.n_seeds,
                "path_sample_sizes": list(b1_paired_variance_null.path_sample_sizes),
                "alpha_sharpe": b1_paired_variance_null.alpha_sharpe,
                "percentile_of_alpha": b1_paired_variance_null.percentile,
                "null_mean": _mean_finite(list(b1_paired_variance_null.null_replicate_means)),
                "null_p50": _percentile_finite(
                    list(b1_paired_variance_null.null_replicate_means), 50.0  # noqa: magic-number
                ),
                "null_p95": _percentile_finite(
                    list(b1_paired_variance_null.null_replicate_means), 95.0  # noqa: magic-number
                ),
            },
            "carry_stripped": _summarize_b1_result(b1_carry_stripped),
            "side_shuffle": {
                "n_seeds": b1_side_shuffle.n_seeds,
                "n_signals": b1_side_shuffle.n_signals,
                "long_prob": b1_side_shuffle.long_prob,
                "side_distribution": b1_side_shuffle.side_distribution,
                "mean_sample_size": b1_side_shuffle.mean_sample_size,
                "alpha_sharpe": b1_side_shuffle.alpha_sharpe,
                "percentile_of_alpha": b1_side_shuffle.percentile,
                "null_mean": _mean_finite(list(b1_side_shuffle.null_sharpes)),
                "null_p50": _percentile_finite(list(b1_side_shuffle.null_sharpes), 50.0),  # noqa: magic-number
                "null_p95": _percentile_finite(list(b1_side_shuffle.null_sharpes), 95.0),  # noqa: magic-number
            },
        }

    # --- decomposição de PnL (§16.6) — pooled sobre as OOF de todos os 15 splits ---

    # AG-215 -- DSR sobre os trades pooled da Camada 1, se e somente se o
    # Manager informou `N_lifetime`. `compute_dsr` já existia
    # (`src.validation.dsr`, Bailey & Lopez de Prado) e era chamado APENAS
    # por `src/analysis/faixa2_dsr_and_b2_check.py` -- nunca pelo
    # relatório do treino, que reportava Sharpe cru. Com
    # `run_layer1_sprint_all_combinations` rodando 15 combinações, relatar
    # o Sharpe da melhor sem deflacionar é o erro clássico de maldição do
    # vencedor.
    if dsr_n_trials is not None and filled_c1.height >= 2:  # noqa: magic-number -- >=2 p/ desvio amostral
        _rets = filled_c1["ret_net"].to_numpy().astype(np.float64)
        _span = backtest_lite.span_seconds(filled_c1.sort("t0")["t0"])
        _, _tpy = backtest_lite.sharpe_naive(_rets, span_seconds=_span)
        _dsr = dsr_mod.compute_dsr(_rets, n_trials=dsr_n_trials, trades_per_year=_tpy)
        dsr_block = {
            "computed": True,
            **asdict(_dsr),
            "passes_conventional_threshold": dsr_mod.dsr_passes_conventional_threshold(_dsr.dsr),
            # Ressalva estrutural, não rodapé: `trades_per_year` vem de
            # `sharpe_naive`, que anualiza por `sqrt(trades/ano)` assumindo
            # trades INDEPENDENTES. Os trades deste projeto são sobrepostos
            # por construção (é o que `uniqueness` mede) -- a anualização,
            # e portanto `sr_annualized`/`sr0_annualized`, está inflada por
            # um fator não medido. A correção correta é Lo (2002), §16.5,
            # registrada como pendente. `dsr`/`sr_per_trade` (escala
            # per-trade) não dependem dessa anualização.
            "caveat_anualizacao": (
                "trades_per_year assume trades independentes; os trades sao sobrepostos "
                "(ver uniqueness/ESS). sr_annualized inflado por fator nao medido -- "
                "correcao Lo(2002)/§16.5 pendente. Leia dsr e sr_per_trade, nao o anualizado."
            ),
        }
    elif dsr_n_trials is not None:
        dsr_block = {
            "computed": False,
            "reason": f"filled_c1.height={filled_c1.height} < 2 -- sem trades para momentos",
        }

    decomp_pooled = decomposition.decompose(filled_c1)
    decomp_by_path: dict[str, Any] = {}
    for pid in sorted({fr.path_id for fr in camada1_folds}):
        path_trades = filled_c1.filter(pl.col("path_id") == pid)
        decomp_by_path[str(pid)] = asdict(decomposition.decompose(path_trades))

    elapsed_s = time.time() - t_start

    # AG-226 -- IDENTIDADE DE REGIME no proprio artefato. Medido
    # 2026-08-25: dos 112 JSON de experiments/, ZERO embutem config_hash,
    # e 67 deles carregam metrica economica derivada de labels.parquet.
    # Sem isso, depois de um relabel e impossivel distinguir por inspecao
    # qual arquivo e de qual regime -- foi exatamente o que AG-218 mostrou
    # na pratica (alpha_layer1_report.json continha XRPUSDT/R3 e foi lido
    # como "o" resultado da Camada 1). O hash vem do labels.parquet que de
    # fato alimentou esta rodada, ja verificado por build_modeling_frame.
    labels_config_hash = (
        str(mf.data["config_hash"][0])
        if "config_hash" in mf.data.columns and mf.data.height > 0
        else None
    )

    report: dict[str, Any] = {
        "schema_version": 1,
        "sprint": 8,
        "symbol": symbol,
        "tf": tf,
        "resolution_id": resolution_id,
        "labels_config_hash": labels_config_hash,
        # valor EFETIVO (pós-resolução do default promovido), não o
        # parâmetro cru -- senão o relatório mentiria "None" mesmo quando
        # Parkinson foi de fato usado.
        "vol_estimator_id": vol_estimator_id_effective,
        "model_id_camada1": model_id_camada1,
        "model_id_camada0": model_id_camada0,
        "t0_start_filter": t0_start,
        "t0_end_filter": t0_end,
        "n_rows_modeling_frame": mf.data.height,
        "n_cpcv_splits": cpcv_result.config.n_splits,
        "n_backtest_paths": cpcv_result.config.n_backtest_paths,
        "elapsed_seconds": elapsed_s,
        "layer1_vs_layer0": {
            "camada1_sharpe_by_path": {str(pid): r.sharpe_naive for pid, r in c1_by_path.items()},
            "camada0_sharpe_by_path": {str(pid): r.sharpe_naive for pid, r in c0_by_path.items()},
            "n_paths_camada1_supera_camada0": n_better,
            "n_paths_total": n_total,
            "min_paths_required": min_paths_required,
            "permanence_pass": permanence_pass,
            "camada1_sharpe_mean": alpha_sharpe_headline,
            "camada0_sharpe_mean": _mean_finite(c0_sharpes),
            # AG-214 -- sigma entre caminhos. Sem isto, `n_paths_camada1_
            # supera_camada0` não tem escala: diferença menor que sigma é
            # ruído. LEIA JUNTO com a ressalva de `PathDispersionStats`:
            # os 5 caminhos reconstroem o MESMO dataset, então sigma mede
            # sensibilidade à partição de treino, não erro amostral.
            "camada1_sharpe_dispersion": asdict(c1_dispersion),
            "camada0_sharpe_dispersion": asdict(c0_dispersion),
            "delta_sharpe_mean": alpha_sharpe_headline - _mean_finite(c0_sharpes),
            "tie_policy": backtest_lite.TIE_LEGACY_COUNTS_AS_BETTER,
            "tie_policy_caveat": (
                "n_better conta empate exato (s1 == s0) como 'Camada 1 melhor' -- vies "
                "aponta sempre para manter a Camada 1 (o desfecho que custa mais "
                "N_lifetime). RESOLVIDO 2026-08-27 (ADR-004 Sec6, handoff de src/models/, "
                "item 2): a alternativa de margin escalar (TIE_REQUIRES_MARGIN) foi "
                "aposentada sem calibracao nova (B23) -- permanence_pass agora exige "
                "TAMBEM n_paths_significant >= min_paths_required (ver permanence_pass_"
                "criterio abaixo), fechando o vies desta contagem isolada nunca decidir "
                "sozinha"
            ),
            "permanence_pass_criterio": (
                "n_better >= min_paths_required AND n_paths_significant >= "
                "min_paths_required -- backtest_lite.permanence_pass_criterion, "
                "ADR-004 Sec6 / handoff de src/models/ item 2, 2026-08-27"
            ),
            # AG-220/ADR-004 Fase 0 -- IC bootstrap por blocos da diferenca
            # Camada1-Camada0 POR CAMINHO. Companion de
            # n_paths_camada1_supera_camada0 acima, NAO substituto: aquele
            # conta vitorias por sharpe_naive, este responde se cada
            # diferenca e distinguivel de ruido. AG-220 mediu |delta| <
            # sigma em BTCUSDT/R1 nas 3 variantes de calibracao testadas --
            # leia os dois numeros juntos, nunca so o primeiro.
            # AG-252 -- duas series, NUNCA reduzidas a uma: `zero_filled`
            # (universo completo, zero fora de sinal) preserva a base de
            # comparacao mas DILUI point_estimate ~20-60x (medido,
            # BTCUSDT/R1, 96-98% das barras sao zero-zero); `signal_only`
            # (so barras onde >=1 camada sinalizou) da a magnitude
            # economica por trade correta. O veredito `significant`
            # concordou nos 5 caminhos medidos, mas e 1 medicao, nao prova
            # geral -- leia os dois campos, nunca so um.
            "permanence_significance_bootstrap": {
                str(pid): {
                    "zero_filled": asdict(r.zero_filled),
                    "signal_only": asdict(r.signal_only),
                }
                for pid, r in permanence_significance.items()
            },
            "n_paths_significant": n_paths_significant,
            "n_paths_significant_signal_only": n_paths_significant_signal_only,
            # ADR-005 §13.13 (item 5 de §13.17) -- `None` quando
            # `permutation_null_replicas=0` (default) -- ausência
            # explícita, não um "não aplicável" silencioso.
            "permutation_null": (
                asdict(permutation_null_result) if permutation_null_result is not None else None
            ),
        },
        # --- AG-211: o `n` estatístico, não o `n` do `shape`. -------------
        "sample_size_efetivo": {
            "ess_sum_uniqueness_long_by_fold": ess_long,
            "ess_sum_uniqueness_short_by_fold": ess_short,
            "n_rows_train_long_by_fold": n_rows_train_long,
            "n_rows_train_short_by_fold": n_rows_train_short,
            "mean_ess_long": _mean_finite(ess_long),
            "mean_ess_short": _mean_finite(ess_short),
            # razão ESS/linhas: quanto do `n` aparente é informação nova.
            # 1,0 = rótulos disjuntos; << 1,0 = sobreposição dominante.
            "mean_ratio_ess_por_linha_long": _mean_finite(
                [e / n for e, n in zip(ess_long, n_rows_train_long, strict=True) if n > 0]  # noqa: unguarded-ratio -- `if n > 0` na propria comprehension
            ),
            "mean_ratio_ess_por_linha_short": _mean_finite(
                [e / n for e, n in zip(ess_short, n_rows_train_short, strict=True) if n > 0]  # noqa: unguarded-ratio -- `if n > 0` na propria comprehension
            ),
            "nota": (
                "B24/§0.2 R4 -- N_eff MEDIDO (soma de uniqueness), nunca uma das duas "
                "formulas fechadas que B24 proibe. "
                "ESS TRANSVERSAL (entre os 5 simbolos correlacionados) NAO esta medido "
                "aqui: M6 (experiments/m6_common_factor_hypothesis_report.json) testa "
                "heterogeneidade de edge MEDIO por simbolo via Cochran's Q/I2, que e uma "
                "pergunta diferente de correlacao de ret_net barra a barra -- ver AG-216"
            ),
        },
        # --- AG-212: desalinhamento contagem x massa no balanceamento ----
        "class_balance": {
            "basis_usado": class_balance_basis,
            "mean_scale_pos_weight_count": _mean_finite(spw_count),
            "mean_scale_pos_weight_weight": _mean_finite(spw_weight),
            "mean_razao_weight_sobre_count": _mean_finite(
                [w / c for w, c in zip(spw_weight, spw_count, strict=True) if c > 0]  # noqa: unguarded-ratio -- `if c > 0` na propria comprehension
            ),
            "nota": (
                "razao != 1,0 mede o desalinhamento: scale_pos_weight entra em CONTAGEM, "
                "mas o gradiente do LightGBM ja e ponderado por sample_weight (MASSA). "
                "A isotonica corrige o NIVEL da probabilidade, nao a forma aprendida "
                "durante o crescimento da arvore (ganho de split, min_child_samples, "
                "min_sum_hessian_in_leaf)"
            ),
        },
        # --- AG-213: os dois alvos concordam? -----------------------------
        "target_agreement_fold0": target_agreement,
        # --- AG-215: Sharpe deflacionado --------------------------------
        "dsr": dsr_block,
        # Proveniência da rodada -- quais políticas estavam ativas.
        "policies": {
            "tau_policy": tau_policy,
            "calib_split_mode": calib_split_mode,
            "class_balance_basis": class_balance_basis,
            "dsr_n_trials": dsr_n_trials,
        },
        "camada1_backtest_by_path": _path_results_to_dict(c1_by_path),
        "camada0_backtest_by_path": _path_results_to_dict(c0_by_path),
        "hhi": {
            "long_by_fold": hhi_values_long,
            "short_by_fold": hhi_values_short,
            "mean_hhi": mean_hhi_nominal,
            "mean_max_share": _mean_finite(max_share_values),
            "mean_n_features_over_1pct": _mean_finite([float(v) for v in n_features_over_1pct]),
            # HHI EFETIVO (D1/D2/D3, CLAUDE.md — achado Sprint 4: features
            # do top-4 por gain correlacionadas, E27f_cost_atr_ratio x
            # C07_vol_pctile_expanding rho=-0,913, A13_dist_ema48_atr x
            # B01_rsi_14 rho=0,947). NUNCA substitui os campos nominais
            # acima — só adiciona a série efetiva ao lado (D2).
            "hhi_effective_long_by_fold": hhi_effective_values_long,
            "hhi_effective_short_by_fold": hhi_effective_values_short,
            "mean_hhi_effective": mean_hhi_effective,
            "mean_n_eff_factors_t1": _mean_finite(n_eff_factors_long + n_eff_factors_short),
            # D3 — Gate 3.4 agora decide sobre o HHI EFETIVO, não o nominal
            # (o nominal subestima concentração real quando features do
            # top-gain são correlacionadas — ver
            # src.models.hhi.compute_effective_concentration para a prova).
            # Thresholds agora lidos de constants.yaml (achado 2026-08-24 --
            # gate3_4_passes/gate3_4_max_share_passes viviam só como default
            # de parâmetro Python, sem entrada de proveniência) -- valores
            # inalterados (0,25/0,30), só a fonte mudou de literal implícito
            # pra constante explícita.
            "gate3_4_hhi_lt_025": hhi.gate3_4_passes(
                mean_hhi_effective, threshold=float(load_constant("alpha_gate3_hhi_effective_max"))
            ),
            # Referência histórica/comparação — o veredito que o HHI
            # NOMINAL sozinho teria dado, mantido visível mas NUNCA usado
            # pelo gate (D3: "mantenha o nominal no relatório também, chave
            # separada, não sobrescrita").
            "gate3_4_hhi_nominal_lt_025_reference": hhi.gate3_4_passes(
                mean_hhi_nominal, threshold=float(load_constant("alpha_gate3_hhi_effective_max"))
            ),
            "gate3_4_max_share_lt_030": hhi.gate3_4_max_share_passes(
                _mean_finite(max_share_values),
                threshold=float(load_constant("alpha_gate3_max_share_max")),
            ),
        },
        "baselines": {
            "b1_random_entry": _summarize_b1_result(b1),
            "b2_buy_and_hold": asdict(b2),
            "b3_regime_only": asdict(b3),
            "b4_feature_shuffle": asdict(b4),
            "b5_short_permanent": asdict(b5),
        },
        "decomposition_pnl": {
            "pooled_all_15_splits": asdict(decomp_pooled),
            "by_path": decomp_by_path,
        },
        "monotone_constraints_example_fold0": {
            "long": {
                f: {
                    "constraint": r.constraint,
                    "mean_ic": r.mean_ic,
                    "n_consistent": r.n_consistent_envs,
                }
                for f, r in camada1_folds[0].long_result.monotone.items()
            },
            "short": {
                f: {
                    "constraint": r.constraint,
                    "mean_ic": r.mean_ic,
                    "n_consistent": r.n_consistent_envs,
                }
                for f, r in camada1_folds[0].short_result.monotone.items()
            },
        },
    }
    if use_economic_gate:
        report["economic_gate"] = _economic_gate_verdicts_by_side(
            filled_c1, symbol=symbol, resolution_id=resolution_id, threshold=pre_trial_gate
        )
        report["n_lifetime_suggested_delta"] = economic_gate.suggested_n_lifetime_delta(
            trained=True
        )
    if run_b1_refinement:
        report["baselines"]["b1_refinement"] = b1_refinement
    write_report_atomic(report, dest_path=report_path)
    logger.info(
        "models.pipeline.run_layer1_sprint_done",
        model_id_camada1=model_id_camada1,
        t0_start_filter=t0_start,
        t0_end_filter=t0_end,
        elapsed_seconds=elapsed_s,
        permanence_pass=permanence_pass,
        n_better=n_better,
        n_total=n_total,
    )
    return report


ALL_SYMBOLS: tuple[str, ...] = (ds.SYMBOL_DEFAULT, *download.DEFAULT_SYMBOLS)
ALL_RESOLUTIONS: tuple[str, ...] = ("R1", "R2", "R3")


def run_layer1_sprint_all_combinations(
    *,
    symbols: tuple[str, ...] = ALL_SYMBOLS,
    resolutions: tuple[str, ...] = ALL_RESOLUTIONS,
    vol_estimator_id: str | None = None,
    device_type: str = "cpu",
    feature_ids: tuple[str, ...] | None = None,
    use_hyperparams_by_combo: bool = False,
    allow_feature_mismatch: bool = False,
    use_economic_gate: bool = True,
    scratch: bool = False,
    report_tag_suffix: str = "",
) -> dict[tuple[str, str], dict[str, Any]]:
    """D-13 (docs/alpha_model_design_doc_2026-08-22.md, §7) -- driver fino
    que chama `run_layer1_sprint` uma vez por (symbol, resolution_id), 15
    vezes por default (5 símbolos x {R1, R2, R3}). `run_layer1_sprint` já
    aceita os dois parâmetros e o CLI já expõe `--resolution-id`
    (Fase 4/5 da migração anterior) -- nenhuma mudança de assinatura foi
    necessária, só orquestração. `device_type` default `"cpu"` -- mesma
    correção/motivo de `run_layer1_sprint` (AG-201, 2026-08-24).

    `report_path`/`run_tag` únicos por combinação (`{symbol}_
    {resolution_id}`) -- fecha `AG-160`: o default de `run_layer1_sprint`
    (`experiments/alpha_layer1_report.json`, sem chave por symbol/
    resolution) faz cada uma das 15 chamadas SOBRESCREVER o relatório da
    anterior (bug de sobrescrita já existente mesmo em execução puramente
    sequencial, agravado 15x pela expansão deste driver). `model_id_
    camada{0,1}` continuam o texto default (`alpha_c1_v1`/`alpha_c0_
    baseline_v1`, SEM sufixo por combinação) -- D-03 já resolveu a
    colisão de artefato via `symbol`/`resolution_id` como colunas/
    segmentos de path explícitos, não é preciso duplicar essa proteção no
    nome do modelo.

    **D-14 -- custo de `N_lifetime` declarado, não escondido.** Nenhum
    trial roda nesta função em si (é orquestração, decide QUANTAS vezes
    chamar `run_layer1_sprint`, não SE deve chamar -- isso é decisão do
    Manager, gate 'Data Layer 100%'). Quando o gate abrir e isto rodar de
    verdade: rodar as 15 combinações de UM desenho já fixado (D-11:
    hiperparâmetro único v1, não uma busca por combinação) não é, por
    definição do ledger (`audit/n_lifetime.yaml`, "N trials = combinações
    de parâmetro que exigem ajuste de modelo NOVO testado contra dado
    real"), automaticamente 15 trials -- é uma leitura genuinamente aberta
    (treinar em 15 mercados vs. buscar parâmetro 15 vezes são coisas
    diferentes). Registrar em `audit/n_lifetime.yaml` (append-only, só
    quando o trial de fato acontecer) exige essa decisão do Manager
    primeiro -- não inventada aqui (B23, mesma disciplina de nunca
    estipular faixa/contagem sem medir).

    `feature_ids`/`use_hyperparams_by_combo` (2026-08-25, `AG-207`/
    `ADR-003`) -- sentinelas `None`/`False` preservam bit-exato o
    comportamento de sempre (T1_FEATURE_IDS, hiperparâmetro único global
    de `constants.yaml`, D-11) pra todo call site/teste existente.
    `feature_ids` explícito (ex. `features_build.SUPPORT_FEATURE_IDS`) é
    repassado IDÊNTICO às 15 chamadas -- mesmo vetor de treino em toda
    combinação. `use_hyperparams_by_combo=True` faz cada chamada
    consultar `hyperparams_by_combo.load_hyperparams_by_combo(symbol,
    resolution_id, feature_ids_effective=...)`; combinação sem
    calibração própria (5 das 15, ver `config/alpha_hyperparams_by_
    combo.yaml`) cai pro hiperparâmetro global -- com warning explícito,
    nunca silencioso.

    **`allow_feature_mismatch` (AG-371, 2026-08-28) -- default `False`.**
    `load_hyperparams_by_combo` valida `feature_ids` resolvido (via
    `features_build.resolve_feature_ids`) contra o vetor sob o qual
    `alpha_hyperparams_by_combo.yaml` foi de fato calibrado (hash de
    conteúdo, não nome de símbolo -- ver docstring do loader). Mismatch
    levanta `HyperparamFeatureMismatchError` por padrão: hiperparâmetro
    calibrado (ADR-003, 25/08) pra um vetor virou stale quando `AG-362`
    (27/08) reestruturou `T1_FEATURE_IDS` sem recalibrar este arquivo, e
    o retreino canônico de 28/08 injetou o hiperparâmetro errado sem
    checagem nenhuma -- o gap que este parâmetro fecha. `True` rebaixa
    pra warning explícito e grava `report["hyperparam_feature_mismatch"]
    = True` -- só pra comparação exploratória deliberada (mesmo espírito
    de `scratch=True`, AG-368); NUNCA usar em retreino canônico.

    `use_economic_gate` (AG-260 ponto (b), `/redesign_workflow`
    2026-08-27) -- repassado IDÊNTICO às 15 chamadas de `run_layer1_
    sprint`, mesmo padrão de `feature_ids` acima. **[Default promovido a
    `True` 2026-08-27]** `False` reproduz o comportamento anterior. Ver a
    docstring de `run_layer1_sprint` pro que `True` de fato faz (soft-
    flag, nunca bloqueia).

    `scratch` (`AG-368`, 2026-08-27) -- repassado IDÊNTICO às 15 chamadas.
    `False` (default) preserva o caminho de sempre: predições em
    `artifacts/predictions_alpha/`, imutáveis, `ArtifactExistsError` se o
    `config_hash` já existir. `True` escreve em `artifacts/scratch/
    predictions_alpha/` e permite sobrescrita -- use quando chamar esta
    função mais de uma vez para o MESMO `symbol`/`resolution_id` com
    designs que podem resolver pro mesmo `config_hash` (ex. comparação
    exploratória, não retreino canônico).

    `report_tag_suffix` (AG-371-ADDENDUM-13, 2026-08-28) -- default `""`
    preserva bit-a-bit o `report_path`/`run_tag` de sempre
    (`alpha_layer1_report_{symbol}_{resolution_id}.json`). Gap real: os
    artefatos de modelo já são content-addressed por `config_hash` (não
    colidem entre `use_hyperparams_by_combo=False` e `True`), mas o
    `report_path` desta função NÃO depende do hiperparâmetro -- rodar as
    15 combinações duas vezes (ex. braço global + braço by-combo, mesma
    comparação do item (2)/(3) fundidos) faz a segunda chamada
    SOBRESCREVER o relatório-resumo da primeira, mesmo elas escrevendo em
    artefatos de modelo distintos. Passar um sufixo (ex. `"_global"` /
    `"_bycombo"`) mantém os dois relatórios-resumo lado a lado sem exigir
    mover arquivo manualmente entre as duas rodadas."""
    # AG-371 -- resolvido UMA vez (mesmo vetor pras 15 chamadas, ver
    # docstring de `feature_ids` acima), usando a mesma fonte de verdade
    # que `run_layer1_sprint` usa internamente pra `feature_ids=None`
    # (`features_build.resolve_feature_ids`) -- é o vetor que precisa
    # validar contra `hyperparams_by_combo`, não o `feature_ids` cru que
    # pode ser `None`.
    feature_ids_effective = features_build.resolve_feature_ids(feature_ids)
    reports: dict[tuple[str, str], dict[str, Any]] = {}
    for symbol in symbols:
        for resolution_id in resolutions:
            run_tag = f"{symbol}_{resolution_id}{report_tag_suffix}"
            report_path = EXPERIMENTS_DIR / f"alpha_layer1_report_{run_tag}.json"
            hyper: alpha.LGBMHyperparams | None = None
            feature_mismatch = False
            if use_hyperparams_by_combo:
                hyper, feature_mismatch = hyperparams_by_combo.load_hyperparams_by_combo(
                    symbol,
                    resolution_id,
                    feature_ids_effective=feature_ids_effective,
                    allow_feature_mismatch=allow_feature_mismatch,
                )
                if hyper is None:
                    logger.warning(
                        "models.pipeline.hyperparams_by_combo_ausente",
                        symbol=symbol,
                        resolution_id=resolution_id,
                        fallback="hiperparametro global de constants.yaml",
                    )
            logger.info(
                "models.pipeline.run_layer1_sprint_all_combinations_start",
                symbol=symbol,
                resolution_id=resolution_id,
                run_tag=run_tag,
                feature_ids_n=len(feature_ids) if feature_ids is not None else None,
                hyper_por_combo=hyper is not None,
                hyperparam_feature_mismatch=feature_mismatch,
                use_economic_gate=use_economic_gate,
            )
            report = run_layer1_sprint(
                symbol=symbol,
                resolution_id=resolution_id,
                vol_estimator_id=vol_estimator_id,
                report_path=report_path,
                device_type=device_type,
                feature_ids=feature_ids,
                hyper=hyper,
                use_economic_gate=use_economic_gate,
                scratch=scratch,
            )
            # AG-371 -- marca o report mesmo sob `allow_feature_mismatch=
            # True` (única forma de o consumidor do JSON persistido saber
            # que este `hyper` não foi validado pro vetor que treinou de
            # fato, sem precisar reler log).
            if feature_mismatch:
                report["hyperparam_feature_mismatch"] = True
            reports[(symbol, resolution_id)] = report
    logger.info(
        "models.pipeline.run_layer1_sprint_all_combinations_done",
        n_combinations=len(reports),
        symbols=symbols,
        resolutions=resolutions,
    )
    return reports


def _optional_policy_kwargs(
    *, calib_split_mode: str | None, class_balance_basis: str | None
) -> dict[str, Any]:
    """Bug real medido nesta sessão, corrigido aqui: o parser de CLI (`_parse_
    args`, abaixo) declarava os defaults LEGADOS de `calib_split_mode`/
    `class_balance_basis` e os passava SEMPRE, explicitamente, pra
    `run_layer1_sprint` -- mesmo quando o usuário não passava a flag. Isso
    mascarava silenciosamente a promoção de `AG-272` (a função em si já
    default para `TEMPORAL_PURGED`/`WEIGHT`): 8 relatórios reais em
    `experiments/*_ag207_k62.json` (2026-08-26) confirmam o dano --
    gerados via CLI sem flag, gravam os valores LEGADOS porque o parser
    sempre sobrescrevia o default certo da função com o default errado do
    argparse.

    Fix: `_parse_args` usa `default=None` pros dois -- esta função só
    inclui a chave no dict quando o usuário passou a flag de verdade. Sem
    ela, `run_layer1_sprint` nunca recebe o parâmetro, e usa o PRÓPRIO
    default -- nunca mais diverge, mesmo se a função for promovida de novo
    no futuro (o defeito original só existia porque o CLI duplicava um
    literal que já vivia na assinatura da função)."""
    kwargs: dict[str, Any] = {}
    if calib_split_mode is not None:
        kwargs["calib_split_mode"] = calib_split_mode
    if class_balance_basis is not None:
        kwargs["class_balance_basis"] = class_balance_basis
    return kwargs


if __name__ == "__main__":  # pragma: no cover — execução manual
    import argparse
    import sys

    def _parse_args() -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description=(
                "Sprint 8 -- Alpha Camada 1. Sem argumentos: comportamento "
                "identico ao de sempre (janela cheia, model_id/relatorio "
                "default). --t0-start/--t0-end + --run-tag reprocessam um "
                "subintervalo (ex. PRD_V4_1.md T0.5, janela comum "
                "2021-12-01..2026-08-01) sem sobrescrever a rodada existente."
            )
        )
        parser.add_argument("--symbol", default=SYMBOL)
        parser.add_argument(
            "--t0-start", default=None, help="ISO date inclusive, ex. 2021-12-01"
        )
        parser.add_argument("--t0-end", default=None, help="ISO date inclusive, ex. 2026-08-01")
        parser.add_argument(
            "--run-tag",
            default=None,
            help=(
                "sufixo aplicado a model_id/relatorio para nao colidir com a "
                "rodada de janela cheia (ex. t05_common_window)"
            ),
        )
        parser.add_argument(
            "--tf",
            default=None,
            help=(
                "grade de tempo explicita (ex. 30m/1h) -- default None preserva "
                "o caminho legado plano (mesmo sentinel de sempre, ver "
                "docstring de run_layer1_sprint)"
            ),
        )
        parser.add_argument(
            "--resolution-id",
            default=None,
            help=(
                "grade dollar-bar (ex. R1, Fase 5 da migracao "
                "Parkinson+dollar-bar) -- vence sobre --tf quando setado, mesmo "
                "desenho de UM parametro de grade das Fases 2-4"
            ),
        )
        parser.add_argument(
            "--vol-estimator-id",
            default=None,
            help='estimador de volatilidade explicito (ex. "parkinson_w20") -- '
            "[PROMOVIDO 2026-08-27] sem a flag, run_layer1_sprint resolve "
            "pra constants.yaml::canonical_volatility_estimator (hoje "
            "parkinson_w20), NAO MAIS ATRWilder legado",
        )
        parser.add_argument(
            "--all-combinations",
            action="store_true",
            help=(
                "D-13 -- roda as 15 combinacoes (5 simbolos x {R1,R2,R3}) via "
                "run_layer1_sprint_all_combinations() em vez de uma rodada "
                "unica; ignora --symbol/--resolution-id/--tf/--run-tag. "
                "Sempre passa feature_ids=T1_FEATURE_IDS explicito (AG-366, "
                "2026-08-27) -- None nao entra no config_hash, colidiria com "
                "artefato de uma composicao de T1 anterior"
            ),
        )
        parser.add_argument(
            "--use-hyperparams-by-combo",
            action="store_true",
            help=(
                "AG-207/ADR-003 -- so com --all-combinations. False (default) "
                "usa o hiperparametro global de constants.yaml em toda "
                "combinacao (comportamento de sempre); True consulta "
                "config/alpha_hyperparams_by_combo.yaml por combinacao, "
                "caindo no global com warning explicito nas celulas sem "
                "calibracao propria"
            ),
        )
        parser.add_argument(
            "--allow-feature-mismatch",
            action="store_true",
            help=(
                "AG-371 -- so com --use-hyperparams-by-combo. False (default, "
                "SEMPRE em retreino canonico) FALHA ALTO "
                "(HyperparamFeatureMismatchError) se o hiperparametro por "
                "combo foi calibrado sob um vetor de features diferente do "
                "que esta rodando agora (hash de conteudo, config/"
                "alpha_hyperparams_by_combo.yaml::feature_ids_hash). True "
                "rebaixa pra warning + marca "
                "report['hyperparam_feature_mismatch']=True -- so pra "
                "comparacao exploratoria deliberada, nunca canonico"
            ),
        )
        # --- AG-208..AG-215: politicas de correcao, todas OPT-IN. Os
        # defaults abaixo reproduzem o comportamento legado bit-a-bit --
        # rodar sem nenhuma destas flags produz exatamente o artefato de
        # sempre, so com o relatorio mais rico (ESS, dispersao entre
        # caminhos, concordancia de alvos, balanceamento medido).
        parser.add_argument(
            "--tau-policy",
            default=alpha.TAU_POLICY_LEGACY_PER_SIDE,
            choices=[alpha.TAU_POLICY_LEGACY_PER_SIDE, alpha.TAU_POLICY_TOTAL_COMMON_OOF],
            help=(
                "AG-210 -- legacy_per_side aplica o quantil (1-target_signal_rate) a "
                "CADA lado (comportamento atual); total_common_oof resolve o par "
                "(tau_long, tau_short) para que a taxa TOTAL bata o orcamento, sobre a "
                "populacao comum de barras de treino fora do fit. Ver "
                "constants.yaml::fee_budget_is_per_side (value: false)"
            ),
        )
        parser.add_argument(
            "--calib-split-mode",
            default=None,
            choices=[alpha.CALIB_SPLIT_LEGACY_RANDOM, alpha.CALIB_SPLIT_TEMPORAL_PURGED],
            help=(
                "AG-209 -- legacy_random_stratified usa train_test_split aleatorio "
                "(rotulos sobrepostos caem dos dois lados do split); temporal_purged "
                "usa bloco temporal contiguo + purge por t1 (B09 aplicado ao sub-split "
                "interno, nao so ao CPCV externo). Sem a flag: usa o default de "
                "run_layer1_sprint (AG-272 promoveu pra temporal_purged -- NAO "
                "hardcodar um valor aqui, ver _optional_policy_kwargs)"
            ),
        )
        parser.add_argument(
            "--class-balance-basis",
            default=None,
            choices=[alpha.CLASS_BALANCE_COUNT, alpha.CLASS_BALANCE_WEIGHT],
            help=(
                "AG-212 -- count usa n_neg/n_pos (contagem); weight usa a razao de "
                "MASSA, coerente com o gradiente ja ponderado por sample_weight. Os "
                "DOIS sao sempre medidos e reportados. Sem a flag: usa o default de "
                "run_layer1_sprint (AG-272 promoveu pra weight -- NAO hardcodar um "
                "valor aqui, ver _optional_policy_kwargs)"
            ),
        )
        parser.add_argument(
            "--dsr-n-trials",
            type=int,
            default=None,
            help=(
                "AG-215 -- N_lifetime auditado (audit/n_lifetime.yaml) para deflacionar "
                "o Sharpe (Bailey & Lopez de Prado). SEM default: nao informado = DSR "
                "nao calculado, com a razao declarada no proprio relatorio. Inventar um "
                "N aqui produziria um DSR tranquilizador e falso (B23)"
            ),
        )
        parser.add_argument(
            "--report-tag-suffix",
            default="",
            help=(
                "AG-371-ADDENDUM-13 -- so com --all-combinations. Sufixo "
                "aplicado ao nome do relatorio-resumo por combinacao "
                "(alpha_layer1_report_{symbol}_{resolution_id}{sufixo}.json), "
                "para rodar o mesmo --all-combinations mais de uma vez (ex. "
                "braco global vs braco --use-hyperparams-by-combo) sem a "
                "segunda chamada sobrescrever o relatorio da primeira. Nao "
                "afeta artefato de modelo (ja content-addressed por "
                "config_hash)."
            ),
        )
        parser.add_argument(
            "--device-type",
            default="cpu",
            choices=["cuda", "cpu", "gpu"],
            help=(
                "AG-201 (2026-08-24) -- default cpu: CUDA bloqueado "
                "estruturalmente neste ambiente (LightGBM exige NCCL, sem "
                "build Windows nativo). Passe cuda explicitamente se/quando "
                "migrar para ambiente Linux/cloud com CUDA+NCCL funcionais"
            ),
        )
        return parser.parse_args()

    def _run_cli() -> int:
        args = _parse_args()
        if args.all_combinations:
            reports = run_layer1_sprint_all_combinations(
                vol_estimator_id=args.vol_estimator_id,
                device_type=args.device_type,
                # AG-366 -- feature_ids=None nao entra no config_hash, entao
                # nao distingue este retreino de um anterior sob outra
                # composicao de T1_FEATURE_IDS. Passar explicito torna o
                # config_hash correto sem mudar o que de fato treina (T1_
                # FEATURE_IDS e o mesmo vetor que None ja resolvia).
                feature_ids=features_build.T1_FEATURE_IDS,
                use_hyperparams_by_combo=args.use_hyperparams_by_combo,
                allow_feature_mismatch=args.allow_feature_mismatch,
                report_tag_suffix=args.report_tag_suffix,
            )
            logger.info(
                "models.pipeline.cli_all_combinations_done",
                n_combinations=len(reports),
                use_hyperparams_by_combo=args.use_hyperparams_by_combo,
                allow_feature_mismatch=args.allow_feature_mismatch,
                report_tag_suffix=args.report_tag_suffix,
            )
            return 0
        tag = f"_{args.run_tag}" if args.run_tag else ""
        report = run_layer1_sprint(
            symbol=args.symbol,
            tf=args.tf,
            resolution_id=args.resolution_id,
            vol_estimator_id=args.vol_estimator_id,
            t0_start=args.t0_start,
            t0_end=args.t0_end,
            model_id_camada1=f"{MODEL_ID_CAMADA1}{tag}",
            model_id_camada0=f"{MODEL_ID_CAMADA0}{tag}",
            report_path=(EXPERIMENTS_DIR / f"alpha_layer1_report{tag}.json") if tag else None,
            device_type=args.device_type,
            tau_policy=args.tau_policy,
            dsr_n_trials=args.dsr_n_trials,
            **_optional_policy_kwargs(
                calib_split_mode=args.calib_split_mode,
                class_balance_basis=args.class_balance_basis,
            ),
        )
        logger.info(
            "models.pipeline.cli_done",
            report_path=str(
                (EXPERIMENTS_DIR / f"alpha_layer1_report{tag}.json")
                if tag
                else (EXPERIMENTS_DIR / "alpha_layer1_report.json")
            ),
            permanence_pass=report["layer1_vs_layer0"]["permanence_pass"],
        )
        return 0

    sys.exit(_run_cli())
