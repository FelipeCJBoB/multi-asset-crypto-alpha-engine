"""Testes de `src/validation/leakage.py` — os 14 testes do §11.5 como
runner único. Cada `_test_NN_*` é chamado diretamente (função privada, mas
é exatamente o que `run_all_leakage_tests` orquestra — testar as peças
soltas dá diagnóstico melhor que só testar o agregado) mais os testes de
integração do runner completo contra `labels/v1/labels.parquet` real."""

from __future__ import annotations

import polars as pl
import pytest

from src.validation import cpcv, leakage
from src.validation._paths import LABELS_OUTPUT_DIR


def _skip_if_labels_missing() -> None:
    if not (LABELS_OUTPUT_DIR / "v1" / "labels.parquet").exists():
        pytest.skip("labels/v1/labels.parquet ausente — rode o Label Engine (Sprint 6) primeiro")


def _make_synthetic_labels(n: int, *, horizon_bars: int = 1) -> pl.DataFrame:
    bar_ms = 900_000
    t0_ms = [i * bar_ms for i in range(n)]
    t1_ms = [t + horizon_bars * bar_ms for t in t0_ms]
    return pl.DataFrame(
        {
            "t0": pl.Series(t0_ms).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "t1": pl.Series(t1_ms).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "side": pl.Series([1] * n, dtype=pl.Int8),
            "sample_weight": pl.Series([1.0] * n, dtype=pl.Float64),
        }
    )


# ============================================================================
# Sentinelas explícitos — testes que dependem de artefato que não existe
# ============================================================================


def test_teste_1_close_futuro_e_pending_sprint_8() -> None:
    result = leakage._test_01_close_futuro()
    assert result.test_id == 1
    assert result.status == leakage.LeakageStatus.PENDING_SPRINT_8


def test_teste_11_calibracao_passa_apos_sprint_8() -> None:
    """Sprint 8 implementou `src/models/alpha.py::fit_side_model` com
    calibração isotônica em sub-split interno do treino (§5.9 passo 9) —
    o teste 11 sai de PENDING_SPRINT_8 (era o caso antes deste sprint) para
    PASS via auditoria estática do código-fonte real."""
    result = leakage._test_11_calibracao_vazada()
    assert result.test_id == 11
    assert result.status == leakage.LeakageStatus.PASS, result.detail


def test_teste_10_meta_e_not_applicable_v1_1_nao_pending() -> None:
    """Distinção deliberada: o Meta NÃO é "pendente de sprint" — está fora
    da V1 inteira (§6.1). Sentinela diferente de PENDING_SPRINT_8."""
    result = leakage._test_10_encadeamento_modelo()
    assert result.test_id == 10
    assert result.status == leakage.LeakageStatus.NOT_APPLICABLE_V1_1
    assert result.status != leakage.LeakageStatus.PENDING_SPRINT_8


# ============================================================================
# Auditorias estáticas — registry, filtros, normalização, paridade
# ============================================================================


def test_teste_2_high_low_futuro_passa_contra_registry_real() -> None:
    result = leakage._test_02_high_low_futuro()
    assert result.status == leakage.LeakageStatus.PASS, result.detail


def test_teste_3_volume_futuro_passa_contra_registry_real() -> None:
    result = leakage._test_03_volume_futuro()
    assert result.status == leakage.LeakageStatus.PASS, result.detail


def test_teste_8_normalizacao_global_passa() -> None:
    result = leakage._test_08_normalizacao_global()
    assert result.status == leakage.LeakageStatus.PASS, result.detail


def test_teste_13_filtros_anacronicos_passa() -> None:
    result = leakage._test_13_filtros_anacronicos()
    assert result.status == leakage.LeakageStatus.PASS, result.detail


def test_teste_14_paridade_reporta_pass_com_nota_de_escopo() -> None:
    result = leakage._test_14_paridade_lote_streaming()
    assert result.status == leakage.LeakageStatus.PASS, result.detail
    assert "features apenas" in result.note


def test_audit_registry_causal_proofs_detecta_id_inexistente() -> None:
    ok, problems, _ = leakage._audit_registry_causal_proofs(("FEATURE_QUE_NAO_EXISTE",))
    assert not ok
    assert any("ausente do registry" in p for p in problems)


def test_verify_causal_proof_reference_detecta_funcao_inexistente() -> None:
    ok, detail = leakage._verify_causal_proof_reference(
        "testado em tests/unit/test_features_groups.py::test_funcao_que_nao_existe_de_verdade"
    )
    assert not ok
    assert "não encontrada" in detail


def test_verify_causal_proof_reference_detecta_arquivo_inexistente() -> None:
    ok, detail = leakage._verify_causal_proof_reference(
        "testado em tests/unit/arquivo_que_nao_existe.py::test_qualquer"
    )
    assert not ok
    assert "não existe" in detail


def test_verify_causal_proof_reference_aceita_referencia_real() -> None:
    ok, detail = leakage._verify_causal_proof_reference(
        "testado em tests/unit/test_features_support.py::test_atr_wilder_causalidade"
    )
    assert ok
    assert detail == "tests/unit/test_features_support.py::test_atr_wilder_causalidade"


