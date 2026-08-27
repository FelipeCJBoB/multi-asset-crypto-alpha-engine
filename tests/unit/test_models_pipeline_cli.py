"""Testes de `src.models.pipeline._optional_policy_kwargs` -- fix de um
bug real medido em 2026-08-27 (handoff de `src/models/`, achado 1).

O parser de CLI (`_parse_args`, dentro de `if __name__ == "__main__":`,
`# pragma: no cover`) declarava os defaults LEGADOS de `calib_split_
mode`/`class_balance_basis` e sempre os passava explicitamente pra
`run_layer1_sprint`, mesmo sem a flag -- mascarando silenciosamente a
promoção de `AG-272` (a função já default para `TEMPORAL_PURGED`/
`WEIGHT`). 8 relatórios reais em `experiments/*_ag207_k62.json`
confirmam o dano: gerados via CLI sem flag, herdaram os valores errados.

`_optional_policy_kwargs` é a peça extraída pra fechar isso de forma
testável -- o resto do CLI (`_parse_args`/`_run_cli`) continua dentro do
guard `if __name__`, não importável, por isso não ganhou teste próprio
aqui (mesmo `# pragma: no cover` de sempre)."""

from __future__ import annotations

from src.models import pipeline


def test_omite_ambos_quando_nenhuma_flag_setada() -> None:
    """O caso que causou o bug real: sem flag, o dict tem que vir VAZIO --
    `run_layer1_sprint` aplica o próprio default (hoje `TEMPORAL_PURGED`/
    `WEIGHT`), nunca um literal duplicado aqui."""
    kwargs = pipeline._optional_policy_kwargs(
        calib_split_mode=None, class_balance_basis=None
    )
    assert kwargs == {}


def test_inclui_calib_split_mode_quando_setado() -> None:
    kwargs = pipeline._optional_policy_kwargs(
        calib_split_mode="legacy_random_stratified", class_balance_basis=None
    )
    assert kwargs == {"calib_split_mode": "legacy_random_stratified"}


def test_inclui_class_balance_basis_quando_setado() -> None:
    kwargs = pipeline._optional_policy_kwargs(
        calib_split_mode=None, class_balance_basis="count"
    )
    assert kwargs == {"class_balance_basis": "count"}


def test_inclui_os_dois_quando_ambos_setados() -> None:
    kwargs = pipeline._optional_policy_kwargs(
        calib_split_mode="temporal_purged", class_balance_basis="weight"
    )
    assert kwargs == {
        "calib_split_mode": "temporal_purged",
        "class_balance_basis": "weight",
    }
