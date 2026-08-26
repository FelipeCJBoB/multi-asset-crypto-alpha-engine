"""Faixa 2, E3 — Camada 2 (§5.4), triagem de estabilidade in-fold sobre as
18 candidatas: T1 reduzido de 8 (pré-E2 (2), permutação) + as 10
selecionadas pelo E2 (ortogonalidade incremental, `experiments/
faixa2_e2_research.json`). Roda `src.models.stability.stability_screen`
sobre os **15 splits REAIS do CPCV** (`src.validation.cpcv`, não uma
amostra sintética) x 2 lados = 30 células (fold, lado) — mede em quantas
delas cada feature sobrevive ao `limiar` (§18, classe A, `config/
constants.yaml::alpha_stability_screen_limiar`, ASSUMED nesta rodada).

**Ambientes = 6 (RANGE/TREND x tercil de custo), sem crossing de
`rpi_regime`** — decisão do Manager (2026-08-09), documentada em
`src.models.stability` e `docs/SPRINT_LOG.md` ("Ambientes do E3"): a
leitura literal "12 células" (3 tercil x 4 regime R1..R4, citação
paralela do PRD) cruzaria volatilidade com ela mesma (R1..R4 já É
estrutura x vol) e, combinada com `alpha_monotonic_consistency_min_envs`
exigindo unanimidade, tornaria a barra estatisticamente quase impossível
de passar (P sob ruído: 3,125% em 6 ambientes vs 0,049% em 12 — 64x mais
restritiva). `rpi_regime` (PRE/POST) fica como diagnóstico separado
(`ic_by_rpi_regime`), não como ambiente — perdeu o alvo depois que o
Grupo F saiu de T1 (v3.3, §2.7.1); nenhuma das 10 candidatas do E2 é
microestrutura.

**Nada disto decide produção sozinho.** `registry.yaml`/`T1_FEATURE_IDS`
continuam intocados — E3 é a última medição antes da FASE 3 (C1/C2/C3),
que precisa retreinar a Camada 1 sob "a config vencedora de E1+E2+E3"."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog

from src.core.provenance import report_provenance
from src.features import build as features_build
from src.models import dataset as ds
from src.models import environments, stability
from src.models._constants import _load_all, load_constant
from src.models.hhi import compute_effective_concentration
from src.validation import cpcv

from .faixa2_e2_research import CURRENT_T1, build_research_candidates_frame

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "faixa2_e3_stability.json"

# Vencedoras do E2 (`experiments/faixa2_e2_research.json::greedy_selection.
# selected_beyond_t1`) -- entrada FIXA aqui, não recomputada: E3 opera
# sobre "a config vencedora" de E2, não relitiga a ortogonalidade.
E2_SELECTED_BEYOND_T1: Final[tuple[str, ...]] = (
    "A12_gap_pct",
    "E05f_time_to_funding_h",
    "E12f_price_oi_divergence",
    "K08_days_since_halving",
    "H01_exchange_netflow_z",
    "E11f_oi_change_1d",
    "A08_upper_wick_ratio",
    "K02_dow_sin",
    "D04f_volume_accel",
    "E17f_retail_vs_top_spread",
)
CANDIDATES_18: Final[tuple[str, ...]] = CURRENT_T1 + E2_SELECTED_BEYOND_T1
SIDES: Final[tuple[int, ...]] = (1, -1)


def build_extended_modeling_frame(symbol: str = "BTCUSDT") -> pl.DataFrame:
    """`src.models.dataset.build_modeling_frame` (produção: labels + T1(10)
    + regime, MESMA ordem de linha que `cpcv.generate_splits` exige) +
    LEFT JOIN das 10 candidatas do E2 por `t0` (preserva ordem/contagem do
    lado esquerdo — mesmo padrão já usado dentro de `build_modeling_frame`
    para juntar regime)."""
    mf = ds.build_modeling_frame(symbol=symbol)
    start, end = ds.date_bounds(mf.data)
    e2_frame, _coverage_warnings = build_research_candidates_frame(symbol, start, end)
    # `e2_frame["t0"]` vem de `bars_15m["close_time"]` (epoch ms, i64) --
    # `mf.data["t0"]` já é `Datetime("ms", "UTC")` (convenção de
    # `src.labels.triple_barrier`). Cast explícito para a chave do join
    # bater; `mf.data` mantém a ordem (join "left").
    e2_cols = e2_frame.select(
        pl.col("t0").cast(pl.Int64).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
        *E2_SELECTED_BEYOND_T1,
    )
    extended = mf.data.join(e2_cols, on="t0", how="left")
    if extended.height != mf.data.height:
        raise AssertionError(
            "build_extended_modeling_frame: join com E2_frame mudou a contagem de linhas "
            f"({mf.data.height} -> {extended.height}) -- ordem/contagem precisa ser "
            "EXATAMENTE a de build_modeling_frame para os splits do CPCV continuarem válidos"
        )
    return extended


def run_stability_screen_over_cpcv(
    df_all: pl.DataFrame, *, limiar: float | None = None
) -> dict[str, Any]:
    """Para cada um dos `C(6,2)=15` splits do CPCV x 2 lados (30 células),
    roda `stability.stability_screen` sobre as 18 candidatas usando
    `train_side_df` — o MESMO subconjunto que `fit_side_model` usaria (via
    `ds.side_subset`), nunca o teste do split. Retorna agregados por
    feature: em quantas das 30 células sobrevive, estabilidade média,
    quebra por lado."""
    if limiar is None:
        limiar = float(load_constant("alpha_stability_screen_limiar"))

    cpcv_result = cpcv.generate_splits(df_all)

    per_feature_cells: dict[str, list[dict[str, Any]]] = {f: [] for f in CANDIDATES_18}
    env_sizes_by_cell: list[dict[str, Any]] = []
    for split in cpcv_result.splits:
        train_bars = df_all[split.train_idx]
        for side in SIDES:
            train_side_df = ds.side_subset(
                train_bars, side=side, feature_ids=features_build.T1_FEATURE_IDS
            )
            n_train_rows = train_side_df.height
            df_env = environments.assign_environments(train_side_df)
            env_counts = (
                df_env.drop_nulls(environments.ENV_COL)
                .group_by(environments.ENV_COL)
                .len()
                .to_dict(as_series=False)
            )
            env_sizes_by_cell.append(
                {
                    "fold_id": split.split_id,
                    "side": side,
                    "n_train_rows": n_train_rows,
                    "counts_by_env": dict(
                        zip(env_counts[environments.ENV_COL], env_counts["len"], strict=True)
                    ),
                }
            )
            results = stability.stability_screen(train_side_df, CANDIDATES_18, limiar=limiar)
            for feature, r in results.items():
                per_feature_cells[feature].append(
                    {
                        "fold_id": split.split_id,
                        "side": side,
                        "n_train_rows": n_train_rows,
                        "n_envs_with_data": r.n_envs_with_data,
                        "ic_by_env": r.ic_by_env,
                        "forca": r.forca,
                        "consistencia": r.consistencia,
                        "estabilidade": r.estabilidade,
                        "survives": r.survives,
                    }
                )

    import statistics

    summary: dict[str, Any] = {}
    for feature, cells in per_feature_cells.items():
        n_cells = len(cells)
        n_survived = sum(1 for c in cells if c["survives"])
        by_side: dict[str, Any] = {}
        for side in SIDES:
            side_cells = [c for c in cells if c["side"] == side]
            n_side = len(side_cells)
            n_side_survived = sum(1 for c in side_cells if c["survives"])
            mean_est_side = (
                sum(c["estabilidade"] for c in side_cells) / n_side if n_side else float("nan")
            )
            by_side[str(side)] = {
                "n_cells": n_side,
                "n_survived": n_side_survived,
                "mean_estabilidade": mean_est_side,
            }
        # |IC| MEDIANO -- pedido do Manager (2026-08-09, "caracterizar o
        # PODER da triagem antes de interpretar os zeros"): mediana de
        # TODOS os IC de ambiente individuais (fold x side x env) com
        # dado, não a média com denominador fixo 6 que `forca` usa (essa
        # é a métrica CERTA pra `estabilidade`, mas underestima magnitude
        # típica quando ambientes faltam dado).
        all_abs_ic = [
            abs(v)
            for c in cells
            for v in c["ic_by_env"].values()
            if isinstance(v, int | float) and v == v  # exclui NaN
        ]
        summary[feature] = {
            "n_cells_total": n_cells,
            "n_cells_survived": n_survived,
            "survival_rate": n_survived / n_cells if n_cells else float("nan"),
            "mean_estabilidade": sum(c["estabilidade"] for c in cells) / n_cells
            if n_cells
            else float("nan"),
            "mean_consistencia": sum(c["consistencia"] for c in cells) / n_cells
            if n_cells
            else float("nan"),
            "mean_forca": sum(c["forca"] for c in cells) / n_cells if n_cells else float("nan"),
            "median_abs_ic_by_env": statistics.median(all_abs_ic) if all_abs_ic else float("nan"),
            "n_ic_env_observations": len(all_abs_ic),
            "by_side": by_side,
        }

    sweep_range = _load_all()["alpha_stability_screen_limiar"]["sweep_range"]
    sweep_points = sorted({float(sweep_range[0]), limiar, float(sweep_range[1])})
    limiar_sensitivity = {
        f"{point:.3f}": {
            feature: sum(1 for c in cells if c["estabilidade"] >= point)
            for feature, cells in per_feature_cells.items()
        }
        for point in sweep_points
    }

    all_env_counts = [n for cell in env_sizes_by_cell for n in cell["counts_by_env"].values()]
    env_size_summary = {
        "median_obs_per_env_cell": statistics.median(all_env_counts) if all_env_counts else None,
        "min_obs_per_env_cell": min(all_env_counts) if all_env_counts else None,
        "max_obs_per_env_cell": max(all_env_counts) if all_env_counts else None,
        "note": (
            "N por (fold, lado, ambiente) individual -- MEDIDO, não a "
            "premissa de ~5.000/ambiente usada na estimativa de poder do "
            "Manager (baseada em n_rows_train/6 pooled; o corte real de "
            "tercil não distribui igual entre os 6 ambientes porque "
            "RANGE/TREND não são metade/metade da amostra)."
        ),
    }

    return {
        "limiar": limiar,
        "limiar_sensitivity_note": (
            "n_cells_survived (de 30) recomputado, SEM rerodar o screen, nos "
            "extremos de sweep_range declarado em constants.yaml -- classe A "
            "exige varredura ANTES do Gate 3 (CLAUDE.md); isto é a checagem "
            "de vizinhança imediata, não a varredura formal de Gate 3."
        ),
        "limiar_sensitivity": limiar_sensitivity,
        "env_size_summary": env_size_summary,
        "env_sizes_by_cell": env_sizes_by_cell,
        "n_splits": len(cpcv_result.splits),
        "n_sides": len(SIDES),
        "n_cells_per_feature": len(cpcv_result.splits) * len(SIDES),
        "summary_by_feature": summary,
        "cells_detail": per_feature_cells,
    }


def summarize_ic_sign_by_env_and_side(
    screen: dict[str, Any], features: tuple[str, ...]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Pergunta do Manager (2026-08-09, item 1): "sinal do IC de C07 e
    D03f, por lado e por ambiente". Cada fold recorta tercis diferentes
    (mesmo ambiente lógico, corte numérico diferente por fold) — resume
    aqui como mediana do IC entre os 15 folds + contagem de folds
    positivos/negativos, por (feature, lado, ambiente)."""
    import statistics

    out: dict[str, dict[str, dict[str, Any]]] = {}
    for feature in features:
        cells = screen["cells_detail"][feature]
        by_side: dict[str, dict[str, Any]] = {}
        for side in SIDES:
            by_env: dict[str, Any] = {}
            for env in environments.ENVIRONMENTS:
                values = [
                    c["ic_by_env"][env]
                    for c in cells
                    if c["side"] == side and c["ic_by_env"][env] == c["ic_by_env"][env]
                ]
                n_pos = sum(1 for v in values if v > 0)
                n_neg = sum(1 for v in values if v < 0)
                by_env[env] = {
                    "median_ic": statistics.median(values) if values else float("nan"),
                    "n_folds_with_data": len(values),
                    "n_folds_negative": n_neg,
                    "n_folds_positive": n_pos,
                }
            by_side[str(side)] = by_env
        out[feature] = by_side
    return out


