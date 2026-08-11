"""Faixa 1 — diagnóstico de calibração de confiança (regime DESCOBERTA, não
otimização). Mede se a probabilidade calibrada do Alpha (`confidence`)
ordena o retorno realizado — pergunta que T1 (`docs/SPRINT_LOG.md`, "Tarefas
quant pós-auditoria") já tocou usando `src.analysis.attribution.
confidence_deciles_by_side`, mas só no agregado pooled, sem NOFILL, sem
estratificação por regime, sem teste de sensibilidade ao calibrador.

**PÓS-HOC, EXPLORATÓRIO, NUNCA INSUMO DE TREINO.** Mesma classe de módulo
que `src.analysis.attribution`/`src.analysis.cost_surface` (ver docstrings
de lá): lê resultado REALIZADO e diagnóstico já persistido, nunca retreina,
nunca decide `tau`/threshold/calibrador de produção. D1-D4 abaixo só MEDEM.

**Diferença deliberada de `confidence_deciles_by_side`: os decis aqui são
calculados sobre a população COMPLETA de sinais (`side_hat == side`,
`is_oof=True`), incluindo `barrier_hit == "NOFILL"`, não só os preenchidos.**
Reusar o bucketing de `confidence_deciles_by_side` (só trades preenchidos)
para "taxa de NOFILL por decil" devolveria 0% em todo decil por construção —
a população que define o decil já teria excluído quem não preencheu. D3 do
prompt desta task pede explicitamente a junção "SEM filtrar NOFILL"; D1-D2-D4
usam a MESMA população para que os quatro diagnósticos sejam comparáveis
entre si (mesmo decil = mesmo conjunto de `t0`s em qualquer um dos quatro).
Consequência esperada e não escondida: os números de D1 não reproduzem
bit-a-bit os do relatório T1 anterior (que usava só trades preenchidos no
bucketing) — a verificação de que as PREMISSAS de T1 (citadas no prompt
desta task) continuam batendo com o disco usa `confidence_deciles_by_side`
diretamente (ver `verify_step0_premises`), não este módulo.

**Constantes locais, não em `constants.yaml`.** `FAIXA1_N_DECILES` (10) e
`FAIXA1_MIN_CELL_N` (200) são parâmetros DESTE diagnóstico exploratório —
mesma categoria de `GRID_FACTORS` em `src.analysis.cost_surface` ("decisão
de varredura exploratória, não uma constante de domínio"; `n_deciles`/
limiar de amostra não mudam nenhum comportamento de produção, só a
granularidade deste relatório). `200` vem literalmente do prompt desta
task (Manager), sem derivação estatística — tratado como parâmetro de
relato, não guardrail de risco (§16.10 classe D).

**D4 foi revisado em andamento** (correção recebida do Manager depois da
primeira versão deste módulo, ver `docs/SPRINT_LOG.md`): a versão original
ajustava 3 variantes de calibrador (Platt, isotônico com bin mínimo) sobre
`raw_score` já persistido, com `n_lifetime += 2`. A versão atual
(`d4_raw_vs_calibrated`/`isotonic_plateau_diagnostics`) **não ajusta
calibrador nenhum** — só compara o ranking por `raw_score` (pré-
calibração) contra o ranking por `confidence` (calibrado, produção) e
inspeciona a estrutura de plateau do isotônico já treinado a partir dos
pares `(raw_score, confidence)` já materializados. `n_lifetime` não
incrementa nesta rodada — não há variante de modelo nem de calibrador,
só leitura.

**Restrição forçada de `E02f_funding_z_expanding` lida direto de
`src.models.monotonic`, não duplicada.** Diferente de `src.analysis.
attribution` (que duplica `_MIN_OBS_SPEARMAN` deliberadamente para não
acoplar módulos), aqui a correção depende de bater com a restrição REAL
usada em produção — duplicar o sinal (`{1: -1, -1: 1}`) arriscaria o
diagnóstico divergir silenciosamente se a Camada 1 mudar a atribuição.
`src.analysis -> src.models` é permitido pelo contrato de import-linter
(só a direção contrária é proibida, ver `pyproject.toml`)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy.stats import chi2_contingency, kendalltau, norm, spearmanr

from src.core.provenance import report_provenance
from src.models.monotonic import _ECONOMIC_FORCED_CONSTRAINT_BY_SIDE

from . import attribution as attr

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_TP = "TP"
_SL = "SL"
_TIME = "TIME"
_NOFILL = "NOFILL"
_BARRIER_CATEGORIES: tuple[str, ...] = (_TP, _SL, _TIME, _NOFILL)

_SIDE_LABEL_BY_HAT: dict[int, str] = {1: "long", -1: "short"}
_RAW_SCORE_COL_BY_SIDE: dict[int, str] = {1: "score_long_raw", -1: "score_short_raw"}

# Ver docstring do módulo — parâmetros de relato deste diagnóstico, não
# constantes de domínio de `constants.yaml`.
FAIXA1_N_DECILES = 10
FAIXA1_MIN_CELL_N = (
    200  # int — lint de número mágico só flagueia float, mantido explícito por clareza
)

STRUCTURAL_REGIMES: tuple[str, ...] = ("R1", "R2", "R3", "R4")

E02F_FEATURE = "E02f_funding_z_expanding"
COST_FEATURE = "E27f_cost_atr_ratio"

_TERCILE_LOW = 1 / 3
_TERCILE_HIGH = 2 / 3
_COST_TERCILE_LABELS: tuple[str, ...] = ("LOW_COST", "MID_COST", "HIGH_COST")

# alpha two-tailed -> quantil normal — constante matemática (definição de
# IC95%), não de domínio, mesma categoria de `_BPS_PER_UNIT` em
# `src.analysis.attribution`.
_CI95_ALPHA_TWO_TAILED = 0.975  # noqa: magic-number


# ============================================================================
# STEP 0 — reprodução das premissas citadas no prompt (gate)
# ============================================================================


def verify_step0_premises(predictions: pl.DataFrame, labels: pl.DataFrame) -> dict[str, Any]:
    """Reproduz, usando `src.analysis.attribution.confidence_deciles_by_side`
    (o método que originalmente produziu os números de T1), as premissas
    marcadas `[HIPÓTESE]` no prompt desta task que dependem só de
    `predictions`/`labels`: tamanho dos decis, decil 10 por lado, Spearman
    por lado. Não decide se a premissa "passa" (isso seria um veredito) —
    devolve os números medidos para o chamador comparar contra o texto do
    prompt."""
    out = attr.confidence_deciles_by_side(predictions, labels, n_deciles=FAIXA1_N_DECILES)
    result: dict[str, Any] = {}
    for side_label in ("long", "short"):
        sub = out.filter(pl.col("side") == side_label).sort("decile")
        n_by_decile = sub["n"].to_list()
        decile10 = sub.filter(pl.col("decile") == FAIXA1_N_DECILES).row(0, named=True)
        deciles = sub["decile"].to_list()
        bps = sub["mean_ret_net_bps_value"].to_list()
        rho, p = spearmanr(deciles, bps)
        result[side_label] = {
            "n_by_decile": n_by_decile,
            "decile_sizes_equal_within_1": (max(n_by_decile) - min(n_by_decile)) <= 1,
            "decile_10_mean_bps": decile10["mean_ret_net_bps_value"],
            "decile_10_t_stat": decile10["t_stat"],
            "decile_10_n": decile10["n"],
            "spearman_rho": float(rho),
            "spearman_p": float(p),
        }
    return result


# ============================================================================
# População consolidada — join predictions + labels + regime, SEM filtrar NOFILL
# ============================================================================


def build_side_population(
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
    regimes: pl.DataFrame,
    *,
    side: int,
) -> pl.DataFrame:
    """UM lado (`side` +1/-1), toda linha `is_oof=True` com `side_hat ==
    side` — **NÃO filtra `barrier_hit == "NOFILL"`** (§3.2; D3 do prompt
    exige a junção sem esse filtro para medir taxa de NOFILL por decil; D1/
    D2/D4 reusam a MESMA população, ver docstring do módulo).

    `regimes` precisa conter `t0`, `regime`, `E27f_cost_atr_ratio` e
    `E02f_funding_z_expanding` — tipicamente `src.models.dataset.
    build_modeling_frame().data.select([...])`, deduplicado por `t0`
    internamente aqui (mesma convenção de `src.analysis.attribution.
    ic_by_regime` — regime/features não variam por lado)."""
    if side not in (1, -1):
        raise ValueError(f"build_side_population: side deve ser 1 ou -1, recebido {side}")

    raw_col = _RAW_SCORE_COL_BY_SIDE[side]
    preds_side = (
        predictions.filter(pl.col("is_oof") & (pl.col("side_hat") == side))
        .select(["t0", "fold_id", "side_hat", "confidence", raw_col])
        .rename({raw_col: "raw_score"})
        .with_columns(pl.col("t0").cast(_T0_DTYPE))
    )
    labels_small = labels.select(["t0", "side", "barrier_hit", "ret_net"]).with_columns(
        pl.col("t0").cast(_T0_DTYPE)
    )
    joined = preds_side.join(
        labels_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
    ).with_columns(pl.col("barrier_hit").cast(pl.Utf8))

    regimes_small = (
        regimes.select(["t0", "regime", COST_FEATURE, E02F_FEATURE])
        .with_columns(pl.col("t0").cast(_T0_DTYPE))
        .unique(subset=["t0"], keep="first")
    )
    joined = joined.join(regimes_small, on="t0", how="left")

    logger.info(
        "analysis.calibration_diagnostics.build_side_population",
        side=side,
        n_signals=preds_side.height,
        n_joined=joined.height,
        n_nofill=joined.filter(pl.col("barrier_hit") == _NOFILL).height,
    )
    return joined


def _assign_deciles(
    df: pl.DataFrame, *, confidence_col: str = "confidence", n_deciles: int = FAIXA1_N_DECILES
) -> pl.DataFrame:
    """Bucketing por RANK, mesma fórmula/desempate de `src.analysis.
    attribution._deciles_for_side` (`(pos * n_deciles) // n_total + 1`,
    desempate por `t0`) — generalizada aqui para operar sobre QUALQUER
    subpopulação (pooled, por regime, por tercil de custo), não só
    trades preenchidos."""
    if df.is_empty():
        return df.with_columns(pl.lit(None, dtype=pl.Int64).alias("decile"))
    ordered = df.sort([confidence_col, "t0"])
    n_total = ordered.height
    idx = np.arange(n_total, dtype=np.int64)
    decile_idx = (idx * n_deciles) // n_total + 1
    return ordered.with_columns(pl.Series("decile", decile_idx, dtype=pl.Int64))


# ============================================================================
# D1 — perfil completo de decil por lado
# ============================================================================


def _ci95(mean: float, std: float, n: int) -> tuple[float, float]:
    if n < 2 or std == 0.0 or not math.isfinite(std):
        return float("nan"), float("nan")
    z = float(norm.ppf(_CI95_ALPHA_TWO_TAILED))
    half = z * std / math.sqrt(n)
    return mean - half, mean + half


def _decile_cell(
    sub: pl.DataFrame, *, decile: int, confidence_col: str = "confidence"
) -> dict[str, Any]:
    n_total = sub.height
    counts = {cat: sub.filter(pl.col("barrier_hit") == cat).height for cat in _BARRIER_CATEGORIES}
    filled = sub.filter(pl.col("barrier_hit") != _NOFILL)
    n_filled = filled.height
    insufficient = n_filled < FAIXA1_MIN_CELL_N

    if n_filled > 0:
        conf_min = float(sub[confidence_col].min())  # type: ignore[arg-type]
        conf_max = float(sub[confidence_col].max())  # type: ignore[arg-type]
    else:
        conf_min = float("nan")
        conf_max = float("nan")

    # "célula com n < FAIXA1_MIN_CELL_N sai marcada insuficiente, NÃO
    # ESTIMADA" (D2 do prompt) — aplicado uniformemente em toda chamada de
    # `_decile_cell` (D1 pooled, D2 por regime/tercil, congruent/
    # incongruent), não só D2: mesma regra, mesmo lugar no código, para não
    # ter dois caminhos que podem divergir. `n`/`n_filled`/as taxas
    # TP/SL/TIME/NOFILL continuam reportadas — são frequência OBSERVADA,
    # não um ponto estimado com incerteza amostral (a distinção que "não
    # estimada" protege é especificamente a média/CI/t-stat).
    if n_filled > 0 and not insufficient:
        bps = filled["ret_net"].to_numpy().astype(np.float64) * 10_000  # noqa: magic-number — bps/fração
        mean_bps = float(np.mean(bps))
        std_bps = float(np.std(bps, ddof=1)) if n_filled > 1 else 0.0
        t_stat = (
            mean_bps / (std_bps / math.sqrt(n_filled))
            if n_filled > 1 and std_bps > 0.0
            else float("nan")
        )
        ci_low, ci_high = _ci95(mean_bps, std_bps, n_filled)
    else:
        mean_bps = float("nan")
        std_bps = float("nan")
        t_stat = float("nan")
        ci_low, ci_high = float("nan"), float("nan")

    return {
        "decile": decile,
        "n": n_total,
        "n_filled": n_filled,
        "confidence_min": conf_min,
        "confidence_max": conf_max,
        "mean_ret_net_bps": mean_bps,
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "std_ret_net_bps": std_bps,
        "t_stat": t_stat,
        "rate_tp": counts[_TP] / n_total if n_total else float("nan"),
        "rate_sl": counts[_SL] / n_total if n_total else float("nan"),
        "rate_time": counts[_TIME] / n_total if n_total else float("nan"),
        "rate_nofill": counts[_NOFILL] / n_total if n_total else float("nan"),
        "n_tp": counts[_TP],
        "n_sl": counts[_SL],
        "n_time": counts[_TIME],
        "n_nofill": counts[_NOFILL],
        "insufficient_n": insufficient,
    }


def decile_profile(
    df_side: pl.DataFrame, *, confidence_col: str = "confidence", n_deciles: int = FAIXA1_N_DECILES
) -> list[dict[str, Any]]:
    """Perfil de decil sobre `df_side` (já filtrado a UM lado, UMA
    subpopulação — pooled, um regime, um tercil de custo). Decis
    calculados por rank sobre `df_side` INTEIRO (filled+NOFILL, ver
    `_assign_deciles`); `mean_ret_net_bps`/CI/t-stat só sobre a fração
    preenchida de cada decil (NOFILL não tem retorno realizado, §3.2).
    Devolve `n_deciles` dicts, sempre — decil sem nenhuma linha (amostra
    menor que `n_deciles`) sai com `n=0`, `insufficient_n=True`, não é
    omitido."""
    if df_side.is_empty():
        return [_decile_cell(df_side.head(0), decile=d) for d in range(1, n_deciles + 1)]
    with_decile = _assign_deciles(df_side, confidence_col=confidence_col, n_deciles=n_deciles)
    rows: list[dict[str, Any]] = []
    for d in range(1, n_deciles + 1):
        sub = with_decile.filter(pl.col("decile") == d)
        rows.append(_decile_cell(sub, decile=d))
    return rows


def _rank_correlations(profile: list[dict[str, Any]]) -> dict[str, Any]:
    """Spearman/Kendall entre índice de decil e `mean_ret_net_bps`, só
    sobre decis com `n_filled > 0` (decil vazio não tem `mean_ret_net_bps`
    finito — entraria como `nan` e quebraria a correlação). `monotonic_
    increasing_p`/`monotonic_decreasing_p` são as versões UNICAUDAIS
    derivadas do p bicaudal do Spearman (`p/2` do lado cujo sinal bate com
    a hipótese, `1 - p/2` do lado oposto) — não dois testes independentes,
    é a mesma estatística lida nas duas direções (H1: rho>0 vs H1: rho<0),
    exatamente o "ambas as direções" pedido no prompt (D1)."""
    usable = [r for r in profile if r["n_filled"] > 0 and math.isfinite(r["mean_ret_net_bps"])]
    if len(usable) < 3:  # noqa: magic-number — mínimo matemático do spearmanr, não constante de domínio
        return {
            "spearman_rho": float("nan"),
            "spearman_p": float("nan"),
            "kendall_tau": float("nan"),
            "kendall_p": float("nan"),
            "monotonic_increasing_p": float("nan"),
            "monotonic_decreasing_p": float("nan"),
            "n_usable_deciles": len(usable),
        }
    deciles = [r["decile"] for r in usable]
    bps = [r["mean_ret_net_bps"] for r in usable]
    rho, p_two = spearmanr(deciles, bps)
    tau, p_tau = kendalltau(deciles, bps)
    rho = float(rho)
    p_two = float(p_two)
    p_incr = p_two / 2.0 if rho >= 0 else 1.0 - p_two / 2.0
    p_decr = p_two / 2.0 if rho <= 0 else 1.0 - p_two / 2.0
    return {
        "spearman_rho": rho,
        "spearman_p": p_two,
        "kendall_tau": float(tau),
        "kendall_p": float(p_tau),
        "monotonic_increasing_p": float(p_incr),
        "monotonic_decreasing_p": float(p_decr),
        "n_usable_deciles": len(usable),
    }


def _mean_excluding_decile(
    profile: list[dict[str, Any]], df_side_with_decile: pl.DataFrame
) -> dict[str, dict[str, Any]]:
    """Média ponderada (pooled, não média-das-médias) de `ret_net` em bps
    sobre trades PREENCHIDOS excluindo um decil por vez — 10 números por
    lado, sem comentário sobre qual é maior/menor (D1 do prompt: "sem
    comentar nenhuma delas"). Chave `"decile_{k}"` (`str`) em vez de `int`
    — `orjson.dumps` exige chave de dict `str` (§1.2 B29, escrita atômica
    do relatório final não pode falhar por tipo de chave)."""
    filled = df_side_with_decile.filter(pl.col("barrier_hit") != _NOFILL)
    out: dict[str, dict[str, Any]] = {}
    n_deciles = len(profile)
    for k in range(1, n_deciles + 1):
        rest = filled.filter(pl.col("decile") != k)
        n = rest.height
        key = f"decile_{k}"
        if n == 0:
            out[key] = {"n": 0, "mean_ret_net_bps": float("nan")}
            continue
        bps = rest["ret_net"].to_numpy().astype(np.float64) * 10_000  # noqa: magic-number
        out[key] = {"n": n, "mean_ret_net_bps": float(np.mean(bps))}
    return out


# ============================================================================
# D2 — estratificação por regime estrutural e tercil de custo
# ============================================================================


def _tercile_cuts(values: pl.Series) -> tuple[float, float]:
    valid = values.drop_nulls()
    q_low = float(valid.quantile(_TERCILE_LOW, interpolation="linear"))  # type: ignore[arg-type]
    q_high = float(valid.quantile(_TERCILE_HIGH, interpolation="linear"))  # type: ignore[arg-type]
    return q_low, q_high


def _assign_cost_tercile(
    df: pl.DataFrame, *, cost_col: str = COST_FEATURE
) -> tuple[pl.DataFrame, float, float]:
    q_low, q_high = _tercile_cuts(df[cost_col])
    bucket = (
        pl.when(pl.col(cost_col).is_null())
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(pl.col(cost_col) <= q_low)
        .then(pl.lit(_COST_TERCILE_LABELS[0]))
        .when(pl.col(cost_col) <= q_high)
        .then(pl.lit(_COST_TERCILE_LABELS[1]))
        .otherwise(pl.lit(_COST_TERCILE_LABELS[2]))
    )
    return df.with_columns(bucket.alias("cost_tercile")), q_low, q_high


def stratified_by_regime(df_side: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for regime in STRUCTURAL_REGIMES:
        sub = df_side.filter(pl.col("regime") == regime)
        profile = decile_profile(sub)
        out[regime] = {
            "n_total": sub.height,
            "decile_profile": profile,
            "correlations": _rank_correlations(profile),
        }
    return out


def stratified_by_cost_tercile(df_side: pl.DataFrame) -> dict[str, Any]:
    if df_side.filter(pl.col(COST_FEATURE).is_not_null()).height < 3:  # noqa: magic-number — mínimo p/ 3 cortes
        return {
            label: {
                "n_total": 0,
                "decile_profile": decile_profile(df_side.head(0)),
                "correlations": _rank_correlations([]),
            }
            for label in _COST_TERCILE_LABELS
        }
    with_tercile, q_low, q_high = _assign_cost_tercile(df_side)
    out: dict[str, Any] = {"tercile_cuts": {"q33": q_low, "q66": q_high}}
    for label in _COST_TERCILE_LABELS:
        sub = with_tercile.filter(pl.col("cost_tercile") == label)
        profile = decile_profile(sub)
        out[label] = {
            "n_total": sub.height,
            "decile_profile": profile,
            "correlations": _rank_correlations(profile),
        }
    return out


def congruent_incongruent_subsets(
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
    regimes: pl.DataFrame,
    populations_by_side: dict[int, pl.DataFrame],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mede o IC de `E02f_funding_z_expanding` x `ret_net` por regime
    (R1-R4), reproduzindo a metodologia da Fase E (`src.analysis.
    attribution.ic_by_regime`, pooled — o mesmo cálculo que produziu o
    achado citado no prompt). Classifica cada regime como CONGRUENTE ou
    INCONGRUENTE com a restrição monotônica forçada de `E02f` **daquele
    lado** (`src.models.monotonic._ECONOMIC_FORCED_CONSTRAINT_BY_SIDE`,
    lida direto da produção, não duplicada — ver docstring do módulo):
    congruente = sinal do IC medido bate com o sinal da restrição forçada.

    Devolve `(congruent, incongruent)` — cada um com, por lado, os
    regimes incluídos e o perfil de decil pooled sobre a UNIÃO desses
    regimes (população de `populations_by_side`, filled+NOFILL)."""
    regimes_small = regimes.select(["t0", "regime", E02F_FEATURE])
    ic_df = attr.ic_by_regime(predictions, labels, regimes_small, (E02F_FEATURE,)).filter(
        pl.col("regime").is_in(list(STRUCTURAL_REGIMES))
    )
    ic_by_regime_measured = {
        row["regime"]: {
            "ic_value": row["ic_value"],
            "ic_n": row["ic_n"],
            "ic_valid": row["ic_valid"],
        }
        for row in ic_df.to_dicts()
    }

    congruent: dict[str, Any] = {"e02f_ic_by_regime": ic_by_regime_measured}
    incongruent: dict[str, Any] = {"e02f_ic_by_regime": ic_by_regime_measured}

    for side, side_label in _SIDE_LABEL_BY_HAT.items():
        forced_sign = _ECONOMIC_FORCED_CONSTRAINT_BY_SIDE[E02F_FEATURE][side]
        congruent_regimes: list[str] = []
        incongruent_regimes: list[str] = []
        for regime in STRUCTURAL_REGIMES:
            entry = ic_by_regime_measured.get(regime)
            if entry is None or not entry["ic_valid"] or entry["ic_value"] is None:
                continue
            measured_sign = 1 if entry["ic_value"] > 0 else (-1 if entry["ic_value"] < 0 else 0)
            if measured_sign == 0:
                continue
            (congruent_regimes if measured_sign == forced_sign else incongruent_regimes).append(
                regime
            )

        pop = populations_by_side[side]
        congruent_sub = (
            pop.filter(pl.col("regime").is_in(congruent_regimes))
            if congruent_regimes
            else pop.head(0)
        )
        incongruent_sub = (
            pop.filter(pl.col("regime").is_in(incongruent_regimes))
            if incongruent_regimes
            else pop.head(0)
        )

        congruent_profile = decile_profile(congruent_sub)
        incongruent_profile = decile_profile(incongruent_sub)
        congruent[side_label] = {
            "forced_constraint_sign": forced_sign,
            "regimes_included": congruent_regimes,
            "n_total": congruent_sub.height,
            "decile_profile": congruent_profile,
            "correlations": _rank_correlations(congruent_profile),
        }
        incongruent[side_label] = {
            "forced_constraint_sign": forced_sign,
            "regimes_included": incongruent_regimes,
            "n_total": incongruent_sub.height,
            "decile_profile": incongruent_profile,
            "correlations": _rank_correlations(incongruent_profile),
        }
    return congruent, incongruent


# ============================================================================
# D3 — NOFILL por decil, qui-quadrado
# ============================================================================


def nofill_by_decile(df_side: pl.DataFrame) -> dict[str, Any]:
    with_decile = _assign_deciles(df_side)
    rows: list[dict[str, Any]] = []
    table: list[list[int]] = []
    for d in range(1, FAIXA1_N_DECILES + 1):
        sub = with_decile.filter(pl.col("decile") == d)
        n = sub.height
        n_nofill = sub.filter(pl.col("barrier_hit") == _NOFILL).height
        rate = n_nofill / n if n > 0 else float("nan")
        low, high = _wilson_ci95(n_nofill, n) if n > 0 else (float("nan"), float("nan"))
        rows.append(
            {
                "decile": d,
                "n": n,
                "n_nofill": n_nofill,
                "nofill_rate": rate,
                "ci95_low": low,
                "ci95_high": high,
                "insufficient_n": n < FAIXA1_MIN_CELL_N,
            }
        )
        table.append([n_nofill, n - n_nofill])

    table_arr = np.asarray(table, dtype=np.int64)
    if (
        table_arr.shape[0] >= 2
        and np.all(table_arr.sum(axis=1) > 0)
        and np.all(table_arr.sum(axis=0) > 0)
    ):
        chi2, p, dof, _expected = chi2_contingency(table_arr)
        chi2_result: dict[str, Any] = {"chi2": float(chi2), "p": float(p), "dof": int(dof)}
    else:
        chi2_result = {"chi2": float("nan"), "p": float("nan"), "dof": None}

    return {"by_decile": rows, "chi2_test": chi2_result}


def _wilson_ci95(successes: int, n: int) -> tuple[float, float]:
    """Wilson score interval — mais estável que a normal para proporções
    perto de 0/1 (taxa de NOFILL pode ser baixa), sem exigir n grande.
    Fórmula padrão (Wilson 1927), não constante de domínio."""
    if n == 0:
        return float("nan"), float("nan")
    z = float(norm.ppf(_CI95_ALPHA_TWO_TAILED))
    p_hat = successes / n
    denom = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denom
    half = (z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2))) / denom
    return center - half, center + half


