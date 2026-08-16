"""Mede a distribuição EMPÍRICA de `n_bars_held` (tempo de primeira
passagem até TP ou SL) em `labels.parquet`, pros 5 ativos -- resposta
direta à pergunta "o horizonte de 32 barras (`time_stop_bars`, 8h a 15m,
`constants.yaml` linha ~139) está calibrado pra este motor, ou é folga
demais/de menos?", levantada ao aplicar a lente FE
(`.claude/skills/audit_engineering/SKILL.md`) ao Label Engine (2026-08-15).

`time_stop_bars` foi justificado em `constants.yaml` como "uma janela de
funding" -- 32×15min = 8h, mesmo período de liquidação de funding da
Binance. Essa é uma leitura estética (soa bem, é redonda) que não conecta
com nada que o sistema realmente calcula: `round_trip_cost_bps`
(`src/features/groups/group_e.py`) usa só `maker_fee`/`taker_fee`, nunca
funding. A pergunta que decide de verdade é outra: quanto tempo os trades
REALMENTE levam pra resolver por barreira, medido no dado já gravado.

O QUE este script mede: pra trades que resolveram por TP ou SL (não por
TIME nem NOFILL -- ver por quê abaixo), a distribuição real de
`n_bars_held`, e o quão perto do teto atual (`time_stop_bars`) a maioria
chega. `n_bars_held <= time_stop_bars` é invariante por construção
(`assert_label_invariants`, `triple_barrier.py`) pra TODA linha TP/SL --
então a pergunta não é "que fração ultrapassa o teto" (nenhuma, por
definição), é "quão perto dele a maioria chega". Se `p90` ficar bem
abaixo do teto, há folga real; se `p90` chegar perto do teto, ele está
sendo pressionado de verdade.

Exclusões deliberadas: `TIME` é censurado no próprio teto por construção
(`n_bars_held == time_stop_bars` sempre que a barreira que "vence" é o
tempo) -- incluir infla artificialmente a cauda alta e não diz nada sobre
quão rápido barreira normalmente resolve. `NOFILL` tem `n_bars_held=0`
literal (a ordem nunca encheu, não houve posição) -- não é tempo de
retenção nenhum.

DUAS RESTRIÇÕES DELIBERADAS sobre o que este script NÃO faz, acordadas
ANTES de escrever o código (Manager, 2026-08-15) -- não descobertas
depois:

1. **NÃO deriva nem propõe um novo valor final pra `time_stop_bars`.** A
   distribuição de `n_bars_held` é função de `tp_atr_mult`/`sl_atr_mult`
   (ambos `class: A`, `ASSUMED`, varredura 2D já planejada pro Sprint 6,
   ver "Estado atual" em `CLAUDE.md`) -- mudar essas duas barreiras muda
   essa distribuição inteira. Derivar o horizonte a partir da calibração
   ATUAL das barreiras seria derivar de uma base que está prestes a
   mudar. Este script é DIAGNÓSTICO (sinal de direção: "32 está com
   folga folgada ou apertada, HOJE"), não a medição final -- o horizonte
   correto entra na varredura 2D existente (virando 3D) ou é rederivado
   DEPOIS dela.

2. **NÃO calcula Information Coefficient em múltiplos horizontes pra
   escolher o "melhor".** Seria a forma mais direta de responder "o
   label olha longe demais", mas rodar IC(horizonte) pra 8/16/32/64 sobre
   a amostra completa e escolher o pico de |IC| é exatamente o banned
   pattern B06 (`CLAUDE.md`) -- usar uma tabela de IC calculada sobre o
   histórico inteiro pra CONFIGURAR o modelo é look-ahead por seleção,
   mesma classe de B04/B20. Se essa medição for feita algum dia, precisa
   ser triagem IN-FOLD (§5.4), não um script solto contra o parquet
   inteiro. Este script fica estritamente descritivo: conta uma coluna
   que já existe, não computa nenhuma métrica de desempenho preditivo --
   por isso NÃO é uma instância de B06.

Rodar depois que `data/labels/{symbol}/15m/v1/labels.parquet` existir
pro(s) símbolo(s) de interesse (já existe pra BTCUSDT/ETHUSDT/BNBUSDT/
XRPUSDT/SOLUSDT, confirmado no Road Map Vivo)."""

