"""Testes de `src/analysis/faixa1_6_reconciliation.py` — foco na PLUMBING
mecânica nova (agregação por regime, ponderação RANGE/TREND, partição de
Simpson, serialização), não nas funções estatísticas reusadas
(`spearmanr`, `decompose`, `backtest_lite.*` — já testadas em seus
próprios módulos). Nenhum teste aqui retreina nem chama Bloco 4 (retreino
real, coberto só pela integração skip-if-ausente no fim do arquivo)."""

from __future__ import annotations

import math

import numpy as np
import orjson
import polars as pl
import pytest

from src.analysis import faixa1_6_reconciliation as f16

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")


# ============================================================================
# _spearman_ic / _ic_by_regime — mínimo de observações, NaN-safe
# ============================================================================


def test_spearman_ic_abaixo_do_minimo_vira_nan() -> None:
    x = np.array([1.0, 2.0, 3.0])  # < _MIN_OBS_IC (5)
    y = np.array([1.0, 2.0, 3.0])
    rho, n = f16._spearman_ic(x, y)
    assert math.isnan(rho)
    assert n == 3


def test_spearman_ic_variancia_zero_vira_nan() -> None:
    x = np.array([1.0] * 10)
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    rho, n = f16._spearman_ic(x, y)
    assert math.isnan(rho)
    assert n == 10


def test_spearman_ic_correlacao_perfeita() -> None:
    x = np.arange(10, dtype=np.float64)
    y = np.arange(10, dtype=np.float64)
    rho, n = f16._spearman_ic(x, y)
    assert rho == pytest.approx(1.0)
    assert n == 10


def test_ic_by_regime_particiona_por_regime_e_ignora_outros() -> None:
    df = pl.DataFrame(
        {
            "regime": ["R1"] * 6 + ["R2"] * 6 + ["R5"] * 6,
            f16._E02F_FEATURE: list(range(6)) + list(range(6)) + list(range(6)),
            "ret_net": list(range(6)) + [-v for v in range(6)] + list(range(6)),
        }
    )
    out = f16._ic_by_regime(df)
    assert set(out.keys()) == set(f16._STRUCTURAL_REGIMES)
    assert out["R1"]["rho"] == pytest.approx(1.0)
    assert out["R2"]["rho"] == pytest.approx(-1.0)
    # R3/R4 sem dado -> NaN, n=0 -- R5 não é regime estrutural, nunca aparece
    assert math.isnan(out["R3"]["rho"]) and out["R3"]["n"] == 0
    assert math.isnan(out["R4"]["rho"]) and out["R4"]["n"] == 0


def test_ic_by_regime_frame_vazio_nao_quebra() -> None:
    schema = {"regime": pl.Utf8, f16._E02F_FEATURE: pl.Float64, "ret_net": pl.Float64}
    df = pl.DataFrame(schema=schema)
    out = f16._ic_by_regime(df)
    assert all(math.isnan(v["rho"]) and v["n"] == 0 for v in out.values())


# ============================================================================
# _weighted_range_trend — média ponderada por n dentro de RANGE/TREND
# ============================================================================


def test_weighted_range_trend_pondera_por_n_nao_media_simples() -> None:
    ic_by_regime = {
        "R1": {"rho": 1.0, "n": 90},
        "R2": {"rho": -1.0, "n": 10},
        "R3": {"rho": 0.0, "n": 1},
        "R4": {"rho": 0.0, "n": 1},
    }
    out = f16._weighted_range_trend(ic_by_regime)
    # média simples seria 0.0; ponderada por n favorece R1 (90 vs 10)
    expected_range = (1.0 * 90 + (-1.0) * 10) / 100
    assert out["RANGE"] == pytest.approx(expected_range)
    assert out["RANGE"] != pytest.approx(0.0)


def test_weighted_range_trend_ignora_nan() -> None:
    ic_by_regime = {
        "R1": {"rho": float("nan"), "n": 0},
        "R2": {"rho": 0.5, "n": 10},
        "R3": {"rho": 1.0, "n": 5},
        "R4": {"rho": float("nan"), "n": 0},
    }
    out = f16._weighted_range_trend(ic_by_regime)
    assert out["RANGE"] == pytest.approx(0.5)
    assert out["TREND"] == pytest.approx(1.0)


