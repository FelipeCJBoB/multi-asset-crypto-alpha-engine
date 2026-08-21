"""Testes de `src/analysis/m6_common_factor_hypothesis.py` — núcleo puro
(`_edge_bruto_se`, `stratum_metrics`, `cochrans_q_heterogeneity`,
`permutation_heterogeneity_test`/AG-092), sem IO real
(`compute_metrics_for_symbol`/`run_and_save_m6_report` fazem IO real via
`dataset.build_modeling_frame`, não exercitados aqui — mesma convenção de
`test_models_dataset.py` sobre `build_modeling_frame`)."""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest
from scipy.stats import chi2

from src.analysis.m6_common_factor_hypothesis import (
    StratumMetrics,
    _dense_bucket_codes,
    _edge_bruto_se,
    _q_statistic_continuous_episode_weighted,
    _q_statistic_from_bucket_codes,
    cochrans_q_heterogeneity,
    cochrans_q_heterogeneity_continuous,
    permutation_heterogeneity_test,
    permutation_heterogeneity_test_continuous,
    stratum_metrics,
)


def test_edge_bruto_se_bate_com_formula_de_variancia_multinomial() -> None:
    """`Var(edge) = tp_mult²·Var(frac_TP) + sl_mult²·Var(frac_SL) -
    2·tp_mult·sl_mult·Cov(frac_TP,frac_SL)`, com `Var(frac_i)=p_i(1-p_i)/n`
    e `Cov(frac_TP,frac_SL)=-frac_TP·frac_SL/n` (propriedade padrão da
    distribuição multinomial) — recomputado aqui de forma independente
    (não chamando `_edge_bruto_se`) pra provar a função, não repetir a
    mesma fórmula duas vezes sem checagem cruzada."""
    frac_tp, frac_sl, n = 0.3, 0.2, 1000
    tp_mult, sl_mult = 2.0, 1.5

    var_tp = frac_tp * (1 - frac_tp) / n
    var_sl = frac_sl * (1 - frac_sl) / n
    cov = -frac_tp * frac_sl / n
    expected_var = tp_mult**2 * var_tp + sl_mult**2 * var_sl - 2 * tp_mult * sl_mult * cov
    expected_se = math.sqrt(expected_var)

    se = _edge_bruto_se(frac_tp, frac_sl, n, tp_mult=tp_mult, sl_mult=sl_mult)
    assert se == pytest.approx(expected_se, rel=1e-9)


def test_edge_bruto_se_n_zero_devolve_nan() -> None:
    assert math.isnan(_edge_bruto_se(0.3, 0.2, 0, tp_mult=2.0, sl_mult=1.5))


def _labels_with_barrier_hits(hits: list[str], atr: float = 0.01) -> pl.DataFrame:
    return pl.DataFrame({"barrier_hit": hits, "atr_at_t0": [atr] * len(hits)})


def test_stratum_metrics_bate_com_algebra_manual_do_prd() -> None:
    """§1.2: `edge_bruto_atr = frac_TP·tp_mult - frac_SL·sl_mult`,
    `edge_liq_atr = edge_bruto_atr - custo_atr`, `captura = edge_liq_atr /
    edge_bruto_atr` — 10 trades com contagem conhecida (4 TP, 3 SL, 2 TIME,
    1 NOFILL), `atr_at_t0` constante (mediana trivial) pra isolar a
    aritmética de `custo_atr` de qualquer efeito de distribuição."""
    labels = _labels_with_barrier_hits(["TP"] * 4 + ["SL"] * 3 + ["TIME"] * 2 + ["NOFILL"] * 1)
    tp_mult, sl_mult = 2.0, 1.5
    maker_fee, taker_fee = 0.0002, 0.0005

    metrics = stratum_metrics(
        labels, symbol="BTCUSDT", side=1, regime=None,
        tp_atr_mult=tp_mult, sl_atr_mult=sl_mult, maker_fee=maker_fee, taker_fee=taker_fee,
    )

    assert metrics.n == 10
    assert metrics.frac_tp == pytest.approx(0.4)
    assert metrics.frac_sl == pytest.approx(0.3)
    expected_edge_bruto = 0.4 * tp_mult - 0.3 * sl_mult
    assert metrics.edge_bruto_atr == pytest.approx(expected_edge_bruto)
    assert metrics.edge_liq_atr == pytest.approx(expected_edge_bruto - metrics.custo_atr)
    assert metrics.captura == pytest.approx(metrics.edge_liq_atr / metrics.edge_bruto_atr)


