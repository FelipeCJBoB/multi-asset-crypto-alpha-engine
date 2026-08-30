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

from src.data.build_dollar_bars import CALIBRATION_TF_BY_RESOLUTION

# src/regime/_paths.py -> parents[0]=src/regime, [1]=src, [2]=raiz do repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

CONSTANTS_PATH: Path = REPO_ROOT / "config" / "constants.yaml"

DATA_ROOT: Path = REPO_ROOT / "data"

# Raiz dos artefatos VERSIONADOS (`src.io.artifact`, camada ADR-001) —
# mesma definição e mesmo valor de `src.models._paths.ARTIFACT_ROOT`.
# Duplicada aqui, e não importada de `models`, porque `regime` é produtor
# e `models` é consumidor: importar do consumidor inverteria a dependência
# (e `src/regime/_paths.py` já repete `REPO_ROOT` pelo mesmo motivo).
ARTIFACT_ROOT: Path = REPO_ROOT / "artifacts"

# Layout §1.2/§4.6 do PRD (pré-V4.1, legado): `data/regimes/{version}/
# regimes.parquet`, irmão de `data/features/{version}/` e
# `data/labels/{version}/`.
REGIME_OUTPUT_DIR: Path = DATA_ROOT / "regimes"

# Layout chaveado do PRD_V4_1.md T0.3 (§3.1, "todo artefato passa a ser
# chaveado" -- extensão do mesmo princípio aplicado a labels/predictions,
# regimes não está no exemplo literal do PRD mas é dado igualmente
# símbolo-específico): `data/regimes/{symbol}/{tf}/{version}/`.
_DEFAULT_TF = "15m"


def regime_symbol_tf_dir(
    symbol: str, version: str, *, tf: str = _DEFAULT_TF, resolution_id: str | None = None
) -> Path:
    """`data/regimes/{symbol}/{grade}/{version}/` — `grade` é `tf` (grade
    de tempo) OU `resolution_id` (dollar bar) quando setado. Mesma guarda
    anti-colisão de `src.labels._paths.labels_symbol_tf_dir`/
    `src.validation._paths.labels_symbol_tf_dir` (AG-042, `project_
    assurance`, 2026-08-17) -- `resolution_id` sempre vence sobre `tf`,
    nunca combina os dois, `ValueError` explícito se não reconhecido.
    Achado real (mapa de dívida técnica multi-ativo, 2026-08-22): este
    pacote nunca tinha ganhado esta guarda, ao contrário de
    `labels`/`validation` — regime sob dollar-bar cairia silenciosamente
    em `.../15m/...` sem isto."""
    if resolution_id is not None:
        if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:
            raise ValueError(
                f"regime_symbol_tf_dir: resolution_id={resolution_id!r} não reconhecido -- "
                f"esperado um de {sorted(CALIBRATION_TF_BY_RESOLUTION)}"
            )
        grade = resolution_id
    else:
        grade = tf
    return DATA_ROOT / "regimes" / symbol / grade / version

# Duplicado de `src/exchange/_paths.py::DEFAULT_SNAPSHOTS_DIR` — mesma tática
# de duplicação tática já usada por `data`/`features` para não cruzar a
# fronteira de um módulo `_paths.py` privado de outro pacote (S10, §4.4).
EXCHANGE_INFO_SNAPSHOTS_DIR: Path = DATA_ROOT / "raw" / "snapshots" / "exchange_info"
