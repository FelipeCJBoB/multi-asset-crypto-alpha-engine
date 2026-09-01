"""Testes de `src/models/meta_ablation.py` — F6 do Meta
(`docs/meta_model_design_doc_2026-08-22.md` §9).

**O teste que mais importa aqui é `test_run_ablation_para_sinal_forte_a1_supera_nulo_e_a3`
e seu par `test_run_ablation_sem_sinal_a1_nao_supera_nulo`** — juntos provam
que o gate distingue "Meta discrimina de verdade" de "Meta é ruído",
exatamente o que o §9 existe para garantir. Um gate que sempre passa (ou
sempre falha) não prova nada — os dois lados precisam ser exercitados."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.models import meta
from src.models import meta_ablation as ab
from src.models import meta_dataset as mds

_BAR_MS = 900_000


def _t0(n: int, *, start_ms: int = 0) -> pl.Series:
    vals = (np.arange(n, dtype=np.int64) * _BAR_MS) + start_ms
    return pl.Series(vals).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")


# ============================================================================
# compute_branch_panel
# ============================================================================


def _mk_panel_table(n: int, *, seed: int, accept_frac: float = 1.0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    ret_net = rng.normal(0.0, 0.02, size=n)
    barrier_hit = np.where(ret_net > 0.0, "TP", "SL")
    accept = (rng.random(n) < accept_frac).astype(np.int8) * rng.choice([-1, 1], size=n).astype(
        np.int8
    )
    return pl.DataFrame(
        {
            "ret_net": ret_net,
            "barrier_hit": barrier_hit,
            "accept_x": accept,
            "uniqueness_subpop": np.ones(n, dtype=np.float64),
        }
    )


def test_compute_branch_panel_aceita_tudo_da_pass_rate_1() -> None:
    table = _mk_panel_table(200, seed=1, accept_frac=1.0)
    panel = ab.compute_branch_panel(table, accept_col="accept_x")
    assert panel.n_signals == 200
    assert panel.pass_rate == pytest.approx(1.0)
    assert panel.n_accept == 200


def test_compute_branch_panel_sem_aceite_da_metricas_nan_nao_erro() -> None:
    table = _mk_panel_table(50, seed=2, accept_frac=0.0)
    panel = ab.compute_branch_panel(table, accept_col="accept_x")
    assert panel.n_accept == 0
    assert panel.pass_rate == pytest.approx(0.0)
    assert np.isnan(panel.win_rate)
    assert np.isnan(panel.sharpe_naive)
    # base_rate é sobre o UNIVERSO, não o aceito -- continua definida
    assert not np.isnan(panel.base_rate_unweighted)


def test_compute_branch_panel_base_rate_e_sobre_o_universo_nao_o_aceito() -> None:
    """Achado central do §9: comparar accuracy do aceito contra a taxa
    base do MESMO aceito seria tautológico -- a taxa base tem que vir do
    universo inteiro, senão nunca detecta "abaixo do acaso"."""
    n = 100
    # universo com win_rate=0.5 exato; aceita só os 10 primeiros, todos TP
    ret_net = np.array([0.02] * 50 + [-0.02] * 50)
    barrier_hit = np.array(["TP"] * 50 + ["SL"] * 50)
    accept = np.array([1] * 10 + [0] * 90, dtype=np.int8)
    table = pl.DataFrame(
        {
            "ret_net": ret_net,
            "barrier_hit": barrier_hit,
            "accept_x": accept,
            "uniqueness_subpop": np.ones(n, dtype=np.float64),
        }
    )
    panel = ab.compute_branch_panel(table, accept_col="accept_x")
    assert panel.base_rate_unweighted == pytest.approx(0.5)
    assert panel.accuracy_unweighted == pytest.approx(1.0)  # os 10 aceitos são todos TP


def test_compute_branch_panel_nofill_excluido_do_preenchido() -> None:
    table = pl.DataFrame(
        {
            "ret_net": [0.02, -0.01, 0.0],
            "barrier_hit": ["TP", "SL", "NOFILL"],
            "accept_x": pl.Series([1, 1, 1], dtype=pl.Int8),
            "uniqueness_subpop": [1.0, 1.0, 1.0],
        }
    )
    panel = ab.compute_branch_panel(table, accept_col="accept_x")
    assert panel.n_accept == 3
    assert panel.n_filled == 2
    assert panel.fill_rate == pytest.approx(2 / 3)


# ============================================================================
# jaccard_accept_sets
# ============================================================================


def test_jaccard_conjuntos_identicos_da_1() -> None:
    a = np.array([1, -1, 0, 1], dtype=np.int64)
    assert ab.jaccard_accept_sets(a, a) == pytest.approx(1.0)


def test_jaccard_conjuntos_disjuntos_da_0() -> None:
    a = np.array([1, 0, 0, 0], dtype=np.int64)
    b = np.array([0, -1, 0, 0], dtype=np.int64)
    assert ab.jaccard_accept_sets(a, b) == pytest.approx(0.0)


def test_jaccard_ambos_vazios_da_nan() -> None:
    a = np.zeros(5, dtype=np.int64)
    assert np.isnan(ab.jaccard_accept_sets(a, a))


def test_jaccard_tamanhos_diferentes_levanta() -> None:
    with pytest.raises(ab.MetaAblationError):
        ab.jaccard_accept_sets(np.zeros(3, dtype=np.int64), np.zeros(5, dtype=np.int64))


# ============================================================================
# build_branch_a0 / build_branch_a3
# ============================================================================


def test_build_branch_a0_aceita_todo_side_hat_sem_inverter() -> None:
    table = pl.DataFrame({"side_hat": pl.Series([1, -1, 1, -1], dtype=pl.Int8)})
    out = ab.build_branch_a0(table)
    assert out[ab.ACCEPT_A0].to_list() == [1, -1, 1, -1]


def test_build_branch_a3_pareia_pass_rate_por_estrato() -> None:
    """Estrato único (1 meta_split_id, 1 symbol, 1 side_hat): A1 aceita 3
    de 10 -> A3 precisa aceitar EXATAMENTE os 3 de maior p_alpha."""
    n = 10
    p_alpha = np.array([0.9, 0.8, 0.1, 0.7, 0.2, 0.3, 0.6, 0.4, 0.5, 0.05])
    accept_a1 = np.array([1, 0, 0, 1, 0, 0, 1, 0, 0, 0], dtype=np.int8)  # 3 aceitos
    table = pl.DataFrame(
        {
            "meta_split_id": pl.Series([0] * n, dtype=pl.Int16),
            "symbol": ["TESTUSDT"] * n,
            "side_hat": pl.Series([1] * n, dtype=pl.Int8),
            "p_alpha": p_alpha,
            ab.ACCEPT_A1: accept_a1,
        }
    )
    out = ab.build_branch_a3(table)
    # `build_branch_a3` reordena as linhas internamente (sort por p_alpha
    # descendente) -- ler p_alpha/aceite do PRÓPRIO `out`, não indexar de
    # volta no array original por posição (linha i de `out` != linha i
    # de `table` depois do sort).
    aceitos = out.filter(pl.col(ab.ACCEPT_A3) != 0)
    assert aceitos.height == 3
    p_alpha_aceitos = sorted(aceitos["p_alpha"].to_list())
    esperado = sorted(np.sort(p_alpha)[-3:].tolist())
    assert p_alpha_aceitos == pytest.approx(esperado)


def test_build_branch_a3_sem_accept_a1_levanta() -> None:
    table = pl.DataFrame({"meta_split_id": [0], "symbol": ["X"], "side_hat": [1], "p_alpha": [0.5]})
    with pytest.raises(ab.MetaAblationError, match="accept_a1"):
        ab.build_branch_a3(table)


def test_build_branch_a3_estrato_sem_aceite_em_a1_nao_aceita_nada() -> None:
    n = 5
    table = pl.DataFrame(
        {
            "meta_split_id": pl.Series([0] * n, dtype=pl.Int16),
            "symbol": ["TESTUSDT"] * n,
            "side_hat": pl.Series([1] * n, dtype=pl.Int8),
            "p_alpha": [0.9, 0.1, 0.5, 0.3, 0.7],
            ab.ACCEPT_A1: pl.Series([0] * n, dtype=pl.Int8),
        }
    )
    out = ab.build_branch_a3(table)
    assert out[ab.ACCEPT_A3].to_list() == [0] * n


# ============================================================================
# run_a2_null_replicas — o nulo A2
# ============================================================================


def _mk_fold_result(
    *,
    meta_split_id: int,
    path_id: int,
    n_train: int,
    n_test: int,
    seed: int,
    discriminativo: bool,
    fold_status: str = mds.META_STATUS_OK,
) -> meta.MetaFoldResult:
    """Constrói um `MetaFoldResult` diretamente (sem passar por `run_meta_
    fold`) -- foco em `train_predictions`/`test_predictions` com `p_meta`
    controlado, pra isolar o teste do nulo A2 da máquina de ajuste."""
    rng = np.random.default_rng(seed)

    def _mk(n: int, *, start: int) -> pl.DataFrame:
        side_hat = rng.choice([-1, 1], size=n).astype(np.int8)
        if discriminativo:
            p_meta = rng.uniform(0.0, 1.0, size=n)
            ret_net = np.where(
                p_meta > 0.5, rng.uniform(0.005, 0.03, n), rng.uniform(-0.03, -0.005, n)
            )
        else:
            # quase constante -- sem poder discriminativo real
            p_meta = rng.uniform(0.4, 0.6, size=n)
            ret_net = rng.normal(0.0, 0.02, size=n)
        barrier_hit = np.where(ret_net > 0.0, "TP", "SL")
        return pl.DataFrame(
            {
                "t0": _t0(n, start_ms=start * _BAR_MS),
                "meta_split_id": pl.Series([meta_split_id] * n, dtype=pl.Int16),
                "path_id": pl.Series([path_id] * n, dtype=pl.Int64),
                "side_hat": pl.Series(side_hat.tolist(), dtype=pl.Int8),
                "p_meta": p_meta,
                "p_alpha": rng.uniform(0.5, 0.9, size=n),
                "ret_net": ret_net,
                "barrier_hit": barrier_hit,
                "uniqueness_subpop": np.ones(n, dtype=np.float64),
                "meta_status": [mds.META_STATUS_OK] * n,
            }
        )

    train = _mk(n_train, start=0)
    test = _mk(n_test, start=n_train)
    # side_final: p_meta >= mediana do próprio teste (tau simplificado, só
    # pra ter um side_final internamente consistente com p_meta -- o teste
    # de A2 não depende do valor exato de tau, só de p_meta/ret_net reais).
    tau = float(np.median(test["p_meta"].to_numpy())) if n_test > 0 else 0.5
    side_final = meta.apply_meta_filter(
        test["side_hat"].to_numpy().astype(np.int64),
        test["p_meta"].to_numpy().astype(np.float64),
        tau_meta=tau,
    )
    test = test.with_columns(side_final=pl.Series(side_final))

    return meta.MetaFoldResult(
        meta_split_id=meta_split_id,
        path_id=path_id,
        fold_status=fold_status,
        n_events_effective=1000.0,
        n_features_effective=9,
        n_train=n_train,
        tau_meta=None,
        design_rank=None,
        coefficient_shares=None,
        test_predictions=test,
        train_predictions=train if fold_status == mds.META_STATUS_OK else None,
    )


def test_run_a2_null_replicas_devolve_n_seeds_valores() -> None:
    fold = _mk_fold_result(
        meta_split_id=0, path_id=0, n_train=300, n_test=100, seed=1, discriminativo=True
    )
    rng = np.random.default_rng(0)
    sharpes = ab.run_a2_null_replicas(fold, n_seeds=50, rng=rng)
    assert sharpes.shape[0] == 50


def test_run_a2_null_replicas_fold_pass_through_devolve_vazio() -> None:
    fold = _mk_fold_result(
        meta_split_id=0,
        path_id=0,
        n_train=10,
        n_test=10,
        seed=2,
        discriminativo=True,
        fold_status=mds.META_STATUS_INSUFFICIENT_SAMPLE,
    )
    rng = np.random.default_rng(0)
    sharpes = ab.run_a2_null_replicas(fold, n_seeds=20, rng=rng)
    assert sharpes.shape[0] == 0


# ============================================================================
# run_ablation_for_combo — o gate completo
# ============================================================================


def test_run_ablation_para_sinal_forte_a1_supera_nulo_e_a3() -> None:
    """Sinal FORTE e real em `p_meta`: A1 precisa superar o nulo A2 e o
    baseline A3 na maioria dos paths -- prova que o gate detecta
    discriminação real quando ela existe."""
    folds = []
    for path_id in range(5):
        for j in range(3):
            fold_id = path_id * 3 + j
            folds.append(
                _mk_fold_result(
                    meta_split_id=fold_id,
                    path_id=path_id,
                    n_train=400,
                    n_test=150,
                    seed=100 + fold_id,
                    discriminativo=True,
                )
            )
    meta_training_set = pl.concat([f.test_predictions for f in folds], how="vertical")
    result = ab.run_ablation_for_combo(
        tuple(folds),
        meta_training_set,
        symbol="TESTUSDT",
        resolution_id="R2",
        variant="camada1",
        n_seeds=100,
        random_state=0,
    )
    assert result.n_paths_total == 5
    assert result.n_paths_passed >= 4, "sinal forte deveria passar na maioria dos paths"
    assert result.gate_passed is True


def test_run_ablation_sem_sinal_a1_nao_supera_nulo() -> None:
    """Sinal NULO (p_meta quase constante, sem relação real com ret_net):
    A1 não deveria superar o nulo A2 sistematicamente -- prova que o
    gate NÃO aprova ruído."""
    folds = []
    for path_id in range(5):
        for j in range(3):
            fold_id = path_id * 3 + j
            folds.append(
                _mk_fold_result(
                    meta_split_id=fold_id,
                    path_id=path_id,
                    n_train=400,
                    n_test=150,
                    seed=200 + fold_id,
                    discriminativo=False,
                )
            )
    meta_training_set = pl.concat([f.test_predictions for f in folds], how="vertical")
    result = ab.run_ablation_for_combo(
        tuple(folds),
        meta_training_set,
        symbol="TESTUSDT",
        resolution_id="R2",
        variant="camada1",
        n_seeds=100,
        random_state=1,
    )
    assert result.n_paths_passed <= 1, "sem sinal real, o gate nao deveria aprovar quase nada"
    assert result.gate_passed is False


def test_run_ablation_path_com_fold_pass_through_nunca_conta_como_pass() -> None:
    """§9, correção 4 -- path com QUALQUER fold pass-through é reportado
    separado e NUNCA conta como PASS, mesmo que os outros 2 folds do
    path sejam fortemente discriminativos."""
    folds = [
        _mk_fold_result(
            meta_split_id=0, path_id=0, n_train=400, n_test=150, seed=1, discriminativo=True
        ),
        _mk_fold_result(
            meta_split_id=1, path_id=0, n_train=400, n_test=150, seed=2, discriminativo=True
        ),
        _mk_fold_result(
            meta_split_id=2,
            path_id=0,
            n_train=10,
            n_test=50,
            seed=3,
            discriminativo=True,
            fold_status=mds.META_STATUS_INSUFFICIENT_SAMPLE,
        ),
    ]
    meta_training_set = pl.concat([f.test_predictions for f in folds], how="vertical")
    result = ab.run_ablation_for_combo(
        tuple(folds),
        meta_training_set,
        symbol="TESTUSDT",
        resolution_id="R2",
        variant="camada1",
        n_seeds=50,
        min_paths_required=1,
        random_state=0,
    )
    assert result.n_paths_total == 1
    path0 = result.path_results[0]
    assert path0.n_folds == 3
    assert path0.n_folds_ok == 2
    assert path0.passed is False, "fold pass-through invalida o path mesmo com 2/3 fortes"


def test_run_ablation_path_com_todos_os_folds_pass_through_nao_quebra() -> None:
    """Achado real (2026-08-31, BTCUSDT/R2): um path pode ter TODOS os
    folds em pass-through -- `null_sharpes` fica vazio pros 3 folds do
    path, `np.concatenate([])` levantava `ValueError` antes do fix."""
    folds = [
        _mk_fold_result(
            meta_split_id=j,
            path_id=0,
            n_train=10,
            n_test=20,
            seed=j,
            discriminativo=True,
            fold_status=mds.META_STATUS_INSUFFICIENT_SAMPLE,
        )
        for j in range(3)
    ]
    meta_training_set = pl.concat([f.test_predictions for f in folds], how="vertical")
    result = ab.run_ablation_for_combo(
        tuple(folds),
        meta_training_set,
        symbol="TESTUSDT",
        resolution_id="R2",
        variant="camada1",
        n_seeds=20,
        min_paths_required=1,
        random_state=0,
    )
    assert result.n_paths_total == 1
    path0 = result.path_results[0]
    assert path0.n_folds_ok == 0
    assert path0.null_sharpes_a2.shape[0] == 0
    assert np.isnan(path0.p95_null_a2)
    assert path0.passed is False
