"""Testes de `src.models.walk_forward` — ADR-008 Fase 4. Núcleo puro
(Idioma A), mesmo padrão de `test_models_alpha_item6_8_9.py::
test_three_way_split_*` para `_temporal_purged_three_way_split`."""

from __future__ import annotations

import numpy as np
import pytest

from src.models import walk_forward as wf
from src.validation.volatility_walkforward import WalkForwardSplit


def test_sem_overlap_de_t1_treino_e_teste_intactos() -> None:
    """`t1 = t0 + 500` nunca cruza a fronteira de teste (bloco de 1000 em
    1000) -- purge não remove nada, `train_idx`/`test_idx` batem
    exatamente com os índices do `WalkForwardSplit`."""
    t0 = np.arange(0, 20, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = t0 + 500  # noqa: magic-number
    split = WalkForwardSplit(fold_id=0, train_end_idx=10, test_start_idx=10, test_end_idx=15)  # noqa: magic-number

    out = wf.walk_forward_split_to_cpcv_split(split, t0, t1)

    np.testing.assert_array_equal(out.train_idx, np.arange(10))
    np.testing.assert_array_equal(out.test_idx, np.arange(10, 15))
    assert out.n_purged == 0
    assert out.n_train_candidate == 10  # noqa: magic-number
    assert out.split_id == 0
    assert out.path_id == 0
    assert out.test_groups == ()
    assert out.train_groups == ()
    assert out.n_embargoed == 0


def test_purga_treino_cujo_t1_cruza_a_fronteira_de_teste() -> None:
    """`t1 = t0 + 3000` cruza a fronteira de teste (`test_start=10000`)
    pras últimas linhas do treino candidato (`t0` em [7000,9000] tem
    `t1` em [10000,12000], >= 10000) -- purge remove ESSAS, mantém o
    resto."""
    t0 = np.arange(0, 20, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = t0 + 3_000  # noqa: magic-number
    split = WalkForwardSplit(fold_id=1, train_end_idx=10, test_start_idx=10, test_end_idx=15)  # noqa: magic-number

    out = wf.walk_forward_split_to_cpcv_split(split, t0, t1)

    test_start = int(t0[10])
    assert out.n_purged > 0
    assert out.n_purged < 10  # noqa: magic-number -- purga parte, não tudo
    assert bool((t1[out.train_idx] < test_start).all())
    # teste nunca é tocado pelo purge -- sempre os índices crus do split.
    np.testing.assert_array_equal(out.test_idx, np.arange(10, 15))


def test_purge_esvaziando_treino_levanta_valueerror() -> None:
    """Todo `t1` do treino candidato aberto além do início do teste --
    purge esvaziaria o treino inteiro, falha alta em vez de treinar
    sobre 0 linhas."""
    t0 = np.arange(0, 10, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = t0 + 10_000_000  # noqa: magic-number -- horizonte de label cobre toda a série
    split = WalkForwardSplit(fold_id=2, train_end_idx=5, test_start_idx=5, test_end_idx=8)  # noqa: magic-number

    with pytest.raises(ValueError, match="esvaziou o treino"):
        wf.walk_forward_split_to_cpcv_split(split, t0, t1)


def test_split_id_reflete_fold_id_do_walk_forward_split() -> None:
    t0 = np.arange(0, 10, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = t0 + 100  # noqa: magic-number
    split = WalkForwardSplit(fold_id=7, train_end_idx=5, test_start_idx=5, test_end_idx=8)  # noqa: magic-number

    out = wf.walk_forward_split_to_cpcv_split(split, t0, t1)

    assert out.split_id == 7  # noqa: magic-number
