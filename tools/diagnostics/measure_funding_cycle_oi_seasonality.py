"""Mede os dois fatos empíricos de que a decisão sobre `feature_e10f_
oi_change_window` (`config/constants.yaml:675-691`) depende, sem decidir
nada sozinho -- resposta direta ao item delegado no comentário dessa
entrada: "Verificar intervalo de funding REAL por símbolo antes de assumir
8h uniforme entre os 5 ativos -- delegado a agente" (AG-027 addendum,
`audit/architecture_gaps_log.yaml`).

CONTEXTO DA HIPÓTESE (Manager, texto literal de `constants.yaml:684-689`):
`feature_e10f_oi_change_window=48` é um z-score ROLANTE de `Δln(oi_
contracts)` (`src/features/groups/group_e.py::e10f_oi_change_z_48`,
linhas 23-34) com janela fixa de 48 barras de 15m = 12h. Se o ciclo de
liquidação de funding da Binance for de fato ~8h (32 barras), 48 é o PIOR
valor possível de uma vizinhança -- 1,5 ciclos, o que faz a baseline
rolante misturar, em momentos diferentes, uma proporção INCONSISTENTE de
"ciclo antigo" vs "ciclo novo" (contaminação de fase). Um múltiplo exato
(32 ou 64) daria relação de fase consistente. Mas isso só é motivo real
pra mudar a janela se (a) o intervalo de funding REAL for ~8h para os 5
ativos -- contratos diferentes na Binance podem ter intervalos diferentes,
e isso já mudou historicamente para certos pares em alta volatilidade
(4h/1h) -- e (b) existir sazonalidade REAL (não ruído) em `Δln(OI)`
alinhada a esse ciclo. As duas perguntas abaixo, nesta ordem.

PARTE 1 -- intervalo de funding real por símbolo. `schemas.py::FUNDING`
já declara `funding_interval_hours` (linha 140) como coluna NATIVA do
dado -- não é calculado por este projeto: `download_funding`
(`src/data/download.py:502-544`) grava literalmente o que o CSV mensal
oficial de `data.binance.vision` reporta por linha (a Binance passou a
publicar esse campo no arquivo público depois que o mecanismo de
intervalo dinâmico existiu). `src/data/checks.py::check_funding_interval`
(linhas 358-377) já mede o GAP real entre `calc_time` consecutivos e
compara contra o valor declarado -- reusado aqui via `lake.query_funding`
+ `checks.check_funding_interval`, não reimplementado. A única medição já
no disco (`data/quality_reports/quality_report_funding_v1.json`) cobre só
BTCUSDT, só 2026-01-01→2026-07-31 (7 meses recentes) -- não decide a
pergunta pros outros 4 ativos nem descarta mudança de regime em janelas
mais antigas (2021-2023, com eventos de volatilidade extrema conhecidos:
LUNA maio/2022, FTX nov/2022). Este script cobre a HISTÓRIA COMPLETA
medida (`SYMBOL_START_DATE`/`END_DATE`,
`src/analysis/volatility_comparison.py:127-134`, mesmo range já auditado
em AG-027 addendum ponto 5) dos 5 ativos, e além do agregado pooled de
`check_funding_interval`, faz run-length encoding de `funding_interval_
hours` pra listar EPISÓDIOS concretos (início/fim/duração) de qualquer
trecho que divirja do valor modal -- não só "houve inconsistência algures
no agregado".

PARTE 2 -- sazonalidade real em `Δln(oi_contracts)` alinhada ao ciclo
medido na Parte 1. Reusa `src.features._sources.load_bars_15m`/
`load_oi_aligned` (o mesmo alinhamento causal asof-backward que já
alimenta `oi_contracts_aligned` em produção -- não reimplementado) e
replica a fórmula de `group_e.py:23-34` (`np.log` + `np.diff`) SEM o
z-score rolante -- só a série de log-diferenças. Duas medições
complementares, deliberadamente não só uma (evita o viés de testar SÓ a
hipótese e "achar" o que se procurava):

  (i) ACF + Ljung-Box nos lags 1×/2×/3× do ciclo de funding MEDIDO na
      Parte 1 (não fixado a priori em 32) -- mesmo padrão já usado em
      `src/analysis/m2_stats.py` (`statsmodels.stats.diagnostic.
      acorr_ljungbox`, `return_df=True`, extração posicional via
      `.iloc[i]`);
  (ii) periodograma (`scipy.signal.periodogram`) sem hipótese -- varre
       TODOS os períodos resolvíveis (até `n/10` barras) e reporta os
       picos de maior potência, pra ver se o ciclo de funding é de fato
       um pico dominante do espectro ou só um lag específico escolhido a
       priori que por acaso teve autocorrelação não-nula.

NOTA DE INTERPRETAÇÃO ESTATÍSTICA (importante pro Manager ler o output
certo): com `n` da ordem de 10^5-10^6 barras, a banda de "ruído branco" a
95% (`1,96/√n`) fica na casa de 0,003-0,006 -- QUALQUER autocorrelação
real, por menor que seja economicamente, passa nesse limiar de
significância estatística. Significância != magnitude. Por isso o script
reporta também `background_acf_typical_abs` (magnitude TÍPICA de ACF em
lags fora do ciclo, mesma série) -- o teste que importa é se o lag do
ciclo se DESTACA do nível típico de autocorrelação da série, não se é
"estatisticamente diferente de zero" (quase garantido nesta escala de
amostra).

DUAS RESTRIÇÕES DELIBERADAS, mesmo padrão de
`measure_time_stop_slack.py`/`measure_barrier_touch_probability.py`:

1. **NÃO decide se `feature_e10f_oi_change_window` deve mudar.** Só mede
   os dois fatos empíricos que a decisão do Manager depende (constants.
   yaml:684-689). Se sazonalidade real existir E o ciclo for consistente,
   o candidato é um múltiplo exato (32 ou 64) -- mover a constante é
   decisão do Manager, feita DEPOIS de ler este output, não deste script.
2. **NÃO é sweep/otimização -- 0 trials.** Leitura determinística de
   parquet já em disco (`data/capacity/funding/`, `data/capacity/
   metrics/`, `data/capacity/klines_1m/`) + estatística descritiva
   (ACF/Ljung-Box/periodograma). Nenhum modelo treinado, nenhum
   hiperparâmetro tocado, `N_lifetime` não incrementa.

Contexto adicional (não decide nada, só calibra expectativa): `docs/
SPRINT_LOG.md` (~linha 1416, achado "D4 -- E10f como candidata") já mediu
estabilidade de sinal (`|IC|×consistência²`) baixa pra E10f nos dois lados
(long 0,0054, short 0,0013) -- mesma ordem de grandeza da fragilidade já
medida pra E02f. Mesmo que a Parte 2 confirme sazonalidade real, isso não
implica que corrigir a janela torna E10f um sinal forte -- é sobre não
deixar um artefato de desenho (contaminação de fase) subtrair do que quer
que o sinal real seja.

Rodar depois que os parquets de `funding`/`metrics`/`klines_1m` existirem
pro(s) símbolo(s) de interesse (já existem pros 5 ativos, backfill
completo -- ver CLAUDE.md "Estado atual")."""

