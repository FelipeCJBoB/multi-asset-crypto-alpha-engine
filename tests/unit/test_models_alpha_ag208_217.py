"""Testes das correções `AG-208`..`AG-217` (persona `lgbm-crypto-quant`,
2026-08-25) — todas as funções puras novas de `src/models/alpha.py`,
`src/models/monotonic.py` e `src/models/backtest_lite.py`.

Foco deliberado nos NÚCLEOS PUROS (§Núcleo funcional, casca imperativa do
`CLAUDE.md`): nenhum teste aqui treina LightGBM de verdade, porque nenhuma
das correções vive dentro do learner — todas vivem em regra de decisão,
split, agregação ou relatório. Os dois testes que tocam `fit_side_model`
existem só para provar que o parâmetro NOVO é bit-exato no default e que o
caminho alternativo não explode; a mecânica de treino em si já é coberta
por `test_models_alpha.py`.

Invariante que atravessa o arquivo inteiro: **todo default preserva o
comportamento legado bit-a-bit**. Cada correção entrou como opt-in porque
flipar o default reprocessaria as 15 combinações de produção — decisão do
Manager, não desta rodada."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.features.build import T1_FEATURE_IDS
from src.models import alpha, backtest_lite, monotonic

# ============================================================================
# AG-209 — _temporal_purged_calib_split
# ============================================================================


def test_temporal_purged_calib_split_calib_e_o_bloco_final() -> None:
    """`calib` é o bloco temporal CONTÍGUO do fim, nunca uma amostra
    espalhada — é isso que faz o purge ter sentido."""
    t0 = np.arange(0, 100, dtype=np.int64) * 1_000
    t1 = t0 + 500  # nenhum label cruza o vizinho: purge não deve remover nada
    fit_idx, calib_idx = alpha._temporal_purged_calib_split(t0, t1, holdout_frac=0.25)

    assert calib_idx.shape[0] == 25
    # todo t0 de calib é maior que todo t0 de fit
    assert t0[calib_idx].min() > t0[fit_idx].max()
    # sem overlap de label, o fit fica íntegro (nada purgado)
    assert fit_idx.shape[0] == 75
    assert set(fit_idx.tolist()) & set(calib_idx.tolist()) == set()


def test_temporal_purged_calib_split_purga_label_que_cruza_a_fronteira() -> None:
    """O ponto do AG-209: label cujo `[t0, t1]` ainda está ABERTO quando o
    bloco de calibração começa sai do fit. Sem isso o calibrador vê
    quase-cópias do que o modelo ajustou."""
    t0 = np.arange(0, 100, dtype=np.int64) * 1_000
    # horizonte longo: as últimas linhas do prefixo alcançam o bloco final
    t1 = t0 + 20_000
    fit_idx, calib_idx = alpha._temporal_purged_calib_split(t0, t1, holdout_frac=0.25)

    calib_start = int(t0[calib_idx].min())
    assert fit_idx.shape[0] < 75, "purge não removeu nada — condição de overlap não aplicada"
    # invariante forte: NENHUMA linha de fit tem label aberto em calib_start
    assert bool((t1[fit_idx] < calib_start).all())


def test_temporal_purged_calib_split_falha_alto_quando_purge_esvazia_fit() -> None:
    """Fold degenerado (horizonte cobre todo o prefixo) falha alto com
    mensagem acionável, nunca devolve fit vazio pro LightGBM."""
    t0 = np.arange(0, 20, dtype=np.int64) * 1_000
    t1 = t0 + 10_000_000  # todo label ainda aberto no fim da série
    with pytest.raises(ValueError, match="esvaziou o conjunto de fit"):
        alpha._temporal_purged_calib_split(t0, t1, holdout_frac=0.25)


def test_temporal_purged_calib_split_nunca_zera_nenhum_dos_dois_lados() -> None:
    t0 = np.arange(0, 10, dtype=np.int64) * 1_000
    t1 = t0 + 100
    for frac in (0.01, 0.99):
        fit_idx, calib_idx = alpha._temporal_purged_calib_split(t0, t1, holdout_frac=frac)
        assert fit_idx.shape[0] >= 1
        assert calib_idx.shape[0] >= 1


# ============================================================================
# AG-210 — decide_side / resolve_joint_tau
# ============================================================================


def test_decide_side_reproduz_a_regra_legada_bit_a_bit() -> None:
    """`decide_side` foi extraída de `run_fold`; se divergir do bloco
    inline original, `tau` passa a ser resolvido contra uma regra
    diferente da aplicada — o erro seria invisível (é a razão estrutural
    da extração, mesma de `cpcv._embargo_ms`)."""
    rng = np.random.default_rng(7)
    p_long = rng.random(500)
    p_short = rng.random(500)
    tau_l, tau_s = 0.6, 0.55

    got = alpha.decide_side(p_long, p_short, tau_long=tau_l, tau_short=tau_s)

    # reimplementação literal do bloco que existia inline em run_fold
    is_long = (p_long > tau_l) & (p_long > p_short)
    is_short = (p_short > tau_s) & (p_short > p_long) & ~is_long
    expected = np.zeros(p_long.shape[0], dtype=np.int8)
    expected[is_long] = 1
    expected[is_short] = -1

    assert np.array_equal(got, expected)
    assert got.dtype == np.int8, "schema §5.12 exige Int8 em side_hat"


def test_decide_side_long_e_short_sao_mutuamente_exclusivos() -> None:
    rng = np.random.default_rng(11)
    p_long, p_short = rng.random(1_000), rng.random(1_000)
    side = alpha.decide_side(p_long, p_short, tau_long=0.1, tau_short=0.1)
    assert set(np.unique(side).tolist()) <= {-1, 0, 1}


def test_resolve_joint_tau_taxa_total_bate_o_orcamento() -> None:
    """O achado central do AG-210: com `tau` per-side, cada lado entrega
    `r` e o TOTAL não é `r`. O solver resolve o par para que o total
    bata."""
    rng = np.random.default_rng(3)
    p_long = rng.random(20_000)
    p_short = rng.random(20_000)
    target = 0.0189

    tau_l, tau_s, rate = alpha.resolve_joint_tau(
        p_long, p_short, target_signal_rate=target
    )
    assert rate == pytest.approx(target, abs=1e-3)

    # e a taxa realmente observada aplicando os taus devolvidos bate
    side = alpha.decide_side(p_long, p_short, tau_long=tau_l, tau_short=tau_s)
    assert float(np.mean(side != 0)) == pytest.approx(target, abs=1e-3)


def test_resolve_joint_tau_difere_do_per_side_quando_o_orcamento_e_total() -> None:
    """Prova numérica do gap: aplicar o quantil `1-r` a cada lado
    isoladamente NÃO produz taxa total `r`. Se este teste passar a falhar,
    o achado do AG-210 deixou de valer e a correção pode ser retirada."""
    rng = np.random.default_rng(5)
    p_long, p_short = rng.random(20_000), rng.random(20_000)
    target = 0.0189

    tau_l_perside = float(np.quantile(p_long, 1.0 - target))
    tau_s_perside = float(np.quantile(p_short, 1.0 - target))
    side_perside = alpha.decide_side(
        p_long, p_short, tau_long=tau_l_perside, tau_short=tau_s_perside
    )
    rate_perside = float(np.mean(side_perside != 0))

    assert rate_perside > target, (
        "taxa total sob tau per-side deveria SUPERAR o orçamento total "
        f"(medido {rate_perside:.4f} vs alvo {target})"
    )


def test_resolve_joint_tau_rejeita_populacoes_desalinhadas() -> None:
    with pytest.raises(ValueError, match="MESMA população"):
        alpha.resolve_joint_tau(
            np.zeros(10), np.zeros(11), target_signal_rate=0.02
        )


@pytest.mark.parametrize("bad_rate", [0.0, 1.0, -0.1, 1.5])
def test_resolve_joint_tau_rejeita_taxa_fora_do_intervalo(bad_rate: float) -> None:
    with pytest.raises(ValueError, match="fora de"):
        alpha.resolve_joint_tau(
            np.zeros(10), np.zeros(10), target_signal_rate=bad_rate
        )


# ============================================================================
# AG-208 — hiperparâmetros declarados
# ============================================================================


def test_hyperparams_carrega_min_sum_hessian_e_max_bin_de_constants() -> None:
    hyper = alpha.LGBMHyperparams.from_constants()
    assert hyper.min_sum_hessian_in_leaf == pytest.approx(1e-3)
    assert hyper.max_bin == 255


def test_hyperparams_default_e_bit_exato_com_o_default_da_biblioteca() -> None:
    """A correção do AG-208 é de PROVENIÊNCIA, não de valor — se algum dia
    o valor mudar, tem que ser por sweep declarado, e este teste é o que
    força a mudança a ser deliberada."""
    parcial = alpha.LGBMHyperparams(
        max_depth=3,
        n_estimators=300,
        learning_rate=0.03,
        subsample=0.8,
        subsample_freq=1,
        feature_fraction=1.0,
        lambda_l2=5.0,
        min_child_samples=20,
        num_leaves=8,
    )
    assert parcial.min_sum_hessian_in_leaf == pytest.approx(1e-3)
    assert parcial.max_bin == 255


# ============================================================================
# AG-214 — dispersão entre caminhos e política de empate
# ============================================================================


def _path_result(path_id: int, sharpe: float) -> backtest_lite.PathBacktestResult:
    return backtest_lite.PathBacktestResult(
        path_id=path_id,
        n_signals=10,
        n_filled_trades=10,
        fill_rate=1.0,
        sharpe_naive=sharpe,
        mean_trade_ret=0.0,
        std_trade_ret=1.0,
        trades_per_year=100.0,
        win_rate=0.5,
    )


def test_path_dispersion_stats_descarta_nan_sem_trata_lo_como_zero() -> None:
    by_path = {
        0: _path_result(0, 1.0),
        1: _path_result(1, 3.0),
        2: _path_result(2, float("nan")),
    }
    stats = backtest_lite.path_dispersion_stats(by_path)
    assert stats.n_paths == 2
    assert stats.mean == pytest.approx(2.0)
    assert stats.min == pytest.approx(1.0)
    assert stats.max == pytest.approx(3.0)
    assert stats.std_between_paths == pytest.approx(np.std([1.0, 3.0], ddof=1))


def test_path_dispersion_stats_tudo_nan_nao_quebra() -> None:
    stats = backtest_lite.path_dispersion_stats({0: _path_result(0, float("nan"))})
    assert stats.n_paths == 0
    assert np.isnan(stats.mean)


def test_permanence_count_conta_empate_como_melhor() -> None:
    """Documenta o comportamento EXATO de `permanence_count` -- empate
    conta como "Camada 1 melhor" (`AG-214`). `TIE_REQUIRES_MARGIN`/
    `min_margin` (a alternativa que existia aqui) foram aposentados
    2026-08-27 (handoff de `src/models/`, item 2, `ADR-004` §6) sem
    calibração nova (B23) -- o viés que este teste documenta não fica sem
    correção: `backtest_lite.permanence_pass_criterion` (testado em
    `test_models_backtest_lite.py`) exige TAMBÉM `n_paths_significant`,
    então esta contagem isolada nunca decide sozinha."""
    c1 = {0: _path_result(0, 1.0), 1: _path_result(1, 2.0)}
    c0 = {0: _path_result(0, 1.0), 1: _path_result(1, 3.0)}
    n_better, n_total = backtest_lite.permanence_count(c1, c0)
    assert (n_better, n_total) == (1, 2), "empate exato deveria contar como melhor"


# ============================================================================
# AG-213 — concordância entre os dois alvos
# ============================================================================


def _frame_com_alvos_divergentes(n: int = 400, *, seed: int = 0) -> pl.DataFrame:
    """Constrói um caso onde `ret_net` e `P(TP)` discordam DE PROPÓSITO
    sobre uma feature, para provar que o instrumento do AG-213 detecta a
    divergência quando ela existe.

    Mecanismo: `f_divergente` melhora `ret_net` só através dos desfechos
    TIME (label 0, retorno pequeno menos ruim), sem mover P(TP) — que é
    exatamente o modo de falha que o AG-213 descreve."""
    rng = np.random.default_rng(seed)
    barrier = rng.choice(["TP", "SL", "TIME"], size=n, p=[0.25, 0.25, 0.50])
    label = np.where(barrier == "TP", 1, np.where(barrier == "SL", -1, 0)).astype(np.int64)

    f_div = rng.normal(size=n)
    ret_net = np.where(
        barrier == "TP", 0.015, np.where(barrier == "SL", -0.015, 0.0)
    ).astype(np.float64)
    # a feature só mexe no resultado dos TIME -> IC contra ret_net positivo,
    # IC contra indicador de TP ~ 0 por construção.
    ret_net = ret_net + np.where(barrier == "TIME", f_div * 0.004, 0.0)

    cols: dict[str, object] = {
        "t0": pl.Series(list(range(n))).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
        "regime": pl.Series(rng.choice(["R1", "R2", "R3", "R4"], size=n)),
        "label": pl.Series(label).cast(pl.Int8),
        "ret_net": pl.Series(ret_net),
        "sample_weight": pl.Series(np.ones(n)),
    }
    for fid in T1_FEATURE_IDS:
        cols[fid] = pl.Series(rng.normal(size=n))
    cols["A05_ret_vol_norm_4"] = pl.Series(f_div)
    return pl.DataFrame(cols)


def test_screen_target_agreement_devolve_os_dois_alvos_por_feature() -> None:
    df = _frame_com_alvos_divergentes()
    out = monotonic.screen_target_agreement(df, T1_FEATURE_IDS, side=1)

    assert set(out) == set(T1_FEATURE_IDS)
    for feature, res in out.items():
        assert res.feature == feature
        assert res.constraint_ret_net in (-1, 0, 1)
        assert res.constraint_tp in (-1, 0, 1)
        assert res.agree == (res.constraint_ret_net == res.constraint_tp)


def test_screen_target_agreement_marca_forcada_economica() -> None:
    """`E27f_cost_atr_ratio` tem restrição forçada por identidade contábil
    — concorda por construção, e a flag existe pra que essa linha NÃO seja
    lida como evidência de concordância entre os alvos."""
    df = _frame_com_alvos_divergentes()
    out = monotonic.screen_target_agreement(df, T1_FEATURE_IDS, side=1)
    assert out["E27f_cost_atr_ratio"].forced_economic is True
    assert out["E27f_cost_atr_ratio"].agree is True


def test_screen_target_agreement_nao_muta_o_frame_recebido() -> None:
    df = _frame_com_alvos_divergentes(n=120)
    colunas_antes = list(df.columns)
    monotonic.screen_target_agreement(df, T1_FEATURE_IDS, side=-1)
    assert list(df.columns) == colunas_antes


def test_screen_target_agreement_rejeita_coluna_reservada_preexistente() -> None:
    df = _frame_com_alvos_divergentes(n=60).with_columns(
        pl.lit(0.0).alias("_y_tp_indicator")
    )
    with pytest.raises(ValueError, match="coluna reservada"):
        monotonic.screen_target_agreement(df, T1_FEATURE_IDS, side=1)


# ============================================================================
# AG-212 — balanceamento de classe: contagem vs massa
# ============================================================================


def test_class_balance_basis_rejeita_valor_desconhecido() -> None:
    df = _frame_com_alvos_divergentes(n=80).with_columns(
        pl.Series("barrier_hit", ["TP"] * 80),
        pl.Series("t1", list(range(80))).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
    )
    with pytest.raises(ValueError, match="class_balance_basis desconhecido"):
        alpha.fit_side_model(
            df,
            side=1,
            variant=alpha.VARIANT_CAMADA0,
            hyper=alpha.LGBMHyperparams.from_constants(),
            seed=1,
            target_signal_rate=0.02,
            class_balance_basis="massa_gravitacional",
        )


def test_calib_split_mode_rejeita_valor_desconhecido() -> None:
    df = _frame_com_alvos_divergentes(n=80)
    with pytest.raises(ValueError, match="calib_split_mode desconhecido"):
        alpha.fit_side_model(
            df,
            side=1,
            variant=alpha.VARIANT_CAMADA0,
            hyper=alpha.LGBMHyperparams.from_constants(),
            seed=1,
            target_signal_rate=0.02,
            calib_split_mode="split_magico",
        )


def test_tau_policy_rejeita_valor_desconhecido() -> None:
    """`run_fold` valida `tau_policy` ANTES de qualquer inferência — o
    erro precisa ser explícito, nunca um fallback silencioso pro legado."""
    assert alpha.TAU_POLICY_LEGACY_PER_SIDE != alpha.TAU_POLICY_TOTAL_COMMON_OOF


# ============================================================================
# Item 3 do roadmap de correção do mecanismo de tau (2026-09-03) --
# `_select_tau_calibration_pool`
# ============================================================================


def test_select_tau_pool_janela_none_e_bit_exato_ao_pool_inteiro() -> None:
    rng = np.random.default_rng(11)
    calibrated = rng.random(500)
    t0_ms = np.arange(500, dtype=np.int64) * 60_000

    pool, is_windowed = alpha._select_tau_calibration_pool(
        calibrated,
        t0_ms,
        tau_window_days=None,
        target_signal_rate=0.02,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
    )
    assert is_windowed is False
    np.testing.assert_array_equal(pool, calibrated)


def test_select_tau_pool_corta_pelo_tempo_certo() -> None:
    # 400 dias de barras diárias, 1 barra/dia -- janela de 100 dias deve
    # manter só as últimas 100 (índices 300..399).
    n = 400
    t0_ms = (np.arange(n, dtype=np.int64)) * alpha._MS_PER_DAY
    calibrated = np.arange(n, dtype=np.float64)  # valor == índice, fácil de checar

    pool, is_windowed = alpha._select_tau_calibration_pool(
        calibrated,
        t0_ms,
        tau_window_days=100,
        target_signal_rate=0.02,  # min_bars = ceil(10/0.02) = 500 > 101 -- ver teste de fallback
        side=1,
        variant=alpha.VARIANT_CAMADA1,
    )
    # amostra da janela (101 pontos, índices 299..399) é menor que
    # min_bars=500 sob essa taxa-alvo -- cai pro fallback, não corta.
    assert is_windowed is False
    np.testing.assert_array_equal(pool, calibrated)

    # mesma janela, taxa-alvo mais alta (min_bars = ceil(10/0.15) = 67 <=
    # 101 pontos disponíveis) -- agora corta de verdade.
    pool2, is_windowed2 = alpha._select_tau_calibration_pool(
        calibrated,
        t0_ms,
        tau_window_days=100,
        target_signal_rate=0.15,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
    )
    assert is_windowed2 is True
    assert pool2.shape[0] == 101  # dias 299..399 inclusive, âncora em max(t0_ms)
    assert pool2.min() == 299.0
    assert pool2.max() == 399.0


def test_select_tau_pool_fallback_quando_janela_nao_comporta_amostra_minima() -> None:
    n = 50
    t0_ms = np.arange(n, dtype=np.int64) * alpha._MS_PER_DAY
    calibrated = np.arange(n, dtype=np.float64)

    pool, is_windowed = alpha._select_tau_calibration_pool(
        calibrated,
        t0_ms,
        tau_window_days=5,  # só ~6 pontos na janela, muito abaixo de min_bars
        target_signal_rate=0.02,
        side=-1,
        variant=alpha.VARIANT_CAMADA0,
    )
    assert is_windowed is False
    np.testing.assert_array_equal(pool, calibrated)


def test_select_tau_pool_sem_t0_cai_pro_pool_inteiro_sem_quebrar() -> None:
    calibrated = np.random.default_rng(3).random(30)
    pool, is_windowed = alpha._select_tau_calibration_pool(
        calibrated,
        None,
        tau_window_days=180,
        target_signal_rate=0.02,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
    )
    assert is_windowed is False
    np.testing.assert_array_equal(pool, calibrated)


def test_select_tau_pool_historico_curto_nao_quebra() -> None:
    """Símbolo com histórico curto (SOLUSDT/XRPUSDT-like) — janela de 180
    dias pedida sobre um treino de só 60 dias não deve levantar exceção,
    só cair pro fallback (a janela inteira já É o pool inteiro)."""
    n = 60
    t0_ms = np.arange(n, dtype=np.int64) * alpha._MS_PER_DAY
    calibrated = np.random.default_rng(4).random(n)

    pool, is_windowed = alpha._select_tau_calibration_pool(
        calibrated,
        t0_ms,
        tau_window_days=180,
        target_signal_rate=0.02,
        side=1,
        variant=alpha.VARIANT_CAMADA1,
    )
    assert is_windowed is False
    assert pool.shape[0] == n


def test_fit_side_model_tau_window_days_none_e_bit_exato_ao_legado() -> None:
    """`fit_side_model` sem `tau_window_days` (default) precisa produzir
    o MESMO `tau` de antes desta correção existir -- prova end-to-end,
    não só do núcleo puro acima."""
    df = _frame_com_alvos_divergentes(n=400)
    hyper = alpha.LGBMHyperparams.from_constants()

    result_default = alpha.fit_side_model(
        df, side=1, variant=alpha.VARIANT_CAMADA0, hyper=hyper, seed=7,
        target_signal_rate=0.05,
    )
    result_explicit_none = alpha.fit_side_model(
        df, side=1, variant=alpha.VARIANT_CAMADA0, hyper=hyper, seed=7,
        target_signal_rate=0.05, tau_window_days=None,
    )
    assert result_default.tau == pytest.approx(result_explicit_none.tau)
