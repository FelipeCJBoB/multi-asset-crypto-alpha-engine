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
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from scipy.stats import chisquare, spearmanr

from src.core.provenance import report_provenance
from src.data import lake
from src.features.build import T1_FEATURE_IDS
from src.labels import barrier_sweep as bs
from src.labels import triple_barrier as tb
from src.models import alpha
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models.decomposition import decompose
from src.models.environments import ENVIRONMENTS, assign_environments
from src.models.hhi import compute_effective_concentration
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


def e2_prereq_configuracoes_viaveis_orcamento(
    orcamento_por_cenario: dict[str, Any],
) -> dict[str, Any]:
    """Pré-E2 (3), a pedido do Manager (2026-08-09): a partir de
    `fase0_orcamento_fees_por_cenario` (F0.2), listar EXPLICITAMENTE quais
    paths são viáveis (não excedem o orçamento) em cada cenário -- não
    escolhe entre eles, só declara o que já foi medido de forma
    diretamente acionável (path a path, não só a razão média agregada)."""
    implied_budget = orcamento_por_cenario["implied_budget_trades_per_year"]
    out: dict[str, Any] = {"implied_budget_trades_per_year": implied_budget, "cenarios": {}}
    for nome, cenario in orcamento_por_cenario["cenarios"].items():
        paths_viaveis: list[str] = []
        paths_inviaveis: list[str] = []
        detalhe_por_path: dict[str, Any] = {}
        for pid, tpy in cenario["trades_per_year_by_path"].items():
            viavel = math.isfinite(tpy) and tpy <= implied_budget
            (paths_viaveis if viavel else paths_inviaveis).append(pid)
            detalhe_por_path[pid] = {
                "trades_per_year": tpy,
                "razao_vs_orcamento": tpy / implied_budget if math.isfinite(tpy) else float("nan"),
                "viavel": viavel,
            }
        out["cenarios"][nome] = {
            "paths_viaveis": sorted(paths_viaveis, key=int),
            "paths_inviaveis": sorted(paths_inviaveis, key=int),
            "n_paths_viaveis": len(paths_viaveis),
            "n_paths_total": len(cenario["trades_per_year_by_path"]),
            "cenario_totalmente_viavel": len(paths_inviaveis) == 0,
            "detalhe_por_path": detalhe_por_path,
        }
    out["nota"] = (
        "lista viabilidade por path em cada cenario ja medido em F0.2 -- "
        "NAO escolhe entre eles, por instrucao explicita do Manager"
    )
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
# E1 — varredura de barreiras 3x3 por lado (`src.labels.barrier_sweep`,
# sliding_window_view — §18.7.1). Grade DECLARADA antes da busca (B20):
# tp_atr_mult x sl_atr_mult, 9 células x 2 lados = 18 variantes.
# n_lifetime += 18 (declarado aqui, aplicado em audit/n_lifetime.yaml pelo
# chamador do relatório -- ver run_and_save_fase2_e1).
# ============================================================================

E1_TP_GRID: Final[tuple[float, ...]] = (1.5, 2.0, 2.5)  # noqa: magic-number
E1_SL_GRID: Final[tuple[float, ...]] = (1.0, 1.5, 2.0)  # noqa: magic-number


