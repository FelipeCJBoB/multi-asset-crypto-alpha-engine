"""Faixa 2 — caminho B com critério de encerramento (§ task "Faixa 2",
2026-08-09). Tentativa estrutural sobre os dois parâmetros definidos por
erro e nunca corrigidos após a medição que os refutou (T1=10 features,
tp_atr_mult/sl_atr_mult=2,0/1,5) — critério de encerramento C1/C2/C3
PRÉ-REGISTRADO no prompt da task, aplicado por script na FASE 3, sem
recomendação de ação embutida.

**Fases deste módulo** (nomes espelham a task, não um sprint do PRD):
FASE 0 (pré-requisitos, bloqueiam o resto — F0.1 já resolvido em
`audit/n_lifetime.yaml`, F0.2/F0.3 aqui), FASE 1 (D1-D4 — diagnóstico sem
retreino; D3 lê `mfe_atr_units`, coluna nova persistida em
`labels/v1/labels.parquet` pelo mesmo laço de `src.labels.triple_barrier.
build_labels`, não recomputada aqui), FASE 2 (E1/E2/E3 — correção real),
FASE 3 (C1/C2/C3 mecânico).

**Reuso, não reimplementação.** `src.analysis.faixa1_5_prerequisites`
(fold_to_path_map, build_realized_trades, load_predictions,
_trades_per_year_per_path), `src.analysis.faixa1_7_edge_or_beta`
(_trend_direction_48b, _decompose_regime_cell), `src.models.decomposition.
decompose`, `src.models.monotonic` (compute_ic_by_env, _assign_from_ic),
`src.models.environments` (assign_environments, ENVIRONMENTS)."""

from __future__ import annotations

import math
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from scipy.stats import chisquare, spearmanr

from src.core.provenance import report_provenance
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models.environments import ENVIRONMENTS, assign_environments
from src.models.monotonic import _assign_from_ic, compute_ic_by_env
from src.validation import cpcv

from . import faixa1_5_prerequisites as f15
from . import faixa1_7_edge_or_beta as f17

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "faixa2_caminho_b.json"

_STRUCTURAL_REGIMES: tuple[str, ...] = ("R1", "R2", "R3", "R4")
_MIN_CELL_N = f15.MIN_CELL_N
_E10F_FEATURE = "E10f_oi_change_z_48"
_B07_FEATURE = "B07_efficiency_ratio_48"

# ============================================================================
# F0.3 — declaração de escopo do fill (versionada, texto fixo — anexar a
# todo relatório desta Faixa). Não é medição nova: reconcilia fatos já
# registrados em constants.yaml (nota pós-§0.2) e SPRINT_LOG ("Auditoria
# externa do Sprint 8"/"Faixa 1.7, duas perguntas de status").
# ============================================================================

FILL_SCOPE_DECLARATION: Final[str] = (
    "Todos os números desta Faixa derivam do fill OTIMISTA do Label Engine "
    "(barrier_hit != NOFILL do triple barrier sobre mark_1m, nunca o "
    "simulador de fila real). Na ÚNICA janela onde há bookTicker real para "
    "comparar (2023-05-16 a 2024-03-30, ~10,5 de 6,5 anos), trocar para o "
    "gate real deixou o Sharpe MENOS negativo (-9,25 -> -4,27) mas "
    "direcional+carry ficaram NEGATIVOS nos dois gates nessa janela "
    "específica -- diferente do +1,60 positivo do pooled de 6,5 anos. A "
    "direção do viés de usar fill otimista FORA dessa janela de 10,5 meses "
    "é DESCONHECIDA -- não 'sempre parece melhor do que é' (caracterização "
    "anterior, imprecisa), apenas não medida. Só Testnet/Paper (Sprints "
    "15-16) resolve isso de verdade."
)