def test_weighted_range_trend_todos_nan_vira_nan() -> None:
    ic_by_regime = {r: {"rho": float("nan"), "n": 0} for r in f16._STRUCTURAL_REGIMES}
    out = f16._weighted_range_trend(ic_by_regime)
    assert math.isnan(out["RANGE"])
    assert math.isnan(out["TREND"])


# ============================================================================
# _mean_of_folds_by_regime
# ============================================================================


def test_mean_of_folds_by_regime_exclui_nan_da_media() -> None:
    by_fold_ic = {
        0: {
            "R1": {"rho": 0.2, "n": 10},
            "R2": {"rho": 0.4, "n": 10},
            "R3": {"rho": 0.0, "n": 0},
            "R4": {"rho": 0.0, "n": 0},
        },
        1: {
            "R1": {"rho": 0.6, "n": 10},
            "R2": {"rho": float("nan"), "n": 0},
            "R3": {"rho": 0.0, "n": 0},
            "R4": {"rho": 0.0, "n": 0},
        },
    }
    for entry in by_fold_ic.values():
        entry["R3"]["rho"] = float("nan")
        entry["R4"]["rho"] = float("nan")
    out = f16._mean_of_folds_by_regime(by_fold_ic)
    assert out["R1"]["mean_rho"] == pytest.approx(0.4)  # (0.2+0.6)/2
    assert out["R1"]["n_folds_used"] == 2
    assert out["R2"]["mean_rho"] == pytest.approx(0.4)  # só fold 0 é válido
    assert out["R2"]["n_folds_used"] == 1
    assert math.isnan(out["R3"]["mean_rho"])
    assert out["R3"]["n_folds_used"] == 0


# ============================================================================
# _pooled_concat
# ============================================================================


def test_pooled_concat_junta_frames_nao_vazios() -> None:
    a = pl.DataFrame({"x": [1, 2]})
    b = pl.DataFrame({"x": [3]})
    empty = pl.DataFrame(schema={"x": pl.Int64})
    out = f16._pooled_concat({0: a, 1: empty, 2: b})
    assert out.height == 3
    assert sorted(out["x"].to_list()) == [1, 2, 3]


def test_pooled_concat_tudo_vazio_devolve_frame_vazio() -> None:
    out = f16._pooled_concat({0: pl.DataFrame(schema={"x": pl.Int64})})
    assert out.height == 0


# ============================================================================
# _build_oof_population — join semantics (side_hat mixed vs filtrado)
# ============================================================================


def _fake_predictions_bloco1() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": [1, 2, 3, 4],
            "fold_id": [0, 0, 0, 0],
            "side_hat": [1, -1, 0, 1],
            "is_oof": [True, True, True, True],
        }
    ).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))


def _fake_mf_bloco1() -> pl.DataFrame:
    rows = []
    for t0 in (1, 2, 3, 4):
        for side in (1, -1):
            rows.append(
                {
                    "t0": t0,
                    "side": side,
                    "barrier_hit": "TP" if t0 != 4 else "NOFILL",
                    "ret_net": 0.01 * t0 * side,
                    "regime": "R1",
                    f16._E02F_FEATURE: 0.1 * t0,
                }
            )
    return pl.DataFrame(rows).with_columns(pl.col("t0").cast(pl.Int64).cast(_T0_DTYPE))


def test_build_oof_population_mixed_inclui_os_dois_lados() -> None:
    out = f16._build_oof_population(_fake_predictions_bloco1(), _fake_mf_bloco1(), side_filter=None)
    # t0=3 (side_hat=0) descartado; t0=4 (side_hat=1) tem barrier_hit NOFILL, descartado
    assert set(out["t0"].dt.epoch(time_unit="ms").to_list()) == {1, 2}
    assert set(out["side_hat"].to_list()) == {1, -1}


def test_build_oof_population_side_filter_restringe_um_lado() -> None:
    predictions = _fake_predictions_bloco1()
    mf_data = _fake_mf_bloco1()
    out_long = f16._build_oof_population(predictions, mf_data, side_filter=1)
    assert out_long["side_hat"].to_list() == [1]
    out_short = f16._build_oof_population(predictions, mf_data, side_filter=-1)
    assert out_short["side_hat"].to_list() == [-1]


# ============================================================================
# _split_folds_by_median_frac_r2
# ============================================================================


