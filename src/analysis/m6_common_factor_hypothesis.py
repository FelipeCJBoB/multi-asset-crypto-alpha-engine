"""M6 — Hipótese do fator comum (PRD_V4_1.md §3.2, 0 trials).

**Nula (Q1):** `edge_bruto_atr` é o MESMO entre os 5 ativos, e as
diferenças em `ret_net` vêm inteiramente de `custo_atr`.

**Falsificação:** se `edge_bruto_atr` variar significativamente com
direção estável, existe componente idiossincrático além do fator comum —
multi-ativo é diversificação real. Se não variar, os 5 são um ativo com 5
estruturas de custo — a seleção entre eles é puramente econômica.

**Pré-requisito satisfeito em 2026-08-14** (`PLANO_MESTRE_PRINCE2.md`
§15.6 item 4): `data/labels/{symbol}/15m/v1/labels.parquet` existe agora
pros 5 ativos. **Zero trials** — teste de proposição sobre dado já
existente, reusa `src.analysis.feasibility.{edge_bruto_atr,custo_atr,
edge_liq_atr,captura,frac_tp_sl_from_labels}` (§1.2) sem nenhuma fórmula
nova. Não precisa de `predictions.parquet`/modelo treinado — `barrier_hit`
e `atr_at_t0` já estão em `labels.parquet`, medidos direto do Label
Engine, upstream de qualquer Alpha.

**Instrumento de falsificação — heterogeneidade de meta-análise
(Cochran's Q / I², DerSimonian & Laird 1986).** Cada símbolo dá uma
estimativa independente de `edge_bruto_atr` com erro-padrão DERIVADO (não
inventado) da variância multinomial de `frac_TP`/`frac_SL` sobre a
amostra real (`n` ~ dezenas de milhares de trades por símbolo/lado — CLT
aproxima bem, ver `_edge_bruto_se`). `Q = Σ w_i(x_i - x̄)²` (pesos
`w_i=1/SE_i²`) segue `chi²(k-1)` sob H0 (todos os símbolos compartilham o
mesmo `edge_bruto_atr` verdadeiro); `I²` é a fração da variação TOTAL
observada atribuível a heterogeneidade real, não ruído de amostragem —
0% rejeita a hipótese idiossincrática (fator comum sobrevive), I² alto
confirma variação real entre ativos. Mesma classe de instrumento (medição
formal decide, não p-value escolhido a dedo) que M4 já usa (Rand
ajustado, PRD §3.2).

**G-C1-4** (todas as métricas estratificadas por symbol/tf/lado/regime):
tabela completa por `(symbol, side, regime)` reportada para auditoria. O
teste de heterogeneidade em si roda POOLED por `(symbol, side)` — através
de regime — porque estratificar por regime também fragmentaria demais a
amostra pra estimar `SE` com confiança (R0/R5 têm poucos trades — achado
F1 do CLAUDE.md, R0 é ~100% warmup em algumas séries) e porque a pergunta
do M6 é sobre o ativo inteiro, não uma condicional de regime."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from scipy.stats import chi2

from src.analysis.feasibility import captura as compute_captura
from src.analysis.feasibility import custo_atr as compute_custo_atr
from src.analysis.feasibility import edge_bruto_atr as compute_edge_bruto_atr
from src.analysis.feasibility import edge_liq_atr as compute_edge_liq_atr
from src.analysis.feasibility import frac_tp_sl_from_labels
from src.core.provenance import report_provenance
from src.labels.triple_barrier import LabelConfig
from src.models.dataset import REGIME_COL, build_modeling_frame
from src.risk._constants import load_constant as load_risk_constant

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "m6_common_factor_hypothesis_report.json"

# Os 5 ativos do projeto (§0.1) — BTCUSDT (labels/v1/ legado) + os 4 alts
# (data/labels/{symbol}/15m/v1/, gerados em 2026-08-14, §15.6 item 4).
ALL_SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
DECISION_TF: Final[str] = "15m"
SIDES: Final[tuple[int, ...]] = (1, -1)


@dataclass(frozen=True, slots=True)
class StratumMetrics:
    """Um corte — `regime=None` significa pooled através de todos os
    regimes (o corte que alimenta o teste de heterogeneidade)."""

    symbol: str
    side: int
    regime: str | None
    n: int
    frac_tp: float
    frac_sl: float
    frac_time: float
    frac_nofill: float
    edge_bruto_atr: float
    edge_bruto_atr_se: float
    custo_atr: float
    edge_liq_atr: float
    captura: float


def _edge_bruto_se(
    frac_tp: float, frac_sl: float, n: int, *, tp_mult: float, sl_mult: float
) -> float:
    """Erro-padrão de `edge_bruto_atr = frac_TP*tp_mult - frac_SL*sl_mult`
    por propagação linear da variância MULTINOMIAL de `(frac_TP, frac_SL)`
    — as duas vêm da MESMA amostra categórica de `barrier_hit`
    (TP/SL/TIME/NOFILL), não são independentes. Para uma multinomial com
    proporções `p_i` sobre `n` observações: `Var(frac_i) = p_i(1-p_i)/n`,
    `Cov(frac_i, frac_j) = -p_i*p_j/n` (i≠j) — propriedade padrão da
    distribuição, não uma aproximação. `Var(edge) = tp_mult²·Var(frac_TP)
    + sl_mult²·Var(frac_SL) - 2·tp_mult·sl_mult·Cov(frac_TP,frac_SL)`."""
    if n <= 0 or np.isnan(frac_tp) or np.isnan(frac_sl):
        return float("nan")
    var_tp = frac_tp * (1.0 - frac_tp) / n
    var_sl = frac_sl * (1.0 - frac_sl) / n
    cov_tp_sl = -frac_tp * frac_sl / n
    var_edge = (tp_mult**2) * var_tp + (sl_mult**2) * var_sl - 2.0 * tp_mult * sl_mult * cov_tp_sl
    return float(np.sqrt(max(var_edge, 0.0)))


def stratum_metrics(
    labels: pl.DataFrame,
    *,
    symbol: str,
    side: int,
    regime: str | None,
    tp_atr_mult: float,
    sl_atr_mult: float,
    maker_fee: float,
    taker_fee: float,
) -> StratumMetrics:
    """Núcleo puro — `labels` já filtrado pelo chamador (por side, e por
    regime se for o corte detalhado). Sem IO, testável com fixture
    sintética pequena."""
    frac = frac_tp_sl_from_labels(labels)
    eb = compute_edge_bruto_atr(
        frac_tp=frac.frac_tp, frac_sl=frac.frac_sl, tp_atr_mult=tp_atr_mult, sl_atr_mult=sl_atr_mult
    )
    se = _edge_bruto_se(
        frac.frac_tp, frac.frac_sl, frac.n, tp_mult=tp_atr_mult, sl_mult=sl_atr_mult
    )
    if frac.n > 0:
        atr_median = float(labels["atr_at_t0"].median())  # type: ignore[arg-type]
        ca = compute_custo_atr(atr_pct=atr_median, maker_fee=maker_fee, taker_fee=taker_fee)
    else:
        ca = float("nan")
    el = compute_edge_liq_atr(edge_bruto=eb, custo_atr_value=ca)
    cap = compute_captura(edge_liq=el, edge_bruto=eb)
    return StratumMetrics(
        symbol=symbol,
        side=side,
        regime=regime,
        n=frac.n,
        frac_tp=frac.frac_tp,
        frac_sl=frac.frac_sl,
        frac_time=frac.frac_time,
        frac_nofill=frac.frac_nofill,
        edge_bruto_atr=eb,
        edge_bruto_atr_se=se,
        custo_atr=ca,
        edge_liq_atr=el,
        captura=cap,
    )


# ============================================================================
# Heterogeneidade — Cochran's Q / I² (DerSimonian & Laird 1986)
# ============================================================================


@dataclass(frozen=True, slots=True)
class HeterogeneityTest:
    side: int
    k: int
    pooled_edge_bruto_atr: float
    q_statistic: float
    df: int
    p_value: float
    i_squared_pct: float
    per_symbol: tuple[StratumMetrics, ...]


def cochrans_q_heterogeneity(strata: tuple[StratumMetrics, ...]) -> HeterogeneityTest:
    """`strata`: uma `StratumMetrics` (pooled, `regime=None`) por símbolo,
    MESMO `side`. `w_i=1/SE_i²` (peso por precisão inversa); `x̄` = média
    ponderada; `Q = Σw_i(x_i-x̄)²` ~ `chi²(k-1)` sob H0 (mesmo
    `edge_bruto_atr` verdadeiro nos `k` símbolos). `I² = max(0,
    (Q-df)/Q)·100%` — fração da variação TOTAL atribuível a
    heterogeneidade real (Higgins & Thompson 2002, instrumento padrão de
    meta-análise, não inventado aqui)."""
    if len({s.side for s in strata}) != 1:
        raise ValueError("cochrans_q_heterogeneity: todos os strata precisam ser do mesmo side")
    side = strata[0].side
    k = len(strata)
    se = np.array([s.edge_bruto_atr_se for s in strata], dtype=np.float64)
    values = np.array([s.edge_bruto_atr for s in strata], dtype=np.float64)
    if np.any(se <= 0) or np.any(np.isnan(se)) or np.any(np.isnan(values)):
        return HeterogeneityTest(
            side=side, k=k, pooled_edge_bruto_atr=float("nan"), q_statistic=float("nan"),
            df=k - 1, p_value=float("nan"), i_squared_pct=float("nan"), per_symbol=strata,
        )
    weights = 1.0 / (se**2)  # noqa: unguarded-ratio -- se>0 garantido pelo guard acima (np.any(se<=0) já retornou)
    pooled = float(np.sum(weights * values) / np.sum(weights))  # noqa: unguarded-ratio -- soma de pesos todos positivos, nunca zero
    q = float(np.sum(weights * (values - pooled) ** 2))
    df = k - 1
    p_value = float(chi2.sf(q, df)) if df > 0 else float("nan")
    i_squared = max(0.0, (q - df) / q) * 100.0 if q > 0 else 0.0  # noqa: unguarded-ratio -- guardado pelo `if q > 0 else 0.0` na mesma linha
    return HeterogeneityTest(
        side=side, k=k, pooled_edge_bruto_atr=pooled, q_statistic=q, df=df,
        p_value=p_value, i_squared_pct=i_squared, per_symbol=strata,
    )


# ============================================================================
# Ponto de entrada com IO — um símbolo, ou os 5
# ============================================================================


def compute_metrics_for_symbol(
    symbol: str, *, tf: str = DECISION_TF
) -> tuple[tuple[StratumMetrics, ...], tuple[StratumMetrics, ...]]:
    """Carrega `labels`+`regime` reais via `dataset.build_modeling_frame`
    (já corrigido pra rotear `symbol` corretamente até `load_labels_v1`,
    achado AG-015 — sem essa correção este módulo teria repetido o MESMO
    bug: features/regime de um símbolo, `barrier_hit`/`atr_at_t0` de
    outro). Retorna `(pooled_by_side, detail_by_side_and_regime)`."""
    cfg = LabelConfig.from_constants(tf=tf)
    maker_fee = float(load_risk_constant("maker_fee"))
    taker_fee = float(load_risk_constant("taker_fee"))

    mf = build_modeling_frame(symbol=symbol, tf=tf)
    data = mf.data

    pooled: list[StratumMetrics] = []
    detail: list[StratumMetrics] = []
    for side in SIDES:
        side_df = data.filter(pl.col("side") == side)
        pooled.append(
            stratum_metrics(
                side_df, symbol=symbol, side=side, regime=None,
                tp_atr_mult=cfg.tp_atr_mult, sl_atr_mult=cfg.sl_atr_mult,
                maker_fee=maker_fee, taker_fee=taker_fee,
            )
        )
        for regime in sorted(side_df[REGIME_COL].drop_nulls().unique().to_list()):
            regime_df = side_df.filter(pl.col(REGIME_COL) == regime)
            detail.append(
                stratum_metrics(
                    regime_df, symbol=symbol, side=side, regime=str(regime),
                    tp_atr_mult=cfg.tp_atr_mult, sl_atr_mult=cfg.sl_atr_mult,
                    maker_fee=maker_fee, taker_fee=taker_fee,
                )
            )

    logger.info(
        "analysis.m6_common_factor.symbol_done",
        symbol=symbol,
        n_total=data.height,
        edge_bruto_atr_long=round(pooled[0].edge_bruto_atr, 6),
        edge_bruto_atr_short=round(pooled[1].edge_bruto_atr, 6),
    )
    return tuple(pooled), tuple(detail)


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 — mesmo padrão de `volatility_comparison._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("analysis.m6_common_factor.report_written", path=str(dest_path))


def run_and_save_m6_report(
    *,
    symbols: tuple[str, ...] = ALL_SYMBOLS,
    tf: str = DECISION_TF,
    dest_path: Path | None = None,
    max_workers: int | None = None,
) -> Path:
    """Ponto de entrada MANUAL — roda os 5 ativos em paralelo (cada
    símbolo é independente), roda o teste de heterogeneidade por lado
    sobre os cortes pooled, persiste o relatório completo (B29). Zero
    trials, zero escrita em `constants.yaml`, zero modelo treinado — não
    consome `N_lifetime`.

    Chame manualmente:
    `uv run python -m src.analysis.m6_common_factor_hypothesis`
    ou `uv run python -c "from src.analysis.m6_common_factor_hypothesis
    import run_and_save_m6_report as r; r()"`."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    logger.info(
        "analysis.m6_common_factor.starting", n_symbols=len(symbols), tf=tf, max_workers=workers
    )

    pooled_by_symbol: dict[str, tuple[StratumMetrics, ...]] = {}
    detail_by_symbol: dict[str, tuple[StratumMetrics, ...]] = {}
    with ProcessPoolExecutor(max_workers=min(workers, len(symbols))) as executor:
        future_to_symbol = {
            executor.submit(compute_metrics_for_symbol, symbol, tf=tf): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            pooled, detail = future.result()
            pooled_by_symbol[symbol] = pooled
            detail_by_symbol[symbol] = detail

    heterogeneity_by_side: dict[int, HeterogeneityTest] = {}
    for side in SIDES:
        strata = tuple(
            next(s for s in pooled_by_symbol[symbol] if s.side == side) for symbol in symbols
        )
        heterogeneity_by_side[side] = cochrans_q_heterogeneity(strata)

    payload: dict[str, Any] = {
        **report_provenance(),
        "decision_tf": tf,
        "symbols": list(symbols),
        "hypothesis": (
            "H0 (Q1, PRD_V4_1.md Sec3.2): edge_bruto_atr e o MESMO entre os "
            "5 ativos -- diferencas em ret_net vem inteiramente de custo_atr. "
            "Falsificacao: I2 alto / p_value baixo no teste de Cochran's Q "
            "indica componente idiossincratico real por ativo."
        ),
        "heterogeneity_by_side": {
            str(side): {
                "k": het.k,
                "pooled_edge_bruto_atr": het.pooled_edge_bruto_atr,
                "q_statistic": het.q_statistic,
                "df": het.df,
                "p_value": het.p_value,
                "i_squared_pct": het.i_squared_pct,
                "per_symbol": [asdict(s) for s in het.per_symbol],
            }
            for side, het in heterogeneity_by_side.items()
        },
        "detail_by_symbol_side_regime": {
            symbol: [asdict(s) for s in detail_by_symbol[symbol]] for symbol in symbols
        },
    }
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info(
        "analysis.m6_common_factor.done",
        i_squared_long=round(heterogeneity_by_side[1].i_squared_pct, 2),
        i_squared_short=round(heterogeneity_by_side[-1].i_squared_pct, 2),
        p_value_long=heterogeneity_by_side[1].p_value,
        p_value_short=heterogeneity_by_side[-1].p_value,
        dest=str(dest),
    )
    return dest


if __name__ == "__main__":
    run_and_save_m6_report()
