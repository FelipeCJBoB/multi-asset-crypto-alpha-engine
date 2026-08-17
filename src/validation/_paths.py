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

from src.data.build_dollar_bars import CALIBRATION_TF_BY_RESOLUTION

# src/validation/_paths.py -> parents[0]=src/validation, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"

# `labels/{version}/labels.parquet` — diretório de DADO no topo do repo
# (irmão de `data/`, `models/`, `experiments/`), mesmo caminho que
# `src/labels/_paths.py::LABELS_OUTPUT_DIR` resolve — duplicado aqui pela
# mesma tática de isolamento entre pacotes descrita acima. Legado
# (pré-V4.1) — ver `labels_symbol_tf_dir` abaixo pro layout chaveado novo,
# que é onde `labels/v1/labels.parquet` (BTCUSDT) foi migrado (T0.3).
LABELS_OUTPUT_DIR: Path = REPO_ROOT / "labels"

_DEFAULT_TF = "15m"


def labels_symbol_tf_dir(
    symbol: str, version: str, *, tf: str = _DEFAULT_TF, resolution_id: str | None = None
) -> Path:
    """`data/labels/{symbol}/{grade}/{version}/` — mesmo layout de
    `src.labels._paths.labels_symbol_tf_dir` (T0.3), mesma guarda
    anti-colisão de `resolution_id` (AG-042, achado de revisão
    independente `project_assurance`, 2026-08-17) -- ver docstring
    daquela função pro racional completo."""
    if resolution_id is not None:
        if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:
            raise ValueError(
                f"labels_symbol_tf_dir: resolution_id={resolution_id!r} não reconhecido -- "
                f"esperado um de {sorted(CALIBRATION_TF_BY_RESOLUTION)}"
            )
        grade = resolution_id
    else:
        grade = tf
    return DATA_ROOT / "labels" / symbol / grade / version

# Saída dos relatórios deste pacote (`leakage_report.json`, resumo de splits
# do CPCV) — irmão de `data/quality_reports/` (Data Quality Engine, Sprint
# 2/3), não dentro dele: motores diferentes, formato de relatório diferente.
VALIDATION_REPORTS_DIR: Path = DATA_ROOT / "validation_reports"
