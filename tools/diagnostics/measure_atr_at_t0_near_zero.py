"""Mede, em `labels.parquet` JÁ PERSISTIDO (0 trials -- contagem direta,
sem sweep/retreino novo), o quão perto de zero `atr_at_t0` chega de
verdade -- pré-requisito de medição pro AG-206 (`audit/architecture_gaps_
log.yaml`) antes de decidir se um piso de volatilidade (`TBM_VOL_FLOOR`,
padrão de outro projeto de referência de Triple Barrier Method) é
justificado neste repo.

**Por que isto importa.** `tp_price`/`sl_price` (`src/labels/triple_
barrier.py`) são `fill_px * (1 ± mult * atr_at_t0)` -- um `atr_at_t0` real
(não-`NaN`, passa o filtro de warmup) mas próximo de zero produz uma
barreira patologicamente estreita (`tp_price`~`sl_price`~`fill_px`).
`ATRWilderEstimator.estimate` (`src/features/volatility.py`) não aplica
nenhum piso -- `atr_abs / close`, direto -- apesar do `Protocol
VolatilityEstimator.estimate` documentar "nunca zero" como contrato (não
enforced em código, só aspiracional). `AG-061` já confirmou candles de
dollar-bar REPETIDOS/degenerados em produção real (SOLUSDT/XRPUSDT sob
R2/R3) -- true range zero ao longo da janela de Wilder é a consequência
direta disso.

**O que este script NÃO faz.** Não decide se o piso é necessário, não
escolhe um valor de piso, não abre sweep/otimização nenhuma -- só reporta
a distribuição real de `atr_at_t0` (já uma coluna persistida) por
símbolo×grade, pros 5 símbolos × {15m, R1, R2, R3}. Decisão de
threshold/provenance do piso (se houver) é o próximo passo, fora deste
script (Regra Zero, CLAUDE.md -- não inventar número sem medir antes)."""

from __future__ import annotations

import sys
from pathlib import Path

# Script standalone (não pacote instalado) -- ver mesma nota em
# tools/diagnostics/measure_barrier_touch_probability.py (achado real
# 2026-08-16, 8 scripts de tools/diagnostics/ tinham este mesmo bug).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import polars as pl
import structlog

from src.validation.cpcv import load_labels_v1

logger = structlog.get_logger(__name__)

_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT")
_GRADES: tuple[tuple[str, str | None], ...] = (
    ("15m", None),
    ("R1", "R1"),
    ("R2", "R2"),
    ("R3", "R3"),
)
# Cortes de inspeção -- puramente descritivos (não thresholds de decisão,
# não escolhem um piso). "1e-4" == 1 bp de preço, "1e-5" == 0,1 bp -- faixa
# ampla o bastante pra ver se a cauda esquerda de atr_at_t0 é vazia ou não,
# sem presumir onde ela começaria a doer.
_INSPECTION_CUTOFFS: tuple[float, ...] = (0.0, 1e-6, 1e-5, 1e-4)  # noqa: magic-number -- cortes de inspeção descritivos deste script de medição, não constante de domínio/pipeline


