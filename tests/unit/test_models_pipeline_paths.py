"""Testes de layout de caminho (PRD_V4_1.md T0.3) — `predictions_symbol_tf_dir`,
o override `dest_dir` de `write_predictions_atomic`, e o roteamento do
parâmetro `tf` de `run_layer1_sprint` (AG-006: o único chamador de produção
de `write_predictions_atomic` nunca passava `dest_dir`, então o layout
chaveado nunca era exercitado com `symbol` real em escopo).

`tf` é sentinela `None`, NÃO `"15m"` (ver docstring de `run_layer1_sprint`
pro porquê — 7 leitores de produção reais leem
`PREDICTIONS_OUTPUT_DIR/alpha/{model_id}/predictions.parquet` direto, sem
noção de `symbol`/`tf`, e ficariam orfanados se o default migrasse
silenciosamente pro layout chaveado): `tf=None` precisa reproduzir o
caminho legado plano BIT-EXATO; só `tf` explícito usa o layout chaveado.

Os testes de `run_layer1_sprint` abaixo stubam CPCV/treino/backtest (splits
vazio -> `alpha.run_all_folds` retorna `[]` sem treinar nada de verdade) —
verificam só o ROTEAMENTO de `symbol`/`tf` até `dest_dir`, não o pipeline de
treino em si (já coberto por `tests/golden/test_sprint8_reproducibility.py`/
`tests/unit/test_models_alpha.py`)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import polars as pl
import pytest

from src.data.resample import UnsupportedTimeframeError
from src.features import build as features_build
from src.models import alpha, dataset, pipeline
from src.models._paths import (
    MODELS_DIR,
    PREDICTIONS_OUTPUT_DIR,
    models_diagnostics_symbol_tf_dir,
    predictions_symbol_tf_dir,
)
from src.validation import cpcv

# `alpha`/`dataset`/`cpcv` importados diretamente (não via `pipeline.alpha`/
# `pipeline.ds`/`pipeline.cpcv`) só por causa de `strict = true` +
# `no_implicit_reexport` (mypy, `pyproject.toml`): acessar um submódulo
# através de outro módulo que só o importou pra uso interno conta como
# "não exportado explicitamente". `pipeline.ds`/`pipeline.alpha`/
# `pipeline.cpcv` são o MESMO objeto de módulo que `dataset`/`alpha`/`cpcv`
# aqui (módulos são singletons em `sys.modules`) — monkeypatch num ou noutro
# tem efeito idêntico em produção; a escolha é só pra satisfazer mypy.


def test_predictions_symbol_tf_dir_layout_chaveado() -> None:
    path = predictions_symbol_tf_dir("ETHUSDT", "alpha_c1_v1")
    assert path == PREDICTIONS_OUTPUT_DIR / "alpha" / "ETHUSDT" / "15m" / "alpha_c1_v1"


def test_predictions_symbol_tf_dir_aceita_tf_explicito() -> None:
    path = predictions_symbol_tf_dir("ETHUSDT", "alpha_c1_v1", tf="30m")
    assert path == PREDICTIONS_OUTPUT_DIR / "alpha" / "ETHUSDT" / "30m" / "alpha_c1_v1"


def test_write_predictions_atomic_dest_dir_override_usa_layout_chaveado(tmp_path: Path) -> None:
    predictions = pl.DataFrame(
        {c: [] for c in alpha.PREDICTIONS_SCHEMA_COLUMNS},
        schema=dict.fromkeys(alpha.PREDICTIONS_SCHEMA_COLUMNS, pl.Float64),
    )
    keyed_dir = tmp_path / "ETHUSDT" / "15m" / "alpha_c1_v1"
    dest = pipeline.write_predictions_atomic(predictions, "alpha_c1_v1", dest_dir=keyed_dir)
    assert dest == keyed_dir / "predictions.parquet"
    assert dest.exists()


def test_write_predictions_atomic_sem_dest_dir_usa_caminho_legado_plano(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dest_dir=None` (omitido) — o fallback que os 7 leitores de produção
    reais listados na docstring de `run_layer1_sprint` dependem — grava em
    `PREDICTIONS_OUTPUT_DIR/alpha/{model_id}/`, NÃO no layout chaveado."""
    monkeypatch.setattr(pipeline, "PREDICTIONS_OUTPUT_DIR", tmp_path)
    predictions = pl.DataFrame(
        {c: [] for c in alpha.PREDICTIONS_SCHEMA_COLUMNS},
        schema=dict.fromkeys(alpha.PREDICTIONS_SCHEMA_COLUMNS, pl.Float64),
    )
    dest = pipeline.write_predictions_atomic(predictions, "alpha_c1_v1")
    assert dest == tmp_path / "alpha" / "alpha_c1_v1" / "predictions.parquet"
    assert dest.exists()


