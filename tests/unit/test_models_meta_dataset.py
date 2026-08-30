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
from polars.testing import assert_frame_equal

from src.models import dataset as ds
from src.models import hhi
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
        (r[0], r[1]): r[3]
        for r in diag.select(
            ds.REGIME_FOLD_COL, "regime", "mediana_caracteristica", "rank_no_fold"
        ).iter_rows()
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


# ---------------------------------------------------------------------------
# F2 — divergência de unicidade (§5)
# ---------------------------------------------------------------------------


def test_hhi_de_participacoes_uniformes_e_um_sobre_n() -> None:
    """Núcleo puro extraído de `compute_concentration`. Uniforme é o caso de
    máxima diluição: HHI = 1/n."""
    assert hhi.hhi_from_shares((0.25, 0.25, 0.25, 0.25)) == pytest.approx(0.25)
    assert hhi.hhi_from_shares((1.0,)) == pytest.approx(1.0)
    assert hhi.hhi_from_shares((0.5, 0.5)) == pytest.approx(0.5)


def test_hhi_concentrado_tende_a_um() -> None:
    concentrado = hhi.hhi_from_shares((0.97, 0.01, 0.01, 0.01))
    diluido = hhi.hhi_from_shares((0.25, 0.25, 0.25, 0.25))
    assert concentrado > diluido
    assert concentrado == pytest.approx(0.9412)


def test_as_float_nao_transforma_zero_em_nan() -> None:
    """Regressão do bug real que este helper substituiu: o idioma
    `float(x.mean() or float("nan"))` avalia `0.0 or nan` como `nan`, então
    uma média legitimamente ZERO virava "não computável". Zero acontece de
    verdade — uma célula só de NOFILL tem `meta_sample_weight` zero em toda
    linha."""
    assert md._as_float(0.0) == 0.0
    assert md._as_float(0) == 0.0
    assert md._as_float(3.5) == pytest.approx(3.5)
    assert np.isnan(md._as_float(None))


def _mk_meta_table() -> pl.DataFrame:
    """Duas células: treino (4 linhas) e teste (2 linhas) do meta-fold 0.

    A subpopulação é DELIBERADAMENTE mais única que o universo
    (`uniqueness_subpop` > `uniqueness_universe`), que é o comportamento
    esperado sob taxa de sinal de ~3%: contra todas as barras um evento tem
    muitos concorrentes; contra só os sinalizados, poucos."""
    return pl.DataFrame(
        {
            "meta_split_id": [0, 0, 0, 0, 0, 0],
            "role": [md.ROLE_TRAIN] * 4 + [md.ROLE_TEST] * 2,
            "uniqueness_universe": [0.1, 0.1, 0.2, 0.2, 0.1, 0.1],
            "uniqueness_subpop": [0.5, 0.5, 1.0, 1.0, 0.5, 0.5],
            "concurrency_universe": [10, 10, 5, 5, 10, 10],
            "concurrency_subpop": [2, 2, 1, 1, 2, 2],
            "meta_sample_weight": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            "y_meta": [1, 0, 1, 0, 1, 0],
            "ret_net": [0.02, -0.01, 0.03, -0.015, 0.02, -0.01],
        }
    )


def test_divergencia_entrega_n_eff_subpop_por_celula() -> None:
    """§5/F2 — `n_eff_subpop` é O entregável: é ele que decide o gate de GBM
    (§7.3) e o N de §14.2."""
    diag = md.compute_uniqueness_divergence(_mk_meta_table())

    assert diag.height == 2, "uma linha por (meta_split_id, role)"
    treino = diag.filter(pl.col("role") == md.ROLE_TRAIN)
    assert treino["n_eff_subpop"][0] == pytest.approx(3.0)  # 0.5+0.5+1.0+1.0
    assert treino["n_eff_universe_restricted"][0] == pytest.approx(0.6)
    assert treino["n_rows"][0] == 4


