"""Registro append-only de experimentos do Label Engine (§11.6) — **Sprint
6, explícito no roadmap do PRD**, não Sprint 11 como o V2 fazia ("o V2
colocava experiment tracking na V1.1, o que tornava o Gate 6 incalculável
por construção"). Sem isso, `N` (§11.6 `trial_budget`) não é reconstruível
e o DSR (Sprint 11) não é calculável.

Cada configuração de barreira testada (cada `LabelConfig` distinto rodado
sobre um período) vira UMA linha aqui — config completa + hash + timestamp
+ métricas básicas de distribuição, nunca sobrescrita nem removida (mesma
regra de edição de `audit/n_lifetime.yaml`/`config/venue_changelog.yaml`:
só se acrescenta).

**Formato: Parquet**, não JSONL — colunar, consistente com "Polars não
Pandas" do resto do stack, e diretamente consultável (`pl.read_parquet`)
para alimentar o DSR mais tarde sem parsing de texto. Cada chamada de
`record_experiment` faz um READ-MODIFY-WRITE ATÔMICO do arquivo inteiro:
lê o log existente, empilha a nova linha, escreve em `.tmp`, `fsync`,
`rename` (B29) — não é um append físico de baixo nível, é um "append"
lógico via substituição atômica do arquivo inteiro. Isso é seguro para o
caso de uso real deste projeto (um único desenvolvedor solo, sem
escritores concorrentes) — não é desenhado como log distribuído."""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import structlog

from ._paths import EXPERIMENTS_DIR
from .triple_barrier import LabelConfig

logger = structlog.get_logger(__name__)

LOG_PATH: Path = EXPERIMENTS_DIR / "label_engine_runs.parquet"

_SCHEMA: dict[str, Any] = {
    "experiment_id": pl.Int64,
    "logged_at_utc": pl.Datetime("ms", "UTC"),
    "sprint": pl.Int32,
    "stage": pl.Utf8,
    "symbol": pl.Utf8,
    "period_start": pl.Utf8,
    "period_end": pl.Utf8,
    "config_hash": pl.Utf8,
    "tp_atr_mult": pl.Float64,
    "sl_atr_mult": pl.Float64,
    # AG-031/B1 -- time_stop_bars (contagem de barra) aposentado como fonte
    # de LabelConfig, mas a COLUNA fica (registro histórico de runs
    # anteriores a 2026-08-16, todos em 32 barras @ 15m). Linhas novas
    # gravam null aqui e o valor real em time_stop_ms (abaixo) -- não
    # fabricar uma conversão pra trás que a config não tem mais.
    "time_stop_bars": pl.Int32,
    "time_stop_ms": pl.Int64,
    # AG-042 (2026-08-17) -- mesmo padrão de time_stop_bars/time_stop_ms
    # acima: fill_timeout_bars (contagem de barra) aposentado como campo
    # de LabelConfig (achado real ao dar suporte a dollar bar -- mesma
    # classe de bug de time_stop_bars, não pega na 1ª rodada), coluna
    # fica pro histórico, linhas novas gravam null aqui e o valor real em
    # fill_timeout_ms.
    "fill_timeout_bars": pl.Int32,
    "fill_timeout_ms": pl.Int64,
    # AG-031/B1 -- mesmo padrão de time_stop_bars/time_stop_ms acima:
    # atr_window (bars) aposentado como fonte de LabelConfig, coluna fica
    # pro histórico, linhas novas gravam null aqui e o valor real em
    # atr_window_ms.
    "atr_window": pl.Int32,
    "atr_window_ms": pl.Int64,
    "maker_fee": pl.Float64,
    "taker_fee": pl.Float64,
    # AG-042 (2026-08-17) -- rastreabilidade de qual GRADE gerou cada
    # linha (achado de gap real: nenhuma coluna registrava isso até
    # agora). `tf` (grade de tempo, "15m" etc.) ou `resolution_id`
    # (dollar bar, "R1"/"R2"/"R3") -- só um dos dois é não-null por
    # linha, mesmo XOR de `LabelConfig.tf`/`resolution_id`. Linhas
    # antigas (antes desta coluna existir) ficam null nas duas -- não
    # inventa retroativamente o que não foi registrado na hora.
    "tf": pl.Utf8,
    "resolution_id": pl.Utf8,
    # AG-116 (2026-08-20) -- horizonte da barreira TIME em CONTAGEM DE
    # BARRA, só sob resolution_id (mesmo XOR de tf/resolution_id acima,
    # ver LabelConfig.horizon_bars em triple_barrier.py). Linhas antigas
    # (antes desta coluna existir) ficam null -- não inventa
    # retroativamente o que não foi registrado na hora, mesmo padrão de
    # tf/resolution_id logo acima.
    "horizon_bars": pl.Int32,
    "n_labels": pl.Int64,
    "n_tp": pl.Int64,
    "n_sl": pl.Int64,
    "n_time": pl.Int64,
    "n_nofill": pl.Int64,
    "pct_tp": pl.Float64,
    "pct_sl": pl.Float64,
    "pct_time": pl.Float64,
    "pct_nofill": pl.Float64,
    "mean_ret_net": pl.Float64,
    "std_ret_net": pl.Float64,
    "sum_uniqueness": pl.Float64,  # N_eff medido (B24) — §0.2 R4
    "notes": pl.Utf8,
}