# ============================================================================
# D4 (REVISADO — correção do Manager recebida em andamento, ver
# docs/SPRINT_LOG.md/relatório da task) — score cru vs score calibrado,
# ZERO calibrador novo ajustado. `n_lifetime` não incrementa: não há
# variante de modelo nem de calibrador, só leitura de `raw_score`/
# `confidence` já persistidos em `predictions.parquet`.
# ============================================================================


def _decile_pairs(df_side: pl.DataFrame) -> pl.DataFrame:
    """Para cada linha de `df_side`, o decil sob ranking por `raw_score`
    (pré-calibração) e o decil sob ranking por `confidence` (calibrado,
    produção) — mesmo `_assign_deciles`, uma vez por coluna, casados por
    um índice de linha estável (`t0` sozinho não é chave: a mesma barra
    aparece em até 5 folds, ver docstring de `src.models.alpha.
    assemble_predictions_table`; `fold_id` desambigua)."""
    indexed = df_side.with_row_index("_row_id")
    by_raw = _assign_deciles(indexed, confidence_col="raw_score").select(
        ["_row_id", pl.col("decile").alias("decile_raw")]
    )
    by_calibrated = _assign_deciles(indexed, confidence_col="confidence").select(
        ["_row_id", pl.col("decile").alias("decile_calibrated")]
    )
    return by_raw.join(by_calibrated, on="_row_id", how="inner")


