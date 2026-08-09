"""Resolução de caminhos do repo — privado ao pacote `features` (§14.2).

Duplicado deliberadamente de `src/data/_paths.py` (que por sua vez duplica
`src/exchange/_paths.py`) em vez de importado de lá — mesma tática já
documentada nos dois módulos anteriores: cada pacote possui sua própria
cópia mínima de resolução de caminho para não acoplar a uma cadeia de
imports entre pacotes por um detalhe de infraestrutura (§14.2 permite
`features -> data`, mas a duplicação evita qualquer acoplamento além do que
é estritamente necessário — `src.data.lake`/`src.data.resample`, que são a
única superfície pública que `features/` de fato precisa de `data/`).

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem
de qualquer diretório.
"""

from __future__ import annotations

from pathlib import Path

# src/features/_paths.py -> parents[0]=src/features, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"
CAPACITY_DIR: Path = DATA_ROOT / "capacity"


def capacity_symbol_dir(source: str, symbol: str = "BTCUSDT") -> Path:
    """`data/capacity/{source}/{symbol}/` — um arquivo parquet por dia
    (exceto `funding`, mensal). Levanta `FileNotFoundError` cedo se o
    diretório não existir."""
    d = CAPACITY_DIR / source / symbol
    if not d.is_dir():
        raise FileNotFoundError(f"diretório de dataset não encontrado: {d}")
    return d
