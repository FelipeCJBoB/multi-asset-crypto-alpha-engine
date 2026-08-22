"""Writer/reader de artefato versionado do lake local — ADR-001
(`docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md`,
ratificado pelo Manager 2026-08-20, action item 2, "antes de qualquer
outro módulo"). Implementa INV-A (chave canônica) e INV-B (proveniência
por hash, imutabilidade) — INV-C/INV-D (causalidade/paridade por coluna)
vivem em `src.io.schema`, importado aqui.

**Escopo desta rodada** (decisão de sequenciamento registrada em
`PLANO_MESTRE_PRINCE2.md`): só o writer/reader de 1 tabela (DataFrame) por
artefato. `snapshot/`/`promotion/`/`bundle/`/`trial_registry/` (action
items 5/9 do ADR) e a migração de `weights.py`/`features/build.py`/
`experiment_log.py` pro writer novo (action item 4) ficam para rodadas
seguintes — construir a abstração genérica de "bundle multi-arquivo"
agora, para estágios que ainda não existem, seria desenho para requisito
hipotético (CLAUDE.md).

**`bar_id` (INV-A) é opcional, não fabricado.** Nenhum artefato real hoje
(`labels.parquet`, `regimes.parquet`) tem `bar_id` monótono — tudo é
indexado por timestamp. Este writer aceita QUALQUER `primary_key`
declarado no schema (inclusive por timestamp, como hoje); se um schema
futuro declarar `bar_id` na chave, `src.io.schema` já valida a companhia
obrigatória de `*_ts_ns` (V-01).

**`config_hash`: sha256+orjson+16-hex, não blake2b.** O padrão já está em
produção em 3 lugares (`src.labels.triple_barrier.LabelConfig.
config_hash`, `bars_calibration_hash`, `_hash_filters`) — reusar evita
introduzir um segundo primitivo de hash no repo sem benefício medido.
Diverge do pseudocódigo literal do ADR (que cita blake2b) por essa razão,
registrada aqui e em `PLANO_MESTRE_PRINCE2.md`.

**Escrita atômica**: mesmo padrão de
`src.labels.triple_barrier.write_labels_atomic`/
`src.regime.build.write_regimes_atomic` — buffer em memória, handle único
`wb`, `fsync` NESSE MESMO handle (reabrir `.tmp` como `O_RDONLY` só pra
fsync falha no Windows com "Bad file descriptor", medido no Sprint 6).
Imutabilidade (V-05): `os.rename` (não `os.replace`) — no Windows,
`os.rename` levanta `FileExistsError` nativamente se o destino já existe,
dando a guarda TOCTOU-livre que `exists()` seguido de rename não dá."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import orjson
import polars as pl
import structlog

from src.core.provenance import report_provenance
from src.io.schema import (
    ArtifactSchema,
    schema_from_json_bytes,
    schema_to_json_bytes,
    validate_schema,
)

logger = structlog.get_logger(__name__)

# Parâmetros de engenharia de escrita atômica -- infraestrutura, não
# parâmetro de domínio quant (CLAUDE.md §Proveniência é sobre parâmetro
# de MODELO/ESTRATÉGIA, ex. tp_atr_mult; retry de I/O sob
# antivírus/indexador do Windows segue o mesmo precedente de
# `_DATE_BUFFER_DAYS` em `src/models/dataset.py:61`).
_WRITE_RETRIES = 5
_WRITE_RETRY_BACKOFF_S = 0.1  # noqa: magic-number -- engenharia, não domínio quant

_MANIFEST_NAME = "manifest.json"
_SCHEMA_NAME = "schema.json"
_CONFIG_NAME = "config.json"
_SUCCESS_NAME = "_SUCCESS"
_DATA_NAME = "part-0000.parquet"


class ArtifactError(Exception):
    """Base de erro deste módulo."""


class ArtifactExistsError(ArtifactError):
    """Artefato já existe e é imutável — nunca sobrescrito (V-05).
    `scratch=True` na escrita contorna isso deliberadamente."""


class ArtifactNotFoundError(ArtifactError):
    """Nenhum diretório com `_SUCCESS` encontrado na partição pedida."""


@dataclass(frozen=True, slots=True)
class FileEntry:
    name: str
    rows: int
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class UpstreamRef:
    stage: str
    config_hash: str
    manifest_hash: str


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Proveniência completa de 1 artefato (INV-B) — serializado como
    `manifest.json`, nunca reescrito depois de criado."""

    stage: str
    schema_version: str
    producer_version: str
    producer_entrypoint: str
    symbol: str
    resolution: str
    config_hash: str
    input_manifest_hash: str | None
    upstream: tuple[UpstreamRef, ...]
    created_at_ns: int
    n_rows: int
    primary_key: tuple[str, ...]
    files: tuple[FileEntry, ...]
    content_hash: str

    def to_json_bytes(self) -> bytes:
        payload: dict[str, Any] = {
            "stage": self.stage,
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "producer_entrypoint": self.producer_entrypoint,
            "symbol": self.symbol,
            "resolution": self.resolution,
            "config_hash": self.config_hash,
            "input_manifest_hash": self.input_manifest_hash,
            "upstream": [asdict(u) for u in self.upstream],
            "created_at_ns": self.created_at_ns,
            "n_rows": self.n_rows,
            "primary_key": list(self.primary_key),
            "files": [asdict(f) for f in self.files],
            "content_hash": self.content_hash,
        }
        return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2)

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ArtifactManifest:
        payload = orjson.loads(raw)
        return cls(
            stage=payload["stage"],
            schema_version=payload["schema_version"],
            producer_version=payload["producer_version"],
            producer_entrypoint=payload["producer_entrypoint"],
            symbol=payload["symbol"],
            resolution=payload["resolution"],
            config_hash=payload["config_hash"],
            input_manifest_hash=payload["input_manifest_hash"],
            upstream=tuple(UpstreamRef(**u) for u in payload["upstream"]),
            created_at_ns=payload["created_at_ns"],
            n_rows=payload["n_rows"],
            primary_key=tuple(payload["primary_key"]),
            files=tuple(FileEntry(**f) for f in payload["files"]),
            content_hash=payload["content_hash"],
        )


