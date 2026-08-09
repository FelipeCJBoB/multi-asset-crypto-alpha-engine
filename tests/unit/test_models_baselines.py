"""Testes de `src/models/baselines.py` — foco no refinamento estatístico
do B1 (correção pós Sprint 8, ver docstring do módulo e
`experiments/alpha_b1_refinement_report.json`):

1. `run_b1_per_path` — cada caminho de CPCV contra um nulo do PRÓPRIO
   tamanho de amostra (não a média entre os 5).
2. `run_b1_paired_variance_null` — nulo com a MESMA estrutura de
   promediação do Alpha (5 sorteios independentes por réplica, média dos 5
   Sharpes) — teste mais delicado: precisa mostrar que a variância desse
   nulo fica MUITO mais perto da variância de uma média de 5 amostras do
   que a variância de um nulo de sorteio único.

Também cobre `run_b1_random_entry` (pool total, item 3 do refinamento —
mesma função já existente, sem lógica nova) como regressão pós-refatoração
(extração de `_non_nofill_pool`/`_draw_sample_sharpe`) — dado sintético
pequeno, sem tocar `labels/v1/labels.parquet` real."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import orjson
import polars as pl
import pytest

from src.models import baselines

# rápido para pytest, estável o bastante para as asserções de variância abaixo
_N_SEEDS_TEST = 300  # noqa: magic-number
# seed arbitrária de teste, sem significado estatístico (int, não precisa constants.yaml)
_BASE_SEED_TEST = 7


def _synthetic_pool(
    n: int = 2000,
    *,
    seed: int = 0,
    n_nofill: int = 0,
    mean: float = 0.0,
    scale: float = 0.01,  # noqa: magic-number — desvio padrão sintético de teste
) -> pl.DataFrame:
    """Pool sintético de trades — `n` linhas NÃO-NOFILL (`barrier_hit ==
    "TP"`) mais `n_nofill` linhas NOFILL (pra exercitar o filtro do pool),
    `t0` espalhado em 1 barra/hora pra `span_seconds`/`sharpe_naive` terem
    uma janela de calendário não-degenerada."""
    rng = np.random.default_rng(seed)
    n_total = n + n_nofill
    t0 = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n_total)]
    barrier_hit = ["TP"] * n + ["NOFILL"] * n_nofill
    ret_net = rng.normal(loc=mean, scale=scale, size=n_total)
    return pl.DataFrame(
        {
            "t0": pl.Series(t0).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "barrier_hit": pl.Series(barrier_hit),
            "ret_net": pl.Series(ret_net),
        }
    )


# ============================================================================
# _non_nofill_pool / _draw_sample_sharpe — helpers extraídos, reusados por
# run_b1_random_entry E run_b1_paired_variance_null
# ============================================================================


def test_non_nofill_pool_filtra_nofill_e_preserva_contagem() -> None:
    df = _synthetic_pool(n=50, n_nofill=20)
    ret_arr, t0_col, n_pool = baselines._non_nofill_pool(df)
    assert n_pool == 50
    assert ret_arr.shape[0] == 50
    assert t0_col.len() == 50


def test_draw_sample_sharpe_e_deterministico_com_mesmo_seed() -> None:
    df = _synthetic_pool(n=500, seed=1)
    ret_arr, t0_col, n_pool = baselines._non_nofill_pool(df)
    s1 = baselines._draw_sample_sharpe(
        np.random.default_rng(_BASE_SEED_TEST), ret_arr, t0_col, n_pool, 100
    )
    s2 = baselines._draw_sample_sharpe(
        np.random.default_rng(_BASE_SEED_TEST), ret_arr, t0_col, n_pool, 100
    )
    assert s1 == s2


# ============================================================================
# run_b1_random_entry — regressão pós-refatoração (item 3 do refinamento
# reusa esta função tal como já existia, sem lógica nova)
# ============================================================================


def test_run_b1_random_entry_sample_size_e_clampado_ao_pool() -> None:
    df = _synthetic_pool(n=100)
    result = baselines.run_b1_random_entry(
        df, sample_size=10_000, alpha_sharpe=0.0, n_seeds=10, base_seed=_BASE_SEED_TEST
    )
    assert result.sample_size == 100


def test_run_b1_random_entry_alpha_muito_alto_da_percentil_100() -> None:
    df = _synthetic_pool(n=2000, mean=0.0, scale=0.01)
    result = baselines.run_b1_random_entry(
        df, sample_size=200, alpha_sharpe=1_000.0, n_seeds=_N_SEEDS_TEST, base_seed=_BASE_SEED_TEST
    )
    assert result.percentile == pytest.approx(100.0)


def test_run_b1_random_entry_alpha_muito_baixo_da_percentil_0() -> None:
    df = _synthetic_pool(n=2000, mean=0.0, scale=0.01)
    result = baselines.run_b1_random_entry(
        df, sample_size=200, alpha_sharpe=-1_000.0, n_seeds=_N_SEEDS_TEST, base_seed=_BASE_SEED_TEST
    )
    assert result.percentile == pytest.approx(0.0)


def test_run_b1_random_entry_e_deterministico_entre_chamadas() -> None:
    df = _synthetic_pool(n=800, seed=3)
    r1 = baselines.run_b1_random_entry(
        df, sample_size=100, alpha_sharpe=0.0, n_seeds=50, base_seed=_BASE_SEED_TEST
    )
    r2 = baselines.run_b1_random_entry(
        df, sample_size=100, alpha_sharpe=0.0, n_seeds=50, base_seed=_BASE_SEED_TEST
    )
    np.testing.assert_array_equal(r1.null_sharpes, r2.null_sharpes)


# ============================================================================
# run_b1_per_path — item 1 do refinamento
# ============================================================================


def test_run_b1_per_path_usa_tamanho_proprio_de_cada_caminho() -> None:
    df = _synthetic_pool(n=1000, mean=0.0, scale=0.01)
    path_sizes = {0: 120, 1: 300}
    path_sharpes = {0: 50.0, 1: -50.0}  # noqa: magic-number — Sharpe sintético extremo, só p/ checar direção

    out = baselines.run_b1_per_path(
        df,
        path_sample_sizes=path_sizes,
        path_alpha_sharpes=path_sharpes,
        n_seeds=_N_SEEDS_TEST,
        base_seed=_BASE_SEED_TEST,
    )

    assert set(out) == {0, 1}
    assert out[0].b1.sample_size == 120
    assert out[1].b1.sample_size == 300
    # Sharpe muito alto vs muito baixo -> percentis nos extremos opostos.
    assert out[0].b1.percentile == pytest.approx(100.0)
    assert out[1].b1.percentile == pytest.approx(0.0)


def test_run_b1_per_path_reusa_run_b1_random_entry_bit_a_bit() -> None:
    """`run_b1_per_path` não deve ter lógica estatística própria — cada
    entrada precisa reproduzir EXATAMENTE `run_b1_random_entry` chamado
    isoladamente com os mesmos argumentos (mesmo pool, mesmo RNG)."""
    df = _synthetic_pool(n=900, seed=5)
    path_sizes = {0: 90, 1: 200}
    path_sharpes = {0: -0.3, 1: 0.7}  # noqa: magic-number — Sharpe sintético arbitrário de teste

    out = baselines.run_b1_per_path(
        df,
        path_sample_sizes=path_sizes,
        path_alpha_sharpes=path_sharpes,
        n_seeds=40,
        base_seed=_BASE_SEED_TEST,
    )
    for path_id, size in path_sizes.items():
        direct = baselines.run_b1_random_entry(
            df,
            sample_size=size,
            alpha_sharpe=path_sharpes[path_id],
            n_seeds=40,
            base_seed=_BASE_SEED_TEST,
        )
        np.testing.assert_array_equal(out[path_id].b1.null_sharpes, direct.null_sharpes)
        assert out[path_id].b1.percentile == direct.percentile


def test_run_b1_per_path_chaves_incompativeis_levanta_value_error() -> None:
    df = _synthetic_pool(n=100)
    with pytest.raises(ValueError):
        baselines.run_b1_per_path(
            df,
            path_sample_sizes={0: 10, 1: 20},
            path_alpha_sharpes={0: 0.0},
            n_seeds=5,
            base_seed=_BASE_SEED_TEST,
        )


# ============================================================================
# run_b1_paired_variance_null — item 2 do refinamento (a parte
# matematicamente mais delicada)
# ============================================================================


def test_run_b1_paired_variance_null_shape_e_tamanhos_clampados() -> None:
    df = _synthetic_pool(n=100)
    result = baselines.run_b1_paired_variance_null(
        df,
        path_sample_sizes=[10, 20, 10_000],
        alpha_sharpe=0.0,
        n_seeds=25,
        base_seed=_BASE_SEED_TEST,
    )
    assert result.null_replicate_means.shape[0] == 25
    assert result.path_sample_sizes == (10, 20, 100)  # 10_000 clampado ao pool (100)


def test_run_b1_paired_variance_null_lista_vazia_levanta_value_error() -> None:
    df = _synthetic_pool(n=100)
    with pytest.raises(ValueError):
        baselines.run_b1_paired_variance_null(
            df, path_sample_sizes=[], alpha_sharpe=0.0, n_seeds=5, base_seed=_BASE_SEED_TEST
        )


def test_run_b1_paired_variance_null_alpha_extremo_da_percentis_0_e_100() -> None:
    df = _synthetic_pool(n=2000, mean=0.0, scale=0.01)
    sizes = [100, 100, 100, 100, 100]
    alto = baselines.run_b1_paired_variance_null(
        df,
        path_sample_sizes=sizes,
        alpha_sharpe=1_000.0,
        n_seeds=_N_SEEDS_TEST,
        base_seed=_BASE_SEED_TEST,
    )
    baixo = baselines.run_b1_paired_variance_null(
        df,
        path_sample_sizes=sizes,
        alpha_sharpe=-1_000.0,
        n_seeds=_N_SEEDS_TEST,
        base_seed=_BASE_SEED_TEST,
    )
    assert alto.percentile == pytest.approx(100.0)
    assert baixo.percentile == pytest.approx(0.0)


def test_run_b1_paired_variance_null_reduz_variancia_vs_sorteio_unico() -> None:
    """O ponto estatístico central da correção: a média de 5 sorteios tem
    variância MENOR que um sorteio único do mesmo tamanho (redução por
    promediação, ~1/5 pela CLT para sorteios aproximadamente independentes)
    — e essa variância reduzida precisa ficar MUITO mais perto de
    `var_single / 5` do que a variância do nulo de sorteio único
    (`var_single`) fica. Comparar `alpha_sharpe` (que É uma média de 5)
    contra o nulo de sorteio único, como o relatório original fazia, ignora
    exatamente essa diferença."""
    df = _synthetic_pool(n=3000, seed=11, mean=0.0, scale=0.02)
    size = 300
    n_seeds = 500

    single = baselines.run_b1_random_entry(
        df, sample_size=size, alpha_sharpe=0.0, n_seeds=n_seeds, base_seed=_BASE_SEED_TEST
    )
    paired = baselines.run_b1_paired_variance_null(
        df,
        path_sample_sizes=[size] * 5,
        alpha_sharpe=0.0,
        n_seeds=n_seeds,
        base_seed=_BASE_SEED_TEST,
    )

    var_single = float(np.var(single.null_sharpes[np.isfinite(single.null_sharpes)], ddof=1))
    var_paired = float(
        np.var(paired.null_replicate_means[np.isfinite(paired.null_replicate_means)], ddof=1)
    )
    var_mean_of_5_expected = var_single / 5.0

    # 1) redução clara de variância (nada perto de ser igual ao sorteio único)
    assert var_paired < var_single * 0.5

    # 2) o nulo pareado fica muito mais perto de var(média de 5) do que o
    #    nulo de sorteio único fica — a asserção central desta correção.
    dist_paired = abs(var_paired - var_mean_of_5_expected)
    dist_single = abs(var_single - var_mean_of_5_expected)
    assert dist_paired < dist_single

    # 3) sanity de magnitude — var_paired deve estar numa vizinhança larga
    #    (mas não frouxa o bastante pra deixar passar qualquer coisa) de
    #    var_single / 5, tolerando o ruído de 500 réplicas.
    assert var_mean_of_5_expected * 0.4 < var_paired < var_mean_of_5_expected * 2.5


# ============================================================================
# write_b1_refinement_report_atomic — B29
# ============================================================================


def test_write_b1_refinement_report_atomic_escreve_e_nao_deixa_tmp(tmp_path: Path) -> None:
    dest = tmp_path / "sub" / "alpha_b1_refinement_report.json"
    payload = {"schema_version": 1, "hello": "world"}
    out_path = baselines.write_b1_refinement_report_atomic(payload, dest_path=dest)
    assert out_path == dest
    assert dest.exists()
    assert not dest.with_name(dest.name + ".tmp").exists()
    assert orjson.loads(dest.read_bytes()) == payload
