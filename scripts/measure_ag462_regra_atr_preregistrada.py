"""AG-462 — executa o teste PRE-REGISTRADO da regra de regime de ATR.

O desenho, a grade de limiar e os 3 criterios de sucesso estao travados em
`audit/pre_registro/ag462_regra_atr_critico.yaml`, commitado ANTES deste
script rodar (commit proprio, ordem verificavel por `git log`). Este modulo
NAO decide nada: ele le o registro e aplica.

**Por que ler o YAML em vez de repetir os numeros aqui.** Se a grade e os
limiares vivessem nos dois lugares, eles poderiam divergir, e a divergencia
mais provavel seria eu ajustando o codigo depois de ver o resultado. Lendo
do registro, mudar o criterio exige mudar o arquivo pre-registrado -- que
aparece no diff, com data, contra um commit anterior.

Resumo do desenho (fonte de verdade e o YAML):
  - folds de cada combo ordenados no tempo e partidos ao meio
  - metade ANTIGA: unica fonte para DERIVAR o limiar (menor da grade com
    ret_net positivo -- menor, nao melhor)
  - metade RECENTE: unico lugar onde o criterio e avaliado
  - c1 t > 2,0 sobre COMBOS · c2 supera controle em >= 4/5 · c3 >= 200
    trades por combo, com regra de INDETERMINADO e de SEM PODER

Uso:

    uv run python -m scripts.measure_ag462_regra_atr_preregistrada
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import structlog
import yaml

from src.models import alpha, dataset, hyperparams_by_combo
from src.models import walk_forward as wf
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_REPO_ROOT: Path = Path(__file__).resolve().parents[1]
_PRE_REGISTRO: Path = _REPO_ROOT / "audit" / "pre_registro" / "ag462_regra_atr_critico.yaml"

_COMBOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)

#: Conversao fracao -> basis points. Definicao matematica, nao constante de
#: dominio (mesma categoria de `_BPS_PER_UNIT` em `triple_barrier`).
_BPS: float = 10_000.0  # noqa: magic-number


def _carrega_registro() -> dict[str, Any]:
    with _PRE_REGISTRO.open(encoding="utf-8") as f:
        reg: dict[str, Any] = yaml.safe_load(f)
    if reg.get("id") != "AG-462":
        raise ValueError(f"pre-registro inesperado: id={reg.get('id')!r}")
    return reg


def _trades_por_fold(symbol: str, resolution_id: str) -> pl.DataFrame:
    """Trades REALIZADOS que o modelo disparou no walk-forward, com o
    `fold_id` preservado (a particao temporal opera sobre ele) e o
    `atr_at_t0`/`ret_net` do label daquela barra."""
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
    mf = dataset.build_modeling_frame(
        symbol=symbol, resolution_id=resolution_id, vol_estimator_id=vol_estimator_id
    )
    hyper = hyperparams_by_combo.load_production_override(
        symbol, resolution_id, alpha.VARIANT_CAMADA1
    )
    if hyper is None:
        raise ValueError(f"{symbol}/{resolution_id} sem override de producao")
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

    pred_all = pl.concat(partes, how="diagonal")
    # `side_hat != 0` separa "populacao de inferencia" de "trade
    # SELECIONADO" -- sem esse filtro o teste compararia a populacao
    # completa consigo mesma.
    sinal = pred_all.filter(pl.col("side_hat") != 0).with_columns(
        pl.col("side_hat").cast(pl.Int8).alias("side")
    )
    if sinal.is_empty():
        return pl.DataFrame()

    labels = pl.read_parquet(
        f"data/labels/{symbol}/{resolution_id}/v1/labels.parquet"
    ).filter(pl.col("barrier_hit") != "NOFILL")

    return (
        sinal.join(
            labels.select(["t0", "side", "atr_at_t0", "barrier_hit", "ret_net"]),
            on=["t0", "side"],
            how="inner",
        )
        .filter(pl.col("barrier_hit").is_in(["TP", "SL", "TIME"]))
        .select(["fold_id", "atr_at_t0", "ret_net"])
    )


def _particao_temporal(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Folds ordenados no tempo, partidos ao meio. `fold_id` e crescente no
    tempo por construcao do walk-forward ancorado."""
    folds = sorted(df["fold_id"].unique().to_list())
    corte = len(folds) // 2
    antigos, recentes = set(folds[:corte]), set(folds[corte:])
    return (
        df.filter(pl.col("fold_id").is_in(list(antigos))),
        df.filter(pl.col("fold_id").is_in(list(recentes))),
    )


def _ret_medio_bps(df: pl.DataFrame, limiar: float) -> tuple[float, int]:
    sub = df.filter(pl.col("atr_at_t0") > limiar) if limiar > 0 else df
    if sub.is_empty():
        return float("nan"), 0
    # `.to_numpy().mean()` em vez de `Series.mean()` -- o retorno agregado do
    # polars e uma uniao ampla nos stubs de tipo (mesmo padrao ja usado em
    # `assert_label_invariants`/`triple_barrier.py`), e `float(...)` direto
    # sobre ela nao passa no mypy strict.
    return float(sub["ret_net"].to_numpy().mean()) * _BPS, int(sub.height)


