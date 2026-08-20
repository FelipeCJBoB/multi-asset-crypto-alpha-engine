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

import datetime as dt
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
    oos_start_ms: int = 0,
    oos_end_ms: int = 1000,
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
        symbol=symbol,
        n_bars=1000,
        n_folds=3,
        baseline=baseline,
        candidates=candidates,
        oos_start_ms=oos_start_ms,
        oos_end_ms=oos_end_ms,
    )


def _raw_labels(open_time_ms: list[int], canonical_id: list[int]) -> m4.RawLabels:
    """`close_time_ms == open_time_ms` aqui de propósito (AG-090) -- a
    maioria destes testes não exercita a diferença open/close, só a
    mecânica do join/agregação em si; `test_asof_join_regime_onto_labels_
    usa_close_time_nao_open_time_ag090` (abaixo) é o teste dedicado que
    prova a diferença real."""
    ts = np.array(open_time_ms, dtype=np.int64)
    return m4.RawLabels(
        open_time_ms=ts,
        close_time_ms=ts,
        canonical_id=np.array(canonical_id, dtype=np.int64),
    )


def _ms(year: int, month: int, day: int) -> int:
    return int(dt.datetime(year, month, day, tzinfo=dt.UTC).timestamp() * 1000)


def _synthetic_labels(rows: list[tuple[int, int, str, float]]) -> pl.DataFrame:
    """`rows`: `(t0_ms, side, barrier_hit, atr_at_t0)` -- subconjunto do
    schema real de `load_labels_v1` que `stratum_metrics`/`frac_tp_sl_
    from_labels` de fato consomem. `t0` timezone-aware UTC ms, mesmo
    dtype do `labels.parquet` REAL (`Datetime('ms', 'UTC')`) -- achado
    real (Fase D re-run, 2026-08-18): uma fixture `t0` naive não pegou
    o `polars.exceptions.SchemaError` que só aparecia contra o dtype
    tz-aware real, e o bug só foi descoberto depois de ~2h de fit real
    já ter rodado. Réplica do dtype real aqui pra este tipo de bug ser
    pego em teste, não em produção."""
    return pl.DataFrame(
        {
            "t0": pl.from_epoch(
                pl.Series([r[0] for r in rows], dtype=pl.Int64), time_unit="ms"
            ).dt.replace_time_zone("UTC"),
            "side": pl.Series([r[1] for r in rows], dtype=pl.Int8),
            "barrier_hit": [r[2] for r in rows],
            "atr_at_t0": [r[3] for r in rows],
        }
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
    fake_raw_labels: dict[str, m4.RawLabels] = {
        "bocpd_v1": _raw_labels([0, 10], [0, 1]),
    }
    calls: list[dict[str, object]] = []

    def _stub(
        symbol: str, start: str, end: str, **kwargs: object
    ) -> tuple[m4.SymbolResult, dict[str, m4.RawLabels]]:
        calls.append({"symbol": symbol, "start": start, "end": end, **kwargs})
        return fake_result, fake_raw_labels

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
    assert outcome.raw_labels is fake_raw_labels
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
            "return_raw_labels": True,
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
    assert outcome.raw_labels is None


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
    ) -> tuple[m4.SymbolResult, dict[str, m4.RawLabels]]:
        calls.append((symbol, start, end, resolution_id))
        return _symbol_result(symbol, candidate_omegas={"bocpd_v1": 0.5}), {}

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
    ) -> tuple[m4.SymbolResult, dict[str, m4.RawLabels]]:
        if symbol == "S2":
            raise RuntimeError("IO real falhou")
        return _symbol_result(symbol, candidate_omegas={"bocpd_v1": 0.5}), {}

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
        compute_heterogeneity=False,  # símbolos sintéticos (S1/S2/S3) -- sem labels.parquet real
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
        compute_heterogeneity=False,  # símbolos sintéticos (S1/S2/S3) -- sem labels.parquet real
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
            "close_time": np.arange(n, dtype=np.int64) * 86_400_000 + 86_399_999,
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
            "close_time": np.arange(n, dtype=np.int64) * 86_400_000 + 86_399_999,
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


# ============================================================================
# Q3 (Terceira via) -- agregação sobre RawLabels já coletados por
# _run_one_cell (custo zero em fits, ver docstring de Q3AggregatedResult).
# Núcleo puro (_q3_asset_detail/_q3_window_summary/_aggregate_q3_for_
# classifier) exercitado com CellOutcome sintético, raw_labels conhecidos
# à mão -- mesmo estilo dos testes de agregação de candidato acima.
# ============================================================================

_WIN_BTC_2ASSETS = mcw.CriticalWindow(
    name="WIN_BTC2",
    event="evento com BTC + 2 ativos (teste)",
    start="2022-01-01",
    end="2022-04-01",
    symbols=("BTCUSDT", "S1", "S2"),
    note="janela sintética de teste",
)
_WIN_BTC_ONLY = mcw.CriticalWindow(
    name="WIN_BTC_ONLY",
    event="evento só BTC, tipo LUNA/FTX (teste)",
    start="2022-05-01",
    end="2022-08-01",
    symbols=("BTCUSDT",),
    note="janela sintética de teste",
)
_Q3_TEST_WINDOWS = (_WIN_BTC_2ASSETS, _WIN_BTC_ONLY)
_BTC_RAW = _raw_labels([0, 10, 20, 30], [0, 1, 0, 1])


