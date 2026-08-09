"""Varre `src/` por divisão com denominador VARIÁVEL sem checagem de sinal
próxima — a classe de bug encontrada duas vezes nesta investigação
(`src.models.decomposition.carry_share = pnl_carry / pnl_total`, sem checar
`pnl_total <= 0`; `src.risk.limits.control_10_risco_real`, que guardava só
`equity == 0`, não `equity <= 0` — um `equity` negativo fazia a razão sair
`<= 0`, que passa qualquer limiar positivo trivialmente, aprovando o
controle de risco na pior hora). Ver `audit/division_guard_audit.md` (Fase
C1/C2, feita à mão sobre 5 arquivos) — este script mecaniza a mesma
pergunta e roda sobre `src/` inteiro, não só onde uma investigação passou.

**Isto é um heurístico, não uma prova.** AST não sabe se um `if` "realmente"
protege a divisão em tempo de execução (early return? branch errado?) — só
que existe, na MESMA função, uma comparação contra zero envolvendo o mesmo
nome do denominador. Falso positivo (denominador estruturalmente positivo,
ex. uma contagem de `len(...)`) é esperado e aceitável — a saída pede
justificativa explícita via `# noqa: unguarded-ratio — <motivo>` (mesmo
padrão de `# noqa: magic-number` em `banned_patterns.py`), não silêncio.
Falso negativo também é possível (guarda existe mas não é uma comparação
direta contra 0 — ex. um outro controle já garante `equity>0` antes desta
função ser chamada) — por isso a saída sem `--strict` é sempre "achados
pra revisar", não "veredito"; só `--strict` (CI/pre-commit) trata unguarded
não-suprimido como falha.

Divisão por LITERAL numérico (`bps / 10000`, `x / 2`) é conversão de
unidade, não razão de dado variável — excluída por construção, mesma
distinção que `_ALLOWED_NUMERIC_LITERALS` já faz em `banned_patterns.py`
pra outra checagem.

Uso:
    python tools/lint/check_unguarded_ratios.py [--path src] [--strict]
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_NOQA_UNGUARDED_RATIO = "noqa: unguarded-ratio"

# `pathlib.Path` sobrecarrega `/` (`__truediv__`) pra junção de caminho — o
# mesmo nó AST (`BinOp(op=Div)`) de uma divisão aritmética de verdade. Sem
# filtrar isso, a maioria dos achados em `src/*/_paths.py` (e qualquer lugar
# que monte caminho) é ruído, não razão de dado. Heurística: um lado
# literal string, OU a base mais à esquerda da cadeia batendo o padrão de
# nome já usado no repo pra raiz de caminho (`REPO_ROOT`, `*_DIR`, `*_ROOT`,
# `*_PATH`, `root`) — recursivo pra cobrir cadeias `A / b / c`.
_PATH_NAME_RE = re.compile(r"(?i)(_dir|_root|_path)$|^(path|root)$")


def _is_path_like(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.Name):
        return bool(_PATH_NAME_RE.search(node.id))
    if isinstance(node, ast.Attribute):
        return bool(_PATH_NAME_RE.search(node.attr)) or _is_path_like(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv)):
        return _is_path_like(node.left) or _is_path_like(node.right)
    if isinstance(node, ast.Call):
        func = node.func
        fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        return fname == "Path"
    return False


# Operadores de comparação que, aplicados ao denominador contra um literal
# numérico (de qualquer lado), contam como "há uma checagem de sinal por
# perto" — não confirma que ela é usada como guarda (early-return/assert),
# só que existe. Ver docstring do módulo.
_SIGN_COMPARISONS: tuple[type[ast.cmpop], ...] = (
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Eq,
    ast.NotEq,
)


def _out(message: str) -> None:
    print(message)  # noqa: T201


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    expression: str
    denominator: str
    guarded: bool
    suppressed: bool


def _denominator_key(node: ast.expr) -> str | None:
    """Nome estável do denominador pra casar contra comparações na mesma
    função — `None` se não for algo nomeável (ex. uma subexpressão
    aritmética `a - b` como denominador, que este script não tenta seguir)."""
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _is_numeric_literal(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    )


def _mentions_sign_check(node: ast.expr, denom_key: str) -> bool:
    """`True` se `node` é uma `Compare` (ou contém uma, via `ast.walk`)
    envolvendo `denom_key` contra 0 com um operador de sinal, OU um
    `try/except ZeroDivisionError` — os dois padrões de guarda já usados em
    `src.core.metric.safe_ratio` (guarda por sinal E fallback de divisão
    literal por zero, ver docstring de `safe_ratio`)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Compare):
            operands = [sub.left, *sub.comparators]
            has_denom = any(_denominator_key(o) == denom_key for o in operands)
            has_zero = any(
                isinstance(o, ast.Constant) and _is_numeric_literal(o) and o.value == 0
                for o in operands
            )
            has_sign_op = any(isinstance(op, _SIGN_COMPARISONS) for op in sub.ops)
            if has_denom and has_zero and has_sign_op:
                return True
        if isinstance(sub, ast.Call):
            func = sub.func
            func_name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if func_name in ("isfinite", "isnan", "isinf") and any(
                _denominator_key(a) == denom_key for a in sub.args
            ):
                return True
    return False