def test_split_folds_by_median_reproduz_inversao_quando_grupos_tem_sinal_oposto() -> None:
    train_long_by_fold = {}
    ic_train_long_by_fold = {}
    for fid in range(6):
        # folds 0-2: baixa fracao de R2 (poucos R2), folds 3-5: alta fracao de R2
        n_r2 = 10 if fid < 3 else 90
        n_r1 = 90 if fid < 3 else 10
        train_long_by_fold[fid] = pl.DataFrame(
            {"regime": ["R1"] * n_r1 + ["R2"] * n_r2}
        )
        rho = 0.5 if fid < 3 else -0.5
        ic_train_long_by_fold[fid] = {
            "R1": {"rho": rho, "n": n_r1},
            "R2": {"rho": rho, "n": n_r2},
            "R3": {"rho": float("nan"), "n": 0},
            "R4": {"rho": float("nan"), "n": 0},
        }
    out = f16._split_folds_by_median_frac_r2(train_long_by_fold, ic_train_long_by_fold)
    assert out["aplicavel"] is True
    assert out["reproduz_inversao"] is True


def test_split_folds_by_median_poucos_folds_nao_aplicavel() -> None:
    train_long_by_fold = {0: pl.DataFrame({"regime": ["R1", "R2"]})}
    ic_train_long_by_fold = {
        0: {r: {"rho": float("nan"), "n": 0} for r in f16._STRUCTURAL_REGIMES}
    }
    out = f16._split_folds_by_median_frac_r2(train_long_by_fold, ic_train_long_by_fold)
    assert out["aplicavel"] is False


# ============================================================================
# report_bloco2_threshold_sanity / report_bloco3_fee_budget_correction —
# não dependem de treino, só leem (ou não) artefatos já em disco
# ============================================================================


def test_report_bloco2_threshold_sanity_sinaliza_bug_confirmado() -> None:
    out = f16.report_bloco2_threshold_sanity()
    assert out["fase_a_metric_valid"] is False
    assert out["fase_b_executada"] is False
    assert out["valores_antes_da_correcao"]["0"] == pytest.approx(1.0)


def test_report_bloco3_fee_budget_correction_referencia_a_correcao() -> None:
    out = f16.report_bloco3_fee_budget_correction()
    assert out["implied_trades_per_year_ponto_central_antes"] == pytest.approx(1325.4192)
    assert len(out["sites_corrigidos"]) == 2
    assert "config/constants.yaml::fee_budget_is_per_side" in out["constante_nova"]


# ============================================================================
# Serialização — nenhum dict-key não-string no payload do Bloco 1 (achado
# real desta rodada: fold_id int quebrava orjson.dumps)
# ============================================================================


def test_reconcile_e02f_ic_payload_serializa_sem_dict_key_nao_string() -> None:
    """`ds.side_subset` exige colunas reais de `build_modeling_frame`
    (T1 completo, warmup) que o fixture mínimo não tem — reconstruir o
    dataset inteiro só pra exercitar a serialização estaria fora de
    escopo (a integração real, mais abaixo, cobre `reconcile_e02f_ic`
    ponta a ponta contra dado real). Aqui verificamos isoladamente o
    formato de saída EXATO que quebrava `orjson.dumps` nesta rodada
    (dict com chave `fold_id` int, não string) — `_ic_by_regime` é a
    mesma função usada por `reconcile_e02f_ic` pra montar esse dict."""
    mf_data = _fake_mf_bloco1()
    ic_by_fold_int_keys = {0: f16._ic_by_regime(mf_data), 1: f16._ic_by_regime(mf_data)}
    payload = {"train_infold_long_ic_by_fold": {str(k): v for k, v in ic_by_fold_int_keys.items()}}
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    reparsed = orjson.loads(blob)
    assert set(reparsed["train_infold_long_ic_by_fold"].keys()) == {"0", "1"}


# ============================================================================
# run_e02f_short_unforced_variant(symbol=..., tf=...) — roteamento de IO
# (AG-012). Mesmo espírito de `tests/unit/test_models_pipeline_paths.py`
# (AG-006): stuba tudo que é caro/precisa de schema real (treino, dataset,
# CPCV, realized/HHI/headlines), captura só os `(model_id, dest_dir)`
# passados a `write_predictions_atomic`/`f15.load_predictions`, e para a
# execução via sentinela assim que os TRÊS pontos de IO já foram
# exercitados — o resto da função (permanence, decomposition, t0_attribution)
# não faz parte do que este teste verifica.
# ============================================================================


class _StopAfterIO(Exception):
    """Sentinela pra interromper `run_e02f_short_unforced_variant` logo após
    os TRÊS pontos de IO relevantes (1 escrita da variante + 2 leituras de
    baseline) terem sido chamados."""