def test_inflation_ratio_maior_que_um_e_o_esperado() -> None:
    """Recalcular na subpopulação DEVE inflar a unicidade. Um ratio perto de
    1 seria o alarme: significaria que mudar o grão não mudou nada, o que
    sob ~3% de taxa de sinal apontaria bug de agrupamento antes de apontar
    propriedade do dado."""
    diag = md.compute_uniqueness_divergence(_mk_meta_table())
    treino = diag.filter(pl.col("role") == md.ROLE_TRAIN)
    assert treino["uniqueness_inflation_ratio"][0] == pytest.approx(5.0)
    assert treino["mean_concurrency_universe"][0] == pytest.approx(7.5)
    assert treino["mean_concurrency_subpop"][0] == pytest.approx(1.5)


def test_weight_hhi_uniforme_da_um_sobre_n_e_n_eff_igual_a_linhas() -> None:
    """Pesos todos iguais ⇒ nenhuma linha domina ⇒ `weight_n_eff` == número
    de linhas. É a leitura que torna o número interpretável."""
    diag = md.compute_uniqueness_divergence(_mk_meta_table())
    treino = diag.filter(pl.col("role") == md.ROLE_TRAIN)
    assert treino["weight_hhi"][0] == pytest.approx(0.25)
    assert treino["weight_n_eff"][0] == pytest.approx(4.0)


def test_weight_hhi_expoe_concentracao_em_poucos_eventos() -> None:
    tabela = _mk_meta_table().with_columns(
        meta_sample_weight=pl.Series([100.0, 0.01, 0.01, 0.01, 1.0, 1.0])
    )
    diag = md.compute_uniqueness_divergence(tabela)
    treino = diag.filter(pl.col("role") == md.ROLE_TRAIN)
    assert treino["weight_hhi"][0] > 0.99
    assert treino["weight_n_eff"][0] < 1.1, "4 linhas, mas ~1 linha efetiva"


def test_peso_total_zero_da_nan_nao_zero() -> None:
    """Uma célula só de NOFILL tem `|ret_net| = 0` em toda linha, logo peso
    total zero. HHI zero significaria "perfeitamente diluído" — o oposto da
    verdade. `nan` é a resposta honesta."""
    tabela = _mk_meta_table().with_columns(
        meta_sample_weight=pl.Series([0.0] * 6)
    )
    diag = md.compute_uniqueness_divergence(tabela)
    assert np.isnan(diag["weight_hhi"][0])


def test_taxa_base_ponderada_e_nao_ponderada_saem_juntas() -> None:
    """§9 — comparar accuracy PONDERADA contra taxa base NÃO-ponderada
    acusaria "abaixo do acaso" num modelo funcionando. As duas juntas para
    que ninguém use a errada por acidente."""
    tabela = _mk_meta_table().with_columns(
        meta_sample_weight=pl.Series([3.0, 1.0, 3.0, 1.0, 1.0, 1.0])
    )
    diag = md.compute_uniqueness_divergence(tabela)
    treino = diag.filter(pl.col("role") == md.ROLE_TRAIN)
    assert treino["base_rate_unweighted"][0] == pytest.approx(0.5)
    # Os positivos carregam peso 3 e os negativos peso 1 -> 6/8.
    assert treino["base_rate_weighted"][0] == pytest.approx(0.75)
    assert treino["base_rate_weighted"][0] != treino["base_rate_unweighted"][0]


def test_corr_abs_ret_com_alvo_e_medida_nao_presumida() -> None:
    """§5 — se `|ret_net|` for muito correlacionado com `y_meta`, o peso
    deixa de ser diagnóstico e `weight_hhi` vira gate. A v1 do design doc
    afirmava que o peso "não vaza porque é o módulo, não o sinal"; isso é
    FALSO com barreiras 2,0/1,5, e a medição existe para não repetir a
    afirmação sem checar."""
    diag = md.compute_uniqueness_divergence(_mk_meta_table())
    treino = diag.filter(pl.col("role") == md.ROLE_TRAIN)
    # |ret| dos positivos (0.02, 0.03) > |ret| dos negativos (0.01, 0.015).
    # Valor exato ≈ 0,845 — conferido à mão, não uma faixa inventada (B23).
    assert treino["corr_abs_ret_y_meta"][0] == pytest.approx(0.8452, abs=1e-3)
    assert treino["corr_abs_ret_y_meta"][0] > 0.8


