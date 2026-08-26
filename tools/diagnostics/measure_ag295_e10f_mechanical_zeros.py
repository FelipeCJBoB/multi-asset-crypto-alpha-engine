"""Mede, sobre dado real, o defeito de `E10f_oi_change_z_48` documentado
em `AG-295` (ficha, `veredito: ERRO_CATEGORICO`) e quantifica a correção
proposta (`group_e.e10f_oi_change_z_48_from_native_delta` +
`_sources.load_oi_change_aligned`).

**O defeito.** `e10f_oi_change_z_48` (produção, `T1_FEATURE_IDS`)
diferencia a série de Open Interest DEPOIS de alinhada à barra
(`_sources.load_oi_aligned`, que repete o último valor conhecido de OI
entre leituras da fonte, ~5 min de relógio). Sob dollar bar R1, barras
mais curtas que 5 min mapeiam pra MESMA leitura de OI via asof-join --
`Δln` entre duas barras assim dá zero por construção, não porque OI
não mudou.

**A correção proposta.** Diferenciar ANTES do alinhamento, na cadência
NATIVA da fonte (`_sources.load_oi_change_aligned`) -- elimina o zero
mecânico por construção, porque não há duas leituras nativas
consecutivas coincidindo por causa de barra curta.

Este script não decide nada -- só mede a magnitude real do problema e do
ganho da correção, pra dar base numérica à proposta (`AG-295`). Rodar com
`uv run python tools/diagnostics/measure_ag295_e10f_mechanical_zeros.py`."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import structlog

from src.features import _sources
from src.features.groups import group_e

logger = structlog.get_logger(__name__)

_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
_WINDOW = 48


def _measure_symbol(symbol: str, start: date, end: date) -> dict[str, object]:
    bars = _sources.load_bars(symbol, start, end, bar_source="dollar_r1")
    n_bars = bars.height

    # Caminho antigo (producao): alinha o NIVEL, diferencia depois.
    oi_level_aligned = _sources.load_oi_aligned(bars, symbol, start, end)
    delta_antigo = np.diff(np.log(oi_level_aligned.to_numpy()))
    z_antigo = group_e.e10f_oi_change_z_48(oi_level_aligned.to_numpy(), window=_WINDOW)

    # Caminho novo (proposta): diferencia na cadencia nativa, alinha o DELTA.
    oi_change_aligned = _sources.load_oi_change_aligned(bars, symbol, start, end)
    z_novo = group_e.e10f_oi_change_z_48_from_native_delta(
        oi_change_aligned.to_numpy(), window=_WINDOW
    )

    frac_zero_antigo = float(np.mean(delta_antigo == 0.0))
    frac_zero_novo = float(
        np.mean(oi_change_aligned.to_numpy()[1:] == 0.0)
    )  # delta real == 0.0 exato e coincidencia legitima, nao mecanica

    finite_z_antigo = z_antigo[np.isfinite(z_antigo)]
    finite_z_novo = z_novo[np.isfinite(z_novo)]

    return {
        "symbol": symbol,
        "n_bars": n_bars,
        "frac_delta_zero_antigo": round(frac_zero_antigo, 4),
        "frac_delta_zero_novo": round(frac_zero_novo, 4),
        "std_z_antigo": round(float(np.std(finite_z_antigo)), 4) if finite_z_antigo.size else None,
        "std_z_novo": round(float(np.std(finite_z_novo)), 4) if finite_z_novo.size else None,
        "frac_abs_z_acima_de_3_antigo": round(float(np.mean(np.abs(finite_z_antigo) > 3.0)), 5)
        if finite_z_antigo.size
        else None,
        "frac_abs_z_acima_de_3_novo": round(float(np.mean(np.abs(finite_z_novo) > 3.0)), 5)
        if finite_z_novo.size
        else None,
    }


def main() -> None:
    # Janela curta e recente, dentro da cobertura real de dado (ver AG-293
    # -- backfill para em 2026-08-07). 60 dias antes disso.
    end = date(2026, 8, 7)
    start = date(2026, 6, 8)

    results = [_measure_symbol(symbol, start, end) for symbol in _SYMBOLS]
    for row in results:
        logger.info("ag295.e10f_mechanical_zeros", **row)


if __name__ == "__main__":
    main()