def main(argv: list[str] | None = None) -> int:
    configure_logging(json_output=False)
    reg = _carrega_registro()
    grade: list[float] = [float(x) for x in reg["desenho"]["grade_de_limiar_declarada_a_priori"]]
    min_trades = 200  # c3 do registro; literal aqui so como espelho, ver assert abaixo
    if "200 trades" not in reg["criterio_de_sucesso"]["c3_amostra_suficiente"]:
        raise ValueError("c3 do pre-registro mudou -- este script esta desatualizado")

    por_combo: list[dict[str, Any]] = []
    for symbol, resolution_id in _COMBOS:
        logger.info("ag462.combo_inicio", symbol=symbol, resolution_id=resolution_id)
        df = _trades_por_fold(symbol, resolution_id)
        if df.is_empty():
            por_combo.append(
                {"symbol": symbol, "resolution_id": resolution_id, "erro": "sem trades"}
            )
            continue
        antigo, recente = _particao_temporal(df)

        # --- DERIVACAO: so na metade ANTIGA, menor limiar com ret_net > 0
        curva_derivacao = []
        limiar_escolhido: float | None = None
        for lim in grade:
            r, n = _ret_medio_bps(antigo, lim)
            curva_derivacao.append({"limiar": lim, "ret_bps": r, "n": n})
            if limiar_escolhido is None and lim > 0 and np.isfinite(r) and r > 0:
                limiar_escolhido = lim

        # --- TESTE: so na metade RECENTE, com o limiar ja fixado
        ret_ctrl, n_ctrl = _ret_medio_bps(recente, 0.0)
        if limiar_escolhido is None:
            ret_filt, n_filt = float("nan"), 0
        else:
            ret_filt, n_filt = _ret_medio_bps(recente, limiar_escolhido)

        por_combo.append(
            {
                "symbol": symbol,
                "resolution_id": resolution_id,
                "n_folds_total": int(df["fold_id"].n_unique()),
                "n_trades_total": int(df.height),
                "derivacao": {
                    "n_trades": int(antigo.height),
                    "curva": curva_derivacao,
                    "limiar_escolhido": limiar_escolhido,
                },
                "teste": {
                    "n_trades_controle": n_ctrl,
                    "ret_bps_controle": ret_ctrl,
                    "n_trades_filtrado": n_filt,
                    "ret_bps_filtrado": ret_filt,
                    "supera_controle": (
                        bool(np.isfinite(ret_filt) and ret_filt > ret_ctrl)
                        if np.isfinite(ret_ctrl)
                        else None
                    ),
                    "indeterminado_c3": bool(n_filt < min_trades),
                },
            }
        )
        logger.info(
            "ag462.combo_fim",
            symbol=symbol,
            resolution_id=resolution_id,
            limiar=limiar_escolhido,
            n_filt=n_filt,
            ret_filt=ret_filt,
        )

    # ---------------- veredito, exatamente como travado no registro ----------
    validos = [c for c in por_combo if "erro" not in c]
    determinados = [c for c in validos if not c["teste"]["indeterminado_c3"]]
    n_indet = len(validos) - len(determinados)

    if n_indet >= 3:
        veredito, c1, c2, c3, t_stat = "SEM_PODER", False, False, False, float("nan")
    else:
        rets = np.array(
            [c["teste"]["ret_bps_filtrado"] for c in determinados], dtype=np.float64
        )
        # `r_arr`, nao `r` -- `r` ja e float no laco de derivacao acima, e
        # reusar o nome faria o type-checker (com razao) ler `.std()` sobre
        # um float. Nome distinto em vez de cast.
        r_arr = rets[np.isfinite(rets)]
        t_stat = (
            float(r_arr.mean() / (r_arr.std(ddof=1) / np.sqrt(r_arr.size)))
            if r_arr.size >= 2 and r_arr.std(ddof=1) > 0
            else float("nan")
        )
        c1 = bool(np.isfinite(t_stat) and r_arr.mean() > 0 and t_stat > 2.0)
        n_supera = sum(1 for c in determinados if c["teste"]["supera_controle"])
        c2 = bool(n_supera >= 4)
        c3 = bool(len(determinados) == len(validos))
        veredito = "SUCESSO" if (c1 and c2 and c3) else "FRACASSO"

    payload = {
        "task": "AG-462 -- teste PRE-REGISTRADO da regra de regime de ATR",
        "pre_registro": str(_PRE_REGISTRO.relative_to(_REPO_ROOT)).replace("\\", "/"),
        "veredito": veredito,
        "criterios": {
            "c1_edge_positivo_t_maior_2": c1,
            "c2_supera_controle_4_de_5": c2,
            "c3_amostra_suficiente": c3,
            "t_stat_sobre_combos": t_stat,
            "n_indeterminados": n_indet,
        },
        "por_combo": por_combo,
    }
    destino = EXPERIMENTS_DIR / "ag462_regra_atr_preregistrada.json"
    destino.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("ag462.gravado", path=str(destino), veredito=veredito)
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
