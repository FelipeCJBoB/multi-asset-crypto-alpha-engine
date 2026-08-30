"""Testes de `src/models/meta_dataset.py` — F1 do Meta
(`docs/meta_model_design_doc_2026-08-22.md`).

**Os testes que mais importam aqui são os CONTROLES POSITIVOS** (§10.2): um
frame deliberadamente violando cada uma das quatro asserções do §10.1, e a
afirmação de que o builder levanta. Sem eles, uma asserção que nunca dispara
é indistinguível de uma asserção correta — crítica que o próprio
`src/validation/leakage.py` já faz de si mesmo. Um detector que não é testado
contra uma violação forjada não prova nada."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.models import dataset as ds
from src.models import meta_dataset as md
from src.validation import cpcv

_MODEL_ID = "alpha_c1_v1"


def _calibrator_id(model_id: str, side: int, fold: int) -> str:
    """Convenção REAL do Alpha, verificada em
    `artifacts/predictions_alpha/.../part-0000.parquet` (2026-08-30)."""
    return f"{model_id}_side{side}_fold{fold}_calibrator"


def _mk_split(
    *, split_id: int, path_id: int, train_idx: list[int], test_idx: list[int]
) -> cpcv.CPCVSplit:
    return cpcv.CPCVSplit(
        split_id=split_id,
        path_id=path_id,
        test_groups=(0, 1),
        train_groups=(2, 3),
        train_idx=np.array(train_idx, dtype=np.int64),
        test_idx=np.array(test_idx, dtype=np.int64),
        n_train_candidate=len(train_idx),
        n_purged=0,
        n_embargoed=0,
    )


def _mk_cpcv_result(splits: list[cpcv.CPCVSplit], n_rows: int) -> cpcv.CPCVResult:
    return cpcv.CPCVResult(
        config=cpcv.CPCVConfig.from_constants(),
        group_id=np.zeros(n_rows, dtype=np.int64),
        edges_ms=np.arange(7, dtype=np.int64),
        splits=tuple(splits),
    )


# ---------------------------------------------------------------------------
# Regra de doador (§4.3)
# ---------------------------------------------------------------------------


def test_donor_folds_sao_os_outros_splits_do_mesmo_path() -> None:
    """Um path do CPCV real tem 3 splits (6 grupos / 2 por bloco de teste),
    então cada meta-fold tem exatamente 2 doadores."""
    splits = [
        _mk_split(split_id=0, path_id=0, train_idx=[0], test_idx=[1]),
        _mk_split(split_id=1, path_id=0, train_idx=[1], test_idx=[2]),
        _mk_split(split_id=2, path_id=0, train_idx=[2], test_idx=[0]),
        _mk_split(split_id=3, path_id=1, train_idx=[0], test_idx=[1]),
    ]
    doadores = md.donor_folds_for_path_matched(_mk_cpcv_result(splits, 3))

    assert doadores[0] == frozenset({1, 2})
    assert doadores[1] == frozenset({0, 2})
    assert doadores[2] == frozenset({0, 1})
    # Path diferente nunca doa — seria pseudo-replicação da mesma barra.
    assert doadores[3] == frozenset()
    for s, ds_ in doadores.items():
        assert s not in ds_, "o próprio meta-fold jamais pode ser doador de si"


# ---------------------------------------------------------------------------
# Controles positivos das 4 asserções do §10.1 (§10.2)
# ---------------------------------------------------------------------------


def _tabela_valida() -> tuple[pl.DataFrame, cpcv.CPCVResult]:
    """Meta-fold 0 (path 0, doador 1) sobre 4 posições. Passa nas quatro."""
    splits = [
        _mk_split(split_id=0, path_id=0, train_idx=[2, 3], test_idx=[0, 1]),
        _mk_split(split_id=1, path_id=0, train_idx=[0, 1], test_idx=[2, 3]),
    ]
    tabela = pl.DataFrame(
        {
            "_pos": [0, 1, 2, 3],
            "fold_id": [0, 0, 1, 1],
            "meta_split_id": [0, 0, 0, 0],
            "role": [md.ROLE_TEST, md.ROLE_TEST, md.ROLE_TRAIN, md.ROLE_TRAIN],
            "side_hat": [1, -1, 1, -1],
            "model_id": [_MODEL_ID] * 4,
            "calibrator_id": [
                _calibrator_id(_MODEL_ID, 1, 0),
                _calibrator_id(_MODEL_ID, -1, 0),
                _calibrator_id(_MODEL_ID, 1, 1),
                _calibrator_id(_MODEL_ID, -1, 1),
            ],
        }
    )
    return tabela, _mk_cpcv_result(splits, 4)


def test_controle_negativo_tabela_valida_nao_levanta() -> None:
    """Sem este, um teste que só verifica que o detector dispara não
    distingue "detector correto" de "detector que reprova tudo"."""
    tabela, result = _tabela_valida()
    md.assert_no_meta_leakage(tabela, result)


def test_controle_positivo_a_pos_fora_do_test_idx_do_fold() -> None:
    """§10.1(a) — a predição não é OOF para aquela linha. É B07 acontecendo."""
    tabela, result = _tabela_valida()
    corrompida = tabela.with_columns(_pos=pl.Series([2, 1, 2, 3]))  # _pos=2 não é teste do fold 0
    with pytest.raises(md.MetaLeakageError, match=r"§10\.1\(a\)"):
        md.assert_no_meta_leakage(corrompida, result)


def test_controle_positivo_b_treino_fora_do_train_idx_desliga_purge() -> None:
    """§10.1(b) — a asserção mais importante do módulo. Simula EXATAMENTE o
    modo de falha que ela existe para pegar: coletar as linhas do path por
    `fold_id` e esquecer a interseção posicional.

    A linha corrompida (`fold_id=1`, `_pos=2`) É do doador certo (passa em
    (c)) e É OOF, porque `_pos=2` está em `test_idx[1]` (passa em (a)) — mas
    NÃO está em `train_idx[0] = [4,5]`, então entrou no treino sem purge nem
    embargo. É esse o cenário em que o dataset fica MAIOR e parece melhor."""
    splits = [
        _mk_split(split_id=0, path_id=0, train_idx=[4, 5], test_idx=[0, 1]),
        _mk_split(split_id=1, path_id=0, train_idx=[0, 1], test_idx=[2, 3]),
        _mk_split(split_id=2, path_id=0, train_idx=[0, 1], test_idx=[4, 5]),
    ]
    result = _mk_cpcv_result(splits, 6)
    base = {
        "_pos": [0, 4],
        "fold_id": [0, 2],
        "meta_split_id": [0, 0],
        "role": [md.ROLE_TEST, md.ROLE_TRAIN],
        "side_hat": [1, 1],
        "model_id": [_MODEL_ID] * 2,
        "calibrator_id": [_calibrator_id(_MODEL_ID, 1, 0), _calibrator_id(_MODEL_ID, 1, 2)],
    }
    md.assert_no_meta_leakage(pl.DataFrame(base), result)  # controle negativo

    corrompida = pl.DataFrame(
        {
            **base,
            "_pos": [0, 2],
            "fold_id": [0, 1],
            "calibrator_id": [
                _calibrator_id(_MODEL_ID, 1, 0),
                _calibrator_id(_MODEL_ID, 1, 1),
            ],
        }
    )
    with pytest.raises(md.MetaLeakageError, match=r"10\.1\(b\)"):
        md.assert_no_meta_leakage(corrompida, result)


def test_controle_positivo_c_fold_doador_igual_ao_meta_fold() -> None:
    """§10.1(c) — o meta-fold treinaria sobre as predições do próprio fold
    que ele testa.

    **ACHADO: sob a geometria REAL do CPCV, (c) é logicamente redundante
    dadas (a) e (b).** Uma linha de treino com `fold_id == meta_split_id = s`
    precisaria de `_pos ∈ test_idx[s]` (por (a)) E `_pos ∈ train_idx[s]`
    (por (b)) — conjuntos disjuntos por construção, então (b) sempre dispara
    primeiro e (c) é inalcançável. Registrado como correção ao §10.1, que
    apresenta as quatro como independentes.

    Manter (c) ainda vale: é barata e não depende da disjunção continuar
    valendo (um esquema de CV futuro com blocos sobrepostos — `AG-153` —
    quebraria essa premissa em silêncio). Para exercitá-la de fato, este
    teste usa um `CPCVResult` DELIBERADAMENTE degenerado, com `train_idx` e
    `test_idx` sobrepostos, que a geometria real nunca produz."""
    degenerado = _mk_cpcv_result(
        [_mk_split(split_id=0, path_id=0, train_idx=[0, 1], test_idx=[0, 1])], 2
    )
    corrompida = pl.DataFrame(
        {
            "_pos": [0],
            "fold_id": [0],
            "meta_split_id": [0],
            "role": [md.ROLE_TRAIN],
            "side_hat": [1],
            "model_id": [_MODEL_ID],
            "calibrator_id": [_calibrator_id(_MODEL_ID, 1, 0)],
        }
    )
    with pytest.raises(md.MetaLeakageError, match=r"10\.1\(c\)"):
        md.assert_no_meta_leakage(corrompida, degenerado)


def test_controle_positivo_d_dois_model_id_misturam_escalas() -> None:
    """§10.1(d) — dois runs do Alpha na mesma tabela misturariam escalas de
    probabilidade SEM ERRO."""
    tabela, result = _tabela_valida()
    corrompida = tabela.with_columns(
        model_id=pl.Series([_MODEL_ID, _MODEL_ID, "alpha_c0_baseline_v1", _MODEL_ID])
    )
    with pytest.raises(md.MetaLeakageError, match=r"model_id.*distintos"):
        md.assert_no_meta_leakage(corrompida, result)


def test_controle_positivo_d_calibrador_de_outro_fold() -> None:
    """§10.1(d), a metade que a versão do documento NÃO pegava. Uma
    contagem de `calibrator_id` correta com ATRIBUIÇÃO trocada passaria na
    regra `n_calib == 2 * n_folds` do design doc — aqui reprova, porque a
    verificação é estrutural linha a linha."""
    tabela, result = _tabela_valida()
    corrompida = tabela.with_columns(
        calibrator_id=pl.Series(
            [
                _calibrator_id(_MODEL_ID, 1, 1),  # fold 1 carimbando linha do fold 0
                _calibrator_id(_MODEL_ID, -1, 0),
                _calibrator_id(_MODEL_ID, 1, 1),
                _calibrator_id(_MODEL_ID, -1, 1),
            ]
        )
    )
    with pytest.raises(md.MetaLeakageError, match=r"§10\.1\(d\)"):
        md.assert_no_meta_leakage(corrompida, result)


def test_controle_positivo_d_calibrador_do_outro_lado() -> None:
    """Mesmo mecanismo, trocando o LADO em vez do fold — `p_alpha` de um
    long calibrado pelo calibrador do short."""
    tabela, result = _tabela_valida()
    corrompida = tabela.with_columns(
        calibrator_id=pl.Series(
            [
                _calibrator_id(_MODEL_ID, -1, 0),  # lado trocado
                _calibrator_id(_MODEL_ID, -1, 0),
                _calibrator_id(_MODEL_ID, 1, 1),
                _calibrator_id(_MODEL_ID, -1, 1),
            ]
        )
    )
    with pytest.raises(md.MetaLeakageError, match=r"§10\.1\(d\)"):
        md.assert_no_meta_leakage(corrompida, result)


# ---------------------------------------------------------------------------
# Guardas de contrato
# ---------------------------------------------------------------------------


def test_predictions_sem_tau_levanta_legacy() -> None:
    """§3.5 — o discriminador de artefato pré-D-15 é a AUSÊNCIA de
    `tau_long`/`tau_short`, não uma `schema_version` desconhecida: os
    artefatos legados não têm versão desconhecida, têm versão inexistente."""
    legado = pl.DataFrame({"t0": [1], "p_long": [0.5], "p_short": [0.5]})
    with pytest.raises(md.LegacyPredictionsError, match="tau_long"):
        md.assert_alpha_predictions_has_tau(legado, origem="predictions/alpha/legado")


def test_predictions_com_tau_passa() -> None:
    novo = pl.DataFrame({"tau_long": [0.9], "tau_short": [0.9]})
    md.assert_alpha_predictions_has_tau(novo, origem="<teste>")


def test_frame_denso_incompativel_com_os_splits_levanta() -> None:
    """§4.7 — `train_idx`/`test_idx` são posicionais; splits gerados sobre
    outro frame indexariam linhas erradas em silêncio."""
    result = _mk_cpcv_result([_mk_split(split_id=0, path_id=0, train_idx=[0], test_idx=[1])], 10)
    with pytest.raises(md.MetaDatasetError, match="POSICIONAIS"):
        md.assert_dense_frame_matches_splits(pl.DataFrame({"a": [1, 2, 3]}), result)


def test_group_matched_levanta_em_vez_de_devolver_sem_purge() -> None:
    """D-08 da v3 — `group_matched` é o único braço sem purge e sem embargo.
    Devolver um resultado silenciosamente pior seria a falha grave; parar é
    o comportamento correto."""
    result = _mk_cpcv_result([_mk_split(split_id=0, path_id=0, train_idx=[0], test_idx=[1])], 2)
    with pytest.raises(md.MetaDatasetError, match="AG-153"):
        md.build_meta_signal_table(
            dense=pl.DataFrame({"a": [1, 2]}),
            predictions=pl.DataFrame({"tau_long": [0.1], "tau_short": [0.1]}),
            cpcv_result=result,
            symbol="BTCUSDT",
            resolution_id="R1",
            variant="camada1",
            donor_rule=md.DONOR_RULE_GROUP_MATCHED,
        )


@pytest.mark.parametrize("proibida", sorted(md.META_FORBIDDEN_FEATURES))
def test_design_matrix_rejeita_cada_coluna_proibida(proibida: str) -> None:
    with pytest.raises(md.MetaLeakageError, match="proibida"):
        md.assert_design_matrix_is_clean(("p_alpha", "margin", proibida))


def test_design_matrix_limpo_passa() -> None:
    md.assert_design_matrix_is_clean(("score_alpha_raw", "p_alpha", "margin", "side_hat"))


def test_t1_esta_entre_as_proibidas() -> None:
    """`t1` é insumo de purge e de unicidade — nunca informação disponível
    em `t0`. É a coluna cuja inclusão acidental seria mais plausível, porque
    ela precisa MESMO estar no frame."""
    assert "t1" in md.META_FORBIDDEN_FEATURES


# ---------------------------------------------------------------------------
# Regime (§6)
# ---------------------------------------------------------------------------


def test_niveis_do_hmm_excluem_o_sentinela() -> None:
    """§6.4 — `NO_DECODE` NÃO ganha dummy: a política declarada para ele é
    veto, e uma coluna que o modelo pudesse ponderar contradiria a política."""
    niveis = md.regime_levels_for_source(ds.REGIME_SOURCE_HMM_K4)
    assert ds.REGIME_NO_DECODE_LABEL not in niveis
    assert niveis == ("S0", "S1", "S2", "S3"), "k=4 canônico (AG-114)"


def test_niveis_do_classificador_por_quantis() -> None:
    niveis = md.regime_levels_for_source(ds.REGIME_SOURCE_QUANTILE_V1)
    assert niveis == ("R0", "R1", "R2", "R3", "R4", "R5")


def test_regime_source_desconhecido_levanta() -> None:
    """§6.3 — inferir os níveis do dado observado é exatamente o proibido."""
    with pytest.raises(md.MetaDatasetError, match="fixos a priori"):
        md.regime_levels_for_source("kmeans_k7_experimental")


def test_one_hot_e_drop_first_e_marca_nivel_desconhecido() -> None:
    """A linha `NO_DECODE` ficaria com TODAS as dummies em 0 — que sob
    drop-first é a codificação do nível de REFERÊNCIA (`S0`), ou seja
    predição errada em vez de erro. Por isso ela sai marcada."""
    tabela = pl.DataFrame({"regime": ["S0", "S1", "S3", ds.REGIME_NO_DECODE_LABEL]})
    out = md._regime_one_hot(tabela, ("S0", "S1", "S2", "S3"))

    assert f"{md.REGIME_OHE_PREFIX}S0" not in out.columns, "S0 é a referência, drop-first"
    assert out[f"{md.REGIME_OHE_PREFIX}S1"].to_list() == [0, 1, 0, 0]
    assert out[f"{md.REGIME_OHE_PREFIX}S3"].to_list() == [0, 0, 1, 0]
    # S0 e NO_DECODE têm a MESMA codificação (tudo 0) — é justamente por isso
    # que `meta_status` precisa distingui-las.
    assert out["meta_status"].to_list() == [
        md.META_STATUS_OK,
        md.META_STATUS_OK,
        md.META_STATUS_OK,
        md.META_STATUS_UNSEEN_REGIME,
    ]


def test_estabilidade_de_regime_exige_a_coluna_de_fold_do_hmm() -> None:
    """Sob o classificador por quantis não há canonicalização por fold, e a
    medição do §6.2 não se aplica — dizer isso é melhor que devolver um
    número sem significado."""
    tabela = pl.DataFrame({"regime": ["R0"], "atr_at_t0": [1.0]})
    with pytest.raises(md.MetaDatasetError, match="hmm_gaussian_k4_v1"):
        md.regime_stability_diagnostic(tabela)


def test_estabilidade_de_regime_expoe_rank_trocado_entre_folds() -> None:
    """§6.2 — o defeito que a medição existe para achar: `S1` é o estado
    MENOS volátil no fold 0 e o MAIS volátil no fold 1. Empilhar os dois
    numa coluna one-hot única trataria estados opostos como o mesmo objeto,
    e o efeito real cancelaria — D-01 seria rejeitada por artefato de
    rotulagem, indistinguível de ausência de sinal."""
    tabela = pl.DataFrame(
        {
            ds.REGIME_FOLD_COL: [0, 0, 1, 1],
            "regime": ["S0", "S1", "S0", "S1"],
            "atr_at_t0": [10.0, 1.0, 1.0, 10.0],
        }
    )
    diag = md.regime_stability_diagnostic(tabela)

    ranks = {
        (r[0], r[1]): r[3] for r in diag.select(ds.REGIME_FOLD_COL, "regime", "mediana_caracteristica", "rank_no_fold").iter_rows()
    }
    assert ranks[(0, "S1")] == 1, "S1 é o menos volátil no fold 0"
    assert ranks[(1, "S1")] == 2, "e o MAIS volátil no fold 1 — rótulo não comparável"
    assert ranks[(0, "S1")] != ranks[(1, "S1")]


def test_estabilidade_de_regime_ignora_o_sentinela() -> None:
    tabela = pl.DataFrame(
        {
            ds.REGIME_FOLD_COL: [0, 0],
            "regime": ["S0", ds.REGIME_NO_DECODE_LABEL],
            "atr_at_t0": [1.0, 99.0],
        }
    )
    diag = md.regime_stability_diagnostic(tabela)
    assert diag.height == 1
    assert diag["regime"].to_list() == ["S0"]
