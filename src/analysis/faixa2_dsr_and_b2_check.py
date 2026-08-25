"""Faixa 2, pré-FASE 3 — DSR formal e comparação contra B2 (buy-and-
hold), pedido do Manager (2026-08-09) sobre a configuração "long +
filtro C07" (`faixa2_vol_accelerator_test.py::run_vol_accelerator_test_
composed`, `total_sharpe` side_1 = +0,4966).

**Dois números, não um trial novo.** Isto é INTERPRETAÇÃO ESTATÍSTICA de
um resultado já medido (id 15 do `n_lifetime`), não uma busca nova —
não incrementa `N_lifetime` (mesmo raciocínio das correções de dado do
E2, "confirmação/caracterização, não trial").

1. **DSR** (`src.validation.dsr`, primeira implementação neste repo,
   §11.6) — usa `N_lifetime` AUDITADO (`audit/n_lifetime.yaml::counter`)
   como `n_trials`, sobre os retornos POR TRADE da população long+filtro
   (reconstruída aqui via `build_production_fired_population` + o mesmo
   percentil de admissão já calibrado, não um novo).
2. **B2 pooled** (`src.models.baselines.run_b2_buy_and_hold`, já
   existente) sobre o MESMO período de calendário — mais um teste de
   diferença de Sharpe por bootstrap em blocos
   (`dsr.sharpe_difference_block_bootstrap`) entre as duas séries
   agregadas por DIA (mesma granularidade do B2), pra não depender de
   uma fórmula fechada de covariância (Jobson-Korkie/Memmel)
   reconstruída de memória."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
import yaml

from src.core.provenance import report_provenance
from src.data import lake
from src.models import backtest_lite
from src.models import baselines as bl
from src.models import dataset as ds
from src.models._constants import load_constant
from src.validation import dsr as dsr_mod

from . import faixa1_5_prerequisites as f15
from .faixa2_vol_accelerator_test import (
    _COST_PCTILE_FEATURE,
    build_production_fired_population,
    calibrate_admission_percentile,
)

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_OUTPUT_PATH: Final[Path] = EXPERIMENTS_DIR / "faixa2_dsr_and_b2_check.json"

# Bootstrap do teste de diferença de Sharpe -- 2000 replicas da MESMA
# ordem de grandeza de precisao de p-valor que os 1000 do B1
# (config/constants.yaml::alpha_b1_n_seeds), dobrado por ser um teste de
# diferenca (2 estatisticas por replica, nao 1).
_BOOTSTRAP_N_REPS = 2000  # noqa: magic-number
# `_BOOTSTRAP_BLOCK_DAYS` (removido, ADR-004 Fase 3, AG-254) -- era 20
# dias ESTIPULADO ("~3 semanas de calendário... sem esvaziar o número de
# blocos", sem medição real, B23 latente). `dsr.sharpe_difference_
# block_bootstrap(block_size=None)` agora MEDE o bloco via `bootstrap_
# diff.select_block_length` sobre a série de diferença pareada -- ver
# docstring daquela função para a reconciliação completa.


def _audited_n_lifetime() -> int:
    path = _REPO_ROOT / "audit" / "n_lifetime.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return int(data["counter"])


def build_long_c07_filtered_population(
    symbol: str = "BTCUSDT",
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Reconstrói a população "long + filtro C07" com a MESMA calibração
    de `run_vol_accelerator_test_composed` — percentil `P` calibrado
    sobre o conjunto disparado dos DOIS lados juntos (mesmo orçamento
    combinado, `target_trades_per_year`), não recalibrado só sobre o
    long (calibrar só sobre o long contra o orçamento cheio daria P=1,0
    -- o long sozinho já cabe perto do orçamento total, então "nenhum
    filtro" pareceria bater a meta; o percentil certo é o do sistema
    completo, aplicado depois ao subconjunto long). Filtra pra
    `side_hat == 1` DEPOIS de calibrar, não antes."""
    target_tpy = float(load_constant("target_signal_rate")) * f15.BARS_PER_YEAR
    fired = build_production_fired_population(symbol)
    calib = calibrate_admission_percentile(fired, target_trades_per_year=target_tpy)
    admitted_long = fired.filter(
        (pl.col("side_hat") == 1) & (pl.col(_COST_PCTILE_FEATURE) <= calib["percentil_admissao"])
    )
    admitted_filled = admitted_long.filter(pl.col("barrier_hit") != "NOFILL")
    return admitted_filled, calib


