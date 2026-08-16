"""Mede o candidato real a `cpcv_embargo_ms` (AG-032, Bloqueador 3/E1) --
resposta direta à pergunta "quanto é '1% do fold', de verdade, sobre o
dataset real, em vez de presumido?"

**Por que isto precisa ser medido, não estimado.** `cpcv_embargo_bars=175`
(43,75h) nunca foi derivado de "1% do fold" -- essa frase é só a
justificativa de LITERATURA citada pra por que existe embargo nenhum no
lado esquerdo/trás (López de Prado, buffer de correlação serial), nunca
um número calculado sobre este dataset. Depois do fix de E4 (`AG-032`,
commit `a7e7e16` -- purge agora cobre os componentes 32 e 96 na fronteira
direita), o embargo passa a ter uma única razão de existir: correlação
serial nas duas bordas. Este script calcula o candidato honesto pra esse
número, a partir da largura REAL de cada um dos 6 grupos cronológicos do
CPCV (`cpcv.assign_time_groups`, `np.linspace` sobre `t0` real) -- não da
suposição de "~1 ano por grupo" que só tinha sido confirmada como faixa
(`test_cpcv_sobre_dataset_real_grupos_cobrem_series_completa`: 300-450
dias), nunca como valor único.

Reporta por grupo (largura real, 1% dela em ms/horas) e um candidato único
pro embargo (mediana entre os 6 grupos -- `embargo_ms` hoje é escalar
único aplicado a todos, não por grupo) contra o valor legado (175 barras =
43,75h) e o piso mecânico de 128 barras que a AG-032 original media
(128*15min = 32h) -- este último não é mais o número que importa (E4
já fecha o resíduo que ele existia pra cobrir), mas serve de referência
de escala pro leitor humano.

Saída: `experiments/cpcv_embargo_clock_candidate.json` (escrita atômica,
B29) + log estruturado com o resumo legível."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Script standalone -- sem isto, `from src...` abaixo falha com
# `ModuleNotFoundError: No module named 'src'` quando invocado por caminho
# direto (`uv run python tools/diagnostics/<este arquivo>.py`), já que só o
# diretório do script entra em sys.path[0] nesse modo (diferente de `-m`, que
# usa o cwd). Achado real (2026-08-16): os 8 scripts de tools/diagnostics/
# que importam de `src.*` tinham este mesmo bug.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("POLARS_MAX_THREADS", "1")

import numpy as np
import orjson
import structlog

from src.validation import cpcv

logger = structlog.get_logger(__name__)

_DEST_PATH = _REPO_ROOT / "experiments" / "cpcv_embargo_clock_candidate.json"

_MS_PER_HOUR = 3_600_000
_LEGACY_EMBARGO_BARS = 175
_LEGACY_EMBARGO_MS = _LEGACY_EMBARGO_BARS * 900_000  # 15m, valor histórico do CLAUDE.md
_MECHANICAL_FLOOR_BARS = 128  # AG-032 original: time_stop(32) + feature_c06(96)
_MECHANICAL_FLOOR_MS = _MECHANICAL_FLOOR_BARS * 900_000
_EMBARGO_FRACTION_OF_FOLD = 0.01  # "1% do fold", López de Prado -- literatura, não medição


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão de `m2_bar_comparison._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)


def main() -> None:
    labels = cpcv.load_labels_v1()
    cfg = cpcv.CPCVConfig.from_constants()
    t0_ms = labels["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    group_id, edges_ms = cpcv.assign_time_groups(t0_ms, cfg.n_groups)

    per_group = []
    for g in range(cfg.n_groups):
        span_ms = int(edges_ms[g + 1]) - int(edges_ms[g])
        candidate_ms = round(span_ms * _EMBARGO_FRACTION_OF_FOLD)
        n_rows = int((group_id == g).sum())
        per_group.append(
            {
                "group": g,
                "span_days": round(span_ms / (24 * _MS_PER_HOUR), 2),  # noqa: unguarded-ratio -- literal > 0
                "n_rows": n_rows,
                "embargo_1pct_ms": candidate_ms,
                "embargo_1pct_hours": round(candidate_ms / _MS_PER_HOUR, 2),  # noqa: unguarded-ratio -- literal > 0
            }
        )

    candidates_ms = np.array([row["embargo_1pct_ms"] for row in per_group], dtype=np.int64)
    median_candidate_ms = int(np.median(candidates_ms))
    min_candidate_ms = int(candidates_ms.min())
    max_candidate_ms = int(candidates_ms.max())

    payload = {
        "symbol": "BTCUSDT",
        "tf": cfg.tf,
        "n_groups": cfg.n_groups,
        "n_rows_total": labels.height,
        "per_group": per_group,
        "candidate_median_ms": median_candidate_ms,
        "candidate_median_hours": round(median_candidate_ms / _MS_PER_HOUR, 2),  # noqa: unguarded-ratio -- literal > 0
        "candidate_min_ms": min_candidate_ms,
        "candidate_max_ms": max_candidate_ms,
        "legacy_embargo_bars": _LEGACY_EMBARGO_BARS,
        "legacy_embargo_ms": _LEGACY_EMBARGO_MS,
        "legacy_embargo_hours": round(_LEGACY_EMBARGO_MS / _MS_PER_HOUR, 2),  # noqa: unguarded-ratio -- literal > 0
        "mechanical_floor_bars_pre_e4": _MECHANICAL_FLOOR_BARS,
        "mechanical_floor_ms_pre_e4": _MECHANICAL_FLOOR_MS,
        "mechanical_floor_hours_pre_e4": round(_MECHANICAL_FLOOR_MS / _MS_PER_HOUR, 2),  # noqa: unguarded-ratio -- literal > 0
        "median_vs_legacy_ratio": round(median_candidate_ms / _LEGACY_EMBARGO_MS, 3),  # noqa: unguarded-ratio -- literal > 0
    }
    _atomic_write_json(payload, _DEST_PATH)

    logger.info(
        "diagnostics.measure_cpcv_embargo_clock_candidate.done",
        n_groups=cfg.n_groups,
        n_rows_total=labels.height,
        per_group=per_group,
        candidate_median_hours=payload["candidate_median_hours"],
        candidate_min_hours=round(min_candidate_ms / _MS_PER_HOUR, 2),  # noqa: unguarded-ratio -- literal > 0
        candidate_max_hours=round(max_candidate_ms / _MS_PER_HOUR, 2),  # noqa: unguarded-ratio -- literal > 0
        legacy_embargo_hours=payload["legacy_embargo_hours"],
        mechanical_floor_hours_pre_e4=payload["mechanical_floor_hours_pre_e4"],
        median_vs_legacy_ratio=payload["median_vs_legacy_ratio"],
        dest_path=str(_DEST_PATH),
    )


if __name__ == "__main__":
    main()
