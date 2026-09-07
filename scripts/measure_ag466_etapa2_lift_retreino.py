"""AG-466 Etapa 2 — o LIFT do modelo sobrevive ao label novo?

A Etapa 1 (`experiments/ag466_etapa1_geometria.json`) mediu que a celula
derivada em SOLUSDT/R3 reduz o gap nos 4 combos nao vistos. Isso e
aritmetica de label: diz que o modelo precisa adicionar MENOS, nao que ele
ainda adiciona. Barreira 2,67x mais larga e horizonte 4x maior e outro
problema de predicao, e o lift de +1,25pp do `AG-461` foi medido sobre o
label de PRODUCAO.

Desenho e criterios vivem em
`audit/pre_registro/ag466_geometria_m4_h128_generaliza.yaml`, commitado
sozinho em `d496398` ANTES de qualquer numero destes combos existir sob
esta geometria. Este modulo le o registro e aplica.

**O que ele faz, em ordem:**
  1. Relabel dos 4 combos na celula derivada, escrito em
     `data/labels/{symbol}/{res}/v_ag466/` -- caminho PARALELO, `v1`
     NUNCA e tocado. Reusa `build_and_write_labels_for_symbol`, o mesmo
     writer de producao, com `dataclasses.replace` sobre o `LabelConfig`
     de `from_constants` -- nao uma construcao paralela que pudesse
     divergir em algum campo.
  2. Walk-forward ancorado sobre CADA versao de label (`v1` e `v_ag466`),
     com os hiperparametros de PRODUCAO. Sem Optuna, declarado no
     registro: reotimizar adicionaria um grau de liberdade que o
     pre-registro nao consegue travar.
  3. Comparacao PAREADA POR FOLD: mesmo `fold_id`, mesmo periodo, labels
     diferentes. O pareamento remove a variacao entre folds, a maior
     fonte de ruido ja medida neste projeto.

**Cache com checagem de correcao.** Se `v_ag466/labels.parquet` ja existe
E o `config_hash` gravado nele bate com o da config que este script
resolveu, o relabel e pulado. Hash diferente = rebuild. Nunca reusa um
artefato que nao seja bit-a-bit a mesma configuracao.

Uso:

    uv run python -m scripts.measure_ag466_etapa2_lift_retreino
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import structlog
import yaml

from src.features.volatility import ParkinsonEstimator
from src.labels._paths import labels_symbol_tf_dir
from src.labels.backfill_multi_symbol import (
    END_DATE,
    SYMBOL_START_DATE,
    build_and_write_labels_for_symbol,
)
from src.labels.triple_barrier import LabelConfig
from src.models import alpha, dataset, hyperparams_by_combo
from src.models import walk_forward as wf
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_REPO_ROOT: Path = Path(__file__).resolve().parents[1]
_PRE_REGISTRO: Path = (
    _REPO_ROOT / "audit" / "pre_registro" / "ag466_geometria_m4_h128_generaliza.yaml"
)

_COMBOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)

_VERSAO_PRODUCAO: str = "v1"
_VERSAO_NOVA: str = "v_ag466"

#: Celula derivada e criterios, espelhados do registro. `_valida_registro`
#: aborta se divergirem do YAML commitado.
_M_DERIVADO: float = 4.0  # noqa: magic-number -- celula derivada, ver pre-registro
_HORIZON_DERIVADO: int = 128  # noqa: magic-number -- celula derivada, ver pre-registro
_MIN_TRADES_POR_FOLD: int = 20  # noqa: magic-number -- c3 do registro
_MIN_FOLDS_VALIDOS: int = 30  # noqa: magic-number -- c3 do registro
_T_CRITICO: float = 2.0  # noqa: magic-number -- c1/c2 do registro
_MIN_COMBOS_POSITIVOS: int = 3  # noqa: magic-number -- c4 do registro

_BPS: float = 10_000.0  # noqa: magic-number -- definicao matematica


def _valida_registro() -> dict[str, Any]:
    """Aborta se qualquer numero espelhado aqui divergir do registro
    commitado. Normaliza a virgula decimal do portugues (licao do AG-463,
    onde a checagem falhou por ortografia)."""
    with _PRE_REGISTRO.open(encoding="utf-8") as f:
        reg: dict[str, Any] = yaml.safe_load(f)
    if reg.get("id") != "AG-466":
        raise ValueError(f"pre-registro inesperado: id={reg.get('id')!r}")
    crit = reg["etapa_2"]["criterio_de_sucesso"]
    esperado = {
        "c1_ganho_pareado": (f"t > {_T_CRITICO:.1f}",),
        "c2_edge_absoluto_positivo": (f"t > {_T_CRITICO:.1f}",),
        "c3_amostra_suficiente": (
            f">= {_MIN_TRADES_POR_FOLD} trades",
            f">= {_MIN_FOLDS_VALIDOS} folds",
        ),
        "c4_nao_e_um_combo_so": (f"{_MIN_COMBOS_POSITIVOS} dos 4",),
    }
    for chave, fragmentos in esperado.items():
        texto = str(crit[chave]).replace(",", ".")
        for frag in fragmentos:
            if frag not in texto:
                raise ValueError(
                    f"divergencia registro-vs-codigo em {chave}: {frag!r} ausente. "
                    "O codigo NAO pode aplicar criterio diferente do commitado."
                )
    destino = str(reg["execucao"]["etapa_2"]["escreve_labels_em"])
    if _VERSAO_NOVA not in destino:
        raise ValueError(f"versao de label do codigo ({_VERSAO_NOVA}) nao bate com {destino!r}")
    return reg


def _config_experimento(symbol: str, resolution_id: str) -> LabelConfig:
    """FONTE UNICA da config do experimento. O relabel escreve sob ela e o
    B15 confere contra ela -- se as duas fossem construidas em lugares
    diferentes, uma divergencia de um campo passaria como
    `ConfigHashMismatchError` inexplicavel, ou pior, um artefato gravado
    sob geometria diferente da declarada."""
    estimator = ParkinsonEstimator(window=int(load_constant("atr_window")))
    return dataclasses.replace(
        LabelConfig.from_constants(
            estimator_id=estimator.estimator_id, resolution_id=resolution_id, symbol=symbol
        ),
        tp_atr_mult=_M_DERIVADO,
        sl_atr_mult=_M_DERIVADO,
        horizon_bars=_HORIZON_DERIVADO,
    )


def _relabel(symbol: str, resolution_id: str) -> Path:
    """Relabel na celula derivada, em caminho paralelo. Pula se o artefato
    existente ja tem o MESMO `config_hash`."""
    estimator = ParkinsonEstimator(window=int(load_constant("atr_window")))
    cfg = _config_experimento(symbol, resolution_id)
    destino = (
        labels_symbol_tf_dir(symbol, _VERSAO_NOVA, resolution_id=resolution_id) / "labels.parquet"
    )
    if destino.exists():
        hash_no_disco = str(
            pl.read_parquet(destino, columns=["config_hash"]).item(0, "config_hash")
        )
        if hash_no_disco == cfg.config_hash:
            logger.info(
                "ag466e2.relabel_reusado",
                symbol=symbol,
                resolution_id=resolution_id,
                config_hash=cfg.config_hash,
            )
            return destino
        logger.info(
            "ag466e2.relabel_hash_divergente",
            symbol=symbol,
            no_disco=hash_no_disco,
            esperado=cfg.config_hash,
        )
    logger.info(
        "ag466e2.relabel_inicio",
        symbol=symbol,
        resolution_id=resolution_id,
        tp=cfg.tp_atr_mult,
        sl=cfg.sl_atr_mult,
        horizon_bars=cfg.horizon_bars,
    )
    return build_and_write_labels_for_symbol(
        symbol,
        SYMBOL_START_DATE[symbol],
        END_DATE,
        version=_VERSAO_NOVA,
        resolution_id=resolution_id,
        config=cfg,
        estimator=estimator,
    )


def _ret_por_fold(symbol: str, resolution_id: str, versao: str) -> dict[int, tuple[float, int]]:
    """Walk-forward ancorado sobre `versao` do label; devolve `ret_net`
    medio e n dos trades SELECIONADOS por fold. `side_hat != 0` separa
    populacao de inferencia de trade selecionado -- sem isso o teste
    compararia a populacao completa consigo mesma.

    Sob `v_ag466` o B15 e conferido contra a config do EXPERIMENTO, nao
    contra `constants.yaml` -- a geometria da celula derivada nao esta na
    global e nao cabe em `barrier_geometry_by_combo.yaml`, que so carrega
    tp/sl. O guardrail continua rodando: `_config_experimento` reconstroi
    a MESMA config que o relabel usou, e um erro ali levanta.
    """
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
    mf = dataset.build_modeling_frame(
        symbol=symbol,
        resolution_id=resolution_id,
        vol_estimator_id=vol_estimator_id,
        labels_version=versao,
        experiment_label_config=(
            _config_experimento(symbol, resolution_id) if versao == _VERSAO_NOVA else None
        ),
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
    partes = [
        f.predictions.with_columns(pl.lit(f.fold_id).alias("fold_id"))
        for f in res.fold_results
        if f.predictions is not None and not f.predictions.is_empty()
    ]
    if not partes:
        return {}
    sinal = (
        pl.concat(partes, how="diagonal")
        .filter(pl.col("side_hat") != 0)
        .with_columns(pl.col("side_hat").cast(pl.Int8).alias("side"))
    )
    if sinal.is_empty():
        return {}
    labels = pl.read_parquet(
        labels_symbol_tf_dir(symbol, versao, resolution_id=resolution_id) / "labels.parquet"
    ).filter(pl.col("barrier_hit") != "NOFILL")
    juntado = (
        sinal.join(
            labels.select(["t0", "side", "barrier_hit", "ret_net"]), on=["t0", "side"], how="inner"
        )
        .filter(pl.col("barrier_hit").is_in(["TP", "SL", "TIME"]))
        .select(["fold_id", "ret_net"])
    )
    saida: dict[int, tuple[float, int]] = {}
    for fid in sorted(juntado["fold_id"].unique().to_list()):
        sub = juntado.filter(pl.col("fold_id") == fid)
        if sub.is_empty():
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
    _valida_registro()

    por_combo: list[dict[str, Any]] = []
    difs_todos: list[float] = []
    novos_todos: list[float] = []

    for symbol, resolution_id in _COMBOS:
        logger.info("ag466e2.combo_inicio", symbol=symbol, resolution_id=resolution_id)
        _relabel(symbol, resolution_id)
        prod = _ret_por_fold(symbol, resolution_id, _VERSAO_PRODUCAO)
        novo = _ret_por_fold(symbol, resolution_id, _VERSAO_NOVA)

        pares: list[dict[str, Any]] = []
        for fid in sorted(set(prod) & set(novo)):
            r_prod, n_prod = prod[fid]
            r_novo, n_novo = novo[fid]
            # c3 -- o piso opera sobre o label NOVO, que e o que esta sendo
            # testado; fold raso e DESCARTADO, nunca contado como zero.
            if n_novo < _MIN_TRADES_POR_FOLD:
                continue
            if not (np.isfinite(r_prod) and np.isfinite(r_novo)):
                continue
            pares.append(
                {
                    "fold_id": fid,
                    "ret_producao_bps": r_prod,
                    "ret_novo_bps": r_novo,
                    "dif_bps": r_novo - r_prod,
                    "n_producao": n_prod,
                    "n_novo": n_novo,
                }
            )

        difs = np.array([p["dif_bps"] for p in pares], dtype=np.float64)
        novos = np.array([p["ret_novo_bps"] for p in pares], dtype=np.float64)
        difs_todos.extend(difs.tolist())
        novos_todos.extend(novos.tolist())
        por_combo.append(
            {
                "symbol": symbol,
                "resolution_id": resolution_id,
                "n_folds_producao": len(prod),
                "n_folds_novo": len(novo),
                "n_folds_validos": len(pares),
                "dif_media_bps": float(difs.mean()) if difs.size else None,
                "ret_novo_medio_bps": float(novos.mean()) if novos.size else None,
                "ret_producao_medio_bps": (
                    float(np.mean([p["ret_producao_bps"] for p in pares])) if pares else None
                ),
                "pares": pares,
            }
        )
        logger.info(
            "ag466e2.combo_fim",
            symbol=symbol,
            resolution_id=resolution_id,
            n_folds=len(pares),
            dif=round(float(difs.mean()), 3) if difs.size else None,
            ret_novo=round(float(novos.mean()), 3) if novos.size else None,
        )

    d_all = np.array(difs_todos, dtype=np.float64)
    n_all = np.array(novos_todos, dtype=np.float64)
    n_folds = int(d_all.size)
    n_combos_pos = sum(
        1 for c in por_combo if c["dif_media_bps"] is not None and c["dif_media_bps"] > 0
    )

    if n_folds < _MIN_FOLDS_VALIDOS:
        veredito, c1, c2, c3, c4 = "SEM_PODER", False, False, False, False
        t1 = t2 = float("nan")
    else:
        t1 = _t_stat(d_all)
        t2 = _t_stat(n_all)
        c1 = bool(np.isfinite(t1) and d_all.mean() > 0 and t1 > _T_CRITICO)
        c2 = bool(np.isfinite(t2) and n_all.mean() > 0 and t2 > _T_CRITICO)
        c3 = True
        c4 = bool(n_combos_pos >= _MIN_COMBOS_POSITIVOS)
        veredito = "SUCESSO" if (c1 and c2 and c3 and c4) else "FRACASSO"

    payload = {
        "task": "AG-466 Etapa 2 -- o lift sobrevive ao label da celula derivada?",
        "pre_registro": str(_PRE_REGISTRO.relative_to(_REPO_ROOT)).replace("\\", "/"),
        "celula_derivada": {"m": _M_DERIVADO, "horizon_bars": _HORIZON_DERIVADO},
        "versao_label_nova": _VERSAO_NOVA,
        "veredito": veredito,
        "criterios": {
            "c1_ganho_pareado": c1,
            "c2_edge_absoluto_positivo": c2,
            "c3_amostra_suficiente": c3,
            "c4_nao_e_um_combo_so": c4,
            "t_ganho_pareado": t1,
            "t_edge_absoluto": t2,
            "dif_media_bps": float(d_all.mean()) if d_all.size else None,
            "ret_novo_medio_bps": float(n_all.mean()) if n_all.size else None,
            "n_folds_validos": n_folds,
            "n_combos_com_dif_positiva": n_combos_pos,
        },
        "por_combo": por_combo,
        "nota": (
            "Hiperparametros de PRODUCAO em ambas as versoes (sem Optuna, declarado no "
            "registro) -- eles foram otimizados sobre o label de producao, o que "
            "desfavorece o label novo por construcao e torna o teste conservador nesse "
            "eixo. Labels de v_ag466 tem config_hash divergente de constants.yaml por "
            "desenho; nao sao artefato de producao."
        ),
    }
    destino = EXPERIMENTS_DIR / "ag466_etapa2_lift.json"
    destino.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("ag466e2.gravado", path=str(destino), veredito=veredito, n_folds=n_folds)
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
