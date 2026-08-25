"""S1 — sweep de sensibilidade `tp_atr_mult`/`sl_atr_mult` (reparametrização
R×S), `docs/s1_design_doc_sweep_tp_sl_reward_risk_2026-08-22.md`. Verificação
de robustez ao redor do valor de produção já escolhido (§16.10 regra 4) —
NUNCA "achamos R/S melhor" (§2 do design doc). Bypassa Feature/Regime
Engine/CPCV/`build_modeling_frame` de propósito (§4) — lê `labels.parquet`
15m direto, população INCONDICIONAL (não a que o Alpha dispara — ressalva
registrada, §11 risco #4 do design doc).

`veredito` fica sempre `"TBD"` neste módulo — o critério operacional de
"sobrevive à faixa" (§11 risco #1) é decisão do Manager, não travada aqui
(decisão confirmada por escrito, 2026-08-24)."""

from __future__ import annotations

import math
import os
import time
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog

from src.analysis.feasibility import breakeven_win_rate, edge_bruto_atr, frac_tp_sl_from_labels
from src.core.provenance import report_provenance
from src.data import lake
from src.features._sources import load_bars_15m
from src.features.groups.group_e import round_trip_cost_bps
from src.labels.backfill_multi_symbol import ALL_SYMBOLS
from src.labels.barrier_geometry import (
    REWARD_RISK_GRID,
    SL_MULT_GRID,
    filled_side_population,
    resolve_geometry,
)
from src.labels.barrier_sweep import resolve_barriers_vectorized
from src.labels.triple_barrier import LabelConfig
from src.models._constants import load_constant

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "s1_tp_sl_sensitivity_report.json"

#: §5 do design doc -- as 2 células cujo `tp_atr_mult` resolvido cai fora
#: do `sweep_range` DECLARADO de `tp_atr_mult` ([1,0; 3,0], `constants.
#: yaml`) -- decisão já travada e verificada no design doc (não recomputada
#: aqui a partir de `sweep_range` genérico; os 2 pontos exatos já são fato
#: registrado, `§11` risco #2).
_UNIVERSAL_EXCLUDED_CELLS: Final[frozenset[tuple[Fraction, Fraction]]] = frozenset(
    {
        (Fraction(2, 1), Fraction(9, 4)),  # tp=4.5 -- excede o teto do sweep_range
        (Fraction(1, 1), Fraction(3, 4)),  # tp=0.75 -- abaixo do piso do sweep_range
    }
)

_SIDES: Final[tuple[int, ...]] = (1, -1)

#: §8 do design doc — tolerância da checagem de identidade algébrica
#: (`edge_atr_units == sl_mult * edge_per_sl_unit`) e da checagem de
#: reprodução exata da célula central. Valor declarado a priori no design
#: doc, não medido/otimizado.
_IDENTITY_ABS_TOL: Final[float] = 1e-9  # noqa: magic-number

#: Conversão bps -> fração (mesma categoria de `_BPS_PER_UNIT`, definição
#: matemática, não constante de domínio — ver `src.labels.triple_barrier`).
_BPS_PER_UNIT: Final[float] = 10_000.0  # noqa: magic-number


def _r2_floor_stop_pct(*, maker_fee: float, taker_fee: float) -> float:
    """Piso de `stop_pct` do controle R2 (`CLAUDE.md` §0.2) -- custo
    round-trip <= `cost_stop_ratio_max` x stop, resolvido pra stop:
    `stop_min = custo_round_trip_pct / cost_stop_ratio_max`. Fixo (não
    depende de símbolo/ATR) -- o que varia por símbolo é o `sl_mult`
    mínimo viável pra alcançar esse piso, dado o ATR mediano do símbolo
    (ver `_min_viable_sl_mult` abaixo)."""
    cost_stop_ratio_max = float(load_constant("cost_stop_ratio_max"))
    cost_bps = round_trip_cost_bps(maker_fee, taker_fee)
    cost_pct = cost_bps / _BPS_PER_UNIT
    return cost_pct / cost_stop_ratio_max