def test_q3_window_summary_none_quando_janela_so_tem_btc() -> None:
    """LUNA/FTX (só BTCUSDT) não são elegíveis pra Q3 -- não existe ativo
    não-BTC pra comparar contra o rótulo derivado de BTC."""
    cells_by_symbol = {
        "BTCUSDT": mcw.CellOutcome(
            "WIN_BTC_ONLY", "BTCUSDT", "R1", None, raw_labels={"bocpd_v1": _BTC_RAW}
        )
    }
    summary = mcw._q3_window_summary(_WIN_BTC_ONLY, "bocpd_v1", cells_by_symbol)
    assert summary is None


def test_q3_window_summary_ari_1_quando_particao_propria_bate_com_derivada() -> None:
    """S1 tem timestamps DIFERENTES de BTC (dollar-bar real nunca
    compartilha grade) mas o rótulo PRÓPRIO, na região de sobreposição, é
    IDÊNTICO ao derivado de BTC via as-of backward -- propriedade
    matemática de `adjusted_rand_score`: partições idênticas sempre dão
    1.0, não precisa recalcular a fórmula pra saber isso."""
    btc_raw = _raw_labels([0, 10, 20, 30], [0, 1, 0, 1])
    # as-of backward: t=5->btc@0=0 ; t=15->btc@10=1 ; t=25->btc@20=0 -> [0,1,0]
    s1_raw = _raw_labels([5, 15, 25], [0, 1, 0])  # == derivado -> ARI=1.0

    cells_by_symbol = {
        "BTCUSDT": mcw.CellOutcome(
            "WIN_BTC2", "BTCUSDT", "R1", None, raw_labels={"bocpd_v1": btc_raw}
        ),
        "S1": mcw.CellOutcome("WIN_BTC2", "S1", "R1", None, raw_labels={"bocpd_v1": s1_raw}),
    }
    summary = mcw._q3_window_summary(_WIN_BTC_2ASSETS, "bocpd_v1", cells_by_symbol)

    assert summary is not None
    assert summary.n_assets_requested == 2  # S1 e S2 (S2 ausente de cells_by_symbol)
    assert summary.n_assets_ok == 1
    assert len(summary.per_asset) == 1
    assert summary.per_asset[0].symbol == "S1"
    assert summary.per_asset[0].n_bars_compared == 3
    assert summary.per_asset[0].adjusted_rand == pytest.approx(1.0)
    assert summary.adjusted_rand_median == pytest.approx(1.0)


def test_q3_window_summary_ativo_sem_raw_labels_excluido_sem_derrubar_outros() -> None:
    """AG-019 reaplicado a Q3: 1 ativo com célula falhada (`raw_labels=
    None`, mesmo padrão de `error is not None`) não derruba os outros
    ativos da mesma janela."""
    btc_raw = _raw_labels([0, 10, 20, 30], [0, 1, 0, 1])
    s1_raw = _raw_labels([5, 15, 25], [0, 1, 0])
    cells_by_symbol = {
        "BTCUSDT": mcw.CellOutcome(
            "WIN_BTC2", "BTCUSDT", "R1", None, raw_labels={"bocpd_v1": btc_raw}
        ),
        "S1": mcw.CellOutcome("WIN_BTC2", "S1", "R1", None, raw_labels={"bocpd_v1": s1_raw}),
        "S2": mcw.CellOutcome("WIN_BTC2", "S2", "R1", None, "boom", None),  # falhou
    }
    summary = mcw._q3_window_summary(_WIN_BTC_2ASSETS, "bocpd_v1", cells_by_symbol)

    assert summary is not None
    assert summary.n_assets_requested == 2
    assert summary.n_assets_ok == 1  # S2 fora, S1 sobrevive
    assert {d.symbol for d in summary.per_asset} == {"S1"}


def test_q3_window_summary_btc_sem_raw_labels_zero_assets_ok_sem_crash() -> None:
    s1_raw = _raw_labels([5, 15, 25], [0, 1, 0])
    cells_by_symbol = {
        "BTCUSDT": mcw.CellOutcome("WIN_BTC2", "BTCUSDT", "R1", None, "boom", None),  # falhou
        "S1": mcw.CellOutcome("WIN_BTC2", "S1", "R1", None, raw_labels={"bocpd_v1": s1_raw}),
    }
    summary = mcw._q3_window_summary(_WIN_BTC_2ASSETS, "bocpd_v1", cells_by_symbol)

    assert summary is not None
    assert summary.n_assets_ok == 0
    assert summary.per_asset == ()
    assert np.isnan(summary.adjusted_rand_median)


def test_q3_asset_detail_sobreposicao_pequena_da_nan_nao_crash() -> None:
    """`n_bars_compared < m4._Q3_MIN_BARS_COMPARED` -> `NaN` explícito,
    mesma disciplina de `_median_or_nan`/`_anova_or_degenerate` (ausência
    de medição, não erro, não zero inventado)."""
    btc_raw = _raw_labels([1000], [0])
    s1_raw = _raw_labels([1001], [0])  # 1 barra de sobreposição -> n_compared=1 < 2
    detail = mcw._q3_asset_detail(btc_raw, "S1", s1_raw)
    assert detail.n_bars_compared == 1
    assert np.isnan(detail.adjusted_rand)


