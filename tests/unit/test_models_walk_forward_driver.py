"""Testes de `src.models.walk_forward.run_walk_forward_for_combo` +
`min_trades_for_non_degenerate_fold`/`_aggregate_stats` — ADR-008
Fase 4. `alpha.run_fold` é MOCKADO (mesmo padrão de `test_models_
alpha_hyperparams_wiring.py`/`test_models_backtest_lite.py::
_FakeFoldResult`): construir um `SideModelResult` real por fold exigiria
booster/calibrador completos por retreino de verdade, caro e irrelevante
pro que este módulo testa (orquestração: geração de folds, marcação de
degenerado, agregação) — a geração REAL de splits
(`generate_anchored_walk_forward_splits`/`walk_forward_split_to_cpcv_
split`) e o backtest/score_quality REAIS continuam rodando sobre dado
sintético."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
import pytest

from src.features.build import T1_FEATURE_IDS
from src.models import alpha
from src.models import walk_forward as wf
from src.validation.cpcv import CPCVSplit

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_BASE = datetime(2020, 1, 1, tzinfo=UTC)


# ============================================================================
# min_trades_for_non_degenerate_fold / _aggregate_stats -- núcleo puro
# ============================================================================


def test_min_trades_for_non_degenerate_fold_e_a_constante_de_alpha() -> None:
    """Sem conversão via `target_signal_rate` (correção de desenho, ver
    docstring da função) -- gateia direto na população REAL das
    estatísticas agregadas (`n_filled_trades`), mesma constante que
    `alpha._resolve_tau_on_common_bars` já usa pro mesmo princípio."""
    assert wf.min_trades_for_non_degenerate_fold() == alpha.MIN_OCCURRENCES_ABOVE_TAU


def test_aggregate_stats_conferido_a_mao() -> None:
    out = wf._aggregate_stats([1.0, 2.0, 3.0])  # noqa: magic-number
    assert out["mean"] == pytest.approx(2.0)  # noqa: magic-number
    assert out["median"] == pytest.approx(2.0)  # noqa: magic-number
    assert out["std"] == pytest.approx(1.0)  # noqa: magic-number
    assert out["min"] == pytest.approx(1.0)  # noqa: magic-number
    assert out["max"] == pytest.approx(3.0)  # noqa: magic-number


def test_aggregate_stats_nan_descartado_antes_de_agregar() -> None:
    com_nan = wf._aggregate_stats([1.0, float("nan"), 3.0])  # noqa: magic-number
    sem_nan = wf._aggregate_stats([1.0, 3.0])  # noqa: magic-number
    assert com_nan == sem_nan


def test_aggregate_stats_um_ponto_so_std_nan() -> None:
    out = wf._aggregate_stats([5.0])  # noqa: magic-number
    assert out["mean"] == pytest.approx(5.0)  # noqa: magic-number
    assert np.isnan(out["std"])


def test_aggregate_stats_vazio_tudo_nan() -> None:
    out = wf._aggregate_stats([])
    assert out["n"] == 0.0
    assert np.isnan(out["mean"])


# ============================================================================
# run_walk_forward_for_combo -- orquestração real, run_fold mockado
# ============================================================================


def _synthetic_mf_data(n_days: int = 1095, seed: int = 0) -> pl.DataFrame:  # noqa: magic-number -- 3 anos
    """3 anos de barras diárias, 2 linhas/barra (`side=1`/`side=-1`) --
    ORDEM por bloco de lado (side=1 inteiro, depois side=-1 inteiro),
    mesma não-monotonicidade real documentada em `walk_forward.py`.
    `t1 = t0 + 1h` (horizonte curto -- nunca cruza fronteira de
    trimestre, purge não entra no caminho deste teste, já coberto à
    parte em `test_models_walk_forward.py`)."""
    rng = np.random.default_rng(seed)
    dates = [_BASE + timedelta(days=i) for i in range(n_days)]
    t0 = pl.Series(dates, dtype=_T0_DTYPE)
    t1 = pl.Series([d + timedelta(hours=1) for d in dates], dtype=_T0_DTYPE)
    ret_net = rng.normal(loc=0.001, scale=0.01, size=n_days)  # noqa: magic-number
    zeros = pl.Series(np.zeros(n_days), dtype=pl.Float64)
    ones = pl.Series(np.ones(n_days), dtype=pl.Float64)
    blocks = []
    for side, ret in ((1, ret_net), (-1, -ret_net)):
        cols: dict[str, object] = {
            "t0": t0,
            "t1": t1,
            "side": pl.Series([side] * n_days, dtype=pl.Int8),
            "barrier_hit": pl.Series(["TP"] * n_days, dtype=pl.Utf8),
            "ret_net": pl.Series(ret, dtype=pl.Float64),
            "sample_weight": ones,
            "ret_gross": pl.Series(ret, dtype=pl.Float64),
            "cost_entry_bps": zeros,
            "cost_exit_bps": zeros,
            "funding_bps": zeros,
        }
        # `alpha.unique_test_bars` (precheck do driver ANTES de chamar
        # `alpha.run_fold`) exige TODAS as colunas de T1_FEATURE_IDS
        # (30 desde `AG-421`, 2026-09-01) presentes e não-nulas -- sem
        # isso todo fold seria descartado como "0 barras de teste
        # válidas", mascarando o resto do teste.
        for fid in T1_FEATURE_IDS:
            cols[fid] = pl.Series(rng.normal(size=n_days), dtype=pl.Float64)
        blocks.append(pl.DataFrame(cols))
    return pl.concat(blocks, how="vertical")


def _tiny_fitted_model(n_features: int, *, seed: int) -> lgb.LGBMClassifier:
    """Modelo LightGBM real, mas minúsculo e treinado sobre dado
    sintético descartável -- só pra `shap.TreeExplainer` (ADR-008 Fase
    7) ter um booster de verdade pra explicar. Reusado por TODOS os
    folds fake de uma chamada (não recriado a cada fold) -- o conteúdo
    do modelo é irrelevante pro que este arquivo testa (orquestração),
    só a FORMA (LGBMClassifier fitted, `n_features_` batendo com
    `x_test`) importa."""
    rng = np.random.default_rng(seed)
    n = 20  # noqa: magic-number -- minúsculo de propósito, só pra caber num booster válido
    x = rng.normal(size=(n, n_features))
    y = rng.integers(0, 2, size=n)
    model = lgb.LGBMClassifier(n_estimators=5, max_depth=2, verbosity=-1)  # noqa: magic-number
    model.fit(x, y)
    return model


class _FakeSideModelResult:
    """Duck-type mínimo pro contrato que `run_walk_forward_for_combo` lê
    de `SideModelResult` (`.gain_by_column_raw` da Fase 5, `.model` da
    Fase 7 -- precisa ser um booster REAL pra `shap.TreeExplainer`
    funcionar, não dá pra fingir; `.tau` -- AG-395, persistido por fold
    no artefato -- default arbitrário, testes que precisam de um valor
    específico sobrescrevem depois de construído; `.fit_segment`/
    `.stop_segment`/`.calib_segment` -- P3 do Exhibit VIII ("Caso 0/20"),
    `score_quality.compute_train_val_test_gap` lê os 3, default `None`
    igual ao dataclass real -- gap fica vazio pro fold fake, sem
    AttributeError)."""

    def __init__(
        self,
        gain_by_column_raw: dict[str, float],
        model: lgb.LGBMClassifier,
        *,
        tau: float = 0.5,  # noqa: magic-number -- default de teste, sem significado de produção
        calib_target_single_class: bool = False,
    ) -> None:
        self.gain_by_column_raw = gain_by_column_raw
        self.model = model
        self.tau = tau
        self.calib_target_single_class = calib_target_single_class
        self.fit_segment = None
        self.stop_segment = None
        self.calib_segment = None


class _FakeFoldResult:
    """Duck-type mínimo pro contrato que `run_walk_forward_for_combo`/
    `backtest_lite.backtest_by_path` de fato usam (`.predictions`/
    `.path_id`/`.variant`/`.n_test_bars`/`.long_result.gain_by_column_
    raw`/`.short_result.gain_by_column_raw`) -- mesmo padrão de
    `_FakeFoldResult` em `test_models_backtest_lite.py`."""

    def __init__(
        self,
        predictions: pl.DataFrame,
        *,
        path_id: int,
        variant: str,
        n_test_bars: int,
        long_model: lgb.LGBMClassifier,
        short_model: lgb.LGBMClassifier,
        n_train_long: int = 0,
        n_train_short: int = 0,
    ) -> None:
        self.predictions = predictions
        self.path_id = path_id
        self.variant = variant
        self.n_test_bars = n_test_bars
        self.n_train_long = n_train_long
        self.n_train_short = n_train_short
        self.long_result = _FakeSideModelResult({T1_FEATURE_IDS[0]: 1.0}, long_model)
        self.short_result = _FakeSideModelResult({T1_FEATURE_IDS[1]: 2.0}, short_model)  # noqa: magic-number


def _make_fake_run_fold(
    degenerate_fold_id: int | None = None,
) -> Callable[..., _FakeFoldResult]:
    # Modelos compartilhados por TODOS os folds fake desta chamada --
    # treinados 1 vez só (custo desprezível, mas sem sentido repetir por
    # fold já que o conteúdo é irrelevante pro que este arquivo testa).
    long_model = _tiny_fitted_model(len(T1_FEATURE_IDS), seed=1)
    short_model = _tiny_fitted_model(len(T1_FEATURE_IDS), seed=2)  # noqa: magic-number

    def _fake_run_fold(
        mf_data_arg: pl.DataFrame,
        split: CPCVSplit,
        *,
        variant: str,
        model_id: str,
        seed: int,
        symbol: str,
        resolution_id: str | None = None,
        **_kwargs: Any,
    ) -> _FakeFoldResult:
        test_bars = (
            mf_data_arg[split.test_idx]
            .filter(pl.col("side") == 1)
            .unique(subset=["t0"], keep="first")
            .sort("t0")
        )
        if degenerate_fold_id is not None and split.split_id == degenerate_fold_id:
            test_bars = test_bars.head(1)
        n = test_bars.height
        train_bars = mf_data_arg[split.train_idx]
        n_train_long = train_bars.filter(pl.col("side") == 1).height
        n_train_short = train_bars.filter(pl.col("side") == -1).height
        confidence = pl.Series(np.linspace(0.5, 0.9, n) if n else [], dtype=pl.Float64)  # noqa: magic-number
        predictions = pl.DataFrame(
            {
                "t0": test_bars["t0"],
                "side_hat": pl.Series([1] * n, dtype=pl.Int8),
                "is_oof": pl.Series([True] * n, dtype=pl.Boolean),
                "fold_id": pl.Series([split.split_id] * n, dtype=pl.Int16),
                "confidence": confidence,
                # AG-394 -- `p_long`/`p_short` (score contínuo por lado,
                # sempre presente, mesmo schema real de `alpha.py:2304-
                # 2305`) exigido por `score_quality.compute_score_
                # quality_full_population`. Fake sempre decide `side_hat=
                # 1` (long) -- `p_short` só precisa ser < `p_long` pra
                # manter esse contrato, valor exato irrelevante (este
                # arquivo testa orquestração, não estatística).
                "p_long": confidence,
                "p_short": pl.Series(
                    (1.0 - np.linspace(0.5, 0.9, n)) if n else [], dtype=pl.Float64
                ),
            }
        )
        return _FakeFoldResult(
            predictions,
            path_id=split.path_id,
            variant=variant,
            n_test_bars=n,
            long_model=long_model,
            short_model=short_model,
            n_train_long=n_train_long,
            n_train_short=n_train_short,
        )

    return _fake_run_fold


def _base_kwargs() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "resolution_id": "R2",
        "variant": alpha.VARIANT_CAMADA1,
        "hyper": alpha.LGBMHyperparams.from_constants(),
        "seed": 1,
        "initial_train_years": 2,  # noqa: magic-number -- 3 anos de dado, deixa 1 ano de teste
    }


def test_run_walk_forward_gera_1_fold_por_wf_split(monkeypatch: pytest.MonkeyPatch) -> None:
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    unique_t0_ms = np.unique(mf_data["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64))
    from src.validation.volatility_walkforward import generate_anchored_walk_forward_splits

    expected_splits = generate_anchored_walk_forward_splits(unique_t0_ms, initial_train_years=2)
    assert result.n_folds_total == len(expected_splits)
    assert len(result.fold_results) == len(expected_splits)
    assert result.n_folds_total > 1  # noqa: magic-number -- teste sem sentido com 1 fold só
    # Correção 2026-08-31 (audit_engineering/ADR-008) -- populacao REAL de
    # treino por lado, nao mais descartada: todo fold treinado (nao pulado
    # por 0 barras de teste) tem n_train_long/short > 0, e nao sao mais
    # iguais a n_train_rows_candidatas (que soma os 2 lados PRE-filtro).
    fold_treinado = next(fm for fm in result.fold_results if fm.n_test_bars > 0)
    assert fold_treinado.n_train_long > 0
    assert fold_treinado.n_train_short > 0
    assert fold_treinado.n_train_long + fold_treinado.n_train_short <= (
        fold_treinado.n_train_rows_candidatas
    )


def test_run_walk_forward_pula_run_fold_quando_teste_tem_zero_barras_validas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado real (`BTCUSDT/R2`, execução real da campanha, 2026-08-31):
    um fold cujo bloco de teste inteiro tem uma feature 100% nula faz
    `alpha.run_fold` quebrar (`predict_proba` sobre array vazio) DEPOIS
    de já ter treinado os dois lados. O driver checa `alpha.unique_test_
    bars` ANTES de chamar `run_fold` -- prova aqui que `run_fold` NUNCA é
    chamado pro fold degenerado (0 barras), mas ele continua no
    artefato."""
    mf_data = _synthetic_mf_data()
    primeiro_feature = T1_FEATURE_IDS[0]

    # Fronteira REAL do teste do fold_id=0 -- calculada, não estimada por
    # offset de dias (trimestre civil não cai num múltiplo fixo de dias).
    from src.validation.volatility_walkforward import generate_anchored_walk_forward_splits

    t0_ms_all = mf_data["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    unique_t0_ms_all = np.unique(t0_ms_all)
    fold0_split = generate_anchored_walk_forward_splits(unique_t0_ms_all, initial_train_years=2)[0]
    janela_nula_ini = datetime.fromtimestamp(
        int(unique_t0_ms_all[fold0_split.test_start_idx]) / 1000, tz=UTC
    )
    janela_nula_fim = datetime.fromtimestamp(
        int(unique_t0_ms_all[fold0_split.test_end_idx - 1]) / 1000, tz=UTC
    ) + timedelta(seconds=1)
    mf_data = mf_data.with_columns(
        pl.when((pl.col("t0") >= janela_nula_ini) & (pl.col("t0") < janela_nula_fim))
        .then(None)
        .otherwise(pl.col(primeiro_feature))
        .alias(primeiro_feature)
    )

    chamadas: list[int] = []
    fake = _make_fake_run_fold()

    def _fake_run_fold_rastreado(
        mf_data_arg: pl.DataFrame, split: CPCVSplit, **kwargs: Any
    ) -> _FakeFoldResult:
        chamadas.append(split.split_id)
        return fake(mf_data_arg, split, **kwargs)

    monkeypatch.setattr(alpha, "run_fold", _fake_run_fold_rastreado)

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert fold0.degenerado is True
    assert fold0.n_test_bars == 0
    assert fold0.score_quality_by_side == {}
    # run_fold nunca chamado -- nenhum SideModelResult existe, gain/decile
    # ficam vazios (honesto: não treinou, não tem gain, não é 0.0 inventado).
    assert fold0.decile_profile_by_side == {}
    assert fold0.gain_by_column_by_side == {}
    assert 0 not in chamadas  # run_fold NUNCA chamado pro fold degenerado
    assert len(chamadas) == result.n_folds_total - 1  # todos os outros, sim


def test_run_walk_forward_marca_fold_degenerado_e_exclui_do_agregado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold(degenerate_fold_id=0))

    # fold 0 forçado pra 1 barra de teste -> 1 trade realizado (o fake
    # sinaliza 100% das barras) < min_trades_for_non_degenerate_fold()
    # (10) -- os outros folds (~1 trimestre = ~90 trades) ficam acima.
    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert fold0.degenerado is True
    assert fold0.n_test_bars == 1
    assert fold0.n_filled_trades < wf.min_trades_for_non_degenerate_fold()
    assert result.n_folds_degenerados == 1
    assert result.n_folds_usados == result.n_folds_total - 1
    # o fold degenerado continua PRESENTE no artefato (auditável), só não
    # entra no agregado -- nunca removido silenciosamente.
    assert len(result.fold_results) == result.n_folds_total


