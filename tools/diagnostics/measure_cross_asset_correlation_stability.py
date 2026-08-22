"""Remede a correlação de log-retornos 15m entre os 5 ativos do universo
(BTC/ETH/SOL/BNB/XRP) — o número ~0,91 citado em `PRD_V4_1.md` §2.8 ("I3")
que sustenta a existência do `control_19_risco_agregado`
(`src/risk/limits.py`) e o argumento "teto simples ≈ teto ponderado por
correlação" da decisão residual §4.2 (`docs/brief_auditoria_externa_
2026-08-22_decisoes_residuais_risco_regime.md`).

**Por que remedir.** Achado `AG-144` (`audit/architecture_gaps_log.yaml`):
o valor ~0,91 nunca teve janela/período declarados na própria seção que o
cita, nunca teve entrada em `audit/evidence_ledger.yaml`, e nunca passou
pelo regime de proveniência §16.10 — nenhum `provenance`/`class`/
`review_by` próprios em `config/constants.yaml`. Autorizado pelo Manager
(2026-08-22, "§4.2 = Pode medir") como medição DESCRITIVA, 0 trials, sobre
OHLC já existente — mesma disciplina da Lente FE de `audit_engineering`
(Passo 3, FE): não abre sweep, não decide "1 controle vs. 2" sozinho, só
mede.

**O que este script mede, exatamente.** Para 4 janelas — a janela comum
histórica usada implicitamente pelo PRD (`2021-12-01` → `END_DATE`,
`src.analysis.volatility_comparison`) e 3 janelas móveis mais curtas
(últimos 90/180/365 dias corridos, terminando em `END_DATE`) — carrega
klines 15m (`src.data.lake.query_bars`, reamostrado de `klines_1m`) dos 5
símbolos, calcula log-retorno por barra, alinha os 5 símbolos por
`open_time` (inner join — só barras onde os 5 têm dado), e calcula a
matriz de correlação de Pearson 5×5 (10 pares únicos). Reporta, por
janela: `n_obs` (barras alinhadas), a matriz completa, os 10 pares
individuais, e `mean`/`min`/`max` entre os pares. Reporta também, entre as
4 janelas, o RANGE de cada par (max-min) — resposta direta à pergunta de
estabilidade que nem os 2 pareceres externos nem a síntese conseguiram
responder sem o repositório.

**O que este script NÃO faz.** Não decide se "1 controle ou 2" — só
entrega o número com proveniência. Não abre nenhum sweep/otimização. Não
altera `config/constants.yaml` nem `evidence_ledger.yaml` — a
Manager/Claude decide, depois de ver o resultado, se o valor entra lá com
`provenance: MEASURED`.

Saída: `experiments/cross_asset_correlation_stability.json` (escrita
atômica, B29).

Rodar (klines 15m reamostrados de 1m, 5 símbolos × 4 janelas — alguns
minutos esperados, só leitura de parquet + numpy, sem fit de modelo):
`uv run python tools/diagnostics/measure_cross_asset_correlation_stability.py`
"""

from __future__ import annotations

import itertools
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

# Script standalone -- mesmo padrão de measure_asof_join_open_vs_close_time_
# divergence.py (achado real AG-049): sem isto, `from src...` falha com
# ModuleNotFoundError quando invocado por caminho direto.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.analysis.volatility_comparison import END_DATE
from src.core.provenance import report_provenance
from src.data import lake

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_DEST_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "cross_asset_correlation_stability.json"
)

# Todos os 5 têm dado a partir de "2021-12-01" (BTCUSDT tem histórico mais
# longo, mas a janela COMUM entre os 5 -- a única onde uma matriz de
# correlação 5x5 é bem-definida -- começa no símbolo com início mais
# tardio; mesma leitura implícita de PRD_V4_1.md §2.8 "I3").
_SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
_COMMON_START: Final[str] = "2021-12-01"
_TF: Final[str] = "15m"


@dataclass(slots=True, frozen=True)
class _WindowResult:
    window_id: str
    start: str
    end: str
    n_obs: int
    pairs: dict[str, float]
    mean_pairwise: float
    min_pairwise: float
    max_pairwise: float
    min_pair: str
    max_pair: str


def _windows() -> list[tuple[str, str, str]]:
    end = date.fromisoformat(END_DATE)
    return [
        ("common_full", _COMMON_START, END_DATE),
        ("last_90d", (end - timedelta(days=90)).isoformat(), END_DATE),
        ("last_180d", (end - timedelta(days=180)).isoformat(), END_DATE),
        ("last_365d", (end - timedelta(days=365)).isoformat(), END_DATE),
    ]


def _load_log_returns_15m(symbol: str, start: str, end: str) -> pl.DataFrame:
    bars = lake.query_bars(symbol, tf=_TF, start=start, end=end).sort("open_time")
    return bars.select(
        pl.col("open_time"),
        (pl.col("close").log() - pl.col("close").shift(1).log()).alias(symbol),
    ).drop_nulls()


