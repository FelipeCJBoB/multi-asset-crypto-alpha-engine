"""Testes de `src/features/volatility_models.py` -- HAR-RV (Corsi 2009),
PRD_V4_1.md §3.2 M1, readaptado pra dollar bar (`AG-036`,
`audit/architecture_gaps_log.yaml`). Base real portada de
`git show 50dd621:tests/unit/test_features_volatility_models.py` (estado
antes da remoção em `2436b33`) -- toda referência a `bars_per_day` virou
`close_time`, mesma mudança do módulo sob teste. Os testes de
`EGARCH(1,1)` do arquivo original NÃO foram trazidos -- esse candidato não
está neste resgate (ver docstring do módulo: esforço GRANDE, bloqueado
por P-2, fora de escopo desta leva).

Eixos cobertos: causalidade dos regressores (dia/semana/mês nunca usam
`realized_var[t]`/dado com `close_time >= close_time[t]` pra prever
`realized_var[t]`), fit/predict end-to-end sobre série sintética conhecida,
dado insuficiente, forecast não-positivo virando NaN, preservação da
correção F1 (vazamento de 1 barra), e os 4 eixos NOVOS da readaptação pra
relógio real: janela sob relógio irregular, `close_time` duplicado
(rajada, `AG-061`), poucas observações dentro da janela (regime de baixa
atividade), e bit-exatidão contra o comportamento antigo por-contagem-de-
barra quando o relógio É de fato uniforme (grade de tempo)."""

from __future__ import annotations

import numpy as np
import pytest

from src.features import volatility_models as vm

# Passo sintético tal que `_MS_PER_DAY` (real, do módulo) cobre exatamente
# 4 barras -- mesma janela "pequena" (4/28/120) do teste original
# (`bars_per_day=4`), agora expressa em relógio uniforme em vez de
# contagem de barra. `_MS_PER_DAY` é múltiplo exato de 4 (21_600_000 * 4),
# então day/week/month fecham em exatamente 4/28/120 barras sem
# arredondamento.
_UNIFORM_STEP_MS = vm._MS_PER_DAY // 4


def _uniform_close_time(n: int) -> vm.IntArray:
    out: vm.IntArray = np.arange(n, dtype=np.int64) * _UNIFORM_STEP_MS
    return out


# ============================================================================
# `_causal_window_mean` -- bloco novo (substitui `_rolling_mean_causal`)
# ============================================================================


def test_causal_window_mean_relogio_irregular_janela_varia_por_densidade_real() -> None:
    # Espaçamento irregular à mão -- prova que a contagem de barras dentro
    # da janela muda de acordo com o `close_time` real, não uma contagem
    # fixa.
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    close_time = np.array([0, 10, 20, 30, 40], dtype=np.int64)
    window_ms = 25

    out = vm._causal_window_mean(x, close_time, window_ms)

    assert np.isnan(out[0])  # nenhuma barra anterior -- janela vazia
    assert out[1] == pytest.approx(1.0)  # so x[0] (close_time=0) dentro de [-15,10)
    assert out[2] == pytest.approx(1.5)  # x[0],x[1] dentro de [-5,20)
    assert out[3] == pytest.approx(2.5)  # x[1],x[2] dentro de [5,30) -- x[0] cai fora
    assert out[4] == pytest.approx(3.5)  # x[2],x[3] dentro de [15,40)


def test_causal_window_mean_rajada_pega_todas_as_barras_dentro_do_periodo_real() -> None:
    # Rajada de 5 barras dentro de poucos ms, seguida por 1 barra bem mais
    # tarde mas ainda dentro de 1 dia real -- a janela de "1 dia" deve
    # pegar a rajada INTEIRA, não uma contagem fixa de barras (essa é
    # exatamente a limitação que o design por-contagem-de-barra antigo
    # tinha sob dollar bar).
    close_time = np.array([0, 100, 200, 300, 400, 50_000_000], dtype=np.int64)
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    day = vm._causal_window_mean(x, close_time, vm._MS_PER_DAY)

    assert day[4] == pytest.approx(np.mean(x[:4]))
    # t=5 está a 50_000_000ms (~13.9h) do início da rajada -- ainda dentro
    # da janela de 1 dia (86_400_000ms) -- as 5 barras da rajada inteira
    # entram na média, densidade real capturada por construção.
    assert day[5] == pytest.approx(np.mean(x[:5]))


