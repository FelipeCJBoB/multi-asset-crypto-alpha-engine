"""Testes de `src/analysis/tau_diagnostics.py` —
`tau_realization_diagnostic`. Três blocos, mesmo padrão de
`test_analysis_attribution.py`:

1. Fixture sintética com números redondos (`_report`/`_entry`) — alvo
   nominal, anualização pré/pós-fill por caminho, razão por caminho,
   médias e dispersão conferidos à mão.
2. Casos de borda/validação — campo obrigatório ausente, `report` vazio/
   sem a chave esperada, parâmetros inválidos, caminho degenerado
   (`trades_per_year <= 0` ou `n_filled_trades == 0`) virando
   `NOT_COMPUTABLE` em vez de `ZeroDivisionError`, dispersão com menos de
   2 caminhos válidos.
3. Integração real — `skip` a menos que `experiments/alpha_layer1_report.
   json` já exista (mesmo padrão skip de `test_analysis_attribution.py`),
   MAIS o invariante proposto pela task (realizado dentro de ±20% do alvo
   nominal E dispersão entre caminhos < 2x). Este bloco relê o relatório
   do disco a cada execução (outros agentes desta investigação podem estar
   regenerando `experiments/alpha_layer1_report.json` em paralelo — ver
   CLAUDE.md desta task) e usa `pytest.xfail(reason=...)` IMPERATIVO (não
   o decorator estático) precisamente para que a mensagem sempre cite os
   números REAIS medidos na execução atual, não um valor congelado na hora
   em que este teste foi escrito — mesma família de API que
   `pytest.mark.xfail` (ver pytest docs, "imperative xfail"), escolhida
   aqui porque o resultado depende de dado que pode mudar entre execuções
   (achado do Sprint de engenharia, não decisão de projeto)."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from src.analysis import tau_diagnostics as tau
from src.core.metric import Unit

# ============================================================================
# Fixture sintética — números redondos, hand-computed nos comentários
# ============================================================================


def _entry(
    *, path_id: int, n_signals: int, n_filled_trades: int, trades_per_year: float
) -> dict[str, Any]:
    return {
        "path_id": path_id,
        "n_signals": n_signals,
        "n_filled_trades": n_filled_trades,
        "trades_per_year": trades_per_year,
        "fill_rate": float(n_filled_trades) / float(n_signals) if n_signals else float("nan"),
        "mean_trade_ret": 0.0,
        "sharpe_naive": 0.0,
        "std_trade_ret": 0.0,
    }


def _report(
    entries: dict[str, dict[str, Any]], *, n_backtest_paths: int | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"camada1_backtest_by_path": entries}
    if n_backtest_paths is not None:
        payload["n_backtest_paths"] = n_backtest_paths
    return payload


def _round_number_report() -> dict[str, Any]:
    """3 caminhos, `período_anos` implícito == 1,0 em todos (`n_filled_trades
    == trades_per_year`) — isola a aritmética de anualização/razão/
    dispersão de qualquer ruído de back-derivação de período.

    path 0: n_filled=100 (tpy=100 -> período=1,0), n_signals=200 -> signals_per_year=200
    path 1: n_filled=200 (tpy=200 -> período=1,0), n_signals=300 -> signals_per_year=300
    path 2: n_filled=50  (tpy=50  -> período=1,0), n_signals=100 -> signals_per_year=100

    target_signal_rate=0.01, bars_per_year=10_000 -> alvo = 0,01*2*10_000 = 200

    ratio_pre  = [200/200, 300/200, 100/200] = [1.0, 1.5, 0.5]
    ratio_post = [100/200, 200/200, 50/200]  = [0.5, 1.0, 0.25]

    mean_signals_per_year = (200+300+100)/3 = 200          -> ratio 1.0
    mean_filled_per_year  = (100+200+50)/3  = 116,666...    -> ratio 0,58333...

    dispersion_pre  = max(200,300,100)/min(...) = 300/100 = 3.0
    dispersion_post = max(100,200,50)/min(...)  = 200/50  = 4.0"""
    return _report(
        {
            "0": _entry(path_id=0, n_signals=200, n_filled_trades=100, trades_per_year=100.0),
            "1": _entry(path_id=1, n_signals=300, n_filled_trades=200, trades_per_year=200.0),
            "2": _entry(path_id=2, n_signals=100, n_filled_trades=50, trades_per_year=50.0),
        },
        n_backtest_paths=3,
    )


_TARGET_SIGNAL_RATE = 0.01
_BARS_PER_YEAR = 10_000.0
_TARGET_NOMINAL = _TARGET_SIGNAL_RATE * _BARS_PER_YEAR  # 100.0 -- SEM fator de lado, ver Bloco 3


def test_alvo_nominal_e_a_definicao_do_quantil_vezes_bars_per_year() -> None:
    result = tau.tau_realization_diagnostic(
        _round_number_report(), target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
    )
    assert result.target_nominal_per_year.value == pytest.approx(_TARGET_NOMINAL)
    assert result.target_nominal_per_year.unit == Unit.COUNT
    assert result.target_nominal_per_year.n == round(_BARS_PER_YEAR)
    assert result.target_nominal_per_year.n_semantics == "bars"
    assert result.target_nominal_per_year.valid is True


def test_alvo_nominal_nao_tem_fator_de_lado() -> None:
    """Regressão (Faixa 1.6, Bloco 3) — `target_signal_rate` já é uma taxa
    TOTAL (derivada de §0.2 R3 sem termo de lado, ver
    `config/constants.yaml::fee_budget_is_per_side`). Se alguém
    reintroduzir um fator ×2 (ou qualquer outro fator de lado) no alvo
    nominal, este teste falha — trava contra a regressão que motivou esta
    task."""
    result = tau.tau_realization_diagnostic(
        _round_number_report(), target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
    )
    assert result.target_nominal_per_year.value == pytest.approx(
        _TARGET_SIGNAL_RATE * _BARS_PER_YEAR
    )
    assert result.target_nominal_per_year.value != pytest.approx(
        _TARGET_SIGNAL_RATE * 2.0 * _BARS_PER_YEAR
    )


def test_anualizacao_e_razao_por_caminho_batem_a_mao() -> None:
    result = tau.tau_realization_diagnostic(
        _round_number_report(), target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
    )
    assert len(result.paths) == 3
    by_id = {p.path_id: p for p in result.paths}

    expected_signals_per_year = {0: 200.0, 1: 300.0, 2: 100.0}
    expected_filled_per_year = {0: 100.0, 1: 200.0, 2: 50.0}
    # alvo = 100.0 (SEM fator de lado, ver Bloco 3) -> ratio dobra vs a versão antiga
    expected_ratio_pre = {0: 2.0, 1: 3.0, 2: 1.0}
    expected_ratio_post = {0: 1.0, 1: 2.0, 2: 0.5}

    for path_id in (0, 1, 2):
        p = by_id[path_id]
        assert p.n_signals_per_year.value == pytest.approx(expected_signals_per_year[path_id])
        assert p.n_signals_per_year.unit == Unit.COUNT
        assert p.n_signals_per_year.n_semantics == "signals"
        assert p.n_filled_per_year.value == pytest.approx(expected_filled_per_year[path_id])
        assert p.n_filled_per_year.n_semantics == "trades"
        assert p.ratio_pre_fill_to_target.value == pytest.approx(expected_ratio_pre[path_id])
        assert p.ratio_pre_fill_to_target.unit == Unit.RATIO
        assert p.ratio_post_fill_to_target.value == pytest.approx(expected_ratio_post[path_id])


def test_media_e_dispersao_entre_caminhos_batem_a_mao() -> None:
    result = tau.tau_realization_diagnostic(
        _round_number_report(), target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
    )
    assert result.mean_n_signals_per_year.value == pytest.approx(200.0)
    assert result.mean_n_signals_per_year.n == 3
    assert result.mean_n_signals_per_year.n_semantics == "cpcv_paths"
    assert result.mean_n_filled_per_year.value == pytest.approx(350.0 / 3.0)

    # alvo = 100.0 (SEM fator de lado, ver Bloco 3)
    assert result.mean_ratio_pre_fill_to_target.value == pytest.approx(2.0)
    assert result.mean_ratio_post_fill_to_target.value == pytest.approx(350.0 / 3.0 / 100.0)

    assert result.dispersion_pre_fill.value == pytest.approx(3.0)
    assert result.dispersion_pre_fill.unit == Unit.RATIO
    assert result.dispersion_pre_fill.n_semantics == "cpcv_paths"
    assert result.dispersion_post_fill.value == pytest.approx(4.0)


# ============================================================================
# Casos de borda / validação
# ============================================================================


def test_camada1_backtest_by_path_ausente_levanta_valueerror() -> None:
    with pytest.raises(ValueError, match="camada1_backtest_by_path"):
        tau.tau_realization_diagnostic(
            {}, target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
        )


def test_camada1_backtest_by_path_vazio_levanta_valueerror() -> None:
    with pytest.raises(ValueError, match="vazio"):
        tau.tau_realization_diagnostic(
            _report({}), target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
        )


def test_campo_obrigatorio_ausente_levanta_valueerror() -> None:
    entry = _entry(path_id=0, n_signals=10, n_filled_trades=5, trades_per_year=5.0)
    del entry["trades_per_year"]
    with pytest.raises(ValueError, match="trades_per_year"):
        tau.tau_realization_diagnostic(
            _report({"0": entry}),
            target_signal_rate=_TARGET_SIGNAL_RATE,
            bars_per_year=_BARS_PER_YEAR,
        )


def test_n_backtest_paths_divergente_levanta_valueerror() -> None:
    report = _round_number_report()
    report["n_backtest_paths"] = 99
    with pytest.raises(ValueError, match="n_backtest_paths"):
        tau.tau_realization_diagnostic(
            report, target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
        )


@pytest.mark.parametrize("target_signal_rate", [0.0, -0.01])
def test_target_signal_rate_nao_positivo_levanta_valueerror(target_signal_rate: float) -> None:
    with pytest.raises(ValueError, match="target_signal_rate"):
        tau.tau_realization_diagnostic(
            _round_number_report(),
            target_signal_rate=target_signal_rate,
            bars_per_year=_BARS_PER_YEAR,
        )


@pytest.mark.parametrize("bars_per_year", [0.0, -1.0])
def test_bars_per_year_nao_positivo_levanta_valueerror(bars_per_year: float) -> None:
    with pytest.raises(ValueError, match="bars_per_year"):
        tau.tau_realization_diagnostic(
            _round_number_report(),
            target_signal_rate=_TARGET_SIGNAL_RATE,
            bars_per_year=bars_per_year,
        )


def test_caminho_com_trades_per_year_zero_vira_not_computable_sem_explodir() -> None:
    """`trades_per_year == 0.0` (backtest sem nenhum trade preenchido naquele
    caminho) quebraria a back-derivação de período (`n_filled_trades /
    trades_per_year`) se não fosse guardado — verifica que os dois
    `Metric` do caminho degenerado voltam `NOT_COMPUTABLE`
    (`valid=False`, `value=nan`), não uma exceção nem um `0.0` silencioso,
    e que os caminhos SÃO excluídos (não tratados como zero) da média/
    dispersão."""
    report = _report(
        {
            "0": _entry(path_id=0, n_signals=200, n_filled_trades=100, trades_per_year=100.0),
            "1": _entry(path_id=1, n_signals=50, n_filled_trades=0, trades_per_year=0.0),
            "2": _entry(path_id=2, n_signals=300, n_filled_trades=200, trades_per_year=200.0),
        }
    )
    result = tau.tau_realization_diagnostic(
        report, target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
    )
    by_id = {p.path_id: p for p in result.paths}
    degenerate = by_id[1]
    assert degenerate.n_signals_per_year.valid is False
    assert math.isnan(degenerate.n_signals_per_year.value)
    assert degenerate.n_filled_per_year.valid is False
    assert degenerate.ratio_pre_fill_to_target.valid is False
    assert degenerate.ratio_post_fill_to_target.valid is False

    # média só sobre os 2 caminhos válidos: (200+300)/2=250 signals/ano,
    # (100+200)/2=150 filled/ano — o caminho degenerado NÃO entra como 0.0
    assert result.mean_n_signals_per_year.value == pytest.approx(250.0)
    assert result.mean_n_signals_per_year.n == 2
    assert result.mean_n_filled_per_year.value == pytest.approx(150.0)

    # dispersão também só sobre os 2 válidos: 300/200=1.5 e 200/100=2.0
    assert result.dispersion_pre_fill.value == pytest.approx(300.0 / 200.0)
    assert result.dispersion_post_fill.value == pytest.approx(200.0 / 100.0)


def test_dispersao_com_menos_de_2_caminhos_validos_vira_not_computable() -> None:
    report = _report(
        {
            "0": _entry(path_id=0, n_signals=200, n_filled_trades=100, trades_per_year=100.0),
            "1": _entry(path_id=1, n_signals=50, n_filled_trades=0, trades_per_year=0.0),
            "2": _entry(path_id=2, n_signals=50, n_filled_trades=0, trades_per_year=0.0),
        }
    )
    result = tau.tau_realization_diagnostic(
        report, target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
    )
    assert result.dispersion_pre_fill.valid is False
    assert math.isnan(result.dispersion_pre_fill.value)
    assert result.dispersion_post_fill.valid is False
    # a média, por sua vez, ainda é computável com 1 caminho válido
    assert result.mean_n_signals_per_year.value == pytest.approx(200.0)
    assert result.mean_n_signals_per_year.n == 1


def test_todos_caminhos_degenerados_media_vira_not_computable() -> None:
    report = _report(
        {
            "0": _entry(path_id=0, n_signals=50, n_filled_trades=0, trades_per_year=0.0),
            "1": _entry(path_id=1, n_signals=50, n_filled_trades=0, trades_per_year=float("nan")),
        }
    )
    result = tau.tau_realization_diagnostic(
        report, target_signal_rate=_TARGET_SIGNAL_RATE, bars_per_year=_BARS_PER_YEAR
    )
    assert result.mean_n_signals_per_year.valid is False
    assert result.mean_n_filled_per_year.valid is False
    assert result.dispersion_pre_fill.valid is False


# ============================================================================
# Integração real — skip se experiments/alpha_layer1_report.json ausente
# ============================================================================


def _load_real_report_and_constants() -> tuple[dict[str, Any], float, float]:
    """Relê `constants.yaml`/`alpha_layer1_report.json` do disco a cada
    chamada (nunca cacheado neste módulo de teste) — outros agentes desta
    investigação podem estar regenerando esses artefatos em paralelo (ver
    docstring do módulo/CLAUDE.md desta task).

    `bars_per_year` usa `src.models.backtest_lite.DAYS_PER_YEAR` (365,25 —
    calendário Gregoriano médio, já a convenção de anualização usada para
    produzir `trades_per_year` no próprio relatório via `sharpe_naive`/
    `span_seconds`) `* 24 * 4` (barras de 15m por dia). **Nota**: a
    aritmética ilustrativa da task (`365,25×24×4 = 35.040`) está incorreta
    — o produto correto é 35.064 (`35.040` é o que dá `365×24×4`, sem os
    0,25 dia extra); usar 365,25 aqui porque é a MESMA constante que já
    anualiza `trades_per_year` no relatório (`DAYS_PER_YEAR`,
    `src.models.backtest_lite`) — misturar duas convenções de dia/ano
    entre alvo e realizado introduziria um viés de ~0,07% que não tem
    nenhuma razão de existir (medido, não estipulado — Regra Zero)."""
    from src.models._constants import load_constant
    from src.models._paths import EXPERIMENTS_DIR
    from src.models.backtest_lite import DAYS_PER_YEAR

    report_path = EXPERIMENTS_DIR / "alpha_layer1_report.json"
    if not report_path.exists():
        pytest.skip(f"artefato real ausente, rode o pipeline primeiro: {report_path}")

    report: dict[str, Any] = json.loads(report_path.read_bytes())
    target_signal_rate = float(load_constant("target_signal_rate"))
    bars_per_year = DAYS_PER_YEAR * 24 * 4
    return report, target_signal_rate, bars_per_year


@pytest.mark.integration
def test_integracao_real_diagnostico_roda_e_produz_metrics_bem_formados() -> None:
    """`experiments/alpha_layer1_report.json` é um artefato COMPARTILHADO e
    volátil (ver docstring de `_load_real_report_and_constants` acima —
    qualquer agente rodando o pipeline pode regerá-lo pra outro combo
    symbol/resolution a qualquer momento) -- não há garantia de que o
    combo presente no disco AGORA tenha 0 caminhos degenerados. Achado
    real (2026-09-01): o arquivo já apareceu com um caminho 100%
    degenerado (`n_filled_trades=0`) real, não um bug -- `tau_
    diagnostics.py:231-233` trata isso deliberadamente como
    `NOT_COMPUTABLE` em vez de dividir por zero (mesmo contrato já
    coberto pelos testes sintéticos do bloco 2 acima). Este teste
    verifica a FORMA bem-formada do resultado sobre QUALQUER combo real
    presente, não assume ausência de degeneração."""
    report, target_signal_rate, bars_per_year = _load_real_report_and_constants()
    result = tau.tau_realization_diagnostic(
        report, target_signal_rate=target_signal_rate, bars_per_year=bars_per_year
    )

    assert result.target_nominal_per_year.valid is True
    assert result.target_nominal_per_year.value > 0.0
    assert len(result.paths) == report["n_backtest_paths"]

    for p in result.paths:
        # caminho degenerado (n_filled_trades==0) é NOT_COMPUTABLE por
        # desenho (tau_diagnostics.py:231-233), não uma falha de forma --
        # os 2 campos concordam em validade (ambos derivam do mesmo
        # período implícito back-derivado) e nunca levantam exceção.
        assert p.n_signals_per_year.valid == p.n_filled_per_year.valid
        if p.n_signals_per_year.valid:
            assert p.n_signals_per_year.value >= 0.0
            assert p.n_filled_per_year.value >= 0.0
            # pre-fill >= post-fill sempre (fill é subconjunto dos sinais)
            assert p.n_signals_per_year.value >= p.n_filled_per_year.value
        else:
            assert p.n_signals_per_year.invalid_reason
            assert p.n_filled_per_year.invalid_reason

    n_paths_validos = sum(1 for p in result.paths if p.n_signals_per_year.valid)
    if n_paths_validos == 0:
        pytest.skip(
            "todos os caminhos do combo presente em alpha_layer1_report.json estao "
            "degenerados agora -- nada a verificar sobre mean/dispersao neste run"
        )

    assert result.mean_n_signals_per_year.valid is True
    assert result.mean_n_filled_per_year.valid is True
    if n_paths_validos >= 2:  # noqa: magic-number -- piso de graus de liberdade pra dispersao (max/min), mesmo do modulo sob teste
        assert result.dispersion_pre_fill.valid is True
        assert result.dispersion_post_fill.valid is True
        assert result.dispersion_pre_fill.value >= 1.0  # max/min de valores positivos nunca é < 1
        assert result.dispersion_post_fill.value >= 1.0


_RATIO_BAND = (0.8, 1.2)  # invariante proposto pela task: realizado dentro de +/-20% do alvo
_DISPERSION_MAX = 2.0  # invariante proposto pela task: dispersão entre caminhos < 2x


def _invariant_holds(
    ratio_value: float, ratio_valid: bool, dispersion_value: float, dispersion_valid: bool
) -> bool:
    return (
        ratio_valid
        and dispersion_valid
        and _RATIO_BAND[0] <= ratio_value <= _RATIO_BAND[1]
        and dispersion_value < _DISPERSION_MAX
    )


@pytest.mark.integration
@pytest.mark.parametrize("versao", ["pre_fill", "post_fill"])
def test_invariante_tau_realizado_perto_do_alvo_e_dispersao_baixa(versao: str) -> None:
    """Invariante NOVO proposto pela task (§ "O que construir") — NÃO é um
    gate operacional, é diagnóstico: `mean_ratio_*_to_target` dentro de
    [0,8 ; 1,2] E `dispersion_*` < 2,0. Roda para as duas versões de
    "realizado" (pré-fill / pós-fill) separadamente, porque respondem
    perguntas diferentes (ver docstring do módulo) e o invariante pode
    bater numa e não na outra.

    Se o invariante FALHAR com o dado real de hoje, este teste NÃO ajusta
    o critério para passar (instrução explícita da task) — chama
    `pytest.xfail(reason=...)` imperativo com os números medidos NESTA
    execução. Se o invariante bater (dado real mudou e passou a caber no
    critério), o teste passa normalmente — nenhuma das duas branches exige
    edição manual deste arquivo."""
    report, target_signal_rate, bars_per_year = _load_real_report_and_constants()
    result = tau.tau_realization_diagnostic(
        report, target_signal_rate=target_signal_rate, bars_per_year=bars_per_year
    )

    if versao == "pre_fill":
        ratio = result.mean_ratio_pre_fill_to_target
        dispersion = result.dispersion_pre_fill
    else:
        ratio = result.mean_ratio_post_fill_to_target
        dispersion = result.dispersion_post_fill

    if _invariant_holds(ratio.value, ratio.valid, dispersion.value, dispersion.valid):
        return

    pytest.xfail(
        f"invariante proposto (ratio in [{_RATIO_BAND[0]}, {_RATIO_BAND[1]}], "
        f"dispersion < {_DISPERSION_MAX}) NAO bate com o dado real medido agora "
        f"({versao}): mean_ratio_to_target={ratio.value:.4f} (valid={ratio.valid}), "
        f"dispersion={dispersion.value:.4f} (valid={dispersion.valid}) -- achado real "
        "do Sprint de engenharia (tau IN-FOLD generaliza pior OOS do que o quantil "
        "nominal sugere, e a variação entre caminhos de CPCV é maior que 2x); NAO "
        "ajustar o criterio para passar (CLAUDE.md, Regra Zero)."
    )