from __future__ import annotations

import math
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

# Script standalone -- sem isto, `from src...` abaixo falha com
# `ModuleNotFoundError: No module named 'src'` quando invocado por caminho
# direto (`uv run python tools/diagnostics/<este arquivo>.py`), já que só o
# diretório do script entra em sys.path[0] nesse modo (diferente de `-m`, que
# usa o cwd). Achado real (2026-08-16): os 8 scripts de tools/diagnostics/
# que importam de `src.*` tinham este mesmo bug.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy.signal import periodogram
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import acf

from src.analysis.volatility_comparison import END_DATE, SYMBOL_START_DATE
from src.data import checks, lake
from src.data._constants import load_constant as load_data_constant
from src.features._sources import load_bars_15m, load_oi_aligned

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT")

_BARS_PER_HOUR: int = 4  # 15m -- 4 barras/hora, usado só pra converter horas declaradas em barras
_MS_PER_DAY: int = 86_400_000

# ACF/periodograma -- constantes de MEDIÇÃO deste script (não hiperparâmetro
# de produção, por isso local em vez de constants.yaml -- mesmo racional de
# `_CEILING_PROXIMITY_BARS` em measure_time_stop_slack.py).
# ~4,2 dias a 15m -- cobre 3x qualquer ciclo plausível (1h-24h)
_ACF_MAX_LAG_BARS: int = 400
# ignora lags 1-4 (memória de curto prazo/microestrutura, não funding)
_BACKGROUND_ACF_LAG_START: int = 5
# exige >=50 repetições do ciclo -- ACF/periodograma não confiáveis com poucas
_MIN_CYCLES_FOR_SEASONALITY: int = 50
_PERIODOGRAM_TOP_K: int = 5
# período só é "resolvível" se <= n/divisor (>=10 repetições na amostra)
_PERIODOGRAM_RESOLVABLE_DIVISOR: int = 10

