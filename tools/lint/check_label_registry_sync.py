"""Lint de LINHAGEM: todo `labels.parquet` em disco tem linha no registro?

ADR-005 §13 v2 §13.11, item 3b de §13.17 (`AG-309`).

**O que verifica.** Para cada `data/labels/{symbol}/{grade}/{version}/
labels.parquet`, se existe ao menos uma linha em
`data/label_engine_runs/label_engine_runs.parquet` com o MESMO
`config_hash`, o mesmo `symbol` e a mesma grade. Se não existe, aquele
artefato não tem proveniência registrada -- e nenhum número publicado a
partir dele é rastreável à config que o gerou.

**Por que um lint e não um teste.** Ele lê o estado do DISCO, que é
ambiente, não código. Um teste que falhasse por causa de um backfill local
ausente seria ruído; um lint rodado de propósito responde a pergunta certa
na hora certa. Mesma categoria dos outros `tools/lint/*` (`check_constants_
provenance.py`, `check_sprint_log_references.py`).

**É `B15` estendido.** `triple_barrier.verify_config_hash` já compara o
`config_hash` do label contra o da execução. Este lint compara o do label
contra o do REGISTRO -- mesma disciplina, fronteira nova (label <-> auditoria).

Uso:

    python tools/lint/check_label_registry_sync.py            # falha se divergir
    python tools/lint/check_label_registry_sync.py --strict   # idem, explícito
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.labels.experiment_log import (  # noqa: E402 -- sys.path acima é pré-requisito
    UnregisteredLabelArtifact,
    find_unregistered_label_artifacts,
)


def _imprime(a: UnregisteredLabelArtifact, registro: str) -> None:
    print(f"  {a.symbol}/{a.grade}/{a.version}")
    print(f"      disco    : {a.config_hash_no_disco}")
    print(f"      registro : {registro}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verifica se todo labels.parquet em disco tem linha correspondente "
            "no registro do Label Engine (ADR-005 §13 v2 §13.11 / AG-309)."
        )
    )
    parser.add_argument(
        "--labels-root",
        default=None,
        help="raiz de data/labels (default: a do repo)",
    )
    parser.add_argument(
        "--log-path",
        default=None,
        help="parquet do registro (default: data/label_engine_runs/label_engine_runs.parquet)",
    )
    parser.add_argument("--strict", action="store_true", help="explícito; já é o comportamento")
    args = parser.parse_args()

    achados = find_unregistered_label_artifacts(
        labels_root=Path(args.labels_root) if args.labels_root else None,
        log_path=Path(args.log_path) if args.log_path else None,
    )
    if not achados:
        print("check_label_registry_sync: todo labels.parquet tem linha no registro.")
        return 0

    aceitos = [a for a in achados if a.accepted_gap]
    pendentes = [a for a in achados if not a.accepted_gap]

    if aceitos:
        print(f"check_label_registry_sync: {len(aceitos)} artefato(s) com gap ACEITO (AG-309):\n")
        for a in aceitos:
            registro = ", ".join(a.config_hashes_no_registro) or "(nenhuma linha para esta célula)"
            _imprime(a, registro)
        print(
            "\nGrade de relógio 15m -- decisão do Manager (2026-08-27): não roda mais, "
            "obsoleta desde AG-042. Ver src.labels.experiment_log."
            "KNOWN_LEGACY_GRADE_LINEAGE_GAPS.\n"
        )

    if not pendentes:
        print("check_label_registry_sync: nenhum gap FORA da lista aceita.")
        return 0

    print(f"check_label_registry_sync: {len(pendentes)} artefato(s) SEM linha no registro:\n")
    for a in pendentes:
        registro = ", ".join(a.config_hashes_no_registro) or "(nenhuma linha para esta célula)"
        _imprime(a, registro)
    print(
        "\nCada um destes é um artefato de produção cuja proveniência não está registrada:\n"
        "nenhum número publicado a partir dele é rastreável à config que o gerou.\n"
        "Isto NÃO se conserta apendando linhas reconstruídas -- o schema do registro\n"
        "declara, duas vezes, 'não inventa retroativamente o que não foi registrado na\n"
        "hora'. Fecha-se escrevendo os labels de novo pelo caminho que registra\n"
        "(src.labels.backfill_multi_symbol.build_and_write_labels_for_symbol), ou\n"
        "aceitando explicitamente que a janela anterior ficou sem proveniência\n"
        "(src.labels.experiment_log.KNOWN_LEGACY_GRADE_LINEAGE_GAPS, se for o mesmo "
        "caso da grade 15m já tratado)."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