def test_causal_window_mean_close_time_duplicado_exclui_estrito_ag061() -> None:
    # AG-061: rajada real com `close_time` idêntico entre 2+ barras (SOLUSDT,
    # 2025-07-16). A comparação estrita "<" precisa excluir a própria barra
    # E qualquer outra com o MESMO close_time -- senão vaza B02 (informação
    # "simultânea" tratada como passado).
    close_time = np.array([0, 100, 100, 100, 200], dtype=np.int64)
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    day = vm._causal_window_mean(x, close_time, vm._MS_PER_DAY)

    # As 3 barras com close_time=100 (posições 1,2,3) não podem entrar na
    # janela umas das outras -- todas enxergam só a barra com close_time=0.
    assert day[1] == pytest.approx(1.0)
    assert day[2] == pytest.approx(1.0)
    assert day[3] == pytest.approx(1.0)
    # t=4 (close_time=200) enxerga as 4 barras anteriores (close_time < 200,
    # incluindo as 3 com close_time=100).
    assert day[4] == pytest.approx(np.mean(x[:4]))


def test_causal_window_mean_poucas_observacoes_usa_o_que_existe_nao_e_nan() -> None:
    # Regime de baixa atividade: só 1 barra anterior dentro da janela de 1
    # dia -- resultado é a média dessa única observação, NÃO NaN e NÃO
    # crash. Comportamento explícito por design (ver docstring do módulo):
    # a janela de relógio real soma o que existir, seja 1 barra ou 500.
    close_time = np.array([0, 12 * 3_600_000], dtype=np.int64)  # 12h depois
    x = np.array([1.0, 2.0])

    day = vm._causal_window_mean(x, close_time, vm._MS_PER_DAY)

    assert np.isnan(day[0])  # sem barra anterior -- janela vazia, NaN documentado
    assert day[1] == pytest.approx(1.0)  # 1 observação disponível, usada -- não NaN


def test_causal_window_mean_shapes_incompativeis_levanta_valueerror() -> None:
    x = np.array([1.0, 2.0, 3.0])
    close_time = np.array([0, 1], dtype=np.int64)
    with pytest.raises(ValueError, match=r"close_time\.shape"):
        vm._causal_window_mean(x, close_time, vm._MS_PER_DAY)


def test_causal_window_mean_close_time_fora_de_ordem_levanta_valueerror() -> None:
    x = np.array([1.0, 2.0, 3.0])
    close_time = np.array([0, 200, 100], dtype=np.int64)  # não-monotônico
    with pytest.raises(ValueError, match="ordenado ascendente"):
        vm._causal_window_mean(x, close_time, vm._MS_PER_DAY)


def test_causal_window_mean_serie_vazia_nao_crash() -> None:
    x = np.array([], dtype=np.float64)
    close_time = np.array([], dtype=np.int64)
    out = vm._causal_window_mean(x, close_time, vm._MS_PER_DAY)
    assert out.shape == (0,)


def test_causal_window_mean_relogio_uniforme_bit_exato_vs_contagem_de_barra_antiga() -> None:
    # Relógio sintético equivalente ao antigo `bars_per_day` -- sob relógio
    # DE FATO uniforme, o desenho novo (janela de relógio real) precisa
    # reproduzir bit-a-bit o resultado do desenho antigo (janela por
    # contagem de barra fixa) na região "regime estacionário" (janela já
    # totalmente coberta).
    rng = np.random.default_rng(11)
    n = 400
    close_time = _uniform_close_time(n)
    x = rng.uniform(0.0001, 0.001, n)

    day_bars, week_bars, month_bars = 4, 28, 120
    day = vm._causal_window_mean(x, close_time, vm._MS_PER_DAY)
    week = vm._causal_window_mean(x, close_time, vm._MS_PER_WEEK)
    month = vm._causal_window_mean(x, close_time, vm._MS_PER_MONTH)

    for t in (day_bars, day_bars + 1, 150, 399):
        assert day[t] == pytest.approx(np.mean(x[t - day_bars : t]))
    for t in (week_bars, week_bars + 5, 200, 399):
        assert week[t] == pytest.approx(np.mean(x[t - week_bars : t]))
    for t in (month_bars, month_bars + 3, 399):
        assert month[t] == pytest.approx(np.mean(x[t - month_bars : t]))