def test_run_walk_forward_zero_folds_levanta_valueerror(monkeypatch: pytest.MonkeyPatch) -> None:
    """Série curta demais pra `initial_train_years` -- 0 folds gerados,
    falha alta em vez de devolver um resultado vazio silencioso."""
    mf_data = _synthetic_mf_data(n_days=180)  # noqa: magic-number -- ~6 meses, < 2 anos
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    with pytest.raises(ValueError, match="0 folds gerados"):
        wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())


def test_run_walk_forward_schema_do_agregado_bate_com_adr_008(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    assert set(result.aggregate.keys()) == {"mean", "median", "std", "min", "max"}
    for stat_dict in result.aggregate.values():
        assert set(stat_dict.keys()) == {"sharpe", "edge_bps", "win_rate"}


def test_run_walk_forward_popula_gain_e_decile_por_lado_de_fold_treinado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-008 Fase 5 (stability matrix) -- eixos "feature gain" e
    "decile returns" vêm populados pra todo fold que de fato treinou
    (não-degenerado, ~90 trades por fold aqui, >= 10 -- decile
    computável). `gain_by_column_by_side` reflete exatamente o que
    `_FakeFoldResult` devolveu (`long_result`/`short_result`), sem
    transformação."""
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert fold0.degenerado is False
    assert fold0.gain_by_column_by_side == {
        "long": {T1_FEATURE_IDS[0]: 1.0},
        "short": {T1_FEATURE_IDS[1]: 2.0},  # noqa: magic-number
    }
    # o fake só sinaliza side_hat=1 (long) -- short fica sem trade, mesmo
    # contrato de ausência de `score_quality_by_side`.
    assert "long" in fold0.decile_profile_by_side
    assert "short" not in fold0.decile_profile_by_side
    assert len(fold0.decile_profile_by_side["long"]["buckets"]) == 10  # noqa: magic-number


def test_run_walk_forward_persiste_tau_e_taxa_de_sinal_por_fold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-395 -- `tau_long`/`tau_short` (antes calculados por `alpha.
    run_fold` e descartados aqui) e `signal_rate_realized` (`n_signals/
    n_test_bars`) agora persistidos por fold. `_FakeSideModelResult` não
    tem `.tau` -- monkeypatch adiciona pra este teste especificamente,
    sem exigir mudar o duck-type nos outros testes deste arquivo."""
    mf_data = _synthetic_mf_data()
    fake = _make_fake_run_fold()

    def _fake_com_tau(*args: Any, **kwargs: Any) -> _FakeFoldResult:
        result = fake(*args, **kwargs)
        result.long_result.tau = 0.62  # noqa: magic-number -- valor arbitrário, só testa passthrough
        result.short_result.tau = 0.58  # noqa: magic-number
        return result

    monkeypatch.setattr(alpha, "run_fold", _fake_com_tau)

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert fold0.degenerado is False
    assert fold0.tau_long == pytest.approx(0.62)  # noqa: magic-number
    assert fold0.tau_short == pytest.approx(0.58)  # noqa: magic-number
    assert fold0.signal_rate_realized == pytest.approx(
        fold0.n_signals / fold0.n_test_bars
    )
    assert 0.0 < fold0.signal_rate_realized <= 1.0


def test_run_walk_forward_persiste_calib_degenerado_por_lado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-393 item 3 -- `calib_target_single_class` de `SideModelResult`
    (novo, sinaliza `y_calib` de 1 classe só -- IsotonicRegression.fit
    devolve constante) propagado por lado em `calib_degenerate_by_side`."""
    mf_data = _synthetic_mf_data()
    fake = _make_fake_run_fold()

    def _fake_com_calib_degenerado(*args: Any, **kwargs: Any) -> _FakeFoldResult:
        result = fake(*args, **kwargs)
        result.long_result.calib_target_single_class = True
        result.short_result.calib_target_single_class = False
        return result

    monkeypatch.setattr(alpha, "run_fold", _fake_com_calib_degenerado)

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert fold0.degenerado is False
    assert fold0.calib_degenerate_by_side == {"long": True, "short": False}


def test_run_walk_forward_popula_train_val_test_gap_via_fit_segment_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P3 do Exhibit VIII ("Caso 0/20") -- `WalkForwardResult.
    train_val_test_gap` vem de `score_quality.compute_train_val_test_gap`
    sobre os `alpha.FoldResult` reais já coletados em `pending`, não um
    campo novo desconectado. `fit_segment` real (5 trades, piso `_MIN_
    OBS_FOR_SMALL_SAMPLE_METRICS`) no lado long de todos os folds --
    long precisa aparecer na tupla resultante; short (sem segmento
    nenhum) fica fora, mesmo contrato de `compute_train_val_test_gap`
    testado em `test_models_score_quality.py`."""
    mf_data = _synthetic_mf_data()
    fake = _make_fake_run_fold()
    fit_seg = alpha.InSampleSegmentScores(
        n=5,  # noqa: magic-number -- piso _MIN_OBS_FOR_SMALL_SAMPLE_METRICS
        calibrated_score=np.array([0.1, 0.3, 0.5, 0.7, 0.9]),  # noqa: magic-number
        label=np.array([0, 0, 0, 1, 1]),
        ret_net=np.array([-0.003, -0.002, -0.001, 0.002, 0.004]),  # noqa: magic-number
    )

    def _fake_com_fit_segment(*args: Any, **kwargs: Any) -> _FakeFoldResult:
        result = fake(*args, **kwargs)
        result.long_result.fit_segment = fit_seg
        return result

    monkeypatch.setattr(alpha, "run_fold", _fake_com_fit_segment)

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    sides_presentes = {g["side"] for g in result.train_val_test_gap}
    assert sides_presentes == {"long"}
    gap_long = next(g for g in result.train_val_test_gap if g["side"] == "long")
    assert gap_long["fit"] is not None
    assert gap_long["fit"]["n_trades"] == fit_seg.n * len(result.fold_results)
    assert gap_long["stop"] is None
    assert gap_long["calib"] is None


def test_run_walk_forward_degenerado_by_side_reflete_populacao_real_por_lado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-401 -- o fake só sinaliza `side_hat=1` (long) em 100% das
    barras; short nunca tem trade nenhum. `degenerado` (fold combinado)
    fica `False` (long sozinho já supera o piso), mas `degenerado_by_
    side['short']` precisa ser `True` -- exatamente o cenário que N4
    descreve (lado thin escondido dentro de um fold que passa no
    agregado)."""
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert fold0.degenerado is False
    assert fold0.degenerado_by_side == {"long": False, "short": True}


def test_run_walk_forward_fold_sem_barra_valida_tem_tau_nan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mesmo cenário de `test_run_walk_forward_pula_run_fold_quando_
    teste_tem_zero_barras_validas` -- `run_fold` nunca chamado, nenhum
    `SideModelResult` existe, `tau_long`/`tau_short`/`signal_rate_
    realized` ficam `NaN` (honesto, não `0.0` inventado)."""
    mf_data = _synthetic_mf_data()
    primeiro_feature = T1_FEATURE_IDS[0]
    from src.validation.volatility_walkforward import generate_anchored_walk_forward_splits

    t0_ms_all = mf_data["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    unique_t0_ms_all = np.unique(t0_ms_all)
    fold0_split = generate_anchored_walk_forward_splits(unique_t0_ms_all, initial_train_years=2)[0]
    janela_nula_ini = datetime.fromtimestamp(
        int(unique_t0_ms_all[fold0_split.test_start_idx]) / 1000, tz=UTC
    )
    janela_nula_fim = datetime.fromtimestamp(
        int(unique_t0_ms_all[fold0_split.test_end_idx - 1]) / 1000, tz=UTC
    ) + timedelta(seconds=1)
    mf_data = mf_data.with_columns(
        pl.when((pl.col("t0") >= janela_nula_ini) & (pl.col("t0") < janela_nula_fim))
        .then(None)
        .otherwise(pl.col(primeiro_feature))
        .alias(primeiro_feature)
    )
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert fold0.n_test_bars == 0
    assert np.isnan(fold0.tau_long)
    assert np.isnan(fold0.tau_short)
    assert np.isnan(fold0.signal_rate_realized)
    assert fold0.score_quality_full_population_by_side == {}
    assert fold0.calib_degenerate_by_side == {}
    assert fold0.degenerado_by_side == {}


def test_run_walk_forward_score_quality_full_population_cobre_os_2_lados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-394 -- diferente de `score_quality_by_side` (só "long", já que
    o fake nunca sinaliza `side_hat=-1`), a métrica de população completa
    usa `p_short` sobre TODA barra (não filtra por side_hat) -- os 2
    lados aparecem, mesmo o que o modelo "nunca escolheu"."""
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert set(fold0.score_quality_by_side.keys()) == {"long"}
    assert set(fold0.score_quality_full_population_by_side.keys()) == {"long", "short"}
    # população maior (sem o filtro side_hat==side_value): n_trades da
    # métrica populacional >= n_trades da métrica restrita, no lado que
    # as duas cobrem.
    assert (
        fold0.score_quality_full_population_by_side["long"]["n_trades"]
        >= fold0.score_quality_by_side["long"]["n_trades"]
    )


def test_run_walk_forward_popula_shap_por_lado_de_fold_treinado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-008 Fase 7 -- `shap_mean_abs_by_side` vem populado (`|SHAP|`
    médio sobre o bloco de teste real, via `shap.TreeExplainer` sobre o
    booster de verdade do fake) pra todo fold treinado, "long"/"short"
    SEMPRE presentes (mesmo contrato de `gain_by_column_by_side` --
    treinar não exige ter sinalizado, diferente de `score_quality_by_
    side`)."""
    mf_data = _synthetic_mf_data()
    monkeypatch.setattr(alpha, "run_fold", _make_fake_run_fold())

    result = wf.run_walk_forward_for_combo(mf_data, **_base_kwargs())

    fold0 = next(fm for fm in result.fold_results if fm.fold_id == 0)
    assert set(fold0.shap_mean_abs_by_side.keys()) == {"long", "short"}
    for side in ("long", "short"):
        by_feature = fold0.shap_mean_abs_by_side[side]
        assert set(by_feature.keys()) == set(T1_FEATURE_IDS)
        assert all(v >= 0.0 for v in by_feature.values())  # |SHAP| nunca negativo