# ============================================================================
# models_diagnostics_symbol_tf_dir (AG-013, audit/architecture_gaps_log.yaml)
# ============================================================================


def test_models_diagnostics_symbol_tf_dir_layout_chaveado() -> None:
    path = models_diagnostics_symbol_tf_dir("ETHUSDT", "alpha_c1_v1")
    assert path == MODELS_DIR / "ETHUSDT" / "15m" / "alpha_c1_v1" / "diagnostics"


def test_models_diagnostics_symbol_tf_dir_aceita_tf_explicito() -> None:
    path = models_diagnostics_symbol_tf_dir("ETHUSDT", "alpha_c1_v1", tf="30m")
    assert path == MODELS_DIR / "ETHUSDT" / "30m" / "alpha_c1_v1" / "diagnostics"


def test_models_diagnostics_symbol_tf_dir_sem_segmento_alpha() -> None:
    """Diferença deliberada em relação a `predictions_symbol_tf_dir` (ver
    docstring do helper em `_paths.py`): o layout LEGADO de diagnóstico
    (`models/{model_id}/diagnostics/`) nunca teve um segmento `"alpha"`
    literal — só `predictions/alpha/{model_id}/` tinha. O layout chaveado
    não inventa um segmento que não existia."""
    path = models_diagnostics_symbol_tf_dir("ETHUSDT", "alpha_c1_v1")
    assert "alpha" not in path.relative_to(MODELS_DIR).parts


# ============================================================================
# run_layer1_sprint(tf=...) — roteamento até write_predictions_atomic
# ============================================================================


class _StopAfterPredictions(Exception):
    """Sentinela pra interromper `run_layer1_sprint` logo após os dois
    `write_predictions_atomic` (Camada 1 e Camada 0) terem sido chamados.
    O resto da função (backtest_lite, baselines, decomposition,
    write_report_atomic) não faz parte do que este teste verifica
    (roteamento de `dest_dir`) e stubar tudo isso pra `FoldResult` vazio
    custaria mais do que vale — abortar aqui é deliberado, não um efeito
    colateral não tratado."""


def _empty_predictions_df() -> pl.DataFrame:
    return pl.DataFrame(
        {c: [] for c in alpha.PREDICTIONS_SCHEMA_COLUMNS},
        schema=dict.fromkeys(alpha.PREDICTIONS_SCHEMA_COLUMNS, pl.Float64),
    )


