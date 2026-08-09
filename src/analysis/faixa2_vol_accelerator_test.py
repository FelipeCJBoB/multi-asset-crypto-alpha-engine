"""Faixa 2, pré-FASE 3 — teste do C07 como ACELERADOR, substituindo o
gate de confiança (§5.6), proposto pelo Manager (2026-08-09) a partir do
achado do E3: `C07_vol_pctile_expanding` é o único sinal unânime em
180/180 combinações (§5.4), mas o disparo do modelo é 12,76x MAIOR
justamente onde esse sinal diz "pior" (R1 0,34% vs R2 4,34%, TP rate
28,35% em R2 vs 42,42% em R3).

**Filtro sobre PREDIÇÕES JÁ EXISTENTES de `alpha_c1_v1` — SEM
RETREINO.** Substitui, não soma, o mecanismo de seleção:

1. `side_hat` "solto" — threshold de confiança no mínimo que ainda
   produz `side_hat != 0` (`argmax(p_long, p_short)`, τ→0). O ÚNICO
   filtro de admissão vira o percentil de `C07`.
2. Percentil `P` fixado A PRIORI pelo orçamento (`implied_budget_
   trades_per_year`, mesma âncora de `fase0_orcamento_fees_por_cenario`)
   — bisseção sobre `trades_per_year` médio entre os 5 paths, NUNCA
   olhando performance (B20: se `P` fosse escolhido pelo resultado, seria
   busca de threshold por métrica OOS).
3. Braço de controle: corte ALEATÓRIO retendo a MESMA contagem de trades
   por path que o corte por vol admitiu, `n_seeds`/`base_seed` do B1
   (`config/constants.yaml::alpha_b1_n_seeds`/`alpha_random_seed`, mesma
   convenção de `src.models.baselines.run_b1_random_entry`) — sem este
   braço, qualquer melhora se confunde com o efeito trivial de negociar
   menos (custo de 5,76 bps/trade melhora quase tudo por construção)."""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog

from src.core.provenance import report_provenance
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models.decomposition import decompose
from src.validation import cpcv

from . import faixa1_5_prerequisites as f15

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "faixa2_vol_accelerator_test.json"

_MODEL_ID: Final[str] = "alpha_c1_v1"
_COST_PCTILE_FEATURE: Final[str] = "C07_vol_pctile_expanding"
_STRUCTURAL_REGIMES: Final[tuple[str, ...]] = ("R1", "R2", "R3", "R4")
_SIDES: Final[tuple[int, ...]] = (1, -1)

_JOIN_COLS: Final[tuple[str, ...]] = (
    "t0",
    "side",
    "barrier_hit",
    "ret_net",
    "ret_gross",
    "cost_entry_bps",
    "cost_exit_bps",
    "funding_bps",
    "regime",
    _COST_PCTILE_FEATURE,
)

# Precisao da bisseçao sobre o percentil de C07 -- 40 iteracoes reduz o
# intervalo [0,1] inicial por 2^40, muito alem da precisao que qualquer
# decisao aqui precisa (nao e constante de dominio, e limite de
# convergencia numerica).
_BISECTION_ITERS = 40  # noqa: magic-number