def test_causal_window_mean_relogio_uniforme_warmup_usa_dado_parcial_nao_nan() -> None:
    # Diferença INTENCIONAL vs o desenho antigo por-contagem-de-barra: o
    # antigo exigia a janela inteira preenchida (`window_n == window`)
    # antes de sair do NaN de warmup; o novo usa o que existir assim que
    # existir >=1 observação -- só documentada aqui pra não ser confundida
    # com regressão de bit-exatidão (que vale só na região "cheia").
    n = 10
    close_time = _uniform_close_time(n)
    x = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0])

    day = vm._causal_window_mean(x, close_time, vm._MS_PER_DAY)  # janela = 4 barras

    assert np.isnan(day[0])
    assert day[1] == pytest.approx(10.0)  # so x[0] disponível (janela parcial, 1/4)
    assert day[2] == pytest.approx(15.0)  # x[0],x[1] (2/4)
    assert day[3] == pytest.approx(20.0)  # x[0],x[1],x[2] (3/4)
    assert day[4] == pytest.approx(25.0)  # janela fechada (4/4) -- bit-exato ao antigo


def test_causal_window_mean_nan_em_x_nao_entra_na_media() -> None:
    # Gap 1 de revisão independente (project_assurance, 2026-08-17): nenhum
    # teste exercitava NaN dentro de `x` (só em `close_time`), apesar da
    # função ter lógica dedicada (`valid = np.isfinite(x)`, soma/contagem
    # separadas) -- central pra robustez sob dollar bar real (AG-061:
    # rajadas/silêncio de mercado produzem gaps reais de dado). NaN no meio
    # da janela é excluído da média, não vira NaN contaminante nem 0
    # espúrio.
    x = np.array([1.0, np.nan, 3.0, 5.0])
    close_time = np.array([0, 10, 20, 30], dtype=np.int64)
    window_ms = 100  # cobre tudo -- so a causalidade filtra

    out = vm._causal_window_mean(x, close_time, window_ms)

    assert np.isnan(out[0])  # janela vazia
    assert out[1] == pytest.approx(1.0)  # so x[0] (válido)
    assert out[2] == pytest.approx(1.0)  # x[0] válido, x[1]=NaN excluído -- não (1+NaN)/2
    assert out[3] == pytest.approx(2.0)  # x[0],x[2] válidos = (1+3)/2, x[1]=NaN excluído


def test_causal_window_mean_inf_em_x_propaga_nao_e_engolido() -> None:
    # Inf É finito=False (np.isfinite(inf) é False) -- mesma exclusão de
    # NaN, não um caso à parte silenciosamente diferente. Confirma que
    # `Inf` não entra na média (excluído, não produz Inf/NaN espúrio na
    # saída) e não é tratado como "válido" por engano.
    x = np.array([1.0, np.inf, 3.0])
    close_time = np.array([0, 10, 20], dtype=np.int64)
    window_ms = 100

    out = vm._causal_window_mean(x, close_time, window_ms)

    assert out[1] == pytest.approx(1.0)  # so x[0] válido, Inf excluído
    assert out[2] == pytest.approx(1.0)  # x[0] válido; Inf continua excluído, não contamina


# ============================================================================
# `_har_components`
# ============================================================================


def test_har_components_nunca_usa_realized_var_no_proprio_indice() -> None:
    # Perturbar realized_var[t] não pode mudar day[t]/week[t]/month[t] --
    # só pode mudar componentes em índices > t (janelas futuras que
    # incluem t no lookback causal).
    rng = np.random.default_rng(5)
    n = 400
    realized_var = rng.uniform(0.0001, 0.001, n)
    close_time = _uniform_close_time(n)

    day_a, week_a, month_a = vm._har_components(realized_var, close_time=close_time)

    perturbed = realized_var.copy()
    t = 200
    perturbed[t] = 999.0  # valor absurdo, se vazasse pra day[t] o teste pegaria
    day_b, week_b, month_b = vm._har_components(perturbed, close_time=close_time)

    assert day_a[t] == pytest.approx(day_b[t])
    assert week_a[t] == pytest.approx(week_b[t])
    assert month_a[t] == pytest.approx(month_b[t])
    # índices > t DEVEM mudar (t entra no lookback causal deles)
    assert day_a[t + 1] != pytest.approx(day_b[t + 1])


# ============================================================================
# `fit_har_rv` / `predict_har_rv` / `HARRVFit`
# ============================================================================


def test_fit_har_rv_dado_insuficiente_retorna_none() -> None:
    realized_var = np.full(5, 0.0005)
    close_time = _uniform_close_time(5)
    fit = vm.fit_har_rv(realized_var, close_time=close_time, train_end_idx=5)
    assert fit is None


