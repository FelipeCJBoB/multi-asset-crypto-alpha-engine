"""Classificador determinístico por quantis expansivos — §4 do PRD.

Núcleo puro (sem IO) do Regime Engine: dados os dois eixos primários já
calculados pelo Feature Engine (Sprint 4) — `B07_efficiency_ratio_48`
(estrutura) e `C07_vol_pctile_expanding` (volatilidade) — e o resultado dos
gatilhos de stress (`src.regime.stress`), produz os 5 regimes canônicos
R0-R5 com histerese + confirmação (§4.5), mais o eixo econômico de saída
(§4.3.1).

**Decisão de design não trivial, resolvida sozinho, documentada aqui (não
escondida):** este módulo consome as features T1/T2 do Feature Engine SEM
a máscara uniforme de `min_warmup_bars` (`build_t1_features(...,
apply_warmup_mask=False)`), mesmo que o Regime Engine tenha seu próprio
gate de warmup (`R0`, index-based). Motivo: `apply_min_warmup_mask` do
Feature Engine zera (`null`) toda feature antes da barra 2000 para
consumo do Alpha — mas `B07_efficiency_ratio_48` tem warmup NATURAL de
~48 barras e `C07_vol_pctile_expanding`/`E27f_cost_atr_ratio` de dezenas
de barras, todos MUITO menores que 2000. Se este módulo recalculasse
`er_quantile` (posto percentil expansivo de `er_48`, ver abaixo) a partir
da série JÁ mascarada, o acumulador expansivo perderia ~1950 barras de
histórico real (bar 48 -> bar 2000) e começaria do zero exatamente na
barra em que R0 termina — um cold start artificial que o próprio `C07`
(computado ANTES da máscara, dentro de `compute_t1_features`) não sofre.
Usar a série não mascarada e aplicar o próprio corte `R0` por ÍNDICE (não
por nulidade) elimina essa assimetria e mantém `er_quantile` equivalente
em espírito a como `vol_pctile` já é calculado internamente.

Pelo mesmo racional, os três estados de histerese (tendência, volatilidade,
stress) evoluem de forma contínua desde a barra 0 — não ficam "congelados"
até `min_warmup_bars` — de modo que ao fim do warmup eles já carregam
histórico real acumulado, não um estado inicial arbitrário. Isso só afeta
a barra em que R0 termina e as poucas barras seguintes; o output para
`t < min_warmup_bars` é sempre `"R0"` de qualquer forma.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from src.features import support
from src.features.support import FloatArray

from . import stress as stress_mod
from ._constants import load_constant

logger = structlog.get_logger(__name__)

ENGINE_VERSION = "regime_v1"

REGIME_LABELS: tuple[str, ...] = ("R0", "R1", "R2", "R3", "R4", "R5")
TRADEABLE_REGIMES: frozenset[str] = frozenset({"R1", "R2", "R3", "R4"})

_ECON_REGIME_LABELS: tuple[str, ...] = (
    "ECONOMICS_FAVORABLE",
    "ECONOMICS_NEUTRAL",
    "ECONOMICS_HOSTILE",
    "ECONOMICS_UNKNOWN",
)

# Tercil — definição matemática (1/3, 2/3), não um parâmetro de domínio
# sujeito a proveniência (§4.3.1: "ECONOMICS_FAVORABLE: cost_atr_ratio <
# p33 expansivo"). Divisão inteira -> float evita literal float fora do
# whitelist do lint (`tools/lint/banned_patterns.py`) sem precisar do
# marcador usado em outros pontos do repo para exceção de "magic number".
_ECON_TERCILE_LOW = 1 / 3
_ECON_TERCILE_HIGH = 2 / 3

StrArray = NDArray[np.object_]


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    """Todas as constantes de `constants.yaml` que o classificador precisa,
    lidas uma única vez (mesmo padrão de `FeatureWindows` em
    `src.features.build`)."""

    er_cutoff_enter: float
    er_cutoff_exit: float
    vol_cutoff_enter: float
    vol_cutoff_exit: float
    min_warmup_bars: int
    confirmation_bars: int
    stress_exit_confirmation_bars: int

    @classmethod
    def from_constants(cls) -> RegimeThresholds:
        return cls(
            er_cutoff_enter=float(load_constant("regime_er_cutoff")),
            er_cutoff_exit=float(load_constant("regime_er_cutoff_exit")),
            vol_cutoff_enter=float(load_constant("regime_vol_cutoff")),
            vol_cutoff_exit=float(load_constant("regime_vol_cutoff_exit")),
            min_warmup_bars=int(load_constant("min_warmup_bars")),
            confirmation_bars=int(load_constant("regime_confirmation_bars")),
            stress_exit_confirmation_bars=int(
                load_constant("regime_stress_exit_confirmation_bars")
            ),
        )


def _run_state_machine(
    er_quantile: FloatArray,
    vol_pctile: FloatArray,
    stress_triggered: NDArray[np.bool_],
    thresholds: RegimeThresholds,
) -> tuple[StrArray, StrArray]:
    """Laço sequencial explícito — mesma justificativa de
    `wilder_smooth`/`expanding_zscore_strict` em `src/features/support.py`:
    o estado em `t` (histerese + contador de confirmação) depende do
    estado em `t-1`, então um passe O(n) com estado explícito é a forma
    mais simples e auditável de implementar §4.5 sem look-ahead.

    Devolve `(regime, regime_raw)`. `bars_in_regime` é calculado depois,
    em `_bars_in_regime`, sobre o `regime` já pronto — não precisa do
    estado interno deste laço.

    Precedência dentro do laço (§4.3: "R5 tem precedência sobre todos os
    outros" | resolução deste Sprint: R0/warmup tem precedência sobre R5 —
    ver docstring do módulo/relatório do Sprint: classificar como R5
    durante o warmup usaria quantis que a própria R0 declara "ainda não
    confiáveis"): `is_warmup -> R0`, senão `stress_state -> R5`, senão
    combinação de `trend_state`/`vol_state` -> R1..R4.

    Os TRÊS estados de histerese (`trend_state`, `vol_state`,
    `stress_state`) são atualizados em TODA barra (inclusive durante o
    warmup) para não sofrerem cold start artificial na barra em que R0
    termina — só a LABEL final respeita `is_warmup`."""
    n = er_quantile.shape[0]
    regime = np.empty(n, dtype=object)
    regime_raw = np.empty(n, dtype=object)

    trend_state = False
    vol_state = False
    stress_state = False
    trend_pending = 0
    vol_pending = 0
    stress_exit_pending = 0

    for t in range(n):
        is_warmup = t < thresholds.min_warmup_bars
        er_q = er_quantile[t]
        vol_p = vol_pctile[t]
        is_stress_instant = bool(stress_triggered[t])
        has_signal = not (np.isnan(er_q) or np.isnan(vol_p))

        # --- regime_raw: classificação instantânea, sem estado ---
        if is_warmup:
            regime_raw[t] = "R0"
        elif is_stress_instant:
            regime_raw[t] = "R5"
        elif not has_signal:
            # dado insuficiente pontual pós-warmup (não esperado na prática
            # — ver relatório do Sprint 5 para a medição real — mas
            # tratado explicitamente em vez de deixar cair num branch
            # errado por NaN): mantém o último raw válido em vez de
            # inventar uma 6a categoria fora do schema §4.6.
            regime_raw[t] = regime_raw[t - 1] if t > 0 else "R0"
        else:
            is_trend_raw = er_q >= thresholds.er_cutoff_enter
            is_high_vol_raw = vol_p >= thresholds.vol_cutoff_enter
            if is_trend_raw and is_high_vol_raw:
                regime_raw[t] = "R4"
            elif is_trend_raw:
                regime_raw[t] = "R3"
            elif is_high_vol_raw:
                regime_raw[t] = "R2"
            else:
                regime_raw[t] = "R1"

        # --- eixo tendência (histerese Schmitt: entrada q60, saída q55) ---
        if has_signal:
            trend_cutoff = thresholds.er_cutoff_exit if trend_state else thresholds.er_cutoff_enter
            candidate_trend = er_q >= trend_cutoff
            if candidate_trend != trend_state:
                trend_pending += 1
                if trend_pending >= thresholds.confirmation_bars:
                    trend_state = candidate_trend
                    trend_pending = 0
            else:
                trend_pending = 0

            # --- eixo volatilidade (histerese Schmitt: entrada 0.70, saída 0.65) ---
            vol_cutoff = thresholds.vol_cutoff_exit if vol_state else thresholds.vol_cutoff_enter
            candidate_vol = vol_p >= vol_cutoff
            if candidate_vol != vol_state:
                vol_pending += 1
                if vol_pending >= thresholds.confirmation_bars:
                    vol_state = candidate_vol
                    vol_pending = 0
            else:
                vol_pending = 0
        # sem sinal (NaN pontual): estado dos dois eixos fica congelado
        # nesta barra — nem propõe troca, nem reseta o contador pendente.

        # --- eixo stress: entrada IMEDIATA, saída com N barras de confirmação (§4.5 assimetria) ---
        if is_stress_instant:
            stress_state = True
            stress_exit_pending = 0
        elif stress_state:
            stress_exit_pending += 1
            if stress_exit_pending >= thresholds.stress_exit_confirmation_bars:
                stress_state = False
                stress_exit_pending = 0
        else:
            stress_exit_pending = 0

        # --- regime confirmado ---
        if is_warmup:
            regime[t] = "R0"
        elif stress_state:
            regime[t] = "R5"
        elif trend_state and vol_state:
            regime[t] = "R4"
        elif trend_state:
            regime[t] = "R3"
        elif vol_state:
            regime[t] = "R2"
        else:
            regime[t] = "R1"

    return regime, regime_raw


def _bars_in_regime(regime: StrArray) -> NDArray[np.int64]:
    """Persistência do regime CONFIRMADO — run-length do array `regime`,
    com um piso de 2 para qualquer regime != R5 (§4.8 invariante:
    `bars_in_regime >= 2 | regime == "R5"`).

    O piso de 2 não é um remendo cosmético: uma transição confirmada para
    R1..R4 SÓ acontece depois de `confirmation_bars` (2) barras
    consecutivas propondo a troca (§4.5) — a barra em que a troca aparece
    no output já carrega, por construção, 2 barras de evidência causal, e
    o piso apenas TORNA ISSO VISÍVEL na coluna (o run-length ingênuo do
    array de saída mostraria 1 nessa barra, porque é a primeira vez que o
    RÓTULO aparece — mas não é a primeira barra de EVIDÊNCIA). A mesma
    convenção resolve o caso de contorno da barra 0 da série inteira (R0,
    run-length verdadeiro = 1 por ser a primeira observação que existe —
    documentado, sem efeito prático: R0 em t=0 nunca é `tradeable` e é
    sempre mascarado a jusante). R5 fica de fora do piso de propósito —
    entra sem confirmação (§4.5), então `bars_in_regime == 1` na barra de
    entrada de R5 é um resultado real, não um artefato a esconder."""
    n = regime.shape[0]
    out = np.empty(n, dtype=np.int64)
    run = 0
    prev: object = None
    for t in range(n):
        run = run + 1 if regime[t] == prev else 1
        out[t] = run if regime[t] == "R5" else max(run, 2)
        prev = regime[t]
    return out


def _economics_regime(econ_quantile: FloatArray) -> StrArray:
    """§4.3.1 — tercil expansivo de `cost_atr_ratio` (via posto percentil
    expansivo estrito, mesma primitiva de `er_quantile`/`vol_pctile`).
    Sem estado (vetorizável): cada barra é independente dado seu próprio
    `econ_quantile`, diferente do eixo estrutura/volatilidade (que tem
    histerese)."""
    n = econ_quantile.shape[0]
    out: StrArray = np.full(n, "ECONOMICS_HOSTILE", dtype=object)
    nan_mask = np.isnan(econ_quantile)
    favorable_mask = ~nan_mask & (econ_quantile < _ECON_TERCILE_LOW)
    neutral_mask = ~nan_mask & ~favorable_mask & (econ_quantile < _ECON_TERCILE_HIGH)
    out[favorable_mask] = "ECONOMICS_FAVORABLE"
    out[neutral_mask] = "ECONOMICS_NEUTRAL"
    out[nan_mask] = "ECONOMICS_UNKNOWN"
    return out


def classify_regimes(
    open_time_ms: stress_mod.TimeArray,
    er_48: FloatArray,
    vol_pctile: FloatArray,
    cost_atr_ratio: FloatArray,
    stress_result: stress_mod.StressResult,
    *,
    thresholds: RegimeThresholds | None = None,
    er_quantile: FloatArray | None = None,
    econ_quantile: FloatArray | None = None,
) -> pl.DataFrame:
    """Núcleo puro do Regime Engine (§4). Todos os arrays de entrada devem
    vir NÃO mascarados por `min_warmup_bars` (ver docstring do módulo) e
    alinhados posicionalmente 1:1 com `open_time_ms` — mesmo contrato de
    alinhamento posicional já usado em `src.features._sources`.

    Colunas de saída: exatamente as do §4.6 (`t0, regime, regime_raw,
    er_48, er_quantile, vol_pctile, bars_in_regime, stress_triggers,
    tradeable, engine_version`) MAIS duas colunas adicionadas por
    instrução explícita da task (§4.3.1, "terceiro eixo... dimensão
    adicional de saída", não listado na tabela literal do §4.6):
    `cost_atr_ratio` (valor bruto) e `econ_regime`
    (`ECONOMICS_FAVORABLE/NEUTRAL/HOSTILE/UNKNOWN`). Extensão documentada,
    não silenciosa.

    `er_quantile`/`econ_quantile` (I-d, PRD_V4_1.md T0.2): opcionais —
    `None` (default, comportamento inalterado) recomputa internamente via
    `expanding_percentile_rank_strict`, igual a antes. Passados prontos,
    usa direto sem recomputar — o mesmo ponto de injeção que `vol_pctile`
    já tinha (chega pronto de `C07_vol_pctile_expanding`) e que `er_48`/
    `cost_atr_ratio` não tinham: sem isso, um chamador que já calculou o
    quantil (ou quer trocar o método de ranking) não tinha como injetar,
    só recalcular por baixo — assimetria sem razão declarada."""
    if thresholds is None:
        thresholds = RegimeThresholds.from_constants()

    n = open_time_ms.shape[0]
    if not (er_48.shape[0] == vol_pctile.shape[0] == cost_atr_ratio.shape[0] == n):
        raise ValueError(
            "classify_regimes: open_time_ms/er_48/vol_pctile/cost_atr_ratio precisam do "
            f"mesmo comprimento (n={n}, er_48={er_48.shape[0]}, vol_pctile={vol_pctile.shape[0]}, "
            f"cost_atr_ratio={cost_atr_ratio.shape[0]})"
        )
    if stress_result.triggered_mask.shape[0] != n:
        raise ValueError("classify_regimes: stress_result não está alinhado com open_time_ms")

    if er_quantile is None:
        er_quantile = support.expanding_percentile_rank_strict(er_48)
    if econ_quantile is None:
        econ_quantile = support.expanding_percentile_rank_strict(cost_atr_ratio)

    regime, regime_raw = _run_state_machine(
        er_quantile, vol_pctile, stress_result.triggered_mask, thresholds
    )
    bars_in_regime = _bars_in_regime(regime)
    econ_regime = _economics_regime(econ_quantile)

    tradeable = np.isin(regime, list(TRADEABLE_REGIMES))

    df = pl.DataFrame(
        {
            "_open_time_ms": open_time_ms,
            "regime": regime.astype(str),
            "regime_raw": regime_raw.astype(str),
            "er_48": er_48,
            "er_quantile": er_quantile,
            "vol_pctile": vol_pctile,
            "bars_in_regime": bars_in_regime,
            "stress_triggers": [list(ids) for ids in stress_result.stress_triggers_list],
            "tradeable": tradeable,
            "cost_atr_ratio": cost_atr_ratio,
            "econ_regime": econ_regime.astype(str),
        }
    )

    df = df.with_columns(
        pl.from_epoch(pl.col("_open_time_ms"), time_unit="ms")
        .dt.replace_time_zone("UTC")
        .dt.cast_time_unit("ns")
        .alias("t0"),
        pl.col("regime").cast(pl.Enum(list(REGIME_LABELS))),
        pl.col("regime_raw").cast(pl.Enum(list(REGIME_LABELS))),
        # §4.6 declara `bars_in_regime: int16`. Desvio deliberado, reportado
        # (não silencioso): int16 satura em 32.767 barras (~341 dias a 15m)
        # — um único regime estável pode, na prática, durar mais que isso
        # sobre os ~6,6 anos de histórico do projeto (ver relatório do
        # Sprint 5 para a contagem real medida). Um overflow silencioso de
        # int16 quebraria a própria invariante `bars_in_regime >= 2` sem
        # aviso (wrap-around pode até virar negativo) — Int32 (max ~2,1
        # bilhões) elimina esse risco a custo de 2 bytes/linha.
        pl.col("bars_in_regime").cast(pl.Int32),
        pl.col("econ_regime").cast(pl.Enum(list(_ECON_REGIME_LABELS))),
        pl.lit(ENGINE_VERSION).alias("engine_version"),
    ).drop("_open_time_ms")

    df = df.select(
        [
            "t0",
            "regime",
            "regime_raw",
            "er_48",
            "er_quantile",
            "vol_pctile",
            "bars_in_regime",
            "stress_triggers",
            "tradeable",
            "engine_version",
            "cost_atr_ratio",
            "econ_regime",
        ]
    )

    logger.info(
        "regime.classifier.classify_regimes",
        n_bars=df.height,
        regime_counts=df["regime"].value_counts().sort("regime").to_dicts(),
    )
    return df


# ============================================================================
# RegimeClassifier (PRD_V4_1.md T0.2) -- Protocol + implementação inicial
# ============================================================================


class RegimeClassifier(Protocol):
    def classify(self, features: pl.DataFrame) -> pl.DataFrame:
        """Colunas: t0, regime, regime_raw, tradeable, classifier_id.
        Causal e online: barra t usa apenas índices < t."""
        ...

    @property
    def n_states(self) -> int: ...

    @property
    def classifier_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class QuantileRegimeClassifier:
    """Wrapper de `classify_regimes` atrás do `RegimeClassifier` Protocol —
    bit-idêntico ao que `src.regime.build.build_regimes` já roda hoje
    (mesmas 4 colunas extraídas de `features`, mesmo
    `stress.compute_stress_triggers`; `build_regimes` foi refatorado pra
    delegar aqui em vez de duplicar a extração).

    `symbol` é bound no construtor: a única IO que sobrevive dentro de
    `classify()` — `stress.discover_filters_hash_snapshots(symbol)`, leve,
    um glob + parse de JSON, não a carga pesada de features — precisa
    saber de qual símbolo. A IO pesada (`build_t1_features`) fica de fora
    do Protocol, no chamador, que monta `features` antes de chamar
    `classify()`."""

    symbol: str
    thresholds: RegimeThresholds | None = None

    def classify(self, features: pl.DataFrame) -> pl.DataFrame:
        open_time_ms = features["open_time"].cast(pl.Int64).to_numpy()
        er_48 = features["B07_efficiency_ratio_48"].cast(pl.Float64).to_numpy()
        vol_pctile = features["C07_vol_pctile_expanding"].cast(pl.Float64).to_numpy()
        funding_z = features["E02f_funding_z_expanding"].cast(pl.Float64).to_numpy()
        cost_atr_ratio = features["E27f_cost_atr_ratio"].cast(pl.Float64).to_numpy()

        filters_snapshots = stress_mod.discover_filters_hash_snapshots(self.symbol)
        stress_inputs = stress_mod.StressInputs(
            n=features.height,
            open_time_ms=open_time_ms,
            vol_pctile_expanding=vol_pctile,
            funding_z_expanding=funding_z,
            spread_pctile_expanding=None,
            filters_hash_snapshots=filters_snapshots,
        )
        stress_result = stress_mod.compute_stress_triggers(stress_inputs)

        df = classify_regimes(
            open_time_ms,
            er_48,
            vol_pctile,
            cost_atr_ratio,
            stress_result,
            thresholds=self.thresholds,
        )
        return df.with_columns(pl.lit(self.classifier_id).alias("classifier_id"))

    @property
    def n_states(self) -> int:
        return len(REGIME_LABELS)

    @property
    def classifier_id(self) -> str:
        return "quantile_regime_v1"
