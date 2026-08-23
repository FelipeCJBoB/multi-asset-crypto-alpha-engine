"""Faixa 1.6 — reconciliação de medições e correções (§ prompt "Faixa 1.6",
2026-08-09). STEP 0 comprova as 5 [HIPÓTESE]; Blocos 1/2/5 são DESCOBERTA
(medem, não concluem — claim: detecção); Bloco 3 é CORREÇÃO real de código
(o fator ×2 do orçamento não é uma leitura alternativa legítima, é um erro
de interpretação propagado por citação — ver `src.analysis.tau_diagnostics`
e `src.analysis.faixa1_5_prerequisites`); Bloco 4 é DESCOBERTA com UMA
alteração de código medida (variante experimental, `n_lifetime += 1`).

**Correções feitas ANTES deste módulo rodar (não por ele) — Blocos 2 e 3
editam `src.analysis.faixa1_5_prerequisites` diretamente, não este
arquivo:**

1. Bloco 3 — `src.analysis.tau_diagnostics` e `src.analysis.
   faixa1_5_prerequisites::fee_budget_sweep` tinham um fator `×2.0` ("2
   lados") no orçamento de fees implicado, sem base na derivação literal
   de `PRD_V3_2_UNIFICADO.md:95-101` (§0.2 R3) — removido dos dois sites,
   `config/constants.yaml::fee_budget_is_per_side` registra a constante
   que antes só existia implícita em código.
2. Bloco 2 Fase A — `src.analysis.faixa1_5_prerequisites::path_dispersion`
   media `threshold_effective_confidence_quantile` sobre a população
   ERRADA (sinais já selecionados, `side_hat != 0` — quantil de um
   quantil) — corrigido para usar todo bar OOF scored do path.

`experiments/faixa1_5_prerequisites.json` já foi reemitido com as duas
correções antes deste módulo existir — este módulo REPORTA essas
correções (Bloco 2/Bloco 3 abaixo são funções de RELATO, não de
recorreção) e faz o trabalho NOVO (Blocos 1/4/5).

**Reuso, não reimplementação.** `src.analysis.faixa1_5_prerequisites`
(fold_to_path_map, build_realized_trades, stratified_headlines,
_hhi_by_fold_side, load_predictions), `src.models.alpha` (run_all_folds,
assemble_predictions_table — com o parâmetro NOVO `unforce_features_by_
side`, aditivo, default `None`, produção intocada), `src.models.pipeline`
(write_predictions_atomic, write_all_fold_diagnostics — mesmos writers,
`model_id` diferente), `src.models.decomposition.decompose`,
`src.models.backtest_lite` (span_seconds, sharpe_naive)."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from scipy.stats import spearmanr

from src.core.provenance import report_provenance
from src.data.resample import step_ms
from src.models import alpha, backtest_lite, decomposition, pipeline
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models._paths import models_diagnostics_symbol_tf_dir, predictions_symbol_tf_dir
from src.validation import cpcv

from . import faixa1_5_prerequisites as f15

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "faixa1_6_reconciliation.json"

_E02F_FEATURE = "E02f_funding_z_expanding"
_STRUCTURAL_REGIMES: tuple[str, ...] = ("R1", "R2", "R3", "R4")
_SIDE_LABEL_BY_HAT: dict[int, str] = {1: "long", -1: "short"}

# Mínimo de observações válidas para Spearman fazer sentido — mesma
# constante de `src.models.monotonic._MIN_OBS_PER_ENV`/
# `src.validation.leakage._MIN_OBS_CORRELATION_SCAN`, reusada aqui pela
# mesma categoria de decisão (mínimo matemático, não parâmetro de
# domínio).
_MIN_OBS_IC = 5

VARIANT_MODEL_ID_E02F_SHORT_UNFORCED = "alpha_c1_e02f_short_unforced_v1"

# T0 (SPRINT_LOG.md, commit c1ca0ae) — variante ANTERIOR a E02f ter
# restrição forçada nos dois lados. Não está mais persistida em disco
# (substituída por `alpha_c1_v1`, mesmo model_id) — citada aqui como
# constante de referência histórica (fato sobre um artefato passado, não
# parâmetro de domínio a varrer — não entra em constants.yaml pelo mesmo
# motivo que um número de commit não entra).
_PRE_T0_DIRECTIONAL_SHARPE_POOLED = 0.194  # noqa: magic-number
_POST_T0_DIRECTIONAL_SHARPE_POOLED_DOCUMENTED = 0.879  # noqa: magic-number


# ============================================================================
# STEP 0 — verificação de premissas [HIPÓTESE] (leitura de contrato, não
# medição — nenhum número novo é computado aqui).
# ============================================================================


def verify_step0_premises() -> dict[str, Any]:
    """Comprova as 5 [HIPÓTESE] do prompt Faixa 1.6. A primeira (mesmo
    alvo) é bloqueante para o Bloco 1 — CONFIRMADA, então o Bloco 1
    prossegue. Um sexto fator, fora da lista original, foi descoberto
    durante a verificação e é reportado aqui como candidato adicional
    para o Bloco 1 (não substitui nenhuma das 4 hipóteses de mecanismo
    pedidas — soma-se a elas)."""
    return {
        "h1_mesmo_alvo": {
            "confirmado": True,
            "bloqueante_para_bloco1": True,
            "evidencia": (
                "src/models/monotonic.py::compute_ic_by_env tem default "
                "target_col='ret_net'; src/analysis/attribution.py::"
                "ic_by_regime (docstring): 'IC de Spearman entre cada "
                "feature ... e ret_net'. As duas medições comparam contra "
                "a MESMA coluna — Bloco 1 prossegue."
            ),
        },
        "h2_mesma_definicao_e_janela_e02f": {
            "confirmado": True,
            "evidencia": (
                "Os dois caminhos leem a coluna 'E02f_funding_z_"
                "expanding' direto de src.models.dataset."
                "build_modeling_frame().data (calibration_diagnostics.py "
                "linha 'regimes = mf.data.select([...])'; "
                "faixa1_5_prerequisites.py usa mf_data diretamente) — "
                "nenhum dos dois recalcula a feature nem aplica janela "
                "própria."
            ),
        },
        "h3_tau_por_fold": {
            "confirmado": True,
            "evidencia": (
                "src/models/alpha.py::fit_side_model — "
                "'tau = float(np.quantile(calibrated_train_all, 1.0 - "
                "target_signal_rate))', onde calibrated_train_all vem de "
                "train_side_df, argumento do PRÓPRIO fold (run_fold "
                "chama fit_side_model uma vez por split). Não há tau "
                "global/constante."
            ),
        },
        "h4_forcada_separavel_por_lado": {
            "confirmado": True,
            "evidencia": (
                "_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE já é "
                "dict[str, dict[int, int]] — estruturalmente separável "
                "por lado. Implementado via parâmetro ADITIVO "
                "unforce_features_by_side (default None em toda a "
                "cadeia screen_monotone_constraints -> fit_side_model -> "
                "run_fold -> run_all_folds), sem mutar "
                "_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE nem qualquer outro "
                "ponto do desenho de produção — "
                "src.models.pipeline.run_layer1_sprint nunca passa esse "
                "argumento, então alpha_c1_v1/alpha_c0_baseline_v1 saem "
                "bit-a-bit idênticos."
            ),
        },
        "h5_mapeamento_fold_path_existe": {
            "confirmado": True,
            "evidencia": (
                "src/validation/cpcv.py::CPCVSplit.path_id — já "
                "consumido por src/analysis/faixa1_5_prerequisites.py::"
                "fold_to_path_map, reusado sem alteração."
            ),
        },
        "mecanismo_adicional_descoberto_fora_da_lista_original": {
            "nome": "mistura_de_lado_no_pooled",
            "descricao": (
                "src/analysis/calibration_diagnostics.py::"
                "congruent_incongruent_subsets chama attr.ic_by_regime "
                "UMA vez sobre 'predictions' inteiro (join por "
                "(t0, side_hat==side) sem filtrar side_hat, isto é, long "
                "E short misturados numa MESMA correlação de Spearman "
                "por regime) e reusa o MESMO resultado pooled nas duas "
                "classificações congruente/incongruente (long e short). "
                "O in-fold (src/models/monotonic.py::"
                "screen_monotone_constraints) é SEMPRE separado por "
                "lado — recebe `side` explícito, roda uma vez por lado, "
                "nunca mistura as duas populações. Como o sinal "
                "econômico forçado de E02f é OPOSTO por lado (-1 long, "
                "+1 short), misturar as duas populações numa correlação "
                "é um mecanismo plausível de inversão de sinal "
                "independente de qualquer relação real por lado — "
                "testado explicitamente como candidato (v) no Bloco 1, "
                "'side_mixing'."
            ),
        },
    }


# ============================================================================
# Bloco 1 — reconciliação do IC pooled vs in-fold de E02f (DESCOBERTA).
# ============================================================================


def _spearman_ic(x: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    mask = np.isfinite(x) & np.isfinite(y)
    n = int(mask.sum())
    if n < _MIN_OBS_IC or np.std(x[mask]) == 0.0 or np.std(y[mask]) == 0.0:
        return float("nan"), n
    rho, _p = spearmanr(x[mask], y[mask])
    return (float(rho) if np.isfinite(rho) else float("nan")), n


def _ic_by_regime(
    df: pl.DataFrame, *, feature_col: str = _E02F_FEATURE, target_col: str = "ret_net"
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for regime in _STRUCTURAL_REGIMES:
        sub = df.filter(pl.col("regime") == regime) if df.height else df
        x = sub[feature_col].to_numpy().astype(np.float64) if sub.height else np.array([])
        y = sub[target_col].to_numpy().astype(np.float64) if sub.height else np.array([])
        rho, n = _spearman_ic(x, y)
        out[regime] = {"rho": rho, "n": n}
    return out


def _weighted_range_trend(ic_by_regime: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Média ponderada por n dentro de RANGE (R1+R2) e TREND (R3+R4) —
    mesma partição de `src.models.environments.RANGE_REGIMES`/
    `TREND_REGIMES`."""

    def _weighted(regimes: tuple[str, ...]) -> float:
        total_n = sum(
            ic_by_regime[r]["n"] for r in regimes if math.isfinite(ic_by_regime[r]["rho"])
        )
        if total_n == 0:
            return float("nan")
        return float(
            sum(
                ic_by_regime[r]["rho"] * ic_by_regime[r]["n"]
                for r in regimes
                if math.isfinite(ic_by_regime[r]["rho"])
            )
            / total_n
        )

    return {"RANGE": _weighted(("R1", "R2")), "TREND": _weighted(("R3", "R4"))}


