"""AG-371 Passo 3 (item 1 da ordem do Manager, 2026-08-29) — infraestrutura
reusável de 1 trial de busca de hiperparâmetro, fatorada uma vez.

Até aqui, 6+ scripts da campanha ADR-002/ADR-003 (`src/validation/
t2_t1_*.py`) duplicavam a mesma sequência (`_build_mf_and_splits` ->
`alpha.run_all_folds` -> reduzir pra Sharpe), cada um com seu próprio loop
de estágio, sem contrato público nem teste de unidade dedicado a essa
composição (mapeado ao desenhar este item, ver `AG-371-ADDENDUM-12`/`-17`).

**Gap real que isto fecha, não hipotético.** NENHUM trial de NENHUM
estágio da ADR-003 persistiu Sharpe por path completo — só o agregado
sobrevive em disco, e nos Estágios 2/3 nem isso (`per_seed` desses
estágios grava só `pooled_sharpe`). Sem Sharpe/retorno por path de CADA
candidato testado, `src.validation.pbo_cscv.compute_pbo` (PBO via CSCV,
item (d) de `AG-371-ADDENDUM-12`) não tem matriz T×N pra rodar — o teste
de overfitting de seleção fica estruturalmente impossível de aplicar
depois de uma campanha já ter rodado. `TrialResult` grava os 5 valores de
Sharpe por path (e `n_signals`/`n_filled`/`fill_rate`/`trades_per_year`
por path, do próprio `backtest_lite.PathBacktestResult`) de CADA trial.

**Custo real medido nesta sessão** (não o da campanha ADR-003 sob 62
features, que não é a referência certa pra uma campanha sob 36): 1 trial
completo (`run_all_folds`, 15 folds/5 paths do CPCV, Camada1, BTCUSDT/R1 —
a maior das 15 células por linhas) = 32,6s. Setup (`_build_mf_and_splits`,
1x por célula, reusável entre trials da mesma célula) = ~28s."""

from __future__ import annotations

import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import orjson

from src.models import alpha, backtest_lite
from src.models import dataset as ds
from src.validation import cpcv
from src.validation.noise_floor_diagnostics import _build_mf_and_splits

build_mf_and_splits = _build_mf_and_splits  # reexport público -- ver docstring do módulo

_HYPER_FIELDS: tuple[str, ...] = (
    "max_depth",
    "num_leaves",
    "min_child_samples",
    "learning_rate",
    "subsample",
    "feature_fraction",
    "lambda_l2",
    "n_estimators",
    "min_sum_hessian_in_leaf",
)


@dataclass(frozen=True, slots=True)
class TrialResult:
    """1 linha = 1 trial = 1 config de hiperparâmetro (só os 9 campos que
    a campanha varia, `_HYPER_FIELDS` — mesmo subconjunto de `config/
    alpha_hyperparams_by_combo.yaml`) treinada sob os 5 paths do CPCV,
    pra 1 `(symbol, resolution_id, variant, seed)`. Campos `*_by_path`
    (não só agregado) são o que fecha o gap de PBO — ver docstring do
    módulo. `trial_id` é escolha do chamador (ex. `f"{stage}_{n}"`), não
    inventado aqui — mantém `TrialResult` cego a em qual estágio/campanha
    está inserido."""

    symbol: str
    resolution_id: str
    variant: str
    seed: int
    trial_id: str
    hyper: dict[str, float]
    pooled_sharpe: float
    sharpe_by_path: dict[str, float]
    n_signals_by_path: dict[str, int]
    n_filled_by_path: dict[str, int]
    fill_rate_by_path: dict[str, float]
    trades_per_year_by_path: dict[str, float]
    n_paths: int
    elapsed_seconds: float