def test_corr_devolve_nan_em_fold_sem_variancia_no_alvo() -> None:
    """8 dos 15 folds do Alpha não produzem sinal nenhum — um fold com
    `y_meta` constante é caso REAL, não hipotético. `nan` é a resposta;
    `np.corrcoef` sozinho daria `nan` COM um RuntimeWarning de divisão por
    zero, e silenciar warning sem achar a causa é proibido."""
    tabela = _mk_meta_table().with_columns(y_meta=pl.Series([1, 1, 1, 1, 1, 1]))
    diag = md.compute_uniqueness_divergence(tabela)
    treino = diag.filter(pl.col("role") == md.ROLE_TRAIN)
    assert np.isnan(treino["corr_abs_ret_y_meta"][0])
    assert treino["base_rate_unweighted"][0] == pytest.approx(1.0)


def test_nofill_com_y_meta_nulo_sai_da_taxa_base_mas_fica_na_celula() -> None:
    """§3.3 item 4 — NOFILL fica no frame (o denominador do ablation precisa
    da população completa) mas não entra no alvo."""
    tabela = _mk_meta_table().with_columns(y_meta=pl.Series([1, 0, None, None, 1, 0]))
    diag = md.compute_uniqueness_divergence(tabela)
    treino = diag.filter(pl.col("role") == md.ROLE_TRAIN)
    assert treino["n_rows"][0] == 4, "as 4 linhas continuam na célula"
    assert treino["base_rate_unweighted"][0] == pytest.approx(0.5), "só as 2 treináveis"


def test_frame_projetado_demais_levanta_em_vez_de_calcular_errado() -> None:
    with pytest.raises(md.MetaDatasetError, match="build_meta_signal_table"):
        md.compute_uniqueness_divergence(pl.DataFrame({"meta_split_id": [0], "role": ["train"]}))


# ---------------------------------------------------------------------------
# §5 CORRIGIDO — o peso não pode carregar um peso de classe não declarado
# ---------------------------------------------------------------------------


def _mk_tabela_para_peso() -> pl.DataFrame:
    """Reproduz a ESTRUTURA real medida em BTCUSDT/R1: barreiras simétricas
    de ATR, e `|ret_net|` sistematicamente MAIOR nos perdedores por causa da
    assimetria de custo maker/taker (saída no TP é maker, no SL é taker).
    `atr_at_t0` é o mesmo nos dois lados — é a magnitude EM RISCO, conhecida
    em `t0` e independente do resultado."""
    return pl.DataFrame(
        {
            "meta_split_id": [0] * 6,
            "role": [md.ROLE_TRAIN] * 6,
            "uniqueness_subpop": [1.0] * 6,
            "atr_at_t0": [0.0015, 0.0015, 0.0020, 0.0020, 0.0010, 0.0010],
            # y=1 -> +0.0019 (saída maker); y=0 -> -0.0030 (saída taker).
            "ret_net": [0.0019, -0.0030, 0.0019, -0.0030, 0.0019, -0.0030],
            "y_meta": [1, 0, 1, 0, 1, 0],
        }
    )


def test_peso_nao_carrega_peso_de_classe_implicito() -> None:
    """§5 corrigido — a fórmula ANTERIOR (`uniqueness * |ret_net|`) produzia
    um peso de classe medido de 1,61:1 a favor dos perdedores, que ninguém
    escolheu e que desloca a escala de `p_meta` sem calibrador rio abaixo
    para absorver (D-07). Este teste é a trava: se alguém voltar a ponderar
    por uma quantidade que depende do resultado, a razão sai de 1."""
    out = md._meta_sample_weight(_mk_tabela_para_peso())
    w = out["meta_sample_weight"].to_numpy()
    y = out["y_meta"].to_numpy()
    razao = w[y == 0].mean() / w[y == 1].mean()
    assert razao == pytest.approx(1.0, abs=1e-9), "peso de classe implícito precisa ser 1"

    # A fórmula antiga, no MESMO dado, para deixar o contraste explícito.
    antiga = out["uniqueness_subpop"].to_numpy() * np.abs(out["ret_net"].to_numpy())
    razao_antiga = antiga[y == 0].mean() / antiga[y == 1].mean()
    assert razao_antiga > 1.5, "a fórmula antiga de fato pesava mais os perdedores"