def test_aggregate_q3_for_classifier_ignora_janela_nao_aplicavel() -> None:
    btc_raw_2assets = _raw_labels([0, 10, 20, 30], [0, 1, 0, 1])
    s1_raw = _raw_labels([5, 15, 25], [0, 1, 0])
    btc_raw_only = _raw_labels([0, 10], [0, 1])

    ok_cells = [
        mcw.CellOutcome(
            "WIN_BTC2", "BTCUSDT", "R1", None, raw_labels={"bocpd_v1": btc_raw_2assets}
        ),
        mcw.CellOutcome("WIN_BTC2", "S1", "R1", None, raw_labels={"bocpd_v1": s1_raw}),
        mcw.CellOutcome(
            "WIN_BTC_ONLY", "BTCUSDT", "R1", None, raw_labels={"bocpd_v1": btc_raw_only}
        ),
    ]
    agg = mcw._aggregate_q3_for_classifier("bocpd_v1", "R1", _Q3_TEST_WINDOWS, ok_cells)

    assert agg.classifier_id == "bocpd_v1"
    assert agg.resolution_id == "R1"
    assert agg.n_windows_requested_total == 2  # as 2 janelas do módulo
    assert agg.n_windows_applicable == 1  # só WIN_BTC2 -- WIN_BTC_ONLY (só BTC) excluída
    assert agg.n_windows_ok == 1
    assert agg.adjusted_rand_median == pytest.approx(1.0)
    assert len(agg.per_window) == 1
    assert agg.per_window[0].window_name == "WIN_BTC2"


def test_aggregate_critical_windows_results_inclui_q3_para_baseline_e_candidatos() -> None:
    """Wiring ponta-a-ponta: `aggregate_critical_windows_results` popula
    `report.q3` -- 1 `Q3AggregatedResult` por `classifier_id` descoberto
    em `symbol_result` (baseline + candidatos), reusando os MESMOS
    `CellOutcome` (raw_labels + symbol_result juntos, exatamente como
    `_run_one_cell` real produz -- não uma célula separada)."""
    btc_raw = {
        "quantile_regime_v1": _raw_labels([0, 10, 20, 30], [0, 1, 0, 1]),
        "bocpd_v1": _raw_labels([0, 10, 20, 30], [1, 0, 1, 0]),
    }
    s1_raw = {
        "quantile_regime_v1": _raw_labels([5, 15, 25], [0, 1, 0]),  # == derivado -> ARI=1.0
        "bocpd_v1": _raw_labels([5, 15, 25], [1, 0, 1]),  # == derivado -> ARI=1.0
    }
    cells = (
        mcw.CellOutcome(
            "WIN_BTC2",
            "BTCUSDT",
            "R1",
            _symbol_result("BTCUSDT", baseline_omega=0.0, candidate_omegas={"bocpd_v1": 0.03}),
            None,
            btc_raw,
        ),
        mcw.CellOutcome(
            "WIN_BTC2",
            "S1",
            "R1",
            _symbol_result("S1", baseline_omega=0.0, candidate_omegas={"bocpd_v1": 0.02}),
            None,
            s1_raw,
        ),
    )
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_Q3_TEST_WINDOWS)

    assert {q.classifier_id for q in report.q3} == {"quantile_regime_v1", "bocpd_v1"}
    baseline_q3 = next(q for q in report.q3 if q.classifier_id == "quantile_regime_v1")
    bocpd_q3 = next(q for q in report.q3 if q.classifier_id == "bocpd_v1")
    assert baseline_q3.adjusted_rand_median == pytest.approx(1.0)
    assert bocpd_q3.adjusted_rand_median == pytest.approx(1.0)
    assert baseline_q3.n_windows_applicable == 1  # WIN_BTC_ONLY não tem célula nenhuma aqui


# ============================================================================
# AG-087 -- transparência de saturação (Jump Model colapsa a 1 estado em
# ~25-29% das células reais, hiperparâmetro calibrado numa única fatia de
# BTC). is_saturated/n_symbols_saturated/n_cells_saturated_total/
# saturation_rate -- NUNCA muda a fórmula de mediana, só torna visível.
# ============================================================================


def test_symbol_detail_marca_is_saturated_quando_switch_rate_zero() -> None:
    saturated = _candidate_result("jump_model_cjm_v1", persistence_switch_rate=0.0)
    healthy = _candidate_result("jump_model_cjm_v1", persistence_switch_rate=0.2)
    assert mcw._symbol_detail_from_candidate("S1", saturated).is_saturated is True
    assert mcw._symbol_detail_from_candidate("S1", healthy).is_saturated is False


def test_aggregate_saturacao_propaga_ate_o_agregado_final() -> None:
    baseline = _candidate_result("quantile_regime_v1", fold_stability_by_construction=True)
    saturated = _candidate_result("jump_model_cjm_v1", persistence_switch_rate=0.0)
    healthy = _candidate_result("jump_model_cjm_v1", persistence_switch_rate=0.2)
    s1 = m4.SymbolResult(
        symbol="S1", n_bars=1000, n_folds=2, baseline=baseline, candidates=(saturated,),
        oos_start_ms=0, oos_end_ms=1000,
    )
    s2 = m4.SymbolResult(
        symbol="S2", n_bars=1000, n_folds=2, baseline=baseline, candidates=(healthy,),
        oos_start_ms=0, oos_end_ms=1000,
    )
    cells = (
        mcw.CellOutcome("WIN_A", "S1", "R1", s1),
        mcw.CellOutcome("WIN_A", "S2", "R1", s2),
    )
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_TEST_WINDOWS)

    jm_agg = report.candidates[0]
    assert jm_agg.classifier_id == "jump_model_cjm_v1"
    assert jm_agg.n_cells_saturated_total == 1
    assert jm_agg.saturation_rate == pytest.approx(0.5)  # 1 de 2 células OK no total

    win_a = next(w for w in jm_agg.per_window if w.window_name == "WIN_A")
    assert win_a.n_symbols_saturated == 1
    s1_detail = next(d for d in win_a.per_symbol if d.symbol == "S1")
    s2_detail = next(d for d in win_a.per_symbol if d.symbol == "S2")
    assert s1_detail.is_saturated is True
    assert s2_detail.is_saturated is False