def run_one_trial(
    mf: ds.ModelingFrame,
    splits: tuple[cpcv.CPCVSplit, ...],
    *,
    symbol: str,
    resolution_id: str,
    variant: str,
    hyper: alpha.LGBMHyperparams,
    feature_ids: tuple[str, ...],
    seed: int,
    trial_id: str,
    device_type: str = "cpu",
    model_id: str = "hyperparam_search_trial",
    calib_split_mode: str = alpha.CALIB_SPLIT_TEMPORAL_PURGED,
) -> TrialResult:
    """1 trial. `mf`/`splits` vêm de UMA chamada de `build_mf_and_splits`
    (reusada pelo chamador em loop pra não pagar o setup ~28s de novo a
    cada trial da MESMA célula — só o treino em si, ~10-33s medido real
    nesta sessão dependendo do tamanho da célula, se repete). `variant` =
    `alpha.VARIANT_CAMADA1`/`VARIANT_CAMADA0` — `AG-371-ADDENDUM-12`(b)
    exige campanhas independentes por camada; este runner é cego a qual
    camada está treinando, quem orquestra decide.

    `calib_split_mode` default `temporal_purged` — MESMO default de
    `run_layer1_sprint` (`AG-272`); `LGBMHyperparams` com `early_stopping_
    mode='three_way'` (default de `from_constants()`) exige esse modo,
    não o legado (achado real, `AG-371` MDA diagnostic script, mesma
    sessão)."""
    t0 = time.time()
    folds = alpha.run_all_folds(
        mf.data,
        splits,
        variant=variant,
        model_id=model_id,
        symbol=symbol,
        resolution_id=resolution_id,
        hyper=hyper,
        seed=seed,
        feature_ids=feature_ids,
        device_type=device_type,
        calib_split_mode=calib_split_mode,
    )
    by_path = backtest_lite.backtest_by_path(folds, mf.data)
    elapsed = time.time() - t0

    sharpe_by_path = {str(pid): r.sharpe_naive for pid, r in by_path.items()}
    finite_sharpes = [s for s in sharpe_by_path.values() if math.isfinite(s)]
    pooled = sum(finite_sharpes) / len(finite_sharpes) if finite_sharpes else float("nan")

    return TrialResult(
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        seed=seed,
        trial_id=trial_id,
        hyper={f: getattr(hyper, f) for f in _HYPER_FIELDS},
        pooled_sharpe=pooled,
        sharpe_by_path=sharpe_by_path,
        n_signals_by_path={str(pid): r.n_signals for pid, r in by_path.items()},
        n_filled_by_path={str(pid): r.n_filled_trades for pid, r in by_path.items()},
        fill_rate_by_path={str(pid): r.fill_rate for pid, r in by_path.items()},
        trades_per_year_by_path={str(pid): r.trades_per_year for pid, r in by_path.items()},
        n_paths=len(by_path),
        elapsed_seconds=elapsed,
    )


def append_trial_result_jsonl(result: TrialResult, path: Path) -> None:
    """Append incremental, 1 linha JSON por trial — NÃO espera a campanha
    inteira terminar pra persistir algo. Precedente real desta sessão:
    `AG-365`, retreino canônico de 15 células crashou no meio; uma
    campanha de horas de trials não pode perder tudo por um crash tardio.

    `open(..., "ab")` + `flush` + `fsync` — durável por LINHA. Não é o
    padrão `.tmp -> fsync -> rename` de `write_report_atomic` (B29) de
    propósito: aquele é pra um arquivo SUBSTITUÍDO por inteiro a cada
    escrita; isto é um log que só CRESCE — reescrever o arquivo inteiro a
    cada trial seria o(n²) desperdiçado sem necessidade nenhuma."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = orjson.dumps(asdict(result)) + b"\n"
    with path.open("ab") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_trial_results_jsonl(path: Path) -> list[dict[str, Any]]:
    """Lê de volta um log de trials — pra retomar uma campanha
    interrompida (não reprocessar trials já feitos) ou pra alimentar
    DSR/PBO depois de uma campanha terminar. `path` inexistente -> lista
    vazia (campanha ainda não começou), não erro."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("rb") as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if stripped:
                out.append(orjson.loads(stripped))
    return out
