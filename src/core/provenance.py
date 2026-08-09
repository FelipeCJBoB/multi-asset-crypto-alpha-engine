"""`report_provenance()` — `generated_at` (ISO-8601 UTC) + `code_version`
(hash curto do commit HEAD) pra mesclar no payload de todo relatório novo
persistido em `experiments/`.

**Por que isto existe.** `experiments/alpha_layer1_report.json` é um
arquivo mutável reescrito a cada `run_layer1_sprint()`, sem nenhum jeito
de saber QUANDO ou de QUE COMMIT um número veio — três consumidores
distintos já leram esse arquivo com um `n` de um momento diferente do
`pnl_total` que ele acompanhava (achado real desta investigação, ver
`docs/SPRINT_LOG.md`). `report_provenance()` não impede isso sozinho
(quem lê o arquivo ainda precisa checar os dois campos), mas torna a
pergunta "esse número é de agora, deste commit?" respondível sem
reconstruir nada."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path


def _git_head_hash(cwd: Path) -> str:
    """Hash curto (7 hex) do commit HEAD. `"unknown"` fora de um repo git
    ou em working tree sem histórico — nunca levanta: proveniência ausente
    não pode derrubar a escrita do relatório que ela deveria documentar."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            capture_output=True,
            encoding="utf-8",
            cwd=cwd,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def report_provenance(*, cwd: Path | None = None) -> dict[str, str]:
    """`{"generated_at": ..., "code_version": ...}` — mesclar no payload de
    um relatório (`dict` ou `dataclasses.asdict(...)`) antes de serializar,
    não substituir campos já existentes com outro nome (ex.
    `FillReconciliationReport.generated_at_utc`, já populado desde antes
    desta função existir — some `code_version` a ele, não duplique
    `generated_at`)."""
    resolved_cwd = cwd if cwd is not None else Path.cwd()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "code_version": _git_head_hash(resolved_cwd),
    }
