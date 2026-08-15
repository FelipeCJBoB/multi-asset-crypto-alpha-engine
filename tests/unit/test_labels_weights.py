"""Testes de `src/labels/weights.py` — concorrência/unicidade (AFML cap. 4)
e `sample_weight` normalizado (§3.5). `compute_concurrency_and_uniqueness`
é verificado contra um exemplo pequeno calculado à mão (3 labels
sobrepostos); `apply_weights` é verificado sobre um `pl.DataFrame`
sintético com o schema pré-pesos real de `triple_barrier`."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.labels import weights

# ============================================================================
# compute_concurrency_and_uniqueness — exemplo calculado à mão
# ============================================================================


def test_concorrencia_e_unicidade_exemplo_a_mao() -> None:
    """3 labels no índice [0, 1, 2] (posições == os próprios `t0`, um label
    por posição): label0 cobre [0,2], label1 cobre [1,2], label2 cobre
    [2,2]. Concorrência por posição: pos0=1 (só label0), pos1=2 (label0 +
    label1), pos2=3 (os três). Unicidade = média de 1/concorrência sobre as
    posições que cada label ocupa — valores conferidos à mão na docstring
    do teste."""
    t0 = np.array([0, 1, 2], dtype=np.int64)
    t1 = np.array([2, 3, 2], dtype=np.int64)

    concurrency, uniqueness = weights.compute_concurrency_and_uniqueness(t0, t1)

    np.testing.assert_array_equal(concurrency, np.array([1, 2, 3]))
    expected_uniqueness = np.array(
        [
            (1 / 1 + 1 / 2 + 1 / 3) / 3,  # label0: posições 0,1,2
            (1 / 2 + 1 / 3) / 2,  # label1: posições 1,2
            (1 / 3) / 1,  # label2: posição 2
        ]
    )
    np.testing.assert_allclose(uniqueness, expected_uniqueness, rtol=1e-12)


def test_concorrencia_sem_sobreposicao_unicidade_um() -> None:
    """Labels que não se sobrepõem (`t1_i < t0_{i+1}`) têm concorrência 1 e
    unicidade 1 em toda parte — o caso trivial do AFML cap. 4."""
    t0 = np.array([0, 10, 20], dtype=np.int64)
    t1 = np.array([5, 15, 25], dtype=np.int64)

    concurrency, uniqueness = weights.compute_concurrency_and_uniqueness(t0, t1)

    np.testing.assert_array_equal(concurrency, np.array([1, 1, 1]))
    np.testing.assert_allclose(uniqueness, np.array([1.0, 1.0, 1.0]))


def test_concorrencia_uma_linha() -> None:
    """Caso degenerado n=1: `span = idx1 - idx0 + 1 = 1`, `concurrency = 1`
    -- exercita o caminho onde `idx0 == idx1` exatamente (o limite inferior
    das provas de segurança dos dois `# noqa: unguarded-ratio` em
    `compute_concurrency_and_uniqueness`, achado de auditoria
    audit_engineering 2026-08-15)."""
    t0 = np.array([0], dtype=np.int64)
    t1 = np.array([5], dtype=np.int64)

    concurrency, uniqueness = weights.compute_concurrency_and_uniqueness(t0, t1)

    np.testing.assert_array_equal(concurrency, np.array([1]))
    np.testing.assert_allclose(uniqueness, np.array([1.0]))


def test_concorrencia_array_vazio_nao_quebra() -> None:
    concurrency, uniqueness = weights.compute_concurrency_and_uniqueness(
        np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    )
    assert concurrency.shape == (0,)
    assert uniqueness.shape == (0,)


def test_concorrencia_t0_desordenado_levanta_erro() -> None:
    """Achado de auditoria (2026-08-15): a precondição 't0 ordenado' era só
    documentada, nunca validada -- um t0 desordenado faria `np.searchsorted`
    devolver `idx1` sem sentido silenciosamente (uniqueness plausível mas
    errado), não um erro óbvio. Esta função é a fronteira real usada por
    `apply_weights` (sample_weight de produção) -- fail-fast é a defesa
    certa aqui, não só no chamador de M2."""
    t0 = np.array([0, 2, 1], dtype=np.int64)  # posições 1 e 2 fora de ordem
    t1 = np.array([5, 5, 5], dtype=np.int64)

    with pytest.raises(ValueError, match="ordenado"):
        weights.compute_concurrency_and_uniqueness(t0, t1)


def test_uniqueness_sempre_em_0_1() -> None:
    """Propriedade estrutural (não um exemplo específico): concorrência
    nunca é 0 no próprio índice do label (ele cobre pelo menos a si mesmo),
    então 1/concorrência está sempre em (0, 1] e a média também."""
    rng = np.random.default_rng(42)
    n = 200
    t0 = np.arange(n, dtype=np.int64)
    span = rng.integers(1, 20, size=n)
    t1 = (t0 + span).astype(np.int64)

    _, uniqueness = weights.compute_concurrency_and_uniqueness(t0, t1)
    assert bool(((uniqueness > 0.0) & (uniqueness <= 1.0)).all())


# ============================================================================
# apply_weights — sobre DataFrame sintético (schema pré-pesos real)
# ============================================================================


def _synthetic_pre_weight_frame() -> pl.DataFrame:
    base_ms = 1_700_000_000_000
    bar_ms = 900_000
    n = 6
    t0_ms = [base_ms + i * bar_ms for i in range(n)]
    t1_ms = [t + 3 * bar_ms for t in t0_ms]  # cada label cobre 3 barras -> sobreposição real
    side = [1, 1, 1, -1, -1, -1]
    ret_net = [0.01, -0.02, 0.015, 0.008, -0.01, 0.02]

    t0_dt = pl.Series(t0_ms, dtype=pl.Int64).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    t1_dt = pl.Series(t1_ms, dtype=pl.Int64).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    return pl.DataFrame(
        {
            "t0": t0_dt,
            "t1": t1_dt,
            "side": pl.Series(side, dtype=pl.Int8),
            "ret_net": pl.Series(ret_net, dtype=pl.Float64),
        }
    )


def test_apply_weights_media_um() -> None:
    out = weights.apply_weights(_synthetic_pre_weight_frame())
    assert "concurrency" in out.columns
    assert "uniqueness" in out.columns
    assert "sample_weight" in out.columns
    # `.to_numpy()` antes do `float()` -- mesmo padrão de
    # `assert_label_invariants` (triple_barrier.py): o retorno agregado de
    # `pl.Series.mean()` é uma união ampla nos stubs de tipo do polars,
    # mypy strict reclama de `float(...)` direto sobre ela. Achado
    # pré-existente (audit_engineering, 2026-08-15), corrigido no caminho.
    mean_w = float(out["sample_weight"].to_numpy().mean())
    assert abs(mean_w - 1.0) < 1e-9


def test_apply_weights_concorrencia_calculada_por_lado() -> None:
    """Concorrência é computada dentro de cada `side` separadamente — um
    label `side=1` não conta como sobreposição de um label `side=-1` no
    mesmo `t0`, mesmo que os dois compartilhem o mesmo intervalo de tempo
    (ver docstring do módulo, item 7)."""
    out = weights.apply_weights(_synthetic_pre_weight_frame())
    long_side = out.filter(pl.col("side") == 1).sort("t0")
    short_side = out.filter(pl.col("side") == -1).sort("t0")
    # cada lado tem 3 labels cobrindo 3 barras cada, dentro do próprio lado
    # -- concorrência máxima dentro de cada lado é 3, nunca 6 (o total
    # combinado), confirmando que os lados não se misturam no cálculo.
    # `.to_numpy()` antes do `int()` -- mesmo motivo do comentário acima.
    assert int(long_side["concurrency"].to_numpy().max()) <= 3
    assert int(short_side["concurrency"].to_numpy().max()) <= 3


def test_apply_weights_dataset_vazio() -> None:
    empty = pl.DataFrame(
        schema={
            "t0": pl.Datetime("ms", "UTC"),
            "t1": pl.Datetime("ms", "UTC"),
            "side": pl.Int8,
            "ret_net": pl.Float64,
        }
    )
    out = weights.apply_weights(empty)
    assert out.height == 0
    assert "sample_weight" in out.columns


def test_apply_weights_todo_ret_net_zero_levanta_erro() -> None:
    """Dataset degenerado (`sample_weight` não pode ser normalizado para
    média 1 sem dividir por zero) levanta erro alto, não produz NaN/inf
    silencioso."""
    df = _synthetic_pre_weight_frame().with_columns(pl.lit(0.0).alias("ret_net"))
    with pytest.raises(ValueError):
        weights.apply_weights(df)


def test_apply_weights_uma_linha_ret_net_nan_levanta_erro() -> None:
    """Achado de auditoria (audit_engineering, 2026-08-15): `np.nanmean`
    (implementação anterior) ignora NaN silenciosamente quando só ALGUMAS
    linhas são não-finitas -- a média das OUTRAS 5 linhas continua um número
    normal (não dispara o guard de `mean_w`), e o `sample_weight` da linha
    contaminada vira NaN sem nenhum erro. Este teste tem 6 linhas com
    `ret_net` finito em 5 delas -- se a implementação voltasse a usar
    `nanmean`, ele passaria silenciosamente (regressão real, não
    hipotética); a implementação corrigida precisa levantar `ValueError`
    mesmo com só 1/6 linhas contaminadas."""
    df = _synthetic_pre_weight_frame()
    ret_net = df["ret_net"].to_list()
    ret_net[0] = float("nan")
    df = df.with_columns(pl.Series("ret_net", ret_net, dtype=pl.Float64))

    with pytest.raises(ValueError, match="não-finita"):
        weights.apply_weights(df)
