"""Teste golden-file de reprodutibilidade — Fase G do CLAUDE.md (auditoria
de engenharia pós-Sprint 8).

**Achado que motivou isto**: uma investigação retreinou a Camada 1 do
Alpha assumindo que XGBoost com `random_state` fixo reproduziria os
números do Sprint 8 original — sem nunca conferir isso linha a linha
contra o `hhi.mean_hhi` já persistido em `experiments/alpha_layer1_report.json`.
A suposição estava certa, mas era uma suposição, não um teste. Se uma
troca de versão do XGBoost/numpy quebrar determinismo no futuro, este
teste avisa em vez de a próxima investigação descobrir por acaso.

**Escopo deliberadamente reduzido**: reproduz o fold 0 (long+short) das
duas variantes (Camada 1 e Camada 0) em vez dos 15 splits completos —
usa a MESMA config real (mesmo `build_modeling_frame()`, mesmo
`generate_splits()`, mesmos hiperparâmetros/seed de `constants.yaml`),
só não paga o custo de treinar os outros 14 folds. Compara contra os
arquivos já commitados em `models/{model_id}/diagnostics/fold_0_*.json`
(gerados por um run completo real, Fase A) com TOLERÂNCIA ZERO em
`hhi`, `gain_by_column`, `concentration_shares`, `n_trees`,
`n_features_over_1pct` — não é um teste de "está na mesma ordem de
grandeza", é bit-a-bit (float compara por `==`, não por `pytest.approx`,
de propósito: XGBoost com `tree_method="hist"`/`random_state` fixo em
CPU é determinístico, uma diferença de ponto flutuante aqui É o sinal
que este teste existe para capturar)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import alpha, pipeline
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1, MODELS_DIR
from src.validation import cpcv

_FOLD_ID_GOLDEN = 0

_VARIANTS = (
    (MODEL_ID_CAMADA1, alpha.VARIANT_CAMADA1),
    (MODEL_ID_CAMADA0, alpha.VARIANT_CAMADA0),
)


def _golden_path(model_id: str, side_label: str) -> Path:
    return MODELS_DIR / model_id / "diagnostics" / f"fold_{_FOLD_ID_GOLDEN}_{side_label}.json"


def _skip_if_golden_missing() -> None:
    missing = [
        str(p)
        for model_id, _ in _VARIANTS
        for p in (_golden_path(model_id, "long"), _golden_path(model_id, "short"))
        if not p.exists()
    ]
    if missing:
        pytest.skip(
            "arquivo(s) golden ausente(s), rode src.models.pipeline.run_layer1_sprint() "
            f"primeiro (Fase A): {missing}"
        )


@pytest.fixture(scope="module")
def modeling_frame_and_splits() -> tuple[object, tuple[cpcv.CPCVSplit, ...]]:
    """Módulo inteiro reusa a mesma reconstrução (~20s) — os dois pares
    variante x lado do fold 0 precisam do MESMO `df_all`/`splits`, não faz
    sentido reconstruir 4x."""
    mf = ds.build_modeling_frame()
    result = cpcv.generate_splits(mf.data)
    return mf.data, result.splits


@pytest.mark.golden
@pytest.mark.slow
@pytest.mark.integration
def test_fold_0_reproduz_diagnostico_commitado_bit_a_bit(
    modeling_frame_and_splits: tuple[object, tuple[cpcv.CPCVSplit, ...]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_if_golden_missing()
    df_all, splits = modeling_frame_and_splits
    hyper = alpha.XGBHyperparams.from_constants()
    seed = int(load_constant("alpha_random_seed"))

    # Escreve num diretório temporário — este teste NUNCA sobrescreve o
    # golden real em `models/`, só o reproduz e compara ao lado.
    monkeypatch.setattr(pipeline, "MODELS_DIR", tmp_path)

    for model_id, variant in _VARIANTS:
        fresh_fold = alpha.run_fold(
            df_all,
            splits[_FOLD_ID_GOLDEN],
            variant=variant,
            hyper=hyper,
            model_id=model_id,
            seed=seed,
        )
        pipeline.write_fold_diagnostics_atomic(
            fresh_fold, model_id=model_id, expected_n_trees=hyper.n_estimators
        )

        for side_label in ("long", "short"):
            golden = json.loads(
                _golden_path(model_id, side_label).read_text(encoding="utf-8")
            )
            fresh = json.loads(
                (tmp_path / model_id / "diagnostics" / f"fold_0_{side_label}.json").read_text(
                    encoding="utf-8"
                )
            )

            # Tolerancia ZERO nos campos que a task G1 pede — HHI,
            # gain_by_column, contagens. `source`/timestamps nao existem
            # neste schema (fold diagnostics nao carrega Metric.source),
            # entao nao ha campo "sempre diferente" a excluir.
            assert fresh["hhi"] == golden["hhi"], (
                f"{model_id}/{side_label}: HHI nao reproduziu bit-a-bit — "
                f"{fresh['hhi']} != {golden['hhi']} (determinismo quebrado?)"
            )
            assert fresh["max_share"] == golden["max_share"]
            assert fresh["n_features_over_1pct"] == golden["n_features_over_1pct"]
            assert fresh["n_trees"] == golden["n_trees"]
            assert fresh["gain_by_column"] == golden["gain_by_column"]
            assert fresh["concentration_shares"] == golden["concentration_shares"]
            assert fresh["n_amostras"] == golden["n_amostras"]
