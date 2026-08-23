"""Varre `**/_paths.py` por guardas contra `CALIBRATION_TF_BY_RESOLUTION`
(`resolution_id not in CALIBRATION_TF_BY_RESOLUTION -> ValueError`) e
confirma que toda ocorrência encontrada (i) de fato levanta `ValueError`
no corpo verdadeiro e (ii) tem a MESMA forma de condição em todo site —
mecaniza a checagem que `AG-176` (`audit/architecture_gaps_log.yaml`)
propôs, mesmo espírito de `check_unguarded_ratios.py` pra outra classe de
bug.

**Contexto -- por que a duplicação existe e por que este script não a
remove.** `src/models/_paths.py`, `src/regime/_paths.py`,
`src/labels/_paths.py` e `src/validation/_paths.py` duplicam
deliberadamente a mesma guarda de poucas linhas (`resolution_id`, quando
setado, precisa ser uma resolução dollar-bar reconhecida -- AG-042/
AG-166) em vez de importar de um módulo compartilhado -- mesma tática já
documentada em cada um desses arquivos: evitar acoplar 4 pacotes por um
detalhe de infraestrutura, mesmo onde a hierarquia de camadas permitiria
o import direto. Essa decisão de arquitetura fica de pé (`AG-176`,
"dentro da convenção do repo") -- o risco real não é a duplicação em si,
é ela DIVERGIR silenciosamente se uma cópia for editada no futuro sem as
outras acompanharem.

**Isto é um heurístico, não uma prova** (mesma ressalva de
`check_unguarded_ratios.py`): AST não executa o código, só confere forma.
NÃO verifica que `resolution_id`, quando setado, de fato VENCE sobre `tf`
no valor final retornado -- a forma de controle de fluxo diverge
legitimamente entre os pacotes (`models/_paths.py::_resolve_grade` usa
`return` antecipado; os outros usam `if/else` atribuindo uma variável
local `grade`) -- checar precedência exigiria seguir o valor de retorno,
não só a forma da guarda. Revisão humana continua necessária pra essa
parte. Também não tenta decidir se uma função DEVERIA ter esta guarda e
não tem (não existe um jeito genérico de saber "isto precisava de
guarda" sem contexto de domínio) -- só audita as guardas que já existem.

Uso:
    python tools/lint/check_resolution_id_guard_parity.py [--path src] [--strict]
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

_CALIBRATION_MAP_NAME = "CALIBRATION_TF_BY_RESOLUTION"


def _out(message: str) -> None:
    print(message)


@dataclass(frozen=True)
class GuardSite:
    file: Path
    function: str
    line: int
    condition: str
    raises_valueerror: bool


def _raises_valueerror(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Raise) and stmt.exc is not None:
            exc = stmt.exc
            func = exc.func if isinstance(exc, ast.Call) else exc
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "ValueError":
                return True
    return False


def _is_calibration_membership_check(node: ast.Compare) -> bool:
    if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        return False
    try:
        text = ast.unparse(node)
    except Exception:
        return False
    return _CALIBRATION_MAP_NAME in text


def _find_guard_sites_in_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[GuardSite]:
    """Guardas cujo `Compare` pertence ao PRÓPRIO corpo de `func_node` --
    não desce em função aninhada (mesma disciplina de
    `check_unguarded_ratios.py::_visit_node`: cada guarda pertence à
    função mais interna que a contém, nunca também à externa)."""
    sites: list[GuardSite] = []

    def visit(node: ast.AST, if_stack: list[ast.If]) -> None:
        if node is not func_node and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        new_if_stack = [*if_stack, node] if isinstance(node, ast.If) else if_stack
        if isinstance(node, ast.Compare) and _is_calibration_membership_check(node):
            enclosing_if = if_stack[-1] if if_stack else None
            raises = _raises_valueerror(enclosing_if.body) if enclosing_if is not None else False
            sites.append(
                GuardSite(
                    file=Path(),  # preenchido pelo chamador
                    function=func_node.name,
                    line=node.lineno,
                    condition=ast.unparse(node),
                    raises_valueerror=raises,
                )
            )
        for child in ast.iter_child_nodes(node):
            visit(child, new_if_stack)

    visit(func_node, [])
    return sites


def _iter_py_files(root: Path, pattern: str) -> list[Path]:
    if root.is_file():
        return [root] if root.match(pattern) else []
    return sorted(p for p in root.rglob(pattern) if "__pycache__" not in p.parts)


def find_guard_sites(root: Path) -> list[GuardSite]:
    sites: list[GuardSite] = []
    for py_file in _iter_py_files(root, "_paths.py"):
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue
        for func_node in ast.walk(tree):
            if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for site in _find_guard_sites_in_function(func_node):
                sites.append(
                    GuardSite(
                        file=py_file,
                        function=site.function,
                        line=site.line,
                        condition=site.condition,
                        raises_valueerror=site.raises_valueerror,
                    )
                )
    return sites


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows usa cp1252 por padrão

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--path", type=Path, default=Path("src"))
    parser.add_argument(
        "--strict",
        action="store_true",
        help="sai com código 1 se houver guarda sem raise ou condições divergentes entre sites",
    )
    args = parser.parse_args()

    if not args.path.exists():
        _out(f"check_resolution_id_guard_parity: {args.path} não existe — nada a verificar.")
        return 0

    sites = find_guard_sites(args.path)
    no_raise = [s for s in sites if not s.raises_valueerror]
    condition_texts = sorted({s.condition for s in sites})

    _out(
        f"check_resolution_id_guard_parity: {len(sites)} guarda(s) contra "
        f"{_CALIBRATION_MAP_NAME} encontrada(s) em {args.path} — "
        f"{len(sites) - len(no_raise)} levantam ValueError, {len(no_raise)} não; "
        f"{len(condition_texts)} forma(s) de condição distinta(s) (esperado: 1)."
    )

    if no_raise:
        _out(
            "\nGuarda encontrada mas o `if` não levanta ValueError no corpo verdadeiro "
            "-- resolution_id inválido cairia silenciosamente em vez de falhar:\n"
        )
        for s in no_raise:
            _out(f"  {s.file}:{s.line} — {s.function}()")

    if len(condition_texts) > 1:
        _out(
            "\nCondições DIVERGEM entre sites (esperado: todas idênticas, mesma variável e "
            "operador -- revise se a divergência é intencional):\n"
        )
        for c in condition_texts:
            _out(f"  {c!r}")

    if args.strict and (no_raise or len(condition_texts) > 1):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