def load_experiment_log(path: Path | None = None) -> pl.DataFrame:
    """Lê o log inteiro; retorna um `pl.DataFrame` vazio (mas com o schema
    certo) se o arquivo ainda não existe — primeira chamada do projeto."""
    log_path = path if path is not None else LOG_PATH
    if not log_path.exists():
        return pl.DataFrame(schema=_SCHEMA)
    return pl.read_parquet(log_path)


def _next_experiment_id(existing: pl.DataFrame) -> int:
    if existing.is_empty():
        return 1
    ids = existing["experiment_id"].to_numpy().astype(np.int64)
    return int(ids.max()) + 1


def summarize_labels(labels: pl.DataFrame) -> dict[str, float | int]:
    """Métricas básicas de distribuição de `barrier_hit` + `ret_net` +
    `N_eff` (soma de `uniqueness`, medida — B24) sobre um `labels.parquet`
    já construído. `n=0` não quebra (dataset vazio -> tudo 0.0)."""
    n = labels.height
    if n == 0:
        return {
            "n_labels": 0,
            "n_tp": 0,
            "n_sl": 0,
            "n_time": 0,
            "n_nofill": 0,
            "pct_tp": 0.0,
            "pct_sl": 0.0,
            "pct_time": 0.0,
            "pct_nofill": 0.0,
            "mean_ret_net": 0.0,
            "std_ret_net": 0.0,
            "sum_uniqueness": 0.0,
        }

    barrier = labels["barrier_hit"].cast(pl.Utf8)
    n_tp = int((barrier == "TP").sum())
    n_sl = int((barrier == "SL").sum())
    n_time = int((barrier == "TIME").sum())
    n_nofill = int((barrier == "NOFILL").sum())

    # `.to_numpy()` primeiro pelo mesmo motivo de `assert_label_invariants`
    # em `triple_barrier.py`: o retorno agregado de `pl.Series.mean()`/
    # `.std()`/`.sum()` é uma união ampla nos stubs do polars.
    ret_net_arr = labels["ret_net"].to_numpy().astype(np.float64)
    uniqueness_arr = labels["uniqueness"].to_numpy().astype(np.float64)
    mean_ret = float(np.mean(ret_net_arr))
    std_ret = float(np.std(ret_net_arr, ddof=1)) if ret_net_arr.size > 1 else 0.0
    sum_uniq = float(np.sum(uniqueness_arr))

    return {
        "n_labels": n,
        "n_tp": n_tp,
        "n_sl": n_sl,
        "n_time": n_time,
        "n_nofill": n_nofill,
        "pct_tp": n_tp / n,
        "pct_sl": n_sl / n,
        "pct_time": n_time / n,
        "pct_nofill": n_nofill / n,
        "mean_ret_net": mean_ret,
        "std_ret_net": std_ret,
        "sum_uniqueness": sum_uniq,
    }


def record_experiment(
    labels: pl.DataFrame,
    config: LabelConfig,
    *,
    symbol: str,
    period_start: str,
    period_end: str,
    sprint: int = 6,
    stage: str = "labels_build",
    notes: str = "",
    path: Path | None = None,
) -> Path:
    """Acrescenta uma linha ao log de experimentos (§11.6) — config
    completa + hash + timestamp + métricas de distribuição de `labels`.
    Nunca edita nem remove linhas existentes."""
    log_path = path if path is not None else LOG_PATH
    existing = load_experiment_log(log_path)
    stats = summarize_labels(labels)

    row = {
        "experiment_id": _next_experiment_id(existing),
        "logged_at_utc": datetime.now(UTC),
        "sprint": sprint,
        "stage": stage,
        "symbol": symbol,
        "period_start": period_start,
        "period_end": period_end,
        "config_hash": config.config_hash,
        "tp_atr_mult": config.tp_atr_mult,
        "sl_atr_mult": config.sl_atr_mult,
        "time_stop_bars": None,  # AG-031/B1 -- LabelConfig não tem mais este campo
        "time_stop_ms": config.time_stop_ms,
        "fill_timeout_bars": None,  # AG-042 -- LabelConfig não tem mais este campo
        "fill_timeout_ms": config.fill_timeout_ms,
        "atr_window": None,  # AG-031/B1 -- LabelConfig não tem mais este campo
        "atr_window_ms": config.atr_window_ms,
        "maker_fee": config.maker_fee,
        "taker_fee": config.taker_fee,
        "tf": config.tf if config.resolution_id is None else None,
        "resolution_id": config.resolution_id,
        "horizon_bars": config.horizon_bars,  # AG-116 -- None sob tf, int sob resolution_id
        "notes": notes,
        **stats,
    }
    new_row = pl.DataFrame([row], schema=_SCHEMA)
    # AG-031/B1 -- "diagonal" (não "vertical") porque o arquivo real em
    # disco (label_engine_runs.parquet, existe desde 2026-08-09) foi escrito
    # sob o _SCHEMA antigo, sem a coluna time_stop_ms -- alinha por NOME de
    # coluna e preenche null onde falta, em vez de exigir schema idêntico.
    # Mesmo padrão "aditivo, nunca migração destrutiva" de constants.yaml/
    # architecture_gaps_log.yaml.
    combined = (
        pl.concat([existing, new_row], how="diagonal") if not existing.is_empty() else new_row
    )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = log_path.with_name(log_path.name + ".tmp")
    buffer = io.BytesIO()
    combined.write_parquet(buffer)
    with tmp_path.open("wb") as fh:
        fh.write(buffer.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, log_path)

    logger.info(
        "labels.experiment_recorded",
        experiment_id=row["experiment_id"],
        config_hash=config.config_hash,
        n_labels=stats["n_labels"],
        path=str(log_path),
    )
    return log_path
