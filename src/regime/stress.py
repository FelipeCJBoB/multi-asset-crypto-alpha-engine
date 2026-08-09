"""Gatilhos de STRESS (R5) — §4.4 do PRD.

**Achado central do Sprint 5 (investigado, não presumido — CLAUDE.md "meça
antes de afirmar"): dos 10 gatilhos S1-S10, só 3 são computáveis hoje sobre
dado histórico com o dado que o repo tem no disco.**

| gatilho | computável? | por quê (resumo — detalhe completo na docstring de cada `sXX_*`) |
|---|---|---|
| S1 vol extrema | **sim** | `C07_vol_pctile_expanding` já existe (Sprint 4) |
| S2 spread extremo | não (hoje) | F02f não existe como feature (saiu de T1, §2.7.1) |
| S3 funding extremo | **sim** | `E02f_funding_z_expanding` já existe (Sprint 4) |
| S4 basis rompido | não | D12 `index_price` nunca foi baixado |
| S5 dado velho | não (por definição) | sinal de operação AO VIVO, não existe em histórico |
| S6 gap de barra | **sim** | reusa `data.checks.check_grid_completeness` (Sprint 3) |
| S7 liquidez rasa | não (como especificado) | `book_depth/` só tem buckets de 100bp+, sem 20bp |
| S8 janela de evento | não | nenhum calendário econômico (K06) coletado |
| S9 cascata de liquidação | não | `forceOrder` (F03) é WS ao vivo, não coletado |
| S10 mudança de filtro | não (hoje) | só 1 snapshot de `exchangeInfo` — sem 2º ponto |

Cada gatilho, computável ou não, é uma função própria que devolve um array
de `TriggerState` — nunca um `bool` puro. Um gatilho `NOT_COMPUTABLE` não é
"não disparou": é "não sei", e confundir os dois é exatamente o tipo de
falha silenciosa que a task pediu para evitar. `NOT_COMPUTABLE` nunca conta
como `TRIGGERED` na composição de R5 (§4.3, "qualquer gatilho de stress.py
dispara") — mas também nunca é reportado como `NOT_TRIGGERED`, preservando
a distinção na coluna interna por gatilho (só a coluna agregada
`stress_triggers` do output, §4.6, colapsa "NOT_TRIGGERED" e
"NOT_COMPUTABLE" em "ausente da lista", porque o schema do PRD só tem
espaço para os que dispararam).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.data import checks as data_checks
from src.data import resample as data_resample
from src.exchange import filters as exchange_filters
from src.features.support import FloatArray

from ._constants import load_constant
from ._paths import EXCHANGE_INFO_SNAPSHOTS_DIR

logger = structlog.get_logger(__name__)

TRIGGER_IDS: tuple[str, ...] = (
    "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10",
)  # fmt: skip


class TriggerState(Enum):
    """Estado tri-valorado de um gatilho, por barra.

    **Deliberadamente NÃO mistura `str` (`class TriggerState(str, Enum)`)**
    — tentativa inicial deste Sprint, revertida depois de medir um bug real:
    misturar `str` faz `numpy` tratar o member como string ao comparar um
    array `dtype=object` contra um escalar (`arr == TriggerState.TRIGGERED`)
    — `np.asarray(TriggerState.TRIGGERED)` usa `str(member)`
    (`"TriggerState.TRIGGERED"`, a representação COM o nome da classe, não
    o `.value`) truncada para o comprimento de `len(value)`, produzindo uma
    string sem sentido (`"TriggerState.TRIGGERED"` -> truncada para 9 chars
    = `"TriggerState.TRIGGE" -> "TS.TRIGGE"` conforme a classe) e uma
    comparação vetorizada que retorna `False` em TODA barra, SEM erro nem
    warning — exatamente o tipo de "False silencioso" que a task pediu
    para nunca deixar passar. Confirmado empiricamente neste Sprint com um
    repro mínimo antes de decidir a correção (não um palpite). `Enum` puro
    usa `PyObject_RichCompare` real por elemento em array `object` e não
    sofre desse problema."""

    TRIGGERED = "TRIGGERED"
    NOT_TRIGGERED = "NOT_TRIGGERED"
    NOT_COMPUTABLE = "NOT_COMPUTABLE"


# dtype=object, elementos TriggerState — numpy não tem enum array nativo
TriggerArray = NDArray[np.object_]
TimeArray = NDArray[np.int64]

# Não é hiperparâmetro nem constante de domínio — é a própria definição de
# calendário de "1 hora" (mesma justificativa de `_MS_PER_MINUTE` em
# `src.data.resample`), por isso não entra em `constants.yaml`.
_MS_PER_HOUR = 3_600_000


def _not_computable(n: int) -> TriggerArray:
    return np.full(n, TriggerState.NOT_COMPUTABLE, dtype=object)


def _threshold_gt(values: FloatArray, threshold: float) -> TriggerArray:
    """`TRIGGERED` onde `values > threshold`; `NOT_TRIGGERED` onde `<=`;
    `NOT_COMPUTABLE` onde `NaN` — o warmup natural da série de entrada
    (ex.: antes de `min_warmup_bars`, ou um gap pontual de dado real) nunca
    deve contar como "não disparou": é informação ausente, não um resultado
    negativo real."""
    n = values.shape[0]
    out = np.empty(n, dtype=object)
    nan_mask = np.isnan(values)
    out[nan_mask] = TriggerState.NOT_COMPUTABLE
    triggered_mask = ~nan_mask & (values > threshold)
    out[triggered_mask] = TriggerState.TRIGGERED
    out[~nan_mask & ~triggered_mask] = TriggerState.NOT_TRIGGERED
    return out


def _threshold_abs_gt(values: FloatArray, threshold: float) -> TriggerArray:
    return _threshold_gt(np.abs(values), threshold)


# ============================================================================
# S1 — vol_pctile_expanding > 0.98 (C07, já existe — Sprint 4)
# ============================================================================


def s01_vol_extreme(vol_pctile_expanding: FloatArray) -> TriggerArray:
    """S1 — §4.4. Fonte: `C07_vol_pctile_expanding`
    (`src.features.groups.group_c.c07_vol_pctile_expanding`), computada
    pelo Feature Engine no Sprint 4 — reusada aqui via a coluna já pronta,
    não recalculada."""
    threshold = float(load_constant("stress_vol_pctile_threshold"))
    return _threshold_gt(vol_pctile_expanding, threshold)


# ============================================================================
# S2 — spread_pctile_expanding > 0.95 (F02f)
# ============================================================================


def s02_spread_extreme(spread_pctile_expanding: FloatArray | None, n: int) -> TriggerArray:
    """S2 — §4.4. Fonte declarada: F02f `spread_pctile_expanding`.

    **Decisão investigada e documentada (não uma aproximação silenciosa):**
    F02f saiu de T1 na v3.3 por quebra de definição RPI em 2025-11-20
    (§2.7.1) e HOJE não existe como feature em `src/features/` — não há
    `group_f.py`, não há entrada em `registry.yaml`. O único dado que
    poderia alimentar F02f é `data/raw/book_ticker/BTCUSDT/*.parquet`
    (best_bid/best_ask tick-a-tick, medido: 4.494.018 linhas só no dia
    2023-05-16), cobrindo uma janela isolada de 320 dias
    (2023-05-16 -> 2024-03-30, ~52,6GB comprimidos) — confirmado por
    listagem real do diretório neste Sprint, não presumido do PRD.

    Construir a série `spread_pctile_expanding` de verdade a partir disso
    significaria reimplementar F02f inteira (resample tick->15m + posto
    percentil expansivo) dentro do Regime Engine, por uma janela de 10,5
    meses desconectada do resto da história (~6,6 anos) — exatamente o tipo
    de sinal parcial/aproximado que a task pediu para não forçar. Decisão:
    esta função fica **dependente de injeção** (não lê `data/raw/` sozinha).
    Se/quando F02f for implementada em `src/features/groups/group_f.py`
    (Grupo F retorna a T1 com ≥6 meses de coleta forward de rpiDepth,
    §2.7.1), quem chama passa a série real aqui e o gatilho passa a
    funcionar sem mudar esta função. Até lá, `spread_pctile_expanding=None`
    (o caso real do pipeline de Sprint 5) produz `NOT_COMPUTABLE` em toda
    barra — estado honesto, não `False`."""
    if spread_pctile_expanding is None:
        return _not_computable(n)
    threshold = float(load_constant("stress_spread_pctile_threshold"))
    return _threshold_gt(spread_pctile_expanding, threshold)


# ============================================================================
# S3 — |funding_z| > 3.0 (E02f, já existe — Sprint 4)
# ============================================================================


def s03_funding_extreme(funding_z_expanding: FloatArray) -> TriggerArray:
    """S3 — §4.4. Fonte: `E02f_funding_z_expanding`
    (`src.features.groups.group_e.e02f_funding_z_expanding`)."""
    threshold = float(load_constant("stress_funding_z_threshold"))
    return _threshold_abs_gt(funding_z_expanding, threshold)


# ============================================================================
# S4 — |basis_perp_index_bps| > 100 (E19f, precisa D10+D12)
# ============================================================================


def s04_basis_break(n: int) -> TriggerArray:
    """S4 — §4.4. Fonte declarada: E19f `basis_perp_index_bps =
    (mark - index) / index * 10000`, precisa D10 (mark price, existe) **e**
    D12 (`index_price_1m`).

    Confirmado neste Sprint (não presumido): D12 nunca foi baixado.
    `config/constants.yaml::index_price_deviation_max_pct` já documenta
    isso ("check 18 fica PENDING até lá") e `src/data/validate.py` marca o
    check 18 (mark/index deviation) como PENDING pela mesma razão. Sem D12,
    E19f não pode ser calculada — `NOT_COMPUTABLE` em toda barra, não uma
    aproximação via outra série de preço."""
    return _not_computable(n)


# ============================================================================
# S5 — bar_staleness > 90s ou book_staleness > 5s (F14f)
# ============================================================================


def s05_stale_data(n: int) -> TriggerArray:
    """S5 — §4.4. `bar_staleness`/`book_staleness` medem o atraso entre "o
    relógio de parede agora" e "o timestamp do último dado recebido" — por
    definição, isso só existe em operação AO VIVO (o processo rodando
    continuamente, comparando contra `time.now()`). Um dataset histórico
    não tem "agora": toda barra já está no disco, então staleness sempre
    seria 0 por construção, o que não é o mesmo que "não é aplicável" —
    é literalmente indefinido fora de live. `NOT_COMPUTABLE` para
    backtest/pipeline histórico; plugue real em Sprint 13+ (live trading,
    watchdogs de WS já existem em `src.exchange.ws`/`rate_limit`, mas o
    gatilho S5 do Regime Engine em si ainda não tem consumidor ao vivo)."""
    return _not_computable(n)


# ============================================================================
# S6 — gap de barra (ausência de barra na grade). Data Quality Engine
# (Sprint 3) já detecta isso — REUSA `data.checks.check_grid_completeness`,
# não duplica a lógica de "o que conta como ausente".
# ============================================================================


def s06_bar_gap(open_time_ms: TimeArray, step_ms: int) -> TriggerArray:
    """S6 — §4.4. Único gatilho verdadeiramente computável em qualquer
    barra da série (nunca `NOT_COMPUTABLE` — a informação "existe uma barra
    imediatamente antes desta, no grid esperado?" está sempre disponível a
    partir do próprio `open_time_ms` que a barra carrega).

    Semântica: `TRIGGERED` na primeira barra PRESENTE depois de um gap
    (a barra de "retomada"), não nas barras ausentes em si — barras
    ausentes não têm linha no output para carregar um sinal (§4.6, `t0` é
    PK; uma barra que não existe não gera PK). Reusa
    `data.checks.check_grid_completeness` (Sprint 3, RF-003 check 9) para
    obter o conjunto de timestamps esperados-mas-ausentes no grid
    `step_ms`, em vez de reimplementar essa lógica aqui."""
    n = open_time_ms.shape[0]
    out = np.full(n, TriggerState.NOT_TRIGGERED, dtype=object)
    if n < 2:
        return out

    ts = open_time_ms.astype(np.int64)
    df = pl.DataFrame({"_ts": ts})
    result = data_checks.check_grid_completeness(df, "_ts", step_ms)
    if result.missing_count == 0:
        return out

    missing = set(result.missing_timestamps_ms)
    ts_list = ts.tolist()
    for i in range(1, n):
        expected_prev = ts_list[i] - step_ms
        if expected_prev in missing:
            out[i] = TriggerState.TRIGGERED
    return out


# ============================================================================
# S7 — depth_at_20bps < 4 x unit_notional (F09f, precisa D02 book_depth)
# ============================================================================


def s07_shallow_liquidity(n: int) -> TriggerArray:
    """S7 — §4.4. Fonte declarada: F09f `depth_at_20bps`, de D02
    (bookDepth).

    Investigado neste Sprint (não presumido): `data/capacity/book_depth/
    BTCUSDT/` EXISTE e cobre a história quase inteira do projeto
    (2023-01-01 -> 2026-08-07, 1.312 arquivos diários, ~30s de cadência
    intradiária) — diferente de S2/S4/S8/S9/S10, aqui o dado realmente
    está lá. Mas o schema real (lido de um arquivo, não presumido) é:

        ts_ms, nocional_m500bp, nocional_m400bp, nocional_m300bp,
        nocional_m200bp, nocional_m100bp, nocional_p100bp, nocional_p200bp,
        nocional_p300bp, nocional_p400bp, nocional_p500bp

    Buckets de ±100/200/300/400/500 bp — **não existe bucket de 20bp**, que
    é exatamente o que S7 pede (`depth_at_20bps`). O bucket mais fino
    disponível é 100bp, 5x mais largo que o threshold do gatilho.

    Por que isto NÃO é implementado como aproximação via `nocional_m100bp`/
    `nocional_p100bp`: a implicação só funciona em uma direção.
    `depth_at_100bp >= depth_at_20bps` sempre (contenção: a banda de 100bp
    contém a de 20bp), então "`depth_at_100bp` já é baixo" prova
    `depth_at_20bps` também baixo — mas "`depth_at_100bp` é alto" NÃO prova
    nada sobre os 20bp mais próximos do mid (um book pode ter um "buraco"
    fino perto do mid e profundidade real só mais longe). Os valores
    medidos de `nocional_m100bp`/`nocional_p100bp` (dezenas de milhões de
    USDT, ex. ~US$72M em 2023-01-01) são ordens de grandeza acima do
    threshold real (`4 x unit_notional` ~ 4 x US$65 = US$260) — usar o
    proxy de 100bp como está SEMPRE resultaria em "não disparou", o que é
    indistinguível de um `False` silencioso mascarando exatamente o
    cenário que o gatilho existe para pegar (liquidez fina PERTO do mid
    com profundidade normal mais longe). `NOT_COMPUTABLE` como especificado
    — não uma aproximação que nunca dispara."""
    return _not_computable(n)


# ============================================================================
# S8 — is_event_window (K06, calendário econômico)
# ============================================================================


def s08_event_window(n: int) -> TriggerArray:
    """S8 — §4.4. Fonte declarada: K06, calendário de FOMC/CPI/NFP (±2h).
    Confirmado neste Sprint: nenhum arquivo/config de calendário econômico
    existe no repo (`grep` por FOMC/CPI/NFP/calendar em `src/`/`config/`
    não retorna nada). `NOT_COMPUTABLE` — sem fonte, não um "nunca é janela
    de evento"."""
    return _not_computable(n)