_ACF_CI_Z_SCORE: float = 1.96  # noqa: magic-number -- constante estatística universal (z 95% CI), não parâmetro de negócio do motor
_LJUNG_BOX_ALPHA: float = 0.05  # noqa: magic-number -- convenção estatística padrão (5%), não parâmetro do motor


@dataclass(frozen=True, slots=True)
class FundingRegimeSummary:
    symbol: str
    n_rows: int
    mode_declared_hours: int
    cycle_bars: int
    declared_hours_counts: dict[int, int]
    measured_median_gap_hours: float
    measured_std_gap_hours: float
    inconsistent_rows: int
    n_regime_change_episodes: int
    episodes: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class SeasonalityMeasurement:
    symbol: str
    n_obs: int
    cycle_bars: int
    white_noise_band: float
    acf_lag1: float
    acf_at_cycle_1x: float
    acf_at_cycle_2x: float
    acf_at_cycle_3x: float
    ljung_box_pvalue_cycle_1x: float
    ljung_box_pvalue_cycle_2x: float
    ljung_box_pvalue_cycle_3x: float
    background_acf_typical_abs: float
    periodogram_top_peaks: list[dict[str, float]]
    periodogram_closest_peak_to_cycle_bars: float | None
    periodogram_closest_peak_delta_bars: float | None


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _funding_interval_episodes(df: pl.DataFrame, mode_hours: int) -> list[dict[str, object]]:
    """Run-length encoding de `funding_interval_hours` declarado (ordenado
    por `calc_time`) -- retorna só os trechos que DIVERGEM do valor modal
    (episódios candidatos a mudança de regime), com início/fim/duração.
    Complementa `checks.check_funding_interval` (que só agrega um
    médio/desvio pooled) com O ONDE de qualquer divergência."""
    values = df["funding_interval_hours"].cast(pl.Int64).to_list()
    times = df["calc_time"].cast(pl.Int64).to_list()
    n = len(values)
    episodes: list[dict[str, object]] = []
    run_start = 0
    for i in range(1, n + 1):
        if i == n or values[i] != values[run_start]:
            run_value = values[run_start]
            if run_value != mode_hours:
                start_ms = times[run_start]
                end_ms = times[i - 1]
                episodes.append(
                    {
                        "declared_hours": run_value,
                        "start": _ms_to_iso(start_ms),
                        "end": _ms_to_iso(end_ms),
                        "n_rows": i - run_start,
                        "duration_days": round((end_ms - start_ms) / _MS_PER_DAY, 2),  # noqa: unguarded-ratio -- _MS_PER_DAY e' constante de conversao de unidade fixa (86_400_000), nunca zero
                    }
                )
            run_start = i
    return episodes


