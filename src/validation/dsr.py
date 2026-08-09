"""DSR/PSR (§11.6) — Deflated Sharpe Ratio (Bailey & López de Prado 2014,
"The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
Overfitting, and Non-Normality", Journal of Portfolio Management) sobre
Probabilistic Sharpe Ratio (Bailey & López de Prado 2012, "The Sharpe
Ratio Efficient Frontier"). Primeira implementação neste repo — §11.6 é
citado como pendente em `src/models/backtest_lite.py` ("sharpe_naive...
não corrigido... nem por DSR, ambos fora de escopo desta rodada") e em
`src/validation/__init__.py` ("DSR/PSR/PBO ainda não implementados").

**Escopo desta rodada (Faixa 2, pré-FASE 3, pedido do Manager
2026-08-09): só o suficiente para avaliar UMA configuração já medida
contra o `N_lifetime` auditado** — não o módulo formal completo do
Sprint 11 (PBO, integração com walk-forward, etc. ficam de fora,
deliberadamente, não esquecidos).

**Escala per-trade, não anualizada, na fórmula interna.** PSR/DSR são
derivados pelos autores para o Sharpe ratio NA MESMA frequência dos `T`
retornos passados — aqui, por-trade (cada trade é uma aposta discreta,
irregularmente espaçada, diferente de um portfólio diariamente
rebalanceado). Anualizar o SR antes de aplicar a fórmula mudaria a
escala de `T`/skew/kurtosis sem mudar a fórmula — erro de unidade.
`sr_annualized = sr_per_trade * sqrt(trades_per_year)` é reportado só
para leitura; a mesma transformação escala `sr0_per_trade` para
`sr0_annualized`, preservando a razão sr/sr0 — comparável, mas nunca
entra na conta interna de `expected_max_sharpe_under_n_trials`/
`probabilistic_sharpe_ratio` diretamente."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

FloatArray = NDArray[np.float64]

# Constante de Euler-Mascheroni (matemática, não de domínio) — Bailey &
# López de Prado (2014), eq. 5-6.
_EULER_MASCHERONI = 0.5772156649015329  # noqa: magic-number
_MIN_TRIALS = 2  # noqa: magic-number -- minimo pra Z^-1(1-1/N) fazer sentido
_MIN_OBS_FOR_MOMENTS = 4  # noqa: magic-number -- kurtosis amostral exige >=4 pontos
# `4.0` no denominador do termo de curtose -- literal da formula de PSR de
# Bailey & Lopez de Prado (2012, eq. 2), nao constante de dominio.
_PSR_KURTOSIS_TERM_DIVISOR = 4.0  # noqa: magic-number
# Expoente 3/2 na normalizacao de assimetria (skewness = m3/m2^1.5) --
# definicao matematica padrao (Fisher-Pearson), nao constante de dominio.
_SKEWNESS_POWER = 1.5  # noqa: magic-number
# Curtose Normal de referencia -- excess_kurtosis = kurtosis - 3, definicao
# matematica padrao, nao constante de dominio.
_NORMAL_KURTOSIS = 3.0  # noqa: magic-number


def expected_max_sharpe_under_n_trials(n_trials: int, sigma_sr: float) -> float:
    """`SR_0` — Bailey & López de Prado (2014), eq. 5-6 (aproximação de
    Euler-Mascheroni para o valor esperado do MÁXIMO de `n_trials`
    variáveis Normais i.i.d. de desvio-padrão `sigma_sr`):

        E[max_n SR_n] = sigma_sr * [(1-gamma)*Z^-1(1-1/N) + gamma*Z^-1(1-1/(N*e))]

    `sigma_sr` é o desvio-padrão dos Sharpe ratios ENTRE os `n_trials`
    trials — quando o histórico completo de cada trial não foi
    rastreado (nosso caso: `N_lifetime` audita CONTAGEM, não a
    distribuição de Sharpe de cada trial individual), o proxy padrão da
    literatura (usado no próprio exemplo numérico de López de Prado,
    "Advances in Financial Machine Learning", cap. 8) é o erro-padrão
    do PRÓPRIO Sharpe observado — ver `compute_dsr`."""
    if n_trials < _MIN_TRIALS:
        raise ValueError(
            f"expected_max_sharpe_under_n_trials: n_trials precisa ser >= {_MIN_TRIALS}"
        )
    z1 = float(norm.ppf(1.0 - 1.0 / n_trials))
    z2 = float(norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
    return sigma_sr * ((1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)


def sharpe_ratio_standard_error(
    sr: float, n_obs: int, skewness: float, excess_kurtosis: float
) -> float:
    """Erro-padrão do Sharpe ratio amostral (Bailey & López de Prado
    2012, eq. 2 — generalização de Lo 2002/Mertens 2002 para retornos
    não-Normais; `excess_kurtosis` = kurtosis - 3, 0 para Normal):

        SE(SR) = sqrt((1 - skew*SR + (excess_kurtosis/4)*SR**2) / (n_obs - 1))
    """
    if n_obs < _MIN_TRIALS:
        return float("nan")
    inside = 1.0 - skewness * sr + (excess_kurtosis / _PSR_KURTOSIS_TERM_DIVISOR) * sr**2
    if inside < 0:
        return float("nan")
    return math.sqrt(inside / (n_obs - 1))


def probabilistic_sharpe_ratio(
    sr_observed: float,
    sr_benchmark: float,
    n_obs: int,
    skewness: float,
    excess_kurtosis: float,
) -> float:
    """`PSR(SR*) = P(SR_verdadeiro > SR*)` — Bailey & López de Prado
    (2012), eq. 1:

        PSR(SR*) = Phi[ (SR_hat - SR*) / SE(SR_hat) ]

    `SE(SR_hat)` avaliado NO `sr_observed` (não no benchmark) — mesma
    convenção do artigo."""
    se_unit = sharpe_ratio_standard_error(sr_observed, n_obs, skewness, excess_kurtosis)
    if not math.isfinite(se_unit) or se_unit <= 0:
        return float("nan")
    z = (sr_observed - sr_benchmark) / se_unit
    return float(norm.cdf(z))


@dataclass(frozen=True, slots=True)
class DSRResult:
    n_trials: int
    n_obs: int
    trades_per_year: float
    sr_per_trade: float
    sr_annualized: float
    skewness: float
    excess_kurtosis: float
    sigma_sr_per_trade: float
    sr0_per_trade: float
    sr0_annualized: float
    dsr: float


def compute_dsr(returns: FloatArray, *, n_trials: int, trades_per_year: float) -> DSRResult:
    """`returns` — retornos POR TRADE (ex. `ret_net`), NÃO anualizados,
    NÃO agregados por dia. `n_trials` — `N_lifetime` auditado
    (`audit/n_lifetime.yaml::counter`), o número de apostas
    independentes já gastas neste projeto (não o `N` de uma busca
    isolada, CLAUDE.md).

    `sigma_sr` para `SR_0` = erro-padrão do PRÓPRIO Sharpe observado
    (`sharpe_ratio_standard_error`, escala per-trade) — proxy padrão
    quando a distribuição real de Sharpe dos `n_trials` trials não foi
    rastreada individualmente (ver docstring de
    `expected_max_sharpe_under_n_trials`)."""
    finite = returns[np.isfinite(returns)]
    n_obs = int(finite.shape[0])
    if n_obs < _MIN_OBS_FOR_MOMENTS:
        raise ValueError(f"compute_dsr: precisa de >= {_MIN_OBS_FOR_MOMENTS} retornos finitos")

    mean = float(np.mean(finite))
    std = float(np.std(finite, ddof=1))
    sr_per_trade = mean / std if std > 0 else float("nan")

    # Momentos amostrais (Fisher-Pearson padrão, viés de amostra pequena
    # não corrigido) -- n_obs desta rodada (milhares) torna o viés
    # desprezível frente à magnitude do efeito medido.
    centered = finite - mean
    m2 = float(np.mean(centered**2))
    m3 = float(np.mean(centered**3))
    m4 = float(np.mean(centered**4))
    skewness = m3 / m2**_SKEWNESS_POWER if m2 > 0 else float("nan")
    excess_kurtosis = (m4 / m2**2 - _NORMAL_KURTOSIS) if m2 > 0 else float("nan")

    sigma_sr = sharpe_ratio_standard_error(sr_per_trade, n_obs, skewness, excess_kurtosis)
    sr0_per_trade = expected_max_sharpe_under_n_trials(n_trials, sigma_sr)
    dsr = probabilistic_sharpe_ratio(sr_per_trade, sr0_per_trade, n_obs, skewness, excess_kurtosis)

    sqrt_tpy = math.sqrt(trades_per_year) if trades_per_year > 0 else float("nan")
    return DSRResult(
        n_trials=n_trials,
        n_obs=n_obs,
        trades_per_year=trades_per_year,
        sr_per_trade=sr_per_trade,
        sr_annualized=sr_per_trade * sqrt_tpy,
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
        sigma_sr_per_trade=sigma_sr,
        sr0_per_trade=sr0_per_trade,
        sr0_annualized=sr0_per_trade * sqrt_tpy,
        dsr=dsr,
    )


# Limiar convencional de DSR (Bailey & Lopez de Prado citam 0,95 como
# "estatisticamente significativo" no sentido usual de 1 desvio de
# confiança de 95% -- não é limiar de decisão de produção desta rodada,
# só a leitura direta do artigo, citada pelo Manager).
_DSR_CONVENTIONAL_THRESHOLD = 0.95  # noqa: magic-number


def dsr_passes_conventional_threshold(dsr: float) -> bool:
    return math.isfinite(dsr) and dsr >= _DSR_CONVENTIONAL_THRESHOLD


def _period_sharpe(returns: FloatArray) -> float:
    if returns.shape[0] < _MIN_TRIALS:
        return float("nan")
    std = float(np.std(returns, ddof=1))
    if std == 0.0:
        return float("nan")
    return float(np.mean(returns)) / std


def sharpe_difference_block_bootstrap(
    returns_a: FloatArray,
    returns_b: FloatArray,
    *,
    n_boot: int,
    block_size: int,
    seed: int,
) -> dict[str, float]:
    """Teste de diferença de Sharpe (`SR_a - SR_b`) por bootstrap em
    blocos sobre séries PAREADAS (mesmo eixo de tempo, mesmo
    comprimento) — evita depender de uma fórmula fechada de covariância
    (Jobson-Korkie/Memmel) reconstruída de memória; blocos preservam a
    autocorrelação serial que uma reamostragem i.i.d. quebraria, e
    reamostrar os PARES (não cada série isolada) preserva a correlação
    contemporânea entre as duas séries — o ponto central de um teste de
    diferença de Sharpe entre estratégias correlacionadas (mesmo ativo
    subjacente)."""
    if returns_a.shape[0] != returns_b.shape[0]:
        raise ValueError(
            "sharpe_difference_block_bootstrap: series precisam ter o mesmo comprimento"
        )
    n = returns_a.shape[0]
    if block_size > n:
        raise ValueError("sharpe_difference_block_bootstrap: block_size maior que a serie")
    rng = np.random.default_rng(seed)
    observed_diff = _period_sharpe(returns_a) - _period_sharpe(returns_b)

    n_blocks = math.ceil(n / block_size)
    diffs = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]
        diffs[i] = _period_sharpe(returns_a[idx]) - _period_sharpe(returns_b[idx])

    valid = diffs[np.isfinite(diffs)]
    if valid.size == 0 or not math.isfinite(observed_diff):
        return {
            "observed_diff": observed_diff,
            "bootstrap_mean_diff": float("nan"),
            "bootstrap_std_diff": float("nan"),
            "ci95_low": float("nan"),
            "ci95_high": float("nan"),
            "p_value_two_sided": float("nan"),
            "n_boot": n_boot,
            "block_size": block_size,
        }
    frac_le_zero = float(np.mean(valid <= 0.0))
    frac_ge_zero = float(np.mean(valid >= 0.0))
    p_two_sided = min(1.0, 2.0 * min(frac_le_zero, frac_ge_zero))
    ci_low, ci_high = np.percentile(valid, [2.5, 97.5])  # noqa: magic-number -- CI 95% padrao
    return {
        "observed_diff": observed_diff,
        "bootstrap_mean_diff": float(np.mean(valid)),
        "bootstrap_std_diff": float(np.std(valid)),
        "ci95_low": float(ci_low),
        "ci95_high": float(ci_high),
        "p_value_two_sided": p_two_sided,
        "n_boot": n_boot,
        "block_size": block_size,
    }
