"""M6 — Hipótese do fator comum (PRD_V4_1.md §3.2, 0 trials).

**Nula (Q1):** `edge_bruto_atr` é o MESMO entre os 5 ativos, e as
diferenças em `ret_net` vêm inteiramente de `custo_atr`.

**Falsificação:** se `edge_bruto_atr` variar significativamente com
direção estável, existe componente idiossincrático além do fator comum —
multi-ativo é diversificação real. Se não variar, os 5 são um ativo com 5
estruturas de custo — a seleção entre eles é puramente econômica.

**Pré-requisito satisfeito em 2026-08-14** (`PLANO_MESTRE_PRINCE2.md`
§15.6 item 4): `data/labels/{symbol}/15m/v1/labels.parquet` existe agora
pros 5 ativos. **Zero trials** — teste de proposição sobre dado já
existente, reusa `src.analysis.feasibility.{edge_bruto_atr,custo_atr,
edge_liq_atr,captura,frac_tp_sl_from_labels}` (§1.2) sem nenhuma fórmula
nova. Não precisa de `predictions.parquet`/modelo treinado — `barrier_hit`
e `atr_at_t0` já estão em `labels.parquet`, medidos direto do Label
Engine, upstream de qualquer Alpha.

**Instrumento de falsificação — heterogeneidade de meta-análise
(Cochran's Q / I², DerSimonian & Laird 1986).** Cada símbolo dá uma
estimativa independente de `edge_bruto_atr` com erro-padrão DERIVADO (não
inventado) da variância multinomial de `frac_TP`/`frac_SL` sobre a
amostra real (`n` ~ dezenas de milhares de trades por símbolo/lado — CLT
aproxima bem, ver `_edge_bruto_se`). `Q = Σ w_i(x_i - x̄)²` (pesos
`w_i=1/SE_i²`) segue `chi²(k-1)` sob H0 (todos os símbolos compartilham o
mesmo `edge_bruto_atr` verdadeiro); `I²` é a fração da variação TOTAL
observada atribuível a heterogeneidade real, não ruído de amostragem —
0% rejeita a hipótese idiossincrática (fator comum sobrevive), I² alto
confirma variação real entre ativos. Mesma classe de instrumento (medição
formal decide, não p-value escolhido a dedo) que M4 já usa (Rand
ajustado, PRD §3.2).

**G-C1-4** (todas as métricas estratificadas por symbol/tf/lado/regime):
tabela completa por `(symbol, side, regime)` reportada para auditoria. O
teste de heterogeneidade em si roda POOLED por `(symbol, side)` — através
de regime — porque estratificar por regime também fragmentaria demais a
amostra pra estimar `SE` com confiança (R0/R5 têm poucos trades — achado
F1 do CLAUDE.md, R0 é ~100% warmup em algumas séries) e porque a pergunta
do M6 é sobre o ativo inteiro, não uma condicional de regime.

**Módulo reusado pelo M4, não só pelo M6.** `permutation_heterogeneity_test`
e `segment_boundaries` (via `src.validation.regime_utility`) já eram
consumidos por `src.analysis.m4_critical_windows` pra heterogeneidade
TP/SL por bucket de regime. A extensão de 2026-08-20 (`AG-114`,
`PLANO_MESTRE_PRINCE2.md §15.12.1`) adiciona `cochrans_q_heterogeneity_continuous`/
`permutation_heterogeneity_test_continuous` — mesma família estatística,
resposta CONTÍNUA (volatilidade futura, não TP/SL) — pra métrica primária
de ranking da qualidade-de-gate de regime, sem tocar nada do que já
existia pro M6/heterogeneidade TP/SL."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy.stats import chi2

from src.analysis.feasibility import captura as compute_captura
from src.analysis.feasibility import custo_atr as compute_custo_atr
from src.analysis.feasibility import edge_bruto_atr as compute_edge_bruto_atr
from src.analysis.feasibility import edge_liq_atr as compute_edge_liq_atr
from src.analysis.feasibility import frac_tp_sl_from_labels
from src.core.provenance import report_provenance
from src.labels.triple_barrier import LabelConfig
from src.models.dataset import REGIME_COL, build_modeling_frame
from src.risk._constants import load_constant as load_risk_constant
from src.validation.regime_utility import segment_boundaries

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "m6_common_factor_hypothesis_report.json"

# Os 5 ativos do projeto (§0.1) — BTCUSDT (labels/v1/ legado) + os 4 alts
# (data/labels/{symbol}/15m/v1/, gerados em 2026-08-14, §15.6 item 4).
ALL_SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
DECISION_TF: Final[str] = "15m"
SIDES: Final[tuple[int, ...]] = (1, -1)


@dataclass(frozen=True, slots=True)
class StratumMetrics:
    """Um corte — `regime=None` significa pooled através de todos os
    regimes (o corte que alimenta o teste de heterogeneidade)."""

    symbol: str
    side: int
    regime: str | None
    n: int
    frac_tp: float
    frac_sl: float
    frac_time: float
    frac_nofill: float
    edge_bruto_atr: float
    edge_bruto_atr_se: float
    custo_atr: float
    edge_liq_atr: float
    captura: float


def _edge_variance_multinomial(
    frac_tp: NDArray[np.float64],
    frac_sl: NDArray[np.float64],
    n: NDArray[np.float64],
    *,
    tp_mult: float,
    sl_mult: float,
) -> NDArray[np.float64]:
    """`Var(edge_bruto_atr)` por propagação linear da variância MULTINOMIAL
    de `(frac_TP, frac_SL)` — as duas vêm da MESMA amostra categórica de
    `barrier_hit` (TP/SL/TIME/NOFILL), não são independentes. Para uma
    multinomial com proporções `p_i` sobre `n` observações:
    `Var(frac_i) = p_i(1-p_i)/n`, `Cov(frac_i, frac_j) = -p_i*p_j/n`
    (i≠j) — propriedade padrão da distribuição, não uma aproximação.
    `Var(edge) = tp_mult²·Var(frac_TP) + sl_mult²·Var(frac_SL) -
    2·tp_mult·sl_mult·Cov(frac_TP,frac_SL)`.

    Núcleo VETORIZADO compartilhado entre `_edge_bruto_se` (escalar,
    pooled/estratificado do M6 -- envolve `frac_tp`/`frac_sl`/`n` num
    array de 1 elemento) e `_q_statistic_from_bucket_codes` (vetorizado
    por grupo, permutação em bloco AG-092) -- extraído 2026-08-19,
    achado de auditoria independente (a mesma fórmula existia duplicada
    nos 2 lugares, protegida só por um teste de equivalência passivo,
    não por uma fonte única; risco real de divergência silenciosa se
    alguém editasse só um dos dois no futuro).

    **Pré-condição -- `n > 0` em TODA posição, garantido pelos 2
    chamadores antes de chegar aqui** (`_edge_bruto_se` retorna `NaN`
    cedo se `n<=0`; `_q_statistic_from_bucket_codes` retorna `NaN` cedo
    se `np.any(n_per_bucket<=0)`) -- esta função não reguarda de
    propósito (evitaria checar 2x o mesmo invariante), então NUNCA
    chame com `n<=0` sem repetir a guarda do lado de fora."""
    var_tp = frac_tp * (1.0 - frac_tp) / n  # noqa: unguarded-ratio -- n>0 garantido pelos 2 chamadores, ver docstring
    var_sl = frac_sl * (1.0 - frac_sl) / n  # noqa: unguarded-ratio -- idem
    cov_tp_sl = -frac_tp * frac_sl / n  # noqa: unguarded-ratio -- idem
    return (tp_mult**2) * var_tp + (sl_mult**2) * var_sl - 2.0 * tp_mult * sl_mult * cov_tp_sl


def _edge_bruto_se(
    frac_tp: float, frac_sl: float, n: int, *, tp_mult: float, sl_mult: float
) -> float:
    """Erro-padrão de `edge_bruto_atr = frac_TP*tp_mult - frac_SL*sl_mult`
    -- wrapper escalar de `_edge_variance_multinomial` (ver docstring
    dela pra fórmula completa/fonte)."""
    if n <= 0 or np.isnan(frac_tp) or np.isnan(frac_sl):
        return float("nan")
    var_edge = _edge_variance_multinomial(
        np.array([frac_tp]), np.array([frac_sl]), np.array([float(n)]),
        tp_mult=tp_mult, sl_mult=sl_mult,
    )
    return float(np.sqrt(max(float(var_edge[0]), 0.0)))


def stratum_metrics(
    labels: pl.DataFrame,
    *,
    symbol: str,
    side: int,
    regime: str | None,
    tp_atr_mult: float,
    sl_atr_mult: float,
    maker_fee: float,
    taker_fee: float,
) -> StratumMetrics:
    """Núcleo puro — `labels` já filtrado pelo chamador (por side, e por
    regime se for o corte detalhado). Sem IO, testável com fixture
    sintética pequena."""
    frac = frac_tp_sl_from_labels(labels)
    eb = compute_edge_bruto_atr(
        frac_tp=frac.frac_tp, frac_sl=frac.frac_sl, tp_atr_mult=tp_atr_mult, sl_atr_mult=sl_atr_mult
    )
    se = _edge_bruto_se(
        frac.frac_tp, frac.frac_sl, frac.n, tp_mult=tp_atr_mult, sl_mult=sl_atr_mult
    )
    if frac.n > 0:
        atr_median = float(labels["atr_at_t0"].median())  # type: ignore[arg-type]
        ca = compute_custo_atr(atr_pct=atr_median, maker_fee=maker_fee, taker_fee=taker_fee)
    else:
        ca = float("nan")
    el = compute_edge_liq_atr(edge_bruto=eb, custo_atr_value=ca)
    cap = compute_captura(edge_liq=el, edge_bruto=eb)
    return StratumMetrics(
        symbol=symbol,
        side=side,
        regime=regime,
        n=frac.n,
        frac_tp=frac.frac_tp,
        frac_sl=frac.frac_sl,
        frac_time=frac.frac_time,
        frac_nofill=frac.frac_nofill,
        edge_bruto_atr=eb,
        edge_bruto_atr_se=se,
        custo_atr=ca,
        edge_liq_atr=el,
        captura=cap,
    )


# ============================================================================
# Heterogeneidade — Cochran's Q / I² (DerSimonian & Laird 1986)
# ============================================================================


@dataclass(frozen=True, slots=True)
class HeterogeneityTest:
    side: int
    k: int
    pooled_edge_bruto_atr: float
    q_statistic: float
    df: int
    p_value: float
    i_squared_pct: float
    per_symbol: tuple[StratumMetrics, ...]


def cochrans_q_heterogeneity(strata: tuple[StratumMetrics, ...]) -> HeterogeneityTest:
    """`strata`: uma `StratumMetrics` (pooled, `regime=None`) por símbolo,
    MESMO `side`. `w_i=1/SE_i²` (peso por precisão inversa); `x̄` = média
    ponderada; `Q = Σw_i(x_i-x̄)²` ~ `chi²(k-1)` sob H0 (mesmo
    `edge_bruto_atr` verdadeiro nos `k` símbolos). `I² = max(0,
    (Q-df)/Q)·100%` — fração da variação TOTAL atribuível a
    heterogeneidade real (Higgins & Thompson 2002, instrumento padrão de
    meta-análise, não inventado aqui).

    **`k=1` (`df=0`) -- corrigido 2026-08-19, achado de auditoria cética
    (reusada pelo M4 pra heterogeneidade por bucket de regime, onde `k=1`
    acontece de verdade quando um candidato satura a 1 bucket só, ex.
    Jump Model degenerado -- AG-087).**

    Em aritmética EXATA, `Q=0` é determinístico pra `k=1` (`x̄` é o
    próprio único valor, `Σw_i(x_i-x̄)²` colapsa a zero por construção --
    não é "indefinido", é trivialmente zero). O que É genuinamente
    ambíguo é a INTERPRETAÇÃO desse zero: "0% de heterogeneidade" (uma
    leitura válida -- não há evidência de heterogeneidade porque não há
    comparação possível) vs. "não há amostra suficiente pra sequer
    perguntar" (a leitura escolhida aqui). **Correção 2026-08-19, `NaN`
    explícito, nunca `0.0`/`100.0`:**
    1. Achado real de auditoria (verificado): em ponto flutuante,
       `pooled = Σ(w·v)/Σw` com 1 termo deveria simplificar pra `v`
       exatamente, mas envolve 2 arredondamentos (`fl(fl(w·v)/w)`), erro
       esperado `~4u²≈4,93e-32` (`u`=épsilon de máquina binário64) --
       bateu quase exato com um caso real medido
       (`experiments/m4_critical_windows_report.json`,
       BTCUSDT/CRYPTO_WINTER/short: `q_statistic=3,857e-32`, não zero
       bit-exato). A fórmula antiga (`(q-df)/q` com `df=0`) amplificava
       esse ruído de ULP pro EXTREMO OPOSTO do pretendido:
       `i_squared_pct=100.0`. Isso sozinho já justificaria um guard
       explícito em vez de deixar o resultado ao sabor do ruído de
       ponto flutuante.
    2. **Correção de proveniência, 2026-08-19 (auditoria independente):**
       a versão anterior deste docstring citava "precedente unânime" em
       `metafor::rma.uni`/pacote `meta` (R)/Higgins & Thompson (2002)/
       Cochrane Handbook §9.5.2 como devolvendo `NA` pra `k=1` -- **essa
       citação era FALSA**, refutada por leitura direta do código-fonte
       real dos 2 pacotes R: `metafor::rma.uni` (`R/rma.uni.r`, branch
       `master`) hard-codifica `QE=0, I2=0, QEp=1` pra `k<=p`; `meta::
       hetcalc` (`R/hetcalc.R`) hard-codifica `Q=0` pra `k=1` com dado
       presente. ISTO É: as duas bibliotecas de referência tratam `k=1`
       como "0% por convenção" e INCLUEM na agregação, o oposto da
       decisão tomada aqui. A escolha `NaN`/EXCLUIR (via `_median_or_nan`
       em `m4_critical_windows.py`) não vem de precedente de biblioteca
       nenhuma -- é uma decisão específica ao uso real deste repo:
       `k=1`/`n_buckets=1` em M4 normalmente significa um classificador
       de regime degenerado que colapsou pra 1 bucket só (AG-087),
       excluir da mediana evita recompensar esse colapso com um score
       artificialmente "limpo" (0% de heterogeneidade), diferente do
       caso de meta-análise clássica (`metafor`/`meta`) onde `k=1` é só
       "1 estudo disponível", sem essa conotação de degenerescência.
    `pooled_edge_bruto_atr` continua computável (é literalmente o valor
    do único estrato) -- só `q_statistic`/`p_value`/`i_squared_pct` viram
    `NaN`. Confirmado que a execução real do M6 nunca teve `k=1`
    (`experiments/m6_common_factor_hypothesis_report.json`, `k=5` sempre
    nos 2 lados) -- esta correção não muda nenhum resultado do M6 já
    auditado/validado. Impacto real medido no M4 (o consumidor onde
    `k=1` de fato ocorre): 26 células com `n_buckets=1` em
    `experiments/m4_critical_windows_report.json` (23 saíam `0.0` "por
    sorte" de ponto flutuante e eram incluídas na mediana antes desta
    correção, 3 saíam `100.0` corrompidas) -- as 26 passam a ser `NaN`/
    excluídas agora, mudança sistemática de tratamento, não só das 3
    quebradas. Esse relatório em disco fica desatualizado em relação a
    este código a partir desta correção; re-execução do M4 pendente
    (aguarda também AG-092, invalidade estatística do instrumento sob
    autocorrelação intra-episódio)."""
    if len({s.side for s in strata}) != 1:
        raise ValueError("cochrans_q_heterogeneity: todos os strata precisam ser do mesmo side")
    side = strata[0].side
    k = len(strata)
    se = np.array([s.edge_bruto_atr_se for s in strata], dtype=np.float64)
    values = np.array([s.edge_bruto_atr for s in strata], dtype=np.float64)
    if np.any(se <= 0) or np.any(np.isnan(se)) or np.any(np.isnan(values)):
        return HeterogeneityTest(
            side=side, k=k, pooled_edge_bruto_atr=float("nan"), q_statistic=float("nan"),
            df=k - 1, p_value=float("nan"), i_squared_pct=float("nan"), per_symbol=strata,
        )
    weights = 1.0 / (se**2)  # noqa: unguarded-ratio -- se>0 garantido pelo guard acima (np.any(se<=0) já retornou)
    pooled = float(np.sum(weights * values) / np.sum(weights))  # noqa: unguarded-ratio -- soma de pesos todos positivos, nunca zero
    df = k - 1
    if df == 0:
        # k=1 -- Q/I² indefinidos matematicamente, NaN explícito (ver
        # docstring acima). pooled continua válido (só reflete o único
        # estrato), não precisa virar NaN junto.
        return HeterogeneityTest(
            side=side, k=k, pooled_edge_bruto_atr=pooled, q_statistic=float("nan"),
            df=df, p_value=float("nan"), i_squared_pct=float("nan"), per_symbol=strata,
        )
    q = float(np.sum(weights * (values - pooled) ** 2))
    p_value = float(chi2.sf(q, df))
    i_squared = max(0.0, (q - df) / q) * 100.0 if q > 0 else 0.0  # noqa: unguarded-ratio -- guardado pelo `if q > 0 else 0.0` na mesma linha
    return HeterogeneityTest(
        side=side, k=k, pooled_edge_bruto_atr=pooled, q_statistic=q, df=df,
        p_value=p_value, i_squared_pct=i_squared, per_symbol=strata,
    )


# ============================================================================
# Permutação em bloco por episódio (AG-092) — corrige a violação de
# independência de estratos de cochrans_q_heterogeneity quando os dados
# vêm de série TEMPORAL com regime persistente, não amostras i.i.d.
# ============================================================================

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]  # AG-114, 2026-08-20 -- generalização contínua precisa do alias


# ============================================================================
# Generalização contínua (AG-114, 2026-08-20, PLANO_MESTRE_PRINCE2.md
# §15.12.1) — mesma família Cochran's Q/DerSimonian-Laird acima, mas pra
# resposta CONTÍNUA (volatilidade futura, não TP/SL binário) e ponderada
# por EPISÓDIO (não por barra) na COMPOSIÇÃO do peso -- `w_i =
# n_episodios_i/var_i` -- não na estimativa de `var_i` em si.
#
# **Achado real desta sessão (rodando a suíte pela 1ª vez, não previsto no
# desenho original): ponderar `var_i` pela variância ENTRE MÉDIAS DE
# EPISÓDIO (não pela variância intra-bucket) exige >=2 episódios por
# bucket pra ser computável -- com exatamente 1 episódio por bucket
# (cenário comum: candidato entra 1x num estado e fica, dentro de 1
# janela crítica curta), `var_i` fica indefinido e o resultado inteiro
# vira `NaN`, mesmo com centenas de barras de dado real disponíveis.**
# Corrigido: `var_i` usa a variância amostral (ddof=1) de TODAS as barras
# FINITAS do bucket `i` (só precisa de >=2 barras, quase sempre verdade),
# mas `n_i` no peso continua sendo CONTAGEM DE EPISÓDIO (não de barra) --
# resolve o achado real (`NaN` explosivo) sem abandonar a correção da
# auditoria 1 pt8 (peso não escala com contagem bruta de barra/trade).
#
# Validade estatística não depende de `var_i` ser um estimador "correto"
# da variância entre episódios -- vem da PERMUTAÇÃO: a mesma fórmula
# (mesmo possível viés) é aplicada ao `Q` observado E a cada `Q` permutado,
# então qualquer viés sistemático cancela na comparação -- mesmo argumento
# já usado pra justificar por que a permutação em bloco corrige a SE
# multinomial subestimada da versão TP/SL (AG-092, ver docstring de
# `permutation_heterogeneity_test`). `n_episodios_i` é INVARIANTE a
# permutação (mesmo multiset de rótulos, só reatribuído a episódios
# diferentes) -- calculado 1x pelo chamador, nunca recomputado por
# permutação.
#
# Motivo do peso por episódio (não abandonado, só corrigido): ADR-001
# (ratificado) repete em 3 lugares independentes a mesma disciplina --
# nunca deixar contagem BRUTA de observação substituir contagem de
# unidade INDEPENDENTE (§1.3, N_eff de trials via clustering; §3.2,
# WeightBasis/concorrência por união de intervalos; §2.8, cMDA permuta o
# cluster inteiro, não a feature). Corrige, no mesmo código, o achado da
# auditoria 1 pt8 do documento de validação do M4 ("estatística observada
# pondera por trade, não por episódio") sem tocar a versão TP/SL acima,
# que permanece intocada (ainda usada por M6 e pelo bloco
# `heterogeneity` do M4 tal como está).
# ============================================================================


def _q_statistic_continuous_episode_weighted(
    bucket_codes: IntArray,
    response: FloatArray,
    n_episodes_per_bucket: FloatArray,
    *,
    k: int,
) -> tuple[float, float]:
    """`(q_statistic, pooled_mean)` -- `w_i = n_episodes_per_bucket[i]/var_i`,
    `var_i` = variância amostral (`ddof=1`) de `response` sobre as barras
    FINITAS do bucket `i` (todas as barras do bucket, não só médias de
    episódio -- só exige `>=2` barras finitas, não `>=2` episódios, ver
    bloco de comentário acima pro achado real que motivou isso).
    `n_episodes_per_bucket` é responsabilidade do CHAMADOR (computado 1x
    fora de qualquer laço de permutação -- ver
    `permutation_heterogeneity_test_continuous`). Bucket presente com
    `<2` barras finitas, OU `var_i<=0` -- `(NaN, NaN)`, mesma disciplina
    de `anova_by_group`/`_q_statistic_from_bucket_codes` (nunca `0`/
    exceção silenciosa; usada dentro de laço de permutação, então nunca
    levanta -- devolve `NaN`)."""
    finite_mask = np.isfinite(response)
    bucket_codes_finite = bucket_codes[finite_mask]
    response_finite = response[finite_mask]

    n_bars_per_bucket = np.bincount(bucket_codes_finite, minlength=k).astype(np.float64)
    present = n_bars_per_bucket > 0
    if np.any(n_bars_per_bucket[present] < 2):
        return float("nan"), float("nan")

    means = np.full(k, np.nan, dtype=np.float64)
    variances = np.full(k, np.nan, dtype=np.float64)
    for b in np.flatnonzero(present):
        bucket_values = response_finite[bucket_codes_finite == b]
        means[b] = float(np.mean(bucket_values))
        variances[b] = float(np.var(bucket_values, ddof=1))

    active_var = variances[present]
    if np.any(active_var <= 0) or np.any(np.isnan(active_var)):
        return float("nan"), float("nan")

    w = n_episodes_per_bucket[present] / active_var  # noqa: unguarded-ratio -- active_var>0 garantido pelo guard acima
    active_means = means[present]
    pooled = float(np.sum(w * active_means) / np.sum(w))  # noqa: unguarded-ratio -- soma de pesos todos positivos, nunca zero
    q = float(np.sum(w * (active_means - pooled) ** 2))
    return q, pooled


@dataclass(frozen=True, slots=True)
class ContinuousHeterogeneityResult:
    k: int
    n_episodes: int
    pooled_response: float
    q_statistic: float
    df: int
    p_value: float
    i_squared_pct: float


def cochrans_q_heterogeneity_continuous(
    bucket_ids: IntArray, response: FloatArray
) -> ContinuousHeterogeneityResult:
    """Espelha `cochrans_q_heterogeneity` (mesma correção `k=1` ->
    `q_statistic`/`p_value`/`i_squared_pct=NaN` explícito, 2026-08-19).
    `bucket_ids`: códigos ARBITRÁRIOS (`canonical_id` cru, não precisa vir
    denso/contíguo) -- densificado internamente via `_dense_bucket_codes`,
    mesmo contrato de `permutation_heterogeneity_test_continuous`
    (chamador nunca precisa pré-densificar)."""
    bucket_codes, k = _dense_bucket_codes(bucket_ids)
    segment_starts, _segment_ends = segment_boundaries(bucket_codes)
    n_episodes = int(segment_starts.shape[0])
    episode_bucket = bucket_codes[segment_starts]
    n_episodes_per_bucket = np.bincount(episode_bucket, minlength=k).astype(np.float64)

    df = k - 1
    q, pooled = _q_statistic_continuous_episode_weighted(
        bucket_codes, response, n_episodes_per_bucket, k=k
    )
    if df <= 0 or np.isnan(q):
        return ContinuousHeterogeneityResult(
            k=k, n_episodes=n_episodes, pooled_response=pooled, q_statistic=float("nan"),
            df=df, p_value=float("nan"), i_squared_pct=float("nan"),
        )
    p_value = float(chi2.sf(q, df))
    i_squared = max(0.0, (q - df) / q) * 100.0 if q > 0 else 0.0  # noqa: unguarded-ratio -- guardado pelo `if q>0 else 0.0`
    return ContinuousHeterogeneityResult(
        k=k, n_episodes=n_episodes, pooled_response=pooled, q_statistic=q,
        df=df, p_value=p_value, i_squared_pct=i_squared,
    )


def _dense_bucket_codes(bucket_ids: IntArray) -> tuple[IntArray, int]:
    """Remapeia códigos de bucket arbitrários (`canonical_id` de um
    candidato de regime, não necessariamente 0..k-1 nem contíguo) pra
    inteiros densos 0..k-1 — `np.bincount` exige índices não-negativos e
    densos. `k` = nº de buckets DISTINTOS presentes (não um valor fixo de
    config — um candidato pode saturar a menos buckets que o nominal,
    AG-087)."""
    uniques, codes = np.unique(bucket_ids, return_inverse=True)
    return codes.astype(np.int64), int(uniques.shape[0])


def _q_statistic_from_bucket_codes(
    bucket_codes: IntArray,
    is_tp: IntArray,
    is_sl: IntArray,
    *,
    tp_mult: float,
    sl_mult: float,
    k: int,
) -> float:
    """Recomputa só `Q` (não `StratumMetrics` inteiro) a partir de
    contagens agregadas por grupo — MESMA fórmula de
    `cochrans_q_heterogeneity` (SE multinomial de `_edge_variance_
    multinomial`, mesmo núcleo que `_edge_bruto_se` usa, pesos `w=1/SE²`,
    `Q=Σw(x-x̄)²`), vetorizado via `np.bincount` pra rodar centenas/
    milhares de vezes (permutação, AG-092) sem o overhead de construir
    `StratumMetrics`/tocar Polars a cada rodada. `Q` só depende de
    `n`/`frac_tp`/`frac_sl` por grupo — nunca de `custo_atr`/
    `edge_liq_atr`/`captura` (que dependem de `atr_at_t0`, fora da fórmula
    de `Q`) — pular esses campos aqui é simplificação LEGÍTIMA, não
    aproximação: equivalência com `cochrans_q_heterogeneity` sobre a
    atribuição REAL (não permutada) provada por teste dedicado
    (`test_q_statistic_from_bucket_codes_bate_com_cochrans_q_
    heterogeneity_na_atribuicao_real`)."""
    n_per_bucket = np.bincount(bucket_codes, minlength=k).astype(np.float64)
    if np.any(n_per_bucket <= 0):
        return float("nan")
    tp_per_bucket = np.bincount(bucket_codes, weights=is_tp, minlength=k)
    sl_per_bucket = np.bincount(bucket_codes, weights=is_sl, minlength=k)
    frac_tp = tp_per_bucket / n_per_bucket
    frac_sl = sl_per_bucket / n_per_bucket
    edge = frac_tp * tp_mult - frac_sl * sl_mult
    var_edge = _edge_variance_multinomial(
        frac_tp, frac_sl, n_per_bucket, tp_mult=tp_mult, sl_mult=sl_mult
    )
    se = np.sqrt(np.maximum(var_edge, 0.0))
    if np.any(se <= 0) or np.any(np.isnan(se)):
        return float("nan")
    w = 1.0 / (se**2)  # noqa: unguarded-ratio -- se>0 garantido pelo guard acima (np.any(se<=0) já retornou)
    pooled = float(np.sum(w * edge) / np.sum(w))  # noqa: unguarded-ratio -- soma de pesos todos positivos, nunca zero
    return float(np.sum(w * (edge - pooled) ** 2))


@dataclass(frozen=True, slots=True)
class PermutationHeterogeneityResult:
    """AG-092 — p-valor EMPÍRICO pra `Q` observado de
    `cochrans_q_heterogeneity`, válido sob autocorrelação intra-episódio
    (premissa violada pelo p-valor assintótico `chi²(k-1)` quando os
    estratos vêm de séries temporais com regime persistente, não amostras
    i.i.d. — ver docstring de `permutation_heterogeneity_test`).
    `k<2`/`n_episodes<2`/`Q` degenerado → `p_value=NaN` explícito, nunca
    inventado. `n_permutations_valid < n_permutations_requested` é
    esperado ocasionalmente (uma permutação pode degenerar — ex. um
    bucket pseudo-atribuído fica só com TP ou só com SL, `SE=0` —
    descartada, não conta pro denominador do p-valor, nunca um crash)."""

    q_observed: float
    p_value: float
    n_episodes: int
    n_permutations_requested: int
    n_permutations_valid: int


def permutation_heterogeneity_test(
    bucket_ids: IntArray,
    is_tp: IntArray,
    is_sl: IntArray,
    *,
    tp_mult: float,
    sl_mult: float,
    n_permutations: int,
    seed: int,
) -> PermutationHeterogeneityResult:
    """Teste de permutação em BLOCO por episódio (AG-092,
    `audit/architecture_gaps_log.yaml`) — corrige a violação de
    independência de estratos de `cochrans_q_heterogeneity` quando os
    dados vêm de uma série TEMPORAL com regime persistente: trades do
    MESMO bucket formam episódios contíguos autocorrelacionados (regime
    persistente = condições de mercado correlacionadas), então o
    erro-padrão multinomial de `_edge_bruto_se` (que assume trades
    i.i.d.) subestima a variância real, inflando `Q`/`I²` artificialmente
    — confirmado empiricamente no relatório real do M4 (`I²` satura
    70-99% quase universalmente, padrão consistente com este mecanismo de
    inflação, não com heterogeneidade real tão extrema).

    `bucket_ids`/`is_tp`/`is_sl`: 1 linha por trade, ORDENADAS POR TEMPO
    pelo chamador (obrigatório — a extração de episódio abaixo assume que
    posições adjacentes no array são adjacentes no tempo).

    Mecânica: extrai EPISÓDIOS (sequências máximas de linhas consecutivas
    com o mesmo bucket, via `regime_utility.segment_boundaries` — mesma
    lógica de run-length de `regime_persistence`). Pra cada permutação:
    embaralha o VETOR de bucket-por-episódio (nunca quebra um episódio no
    meio, preserva duração/ordem temporal de cada um), reatribui cada
    linha ao bucket do seu episódio pós-embaralhamento, recomputa `Q` sob
    essa atribuição pseudo-aleatória. `Q` observado é só mais um ponto
    dentro dessa distribuição nula — p-valor empírico = fração de
    permutações com `Q_perm >= Q_observado` (com correção +1, padrão de
    teste de permutação: `(1+Σ[Q_perm>=Q_obs])/(1+B)`, nunca 0 exato
    mesmo se NENHUMA permutação igualar/superar o observado).

    Por que isso resolve a violação de i.i.d. sem precisar corrigir a
    fórmula de `SE`: a distribuição nula é gerada com a MESMA fórmula de
    `Q` (mesma `SE` potencialmente subestimada) aplicada a cada
    permutação — como o embaralhamento é por EPISÓDIO inteiro (nunca por
    linha individual), a estrutura de autocorrelação intra-episódio
    permanece intacta em CADA permutação, então qualquer inflação de `Q`
    causada por essa autocorrelação afeta a distribuição nula do MESMO
    jeito que afeta o `Q` observado — comparar os dois cancela o viés,
    mesmo sem jamais estimar a `SE` "certa". Padrão estabelecido pra
    testar diferença de grupo sob dependência intra-cluster (permutação
    em bloco/cluster), não uma técnica inventada aqui.

    `k` (nº de buckets distintos) é PRESERVADO em toda permutação —
    embaralhar VALORES já presentes no vetor de episódios (não
    resortear/reamostrar com reposição) nunca remove um valor do
    conjunto, só troca quais episódios o carregam. `df=k-1` implícito
    continua constante entre `Q_observado` e toda `Q_perm`, comparação
    like-for-like.

    **Resolução do p-valor degrada com poucos episódios** (achado de
    auditoria independente, 2026-08-19): `p_min` teórico é `1/(B+1)`, mas
    isso só vale quando o nº de rearranjos DISTINTOS de episódio->bucket
    excede `B` -- com `n_episodes` baixo (ex. 3 episódios, 2 buckets),
    o nº de rearranjos distintos pode ser tão baixo quanto 3-6,
    tornando o piso real de resolução muito mais grosseiro que `B`
    sugere, independente de `B=1000` (`m4_heterogeneity_n_permutations`).
    Não é um bug (a amostragem da distribuição nula EXATA continua
    correta), mas `n_episodes` (exposto em `PermutationHeterogeneityResult`)
    deve ser conferido antes de tratar um `p_value` baixo como forte --
    poucos episódios também produzem `p_value` categoricamente granular
    (ex. só `{1/4, 2/4, 3/4, 1.0}` possíveis com 3 episódios/2 buckets)."""
    if bucket_ids.shape[0] == 0:
        raise ValueError("permutation_heterogeneity_test: bucket_ids vazio")
    if not (bucket_ids.shape == is_tp.shape == is_sl.shape):
        raise ValueError(
            "permutation_heterogeneity_test: bucket_ids/is_tp/is_sl precisam do mesmo shape "
            f"(bucket_ids={bucket_ids.shape}, is_tp={is_tp.shape}, is_sl={is_sl.shape})"
        )
    bucket_codes, k = _dense_bucket_codes(bucket_ids)
    segment_starts, segment_ends = segment_boundaries(bucket_codes)
    n_episodes = int(segment_starts.shape[0])
    q_observed = _q_statistic_from_bucket_codes(
        bucket_codes, is_tp, is_sl, tp_mult=tp_mult, sl_mult=sl_mult, k=k
    )
    if k < 2 or n_episodes < 2 or np.isnan(q_observed):
        return PermutationHeterogeneityResult(
            q_observed=q_observed, p_value=float("nan"), n_episodes=n_episodes,
            n_permutations_requested=n_permutations, n_permutations_valid=0,
        )

    episode_id = np.repeat(np.arange(n_episodes, dtype=np.int64), segment_ends - segment_starts)
    episode_bucket = bucket_codes[segment_starts]

    rng = np.random.default_rng(seed)
    n_ge = 0
    n_valid = 0
    for _ in range(n_permutations):
        permuted = rng.permutation(episode_bucket)
        pseudo_codes = permuted[episode_id]
        q_perm = _q_statistic_from_bucket_codes(
            pseudo_codes, is_tp, is_sl, tp_mult=tp_mult, sl_mult=sl_mult, k=k
        )
        if np.isnan(q_perm):
            continue
        n_valid += 1
        if q_perm >= q_observed:
            n_ge += 1

    empirical_p = (1.0 + n_ge) / (1.0 + n_valid)  # noqa: unguarded-ratio -- n_valid é contagem >=0, guardado pelo if abaixo
    p_value = float("nan") if n_valid == 0 else empirical_p
    return PermutationHeterogeneityResult(
        q_observed=q_observed, p_value=p_value, n_episodes=n_episodes,
        n_permutations_requested=n_permutations, n_permutations_valid=n_valid,
    )


def permutation_heterogeneity_test_continuous(
    bucket_ids: IntArray, response: FloatArray, *, n_permutations: int, seed: int
) -> PermutationHeterogeneityResult:
    """Generalização contínua de `permutation_heterogeneity_test` (AG-092)
    -- MESMA mecânica bar-level (`segment_boundaries`, `episode_id`
    repetido, embaralha o vetor de bucket-por-episódio, reexpande pra
    barra) -- resposta contínua (ex. `forward_realized_vol`) em vez de
    TP/SL binário, estatística ponderada por CONTAGEM DE EPISÓDIO (ver
    bloco de comentário acima, `_q_statistic_continuous_episode_weighted`).
    Reusa `PermutationHeterogeneityResult` (campos já genéricos o
    suficiente).

    `bucket_ids`/`response`: 1 linha por BARRA, ordenadas por tempo pelo
    chamador (mesmo contrato de `permutation_heterogeneity_test`).

    **`n_episodes_per_bucket` calculado 1x, fora do laço de permutação --
    não é aproximação, é exato.** Cada permutação embaralha o vetor
    `episode_bucket` (`rng.permutation`, sem reposição) -- isso reordena
    QUAIS episódios carregam qual rótulo, mas nunca muda o MULTISET de
    rótulos em si (mesmos valores, posições diferentes). Logo
    `bincount(permuted_episode_bucket)` é sempre idêntico a
    `bincount(episode_bucket)` -- `n_episodes_per_bucket` é invariante a
    permutação por construção, recalculá-lo a cada permutação seria
    trabalho redundante, não uma correção necessária."""
    if bucket_ids.shape[0] == 0:
        raise ValueError("permutation_heterogeneity_test_continuous: bucket_ids vazio")
    if bucket_ids.shape != response.shape:
        raise ValueError(
            "permutation_heterogeneity_test_continuous: bucket_ids/response precisam do "
            f"mesmo shape (bucket_ids={bucket_ids.shape}, response={response.shape})"
        )
    bucket_codes, k = _dense_bucket_codes(bucket_ids)
    segment_starts, segment_ends = segment_boundaries(bucket_codes)
    n_episodes = int(segment_starts.shape[0])
    episode_id = np.repeat(np.arange(n_episodes, dtype=np.int64), segment_ends - segment_starts)
    episode_bucket = bucket_codes[segment_starts]
    n_episodes_per_bucket = np.bincount(episode_bucket, minlength=k).astype(np.float64)

    q_observed, _pooled = _q_statistic_continuous_episode_weighted(
        bucket_codes, response, n_episodes_per_bucket, k=k
    )

    if k < 2 or n_episodes < 2 or np.isnan(q_observed):
        return PermutationHeterogeneityResult(
            q_observed=q_observed, p_value=float("nan"), n_episodes=n_episodes,
            n_permutations_requested=n_permutations, n_permutations_valid=0,
        )

    rng = np.random.default_rng(seed)
    n_ge = 0
    n_valid = 0
    for _ in range(n_permutations):
        permuted_episode_bucket = rng.permutation(episode_bucket)
        pseudo_codes = permuted_episode_bucket[episode_id]
        q_perm, _ = _q_statistic_continuous_episode_weighted(
            pseudo_codes, response, n_episodes_per_bucket, k=k
        )
        if np.isnan(q_perm):
            continue
        n_valid += 1
        if q_perm >= q_observed:
            n_ge += 1

    empirical_p = (1.0 + n_ge) / (1.0 + n_valid)  # noqa: unguarded-ratio -- n_valid é contagem >=0, guardado pelo if abaixo
    p_value = float("nan") if n_valid == 0 else empirical_p
    return PermutationHeterogeneityResult(
        q_observed=q_observed, p_value=p_value, n_episodes=n_episodes,
        n_permutations_requested=n_permutations, n_permutations_valid=n_valid,
    )


# ============================================================================
# Ponto de entrada com IO — um símbolo, ou os 5
# ============================================================================


def compute_metrics_for_symbol(
    symbol: str,
    *,
    tf: str = DECISION_TF,
    resolution_id: str | None = None,
    vol_estimator_id: str = "parkinson_w20",
) -> tuple[tuple[StratumMetrics, ...], tuple[StratumMetrics, ...]]:
    """Carrega `labels`+`regime` reais via `dataset.build_modeling_frame`
    (já corrigido pra rotear `symbol` corretamente até `load_labels_v1`,
    achado AG-015 — sem essa correção este módulo teria repetido o MESMO
    bug: features/regime de um símbolo, `barrier_hit`/`atr_at_t0` de
    outro). Retorna `(pooled_by_side, detail_by_side_and_regime)`."""
    # AG-233 -- grade de PRODUCAO quando `resolution_id` e passado. Ate
    # esta correcao o modulo rodava so em DECISION_TF="15m", grade que
    # deixou de ser producao em AG-042 (2026-08-16) -- ou seja, o
    # I2=96-98% que este teste produziu (fator comum entre os 5 ativos,
    # citado em decisao de escopo multi-ativo) foi medido na grade errada.
    if resolution_id is not None:
        cfg = LabelConfig.from_constants(
            estimator_id=vol_estimator_id, resolution_id=resolution_id
        )
    else:
        cfg = LabelConfig.from_constants(tf=tf)
    maker_fee = float(load_risk_constant("maker_fee"))
    taker_fee = float(load_risk_constant("taker_fee"))

    mf = build_modeling_frame(
        symbol=symbol,
        tf=tf,
        resolution_id=resolution_id,
        vol_estimator_id=vol_estimator_id if resolution_id is not None else None,
    )
    data = mf.data

    pooled: list[StratumMetrics] = []
    detail: list[StratumMetrics] = []
    for side in SIDES:
        side_df = data.filter(pl.col("side") == side)
        pooled.append(
            stratum_metrics(
                side_df, symbol=symbol, side=side, regime=None,
                tp_atr_mult=cfg.tp_atr_mult, sl_atr_mult=cfg.sl_atr_mult,
                maker_fee=maker_fee, taker_fee=taker_fee,
            )
        )
        for regime in sorted(side_df[REGIME_COL].drop_nulls().unique().to_list()):
            regime_df = side_df.filter(pl.col(REGIME_COL) == regime)
            detail.append(
                stratum_metrics(
                    regime_df, symbol=symbol, side=side, regime=str(regime),
                    tp_atr_mult=cfg.tp_atr_mult, sl_atr_mult=cfg.sl_atr_mult,
                    maker_fee=maker_fee, taker_fee=taker_fee,
                )
            )

    logger.info(
        "analysis.m6_common_factor.symbol_done",
        symbol=symbol,
        n_total=data.height,
        edge_bruto_atr_long=round(pooled[0].edge_bruto_atr, 6),
        edge_bruto_atr_short=round(pooled[1].edge_bruto_atr, 6),
    )
    return tuple(pooled), tuple(detail)


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 — mesmo padrão de `volatility_comparison._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("analysis.m6_common_factor.report_written", path=str(dest_path))


def run_and_save_m6_report(
    *,
    symbols: tuple[str, ...] = ALL_SYMBOLS,
    tf: str = DECISION_TF,
    resolution_id: str | None = None,
    vol_estimator_id: str = "parkinson_w20",
    dest_path: Path | None = None,
    max_workers: int | None = None,
) -> Path:
    """Ponto de entrada MANUAL — roda os 5 ativos em paralelo (cada
    símbolo é independente), roda o teste de heterogeneidade por lado
    sobre os cortes pooled, persiste o relatório completo (B29). Zero
    trials, zero escrita em `constants.yaml`, zero modelo treinado — não
    consome `N_lifetime`.

    Chame manualmente:
    `uv run python -m src.analysis.m6_common_factor_hypothesis`
    ou `uv run python -c "from src.analysis.m6_common_factor_hypothesis
    import run_and_save_m6_report as r; r()"`."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    logger.info(
        "analysis.m6_common_factor.starting", n_symbols=len(symbols), tf=tf, max_workers=workers
    )

    pooled_by_symbol: dict[str, tuple[StratumMetrics, ...]] = {}
    detail_by_symbol: dict[str, tuple[StratumMetrics, ...]] = {}
    failed_tasks: list[str] = []
    with ProcessPoolExecutor(max_workers=min(workers, len(symbols))) as executor:
        future_to_symbol = {
            executor.submit(
                compute_metrics_for_symbol,
                symbol,
                tf=tf,
                resolution_id=resolution_id,
                vol_estimator_id=vol_estimator_id,
            ): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            # AG-019: future.result() isolado em try/except -- 1 símbolo
            # falhando não pode derrubar os outros já concluídos com
            # sucesso (ver m2_bar_comparison.run_and_save_bar_comparison_report).
            try:
                pooled, detail = future.result()
            except Exception as exc:
                failed_tasks.append(symbol)
                logger.error(
                    "analysis.m6_common_factor.task_failed",
                    symbol=symbol,
                    error=repr(exc),
                )
                continue
            pooled_by_symbol[symbol] = pooled
            detail_by_symbol[symbol] = detail

    if failed_tasks:
        logger.warning(
            "analysis.m6_common_factor.tasks_failed",
            n_failed=len(failed_tasks),
            n_symbols=len(symbols),
            failed=failed_tasks,
        )

    # Cochran's Q e o detalhe por símbolo só cobrem quem resolveu -- um
    # símbolo falho (ausente de pooled_by_symbol) não pode derrubar o
    # teste dos outros nem virar KeyError aqui.
    ok_symbols = tuple(symbol for symbol in symbols if symbol in pooled_by_symbol)

    heterogeneity_by_side: dict[int, HeterogeneityTest] = {}
    for side in SIDES:
        strata = tuple(
            next(s for s in pooled_by_symbol[symbol] if s.side == side) for symbol in ok_symbols
        )
        heterogeneity_by_side[side] = cochrans_q_heterogeneity(strata)

    payload: dict[str, Any] = {
        **report_provenance(),
        "decision_tf": tf,
        "symbols": list(symbols),
        "failed_symbols": failed_tasks,
        "hypothesis": (
            "H0 (Q1, PRD_V4_1.md Sec3.2): edge_bruto_atr e o MESMO entre os "
            "5 ativos -- diferencas em ret_net vem inteiramente de custo_atr. "
            "Falsificacao: I2 alto / p_value baixo no teste de Cochran's Q "
            "indica componente idiossincratico real por ativo."
        ),
        "heterogeneity_by_side": {
            str(side): {
                "k": het.k,
                "pooled_edge_bruto_atr": het.pooled_edge_bruto_atr,
                "q_statistic": het.q_statistic,
                "df": het.df,
                "p_value": het.p_value,
                "i_squared_pct": het.i_squared_pct,
                "per_symbol": [asdict(s) for s in het.per_symbol],
            }
            for side, het in heterogeneity_by_side.items()
        },
        "detail_by_symbol_side_regime": {
            symbol: [asdict(s) for s in detail_by_symbol[symbol]] for symbol in ok_symbols
        },
    }
    # AG-233 -- arquivo POR GRADE; default sem sufixo continua sendo o da
    # grade legada, para nao orfanar leitores.
    if dest_path is not None:
        dest = dest_path
    elif resolution_id is not None:
        dest = DEFAULT_REPORT_PATH.with_name(
            DEFAULT_REPORT_PATH.stem + f"_{resolution_id}" + DEFAULT_REPORT_PATH.suffix
        )
    else:
        dest = DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info(
        "analysis.m6_common_factor.done",
        i_squared_long=round(heterogeneity_by_side[1].i_squared_pct, 2),
        i_squared_short=round(heterogeneity_by_side[-1].i_squared_pct, 2),
        p_value_long=heterogeneity_by_side[1].p_value,
        p_value_short=heterogeneity_by_side[-1].p_value,
        n_failed=len(failed_tasks),
        dest=str(dest),
    )
    return dest


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    import argparse
    import sys

    def _run() -> int:
        ap = argparse.ArgumentParser(
            description=(
                "M6 -- hipotese do fator comum entre os 5 ativos. AG-233: use "
                "--resolution-id para medir a grade CANONICA DE PRODUCAO. Sem o "
                "argumento, mede a grade de relogio 15m LEGADA."
            )
        )
        ap.add_argument("--resolution-id", default=None, choices=["R1", "R2", "R3"])
        ap.add_argument("--vol-estimator-id", default="parkinson_w20")
        args = ap.parse_args()
        if args.resolution_id is None:
            logger.warning(
                "analysis.m6_common_factor.grade_legada",
                detail="AG-233 -- rodando sobre a grade de RELOGIO 15m, que nao e "
                "producao desde AG-042. O I2 medido aqui nao descreve a grade real",
            )
        destino = run_and_save_m6_report(
            resolution_id=args.resolution_id, vol_estimator_id=args.vol_estimator_id
        )
        logger.info(
            "analysis.m6_common_factor.cli_done",
            report_path=str(destino),
            resolution_id=args.resolution_id,
        )
        return 0

    sys.exit(_run())