def test_fit_e_predict_har_rv_serie_constante_reproduz_o_valor() -> None:
    # realized_var constante -> day=week=month=constante uma vez há
    # qualquer dado -> fit+predict devem reproduzir a mesma constante
    # (regressores perfeitamente colineares, mas qualquer solução OLS
    # válida satisfaz intercept + (beta_day+beta_week+beta_month)*c == c
    # exatamente).
    n = 400
    const = 0.0004
    realized_var = np.full(n, const)
    close_time = _uniform_close_time(n)

    fit = vm.fit_har_rv(realized_var, close_time=close_time, train_end_idx=n)
    assert fit is not None
    assert fit.n_train > 0

    forecast = vm.predict_har_rv(fit, realized_var, close_time=close_time)
    tail = forecast[50:]  # bem além do warmup
    valid = tail[~np.isnan(tail)]
    assert valid.size > 0
    assert np.allclose(valid, const, rtol=1e-6)


def test_fit_har_rv_causal_treino_nao_ve_teste() -> None:
    # Ajuste sobre [0, train_end_idx) não pode mudar se dado ALÉM de
    # train_end_idx for alterado.
    rng = np.random.default_rng(9)
    n = 500
    realized_var = rng.uniform(0.0001, 0.001, n)
    close_time = _uniform_close_time(n)
    train_end_idx = 300

    fit_a = vm.fit_har_rv(realized_var, close_time=close_time, train_end_idx=train_end_idx)
    perturbed = realized_var.copy()
    perturbed[train_end_idx:] = 999.0  # todo o "futuro" (fora do treino) vira absurdo
    fit_b = vm.fit_har_rv(perturbed, close_time=close_time, train_end_idx=train_end_idx)

    assert fit_a is not None and fit_b is not None
    assert fit_a.intercept == pytest.approx(fit_b.intercept)
    assert fit_a.beta_day == pytest.approx(fit_b.beta_day)
    assert fit_a.beta_week == pytest.approx(fit_b.beta_week)
    assert fit_a.beta_month == pytest.approx(fit_b.beta_month)


def test_fit_har_rv_preserva_correcao_f1_exclui_alvo_dependente_da_1a_barra_de_teste() -> None:
    # Regressão da correção F1 (achado original de auditoria, 2026-08-11,
    # preservada intacta nesta readaptação): realized_var[t] = r_{t+1}^2,
    # então realized_var[train_end_idx-1] depende de close[train_end_idx]
    # -- a 1a barra de TESTE. `fit_end_idx = train_end_idx - 1` (exclusive)
    # precisa excluir esse ponto específico do treino -- perturbar SÓ ele
    # não pode mudar o fit. Se a correção regredisse pra
    # `fit_end_idx = train_end_idx`, este teste pegaria.
    rng = np.random.default_rng(13)
    n = 500
    realized_var = rng.uniform(0.0001, 0.001, n)
    close_time = _uniform_close_time(n)
    train_end_idx = 300

    fit_a = vm.fit_har_rv(realized_var, close_time=close_time, train_end_idx=train_end_idx)
    perturbed = realized_var.copy()
    perturbed[train_end_idx - 1] = 999.0  # só o ponto que F1 deve excluir do alvo
    fit_b = vm.fit_har_rv(perturbed, close_time=close_time, train_end_idx=train_end_idx)

    assert fit_a is not None and fit_b is not None
    assert fit_a.intercept == pytest.approx(fit_b.intercept)
    assert fit_a.beta_day == pytest.approx(fit_b.beta_day)
    assert fit_a.beta_week == pytest.approx(fit_b.beta_week)
    assert fit_a.beta_month == pytest.approx(fit_b.beta_month)
    assert fit_a.n_train == fit_b.n_train


def test_predict_har_rv_forecast_nao_positivo_vira_nan() -> None:
    fit = vm.HARRVFit(intercept=-1.0, beta_day=0.0, beta_week=0.0, beta_month=0.0, n_train=100)
    n = 200
    realized_var = np.full(n, 0.0005)
    close_time = _uniform_close_time(n)
    forecast = vm.predict_har_rv(fit, realized_var, close_time=close_time)
    valid_region = forecast[1:]  # a partir de t=1 já há dado suficiente (warmup rápido por design)
    assert valid_region.size > 0
    assert np.all(np.isnan(valid_region))
