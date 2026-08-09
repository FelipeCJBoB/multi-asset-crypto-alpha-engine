"""Verifica que toda linha NOVA de `docs/SPRINT_LOG.md` que cita um número tem
uma referência reconhecível por perto — caminho de arquivo entre crases, hash
de commit entre crases, ou citação de seção do PRD (`§N`).

Motivação (achado real desta investigação, ver `docs/SPRINT_LOG.md`, Fase H):
uma análise decisiva (IC de features por regime) foi feita num script ad hoc,
respondeu a uma pergunta, e foi deletada — sem número reproduzível nem
referência a onde o resultado vive, não há como reconstituir a resposta daqui
a 3 meses. Este script não impede alguém de escrever um número solto — isso é
best-effort, heurístico, não um parser de português. Ele torna o hábito de
"todo número tem uma proveniência apontável" visível no CI, com uma válvula de
escape explícita para prosa legítima sem referência formal.

**É HEURÍSTICO por natureza — não parseia prosa em português com certeza.**
Falso positivo esperado (ex. "os 5 estados de regime" não tem — nem precisa
de — uma referência formal). Duas válvulas de escape:
  1. Comentário HTML `<!-- check-sprint-log: skip -->` na linha anterior à
     flagged, ou no final da própria linha flagged.
  2. Ajustar `--window` se o parágrafo for maior que o padrão.

O que conta como "referência" nas proximidades (mesma linha, ou dentro da
janela de `--window` linhas de distância, limitado à fronteira de parágrafo —
linha em branco):
  - hash de commit entre crases: `` `981b153` `` (7 a 40 hex chars)
  - caminho de arquivo entre crases contendo "/": `` `src/models/alpha.py` ``
  - citação de seção do PRD: `§5.11`

Uso:
    python tools/lint/check_sprint_log_references.py
    python tools/lint/check_sprint_log_references.py --base HEAD~1   # modo CI
    python tools/lint/check_sprint_log_references.py --base HEAD     # modo pre-commit (padrão)

Sem `--base`, compara o índice+working tree contra `HEAD` — o que capturaria
o próximo commit (uso local/pre-commit, antes do commit existir). Em CI, o
push já é o commit — não há diff de working tree contra HEAD — por isso o
step de CI passa `--base HEAD~1` explicitamente (precisa de
`fetch-depth >= 2` no checkout; ver `.github/workflows/ci.yml`).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _out(message: str) -> None:
    """Saída de CLI deste script. `tools/lint/` não é "código de pipeline"
    (B28/§14.1 mira em `src/`) — mas o ruff (`T20`, `pyproject.toml`) não
    distingue por diretório, só por `tests/**`. Um único `# noqa` aqui em vez
    de um por chamada."""
    print(message)  # noqa: T201


_SKIP_MARKER = "<!-- check-sprint-log: skip -->"

_NUMBER_RE = re.compile(r"\d[\d.,]*\s*(?:%|bps|x)?")

_REFERENCE_RE = re.compile(
    r"`[0-9a-f]{7,40}`"  # hash de commit entre crases
    r"|`[^`\n]*/[^`\n]*`"  # caminho entre crases (contém "/")
    r"|§\s?\d"  # citação de seção do PRD
)

_DEFAULT_WINDOW = 4  # linhas para cada lado — proxy de "mesmo parágrafo/bullet"


@dataclass(frozen=True)
class Problem:
    line: int
    text: str


def parse_added_lines(diff_text: str) -> dict[int, str]:
    """Extrai {número da linha no arquivo NOVO: conteúdo} de um diff unificado
    com `--unified=0` (só linhas modificadas, sem contexto — cada linha do
    corpo do hunk é `+` ou `-`, nunca contexto). Linhas removidas (`-`) não
    consomem numeração do arquivo novo."""
    added: dict[int, str] = {}
    new_lineno = 0
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            if match:
                new_lineno = int(match.group(1))
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added[new_lineno] = line[1:]
            new_lineno += 1
        elif line.startswith("-"):
            continue
        else:
            # unified=0 não deveria emitir linha de contexto; se emitir por
            # algum motivo (ex. linha "\ No newline at end of file"), não
            # conta como número de linha novo.
            continue
    return added


def _paragraph_window(lineno: int, lines: list[str], max_distance: int) -> tuple[int, int]:
    """(início, fim) 1-based do parágrafo/bullet ao redor de `lineno` — para
    de expandir em linha em branco (fronteira de parágrafo em markdown) ou em
    `max_distance` linhas, o que vier primeiro."""
    n = len(lines)
    start = lineno
    while start > 1 and start - 1 >= lineno - max_distance and lines[start - 2].strip() != "":
        start -= 1
    end = lineno
    while end < n and end + 1 <= lineno + max_distance and lines[end].strip() != "":
        end += 1
    return start, end


def _is_skipped(lineno: int, lines: list[str]) -> bool:
    line_text = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ""
    prev_text = lines[lineno - 2] if 0 <= lineno - 2 < len(lines) else ""
    return _SKIP_MARKER in line_text or _SKIP_MARKER in prev_text


def check_diff(
    diff_text: str, new_file_lines: list[str], window: int = _DEFAULT_WINDOW
) -> list[Problem]:
    """Para cada linha ADICIONADA no diff que contém um número, confere se há
    referência reconhecível na janela ao redor (no conteúdo do arquivo NOVO,
    não só nas linhas adicionadas — uma referência já existente no parágrafo
    antes da edição conta)."""
    problems: list[Problem] = []
    added = parse_added_lines(diff_text)
    for lineno in sorted(added):
        content = added[lineno]
        if not _NUMBER_RE.search(content):
            continue
        if _is_skipped(lineno, new_file_lines):
            continue
        start, end = _paragraph_window(lineno, new_file_lines, window)
        window_text = "\n".join(new_file_lines[start - 1 : end])
        if _REFERENCE_RE.search(window_text):
            continue
        problems.append(Problem(lineno, content))
    return problems


def _git_diff(base: str, path: Path, cwd: Path) -> str | None:
    # encoding="utf-8" explícito, não text=True — mesmo motivo documentado em
    # check_constants_referenced.py::_read_staged: o default de texto do
    # subprocess no Windows segue a codepage do console (cp1252), que quebra
    # nos acentos do português presentes em docs/SPRINT_LOG.md.
    try:
        rel = path.resolve().relative_to(cwd.resolve()).as_posix()
    except ValueError:
        rel = str(path)
    result = subprocess.run(
        ["git", "diff", "--unified=0", base, "--", rel],
        capture_output=True,
        encoding="utf-8",
        cwd=cwd,
    )
    if result.returncode != 0 or result.stdout is None:
        return None
    return result.stdout


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows usa cp1252 por padrão

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--path", type=Path, default=Path("docs/SPRINT_LOG.md"))
    parser.add_argument(
        "--base",
        default="HEAD",
        help="ref git para diff (padrão HEAD — uso local/pre-commit; CI usa HEAD~1)",
    )
    parser.add_argument("--window", type=int, default=_DEFAULT_WINDOW)
    args = parser.parse_args()

    if not args.path.exists():
        _out(f"check_sprint_log_references: {args.path} não existe — nada a verificar.")
        return 0

    diff_text = _git_diff(args.base, args.path, Path.cwd())
    if diff_text is None:
        _out(
            f"check_sprint_log_references: não foi possível calcular `git diff {args.base}` "
            f"para {args.path} (não é repo git, ref inexistente — ex. HEAD~1 num checkout raso "
            "sem histórico suficiente, ou primeiro commit). Nada a verificar."
        )
        return 0

    if not diff_text.strip():
        _out(f"check_sprint_log_references: {args.path} sem mudanças contra {args.base}.")
        return 0

    new_file_lines = args.path.read_text(encoding="utf-8").splitlines()
    problems = check_diff(diff_text, new_file_lines, window=args.window)

    if problems:
        _out(
            f"check_sprint_log_references: {len(problems)} linha(s) nova(s) com número sem "
            f"referência reconhecível a até {args.window} linhas de distância "
            "(HEURÍSTICO — ver docstring do módulo; falso positivo? adicione "
            f"`{_SKIP_MARKER}` na linha anterior):\n"
        )
        for p in problems:
            _out(f"  {args.path}:{p.line} — {p.text.strip()!r}")
        return 1

    _out(f"check_sprint_log_references: OK — nenhuma linha nova sem referência (base={args.base}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
