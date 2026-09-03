"""Medição EXPLORATÓRIA: o que acontece com `target_signal_rate` ACIMA do
topo do `sweep_range` já adotado ([0,0095; 0,0284] — a banda de
sensibilidade ±50% em torno do valor DERIVED antigo, 0,0189, exigida por
CLAUDE.md §Proveniência pra classe A antes do Gate 3).

Isto NÃO estende `sweep_range` em `constants.yaml` — é só uma pergunta
"e se" (pedida pelo Manager, 2026-09-03) sobre a continuação da mesma
relação monotônica já medida no Estágio B (`scripts.sweep_tau_mechanism
--stage B`), pra ver se ela permanece bem comportada (ao contrário do
tau FIXO em 0,51, que devolveu taxa de sinal descontrolada — 56% médio,
sem relação com nenhum orçamento). Reusa `_summarize_point` de
`scripts.sweep_tau_mechanism` sem modificação, mesma métrica (frac de
fold usável / std do signal_rate realizado, nunca edge/Sharpe), mesma
janela travada (180d, vencedora do Estágio A).

Nenhum artefato canônico é tocado, `constants.yaml` não é editado --
escreve só em `experiments/tau_sweep_rate_beyond_range.json`.

Uso:

    uv run python -m scripts.sweep_tau_rate_beyond_range
"""

from __future__ import annotations

import sys
from typing import Any

import structlog

from scripts.sweep_tau_mechanism import _summarize_point
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import write_report_atomic
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

# Pontos ACIMA do topo do sweep_range já adotado (0,0284) -- eixo do
# experimento, não constante de domínio. 0,04/0,06/0,10 escolhidos pra
# cobrir ~1,4x/2,1x/3,5x o valor adotado, espaçamento log-like grosseiro
# suficiente pra ver se a relação continua monotônica bem comportada ou
# se degenera (mesmo tipo de teste que expôs o problema do tau=0,51
# fixo).
_RATE_POINTS_BEYOND_RANGE: tuple[float, ...] = (0.15,)  # noqa: magic-number
# vencedor do Estágio A, mesmo valor de produção
_TAU_WINDOW_DAYS_LOCKED = 180  # noqa: magic-number
# sweep_range já declarado em constants.yaml::target_signal_rate -- citado
# aqui só pra registro no payload, não uma constante de domínio nova.
_SWEEP_RANGE_DECLARADO = (0.0095, 0.0284)  # noqa: magic-number


def main(argv: list[str] | None = None) -> int:
    configure_logging(json_output=False)
    seed = int(load_constant("alpha_random_seed"))

    points: list[dict[str, Any]] = []
    for rate in _RATE_POINTS_BEYOND_RANGE:
        logger.info(
            "scripts.sweep_tau_rate_beyond_range.ponto_iniciado",
            tau_window_days=_TAU_WINDOW_DAYS_LOCKED,
            target_signal_rate=rate,
        )
        points.append(
            _summarize_point(
                tau_window_days=_TAU_WINDOW_DAYS_LOCKED,
                target_signal_rate=rate,
                seed=seed,
                device_type="cpu",
            )
        )

    out_path = EXPERIMENTS_DIR / "tau_sweep_rate_beyond_range_015.json"
    payload = {
        "seed": seed,
        "tau_window_days_locked": _TAU_WINDOW_DAYS_LOCKED,
        "sweep_range_declarado": list(_SWEEP_RANGE_DECLARADO),
        "nota": (
            "pontos ACIMA do topo do sweep_range ja adotado -- exploratorio, "
            "nao estende constants.yaml::target_signal_rate.sweep_range"
        ),
        "points": points,
        "producer_entrypoint": "scripts.sweep_tau_rate_beyond_range",
    }
    write_report_atomic(payload, dest_path=out_path)
    logger.info(
        "scripts.sweep_tau_rate_beyond_range.concluido", path=str(out_path), n_points=len(points)
    )
    return 0


if __name__ == "__main__":  # pragma: no cover -- execução manual
    sys.exit(main())
