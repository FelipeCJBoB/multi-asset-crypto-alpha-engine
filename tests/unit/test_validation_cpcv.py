"""Testes de `src/validation/cpcv.py` — splitter combinatório real, purge
por `t1`, embargo, e 1-fatoração de caminhos de backtest.

`_make_synthetic_labels` cobre a mecânica com dados pequenos e controlados
(fronteiras de grupo conhecidas de antemão). Os testes contra
`labels/v1/labels.parquet` REAL (462.682 linhas, Sprint 6) ficam na seção
final — são o teste 6 do §11.5 (contaminação de label) rodando de verdade,
não só sobre sintético."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.data.resample import step_ms
from src.validation import cpcv
from src.validation._paths import labels_symbol_tf_dir

_BAR_MS = 900_000  # 15m


def _make_synthetic_labels(
    n: int, *, side: int = 1, horizon_bars: int = 4, start_ms: int = 0, bar_ms: int = _BAR_MS
) -> pl.DataFrame:
    """`n` labels sintéticos com `t0` em barras CONSECUTIVAS espaçadas de
    `bar_ms` (default 15m) e `t1 = t0 + horizon_bars * bar_ms` (horizonte
    fixo, análogo a um `time_stop_bars` pequeno) — o suficiente para
    exercitar purge/embargo sem precisar do dataset real.

    `bar_ms` (AG-009) — antes desta correção o espaçamento era sempre
    `_BAR_MS` (15m) independente do `tf` de um `CPCVConfig` associado,
    truque usado pelos testes AG-004 originais para simular um "TF
    diferente" sem reescrever a fixture. Isso agora colide de propósito
    com `assert_tf_consistent` (a própria guarda AG-009 que esta rodada
    adiciona) — dado espaçado em 15m analisado com `config.tf="30m"` é
    EXATAMENTE o cenário que a guarda existe para rejeitar. `bar_ms`
    deixa o chamador declarar um espaçamento que bate de verdade com o
    `tf` do `CPCVConfig` usado no teste."""
    t0_ms = [start_ms + i * bar_ms for i in range(n)]
    t1_ms = [t + horizon_bars * bar_ms for t in t0_ms]
    return pl.DataFrame(
        {
            "t0": pl.Series(t0_ms).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "t1": pl.Series(t1_ms).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "side": pl.Series([side] * n, dtype=pl.Int8),
            "sample_weight": pl.Series([1.0] * n, dtype=pl.Float64),
        }
    )


_CFG = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=2)


# ============================================================================
# CPCVConfig
# ============================================================================


def test_config_n_splits_e_n_backtest_paths_batem_com_o_prd() -> None:
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=175)
    assert cfg.n_splits == 15  # C(6,2), §11.4
    assert cfg.n_backtest_paths == 5  # C(5,1), §11.4


def test_config_rejeita_n_test_groups_invalido() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.CPCVConfig(n_groups=6, n_test_groups=0, embargo_bars=1)
    with pytest.raises(cpcv.CPCVError):
        cpcv.CPCVConfig(n_groups=6, n_test_groups=6, embargo_bars=1)


def test_config_rejeita_embargo_negativo() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=-1)


def test_config_from_constants_le_constants_yaml() -> None:
    cfg = cpcv.CPCVConfig.from_constants()
    assert cfg.n_groups == 6
    assert cfg.n_test_groups == 2
    assert cfg.embargo_bars == 175


# ============================================================================
# AG-004 — tf deixa de ser _BAR_MS hardcoded em 15m
# ============================================================================


def test_config_tf_default_e_15m_bit_exato() -> None:
    """Todo caller existente no repo constrói CPCVConfig sem `tf` — o
    default precisa preservar exatamente o comportamento de antes da
    correção AG-004 (_BAR_MS fixo em step_ms("15m"))."""
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=2)
    assert cfg.tf == "15m"

    cfg_from_constants = cpcv.CPCVConfig.from_constants()
    assert cfg_from_constants.tf == "15m"


def test_config_rejeita_tf_desconhecido() -> None:
    from src.data.resample import UnsupportedTimeframeError

    with pytest.raises(UnsupportedTimeframeError):
        cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=2, tf="7m")


def test_embargo_ms_escala_com_tf_nao_fica_preso_em_15m() -> None:
    """O achado real de AG-004: embargo em 30m tinha que ser 2x o de 15m
    pro MESMO embargo_bars, porque cada barra de 30m cobre o dobro do
    tempo. Antes da correção, os dois davam o mesmo embargo_ms (bug
    silencioso) porque _BAR_MS estava fixo em 15m independente de `tf`.

    Reescrito nesta rodada (AG-009) para testar `cpcv._embargo_ms`
    diretamente — a função pura extraída de `generate_splits`/
    `assert_embargo_respected` — em vez de rodar `generate_splits`
    ponta-a-ponta sobre um `labels` sintético deliberadamente espaçado em
    15m mas reclamado como `tf="30m"`. Essa combinação (dado de um TF,
    config de outro) é EXATAMENTE o que a guarda `assert_tf_consistent`
    (AG-009, roda sempre dentro de `generate_splits`) agora rejeita por
    design — não é mais um jeito válido de simular "escala com tf" via
    `generate_splits`. Testar `_embargo_ms` isoladamente é estritamente
    mais preciso: nenhuma interação com purge/embargo_mask/boundary de
    grupo a considerar, só a aritmética `embargo_bars * step_ms(tf)` que
    é o que AG-004 corrigiu."""
    cfg_15m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=4, tf="15m")
    cfg_30m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=4, tf="30m")

    embargo_ms_15m = cpcv._embargo_ms(cfg_15m)
    embargo_ms_30m = cpcv._embargo_ms(cfg_30m)

    assert embargo_ms_15m == 4 * step_ms("15m")
    assert embargo_ms_30m == 2 * embargo_ms_15m, (
        "embargo em 30m precisa cobrir EXATAMENTE 2x o tempo (ms) do de 15m para o "
        f"mesmo embargo_bars ({embargo_ms_30m} vs {embargo_ms_15m})"
    )


def test_generate_splits_e_assert_embargo_respected_usam_o_mesmo_embargo_ms(
) -> None:
    """`generate_splits` (que aplica o embargo) e `assert_embargo_respected`
    (que checa que ele foi respeitado) precisam calcular embargo_ms a
    partir do MESMO `config.tf` -- senão a própria checagem (que deveria
    pegar violação) ficaria calibrada pro TF errado e passaria
    silenciosamente. Os dois agora chamam literalmente `_embargo_ms`
    (extraído nesta rodada, AG-009) em vez de duas cópias inline da mesma
    fórmula -- este teste roda o caminho real com `tf="30m"` e dado
    sintético genuinamente espaçado em 30m (`bar_ms=step_ms("30m")`, não
    mais o truque de reclamar 30m sobre dado de 15m, que colidiria com a
    guarda `assert_tf_consistent`)."""
    n = 600
    labels = _make_synthetic_labels(n, horizon_bars=1, bar_ms=step_ms("30m"))
    cfg_30m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=4, tf="30m")
    result = cpcv.generate_splits(labels, cfg_30m)
    assert sum(s.n_embargoed for s in result.splits) > 0
    cpcv.assert_embargo_respected(labels, result)  # não deve levantar


# ============================================================================
# AG-009 — assert_tf_consistent: guarda cruzada entre `tf` de `labels` e
# `CPCVConfig.tf`. `load_labels_v1(tf=...)` e `CPCVConfig(tf=...)` são dois
# parâmetros independentes hoje (nenhuma ligação estrutural entre os dois) --
# esta guarda mede o espaçamento REAL de `t0` contra `step_ms(config.tf)` e
# falha alto se divergirem, em vez de computar o embargo na unidade errada
# silenciosamente.
# ============================================================================


def test_assert_tf_consistent_aceita_default_15m_bit_exato() -> None:
    """Caso consistente -- dado sintético espaçado em 15m (`_BAR_MS`, o
    default de `_make_synthetic_labels`) contra `CPCVConfig` default
    (`tf="15m"`) não deve levantar, e `generate_splits` continua
    produzindo exatamente os mesmos 15 splits/5 caminhos de sempre -- a
    guarda é read-only (não muda `t0_ms`/`t1_ms`/grupos/purge/embargo),
    então bit-exatidão do resultado segue por construção, não por
    coincidência de teste."""
    labels = _make_synthetic_labels(600, horizon_bars=1)
    cpcv.assert_tf_consistent(labels, _CFG)  # não deve levantar

    result = cpcv.generate_splits(labels, _CFG)
    assert len(result.splits) == 15
    assert result.config.n_backtest_paths == 5


def test_assert_tf_consistent_aceita_tf_explicito_consistente() -> None:
    """Não é só o default 15m -- qualquer `tf` suportado cujo dado bata
    com o espaçamento declarado passa."""
    labels = _make_synthetic_labels(600, horizon_bars=1, bar_ms=step_ms("30m"))
    cfg_30m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=2, tf="30m")
    cpcv.assert_tf_consistent(labels, cfg_30m)  # não deve levantar


def test_assert_tf_consistent_rejeita_tf_divergente_15m_vs_30m() -> None:
    """O footgun real do AG-009, reproduzido sem precisar do dataset real:
    `labels` espaçado em 30m (como `load_labels_v1(tf="30m")` produziria)
    combinado com um `CPCVConfig` no default `tf="15m"` (como
    `CPCVConfig.from_constants()` sem `tf` explícito) -- os dois lados
    nunca eram checados um contra o outro antes desta correção."""
    labels = _make_synthetic_labels(600, horizon_bars=1, bar_ms=step_ms("30m"))
    cfg_15m_default = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=2)
    with pytest.raises(cpcv.CPCVError, match="AG-009"):
        cpcv.assert_tf_consistent(labels, cfg_15m_default)


def test_assert_tf_consistent_rejeita_tf_divergente_15m_vs_1h() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)  # 15m (default bar_ms)
    cfg_1h = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=2, tf="1h")
    with pytest.raises(cpcv.CPCVError, match="AG-009"):
        cpcv.assert_tf_consistent(labels, cfg_1h)


def test_assert_tf_consistent_tolera_gaps_minoritarios_na_mediana() -> None:
    """Dado real tem gaps ocasionais (ver `known_gaps`, docstring do
    módulo) -- a guarda usa a MEDIANA do diff entre `t0` consecutivos, não
    o mínimo nem uniformidade estrita, então uma MINORIA de barras
    faltando não pode disparar falso positivo. Simulado removendo ~5% das
    linhas de um grid de 15m antes de checar contra `tf="15m"`."""
    n = 600
    labels = _make_synthetic_labels(n, horizon_bars=1)
    rng = np.random.default_rng(42)
    drop_idx = rng.choice(n, size=n // 20, replace=False)  # noqa: magic-number -- ~5%
    keep_mask = np.ones(n, dtype=bool)
    keep_mask[drop_idx] = False
    labels_com_gaps = labels.filter(pl.Series(keep_mask))
    cpcv.assert_tf_consistent(labels_com_gaps, _CFG)  # não deve levantar


def test_assert_tf_consistent_instancia_unica_nao_levanta() -> None:
    """Sem pelo menos 2 `t0` distintos não há diff pra medir -- a guarda
    não levanta neste caso degenerado (deixa `assign_time_groups`, chamada
    logo depois dentro de `generate_splits`, levantar seu próprio erro
    mais específico de 'instante único não particionável')."""
    labels = _make_synthetic_labels(1, horizon_bars=1)
    cpcv.assert_tf_consistent(labels, _CFG)  # não deve levantar


def test_generate_splits_rejeita_tf_inconsistente_sem_opt_out() -> None:
    """A guarda roda DENTRO de `generate_splits`, sempre, sem opt-out
    (decisão AG-009) -- não só disponível como função separada que o
    caller precisa lembrar de invocar. Prova que a combinação
    `load_labels_v1(tf="30m")` + `CPCVConfig.from_constants()` (default
    `tf="15m"`) descrita no achado é pega automaticamente, não só
    detectável manualmente."""
    labels = _make_synthetic_labels(600, horizon_bars=1, bar_ms=step_ms("30m"))
    cfg_15m_default = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=2)
    with pytest.raises(cpcv.CPCVError, match="AG-009"):
        cpcv.generate_splits(labels, cfg_15m_default)


# ============================================================================
# assign_time_groups — partição cronológica
# ============================================================================


def test_assign_time_groups_particiona_em_blocos_iguais() -> None:
    n = 600
    t0_ms = np.arange(n, dtype=np.int64) * _BAR_MS
    group_id, edges_ms = cpcv.assign_time_groups(t0_ms, 6)
    assert group_id.shape[0] == n
    assert set(np.unique(group_id).tolist()) == {0, 1, 2, 3, 4, 5}
    assert edges_ms.shape[0] == 7
    # cada grupo cronológico tem ~ o mesmo tamanho (tolerância de 1 bucket)
    counts = np.bincount(group_id, minlength=6)
    assert counts.max() - counts.min() <= 1


def test_assign_time_groups_cobre_o_maximo_no_ultimo_grupo() -> None:
    t0_ms = np.array([0, 100, 200, 300, 400, 500], dtype=np.int64)
    group_id, _ = cpcv.assign_time_groups(t0_ms, 3)
    assert group_id[-1] == 2  # o próprio máximo cai no último grupo, não "fora"


def test_assign_time_groups_vazio_levanta_erro() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.assign_time_groups(np.array([], dtype=np.int64), 6)


def test_assign_time_groups_instante_unico_levanta_erro() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.assign_time_groups(np.array([100, 100, 100], dtype=np.int64), 3)


# ============================================================================
# 1-fatoração de K_n — n_backtest_paths
# ============================================================================


def test_1_fatoracao_k6_cobre_todos_os_15_pares_exatamente_uma_vez() -> None:
    rounds = cpcv._round_robin_1_factorization(6)
    assert len(rounds) == 5
    all_pairs: list[tuple[int, int]] = []
    for pairs in rounds:
        assert len(pairs) == 3  # 6 grupos / 2 por par
        covered = {g for pair in pairs for g in pair}
        assert covered == {0, 1, 2, 3, 4, 5}  # cada rodada cobre todos os grupos 1x
        all_pairs.extend(pairs)
    assert len(all_pairs) == 15
    assert len(set(all_pairs)) == 15  # todos distintos — nenhum par repetido entre rodadas
    from itertools import combinations

    assert set(all_pairs) == set(combinations(range(6), 2))


def test_1_fatoracao_rejeita_n_impar_ou_menor_que_2() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv._round_robin_1_factorization(5)
    with pytest.raises(cpcv.CPCVError):
        cpcv._round_robin_1_factorization(0)


def test_path_assignment_e_consistente_com_generate_splits() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    # cada path cobre os 6 grupos de teste exatamente uma vez, batendo com a
    # verificação de generate_splits contra dado real (test_validation_cpcv real, abaixo)
    coverage: dict[int, set[int]] = {}
    for s in result.splits:
        coverage.setdefault(s.path_id, set()).update(s.test_groups)
    assert len(coverage) == 5
    for groups in coverage.values():
        assert groups == {0, 1, 2, 3, 4, 5}


# ============================================================================
# generate_splits — mecânica de purge/embargo com fronteiras controladas
# ============================================================================


def test_generate_splits_produz_15_splits_para_6_grupos_2_teste() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    assert len(result.splits) == 15
    assert {s.split_id for s in result.splits} == set(range(15))


def test_generate_splits_test_idx_e_train_idx_nunca_se_intersectam() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=3)
    result = cpcv.generate_splits(labels, _CFG)
    for s in result.splits:
        assert np.intersect1d(s.train_idx, s.test_idx).size == 0


def test_generate_splits_test_idx_e_exatamente_os_grupos_de_teste() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    for s in result.splits:
        test_groups_observed = set(result.group_id[s.test_idx].tolist())
        assert test_groups_observed <= set(s.test_groups)


def test_generate_splits_purge_remove_overlap_na_borda() -> None:
    """Horizonte de label deliberadamente GRANDE (20 barras) pra forçar
    overlap real entre um label de treino perto da borda de um grupo e o
    grupo de teste seguinte — prova que `n_purged > 0` quando o cenário
    exige, não só que o splitter roda sem erro."""
    n = 1200  # 6 grupos de 200 barras cada
    labels = _make_synthetic_labels(n, horizon_bars=20)
    cfg_sem_embargo = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=0)
    result = cpcv.generate_splits(labels, cfg_sem_embargo)

    total_purged = sum(s.n_purged for s in result.splits)
    assert total_purged > 0


def test_generate_splits_purge_cresce_com_horizonte_do_label() -> None:
    """Horizonte de label maior tem que produzir >= purge que um horizonte
    menor, split a split — prova que o purge usa o `t1` REAL de cada linha
    (item 2 da docstring do módulo), não uma margem fixa desacoplada do
    horizonte. Não assume purge==0 para horizonte pequeno: como as
    fronteiras de grupo são cronológicas (`assign_time_groups`, partição
    por tempo) e não alinhadas à grade de barras, mesmo um horizonte de 1
    barra pode cruzar uma fronteira que caia no meio dela — comportamento
    correto do AFML (purge por t1 exato), não um bug."""
    n = 1200
    cfg_sem_embargo = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=0)
    labels_curto = _make_synthetic_labels(n, horizon_bars=1)
    labels_longo = _make_synthetic_labels(n, horizon_bars=20)
    result_curto = cpcv.generate_splits(labels_curto, cfg_sem_embargo)
    result_longo = cpcv.generate_splits(labels_longo, cfg_sem_embargo)

    for s_curto, s_longo in zip(result_curto.splits, result_longo.splits, strict=True):
        assert s_longo.n_purged >= s_curto.n_purged

    total_curto = sum(s.n_purged for s in result_curto.splits)
    total_longo = sum(s.n_purged for s in result_longo.splits)
    assert total_longo > total_curto


def test_generate_splits_purge_cobre_lookback_de_feature_de_treino_apos_g_end() -> None:
    """AG-032/E4 — critério de aceite explícito (item 2b da docstring do
    módulo). 'Purge usa o t1 real do teste' fecha o componente 32
    (horizonte do LABEL de teste esticando pra FRENTE, além de `g_end`) —
    mas isso sozinho NÃO cobre o componente 96 (janela de LOOKBACK de uma
    feature de TREINO, ex. `feature_c06_vol_ratio_long_window`, esticando
    pra TRÁS através de `g_end`, pra dentro do território de teste). São
    duas direções mecanicamente diferentes da mesma cegueira de fronteira.

    Isola SÓ o componente 96: toda a base usa `horizon_bars=1` (label
    curtíssimo — nenhum `t1`, nem de teste nem de treino, chega perto de
    cruzar fronteira nenhuma sozinho), então qualquer purge observado aqui
    só pode vir do parâmetro novo, não de overlap de label.

    Prova as duas metades do critério de aceite: (a) com
    `max_feature_lookback_ms=0` (default, comportamento de sempre), uma
    linha de treino no "vão" logo após `g_end` sobrevive no treino — prova
    que o componente 96 NÃO é pego sem o parâmetro; (b) com
    `max_feature_lookback_ms` cobrindo o vão, a MESMA linha é purgada."""
    n = 400  # 4 grupos de ~100 barras cada
    base = _make_synthetic_labels(n, horizon_bars=1)
    cfg_probe = cpcv.CPCVConfig(n_groups=4, n_test_groups=2, embargo_bars=0)
    t0_ms_base = base["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    _, edges_ms = cpcv.assign_time_groups(t0_ms_base, cfg_probe.n_groups)
    g1_end = int(edges_ms[2]) - 1  # borda direita do grupo 1 (fronteira exclusiva)

    # Linha extra R: t0 dez barras DEPOIS de g1_end -- cai no grupo 2
    # (candidato de treino quando test_groups=(0,1)), label curtíssimo
    # (horizon_bars=1, igual à base). offset_bars=10 é deliberadamente
    # generoso: g_end_effective do grupo 1 pode crescer até 1 bar acima de
    # g1_end (a última linha do grupo pode ter t1=t0+1bar ultrapassando a
    # fronteira, mesmo sob horizon=1) -- 10 barras de folga garante R
    # sobrevive em (a) mesmo no pior caso desse efeito de arredondamento.
    offset_bars = 10
    r_t0_ms = g1_end + 1 + offset_bars * _BAR_MS
    r_row = pl.DataFrame(
        {
            "t0": pl.Series([r_t0_ms]).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "t1": pl.Series([r_t0_ms + _BAR_MS])
            .cast(pl.Datetime("ms"))
            .dt.replace_time_zone("UTC"),
            "side": pl.Series([1], dtype=pl.Int8),
            "sample_weight": pl.Series([1.0], dtype=pl.Float64),
        }
    )
    labels = pl.concat([base, r_row])
    r_idx = n  # última linha (R é a única acrescentada após os `n` da base)

    # (a) default -- sem max_feature_lookback_ms, componente 96 não é pego.
    cfg_sem_lookback = cpcv.CPCVConfig(n_groups=4, n_test_groups=2, embargo_bars=0)
    result_sem = cpcv.generate_splits(labels, cfg_sem_lookback)
    split0_sem = result_sem.splits[0]
    assert split0_sem.test_groups == (0, 1), "premissa do teste: 1º split cobre grupos 0+1"
    assert r_idx in split0_sem.train_idx.tolist(), (
        "sem max_feature_lookback_ms, a linha do vão sobrevive no treino -- "
        "comportamento ATUAL, prova que o componente 96 não é pego por padrão"
    )

    # (b) lookback cobrindo o vão (11 barras >= offset_bars+1) -- mesma
    # linha precisa ser purgada agora.
    lookback_ms = (offset_bars + 1) * _BAR_MS
    cfg_com_lookback = cpcv.CPCVConfig(
        n_groups=4, n_test_groups=2, embargo_bars=0, max_feature_lookback_ms=lookback_ms
    )
    result_com = cpcv.generate_splits(labels, cfg_com_lookback)
    split0_com = result_com.splits[0]
    assert split0_com.test_groups == (0, 1)
    assert r_idx not in split0_com.train_idx.tolist(), (
        "com max_feature_lookback_ms cobrindo o vão, a MESMA linha precisa ser "
        "purgada -- prova que o parâmetro fecha o componente 96 (AG-032, "
        "critério de aceite de E4)"
    )
    assert split0_com.n_purged >= split0_sem.n_purged + 1


def test_generate_splits_embargo_remove_bordas_mesmo_sem_overlap_de_t1() -> None:
    n = 1200
    labels = _make_synthetic_labels(n, horizon_bars=1)  # sem overlap de t1
    result = cpcv.generate_splits(labels, _CFG)  # embargo_bars=2
    total_embargoed = sum(s.n_embargoed for s in result.splits)
    assert total_embargoed > 0


def test_generate_splits_embargo_zero_desativa_a_janela() -> None:
    n = 1200
    labels = _make_synthetic_labels(n, horizon_bars=1)
    cfg_sem_embargo = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=0)
    result = cpcv.generate_splits(labels, cfg_sem_embargo)
    assert all(s.n_embargoed == 0 for s in result.splits)


def test_generate_splits_rejeita_n_test_groups_diferente_de_2() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=1, embargo_bars=0)
    with pytest.raises(cpcv.CPCVError):
        cpcv.generate_splits(labels, cfg)


def test_generate_splits_vazio_levanta_erro() -> None:
    empty = _make_synthetic_labels(0)
    with pytest.raises(cpcv.CPCVError):
        cpcv.generate_splits(empty, _CFG)


# ============================================================================
# assert_no_train_t1_leaks_into_test — teste 6 do §11.5, mecânica sintética
# ============================================================================


def test_assert_no_train_t1_leaks_passa_no_caso_normal() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    cpcv.assert_no_train_t1_leaks_into_test(labels, result)  # não deve levantar


def test_assert_no_train_t1_leaks_detecta_vazamento_forjado() -> None:
    """Forja um split com `train_idx` incluindo uma linha cujo `[t0, t1]`
    cai DENTRO do primeiro grupo de teste — prova que a função detecta a
    violação, não só que "passa quando tudo está certo" (o mesmo cuidado já
    tomado em `test_data_resample.py::
    test_assert_no_lookahead_detecta_close_time_futuro_forjado`)."""
    n = 1200
    labels = _make_synthetic_labels(n, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)

    real_split = result.splits[0]
    g0 = real_split.test_groups[0]
    g0_start = int(result.edges_ms[g0])
    # linha cujo t0 cai dentro do grupo de teste g0 -- índice = a própria
    # posição do primeiro elemento do grupo de teste no array
    test_row_idx = int(real_split.test_idx[0])
    assert int(labels["t0"].dt.epoch(time_unit="ms")[test_row_idx]) >= g0_start

    forged_train_idx = np.concatenate([real_split.train_idx, np.array([test_row_idx])])
    forged_split = cpcv.CPCVSplit(
        split_id=real_split.split_id,
        path_id=real_split.path_id,
        test_groups=real_split.test_groups,
        train_groups=real_split.train_groups,
        train_idx=forged_train_idx,
        test_idx=real_split.test_idx,
        n_train_candidate=real_split.n_train_candidate,
        n_purged=real_split.n_purged,
        n_embargoed=real_split.n_embargoed,
    )
    forged_result = cpcv.CPCVResult(
        config=result.config,
        group_id=result.group_id,
        edges_ms=result.edges_ms,
        splits=(forged_split, *result.splits[1:]),
    )
    with pytest.raises(AssertionError):
        cpcv.assert_no_train_t1_leaks_into_test(labels, forged_result)


def test_assert_embargo_respected_passa_no_caso_normal() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    cpcv.assert_embargo_respected(labels, result)  # não deve levantar


# ============================================================================
# summarize_splits
# ============================================================================


def test_summarize_splits_soma_train_test_purge_embargo_bate_com_candidato() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=3)
    result = cpcv.generate_splits(labels, _CFG)
    summary = cpcv.summarize_splits(result)
    assert summary.height == 15
    # n_train + n_purged + n_embargoed == n_train_candidate, para cada split
    check = summary.select(
        (
            pl.col("n_train") + pl.col("n_purged") + pl.col("n_embargoed")
            == pl.col("n_train_candidate")
        ).alias("ok")
    )
    assert bool(check["ok"].all())


# ============================================================================
# load_labels_v1 + dataset REAL (labels/v1/labels.parquet, Sprint 6)
# ============================================================================


def _skip_if_labels_missing() -> None:
    path = labels_symbol_tf_dir("BTCUSDT", "v1") / "labels.parquet"
    if not path.exists():
        pytest.skip(f"{path} ausente — rode o Label Engine (Sprint 6) primeiro")


def test_load_labels_v1_inexistente_levanta_filenotfound() -> None:
    with pytest.raises(FileNotFoundError):
        cpcv.load_labels_v1(version="versao_que_nao_existe_12345")


def test_load_labels_v1_tf_default_preserva_caminho_15m_existente() -> None:
    """`tf` é novo (AG-004) — o default precisa continuar resolvendo pro
    MESMO caminho de sempre (data/labels/{symbol}/15m/{version}/), não um
    caminho novo que quebraria o artefato real já gravado."""
    with pytest.raises(FileNotFoundError) as exc_info:
        cpcv.load_labels_v1(version="versao_que_nao_existe_12345")
    assert "\\15m\\" in str(exc_info.value) or "/15m/" in str(exc_info.value)


def test_load_labels_v1_tf_explicito_muda_o_caminho_resolvido() -> None:
    with pytest.raises(FileNotFoundError) as exc_info:
        cpcv.load_labels_v1(version="versao_que_nao_existe_12345", tf="30m")
    assert "\\30m\\" in str(exc_info.value) or "/30m/" in str(exc_info.value)


@pytest.mark.integration
def test_cpcv_sobre_dataset_real_15_splits_zero_vazamento() -> None:
    """O teste central — §11.5 #6 rodando contra `labels/v1/labels.parquet`
    real (462.682 linhas, ambos os lados, 2020-01→2026-08, Sprint 6), não
    sintético. Confirma: 15 splits, 5 caminhos, e ZERO t1 de treino
    cruzando qualquer janela de teste em qualquer split."""
    _skip_if_labels_missing()
    labels = cpcv.load_labels_v1()
    result = cpcv.generate_splits(labels)

    assert result.config.n_splits == 15
    assert result.config.n_backtest_paths == 5
    assert len(result.splits) == 15

    cpcv.assert_no_train_t1_leaks_into_test(labels, result)
    cpcv.assert_embargo_respected(labels, result)

    summary = cpcv.summarize_splits(result)
    assert summary.height == 15
    # todo split tem treino e teste não-vazios sobre o dataset real
    assert bool((summary["n_train"] > 0).all())
    assert bool((summary["n_test"] > 0).all())
    # teste cobre uma fração razoável do dataset (2 de 6 grupos ~= 1/3)
    total = labels.height
    for row in summary.iter_rows(named=True):
        assert 0.2 < row["n_test"] / total < 0.45


@pytest.mark.integration
def test_cpcv_sobre_dataset_real_grupos_cobrem_series_completa() -> None:
    _skip_if_labels_missing()
    labels = cpcv.load_labels_v1()
    result = cpcv.generate_splits(labels)
    assert set(np.unique(result.group_id).tolist()) == {0, 1, 2, 3, 4, 5}
    # ~1 ano por grupo (§11.4) sobre ~6,6 anos de dataset real
    for g in range(6):
        span_ms = int(result.edges_ms[g + 1]) - int(result.edges_ms[g])
        span_days = span_ms / (24 * 60 * 60 * 1000)  # noqa: magic-number
        assert 300 < span_days < 450  # ~1 ano, com folga


@pytest.mark.integration
def test_cpcv_sobre_dataset_real_purge_e_embargo_sao_pequenos_face_ao_dataset() -> None:
    """`time_stop_bars` (32 barras, 8h) e `embargo_bars` (175 barras,
    ~44h) são desprezíveis frente a grupos de ~1 ano — purge+embargo por
    split não deveria remover mais que uma fração pequena do treino
    candidato."""
    _skip_if_labels_missing()
    labels = cpcv.load_labels_v1()
    result = cpcv.generate_splits(labels)
    summary = cpcv.summarize_splits(result)
    frac_removed = (summary["n_purged"] + summary["n_embargoed"]) / summary["n_train_candidate"]
    assert bool((frac_removed < 0.02).all())  # noqa: magic-number