def test_stratum_metrics_n_zero_propaga_nan_sem_levantar() -> None:
    labels = _labels_with_barrier_hits([])
    metrics = stratum_metrics(
        labels, symbol="BTCUSDT", side=1, regime=None,
        tp_atr_mult=2.0, sl_atr_mult=1.5, maker_fee=0.0002, taker_fee=0.0005,
    )
    assert metrics.n == 0
    assert math.isnan(metrics.custo_atr)
    assert math.isnan(metrics.edge_bruto_atr_se)


def _stratum(symbol: str, edge: float, se: float, *, side: int = 1) -> StratumMetrics:
    return StratumMetrics(
        symbol=symbol, side=side, regime=None, n=100_000,
        frac_tp=0.4, frac_sl=0.3, frac_time=0.2, frac_nofill=0.1,
        edge_bruto_atr=edge, edge_bruto_atr_se=se,
        custo_atr=0.1, edge_liq_atr=edge - 0.1,
        captura=(edge - 0.1) / edge if edge else float("nan"),
    )


def test_cochrans_q_valores_identicos_da_q_zero_i2_zero_p_value_um() -> None:
    """Todos os símbolos com o MESMO `edge_bruto_atr` verdadeiro (SEs
    diferentes, não importa) -- heterogeneidade zero por construção:
    `Q=0` exato (cada desvio ao quadrado é zero), `I²=0%`, `p_value=1,0`
    exato (`chi2.sf(0, df)=1` sempre, pra qualquer df>=1 -- P(X<=0)=0 numa
    distribuição chi² contínua, então P(X>0)=1)."""
    strata = (
        _stratum("BTCUSDT", 0.5, 0.01),
        _stratum("ETHUSDT", 0.5, 0.02),
        _stratum("SOLUSDT", 0.5, 0.03),
    )
    het = cochrans_q_heterogeneity(strata)
    assert het.pooled_edge_bruto_atr == pytest.approx(0.5)
    assert het.q_statistic == pytest.approx(0.0, abs=1e-12)
    assert het.i_squared_pct == pytest.approx(0.0)
    assert het.p_value == pytest.approx(1.0)


def test_cochrans_q_dois_simbolos_bate_com_valor_conhecido_da_chi2() -> None:
    """k=2, valores [0,6; 0,4], SE=0,1 nos dois -- pesos iguais (100 cada),
    `pooled=0,5` exato, `Q=100·0,01+100·0,01=2,0` exato, `df=1`,
    `I²=max(0,(2-1)/2)·100=50%` exato. `p_value=chi2.sf(2,1)≈0,1573` --
    valor de referência bem estabelecido (chi²(1) é o quadrado de uma
    normal padrão: `P(X>2)=P(|Z|>√2)=2·(1-Φ(√2))≈0,15730`), não um número
    de scipy tomado de caixa-preta."""
    strata = (_stratum("BTCUSDT", 0.6, 0.1), _stratum("ETHUSDT", 0.4, 0.1))
    het = cochrans_q_heterogeneity(strata)

    assert het.pooled_edge_bruto_atr == pytest.approx(0.5)
    assert het.q_statistic == pytest.approx(2.0)
    assert het.df == 1
    assert het.i_squared_pct == pytest.approx(50.0)
    assert het.p_value == pytest.approx(0.15730, abs=1e-4)


def test_cochrans_q_side_misturado_levanta_erro() -> None:
    strata = (_stratum("BTCUSDT", 0.5, 0.1, side=1), _stratum("ETHUSDT", 0.5, 0.1, side=-1))
    with pytest.raises(ValueError, match="mesmo side"):
        cochrans_q_heterogeneity(strata)


def test_cochrans_q_se_invalido_devolve_nan_sem_levantar() -> None:
    strata = (_stratum("BTCUSDT", 0.5, 0.0), _stratum("ETHUSDT", 0.5, 0.1))
    het = cochrans_q_heterogeneity(strata)
    assert math.isnan(het.pooled_edge_bruto_atr)
    assert math.isnan(het.q_statistic)
    assert math.isnan(het.p_value)


