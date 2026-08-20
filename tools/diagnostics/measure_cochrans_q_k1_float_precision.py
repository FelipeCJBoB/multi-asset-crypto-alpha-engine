"""Diagnóstico -- mecânica de ponto flutuante do bug k=1/df=0 em
`cochrans_q_heterogeneity` (`src/analysis/m6_common_factor_hypothesis.py`,
linhas 181-209).

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python tools/diagnostics/measure_cochrans_q_k1_float_precision.py

Achado real que motiva este script -- persistido em
`experiments/m4_critical_windows_report.json`, célula BTCUSDT /
CRYPTO_WINTER / short (side=-1), IDÊNTICO nas 3 resoluções (R1/R2/R3):

    n_buckets            = 1
    df                   = 0
    pooled_edge_bruto_atr = 0.023923992673992697
    q_statistic           = 3.85699949405511e-32   (deveria ser 0.0 exato)
    p_value               = null                    (já correto, NaN)
    i_squared_pct         = 100.0                    (deveria ser 0.0 "por
                                                       convenção", segundo
                                                       o docstring de
                                                       HeterogeneitySymbolDetail
                                                       -- virou o OPOSTO)

No dataset completo há 26 células com `n_buckets=1`; 23/26 saíram com
`q_statistic == 0.0` bit-exato (a "sorte" de w*v/w recuperar v), só esta
1 célula (replicada 3x, 1 por resolução) saiu com ruído -- ou seja, o bug
NÃO é determinístico/sempre-manifesto, é uma minoria silenciosa, o que o
torna mais perigoso (não dispara em todo teste ad-hoc, só nesta
combinação específica de w/v).

Este script tem 2 partes independentes:

  1. Reproduz o valor real acima a partir do dado real (`labels.parquet`)
     -- quando `n_buckets=1`, o único bucket cobre TODO `side_df` da
     janela (não sobrou partição nenhuma), então filtrar só por
     (symbol, window, side) já reproduz a MESMA fatia que
     `m6.stratum_metrics` viu dentro de `m4._heterogeneity_for_symbol_
     window` -- não precisa refazer nenhum fit de regime.

  2. Caracteriza a mecânica genericamente -- sweep sintético de
     magnitude/escala de `(w, v)` pra k=1 (prova que o erro é ~ordem de
     grandeza do épsilon de máquina ao quadrado, não uma coincidência de
     escala), + os 2 outros cenários degenerados citados no pedido do
     Manager (k=2 com valores idênticos, pesos extremamente
     desbalanceados) -- SEM IO, só numpy, pra confirmar/refutar se
     produzem o MESMO tipo de misfire (hipótese do relatório: NÃO
     produzem, porque `df>=1` protege via `max(0, (q-df)/q)`, só `df=0`
     não tem essa margem).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl

from src.analysis import m6_common_factor_hypothesis as m6
from src.labels.triple_barrier import LabelConfig
from src.risk._constants import load_constant as load_risk_constant
from src.validation.cpcv import load_labels_v1


def _epoch_ms(iso_date: str) -> int:
    return int(dt.datetime.fromisoformat(iso_date).replace(tzinfo=dt.UTC).timestamp() * 1000)


def part1_reproduce_real_case() -> None:
    print("=== Parte 1 -- reproduz o caso real BTCUSDT/CRYPTO_WINTER/short ===")
    symbol = "BTCUSDT"
    start_ms = _epoch_ms("2022-04-01")
    end_ms = _epoch_ms("2023-07-01")

    labels = load_labels_v1(symbol=symbol, tf="15m")
    window = labels.filter(
        (pl.col("t0").dt.epoch(time_unit="ms") >= start_ms)
        & (pl.col("t0").dt.epoch(time_unit="ms") < end_ms)
        & (pl.col("side") == -1)
    )

    cfg = LabelConfig.from_constants(tf="15m")
    maker_fee = float(load_risk_constant("maker_fee"))
    taker_fee = float(load_risk_constant("taker_fee"))

    stratum = m6.stratum_metrics(
        window,
        symbol=symbol,
        side=-1,
        regime="ALL_ONE_BUCKET_DIAGNOSTICO",
        tp_atr_mult=cfg.tp_atr_mult,
        sl_atr_mult=cfg.sl_atr_mult,
        maker_fee=maker_fee,
        taker_fee=taker_fee,
    )
    print(f"n={stratum.n}  frac_tp={stratum.frac_tp!r}  frac_sl={stratum.frac_sl!r}")
    print(f"edge_bruto_atr={stratum.edge_bruto_atr!r}")
    print(f"edge_bruto_atr_se={stratum.edge_bruto_atr_se!r}")
    print("esperado (persistido em experiments/m4_critical_windows_report.json):")
    print("  n_obs_total=8736, pooled_edge_bruto_atr=0.023923992673992697")

    het = m6.cochrans_q_heterogeneity((stratum,))
    print(f"\npooled={het.pooled_edge_bruto_atr!r}")
    print(f"q_statistic={het.q_statistic!r}")
    print(f"df={het.df}  p_value={het.p_value!r}")
    print(f"i_squared_pct={het.i_squared_pct!r}")
    print(
        "pooled == stratum.edge_bruto_atr (comparação bit-exata)? "
        f"{het.pooled_edge_bruto_atr == stratum.edge_bruto_atr}"
    )
    print("esperado (persistido): q_statistic=3.85699949405511e-32, i_squared_pct=100.0")
    print(
        "\nSE bater: confirma que a mecânica é exatamente "
        "fl(fl(w*v)/w) != v pra este w/v reais, nada mais exótico."
    )


def part2_generic_mechanism() -> None:
    print("\n\n=== Parte 2 -- mecânica genérica (sem IO) ===")

    print("\n-- 2a. k=1, w=1/se^2 variando escala de se, v = edge real fixo --")
    v = 0.023923992673992697
    for se in (1e-2, 1e-3, 1e-4, 1e-5, 5e-4, 3.7e-4, 2.71828e-3):
        w = 1.0 / (se**2)
        weights = np.array([w])
        values = np.array([v])
        pooled = float(np.sum(weights * values) / np.sum(weights))
        q = float(np.sum(weights * (values - pooled) ** 2))
        exact = pooled == v
        print(
            f"  se={se!r:>10}  w={w:.6e}  pooled==v exato? {str(exact):5}  "
            f"pooled-v={pooled - v!r}  q={q!r}"
        )
    print(
        "  -- hipótese do relatório: q, quando != 0, fica na ordem de "
        "w * v^2 * (2*u)^2 (u=2^-53), i.e. ruído de ULP, nunca sinal real."
    )

    print("\n-- 2b. controle -- k=1, w = 2**20 (potência de 2 exata) --")
    w_pow2 = float(2**20)
    weights = np.array([w_pow2])
    values = np.array([v])
    pooled_pow2 = float(np.sum(weights * values) / np.sum(weights))
    print(
        f"  pooled==v exato? {pooled_pow2 == v} "
        "(esperado True -- multiplicar/dividir por potência de 2 só desloca "
        "o expoente, sem arredondamento -- confirma que o bug É de "
        "arredondamento genérico, não universal a QUALQUER w)"
    )

    print("\n-- 2c. k=2, valores IDÊNTICOS bit-a-bit, pesos variando --")
    v2 = np.array([0.0239239926, 0.0239239926])
    for se_pair in ((0.001, 0.001), (0.0001, 0.05), (1e-6, 1e-2)):
        w2 = 1.0 / (np.array(se_pair) ** 2)
        pooled2 = float(np.sum(w2 * v2) / np.sum(w2))
        q2 = float(np.sum(w2 * (v2 - pooled2) ** 2))
        df2 = 1
        i2 = max(0.0, (q2 - df2) / q2) * 100.0 if q2 > 0 else 0.0
        print(f"  se={se_pair}  pooled==v[0] exato? {pooled2 == v2[0]}  q={q2!r}  i2%={i2!r}")
    print(
        "  -- hipótese do relatório: mesmo se q2 sair > 0 por ruído, "
        "df=1 (k=2) domina qualquer q na casa de 1e-30, "
        "max(0,(q-1)/q) fica MUITO negativo -> clipado a 0% -- "
        "SEM misfire, ao contrário do caso k=1/df=0."
    )

    print("\n-- 2d. k=2, pesos extremamente desbalanceados (SE 1e-6 vs 1e-1) --")
    v3 = np.array([0.02, 0.05])  # valores DIFERENTES -- heterogeneidade real, não ruído
    se3 = np.array([1e-6, 1e-1])
    w3 = 1.0 / (se3**2)
    pooled3 = float(np.sum(w3 * v3) / np.sum(w3))
    q3 = float(np.sum(w3 * (v3 - pooled3) ** 2))
    print(f"  w3={w3}")
    print(f"  pooled={pooled3!r}  (esperado ~= v[0]=0.02, estrato 2 quase não move a média)")
    print(f"  q={q3!r}  (checar magnitude -- overflow/cancelamento visível ou não)")


if __name__ == "__main__":
    part1_reproduce_real_case()
    part2_generic_mechanism()