def build_loose_realized_population(symbol: str = "BTCUSDT") -> pl.DataFrame:
    """`side_hat` recomputado de `argmax(p_long, p_short)` (threshold de
    confiança no mínimo que ainda produz sinal) -- substitui a coluna
    `side_hat` de produção (calibrada por `alpha_calibration_holdout_frac`
    + `tau`), não a soma. Junta com `mf.data` (T1/regime/custos/labels)
    exatamente como `f15.build_realized_trades`, mas pela chave nova."""
    preds = f15.load_predictions(_MODEL_ID).filter(pl.col("is_oof"))
    side_hat_loose = (
        pl.when(pl.col("p_long") >= pl.col("p_short")).then(1).otherwise(-1).cast(pl.Int8)
    )
    preds = preds.select("t0", "fold_id", "p_long", "p_short").with_columns(
        side_hat_loose.alias("side_hat")
    )

    mf = ds.build_modeling_frame(symbol=symbol)
    cpcv_result = cpcv.generate_splits(mf.data)
    fold_to_path = f15.fold_to_path_map(cpcv_result.splits)

    mf_small = mf.data.select(list(_JOIN_COLS)).with_columns(pl.col("barrier_hit").cast(pl.Utf8))
    joined = preds.join(mf_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner")
    path_series = pl.Series(
        "path_id", [fold_to_path[f] for f in joined["fold_id"].to_list()], dtype=pl.Int64
    )
    return joined.with_columns(path_series)


def calibrate_admission_percentile(
    loose_pop: pl.DataFrame, *, target_trades_per_year: float
) -> dict[str, Any]:
    """Bisseção sobre `P` (percentil de `C07_vol_pctile_expanding`, já em
    [0,1] por construção -- o corte É o percentil, sem precisar de
    `.quantile()`): admite `C07 <= P`, mede `trades_per_year` médio entre
    os 5 paths (`f15._trades_per_year_per_path`, mesma métrica de F0.2),
    monotônico em `P` (admitir mais barras nunca reduz a contagem) —
    convergência garantida. NENHUM resultado de performance entra aqui."""
    lo, hi = 0.0, 1.0

    def _mean_tpy(p: float) -> float:
        admitted = loose_pop.filter(pl.col(_COST_PCTILE_FEATURE) <= p)
        per_path = f15._trades_per_year_per_path(admitted)
        finite = [
            v["trades_per_year"] for v in per_path.values() if math.isfinite(v["trades_per_year"])
        ]
        return float(np.mean(finite)) if finite else 0.0

    for _ in range(_BISECTION_ITERS):
        mid = (lo + hi) / 2
        if _mean_tpy(mid) < target_trades_per_year:
            lo = mid
        else:
            hi = mid
    p_final = hi
    return {
        "percentil_admissao": p_final,
        "target_trades_per_year": target_trades_per_year,
        "trades_per_year_no_percentil": _mean_tpy(p_final),
        "nota": (
            "P fixado SOMENTE pelo criterio de volume (trades/ano == "
            "orcamento) -- nenhuma metrica de performance (Sharpe/ret_net) "
            "consultada nesta calibracao, por instrucao explicita do "
            "Manager (evitar B20)."
        ),
    }


def _filled(pop: pl.DataFrame) -> pl.DataFrame:
    return pop.filter(pl.col("barrier_hit") != "NOFILL")


def compute_metrics_battery(pop: pl.DataFrame, *, source: str) -> dict[str, Any]:
    """`decompose()` (directional_sharpe/total_sharpe/carry_share) +
    taxas de barreira, no total e quebrado por lado e por regime -- mesma
    bateria pedida pelo Manager, "antes e depois, lado a lado"."""
    filled = _filled(pop)

    def _slice_metrics(sub: pl.DataFrame, sub_filled: pl.DataFrame, tag: str) -> dict[str, Any]:
        n = sub.height
        rates = f15._barrier_rates(sub) if n else {}
        dec = decompose(sub_filled, source=f"{source}::{tag}")
        ret_net = sub_filled["ret_net"].to_numpy().astype(np.float64)
        return {
            "n_trades_emitidos": n,
            "n_trades_preenchidos": sub_filled.height,
            "rate_tp": rates.get("rate_tp", float("nan")),
            "rate_sl": rates.get("rate_sl", float("nan")),
            "rate_time": rates.get("rate_time", float("nan")),
            "rate_nofill": rates.get("rate_nofill", float("nan")),
            "directional_sharpe": dec.directional_sharpe.value,
            "total_sharpe": dec.total_sharpe.value,
            "carry_share": dec.carry_share.value,
            "ret_net_mean_bps": float(np.mean(ret_net) * 10_000) if ret_net.size else float("nan"),
        }

    out: dict[str, Any] = {"total": _slice_metrics(pop, filled, "total")}
    for side in _SIDES:
        sub = pop.filter(pl.col("side_hat") == side)
        sub_filled = filled.filter(pl.col("side_hat") == side)
        out[f"side_{side}"] = _slice_metrics(sub, sub_filled, f"side_{side}")
    out["by_side_regime"] = {}
    for side in _SIDES:
        for regime in _STRUCTURAL_REGIMES:
            key = f"side_{side}__{regime}"
            sub = pop.filter((pl.col("side_hat") == side) & (pl.col("regime") == regime))
            sub_filled = filled.filter(
                (pl.col("side_hat") == side) & (pl.col("regime") == regime)
            )
            out["by_side_regime"][key] = _slice_metrics(sub, sub_filled, key)
    out["trades_per_year_by_path"] = {
        str(k): v["trades_per_year"] for k, v in f15._trades_per_year_per_path(pop).items()
    }
    return out


def run_random_control_arm(
    loose_pop: pl.DataFrame,
    *,
    admitted_n_by_path: dict[int, int],
    n_seeds: int | None = None,
    base_seed: int | None = None,
) -> dict[str, Any]:
    """Braço de controle pedido pelo Manager: corte ALEATÓRIO retendo a
    MESMA contagem de trades por path que o corte por vol admitiu —
    `n_seeds`/`base_seed` do B1 (mesma convenção determinística de
    `src.models.baselines.run_b1_random_entry`, RNG avançado
    sequencialmente por path dentro de cada réplica). Sem reposição,
    dentro do MESMO pool "solto" (pré-filtro de vol) que o braço do C07
    usa -- comparação justa: mesmo pool, mesma contagem, só o CRITÉRIO de
    admissão muda (aleatório vs percentil de C07)."""
    n_seeds = n_seeds if n_seeds is not None else int(load_constant("alpha_b1_n_seeds"))
    base_seed = base_seed if base_seed is not None else int(load_constant("alpha_random_seed"))

    by_path_pop = {pid: loose_pop.filter(pl.col("path_id") == pid) for pid in admitted_n_by_path}
    rng = np.random.default_rng(base_seed)

    directional_sharpes: list[float] = []
    total_sharpes: list[float] = []
    ret_net_means: list[float] = []
    for _seed_i in range(n_seeds):
        draws: list[pl.DataFrame] = []
        for pid, n_admit in admitted_n_by_path.items():
            pool = by_path_pop[pid]
            n_pool = pool.height
            size = min(n_admit, n_pool)
            idx = rng.choice(n_pool, size=size, replace=False)
            draws.append(pool[idx.tolist()])
        replica = pl.concat(draws, how="vertical") if draws else loose_pop.clear()
        replica_filled = _filled(replica)
        dec = decompose(replica_filled, source="faixa2_vol_accelerator_test::control_replica")
        ret_net = replica_filled["ret_net"].to_numpy().astype(np.float64)
        directional_sharpes.append(dec.directional_sharpe.value)
        total_sharpes.append(dec.total_sharpe.value)
        ret_net_means.append(float(np.mean(ret_net) * 10_000) if ret_net.size else float("nan"))

    ds_arr = np.array(directional_sharpes)
    ts_arr = np.array(total_sharpes)
    rn_arr = np.array(ret_net_means)
    ds_valid = ds_arr[np.isfinite(ds_arr)]
    ts_valid = ts_arr[np.isfinite(ts_arr)]
    rn_valid = rn_arr[np.isfinite(rn_arr)]
    return {
        "n_seeds": n_seeds,
        "base_seed": base_seed,
        "admitted_n_by_path": {str(k): v for k, v in admitted_n_by_path.items()},
        "directional_sharpe_replicas": directional_sharpes,
        "ret_net_mean_bps_replicas": ret_net_means,
        "directional_sharpe_null": {
            "mean": float(np.mean(ds_valid)) if ds_valid.size else float("nan"),
            "std": float(np.std(ds_valid)) if ds_valid.size else float("nan"),
            "p05": float(np.percentile(ds_valid, 5)) if ds_valid.size else float("nan"),
            "p50": float(np.percentile(ds_valid, 50)) if ds_valid.size else float("nan"),
            "p95": float(np.percentile(ds_valid, 95)) if ds_valid.size else float("nan"),
        },
        "total_sharpe_null": {
            "mean": float(np.mean(ts_valid)) if ts_valid.size else float("nan"),
            "p50": float(np.percentile(ts_valid, 50)) if ts_valid.size else float("nan"),
        },
        "ret_net_mean_bps_null": {
            "mean": float(np.mean(rn_valid)) if rn_valid.size else float("nan"),
            "p50": float(np.percentile(rn_valid, 50)) if rn_valid.size else float("nan"),
        },
    }


def _percentile_of_value(null_values: list[float], value: float) -> float:
    arr = np.array(null_values)
    valid = arr[np.isfinite(arr)]
    if not valid.size or not math.isfinite(value):
        return float("nan")
    return float(np.mean(valid < value) * 100.0)  # noqa: magic-number -- fracao -> percentual


def run_vol_accelerator_test(symbol: str = "BTCUSDT") -> dict[str, Any]:
    target_tpy = float(load_constant("target_signal_rate")) * f15.BARS_PER_YEAR

    loose_pop = build_loose_realized_population(symbol)
    calib = calibrate_admission_percentile(loose_pop, target_trades_per_year=target_tpy)
    p_star = calib["percentil_admissao"]

    admitted = loose_pop.filter(pl.col(_COST_PCTILE_FEATURE) <= p_star)
    admitted_n_by_path = {
        int(pid): admitted.filter(pl.col("path_id") == pid).height
        for pid in sorted(loose_pop["path_id"].unique().to_list())
    }
    frac_retained = admitted.height / loose_pop.height if loose_pop.height else float("nan")

    metrics_vol_filter = compute_metrics_battery(
        admitted, source="faixa2_vol_accelerator_test::vol_filter"
    )

    mf = ds.build_modeling_frame(symbol=symbol)
    cpcv_result = cpcv.generate_splits(mf.data)
    fold_to_path = f15.fold_to_path_map(cpcv_result.splits)
    preds_producao = f15.load_predictions(_MODEL_ID)
    realized_producao = f15.build_realized_trades(preds_producao, mf.data, fold_to_path)
    metrics_producao = compute_metrics_battery(
        realized_producao, source="faixa2_vol_accelerator_test::producao_atual"
    )

    control = run_random_control_arm(loose_pop, admitted_n_by_path=admitted_n_by_path)

    vol_alta_share_long = (
        loose_pop.filter(
            (pl.col("side_hat") == 1) & pl.col("regime").is_in(["R2", "R4"])
        ).height
        / loose_pop.filter(pl.col("side_hat") == 1).height
        if loose_pop.filter(pl.col("side_hat") == 1).height
        else float("nan")
    )

    comparison = {
        "directional_sharpe": {
            "producao_atual": metrics_producao["total"]["directional_sharpe"],
            "vol_filter": metrics_vol_filter["total"]["directional_sharpe"],
            "controle_aleatorio_null_p50": control["directional_sharpe_null"]["p50"],
            "vol_filter_percentil_vs_controle": _percentile_of_value(
                control["directional_sharpe_replicas"],
                metrics_vol_filter["total"]["directional_sharpe"],
            ),
        },
        "ret_net_mean_bps": {
            "producao_atual": metrics_producao["total"]["ret_net_mean_bps"],
            "vol_filter": metrics_vol_filter["total"]["ret_net_mean_bps"],
            "controle_aleatorio_null_p50": control["ret_net_mean_bps_null"]["p50"],
            "vol_filter_percentil_vs_controle": _percentile_of_value(
                control["ret_net_mean_bps_replicas"],
                metrics_vol_filter["total"]["ret_net_mean_bps"],
            ),
        },
    }

    return {
        "target_trades_per_year": target_tpy,
        "calibracao_percentil": calib,
        "fracao_retida": frac_retained,
        "vol_alta_share_dos_trades_long_no_pool_solto": vol_alta_share_long,
        "admitted_n_by_path": {str(k): v for k, v in admitted_n_by_path.items()},
        "metrics_producao_atual": metrics_producao,
        "metrics_vol_filter": metrics_vol_filter,
        "controle_aleatorio": control,
        "comparison_summary": comparison,
        "nota": (
            "Filtro sobre predicoes JA EXISTENTES de alpha_c1_v1 -- SEM "
            "RETREINO. side_hat solto = argmax(p_long, p_short) "
            "(threshold de confianca no minimo que ainda produz sinal); "
            "unico filtro de admissao = percentil de C07, fixado A PRIORI "
            "pelo orcamento (nunca por performance). Controle aleatorio "
            "retem a MESMA contagem por path, mesmas sementes do B1 "
            "(config/constants.yaml::alpha_b1_n_seeds/alpha_random_seed) "
            "-- separa 'o sinal de vol funciona' de 'negociar menos ajuda' "
            "(custo de 5,76 bps/trade melhora quase tudo por construcao)."
        ),
    }


def run_and_save_vol_accelerator_test(*, dest_path: Path | None = None) -> Path:
    """Ponto de entrada MANUAL. Chame: `uv run python -c "from
    src.analysis.faixa2_vol_accelerator_test import
    run_and_save_vol_accelerator_test as r; r()"`."""
    t0 = time.perf_counter()
    payload = run_vol_accelerator_test()
    payload["elapsed_seconds_total"] = time.perf_counter() - t0
    payload = {**report_provenance(), "task": "faixa2_vol_accelerator_test", **payload}

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
        "analysis.faixa2_vol_accelerator_test.written",
        path=str(dest),
        elapsed_seconds_total=round(payload["elapsed_seconds_total"], 1),
    )
    return dest


