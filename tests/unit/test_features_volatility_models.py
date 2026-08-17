"""Testes de `src/features/volatility_models.py` -- HAR-RV (Corsi 2009) +
EGARCH(1,1) acoplado (Nelson 1991 + extensão por analogia a Ghysels &
Jasiak 1998), PRD_V4_1.md §3.2 M1, readaptados pra dollar bar (`AG-036`,
`audit/architecture_gaps_log.yaml`, addendums de 2026-08-17). Base HAR-RV
portada de `git show 50dd621:tests/unit/test_features_volatility_models.py`
(estado antes da remoção em `2436b33`) -- toda referência a `bars_per_day`
virou `close_time`, mesma mudança do módulo sob teste.

Eixos HAR-RV: causalidade dos regressores (dia/semana/mês nunca usam
`realized_var[t]`/dado com `close_time >= close_time[t]` pra prever
`realized_var[t]`), fit/predict end-to-end sobre série sintética conhecida,
dado insuficiente, forecast não-positivo virando NaN, preservação da
correção F1 (vazamento de 1 barra), e os 4 eixos NOVOS da readaptação pra
relógio real: janela sob relógio irregular, `close_time` duplicado
(rajada, `AG-061`), poucas observações dentro da janela (regime de baixa
atividade), e bit-exatidão contra o comportamento antigo por-contagem-de-
barra quando o relógio É de fato uniforme (grade de tempo).

Eixos EGARCH acoplado (bloco no final do arquivo): bit-exatidão da RECURSÃO
(`_egarch_log_var_recursion_coupled`) sob relógio uniforme (`tau≡1`) contra
uma versão ORACLE portada de `git show 50dd621` (mesmo padrão de prova de
retrocompatibilidade que HAR-RV já fez), direção do efeito sob `tau`
variável (barra de duração longa reverte mais rápido -- não só "roda sem
erro"), tratamento de `result.success=False`/dado insuficiente/`psi_bar`
inválido (retorna `None`, nunca coeficiente de otimização falha), e
forecast inválido explicitamente marcado NaN."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import optimize as scipy_optimize

from src.features import acd
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


# ============================================================================
# EGARCH(1,1) ACOPLADO -- ver docstring do módulo (topo deste arquivo) e de
# `volatility_models.py` pro desenho completo/decisões.
# ============================================================================

_EGARCH_ORACLE_LOG_VAR_CLIP = 50.0
_EGARCH_ORACLE_SQRT_2_OVER_PI = float(np.sqrt(2.0 / np.pi))


def _oracle_egarch_log_var_recursion(
    log_return: vm.FloatArray,
    *,
    omega: float,
    alpha: float,
    beta: float,
    gamma: float,
    log_var_seed: float,
) -> vm.FloatArray:
    """Portada de `git show 50dd621:src/features/volatility_models.py`
    (`_egarch_log_var_recursion`, ANTES do acoplamento) -- usada só como
    ORACLE de bit-exatidão contra `_egarch_log_var_recursion_coupled` sob
    relógio uniforme (`tau≡1`). Nunca importada em produção -- o módulo
    real não reintroduz o nome sem sufixo `_coupled` (ver docstring do
    módulo)."""
    n = log_return.shape[0]
    log_var = np.full(n, np.nan, dtype=np.float64)
    first_valid = 0
    while first_valid < n and np.isnan(log_return[first_valid]):
        first_valid += 1
    if first_valid >= n:
        return log_var
    log_var[first_valid] = log_var_seed
    for t in range(first_valid, n - 1):
        lv = log_var[t]
        if not np.isfinite(lv):
            break
        sigma_t = float(np.sqrt(np.exp(min(lv, _EGARCH_ORACLE_LOG_VAR_CLIP))))
        eps_t = log_return[t]
        if np.isnan(eps_t) or sigma_t <= 0.0:
            log_var[t + 1] = lv
            continue
        z_t = eps_t / sigma_t
        next_lv = (
            omega + beta * lv + alpha * (abs(z_t) - _EGARCH_ORACLE_SQRT_2_OVER_PI) + gamma * z_t
        )
        log_var[t + 1] = next_lv if np.isfinite(next_lv) else np.nan
    return log_var


def _oracle_predict_egarch(
    log_return: vm.FloatArray,
    *,
    omega: float,
    alpha: float,
    beta: float,
    gamma: float,
    log_var_seed: float,
) -> vm.FloatArray:
    """Equivalente ORACLE de `predict_egarch` (git show `50dd621`) -- só
    pra comparação de bit-exatidão, mesma ressalva de
    `_oracle_egarch_log_var_recursion`."""
    log_var = _oracle_egarch_log_var_recursion(
        log_return, omega=omega, alpha=alpha, beta=beta, gamma=gamma, log_var_seed=log_var_seed
    )
    n = log_return.shape[0]
    forecast_var = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        with np.errstate(over="ignore", invalid="ignore"):
            forecast_var[:-1] = np.exp(
                np.clip(log_var[1:], -_EGARCH_ORACLE_LOG_VAR_CLIP, _EGARCH_ORACLE_LOG_VAR_CLIP)
            )
    return forecast_var


def test_egarch_log_var_recursion_coupled_relogio_uniforme_bit_exato_vs_original() -> None:
    # Teste MAIS IMPORTANTE desta parte (mesma prova de retrocompatibilidade
    # que HAR-RV já fez): sob tau≡1 pra todo t (psi_i≡psi_bar), a recursão
    # acoplada precisa reproduzir bit-a-bit a recursão original (oracle
    # portada acima). `beta` NEGATIVO usado deliberadamente -- prova que a
    # bit-exatidão vale em qualquer domínio de beta quando o expoente é
    # exatamente 1.0 (nunca cai no ramo de potência fracionária/complexa,
    # ver docstring do módulo sobre o bound do OTIMIZADOR ser mais estreito
    # que a RECURSÃO em si).
    rng = np.random.default_rng(21)
    n = 300
    log_return = rng.normal(0.0, 0.01, n)
    omega, alpha, beta, gamma, log_var_seed = -0.3, 0.15, -0.5, 0.05, -8.0
    psi_uniform = np.full(n, 7.0)  # qualquer constante >0 -- psi_bar sai igual, tau=1 sempre

    oracle = _oracle_egarch_log_var_recursion(
        log_return, omega=omega, alpha=alpha, beta=beta, gamma=gamma, log_var_seed=log_var_seed
    )
    coupled = vm._egarch_log_var_recursion_coupled(
        log_return,
        omega=omega,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        log_var_seed=log_var_seed,
        psi=psi_uniform,
        psi_bar=7.0,
    )

    assert np.allclose(coupled, oracle, equal_nan=True)


def test_predict_egarch_coupled_relogio_uniforme_bit_exato_vs_oracle_predict() -> None:
    rng = np.random.default_rng(22)
    n = 250
    log_return = rng.normal(0.0, 0.01, n)
    omega, alpha, beta, gamma, log_var_seed = -0.2, 0.1, 0.85, -0.05, -7.5
    psi_uniform = np.full(n, 3.0)

    oracle_forecast = _oracle_predict_egarch(
        log_return, omega=omega, alpha=alpha, beta=beta, gamma=gamma, log_var_seed=log_var_seed
    )
    fit = vm.EGARCHCoupledFit(
        omega=omega,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        log_var_seed=log_var_seed,
        psi_bar=3.0,
        n_train=n,
    )
    coupled_forecast = vm.predict_egarch_coupled(fit, log_return, psi_uniform)

    assert np.allclose(coupled_forecast, oracle_forecast, equal_nan=True)


def test_egarch_log_var_recursion_coupled_duracao_longa_reverte_mais_rapido() -> None:
    # Propriedade de sanidade (spec): duração relativa MAIOR (tau>1) ->
    # beta**tau MENOR (0<beta<1) -> reversão à média mais rápida. Isola o
    # termo de persistência (alpha=gamma=0, o valor de log_return não entra
    # na conta) e confere as 3 trajetórias contra a fórmula fechada
    # next_lv = omega + beta**tau * lv -- não é só "roda sem erro".
    log_return = np.array([0.01, 0.01, 0.01])
    omega, beta, log_var_seed = -2.0, 0.8, 5.0
    psi_bar = 10.0

    def _log_var_1_para_tau(tau: float) -> float:
        psi = np.array([psi_bar * tau, np.nan, np.nan])
        log_var = vm._egarch_log_var_recursion_coupled(
            log_return, omega=omega, alpha=0.0, beta=beta, gamma=0.0,
            log_var_seed=log_var_seed, psi=psi, psi_bar=psi_bar,
        )
        return float(log_var[1])

    lv_short = _log_var_1_para_tau(0.5)  # duração curta -- tau<1
    lv_baseline = _log_var_1_para_tau(1.0)  # relógio uniforme -- tau=1
    lv_long = _log_var_1_para_tau(2.0)  # duração longa -- tau>1

    assert lv_short == pytest.approx(omega + beta**0.5 * log_var_seed)
    assert lv_baseline == pytest.approx(omega + beta**1.0 * log_var_seed)
    assert lv_long == pytest.approx(omega + beta**2.0 * log_var_seed)

    # Distância até omega (o termo pra onde a recursão reverte, isolado de
    # choque) DIMINUI com tau maior -- reversão mais rápida, auditável.
    dist_short = abs(lv_short - omega)
    dist_baseline = abs(lv_baseline - omega)
    dist_long = abs(lv_long - omega)
    assert dist_long < dist_baseline < dist_short


def test_egarch_log_var_recursion_coupled_psi_nan_usa_tau_1_warmup() -> None:
    # psi[t] NaN (warmup/indisponível) -> tau_t=1.0, reduz à recursão
    # original NESSA barra especificamente -- sem precisar de tau≡1 na
    # série inteira.
    log_return = np.array([0.01, 0.01, 0.01])
    omega, alpha, beta, gamma, log_var_seed = -1.0, 0.1, 0.9, 0.02, -6.0
    psi_bar = 5.0
    psi_com_nan = np.array([np.nan, np.nan, np.nan])

    oracle = _oracle_egarch_log_var_recursion(
        log_return, omega=omega, alpha=alpha, beta=beta, gamma=gamma, log_var_seed=log_var_seed
    )
    coupled = vm._egarch_log_var_recursion_coupled(
        log_return, omega=omega, alpha=alpha, beta=beta, gamma=gamma,
        log_var_seed=log_var_seed, psi=psi_com_nan, psi_bar=psi_bar,
    )
    assert np.allclose(coupled, oracle, equal_nan=True)


def test_egarch_log_var_recursion_coupled_psi_shape_mismatch_levanta_valueerror() -> None:
    log_return = np.full(100, 0.001)
    psi = np.full(50, 1.0)
    with pytest.raises(ValueError, match=r"psi\.shape"):
        vm._egarch_log_var_recursion_coupled(
            log_return,
            omega=-1.0,
            alpha=0.1,
            beta=0.9,
            gamma=0.0,
            log_var_seed=-5.0,
            psi=psi,
            psi_bar=1.0,
        )


def test_fit_egarch_coupled_dado_insuficiente_retorna_none() -> None:
    n = 10
    log_return = np.full(n, 0.001)
    psi = np.full(n, 1.0)
    fit = vm.fit_egarch_coupled(log_return, psi, train_end_idx=n)
    assert fit is None


def test_fit_egarch_coupled_psi_bar_invalido_retorna_none() -> None:
    # Nenhum psi válido (finito) dentro do treino -- psi_bar não computável.
    rng = np.random.default_rng(23)
    n = 200
    log_return = rng.normal(0.0, 0.01, n)
    psi = np.full(n, np.nan)
    fit = vm.fit_egarch_coupled(log_return, psi, train_end_idx=n)
    assert fit is None


def test_fit_egarch_coupled_shape_mismatch_psi_levanta_valueerror() -> None:
    log_return = np.full(100, 0.001)
    psi = np.full(50, 1.0)
    with pytest.raises(ValueError, match=r"psi\.shape"):
        vm.fit_egarch_coupled(log_return, psi, train_end_idx=100)


def test_predict_egarch_coupled_shape_mismatch_psi_levanta_valueerror() -> None:
    fit = vm.EGARCHCoupledFit(
        omega=-1.0, alpha=0.1, beta=0.9, gamma=0.0, log_var_seed=-5.0, psi_bar=1.0, n_train=100
    )
    log_return = np.full(100, 0.001)
    psi = np.full(50, 1.0)
    with pytest.raises(ValueError, match=r"psi\.shape"):
        vm.predict_egarch_coupled(fit, log_return, psi)


class _FakeFailedOptimizeResult:
    """Dublê de `scipy.optimize.OptimizeResult` -- `result.success=False`
    é lido ANTES de `result.x` (curto-circuito de `or`), então `.x` nunca
    precisa ser um array real pra este teste."""

    success = False
    x = np.zeros(4)


def test_fit_egarch_coupled_otimizador_nao_converge_retorna_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_minimize(*_args: object, **_kwargs: object) -> _FakeFailedOptimizeResult:
        return _FakeFailedOptimizeResult()

    # `vm.py` faz `from scipy import optimize` -- o nome `optimize` lá é o
    # MESMO objeto módulo que `scipy_optimize` aqui (`sys.modules['scipy.
    # optimize']`), não uma cópia -- monkeypatch aqui afeta a chamada real
    # dentro de `fit_egarch_coupled`. Patchear via `scipy_optimize` (import
    # direto neste arquivo) em vez de `vm.optimize` evita mypy strict
    # reclamar de "does not explicitly export attribute" (reexport
    # implícito de um import de terceiro em `vm`, não um símbolo do
    # próprio módulo).
    monkeypatch.setattr(scipy_optimize, "minimize", _fake_minimize)

    rng = np.random.default_rng(24)
    n = 200
    log_return = rng.normal(0.0, 0.01, n)
    psi = np.full(n, 1.0)
    fit = vm.fit_egarch_coupled(log_return, psi, train_end_idx=n)
    assert fit is None


def test_predict_egarch_coupled_serie_toda_nan_forecast_todo_nan_explicito() -> None:
    # log_return inteiro NaN -- first_valid nunca é encontrado, log_var
    # fica todo NaN por construção -- forecast precisa refletir isso
    # explicitamente (NaN), não erro nem valor espúrio.
    n = 10
    log_return = np.full(n, np.nan)
    psi = np.full(n, 1.0)
    fit = vm.EGARCHCoupledFit(
        omega=-1.0, alpha=0.1, beta=0.9, gamma=0.0, log_var_seed=-5.0, psi_bar=1.0, n_train=100
    )
    forecast = vm.predict_egarch_coupled(fit, log_return, psi)
    assert forecast.shape == (n,)
    assert np.all(np.isnan(forecast))


@pytest.mark.slow
def test_fit_e_predict_egarch_coupled_converge_e_produz_forecast_positivo_serie_real() -> None:
    # Caminho feliz end-to-end: log_return tipo-GARCH (heterocedástico) +
    # psi sintético (duração positiva, mediana != média -- cauda leve
    # propositalmente assimétrica, sem depender de src.features.acd pra
    # manter este arquivo de teste autocontido) -- fit converge, forecast
    # sai positivo e finito na região com dado suficiente.
    rng = np.random.default_rng(25)
    n = 400
    true_sigma = np.empty(n, dtype=np.float64)
    true_sigma[0] = 0.01
    log_return = np.empty(n, dtype=np.float64)
    log_return[0] = rng.normal(0.0, true_sigma[0])
    for t in range(1, n):
        true_sigma[t] = 0.3 * true_sigma[t - 1] + 0.005 + 0.05 * abs(log_return[t - 1])
        log_return[t] = rng.normal(0.0, true_sigma[t])
    psi = np.abs(rng.normal(500.0, 150.0, n)) + 50.0  # sempre positivo, cauda leve

    fit = vm.fit_egarch_coupled(log_return, psi, train_end_idx=n)
    assert fit is not None
    assert fit.n_train == n
    assert fit.psi_bar > 0.0

    forecast = vm.predict_egarch_coupled(fit, log_return, psi)
    tail = forecast[50:-1]  # além do warmup, exclui a última posição (sempre NaN por construção)
    valid = tail[np.isfinite(tail)]
    assert valid.size > 0
    assert np.all(valid > 0.0)


# ============================================================================
# Integração real acd.predict_acd -> fit_egarch_coupled/predict_egarch_coupled
# (achado MEDIUM de project_assurance, 2026-08-17: nenhum teste ligava os 2
# módulos de verdade -- todos os testes acima constroem `psi` à mão)
# ============================================================================


def _synthetic_close_time_irregular(n: int, *, rng: np.random.Generator) -> vm.IntArray:
    # Durações log-normais (sempre positivas, cauda direita) -- relógio
    # genuinamente NÃO-uniforme, mesmo espírito de AG-061 (duração real de
    # dollar bar é fortemente assimétrica), sem depender de dado real do
    # disco (arquivo de teste autocontido).
    durations = rng.lognormal(mean=6.0, sigma=0.5, size=n - 1)  # ~400ms típico
    close_time: vm.IntArray = np.concatenate(
        ([0], np.cumsum(durations))
    ).astype(np.int64)
    return close_time


def test_acd_predict_integra_com_egarch_coupled_end_to_end() -> None:
    # Prova de integração real (não `psi` construído à mão): close_time
    # sintético irregular -> acd.fit_acd/predict_acd -> psi real ->
    # fit_egarch_coupled/predict_egarch_coupled. Fecha o gap de
    # project_assurance -- os 2 módulos rodando juntos de verdade, não só
    # cada um isolado.
    rng = np.random.default_rng(77)
    n = 200
    close_time = _synthetic_close_time_irregular(n, rng=rng)

    true_sigma = np.empty(n, dtype=np.float64)
    true_sigma[0] = 0.01
    log_return = np.empty(n, dtype=np.float64)
    log_return[0] = rng.normal(0.0, true_sigma[0])
    for t in range(1, n):
        true_sigma[t] = 0.3 * true_sigma[t - 1] + 0.005 + 0.05 * abs(log_return[t - 1])
        log_return[t] = rng.normal(0.0, true_sigma[t])

    acd_fit = acd.fit_acd(close_time, train_end_idx=n)
    assert acd_fit is not None
    psi = acd.predict_acd(acd_fit, close_time)
    assert psi.shape[0] == n

    egarch_fit = vm.fit_egarch_coupled(log_return, psi, train_end_idx=n)
    assert egarch_fit is not None
    assert egarch_fit.psi_bar > 0.0

    forecast = vm.predict_egarch_coupled(egarch_fit, log_return, psi)
    tail = forecast[50:-1]
    valid = tail[np.isfinite(tail)]
    assert valid.size > 0
    assert np.all(valid > 0.0)


def test_egarch_coupled_causal_perturbar_futuro_via_acd_nao_muda_passado() -> None:
    # Prova de causalidade PONTA A PONTA (achado de project_assurance --
    # a causalidade de psi[t] havia sido só verificada por leitura de
    # código, nunca por teste executável ligando os 2 módulos): perturbar
    # close_time/log_return estritamente DEPOIS de t_check não pode mudar
    # log_var[t_check+1].
    #
    # `fit_acd`/`fit_egarch_coupled` rodam com `train_end_idx=t_check+1`
    # -- IDÊNTICO nos dois cenários (só o prefixo comum, não-perturbado,
    # entra no MLE) -- de propósito: se o fit usasse a série inteira já
    # perturbada, os COEFICIENTES ajustados divergiriam entre os 2
    # cenários só por causa de dado de treino diferente, o que
    # contaminaria a comparação (log_var[t_check+1] mudaria mesmo com
    # recursão perfeitamente causal, por parâmetro diferente, não por
    # vazamento). Isolando o fit ao prefixo comum, qualquer diferença em
    # log_var[t_check+1] só pode vir da RECURSÃO enxergando o futuro.
    rng = np.random.default_rng(99)
    n = 200
    t_check = 120  # bem depois do warmup (_ACD_MIN_TRAIN_OBS=50, _EGARCH_MIN_TRAIN_OBS=50)

    close_time_a = _synthetic_close_time_irregular(n, rng=rng)
    log_return_a = rng.normal(0.0, 0.01, n)

    acd_fit = acd.fit_acd(close_time_a, train_end_idx=t_check + 1)
    assert acd_fit is not None
    psi_prefix = acd.predict_acd(acd_fit, close_time_a[: t_check + 1])
    egarch_fit = vm.fit_egarch_coupled(
        log_return_a[: t_check + 1], psi_prefix, train_end_idx=t_check + 1
    )
    assert egarch_fit is not None

    def _log_var_at_t_check_plus_1(
        close_time: vm.IntArray, log_return: vm.FloatArray
    ) -> float:
        assert acd_fit is not None
        assert egarch_fit is not None
        psi_full = acd.predict_acd(acd_fit, close_time)
        log_var = vm._egarch_log_var_recursion_coupled(
            log_return,
            omega=egarch_fit.omega,
            alpha=egarch_fit.alpha,
            beta=egarch_fit.beta,
            gamma=egarch_fit.gamma,
            log_var_seed=egarch_fit.log_var_seed,
            psi=psi_full,
            psi_bar=egarch_fit.psi_bar,
        )
        return float(log_var[t_check + 1])

    log_var_a = _log_var_at_t_check_plus_1(close_time_a, log_return_a)

    # Perturba close_time E log_return estritamente DEPOIS de t_check --
    # durações futuras bem maiores (rajada de baixíssima atividade) e
    # retornos futuros bem maiores em módulo, ambos deliberadamente
    # extremos pra qualquer vazamento aparecer com folga, não sutil.
    close_time_b = close_time_a.copy()
    tail_durations = np.diff(close_time_b[t_check + 1 :]).astype(np.int64)
    close_time_b[t_check + 1 :] = close_time_b[t_check] + np.cumsum(
        np.concatenate(([1], tail_durations * 50 + 10_000))
    )[: n - (t_check + 1)]
    log_return_b = log_return_a.copy()
    log_return_b[t_check + 1 :] = rng.normal(0.0, 5.0, n - (t_check + 1))

    log_var_b = _log_var_at_t_check_plus_1(close_time_b, log_return_b)

    assert log_var_a == pytest.approx(log_var_b)