def _function_has_zero_division_guard(func_node: ast.AST, denom_key: str) -> bool:
    for sub in ast.walk(func_node):
        if isinstance(sub, ast.Try):
            for handler in sub.handlers:
                handler_type = handler.type
                names = (
                    [n.id for n in ast.walk(handler_type) if isinstance(n, ast.Name)]
                    if handler_type is not None
                    else []
                )
                if "ZeroDivisionError" in names:
                    return True
        if isinstance(sub, (ast.If, ast.Assert)) and _mentions_sign_check(
            sub.test if isinstance(sub, (ast.If, ast.Assert)) else sub, denom_key
        ):
            return True
    return False


def _line_has_suppression(source_lines: list[str], lineno: int) -> bool:
    if 1 <= lineno <= len(source_lines):
        return _NOQA_UNGUARDED_RATIO in source_lines[lineno - 1]
    return False


def _visit_node(
    node: ast.AST,
    stack: list[ast.AST],
    *,
    py_file: Path,
    source_lines: list[str],
    findings: list[Finding],
) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        stack = [*stack, node]
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv)):
        denom = node.right
        if not _is_numeric_literal(denom) and not _is_path_like(node):
            denom_key = _denominator_key(denom)
            if denom_key is not None:
                scope = stack[-1]
                guarded = _function_has_zero_division_guard(scope, denom_key)
                expr = _denominator_key(node) or "<?>"
                findings.append(
                    Finding(
                        file=py_file,
                        line=node.lineno,
                        expression=expr,
                        denominator=denom_key,
                        guarded=guarded,
                        suppressed=_line_has_suppression(source_lines, node.lineno),
                    )
                )
    for child in ast.iter_child_nodes(node):
        _visit_node(child, stack, py_file=py_file, source_lines=source_lines, findings=findings)


def find_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for py_file in sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts):
        source = py_file.read_text(encoding="utf-8")
        source_lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        # Mapeia cada BinOp de divisão para a função (def/async def) que a
        # contém — módulo inteiro conta como "função" implícita pra código
        # de nível de módulo (raro em src/, mas não deveria quebrar o scan).
        _visit_node(tree, [tree], py_file=py_file, source_lines=source_lines, findings=findings)
    return findings


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
        help="sai com código 1 se houver divisão não-guardada e não-suprimida",
    )
    args = parser.parse_args()

    if not args.path.exists():
        _out(f"check_unguarded_ratios: {args.path} não existe — nada a verificar.")
        return 0

    findings = find_findings(args.path)
    unguarded = [f for f in findings if not f.guarded and not f.suppressed]
    guarded = [f for f in findings if f.guarded]
    suppressed = [f for f in findings if f.suppressed]

    _out(
        f"check_unguarded_ratios: {len(findings)} divisão(ões) de denominador variável "
        f"em {args.path} — {len(guarded)} com checagem de sinal na mesma função, "
        f"{len(suppressed)} suprimida(s) explicitamente, {len(unguarded)} sem nenhuma das duas."
    )

    if unguarded:
        _out(
            "\nSem checagem de sinal na mesma função — revise se o denominador pode ser "
            "<=0/NaN em produção; se for estruturalmente seguro, documente com "
            f"'# {_NOQA_UNGUARDED_RATIO} — <motivo>' na mesma linha:\n"
        )
        for f in unguarded:
            _out(f"  {f.file}:{f.line} — {f.expression}  (denominador: {f.denominator})")

    if args.strict and unguarded:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
