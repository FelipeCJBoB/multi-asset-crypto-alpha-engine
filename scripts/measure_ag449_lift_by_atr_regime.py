"""AG-449 — o lift do modelo sobrevive no regime de ATR alto?

A dissecação do `AG-449` (2026-09-05) trocou a pergunta. "O vetor de
features discrimina?" tem resposta MEDIDA e é **sim, pouco**:

    win rate INCONDICIONAL (todos os trades preenchidos)   50,78%
      -- constante em 0,04pp entre 3 ativos e 2 grades
    win rate CONDICIONAL out-of-time (walk-forward)        +1,25pp de lift
    win rate CONDICIONAL in-fold (CPCV)                    +2,96pp de lift
    breakeven exigido pelo custo                           53,06% a 57,14%

O breakeven é função do ATR (custo é ~fixo em bps, a barreira escala com a
volatilidade), e cai de 63,4% no decil 1 de ATR para 51,8% no decil 10.
A win rate INCONDICIONAL, medida por decil de ATR, NÃO sobe junto: fica em
50,4-51,1% em todos os decis de todos os combos. Logo o gap incondicional
nunca fecha sozinho -- no melhor decil ainda faltam 1,1pp.

**A pergunta que este script responde, e que nenhuma medição anterior
cobre**: o LIFT do modelo (a parte que não é incondicional) se mantém no
decil alto de ATR? Se mantiver, a conta fecha por regime sem exigir feature
nova:

    decil 10 de ATR:  breakeven ~52,2%  |  incondicional 50,8% + lift 1,25pp
                      = 52,05%  -> a ~0,15pp de viabilidade

Se o lift DESAPARECER em ATR alto (hipótese oposta e igualmente plausível:
volatilidade alta = mais ruído = modelo discrimina pior), a alavanca não
existe e o `AG-449` fica onde está.

**Por que precisa de execução própria**: `run_walk_forward_campaign` não
expõe `keep_predictions`, e sem as predições não dá pra cruzar o trade
SELECIONADO com o `atr_at_t0` da barra. O artefato canônico grava
`predictions=None` por desenho (não guarda dado por trade).

NÃO altera nada em disco de produção: escreve só
`experiments/ag449_lift_by_atr_regime.json`.

Uso:

    uv run python -m scripts.measure_ag449_lift_by_atr_regime
"""

from __future__ import annotations

import json
import sys
from typing import Any

import numpy as np
import polars as pl
import structlog

from src.analysis.feasibility import breakeven_win_rate
from src.models import alpha, dataset, hyperparams_by_combo
from src.models import walk_forward as wf
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_COMBOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)

#: Terços, não decis. Decil sobre os trades SELECIONADOS deixaria ~30-80
#: trades por balde em vários folds -- abaixo do piso de 10 que o próprio
#: projeto já usa pra Sharpe/win-rate ter sentido (`alpha.
#: MIN_OCCURRENCES_ABOVE_TAU`), e a leitura viraria ruído de bucket. Terço
#: preserva n por balde na casa das centenas/milhares.
_N_BUCKETS: int = 3

#: Piso de trades por (combo, balde) pra reportar win rate. Mesmo valor e
#: mesmo motivo de `alpha.MIN_OCCURRENCES_ABOVE_TAU`, reusado em vez de
#: reinventado -- balde abaixo disso entra no JSON com `win_rate: null`,
#: nunca com um número que não se sustenta.
_MIN_TRADES_POR_BALDE: int = 30  # noqa: magic-number -- ver comentário acima


def _predicoes_do_combo(symbol: str, resolution_id: str) -> pl.DataFrame:
    """Roda o walk-forward do combo com `keep_predictions=True` e devolve
    as predições de TODOS os folds concatenadas, já filtradas aos trades
    REALIZADOS (o que o gate Alpha mede)."""
    # Mesma construcao do `run_walk_forward_campaign` -- reusada, nao
    # reinventada: `vol_estimator_id` explicito (obrigatorio sob dollar
    # bar) e `hyper` do override de producao, pra que esta medicao rode
    # sobre EXATAMENTE o modelo que o gate avalia.
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
    mf = dataset.build_modeling_frame(
        symbol=symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
    )
    hyper = hyperparams_by_combo.load_production_override(
        symbol, resolution_id, alpha.VARIANT_CAMADA1
    )
    if hyper is None:
        raise ValueError(
            f"{symbol}/{resolution_id} sem entrada em "
            "alpha_production_hyperparam_override -- esperado presente pros 5 candidatos"
        )
    res = wf.run_walk_forward_for_combo(
        mf.data,
        symbol=symbol,
        resolution_id=resolution_id,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=int(load_constant("alpha_random_seed")),
        keep_predictions=True,
    )
    partes: list[pl.DataFrame] = []
    for fold in res.fold_results:
        pred = fold.predictions
        if pred is None or pred.is_empty():
            continue
        partes.append(pred.with_columns(pl.lit(fold.fold_id).alias("fold_id")))
    if not partes:
        return pl.DataFrame()
    return pl.concat(partes, how="diagonal")


