"""Testes de `src/models/pipeline.py` — persistência de diagnóstico por
fold x lado (task A1 do CLAUDE.md).

Achado que motivou esta task: `gain_by_column` (bruto) e
`concentration.shares`/`hhi`/`max_share` (normalizados) só existiam em
memória dentro de `FoldResult`/`SideModelResult` — nunca escritos em disco.
Recuperar isso para uma investigação custou um retreino completo (~117s).

Dois blocos, mesmo padrão de `tests/unit/test_models_alpha.py`:

1. Mecânica com dado sintético pequeno — barato (poucos segundos), mas
   REAL: `alpha.fit_side_model` treina um LightGBM de verdade, não um mock.
   Evita pagar o custo do CPCV completo (15 splits x 2 variantes) só para
   testar a escrita do JSON.
2. Integração real — `skip`-a-menos-que os `n_splits * 2` arquivos já
   existam em `models/{model_id}/diagnostics/` (escritos por
   `src.models.pipeline.run_layer1_sprint`), mesmo padrão skip de
   `test_models_alpha.py::_skip_if_predictions_missing`. Não força um
   retreino de ~117s a cada execução da suíte."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.features.build import T1_FEATURE_IDS
from src.models import alpha, pipeline
from src.models._constants import load_constant
from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1, MODELS_DIR
from src.validation.cpcv import CPCVConfig

_TEST_MODEL_ID = "test_diagnostics_model"


def _synthetic_side_frame(n: int = 80, *, seed: int) -> pl.DataFrame:
    """Mesma forma de `test_models_alpha.py::_synthetic_train_frame`, já
    filtrada por lado (o que `fit_side_model` espera receber — filtragem de
    NOFILL/warmup é responsabilidade de `ds.side_subset`, fora do escopo
    deste teste)."""
    rng = np.random.default_rng(seed)
    cols: dict[str, object] = {
        "label": pl.Series(rng.choice([1, 0], size=n)).cast(pl.Int8),
        "sample_weight": pl.Series(np.abs(rng.normal(loc=1.0, scale=0.1, size=n))),
        "regime": pl.Series(rng.choice(["R1", "R2", "R3", "R4", "R5"], size=n)),
        # `monotonic.screen_monotone_constraints` (chamada por
        # `fit_side_model`) calcula IC de Spearman contra `ret_net` por
        # ambiente — obrigatória aqui, mesma coluna de
        # `test_models_alpha.py::_synthetic_train_frame`.
        "ret_net": pl.Series(rng.normal(scale=0.01, size=n)),
    }
    for fid in T1_FEATURE_IDS:
        cols[fid] = pl.Series(rng.normal(size=n))
    return pl.DataFrame(cols)


def _fake_fold_result(*, fold_id: int, path_id: int, variant: str, seed: int) -> alpha.FoldResult:
    """`FoldResult` com modelos de verdade (treinados sobre dado sintético
    pequeno), montado à mão em vez de via `alpha.run_fold` — evita compor
    `df_all` com colunas `side`/`barrier_hit`/CPCVSplit só para satisfazer
    `ds.side_subset`, que não é o que este teste verifica. `predictions` e
    as três contagens de `n_test_bars`/`n_train_*` não são lidas por
    `write_fold_diagnostics_atomic` (só `long_result`/`short_result`/
    `fold_id`/`path_id`/`variant`), então ficam com valores mínimos."""
    hyper = alpha.LGBMHyperparams.from_constants()
    target_signal_rate = float(load_constant("target_signal_rate"))
    train_long = _synthetic_side_frame(seed=seed)
    train_short = _synthetic_side_frame(seed=seed + 1)

    long_result = alpha.fit_side_model(
        train_long,
        side=1,
        variant=variant,
        hyper=hyper,
        seed=seed,
        target_signal_rate=target_signal_rate,
    )
    short_result = alpha.fit_side_model(
        train_short,
        side=-1,
        variant=variant,
        hyper=hyper,
        seed=seed,
        target_signal_rate=target_signal_rate,
    )
    return alpha.FoldResult(
        fold_id=fold_id,
        path_id=path_id,
        variant=variant,
        model_id=_TEST_MODEL_ID,
        predictions=pl.DataFrame(),
        long_result=long_result,
        short_result=short_result,
        n_train_long=train_long.height,
        n_train_short=train_short.height,
        n_test_bars=0,
    )


# ============================================================================
# _side_label
# ============================================================================


def test_side_label_valores_esperados() -> None:
    assert pipeline._side_label(1) == "long"
    assert pipeline._side_label(-1) == "short"


def test_side_label_rejeita_valor_desconhecido() -> None:
    with pytest.raises(ValueError):
        pipeline._side_label(0)


# ============================================================================
# write_fold_diagnostics_atomic — mecânica, dado sintético
# ============================================================================


def test_write_fold_diagnostics_atomic_escreve_dois_json_validos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "MODELS_DIR", tmp_path)
    hyper = alpha.LGBMHyperparams.from_constants()
    fold = _fake_fold_result(fold_id=0, path_id=0, variant=alpha.VARIANT_CAMADA1, seed=7)

    written = pipeline.write_fold_diagnostics_atomic(
        fold, model_id=_TEST_MODEL_ID, expected_n_trees=hyper.n_estimators
    )

    assert len(written) == 2
    out_dir = tmp_path / _TEST_MODEL_ID / "diagnostics"
    files = sorted(out_dir.glob("*.json"))
    assert {p.name for p in files} == {"fold_0_long.json", "fold_0_short.json"}
    assert {p.name for p in files} == {p.name for p in written}

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["model_id"] == _TEST_MODEL_ID
        assert payload["variant"] == alpha.VARIANT_CAMADA1
        assert payload["fold_id"] == 0
        assert payload["path_id"] == 0
        assert payload["side"] in (1, -1)
        assert payload["side_label"] in ("long", "short")

        # gain bruto (não normalizado) e share normalizado — os dois lados
        # do achado original (decisão (a), ver relatório da task).
        assert isinstance(payload["gain_by_column"], dict)
        assert isinstance(payload["concentration_shares"], dict)
        assert set(payload["concentration_shares"].keys()) == set(alpha.DESIGN_COLUMNS)
        assert set(payload["gain_by_column"].keys()) <= set(alpha.DESIGN_COLUMNS)

        assert 0.0 <= payload["hhi"] <= 1.0
        assert 0.0 <= payload["max_share"] <= 1.0
        assert isinstance(payload["n_features_over_1pct"], int)

        # HHI EFETIVO (D1/D2, CLAUDE.md) — irmão do nominal acima, sobre as
        # 10 features T1 (não as 14 DESIGN_COLUMNS — dummies de regime
        # ficam fora por padrão, ver src.models.hhi.
        # compute_effective_concentration). N_eff_factors em [1, 10].
        assert 0.0 <= payload["hhi_effective"] <= 1.0
        assert 1.0 <= payload["n_eff_factors_t1"] <= len(T1_FEATURE_IDS) + 1e-9
        assert isinstance(payload["concentration_effective_weights"], dict)
        assert set(payload["concentration_effective_weights"].keys()) == set(T1_FEATURE_IDS)
        assert abs(sum(payload["concentration_effective_weights"].values()) - 1.0) < 1e-6
        assert isinstance(payload["concentration_effective_eigenvalues"], list)
        assert len(payload["concentration_effective_eigenvalues"]) == len(T1_FEATURE_IDS)

        # sem early stopping nesta rodada (§5.10/docstring alpha.py) — deve
        # bater exatamente com alpha_lgbm_n_estimators.
        assert payload["n_trees"] == hyper.n_estimators
        assert payload["best_iteration"] is None
        assert payload["best_iteration_note"] == pipeline._BEST_ITERATION_NOTE

        assert payload["n_amostras"]["n_train_fit"] > 0
        assert payload["n_amostras"]["n_train_calib"] > 0


def test_write_fold_diagnostics_atomic_n_trees_divergente_nao_quebra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`expected_n_trees` errado só gera log de warning (ver
    `_fold_diagnostics_payload`), nunca lança exceção — o diagnóstico
    continua sendo escrito com o `n_trees` REAL medido do booster."""
    monkeypatch.setattr(pipeline, "MODELS_DIR", tmp_path)
    fold = _fake_fold_result(fold_id=1, path_id=0, variant=alpha.VARIANT_CAMADA0, seed=13)

    written = pipeline.write_fold_diagnostics_atomic(
        fold, model_id=_TEST_MODEL_ID, expected_n_trees=1
    )

    assert len(written) == 2
    for path in written:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["n_trees"] != 1  # real medido do booster, não o esperado errado