def test_cochrans_q_k1_devolve_nan_nunca_zero_ou_cem_por_acaso_de_ponto_flutuante() -> None:
    """`k=1` -- `Q=0` é determinístico em aritmética exata (não
    "indefinido"), mas este repo trata como `NaN`/não-computável por
    decisão específica ao uso real (M4: `k=1` normalmente é um
    classificador degenerado que saturou a 1 bucket, AG-087 -- excluir
    da mediana evita recompensar isso com um score "limpo"). NÃO é
    precedente de `metafor`/`meta` (R) -- verificado por auditoria
    independente que ambos hard-codificam `Q=0`/`I²=0%` pra `k=1`, o
    OPOSTO de `NaN` (ver docstring de `cochrans_q_heterogeneity` pra a
    correção de proveniência completa, 2026-08-19). NUNCA um `0.0` que
    dependeria de `Σ(w·v)/Σw` com 1 termo recuperar `v` bit-exato (não
    garantido em ponto flutuante -- achado real,
    `experiments/m4_critical_windows_report.json`,
    BTCUSDT/CRYPTO_WINTER/short: essa conta deu `3,857e-32`, não `0.0`,
    e a fórmula antiga `(q-df)/q` com `df=0` virava `100.0`, o extremo
    oposto do "0.0 por convenção" pretendido). `pooled_edge_bruto_atr`
    continua computável -- é literalmente o valor do único estrato."""
    strata = (_stratum("BTCUSDT", 0.023456789123456, 0.01234567891011),)
    het = cochrans_q_heterogeneity(strata)
    assert het.k == 1
    assert het.df == 0
    assert math.isnan(het.q_statistic)
    assert math.isnan(het.p_value)
    assert math.isnan(het.i_squared_pct)
    assert het.pooled_edge_bruto_atr == pytest.approx(0.023456789123456)


def test_cochrans_q_k2_valores_quase_identicos_ainda_clipa_pra_zero_no_df_maior_que_zero() -> (
    None
):
    """Contraste com o teste de `k=1` acima: `k=2` com valores quase
    idênticos (mas não exatamente iguais) também pode gerar `q` residual
    de ruído de ponto flutuante -- mas `df=1` absorve isso via `max(0,
    (q-df)/q)`, nunca vira `100%` como o bug de `k=1` fazia. Só `df=0` é
    perigoso (ver docstring de `cochrans_q_heterogeneity`)."""
    strata = (
        _stratum("BTCUSDT", 0.5, 0.1),
        _stratum("ETHUSDT", 0.5 + 1e-15, 0.1),  # "igual" a menos de ruído de ULP
    )
    het = cochrans_q_heterogeneity(strata)
    assert het.df == 1
    assert not math.isnan(het.i_squared_pct)
    assert het.i_squared_pct == pytest.approx(0.0, abs=1e-6)


# ============================================================================
# AG-092 -- permutation_heterogeneity_test (permutação em bloco por
# episódio, corrige violação de independência de estratos sob
# autocorrelação intra-episódio).
# ============================================================================


def test_dense_bucket_codes_remapeia_ids_arbitrarios_pra_0_k_menos_1() -> None:
    bucket_ids = np.array([7, 7, 3, 3, 3, 9], dtype=np.int64)
    codes, k = _dense_bucket_codes(bucket_ids)
    assert k == 3
    assert codes.tolist() == [1, 1, 0, 0, 0, 2]  # 3->0, 7->1, 9->2 (ordem ascendente)


