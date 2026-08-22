"""Camada de artefatos do lake local — ADR-001 (`docs/ADR-001_arquitetura_
artefatos_e_contratos_2026-08-19_base.md`, ratificado pelo Manager
2026-08-20). `schema.py` — contrato de coluna versionado (INV-C/INV-D),
zero I/O. `artifact.py` — writer/reader de tabela imutável, endereçado por
`config_hash`, com proveniência por hash encadeado (INV-A/INV-B).

Pacote sem dependência de nenhuma camada de domínio (`exchange`, `data`,
`features`, `labels`, `regime`, `models`, `validation`, `backtest`,
`risk`, `execution`, `live`) — mesmo papel de `src/core/`, importável por
qualquer uma delas. `pyproject.toml::[tool.importlinter]` não declara
contrato `layers` formal (só 7 regras `forbidden` pontuais, nenhuma
restringe `src.core`/`src.io`), então nenhum contrato novo é necessário
pra este pacote ser importável livremente.

**Escopo desta rodada** (decisão de sequenciamento — action items do
ADR-001, `PLANO_MESTRE_PRINCE2.md`): só o writer/reader de 1 tabela
(DataFrame) por artefato. `snapshot/`/`promotion/`/`bundle/`/
`trial_registry/` (artefatos multi-arquivo, action items 5/9) e a
migração de `weights.py`/`features/build.py`/`experiment_log.py` pra este
writer (action item 4) ficam para rodadas seguintes — construir a
abstração genérica agora, para estágios que ainda não existem, seria
desenho para requisito hipotético."""

from __future__ import annotations

from .artifact import (
    ArtifactError,
    ArtifactExistsError,
    ArtifactManifest,
    ArtifactNotFoundError,
    FileEntry,
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
from .schema import (
    ArtifactSchema,
    CausalityClass,
    ColumnRole,
    ColumnSpec,
    ParityClass,
    SchemaValidationError,
    schema_from_json_bytes,
    schema_to_json_bytes,
    validate_schema,
)

__all__ = [
    "ArtifactError",
    "ArtifactExistsError",
    "ArtifactManifest",
    "ArtifactNotFoundError",
    "ArtifactSchema",
    "CausalityClass",
    "ColumnRole",
    "ColumnSpec",
    "FileEntry",
    "ParityClass",
    "SchemaValidationError",
    "UpstreamRef",
    "artifact_dir",
    "artifact_exists",
    "compute_config_hash",
    "gc_incomplete",
    "read_artifact",
    "read_manifest",
    "scan_artifact",
    "schema_from_json_bytes",
    "schema_to_json_bytes",
    "validate_schema",
    "write_artifact",
]
