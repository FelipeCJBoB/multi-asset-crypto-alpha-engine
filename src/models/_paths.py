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

from src.data.build_dollar_bars import CALIBRATION_TF_BY_RESOLUTION

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

# D-06 (docs/alpha_model_design_doc_2026-08-22.md, fecha AG-154) — raiz do
# lake de artefatos versionados (`src.io.artifact.write_artifact`/
# `scan_artifact`), irmão de `predictions/`/`data/`/`models/`/`experiments/`
# no topo do repo. Namespaced por `stage` dentro (`predictions_alpha` é o
# primeiro consumidor real, `pipeline.PREDICTIONS_ARTIFACT_STAGE`) — sem
# precedente anterior no repo pra nomear (`grep write_artifact` antes desta
# mudança só achava a definição/1 teste), escolha nova: "artifacts", não
# "lake" (ADR-001 não trava um nome literal pra raiz, só o layout interno
# de `artifact_dir`).
ARTIFACT_ROOT: Path = REPO_ROOT / "artifacts"

# Layout chaveado do PRD_V4_1.md T0.3 (§3.1): `predictions/alpha/{symbol}/
# {tf}/{model_id}/`.
_DEFAULT_TF = "15m"


def _resolve_grade(*, tf: str, resolution_id: str | None) -> str:
    """`tf` (grade de tempo) OU `resolution_id` (dollar bar) — mesma guarda
    anti-colisão de `src.labels._paths.labels_symbol_tf_dir`/
    `src.validation._paths.labels_symbol_tf_dir` (AG-042, achado real de
    `project_assurance`, 2026-08-17): `resolution_id`, quando presente,
    SEMPRE vence sobre `tf` (nunca combina os dois no mesmo path) e precisa
    ser uma resolução dollar-bar reconhecida — levanta `ValueError`
    explícito caso contrário, nunca aceita string livre que pudesse colidir
    com um `tf` de grade de tempo real. Achado real (mapa de dívida técnica
    multi-ativo, 2026-08-22): este pacote nunca tinha ganhado esta guarda,
    ao contrário de `labels`/`validation` — produções/diagnósticos sob
    dollar-bar cairiam silenciosamente em `.../15m/...` sem isto."""
    if resolution_id is not None:
        if resolution_id not in CALIBRATION_TF_BY_RESOLUTION:
            raise ValueError(
                f"resolution_id={resolution_id!r} não reconhecido -- "
                f"esperado um de {sorted(CALIBRATION_TF_BY_RESOLUTION)}"
            )
        return resolution_id
    return tf


def predictions_symbol_tf_dir(
    symbol: str, model_id: str, *, tf: str = _DEFAULT_TF, resolution_id: str | None = None
) -> Path:
    """`predictions/alpha/{symbol}/{grade}/{model_id}/` — ver `_resolve_grade`."""
    grade = _resolve_grade(tf=tf, resolution_id=resolution_id)
    return PREDICTIONS_OUTPUT_DIR / "alpha" / symbol / grade / model_id

# Registro append-only de experimentos (§11.6) — mesmo diretório que
# `src/labels/_paths.py::EXPERIMENTS_DIR` resolve; este pacote grava
# `experiments/alpha_layer1_report.json` (relatório desta rodada) ali.
EXPERIMENTS_DIR: Path = REPO_ROOT / "experiments"

# `models/{model_id}/diagnostics/fold_{fold_id}_{side}.json` (task A1,
# CLAUDE.md) — diretório de DADO no topo do repo (irmão de `data/`,
# `predictions/`, `experiments/`), não o pacote de código `src/models/`.
# Movido para cá em AG-013 (`audit/architecture_gaps_log.yaml`): até essa
# mudança vivia só em `src.models.pipeline` (comentário histórico dali:
# "não movido para `_paths.py` porque esse arquivo está fora do escopo
# desta mudança") porque não havia, até então, nenhum layout chaveado por
# symbol/tf que justificasse centralizar aqui — `models_diagnostics_
# symbol_tf_dir` abaixo é exatamente esse layout, então agora os dois
# vivem juntos, mesma disciplina de `PREDICTIONS_OUTPUT_DIR`/
# `predictions_symbol_tf_dir` acima. `src.models.pipeline` importa este
# símbolo em vez de redefini-lo (`from ._paths import MODELS_DIR`);
# `pipeline.MODELS_DIR` continua existindo e monkeypatchável nos testes
# existentes — mesmo objeto `Path`, só a origem do import muda.
MODELS_DIR: Path = REPO_ROOT / "models"


def models_diagnostics_symbol_tf_dir(
    symbol: str, model_id: str, *, tf: str = _DEFAULT_TF, resolution_id: str | None = None
) -> Path:
    """`models/{symbol}/{grade}/{model_id}/diagnostics/` (AG-013) — layout
    chaveado para `src.models.pipeline.write_fold_diagnostics_atomic`/
    `write_all_fold_diagnostics` e `src.analysis.faixa1_5_prerequisites.
    _hhi_by_fold_side`, mesmo padrão `{symbol}/{tf}/{model_id}` de
    `predictions_symbol_tf_dir` acima.

    Duas diferenças deliberadas em relação a `predictions_symbol_tf_dir`,
    ambas para não inventar uma migração que não corresponde a nada que já
    existisse:

    1. SEM o segmento literal `"alpha"` entre `MODELS_DIR` e `{symbol}`.
       O layout LEGADO de predictions já tinha esse segmento
       (`predictions/alpha/{model_id}/` — §5.12 previa múltiplas famílias
       de artefato, `alpha` e futuramente `meta`, sob `predictions/`) — o
       layout chaveado só preserva o que já existia. O layout legado de
       diagnóstico é `models/{model_id}/diagnostics/`, SEM esse segmento
       (nunca existiu `models/alpha/{model_id}/`); adicionar `"alpha"`
       aqui criaria um segmento nunca presente no legado.
    2. COM o sufixo `/"diagnostics"` depois de `{model_id}` — espelha
       exatamente onde esse segmento já vive no layout legado
       (`models/{model_id}/diagnostics/`), só com `{symbol}/{tf}`
       inseridos antes de `{model_id}`.

    Por que isto é OPT-IN, nunca o novo default: `models/*/diagnostics/
    *.json` é intencionalmente VERSIONADO no git — não está no
    `.gitignore`, ao contrário do artefato binário de modelo
    (`models/{model_id}/*.bin`/`*.json` na raiz de `models/{model_id}/`).
    É "evidência de auditoria pequena e legível" (docstring de
    `write_fold_diagnostics_atomic`), mesma categoria de
    `data/quality_reports/`. Migrar o layout DEFAULT espalharia os
    arquivos de evidência já commitados (30 hoje, task A1/A2 do
    CLAUDE.md) para um caminho novo, órfãos no antigo — não é só uma
    escrita de dado descartável, é histórico de repo. Por isso
    `write_fold_diagnostics_atomic`/`write_all_fold_diagnostics`/
    `_hhi_by_fold_side` continuam com `dest_dir: Path | None = None`
    preservando `models/{model_id}/diagnostics/` bit-exato por default;
    este helper só é usado quando um chamador passa `dest_dir=
    models_diagnostics_symbol_tf_dir(...)` explicitamente. `resolution_id`
    — ver `_resolve_grade`."""
    grade = _resolve_grade(tf=tf, resolution_id=resolution_id)
    return MODELS_DIR / symbol / grade / model_id / "diagnostics"
