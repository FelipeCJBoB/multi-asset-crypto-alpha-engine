"""Compara, lado a lado, MÉDIA vs. DESVIO-PADRÃO de `realized_vol_short`
por `canonical_id` -- responde a pergunta em aberto da migração de
`canonicalize_states` (`AG-121`): o ADR-001 §5 recomenda desvio-padrão
(`order_stat = np.std(x, axis=0)[1]`), mas o texto do próprio `AG-121` e
`src.validation.regime_utility.identify_stress_state_by_volatility` (já
em produção) usam média. As duas estatísticas podem discordar sobre qual
estado é "o mais volátil" -- este script MEDE se discordam de verdade
nos dados reais já persistidos, não assume.

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python tools/diagnostics/compare_canonicalization_criterion_media_vs_desvio.py

**Dado usado -- sem re-fit, sem medição nova (B23).** `experiments/
m4_raw_labels/{resolution}/{window}/{symbol}/{classifier_id}.parquet`
(`canonical_id`/`close_time_ms` por barra, já persistido pela varredura
real do M4) joinado com `experiments/m4_forward_vol_history/
{resolution}/{symbol}.parquet` (`realized_vol_short` por barra,
candidato-independente) por `close_time_ms` -- mesmo padrão de join já
usado internamente por `src.analysis.m4_critical_windows`. Ressalva
honesta (não escondida): isto usa `realized_vol_short` do período OOS de
cada janela crítica, não a média AJUSTADA do fit de treino que o
pseudocódigo do ADR-001 usa literalmente (`fit.params.emissions.
means[:,1]`, não persistido em disco) -- para o HMM, os dois deveriam
convergir na mesma direção (o candidato não muda de estrutura entre
treino e OOS por desenho, `test_causalidade_perturbar_futuro_nao_muda_
passado`), mas não são bit-idênticos. Suficiente para responder "as duas
estatísticas discordam?", não para fixar o valor final da migração.

`quantile_regime_v1` (classificador BASELINE) excluído -- não usa
`canonicalize_states` (rótulo semântico próprio, docstring de
`src.regime.canonicalization` já avisa "não usar pro baseline").

Saída: `experiments/canonicalization_criterion_media_vs_desvio.json`
(escrita atômica, B29) -- por (resolution_id, window_name, symbol,
classifier_id): estado "mais volátil" segundo MÉDIA vs. segundo DESVIO-
PADRÃO, e se concordam. Resumo agregado: em quantos % das combinações os
2 critérios concordam, por classifier_id."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import orjson
import polars as pl
import structlog

from src.core.provenance import report_provenance

logger = structlog.get_logger(__name__)

_RAW_LABELS_DIR: Final[Path] = _REPO_ROOT / "experiments" / "m4_raw_labels"
_FORWARD_VOL_HISTORY_DIR: Final[Path] = _REPO_ROOT / "experiments" / "m4_forward_vol_history"
_DEST_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "canonicalization_criterion_media_vs_desvio.json"
)
# Baseline não usa canonicalize_states -- fora de escopo desta comparação
# (docstring do módulo).
_EXCLUDED_CLASSIFIER_IDS: Final[frozenset[str]] = frozenset({"quantile_regime_v1"})
# Piso de barras por estado pra uma média/desvio-padrão não ser ruído puro
# -- mesma ordem de grandeza do piso já usado em outros diagnósticos deste
# pacote (measure_dollar_bar_duration_p99_by_resolution.py).
_MIN_BARS_PER_STATE: Final[int] = 30


def _forward_vol_history_path(resolution_id: str, symbol: str) -> Path:
    return _FORWARD_VOL_HISTORY_DIR / resolution_id / f"{symbol}.parquet"


def _compare_one_cell(
    raw_labels_path: Path, resolution_id: str, symbol: str
) -> dict[str, Any] | None:
    vol_history_path = _forward_vol_history_path(resolution_id, symbol)
    if not vol_history_path.is_file():
        logger.warning(
            "diagnostics.compare_canonicalization_criterion.vol_history_missing",
            resolution_id=resolution_id,
            symbol=symbol,
            path=str(vol_history_path),
        )
        return None

    labels = pl.read_parquet(raw_labels_path).select("close_time_ms", "canonical_id")
    vol_history = pl.read_parquet(vol_history_path).select("close_time_ms", "realized_vol_short")
    joined = labels.join(vol_history, on="close_time_ms", how="inner")
    if joined.height == 0:
        return None

    per_state = (
        joined.group_by("canonical_id")
        .agg(
            pl.col("realized_vol_short").mean().alias("mean_vol"),
            pl.col("realized_vol_short").std(ddof=1).alias("std_vol"),
            pl.len().alias("n_bars"),
        )
        .sort("canonical_id")
    )
    if per_state.filter(pl.col("n_bars") < _MIN_BARS_PER_STATE).height > 0:
        return None

    mean_vol = per_state["mean_vol"].to_numpy()
    std_vol = per_state["std_vol"].to_numpy()
    canonical_ids = per_state["canonical_id"].to_numpy()
    if np.any(np.isnan(mean_vol)) or np.any(np.isnan(std_vol)):
        return None

    highest_by_mean = int(canonical_ids[int(np.argmax(mean_vol))])
    highest_by_std = int(canonical_ids[int(np.argmax(std_vol))])
    return {
        "n_states": int(per_state.height),
        "n_bars_joined": int(joined.height),
        "mean_vol_by_state": {
            str(int(cid)): round(float(v), 6)
            for cid, v in zip(canonical_ids, mean_vol, strict=True)
        },
        "std_vol_by_state": {
            str(int(cid)): round(float(v), 6)
            for cid, v in zip(canonical_ids, std_vol, strict=True)
        },
        "highest_vol_state_by_mean": highest_by_mean,
        "highest_vol_state_by_std": highest_by_std,
        "criteria_agree": highest_by_mean == highest_by_std,
    }


def main() -> None:
    if not _RAW_LABELS_DIR.is_dir():
        logger.warning(
            "diagnostics.compare_canonicalization_criterion.raw_labels_dir_missing",
            path=str(_RAW_LABELS_DIR),
        )
        results: list[dict[str, Any]] = []
    else:
        results = []
        for raw_labels_path in sorted(_RAW_LABELS_DIR.rglob("*.parquet")):
            classifier_id = raw_labels_path.stem
            if classifier_id in _EXCLUDED_CLASSIFIER_IDS:
                continue
            symbol = raw_labels_path.parent.name
            window_name = raw_labels_path.parent.parent.name
            resolution_id = raw_labels_path.parent.parent.parent.name

            comparison = _compare_one_cell(raw_labels_path, resolution_id, symbol)
            if comparison is None:
                continue
            row = {
                "resolution_id": resolution_id,
                "window_name": window_name,
                "symbol": symbol,
                "classifier_id": classifier_id,
                **comparison,
            }
            results.append(row)
            logger.info(
                "diagnostics.compare_canonicalization_criterion.cell_done",
                resolution_id=resolution_id,
                window_name=window_name,
                symbol=symbol,
                classifier_id=classifier_id,
                criteria_agree=comparison["criteria_agree"],
            )

    by_classifier: dict[str, list[bool]] = {}
    for row in results:
        by_classifier.setdefault(row["classifier_id"], []).append(row["criteria_agree"])
    agreement_summary = {
        classifier_id: {
            "n_cells": len(flags),
            "n_agree": sum(flags),
            "pct_agree": (
                round(100.0 * sum(flags) / len(flags), 1)  # noqa: magic-number -- conversão fração->percentual, não constante de domínio
                if flags
                else None
            ),
        }
        for classifier_id, flags in sorted(by_classifier.items())
    }

    payload: dict[str, Any] = {
        **report_provenance(),
        "measurement_provenance": (
            "MEASURED -- mean/std de realized_vol_short por canonical_id, lido de "
            "experiments/m4_raw_labels/ (canonical_id ja persistido pela varredura real do "
            "M4) joinado com experiments/m4_forward_vol_history/ (realized_vol_short, "
            "candidato-independente) por close_time_ms. Sem re-fit, sem medicao nova (B23). "
            "Responde AG-121 -- qual estatistica usar na migracao de canonicalize_states "
            "(media, convencao ja em producao via identify_stress_state_by_volatility, vs. "
            "desvio-padrao, pseudocodigo literal do ADR-001 SS5)."
        ),
        "excluded_classifier_ids": sorted(_EXCLUDED_CLASSIFIER_IDS),
        "min_bars_per_state": _MIN_BARS_PER_STATE,
        "n_cells_compared": len(results),
        "agreement_summary_by_classifier_id": agreement_summary,
        "results": results,
        "next_step": (
            "Manager revisa agreement_summary_by_classifier_id -- se os 2 criterios "
            "concordarem na esmagadora maioria das celulas, a escolha entre media/desvio-"
            "padrao e de baixo risco pratico (qualquer um produz a mesma migracao); se "
            "discordarem com frequencia real, a escolha do criterio muda o resultado de "
            "verdade e precisa de justificativa tecnica explicita, nao so conveniencia. "
            "B20: criterio final nao escolhido programaticamente aqui."
        ),
    }
    dest_path = _DEST_PATH
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)

    logger.info(
        "diagnostics.compare_canonicalization_criterion.done",
        n_cells_compared=len(results),
        agreement_summary=agreement_summary,
        dest_path=str(dest_path),
    )


if __name__ == "__main__":
    main()