def _min_viable_sl_mult(*, atr_median_side: float, r2_floor_stop_pct: float) -> float:
    """`sl_mult` mínimo pra `stop_pct_cell = sl_mult * atr_median_side`
    não violar o piso R2 -- célula com `sl_mult` abaixo disso é
    estruturalmente inviável PRA ESSE SÍMBOLO (não um ponto fraco a
    reportar com flag, um ponto que não existe -- §11 risco #3 do design
    doc, decisão do Manager 2026-08-22, reaplicada aqui com ATR medido
    fresco em vez do valor de 2 dias atrás citado no design doc)."""
    if atr_median_side <= 0.0 or not math.isfinite(atr_median_side):
        return float("inf")
    return r2_floor_stop_pct / atr_median_side


def _valid_cells_for_symbol(min_viable_sl_mult: float) -> tuple[tuple[Fraction, Fraction], ...]:
    out = []
    for reward_risk_ratio in REWARD_RISK_GRID:
        for sl_mult in SL_MULT_GRID:
            if (reward_risk_ratio, sl_mult) in _UNIVERSAL_EXCLUDED_CELLS:
                continue
            if float(sl_mult) < min_viable_sl_mult:
                continue
            out.append((reward_risk_ratio, sl_mult))
    return tuple(out)


def _load_side_inputs(
    symbol: str, labels: pl.DataFrame, *, side: int
) -> tuple[pl.DataFrame, float, int, int]:
    """`filled_side` + `atr_median_side` (não depende de tp/sl, calculado
    1x) + `n_total_side`/`n_nofill_side` (denominador de `frac_nofill`,
    também não depende de tp/sl)."""
    side_all = labels.filter(pl.col("side") == side)
    n_total_side = side_all.height
    n_nofill_side = int((side_all["barrier_hit"].cast(pl.Utf8) == "NOFILL").sum())
    filled_side = filled_side_population(labels, side=side)
    atr_median_side = (
        float(filled_side["atr_at_t0"].median())  # type: ignore[arg-type]
        if filled_side.height
        else float("nan")
    )
    return filled_side, atr_median_side, n_total_side, n_nofill_side


