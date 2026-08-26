"""GRUPO K — Temporal e calendário (§2.12). Lote A da liberação de
features (H5, 2026-08-24) — K01-K04. Todas T2 (nenhuma promovida a
T1 por esta implementação, §0.2 R4/§2.13). Explicitamente fora deste
grupo: K05 (`hours_to_funding`, o próprio PRD diz "ver E05f" — alias de
`group_e.e05f_time_to_funding_h`, não uma feature separada), K06
("gatilho de Risk, não feature", PRD literal) e K07 (precisa de
calendário de vencimento de opções, fonte externa ausente).

**`K08_days_since_halving` REMOVIDA 2026-08-26** (achado de `AG-263`,
sobrevive à reprovação de `project_assurance` em `ADR-005 §11.4`, item
3): aplicava as 4 datas de halving do BITCOIN aos 5 ativos sem eixo de
símbolo — pra ETH/SOL/BNB/XRP é rampa monótona de calendário com nome
econômico, eixo de sobreajuste por época dentro do fold. Ver
`audit/architecture_gaps_log.yaml::AG-263` (achado original) e o
addendum de remoção na mesma entrada.

Única fonte de dado: o timestamp da própria barra (`close_time`, epoch
ms) — nenhuma dependência de OHLCV/funding/OI. Núcleo 100% puro (Idioma
A, `docs/nucleo_casca_design_doc_2026-08-23.md`): matemática de
timestamp determinística, sem IO, sem suavização/estado — não se aplica
a distinção rolante-vs-expansiva de `support.py` (cada barra depende só
do PRÓPRIO timestamp, nunca de uma janela de barras vizinhas).

Constantes de PERÍODO do calendário (24h/dia, 7 dias/semana, 2π
radianos) são definicionais, não hiperparâmetro de negócio — mesma
classe das constantes de fórmula fechada da literatura (`4*ln2` em
`support.parkinson_vol`, `0.34/1.34` em `support.yang_zhang_vol`) que
`constants.yaml` já documenta como isentas de entrada própria. Fronteiras
de SESSÃO (K04) SÃO decisão com proveniência real (`LITERATURE`,
pesquisa web) e tem entrada em `constants.yaml`.
"""

from __future__ import annotations

import numpy as np

from ..support import FloatArray

_MS_PER_DAY: int = 86_400_000  # noqa: magic-number -- ms/dia, conversão de unidade, não hiperparâmetro
_MS_PER_HOUR: float = 3_600_000.0  # noqa: magic-number -- ms/hora, conversão de unidade
_HOURS_PER_DAY: float = 24.0  # noqa: magic-number -- definicional (calendário), não hiperparâmetro
_DAYS_PER_WEEK: float = 7.0  # noqa: magic-number -- definicional (calendário), não hiperparâmetro
_WEEKEND_DOW: tuple[float, float] = (2.0, 3.0)  # noqa: magic-number -- índices de sábado/domingo na convenção dow=0..6 de _utc_day_of_week (0=quinta, época Unix), não hiperparâmetro


def _utc_hour_of_day(close_time_ms: FloatArray) -> FloatArray:
    """Hora UTC fracionária `[0, 24)` a partir de epoch ms."""
    ms_since_epoch = close_time_ms.astype(np.int64)
    ms_in_day = ms_since_epoch % _MS_PER_DAY
    out: FloatArray = ms_in_day.astype(np.float64) / _MS_PER_HOUR
    return out


def _utc_day_of_week(close_time_ms: FloatArray) -> FloatArray:
    """Dia da semana UTC `[0,7)`, 0=quinta — a época Unix (1970-01-01)
    foi uma quinta-feira; `floor(dias_desde_epoch) % 7` reproduz isso sem
    depender de biblioteca de calendário (matemática pura de timestamp,
    determinística, mesmo espírito de `support.wilder_smooth` preferir
    laço explícito a uma dependência externa quando a definição literal
    importa)."""
    ms_since_epoch = close_time_ms.astype(np.int64)
    days_since_epoch = ms_since_epoch // _MS_PER_DAY
    out: FloatArray = (days_since_epoch % 7).astype(np.float64)  # noqa: magic-number -- dias/semana, definicional
    return out


