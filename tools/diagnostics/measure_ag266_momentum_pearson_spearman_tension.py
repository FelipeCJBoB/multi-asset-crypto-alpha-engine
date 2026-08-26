"""Isola a tensão Pearson-vs-Spearman deixada em pé por `AG-266` (§7/§8
item 5 do `ADR-005`): a autocorrelação de PEARSON do retorno de BNB é
`+0,0009` (nula), mas o IC de SPEARMAN de `A01` (retorno de 1 barra
defasado) contra o retorno seguinte é `~+0,017` e consistente por
quartil. Divergirem nessa direção significa relação no CORPO da
distribuição com caudas que a cancelam — compatível tanto com
microestrutura real quanto com efeito de discretização não isolado.

**O que este script mede, sem decidir nada:**
1. Reproduz os dois números (Pearson/Spearman, amostra cheia) por símbolo/
   R1, pra confirmar que a tensão citada em `AG-266` é reproduzível aqui.
2. Pearson com corte progressivo de cauda (por percentil de `|A01|`) —
   testa DIRETAMENTE a hipótese "caudas cancelam": se Pearson converge
   pra perto do Spearman conforme a cauda é cortada, a hipótese tem
   suporte; se não converge, não tem.
3. Retorno seguinte médio por decil de `A01` — revela se a relação é
   monotônica no corpo (suporte a momentum real) ou dominada por poucos
   decis extremos.
4. Curtose/assimetria do retorno — quantifica quão pesada é a cauda.
5. Contribuição de cada observação ao numerador de Pearson
   (`(A01-média)(fwd-média)`) — quantas observações, e de que sinal,
   dominam a soma.
6. Discretização: fração de `A01`/retorno-seguinte exatamente zero.

Núcleo puro (Idioma A) nas funções `_pearson`/`_trimmed_pearson`/
`_decile_means`/`_contribution_decomposition` — recebem arrays, devolvem
números. A casca (`_measure_symbol`/`main`) resolve símbolo/dado real.
Rodar com `uv run python tools/diagnostics/
measure_ag266_momentum_pearson_spearman_tension.py`."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import polars as pl
import structlog
from scipy.stats import kurtosis, skew

from src.analysis.ic_by_horizon import forward_log_return, spearman_ic
from src.features import _sources
from src.features.groups import group_a
from src.labels.backfill_multi_symbol import END_DATE, SYMBOL_START_DATE

logger = structlog.get_logger(__name__)

EXPERIMENTS_DIR: Final[Path] = Path("experiments")

#: BNB/XRP são o alvo explícito de `§8` item 5 do ADR-005 ("isolar o
#: momentum de BNB/XRP"); BTC/ETH/SOL entram como referência de contraste
#: (BTC tem a autocorrelação de Pearson mais negativa medida em AG-266,
#: -0,0122 -- útil pra ver se o padrão de convergência é exclusivo de
#: BNB/XRP ou geral).
_SYMBOLS: tuple[str, ...] = ("BNBUSDT", "XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")

#: Percentis de corte de cauda testados (por `|A01|`, simétrico) -- inclui
#: 0 (amostra cheia, reproduz o número citado em AG-266).
_TRIM_FRACTIONS: tuple[float, ...] = (0.0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.10)

_N_DECILES: Final[int] = 10
_TOP_K_CONTRIBUTORS: Final[int] = 20


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    """Pearson simples sobre um par de arrays já sem NaN. `NaN` se
    qualquer lado for constante (correlação indefinida, não zero)."""
    if x.shape[0] < 2 or float(x.std()) == 0.0 or float(y.std()) == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _trimmed_pearson(
    a01: np.ndarray, fwd: np.ndarray, trim_frac: float
) -> tuple[float, int]:
    """Pearson após remover, simetricamente, a fração `trim_frac` das
    observações com maior `|a01|` (a variável PREDITORA, não o alvo --
    cortar pelo alvo seria olhar o futuro pra decidir o corte). Devolve
    `(pearson, n_retido)`.

    `trim_frac=0.0` é a amostra cheia (sem corte)."""
    n = a01.shape[0]
    if trim_frac <= 0.0:
        return _pearson(a01, fwd), n
    k = round(n * trim_frac)
    if k <= 0 or n - k < _N_DECILES:
        return float("nan"), 0
    # `order` é crescente por |a01| -- as últimas `k` posições são as mais
    # extremas; ficam de fora do subconjunto retido.
    order = np.argsort(np.abs(a01))
    keep = order[: n - k]
    return _pearson(a01[keep], fwd[keep]), int(keep.shape[0])


def _decile_means(a01: np.ndarray, fwd: np.ndarray, n_deciles: int) -> list[dict[str, Any]]:
    """Retorno seguinte médio/mediano por decil de `A01` -- revela se a
    relação é monotônica no corpo ou dominada por decis extremos."""
    order = np.argsort(a01)
    n = a01.shape[0]
    edges = np.linspace(0, n, n_deciles + 1, dtype=int)
    out: list[dict[str, Any]] = []
    for i in range(n_deciles):
        idx = order[edges[i] : edges[i + 1]]
        if idx.shape[0] == 0:
            continue
        a01_slice = a01[idx]
        fwd_slice = fwd[idx]
        out.append(
            {
                "decil": i + 1,
                "n": int(idx.shape[0]),
                "a01_medio": round(float(a01_slice.mean()), 6),
                "fwd_medio": round(float(fwd_slice.mean()), 6),
                "fwd_mediano": round(float(np.median(fwd_slice)), 6),
            }
        )
    return out


def _contribution_decomposition(
    a01: np.ndarray, fwd: np.ndarray, top_k: int
) -> dict[str, Any]:
    """Decompõe o numerador de Pearson, `Σ (a01-média)(fwd-média)`, por
    observação -- quantifica se um punhado de pontos extremos domina a
    soma (e em que sinal) ou se a contribuição é difusa."""
    a01_c = a01 - a01.mean()
    fwd_c = fwd - fwd.mean()
    contrib = a01_c * fwd_c
    total = float(contrib.sum())
    order = np.argsort(np.abs(contrib))[::-1]
    top_idx = order[:top_k]
    top_sum = float(contrib[top_idx].sum())
    n = a01.shape[0]
    frac_denom = total if total != 0.0 else float("nan")
    return {
        "n_total": int(n),
        "soma_total_numerador": total,
        "top_k": int(top_k),
        "soma_top_k": top_sum,
        "frac_top_k_da_soma_total": round(top_sum / frac_denom, 4)  # noqa: unguarded-ratio -- guarda de np.isfinite/!=0.0 no ternário logo abaixo, mesma expressão
        if np.isfinite(frac_denom) and frac_denom != 0.0
        else None,
        "sinal_top_k_igual_ao_total": bool(np.sign(top_sum) == np.sign(total))
        if total != 0.0
        else None,
        "n_top_k_positivos": int(np.sum(contrib[top_idx] > 0)),
        "n_top_k_negativos": int(np.sum(contrib[top_idx] < 0)),
    }


def _measure_symbol(symbol: str) -> dict[str, Any]:
    start = SYMBOL_START_DATE[symbol]
    bars = _sources.load_bars(symbol, start, END_DATE, bar_source="dollar_r1")
    # AG-264 -- mesma dedupe de open_time (maior close_time) usada por
    # ic_by_horizon.py, pra não computar retorno sobre barra residual de
    # duração zero.
    bars_dedup = bars.sort(["open_time", "close_time"]).unique(
        subset=["open_time"], keep="last", maintain_order=True
    )
    close = bars_dedup["close"].cast(pl.Float64).to_numpy().astype(np.float64)

    a01 = group_a.a01_log_return_1(close, lag_bars=1)
    fwd = forward_log_return(close, horizon_bars=1)

    valid = np.isfinite(a01) & np.isfinite(fwd)
    n_valid = int(valid.sum())
    a01_v = a01[valid]
    fwd_v = fwd[valid]

    pearson_full = _pearson(a01_v, fwd_v)
    spearman_full = spearman_ic(a01_v, fwd_v)

    trims = []
    for frac in _TRIM_FRACTIONS:
        p, n_ret = _trimmed_pearson(a01_v, fwd_v, frac)
        trims.append(
            {
                "trim_frac": frac,
                "n_retido": n_ret,
                "pearson": round(p, 6) if np.isfinite(p) else None,
            }
        )

    deciles = _decile_means(a01_v, fwd_v, _N_DECILES)
    contrib = _contribution_decomposition(a01_v, fwd_v, _TOP_K_CONTRIBUTORS)

    frac_a01_zero = float(np.mean(a01_v == 0.0))
    frac_fwd_zero = float(np.mean(fwd_v == 0.0))

    return {
        "symbol": symbol,
        "n_bars": bars_dedup.height,
        "n_valid_pares": n_valid,
        "pearson_amostra_cheia": round(pearson_full, 6) if np.isfinite(pearson_full) else None,
        "spearman_amostra_cheia": round(spearman_full, 6)
        if np.isfinite(spearman_full)
        else None,
        "curtose_excesso_a01": round(float(kurtosis(a01_v, fisher=True)), 3),
        "assimetria_a01": round(float(skew(a01_v)), 4),
        "frac_a01_exatamente_zero": round(frac_a01_zero, 5),
        "frac_fwd_exatamente_zero": round(frac_fwd_zero, 5),
        "pearson_por_corte_de_cauda": trims,
        "retorno_seguinte_por_decil_de_a01": deciles,
        "decomposicao_contribuicao_numerador": contrib,
    }


def main() -> None:
    results = [_measure_symbol(symbol) for symbol in _SYMBOLS]
    for r in results:
        logger.info(
            "ag266_momentum_tension.medido",
            symbol=r["symbol"],
            pearson=r["pearson_amostra_cheia"],
            spearman=r["spearman_amostra_cheia"],
            curtose=r["curtose_excesso_a01"],
        )
    payload = {"symbols": results}
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / "ag266_momentum_pearson_spearman_tension_report.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(out_path)
    logger.info("ag266_momentum_tension.persistido", path=str(out_path))


if __name__ == "__main__":
    main()
