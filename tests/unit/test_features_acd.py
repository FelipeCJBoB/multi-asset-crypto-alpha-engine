"""Testes de `src/features/acd.py` -- ACD(1,1) (Engle & Russell 1998) sobre
durações reais de `close_time`, 1ª metade do resgate "EGARCH acoplado"
(`AG-036`, `audit/architecture_gaps_log.yaml`, addendums de 2026-08-17).

Eixos cobertos: causalidade da recursão (`ψ[j]` nunca usa `x[j..]`),
recuperação aproximada de parâmetros conhecidos via MLE sobre série
sintética, dado insuficiente retorna `None`, duração zero (`AG-061`, rajada
real) não crasha, log-verossimilhança Weibull derivada à mão bate contra
`scipy.stats.weibull_min.logpdf`, validação de ordenação de `close_time`,
e convenção de índice/NaN de `predict_acd` (semente em `ψ[0]` mascarada,
cauda em `ψ[n-1]` sem duração definida).

**Nota de honestidade**: o teste de recuperação de parâmetros por MLE
(`test_fit_acd_recupera_parametros_aproximados_de_serie_sintetica_conhecida`)
não pôde ser executado nesta sessão (protocolo do repo -- só o usuário roda
`pytest`, CLAUDE.md "Protocolo de execução"). As tolerâncias foram
escolhidas deliberadamente generosas (MLE de 4 parâmetros sobre ruído
Weibull real tem variância amostral genuína) para minimizar o risco de
teste frágil não verificado por execução real -- reveja/aperte se rodar e
sobrar folga."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import special
from scipy.stats import weibull_min

from src.features import acd


def _close_time_from_durations(x: acd.IntArray) -> acd.IntArray:
    """`close_time[0]=0`, `close_time[j+1]=close_time[j]+x[j]` -- inverso de
    `_acd_durations`, usado pra construir cenários de teste a partir de uma
    sequência de durações desejada."""
    out: acd.IntArray = np.concatenate(([0], np.cumsum(x))).astype(np.int64)
    return out


# ============================================================================
# `_acd_psi_recursion` -- causalidade
# ============================================================================


def test_acd_psi_recursion_nunca_usa_duracao_no_proprio_indice() -> None:
    # Perturbar x[t] não pode mudar psi[t] (psi[t] usa só x[0..t-1]) -- só
    # psi[t+1] em diante pode mudar. Mesmo padrão de
    # test_har_components_nunca_usa_realized_var_no_proprio_indice.
    rng = np.random.default_rng(7)
    n = 200
    x = rng.uniform(1.0, 100.0, n)
    psi_seed = float(np.mean(x))

    psi_a = acd._acd_psi_recursion(x, omega=2.0, alpha=0.1, beta=0.8, psi_seed=psi_seed)

    perturbed = x.copy()
    t = 100
    perturbed[t] = 999_999.0  # valor absurdo -- se vazasse pra psi[t] o teste pegaria
    psi_b = acd._acd_psi_recursion(perturbed, omega=2.0, alpha=0.1, beta=0.8, psi_seed=psi_seed)

    assert psi_a[t] == pytest.approx(psi_b[t])
    # índice > t DEVE mudar (x[t] entra na recursão de psi[t+1])
    assert psi_a[t + 1] != pytest.approx(psi_b[t + 1])


def test_acd_psi_recursion_psi0_e_sempre_a_semente_fixa() -> None:
    x = np.array([1.0, 2.0, 3.0])
    psi = acd._acd_psi_recursion(x, omega=5.0, alpha=0.1, beta=0.5, psi_seed=42.0)
    assert psi[0] == pytest.approx(42.0)


def test_acd_psi_recursion_positiva_por_construcao_mesmo_com_x_zero() -> None:
    # AG-061: x[j]==0 é dado válido. omega>0, alpha,beta>=0, x>=0 -- psi[j]
    # >= omega > 0 sempre, por indução (ver docstring de _acd_psi_recursion).
    x = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
    psi = acd._acd_psi_recursion(x, omega=3.0, alpha=0.2, beta=0.7, psi_seed=10.0)
    assert np.all(np.isfinite(psi))
    assert np.all(psi > 0.0)


# ============================================================================
# `_acd_weibull_log_pdf` -- confere contra scipy.stats.weibull_min
# ============================================================================


def test_acd_weibull_log_pdf_bate_scipy_weibull_min_num_caso_concreto() -> None:
    psi = np.array([2.0, 5.0, 0.5])
    kappa = 1.7
    x = np.array([1.3, 4.0, 0.2])
    lam = psi / special.gamma(1.0 + 1.0 / kappa)

    got = acd._acd_weibull_log_pdf(x, psi, kappa)
    expected = weibull_min.logpdf(x, kappa, scale=lam)

    assert got == pytest.approx(expected, rel=1e-9)


def test_acd_weibull_log_pdf_x_zero_censurado_e_finito_qualquer_kappa() -> None:
    # Achado real (não hipotético): avaliar a Weibull no LIMITE matemático
    # exato em x=0 (-inf pra kappa>1, +inf pra kappa<1) trava o L-BFGS-B --
    # ver test_predict_acd_duracao_zero_no_meio_da_serie_nao_crasha_ag061.
    # x==0 é censura de quantização de timestamp (resolução 1ms), não zero
    # físico -- _acd_weibull_log_pdf floora pra _ACD_DURATION_FLOOR_MS antes
    # de avaliar, produzindo um valor FINITO pra qualquer kappa, não um
    # limite de fronteira.
    for kappa in (0.5, 1.0, 2.0):
        out = acd._acd_weibull_log_pdf(np.array([0.0]), np.array([5.0]), kappa=kappa)
        assert np.isfinite(out[0]), f"kappa={kappa}: esperado finito, achou {out[0]}"


def test_acd_weibull_log_pdf_x_zero_bate_avaliar_no_piso_de_censura_diretamente() -> None:
    # O floor é aplicado ANTES da fórmula -- avaliar em x=0 precisa bater
    # exatamente com avaliar em x=_ACD_DURATION_FLOOR_MS diretamente (não é
    # um valor especial calculado à parte, é a mesma fórmula sobre o dado
    # censurado).
    psi = np.array([5.0])
    kappa = 2.0
    out_zero = acd._acd_weibull_log_pdf(np.array([0.0]), psi, kappa=kappa)
    out_floor = acd._acd_weibull_log_pdf(np.array([acd._ACD_DURATION_FLOOR_MS]), psi, kappa=kappa)
    assert out_zero[0] == pytest.approx(out_floor[0])


def test_acd_weibull_log_pdf_x_nao_zero_nao_e_afetado_pelo_floor() -> None:
    # Durações reais (>=1ms, close_time é IntArray em ms -- x nunca é
    # fracionário exceto pelo floor de censura) precisam bater exatamente
    # contra scipy.stats.weibull_min, sem NENHUM efeito do floor -- só
    # x==0 é tocado.
    x = np.array([1.0, 50.0, 300.0])
    psi = np.array([5.0, 5.0, 5.0])
    kappa = 1.7
    lam = 5.0 / special.gamma(1.0 + 1.0 / kappa)
    expected = weibull_min.logpdf(x, kappa, scale=lam)
    out = acd._acd_weibull_log_pdf(x, psi, kappa=kappa)
    assert out == pytest.approx(expected)


# ============================================================================
# `fit_acd` / `predict_acd`
# ============================================================================


def test_fit_acd_dado_insuficiente_retorna_none() -> None:
    close_time = _close_time_from_durations(np.full(5, 100, dtype=np.int64))
    fit = acd.fit_acd(close_time, train_end_idx=close_time.shape[0])
    assert fit is None


@pytest.mark.slow
def test_fit_acd_recupera_parametros_aproximados_de_serie_sintetica_conhecida() -> None:
    rng = np.random.default_rng(2024)
    n = 3000
    true_omega, true_alpha, true_beta, true_kappa = 20.0, 0.15, 0.75, 1.3

    # Draws Weibull(kappa, scale=1) padrão gerados em bloco (vetorizado) --
    # x[j] = standard_draws[j] * lam[j] (propriedade de escala da Weibull:
    # U~Weibull(k,1) => lam*U~Weibull(k,lam)) evita 3000 chamadas
    # individuais de scipy.stats.rvs (custo de overhead por chamada real,
    # não do laço sequencial em si, que é inerente a testar fit_acd de
    # verdade -- ver marker @pytest.mark.slow acima).
    standard_draws = weibull_min.rvs(true_kappa, size=n, random_state=rng)

    x = np.empty(n, dtype=np.float64)
    psi_true = np.empty(n, dtype=np.float64)
    psi_true[0] = true_omega / (1.0 - true_alpha - true_beta)  # média estacionária
    gamma_term = special.gamma(1.0 + 1.0 / true_kappa)
    for j in range(n):
        if j > 0:
            psi_true[j] = true_omega + true_alpha * x[j - 1] + true_beta * psi_true[j - 1]
        lam = psi_true[j] / gamma_term
        x[j] = standard_draws[j] * lam

    x_int = np.maximum(np.round(x), 0.0).astype(np.int64)
    close_time = _close_time_from_durations(x_int)

    fit = acd.fit_acd(close_time, train_end_idx=close_time.shape[0])

    assert fit is not None
    # Tolerâncias generosas -- MLE de 4 parâmetros sobre ruído Weibull real,
    # não recuperação exata (ver nota de honestidade no topo do arquivo).
    assert fit.kappa == pytest.approx(true_kappa, abs=0.6)
    persistence_true = true_alpha + true_beta
    persistence_fit = fit.alpha + fit.beta
    assert persistence_fit == pytest.approx(persistence_true, abs=0.25)
    stationary_mean_true = true_omega / (1.0 - persistence_true)
    stationary_mean_fit = fit.omega / (1.0 - persistence_fit) if persistence_fit < 1.0 else np.nan
    assert np.isfinite(stationary_mean_fit)
    assert stationary_mean_fit == pytest.approx(stationary_mean_true, rel=0.5)


def test_predict_acd_duracao_zero_no_meio_da_serie_nao_crasha_ag061() -> None:
    rng = np.random.default_rng(3)
    n = 300
    x = rng.integers(50, 500, n).astype(np.int64)
    x[150:155] = 0  # rajada com close_time repetido, AG-061
    close_time = _close_time_from_durations(x)

    fit = acd.fit_acd(close_time, train_end_idx=close_time.shape[0])
    assert fit is not None

    psi = acd.predict_acd(fit, close_time)
    assert psi.shape[0] == close_time.shape[0]
    valid = psi[np.isfinite(psi)]
    assert valid.size > 0
    assert np.all(valid > 0.0)


def test_predict_acd_convencao_de_indice_psi0_e_psi_ultimo_sao_nan() -> None:
    # >= _ACD_MIN_TRAIN_OBS (50) durações -- 60 barras -> 59 durações.
    close_time = _close_time_from_durations(np.full(60, 100, dtype=np.int64))
    fit = acd.fit_acd(close_time, train_end_idx=close_time.shape[0])
    assert fit is not None

    psi = acd.predict_acd(fit, close_time)
    n = close_time.shape[0]
    assert np.isnan(psi[0])
    assert np.isnan(psi[n - 1])
    # posições centrais (1..n-2) devem ser finitas e positivas
    assert np.all(np.isfinite(psi[1 : n - 1]))
    assert np.all(psi[1 : n - 1] > 0.0)


def test_predict_acd_serie_curta_demais_para_posicao_central_so_nan() -> None:
    # n<3 -- nenhuma posição "central" (i=1..n-2) existe.
    close_time = np.array([0, 100], dtype=np.int64)
    fit = acd.ACDFit(omega=1.0, alpha=0.1, beta=0.5, kappa=1.0, psi_seed=100.0, n_train=50)
    psi = acd.predict_acd(fit, close_time)
    assert psi.shape == (2,)
    assert np.all(np.isnan(psi))


def test_fit_acd_close_time_fora_de_ordem_levanta_valueerror() -> None:
    close_time = np.array([0, 200, 100], dtype=np.int64)
    with pytest.raises(ValueError, match="ordenado ascendente"):
        acd.fit_acd(close_time, train_end_idx=3)


def test_predict_acd_close_time_fora_de_ordem_levanta_valueerror() -> None:
    fit = acd.ACDFit(omega=1.0, alpha=0.1, beta=0.5, kappa=1.0, psi_seed=10.0, n_train=50)
    close_time = np.array([0, 200, 100], dtype=np.int64)
    with pytest.raises(ValueError, match="ordenado ascendente"):
        acd.predict_acd(fit, close_time)