def test_peso_preserva_a_ordenacao_por_magnitude_em_risco() -> None:
    """Trocar `|ret_net|` por `atr_at_t0` elimina o viés de classe SEM
    perder a ênfase econômica: eventos com barreira mais larga continuam
    pesando mais."""
    out = md._meta_sample_weight(_mk_tabela_para_peso())
    w = out["meta_sample_weight"].to_numpy()
    atr = out["atr_at_t0"].to_numpy()
    # ATR 0.0020 > 0.0015 > 0.0010 -> pesos na mesma ordem.
    assert w[2] > w[0] > w[4]
    assert w[3] > w[1] > w[5]
    assert np.corrcoef(w, atr)[0, 1] == pytest.approx(1.0)


def test_peso_normalizado_para_media_um_no_treino() -> None:
    out = md._meta_sample_weight(_mk_tabela_para_peso())
    treino = out.filter(pl.col("role") == md.ROLE_TRAIN)
    assert float(treino["meta_sample_weight"].mean()) == pytest.approx(1.0)


def test_peso_nao_usa_ret_net_de_forma_nenhuma() -> None:
    """Guarda estrutural: multiplicar `ret_net` por 100 não pode mudar o
    peso. Se mudar, alguém reintroduziu dependência do resultado."""
    base = _mk_tabela_para_peso()
    alterada = base.with_columns(ret_net=pl.col("ret_net") * 100.0)
    w_base = md._meta_sample_weight(base)["meta_sample_weight"].to_numpy()
    w_alt = md._meta_sample_weight(alterada)["meta_sample_weight"].to_numpy()
    assert np.allclose(w_base, w_alt)


def test_diagnostico_reporta_o_peso_de_classe_implicito() -> None:
    """A métrica existe porque um comentário não teria pego o defeito de
    1,61 — um número reportado por fold pega."""
    tabela = _mk_meta_table().with_columns(
        meta_sample_weight=pl.Series([2.0, 1.0, 2.0, 1.0, 1.0, 1.0])
    )
    diag = md.compute_uniqueness_divergence(tabela)
    treino = diag.filter(pl.col("role") == md.ROLE_TRAIN)
    # y = [1,0,1,0] com pesos [2,1,2,1] -> mean(w|y=0)=1, mean(w|y=1)=2.
    assert treino["weight_class_ratio"][0] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# F3 — controle positivo sintético de vazamento (§4.3), GATE de F6
# ---------------------------------------------------------------------------


def _mk_tabela_vazamento() -> pl.DataFrame:
    """6 linhas, das quais 2 são NOFILL (`y_meta` nulo)."""
    return pl.DataFrame(
        {
            "p_alpha": [0.4, 0.6, 0.45, 0.55, 0.5, 0.5],
            "y_meta": [1, 0, 1, 0, None, None],
            "margin": [0.1, -0.1, 0.05, -0.05, 0.0, 0.0],
        },
        schema_overrides={"y_meta": pl.Int8},
    )


def test_lambda_zero_devolve_o_frame_intocado() -> None:
    """λ=0 é o braço de CONTROLE e precisa ser o baseline exato, não uma
    aproximação dele."""
    base = _mk_tabela_vazamento()
    assert_frame_equal(md.inject_synthetic_leakage(base, 0.0), base, check_exact=True)


def test_injecao_move_p_alpha_na_direcao_do_alvo() -> None:
    out = md.inject_synthetic_leakage(_mk_tabela_vazamento(), 0.5)
    p = out["p_alpha"].to_list()
    # y=1: 0.5*0.4 + 0.5*1 = 0.7   |   y=0: 0.5*0.6 + 0.5*0 = 0.3
    assert p[0] == pytest.approx(0.7)
    assert p[1] == pytest.approx(0.3)


