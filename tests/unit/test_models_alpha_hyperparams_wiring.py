"""Testes do wiring unificado de `regularization_basis`/`early_stopping_
mode`/`ic_magnitude_floor_k` (handoff de `src/models/`, item 1,
2026-08-27, `AG-324`/`AG-325`/`AG-326`).

Os 3 já eram implementados/testados em `fit_side_model` (`tests/unit/
test_models_alpha_item6_8_9.py`) mas presos no mesmo teto -- nenhuma
camada acima (`run_fold`/`run_all_folds`/`run_layer1_sprint`) tinha como
setá-los. A correção NÃO adiciona parâmetro novo em nenhuma das 3 camadas
-- os 3 viram campos de `LGBMHyperparams`, que já atravessa as 3 intacto
via `hyper=hyper`. Este arquivo cobre a peça que faltava: `LGBMHyper
params` em si, e a wiring real dentro de `run_fold`."""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import polars as pl
import pytest

from src.features.build import T1_FEATURE_IDS
from src.models import alpha
from src.models import dataset as ds
from src.validation.cpcv import CPCVSplit

# ============================================================================
# LGBMHyperparams -- defaults bit-exatos, from_constants() opt-in
# ============================================================================


def test_lgbm_hyperparams_defaults_sao_os_promovidos_2026_08_27() -> None:
    """**[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27]** -- os defaults do
    dataclass, construído sem setar os três campos, já são o comportamento
    CORRIGIDO (`AG-324`/`AG-325`/`AG-326`), não mais o legado. Ver
    `CLAUDE.md` "Diretrizes de comportamento"."""
    hyper = alpha.LGBMHyperparams(
        max_depth=3,
        n_estimators=100,  # noqa: magic-number
        learning_rate=0.1,  # noqa: magic-number
        subsample=0.8,  # noqa: magic-number
        subsample_freq=1,
        feature_fraction=1.0,
        lambda_l2=0.0,
        min_child_samples=20,  # noqa: magic-number
        num_leaves=3,
    )
    assert hyper.regularization_basis == alpha.REGULARIZATION_ESS_DERIVED
    assert hyper.early_stopping_mode == alpha.EARLY_STOPPING_THREE_WAY
    # campo do dataclass -- from_constants() é quem resolve o valor real
    assert hyper.ic_magnitude_floor_k is None


def test_lgbm_hyperparams_construcao_explicita_reproduz_o_legado() -> None:
    """O legado continua acessível, só deixou de ser o default -- quem
    quiser reproduzir o comportamento anterior passa os três campos
    explicitamente."""
    hyper = alpha.LGBMHyperparams(
        max_depth=3,
        n_estimators=100,  # noqa: magic-number
        learning_rate=0.1,  # noqa: magic-number
        subsample=0.8,  # noqa: magic-number
        subsample_freq=1,
        feature_fraction=1.0,
        lambda_l2=0.0,
        min_child_samples=20,  # noqa: magic-number
        num_leaves=3,
        regularization_basis=alpha.REGULARIZATION_FIXED,
        early_stopping_mode=alpha.EARLY_STOPPING_FIXED,
    )
    assert hyper.regularization_basis == alpha.REGULARIZATION_FIXED
    assert hyper.early_stopping_mode == alpha.EARLY_STOPPING_FIXED


def test_from_constants_default_le_ic_magnitude_floor_k() -> None:
    """**[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27]** -- `from_constants()`
    sem argumento nenhum já lê `alpha_monotonic_ic_magnitude_floor_k` de
    `constants.yaml` (`AG-324`: medido, `|mean_ic| ~= 0,007` contra
    `SE ~= 0,005`), fechando a desconexão constante↔código sem precisar de
    `use_ic_magnitude_floor=True` explícito."""
    hyper = alpha.LGBMHyperparams.from_constants()
    assert hyper.ic_magnitude_floor_k == pytest.approx(2.0)  # noqa: magic-number -- valor real de constants.yaml, não invenção do teste
    assert hyper.regularization_basis == alpha.REGULARIZATION_ESS_DERIVED
    assert hyper.early_stopping_mode == alpha.EARLY_STOPPING_THREE_WAY


def test_from_constants_use_ic_magnitude_floor_false_reproduz_o_legado() -> None:
    """O legado (`ic_magnitude_floor_k=None`, sinal+consistência puro)
    continua acessível -- só deixou de ser o default."""
    hyper = alpha.LGBMHyperparams.from_constants(use_ic_magnitude_floor=False)
    assert hyper.ic_magnitude_floor_k is None


