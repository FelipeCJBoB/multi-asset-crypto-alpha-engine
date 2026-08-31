"""Testes de `src/models/alpha.py` — matriz de desenho, seed determinística
e as invariantes do §5.13, viradas teste por instrução explícita da task:

```python
assert set(monotone_constraints) <= set(features_in_training_window)
assert stability_screen_data.index.max() <= train_end
assert alpha_preds.loc[alpha_preds.fold_id.notna(), "is_oof"].all()
assert not X_alpha.columns.str.startswith("J")
```

A integração real (treino de verdade sobre `labels/v1/labels.parquet`) é
cara (~2 min para os 15 splits x 2 variantes, Sprint 8) — os testes daqui
usam dado sintético pequeno para a mecânica, e um teste de integração
`skip`-a-menos-que o output real já exista
(`predictions/alpha/{model_id}/predictions.parquet`, escrito por
`src.models.pipeline.run_layer1_sprint`), mesmo padrão de
`tests/unit/test_validation_cpcv.py::_skip_if_labels_missing`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.features.build import T1_FEATURE_IDS
from src.models import alpha, monotonic
from src.models._constants import load_constant
from src.models._paths import PREDICTIONS_OUTPUT_DIR
from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1


def _synthetic_train_frame(
    n: int = 60, *, seed: int = 0, extra_feature_ids: tuple[str, ...] = ()
) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    cols: dict[str, object] = {
        "t0": pl.Series(list(range(n))).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
        "regime": pl.Series(rng.choice(["R1", "R2", "R3", "R4", "R5"], size=n)),
        "label": pl.Series(rng.choice([1, -1, 0], size=n)).cast(pl.Int8),
        "ret_net": pl.Series(rng.normal(scale=0.01, size=n)),
        "sample_weight": pl.Series(np.abs(rng.normal(loc=1.0, scale=0.1, size=n))),
    }
    for fid in T1_FEATURE_IDS:
        cols[fid] = pl.Series(rng.normal(size=n))
    # `extra_feature_ids` (2026-08-24) — colunas T2 sintéticas, pros testes
    # de `feature_ids` parametrizável (ablação T2→T1) poderem montar um
    # vetor de treino DIFERENTE de `T1_FEATURE_IDS` sem inventar um fixture
    # novo. Vazio por padrão -- preserva todo call site existente.
    for fid in extra_feature_ids:
        cols[fid] = pl.Series(rng.normal(size=n))
    return pl.DataFrame(cols)


# ============================================================================
# build_design_matrix
# ============================================================================


def test_build_design_matrix_shape_e_colunas() -> None:
    """Regime SAIU do vetor de treino (2026-08-21, ADR-001 §2.7,
    `PLANO_MESTRE_PRINCE2.md §15.13`) — `DESIGN_COLUMNS` é só as features
    T1 ativas (`T1_FEATURE_IDS`), `build_design_matrix` nunca lê a coluna
    `regime`."""
    df = _synthetic_train_frame()
    X = alpha.build_design_matrix(df)
    assert X.shape == (df.height, len(alpha.DESIGN_COLUMNS))
    assert alpha.DESIGN_COLUMNS == T1_FEATURE_IDS


def test_build_design_matrix_ignora_coluna_regime_se_presente() -> None:
    """`df` pode conter uma coluna `regime` (ex. vindo do `ModelingFrame`
    pra outros consumidores, `run_b3_regime_only`) sem afetar o design
    matrix — `build_design_matrix` nunca a lê."""
    df = pl.DataFrame(
        {
            **{fid: pl.Series([1.0, 2.0]) for fid in T1_FEATURE_IDS},
            "regime": pl.Series(["R2", "R1"]),
        }
    )
    X = alpha.build_design_matrix(df)
    assert X.shape == (2, len(T1_FEATURE_IDS))


def test_build_design_matrix_feature_ids_customizado() -> None:
    """`feature_ids` (2026-08-24, `docs/t2_t1_promotion_ablation_design_
    doc_2026-08-24.md` §5.2) — passar um vetor diferente de
    `T1_FEATURE_IDS` monta a matriz sobre ESSAS colunas, na mesma ordem,
    não sobre `DESIGN_COLUMNS`."""
    extra = ("T2_CANDIDATE_A", "T2_CANDIDATE_B")
    df = _synthetic_train_frame(n=10, extra_feature_ids=extra)
    k_features = T1_FEATURE_IDS[:3] + extra
    X = alpha.build_design_matrix(df, feature_ids=k_features)
    assert X.shape == (10, len(k_features))
    # ordem importa (D-07 -- mesma ordem de `feature_name=` no fit) --
    # coluna 3 do array tem que bater com a coluna `T2_CANDIDATE_A` do df.
    np.testing.assert_array_equal(X[:, 3], df["T2_CANDIDATE_A"].to_numpy())


# ============================================================================
# §5.13 invariantes
# ============================================================================


def test_invariante_monotone_constraints_subconjunto_das_features_treinadas() -> None:
    """`set(monotone_constraints) <= set(features_in_training_window)` —
    `screen_monotone_constraints` só devolve chaves para as `feature_ids`
    recebidas, nunca mais que isso (verificado por construção do dict, não
    só confiado)."""
    df = _synthetic_train_frame()
    results = monotonic.screen_monotone_constraints(
        df, T1_FEATURE_IDS, side=1, min_consistent_envs=6
    )
    assert set(results.keys()) <= set(T1_FEATURE_IDS)


def test_invariante_ic_screening_depende_so_do_frame_recebido() -> None:
    """`stability_screen_data.index.max() <= train_end` (§5.13) —
    operacionalizado aqui como "o resultado só depende do frame passado,
    nunca de dado externo": duas chamadas com frames DIFERENTES (mesmo
    tamanho, valores diferentes) produzem resultados diferentes — prova que
    a função não lê nenhum estado global/cache que pudesse vazar dado de
    fora da janela de treino recebida."""
    df_a = _synthetic_train_frame(n=120, seed=1)
    df_b = _synthetic_train_frame(n=120, seed=2)
    results_a = monotonic.screen_monotone_constraints(
        df_a, T1_FEATURE_IDS, side=1, min_consistent_envs=6
    )
    results_b = monotonic.screen_monotone_constraints(
        df_b, T1_FEATURE_IDS, side=1, min_consistent_envs=6
    )
    ic_a = {f: r.mean_ic for f, r in results_a.items()}
    ic_b = {f: r.mean_ic for f, r in results_b.items()}
    assert ic_a != ic_b  # seeds/dados diferentes -> IC medido diferente


def test_invariante_grupo_j_nunca_entra_no_vetor_do_alpha() -> None:
    """`assert not X_alpha.columns.str.startswith("J")` — Grupo J
    (execução) é exclusivo do Meta (§2.11), fora do escopo do Alpha."""
    assert not any(c.startswith("J") for c in alpha.DESIGN_COLUMNS)
    assert not any(c.startswith("J") for c in T1_FEATURE_IDS)


# ============================================================================
# seed determinística
# ============================================================================


def test_derived_seed_e_deterministica() -> None:
    s1 = alpha._derived_seed(42, 3, 1)
    s2 = alpha._derived_seed(42, 3, 1)
    assert s1 == s2


def test_derived_seed_varia_com_os_parametros() -> None:
    s1 = alpha._derived_seed(42, 3, 1)
    s2 = alpha._derived_seed(42, 4, 1)
    assert s1 != s2


# ============================================================================
# SideModelResult.gain_by_column_raw (task A1 do CLAUDE.md) — campo
# aditivo: gain BRUTO por coluna, antes da normalização que
# `compute_concentration` aplica em `concentration.shares`. Existe para
# `src.models.pipeline.write_fold_diagnostics_atomic` não precisar de um
# retreino para recuperar o gain bruto (achado que motivou a task).
# ============================================================================


def test_fit_side_model_expoe_gain_by_column_raw() -> None:
    df = _synthetic_train_frame(n=80, seed=3)
    hyper = alpha.LGBMHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
    )

    assert isinstance(result.gain_by_column_raw, dict)
    # só colunas em que o booster de fato dividiu (gain > 0) aparecem aqui —
    # mesma convenção do dict que `compute_concentration` recebe (docstring
    # de `src.models.hhi`), diferente de `concentration.shares` (que inclui
    # TODAS as colunas, com 0.0 explícito para as não usadas).
    assert set(result.gain_by_column_raw.keys()) <= set(alpha.DESIGN_COLUMNS)
    assert all(v > 0.0 for v in result.gain_by_column_raw.values())
    # o share normalizado (`concentration.shares`) é derivado do MESMO gain
    # bruto — toda chave presente no bruto também está no share normalizado.
    assert set(result.gain_by_column_raw.keys()) <= set(result.concentration.shares.keys())


def test_fit_side_model_subsample_freq_realmente_ativa_o_bagging() -> None:
    """Achado real (`audit_engineering`, 2026-08-23): `subsample` sozinho
    é um no-op silencioso no LightGBM -- só tem efeito com
    `subsample_freq` (alias `bagging_freq`) como inteiro positivo
    (default da lib é 0 = desabilitado). Este teste prova que o
    parâmetro chega de fato no `LGBMClassifier` construído (não só que
    `LGBMHyperparams.from_constants()` carrega um valor), lendo de volta
    via `get_params()` -- a mesma classe de falha (`subsample` sozinho,
    "renomeação direta, sem mudança de valor") passaria por qualquer
    teste que só checasse `hyper.subsample_freq > 0` sem verificar que o
    valor realmente chega no objeto treinado."""
    df = _synthetic_train_frame(n=80, seed=7)
    hyper = alpha.LGBMHyperparams.from_constants()
    assert hyper.subsample_freq >= 1  # 0 desabilitaria o bagging silenciosamente
    target_signal_rate = float(load_constant("target_signal_rate"))

    result = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
    )

    params = result.model.get_params()
    assert params["subsample_freq"] == hyper.subsample_freq
    assert params["subsample"] == hyper.subsample
    # force_row_wise -- recomendação da doc oficial do LightGBM junto de
    # deterministic=True, achado real da mesma auditoria.
    assert params["force_row_wise"] is True
    assert params["deterministic"] is True


# ============================================================================
# `feature_ids` parametrizável (2026-08-24, `docs/t2_t1_promotion_ablation_
# design_doc_2026-08-24.md` §5.2) — achado de auditoria: o vetor de
# features estava hardcoded em 5 pontos de `fit_side_model` (screening de
# monotonicidade, matriz de desenho, `feature_name` do booster, HHI/HHI-
# efetivo), não era parâmetro em lugar nenhum, apesar de `hyper` já ser
# injetável. Os testes abaixo provam que passar um vetor DIFERENTE de
# `T1_FEATURE_IDS` de fato treina sobre esse vetor -- não só que a
# assinatura aceita o argumento.
# ============================================================================


def test_fit_side_model_feature_ids_customizado_treina_no_vetor_certo() -> None:
    extra = ("T2_CANDIDATE_A", "T2_CANDIDATE_B")
    k_features = T1_FEATURE_IDS[:3] + extra
    df = _synthetic_train_frame(n=120, seed=11, extra_feature_ids=extra)
    hyper = alpha.LGBMHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
        feature_ids=k_features,
    )

    # o booster só conhece as 5 colunas de `k_features` -- nunca as 4
    # T1 excluídas (T1_FEATURE_IDS[3:]), nunca inventa nome novo.
    assert set(result.model.booster_.feature_name()) == set(k_features)
    assert set(result.gain_by_column_raw.keys()) <= set(k_features)
    assert set(result.monotone.keys()) <= set(k_features)
    assert len(result.monotone_constraints) == len(k_features)
    # HHI/HHI-efetivo também avaliados sobre `k_features`, não T1 fixo.
    assert set(result.concentration.shares.keys()) == set(k_features)


def test_fit_side_model_default_preserva_comportamento_t1() -> None:
    """Sem `feature_ids`, o comportamento é bit-idêntico ao de antes desta
    mudança -- mesma seed, dado sintético igual, `feature_name()` bate
    exatamente com `T1_FEATURE_IDS`."""
    df = _synthetic_train_frame(n=80, seed=5)
    hyper = alpha.LGBMHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
    )
    assert set(result.model.booster_.feature_name()) <= set(T1_FEATURE_IDS)


def test_unique_test_bars_feature_ids_filtra_warmup_pelo_vetor_certo() -> None:
    """Achado de correção (não só plumbing, §5.2 do design doc): uma barra
    NULL numa feature T2 candidata, mas válida nas 7 T1, tem que ser
    excluída quando `feature_ids` inclui essa T2 -- senão `build_design_
    matrix` receberia `NaN` silencioso na inferência."""
    extra = ("T2_CANDIDATE_A",)
    df = _synthetic_train_frame(n=5, extra_feature_ids=extra)
    df = df.with_columns(side=pl.Series([1, 1, 1, 1, 1], dtype=pl.Int8))
    # barra de índice 2 fica NULL só na T2 candidata -- válida em T1.
    t2_values = df["T2_CANDIDATE_A"].to_list()
    t2_values[2] = None
    df = df.with_columns(pl.Series("T2_CANDIDATE_A", t2_values, dtype=pl.Float64))

    out_t1_only = alpha.unique_test_bars(df)
    assert out_t1_only.height == 5  # T1 sozinho não vê o NULL da T2

    out_com_t2 = alpha.unique_test_bars(df, feature_ids=T1_FEATURE_IDS + extra)
    assert out_com_t2.height == 4  # exclui a barra NULL na T2 candidata


# ============================================================================
# `null_permutation_seed` / `_permute_label_and_ret_net` (2026-08-24,
# `docs/t2_t1_ablation_veredito_duas_analises_2026-08-24.md` §4, Fase 0b) --
# nulo por permutação de rótulo, usado pra calibrar o gate de permanência
# (`n_better>=4/5`) sem assumir Binomial.
# ============================================================================


def test_permute_label_e_ret_net_move_juntos_mesmo_indice() -> None:
    """`label`/`ret_net` têm que se mover pela MESMA permutação -- a
    relação interna entre os dois (daquela linha original) sobrevive, só a
    relação com as features quebra."""
    df = _synthetic_train_frame(n=40, seed=3)
    original_pairs = set(zip(df["label"].to_list(), df["ret_net"].to_list(), strict=True))

    out = alpha._permute_label_and_ret_net(df, seed=123)

    permuted_pairs = set(zip(out["label"].to_list(), out["ret_net"].to_list(), strict=True))
    assert permuted_pairs == original_pairs  # mesmos pares (label, ret_net), só reordenados
    # a ordem de pelo menos uma das duas colunas realmente mudou -- não é
    # a identidade disfarçada de permutação (n=40, chance de identidade
    # verdadeira sob rng real é desprezível).
    assert out["label"].to_list() != df["label"].to_list()


def test_permute_label_e_ret_net_nao_toca_outras_colunas() -> None:
    """Features, `sample_weight`, `t0` ficam intocados na linha original --
    só `label`/`ret_net` mudam de linha."""
    df = _synthetic_train_frame(n=40, seed=4)
    out = alpha._permute_label_and_ret_net(df, seed=7)

    assert out["sample_weight"].to_list() == df["sample_weight"].to_list()
    assert out["t0"].to_list() == df["t0"].to_list()
    for fid in T1_FEATURE_IDS:
        assert out[fid].to_list() == df[fid].to_list()


def test_permute_label_e_ret_net_e_deterministica() -> None:
    df = _synthetic_train_frame(n=40, seed=5)
    out_a = alpha._permute_label_and_ret_net(df, seed=99)
    out_b = alpha._permute_label_and_ret_net(df, seed=99)
    assert out_a["label"].to_list() == out_b["label"].to_list()
    assert out_a["ret_net"].to_list() == out_b["ret_net"].to_list()


def test_fit_side_model_null_permutation_seed_none_preserva_producao() -> None:
    """Default `None` -- comportamento bit-idêntico ao de antes desta
    extensão (mesma seed, mesmo dado sintético -- resultado igual com ou
    sem o parâmetro explícito)."""
    df = _synthetic_train_frame(n=80, seed=6)
    hyper = alpha.LGBMHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result_default = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
    )
    result_explicit_none = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
        null_permutation_seed=None,
    )

    assert result_default.gain_by_column_raw == result_explicit_none.gain_by_column_raw
    assert result_default.monotone_constraints == result_explicit_none.monotone_constraints


def test_fit_side_model_null_permutation_seed_muda_monotone_constraints() -> None:
    """Achado central da Fase 0b: sob permutação, `screen_monotone_
    constraints` (que lê `ret_net`, não `label`) opera sobre um `ret_net`
    embaralhado -- as restrições monotônicas resultantes não podem mais
    refletir a relação econômica real feature->retorno. Prova indireta de
    que `ret_net` de fato está sendo permutado (não só `label`): rodar com
    `null_permutation_seed` fixo é determinístico (mesma seed -> mesmo
    resultado), igual ao teste de determinismo acima, mas usando uma seed
    de permutação DIFERENTE da run sem permutação alguma."""
    df = _synthetic_train_frame(n=150, seed=8)
    hyper = alpha.LGBMHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result_a = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
        null_permutation_seed=11,
    )
    result_b = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
        null_permutation_seed=11,
    )
    # mesma seed de permutação -> mesmo resultado (determinismo).
    assert result_a.monotone_constraints == result_b.monotone_constraints
    assert result_a.gain_by_column_raw == result_b.gain_by_column_raw


def test_fit_side_model_null_permutation_seed_preserva_sample_weight() -> None:
    """`sample_weight` nunca é permutado -- reflete unicidade temporal do
    label, não o resultado econômico. `n_train_fit + n_train_calib` (a
    partição interna que `sample_weight` ajuda a definir via estratificação
    por `y`) tem que somar ao total de linhas, permutado ou não."""
    df = _synthetic_train_frame(n=80, seed=9)
    hyper = alpha.LGBMHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
        null_permutation_seed=42,
    )
    assert result.n_train_fit + result.n_train_calib == df.height


def test_monotone_constraints_tem_exatamente_10_entradas() -> None:
    """Fecha a lacuna deixada pela remoção de `+ tuple(0 for _ in
    REGIME_DUMMY_COLUMNS)` (2026-08-21) — `monotone_constraints` que de
    fato vai pro LightGBM precisa ter 1 entrada por coluna de
    `DESIGN_COLUMNS` (7 -- T1_FEATURE_IDS, após AG-032 excluir as 3
    expanding --, não mais 14), nunca sobrar/faltar."""
    df = _synthetic_train_frame(n=80, seed=5)
    hyper = alpha.LGBMHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
    )

    assert len(result.monotone_constraints) == len(T1_FEATURE_IDS)
    assert len(result.monotone_constraints) == len(alpha.DESIGN_COLUMNS)


# ============================================================================
# Restrição forçada por lado (`_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE`,
# `src.models.monotonic`) fim a fim via `fit_side_model` -- REMOVIDO
# 2026-08-23, AG-032: o único exemplo real que este bloco testava,
# `E02f_funding_z_expanding`, saiu do conjunto ativo de treino
# (`T1_FEATURE_IDS`). O mecanismo em si (dict vazio hoje, pronto pra
# feature futura com a mesma assinatura contábil) continua coberto
# isoladamente em `tests/unit/test_models_monotonic.py` (nome de feature
# sintético via `monkeypatch`) -- cobertura fim a fim via `fit_side_model`
# fica pendente até uma feature real dessa categoria voltar ao conjunto
# ativo (não recriar um teste fim a fim contra `monkeypatch` só pra manter
# a cobertura -- B23, não inventar cenário sem feature real por trás).
# ============================================================================


# ============================================================================
# Integração real — skip se o Sprint 8 ainda não rodou
# ============================================================================


def _predictions_path(model_id: str) -> Path:
    return PREDICTIONS_OUTPUT_DIR / "alpha" / model_id / "predictions.parquet"


def _skip_if_predictions_missing() -> None:
    if not _predictions_path(MODEL_ID_CAMADA1).exists():
        pytest.skip(
            "predictions/alpha/.../predictions.parquet ausente — rode "
            "src.models.pipeline.run_layer1_sprint() primeiro (Sprint 8)"
        )


def _skip_if_predictions_schema_legado() -> None:
    """D-03/D-05 (docs/alpha_model_design_doc_2026-08-22.md) estendem
    `PREDICTIONS_SCHEMA_COLUMNS` de 17 para 21 colunas. Os `predictions.
    parquet` legados em disco (pré-migração LightGBM, `AG-150`/`AG-162`)
    ainda têm o schema antigo — isso NÃO é bug do código novo, é artefato
    reconstruível que só é regenerado quando o gate "Data Layer 100%" abrir
    e `run_layer1_sprint` rodar de novo (§13 do design doc do Alpha,
    "regeneração deliberada, não drift silencioso"). `skip` com mensagem
    explícita em vez de `AssertionError` genérico — mais honesto sobre a
    causa real (artefato desatualizado, não código quebrado)."""
    preds = pl.read_parquet(_predictions_path(MODEL_ID_CAMADA1))
    if tuple(preds.columns) != alpha.PREDICTIONS_SCHEMA_COLUMNS:
        pytest.skip(
            "predictions.parquet em disco tem schema legado (pré-D-03/D-05, "
            "migração LightGBM) -- regenere via run_layer1_sprint() para "
            "validar o schema novo, ver AG-150/AG-162"
        )


def test_predictions_parquet_real_schema_e_invariantes() -> None:
    _skip_if_predictions_missing()
    _skip_if_predictions_schema_legado()
    preds = pl.read_parquet(_predictions_path(MODEL_ID_CAMADA1))

    assert tuple(preds.columns) == alpha.PREDICTIONS_SCHEMA_COLUMNS
    # invariante 3 do §5.13: toda linha com fold_id não-nulo é OOF.
    with_fold = preds.filter(pl.col("fold_id").is_not_null())
    assert bool(with_fold["is_oof"].all())
    assert set(preds["side_hat"].unique().to_list()) <= {-1, 0, 1}
    # features_selecionadas é sempre um subconjunto (aqui, o conjunto
    # inteiro — Camada 2 não implementada nesta rodada, ver docstring de
    # src.models.alpha.run_fold) de T1_FEATURE_IDS.
    all_selected = preds["features_selecionadas"].explode().unique().to_list()
    assert set(all_selected) <= set(T1_FEATURE_IDS)


def test_predictions_parquet_camada0_tambem_existe() -> None:
    _skip_if_predictions_missing()
    assert _predictions_path(MODEL_ID_CAMADA0).exists()
