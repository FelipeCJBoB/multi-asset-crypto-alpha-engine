"""Verifica os 32 banned patterns do CLAUDE.md contra o código do pipeline.

Nem todo padrão banido é detectável por análise estática — vários (B01, B02, B05,
B14 etc.) são arquiteturais/semânticos e exigem revisão humana ou teste de
integração dedicado (ex.: teste de causalidade, teste de paridade). Este script
NÃO finge cobertura que não tem: cada padrão é marcado `automated=True/False` no
registro abaixo, e o relatório separa "violações encontradas" de "não
automatizável — ver DoD/checklist de PR".

Também aplica a Regra 1 do registro de proveniência (§16.10.2): nenhum literal
numérico solto em código de pipeline, fora de `config/constants.yaml`. Todo
`float` é verificado sem restrição de contexto; `int` é verificado só em
kwarg nomeado de chamada ou default de parâmetro de função -- ver docstring
de `_check_int_keyword_or_default_literals` pra por que o escopo de `int` é
deliberadamente mais estreito (achado 2026-08-24: espelhar a lógica de
`float` pra `int` sem restringir contexto gera centenas de falso positivo
estrutural — `range(N)`, índice, slice — não bug real).

Uso:
    python tools/lint/banned_patterns.py [--path src] [--strict]

--strict (usado por pre-commit/CI): sai com código 1 se qualquer violação
automatizada for encontrada. Sem --strict, só reporta.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Literais considerados triviais o bastante para não exigir constants.yaml —
# índices, contagens de base 0/1, sinais. Qualquer outro float literal em
# src/ é reportado.
_ALLOWED_NUMERIC_LITERALS: frozenset[float] = frozenset({0.0, 1.0, -1.0, 2.0, 0.5})

# Espelha _ALLOWED_NUMERIC_LITERALS (mesmos 4 valores estruturais, sem o 0.5
# fracionário que não tem equivalente inteiro) -- ver docstring de
# _check_int_keyword_or_default_literals logo abaixo pra por que a whitelist
# de int NÃO é uma cópia ingênua da lógica de float.
_ALLOWED_INT_LITERALS: frozenset[int] = frozenset({-1, 0, 1, 2})

_NOQA_MAGIC_NUMBER = "noqa: magic-number"


@dataclass(frozen=True)
class Pattern:
    id: str
    category: str
    description: str
    anchor: str
    automated: bool


PATTERNS: tuple[Pattern, ...] = (
    # Vazamento temporal
    Pattern("B01", "vazamento_temporal", "filtros de instrumento atuais em dado histórico — usar load_filters_asof(t)", "§1.4", False),
    Pattern("B02", "vazamento_temporal", "quantil/z-score com índice >= t — janela expansiva estrita < t", "§2.0", False),
    Pattern("B03", "vazamento_temporal", "scaler ajustado no dataset inteiro — expansivo ou por fold", "§11.5 #8", False),
    Pattern("B04", "vazamento_temporal", "seleção de feature fora do fold", "§11.5 #12", False),
    Pattern("B05", "vazamento_temporal", "HMM/regime ajustado na série toda e predito barra a barra", "§5.2", False),
    Pattern("B06", "vazamento_temporal", "tabela de IC de 7 anos usada para configurar modelo — triagem in-fold", "§5.3", False),
    # Vazamento estrutural
    Pattern("B07", "vazamento_estrutural", "Meta treinado em predição do Alpha sem is_oof", "§5.12", True),
    Pattern("B08", "vazamento_estrutural", "calibrador ajustado sobre o próprio OOF", "§5.9 passo 9", False),
    Pattern("B09", "vazamento_estrutural", "split de CV sem purge por t1", "§11.4", False),
    Pattern("B10", "vazamento_estrutural", "treino sem sample_weight de unicidade", "§3.5", False),
    # Label e execução
    Pattern("B11", "label_execucao", "barreira avaliada em high/low da barra de 15m — usar mark_1m", "§3.4", False),
    Pattern("B12", "label_execucao", "stop com working_type: CONTRACT_PRICE — usar MARK_PRICE", "§9.1", True),
    Pattern("B13", "label_execucao", "ordem limite convertida em market no timeout — on_timeout: CANCEL", "§9.1", True),
    Pattern("B14", "label_execucao", "TP postado antes do SL após fill — SL sempre primeiro", "§16.2", False),
    Pattern("B15", "label_execucao", "config_hash do label != o da execução", "§3.4", False),
    Pattern("B16", "label_execucao", "ordem enviada com outra em UNKNOWN", "§9.7", False),
    Pattern("B17", "label_execucao", "cache local de equity — reconciliação é a única fonte", "§8.7", True),
    # Modelo
    Pattern("B18", "modelo", "multi:softprob/multiclass(ova) — usar M_long/M_short", "§5.2", True),
    Pattern("B19", "modelo", "colsample_bytree/feature_fraction < 1.0 c/ bagging", "§5.10", True),
    Pattern("B20", "modelo", "threshold escolhido por métrica OOS — a priori pelo orçamento de fees", "§5.6", False),
    Pattern("B21", "modelo", "hmmlearn — determinístico por quantis; dynamax na V1.1", "§14.1", True),
    Pattern("B22", "modelo", "retreinar após sequência de perdas — cadência fixa declarada a priori", "§16.4", False),
    Pattern("B23", "modelo", "faixa esperada inventada em doc ou teste — 'TBD — medir no Sprint N'", "§16.10 M4", False),
    Pattern("B24", "modelo", "N_eff = n/h ou 1+s(2h-1) como constante — medir Σ uniqueness", "§0.2 R4", True),
    Pattern("B25", "modelo", "presumir ATR de volatilidade anualizada — medir dos klines", "§0.4", False),
    # Stack e operação
    Pattern("B26", "stack_operacao", "Pandas no core — Polars lazy; Pandas só em interop de borda", "§14.1", True),
    Pattern("B27", "stack_operacao", "pip/venv/conda — uv + lockfile", "§14.1", True),
    Pattern("B28", "stack_operacao", "print() — structlog + orjson", "§14.1", True),
    Pattern("B29", "stack_operacao", "escrita não-atômica — .tmp -> fsync -> rename", "§1.2", False),
    Pattern("B30", "stack_operacao", "enable_withdraw: true na chave de API — jamais", "§16.7", True),
    Pattern("B31", "stack_operacao", "chave em código, config versionada, log ou mensagem de erro", "§16.7", True),
    Pattern("B32", "stack_operacao", "assinar REST sem percent-encode antes — senão -1022", "§9.4", False),
)

_AUTOMATED = {p.id: p for p in PATTERNS if p.automated}


@dataclass(frozen=True)
class Violation:
    pattern_id: str
    file: Path
    line: int
    detail: str


def _iter_py_files(root: Path) -> list[Path]:
    """`root` pode ser um arquivo único ou um diretório — `Path.rglob` só
    itera diretórios; num arquivo, devolve vazio silenciosamente (mesma classe
    de bug já corrigida em `check_unguarded_ratios.py`/`check_constants_
    referenced.py`, commit `1182146`, 2026-08-09: `--path <arquivo>` reportava
    "nenhuma violação encontrada" sem nunca ler o arquivo — falso negativo,
    não ausência real de violação. `banned_patterns.py` tem o mesmo padrão
    `_iter_py_files` dos outros dois scripts mas nunca recebeu o mesmo fix,
    apesar de ser invocado com `--path <arquivo>` pela mesma skill de
    auditoria e pela exceção nomeada de `CLAUDE.md` — achado real desta
    sessão, 2026-08-17)."""
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _int_magic_number_violation(
    path: Path, node: ast.expr, lines: list[str], context: str
) -> Violation | None:
    """`node` é o valor de um kwarg de chamada ou de um default de função
    (ver `_check_int_keyword_or_default_literals`). Devolve `Violation` se
    for um `int` literal fora da whitelist estrutural e sem `noqa`; `None`
    caso contrário (não é `ast.Constant`, é `bool`, está na whitelist, ou
    tem noqa na linha)."""
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    # bool é subclasse de int em Python (isinstance(True, int) is True) --
    # True/False como kwarg/default (ex. strict=True) não é magic number.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value in _ALLOWED_INT_LITERALS:
        return None
    line_text = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
    if _NOQA_MAGIC_NUMBER in line_text:
        return None
    detail = f"literal int {value!r} como {context} fora de constants.yaml"
    return Violation("MAGIC_NUMBER", path, node.lineno, detail)


def _check_int_keyword_or_default_literals(
    path: Path, tree: ast.AST, lines: list[str]
) -> list[Violation]:
    """Regra 1 (§16.10.2), extensão pra `int` (achado de varredura: o check
    original só olhava `float` via `isinstance(node.value, float)` -- todo
    `int` mágico em `src/` passava 100% despercebido).

    Espelhar a lógica de `float` ingenuamente (qualquer `ast.Constant`
    inteiro solto no corpo, sem restrição de contexto) explode em falso
    positivo: inteiro pequeno é MUITO mais comum como índice/contador/
    tamanho estrutural (`range(10)`, `for i in range(3)`, slicing,
    `shape[1]`, tamanho de tupla) do que como hiperparâmetro de domínio --
    MEDIDO nesta sessão, não hipotético: uma sonda temporária que aplicava
    o mesmo `isinstance(node.value, int) and not in _ALLOWED_INT_LITERALS`
    de baixo SEM a restrição de contexto (kwarg/default) rodada via
    `python tools/lint/banned_patterns.py --path src --strict` (comando
    mecânico autorizado) achou 352 "violações" em `src/` inteiro -- contra
    27 achados reais no escopo restrito abaixo (mais 23 `float` já
    pré-existentes ao check de `int`), no mesmo `src/`. Confirma a ordem de
    grandeza "centenas" citada como sinal de alarme na instrução original
    desta tarefa -- não é o repo tendo centenas de hiperparâmetros
    escondidos, é ruído estrutural (`range(N)`, índices de slice, literais
    de teste/fixture) dominando a contagem sem o filtro de contexto.

    Escopo adotado, deliberadamente mais estreito que o de `float`: só
    literais `int` usados como (a) valor de KWARG NOMEADO numa chamada
    (`ast.Call.keywords`, ex. `num_iters=100`) ou (b) DEFAULT DE PARÂMETRO
    numa `def`/`async def` (`ast.arguments.defaults`/`kw_defaults`, ex.
    `def f(x: int = 100)`). Essas duas posições são onde hiperparâmetro
    numérico de fato aparece em código Python idiomático deste repo (ver
    `_DEFAULT_NUM_EM_ITERS`/`_DEFAULT_STICKY_CONCENTRATION` em
    `src/regime/hmm_gaussian.py`, achado real que motivou esta extensão) --
    argumento POSICIONAL (`foo(100)`), literal em subscript/slice, e
    literal solto em expressão/corpo continuam FORA do escopo, de propósito:
    são estruturais na esmagadora maioria dos casos (`range(N)`, índice,
    tamanho de tupla) e não têm marcador sintático que os distinga de um
    hiperparâmetro real sem heurística muito mais cara (teria que inferir o
    NOME do parâmetro posicional via assinatura da função chamada, fora do
    alcance de um lint estático de arquivo único)."""
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg is None:  # **kwargs unpacking, não é kwarg nomeado
                    continue
                v = _int_magic_number_violation(path, kw.value, lines, f"kwarg '{kw.arg}'")
                if v is not None:
                    violations.append(v)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            defaults = list(args.defaults) + [d for d in args.kw_defaults if d is not None]
            for default_node in defaults:
                v = _int_magic_number_violation(
                    path, default_node, lines, f"default de parâmetro em '{node.name}'"
                )
                if v is not None:
                    violations.append(v)
    return violations


def _check_ast(path: Path, tree: ast.AST, source: str) -> list[Violation]:
    violations: list[Violation] = []
    lines = source.splitlines()
    violations.extend(_check_int_keyword_or_default_literals(path, tree, lines))

    for node in ast.walk(tree):
        # B28 — print()
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            violations.append(Violation("B28", path, node.lineno, "print() encontrado — usar structlog"))

        # B26 — import pandas (interop de borda deve usar `import pandas  # noqa: interop-only`)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if name.split(".")[0] == "pandas":
                    line_text = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                    if "noqa: interop-only" not in line_text:
                        violations.append(Violation("B26", path, node.lineno, "import pandas fora de interop de borda marcada"))
                if name.split(".")[0] == "hmmlearn":
                    violations.append(Violation("B21", path, node.lineno, "import hmmlearn — proibido, usar quantis/dynamax"))

        # Regra 1 (§16.10.2) — literal numérico solto fora de config/constants.yaml
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            if node.value not in _ALLOWED_NUMERIC_LITERALS:
                line_text = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                if _NOQA_MAGIC_NUMBER not in line_text:
                    violations.append(
                        Violation("MAGIC_NUMBER", path, node.lineno, f"literal {node.value!r} fora de constants.yaml")
                    )

    return violations


def _check_text(path: Path, source: str) -> list[Violation]:
    violations: list[Violation] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        if re.search(r"CONTRACT_PRICE", line):
            violations.append(Violation("B12", path, lineno, "working_type: CONTRACT_PRICE — deve ser MARK_PRICE"))
        if re.search(r"multi:softprob|multiclass(ova)?[\"']", line):
            violations.append(Violation("B18", path, lineno, "multi:softprob/multiclass(ova) — usar M_long/M_short"))
        if re.search(r"(colsample_bytree|feature_fraction)[\"']?\s*[:=]\s*0\.\d", line):
            violations.append(
                Violation("B19", path, lineno, "colsample_bytree/feature_fraction < 1.0 — usar 1.0")
            )
        if re.search(r"on_timeout[\"']?\s*[:=]\s*[\"']?MARKET(?!_reduce_only)", line):
            violations.append(Violation("B13", path, lineno, "on_timeout convertendo para MARKET na entrada — deve ser CANCEL"))
        if re.search(r"enable_withdraw[\"']?\s*[:=]\s*true", line, re.IGNORECASE):
            violations.append(Violation("B30", path, lineno, "enable_withdraw: true — jamais, em nenhuma circunstância"))
        if re.search(r"equity_source[\"']?\s*[:=]\s*[\"'](?!reconciliation)", line):
            violations.append(Violation("B17", path, lineno, "equity_source != reconciliation — cache local de equity proibido"))
        if re.search(r"\b(1\s*\+\s*s\s*\*\s*\(2\s*\*?\s*h\s*-\s*1\)|n\s*/\s*h\b)", line):
            violations.append(Violation("B24", path, lineno, "fórmula fechada de N_eff — medir Σ uniqueness, não estipular"))
        # heurística de segredo: string longa alfanumérica atribuída a var com nome suspeito
        if re.search(r"(?i)(api_key|secret|signature)\s*=\s*[\"'][A-Za-z0-9+/_-]{20,}[\"']", line):
            violations.append(Violation("B31", path, lineno, "possível segredo em código — usar variável de ambiente"))
    return violations


#: B07 (D-13, §10.4 do design doc do Meta) — correção da v1: a regra
#: original ("todo arquivo em `src/models/` que menciona `predictions.
#: parquet`/`p_alpha`/`p_long`/`p_short` precisa mencionar `is_oof`")
#: quebraria o build de cara: `pipeline.py` (orquestrador) e `_paths.py`
#: (helper de caminho) mencionam os gatilhos sem nunca precisar tocar em
#: `is_oof` — falsos positivos legítimos, não achados reais. Regra
#: corrigida: só arquivos que mencionem o gatilho E `fit`/`train` (como
#: TOKEN — `\b`, não substring: não pega `train_idx`/`fit_side_model`,
#: que são identificadores compostos, não o verbo isolado).
#: `persistence.py` — sobre FORMATO de serialização (calibrador/learner
#: como coef/intercept crus, sem `pickle`), agnóstico a se o `fit`
#: upstream usou OOF ou não; essa garantia é de `fit_side_model`/
#: `run_meta_fold` (arquivos onde o token `is_oof` de fato importa), não
#: de como o resultado do fit é gravado em disco depois.
_B07_ALLOWLIST: frozenset[str] = frozenset({"pipeline.py", "_paths.py", "persistence.py"})
_B07_TRIGGER_RE = re.compile(r"predictions\.parquet|\bp_alpha\b|\bp_long\b|\bp_short\b")
_B07_FIT_TRAIN_RE = re.compile(r"\bfit\b|\btrain\b")
_B07_IS_OOF_RE = re.compile(r"\bis_oof\b")


def _check_b07_meta_is_oof(path: Path, source: str) -> list[Violation]:
    """B07 — cobertura PARCIAL declarada (grep de arquivo inteiro, não
    prova de fluxo de dado): sinaliza quando um arquivo em `src/models/`
    referencia sinal do Alpha (`predictions.parquet`/`p_alpha`/`p_long`/
    `p_short`) e treina algo (`fit`/`train` como token) sem NUNCA
    mencionar `is_oof` em lugar nenhum do arquivo — nem no código, nem em
    comentário/docstring explicando de onde vem a garantia. Reportar
    `automated=True` com esta cobertura parcial é estritamente melhor que
    `automated=False` (§10.4 do design doc do Meta) — não prova ausência
    de vazamento, mas transforma "ninguém documentou de onde vem o OOF"
    de silêncio em achado."""
    if path.name in _B07_ALLOWLIST:
        return []
    if not (_B07_TRIGGER_RE.search(source) and _B07_FIT_TRAIN_RE.search(source)):
        return []
    if _B07_IS_OOF_RE.search(source):
        return []
    return [
        Violation(
            "B07",
            path,
            1,
            "menciona sinal do Alpha (predictions.parquet/p_alpha/p_long/p_short) e "
            "fit/train, mas nunca menciona is_oof — sem referência de onde vem a "
            "garantia de OOF (mesmo em comentário), documente ou adicione a "
            "allowlist com justificativa",
        )
    ]


def _check_repo_root(root: Path) -> list[Violation]:
    """B27 — nenhum artefato de pip/venv/conda no root do projeto."""
    violations: list[Violation] = []
    project_root = root.parent if root.name == "src" else root
    for forbidden in ("requirements.txt", "Pipfile", "environment.yml", "environment.yaml"):
        candidate = project_root / forbidden
        if candidate.exists():
            violations.append(Violation("B27", candidate, 1, f"{forbidden} presente — projeto usa uv + lockfile, não pip/venv/conda"))
    return violations


def scan(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    violations.extend(_check_repo_root(path))
    for py_file in _iter_py_files(path):
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as exc:
            violations.append(Violation("SYNTAX_ERROR", py_file, exc.lineno or 1, str(exc)))
            continue
        violations.extend(_check_ast(py_file, tree, source))
        violations.extend(_check_text(py_file, source))
        if "models" in py_file.parts:
            violations.extend(_check_b07_meta_is_oof(py_file, source))
    return violations


def _report(violations: list[Violation]) -> None:
    if not violations:
        print("banned_patterns: nenhuma violação automatizada encontrada.")
    else:
        print(f"banned_patterns: {len(violations)} violação(ões) encontrada(s):\n")
        for v in violations:
            desc = _AUTOMATED.get(v.pattern_id)
            anchor = desc.anchor if desc else "§16.10.2 (Regra 1)"
            print(f"  [{v.pattern_id}] {v.file}:{v.line} — {v.detail} ({anchor})")

    manual = [p for p in PATTERNS if not p.automated]
    print(f"\n{len(manual)} padrões NÃO são verificáveis por este script — revisão humana obrigatória em PR:")
    for p in manual:
        print(f"  [{p.id}] {p.description} ({p.anchor})")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows usa cp1252 por padrão

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path("src"))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"banned_patterns: caminho {args.path} não existe — nada a verificar (scaffolding ainda vazio).")
        return 0

    violations = scan(args.path)
    _report(violations)

    if args.strict and violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
