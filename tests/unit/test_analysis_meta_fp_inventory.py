"""Testes de `src/analysis/meta_fp_inventory.py` — P0 do Gate E0 (§2.6):
esquema de permutação circular-shift-por-bloco + validação obrigatória do
nulo. Tudo sintético/determinístico (sem dependência de dado real em
disco) — a medição contra dado real fica num script separado."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.analysis import meta_fp_inventory as fpi

_BAR_MS = 900_000  # 15m


def _t0_series(n: int, *, start_ms: int = 0, bar_ms: int = _BAR_MS) -> np.ndarray:
    return (np.arange(n, dtype=np.int64) * bar_ms) + start_ms


# ============================================================================
# classify_fp_binary — as 4 classes do §2.6
# ============================================================================


def test_classify_fp_binary_mapeia_as_4_classes() -> None:
    labels = pl.DataFrame(
        {
            "barrier_hit": ["SL", "TP", "TIME", "TIME", "NOFILL"],
            "ret_net": [-0.01, 0.02, 0.005, -0.003, 0.0],
        }
    )
    out = fpi.classify_fp_binary(labels)
    assert out["y_fp"].to_list() == [1, 0, 0, 1, None]


def test_classify_fp_binary_time_com_ret_net_exatamente_zero_e_fp() -> None:
    """§2.6 literal: `TIME -> 1[ret_net > 0]` (estrito) — ret_net==0.0 cai
    no complemento (y_fp=1), não é um caso ambíguo."""
    labels = pl.DataFrame({"barrier_hit": ["TIME"], "ret_net": [0.0]})
    assert fpi.classify_fp_binary(labels)["y_fp"].to_list() == [1]


# ============================================================================
# circular_shift_by_time — propriedades da rotação
# ============================================================================


def test_circular_shift_shift_zero_e_identidade() -> None:
    t0_ms = _t0_series(50)
    values = np.arange(50, dtype=np.int64)
    shifted = fpi.circular_shift_by_time(t0_ms, values, shift_ms=0)
    np.testing.assert_array_equal(shifted, values)


def test_circular_shift_preserva_o_multiset_de_valores() -> None:
    """Rotação nunca inventa nem descarta valor — só reposiciona."""
    rng = np.random.default_rng(0)
    t0_ms = _t0_series(200)
    values = rng.integers(0, 4, size=200).astype(np.int64)
    shifted = fpi.circular_shift_by_time(t0_ms, values, shift_ms=37 * _BAR_MS)
    assert sorted(shifted.tolist()) == sorted(values.tolist())


def test_circular_shift_e_de_fato_circular_no_wraparound() -> None:
    """Deslocar por uma barra inteira equivale a rotacionar o array por 1
    posição (wraparound: a primeira linha original vira a última) --
    `shift_ms` desloca τ = t0 + shift PRA FRENTE, então a linha `i` passa
    a ler o valor que originalmente estava em `i+1` (circular)."""
    n = 20
    t0_ms = _t0_series(n)
    values = np.arange(n, dtype=np.int64)
    shifted = fpi.circular_shift_by_time(t0_ms, values, shift_ms=_BAR_MS)
    esperado = np.roll(values, -1)  # posição i recebe o valor de i+1, circular
    np.testing.assert_array_equal(shifted, esperado)


def test_circular_shift_preserva_blocos_contiguos() -> None:
    """Um bloco contíguo de valor constante continua contíguo (só muda de
    posição) — a propriedade central que justifica "circular-shift POR
    BLOCO" preservar estrutura de blocos, ver docstring do módulo."""
    n = 60
    t0_ms = _t0_series(n)
    # 3 blocos contíguos de 20 barras: 0,0,...,1,1,...,2,2,...
    values = np.repeat(np.arange(3, dtype=np.int64), 20)
    shifted = fpi.circular_shift_by_time(t0_ms, values, shift_ms=13 * _BAR_MS)
    # conta quantas transições de valor existem na série deslocada -- uma
    # rotação circular de 3 blocos tem no máximo 3 transições (podendo
    # "colar" duas cópias do mesmo bloco na fronteira circular, <=3)
    transitions = int(np.sum(shifted[1:] != shifted[:-1]))
    assert transitions <= 3