def _build_oof_population(
    predictions: pl.DataFrame, mf_data: pl.DataFrame, *, side_filter: int | None
) -> pl.DataFrame:
    """OOF, filled, `side_hat != 0` (misturado se `side_filter=None`,
    senão só aquele lado) — mesma semântica de junção que
    `src.analysis.attribution.ic_by_regime` documenta (join por
    `(t0, side_hat == side)`), reimplementada aqui como DataFrame
    intermediário reusável — `ic_by_regime` não expõe a população
    intermediária, só o IC já agregado, e o Bloco 1 precisa da população
    em 3 variantes (mista/long/short)."""
    preds = predictions.filter(pl.col("is_oof") & (pl.col("side_hat") != 0))
    if side_filter is not None:
        preds = preds.filter(pl.col("side_hat") == side_filter)
    preds = preds.select("t0", "fold_id", "side_hat")
    mf_small = mf_data.select(
        ["t0", "side", "barrier_hit", "ret_net", "regime", _E02F_FEATURE]
    ).with_columns(pl.col("barrier_hit").cast(pl.Utf8))
    joined = preds.join(mf_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner")
    return joined.filter(pl.col("barrier_hit") != "NOFILL")


def _train_side_per_fold(
    mf_data: pl.DataFrame, splits: tuple[cpcv.CPCVSplit, ...], *, side: int
) -> dict[int, pl.DataFrame]:
    out: dict[int, pl.DataFrame] = {}
    for split in splits:
        train_bars = mf_data[split.train_idx]
        out[split.split_id] = ds.side_subset(train_bars, side=side)
    return out


def _pooled_concat(by_fold: dict[int, pl.DataFrame]) -> pl.DataFrame:
    frames = [df for df in by_fold.values() if df.height]
    return pl.concat(frames, how="vertical") if frames else pl.DataFrame(schema=[])


def _mean_of_folds_by_regime(
    by_fold_ic: dict[int, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for regime in _STRUCTURAL_REGIMES:
        vals = [v[regime]["rho"] for v in by_fold_ic.values() if math.isfinite(v[regime]["rho"])]
        out[regime] = {
            "mean_rho": float(np.mean(vals)) if vals else float("nan"),
            "n_folds_used": len(vals),
        }
    return out


def _split_folds_by_median_frac_r2(
    train_long_by_fold: dict[int, pl.DataFrame],
    ic_train_long_by_fold: dict[int, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Partição candidata pro `simpson_partition`: divide os 15 folds em
    dois grupos pela mediana da fração de R2 dentro de RANGE (R1+R2) do
    TREINO daquele fold — reproduz (ou não) a inversão RANGE se a
    composição de fold for o mecanismo dominante."""
    frac_r2: dict[int, float] = {}
    for fid, df in train_long_by_fold.items():
        n_r1 = df.filter(pl.col("regime") == "R1").height
        n_r2 = df.filter(pl.col("regime") == "R2").height
        frac_r2[fid] = n_r2 / (n_r1 + n_r2) if (n_r1 + n_r2) > 0 else float("nan")

    valid = {fid: v for fid, v in frac_r2.items() if math.isfinite(v)}
    if len(valid) < 4:
        return {"aplicavel": False, "motivo": "menos de 4 folds com fração de R2 válida"}
    median = float(np.median(list(valid.values())))
    low_group = [fid for fid, v in valid.items() if v <= median]
    high_group = [fid for fid, v in valid.items() if v > median]

    def _group_range_ic(fold_ids: list[int]) -> float:
        vals = [
            _weighted_range_trend(ic_train_long_by_fold[fid])["RANGE"]
            for fid in fold_ids
            if math.isfinite(_weighted_range_trend(ic_train_long_by_fold[fid])["RANGE"])
        ]
        return float(np.mean(vals)) if vals else float("nan")

    return {
        "aplicavel": True,
        "variavel_particao": "fracao_r2_dentro_de_range_no_treino_do_fold",
        "mediana": median,
        "grupo_baixo_fracao_r2": {
            "fold_ids": low_group,
            "range_ic_medio": _group_range_ic(low_group),
        },
        "grupo_alto_fracao_r2": {
            "fold_ids": high_group,
            "range_ic_medio": _group_range_ic(high_group),
        },
        "reproduz_inversao": (
            math.isfinite(_group_range_ic(low_group))
            and math.isfinite(_group_range_ic(high_group))
            and (_group_range_ic(low_group) > 0) != (_group_range_ic(high_group) > 0)
        ),
    }


def reconcile_e02f_ic(
    predictions: pl.DataFrame, mf_data: pl.DataFrame, splits: tuple[cpcv.CPCVSplit, ...]
) -> dict[str, Any]:
    """Bloco 1 — DESCOBERTA, claim de detecção. Pipeline ÚNICO
    (`_ic_by_regime`/`_spearman_ic`), variando SOMENTE população/
    agregação/lado — nunca o alvo (`ret_net`) nem a definição de E02f.
    NÃO decide qual medição é autoritativa (B06 governa o USO da tabela
    de IC, não a medição em si — CLAUDE.md)."""
    oof_mixed = _build_oof_population(predictions, mf_data, side_filter=None)
    oof_long = _build_oof_population(predictions, mf_data, side_filter=1)
    oof_short = _build_oof_population(predictions, mf_data, side_filter=-1)

    ic_oof_mixed = _ic_by_regime(oof_mixed)
    ic_oof_long = _ic_by_regime(oof_long)
    ic_oof_short = _ic_by_regime(oof_short)

    reproduction_check_vs_persisted = None
    calib_path = EXPERIMENTS_DIR / "faixa1_calibration_diagnostic.json"
    if calib_path.exists():
        persisted = orjson.loads(calib_path.read_bytes())
        persisted_ic = persisted.get("constraint_congruent_subset", {}).get("e02f_ic_by_regime")
        if persisted_ic:
            reproduction_check_vs_persisted = {
                regime: {
                    "persisted_ic_value": persisted_ic.get(regime, {}).get("ic_value"),
                    "persisted_ic_n": persisted_ic.get(regime, {}).get("ic_n"),
                    "recomputado_oof_mixed_rho": ic_oof_mixed[regime]["rho"],
                    "recomputado_oof_mixed_n": ic_oof_mixed[regime]["n"],
                }
                for regime in _STRUCTURAL_REGIMES
            }

    train_long_by_fold = _train_side_per_fold(mf_data, splits, side=1)
    ic_train_long_by_fold = {fid: _ic_by_regime(df) for fid, df in train_long_by_fold.items()}
    ic_train_long_pooled_concat = _ic_by_regime(_pooled_concat(train_long_by_fold))
    ic_train_long_mean_of_folds = _mean_of_folds_by_regime(ic_train_long_by_fold)

    train_short_by_fold = _train_side_per_fold(mf_data, splits, side=-1)
    ic_train_short_by_fold = {fid: _ic_by_regime(df) for fid, df in train_short_by_fold.items()}

    oof_long_by_fold: dict[int, pl.DataFrame] = {
        int(fid): oof_long.filter(pl.col("fold_id") == fid)
        for fid in sorted(oof_long["fold_id"].unique().to_list())
    }
    ic_oof_long_by_fold = {fid: _ic_by_regime(df) for fid, df in oof_long_by_fold.items()}
    ic_oof_long_mean_of_folds = _mean_of_folds_by_regime(ic_oof_long_by_fold)

    by_fold_contribution = [
        {"fold_id": fid, "ic_by_regime_train_long": ic_train_long_by_fold[fid]}
        for fid in sorted(ic_train_long_by_fold.keys())
    ]

    # (i) composição de fold — Spearman(IC RANGE do fold, fração de R2
    # dentro de RANGE no treino daquele fold), n=15.
    range_ic_per_fold: list[float] = []
    frac_r2_per_fold: list[float] = []
    for fid, df in train_long_by_fold.items():
        range_w = _weighted_range_trend(ic_train_long_by_fold[fid])["RANGE"]
        n_r1 = df.filter(pl.col("regime") == "R1").height
        n_r2 = df.filter(pl.col("regime") == "R2").height
        frac_r2 = n_r2 / (n_r1 + n_r2) if (n_r1 + n_r2) > 0 else float("nan")
        if math.isfinite(range_w) and math.isfinite(frac_r2):
            range_ic_per_fold.append(range_w)
            frac_r2_per_fold.append(frac_r2)
    if len(range_ic_per_fold) >= 3:
        rho_fc, p_fc = spearmanr(range_ic_per_fold, frac_r2_per_fold)
        fold_composition: dict[str, Any] = {
            "rho": float(rho_fc),
            "p": float(p_fc),
            "n_folds": len(range_ic_per_fold),
            "interpretacao_literal": (
                "Spearman(IC ponderado de RANGE do fold, fracao de R2 "
                "dentro de RANGE no treino do fold) -- rho alto sugere "
                "que a composicao R1 vs R2 do treino explica parte da "
                "dispersao do IC RANGE entre folds"
            ),
        }
    else:
        fold_composition = {
            "rho": float("nan"),
            "p": float("nan"),
            "n_folds": len(range_ic_per_fold),
        }

    # (ii) deslocamento de nível — média/desvio de E02f e de ret_net, por
    # regime, OOF-long vs treino-long pooled.
    def _level_stats(df: pl.DataFrame) -> dict[str, Any]:
        if df.height == 0:
            return {
                "mean_e02f": float("nan"),
                "std_e02f": float("nan"),
                "mean_ret_net": float("nan"),
                "std_ret_net": float("nan"),
                "n": 0,
            }
        e = df[_E02F_FEATURE].to_numpy().astype(np.float64)
        r = df["ret_net"].to_numpy().astype(np.float64)
        return {
            "mean_e02f": float(np.nanmean(e)),
            "std_e02f": float(np.nanstd(e)),
            "mean_ret_net": float(np.nanmean(r)),
            "std_ret_net": float(np.nanstd(r)),
            "n": int(df.height),
        }

    train_long_pooled_df = _pooled_concat(train_long_by_fold)
    level_shift = {
        regime: {
            "oof_long": _level_stats(oof_long.filter(pl.col("regime") == regime)),
            "train_long_pooled": _level_stats(
                train_long_pooled_df.filter(pl.col("regime") == regime)
                if train_long_pooled_df.height
                else train_long_pooled_df
            ),
        }
        for regime in _STRUCTURAL_REGIMES
    }

    # (iii) OOF vs treino — MESMO fold, MESMO lado (long), só muda a
    # fonte de dado (teste realizado vs treino in-fold).
    empty_regime_ic = {r: {"rho": float("nan"), "n": 0} for r in _STRUCTURAL_REGIMES}
    oof_vs_train = {
        str(fid): {
            "train": ic_train_long_by_fold[fid],
            "oof": ic_oof_long_by_fold.get(fid, empty_regime_ic),
        }
        for fid in sorted(ic_train_long_by_fold.keys())
    }

    # (iv) ponderação — pooled-concat (n-ponderado implicitamente) vs
    # média-simples-dos-folds (cada fold pesa igual), treino e OOF, lado long.
    weighting = {
        "train_long": {
            "pooled_concat_by_regime": ic_train_long_pooled_concat,
            "mean_of_folds_by_regime": ic_train_long_mean_of_folds,
        },
        "oof_long": {
            "pooled_concat_by_regime": ic_oof_long,
            "mean_of_folds_by_regime": ic_oof_long_mean_of_folds,
        },
    }

    # (v) mistura de lado — mecanismo adicional descoberto no STEP 0,
    # fora da lista original de 4.
    side_mixing_mecanismo_adicional_nao_pedido_na_lista_original = {
        "oof_mixed_side_by_regime": ic_oof_mixed,
        "oof_long_only_by_regime": ic_oof_long,
        "oof_short_only_by_regime": ic_oof_short,
        "oof_mixed_range_trend_weighted": _weighted_range_trend(ic_oof_mixed),
        "oof_long_only_range_trend_weighted": _weighted_range_trend(ic_oof_long),
        "oof_short_only_range_trend_weighted": _weighted_range_trend(ic_oof_short),
    }

    simpson_partition = {
        "particao_lado_oof_mixed_vs_side_separated": {
            "descricao": (
                "mistura long+short num só Spearman por regime (pooled "
                "atual, ic_by_regime de producao) vs long sozinho vs "
                "short sozinho, todos OOF"
            ),
            "mixed": _weighted_range_trend(ic_oof_mixed),
            "long_only": _weighted_range_trend(ic_oof_long),
            "short_only": _weighted_range_trend(ic_oof_short),
        },
        "particao_fold_por_mediana_fracao_r2_no_treino": _split_folds_by_median_frac_r2(
            train_long_by_fold, ic_train_long_by_fold
        ),
    }

    return {
        "same_target_verified": True,
        "same_target_verified_evidence": "ambos usam ret_net -- ver step0_premises.h1_mesmo_alvo",
        "reproduction_check_vs_persisted": reproduction_check_vs_persisted,
        "oof_mixed_side_ic_by_regime": ic_oof_mixed,
        "oof_long_only_ic_by_regime": ic_oof_long,
        "oof_short_only_ic_by_regime": ic_oof_short,
        "train_infold_long_ic_by_fold": {str(k): v for k, v in ic_train_long_by_fold.items()},
        "train_infold_short_ic_by_fold": {str(k): v for k, v in ic_train_short_by_fold.items()},
        "by_fold_contribution": by_fold_contribution,
        "candidate_mechanisms": {
            "fold_composition": fold_composition,
            "level_shift": level_shift,
            "oof_vs_train": oof_vs_train,
            "weighting": weighting,
            "side_mixing_mecanismo_adicional_nao_pedido_na_lista_original": (
                side_mixing_mecanismo_adicional_nao_pedido_na_lista_original
            ),
        },
        "simpson_partition": simpson_partition,
    }


# ============================================================================
# Bloco 2 — relato da correção do threshold (Fase A já rodou e corrigiu o
# código em src.analysis.faixa1_5_prerequisites; Fase B NÃO roda).
# ============================================================================

# Valores TEXTUAIS congelados do artefato buggy (experiments/faixa1_5_
# prerequisites.json antes da correção, ver git log) -- fato sobre um
# artefato passado, não parâmetro de domínio; não entra em constants.yaml
# pelo mesmo motivo que um hash de commit não entra.
_THRESHOLD_VALUES_ANTES_DA_CORRECAO: dict[str, float] = {
    "0": 1.0000000000000000,
    "1": 0.7795116305351257,  # noqa: magic-number
    "2": 0.8151728510856628,  # noqa: magic-number
    "3": 0.7429246902465820,  # noqa: magic-number
    "4": 0.9646622538566589,  # noqa: magic-number
}


def report_bloco2_threshold_sanity() -> dict[str, Any]:
    """Bloco 2 — Fase A (verificação de sanidade). PAROU na Fase A: bug
    de medição confirmado (quantil-de-um-quantil — ver docstring de
    `src.analysis.faixa1_5_prerequisites.path_dispersion`) e já
    corrigido diretamente naquele módulo antes deste rodar. Fase B
    (regime do treino x quantil efetivo) NÃO executa — instrução
    explícita do prompt: 'Se for defeito de medição, corrigir a métrica
    e reemitir os 5 valores. PARAR o Bloco 2 aqui e reportar.'"""
    f15_path = EXPERIMENTS_DIR / "faixa1_5_prerequisites.json"
    valores_depois: dict[str, float] | None = None
    if f15_path.exists():
        payload = orjson.loads(f15_path.read_bytes())
        per_path = payload.get("path_dispersion", {}).get("per_path", {})
        valores_depois = {
            pid: entry.get("threshold_effective_confidence_quantile")
            for pid, entry in per_path.items()
        }

    return {
        "fase_a_metric_valid": False,
        "fase_a_finding": (
            "threshold_effective_confidence_quantile tomava o quantil "
            "(1 - target_signal_rate) sobre a população JÁ SELECIONADA "
            "(realized: side_hat != 0, ou seja, toda linha ali já passou "
            "confidence > tau por construção) em vez da população "
            "COMPLETA de bars scored no path (predictions, is_oof=True, "
            "sem filtrar side_hat) — quantil-de-um-quantil. Path 0 "
            "mediu exatamente 1,0000 com 7.162 trades preenchidos: um "
            "threshold no máximo da distribuição deveria produzir ZERO "
            "trades, não 7.162 — contradição que expôs o defeito. "
            "Verificado empiricamente antes de qualquer edição: a "
            "versão corrigida cai numa faixa estreita (0,55-0,60) em "
            "vez de variar 0,74-1,00."
        ),
        "corrigido_em": (
            "src/analysis/faixa1_5_prerequisites.py::path_dispersion "
            "(agora recebe `predictions` como parâmetro obrigatório e "
            "usa a população completa de bars scored, is_oof=True, sem "
            "filtrar side_hat, para o quantil)"
        ),
        "valores_antes_da_correcao": _THRESHOLD_VALUES_ANTES_DA_CORRECAO,
        "valores_depois_da_correcao": valores_depois,
        "fase_b_executada": False,
        "fase_b_motivo_nao_executada": (
            "Fase A encontrou defeito de medição -- instrução explícita "
            "do prompt: 'PARAR o Bloco 2 aqui e reportar'"
        ),
    }


# ============================================================================
# Bloco 3 — relato da correção do fator x2 (já aplicada em
# src.analysis.tau_diagnostics e src.analysis.faixa1_5_prerequisites,
# config/constants.yaml::fee_budget_is_per_side).
# ============================================================================


def report_bloco3_fee_budget_correction() -> dict[str, Any]:
    """Bloco 3 — CONSTRUTIVO. A correção em si (remoção do fator x2, nova
    constante, testes de regressão) já foi feita antes deste módulo
    existir — esta função só reporta o antes/depois lendo o artefato já
    reemitido, para o JSON final ter os 5 grupos exigidos pelo Bloco 6."""
    f15_path = EXPERIMENTS_DIR / "faixa1_5_prerequisites.json"
    ponto_central_depois = None
    if f15_path.exists():
        payload = orjson.loads(f15_path.read_bytes())
        ponto_central_depois = payload.get("fee_budget_sweep", {}).get("points", {}).get("0.030")

    return {
        "sites_corrigidos": [
            "src/analysis/tau_diagnostics.py (introduziu o fator x2.0 originalmente)",
            "src/analysis/faixa1_5_prerequisites.py::fee_budget_sweep (herdou por citação)",
        ],
        "constante_nova": (
            "config/constants.yaml::fee_budget_is_per_side "
            "(value: false, provenance DERIVED, "
            "derived_from: [fee_budget_monthly, target_signal_rate])"
        ),
        # fato sobre o artefato buggy anterior (0,0189 * 2.0 * 35064,
        # ver git log) -- não parâmetro de domínio.
        "implied_trades_per_year_ponto_central_antes": 1325.4192,  # noqa: magic-number
        "implied_trades_per_year_ponto_central_depois": (
            ponto_central_depois.get("implied_trades_per_year") if ponto_central_depois else None
        ),
        "teste_de_regressao": [
            "tests/unit/test_analysis_tau_diagnostics.py::test_alvo_nominal_nao_tem_fator_de_lado",
            (
                "tests/unit/test_analysis_faixa1_5_prerequisites.py::"
                "test_fee_budget_sweep_no_ponto_central_scale_e_um "
                "(assert de desigualdade contra o valor com x2 adicionado)"
            ),
        ],
        "prd_e_sprint_log_atualizados": True,
    }


# ============================================================================
# Bloco 4 — variante do short sem restrição forçada de E02f. Retreino
# real via alpha.run_all_folds (unforce_features_by_side aditivo).
# n_lifetime += 1.
# ============================================================================


def _realized_all_sides(realized: pl.DataFrame) -> pl.DataFrame:
    return realized.filter(pl.col("barrier_hit") != "NOFILL")


def _sharpe_by_path_from_realized(realized: pl.DataFrame) -> dict[int, float]:
    """Sharpe pooled (ambos os lados) por `path_id`, direto de um frame
    `realized` já construído (`f15.build_realized_trades`) — mesma
    definição de `src.models.backtest_lite.backtest_by_path`, mas
    operando sobre um DataFrame já materializado em vez de
    `list[FoldResult]` (não temos `FoldResult` para os modelos JÁ
    persistidos em disco, só predictions.parquet)."""
    out: dict[int, float] = {}
    for pid in sorted(realized["path_id"].unique().to_list()):
        filled = _realized_all_sides(realized.filter(pl.col("path_id") == pid))
        rets = filled["ret_net"].to_numpy().astype(np.float64)
        span = backtest_lite.span_seconds(filled["t0"]) if filled.height else 0.0
        sharpe, _tpy = backtest_lite.sharpe_naive(rets, span_seconds=span)
        out[int(pid)] = sharpe
    return out


def run_e02f_short_unforced_variant(
    *, symbol: str = ds.SYMBOL_DEFAULT, tf: str | None = None
) -> dict[str, Any]:
    """Bloco 4 — DESCOBERTA, com UMA alteração de código medida
    (`unforce_features_by_side={_E02F_FEATURE: frozenset({-1})}` — só o
    short; o long usa a MESMA `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` de
    sempre). Retreina os 15 folds (Camada 1, ambos os lados — os pesos
    do XGBoost de M_long/M_short são independentes, mas `side_hat =
    argmax(p_long, p_short)` acopla os dois na SELEÇÃO — não há como
    isolar só o short sem retreinar os dois). `n_lifetime += 1` — é uma
    variante NOVA de modelo (feature entra sem restrição forçada num
    lado), não uma correção de bug (Bloco 3) nem medição pós-hoc
    (Blocos 1/2/5).

    `tf` (AG-012, mesmo padrão sentinela de `src.models.pipeline.
    run_layer1_sprint`, AG-006) — `None` (default, o que `run_faixa1_6`
    e todo chamador/teste existente fazem hoje): `write_predictions_atomic`
    grava e as duas leituras de baseline (`f15.load_predictions` para
    `MODEL_ID_CAMADA1`/`MODEL_ID_CAMADA0`) lêem do caminho legado plano
    `PREDICTIONS_OUTPUT_DIR/alpha/{model_id}` — bit-exato com o
    comportamento anterior. `tf` explícito: as TRÊS operações de IO
    (a escrita da variante E as duas leituras de baseline) roteiam pelo
    layout chaveado `predictions_symbol_tf_dir(symbol, model_id, tf=tf)` —
    não só a escrita, porque `symbol` já é aceito de verdade por esta
    função (`mf = ds.build_modeling_frame(symbol=symbol)` abaixo já usa
    dado do símbolo pedido); se só a escrita fosse corrigida, um chamador
    futuro com `symbol` não-default compararia a variante daquele símbolo
    contra o baseline ERRADO (sempre `BTCUSDT`, lido do caminho legado
    plano, que `f15.load_predictions` não tem como distinguir por
    símbolo). `step_ms(tf)` valida cedo, antes do retreino caro dos 15
    folds x 2 lados.

    AG-016 (`audit/architecture_gaps_log.yaml`) — mesmo raciocínio acima,
    aplicado ao lado `diagnostics/` em vez de `predictions/`: as TRÊS
    operações equivalentes de IO de diagnóstico (`pipeline.
    write_all_fold_diagnostics` da variante E as duas leituras de baseline
    via `f15._hhi_by_fold_side` para `VARIANT_MODEL_ID_E02F_SHORT_UNFORCED`/
    `MODEL_ID_CAMADA1`) agora também roteiam por `tf`: `None` preserva o
    caminho legado plano `MODELS_DIR/{model_id}/diagnostics/` (AG-013,
    bit-exato, os arquivos já commitados nunca migram sozinhos); `tf`
    explícito roteia pelo layout chaveado `models_diagnostics_symbol_tf_dir(
    symbol, model_id, tf=tf)`. Antes desta correção, a capacidade existia
    (AG-013) mas não estava fiada aqui — um `symbol` não-default com `tf`
    explícito já comparava as PREDICTIONS certas mas colidiria os
    DIAGNOSTICS de fold entre símbolos em `MODELS_DIR/{model_id}/
    diagnostics/` plano."""
    if tf is not None:
        step_ms(tf)  # UnsupportedTimeframeError cedo -- antes do treino caro abaixo
    mf = ds.build_modeling_frame(symbol=symbol)
    cpcv_result = cpcv.generate_splits(mf.data)
    splits = cpcv_result.splits
    fold_to_path = f15.fold_to_path_map(splits)

    hyper = alpha.LGBMHyperparams.from_constants()
    seed = int(load_constant("alpha_random_seed"))
    unforce = {_E02F_FEATURE: frozenset({-1})}

    logger.info(
        "analysis.faixa1_6.bloco4_variant_train_start",
        model_id=VARIANT_MODEL_ID_E02F_SHORT_UNFORCED,
    )
    variant_folds = alpha.run_all_folds(
        mf.data,
        splits,
        variant=alpha.VARIANT_CAMADA1,
        model_id=VARIANT_MODEL_ID_E02F_SHORT_UNFORCED,
        symbol=symbol,
        hyper=hyper,
        seed=seed,
        unforce_features_by_side=unforce,
    )
    # `tf=None` (default): SEM dest_dir -> caminho legado plano
    # `MODELS_DIR/{model_id}/diagnostics/`, bit-exato (AG-013 preserva os
    # arquivos já commitados). `tf` explícito: layout chaveado por
    # symbol/tf (AG-016) — mesma disciplina de `dest_dir_variant` abaixo
    # para `write_predictions_atomic`.
    dest_dir_diag_variant = (
        models_diagnostics_symbol_tf_dir(symbol, VARIANT_MODEL_ID_E02F_SHORT_UNFORCED, tf=tf)
        if tf is not None
        else None
    )
    pipeline.write_all_fold_diagnostics(
        variant_folds,
        model_id=VARIANT_MODEL_ID_E02F_SHORT_UNFORCED,
        hyper=hyper,
        dest_dir=dest_dir_diag_variant,
    )
    preds_variant = alpha.assemble_predictions_table(variant_folds)
    # `tf=None` (default): SEM dest_dir -> caminho legado plano, bit-exato
    # com o comportamento anterior a esta mudança. `tf` explícito: layout
    # chaveado por symbol/tf — mesma disciplina de `run_layer1_sprint`
    # (AG-006) para as TRÊS operações de IO desta função (ver docstring).
    dest_dir_variant = (
        predictions_symbol_tf_dir(symbol, VARIANT_MODEL_ID_E02F_SHORT_UNFORCED, tf=tf)
        if tf is not None
        else None
    )
    pipeline.write_predictions_atomic(
        preds_variant, VARIANT_MODEL_ID_E02F_SHORT_UNFORCED, dest_dir=dest_dir_variant
    )
    logger.info("analysis.faixa1_6.bloco4_variant_train_done", n_folds=len(variant_folds))

    realized_variant = f15.build_realized_trades(preds_variant, mf.data, fold_to_path)
    # Par simétrico de leitura de `dest_dir_diag_variant` acima -- mesmo
    # `model_id`/`symbol`/`tf`, o que `write_all_fold_diagnostics` acabou
    # de gravar.
    hhi_variant = f15._hhi_by_fold_side(
        model_id=VARIANT_MODEL_ID_E02F_SHORT_UNFORCED, dest_dir=dest_dir_diag_variant
    )
    headlines_variant = f15.stratified_headlines(realized_variant, hhi_variant)

    dest_dir_camada1 = (
        predictions_symbol_tf_dir(symbol, pipeline.MODEL_ID_CAMADA1, tf=tf)
        if tf is not None
        else None
    )
    preds_baseline = f15.load_predictions(
        model_id=pipeline.MODEL_ID_CAMADA1, dest_dir=dest_dir_camada1
    )
    realized_baseline = f15.build_realized_trades(preds_baseline, mf.data, fold_to_path)
    # `tf=None` (default): SEM dest_dir -> caminho legado plano, bit-exato.
    # `tf` explícito: layout chaveado por symbol/tf (AG-016) -- mesmo par
    # symbol/tf usado acima em `dest_dir_camada1` pra ler as predictions
    # deste mesmo baseline (`MODEL_ID_CAMADA1`), agora pro diagnostics.
    dest_dir_diag_camada1 = (
        models_diagnostics_symbol_tf_dir(symbol, pipeline.MODEL_ID_CAMADA1, tf=tf)
        if tf is not None
        else None
    )
    hhi_baseline = f15._hhi_by_fold_side(
        model_id=pipeline.MODEL_ID_CAMADA1, dest_dir=dest_dir_diag_camada1
    )
    headlines_baseline = f15.stratified_headlines(realized_baseline, hhi_baseline)

    dest_dir_camada0 = (
        predictions_symbol_tf_dir(symbol, pipeline.MODEL_ID_CAMADA0, tf=tf)
        if tf is not None
        else None
    )
    preds_camada0 = f15.load_predictions(
        model_id=pipeline.MODEL_ID_CAMADA0, dest_dir=dest_dir_camada0
    )
    realized_camada0 = f15.build_realized_trades(preds_camada0, mf.data, fold_to_path)

    variant_sharpe_by_path = _sharpe_by_path_from_realized(realized_variant)
    baseline_sharpe_by_path = _sharpe_by_path_from_realized(realized_baseline)
    camada0_sharpe_by_path = _sharpe_by_path_from_realized(realized_camada0)

    min_paths_required = int(load_constant("alpha_layer1_permanence_min_paths"))
    common_paths = sorted(set(variant_sharpe_by_path) & set(camada0_sharpe_by_path))
    n_better_variant = sum(
        1
        for pid in common_paths
        if math.isfinite(variant_sharpe_by_path[pid])
        and math.isfinite(camada0_sharpe_by_path[pid])
        and variant_sharpe_by_path[pid] >= camada0_sharpe_by_path[pid]
    )
    permanence_variant = {
        "n_paths_supera_camada0": n_better_variant,
        "n_paths_total": len(common_paths),
        "min_paths_required": min_paths_required,
        "permanence_pass": n_better_variant >= min_paths_required,
        "sharpe_by_path": {str(pid): variant_sharpe_by_path[pid] for pid in common_paths},
    }
    permanence_baseline_ref = {
        "sharpe_by_path": {str(pid): baseline_sharpe_by_path.get(pid) for pid in common_paths},
    }

    pooled_baseline = decomposition.decompose(
        _realized_all_sides(realized_baseline), source="faixa1_6::bloco4::baseline_c1_v1::pooled"
    )
    pooled_variant = decomposition.decompose(
        _realized_all_sides(realized_variant),
        source="faixa1_6::bloco4::variant_short_unforced::pooled",
    )

    # n de bars cujo side_hat MUDOU entre baseline e variante (evidência
    # do acoplamento via seleção argmax(p_long,p_short) mencionado acima
    # — long/short não têm pesos compartilhados, mas COMPETEM pela
    # mesma barra).
    join_cols = ["t0", "fold_id"]
    cmp = preds_baseline.select([*join_cols, "side_hat"]).join(
        preds_variant.select([*join_cols, "side_hat"]),
        on=join_cols,
        how="inner",
        suffix="_variant",
    )
    n_bars_side_flip = int((cmp["side_hat"] != cmp["side_hat_variant"]).sum())

    t0_attribution = {
        "pre_t0_directional_sharpe_pooled": _PRE_T0_DIRECTIONAL_SHARPE_POOLED,
        "pre_t0_source": (
            "docs/SPRINT_LOG.md, seção T0 (commit c1ca0ae) -- variante "
            "anterior a E02f ter restrição forçada nos dois lados não "
            "está mais persistida em disco (mesmo model_id alpha_c1_v1 "
            "foi substituído), não recalculada aqui"
        ),
        "post_t0_both_sides_forced_directional_sharpe_pooled": (
            pooled_baseline.directional_sharpe.value
        ),
        "post_t0_documented_reference": _POST_T0_DIRECTIONAL_SHARPE_POOLED_DOCUMENTED,
        "variant_short_unforced_directional_sharpe_pooled": pooled_variant.directional_sharpe.value,
        "n_bars_side_flip_vs_baseline": n_bars_side_flip,
        "caveat": (
            "M_long e M_short são XGBoost independentes (pesos não se "
            "acoplam), mas side_hat = argmax(p_long, p_short) acopla os "
            "dois NA SELEÇÃO — mudar a restrição do short pode mudar "
            "quais barras o LONG efetivamente 'ganha', então a "
            "diferença pooled não é uma decomposição aditiva limpa "
            "entre 'contribuição do long' e 'contribuição do short'. "
            "n_bars_side_flip_vs_baseline mede o tamanho desse "
            "acoplamento diretamente."
        ),
    }

    return {
        "n_lifetime_delta": 1,
        "variant_model_id": VARIANT_MODEL_ID_E02F_SHORT_UNFORCED,
        "unforce_features_by_side_usado": {"E02f_funding_z_expanding": ["short"]},
        "long_restriction_untouched": True,
        "headlines_baseline_alpha_c1_v1": headlines_baseline,
        "headlines_variant": headlines_variant,
        "permanence_variant_vs_camada0": permanence_variant,
        "permanence_baseline_vs_camada0_reference": permanence_baseline_ref,
        "t0_attribution": t0_attribution,
        "pooled_both_sides": {
            "baseline": {
                "total_sharpe": pooled_baseline.total_sharpe.value,
                "directional_sharpe": pooled_baseline.directional_sharpe.value,
                "n_trades": pooled_baseline.n_trades,
            },
            "variant": {
                "total_sharpe": pooled_variant.total_sharpe.value,
                "directional_sharpe": pooled_variant.directional_sharpe.value,
                "n_trades": pooled_variant.n_trades,
            },
        },
    }


# ============================================================================
# Bloco 5 — varredura pooled vs estratificado (DESCOBERTA, claim de
# detecção). Escopo DECLARADO (não é exaustivo sobre todo src/analysis,
# src/models, src/validation — ver docstring de `pooled_vs_stratified_
# inventory`).
# ============================================================================


def _hhi_dispersion_check() -> dict[str, Any]:
    """`hhi.mean_hhi`/`mean_hhi_effective` (UM número, pooled sobre os
    15 folds x 2 lados) vs `hhi.long_by_fold`/`short_by_fold`/
    `hhi_effective_*_by_fold` (já estratificados NO MESMO relatório) —
    zero recomputação, só comparação do que já está persistido."""
    report_path = EXPERIMENTS_DIR / "alpha_layer1_report.json"
    if not report_path.exists():
        return {"aplicavel": False, "motivo": f"{report_path} ausente"}
    report = orjson.loads(report_path.read_bytes())
    hhi = report.get("hhi", {})
    long_by_fold = hhi.get("hhi_effective_long_by_fold", [])
    short_by_fold = hhi.get("hhi_effective_short_by_fold", [])
    all_folds = [v for v in (long_by_fold + short_by_fold) if isinstance(v, (int, float))]
    if not all_folds:
        return {"aplicavel": False, "motivo": "hhi_effective_*_by_fold vazio"}
    pooled = hhi.get("mean_hhi_effective")
    lo, hi = min(all_folds), max(all_folds)
    divergencia_relativa = (hi - lo) / pooled if pooled else float("nan")
    return {
        "metrica": "hhi_effective (concentração de fatores de informação)",
        "pooled_mean": pooled,
        "by_fold_min": lo,
        "by_fold_max": hi,
        "divergencia_relativa": divergencia_relativa,
        "sign_flip": False,
        "nota": (
            "HHI é sempre >= 0 -- não há sign_flip possível; divergência "
            "aqui é dispersão de magnitude, não inversão"
        ),
    }


def _tau_ratio_dispersion_check() -> dict[str, Any]:
    """`tau_diagnostics.mean_ratio_*_to_target` (pooled, média sobre 5
    caminhos) vs `paths[].ratio_*_fill_to_target` (já estratificado por
    caminho, MESMO dataclass) — via re-execução barata de
    `tau_realization_diagnostic` (não retreina nada, só aritmética sobre
    `alpha_layer1_report.json` já em disco)."""
    from src.analysis import tau_diagnostics as tau
    from src.models.backtest_lite import DAYS_PER_YEAR

    report_path = EXPERIMENTS_DIR / "alpha_layer1_report.json"
    if not report_path.exists():
        return {"aplicavel": False, "motivo": f"{report_path} ausente"}
    report = orjson.loads(report_path.read_bytes())
    target_signal_rate = float(load_constant("target_signal_rate"))
    bars_per_year = DAYS_PER_YEAR * 24 * 4
    result = tau.tau_realization_diagnostic(
        report, target_signal_rate=target_signal_rate, bars_per_year=bars_per_year
    )
    ratios = [
        p.ratio_post_fill_to_target.value
        for p in result.paths
        if p.ratio_post_fill_to_target.valid
    ]
    if not ratios:
        return {"aplicavel": False, "motivo": "nenhum path com ratio_post_fill_to_target válido"}
    pooled = result.mean_ratio_post_fill_to_target.value
    lo, hi = min(ratios), max(ratios)
    divergencia_relativa = (hi - lo) / pooled if pooled else float("nan")
    return {
        "metrica": "ratio_post_fill_to_target (realizado/alvo nominal de tau)",
        "pooled_mean": pooled,
        "by_path_min": lo,
        "by_path_max": hi,
        "divergencia_relativa": divergencia_relativa,
        "sign_flip": False,
        "nota": "ratio é sempre >= 0 -- divergência aqui é dispersão de magnitude, não inversão",
    }


def _static_rule_regime_stratification(mf_data: pl.DataFrame) -> dict[str, Any]:
    """B3 (regra estática, long em R3/R4)/B5 (short permanente) —
    `baselines.py` só reporta o número POOLED (trades_per_year/
    sharpe_naive/mean_trade_ret sobre TODO o dataset). Recomputa
    estratificado por regime, mesma regra de filtro, NOVO (não existe
    em nenhum lugar do repo hoje)."""
    from src.models.baselines import run_b3_regime_only, run_b5_short_permanent

    out: dict[str, Any] = {}
    rules = {
        "b3_regime_only": (
            mf_data.filter(
                (pl.col("side") == 1)
                & pl.col("regime").is_in(["R3", "R4"])
                & (pl.col("A13_dist_ema48_atr") > 0.0)
                & pl.col("A13_dist_ema48_atr").is_not_null()
            ),
            run_b3_regime_only(mf_data),
        ),
        "b5_short_permanent": (
            mf_data.filter(pl.col("side") == -1),
            run_b5_short_permanent(mf_data),
        ),
    }
    for name, (trades, pooled_result) in rules.items():
        trades = trades.with_columns(pl.col("barrier_hit").cast(pl.Utf8))
        by_regime: dict[str, Any] = {}
        for regime in _STRUCTURAL_REGIMES:
            # filtra NOFILL -- mesma disciplina de `run_b3_regime_only`/
            # `run_b5_short_permanent` (fill_rate reportado à parte,
            # Sharpe/mean_trade_ret só sobre trades EXECUTADOS).
            sub = trades.filter((pl.col("regime") == regime) & (pl.col("barrier_hit") != "NOFILL"))
            rets = sub["ret_net"].to_numpy().astype(np.float64) if sub.height else np.array([])
            span = backtest_lite.span_seconds(sub["t0"]) if sub.height else 0.0
            sharpe, tpy = backtest_lite.sharpe_naive(rets, span_seconds=span)
            by_regime[regime] = {
                "n_trades_filled": int(sub.height),
                "sharpe_naive": sharpe,
                "trades_per_year": tpy,
                "mean_trade_ret": float(np.mean(rets)) if rets.size else float("nan"),
            }
        pooled_sharpe = pooled_result.sharpe_naive
        by_regime_sharpes = [
            v["sharpe_naive"] for v in by_regime.values() if math.isfinite(v["sharpe_naive"])
        ]
        sign_flip = bool(by_regime_sharpes) and any(
            math.isfinite(pooled_sharpe) and (s > 0) != (pooled_sharpe > 0)
            for s in by_regime_sharpes
        )
        divergencia_relativa = (
            (max(by_regime_sharpes) - min(by_regime_sharpes)) / abs(pooled_sharpe)
            if by_regime_sharpes and math.isfinite(pooled_sharpe) and pooled_sharpe != 0
            else float("nan")
        )
        out[name] = {
            "pooled_sharpe_naive": pooled_sharpe,
            "by_regime": by_regime,
            "sign_flip": sign_flip,
            "divergencia_relativa": divergencia_relativa,
        }
    return out


def _t1_feature_leakage_scan_by_regime(mf_data: pl.DataFrame) -> dict[str, Any]:
    """`leakage_report.json` (src.validation.leakage.scan_feature_target_
    correlation) reporta UM rho pooled por feature T1, sobre o dataset
    inteiro. Recomputa por regime (reusando `_ic_by_regime` deste
    módulo, que já é genérico em `feature_col`) para as 10 features T1
    — checa sign_flip além de E02f (que já sabemos que inverte)."""
    from src.features.build import T1_FEATURE_IDS
    from src.validation._paths import VALIDATION_REPORTS_DIR

    leakage_path = VALIDATION_REPORTS_DIR / "feature_leakage_scan_report.json"
    pooled_by_feature: dict[str, float] = {}
    if leakage_path.exists():
        payload = orjson.loads(leakage_path.read_bytes())
        for entry in payload.get("entries", payload.get("features", [])) or []:
            if isinstance(entry, dict) and "feature" in entry:
                pooled_by_feature[entry["feature"]] = float(
                    entry.get("spearman_rho", float("nan"))
                )

    out: dict[str, Any] = {}
    for feature in T1_FEATURE_IDS:
        by_regime = _ic_by_regime(mf_data, feature_col=feature, target_col="ret_net")
        rhos = [v["rho"] for v in by_regime.values() if math.isfinite(v["rho"])]
        sign_flip = len({(r > 0) for r in rhos}) > 1 if rhos else False
        pooled = pooled_by_feature.get(feature)
        out[feature] = {
            "pooled_rho_from_leakage_report": pooled,
            "by_regime": by_regime,
            "sign_flip_across_regimes": sign_flip,
        }
    return out


def pooled_vs_stratified_inventory(mf_data: pl.DataFrame) -> dict[str, Any]:
    """Bloco 5 — DESCOBERTA, claim de detecção. NÃO corrige nenhuma.

    **Escopo declarado (não exaustivo).** "Toda métrica agregada emitida
    por qualquer módulo em src/analysis, src/models, src/validation"
    tomado literalmente seria dezenas de números sem estratificação
    natural disponível (ex. percentis de baseline nulo, AUC de feature-
    shuffle). Escopo real desta varredura: métricas onde (a) já existe
    uma versão estratificada NO MESMO artefato pra comparar sem
    recomputar do zero, ou (b) uma estratificação natural (por regime)
    é barata de computar com as funções já existentes deste módulo/
    `src.models.baselines`/`src.validation.leakage`. Quatro itens,
    ordenados por divergência relativa decrescente ao final."""
    items: dict[str, Any] = {
        "hhi_effective_pooled_vs_by_fold": _hhi_dispersion_check(),
        "tau_ratio_pooled_vs_by_path": _tau_ratio_dispersion_check(),
        "baselines_b3_b5_pooled_vs_by_regime": _static_rule_regime_stratification(mf_data),
        "t1_features_leakage_scan_pooled_vs_by_regime": _t1_feature_leakage_scan_by_regime(mf_data),
    }

    ranking: list[dict[str, Any]] = []
    for name, payload in items.items():
        if name == "baselines_b3_b5_pooled_vs_by_regime":
            for sub_name, sub_payload in payload.items():
                ranking.append(
                    {
                        "metrica": f"{name}.{sub_name}",
                        "divergencia_relativa": sub_payload.get("divergencia_relativa"),
                        "sign_flip": sub_payload.get("sign_flip"),
                    }
                )
        elif name == "t1_features_leakage_scan_pooled_vs_by_regime":
            for feature, sub_payload in payload.items():
                ranking.append(
                    {
                        "metrica": f"{name}.{feature}",
                        "divergencia_relativa": None,
                        "sign_flip": sub_payload.get("sign_flip_across_regimes"),
                    }
                )
        else:
            ranking.append(
                {
                    "metrica": name,
                    "divergencia_relativa": payload.get("divergencia_relativa"),
                    "sign_flip": payload.get("sign_flip"),
                }
            )
    ranking_ordenado = sorted(
        ranking,
        key=lambda r: (r["divergencia_relativa"] is None, -(r["divergencia_relativa"] or 0.0)),
    )

    return {
        "escopo_declarado": (
            "4 categorias: HHI efetivo, ratio de tau, baselines B3/B5 "
            "por regime, e as 10 features T1 do scan de leakage por "
            "regime -- não é varredura exaustiva de todo src/analysis, "
            "src/models, src/validation (ver docstring da função)"
        ),
        "items": items,
        "ranking_por_divergencia_relativa_decrescente": ranking_ordenado,
    }


# ============================================================================
# Bloco 6 — orquestração, SEM campo de veredito.
# ============================================================================


def run_faixa1_6() -> dict[str, Any]:
    step0 = verify_step0_premises()

    mf = ds.build_modeling_frame()
    cpcv_result = cpcv.generate_splits(mf.data)
    splits = cpcv_result.splits
    predictions = f15.load_predictions(model_id=pipeline.MODEL_ID_CAMADA1)

    ic_reconciliation = reconcile_e02f_ic(predictions, mf.data, splits)
    threshold_report = report_bloco2_threshold_sanity()
    fee_budget_report = report_bloco3_fee_budget_correction()
    short_constraint_variant = run_e02f_short_unforced_variant()
    pooled_vs_stratified = pooled_vs_stratified_inventory(mf.data)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "task": "faixa1_6_reconciliation",
        "step0_premises": step0,
        "ic_reconciliation": ic_reconciliation,
        "threshold": threshold_report,
        "fee_budget_corrected": fee_budget_report,
        "short_constraint_variant": short_constraint_variant,
        "pooled_vs_stratified_inventory": pooled_vs_stratified,
    }
    return payload


def run_and_save_faixa1_6(*, dest_path: Path | None = None) -> Path:
    """Ponto de entrada MANUAL (mesmo padrão de
    `run_and_save_faixa1_5`/`run_and_save_faixa1_report`). Chame:
    `uv run python -m src.analysis.faixa1_6_reconciliation`.

    **Aviso de custo:** o Bloco 4 (`run_e02f_short_unforced_variant`)
    retreina 15 folds x 2 lados de XGBoost — minutos, não segundos (ver
    `elapsed_seconds` de `alpha_layer1_report.json` para a ordem de
    grandeza da mesma operação para a Camada 1 completa)."""
    payload = run_faixa1_6()
    payload = {**report_provenance(), **payload}

    dest = dest_path if dest_path is not None else DEFAULT_OUTPUT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest)
    logger.info("analysis.faixa1_6_reconciliation.written", path=str(dest))
    return dest


if __name__ == "__main__":
    run_and_save_faixa1_6()
