"""ADR-007 Item 3 — calibração real do `AG-220` (poder estatístico do gate
de permanência) sob o vetor de 36 features (`T1_FEATURE_IDS`, `AG-372`) e o
GATE DUPLO atual (Sharpe relativo + edge bruto absoluto, `AG-383`-addendum)
— nunca calibrado antes sob nenhum dos dois. A calibração anterior (Fase 0b
do `ADR-002`, `src.validation.noise_floor_diagnostics`) rodou sob um vetor
de 7-62 features, hiperparâmetro DEFAULT (`LGBMHyperparams.from_constants()`,
não o vencedor confirmado do combo) e as políticas BARE DEFAULT de
`alpha.run_all_folds` (regime legado pré-`AG-272`, não o de produção) —
reusar aquelas funções diretamente calibraria o instrumento errado. Este
módulo é novo, não uma extensão daquele, por isso.

**Nulo testado**: `label`+`ret_net` permutados JUNTOS (mesmo índice de
permutação por linha, dentro do treino, por lado — `alpha.
_permute_label_and_ret_net` via `null_permutation_seed`), Camada1 E Camada0
sob a MESMA permutação por repetição — o nulo é "as duas camadas são
equivalentes sob hiperparâmetro fixo", não "uma é lixo, a outra é real".

**Hiperparâmetro FIXO por camada** — o vencedor JÁ CONFIRMADO do combo
(`experiments/alpha_optuna_confirmation_*_20260830T143204Z.json`, gate
duplo, `AG-383`-addendum), passado explícito pelo caller, nunca
`from_constants()`. Calibrar sob o default mediria o poder de um gate que
ninguém está de fato aplicando.

**Políticas de produção passadas explícitas** (`tau_policy`/`calib_split_
mode`/`class_balance_basis`/`calib_weight_basis`/`enforce_r2`), MESMO
conjunto de `hyperparams_optuna.py::confirm_top_k_multi_seed` — nunca os
bare defaults de `run_all_folds` (regime legado). `monotone_screen_
override` NUNCA passado aqui: sob permutação, o IC de cada feature contra
`ret_net` muda a cada repetição (a permutação acontece ANTES da triagem de
monotonicidade dentro de `fit_side_model`) — cachear a triagem do dado NÃO
permutado contaminaria o nulo com informação real."""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import structlog

from src.models import alpha, backtest_lite
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1
from src.validation.noise_floor_diagnostics import _build_mf_and_splits

logger = structlog.get_logger(__name__)

_BPS_PER_UNIT = 10_000


