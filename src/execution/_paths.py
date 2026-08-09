"""Resolução de caminhos do repo — privado ao pacote `execution` (§14.2).

Duplicado deliberadamente de `src/data/_paths.py` / `src/labels/_paths.py`
pelo mesmo motivo já documentado nos dois: cada pacote mantém sua própria
cópia mínima de resolução de caminho para não acoplar a uma cadeia de
imports por um detalhe de infraestrutura. `execution -> data` (via
`src.data.lake.query_agg_trades`, reusado por `fill_simulator.py`) é um
import direto permitido pela hierarquia de camadas — só a resolução de PATH
é duplicada aqui, não a lógica de consulta.

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem
de qualquer diretório.
"""

from __future__ import annotations

from pathlib import Path

# src/execution/_paths.py -> parents[0]=src/execution, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"
RAW_DIR: Path = DATA_ROOT / "raw"

# bookTicker (D08/D09) — layout `data/raw/book_ticker/{symbol}/yyyy-mm-dd.parquet`,
# um arquivo por dia. Cobertura real medida: 2023-05-16..2024-03-30 (ver
# known_gaps.d05_d08_d09_upstream_availability_shorter_than_prd_claims em
# constants.yaml) — não contínua até hoje, upstream descontinuado.
BOOK_TICKER_DIR: Path = RAW_DIR / "book_ticker"

# Output BULK do simulador de fila (§9.5, Sprint 9) — reconstrutível a
# partir de código + config + dado fonte, mesma categoria de `/labels/` e
# `/regime/` no .gitignore (ver ali o comentário completo). Diretório de
# DADO no topo do repo, irmão de `data/`, `labels/`, `models/` — não
# confundir com o pacote de CÓDIGO `src/execution/`.
FILL_SIMULATOR_OUTPUT_DIR: Path = REPO_ROOT / "execution" / "fill_simulator"

# Registro append-only PEQUENO (mesmo padrão de
# `src/labels/experiment_log.py` — config+métricas, não dado bruto) —
# versionado, não cai no .gitignore.
EXPERIMENTS_DIR: Path = REPO_ROOT / "experiments"


def book_ticker_symbol_dir(symbol: str) -> Path:
    """Levanta `FileNotFoundError` cedo se o diretório não existir, em vez
    de deixar um glob vazio passar silencioso (mesmo padrão de
    `src.data._paths.capacity_symbol_dir`)."""
    d = BOOK_TICKER_DIR / symbol
    if not d.is_dir():
        raise FileNotFoundError(f"diretório de bookTicker não encontrado: {d}")
    return d