def fase0_declaracao_escopo_fill() -> dict[str, Any]:
    # 10.5/6.5 -- fatos já medidos e documentados (janela real de bookTicker
    # vs. período total do dataset, "Auditoria externa do Sprint 8"), não
    # parâmetros de domínio novos -- mesma categoria de
    # `_PRE_T0_DIRECTIONAL_SHARPE_POOLED` em faixa1_6_reconciliation.py.
    meses_janela_verificavel = 10.5  # noqa: magic-number
    anos_periodo_total = 6.5  # noqa: magic-number
    return {
        "declaracao": FILL_SCOPE_DECLARATION,
        "janela_verificavel": {
            "inicio": "2023-05-16",
            "fim": "2024-03-30",
            "meses": meses_janela_verificavel,
        },
        "periodo_total_dataset_anos": anos_periodo_total,
        "fonte": (
            "docs/SPRINT_LOG.md, secoes 'Auditoria externa do Sprint 8 + "
            "reconciliacao parcial' e 'Faixa 1.7, duas perguntas de status'; "
            "config/constants.yaml, nota apos adverse_selection_gate0_break_bps"
        ),
    }


# ============================================================================
# F0.2 — orçamento de fees por cenário (emite, não decide).
# ============================================================================


def fase0_orcamento_fees_por_cenario(realized: pl.DataFrame) -> dict[str, Any]:
    """4 cenários pedidos pela task: (i) sistema atual, (ii) só short,
    (iii) long sem R2, (iv) só short + long sem R2. `realized` já é
    `f15.build_realized_trades` (todo sinal emitido, com `path_id`) — cada
    cenário é um FILTRO sobre essa população, nunca um filtro em produção
    (`src.models.monotonic`/Decision Engine intocados)."""
    target_signal_rate = float(load_constant("target_signal_rate"))
    implied_budget_trades_per_year = target_signal_rate * f15.BARS_PER_YEAR

    long_mask = pl.col("side_hat") == 1
    short_mask = pl.col("side_hat") == -1
    long_sem_r2_mask = long_mask & (pl.col("regime") != "R2")

    cenarios = {
        "sistema_atual": realized,
        "so_short": realized.filter(short_mask),
        "long_sem_r2": realized.filter(long_sem_r2_mask),
        "so_short_mais_long_sem_r2": pl.concat(
            [realized.filter(short_mask), realized.filter(long_sem_r2_mask)], how="vertical"
        ),
    }

    out: dict[str, Any] = {
        "implied_budget_trades_per_year": implied_budget_trades_per_year,
        "fee_budget_monthly_atual": float(load_constant("fee_budget_monthly")),
        "cenarios": {},
    }
    for nome, sub in cenarios.items():
        per_path = f15._trades_per_year_per_path(sub)
        n_paths_excede = sum(
            1
            for v in per_path.values()
            if math.isfinite(v["trades_per_year"])
            and v["trades_per_year"] > implied_budget_trades_per_year
        )
        out["cenarios"][nome] = {
            "trades_per_year_by_path": {str(k): v["trades_per_year"] for k, v in per_path.items()},
            "n_filled_by_path": {str(k): v["n_filled"] for k, v in per_path.items()},
            "n_paths_excede_orcamento": n_paths_excede,
            "n_paths_total": len(per_path),
            "razao_media_vs_orcamento": (
                float(
                    np.mean(
                        [
                            v["trades_per_year"] / implied_budget_trades_per_year
                            for v in per_path.values()
                            if math.isfinite(v["trades_per_year"])
                        ]
                    )
                )
                if any(math.isfinite(v["trades_per_year"]) for v in per_path.values())
                else float("nan")
            ),
        }
    return out


# ============================================================================
# D1 — taxa base direcional por regime (lift long/short + qui-quadrado +
# directional_sharpe da fatia contracorrente).
# ============================================================================


def _base_rate_alta_by_regime(mf_data: pl.DataFrame) -> dict[str, dict[str, Any]]:
    """P(alta|barra do regime) — sinal de tendência de 48b sobre TODA barra
    do regime (não só as que viraram trade), via `f17._trend_direction_48b`
    reusado (mesma definição causal de tendência do resto da Faixa 1.7)."""
    trend = f17._trend_direction_48b(mf_data)
    bars = (
        mf_data.filter(pl.col("side") == 1)
        .select("t0", "regime")
        .unique(subset=["t0"])
        .join(trend, on="t0", how="left")
    )
    out: dict[str, dict[str, Any]] = {}
    regions = {**{r: (r,) for r in _STRUCTURAL_REGIMES}, "R3_R4": ("R3", "R4")}
    for label, regimes in regions.items():
        sub = bars.filter(pl.col("regime").is_in(list(regimes)) & (pl.col("trend_sign_48b") != 0))
        n = sub.height
        n_alta = sub.filter(pl.col("trend_sign_48b") == 1).height
        out[label] = {
            "n_bars": n,
            "n_alta": n_alta,
            "n_baixa": n - n_alta,
            "p_alta": n_alta / n if n else float("nan"),
        }
    return out


