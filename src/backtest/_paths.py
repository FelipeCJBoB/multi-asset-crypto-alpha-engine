"""Resolução de caminhos do repo — privado ao pacote `backtest` (§14.2).

Duplicado deliberadamente de `src/models/_paths.py` / `src/execution/_paths.py`
pelo mesmo motivo já documentado em ambos: cada pacote mantém sua própria
cópia mínima de resolução de caminho para não acoplar a uma cadeia de
imports por um detalhe de infraestrutura, mesmo onde a hierarquia de
camadas (§14.2, `[tool.importlinter]` em `pyproject.toml`) já permite o
import direto (`backtest -> models`/`backtest -> execution`/`backtest ->
labels`/`backtest -> validation` não têm nenhum contrato `forbidden` —
ver `pyproject.toml`).

As datas de janela real do bookTicker (`BOOK_TICKER_WINDOW_START/_END`) e
o limite RPI (`RPI_BREAK_DATE`) NÃO são duplicadas aqui — são importadas
diretamente de `src.execution.fill_simulator` (única fonte de verdade da
medição; duplicar valores medidos, ao contrário de paths de infra,
violaria a Regra Zero de proveniência, §16.10).

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem
de qualquer diretório."""

from __future__ import annotations

from pathlib import Path

# src/backtest/_paths.py -> parents[0]=src/backtest, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# `labels/{version}/labels.parquet` — mesmo caminho que
# `src/models/_paths.py::LABELS_OUTPUT_DIR` / `src/validation/_paths.py`
# resolvem. Não usado por `fill_reconciliation.load_labels()` desde T0.3
# (delega em `src.validation.cpcv.load_labels_v1()`, já importado neste
# pacote) — mantido só por caso futuro que precise do caminho legado
# diretamente.
LABELS_OUTPUT_DIR: Path = REPO_ROOT / "labels"

# `predictions/alpha/{model_id}/predictions.parquet` (§5.12) — mesmo
# caminho que `src/models/_paths.py::PREDICTIONS_OUTPUT_DIR` resolve.
PREDICTIONS_OUTPUT_DIR: Path = REPO_ROOT / "predictions"

# `execution/fill_simulator/{version}/orders.parquet` (§9.5, Sprint 9) —
# mesmo caminho que `src/execution/_paths.py::FILL_SIMULATOR_OUTPUT_DIR`
# resolve. Diretório de DADO no topo do repo, não confundir com o pacote
# de código `src/execution/`.
FILL_SIMULATOR_OUTPUT_DIR: Path = REPO_ROOT / "execution" / "fill_simulator"


def fill_simulator_symbol_dir(symbol: str, *, version: str = "v1") -> Path:
    """`execution/fill_simulator/{symbol}/{version}/` — mesma função
    (duplicada, mesmo motivo do resto deste arquivo) de
    `src.execution._paths.fill_simulator_symbol_dir` (`AG-345`,
    2026-08-27). Função PURA de resolução de path, não checa existência
    nem cria diretório."""
    return FILL_SIMULATOR_OUTPUT_DIR / symbol / version

# Registro append-only de experimentos (§11.6) — mesmo diretório que
# `src/models/_paths.py::EXPERIMENTS_DIR` resolve; este pacote grava
# `experiments/backtest_fill_reconciliation_report.json` ali.
EXPERIMENTS_DIR: Path = REPO_ROOT / "experiments"
