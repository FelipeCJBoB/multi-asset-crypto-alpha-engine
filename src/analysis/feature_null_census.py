"""Censo de nulos por coluna x célula — ADR-005 §13 v2 (`§13.5-2`, item 3
de `§13.17`), `AG-308`.

**Por que este módulo existe.** `§13.5-2` pede o censo como artefato:
*"com 69 de 69 colunas contendo NaN, isso é informação de primeira ordem
sobre a amostra efetiva e hoje não existe em lugar nenhum"*. Ele só passou
a ser mensurável depois de `AG-300` (a fronteira `nan_to_null=True`): antes,
`NaN` e `null` coexistiam no mesmo Float64 e `null_count()` mentia por
omissão.

**A pergunta que ele responde**, e que nenhum artefato do repo respondia:
*quantas linhas do conjunto de treino cada coluna custa?* Não "quantos
nulos ela tem" — isso é fácil e enganoso, porque colunas com warmup longo
se sobrepõem. O número que decide é o **custo EXCLUSIVO**: linhas em que
`c` é nula **e todas as outras do vetor são válidas**. É o que se ganha de
volta ao tirar `c` do vetor, e só ele.

Exemplo do porquê a distinção importa: duas colunas com 17.520 nulos de
warmup no mesmo prefixo têm `n_null` gigante e custo exclusivo **zero** —
tirar uma delas não devolve linha nenhuma. Reportar só `n_null` faria as
duas parecerem caríssimas.

**Não decide nada.** Não remove coluna, não altera artefato, não é lido por
nenhum pipeline de treino/execução — mesmo status DECISION-SUPPORT de
`feasibility.py`/`production_grade_gate.py`/`r2_admissibility_census.py`.
Existe para que a decisão sobre o vetor (em curso, ver `AG-295` e a
reprogramação de features) seja tomada com o custo em linhas na mesa.

**Fonte:** `src.features.build.build_t1_features` com o `bar_source` da
resolução — o MESMO caminho que `src.models.dataset.build_modeling_frame`
usa, não uma reimplementação. Nenhum label é lido: o censo é sobre a
disponibilidade da feature, não sobre o desfecho.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl
import structlog

from src.features import build as features_build
from src.labels._constants import load_constant

logger = structlog.get_logger(__name__)

EXPERIMENTS_DIR: Final[Path] = Path("experiments")
SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")

#: Quantas colunas mais caras detalhar no log (o JSON leva todas).
_TOP_N_LOG: Final[int] = 5  # noqa: magic-number -- verbosidade de log, não constante de domínio


# ============================================================================
# NÚCLEO PURO (Idioma A) — recebe o frame em memória, devolve dado em memória.
# ============================================================================


@dataclass(frozen=True, slots=True)
class ColumnNullStats:
    feature_id: str
    n_null: int
    frac_null: float
    #: Índice da primeira linha com valor — o warmup EFETIVO desta coluna,
    #: medido em vez de declarado (`B23`). `-1` se a coluna é 100% nula.
    primeira_linha_valida: int
    #: Linhas em que ESTA coluna é nula e TODAS as outras do vetor são
    #: válidas. É o que se recupera tirando-a do vetor, e só isto.
    n_null_exclusivo: int


@dataclass(frozen=True, slots=True)
class CellNullCensus:
    symbol: str
    resolution_id: str
    bar_source: str
    n_features: int
    n_linhas: int
    #: Linhas em que TODAS as `feature_ids` são válidas — a população que
    #: `side_subset` de fato entrega ao treino.
    n_linhas_todas_validas: int
    frac_retida: float
    n_colunas_mortas: int
    colunas_mortas: list[str]
    #: Retencao DESCONTANDO as colunas mortas. Achado da 1a execucao real:
    #: com uma unica coluna 100% nula no vetor, `n_linhas_todas_validas` e
    #: ZERO e o agregado nao informa nada -- a coluna morta domina e
    #: esconde o custo de todas as outras. Este par e o numero acionavel:
    #: quanto o vetor reteria depois de resolvida a coluna morta.
    n_linhas_todas_validas_sem_mortas: int
    frac_retida_sem_mortas: float
    por_coluna: list[dict[str, Any]]


def column_null_stats(
    df: pl.DataFrame, feature_ids: tuple[str, ...]
) -> tuple[ColumnNullStats, ...]:
    """Estatística de nulos por coluna, incluindo o custo EXCLUSIVO.

    Núcleo puro: `df` já em memória, nenhum IO. `feature_ids` precisa estar
    contido nas colunas de `df` — ausência falha alto em vez de ser tratada
    como coluna vazia (uma coluna que não existe e uma coluna 100% nula são
    problemas diferentes e merecem mensagens diferentes)."""
    faltando = sorted(set(feature_ids) - set(df.columns))
    if faltando:
        raise KeyError(
            f"column_null_stats: coluna(s) ausente(s) no frame: {faltando}. Uma coluna "
            "inexistente não é o mesmo que uma coluna vazia -- não é possível medir custo "
            "de nulo sobre algo que não foi calculado"
        )
    if not feature_ids:
        raise ValueError("column_null_stats: feature_ids vazio -- nada a medir")

    sub = df.select(feature_ids)
    # `n_outras_nulas` = quantas OUTRAS colunas do vetor são nulas na linha.
    # Uma linha só conta como custo exclusivo de `c` se `c` é nula e esse
    # contador (excluindo `c`) é zero.
    n_nulas_por_linha = sub.select(
        pl.sum_horizontal([pl.col(f).is_null().cast(pl.Int32) for f in feature_ids]).alias("_n")
    )["_n"]

    out: list[ColumnNullStats] = []
    for fid in feature_ids:
        col = sub[fid]
        is_null = col.is_null()
        n_null = int(is_null.sum())
        # exclusivo: esta nula E o total de nulas na linha e exatamente 1
        n_excl = int((is_null & (n_nulas_por_linha == 1)).sum())
        primeira = -1 if n_null == sub.height else int(is_null.not_().arg_max() or 0)
        out.append(
            ColumnNullStats(
                feature_id=fid,
                n_null=n_null,
                frac_null=(n_null / sub.height) if sub.height else float("nan"),
                primeira_linha_valida=primeira,
                n_null_exclusivo=n_excl,
            )
        )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class ColumnDistributionStats:
    """ADR-008 Fase 2 — estatística descritiva por feature (bloco 7 do
    consultor: dtype/missing%/mean/std/percentis/min/max). `missing%` já
    vive em `ColumnNullStats.frac_null` (não duplicado aqui) — esta
    classe cobre só o que faltava. Calculada sobre valores NÃO-nulos
    apenas (`drop_nulls`) — incluir `null` na média/percentil
    silenciosamente os trataria como `0.0`, mentira maior que reportar
    `NaN` quando a coluna é 100% nula."""

    feature_id: str
    dtype: str
    n_valid: int
    mean: float
    std: float
    p01: float
    p05: float
    p50: float
    p95: float
    p99: float
    min: float
    max: float


def column_distribution_stats(
    df: pl.DataFrame, feature_ids: tuple[str, ...]
) -> tuple[ColumnDistributionStats, ...]:
    """Núcleo puro, mesmo contrato de erro de `column_null_stats` (coluna
    ausente falha alto, `feature_ids` vazio falha alto)."""
    faltando = sorted(set(feature_ids) - set(df.columns))
    if faltando:
        raise KeyError(
            f"column_distribution_stats: coluna(s) ausente(s) no frame: {faltando}"
        )
    if not feature_ids:
        raise ValueError("column_distribution_stats: feature_ids vazio -- nada a medir")

    out: list[ColumnDistributionStats] = []
    for fid in feature_ids:
        dtype_str = str(df.schema[fid])
        col = df[fid].cast(pl.Float64).drop_nulls()
        n_valid = col.len()
        if n_valid == 0:
            nan = float("nan")
            out.append(
                ColumnDistributionStats(
                    feature_id=fid,
                    dtype=dtype_str,
                    n_valid=0,
                    mean=nan,
                    std=nan,
                    p01=nan,
                    p05=nan,
                    p50=nan,
                    p95=nan,
                    p99=nan,
                    min=nan,
                    max=nan,
                )
            )
            continue
        out.append(
            ColumnDistributionStats(
                feature_id=fid,
                dtype=dtype_str,
                n_valid=n_valid,
                mean=float(col.mean()),  # type: ignore[arg-type]
                std=float(col.std(ddof=1)) if n_valid >= 2 else float("nan"),  # type: ignore[arg-type]
                p01=float(col.quantile(0.01, interpolation="linear")),  # type: ignore[arg-type] # noqa: magic-number -- percentil padrao (1%), nao constante de dominio
                p05=float(col.quantile(0.05, interpolation="linear")),  # type: ignore[arg-type] # noqa: magic-number -- percentil padrao (5%), nao constante de dominio
                p50=float(col.quantile(0.50, interpolation="linear")),  # type: ignore[arg-type] # noqa: magic-number -- mediana, nao constante de dominio
                p95=float(col.quantile(0.95, interpolation="linear")),  # type: ignore[arg-type] # noqa: magic-number -- percentil padrao (95%), nao constante de dominio
                p99=float(col.quantile(0.99, interpolation="linear")),  # type: ignore[arg-type] # noqa: magic-number -- percentil padrao (99%), nao constante de dominio
                min=float(col.min()),  # type: ignore[arg-type]
                max=float(col.max()),  # type: ignore[arg-type]
            )
        )
    return tuple(out)


def census_from_frame(
    df: pl.DataFrame,
    feature_ids: tuple[str, ...],
    *,
    symbol: str,
    resolution_id: str,
    bar_source: str,
) -> CellNullCensus:
    """Núcleo: monta o censo de uma célula a partir do frame já construído."""
    stats = column_null_stats(df, feature_ids)
    dist_stats_by_feature = {
        s.feature_id: asdict(s) for s in column_distribution_stats(df, feature_ids)
    }
    n_todas_validas = df.select(feature_ids).drop_nulls().height
    mortas = sorted(s.feature_id for s in stats if s.primeira_linha_valida == -1)
    por_coluna = sorted(
        (
            {**asdict(s), **dist_stats_by_feature[s.feature_id]}
            for s in stats
        ),
        key=lambda d: (-int(d["n_null_exclusivo"]), -int(d["n_null"]), str(d["feature_id"])),
    )
    vivas = tuple(f for f in feature_ids if f not in set(mortas))
    n_sem_mortas = df.select(vivas).drop_nulls().height if vivas else 0
    return CellNullCensus(
        symbol=symbol,
        resolution_id=resolution_id,
        bar_source=bar_source,
        n_features=len(feature_ids),
        n_linhas=df.height,
        n_linhas_todas_validas=n_todas_validas,
        frac_retida=(n_todas_validas / df.height) if df.height else float("nan"),
        n_colunas_mortas=len(mortas),
        colunas_mortas=mortas,
        n_linhas_todas_validas_sem_mortas=n_sem_mortas,
        frac_retida_sem_mortas=(n_sem_mortas / df.height) if df.height else float("nan"),
        por_coluna=list(por_coluna),
    )


# ============================================================================
# CASCA IMPERATIVA
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


def _bar_source_for(resolution_id: str) -> str:
    """Mesmo mapa de `src.models.dataset._BAR_SOURCE_BY_RESOLUTION`, lido de
    lá em vez de duplicado -- duas tabelas que pudessem divergir sobre qual
    barra é qual resolução é exatamente a classe de bug que `AG-042` gerou."""
    from src.models.dataset import _BAR_SOURCE_BY_RESOLUTION

    if resolution_id not in _BAR_SOURCE_BY_RESOLUTION:
        raise ValueError(
            f"_bar_source_for: resolution_id={resolution_id!r} desconhecido -- "
            f"esperado um de {sorted(_BAR_SOURCE_BY_RESOLUTION)}"
        )
    return _BAR_SOURCE_BY_RESOLUTION[resolution_id]


def census_for_cell(
    symbol: str,
    resolution_id: str,
    *,
    feature_ids: tuple[str, ...],
    start: str,
    end: str,
) -> CellNullCensus:
    """Constrói o frame da célula e delega ao núcleo.

    `apply_warmup_mask=True` de propósito: é o frame que a modelagem de
    fato vê. O prefixo de warmup uniforme faz parte do custo real, não é
    um artefato a descontar."""
    bar_source = _bar_source_for(resolution_id)
    df = features_build.build_t1_features(
        symbol, start, end, apply_warmup_mask=True, bar_source=bar_source
    )
    return census_from_frame(
        df, feature_ids, symbol=symbol, resolution_id=resolution_id, bar_source=bar_source
    )


def run_feature_null_census(
    *,
    symbols: Sequence[str] = SYMBOLS,
    resolutions: Sequence[str] = RESOLUTIONS,
    feature_ids: tuple[str, ...] | None = None,
    start: str | None = None,
    end: str | None = None,
    out_dir: Path = EXPERIMENTS_DIR,
) -> Path:
    """Roda o censo nas células pedidas e persiste.

    `feature_ids=None` resolve para o vetor de produção ADITIVO
    (`T1_FEATURE_IDS + SUPPORT_FEATURE_IDS`, `AG-207`/`AG-234`) **no
    momento da execução** — de propósito: a reprogramação de features em
    curso pode mudar esse conjunto, e o censo deve descrever o vetor que
    existe, não um congelado aqui."""
    from src.labels.backfill_multi_symbol import END_DATE, SYMBOL_START_DATE

    vetor = (
        feature_ids
        if feature_ids is not None
        else features_build.T1_FEATURE_IDS + features_build.SUPPORT_FEATURE_IDS
    )
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for symbol in symbols:
        s_start = start if start is not None else SYMBOL_START_DATE[symbol]
        s_end = end if end is not None else END_DATE
        for resolution_id in resolutions:
            try:
                cell = census_for_cell(
                    symbol, resolution_id, feature_ids=vetor, start=s_start, end=s_end
                )
            except (FileNotFoundError, ValueError, KeyError) as exc:
                skipped.append(
                    {
                        "symbol": symbol,
                        "resolution_id": resolution_id,
                        "motivo": f"{type(exc).__name__}: {exc}",
                    }
                )
                logger.warning(
                    "analysis.feature_null_census.celula_pulada",
                    symbol=symbol,
                    resolution_id=resolution_id,
                    erro=type(exc).__name__,
                )
                continue
            rows.append(asdict(cell))
            piores = cell.por_coluna[:_TOP_N_LOG]
            logger.info(
                "analysis.feature_null_census.celula",
                symbol=cell.symbol,
                resolution_id=cell.resolution_id,
                n_linhas=cell.n_linhas,
                n_linhas_todas_validas=cell.n_linhas_todas_validas,
                frac_retida=round(cell.frac_retida, 5),
                frac_retida_sem_mortas=round(cell.frac_retida_sem_mortas, 5),
                n_colunas_mortas=cell.n_colunas_mortas,
                piores_por_custo_exclusivo=[
                    (str(d["feature_id"]), int(d["n_null_exclusivo"])) for d in piores
                ],
            )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "measurement_provenance": (
            "MEASURED -- nulos por coluna x celula sobre src.features.build."
            "build_t1_features (mesmo bar_source que src.models.dataset."
            "build_modeling_frame usa), apply_warmup_mask=True. So mensuravel apos "
            "AG-300 (nan_to_null=True na fronteira): antes NaN e null coexistiam e "
            "null_count() mentia por omissao. `n_null_exclusivo` = linhas em que a "
            "coluna e nula E todas as outras do vetor sao validas -- o que se recupera "
            "tirando-a, e so isso. ADR-005 §13 v2 §13.5-2 / item 3 de §13.17 / AG-308. "
            "DECISION-SUPPORT: nenhum pipeline de treino/execucao le este artefato."
        ),
        "min_warmup_bars": int(load_constant("min_warmup_bars")),
        "n_features_no_vetor": len(vetor),
        "feature_ids": list(vetor),
        "by_cell": rows,
        "skipped": skipped,
    }
    out_path = _write_atomic(
        out_dir / "feature_null_census.json", json.dumps(payload, indent=2, ensure_ascii=False)
    )
    logger.info(
        "analysis.feature_null_census.done",
        n_celulas=len(rows),
        n_skipped=len(skipped),
        report_path=str(out_path.resolve()),
    )
    return out_path


if __name__ == "__main__":  # pragma: no cover -- casca de CLI
    parser = argparse.ArgumentParser(
        description=(
            "Censo de nulos por coluna x celula (ADR-005 §13 v2 §13.5-2). "
            "Nao remove coluna, nao altera artefato."
        )
    )
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    parser.add_argument("--resolutions", nargs="+", default=list(RESOLUTIONS))
    parser.add_argument("--start", default=None, help="default: SYMBOL_START_DATE do simbolo")
    parser.add_argument("--end", default=None, help="default: END_DATE")
    args = parser.parse_args()

    report_path = run_feature_null_census(
        symbols=args.symbols,
        resolutions=args.resolutions,
        start=args.start,
        end=args.end,
    )
    logger.info("analysis.feature_null_census.cli_done", report_path=str(report_path.resolve()))
