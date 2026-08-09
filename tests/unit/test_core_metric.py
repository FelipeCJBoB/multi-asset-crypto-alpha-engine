"""Testes de `src/core/metric.py` — `Metric`/`Unit`/`safe_ratio`.

Combina exemplos concretos (mesmo padrão do resto do repo) com um teste de
propriedade via `hypothesis` (primeiro uso no repo — `pytest+hypothesis` já
é dependência declarada no stack, `pyproject.toml`): para qualquer `Metric`
construído com estratégias razoáveis, `unit` é uma instância válida de
`Unit`, `n` (quando `valid=True`) é `> 0`, e `n_semantics` é uma string não
vazia — e um `Metric` inválido (`n=0` e/ou `value=nan`, ambos esperados)
não quebra essa checagem."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.core.metric import Metric, Unit, safe_ratio

# ============================================================================
# Estratégias
# ============================================================================

_finite_floats = st.floats(allow_nan=False, allow_infinity=False, width=64)
_any_floats = st.floats(width=64)  # pode incluir nan/inf — Metric não restringe value
_non_empty_text = st.text(min_size=1, max_size=30)
_units = st.sampled_from(list(Unit))
_sources = st.text(min_size=0, max_size=50)


@st.composite
def _valid_metrics(draw: st.DrawFn) -> Metric:
    return Metric(
        value=draw(_finite_floats),
        unit=draw(_units),
        n=draw(st.integers(min_value=1, max_value=1_000_000)),
        n_semantics=draw(_non_empty_text),
        source=draw(_sources),
        valid=True,
        invalid_reason=None,
    )


@st.composite
def _invalid_metrics(draw: st.DrawFn) -> Metric:
    """`n=0` e `value=nan` são exemplos ESPERADOS de `Metric` inválido —
    não são casos degenerados a evitar na estratégia, são exatamente o que
    `safe_ratio` produz quando o guard de denominador dispara."""
    value = draw(st.one_of(st.just(float("nan")), _any_floats))
    return Metric(
        value=value,
        unit=draw(_units),
        n=draw(st.integers(min_value=0, max_value=1_000_000)),
        n_semantics=draw(_non_empty_text),
        source=draw(_sources),
        valid=False,
        invalid_reason=draw(st.one_of(st.none(), _non_empty_text)),
    )


# ============================================================================
# Propriedade — unit válida, n>0 quando valid, n_semantics não vazia
# ============================================================================


@given(_valid_metrics())
def test_metric_valido_tem_unit_valida_n_positivo_e_n_semantics_nao_vazia(m: Metric) -> None:
    assert isinstance(m.unit, Unit)
    assert m.n > 0
    assert isinstance(m.n_semantics, str)
    assert m.n_semantics != ""


@given(_invalid_metrics())
def test_metric_invalido_nao_quebra_a_checagem_de_propriedade(m: Metric) -> None:
    """`n=0`/`value=nan` num `Metric` inválido são esperados — a checagem
    de `unit`/`n_semantics` continua valendo; só a exigência `n > 0` é
    suspensa (não invertida — `n=0` não é exigido, só permitido)."""
    assert isinstance(m.unit, Unit)
    assert isinstance(m.n_semantics, str)
    assert m.n_semantics != ""
    assert m.valid is False
    assert m.n >= 0  # nunca negativo, mas pode ser 0 — não quebra nada ler o campo


# ============================================================================
# to_json — Unit vira string, não o objeto enum
# ============================================================================


def test_to_json_serializa_unit_como_string_e_preserva_campos() -> None:
    m = Metric(
        value=0.0458,
        unit=Unit.RATIO,
        n=30_623,
        n_semantics="trades",
        source="labels/v1",
    )
    d = m.to_json()
    assert d["unit"] == "ratio"
    assert isinstance(d["unit"], str)
    assert d["value"] == 0.0458
    assert d["n"] == 30_623
    assert d["n_semantics"] == "trades"
    assert d["source"] == "labels/v1"
    assert d["valid"] is True
    assert d["invalid_reason"] is None


# ============================================================================
# safe_ratio — guard de denominador (achado nº1 da auditoria)
# ============================================================================


def _m(value: float, *, unit: Unit = Unit.FRACTION_OF_NOTIONAL, n: int = 100) -> Metric:
    return Metric(value=value, unit=unit, n=n, n_semantics="trades", source="test")


def test_safe_ratio_denominador_negativo_com_guard_marca_invalido() -> None:
    """O achado nº1 da auditoria: `carry_share = pnl_carry / pnl_total`
    quando `pnl_total < 0` "passa" um gate de forma acidental sem o guard.
    Com `require_den_positive=True`, o resultado fica `valid=False` em vez
    de um número calculado sem sentido."""
    num = _m(-0.02)
    den = _m(-0.05)  # pnl_total negativo, mesmo sinal de dados reais de hoje
    result = safe_ratio(
        num, den, require_den_positive=True, unit=Unit.RATIO, n_semantics="trades", source="s"
    )
    assert result.valid is False
    assert math.isnan(result.value)
    assert result.invalid_reason is not None and "<=" in result.invalid_reason


def test_safe_ratio_denominador_zero_com_guard_marca_invalido() -> None:
    num = _m(0.01)
    den = _m(0.0)
    result = safe_ratio(
        num, den, require_den_positive=True, unit=Unit.RATIO, n_semantics="trades", source="s"
    )
    assert result.valid is False
    assert math.isnan(result.value)


def test_safe_ratio_denominador_nan_com_guard_marca_invalido() -> None:
    num = _m(0.01)
    den = _m(float("nan"))
    result = safe_ratio(
        num, den, require_den_positive=True, unit=Unit.RATIO, n_semantics="trades", source="s"
    )
    assert result.valid is False
    assert math.isnan(result.value)


def test_safe_ratio_denominador_positivo_calcula_normal() -> None:
    num = _m(0.02)
    den = _m(0.10)
    result = safe_ratio(
        num, den, require_den_positive=True, unit=Unit.RATIO, n_semantics="trades", source="s"
    )
    assert result.valid is True
    assert result.value == pytest.approx(0.2)  # noqa: magic-number — comparação de teste
    assert result.unit == Unit.RATIO
    assert result.n == num.n  # herdado do numerador, ver docstring de safe_ratio


def test_safe_ratio_sem_exigir_denominador_positivo_aceita_negativo() -> None:
    num = _m(0.02)
    den = _m(-0.10)
    result = safe_ratio(
        num, den, require_den_positive=False, unit=Unit.RATIO, n_semantics="trades", source="s"
    )
    assert result.valid is True
    assert result.value == pytest.approx(-0.2)  # noqa: magic-number — comparação de teste


def test_safe_ratio_sem_exigir_denominador_positivo_mas_zero_ainda_marca_invalido() -> None:
    """`require_den_positive=False` opta por não exigir sinal, mas divisão
    por zero literal em Python levanta `ZeroDivisionError` de qualquer
    forma — `safe_ratio` precisa continuar "safe" nos dois modos."""
    num = _m(0.02)
    den = _m(0.0)
    result = safe_ratio(
        num, den, require_den_positive=False, unit=Unit.RATIO, n_semantics="trades", source="s"
    )
    assert result.valid is False
    assert math.isnan(result.value)


def test_safe_ratio_propaga_invalidez_dos_operandos() -> None:
    num = _m(0.02)
    invalid_den = Metric(
        value=float("nan"),
        unit=Unit.FRACTION_OF_NOTIONAL,
        n=0,
        n_semantics="trades",
        source="s",
        valid=False,
        invalid_reason="teste",
    )
    result = safe_ratio(
        num,
        invalid_den,
        require_den_positive=False,
        unit=Unit.RATIO,
        n_semantics="trades",
        source="s",
    )
    # den.value é nan -> ZeroDivisionError não dispara, mas nan/x == nan;
    # o resultado é matematicamente nan (não passa pelo branch de guard,
    # já que require_den_positive=False) e não deveria fingir validade.
    assert math.isnan(result.value)


# ============================================================================
# __add__/__sub__ — mesma unidade soma, unidades diferentes levantam
# ============================================================================


def test_metric_add_mesma_unidade_soma_valor_e_preserva_n() -> None:
    a = _m(0.01)
    b = _m(0.02)
    c = a + b
    assert c.value == pytest.approx(0.03)  # noqa: magic-number — comparação de teste
    assert c.unit == Unit.FRACTION_OF_NOTIONAL
    assert c.n == a.n
    assert c.valid is True


def test_metric_sub_mesma_unidade_subtrai_valor() -> None:
    a = _m(0.05)
    b = _m(0.02)
    c = a - b
    assert c.value == pytest.approx(0.03)  # noqa: magic-number — comparação de teste (0.05 - 0.02)


def test_metric_add_unidades_diferentes_levanta_valueerror() -> None:
    a = _m(0.01, unit=Unit.FRACTION_OF_NOTIONAL)
    b = _m(1.5, unit=Unit.SHARPE_ANNUALIZED)
    try:
        _ = a + b
    except ValueError:
        pass
    else:
        raise AssertionError("esperava ValueError ao somar Metric de unidades diferentes")


def test_metric_sub_unidades_diferentes_levanta_valueerror() -> None:
    a = _m(0.01, unit=Unit.RATIO)
    b = _m(5.0, unit=Unit.COUNT)
    try:
        _ = a - b
    except ValueError:
        pass
    else:
        raise AssertionError("esperava ValueError ao subtrair Metric de unidades diferentes")


def test_metric_add_populacoes_diferentes_marca_resultado_invalido() -> None:
    """`n`/`n_semantics` divergentes entre os dois operandos não levantam
    exceção (a checagem estrutural obrigatória é só de `unit`), mas marcam
    o resultado `valid=False` — divergência de população é sinal de erro
    silencioso demais para deixar passar sem marca."""
    a = _m(0.01, n=100)
    b = _m(0.02, n=50)
    c = a + b
    assert c.valid is False
    assert c.invalid_reason is not None


# ============================================================================
# __mul__/__rmul__ — escalar adimensional sem checagem de unidade
# ============================================================================


def test_metric_mul_escalar_nao_checa_unidade() -> None:
    a = _m(0.01, unit=Unit.SHARPE_ANNUALIZED)
    c = a * 3
    assert c.value == pytest.approx(0.03)  # noqa: magic-number — comparação de teste
    assert c.unit == Unit.SHARPE_ANNUALIZED
    assert c.n == a.n


def test_metric_rmul_escalar_funciona_dos_dois_lados() -> None:
    a = _m(0.01)
    assert (a * 3).value == (3 * a).value


def test_metric_mul_por_metric_levanta_typeerror() -> None:
    a = _m(0.01)
    b = _m(2.0)
    try:
        _ = a * b
    except TypeError:
        pass
    else:
        raise AssertionError("esperava TypeError ao multiplicar Metric por Metric")
