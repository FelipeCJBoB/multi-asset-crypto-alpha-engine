"""Testes de `src/analysis/feature_null_census.py` — censo de nulos por
coluna x célula (ADR-005 §13 v2 §13.5-2, item 3 de §13.17, `AG-308`).

Núcleo 100% puro (Idioma A): todos os testes montam o frame em memória,
nenhum toca disco — sem `_skip_if_*`, sem marcador `integration`.

A métrica que os testes existem para proteger é `n_null_exclusivo`:
linhas em que a coluna é nula **e todas as outras do vetor são válidas**.
É o único número que responde "quanto eu recupero tirando esta coluna", e
é fácil de implementar errado como `n_null` (que superestima
grosseiramente quando os nulos de warmup se sobrepõem — o caso normal).
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from src.analysis import feature_null_census as census

_A, _B, _C = "A_col", "B_col", "C_col"


def _frame(**cols: list[float | None]) -> pl.DataFrame:
    return pl.DataFrame({k: pl.Series(v, dtype=pl.Float64) for k, v in cols.items()})


# ============================================================================
# 1. `n_null_exclusivo` — a métrica que decide
# ============================================================================


def test_custo_exclusivo_conta_so_a_linha_em_que_ela_e_a_UNICA_nula() -> None:
    df = _frame(
        A_col=[None, 1.0, 1.0, 1.0],  # linha 0: A é a única nula -> exclusivo
        B_col=[1.0, None, 1.0, 1.0],  # linha 1: B é a única nula -> exclusivo
        C_col=[None, None, 1.0, 1.0],  # linhas 0 e 1: acompanhada -> 0 exclusivo
    )
    by = {s.feature_id: s for s in census.column_null_stats(df, (_A, _B, _C))}
    assert by[_A].n_null == 1 and by[_A].n_null_exclusivo == 0, "A divide a linha 0 com C"
    assert by[_B].n_null == 1 and by[_B].n_null_exclusivo == 0, "B divide a linha 1 com C"
    assert by[_C].n_null == 2 and by[_C].n_null_exclusivo == 0, "C nunca está sozinha"


def test_coluna_isolada_tem_custo_exclusivo_igual_ao_n_null() -> None:
    """Quando ninguém mais é nulo naquelas linhas, os dois números batem —
    é o caso `D07f` do dado real."""
    df = _frame(
        A_col=[1.0, 1.0, 1.0, 1.0],
        B_col=[1.0, 1.0, 1.0, 1.0],
        C_col=[None, None, 1.0, 1.0],
    )
    by = {s.feature_id: s for s in census.column_null_stats(df, (_A, _B, _C))}
    assert by[_C].n_null == 2
    assert by[_C].n_null_exclusivo == 2


def test_nulos_de_warmup_PERFEITAMENTE_aninhados_tem_custo_exclusivo_zero() -> None:
    """O caso que motiva a métrica, e o achado real do dado: as 13 colunas
    de futures-positioning começam todas na MESMA linha (a fonte só existe
    a partir de certa data). Cada uma tem `n_null` enorme e custo exclusivo
    ZERO — tirar UMA não devolve linha nenhuma; só tirar o bloco inteiro
    devolve. Reportar `n_null` faria as 13 parecerem caríssimas
    individualmente."""
    prefixo: list[float | None] = [None, None, None]
    corpo: list[float | None] = [1.0, 1.0]
    df = _frame(A_col=prefixo + corpo, B_col=prefixo + corpo, C_col=[1.0] * 5)
    by = {s.feature_id: s for s in census.column_null_stats(df, (_A, _B, _C))}
    assert by[_A].n_null == 3
    assert by[_B].n_null == 3
    assert by[_A].n_null_exclusivo == 0
    assert by[_B].n_null_exclusivo == 0


def test_primeira_linha_valida_mede_o_warmup_efetivo() -> None:
    df = _frame(A_col=[None, None, 5.0, 6.0], B_col=[1.0, 2.0, 3.0, 4.0])
    by = {s.feature_id: s for s in census.column_null_stats(df, (_A, _B))}
    assert by[_A].primeira_linha_valida == 2
    assert by[_B].primeira_linha_valida == 0


# ============================================================================
# 2. Coluna morta — o par `frac_retida` / `frac_retida_sem_mortas`
# ============================================================================


def test_coluna_morta_zera_a_retencao_e_o_par_sem_mortas_e_o_numero_acionavel() -> None:
    """Achado da 1ª execução real, e o motivo de `frac_retida_sem_mortas`
    existir: com UMA coluna 100% nula no vetor, `frac_retida` é 0 nas 15
    células e o agregado não informa nada — a coluna morta domina e esconde
    o custo de todas as outras."""
    df = _frame(
        A_col=[None, 1.0, 1.0, 1.0],
        B_col=[1.0, 1.0, 1.0, 1.0],
        C_col=[None, None, None, None],  # morta
    )
    c = census.census_from_frame(
        df, (_A, _B, _C), symbol="TESTUSDT", resolution_id="R1", bar_source="dollar_r1"
    )
    assert c.colunas_mortas == [_C]
    assert c.n_colunas_mortas == 1
    assert c.n_linhas_todas_validas == 0
    assert c.frac_retida == pytest.approx(0.0)
    # descontando a morta, sobram 3 das 4 linhas (a linha 0 cai por A)
    assert c.n_linhas_todas_validas_sem_mortas == 3
    assert c.frac_retida_sem_mortas == pytest.approx(0.75)


def test_coluna_morta_tem_primeira_linha_valida_menos_um() -> None:
    df = _frame(A_col=[1.0, 1.0], C_col=[None, None])
    by = {s.feature_id: s for s in census.column_null_stats(df, (_A, _C))}
    assert by[_C].primeira_linha_valida == -1
    assert by[_A].primeira_linha_valida == 0


def test_sem_coluna_morta_as_duas_retencoes_coincidem() -> None:
    df = _frame(A_col=[None, 1.0, 1.0], B_col=[1.0, 1.0, 1.0])
    c = census.census_from_frame(
        df, (_A, _B), symbol="TESTUSDT", resolution_id="R1", bar_source="dollar_r1"
    )
    assert c.n_colunas_mortas == 0
    assert c.frac_retida == c.frac_retida_sem_mortas == pytest.approx(2 / 3)


# ============================================================================
# 3. Ordenação e contratos
# ============================================================================


def test_por_coluna_vem_ordenado_por_custo_exclusivo_decrescente() -> None:
    df = _frame(
        A_col=[None, None, 1.0, 1.0],  # 2 exclusivos
        B_col=[1.0, 1.0, None, 1.0],  # 1 exclusivo
        C_col=[1.0, 1.0, 1.0, 1.0],  # 0
    )
    c = census.census_from_frame(
        df, (_C, _B, _A), symbol="TESTUSDT", resolution_id="R1", bar_source="dollar_r1"
    )
    assert [d["feature_id"] for d in c.por_coluna] == [_A, _B, _C]


def test_coluna_ausente_no_frame_falha_com_o_nome() -> None:
    df = _frame(A_col=[1.0, 2.0])
    with pytest.raises(KeyError, match="Z99"):
        census.column_null_stats(df, (_A, "Z99_nao_existe"))


def test_feature_ids_vazio_levanta() -> None:
    df = _frame(A_col=[1.0, 2.0])
    with pytest.raises(ValueError, match="vazio"):
        census.column_null_stats(df, ())


def test_bar_source_por_resolucao_vem_do_dataset_nao_de_uma_copia() -> None:
    """A tabela de `resolution_id -> bar_source` mora em
    `src.models.dataset`. Duas cópias que pudessem divergir sobre qual barra
    é qual resolução é a classe de bug de `AG-042`."""
    from src.models.dataset import _BAR_SOURCE_BY_RESOLUTION

    for res, expected in _BAR_SOURCE_BY_RESOLUTION.items():
        assert census._bar_source_for(res) == expected
    with pytest.raises(ValueError, match="R9"):
        census._bar_source_for("R9")


# ============================================================================
# ADR-008 Fase 2 — column_distribution_stats (mean/std/percentis/min/max)
# ============================================================================


def test_column_distribution_stats_valores_conferidos_a_mao() -> None:
    """`A_col = [1,2,3,4,5]` (sem nulo) -- mean=3,0, std(ddof=1)=sqrt(2,5),
    min=1,0, max=5,0, mediana(p50)=3,0 -- valores de livro-texto, não
    aproximados."""
    df = _frame(A_col=[1.0, 2.0, 3.0, 4.0, 5.0])
    out = census.column_distribution_stats(df, (_A,))
    assert len(out) == 1
    s = out[0]
    assert s.feature_id == _A
    assert s.dtype == "Float64"
    assert s.n_valid == 5
    assert s.mean == pytest.approx(3.0)
    assert s.std == pytest.approx(2.5**0.5)
    assert s.p50 == pytest.approx(3.0)
    assert s.min == pytest.approx(1.0)
    assert s.max == pytest.approx(5.0)


def test_column_distribution_stats_ignora_nulos_no_calculo() -> None:
    """`[1, null, 3]` -- mean/min/max ignoram o `null` (mean=2,0, não
    tratar `null` como `0.0`, que daria mean=1,333...)."""
    df = _frame(A_col=[1.0, None, 3.0])
    out = census.column_distribution_stats(df, (_A,))
    s = out[0]
    assert s.n_valid == 2
    assert s.mean == pytest.approx(2.0)
    assert s.min == pytest.approx(1.0)
    assert s.max == pytest.approx(3.0)


def test_column_distribution_stats_coluna_100pct_nula_devolve_nan_nao_erro() -> None:
    df = _frame(A_col=[None, None, None])
    out = census.column_distribution_stats(df, (_A,))
    s = out[0]
    assert s.n_valid == 0
    assert math.isnan(s.mean)
    assert math.isnan(s.std)
    assert math.isnan(s.p50)


def test_column_distribution_stats_um_valor_so_std_nan() -> None:
    """`std` amostral (`ddof=1`) é indefinido com 1 ponto -- `NaN`, não
    `ZeroDivisionError`."""
    df = _frame(A_col=[1.0])
    out = census.column_distribution_stats(df, (_A,))
    assert out[0].n_valid == 1
    assert math.isnan(out[0].std)
    assert out[0].mean == pytest.approx(1.0)


def test_column_distribution_stats_coluna_ausente_levanta_keyerror() -> None:
    df = _frame(A_col=[1.0, 2.0])
    with pytest.raises(KeyError, match="Z99"):
        census.column_distribution_stats(df, (_A, "Z99_nao_existe"))


def test_column_distribution_stats_feature_ids_vazio_levanta() -> None:
    df = _frame(A_col=[1.0, 2.0])
    with pytest.raises(ValueError, match="vazio"):
        census.column_distribution_stats(df, ())


def test_census_from_frame_mescla_distribuicao_no_por_coluna_sem_quebrar_schema() -> None:
    """`por_coluna` continua tendo os campos de `ColumnNullStats` (schema
    existente, D0/backward-compat) E ganha os de `ColumnDistributionStats`
    (aditivo) -- os dois convivem no mesmo dict por feature."""
    df = _frame(A_col=[1.0, 2.0, 3.0], B_col=[1.0, 1.0, 1.0])
    c = census.census_from_frame(
        df, (_A, _B), symbol="TESTUSDT", resolution_id="R1", bar_source="dollar_r1"
    )
    by_feature = {d["feature_id"]: d for d in c.por_coluna}
    # campos antigos continuam presentes
    assert "n_null" in by_feature[_A]
    assert "n_null_exclusivo" in by_feature[_A]
    # campos novos entraram
    assert by_feature[_A]["mean"] == pytest.approx(2.0)
    assert by_feature[_B]["std"] == pytest.approx(0.0)