# ============================================================================
# Correção do Manager (2026-08-09): o teste acima testou C07 como
# SUBSTITUTO do gate de confiança sobre TODAS as barras -- percentil 1
# resultante caía numa região onde a própria geometria de barreira já não
# é válida (stop = 1,5x ATR abaixo do piso de quantização R1), confundindo
# "C07 não ajuda direção" com "o corte forçou uma região patológica".
# Teste corrigido: COMPOR, não substituir -- gate de confiança de
# produção INTACTO (`side_hat` real), C07 aplicado SOMENTE sobre o
# conjunto JÁ DISPARADO (~1,89% das barras, não 100%) e o braço de
# controle sorteia do MESMO conjunto disparado (não do universo) -- só
# assim o controle isola o efeito de C07, não o efeito de perder o gate.
# ============================================================================


def build_production_fired_population(symbol: str = "BTCUSDT") -> pl.DataFrame:
    """`f15.build_realized_trades` (gate de confiança de produção
    intacto, `side_hat` REAL de `alpha_c1_v1`) + `C07_vol_pctile_
    expanding` via join adicional por `t0` (fora de `_REALIZED_JOIN_
    COLS`, que não inclui C07)."""
    mf = ds.build_modeling_frame(symbol=symbol)
    cpcv_result = cpcv.generate_splits(mf.data)
    fold_to_path = f15.fold_to_path_map(cpcv_result.splits)
    preds = f15.load_predictions(_MODEL_ID)
    realized = f15.build_realized_trades(preds, mf.data, fold_to_path)
    c07 = mf.data.select("t0", _COST_PCTILE_FEATURE).unique(subset=["t0"])
    return realized.join(c07, on="t0", how="left")