def test_injecao_nao_toca_linhas_sem_rotulo() -> None:
    """NOFILL não tem `y_meta` para vazar. Imputar 0 injetaria viés contra o
    lado positivo em vez de vazamento, e o resultado do controle passaria a
    depender da fração de NOFILL da célula."""
    out = md.inject_synthetic_leakage(_mk_tabela_vazamento(), 0.9)
    assert out["p_alpha"].to_list()[4:] == [0.5, 0.5]


def test_injecao_so_toca_p_alpha() -> None:
    """Um canal, um knob — perturbar `margin` junto dobraria o vazamento por
    unidade de λ e a monotonicidade deixaria de ser interpretável."""
    base = _mk_tabela_vazamento()
    out = md.inject_synthetic_leakage(base, 0.5)
    assert out["margin"].to_list() == base["margin"].to_list()


@pytest.mark.parametrize("lam", [-0.1, 1.5])
def test_lambda_fora_do_intervalo_levanta(lam: float) -> None:
    with pytest.raises(md.MetaDatasetError, match="fora de"):
        md.inject_synthetic_leakage(_mk_tabela_vazamento(), lam)


def _avaliador_sensivel(table: pl.DataFrame) -> float:
    """Métrica que ENXERGA `p_alpha`: separação média entre as classes."""
    t = table.filter(pl.col("y_meta").is_not_null())
    pos = t.filter(pl.col("y_meta") == 1)["p_alpha"].mean()
    neg = t.filter(pl.col("y_meta") == 0)["p_alpha"].mean()
    return float(pos) - float(neg)  # type: ignore[arg-type]


def test_harness_detecta_vazamento_com_avaliador_sensivel() -> None:
    resultado = md.run_leakage_positive_control(
        _mk_tabela_vazamento(), _avaliador_sensivel
    )
    assert resultado.detected is True
    assert resultado.lambda_grid == (0.0, 0.05, 0.1, 0.2, 0.4), "grade a priori de constants.yaml"
    assert resultado.metric_by_lambda[0] < resultado.metric_by_lambda[-1]


def test_harness_REPROVA_com_avaliador_cego() -> None:
    """**O teste mais importante de F3.** Um controle positivo que não pode
    reprovar não controla nada. Com um avaliador que ignora `p_alpha`, o
    gate TEM de fechar — e a mensagem tem de dizer que F6 não roda."""
    resultado = md.run_leakage_positive_control(
        _mk_tabela_vazamento(), lambda _t: 0.42
    )
    assert resultado.detected is False
    assert "F6 não roda" in resultado.reason
    assert len(set(resultado.metric_by_lambda)) == 1, "métrica constante: harness cego"


def test_harness_reprova_metrica_nao_monotonica() -> None:
    valores = iter([0.1, 0.5, 0.2, 0.9, 1.0])
    resultado = md.run_leakage_positive_control(
        _mk_tabela_vazamento(), lambda _t: next(valores)
    )
    assert resultado.detected is False
    assert "crescente" in resultado.reason


def test_harness_reprova_metrica_nao_finita() -> None:
    """Um harness que devolve `nan` não comparou nada — e um controle que
    não compara não controla."""
    valores = iter([0.1, float("nan"), 0.3, 0.4, 0.5])
    resultado = md.run_leakage_positive_control(
        _mk_tabela_vazamento(), lambda _t: next(valores)
    )
    assert resultado.detected is False
    assert "não-finita" in resultado.reason


def test_grade_precisa_comecar_em_zero() -> None:
    with pytest.raises(md.MetaDatasetError, match="linha de base"):
        md.run_leakage_positive_control(
            _mk_tabela_vazamento(), _avaliador_sensivel, lambda_grid=(0.1, 0.2)
        )


def test_grade_precisa_estar_ordenada() -> None:
    with pytest.raises(md.MetaDatasetError, match="fora de ordem"):
        md.run_leakage_positive_control(
            _mk_tabela_vazamento(), _avaliador_sensivel, lambda_grid=(0.0, 0.4, 0.2)
        )


def test_grade_de_um_ponto_so_levanta() -> None:
    with pytest.raises(md.MetaDatasetError, match="sem baseline"):
        md.run_leakage_positive_control(
            _mk_tabela_vazamento(), _avaliador_sensivel, lambda_grid=(0.0,)
        )
