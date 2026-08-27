"""Testes de `src/validation/leakage.py` — os 14 testes do §11.5 como
runner único. Cada `_test_NN_*` é chamado diretamente (função privada, mas
é exatamente o que `run_all_leakage_tests` orquestra — testar as peças
soltas dá diagnóstico melhor que só testar o agregado) mais os testes de
integração do runner completo contra `labels/v1/labels.parquet` real."""

from __future__ import annotations

import polars as pl
import pytest

from src.features import build as features_build
from src.features.build import T1_FEATURE_IDS
from src.validation import cpcv, leakage
from src.validation._paths import labels_symbol_tf_dir

# Universo de 5 símbolos do projeto (§15, PLANO_MESTRE_PRINCE2.md) — mesmo
# tuple literal usado em tests/unit/test_validation_cpcv.py::_ALL_SYMBOLS
# (convenção do repo: cada módulo/teste declara o próprio tuple em vez de
# importar entre pacotes de camadas diferentes, ver
# src/labels/backfill_multi_symbol.py::ALL_SYMBOLS/src/analysis/
# m6_common_factor_hypothesis.py::ALL_SYMBOLS). Achado F2 (candidato a
# AG-130, auditoria 2026-08-19): antes desta correção,
# test_run_all_leakage_tests_sobre_dataset_real chamava
# cpcv.load_labels_v1() sem argumento, sempre resolvendo symbol="BTCUSDT"
# -- os outros 4 símbolos nunca eram exercitados pelo runner de leakage
# completo de verdade.
_ALL_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def _skip_if_labels_missing(symbol: str = "BTCUSDT", *, resolution_id: str | None = None) -> None:
    """`resolution_id=None` (default) checa a grade LEGADA (`tf=15m`) —
    use `resolution_id="R1"` pra checar a grade de produção real
    (dollar bar, `AG-042`). Achado 2026-08-27 (`project_assurance`, 3ª
    revisão de §14): os 2 testes de vazamento que consomem dado real
    deste arquivo checavam/carregavam a grade de 15m por default —
    `build_modeling_frame()`/`run_all_leakage_tests()` sem argumentos
    caem nesse default, e desde `AG-236` isso falha com
    `ConfigHashMismatchError` contra o `labels.parquet` de 15m real
    (B15, guarda funcionando como deveria — o defeito era nos
    CHAMADORES, não na guarda)."""
    path = labels_symbol_tf_dir(symbol, "v1", resolution_id=resolution_id) / "labels.parquet"
    if not path.exists():
        pytest.skip(f"{path} ausente — rode o Label Engine (Sprint 6) primeiro")


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
# Fase 4 (2026-08-17, migração Parkinson+dollar-bar) -- config/symbol
# repassados a generate_splits nos testes 6/7/12, achado G6 da revisão
# project_assurance
# ============================================================================


def test_teste_06_cpcverror_de_grade_mismatch_vira_fail_nao_crash() -> None:
    """Antes desta correção, `_test_06_contaminacao_label` só capturava
    `AssertionError` -- `generate_splits`/`assert_grade_consistent` levantam
    `CPCVError` (não `AssertionError`) em divergência de grade, escapando
    como exceção não tratada em vez de virar FAIL reportado. `config`
    deliberadamente errado (30m contra espaçamento real de 15m) força esse
    caminho."""
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    config_errada = cpcv.CPCVConfig.from_constants(tf="30m", grade_id="30m")
    result = leakage._test_06_contaminacao_label(labels, config=config_errada, symbol="BTCUSDT")
    assert result.test_id == 6
    assert result.status == leakage.LeakageStatus.FAIL


