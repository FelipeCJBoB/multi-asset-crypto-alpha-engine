"""Q10-Q1 pooled em nível de portfólio — fecha o item 14 do roadmap "Caso
0/20" (backlog próprio, Ângulo do adendo dos Ângulos 7-8: métrica de rank
não-linear pode captar sinal concentrado nos extremos de confiança, que
AUC/edge médio — ambos lineares — não capturam).

**Método.** `Q10-Q1` já é medido por fold/lado (`score_quality.
compute_decile_profile`, persistido em `decile_profile_by_side`). Sem os
trades brutos por barra (só os buckets agregados por fold), um pooling
"de verdade" (rejuntar os decis através de folds) não é reconstruível a
partir do artefato — a alternativa honesta é a média PONDERADA por
`n_trades` do decil 1+10 (mais peso pros folds com mais trades nos
extremos, não um "quanto vale mais" arbitrário) mais a checagem de
consistência de SINAL entre folds (quantos folds concordam na direção —
um spread real deveria ser majoritariamente consistente, ruído puro
deveria ser ~50/50).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import structlog

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix", default="")
    parser.add_argument("--experiments-dir", type=Path, default=EXPERIMENTS_DIR)
    args = parser.parse_args(argv)

    configure_logging(json_output=False)

    for variant in _VARIANTS:
        for side in _SIDES:
            valores_ponderados: list[tuple[float, float]] = []  # (valor, peso)
            sinais_positivos = 0
            sinais_negativos = 0
            for symbol, res in _CANDIDATOS:
                suffix = f"_{args.suffix}" if args.suffix else ""
                path = args.experiments_dir / f"alpha_walk_forward_{symbol}_{res}{suffix}.json"
                payload = json.loads(path.read_text(encoding="utf-8"))[variant]
                for fold in payload["fold_results"]:
                    if fold["degenerado"]:
                        continue
                    dp = fold.get("decile_profile_by_side", {}).get(side)
                    if dp is None or dp.get("q10_minus_q1_bps") is None:
                        continue
                    q10_q1 = dp["q10_minus_q1_bps"]
                    buckets = dp["buckets"]
                    peso = buckets[0]["n_trades"] + buckets[-1]["n_trades"]
                    if peso <= 0:
                        continue
                    valores_ponderados.append((q10_q1, float(peso)))
                    if q10_q1 > 0:
                        sinais_positivos += 1
                    elif q10_q1 < 0:
                        sinais_negativos += 1

            if not valores_ponderados:
                logger.info(
                    "scripts.measure_q10_q1_pooled.sem_dado", variant=variant, side=side
                )
                continue

            soma_peso = sum(p for _, p in valores_ponderados)
            media_ponderada = sum(v * p for v, p in valores_ponderados) / soma_peso  # noqa: unguarded-ratio -- soma_peso>0 garantido pelos `if peso<=0: continue`/`if not valores_ponderados` acima
            n_folds = len(valores_ponderados)
            total_sinais = sinais_positivos + sinais_negativos
            frac_positivos = (
                sinais_positivos / total_sinais if total_sinais > 0 else float("nan")  # noqa: unguarded-ratio -- guardado pelo ternario: so divide quando total_sinais>0
            )
            logger.info(
                "scripts.measure_q10_q1_pooled.celula",
                variant=variant,
                side=side,
                n_folds=n_folds,
                q10_q1_pooled_ponderado_bps=round(media_ponderada, 2),
                n_trades_totais_nos_extremos=int(soma_peso),
                sinais_positivos=sinais_positivos,
                sinais_negativos=sinais_negativos,
                frac_folds_positivos=round(frac_positivos, 3)
                if frac_positivos == frac_positivos  # NaN-safe sem import extra
                else None,
            )

    logger.info("scripts.measure_q10_q1_pooled.concluido")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
