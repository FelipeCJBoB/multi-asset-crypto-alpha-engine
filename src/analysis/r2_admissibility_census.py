"""Censo de admissibilidade econômica R2 da população de MODELAGEM —
ADR-005 §13 v2 (`§13.16.3`, item 11b de `§13.17`) — `AG-296`/`AG-297`.

**Por que este módulo existe.** R2 é uma das cinco restrições invioláveis
(`CLAUDE.md` §0.2): `custo_round_trip <= cost_stop_ratio_max * stop`. Ela é
avaliada hoje em `src/analysis/m3_timeframe_choice.py`,
`src/analysis/s1_tp_sl_sensitivity.py` e
`src/analysis/volatility_operational_effect.py` — **e em nenhum lugar de
`src/models/`** (verificado por varredura: `cost_stop_ratio_max` não aparece
no pacote de modelagem). A camada onde o Alpha aprende nunca viu R2.

Como `stop` de produção é `sl_atr_mult * ATR(t0)` e o `ATR` varia barra a
barra, R2 **não é uma propriedade da célula — é uma propriedade da linha**.
Uma barra de baixa volatilidade tem stop pequeno, e o mesmo custo de ida e
volta em bps passa a consumir uma fração muito maior dele. Esse é o mesmo
mecanismo que `AG-165`/`AG-190` registram para a heterogeneidade ENTRE
ativos, aplicado DENTRO de um ativo.

Este módulo mede quantas linhas do conjunto que o modelo de fato treina e
pontua estão abaixo do piso, por célula. **Não filtra nada, não altera
nenhum artefato, não é lido por nenhum pipeline de treino/execução** —
mesmo status DECISION-SUPPORT de `feasibility.py`/`production_grade_gate.py`.

**Relação com o breakeven por linha.** Sob payoff simétrico
(`tp_atr_mult == sl_atr_mult`, a geometria de produção hoje), vale a
identidade:

    breakeven(linha) = 0,5 + custo / (2 * stop)
    R2               = custo <= ratio * stop
    ==>  R2  <=>  breakeven(linha) <= 0,5 + ratio/2   (= 0,60 com ratio=0,20)

O teste aplicado aqui é o **R2 direto** (`custo <= ratio * stop`), não a
identidade — ela vale só sob simetria, e a simetria é medida e reportada
(`payoff_simetrico`) em vez de presumida. O `breakeven` sai no relatório
como diagnóstico, porque é a forma em que a régua de
`config/min_alpha_lift_by_combo.yaml` está denominada.

**Fonte:** `data/labels/{symbol}/{resolution_id}/{version}/labels.parquet`,
colunas `entry_price_limit`/`tp_price`/`sl_price`/`cost_entry_bps`/
`cost_exit_bps` — todas conhecidas em `t0` (o limite de entrada é postado
em `t0`; o preço de fill não entra em nenhuma conta deste módulo). Nenhuma
feature, nenhum modelo, nenhuma predição: este censo é interpretável mesmo
com o purge de `§13.1` quebrado, e é por isso que ele vem antes.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from src.labels._constants import load_constant
from src.labels._paths import labels_symbol_tf_dir

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]

EXPERIMENTS_DIR: Final[Path] = Path("experiments")
SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")

#: Quantis reportados da distribuição por linha. Não são constantes de
#: domínio (não entram em nenhuma decisão) — é a forma de descrever uma
#: distribuição sem despejar 400 mil números num JSON.
_REPORT_QUANTILES: Final[tuple[float, ...]] = (0.01, 0.10, 0.50, 0.90, 0.99)  # noqa: magic-number -- forma de descrever distribuição, não constante de domínio

#: Tolerância relativa para chamar `tp_atr_mult == sl_atr_mult` de simétrico.
#: Puramente numérica (ruído de float na reconstrução de preço de barreira),
#: não um limiar de negócio.
_SIMETRIA_RTOL: Final[float] = 1e-6  # noqa: magic-number -- tolerância numérica de float, não limiar de negócio

_BPS_PER_UNIT: Final[float] = 10_000.0  # noqa: magic-number -- conversão de unidade


# ============================================================================
# NÚCLEO PURO (Idioma A, `CLAUDE.md` §Núcleo funcional, casca imperativa) —
# zero IO, zero rede. Recebe arrays em memória, devolve dado em memória.
# ============================================================================


@dataclass(frozen=True, slots=True)
class R2CellCensus:
    """Censo de UMA célula (`symbol` x `resolution_id` x `side`)."""

    symbol: str
    resolution_id: str
    side: int
    n_linhas: int
    n_viola_r2: int
    frac_viola_r2: float
    cost_stop_ratio_max: float
    payoff_simetrico: bool
    #: Linhas em que `ganho - custo <= 0`: o TP não cobre o custo de ida e
    #: volta, então NÃO EXISTE `p` em [0,1] que faça a linha empatar — nem
    #: acertar o TP em 100% das vezes salva. `breakeven` é indefinido nelas
    #: e elas ficam FORA de todos os quantis abaixo; contá-las aqui é a
    #: razão de este campo existir em vez de a função abortar.
    #: Violam R2 por construção (sob payoff simétrico, `ganho < custo`
    #: implica `custo/stop > 1 > cost_stop_ratio_max`).
    n_tp_nao_cobre_custo: int
    frac_tp_nao_cobre_custo: float
    #: `custo / stop` por linha — a grandeza que R2 limita. Quantis.
    cost_over_stop_q: dict[str, float]
    #: `P(TP)` de breakeven por linha. Quantis. Diagnóstico (ver docstring).
    breakeven_q: dict[str, float]
    #: Quantis do breakeven APENAS entre as linhas que passam em R2 — é a
    #: amplitude que uma regra de decisão por linha ainda precisa cobrir.
    breakeven_admissivel_q: dict[str, float]


def cost_fraction(cost_entry_bps: FloatArray, cost_exit_bps: FloatArray) -> FloatArray:
    """Custo de ida e volta como fração do nocional (bps -> fração)."""
    return np.asarray((cost_entry_bps + cost_exit_bps) / _BPS_PER_UNIT, dtype=np.float64)


def stop_fraction(entry_price: FloatArray, sl_price: FloatArray) -> FloatArray:
    """`|SL - entrada| / entrada`. Vale para os dois lados por construção:
    em `side=+1` o SL fica abaixo da entrada, em `side=-1` acima (verificado
    contra `labels.parquet`), e o módulo da diferença é a mesma grandeza
    econômica nos dois casos."""
    return np.asarray(np.abs(sl_price - entry_price) / entry_price, dtype=np.float64)


def gain_fraction(entry_price: FloatArray, tp_price: FloatArray) -> FloatArray:
    """`|TP - entrada| / entrada`, mesma simetria de `stop_fraction`."""
    return np.asarray(np.abs(tp_price - entry_price) / entry_price, dtype=np.float64)


def breakeven_probability(
    gain: FloatArray, stop: FloatArray, cost: FloatArray
) -> FloatArray:
    """`P(TP)` a partir da qual a linha empata, líquida de custo.

    `E[r] = p*(ganho - custo) - (1-p)*(stop + custo) = 0`, resolvido em `p`.
    Não presume `ganho == stop` — sob geometria assimétrica a fórmula segue
    valendo, só deixa de coincidir com `0,5 + custo/(2*stop)`.

    **A guarda é sobre `ganho - custo`, não sobre o denominador** (achado do
    próprio teste desta função, 2026-08-26): a primeira versão validava
    `(ganho - custo) + (stop + custo) > 0`, que é uma condição fraca demais.
    Com ganho de 5 bps, stop de 5 bps e custo de 60 bps o denominador dá
    `+0,001` — passa na guarda — e o breakeven sai **6,5**, uma
    "probabilidade" maior que 1 entregue sem erro. Quando o TP não cobre nem
    o próprio custo de ida e volta, **não existe `p` que faça a linha
    empatar**; a resposta certa é falhar alto, não devolver um número."""
    g_tp = gain - cost
    g_sl = stop + cost
    if np.any(g_tp <= 0.0):
        raise ValueError(
            "breakeven_probability: geometria degenerada em "
            f"{int((g_tp <= 0.0).sum())} linha(s) -- (ganho - custo) <= 0, ou seja o TP "
            "não cobre o custo de ida e volta. Não existe p em [0,1] que zere E[r]: "
            "qualquer valor devolvido aqui seria > 1 e não é uma probabilidade"
        )
    return np.asarray(g_sl / (g_tp + g_sl), dtype=np.float64)


def viola_r2(cost: FloatArray, stop: FloatArray, *, cost_stop_ratio_max: float) -> BoolArray:
    """R2 literal (`CLAUDE.md` §0.2): `custo_round_trip <= ratio * stop`.
    Devolve a máscara do que **viola**."""
    return np.asarray(cost > (cost_stop_ratio_max * stop), dtype=np.bool_)


def _quantis(values: FloatArray) -> dict[str, float]:
    if values.size == 0:
        return {f"p{int(q * 100):02d}": float("nan") for q in _REPORT_QUANTILES}
    qs = np.quantile(values, _REPORT_QUANTILES)
    return {f"p{int(q * 100):02d}": float(v) for q, v in zip(_REPORT_QUANTILES, qs, strict=True)}


def census_from_arrays(
    *,
    symbol: str,
    resolution_id: str,
    side: int,
    entry_price: FloatArray,
    tp_price: FloatArray,
    sl_price: FloatArray,
    cost_entry_bps: FloatArray,
    cost_exit_bps: FloatArray,
    cost_stop_ratio_max: float,
) -> R2CellCensus:
    """Núcleo: recebe as cinco colunas em memória, devolve o censo.

    Testável sem tocar em disco — é o ponto inteiro do Idioma A."""
    cost = cost_fraction(cost_entry_bps, cost_exit_bps)
    stop = stop_fraction(entry_price, sl_price)
    gain = gain_fraction(entry_price, tp_price)
    if np.any(stop <= 0.0):
        raise ValueError(
            f"census_from_arrays: stop <= 0 em {int((stop <= 0.0).sum())} linha(s) de "
            f"{symbol}/{resolution_id}/side={side} -- SL igual à entrada não é um label "
            "válido; falha alto em vez de produzir razão custo/stop infinita"
        )
    ratio = cost / stop
    mask_viola = viola_r2(cost, stop, cost_stop_ratio_max=cost_stop_ratio_max)
    # `breakeven_probability` falha alto quando `ganho <= custo` -- é o
    # comportamento certo para uma função de cálculo (o valor é indefinido
    # ali). Mas ESTE é um censo: a resposta certa é CONTAR essas linhas, não
    # abortar a célula inteira por causa delas. Elas saem dos quantis e
    # entram no seu próprio campo. Achado real da 1ª execução: existem 177
    # linhas assim nas 15 células (0,006%), concentradas em SOLUSDT/R1-R2 (AG-297).
    mask_impossivel = (gain - cost) <= 0.0
    be_validos = breakeven_probability(
        gain[~mask_impossivel], stop[~mask_impossivel], cost[~mask_impossivel]
    )
    admissivel = ~mask_viola[~mask_impossivel]
    return R2CellCensus(
        symbol=symbol,
        resolution_id=resolution_id,
        side=side,
        n_linhas=int(entry_price.shape[0]),
        n_viola_r2=int(mask_viola.sum()),
        frac_viola_r2=float(mask_viola.mean()) if entry_price.shape[0] else float("nan"),
        cost_stop_ratio_max=cost_stop_ratio_max,
        payoff_simetrico=bool(np.allclose(gain, stop, rtol=_SIMETRIA_RTOL)),
        n_tp_nao_cobre_custo=int(mask_impossivel.sum()),
        frac_tp_nao_cobre_custo=(
            float(mask_impossivel.mean()) if entry_price.shape[0] else float("nan")
        ),
        cost_over_stop_q=_quantis(ratio),
        breakeven_q=_quantis(be_validos),
        breakeven_admissivel_q=_quantis(be_validos[admissivel]),
    )


# ============================================================================
# CASCA IMPERATIVA — resolve símbolo/grade/arquivo e delega ao núcleo acima.
# ============================================================================


def _write_atomic(path: Path, content: str) -> Path:
    """B29 -- `.tmp` -> `fsync` -> `rename`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    fd = os.open(tmp, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


_COLS: Final[tuple[str, ...]] = (
    "side",
    "barrier_hit",
    "entry_price_limit",
    "tp_price",
    "sl_price",
    "cost_entry_bps",
    "cost_exit_bps",
    "config_hash",
)


def census_for_cell(
    symbol: str,
    resolution_id: str,
    *,
    labels_version: str = "v1",
    cost_stop_ratio_max: float,
) -> tuple[list[R2CellCensus], str]:
    """Lê `labels.parquet` da célula e devolve `(censo por lado, config_hash)`.

    `NOFILL` é excluído: a linha nunca virou posição, então não há custo de
    ida e volta a comparar contra stop nenhum. Mesma exclusão que
    `src.models.dataset.side_subset` faz no treino — aqui pelo motivo
    econômico, lá pelo estatístico, e as duas coincidem."""
    label_dir = labels_symbol_tf_dir(symbol, labels_version, resolution_id=resolution_id)
    path = label_dir / "labels.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"census_for_cell: {path} não existe -- rode o backfill de labels para "
            f"{symbol}/{resolution_id} antes (src.labels.backfill_multi_symbol)"
        )
    df = pl.read_parquet(path, columns=list(_COLS)).filter(
        pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL"
    )
    hashes = df["config_hash"].unique().to_list()
    if len(hashes) != 1:
        raise ValueError(
            f"census_for_cell: {path} combina {len(hashes)} config_hash distintos "
            f"({hashes}) -- um censo sobre labels de regimes diferentes não descreve "
            "nenhum deles (mesmo espírito de B15/verify_config_hash)"
        )
    out: list[R2CellCensus] = []
    for side in (1, -1):
        sub = df.filter(pl.col("side") == side)
        out.append(
            census_from_arrays(
                symbol=symbol,
                resolution_id=resolution_id,
                side=side,
                entry_price=sub["entry_price_limit"].to_numpy().astype(np.float64),
                tp_price=sub["tp_price"].to_numpy().astype(np.float64),
                sl_price=sub["sl_price"].to_numpy().astype(np.float64),
                cost_entry_bps=sub["cost_entry_bps"].to_numpy().astype(np.float64),
                cost_exit_bps=sub["cost_exit_bps"].to_numpy().astype(np.float64),
                cost_stop_ratio_max=cost_stop_ratio_max,
            )
        )
    return out, str(hashes[0])


