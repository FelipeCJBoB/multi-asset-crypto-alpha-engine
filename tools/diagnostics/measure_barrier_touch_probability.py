"""Mede a probabilidade EMPÍRICA real de qual barreira toca primeiro
(TP vs SL) em `labels.parquet`, pros 5 ativos -- primeira aplicação
concreta da lente FE (Falha de Especificação Econômica,
`.claude/skills/audit_engineering/SKILL.md`, pergunta 2) e resposta
direta ao achado AG-027.

`src.features.groups.group_e.round_trip_cost_bps` assume P(TP
primeiro)=P(SL primeiro)=0,5 ao estimar o custo esperado de round-trip
que alimenta a feature `E27f_cost_atr_ratio`. Achado de auditoria
(2026-08-15, verificado por rederivação matemática independente): sob
aproximação de ruína do apostador (caminhante aleatório simétrico sem
drift, 2 barreiras absorventes a distâncias `sl_atr_mult`/`tp_atr_mult`
do preço de entrada), P(SL primeiro) = tp_atr_mult/(tp_atr_mult+
sl_atr_mult) ≈ 57,1% -- não 50%, porque a barreira mais PRÓXIMA (SL,
1,5×ATR) tem mais chance de ser tocada primeiro que a mais distante (TP,
2,0×ATR) sob um passeio simétrico. Isso é só a aproximação de 1ª ordem
(sem drift/skew/curtose real do retorno cripto) -- este script mede a
proporção EMPÍRICA real, direto do resultado já simulado pelo Label
Engine (`barrier_hit` em `labels.parquet`), sem nenhum experimento novo.

Rodar depois que `data/labels/{symbol}/15m/v1/labels.parquet` existir
pro(s) símbolo(s) de interesse (já existe pra BTCUSDT/ETHUSDT/BNBUSDT/
XRPUSDT/SOLUSDT, confirmado no Road Map Vivo)."""

from __future__ import annotations

import math

import structlog

from src.data._constants import load_constant as load_data_constant
from src.validation.cpcv import load_labels_v1

logger = structlog.get_logger(__name__)

_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT")


def _gambler_ruin_p_sl_first(tp_atr_mult: float, sl_atr_mult: float) -> float:
    """Aproximação de 1ª ordem (ruína do apostador, passeio simétrico sem
    drift, 2 barreiras absorventes): P(barreira mais próxima tocar
    primeiro) = distância_da_OUTRA / soma_das_distâncias."""
    return tp_atr_mult / (tp_atr_mult + sl_atr_mult)  # noqa: unguarded-ratio -- validado no __post_init__ de LabelConfig (ambos >0)