def _plateau_runs(raw_sorted: FloatArray, confidence_sorted: FloatArray) -> list[dict[str, Any]]:
    """Runs de `confidence` constante ao longo de `raw_score` ordenado
    ascendente — cada run é uma região plana do calibrador isotônico já
    ajustado em produção. `IsotonicRegression.predict` (`out_of_bounds=
    "clip"`) interpola linearmente entre os nós ajustados; dentro de um
    trecho onde dois nós consecutivos compartilham o mesmo `y`, QUALQUER
    `x` no intervalo (inclusive fora do treino, como o conjunto de teste
    OOF aqui) devolve exatamente esse `y` — por isso runs de igualdade
    exata em `confidence` identificam plateaus reais do calibrador, sem
    precisar do objeto `IsotonicRegression` original (nunca persistido em
    disco, só `raw_score`/`confidence` já materializados)."""
    n = raw_sorted.shape[0]
    if n == 0:
        return []
    runs: list[dict[str, Any]] = []
    start = 0
    for i in range(1, n + 1):
        if i == n or not math.isclose(
            confidence_sorted[i], confidence_sorted[start], rel_tol=1e-9, abs_tol=1e-12
        ):
            runs.append(
                {
                    "n_points": i - start,
                    "raw_score_min": float(raw_sorted[start]),
                    "raw_score_max": float(raw_sorted[i - 1]),
                    "width": float(raw_sorted[i - 1] - raw_sorted[start]),
                    "confidence_value": float(confidence_sorted[start]),
                }
            )
            start = i
    return runs