from __future__ import annotations

import numpy as np
import polars as pl
import structlog

from src.data._constants import load_constant as load_data_constant
from src.validation.cpcv import load_labels_v1

logger = structlog.get_logger(__name__)

_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT")
_PERCENTILES: tuple[int, ...] = (50, 75, 90, 95, 99)
_CEILING_PROXIMITY_BARS: int = 4  # "perto do teto" = dentro de 4 barras (1h a 15m) dele


def _percentiles(n_bars_held: np.ndarray) -> dict[str, float]:
    return {f"p{p}": float(np.percentile(n_bars_held, p)) for p in _PERCENTILES}


def main() -> None:
    time_stop_bars = int(load_data_constant("time_stop_bars"))
    ceiling_threshold = time_stop_bars - _CEILING_PROXIMITY_BARS

    pooled: list[int] = []

    for symbol in _SYMBOLS:
        try:
            labels = load_labels_v1(symbol=symbol)
        except FileNotFoundError as exc:
            logger.warning(
                "diagnostics.measure_time_stop_slack.symbol_skipped",
                symbol=symbol,
                error=repr(exc),
            )
            continue

        resolved = labels.filter(labels["barrier_hit"].cast(pl.Utf8).is_in(["TP", "SL"]))
        n_resolved = resolved.height
        if n_resolved == 0:
            logger.warning(
                "diagnostics.measure_time_stop_slack.no_tp_sl",
                symbol=symbol,
            )
            continue

        n_bars_held = resolved["n_bars_held"].cast(pl.Int64).to_numpy()
        pooled.extend(n_bars_held.tolist())

        frac_near_ceiling = float(np.mean(n_bars_held >= ceiling_threshold))

        logger.info(
            "diagnostics.measure_time_stop_slack.symbol_done",
            symbol=symbol,
            time_stop_bars=time_stop_bars,
            n_resolved_tp_sl=n_resolved,
            frac_within_4_bars_of_ceiling=round(frac_near_ceiling, 4),
            **{k: round(v, 2) for k, v in _percentiles(n_bars_held).items()},
        )

    if not pooled:
        logger.warning(
            "diagnostics.measure_time_stop_slack.no_data",
            note="nenhum símbolo tinha labels.parquet -- rode o Label Engine primeiro",
        )
        return

    pooled_arr = np.array(pooled)
    pooled_frac_near_ceiling = float(np.mean(pooled_arr >= ceiling_threshold))

    logger.info(
        "diagnostics.measure_time_stop_slack.pooled_done",
        time_stop_bars=time_stop_bars,
        n_symbols_with_data=len(_SYMBOLS),
        pooled_n_resolved_tp_sl=len(pooled),
        pooled_frac_within_4_bars_of_ceiling=round(pooled_frac_near_ceiling, 4),
        **{k: round(v, 2) for k, v in _percentiles(pooled_arr).items()},
        note=(
            "leitura: se p90 << time_stop_bars, ha folga real (candidato a "
            "encurtar QUANDO a varredura 2D de tp/sl_atr_mult do Sprint 6 "
            "rodar, nao antes); se p90 proximo de time_stop_bars, o teto "
            "esta sendo pressionado de verdade e reduzir agora cortaria "
            "resolucoes legitimas. NAO decidir um novo valor so com isso "
            "-- ver docstring do modulo, restricoes 1 e 2 (ordem "
            "barreiras-antes-do-horizonte e B06)."
        ),
    )


if __name__ == "__main__":
    main()