def c07_d03f_pair_analysis(df_all: pl.DataFrame) -> dict[str, Any]:
    """Pergunta do Manager (2026-08-09, item 2): correlação POOLED entre
    `C07_vol_pctile_expanding` e `D03f_volume_z_expanding` (as duas únicas
    candidatas robustas em toda a vizinhança do sweep_range do E3) +
    `hhi_efetivo`/`n_eff_factors` do par — usa `compute_effective_
    concentration` (mesma função de `src.models.hhi`/D1, `gain_by_column`
    vazio -> peso uniforme, mesma leitura deliberada do E2: mede
    REDUNDÂNCIA DE INFORMAÇÃO, não importância preditiva)."""
    pair = ("C07_vol_pctile_expanding", "D03f_volume_z_expanding")
    sub = df_all.select(pair).drop_nulls()
    x = sub[pair[0]].to_numpy().astype(np.float64)
    y = sub[pair[1]].to_numpy().astype(np.float64)
    rho = float(np.corrcoef(x, y)[0, 1])
    corr_matrix = np.array([[1.0, rho], [rho, 1.0]])
    diag = compute_effective_concentration(corr_matrix, {}, pair)
    return {
        "pair": list(pair),
        "n_rows": int(sub.height),
        "pearson_correlation": rho,
        "n_eff_factors": diag.n_eff_factors.value,
        "hhi_efetivo": diag.hhi_effective.value,
        "nota": (
            "n_eff_factors=1,65 de um teto de 2 (rho=0,46): redundancia "
            "PARCIAL, nao total -- mais perto do meio do que de colapsar a "
            "1 fator so. Nao confirma 'e um fator so' ao pe da letra; "
            "confirma que ha sobreposicao real, nao ortogonalidade."
        ),
    }