def _filled_side_population(mf_data: pl.DataFrame, *, side: int) -> pl.DataFrame:
    """Trades JÁ preenchidos de UM lado, de QUALQUER config (fill não
    depende de tp/sl -- ver docstring de `src.labels.barrier_sweep`).
    Colunas exigidas por `resolve_barriers_vectorized` + as que os
    sumários de célula precisam (regime, atr_at_t0)."""
    return mf_data.filter(
        (pl.col("side") == side) & (pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    ).select("t0", "t_entry", "entry_price_fill", "atr_at_t0", "regime")


def _cell_trades(
    filled_side: pl.DataFrame, resolved: bs.ResolvedBarriers, *, side: int
) -> pl.DataFrame:
    n = filled_side.height
    return filled_side.select("t0", "regime", "atr_at_t0").with_columns(
        pl.Series("side_hat", [side] * n, dtype=pl.Int64),
        pl.Series("barrier_hit", resolved.barrier_hit),
        pl.Series("ret_gross", resolved.ret_gross),
        pl.Series("ret_net", resolved.ret_net),
        pl.Series("funding_bps", resolved.funding_bps),
        pl.Series("cost_entry_bps", resolved.cost_entry_bps),
        pl.Series("cost_exit_bps", resolved.cost_exit_bps),
    )


def _map_trades_to_paths(
    trades: pl.DataFrame, predictions: pl.DataFrame, fold_to_path: dict[int, int]
) -> pl.DataFrame:
    """Mesma técnica de `f15.build_realized_trades`, SEM filtrar
    `side_hat != 0` -- E1 mede capacidade INCONDICIONAL da nova geometria
    de barreira (nenhum modelo foi retreinado sobre ela), mesmo espírito
    de `f17.b1_any_entry_by_regime`/`b2_continuous_exposure_by_regime`. Um
    `t0` é testado (OOF) em 5 splits diferentes (1-fatoração de K_6,
    `n_backtest_paths=5`) -- o join duplica a linha em até 5 paths, por
    desenho (mesmo comportamento de `build_realized_trades`)."""
    oof_all = predictions.filter(pl.col("is_oof")).select("t0", "fold_id").unique()
    joined = trades.join(oof_all, on="t0", how="inner")
    path_series = pl.Series(
        "path_id", [fold_to_path[f] for f in joined["fold_id"].to_list()], dtype=pl.Int64
    )
    return joined.with_columns(path_series)


def _edge_atr_closed_form_by_regime(
    cell_trades: pl.DataFrame, mf_data_side_all: pl.DataFrame, *, tp: float, sl: float
) -> dict[str, Any]:
    """Edge em unidades de ATR por regime, forma fechada pedida pelo
    Manager (2026-08-09, resposta pré-E2): `edge = frac_tp(regime) x tp -
    frac_sl(regime) x sl` -- NÃO `directional_sharpe` incondicional (que
    mistura variância/anualização, não é o número que isola geometria).
    `frac_tp`/`frac_sl` usam como denominador TODA barra do lado NAQUELE
    regime (preenchida ou não, mesma convenção side-level do resto do E1),
    não só as preenchidas -- TIME contribui 0 implicitamente (aproximação
    declarada: o payoff médio de TIME não é 0 exato, mas é pequeno e não
    determinístico por construção, diferente de TP/SL que são exatamente
    +tp/-sl por definição de barreira)."""
    out: dict[str, Any] = {}
    for regime in _STRUCTURAL_REGIMES:
        n_total_regime = mf_data_side_all.filter(pl.col("regime") == regime).height
        regime_trades = cell_trades.filter(pl.col("regime") == regime)
        barrier = regime_trades["barrier_hit"]
        n_tp = int((barrier == "TP").sum())
        n_sl = int((barrier == "SL").sum())
        n_time = int((barrier == "TIME").sum())
        frac_tp = n_tp / n_total_regime if n_total_regime else float("nan")
        frac_sl = n_sl / n_total_regime if n_total_regime else float("nan")
        frac_time = n_time / n_total_regime if n_total_regime else float("nan")
        out[regime] = {
            "n_total_regime": n_total_regime,
            "frac_tp": frac_tp,
            "frac_sl": frac_sl,
            "frac_time": frac_time,
            "edge_atr_closed_form": (
                frac_tp * tp - frac_sl * sl if math.isfinite(frac_tp) and math.isfinite(frac_sl)
                else float("nan")
            ),
        }
    return out


def _cell_summary(
    cell_trades: pl.DataFrame,
    cell_trades_with_path: pl.DataFrame,
    mf_data_side_all: pl.DataFrame,
    *,
    n_total_side: int,
    n_nofill_side: int,
    tp: float,
    sl: float,
    side_label: str,
) -> dict[str, Any]:
    """`cell_trades` (sem duplicação de path) alimenta directional_sharpe/
    edge/custo -- `cell_trades_with_path` (duplicado até 5x, um por path,
    ver `_map_trades_to_paths`) só alimenta `trades_per_year_by_path`.
    Misturar os dois em `decompose()` enviesaria levemente média/desvio na
    direção dos trades perto do centro do dataset (que aparecem em mais
    paths que os das bordas) -- evitado mantendo as duas populações
    separadas."""
    edge_atr = (cell_trades["ret_gross"] / cell_trades["atr_at_t0"]).to_numpy().astype(np.float64)
    edge_atr = edge_atr[np.isfinite(edge_atr)]
    cost_bps = (
        (cell_trades["cost_entry_bps"] + cell_trades["cost_exit_bps"]).to_numpy().astype(np.float64)
    )

    by_regime: dict[str, Any] = {}
    for regime in _STRUCTURAL_REGIMES:
        cell_regime = cell_trades.filter(pl.col("regime") == regime)
        result = decompose(cell_regime, source=f"faixa2::e1::{side_label}_tp{tp}_sl{sl}_{regime}")
        by_regime[regime] = {
            "n_trades": result.n_trades,
            "directional_sharpe": result.directional_sharpe.value,
        }

    per_path = f15._trades_per_year_per_path(cell_trades_with_path)
    edge_atr_by_regime = _edge_atr_closed_form_by_regime(
        cell_trades, mf_data_side_all, tp=tp, sl=sl
    )

    return {
        "tp_atr_mult": tp,
        "sl_atr_mult": sl,
        "n_filled": cell_trades.height,
        "n_total_side": n_total_side,
        "n_nofill_side": n_nofill_side,
        "frac_nofill": n_nofill_side / n_total_side if n_total_side else float("nan"),
        "edge_atr_units_mean": float(np.mean(edge_atr)) if edge_atr.size else float("nan"),
        "edge_atr_closed_form_by_regime": edge_atr_by_regime,
        "cost_bps_mean": float(np.mean(cost_bps)) if cost_bps.size else float("nan"),
        "directional_sharpe_by_regime": by_regime,
        "trades_per_year_by_path": {str(pid): v["trades_per_year"] for pid, v in per_path.items()},
    }


def run_fase2_e1(
    mf_data: pl.DataFrame,
    predictions: pl.DataFrame,
    splits: tuple[cpcv.CPCVSplit, ...],
) -> dict[str, Any]:
    """FASE 2, E1 — roda o grid 3x3 DECLARADO (`E1_TP_GRID`/`E1_SL_GRID`)
    independente por lado (9 células/lado, 18 total). Carrega
    `mark_1m`/`funding` da série completa UMA VEZ (mesmo padrão de
    `cost_surface.build_cost_surface_grid_for_symbol`), reusa para as 18
    células. NÃO decide/escolhe -- só emite, mesmo padrão de todo o resto
    da Faixa 2."""
    cfg = tb.LabelConfig.from_constants()
    fold_to_path = f15.fold_to_path_map(splits)

    t0_min, t0_max = mf_data["t0"].min(), mf_data["t0"].max()
    start = (t0_min.date() - timedelta(days=3)).isoformat()  # type: ignore[union-attr]
    end = (t0_max.date() + timedelta(days=3)).isoformat()  # type: ignore[union-attr]
    mark_1m = lake.query_bars(
        ds.SYMBOL_DEFAULT, "1m", start, end, source="mark_price_klines_1m", cast_prices=True
    )
    funding = lake.query_funding(ds.SYMBOL_DEFAULT, start, end)
    logger.info(
        "analysis.faixa2_e1.data_loaded", n_mark_1m=mark_1m.height, n_funding=funding.height
    )

    payload: dict[str, Any] = {
        "grid_declared_before_search": {
            "tp_atr_mult": list(E1_TP_GRID),
            "sl_atr_mult": list(E1_SL_GRID),
        },
        "n_lifetime_delta": len(E1_TP_GRID) * len(E1_SL_GRID) * 2,
        "cells": {},
        "sanidade_centro_da_grade": {},
    }

    for side, side_label in ((1, "long"), (-1, "short")):
        filled_side = _filled_side_population(mf_data, side=side)
        mf_data_side_all = mf_data.filter(pl.col("side") == side).select("regime")
        n_total_side = mf_data_side_all.height
        n_nofill_side = n_total_side - filled_side.height

        for tp in E1_TP_GRID:
            for sl in E1_SL_GRID:
                t_cell = time.perf_counter()
                resolved = bs.resolve_barriers_vectorized(
                    filled_side,
                    mark_1m,
                    funding,
                    side=side,
                    tp_atr_mult=tp,
                    sl_atr_mult=sl,
                    time_stop_bars=cfg.time_stop_bars,
                    maker_fee=cfg.maker_fee,
                    taker_fee=cfg.taker_fee,
                )
                cell_trades = _cell_trades(filled_side, resolved, side=side)

                # distribuição TP/SL/TIME EXATA sobre a população SEM
                # duplicação de path (antes do join com predictions).
                barrier_arr = np.array(resolved.barrier_hit)
                n_tp_exact = int((barrier_arr == "TP").sum())
                n_sl_exact = int((barrier_arr == "SL").sum())
                n_time_exact = int((barrier_arr == "TIME").sum())

                cell_with_path = _map_trades_to_paths(cell_trades, predictions, fold_to_path)
                summary = _cell_summary(
                    cell_trades,
                    cell_with_path,
                    mf_data_side_all,
                    n_total_side=n_total_side,
                    n_nofill_side=n_nofill_side,
                    tp=tp,
                    sl=sl,
                    side_label=side_label,
                )
                summary["frac_tp"] = n_tp_exact / n_total_side
                summary["frac_sl"] = n_sl_exact / n_total_side
                summary["frac_time"] = n_time_exact / n_total_side
                summary["elapsed_seconds"] = time.perf_counter() - t_cell

                key = f"{side_label}_tp{tp}_sl{sl}"
                payload["cells"][key] = summary
                logger.info(
                    "analysis.faixa2_e1.cell_done",
                    side=side_label,
                    tp_atr_mult=tp,
                    sl_atr_mult=sl,
                    elapsed_s=round(summary["elapsed_seconds"], 1),
                )

    # sanidade: centro da grade (tp=2.0, sl=1.5, herdado de constants.yaml)
    # reproduz a distribuição pooled do Sprint 6 (TP 36,5% / SL 51,3% /
    # TIME 6,5% / NOFILL 5,7% -- docs/SPRINT_LOG.md, secao Sprint 6).
    center_long = payload["cells"][f"long_tp{cfg.tp_atr_mult}_sl{cfg.sl_atr_mult}"]
    center_short = payload["cells"][f"short_tp{cfg.tp_atr_mult}_sl{cfg.sl_atr_mult}"]
    n_total_pooled = center_long["n_total_side"] + center_short["n_total_side"]
    pooled_frac = {
        "TP": (
            center_long["frac_tp"] * center_long["n_total_side"]
            + center_short["frac_tp"] * center_short["n_total_side"]
        )
        / n_total_pooled,
        "SL": (
            center_long["frac_sl"] * center_long["n_total_side"]
            + center_short["frac_sl"] * center_short["n_total_side"]
        )
        / n_total_pooled,
        "TIME": (
            center_long["frac_time"] * center_long["n_total_side"]
            + center_short["frac_time"] * center_short["n_total_side"]
        )
        / n_total_pooled,
        "NOFILL": (
            center_long["frac_nofill"] * center_long["n_total_side"]
            + center_short["frac_nofill"] * center_short["n_total_side"]
        )
        / n_total_pooled,
    }
    # fatos MEDIDOS do Sprint 6 (labels/v1/labels.parquet, ver SPRINT_LOG),
    # não parâmetros de domínio -- mesma categoria de
    # `_PRE_T0_DIRECTIONAL_SHARPE_POOLED` em faixa1_6_reconciliation.py.
    sprint6_reference = {
        "TP": 0.3654,  # noqa: magic-number
        "SL": 0.5125,  # noqa: magic-number
        "TIME": 0.0652,  # noqa: magic-number
        "NOFILL": 0.0569,  # noqa: magic-number
    }
    payload["sanidade_centro_da_grade"] = {
        "pooled_frac_recomputado": pooled_frac,
        "sprint6_referencia": sprint6_reference,
        "max_abs_diff": max(abs(pooled_frac[k] - sprint6_reference[k]) for k in sprint6_reference),
    }
    payload["edge_atr_synthesis"] = _edge_atr_synthesis(payload["cells"])
    return payload


_E1_TP_LOWER_BOUNDARY: Final[float] = min(E1_TP_GRID)


def _edge_atr_synthesis(cells: dict[str, Any]) -> dict[str, Any]:
    """Melhor célula por `edge_atr_closed_form` (média sobre os 4 regimes),
    por lado, e por lado x regime -- NÃO decide, só ordena e detecta se a
    borda inferior de `tp_atr_mult` foi tocada (critério do Manager,
    2026-08-09: 'se a melhor célula for a de menor tp, propor extensão')."""
    out: dict[str, Any] = {"best_by_side": {}, "best_by_side_regime": {}}
    for side_label in ("long", "short"):
        side_keys = [k for k in cells if k.startswith(f"{side_label}_")]
        ranked = sorted(
            side_keys,
            key=lambda k: float(
                np.mean(
                    [
                        e["edge_atr_closed_form"]
                        for e in cells[k]["edge_atr_closed_form_by_regime"].values()
                    ]
                )
            ),
            reverse=True,
        )
        best_key = ranked[0]
        best_cell = cells[best_key]
        best_mean_edge = float(
            np.mean(
                [
                    e["edge_atr_closed_form"]
                    for e in best_cell["edge_atr_closed_form_by_regime"].values()
                ]
            )
        )
        out["best_by_side"][side_label] = {
            "cell": best_key,
            "tp_atr_mult": best_cell["tp_atr_mult"],
            "sl_atr_mult": best_cell["sl_atr_mult"],
            "mean_edge_atr_closed_form": best_mean_edge,
            "toca_borda_inferior_tp": best_cell["tp_atr_mult"] <= _E1_TP_LOWER_BOUNDARY,
        }
        for regime in _STRUCTURAL_REGIMES:

            def _edge_for_regime(key: str, *, _regime: str = regime) -> float:
                edge = cells[key]["edge_atr_closed_form_by_regime"][_regime][
                    "edge_atr_closed_form"
                ]
                return float(edge)

            regime_ranked = sorted(side_keys, key=_edge_for_regime, reverse=True)
            best_regime_key = regime_ranked[0]
            best_regime_cell = cells[best_regime_key]
            best_regime_edge = best_regime_cell["edge_atr_closed_form_by_regime"][regime][
                "edge_atr_closed_form"
            ]
            out["best_by_side_regime"][f"{side_label}_{regime}"] = {
                "cell": best_regime_key,
                "tp_atr_mult": best_regime_cell["tp_atr_mult"],
                "sl_atr_mult": best_regime_cell["sl_atr_mult"],
                "edge_atr_closed_form": best_regime_edge,
                "toca_borda_inferior_tp": best_regime_cell["tp_atr_mult"] <= _E1_TP_LOWER_BOUNDARY,
            }

    any_touches_lower_boundary = out["best_by_side"]["long"]["toca_borda_inferior_tp"] or out[
        "best_by_side"
    ]["short"]["toca_borda_inferior_tp"]
    out["proposta_extensao_grade"] = (
        {
            "gatilho": (
                "melhor celula (media dos 4 regimes) toca a borda inferior de "
                f"tp_atr_mult={_E1_TP_LOWER_BOUNDARY} em pelo menos um lado -- "
                "criterio do Manager (2026-08-09): propor extensao, nao rodar"
            ),
            "tp_atr_mult_proposto": [1.0, 1.25],  # noqa: magic-number
            "n_lifetime_delta_se_aprovado": 2 * 2 * 2,
            "nota": (
                "PROPOSTA, nao executada. Precisa de N_lifetime declarado "
                "ANTES de rodar (B20), mesma disciplina do grid original de E1."
            ),
        }
        if any_touches_lower_boundary
        else {"gatilho": "nao disparado -- melhor celula nao toca a borda inferior de tp"}
    )
    return out


E1_OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "faixa2_e1_barrier_sweep.json"


def run_and_save_fase2_e1(*, dest_path: Path | None = None) -> Path:
    """Ponto de entrada MANUAL, separado de `run_and_save_fase0_e_fase1`
    (custo real: carrega `mark_1m`/`funding` da série completa + 18
    resoluções vetorizadas — minutos, não segundos). Chame:
    `uv run python -c "from src.analysis.faixa2_caminho_b import
    run_and_save_fase2_e1 as r; r()"`."""
    mf = ds.build_modeling_frame()
    cpcv_result = cpcv.generate_splits(mf.data)
    splits = cpcv_result.splits
    predictions = f15.load_predictions()

    t0 = time.perf_counter()
    payload = run_fase2_e1(mf.data, predictions, splits)
    payload["elapsed_seconds_total"] = time.perf_counter() - t0
    payload = {**report_provenance(), "task": "faixa2_e1_barrier_sweep", **payload}

    dest = dest_path if dest_path is not None else E1_OUTPUT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest)
    logger.info(
        "analysis.faixa2_e1.written",
        path=str(dest),
        elapsed_seconds_total=round(payload["elapsed_seconds_total"], 1),
    )
    return dest


