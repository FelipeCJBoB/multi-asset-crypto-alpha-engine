"""Verifica que toda constante referenciada via `load_constant("...")` em `src/`
tem entrada correspondente em `config/constants.yaml` — **no estado que seria
commitado** (índice do git), não no working tree bruto.

Motivação (achado real desta investigação, ver `docs/SPRINT_LOG.md`, Fase H):
~280 linhas de proveniência de constantes (Sprints 8 e 12) ficaram no working
tree por sessões inteiras sem nunca entrar em commit — os commits que
"fechavam" aqueles sprints capturaram o `.py` mas não a entrada correspondente
em `constants.yaml`. `check_constants_provenance.py` (já existente neste
diretório) valida a FORMA das entradas que já estão em `constants.yaml` —
`class`, `provenance`, `sweep_range` etc. Ele não confere se toda referência
`load_constant("nome")` no código tem alguma entrada. Este script cobre essa
lacuna, e faz isso contra o ÍNDICE do git (staged), não o arquivo em disco:
um `constants.yaml` correto no disco mas não staged não teria pegado o
incidente real — o commit teria saído incompleto do mesmo jeito.

Uso:
    python tools/lint/check_constants_referenced.py
    python tools/lint/check_constants_referenced.py --src src \
        --constants config/constants.yaml
    python tools/lint/check_constants_referenced.py --worktree  # ignora o índice do git

Fora de um repo git (ou arquivo não rastreado no índice), cai para o disco
automaticamente — documentado no valor de retorno de `load_constant_names`
(campo `origin`), nunca um fallback silencioso.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


def _out(message: str) -> None:
    """Saída de CLI deste script. `tools/lint/` não é "código de pipeline"
    (B28/§14.1 mira em `src/`) — mas o ruff (`T20`, `pyproject.toml`) não
    distingue por diretório, só por `tests/**`. Um único `# noqa` aqui em vez
    de um por chamada."""
    print(message)  # noqa: T201


@dataclass(frozen=True)
class Reference:
    name: str
    file: Path
    line: int


def find_references(root: Path) -> list[Reference]:
    """AST-scan de `root` procurando toda chamada `load_constant("literal")`
    (aceita tanto `load_constant(...)` quanto `algo.load_constant(...)`, para
    não depender de como o símbolo foi importado).

    Chamadas com primeiro argumento não-literal (variável, f-string, etc.) não
    podem ser resolvidas estaticamente — são ignoradas, não reportadas nem como
    erro nem como referência válida. Nenhum caso desses existe em `src/` hoje
    (confirmado por grep manual ao escrever este script: todo call site usa
    string literal). Se aparecer um no futuro, este scanner simplesmente não o
    verá — limitação conhecida do approach AST estático, não um bug silencioso.
    """
    refs: list[Reference] = []
    for py_file in sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts):
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            is_load_constant = (isinstance(func, ast.Name) and func.id == "load_constant") or (
                isinstance(func, ast.Attribute) and func.attr == "load_constant"
            )
            if not is_load_constant:
                continue
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                refs.append(Reference(first_arg.value, py_file, node.lineno))
    return refs


def _keys(data: dict[str, object]) -> set[str]:
    # "known_gaps" não é uma constante lida por load_constant() — é metadado
    # de cobertura de dado (mesma exceção já aplicada em
    # check_constants_provenance.py::check).
    return {k for k in data if k != "known_gaps"}


def _git_repo_root(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            encoding="utf-8",
            cwd=cwd,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(result.stdout.strip())


def _read_staged(path: Path) -> str | None:
    """Devolve o conteúdo de `path` como está no ÍNDICE do git (o que
    `git commit` capturaria agora), ou `None` se não for possível: fora de um
    repo git, arquivo não rastreado, etc.

    `encoding="utf-8"` é explícito (não `text=True`): o default de texto do
    subprocess no Windows segue a codepage do console (cp1252), que quebra em
    qualquer conteúdo com acento ou símbolo (`Ⓢ`, `§`, "proveniência" — todos
    presentes em `constants.yaml`/`src/`). Sem isso, a leitura do índice falha
    silenciosamente (thread de leitura do subprocess morre com
    `UnicodeDecodeError`, `result.stdout` some) e o script cai pro fallback de
    disco sem avisar — comportamento observado e corrigido ao testar este
    script contra o `constants.yaml` real do repo, que tem `Ⓢ` na linha 1."""
    repo_root = _git_repo_root(path.parent if path.parent.exists() else Path.cwd())
    if repo_root is None:
        return None
    try:
        rel = path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return None
    result = subprocess.run(
        ["git", "show", f":{rel}"],
        capture_output=True,
        encoding="utf-8",
        cwd=repo_root,
    )
    if result.returncode != 0 or result.stdout is None:
        return None
    return result.stdout


def load_constant_names(path: Path, *, prefer_staged: bool = True) -> tuple[set[str], str]:
    """Devolve (chaves definidas, descrição da origem).

    Com `prefer_staged=True` (padrão — usado pelo hook), tenta o índice do
    git primeiro; cai para o arquivo em disco só se o índice não estiver
    disponível (fora de repo git, arquivo não rastreado). Com
    `prefer_staged=False` (`--worktree`), vai direto pro disco.
    """
    if prefer_staged:
        staged_text = _read_staged(path)
        if staged_text is not None:
            data = yaml.safe_load(staged_text) or {}
            return _keys(data), "índice do git (staged)"
    if not path.exists():
        return set(), "arquivo ausente"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    origin = (
        "working tree (fallback — índice do git indisponível)"
        if prefer_staged
        else "working tree (--worktree)"
    )
    return _keys(data), origin


def check(references: list[Reference], defined: set[str]) -> list[str]:
    """Devolve uma linha de problema por referência sem entrada correspondente."""
    problems: list[str] = []
    for ref in references:
        if ref.name not in defined:
            problems.append(
                f'{ref.file}:{ref.line} — load_constant("{ref.name}") não tem entrada '
                "em config/constants.yaml"
            )
    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows usa cp1252 por padrão

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--src", type=Path, default=Path("src"))
    parser.add_argument("--constants", type=Path, default=Path("config/constants.yaml"))
    parser.add_argument(
        "--worktree",
        action="store_true",
        help="ignora o índice do git, lê config/constants.yaml direto do disco",
    )
    args = parser.parse_args()

    if not args.src.exists():
        _out(f"check_constants_referenced: {args.src} não existe — nada a verificar.")
        return 0

    references = find_references(args.src)
    defined, origin = load_constant_names(args.constants, prefer_staged=not args.worktree)

    _out(
        f"check_constants_referenced: {len(references)} referência(s) load_constant(...) "
        f"em {args.src}, {len(defined)} constante(s) definidas em {args.constants} ({origin})."
    )

    problems = check(references, defined)
    if problems:
        _out(f"\n{len(problems)} referência(s) sem entrada correspondente:\n")
        for p in problems:
            _out(f"  {p}")
        return 1

    _out("check_constants_referenced: OK — toda referência tem entrada correspondente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
