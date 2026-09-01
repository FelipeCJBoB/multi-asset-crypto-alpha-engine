"""Bootstrap em bloco para os pooled do Ângulo 7 (AUC) e Ângulo 8 (edge_bps) —
fecha o item 15 do roadmap "Caso 0/20" (backlog item 2 do adendo
`docs/adendo_angulos_7_8_pooled_meta_analise_gate_model_alpha_2026-08-31.md`).

**Por que.** Os pooled originais (Ângulos 7/8) usam aproximação normal
(Zelen & Severo 1964) sobre `SE_pooled` teórico (Hanley-McNeil pra AUC,
identidade via `sharpe_naive` pra edge) — nunca testada contra a
autocorrelação REAL medida entre folds (`AG-392` item 1: lag-1
predominantemente negativo, média -0,216, só 1 de 5 séries positiva
+0,854). Este script substitui a aproximação normal por reamostragem
não-paramétrica (moving block bootstrap), respeitando a ordem temporal
dos folds dentro de cada combo.

**Método.** Cada fold já carrega seu peso de variância-inversa (mesma
fórmula do adendo: Hanley-McNeil pra AUC, identidade `t_stat=sharpe_naive
· sqrt(span_years)` pra edge). O bootstrap reamostra BLOCOS de `L` folds
consecutivos (com reposição, circular) dentro de cada combo — preserva
autocorrelação de curto prazo se ela existisse — e agrega através dos 5
combos (mesma suposição de independência entre-combo já assumida no
Ângulo 7, não retestada aqui). `L=1` equivale a bootstrap i.i.d. comum;
reportado lado a lado com `L=2` como checagem de sensibilidade ao
comprimento do bloco, já que a autocorrelação medida é fraca/negativa.

Valor de saída: SE bootstrap (empírico) vs. SE paramétrico (Hanley-McNeil/
identidade), IC percentil 90%, e p-valor empírico unicaudal (fração de
réplicas bootstrap no lado nulo).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path

import structlog

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
_VARIANTS: tuple[str, ...] = ("camada1", "camada0")
_SIDES: tuple[str, ...] = ("long", "short")


_TRES = 3.0  # noqa: magic-number -- fator fixo Hanley-McNeil, nao constante de dominio


def _auc_weight(n_trades: int) -> float:
    se_sq = (n_trades + 1) / (_TRES * n_trades * n_trades)  # noqa: unguarded-ratio -- n_trades>0 ja garantido pelo `if n_trades <= 0: continue` do caller
    return 1.0 / se_sq  # noqa: unguarded-ratio -- se_sq>0 sempre (n_trades>0 por construcao)


def _span_years(test_start: str, test_end: str) -> float:
    t0 = datetime.fromisoformat(test_start)
    t1 = datetime.fromisoformat(test_end)
    dias_por_ano = 365.25  # noqa: magic-number -- calendario, mesma aproximacao do adendo
    denom = 86400.0 * dias_por_ano  # noqa: magic-number -- segundos/dia, literal fixo >0
    return (t1 - t0).total_seconds() / denom  # noqa: unguarded-ratio -- denom e literal fixo positivo, nunca 0


def _load_auc_series(
    experiments_dir: Path, suffix: str
) -> dict[str, list[tuple[float, float]]]:
    """Retorna, por `variant|side|symbol/res`, lista ordenada por fold_id de (auc, peso)."""
    out: dict[str, list[tuple[float, float]]] = {}
    for symbol, res in _CANDIDATOS:
        path = experiments_dir / f"alpha_walk_forward_{symbol}_{res}{suffix}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for variant in _VARIANTS:
            for side in _SIDES:
                combo_series: list[tuple[float, float]] = []
                for fold in sorted(payload[variant]["fold_results"], key=lambda f: f["fold_id"]):
                    if fold["degenerado"]:
                        continue
                    sq = fold["score_quality_by_side"].get(side)
                    if sq is None or sq.get("roc_auc") is None:
                        continue
                    n_trades = sq["n_trades"]
                    if n_trades <= 0:
                        continue
                    combo_series.append((sq["roc_auc"], _auc_weight(n_trades)))
                if combo_series:
                    out[f"{variant}|{side}|{symbol}/{res}"] = combo_series
    return out


def _load_edge_series(
    experiments_dir: Path, suffix: str
) -> dict[str, list[tuple[float, float]]]:
    """Retorna, por variant, lista de listas por combo de (edge_bps, peso)."""
    out: dict[str, list[tuple[float, float]]] = {}
    for symbol, res in _CANDIDATOS:
        path = experiments_dir / f"alpha_walk_forward_{symbol}_{res}{suffix}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for variant in _VARIANTS:
            combo_series: list[tuple[float, float]] = []
            for fold in sorted(payload[variant]["fold_results"], key=lambda f: f["fold_id"]):
                if fold["degenerado"]:
                    continue
                edge_bps = fold["edge_bps"]
                sharpe = fold["sharpe"]
                if edge_bps is None or sharpe is None or sharpe == 0.0:
                    continue
                span_years = _span_years(fold["test_start"], fold["test_end"])
                if span_years <= 0.0:
                    continue
                t_stat = sharpe * math.sqrt(span_years)
                if t_stat == 0.0:
                    continue
                se = edge_bps / t_stat
                if se == 0.0:
                    continue
                combo_series.append((edge_bps, 1.0 / (se * se)))  # noqa: unguarded-ratio -- se!=0.0 ja garantido pelo `if se == 0.0: continue` acima nesta funcao
            if combo_series:
                out[f"{variant}|{symbol}/{res}"] = combo_series
    return out


def _weighted_pool(values_weights: list[tuple[float, float]]) -> float:
    soma_peso = sum(w for _, w in values_weights)
    return sum(v * w for v, w in values_weights) / soma_peso  # noqa: unguarded-ratio -- guardado por _bootstrap_replicas: so chama com lista nao-vazia (peso sempre >0 por construcao)


def _block_resample(
    series: list[tuple[float, float]], block_length: int, rng: random.Random
) -> list[tuple[float, float]]:
    k = len(series)
    if k == 0:
        return []
    resampled: list[tuple[float, float]] = []
    while len(resampled) < k:
        start = rng.randrange(k)
        for j in range(block_length):
            resampled.append(series[(start + j) % k])
    return resampled[:k]


def _bootstrap_replicas(
    combo_series_list: list[list[tuple[float, float]]],
    *,
    block_length: int,
    n_bootstrap: int,
    seed: int,
) -> list[float]:
    rng = random.Random(seed)  # noqa: banned-random -- reamostragem estatistica declarada, nao seguranca/trial de producao
    replicas: list[float] = []
    for _ in range(n_bootstrap):
        pooled: list[tuple[float, float]] = []
        for series in combo_series_list:
            pooled.extend(_block_resample(series, block_length, rng))
        if pooled:
            replicas.append(_weighted_pool(pooled))
    return replicas


def _report_cell(
    *,
    label: str,
    combo_series_list: list[list[tuple[float, float]]],
    null_value: float,
    n_bootstrap: int,
    seed: int,
) -> None:
    pooled_all = [item for series in combo_series_list for item in series]
    if not pooled_all:
        logger.info("scripts.measure_pooled_block_bootstrap.sem_dado", label=label)
        return
    observado = _weighted_pool(pooled_all)
    soma_pesos = math.sqrt(sum(w for _, w in pooled_all))
    se_parametrico = 1.0 / soma_pesos  # noqa: unguarded-ratio -- pesos sempre >0 (Hanley-McNeil/inverso de SE^2), pooled_all nao-vazio garantido pelo early-return acima
    n_folds = len(pooled_all)

    for block_length in (1, 2):
        replicas = _bootstrap_replicas(
            combo_series_list,
            block_length=block_length,
            n_bootstrap=n_bootstrap,
            seed=seed,
        )
        replicas.sort()
        n_rep = len(replicas)
        if n_rep > 1:
            variancia_boot = sum((r - observado) ** 2 for r in replicas) / (n_rep - 1)  # noqa: unguarded-ratio -- guardado por `if n_rep > 1` nesta mesma funcao
            se_boot = variancia_boot**0.5
        else:
            se_boot = float("nan")
        p05 = replicas[int(0.05 * n_rep)]  # noqa: magic-number -- percentil 5/95, definicao padrao de IC 90%
        p95 = replicas[int(0.95 * n_rep) - 1]  # noqa: magic-number
        frac_abaixo_nulo = (
            sum(1 for r in replicas if r <= null_value) / n_rep  # noqa: unguarded-ratio -- n_rep=n_bootstrap (argparse default=2000, sempre>0)
            if n_rep > 0
            else float("nan")
        )
        p_empirico = frac_abaixo_nulo if observado >= null_value else 1.0 - frac_abaixo_nulo
        logger.info(
            "scripts.measure_pooled_block_bootstrap.celula",
            label=label,
            block_length=block_length,
            n_folds=n_folds,
            n_bootstrap_efetivo=n_rep,
            observado=round(observado, 4),
            se_parametrico=round(se_parametrico, 4),
            se_bootstrap=round(se_boot, 4),
            ic90_bootstrap=(round(p05, 4), round(p95, 4)),
            null_value=null_value,
            p_empirico_unicaudal=round(p_empirico, 4),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix", default="")
    parser.add_argument("--experiments-dir", type=Path, default=EXPERIMENTS_DIR)
    parser.add_argument("--n-bootstrap", type=int, default=2000)  # noqa: magic-number -- mesmo orcamento de replicas do measure_gate_power.py
    parser.add_argument(
        "--seed", type=int, default=int(load_constant("alpha_random_seed"))
    )
    args = parser.parse_args(argv)

    configure_logging(json_output=False)

    auc_by_variant_side: dict[str, list[list[tuple[float, float]]]] = {}
    auc_raw = _load_auc_series(args.experiments_dir, args.suffix)
    for key, series in auc_raw.items():
        variant, side, _combo = key.split("|")
        auc_by_variant_side.setdefault(f"{variant}|{side}", []).append(series)

    for variant in _VARIANTS:
        combo_series_list: list[list[tuple[float, float]]] = []
        for side in _SIDES:
            combo_series_list.extend(auc_by_variant_side.get(f"{variant}|{side}", []))
        null_value = 0.5  # noqa: magic-number -- H0 do gate Model, AUC de moeda honesta
        _report_cell(
            label=f"angulo7_auc_portfolio_{variant}",
            combo_series_list=combo_series_list,
            null_value=null_value,
            n_bootstrap=args.n_bootstrap,
            seed=args.seed,
        )

    edge_raw = _load_edge_series(args.experiments_dir, args.suffix)
    edge_by_variant: dict[str, list[list[tuple[float, float]]]] = {}
    for key, series in edge_raw.items():
        parts = key.split("|")
        if len(parts) != 2:
            continue
        variant, _combo = parts
        edge_by_variant.setdefault(variant, []).append(series)

    for variant in _VARIANTS:
        combo_series_list = edge_by_variant.get(variant, [])
        null_value = 0.0  # noqa: magic-number -- H0 do gate Alpha, edge_bps zero
        _report_cell(
            label=f"angulo8_edge_portfolio_{variant}",
            combo_series_list=combo_series_list,
            null_value=null_value,
            n_bootstrap=args.n_bootstrap,
            seed=args.seed,
        )

    xrp_r3_c0_edge = [
        series
        for key, series in edge_raw.items()
        if key == "camada0|XRPUSDT/R3"
    ]
    if xrp_r3_c0_edge:
        _report_cell(
            label="angulo8_edge_XRPUSDT_R3_camada0_celula_unica_p_lt_005",
            combo_series_list=xrp_r3_c0_edge,
            null_value=0.0,
            n_bootstrap=args.n_bootstrap,
            seed=args.seed,
        )

    logger.info("scripts.measure_pooled_block_bootstrap.concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