# ============================================================================
# Pré-E2 (2) — importância por permutação + resolução dos 2 pares de
# ortogonalidade (§5.8, achado do Sprint 4: E27f_cost_atr_ratio x
# C07_vol_pctile_expanding rho=-0,913; A13_dist_ema48_atr x B01_rsi_14
# rho=+0,947). Retreina a Camada 1 EM MEMÓRIA (mesma config/seed de
# produção -- verificado bit-idêntico contra alpha_c1_v1 antes de confiar
# em qualquer número daqui), nunca persiste um model_id novo.
# ============================================================================

_ORTHOGONALITY_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("E27f_cost_atr_ratio", "C07_vol_pctile_expanding"),
    ("A13_dist_ema48_atr", "B01_rsi_14"),
)


def _test_side_xy(
    mf_data: pl.DataFrame, split: cpcv.CPCVSplit, *, side: int
) -> tuple[np.ndarray, np.ndarray]:
    """MESMA definição de `y` que `alpha.fit_side_model` usa no TREINO
    (`label==1`, "TP antes de SL"), aplicada ao TESTE do fold -- avaliação
    de importância precisa do desempenho em dado que o modelo não viu."""
    test_bars = mf_data[split.test_idx]
    test_side = ds.side_subset(test_bars, side=side)
    x = alpha.build_design_matrix(test_side)
    y = (test_side["label"].cast(pl.Int64) == 1).to_numpy().astype(np.int64)
    return x, y


