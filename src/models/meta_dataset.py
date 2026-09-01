"""Montagem do `meta_training_set` — camada 2 (meta-labeling), F1 de
`docs/meta_model_design_doc_2026-08-22.md` (§3 contrato, §4.3 regra de
doador, §4.7 seleção posicional, §5 pesos, §6 regime, §10.1 asserções).

**O que este módulo faz, em uma frase.** Pega as predições OOF do Alpha,
liga cada sinal (`side_hat != 0`) ao resultado REAL daquele lado nos
labels, e organiza as linhas em meta-folds sob a regra `path_matched` —
produzindo a tabela que o Meta treina.

**O que ele recusa a fazer.** Nunca imputa `tau`, nunca degrada em
silêncio, nunca deixa uma linha de treino entrar sem purge. As quatro
asserções do §10.1 rodam em `assert_no_meta_leakage` e levantam
`MetaLeakageError` — nunca `assert` (some sob `python -O`), nunca
`filter()` (mascara a causa raiz).

**A regra de doador (`path_matched`, D-08/§4.3).** Para o meta-fold `s`
(split `s` do Alpha, path `p`):

    TESTE  = `fold_id == s`        e `_pos ∈ splits[s].test_idx`
    TREINO = `fold_id ∈ path(p)\\{s}` e `_pos ∈ splits[s].train_idx`

A interseção posicional com `train_idx` **não é redundante** — `train_idx`
é o único objeto que carrega purge + embargo (`cpcv.py`). Uma
implementação que colete as linhas do path só por `fold_id` e esqueça a
interseção satisfaz as outras três asserções, produz um dataset MAIOR
(parece melhor) e **desliga B09 inteiro em silêncio**. É o modo de falha
mais provável deste módulo, e é o que a asserção (b) do §10.1 existe para
pegar.

**`group_matched` não está implementado, de propósito** (D-08 da v3): é o
único dos dois braços sem purge e sem embargo, exige uma primitiva de
purge por bloco arbitrário que `cpcv.py` não tem (`AG-153`), e nunca teve
o lado do TESTE definido. É trabalho futuro (F9), não Meta v1 — pedir por
ele levanta, não devolve um resultado silenciosamente pior.

**DESVIO REGISTRADO do §3.1 (chave primária).** O documento declara
`(symbol, t0, side_hat, fold_id, variant, model_id)`. Essa tupla **não é
única** sob `path_matched`: um path tem 3 splits, então uma linha com
`fold_id = f` é TREINO de 2 meta-folds (os outros dois splits do path de
`f`) e TESTE de 1 — três linhas de saída com a mesma tupla. A chave real
precisa de `meta_split_id`. Implementado assim aqui, e reportado ao
Manager como correção de especificação, não como divergência silenciosa.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from src.labels.weights import compute_concurrency_and_uniqueness
from src.regime.classifier import REGIME_LABELS
from src.validation import cpcv

from . import dataset as ds
from ._constants import load_constant
from .backtest_lite import join_signals_to_labels
from .hhi import hhi_from_shares

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------

#: Regra de doador do caminho crítico (D-08). `group_matched` é F9, não v1.
DONOR_RULE_PATH_MATCHED = "path_matched"
DONOR_RULE_GROUP_MATCHED = "group_matched"

ROLE_TRAIN = "train"
ROLE_TEST = "test"

META_STATUS_OK = "OK"
META_STATUS_UNSEEN_REGIME = "UNSEEN_REGIME"
META_STATUS_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
#: Achado real (2026-08-31, BTCUSDT/R2, fold real — não hipotético):
#: `meta.check_design_rank` (§3.4) pode levantar `RankDeficientDesignError`
#: num fold pequeno cuja janela de treino nunca observou algum nível de
#: regime — a dummy correspondente fica com variância zero E colinear com
#: as outras (rank=8 de 9 colunas medido). O design doc nunca declarou
#: operacionalmente o que fazer nesse caso; a decisão aqui segue a MESMA
#: política de `INSUFFICIENT_SAMPLE` (§7.3: "vetar tudo por um problema do
#: acessório mataria a estratégia") — pass-through, nunca veto, nunca
#: degradar pra um design matrix mais simples em silêncio. Status distinto
#: de `INSUFFICIENT_SAMPLE` (causa raiz diferente: colinearidade, não
#: tamanho de amostra) para que o painel por fold (§9) não confunda as
#: duas ao diagnosticar POR QUE um fold não ajustou modelo.
META_STATUS_RANK_DEFICIENT = "RANK_DEFICIENT"

#: Prefixo do one-hot. Existe para desfazer a ambiguidade de nome entre
#: NÍVEL DE REGIME e `resolution_id` (a grade de barra) — sob o
#: classificador por quantis os níveis eram `R0..R5` e a grade é
#: `R1`/`R2`/`R3`; ler `R1` num schema sem prefixo era genuinamente
#: ambíguo. Sob o HMM os níveis são `S0..S{k-1}` (`dataset.hmm_state_labels`),
#: o que remove a ambiguidade na origem.
REGIME_OHE_PREFIX = "regime_ohe_"


def regime_levels_for_source(regime_source: str) -> tuple[str, ...]:
    """Níveis do one-hot, FIXOS A PRIORI dado o classificador (§6.3) —
    nunca derivados do fold: níveis derivados do fold fariam o número de
    colunas mudar por fold, e sob canonicalização por retorno "estado 2 <
    estado 3" não significa volatilidade (`AG-121`), então ordinal seria uma
    relação inventada.

    Sob o HMM devolve só os `k` estados REAIS — o sentinela `NO_DECODE` não
    ganha dummy de propósito: a política declarada para ele é VETO (§6.4),
    e uma coluna que o modelo pudesse ponderar contradiria a política."""
    if regime_source == ds.REGIME_SOURCE_HMM_K4:
        n_states = int(load_constant("canonical_regime_hmm_n_states"))
        return tuple(
            n for n in ds.hmm_state_labels(n_states) if n != ds.REGIME_NO_DECODE_LABEL
        )
    if regime_source == ds.REGIME_SOURCE_QUANTILE_V1:
        return tuple(REGIME_LABELS)
    raise MetaDatasetError(
        f"regime_source={regime_source!r} desconhecido — o Meta precisa dos níveis "
        "fixos a priori para montar o one-hot, e inferi-los do dado observado seria "
        "exatamente o que §6.3 proíbe."
    )

#: Colunas que NUNCA podem entrar no design matrix do Meta. `t1` está aqui
#: porque é insumo de purge e de unicidade, não informação disponível em
#: `t0`; `ret_net`/`barrier_hit`/`y_meta` são o futuro; `fill_assumed` é
#: derivado do futuro; `meta_sample_weight` e as unicidades são calculadas
#: sobre a população de treino e não são informação disponível em `t0`.
#:
#: `ret_net` merece nota: com barreiras simétricas (`tp_atr_mult =
#: sl_atr_mult = 1.5`) e a assimetria de custo maker/taker entre TP e SL,
#: `|ret_net|` medido tem 48,7% da variância explicada pela CLASSE — é
#: quase um classificador do próprio alvo. Por isso ele saiu também do
#: PESO (§5 corrigido, ver `_meta_sample_weight`), não só do design matrix.
META_FORBIDDEN_FEATURES: frozenset[str] = frozenset(
    {
        "t1",
        "barrier_hit",
        "ret_net",
        "y_meta",
        "fill_assumed",
        "meta_sample_weight",
        "uniqueness_universe",
        "uniqueness_subpop",
    }
)

#: Discriminador de artefato pré-D-15 (§3.5, reconciliado em `AG-162`): a
#: AUSÊNCIA destas duas colunas, não uma `schema_version` desconhecida —
#: os artefatos legados não têm versão desconhecida, têm versão inexistente.
_ALPHA_TAU_COLUMNS: tuple[str, ...] = ("tau_long", "tau_short")

_SIDE_LONG = 1
_SIDE_SHORT = -1
_NOFILL = "NOFILL"


class MetaDatasetError(Exception):
    """Erro de contrato na montagem do `meta_training_set`."""


class LegacyPredictionsError(MetaDatasetError):
    """`predictions.parquet` do Alpha sem `tau_long`/`tau_short` — artefato
    anterior a D-15 (`AG-162`). Sem essas colunas o Meta não consegue
    derivar `tau_alpha` (§3.5), e derivar errado é pior que parar."""


class MetaLeakageError(MetaDatasetError):
    """Uma das quatro asserções estruturais do §10.1 falhou. `raise`, nunca
    `assert` (some sob `python -O`), nunca `filter()` (mascara a causa)."""


# ---------------------------------------------------------------------------
# Regra de doador
# ---------------------------------------------------------------------------


def donor_folds_for_path_matched(
    cpcv_result: cpcv.CPCVResult,
) -> dict[int, frozenset[int]]:
    """Para cada meta-fold `s`, o conjunto de folds do Alpha autorizados a
    DOAR linhas de treino: os outros splits do MESMO path (§4.3).

    Por que o mesmo path, e não qualquer fold: `_path_assignment` usa
    1-fatoração round-robin, então dentro de um `path_id` os blocos de teste
    PARTICIONAM os grupos — logo `(symbol, t0)` é único dentro do path e não
    há pseudo-replicação. Um doador de outro path reintroduziria a mesma
    barra várias vezes com `p_alpha` de modelos diferentes."""
    splits_by_path: dict[int, set[int]] = {}
    for split in cpcv_result.splits:
        splits_by_path.setdefault(split.path_id, set()).add(split.split_id)
    return {
        split.split_id: frozenset(splits_by_path[split.path_id] - {split.split_id})
        for split in cpcv_result.splits
    }


# ---------------------------------------------------------------------------
# Guardas
# ---------------------------------------------------------------------------


def assert_alpha_predictions_has_tau(predictions: pl.DataFrame, *, origem: str) -> None:
    """§3.5 — levanta com o caminho do artefato e a instrução de retreinar."""
    faltando = [c for c in _ALPHA_TAU_COLUMNS if c not in predictions.columns]
    if faltando:
        raise LegacyPredictionsError(
            f"predições do Alpha em {origem} não têm {faltando} — artefato anterior a "
            "D-15/AG-162, sem tau persistido. O Meta deriva tau_alpha = tau_long se "
            "side_hat == 1 senão tau_short (§3.5) e não tem como fazer isso aqui. "
            "Retreine o Alpha (src.models.pipeline.run_layer1_sprint) sobre esta célula."
        )


def assert_dense_frame_matches_splits(
    dense: pl.DataFrame, cpcv_result: cpcv.CPCVResult
) -> None:
    """§4.7, guarda falsificável — os splits precisam ter sido gerados sobre
    ESTE frame denso, senão `train_idx`/`test_idx` indexam outra coisa e a
    seleção posicional vira lixo silencioso. Substitui o grep proposto na v1
    do documento, que seria driblável por import indireto."""
    n_splits_rows = int(cpcv_result.group_id.shape[0])
    if dense.height != n_splits_rows:
        raise MetaDatasetError(
            f"frame denso tem {dense.height} linhas mas os splits do CPCV foram "
            f"gerados sobre {n_splits_rows} — `train_idx`/`test_idx` são POSICIONAIS "
            "(§4.7) e indexariam linhas erradas. Gere os splits sobre o mesmo frame "
            "que você está passando aqui."
        )


def _test_masks_by_fold(
    cpcv_result: cpcv.CPCVResult, n_rows: int
) -> dict[int, BoolArray]:
    masks: dict[int, BoolArray] = {}
    for split in cpcv_result.splits:
        mask = np.zeros(n_rows, dtype=bool)
        mask[split.test_idx] = True
        masks[split.split_id] = mask
    return masks


def _train_masks_by_split(
    cpcv_result: cpcv.CPCVResult, n_rows: int
) -> dict[int, BoolArray]:
    masks: dict[int, BoolArray] = {}
    for split in cpcv_result.splits:
        mask = np.zeros(n_rows, dtype=bool)
        mask[split.train_idx] = True
        masks[split.split_id] = mask
    return masks


def assert_no_meta_leakage(table: pl.DataFrame, cpcv_result: cpcv.CPCVResult) -> None:
    """As QUATRO asserções falsificáveis do §10.1.

    `is_oof` não está entre elas de propósito: é constante `True` por
    construção do Alpha, então asseri-lo é tautologia — exatamente a crítica
    que o §10.1 faz à v1 do documento.

        (a) toda linha:       `_pos ∈ splits[fold_id].test_idx`
        (b) linhas de TREINO: `_pos ∈ splits[meta_split_id].train_idx`
        (c) linhas de TREINO: `fold_id != meta_split_id`
        (d) proveniência:     `n_unique(calibrator_id) == 2 × n_unique(fold_id)`
                              e `n_unique(model_id) == 1`

    (b) é a mais importante. Sem ela, uma implementação que colete as linhas
    do path por `fold_id` e esqueça a interseção posicional passa em (a),
    (c) e (d), produz um dataset maior — e desliga purge e embargo inteiros
    sem emitir um aviso sequer.

    **ACHADO (2026-08-30): (c) é redundante sob a geometria REAL do CPCV.**
    O §10.1 apresenta as quatro como independentes. Não são: uma linha de
    treino com `fold_id == meta_split_id = s` precisaria de
    `_pos ∈ test_idx[s]` (por (a)) E `_pos ∈ train_idx[s]` (por (b)), e
    esses conjuntos são disjuntos por construção — logo (b) sempre dispara
    antes e (c) é inalcançável. Mantida mesmo assim: é barata, e não depende
    da disjunção continuar valendo. Um esquema de CV com blocos sobrepostos
    (o espaço que `AG-153` abre) quebraria essa premissa em silêncio, e aí
    (c) passa a ser a única a pegar o caso."""
    if table.height == 0:
        return
    n_rows = int(cpcv_result.group_id.shape[0])
    pos = table["_pos"].to_numpy().astype(np.int64)
    fold_id = table["fold_id"].to_numpy().astype(np.int64)
    meta_split_id = table["meta_split_id"].to_numpy().astype(np.int64)
    is_train = (table["role"] == ROLE_TRAIN).to_numpy()

    test_masks = _test_masks_by_fold(cpcv_result, n_rows)
    train_masks = _train_masks_by_split(cpcv_result, n_rows)

    # (a) — toda linha veio do bloco de TESTE do fold que a produziu.
    for f in np.unique(fold_id):
        sel = fold_id == f
        if int(f) not in test_masks:
            raise MetaLeakageError(
                f"§10.1(a): fold_id={int(f)} não existe entre os splits do CPCV"
            )
        fora = ~test_masks[int(f)][pos[sel]]
        if bool(fora.any()):
            raise MetaLeakageError(
                f"§10.1(a): {int(fora.sum())} linha(s) com fold_id={int(f)} têm `_pos` "
                "FORA de splits[fold_id].test_idx — a predição não é OOF para aquela "
                "linha. Isto é B07 acontecendo."
            )

    # (b) — linhas de treino respeitam purge + embargo do meta-fold.
    for s in np.unique(meta_split_id[is_train]):
        sel = is_train & (meta_split_id == s)
        fora = ~train_masks[int(s)][pos[sel]]
        if bool(fora.any()):
            raise MetaLeakageError(
                f"§10.1(b): {int(fora.sum())} linha(s) de TREINO do meta-fold {int(s)} "
                "têm `_pos` fora de splits[meta_split_id].train_idx — purge e embargo "
                "(B09) NÃO foram aplicados a elas. Provável causa: seleção por "
                "`fold_id` sem a interseção posicional (§4.3)."
            )

    # (c) — o doador nunca é o próprio meta-fold.
    auto_doacao = is_train & (fold_id == meta_split_id)
    if bool(auto_doacao.any()):
        raise MetaLeakageError(
            f"§10.1(c): {int(auto_doacao.sum())} linha(s) de TREINO têm "
            "fold_id == meta_split_id — o meta-fold estaria treinando sobre as "
            "predições do próprio fold que ele testa."
        )

    # (d) — proveniência: 2 calibradores por fold (um por lado), 1 model_id.
    n_model_id = int(table["model_id"].n_unique())
    if n_model_id != 1:
        raise MetaLeakageError(
            f"§10.1(d): {n_model_id} `model_id` distintos na mesma tabela — misturar "
            "dois runs do Alpha misturaria escalas de probabilidade SEM ERRO. "
            "Monte um `meta_training_set` por run."
        )
    # §10.1(d), CORRIGIDO CONTRA O DADO REAL (2026-08-30).
    #
    # O documento manda asserir `n_unique(calibrator_id) == 2 * n_unique(fold_id)`.
    # Medido sobre `artifacts/predictions_alpha` (BTCUSDT/R1, camada1, 15 folds):
    # o valor observado é 10, não 30 — e nunca é 30 em nenhum dos runs em disco
    # (10, 12, 18, 26 conforme a rodada). Dois motivos independentes, ambos
    # estruturais e nenhum deles um defeito do Alpha:
    #   (i)  existe o valor literal "n/a" para linhas sem sinal;
    #   (ii) só 8 dos 15 folds produzem QUALQUER sinal (folds 0,1,2,3,5,6,7,10
    #        ficam em zero), e um par (fold, lado) que nunca sinaliza não
    #        aparece no artefato.
    # A asserção do documento reprovaria todo artefato real que existe.
    #
    # A substituta é MAIS forte, não mais fraca: em vez de contar, verifica a
    # correspondência estrutural linha a linha — o calibrador que carimbou a
    # linha tem de ser exatamente o do `(fold_id, side_hat)` daquela linha.
    # Uma contagem certa com atribuição trocada passaria na regra do
    # documento e é pega por esta.
    esperado = (
        pl.col("model_id")
        + "_side"
        + pl.col("side_hat").cast(pl.Utf8)
        + "_fold"
        + pl.col("fold_id").cast(pl.Utf8)
        + "_calibrator"
    )
    divergentes = table.filter(pl.col("calibrator_id") != esperado)
    if divergentes.height > 0:
        amostra = divergentes.select("fold_id", "side_hat", "calibrator_id").head(3)
        raise MetaLeakageError(
            f"§10.1(d): {divergentes.height} linha(s) com `calibrator_id` que não "
            "corresponde ao par (fold_id, side_hat) da própria linha — a probabilidade "
            "foi calibrada por um calibrador de OUTRO fold ou de OUTRO lado, o que "
            f"quebra a comparabilidade de `p_alpha`. Amostra:\n{amostra}"
        )


def assert_design_matrix_is_clean(columns: tuple[str, ...]) -> None:
    """Mesma disciplina de `DESIGN_COLUMNS` no Alpha: o design matrix é
    validado contra `META_FORBIDDEN_FEATURES` antes de qualquer fit."""
    proibidas = sorted(set(columns) & META_FORBIDDEN_FEATURES)
    if proibidas:
        raise MetaLeakageError(
            f"design matrix do Meta contém coluna(s) proibida(s): {proibidas}. "
            "São o futuro (`ret_net`/`barrier_hit`/`y_meta`), derivadas do futuro "
            "(`fill_assumed`), ou função do alvo (`meta_sample_weight`/`uniqueness_*`). "
            "`t1` é insumo de purge e unicidade, nunca feature."
        )


# ---------------------------------------------------------------------------
# Peças de montagem
# ---------------------------------------------------------------------------


def _derive_side_projected_columns(table: pl.DataFrame) -> pl.DataFrame:
    """`p_alpha`/`score_alpha_raw`/`tau_alpha` são DERIVADAS por seleção de
    lado, nunca colunas físicas do Alpha (§3.2/§3.5/§21). `tau_alpha` segue
    o mesmo padrão já provado de `p_alpha` em vez de introduzir um segundo
    mecanismo de derivação só para si — foi a reconciliação de `AG-162`."""
    is_long = pl.col("side_hat") == _SIDE_LONG
    return table.with_columns(
        p_alpha=pl.when(is_long).then(pl.col("p_long")).otherwise(pl.col("p_short")),
        score_alpha_raw=pl.when(is_long)
        .then(pl.col("score_long_raw"))
        .otherwise(pl.col("score_short_raw")),
        tau_alpha=pl.when(is_long).then(pl.col("tau_long")).otherwise(pl.col("tau_short")),
        # `margin` é projetada no lado: para um short, `p_short - p_long` é a
        # margem a favor da decisão tomada (§3.2).
        margin=pl.col("side_hat").cast(pl.Float64) * (pl.col("p_long") - pl.col("p_short")),
    )


def _derive_target(table: pl.DataFrame, *, include_nofill: bool) -> pl.DataFrame:
    """§3.3 — `y_meta = 1[ret_net > 0]`, PnL líquida.

    Quatro coisas que é fácil errar seguindo o AFML ao pé da letra:
    1. `ret_net` JÁ vem projetado no lado (`triple_barrier` emite uma linha
       por lado). NÃO multiplicar por `side` de novo — dupla projeção.
    2. `ret_net == 0.0` exato → `y_meta = 0`.
    3. `TIME` não é caso especial: o snippet 3.7 do AFML usa `sign(ret·side)`
       e o Exercício 3.3 sugere 0 na vertical; o livro não trava. A regra
       daqui é `1[ret_net > 0]` inclusive em TIME.
    4. `y_meta` ≠ label do Alpha. O Alpha treina `1[barrier_hit == "TP"]`; o
       Meta treina PnL líquida. **A assimetria é o mecanismo** — o Alpha não
       otimiza custo nem funding."""
    fill_assumed = pl.col("barrier_hit") != _NOFILL
    y_bruto = (pl.col("ret_net") > 0.0).cast(pl.Int8)
    y_meta = y_bruto if include_nofill else pl.when(fill_assumed).then(y_bruto).otherwise(None)
    return table.with_columns(
        fill_assumed=fill_assumed,
        y_meta=y_meta.cast(pl.Int8),
    )


def _regime_one_hot(table: pl.DataFrame, regime_levels: tuple[str, ...]) -> pl.DataFrame:
    """One-hot drop-first sobre níveis FIXOS A PRIORI (§6.3).

    O nível de referência (dropado) é o primeiro de `regime_levels`. Uma
    linha cujo `regime` não está entre os níveis conhecidos ficaria com
    TODAS as dummies em 0 — que sob drop-first é exatamente a codificação
    do nível de referência, ou seja **predição errada em vez de erro**. É o
    caso que a v1 do documento não viu, e sob o HMM ele não é raro: o
    sentinela `NO_DECODE` cobre os 2 primeiros anos de cada símbolo
    (`m1_walkforward_initial_train_years`), um bloco contíguo de calendário
    que cai inteiro no grupo 0 da partição cronológica do CPCV.

    Por isso a marcação acontece AQUI, junto do one-hot, e não num passo
    posterior que alguém pudesse esquecer de chamar. A política declarada
    para `meta_status != OK` é VETO (§6.4), coerente com D-05 ("não
    aposte") — e as mesmas linhas ficam fora do TREINO, senão o modelo
    aprenderia sobre uma codificação que sabemos estar errada."""
    regime_utf8 = pl.col("regime").cast(pl.Utf8)
    conhecido = regime_utf8.is_in(list(regime_levels))
    dummies = [
        (regime_utf8 == nivel).cast(pl.Int8).alias(f"{REGIME_OHE_PREFIX}{nivel}")
        for nivel in regime_levels[1:]  # drop-first
    ]
    return table.with_columns(*dummies).with_columns(
        meta_status=pl.when(conhecido)
        .then(pl.lit(META_STATUS_OK))
        .otherwise(pl.lit(META_STATUS_UNSEEN_REGIME))
    )


def regime_stability_diagnostic(
    table: pl.DataFrame, *, characteristic: str = "atr_at_t0"
) -> pl.DataFrame:
    """§6.2 — mede a estabilidade do mapeamento estado↔característica entre
    folds de canonicalização do HMM. **Pré-requisito de D-01**, a rodar
    ANTES de qualquer treino do Meta.

    O problema que ela existe para detectar: sob o HMM a canonicalização é
    por fold do walk-forward, por retorno ascendente com desempate por
    variância (`build_hmm`). Logo `S2` do fold 3 e `S2` do fold 7 estão
    ligados apenas por *rank de retorno dentro do próprio fold* — não são o
    mesmo objeto. Empilhá-los numa coluna one-hot única pressupõe uma
    comparabilidade que ninguém verificou. Se o efeito real existir com
    sinal oposto em folds distintos, ele **cancela**, e D-01 é rejeitada
    por artefato de rotulagem em vez de por ausência de sinal — os dois
    resultados são indistinguíveis sem esta medição.

    `characteristic` default `atr_at_t0`: é volatilidade, é conhecida em
    `t0` (nunca o alvo), e já está no `meta_training_set` (§3.2).

    Devolve uma linha por `(regime_fold_id, regime)` com a mediana e a
    contagem da característica, mais o RANK daquele estado dentro do seu
    fold. Comparar os ranks entre folds é o teste: se o estado `S2` é o 3º
    mais volátil num fold e o 1º noutro, o rótulo não é comparável.

    **Sem limiar de aprovação declarado, de propósito (B23).** O design doc
    não trava um; inventar um aqui seria exatamente o que `AG-114`/`AG-122`
    documentam como o modo de falha de "gate sem definição operacional".
    Reporta o número; quem decide o critério é o Manager."""
    if ds.REGIME_FOLD_COL not in table.columns:
        raise MetaDatasetError(
            f"regime_stability_diagnostic exige a coluna {ds.REGIME_FOLD_COL!r}, que só "
            "existe sob `regime_source=hmm_gaussian_k4_v1` "
            "(`dataset.build_modeling_frame`). Sob o classificador por quantis não há "
            "canonicalização por fold e esta medição não se aplica."
        )
    por_estado = (
        table.filter(pl.col("regime") != ds.REGIME_NO_DECODE_LABEL)
        .group_by([ds.REGIME_FOLD_COL, "regime"])
        .agg(
            mediana_caracteristica=pl.col(characteristic).median(),
            n_linhas=pl.len(),
        )
    )
    return por_estado.with_columns(
        rank_no_fold=pl.col("mediana_caracteristica")
        .rank(method="ordinal")
        .over(ds.REGIME_FOLD_COL)
    ).sort([ds.REGIME_FOLD_COL, "regime"])


def _assert_regime_join_is_total(table: pl.DataFrame) -> None:
    """§6.4 — 100% das linhas com `regime` não-nulo. Nulo levanta com
    contagem e intervalo. NUNCA imputação silenciosa."""
    n_nulo = int(table["regime"].null_count())
    if n_nulo == 0:
        return
    nulos = table.filter(pl.col("regime").is_null())
    t0_min = str(nulos["t0"].min())
    t0_max = str(nulos["t0"].max())
    raise MetaDatasetError(
        f"§6.4: {n_nulo} linha(s) sem `regime` após o join, de {table.height} — "
        f"intervalo t0 [{t0_min}, {t0_max}]. O join de regime é "
        "exato (não as-of), então nulo significa cobertura faltando no artefato de "
        "regime, não tolerância mal escolhida. Nunca imputado."
    )


def _uniqueness_subpop(table: pl.DataFrame) -> pl.DataFrame:
    """§5/D-10 — unicidade RECALCULADA na subpopulação, com o grão
    `(symbol, side_hat)` explícito, dentro de cada `(meta_split_id, role)`.

    Herdar `uniqueness` do universo está errado por três motivos: (a) a
    concorrência foi contada contra todas as barras, não contra a população
    sinalizada; (b) a normalização "média 1" não vale num subconjunto; (c)
    concorrência global conta vizinhos que estão no bloco de TESTE, então o
    peso de uma linha de treino codificaria a densidade de sinal do teste.

    Sem o `groupby(symbol, side_hat)` a chamada ou levanta `ValueError`
    (linhas concatenadas por `fold_id` não vêm ordenadas por `t0`) ou conta
    um evento de BTC como concorrente de um de ETH e um short como
    concorrente de um long — e `n_eff_subpop` sairia subestimado por ~5×,
    mandando todo fold para `INSUFFICIENT_SAMPLE`. Isso seria lido como "a
    amostra matou o desenho" quando foi um bug de agrupamento.

    `role` entra no grão junto com `meta_split_id` (decisão deste módulo,
    não do documento): calcular a concorrência sobre treino ∪ teste faria a
    densidade do teste entrar no peso do treino — precisamente o defeito (c)
    que a regra existe para corrigir.

    `concurrency_subpop` é PERSISTIDA junto, não descartada.
    `compute_concurrency_and_uniqueness` devolve as duas, e a concorrência é
    insumo obrigatório do `UniquenessDivergenceDiagnostic` (§5). Jogá-la
    fora aqui e recomputá-la depois seria repetir literalmente o padrão que
    `AG-150` registrou sobre o `tau` do Alpha — calculado e descartado, e
    depois faltando exatamente onde importava."""
    partes: list[pl.DataFrame] = []
    chaves = ("meta_split_id", "role", "symbol", "side_hat")
    for _chave, grupo in table.group_by(chaves, maintain_order=True):
        ordenado = grupo.sort("t0")
        t0_ms = ordenado["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        t1_ms = ordenado["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        concorrencia, unicidade = compute_concurrency_and_uniqueness(t0_ms, t1_ms)
        partes.append(
            ordenado.with_columns(
                uniqueness_subpop=pl.Series(unicidade),
                concurrency_subpop=pl.Series(concorrencia),
            )
        )
    return pl.concat(partes, how="vertical")


def _meta_sample_weight(table: pl.DataFrame) -> pl.DataFrame:
    """§5 CORRIGIDO — `uniqueness_subpop × atr_at_t0`, normalizado para
    média 1 DENTRO do treino de cada meta-fold.

    **Por que NÃO é mais `|ret_net|`** (medido em 2026-08-30 sobre
    BTCUSDT/R1 camada1, 11.859 linhas de treino; ver
    `audit/evidence_ledger.yaml`):

    O documento justificava `|ret_net|` dizendo que com `tp_atr_mult = 2.0`
    e `sl_atr_mult = 1.5` teríamos `E[|ret_net| | y=1] ≈ 1,33 ×
    E[|ret_net| | y=0]`. Duas coisas estavam erradas. Primeiro, as barreiras
    hoje são **simétricas** (`tp_atr_mult = sl_atr_mult = 1.5`). Segundo, e
    pior, a razão medida é **invertida**: `E[|ret_net| | y=1] = 0,63 ×
    E[|ret_net| | y=0]`. Bruto as saídas são simétricas (±0,00226, como
    manda 1,5/1,5); a assimetria inteira vem do CUSTO DE EXECUÇÃO — sair no
    TP é fill maker (2 bps), sair no SL é fill taker (5 bps).

    A consequência é que `|ret_net|` sob barreiras de ATR fixas quase não é
    "magnitude econômica do evento": **48,7% da sua variância é explicada
    pela CLASSE** (η²), e o peso resultante equivale a um **peso de classe
    de 1,61:1 a favor dos perdedores** — nunca escolhido, nunca declarado,
    nunca medido até aqui. `uniqueness` não tem parte nisso
    (`corr(uniqueness, y) = −0,009`); o viés é todo de `|ret_net|`.

    **Por que isso importa mais do que parece.** Um peso de classe no
    TREINO desloca a escala de `p_meta`, e D-07 removeu o calibrador que
    absorveria o deslocamento — então `p_meta` deixa de estimar
    `P(y=1|X)` e passa a estimar uma versão inclinada, sem nada rio abaixo
    que corrija. A assimetria de custo TP/SL é econômica e real, mas o
    lugar dela é a REGRA DE DECISÃO (`tau_meta`, §8.3), onde é um parâmetro
    declarado — não o peso de treino, onde entra duas vezes e sem controle.

    **Por que `atr_at_t0` é a substituta certa, e não um remendo.** Ela é a
    escala da barreira (`k × ATR`) a menos de uma constante, e portanto a
    magnitude EM RISCO do evento — conhecida em `t0`, nunca função do
    resultado. Medido, sobre o mesmo dado:

        razão de peso entre classes:  1,596  ->  0,997
        corr(peso, y_meta):          -0,698  ->  0,006
        η² (classe explica):          0,487  ->  0,000
        corr com |ret_net| DENTRO da classe:   0,89 (y=0) / 0,97 (y=1)

    Ou seja: elimina o peso de classe acidental e a dependência do alvo, e
    **preserva** a ordenação econômica que justificava ponderar por
    magnitude. `atr_at_t0` já vem em unidades de RETORNO (mediana 0,00148),
    não de preço — não há divisão por preço a fazer.

    O multiplicador da barreira (`sl_atr_mult`) é omitido de propósito: sob
    normalização para média 1 dentro do fold, qualquer constante positiva
    cancela. Lê-lo aqui criaria uma dependência de constante numericamente
    inerte. Omissão deliberada, não esquecimento.

    **FORA DO ESCOPO desta correção, e reportado ao Manager:**
    `src.labels.weights.apply_weights` usa a MESMA fórmula
    (`sample_weight = uniqueness × |ret_net|`) para o ALPHA, com peso de
    classe implícito medido em **1,303**. Corrigir lá muda o treino de todo
    o motor e invalidaria as medições em disco — é decisão do Manager, não
    efeito colateral desta função."""
    bruto = pl.col("uniqueness_subpop") * pl.col("atr_at_t0")
    so_treino = pl.when(pl.col("role") == ROLE_TRAIN).then(bruto).otherwise(None)
    media_treino = so_treino.mean().over("meta_split_id")
    return table.with_columns(
        meta_sample_weight=pl.when(media_treino > 0.0)
        .then(bruto / media_treino)
        .otherwise(0.0)
    )


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

#: Colunas que `join_signals_to_labels` traz de `dense` ALÉM das colunas
#: base do harness. `_pos` é a chave posicional contra `train_idx`/`test_idx`
#: (§4.7); `t1` é purge e unicidade e NUNCA feature; `uniqueness` é o valor
#: do universo, mantido só como diagnóstico contra o recalculado (§5).
_CARRY_FROM_DENSE: tuple[str, ...] = (
    "_pos",
    "t1",
    "atr_at_t0",
    "uniqueness",
    # `concurrency` do UNIVERSO — o denominador contra o qual a concorrência
    # recalculada na subpopulação é comparada (§5). Sem ele não há como
    # distinguir "a subpopulação é mais única porque é esparsa" de "a
    # subpopulação é mais única porque o cálculo mudou de grão".
    "concurrency",
    "regime",
)

_SIGNAL_COLUMNS_FROM_PREDICTIONS: tuple[str, ...] = (
    "t0",
    "side_hat",
    "fold_id",
    "p_long",
    "p_short",
    "tau_long",
    "tau_short",
    "score_long_raw",
    "score_short_raw",
    "model_id",
    "calibrator_id",
    "is_oof",
)


def build_meta_signal_table(
    *,
    dense: pl.DataFrame,
    predictions: pl.DataFrame,
    cpcv_result: cpcv.CPCVResult,
    symbol: str,
    resolution_id: str,
    variant: str,
    donor_rule: str = DONOR_RULE_PATH_MATCHED,
    regime_source: str = ds.REGIME_SOURCE_HMM_K4,
    origem: str = "<memória>",
) -> pl.DataFrame:
    """Monta o `meta_training_set` (§3.2) para UM `(symbol, resolution_id,
    variant)`.

    `dense` é o frame DENSO (`dataset.build_modeling_frame(...).data`) sobre
    o qual `cpcv_result` foi gerado — a seleção do subconjunto sinalizado é
    POSICIONAL (§4.7), nunca por regeneração de splits sobre o subconjunto:
    `assert_grade_consistent` sobre subconjunto esparso ou passa em silêncio
    (ramo dollar-bar, que lê `_calibration.json` e nunca olha `labels`) ou
    quebra com `CPCVError` espúrio (ramo de tempo).

    `variant` (`camada1`/`camada0`) entra na chave para que misturar as duas
    seja impossível por engano, não só desaconselhado."""
    if donor_rule != DONOR_RULE_PATH_MATCHED:
        raise MetaDatasetError(
            f"donor_rule={donor_rule!r} não implementado. `{DONOR_RULE_GROUP_MATCHED}` é "
            "F9/trabalho futuro (D-08 da v3): exige uma primitiva de purge por bloco "
            "arbitrário que `cpcv.py` não tem (AG-153), e nunca teve o lado do TESTE "
            "definido. Devolver um resultado sem purge seria pior que levantar."
        )
    assert_dense_frame_matches_splits(dense, cpcv_result)
    assert_alpha_predictions_has_tau(predictions, origem=origem)

    include_nofill = bool(load_constant("meta_include_nofill_in_training"))

    dense_indexed = dense.with_row_index(name="_pos").with_columns(
        # `with_row_index` devolve UInt32, que `src.io.schema._DTYPE_BY_NAME`
        # não conhece — `Int64` é o menor tipo suportado que cobre o índice.
        pl.col("_pos").cast(pl.Int64)
    )

    regime_levels = regime_levels_for_source(regime_source)
    # `regime_fold_id` só existe sob o HMM, e é o insumo da medição de
    # estabilidade do §6.2 — sem ele o one-hot de regime não é auditável.
    carry = _CARRY_FROM_DENSE
    if regime_source == ds.REGIME_SOURCE_HMM_K4:
        if ds.REGIME_FOLD_COL not in dense.columns:
            raise MetaDatasetError(
                f"regime_source=hmm_gaussian_k4_v1 mas o frame denso não tem "
                f"{ds.REGIME_FOLD_COL!r}. Gere o frame com "
                "`dataset.build_modeling_frame(..., regime_source='hmm_gaussian_k4_v1')` "
                "— o classificador por quantis não produz esta coluna, e sem ela a "
                "estabilidade cross-fold do rótulo (§6.2) fica não-verificável."
            )
        carry = (*carry, ds.REGIME_FOLD_COL)

    sinais = predictions.filter(pl.col("side_hat") != 0).select(
        list(_SIGNAL_COLUMNS_FROM_PREDICTIONS)
    )
    ligado = join_signals_to_labels(sinais, dense_indexed, carry=carry)
    _assert_regime_join_is_total(ligado)

    doadores = donor_folds_for_path_matched(cpcv_result)
    n_rows = int(cpcv_result.group_id.shape[0])
    test_masks = _test_masks_by_fold(cpcv_result, n_rows)
    train_masks = _train_masks_by_split(cpcv_result, n_rows)

    pos = ligado["_pos"].to_numpy().astype(np.int64)
    fold_id = ligado["fold_id"].to_numpy().astype(np.int64)

    blocos: list[pl.DataFrame] = []
    for split in cpcv_result.splits:
        s = split.split_id
        # TESTE — a barra saiu do bloco de teste DESTE fold.
        sel_teste = (fold_id == s) & test_masks[s][pos]
        if bool(sel_teste.any()):
            blocos.append(
                ligado.filter(pl.Series(sel_teste)).with_columns(
                    meta_split_id=pl.lit(s, dtype=pl.Int16),
                    path_id=pl.lit(split.path_id, dtype=pl.Int64),
                    role=pl.lit(ROLE_TEST),
                )
            )
        # TREINO — doador é outro fold do MESMO path, E a posição precisa
        # estar em `train_idx` do meta-fold. A segunda condição é a que
        # carrega purge + embargo; sem ela B09 desliga em silêncio (§10.1b).
        sel_treino = np.isin(fold_id, list(doadores[s])) & train_masks[s][pos]
        if bool(sel_treino.any()):
            blocos.append(
                ligado.filter(pl.Series(sel_treino)).with_columns(
                    meta_split_id=pl.lit(s, dtype=pl.Int16),
                    path_id=pl.lit(split.path_id, dtype=pl.Int64),
                    role=pl.lit(ROLE_TRAIN),
                )
            )

    if not blocos:
        raise MetaDatasetError(
            f"nenhuma linha sobreviveu à seleção posicional para {symbol}/{resolution_id}/"
            f"{variant} — nenhum sinal do Alpha caiu simultaneamente no bloco de teste do "
            "seu fold e no train_idx/test_idx de algum meta-fold. Verifique se "
            "`predictions` e `cpcv_result` vieram do MESMO run."
        )

    tabela = pl.concat(blocos, how="vertical")
    tabela = tabela.with_columns(
        symbol=pl.lit(symbol),
        resolution_id=pl.lit(resolution_id),
        variant=pl.lit(variant),
        donor_rule=pl.lit(donor_rule),
        uniqueness_universe=pl.col("uniqueness"),
        concurrency_universe=pl.col("concurrency"),
    )
    tabela = _derive_side_projected_columns(tabela)
    tabela = _derive_target(tabela, include_nofill=include_nofill)
    tabela = _regime_one_hot(tabela, regime_levels)
    tabela = _uniqueness_subpop(tabela)
    tabela = _meta_sample_weight(tabela)

    assert_no_meta_leakage(tabela, cpcv_result)

    logger.info(
        "models.meta_dataset.build_meta_signal_table",
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        donor_rule=donor_rule,
        regime_source=regime_source,
        regime_levels=regime_levels,
        n_linhas=tabela.height,
        n_treino=int((tabela["role"] == ROLE_TRAIN).sum()),
        n_teste=int((tabela["role"] == ROLE_TEST).sum()),
        n_meta_folds=int(tabela["meta_split_id"].n_unique()),
        n_nofill=int((tabela["barrier_hit"] == _NOFILL).sum()),
        n_unseen_regime=int((tabela["meta_status"] == META_STATUS_UNSEEN_REGIME).sum()),
        # §6.4 pede as duas contagens SEPARADAS: sentinela "sem decode" do
        # HMM e nível fora do conjunto conhecido são causas diferentes com a
        # mesma política (veto). Somá-las esconderia qual das duas dominou.
        n_regime_no_decode=int((tabela["regime"] == ds.REGIME_NO_DECODE_LABEL).sum()),
        n_teste_vetado=int(
            ((tabela["role"] == ROLE_TEST) & (tabela["meta_status"] != META_STATUS_OK)).sum()
        ),
        include_nofill_in_training=include_nofill,
    )
    return tabela


# ---------------------------------------------------------------------------
# F2 — divergência de unicidade (§5). Entrega o `n_eff_subpop` MEDIDO, que
# decide o gate de GBM (§7.3) e o N de §14.2.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UniquenessDivergenceDiagnostic:
    """Uma célula `(meta_split_id, role)` do diagnóstico obrigatório do §5.

    **Nenhum limiar é declarado aqui, de propósito (B23).** O design doc
    manda derivar o limiar de `weight_hhi` do HHI do Alpha
    (`hhi_importancia`), e o de `n_eff` de uma medição que ainda não
    existe. Inventar um número redondo agora seria criar exatamente o tipo
    de gate sem definição operacional que `AG-114`/`AG-122` registram como
    modo de falha. Isto REPORTA; quem decide é o Manager."""

    meta_split_id: int
    role: str
    n_rows: int
    #: Σ `uniqueness` do UNIVERSO, restrita às linhas desta subpopulação.
    n_eff_universe_restricted: float
    #: Σ `uniqueness_subpop` — a medida honesta de tamanho de amostra desta
    #: célula (B24). É este número que o §7.3 usa para decidir GBM vs
    #: logística, e o §14.2 para dimensionar N.
    n_eff_subpop: float
    #: `n_eff_subpop / n_eff_universe_restricted`. > 1 é o ESPERADO: a
    #: subpopulação é esparsa, logo cada evento é mais único nela do que
    #: contra todas as barras. Um valor próximo de 1 é o sinal de alarme —
    #: significaria que recalcular na subpopulação não mudou nada, o que
    #: sob taxa de sinal de ~3% não deveria acontecer e apontaria bug de
    #: agrupamento antes de apontar propriedade do dado.
    uniqueness_inflation_ratio: float
    mean_concurrency_universe: float
    mean_concurrency_subpop: float
    #: HHI de `meta_sample_weight` SOBRE LINHAS. Mede se o treino desta
    #: célula está concentrado em poucos eventos.
    weight_hhi: float
    #: `1 / weight_hhi` — o mesmo número em "linhas equivalentes", que é
    #: mais fácil de comparar com `n_rows` do que uma razão adimensional.
    weight_n_eff: float
    #: §5 — se `|ret_net|` for muito correlacionado com `y_meta`, o peso
    #: deixa de ser só "quanto este evento importa" e vira quase um
    #: classificador do alvo. Nesse caso `weight_hhi` deixa de ser
    #: diagnóstico e vira gate. Medido, não presumido.
    corr_abs_ret_y_meta: float
    #: `mean(w | y=0) / mean(w | y=1)` — o PESO DE CLASSE IMPLÍCITO que a
    #: fórmula de ponderação produz. Deve ficar ≈ 1: qualquer coisa longe
    #: disso é um peso de classe que ninguém escolheu, e que desloca a
    #: escala de `p_meta` sem calibrador rio abaixo para absorver (D-07).
    #:
    #: Esta métrica existe porque a fórmula ANTERIOR (`uniqueness vezes
    #: |ret_net|`) produzia 1,61 sem que nada no pipeline percebesse. Um
    #: comentário não teria pego; um número reportado por fold pega.
    weight_class_ratio: float
    #: §9 — comparar accuracy ponderada contra taxa base NÃO-ponderada
    #: acusaria "abaixo do acaso" num modelo funcionando. As duas saem
    #: juntas para que ninguém use a errada.
    base_rate_unweighted: float
    base_rate_weighted: float


def _as_float(value: object) -> float:
    """Agregação de polars (`mean`/`median`/`min`) devolve um union type, e
    `None` quando o frame está vazio.

    Escrito como função, e não como `float(x.mean() or float("nan"))`:
    aquele idioma tem um bug real — `0.0 or nan` avalia para `nan`, então
    uma média legitimamente ZERO seria reportada como "não computável".
    Zero é um valor perfeitamente possível aqui (uma célula só de NOFILL
    tem `meta_sample_weight` zero em toda linha)."""
    if value is None:
        return float("nan")
    return float(value)  # type: ignore[arg-type]


def _corr(x: FloatArray, y: FloatArray) -> float:
    """Pearson com guarda de variância zero. `np.corrcoef` devolve `nan`
    com um `RuntimeWarning` de divisão por zero quando um dos vetores é
    constante — e um fold em que todo `y_meta` é 0 é um caso REAL aqui (8
    dos 15 folds do Alpha não produzem sinal nenhum). `nan` é a resposta
    certa; o warning é ruído que esconderia um problema de verdade."""
    if x.size < 2 or float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _diagnostic_for_cell(cell: pl.DataFrame) -> UniquenessDivergenceDiagnostic:
    n_eff_universe = float(cell["uniqueness_universe"].sum())
    n_eff_subpop = float(cell["uniqueness_subpop"].sum())
    pesos = cell["meta_sample_weight"].to_numpy().astype(np.float64)
    soma_pesos = float(pesos.sum())
    if soma_pesos > 0.0:
        shares = pesos / soma_pesos
        weight_hhi = hhi_from_shares(tuple(float(s) for s in shares))
    else:
        # Peso total zero acontece de verdade: uma célula só de NOFILL tem
        # `|ret_net| = 0` em toda linha. `nan` em vez de 0.0 — HHI zero
        # significaria "perfeitamente diluído", o oposto da verdade.
        weight_hhi = float("nan")

    treinaveis = cell.filter(pl.col("y_meta").is_not_null())
    if treinaveis.height > 0:
        y = treinaveis["y_meta"].to_numpy().astype(np.float64)
        abs_ret = treinaveis["ret_net"].abs().to_numpy().astype(np.float64)
        w = treinaveis["meta_sample_weight"].to_numpy().astype(np.float64)
        base_unweighted = float(y.mean())
        base_weighted = float((y * w).sum() / w.sum()) if float(w.sum()) > 0.0 else float("nan")
        corr = _corr(abs_ret, y)
        w_neg, w_pos = w[y == 0.0], w[y == 1.0]
        class_ratio = (
            float(w_neg.mean() / w_pos.mean())
            if w_neg.size > 0 and w_pos.size > 0 and float(w_pos.mean()) > 0.0
            else float("nan")
        )
    else:
        base_unweighted = float("nan")
        base_weighted = float("nan")
        corr = float("nan")
        class_ratio = float("nan")

    return UniquenessDivergenceDiagnostic(
        meta_split_id=int(cell["meta_split_id"][0]),
        role=str(cell["role"][0]),
        n_rows=cell.height,
        n_eff_universe_restricted=n_eff_universe,
        n_eff_subpop=n_eff_subpop,
        uniqueness_inflation_ratio=(
            n_eff_subpop / n_eff_universe if n_eff_universe > 0.0 else float("nan")
        ),
        mean_concurrency_universe=_as_float(cell["concurrency_universe"].mean()),
        mean_concurrency_subpop=_as_float(cell["concurrency_subpop"].mean()),
        weight_hhi=weight_hhi,
        weight_n_eff=(1.0 / weight_hhi if weight_hhi > 0.0 else float("nan")),
        corr_abs_ret_y_meta=corr,
        weight_class_ratio=class_ratio,
        base_rate_unweighted=base_unweighted,
        base_rate_weighted=base_weighted,
    )


def compute_uniqueness_divergence(table: pl.DataFrame) -> pl.DataFrame:
    """§5 — `UniquenessDivergenceDiagnostic` por `(meta_split_id, role)`.

    **É este o entregável de F2**: `n_eff_subpop` medido, que o §15.2 marca
    como o insumo que decide o gate de GBM (§7.3) e o N de §14.2. Sem ele,
    a escolha de learner seria feita por julgamento na hora — o viés que
    travar o critério a priori existe para evitar.

    Devolve um frame (uma linha por célula) em vez de uma lista de
    dataclasses porque o consumidor natural é escrita de artefato e log
    estruturado; `UniquenessDivergenceDiagnostic` continua sendo o contrato
    tipado de cada linha."""
    faltando = sorted(
        c
        for c in (
            "meta_split_id",
            "role",
            "uniqueness_universe",
            "uniqueness_subpop",
            "concurrency_universe",
            "concurrency_subpop",
            "meta_sample_weight",
            "y_meta",
            "ret_net",
        )
        if c not in table.columns
    )
    if faltando:
        raise MetaDatasetError(
            f"compute_uniqueness_divergence: faltam {faltando} — o frame precisa vir de "
            "`build_meta_signal_table`, não de um subconjunto já projetado."
        )

    linhas = [
        asdict(_diagnostic_for_cell(cell))
        for _chave, cell in table.group_by(("meta_split_id", "role"), maintain_order=True)
    ]
    diag = pl.DataFrame(linhas).sort(["meta_split_id", "role"])
    treino = diag.filter(pl.col("role") == ROLE_TRAIN)
    logger.info(
        "models.meta_dataset.uniqueness_divergence",
        n_celulas=diag.height,
        # Agregados sobre TREINO — é o que decide learner e N.
        n_eff_subpop_total_treino=_as_float(treino["n_eff_subpop"].sum()),
        n_eff_subpop_mediana_treino=_as_float(treino["n_eff_subpop"].median()),
        n_eff_subpop_min_treino=_as_float(treino["n_eff_subpop"].min()),
        inflation_ratio_mediana=_as_float(treino["uniqueness_inflation_ratio"].median()),
        weight_hhi_mediana=_as_float(treino["weight_hhi"].median()),
        # Deve ficar ≈ 1. Longe disso = peso de classe não declarado (§5).
        weight_class_ratio_mediana=_as_float(treino["weight_class_ratio"].median()),
        corr_abs_ret_y_meta_mediana=_as_float(treino["corr_abs_ret_y_meta"].median()),
    )
    return diag


# ---------------------------------------------------------------------------
# F3 — CONTROLE POSITIVO sintético de vazamento (§4.3).
#
# GATE BLOQUEANTE de F6: se o harness não detecta um vazamento INJETADO, ele
# também não detectaria um real, e nada que ele reporte é interpretável.
#
# Isto substitui a mitigação que a v2 do design doc propunha para R1
# (comparar dois braços de doador, `path_matched` vs `group_matched`). O
# controle positivo é ESTRITAMENTE melhor: é falsificável por construção, em
# vez de depender de dois braços concordarem — e `group_matched` saiu do
# caminho crítico por não ter purge (D-08 da v3).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeakagePositiveControlResult:
    """Resultado do controle positivo. `detected` é o GATE.

    O critério é declarado sem inventar limiar (B23): a métrica precisa ser
    ESTRITAMENTE crescente ao longo da grade de `lambda`, e o valor em
    `lambda` máximo precisa superar o de `lambda = 0`. Nenhuma tolerância
    numérica é fabricada — "monotonicamente" é o que o §4.3 pede, e empate
    reprova. Os valores brutos saem junto para que a decisão seja
    auditável, não só o booleano."""

    lambda_grid: tuple[float, ...]
    metric_by_lambda: tuple[float, ...]
    detected: bool
    reason: str


def inject_synthetic_leakage(
    table: pl.DataFrame, lam: float, *, column: str = "p_alpha"
) -> pl.DataFrame:
    """§4.3 — injeta vazamento calibrável: `p_alpha' = (1-λ)·p_alpha + λ·y_meta`.

    **Só `p_alpha` é perturbado, de propósito.** `margin` e
    `score_alpha_raw` são correlacionadas com `p_alpha` e perturbá-las
    junto dobraria o vazamento efetivo por unidade de λ — a monotonicidade
    em λ deixaria de ser interpretável como sensibilidade do harness e
    passaria a medir quantos canais foram contaminados. Um canal, um knob.

    **Linhas com `y_meta` nulo (NOFILL) ficam INTOCADAS.** Não há rótulo
    para vazar nelas; imputar 0 injetaria um viés sistemático contra o
    lado positivo em vez de vazamento, e o resultado do controle passaria
    a depender da fração de NOFILL da célula.

    `lam = 0.0` devolve a coluna byte a byte igual — é o braço de controle,
    e precisa ser exatamente o baseline, não uma aproximação dele."""
    if not 0.0 <= lam <= 1.0:
        raise MetaDatasetError(
            f"inject_synthetic_leakage: lambda={lam} fora de [0, 1]. λ=1 substituiria "
            "p_alpha PELO alvo, o que testa aritmética e não o pipeline."
        )
    if column not in table.columns:
        raise MetaDatasetError(
            f"inject_synthetic_leakage: coluna {column!r} ausente — o frame precisa vir "
            "de `build_meta_signal_table`."
        )
    if lam == 0.0:
        return table
    vazado = (1.0 - lam) * pl.col(column) + lam * pl.col("y_meta").cast(pl.Float64)
    return table.with_columns(
        pl.when(pl.col("y_meta").is_null()).then(pl.col(column)).otherwise(vazado).alias(column)
    )


def run_leakage_positive_control(
    table: pl.DataFrame,
    evaluate: Callable[[pl.DataFrame], float],
    *,
    lambda_grid: Sequence[float] | None = None,
) -> LeakagePositiveControlResult:
    """Roda o controle positivo: injeta cada `lambda` da grade a priori e
    chama `evaluate` sobre o frame contaminado.

    `evaluate` recebe o `meta_training_set` com `p_alpha` já contaminado e
    devolve UMA métrica OOS (em F6 será o Sharpe OOS do braço A1). É
    injetado como parâmetro em vez de importado para que este harness não
    dependa do learner — F3 vem ANTES de F4 na sequência do §15.2, e um
    controle que só pudesse rodar depois do modelo existir chegaria tarde
    demais para o que ele protege.

    **O gate:** `detected == False` ⟹ F6 NÃO RODA. Um harness cego a um
    vazamento de λ=0,4 é cego a qualquer vazamento real, e todo número que
    ele produzir é ruído com aparência de resultado."""
    grid = tuple(
        float(x)
        for x in (
            lambda_grid
            if lambda_grid is not None
            else load_constant("meta_leakage_control_lambda_grid")
        )
    )
    if len(grid) < 2:
        raise MetaDatasetError(
            f"run_leakage_positive_control: grade {grid} tem menos de 2 pontos — "
            "sem baseline não há o que comparar."
        )
    if grid[0] != 0.0:
        raise MetaDatasetError(
            f"run_leakage_positive_control: grade {grid} não começa em λ=0. O braço "
            "sem injeção é a linha de base do controle e não pode faltar."
        )
    if list(grid) != sorted(grid):
        raise MetaDatasetError(
            f"run_leakage_positive_control: grade {grid} fora de ordem — a checagem de "
            "monotonicidade pressupõe λ crescente."
        )

    metricas = tuple(float(evaluate(inject_synthetic_leakage(table, lam))) for lam in grid)

    if any(not np.isfinite(m) for m in metricas):
        return LeakagePositiveControlResult(
            lambda_grid=grid,
            metric_by_lambda=metricas,
            detected=False,
            reason=(
                "métrica não-finita em algum λ — o harness não produziu um número "
                "comparável, e um controle que não compara não controla nada."
            ),
        )
    crescente = all(b > a for a, b in itertools.pairwise(metricas))
    if not crescente:
        return LeakagePositiveControlResult(
            lambda_grid=grid,
            metric_by_lambda=metricas,
            detected=False,
            reason=(
                "métrica NÃO é estritamente crescente em λ. O harness não enxerga "
                "vazamento injetado — logo também não enxergaria vazamento real. "
                "GATE: F6 não roda (§4.3)."
            ),
        )
    logger.info(
        "models.meta_dataset.leakage_positive_control",
        lambda_grid=grid,
        metric_by_lambda=metricas,
        detected=True,
        ganho_lambda_max_sobre_baseline=metricas[-1] - metricas[0],
    )
    return LeakagePositiveControlResult(
        lambda_grid=grid,
        metric_by_lambda=metricas,
        detected=True,
        reason="métrica estritamente crescente em λ — o harness detecta vazamento injetado.",
    )