def measure_funding_interval(symbol: str) -> FundingRegimeSummary | None:
    """Parte 1 -- intervalo de funding real, história completa medida."""
    start = SYMBOL_START_DATE[symbol]
    df = lake.query_funding(symbol, start, END_DATE)
    if df.is_empty():
        logger.warning(
            "diagnostics.measure_funding_cycle_oi_seasonality.no_funding_data",
            symbol=symbol,
        )
        return None

    df = df.sort("calc_time")
    n_rows = df.height

    counts_df = df["funding_interval_hours"].value_counts().sort("funding_interval_hours")
    declared_hours_counts: dict[int, int] = dict(
        zip(
            counts_df["funding_interval_hours"].cast(pl.Int64).to_list(),
            counts_df["count"].cast(pl.Int64).to_list(),
            strict=True,
        )
    )
    mode_declared_hours = max(declared_hours_counts, key=lambda h: declared_hours_counts[h])
    cycle_bars = mode_declared_hours * _BARS_PER_HOUR

    interval_result = checks.check_funding_interval(df)  # reuso -- checks.py:358-377
    episodes = _funding_interval_episodes(df, mode_declared_hours)

    summary = FundingRegimeSummary(
        symbol=symbol,
        n_rows=n_rows,
        mode_declared_hours=mode_declared_hours,
        cycle_bars=cycle_bars,
        declared_hours_counts=declared_hours_counts,
        measured_median_gap_hours=round(interval_result.measured_median_gap_hours, 6),
        measured_std_gap_hours=round(interval_result.measured_std_gap_hours, 6),
        inconsistent_rows=interval_result.inconsistent_rows,
        n_regime_change_episodes=len(episodes),
        episodes=episodes,
    )

    logger.info(
        "diagnostics.measure_funding_cycle_oi_seasonality.part1_symbol_done",
        start=start,
        end=END_DATE,
        **asdict(summary),
    )
    return summary


def _delta_log_oi(symbol: str, start: str, end: str) -> FloatArray:
    """Mesma fórmula de `group_e.e10f_oi_change_z_48` (group_e.py:23-34),
    SEM o z-score rolante -- só `Δln(oi_contracts)`, alinhado causalmente
    ao grid de 15m via `_sources.load_bars_15m`/`load_oi_aligned` (reuso,
    não reimplementação do asof-join)."""
    bars = load_bars_15m(symbol, start, end)
    oi = load_oi_aligned(bars, symbol, start, end)
    oi_arr = oi.cast(pl.Float64).to_numpy().astype(np.float64)
    log_oi = np.log(oi_arr)
    n = log_oi.shape[0]
    delta = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        delta[1:] = np.diff(log_oi)
    return delta


def _trim_leading_nan(delta: FloatArray, *, symbol: str) -> FloatArray:
    """Remove só o bloco de NaN inicial (warmup antes do primeiro ponto de
    OI -- `Δln` do primeiro índice é sempre NaN por construção, mais
    quantos bars faltarem até o primeiro evento de `metrics`). NaN
    remanescente NO MEIO da série seria inesperado dado o forward-fill do
    asof-join backward -- se aparecer, é logado e descartado (não
    interpolado -- não inventa dado), mas quebra o espaçamento uniforme de
    15m, então é sinalizado explicitamente pra quem for ler o resultado."""
    finite = np.isfinite(delta)
    if not finite.any():
        return np.empty(0, dtype=np.float64)
    first_valid = int(np.argmax(finite))
    trimmed = delta[first_valid:]
    remaining_nan = int(np.sum(~np.isfinite(trimmed)))
    if remaining_nan:
        trimmed = trimmed[np.isfinite(trimmed)]
        logger.warning(
            "diagnostics.measure_funding_cycle_oi_seasonality.mid_series_nan_dropped",
            symbol=symbol,
            n_dropped=remaining_nan,
            note=(
                "NaN apos o primeiro OI valido -- inesperado dado o "
                "forward-fill do asof-join backward; linhas descartadas "
                "(nao interpoladas), espacamento de 15m local nao mais "
                "uniforme -- interpretar ACF/periodograma com cautela"
            ),
        )
    return trimmed