def _permutation_importance_auc_drop(
    model: Any,
    x_test: np.ndarray,
    y_test: np.ndarray,
    *,
    n_t1_features: int,
    rng: np.random.Generator,
) -> list[float]:
    """`baseline_auc - permuted_auc` por feature T1 (colunas `0..n_t1_
    features-1` de `x_test` -- as dummies de regime, colunas seguintes,
    nunca são permutadas: a pergunta é sobre as 10 T1, não sobre regime).
    Uma permutação por feature (não repetida/mediana de N shuffles) --
    aproximação declarada por custo (15 folds x 2 lados x 10 features já
    são 300 avaliações de AUC; repetir 10x seria 3.000)."""
    from sklearn.metrics import roc_auc_score

    if x_test.shape[0] < 2 or len(np.unique(y_test)) < 2:
        return [float("nan")] * n_t1_features
    baseline_auc = roc_auc_score(y_test, model.predict_proba(x_test)[:, 1])
    out: list[float] = []
    for j in range(n_t1_features):
        x_perm = x_test.copy()
        perm = rng.permutation(x_perm.shape[0])
        x_perm[:, j] = x_perm[perm, j]
        permuted_auc = roc_auc_score(y_test, model.predict_proba(x_perm)[:, 1])
        out.append(float(baseline_auc - permuted_auc))
    return out