# ============================================================================
# S9 — liq_notional_z > 4.0 (E25f, precisa stream forceOrder / F03)
# ============================================================================


def s09_liquidation_cascade(n: int) -> TriggerArray:
    """S9 — §4.4. Fonte declarada: E25f `liq_notional_z`, de F03
    (`forceOrder`). `forceOrder` é um stream de WebSocket ao vivo
    (`@forceOrder`) — a Binance não publica dump histórico público de
    liquidações agregadas para reconstrução retroativa. Confirmado neste
    Sprint: nenhum dado de liquidação/`forceOrder` existe em `data/`.
    `NOT_COMPUTABLE` para qualquer backtest histórico; plugue real é
    coleta forward via WS (fora de escopo do Sprint 5)."""
    return _not_computable(n)


# ============================================================================
# S10 — filters_hash mudou nas últimas 24h (F01, exchangeInfo)
# ============================================================================


_FILTERS_HASH_FIELDS = (
    "tick_size", "step_size", "min_qty", "max_qty",
    "market_step_size", "min_notional",
)  # fmt: skip


def compute_filters_hash(f: exchange_filters.Filters) -> str:
    """Hash determinístico só dos campos de LOT_SIZE/PRICE_FILTER/
    MIN_NOTIONAL relevantes a quantização (§0.2 R1) — não do payload bruto
    de `exchangeInfo` inteiro, que muda por campos irrelevantes (ex.
    `serverTime`) sem que nenhum filtro real tenha mudado. `sha256` sobre
    os campos concatenados em ordem fixa (`_FILTERS_HASH_FIELDS`) —
    determinístico e barato."""
    payload = "|".join(str(getattr(f, field)) for field in _FILTERS_HASH_FIELDS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def discover_filters_hash_snapshots(
    symbol: str = "BTCUSDT",
) -> tuple[tuple[int, str], ...]:
    """Enumera os snapshots CANÔNICOS de `exchangeInfo` em
    `data/raw/snapshots/exchange_info/*.json` (não os `reconstructed/` —
    S10 é sobre detectar mudança real observada, não uma reconstrução por
    anúncio) e devolve `(timestamp_ms_do_snapshot, filters_hash)` ordenado
    por data. Reusa `src.exchange.filters.parse_exchange_info_snapshot`
    (Sprint 2) para o parsing — não duplica a extração de LOT_SIZE/
    PRICE_FILTER/MIN_NOTIONAL.

    Medido neste Sprint: só existe 1 arquivo (`2026-08-08.json`) — com um
    único ponto não há como detectar "mudou", então esta função devolve
    uma tupla de tamanho 1 hoje, e `s10_filters_hash_changed` (que exige
    >= 2 pontos) resolve para `NOT_COMPUTABLE` em todo o pipeline real
    até um 2º snapshot existir."""
    if not EXCHANGE_INFO_SNAPSHOTS_DIR.is_dir():
        return ()

    out: list[tuple[int, str]] = []
    for path in sorted(EXCHANGE_INFO_SNAPSHOTS_DIR.glob("*.json")):
        try:
            snap_date = date.fromisoformat(path.stem)
        except ValueError:
            continue  # não é yyyy-mm-dd.json (ex.: arquivo fora do padrão)
        raw = orjson.loads(path.read_bytes())
        parsed = exchange_filters.parse_exchange_info_snapshot(
            raw, symbol=symbol, snapshot_date=snap_date
        )
        h = compute_filters_hash(parsed)
        snap_dt = datetime(snap_date.year, snap_date.month, snap_date.day, tzinfo=UTC)
        ts_ms = int(snap_dt.timestamp() * 1000)
        out.append((ts_ms, h))
    return tuple(sorted(out, key=lambda pair: pair[0]))


def s10_filters_hash_changed(
    open_time_ms: TimeArray,
    snapshots: tuple[tuple[int, str], ...] | None,
) -> TriggerArray:
    """S10 — §4.4. Precisa >= 2 snapshots de `exchangeInfo` para detectar
    "mudou" (um hash sozinho não tem com o que ser comparado). Medido neste
    Sprint: `discover_filters_hash_snapshots()` devolve exatamente 1 ponto
    (2026-08-08) — `NOT_COMPUTABLE` em toda a série até um 2º snapshot
    existir (coleta forward diária já iniciou, ver CLAUDE.md "Pendências
    P0"). Com >= 2 snapshots, `TRIGGERED` nas barras cujo `open_time` cai
    dentro de `stress_filters_hash_window_hours` (24h, `constants.yaml`)
    após um evento de mudança de hash entre snapshots consecutivos."""
    n = open_time_ms.shape[0]
    if snapshots is None or len(snapshots) < 2:
        return _not_computable(n)

    window_ms = int(load_constant("stress_filters_hash_window_hours")) * _MS_PER_HOUR
    sorted_snaps = sorted(snapshots, key=lambda pair: pair[0])
    change_ts = [
        sorted_snaps[i][0]
        for i in range(1, len(sorted_snaps))
        if sorted_snaps[i][1] != sorted_snaps[i - 1][1]
    ]
    out = np.full(n, TriggerState.NOT_TRIGGERED, dtype=object)
    if not change_ts:
        return out

    change_arr = np.array(change_ts, dtype=np.int64)
    ts = open_time_ms.astype(np.int64)
    for i in range(n):
        t = int(ts[i])
        lo = t - window_ms
        idx_hi = int(np.searchsorted(change_arr, t, side="right"))
        idx_lo = int(np.searchsorted(change_arr, lo, side="right"))
        if idx_hi > idx_lo:
            out[i] = TriggerState.TRIGGERED
    return out


# ============================================================================
# Composição — StressInputs/StressResult, uma entrada por gatilho
# ============================================================================


@dataclass(frozen=True, slots=True)
class StressInputs:
    """Entradas dos 10 gatilhos. Os campos `| None` correspondem aos
    gatilhos dependentes de dado que não existe hoje no pipeline padrão
    (S2, S10) — passar `None` (o default de `build.py`) produz
    `NOT_COMPUTABLE`, documentado em cada função `sXX_*` acima."""

    n: int
    open_time_ms: TimeArray
    vol_pctile_expanding: FloatArray
    funding_z_expanding: FloatArray
    step_ms: int = 0  # 0 -> resolvido para o passo de 15m em compute_stress_triggers
    spread_pctile_expanding: FloatArray | None = None
    filters_hash_snapshots: tuple[tuple[int, str], ...] | None = None


@dataclass(frozen=True, slots=True)
class StressResult:
    triggers: dict[str, TriggerArray]  # gatilho_id -> array de TriggerState por barra
    triggered_mask: NDArray[np.bool_]  # True se QUALQUER gatilho TRIGGERED nessa barra
    stress_triggers_list: tuple[tuple[str, ...], ...]  # por barra, ids TRIGGERED (§4.6)


def compute_stress_triggers(inputs: StressInputs) -> StressResult:
    """Roda os 10 gatilhos e agrega. `step_ms` default (0) resolve para o
    passo de 15m via `src.data.resample.step_ms("15m")` — decision_tf do
    projeto (§0.1); um chamador de outro TF passaria `step_ms` explícito
    em `StressInputs`."""
    step_ms = inputs.step_ms or data_resample.step_ms("15m")

    triggers: dict[str, TriggerArray] = {
        "S1": s01_vol_extreme(inputs.vol_pctile_expanding),
        "S2": s02_spread_extreme(inputs.spread_pctile_expanding, inputs.n),
        "S3": s03_funding_extreme(inputs.funding_z_expanding),
        "S4": s04_basis_break(inputs.n),
        "S5": s05_stale_data(inputs.n),
        "S6": s06_bar_gap(inputs.open_time_ms, step_ms),
        "S7": s07_shallow_liquidity(inputs.n),
        "S8": s08_event_window(inputs.n),
        "S9": s09_liquidation_cascade(inputs.n),
        "S10": s10_filters_hash_changed(inputs.open_time_ms, inputs.filters_hash_snapshots),
    }

    n = inputs.n
    triggered_mask = np.zeros(n, dtype=bool)
    stress_triggers_lists: list[list[str]] = [[] for _ in range(n)]
    for sid in TRIGGER_IDS:
        arr = triggers[sid]
        is_trig = arr == TriggerState.TRIGGERED
        triggered_mask |= is_trig
        for i in np.flatnonzero(is_trig):
            stress_triggers_lists[i].append(sid)

    n_computable = {
        sid: int(np.sum(triggers[sid] != TriggerState.NOT_COMPUTABLE)) for sid in TRIGGER_IDS
    }
    n_triggered = {sid: int(np.sum(triggers[sid] == TriggerState.TRIGGERED)) for sid in TRIGGER_IDS}
    logger.info(
        "regime.stress.compute_stress_triggers",
        n_bars=n,
        n_computable_bars_by_trigger=n_computable,
        n_triggered_bars_by_trigger=n_triggered,
        n_bars_any_triggered=int(triggered_mask.sum()),
    )

    return StressResult(
        triggers=triggers,
        triggered_mask=triggered_mask,
        stress_triggers_list=tuple(tuple(lst) for lst in stress_triggers_lists),
    )
