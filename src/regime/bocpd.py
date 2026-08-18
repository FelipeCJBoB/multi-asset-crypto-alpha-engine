"""BOCPD vendorizado — M4 (`PRD_V4_1.md` §3.2), Adams & MacKay (2007),
"Bayesian Online Changepoint Detection". Sem lib PyPI madura/dominante
disponível (pesquisado — só implementações de referência de ~150-300
linhas, nenhuma com adoção comparável a `dynamax`/`jumpmodels`) — mesmo
precedente desta sessão de resgatar/readaptar métodos sem lib madura
(`src/features/acd.py`).

**Modelo:** verossimilhança Normal com média E variância desconhecidas,
prior conjugado Normal-Inverse-Gamma (NIG) — `μ|σ² ~ N(μ0, σ²/κ0)`,
`σ² ~ InvGamma(α0, β0)`. Ao integrar a variância desconhecida
analiticamente, a distribuição PREDITIVA marginal resultante já é
**Student-t** (não Gaussiana) — robustez a cauda pesada embutida no
próprio desenho, sem precisar de verossimilhança Student-t explícita.
Achado real de pesquisa (2026-08-17, antes de codar): mesmo com esse
tratamento, literatura recente mostra que BOCPD ainda perde precisão sob
dado GENUINAMENTE de cauda mais pesada que o Student-t implícito do NIG
consegue capturar — **limitação conhecida, documentada aqui, não
escondida**. Decisão do Manager: começar pela versão padrão (esta),
Student-t explícito fica pra iteração futura.

**Hazard constante** — `H(r) = 1/hazard_lambda` pra todo run-length `r`
(prior geométrico sobre duração de segmento, média = `hazard_lambda`
barras). Causal por construção: a probabilidade de mudança de regime em
`t` nunca depende de observação `> t`.

**Poda de hipótese de run-length** — sem poda, o algoritmo é O(T²)
(mantém uma hipótese por run-length possível, cresce 1/passo);
inviável sobre ~230k barras. Poda hipóteses cuja probabilidade posterior
cai abaixo de `prune_threshold` relativo ao máximo — prática padrão da
literatura de BOCPD (não uma simplificação inventada aqui), mantém custo
efetivo próximo de O(T) pra hazard/duração realistas."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.special import logsumexp
from scipy.stats import t as student_t

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

# Prior NIG "não-informativo" fraco -- média 0 (retorno esperado ~0 em
# horizonte de 1 barra), kappa0 baixo (pouca confiança na média a priori),
# alpha0/beta0 dando variância a priori modesta mas não zero. Não são
# constantes de domínio sujeitas a `constants.yaml`/proveniência (§16.10)
# -- são hiperparâmetros de PRIOR estatístico padrão da literatura de
# BOCPD (Adams & MacKay 2007, exemplo canônico), não um número de negócio
# do projeto.
_PRIOR_MU0 = 0.0
_PRIOR_KAPPA0 = 1.0
_PRIOR_ALPHA0 = 1.0
_PRIOR_BETA0 = 1.0
_DEFAULT_PRUNE_THRESHOLD = 1e-4


@dataclass(frozen=True, slots=True)
class BOCPDResult:
    """`changepoint_prob[t]` = probabilidade posterior de `run_length=0`
    em `t` (P(mudança de regime detectada nesta barra), não uma predição
    de mudança FUTURA). `map_run_length[t]` = run-length de maior
    probabilidade posterior em `t` (MAP, não a média). `segment_id[t]` =
    índice de segmento entre changepoints consecutivos (derivado de
    `map_run_length`, `0`-indexado, crescente)."""

    changepoint_prob: FloatArray
    map_run_length: IntArray
    segment_id: IntArray


def _log_predictive(
    x: float, mu: FloatArray, kappa: FloatArray, alpha: FloatArray, beta: FloatArray
) -> FloatArray:
    """Log-densidade preditiva Student-t, vetorizada sobre todas as
    hipóteses de run-length ativas. `df=2*alpha`, `loc=mu`,
    `scale=sqrt(beta*(kappa+1)/(alpha*kappa))` -- forma fechada padrão da
    marginal Normal-Inverse-Gamma (não citação de fórmula sem derivação:
    resultado padrão de conjugação NIG, ver Murphy 2007 "Conjugate
    Bayesian analysis of the Gaussian distribution", eq. 100)."""
    df = 2.0 * alpha
    scale = np.sqrt(beta * (kappa + 1.0) / (alpha * kappa))  # noqa: unguarded-ratio -- alpha/kappa partem de 1.0 (prior) e só crescem, nunca <=0
    result: FloatArray = np.asarray(student_t.logpdf(x, df=df, loc=mu, scale=scale))
    return result


def _update_sufficient_stats(
    x: float, mu: FloatArray, kappa: FloatArray, alpha: FloatArray, beta: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Atualização conjugada NIG posterior->prior da próxima observação,
    vetorizada sobre todas as hipóteses ativas (Murphy 2007, eq. 86-89)."""
    kappa_new = kappa + 1.0  # sempre >= 2.0 (kappa parte de 1.0, só cresce)
    mu_new = (kappa * mu + x) / kappa_new  # noqa: unguarded-ratio -- kappa_new>=2.0 acima
    alpha_new = alpha + 0.5
    beta_new = beta + (kappa * (x - mu) ** 2) / (2.0 * kappa_new)  # noqa: unguarded-ratio -- idem
    return mu_new, kappa_new, alpha_new, beta_new


def run_bocpd(
    obs: FloatArray, *, hazard_lambda: float, prune_threshold: float = _DEFAULT_PRUNE_THRESHOLD
) -> BOCPDResult:
    """Núcleo puro, sem IO. `obs` = série 1-D (univariado, `log_return_1`
    pro candidato de regime real — setup clássico de Adams & MacKay).
    `hazard_lambda` > 1 obrigatório (duração média de segmento em barras;
    `H = 1/hazard_lambda` precisa ficar em `(0, 1)`).

    Online/causal por construção: barra `t` só usa `obs[:t+1]` — não há
    passo de "fit em lote seguido de predição retroativa" (diferente de
    HMM/Jump Model, que refazem fit por fold de walk-forward, ver
    `PRD_V4_1.md` M4 item 1 do plano). Todo o array em log-espaço
    (log-sum-exp) por estabilidade numérica sobre séries longas."""
    if hazard_lambda <= 1.0:
        raise ValueError(f"run_bocpd: hazard_lambda precisa ser > 1, recebeu {hazard_lambda}")
    n = obs.shape[0]
    if n == 0:
        raise ValueError("run_bocpd: obs vazio")

    log_hazard = -np.log(hazard_lambda)
    log_one_minus_hazard = np.log1p(-1.0 / hazard_lambda)  # noqa: unguarded-ratio -- hazard_lambda>1 checado acima

    # Hipóteses ativas: arrays paralelos, índice = run-length atual.
    # Começa com só a hipótese r=0 (log-prob 1.0 = log 0.0) na barra 0.
    log_r = np.array([0.0])
    mu = np.array([_PRIOR_MU0])
    kappa = np.array([_PRIOR_KAPPA0])
    alpha = np.array([_PRIOR_ALPHA0])
    beta = np.array([_PRIOR_BETA0])

    changepoint_prob = np.empty(n, dtype=np.float64)
    map_run_length = np.empty(n, dtype=np.int64)

    for t in range(n):
        x = float(obs[t])
        log_pred = _log_predictive(x, mu, kappa, alpha, beta)

        log_joint = log_r + log_pred
        log_growth = log_joint + log_one_minus_hazard
        log_cp = logsumexp(log_joint + log_hazard)

        log_r_new = np.concatenate(([log_cp], log_growth))
        log_r_new -= logsumexp(log_r_new)  # normaliza

        mu_upd, kappa_upd, alpha_upd, beta_upd = _update_sufficient_stats(
            x, mu, kappa, alpha, beta
        )
        mu_new = np.concatenate(([_PRIOR_MU0], mu_upd))
        kappa_new = np.concatenate(([_PRIOR_KAPPA0], kappa_upd))
        alpha_new = np.concatenate(([_PRIOR_ALPHA0], alpha_upd))
        beta_new = np.concatenate(([_PRIOR_BETA0], beta_upd))

        # poda: mantém só hipóteses com prob relativa >= prune_threshold
        keep_mask = log_r_new >= (np.max(log_r_new) + np.log(prune_threshold))
        log_r = log_r_new[keep_mask]
        log_r -= logsumexp(log_r)  # renormaliza pós-poda
        mu = mu_new[keep_mask]
        kappa = kappa_new[keep_mask]
        alpha = alpha_new[keep_mask]
        beta = beta_new[keep_mask]

        changepoint_prob[t] = float(np.exp(log_r[0])) if keep_mask[0] else 0.0
        map_run_length[t] = int(np.argmax(log_r))

    segment_id = _segments_from_map_run_length(map_run_length)
    return BOCPDResult(
        changepoint_prob=changepoint_prob, map_run_length=map_run_length, segment_id=segment_id
    )


def _segments_from_map_run_length(map_run_length: IntArray) -> IntArray:
    """Novo segmento sempre que `map_run_length` reseta a 0 (changepoint
    MAP detectado) OU cai em relação à barra anterior sem chegar a 0
    (reatribuição de hipótese MAP entre run-lengths vizinhos, mais raro
    mas possível sob poda) -- ambos os casos tratados como fronteira de
    segmento, nunca um crescimento monotônico esperado quebrando
    silenciosamente em segmento novo."""
    n = map_run_length.shape[0]
    is_boundary = np.zeros(n, dtype=np.bool_)
    is_boundary[0] = True
    if n > 1:
        is_boundary[1:] = map_run_length[1:] <= map_run_length[:-1]
        # crescimento normal (run-length aumenta em 1, mesma continuação
        # de segmento) NÃO é fronteira -- só reset/queda é.
        is_boundary[1:] &= map_run_length[1:] != (map_run_length[:-1] + 1)
    return np.cumsum(is_boundary).astype(np.int64) - 1


def segments_to_canonical_states(
    segment_id: IntArray, response: FloatArray, *, n_buckets: int
) -> IntArray:
    """Reduz segmento->barra: calcula retorno médio por segmento, agrupa
    segmentos em `n_buckets` por quantil desse retorno médio (não por
    valor absoluto -- consistente com o resto do M4, que usa posto/quantil
    em vez de corte de valor bruto), propaga o bucket de volta pra nível
    de barra. Levanta `ValueError` se `n_buckets` >= nº de segmentos
    distintos (bucket vazio silencioso, não faz sentido estatístico)."""
    if segment_id.shape != response.shape:
        raise ValueError(
            "segments_to_canonical_states: segment_id/response precisam do mesmo shape "
            f"(segment_id={segment_id.shape}, response={response.shape})"
        )
    unique_segments = np.unique(segment_id)
    if n_buckets >= unique_segments.size:
        raise ValueError(
            f"segments_to_canonical_states: n_buckets={n_buckets} >= "
            f"n_segments={unique_segments.size} -- bucket vazio garantido"
        )

    finite_mask = np.isfinite(response)
    segment_mean: dict[int, float] = {}
    for seg in unique_segments.tolist():
        seg_response = response[(segment_id == seg) & finite_mask]
        segment_mean[seg] = float(np.mean(seg_response)) if seg_response.size > 0 else 0.0

    means = np.array([segment_mean[s] for s in unique_segments.tolist()])
    edges = np.quantile(means, np.linspace(0, 1, n_buckets + 1)[1:-1])
    bucket_by_segment = {
        seg: int(np.searchsorted(edges, segment_mean[seg], side="right"))
        for seg in unique_segments.tolist()
    }

    result: IntArray = np.vectorize(bucket_by_segment.get)(segment_id).astype(np.int64)
    return result


__all__ = ["BOCPDResult", "run_bocpd", "segments_to_canonical_states"]