def e2_prereq_permutation_importance_and_orthogonality(
    mf_data: pl.DataFrame, splits: tuple[cpcv.CPCVSplit, ...]
) -> dict[str, Any]:
    hyper = alpha.XGBHyperparams.from_constants()
    seed = int(load_constant("alpha_random_seed"))

    logger.info("analysis.faixa2_e2prereq.retrain_start")
    fold_results = alpha.run_all_folds(
        mf_data,
        splits,
        variant=alpha.VARIANT_CAMADA1,
        model_id="e2_prereq_verification_not_persisted",
        hyper=hyper,
        seed=seed,
    )
    logger.info("analysis.faixa2_e2prereq.retrain_done", n_folds=len(fold_results))

    new_preds = alpha.assemble_predictions_table(fold_results)
    existing_preds = f15.load_predictions()
    cmp = new_preds.select("t0", "fold_id", "side_hat", "confidence").join(
        existing_preds.select("t0", "fold_id", "side_hat", "confidence"),
        on=["t0", "fold_id"],
        how="inner",
        suffix="_existing",
    )
    n_side_hat_mismatch = int((cmp["side_hat"] != cmp["side_hat_existing"]).sum())
    conf_diff_arr = (
        (cmp["confidence"] - cmp["confidence_existing"]).abs().to_numpy().astype(np.float64)
    )
    max_conf_diff = float(np.max(conf_diff_arr)) if conf_diff_arr.size else float("nan")
    reproduction_check = {
        "n_rows_compared": cmp.height,
        "n_side_hat_mismatch": n_side_hat_mismatch,
        "max_confidence_abs_diff": max_conf_diff,
        "bit_identical": n_side_hat_mismatch == 0 and max_conf_diff < 1e-9,  # noqa: magic-number
        "nota": (
            "retreino em memoria, MESMA config/seed de alpha_c1_v1, nunca "
            "persistido em disco -- este check confirma que os numeros de "
            "importancia abaixo vem do modelo de producao, nao de uma "
            "variante nova (n_lifetime += 0 se bit_identical)"
        ),
    }

    importance_records: list[dict[str, Any]] = []
    hhi_before_records: list[dict[str, Any]] = []
    correlation_by_fold_side: dict[tuple[int, int], np.ndarray] = {}
    gain_by_fold_side: dict[tuple[int, int], dict[str, float]] = {}

    for fold_result, split in zip(fold_results, splits, strict=True):
        train_bars = mf_data[split.train_idx]
        for side, side_label, side_result in (
            (1, "long", fold_result.long_result),
            (-1, "short", fold_result.short_result),
        ):
            train_side = ds.side_subset(train_bars, side=side)
            correlation_t1 = alpha._t1_correlation_matrix(train_side)
            gain_by_column = side_result.gain_by_column_raw
            correlation_by_fold_side[(split.split_id, side)] = correlation_t1
            gain_by_fold_side[(split.split_id, side)] = gain_by_column

            hhi_before = compute_effective_concentration(
                correlation_t1,
                gain_by_column,
                T1_FEATURE_IDS,
                source=f"faixa2::e2prereq::hhi_before::fold{split.split_id}_{side_label}",
            )
            hhi_before_records.append(
                {
                    "fold_id": split.split_id,
                    "side": side_label,
                    "hhi_effective": hhi_before.hhi_effective.value,
                }
            )

            x_test, y_test = _test_side_xy(mf_data, split, side=side)
            rng = np.random.default_rng(alpha._derived_seed(seed, split.split_id, side, 99))
            importances = _permutation_importance_auc_drop(
                side_result.model, x_test, y_test, n_t1_features=len(T1_FEATURE_IDS), rng=rng
            )
            for feat, imp in zip(T1_FEATURE_IDS, importances, strict=True):
                importance_records.append(
                    {
                        "fold_id": split.split_id,
                        "side": side_label,
                        "feature": feat,
                        "auc_drop": imp,
                    }
                )

    importance_df = pl.DataFrame(importance_records)
    mean_importance_by_side_feature: dict[str, dict[str, float]] = {"long": {}, "short": {}}
    for side_label in ("long", "short"):
        sub = importance_df.filter(pl.col("side") == side_label)
        for feat in T1_FEATURE_IDS:
            vals = sub.filter(pl.col("feature") == feat)["auc_drop"].to_numpy().astype(np.float64)
            vals = vals[np.isfinite(vals)]
            mean_importance_by_side_feature[side_label][feat] = (
                float(np.mean(vals)) if vals.size else float("nan")
            )

    pooled_importance = {
        feat: float(
            np.nanmean(
                [
                    mean_importance_by_side_feature["long"][feat],
                    mean_importance_by_side_feature["short"][feat],
                ]
            )
        )
        for feat in T1_FEATURE_IDS
    }

    dropped: list[str] = []
    pair_decisions: list[dict[str, Any]] = []
    for feat_a, feat_b in _ORTHOGONALITY_PAIRS:
        imp_a, imp_b = pooled_importance[feat_a], pooled_importance[feat_b]
        loser = feat_a if imp_a < imp_b else feat_b
        winner = feat_b if loser == feat_a else feat_a
        dropped.append(loser)
        pair_decisions.append(
            {
                "par": [feat_a, feat_b],
                "importancia_pooled": {feat_a: imp_a, feat_b: imp_b},
                "descartada_menor_importancia": loser,
                "mantida": winner,
            }
        )

    reduced_feature_ids = tuple(f for f in T1_FEATURE_IDS if f not in dropped)
    idx_reduced = [T1_FEATURE_IDS.index(f) for f in reduced_feature_ids]

    hhi_after_records: list[dict[str, Any]] = []
    for (fold_id, side), correlation_t1 in correlation_by_fold_side.items():
        gain_by_column = gain_by_fold_side[(fold_id, side)]
        correlation_reduced = correlation_t1[np.ix_(idx_reduced, idx_reduced)]
        side_label = "long" if side == 1 else "short"
        hhi_after = compute_effective_concentration(
            correlation_reduced,
            gain_by_column,
            reduced_feature_ids,
            source=f"faixa2::e2prereq::hhi_after::fold{fold_id}_{side_label}",
        )
        hhi_after_records.append(
            {"fold_id": fold_id, "side": side_label, "hhi_effective": hhi_after.hhi_effective.value}
        )

    mean_hhi_before = float(np.mean([r["hhi_effective"] for r in hhi_before_records]))
    mean_hhi_after = float(np.mean([r["hhi_effective"] for r in hhi_after_records]))

    return {
        "reproduction_check_vs_alpha_c1_v1": reproduction_check,
        "permutation_importance_mean_auc_drop_by_side_feature": mean_importance_by_side_feature,
        "permutation_importance_pooled": pooled_importance,
        "orthogonality_pair_decisions": pair_decisions,
        "features_descartadas": dropped,
        "features_mantidas_t1_reduzido": list(reduced_feature_ids),
        "hhi_efetivo_antes": {
            "mean": mean_hhi_before,
            "n_features": len(T1_FEATURE_IDS),
            "by_fold_side": hhi_before_records,
        },
        "hhi_efetivo_depois": {
            "mean": mean_hhi_after,
            "n_features": len(reduced_feature_ids),
            "by_fold_side": hhi_after_records,
        },
        "nota": (
            "descarta o membro de MENOR importancia por permutacao de cada "
            "par -- nao decide manter/promover nada em T1, essa decisao "
            "fica com E2 (pausado por instrucao do Manager, 2026-08-09)"
        ),
    }