def isotonic_plateau_diagnostics(df_side: pl.DataFrame) -> dict[str, Any]:
    """Por fold (o calibrador isotônico é ajustado por fold x lado, §5.9):
    região plana mais LARGA (maior `raw_score_max - raw_score_min`) e
    região plana do TOPO (a que contém o maior `raw_score` do fold —
    território de decil 10). Agregado por lado: a mais larga entre os 15
    folds, e a soma de pontos na região do topo entre os 15 folds."""
    per_fold: list[dict[str, Any]] = []
    for fold_id in sorted(df_side["fold_id"].unique().to_list()):
        fold_df = df_side.filter(pl.col("fold_id") == fold_id).sort("raw_score")
        raw = fold_df["raw_score"].to_numpy().astype(np.float64)
        conf = fold_df["confidence"].to_numpy().astype(np.float64)
        runs = _plateau_runs(raw, conf)
        if not runs:
            continue
        widest = max(runs, key=lambda r: r["width"])
        top = runs[-1]
        per_fold.append(
            {
                "fold_id": int(fold_id),
                "n_points_fold": int(raw.shape[0]),
                "widest_plateau_width": widest["width"],
                "widest_plateau_n_points": widest["n_points"],
                "top_plateau_width": top["width"],
                "top_plateau_n_points": top["n_points"],
            }
        )
    if not per_fold:
        empty_result: dict[str, Any] = {
            "per_fold": [],
            "widest_plateau_width_max": float("nan"),
            "widest_plateau_fold_id": None,
            "top_plateau_n_points_total": 0,
        }
        return empty_result
    widest_overall = max(per_fold, key=lambda r: r["widest_plateau_width"])
    return {
        "per_fold": per_fold,
        "widest_plateau_width_max": widest_overall["widest_plateau_width"],
        "widest_plateau_fold_id": widest_overall["fold_id"],
        "top_plateau_n_points_total": sum(r["top_plateau_n_points"] for r in per_fold),
    }