# ============================================================================
# Rechecks diretos (código real reexecutado, não só citação de teste)
# ============================================================================


def test_teste_4_funding_futuro_passa() -> None:
    result = leakage._test_04_funding_futuro()
    assert result.status == leakage.LeakageStatus.PASS, result.detail


def test_teste_5_regime_futuro_passa() -> None:
    result = leakage._test_05_regime_futuro()
    assert result.status == leakage.LeakageStatus.PASS, result.detail


def test_teste_9_lookahead_resample_passa() -> None:
    result = leakage._test_09_lookahead_resample()
    assert result.status == leakage.LeakageStatus.PASS, result.detail


# ============================================================================
# Testes que precisam de labels — sintético controlado
# ============================================================================


def test_teste_6_contaminacao_label_passa_com_sintetico() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    result = leakage._test_06_contaminacao_label(labels)
    assert result.status == leakage.LeakageStatus.PASS, result.detail


def test_teste_7_sample_weight_passa_com_sintetico() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    result = leakage._test_07_labels_sobrepostos(labels)
    assert result.status == leakage.LeakageStatus.PASS, result.detail
    assert "PARCIAL" in result.note


def test_teste_7_falha_se_sample_weight_ausente() -> None:
    labels = _make_synthetic_labels(10, horizon_bars=1).drop("sample_weight")
    result = leakage._test_07_labels_sobrepostos(labels)
    assert result.status == leakage.LeakageStatus.FAIL


def test_teste_12_selecao_feature_vazada_passa_com_sintetico() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    result = leakage._test_12_selecao_feature_vazada(labels)
    assert result.status == leakage.LeakageStatus.PASS, result.detail


# ============================================================================
# Runner completo — os 14, na ordem, com status coerente
# ============================================================================


def test_run_all_leakage_tests_retorna_14_na_ordem_da_tabela() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    results = leakage.run_all_leakage_tests(labels)
    assert len(results) == 14
    assert [r.test_id for r in results] == list(range(1, 15))


def test_run_all_leakage_tests_sentinelas_corretos_sobre_sintetico() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    results = {r.test_id: r for r in leakage.run_all_leakage_tests(labels)}
    assert results[1].status == leakage.LeakageStatus.PENDING_SPRINT_8
    assert results[10].status == leakage.LeakageStatus.NOT_APPLICABLE_V1_1
    # teste 11 saiu de PENDING_SPRINT_8 para PASS no Sprint 8 — ver
    # test_teste_11_calibracao_passa_apos_sprint_8 acima.
    # os demais 12 (2,3,4,5,6,7,8,9,11,12,13,14) precisam ter rodado de
    # verdade e reportado PASS contra o dataset sintético/registry real
    ran_for_real = {2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14}
    for tid in ran_for_real:
        assert results[tid].status == leakage.LeakageStatus.PASS, (
            f"teste {tid}: {results[tid].detail}"
        )


def test_leakage_test_result_to_dict_serializa_status_como_string() -> None:
    result = leakage._test_10_encadeamento_modelo()
    d = result.to_dict()
    assert d["status"] == "NOT_APPLICABLE_V1_1"
    assert isinstance(d["status"], str)


def test_write_leakage_report_atomic_grava_json_sem_deixar_tmp(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    labels = _make_synthetic_labels(200, horizon_bars=1)
    results = leakage.run_all_leakage_tests(labels)
    dest = tmp_path / "leakage_report.json"
    path = leakage.write_leakage_report_atomic(results, dest_path=dest)
    assert path == dest
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()

    import orjson

    payload = orjson.loads(path.read_bytes())
    assert payload["schema_version"] == 1
    assert len(payload["tests"]) == 14


# ============================================================================
# Runner completo — dataset REAL (labels/v1/labels.parquet, Sprint 6)
# ============================================================================


@pytest.mark.integration
def test_run_all_leakage_tests_sobre_dataset_real() -> None:
    """Roda o relatório completo contra o dataset real de produção — o
    caminho que `python -m src.validation.leakage` de fato exercita. Não
    reforça um número fixo de PASS (o dataset real pode mudar de tamanho
    entre Sprints), só confirma que a orquestração não quebra e que os
    sentinelas de escopo (1/10/11) continuam corretos mesmo sobre dado
    real."""
    _skip_if_labels_missing()
    labels = cpcv.load_labels_v1()
    results = {r.test_id: r for r in leakage.run_all_leakage_tests(labels)}
    assert len(results) == 14
    assert results[1].status == leakage.LeakageStatus.PENDING_SPRINT_8
    assert results[10].status == leakage.LeakageStatus.NOT_APPLICABLE_V1_1
    assert results[11].status == leakage.LeakageStatus.PASS, results[11].detail
    assert results[6].status == leakage.LeakageStatus.PASS, results[6].detail
    assert results[7].status == leakage.LeakageStatus.PASS, results[7].detail
    assert results[12].status == leakage.LeakageStatus.PASS, results[12].detail
