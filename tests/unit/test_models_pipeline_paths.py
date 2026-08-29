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
from src.io import artifact as io_artifact
from src.models import alpha, dataset, hyperparams_by_combo, pipeline
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


def test_predictions_symbol_tf_dir_aceita_resolution_id() -> None:
    """Achado real (mapa de dívida técnica multi-ativo, 2026-08-22):
    `predictions_symbol_tf_dir` nunca tinha suporte a `resolution_id`
    (dollar-bar), ao contrário de `labels_symbol_tf_dir`
    (`src.labels._paths`/`src.validation._paths`, AG-042). `resolution_id`
    vence sobre `tf` -- mesma guarda anti-colisão."""
    path = predictions_symbol_tf_dir("ETHUSDT", "alpha_c1_v1", tf="30m", resolution_id="R1")
    assert path == PREDICTIONS_OUTPUT_DIR / "alpha" / "ETHUSDT" / "R1" / "alpha_c1_v1"


def test_predictions_symbol_tf_dir_resolution_id_nao_reconhecido_levanta_valueerror() -> None:
    with pytest.raises(ValueError, match="resolution_id"):
        predictions_symbol_tf_dir("ETHUSDT", "alpha_c1_v1", resolution_id="R99")


def test_models_diagnostics_symbol_tf_dir_aceita_resolution_id() -> None:
    path = models_diagnostics_symbol_tf_dir("ETHUSDT", "alpha_c1_v1", resolution_id="R2")
    assert path == MODELS_DIR / "ETHUSDT" / "R2" / "alpha_c1_v1" / "diagnostics"


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
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )

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
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    monkeypatch.setattr(
        alpha, "assemble_predictions_table", lambda fold_results: _empty_predictions_df()
    )

    def _fake_write_predictions_atomic(
        predictions: pl.DataFrame, model_id: str, *, dest_dir: Path | None = None
    ) -> Path:
        raise _StopAfterPredictions()

    monkeypatch.setattr(pipeline, "write_predictions_atomic", _fake_write_predictions_atomic)

    # D-06 (2026-08-23, fecha AG-154) -- resolution_id setado agora roteia
    # pra write_predictions_versioned, não write_predictions_atomic (ver
    # docstring de write_predictions_versioned). Este helper é usado tanto
    # pro ramo legado (tf="30m", resolution_id=None) quanto pro ramo novo
    # (resolution_id="R1") -- precisa do sentinela nos DOIS writers pra
    # parar cedo em qualquer um dos dois, sem se importar qual é chamado.
    def _fake_write_predictions_versioned(*args: Any, **kwargs: Any) -> Any:
        raise _StopAfterPredictions()

    monkeypatch.setattr(pipeline, "write_predictions_versioned", _fake_write_predictions_versioned)

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
    # **[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27]** vol_estimator_id=None
    # não chega mais None em build_modeling_frame -- run_layer1_sprint
    # resolve pra constants.yaml::canonical_volatility_estimator antes de
    # chamar. "parkinson_w20" é o valor real de constants.yaml, não
    # invenção do teste (mesma convenção de test_models_alpha_hyperparams_
    # wiring.py::test_from_constants_default_le_ic_magnitude_floor_k).
    assert bmf_calls["vol_estimator_id"] == "parkinson_w20"
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