def _run_layer1_sprint_capturing_predictions_calls(
    monkeypatch: pytest.MonkeyPatch, **run_kwargs: Any
) -> list[dict[str, Any]]:
    """Stuba `build_modeling_frame`/`cpcv.generate_splits` (splits vazio) e
    `assemble_predictions_table`, captura os dois `(model_id, dest_dir)`
    passados a `write_predictions_atomic`, e para a execução aí via
    `_StopAfterPredictions` — nenhum XGBoost real é treinado (o loop de
    `alpha.run_all_folds` sobre `splits=()` não executa nenhuma iteração)."""
    calls: list[dict[str, Any]] = []

    fake_mf = dataset.ModelingFrame(
        data=pl.DataFrame({"t0": []}), t1_feature_ids=(), regime_labels_present=()
    )
    monkeypatch.setattr(dataset, "build_modeling_frame", lambda *a, **k: fake_mf)

    fake_cpcv_result = SimpleNamespace(
        splits=(), config=SimpleNamespace(n_splits=0, n_backtest_paths=0)
    )
    monkeypatch.setattr(cpcv, "generate_splits", lambda *a, **k: fake_cpcv_result)
    # AG-032 item 8 -- run_layer1_sprint wireou compute_max_feature_lookback_ms
    # (fail-fast contra lookback_bars="expanding" em T1_FEATURE_IDS) no
    # CPCVConfig real; este teste não é sobre essa checagem (é sobre
    # roteamento de dest_dir), mesmo bypass já usado em
    # test_validation_leakage.py.
    monkeypatch.setattr(features_build, "compute_max_feature_lookback_ms", lambda tf: 0)

    monkeypatch.setattr(
        alpha,
        "assemble_predictions_table",
        lambda fold_results: _empty_predictions_df(),
    )

    def _fake_write_predictions_atomic(
        predictions: pl.DataFrame, model_id: str, *, dest_dir: Path | None = None
    ) -> Path:
        calls.append({"model_id": model_id, "dest_dir": dest_dir})
        if len(calls) >= 2:
            raise _StopAfterPredictions()
        # `dest_dir` é `None` no caso `tf=None` (default) — mesma
        # convenção legada de `write_predictions_atomic` real; o valor de
        # retorno aqui não é lido por `run_layer1_sprint` (descartado),
        # só precisa satisfazer a assinatura `-> Path`.
        return (dest_dir / "predictions.parquet") if dest_dir is not None else Path("unused")

    monkeypatch.setattr(pipeline, "write_predictions_atomic", _fake_write_predictions_atomic)

    with pytest.raises(_StopAfterPredictions):
        pipeline.run_layer1_sprint(**run_kwargs)

    assert len(calls) == 2
    return calls