def test_q_statistic_from_bucket_codes_bate_com_cochrans_q_heterogeneity_na_atribuicao_real() -> (
    None
):
    """Prova que o núcleo vetorizado (`_q_statistic_from_bucket_codes`,
    usado pelo teste de permutação AG-092 pra rodar centenas/milhares de
    vezes sem overhead de `StratumMetrics`/Polars) reproduz EXATAMENTE o
    `Q` da via lenta já validada (`stratum_metrics` +
    `cochrans_q_heterogeneity`) sobre a MESMA atribuição real de buckets
    -- prova que pular `custo_atr`/`edge_liq_atr`/`captura` (que `Q` não
    usa) é simplificação legítima, não uma fórmula diferente por
    acidente."""
    rng = np.random.default_rng(7)
    n = 300
    bucket_ids = rng.integers(0, 3, size=n).astype(np.int64)  # 3 buckets
    hits = rng.choice(["TP", "SL", "TIME", "NOFILL"], size=n, p=[0.3, 0.25, 0.3, 0.15])
    atr = rng.uniform(0.005, 0.02, size=n)
    labels = pl.DataFrame({"barrier_hit": hits, "atr_at_t0": atr})

    strata = tuple(
        stratum_metrics(
            labels.filter(pl.Series(bucket_ids) == b),
            symbol="TESTUSDT", side=1, regime=str(b),
            tp_atr_mult=2.0, sl_atr_mult=1.5, maker_fee=0.0002, taker_fee=0.0005,
        )
        for b in sorted(set(bucket_ids.tolist()))
    )
    het_slow = cochrans_q_heterogeneity(strata)

    is_tp = (hits == "TP").astype(np.int64)
    is_sl = (hits == "SL").astype(np.int64)
    codes, k = _dense_bucket_codes(bucket_ids)
    q_fast = _q_statistic_from_bucket_codes(codes, is_tp, is_sl, tp_mult=2.0, sl_mult=1.5, k=k)

    assert q_fast == pytest.approx(het_slow.q_statistic, rel=1e-9)


def test_permutation_heterogeneity_test_k1_devolve_nan() -> None:
    """1 único bucket -- mesmo caso degenerado de `cochrans_q_
    heterogeneity` (AG-091), sem sentido permutar nada."""
    n = 100
    bucket_ids = np.zeros(n, dtype=np.int64)
    is_tp = np.zeros(n, dtype=np.int64)
    is_sl = np.zeros(n, dtype=np.int64)
    result = permutation_heterogeneity_test(
        bucket_ids, is_tp, is_sl, tp_mult=2.0, sl_mult=1.5, n_permutations=200, seed=1
    )
    assert math.isnan(result.p_value)
    assert result.n_episodes == 1
    assert result.n_permutations_valid == 0


def test_permutation_heterogeneity_test_array_vazio_levanta_value_error() -> None:
    empty = np.array([], dtype=np.int64)
    with pytest.raises(ValueError, match="vazio"):
        permutation_heterogeneity_test(
            empty, empty, empty, tp_mult=2.0, sl_mult=1.5, n_permutations=200, seed=1
        )


def test_permutation_heterogeneity_test_shape_desalinhado_levanta_value_error() -> None:
    """Achado de auditoria independente (L3, 2026-08-19) -- mesma
    disciplina de `adjusted_rand` (`regime_utility.py`), que já levanta
    `ValueError` explícito em shape mismatch em vez de deixar o NumPy
    levantar um erro genérico e menos claro."""
    bucket_ids = np.zeros(100, dtype=np.int64)
    is_tp = np.zeros(100, dtype=np.int64)
    is_sl = np.zeros(50, dtype=np.int64)  # shape errado de propósito
    with pytest.raises(ValueError, match="mesmo shape"):
        permutation_heterogeneity_test(
            bucket_ids, is_tp, is_sl, tp_mult=2.0, sl_mult=1.5, n_permutations=200, seed=1
        )


