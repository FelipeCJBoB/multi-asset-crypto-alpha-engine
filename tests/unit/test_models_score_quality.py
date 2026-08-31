"""Testes de `src.models.score_quality` — qualidade do SCORE final do
Alpha (classificação formal + IC/Rank IC/IC IR/Q10-Q1), ADR-008 Fase 1.
Mesmo padrão de fixture de `test_analysis_attribution.py`
(`confidence_deciles_by_side`) — join por lado, `t0` cresce com posição
na lista, `confidence`/`ret_net`/`fold_id` controlados diretamente."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from src.models import alpha
from src.models import score_quality as sq

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_BASE = datetime(2024, 1, 1, tzinfo=UTC)


def _t0s(n: int) -> list[datetime]:
    return [_BASE + timedelta(days=i) for i in range(n)]


def _predictions_df(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=_T0_DTYPE),
            "side_hat": pl.Series([r["side_hat"] for r in rows], dtype=pl.Int8),
            "is_oof": pl.Series([r.get("is_oof", True) for r in rows], dtype=pl.Boolean),
            "fold_id": pl.Series([r.get("fold_id", 0) for r in rows], dtype=pl.Int16),
            "confidence": pl.Series([r["confidence"] for r in rows], dtype=pl.Float64),
        }
    )


def _labels_df(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=_T0_DTYPE),
            "side": pl.Series([r["side"] for r in rows], dtype=pl.Int8),
            "barrier_hit": pl.Series([r.get("barrier_hit", "TP") for r in rows], dtype=pl.Utf8),
            "ret_net": pl.Series([r["ret_net"] for r in rows], dtype=pl.Float64),
        }
    )


def test_compute_score_quality_separacao_perfeita_auc_1_e_ic_positivo() -> None:
    """5 trades long (piso `_MIN_OBS_FOR_SMALL_SAMPLE_METRICS`=5,
    correção 2026-08-31): confidence crescente, ret_net crescente (3
    losses baixa confiança, 2 wins alta confiança) -- separação
    perfeita, AUC=1,0 exato, IC de Spearman = 1,0 exato (mesma ordem)."""
    t0s = _t0s(5)
    confidence = [0.1, 0.3, 0.5, 0.7, 0.9]
    ret_net = [-0.003, -0.002, -0.001, 0.002, 0.004]
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": confidence[i], "fold_id": 0}
        for i in range(5)
    ]
    label_rows = [{"t0": t0s[i], "side": 1, "ret_net": ret_net[i]} for i in range(5)]
    predictions = _predictions_df(pred_rows)
    labels = _labels_df(label_rows)

    out = sq.compute_score_quality(predictions, labels)

    assert len(out) == 1
    r = out[0]
    assert r.side == "long"
    assert r.n_trades == 5
    assert r.roc_auc == pytest.approx(1.0)
    assert r.spearman_ic_pooled == pytest.approx(1.0)
    assert np.isnan(r.q10_minus_q1_bps)  # n=5 < 10 decis -- indefinido, nao zero
    assert r.pearson_ic == pytest.approx(np.corrcoef(confidence, ret_net)[0, 1])
    # cross-check direto contra sklearn sobre o MESMO subconjunto -- prova
    # que a seleção de dado (join/filtro) bate, não reimplementa a fórmula
    y_true = np.array([0, 0, 0, 1, 1])
    y_score = np.array(confidence)
    assert r.roc_auc == pytest.approx(float(roc_auc_score(y_true, y_score)))
    assert r.log_loss == pytest.approx(float(log_loss(y_true, y_score, labels=[0, 1])))
    assert r.brier_score == pytest.approx(float(brier_score_loss(y_true, y_score)))


def test_compute_score_quality_amostra_menor_que_5_todas_metricas_nan() -> None:
    """Correção 2026-08-31 (achado real de auditoria, `AG-391`): com
    `n<5` trades, classificação (AUC/PR-AUC/LogLoss/Brier) e correlação
    (Pearson/Spearman) ficam `NaN`, mesmo sob separação perfeita --
    n=2-4 produz correlação/AUC degenerada (sempre ±1,0/0,0/1,0), não
    informativa. Mesmo piso de `src.models.monotonic._MIN_OBS_PER_ENV`."""
    for n in (2, 3, 4):
        t0s = _t0s(n)
        confidence = [0.1 + 0.2 * i for i in range(n)]
        ret_net = [-0.002 + 0.001 * i for i in range(n)]
        pred_rows = [
            {"t0": t0s[i], "side_hat": 1, "confidence": confidence[i], "fold_id": 0}
            for i in range(n)
        ]
        label_rows = [{"t0": t0s[i], "side": 1, "ret_net": ret_net[i]} for i in range(n)]
        out = sq.compute_score_quality(_predictions_df(pred_rows), _labels_df(label_rows))

        assert len(out) == 1, f"n={n}"
        r = out[0]
        assert r.n_trades == n
        assert np.isnan(r.roc_auc), f"n={n}"
        assert np.isnan(r.pr_auc), f"n={n}"
        assert np.isnan(r.log_loss), f"n={n}"
        assert np.isnan(r.brier_score), f"n={n}"
        assert np.isnan(r.pearson_ic), f"n={n}"
        assert np.isnan(r.spearman_ic_pooled), f"n={n}"


def test_compute_score_quality_q10_menos_q1_conferido_a_mao() -> None:
    """20 trades long, confidence estritamente crescente (rank == índice),
    `ret_net` = índice em bps -- bucketing por rank com 10 decis dá 2
    trades por decil: decil1 (rank 0,1) -> ret={0,1}bps, media=0,5bps;
    decil10 (rank 18,19) -> ret={18,19}bps, media=18,5bps. Spread
    esperado = 18,5-0,5 = 18,0bps, valor exato, não aproximado."""
    t0s = _t0s(20)
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": float(i) / 19.0, "fold_id": 0}
        for i in range(20)
    ]
    label_rows = [{"t0": t0s[i], "side": 1, "ret_net": float(i) / 10_000.0} for i in range(20)]
    out = sq.compute_score_quality(_predictions_df(pred_rows), _labels_df(label_rows))

    r = out[0]
    assert r.q10_minus_q1_bps == pytest.approx(18.0)


def test_compute_score_quality_classe_unica_classificacao_nan_mas_ic_computado() -> None:
    """Todos os trades são win (y_true constante) -- AUC/PR-AUC/LogLoss/
    Brier indefinidos (NaN, mesma convenção de
    `src.models.baselines._pool_auc`), mas o IC de Spearman continua
    computável (mede ranking contra retorno CONTÍNUO, não contra a classe
    binária). 5 trades (piso `_MIN_OBS_FOR_SMALL_SAMPLE_METRICS`,
    correção 2026-08-31)."""
    t0s = _t0s(5)
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": c, "fold_id": 0}
        for i, c in enumerate([0.2, 0.35, 0.5, 0.65, 0.8])
    ]
    label_rows = [
        {"t0": t0s[i], "side": 1, "ret_net": r}
        for i, r in enumerate([0.001, 0.0015, 0.002, 0.0025, 0.003])
    ]
    out = sq.compute_score_quality(_predictions_df(pred_rows), _labels_df(label_rows))

    assert len(out) == 1
    r = out[0]
    assert np.isnan(r.roc_auc)
    assert np.isnan(r.pr_auc)
    assert np.isnan(r.log_loss)
    assert np.isnan(r.brier_score)
    assert r.spearman_ic_pooled == pytest.approx(1.0)


def test_compute_score_quality_dispersao_de_ic_por_fold_conferida_a_mao() -> None:
    """3 folds, cada um com 5 trades (piso `_MIN_OBS_FOR_SMALL_SAMPLE_
    METRICS`, correção 2026-08-31) e correlação perfeita interna mas
    MAGNITUDE diferente de retorno por fold (não afeta o IC de Spearman,
    que é invariante a escala) -- aqui construo folds com sinal de IC
    OPOSTO (2 folds IC=+1,0, 1 fold IC=-1,0) para ter uma dispersão real
    de conferir a mão: mean=1/3, std(ddof=1)=sqrt(3)/... -- calculado
    explicitamente abaixo, não assumido."""
    pred_rows = []
    label_rows = []
    t0s = _t0s(15)
    # fold 0: IC=+1 (confidence e ret_net andam juntos)
    # fold 1: IC=+1
    # fold 2: IC=-1 (confidence e ret_net invertidos)
    fold_confidences = [
        [0.1, 0.3, 0.5, 0.7, 0.9],
        [0.15, 0.35, 0.55, 0.75, 0.95],
        [0.9, 0.7, 0.5, 0.3, 0.1],
    ]
    ret_net_seq = [0.001, 0.002, 0.003, 0.004, 0.005]
    idx = 0
    for fold_id in range(3):
        for j in range(5):
            pred_rows.append(
                {
                    "t0": t0s[idx],
                    "side_hat": 1,
                    "confidence": fold_confidences[fold_id][j],
                    "fold_id": fold_id,
                }
            )
            label_rows.append({"t0": t0s[idx], "side": 1, "ret_net": ret_net_seq[j]})
            idx += 1

    out = sq.compute_score_quality(_predictions_df(pred_rows), _labels_df(label_rows))
    r = out[0]

    assert r.n_folds_com_ic == 3
    ics = np.array([1.0, 1.0, -1.0])
    expected_mean = float(ics.mean())
    expected_std = float(ics.std(ddof=1))
    expected_ir = expected_mean / expected_std
    expected_tstat = expected_mean / (expected_std / np.sqrt(3))
    assert r.spearman_ic_mean_por_fold == pytest.approx(expected_mean)
    assert r.spearman_ic_std_por_fold == pytest.approx(expected_std)
    assert r.ic_ir == pytest.approx(expected_ir)
    assert r.ic_tstat == pytest.approx(expected_tstat)
    assert r.pct_ic_positive == pytest.approx(2.0 / 3.0)


def test_compute_score_quality_um_fold_so_dispersao_nan() -> None:
    """1 fold só, 5 trades (piso `_MIN_OBS_FOR_SMALL_SAMPLE_METRICS`,
    correção 2026-08-31) -- IC mean/median existem, mas std/IC_IR/t-stat
    exigem >=2 FOLDS (desvio-padrão amostral indefinido com 1 ponto) --
    `NaN`, não `ZeroDivisionError`."""
    t0s = _t0s(5)
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": c, "fold_id": 0}
        for i, c in enumerate([0.1, 0.3, 0.5, 0.7, 0.9])
    ]
    label_rows = [
        {"t0": t0s[i], "side": 1, "ret_net": r}
        for i, r in enumerate([0.001, 0.002, 0.003, 0.004, 0.005])
    ]
    out = sq.compute_score_quality(_predictions_df(pred_rows), _labels_df(label_rows))
    r = out[0]

    assert r.n_folds_com_ic == 1
    assert r.spearman_ic_mean_por_fold == pytest.approx(1.0)
    assert np.isnan(r.spearman_ic_std_por_fold)
    assert np.isnan(r.ic_ir)
    assert np.isnan(r.ic_tstat)


def test_compute_score_quality_filtros_excluem_is_oof_false_e_nofill() -> None:
    """Mesmo espírito do teste irmão em `confidence_deciles_by_side` --
    linhas contaminantes (is_oof=False, NOFILL) não devem entrar no
    cômputo. `side_hat=-1` legítimo (sem contaminação) continua contando
    como 1 trade válido do lado short — os dois lados aparecem na saída,
    cada um só com as linhas realmente válidas."""
    t0s = _t0s(5)
    pred_rows = [
        {"t0": t0s[0], "side_hat": 1, "confidence": 0.3, "fold_id": 0},
        {"t0": t0s[1], "side_hat": 1, "confidence": 0.7, "fold_id": 0},
        {"t0": t0s[2], "side_hat": 1, "confidence": 0.9, "is_oof": False, "fold_id": 0},
        {"t0": t0s[3], "side_hat": -1, "confidence": 0.9, "fold_id": 0},
        {"t0": t0s[4], "side_hat": 1, "confidence": 0.5, "fold_id": 0},
    ]
    label_rows = [
        {"t0": t0s[0], "side": 1, "ret_net": -0.001},
        {"t0": t0s[1], "side": 1, "ret_net": 0.002},
        {"t0": t0s[2], "side": 1, "ret_net": 0.001},
        {"t0": t0s[3], "side": -1, "ret_net": 0.001},
        {"t0": t0s[4], "side": 1, "ret_net": 0.001, "barrier_hit": "NOFILL"},
    ]
    out = sq.compute_score_quality(_predictions_df(pred_rows), _labels_df(label_rows))
    by_side = {r.side: r for r in out}

    assert set(by_side) == {"long", "short"}
    # long: 5 linhas -> exclui is_oof=False (t0s[2]) e NOFILL (t0s[4]) -> 2 válidas
    assert by_side["long"].n_trades == 2
    # short: só t0s[3], sem contaminação -> 1 válida
    assert by_side["short"].n_trades == 1


def test_compute_score_quality_lado_sem_trade_ausente_da_tupla() -> None:
    t0s = _t0s(2)
    pred_rows = [{"t0": t0s[i], "side_hat": 1, "confidence": 0.5, "fold_id": 0} for i in range(2)]
    label_rows = [{"t0": t0s[i], "side": 1, "ret_net": 0.001} for i in range(2)]
    out = sq.compute_score_quality(_predictions_df(pred_rows), _labels_df(label_rows))

    assert len(out) == 1
    assert {r.side for r in out} == {"long"}


def test_compute_score_quality_predictions_vazio_devolve_tupla_vazia_sem_checar_labels() -> None:
    """0 folds (ex. `permutation_null_replicas` interrompe antes de
    treinar) -- mesmo early-return de
    `backtest_lite.realize_trades` (nunca toca `df_all` quando
    `fold_results` está vazio): `labels` pode ser um stub sem as colunas
    exigidas, não deve levantar."""
    predictions = pl.DataFrame(
        schema={
            "t0": _T0_DTYPE,
            "side_hat": pl.Int8,
            "is_oof": pl.Boolean,
            "fold_id": pl.Int16,
            "confidence": pl.Float64,
        }
    )
    labels_stub = pl.DataFrame({"t0": pl.Series([], dtype=_T0_DTYPE)})

    out = sq.compute_score_quality(predictions, labels_stub)

    assert out == ()


def test_compute_score_quality_coluna_ausente_em_predictions_levanta_valueerror() -> None:
    predictions = _predictions_df(
        [{"t0": _t0s(1)[0], "side_hat": 1, "confidence": 0.5, "fold_id": 0}]
    ).drop("fold_id")
    labels = _labels_df([{"t0": _t0s(1)[0], "side": 1, "ret_net": 0.001}])
    with pytest.raises(ValueError, match="fold_id"):
        sq.compute_score_quality(predictions, labels)


def test_compute_score_quality_coluna_ausente_em_labels_levanta_valueerror() -> None:
    predictions = _predictions_df(
        [{"t0": _t0s(1)[0], "side_hat": 1, "confidence": 0.5, "fold_id": 0}]
    )
    labels = _labels_df([{"t0": _t0s(1)[0], "side": 1, "ret_net": 0.001}]).drop("ret_net")
    with pytest.raises(ValueError, match="ret_net"):
        sq.compute_score_quality(predictions, labels)


# ============================================================================
# compute_decile_profile — ADR-008 Fase 5 (eixo "decile returns" da
# stability matrix). MESMA população/join de compute_score_quality
# (_join_oof_predictions_to_labels) — reusa as mesmas fixtures.
# ============================================================================


def test_compute_decile_profile_conferido_a_mao() -> None:
    """Mesmo fixture de `test_compute_score_quality_q10_menos_q1_
    conferido_a_mao` — 20 trades long, `confidence` estritamente
    crescente, `ret_net=i/10_000`. Decil `d` (1-indexado) cobre ranks
    `[2(d-1), 2(d-1)+1]` -> `mean_ret_net_bps = (4d-3)/2`, `n_trades=2`
    em CADA um dos 10 decis — valores exatos, não aproximados."""
    t0s = _t0s(20)  # noqa: magic-number
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": float(i) / 19.0, "fold_id": 0}
        for i in range(20)  # noqa: magic-number
    ]
    label_rows = [{"t0": t0s[i], "side": 1, "ret_net": float(i) / 10_000.0} for i in range(20)]  # noqa: magic-number
    out = sq.compute_decile_profile(_predictions_df(pred_rows), _labels_df(label_rows))

    assert len(out) == 1
    r = out[0]
    assert r.side == "long"
    assert r.n_trades == 20  # noqa: magic-number
    assert len(r.buckets) == 10  # noqa: magic-number
    for d in range(1, 11):
        bucket = r.buckets[d - 1]
        assert bucket.decile == d
        assert bucket.n_trades == 2  # noqa: magic-number
        assert bucket.mean_ret_net_bps == pytest.approx((4 * d - 3) / 2)
    assert r.q10_minus_q1_bps == pytest.approx(18.0)  # noqa: magic-number


def test_compute_decile_profile_q10_minus_q1_bate_com_score_quality() -> None:
    """`q10_minus_q1_bps` tem que ser IDÊNTICO entre as duas funções sobre
    o mesmo dado -- mesma população (`_join_oof_predictions_to_labels`
    compartilhada) e mesmo `_decile_buckets` por baixo."""
    t0s = _t0s(15)  # noqa: magic-number
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": float(i) / 14.0, "fold_id": 0}
        for i in range(15)  # noqa: magic-number
    ]
    label_rows = [{"t0": t0s[i], "side": 1, "ret_net": float(i) / 10_000.0} for i in range(15)]  # noqa: magic-number
    predictions = _predictions_df(pred_rows)
    labels = _labels_df(label_rows)

    score_quality_out = sq.compute_score_quality(predictions, labels)
    decile_out = sq.compute_decile_profile(predictions, labels)

    assert score_quality_out[0].q10_minus_q1_bps == pytest.approx(decile_out[0].q10_minus_q1_bps)


def test_compute_decile_profile_deterministico_sob_ordem_de_entrada_com_confidence_empatada() -> (
    None
):
    """Correção 2026-08-31 (achado real de auditoria) -- `.join()` do
    Polars não garante ordem de linha entre execuções (hash join), e
    `_decile_buckets` desempata platôs de `confidence` idêntica (comuns
    sob calibrador isotônico, função-degrau) via `argsort(kind="stable")`,
    que só preserva a ordem de CHEGADA das linhas. `_join_oof_
    predictions_to_labels` agora ordena por `[confidence, t0]` antes de
    devolver -- alimentar as MESMAS linhas em ordem de entrada DIFERENTE
    tem que produzir o MESMO resultado (desempatado por `t0`, nunca por
    ordem de chegada)."""
    t0s = _t0s(12)  # noqa: magic-number
    confidences = [0.3] * 6 + [0.7] * 6  # 2 platos de 6 -- forca empate real
    ret_nets = [float(i) / 10_000.0 for i in range(12)]  # noqa: magic-number -- distinto por t0
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": confidences[i], "fold_id": 0}
        for i in range(12)  # noqa: magic-number
    ]
    label_rows = [{"t0": t0s[i], "side": 1, "ret_net": ret_nets[i]} for i in range(12)]  # noqa: magic-number

    out_forward = sq.compute_decile_profile(_predictions_df(pred_rows), _labels_df(label_rows))
    out_reversed = sq.compute_decile_profile(
        _predictions_df(list(reversed(pred_rows))), _labels_df(list(reversed(label_rows)))
    )

    assert out_forward[0].buckets == out_reversed[0].buckets
    assert out_forward[0].q10_minus_q1_bps == out_reversed[0].q10_minus_q1_bps


def test_compute_decile_profile_menos_de_10_trades_ausente_da_tupla() -> None:
    t0s = _t0s(5)
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": float(i), "fold_id": 0} for i in range(5)
    ]
    label_rows = [{"t0": t0s[i], "side": 1, "ret_net": 0.001} for i in range(5)]  # noqa: magic-number
    out = sq.compute_decile_profile(_predictions_df(pred_rows), _labels_df(label_rows))

    assert out == ()


def test_compute_decile_profile_predictions_vazio_devolve_tupla_vazia() -> None:
    predictions = pl.DataFrame(
        schema={
            "t0": _T0_DTYPE,
            "side_hat": pl.Int8,
            "is_oof": pl.Boolean,
            "fold_id": pl.Int16,
            "confidence": pl.Float64,
        }
    )
    labels_stub = pl.DataFrame({"t0": pl.Series([], dtype=_T0_DTYPE)})

    out = sq.compute_decile_profile(predictions, labels_stub)

    assert out == ()


def test_compute_decile_profile_coluna_ausente_em_predictions_levanta_valueerror() -> None:
    predictions = _predictions_df(
        [{"t0": _t0s(1)[0], "side_hat": 1, "confidence": 0.5, "fold_id": 0}]
    ).drop("fold_id")
    labels = _labels_df([{"t0": _t0s(1)[0], "side": 1, "ret_net": 0.001}])  # noqa: magic-number
    with pytest.raises(ValueError, match="fold_id"):
        sq.compute_decile_profile(predictions, labels)


# ============================================================================
# compute_train_val_test_gap — ADR-008 Fase 3. Mesmas fórmulas de
# `compute_score_quality` acima, aplicadas aos segmentos IN-SAMPLE
# (`fit`/`stop`/`calib`) em vez do join OOF. Fakes duck-typed mínimos
# (mesmo padrão de `_FakeFoldResult` em `test_models_backtest_lite.py`) --
# construir um `SideModelResult`/`FoldResult` real exigiria booster/
# calibrador/HHI completos, irrelevante pro que esta função lê
# (`.fit_segment`/`.stop_segment`/`.calib_segment`, `.long_result`/
# `.short_result`).
# ============================================================================


def _segment(
    calibrated_score: list[float], label: list[int], ret_net: list[float]
) -> alpha.InSampleSegmentScores:
    return alpha.InSampleSegmentScores(
        n=len(calibrated_score),
        calibrated_score=np.array(calibrated_score, dtype=np.float64),
        label=np.array(label, dtype=np.int64),
        ret_net=np.array(ret_net, dtype=np.float64),
    )


class _FakeSideModelResult:
    def __init__(
        self,
        fit_segment: alpha.InSampleSegmentScores | None = None,
        stop_segment: alpha.InSampleSegmentScores | None = None,
        calib_segment: alpha.InSampleSegmentScores | None = None,
    ) -> None:
        self.fit_segment = fit_segment
        self.stop_segment = stop_segment
        self.calib_segment = calib_segment


class _FakeFoldResult:
    def __init__(
        self, long_result: _FakeSideModelResult, short_result: _FakeSideModelResult
    ) -> None:
        self.long_result = long_result
        self.short_result = short_result


def test_compute_train_val_test_gap_fit_separacao_perfeita_mesma_formula_score_quality() -> None:
    """Mesmo cenário de separação perfeita de
    `test_compute_score_quality_separacao_perfeita_auc_1_e_ic_positivo`,
    mas sobre o segmento `fit` in-sample -- prova que a agregação usa
    EXATAMENTE a mesma fórmula (cross-check direto contra sklearn), não
    uma versão paralela divergente. `stop`/`calib` ausentes (short sem
    nenhum segmento) -- só `long` aparece na tupla. 5 trades (piso
    `_MIN_OBS_FOR_SMALL_SAMPLE_METRICS`, correção 2026-08-31)."""
    calibrated_score = [0.1, 0.3, 0.5, 0.7, 0.9]  # noqa: magic-number
    ret_net = [-0.003, -0.002, -0.001, 0.002, 0.004]  # noqa: magic-number
    label = [0, 0, 0, 1, 1]
    fit_seg = _segment(calibrated_score, label, ret_net)
    fold = _FakeFoldResult(_FakeSideModelResult(fit_segment=fit_seg), _FakeSideModelResult())

    out = sq.compute_train_val_test_gap([fold])  # type: ignore[list-item]

    assert len(out) == 1
    r = out[0]
    assert r.side == "long"
    assert r.fit is not None
    assert r.fit.n_trades == 5
    y_true = np.array([0, 0, 0, 1, 1])
    assert r.fit.roc_auc == pytest.approx(float(roc_auc_score(y_true, np.array(calibrated_score))))
    assert r.stop is None
    assert r.calib is None
    assert r.gap_fit_minus_stop == {}


def test_compute_train_val_test_gap_pool_fit_entre_2_folds() -> None:
    """2 folds, 5 trades cada (piso `_MIN_OBS_FOR_SMALL_SAMPLE_METRICS`
    por segmento, correção 2026-08-31) -- pool de 10 trades, 1 IC por
    fold, ambos computáveis."""
    seg_a = _segment(
        [0.1, 0.3, 0.5, 0.7, 0.9],  # noqa: magic-number
        [0, 0, 0, 1, 1],
        [-0.003, -0.002, -0.001, 0.002, 0.003],  # noqa: magic-number
    )
    seg_b = _segment(
        [0.15, 0.35, 0.55, 0.75, 0.95],  # noqa: magic-number
        [0, 0, 0, 1, 1],
        [-0.004, -0.002, -0.001, 0.003, 0.004],  # noqa: magic-number
    )
    fold_a = _FakeFoldResult(_FakeSideModelResult(fit_segment=seg_a), _FakeSideModelResult())
    fold_b = _FakeFoldResult(_FakeSideModelResult(fit_segment=seg_b), _FakeSideModelResult())

    out = sq.compute_train_val_test_gap([fold_a, fold_b])  # type: ignore[list-item]

    r = out[0]
    assert r.fit is not None
    assert r.fit.n_trades == 10  # 5 + 5 pooled entre os 2 folds
    assert r.fit.n_folds_com_ic == 2  # 1 IC por fold, ambos computáveis (n=5 >= 5)


def test_compute_train_val_test_gap_deltas_conferidos_a_mao() -> None:
    """`fit` com separação perfeita (roc_auc=1,0), `stop` com separação
    invertida (roc_auc=0,0) -- `gap_fit_minus_stop["roc_auc"]` tem que
    ser exatamente 1,0-0,0=1,0, não uma aproximação. 5 trades por
    segmento (piso `_MIN_OBS_FOR_SMALL_SAMPLE_METRICS`, correção
    2026-08-31)."""
    ret_net = [-0.004, -0.003, -0.002, 0.001, 0.002]  # noqa: magic-number -- vitoria = [0,0,0,1,1]
    label = [0, 0, 0, 1, 1]
    fit_seg = _segment([0.1, 0.3, 0.5, 0.7, 0.9], label, ret_net)  # noqa: magic-number
    stop_seg = _segment([0.9, 0.7, 0.5, 0.3, 0.1], label, ret_net)  # noqa: magic-number
    fold = _FakeFoldResult(
        _FakeSideModelResult(fit_segment=fit_seg, stop_segment=stop_seg), _FakeSideModelResult()
    )

    out = sq.compute_train_val_test_gap([fold])  # type: ignore[list-item]
    r = out[0]

    assert r.fit is not None
    assert r.stop is not None
    assert r.fit.roc_auc == pytest.approx(1.0)
    assert r.stop.roc_auc == pytest.approx(0.0)
    assert r.gap_fit_minus_stop["roc_auc"] == pytest.approx(1.0)


def test_compute_train_val_test_gap_y_true_e_vitoria_economica_nao_label_bruto() -> None:
    """`label` (TP/not-TP bruto) e `ret_net>0` (vitória econômica)
    DIVERGEM deliberadamente aqui -- se a implementação usasse `label`
    bruto como `y_true`, `roc_auc` seria baixo (ordem invertida); usando
    vitória econômica (mesma convenção de `compute_score_quality`), é
    1,0. Prova que a convenção documentada é real, não só descrita. 5
    trades (piso `_MIN_OBS_FOR_SMALL_SAMPLE_METRICS`, correção
    2026-08-31)."""
    calibrated_score = [0.1, 0.3, 0.5, 0.7, 0.9]  # noqa: magic-number
    label = [1, 1, 1, 0, 0]  # oposto do sinal de `ret_net` abaixo, de proposito
    ret_net = [-0.004, -0.003, -0.002, 0.002, 0.003]  # noqa: magic-number -- vitoria = [0,0,0,1,1]
    seg = _segment(calibrated_score, label, ret_net)
    fold = _FakeFoldResult(_FakeSideModelResult(fit_segment=seg), _FakeSideModelResult())

    out = sq.compute_train_val_test_gap([fold])  # type: ignore[list-item]
    r = out[0]

    assert r.fit is not None
    assert r.fit.roc_auc == pytest.approx(1.0)


def test_compute_train_val_test_gap_nenhum_segmento_em_nenhum_lado_devolve_tupla_vazia() -> None:
    fold = _FakeFoldResult(_FakeSideModelResult(), _FakeSideModelResult())
    out = sq.compute_train_val_test_gap([fold])  # type: ignore[list-item]
    assert out == ()


def test_compute_train_val_test_gap_segmento_n_zero_tratado_como_ausente() -> None:
    """Segmento com `n=0` (arrays vazios) não deve contaminar o pool nem
    aparecer como um resultado `NaN` -- tratado como ausente, mesmo
    contrato de lado sem trade em `compute_score_quality`."""
    seg_vazio = alpha.InSampleSegmentScores(
        n=0,
        calibrated_score=np.array([], dtype=np.float64),
        label=np.array([], dtype=np.int64),
        ret_net=np.array([], dtype=np.float64),
    )
    fold = _FakeFoldResult(_FakeSideModelResult(fit_segment=seg_vazio), _FakeSideModelResult())
    out = sq.compute_train_val_test_gap([fold])  # type: ignore[list-item]
    assert out == ()