def _cell_result(
    filled_side: pl.DataFrame,
    mark_1m: pl.DataFrame,
    funding: pl.DataFrame,
    decision_bar_close_time_ms: np.ndarray,
    *,
    side: int,
    reward_risk_ratio: Fraction,
    sl_mult: Fraction,
    cfg: LabelConfig,
    atr_median_side: float,
    horizon_end_ms: np.ndarray | None = None,
) -> dict[str, Any]:
    tp_atr_mult, sl_atr_mult = resolve_geometry(reward_risk_ratio, sl_mult)
    resolved = resolve_barriers_vectorized(
        filled_side,
        mark_1m,
        funding,
        side=side,
        tp_atr_mult=tp_atr_mult,
        sl_atr_mult=sl_atr_mult,
        time_stop_ms=cfg.time_stop_ms,
        maker_fee=cfg.maker_fee,
        taker_fee=cfg.taker_fee,
        decision_bar_close_time_ms=decision_bar_close_time_ms,
        tf=cfg.resolution_id if cfg.resolution_id is not None else cfg.tf,
        horizon_end_ms=horizon_end_ms,
    )
    resolved_df = pl.DataFrame({"barrier_hit": resolved.barrier_hit})
    frac = frac_tp_sl_from_labels(resolved_df)

    # [corrigido pós-auditoria, §8] chamada por keyword, guarda de NaN
    # antes da checagem de identidade -- estrato vazio propaga NaN, nunca
    # aborta a execução inteira (mesma disciplina de feasibility.py).
    edge_atr_units = edge_bruto_atr(
        frac_tp=frac.frac_tp, frac_sl=frac.frac_sl, tp_atr_mult=tp_atr_mult, sl_atr_mult=sl_atr_mult
    )
    edge_per_sl_unit = (
        frac.frac_tp * float(reward_risk_ratio) - frac.frac_sl
        if math.isfinite(frac.frac_tp) and math.isfinite(frac.frac_sl)
        else float("nan")
    )
    if not (math.isnan(frac.frac_tp) or math.isnan(frac.frac_sl)):
        identity_diff = abs(edge_atr_units - float(sl_mult) * edge_per_sl_unit)
        assert identity_diff < _IDENTITY_ABS_TOL, (
            f"S1 identidade quebrada: edge_atr_units={edge_atr_units} != "
            f"sl_mult*edge_per_sl_unit={float(sl_mult) * edge_per_sl_unit} "
            f"(diff={identity_diff})"
        )

    breakeven_wr_frictionless = 1.0 / (1.0 + float(reward_risk_ratio))
    breakeven_wr_cost_adjusted = breakeven_win_rate(
        atr_pct=atr_median_side,
        tp_atr_mult=tp_atr_mult,
        sl_atr_mult=sl_atr_mult,
        maker_fee=cfg.maker_fee,
        taker_fee=cfg.taker_fee,
    )
    collision_rate = (
        float(np.mean(resolved.tie_break_used)) if resolved.tie_break_used.size else float("nan")
    )
    holding_mediano_bars = (
        float(np.median(resolved.n_bars_held)) if resolved.n_bars_held.size else float("nan")
    )

    return {
        "reward_risk_ratio": str(reward_risk_ratio),
        "sl_atr_mult_frac": str(sl_mult),
        "tp_atr_mult": tp_atr_mult,
        "sl_atr_mult": sl_atr_mult,
        "n_filled": filled_side.height,
        "frac_tp": frac.frac_tp,
        "frac_sl": frac.frac_sl,
        "frac_timeout": frac.frac_time,
        "frac_events_measured": frac.n,
        "edge_atr_units": edge_atr_units,
        "edge_per_sl_unit": edge_per_sl_unit,
        "breakeven_wr_frictionless": breakeven_wr_frictionless,
        "breakeven_wr_cost_adjusted": breakeven_wr_cost_adjusted,
        "collision_rate": collision_rate,
        "holding_mediano_bars": holding_mediano_bars,
        "stop_pct_cell": (
            sl_atr_mult * atr_median_side if math.isfinite(atr_median_side) else float("nan")
        ),
    }


def _side_label(side: int) -> str:
    return "long" if side == 1 else "short"


