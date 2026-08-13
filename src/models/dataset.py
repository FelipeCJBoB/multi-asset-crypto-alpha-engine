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


def build_modeling_frame(
    symbol: str = SYMBOL_DEFAULT,
    *,
    labels_version: str = "v1",
    tf: str = "15m",
    t0_start: str | None = None,
    t0_end: str | None = None,
) -> ModelingFrame:
    """`t0_start`/`t0_end` (ISO date, inclusive, ex. "2021-12-01") filtram o
    frame FINAL por `t0`, DEPOIS de features/regime terem sido computados
    sobre o histórico COMPLETO de `labels` — nunca antes. `build_t1_features`/
    `build_regimes` não estendem a janela pedida automaticamente
    (`src/features/build.py` docstring); filtrar `labels` antes de
    `date_bounds` reiniciaria as séries expansivas (`C07_vol_pctile_
    expanding`, `E02f_funding_z_expanding`, e o regime que deriva de C07) em
    `t0_start` em vez de no início real do dataset, mudando silenciosamente a
    definição de regime/feature da janela — violaria a instrução do
    PRD_V4_1.md T0.5 ("sem alteração alguma"). Janela `None`/`None` (default)
    preserva o comportamento anterior byte a byte.

    **Achado real, corrigido aqui (§15.6 item 4 do PLANO_MESTRE, preparação
    de engenharia multi-ativo, 2026-08-13):** até esta correção,
    `cpcv.load_labels_v1()` era chamado SEM `symbol=` — sempre carregava
    `labels/BTCUSDT/15m/v1/labels.parquet` (default de `load_labels_v1`),
    não importa qual `symbol` fosse pedido aqui. `symbol="ETHUSDT"` fazia
    `build_t1_features`/`build_regimes` calcularem de verdade sobre dado do
    ETH, mas o `join` final (linha ~129, por `_close_time_ms`) casava essas
    features com os LABELS do BTC (mesmo grid de 15m, timestamps batem por
    coincidência de calendário, não por serem do mesmo ativo) — um frame de
    "features de ETH, alvo de BTC", silenciosamente incoerente. Não é
    hipotético: `src/models/pipeline.py::run_layer1_sprint`,
    `faixa1_6_reconciliation.py`, `faixa2_vol_accelerator_test.py`,
    `faixa2_e3_stability.py`, `faixa2_dsr_and_b2_check.py` já chamam esta
    função com `symbol=symbol` explícito hoje — nenhum notou o bug porque
    nenhum símbolo além de BTCUSDT teve `labels/` gerado até agora
    (pré-requisito que este item do roadmap resolve). `labels_version`/`tf`
    novos, mesmo padrão de `CPCVConfig.tf`/`LabelConfig.tf` (AG-004/005) —
    default `"v1"`/`"15m"` preserva bit-exato todo caller que já passa
    `symbol="BTCUSDT"` (ou usa o default), já que carregar
    `load_labels_v1("v1", symbol="BTCUSDT", tf="15m")` é idêntico a
    `load_labels_v1()` sem argumentos. Callers com `symbol` não-BTC
    corrigem de bug, não mudam de comportamento -- não havia comportamento
    "correto" anterior pra preservar nesse caso."""
    labels = cpcv.load_labels_v1(labels_version, symbol=symbol, tf=tf).with_row_index("_pos")
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

    # Filtro de janela por `t0` — SÓ AQUI, depois de features/regime já
    # computados sobre o histórico completo (ver docstring). `n_rows_pre_
    # janela` fica no log para o filtro nunca ser silencioso.
    # `t0` é `Datetime` UTC-aware (`src.labels.triple_barrier`,
    # `.dt.replace_time_zone("UTC")`) — comparar via `pl.lit(...).str.
    # to_datetime(time_zone="UTC")` em vez de `datetime.fromisoformat` cru
    # (naive) evita erro/mismatch de timezone na comparação.
    n_rows_pre_janela = merged.height
    if t0_start is not None:
        merged = merged.filter(pl.col("t0") >= pl.lit(t0_start).str.to_datetime(time_zone="UTC"))
    if t0_end is not None:
        merged = merged.filter(pl.col("t0") <= pl.lit(t0_end).str.to_datetime(time_zone="UTC"))

    n_missing_regime = int(merged[REGIME_COL].null_count())
    n_missing_feat = int(merged[T1_FEATURE_IDS[0]].null_count())
    regimes_present = tuple(
        sorted(v for v in merged[REGIME_COL].drop_nulls().unique().to_list())
    )
    logger.info(
        "models.dataset.build_modeling_frame",
        symbol=symbol,
        t0_start_filter=t0_start,
        t0_end_filter=t0_end,
        start=start,
        end=end,
        n_rows_pre_janela=n_rows_pre_janela,
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
