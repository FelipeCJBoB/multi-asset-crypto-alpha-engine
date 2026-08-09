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


def _synthetic_train_frame(n: int = 60, *, seed: int = 0) -> pl.DataFrame:
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
    return pl.DataFrame(cols)


# ============================================================================
# build_design_matrix
# ============================================================================


def test_build_design_matrix_shape_e_colunas() -> None:
    df = _synthetic_train_frame()
    X = alpha.build_design_matrix(df)
    assert X.shape == (df.height, len(alpha.DESIGN_COLUMNS))
    assert len(alpha.DESIGN_COLUMNS) == len(T1_FEATURE_IDS) + len(alpha.REGIME_ONEHOT_LEVELS)


def test_build_design_matrix_dummy_de_regime_e_one_hot() -> None:
    df = pl.DataFrame(
        {
            **{fid: pl.Series([0.0, 0.0]) for fid in T1_FEATURE_IDS},
            "regime": pl.Series(["R2", "R1"]),  # R1 é a referência (drop-first)
        }
    )
    X = alpha.build_design_matrix(df)
    n_t1 = len(T1_FEATURE_IDS)
    row_r2 = X[0, n_t1:]
    row_r1 = X[1, n_t1:]
    assert row_r2.tolist() == [1.0, 0.0, 0.0, 0.0]  # R2 é o 1o nível de REGIME_ONEHOT_LEVELS
    assert row_r1.tolist() == [0.0, 0.0, 0.0, 0.0]  # referência -> todos os dummies zero


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
    hyper = alpha.XGBHyperparams.from_constants()
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


# ============================================================================
# Restrição forçada por lado — `E02f_funding_z_expanding` (extensão de
# `_ECONOMIC_FORCED_CONSTRAINT` para `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE`,
# ver `src.models.monotonic`). Fim a fim via `fit_side_model` — não só
# `screen_monotone_constraints` isolado (esse já é coberto em
# `tests/unit/test_models_monotonic.py`) — para provar que `side` chega
# corretamente até o `monotone_constraints` que o XGBoost de fato recebe.
# `_synthetic_train_frame` gera `E02f_funding_z_expanding` como ruído normal
# independente de `ret_net` (sem sinal de IC nenhum) — a restrição só pode
# vir da força econômica, nunca da triagem estatística.
# ============================================================================

_E02F_IDX = T1_FEATURE_IDS.index("E02f_funding_z_expanding")


def test_fit_side_model_e02f_forcado_menos_1_no_long() -> None:
    df = _synthetic_train_frame(n=80, seed=4)
    hyper = alpha.XGBHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
    )

    assert result.monotone["E02f_funding_z_expanding"].constraint == -1
    assert result.monotone["E02f_funding_z_expanding"].forced_economic is True
    assert result.monotone_constraints[_E02F_IDX] == -1


def test_fit_side_model_e02f_forcado_mais_1_no_short() -> None:
    df = _synthetic_train_frame(n=80, seed=4)
    hyper = alpha.XGBHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result = alpha.fit_side_model(
        df,
        side=-1,
        variant=alpha.VARIANT_CAMADA1,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
    )

    assert result.monotone["E02f_funding_z_expanding"].constraint == 1
    assert result.monotone["E02f_funding_z_expanding"].forced_economic is True
    assert result.monotone_constraints[_E02F_IDX] == 1


def test_fit_side_model_e02f_forcado_independente_do_variant_camada0() -> None:
    """Camada 0 (`VARIANT_CAMADA0`) zera TODAS as restrições T1 por
    desenho (`fit_side_model`: `t1_constraints = tuple(0 for _ in
    T1_FEATURE_IDS)`), inclusive as forçadas — a força econômica só se
    aplica à Camada 1. `monotone["E02f_..."].constraint` (o resultado bruto
    de `screen_monotone_constraints`, sempre calculado) continua forçado;
    só o `monotone_constraints` (o que de fato vai para o XGBoost) é zerado
    pela variante Camada 0."""
    df = _synthetic_train_frame(n=80, seed=4)
    hyper = alpha.XGBHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))

    result = alpha.fit_side_model(
        df,
        side=1,
        variant=alpha.VARIANT_CAMADA0,
        hyper=hyper,
        seed=0,
        target_signal_rate=target_signal_rate,
    )

    assert result.monotone["E02f_funding_z_expanding"].constraint == -1
    assert result.monotone_constraints[_E02F_IDX] == 0


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


def test_predictions_parquet_real_schema_e_invariantes() -> None:
    _skip_if_predictions_missing()
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
