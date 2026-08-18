"""Testes de `src/analysis/m4_critical_windows.py` -- orquestrador de
janelas históricas críticas × resoluções, Fase B do plano
`wise-exploring-panda.md`. Mesmo estilo de `test_analysis_m4_regime_
comparison.py`: núcleo puro (`aggregate_critical_windows_results`)
exercitado com `CellOutcome`/`m4.SymbolResult`/`m4.CandidateResult`
SINTÉTICOS (sem tocar disco); a camada de IO (`run_critical_windows_
comparison`) é testada via `monkeypatch` de `m4.run_regime_comparison_
for_symbol` (mesma técnica já usada nos testes de `run_q3_common_factor_
regime`); só o teste `integration`/`slow` final toca disco de verdade."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import orjson
import polars as pl
import pytest

from src.analysis import m4_critical_windows as mcw
from src.analysis import m4_regime_comparison as m4
from src.data import lake
from src.data._paths import CAPACITY_DIR
from src.regime import classifier as regime_classifier
from src.validation.regime_utility import ANOVAResult, PersistenceMetrics

# ============================================================================
# Fixtures sintéticas -- CandidateResult/SymbolResult com métricas
# CONTROLADAS (valores conhecidos à mão, pra verificar a mediana de
# medianas sem precisar recalcular a fórmula nos testes).
# ============================================================================


def _candidate_result(
    classifier_id: str,
    *,
    n_states: int = 2,
    separation_omega_squared: float = 0.5,
    orthogonality_omega_squared: float = 0.1,
    persistence_median_duration_bars: float = 10.0,
    persistence_switch_rate: float = 0.2,
    fold_stability_adjusted_rand_mean: float = 0.8,
    fold_stability_adjusted_rand_min: float = 0.7,
    fold_stability_by_construction: bool = False,
    n_oos_obs: int = 100,
    n_folds_evaluated: int = 3,
) -> m4.CandidateResult:
    anova_sep = ANOVAResult(
        f_stat=1.0, omega_squared=separation_omega_squared, p_value=0.01, k_groups=2, n=n_oos_obs
    )
    anova_orth = ANOVAResult(
        f_stat=1.0, omega_squared=orthogonality_omega_squared, p_value=0.01, k_groups=2, n=n_oos_obs
    )
    persistence = PersistenceMetrics(
        median_duration_bars=persistence_median_duration_bars,
        switch_rate=persistence_switch_rate,
        n_segments=5,
    )
    return m4.CandidateResult(
        classifier_id=classifier_id,
        n_states=n_states,
        separation=anova_sep,
        orthogonality=anova_orth,
        persistence=persistence,
        fold_stability_adjusted_rand_mean=fold_stability_adjusted_rand_mean,
        fold_stability_adjusted_rand_min=fold_stability_adjusted_rand_min,
        fold_stability_by_construction=fold_stability_by_construction,
        n_oos_obs=n_oos_obs,
        n_folds_evaluated=n_folds_evaluated,
    )


def _symbol_result(
    symbol: str,
    *,
    baseline_omega: float = 0.3,
    candidate_omegas: dict[str, float],
    n_oos_obs: int = 100,
) -> m4.SymbolResult:
    baseline = _candidate_result(
        "quantile_regime_v1",
        separation_omega_squared=baseline_omega,
        fold_stability_by_construction=True,
        n_oos_obs=n_oos_obs,
    )
    candidates = tuple(
        _candidate_result(cid, separation_omega_squared=omega, n_oos_obs=n_oos_obs)
        for cid, omega in candidate_omegas.items()
    )
    return m4.SymbolResult(
        symbol=symbol, n_bars=1000, n_folds=3, baseline=baseline, candidates=candidates
    )


_WIN_A = mcw.CriticalWindow(
    name="WIN_A",
    event="evento A (teste)",
    start="2022-01-01",
    end="2022-04-01",
    symbols=("S1", "S2"),
    note="janela sintética de teste",
)
_WIN_B = mcw.CriticalWindow(
    name="WIN_B",
    event="evento B (teste)",
    start="2023-01-01",
    end="2023-04-01",
    symbols=("S3",),
    note="janela sintética de teste",
)
_TEST_WINDOWS = (_WIN_A, _WIN_B)


# ============================================================================
# _median_or_nan
# ============================================================================


def test_median_or_nan_valores_conhecidos() -> None:
    assert mcw._median_or_nan([1.0, 2.0, 3.0]) == pytest.approx(2.0)
    assert mcw._median_or_nan([1.0, 3.0]) == pytest.approx(2.0)


def test_median_or_nan_filtra_nan_antes_da_mediana() -> None:
    assert mcw._median_or_nan([1.0, float("nan"), 3.0]) == pytest.approx(2.0)


def test_median_or_nan_lista_vazia_ou_so_nan_da_nan_explicito() -> None:
    assert np.isnan(mcw._median_or_nan([]))
    assert np.isnan(mcw._median_or_nan([float("nan"), float("nan")]))


# ============================================================================
# aggregate_critical_windows_results -- núcleo puro, mediana de medianas
# ============================================================================


def test_aggregate_mediana_de_medianas_nao_e_pooling_direto() -> None:
    """WIN_A tem 2 símbolos (omega 0.2 e 0.4 -> mediana da janela = 0.3),
    WIN_B tem 1 símbolo (omega 0.9 -> mediana da janela = 0.9). Mediana
    ENTRE janelas = median([0.3, 0.9]) = 0.6 -- DIFERENTE de um pooling
    direto de todas as 3 observações (median([0.2, 0.4, 0.9]) = 0.4).
    Prova que a agregação de 2 níveis pesa cada janela igualmente,
    independente de quantos símbolos ela tem (ver docstring do módulo,
    seção "Agregação")."""
    cells = (
        mcw.CellOutcome(
            "WIN_A", "S1", "R1", _symbol_result("S1", candidate_omegas={"bocpd_v1": 0.2})
        ),
        mcw.CellOutcome(
            "WIN_A", "S2", "R1", _symbol_result("S2", candidate_omegas={"bocpd_v1": 0.4})
        ),
        mcw.CellOutcome(
            "WIN_B", "S3", "R1", _symbol_result("S3", candidate_omegas={"bocpd_v1": 0.9})
        ),
    )
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_TEST_WINDOWS)

    assert report.resolution_id == "R1"
    assert len(report.candidates) == 1
    bocpd_agg = report.candidates[0]
    assert bocpd_agg.classifier_id == "bocpd_v1"
    assert bocpd_agg.n_windows_ok == 2
    assert bocpd_agg.n_windows_requested == 2
    assert bocpd_agg.separation_omega_squared_median == pytest.approx(0.6)
    # NÃO deveria bater com o pooling direto -- prova que a agregação é
    # de 2 níveis, não 1 só.
    assert bocpd_agg.separation_omega_squared_median != pytest.approx(0.4)

    # detalhe por janela -- 2 janelas, cada uma com sua própria mediana.
    assert len(bocpd_agg.per_window) == 2
    win_a_summary = next(w for w in bocpd_agg.per_window if w.window_name == "WIN_A")
    win_b_summary = next(w for w in bocpd_agg.per_window if w.window_name == "WIN_B")
    assert win_a_summary.separation_omega_squared == pytest.approx(0.3)
    assert win_a_summary.n_symbols_ok == 2
    assert win_b_summary.separation_omega_squared == pytest.approx(0.9)
    assert win_b_summary.n_symbols_ok == 1

    # detalhe por símbolo -- nunca escondido atrás da mediana da janela.
    assert {d.symbol for d in win_a_summary.per_symbol} == {"S1", "S2"}
    assert {d.symbol for d in win_b_summary.per_symbol} == {"S3"}


def test_aggregate_baseline_agregado_separadamente_dos_candidatos() -> None:
    cells = (
        mcw.CellOutcome(
            "WIN_A",
            "S1",
            "R1",
            _symbol_result("S1", baseline_omega=0.1, candidate_omegas={"bocpd_v1": 0.9}),
        ),
        mcw.CellOutcome(
            "WIN_B",
            "S3",
            "R1",
            _symbol_result("S3", baseline_omega=0.15, candidate_omegas={"bocpd_v1": 0.95}),
        ),
    )
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_TEST_WINDOWS)

    assert report.baseline.classifier_id == "quantile_regime_v1"
    assert report.baseline.separation_omega_squared_median == pytest.approx(
        np.median([0.1, 0.15])
    )
    assert report.candidates[0].separation_omega_squared_median == pytest.approx(
        np.median([0.9, 0.95])
    )


def test_aggregate_ag019_1_celula_falhada_e_1_pulada_nao_derrubam_as_outras() -> None:
    """AG-019: `CellOutcome.error` (exceção real) e `symbol_result=None,
    error=None` (folds insuficientes, `m4.run_regime_comparison_for_
    symbol` devolveu `None`) são casos DIFERENTES -- viram `FailedCell`/
    `SkippedCell` respectivamente, nenhum dos dois participa da mediana,
    e nenhum dos dois derruba a agregação das células OK restantes."""
    cells = (
        mcw.CellOutcome(
            "WIN_A", "S1", "R1", _symbol_result("S1", candidate_omegas={"bocpd_v1": 0.5})
        ),
        mcw.CellOutcome("WIN_A", "S2", "R1", None, "ValueError: boom"),  # falhou
        mcw.CellOutcome("WIN_B", "S3", "R1", None, None),  # pulado -- folds insuficientes
    )
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_TEST_WINDOWS)

    assert len(report.failed_cells) == 1
    assert report.failed_cells[0].window_name == "WIN_A"
    assert report.failed_cells[0].symbol == "S2"
    assert report.failed_cells[0].error == "ValueError: boom"

    assert len(report.skipped_cells) == 1
    assert report.skipped_cells[0].window_name == "WIN_B"
    assert report.skipped_cells[0].symbol == "S3"
    assert report.skipped_cells[0].reason == "folds_insuficientes"

    # a única célula OK (WIN_A/S1) ainda produz um agregado válido --
    # ausência de S2/WIN_B não gera crash, só reduz n_symbols_ok/n_windows_ok.
    bocpd_agg = report.candidates[0]
    assert bocpd_agg.separation_omega_squared_median == pytest.approx(0.5)
    assert bocpd_agg.n_windows_ok == 1  # só WIN_A contribuiu
    assert bocpd_agg.n_windows_requested == 2  # WIN_B ainda listada


def test_aggregate_todas_as_janelas_aparecem_no_detalhe_mesmo_sem_nenhum_simbolo_ok() -> None:
    """`per_window` nunca filtra silenciosamente uma janela sem medição --
    aparece com `n_symbols_ok=0`/métricas `NaN`, não desaparece."""
    cells = (
        mcw.CellOutcome("WIN_A", "S1", "R1", None, "erro"),
        mcw.CellOutcome("WIN_A", "S2", "R1", None, "erro"),
        mcw.CellOutcome(
            "WIN_B", "S3", "R1", _symbol_result("S3", candidate_omegas={"bocpd_v1": 0.7})
        ),
    )
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_TEST_WINDOWS)
    bocpd_agg = report.candidates[0]

    assert len(bocpd_agg.per_window) == 2  # WIN_A E WIN_B, mesmo WIN_A 100% falha
    win_a_summary = next(w for w in bocpd_agg.per_window if w.window_name == "WIN_A")
    assert win_a_summary.n_symbols_ok == 0
    assert np.isnan(win_a_summary.separation_omega_squared)
    assert win_a_summary.per_symbol == ()

    assert bocpd_agg.n_windows_ok == 1
    assert bocpd_agg.separation_omega_squared_median == pytest.approx(0.7)


def test_aggregate_nenhuma_celula_ok_produz_agregado_todo_nan_sem_crash() -> None:
    cells = (
        mcw.CellOutcome("WIN_A", "S1", "R1", None, "erro"),
        mcw.CellOutcome("WIN_B", "S3", "R1", None, None),
    )
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_TEST_WINDOWS)

    assert report.baseline.classifier_id == "quantile_regime_v1"  # fallback, não crash
    assert report.baseline.n_windows_ok == 0
    assert np.isnan(report.baseline.separation_omega_squared_median)
    assert report.candidates == ()  # nenhum classifier_id descoberto -- nenhuma célula OK
    assert len(report.failed_cells) == 1
    assert len(report.skipped_cells) == 1


def test_aggregate_classifier_id_por_lookup_nao_por_indice_posicional() -> None:
    """`_find_candidate` busca por `classifier_id`, não índice -- prova que
    a agregação continua correta mesmo se 2 células tiverem os candidatos
    em ORDEM diferente (não deveria acontecer com hiperparâmetros fixos,
    mas o núcleo puro não presume isso)."""
    s1 = _symbol_result("S1", candidate_omegas={"hmm_gaussian_k2_v1": 0.1, "bocpd_v1": 0.2})
    # S2 com a MESMA composição mas inserida em ordem inversa no dict --
    # como m4.SymbolResult.candidates é uma tupla ordenada por inserção,
    # simula uma ordem diferente de candidatos entre células.
    s2 = _symbol_result("S2", candidate_omegas={"bocpd_v1": 0.4, "hmm_gaussian_k2_v1": 0.3})

    cells = (
        mcw.CellOutcome("WIN_A", "S1", "R1", s1),
        mcw.CellOutcome("WIN_A", "S2", "R1", s2),
    )
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_TEST_WINDOWS)

    by_id = {c.classifier_id: c for c in report.candidates}
    assert set(by_id) == {"hmm_gaussian_k2_v1", "bocpd_v1"}
    assert by_id["hmm_gaussian_k2_v1"].separation_omega_squared_median == pytest.approx(
        np.median([0.1, 0.3])
    )
    assert by_id["bocpd_v1"].separation_omega_squared_median == pytest.approx(
        np.median([0.2, 0.4])
    )


# ============================================================================
# _run_one_cell -- AG-019 na camada de IO (monkeypatch de m4.run_regime_
# comparison_for_symbol, sem tocar disco)
# ============================================================================


def test_run_one_cell_caminho_normal_devolve_symbol_result(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_result = _symbol_result("BTCUSDT", candidate_omegas={"bocpd_v1": 0.5})
    calls: list[dict[str, object]] = []

    def _stub(symbol: str, start: str, end: str, **kwargs: object) -> m4.SymbolResult:
        calls.append({"symbol": symbol, "start": start, "end": end, **kwargs})
        return fake_result

    monkeypatch.setattr(m4, "run_regime_comparison_for_symbol", _stub)

    outcome = mcw._run_one_cell(
        _WIN_A,
        "BTCUSDT",
        "R2",
        initial_train_years=1,
        hmm_states_grid=(2,),
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
        hmm_seed=0,
        jump_seed=0,
    )

    assert outcome.window_name == "WIN_A"
    assert outcome.symbol == "BTCUSDT"
    assert outcome.resolution_id == "R2"
    assert outcome.symbol_result is fake_result
    assert outcome.error is None
    assert calls == [
        {
            "symbol": "BTCUSDT",
            "start": "2022-01-01",
            "end": "2022-04-01",
            "initial_train_years": 1,
            "resolution_id": "R2",
            "hmm_states_grid": (2,),
            "jump_n_states": 2,
            "jump_penalty": 0.002,
            "bocpd_hazard_lambda": 65.0,
            "bocpd_n_canonical_buckets": 3,
            "hmm_seed": 0,
            "jump_seed": 0,
        }
    ]


def test_run_one_cell_none_e_folds_insuficientes_nao_e_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m4, "run_regime_comparison_for_symbol", lambda *a, **k: None)
    outcome = mcw._run_one_cell(
        _WIN_A,
        "BTCUSDT",
        "R1",
        initial_train_years=1,
        hmm_states_grid=(2,),
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
        hmm_seed=0,
        jump_seed=0,
    )
    assert outcome.symbol_result is None
    assert outcome.error is None  # "pulado", não "falhou"


def test_run_one_cell_excecao_vira_cell_outcome_error_nunca_propaga(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _stub_raises(*_args: object, **_kwargs: object) -> m4.SymbolResult:
        raise ValueError("dado corrompido")

    monkeypatch.setattr(m4, "run_regime_comparison_for_symbol", _stub_raises)

    outcome = mcw._run_one_cell(
        _WIN_A,
        "BTCUSDT",
        "R1",
        initial_train_years=1,
        hmm_states_grid=(2,),
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
        hmm_seed=0,
        jump_seed=0,
    )
    assert outcome.symbol_result is None
    assert outcome.error is not None
    assert "dado corrompido" in outcome.error


# ============================================================================
# run_critical_windows_comparison -- caminho sequencial (max_workers=1),
# monkeypatch de m4.run_regime_comparison_for_symbol. Prova causalidade da
# MONTAGEM: cada célula recebe o start/end/resolution_id da PRÓPRIA
# janela, nunca de outra (sem vazamento entre janelas/resoluções).
# ============================================================================


def test_run_critical_windows_comparison_chama_cada_celula_com_a_janela_e_resolucao_corretas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str, str]] = []  # (symbol, start, end, resolution_id)

    def _stub(
        symbol: str, start: str, end: str, *, resolution_id: str, **_kwargs: object
    ) -> m4.SymbolResult:
        calls.append((symbol, start, end, resolution_id))
        return _symbol_result(symbol, candidate_omegas={"bocpd_v1": 0.5})

    monkeypatch.setattr(m4, "run_regime_comparison_for_symbol", _stub)

    report = mcw.run_critical_windows_comparison(
        "R3",
        windows=_TEST_WINDOWS,
        initial_train_years=1,
        hmm_states_grid=(2,),
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
        max_workers=1,
    )

    # 3 células: WIN_A/S1, WIN_A/S2, WIN_B/S3 -- CADA uma com o start/end
    # da PRÓPRIA janela e resolution_id="R3" (nunca misturado).
    assert sorted(calls) == sorted(
        [
            ("S1", "2022-01-01", "2022-04-01", "R3"),
            ("S2", "2022-01-01", "2022-04-01", "R3"),
            ("S3", "2023-01-01", "2023-04-01", "R3"),
        ]
    )
    assert report.resolution_id == "R3"
    assert report.candidates[0].classifier_id == "bocpd_v1"
    assert report.failed_cells == ()
    assert report.skipped_cells == ()


def test_run_critical_windows_comparison_ag019_1_simbolo_falha_outros_seguem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _stub(
        symbol: str, start: str, end: str, *, resolution_id: str, **_kwargs: object
    ) -> m4.SymbolResult:
        if symbol == "S2":
            raise RuntimeError("IO real falhou")
        return _symbol_result(symbol, candidate_omegas={"bocpd_v1": 0.5})

    monkeypatch.setattr(m4, "run_regime_comparison_for_symbol", _stub)

    report = mcw.run_critical_windows_comparison(
        "R1",
        windows=_TEST_WINDOWS,
        initial_train_years=1,
        hmm_states_grid=(2,),
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
        max_workers=1,
    )

    assert len(report.failed_cells) == 1
    assert report.failed_cells[0].symbol == "S2"
    # S1 (mesma janela de S2) e S3 (outra janela) não foram afetados.
    assert report.candidates[0].n_windows_ok == 2


# ============================================================================
# run_and_save_critical_windows_report -- payload/atomic write, IO
# mockada (run_critical_windows_comparison via monkeypatch), sem tocar
# disco real de dollar-bars.
# ============================================================================


def test_run_and_save_critical_windows_report_escreve_json_atomico(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _stub_run_critical_windows_comparison(
        resolution_id: str, **_kwargs: object
    ) -> mcw.CriticalWindowsReport:
        cells = (
            mcw.CellOutcome(
                "WIN_A",
                "S1",
                resolution_id,
                _symbol_result("S1", candidate_omegas={"bocpd_v1": 0.5}),
            ),
        )
        return mcw.aggregate_critical_windows_results(resolution_id, cells, windows=_TEST_WINDOWS)

    monkeypatch.setattr(
        mcw, "run_critical_windows_comparison", _stub_run_critical_windows_comparison
    )

    dest = tmp_path / "m4_critical_windows_report.json"
    result_path = mcw.run_and_save_critical_windows_report(
        resolutions=("R1", "R2"),
        windows=_TEST_WINDOWS,
        dest_path=dest,
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
    )

    assert result_path == dest
    assert dest.exists()
    assert not dest.with_name(dest.name + ".tmp").exists()  # B29 -- tmp removido pelo rename

    payload = orjson.loads(dest.read_bytes())
    assert payload["resolutions_evaluated"] == ["R1", "R2"]
    assert len(payload["by_resolution"]) == 2
    assert payload["by_resolution"][0]["resolution_id"] == "R1"
    assert payload["by_resolution"][1]["resolution_id"] == "R2"
    assert "ag043_barra_vs_tempo_real_caveat" in payload
    assert "luna_ftx_btc_only_caveat" in payload
    assert "target_fold_is_fold1_not_fold0_caveat" in payload
    assert len(payload["windows"]) == 2
    assert payload["partial"] is False  # escrita final, não checkpoint


def test_run_and_save_critical_windows_report_escreve_checkpoint_parcial_por_resolucao(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Achado `project_assurance` 2026-08-18 (HIGH, mesma classe de gap já
    corrigida em `m2_bar_comparison.py`/AG-019 -- checkpoint incremental):
    antes desta correção, uma falha entre a 2ª e a 3ª resolução descartava
    as 2 resoluções já concluídas, porque nada era persistido até a função
    inteira terminar. Prova: depois que a stub de R1 retorna mas ANTES de
    R2 rodar, `dest` já existe em disco com `partial=True` e só R1 em
    `by_resolution` -- não só no final."""
    calls: list[str] = []
    snapshot_before_r2: dict[str, object] = {}

    def _stub_run_critical_windows_comparison(
        resolution_id: str, **_kwargs: object
    ) -> mcw.CriticalWindowsReport:
        if resolution_id == "R2":
            # Checkpoint de R1 precisa já estar no disco ANTES de R2 começar.
            assert dest.exists(), "checkpoint de R1 deveria já ter sido escrito"
            snapshot_before_r2.update(orjson.loads(dest.read_bytes()))
        calls.append(resolution_id)
        cells = (
            mcw.CellOutcome(
                "WIN_A",
                "S1",
                resolution_id,
                _symbol_result("S1", candidate_omegas={"bocpd_v1": 0.5}),
            ),
        )
        return mcw.aggregate_critical_windows_results(resolution_id, cells, windows=_TEST_WINDOWS)

    monkeypatch.setattr(
        mcw, "run_critical_windows_comparison", _stub_run_critical_windows_comparison
    )

    dest = tmp_path / "m4_critical_windows_report.json"
    mcw.run_and_save_critical_windows_report(
        resolutions=("R1", "R2"),
        windows=_TEST_WINDOWS,
        dest_path=dest,
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
    )

    assert calls == ["R1", "R2"]  # sanity -- stub chamada na ordem esperada
    assert snapshot_before_r2["partial"] is True
    assert snapshot_before_r2["resolutions_evaluated"] == ["R1", "R2"]  # pedido completo
    by_resolution = snapshot_before_r2["by_resolution"]
    assert isinstance(by_resolution, list)
    assert len(by_resolution) == 1  # só R1 -- R2 ainda não rodou neste ponto
    assert by_resolution[0]["resolution_id"] == "R1"

    # Estado final -- partial=False, as 2 resoluções presentes.
    final_payload = orjson.loads(dest.read_bytes())
    assert final_payload["partial"] is False
    assert len(final_payload["by_resolution"]) == 2


