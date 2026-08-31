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
    """4 trades long: confidence crescente, ret_net crescente (2 losses
    baixa confiança, 2 wins alta confiança) -- separação perfeita,
    AUC=1,0 exato, IC de Spearman = 1,0 exato (mesma ordem)."""
    t0s = _t0s(4)
    confidence = [0.1, 0.4, 0.6, 0.9]
    ret_net = [-0.002, -0.001, 0.003, 0.004]
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": confidence[i], "fold_id": 0}
        for i in range(4)
    ]
    label_rows = [{"t0": t0s[i], "side": 1, "ret_net": ret_net[i]} for i in range(4)]
    predictions = _predictions_df(pred_rows)
    labels = _labels_df(label_rows)

    out = sq.compute_score_quality(predictions, labels)

    assert len(out) == 1
    r = out[0]
    assert r.side == "long"
    assert r.n_trades == 4
    assert r.roc_auc == pytest.approx(1.0)
    assert r.spearman_ic_pooled == pytest.approx(1.0)
    assert np.isnan(r.q10_minus_q1_bps)  # n=4 < 10 decis -- indefinido, nao zero
    assert r.pearson_ic == pytest.approx(np.corrcoef(confidence, ret_net)[0, 1])
    # cross-check direto contra sklearn sobre o MESMO subconjunto -- prova
    # que a seleção de dado (join/filtro) bate, não reimplementa a fórmula
    y_true = np.array([0, 0, 1, 1])
    y_score = np.array(confidence)
    assert r.roc_auc == pytest.approx(float(roc_auc_score(y_true, y_score)))
    assert r.log_loss == pytest.approx(float(log_loss(y_true, y_score, labels=[0, 1])))
    assert r.brier_score == pytest.approx(float(brier_score_loss(y_true, y_score)))


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
    binária)."""
    t0s = _t0s(3)
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": c, "fold_id": 0}
        for i, c in enumerate([0.2, 0.5, 0.8])
    ]
    label_rows = [
        {"t0": t0s[i], "side": 1, "ret_net": r}
        for i, r in enumerate([0.001, 0.002, 0.003])
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
    """3 folds, cada um com 3 trades e correlação perfeita interna mas
    MAGNITUDE diferente de retorno por fold (não afeta o IC de Spearman,
    que é invariante a escala) -- aqui construo folds com sinal de IC
    OPOSTO (2 folds IC=+1,0, 1 fold IC=-1,0) para ter uma dispersão real
    de conferir a mão: mean=1/3, std(ddof=1)=sqrt(3)/... -- calculado
    explicitamente abaixo, não assumido."""
    pred_rows = []
    label_rows = []
    t0s = _t0s(9)
    # fold 0: IC=+1 (confidence e ret_net andam juntos)
    # fold 1: IC=+1
    # fold 2: IC=-1 (confidence e ret_net invertidos)
    fold_confidences = [[0.1, 0.5, 0.9], [0.2, 0.4, 0.8], [0.9, 0.5, 0.1]]
    fold_rets = [[0.001, 0.002, 0.003], [0.001, 0.002, 0.003], [0.001, 0.002, 0.003]]
    idx = 0
    for fold_id in range(3):
        for j in range(3):
            pred_rows.append(
                {
                    "t0": t0s[idx],
                    "side_hat": 1,
                    "confidence": fold_confidences[fold_id][j],
                    "fold_id": fold_id,
                }
            )
            label_rows.append({"t0": t0s[idx], "side": 1, "ret_net": fold_rets[fold_id][j]})
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
    """1 fold só -- IC mean/median existem, mas std/IC_IR/t-stat exigem
    >=2 pontos (desvio-padrão amostral indefinido com 1 ponto) -- `NaN`,
    não `ZeroDivisionError`."""
    t0s = _t0s(3)
    pred_rows = [
        {"t0": t0s[i], "side_hat": 1, "confidence": c, "fold_id": 0}
        for i, c in enumerate([0.1, 0.5, 0.9])
    ]
    label_rows = [
        {"t0": t0s[i], "side": 1, "ret_net": r}
        for i, r in enumerate([0.001, 0.002, 0.003])
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
