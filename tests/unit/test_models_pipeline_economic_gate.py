"""Testes de `src.models.pipeline._economic_gate_verdicts_by_side` --
orquestrador de trial soft-flag do gate econômico (AG-260 ponto (b),
`/redesign_workflow` 2026-08-27).

Depois do refactor de Fase 6 (revisão de qualidade), a função recebe
`threshold: GateRow | None` já resolvido pelo caller -- não toca disco,
não chama `lookup_pre_trial_gate` internamente. Isso a torna um núcleo
puro (Idioma A, §Núcleo funcional do CLAUDE.md): `pl.DataFrame` +
`GateRow` em memória entram, `dict` em memória sai -- testável sem
mockar `config/min_alpha_lift_by_combo.yaml` nem rodar um treino real.

O caminho ponta a ponta (`run_layer1_sprint(use_economic_gate=True)`
chamando esta função de verdade com `filled_c1` de um treino real) NÃO é
exercitado aqui -- custaria um CPCV completo (~117s, ver docstring de
`test_models_pipeline.py`) só para testar roteamento já coberto por este
arquivo no nível da função pura. Ver `tests/unit/test_models_pipeline_
paths.py` pro mesmo racional aplicado a `tf`/`dest_dir`."""

from __future__ import annotations

import polars as pl
import pytest

from src.models import pipeline
from src.models.economic_gate import GateRow

_SYMBOL = "BTCUSDT"
_RESOLUTION_ID = "R1"


def _threshold(*, breakeven_wr: float = 0.55, side: str = "long") -> GateRow:
    return GateRow(
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        side=side,
        cell_id="c",
        tp_atr_mult=1.5,
        sl_atr_mult=1.5,
        n_filled=1,
        atr_median_bps=30.0,
        p_tp=0.47,
        breakeven_wr=breakeven_wr,
        required_lift=breakeven_wr / 0.47,
        required_lift_stderr=0.001,
        required_lift_ci95_low=0.0,
        required_lift_ci95_high=1.0,
    )


def _filled_trades(rows: list[tuple[int, str]]) -> pl.DataFrame:
    """`rows` = [(side_hat, barrier_hit), ...] -- só as duas colunas que
    `_economic_gate_verdicts_by_side` lê de `filled_c1`."""
    return pl.DataFrame(
        {
            "side_hat": pl.Series([r[0] for r in rows], dtype=pl.Int8),
            "barrier_hit": pl.Series([r[1] for r in rows], dtype=pl.Utf8),
        }
    )


def test_none_quando_resolution_id_none() -> None:
    trades = _filled_trades([(1, "TP")])
    out = pipeline._economic_gate_verdicts_by_side(
        trades, symbol=_SYMBOL, resolution_id=None, threshold=_threshold()
    )
    assert out is None


def test_none_quando_threshold_none() -> None:
    trades = _filled_trades([(1, "TP")])
    out = pipeline._economic_gate_verdicts_by_side(
        trades, symbol=_SYMBOL, resolution_id=_RESOLUTION_ID, threshold=None
    )
    assert out is None


def test_computa_veredito_por_lado() -> None:
    # long: 3 TP em 4 preenchidos (p_tp=0.75); short: 1 TP em 4 (p_tp=0.25).
    trades = _filled_trades(
        [
            (1, "TP"), (1, "TP"), (1, "TP"), (1, "SL"),
            (-1, "TP"), (-1, "SL"), (-1, "SL"), (-1, "TIME"),
        ]
    )
    out = pipeline._economic_gate_verdicts_by_side(
        trades,
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        threshold=_threshold(breakeven_wr=0.55),
    )
    assert out is not None
    assert out["long"]["candidate_p_tp"] == pytest.approx(0.75)
    assert out["long"]["passes"] is True
    assert out["short"]["candidate_p_tp"] == pytest.approx(0.25)
    assert out["short"]["passes"] is False


def test_none_por_lado_sem_nenhum_trade_preenchido() -> None:
    trades = _filled_trades([(1, "TP"), (1, "SL")])  # nenhum trade short
    out = pipeline._economic_gate_verdicts_by_side(
        trades, symbol=_SYMBOL, resolution_id=_RESOLUTION_ID, threshold=_threshold()
    )
    assert out is not None
    assert out["long"] is not None
    assert out["short"] is None


def test_none_por_lado_quando_zero_tp_nunca_levanta() -> None:
    """`candidate_p_tp==0.0` faria `evaluate_economic_gate` levantar
    `EconomicGateError` -- a função tem que engolir isso e devolver
    `None` pro lado, nunca deixar propagar (soft-flag, nunca interrompe
    o treino real)."""
    trades = _filled_trades([(1, "SL"), (1, "TIME")])  # long: zero TP
    out = pipeline._economic_gate_verdicts_by_side(
        trades, symbol=_SYMBOL, resolution_id=_RESOLUTION_ID, threshold=_threshold()
    )
    assert out is not None
    assert out["long"] is None
