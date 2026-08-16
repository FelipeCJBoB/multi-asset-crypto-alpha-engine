"""GRUPO A — Preço e retorno (§2.2). Escopo T1 do Sprint 4: A05, A13.

Ambíguidade de notação do PRD resolvida por análise dimensional (reportada
no relatório do Sprint 4, não silenciada): a tabela §2.2 usa o mesmo rótulo
`ATR_20` nas fórmulas de A05 e A13, mas eles não podem ser a mesma
quantidade:

* **A05** `ln(C_t/C_{t−4}) / (ATR_20 × 2)` — o numerador (log-retorno) é
  adimensional, então o denominador precisa ser adimensional também: é
  `atr_20_pct` (fração do preço, §2.4 C02), não o ATR em dólares. Dividir
  por ATR em dólares (~centenas) produziria um número da ordem de 1e-5,
  incompatível de escala com o resto do vetor T1.
* **A13** `(C_t − EMA_48) / ATR_20` — o numerador está em unidade de preço
  (dólares), então o denominador precisa estar na mesma unidade: é o ATR
  absoluto (§2.4 C01), não `atr_20_pct`. Dividir por uma fração (~0,003)
  produziria um número da ordem de 1e5.

Confirmado numericamente contra a tabela §0.4 (ATR mediano 15m = 0,305%
≈ US$ 198 a US$ 65.000): A05 com `atr_20_pct` dá uma feature O(1); A13 com
ATR absoluto dá uma feature O(1) a O(10) ("distância em unidades de ATR").
As combinações trocadas dão ordens de grandeza absurdas — não é uma escolha
estética, é a única leitura que faz a feature ter escala utilizável.
"""

from __future__ import annotations

import numpy as np

from ..support import FloatArray


def a05_ret_vol_norm_4(close: FloatArray, atr_20_pct: FloatArray, lookback_bars: int) -> FloatArray:
    """`ln(C_t/C_{t-lookback_bars}) / (atr_20_pct × 2)` — §2.2 A05."""
    n = close.shape[0]
    log_ret = np.full(n, np.nan, dtype=np.float64)
    if n > lookback_bars:
        log_ret[lookback_bars:] = np.log(close[lookback_bars:] / close[:-lookback_bars])
    # 2.0 = feature_a05_vol_norm_divisor em config/constants.yaml (AG-027,
    # 2026-08-15) -- valor ASSUMED, propósito não documentado em lugar
    # nenhum encontrado; não lido dinamicamente ainda (ver ressalva de
    # escopo na entrada do yaml).
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = log_ret / (atr_20_pct * 2.0)  # noqa: magic-number -- ver comentário acima
    return out


def a13_dist_ema48_atr(close: FloatArray, ema_48: FloatArray, atr_20_abs: FloatArray) -> FloatArray:
    """`(C_t − EMA_48) / ATR_20` (absoluto) — §2.2 A13."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = (close - ema_48) / atr_20_abs
    return out