def test_aggregate_sem_celula_ok_saturation_rate_e_nan_nao_crash() -> None:
    cells = (mcw.CellOutcome("WIN_A", "S1", "R1", None, "erro"),)
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_TEST_WINDOWS)
    assert np.isnan(report.baseline.saturation_rate)
    assert report.baseline.n_cells_saturated_total == 0


# ============================================================================
# AG-084 -- BOCPD sobre o histórico causal COMPLETO do símbolo, não
# fatiado por janela crítica. _bocpd_metrics_for_window/_replace_bocpd_
# candidate (núcleo puro) + _compute_bocpd_full_history (IO mockada, prova
# que start/end usados são SYMBOL_START_DATE/END_DATE, nunca os de uma
# janela específica -- essa é a correção central do bug).
# ============================================================================


def test_bocpd_metrics_for_window_fatia_por_timestamp_nao_por_fold() -> None:
    ts = np.array(
        [_ms(2021, 6, 1), _ms(2022, 1, 5), _ms(2022, 2, 5), _ms(2022, 5, 1)], dtype=np.int64
    )
    full = mcw._BocpdFullHistory(
        open_time_ms=ts,
        close_time_ms=ts,  # AG-090 -- filtro de janela usa close_time_ms
        canonical_id=np.array([0, 0, 1, 1], dtype=np.int64),
        forward_return=np.array([0.01, 0.02, -0.01, 0.03], dtype=np.float64),
        vol_pctile=np.array([0.2, 0.3, 0.7, 0.8], dtype=np.float64),
    )
    result, raw = mcw._bocpd_metrics_for_window(
        _ms(2022, 1, 1), _ms(2022, 4, 1), full, n_canonical_buckets=2
    )

    assert result.classifier_id == "bocpd_v1"
    assert result.fold_stability_by_construction is True
    assert result.n_folds_evaluated == 0
    # só os 2 pontos dentro de [2022-01-01, 2022-04-01) sobrevivem -- os de
    # 2021-06-01 (antes) e 2022-05-01 (depois) ficam de fora.
    assert raw.open_time_ms.tolist() == [_ms(2022, 1, 5), _ms(2022, 2, 5)]
    assert raw.close_time_ms.tolist() == [_ms(2022, 1, 5), _ms(2022, 2, 5)]
    assert raw.canonical_id.tolist() == [0, 1]


def test_bocpd_metrics_for_window_mascara_usa_close_time_nao_open_time_ag090() -> None:
    """Achado de auditoria independente (AG-090, 2026-08-19, M-1): o
    teste acima usa `open_time_ms == close_time_ms`, então nunca provou
    que a máscara de pertencimento à janela (`_bocpd_metrics_for_window`)
    de fato chaveia em `close_time_ms` -- um refator que revertesse a
    máscara pra `open_time_ms` passaria despercebido. Este teste usa 4
    barras com `open`/`close` DIVERGENTES o suficiente pra inverter a
    decisão de pertencimento em 2 delas:

    - barra 0: `open` ANTES da janela (2021-12-30), `close` DENTRO
      (2022-01-02) -- só pertence sob `close_time_ms`.
    - barra 1: `open`/`close` dentro da janela (controle).
    - barra 2: `open` DENTRO da janela (2022-03-31), `close` DEPOIS
      (2022-04-02) -- só pertenceria sob `open_time_ms` (bug antigo).
    - barra 3: `open`/`close` depois da janela (controle, fora dos dois).

    Sob `close_time_ms` (implementação atual): sobrevivem 0 e 1. Sob
    `open_time_ms` (implementação hipotética pré-AG-090): sobreviveriam
    1 e 2 -- conjunto DIFERENTE, prova que a máscara realmente usa
    `close_time_ms`."""
    full = mcw._BocpdFullHistory(
        open_time_ms=np.array(
            [_ms(2021, 12, 30), _ms(2022, 2, 1), _ms(2022, 3, 31), _ms(2022, 5, 1)],
            dtype=np.int64,
        ),
        close_time_ms=np.array(
            [_ms(2022, 1, 2), _ms(2022, 2, 1), _ms(2022, 4, 2), _ms(2022, 5, 1)],
            dtype=np.int64,
        ),
        canonical_id=np.array([0, 1, 1, 0], dtype=np.int64),
        forward_return=np.array([0.01, 0.02, -0.01, 0.03], dtype=np.float64),
        vol_pctile=np.array([0.2, 0.3, 0.7, 0.8], dtype=np.float64),
    )
    _result, raw = mcw._bocpd_metrics_for_window(
        _ms(2022, 1, 1), _ms(2022, 4, 1), full, n_canonical_buckets=2
    )

    assert raw.canonical_id.tolist() == [0, 1]  # barras 0 e 1, nunca 1 e 2
    assert raw.close_time_ms.tolist() == [_ms(2022, 1, 2), _ms(2022, 2, 1)]


