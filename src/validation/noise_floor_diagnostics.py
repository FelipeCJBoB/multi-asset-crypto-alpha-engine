"""Fase 0 — diagnóstico de ruído (`docs/t2_t1_ablation_veredito_duas_
analises_2026-08-24.md` §4), pré-requisito antes de qualquer sweep de
k/hiperparâmetro do Alpha. Ponto de entrada com IO — monta `mf`/`splits`
exatamente como `src.models.pipeline.run_layer1_sprint` (mesmo padrão de
produção, reusado aqui, não duplicado), delega o cálculo real pro núcleo
já testado em `src.models.alpha`.

**0a — repetição de seed**: `k=7` (T1 atual) e hiperparâmetro PROD
travados, só a `seed` varia entre repetições — mede σ do Sharpe pooled
(mesma definição de `alpha_sharpe_headline` em `pipeline.py`: média dos
Sharpe por path, não uma métrica nova) sob ruído de treino puro (LightGBM
+ sub-split de calibração), sem nenhuma mudança de configuração.

**0b — nulo por permutação de rótulo**: `label`+`ret_net` permutados
juntos (`alpha._permute_label_and_ret_net`, `null_permutation_seed`),
Camada1 E Camada0 recebendo a MESMA permutação por repetição (mesmo
`null_permutation_seed` nas duas chamadas de `run_all_folds`) — o nulo
testado é "as duas camadas são equivalentes", não "uma é lixo, a outra é
real". Produz a distribuição empírica de `n_better` sob ruído verdadeiro,
calibrando o limiar de `alpha_layer1_permanence_min_paths` sem assumir
Binomial (os 5 paths do CPCV compartilham dado de treino, não são
independentes).

Escreve `experiments/noise_floor_diagnostics_{symbol}_{resolution_id}.
json` (B29 — `.tmp` -> `fsync` -> `rename`). NÃO decide o limiar sozinho
— produz o material bruto (distribuição completa, não só um percentil)
pro `AG-NNN` que o Manager decide (`docs/t2_t1_ablation_veredito_duas_
analises_2026-08-24.md` §4, 3 razões pra não substituir `constants.yaml`
direto)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import structlog

from src.features import build as features_build
from src.models import alpha, backtest_lite
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1
from src.validation import cpcv

logger = structlog.get_logger(__name__)

FloatList = list[float]


def _mean_finite(values: FloatList) -> float:
    arr = np.asarray(values, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    return float(np.mean(finite)) if finite.size else float("nan")


def _build_mf_and_splits(
    symbol: str,
    resolution_id: str,
    vol_estimator_id: str | None,
    extra_feature_ids: tuple[str, ...] = (),
) -> tuple[ds.ModelingFrame, tuple[cpcv.CPCVSplit, ...]]:
    """Mesma sequência de `pipeline.run_layer1_sprint` (linhas 488-520) —
    reusada aqui, não reimplementada, pra qualquer correção futura do
    caminho de produção (ex. AG-032 componente 96) valer automaticamente
    pra este diagnóstico também.

    `extra_feature_ids` (2026-08-24, pré-requisito da Fase 1 — `src.
    analysis.t2_ranking_ortogonalidade`) — default `()` preserva bit-
    exato o uso da Fase 0 (só T1). Repassado pra `build_modeling_frame`
    quando o chamador precisa das candidatas T2 presentes em `mf.data`
    (ranking de estabilidade/ortogonalidade), sem duplicar esta função."""
    tf_effective = "15m"
    mf = ds.build_modeling_frame(
        symbol=symbol,
        tf=tf_effective,
        resolution_id=resolution_id,
        vol_estimator_id=vol_estimator_id,
        extra_feature_ids=extra_feature_ids,
    )
    max_feature_lookback_ms = features_build.compute_max_feature_lookback_ms(
        tf_effective, resolution_id=resolution_id
    )
    cpcv_config = cpcv.CPCVConfig.from_constants(
        tf=tf_effective,
        grade_id=resolution_id,
        max_feature_lookback_ms=max_feature_lookback_ms,
    )
    cpcv_result = cpcv.generate_splits(mf.data, config=cpcv_config, symbol=symbol)
    return mf, cpcv_result.splits


def _pooled_sharpe(
    fold_results: list[alpha.FoldResult], df_all: Any
) -> tuple[float, dict[str, float]]:
    """Achado real (2026-08-24, 1ª execução real desta Fase 0): `orjson`
    exige chave `str`, não `int` -- `path_id` (`backtest_by_path`'s
    dict key) é `int`. Bug descoberto DEPOIS de 60 execuções reais já
    terem terminado -- `write_report_atomic` falhou só na última etapa
    (serialização), o compute em si estava correto. Chaves convertidas
    pra `str` aqui, no núcleo, não em cada call site."""
    by_path = backtest_lite.backtest_by_path(fold_results, df_all)
    sharpes = {str(pid): r.sharpe_naive for pid, r in by_path.items()}
    return _mean_finite(list(sharpes.values())), sharpes


def run_seed_repetition(
    symbol: str,
    resolution_id: str,
    *,
    n_repeats: int = 10,
    device_type: str = "cuda",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    """0a — `k=7`/hiperparâmetro PROD travados, só `seed` varia."""
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id)
    hyper = alpha.LGBMHyperparams.from_constants()

    pooled_sharpes: FloatList = []
    per_repeat: list[dict[str, Any]] = []
    for i in range(n_repeats):
        seed = alpha._derived_seed(int(load_constant("alpha_random_seed")), i)
        t0 = time.time()
        folds = alpha.run_all_folds(
            mf.data,
            splits,
            variant=alpha.VARIANT_CAMADA1,
            model_id=MODEL_ID_CAMADA1,
            symbol=symbol,
            resolution_id=resolution_id,
            hyper=hyper,
            seed=seed,
            device_type=device_type,
        )
        elapsed_s = time.time() - t0
        pooled, by_path = _pooled_sharpe(folds, mf.data)
        pooled_sharpes.append(pooled)
        per_repeat.append(
            {"repeat": i, "seed": seed, "pooled_sharpe": pooled, "sharpe_by_path": by_path,
             "elapsed_seconds": elapsed_s}
        )
        logger.info(
            "validation.noise_floor.seed_repetition_done",
            repeat=i,
            pooled_sharpe=pooled,
            elapsed_seconds=elapsed_s,
        )

    # ddof=1 (desvio-padrão amostral) exige n>=2 -- com n_repeats=1 (modo
    # --probe-only) o denominador (n-1) é 0, o que o numpy resolveria como
    # RuntimeWarning + NaN silencioso em vez de comunicar a causa real (a
    # estatística não é definida com 1 amostra, não é um erro de cálculo).
    std = (
        float(np.std(np.asarray(pooled_sharpes, dtype=np.float64), ddof=1))
        if len(pooled_sharpes) >= 2
        else float("nan")
    )
    return {
        "experiment": "0a_seed_repetition",
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_repeats": n_repeats,
        "pooled_sharpe_mean": _mean_finite(pooled_sharpes),
        "pooled_sharpe_std": std,
        "per_repeat": per_repeat,
    }


def run_permutation_null(
    symbol: str,
    resolution_id: str,
    *,
    n_repeats: int = 50,
    device_type: str = "cuda",
    vol_estimator_id: str | None = None,
) -> dict[str, Any]:
    """0b — `label`+`ret_net` permutados juntos, Camada1 E Camada0 sob a
    MESMA permutação por repetição (mesmo `null_permutation_seed`)."""
    mf, splits = _build_mf_and_splits(symbol, resolution_id, vol_estimator_id)
    hyper = alpha.LGBMHyperparams.from_constants()
    model_seed = int(load_constant("alpha_random_seed"))

    n_better_list: list[int] = []
    per_repeat: list[dict[str, Any]] = []
    for i in range(n_repeats):
        perm_seed = alpha._derived_seed(model_seed, 999_983, i)  # noqa: magic-number -- separa o espaço de seed de permutação do de modelo, arbitrário
        t0 = time.time()
        c1_folds = alpha.run_all_folds(
            mf.data,
            splits,
            variant=alpha.VARIANT_CAMADA1,
            model_id=MODEL_ID_CAMADA1,
            symbol=symbol,
            resolution_id=resolution_id,
            hyper=hyper,
            seed=model_seed,
            device_type=device_type,
            null_permutation_seed=perm_seed,
        )
        c0_folds = alpha.run_all_folds(
            mf.data,
            splits,
            variant=alpha.VARIANT_CAMADA0,
            model_id=MODEL_ID_CAMADA0,
            symbol=symbol,
            resolution_id=resolution_id,
            hyper=hyper,
            seed=model_seed,
            device_type=device_type,
            null_permutation_seed=perm_seed,
        )
        elapsed_s = time.time() - t0
        c1_by_path = backtest_lite.backtest_by_path(c1_folds, mf.data)
        c0_by_path = backtest_lite.backtest_by_path(c0_folds, mf.data)
        n_better, n_total = backtest_lite.permanence_count(c1_by_path, c0_by_path)
        n_better_list.append(n_better)
        per_repeat.append(
            {
                "repeat": i,
                "perm_seed": perm_seed,
                "n_better": n_better,
                "n_total": n_total,
                "camada1_sharpe_by_path": {
                    str(pid): r.sharpe_naive for pid, r in c1_by_path.items()
                },
                "camada0_sharpe_by_path": {
                    str(pid): r.sharpe_naive for pid, r in c0_by_path.items()
                },
                "elapsed_seconds": elapsed_s,
            }
        )
        logger.info(
            "validation.noise_floor.permutation_null_done",
            repeat=i,
            n_better=n_better,
            elapsed_seconds=elapsed_s,
        )

    n_better_arr = np.asarray(n_better_list, dtype=np.int64)
    distribution = {str(v): int(np.sum(n_better_arr == v)) for v in sorted(set(n_better_list))}
    return {
        "experiment": "0b_permutation_null",
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_repeats": n_repeats,
        "permutation_scheme": "iid_per_split_per_side",
        "n_better_distribution": distribution,
        "n_better_mean": _mean_finite([float(v) for v in n_better_list]),
        "per_repeat": per_repeat,
    }


def write_report_atomic(payload: dict[str, Any], *, symbol: str, resolution_id: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`, mesmo padrão de
    `src.validation.leakage.write_leakage_report_atomic`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / f"noise_floor_diagnostics_{symbol}_{resolution_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.noise_floor.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fase 0 -- diagnóstico de ruído do Alpha")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--resolution-id", default="R1")
    parser.add_argument(
        "--vol-estimator-id",
        default="parkinson_w20",
        help="obrigatório sob resolution_id dollar-bar (R1/R2/R3) -- "
        "'parkinson_w20' é o estimador real usado pra gerar os labels de produção "
        "(run_and_write_labels_dollar_bar_parkinson, Fase 5 AG-036)",
    )
    parser.add_argument("--device-type", default="cuda")
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="roda só 1 execução de 0a (mede tempo real) sem commitar o orçamento inteiro",
    )
    parser.add_argument("--n-repeats-0a", type=int, default=10)
    parser.add_argument("--n-repeats-0b", type=int, default=50)
    args = parser.parse_args()

    if args.probe_only:
        result = run_seed_repetition(
            args.symbol,
            args.resolution_id,
            n_repeats=1,
            device_type=args.device_type,
            vol_estimator_id=args.vol_estimator_id,
        )
        elapsed = result["per_repeat"][0]["elapsed_seconds"]
        total_execucoes_fase0 = args.n_repeats_0a + args.n_repeats_0b  # default 10+50=60
        seconds_per_minute = 60.0  # noqa: magic-number -- conversão de unidade, não constante de domínio
        logger.info(
            "validation.noise_floor.probe_done",
            elapsed_seconds_1_execucao=elapsed,
            total_execucoes_fase0=total_execucoes_fase0,
            fase0_estimada_minutos=(elapsed * total_execucoes_fase0) / seconds_per_minute,
        )
        return 0

    t_start = time.time()
    result_0a = run_seed_repetition(
        args.symbol,
        args.resolution_id,
        n_repeats=args.n_repeats_0a,
        device_type=args.device_type,
        vol_estimator_id=args.vol_estimator_id,
    )
    result_0b = run_permutation_null(
        args.symbol,
        args.resolution_id,
        n_repeats=args.n_repeats_0b,
        device_type=args.device_type,
        vol_estimator_id=args.vol_estimator_id,
    )
    payload = {
        "symbol": args.symbol,
        "resolution_id": args.resolution_id,
        "total_elapsed_seconds": time.time() - t_start,
        "0a_seed_repetition": result_0a,
        "0b_permutation_null": result_0b,
    }
    out_path = write_report_atomic(payload, symbol=args.symbol, resolution_id=args.resolution_id)
    logger.info(
        "validation.noise_floor.cli_done",
        pooled_sharpe_mean=result_0a["pooled_sharpe_mean"],
        pooled_sharpe_std=result_0a["pooled_sharpe_std"],
        n_better_distribution=result_0b["n_better_distribution"],
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli())