def run_dsr_check(symbol: str = "BTCUSDT") -> dict[str, Any]:
    n_trials = _audited_n_lifetime()
    admitted_filled, calib = build_long_c07_filtered_population(symbol)

    ret_net = admitted_filled["ret_net"].to_numpy().astype(np.float64)
    span = backtest_lite.span_seconds(admitted_filled["t0"])
    _sharpe_check, trades_per_year = backtest_lite.sharpe_naive(ret_net, span_seconds=span)

    result = dsr_mod.compute_dsr(ret_net, n_trials=n_trials, trades_per_year=trades_per_year)

    return {
        "n_lifetime_auditado": n_trials,
        "calibracao_percentil_reusada": calib,
        "n_trades": admitted_filled.height,
        "dsr_result": {
            "n_trials": result.n_trials,
            "n_obs": result.n_obs,
            "trades_per_year": result.trades_per_year,
            "sr_per_trade": result.sr_per_trade,
            "sr_annualized": result.sr_annualized,
            "skewness": result.skewness,
            "excess_kurtosis": result.excess_kurtosis,
            "sigma_sr_per_trade": result.sigma_sr_per_trade,
            "sr0_per_trade": result.sr0_per_trade,
            "sr0_annualized": result.sr0_annualized,
            "dsr": result.dsr,
            "dsr_passa_limiar_convencional_0_95": dsr_mod.dsr_passes_conventional_threshold(
                result.dsr
            ),
        },
        "nota": (
            "DSR calculado na escala POR TRADE (T=n_trades, skew/kurtosis "
            "amostrais reais, nao Normal assumido) -- sr_annualized/"
            "sr0_annualized reportados so para leitura (mesma escala de "
            "sqrt(trades_per_year) aplicada aos dois, razao preservada). "
            "sigma_sr usa o erro-padrao do proprio Sharpe observado como "
            "proxy pra dispersao entre os N_lifetime trials (distribuicao "
            "real de Sharpe por trial nao foi rastreada individualmente "
            "neste projeto -- mesmo proxy do exemplo numerico de Lopez de "
            "Prado, AFML cap. 8)."
        ),
    }


def _daily_returns_from_trades(trades: pl.DataFrame, start: str, end: str) -> pl.DataFrame:
    """Soma `ret_net` por dia de calendário (`t0.date()`), dias sem
    trade recebem 0 (posição flat) -- grade diária completa em
    `[start, end]` pra alinhar com `run_b2_buy_and_hold` (que também usa
    barras diárias)."""
    by_day = (
        trades.with_columns(pl.col("t0").dt.date().alias("_day"))
        .group_by("_day")
        .agg(pl.col("ret_net").sum().alias("ret_net_day"))
    )
    full_grid = pl.date_range(
        pl.Series([start]).str.strptime(pl.Date, "%Y-%m-%d")[0],
        pl.Series([end]).str.strptime(pl.Date, "%Y-%m-%d")[0],
        interval="1d",
        eager=True,
    ).alias("_day")
    grid_df = pl.DataFrame({"_day": full_grid})
    joined = grid_df.join(by_day, on="_day", how="left").with_columns(
        pl.col("ret_net_day").fill_null(0.0)
    )
    return joined.sort("_day")