def test_run_layer1_sprint_tf_default_preserva_caminho_legado_plano(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEM passar `tf` (`tf=None`, o que todo chamador/teste existente faz
    hoje), `run_layer1_sprint` continua chamando `write_predictions_atomic`
    com `dest_dir=None` para as DUAS variantes — bit-exato com o
    comportamento anterior a esta mudança, NÃO o layout chaveado. Ver
    docstring de `run_layer1_sprint`/AG-006: o default migrar
    silenciosamente pro layout chaveado orfanaria 7 leitores de produção
    reais que ainda leem o caminho legado plano direto."""
    calls = _run_layer1_sprint_capturing_predictions_calls(monkeypatch)

    assert calls[0] == {"model_id": pipeline.MODEL_ID_CAMADA1, "dest_dir": None}
    assert calls[1] == {"model_id": pipeline.MODEL_ID_CAMADA0, "dest_dir": None}


def test_run_layer1_sprint_tf_explicito_propaga_ate_dest_dir_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tf="30m"` explícito propaga até o `dest_dir` final de AMBAS as
    variantes (Camada 1 e Camada 0) — a prova de roteamento pedida pela
    task."""
    calls = _run_layer1_sprint_capturing_predictions_calls(monkeypatch, tf="30m")

    for call in calls:
        assert "30m" in call["dest_dir"].parts
    expected_c1 = predictions_symbol_tf_dir(pipeline.SYMBOL, pipeline.MODEL_ID_CAMADA1, tf="30m")
    expected_c0 = predictions_symbol_tf_dir(pipeline.SYMBOL, pipeline.MODEL_ID_CAMADA0, tf="30m")
    assert calls[0]["dest_dir"] == expected_c1
    assert calls[1]["dest_dir"] == expected_c0


# ============================================================================
# run_layer1_sprint(tf=..., resolution_id=..., vol_estimator_id=...) --
# propagação até build_modeling_frame/generate_splits (achado de auditoria,
# audit_engineering 2026-08-17: nenhum teste existente capturava os kwargs
# reais recebidos por esses dois -- só o roteamento de dest_dir, que não
# prova que build_modeling_frame/CPCVConfig de fato receberam tf/
# resolution_id/vol_estimator_id/config/symbol corretos)
# ============================================================================


def _run_layer1_sprint_capturing_core_calls(
    monkeypatch: pytest.MonkeyPatch, **run_kwargs: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mesmo padrão de `_run_layer1_sprint_capturing_predictions_calls`, mas
    captura os KWARGS reais recebidos por `build_modeling_frame`/
    `generate_splits` (a correção-âncora desta migração, Fase 4) em vez de
    descartá-los."""
    bmf_calls: dict[str, Any] = {}
    gs_calls: dict[str, Any] = {}

    fake_mf = dataset.ModelingFrame(
        data=pl.DataFrame({"t0": []}), t1_feature_ids=(), regime_labels_present=()
    )

    def _fake_build_modeling_frame(**kwargs: Any) -> dataset.ModelingFrame:
        bmf_calls.update(kwargs)
        return fake_mf

    monkeypatch.setattr(dataset, "build_modeling_frame", _fake_build_modeling_frame)

    fake_cpcv_result = SimpleNamespace(
        splits=(), config=SimpleNamespace(n_splits=0, n_backtest_paths=0)
    )

    def _fake_generate_splits(
        labels: pl.DataFrame, config: object = None, *, symbol: str | None = None
    ) -> object:
        gs_calls.update(config=config, symbol=symbol)
        return fake_cpcv_result

    monkeypatch.setattr(cpcv, "generate_splits", _fake_generate_splits)
    # AG-032 item 8 -- ver comentário equivalente em
    # _run_layer1_sprint_capturing_predictions_calls acima.
    monkeypatch.setattr(features_build, "compute_max_feature_lookback_ms", lambda tf: 0)
    monkeypatch.setattr(
        alpha, "assemble_predictions_table", lambda fold_results: _empty_predictions_df()
    )

    def _fake_write_predictions_atomic(
        predictions: pl.DataFrame, model_id: str, *, dest_dir: Path | None = None
    ) -> Path:
        raise _StopAfterPredictions()

    monkeypatch.setattr(pipeline, "write_predictions_atomic", _fake_write_predictions_atomic)

    with pytest.raises(_StopAfterPredictions):
        pipeline.run_layer1_sprint(**run_kwargs)

    return bmf_calls, gs_calls


def test_run_layer1_sprint_tf_explicito_propaga_ate_build_modeling_frame_e_cpcv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado de auditoria: `tf="30m"` era validado (`step_ms`) mas nunca
    chegava a `build_modeling_frame`/`generate_splits` -- bug real corrigido
    na Fase 4, sem teste de regressão até agora."""
    bmf_calls, gs_calls = _run_layer1_sprint_capturing_core_calls(monkeypatch, tf="30m")

    assert bmf_calls["tf"] == "30m"
    assert bmf_calls["resolution_id"] is None
    assert bmf_calls["vol_estimator_id"] is None
    assert bmf_calls["symbol"] == pipeline.SYMBOL

    assert gs_calls["symbol"] == pipeline.SYMBOL
    cpcv_config = gs_calls["config"]
    assert cpcv_config.tf == "30m"
    assert cpcv_config.grade_id == "30m"


def test_run_layer1_sprint_resolution_id_propaga_ate_build_modeling_frame_e_cpcv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resolution_id="R1"` vence sobre `tf` (que fica `None`, sentinela
    legado) na construção do `grade_id` do CPCV -- mesmo desenho de UM
    parâmetro de grade das Fases 2-4."""
    bmf_calls, gs_calls = _run_layer1_sprint_capturing_core_calls(
        monkeypatch, resolution_id="R1", vol_estimator_id="parkinson_w20"
    )

    assert bmf_calls["tf"] == "15m"  # tf_effective (tf=None -> "15m")
    assert bmf_calls["resolution_id"] == "R1"
    assert bmf_calls["vol_estimator_id"] == "parkinson_w20"

    cpcv_config = gs_calls["config"]
    assert cpcv_config.grade_id == "R1"


def test_run_layer1_sprint_tf_invalido_levanta_cedo_sem_trabalho_caro() -> None:
    """`step_ms(tf)` valida ANTES de `build_modeling_frame`/CPCV/treino —
    nenhum monkeypatch nesta função: se a validação não fosse a primeira
    linha de `run_layer1_sprint`, este teste tentaria I/O real (labels/
    features/regime) e falharia por outro motivo, não pelo `tf`
    inválido."""
    with pytest.raises(UnsupportedTimeframeError):
        pipeline.run_layer1_sprint(tf="7m")