def main() -> None:
    tp_atr_mult = float(load_data_constant("tp_atr_mult"))
    sl_atr_mult = float(load_data_constant("sl_atr_mult"))
    maker_fee = float(load_data_constant("maker_fee"))
    taker_fee = float(load_data_constant("taker_fee"))

    p_sl_first_theory = _gambler_ruin_p_sl_first(tp_atr_mult, sl_atr_mult)
    p_tp_first_theory = 1.0 - p_sl_first_theory
    cost_bps_assumed_5050 = (maker_fee + 0.5 * maker_fee + 0.5 * taker_fee) * 10_000
    cost_bps_theory = (
        maker_fee + p_tp_first_theory * maker_fee + p_sl_first_theory * taker_fee
    ) * 10_000

    logger.info(
        "diagnostics.measure_barrier_touch_probability.theory",
        tp_atr_mult=tp_atr_mult,
        sl_atr_mult=sl_atr_mult,
        p_tp_first_gambler_ruin=round(p_tp_first_theory, 4),
        p_sl_first_gambler_ruin=round(p_sl_first_theory, 4),
        cost_bps_assumed_5050=round(cost_bps_assumed_5050, 3),
        cost_bps_gambler_ruin=round(cost_bps_theory, 3),
    )

    pooled_tp = 0
    pooled_sl = 0
    pooled_time = 0
    pooled_nofill = 0

    for symbol in _SYMBOLS:
        try:
            labels = load_labels_v1(symbol=symbol)
        except FileNotFoundError as exc:
            logger.warning(
                "diagnostics.measure_barrier_touch_probability.symbol_skipped",
                symbol=symbol,
                error=repr(exc),
            )
            continue

        counts = labels["barrier_hit"].value_counts()
        by_barrier = dict(zip(counts["barrier_hit"].cast(str), counts["count"], strict=True))
        n_tp = int(by_barrier.get("TP", 0))
        n_sl = int(by_barrier.get("SL", 0))
        n_time = int(by_barrier.get("TIME", 0))
        n_nofill = int(by_barrier.get("NOFILL", 0))
        n_tp_or_sl = n_tp + n_sl

        pooled_tp += n_tp
        pooled_sl += n_sl
        pooled_time += n_time
        pooled_nofill += n_nofill

        if n_tp_or_sl == 0:
            logger.warning(
                "diagnostics.measure_barrier_touch_probability.no_tp_sl",
                symbol=symbol,
                n_time=n_time,
                n_nofill=n_nofill,
            )
            continue

        p_tp_empirical = n_tp / n_tp_or_sl  # noqa: unguarded-ratio -- guardado por n_tp_or_sl==0 acima
        p_sl_empirical = n_sl / n_tp_or_sl  # noqa: unguarded-ratio -- idem
        cost_bps_empirical = (
            maker_fee + p_tp_empirical * maker_fee + p_sl_empirical * taker_fee
        ) * 10_000
        # erro padrão de uma proporção binomial -- quão preciso é este n
        se = math.sqrt(p_tp_empirical * p_sl_empirical / n_tp_or_sl)  # noqa: unguarded-ratio -- n_tp_or_sl>0 acima

        logger.info(
            "diagnostics.measure_barrier_touch_probability.symbol_done",
            symbol=symbol,
            n_tp=n_tp,
            n_sl=n_sl,
            n_time=n_time,
            n_nofill=n_nofill,
            p_tp_empirical=round(p_tp_empirical, 4),
            p_sl_empirical=round(p_sl_empirical, 4),
            p_tp_empirical_se=round(se, 4),
            cost_bps_empirical=round(cost_bps_empirical, 3),
            cost_bps_assumed_5050=round(cost_bps_assumed_5050, 3),
            cost_bps_gambler_ruin_theory=round(cost_bps_theory, 3),
        )

    pooled_n = pooled_tp + pooled_sl
    if pooled_n > 0:
        p_tp_pooled = pooled_tp / pooled_n  # noqa: unguarded-ratio -- guardado por pooled_n>0 acima
        p_sl_pooled = pooled_sl / pooled_n  # noqa: unguarded-ratio -- idem
        cost_bps_pooled = (
            maker_fee + p_tp_pooled * maker_fee + p_sl_pooled * taker_fee
        ) * 10_000
        logger.info(
            "diagnostics.measure_barrier_touch_probability.pooled_done",
            n_symbols_with_data=len(_SYMBOLS),
            pooled_n_tp=pooled_tp,
            pooled_n_sl=pooled_sl,
            pooled_n_time=pooled_time,
            pooled_n_nofill=pooled_nofill,
            p_tp_pooled=round(p_tp_pooled, 4),
            p_sl_pooled=round(p_sl_pooled, 4),
            cost_bps_pooled_empirical=round(cost_bps_pooled, 3),
            cost_bps_assumed_5050=round(cost_bps_assumed_5050, 3),
            cost_bps_gambler_ruin_theory=round(cost_bps_theory, 3),
            note=(
                "se cost_bps_pooled_empirical divergir de cost_bps_assumed_5050 "
                "na mesma direcao/magnitude que cost_bps_gambler_ruin_theory, "
                "AG-027 esta confirmado empiricamente -- proximo passo e' "
                "propor o valor corrigido de round_trip_cost_bps ao Manager, "
                "nao editar o codigo sozinho (Regra Zero -- numero medido, "
                "nao otimizado de volta)"
            ),
        )
    else:
        logger.warning(
            "diagnostics.measure_barrier_touch_probability.no_data",
            note="nenhum símbolo tinha labels.parquet -- rode o Label Engine primeiro",
        )


if __name__ == "__main__":
    main()
