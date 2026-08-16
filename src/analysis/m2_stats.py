"""M2 — núcleo estatístico puro (zero IO), extraído de
`m2_bar_comparison.py` no desmembramento de 2026-08-15 (brainstorm +
validação por auditoria externa, Opção 3: cortar por fronteira de
processo, não por camada nem por estágio de pipeline — ver docstring
completa de `m2_bar_comparison.py` pro histórico de achados/decisões
desta família de módulos, e `PLANO_MESTRE_PRINCE2.md` §15 pro registro
formal).

JB/curtose/Ljung-Box/ADF (`scipy.stats`/`statsmodels`) sobre log-retorno
de `close`, e "razão de amostra efetiva" via
`src.labels.weights.compute_concurrency_and_uniqueness` (produção real,
testada — não uma reimplementação). Testável isoladamente com `bars`
sintético — nenhuma função aqui toca `duckdb`/`lake`/rede, por construção
(é o que garante que `compute_bar_statistics` continue barata de testar
mesmo depois do split).

Import de `src.labels` a partir de `src.analysis` NÃO viola a hierarquia
de camadas (`pyproject.toml::[tool.importlinter]`, contrato "labels só é
lido por models/validation/backtest" lista só
`exchange/data/features/regime/risk/execution/live/monitoring` como
proibidos — `analysis` fica de fora deliberadamente, mesmo padrão já
usado em `m6_common_factor_hypothesis.py`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy import stats as scipy_stats
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import adfuller

from src.data._constants import load_constant as load_data_constant
from src.labels.weights import compute_concurrency_and_uniqueness

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

BAR_TYPES: Final[tuple[str, ...]] = ("time", "dollar", "volume", "tick_imbalance")

# ADF/gesdd: estatística fora desta faixa não tem leitura econômica -- um
# valor além disso é sinal de SVD corrompida (numpy#20384), não de rejeição
# forte de H0.
#
# CORREÇÃO 2026-08-15 (achado no 1º run canônico real de M2): o valor
# original (30.0) partiu de uma afirmação nunca verificada contra dado real
# deste projeto ("ADF costuma ficar bem dentro de [-10,10] mesmo em séries
# fortemente estacionárias") -- estava ERRADA pra amostra grande. O run real
# disparou o gate em TODAS as 13 tasks de barra de tempo (n de 40.943 a
# 231.551), sempre com |adf_stat| entre 60 e 145 -- padrão sistemático, não
# anomalia isolada, sinal de que o limiar estava errado, não o dado.
# Verificado: adf_stat/sqrt(n) fica em ~-0,30 nas 13 tasks, consistente
# entre símbolos e TFs -- exatamente o comportamento esperado de uma
# estatística genuína (ADF diverge com sqrt(n) sob forte estacionariedade;
# quanto maior a amostra, mais extremo o valor, sem ser corrupção). O modo
# de falha real (numpy#20384) produz algo qualitativamente diferente --
# `-1,27e14` no caso sintético já capturado por este gate (12 ordens de
# grandeza acima de qualquer valor real observado aqui), não uma dezena de
# vezes maior. Novo limiar (2000) mantém margem enorme dos dois lados: bem
# acima de qualquer extrapolação razoável do padrão sqrt(n) observado
# (~-0,30 x sqrt(n) chegaria a ~-300 só em n=1.000.000, um TF/ativo que não
# existe neste projeto), e ainda assim 11 ordens de magnitude abaixo do
# padrão de corrupção real já visto.
_ADF_STAT_PLAUSIBLE_ABS_MAX: Final[float] = 2000.0


@dataclass(frozen=True, slots=True)
class BarComparisonMetrics:
    """Resumo por (symbol, tf, bar_type) -- `NaN` explícito onde a amostra
    é pequena demais pros testes (nunca um zero fabricado)."""

    symbol: str
    tf: str
    bar_type: str
    n_bars: int
    n_returns: int
    jarque_bera_stat: float
    jarque_bera_pvalue: float
    kurtosis_excess: float
    ljung_box_r_pvalue: float
    ljung_box_r2_pvalue: float
    adf_stat: float
    adf_pvalue: float
    avg_uniqueness: float


def _log_returns(close: FloatArray) -> FloatArray:
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(close))
    return r


def _run_adfuller(
    symbol: str, tf: str, bar_type: str, r: FloatArray, *, maxlag: int
) -> tuple[float, float]:
    """ADF sobre `r`, com duas correções sobre `adfuller(r, autolag="AIC")`
    ingênuo -- achado real de auditoria (`audit_engineering`, 2026-08-15,
    pesquisa web antes de codar, não hipótese):

    1. **`autolag=None` (lag FIXO em `maxlag`, não busca 1..maxlag').**
       `adfuller(autolag="AIC")` sem `maxlag` explícito usa o default
       `12*(nobs/100)^0.25` -- para `nobs≈164 mil` (o tamanho típico de
       barra de 15m dos 5 ativos), isso é `maxlag≈76`, e a busca AIC ajusta
       UMA regressão OLS (logo, UMA SVD via `np.linalg.svd` dentro de
       `pinv_extended`) por cada lag testado -- até 76 SVDs por chamada,
       cada uma sobre uma matriz de desenho `(nobs, lag+2)`. Isso é um
       problema conhecido e documentado da própria `statsmodels`
       (`autolag` "wasting memory", issue #1849, aberta desde 2014, ainda
       sem fix definitivo em 0.14.6) -- não uma suposição. Fixar
       `maxlag=ljung_box_lags` (mesma constante do Ljung-Box, mesma
       justificativa de "nº de lags relevante pra retorno financeiro
       intradiário") faz UMA única regressão em vez de até 76 -- reduz o
       nº de SVDs por task em ~76x e o tamanho da MAIOR matriz testada de
       `(nobs, 78)` pra `(nobs, ljung_box_lags+2)`.
    2. **Blindagem contra falha conhecida do driver LAPACK `gesdd`.** Mesmo
       com (1), `np.linalg.svd` sobre matriz alta-e-estreita (`nobs` linhas
       × poucas colunas) usa por padrão o driver `gesdd` (divide-and-
       conquer) do backend BLAS dos wheels do NumPy pro Windows/PyPI
       (OpenBLAS, confirmado por pesquisa -- não presumido) -- `gesdd` tem
       histórico documentado de falhar/vazar memória sob concorrência ou
       matrizes grandes independente do nº de threads (numpy#20384 "init_
       dgesdd failed init for large SVD"; OpenBLAS#3044 "GESDD fails when
       GESVD succeeds, depends on number of threads"; múltiplos issues de
       crash em matriz alta-e-estreita no próprio OpenBLAS). `numpy.linalg.
       svd` não expõe parâmetro de driver (diferente de `scipy.linalg.svd
       (..., lapack_driver=...)`), então não dá pra forçar `gesvd` sem
       monkey-patch frágil -- a defesa correta é capturar a falha (
       `MemoryError`/`numpy.linalg.LinAlgError`, ambas observadas em
       produção nesta sessão) e devolver NaN explícito pra ESSA célula, não
       deixar 1 task ruim derrubar as outras 19 do batch (mesma disciplina
       FCN de `_nan_metrics` -- não computável ≠ zero).

    3. **Gate de plausibilidade pós-cálculo, não só captura de exceção.**
       Achado de auditoria (`project_assurance`, 2026-08-15, WebFetch da
       issue real): `numpy#20384` documenta uma falha do `gesdd` que **não
       levanta exceção nenhuma** -- imprime uma mensagem C-level e pode
       devolver `u`/`s`/`vt` zerados ou não-inicializados, que fluem pro
       OLS interno do `adfuller` e saem como `adf_stat`/`adf_pvalue`
       FINITOS mas fabricados. O `except` acima cobre só os 2 modos de
       falha RUIDOSOS -- não cobre este. Defesa: estatística ADF pra
       retorno financeiro intradiário real não tem leitura econômica fora
       de `_ADF_STAT_PLAUSIBLE_ABS_MAX` (30) -- um valor além disso é sinal
       de corrupção numérica, não de rejeição forte de H0. Isso não é mais
       uma exceção a capturar (o bug não levanta nenhuma), é um prior de
       domínio explícito substituindo confiança cega no retorno da lib."""
    try:
        adf_result = adfuller(r, maxlag=maxlag, autolag=None)
        adf_stat, adf_pvalue = float(adf_result[0]), float(adf_result[1])
    except (MemoryError, np.linalg.LinAlgError) as exc:
        logger.warning(
            "analysis.m2_stats.adf_failed",
            symbol=symbol,
            tf=tf,
            bar_type=bar_type,
            n_returns=len(r),
            error=repr(exc),
        )
        return float("nan"), float("nan")

    if not np.isfinite(adf_stat) or abs(adf_stat) > _ADF_STAT_PLAUSIBLE_ABS_MAX:
        logger.warning(
            "analysis.m2_stats.adf_stat_implausible",
            symbol=symbol,
            tf=tf,
            bar_type=bar_type,
            n_returns=len(r),
            adf_stat=adf_stat,
        )
        return float("nan"), float("nan")
    return adf_stat, adf_pvalue


def _nan_metrics(
    symbol: str,
    tf: str,
    bar_type: str,
    n_bars: int,
    n_returns: int,
    *,
    avg_uniqueness: float = float("nan"),
) -> BarComparisonMetrics:
    """`avg_uniqueness` tem parâmetro próprio (default NaN só pro caso de
    task inteira ausente, `m2_bar_comparison._build_payload`) -- achado de
    auditoria 2026-08-15: antes desta correção, todo caminho que caía aqui
    (incluindo amostra pequena DEMAIS PROS TESTES DE RETORNO, mas com
    close_time suficiente) recebia avg_uniqueness=NaN mesmo quando
    `compute_concurrency_and_uniqueness` conseguia computar um valor real
    -- conflava dois requisitos de amostra distintos (`n_returns>>lags` só
    vale pra JB/Ljung-Box/ADF; uniqueness só precisa de `t0/t1` válidos)."""
    nan = float("nan")
    return BarComparisonMetrics(
        symbol=symbol,
        tf=tf,
        bar_type=bar_type,
        n_bars=n_bars,
        n_returns=n_returns,
        jarque_bera_stat=nan,
        jarque_bera_pvalue=nan,
        kurtosis_excess=nan,
        ljung_box_r_pvalue=nan,
        ljung_box_r2_pvalue=nan,
        adf_stat=nan,
        adf_pvalue=nan,
        avg_uniqueness=avg_uniqueness,
    )


def compute_bar_statistics(
    symbol: str,
    tf: str,
    bar_type: str,
    bars: pl.DataFrame,
    *,
    time_stop_ms: int,
    ljung_box_lags: int,
) -> BarComparisonMetrics:
    """Núcleo puro (sem IO) -- JB/curtose/Ljung-Box(r,r²)/ADF sobre
    log-retorno de `close`, e unicidade média via `compute_concurrency_and_
    uniqueness` sobre `close_time`. Testável isoladamente com `bars`
    sintético, ao contrário das funções de `m2_worker.py` (IO real).
    `time_stop_ms` é FIXO entre chamadas com `tf` diferente -- ver
    docstring de `m2_bar_comparison.py` (`TIME_STOP_REFERENCE_TF`) -- este
    núcleo só recebe o valor já calculado, não recalcula por `tf`."""
    n_bars = bars.height
    close = bars["close"].cast(pl.Float64).to_numpy()
    r = _log_returns(close)
    n_returns = int(np.sum(np.isfinite(r)))

    # avg_uniqueness computado ANTES do gate de min_obs abaixo, de propósito
    # -- achado de auditoria 2026-08-15: `compute_concurrency_and_uniqueness`
    # só precisa de `t0`/`t1` válidos, não de `n_returns>>lags` (esse
    # requisito é específico de JB/Ljung-Box/ADF, que dependem da
    # aproximação qui-quadrado). Conflar os dois fazia uma amostra pequena
    # DEMAIS PROS TESTES DE RETORNO devolver avg_uniqueness=NaN mesmo
    # quando o valor era perfeitamente computável.
    close_time = bars["close_time"].cast(pl.Int64).to_numpy()
    t0 = close_time.astype(np.int64)
    t1 = t0 + time_stop_ms
    _, uniqueness = compute_concurrency_and_uniqueness(t0, t1)
    avg_uniqueness = float(np.mean(uniqueness)) if uniqueness.size else float("nan")

    # bars_comparison_min_obs_multiplier -- achado de auditoria 2026-08-15:
    # o valor antigo (4, literal local sem provenance) subestimava o
    # mínimo seguro pro Ljung-Box (aproximação qui-quadrado exige n>>lags);
    # movido pra constants.yaml com derivação da literatura (Tsay).
    min_obs_multiplier = int(load_data_constant("bars_comparison_min_obs_multiplier"))
    min_obs = min_obs_multiplier * ljung_box_lags
    if n_returns < min_obs:
        return _nan_metrics(symbol, tf, bar_type, n_bars, n_returns, avg_uniqueness=avg_uniqueness)
    r_finite = r[np.isfinite(r)]

    jb = scipy_stats.jarque_bera(r_finite)
    kurt = float(scipy_stats.kurtosis(r_finite, fisher=True))
    lb_r = acorr_ljungbox(r_finite, lags=[ljung_box_lags], return_df=True)
    lb_r2 = acorr_ljungbox(r_finite**2, lags=[ljung_box_lags], return_df=True)
    adf_stat, adf_pvalue = _run_adfuller(symbol, tf, bar_type, r_finite, maxlag=ljung_box_lags)

    return BarComparisonMetrics(
        symbol=symbol,
        tf=tf,
        bar_type=bar_type,
        n_bars=n_bars,
        n_returns=n_returns,
        jarque_bera_stat=float(jb.statistic),
        jarque_bera_pvalue=float(jb.pvalue),
        kurtosis_excess=kurt,
        ljung_box_r_pvalue=float(lb_r["lb_pvalue"].iloc[0]),
        ljung_box_r2_pvalue=float(lb_r2["lb_pvalue"].iloc[0]),
        adf_stat=adf_stat,
        adf_pvalue=adf_pvalue,
        avg_uniqueness=avg_uniqueness,
    )
