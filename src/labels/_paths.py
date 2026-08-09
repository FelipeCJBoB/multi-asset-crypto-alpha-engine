"""Resolução de caminhos do repo — privado ao pacote `labels` (§14.2).

Duplicado deliberadamente de `src/features/_paths.py` (que por sua vez
duplica `src/data/_paths.py`/`src/exchange/_paths.py`) em vez de importado
de lá — mesma tática já documentada nos três módulos anteriores: cada
pacote possui sua própria cópia mínima de resolução de caminho para não
acoplar a uma cadeia de imports entre pacotes por um detalhe de
infraestrutura, mesmo onde a hierarquia de camadas (§14.2) já permite o
import direto (`labels -> features` é permitido; a duplicação evita
acoplar além do estritamente necessário).

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem
de qualquer diretório.
"""

from __future__ import annotations

from pathlib import Path

# src/labels/_paths.py -> parents[0]=src/labels, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"
CAPACITY_DIR: Path = DATA_ROOT / "capacity"

# Output do Label Engine — §3.5: `labels/{version}/labels.parquet`. Diretório
# de DADO no topo do repo (irmão de `data/`, `models/`, `experiments/`), não
# confundir com o pacote de CÓDIGO `src/labels/`.
LABELS_OUTPUT_DIR: Path = REPO_ROOT / "labels"

# Registro append-only de experimentos (§11.6) — `experiments/label_engine_runs.parquet`.
EXPERIMENTS_DIR: Path = REPO_ROOT / "experiments"