def _ci95_mean_bps(rets_frac: np.ndarray) -> tuple[float, float]:
    if rets_frac.size < 2:
        return float("nan"), float("nan")
    bps = rets_frac * 10_000
    mean = float(np.mean(bps))
    std = float(np.std(bps, ddof=1))
    if std == 0.0:
        return mean, mean
    from scipy.stats import norm

    # 0.975 -- quantil de CI95 bicaudal, definição matemática (mesmo padrão
    # de faixa1_5_prerequisites._ci95_mean), não parâmetro de domínio.
    ci95_two_sided_quantile = 0.975  # noqa: magic-number
    half = float(norm.ppf(ci95_two_sided_quantile)) * std / math.sqrt(bps.size)
    return mean - half, mean + half


def d1_taxa_base_direcional_por_regime(
    mf_data: pl.DataFrame, realized: pl.DataFrame
) -> dict[str, Any]:
    """Para cada regime R1-R4 e R3+R4 agregado: base rate de alta (todas as
    barras), taxa condicional ao trade (long: P(alta|trade); short:
    P(baixa|trade)), lift = condicional/base, qui-quadrado (goodness-of-fit
    contra o base rate), e directional_sharpe + CI95 da MÉDIA de
    `pnl_direcional` (bps/trade — Sharpe em si não tem CI fechado sem mais
    suposição; a média por trade é o proxy declarado aqui, mesma disciplina
    de aproximação declarada do resto da Faixa) da fatia CONTRACORRENTE
    (long em barra de baixa; short em barra de alta)."""
    trend = f17._trend_direction_48b(mf_data)
    base_rates = _base_rate_alta_by_regime(mf_data)

    out: dict[str, Any] = {"base_rates_p_alta": base_rates, "long": {}, "short": {}}

    regions = {**{r: (r,) for r in _STRUCTURAL_REGIMES}, "R3_R4": ("R3", "R4")}
    for side, side_label, trend_favoravel, trend_contra in (
        (1, "long", 1, -1),
        (-1, "short", -1, 1),
    ):
        for label, regimes in regions.items():
            trades = realized.filter(
                (pl.col("side_hat") == side) & pl.col("regime").is_in(list(regimes))
            ).join(trend, on="t0", how="left")
            trades_com_trend = trades.filter(pl.col("trend_sign_48b") != 0)
            n_total = trades_com_trend.height
            n_favoravel = trades_com_trend.filter(
                pl.col("trend_sign_48b") == trend_favoravel
            ).height
            p_condicional = n_favoravel / n_total if n_total else float("nan")
            base = base_rates[label]
            p_base_favoravel = (
                base["p_alta"] if trend_favoravel == 1 else (1.0 - base["p_alta"])
            )
            lift = (
                p_condicional / p_base_favoravel
                if math.isfinite(p_condicional) and p_base_favoravel > 0
                else float("nan")
            )

            chi2_stat, chi2_p = float("nan"), float("nan")
            if n_total >= _MIN_CELL_N and math.isfinite(p_base_favoravel):
                n_contra_obs = n_total - n_favoravel
                expected_favoravel = n_total * p_base_favoravel
                expected_contra = n_total * (1.0 - p_base_favoravel)
                if expected_favoravel > 0 and expected_contra > 0:
                    chi2_stat, chi2_p = chisquare(
                        f_obs=[n_favoravel, n_contra_obs],
                        f_exp=[expected_favoravel, expected_contra],
                    )
                    chi2_stat, chi2_p = float(chi2_stat), float(chi2_p)

            contra = trades_com_trend.filter(pl.col("trend_sign_48b") == trend_contra)
            contra_filled = contra.filter(pl.col("barrier_hit") != "NOFILL")
            decomp = f17._decompose_regime_cell(
                contra_filled, source=f"faixa2::d1_taxa_base::{side_label}_{label}_contra"
            )
            ci_low, ci_high = (
                _ci95_mean_bps(contra_filled["ret_gross"].to_numpy().astype(np.float64))
                if contra_filled.height
                else (float("nan"), float("nan"))
            )

            out[side_label][label] = {
                "n_trades_com_trend_conhecida": n_total,
                "n_favoravel": n_favoravel,
                "p_condicional_favoravel": p_condicional,
                "p_base_favoravel": p_base_favoravel,
                "lift": lift,
                "chi2_stat": chi2_stat,
                "chi2_p": chi2_p,
                "fatia_contracorrente": {
                    **decomp,
                    "pnl_direcional_mean_bps_ci95_low": ci_low,
                    "pnl_direcional_mean_bps_ci95_high": ci_high,
                },
            }
    return out