def test_permutation_heterogeneity_test_2_episodios_1_por_bucket_p_value_sempre_um() -> None:
    """Achado central de AG-092: com exatamente 1 episódio por bucket
    (`k=2`, `n_episodes=2`), toda permutação possível do vetor de
    bucket-por-episódio é ou a identidade ou a troca completa dos 2
    rótulos -- e `Q = Σw_i(edge_i-pooled)²` é uma função SIMÉTRICA do
    CONJUNTO `{(edge_i, w_i)}`, invariante a qual índice físico guarda
    qual valor. Logo `Q_perm == Q_observado` em TODA permutação, sempre,
    mesmo com os 2 grupos tendo edges bem diferentes -- `p_value=1.0`
    exato, analiticamente previsível (não um resultado de sorte de
    seed). Prova indireta mas rigorosa de que a permutação é por
    EPISÓDIO inteiro (nunca por linha individual): um embaralhamento
    linha-a-linha misturaria TP/SL das duas metades e produziria uma
    distribuição de `Q_perm` dispersa, não esse resultado degenerado
    exato -- se este teste falhar (`p_value != 1.0`) depois de uma
    mudança futura, é sinal de que a permutação parou de respeitar
    fronteira de episódio."""
    rng = np.random.default_rng(11)
    n_a, n_b = 200, 150
    hit_a = rng.choice(["TP", "SL", "TIME"], size=n_a, p=[0.6, 0.2, 0.2])
    hit_b = rng.choice(["TP", "SL", "TIME"], size=n_b, p=[0.2, 0.6, 0.2])
    hits = np.concatenate([hit_a, hit_b])
    is_tp = (hits == "TP").astype(np.int64)
    is_sl = (hits == "SL").astype(np.int64)
    bucket_ids = np.concatenate(
        [np.zeros(n_a, dtype=np.int64), np.ones(n_b, dtype=np.int64)]
    )

    result = permutation_heterogeneity_test(
        bucket_ids, is_tp, is_sl, tp_mult=2.0, sl_mult=1.5, n_permutations=500, seed=1
    )
    assert result.n_episodes == 2
    assert not math.isnan(result.q_observed)
    assert result.q_observed > 0.0  # os 2 grupos têm edge claramente diferente
    assert result.n_permutations_valid == 500
    assert result.p_value == pytest.approx(1.0)


def test_permutation_heterogeneity_test_3_episodios_1_por_bucket_generaliza_alem_de_k2() -> None:
    """Achado de auditoria independente (L2, 2026-08-19): o argumento de
    simetria do teste acima (`Q` é função do CONJUNTO `{(edge_i,w_i)}`,
    invariante a relabeling) generaliza pra QUALQUER `n_episodes==k`, não
    só a troca binária de `k=2` -- este teste exercita `k=3` (3! = 6
    permutações possíveis, não só 2), cobrindo a lógica de indexação
    (`np.repeat`/`permuted[episode_id]`) num cenário com mais de 2 grupos
    interagindo, onde um bug sutil de indexação teria mais chance de
    escapar do caso binário."""
    rng = np.random.default_rng(17)
    n_a, n_b, n_c = 150, 150, 150
    hit_a = rng.choice(["TP", "SL", "TIME"], size=n_a, p=[0.7, 0.1, 0.2])
    hit_b = rng.choice(["TP", "SL", "TIME"], size=n_b, p=[0.4, 0.4, 0.2])
    hit_c = rng.choice(["TP", "SL", "TIME"], size=n_c, p=[0.1, 0.7, 0.2])
    hits = np.concatenate([hit_a, hit_b, hit_c])
    is_tp = (hits == "TP").astype(np.int64)
    is_sl = (hits == "SL").astype(np.int64)
    bucket_ids = np.concatenate(
        [
            np.zeros(n_a, dtype=np.int64),
            np.ones(n_b, dtype=np.int64),
            np.full(n_c, 2, dtype=np.int64),
        ]
    )

    result = permutation_heterogeneity_test(
        bucket_ids, is_tp, is_sl, tp_mult=2.0, sl_mult=1.5, n_permutations=500, seed=3
    )
    assert result.n_episodes == 3
    assert not math.isnan(result.q_observed)
    assert result.q_observed > 0.0
    assert result.n_permutations_valid == 500
    assert result.p_value == pytest.approx(1.0)


def test_permutation_heterogeneity_test_separacao_real_com_muitos_episodios_da_p_value_baixo() -> (
    None
):
    """Contraste com o teste acima: MUITOS episódios curtos alternando
    entre os 2 buckets (não só 1 cada) -- o espaço de permutação é bem
    maior, e a separação real entre os 2 grupos deveria ser
    estatisticamente detectável (`p_value` baixo), provando que o teste
    tem PODER de detectar heterogeneidade genuína, não só produz `NaN`/
    `1.0` em qualquer cenário."""
    rng = np.random.default_rng(23)
    bucket_chunks = []
    hit_chunks = []
    for i in range(20):  # 20 episódios alternando, ~50 trades cada
        n_ep = 50
        if i % 2 == 0:
            bucket_chunks.append(np.zeros(n_ep, dtype=np.int64))
            hit_chunks.append(rng.choice(["TP", "SL", "TIME"], size=n_ep, p=[0.65, 0.15, 0.2]))
        else:
            bucket_chunks.append(np.ones(n_ep, dtype=np.int64))
            hit_chunks.append(rng.choice(["TP", "SL", "TIME"], size=n_ep, p=[0.15, 0.65, 0.2]))
    bucket_ids = np.concatenate(bucket_chunks)
    hits = np.concatenate(hit_chunks)
    is_tp = (hits == "TP").astype(np.int64)
    is_sl = (hits == "SL").astype(np.int64)

    result = permutation_heterogeneity_test(
        bucket_ids, is_tp, is_sl, tp_mult=2.0, sl_mult=1.5, n_permutations=1000, seed=5
    )
    assert result.n_episodes == 20
    assert result.p_value < 0.05


