"""Verifica config/constants.yaml contra as regras de proveniência (§16.10.2).

Regra 2: build de produção não pode ter constante classe A com
`provenance: ASSUMED`. Regra 4: toda classe A precisa de `sweep_required: true`
e `sweep_range` declarado.

Uso:
    python tools/lint/check_constants_provenance.py [--path config/constants.yaml]
        [--fail-on-assumed-class-a] [--only-ret-net-gate]

Sem --fail-on-assumed-class-a, só reporta — é o modo esperado até o Sprint 10
(varredura de sensibilidade ainda não feita, então classe A ASSUMED é estado
normal de pesquisa, não bug).

**Achado de auditoria (AG-028, 2026-08-15):** até esta versão, o script só
processava `class: A` — o campo `review_by` de constantes `class: B`
`ASSUMED` (ex. as 8 janelas de feature de AG-027, `feature_a13_ema_window`
etc.) nunca era lido em lugar nenhum. O campo existia como intenção
documentada em `constants.yaml`, sem nenhum mecanismo que o tornasse
visível — a mesma classe de defeito que já apareceu 4x antes (AG-004/005/
017/027: parâmetro com escopo/prazo implícito nunca verificado
mecanicamente) reapareceria de novo sem aviso quando o sprint de revisão
chegasse. `check_assumed_class_b_review_by` abaixo fecha isso: lista TODA
constante `class: B` `ASSUMED` com seu `review_by`, sempre visível, sem
comparar contra "sprint atual" (não há tracking machine-readable de sprint
neste repo — mesma limitação que `check_assumed_class_a` já tem, que só
lista, não compara contra um "Sprint 10" real). Visibilidade incondicional
é o alarme; decidir se o prazo já passou continua julgamento humano."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def check(data: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, entry in data.items():
        if name == "known_gaps" or not isinstance(entry, dict):
            continue
        if "class" not in entry or "provenance" not in entry:
            problems.append(f"{name}: falta 'class' ou 'provenance'")
            continue
        if entry["class"] == "A":
            derived_from = entry.get("derived_from")
            if entry.get("sweep_required") is not True and not derived_from:
                problems.append(
                    f"{name}: classe A precisa de sweep_required: true, ou de 'derived_from' "
                    "apontando para os pais já varridos (regra 4)"
                )
            if entry["provenance"] == "ASSUMED" and not entry.get("sweep_range"):
                problems.append(f"{name}: classe A ASSUMED sem sweep_range declarado")
    return problems


def check_assumed_class_a(data: dict[str, Any]) -> list[str]:
    return [
        name
        for name, entry in data.items()
        if isinstance(entry, dict)
        and entry.get("class") == "A"
        and entry.get("provenance") == "ASSUMED"
    ]


def check_assumed_no_caminho_do_pnl(data: dict[str, Any]) -> list[str]:
    """AG-442 — classe A `ASSUMED` que declara `enters_ret_net: true`.

    **Por que esta checagem é diferente das outras.** `check_assumed_class_a`
    lista TODA classe A ASSUMED sem falhar, porque antes da varredura de
    sensibilidade isso é estado normal de pesquisa. Mas há um subconjunto
    para o qual "estado normal de pesquisa" deixou de valer: a constante que
    é SUBTRAÍDA de `ret_net`. Ela não afeta só um gate ou um sizing — ela
    entra no número que decide se um candidato dá lucro, e portanto governa
    toda promoção.

    Caso que motivou (`AG-432`, 2026-09-03): `adverse_selection_bps` era
    coluna informativa que nenhum gate lia. Passou a ser cobrada de
    `ret_net` e, com isso, mudou de categoria — de cosmética para
    decisória — **sem que nada no repositório registrasse a mudança de
    status**. Continuou aparecendo na mesma lista de 15 pendências do
    Sprint 10, indistinguível de uma constante de guardrail.

    `enters_ret_net` é DECLARATIVO de propósito, não inferido do código: a
    alternativa (grep no `triple_barrier` atrás de quem entra na fórmula)
    quebra em silêncio quando o custo muda de forma, e um lint que erra em
    silêncio é pior que nenhum. Declarar é barato e auditável — quem move
    uma constante para dentro de `ret_net` tem que dizer isso aqui.

    Diferente das outras: esta FALHA o build sempre, sem flag. Uma constante
    inventada dentro do P&L é o tipo de coisa que não deve esperar sprint."""
    return sorted(
        name
        for name, entry in data.items()
        if isinstance(entry, dict)
        and entry.get("class") == "A"
        and entry.get("provenance") == "ASSUMED"
        and entry.get("enters_ret_net") is True
    )


def check_assumed_class_b_review_by(data: dict[str, Any]) -> list[tuple[str, str]]:
    """(nome, review_by) de toda constante `class: B` `ASSUMED` que declara
    `review_by` -- ver docstring do módulo (AG-028). Classe B sem
    `review_by` declarado não entra aqui (isso é um problema à parte, não
    coberto por este achado)."""
    return sorted(
        (name, str(entry["review_by"]))
        for name, entry in data.items()
        if isinstance(entry, dict)
        and entry.get("class") == "B"
        and entry.get("provenance") == "ASSUMED"
        and entry.get("review_by")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path("config/constants.yaml"))
    parser.add_argument("--fail-on-assumed-class-a", action="store_true")
    parser.add_argument(
        "--only-ret-net-gate",
        action="store_true",
        help="AG-442 -- roda SO a checagem de classe A ASSUMED com enters_ret_net: true. "
        "Existe pra ter um step de CI BLOQUEANTE estreito, sem arrastar as 15 classe A "
        "ASSUMED legitimamente pendentes do Sprint 10 (cujo step segue non-blocking).",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"check_constants_provenance: {args.path} não existe.")
        return 1

    data = _load(args.path)

    if args.only_ret_net_gate:
        no_pnl_only = check_assumed_no_caminho_do_pnl(data)
        if not no_pnl_only:
            print(
                "check_constants_provenance: nenhuma constante classe A ASSUMED "
                "declarada em `ret_net` (AG-442)."
            )
            return 0
        print(f"FALHA (AG-442): {len(no_pnl_only)} constante(s) classe A ASSUMED em `ret_net`:")
        for name in no_pnl_only:
            print(f"  - {name}")
        print(
            "  Uma constante INVENTADA dentro do P&L decide promocao de candidato. "
            "Saidas: medir, remover de ret_net, ou o Manager renunciar explicitamente."
        )
        return 1

    problems = check(data)
    for p in problems:
        print(f"check_constants_provenance: {p}")

    assumed = check_assumed_class_a(data)
    if assumed:
        print(
            f"\n{len(assumed)} constante(s) classe A ainda ASSUMED "
            "(esperado antes da varredura, Sprint 10):"
        )
        for name in assumed:
            print(f"  - {name}")

    no_pnl = check_assumed_no_caminho_do_pnl(data)
    if no_pnl:
        print(
            f"\nFALHA (AG-442): {len(no_pnl)} constante(s) classe A ASSUMED que entram "
            "em `ret_net` (`enters_ret_net: true`):"
        )
        for name in no_pnl:
            print(f"  - {name}")
        print(
            "  Uma constante INVENTADA dentro do P&L decide promoção de candidato. "
            "Meça, ou remova do cálculo de ret_net -- não espere sprint."
        )

    assumed_b = check_assumed_class_b_review_by(data)
    if assumed_b:
        print(
            f"\n{len(assumed_b)} constante(s) classe B ASSUMED com review_by "
            "declarado (AG-028 -- visibilidade, não falha):"
        )
        for name, review_by in assumed_b:
            print(f"  - {name}: review_by={review_by}")

    if problems or no_pnl:
        return 1
    if args.fail_on_assumed_class_a and assumed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
