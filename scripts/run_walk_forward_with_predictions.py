"""Walk-forward canônico (hiperparâmetro de PRODUÇÃO, inalterado) com
`keep_predictions=True` — fecha os itens 16 (condicionamento por regime
barra-a-barra) e P2 (`edge_bps`/`sharpe` por trade individual) do
roadmap "Caso 0/20", além de expor `train_val_test_gap` (P3, já cabeado
em `walk_forward.py` sem custo adicional, commit `8b96c6d`).

**Nunca toca produção nem o artefato canônico**: mesmos hiperparâmetros/
seed/tau_policy que geraram `experiments/alpha_walk_forward_*.json` —
só ADICIONA `keep_predictions=True`. Escreve em arquivos SEPARADOS:

- `experiments/alpha_walk_forward_{symbol}_{res}_with_predictions.json`
  (mesmo schema do canônico, MENOS o campo `predictions` por fold —
  `pl.DataFrame` não é serializável em JSON, salvo à parte)
- `experiments/alpha_walk_forward_predictions_{symbol}_{res}_{variant}.parquet`
  (as previsões OOS reais por barra, todos os folds concatenados, com
  `fold_id`/`symbol`/`resolution_id`/`variant` como colunas — mesmo
  padrão de escrita atômica tmp→fsync→rename de `hyperparams_optuna.
  export_trial_trajectory`)
- `experiments/alpha_walk_forward_feature_deciles_{symbol}_{res}_{variant}.parquet`
  (AG-424 -- census de decil das 30 features T1 ativas contra `ret_net`
  realizado, `src.analysis.attribution.feature_deciles_by_side`, mesma
  matemática/guard estatístico já validado em produção pra
  `confidence_deciles_by_side`. Artefato canônico de produção, não
  experimento solto -- regenerado toda vez que este script roda, mesmo
  ciclo de vida dos predictions acima).

Autorização explícita do Manager (2026-09-01): "Aprovo Retreino junto"
(itens 16/P2/P3), custo real de `n_lifetime` (retreino completo dos 5
candidatos × 2 camadas).

Uso:

    uv run python -m scripts.run_walk_forward_with_predictions
"""

from __future__ import annotations

import dataclasses
import io
import os
import sys
from pathlib import Path
from typing import Any

import polars as pl
import structlog

from src.analysis import attribution
from src.features.build import T1_FEATURE_IDS
from src.models import alpha, dataset, hyperparams_by_combo, pipeline
from src.models import walk_forward as wf
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_VARIANTS: tuple[str, ...] = (alpha.VARIANT_CAMADA1, alpha.VARIANT_CAMADA0)


def _write_parquet_atomic(df: pl.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    with tmp_path.open("wb") as fh:
        fh.write(buffer.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)


def main() -> int:
    configure_logging(json_output=False)
    seed = int(load_constant("alpha_random_seed"))
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))

    for symbol, resolution_id in _CANDIDATOS:
        mf = dataset.build_modeling_frame(
            symbol=symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
        )
        payload_json: dict[str, Any] = {}
        for variant in _VARIANTS:
            hyper = hyperparams_by_combo.load_production_override(symbol, resolution_id, variant)
            if hyper is None:
                raise ValueError(
                    f"run_walk_forward_with_predictions: {symbol}/{resolution_id}/{variant} "
                    "sem entrada em alpha_production_hyperparam_override -- esperado presente "
                    "pros 5 candidatos promovidos, ver ADR-008 Secao 1.4"
                )
            logger.info(
                "scripts.run_walk_forward_with_predictions.iniciando",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
            )
            result = wf.run_walk_forward_for_combo(
                mf.data,
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                hyper=hyper,
                seed=seed,
                device_type="cpu",
                tau_policy=alpha.TAU_POLICY_LEGACY_PER_SIDE,
                keep_predictions=True,
            )

            pred_frames = [
                fm.predictions.with_columns(
                    pl.lit(fm.fold_id).alias("fold_id"),
                    pl.lit(symbol).alias("symbol"),
                    pl.lit(resolution_id).alias("resolution_id"),
                    pl.lit(variant).alias("variant"),
                )
                for fm in result.fold_results
                if fm.predictions is not None and fm.predictions.height > 0
            ]
            if pred_frames:
                all_predictions = pl.concat(pred_frames, how="vertical_relaxed")
                pred_path = (
                    EXPERIMENTS_DIR
                    / f"alpha_walk_forward_predictions_{symbol}_{resolution_id}_{variant}.parquet"
                )
                _write_parquet_atomic(all_predictions, pred_path)
                logger.info(
                    "scripts.run_walk_forward_with_predictions.predictions_escrito",
                    path=str(pred_path),
                    n_rows=all_predictions.height,
                )

                # AG-424 -- census de decil das 30 features T1 contra o
                # ret_net realizado, mesma matemática/guard de
                # confidence_deciles_by_side. mf.data já tem t0 + todas as
                # T1_FEATURE_IDS + ret_net/barrier_hit -- serve tanto de
                # `labels` quanto de `feature_values` na assinatura.
                feature_deciles = attribution.feature_deciles_by_side(
                    all_predictions, mf.data, mf.data, T1_FEATURE_IDS
                )
                deciles_path = (
                    EXPERIMENTS_DIR
                    / f"alpha_walk_forward_feature_deciles_{symbol}_{resolution_id}_"
                    f"{variant}.parquet"
                )
                _write_parquet_atomic(feature_deciles, deciles_path)
                logger.info(
                    "scripts.run_walk_forward_with_predictions.feature_deciles_escrito",
                    path=str(deciles_path),
                    n_rows=feature_deciles.height,
                )

            result_dict = dataclasses.asdict(result)
            for fm_dict in result_dict["fold_results"]:
                fm_dict["predictions"] = None
            payload_json[variant] = result_dict

            logger.info(
                "scripts.run_walk_forward_with_predictions.concluido_combo",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                n_folds_usados=result.n_folds_usados,
            )

        payload_json["run_metadata"] = {
            "seed": seed,
            "tau_policy": alpha.TAU_POLICY_LEGACY_PER_SIDE,
            "device_type": "cpu",
            "symbol": symbol,
            "resolution_id": resolution_id,
            "producer_entrypoint": "scripts.run_walk_forward_with_predictions",
            "keep_predictions": True,
        }
        out_path = (
            EXPERIMENTS_DIR / f"alpha_walk_forward_{symbol}_{resolution_id}_with_predictions.json"
        )
        pipeline.write_report_atomic(payload_json, dest_path=out_path)
        logger.info(
            "scripts.run_walk_forward_with_predictions.artefato_escrito", path=str(out_path)
        )

    logger.info("scripts.run_walk_forward_with_predictions.tudo_concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