def test_permutation_heterogeneity_test_e_deterministico_mesmo_seed_mesmo_resultado() -> None:
    rng = np.random.default_rng(31)
    n = 400
    bucket_ids = rng.integers(0, 2, size=n).astype(np.int64)
    hits = rng.choice(["TP", "SL", "TIME"], size=n, p=[0.4, 0.3, 0.3])
    is_tp = (hits == "TP").astype(np.int64)
    is_sl = (hits == "SL").astype(np.int64)

    result_a = permutation_heterogeneity_test(
        bucket_ids, is_tp, is_sl, tp_mult=2.0, sl_mult=1.5, n_permutations=300, seed=99
    )
    result_b = permutation_heterogeneity_test(
        bucket_ids, is_tp, is_sl, tp_mult=2.0, sl_mult=1.5, n_permutations=300, seed=99
    )
    assert result_a == result_b


# ============================================================================
# Generalização contínua (AG-114, 2026-08-20, PLANO_MESTRE_PRINCE2.md
# §15.12.1) -- mesma família Cochran's Q/permutação em bloco, resposta
# CONTÍNUA (volatilidade futura) e ponderada por EPISÓDIO desde a
# estatística observada, não só a distribuição nula.
# ============================================================================


def test_q_statistic_continuous_episode_weighted_bate_com_calculo_manual() -> None:
    """`bucket_codes`/`response` bar-level; `n_episodes_per_bucket`
    FORNECIDO pelo chamador (não derivado dentro da função -- ver
    docstring). Bucket 0: barras `[1.0,1.0,2.0,2.0,1.5,1.5]` (n=6, média
    1.5, var(ddof=1)=0.2); bucket 1: barras `[3.0,3.0,4.0,4.0]` (n=4,
    média 3.5, var=1/3). `n_episodes_per_bucket=[3,2]` (3 episódios no
    bucket 0, 2 no bucket 1, contando runs consecutivos reais no array).
    `w0=3/0.2=15`, `w1=2/(1/3)=6`, `pooled=(15*1.5+6*3.5)/21=87/42=29/14`,
    `Q=15*(1.5-29/14)²+6*(3.5-29/14)²=840/49≈17,142857` -- calculado à
    mão de forma independente, não reusando a fórmula da função."""
    bucket_codes = np.array([0, 0, 1, 1, 0, 0, 1, 1, 0, 0], dtype=np.int64)
    response = np.array(
        [1.0, 1.0, 3.0, 3.0, 2.0, 2.0, 4.0, 4.0, 1.5, 1.5], dtype=np.float64
    )
    n_episodes_per_bucket = np.array([3.0, 2.0], dtype=np.float64)

    q, pooled = _q_statistic_continuous_episode_weighted(
        bucket_codes, response, n_episodes_per_bucket, k=2
    )

    assert q == pytest.approx(840.0 / 49.0, rel=1e-9)
    assert pooled == pytest.approx(29.0 / 14.0, rel=1e-9)


def test_q_statistic_continuous_episode_weighted_menos_de_2_barras_da_nan() -> None:
    """Bucket 1 tem só 1 BARRA finita -- variância amostral (ddof=1)
    indefinida, resultado inteiro vira NaN (mesma disciplina de
    `anova_by_group`/`_q_statistic_from_bucket_codes`: nunca 0/exceção
    silenciosa dentro de um laço de permutação). Diferente da versão
    anterior (episódio-mean-variance): aqui o que importa é contagem de
    BARRA por bucket, não de episódio -- corrigido depois de achado real
    rodando a suíte (ver comentário no módulo)."""
    bucket_codes = np.array([0, 0, 0, 1], dtype=np.int64)
    response = np.array([1.0, 2.0, 1.5, 5.0], dtype=np.float64)
    n_episodes_per_bucket = np.array([1.0, 1.0], dtype=np.float64)

    q, pooled = _q_statistic_continuous_episode_weighted(
        bucket_codes, response, n_episodes_per_bucket, k=2
    )

    assert math.isnan(q)
    assert math.isnan(pooled)


