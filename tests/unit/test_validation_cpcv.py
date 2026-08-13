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

from src.validation import cpcv
from src.validation._paths import labels_symbol_tf_dir

_BAR_MS = 900_000  # 15m


def _make_synthetic_labels(
    n: int, *, side: int = 1, horizon_bars: int = 4, start_ms: int = 0
) -> pl.DataFrame:
    """`n` labels sintéticos com `t0` em barras de 15m consecutivas e
    `t1 = t0 + horizon_bars * 15m` (horizonte fixo, análogo a um
    `time_stop_bars` pequeno) — o suficiente para exercitar purge/embargo
    sem precisar do dataset real."""
    t0_ms = [start_ms + i * _BAR_MS for i in range(n)]
    t1_ms = [t + horizon_bars * _BAR_MS for t in t0_ms]
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


def test_embargo_escala_com_tf_nao_fica_preso_em_15m() -> None:
    """O achado real de AG-004: embargo em 30m tinha que ser 2x o de 15m
    pro MESMO embargo_bars, porque cada barra de 30m cobre o dobro do
    tempo. Antes da correção, os dois davam o mesmo embargo_ms (bug
    silencioso) porque _BAR_MS estava fixo em 15m independente de `tf`.

    Achado do Agent independente (project_assurance, revisão desta
    correção): a versão anterior deste teste só checava
    `n_embargoed_30m > n_embargoed_15m` — passaria até para uma correção
    parcial (ex. escala 1,3x em vez de 2x). `t0` sintético é espaçado a
    900_000ms fixo independente de `tf`, então a razão exata É
    computável — trava o valor exato, não só a direção."""
    n = 600
    labels = _make_synthetic_labels(n, horizon_bars=1)

    cfg_15m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=4, tf="15m")
    cfg_30m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=4, tf="30m")

    result_15m = cpcv.generate_splits(labels, cfg_15m)
    result_30m = cpcv.generate_splits(labels, cfg_30m)

    n_embargoed_15m = sum(s.n_embargoed for s in result_15m.splits)
    n_embargoed_30m = sum(s.n_embargoed for s in result_30m.splits)

    assert n_embargoed_15m > 0, "fixture precisa gerar embargo>0 em 15m pra este teste valer algo"
    # embargo_ms dobra (30m = 2x step_ms de 15m); t0 sintético é espaçado a
    # 900_000ms fixo (_BAR_MS de teste), logo o número de barras cobertas
    # pela janela de embargo também dobra exatamente -- razão 2,0, não só ">"
    assert n_embargoed_30m == 2 * n_embargoed_15m, (
        f"embargo em 30m precisa cobrir EXATAMENTE 2x as linhas de 15m para o "
        f"mesmo embargo_bars ({n_embargoed_30m} vs {n_embargoed_15m}) — razão "
        "parcial indicaria escala errada, não só ausência de escala"
    )


def test_assert_embargo_respected_usa_tf_do_config_nao_constante_fixa() -> None:
    """assert_embargo_respected precisa calcular embargo_ms a partir de
    result.config.tf, não de uma constante de módulo — senão a própria
    checagem de embargo (que deveria pegar violação) ficaria calibrada
    pro TF errado e passaria silenciosamente."""
    n = 600
    labels = _make_synthetic_labels(n, horizon_bars=1)
    cfg_30m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_bars=4, tf="30m")
    result = cpcv.generate_splits(labels, cfg_30m)
    # não deve levantar -- a própria geração de splits já respeitou o embargo
    # calculado com tf="30m"; se assert_embargo_respected recalculasse com
    # 15m hardcoded, a janela seria menor e o teste passaria por acidente,
    # não por corretude -- este teste não distingue os dois casos sozinho,
    # mas falha se generate_splits e assert_embargo_respected divergirem de
    # config.tf em direções opostas (o que um _BAR_MS remanescente causaria).
    cpcv.assert_embargo_respected(labels, result)


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