def d4_raw_vs_calibrated(df_side: pl.DataFrame) -> dict[str, Any]:
    """D4 revisado: (1) D1 refeito sobre `raw_score` em vez de `confidence`
    — se o antipadrão de decil 10 (long) sobrevive ao score cru, a causa é
    o modelo, não o calibrador; (2) fração de linhas cujo decil muda entre
    as duas versões; (3)/(4) `isotonic_plateau_diagnostics`. Nenhum
    calibrador é ajustado aqui — só leitura de colunas já persistidas."""
    profile_raw = decile_profile(df_side, confidence_col="raw_score")
    profile_calibrated = decile_profile(df_side, confidence_col="confidence")

    pairs = _decile_pairs(df_side)
    n_compared = pairs.height
    n_swap = pairs.filter(pl.col("decile_raw") != pl.col("decile_calibrated")).height
    fraction_swap = n_swap / n_compared if n_compared else float("nan")

    return {
        "decile_profile_raw_score": profile_raw,
        "correlations_raw_score": _rank_correlations(profile_raw),
        "decile_profile_calibrated": profile_calibrated,
        "correlations_calibrated": _rank_correlations(profile_calibrated),
        "n_compared": n_compared,
        "n_decile_swap": n_swap,
        "fraction_pairs_decile_swap": fraction_swap,
        "isotonic_plateau": isotonic_plateau_diagnostics(df_side),
    }


