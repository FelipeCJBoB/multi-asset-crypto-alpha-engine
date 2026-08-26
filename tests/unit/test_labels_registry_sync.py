"""Testes do detector de linhagem `labels.parquet` <-> registro do Label
Engine (ADR-005 §13 v2 §13.11, item 3b de §13.17, `AG-309`).

Tudo em `tmp_path`: nenhum teste lê o `data/` real, então o resultado não
depende de qual backfill existe na máquina. O que os testes protegem é a
regra de casamento — e ela tem uma sutileza que é fácil de errar: casar só
por `config_hash` GLOBAL seria frouxo, porque o mesmo hash de config vale
para os 5 símbolos, então um único símbolo registrado faria os outros
quatro passarem. O casamento é por `(symbol, grade, config_hash)`.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from src.labels.experiment_log import (
    find_unregistered_label_artifacts,
    label_artifact_config_hash,
)


def _labels(path: Path, config_hash: str, n: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"config_hash": [config_hash] * n}).write_parquet(path)


def _registro(path: Path, linhas: list[dict[str, str | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = {"symbol": pl.Utf8, "tf": pl.Utf8, "resolution_id": pl.Utf8, "config_hash": pl.Utf8}
    pl.DataFrame(linhas, schema=schema).write_parquet(path)


def test_artefato_com_linha_correspondente_nao_e_reportado(tmp_path: Path) -> None:
    root = tmp_path / "labels"
    log = tmp_path / "log.parquet"
    _labels(root / "BTCUSDT" / "R1" / "v1" / "labels.parquet", "abc123")
    _registro(
        log, [{"symbol": "BTCUSDT", "tf": None, "resolution_id": "R1", "config_hash": "abc123"}]
    )
    assert find_unregistered_label_artifacts(labels_root=root, log_path=log) == ()


def test_hash_divergente_e_reportado_com_os_dois_lados(tmp_path: Path) -> None:
    """O caso real medido em 2026-08-26: disco `3599b765b7a53ff2`, registro
    `67d2193fff4a1fae` — 20 de 20 artefatos."""
    root = tmp_path / "labels"
    log = tmp_path / "log.parquet"
    _labels(root / "BTCUSDT" / "R1" / "v1" / "labels.parquet", "novo_hash")
    _registro(
        log, [{"symbol": "BTCUSDT", "tf": None, "resolution_id": "R1", "config_hash": "velho"}]
    )
    (achado,) = find_unregistered_label_artifacts(labels_root=root, log_path=log)
    assert achado.symbol == "BTCUSDT"
    assert achado.grade == "R1"
    assert achado.config_hash_no_disco == "novo_hash"
    assert achado.config_hashes_no_registro == ("velho",)


def test_casamento_NAO_e_por_hash_global_e_sim_por_celula(tmp_path: Path) -> None:
    """A sutileza que o detector existe para não errar: o mesmo
    `config_hash` vale para os 5 símbolos. Registrar UM símbolo não pode
    fazer os outros quatro passarem."""
    root = tmp_path / "labels"
    log = tmp_path / "log.parquet"
    for sym in ("BTCUSDT", "ETHUSDT"):
        _labels(root / sym / "R1" / "v1" / "labels.parquet", "mesmo_hash")
    _registro(
        log, [{"symbol": "BTCUSDT", "tf": None, "resolution_id": "R1", "config_hash": "mesmo_hash"}]
    )
    achados = find_unregistered_label_artifacts(labels_root=root, log_path=log)
    assert [a.symbol for a in achados] == ["ETHUSDT"]


def test_grade_diferente_do_mesmo_simbolo_nao_conta_como_cobertura(tmp_path: Path) -> None:
    """Registrar R1 não cobre R3, mesmo com o símbolo certo."""
    root = tmp_path / "labels"
    log = tmp_path / "log.parquet"
    _labels(root / "BTCUSDT" / "R3" / "v1" / "labels.parquet", "h3")
    _registro(log, [{"symbol": "BTCUSDT", "tf": None, "resolution_id": "R1", "config_hash": "h3"}])
    (achado,) = find_unregistered_label_artifacts(labels_root=root, log_path=log)
    assert achado.grade == "R3"


def test_grade_de_relogio_casa_pela_coluna_tf(tmp_path: Path) -> None:
    """O schema é XOR: `resolution_id` sob dollar bar, `tf` sob relógio.
    O detector precisa ler os dois."""
    root = tmp_path / "labels"
    log = tmp_path / "log.parquet"
    _labels(root / "BTCUSDT" / "15m" / "v1" / "labels.parquet", "h15")
    _registro(
        log, [{"symbol": "BTCUSDT", "tf": "15m", "resolution_id": None, "config_hash": "h15"}]
    )
    assert find_unregistered_label_artifacts(labels_root=root, log_path=log) == ()


def test_celula_sem_nenhuma_linha_no_registro_reporta_lista_vazia(tmp_path: Path) -> None:
    root = tmp_path / "labels"
    log = tmp_path / "log.parquet"
    _labels(root / "SOLUSDT" / "R2" / "v1" / "labels.parquet", "hx")
    _registro(log, [{"symbol": "BTCUSDT", "tf": None, "resolution_id": "R1", "config_hash": "hx"}])
    (achado,) = find_unregistered_label_artifacts(labels_root=root, log_path=log)
    assert achado.config_hashes_no_registro == ()


def test_raiz_de_labels_inexistente_devolve_vazio_em_vez_de_estourar(tmp_path: Path) -> None:
    log = tmp_path / "log.parquet"
    _registro(log, [])
    assert (
        find_unregistered_label_artifacts(labels_root=tmp_path / "nao_existe", log_path=log) == ()
    )


def test_artefato_com_mais_de_um_config_hash_falha_alto(tmp_path: Path) -> None:
    """Mesmo espírito de `B15`/`verify_config_hash`, aplicado ao artefato:
    um arquivo que mistura regimes de label não descreve nenhum deles."""
    path = tmp_path / "labels.parquet"
    pl.DataFrame({"config_hash": ["a", "a", "b"]}).write_parquet(path)
    with pytest.raises(ValueError, match="combina 2 config_hash"):
        label_artifact_config_hash(path)


def test_artefato_com_hash_unico_devolve_o_hash(tmp_path: Path) -> None:
    path = tmp_path / "labels.parquet"
    pl.DataFrame({"config_hash": ["so_um"] * 5}).write_parquet(path)
    assert label_artifact_config_hash(path) == "so_um"
