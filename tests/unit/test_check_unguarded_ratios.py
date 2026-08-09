"""Testes de `check_unguarded_ratios.py` — cobre a exclusão de literal
numérico e de junção de caminho (`pathlib.Path.__truediv__` usa o mesmo nó
AST que divisão aritmética — achado real ao rodar o script pela primeira
vez contra `src/`, ver `docs/SPRINT_LOG.md`), a detecção de guarda de sinal
(`if`/`assert`, `try/except ZeroDivisionError`), e a supressão explícita
via `# noqa: unguarded-ratio`."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lint"))

import check_unguarded_ratios as cur


def _findings(tmp_path: Path, code: str) -> list[cur.Finding]:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "mod.py").write_text(code, encoding="utf-8")
    return cur.find_findings(src)


# --------------------------------------------------------------------------
# exclusões — não são razão de dado variável
# --------------------------------------------------------------------------


def test_ignora_divisao_por_literal_numerico(tmp_path: Path) -> None:
    findings = _findings(tmp_path, "def f(bps):\n    return bps / 10000\n")
    assert findings == []


def test_ignora_juncao_de_caminho_com_string_literal(tmp_path: Path) -> None:
    findings = _findings(tmp_path, "def f(root):\n    return root / 'config' / 'constants.yaml'\n")
    assert findings == []


def test_ignora_juncao_de_caminho_por_nome_de_variavel_dir(tmp_path: Path) -> None:
    # sem literal string nenhum — só o padrão de nome (*_DIR) identifica
    findings = _findings(
        tmp_path,
        "def f(CAPACITY_DIR, source, symbol):\n    return CAPACITY_DIR / source / symbol\n",
    )
    assert findings == []


def test_ignora_juncao_de_caminho_via_path_root(tmp_path: Path) -> None:
    findings = _findings(tmp_path, "def f(root, name):\n    return root / name\n")
    assert findings == []


# --------------------------------------------------------------------------
# achados reais — razão de denominador variável
# --------------------------------------------------------------------------


def test_detecta_divisao_com_denominador_variavel(tmp_path: Path) -> None:
    findings = _findings(tmp_path, "def f(a, b):\n    return a / b\n")
    assert len(findings) == 1
    assert findings[0].denominator == "b"
    assert not findings[0].guarded
    assert not findings[0].suppressed


def test_denominador_com_atributo(tmp_path: Path) -> None:
    findings = _findings(tmp_path, "def f(sizing):\n    return sizing.risk_real / sizing.equity\n")
    assert len(findings) == 1
    assert findings[0].denominator == "sizing.equity"


# --------------------------------------------------------------------------
# guarda de sinal — if/assert/try-except
# --------------------------------------------------------------------------


def test_guarda_com_if_early_return_e_detectada(tmp_path: Path) -> None:
    code = "def f(a, b):\n    if b <= 0:\n        return None\n    return a / b\n"
    findings = _findings(tmp_path, code)
    assert len(findings) == 1
    assert findings[0].guarded


def test_guarda_com_assert_e_detectada(tmp_path: Path) -> None:
    code = "def f(a, b):\n    assert b > 0\n    return a / b\n"
    findings = _findings(tmp_path, code)
    assert findings[0].guarded


def test_guarda_com_try_except_zero_division_e_detectada(tmp_path: Path) -> None:
    code = (
        "def f(a, b):\n"
        "    try:\n"
        "        return a / b\n"
        "    except ZeroDivisionError:\n"
        "        return None\n"
    )
    findings = _findings(tmp_path, code)
    assert findings[0].guarded


def test_sem_guarda_nenhuma_e_reportado_como_nao_guardado(tmp_path: Path) -> None:
    code = (
        "def f(a, b):\n"
        "    if a > 0:\n"  # checa 'a', não o denominador 'b' — não conta como guarda
        "        pass\n"
        "    return a / b\n"
    )
    findings = _findings(tmp_path, code)
    assert not findings[0].guarded


def test_guarda_em_outra_funcao_nao_conta(tmp_path: Path) -> None:
    code = "def guarded(b):\n    if b <= 0:\n        return None\ndef f(a, b):\n    return a / b\n"
    findings = _findings(tmp_path, code)
    assert len(findings) == 1
    assert not findings[0].guarded


# --------------------------------------------------------------------------
# --path apontando pra um arquivo único, não um diretório — Path.rglob
# devolve vazio silenciosamente nesse caso (achado real de auditoria,
# ver docs/SPRINT_LOG.md); find_findings precisa tratar os dois casos.
# --------------------------------------------------------------------------


def test_detecta_divisao_quando_path_e_arquivo_unico(tmp_path: Path) -> None:
    mod = tmp_path / "mod.py"
    mod.write_text("def f(a, b):\n    return a / b\n", encoding="utf-8")
    findings = cur.find_findings(mod)
    assert len(findings) == 1
    assert not findings[0].guarded


# --------------------------------------------------------------------------
# supressão explícita
# --------------------------------------------------------------------------


def test_noqa_suprime_o_achado(tmp_path: Path) -> None:
    code = "def f(a, b):\n    return a / b  # noqa: unguarded-ratio — b eh len(), sempre >0\n"
    findings = _findings(tmp_path, code)
    assert len(findings) == 1
    assert findings[0].suppressed


# --------------------------------------------------------------------------
# CLI — --strict
# --------------------------------------------------------------------------


def test_main_strict_retorna_1_com_achado_nao_guardado_nem_suprimido(
    tmp_path: Path, monkeypatch: object
) -> None:
    import contextlib
    import io

    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def f(a, b):\n    return a / b\n", encoding="utf-8")

    argv = ["check_unguarded_ratios.py", "--path", str(src), "--strict"]
    monkeypatch.setattr(sys, "argv", argv)  # type: ignore[attr-defined]
    with contextlib.redirect_stdout(io.StringIO()):
        code = cur.main()
    assert code == 1


def test_main_sem_strict_retorna_0_mesmo_com_achado(tmp_path: Path, monkeypatch: object) -> None:
    import contextlib
    import io

    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def f(a, b):\n    return a / b\n", encoding="utf-8")

    argv = ["check_unguarded_ratios.py", "--path", str(src)]
    monkeypatch.setattr(sys, "argv", argv)  # type: ignore[attr-defined]
    with contextlib.redirect_stdout(io.StringIO()):
        code = cur.main()
    assert code == 0