# ============================================================================
# ECE — Expected Calibration Error (auditoria Laplace_Quant_V16, 2026-08-09)
# ============================================================================

# Nº de bins do ECE — parâmetro de relato deste diagnóstico (mesma categoria
# de FAIXA1_N_DECILES, ver docstring do módulo), não constante de domínio.
FAIXA1_ECE_N_BINS = 10


def expected_calibration_error(
    confidence: FloatArray, outcome: NDArray[np.int64], *, n_bins: int = FAIXA1_ECE_N_BINS
) -> dict[str, Any]:
    """ECE padrão (Guo et al. 2017, "On Calibration of Modern Neural
    Networks") — bins de LARGURA uniforme sobre `[0, 1]` (não por quantil/
    contagem igual: um bin quase vazio precisa aparecer vazio no relatório,
    não ser escondido atrás de uma borda ajustada pra caber gente),
    ponderado por população de cada bin:
    `ECE = Σ_b (n_b/N) × |mean(confidence_b) − mean(outcome_b)|`.

    Diferença deliberada da leitura de ECE em
    `train_alpha_c1_v14.py::main` do projeto irmão Laplace_Quant_V16 (que
    inspirou esta função): lá o cálculo é `mean(|prob_true_b − prob_pred_b|)`
    SEM ponderar por `n_b` (`sklearn.calibration.calibration_curve` com
    `strategy="uniform"` seguido de média simples) — um bin com 3
    observações pesa igual a um com 3000. A definição de Guo et al. é a
    convenção padrão da literatura de calibração e é o que a maioria das
    ferramentas chama de "ECE" sem qualificar; por isso a reimplementação
    aqui pondera por `n_b`, não copia a leitura da fonte sem verificar.

    `outcome` precisa ser `{0, 1}` (ex. `barrier_hit == "TP"`) — não
    filtra `NOFILL` sozinha, quem chama passa só a população preenchida
    (mesma disciplina de `decile_profile`)."""
    n = confidence.shape[0]
    if n == 0:
        return {"ece": float("nan"), "n": 0, "bins": []}

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.clip(np.digitize(confidence, edges[1:-1], right=False), 0, n_bins - 1)

    bins: list[dict[str, Any]] = []
    ece = 0.0
    for b in range(n_bins):
        mask = bin_idx == b
        n_b = int(mask.sum())
        if n_b == 0:
            bins.append(
                {
                    "bin": b,
                    "bin_edge_low": float(edges[b]),
                    "bin_edge_high": float(edges[b + 1]),
                    "n": 0,
                    "mean_confidence": float("nan"),
                    "mean_outcome": float("nan"),
                    "gap": float("nan"),
                }
            )
            continue
        mean_conf = float(confidence[mask].mean())
        mean_out = float(outcome[mask].astype(np.float64).mean())
        gap = abs(mean_conf - mean_out)
        ece += (n_b / n) * gap
        bins.append(
            {
                "bin": b,
                "bin_edge_low": float(edges[b]),
                "bin_edge_high": float(edges[b + 1]),
                "n": n_b,
                "mean_confidence": mean_conf,
                "mean_outcome": mean_out,
                "gap": gap,
            }
        )
    return {"ece": float(ece), "n": n, "bins": bins}