def k01_hour_sin(close_time_ms: FloatArray) -> FloatArray:
    """`sin(2π × hora_UTC / 24)` — §2.12 K01."""
    hour = _utc_hour_of_day(close_time_ms)
    out: FloatArray = np.sin(2.0 * np.pi * hour / _HOURS_PER_DAY)  # noqa: magic-number -- 2π, constante matemática
    return out


def k01_hour_cos(close_time_ms: FloatArray) -> FloatArray:
    """`cos(2π × hora_UTC / 24)` — §2.12 K01."""
    hour = _utc_hour_of_day(close_time_ms)
    out: FloatArray = np.cos(2.0 * np.pi * hour / _HOURS_PER_DAY)  # noqa: magic-number -- 2π, constante matemática
    return out


def k02_dow_sin(close_time_ms: FloatArray) -> FloatArray:
    """`sin(2π × dia_da_semana_UTC / 7)` — §2.12 K02."""
    dow = _utc_day_of_week(close_time_ms)
    out: FloatArray = np.sin(2.0 * np.pi * dow / _DAYS_PER_WEEK)  # noqa: magic-number -- 2π, constante matemática
    return out


def k02_dow_cos(close_time_ms: FloatArray) -> FloatArray:
    """`cos(2π × dia_da_semana_UTC / 7)` — §2.12 K02."""
    dow = _utc_day_of_week(close_time_ms)
    out: FloatArray = np.cos(2.0 * np.pi * dow / _DAYS_PER_WEEK)  # noqa: magic-number -- 2π, constante matemática
    return out


def k03_is_weekend(close_time_ms: FloatArray) -> FloatArray:
    """`1.0` se sábado ou domingo UTC, senão `0.0` — §2.12 K03. Época
    Unix é quinta (`dow=0` em `_utc_day_of_week`) → sábado=`dow 2`,
    domingo=`dow 3`."""
    dow = _utc_day_of_week(close_time_ms)
    out: FloatArray = np.isin(dow, _WEEKEND_DOW).astype(np.float64)
    return out


def k04_session_asia(
    close_time_ms: FloatArray, asia_start_h: float, asia_end_h: float
) -> FloatArray:
    """`1.0` se a hora UTC da barra está em `[asia_start_h, asia_end_h)`
    — §2.12 K04. Partição MUTUAMENTE EXCLUSIVA e fixa (sem horário de
    verão) das 24h entre 3 sessões — simplificação deliberada da
    convenção real de mercado (sessões se sobrepõem e deslocam com DST;
    pesquisa web: Tóquio 00:00-09:00 UTC, Londres 07:00/08:00-16:00/17:00
    UTC, Nova York 12:00/13:00-21:00/22:00 UTC) porque K04 pede "sessão
    DOMINANTE" (uma só por barra, PRD §2.12), não as 3 janelas
    sobrepostas literais. Fronteiras usadas (00-08 Ásia / 08-16 Europa /
    16-24 EUA UTC) em `constants.yaml` (`feature_k04_asia_start_hour`
    etc.), `provenance: LITERATURE` com a ressalva de simplificação
    documentada ali."""
    hour = _utc_hour_of_day(close_time_ms)
    out: FloatArray = ((hour >= asia_start_h) & (hour < asia_end_h)).astype(np.float64)
    return out


def k04_session_europe(
    close_time_ms: FloatArray, europe_start_h: float, europe_end_h: float
) -> FloatArray:
    """`1.0` se a hora UTC da barra está em `[europe_start_h,
    europe_end_h)` — §2.12 K04. Ver docstring de `k04_session_asia`."""
    hour = _utc_hour_of_day(close_time_ms)
    out: FloatArray = ((hour >= europe_start_h) & (hour < europe_end_h)).astype(np.float64)
    return out


def k04_session_us(close_time_ms: FloatArray, us_start_h: float, us_end_h: float) -> FloatArray:
    """`1.0` se a hora UTC da barra está em `[us_start_h, us_end_h)` —
    §2.12 K04. Ver docstring de `k04_session_asia`. `us_end_h=24` fecha
    o dia (`hour < 24` sempre verdadeiro para hora fracionária válida)."""
    hour = _utc_hour_of_day(close_time_ms)
    out: FloatArray = ((hour >= us_start_h) & (hour < us_end_h)).astype(np.float64)
    return out