def run_dual_gate_permutation_null(
    symbol: str,
    resolution_id: str,
    *,
    camada1_hyper: alpha.LGBMHyperparams,
    camada0_hyper: alpha.LGBMHyperparams,
    n_repeats: int | None = None,
    device_type: str = "cpu",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    """Distribuição empírica do GATE DUPLO (`permanence_pass`/`edge_gate_
    pass`/`dual_gate_pass`) sob nulo verdadeiro (sem sinal real), pro
    hiperparâmetro FIXO já confirmado deste combo. Não decide o limiar
    sozinho — produz o material bruto (todas as `n_repeats` repetições)
    pro `Item 5` do ADR-007 usar."""
    n_repeats_resolved = (
        n_repeats
        if n_repeats is not None
        else int(load_constant("alpha_ag220_calibration_n_repeats"))
    )
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id)
    model_seed = int(load_constant("alpha_random_seed"))
    permanence_min_paths = int(load_constant("alpha_layer1_permanence_min_paths"))
    edge_min_bps = float(load_constant("alpha_layer1_permanence_min_edge_bps"))
    edge_min_trades = int(load_constant("alpha_layer1_permanence_min_trades"))

    permanence_pass_list: list[bool] = []
    edge_gate_pass_list: list[bool] = []
    dual_gate_pass_list: list[bool] = []
    n_better_list: list[int] = []
    per_repeat: list[dict[str, Any]] = []

    for i in range(n_repeats_resolved):
        perm_seed = alpha._derived_seed(model_seed, 999_983, i)  # noqa: magic-number -- espaço de seed de permutação separado do de modelo (mesma convenção de noise_floor_diagnostics.py)
        t0 = time.time()
        common_kwargs: dict[str, Any] = {
            "symbol": symbol,
            "resolution_id": resolution_id,
            "seed": model_seed,
            "feature_ids": None,
            "device_type": device_type,
            "tau_policy": alpha.TAU_POLICY_LEGACY_PER_SIDE,
            "calib_split_mode": alpha.CALIB_SPLIT_TEMPORAL_PURGED,
            "class_balance_basis": alpha.CLASS_BALANCE_WEIGHT,
            "calib_weight_basis": alpha.CALIB_WEIGHT_UNIQUENESS,
            "enforce_r2": True,
            "null_permutation_seed": perm_seed,
        }
        c1_folds = alpha.run_all_folds(
            mf.data,
            splits,
            variant=alpha.VARIANT_CAMADA1,
            model_id=MODEL_ID_CAMADA1,
            hyper=camada1_hyper,
            **common_kwargs,
        )
        c0_folds = alpha.run_all_folds(
            mf.data,
            splits,
            variant=alpha.VARIANT_CAMADA0,
            model_id=MODEL_ID_CAMADA0,
            hyper=camada0_hyper,
            **common_kwargs,
        )
        elapsed_s = time.time() - t0

        c1_by_path = backtest_lite.backtest_by_path(c1_folds, mf.data)
        c0_by_path = backtest_lite.backtest_by_path(c0_folds, mf.data)

        # MESMA contagem estrita (`>`, não `>=`) de confirm_combo_paired
        # (hyperparams_optuna.py) -- permanence_count (backtest_lite.py)
        # usa `>=` (empate conta como Camada1 melhor, AG-214) -- critério
        # diferente do que o gate duplo real aplica; usar o outro aqui
        # calibraria um gate que ninguém de fato aplica.
        common_paths = set(c1_by_path) & set(c0_by_path)
        n_better = sum(
            1 for p in common_paths if c1_by_path[p].sharpe_naive > c0_by_path[p].sharpe_naive
        )
        permanence_pass = n_better >= permanence_min_paths

        c1_edges = [
            r.mean_trade_ret * _BPS_PER_UNIT
            for r in c1_by_path.values()
            if math.isfinite(r.mean_trade_ret)
        ]
        c1_edge_bps = sum(c1_edges) / len(c1_edges) if c1_edges else float("nan")
        c1_trades = sum(r.n_filled_trades for r in c1_by_path.values())
        edge_gate_pass = (
            math.isfinite(c1_edge_bps)
            and c1_edge_bps > edge_min_bps
            and c1_trades >= edge_min_trades
        )
        dual_gate_pass = permanence_pass and edge_gate_pass

        n_better_list.append(n_better)
        permanence_pass_list.append(permanence_pass)
        edge_gate_pass_list.append(edge_gate_pass)
        dual_gate_pass_list.append(dual_gate_pass)
        per_repeat.append(
            {
                "repeat": i,
                "perm_seed": perm_seed,
                "n_better": n_better,
                "permanence_pass": permanence_pass,
                "camada1_edge_bps": c1_edge_bps,
                "camada1_trades": c1_trades,
                "edge_gate_pass": edge_gate_pass,
                "dual_gate_pass": dual_gate_pass,
                "elapsed_seconds": elapsed_s,
            }
        )
        logger.info(
            "validation.ag220_dual_gate_calibration.repeat_done",
            symbol=symbol,
            resolution_id=resolution_id,
            repeat=i,
            n_better=n_better,
            permanence_pass=permanence_pass,
            camada1_edge_bps=c1_edge_bps,
            edge_gate_pass=edge_gate_pass,
            dual_gate_pass=dual_gate_pass,
            elapsed_seconds=elapsed_s,
        )

    n_better_arr = np.asarray(n_better_list, dtype=np.int64)
    n_better_distribution = {
        str(v): int(np.sum(n_better_arr == v)) for v in sorted(set(n_better_list))
    }
    result = {
        "experiment": "adr007_item3_dual_gate_permutation_null",
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_repeats": n_repeats_resolved,
        "permanence_min_paths": permanence_min_paths,
        "edge_min_bps": edge_min_bps,
        "edge_min_trades": edge_min_trades,
        "n_better_distribution": n_better_distribution,
        # taxa de falso-positivo empirica: fracao das repeticoes SOB NULO
        # (sem sinal real) que teriam passado cada gate -- e o numero que
        # o Item 5 do ADR-007 precisa pra decidir o piso de confianca.
        "false_positive_rate_permanence": float(np.mean(permanence_pass_list)),
        "false_positive_rate_edge_gate": float(np.mean(edge_gate_pass_list)),
        "false_positive_rate_dual_gate": float(np.mean(dual_gate_pass_list)),
        "per_repeat": per_repeat,
    }
    logger.info(
        "validation.ag220_dual_gate_calibration.combo_done",
        symbol=symbol,
        resolution_id=resolution_id,
        n_repeats=n_repeats_resolved,
        false_positive_rate_permanence=result["false_positive_rate_permanence"],
        false_positive_rate_edge_gate=result["false_positive_rate_edge_gate"],
        false_positive_rate_dual_gate=result["false_positive_rate_dual_gate"],
    )
    return result


