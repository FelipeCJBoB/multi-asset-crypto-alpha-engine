"""Resolução de caminhos do repo — privado ao pacote `exchange` (§14.2).

Centraliza a única suposição de layout de diretório que os módulos de
`exchange/` precisam fazer: onde fica a raiz do repo, `config/constants.yaml`
e `data/raw/snapshots/exchange_info/`. Resolvido a partir de `__file__`, não
de `cwd()`, para que os testes rodem de qualquer diretório.
"""

from __future__ import annotations

from pathlib import Path

# src/exchange/_paths.py -> parents[0]=src/exchange, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DEFAULT_SNAPSHOTS_DIR: Path = REPO_ROOT / "data" / "raw" / "snapshots" / "exchange_info"