def _empty_predictions_df() -> pl.DataFrame:
    from src.models import alpha

    return pl.DataFrame(
        {c: [] for c in alpha.PREDICTIONS_SCHEMA_COLUMNS},
        schema=dict.fromkeys(alpha.PREDICTIONS_SCHEMA_COLUMNS, pl.Float64),
    )


def _run_variant_capturing_io_calls(
    monkeypatch: pytest.MonkeyPatch, **run_kwargs: str
) -> list[dict[str, object]]:
    from types import SimpleNamespace

    from src.analysis import faixa1_5_prerequisites as f15_mod
    from src.models import alpha, dataset, pipeline
    from src.validation import cpcv

    write_calls: list[dict[str, object]] = []
    read_calls: list[dict[str, object]] = []

    fake_mf = dataset.ModelingFrame(
        data=pl.DataFrame({"t0": []}), t1_feature_ids=(), regime_labels_present=()
    )
    monkeypatch.setattr(dataset, "build_modeling_frame", lambda *a, **k: fake_mf)

    fake_cpcv_result = SimpleNamespace(splits=())
    monkeypatch.setattr(cpcv, "generate_splits", lambda *a, **k: fake_cpcv_result)

    monkeypatch.setattr(
        alpha, "assemble_predictions_table", lambda fold_results: _empty_predictions_df()
    )

    def _fake_write_predictions_atomic(
        predictions: pl.DataFrame, model_id: str, **kw: object
    ) -> None:
        write_calls.append({"model_id": model_id, "dest_dir": kw.get("dest_dir")})

    monkeypatch.setattr(pipeline, "write_predictions_atomic", _fake_write_predictions_atomic)

    # Downstream de cada preds_* (realized/HHI/headlines) não faz parte do
    # que este teste verifica (roteamento de dest_dir) — stubado igual a
    # `write_predictions_atomic`, mesma disciplina.
    monkeypatch.setattr(f15_mod, "build_realized_trades", lambda *a, **k: pl.DataFrame())
    monkeypatch.setattr(f15_mod, "_hhi_by_fold_side", lambda *a, **k: pl.DataFrame())
    monkeypatch.setattr(f15_mod, "stratified_headlines", lambda *a, **k: {})

    def _fake_load_predictions(*, model_id: str, **kw: object) -> pl.DataFrame:
        read_calls.append({"model_id": model_id, "dest_dir": kw.get("dest_dir")})
        if len(read_calls) >= 2:
            raise _StopAfterIO()
        return _empty_predictions_df()

    monkeypatch.setattr(f15_mod, "load_predictions", _fake_load_predictions)

    with pytest.raises(_StopAfterIO):
        f16.run_e02f_short_unforced_variant(**run_kwargs)

    assert len(write_calls) == 1
    assert len(read_calls) == 2
    return [*write_calls, *read_calls]


