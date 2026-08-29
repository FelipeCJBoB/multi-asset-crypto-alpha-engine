"""Testes de `src.models.hyperparams_by_combo` -- foco na trava de
compatibilidade de vetor de features (AG-371, `audit/architecture_gaps_
log.yaml`, 2026-08-28): hiperparâmetro calibrado (ADR-003, 25/08) sob um
vetor de features específico não pode ser injetado silenciosamente sob
outro vetor sem medição nova (a campanha de 25/08 mediu sob os 62
`SUPPORT_FEATURE_IDS` da época; `AG-362`, 27/08, reestruturou
`T1_FEATURE_IDS` sem recalibrar este arquivo -- exatamente o que o
retreino canônico de 28/08 injetou sem checagem).

`_cache` monkeypatchado direto (mesmo padrão do loader de `_constants.py`
citado na docstring do módulo) -- nenhum teste aqui toca o YAML real de
`config/alpha_hyperparams_by_combo.yaml`."""

from __future__ import annotations

from typing import Any

import pytest

from src.models import hyperparams_by_combo as mod
from src.models.alpha import LGBMHyperparams

_FEATURE_IDS_A = ("A01", "A02", "A03")
_FEATURE_IDS_B = ("B01", "B02")

_COMBO_ENTRY = {
    "max_depth": 2,
    "num_leaves": 3,
    "min_child_samples": 2000,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "feature_fraction": 1.0,
    "lambda_l2": 5.0,
    "n_estimators": 300,
    "min_sum_hessian_in_leaf": 0.001,
}


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_cache", None, raising=False)


def _set_payload(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr(mod, "_cache", payload)


def test_compute_feature_ids_hash_e_independente_de_ordem() -> None:
    assert mod.compute_feature_ids_hash(("A01", "A02", "A03")) == mod.compute_feature_ids_hash(
        ("A03", "A01", "A02")
    )


def test_compute_feature_ids_hash_muda_com_conteudo() -> None:
    assert mod.compute_feature_ids_hash(_FEATURE_IDS_A) != mod.compute_feature_ids_hash(
        _FEATURE_IDS_B
    )


def test_combo_sem_calibracao_retorna_none_sem_checar_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`entry is None` (5 das 15 combinações) pula a checagem de feature
    -- não há hiperparâmetro calibrado pra validar contra nada, mesmo que
    `feature_ids_hash` do header também esteja ausente/errado."""
    _set_payload(monkeypatch, {"feature_ids_hash": None, "combos": {}})

    hyper, mismatch = mod.load_hyperparams_by_combo(
        "BTCUSDT", "R1", feature_ids_effective=_FEATURE_IDS_A
    )

    assert hyper is None
    assert mismatch is False


def test_hash_bate_retorna_hyper_sem_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_hash = mod.compute_feature_ids_hash(_FEATURE_IDS_A)
    _set_payload(
        monkeypatch,
        {"feature_ids_hash": expected_hash, "combos": {"BTCUSDT_R1": _COMBO_ENTRY}},
    )

    hyper, mismatch = mod.load_hyperparams_by_combo(
        "BTCUSDT", "R1", feature_ids_effective=_FEATURE_IDS_A
    )

    assert isinstance(hyper, LGBMHyperparams)
    assert hyper.num_leaves == 3
    assert mismatch is False


def test_hash_diferente_levanta_por_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """AG-371 -- comportamento DEFAULT é fail-closed. O warning que já
    existia pra 'combinação sem calibração' não impediu ninguém de
    confiar no retreino contaminado de 28/08; um segundo warning aqui
    repetiria o mesmo erro."""
    stale_hash = mod.compute_feature_ids_hash(_FEATURE_IDS_B)
    _set_payload(
        monkeypatch,
        {"feature_ids_hash": stale_hash, "combos": {"BTCUSDT_R1": _COMBO_ENTRY}},
    )

    with pytest.raises(mod.HyperparamFeatureMismatchError):
        mod.load_hyperparams_by_combo("BTCUSDT", "R1", feature_ids_effective=_FEATURE_IDS_A)


def test_feature_ids_hash_ausente_no_header_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Header sem `feature_ids_hash` (`null`, arquivo pré-AG-371 nunca
    migrado) -- fail-closed, não silenciosamente aceito como 'sem
    checagem disponível'."""
    _set_payload(monkeypatch, {"combos": {"BTCUSDT_R1": _COMBO_ENTRY}})

    with pytest.raises(mod.HyperparamFeatureMismatchError):
        mod.load_hyperparams_by_combo("BTCUSDT", "R1", feature_ids_effective=_FEATURE_IDS_A)


def test_allow_feature_mismatch_rebaixa_pra_warning_e_retorna_hyper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`allow_feature_mismatch=True` -- só pra comparação exploratória
    deliberada (mesmo espírito de `scratch=True`, AG-368): não levanta,
    mas o `mismatch=True` de volta precisa sobreviver pro chamador marcar
    o report como contaminado."""
    stale_hash = mod.compute_feature_ids_hash(_FEATURE_IDS_B)
    _set_payload(
        monkeypatch,
        {"feature_ids_hash": stale_hash, "combos": {"BTCUSDT_R1": _COMBO_ENTRY}},
    )

    hyper, mismatch = mod.load_hyperparams_by_combo(
        "BTCUSDT",
        "R1",
        feature_ids_effective=_FEATURE_IDS_A,
        allow_feature_mismatch=True,
    )

    assert isinstance(hyper, LGBMHyperparams)
    assert mismatch is True