def measure_oi_seasonality(symbol: str, cycle_bars: int) -> SeasonalityMeasurement | None:
    """Parte 2 -- ACF/Ljung-Box nos múltiplos do ciclo medido na Parte 1 +
    periodograma sem hipótese, sobre `Δln(oi_contracts)` completo."""
    start = SYMBOL_START_DATE[symbol]
    raw_delta = _delta_log_oi(symbol, start, END_DATE)
    delta = _trim_leading_nan(raw_delta, symbol=symbol)
    n = delta.shape[0]

    min_required = cycle_bars * _MIN_CYCLES_FOR_SEASONALITY
    if n < min_required:
        logger.warning(
            "diagnostics.measure_funding_cycle_oi_seasonality.series_too_short",
            symbol=symbol,
            n_obs=n,
            cycle_bars=cycle_bars,
            min_required=min_required,
        )
        return None

    max_lag = min(_ACF_MAX_LAG_BARS, n // 3)
    lags_of_interest = [
        lag for lag in (cycle_bars, cycle_bars * 2, cycle_bars * 3) if 0 < lag <= max_lag
    ]
    if not lags_of_interest:
        logger.warning(
            "diagnostics.measure_funding_cycle_oi_seasonality.cycle_exceeds_max_lag",
            symbol=symbol,
            cycle_bars=cycle_bars,
            max_lag=max_lag,
        )
        return None

    acf_vals = acf(delta, nlags=max_lag, fft=True)
    white_noise_band = _ACF_CI_Z_SCORE / math.sqrt(n)  # noqa: unguarded-ratio -- n >= min_required > 0, guardado acima

    def _acf_at(lag: int) -> float:
        return float(acf_vals[lag]) if lag < acf_vals.shape[0] else float("nan")

    background_lags = np.arange(_BACKGROUND_ACF_LAG_START, max_lag + 1)
    background_acf_typical_abs = (
        float(np.mean(np.abs(acf_vals[background_lags])))
        if background_lags.size
        else float("nan")
    )

    lb = acorr_ljungbox(delta, lags=lags_of_interest, return_df=True)
    lb_pvalues = {lag: float(lb["lb_pvalue"].iloc[i]) for i, lag in enumerate(lags_of_interest)}

    freqs, power = periodogram(delta)
    positive = freqs > 0
    freqs_pos = freqs[positive]
    power_pos = power[positive]
    periods_bars = 1.0 / freqs_pos  # noqa: unguarded-ratio -- freqs_pos e' freqs[freqs > 0] (linha anterior), filtro de mascara, nunca zero
    resolvable = periods_bars <= (n // _PERIODOGRAM_RESOLVABLE_DIVISOR)  # noqa: unguarded-ratio -- _PERIODOGRAM_RESOLVABLE_DIVISOR e' constante local positiva (10), nunca zero
    power_r = power_pos[resolvable]
    periods_r = periods_bars[resolvable]

    total_power = float(power_r.sum())
    top_peaks: list[dict[str, float]] = []
    closest_peak_period: float | None = None
    closest_peak_delta: float | None = None
    if total_power <= 0:
        logger.warning(
            "diagnostics.measure_funding_cycle_oi_seasonality.degenerate_periodogram",
            symbol=symbol,
        )
    else:
        order = np.argsort(power_r)[::-1][:_PERIODOGRAM_TOP_K]
        top_peaks = [
            {
                "period_bars": round(float(periods_r[i]), 2),
                "power_share": round(float(power_r[i]) / total_power, 6),
            }
            for i in order
        ]
        closest = min(top_peaks, key=lambda p: abs(p["period_bars"] - cycle_bars))
        closest_peak_period = closest["period_bars"]
        closest_peak_delta = round(abs(closest_peak_period - cycle_bars), 2)

    result = SeasonalityMeasurement(
        symbol=symbol,
        n_obs=n,
        cycle_bars=cycle_bars,
        white_noise_band=round(white_noise_band, 6),
        acf_lag1=round(_acf_at(1), 6),
        acf_at_cycle_1x=round(_acf_at(cycle_bars), 6),
        acf_at_cycle_2x=round(_acf_at(cycle_bars * 2), 6),
        acf_at_cycle_3x=round(_acf_at(cycle_bars * 3), 6),
        ljung_box_pvalue_cycle_1x=lb_pvalues.get(cycle_bars, float("nan")),
        ljung_box_pvalue_cycle_2x=lb_pvalues.get(cycle_bars * 2, float("nan")),
        ljung_box_pvalue_cycle_3x=lb_pvalues.get(cycle_bars * 3, float("nan")),
        background_acf_typical_abs=round(background_acf_typical_abs, 6),
        periodogram_top_peaks=top_peaks,
        periodogram_closest_peak_to_cycle_bars=closest_peak_period,
        periodogram_closest_peak_delta_bars=closest_peak_delta,
    )

    logger.info(
        "diagnostics.measure_funding_cycle_oi_seasonality.part2_symbol_done",
        ljung_box_alpha=_LJUNG_BOX_ALPHA,
        **asdict(result),
    )
    return result


def main() -> None:
    current_window_bars = int(load_data_constant("feature_e10f_oi_change_window"))

    funding_summaries: dict[str, FundingRegimeSummary] = {}
    for symbol in _SYMBOLS:
        summary = measure_funding_interval(symbol)
        if summary is not None:
            funding_summaries[symbol] = summary

    if not funding_summaries:
        logger.warning(
            "diagnostics.measure_funding_cycle_oi_seasonality.no_data",
            note="nenhum simbolo tinha dado de funding -- rode o backfill primeiro",
        )
        return

    modes_by_symbol = {s: v.mode_declared_hours for s, v in funding_summaries.items()}
    all_consistent_8h = all(h == 8 for h in modes_by_symbol.values())  # noqa: magic-number -- 8 e' int, nao float, nao capturado pelo lint; comparacao contra o valor citado por nome no PRD (§ funding 8h), nao um hiperparametro do motor
    any_regime_change = any(v.n_regime_change_episodes > 0 for v in funding_summaries.values())

    logger.info(
        "diagnostics.measure_funding_cycle_oi_seasonality.part1_pooled",
        current_window_bars=current_window_bars,
        modes_by_symbol=modes_by_symbol,
        all_consistent_8h=all_consistent_8h,
        any_regime_change_episode=any_regime_change,
        note=(
            "se all_consistent_8h=True e any_regime_change_episode=False, a "
            "premissa 'funding real e 8h em todos os 5 ativos, sem mudanca "
            "de regime' esta confirmada -- a Parte 2 pode ler cycle_bars=32 "
            "uniformemente. Caso contrario, cycle_bars varia por "
            "simbolo/periodo -- ver 'episodes' de cada simbolo no evento "
            "part1_symbol_done antes de generalizar."
        ),
    )

    seasonality_results: dict[str, SeasonalityMeasurement] = {}
    for symbol, summary in funding_summaries.items():
        result = measure_oi_seasonality(symbol, summary.cycle_bars)
        if result is not None:
            seasonality_results[symbol] = result

    if not seasonality_results:
        logger.warning(
            "diagnostics.measure_funding_cycle_oi_seasonality.no_seasonality_data",
            note="nenhum simbolo teve serie de OI longa o bastante -- ver series_too_short acima",
        )
        return

    logger.info(
        "diagnostics.measure_funding_cycle_oi_seasonality.final_note",
        note=(
            "leitura pro Manager -- 'existe sazonalidade real de ~Xh, de "
            "magnitude Y' se, PRO MESMO simbolo, acf_at_cycle_1x/2x/3x "
            "forem consistentemente MAIORES em magnitude que "
            "background_acf_typical_abs (nao so 'estatisticamente != 0' -- "
            "com n desta ordem, white_noise_band ~0,003-0,006 deixa QUASE "
            "QUALQUER autocorrelacao real 'significante', entao o teste que "
            "importa e' relativo ao nivel tipico de ruido da propria serie, "
            "nao contra zero) E se periodogram_closest_peak_delta_bars for "
            "pequeno (pico de maior potencia do espectro cai perto do ciclo "
            "de funding por conta propria, nao so um lag especifico "
            "escolhido a priori que teve autocorrelacao != 0). Sem essa "
            "combinacao nos dois lados, 'nao ha sazonalidade detectavel "
            "alem de ruido' e' a leitura honesta. NAO mover "
            "feature_e10f_oi_change_window so por '48=1,5 ciclo soa "
            "estranho' -- decisao final e' do Manager, apos ler este "
            "output (ver docstring do modulo, restricoes 1 e 2)."
        ),
    )


if __name__ == "__main__":
    main()
