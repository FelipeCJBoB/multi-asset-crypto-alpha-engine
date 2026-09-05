"""AG-463 — executa o teste PRE-REGISTRADO da regra de ATR por QUANTIL.

**Segunda tentativa** sobre a hipotese do `AG-461`. A primeira (`AG-462`)
deu SEM_PODER porque usava limiar ABSOLUTO de ATR e o ATR caiu em 5 de 5
combos entre as metades — o limiar do passado esvaziava a amostra do
presente. Aqui o limiar e um QUANTIL calculado DENTRO de cada fold, entao a
fracao selecionada nao depende do nivel de volatilidade.

Desenho, grade e os 4 criterios vivem em
`audit/pre_registro/ag463_regra_atr_quantil_v2.yaml`, commitado ANTES deste
script rodar (commit proprio, ordem verificavel por `git log`). Este modulo
le o registro e aplica — nao decide nada.

Uso:

    uv run python -m scripts.measure_ag463_regra_atr_quantil
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
_PRE_REGISTRO: Path = (
    _REPO_ROOT / "audit" / "pre_registro" / "ag463_regra_atr_quantil_v2.yaml"
)

_COMBOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)

#: Conversao fracao -> basis points (definicao matematica, nao constante de
#: dominio -- mesma categoria de `_BPS_PER_UNIT` em `triple_barrier`).
_BPS: float = 10_000.0  # noqa: magic-number

#: c3 do pre-registro. Espelhados aqui pra leitura; a fonte de verdade e o
#: YAML e o `_valida_registro` aborta se os dois divergirem.
_MIN_TRADES_POR_FOLD: int = 20  # noqa: magic-number -- c3 do registro
_MIN_FOLDS_VALIDOS: int = 30  # noqa: magic-number -- c3 do registro
_T_CRITICO: float = 2.0  # noqa: magic-number -- c1/c2 do registro
_MIN_COMBOS_POSITIVOS: int = 3  # noqa: magic-number -- c4 do registro


def _valida_registro() -> dict[str, Any]:
    """Le o registro e ABORTA se os numeros espelhados no codigo divergirem
    dele. Sem esta checagem, o codigo poderia silenciosamente aplicar um
    criterio diferente do que foi commitado antes -- que e precisamente a
    fraude que o pre-registro existe pra tornar impossivel."""
    with _PRE_REGISTRO.open(encoding="utf-8") as f:
        reg: dict[str, Any] = yaml.safe_load(f)
    if reg.get("id") != "AG-463":
        raise ValueError(f"pre-registro inesperado: id={reg.get('id')!r}")
    crit = reg["criterio_de_sucesso"]
    esperado = {
        "c3_amostra_suficiente": (
            f">= {_MIN_TRADES_POR_FOLD} trades",
            f">= {_MIN_FOLDS_VALIDOS} folds",
        ),
        "c1_ganho_pareado": (f"t > {_T_CRITICO:.1f}",),
        "c2_edge_absoluto_positivo": (f"t > {_T_CRITICO:.1f}",),
        "c4_nao_e_um_combo_so": (f"{_MIN_COMBOS_POSITIVOS} dos 5",),
    }
    for chave, fragmentos in esperado.items():
        # O registro e escrito em portugues e usa VIRGULA decimal ("t > 2,0");
        # o f-string aqui produz PONTO ("t > 2.0"). Normalizar os dois lados
        # compara o NUMERO, que e o que o pre-registro trava -- nao afrouxa
        # criterio nenhum: 2,0 e 2.0 sao o mesmo limiar escrito em duas
        # convencoes. Sem isto a checagem falha por ortografia e nunca chega
        # a olhar o criterio de verdade.
        texto = str(crit[chave]).replace(",", ".")
        for frag in fragmentos:
            if frag not in texto:
                raise ValueError(
                    f"divergencia registro-vs-codigo em {chave}: {frag!r} ausente. "
                    "O codigo NAO pode aplicar criterio diferente do commitado."
                )
    return reg


def _trades_por_fold(symbol: str, resolution_id: str) -> pl.DataFrame:
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

    sinal = (
        pl.concat(partes, how="diagonal")
        .filter(pl.col("side_hat") != 0)
        .with_columns(pl.col("side_hat").cast(pl.Int8).alias("side"))
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


def _ret_por_fold(df: pl.DataFrame, q: float) -> dict[int, tuple[float, int]]:
    """`ret_net` medio e n POR FOLD, com o quantil recalculado DENTRO de
    cada fold — e isso que torna a fracao selecionada independente do nivel
    de volatilidade da janela."""
    saida: dict[int, tuple[float, int]] = {}
    for fid in sorted(df["fold_id"].unique().to_list()):
        sub = df.filter(pl.col("fold_id") == fid)
        if q > 0.0:
            atr = sub["atr_at_t0"].to_numpy()
            if atr.size == 0:
                continue
            corte = float(np.quantile(atr, q))
            sub = sub.filter(pl.col("atr_at_t0") > corte)
        if sub.is_empty():
            saida[int(fid)] = (float("nan"), 0)
            continue
        saida[int(fid)] = (float(sub["ret_net"].to_numpy().mean()) * _BPS, int(sub.height))
    return saida


def _t_stat(x: np.ndarray) -> float:
    if x.size < 2:
        return float("nan")
    dp = float(x.std(ddof=1))
    if dp <= 0.0:
        return float("nan")
    return float(x.mean() / (dp / np.sqrt(x.size)))


def main(argv: list[str] | None = None) -> int:
    configure_logging(json_output=False)
    reg = _valida_registro()
    grade: list[float] = [
        float(x) for x in reg["desenho"]["grade_de_quantil_declarada_a_priori"]
    ]

    por_combo: list[dict[str, Any]] = []
    difs_todos: list[float] = []
    filt_todos: list[float] = []

    for symbol, resolution_id in _COMBOS:
        logger.info("ag463.combo_inicio", symbol=symbol, resolution_id=resolution_id)
        df = _trades_por_fold(symbol, resolution_id)
        if df.is_empty():
            por_combo.append(
                {"symbol": symbol, "resolution_id": resolution_id, "erro": "sem trades"}
            )
            continue

        folds = sorted(df["fold_id"].unique().to_list())
        corte = len(folds) // 2
        antigo = df.filter(pl.col("fold_id").is_in(folds[:corte]))
        recente = df.filter(pl.col("fold_id").is_in(folds[corte:]))

        # --- DERIVACAO: menor q com ret_net medio positivo na metade ANTIGA
        curva = []
        q_escolhido: float | None = None
        for q in grade:
            por_f = _ret_por_fold(antigo, q)
            vals = np.array([v for v, n in por_f.values() if n > 0], dtype=np.float64)
            m = float(vals.mean()) if vals.size else float("nan")
            curva.append({"q": q, "ret_bps": m, "n_folds": int(vals.size)})
            if q_escolhido is None and q > 0.0 and np.isfinite(m) and m > 0:
                q_escolhido = q

        if q_escolhido is None:
            por_combo.append(
                {
                    "symbol": symbol,
                    "resolution_id": resolution_id,
                    "derivacao": {"curva": curva, "q_escolhido": None},
                    "sem_regra": True,
                }
            )
            logger.info("ag463.sem_regra", symbol=symbol, resolution_id=resolution_id)
            continue

        # --- TESTE: metade RECENTE, pareado fold a fold
        ctrl = _ret_por_fold(recente, 0.0)
        filt = _ret_por_fold(recente, q_escolhido)
        pares = []
        for fid in sorted(set(ctrl) & set(filt)):
            rc, _n_ctrl = ctrl[fid]
            rf, nf = filt[fid]
            if nf < _MIN_TRADES_POR_FOLD or not np.isfinite(rc) or not np.isfinite(rf):
                continue
            pares.append(
                {
                    "fold_id": fid,
                    "ret_ctrl": rc,
                    "ret_filt": rf,
                    "dif": rf - rc,
                    "n_filt": nf,
                }
            )

        difs = np.array([p["dif"] for p in pares], dtype=np.float64)
        filts = np.array([p["ret_filt"] for p in pares], dtype=np.float64)
        difs_todos.extend(difs.tolist())
        filt_todos.extend(filts.tolist())

        por_combo.append(
            {
                "symbol": symbol,
                "resolution_id": resolution_id,
                "sem_regra": False,
                "derivacao": {"curva": curva, "q_escolhido": q_escolhido},
                "teste": {
                    "n_folds_validos": len(pares),
                    "dif_media_bps": float(difs.mean()) if difs.size else None,
                    "ret_filt_medio_bps": float(filts.mean()) if filts.size else None,
                    "pares": pares,
                },
            }
        )
        logger.info(
            "ag463.combo_fim",
            symbol=symbol,
            resolution_id=resolution_id,
            q=q_escolhido,
            n_folds=len(pares),
            dif=float(difs.mean()) if difs.size else None,
        )

    # ------------------------- veredito, como travado -----------------------
    d_all = np.array(difs_todos, dtype=np.float64)
    f_all = np.array(filt_todos, dtype=np.float64)
    n_folds = int(d_all.size)

    com_teste = [c for c in por_combo if not c.get("sem_regra") and "erro" not in c]
    n_combos_pos = sum(
        1
        for c in com_teste
        if c["teste"]["dif_media_bps"] is not None and c["teste"]["dif_media_bps"] > 0
    )

    if n_folds < _MIN_FOLDS_VALIDOS:
        veredito, c1, c2, c3, c4 = "SEM_PODER", False, False, False, False
        t1 = t2 = float("nan")
    else:
        t1 = _t_stat(d_all)
        t2 = _t_stat(f_all)
        c1 = bool(np.isfinite(t1) and d_all.mean() > 0 and t1 > _T_CRITICO)
        c2 = bool(np.isfinite(t2) and f_all.mean() > 0 and t2 > _T_CRITICO)
        c3 = True
        c4 = bool(n_combos_pos >= _MIN_COMBOS_POSITIVOS)
        veredito = "SUCESSO" if (c1 and c2 and c3 and c4) else "FRACASSO"

    payload = {
        "task": "AG-463 -- teste PRE-REGISTRADO da regra de ATR por quantil (2a tentativa)",
        "pre_registro": str(_PRE_REGISTRO.relative_to(_REPO_ROOT)).replace("\\", "/"),
        "tentativa_anterior": "AG-462 (SEM_PODER)",
        "veredito": veredito,
        "criterios": {
            "c1_ganho_pareado": c1,
            "c2_edge_absoluto_positivo": c2,
            "c3_amostra_suficiente": c3,
            "c4_nao_e_um_combo_so": c4,
            "t_ganho_pareado": t1,
            "t_edge_absoluto": t2,
            "dif_media_bps": float(d_all.mean()) if d_all.size else None,
            "ret_filt_medio_bps": float(f_all.mean()) if f_all.size else None,
            "n_folds_validos": n_folds,
            "n_combos_com_dif_positiva": n_combos_pos,
        },
        "por_combo": por_combo,
    }
    destino = EXPERIMENTS_DIR / "ag463_regra_atr_quantil.json"
    destino.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("ag463.gravado", path=str(destino), veredito=veredito)
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
