"""Faixa 1.7 — edge ou beta+regularização? (§ prompt "Faixa 1.7", 2026-08-09).

Contexto: a Faixa 1.6 mediu um antipadrão (seleção 12,8x maior em R2, o
pior regime direcional) sem decidir a causa. Esta rodada é DIFERENTE das
anteriores por instrução explícita do usuário: existe para produzir uma
decisão binária — **Q1: existe edge, ou é beta + regularização? Q2: a
confiança é consertável?** — não só para descrever. O critério de decisão
foi pré-registrado ANTES de rodar (ver mensagem do turno, reproduzido nos
docstrings de cada função abaixo) — isto aqui só mede; a aplicação do
critério aos números é feita na síntese (fora deste módulo, no relatório
ao usuário/SPRINT_LOG), não em nenhum campo `passed`/`ok`/`conclusion`
deste JSON.

**Escopo deliberadamente NÃO coberto nesta rodada — MFE por regime.**
Excursão favorável máxima por trade exigiria re-caminhar `mark_1m` por
trade (a mesma varredura que `src.labels.triple_barrier._first_barrier_
touch` já faz internamente, mas cujo resultado — o caminho completo, não
só o toque — não é persistido). Não é reuso de coluna já existente como
as outras 7 medições desta rodada; é computação nova sobre 1m completo.
Se for feita, o lugar certo é ESTENDER `build_labels` pra persistir
`mfe_atr_units` no mesmo laço que já varre `path_high`/`path_low` (barato
ali, caro re-implementado à parte) — não faz parte deste módulo.

**Reuso, não reimplementação.** `src.analysis.faixa1_5_prerequisites`
(fold_to_path_map, build_realized_trades), `src.analysis.
faixa1_6_reconciliation` (_build_oof_population, _ic_by_regime,
_spearman_ic), `src.models.decomposition.decompose`, `src.models.
backtest_lite` (span_seconds, sharpe_naive)."""

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
from src.models import backtest_lite, decomposition, pipeline
from src.models import dataset as ds

from . import calibration_diagnostics as caldiag
from . import faixa1_5_prerequisites as f15
from . import faixa1_6_reconciliation as f16

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "faixa1_7_edge_or_beta.json"

_E02F_FEATURE = "E02f_funding_z_expanding"
_VOL_PROXY_FEATURE = "C07_vol_pctile_expanding"
_STRUCTURAL_REGIMES: tuple[str, ...] = ("R1", "R2", "R3", "R4")

# Features de maior gain medidas em faixa1_6 (fold 0 long) — reusadas aqui
# só como lista de comparação pra Medição pendente #2 (distribuição por
# regime), não recalculadas.
_TOP_GAIN_FEATURES: tuple[str, ...] = (
    "E27f_cost_atr_ratio",
    "B01_rsi_14",
    "C06_vol_ratio_12_96",
    "A05_ret_vol_norm_4",
)


