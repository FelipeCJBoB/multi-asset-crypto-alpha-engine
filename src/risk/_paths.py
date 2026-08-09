"""Resolução de caminhos do repo — privado ao pacote `risk` (§14.2).

Duplicado deliberadamente de `src/regime/_paths.py` (que por sua vez duplica
`src/features/_paths.py` -> `src/data/_paths.py`), mesma tática já usada
pelos pacotes anteriores: cada pacote tem sua própria cópia mínima de
resolução de caminho para não acoplar a uma cadeia de imports entre pacotes
por um detalhe de infraestrutura.

`risk/` não tem diretório de output próprio (Sprint 9: motor puro — sizing +
controles + kill switch — sem persistência; auditoria/append-only de eventos
é responsabilidade de outra camada, §10.6). Só `CONSTANTS_PATH` é necessário
aqui.

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem de
qualquer diretório.
"""

from __future__ import annotations

from pathlib import Path

# src/risk/_paths.py -> parents[0]=src/risk, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"
