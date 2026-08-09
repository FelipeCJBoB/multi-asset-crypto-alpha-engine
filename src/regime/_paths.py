"""Resolução de caminhos do repo — privado ao pacote `regime` (§14.2).

Duplicado deliberadamente de `src/features/_paths.py` (que por sua vez
duplica `src/data/_paths.py`), pela mesma tática já documentada nos dois
módulos anteriores: cada pacote possui sua própria cópia mínima de
resolução de caminho para não acoplar a uma cadeia de imports entre
pacotes por um detalhe de infraestrutura.

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem
de qualquer diretório.
"""

from __future__ import annotations

from pathlib import Path

# src/regime/_paths.py -> parents[0]=src/regime, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"

# Layout §1.2/§4.6 do PRD: `data/regimes/{version}/regimes.parquet`, irmão
# de `data/features/{version}/` e `data/labels/{version}/`.
REGIME_OUTPUT_DIR: Path = DATA_ROOT / "regimes"

# Duplicado de `src/exchange/_paths.py::DEFAULT_SNAPSHOTS_DIR` — mesma tática
# de duplicação tática já usada por `data`/`features` para não cruzar a
# fronteira de um módulo `_paths.py` privado de outro pacote (S10, §4.4).
EXCHANGE_INFO_SNAPSHOTS_DIR: Path = DATA_ROOT / "raw" / "snapshots" / "exchange_info"