def _medir_combo(symbol: str, resolution_id: str) -> dict[str, Any]:
    mk = float(load_constant("maker_fee"))
    tk = float(load_constant("taker_fee"))
    adv = float(load_constant("adverse_selection_bps"))
    tp = float(load_constant("tp_atr_mult"))
    sl = float(load_constant("sl_atr_mult"))

    labels = pl.read_parquet(
        f"data/labels/{symbol}/{resolution_id}/v1/labels.parquet"
    ).filter(pl.col("barrier_hit") != "NOFILL")

    pred = _predicoes_do_combo(symbol, resolution_id)
    if pred.is_empty():
        logger.warning("ag449.sem_predicoes", symbol=symbol, resolution_id=resolution_id)
        return {"symbol": symbol, "resolution_id": resolution_id, "erro": "sem predicoes"}

    # `predictions` traz TODA barra de teste, com `side_hat` = 0 onde o
    # modelo nao disparou. O gate Alpha mede so o que ele DISPAROU, entao o
    # filtro `side_hat != 0` e o que separa "populacao de inferencia" de
    # "trade selecionado" -- sem ele, condicional e incondicional seriam a
    # mesma coisa e o lift daria zero por construcao.
    pred_sinal = pred.filter(pl.col("side_hat") != 0).with_columns(
        pl.col("side_hat").cast(pl.Int8).alias("side")
    )
    if pred_sinal.is_empty():
        return {"symbol": symbol, "resolution_id": resolution_id, "erro": "nenhum sinal"}

    sel = pred_sinal.join(
        labels.select(["t0", "side", "atr_at_t0", "barrier_hit", "ret_net"]),
        on=["t0", "side"],
        how="inner",
    )
    # Só trades REALIZADOS: é a população que o gate Alpha mede.
    sel = sel.filter(pl.col("barrier_hit").is_in(["TP", "SL", "TIME"]))
    if sel.is_empty():
        return {"symbol": symbol, "resolution_id": resolution_id, "erro": "join vazio"}

    atr_todos = labels["atr_at_t0"].to_numpy()
    cortes = np.quantile(atr_todos, [i / _N_BUCKETS for i in range(1, _N_BUCKETS)])

    def _balde(a: np.ndarray) -> np.ndarray:
        return np.asarray(np.digitize(a, cortes))

    y_inc = (labels["barrier_hit"] == "TP").to_numpy().astype(float)
    b_inc = _balde(atr_todos)

    atr_sel = sel["atr_at_t0"].to_numpy()
    y_sel = (sel["barrier_hit"] == "TP").to_numpy().astype(float)
    ret_sel = sel["ret_net"].to_numpy()
    b_sel = _balde(atr_sel)

    baldes: list[dict[str, Any]] = []
    for k in range(_N_BUCKETS):
        mi = b_inc == k
        ms = b_sel == k
        n_sel = int(ms.sum())
        atr_med = float(np.median(atr_todos[mi])) if mi.sum() else float("nan")
        be = (
            breakeven_win_rate(
                atr_pct=atr_med,
                tp_atr_mult=tp,
                sl_atr_mult=sl,
                maker_fee=mk,
                taker_fee=tk,
                adverse_selection_bps=adv,
            )
            if np.isfinite(atr_med) and atr_med > 0
            else float("nan")
        )
        wr_inc = float(y_inc[mi].mean()) if mi.sum() else float("nan")
        # Piso explícito: balde raso entra como `null`, nunca como número
        # que não se sustenta (B23 -- não inventar precisão que o n não dá).
        wr_sel = float(y_sel[ms].mean()) if n_sel >= _MIN_TRADES_POR_BALDE else float("nan")
        lift = wr_sel - wr_inc if np.isfinite(wr_sel) else float("nan")
        baldes.append(
            {
                "balde": k + 1,
                "atr_mediano": atr_med,
                "n_incondicional": int(mi.sum()),
                "n_selecionado": n_sel,
                "win_rate_incondicional": wr_inc,
                "win_rate_selecionada": None if not np.isfinite(wr_sel) else wr_sel,
                "lift_pp": None if not np.isfinite(lift) else lift * 100.0,
                "breakeven": be,
                "gap_selecionada_menos_breakeven_pp": (
                    None if not np.isfinite(wr_sel) else (wr_sel - be) * 100.0
                ),
                "ret_net_medio_bps": (
                    float(ret_sel[ms].mean()) * 1e4 if n_sel else None
                ),
            }
        )

    return {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_trades_selecionados": int(sel.height),
        "n_trades_incondicionais": int(labels.height),
        "baldes": baldes,
    }


def main(argv: list[str] | None = None) -> int:
    configure_logging(json_output=False)
    resultados = []
    for symbol, resolution_id in _COMBOS:
        logger.info("ag449.combo_inicio", symbol=symbol, resolution_id=resolution_id)
        r = _medir_combo(symbol, resolution_id)
        resultados.append(r)
        logger.info(
            "ag449.combo_fim",
            symbol=symbol,
            resolution_id=resolution_id,
            erro=r.get("erro"),
            n_sel=r.get("n_trades_selecionados"),
        )

    destino = EXPERIMENTS_DIR / "ag449_lift_by_atr_regime.json"
    payload = {
        "task": "AG-449 -- lift do modelo por regime de ATR (walk-forward, out-of-time)",
        "n_buckets": _N_BUCKETS,
        "min_trades_por_balde": _MIN_TRADES_POR_BALDE,
        "nota": (
            "win_rate_incondicional e a populacao COMPLETA de labels daquele balde; "
            "win_rate_selecionada e so o que o modelo disparou no walk-forward "
            "(out-of-time). lift = selecionada - incondicional, isolando o que o "
            "modelo adiciona sobre o piso de mercado. breakeven usa o ATR MEDIANO do "
            "balde -- cai com ATR porque o custo e ~fixo em bps e a barreira escala."
        ),
        "resultados": resultados,
    }
    destino.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("ag449.gravado", path=str(destino))
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
