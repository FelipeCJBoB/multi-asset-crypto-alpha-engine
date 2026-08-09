"""Resolução de caminhos do repo — privado ao pacote `validation` (§14.2).

Duplicado deliberadamente de `src/labels/_paths.py` (que por sua vez duplica
`src/features/_paths.py` -> `src/data/_paths.py` -> `src/exchange/_paths.py`)
em vez de importado de lá — mesma tática já documentada nos pacotes
anteriores: cada pacote possui sua própria cópia mínima de resolução de
caminho para não acoplar a uma cadeia de imports entre pacotes por um
detalhe de infraestrutura, mesmo onde a hierarquia de camadas (§14.2) já
permite o import direto (`validation -> labels` é permitido — `labels` só
pode ser LIDO por `models/`, `validation/`, `backtest/`, ver
`pyproject.toml` `[tool.importlinter]` — a duplicação evita acoplar além do
estritamente necessário).

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem
de qualquer diretório.
"""

from __future__ import annotations

from pathlib import Path

# src/validation/_paths.py -> parents[0]=src/validation, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"

# `labels/{version}/labels.parquet` — diretório de DADO no topo do repo
# (irmão de `data/`, `models/`, `experiments/`), mesmo caminho que
# `src/labels/_paths.py::LABELS_OUTPUT_DIR` resolve — duplicado aqui pela
# mesma tática de isolamento entre pacotes descrita acima.
LABELS_OUTPUT_DIR: Path = REPO_ROOT / "labels"

# Saída dos relatórios deste pacote (`leakage_report.json`, resumo de splits
# do CPCV) — irmão de `data/quality_reports/` (Data Quality Engine, Sprint
# 2/3), não dentro dele: motores diferentes, formato de relatório diferente.
VALIDATION_REPORTS_DIR: Path = DATA_ROOT / "validation_reports"