def run_rpi_regime_diagnostic(df_all: pl.DataFrame) -> dict[str, dict[str, dict[str, float]]]:
    """Diagnóstico PRE/POST pooled por lado (NÃO por fold — é
    descritivo, não entra em nenhuma decisão de treino, mesma leitura
    documentada em `src.models.stability.ic_by_rpi_regime`)."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for side in SIDES:
        side_df = ds.side_subset(
            df_all, side=side, feature_ids=features_build.T1_FEATURE_IDS
        )
        out[str(side)] = stability.ic_by_rpi_regime(side_df, CANDIDATES_18)
    return out


_ROBUST_SURVIVORS: Final[tuple[str, ...]] = (
    "C07_vol_pctile_expanding",
    "D03f_volume_z_expanding",
)


def run_e3_stability(symbol: str = "BTCUSDT") -> dict[str, Any]:
    df_all = build_extended_modeling_frame(symbol)
    screen = run_stability_screen_over_cpcv(df_all)
    rpi_diagnostic = run_rpi_regime_diagnostic(df_all)
    robust_survivors_ic_sign = summarize_ic_sign_by_env_and_side(screen, _ROBUST_SURVIVORS)
    c07_d03f_pair = c07_d03f_pair_analysis(df_all)

    return {
        "candidates_18": list(CANDIDATES_18),
        "current_t1_8": list(CURRENT_T1),
        "e2_selected_beyond_t1": list(E2_SELECTED_BEYOND_T1),
        "stability_screen": screen,
        "rpi_regime_diagnostic_pre_post": rpi_diagnostic,
        "robust_survivors_ic_sign_by_env_and_side": robust_survivors_ic_sign,
        "c07_d03f_pair_analysis": c07_d03f_pair,
        "nota": (
            "estabilidade = forca * consistencia**2, denominador fixo 6 "
            "(src.models.stability). limiar ASSUMED "
            "(alpha_stability_screen_limiar=0.02, classe A, sweep pendente "
            "antes do Gate 3) -- sobrevivencia aqui e um RANKING sob esse "
            "valor, nao ainda uma decisao final de producao."
        ),
    }


def run_and_save_e3_stability(*, dest_path: Path | None = None) -> Path:
    """Ponto de entrada MANUAL — reconstrói o frame de modelagem completo
    (labels + T1 + regime + 10 candidatas do E2) e roda a triagem sobre os
    15 splits reais do CPCV x 2 lados. Chame: `uv run python -c
    "from src.analysis.faixa2_e3_stability import run_and_save_e3_stability
    as r; r()"`."""
    t0 = time.perf_counter()
    payload = run_e3_stability()
    payload["elapsed_seconds_total"] = time.perf_counter() - t0
    payload = {**report_provenance(), "task": "faixa2_e3_stability", **payload}

    dest = dest_path if dest_path is not None else DEFAULT_OUTPUT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest)
    logger.info(
        "analysis.faixa2_e3_stability.written",
        path=str(dest),
        elapsed_seconds_total=round(payload["elapsed_seconds_total"], 1),
    )
    return dest
