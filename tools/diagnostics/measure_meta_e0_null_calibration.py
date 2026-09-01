"""Medição real de `validate_null_calibration` (P0, Gate E0 §2.6) — 5
símbolos × {R2, R3}, dado real de produção. Decisão do Manager
(2026-08-31): 15m/R1 não são grade de treino do Alpha hoje — pular
E0-piloto (bloqueado por B15 em labels legados) e medir direto contra
R2/R3, as grades vigentes.

**Universo desta medição**: `t0`/`t1`/`barrier_hit`/`ret_net`/`side`/
`regime` de `build_modeling_frame` (quantile classifier — não há
artefato HMM persistido ainda, `RegimeHmmArtifactMissingError`
esperado; testar a MÁQUINA estatística não depende de qual candidato de
regime vai pra produção). NÃO usa `predictions.parquet` real — não
existe artefato Alpha em R1/R2/R3 ainda, só os legados `alpha_c0/c1`
(grade 15m). Path/`is_oof`/`side_hat` do Alpha real não entram aqui de
propósito: cada "path" do CPCV, reconstruído sem um modelo real por
split, cobre 100% do dataset (união dos 6 grupos) — os 5 paths dariam a
MESMA população para este teste puramente estatístico, então o script
usa o dataset inteiro por (symbol, resolution), não replica os 5 paths.

**Proxy "sabidamente sem sinal"**: regime de OUTRO símbolo (mesma
resolução), alinhado por POSIÇÃO (trunca ao menor comprimento) — texto
literal do §2.6 ("ex.: o próprio regime de um símbolo diferente,
alinhado por posição"). Roda em anel (BTC↦ETH, ETH↦SOL, SOL↦BNB,
BNB↦XRP, XRP↦BTC) para cobrir os 5 símbolos com proxies distintos.

Orçamento: `n_trials=100`, `n_seeds_per_trial=100` por combo (10.000
chamadas de AUC/combo) — medido em ~0,04s/chamada sobre BTCUSDT/R2
(220k linhas, o maior combo), ~7min/combo, ~70min para os 10 combos.
Não é o orçamento de produção do Gate E0 real (`alpha_b1_n_seeds=1000`)
— é uma amostra de Monte Carlo suficiente pra um veredito de calibração
com IC razoável (erro padrão ~2,2pp em torno de 5% com n_trials=100),
documentado como tal, não escondido.

Saída: `experiments/meta_e0_null_calibration_2026-08-31.json`,
atômico (`.tmp` -> fsync -> rename)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import structlog

from src.analysis import meta_fp_inventory as fpi
from src.models import dataset as ds
from src.regime.classifier import REGIME_LABELS
from src.validation import cpcv

logger = structlog.get_logger(__name__)

_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
_RESOLUTIONS: tuple[str, ...] = ("R2", "R3")
_VOL_ESTIMATOR_ID = "parkinson_w20"
_N_TRIALS = 100
_N_SEEDS_PER_TRIAL = 100
_SEED = 20260831

_OUT_FILENAME = "meta_e0_null_calibration_2026-08-31.json"
_OUT_PATH = _REPO_ROOT / "experiments" / _OUT_FILENAME

_REGIME_MAP = {label: i for i, label in enumerate(REGIME_LABELS)}


def _population(symbol: str, resolution_id: str) -> dict[str, Any]:
    mf = ds.build_modeling_frame(
        symbol=symbol, resolution_id=resolution_id, vol_estimator_id=_VOL_ESTIMATOR_ID
    )
    labeled = fpi.classify_fp_binary(mf.data)
    # regime pode ser nulo numa fração minúscula de linhas (achado real,
    # 2026-08-31: build_modeling_frame mede e loga n_missing_regime > 0 --
    # nao e bug deste script, e realidade de dado ja instrumentada
    # upstream; sem este filtro, o mapeamento pra int abaixo produz o
    # sentinela de overflow int64 e derruba weighted_state_positive_rate).
    sub = labeled.filter(
        labeled["y_fp"].is_not_null() & labeled["regime"].is_not_null()
    ).sort("t0")

    t0_ms = sub["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    y = sub["y_fp"].to_numpy().astype(np.float64)
    state_ids = (
        sub["regime"].cast(str).replace(_REGIME_MAP).cast(int).to_numpy().astype(np.int64)
    )
    weight = fpi.uniqueness_per_side(sub["t0"], sub["t1"], sub["side"])

    result = cpcv.generate_splits(
        mf.data, config=cpcv.CPCVConfig.from_constants(grade_id=resolution_id), symbol=symbol
    )
    group_widths = np.diff(result.edges_ms)
    block_width_ms = int(np.median(group_widths))

    return {
        "t0_ms": t0_ms,
        "y": y,
        "state_ids": state_ids,
        "weight": weight,
        "block_width_ms": block_width_ms,
        "n_rows": int(t0_ms.shape[0]),
        "n_nofill_excluded": int(mf.data.height - sub.height),
    }


def main() -> int:
    populations: dict[tuple[str, str], dict[str, Any]] = {}
    t_start = time.time()
    for resolution_id in _RESOLUTIONS:
        for symbol in _SYMBOLS:
            t0 = time.time()
            populations[(symbol, resolution_id)] = _population(symbol, resolution_id)
            logger.info(
                "meta_e0_null_calibration.population_pronta",
                symbol=symbol,
                resolution_id=resolution_id,
                n_rows=populations[(symbol, resolution_id)]["n_rows"],
                elapsed_s=round(time.time() - t0, 1),
            )

    results: list[dict[str, object]] = []
    for resolution_id in _RESOLUTIONS:
        symbols = list(_SYMBOLS)
        for i, symbol in enumerate(symbols):
            proxy_symbol = symbols[(i + 1) % len(symbols)]
            pop = populations[(symbol, resolution_id)]
            proxy_pop = populations[(proxy_symbol, resolution_id)]

            n = min(pop["n_rows"], proxy_pop["n_rows"])
            proxy_state_ids = proxy_pop["state_ids"][:n]
            t0_ms = pop["t0_ms"][:n]
            y = pop["y"][:n]
            weight = pop["weight"][:n]

            rng = np.random.default_rng(_SEED + hash((symbol, resolution_id)) % 10_000)
            t0 = time.time()
            calib = fpi.validate_null_calibration(
                t0_ms,
                proxy_state_ids,
                y,
                weight,
                n_states=len(REGIME_LABELS),
                block_width_ms=pop["block_width_ms"],
                n_trials=_N_TRIALS,
                n_seeds_per_trial=_N_SEEDS_PER_TRIAL,
                rng=rng,
            )
            dt = time.time() - t0
            logger.info(
                "meta_e0_null_calibration.combo_concluido",
                symbol=symbol,
                resolution_id=resolution_id,
                proxy_symbol=proxy_symbol,
                pass_rate=round(calib.pass_rate, 4),
                ci_low=round(calib.ci_low, 4),
                ci_high=round(calib.ci_high, 4),
                well_calibrated=calib.well_calibrated,
                elapsed_s=round(dt, 1),
            )
            results.append(
                {
                    "symbol": symbol,
                    "resolution_id": resolution_id,
                    "proxy_symbol": proxy_symbol,
                    "n_rows": n,
                    "n_states": len(REGIME_LABELS),
                    "block_width_ms": pop["block_width_ms"],
                    "n_trials": calib.n_trials,
                    "n_seeds_per_trial": calib.n_seeds_per_trial,
                    "n_pass": calib.n_pass,
                    "pass_rate": calib.pass_rate,
                    "target": calib.target,
                    "confidence_level": calib.confidence_level,
                    "ci_low": calib.ci_low,
                    "ci_high": calib.ci_high,
                    "well_calibrated": calib.well_calibrated,
                    "elapsed_s": dt,
                }
            )

    n_well_calibrated = sum(1 for r in results if r["well_calibrated"])
    total_elapsed_s = time.time() - t_start
    payload: dict[str, Any] = {
        "_schema": "meta_e0_null_calibration/1.0.0",
        "_gerado_por": "tools/diagnostics/measure_meta_e0_null_calibration.py",
        "_proposito": (
            "P0 do Gate E0 (docs/meta_model_design_doc_2026-08-22.md Sec2.6) -- "
            "validacao obrigatoria do nulo (circular-shift-by-block), medida contra "
            "R2/R3 real dos 5 simbolos (15m/R1 fora de escopo, decisao do Manager "
            "2026-08-31 -- nao sao grade de treino do Alpha hoje)."
        ),
        "_vol_estimator_id": _VOL_ESTIMATOR_ID,
        "_n_trials": _N_TRIALS,
        "_n_seeds_per_trial": _N_SEEDS_PER_TRIAL,
        "_seed_base": _SEED,
        "n_combos": len(results),
        "n_well_calibrated": n_well_calibrated,
        "total_elapsed_s": total_elapsed_s,
        "combos": results,
    }

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _OUT_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, _OUT_PATH)

    logger.info(
        "meta_e0_null_calibration.concluido",
        n_combos=len(results),
        n_well_calibrated=n_well_calibrated,
        out_path=str(_OUT_PATH),
        total_elapsed_s=round(total_elapsed_s, 1),
    )
    return 0 if n_well_calibrated == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