def test_run_layer1_sprint_vol_estimator_id_explicito_legado_vence_sobre_o_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27]** o legado (ATRWilder)
    continua acessível -- só deixou de ser o que `None` significa. Quem
    passa `vol_estimator_id` explícito, mesmo o valor legado, chega
    intacto em `build_modeling_frame` -- a resolução via `constants.yaml`
    só entra quando o caller não decide nada."""
    bmf_calls, _ = _run_layer1_sprint_capturing_core_calls(
        monkeypatch, resolution_id="R1", vol_estimator_id="atr_wilder_w20"
    )

    assert bmf_calls["vol_estimator_id"] == "atr_wilder_w20"


class _StopAfterDiagnostics(Exception):
    """Sentinela pra interromper `run_layer1_sprint` logo após os dois
    `write_all_fold_diagnostics` terem sido chamados — mesma disciplina de
    `_StopAfterPredictions`, mas pro roteamento de diagnósticos.

    Achado real (revisão `audit_engineering`, 2026-08-22): o helper de
    predictions (`_run_layer1_sprint_capturing_predictions_calls`) NUNCA
    exercitava `models_diagnostics_symbol_tf_dir` de verdade —
    `write_all_fold_diagnostics` itera `fold_results` internamente
    (`write_fold_diagnostics_atomic` por fold), e como `splits=()` produz
    `fold_results=[]`, o loop interno nunca roda; só o `dest_dir` PASSADO
    pra `write_all_fold_diagnostics` importa pro roteamento, então
    monkeypatch direto nela (como já feito pra `write_predictions_atomic`)
    é suficiente e não precisa de fold real."""


def _run_layer1_sprint_capturing_diagnostics_calls(
    monkeypatch: pytest.MonkeyPatch, **run_kwargs: Any
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    fake_mf = dataset.ModelingFrame(
        data=pl.DataFrame({"t0": []}), t1_feature_ids=(), regime_labels_present=()
    )
    monkeypatch.setattr(dataset, "build_modeling_frame", lambda *a, **k: fake_mf)

    fake_cpcv_result = SimpleNamespace(
        splits=(), config=SimpleNamespace(n_splits=0, n_backtest_paths=0)
    )
    monkeypatch.setattr(cpcv, "generate_splits", lambda *a, **k: fake_cpcv_result)
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )

    def _fake_write_all_fold_diagnostics(
        fold_results: list[Any], *, model_id: str, hyper: Any, dest_dir: Path | None = None
    ) -> None:
        calls.append({"model_id": model_id, "dest_dir": dest_dir})
        if len(calls) >= 2:
            raise _StopAfterDiagnostics()

    monkeypatch.setattr(pipeline, "write_all_fold_diagnostics", _fake_write_all_fold_diagnostics)

    with pytest.raises(_StopAfterDiagnostics):
        pipeline.run_layer1_sprint(**run_kwargs)

    assert len(calls) == 2
    return calls


def test_run_layer1_sprint_resolution_id_propaga_ate_dest_dir_diagnosticos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado real (revisão `audit_engineering`, 2026-08-22): o teste
    irmão (`..._dest_dir_final`, abaixo) só provava o roteamento de
    `predictions_symbol_tf_dir` — `models_diagnostics_symbol_tf_dir` (os
    outros 2 dos 4 call sites corrigidos em `pipeline.py`) nunca era
    exercitado, nem implicitamente (uma regressão isolada nos 2 call
    sites de diagnóstico não seria pega por nenhum teste existente)."""
    calls = _run_layer1_sprint_capturing_diagnostics_calls(monkeypatch, resolution_id="R1")

    for call in calls:
        assert call["dest_dir"] is not None
        assert "R1" in call["dest_dir"].parts
        assert "15m" not in call["dest_dir"].parts
    expected_c1 = models_diagnostics_symbol_tf_dir(
        pipeline.SYMBOL, pipeline.MODEL_ID_CAMADA1, resolution_id="R1"
    )
    expected_c0 = models_diagnostics_symbol_tf_dir(
        pipeline.SYMBOL, pipeline.MODEL_ID_CAMADA0, resolution_id="R1"
    )
    assert calls[0] == {"model_id": pipeline.MODEL_ID_CAMADA1, "dest_dir": expected_c1}
    assert calls[1] == {"model_id": pipeline.MODEL_ID_CAMADA0, "dest_dir": expected_c0}


def _run_layer1_sprint_capturing_versioned_predictions_calls(
    monkeypatch: pytest.MonkeyPatch, **run_kwargs: Any
) -> list[dict[str, Any]]:
    """Mesmo padrão de `_run_layer1_sprint_capturing_predictions_calls`,
    pro ramo `resolution_id is not None` (D-06, 2026-08-23, fecha
    `AG-154`) -- captura os kwargs reais passados a
    `write_predictions_versioned` (`root`/`symbol`/`resolution_id`/
    `model_id`/`config`), não `dest_dir` (que não existe mais nesse
    ramo -- `io.artifact.write_artifact` deriva o caminho de
    `root`+`stage`+`config_hash`+`symbol`+`resolution`, não recebe um
    `Path` explícito)."""
    calls: list[dict[str, Any]] = []

    fake_mf = dataset.ModelingFrame(
        data=pl.DataFrame({"t0": []}), t1_feature_ids=(), regime_labels_present=()
    )
    monkeypatch.setattr(dataset, "build_modeling_frame", lambda *a, **k: fake_mf)

    fake_cpcv_result = SimpleNamespace(
        splits=(), config=SimpleNamespace(n_splits=0, n_backtest_paths=0)
    )
    monkeypatch.setattr(cpcv, "generate_splits", lambda *a, **k: fake_cpcv_result)
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    monkeypatch.setattr(
        alpha, "assemble_predictions_table", lambda fold_results: _empty_predictions_df()
    )

    def _fake_write_predictions_versioned(
        predictions: pl.DataFrame,
        *,
        root: Path,
        symbol: str,
        resolution_id: str,
        model_id: str,
        config: dict[str, Any],
        scratch: bool = False,
    ) -> Any:
        calls.append(
            {
                "root": root,
                "symbol": symbol,
                "resolution_id": resolution_id,
                "model_id": model_id,
                "config": config,
                "scratch": scratch,
            }
        )
        if len(calls) >= 2:
            raise _StopAfterPredictions()
        return None

    monkeypatch.setattr(pipeline, "write_predictions_versioned", _fake_write_predictions_versioned)

    with pytest.raises(_StopAfterPredictions):
        pipeline.run_layer1_sprint(**run_kwargs)

    assert len(calls) == 2
    return calls