def test_q_statistic_continuous_episode_weighted_filtra_nan_antes_de_agrupar() -> None:
    """Barra com `response=NaN` é excluída do cálculo de var/média do seu
    bucket -- não propaga `NaN` pra tudo, mesma disciplina de
    `anova_by_group`."""
    bucket_codes = np.array([0, 0, 0, 1, 1, 1], dtype=np.int64)
    response = np.array([1.0, np.nan, 1.2, 5.0, 5.3, 4.8], dtype=np.float64)
    n_episodes_per_bucket = np.array([1.0, 1.0], dtype=np.float64)

    q, pooled = _q_statistic_continuous_episode_weighted(
        bucket_codes, response, n_episodes_per_bucket, k=2
    )
    assert np.isfinite(q)
    assert np.isfinite(pooled)


def test_q_statistic_continuous_episode_weighted_computavel_com_1_episodio_por_bucket() -> None:
    """**Achado real desta sessão**: com `n_episodes_per_bucket=[1,1]`
    (exatamente 1 episódio por bucket, cenário comum -- candidato entra
    1x num estado e fica), o resultado É computável (usa variância
    BAR-LEVEL, não variância entre médias de episódio) -- diferente do
    desenho anterior, que dava `NaN` sempre nesse cenário mesmo com
    centenas de barras de dado real disponíveis."""
    bucket_codes = np.array([0, 0, 0, 0, 1, 1, 1], dtype=np.int64)
    response = np.array([1.0, 1.1, 0.9, 1.0, 5.0, 5.2, 4.8], dtype=np.float64)
    n_episodes_per_bucket = np.array([1.0, 1.0], dtype=np.float64)

    q, pooled = _q_statistic_continuous_episode_weighted(
        bucket_codes, response, n_episodes_per_bucket, k=2
    )
    assert np.isfinite(q)
    assert np.isfinite(pooled)
    assert q > 0.0  # os 2 buckets têm média claramente diferente


def test_cochrans_q_heterogeneity_continuous_bate_com_calculo_manual() -> None:
    """Mesmo cenário de `test_q_statistic_continuous_episode_weighted_
    bate_com_calculo_manual`, mas via a função pública (que deriva
    `n_episodes_per_bucket` sozinha a partir de `segment_boundaries`)."""
    bucket_ids = np.array([0, 0, 1, 1, 0, 0, 1, 1, 0, 0], dtype=np.int64)
    response = np.array(
        [1.0, 1.0, 3.0, 3.0, 2.0, 2.0, 4.0, 4.0, 1.5, 1.5], dtype=np.float64
    )

    result = cochrans_q_heterogeneity_continuous(bucket_ids, response)

    assert result.k == 2
    assert result.n_episodes == 5
    assert result.df == 1
    assert result.q_statistic == pytest.approx(840.0 / 49.0, rel=1e-9)
    assert result.pooled_response == pytest.approx(29.0 / 14.0, rel=1e-9)
    expected_p = float(chi2.sf(840.0 / 49.0, 1))
    assert result.p_value == pytest.approx(expected_p, rel=1e-9)
    expected_i_squared = max(0.0, (840.0 / 49.0 - 1) / (840.0 / 49.0)) * 100.0
    assert result.i_squared_pct == pytest.approx(expected_i_squared, rel=1e-9)


def test_cochrans_q_heterogeneity_continuous_k1_devolve_nan() -> None:
    """1 único bucket -- mesmo caso degenerado de `cochrans_q_
    heterogeneity` (AG-091): `Q`/`p_value`/`i_squared_pct` viram `NaN`
    explícito (`df=0`), nunca `0.0`/`100.0` por acidente de ponto
    flutuante."""
    n = 100
    bucket_ids = np.zeros(n, dtype=np.int64)
    response = np.linspace(0.01, 0.05, n)
    result = cochrans_q_heterogeneity_continuous(bucket_ids, response)
    assert result.k == 1
    assert result.df == 0
    assert math.isnan(result.q_statistic)
    assert math.isnan(result.p_value)
    assert math.isnan(result.i_squared_pct)


