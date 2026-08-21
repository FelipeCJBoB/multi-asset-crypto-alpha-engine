"""Faixa 2 E2 — ranking por ortogonalidade incremental das candidatas T2
(§2.2-2.12), passe de pesquisa liberado pelo Manager (2026-08-09): "sem
curadoria... ranqueadas por ortogonalidade incremental contra o T1 de 8,
parando em hhi_efetivo de 12-15. 1 trial." + "medir explicitamente a
correlação de cada candidata com C07_vol_pctile_expanding e reportar. Uma
candidata que só adiciona mais um ângulo de vol não deve subir, mesmo que
a ortogonalidade contra o conjunto inteiro pareça boa."

**Correlação POOLED, não in-fold** — deliberado (mesma leitura de
`src.models.hhi`/E2 original: "a triagem final é in-fold (Camada 2), nunca
a tabela pooled"). Isto é a busca EXPLORATÓRIA que decide QUAIS
candidatas entram no conjunto ampliado; a decisão de PERMANÊNCIA de cada
uma, por fold, é do E3 (Camada 2), que ainda não rodou.

**Pesos uniformes na projeção de `n_eff_factors`** — nenhum candidato
passou por um XGBoost ainda (isso só aconteceria ao retreinar a Camada 1
sob o T1 ampliado, fora do escopo desta rodada). `compute_effective_
concentration` cai para peso uniforme quando `gain_by_column` está vazio
(mesmo fallback já documentado na função) — usado aqui deliberadamente,
não um acidente: mede REDUNDÂNCIA DE INFORMAÇÃO (estrutura de correlação),
não importância preditiva (isso é o `n_lifetime`/permutação de pré-E2
(2), método diferente, pergunta diferente)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from research import _sources_research as sr
from research import research_t2 as r2
from src.core.provenance import report_provenance
from src.data import lake
from src.features import _sources
from src.features._constants import load_constant
from src.features.build import T1_FEATURE_IDS, compute_t1_features
from src.features.groups import group_c
from src.models.hhi import compute_effective_concentration

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "faixa2_e2_research.json"

# T1 reduzido pós pré-E2 (2) -- E27f_cost_atr_ratio e A13_dist_ema48_atr
# descartadas por importância por permutação negativa/menor no par.
CURRENT_T1: Final[tuple[str, ...]] = (
    "A05_ret_vol_norm_4",
    "B01_rsi_14",
    "C06_vol_ratio_12_96",
    "C07_vol_pctile_expanding",
    "D03f_volume_z_expanding",
    "D06f_taker_imbalance_z_48",
    "E02f_funding_z_expanding",
    "E10f_oi_change_z_48",
)
# Descartadas em pré-E2 (2) por importância por permutação -- fora de
# candidatura aqui (decisão já tomada, critério diferente/já aplicado;
# esta rodada é sobre ortogonalidade, não re-litiga a de importância).
# Mantidas na matriz de correlação só como REFERÊNCIA (ex. mostrar o
# corr(E27f, C07)=-0,72 que ajudou a motivar o descarte), nunca elegíveis
# pra seleção gulosa.
_ALREADY_DECIDED_AGAINST: Final[frozenset[str]] = frozenset(
    {"E27f_cost_atr_ratio", "A13_dist_ema48_atr"}
)
_VOL_PROXY_FEATURE = "C07_vol_pctile_expanding"
# 12-15: alvo de n_eff_factors literal da task original de E2 ("Alvo é
# hhi_efetivo... sair de 5,3 fatores independentes para 12-15"), citado,
# não escolhido nesta rodada.
_N_EFF_TARGET_LOW = 12.0  # noqa: magic-number
_N_EFF_TARGET_HIGH = 15.0  # noqa: magic-number
_HIGH_VOL_CORR_FLAG_THRESHOLD = 0.60  # noqa: magic-number -- limiar de sinalização, não gate


def build_research_candidates_frame(
    symbol: str, start: str, end: str
) -> tuple[pl.DataFrame, dict[str, str]]:
    """Carrega TODAS as fontes (bars/funding/oi/metrics-wide/bvol/
    agg_order_flow) uma vez, computa T1-8 + todas as candidatas T2
    computáveis (`research_t2`), devolve `(frame, avisos_de_cobertura)` —
    `frame` tem `t0` (=close_time) + uma coluna por feature.

    Grupo H (on-chain) DESCONTINUADO (2026-08-21) -- ver
    `audit/architecture_gaps_log.yaml::AG-135`: só 5/11 features
    computáveis com o dado real disponível, BTC-only (sem cobertura pros
    outros 4 ativos), 2 delas com gaps de licenciamento/dado prováveis.
    Não é mais carregado nem computado aqui."""
    bars_15m = _sources.load_bars_15m(symbol, start, end)
    funding_aligned = _sources.load_funding_aligned(bars_15m, symbol, start, end)
    oi_aligned = _sources.load_oi_aligned(bars_15m, symbol, start, end)
    metrics_wide = sr.load_metrics_wide_aligned(bars_15m, symbol, start, end)
    bvol_aligned = sr.load_bvol_aligned(bars_15m, start, end)
    agg_flow_aligned = sr.load_agg_order_flow_imbalance_aligned(bars_15m, symbol, start, end)

    funding_raw = lake.query_funding(symbol, start, end)
    # 8.0h: fallback só se `funding_raw` vier vazio (intervalo padrão
    # documentado da Binance, LITERATURE -- mesma fonte de
    # `listen_key_validity_s` em constants.yaml); o valor REAL é sempre
    # medido de `funding_interval_hours` quando há dado.
    default_funding_interval_hours = 8.0  # noqa: magic-number
    funding_interval_hours = (
        float(funding_raw["funding_interval_hours"][0])
        if funding_raw.height
        else default_funding_interval_hours
    )

    close = bars_15m["close"].cast(pl.Float64).to_numpy()
    high = bars_15m["high"].cast(pl.Float64).to_numpy()
    low = bars_15m["low"].cast(pl.Float64).to_numpy()
    close_time_ms = bars_15m["close_time"].cast(pl.Float64).to_numpy()
    open_time_ms = bars_15m["open_time"].cast(pl.Float64).to_numpy()

    # I-b (PRD_V4_1.md T0.1): era literal 20 -- banned pattern ativo, uma
    # varredura de atr_window não alcançava esta chamada.
    atr_20_abs = group_c.c01_atr_20(high, low, close, int(load_constant("atr_window")))
    atr_20_pct = group_c.c02_atr_20_pct(atr_20_abs, close)
    log_return_1 = np.full(close.shape[0], np.nan, dtype=np.float64)
    log_return_1[1:] = np.log(close[1:] / close[:-1])
    log_return_12 = np.full(close.shape[0], np.nan, dtype=np.float64)
    if close.shape[0] > 12:
        log_return_12[12:] = np.log(close[12:] / close[:-12])

    bvol_arr = bvol_aligned.to_numpy().astype(np.float64)
    bvol_coverage = float(np.mean(np.isfinite(bvol_arr))) if bvol_arr.size else 0.0

    # T1 atual (10) + C01/C02 (support, também candidatas T2 por tier) --
    # reusa compute_t1_features de producao, NAO reimplementado aqui, pra
    # garantir que a matriz de correlacao trata o T1 EXATAMENTE como o
    # modelo o ve (mesmos primitivos, mesma mascara de warmup). B07 sai
    # (ja vem de group_b_research, mesmo primitivo -- evita coluna
    # duplicada com valor identico).
    t1_frame = compute_t1_features(bars_15m, funding_aligned, oi_aligned)
    columns: dict[str, FloatArray] = {
        fid: t1_frame[fid].cast(pl.Float64).to_numpy() for fid in T1_FEATURE_IDS
    }
    columns["C01_atr_20"] = t1_frame["C01_atr_20"].cast(pl.Float64).to_numpy()
    columns["C02_atr_20_pct"] = t1_frame["C02_atr_20_pct"].cast(pl.Float64).to_numpy()

    columns.update(r2.group_a_research(bars_15m, atr_20_pct))
    columns.update(r2.group_b_research(bars_15m, atr_20_abs))
    columns.update(
        r2.group_c_research(
            bars_15m,
            log_return_1,
            atr_20_abs,
            atr_20_pct,
            bvol_aligned=bvol_arr if bvol_coverage > 0 else None,
        )
    )
    columns.update(
        r2.group_d_research(bars_15m, order_flow_imb_1m_agg=None)
    )
    columns.update(
        r2.group_e_research(
            funding_aligned.to_numpy().astype(np.float64),
            funding_interval_hours,
            metrics_wide["sum_open_interest_value"].to_numpy().astype(np.float64),
            oi_aligned.to_numpy().astype(np.float64),
            close,
            log_return_12,
            metrics_wide["sum_toptrader_long_short_ratio"].to_numpy().astype(np.float64),
            metrics_wide["count_long_short_ratio"].to_numpy().astype(np.float64),
            metrics_wide["sum_taker_long_short_vol_ratio"].to_numpy().astype(np.float64),
            close_time_ms,
            agg_order_flow_imb=agg_flow_aligned.to_numpy().astype(np.float64),
        )
    )
    columns.update(r2.group_k_research(open_time_ms))

    frame = pl.DataFrame({"t0": bars_15m["close_time"], **columns})

    coverage_warnings: dict[str, str] = {}
    if bvol_coverage > 0:
        coverage_warnings["C13_bvol_index"] = (
            f"cobertura {bvol_coverage:.1%} do periodo -- BVOL so existe desde 2023-06-20"
        )
        coverage_warnings["C14_bvol_z_90d"] = coverage_warnings["C13_bvol_index"]
        coverage_warnings["C15_iv_rv_spread"] = coverage_warnings["C13_bvol_index"]
    return frame, coverage_warnings


def pairwise_corr_matrix(data: dict[str, FloatArray]) -> tuple[FloatArray, tuple[str, ...]]:
    """Correlação de Pearson PAIRWISE-COMPLETE (cada par usa só as linhas
    onde AMBAS as colunas são finitas) — necessário porque a cobertura
    difere muito entre candidatas (BVOL ~3,1 anos, on-chain diário, T1
    ~6,6 anos completos)."""
    names = tuple(data.keys())
    n = len(names)
    mat = np.full((n, n), np.nan, dtype=np.float64)
    for i in range(n):
        mat[i, i] = 1.0
        for j in range(i + 1, n):
            x, y = data[names[i]], data[names[j]]
            mask = np.isfinite(x) & np.isfinite(y)
            if int(mask.sum()) < 30:  # mínimo trivial pra correlação fazer sentido
                continue
            xm, ym = x[mask], y[mask]
            if np.std(xm) == 0.0 or np.std(ym) == 0.0:
                continue
            rho = float(np.corrcoef(xm, ym)[0, 1])
            mat[i, j] = rho
            mat[j, i] = rho
    return mat, names


def _n_eff_for_subset(
    full_corr: FloatArray, name_to_idx: dict[str, int], subset: list[str]
) -> float:
    idx = [name_to_idx[s] for s in subset]
    sub_corr = full_corr[np.ix_(idx, idx)]
    result = compute_effective_concentration(sub_corr, {}, tuple(subset))
    return float(result.n_eff_factors.value)


def greedy_select_by_orthogonality(
    corr_matrix: FloatArray,
    names: tuple[str, ...],
    *,
    current_t1: tuple[str, ...],
    vol_proxy: str,
    target_low: float,
    target_high: float,
) -> dict[str, Any]:
    name_to_idx = {n: i for i, n in enumerate(names)}
    selected = [f for f in current_t1 if f in name_to_idx]
    candidates = [
        n for n in names if n not in selected and n not in _ALREADY_DECIDED_AGAINST
    ]

    initial_n_eff = _n_eff_for_subset(corr_matrix, name_to_idx, selected)
    n_eff_history: list[dict[str, Any]] = [
        {"step": 0, "feature_added": None, "n_eff_factors": initial_n_eff}
    ]
    vol_corr_by_candidate: dict[str, float] = {}
    vol_idx = name_to_idx.get(vol_proxy, -1)
    for c in candidates:
        if c == vol_proxy or c not in name_to_idx:
            continue
        rho = corr_matrix[name_to_idx[c], vol_idx] if vol_idx >= 0 else float("nan")
        vol_corr_by_candidate[c] = float(rho) if math.isfinite(rho) else float("nan")

    step = 0
    while n_eff_history[-1]["n_eff_factors"] < target_high and candidates:
        step += 1
        best_candidate = None
        best_n_eff = -1.0
        for c in candidates:
            if c not in name_to_idx:
                continue
            trial = _n_eff_for_subset(corr_matrix, name_to_idx, [*selected, c])
            if math.isfinite(trial) and trial > best_n_eff:
                best_n_eff = trial
                best_candidate = c
        if best_candidate is None:
            break
        selected.append(best_candidate)
        candidates.remove(best_candidate)
        n_eff_history.append(
            {"step": step, "feature_added": best_candidate, "n_eff_factors": best_n_eff}
        )
        if best_n_eff >= target_low:
            pass  # continua até target_high ou esgotar -- não para no piso

    return {
        "selected_beyond_t1": selected[len(current_t1) :],
        "final_selected_set": selected,
        "final_n_eff_factors": n_eff_history[-1]["n_eff_factors"],
        "n_eff_target": [target_low, target_high],
        "reached_target": n_eff_history[-1]["n_eff_factors"] >= target_low,
        "selection_history": n_eff_history,
        "vol_proxy_correlation_by_candidate": vol_corr_by_candidate,
    }


def flag_vol_saturated_selections(
    selection: dict[str, Any], *, threshold: float = _HIGH_VOL_CORR_FLAG_THRESHOLD
) -> list[dict[str, Any]]:
    """Pedido explícito do Manager: sinalizar candidatas PROMOVIDAS cujo
    |corr| com C07 é alta, mesmo que a ortogonalidade contra o conjunto
    inteiro tenha parecido boa (correlação com UMA feature específica,
    C07, é uma pergunta diferente de "quão redundante é com TODO o
    conjunto selecionado")."""
    flags = []
    for feat in selection["selected_beyond_t1"]:
        rho = selection["vol_proxy_correlation_by_candidate"].get(feat)
        if rho is not None and math.isfinite(rho) and abs(rho) >= threshold:
            flags.append({"feature": feat, "corr_com_c07": rho})
    return flags


def run_e2_research(
    symbol: str = "BTCUSDT", start: str = "2020-01-01", end: str = "2026-08-06"
) -> dict[str, Any]:
    frame, coverage_warnings = build_research_candidates_frame(symbol, start, end)
    data = {c: frame[c].to_numpy().astype(np.float64) for c in frame.columns if c != "t0"}

    corr_matrix, names = pairwise_corr_matrix(data)
    selection = greedy_select_by_orthogonality(
        corr_matrix,
        names,
        current_t1=CURRENT_T1,
        vol_proxy=_VOL_PROXY_FEATURE,
        target_low=_N_EFF_TARGET_LOW,
        target_high=_N_EFF_TARGET_HIGH,
    )
    vol_flags = flag_vol_saturated_selections(selection)

    all_vol_corr: dict[str, float] = {}
    idx_vol = names.index(_VOL_PROXY_FEATURE) if _VOL_PROXY_FEATURE in names else -1
    for i, n in enumerate(names):
        if n == _VOL_PROXY_FEATURE:
            continue
        rho = corr_matrix[i, idx_vol] if idx_vol >= 0 else float("nan")
        all_vol_corr[n] = float(rho) if math.isfinite(rho) else float("nan")

    n_candidates_evaluated = len(
        [n for n in names if n not in CURRENT_T1 and n not in _ALREADY_DECIDED_AGAINST]
    )
    return {
        "current_t1_8": list(CURRENT_T1),
        "already_decided_against_excluded_from_candidacy": sorted(_ALREADY_DECIDED_AGAINST),
        "n_candidates_evaluated": n_candidates_evaluated,
        "coverage_warnings": coverage_warnings,
        "correlation_with_c07_all_candidates": all_vol_corr,
        "greedy_selection": selection,
        "vol_saturated_flags_in_selection": vol_flags,
        "nota": (
            "correlacao pooled, pesos uniformes na projecao de n_eff -- "
            "NAO decide promocao a producao (registry.yaml/T1_FEATURE_IDS), "
            "so ranqueia. A decisao de permanencia real e do E3 (Camada 2, "
            "in-fold), ainda nao implementado."
        ),
    }


def run_and_save_e2_research(*, dest_path: Path | None = None) -> Path:
    """Ponto de entrada MANUAL — carrega ~6,5 anos de todas as fontes e
    computa ~60 candidatas, minutos não segundos. Chame: `uv run python -c
    "from src.analysis.faixa2_e2_research import run_and_save_e2_research
    as r; r()"`."""
    import os
    import time

    t0 = time.perf_counter()
    payload = run_e2_research()
    payload["elapsed_seconds_total"] = time.perf_counter() - t0
    payload = {**report_provenance(), "task": "faixa2_e2_research", **payload}

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
        "analysis.faixa2_e2_research.written",
        path=str(dest),
        elapsed_seconds_total=round(payload["elapsed_seconds_total"], 1),
    )
    return dest


if __name__ == "__main__":
    run_and_save_e2_research()