def test_teste_07_cpcverror_de_grade_mismatch_vira_fail_nao_crash() -> None:
    """Achado de auditoria (audit_engineering, 2026-08-17): `_test_07` tinha
    o MESMO risco de `_test_06` (mesmo `config`/`symbol`, mesma
    `generate_splits`) sem a mesma proteção -- `CPCVError` de divergência
    de grade escapava não tratado. Corrigido junto com `_test_06`/`_test_12`."""
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    config_errada = cpcv.CPCVConfig.from_constants(tf="30m", grade_id="30m")
    result = leakage._test_07_labels_sobrepostos(labels, config=config_errada, symbol="BTCUSDT")
    assert result.test_id == 7
    assert result.status == leakage.LeakageStatus.FAIL


def test_teste_12_cpcverror_de_grade_mismatch_vira_fail_nao_crash() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    config_errada = cpcv.CPCVConfig.from_constants(tf="30m", grade_id="30m")
    result = leakage._test_12_selecao_feature_vazada(labels, config=config_errada, symbol="BTCUSDT")
    assert result.test_id == 12
    assert result.status == leakage.LeakageStatus.FAIL


def test_run_all_leakage_tests_repassa_symbol_a_generate_splits_dos_testes_6_7_12(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Antes desta correção, os testes 6/7/12 chamavam `generate_splits(labels)`
    sem `symbol`/`config` -- sempre grade `"15m"` por baixo, independente do
    que fosse pedido. Spy sobre a função real (não um fake que pula a
    execução) prova que `symbol` chega de fato às 3 chamadas."""
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    # AG-032 item 8 (Fix A) -- run_all_leakage_tests agora chama
    # features_build.compute_max_feature_lookback_ms(tf), que dispara
    # ExpandingFeatureLookbackError contra o T1_FEATURE_IDS real (3
    # features expanding conhecidas) antes de chegar em generate_splits.
    # Este teste não é sobre essa checagem -- bypassa com um valor
    # sintético fixo, mesmo padrão de isolar a dependência que não é o
    # objeto do teste.
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    real_generate_splits = cpcv.generate_splits
    symbols_recebidos: list[str | None] = []

    def _spy_generate_splits(
        labels_arg: pl.DataFrame,
        config: cpcv.CPCVConfig | None = None,
        *,
        symbol: str | None = None,
    ) -> cpcv.CPCVResult:
        symbols_recebidos.append(symbol)
        return real_generate_splits(labels_arg, config=config, symbol=symbol)

    monkeypatch.setattr(cpcv, "generate_splits", _spy_generate_splits)
    leakage.run_all_leakage_tests(labels, feature_ids=T1_FEATURE_IDS, symbol="ETHUSDT")
    assert symbols_recebidos == ["ETHUSDT", "ETHUSDT", "ETHUSDT"]


def test_run_all_leakage_tests_grade_id_prioriza_resolution_id_sobre_tf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resolution_id`, quando setado, vence sobre `tf` na construção do
    `CPCVConfig` dos testes 6/7/12 -- mesmo desenho de UM parâmetro de
    grade (não dois independentes) usado em `build_modeling_frame`/
    `build_regimes` (Fase 4). Monkeypatch de `CPCVConfig.from_constants`
    pra capturar os argumentos e interromper cedo -- não precisa de
    `_calibration.json` real nem de labels com espaçamento dollar-bar."""
    labels = _make_synthetic_labels(60, horizon_bars=1)
    # AG-032 item 8 (Fix A) -- ver nota equivalente no teste anterior:
    # bypassa o fail-fast de features expanding, irrelevante pro que este
    # teste verifica (prioridade resolution_id > tf).
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    captured: dict[str, object] = {}

    class _Stop(Exception):
        pass

    def _spy_from_constants(
        *, tf: str = "15m", grade_id: str | None = None, max_feature_lookback_ms: int = 0
    ) -> cpcv.CPCVConfig:
        captured.update(tf=tf, grade_id=grade_id)
        raise _Stop

    monkeypatch.setattr(cpcv.CPCVConfig, "from_constants", staticmethod(_spy_from_constants))
    with pytest.raises(_Stop):
        leakage.run_all_leakage_tests(
            labels, feature_ids=T1_FEATURE_IDS, tf="30m", resolution_id="R1"
        )
    assert captured == {"tf": "30m", "grade_id": "R1"}


# ============================================================================
# Runner completo — os 14, na ordem, com status coerente
# ============================================================================


def test_run_all_leakage_tests_retorna_14_na_ordem_da_tabela(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # AG-032 item 8 (Fix A) -- bypassa o fail-fast de features expanding
    # (T1_FEATURE_IDS real dispara ExpandingFeatureLookbackError), fora do
    # que este teste verifica (contagem/ordem dos 14 testes).
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    results = leakage.run_all_leakage_tests(labels, feature_ids=T1_FEATURE_IDS)
    assert len(results) == 14
    assert [r.test_id for r in results] == list(range(1, 15))


def test_run_all_leakage_tests_sentinelas_corretos_sobre_sintetico(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # AG-032 item 8 (Fix A) -- mesmo bypass, ver nota acima.
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    results = {
        r.test_id: r for r in leakage.run_all_leakage_tests(labels, feature_ids=T1_FEATURE_IDS)
    }
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


def test_write_leakage_report_atomic_grava_json_sem_deixar_tmp(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    # AG-032 item 8 (Fix A) -- bypassa o fail-fast de features expanding,
    # irrelevante pro que este teste verifica (escrita atômica do report).
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    labels = _make_synthetic_labels(200, horizon_bars=1)
    results = leakage.run_all_leakage_tests(labels, feature_ids=T1_FEATURE_IDS)
    dest = tmp_path / "leakage_report.json"
    path = leakage.write_leakage_report_atomic(results, dest_path=dest)
    assert path == dest
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()

    import orjson

    payload = orjson.loads(path.read_bytes())
    assert payload["schema_version"] == 1
    assert len(payload["tests"]) == 14
    # Achado F5 (candidato a AG-131, auditoria 2026-08-19): report_provenance()
    # (src.core.provenance, mesmo padrão já usado em ~25 módulos de
    # src/analysis/) precisa estar no payload -- generated_at/code_version.
    assert "generated_at" in payload
    assert "code_version" in payload


# ============================================================================
# Runner completo — dataset REAL (labels/v1/labels.parquet, Sprint 6)
# ============================================================================


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _ALL_SYMBOLS)
def test_run_all_leakage_tests_sobre_dataset_real(
    symbol: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roda o relatório completo contra o dataset real de produção — o
    caminho que `python -m src.validation.leakage` de fato exercita. Não
    reforça um número fixo de PASS (o dataset real pode mudar de tamanho
    entre Sprints), só confirma que a orquestração não quebra e que os
    sentinelas de escopo (1/10/11) continuam corretos mesmo sobre dado
    real.

    Parametrizado pros 5 símbolos do universo (achado F2, candidato a
    AG-130, auditoria 2026-08-19) — skip automático (`_skip_if_labels_
    missing`) por símbolo cujo backfill local ainda não existe.

    **Achado 2026-08-22 (verificação incidental, não relacionada à
    migração de path que motivou rodar a suíte completa)**: mesmo gap do
    AG-032 item 8 já corrigido nos testes sintéticos acima e em
    `tests/unit/test_models_pipeline_paths.py` nesta mesma sessão, nunca
    tinha sido propagado pra este teste especificamente (o único que
    roda contra dataset REAL, não sintético) — `run_all_leakage_tests`
    chama `features_build.compute_max_feature_lookback_ms(tf)` internamente,
    que dispara `ExpandingFeatureLookbackError` contra o `T1_FEATURE_IDS`
    real (3 features `expanding` conhecidas) antes de chegar na lógica
    que este teste de fato exercita. Mesmo bypass, mesmo motivo.

    **Corrigido 2026-08-27 (`project_assurance`, 3ª revisão de §14):**
    até esta versão, `_skip_if_labels_missing`/`load_labels_v1`/
    `run_all_leakage_tests` eram chamados sem `resolution_id`, caindo
    todos na grade LEGADA de 15m (`tf="15m"` default) — não é a grade
    de produção real (dollar bar R1, `AG-042`) desde 2026-08-16. O
    relatório de vazamento que este teste valida passava a garantir
    proteção contra a grade errada, silenciosamente."""
    monkeypatch.setattr(
        features_build, "compute_max_feature_lookback_ms", lambda tf, feature_ids, **_: 0
    )
    _skip_if_labels_missing(symbol, resolution_id="R1")
    labels = cpcv.load_labels_v1(symbol=symbol, resolution_id="R1")
    results = {
        r.test_id: r
        for r in leakage.run_all_leakage_tests(
            labels, feature_ids=T1_FEATURE_IDS, symbol=symbol, resolution_id="R1"
        )
    }
    assert len(results) == 14
    assert results[1].status == leakage.LeakageStatus.PENDING_SPRINT_8
    assert results[10].status == leakage.LeakageStatus.NOT_APPLICABLE_V1_1
    assert results[11].status == leakage.LeakageStatus.PASS, results[11].detail
    assert results[6].status == leakage.LeakageStatus.PASS, results[6].detail
    assert results[7].status == leakage.LeakageStatus.PASS, results[7].detail
    assert results[12].status == leakage.LeakageStatus.PASS, results[12].detail


# ============================================================================
# scan_feature_target_correlation — scan estatístico (auditoria Laplace_
# Quant_V16, 2026-08-09), não um dos 14 testes numerados
# ============================================================================


def _synthetic_scan_frame(n: int = 500) -> pl.DataFrame:
    """`clean` não correlaciona com o target (ruído independente); `leaked`
    É o target com ruído mínimo — deve estourar `hard_fail` sempre, em
    qualquer N razoável (rho esperado ~0.99, muito acima de 0.30)."""
    import numpy as np

    rng = np.random.default_rng(42)
    target = rng.normal(size=n)
    clean = rng.normal(size=n)
    leaked = target + rng.normal(scale=0.001, size=n)
    return pl.DataFrame(
        {
            "ret_net": target.astype(np.float64),
            "clean_feature": clean.astype(np.float64),
            "leaked_feature": leaked.astype(np.float64),
        }
    )


def test_scan_detecta_feature_vazada_e_nao_flag_feature_limpa() -> None:
    df = _synthetic_scan_frame()
    entries = leakage.scan_feature_target_correlation(df, ("clean_feature", "leaked_feature"))
    by_name = {e.feature: e for e in entries}

    assert abs(by_name["leaked_feature"].spearman_rho) > 0.9
    assert by_name["leaked_feature"].hard_fail is True
    assert by_name["leaked_feature"].elevated is True

    assert by_name["clean_feature"].hard_fail is False
    assert by_name["clean_feature"].n == 500


def test_scan_threshold_bonferroni_escala_com_n_e_n_features() -> None:
    df = _synthetic_scan_frame(n=200)
    entries_1f = leakage.scan_feature_target_correlation(df, ("clean_feature",))
    entries_2f = leakage.scan_feature_target_correlation(df, ("clean_feature", "leaked_feature"))
    # mais features -> threshold Bonferroni mais alto (sqrt(2) > sqrt(1))
    assert entries_2f[0].bonferroni_threshold > entries_1f[0].bonferroni_threshold
    # hard_fail_threshold é constante fixa, não escala com n_features
    assert entries_2f[0].hard_fail_threshold == entries_1f[0].hard_fail_threshold


def test_scan_amostra_insuficiente_nao_quebra() -> None:
    df = pl.DataFrame({"ret_net": [1.0, 2.0], "f": [1.0, 2.0]})
    entries = leakage.scan_feature_target_correlation(df, ("f",))
    assert len(entries) == 1
    assert entries[0].n == 2
    assert entries[0].elevated is False
    assert entries[0].hard_fail is False


def test_scan_feature_ids_vazio_levanta_valueerror() -> None:
    df = pl.DataFrame({"ret_net": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="feature_ids vazio"):
        leakage.scan_feature_target_correlation(df, ())


def test_scan_target_col_ausente_levanta_valueerror() -> None:
    df = pl.DataFrame({"f": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="target_col"):
        leakage.scan_feature_target_correlation(df, ("f",))


def test_scan_feature_ausente_levanta_valueerror() -> None:
    df = pl.DataFrame({"ret_net": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="ausente em df"):
        leakage.scan_feature_target_correlation(df, ("nao_existe",))


def test_write_correlation_scan_report_atomic_grava_json_sem_deixar_tmp(
    tmp_path: object,
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    df = _synthetic_scan_frame()
    entries = leakage.scan_feature_target_correlation(df, ("clean_feature", "leaked_feature"))
    dest = tmp_path / "feature_leakage_scan_report.json"
    path = leakage.write_correlation_scan_report_atomic(entries, dest_path=dest)
    assert path == dest
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()

    import orjson

    payload = orjson.loads(path.read_bytes())
    assert payload["schema_version"] == 1
    assert len(payload["entries"]) == 2
    # Achado F5 (candidato a AG-131, auditoria 2026-08-19) -- mesma checagem
    # de report_provenance() do teste irmão acima (write_leakage_report_atomic).
    assert "generated_at" in payload
    assert "code_version" in payload


@pytest.mark.slow
@pytest.mark.integration
def test_scan_sobre_dataset_real_nenhuma_feature_t1_hard_falha() -> None:
    """Dataset real, as 10 T1 x `ret_net` (filled trades). Não afirma um
    valor específico de `spearman_rho` (pode mudar se o Label Engine
    mudar de versão) — só que, com o `hard_fail_threshold` calibrado
    nesta auditoria (2x o maior |rho| causal já medido, 0.142), nenhuma
    T1 hoje deveria estourar o gate bloqueante. `elevated` pode ser True
    (é informativo, não falha o teste) — ver docstring do módulo para o
    motivo de `E27f_cost_atr_ratio`/`C07_vol_pctile_expanding`/
    `C06_vol_ratio_12_96`/`D03f_volume_z_expanding` ficarem elevated por
    correlação estrutural com a geometria ATR-escalada do label, não
    vazamento.

    **Corrigido 2026-08-27 (`project_assurance`, 3ª revisão de §14):**
    `build_modeling_frame()` sem argumentos caía na grade LEGADA de 15m
    — desde `AG-236` isso levanta `ConfigHashMismatchError` (B15) contra
    o `labels.parquet` de 15m real, porque os labels persistidos nessa
    grade não batem mais com o `config_hash` de execução atual. Passando
    `resolution_id="R1"` (grade de produção real, dollar bar) o teste
    volta a rodar contra a grade que de fato importa — e, sob
    `resolution_id` setado, `vol_estimator_id` explícito também é
    exigido (`AG-140`, guarda em `build_modeling_frame`): sem `bar_ms`
    fixo sob dollar bar não há estimador default derivável, e os labels
    reais de R1 foram gerados com `parkinson_w20`
    (`run_and_write_labels_dollar_bar_parkinson`), mesmo valor já usado
    em `tests/unit/test_models_dataset.py`."""
    from src.features.build import T1_FEATURE_IDS
    from src.models import dataset as ds

    _skip_if_labels_missing(resolution_id="R1")
    mf = ds.build_modeling_frame(resolution_id="R1", vol_estimator_id="parkinson_w20")
    filled = mf.data.filter(pl.col("barrier_hit") != "NOFILL")
    entries = leakage.scan_feature_target_correlation(filled, T1_FEATURE_IDS)
    hard_failures = [e for e in entries if e.hard_fail]
    assert not hard_failures, (
        f"T1 features estourando hard_fail_threshold (revisar Label Engine ou "
        f"recalibrar constants.yaml::feature_leakage_hard_fail_threshold): "
        f"{[(e.feature, e.spearman_rho) for e in hard_failures]}"
    )