def _load_confirmed_winner_hyper(
    symbol: str, resolution_id: str, *, run_stamp: str
) -> tuple[alpha.LGBMHyperparams, alpha.LGBMHyperparams]:
    """Lê `(camada1_hyper, camada0_hyper)` JÁ CONFIRMADOS do JSON real
    gravado por `hyperparams_optuna.py --confirm` (gate duplo,
    `AG-383`-addendum) — nunca `LGBMHyperparams.from_constants()`
    (calibraria o hiperparâmetro default, não o que está sendo avaliado
    de fato pra promoção)."""
    import dataclasses
    import json

    path = (
        EXPERIMENTS_DIR
        / f"alpha_optuna_confirmation_{symbol}_{resolution_id}_{run_stamp}.json"
    )
    if not path.exists():
        raise FileNotFoundError(
            f"_load_confirmed_winner_hyper: {path} não existe -- rode "
            "`hyperparams_optuna.py --confirm` pra este combo primeiro"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    base_hyper = alpha.LGBMHyperparams.from_constants()
    camada1_hyper = dataclasses.replace(base_hyper, **data["camada1"]["winner"]["hyper"])
    camada0_hyper = dataclasses.replace(base_hyper, **data["camada0"]["winner"]["hyper"])
    return camada1_hyper, camada0_hyper


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "ADR-007 Item 3 -- calibração real do AG-220 (falso-positivo do "
            "gate duplo) sob o hiperparâmetro JÁ CONFIRMADO do combo."
        )
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--resolution-id", required=True)
    parser.add_argument(
        "--confirmation-run-stamp",
        default="20260830T143204Z",
        help="run_stamp do JSON de confirmação real (AG-383-addendum, gate duplo) a reusar.",
    )
    parser.add_argument("--n-repeats", type=int, default=None)
    parser.add_argument("--device-type", default="cpu")
    parser.add_argument("--vol-estimator-id", default=None)
    args = parser.parse_args()

    camada1_hyper, camada0_hyper = _load_confirmed_winner_hyper(
        args.symbol, args.resolution_id, run_stamp=args.confirmation_run_stamp
    )
    result = run_dual_gate_permutation_null(
        args.symbol,
        args.resolution_id,
        camada1_hyper=camada1_hyper,
        camada0_hyper=camada0_hyper,
        n_repeats=args.n_repeats,
        device_type=args.device_type,
        vol_estimator_id=args.vol_estimator_id,
    )
    write_report_atomic(result, symbol=args.symbol, resolution_id=args.resolution_id)
    return 0


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`, mesmo padrão de
    `src.validation.noise_floor_diagnostics.write_report_atomic`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"ag220_dual_gate_calibration_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.ag220_dual_gate_calibration.report_written", path=str(out_path))
    return out_path


if __name__ == "__main__":
    import sys

    sys.exit(_run_cli())