def run_b2_comparison(symbol: str = "BTCUSDT") -> dict[str, Any]:
    mf = ds.build_modeling_frame(symbol=symbol)
    start, end = ds.date_bounds(mf.data)

    admitted_filled, _calib = build_long_c07_filtered_population(symbol)
    daily_strategy = _daily_returns_from_trades(admitted_filled, start, end)

    b2 = bl.run_b2_buy_and_hold(symbol, start, end)

    b2_daily = lake.query_bars(symbol, "1d", start, end, source="klines_1m", cast_prices=True)
    b2_close = b2_daily.sort("open_time")["close"].cast(pl.Float64).to_numpy()
    b2_log_ret = np.diff(np.log(b2_close))
    # `b2_log_ret` tem 1 a menos que `b2_close`/dias -- alinhado pelo
    # FIM: log_ret[i] = log(close[i+1]/close[i]), atribuido ao dia i+1.
    n_align = min(b2_log_ret.shape[0], daily_strategy.height - 1)
    strategy_daily_all = daily_strategy["ret_net_day"].to_numpy().astype(np.float64)
    strategy_daily_arr = strategy_daily_all[1 : n_align + 1]
    b2_daily_arr = b2_log_ret[:n_align]

    diff_test = dsr_mod.sharpe_difference_block_bootstrap(
        strategy_daily_arr,
        b2_daily_arr,
        n_boot=_BOOTSTRAP_N_REPS,
        seed=int(load_constant("alpha_random_seed")),
    )

    strategy_sharpe_daily_annualized = (
        float(np.mean(strategy_daily_arr) / np.std(strategy_daily_arr, ddof=1))
        * float(np.sqrt(365.25))  # noqa: magic-number -- mesma convencao de DAYS_PER_YEAR do B2
        if np.std(strategy_daily_arr, ddof=1) > 0
        else float("nan")
    )

    return {
        "periodo": {"start": start, "end": end},
        "b2_buy_and_hold": {
            "sharpe_naive_anualizado": b2.sharpe_naive,
            "n_days": b2.n_days,
        },
        "long_mais_c07_agregado_diario": {
            "sharpe_naive_anualizado": strategy_sharpe_daily_annualized,
            "n_days_grade": daily_strategy.height,
            "n_days_com_trade": int((daily_strategy["ret_net_day"] != 0.0).sum()),
        },
        "teste_diferenca_bootstrap_blocos": diff_test,
        "nota": (
            "Series diarias ALINHADAS (mesmo n de dias, mesma janela de "
            "calendario) para o teste -- 'long+C07' agrega ret_net por "
            "dia (soma, 0 nos dias sem trade); B2 usa log-retorno diario "
            "do close. Teste por bootstrap em blocos (nao Jobson-Korkie/"
            "Memmel fechado) -- reamostra os PARES (dia a dia), preserva "
            "a correlacao contemporanea entre as duas series (mesmo "
            "ativo subjacente) sem depender de uma formula de covariancia "
            "reconstruida de memoria."
        ),
    }


def run_and_save_dsr_and_b2_check(*, dest_path: Path | None = None) -> Path:
    """Ponto de entrada MANUAL. Chame: `uv run python -c "from
    src.analysis.faixa2_dsr_and_b2_check import
    run_and_save_dsr_and_b2_check as r; r()"`."""
    t0 = time.perf_counter()
    payload: dict[str, Any] = {
        "dsr_check": run_dsr_check(),
        "b2_comparison": run_b2_comparison(),
    }
    payload["elapsed_seconds_total"] = time.perf_counter() - t0
    payload = {**report_provenance(), "task": "faixa2_dsr_and_b2_check", **payload}

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
        "analysis.faixa2_dsr_and_b2_check.written",
        path=str(dest),
        elapsed_seconds_total=round(payload["elapsed_seconds_total"], 1),
    )
    return dest


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    # AG-231 -- CLI adicionada 2026-08-25. Este modulo produz um artefato de
    # `experiments/` que DERIVA de `labels.parquet`, entao precisa ser
    # re-executado apos o relabel de AG-221; ate aqui so era chamavel via
    # `python -c "from ... import run_and_save_dsr_and_b2_check as r; r()"`, o que o deixava de
    # fora de qualquer orquestracao reproduzivel de re-execucao.
    import sys

    def _run() -> int:
        destino = run_and_save_dsr_and_b2_check()
        logger.info("analysis.faixa2_dsr_and_b2_check.cli_done", report_path=str(destino))
        return 0

    sys.exit(_run())