# ============================================================================
# resolution_id -- interface nova em m4_regime_comparison.run_regime_
# comparison_for_symbol (Fase B). Testado aqui (não no arquivo de teste
# de m4_regime_comparison.py) porque é o consumidor direto desta mudança
# de interface -- mas exercita a função de lá, não deste módulo.
# ============================================================================


def test_run_regime_comparison_for_symbol_resolution_id_seleciona_r2_nos_dois_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resolution_id` precisa selecionar `lake.query_dollar_bars` E
    `build_regimes` JUNTOS, com a MESMA resolução -- nunca um sob R2 e o
    outro sob R1 por engano (isso quebraria `_assert_bars_baseline_
    aligned` silenciosamente adiante, ou pior, mediria regime de uma
    resolução contra retorno/vol_pctile de outra)."""
    n = 30
    bars_df = pl.DataFrame(
        {
            "open_time": np.arange(n, dtype=np.int64) * 86_400_000,
            "close": 100.0 + np.arange(n, dtype=np.float64),
        }
    )
    t0 = (
        pl.from_epoch(pl.Series(bars_df["open_time"]), time_unit="ms")
        .dt.replace_time_zone("UTC")
        .dt.cast_time_unit("ns")
    )
    baseline_df = pl.DataFrame(
        {
            "t0": t0,
            "regime": pl.Series(["R1"] * n).cast(pl.Enum(list(regime_classifier.REGIME_LABELS))),
            "vol_pctile": np.linspace(0.0, 1.0, n),
            "classifier_id": pl.Series(["quantile_regime_v1"] * n),
        }
    )

    query_calls: list[dict[str, object]] = []
    build_calls: list[dict[str, object]] = []

    def _stub_query_dollar_bars(
        symbol: str, start: str, end: str, *, resolution_id: str = "R1", **_kwargs: object
    ) -> pl.DataFrame:
        query_calls.append(
            {"symbol": symbol, "start": start, "end": end, "resolution_id": resolution_id}
        )
        return bars_df

    def _stub_build_regimes(
        symbol: str, start: str, end: str, *, bar_source: str = "time_15m", **_kwargs: object
    ) -> pl.DataFrame:
        build_calls.append(
            {"symbol": symbol, "start": start, "end": end, "bar_source": bar_source}
        )
        return baseline_df

    monkeypatch.setattr(lake, "query_dollar_bars", _stub_query_dollar_bars)
    monkeypatch.setattr(m4, "build_regimes", _stub_build_regimes)

    m4.run_regime_comparison_for_symbol(
        "TESTUSDT",
        "2020-01-01",
        "2020-02-01",
        initial_train_years=1,
        resolution_id="R2",
        hmm_states_grid=(2,),
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
    )

    assert query_calls == [
        {"symbol": "TESTUSDT", "start": "2020-01-01", "end": "2020-02-01", "resolution_id": "R2"}
    ]
    assert build_calls == [
        {
            "symbol": "TESTUSDT",
            "start": "2020-01-01",
            "end": "2020-02-01",
            "bar_source": "dollar_r2",
        }
    ]


def test_run_regime_comparison_for_symbol_resolution_id_default_preserva_r1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem passar `resolution_id`, comportamento idêntico a antes da Fase
    B (`resolution_id="R1"`/`bar_source="dollar_r1"`) -- mesmo protocolo
    de `return_raw_labels` na Fase 4: default nunca muda caller
    existente."""
    n = 30
    bars_df = pl.DataFrame(
        {
            "open_time": np.arange(n, dtype=np.int64) * 86_400_000,
            "close": 100.0 + np.arange(n, dtype=np.float64),
        }
    )
    t0 = (
        pl.from_epoch(pl.Series(bars_df["open_time"]), time_unit="ms")
        .dt.replace_time_zone("UTC")
        .dt.cast_time_unit("ns")
    )
    baseline_df = pl.DataFrame(
        {
            "t0": t0,
            "regime": pl.Series(["R1"] * n).cast(pl.Enum(list(regime_classifier.REGIME_LABELS))),
            "vol_pctile": np.linspace(0.0, 1.0, n),
            "classifier_id": pl.Series(["quantile_regime_v1"] * n),
        }
    )

    query_calls: list[dict[str, object]] = []
    build_calls: list[dict[str, object]] = []

    def _stub_query_dollar_bars(
        symbol: str, start: str, end: str, *, resolution_id: str = "R1", **_kwargs: object
    ) -> pl.DataFrame:
        query_calls.append({"resolution_id": resolution_id})
        return bars_df

    def _stub_build_regimes(
        symbol: str, start: str, end: str, *, bar_source: str = "time_15m", **_kwargs: object
    ) -> pl.DataFrame:
        build_calls.append({"bar_source": bar_source})
        return baseline_df

    monkeypatch.setattr(lake, "query_dollar_bars", _stub_query_dollar_bars)
    monkeypatch.setattr(m4, "build_regimes", _stub_build_regimes)

    m4.run_regime_comparison_for_symbol(
        "TESTUSDT",
        "2020-01-01",
        "2020-02-01",
        initial_train_years=1,
        hmm_states_grid=(2,),
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
    )

    assert query_calls == [{"resolution_id": "R1"}]
    assert build_calls == [{"bar_source": "dollar_r1"}]


# ============================================================================
# CRITICAL_WINDOWS -- constante módulo-level, estrutura básica
# ============================================================================


def test_critical_windows_5_janelas_luna_ftx_btc_only() -> None:
    assert len(mcw.CRITICAL_WINDOWS) == 5
    by_name = {w.name: w for w in mcw.CRITICAL_WINDOWS}
    assert by_name["LUNA"].symbols == ("BTCUSDT",)
    assert by_name["FTX"].symbols == ("BTCUSDT",)
    for name in ("CRYPTO_WINTER", "ETF_HALVING", "RECENTE"):
        assert len(by_name[name].symbols) == 5
        assert "BTCUSDT" in by_name[name].symbols


def test_resolutions_r1_r2_r3() -> None:
    assert mcw.RESOLUTIONS == ("R1", "R2", "R3")


# ============================================================================
# Integration/slow -- 1 janela pequena, BTCUSDT, R1, IO real. Não cobre
# as 18 combinações completas (isso é Fase D, execução real, fora de
# escopo desta suíte).
# ============================================================================

_SMALL_WINDOW = mcw.CriticalWindow(
    name="SMOKE",
    event="smoke test (não é uma das 5 janelas críticas reais)",
    start="2020-01-01",
    end="2021-01-08",
    symbols=("BTCUSDT",),
    note="mesma janela do smoke test de m4_regime_comparison.py -- já provada rápida/suficiente",
)


def _skip_if_no_backfill() -> None:
    path = CAPACITY_DIR / "dollar_bars_r1" / "BTCUSDT" / "2020-01-01.parquet"
    if not path.exists():
        pytest.skip(f"backfill local de dollar_bars_r1/BTCUSDT ausente: {path}")


@pytest.mark.integration
@pytest.mark.slow
def test_run_critical_windows_comparison_1_janela_btcusdt_r1_sobre_dado_real() -> None:
    _skip_if_no_backfill()
    report = mcw.run_critical_windows_comparison(
        "R1",
        windows=(_SMALL_WINDOW,),
        initial_train_years=1,
        hmm_states_grid=(2,),
        jump_n_states=2,
        jump_penalty=0.002,
        bocpd_hazard_lambda=65.0,
        bocpd_n_canonical_buckets=3,
        max_workers=1,
    )

    assert report.resolution_id == "R1"
    assert report.failed_cells == ()
    assert report.baseline.n_windows_requested == 1
    # baseline/BOCPD são "por construção" -- sempre rodam sem refit, não
    # deveriam falhar mesmo em dado ruidoso; HMM/Jump Model PODEM degenerar
    # (n_windows_ok pode ser 0) sem que isso seja um bug do orquestrador.
    assert report.baseline.n_windows_ok == 1
    classifier_ids = {c.classifier_id for c in report.candidates}
    assert "bocpd_v1" in classifier_ids
