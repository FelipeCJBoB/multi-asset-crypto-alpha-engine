"""Testes de `src/analysis/m2_bar_comparison.py` -- orquestrador
(`ProcessPoolExecutor`, fan-out, relatório), depois do desmembramento de
2026-08-15 em `m2_stats.py` (núcleo estatístico, ver
`test_analysis_m2_stats.py`) + `m2_worker.py` (tudo que roda dentro de 1
processo filho, ver `test_analysis_m2_worker.py`) + este arquivo (só
orquestração). `run_and_save_bar_comparison_report` em si (o
`ProcessPoolExecutor` completo) não é exercitado aqui -- IO real de
verdade, custoso demais pra suíte automatizada.

**Correção sobre uma alegação anterior (achado de auditoria
`project_assurance`, 2026-08-15):** este arquivo dizia "mesma convenção
de M1/M3/M6 -- IO real fica fora da suíte automatizada". Falso pra M1 e
M3 -- os dois têm teste `integration`+`slow` de ponta a ponta contra
backfill local (`test_run_volatility_comparison_for_symbol_tf_btcusdt_
15m_sobre_dado_real`, `test_compute_timeframe_choice_for_symbol_btcusdt_
sobre_dado_real`); só M6 batia com a alegação. M2 agora tem o equivalente
em `test_analysis_m2_worker.py` (`test_compute_time_bar_for_symbol_
btcusdt_sobre_dado_real` + `test_trades_dependent_bars_btcusdt_sobre_
dado_real_janela_curta`) -- não aqui, porque as funções que fazem IO real
vivem em `m2_worker.py`, não neste arquivo. Fica enxuto de propósito: o
que sobrou testável sem IO nesta camada de orquestração pura é só a
constante de referência de `time_stop_ms` abaixo."""

from __future__ import annotations

import src.analysis.m2_bar_comparison as m2


def test_time_stop_reference_tf_e_15m() -> None:
    """Trava o TF de referência -- `time_stop_bars=32` só significa "1
    janela de funding" (8h) se convertido via `step_ms("15m")`. Mudar
    esta constante sem reavaliar `time_stop_bars` quebraria essa
    equivalência silenciosamente."""
    assert m2.TIME_STOP_REFERENCE_TF == "15m"
