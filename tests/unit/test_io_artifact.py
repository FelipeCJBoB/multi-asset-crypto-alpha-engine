"""Testes de `src.io.artifact` — ADR-001 INV-A/INV-B (V-05/V-07/V-08)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from src.io.artifact import (
    ArtifactExistsError,
    ArtifactNotFoundError,
    UpstreamRef,
    artifact_dir,
    artifact_exists,
    compute_config_hash,
    gc_incomplete,
    read_artifact,
    read_manifest,
    scan_artifact,
    write_artifact,
)
from src.io.schema import ArtifactSchema, ColumnSpec


def _schema() -> ArtifactSchema:
    return ArtifactSchema(
        schema_version="1.0.0",
        primary_key=("t0",),
        columns=(
            ColumnSpec(name="t0", dtype="Int64", nullable=False, role="key"),
            ColumnSpec(name="close", dtype="Float64", nullable=False),
        ),
    )


def _df() -> pl.DataFrame:
    return pl.DataFrame({"t0": [1, 2, 3], "close": [10.0, 11.0, 12.0]})  # noqa: magic-number


def test_compute_config_hash_muda_com_schema_version() -> None:
    h1 = compute_config_hash({"a": 1}, schema_version="1.0.0")
    h2 = compute_config_hash({"a": 1}, schema_version="2.0.0")
    assert h1 != h2


def test_compute_config_hash_estavel_sob_reordenacao_de_chave() -> None:
    h1 = compute_config_hash({"a": 1, "b": 2}, schema_version="1.0.0")
    h2 = compute_config_hash({"b": 2, "a": 1}, schema_version="1.0.0")
    assert h1 == h2


def test_write_read_round_trip_bit_identico(tmp_path: Path) -> None:
    schema = _schema()
    df = _df()
    manifest = write_artifact(
        df,
        root=tmp_path,
        stage="labels",
        symbol="BTCUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
    )
    assert manifest.n_rows == 3
    assert manifest.stage == "labels"

    df2, manifest2 = read_artifact(
        root=tmp_path,
        stage="labels",
        config_hash=manifest.config_hash,
        symbol="BTCUSDT",
        resolution="R1",
    )
    assert df2.equals(df)
    assert manifest2 == manifest


def test_write_artifact_grava_no_path_esperado_v07(tmp_path: Path) -> None:
    schema = _schema()
    manifest = write_artifact(
        _df(),
        root=tmp_path,
        stage="labels",
        symbol="BTCUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
    )
    expected = artifact_dir(
        tmp_path,
        stage="labels",
        config_hash=manifest.config_hash,
        symbol="BTCUSDT",
        resolution="R1",
    )
    assert expected.exists()
    assert (expected / "_SUCCESS").exists()
    assert (expected / "manifest.json").exists()
    assert (expected / "schema.json").exists()
    assert (expected / "config.json").exists()
    assert (expected / "part-0000.parquet").exists()
    # V-07 -- config_hash acima de symbol/resolution
    assert expected.parts[-3] == f"config_hash={manifest.config_hash}"


def test_write_artifact_imutavel_recusa_sobrescrita(tmp_path: Path) -> None:
    schema = _schema()
    write_artifact(
        _df(),
        root=tmp_path,
        stage="labels",
        symbol="BTCUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
    )
    with pytest.raises(ArtifactExistsError):
        write_artifact(
            _df(),
            root=tmp_path,
            stage="labels",
            symbol="BTCUSDT",
            resolution="R1",
            config={"tp": 2.0},
            schema=schema,
            producer_entrypoint="test_io_artifact",
        )


def test_write_artifact_scratch_permite_sobrescrita(tmp_path: Path) -> None:
    schema = _schema()
    write_artifact(
        _df(),
        root=tmp_path,
        stage="labels",
        symbol="BTCUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
        scratch=True,
    )
    df_novo = pl.DataFrame({"t0": [9], "close": [99.0]})  # noqa: magic-number
    manifest2 = write_artifact(
        df_novo,
        root=tmp_path,
        stage="labels",
        symbol="BTCUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
        scratch=True,
    )
    df_lido, _ = read_artifact(
        root=tmp_path,
        stage="labels",
        config_hash=manifest2.config_hash,
        symbol="BTCUSDT",
        resolution="R1",
        scratch=True,
    )
    assert df_lido.equals(df_novo)


def test_read_artifact_inexistente_levanta_not_found(tmp_path: Path) -> None:
    with pytest.raises(ArtifactNotFoundError):
        read_manifest(tmp_path / "nao_existe")


def test_escrita_interrompida_invisivel_ao_leitor(tmp_path: Path) -> None:
    """Diretório sem `_SUCCESS` (simulando crash no meio da escrita) não
    deve ser enxergado por `artifact_exists`/`scan_artifact` -- só
    `_SUCCESS` é autoridade (V-05)."""
    schema = _schema()
    manifest = write_artifact(
        _df(),
        root=tmp_path,
        stage="labels",
        symbol="BTCUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
    )
    dest = artifact_dir(
        tmp_path,
        stage="labels",
        config_hash=manifest.config_hash,
        symbol="BTCUSDT",
        resolution="R1",
    )
    (dest / "_SUCCESS").unlink()
    assert not artifact_exists(
        root=tmp_path,
        stage="labels",
        config_hash=manifest.config_hash,
        symbol="BTCUSDT",
        resolution="R1",
    )
    with pytest.raises(ArtifactNotFoundError):
        scan_artifact(tmp_path, stage="labels", config_hash=manifest.config_hash)


def test_scan_artifact_cobre_varios_simbolos_sob_mesmo_config_hash(
    tmp_path: Path,
) -> None:
    schema = _schema()
    config = {"tp": 2.0}
    hashes = set()
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        manifest = write_artifact(
            _df(),
            root=tmp_path,
            stage="labels",
            symbol=symbol,
            resolution="R1",
            config=config,
            schema=schema,
            producer_entrypoint="test_io_artifact",
        )
        hashes.add(manifest.config_hash)
    assert len(hashes) == 1  # mesmo config -> mesmo config_hash, independente do símbolo

    scanned = scan_artifact(tmp_path, stage="labels", config_hash=hashes.pop()).collect()
    assert scanned.height == 9  # 3 símbolos x 3 linhas


def test_write_artifact_com_upstream_preenche_input_manifest_hash(tmp_path: Path) -> None:
    """Achado de revisão (audit_engineering, 2026-08-22): o caminho de
    `upstream=`/`input_manifest_hash` (núcleo de INV-B, proveniência por
    hash encadeado) tinha 0% de cobertura -- este teste fecha o gap."""
    schema = _schema()
    upstream = (
        UpstreamRef(stage="bars", config_hash="aaaa1111", manifest_hash="bbbb2222"),
        UpstreamRef(stage="features", config_hash="cccc3333", manifest_hash="dddd4444"),
    )
    manifest = write_artifact(
        _df(),
        root=tmp_path,
        stage="labels",
        symbol="BTCUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
        upstream=upstream,
    )
    assert manifest.upstream == upstream
    assert manifest.input_manifest_hash is not None
    assert len(manifest.input_manifest_hash) == 16

    # ordem de `upstream` na chamada não deve mudar o hash -- a função
    # ordena por `stage` antes de hashear (determinismo independente da
    # ordem de coleta do caller).
    manifest2 = write_artifact(
        _df(),
        root=tmp_path,
        stage="labels",
        symbol="ETHUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
        upstream=tuple(reversed(upstream)),
    )
    assert manifest2.input_manifest_hash == manifest.input_manifest_hash

    _, manifest_lido = read_artifact(
        root=tmp_path,
        stage="labels",
        config_hash=manifest.config_hash,
        symbol="BTCUSDT",
        resolution="R1",
    )
    assert manifest_lido.upstream == upstream


def test_write_artifact_falha_no_meio_nao_deixa_tmp_dir_orfao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Achado de revisão (audit_engineering, 2026-08-22): uma exceção
    entre `tmp_dir.mkdir()` e o rename final não deveria deixar lixo em
    disco -- `write_artifact` limpa `tmp_dir` no caminho de exceção.
    Força a falha DEPOIS de `tmp_dir` já existir (monkeypatch em
    `schema_to_json_bytes`, chamada só depois do parquet já ter sido
    escrito no tmp_dir) para exercitar o `except`/`shutil.rmtree` de
    verdade, não só o caminho de validação prévia."""
    import src.io.artifact as artifact_module

    def _quebrado(*_args: object, **_kwargs: object) -> bytes:
        raise RuntimeError("falha simulada no meio da escrita")

    monkeypatch.setattr(artifact_module, "schema_to_json_bytes", _quebrado)

    with pytest.raises(RuntimeError, match="falha simulada"):
        write_artifact(
            _df(),
            root=tmp_path,
            stage="labels",
            symbol="BTCUSDT",
            resolution="R1",
            config={"tp": 2.0},
            schema=_schema(),
            producer_entrypoint="test_io_artifact",
        )
    leftovers = list(tmp_path.rglob(".tmp-*"))
    assert leftovers == []


def test_gc_incomplete_remove_diretorio_orfao(tmp_path: Path) -> None:
    schema = _schema()
    manifest = write_artifact(
        _df(),
        root=tmp_path,
        stage="labels",
        symbol="BTCUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
    )
    dest = artifact_dir(
        tmp_path,
        stage="labels",
        config_hash=manifest.config_hash,
        symbol="BTCUSDT",
        resolution="R1",
    )
    (dest / "_SUCCESS").unlink()  # simula escrita interrompida

    found_dry = gc_incomplete(tmp_path, dry_run=True)
    assert dest in found_dry
    assert dest.exists()  # dry_run não remove

    removed = gc_incomplete(tmp_path, dry_run=False)
    assert dest in removed
    assert not dest.exists()


def test_gc_incomplete_nao_toca_artefato_completo(tmp_path: Path) -> None:
    schema = _schema()
    write_artifact(
        _df(),
        root=tmp_path,
        stage="labels",
        symbol="BTCUSDT",
        resolution="R1",
        config={"tp": 2.0},
        schema=schema,
        producer_entrypoint="test_io_artifact",
    )
    orphans = gc_incomplete(tmp_path, dry_run=True)
    assert orphans == ()