def run_vol_accelerator_test_composed(symbol: str = "BTCUSDT") -> dict[str, Any]:
    """COMPOR: C07 filtra o conjunto JÁ DISPARADO pela produção, não o
    universo. `P` continua fixado a priori pelo mesmo orçamento
    (`trades_per_year == implied_budget`), agora como fração do conjunto
    disparado, não das barras totais. Controle aleatório sorteia do MESMO
    conjunto disparado (`fired`), mesma contagem por path -- isola "C07
    adiciona algo sobre o gate" de "negociar menos ajuda"."""
    target_tpy = float(load_constant("target_signal_rate")) * f15.BARS_PER_YEAR

    fired = build_production_fired_population(symbol)
    calib = calibrate_admission_percentile(fired, target_trades_per_year=target_tpy)
    p_star = calib["percentil_admissao"]

    admitted = fired.filter(pl.col(_COST_PCTILE_FEATURE) <= p_star)
    admitted_n_by_path = {
        int(pid): admitted.filter(pl.col("path_id") == pid).height
        for pid in sorted(fired["path_id"].unique().to_list())
    }
    frac_retained = admitted.height / fired.height if fired.height else float("nan")

    metrics_composed = compute_metrics_battery(
        admitted, source="faixa2_vol_accelerator_test::composed_filter"
    )
    metrics_producao = compute_metrics_battery(
        fired, source="faixa2_vol_accelerator_test::producao_atual"
    )
    control = run_random_control_arm(fired, admitted_n_by_path=admitted_n_by_path)

    comparison = {
        "directional_sharpe": {
            "producao_atual_sem_filtro": metrics_producao["total"]["directional_sharpe"],
            "producao_mais_c07": metrics_composed["total"]["directional_sharpe"],
            "controle_aleatorio_do_disparado_null_p50": control["directional_sharpe_null"]["p50"],
            "composto_percentil_vs_controle": _percentile_of_value(
                control["directional_sharpe_replicas"],
                metrics_composed["total"]["directional_sharpe"],
            ),
        },
        "ret_net_mean_bps": {
            "producao_atual_sem_filtro": metrics_producao["total"]["ret_net_mean_bps"],
            "producao_mais_c07": metrics_composed["total"]["ret_net_mean_bps"],
            "controle_aleatorio_do_disparado_null_p50": control["ret_net_mean_bps_null"]["p50"],
            "composto_percentil_vs_controle": _percentile_of_value(
                control["ret_net_mean_bps_replicas"],
                metrics_composed["total"]["ret_net_mean_bps"],
            ),
        },
    }

    return {
        "target_trades_per_year": target_tpy,
        "calibracao_percentil": calib,
        "fracao_retida_do_conjunto_disparado": frac_retained,
        "admitted_n_by_path": {str(k): v for k, v in admitted_n_by_path.items()},
        "metrics_producao_sem_filtro": metrics_producao,
        "metrics_producao_mais_c07": metrics_composed,
        "controle_aleatorio_do_disparado": control,
        "comparison_summary": comparison,
        "nota": (
            "COMPOR, nao substituir (correcao do Manager sobre o teste "
            "anterior, faixa2_vol_accelerator_test.json): gate de "
            "confianca de producao INTACTO (side_hat real de "
            "alpha_c1_v1); C07 filtra SOMENTE o conjunto ja disparado "
            "(~1,89% das barras), nao 100% -- evita a regiao patologica "
            "de vol extremamente baixa (stop=1,5xATR abaixo do piso de "
            "quantizacao R1) que o teste anterior expos sem querer. "
            "Controle aleatorio sorteia do MESMO conjunto disparado, "
            "mesmas sementes do B1 -- isola 'C07 adiciona algo sobre o "
            "gate' de 'negociar menos ajuda'."
        ),
    }


def run_and_save_vol_accelerator_test_composed(*, dest_path: Path | None = None) -> Path:
    """Ponto de entrada MANUAL. Chame: `uv run python -c "from
    src.analysis.faixa2_vol_accelerator_test import
    run_and_save_vol_accelerator_test_composed as r; r()"`."""
    t0 = time.perf_counter()
    payload = run_vol_accelerator_test_composed()
    payload["elapsed_seconds_total"] = time.perf_counter() - t0
    payload = {**report_provenance(), "task": "faixa2_vol_accelerator_test_composed", **payload}

    dest = (
        dest_path
        if dest_path is not None
        else EXPERIMENTS_DIR / "faixa2_vol_accelerator_test_composed.json"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest)
    logger.info(
        "analysis.faixa2_vol_accelerator_test_composed.written",
        path=str(dest),
        elapsed_seconds_total=round(payload["elapsed_seconds_total"], 1),
    )
    return dest