def _with_side_hat(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(pl.col("side").alias("side_hat")) if "side" in df.columns else df


def _decompose_regime_cell(df_all: pl.DataFrame, *, source: str) -> dict[str, Any]:
    filled = df_all.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    if filled.height == 0:
        return {
            "n_trades": 0,
            "directional_sharpe": None,
            "total_sharpe": None,
            "ret_net_bps": None,
        }
    if "side_hat" not in filled.columns:
        filled = _with_side_hat(filled)
    result = decompose(filled, source=source)
    return {
        "n_trades": result.n_trades,
        "directional_sharpe": result.directional_sharpe.value,
        "total_sharpe": result.total_sharpe.value,
        "ret_net_bps": result.pnl_total.per_unit().value if result.pnl_total.valid else None,
    }


def decompose(trades: pl.DataFrame, *, source: str) -> decomposition.DecompositionResult:
    return decomposition.decompose(trades, source=source)


# ============================================================================
# Medição 1 (Q1) — R3 partido por direção de tendência.
#
# Pré-registrado: long lucra em R3-alta E R3-baixa (directional_sharpe > 0
# nas duas, ordem de grandeza comparável) => skill direcional real
# ("compra-na-correção"). Long lucra só em R3-alta, neutro/negativo em
# R3-baixa => beta (é apenas estar comprado quando o mercado sobe).
# ============================================================================


def _trend_direction_48b(mf_data: pl.DataFrame) -> pl.DataFrame:
    """Sinal do retorno de 48 barras (log, causal — usa só [t-48, t]),
    computado UMA vez sobre `entry_price_limit` do lado long (preço não
    depende de lado; `side=1` só pra deduplicar por `t0`, mesma convenção
    de `alpha._unique_test_bars`). Devolve `(t0, trend_sign)`,
    `trend_sign` em `{-1, 0, 1}` (`0` se não houver 48 barras de histórico
    ainda, warmup local desta medição — não é o warmup de `min_warmup_bars`
    do resto do T1, é específico deste corte)."""
    px = (
        mf_data.filter(pl.col("side") == 1)
        .select("t0", "entry_price_limit")
        .unique(subset=["t0"])
        .sort("t0")
    )
    log_px = np.log(px["entry_price_limit"].to_numpy().astype(np.float64))
    ret_48b = np.full(log_px.shape[0], np.nan)
    ret_48b[48:] = log_px[48:] - log_px[:-48]
    trend_sign = np.where(np.isnan(ret_48b), 0, np.sign(ret_48b)).astype(np.int64)
    return px.select("t0").with_columns(pl.Series("trend_sign_48b", trend_sign))


def r3_split_by_trend_direction(
    mf_data: pl.DataFrame, realized_long: pl.DataFrame
) -> dict[str, Any]:
    trend = _trend_direction_48b(mf_data)
    r3_long = realized_long.filter(pl.col("regime") == "R3").join(trend, on="t0", how="left")
    n_total_r3_long = r3_long.height
    out: dict[str, Any] = {"n_total_r3_long_signals": n_total_r3_long}
    for label, sign in (("R3_alta", 1), ("R3_baixa", -1)):
        sub = r3_long.filter(pl.col("trend_sign_48b") == sign)
        out[label] = _decompose_regime_cell(sub, source=f"faixa1_7::r3_split::{label}")
    frac_r3_alta = (
        out["R3_alta"]["n_trades"] / n_total_r3_long if n_total_r3_long else float("nan")
    )
    out["fracao_do_book_long_em_r3_alta"] = frac_r3_alta
    return out


# ============================================================================
# Medição 2 (Q1) — B1 (qualquer entrada) e B2 (exposição contínua) por
# regime, comparados contra o Alpha (já em stratified_headlines).
#
# Pré-registrado: se o baseline "qualquer entrada" (B1-like) OU o baseline
# "exposição contínua" (B2-like) já mostrar o MESMO padrão R2-ruim/
# R3-R4-bom que o Alpha, a explicação mais parcimoniosa é geometria de
# barreira/mercado (beta), não skill de feature — o Alpha teria que
# SUPERAR essas células, não só repetir o sinal delas, pra contar como
# skill.
# ============================================================================


def b1_any_entry_by_regime(mf_data: pl.DataFrame) -> dict[str, Any]:
    """"B1-like": Sharpe de TODA entrada não-NOFILL na regime, os dois
    lados juntos — mesma definição de população de `run_b1_random_entry`
    (`_non_nofill_pool`, ambos os lados), mas sem sortear: reporta o
    Sharpe do POOL inteiro por regime (equivalente ao limite de
    `sample_size` -> tamanho da população), que é a mesma mecânica já
    usada em `faixa1_6_reconciliation._static_rule_regime_stratification`
    para B3/B5, generalizada aqui pra "qualquer entrada" em vez de uma
    regra específica."""
    df = mf_data.with_columns(pl.col("barrier_hit").cast(pl.Utf8))
    out: dict[str, Any] = {}
    for regime in _STRUCTURAL_REGIMES:
        sub = df.filter((pl.col("regime") == regime) & (pl.col("barrier_hit") != "NOFILL"))
        rets = sub["ret_net"].to_numpy().astype(np.float64) if sub.height else np.array([])
        span = backtest_lite.span_seconds(sub["t0"]) if sub.height else 0.0
        sharpe, _tpy = backtest_lite.sharpe_naive(rets, span_seconds=span)
        out[regime] = {
            "n_trades": int(sub.height),
            "sharpe_naive": sharpe,
            "mean_ret_net_bps": float(np.mean(rets) * 10_000) if rets.size else float("nan"),
        }
    return out


def b2_continuous_exposure_by_regime(mf_data: pl.DataFrame) -> dict[str, Any]:
    """"B2-like": Sharpe de estar sempre COMPRADO (long contínuo, mesmo
    espírito de buy-and-hold do B2 original), condicionado ao regime da
    barra — log-retorno bar-a-bar de `entry_price_limit` (proxy de preço a
    15m; o B2 original usa klines diários de fonte separada, aqui reusamos
    o preço já presente em `mf.data` pra não buscar uma fonte nova),
    marcado pelo regime da barra DE ORIGEM do retorno (t-1 -> t rotulado
    pelo regime em t-1, causal)."""
    px = (
        mf_data.filter(pl.col("side") == 1)
        .select("t0", "entry_price_limit", "regime")
        .unique(subset=["t0"])
        .sort("t0")
    )
    log_px = np.log(px["entry_price_limit"].to_numpy().astype(np.float64))
    bar_ret = np.diff(log_px)
    regime_of_origin = px["regime"].to_list()[:-1]
    out: dict[str, Any] = {}
    for regime in _STRUCTURAL_REGIMES:
        mask = np.array([r == regime for r in regime_of_origin])
        rets = bar_ret[mask]
        if rets.size < 2:
            out[regime] = {"n_bars": int(rets.size), "sharpe_naive": float("nan")}
            continue
        # anualização por barra de 15m -- mesma convenção de bars_per_year
        # de faixa1_5_prerequisites (BARS_PER_YEAR), não uma nova constante.
        mean, std = float(np.mean(rets)), float(np.std(rets, ddof=1))
        sharpe = mean / std * math.sqrt(f15.BARS_PER_YEAR) if std > 0 else float("nan")
        out[regime] = {"n_bars": int(rets.size), "sharpe_naive": sharpe}
    return out


def continuous_exposure_by_side_and_regime(mf_data: pl.DataFrame) -> dict[str, Any]:
    """Espelho short de `b2_continuous_exposure_by_regime` — MESMO
    retorno bar-a-bar (`bar_ret`), sinal invertido pro short (posição
    espelhada no MESMO preço, sem custo/funding — mesma simplificação
    declarada do B2 original). Devolve os dois lados juntos, pra montar
    o gap contra o Alpha (`alpha_vs_naive_continuous_gap`) sem duplicar a
    extração de preço."""
    px = (
        mf_data.filter(pl.col("side") == 1)
        .select("t0", "entry_price_limit", "regime")
        .unique(subset=["t0"])
        .sort("t0")
    )
    log_px = np.log(px["entry_price_limit"].to_numpy().astype(np.float64))
    bar_ret = np.diff(log_px)
    regime_of_origin = px["regime"].to_list()[:-1]

    out: dict[str, Any] = {"long": {}, "short": {}}
    for regime in _STRUCTURAL_REGIMES:
        mask = np.array([r == regime for r in regime_of_origin])
        for side_label, sign in (("long", 1.0), ("short", -1.0)):
            rets = sign * bar_ret[mask]
            if rets.size < 2:
                out[side_label][regime] = {"n_bars": int(rets.size), "sharpe_naive": float("nan")}
                continue
            mean, std = float(np.mean(rets)), float(np.std(rets, ddof=1))
            sharpe = mean / std * math.sqrt(f15.BARS_PER_YEAR) if std > 0 else float("nan")
            out[side_label][regime] = {"n_bars": int(rets.size), "sharpe_naive": sharpe}
    return out


def alpha_vs_naive_continuous_gap(
    naive_by_side_regime: dict[str, Any], alpha_directional_sharpe_by_side_regime: dict[str, Any]
) -> dict[str, Any]:
    """O teste mais direto de skill seletivo desta rodada: `Alpha
    (directional_sharpe seletivo) - naive (sempre exposto, mesmo lado,
    mesmo regime)`. Positivo = a seleção de ENTRADA do Alpha bate ficar
    simplesmente exposto o tempo todo naquele regime (skill real de
    timing). Negativo = a seleção é PIOR que não selecionar nada — o
    Alpha está escolhendo momentos ativamente ruins dentro de um regime
    que, passivamente, teria sido aceitável ou bom."""
    out: dict[str, Any] = {}
    for side_label in ("long", "short"):
        out[side_label] = {}
        for regime in _STRUCTURAL_REGIMES:
            alpha_val = alpha_directional_sharpe_by_side_regime.get(side_label, {}).get(regime)
            naive_val = naive_by_side_regime.get(side_label, {}).get(regime, {}).get("sharpe_naive")
            gap = (
                alpha_val - naive_val
                if alpha_val is not None and naive_val is not None and math.isfinite(naive_val)
                else None
            )
            out[side_label][regime] = {
                "alpha_directional_sharpe": alpha_val,
                "naive_continuous_sharpe": naive_val,
                "gap_alpha_menos_naive": gap,
            }
    return out


# ============================================================================
# Medição extra (a pedido, pós-síntese) — R3/R4 partidos por direção de
# tendência, os DOIS lados (a Medição 1 original só cobriu long x R3).
# ============================================================================


def trend_split_by_regime_and_side(
    mf_data: pl.DataFrame, realized: pl.DataFrame, *, side: int, side_label: str, regime: str
) -> dict[str, Any]:
    trend = _trend_direction_48b(mf_data)
    pop = realized.filter((pl.col("side_hat") == side) & (pl.col("regime") == regime)).join(
        trend, on="t0", how="left"
    )
    n_total = pop.height
    out: dict[str, Any] = {"n_total_signals": n_total}
    for label, sign in (("alta", 1), ("baixa", -1)):
        sub = pop.filter(pl.col("trend_sign_48b") == sign)
        out[label] = _decompose_regime_cell(
            sub, source=f"faixa1_7::trend_split::{side_label}_{regime}_{label}"
        )
    n_alta = out["alta"]["n_trades"]
    out["fracao_em_alta"] = n_alta / n_total if n_total else float("nan")
    return out


# ============================================================================
# Medição 3 (Q1) — IC de E02f contra PnL_carry vs PnL_direcional,
# separados (sem retreino).
#
# Pré-registrado: |IC(E02f, carry)| >> |IC(E02f, direcional)| => identidade
# contábil confirmada, efeito do T0 é carry mal atribuído no relatório
# anterior (Faixa 1.6 mediu a queda em directional_sharpe, mas a CAUSA
# pode ainda ser carry se a seleção de trade mudar a composição de forma
# que desloque o directional_sharpe indiretamente). |IC(E02f, direcional)|
# comparável ou maior => a restrição está fazendo algo além do anunciado;
# não invalida o ganho do T0, muda a explicação e reforça a necessidade do
# controle de sinal aleatório antes de canonizar.
# ============================================================================


def _build_oof_population_with_pnl_components(
    predictions: pl.DataFrame, mf_data: pl.DataFrame, *, side_filter: int
) -> pl.DataFrame:
    """Mesma semântica de junção de
    `faixa1_6_reconciliation._build_oof_population` (OOF, filled,
    side_hat == side_filter), mas com `ret_gross`/`funding_bps` extras --
    os dois termos de `src.models.decomposition.decompose` que esta
    medição precisa separar (aquela função só seleciona o necessário para
    IC por regime, não os componentes de PnL)."""
    preds = predictions.filter(
        pl.col("is_oof") & (pl.col("side_hat") != 0) & (pl.col("side_hat") == side_filter)
    ).select("t0", "fold_id", "side_hat")
    mf_small = mf_data.select(
        ["t0", "side", "barrier_hit", "ret_net", "ret_gross", "funding_bps", _E02F_FEATURE]
    ).with_columns(pl.col("barrier_hit").cast(pl.Utf8))
    joined = preds.join(mf_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner")
    return joined.filter(pl.col("barrier_hit") != "NOFILL")


def e02f_ic_carry_vs_directional(
    predictions: pl.DataFrame, mf_data: pl.DataFrame
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for side_label, side in (("long", 1), ("short", -1)):
        pop = _build_oof_population_with_pnl_components(predictions, mf_data, side_filter=side)
        if pop.height == 0:
            out[side_label] = {"ic_e02f_vs_carry": None, "ic_e02f_vs_directional": None, "n": 0}
            continue
        e02f = pop[_E02F_FEATURE].to_numpy().astype(np.float64)
        pnl_carry = -(pop["funding_bps"].to_numpy().astype(np.float64) / 10_000)
        pnl_direcional = pop["ret_gross"].to_numpy().astype(np.float64)
        rho_carry, n_carry = f16._spearman_ic(e02f, pnl_carry)
        rho_dir, n_dir = f16._spearman_ic(e02f, pnl_direcional)
        out[side_label] = {
            "ic_e02f_vs_carry": rho_carry,
            "n_carry": n_carry,
            "ic_e02f_vs_directional": rho_dir,
            "n_directional": n_dir,
            "razao_abs_carry_sobre_direcional": (
                abs(rho_carry) / abs(rho_dir) if math.isfinite(rho_dir) and rho_dir != 0 else None
            ),
        }
    return out


# ============================================================================
# Medição 4 (Q2) — regime one-hot está na matriz de features do Alpha?
#
# Pré-registrado: se NÃO estiver, a resposta é dar a informação ao
# modelo, não filtrar. Se JÁ estiver (como o gain_by_column da Faixa 1.6
# já sugeriu — regime_R2 ~0,95% do gain médio), o problema não é
# informação ausente, é informação SUBUTILIZADA — muda a recomendação
# pra engenharia de interação, não feature nova.
# ============================================================================


def confirm_regime_onehot_in_design_matrix() -> dict[str, Any]:
    from src.models.alpha import DESIGN_COLUMNS, REGIME_DUMMY_COLUMNS, REGIME_ONEHOT_LEVELS

    return {
        "presente": True,
        "colunas": list(REGIME_DUMMY_COLUMNS),
        "niveis_onehot": list(REGIME_ONEHOT_LEVELS),
        "categoria_referencia_drop_first": "R1",
        "design_columns_total": len(DESIGN_COLUMNS),
        "evidencia": (
            "src/models/alpha.py::DESIGN_COLUMNS = "
            "(*T1_FEATURE_IDS, *REGIME_DUMMY_COLUMNS)"
        ),
        "gain_medio_regime_r2_ja_medido": (
            "~0,95% do gain médio (Faixa 1.6 e Bloco 5 anterior) -- informação "
            "presente, mas de baixo peso relativo às 10 features T1 contínuas"
        ),
    }


# ============================================================================
# Medição 5 (Q2) — ortogonalizar confiança contra volatilidade.
#
# Pré-registrado: se a confiança RESIDUALIZADA (removida a componente
# linear de C07_vol_pctile_expanding) ordenar retorno por decil de forma
# significativa (Spearman |rho| com p<0,05, mesmo teste D1 da Faixa 1),
# a confiança é CONSERTÁVEL removendo a contaminação de vol. Se o resíduo
# continuar sem ordenar, o problema não é vol -- é outra coisa (ou não há
# sinal de confiança genuíno pra extrair por essa via).
# ============================================================================


def orthogonalize_confidence_vs_vol(
    predictions: pl.DataFrame, mf_data: pl.DataFrame
) -> dict[str, Any]:
    labels_cols = mf_data.select(["t0", "side", "barrier_hit", "ret_net", "regime"])
    # `build_side_population` só traz regime/COST_FEATURE/E02F_FEATURE do
    # 3o argumento (hardcoded em calibration_diagnostics.py) -- o proxy de
    # vol precisa de um join à parte, não passa pelo mecanismo de `regimes`.
    vol_proxy_cols = mf_data.select(["t0", _VOL_PROXY_FEATURE]).unique(subset=["t0"])
    out: dict[str, Any] = {}
    for side, side_label in ((1, "long"), (-1, "short")):
        pop = caldiag.build_side_population(predictions, labels_cols, mf_data, side=side)
        pop = pop.join(vol_proxy_cols, on="t0", how="left")
        conf = pop["confidence"].to_numpy().astype(np.float64)
        vol = pop[_VOL_PROXY_FEATURE].to_numpy().astype(np.float64)
        ret = pop["ret_net"].to_numpy().astype(np.float64)
        mask = np.isfinite(conf) & np.isfinite(vol) & np.isfinite(ret)
        conf, vol, ret = conf[mask], vol[mask], ret[mask]

        rho_conf_vol, p_conf_vol = spearmanr(conf, vol)

        # residualização OLS simples (diagnóstico, não produção -- global,
        # não por fold; declarado explicitamente, mesma disciplina de
        # `_weighted_hhi`'s "APROXIMAÇÃO declarada" em faixa1_5_prerequisites).
        vol_c = vol - vol.mean()
        vol_c_ss = np.dot(vol_c, vol_c)
        beta = float(np.dot(vol_c, conf - conf.mean()) / vol_c_ss) if vol_c_ss > 0 else 0.0
        conf_resid = conf - beta * vol_c - conf.mean()

        with_decile_conf = pop.filter(
            pl.Series("_mask", mask)
        ) if mask.sum() < pop.height else pop
        # decile do SCORE ORIGINAL (D1, ja existente) vs decile do RESIDUO --
        # reusa decile_profile/rank_correlations com uma coluna extra.
        pop_resid = with_decile_conf.with_columns(pl.Series("confidence_resid", conf_resid))
        profile_original = caldiag.decile_profile(with_decile_conf, confidence_col="confidence")
        corr_original = caldiag._rank_correlations(profile_original)
        profile_resid = caldiag.decile_profile(pop_resid, confidence_col="confidence_resid")
        corr_resid = caldiag._rank_correlations(profile_resid)

        out[side_label] = {
            "n": int(mask.sum()),
            "spearman_confidence_vs_vol_proxy": {
                "rho": float(rho_conf_vol),
                "p": float(p_conf_vol),
            },
            "beta_confidence_on_vol": beta,
            "decile_spearman_confidence_original": corr_original.get("spearman_rho"),
            "decile_spearman_confidence_original_p": corr_original.get("spearman_p"),
            "decile_spearman_confidence_residualizada": corr_resid.get("spearman_rho"),
            "decile_spearman_confidence_residualizada_p": corr_resid.get("spearman_p"),
        }
    return out


# ============================================================================
# Medições pendentes do turno anterior — regime x ano, distribuição de
# feature R2 vs resto (proxy declarado de SHAP-por-regime, ver docstring),
# NOFILL x tercil de custo dentro de R2.
# ============================================================================


def regime_r2_by_year(mf_data: pl.DataFrame) -> dict[str, Any]:
    df = mf_data.filter((pl.col("side") == 1) & (pl.col("regime") == "R2")).with_columns(
        pl.col("barrier_hit").cast(pl.Utf8), pl.col("t0").dt.year().alias("year")
    )
    out: dict[str, Any] = {}
    for year in sorted(df["year"].unique().to_list()):
        sub = df.filter(pl.col("year") == year)
        out[str(year)] = _decompose_regime_cell(sub, source=f"faixa1_7::r2_by_year::{year}")
    return out


def feature_distribution_r2_vs_others(mf_data: pl.DataFrame) -> dict[str, Any]:
    """PROXY declarado de "SHAP condicionado por regime" (medição pendente
    #2 do turno anterior) -- não é SHAP real (os Boosters treinados não
    são persistidos em disco, só gain_by_column agregado; SHAP exigiria
    retreino). Compara a DISTRIBUIÇÃO das 4 features de maior gain
    (já medidas na Faixa 1.6) entre barras R2 e barras R3/R4, lado long --
    evidência indireta de "valores extremos de features vol-sensíveis
    concentram-se em R2", não prova de comportamento do modelo."""
    df = mf_data.filter(pl.col("side") == 1)
    out: dict[str, Any] = {}
    for feature in _TOP_GAIN_FEATURES:
        r2 = (
            df.filter(pl.col("regime") == "R2")[feature]
            .drop_nulls()
            .to_numpy()
            .astype(np.float64)
        )
        trend = (
            df.filter(pl.col("regime").is_in(["R3", "R4"]))[feature]
            .drop_nulls()
            .to_numpy()
            .astype(np.float64)
        )
        out[feature] = {
            "r2_mean": float(np.mean(r2)) if r2.size else float("nan"),
            "r2_std": float(np.std(r2)) if r2.size else float("nan"),
            "r2_p90_abs": float(np.percentile(np.abs(r2), 90)) if r2.size else float("nan"),
            "trend_r3_r4_mean": float(np.mean(trend)) if trend.size else float("nan"),
            "trend_r3_r4_std": float(np.std(trend)) if trend.size else float("nan"),
            "trend_r3_r4_p90_abs": (
                float(np.percentile(np.abs(trend), 90)) if trend.size else float("nan")
            ),
        }
    return out


def nofill_x_cost_tercile_within_r2(mf_data: pl.DataFrame) -> dict[str, Any]:
    df = mf_data.filter((pl.col("side") == 1) & (pl.col("regime") == "R2")).with_columns(
        pl.col("barrier_hit").cast(pl.Utf8)
    )
    cost_valid = df.filter(pl.col("E27f_cost_atr_ratio").is_not_null())["E27f_cost_atr_ratio"]
    if cost_valid.len() < 3:
        return {"aplicavel": False}
    q_low = float(cost_valid.quantile(1 / 3, interpolation="linear"))  # type: ignore[arg-type]
    q_high = float(cost_valid.quantile(2 / 3, interpolation="linear"))  # type: ignore[arg-type]
    out: dict[str, Any] = {}
    for label, lo, hi in (
        ("LOW_COST", None, q_low),
        ("MID_COST", q_low, q_high),
        ("HIGH_COST", q_high, None),
    ):
        expr = pl.col("E27f_cost_atr_ratio").is_not_null()
        if lo is not None:
            expr = expr & (pl.col("E27f_cost_atr_ratio") > lo)
        if hi is not None:
            expr = expr & (pl.col("E27f_cost_atr_ratio") <= hi)
        sub = df.filter(expr)
        n = sub.height
        n_nofill = sub.filter(pl.col("barrier_hit") == "NOFILL").height
        out[label] = {"n": n, "rate_nofill": n_nofill / n if n else float("nan")}
    return out


# ============================================================================
# Orquestração — sem campo de veredito. A síntese Q1/Q2 acontece fora
# deste módulo (relatório ao usuário/SPRINT_LOG), aplicando o critério
# pré-registrado nos docstrings acima aos números aqui.
# ============================================================================


def _load_alpha_directional_sharpe_by_side_regime() -> dict[str, Any]:
    """Relê `stratified_headlines.by_side_regime` já persistido
    (Faixa 1.5/1.6) — não recalcula (mesmo `decompose()` sobre a mesma
    população, já correto ali)."""
    f15_path = EXPERIMENTS_DIR / "faixa1_5_prerequisites.json"
    payload = orjson.loads(f15_path.read_bytes())
    bsr = payload["stratified_headlines"]["by_side_regime"]
    out: dict[str, Any] = {"long": {}, "short": {}}
    for side_label in ("long", "short"):
        for regime in _STRUCTURAL_REGIMES:
            out[side_label][regime] = bsr[f"{side_label}_{regime}"]["directional_sharpe"]["value"]
    return out


def run_faixa1_7() -> dict[str, Any]:
    mf = ds.build_modeling_frame()
    predictions = f15.load_predictions(model_id=pipeline.MODEL_ID_CAMADA1)
    from src.validation import cpcv as cpcv_mod

    cpcv_result = cpcv_mod.generate_splits(mf.data)
    fold_to_path = f15.fold_to_path_map(cpcv_result.splits)
    realized = f15.build_realized_trades(predictions, mf.data, fold_to_path)
    realized_long = realized.filter(pl.col("side_hat") == 1)

    naive_continuous = continuous_exposure_by_side_and_regime(mf.data)
    alpha_dirsharpe = _load_alpha_directional_sharpe_by_side_regime()

    trend_split_r3_r4_both_sides: dict[str, Any] = {}
    for side, side_label in ((1, "long"), (-1, "short")):
        for regime in ("R3", "R4"):
            trend_split_r3_r4_both_sides[f"{side_label}_{regime}"] = (
                trend_split_by_regime_and_side(
                    mf.data, realized, side=side, side_label=side_label, regime=regime
                )
            )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "task": "faixa1_7_edge_or_beta",
        "mfe_por_regime_escopo": (
            "NÃO computado nesta rodada -- exige re-caminhar mark_1m por "
            "trade, computação nova (não reuso de coluna existente). Ver "
            "docstring do módulo para o desenho recomendado (estender "
            "build_labels, não recomputar à parte)."
        ),
        "q1_r3_split_por_direcao_de_tendencia": r3_split_by_trend_direction(mf.data, realized_long),
        "q1_b1_qualquer_entrada_por_regime": b1_any_entry_by_regime(mf.data),
        "q1_b2_exposicao_continua_por_regime": b2_continuous_exposure_by_regime(mf.data),
        "q1_e02f_ic_carry_vs_direcional": e02f_ic_carry_vs_directional(predictions, mf.data),
        "q2_regime_onehot_confirmacao": confirm_regime_onehot_in_design_matrix(),
        "q2_confianca_ortogonalizada_vs_vol": orthogonalize_confidence_vs_vol(predictions, mf.data),
        "pendente_regime_r2_por_ano": regime_r2_by_year(mf.data),
        "pendente_distribuicao_feature_r2_vs_tendencia": feature_distribution_r2_vs_others(mf.data),
        "pendente_nofill_x_custo_dentro_r2": nofill_x_cost_tercile_within_r2(mf.data),
        # Extensão pós-síntese (a pedido) — resposta "milimétrica" a onde
        # o motor acerta no pior-esperado e erra no melhor-esperado.
        "extensao_naive_continuo_por_lado_e_regime": naive_continuous,
        "extensao_gap_alpha_menos_naive": alpha_vs_naive_continuous_gap(
            naive_continuous, alpha_dirsharpe
        ),
        "extensao_trend_split_r3_r4_ambos_lados": trend_split_r3_r4_both_sides,
    }
    return payload


def run_and_save_faixa1_7(*, dest_path: Path | None = None) -> Path:
    """`uv run python -m src.analysis.faixa1_7_edge_or_beta`."""
    payload = run_faixa1_7()
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
    logger.info("analysis.faixa1_7_edge_or_beta.written", path=str(dest))
    return dest


if __name__ == "__main__":
    run_and_save_faixa1_7()
