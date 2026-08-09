"""Testes de `src/core/provenance.py` — `report_provenance()`."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from src.core.provenance import report_provenance


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_report_provenance_tem_generated_at_e_code_version_dentro_de_um_repo_git() -> None:
    before = datetime.now(UTC)
    result = report_provenance()
    after = datetime.now(UTC)

    assert set(result.keys()) == {"generated_at", "code_version"}
    generated_at = datetime.fromisoformat(result["generated_at"])
    assert before <= generated_at <= after
    assert result["code_version"] != "unknown"
    assert len(result["code_version"]) == 7


def test_report_provenance_fora_de_repo_git_devolve_unknown_sem_levantar(tmp_path: Path) -> None:
    result = report_provenance(cwd=tmp_path)
    assert result["code_version"] == "unknown"
    # generated_at continua populado -- ausência de git não pode derrubar
    # a proveniência de tempo, só a de commit.
    datetime.fromisoformat(result["generated_at"])


def test_report_provenance_code_version_bate_com_git_rev_parse(tmp_path: Path) -> None:
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    _git("add", "f.txt", cwd=tmp_path)
    _git("commit", "-q", "-m", "init", cwd=tmp_path)

    expected = _git("rev-parse", "--short=7", "HEAD", cwd=tmp_path).stdout.strip()
    result = report_provenance(cwd=tmp_path)
    assert result["code_version"] == expected
