"""Testes de `src.models.walk_forward` — ADR-008 Fase 4. Núcleo puro
(Idioma A), mesmo padrão de `test_models_alpha_item6_8_9.py::
test_three_way_split_*` para `_temporal_purged_three_way_split`.

Fixtures com 2 LINHAS POR BARRA (`side=1`/`side=-1`, `t0` repetido) —
mesma realidade de `mf.data`/`labels.parquet` que `alpha.run_fold` de
fato fatia (achado real, ver docstring do módulo: `t0_ms` não é
globalmente monótono, por isso o adaptador trabalha por timestamp via
`unique_t0_ms`, não por posição direta)."""

from __future__ import annotations

import numpy as np
import pytest

from src.models import walk_forward as wf
from src.validation.volatility_walkforward import WalkForwardSplit


def _duas_linhas_por_barra(unique_t0: np.ndarray, t1: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`df_all` de 2 linhas/barra, mas ORDENADO por bloco de lado (todo
    `side=1` primeiro, depois todo `side=-1`) -- o padrão que quebrou
    `np.searchsorted` na execução real contra `BTCUSDT/R2` (`t0` cai de
    volta ao início na metade do array, não globalmente crescente)."""
    t0_ms = np.concatenate([unique_t0, unique_t0])
    t1_ms = np.concatenate([t1, t1])
    return t0_ms, t1_ms


def test_sem_overlap_de_t1_treino_e_teste_intactos() -> None:
    """`t1 = t0 + 500` nunca cruza a fronteira de teste (bloco de 1000 em
    1000) -- purge não remove nada, `n_train`/`n_test` batem exatamente
    com o dobro do range do `WalkForwardSplit` (2 linhas/barra)."""
    unique_t0 = np.arange(0, 20, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = unique_t0 + 500  # noqa: magic-number
    t0_ms, t1_ms = _duas_linhas_por_barra(unique_t0, t1)
    split = WalkForwardSplit(fold_id=0, train_end_idx=10, test_start_idx=10, test_end_idx=15)  # noqa: magic-number

    out = wf.walk_forward_split_to_cpcv_split(split, unique_t0, t0_ms, t1_ms)

    assert out.train_idx.shape[0] == 20  # noqa: magic-number -- 10 barras x 2 lados
    assert out.test_idx.shape[0] == 10  # noqa: magic-number -- 5 barras x 2 lados
    assert bool((t0_ms[out.train_idx] < unique_t0[10]).all())
    test_t0 = t0_ms[out.test_idx]
    assert bool(((test_t0 >= unique_t0[10]) & (test_t0 < unique_t0[15])).all())
    assert out.n_purged == 0
    assert out.n_train_candidate == 20  # noqa: magic-number
    assert out.split_id == 0
    # path_id == fold_id (não 0 fixo) -- ver docstring do módulo:
    # backtest_lite.backtest_by_path agrupa por path_id, precisa de 1
    # valor distinto por fold pra tratar cada fold como seu próprio
    # "caminho" de 1 fold.
    assert out.path_id == 0
    assert out.test_groups == ()
    assert out.train_groups == ()
    assert out.n_embargoed == 0


def test_purga_treino_cujo_t1_cruza_a_fronteira_de_teste() -> None:
    """`t1 = t0 + 3000` cruza a fronteira de teste (`test_start=10000`)
    pras últimas barras do treino candidato -- purge remove ESSAS (dos
    dois lados), mantém o resto."""
    unique_t0 = np.arange(0, 20, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = unique_t0 + 3_000  # noqa: magic-number
    t0_ms, t1_ms = _duas_linhas_por_barra(unique_t0, t1)
    split = WalkForwardSplit(fold_id=1, train_end_idx=10, test_start_idx=10, test_end_idx=15)  # noqa: magic-number

    out = wf.walk_forward_split_to_cpcv_split(split, unique_t0, t0_ms, t1_ms)

    test_start = int(unique_t0[10])
    assert out.n_purged > 0
    assert out.n_purged < 20  # noqa: magic-number -- purga parte, não tudo
    assert bool((t1_ms[out.train_idx] < test_start).all())
    # teste nunca é tocado pelo purge -- sempre as barras cruas do split.
    assert out.test_idx.shape[0] == 10  # noqa: magic-number


def test_purge_esvaziando_treino_levanta_valueerror() -> None:
    """Todo `t1` do treino candidato aberto além do início do teste --
    purge esvaziaria o treino inteiro, falha alta em vez de treinar
    sobre 0 linhas."""
    unique_t0 = np.arange(0, 10, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = unique_t0 + 10_000_000  # noqa: magic-number -- horizonte de label cobre toda a série
    t0_ms, t1_ms = _duas_linhas_por_barra(unique_t0, t1)
    split = WalkForwardSplit(fold_id=2, train_end_idx=5, test_start_idx=5, test_end_idx=8)  # noqa: magic-number

    with pytest.raises(ValueError, match="esvaziou o treino"):
        wf.walk_forward_split_to_cpcv_split(split, unique_t0, t0_ms, t1_ms)


def test_split_id_e_path_id_refletem_fold_id_do_walk_forward_split() -> None:
    """`path_id == fold_id` (não `0` fixo) -- ver docstring do módulo:
    `backtest_lite.backtest_by_path` agrupa por `path_id`, precisa de 1
    valor distinto por fold pra tratar cada fold de walk-forward como
    seu próprio "caminho" de 1 fold, reusando essa função já testada."""
    unique_t0 = np.arange(0, 10, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = unique_t0 + 100  # noqa: magic-number
    t0_ms, t1_ms = _duas_linhas_por_barra(unique_t0, t1)
    split = WalkForwardSplit(fold_id=7, train_end_idx=5, test_start_idx=5, test_end_idx=8)  # noqa: magic-number

    out = wf.walk_forward_split_to_cpcv_split(split, unique_t0, t0_ms, t1_ms)

    assert out.split_id == 7  # noqa: magic-number
    assert out.path_id == 7  # noqa: magic-number


def test_ultimo_fold_test_end_idx_igual_ao_comprimento_da_timeline() -> None:
    """`test_end_idx == len(unique_t0_ms)` (último fold, "até o fim da
    série") -- não existe `unique_t0_ms[test_end_idx]` pra ler; o
    fechamento à direita usa `t0_ms.max() + 1`, sem excluir a última
    barra real."""
    unique_t0 = np.arange(0, 12, dtype=np.int64) * 1_000  # noqa: magic-number
    t1 = unique_t0 + 100  # noqa: magic-number
    t0_ms, t1_ms = _duas_linhas_por_barra(unique_t0, t1)
    split = WalkForwardSplit(fold_id=3, train_end_idx=8, test_start_idx=8, test_end_idx=12)  # noqa: magic-number

    out = wf.walk_forward_split_to_cpcv_split(split, unique_t0, t0_ms, t1_ms)

    assert out.test_idx.shape[0] == 8  # noqa: magic-number -- 4 barras finais x 2 lados
    assert bool((t0_ms[out.test_idx] >= unique_t0[8]).all())
