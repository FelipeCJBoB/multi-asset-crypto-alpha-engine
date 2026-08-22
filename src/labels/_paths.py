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

from src.data.build_dollar_bars import CALIBRATION_TF_BY_RESOLUTION

# src/labels/_paths.py -> parents[0]=src/labels, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"
CAPACITY_DIR: Path = DATA_ROOT / "capacity"

# Output do Label Engine — §3.5: `labels/{version}/labels.parquet`. Diretório
# de DADO no topo do repo (irmão de `data/`, `models/`, `experiments/`), não
# confundir com o pacote de CÓDIGO `src/labels/`. Layout LEGADO (pré-V4.1,
# só BTCUSDT) — o artefato real `labels/v1/labels.parquet` mora aqui e
# continua morando aqui (~29 módulos/testes referenciam este caminho
# literalmente; migrá-los é trabalho separado, não feito nesta rodada).
LABELS_OUTPUT_DIR: Path = REPO_ROOT / "labels"

# Layout chaveado do PRD_V4_1.md T0.3 (§3.1): `data/labels/{symbol}/{tf}/
# {label_version}/`. Convive com LABELS_OUTPUT_DIR acima -- não substitui
# nem migra o artefato legado. Escritas NOVAS (símbolos além de BTCUSDT, ou
# BTCUSDT reprocessado deliberadamente sob o layout novo) usam isto.
_DEFAULT_TF = "15m"


def labels_symbol_tf_dir(
    symbol: str, version: str, *, tf: str = _DEFAULT_TF, resolution_id: str | None = None
) -> Path:
    """`data/labels/{symbol}/{grade}/{version}/` — `grade` é `tf` (grade de
    tempo, comportamento bit-exato de sempre) OU `resolution_id` (dollar
    bar, AG-042) quando setado.

    **Guarda anti-colisão (achado real de revisão independente
    `project_assurance`, 2026-08-17)**: `resolution_id`, quando presente,
    SEMPRE vence sobre `tf` (nunca combina os dois no mesmo path) e
    precisa ser uma resolução dollar-bar reconhecida
    (`CALIBRATION_TF_BY_RESOLUTION`) — levanta `ValueError` explícito
    caso contrário, nunca aceita uma string livre que pudesse colidir com
    um `tf` de grade de tempo real. Sem esta guarda, um caller que
    setasse `resolution_id="R1"` mas deixasse `tf` no default `"15m"`
    (rótulo remanescente, não mais usado como grade real) produziria o
    MESMO path que os labels de produção reais de grade de tempo já
    treinados (`data/labels/{symbol}/15m/v1/`) — sobrescrevendo produção
    com dado de outra grade, mascarado como "15m"."""
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


# Registro append-only de RODADAS REAIS de produção do Label Engine (§11.6)
# -- não é resultado de experimento/exploração, é log de execução (toda
# rodada real de build de labels grava aqui via backfill_multi_symbol) --
# corrigido 2026-08-22 pra sair de experiments/ (nome do diretório sinaliza
# "descartável/exploratório", incompatível com um log de produção lido de
# volta pelo próprio pipeline). Histórico preservado via `git mv`, não
# recriado do zero.
LABEL_ENGINE_RUNS_DIR: Path = DATA_ROOT / "label_engine_runs"

EXPERIMENTS_DIR: Path = REPO_ROOT / "experiments"
