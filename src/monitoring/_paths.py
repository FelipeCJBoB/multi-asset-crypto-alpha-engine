"""Resolução de caminhos do repo — privado ao pacote `monitoring` (§14.2).

Duplicado deliberadamente das cópias já existentes em `src/data/_paths.py`,
`src/risk/_paths.py`, etc. — mesma tática já usada por todo pacote do repo
(`data`, `exchange`, `execution`, `features`, `labels`, `models`, `regime`,
`risk`, `validation`): cada um mantém sua própria cópia mínima de resolução
de caminho, em vez de importar de outro pacote por um detalhe de
infraestrutura. TODO(Sprint 3+, mesmo já registrado nas outras cópias):
consolidar todas numa raiz compartilhada fora da hierarquia de camadas
(ex. `src/_paths.py`) quando o formato estabilizar.

`monitoring/` não tem diretório de output próprio ainda (este módulo é o
1º consumidor de `constants.yaml` do pacote — `dollar_bar_drift.py`, AG-042
item 2). Só `CONSTANTS_PATH` é necessário aqui.

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem
de qualquer diretório."""

from __future__ import annotations

from pathlib import Path

# src/monitoring/_paths.py -> parents[0]=src/monitoring, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"