def test_run_e02f_short_unforced_variant_tf_default_preserva_caminho_legado_plano(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEM passar `tf` (default, o que `run_faixa1_6` e todo chamador/teste
    existente fazem hoje) — a escrita da variante E as duas leituras de
    baseline (Camada 1, Camada 0) usam `dest_dir=None`, bit-exato com o
    caminho legado plano de antes desta mudança (AG-012)."""
    from src.models import pipeline

    calls = _run_variant_capturing_io_calls(monkeypatch)

    assert calls[0] == {
        "model_id": f16.VARIANT_MODEL_ID_E02F_SHORT_UNFORCED,
        "dest_dir": None,
    }
    assert calls[1] == {"model_id": pipeline.MODEL_ID_CAMADA1, "dest_dir": None}
    assert calls[2] == {"model_id": pipeline.MODEL_ID_CAMADA0, "dest_dir": None}


def test_run_e02f_short_unforced_variant_tf_explicito_roteia_escrita_e_as_duas_leituras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tf` explícito propaga até o `dest_dir` das TRÊS operações de IO —
    não só a escrita (achado AG-012: se só a escrita fosse corrigida, a
    variante de um `symbol` não-default compararia contra o baseline
    ERRADO, sempre lido do caminho legado plano)."""
    from src.models._paths import predictions_symbol_tf_dir
    from src.models.pipeline import MODEL_ID_CAMADA0, MODEL_ID_CAMADA1

    calls = _run_variant_capturing_io_calls(monkeypatch, symbol="ETHUSDT", tf="30m")

    expected_variant = predictions_symbol_tf_dir(
        "ETHUSDT", f16.VARIANT_MODEL_ID_E02F_SHORT_UNFORCED, tf="30m"
    )
    expected_camada1 = predictions_symbol_tf_dir("ETHUSDT", MODEL_ID_CAMADA1, tf="30m")
    expected_camada0 = predictions_symbol_tf_dir("ETHUSDT", MODEL_ID_CAMADA0, tf="30m")

    assert calls[0] == {
        "model_id": f16.VARIANT_MODEL_ID_E02F_SHORT_UNFORCED,
        "dest_dir": expected_variant,
    }
    assert calls[1] == {"model_id": MODEL_ID_CAMADA1, "dest_dir": expected_camada1}
    assert calls[2] == {"model_id": MODEL_ID_CAMADA0, "dest_dir": expected_camada0}


def test_run_e02f_short_unforced_variant_tf_invalido_levanta_cedo_sem_trabalho_caro() -> None:
    """`step_ms(tf)` valida ANTES de `build_modeling_frame`/CPCV/treino —
    sem nenhum monkeypatch: se a validação não fosse a primeira linha da
    função, este teste tentaria I/O real (labels/features/regime) e
    falharia por outro motivo, não pelo `tf` inválido."""
    from src.data.resample import UnsupportedTimeframeError

    with pytest.raises(UnsupportedTimeframeError):
        f16.run_e02f_short_unforced_variant(tf="7m")


# ============================================================================
# Integração real — skip se os artefatos de produção não existirem.
# NÃO exercita o Bloco 4 (retreino) -- só as peças que leem artefato real.
# ============================================================================


def _skip_if_missing() -> None:
    from src.models._paths import PREDICTIONS_OUTPUT_DIR
    from src.models.pipeline import MODEL_ID_CAMADA1

    preds_path = PREDICTIONS_OUTPUT_DIR / "alpha" / MODEL_ID_CAMADA1 / "predictions.parquet"
    if not preds_path.exists():
        pytest.skip(f"artefato real ausente: {preds_path}")


@pytest.mark.slow
@pytest.mark.integration
def test_reconcile_e02f_ic_dado_real_reproduz_o_pooled_ja_persistido() -> None:
    """A reconstrução independente do IC pooled (Bloco 1) precisa bater
    EXATAMENTE com o número já persistido em
    `experiments/faixa1_calibration_diagnostic.json` — é o mesmo cálculo
    (mesma junção, mesmo alvo), só reimplementado como DataFrame
    intermediário reusável. Se divergir, ou a reimplementação está errada
    ou o artefato mudou sem re-rodar a Faixa 1 — os dois são bugs."""
    pytest.skip(
        "AG-257 -- este teste junta `predictions/alpha/` (treinadas sob a "
        "grade de RELOGIO 15m) com `build_modeling_frame`. Desde AG-236 o "
        "frame na grade legada falha alto em B15 (comportamento pretendido), "
        "e migrar o frame para R1 quebraria o join por `t0` -- as grades sao "
        "diferentes. NAO ha predictions equivalentes em R1: o retreino sob a "
        "grade canonica ainda nao foi persistido. GATILHO DE REATIVACAO: "
        "quando existir `predictions/alpha/{symbol}/R1/{model_id}/"
        "predictions.parquet`, remover este skip e repontar o teste para elas.",
    )
    _skip_if_missing()
    from src.analysis import faixa1_5_prerequisites as f15
    from src.models import dataset as ds
    from src.models import pipeline
    from src.validation import cpcv

    calib_path = f16.EXPERIMENTS_DIR / "faixa1_calibration_diagnostic.json"
    if not calib_path.exists():
        pytest.skip(f"artefato real ausente: {calib_path}")

    mf = ds.build_modeling_frame()
    cpcv_result = cpcv.generate_splits(mf.data)
    predictions = f15.load_predictions(model_id=pipeline.MODEL_ID_CAMADA1)

    result = f16.reconcile_e02f_ic(predictions, mf.data, cpcv_result.splits)
    check = result["reproduction_check_vs_persisted"]
    assert check is not None
    for regime in f16._STRUCTURAL_REGIMES:
        entry = check[regime]
        if entry["persisted_ic_value"] is None:
            continue
        assert entry["recomputado_oof_mixed_rho"] == pytest.approx(entry["persisted_ic_value"])