def _measure_window(window_id: str, start: str, end: str) -> _WindowResult | None:
    per_symbol = [_load_log_returns_15m(sym, start, end) for sym in _SYMBOLS]
    aligned = per_symbol[0]
    for df in per_symbol[1:]:
        aligned = aligned.join(df, on="open_time", how="inner")
    n_obs = aligned.height
    if n_obs < 2:
        logger.warning(
            "diagnostics.measure_cross_asset_correlation_stability.skip_insufficient_data",
            window_id=window_id,
            n_obs=n_obs,
        )
        return None

    ret_matrix = aligned.select(_SYMBOLS).to_numpy().astype(np.float64)  # (n_obs, 5)
    corr = np.corrcoef(ret_matrix, rowvar=False)  # (5, 5)

    pairs: dict[str, float] = {}
    for i, j in itertools.combinations(range(len(_SYMBOLS)), 2):
        key = f"{_SYMBOLS[i]}-{_SYMBOLS[j]}"
        pairs[key] = round(float(corr[i, j]), 4)

    values = list(pairs.values())
    min_pair = min(pairs, key=lambda k: pairs[k])
    max_pair = max(pairs, key=lambda k: pairs[k])

    result = _WindowResult(
        window_id=window_id,
        start=start,
        end=end,
        n_obs=n_obs,
        pairs=pairs,
        mean_pairwise=round(float(np.mean(values)), 4),
        min_pairwise=round(float(np.min(values)), 4),
        max_pairwise=round(float(np.max(values)), 4),
        min_pair=min_pair,
        max_pair=max_pair,
    )
    logger.info(
        "diagnostics.measure_cross_asset_correlation_stability.window_done",
        window_id=window_id,
        start=start,
        end=end,
        n_obs=n_obs,
        mean_pairwise=result.mean_pairwise,
        min_pair=f"{min_pair}={pairs[min_pair]}",
        max_pair=f"{max_pair}={pairs[max_pair]}",
    )
    return result


def _result_to_dict(r: _WindowResult) -> dict[str, Any]:
    return {
        "window_id": r.window_id,
        "start": r.start,
        "end": r.end,
        "n_obs": r.n_obs,
        "pairs": r.pairs,
        "mean_pairwise": r.mean_pairwise,
        "min_pairwise": r.min_pairwise,
        "max_pairwise": r.max_pairwise,
        "min_pair": r.min_pair,
        "max_pair": r.max_pair,
    }


def _stability_across_windows(results: list[_WindowResult]) -> dict[str, Any]:
    if len(results) < 2:
        return {"note": "menos de 2 janelas com dado suficiente -- estabilidade não avaliável"}
    pair_keys = list(results[0].pairs)
    ranges: dict[str, float] = {}
    for key in pair_keys:
        vals = [r.pairs[key] for r in results if key in r.pairs]
        ranges[key] = round(max(vals) - min(vals), 4) if len(vals) >= 2 else float("nan")
    return {
        "range_per_pair": ranges,
        "max_range": round(max(ranges.values()), 4) if ranges else float("nan"),
        "interpretation": (
            "range = max(corr) - min(corr) do mesmo par entre as 4 janelas. "
            "range pequeno (ex. < 0.05) sustenta tratar ~0,91 como estável; "
            "range grande sugere que o número é sensível à janela escolhida "
            "e não deveria ser citado sem a janela junto."
        ),
    }


def main() -> None:
    logger.info(
        "diagnostics.measure_cross_asset_correlation_stability.starting",
        symbols=_SYMBOLS,
        n_windows=len(_windows()),
    )

    results: list[_WindowResult] = []
    for window_id, start, end in _windows():
        r = _measure_window(window_id, start, end)
        if r is not None:
            results.append(r)

    payload: dict[str, Any] = {
        **report_provenance(),
        "measurement_provenance": (
            "MEASURED -- log-retornos 15m (src.data.lake.query_bars, "
            "reamostrado de klines_1m) dos 5 símbolos do universo, alinhados "
            "por open_time (inner join), correlação de Pearson 5x5 sobre 4 "
            "janelas (histórica comum 2021-12-01..END_DATE + 3 janelas "
            "móveis 90/180/365d). Responde AG-144 (audit/architecture_gaps_"
            "log.yaml): proveniência/janela/estabilidade do valor ~0,91 "
            "citado em PRD_V4_1.md §2.8 'I3', que sustenta control_19_"
            "risco_agregado (src/risk/limits.py) e a decisão residual §4.2 "
            "(docs/brief_auditoria_externa_2026-08-22_decisoes_residuais_"
            "risco_regime.md). Medição descritiva, 0 trials -- não decide "
            "'1 controle vs. 2' nem abre sweep."
        ),
        "symbols": list(_SYMBOLS),
        "windows": [_result_to_dict(r) for r in results],
        "stability_across_windows": _stability_across_windows(results),
    }
    dest_path = _DEST_PATH
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)

    logger.info(
        "diagnostics.measure_cross_asset_correlation_stability.done",
        n_windows=len(results),
        dest_path=str(dest_path),
    )


if __name__ == "__main__":
    main()