def test_run_layer1_sprint_resolution_id_propaga_ate_write_predictions_versioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resolution_id="R1"` propaga até `write_predictions_versioned`
    (D-06, 2026-08-23, fecha `AG-154`) pras DUAS variantes (Camada 1 e
    Camada 0), com `root=ARTIFACT_ROOT` e `config["variant"]` distinguindo
    as duas -- não mais `write_predictions_atomic`/`dest_dir` pra este
    ramo (achado desta rodada: `write_predictions_versioned` exige
    `resolution_id: str`, não opcional, só pode servir este ramo mesmo)."""
    calls = _run_layer1_sprint_capturing_versioned_predictions_calls(
        monkeypatch, resolution_id="R1"
    )

    # AG-371-ADDENDUM-10 (2026-08-28) -- config de AMBAS as variantes
    # ganhou tau_policy/calib_split_mode/class_balance_basis/calib_
    # weight_basis (sempre, sem gate condicional -- os 4 nunca têm
    # sentinela "não especificado", `run_layer1_sprint` já resolve pro
    # default concreto antes daqui). Valores abaixo são os defaults da
    # função (nenhum passado explícito neste teste).
    base_config_extra = {
        "tau_policy": alpha.TAU_POLICY_LEGACY_PER_SIDE,
        "calib_split_mode": alpha.CALIB_SPLIT_TEMPORAL_PURGED,
        "class_balance_basis": alpha.CLASS_BALANCE_WEIGHT,
        "calib_weight_basis": alpha.CALIB_WEIGHT_UNIQUENESS,
    }

    assert calls[0]["symbol"] == pipeline.SYMBOL
    assert calls[0]["resolution_id"] == "R1"
    assert calls[0]["model_id"] == pipeline.MODEL_ID_CAMADA1
    assert calls[0]["config"] == {"variant": alpha.VARIANT_CAMADA1, **base_config_extra}
    assert calls[0]["root"] == pipeline.ARTIFACT_ROOT
    assert calls[0]["scratch"] is False

    assert calls[1]["symbol"] == pipeline.SYMBOL
    assert calls[1]["resolution_id"] == "R1"
    assert calls[1]["model_id"] == pipeline.MODEL_ID_CAMADA0
    # AG-371-ADDENDUM-8 (2026-08-28) -- config de Camada0 ganhou
    # `camada0_constrained_features` (entra no config_hash de propósito,
    # pra um retreino sob a correção nunca colidir com um artefato
    # pré-correção); Camada1 continua sem essa chave.
    assert calls[1]["config"] == {
        "variant": alpha.VARIANT_CAMADA0,
        **base_config_extra,
        "camada0_constrained_features": sorted(alpha.CAMADA0_CONSTRAINED_FEATURES),
    }
    assert calls[1]["root"] == pipeline.ARTIFACT_ROOT
    assert calls[1]["scratch"] is False


def test_run_layer1_sprint_scratch_true_propaga_ate_write_predictions_versioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regressão de `AG-368` (2026-08-27): `scratch=True` precisa chegar
    ATÉ `write_predictions_versioned` pras DUAS variantes -- achado ao
    vivo rodando `ag362_incremental_value_report.py` (2 designs
    diferentes resolvendo pro mesmo `config_hash` numa célula sem
    calibração própria em `alpha_hyperparams_by_combo.yaml`,
    `ArtifactExistsError` na 2ª escrita; `scratch=True` é o mecanismo já
    existente de `write_artifact`/ADR-001 pra iteração exploratória)."""
    calls = _run_layer1_sprint_capturing_versioned_predictions_calls(
        monkeypatch, resolution_id="R1", scratch=True
    )

    assert calls[0]["scratch"] is True
    assert calls[1]["scratch"] is True


class _StopAfterCamada0ArtifactCollision(Exception):
    pass


def test_run_layer1_sprint_camada0_artifact_existente_nao_crasha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-371-ADDENDUM-15 (2026-08-28) -- achado real ao rodar o braço
    by-combo do Passo 1: célula sem entrada em `alpha_hyperparams_by_combo
    .yaml` cai em `hyper=None` nos DOIS braços (global e by-combo),
    produzindo config de Camada0 idêntica a um artefato canônico já
    escrito pelo braço global -- `ArtifactExistsError` sem captura (só
    Camada1 tinha o try/except desde `AG-371-ADDENDUM-9`) matava
    `run_layer1_sprint_all_combinations` inteiro na primeira célula sem
    calibração própria. Prova que o write de Camada0 agora captura
    `ArtifactExistsError` e o run PROSSEGUE (chega em `backtest_by_path`,
    a próxima etapa real do corpo) em vez de propagar."""
    fake_mf = dataset.ModelingFrame(
        data=pl.DataFrame({"t0": []}), t1_feature_ids=(), regime_labels_present=()
    )
    monkeypatch.setattr(dataset, "build_modeling_frame", lambda *a, **k: fake_mf)
    fake_cpcv_result = SimpleNamespace(
        splits=(), config=SimpleNamespace(n_splits=0, n_backtest_paths=0)
    )
    monkeypatch.setattr(cpcv, "generate_splits", lambda *a, **k: fake_cpcv_result)
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    monkeypatch.setattr(
        alpha, "assemble_predictions_table", lambda fold_results: _empty_predictions_df()
    )

    write_calls: list[str] = []

    def _fake_write_predictions_versioned(
        predictions: pl.DataFrame,
        *,
        root: Path,
        symbol: str,
        resolution_id: str,
        model_id: str,
        config: dict[str, Any],
        scratch: bool = False,
    ) -> Any:
        write_calls.append(config["variant"])
        if config["variant"] == alpha.VARIANT_CAMADA0:
            raise io_artifact.ArtifactExistsError("config_hash ja existe -- artefato canonico")
        return None

    monkeypatch.setattr(pipeline, "write_predictions_versioned", _fake_write_predictions_versioned)
    monkeypatch.setattr(
        pipeline.backtest_lite,
        "backtest_by_path",
        lambda *a, **k: (_ for _ in ()).throw(_StopAfterCamada0ArtifactCollision()),
    )

    with pytest.raises(_StopAfterCamada0ArtifactCollision):
        pipeline.run_layer1_sprint(resolution_id="R1")

    assert write_calls == [alpha.VARIANT_CAMADA1, alpha.VARIANT_CAMADA0]


def test_run_layer1_sprint_tf_invalido_levanta_cedo_sem_trabalho_caro() -> None:
    """`step_ms(tf)` valida ANTES de `build_modeling_frame`/CPCV/treino —
    nenhum monkeypatch nesta função: se a validação não fosse a primeira
    linha de `run_layer1_sprint`, este teste tentaria I/O real (labels/
    features/regime) e falharia por outro motivo, não pelo `tf`
    inválido."""
    with pytest.raises(UnsupportedTimeframeError):
        pipeline.run_layer1_sprint(tf="7m")


def test_run_layer1_sprint_feature_com_defeito_construcao_levanta_cedo_sem_trabalho_caro() -> (
    None
):
    """Achado real 2026-08-27 (handoff de `src/models/`, `AG-296`/`AG-297`/
    item 3): `E11f_oi_change_1d` (`defeito_construcao: true`) já entrou num
    LightGBM real via a campanha T2→T1 sem gate nenhum. `assert_no_defeito_
    construcao_in_active_set` valida ANTES de `build_modeling_frame` --
    mesmo padrão de `test_run_layer1_sprint_tf_invalido_levanta_cedo_sem_
    trabalho_caro`, nenhum monkeypatch: se a validação não fosse anterior
    ao IO, este teste tentaria carregar labels/features reais e falharia
    por outro motivo."""
    with pytest.raises(features_build.DefeitoConstrucaoFeatureError, match="E11f_oi_change_1d"):
        pipeline.run_layer1_sprint(
            feature_ids=(*features_build.T1_FEATURE_IDS, "E11f_oi_change_1d")
        )


# ============================================================================
# run_layer1_sprint_all_combinations — D-13 (docs/alpha_model_design_doc_
# 2026-08-22.md §7). Monkeypatcha run_layer1_sprint INTEIRO (não seus
# internos) -- orquestração, não repete a cobertura de treino já testada
# em outro lugar.
# ============================================================================


def test_run_layer1_sprint_all_combinations_roda_5x3_com_report_path_unico(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_run_layer1_sprint(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"layer1_vs_layer0": {"permanence_pass": True}}

    monkeypatch.setattr(pipeline, "run_layer1_sprint", _fake_run_layer1_sprint)

    reports = pipeline.run_layer1_sprint_all_combinations()

    assert len(calls) == 15  # 5 símbolos x {R1, R2, R3}
    assert len(reports) == 15
    pairs = [(c["symbol"], c["resolution_id"]) for c in calls]
    assert len(set(pairs)) == 15  # nenhuma combinação repetida

    # AG-160 -- report_path único por combinação, nunca o default
    # compartilhado (experiments/alpha_layer1_report.json).
    report_paths = [c["report_path"] for c in calls]
    assert len(set(report_paths)) == 15
    for symbol, resolution_id in pairs:
        expected = pipeline.EXPERIMENTS_DIR / f"alpha_layer1_report_{symbol}_{resolution_id}.json"
        assert expected in report_paths


def test_run_layer1_sprint_all_combinations_symbols_resolutions_customizados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        pipeline,
        "run_layer1_sprint",
        lambda **kwargs: calls.append(kwargs) or {"layer1_vs_layer0": {"permanence_pass": True}},
    )

    pipeline.run_layer1_sprint_all_combinations(symbols=("BTCUSDT", "ETHUSDT"), resolutions=("R1",))

    assert len(calls) == 2
    assert {(c["symbol"], c["resolution_id"]) for c in calls} == {
        ("BTCUSDT", "R1"),
        ("ETHUSDT", "R1"),
    }


def test_run_layer1_sprint_all_combinations_report_tag_suffix_evita_sobrescrita(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-371-ADDENDUM-13 -- rodar --all-combinations 2x (ex. braço global +
    braço by-combo) sem sufixo faz a 2a chamada sobrescrever o report_path
    da 1a (mesmo nome, artefato de modelo já é content-addressed e não
    colide). `report_tag_suffix` diferencia o nome do relatório-resumo;
    default "" preserva o nome de sempre (coberto pelo teste acima)."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        pipeline,
        "run_layer1_sprint",
        lambda **kwargs: calls.append(kwargs) or {"layer1_vs_layer0": {}},
    )

    pipeline.run_layer1_sprint_all_combinations(
        symbols=("BTCUSDT",), resolutions=("R1",), report_tag_suffix="_bycombo"
    )

    expected = pipeline.EXPERIMENTS_DIR / "alpha_layer1_report_BTCUSDT_R1_bycombo.json"
    assert calls[0]["report_path"] == expected


# ============================================================================
# run_layer1_sprint_all_combinations x hyperparams_by_combo -- AG-371
# (2026-08-28). `load_hyperparams_by_combo` monkeypatchado direto (não o
# YAML real) -- estes testes cobrem só o THREADING de
# feature_ids_effective/allow_feature_mismatch/report["hyperparam_
# feature_mismatch"], não a lógica de hash em si (isso é
# test_models_hyperparams_by_combo.py).
# ============================================================================


def test_run_layer1_sprint_all_combinations_resolve_feature_ids_antes_do_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-371 -- `feature_ids=None` (sentinela) precisa chegar em
    `load_hyperparams_by_combo` já resolvido pro vetor ativo
    (`features_build.T1_FEATURE_IDS`), não como `None` cru -- é o mesmo
    vetor que `run_layer1_sprint` resolve internamente
    (`features_build.resolve_feature_ids`); duas fontes de verdade
    divergindo foi a causa raiz do AG-371 original."""
    seen: list[tuple[str, ...]] = []

    def _fake_load(
        symbol: str,
        resolution_id: str,
        *,
        feature_ids_effective: tuple[str, ...],
        **kwargs: Any,
    ) -> tuple[None, bool]:
        seen.append(feature_ids_effective)
        return None, False

    monkeypatch.setattr(hyperparams_by_combo, "load_hyperparams_by_combo", _fake_load)
    monkeypatch.setattr(
        pipeline, "run_layer1_sprint", lambda **kwargs: {"layer1_vs_layer0": {}}
    )

    pipeline.run_layer1_sprint_all_combinations(
        symbols=("BTCUSDT",), resolutions=("R1",), use_hyperparams_by_combo=True
    )

    assert seen == [features_build.T1_FEATURE_IDS]


def test_run_layer1_sprint_all_combinations_passa_feature_mismatch_como_parametro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-371-ADDENDUM-16 (2026-08-29) -- regressão real: a versão antiga
    mutava `report["hyperparam_feature_mismatch"]` DEPOIS de receber o
    dict de volta de `run_layer1_sprint`, que já tinha gravado o JSON em
    disco (`write_report_atomic`) ANTES de retornar -- a mutação só
    afetava a cópia em memória, o arquivo persistido nunca carregava a
    chave (medido real: os 15 relatórios `_bycombo` do braço by-combo
    desta sessão, 10/15 com mismatch genuíno, nenhum com a chave no JSON).
    Fix: `hyperparam_feature_mismatch` vira PARÂMETRO de `run_layer1_
    sprint`, resolvido pelo chamador ANTES da chamada -- este teste prova
    que o kwarg chega, não que o dict de retorno mude (isso agora é
    responsabilidade de `run_layer1_sprint`, coberto pelos testes dele
    próprio)."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        hyperparams_by_combo,
        "load_hyperparams_by_combo",
        lambda *a, **kw: (alpha.LGBMHyperparams.from_constants(), True),
    )
    monkeypatch.setattr(
        pipeline,
        "run_layer1_sprint",
        lambda **kwargs: calls.append(kwargs) or {"layer1_vs_layer0": {}},
    )

    pipeline.run_layer1_sprint_all_combinations(
        symbols=("BTCUSDT",),
        resolutions=("R1",),
        use_hyperparams_by_combo=True,
        allow_feature_mismatch=True,
    )

    assert calls[0]["hyperparam_feature_mismatch"] is True


def test_run_layer1_sprint_all_combinations_sem_mismatch_passa_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        hyperparams_by_combo,
        "load_hyperparams_by_combo",
        lambda *a, **kw: (alpha.LGBMHyperparams.from_constants(), False),
    )
    monkeypatch.setattr(
        pipeline,
        "run_layer1_sprint",
        lambda **kwargs: calls.append(kwargs) or {"layer1_vs_layer0": {}},
    )

    pipeline.run_layer1_sprint_all_combinations(
        symbols=("BTCUSDT",), resolutions=("R1",), use_hyperparams_by_combo=True
    )

    assert calls[0]["hyperparam_feature_mismatch"] is False


def test_run_layer1_sprint_all_combinations_propaga_mismatch_error_por_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`allow_feature_mismatch=False` (default) -- a exceção do loader
    precisa propagar até o chamador do CLI/script, não ser engolida."""

    def _fake_load(*args: Any, **kwargs: Any) -> Any:
        raise hyperparams_by_combo.HyperparamFeatureMismatchError("mismatch de teste")

    monkeypatch.setattr(hyperparams_by_combo, "load_hyperparams_by_combo", _fake_load)

    with pytest.raises(hyperparams_by_combo.HyperparamFeatureMismatchError):
        pipeline.run_layer1_sprint_all_combinations(
            symbols=("BTCUSDT",), resolutions=("R1",), use_hyperparams_by_combo=True
        )


def _run_layer1_sprint_capturing_run_all_folds_calls(
    monkeypatch: pytest.MonkeyPatch, **run_kwargs: Any
) -> list[dict[str, Any]]:
    """Mesmo padrão de `_run_layer1_sprint_capturing_predictions_calls`,
    mas captura os kwargs de `alpha.run_all_folds` em vez de `dest_dir` --
    `splits=()` (via `cpcv.generate_splits` stubado) faria o loop INTERNO
    de `run_all_folds` não rodar nenhuma vez, então esse teste precisa
    stubar `run_all_folds` diretamente pra exercitar o argumento passado
    a ele (D-18, `device_type`), não o que ele faz por dentro."""
    calls: list[dict[str, Any]] = []

    fake_mf = dataset.ModelingFrame(
        data=pl.DataFrame({"t0": []}), t1_feature_ids=(), regime_labels_present=()
    )
    monkeypatch.setattr(dataset, "build_modeling_frame", lambda *a, **k: fake_mf)
    fake_cpcv_result = SimpleNamespace(
        splits=(), config=SimpleNamespace(n_splits=0, n_backtest_paths=0)
    )
    monkeypatch.setattr(cpcv, "generate_splits", lambda *a, **k: fake_cpcv_result)
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )

    def _fake_run_all_folds(*_args: Any, **kwargs: Any) -> list[Any]:
        calls.append(kwargs)
        return []

    monkeypatch.setattr(alpha, "run_all_folds", _fake_run_all_folds)
    monkeypatch.setattr(
        alpha, "assemble_predictions_table", lambda fold_results: _empty_predictions_df()
    )

    def _fake_write_predictions_atomic(
        predictions: pl.DataFrame, model_id: str, *, dest_dir: Path | None = None
    ) -> Path:
        if len(calls) >= 2:
            raise _StopAfterPredictions()
        return Path("unused")

    monkeypatch.setattr(pipeline, "write_predictions_atomic", _fake_write_predictions_atomic)

    with pytest.raises(_StopAfterPredictions):
        pipeline.run_layer1_sprint(**run_kwargs)

    assert len(calls) == 2  # camada1 + camada0
    return calls


def test_run_layer1_sprint_device_type_default_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """**ATUALIZADO 2026-08-25 -- este teste estava VERMELHO e afirmava o
    oposto do codigo.** Chamava-se `..._default_cuda` e exigia
    `device_type == "cuda"`, ancorado em D-18 ("GPU obrigatoria em
    producao"). `AG-201` (2026-08-24) trocou o default de
    `run_layer1_sprint` para `"cpu"` por bloqueio ESTRUTURAL, nao por
    preferencia: LightGBM 4.7.0 exige NCCL incondicionalmente sob
    `USE_CUDA=ON` (`CMakeLists.txt:243`) e NCCL nao tem build nativo
    Windows -- toda chamada real ja precisava passar `"cpu"` a mao. O
    teste nao foi revisado junto da correcao, entao a suite ficou
    quebrada com um teste que codificava o comportamento ANTIGO como se
    fosse contrato.

    Achado colateral (persona `lgbm-crypto-quant`, 2026-08-25): e
    exatamente o padrao de dessincronizacao que `AG-123` cataloga
    (correcao aplicada num lugar, referencias ao mesmo `AG-NNN` nao
    revisadas) -- aqui entre codigo e teste, nao entre secoes de doc.

    O contrato que este teste passa a codificar: o default e `"cpu"`
    NESTE AMBIENTE, e mudar isso e decisao explicita do Manager quando/se
    o treino migrar para Linux/cloud com CUDA+NCCL funcionais -- nunca um
    reflip por engano."""
    calls = _run_layer1_sprint_capturing_run_all_folds_calls(monkeypatch)
    assert all(c["device_type"] == "cpu" for c in calls)


def test_run_layer1_sprint_device_type_explicito_sobrescreve_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`"cuda"` explicito continua chegando intacto a `run_all_folds` -- o
    mecanismo de opt-in de D-18 sobreviveu a `AG-201`, so o DEFAULT mudou.
    Trocado de `"cpu"` para `"cuda"` junto da atualizacao acima: com o
    default agora `"cpu"`, passar `"cpu"` explicito nao provava mais nada
    (o teste passaria mesmo se o parametro fosse ignorado)."""
    calls = _run_layer1_sprint_capturing_run_all_folds_calls(monkeypatch, device_type="cuda")
    assert all(c["device_type"] == "cuda" for c in calls)


# ============================================================================
# run_layer1_sprint(persist_model_bundles=...) -- roteamento até
# write_all_fold_model_bundles (AG-141/item 10 de ADR-005 §13.17). Mesmo
# padrão dos blocos acima: stuba CPCV/treino (splits vazio), captura os
# kwargs reais recebidos por write_all_fold_model_bundles em vez de
# descartá-los ou exercitar o pipeline de treino de verdade.
# ============================================================================


def _run_layer1_sprint_capturing_model_bundle_calls(
    monkeypatch: pytest.MonkeyPatch, **run_kwargs: Any
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    fake_mf = dataset.ModelingFrame(
        data=pl.DataFrame({"t0": []}), t1_feature_ids=(), regime_labels_present=()
    )
    monkeypatch.setattr(dataset, "build_modeling_frame", lambda *a, **k: fake_mf)
    fake_cpcv_result = SimpleNamespace(
        splits=(), config=SimpleNamespace(n_splits=0, n_backtest_paths=0)
    )
    monkeypatch.setattr(cpcv, "generate_splits", lambda *a, **k: fake_cpcv_result)
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 42
    )
    monkeypatch.setattr(alpha, "run_all_folds", lambda *a, **k: [])
    monkeypatch.setattr(
        alpha, "assemble_predictions_table", lambda fold_results: _empty_predictions_df()
    )

    def _fake_write_all_fold_model_bundles(fold_results: list[Any], **kwargs: Any) -> list[Any]:
        calls.append(kwargs)
        return []

    monkeypatch.setattr(
        pipeline, "write_all_fold_model_bundles", _fake_write_all_fold_model_bundles
    )

    def _fake_write_predictions_atomic(
        predictions: pl.DataFrame, model_id: str, *, dest_dir: Path | None = None
    ) -> Path:
        raise _StopAfterPredictions()

    monkeypatch.setattr(pipeline, "write_predictions_atomic", _fake_write_predictions_atomic)

    def _fake_write_predictions_versioned(*args: Any, **kwargs: Any) -> Any:
        raise _StopAfterPredictions()

    monkeypatch.setattr(pipeline, "write_predictions_versioned", _fake_write_predictions_versioned)

    with pytest.raises(_StopAfterPredictions):
        pipeline.run_layer1_sprint(**run_kwargs)

    return calls


def test_run_layer1_sprint_persist_model_bundles_default_nunca_chama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default `persist_model_bundles=False` -- bit-exato com todo call
    site/teste existente, nenhum grava bundle de modelo hoje."""
    calls = _run_layer1_sprint_capturing_model_bundle_calls(monkeypatch, tf="30m")
    assert calls == []


def test_run_layer1_sprint_persist_model_bundles_true_mas_caminho_legado_plano_nao_chama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`persist_model_bundles=True` sozinho não basta -- sem `tf`/
    `resolution_id` explícito (`path_tf is None`, o caminho legado plano),
    o gate recusa: `symbol`/`resolution_id` não bastam pra nomear uma
    partição sem colisão sob a grade de tempo legada (mesmo motivo do
    gate de diagnóstico, `dest_dir_diag_c1`/`c0`)."""
    calls = _run_layer1_sprint_capturing_model_bundle_calls(
        monkeypatch, persist_model_bundles=True
    )
    assert calls == []


def test_run_layer1_sprint_persist_model_bundles_true_com_tf_explicito_chama_as_duas_variantes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _run_layer1_sprint_capturing_model_bundle_calls(
        monkeypatch, tf="30m", persist_model_bundles=True
    )
    assert len(calls) == 2  # camada1 + camada0
    for call in calls:
        assert call["symbol"] == pipeline.SYMBOL
        assert call["resolution_id"] == "30m"  # grade_id: tf_effective quando resolution_id é None
        assert call["purge_ms_effective"] == 42
        assert call["feature_ids"] == features_build.T1_FEATURE_IDS


def test_run_layer1_sprint_persist_model_bundles_true_com_resolution_id_usa_grade_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _run_layer1_sprint_capturing_model_bundle_calls(
        monkeypatch, resolution_id="R1", persist_model_bundles=True
    )
    assert len(calls) == 2
    for call in calls:
        assert call["resolution_id"] == "R1"


# ============================================================================
# run_layer1_sprint(permutation_null_replicas=...) -- ADR-005 §13.13, item 5
# de §13.17. `compute_permutation_null_headline` (o cálculo em si, IO
# incluso) é testada isolada em test_models_pipeline.py -- aqui só o
# ROTEAMENTO: `run_layer1_sprint` chama essa função (com que kwargs) quando
# e só quando `permutation_null_replicas > 0`. Stuba a função inteira (não
# `alpha.run_all_folds`) e para IMEDIATAMENTE quando ela é chamada -- não
# precisa orquestrar backtest/DSR/baselines/decomposition pra chegar lá,
# porque o bloco de item 5 fica DEPOIS de `write_predictions_atomic` no
# corpo real (`alpha_sharpe_headline` depende de `backtest_by_path`, que só
# roda depois das predictions serem gravadas).
# ============================================================================


def test_permutation_null_replicas_default_nunca_chama_o_calculo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default `permutation_null_replicas=0` -- mesma prova por assinatura
    que as outras políticas opt-in do dia (`regularization_basis` etc.):
    nenhum call site/teste existente paga o custo do nulo de permutação."""
    import inspect

    sig = inspect.signature(pipeline.run_layer1_sprint)
    assert sig.parameters["permutation_null_replicas"].default == 0


def test_permutation_null_replicas_k_chama_o_calculo_com_os_kwargs_certos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_compute_permutation_null_headline(*_args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        raise _StopAfterPredictions()

    monkeypatch.setattr(
        pipeline, "compute_permutation_null_headline", _fake_compute_permutation_null_headline
    )

    fake_mf = dataset.ModelingFrame(
        data=pl.DataFrame({"t0": []}), t1_feature_ids=(), regime_labels_present=()
    )
    monkeypatch.setattr(dataset, "build_modeling_frame", lambda *a, **k: fake_mf)
    fake_cpcv_result = SimpleNamespace(
        splits=(), config=SimpleNamespace(n_splits=0, n_backtest_paths=0)
    )
    monkeypatch.setattr(cpcv, "generate_splits", lambda *a, **k: fake_cpcv_result)
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    monkeypatch.setattr(alpha, "run_all_folds", lambda *a, **k: [])
    monkeypatch.setattr(
        alpha, "assemble_predictions_table", lambda fold_results: _empty_predictions_df()
    )
    monkeypatch.setattr(
        pipeline,
        "write_predictions_atomic",
        lambda predictions, model_id, *, dest_dir=None: Path("unused"),
    )

    k = 3  # noqa: magic-number
    with pytest.raises(_StopAfterPredictions):
        pipeline.run_layer1_sprint(permutation_null_replicas=k)

    assert len(calls) == 1
    assert calls[0]["k_replicas"] == k
    assert calls[0]["symbol"] == pipeline.SYMBOL
    assert calls[0]["model_id"] == pipeline.MODEL_ID_CAMADA1


def test_all_symbols_e_all_resolutions_universo_esperado() -> None:
    """`ALL_SYMBOLS`/`ALL_RESOLUTIONS` -- 5 símbolos (BTC + os 4 alts de
    `src.data.download.DEFAULT_SYMBOLS`), 3 resoluções (R1/R2/R3, D-02/
    AG-100/AG-124 -- todas produção)."""
    assert set(pipeline.ALL_SYMBOLS) == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"}
    assert pipeline.ALL_RESOLUTIONS == ("R1", "R2", "R3")