def test_write_all_fold_diagnostics_um_arquivo_por_fold_x_lado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "MODELS_DIR", tmp_path)
    hyper = alpha.LGBMHyperparams.from_constants()
    folds = [
        _fake_fold_result(fold_id=i, path_id=0, variant=alpha.VARIANT_CAMADA1, seed=100 + i)
        for i in range(3)
    ]

    written = pipeline.write_all_fold_diagnostics(folds, model_id=_TEST_MODEL_ID, hyper=hyper)

    assert len(written) == 3 * 2
    out_dir = tmp_path / _TEST_MODEL_ID / "diagnostics"
    assert len(list(out_dir.glob("*.json"))) == 6


# ============================================================================
# dest_dir (AG-013, audit/architecture_gaps_log.yaml) — write_fold_
# diagnostics_atomic/write_all_fold_diagnostics ganham o mesmo sentinela
# `Path | None = None` de write_predictions_atomic (AG-006/AG-012). Paridade
# bit-exata do default já é coberta pelos 3 testes acima (nenhum passa
# `dest_dir`, e continuam passando sem alteração após a mudança) — os dois
# testes abaixo cobrem só o roteamento novo.
# ============================================================================


def test_write_fold_diagnostics_atomic_dest_dir_override_usa_layout_chaveado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dest_dir` explícito grava fora de `MODELS_DIR` inteiramente — não só
    num subdiretório dele — prova de que o parâmetro substitui o destino em
    vez de só compor com o legado."""
    monkeypatch.setattr(pipeline, "MODELS_DIR", tmp_path / "nao_deveria_ser_usado")
    hyper = alpha.LGBMHyperparams.from_constants()
    fold = _fake_fold_result(fold_id=0, path_id=0, variant=alpha.VARIANT_CAMADA1, seed=21)
    keyed_dir = tmp_path / "ETHUSDT" / "15m" / _TEST_MODEL_ID / "diagnostics"

    written = pipeline.write_fold_diagnostics_atomic(
        fold, model_id=_TEST_MODEL_ID, expected_n_trees=hyper.n_estimators, dest_dir=keyed_dir
    )

    assert len(written) == 2
    assert {p.name for p in written} == {"fold_0_long.json", "fold_0_short.json"}
    for path in written:
        assert path.parent == keyed_dir
    assert not (tmp_path / "nao_deveria_ser_usado").exists()


def test_write_all_fold_diagnostics_propaga_dest_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "MODELS_DIR", tmp_path / "nao_deveria_ser_usado")
    hyper = alpha.LGBMHyperparams.from_constants()
    folds = [
        _fake_fold_result(fold_id=i, path_id=0, variant=alpha.VARIANT_CAMADA1, seed=200 + i)
        for i in range(2)
    ]
    keyed_dir = tmp_path / "ETHUSDT" / "15m" / _TEST_MODEL_ID / "diagnostics"

    written = pipeline.write_all_fold_diagnostics(
        folds, model_id=_TEST_MODEL_ID, hyper=hyper, dest_dir=keyed_dir
    )

    assert len(written) == 2 * 2
    assert all(path.parent == keyed_dir for path in written)
    assert not (tmp_path / "nao_deveria_ser_usado").exists()


# ============================================================================
# Integração real — skip se o pipeline completo ainda não rodou
# ============================================================================


def _diagnostics_dir(model_id: str) -> Path:
    return MODELS_DIR / model_id / "diagnostics"


def _expected_n_diagnostics_files() -> int:
    """`n_splits * 2 lados` — `n_splits` é puramente combinatório
    (`C(n_groups, n_test_groups)`, ver `CPCVConfig.n_splits`), não um
    número inventado no teste: com `cpcv_n_groups=6`/`cpcv_n_test_groups=2`
    (`constants.yaml`) dá `C(6,2)=15`, batendo com os 15*2=30 citados na
    task A1 do CLAUDE.md."""
    return CPCVConfig.from_constants().n_splits * 2


def _skip_if_diagnostics_missing(model_id: str) -> None:
    n_expected = _expected_n_diagnostics_files()
    out_dir = _diagnostics_dir(model_id)
    n_found = len(list(out_dir.glob("*.json"))) if out_dir.exists() else 0
    if n_found != n_expected:
        pytest.skip(
            f"models/{model_id}/diagnostics/ tem {n_found} arquivo(s), esperado "
            f"{n_expected} — rode src.models.pipeline.run_layer1_sprint() primeiro "
            "(Sprint 8/task A1, ~117s)"
        )


@pytest.mark.parametrize("model_id", [MODEL_ID_CAMADA1, MODEL_ID_CAMADA0])
def test_diagnostics_reais_contagem_e_schema(model_id: str) -> None:
    _skip_if_diagnostics_missing(model_id)
    out_dir = _diagnostics_dir(model_id)
    files = sorted(out_dir.glob("*.json"))
    assert len(files) == _expected_n_diagnostics_files()

    expected_keys = {
        "schema_version",
        "model_id",
        "variant",
        "fold_id",
        "path_id",
        "side",
        "side_label",
        "gain_by_column",
        "concentration_shares",
        "hhi",
        "max_share",
        "n_features_over_1pct",
        # HHI EFETIVO (D1/D2, CLAUDE.md) — ver
        # test_write_fold_diagnostics_atomic_escreve_dois_json_validos acima
        # para a checagem de forma/bounds.
        "hhi_effective",
        "n_eff_factors_t1",
        "concentration_effective_weights",
        "concentration_effective_eigenvalues",
        "n_trees",
        "best_iteration",
        "best_iteration_note",
        "n_amostras",
    }
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert set(payload.keys()) == expected_keys
        assert payload["model_id"] == model_id
        assert payload["side_label"] in ("long", "short")
        assert payload["best_iteration"] is None
