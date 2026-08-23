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
from src.labels.triple_barrier import LabelConfig, verify_config_hash
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

# Fase 4 (2026-08-17, AG-036/065) — única fonte de mapeamento resolution_id
# -> bar_source de Feature/Regime Engine, mesmo escopo de produção de
# `src.data.build_dollar_bars.CALIBRATION_TF_BY_RESOLUTION`. Propositalmente
# um dict FECHADO, não um `f"dollar_{resolution_id.lower()}"` genérico -- um
# resolution_id sem bar_source mapeado aqui levanta ValueError explícito
# em vez de tentar um bar_source que `_sources.load_bars` não suporta.
#
# R2/R3 adicionados 2026-08-22 (AG-100, decisao_manager_2026-08-21):
# Manager confirmou R2/R3 como escopo de PRODUÇÃO (revoga a citação de
# PRD_V4_1.md "R2/R3 são pesquisa, nunca alvo de produção" -- doc já
# obsoleto por decisão canônica do projeto), condicionado à recalibração
# CAUSAL do threshold dollar-bar (`AG-124`) ter fechado -- fechou
# 2026-08-22 (15/15 células reprocessadas, validação item 22 positiva).
# Editar este dict ANTES disso teria sido cosmético (labels não
# existiam ainda, e as barras `dollar_r2`/`dollar_r3` em disco
# precisavam ser recalibradas de qualquer forma) -- por isso ficou
# represado até agora, não esquecido.
_BAR_SOURCE_BY_RESOLUTION: dict[str, str] = {
    "R1": "dollar_r1",
    "R2": "dollar_r2",
    "R3": "dollar_r3",
}


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
    resolution_id: str | None = None,
    vol_estimator_id: str | None = None,
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
    "correto" anterior pra preservar nesse caso.

    `resolution_id`/`vol_estimator_id` (2026-08-17, Fase 4 da migração
    Parkinson+dollar-bar, achado G2/G4 da revisão `project_assurance` —
    peça de orquestração que faltava: até esta mudança, nem
    `build_t1_features` nem `build_regimes` recebiam `bar_source` daqui,
    então mesmo um `resolution_id` chegando até este ponto produziria
    labels R1 casados com features/regime de 15m, incoerente e
    silencioso). `resolution_id=None` (default) preserva bit-exato:
    labels via `tf` (grade de tempo), features/regime via
    `bar_source="time_15m"`. `resolution_id="R1"` propaga a MESMA grade
    pros três -- `load_labels_v1(resolution_id=...)` pros labels,
    `bar_source` derivado de `_BAR_SOURCE_BY_RESOLUTION` pra features E
    regime. Deliberadamente UM parâmetro de grade, não dois independentes
    (`resolution_id` + `bar_source` livres): dois parâmetros que pudessem
    divergir (`resolution_id="R1"` com `bar_source` default `"time_15m"`,
    por exemplo) reintroduziriam exatamente a incoerência silenciosa que
    este item do plano existe pra fechar. `"R1"`/`"R2"`/`"R3"` têm
    `bar_source` mapeado hoje (`AG-100`, 2026-08-22 -- R2/R3 promovidas a
    escopo de PRODUÇÃO pelo Manager, condicionado à recalibração causal do
    threshold dollar-bar, `AG-124`, fechada no mesmo dia -- revoga a citação
    de `PRD_V4_1.md` "R2/R3 são pesquisa", doc já obsoleto por decisão
    canônica do projeto); `resolution_id` fora do mapa levanta `ValueError`
    explícito aqui, nunca tenta um `bar_source` que `_sources.load_bars`
    não suporta.

    **`verify_config_hash` (B15) wireado no caminho real, 2026-08-23,
    `AG-140`.** Achado do `stage_readiness_audit` (2026-08-22): a função já
    existia, testada isoladamente (`src/labels/triple_barrier.py`), mas
    nenhum chamador fora de `src/labels/` a invocava — em particular, este
    módulo (o único ponto real onde `labels.parquet` é carregado pra
    montar o frame de treino/backtest) não checava `config_hash` nenhum.
    Um `labels.parquet` gerado sob uma config antiga (`tp_atr_mult`/
    `sl_atr_mult`/`time_stop_ms`/`atr_window_ms`/`fill_timeout_ms`/fees
    mudados em `constants.yaml` depois do backfill) passaria hoje
    despercebido pro treino — exatamente o cenário que B15 existe pra
    impedir. Agora: logo após carregar `labels`, `execution_config =
    LabelConfig.from_constants(estimator_id=vol_estimator_id, tf=tf,
    resolution_id=resolution_id)` — MESMO `vol_estimator_id` já recebido
    aqui (nunca um estimador separado/divergente pra label vs. feature/
    regime, mesmo princípio de "uma grade só" já documentado acima —
    também por isso `resolution_id` setado agora EXIGE `vol_estimator_id`
    explícito, mesma regra que `LabelConfig.from_constants` já impunha:
    sem essa exigência, `vol_estimator_id=None` computaria features com o
    estimador default enquanto os labels reais de R1/R2/R3 foram gerados
    com Parkinson explícito — inconsistência silenciosa, não coberta por
    nenhum teste até este achado). `verify_config_hash(labels,
    execution_config)` levanta `ConfigHashMismatchError` (falha alta,
    mesma disciplina de `assert_label_invariants`) se o hash embutido no
    arquivo divergir. **Não executado empiricamente contra os
    `labels.parquet` reais nesta sessão** (Claude não roda `.py` — ver
    `CLAUDE.md`, protocolo de execução): se `constants.yaml` de fato
    divergiu de quando os labels tf=15m foram gerados, este wireup vai
    revelar isso na primeira chamada real — um achado genuíno a registrar,
    não um bug desta correção. Rode `uv run pytest tests/unit/
    test_models_dataset.py -k config_hash` e, se disponível, `python -c
    "from src.models import dataset; dataset.build_modeling_frame()"` pra
    confirmar contra dado real.

    **Achado de auditoria corrigido aqui (`audit_engineering`, 2026-08-17):
    a mesma garantia de UM parâmetro de grade valia só pro eixo
    `resolution_id`, não pro eixo `tf`.** Sob `resolution_id=None`,
    `bar_source` era hardcoded `"time_15m"` incondicionalmente -- um
    `tf="30m"`/`"1h"` chegaria corretamente a `load_labels_v1` E a
    `CPCVConfig.grade_id` (via `pipeline.py`), mas features/regime
    continuariam vindo da grade de 15m, silenciosamente incoerente. Não
    era explorável no momento do achado (`data/labels/` só tem subpasta
    `15m/` pros 5 símbolos hoje -- `load_labels_v1(tf="30m")` levanta
    `FileNotFoundError` antes de qualquer join), mas o projeto está
    ativamente construindo suporte multi-TF M15/M30/H1 (M2, commits
    recentes) -- no momento em que labels de 30m/1h existirem em disco,
    esse caminho vira ativo. Corrigido pela mesma disciplina de falhar
    alto: `tf` só pode ser `"15m"` quando `resolution_id is None`, porque
    `_sources.load_bars`/Feature Engine não suportam nenhuma outra grade
    de TEMPO ainda (só `"time_15m"`/`"dollar_r1"` existem como
    `bar_source` válido hoje) -- estender isso é trabalho de escopo
    multi-TF do Feature/Regime Engine, não desta migração."""
    if resolution_id is not None and resolution_id not in _BAR_SOURCE_BY_RESOLUTION:
        raise ValueError(
            f"build_modeling_frame: resolution_id={resolution_id!r} sem bar_source de "
            "Feature/Regime Engine mapeado -- suportado hoje: "
            f"{sorted(_BAR_SOURCE_BY_RESOLUTION)} (dict FECHADO por desenho, ver "
            "_BAR_SOURCE_BY_RESOLUTION -- AG-100, 2026-08-22)"
        )
    if resolution_id is not None and vol_estimator_id is None:
        raise ValueError(
            f"build_modeling_frame: resolution_id={resolution_id!r} exige vol_estimator_id "
            "explícito -- mesma exigência de LabelConfig.from_constants (não há bar_ms sob "
            "dollar bar pra derivar um estimador default). Os labels reais de produção sob "
            "resolution_id foram gerados com estimator_id explícito (ex. 'parkinson_w20', "
            "run_and_write_labels_dollar_bar_parkinson) -- deixar vol_estimator_id=None aqui "
            "computaria features/regime com um estimador diferente do que os labels assumem, "
            "silenciosamente (AG-140)."
        )
    if resolution_id is None and tf != "15m":
        raise ValueError(
            f"build_modeling_frame: tf={tf!r} sem bar_source de Feature/Regime Engine "
            "mapeado -- só 'time_15m' existe hoje (achado de auditoria, 2026-08-17: "
            "labels/CPCV honrariam tf='30m'/'1h', mas features/regime ficariam presos em "
            "15m, incoerência silenciosa). Suporte multi-TF do Feature/Regime Engine é "
            "trabalho separado, fora do escopo desta migração."
        )
    bar_source = (
        "time_15m" if resolution_id is None else _BAR_SOURCE_BY_RESOLUTION[resolution_id]
    )

    labels = cpcv.load_labels_v1(labels_version, symbol=symbol, tf=tf, resolution_id=resolution_id)
    execution_config = LabelConfig.from_constants(
        estimator_id=vol_estimator_id, tf=tf, resolution_id=resolution_id
    )
    verify_config_hash(labels, execution_config)
    labels = labels.with_row_index("_pos")
    start, end = date_bounds(labels)

    features_df = features_build.build_t1_features(
        symbol, start, end, bar_source=bar_source, vol_estimator_id=vol_estimator_id
    )
    regimes_df = regime_build.build_regimes(
        symbol, start, end, bar_source=bar_source, vol_estimator_id=vol_estimator_id
    )

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
        resolution_id=resolution_id,
        bar_source=bar_source,
        vol_estimator_id=vol_estimator_id,
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
