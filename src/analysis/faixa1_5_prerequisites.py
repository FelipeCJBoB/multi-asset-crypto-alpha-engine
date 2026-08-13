"""Faixa 1.5 — pré-requisitos do walk-forward (§ prompt "Faixa 1.5",
2026-08-09). REGIME É DECLARADO POR FUNÇÃO/BLOCO (ver docstring de cada
uma) — Blocos 1/2/3/5 são DESCOBERTA (medem, não concluem); Bloco 4 é
CONSTRUTIVO (adiciona um campo novo). Nenhuma função aqui decide, filtra
em produção, ou altera `src.models.monotonic`/o Decision Engine.

**PÓS-HOC, NUNCA INSUMO DE TREINO.** Mesma classe de módulo que
`src.analysis.attribution`/`.cost_surface`/`.calibration_diagnostics`: lê
predições/labels/splits/diagnósticos já persistidos, nunca retreina o
XGBoost (Blocos 1/2/3/5 — `n_lifetime += 0`, é aritmética e reconstrução
determinística do mapeamento fold→path via `cpcv.generate_splits`, não
uma variante de modelo). Bloco 4 adiciona uma COLUNA nova a uma cópia de
`predictions.parquet` sem ajustar calibrador nenhum (`n_lifetime += 1`,
ver docstring de `add_confidence_rank`).

**Reuso, não reimplementação.** `src.models.decomposition.decompose()`
(Sharpe/carry/PnL por trade), `src.models.backtest_lite.span_seconds`/
`sharpe_naive`/`DAYS_PER_YEAR` (anualização), `src.core.metric.Metric.
per_unit()` (fração somada -> bps/trade), `src.models.monotonic.
compute_ic_by_env`/`screen_monotone_constraints`, `src.models.
environments.assign_environments`, `src.analysis.calibration_diagnostics.
build_side_population`/`_assign_deciles`/`decile_profile`/
`_rank_correlations` (Bloco 4 reexecuta D1/D4 sobre `confidence_rank` com
a MESMA rubrica da Faixa 1, não uma nova).

**Revisão de `check_unguarded_ratios.py` (2026-08-09).** 11 divisões
flagueadas, nenhuma exigiu correção — todas seguras por construção:
constantes de módulo (`_BAR_SECONDS`, `backtest_lite.DAYS_PER_YEAR`/
`.SECONDS_PER_DAY`, `step=0.005` do sweep), guardas já presentes que o
scanner não reconhece (`n<2`/truthiness de `set` em vez de `<=0`
explícito), e `pl.count().over("fold_id")` — sempre `>=1` por construção
(a própria linha pertence ao grupo que está sendo contado)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from scipy.stats import spearmanr

from src.core.provenance import report_provenance
from src.models import backtest_lite
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models._paths import PREDICTIONS_OUTPUT_DIR
from src.models.decomposition import decompose
from src.models.environments import ENVIRONMENTS, assign_environments
from src.models.monotonic import (
    _ECONOMIC_FORCED_CONSTRAINT_BY_SIDE,
    _assign_from_ic,
    compute_ic_by_env,
)
from src.models.pipeline import MODEL_ID_CAMADA1, MODELS_DIR
from src.validation import cpcv

from . import calibration_diagnostics as caldiag

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "faixa1_5_prerequisites.json"

_SIDE_LABEL_BY_HAT: dict[int, str] = {1: "long", -1: "short"}
_STRUCTURAL_REGIMES: tuple[str, ...] = ("R1", "R2", "R3", "R4")
_E02F_FEATURE = "E02f_funding_z_expanding"
_COST_FEATURE = "E27f_cost_atr_ratio"
_NOFILL = "NOFILL"
_TP = "TP"
_SL = "SL"
_TIME = "TIME"

# Mínimo de trades por célula pra reportar estimativa — mesmo parâmetro de
# relato que `calibration_diagnostics.FAIXA1_MIN_CELL_N` (200, citado
# literalmente no prompt original da Faixa 1); reusado aqui pela mesma
# categoria de decisão (parâmetro de relato, não guardrail de risco,
# §16.10 classe D), não uma constante nova independente.
MIN_CELL_N = caldiag.FAIXA1_MIN_CELL_N

# Segundos por barra de 15m e dias/ano (calendário gregoriano médio,
# `src.models.backtest_lite.DAYS_PER_YEAR`, mesma convenção de
# anualização usada em todo o resto do repo) -> barras/ano é ARITMÉTICA
# sobre os dois, nunca um literal solto (era [HIPÓTESE] "35.064 (365x96)"
# no prompt — 365x96=35.040, não 35.064; 365,25x96=35.064 EXATO, batendo
# com `DAYS_PER_YEAR`; a fórmula citada no prompt tinha uma imprecisão de
# anotação, o valor-alvo 35.064 está correto e é reproduzido aqui, não
# copiado).
_BAR_SECONDS: Final[float] = 15 * 60
BARS_PER_YEAR: Final[float] = (
    backtest_lite.DAYS_PER_YEAR * backtest_lite.SECONDS_PER_DAY / _BAR_SECONDS
)


# ============================================================================
# Carregamento comum — predictions + modeling frame + mapeamento fold->path
# (determinístico via cpcv.generate_splits, SEM retreino).
# ============================================================================


def load_predictions(
    model_id: str = MODEL_ID_CAMADA1, *, dest_dir: Path | None = None
) -> pl.DataFrame:
    """`dest_dir` (AG-012, mesmo padrão de `src.models.pipeline.
    write_predictions_atomic`/`run_layer1_sprint`, AG-006): default `None`
    preserva o caminho legado plano `PREDICTIONS_OUTPUT_DIR/alpha/
    {model_id}/predictions.parquet`, bit-exato com todo chamador existente
    (nenhum passa este argumento hoje — `faixa1_5_prerequisites.py`,
    `faixa1_6_reconciliation.py`, `faixa1_7_edge_or_beta.py`,
    `faixa2_caminho_b.py`, `faixa2_vol_accelerator_test.py`). Passar
    `src.models._paths.predictions_symbol_tf_dir(symbol, model_id, tf=tf)`
    lê do layout chaveado novo — o par simétrico de leitura do que
    `write_predictions_atomic(dest_dir=...)` já grava."""
    src_dir = dest_dir if dest_dir is not None else (PREDICTIONS_OUTPUT_DIR / "alpha" / model_id)
    return pl.read_parquet(src_dir / "predictions.parquet")


def fold_to_path_map(splits: tuple[cpcv.CPCVSplit, ...]) -> dict[int, int]:
    """`{fold_id: path_id}` — direto de `CPCVSplit.split_id`/`.path_id`
    (`src.models.alpha.run_fold` usa exatamente esses dois campos como
    `fold_id`/`path_id` de `FoldResult`, ver `pipeline.py:417`). Puramente
    combinatório: `cpcv.generate_splits(mf.data)` é determinístico dado
    `mf.data`, não depende de nenhum modelo treinado."""
    return {s.split_id: s.path_id for s in splits}


_REALIZED_JOIN_COLS: Final[tuple[str, ...]] = (
    "t0",
    "side",
    "barrier_hit",
    "ret_net",
    "ret_gross",
    "cost_entry_bps",
    "cost_exit_bps",
    "funding_bps",
    "regime",
    _COST_FEATURE,
    _E02F_FEATURE,
)


def build_realized_trades(
    predictions: pl.DataFrame, mf_data: pl.DataFrame, fold_to_path: dict[int, int]
) -> pl.DataFrame:
    """Todo sinal emitido (`side_hat != 0`, `is_oof=True`), preenchido ou
    não, com `path_id` (via `fold_to_path`) e regime/custo/funding/PnL já
    presentes — `mf.data` (`src.models.dataset.build_modeling_frame`) já
    tem `labels/v1/labels.parquet` inteiro mais T1/regime unidos, então
    este único join (`t0, side_hat == side`) basta, sem precisar reler
    `labels.parquet` separadamente. NÃO filtra `NOFILL` — mesmo padrão de
    `src.models.backtest_lite.realize_trades`/`src.analysis.
    calibration_diagnostics.build_side_population`; quem quer só
    preenchidos filtra explicitamente (`decompose()` exige isso, ver
    `_filled` abaixo)."""
    preds = predictions.filter(pl.col("is_oof") & (pl.col("side_hat") != 0)).select(
        "t0", "fold_id", "side_hat", "confidence", "score_long_raw", "score_short_raw"
    )
    mf_small = mf_data.select(list(_REALIZED_JOIN_COLS)).with_columns(
        pl.col("barrier_hit").cast(pl.Utf8)
    )
    joined = preds.join(mf_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner")
    path_series = pl.Series(
        "path_id",
        [fold_to_path[f] for f in joined["fold_id"].to_list()],
        dtype=pl.Int64,
    )
    return joined.with_columns(path_series)


def _filled(realized: pl.DataFrame) -> pl.DataFrame:
    return realized.filter(pl.col("barrier_hit") != _NOFILL)


def _barrier_rates(df: pl.DataFrame) -> dict[str, float]:
    n = df.height
    if n == 0:
        return {
            "rate_tp": float("nan"),
            "rate_sl": float("nan"),
            "rate_time": float("nan"),
            "rate_nofill": float("nan"),
        }
    counts = {b: df.filter(pl.col("barrier_hit") == b).height for b in (_TP, _SL, _TIME, _NOFILL)}
    return {
        "rate_tp": counts[_TP] / n,
        "rate_sl": counts[_SL] / n,
        "rate_time": counts[_TIME] / n,
        "rate_nofill": counts[_NOFILL] / n,
    }


# ============================================================================
# Bloco 1 — varredura de fee_budget_monthly (DESCOBERTA — detecção, não
# escolha de valor).
# ============================================================================


def _trades_per_year_per_path(realized: pl.DataFrame) -> dict[int, dict[str, float]]:
    """Por `path_id`: `n_filled`, `span_seconds` (primeiro->último `t0`
    PREENCHIDO, mesma definição de `backtest_lite.span_seconds`) e
    `trades_per_year = n_filled / span_years` — a "convenção do repo"
    citada no prompt (`backtest_lite.sharpe_naive`/`.trades_per_year` já
    fazem exatamente esta conta por caminho; reproduzida aqui direto sobre
    `realized` em vez de reconstruir `FoldResult` — que exigiria
    retreino)."""
    out: dict[int, dict[str, float]] = {}
    for path_id in sorted(realized["path_id"].unique().to_list()):
        sub = _filled(realized.filter(pl.col("path_id") == path_id))
        n_filled = sub.height
        span = backtest_lite.span_seconds(sub["t0"]) if n_filled else 0.0
        span_years = span / (backtest_lite.DAYS_PER_YEAR * backtest_lite.SECONDS_PER_DAY)
        tpy = n_filled / span_years if span_years > 0 else float("nan")
        out[int(path_id)] = {
            "n_filled": n_filled,
            "span_seconds": span,
            "trades_per_year": tpy,
        }
    return out


def fee_budget_sweep(realized: pl.DataFrame) -> dict[str, Any]:
    """Bloco 1 — DESCOBERTA. `target_signal_rate` é DERIVADA de
    `fee_budget_monthly` (`constants.yaml`, ambas classe A ASSUMED/DERIVED,
    nunca varridas). Assunção de escala EXPLÍCITA e declarada aqui (não
    verificada no repo — não existe fórmula fechada documentada): a
    relação é LINEAR — `target_signal_rate_ajustada = target_signal_rate *
    (candidato / fee_budget_monthly_atual)`. `orçamento/ano implicado =
    target_signal_rate_ajustada * BARS_PER_YEAR` — mesma fórmula de
    `src.analysis.tau_diagnostics` ("alvo nominal"), reusada, não
    reinventada.

    **Correção (Faixa 1.6, Bloco 3, 2026-08-09) — SEM fator de lado.** Até
    2026-08-09 esta função multiplicava por `2.0` ("2 lados"), citando
    `tau_diagnostics` como precedente — fator que `tau_diagnostics`
    introduziu e que este módulo herdou por citação, sem checar contra a
    derivação original. `PRD_V3_2_UNIFICADO.md:95-101` (§0.2 R3) deriva o
    orçamento como contagem TOTAL de trades (`661/ano`, sem termo de
    lado), e `target_signal_rate` já é essa taxa dividida por
    `BARS_PER_YEAR` — dobrar de volta aqui dobrava o orçamento de fees
    implícito (ver `config/constants.yaml::fee_budget_is_per_side`, e
    `src/analysis/faixa1_6_reconciliation.py`, Bloco 3, para a auditoria
    completa). Os pontos deste sweep antes da correção tinham
    `implied_trades_per_year` 2x maior que o correto.

    Não escolhe valor, não conclui se cabe — só reporta, por ponto da
    grade, o orçamento implicado e quais `path_id`/células excedem."""
    fee_budget_current = float(load_constant("fee_budget_monthly"))
    target_signal_rate_current = float(load_constant("target_signal_rate"))

    sweep_range = (0.015, 0.045)
    step = 0.005
    n_points = round((sweep_range[1] - sweep_range[0]) / step) + 1
    grid = [round(sweep_range[0] + i * step, 10) for i in range(n_points)]

    per_path = _trades_per_year_per_path(realized)
    unconditional_trades_per_year = {pid: v["trades_per_year"] for pid, v in per_path.items()}

    cells: dict[str, dict[int, dict[str, float]]] = {}
    for side, side_label in _SIDE_LABEL_BY_HAT.items():
        for regime in _STRUCTURAL_REGIMES:
            key = f"{side_label}_{regime}"
            sub = realized.filter((pl.col("side_hat") == side) & (pl.col("regime") == regime))
            cells[key] = _trades_per_year_per_path(sub)

    points: dict[str, Any] = {}
    for candidate in grid:
        scale = candidate / fee_budget_current
        adjusted_rate = target_signal_rate_current * scale
        implied_trades_per_year = adjusted_rate * BARS_PER_YEAR

        by_path_exceeds = {
            str(pid): bool(tpy > implied_trades_per_year) if math.isfinite(tpy) else None
            for pid, tpy in unconditional_trades_per_year.items()
        }
        by_cell_exceeds: dict[str, dict[str, Any]] = {}
        for key, cell_per_path in cells.items():
            n_total_cell = sum(v["n_filled"] for v in cell_per_path.values())
            by_cell_exceeds[key] = {
                "n_filled_total": n_total_cell,
                "insufficient_n": n_total_cell < MIN_CELL_N,
                "by_path_exceeds": {
                    str(pid): bool(v["trades_per_year"] > implied_trades_per_year)
                    if math.isfinite(v["trades_per_year"])
                    else None
                    for pid, v in cell_per_path.items()
                },
            }

        points[f"{candidate:.3f}"] = {
            "fee_budget_monthly": candidate,
            "scale_vs_current": scale,
            "target_signal_rate_adjusted": adjusted_rate,
            "implied_trades_per_year": implied_trades_per_year,
            "unconditional_trades_per_year_by_path": {
                str(pid): tpy for pid, tpy in unconditional_trades_per_year.items()
            },
            "unconditional_by_path_exceeds": by_path_exceeds,
            "by_cell": by_cell_exceeds,
        }

    n_cells_sufficient = sum(
        1
        for v in points[f"{sweep_range[0] + 3 * step:.3f}"]["by_cell"].values()
        if not v["insufficient_n"]
    )

    return {
        "fee_budget_monthly_current": fee_budget_current,
        "target_signal_rate_current": target_signal_rate_current,
        "bars_per_year": BARS_PER_YEAR,
        "scaling_assumption": (
            "linear: target_signal_rate_adjusted = target_signal_rate * (candidate/current)"
        ),
        "sweep_grid": grid,
        "n_cells_with_sufficient_n_at_central_point": n_cells_sufficient,
        "points": points,
    }


# ============================================================================
# Bloco 2 — checagem de Simpson nos números-manchete (DESCOBERTA).
# ============================================================================


def _decompose_metrics(trades_filled: pl.DataFrame, *, source: str) -> dict[str, Any]:
    if trades_filled.height == 0:
        return {
            "n_trades": 0,
            "insufficient_n": True,
            "total_sharpe": None,
            "directional_sharpe": None,
            "carry_share": None,
            "ret_net_bps_per_trade": None,
        }
    result = decompose(trades_filled, source=source)
    insufficient = result.n_trades < MIN_CELL_N
    ret_net_bps = None
    if result.pnl_total.valid:
        try:
            ret_net_bps = result.pnl_total.per_unit().to_json()
        except ValueError:
            ret_net_bps = None
    return {
        "n_trades": result.n_trades,
        "insufficient_n": insufficient,
        "total_sharpe": result.total_sharpe.to_json(),
        "directional_sharpe": result.directional_sharpe.to_json(),
        "carry_share": result.carry_share.to_json(),
        "ret_net_bps_per_trade": ret_net_bps,
    }


def _hhi_by_fold_side(model_id: str = MODEL_ID_CAMADA1) -> pl.DataFrame:
    """Carrega `hhi`/`hhi_effective` dos 30 arquivos de diagnóstico por
    fold x lado já persistidos (`models/{model_id}/diagnostics/fold_N_
    {side}.json`, Fase A) — não recalcula (recalcular exigiria o `X`/
    `booster` do fold, não persistidos)."""
    diag_dir = MODELS_DIR / model_id / "diagnostics"
    rows: list[dict[str, Any]] = []
    for path in sorted(diag_dir.glob("fold_*_*.json")):
        d = orjson.loads(path.read_bytes())
        rows.append(
            {
                "fold_id": d["fold_id"],
                "side": d["side"],
                "hhi": d["hhi"],
                "hhi_effective": d["hhi_effective"],
            }
        )
    return pl.DataFrame(rows)


_HHI_STRATIFIED_METHODOLOGY = (
    "media de HHI por fold, ponderada por fracao de trades do fold no subconjunto"
)


def _weighted_hhi(
    realized: pl.DataFrame, hhi_df: pl.DataFrame, *, side: int, filter_expr: pl.Expr
) -> dict[str, Any]:
    """HHI "estratificado" por regime/tercil é uma APROXIMAÇÃO declarada:
    HHI é uma propriedade do MODELO treinado por fold (concentração de
    `gain_by_column`), não do trade individual — não existe HHI "do
    trade". Reportado aqui como a média de HHI por fold PONDERADA pela
    fração dos trades REALIZADOS daquele fold que caem no subconjunto
    (`filter_expr`) — não é um refit condicional a regime (isso exigiria
    retreinar, fora de escopo/CONSTRUTIVO). Documentado explicitamente no
    campo `methodology` do retorno, não escondido atrás do número."""
    side_hhi = hhi_df.filter(pl.col("side") == side)
    weights: dict[int, float] = {}
    total_n = 0
    for row in side_hhi.iter_rows(named=True):
        fold_trades = realized.filter(
            (pl.col("side_hat") == side) & (pl.col("fold_id") == row["fold_id"])
        )
        n = fold_trades.filter(filter_expr).height
        weights[row["fold_id"]] = n
        total_n += n
    if total_n == 0:
        return {
            "hhi_weighted": None,
            "hhi_effective_weighted": None,
            "n_trades_total": 0,
            "methodology": _HHI_STRATIFIED_METHODOLOGY,
        }
    hhi_w = sum(
        row["hhi"] * weights[row["fold_id"]] / total_n for row in side_hhi.iter_rows(named=True)
    )
    hhi_eff_w = sum(
        row["hhi_effective"] * weights[row["fold_id"]] / total_n
        for row in side_hhi.iter_rows(named=True)
    )
    return {
        "hhi_weighted": hhi_w,
        "hhi_effective_weighted": hhi_eff_w,
        "n_trades_total": total_n,
        "methodology": _HHI_STRATIFIED_METHODOLOGY,
    }


def stratified_headlines(realized: pl.DataFrame, hhi_df: pl.DataFrame) -> dict[str, Any]:
    """Bloco 2 — DESCOBERTA. Recomputa total_sharpe/directional_sharpe/
    carry_share/ret_net (bps/trade via `Metric.per_unit()`)/taxas de
    barreira, estratificado por lado x regime estrutural e lado x tercil
    de custo, lado a lado com o valor pooled. Célula `n < MIN_CELL_N` sai
    `insufficient_n: true`, estimativas `None` (não estimadas). Não
    conclui quais divergências são materiais."""
    out: dict[str, Any] = {"pooled": {}, "by_side_regime": {}, "by_side_cost_tercile": {}}

    for side, side_label in _SIDE_LABEL_BY_HAT.items():
        sub = _filled(realized.filter(pl.col("side_hat") == side))
        out["pooled"][side_label] = {
            **_decompose_metrics(sub, source=f"faixa1_5::pooled::{side_label}"),
            **_barrier_rates(realized.filter(pl.col("side_hat") == side)),
        }

        for regime in _STRUCTURAL_REGIMES:
            key = f"{side_label}_{regime}"
            cell_all = realized.filter((pl.col("side_hat") == side) & (pl.col("regime") == regime))
            cell_filled = _filled(cell_all)
            out["by_side_regime"][key] = {
                **_decompose_metrics(cell_filled, source=f"faixa1_5::by_regime::{key}"),
                **_barrier_rates(cell_all),
                **_weighted_hhi(
                    realized, hhi_df, side=side, filter_expr=pl.col("regime") == regime
                ),
            }

        cost_valid = realized.filter(pl.col(_COST_FEATURE).is_not_null())[_COST_FEATURE]
        if cost_valid.len() >= 3:
            q_low = float(cost_valid.quantile(1 / 3, interpolation="linear"))  # type: ignore[arg-type]
            q_high = float(cost_valid.quantile(2 / 3, interpolation="linear"))  # type: ignore[arg-type]
            tercile_bounds: dict[str, tuple[float | None, float | None]] = {
                "LOW_COST": (None, q_low),
                "MID_COST": (q_low, q_high),
                "HIGH_COST": (q_high, None),
            }
            for label, (lo, hi) in tercile_bounds.items():
                expr = pl.col(_COST_FEATURE).is_not_null()
                if lo is not None:
                    expr = expr & (pl.col(_COST_FEATURE) > lo)
                if hi is not None:
                    expr = expr & (pl.col(_COST_FEATURE) <= hi)
                key = f"{side_label}_{label}"
                cell_all = realized.filter((pl.col("side_hat") == side) & expr)
                cell_filled = _filled(cell_all)
                out["by_side_cost_tercile"][key] = {
                    **_decompose_metrics(cell_filled, source=f"faixa1_5::by_cost_tercile::{key}"),
                    **_barrier_rates(cell_all),
                    **_weighted_hhi(realized, hhi_df, side=side, filter_expr=expr),
                }
    return out


# ============================================================================
# Bloco 3 — dispersão entre paths (DESCOBERTA).
# ============================================================================


def _ci95_mean(values: np.ndarray) -> tuple[float, float]:
    n = values.shape[0]
    if n < 2:
        return float("nan"), float("nan")
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    if std == 0.0:
        return mean, mean
    from scipy.stats import norm

    z = float(norm.ppf(0.975))
    half = z * std / math.sqrt(n)
    return mean - half, mean + half


def path_dispersion(
    realized: pl.DataFrame, splits: tuple[cpcv.CPCVSplit, ...], predictions: pl.DataFrame
) -> dict[str, Any]:
    """Bloco 3 — DESCOBERTA. Por `path_id`: `n_filled`, cobertura
    calendário, trades/ano, ret_net médio ponderado + IC95, distribuição
    de regime, threshold efetivo (quantil de `confidence` realizado vs
    `target_signal_rate`), fração de barras compartilhadas com outros
    paths. Spearman `n_filled` x `ret_net médio`, n=5 (ressalva explícita).

    **Correção (Faixa 1.6, Bloco 2 Fase A, 2026-08-09) —
    `threshold_effective_confidence_quantile` era medido sobre a
    população ERRADA.** Até 2026-08-09 este campo tomava o quantil `1 -
    target_signal_rate` de `confidence` dentro de `realized` — que já é
    só sinais EMITIDOS (`side_hat != 0`, pós-seleção: toda linha ali JÁ
    passou `confidence > tau`). Isso é quantil-de-um-quantil: path 0 media
    exatamente `1,0000` com 7.162 trades preenchidos, o que o nome do
    campo sugeria (erradamente) ser um threshold que produziria ZERO
    trades. Verificado empiricamente (`src.analysis.
    faixa1_6_reconciliation`, Bloco 2): recalculado sobre a população
    CORRETA — todo bar OOF que o modelo pontuou naquele path, via
    `predictions` (`is_oof=True`, SEM filtrar `side_hat != 0`) — os 5
    valores caem numa faixa estreita e plausível (0,55–0,60), não mais
    colados em 1,0000 nem variando 0,74–1,00. `predictions` agora é
    parâmetro obrigatório desta função por causa disso.

    **Limitação de independência dos CIs, registrada aqui e não
    corrigida nesta rodada:** os CI95 abaixo tratam cada trade dentro de
    um path como i.i.d. — não são: a MESMA barra pode aparecer em até 5
    paths com retornos correlacionados (mesma barreira, mesmo `ret_net`,
    modelos-fold diferentes). Os CIs são provavelmente OTIMISTAS (mais
    estreitos que o real). Mesma família de problema do §16.5 (Lo 2002),
    mas por duplicação ENTRE paths, não autocorrelação DENTRO de um
    path — corrigir exigiria um bootstrap por bloco de t0 cruzando os 5
    paths, fora do escopo desta rodada (DESCOBERTA, não correção)."""
    target_signal_rate = float(load_constant("target_signal_rate"))
    path_ids = sorted(realized["path_id"].unique().to_list())
    fold_to_path = fold_to_path_map(splits)
    all_scored = predictions.filter(pl.col("is_oof"))
    folds_by_path: dict[int, list[int]] = {}
    for fold_id, pid in fold_to_path.items():
        folds_by_path.setdefault(pid, []).append(fold_id)

    all_t0_by_path: dict[int, set[Any]] = {
        pid: set(realized.filter(pl.col("path_id") == pid)["t0"].to_list()) for pid in path_ids
    }

    per_path: dict[str, Any] = {}
    n_filled_series: list[int] = []
    mean_ret_series: list[float] = []
    for pid in path_ids:
        sub_all = realized.filter(pl.col("path_id") == pid)
        sub_filled = _filled(sub_all)
        n_filled = sub_filled.height
        span = backtest_lite.span_seconds(sub_filled["t0"]) if n_filled else 0.0
        span_years = span / (backtest_lite.DAYS_PER_YEAR * backtest_lite.SECONDS_PER_DAY)
        tpy = n_filled / span_years if span_years > 0 else float("nan")

        bps = (
            sub_filled["ret_net"].to_numpy().astype(np.float64) * 10_000
            if n_filled
            else np.array([])
        )
        mean_bps = float(np.mean(bps)) if bps.size else float("nan")
        ci_low, ci_high = _ci95_mean(bps) if bps.size else (float("nan"), float("nan"))

        regime_counts = (
            sub_all.group_by("regime").len().sort("regime").to_dicts() if sub_all.height else []
        )

        others_t0: set[Any] = (
            set().union(*(v for k, v in all_t0_by_path.items() if k != pid))
            if len(path_ids) > 1
            else set()
        )
        n_shared = len(all_t0_by_path[pid] & others_t0)
        frac_shared = n_shared / len(all_t0_by_path[pid]) if all_t0_by_path[pid] else float("nan")

        # POPULAÇÃO CORRETA (Bloco 2 Fase A) — todo bar OOF pontuado nos
        # folds deste path, SEM filtrar side_hat != 0 (`all_scored`, não
        # `sub_all`/`realized`, que já é pós-seleção — ver docstring).
        scored_this_path = all_scored.filter(pl.col("fold_id").is_in(folds_by_path.get(pid, [])))
        conf_all_scored = (
            scored_this_path["confidence"].to_numpy().astype(np.float64)
            if scored_this_path.height
            else np.array([])
        )
        threshold_effective = (
            float(np.quantile(conf_all_scored, 1.0 - target_signal_rate))
            if conf_all_scored.size
            else float("nan")
        )

        n_filled_series.append(n_filled)
        mean_ret_series.append(mean_bps)

        per_path[str(pid)] = {
            "n_signals": sub_all.height,
            "n_filled": n_filled,
            "span_seconds": span,
            "trades_per_year": tpy,
            "mean_ret_net_bps": mean_bps,
            "ci95_low_bps": ci_low,
            "ci95_high_bps": ci_high,
            "regime_distribution": regime_counts,
            "threshold_effective_confidence_quantile": threshold_effective,
            "n_all_scored_bars_this_path": int(scored_this_path.height),
            "n_t0_shared_with_other_paths": n_shared,
            "fraction_t0_shared": frac_shared,
        }

    if len(path_ids) >= 3 and all(math.isfinite(x) for x in mean_ret_series):
        rho, p = spearmanr(n_filled_series, mean_ret_series)
        spearman_result = {"rho": float(rho), "p": float(p), "n_paths": len(path_ids)}
    else:
        spearman_result = {"rho": float("nan"), "p": float("nan"), "n_paths": len(path_ids)}

    return {
        "per_path": per_path,
        "spearman_n_filled_vs_mean_bps": spearman_result,
        "ci_independence_caveat": (
            "CI95 por path trata trades como i.i.d.; a mesma barra pode aparecer em "
            "ate 5 paths com retorno correlacionado (mesma barreira, ret_net identico, "
            "modelo-fold diferente) -- CIs provavelmente otimistas (mais estreitos que "
            "o real). Mesma familia do §16.5 (Lo 2002), por duplicacao ENTRE paths, "
            "nao autocorrelacao intra-path. Nao corrigido nesta rodada."
        ),
    }


# ============================================================================
# Bloco 4 — confidence_rank intra-fold (CONSTRUTIVO). n_lifetime += 1.
# ============================================================================


def add_confidence_rank(predictions: pl.DataFrame) -> pl.DataFrame:
    """Bloco 4. ADICIONA `confidence_rank` (percentil, (0,1], do `score_
    {side}_raw` DENTRO do `fold_id` que o gerou) a uma CÓPIA de
    `predictions` — não remove `confidence`. Resolve o problema
    verificado (calibrador isotônico ajustado POR FOLD: empilhar 15 mapas
    devolve uma ORDEM só localmente monotônica, não globalmente) sem
    recalibrar sobre OOF empilhado (isso vazaria os 15 folds entre si na
    própria probabilidade, que o Meta consumiria na V1.1 — proibido pelo
    prompt). `confidence_rank` é ordem pura (rank), não probabilidade —
    não substitui `confidence` onde a magnitude calibrada é necessária."""
    long_rank = pl.col("score_long_raw").rank(method="average").over("fold_id") / pl.col(
        "score_long_raw"
    ).count().over("fold_id")
    short_rank = pl.col("score_short_raw").rank(method="average").over("fold_id") / pl.col(
        "score_short_raw"
    ).count().over("fold_id")
    rank_by_side = (
        pl.when(pl.col("side_hat") == 1)
        .then(long_rank)
        .when(pl.col("side_hat") == -1)
        .then(short_rank)
        .otherwise(None)
        .alias("confidence_rank")
    )
    return predictions.with_columns(rank_by_side)


def confidence_variants_analysis(
    predictions_with_rank: pl.DataFrame, mf_data: pl.DataFrame
) -> dict[str, Any]:
    """Reexecuta D1 (decis por lado, correlações, exclusão de decil k) e
    D4 (raw vs. versão) sobre as TRÊS colunas — `score_{side}_raw`
    (cru), `confidence` (calibrado), `confidence_rank` (novo) — usando as
    MESMAS funções de `src.analysis.calibration_diagnostics`
    (`build_side_population`/`decile_profile`/`_rank_correlations`/
    `_mean_excluding_decile`), não uma rubrica nova."""
    labels_cols = mf_data.select(["t0", "side", "barrier_hit", "ret_net", "regime", _E02F_FEATURE])
    out: dict[str, Any] = {}
    for side, side_label in _SIDE_LABEL_BY_HAT.items():
        pop = caldiag.build_side_population(predictions_with_rank, labels_cols, mf_data, side=side)
        pop = pop.join(
            predictions_with_rank.select(["t0", "fold_id", "confidence_rank"]),
            on=["t0", "fold_id"],
            how="left",
        )
        variants: dict[str, Any] = {}
        for col_label, col_name in (
            ("raw_score", "raw_score"),
            ("calibrated", "confidence"),
            ("rank", "confidence_rank"),
        ):
            profile = caldiag.decile_profile(pop, confidence_col=col_name)
            correlations = caldiag._rank_correlations(profile)
            with_decile = caldiag._assign_deciles(pop, confidence_col=col_name)
            mean_excl = caldiag._mean_excluding_decile(profile, with_decile)
            variants[col_label] = {
                "decile_profile": profile,
                "correlations": correlations,
                "mean_excluding_decile_k": mean_excl,
            }
        by_regime: dict[str, Any] = {}
        for regime in _STRUCTURAL_REGIMES:
            sub = pop.filter(pl.col("regime") == regime)
            by_regime[regime] = {
                col_label: {
                    "correlations": caldiag._rank_correlations(
                        caldiag.decile_profile(sub, confidence_col=col_name)
                    )
                }
                for col_label, col_name in (
                    ("raw_score", "raw_score"),
                    ("calibrated", "confidence"),
                    ("rank", "confidence_rank"),
                )
            }
        out[side_label] = {"variants": variants, "by_regime": by_regime}
    return out


# ============================================================================
# Bloco 5 — E02f: medição in-fold (DESCOBERTA). PROIBIDO alterar
# monotonic.py, hardcodar regra por regime, ou escolher entre rotas.
# ============================================================================


def e02f_in_fold(mf_data: pl.DataFrame, splits: tuple[cpcv.CPCVSplit, ...]) -> dict[str, Any]:
    """Bloco 5 — DESCOBERTA. Para cada um dos 15 folds x 2 lados: IC de
    `E02f_funding_z_expanding` por ambiente (`compute_ic_by_env`, os 6
    ambientes de `src.models.environments`), IN-FOLD (só `train_idx` do
    split, nunca teste — B02/B06), sem retreinar. `screen_sign` é o sinal
    que `_assign_from_ic` (o mesmo núcleo estatístico de `screen_
    monotone_constraints`) atribuiria SE `E02f` não estivesse em
    `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` — lido do módulo real, não
    duplicado. Não decide/hardcoda nada; só mede."""
    min_consistent_envs = int(load_constant("alpha_monotonic_consistency_min_envs"))
    out: dict[str, Any] = {}
    for split in splits:
        train_bars = mf_data[split.train_idx]
        fold_entry: dict[str, Any] = {}
        for side in (1, -1):
            train_side = ds.side_subset(train_bars, side=side)
            df_env = assign_environments(train_side)
            ic_by_env = compute_ic_by_env(df_env, _E02F_FEATURE, "ret_net")
            screen_sign, mean_ic, n_consistent, n_with_data = _assign_from_ic(
                ic_by_env, min_consistent_envs=min_consistent_envs
            )
            forced_sign = _ECONOMIC_FORCED_CONSTRAINT_BY_SIDE[_E02F_FEATURE][side]
            n_by_env = {
                env: int(
                    df_env.filter(pl.col("env") == env)
                    .filter(pl.col(_E02F_FEATURE).is_not_null() & pl.col("ret_net").is_not_null())
                    .height
                )
                for env in ENVIRONMENTS
            }
            consistency_sq = (n_consistent / 6.0) ** 2
            fold_entry[_SIDE_LABEL_BY_HAT[side]] = {
                "ic_by_env": ic_by_env,
                "n_by_env": n_by_env,
                "mean_ic": mean_ic,
                "n_consistent_envs": n_consistent,
                "n_envs_with_data": n_with_data,
                "screen_sign_if_not_forced": screen_sign,
                "forced_sign_actual": forced_sign,
                "consistency_metric_ic_x_consistency_sq": abs(mean_ic) * consistency_sq
                if math.isfinite(mean_ic)
                else float("nan"),
            }
        out[str(split.split_id)] = fold_entry
    return out


# ============================================================================
# Bloco 6 — orquestração, sem campo de veredito.
# ============================================================================


def run_faixa1_5(
    predictions: pl.DataFrame, mf_data: pl.DataFrame, splits: tuple[cpcv.CPCVSplit, ...]
) -> dict[str, Any]:
    fold_to_path = fold_to_path_map(splits)
    realized = build_realized_trades(predictions, mf_data, fold_to_path)
    hhi_df = _hhi_by_fold_side()

    predictions_with_rank = add_confidence_rank(predictions)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "task": "faixa1_5_prerequisites",
        "fee_budget_sweep": fee_budget_sweep(realized),
        "stratified_headlines": stratified_headlines(realized, hhi_df),
        "path_dispersion": path_dispersion(realized, splits, predictions),
        "confidence_variants": confidence_variants_analysis(predictions_with_rank, mf_data),
        "e02f_in_fold": e02f_in_fold(mf_data, splits),
    }
    return payload


def run_and_save_faixa1_5(*, dest_path: Path | None = None) -> Path:
    """Ponto de entrada MANUAL (mesmo padrão de `run_and_save_cost_
    surface_report`/`run_and_save_faixa1_report`). Chame:
    `uv run python -m src.analysis.faixa1_5_prerequisites`."""
    mf = ds.build_modeling_frame()
    cpcv_result = cpcv.generate_splits(mf.data)
    predictions = load_predictions()

    payload = run_faixa1_5(predictions, mf.data, cpcv_result.splits)
    payload = {**report_provenance(), **payload}

    dest = dest_path if dest_path is not None else DEFAULT_OUTPUT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    import os

    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest)
    logger.info("analysis.faixa1_5_prerequisites.written", path=str(dest))
    return dest


if __name__ == "__main__":
    run_and_save_faixa1_5()
