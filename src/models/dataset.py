"""Monta o frame de modelagem do Alpha (Sprint 8, §5.9 passo 1 em diante):
labels/v1/labels.parquet (Sprint 6) enriquecido com as 10 features T1
(Sprint 4) e o regime estrutural (Sprint 5), preservando EXATAMENTE a
ordem/contagem de linhas de `src.validation.cpcv.load_labels_v1()` — os
`train_idx`/`test_idx` posicionais de `cpcv.generate_splits` só são válidos
se o frame que os consome tiver a mesma ordem que o frame que os gerou.

**Achado, não escondido: `data/regimes/regime_v1/regimes.parquet` (Sprint 5,
artefato em disco) está desatualizado — cobre só 2019-12-31→2024-03-30
(148.992 linhas), enquanto `labels/v1/labels.parquet` (Sprint 6, depois do
backfill de dados descrito em `constants.yaml::known_gaps.
dataset_start_mismatch`) cobre 2020-01-01→2026-08-06 (462.682 linhas, os
dois lados).** O Regime Engine (`src.regime.build.build_regimes`) é
determinístico e causal (quantis expansivos, §4) — reexecutá-lo sobre o
intervalo completo dos labels reproduz os MESMOS valores no trecho que já
existia em disco (nenhuma barra usa dado futuro) e simplesmente estende a
cobertura. Este módulo reconstrói o regime EM MEMÓRIA a cada chamada
(~8s medido sobre a série completa, Sprint 8) em vez de sobrescrever o
artefato canônico em `data/regimes/regime_v1/regimes.parquet` — evita
qualquer risco de colidir com outro processo/agente lendo esse arquivo
nesta sessão, e o custo de recomputar é desprezível frente ao custo de
treino do Alpha. Reconciliar o artefato em disco (Sprint 5) é trabalho de
outro sprint, registrado no relatório do Sprint 8, não resolvido aqui por
não ser o escopo desta rodada.

**Junção de chaves de tempo — duas convenções coexistem no repo e são
resolvidas aqui:** `src.labels.triple_barrier` usa `t0 = close_time` da
barra de 15m; `src.regime.classifier` usa `t0 = open_time` da mesma barra
(ver docstring de `src.regime.build`). Este módulo junta em duas etapas:
primeiro features (`open_time`/`close_time` da MESMA barra) com regime
(chave `open_time`), produzindo uma tabela por barra; depois essa tabela
por barra com `labels` via `close_time == labels.t0` — nunca confundindo
as duas convenções."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import polars as pl
import structlog

from src.features import build as features_build
from src.features.build import T1_FEATURE_IDS
from src.regime import build as regime_build
from src.validation import cpcv

logger = structlog.get_logger(__name__)

SYMBOL_DEFAULT = "BTCUSDT"

REGIME_COL = "regime"
TRADEABLE_COL = "tradeable"

# Folga de calendário ao redor de [min(t0), max(t0)] dos labels para
# reconstruir features/regime sobre o MESMO intervalo sem cortar a borda —
# não é parâmetro de domínio (não afeta nenhum resultado estatístico, só
# garante que o pipeline de IO não trunca a última/primeira barra por
# arredondamento de data), mesma categoria de "1 dia de folga" já usada em
# `src.labels.triple_barrier.build_labels_for_symbol`.
_DATE_BUFFER_DAYS = 3  # noqa: magic-number


def date_bounds(labels: pl.DataFrame) -> tuple[str, str]:
    """`[min(t0), max(t0)]` do frame passado, com folga de
    `_DATE_BUFFER_DAYS` — pública porque `src.models.pipeline` (B2 buy-
    and-hold) precisa da MESMA janela de calendário que este módulo usa
    para reconstruir features/regime, não uma janela nova e potencialmente
    inconsistente."""
    t0_min = labels["t0"].min()
    t0_max = labels["t0"].max()
    if t0_min is None or t0_max is None:
        raise ValueError("dataset.date_bounds: labels vazio ou t0 nulo")
    start = (t0_min.date() - timedelta(days=_DATE_BUFFER_DAYS)).isoformat()  # type: ignore[union-attr]
    end = (t0_max.date() + timedelta(days=_DATE_BUFFER_DAYS)).isoformat()  # type: ignore[union-attr]
    return start, end


@dataclass(frozen=True, slots=True)
class ModelingFrame:
    """`data` tem exatamente as colunas de `labels/v1/labels.parquet`
    (`src.labels.triple_barrier.LABEL_COLUMNS`) mais as 10 features T1
    (`T1_FEATURE_IDS`) e `regime`/`tradeable` (Regime Engine), na MESMA
    ordem/contagem de linhas que `src.validation.cpcv.load_labels_v1()`
    produziria sozinho — `cpcv.generate_splits(frame.data)` é seguro de
    chamar diretamente sobre `data`."""

    data: pl.DataFrame
    t1_feature_ids: tuple[str, ...]
    regime_labels_present: tuple[str, ...]


def build_modeling_frame(symbol: str = SYMBOL_DEFAULT) -> ModelingFrame:
    labels = cpcv.load_labels_v1().with_row_index("_pos")
    start, end = date_bounds(labels)

    features_df = features_build.build_t1_features(symbol, start, end)
    regimes_df = regime_build.build_regimes(symbol, start, end)

    bar_table = features_df.with_columns(
        pl.col("open_time").cast(pl.Int64).alias("_open_time_ms"),
        pl.col("close_time").cast(pl.Int64).alias("_close_time_ms"),
    )
    regime_small = regimes_df.select(
        pl.col("t0").dt.epoch(time_unit="ms").alias("_open_time_ms"),
        pl.col("regime").cast(pl.Utf8).alias(REGIME_COL),
        pl.col("tradeable"),
    )
    bar_table = bar_table.join(regime_small, on="_open_time_ms", how="left")

    labels2 = labels.with_columns(pl.col("t0").dt.epoch(time_unit="ms").alias("_close_time_ms"))
    join_cols = ["_close_time_ms", *T1_FEATURE_IDS, REGIME_COL, TRADEABLE_COL]
    merged = labels2.join(bar_table.select(join_cols), on="_close_time_ms", how="left")
    merged = merged.sort("_pos").drop(["_pos", "_close_time_ms"])

    n_missing_regime = int(merged[REGIME_COL].null_count())
    n_missing_feat = int(merged[T1_FEATURE_IDS[0]].null_count())
    regimes_present = tuple(
        sorted(v for v in merged[REGIME_COL].drop_nulls().unique().to_list())
    )
    logger.info(
        "models.dataset.build_modeling_frame",
        symbol=symbol,
        start=start,
        end=end,
        n_rows=merged.height,
        n_missing_regime=n_missing_regime,
        n_missing_t1_first_feature=n_missing_feat,
        regimes_present=regimes_present,
    )
    return ModelingFrame(
        data=merged, t1_feature_ids=T1_FEATURE_IDS, regime_labels_present=regimes_present
    )


def side_subset(frame: pl.DataFrame, *, side: int) -> pl.DataFrame:
    """Sub-população de modelagem do Alpha (M_long `side=1` / M_short
    `side=-1`, B18): descarta NOFILL (§3.7 — ruído de execução, não sinal,
    instrução explícita da task) e linhas sem features T1 (warmup,
    `min_warmup_bars`). NÃO filtra por regime — `regime` entra como
    variável categórica one-hot de 5 níveis (R1..R5; R0 nunca aparece pós-
    warmup) diretamente no vetor de treino, conforme §2.13 literal ("mais o
    regime como variável categórica... consome mais 4 graus de liberdade").
    Excluir R0/R5 é uma decisão isolada da DEFINIÇÃO DE AMBIENTE (§5.4,
    Camada 1 IC screening — ver `src.models.environments`), não do conjunto
    de treino do XGBoost em si."""
    if side not in (1, -1):
        raise ValueError(f"side_subset: side deve ser 1 ou -1, recebido {side}")
    out = frame.filter(
        (pl.col("side") == side)
        & (pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
        & pl.col(T1_FEATURE_IDS[0]).is_not_null()
    )
    for fid in T1_FEATURE_IDS[1:]:
        out = out.filter(pl.col(fid).is_not_null())
    return out