def test_bocpd_metrics_for_window_sem_overlap_produz_degenerado_sem_crash() -> None:
    ts = np.array([_ms(2021, 1, 1), _ms(2021, 2, 1)], dtype=np.int64)
    full = mcw._BocpdFullHistory(
        open_time_ms=ts,
        close_time_ms=ts,
        canonical_id=np.array([0, 0], dtype=np.int64),
        forward_return=np.array([0.01, 0.02], dtype=np.float64),
        vol_pctile=np.array([0.2, 0.3], dtype=np.float64),
    )
    result, raw = mcw._bocpd_metrics_for_window(
        _ms(2022, 1, 1), _ms(2022, 4, 1), full, n_canonical_buckets=2
    )
    assert raw.open_time_ms.shape == (0,)
    assert raw.close_time_ms.shape == (0,)
    assert np.isnan(result.separation.omega_squared)


def test_replace_bocpd_candidate_so_troca_bocpd_resto_intocado() -> None:
    baseline = _candidate_result("quantile_regime_v1", fold_stability_by_construction=True)
    old_bocpd = _candidate_result("bocpd_v1", persistence_switch_rate=0.02)
    hmm = _candidate_result("hmm_gaussian_k2_v1")
    symbol_result = m4.SymbolResult(
        symbol="S1", n_bars=1000, n_folds=2, baseline=baseline, candidates=(hmm, old_bocpd),
        oos_start_ms=0, oos_end_ms=1000,
    )
    old_raw = {
        "quantile_regime_v1": _raw_labels([0, 10], [0, 1]),
        "bocpd_v1": _raw_labels([0, 10], [0, 0]),
        "hmm_gaussian_k2_v1": _raw_labels([0, 10], [1, 1]),
    }
    new_bocpd = _candidate_result("bocpd_v1", persistence_switch_rate=0.5)
    new_bocpd_raw = _raw_labels([5, 15], [1, 0])

    new_symbol_result, new_raw = mcw._replace_bocpd_candidate(
        symbol_result, old_raw, new_bocpd, new_bocpd_raw
    )

    assert new_symbol_result.baseline is baseline
    by_id = {c.classifier_id: c for c in new_symbol_result.candidates}
    assert by_id["hmm_gaussian_k2_v1"] is hmm
    assert by_id["bocpd_v1"] is new_bocpd
    assert new_raw is not None
    assert new_raw["bocpd_v1"] is new_bocpd_raw
    assert new_raw["hmm_gaussian_k2_v1"] is old_raw["hmm_gaussian_k2_v1"]


def test_replace_bocpd_candidate_raw_labels_none_permanece_none() -> None:
    baseline = _candidate_result("quantile_regime_v1", fold_stability_by_construction=True)
    old_bocpd = _candidate_result("bocpd_v1")
    symbol_result = m4.SymbolResult(
        symbol="S1", n_bars=1000, n_folds=2, baseline=baseline, candidates=(old_bocpd,),
        oos_start_ms=0, oos_end_ms=1000,
    )
    new_bocpd = _candidate_result("bocpd_v1", persistence_switch_rate=0.9)
    new_bocpd_raw = _raw_labels([5, 15], [1, 0])

    _new_symbol_result, new_raw = mcw._replace_bocpd_candidate(
        symbol_result, None, new_bocpd, new_bocpd_raw
    )
    assert new_raw is None