def calibration_error_by_side(
    df_side: pl.DataFrame, *, n_bins: int = FAIXA1_ECE_N_BINS
) -> dict[str, Any]:
    """ECE sobre `confidence` (calibrado, produção) E sobre `raw_score`
    (pré-calibração) — mesmo par de colunas de `d4_raw_vs_calibrated`, pra
    responder a pergunta que a ordenação por decil não responde sozinha:
    a calibração piora a ORDENAÇÃO (já medido em D4) e melhora, piora ou
    não muda a MAGNITUDE (`P_cal` bate com a frequência real de TP)? São
    perguntas diferentes — uma calibração pode desordenar e ainda reduzir
    o erro de magnitude, ou vice-versa. Só sobre trades preenchidos
    (`barrier_hit != NOFILL`); `outcome = (barrier_hit == "TP")`, mesma
    definição de `y` usada no treino (`src.models.alpha.fit_side_model`)."""
    filled = df_side.filter(pl.col("barrier_hit") != _NOFILL)
    outcome = (filled["barrier_hit"] == _TP).to_numpy().astype(np.int64)
    confidence = filled["confidence"].to_numpy().astype(np.float64)
    raw_score = filled["raw_score"].to_numpy().astype(np.float64)
    return {
        "n_filled": filled.height,
        "calibrated": expected_calibration_error(confidence, outcome, n_bins=n_bins),
        "raw_score": expected_calibration_error(raw_score, outcome, n_bins=n_bins),
    }


# ============================================================================
# Orquestração — monta o JSON da rubrica pré-registrada
# ============================================================================


