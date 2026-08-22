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

import contextlib
import io
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import structlog

from ._paths import LABEL_ENGINE_RUNS_DIR
from .triple_barrier import LabelBuildStats, LabelConfig

logger = structlog.get_logger(__name__)

LOG_PATH: Path = LABEL_ENGINE_RUNS_DIR / "label_engine_runs.parquet"

# AG-145 (audit/architecture_gaps_log.yaml) -- record_experiment fazia
# read-modify-write do arquivo inteiro sem lock; sob ProcessPoolExecutor
# real (src.labels.backfill_multi_symbol), 2+ processos podiam ler o
# mesmo estado e a ultima escrita vencer, perdendo a linha do outro em
# silencio. Timeout/poll de engenharia (nao dominio quant, mesmo
# precedente de _DATE_BUFFER_DAYS em src/models/dataset.py:61) -- volume
# real deste log e ~dezenas de linhas/ano (nao escala de trial do
# Optuna), entao um lock simples e proporcional; o padrao
# um-arquivo-por-trial (V-06 do ADR-001, action item 5) fica pra quando
# um consumidor de volume real existir.
_LOCK_TIMEOUT_S = 30.0  # noqa: magic-number -- engenharia, não domínio quant
_LOCK_POLL_S = 0.05  # noqa: magic-number -- engenharia, não domínio quant
_LOCK_STALE_S = 60.0  # noqa: magic-number -- engenharia, não domínio quant

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
    # AG-128 (F2, achado `audit_engineering` 2026-08-19) -- os 3 contadores
    # de diagnóstico que `triple_barrier.build_labels`/`build_labels_with_
    # stats` sempre computou (warmup de ATR descartado, cauda incompleta de
    # mark_1m/funding, desempate TP=SL no mesmo candle de 1m -- item 5 da
    # docstring de triple_barrier.py) mas só emitia via `logger.info`,
    # nunca persistido. Vem de `LabelBuildStats` (`triple_barrier.py`),
    # agregado pelos dois lados (soma simples, ver `build_labels_both_
    # sides_with_stats`). Linhas antigas (antes desta coluna existir) ficam
    # null -- mesmo padrão aditivo, nunca migração destrutiva, de tf/
    # resolution_id/horizon_bars acima.
    "n_warmup_dropped": pl.Int64,
    "n_incomplete_tail": pl.Int64,
    "n_tie_break": pl.Int64,
    # AG-100 F1/F2 (achado `project_assurance`, 2026-08-22) -- quebra
    # granular de n_incomplete_tail (3 causas distintas antes conflacionadas
    # sob 1 coluna, ver docstring de LabelBuildStats em triple_barrier.py)
    # + n_empty_mark_window (janela mark_1m[t_entry:horizon_end_ms] vazia --
    # trade não-computável sob rajada de dollar-bar, achado que causou o
    # crash real do backfill AG-100 R2/R3 em SOLUSDT/XRPUSDT). Linhas
    # antigas (antes desta coluna existir) ficam null -- mesmo padrão
    # aditivo, nunca migração destrutiva, de tf/resolution_id/horizon_bars.
    "n_incomplete_tail_fill": pl.Int64,
    "n_incomplete_tail_decision_bars": pl.Int64,
    "n_incomplete_tail_barrier": pl.Int64,
    "n_empty_mark_window": pl.Int64,
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


@contextlib.contextmanager
def _file_lock(lock_path: Path) -> Iterator[None]:
    """Mutex entre processos via criação exclusiva de arquivo
    (`O_CREAT | O_EXCL`) — portátil (Windows/POSIX), sem dependência
    nova. `open` com `O_EXCL` falha com `FileExistsError` se o lock já
    existir; poll com backoff fixo até `_LOCK_TIMEOUT_S`. Lock mais
    velho que `_LOCK_STALE_S` é removido à força antes de tentar de
    novo — um processo que morreu segurando o lock (crash, `SIGKILL`)
    não deveria travar o log pra sempre."""
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                age_s = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue  # lock sumiu entre o open e o stat -- tenta de novo
            if age_s > _LOCK_STALE_S:
                logger.warning(
                    "labels.experiment_log.lock_stale_removed",
                    lock_path=str(lock_path),
                    age_s=age_s,
                )
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"labels.experiment_log: lock {lock_path} não liberado em "
                    f"{_LOCK_TIMEOUT_S}s -- outro processo pode estar preso"
                ) from None
            time.sleep(_LOCK_POLL_S)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


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
    build_stats: LabelBuildStats | None = None,
    path: Path | None = None,
) -> Path:
    """Acrescenta uma linha ao log de experimentos (§11.6) — config
    completa + hash + timestamp + métricas de distribuição de `labels`.
    Nunca edita nem remove linhas existentes.

    `build_stats` (AG-128, F2) — os 3 contadores de diagnóstico de
    `triple_barrier.LabelBuildStats` (n_warmup_dropped/n_incomplete_tail/
    n_tie_break), quando o caller tem essa informação disponível (ex.
    `build_labels_for_symbol_with_stats`). `None` (default) grava `null`
    nas 3 colunas -- preserva todo caller existente que só tem `labels`/
    `config` em mãos (ex. testes que constroem `labels` sinteticamente,
    sem passar por `build_labels_with_stats`)."""
    log_path = path if path is not None else LOG_PATH
    lock_path = log_path.with_name(log_path.name + ".lock")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(lock_path):
        return _record_experiment_locked(
            labels,
            config,
            symbol=symbol,
            period_start=period_start,
            period_end=period_end,
            sprint=sprint,
            stage=stage,
            notes=notes,
            build_stats=build_stats,
            log_path=log_path,
        )


def _record_experiment_locked(
    labels: pl.DataFrame,
    config: LabelConfig,
    *,
    symbol: str,
    period_start: str,
    period_end: str,
    sprint: int,
    stage: str,
    notes: str,
    build_stats: LabelBuildStats | None,
    log_path: Path,
) -> Path:
    """Corpo real de `record_experiment` — só chamado com `_file_lock`
    de `log_path` já adquirido pelo caller (AG-145: read-modify-write
    do arquivo inteiro precisa ser atômico entre PROCESSOS, não só
    entre threads do mesmo processo)."""
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
        "n_warmup_dropped": build_stats.n_warmup_dropped if build_stats is not None else None,
        "n_incomplete_tail": build_stats.n_incomplete_tail if build_stats is not None else None,
        "n_tie_break": build_stats.n_tie_break if build_stats is not None else None,
        "n_incomplete_tail_fill": (
            build_stats.n_incomplete_tail_fill if build_stats is not None else None
        ),
        "n_incomplete_tail_decision_bars": (
            build_stats.n_incomplete_tail_decision_bars if build_stats is not None else None
        ),
        "n_incomplete_tail_barrier": (
            build_stats.n_incomplete_tail_barrier if build_stats is not None else None
        ),
        "n_empty_mark_window": (
            build_stats.n_empty_mark_window if build_stats is not None else None
        ),
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
