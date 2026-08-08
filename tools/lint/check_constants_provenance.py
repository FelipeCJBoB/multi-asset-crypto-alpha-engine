"""Verifica config/constants.yaml contra as regras de proveniência (§16.10.2).

Regra 2: build de produção não pode ter constante classe A com
`provenance: ASSUMED`. Regra 4: toda classe A precisa de `sweep_required: true`
e `sweep_range` declarado.

Uso:
    python tools/lint/check_constants_provenance.py [--path config/constants.yaml] [--fail-on-assumed-class-a]

Sem --fail-on-assumed-class-a, só reporta — é o modo esperado até o Sprint 10
(varredura de sensibilidade ainda não feita, então classe A ASSUMED é estado
normal de pesquisa, não bug).
"""

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
        if isinstance(entry, dict) and entry.get("class") == "A" and entry.get("provenance") == "ASSUMED"
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path("config/constants.yaml"))
    parser.add_argument("--fail-on-assumed-class-a", action="store_true")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"check_constants_provenance: {args.path} não existe.")
        return 1

    data = _load(args.path)
    problems = check(data)
    for p in problems:
        print(f"check_constants_provenance: {p}")

    assumed = check_assumed_class_a(data)
    if assumed:
        print(f"\n{len(assumed)} constante(s) classe A ainda ASSUMED (esperado antes da varredura, Sprint 10):")
        for name in assumed:
            print(f"  - {name}")

    if problems:
        return 1
    if args.fail_on_assumed_class_a and assumed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
