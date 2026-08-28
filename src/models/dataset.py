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

import numpy as np
import polars as pl
import structlog

from src.features import build as features_build
from src.features.build import T1_FEATURE_IDS
from src.labels import r2_admissibility
from src.labels.triple_barrier import LabelConfig, verify_config_hash
from src.regime import build as regime_build
from src.validation import cpcv

from ._constants import load_constant

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

# Achado real (audit_engineering, 2026-08-24) -- ids das 4 features T2 de
# futures-positioning (Lote C, H5) que exigem `load_futures_positioning=
# True` em `features_build.build_t1_features`. Mesmos ids de `src.features.
# build.SUPPORT_FEATURE_IDS`, duplicado aqui só como um `frozenset` pra
# checagem O(1) de interseção com `extra_feature_ids` -- não é uma segunda
# fonte de verdade sobre QUAIS features existem (`build.SUPPORT_FEATURE_
# IDS` continua sendo isso), só sobre quais delas precisam desse
# carregamento específico.
_FUTURES_POSITIONING_FEATURE_IDS: frozenset[str] = frozenset(
    {
        "E08f_oi_notional",
        "E14f_toptrader_ls_ratio",
        "E15f_toptrader_ls_z",
        "E16f_global_ls_ratio",
        "E17f_retail_vs_top_spread",
        "E18f_taker_ls_vol_ratio",
    }
)


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
    extra_feature_ids: tuple[str, ...] = (),
    use_geometry_by_combo: bool = False,
) -> ModelingFrame:
    """`extra_feature_ids` (AG-032, 2026-08-23) — colunas de feature ALÉM
    de `T1_FEATURE_IDS` a incluir em `mf.data`, ex. `C07_vol_pctile_
    expanding`/`D03f_volume_z_expanding`/`E02f_funding_z_expanding` (saíram
    do conjunto de treino do Alpha, mas `compute_t1_features` continua
    calculando as 3 — só não entram no `join_cols` default). Uso
    EXCLUSIVAMENTE de análise pós-hoc (`src/analysis/`, nunca insumo de
    treino/seleção de feature, mesma fronteira de `importlinter` já
    documentada em `CLAUDE.md`) que precise ler essas colunas sobre um
    `ModelingFrame` real, sem reintroduzi-las em `T1_FEATURE_IDS`. Default
    `()` preserva o comportamento anterior byte a byte — nenhum caller
    existente passa este argumento. Não interage com a proteção de purge
    do CPCV (`features_build.compute_max_feature_lookback_ms` é chamada
    separadamente por `pipeline.py`/`leakage.py`, sempre com
    `T1_FEATURE_IDS`, nunca com `extra_feature_ids`) — pedir uma das 3
    features expanding aqui é seguro justamente porque `mf.data` não é
    insumo de CPCV, só de análise pós-hoc.

    `t0_start`/`t0_end` (ISO date, inclusive, ex. "2021-12-01") filtram o
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
    _overlap = set(extra_feature_ids) & set(T1_FEATURE_IDS)
    if _overlap:
        raise ValueError(
            f"build_modeling_frame: extra_feature_ids={sorted(_overlap)} já está em "
            "T1_FEATURE_IDS -- passaria coluna duplicada pro join, sinal de uso incorreto "
            "(extra_feature_ids é só pra colunas FORA do conjunto de treino do Alpha)"
        )

    labels = cpcv.load_labels_v1(labels_version, symbol=symbol, tf=tf, resolution_id=resolution_id)
    # AG-260 -- a config de VERIFICAÇÃO tem que ser resolvida sob a mesma
    # regra de geometria que o WRITER usou (`backfill_multi_symbol.
    # run_and_write_labels_dollar_bar_parkinson(use_geometry_by_combo=...)`),
    # senão `verify_config_hash` compara contra uma geometria que não é a
    # dos labels em disco e o pipeline inteiro trava em
    # `ConfigHashMismatchError`. O default `False` mantém o par
    # escrita/leitura no global, bit-exato -- os dois lados só migram
    # juntos, por decisão explícita, nunca um sem o outro.
    execution_config = LabelConfig.from_constants(
        estimator_id=vol_estimator_id,
        tf=tf,
        resolution_id=resolution_id,
        symbol=symbol,
        use_geometry_by_combo=use_geometry_by_combo,
    )
    verify_config_hash(labels, execution_config)
    labels = labels.with_row_index("_pos")
    start, end = date_bounds(labels)

    # Achado real (audit_engineering, 2026-08-24, pedido do usuário --
    # "auditar se o LightGBM está pronto pra receber a totalidade das
    # features"): `build_t1_features` carregava D07f (klines_1m bruto,
    # ~15-96x mais linhas que bars_15m) e as 4 colunas de metrics de
    # E08f-E18f por padrão, SEM NENHUM caller aqui pedir -- na época,
    # T1_FEATURE_IDS (só 7) não usava nenhuma das duas, e ambas eram
    # descartadas no join_cols abaixo a menos que extra_feature_ids as
    # pedisse explicitamente. Custo de IO real pago à toa em TODO treino
    # real do Alpha.
    #
    # **[CORRIGIDO 2026-08-27, `AG-365`]** A checagem original só olhava
    # `extra_feature_ids`, nunca `T1_FEATURE_IDS` -- premissa segura
    # SÓ enquanto o conjunto T1 fosse fixo e nunca precisasse dessas
    # fontes. `AG-362` (mesmo dia, sessão paralela) promoveu 15 features
    # L3→T1 -- `T1_FEATURE_IDS` foi de 7 pra 22, incluindo
    # `E14f_toptrader_ls_ratio`/`E16f_global_ls_ratio` (2 das 6 de
    # `_FUTURES_POSITIONING_FEATURE_IDS`) DIRETO no vetor base, não via
    # `extra_feature_ids`. A checagem antiga continuou devolvendo `False`
    # incondicionalmente pra essas duas -- `load_futures_positioning`
    # nunca ligava, as 2 colunas chegavam 100% nulas em produção,
    # `side_subset` (`AG-300`) barrava com `DeadFeatureColumnError` no
    # primeiro fold real (`--all-combinations`, BTCUSDT/R1, achado ao
    # vivo rodando o retreino canônico). Mesma classe de furo que `AG-300`
    # já tinha fechado uma vez em `side_subset` (conjunto checado
    # diferente do conjunto de fato treinado) -- aqui reaparece um nível
    # acima, na decisão de QUAL DADO CARREGAR, não em qual coluna filtrar.
    # Correção estrutural, não pontual: a checagem agora olha a UNIÃO de
    # `T1_FEATURE_IDS` (sempre ativo) com `extra_feature_ids` (opcional),
    # nunca só o segundo -- autocorrige se T1 mudar de composição de novo
    # no futuro, sem exigir sincronização manual entre os dois módulos.
    _active_feature_ids = frozenset(features_build.T1_FEATURE_IDS) | frozenset(extra_feature_ids)
    _needs_d07f = "D07f_taker_imbalance_1m_agg" in _active_feature_ids
    _needs_futures_positioning = bool(_active_feature_ids & _FUTURES_POSITIONING_FEATURE_IDS)

    features_df = features_build.build_t1_features(
        symbol,
        start,
        end,
        bar_source=bar_source,
        vol_estimator_id=vol_estimator_id,
        load_taker_imbalance_1m=_needs_d07f,
        load_futures_positioning=_needs_futures_positioning,
    )
    # `build_regimes` reusa `build_t1_features` internamente pra B07/C07/
    # E02f/E27f (Regime Engine) -- NUNCA precisa de D07f nem das 4
    # colunas de futures-positioning, incondicionalmente (não depende de
    # `extra_feature_ids`, que é escopo só do frame de FEATURES, não do
    # de regime). `False`/`False` explícitos, mesmo achado acima.
    regimes_df = regime_build.build_regimes(
        symbol,
        start,
        end,
        bar_source=bar_source,
        vol_estimator_id=vol_estimator_id,
        load_taker_imbalance_1m=False,
        load_futures_positioning=False,
    )

    bar_table = features_df.with_columns(
        pl.col("open_time").cast(pl.Int64).alias("_open_time_ms"),
        pl.col("close_time").cast(pl.Int64).alias("_close_time_ms"),
    )
    # AG-202 (2026-08-24) -- `open_time` duplicado colide neste join. Causa
    # real (não um bug em `src.data.bars` -- ver `audit/architecture_gaps_
    # log.yaml::AG-202`, addendum_correcao_diagnostico): raríssimo, 2 trades
    # da Binance no mesmo milissegundo caindo numa fronteira de
    # recalibração do walk-forward produzem 2 barras dollar com o MESMO
    # `open_time` -- uma "fantasma" (duração zero, 1 trade, fecha sozinha;
    # comportamento JÁ TESTADO e deliberado de `bars.threshold_bars_step`,
    # ver `tests/unit/test_data_bars.py::
    # test_threshold_bars_drain_sobrevive_a_troca_de_threshold_entre_
    # periodos`) e uma real (duração > 0). `build_regimes` reusa `build_t1_
    # features` internamente e herda a mesma duplicata -- o classificador
    # de regime tem histerese (estado com memória), então processa as 2
    # linhas em sequência e produz 2 avaliações distintas pro mesmo
    # `open_time`. Este join assumia `open_time` único -- nunca foi um
    # contrato garantido por `bars.py`. Dedup explícito, 2 partes:
    n_bar_rows_before = bar_table.height
    # (1) bar_table por open_time, mantendo a barra com MAIOR close_time --
    # a fantasma tem close_time==open_time (duração zero, sempre o MENOR
    # close_time do grupo); a real tem duração > 0. Ordenar (open_time,
    # close_time) ascendente e manter o ÚLTIMO por open_time (mesmo idioma
    # de `alpha.py::_unique_test_bars`, AG-202 irmão) garante a barra real.
    bar_table = bar_table.sort(["_open_time_ms", "_close_time_ms"]).unique(
        subset=["_open_time_ms"], keep="last", maintain_order=True
    )
    n_bar_dropped = n_bar_rows_before - bar_table.height
    if n_bar_dropped > 0:
        logger.warning(
            "models.dataset.build_modeling_frame_open_time_duplicado",
            n_dropped=n_bar_dropped,
            detail="AG-202 -- barra-fantasma (duração zero) descartada, "
            "mantida a barra real (maior close_time) por open_time",
        )

    regime_small = regimes_df.select(
        pl.col("t0").dt.epoch(time_unit="ms").alias("_open_time_ms"),
        pl.col("regime").cast(pl.Utf8).alias(REGIME_COL),
        pl.col("tradeable"),
    )
    # (2) regime_small por open_time, mantendo a ÚLTIMA avaliação na ordem
    # sequencial original (sem reordenar) -- o classificador processa
    # barra a barra com histerese, então a última avaliação pro mesmo
    # open_time reflete o estado ASSENTADO depois de já ter visto as 2
    # linhas (não a intermediária, que só existiu por causa da fantasma).
    n_regime_rows_before = regime_small.height
    regime_small = regime_small.unique(
        subset=["_open_time_ms"], keep="last", maintain_order=True
    )
    n_regime_dropped = n_regime_rows_before - regime_small.height
    if n_regime_dropped > 0:
        logger.warning(
            "models.dataset.build_modeling_frame_regime_open_time_duplicado",
            n_dropped=n_regime_dropped,
            detail="AG-202 -- avaliação de regime extra pro mesmo open_time "
            "(causada pela barra-fantasma), mantida a ÚLTIMA "
            "(estado assentado após histerese)",
        )

    bar_table = bar_table.join(regime_small, on="_open_time_ms", how="left")

    labels2 = labels.with_columns(pl.col("t0").dt.epoch(time_unit="ms").alias("_close_time_ms"))
    join_cols = [
        "_close_time_ms",
        *T1_FEATURE_IDS,
        *extra_feature_ids,
        REGIME_COL,
        TRADEABLE_COL,
    ]
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


def side_subset(
    frame: pl.DataFrame, *, side: int, feature_ids: tuple[str, ...], enforce_r2: bool = True
) -> pl.DataFrame:
    """Sub-população de modelagem do Alpha (M_long `side=1` / M_short
    `side=-1`, B18): descarta NOFILL (§3.7 — ruído de execução, não sinal,
    instrução explícita da task) e linhas sem features T1 (warmup,
    `min_warmup_bars`). NÃO filtra por regime.

    **[CORRIGIDO 2026-08-27, `AG-343`]** Este docstring afirmava que
    `regime` entra como variável categórica one-hot de 5 níveis
    diretamente no vetor de treino (§2.13) -- falso desde 2026-08-21
    (`AG-343`, handoff de `src/models/`): `src.models.alpha.DESIGN_
    COLUMNS` removeu o one-hot de regime (ratificado pelo Manager, ADR-001
    §2.7, "regime = gate de risco, não feature preditiva"), mantendo só as
    7 `T1_FEATURE_IDS`. `regime` continua saindo desta função sem filtro
    (`side_subset` nunca filtrou por ele), mas hoje é consumido só como
    GATE de risco (`src.risk.limits::control_01_regime_tradeavel`), não
    como feature do Alpha -- este docstring nunca foi atualizado pra
    refletir a mudança, apesar de ser o módulo que produz a própria
    coluna citada.

    `enforce_r2` (achado real 2026-08-27, handoff de `src/models/`,
    `AG-296`/`AG-297`): R2 -- uma das cinco restrições invioláveis,
    `CLAUDE.md` §0.2, `custo_round_trip <= cost_stop_ratio_max * stop` --
    nunca era aplicada nesta camada (`cost_stop_ratio_max` não aparecia em
    nenhum lugar de `src/models/`). Como `stop` de produção é `sl_atr_mult
    * ATR(t0)`, R2 é propriedade da LINHA, não da célula -- medido, até
    27% das linhas de BNBUSDT/R1 violam R2 (`experiments/r2_admissibility_
    census.json`, `src.analysis.r2_admissibility_census`). Pior: `src.
    labels.weights.apply_weights` (`sample_weight = uniqueness *
    |ret_net|`) dá peso MAIOR justamente às linhas mais catastróficas --
    incluindo as que violam R2, que entravam no treino com peso pleno OU
    maior, nunca excluídas. Default `False` preserva bit-exato todo call
    site/teste existente. `True` filtra as linhas que violam R2 ANTES do
    warmup, usando a MESMA fórmula de `src.analysis.r2_admissibility_
    census` (núcleo compartilhado em `src.labels.r2_admissibility`,
    `models/` não pode importar `analysis/`) -- a linha nunca chega no
    cálculo de `sample_weight` rio abaixo, porque nunca entra no treino.
    **[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27, decisão do Manager --
    ver `CLAUDE.md` "Diretrizes de comportamento"]** `False` reproduz o
    comportamento anterior (R2 nunca filtrada) -- passe explicitamente se
    quiser isso.

    **`funding_bps` incluído no custo (`AG-249` Problema A, 2026-08-27,
    achado da sessão paralela).** O custo passado pra `cost_fraction`
    inclui `abs(funding_bps)` -- a mesma coluna real de `labels.parquet`,
    já disponível no frame. Só afeta o resultado quando `enforce_r2=True`
    (o custo entra na conta de `viola_r2`); sem `enforce_r2`, `funding_
    bps` nunca é lido."""
    if side not in (1, -1):
        raise ValueError(f"side_subset: side deve ser 1 ou -1, recebido {side}")
    if not feature_ids:
        raise ValueError(
            "side_subset: feature_ids vazio -- sem conjunto declarado nao ha warmup a "
            "filtrar, e devolver o frame inteiro seria pior que falhar (AG-300)"
        )
    faltando = sorted(set(feature_ids) - set(frame.columns))
    if faltando:
        raise ValueError(
            f"side_subset: coluna(s) de feature ausente(s) no frame: {faltando}. O filtro "
            "de warmup precisa das MESMAS colunas que o trial vai treinar -- filtrar por um "
            "subconjunto diferente e o defeito que AG-300 fecha"
        )
    out = frame.filter(
        (pl.col("side") == side) & (pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    )
    if enforce_r2:
        cost_stop_ratio_max = float(load_constant("cost_stop_ratio_max"))
        cost = r2_admissibility.cost_fraction(
            out["cost_entry_bps"].to_numpy().astype(np.float64),
            out["cost_exit_bps"].to_numpy().astype(np.float64),
            out["funding_bps"].to_numpy().astype(np.float64),
        )
        stop = r2_admissibility.stop_fraction(
            out["entry_price_limit"].to_numpy().astype(np.float64),
            out["sl_price"].to_numpy().astype(np.float64),
        )
        mask_viola = r2_admissibility.viola_r2(
            cost, stop, cost_stop_ratio_max=cost_stop_ratio_max
        )
        n_antes_r2 = out.height
        n_viola = int(mask_viola.sum())
        if n_antes_r2 > 0:  # noqa: SIM108 -- if/else, não ternário: tools/lint/check_unguarded_ratios.py só reconhece guarda em ast.If/ast.Assert, não em IfExp
            frac_viola_r2 = n_viola / n_antes_r2
        else:
            frac_viola_r2 = float("nan")
        if n_viola > 0:
            out = out.filter(pl.Series("_r2_ok", ~mask_viola))
        logger.info(
            "models.dataset.side_subset_r2_gate",
            side=side,
            n_antes=n_antes_r2,
            n_viola_r2=n_viola,
            frac_viola_r2=frac_viola_r2,
            cost_stop_ratio_max=cost_stop_ratio_max,
        )
    # AG-300 -- coluna 100% nula NESTE lado falha alto, ANTES do filtro.
    # Sem isto o filtro abaixo esvazia o conjunto de treino, e "0 linhas"
    # e um sintoma muito pior de diagnosticar do que o nome da coluna: nao
    # diz QUAL das 69 causou. A guarda vive aqui, e nao em
    # `build_t1_features`, porque e aqui que a consequencia aparece -- o
    # builder generico e usado tambem por analise/paridade, que podem
    # legitimamente olhar uma coluna morta sem treinar sobre ela.
    mortas = sorted(fid for fid in feature_ids if out[fid].null_count() == out.height)
    if mortas and out.height > 0:
        raise features_build.DeadFeatureColumnError(
            f"side_subset(side={side}): coluna(s) 100% nula(s) em {out.height} linhas do "
            f"lado: {mortas}. Filtrar warmup por elas zera o conjunto de treino. Uma "
            "coluna sem nenhum valor finito nao e feature -- e ausencia de dado com nome "
            "de feature (ex. D07f_taker_imbalance_1m_agg sob dollar bar, que so tem fonte "
            "quando bar_source == 'time_15m'). Decisao necessaria, NAO tomada aqui: tirar "
            "a coluna do conjunto ativo para esta grade, OU prover a fonte que falta. "
            "Ver ADR-005 §13 v2 §13.2 / AG-300."
        )
    for fid in feature_ids:
        out = out.filter(pl.col(fid).is_not_null())
    return out
