"""Sanity check do linter de banned patterns — detecta o que promete detectar,
e não falso-positiva no scaffolding vazio."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lint"))

import banned_patterns as bp  # noqa: E402


def test_scaffolding_vazio_nao_viola(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text('"""stub"""\n', encoding="utf-8")
    assert bp.scan(tmp_path) == []


def test_detecta_print(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("print('debug')\n", encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "B28" in ids


def test_detecta_pandas_sem_marca_interop(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("import pandas as pd\n", encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "B26" in ids


def test_pandas_marcado_interop_nao_viola(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("import pandas as pd  # noqa: interop-only\n", encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "B26" not in ids


def test_detecta_hmmlearn(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("from hmmlearn import hmm\n", encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "B21" in ids


def test_detecta_multi_softprob(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text('objective = "multi:softprob"\n', encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "B18" in ids


def test_detecta_contract_price(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text('working_type = "CONTRACT_PRICE"\n', encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "B12" in ids


def test_detecta_enable_withdraw(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("enable_withdraw = true\n", encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "B30" in ids


def test_detecta_magic_number_float(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("risk_per_trade = 0.005\n", encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "MAGIC_NUMBER" in ids


def test_magic_number_com_noqa_nao_viola(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("risk_per_trade = 0.005  # noqa: magic-number\n", encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "MAGIC_NUMBER" not in ids


def test_literais_triviais_permitidos(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("x = 0.5\ny = -1.0\n", encoding="utf-8")
    ids = {v.pattern_id for v in bp.scan(tmp_path)}
    assert "MAGIC_NUMBER" not in ids
