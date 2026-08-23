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

from src.data.resample import step_ms
from src.features import build as features_build
from src.validation import cpcv

from . import alpha, backtest_lite, baselines, decomposition, hhi
from . import dataset as ds
from ._constants import load_constant
from ._paths import (
    EXPERIMENTS_DIR,
    PREDICTIONS_OUTPUT_DIR,
    models_diagnostics_symbol_tf_dir,
    predictions_symbol_tf_dir,
)

# Reexport explícito (`as MODELS_DIR`, não só `import MODELS_DIR`) —
# `mypy --strict`/`no_implicit_reexport` (`pyproject.toml`) trata um import
# simples como privado ao módulo; vários chamadores fazem
# `from src.models.pipeline import MODELS_DIR` (`faixa1_5_prerequisites.py`
# e testes, ver AG-013) e precisam continuar funcionando sob checagem
# estrita, não só em runtime.
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
    chaveado novo."""
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
            alpha_xgb_n_estimators=expected_n_trees,
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
) -> dict[str, Any]:
    """`t0_start`/`t0_end`/`model_id_camada{0,1}`/`report_path` default para
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

    `resolution_id`/`vol_estimator_id` (Fase 4, AG-030/036/065) —
    `resolution_id=None` (default) preserva bit-exato: `tf_effective =
    tf ou "15m"`, `grade_id = tf_effective`, mesmo caminho de sempre.
    `resolution_id="R1"` propaga a MESMA grade pra `build_modeling_frame`
    (que por sua vez propaga pra labels/features/regime, Fase 4 item 15) E
    pro `CPCVConfig.grade_id` do CPCV — um único parâmetro de grade, não
    dois que pudessem divergir. `path_tf` (destino em disco de predictions/
    diagnostics) usa `resolution_id` quando setado, MESMO que `tf` continue
    `None` — nunca cai no caminho legado plano que colidiria com os 5
    `model_id` de produção já treinados sob grade de tempo (mesma guarda
    de path-collision de `labels_symbol_tf_dir`, Fase 1)."""
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
    mf = ds.build_modeling_frame(
        symbol=symbol,
        tf=tf_effective,
        resolution_id=resolution_id,
        vol_estimator_id=vol_estimator_id,
        t0_start=t0_start,
        t0_end=t0_end,
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
    max_feature_lookback_ms = features_build.compute_max_feature_lookback_ms(
        tf_effective, resolution_id=resolution_id
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

    hyper = alpha.LGBMHyperparams.from_constants()
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

    preds_c1 = alpha.assemble_predictions_table(camada1_folds)
    preds_c0 = alpha.assemble_predictions_table(camada0_folds)
    # `tf=None`/`resolution_id=None` (default): SEM dest_dir -> caminho
    # legado plano, bit-exato com o comportamento anterior a esta mudança
    # (ver docstring da função — 7 leitores de produção reais ainda
    # dependem disso). `tf`/`resolution_id` explícito: layout chaveado por
    # symbol/`path_tf` (mesma guarda contra colisão do bloco acima).
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
    permanence_pass = n_better >= min_paths_required

    c1_sharpes = [r.sharpe_naive for r in c1_by_path.values()]
    c0_sharpes = [r.sharpe_naive for r in c0_by_path.values()]
    alpha_sharpe_headline = _mean_finite(c1_sharpes)

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
    b4 = baselines.run_b4_feature_shuffle(mf.data, splits, camada1_folds)
    b5 = baselines.run_b5_short_permanent(mf.data)

    # --- decomposição de PnL (§16.6) — pooled sobre as OOF de todos os 15 splits ---
    filled_c1 = realized_c1.filter(pl.col("barrier_hit") != "NOFILL")
    decomp_pooled = decomposition.decompose(filled_c1)
    decomp_by_path: dict[str, Any] = {}
    for pid in sorted({fr.path_id for fr in camada1_folds}):
        path_trades = filled_c1.filter(pl.col("path_id") == pid)
        decomp_by_path[str(pid)] = asdict(decomposition.decompose(path_trades))

    elapsed_s = time.time() - t_start

    report: dict[str, Any] = {
        "schema_version": 1,
        "sprint": 8,
        "symbol": symbol,
        "tf": tf,
        "resolution_id": resolution_id,
        "vol_estimator_id": vol_estimator_id,
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
            "gate3_4_hhi_lt_025": hhi.gate3_4_passes(mean_hhi_effective),
            # Referência histórica/comparação — o veredito que o HHI
            # NOMINAL sozinho teria dado, mantido visível mas NUNCA usado
            # pelo gate (D3: "mantenha o nominal no relatório também, chave
            # separada, não sobrescrita").
            "gate3_4_hhi_nominal_lt_025_reference": hhi.gate3_4_passes(mean_hhi_nominal),
            "gate3_4_max_share_lt_030": hhi.gate3_4_max_share_passes(
                _mean_finite(max_share_values)
            ),
        },
        "baselines": {
            "b1_random_entry": {
                "n_seeds": b1.n_seeds,
                "sample_size": b1.sample_size,
                "alpha_sharpe": b1.alpha_sharpe,
                "percentile_of_alpha": b1.percentile,
                "null_mean": _mean_finite(list(b1.null_sharpes)),
                "null_p50": _percentile_finite(list(b1.null_sharpes), 50.0),  # noqa: magic-number
                "null_p95": _percentile_finite(list(b1.null_sharpes), 95.0),  # noqa: magic-number
            },
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
            "default None preserva ATRWilder bit-exato",
        )
        return parser.parse_args()

    def _run_cli() -> int:
        args = _parse_args()
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