def run_faixa1_diagnostic(
    predictions: pl.DataFrame, labels: pl.DataFrame, regimes: pl.DataFrame
) -> dict[str, Any]:
    """Monta o payload completo D1-D4 + rubrica pré-registrada (prompt da
    task Faixa 1). Não decide nada — só mede. `regimes` = `src.models.
    dataset.build_modeling_frame().data` (ou qualquer frame com `t0`,
    `regime`, `E27f_cost_atr_ratio`, `E02f_funding_z_expanding`)."""
    step0 = verify_step0_premises(predictions, labels)

    populations = {
        side: build_side_population(predictions, labels, regimes, side=side) for side in (1, -1)
    }

    d1_profiles: dict[str, list[dict[str, Any]]] = {}
    d1_correlations: dict[str, Any] = {}
    d1_mean_excluding: dict[str, Any] = {}
    for side, side_label in _SIDE_LABEL_BY_HAT.items():
        pop = populations[side]
        profile = decile_profile(pop)
        d1_profiles[side_label] = profile
        d1_correlations[side_label] = _rank_correlations(profile)
        with_decile = _assign_deciles(pop)
        d1_mean_excluding[side_label] = _mean_excluding_decile(profile, with_decile)

    d2_by_regime = {
        side_label: stratified_by_regime(populations[side])
        for side, side_label in _SIDE_LABEL_BY_HAT.items()
    }
    d2_by_cost_tercile = {
        side_label: stratified_by_cost_tercile(populations[side])
        for side, side_label in _SIDE_LABEL_BY_HAT.items()
    }
    congruent, incongruent = congruent_incongruent_subsets(
        predictions, labels, regimes, populations
    )

    d3 = {
        side_label: nofill_by_decile(populations[side])
        for side, side_label in _SIDE_LABEL_BY_HAT.items()
    }

    d4 = {
        side_label: d4_raw_vs_calibrated(populations[side])
        for side, side_label in _SIDE_LABEL_BY_HAT.items()
    }

    ece = {
        side_label: calibration_error_by_side(populations[side])
        for side, side_label in _SIDE_LABEL_BY_HAT.items()
    }

    payload: dict[str, Any] = {
        "schema_version": 1,
        "task": "faixa1_calibration_diagnostic",
        "regime": "DESCOBERTA",
        "n_deciles": FAIXA1_N_DECILES,
        "min_cell_n": FAIXA1_MIN_CELL_N,
        "step0_premises_reproduced": step0,
        "spearman_by_side": {s: d1_correlations[s]["spearman_rho"] for s in ("long", "short")},
        "spearman_p_by_side": {s: d1_correlations[s]["spearman_p"] for s in ("long", "short")},
        "kendall_by_side": {s: d1_correlations[s]["kendall_tau"] for s in ("long", "short")},
        "kendall_p_by_side": {s: d1_correlations[s]["kendall_p"] for s in ("long", "short")},
        "monotonic_increasing_p": {
            s: d1_correlations[s]["monotonic_increasing_p"] for s in ("long", "short")
        },
        "monotonic_decreasing_p": {
            s: d1_correlations[s]["monotonic_decreasing_p"] for s in ("long", "short")
        },
        "decile_mean_bps": d1_profiles,
        "mean_excluding_decile_k": d1_mean_excluding,
        "nofill_rate_by_decile": d3,
        "by_regime": d2_by_regime,
        "by_cost_tercile": d2_by_cost_tercile,
        "constraint_congruent_subset": congruent,
        "constraint_incongruent_subset": incongruent,
        "calibrator_comparison": d4,
        "expected_calibration_error": ece,
    }
    return payload


def run_and_save_faixa1_report(*, dest_path: Any = None) -> Any:
    """Ponto de entrada MANUAL (mesmo padrão de `src.analysis.cost_surface.
    run_and_save_cost_surface_report`) — carrega `predictions/alpha/
    alpha_c1_v1/predictions.parquet`, `labels/v1/labels.parquet` e
    `src.models.dataset.build_modeling_frame()` do disco, roda
    `run_faixa1_diagnostic`, escreve `experiments/
    faixa1_calibration_diagnostic.json` (B29, atômico) com
    `generated_at`/`code_version` (`report_provenance()`).

    Chame manualmente: `uv run python -m src.analysis.calibration_diagnostics`."""
    import os
    from pathlib import Path

    import orjson

    from src.models import dataset as ds
    from src.models._paths import PREDICTIONS_OUTPUT_DIR
    from src.models.pipeline import MODEL_ID_CAMADA1
    from src.validation import cpcv

    predictions = pl.read_parquet(
        PREDICTIONS_OUTPUT_DIR / "alpha" / MODEL_ID_CAMADA1 / "predictions.parquet"
    )
    # T0.3 -- via cpcv.load_labels_v1() em vez de reconstruir o caminho
    # (que migrou de labels/v1/ pro layout chaveado data/labels/BTCUSDT/15m/v1/).
    labels = cpcv.load_labels_v1()
    mf = ds.build_modeling_frame()
    regimes = mf.data.select(["t0", "regime", COST_FEATURE, E02F_FEATURE])

    payload = run_faixa1_diagnostic(predictions, labels, regimes)
    payload = {**report_provenance(), **payload}

    repo_root = Path(__file__).resolve().parents[2]
    out_path = (
        dest_path
        if dest_path is not None
        else repo_root / "experiments" / "faixa1_calibration_diagnostic.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("analysis.calibration_diagnostics.report_written", path=str(out_path))
    return out_path


if __name__ == "__main__":
    run_and_save_faixa1_report()
