"""Resolução de caminhos do repo — privado ao pacote `models` (§14.2).

Duplicado deliberadamente de `src/validation/_paths.py` (que por sua vez
duplica `src/labels/_paths.py` -> `src/features/_paths.py` -> `src/data/
_paths.py` -> `src/exchange/_paths.py`) em vez de importado de lá — mesma
tática já documentada em todos os pacotes anteriores: cada pacote possui
sua própria cópia mínima de resolução de caminho para não acoplar a uma
cadeia de imports entre pacotes por um detalhe de infraestrutura, mesmo
onde a hierarquia de camadas (§14.2) já permite o import direto
(`models -> labels`/`models -> regime`/`models -> features` são
permitidos — a duplicação evita acoplar além do estritamente necessário).

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem
de qualquer diretório."""

from __future__ import annotations

from pathlib import Path

# src/models/_paths.py -> parents[0]=src/models, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"

# `labels/{version}/labels.parquet` — mesmo caminho que
# `src/validation/_paths.py::LABELS_OUTPUT_DIR` resolve.
LABELS_OUTPUT_DIR: Path = REPO_ROOT / "labels"

# §5.12 — `predictions/alpha/{model_id}/predictions.parquet` (legado,
# pré-V4.1). Diretório de DADO no topo do repo (irmão de `data/`, `labels/`,
# `models/`, `experiments/`), não confundir com o pacote de CÓDIGO
# `src/models/`.
PREDICTIONS_OUTPUT_DIR: Path = REPO_ROOT / "predictions"

# Layout chaveado do PRD_V4_1.md T0.3 (§3.1): `predictions/alpha/{symbol}/
# {tf}/{model_id}/`.
_DEFAULT_TF = "15m"


def predictions_symbol_tf_dir(symbol: str, model_id: str, *, tf: str = _DEFAULT_TF) -> Path:
    """`predictions/alpha/{symbol}/{tf}/{model_id}/`."""
    return PREDICTIONS_OUTPUT_DIR / "alpha" / symbol / tf / model_id

# Registro append-only de experimentos (§11.6) — mesmo diretório que
# `src/labels/_paths.py::EXPERIMENTS_DIR` resolve; este pacote grava
# `experiments/alpha_layer1_report.json` (relatório desta rodada) ali.
EXPERIMENTS_DIR: Path = REPO_ROOT / "experiments"