E2_PREREQ_OUTPUT_PATH: Final[Path] = (
    EXPERIMENTS_DIR / "faixa2_e2_prereq_permutation_importance.json"
)


def run_and_save_e2_prereq_permutation_importance(*, dest_path: Path | None = None) -> Path:
    """Ponto de entrada MANUAL -- retreina a Camada 1 (15 folds x 2 lados),
    minutos não segundos. Chame: `uv run python -c "from
    src.analysis.faixa2_caminho_b import
    run_and_save_e2_prereq_permutation_importance as r; r()"`."""
    mf = ds.build_modeling_frame()
    cpcv_result = cpcv.generate_splits(mf.data)
    splits = cpcv_result.splits

    t0 = time.perf_counter()
    payload = e2_prereq_permutation_importance_and_orthogonality(mf.data, splits)
    payload["elapsed_seconds_total"] = time.perf_counter() - t0
    payload = {
        **report_provenance(),
        "task": "faixa2_e2_prereq_permutation_importance",
        **payload,
    }

    dest = dest_path if dest_path is not None else E2_PREREQ_OUTPUT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest)
    logger.info(
        "analysis.faixa2_e2prereq.written",
        path=str(dest),
        elapsed_seconds_total=round(payload["elapsed_seconds_total"], 1),
    )
    return dest


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

    orcamento_por_cenario = fase0_orcamento_fees_por_cenario(realized)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "task": "faixa2_caminho_b",
        "fase0_f0_1_n_lifetime_auditado": {
            "counter_antes": 5,
            "counter_depois": 23,
            "delta": 18,
            "fonte": "audit/n_lifetime.yaml, ids 6-9",
        },
        "fase0_f0_2_orcamento_fees_por_cenario": orcamento_por_cenario,
        "fase0_f0_3_declaracao_escopo_fill": fase0_declaracao_escopo_fill(),
        "fase1_d1_taxa_base_direcional_por_regime": d1_taxa_base_direcional_por_regime(
            mf.data, realized
        ),
        "fase1_d2_long_r2_selecionado_vs_nao_selecionado": (
            d2_long_r2_selecionado_vs_nao_selecionado(mf.data, predictions, splits)
        ),
        "fase1_d3_mfe_por_regime": d3_mfe_por_regime(mf.data),
        "fase1_d4_e10f_como_candidata": d4_e10f_como_candidata(mf.data, splits),
        "pre_e2_3_configuracoes_viaveis_orcamento": e2_prereq_configuracoes_viaveis_orcamento(
            orcamento_por_cenario
        ),
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
