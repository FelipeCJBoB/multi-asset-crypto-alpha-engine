"""Testes de `check_resolution_id_guard_parity.py` (`AG-176`) — cobre
detecção de guarda contra `CALIBRATION_TF_BY_RESOLUTION`, confirmação de
`raise ValueError` no corpo verdadeiro, divergência de forma entre sites,
e que uma guarda em função aninhada/outro arquivo não se mistura.

Inclui um teste de integração que roda o script real contra `src/` do
próprio repo — trava o achado atual (4 sites, 1 forma, tudo consistente)
como regressão: se uma cópia futura divergir, este teste é o primeiro a
quebrar."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lint"))

import check_resolution_id_guard_parity as crgp

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _sites(tmp_path: Path, code: str, filename: str = "_paths.py") -> list[crgp.GuardSite]:
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True, exist_ok=True)
    (src / filename).write_text(code, encoding="utf-8")
    return crgp.find_guard_sites(tmp_path / "src")


# ============================================================================
# Detecção básica
# ============================================================================


def test_detecta_guarda_com_raise(tmp_path: Path) -> None:
    code = (
        "def f(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        raise ValueError('nao reconhecido')\n"
    )
    sites = _sites(tmp_path, code)
    assert len(sites) == 1
    assert sites[0].function == "f"
    assert sites[0].raises_valueerror
    assert sites[0].condition == "resolution_id not in CALIBRATION_TF_BY_RESOLUTION"


def test_ignora_arquivo_que_nao_e_paths_py(tmp_path: Path) -> None:
    sites = _sites(
        tmp_path,
        "def f(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        raise ValueError('x')\n",
        filename="not_paths.py",
    )
    assert sites == []


def test_ignora_arquivo_sem_nenhuma_guarda(tmp_path: Path) -> None:
    sites = _sites(tmp_path, "def f(a, b):\n    return a + b\n")
    assert sites == []


# ============================================================================
# Guarda sem raise — achado real que o script existe pra pegar
# ============================================================================


def test_guarda_sem_raise_e_reportada_como_nao_levanta(tmp_path: Path) -> None:
    code = (
        "def f(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        pass\n"  # nunca levanta -- cai silenciosamente
        "    return resolution_id\n"
    )
    sites = _sites(tmp_path, code)
    assert len(sites) == 1
    assert not sites[0].raises_valueerror


def test_guarda_com_outra_excecao_nao_conta_como_valueerror(tmp_path: Path) -> None:
    code = (
        "def f(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        raise KeyError('errado')\n"
    )
    sites = _sites(tmp_path, code)
    assert len(sites) == 1
    assert not sites[0].raises_valueerror


# ============================================================================
# Escopo por função — guarda aninhada não vaza pra função externa
# ============================================================================


def test_guarda_em_funcao_aninhada_pertence_so_a_ela(tmp_path: Path) -> None:
    code = (
        "def outer(resolution_id):\n"
        "    def inner(resolution_id):\n"
        "        if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "            raise ValueError('x')\n"
        "    return inner(resolution_id)\n"
    )
    sites = _sites(tmp_path, code)
    assert len(sites) == 1
    assert sites[0].function == "inner"


def test_duas_funcoes_mesma_condicao_sao_1_forma_distinta(tmp_path: Path) -> None:
    code = (
        "def a(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        raise ValueError('a')\n"
        "def b(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        raise ValueError('b')\n"
    )
    sites = _sites(tmp_path, code)
    assert len(sites) == 2
    assert len({s.condition for s in sites}) == 1


def test_condicao_divergente_e_detectada(tmp_path: Path) -> None:
    """Mesma checagem, mas uma cópia usa `self.resolution_id` (Attribute)
    em vez de `resolution_id` (Name) -- forma diferente, deveria ser
    sinalizado como divergência."""
    code = (
        "def a(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        raise ValueError('a')\n"
        "class C:\n"
        "    def b(self):\n"
        "        if self.resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "            raise ValueError('b')\n"
    )
    sites = _sites(tmp_path, code)
    assert len(sites) == 2
    assert len({s.condition for s in sites}) == 2


# ============================================================================
# CLI — --strict
# ============================================================================


def test_main_strict_retorna_1_com_guarda_sem_raise(
    tmp_path: Path, monkeypatch: object
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "_paths.py").write_text(
        "def f(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        pass\n",
        encoding="utf-8",
    )
    argv = ["check_resolution_id_guard_parity.py", "--path", str(src), "--strict"]
    monkeypatch.setattr(sys, "argv", argv)  # type: ignore[attr-defined]
    with contextlib.redirect_stdout(io.StringIO()):
        code = crgp.main()
    assert code == 1


def test_main_strict_retorna_1_com_condicao_divergente(
    tmp_path: Path, monkeypatch: object
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "_paths.py").write_text(
        "def a(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        raise ValueError('a')\n"
        "class C:\n"
        "    def b(self):\n"
        "        if self.resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "            raise ValueError('b')\n",
        encoding="utf-8",
    )
    argv = ["check_resolution_id_guard_parity.py", "--path", str(src), "--strict"]
    monkeypatch.setattr(sys, "argv", argv)  # type: ignore[attr-defined]
    with contextlib.redirect_stdout(io.StringIO()):
        code = crgp.main()
    assert code == 1


def test_main_sem_strict_retorna_0_mesmo_com_achado(tmp_path: Path, monkeypatch: object) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "_paths.py").write_text(
        "def f(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        pass\n",
        encoding="utf-8",
    )
    argv = ["check_resolution_id_guard_parity.py", "--path", str(src)]
    monkeypatch.setattr(sys, "argv", argv)  # type: ignore[attr-defined]
    with contextlib.redirect_stdout(io.StringIO()):
        code = crgp.main()
    assert code == 0


def test_main_path_arquivo_unico(tmp_path: Path, monkeypatch: object) -> None:
    p = tmp_path / "_paths.py"
    p.write_text(
        "def f(resolution_id):\n"
        "    if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    argv = ["check_resolution_id_guard_parity.py", "--path", str(p), "--strict"]
    monkeypatch.setattr(sys, "argv", argv)  # type: ignore[attr-defined]
    with contextlib.redirect_stdout(io.StringIO()):
        code = crgp.main()
    assert code == 0


def test_main_path_inexistente_nao_falha(tmp_path: Path, monkeypatch: object) -> None:
    argv = ["check_resolution_id_guard_parity.py", "--path", str(tmp_path / "nao_existe")]
    monkeypatch.setattr(sys, "argv", argv)  # type: ignore[attr-defined]
    with contextlib.redirect_stdout(io.StringIO()):
        code = crgp.main()
    assert code == 0


# ============================================================================
# Integração — trava o achado real do repo (4 sites, 1 forma) como regressão
# ============================================================================


def test_estado_real_do_repo_hoje_4_sites_1_forma_consistente() -> None:
    """`AG-176`: os 4 pacotes (`models`/`regime`/`labels`/`validation`)
    duplicam a mesma guarda de propósito -- este teste prova que, hoje,
    as 4 cópias são comportamentalmente idênticas (mesma condição, todas
    levantam `ValueError`). Se uma edição futura divergir uma cópia, este
    teste quebra primeiro -- é exatamente o "script mecânico" que a
    entrada do ledger propôs, agora também travado como regressão de
    teste, não só executável manualmente."""
    sites = crgp.find_guard_sites(_REPO_ROOT / "src")
    assert len(sites) == 4
    assert all(s.raises_valueerror for s in sites)
    assert len({s.condition for s in sites}) == 1
    assert {s.file.parent.name for s in sites} == {"models", "regime", "labels", "validation"}
