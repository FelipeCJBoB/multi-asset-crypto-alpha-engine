"""Distribuição de MFE (`mfe_atr_units`) por símbolo/lado -- insumo pra
V41-6 (`PRD_V4_1.md §4.1`, "recalcular tp_mult/sl_mult a partir da
distribuição de MFE, não por grid"), item 1 da rodada de 2026-08-22
(Manager: "Escreva o procedimento de derivação por MFE agora... teste-o
contra a população incondicional como validação de implementação -- não
como fonte de valor").

**Isto NÃO é a derivação em si -- é o diagnóstico que expõe a forma real
da distribuição, pra decisão informada de qual percentil usar.** Rodar
sobre a população INCONDICIONAL de `labels.parquet` é sabidamente viesado
(`PRD_V4_1.md §4.1`: "a rederivação roda sobre a população que o Alpha
dispara... a varredura da Faixa 2 foi incondicional -- erro de desenho
registrado") -- os números aqui são fixture de validação de implementação
(a lógica de percentil/agregação está correta), NUNCA um candidato a
`tp_atr_mult`/`sl_atr_mult` em `constants.yaml`. `provenance: DERIVED`
não se aplica a nada que saia deste script.

`mfe_atr_units` já é persistido por trade (`triple_barrier.py:1308`,
"melhor preço favorável até o toque, em unidades de ATR, side-ajustado" --
se `barrier_hit=="tp"`, `mfe_atr_units >= tp_atr_mult` por construção).
Não precisa recomputar nada -- só ler e agregar.

**Lado SL não tem equivalente hoje**: não existe `mae_atr_units`
(Maximum Adverse Excursion) persistido em `labels.parquet` -- a derivação
simétrica (MFE->TP, MAE->SL) não é possível com o dado que existe. Esta
lacuna fica registrada aqui, não resolvida (ver docs/s1_design_doc_
sweep_tp_sl_reward_risk_2026-08-22.md §6-bis) -- decisão de como derivar
o lado SL (adicionar mae_atr_units ao Label Engine, ou usar outro
princípio) fica pro Manager.

Rodar:
    uv run python tools/diagnostics/measure_mfe_distribution_for_barrier_derivation.py \
        --out experiments/mfe_distribution_for_barrier_derivation.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import orjson
import polars as pl
import structlog

from src.analysis.volatility_comparison import SYMBOL_START_DATE
from src.core.provenance import report_provenance
from src.data._constants import load_constant

logger = structlog.get_logger(__name__)

_PERCENTILES: Final[tuple[int, ...]] = (10, 25, 50, 75, 90, 95, 99)
_MIN_TRADES_FOR_STATS: Final[int] = 30


def _labels_path(symbol: str) -> Path:
    return _REPO_ROOT / "data" / "labels" / symbol / "15m" / "v1" / "labels.parquet"


def _mfe_stats_for_side(mfe: np.ndarray, *, tp_atr_mult_producao: float) -> dict[str, Any]:
    """Estatísticas descritivas puras -- nenhuma escolha de percentil pra
    derivação é feita aqui, só reportada pra decisão humana."""
    if mfe.shape[0] < _MIN_TRADES_FOR_STATS:
        return {"n": int(mfe.shape[0]), "not_computable": True}
    percentiles = {
        f"p{p}": float(np.percentile(mfe, p)) for p in _PERCENTILES
    }
    frac_reaches_producao = float(np.mean(mfe >= tp_atr_mult_producao))
    return {
        "n": int(mfe.shape[0]),
        "mean": float(np.mean(mfe)),
        "median": float(np.median(mfe)),
        **percentiles,
        "frac_reaches_tp_atr_mult_producao": frac_reaches_producao,
        "tp_atr_mult_producao_referencia": tp_atr_mult_producao,
    }


def measure_symbol(symbol: str, *, tp_atr_mult_producao: float) -> dict[str, Any]:
    path = _labels_path(symbol)
    df = pl.read_parquet(path)
    filled = df.filter(pl.col("barrier_hit") != "NOFILL")

    result: dict[str, Any] = {"symbol": symbol, "n_filled_total": filled.height}
    for side, side_name in ((1, "long"), (-1, "short")):
        side_df = filled.filter(pl.col("side") == side)
        mfe = side_df["mfe_atr_units"].drop_nulls().to_numpy()
        result[side_name] = _mfe_stats_for_side(mfe, tp_atr_mult_producao=tp_atr_mult_producao)

    all_mfe = filled["mfe_atr_units"].drop_nulls().to_numpy()
    result["pooled_both_sides"] = _mfe_stats_for_side(
        all_mfe, tp_atr_mult_producao=tp_atr_mult_producao
    )
    logger.info(
        "diagnostics.measure_mfe_distribution.symbol_done",
        symbol=symbol,
        n_filled=filled.height,
        median_pooled=result["pooled_both_sides"].get("median"),
        frac_reaches_producao_pooled=result["pooled_both_sides"].get(
            "frac_reaches_tp_atr_mult_producao"
        ),
    )
    return result


def measure_all(symbols: list[str]) -> dict[str, Any]:
    tp_atr_mult_producao = float(load_constant("tp_atr_mult"))
    table = {symbol: measure_symbol(symbol, tp_atr_mult_producao=tp_atr_mult_producao) for symbol in symbols}
    return {
        **report_provenance(),
        "task": "mfe_distribution_for_barrier_derivation",
        "warning": (
            "FIXTURE DE VALIDACAO DE IMPLEMENTACAO, NAO FONTE DE VALOR. "
            "Populacao incondicional (labels.parquet completo, sem filtro do "
            "Alpha) -- PRD_V4_1.md Sec4.1 registra isso como 'erro de desenho' "
            "quando usado como base de derivacao real. Nenhum numero aqui "
            "deve entrar em constants.yaml com provenance DERIVED."
        ),
        "tp_atr_mult_producao_referencia": tp_atr_mult_producao,
        "percentiles_reportados": list(_PERCENTILES),
        "mae_atr_units_disponivel": False,
        "nota_lado_sl": (
            "mae_atr_units (Maximum Adverse Excursion) nao existe persistido "
            "em labels.parquet -- derivacao simetrica MFE->TP / MAE->SL nao "
            "e possivel com o dado atual. Decisao pendente do Manager."
        ),
        "table": table,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", nargs="+", default=list(SYMBOL_START_DATE), help="default: os 5 símbolos"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Se informado, grava o resultado em JSON aqui"
    )
    args = parser.parse_args()

    result = measure_all(args.symbols)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
        logger.info("diagnostics.measure_mfe_distribution.written", out=str(args.out))

    logger.info("diagnostics.measure_mfe_distribution.summary", symbols=args.symbols)


if __name__ == "__main__":
    main()
