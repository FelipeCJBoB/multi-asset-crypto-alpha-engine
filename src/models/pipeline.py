"""Orquestração ponta a ponta do Sprint 8 — Alpha Camada 1 (§5, §16.1,
§16.6). Roda os 15 splits do CPCV (Sprint 7) para as duas variantes
(Camada 1 monotônica e Camada 0 conceitual sem restrição), os 5 baselines
nulos, a decomposição de PnL, e decide o critério de permanência do §5.11
adaptado (`alpha_layer1_permanence_min_paths`, ver `constants.yaml`).

Escreve `predictions/alpha/{model_id}/predictions.parquet` (§5.12, um
arquivo por variante) e `experiments/alpha_layer1_report.json` (números
desta rodada — HHI, baselines, decomposição, decisão de permanência)."""

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

from src.validation import cpcv

from . import alpha, backtest_lite, baselines, decomposition
from . import dataset as ds
from ._constants import load_constant
from ._paths import EXPERIMENTS_DIR, PREDICTIONS_OUTPUT_DIR, REPO_ROOT

logger = structlog.get_logger(__name__)

MODEL_ID_CAMADA1 = "alpha_c1_v1"
MODEL_ID_CAMADA0 = "alpha_c0_baseline_v1"

SYMBOL = ds.SYMBOL_DEFAULT

# `models/{model_id}/diagnostics/` (task A1 do CLAUDE.md) — diretório de
# DADO no topo do repo (irmão de `data/`, `predictions/`, `experiments/`),
# não o pacote de código `src/models/`. Não movido para `_paths.py` porque
# esse arquivo está fora do escopo desta mudança; `REPO_ROOT` já é público
# em `._paths`, então isso é só um import de símbolo existente, não edição.
MODELS_DIR: Path = REPO_ROOT / "models"


def write_predictions_atomic(predictions: pl.DataFrame, model_id: str) -> Path:
    """§5.12 — `predictions/alpha/{model_id}/predictions.parquet`. Mesmo
    padrão `.tmp -> fsync -> rename` (B29) de
    `src.labels.triple_barrier.write_labels_atomic`."""
    out_dir = PREDICTIONS_OUTPUT_DIR / "alpha" / model_id
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

    `n_trees` vem de `booster.num_boosted_rounds()` — como early stopping
    não está implementado nesta rodada (ver docstring do módulo
    `src.models.alpha` e `constants.yaml:alpha_xgb_n_estimators`), o
    esperado é `n_trees == alpha_xgb_n_estimators` (300) sempre; um desvio é
    logado como warning aqui em vez de silenciosamente ignorado.
    `best_iteration` não tem significado sem early stopping — reportado
    como `null` com uma nota explícita, nunca inventado (mesma disciplina
    de `TBD — medir no Sprint N`, B23)."""
    booster = side_result.model.get_booster()
    n_trees = int(booster.num_boosted_rounds())
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
) -> list[Path]:
    """`models/{model_id}/diagnostics/fold_{fold_id}_{side_label}.json` —
    um arquivo por fold x lado (long e short), B29: `.tmp` -> `fsync` ->
    `rename`, mesmo padrão de `write_predictions_atomic`/
    `write_report_atomic` acima. Ver `.gitignore`: `models/*/diagnostics/`
    é intencionalmente versionado (evidência de auditoria pequena e
    legível, mesma categoria de `data/quality_reports/`), não é o artefato
    binário de modelo que `models/*.bin`/`models/*.json` (raiz de
    `models/{model_id}/`) ignoram."""
    out_dir = MODELS_DIR / model_id / "diagnostics"
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
    hyper: alpha.XGBHyperparams,
) -> list[Path]:
    """Escreve o diagnóstico de todos os folds de uma variante (Camada 1 OU
    Camada 0) — chamada duas vezes por `run_layer1_sprint`, uma por
    variante, cada uma com seu próprio `model_id`."""
    written: list[Path] = []
    for fr in fold_results:
        written.extend(
            write_fold_diagnostics_atomic(
                fr, model_id=model_id, expected_n_trees=hyper.n_estimators
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


def run_layer1_sprint(*, symbol: str = SYMBOL) -> dict[str, Any]:
    t_start = time.time()
    mf = ds.build_modeling_frame(symbol=symbol)
    cpcv_result = cpcv.generate_splits(mf.data)
    splits = cpcv_result.splits
    logger.info(
        "models.pipeline.run_layer1_sprint_start",
        n_rows=mf.data.height,
        n_splits=cpcv_result.config.n_splits,
        n_backtest_paths=cpcv_result.config.n_backtest_paths,
    )

    hyper = alpha.XGBHyperparams.from_constants()
    seed = int(load_constant("alpha_random_seed"))

    camada1_folds = alpha.run_all_folds(
        mf.data,
        splits,
        variant=alpha.VARIANT_CAMADA1,
        model_id=MODEL_ID_CAMADA1,
        hyper=hyper,
        seed=seed,
    )
    camada0_folds = alpha.run_all_folds(
        mf.data,
        splits,
        variant=alpha.VARIANT_CAMADA0,
        model_id=MODEL_ID_CAMADA0,
        hyper=hyper,
        seed=seed,
    )

    # --- diagnóstico por fold x lado (task A1 do CLAUDE.md) — persiste o
    # que antes só existia em memória dentro de FoldResult/SideModelResult
    # e nunca saía do processo (gain_by_column bruto, shares normalizados,
    # HHI, n_trees, tamanho de amostra). Escrito para as DUAS variantes,
    # cada uma no seu próprio model_id, antes de qualquer agregação em
    # médias no relatório final.
    write_all_fold_diagnostics(camada1_folds, model_id=MODEL_ID_CAMADA1, hyper=hyper)
    write_all_fold_diagnostics(camada0_folds, model_id=MODEL_ID_CAMADA0, hyper=hyper)

    preds_c1 = alpha.assemble_predictions_table(camada1_folds)
    preds_c0 = alpha.assemble_predictions_table(camada0_folds)
    write_predictions_atomic(preds_c1, MODEL_ID_CAMADA1)
    write_predictions_atomic(preds_c0, MODEL_ID_CAMADA0)

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

    # --- baselines nulos (§16.1) ---
    realized_c1 = backtest_lite.realize_trades(camada1_folds, mf.data)
    n_filled_c1 = realized_c1.filter(pl.col("barrier_hit") != "NOFILL").height
    sample_size_b1 = max(1, round(n_filled_c1 / max(len(c1_by_path), 1)))

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
            "mean_hhi": _mean_finite(hhi_values_long + hhi_values_short),
            "mean_max_share": _mean_finite(max_share_values),
            "mean_n_features_over_1pct": _mean_finite([float(v) for v in n_features_over_1pct]),
            "gate3_4_hhi_lt_025": _mean_finite(hhi_values_long + hhi_values_short) < 0.25,  # noqa: magic-number
            "gate3_4_max_share_lt_030": _mean_finite(max_share_values) < 0.30,  # noqa: magic-number
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
    write_report_atomic(report)
    logger.info(
        "models.pipeline.run_layer1_sprint_done",
        elapsed_seconds=elapsed_s,
        permanence_pass=permanence_pass,
        n_better=n_better,
        n_total=n_total,
    )
    return report


if __name__ == "__main__":  # pragma: no cover — execução manual
    import sys

    def _run_cli() -> int:
        run_layer1_sprint()
        return 0

    sys.exit(_run_cli())