def run_r2_admissibility_census(
    *,
    symbols: Sequence[str] = SYMBOLS,
    resolutions: Sequence[str] = RESOLUTIONS,
    labels_version: str = "v1",
    out_dir: Path = EXPERIMENTS_DIR,
) -> Path:
    """Roda o censo nas células pedidas e persiste o relatório.

    Célula ausente em disco é **reportada como ausente**, não silenciada e
    não inventada (B23): o `skipped` do payload nomeia cada uma e o motivo."""
    ratio = float(load_constant("cost_stop_ratio_max"))
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for symbol in symbols:
        for resolution_id in resolutions:
            try:
                cells, config_hash = census_for_cell(
                    symbol,
                    resolution_id,
                    labels_version=labels_version,
                    cost_stop_ratio_max=ratio,
                )
            except FileNotFoundError as exc:
                skipped.append(
                    {"symbol": symbol, "resolution_id": resolution_id, "motivo": str(exc)}
                )
                logger.warning(
                    "analysis.r2_admissibility_census.celula_ausente",
                    symbol=symbol,
                    resolution_id=resolution_id,
                )
                continue
            for cell in cells:
                row = asdict(cell)
                row["labels_config_hash"] = config_hash
                rows.append(row)
                logger.info(
                    "analysis.r2_admissibility_census.celula",
                    symbol=cell.symbol,
                    resolution_id=cell.resolution_id,
                    side=cell.side,
                    n_linhas=cell.n_linhas,
                    frac_viola_r2=round(cell.frac_viola_r2, 5),
                    breakeven_mediano=round(cell.breakeven_q["p50"], 5),
                )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "measurement_provenance": (
            "MEASURED -- R2 (custo_round_trip <= cost_stop_ratio_max * stop, CLAUDE.md "
            "§0.2) aplicada POR LINHA sobre data/labels/{symbol}/{resolution_id}/"
            "{version}/labels.parquet, excluindo NOFILL. Todas as colunas usadas são "
            "conhecidas em t0 (entry_price_limit/tp_price/sl_price/custos), nenhuma "
            "depende de preço de fill. ADR-005 §13 v2 §13.16.3 / item 11b de §13.17. "
            "AG-296 (R2 nunca aplicada em src/models/) e AG-297 (TP abaixo do custo). "
            "DECISION-SUPPORT: nenhum pipeline de treino/execução lê este artefato."
        ),
        "cost_stop_ratio_max": ratio,
        "labels_version": labels_version,
        "by_cell": rows,
        "skipped": skipped,
    }
    out_path = _write_atomic(
        out_dir / "r2_admissibility_census.json",
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    logger.info(
        "analysis.r2_admissibility_census.done",
        n_celulas=len(rows),
        n_skipped=len(skipped),
        report_path=str(out_path.resolve()),
    )
    return out_path


if __name__ == "__main__":  # pragma: no cover -- casca de CLI
    parser = argparse.ArgumentParser(
        description=(
            "Censo de admissibilidade R2 por linha da população de modelagem "
            "(ADR-005 §13 v2, §13.16.3). Não filtra nem altera nada."
        )
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=list(SYMBOLS),
        help="Símbolos a auditar (default: os 5 do universo).",
    )
    parser.add_argument(
        "--resolutions",
        nargs="+",
        default=list(RESOLUTIONS),
        help="Resoluções a auditar (default: R1 R2 R3).",
    )
    parser.add_argument("--labels-version", type=str, default="v1")
    args = parser.parse_args()

    report_path = run_r2_admissibility_census(
        symbols=args.symbols,
        resolutions=args.resolutions,
        labels_version=args.labels_version,
    )
    logger.info(
        "analysis.r2_admissibility_census.cli_done", report_path=str(report_path.resolve())
    )