def test_compute_bocpd_full_history_usa_historico_completo_nao_janela(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-084 -- prova central da correção: `_compute_bocpd_full_history`
    chama `query_dollar_bars`/`build_regimes` com `SYMBOL_START_DATE
    [symbol]`/`END_DATE` (histórico causal completo), NUNCA com datas de
    uma janela crítica específica -- é essa mudança que corrige o reset
    do prior bayesiano do BOCPD a cada janela (AG-084)."""
    n = 150
    open_time_ms = np.arange(n, dtype=np.int64) * 900_000  # grade de 15min, arbitrária
    close_time_ms = open_time_ms + 899_999  # AG-090 -- bars_df precisa de close_time real
    rng = np.random.default_rng(1)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.1, n))
    bars_df = pl.DataFrame(
        {"open_time": open_time_ms, "close_time": close_time_ms, "close": close}
    )
    t0 = pl.from_epoch(pl.Series(open_time_ms, dtype=pl.Int64), time_unit="ms")
    baseline_df = pl.DataFrame({"t0": t0, "vol_pctile": np.linspace(0.0, 1.0, n)})

    calls: list[dict[str, object]] = []

    def _fake_query_dollar_bars(
        symbol: str, start: str, end: str, **_kwargs: object
    ) -> pl.DataFrame:
        calls.append({"fn": "query_dollar_bars", "symbol": symbol, "start": start, "end": end})
        return bars_df

    def _fake_build_regimes(symbol: str, start: str, end: str, **_kwargs: object) -> pl.DataFrame:
        calls.append({"fn": "build_regimes", "symbol": symbol, "start": start, "end": end})
        return baseline_df

    monkeypatch.setattr(lake, "query_dollar_bars", _fake_query_dollar_bars)
    monkeypatch.setattr(mcw, "build_regimes", _fake_build_regimes)
    monkeypatch.setattr(mcw, "load_data_constant", lambda *_a, **_k: 1)

    full = mcw._compute_bocpd_full_history(
        "BTCUSDT", "R1", hazard_lambda=50.0, n_canonical_buckets=2
    )

    assert len(calls) == 2
    for call in calls:
        assert call["symbol"] == "BTCUSDT"
        assert call["start"] == m4.SYMBOL_START_DATE["BTCUSDT"]  # NUNCA start de janela
        assert call["end"] == m4.END_DATE  # NUNCA end de janela
    assert isinstance(full, mcw._BocpdFullHistory)
    assert (
        full.open_time_ms.shape
        == full.close_time_ms.shape
        == full.canonical_id.shape
        == full.forward_return.shape
    )


# ============================================================================
# G-C1-2 revisado -- Cochran's Q/I² de edge_bruto_atr condicionado por
# bucket de regime (decisão do Manager, 2026-08-18, substitui "separação
# a 1 barra" como critério primário -- AG-084/AG-087, PRD_V4_1.md §3.2).
# _asof_join_regime_onto_labels/_heterogeneity_for_symbol_window/
# _aggregate_heterogeneity_for_classifier exercitados com labels
# sintéticos (schema mínimo de load_labels_v1) -- stratum_metrics/
# cochrans_q_heterogeneity JÁ testados em test_analysis_m6_common_factor_
# hypothesis.py, reusados aqui sem reimplementar fórmula nenhuma.
# ============================================================================


def test_asof_join_regime_onto_labels_e_backward_causal() -> None:
    """Mesma prova de causalidade central de Q3 (`_asof_join_btc_labels`),
    reaplicada a label -- cada linha recebe o bucket de regime ATIVO no
    seu `t0`, nunca um bucket com timestamp futuro."""
    labels = _synthetic_labels(
        [(5, 1, "TP", 0.01), (15, 1, "SL", 0.01), (25, 1, "TP", 0.01)]
    )
    regime_raw = _raw_labels([0, 10, 20, 30], [0, 1, 0, 1])
    joined = mcw._asof_join_regime_onto_labels(labels, regime_raw)
    # t0=5ms -> regime@0=0 ; t0=15ms -> regime@10=1 ; t0=25ms -> regime@20=0
    assert joined["regime_bucket"].to_list() == [0, 1, 0]


def test_asof_join_regime_onto_labels_usa_close_time_nao_open_time_ag090() -> None:
    """Regressão de AG-090 -- mesmo raciocínio de
    `test_asof_join_btc_labels_open_close_divergentes_prova_ag090`
    (`test_analysis_m4_regime_comparison.py`), aplicado ao join de
    heterogeneidade: `labels.t0` (`src/labels/triple_barrier.py:913`,
    `t0_arr = bars["close_time"]`) precisa casar com `regime_raw.
    close_time_ms`, nunca `.open_time_ms`.

    Barra de regime A: `open=0, close=100`, bucket=0 -- só CONHECÍVEL a
    partir de `t=100`. Barra B: `open=100, close=110`, bucket=1.

    - label `t0=50` -- ANTES de A fechar -- nenhum bucket deveria
      existir ainda (excluído). Um join por `open_time_ms` bateria com A
      (`50 >= 0`) por engano.
    - label `t0=105` -- DEPOIS de A fechar, ANTES de B fechar -- herda o
      bucket de A (0), nunca o de B. Um join por `open_time_ms` bateria
      com B (`105 >= open=100`) por engano."""
    labels = _synthetic_labels(
        [
            (50, 1, "TP", 0.01),
            (105, 1, "TP", 0.01),
        ]
    )
    regime_raw = m4.RawLabels(
        open_time_ms=np.array([0, 100], dtype=np.int64),
        close_time_ms=np.array([100, 110], dtype=np.int64),
        canonical_id=np.array([0, 1], dtype=np.int64),
    )
    joined = mcw._asof_join_regime_onto_labels(labels, regime_raw)
    assert joined.height == 1  # só o 2o label sobrevive
    assert joined["regime_bucket"].to_list() == [0]  # bucket de A, nunca de B


def test_heterogeneity_for_symbol_window_filtra_periodo_e_agrupa_por_bucket() -> None:
    labels = _synthetic_labels(
        [
            (_ms(2021, 6, 1), 1, "TP", 0.01),  # FORA da janela -- deve ser excluído
            (_ms(2022, 1, 5), 1, "TP", 0.01),
            (_ms(2022, 1, 10), 1, "TP", 0.01),
            (_ms(2022, 1, 15), 1, "SL", 0.01),
            (_ms(2022, 2, 5), 1, "SL", 0.01),
            (_ms(2022, 2, 10), 1, "SL", 0.01),
            (_ms(2022, 2, 15), 1, "TP", 0.01),
        ]
    )
    regime_raw = _raw_labels([_ms(2022, 1, 1), _ms(2022, 2, 1)], [0, 1])

    long_detail, short_detail = mcw._heterogeneity_for_symbol_window(
        "S1",
        _WIN_BTC_2ASSETS,
        regime_raw,
        labels,
        tp_atr_mult=2.0,
        sl_atr_mult=1.0,
        maker_fee=0.0002,
        taker_fee=0.0004,
        n_permutations=200,
        permutation_seed=1,
    )

    assert long_detail.symbol == "S1"
    assert long_detail.n_obs_total == 6  # exclui o rótulo de 2021-06-01
    assert long_detail.n_buckets == 2
    assert not np.isnan(long_detail.i_squared_pct)
    assert not np.isnan(long_detail.pooled_edge_bruto_atr)

    # side=-1 sem nenhuma linha nesta fixture -- degenerado, NaN explícito,
    # sem crash (guard ANTES de chamar m6.cochrans_q_heterogeneity).
    assert short_detail.n_buckets == 0
    assert short_detail.n_obs_total == 0
    assert short_detail.df == -1
    assert np.isnan(short_detail.i_squared_pct)


def test_heterogeneity_for_symbol_window_n_episodes_reflete_intercalacao_cronologica_real() -> (
    None
):
    """Achado de auditoria independente (AG-092, F1, 2026-08-19): o
    teste acima (`n_buckets=2`) usa uma fixture onde os buckets já são
    CONTÍGUOS por tempo (labels de janeiro inteiro = bucket 0, de
    fevereiro inteiro = bucket 1) -- não discriminaria uma reordenação
    silenciosa em algum ponto do pipeline (`_asof_join_regime_onto_
    labels`/`.filter()`), porque bucket-contiguidade e
    tempo-contiguidade coincidem por construção da fixture. Este teste
    usa `regime_raw` com bucket INTERCALADO no tempo (0,1,0,1, 4 trocas)
    -- se a ordenação cronológica fosse violada em algum ponto (ex.
    linhas reagrupadas por valor de bucket em vez de posição temporal),
    `n_episodes` sairia errado (2, não 4)."""
    labels = _synthetic_labels(
        [
            (_ms(2022, 1, 5), 1, "TP", 0.01),  # bucket 0 (regime@2022-01-01)
            (_ms(2022, 1, 15), 1, "SL", 0.01),  # bucket 1 (regime@2022-01-10)
            (_ms(2022, 1, 25), 1, "TP", 0.01),  # bucket 0 (regime@2022-01-20)
            (_ms(2022, 2, 5), 1, "SL", 0.01),  # bucket 1 (regime@2022-01-30)
        ]
    )
    regime_raw = _raw_labels(
        [_ms(2022, 1, 1), _ms(2022, 1, 10), _ms(2022, 1, 20), _ms(2022, 1, 30)],
        [0, 1, 0, 1],
    )

    long_detail, _short_detail = mcw._heterogeneity_for_symbol_window(
        "S1",
        _WIN_BTC_2ASSETS,
        regime_raw,
        labels,
        tp_atr_mult=2.0,
        sl_atr_mult=1.0,
        maker_fee=0.0002,
        taker_fee=0.0004,
        n_permutations=200,
        permutation_seed=1,
    )
    assert long_detail.n_buckets == 2
    assert long_detail.n_episodes == 4  # 4 trocas de bucket na ordem real, nunca 2


def test_heterogeneity_for_symbol_window_n_buckets_1_da_nan_nunca_zero_ou_cem() -> None:
    """Achado de auditoria independente (AG-091, 2026-08-19, F3): a suíte
    já cobria `n_buckets=0` (acima) e `n_buckets=2` (acima), mas nunca o
    cenário REAL que motivou o fix de `cochrans_q_heterogeneity` -- M4
    onde um candidato satura a 1 bucket só (AG-087, Jump Model
    degenerado). `regime_raw` aqui tem um ÚNICO bucket (0) durante toda
    a janela -- todas as labels caem no mesmo grupo, `k=1`/`df=0`."""
    labels = _synthetic_labels(
        [
            (_ms(2022, 1, 5), 1, "TP", 0.01),
            (_ms(2022, 1, 10), 1, "SL", 0.01),
            (_ms(2022, 2, 5), 1, "TP", 0.01),
        ]
    )
    regime_raw = _raw_labels([_ms(2022, 1, 1), _ms(2022, 2, 1)], [0, 0])  # 1 único bucket

    long_detail, _short_detail = mcw._heterogeneity_for_symbol_window(
        "S1",
        _WIN_BTC_2ASSETS,
        regime_raw,
        labels,
        tp_atr_mult=2.0,
        sl_atr_mult=1.0,
        maker_fee=0.0002,
        taker_fee=0.0004,
        n_permutations=200,
        permutation_seed=1,
    )

    assert long_detail.n_buckets == 1
    assert long_detail.df == 0
    assert np.isnan(long_detail.i_squared_pct)  # NUNCA 0.0 nem 100.0
    assert np.isnan(long_detail.q_statistic)
    assert not np.isnan(long_detail.pooled_edge_bruto_atr)  # continua computável
    # AG-092 -- k=1 é degenerado pro teste de permutação também (mesmo
    # raciocínio de k=1 em cochrans_q_heterogeneity, AG-091).
    assert np.isnan(long_detail.p_value_permutation)
    assert long_detail.n_episodes == 1
    assert long_detail.n_permutations_valid == 0
    assert long_detail.n_permutations_requested == 200

    # `_window_heterogeneity_summary` conta n_buckets=1 como "ok" (n_
    # symbols_ok inclui S1), mas `_median_or_nan` exclui a contribuição
    # NaN da mediana -- só o S2 (n_buckets=2, valor real) sobrevive nela.
    s2_detail = mcw.HeterogeneitySymbolDetail(
        symbol="S2", side=1, n_buckets=2, n_obs_total=6,
        pooled_edge_bruto_atr=0.1, q_statistic=2.0, df=1,
        p_value=0.15, i_squared_pct=50.0,
        p_value_permutation=0.2, n_episodes=4,
        n_permutations_requested=200, n_permutations_valid=200,
    )
    summary = mcw._window_heterogeneity_summary(_WIN_BTC_2ASSETS, 1, (long_detail, s2_detail))
    assert summary.n_symbols_ok == 2  # S1 (n_buckets=1) E S2 contam como "ok"
    assert summary.i_squared_pct_median == pytest.approx(50.0)  # só o valor real de S2
    assert summary.p_value_permutation_median == pytest.approx(0.2)  # idem, só S2


def test_aggregate_heterogeneity_for_classifier_placeholder_pra_simbolo_sem_dado() -> None:
    """AG-019 reaplicado: símbolo sem célula/raw_labels/labels nunca é
    omitido de `per_symbol` -- vira `n_buckets=0` explícito."""
    labels_s1 = _synthetic_labels(
        [
            (_ms(2022, 1, 5), 1, "TP", 0.01),
            (_ms(2022, 1, 10), 1, "SL", 0.01),
            (_ms(2022, 2, 5), 1, "SL", 0.01),
            (_ms(2022, 2, 10), 1, "TP", 0.01),
        ]
    )
    regime_raw = _raw_labels([_ms(2022, 1, 1), _ms(2022, 2, 1)], [0, 1])
    ok_cells = [
        mcw.CellOutcome("WIN_BTC2", "S1", "R1", None, raw_labels={"bocpd_v1": regime_raw}),
    ]
    labels_by_symbol = {"S1": labels_s1}

    agg = mcw._aggregate_heterogeneity_for_classifier(
        "bocpd_v1",
        "R1",
        1,
        _Q3_TEST_WINDOWS,
        ok_cells,
        labels_by_symbol,
        tp_atr_mult=2.0,
        sl_atr_mult=1.0,
        maker_fee=0.0002,
        taker_fee=0.0004,
        n_permutations=200,
        permutation_seed=1,
    )

    assert agg.classifier_id == "bocpd_v1"
    assert agg.side == 1
    assert agg.n_windows_requested == 2  # WIN_BTC2 + WIN_BTC_ONLY
    assert agg.n_windows_ok == 1  # só WIN_BTC2 teve algum símbolo OK

    win_summary = next(w for w in agg.per_window if w.window_name == "WIN_BTC2")
    assert win_summary.n_symbols_requested == 3  # BTCUSDT, S1, S2
    assert win_summary.n_symbols_ok == 1  # só S1
    assert {d.symbol for d in win_summary.per_symbol} == {"BTCUSDT", "S1", "S2"}
    btc_detail = next(d for d in win_summary.per_symbol if d.symbol == "BTCUSDT")
    assert btc_detail.n_buckets == 0
    assert np.isnan(btc_detail.i_squared_pct)


def test_aggregate_critical_windows_results_heterogeneity_vazio_por_default() -> None:
    """Contrato anterior a esta mudança preservado -- sem `labels_by_
    symbol`, `heterogeneity` fica vazio; todo teste/chamador anterior a
    G-C1-2 revisado continua funcionando sem alteração."""
    cells = (
        mcw.CellOutcome(
            "WIN_A", "S1", "R1", _symbol_result("S1", candidate_omegas={"bocpd_v1": 0.5})
        ),
    )
    report = mcw.aggregate_critical_windows_results("R1", cells, windows=_TEST_WINDOWS)
    assert report.heterogeneity == ()


def test_aggregate_critical_windows_results_heterogeneity_params_parciais_levanta_valueerror() -> (
    None
):
    cells = (
        mcw.CellOutcome(
            "WIN_A", "S1", "R1", _symbol_result("S1", candidate_omegas={"bocpd_v1": 0.5})
        ),
    )
    with pytest.raises(ValueError, match="TODOS juntos ou NENHUM"):
        mcw.aggregate_critical_windows_results(
            "R1", cells, windows=_TEST_WINDOWS, labels_by_symbol={}, tp_atr_mult=2.0
        )


def test_aggregate_critical_windows_results_com_heterogeneity_side_separado() -> None:
    labels_btc = _synthetic_labels(
        [
            (_ms(2022, 1, 5), 1, "TP", 0.01),
            (_ms(2022, 1, 10), 1, "SL", 0.01),
            (_ms(2022, 2, 5), 1, "SL", 0.01),
            (_ms(2022, 2, 10), 1, "TP", 0.01),
        ]
    )
    regime_raw = {"bocpd_v1": _raw_labels([_ms(2022, 1, 1), _ms(2022, 2, 1)], [0, 1])}
    cells = (
        mcw.CellOutcome(
            "WIN_BTC2",
            "BTCUSDT",
            "R1",
            _symbol_result("BTCUSDT", baseline_omega=0.0, candidate_omegas={"bocpd_v1": 0.02}),
            None,
            regime_raw,
        ),
    )
    report = mcw.aggregate_critical_windows_results(
        "R1",
        cells,
        windows=_Q3_TEST_WINDOWS,
        labels_by_symbol={"BTCUSDT": labels_btc},
        tp_atr_mult=2.0,
        sl_atr_mult=1.0,
        maker_fee=0.0002,
        taker_fee=0.0004,
        n_permutations=200,
        permutation_seed=1,
    )
    # 2 classifier_id (baseline + bocpd_v1) x 2 lados = 4 entradas
    assert len(report.heterogeneity) == 4
    assert {h.side for h in report.heterogeneity} == {1, -1}
    assert {h.classifier_id for h in report.heterogeneity} == {"quantile_regime_v1", "bocpd_v1"}
