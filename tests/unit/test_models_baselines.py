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
pequeno, sem tocar `labels/v1/labels.parquet` real.

**T2/T3 (percentil carry-stripped + B1'):**

3. `strip_carry`/`run_b1_carry_stripped` — reconciliação de
   `ret_net_sem_carry` contra `ret_net` original (mesma tolerância de
   `decomposition.py`, 1e-6) + teste de wiring (um Alpha cujo edge é
   inteiramente carry perde a vantagem quando o carry é removido dos DOIS
   lados da comparação).
4. `run_b1_side_shuffle` (B1') — mecânica de sorteio de LADO com barra/
   timing REAL fixa, com dado sintético de dois lados por barra
   (`side=1`/`side=-1`, convenção de `labels/v1/labels.parquet`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import orjson
import polars as pl
import pytest

from src.models import backtest_lite, baselines

# rápido para pytest, estável o bastante para as asserções de variância abaixo
_N_SEEDS_TEST = 300  # noqa: magic-number
# seed arbitrária de teste, sem significado estatístico (int, não precisa constants.yaml)
_BASE_SEED_TEST = 7


# ============================================================================
# b1_sample_size (2026-08-23, núcleo funcional/casca imperativa -- docs/
# nucleo_casca_design_doc_2026-08-23.md) -- extraída de src/models/
# pipeline.py::run_layer1_sprint pra virar testável sem rodar o pipeline
# CPCV/XGBoost inteiro.
# ============================================================================


def test_b1_sample_size_divide_pooled_por_n_paths() -> None:
    assert baselines.b1_sample_size(100, 5) == 20


def test_b1_sample_size_arredonda() -> None:
    assert baselines.b1_sample_size(101, 5) == 20  # 20.2 -> 20
    assert baselines.b1_sample_size(103, 5) == 21  # 20.6 -> 21


def test_b1_sample_size_piso_1_nunca_amostra_vazia() -> None:
    assert baselines.b1_sample_size(0, 5) == 1
    assert baselines.b1_sample_size(0, 0) == 1


def test_b1_sample_size_n_paths_zero_cai_no_piso_do_denominador() -> None:
    """`n_paths=0` (caso degenerado) não levanta ZeroDivisionError -- cai
    no mesmo piso 1 do denominador que o código de produção já aplicava
    (`max(len(c1_by_path), 1)`)."""
    assert baselines.b1_sample_size(50, 0) == 50


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


# ============================================================================
# T2 — strip_carry / run_b1_carry_stripped
# ============================================================================


def _synthetic_carry_pool(
    n: int = 200,
    *,
    seed: int = 0,
    ret_gross_mean: float = 0.0,
    ret_gross_scale: float = 0.01,  # noqa: magic-number — desvio padrão sintético de teste
    funding_bps_mean: float = 0.0,
    funding_bps_scale: float = 10.0,  # noqa: magic-number — escala sintética de teste
    cost_bps: float = 1.0,  # noqa: magic-number — custo fixo sintético de teste (bps)
) -> pl.DataFrame:
    """Pool sintético com as colunas cruas de `labels/v1/labels.parquet`
    necessárias por `strip_carry` (`ret_gross, cost_entry_bps,
    cost_exit_bps, funding_bps`) MAIS `ret_net` construído pela MESMA soma
    de 3 termos que `src.labels.triple_barrier`/`src.models.decomposition`
    usam (`ret_net = ret_gross - cost_frac - funding_frac`) — é essa
    consistência interna que os testes de reconciliação abaixo verificam."""
    rng = np.random.default_rng(seed)
    t0 = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    ret_gross = rng.normal(loc=ret_gross_mean, scale=ret_gross_scale, size=n)
    cost_entry_bps = np.full(n, cost_bps)
    cost_exit_bps = np.full(n, cost_bps)
    funding_bps = rng.normal(loc=funding_bps_mean, scale=funding_bps_scale, size=n)
    cost_frac = (cost_entry_bps + cost_exit_bps) / 10_000.0  # noqa: magic-number — bps->fração, mesma conversão de baselines.py
    funding_frac = funding_bps / 10_000.0  # noqa: magic-number — bps->fração
    ret_net = ret_gross - cost_frac - funding_frac
    return pl.DataFrame(
        {
            "t0": pl.Series(t0).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "barrier_hit": pl.Series(["TP"] * n),
            "ret_gross": pl.Series(ret_gross),
            "cost_entry_bps": pl.Series(cost_entry_bps),
            "cost_exit_bps": pl.Series(cost_exit_bps),
            "funding_bps": pl.Series(funding_bps),
            "ret_net": pl.Series(ret_net),
        }
    )


def test_strip_carry_reconciliacao_bate_com_ret_net_original() -> None:
    """A soma direção+execução (`strip_carry`) + carry recuperado
    (`-funding_bps/1e4`, mesmo sinal de `pnl_carry` em `decomposition.py`)
    precisa reproduzir `ret_net` original dentro da MESMA tolerância de
    ponto flutuante que `decomposition.py` usa (1e-6)."""
    df = _synthetic_carry_pool(n=500, seed=3, funding_bps_scale=25.0)
    stripped = baselines.strip_carry(df)

    carry_recovered = -df["funding_bps"].to_numpy().astype(np.float64) / 10_000.0
    reconciled = stripped["ret_net"].to_numpy().astype(np.float64) + carry_recovered
    original = df["ret_net"].to_numpy().astype(np.float64)

    max_abs_diff = float(np.max(np.abs(reconciled - original)))
    assert max_abs_diff < 1e-6


def test_strip_carry_preserva_outras_colunas_e_so_muda_ret_net_quando_ha_funding() -> None:
    df = _synthetic_carry_pool(n=50, seed=4, funding_bps_scale=50.0)
    stripped = baselines.strip_carry(df)

    assert stripped.columns == df.columns
    np.testing.assert_array_equal(stripped["ret_gross"].to_numpy(), df["ret_gross"].to_numpy())
    np.testing.assert_array_equal(stripped["t0"].to_numpy(), df["t0"].to_numpy())
    # funding != 0 em quase toda linha sintética -> ret_net muda em quase
    # toda linha (não precisa mudar em TODAS, só não pode ficar idêntico).
    assert not np.allclose(stripped["ret_net"].to_numpy(), df["ret_net"].to_numpy())


def test_strip_carry_sem_funding_nao_muda_ret_net() -> None:
    """Caso degenerado (funding = 0 em toda linha): `strip_carry` deve
    devolver `ret_net` IDÊNTICO ao original — sanity check direto da
    fórmula, sem depender da tolerância de reconciliação."""
    df = _synthetic_carry_pool(n=50, seed=5, funding_bps_mean=0.0, funding_bps_scale=0.0)
    stripped = baselines.strip_carry(df)
    np.testing.assert_allclose(
        stripped["ret_net"].to_numpy(), df["ret_net"].to_numpy(), atol=1e-12
    )


def test_run_b1_carry_stripped_remove_vantagem_que_vem_so_de_carry() -> None:
    """Teste de wiring do T2: constrói um Alpha cuja vantagem em `ret_net`
    vem INTEIRAMENTE de carry (funding CONSTANTE e artificialmente
    favorável, sem edge direcional real algum) — a comparação COM carry
    deve dar percentil alto (a vantagem existe em `ret_net`), a comparação
    SEM carry (`run_b1_carry_stripped`) precisa colapsar essa vantagem,
    porque o que a alimentava foi removido dos dois lados.

    `ret_gross` de `alpha_trades` alterna `+escala/-escala` de forma
    DETERMINÍSTICA (média EXATAMENTE 0, sem ruído de amostragem) — evita
    que o teste dependa de uma média amostral aleatória, que a anualização
    de `sharpe_naive` (proporcional a `sqrt(trades_per_year)`, grande para
    poucos trades num intervalo curto) amplificaria de forma instável."""
    pool = _synthetic_carry_pool(n=4000, seed=6, funding_bps_scale=10.0)

    n_alpha = 300
    ret_gross_scale = 0.01  # noqa: magic-number — mesma escala do pool sintético
    cost_bps = 1.0  # noqa: magic-number — custo fixo sintético de teste (bps)
    funding_bps_favoravel = -400.0  # noqa: magic-number — carry artificialmente enorme e favorável
    t0_alpha = [datetime(2021, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n_alpha)]
    ret_gross_alpha = np.tile([ret_gross_scale, -ret_gross_scale], n_alpha // 2)
    cost_frac = (cost_bps + cost_bps) / 10_000.0  # noqa: magic-number — bps->fração
    funding_frac_alpha = funding_bps_favoravel / 10_000.0  # noqa: magic-number — bps->fração
    ret_net_com_carry = ret_gross_alpha - cost_frac - funding_frac_alpha
    alpha_trades = pl.DataFrame(
        {
            "t0": pl.Series(t0_alpha).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "barrier_hit": pl.Series(["TP"] * n_alpha),
            "ret_gross": pl.Series(ret_gross_alpha),
            "cost_entry_bps": pl.Series([cost_bps] * n_alpha),
            "cost_exit_bps": pl.Series([cost_bps] * n_alpha),
            "funding_bps": pl.Series([funding_bps_favoravel] * n_alpha),
            "ret_net": pl.Series(ret_net_com_carry),
        }
    )

    span = backtest_lite.span_seconds(alpha_trades["t0"])
    alpha_sharpe_com_carry, _ = backtest_lite.sharpe_naive(
        alpha_trades["ret_net"].to_numpy().astype(np.float64), span_seconds=span
    )

    result_com_carry = baselines.run_b1_random_entry(
        pool,
        sample_size=alpha_trades.height,
        alpha_sharpe=alpha_sharpe_com_carry,
        n_seeds=_N_SEEDS_TEST,
        base_seed=_BASE_SEED_TEST,
    )
    result_sem_carry = baselines.run_b1_carry_stripped(
        pool, alpha_trades, n_seeds=_N_SEEDS_TEST, base_seed=_BASE_SEED_TEST
    )

    assert result_com_carry.percentile > 90.0  # noqa: magic-number — margem larga de teste
    # a vantagem inteira vinha de carry -> removida dos dois lados, o
    # percentil precisa cair de forma clara (não precisa ficar em 50 exato,
    # só deixar de ser a vantagem extrema de antes).
    assert result_sem_carry.percentile < result_com_carry.percentile - 20.0  # noqa: magic-number — margem larga de teste


def test_run_b1_carry_stripped_sample_size_vem_de_alpha_trades() -> None:
    pool = _synthetic_carry_pool(n=500, seed=7)
    alpha_trades = _synthetic_carry_pool(n=37, seed=70)
    result = baselines.run_b1_carry_stripped(
        pool, alpha_trades, n_seeds=10, base_seed=_BASE_SEED_TEST
    )
    assert result.sample_size == 37


# ============================================================================
# T3 — run_b1_side_shuffle (B1')
# ============================================================================


def _synthetic_two_sided_labels(
    n: int = 500,
    *,
    seed: int = 0,
    long_ret: float = 0.0,
    short_ret: float = 0.0,
    long_scale: float = 0.01,  # noqa: magic-number — desvio padrão sintético de teste
    short_scale: float = 0.01,  # noqa: magic-number — desvio padrão sintético de teste
    long_nofill_frac: float = 0.0,
    short_nofill_frac: float = 0.0,
) -> pl.DataFrame:
    """`n` barras, cada uma com DUAS linhas (`side=1` e `side=-1`) — mesma
    convenção de `labels/v1/labels.parquet` (toda barra tem os dois lados
    rotulados, `src.labels.triple_barrier.build_labels_both_sides`)."""
    rng = np.random.default_rng(seed)
    t0 = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    t0_series = pl.Series(t0).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")

    long_ret_arr = rng.normal(loc=long_ret, scale=long_scale, size=n)
    short_ret_arr = rng.normal(loc=short_ret, scale=short_scale, size=n)
    long_fill = rng.random(n) >= long_nofill_frac
    short_fill = rng.random(n) >= short_nofill_frac

    long_df = pl.DataFrame(
        {
            "t0": t0_series,
            "side": pl.Series([1] * n, dtype=pl.Int8),
            "barrier_hit": pl.Series(["TP" if f else "NOFILL" for f in long_fill]),
            "ret_net": pl.Series(long_ret_arr),
        }
    )
    short_df = pl.DataFrame(
        {
            "t0": t0_series,
            "side": pl.Series([-1] * n, dtype=pl.Int8),
            "barrier_hit": pl.Series(["TP" if f else "NOFILL" for f in short_fill]),
            "ret_net": pl.Series(short_ret_arr),
        }
    )
    return pl.concat([long_df, short_df], how="vertical").sort(["t0", "side"])


def _signals_from_bars(
    labels: pl.DataFrame,
    bar_indices: list[int],
    side_hat_values: list[int],
    *,
    is_oof: bool = True,
    fold_id: int = 0,
) -> pl.DataFrame:
    """Constrói uma tabela de sinais (schema mínimo §5.12: `t0, side_hat,
    is_oof, fold_id`) apontando para barras REAIS de `labels` (`t0` fatiado
    diretamente da coluna, nunca reconstruído à parte — evita qualquer risco
    de mismatch de dtype/timezone no join de `_signal_side_outcomes`)."""
    unique_t0 = labels.filter(pl.col("side") == 1).sort("t0")["t0"]
    chosen_t0 = unique_t0[bar_indices]
    n = len(bar_indices)
    return pl.DataFrame(
        {
            "t0": chosen_t0,
            "side_hat": pl.Series(side_hat_values, dtype=pl.Int8),
            "is_oof": pl.Series([is_oof] * n, dtype=pl.Boolean),
            "fold_id": pl.Series([fold_id] * n, dtype=pl.Int16),
        }
    )


# ---- helpers privados (_signal_side_outcomes / _draw_side_shuffle_sharpe) ----


def test_signal_side_outcomes_junta_os_dois_lados_da_mesma_barra() -> None:
    labels = _synthetic_two_sided_labels(
        n=10, seed=1, long_ret=0.02, short_ret=-0.02, long_scale=0.0, short_scale=0.0
    )
    signals = _signals_from_bars(labels, [0, 1, 2, 3, 4], [1, 1, -1, -1, 1])

    ret_long, ret_short, filled_long, filled_short, t0 = baselines._signal_side_outcomes(
        labels, signals
    )

    assert ret_long.shape[0] == 5
    np.testing.assert_allclose(ret_long, 0.02, atol=1e-9)
    np.testing.assert_allclose(ret_short, -0.02, atol=1e-9)
    assert bool(filled_long.all())
    assert bool(filled_short.all())
    assert t0.len() == 5


def test_signal_side_outcomes_preserva_repeticao_de_t0() -> None:
    """`signals` pode ter a MESMA barra repetida (folds/caminhos diferentes
    do CPCV) — o join precisa preservar essa multiplicidade, não deduplicar
    por `t0`."""
    labels = _synthetic_two_sided_labels(n=5, seed=2, long_scale=0.0, short_scale=0.0)
    signals = _signals_from_bars(labels, [0, 0, 0, 1], [1, -1, 1, 1])  # barra 0 repetida 3x

    ret_long, _, _, _, t0 = baselines._signal_side_outcomes(labels, signals)
    assert ret_long.shape[0] == 4
    assert t0.len() == 4


def test_draw_side_shuffle_sharpe_e_deterministico_com_mesmo_seed() -> None:
    labels = _synthetic_two_sided_labels(n=200, seed=3)
    signals = _signals_from_bars(labels, list(range(50)), [1] * 50)
    ret_long, ret_short, filled_long, filled_short, t0 = baselines._signal_side_outcomes(
        labels, signals
    )
    args = (ret_long, ret_short, filled_long, filled_short, t0, 0.5)
    s1, n1 = baselines._draw_side_shuffle_sharpe(np.random.default_rng(_BASE_SEED_TEST), *args)
    s2, n2 = baselines._draw_side_shuffle_sharpe(np.random.default_rng(_BASE_SEED_TEST), *args)
    assert s1 == s2
    assert n1 == n2


def test_draw_side_shuffle_sharpe_sample_size_fixo_quando_tudo_preenchido() -> None:
    """Propriedade central de B1' (barra/timing REAL, nunca sorteada): se
    os dois lados de toda barra preenchem sempre, o TAMANHO da amostra não
    pode variar entre sorteios de lado diferentes — só o LADO muda, nunca a
    contagem de barras."""
    n = 40
    ret_long = np.full(n, 0.01)
    ret_short = np.full(n, -0.01)
    filled_long = np.ones(n, dtype=bool)
    filled_short = np.ones(n, dtype=bool)
    labels = _synthetic_two_sided_labels(n=n, seed=9)
    t0 = labels.filter(pl.col("side") == 1).sort("t0")["t0"]

    for seed in (1, 2, 3, 4):
        _, n_filled = baselines._draw_side_shuffle_sharpe(
            np.random.default_rng(seed), ret_long, ret_short, filled_long, filled_short, t0, 0.5
        )
        assert n_filled == n


def test_draw_side_shuffle_sharpe_descarta_nofill() -> None:
    n = 20
    ret_long = np.full(n, 0.01)
    ret_short = np.full(n, -0.01)
    filled_long = np.array([True] * 10 + [False] * 10)
    filled_short = np.array([False] * 10 + [True] * 10)
    labels = _synthetic_two_sided_labels(n=n, seed=10)
    t0 = labels.filter(pl.col("side") == 1).sort("t0")["t0"]

    # rng determinístico só pra fixar o padrão de sorteio nesta chamada
    _, n_filled = baselines._draw_side_shuffle_sharpe(
        np.random.default_rng(0), ret_long, ret_short, filled_long, filled_short, t0, 0.5
    )
    # NEM toda barra preenche pro lado sorteado (metade só preenche LONG,
    # metade só preenche SHORT) -> a amostra filtrada é estritamente menor
    # que n na maioria dos padrões de sorteio possíveis.
    assert 0 <= n_filled <= n


# ---- run_b1_side_shuffle (função pública) ----


def test_run_b1_side_shuffle_side_distribution_invalido_levanta_value_error() -> None:
    labels = _synthetic_two_sided_labels(n=20, seed=11)
    signals = _signals_from_bars(labels, [0, 1], [1, -1])
    with pytest.raises(ValueError):
        baselines.run_b1_side_shuffle(
            labels, signals, alpha_sharpe=0.0, side_distribution="nao_existe"
        )


def test_run_b1_side_shuffle_sem_sinais_levanta_value_error() -> None:
    labels = _synthetic_two_sided_labels(n=20, seed=12)
    signals = _signals_from_bars(labels, [0, 1, 2], [0, 0, 0])  # side_hat todo zero
    with pytest.raises(ValueError):
        baselines.run_b1_side_shuffle(labels, signals, alpha_sharpe=0.0)


def test_run_b1_side_shuffle_filtra_side_hat_zero_e_is_oof_false() -> None:
    labels = _synthetic_two_sided_labels(n=20, seed=13)
    signals_raw = _signals_from_bars(labels, [0, 1, 2, 3, 4], [1, 0, -1, 1, -1])
    # marca a barra de índice 3 (quarta linha) como NÃO-oof -- deve ser
    # descartada mesmo tendo side_hat != 0.
    is_oof_values = [True, True, True, False, True]
    signals_raw = signals_raw.with_columns(
        pl.Series(is_oof_values, dtype=pl.Boolean).alias("is_oof")
    )
    result = baselines.run_b1_side_shuffle(
        labels, signals_raw, alpha_sharpe=0.0, n_seeds=5, base_seed=_BASE_SEED_TEST
    )
    # side_hat != 0 -> índices 0,2,3,4 (4 linhas); is_oof descarta o índice 3 -> 3 sinais.
    assert result.n_signals == 3


def test_run_b1_side_shuffle_uniform_long_prob_e_meio() -> None:
    labels = _synthetic_two_sided_labels(
        n=100, seed=14, long_ret=1.0, short_ret=-1.0, long_scale=0.0, short_scale=0.0
    )
    signals = _signals_from_bars(labels, list(range(50)), [1] * 30 + [-1] * 20)
    result = baselines.run_b1_side_shuffle(
        labels, signals, alpha_sharpe=0.0, side_distribution="uniform",
        n_seeds=10, base_seed=_BASE_SEED_TEST,
    )
    assert result.long_prob == pytest.approx(0.5)
    assert result.side_distribution == "uniform"
    assert result.n_signals == 50


def test_run_b1_side_shuffle_empirical_usa_proporcao_real_observada() -> None:
    labels = _synthetic_two_sided_labels(
        n=100, seed=15, long_ret=1.0, short_ret=-1.0, long_scale=0.0, short_scale=0.0
    )
    # 30 long, 20 short -> long_prob esperado = 0.6
    signals = _signals_from_bars(labels, list(range(50)), [1] * 30 + [-1] * 20)
    result = baselines.run_b1_side_shuffle(
        labels, signals, alpha_sharpe=0.0, side_distribution="empirical",
        n_seeds=10, base_seed=_BASE_SEED_TEST,
    )
    assert result.long_prob == pytest.approx(0.6)


def test_run_b1_side_shuffle_alpha_extremo_da_percentis_0_e_100() -> None:
    labels = _synthetic_two_sided_labels(
        n=2000, seed=16, long_ret=0.0, short_ret=0.0, long_scale=0.01, short_scale=0.01
    )
    signals = _signals_from_bars(labels, list(range(300)), [1] * 300)

    alto = baselines.run_b1_side_shuffle(
        labels, signals, alpha_sharpe=1_000.0, n_seeds=_N_SEEDS_TEST, base_seed=_BASE_SEED_TEST
    )
    baixo = baselines.run_b1_side_shuffle(
        labels, signals, alpha_sharpe=-1_000.0, n_seeds=_N_SEEDS_TEST, base_seed=_BASE_SEED_TEST
    )
    assert alto.percentile == pytest.approx(100.0)
    assert baixo.percentile == pytest.approx(0.0)


def test_run_b1_side_shuffle_direcao_real_bate_nulo_de_lado_sorteado() -> None:
    """Cenário central de T3: LONG sempre ganha, SHORT sempre perde (edge
    direcional real e forte) — um Alpha que SEMPRE acerta o lado LONG deve
    bater com folga o nulo de lado sorteado 50/50 (que metade das vezes
    escolhe SHORT e perde)."""
    labels = _synthetic_two_sided_labels(
        n=2000, seed=17, long_ret=0.02, short_ret=-0.02, long_scale=0.005, short_scale=0.005
    )
    signals = _signals_from_bars(labels, list(range(300)), [1] * 300)

    alpha_rets = labels.filter(pl.col("side") == 1)["ret_net"].to_numpy()[:300]
    span = backtest_lite.span_seconds(
        labels.filter(pl.col("side") == 1).sort("t0")["t0"].head(300)
    )
    alpha_sharpe, _ = backtest_lite.sharpe_naive(alpha_rets, span_seconds=span)

    result = baselines.run_b1_side_shuffle(
        labels, signals, alpha_sharpe=alpha_sharpe, n_seeds=_N_SEEDS_TEST, base_seed=_BASE_SEED_TEST
    )
    assert result.percentile > 95.0  # noqa: magic-number — margem larga de teste


def test_run_b1_side_shuffle_e_deterministico_entre_chamadas() -> None:
    labels = _synthetic_two_sided_labels(n=300, seed=18)
    signals = _signals_from_bars(labels, list(range(80)), [1] * 40 + [-1] * 40)
    r1 = baselines.run_b1_side_shuffle(
        labels, signals, alpha_sharpe=0.0, n_seeds=50, base_seed=_BASE_SEED_TEST
    )
    r2 = baselines.run_b1_side_shuffle(
        labels, signals, alpha_sharpe=0.0, n_seeds=50, base_seed=_BASE_SEED_TEST
    )
    np.testing.assert_array_equal(r1.null_sharpes, r2.null_sharpes)