def test_circular_shift_aceita_t0_fora_de_ordem_e_devolve_na_ordem_de_entrada() -> None:
    n = 30
    t0_sorted = _t0_series(n)
    values_sorted = np.arange(n, dtype=np.int64)
    perm = np.random.default_rng(1).permutation(n)
    t0_embaralhado = t0_sorted[perm]
    values_embaralhado = values_sorted[perm]

    shifted_ordenado = fpi.circular_shift_by_time(t0_sorted, values_sorted, shift_ms=0)
    shifted_embaralhado = fpi.circular_shift_by_time(t0_embaralhado, values_embaralhado, shift_ms=0)
    # mesmo shift (0) -- resultado, quando reordenado de volta por t0, bate
    reordenado = shifted_embaralhado[np.argsort(perm)]
    np.testing.assert_array_equal(shifted_ordenado, reordenado)


def test_draw_circular_shift_ms_fica_dentro_do_intervalo_declarado() -> None:
    t0_ms = _t0_series(100)
    duration_ms = int(t0_ms.max() - t0_ms.min()) + 1
    rng = np.random.default_rng(2)
    for _ in range(200):
        shift = fpi.draw_circular_shift_ms(t0_ms, rng)
        assert 0 <= shift < duration_ms


def test_effective_block_count_e_duracao_sobre_largura_de_grupo() -> None:
    """Mesma convenção de `cpcv.assign_time_groups`: duração = `(max-min)
    + 1` (fronteira direita exclusiva cobrindo o próprio máximo), não
    `n_linhas * espaçamento` -- dado real (dollar bars) não tem
    espaçamento uniforme, então só `t0.max()-t0.min()` é universal."""
    t0_ms = _t0_series(96)  # t0 de 0 a 95*bar_ms
    block_width_ms = 24 * _BAR_MS
    n_blocks = fpi.effective_block_count(t0_ms, block_width_ms)
    duracao_esperada = (95 * _BAR_MS) + 1
    assert n_blocks == pytest.approx(duracao_esperada / (24 * _BAR_MS), rel=1e-9)


# ============================================================================
# weighted_state_positive_rate / weighted_state_auc
# ============================================================================


def test_weighted_state_positive_rate_pondera_corretamente() -> None:
    y = np.array([1.0, 1.0, 0.0, 0.0], dtype=np.float64)
    state_ids = np.array([0, 0, 1, 1], dtype=np.int64)
    weight = np.array([1.0, 3.0, 1.0, 1.0], dtype=np.float64)
    rate = fpi.weighted_state_positive_rate(y, state_ids, weight, n_states=2)
    assert rate[0] == pytest.approx(1.0)  # ambas as linhas do estado 0 são y=1
    assert rate[1] == pytest.approx(0.0)


def test_weighted_state_positive_rate_estado_sem_massa_vira_nan() -> None:
    y = np.array([1.0, 0.0], dtype=np.float64)
    state_ids = np.array([0, 0], dtype=np.int64)
    weight = np.array([1.0, 1.0], dtype=np.float64)
    rate = fpi.weighted_state_positive_rate(y, state_ids, weight, n_states=3)
    assert not np.isnan(rate[0])
    assert np.isnan(rate[1])
    assert np.isnan(rate[2])


def test_weighted_state_positive_rate_state_ids_fora_intervalo_levanta_erro_com_contexto() -> None:
    """Achado real (2026-08-31): `regime` nulo mapeado sem filtro upstream
    vira o sentinela de overflow int64 (`-9223372036854775808`) e indexava
    fora dos limites com `IndexError` sem nenhum contexto. Precisa falhar
    alto, cedo, com `MetaFpInventoryError` explicando a causa provável."""
    y = np.array([1.0, 0.0, 1.0], dtype=np.float64)
    state_ids = np.array([0, 1, -9223372036854775808], dtype=np.int64)
    weight = np.ones(3, dtype=np.float64)
    with pytest.raises(fpi.MetaFpInventoryError, match="fora de"):
        fpi.weighted_state_positive_rate(y, state_ids, weight, n_states=3)