def artifact_dir(
    root: Path, *, stage: str, config_hash: str, symbol: str, resolution: str
) -> Path:
    """`{root}/{stage}/config_hash={h}/symbol={S}/resolution={R}/` —
    `config_hash` ACIMA de symbol/resolution (V-07) para que 1
    `scan_artifact(config_hash=...)` cubra as 15 linhas de uma rodada com
    um único `scan_parquet`."""
    return (
        root
        / stage
        / f"config_hash={config_hash}"
        / f"symbol={symbol}"
        / f"resolution={resolution}"
    )


def compute_config_hash(config: dict[str, Any], *, schema_version: str) -> str:
    """`sha256(orjson(payload, OPT_SORT_KEYS)).hexdigest()[:16]` — mesmo
    padrão de `LabelConfig.config_hash` (`src/labels/triple_barrier.py:
    541-542`). `schema_version` entra no payload (V-08: mudança de schema
    nunca reusa artefato antigo em silêncio)."""
    payload = {"schema_version": schema_version, **config}
    blob = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(blob).hexdigest()[:16]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Handle único `wb`, `fsync` NESSE MESMO handle — mesmo padrão de
    `write_labels_atomic` (`src/labels/triple_barrier.py:1782-1807`),
    aplicado uniformemente aos 4 arquivos pequenos do bundle (`schema.
    json`/`config.json`/`manifest.json`/parquet). Achado real de revisão
    (`audit_engineering`, 2026-08-22): antes desta função, só
    `manifest.json`/parquet passavam por `fsync` — `schema.json`/
    `config.json` usavam `Path.write_bytes()` sem flush/fsync, deixando
    um artefato marcado completo (`_SUCCESS` presente) potencialmente
    com esses 2 arquivos truncados após crash logo depois do
    `os.rename()`."""
    with path.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


# errno de "sem espaço em disco" -- POSIX ENOSPC, também usado pelo
# Windows via WinError 112 mapeado para errno.ENOSPC pelo runtime C do
# Python. Nunca vale retry: mais tentativas não liberam espaço.
_ENOSPC = 28


def atomic_rename_dir(tmp_dir: Path, dest_dir: Path) -> None:
    """V-05 — imutabilidade sem TOCTOU. `os.rename` (não `os.replace`)
    levanta `FileExistsError` nativamente no Windows se `dest_dir` já
    existir — não precisa checar `exists()` antes (checagem + rename
    separados seria a própria condição de corrida que isso evita). Retry
    com backoff em outros `OSError` (antivírus/indexador do Windows
    seguram handles por um instante depois do fsync) — EXCETO
    `ENOSPC` (disco cheio), que falha imediato: retry não libera
    espaço, só desperdiça tempo (achado de revisão, 2026-08-22)."""
    last_exc: OSError | None = None
    for attempt in range(_WRITE_RETRIES):
        try:
            os.rename(tmp_dir, dest_dir)
            return
        except FileExistsError:
            raise ArtifactExistsError(
                f"artefato já existe em {dest_dir} -- imutável, nunca sobrescrito "
                "(use scratch=True para iteração exploratória)"
            ) from None
        except OSError as exc:
            if exc.errno == _ENOSPC:
                raise
            last_exc = exc
            logger.warning(
                "io.artifact.rename_retry",
                tmp_dir=str(tmp_dir),
                dest_dir=str(dest_dir),
                attempt=attempt + 1,
                max_attempts=_WRITE_RETRIES,
                error=str(exc),
            )
            time.sleep(_WRITE_RETRY_BACKOFF_S * (2**attempt))
    assert last_exc is not None
    raise last_exc


def write_artifact(
    df: pl.DataFrame,
    *,
    root: Path,
    stage: str,
    symbol: str,
    resolution: str,
    config: dict[str, Any],
    schema: ArtifactSchema,
    producer_entrypoint: str,
    upstream: tuple[UpstreamRef, ...] = (),
    scratch: bool = False,
) -> ArtifactManifest:
    """Escreve `df` como artefato imutável em
    `artifact_dir(root, stage=stage, config_hash=..., symbol=symbol,
    resolution=resolution)`. Valida contra `schema` ANTES de tocar disco
    (nunca persiste artefato inválido). `scratch=True` escreve em
    `{root}/scratch/...` e permite sobrescrita — mitigação nomeada no
    ADR-001 ("Fica mais difícil: iterar rápido... modo scratch/ fora do
    lake, explicitamente não-promovível")."""
    validate_schema(df, schema)

    config_hash = compute_config_hash(config, schema_version=schema.schema_version)
    effective_root = (root / "scratch") if scratch else root
    dest_dir = artifact_dir(
        effective_root,
        stage=stage,
        config_hash=config_hash,
        symbol=symbol,
        resolution=resolution,
    )

    if not scratch and (dest_dir / _SUCCESS_NAME).exists():
        raise ArtifactExistsError(
            f"artefato já existe em {dest_dir} -- imutável, nunca sobrescrito "
            "(use scratch=True para iteração exploratória)"
        )

    tmp_dir = dest_dir.parent / f".tmp-{dest_dir.name}-{os.getpid()}-{time.monotonic_ns()}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        data_buffer = io.BytesIO()
        df.write_parquet(data_buffer)
        data_bytes = data_buffer.getvalue()
        atomic_write_bytes(tmp_dir / _DATA_NAME, data_bytes)
        data_sha256 = sha256_bytes(data_bytes)
        file_entry = FileEntry(
            name=_DATA_NAME, rows=df.height, bytes=len(data_bytes), sha256=data_sha256
        )

        # V-03 -- mesmo primitivo de compute_config_hash (orjson +
        # OPT_SORT_KEYS), não concatenação de string ad hoc: uma lista
        # estruturada serializada não tem ambiguidade de separador entre
        # registros (achado de revisão, 2026-08-22 -- a versão anterior
        # concatenava "stage:hash:hash" sem separador entre entradas de
        # upstream, defesa em profundidade mesmo com stage/hash hoje
        # vindos de vocabulário controlado, não input externo).
        input_manifest_hash: str | None = None
        if upstream:
            upstream_payload = [asdict(u) for u in sorted(upstream, key=lambda u: u.stage)]
            upstream_blob = orjson.dumps(upstream_payload, option=orjson.OPT_SORT_KEYS)
            input_manifest_hash = sha256_bytes(upstream_blob)[:16]

        manifest = ArtifactManifest(
            stage=stage,
            schema_version=schema.schema_version,
            producer_version=report_provenance()["code_version"],
            producer_entrypoint=producer_entrypoint,
            symbol=symbol,
            resolution=resolution,
            config_hash=config_hash,
            input_manifest_hash=input_manifest_hash,
            upstream=upstream,
            created_at_ns=time.time_ns(),
            n_rows=df.height,
            primary_key=schema.primary_key,
            files=(file_entry,),
            content_hash=sha256_bytes(f"{file_entry.name}:{file_entry.sha256}".encode())[:16],
        )

        atomic_write_bytes(tmp_dir / _SCHEMA_NAME, schema_to_json_bytes(schema))
        atomic_write_bytes(
            tmp_dir / _CONFIG_NAME,
            orjson.dumps(config, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2),
        )
        atomic_write_bytes(tmp_dir / _MANIFEST_NAME, manifest.to_json_bytes())

        # _SUCCESS por último -- é a autoridade (V-05); leitor ignora
        # diretório sem ele.
        (tmp_dir / _SUCCESS_NAME).touch()
    except Exception:
        # Achado de revisão (2026-08-22): sem isto, uma falha no meio da
        # escrita (ex. write_parquet, serialização de manifest) deixava
        # tmp_dir órfão em disco -- gc_incomplete() limpa depois, mas
        # falhar rápido e limpo é melhor que depender de rodar GC manual.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    if scratch and dest_dir.exists():
        # scratch permite sobrescrita explícita -- remove o diretório
        # antigo antes do rename (sem garantia de imutabilidade aqui, por
        # desenho).
        shutil.rmtree(dest_dir)

    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    atomic_rename_dir(tmp_dir, dest_dir)

    logger.info(
        "io.artifact.written",
        stage=stage,
        symbol=symbol,
        resolution=resolution,
        config_hash=config_hash,
        n_rows=df.height,
        scratch=scratch,
        path=str(dest_dir),
    )
    return manifest


def read_manifest(dest_dir: Path) -> ArtifactManifest:
    if not (dest_dir / _SUCCESS_NAME).exists():
        raise ArtifactNotFoundError(f"nenhum artefato completo em {dest_dir} (sem _SUCCESS)")
    return ArtifactManifest.from_json_bytes((dest_dir / _MANIFEST_NAME).read_bytes())


def read_artifact(
    *,
    root: Path,
    stage: str,
    config_hash: str,
    symbol: str,
    resolution: str,
    scratch: bool = False,
    validate: bool = True,
) -> tuple[pl.DataFrame, ArtifactManifest]:
    """Carrega o artefato de 1 partição específica — devolve `(df,
    manifest)`. `validate=True` (default) reaplica `validate_schema`
    depois de ler, provando simetria escrita/leitura (INV-D)."""
    effective_root = (root / "scratch") if scratch else root
    dest_dir = artifact_dir(
        effective_root,
        stage=stage,
        config_hash=config_hash,
        symbol=symbol,
        resolution=resolution,
    )
    manifest = read_manifest(dest_dir)
    schema = schema_from_json_bytes((dest_dir / _SCHEMA_NAME).read_bytes())
    df = pl.read_parquet(dest_dir / _DATA_NAME)
    if validate:
        validate_schema(df, schema)
    return df, manifest


def artifact_exists(
    *,
    root: Path,
    stage: str,
    config_hash: str,
    symbol: str,
    resolution: str,
    scratch: bool = False,
) -> bool:
    effective_root = (root / "scratch") if scratch else root
    dest_dir = artifact_dir(
        effective_root,
        stage=stage,
        config_hash=config_hash,
        symbol=symbol,
        resolution=resolution,
    )
    return (dest_dir / _SUCCESS_NAME).exists()


def scan_artifact(
    root: Path,
    *,
    stage: str,
    config_hash: str | None = None,
    symbol: str | None = None,
    resolution: str | None = None,
) -> pl.LazyFrame:
    """Varre 1 ou mais partições completas (com `_SUCCESS`) sob `stage` —
    `config_hash=None` cobre todas as rodadas; `symbol`/`resolution=None`
    cobre todos os símbolos/resoluções daquele hash (V-07: até 15 linhas
    numa única leitura). NUNCA usa glob solto sobre `part-*.parquet` —
    enumera diretórios com `_SUCCESS` primeiro, monta lista explícita de
    paths, só então `pl.scan_parquet` — diretório de escrita interrompida
    (sem `_SUCCESS`) é invisível por construção."""
    stage_dir = root / stage
    if not stage_dir.exists():
        raise ArtifactNotFoundError(f"nenhum artefato para stage={stage!r} em {root}")

    pattern = (
        f"config_hash={config_hash or '*'}/symbol={symbol or '*'}/resolution={resolution or '*'}"
    )
    candidate_dirs = sorted(stage_dir.glob(pattern))
    complete_dirs = [d for d in candidate_dirs if (d / _SUCCESS_NAME).exists()]
    if not complete_dirs:
        raise ArtifactNotFoundError(
            f"nenhuma partição completa (_SUCCESS) para stage={stage!r}, "
            f"config_hash={config_hash!r}, symbol={symbol!r}, resolution={resolution!r}"
        )
    paths = [d / _DATA_NAME for d in complete_dirs]
    return pl.scan_parquet(paths)


def gc_incomplete(
    root: Path, *, stage: str | None = None, dry_run: bool = True
) -> tuple[Path, ...]:
    """V-11, metade autocontida — remove (ou só lista, se `dry_run`)
    diretórios SEM `_SUCCESS`: lixo de escrita interrompida (`.tmp-*`
    órfão de um processo morto no meio da escrita, ou um `dest_dir` real
    que nunca completou por crash). NÃO implementa GC por referência de
    promoção (precisa de `trial_registry`/`promotion/`, action items 5/9
    do ADR, fora do escopo desta rodada)."""
    if not root.exists():
        return ()
    stages = (
        [root / stage]
        if stage is not None
        else [p for p in root.iterdir() if p.is_dir() and p.name != "scratch"]
    )
    orphans: list[Path] = []
    for stage_dir in stages:
        if not stage_dir.exists():
            continue
        for candidate in stage_dir.rglob(".tmp-*"):
            if candidate.is_dir():
                orphans.append(candidate)
        for candidate in stage_dir.glob("config_hash=*/symbol=*/resolution=*"):
            if candidate.is_dir() and not (candidate / _SUCCESS_NAME).exists():
                orphans.append(candidate)

    if not dry_run:
        for path in orphans:
            shutil.rmtree(path, ignore_errors=True)
        logger.info("io.artifact.gc_incomplete.removed", n_removed=len(orphans))
    else:
        logger.info("io.artifact.gc_incomplete.dry_run", n_found=len(orphans))
    return tuple(orphans)


__all__ = [
    "ArtifactError",
    "ArtifactExistsError",
    "ArtifactManifest",
    "ArtifactNotFoundError",
    "FileEntry",
    "UpstreamRef",
    "artifact_dir",
    "artifact_exists",
    "atomic_rename_dir",
    "atomic_write_bytes",
    "compute_config_hash",
    "gc_incomplete",
    "read_artifact",
    "read_manifest",
    "scan_artifact",
    "sha256_bytes",
    "write_artifact",
]
