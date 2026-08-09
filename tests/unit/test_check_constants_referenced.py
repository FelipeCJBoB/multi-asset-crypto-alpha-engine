"""Testes de `check_constants_referenced.py` — cobre o AST-scan de
`load_constant("...")`, a checagem contra chaves definidas, e o caso real que
motivou o script: código+constants.yaml *staged* juntos no índice do git, mas
a chave referenciada só existe no working tree (não staged) — é isso que
teria pego o incidente de ~280 linhas de proveniência descrito em
`docs/SPRINT_LOG.md` (Fase H)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lint"))

import check_constants_referenced as ccr


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _init_repo(cwd: Path) -> None:
    _git("init", "-q", cwd=cwd)
    _git("config", "user.email", "test@example.com", cwd=cwd)
    _git("config", "user.name", "Test", cwd=cwd)


# --------------------------------------------------------------------------
# find_references — AST scan
# --------------------------------------------------------------------------


def test_find_references_detecta_chamada_simples(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text('x = load_constant("tick_size")\n', encoding="utf-8")

    refs = ccr.find_references(src)

    assert len(refs) == 1
    assert refs[0].name == "tick_size"
    assert refs[0].line == 1
    assert refs[0].file == src / "mod.py"


def test_find_references_detecta_chamada_qualificada(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text('x = _constants.load_constant("tick_size")\n', encoding="utf-8")

    refs = ccr.find_references(src)

    assert {r.name for r in refs} == {"tick_size"}


def test_find_references_ignora_argumento_nao_literal(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text(
        "name = 'tick_size'\nx = load_constant(name)\n",
        encoding="utf-8",
    )

    refs = ccr.find_references(src)

    assert refs == []


def test_find_references_multiplas_chamadas_varios_arquivos(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir(parents=True)
    (src / "a" / "mod.py").write_text('load_constant("foo")\n', encoding="utf-8")
    (src / "b" / "mod.py").write_text(
        'load_constant("bar")\nload_constant("baz")\n', encoding="utf-8"
    )

    refs = ccr.find_references(src)

    assert {r.name for r in refs} == {"foo", "bar", "baz"}


def test_find_references_ignora_syntax_error(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "broken.py").write_text("def (((\n", encoding="utf-8")

    assert ccr.find_references(src) == []


def test_find_references_com_path_de_arquivo_unico(tmp_path: Path) -> None:
    """`--src <arquivo>` (não diretório) — `Path.rglob` devolve vazio
    silenciosamente nesse caso (achado real de auditoria, ver
    docs/SPRINT_LOG.md); `find_references` precisa tratar os dois casos."""
    mod = tmp_path / "mod.py"
    mod.write_text('load_constant("tick_size")\n', encoding="utf-8")

    refs = ccr.find_references(mod)

    assert {r.name for r in refs} == {"tick_size"}


# --------------------------------------------------------------------------
# check() — comparação contra chaves definidas
# --------------------------------------------------------------------------


def test_check_falha_com_mensagem_clara_para_constante_ausente(tmp_path: Path) -> None:
    ref = ccr.Reference(name="nao_existe", file=tmp_path / "mod.py", line=7)

    problems = ccr.check([ref], defined={"tick_size"})

    assert len(problems) == 1
    assert "mod.py:7" in problems[0]
    assert "nao_existe" in problems[0]


def test_check_passa_quando_toda_referencia_tem_entrada(tmp_path: Path) -> None:
    refs = [
        ccr.Reference(name="tick_size", file=tmp_path / "mod.py", line=1),
        ccr.Reference(name="maker_fee", file=tmp_path / "mod.py", line=2),
    ]

    problems = ccr.check(refs, defined={"tick_size", "maker_fee", "outra_nao_referenciada"})

    assert problems == []


def test_keys_exclui_known_gaps() -> None:
    assert ccr._keys({"foo": {}, "known_gaps": {}}) == {"foo"}


# --------------------------------------------------------------------------
# load_constant_names — índice do git (staged) vs. working tree
#
# Este é o comportamento que resolve o incidente real: o hook precisa
# enxergar o que SERIA commitado, não o arquivo em disco.
# --------------------------------------------------------------------------


def test_load_constant_names_le_indice_staged_nao_worktree_sujo(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    constants_path = config_dir / "constants.yaml"
    constants_path.write_text("foo:\n  value: 1\n", encoding="utf-8")
    _git("add", "config/constants.yaml", cwd=tmp_path)

    # working tree agora diverge do índice (arquivo sujo, não re-staged) —
    # simula exatamente o incidente: a entrada certa nunca chegou ao commit.
    constants_path.write_text("bar:\n  value: 2\n", encoding="utf-8")

    keys, origin = ccr.load_constant_names(constants_path, prefer_staged=True)

    assert keys == {"foo"}
    assert "staged" in origin


def test_load_constant_names_worktree_flag_ignora_indice(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    constants_path = config_dir / "constants.yaml"
    constants_path.write_text("foo:\n  value: 1\n", encoding="utf-8")
    _git("add", "config/constants.yaml", cwd=tmp_path)
    constants_path.write_text("bar:\n  value: 2\n", encoding="utf-8")

    keys, origin = ccr.load_constant_names(constants_path, prefer_staged=False)

    assert keys == {"bar"}
    assert "working tree" in origin


def test_load_constant_names_fora_de_repo_git_cai_para_disco(tmp_path: Path) -> None:
    constants_path = tmp_path / "constants.yaml"
    constants_path.write_text("foo:\n  value: 1\n", encoding="utf-8")

    keys, origin = ccr.load_constant_names(constants_path, prefer_staged=True)

    assert keys == {"foo"}
    assert "fallback" in origin


def test_incidente_real_codigo_e_yaml_staged_juntos_mas_chave_so_no_disco(tmp_path: Path) -> None:
    """Reproduz o incidente: `.py` referenciando uma constante nova E
    `constants.yaml` com a entrada — ambos staged juntos — deve passar. Mas
    se a entrada só existir no disco (não staged), o hook deve falhar mesmo
    que `constants.yaml` "pareça" correto para quem olha o arquivo direto."""
    _init_repo(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (src / "mod.py").write_text('load_constant("nova_constante")\n', encoding="utf-8")
    constants_path = config_dir / "constants.yaml"
    constants_path.write_text("nova_constante:\n  value: 1\n", encoding="utf-8")
    _git("add", "src/mod.py", "config/constants.yaml", cwd=tmp_path)

    refs = ccr.find_references(src)
    defined, _origin = ccr.load_constant_names(constants_path, prefer_staged=True)
    assert ccr.check(refs, defined) == []

    # Agora simula o incidente real: alguém edita o .py pra referenciar OUTRA
    # constante nova, adiciona a entrada em constants.yaml no disco, mas
    # esquece de `git add` — só o .py foi staged.
    (src / "mod.py").write_text(
        'load_constant("nova_constante")\nload_constant("esquecida")\n',
        encoding="utf-8",
    )
    constants_path.write_text(
        "nova_constante:\n  value: 1\nesquecida:\n  value: 2\n",
        encoding="utf-8",
    )
    _git("add", "src/mod.py", cwd=tmp_path)  # só o .py — constants.yaml fica não-staged

    refs = ccr.find_references(src)
    defined, origin = ccr.load_constant_names(constants_path, prefer_staged=True)
    problems = ccr.check(refs, defined)

    assert "staged" in origin
    assert len(problems) == 1
    assert "esquecida" in problems[0]