def test_weighted_state_positive_rate_state_ids_igual_a_n_states_levanta_erro() -> None:
    """Fora-de-intervalo também pelo lado de CIMA (`state_ids == n_states`
    é o erro clássico off-by-one, não só sentinelas negativos)."""
    y = np.array([1.0, 0.0], dtype=np.float64)
    state_ids = np.array([0, 3], dtype=np.int64)  # n_states=3 -> válido é 0,1,2
    weight = np.ones(2, dtype=np.float64)
    with pytest.raises(fpi.MetaFpInventoryError):
        fpi.weighted_state_positive_rate(y, state_ids, weight, n_states=3)


def test_weighted_state_auc_estado_perfeitamente_discriminativo_da_auc_1() -> None:
    n = 200
    state_ids = np.array([0] * (n // 2) + [1] * (n // 2), dtype=np.int64)
    y = np.array([0.0] * (n // 2) + [1.0] * (n // 2), dtype=np.float64)  # estado==y exatamente
    weight = np.ones(n, dtype=np.float64)
    auc = fpi.weighted_state_auc(y, state_ids, weight, n_states=2)
    assert auc == pytest.approx(1.0)


def test_weighted_state_auc_sem_relacao_fica_perto_de_0_5() -> None:
    rng = np.random.default_rng(3)
    n = 5000
    state_ids = rng.integers(0, 4, size=n).astype(np.int64)
    y = rng.integers(0, 2, size=n).astype(np.float64)  # independente de state_ids
    weight = np.ones(n, dtype=np.float64)
    auc = fpi.weighted_state_auc(y, state_ids, weight, n_states=4)
    assert auc == pytest.approx(0.5, abs=0.05)


def test_weighted_state_auc_menos_de_2_classes_em_y_retorna_nan() -> None:
    y = np.zeros(10, dtype=np.float64)  # só classe 0
    state_ids = np.array([0, 1] * 5, dtype=np.int64)
    weight = np.ones(10, dtype=np.float64)
    assert np.isnan(fpi.weighted_state_auc(y, state_ids, weight, n_states=2))


def test_weighted_state_auc_menos_de_2_estados_com_massa_retorna_nan() -> None:
    y = np.array([1.0, 0.0, 1.0, 0.0], dtype=np.float64)
    state_ids = np.zeros(4, dtype=np.int64)  # todo mundo no mesmo estado
    weight = np.ones(4, dtype=np.float64)
    assert np.isnan(fpi.weighted_state_auc(y, state_ids, weight, n_states=1))


# ============================================================================
# evaluate_path_null — procedimento completo de 1 path
# ============================================================================


def _sinal_forte(n: int, *, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """`state_ids` prediz `y` quase perfeitamente (com um pouco de ruído,
    pra não ficar em 1,0 exato) -- construído pra sobreviver ao nulo."""
    rng = np.random.default_rng(seed)
    t0_ms = _t0_series(n)
    state_ids = rng.integers(0, 3, size=n).astype(np.int64)
    noise = rng.random(n) < 0.1
    y = (state_ids == 0).astype(np.float64)
    y[noise] = 1.0 - y[noise]
    weight = np.ones(n, dtype=np.float64)
    return t0_ms, state_ids, y, weight


def _sinal_nulo(n: int, *, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    t0_ms = _t0_series(n)
    state_ids = rng.integers(0, 3, size=n).astype(np.int64)
    y = rng.integers(0, 2, size=n).astype(np.float64)
    weight = np.ones(n, dtype=np.float64)
    return t0_ms, state_ids, y, weight


def test_evaluate_path_null_sinal_forte_tende_a_passar() -> None:
    t0_ms, state_ids, y, weight = _sinal_forte(2000, seed=10)
    rng = np.random.default_rng(11)
    result = fpi.evaluate_path_null(
        t0_ms, state_ids, y, weight,
        n_states=3, block_width_ms=200 * _BAR_MS, n_seeds=100, rng=rng,
    )
    assert result.auc_observed > 0.8
    assert result.passed is True
    assert result.n_seeds == 100
    assert result.n_states_observed == 3


def test_evaluate_path_null_sem_relacao_geralmente_nao_passa() -> None:
    """Estocástico por natureza -- roda várias sementes independentes e
    exige que a MAIORIA não passe (proxy rápido da calibração ~5%, sem
    pagar o custo de `validate_null_calibration` completo)."""
    n_trials = 30
    n_pass = 0
    for trial in range(n_trials):
        t0_ms, state_ids, y, weight = _sinal_nulo(800, seed=100 + trial)
        rng = np.random.default_rng(200 + trial)
        result = fpi.evaluate_path_null(
            t0_ms, state_ids, y, weight,
            n_states=3, block_width_ms=80 * _BAR_MS, n_seeds=60, rng=rng,
        )
        n_pass += int(result.passed)
    assert n_pass / n_trials <= 0.30  # bem acima de 5% seria sinal de nulo mal calibrado


# ============================================================================
# validate_null_calibration — P0, a validação obrigatória e bloqueante
# ============================================================================


def test_validate_null_calibration_com_nulo_bem_calibrado_fica_perto_de_5_porcento() -> None:
    t0_ms, _state_ids_real, y, weight = _sinal_nulo(600, seed=42)
    # proxy SEM relação com y (mesma lógica de "regime de outro símbolo"),
    # gerado com semente independente
    proxy_state_ids = np.random.default_rng(99).integers(0, 3, size=600).astype(np.int64)

    rng = np.random.default_rng(7)
    result = fpi.validate_null_calibration(
        t0_ms, proxy_state_ids, y, weight,
        n_states=3, block_width_ms=60 * _BAR_MS,
        n_trials=60, n_seeds_per_trial=60, rng=rng,
    )
    assert result.n_trials == 60
    assert 0.0 <= result.pass_rate <= 1.0
    assert result.ci_low <= result.ci_high
    # o IC precisa ser plausível em torno de 5% -- não exige well_calibrated
    # True sempre (é um teste estocástico de um esquema estocástico), mas a
    # taxa não pode estar grosseiramente errada (ex. >30%, sinal de nulo
    # estruturalmente mal calibrado, não flutuação amostral)
    assert result.pass_rate <= 0.30


def test_validate_null_calibration_retorna_dataclass_consistente() -> None:
    t0_ms, _s, y, weight = _sinal_nulo(300, seed=1)
    proxy = np.random.default_rng(2).integers(0, 2, size=300).astype(np.int64)
    rng = np.random.default_rng(3)
    result = fpi.validate_null_calibration(
        t0_ms, proxy, y, weight,
        n_states=2, block_width_ms=30 * _BAR_MS,
        n_trials=20, n_seeds_per_trial=20, rng=rng,
    )
    assert result.n_pass == pytest.approx(result.pass_rate * result.n_trials, abs=1e-9)
    assert result.target == 0.05
    assert result.confidence_level == 0.95
    assert isinstance(result.well_calibrated, bool)


# ============================================================================
# uniqueness_per_side
# ============================================================================


def test_uniqueness_per_side_separa_long_e_short() -> None:
    n = 20
    t0 = pl.Series(_t0_series(n)).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    t1 = pl.Series(_t0_series(n) + 4 * _BAR_MS).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    side = pl.Series([1] * 10 + [-1] * 10, dtype=pl.Int8)
    unicidade = fpi.uniqueness_per_side(t0, t1, side)
    assert unicidade.shape[0] == n
    assert bool(np.all(unicidade > 0.0))
    assert bool(np.all(unicidade <= 1.0))


def test_uniqueness_per_side_preserva_ordem_de_entrada() -> None:
    """`side` intercalado a cada linha -- a saída precisa alinhar com a
    ORDEM DE ENTRADA, não com a ordem interna de processamento por grupo
    (`group_by` reordena; a função precisa desfazer isso)."""
    n = 12
    t0_vals = _t0_series(n)
    side_vals = np.array([1, -1] * 6, dtype=np.int64)  # alterna a cada linha
    t0 = pl.Series(t0_vals).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    t1 = pl.Series(t0_vals + 4 * _BAR_MS).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    side = pl.Series(side_vals.tolist(), dtype=pl.Int8)
    unicidade = fpi.uniqueness_per_side(t0, t1, side)

    for target_side in (1, -1):
        mask = side_vals == target_side
        _concorrencia, esperado = fpi.compute_concurrency_and_uniqueness(
            t0_vals[mask].astype(np.int64), (t0_vals[mask] + 4 * _BAR_MS).astype(np.int64)
        )
        np.testing.assert_allclose(unicidade[mask], esperado)