# ============================================================================
# run_fold -- prova de wiring: os 3 campos de `hyper` chegam em
# `fit_side_model` sem precisar de parâmetro novo em `run_fold` em si.
# `ds.side_subset`/`alpha.fit_side_model` monkeypatchados -- o que este
# teste prova é ROTEAMENTO (mesmo espírito de `test_models_pipeline_
# paths.py`), não o comportamento de treino em si (já coberto em `test_
# models_alpha_item6_8_9.py`).
# ============================================================================


class _StopEarly(Exception):
    """Aborta `run_fold` logo depois da 2ª chamada de `fit_side_model`
    (lado short) -- captura os kwargs dos dois lados sem pagar o custo de
    rodar o resto de `run_fold` (backtest/monotonic/concentration)."""


def _minimal_df_and_split() -> tuple[pl.DataFrame, CPCVSplit]:
    df = pl.DataFrame({"t0": [0]}).with_columns(
        pl.col("t0").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    )
    idx = np.array([0], dtype=np.int64)
    split = CPCVSplit(
        split_id=0,
        path_id=0,
        test_groups=(0,),
        train_groups=(0,),
        train_idx=idx,
        test_idx=idx,
        n_train_candidate=1,
        n_purged=0,
        n_embargoed=0,
    )
    return df, split


def test_run_fold_repassa_os_tres_campos_de_hyper_pros_dois_lados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df, split = _minimal_df_and_split()
    calls: list[dict[str, Any]] = []

    def _fake_side_subset(frame: pl.DataFrame, **kwargs: Any) -> pl.DataFrame:
        return frame

    def _fake_fit_side_model(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        if len(calls) == 2:
            raise _StopEarly
        return None

    monkeypatch.setattr(ds, "side_subset", _fake_side_subset)
    monkeypatch.setattr(alpha, "fit_side_model", _fake_fit_side_model)

    hyper = dataclasses.replace(
        alpha.LGBMHyperparams.from_constants(),
        regularization_basis=alpha.REGULARIZATION_ESS_DERIVED,
        early_stopping_mode=alpha.EARLY_STOPPING_THREE_WAY,
        ic_magnitude_floor_k=3.0,  # noqa: magic-number -- valor arbitrário só pra provar que atravessa
    )

    with pytest.raises(_StopEarly):
        alpha.run_fold(
            df,
            split,
            variant=alpha.VARIANT_CAMADA1,
            model_id="test_model",
            hyper=hyper,
            seed=1,
            symbol="BTCUSDT",
            feature_ids=T1_FEATURE_IDS,
        )

    assert len(calls) == 2
    for side_kwargs in calls:
        assert side_kwargs["regularization_basis"] == alpha.REGULARIZATION_ESS_DERIVED
        assert side_kwargs["early_stopping_mode"] == alpha.EARLY_STOPPING_THREE_WAY
        assert side_kwargs["ic_magnitude_floor_k"] == pytest.approx(3.0)  # noqa: magic-number


def test_run_fold_default_hyper_repassa_os_defaults_promovidos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27]** -- `hyper` sem os
    três campos setados (`LGBMHyperparams.from_constants()`) já chega em
    `fit_side_model` com o comportamento CORRIGIDO, não mais o legado."""
    df, split = _minimal_df_and_split()
    calls: list[dict[str, Any]] = []

    def _fake_side_subset(frame: pl.DataFrame, **kwargs: Any) -> pl.DataFrame:
        return frame

    def _fake_fit_side_model(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        if len(calls) == 2:
            raise _StopEarly
        return None

    monkeypatch.setattr(ds, "side_subset", _fake_side_subset)
    monkeypatch.setattr(alpha, "fit_side_model", _fake_fit_side_model)

    with pytest.raises(_StopEarly):
        alpha.run_fold(
            df,
            split,
            variant=alpha.VARIANT_CAMADA1,
            model_id="test_model",
            hyper=alpha.LGBMHyperparams.from_constants(),
            seed=1,
            symbol="BTCUSDT",
            feature_ids=T1_FEATURE_IDS,
        )

    for side_kwargs in calls:
        assert side_kwargs["regularization_basis"] == alpha.REGULARIZATION_ESS_DERIVED
        assert side_kwargs["early_stopping_mode"] == alpha.EARLY_STOPPING_THREE_WAY
        assert side_kwargs["ic_magnitude_floor_k"] == pytest.approx(2.0)  # noqa: magic-number -- valor real de constants.yaml
