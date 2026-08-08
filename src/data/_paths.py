"""Resolução de caminhos do repo — privado ao pacote `data` (§14.2).

Duplicado deliberadamente de `src/exchange/_paths.py`, em vez de importado de
lá: no momento em que este módulo foi escrito, `exchange/` estava sendo
implementado em paralelo por outro agente, e importar um pacote em fluxo
faria `data/` quebrar por uma dependência que ainda muda de forma. A
hierarquia de camadas (§14.2) permite `data -> exchange`; a duplicação é
tática, não estrutural.

TODO(Sprint 3+): quando `exchange/` estabilizar, avaliar consolidar as duas
cópias de `_paths.py` — via import direto de `src.exchange._paths`, ou
promovendo a resolução de `REPO_ROOT`/`CONSTANTS_PATH` para um módulo
compartilhado fora da hierarquia de camadas (ex.: `src/_paths.py`). Não fazer
isso antes disso: duas cópias pequenas e óbvias são mais seguras agora do que
uma dependência cruzada com um módulo ainda instável.

Resolvido a partir de `__file__`, não de `cwd()`, para que os testes rodem de
qualquer diretório.
"""

from __future__ import annotations

from pathlib import Path

# src/data/_paths.py -> parents[0]=src/data, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"
VENUE_CHANGELOG_PATH: Path = REPO_ROOT / "config" / "venue_changelog.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"

# Layout provisório do backfill do Sprint 1 — SOMENTE LEITURA para este
# módulo (outro processo pode estar escrevendo em data/raw/book_ticker/ neste
# exato momento). A consolidação para o layout canônico `data/raw/` do §1.2
# é tarefa futura, deliberadamente adiada até o download de bookTicker
# terminar (evita colisão de escrita).
CAPACITY_DIR: Path = DATA_ROOT / "capacity"

# Layout canônico §1.2 — existe hoje só para snapshots/ (F01/F02/F04) e
# bvol_index/ (D05). O resto de raw/ chega na consolidação futura.
RAW_DIR: Path = DATA_ROOT / "raw"
PROCESSED_DIR: Path = DATA_ROOT / "processed"

QUALITY_REPORTS_DIR: Path = DATA_ROOT / "quality_reports"


def capacity_symbol_dir(source: str, symbol: str = "BTCUSDT") -> Path:
    """`data/capacity/{source}/{symbol}/` — um arquivo parquet por dia
    (exceto `funding`, que é mensal). Levanta `FileNotFoundError` cedo se o
    diretório não existir, em vez de deixar um glob vazio passar silencioso."""
    d = CAPACITY_DIR / source / symbol
    if not d.is_dir():
        raise FileNotFoundError(f"diretório de dataset não encontrado: {d}")
    return d
