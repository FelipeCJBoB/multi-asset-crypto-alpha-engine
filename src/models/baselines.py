"""Cinco baselines nulos — §16.1, RF-024. Mesmo motor que o Alpha
(`ret_net` já calculado por `src.labels.triple_barrier` — barreiras,
custos, quantização e funding idênticos; `backtest_lite.sharpe_naive`
idêntico em todos): B1 aleatório (1.000 sementes), B2 buy-and-hold, B3 só
regime, B4 features embaralhadas (AUC), B5 short permanente (§16.6)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from sklearn.metrics import roc_auc_score

from src.data import lake
from src.features.build import T1_FEATURE_IDS
from src.validation.cpcv import CPCVSplit

from . import backtest_lite
from . import dataset as ds
from ._constants import load_constant
from .alpha import FoldResult, build_design_matrix

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

_MIN_CLASSES_FOR_AUC = 2  # noqa: magic-number — roc_auc_score exige as 2 classes presentes


# ============================================================================
# B1 — entrada aleatória, 1.000 sementes (§16.1)
# ============================================================================


@dataclass(frozen=True, slots=True)
class B1Result:
    n_seeds: int
    sample_size: int
    null_sharpes: FloatArray
    alpha_sharpe: float
    percentile: float


def run_b1_random_entry(
    df_all: pl.DataFrame,
    *,
    sample_size: int,
    alpha_sharpe: float,
    n_seeds: int | None = None,
    base_seed: int | None = None,
) -> B1Result:
    """`sample_size` deve ser o número REAL de trades preenchidos que o
    Alpha produziu (mesma taxa de sinal, texto literal do §16.1) — o
    chamador passa isso, este módulo não decide sozinho o tamanho da
    amostra nula. Pool = todos os trades NÃO-NOFILL do dataset inteiro
    (os dois lados), porque uma "entrada aleatória" não sabe escolher lado
    — sortear dentre os dois lados já realizados é a leitura mais direta de
    "lado sorteado" (texto do §16.1)."""
    n_seeds = n_seeds if n_seeds is not None else int(load_constant("alpha_b1_n_seeds"))
    base_seed = base_seed if base_seed is not None else int(load_constant("alpha_random_seed"))

    pool = df_all.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    ret_arr = pool["ret_net"].to_numpy().astype(np.float64)
    t0_col = pool["t0"]
    n_pool = ret_arr.shape[0]

    effective_size = min(sample_size, n_pool)
    if effective_size < sample_size:
        logger.warning(
            "models.baselines.b1_sample_clamped", requested=sample_size, pool_size=n_pool
        )

    rng = np.random.default_rng(base_seed)
    null_sharpes = np.empty(n_seeds, dtype=np.float64)
    for i in range(n_seeds):
        idx = rng.choice(n_pool, size=effective_size, replace=False)
        sample_rets = ret_arr[idx]
        sample_t0 = t0_col[idx]
        span = backtest_lite.span_seconds(sample_t0)
        sharpe, _ = backtest_lite.sharpe_naive(sample_rets, span_seconds=span)
        null_sharpes[i] = sharpe

    valid = null_sharpes[np.isfinite(null_sharpes)]
    # 100.0 é conversão fração -> percentual (definição matemática, não
    # constante de domínio) — mesma categoria de `_BPS_PER_UNIT` em
    # `src.labels.triple_barrier`.
    percentile = float(np.mean(valid < alpha_sharpe) * 100.0) if valid.size else float("nan")  # noqa: magic-number

    result = B1Result(
        n_seeds=n_seeds,
        sample_size=effective_size,
        null_sharpes=null_sharpes,
        alpha_sharpe=alpha_sharpe,
        percentile=percentile,
    )
    logger.info(
        "models.baselines.run_b1_random_entry",
        n_seeds=n_seeds,
        sample_size=effective_size,
        alpha_sharpe=alpha_sharpe,
        percentile=percentile,
        null_mean=float(np.nanmean(null_sharpes)),
        null_p95=float(np.nanpercentile(valid, 95)) if valid.size else float("nan"),
    )
    return result


# ============================================================================
# B2 — buy-and-hold BTCUSDT sem alavancagem (§16.1)
# ============================================================================


@dataclass(frozen=True, slots=True)
class B2Result:
    sharpe_naive: float
    n_days: int
    mean_daily_log_ret: float
    std_daily_log_ret: float


def run_b2_buy_and_hold(symbol: str, start: str, end: str) -> B2Result:
    """Retorno diário (log) do close do perpétuo, sem alavancagem, sem
    funding/fees — o "prêmio direcional do ativo" puro (§16.1: "contexto,
    não meta"). `sharpe_naive` aplicado sobre retornos DIÁRIOS, não sobre
    trades — anualização por `sqrt(365,25)` (dias corridos, não dias
    úteis, consistente com um ativo 24/7)."""
    daily = lake.query_bars(symbol, "1d", start, end, source="klines_1m", cast_prices=True)
    close = daily.sort("open_time")["close"].cast(pl.Float64).to_numpy()
    if close.shape[0] < 2:  # noqa: magic-number — mínimo para 1 log-retorno existir
        return B2Result(
            sharpe_naive=float("nan"), n_days=int(close.shape[0]),
            mean_daily_log_ret=float("nan"), std_daily_log_ret=float("nan"),
        )
    log_ret = np.diff(np.log(close))
    mean = float(np.mean(log_ret))
    std = float(np.std(log_ret, ddof=1))
    sharpe = mean / std * float(np.sqrt(backtest_lite.DAYS_PER_YEAR)) if std > 0.0 else float("nan")
    result = B2Result(
        sharpe_naive=sharpe, n_days=int(close.shape[0]),
        mean_daily_log_ret=mean, std_daily_log_ret=std,
    )
    logger.info("models.baselines.run_b2_buy_and_hold", **asdict(result))
    return result


# ============================================================================
# B3 (regra estática, só regime) / B5 (short permanente) — §16.1/§16.6
# ============================================================================


@dataclass(frozen=True, slots=True)
class StaticRuleResult:
    name: str
    n_signals: int
    n_filled_trades: int
    fill_rate: float
    sharpe_naive: float
    mean_trade_ret: float
    trades_per_year: float


def _static_rule_result(name: str, trades: pl.DataFrame) -> StaticRuleResult:
    n_signals = trades.height
    filled = trades.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    n_filled = filled.height
    fill_rate = float(n_filled) / float(n_signals) if n_signals > 0 else float("nan")
    span = backtest_lite.span_seconds(filled["t0"])
    rets = filled["ret_net"].to_numpy().astype(np.float64)
    sharpe, tpy = backtest_lite.sharpe_naive(rets, span_seconds=span)
    mean_ret = float(np.mean(rets)) if rets.size else float("nan")
    result = StaticRuleResult(
        name=name, n_signals=n_signals, n_filled_trades=n_filled, fill_rate=fill_rate,
        sharpe_naive=sharpe, mean_trade_ret=mean_ret, trades_per_year=tpy,
    )
    logger.info("models.baselines.static_rule", **asdict(result))
    return result


def run_b3_regime_only(df_all: pl.DataFrame) -> StaticRuleResult:
    """Long em R3/R4 com `A13_dist_ema48_atr > 0`, sem Alpha (§16.1) — regra
    estática aplicada sobre o dataset INTEIRO (não há ajuste/fit nenhum
    aqui, então não há fold de CPCV a respeitar — a regra não "aprende"
    nada da amostra)."""
    trades = df_all.filter(
        (pl.col("side") == 1)
        & pl.col("regime").is_in(["R3", "R4"])
        & (pl.col("A13_dist_ema48_atr") > 0.0)
        & pl.col("A13_dist_ema48_atr").is_not_null()
    ).sort("t0")
    return _static_rule_result("B3_regime_only", trades)


def run_b5_short_permanent(df_all: pl.DataFrame) -> StaticRuleResult:
    """Short permanente, mesmo sizing conceitual (§16.6) — isola o carry
    puro: todo `t0` com label do lado curto (exceto warmup, já fora de
    `df_all` via `build_modeling_frame`)."""
    trades = df_all.filter(pl.col("side") == -1).sort("t0")
    return _static_rule_result("B5_short_permanent", trades)


# ============================================================================
# B4 — Alpha com features embaralhadas (§16.1) — AUC deve colapsar a ~0,5
# ============================================================================


@dataclass(frozen=True, slots=True)
class B4Result:
    auc_real_long: float
    auc_permuted_long: float
    auc_real_short: float
    auc_permuted_short: float
    auc_real_pooled: float
    auc_permuted_pooled: float
    n_eval_long: int
    n_eval_short: int


def _pool_auc(y_parts: list[IntArray], s_parts: list[FloatArray]) -> float:
    if not y_parts:
        return float("nan")
    y_cat = np.concatenate(y_parts)
    s_cat = np.concatenate(s_parts)
    if np.unique(y_cat).shape[0] < _MIN_CLASSES_FOR_AUC:
        return float("nan")
    return float(roc_auc_score(y_cat, s_cat))


def run_b4_feature_shuffle(
    df_all: pl.DataFrame,
    splits: tuple[CPCVSplit, ...],
    camada1_fold_results: list[FoldResult],
    *,
    seed: int | None = None,
) -> B4Result:
    """Reusa os modelos JÁ TREINADOS da Camada 1 (nenhum retreino — B4 é um
    teste de AVALIAÇÃO, não um variante de treino) — embaralha cada uma das
    10 colunas T1 INDEPENDENTEMENTE, dentro do conjunto de teste de cada
    fold (mantém a marginal de cada coluna, destrói a associação linha a
    linha entre feature e alvo, texto literal do §16.1). Colunas de regime
    (one-hot) NÃO são embaralhadas — não são "as features" no sentido do
    vetor T1 (§2.13), são o estado conhecido da barra."""
    seed = seed if seed is not None else int(load_constant("alpha_random_seed"))
    rng = np.random.default_rng(seed)
    n_t1 = len(T1_FEATURE_IDS)

    split_by_id = {s.split_id: s for s in splits}
    y_real_long: list[IntArray] = []
    s_real_long: list[FloatArray] = []
    s_perm_long: list[FloatArray] = []
    y_real_short: list[IntArray] = []
    s_real_short: list[FloatArray] = []
    s_perm_short: list[FloatArray] = []

    for fr in camada1_fold_results:
        split = split_by_id[fr.fold_id]
        test_bars = df_all[split.test_idx]
        for side, model, y_acc, sreal_acc, sperm_acc in (
            (1, fr.long_result.model, y_real_long, s_real_long, s_perm_long),
            (-1, fr.short_result.model, y_real_short, s_real_short, s_perm_short),
        ):
            test_side = ds.side_subset(test_bars, side=side)
            if test_side.height == 0:
                continue
            X = build_design_matrix(test_side)
            y = (test_side["label"].cast(pl.Int64) == 1).to_numpy().astype(np.int64)
            p_real = model.predict_proba(X)[:, 1]

            X_perm = X.copy()
            for j in range(n_t1):
                perm_idx = rng.permutation(X_perm.shape[0])
                X_perm[:, j] = X_perm[perm_idx, j]
            p_perm = model.predict_proba(X_perm)[:, 1]

            y_acc.append(y)
            sreal_acc.append(p_real)
            sperm_acc.append(p_perm)

    auc_real_long = _pool_auc(y_real_long, s_real_long)
    auc_perm_long = _pool_auc(y_real_long, s_perm_long)
    auc_real_short = _pool_auc(y_real_short, s_real_short)
    auc_perm_short = _pool_auc(y_real_short, s_perm_short)
    auc_real_pooled = _pool_auc(y_real_long + y_real_short, s_real_long + s_real_short)
    auc_perm_pooled = _pool_auc(y_real_long + y_real_short, s_perm_long + s_perm_short)

    result = B4Result(
        auc_real_long=auc_real_long,
        auc_permuted_long=auc_perm_long,
        auc_real_short=auc_real_short,
        auc_permuted_short=auc_perm_short,
        auc_real_pooled=auc_real_pooled,
        auc_permuted_pooled=auc_perm_pooled,
        n_eval_long=int(sum(a.shape[0] for a in y_real_long)),
        n_eval_short=int(sum(a.shape[0] for a in y_real_short)),
    )
    logger.info("models.baselines.run_b4_feature_shuffle", **asdict(result))
    return result