def main() -> None:
    pooled_frames: list[pl.DataFrame] = []

    for symbol in _SYMBOLS:
        for grade_label, resolution_id in _GRADES:
            try:
                labels = load_labels_v1(symbol=symbol, resolution_id=resolution_id)
            except FileNotFoundError as exc:
                logger.warning(
                    "diagnostics.measure_atr_at_t0_near_zero.grade_skipped",
                    symbol=symbol,
                    grade=grade_label,
                    error=repr(exc),
                )
                continue

            atr = labels.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")["atr_at_t0"]
            n = atr.len()
            if n == 0:
                logger.warning(
                    "diagnostics.measure_atr_at_t0_near_zero.no_rows",
                    symbol=symbol,
                    grade=grade_label,
                )
                continue

            arr = atr.drop_nulls()
            # Nomes de chave FIXOS (não gerados por f-string a partir do
            # valor do corte/quantil) -- **dict em logger.info exige nomes
            # válidos de identificador; "n_below_1e-06"/"p0.1" quebrariam
            # nisso. _INSPECTION_CUTOFFS tem que continuar em ordem
            # correspondente a esta tupla, não solto.
            n_below_0, n_below_1e6, n_below_1e5, n_below_1e4 = (
                int((arr <= cutoff).sum()) for cutoff in _INSPECTION_CUTOFFS
            )
            # `or float("nan")` seria um bug real aqui, não estilo: um
            # mínimo/quantil legitimamente igual a 0.0 é EXATAMENTE o sinal
            # mais importante que este script existe pra detectar -- `0.0
            # or x` avalia pra `x` (falsy), silenciando o próprio achado.
            # Checagem explícita de `None` (só caso `arr` viesse vazio, já
            # descartado por `n == 0` acima -- defensivo, não esperado).
            atr_min = arr.min()
            q_0_1 = arr.quantile(0.001, interpolation="linear")  # noqa: magic-number -- quantil de inspeção, não constante de domínio
            q_1 = arr.quantile(0.01, interpolation="linear")  # noqa: magic-number -- idem
            q_5 = arr.quantile(0.05, interpolation="linear")  # noqa: magic-number -- idem
            q_50 = arr.quantile(0.50, interpolation="linear")
            p_0_1 = float(q_0_1) if q_0_1 is not None else float("nan")
            p_1 = float(q_1) if q_1 is not None else float("nan")
            p_5 = float(q_5) if q_5 is not None else float("nan")
            p_50 = float(q_50) if q_50 is not None else float("nan")

            logger.info(
                "diagnostics.measure_atr_at_t0_near_zero.grade_done",
                symbol=symbol,
                grade=grade_label,
                n_rows=n,
                min_atr_at_t0=(
                    float(atr_min) if atr_min is not None else float("nan")  # type: ignore[arg-type]
                ),
                p0_1=p_0_1,
                p1=p_1,
                p5=p_5,
                p50=p_50,
                n_below_0=n_below_0,
                n_below_1e_minus_6=n_below_1e6,
                n_below_1e_minus_5=n_below_1e5,
                n_below_1e_minus_4=n_below_1e4,
            )

            pooled_frames.append(
                labels.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL").select(
                    pl.lit(symbol).alias("symbol"),
                    pl.lit(grade_label).alias("grade"),
                    pl.col("atr_at_t0"),
                    pl.col("barrier_hit"),
                    pl.col("n_bars_held"),
                )
            )

    if not pooled_frames:
        logger.warning(
            "diagnostics.measure_atr_at_t0_near_zero.no_data",
            note="nenhum symbol x grade tinha labels.parquet -- rode o Label Engine primeiro",
        )
        return

    pooled = pl.concat(pooled_frames, how="vertical")
    pooled_n = pooled.height
    pooled_min = pooled["atr_at_t0"].min()  # None só se pooled vazio (pooled_n>0 garante que não)
    logger.info(
        "diagnostics.measure_atr_at_t0_near_zero.pooled_done",
        pooled_n_rows=pooled_n,
        pooled_min_atr_at_t0=(
            float(pooled_min) if pooled_min is not None else float("nan")  # type: ignore[arg-type]
        ),
        pooled_n_exactly_zero=int((pooled["atr_at_t0"] <= _INSPECTION_CUTOFFS[0]).sum()),
        pooled_n_below_1e_minus_6=int((pooled["atr_at_t0"] <= _INSPECTION_CUTOFFS[1]).sum()),
        pooled_n_below_1e_minus_5=int((pooled["atr_at_t0"] <= _INSPECTION_CUTOFFS[2]).sum()),
        pooled_n_below_1e_minus_4=int((pooled["atr_at_t0"] <= _INSPECTION_CUTOFFS[3]).sum()),
    )

    # As N linhas de menor atr_at_t0 no pool inteiro -- inspeção direta de
    # QUEM são (símbolo/grade/barrier_hit/n_bars_held), não só a contagem
    # agregada. Um n_bars_held muito baixo nessas linhas é a assinatura
    # concreta da patologia (barreira colapsada perto do fill, qualquer
    # movimento mínimo já dispara).
    bottom_n = 20
    lowest = pooled.sort("atr_at_t0").head(bottom_n)
    logger.info(
        "diagnostics.measure_atr_at_t0_near_zero.lowest_rows",
        n_inspected=min(bottom_n, pooled_n),
        rows=lowest.select("symbol", "grade", "atr_at_t0", "barrier_hit", "n_bars_held").rows(
            named=True
        ),
    )


if __name__ == "__main__":
    main()