def run_s1_tp_sl_sensitivity(
    *,
    symbols: tuple[str, ...] = ALL_SYMBOLS,
    resolution_id: str | None = None,
    vol_estimator_id: str = "parkinson_w20",
) -> dict[str, Any]:
    """Núcleo com IO -- loop `symbol x side x célula válida`. Devolve o
    payload completo (sem `report_provenance`/timing, adicionados pelo
    caller `run_and_save_s1_tp_sl_sensitivity`).

    `resolution_id` (AG-232/AG-233, 2026-08-25) -- `None` (default)
    preserva bit-exato o comportamento histórico: grade de RELÓGIO 15m.
    `"R1"`/`"R2"`/`"R3"` roda sobre a grade CANÔNICA DE PRODUÇÃO
    (dollar bar, `AG-042`).

    **Por que existe.** Até esta correção o módulo lia
    `data/labels/{symbol}/15m/v1/labels.parquet` com o caminho HARDCODED,
    e `load_bars_15m` para as barras de decisão -- ou seja, decidia
    `tp_atr_mult`/`sl_atr_mult` (constantes CLASSE A) medindo uma grade
    que deixou de ser produção em 2026-08-16. Detectado quando o relabel
    de `AG-221` mudou `ret_gross` em +3 a +5 bps nas 15 combinações
    dollar-bar e este sweep devolveu edge IDÊNTICO até a 5ª casa decimal.

    **Rode POR RESOLUÇÃO, não pooled.** As janelas de feature do projeto
    são em CONTAGEM DE BARRA (`AG-043`), então "48 barras" é horizonte de
    tempo diferente em cada resolução -- agregar entre R1/R2/R3 mistura
    horizontes. Cada chamada produz um relatório próprio."""
    if resolution_id is not None:
        cfg = LabelConfig.from_constants(
            estimator_id=vol_estimator_id, resolution_id=resolution_id
        )
    else:
        cfg = LabelConfig.from_constants()
    r2_floor_stop_pct = _r2_floor_stop_pct(maker_fee=cfg.maker_fee, taker_fee=cfg.taker_fee)

    by_symbol: dict[str, Any] = {}
    cell_accum: dict[str, list[dict[str, Any]]] = {}
    production_check: dict[str, Any] | None = None

    for symbol in symbols:
        grade = resolution_id if resolution_id is not None else "15m"
        labels = pl.read_parquet(f"data/labels/{symbol}/{grade}/v1/labels.parquet")
        t0_min, t0_max = labels["t0"].min(), labels["t0"].max()
        start = (t0_min.date() - timedelta(days=3)).isoformat()  # type: ignore[union-attr]
        end = (t0_max.date() + timedelta(days=3)).isoformat()  # type: ignore[union-attr]
        mark_1m = lake.query_bars(
            symbol, "1m", start, end, source="mark_price_klines_1m", cast_prices=True
        )
        funding = lake.query_funding(symbol, start, end)
        # AG-232 -- barras de DECISÃO da grade real, não 15m fixo.
        bars_decisao = (
            lake.query_dollar_bars(symbol, start, end, resolution_id=resolution_id)
            if resolution_id is not None
            else load_bars_15m(symbol, start, end)
        )
        decision_bar_close_time_ms = (
            bars_decisao["close_time"].cast(pl.Int64).to_numpy().astype(np.int64)
        )
        # AG-116/AG-234 -- sob dollar bar o horizonte da barreira TIME é
        # CONTAGEM DE BARRA, não relógio. O grid de decisão é o `t0` único
        # dos labels (um por barra, os dois lados compartilham).
        t0_grid = np.sort(
            labels["t0"].unique().dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        )
        horizon_bars = int(load_constant("horizon_bars")) if resolution_id is not None else 0
        logger.info(
            "analysis.s1.symbol_data_loaded",
            symbol=symbol,
            n_labels=labels.height,
            n_mark_1m=mark_1m.height,
            n_funding=funding.height,
            n_bars_decisao=bars_decisao.height,
            grade=grade,
        )

        by_symbol[symbol] = {"by_side": {}}
        for side in _SIDES:
            side_label = _side_label(side)
            filled_side, atr_median_side, n_total_side, n_nofill_side = _load_side_inputs(
                symbol, labels, side=side
            )
            # AG-116 -- horizonte por CONTAGEM DE BARRA sob dollar bar.
            # Trades cujo horizonte cai além do grid carregado são
            # descartados aqui (mesma semântica de cauda incompleta de
            # `build_labels`), porque `resolve_barriers_vectorized` LEVANTA
            # se a janela de mark não cobrir o horizonte -- descartar antes
            # é o que mantém a rodada inteira viável.
            horizon_end_side: np.ndarray | None = None
            if resolution_id is not None and filled_side.height:
                _t0 = filled_side["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
                _idx = np.searchsorted(t0_grid, _t0, side="left") + horizon_bars
                _ok = _idx < t0_grid.shape[0]
                if not bool(_ok.all()):
                    filled_side = filled_side.filter(pl.Series(_ok))
                    _idx = _idx[_ok]
                horizon_end_side = t0_grid[_idx]
            min_viable_sl_mult = _min_viable_sl_mult(
                atr_median_side=atr_median_side, r2_floor_stop_pct=r2_floor_stop_pct
            )
            valid_cells = _valid_cells_for_symbol(min_viable_sl_mult)

            cells_out: dict[str, Any] = {}
            for reward_risk_ratio, sl_mult in valid_cells:
                cell_key = f"R{reward_risk_ratio}_S{sl_mult}"
                result = _cell_result(
                    filled_side,
                    mark_1m,
                    funding,
                    decision_bar_close_time_ms,
                    side=side,
                    reward_risk_ratio=reward_risk_ratio,
                    sl_mult=sl_mult,
                    cfg=cfg,
                    atr_median_side=atr_median_side,
                    horizon_end_ms=horizon_end_side,
                )
                result["frac_nofill"] = (
                    n_nofill_side / n_total_side if n_total_side else float("nan")
                )
                result["n_total_side"] = n_total_side
                cells_out[cell_key] = result
                cell_accum.setdefault(cell_key, []).append(result)

                if reward_risk_ratio == Fraction(4, 3) and sl_mult == Fraction(3, 2):
                    prod_tp = float(load_constant("tp_atr_mult"))
                    prod_sl = float(load_constant("sl_atr_mult"))
                    reproduces_prod = math.isclose(
                        result["tp_atr_mult"], prod_tp, abs_tol=_IDENTITY_ABS_TOL
                    ) and math.isclose(result["sl_atr_mult"], prod_sl, abs_tol=_IDENTITY_ABS_TOL)
                    if production_check is None:
                        production_check = {"reproduz_producao_exato": reproduces_prod}
                    else:
                        production_check["reproduz_producao_exato"] = (
                            production_check["reproduz_producao_exato"] and reproduces_prod
                        )

            by_symbol[symbol]["by_side"][side_label] = {
                "atr_median_side": atr_median_side,
                "min_viable_sl_mult": min_viable_sl_mult,
                "n_cells_validas": len(valid_cells),
                "n_cells_excluidas_r2": len(REWARD_RISK_GRID) * len(SL_MULT_GRID)
                - len(_UNIVERSAL_EXCLUDED_CELLS)
                - len(valid_cells),
                "cells": cells_out,
            }
            logger.info(
                "analysis.s1.side_done",
                symbol=symbol,
                side=side_label,
                n_cells_validas=len(valid_cells),
                atr_median_side=atr_median_side,
            )

    aggregate_by_cell: dict[str, Any] = {}
    for cell_key, results in cell_accum.items():
        edges = [r["edge_atr_units"] for r in results if math.isfinite(r["edge_atr_units"])]
        aggregate_by_cell[cell_key] = {
            "reward_risk_ratio": results[0]["reward_risk_ratio"],
            "sl_atr_mult_frac": results[0]["sl_atr_mult_frac"],
            "tp_atr_mult": results[0]["tp_atr_mult"],
            "sl_atr_mult": results[0]["sl_atr_mult"],
            "n_estratos_symbol_side": len(results),
            "edge_atr_units_mean_across_strata": float(np.mean(edges)) if edges else float("nan"),
            "edge_atr_units_min_across_strata": float(np.min(edges)) if edges else float("nan"),
            "edge_atr_units_max_across_strata": float(np.max(edges)) if edges else float("nan"),
        }

    return {
        "task": "s1_tp_sl_sensitivity",
        # AG-232 -- identidade da GRADE medida, no proprio artefato. Sem
        # isto, dois relatorios de grades diferentes sao indistinguiveis
        # por inspecao (mesma licao de AG-226/AG-218).
        "grade_medida": resolution_id if resolution_id is not None else "15m_relogio_LEGADO",
        "resolution_id": resolution_id,
        "config_hash": cfg.config_hash,
        "grid_declared_before_search": {
            "reward_risk_ratio": [str(r) for r in REWARD_RISK_GRID],
            "sl_atr_mult": [str(s) for s in SL_MULT_GRID],
        },
        "production_cell": {
            "reward_risk_ratio": "4/3",
            "sl_atr_mult": "3/2",
            "tp_atr_mult_equivalente": 2.0,
        },
        "grid_universally_excluded": [
            f"R={r},S={s} -> tp_atr_mult={float(r) * float(s)} fora do sweep_range declarado "
            "de tp_atr_mult ([1.0,3.0], constants.yaml)"
            for r, s in sorted(_UNIVERSAL_EXCLUDED_CELLS, key=str)
        ],
        "r2_floor_stop_pct": r2_floor_stop_pct,
        "n_lifetime_delta": 18,
        "n_lifetime_delta_nota": (
            "3 leituras concorrentes no design doc (9/18/1, §11 risco #8), nenhuma "
            "reconciliada pelo autor do desenho -- aplicado aqui o criterio MECANICO ja "
            "escrito no cabecalho do proprio n_lifetime.yaml (recalculo de backtest por "
            "combinacao), mesmo usado pelo precedente id=10 (3x3 por lado -> delta=18): "
            "resolve_barriers_vectorized e chamado separadamente por (celula, lado), "
            "9 celulas x 2 lados = 18. Simbolo permanece estrato de robustez, nao dimensao "
            "de busca (mesma leitura do precedente)."
        ),
        "by_symbol": by_symbol,
        "aggregate_by_cell": aggregate_by_cell,
        "sanidade_centro_da_grade": production_check or {"reproduz_producao_exato": None},
        "veredito": (
            "TBD -- criterio operacional de 'sobrevive a faixa' e decisao do "
            "Manager, nao computado aqui (design doc SS11 risco #1, "
            "confirmado 2026-08-24)"
        ),
    }


def run_and_save_s1_tp_sl_sensitivity(
    *,
    dest_path: Path | None = None,
    resolution_id: str | None = None,
    vol_estimator_id: str = "parkinson_w20",
) -> Path:
    """Ponto de entrada MANUAL com IO. Chame:
    `uv run python -c "from src.analysis.s1_tp_sl_sensitivity import
    run_and_save_s1_tp_sl_sensitivity as r; r()"`."""
    t_start = time.perf_counter()
    payload = run_s1_tp_sl_sensitivity(
        resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
    )
    payload["elapsed_seconds_total"] = time.perf_counter() - t_start
    payload = {**report_provenance(), **payload}

    # AG-232 -- arquivo POR GRADE. O default sem sufixo continua sendo o
    # da grade legada, para nao orfanar leitores; dollar bar grava em
    # arquivo proprio, nunca por cima.
    if dest_path is not None:
        dest = dest_path
    elif resolution_id is not None:
        dest = EXPERIMENTS_DIR / f"s1_tp_sl_sensitivity_report_{resolution_id}.json"
    else:
        dest = OUTPUT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest)
    logger.info(
        "analysis.s1.written",
        path=str(dest),
        elapsed_seconds_total=round(payload["elapsed_seconds_total"], 1),
    )
    return dest


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    # AG-231 -- CLI adicionada 2026-08-25. Este modulo produz um artefato de
    # `experiments/` que DERIVA de `labels.parquet`, entao precisa ser
    # re-executado apos o relabel de AG-221; ate aqui so era chamavel via
    # `python -c "from ... import run_and_save_s1_tp_sl_sensitivity as r; r()"`, o que o deixava de
    # fora de qualquer orquestracao reproduzivel de re-execucao.
    import argparse
    import sys

    def _run() -> int:
        ap = argparse.ArgumentParser(
            description=(
                "S1 -- sweep de geometria tp/sl. AG-232: use --resolution-id para "
                "medir a grade CANONICA DE PRODUCAO (dollar bar). Sem o argumento, "
                "mede a grade de relogio 15m LEGADA, que nao e producao desde AG-042."
            )
        )
        ap.add_argument(
            "--resolution-id",
            default=None,
            choices=["R1", "R2", "R3"],
            help="grade de producao a medir; omitir = 15m legado (bit-exato historico)",
        )
        ap.add_argument("--vol-estimator-id", default="parkinson_w20")
        args = ap.parse_args()
        if args.resolution_id is None:
            logger.warning(
                "analysis.s1_tp_sl_sensitivity.grade_legada",
                detail="AG-232 -- rodando sobre a grade de RELOGIO 15m, que nao e "
                "producao desde AG-042. Para decidir tp_atr_mult/sl_atr_mult (classe A) "
                "use --resolution-id R1|R2|R3",
            )
        destino = run_and_save_s1_tp_sl_sensitivity(
            resolution_id=args.resolution_id, vol_estimator_id=args.vol_estimator_id
        )
        logger.info(
            "analysis.s1_tp_sl_sensitivity.cli_done",
            report_path=str(destino),
            resolution_id=args.resolution_id,
        )
        return 0

    sys.exit(_run())