# ============================================================================
# D2 — long x R2, selecionado (side_hat==1) vs não-selecionado (visto,
# não disparado) DENTRO de R2. Não conclui — só isola o que distingue.
# ============================================================================

_D2_FEATURES: tuple[str, ...] = (
    "A05_ret_vol_norm_4",
    "A13_dist_ema48_atr",
    "B01_rsi_14",
    "E27f_cost_atr_ratio",
    "C06_vol_ratio_12_96",
    "C07_vol_pctile_expanding",
    "D03f_volume_z_expanding",
    "D06f_taker_imbalance_z_48",
    "E02f_funding_z_expanding",
    "E10f_oi_change_z_48",
)


def _ks_effect_size(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    from scipy.stats import ks_2samp

    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if a.size < 2 or b.size < 2:
        return {"ks_stat": float("nan"), "ks_p": float("nan"), "cohen_d": float("nan")}
    ks_stat, ks_p = ks_2samp(a, b)
    n_total = a.size + b.size
    if n_total > 2:
        pooled_var = (
            (a.size - 1) * np.var(a, ddof=1) + (b.size - 1) * np.var(b, ddof=1)
        ) / (n_total - 2)
        pooled_std = math.sqrt(pooled_var)
    else:
        pooled_std = float("nan")
    if pooled_std and math.isfinite(pooled_std) and pooled_std > 0:
        cohen_d = float((np.mean(a) - np.mean(b)) / pooled_std)
    else:
        cohen_d = float("nan")
    return {"ks_stat": float(ks_stat), "ks_p": float(ks_p), "cohen_d": cohen_d}


def d2_long_r2_selecionado_vs_nao_selecionado(
    mf_data: pl.DataFrame, predictions: pl.DataFrame, splits: tuple[cpcv.CPCVSplit, ...]
) -> dict[str, Any]:
    """`side_hat==1` (selecionado) vem de `predictions` (OOF, join por t0);
    "visto e não disparado" é toda barra de R2, lado long, que ALGUM fold
    teve como OOF-scored mas cujo `side_hat` não foi 1 nesse fold — usa
    `predictions.filter(is_oof=True)` sem filtrar `side_hat`, join com R2."""
    fold_to_path = f15.fold_to_path_map(splits)
    oof_scored = predictions.filter(pl.col("is_oof")).select("t0", "fold_id", "side_hat")

    # `bars_in_regime` não sobrevive ao join de `dataset.build_modeling_frame`
    # (só `regime`/`tradeable` são selecionados de `regime_build.build_regimes`
    # ali) — reconstruído aqui do mesmo Regime Engine, MESMA cadeia de join
    # que `dataset.py` usa internamente: `regime_build.build_regimes(...).t0`
    # é o `open_time` da barra (chave real do Regime Engine), enquanto
    # `mf_data.t0` é o `close_time` (chave dos labels) — os dois só
    # coincidem via `features_build.build_t1_features`, que expõe
    # `open_time`/`close_time` da MESMA barra lado a lado (não um deslocamento
    # fixo assumido; lido do dado, evitando repetir o erro de off-by-one
    # já documentado em constants.yaml para outras constantes de janela).
    from src.features import build as features_build
    from src.regime import build as regime_build

    t0_min, t0_max = mf_data["t0"].min(), mf_data["t0"].max()
    start = (t0_min.date() - timedelta(days=3)).isoformat()  # type: ignore[union-attr]
    end = (t0_max.date() + timedelta(days=3)).isoformat()  # type: ignore[union-attr]

    regimes_df = regime_build.build_regimes(ds.SYMBOL_DEFAULT, start, end)
    open_close_map = features_build.build_t1_features(ds.SYMBOL_DEFAULT, start, end).select(
        pl.col("open_time").cast(pl.Int64).alias("_open_time_ms"),
        pl.col("close_time").cast(pl.Datetime("ms", "UTC")).alias("t0"),
    )
    bars_in_regime_col = (
        regimes_df.select(
            pl.col("t0").dt.epoch(time_unit="ms").alias("_open_time_ms"),
            pl.col("bars_in_regime"),
        )
        .join(open_close_map, on="_open_time_ms", how="inner")
        .select("t0", "bars_in_regime")
    )

    r2_long_bars = (
        mf_data.filter((pl.col("side") == 1) & (pl.col("regime") == "R2"))
        .select("t0", "regime", *_D2_FEATURES)
        .join(bars_in_regime_col, on="t0", how="left")
    )
    joined = oof_scored.join(r2_long_bars, on="t0", how="inner")
    selected = joined.filter(pl.col("side_hat") == 1)
    not_selected = joined.filter(pl.col("side_hat") != 1)

    feature_comparison: dict[str, Any] = {}
    for feat in (*_D2_FEATURES, "bars_in_regime"):
        a = selected[feat].to_numpy().astype(np.float64)
        b = not_selected[feat].to_numpy().astype(np.float64)
        feature_comparison[feat] = {
            "selected_mean": float(np.nanmean(a)) if a.size else float("nan"),
            "not_selected_mean": float(np.nanmean(b)) if b.size else float("nan"),
            **_ks_effect_size(a, b),
        }

    realized = f15.build_realized_trades(predictions, mf_data, fold_to_path)
    r2_long_realized = realized.filter((pl.col("side_hat") == 1) & (pl.col("regime") == "R2"))
    filled = r2_long_realized.filter(pl.col("barrier_hit") != "NOFILL")
    ret_future = (
        filled["ret_net"].to_numpy().astype(np.float64) if filled.height else np.array([])
    )
    ci_low, ci_high = (
        _ci95_mean_bps(ret_future) if ret_future.size else (float("nan"), float("nan"))
    )

    hour_utc_selected = selected["t0"].dt.hour().to_list() if selected.height else []
    hour_utc_not_selected = not_selected["t0"].dt.hour().to_list() if not_selected.height else []
    dow_selected = selected["t0"].dt.weekday().to_list() if selected.height else []
    dow_not_selected = not_selected["t0"].dt.weekday().to_list() if not_selected.height else []

    return {
        "n_selected": selected.height,
        "n_not_selected": not_selected.height,
        "feature_distribution_comparison": feature_comparison,
        "retorno_futuro_realizado_selected": {
            "n_filled": filled.height,
            "mean_ret_net_bps": (
                float(np.mean(ret_future) * 10_000) if ret_future.size else float("nan")
            ),
            "ci95_low_bps": ci_low,
            "ci95_high_bps": ci_high,
        },
        "hora_utc_selected_hist": {
            str(h): hour_utc_selected.count(h) for h in sorted(set(hour_utc_selected))
        },
        "hora_utc_not_selected_hist": {
            str(h): hour_utc_not_selected.count(h) for h in sorted(set(hour_utc_not_selected))
        },
        "dia_semana_selected_hist": {
            str(d): dow_selected.count(d) for d in sorted(set(dow_selected))
        },
        "dia_semana_not_selected_hist": {
            str(d): dow_not_selected.count(d) for d in sorted(set(dow_not_selected))
        },
        "regime_r2_dummy_valor_e_gain": {
            "valor_selected": 1.0,
            "valor_not_selected": 1.0,
            "nota": (
                "o valor da dummy regime_R2 e trivialmente 1 nas DUAS populacoes "
                "(o proprio filtro de R2 garante isso) -- nao discrimina "
                "selecionado de nao-selecionado por construcao. O GAIN da dummy "
                "e propriedade do MODELO por fold (nao do trade individual, "
                "mesma ressalva de _weighted_hhi em faixa1_5_prerequisites), ja "
                "medido em rodada anterior (~0,95% do gain medio, Faixa 1.6/1.7) "
                "-- nao recomputado aqui, citado por referencia."
            ),
        },
        "nota": (
            "so isola o que distingue as duas populacoes -- nao conclui causa, "
            "por instrucao explicita da task (D2: 'Nao concluir')"
        ),
    }


# ============================================================================
# D3 — MFE por regime e por lado (mfe_atr_units já persistido em
# labels/v1/labels.parquet, estendido no laço de src.labels.triple_barrier
# -- não recomputado aqui). Alimenta diretamente a grade de E1: se a
# mediana de MFE num regime for muito menor que tp_atr_mult, o alvo atual
# está fora de alcance ali.
# ============================================================================


def d3_mfe_por_regime(mf_data: pl.DataFrame) -> dict[str, Any]:
    tp_atr_mult = float(load_constant("tp_atr_mult"))
    out: dict[str, Any] = {"tp_atr_mult_atual": tp_atr_mult, "long": {}, "short": {}}
    for side, side_label in ((1, "long"), (-1, "short")):
        for regime in _STRUCTURAL_REGIMES:
            sub = mf_data.filter(
                (pl.col("side") == side)
                & (pl.col("regime") == regime)
                & (pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
            )
            mfe = sub["mfe_atr_units"].drop_nulls().to_numpy().astype(np.float64)
            mfe = mfe[np.isfinite(mfe)]
            if mfe.size == 0:
                out[side_label][regime] = {"n": 0}
                continue
            out[side_label][regime] = {
                "n": int(mfe.size),
                "median": float(np.median(mfe)),
                "p25": float(np.percentile(mfe, 25)),
                "p75": float(np.percentile(mfe, 75)),
                "mean": float(np.mean(mfe)),
                "frac_mfe_menor_que_tp_atr_mult_atual": float(np.mean(mfe < tp_atr_mult)),
            }
    return out


# ============================================================================
# D4 — E10f como candidata: IC in-fold por ambiente, estabilidade,
# correlação com B07 (eixo de estrutura). Não decide inclusão/exclusão.
# ============================================================================


def d4_e10f_como_candidata(
    mf_data: pl.DataFrame, splits: tuple[cpcv.CPCVSplit, ...]
) -> dict[str, Any]:
    min_consistent_envs = int(load_constant("alpha_monotonic_consistency_min_envs"))
    by_fold: dict[str, Any] = {}
    for split in splits:
        train_bars = mf_data[split.train_idx]
        fold_entry: dict[str, Any] = {}
        for side in (1, -1):
            train_side = ds.side_subset(train_bars, side=side)
            df_env = assign_environments(train_side)
            ic_by_env = compute_ic_by_env(df_env, _E10F_FEATURE, "ret_net")
            screen_sign, mean_ic, n_consistent, n_with_data = _assign_from_ic(
                ic_by_env, min_consistent_envs=min_consistent_envs
            )
            consistency_sq = (n_consistent / len(ENVIRONMENTS)) ** 2
            fold_entry["long" if side == 1 else "short"] = {
                "ic_by_env": ic_by_env,
                "mean_ic": mean_ic,
                "n_consistent_envs": n_consistent,
                "n_envs_with_data": n_with_data,
                "screen_sign": screen_sign,
                "stability_ic_x_consistency_sq": (
                    abs(mean_ic) * consistency_sq if math.isfinite(mean_ic) else float("nan")
                ),
            }
        by_fold[str(split.split_id)] = fold_entry

    # correlação pooled E10f x B07 (feature-vs-feature, não feature-vs-alvo
    # -- não é leakage, é checar se a candidata é redundante com uma T1 já
    # existente que descreve o mesmo eixo de estrutura, ver PRD orientação
    # da Fase E2 "priorizar candidatas que descrevem persistência/transição
    # de regime"). B07 não sobrevive ao join de build_modeling_frame (só
    # T1_FEATURE_IDS são selecionados de features_build ali, mesma lacuna
    # de bars_in_regime acima) -- recomputado aqui via build_t1_features
    # (mesma fonte, não uma segunda implementação) e juntado por t0.
    from src.features import build as features_build

    t0_min, t0_max = mf_data["t0"].min(), mf_data["t0"].max()
    start = (t0_min.date() - timedelta(days=3)).isoformat()  # type: ignore[union-attr]
    end = (t0_max.date() + timedelta(days=3)).isoformat()  # type: ignore[union-attr]
    b07_df = (
        features_build.build_t1_features(ds.SYMBOL_DEFAULT, start, end)
        .select(
            pl.col("close_time").cast(pl.Int64).alias("_close_time_ms"),
            pl.col(_B07_FEATURE),
        )
    )
    mf_with_b07 = mf_data.filter(pl.col("side") == 1).with_columns(
        pl.col("t0").dt.epoch(time_unit="ms").alias("_close_time_ms")
    ).join(b07_df, on="_close_time_ms", how="left")

    pooled = mf_with_b07.select(_E10F_FEATURE, _B07_FEATURE)
    x_raw = pooled[_E10F_FEATURE].to_numpy().astype(np.float64)
    y_raw = pooled[_B07_FEATURE].to_numpy().astype(np.float64)
    # `.drop_nulls()` só remove polars-null; E10f pode ter NaN de ponto
    # flutuante genuíno (ex. divisão indefinida na janela de 48 barras),
    # que sobrevive a `drop_nulls()` e contaminaria spearmanr com NaN
    # silencioso -- mesma disciplina de `_spearman_ic` (faixa1_6/faixa1_7),
    # reusada aqui via máscara `np.isfinite` explícita em vez do método do
    # polars.
    finite_mask = np.isfinite(x_raw) & np.isfinite(y_raw)
    n_finite = int(finite_mask.sum())
    if n_finite >= 5 and np.std(x_raw[finite_mask]) > 0 and np.std(y_raw[finite_mask]) > 0:
        rho, p = spearmanr(x_raw[finite_mask], y_raw[finite_mask])
        corr_b07 = {"rho": float(rho), "p": float(p), "n": n_finite}
    else:
        corr_b07 = {"rho": float("nan"), "p": float("nan"), "n": n_finite}

    mean_stability_long = float(
        np.mean(
            [
                v["long"]["stability_ic_x_consistency_sq"]
                for v in by_fold.values()
                if math.isfinite(v["long"]["stability_ic_x_consistency_sq"])
            ]
        )
    )
    mean_stability_short = float(
        np.mean(
            [
                v["short"]["stability_ic_x_consistency_sq"]
                for v in by_fold.values()
                if math.isfinite(v["short"]["stability_ic_x_consistency_sq"])
            ]
        )
    )

    return {
        "by_fold": by_fold,
        "mean_stability_ic_x_consistency_sq": {
            "long": mean_stability_long,
            "short": mean_stability_short,
        },
        "correlacao_pooled_com_b07_efficiency_ratio": corr_b07,
        "nota": "não decide inclusão/exclusão de E10f em T1 — só mede, por instrução da task",
    }


# ============================================================================
# Orquestração FASE 0 + FASE 1 (D1/D2/D4 — D3 é tratado em
# src.labels.triple_barrier, ver mfe_atr_units; E1/E2/E3/FASE 3 entram em
# rodadas seguintes deste mesmo módulo).
# ============================================================================


def run_fase0_e_fase1() -> dict[str, Any]:
    mf = ds.build_modeling_frame()
    cpcv_result = cpcv.generate_splits(mf.data)
    splits = cpcv_result.splits
    predictions = f15.load_predictions()
    fold_to_path = f15.fold_to_path_map(splits)
    realized = f15.build_realized_trades(predictions, mf.data, fold_to_path)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "task": "faixa2_caminho_b",
        "fase0_f0_1_n_lifetime_auditado": {
            "counter_antes": 5,
            "counter_depois": 23,
            "delta": 18,
            "fonte": "audit/n_lifetime.yaml, ids 6-9",
        },
        "fase0_f0_2_orcamento_fees_por_cenario": fase0_orcamento_fees_por_cenario(realized),
        "fase0_f0_3_declaracao_escopo_fill": fase0_declaracao_escopo_fill(),
        "fase1_d1_taxa_base_direcional_por_regime": d1_taxa_base_direcional_por_regime(
            mf.data, realized
        ),
        "fase1_d2_long_r2_selecionado_vs_nao_selecionado": (
            d2_long_r2_selecionado_vs_nao_selecionado(mf.data, predictions, splits)
        ),
        "fase1_d3_mfe_por_regime": d3_mfe_por_regime(mf.data),
        "fase1_d4_e10f_como_candidata": d4_e10f_como_candidata(mf.data, splits),
    }
    return payload


def run_and_save_fase0_e_fase1(*, dest_path: Path | None = None) -> Path:
    """`uv run python -m src.analysis.faixa2_caminho_b`."""
    payload = run_fase0_e_fase1()
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
    logger.info("analysis.faixa2_caminho_b.written", path=str(dest))
    return dest


if __name__ == "__main__":
    run_and_save_fase0_e_fase1()
