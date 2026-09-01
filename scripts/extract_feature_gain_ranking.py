"""Extrai gain_by_side (leitura pura, sem retreino) dos 5 candidatos × 2
camadas × 2 lados, grava um único JSON consolidado em experiments/ pra
análise de otimização de feature set (top-15/20).

Só leitura de diagnostics já em disco -- não altera nenhum artefato de
produção. Não é um dos scripts que retreinam nem otimizam; roda em segundos.

Uso:

    uv run python -m scripts.extract_feature_gain_ranking
"""

from __future__ import annotations

import orjson
import structlog

from src.analysis.attribution import gain_by_side
from src.models.pipeline import MODELS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_CAMADAS: tuple[str, ...] = ("alpha_c1_v1", "alpha_c0_baseline_v1")


def main() -> int:
    configure_logging(json_output=False)
    out: dict[str, list[dict[str, object]]] = {}
    for symbol, resolution_id in _CANDIDATOS:
        for model_id in _CAMADAS:
            diagnostics_dir = MODELS_DIR / symbol / resolution_id / model_id / "diagnostics"
            key = f"{symbol}/{resolution_id}/{model_id}"
            if not diagnostics_dir.exists():
                logger.warning("extract_feature_gain_ranking.sem_diagnostics", key=key)
                continue
            df = gain_by_side(diagnostics_dir, model_id)
            out[key] = df.to_dicts()
            logger.info("extract_feature_gain_ranking.combo_ok", key=key, n_linhas=df.height)

    dest = "experiments/feature_gain_ranking_5_candidatos_20260901.json"
    with open(dest, "wb") as f:
        f.write(orjson.dumps(out, option=orjson.OPT_INDENT_2))
    logger.info("extract_feature_gain_ranking.escrito", dest=dest, n_combos=len(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
