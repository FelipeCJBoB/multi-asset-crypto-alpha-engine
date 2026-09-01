"""Condicionamento por regime (proxy fold-a-fold) — fecha o item 16 do
roadmap "Caso 0/20" (backlog item 3 do adendo `docs/adendo_angulos_7_8_
pooled_meta_analise_gate_model_alpha_2026-08-31.md`).

**Hipótese testada.** `R10` (documento-fonte) já sinaliza que a janela de
teste walk-forward é dominada por um único regime macro — se verdade, sinal
concentrado num subconjunto de regime ficaria mascarado na média
incondicional dos gates oficiais. `E05f_time_to_funding_h`/
`E16f_global_ls_ratio` são as 2 features SHAP-dominantes (Seção 8.2 do
documento-fonte).

**Por que é um PROXY, não o teste ideal.** O teste ideal condicionaria
AUC/edge por BARRA (regime da barra no momento do trade), o que exige as
previsões (`p_long`/`p_short`) por barra — não persistidas nos artefatos
walk-forward existentes (`keep_predictions=False` é o default até hoje,
`986e527`). Reconstruí-las exigiria um NOVO walk-forward retreinado
(`n_lifetime` real), não autorizado nesta rodada (mesma lógica de custo do
item 12/`AG-411`). Esta versão usa a granularidade de FOLD: para cada fold
não-degenerado, calcula a mediana de `E05f`/`E16f` dentro da janela de
teste do fold (`build_modeling_frame` — leitura pura de feature já
materializada, sem treino, sem custo de `n_lifetime`) e correlaciona
(Spearman) com a AUC/edge_bps JÁ MEDIDA daquele fold. Mais fraco que
condicionamento por barra, mas real e sem custo de trial novo.

**Achado sob demanda separado**: a variância do proxy ENTRE folds também
testa `R10` diretamente — regime homogêneo entre folds (proxy quase
constante) sustentaria `R10`; heterogeneidade real abriria espaço pro
condicionamento de barra ser o próximo passo genuíno (não feito aqui).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path

import structlog
from scipy import stats

from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.dataset import build_modeling_frame
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
_REGIME_FEATURES: tuple[str, ...] = ("E05f_time_to_funding_h", "E16f_global_ls_ratio")


def _fold_regime_proxy(
    symbol: str, resolution_id: str, fold_windows: list[tuple[int, str, str]]
) -> dict[int, dict[str, float]]:
    """`fold_windows` = [(fold_id, test_start, test_end), ...]. Retorna
    fold_id -> {feature: mediana, "n_bars": int} dentro da janela de teste."""
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
    mf = build_modeling_frame(
        symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
    )
    out: dict[int, dict[str, float]] = {}
    for fold_id, test_start, test_end in fold_windows:
        t0_start = datetime.fromisoformat(test_start)
        t0_end = datetime.fromisoformat(test_end)
        window = mf.data.filter(
            (mf.data["t0"] >= t0_start) & (mf.data["t0"] < t0_end)
        )
        n_bars = window.height
        if n_bars == 0:
            continue
        entry: dict[str, float] = {"n_bars": float(n_bars)}
        for feat in _REGIME_FEATURES:
            mediana = window[feat].median()
            entry[feat] = (
                float(mediana) if mediana is not None else float("nan")  # type: ignore[arg-type]
            )
        out[fold_id] = entry
    return out


def _load_fold_windows(
    experiments_dir: Path, suffix: str, symbol: str, res: str
) -> list[tuple[int, str, str]]:
    path = experiments_dir / f"alpha_walk_forward_{symbol}_{res}{suffix}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    windows: list[tuple[int, str, str]] = []
    for fold in payload["camada1"]["fold_results"]:
        if fold["degenerado"]:
            continue
        windows.append((fold["fold_id"], fold["test_start"], fold["test_end"]))
    return windows


@dataclasses.dataclass
class FoldPerformance:
    edge_bps_by_variant: dict[str, float | None] = dataclasses.field(default_factory=dict)
    auc_by_variant_side: dict[str, dict[str, float | None]] = dataclasses.field(
        default_factory=dict
    )


def _load_fold_performance(
    experiments_dir: Path, suffix: str, symbol: str, res: str
) -> dict[int, FoldPerformance]:
    out: dict[int, FoldPerformance] = {}
    for variant in _VARIANTS:
        path = experiments_dir / f"alpha_walk_forward_{symbol}_{res}{suffix}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for fold in payload[variant]["fold_results"]:
            if fold["degenerado"]:
                continue
            fold_id = fold["fold_id"]
            entry = out.setdefault(fold_id, FoldPerformance())
            entry.edge_bps_by_variant[variant] = fold["edge_bps"]
            auc_by_side: dict[str, float | None] = {}
            for side in _SIDES:
                sq = fold["score_quality_by_side"].get(side)
                auc_by_side[side] = sq["roc_auc"] if sq is not None else None
            entry.auc_by_variant_side[variant] = auc_by_side
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix", default="")
    parser.add_argument("--experiments-dir", type=Path, default=EXPERIMENTS_DIR)
    args = parser.parse_args(argv)

    configure_logging(json_output=False)

    regime_por_feature: dict[str, list[float]] = {feat: [] for feat in _REGIME_FEATURES}
    auc_por_feature: dict[str, list[float]] = {feat: [] for feat in _REGIME_FEATURES}
    edge_por_feature: dict[str, list[float]] = {feat: [] for feat in _REGIME_FEATURES}
    edge_values_por_feature: dict[str, list[float]] = {feat: [] for feat in _REGIME_FEATURES}

    for symbol, res in _CANDIDATOS:
        windows = _load_fold_windows(args.experiments_dir, args.suffix, symbol, res)
        proxy = _fold_regime_proxy(symbol, res, windows)
        perf = _load_fold_performance(args.experiments_dir, args.suffix, symbol, res)

        proxy_medians = {feat: [proxy[fid][feat] for fid in proxy] for feat in _REGIME_FEATURES}
        logger.info(
            "scripts.measure_regime_conditioning_proxy.heterogeneidade_por_combo",
            symbol=symbol,
            resolution_id=res,
            n_folds=len(proxy),
            **{
                f"{feat}_min": round(min(vals), 3) if vals else None
                for feat, vals in proxy_medians.items()
            },
            **{
                f"{feat}_max": round(max(vals), 3) if vals else None
                for feat, vals in proxy_medians.items()
            },
        )

        for fold_id, proxy_entry in proxy.items():
            perf_entry = perf.get(fold_id)
            if perf_entry is None:
                continue
            for variant in _VARIANTS:
                edge_bps = perf_entry.edge_bps_by_variant.get(variant)
                auc_by_side = perf_entry.auc_by_variant_side.get(variant, {})
                for feat in _REGIME_FEATURES:
                    regime_val = proxy_entry[feat]
                    if edge_bps is not None:
                        edge_por_feature[feat].append(regime_val)
                        edge_values_por_feature[feat].append(edge_bps)
                    for side in _SIDES:
                        auc_val = auc_by_side.get(side)
                        if auc_val is not None:
                            regime_por_feature[feat].append(regime_val)
                            auc_por_feature[feat].append(auc_val)

    for feat in _REGIME_FEATURES:
        if len(regime_por_feature[feat]) >= 3:  # noqa: magic-number -- minimo p/ spearman ter sentido, nao constante de dominio
            rho, p = stats.spearmanr(regime_por_feature[feat], auc_por_feature[feat])
            logger.info(
                "scripts.measure_regime_conditioning_proxy.correlacao_auc",
                feature=feat,
                n=len(regime_por_feature[feat]),
                spearman_rho=round(float(rho), 4),
                p_valor=round(float(p), 4),
            )
        if len(edge_por_feature[feat]) >= 3:  # noqa: magic-number -- minimo p/ spearman ter sentido
            rho_e, p_e = stats.spearmanr(edge_por_feature[feat], edge_values_por_feature[feat])
            logger.info(
                "scripts.measure_regime_conditioning_proxy.correlacao_edge",
                feature=feat,
                n=len(edge_por_feature[feat]),
                spearman_rho=round(float(rho_e), 4),
                p_valor=round(float(p_e), 4),
            )

    logger.info("scripts.measure_regime_conditioning_proxy.concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