def test_permutation_heterogeneity_test_continuous_k1_devolve_nan() -> None:
    n = 100
    bucket_ids = np.zeros(n, dtype=np.int64)
    response = np.linspace(0.01, 0.05, n)
    result = permutation_heterogeneity_test_continuous(
        bucket_ids, response, n_permutations=200, seed=1
    )
    assert math.isnan(result.p_value)
    assert result.n_episodes == 1
    assert result.n_permutations_valid == 0


def test_permutation_heterogeneity_test_continuous_array_vazio_levanta_value_error() -> None:
    empty = np.array([], dtype=np.int64)
    empty_f = np.array([], dtype=np.float64)
    with pytest.raises(ValueError, match="vazio"):
        permutation_heterogeneity_test_continuous(empty, empty_f, n_permutations=200, seed=1)


def test_permutation_heterogeneity_test_continuous_shape_desalinhado_levanta_value_error() -> (
    None
):
    bucket_ids = np.zeros(100, dtype=np.int64)
    response = np.zeros(50, dtype=np.float64)  # shape errado de propósito
    with pytest.raises(ValueError, match="mesmo shape"):
        permutation_heterogeneity_test_continuous(
            bucket_ids, response, n_permutations=200, seed=1
        )


def test_permutation_heterogeneity_test_continuous_2_episodios_1_por_bucket_p_value_sempre_um() -> (
    None
):
    """Mesmo argumento de simetria do teste análogo TP/SL
    (`test_permutation_heterogeneity_test_2_episodios_1_por_bucket_p_
    value_sempre_um`): com 1 episódio por bucket, `Q` é função SIMÉTRICA
    do conjunto `{(média_i, w_i)}`, invariante a qual episódio físico
    guarda qual valor -- `Q_perm == Q_observado` em toda permutação,
    `p_value=1.0` exato, analiticamente previsível."""
    rng = np.random.default_rng(11)
    n_a, n_b = 200, 150
    response_a = rng.normal(0.01, 0.002, n_a)
    response_b = rng.normal(0.05, 0.01, n_b)
    response = np.concatenate([response_a, response_b])
    bucket_ids = np.concatenate(
        [np.zeros(n_a, dtype=np.int64), np.ones(n_b, dtype=np.int64)]
    )

    result = permutation_heterogeneity_test_continuous(
        bucket_ids, response, n_permutations=500, seed=1
    )
    assert result.n_episodes == 2
    assert not math.isnan(result.q_observed)
    assert result.q_observed > 0.0
    assert result.n_permutations_valid == 500
    assert result.p_value == pytest.approx(1.0)


def test_permutation_heterogeneity_test_continuous_separacao_real_da_p_value_baixo() -> None:
    rng = np.random.default_rng(23)
    bucket_chunks = []
    response_chunks = []
    for i in range(20):  # 20 episódios alternando, ~50 barras cada
        n_ep = 50
        if i % 2 == 0:
            bucket_chunks.append(np.zeros(n_ep, dtype=np.int64))
            response_chunks.append(rng.normal(0.01, 0.002, n_ep))
        else:
            bucket_chunks.append(np.ones(n_ep, dtype=np.int64))
            response_chunks.append(rng.normal(0.05, 0.002, n_ep))
    bucket_ids = np.concatenate(bucket_chunks)
    response = np.concatenate(response_chunks)

    result = permutation_heterogeneity_test_continuous(
        bucket_ids, response, n_permutations=1000, seed=5
    )
    assert result.n_episodes == 20
    assert result.p_value < 0.05


def test_permutation_heterogeneity_test_continuous_e_deterministico_mesma_seed() -> None:
    rng = np.random.default_rng(31)
    n = 400
    bucket_ids = rng.integers(0, 2, size=n).astype(np.int64)
    response = rng.normal(0.02, 0.01, n)

    result_a = permutation_heterogeneity_test_continuous(
        bucket_ids, response, n_permutations=300, seed=99
    )
    result_b = permutation_heterogeneity_test_continuous(
        bucket_ids, response, n_permutations=300, seed=99
    )
    assert result_a == result_b
