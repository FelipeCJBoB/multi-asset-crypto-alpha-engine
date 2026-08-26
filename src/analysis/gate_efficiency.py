"""AG-118 — Gate Efficiency: do candidato vencedor do `AG-114` ao consumo
real por Risk/Decision Engine (`PLANO_MESTRE_PRINCE2.md` §15.12.4,
`audit/architecture_gaps_log.yaml::AG-118`).

**A pergunta que este módulo responde, DIFERENTE de `AG-114`.** `AG-114`
mede se um candidato de regime TEM estrutura suficiente pra ser um bom
detector (gates de occupancy/transition-failure + heterogeneidade de
volatilidade futura) — pergunta abstrata, sobre o candidato em si. Este
módulo mede se o candidato JÁ ESCOLHIDO (`hmm_gaussian_k4_v1`, vencedor
real do `AG-114`, `PLANO_MESTRE_PRINCE2.md §15.12.5`) é ÚTIL como GATE
ECONÔMICO pro triple-barrier real: `P(stop|regime)`, `P(target|regime)`,
`E[return|regime]`, `tail_loss|regime`, `holding_time|regime`, e a
pergunta central da recomendação #5 do ADR-001 (percentil de holding
time) + a pergunta original do Manager ("o gate remove uma parte
desproporcional dos eventos ruins sem destruir demasiadamente os bons?").

**Verificado contra o ADR-001 completo antes de escrever este módulo**
(`docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md`,
Partes I/II, ~1900 linhas — versão completa, não o resumo de 222 linhas
lido antes nesta sessão). 3 achados relevantes:

1. **§3.4 Cláusula 2 já antecipa exatamente este papel** — o contrato
   `regime()` proposto tem um campo `tradeable: Boolean!` descrito como
   "papel 2 — o GATE". Este módulo produz a EVIDÊNCIA (via
   `GateEfficiencyResult.lift`) que justificaria (ou não) ligar esse
   campo pro candidato vencedor — não implementa o campo em si, que
   pertence à camada de artefato formal (`src/io/artifact.py`/
   `src/io/schema.py`, ADR-001 action item 3, **ainda não construída**).
2. **Não bloqueado pelo action item 3** ("implementar `src/io/
   artifact.py`+`schema.py` antes de qualquer outro módulo novo") —
   esse item é sobre a camada de LAKE/manifest formal (INV-A a INV-D)
   que serviria artefatos de PRODUÇÃO consumidos por outros estágios do
   pipeline. Este módulo é análise/medição pós-hoc (`src/analysis/`,
   fora do contrato `importlinter` de propósito, mesma categoria de
   `m4_critical_windows.py`/`m6_common_factor_hypothesis.py` já
   existentes) — nunca produz artefato consumido como insumo de
   treino/seleção, só relatório JSON em `experiments/`.
3. **`decode_mode` obrigatório (§3.4 Cláusula 2) — verificado, não
   assumido.** ADR-001 exige que só rótulo `filter` (causal,
   `p(z_t|y_{1:t})`, nunca smoother/Viterbi) seja consumível por
   Learner/Gate. `src/regime/hmm_gaussian.py::predict_hmm_gaussian`
   (docstring, linha 361) já implementa `filter` — `hmm_gaussian_k4_v1`
   está em conformidade, nenhuma mudança necessária.

**Achado colateral registrado, não bloqueante** (`AG-121`,
`audit/architecture_gaps_log.yaml`): ADR-001 §3.4 recomenda
canonicalizar estado por volatilidade ascendente; a implementação real
(`src/regime/canonicalization.py`, `PRD_V4_1.md` §3.2 literal) ordena
por RETORNO ascendente — divergência real, não reconciliada. Este
módulo evita o problema por construção — nunca confia em `canonical_id`
como proxy de volatilidade, sempre deriva o bucket de stress via
`identify_stress_state_by_volatility` (mesma função do `AG-114`, mede
`realized_vol_short` diretamente).

**Custo: zero fits novos.** `RawLabels` de `hmm_gaussian_k4_v1` (canonical
_id/close_time_ms/open_time_ms por barra, já causal/filter) foram
persistidos pela rodada real do `AG-114` (`experiments/m4_raw_labels/`,
`persist_raw_labels=True` default desde a extensão de gate-quality) —
lidos aqui, nunca refeitos. `_SymbolForwardVolHistory` (`realized_vol_
short`) é candidato-independente e barato (só IO + transformação
vetorizada, sem fit) — recomputado fresco via `m4_critical_windows.
_compute_symbol_forward_vol_history`, mesma função já usada pelo bloco
de gate-quality, não uma cópia nova.

**Escopo: por-janela, agregado por pooling de contagem dentro da
resolução — não por histórico contínuo.** `hmm_gaussian_k4_v1` foi
ajustado por walk-forward ANCORADO EM CADA JANELA CRÍTICA
separadamente (5 janelas = 5 folds de teste independentes, não uma
série contínua) — não existe uma série "histórico completo" coerente
pra reconstruir aqui sem refit novo (fora do orçamento de custo zero
deste módulo). `GateEfficiencySymbolDetail` é por (resolução, janela,
símbolo, side, bucket); `GateEfficiencyResult` (a métrica de remoção
assimétrica) faz POOLING de contagens SL/TP através das janelas dentro
de uma resolução — não mediana de taxas pequenas-amostra, que seria
menos potente estatisticamente pra exatamente o mesmo problema de poder
que already afetou Jump Model (`AG-119`)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog

from src.analysis import m4_critical_windows as mcw
from src.analysis import m4_regime_comparison as m4
from src.analysis.m6_common_factor_hypothesis import StratumMetrics, stratum_metrics
from src.data._constants import load_constant as load_data_constant
from src.labels.triple_barrier import LabelConfig
from src.risk._constants import load_constant as load_risk_constant
from src.validation.regime_utility import identify_stress_state_by_volatility

logger = structlog.get_logger(__name__)

#: `AG-244-ADDENDUM-3` -- fração do período usada para AJUSTAR o rótulo de
#: stress no modo causal; o restante é o que se avalia. Um terço é o maior
#: prefixo que ainda deixa a maior parte da amostra para medição, e não é um
#: parâmetro de negócio: mudá-lo altera a precisão do rótulo, nunca uma
#: decisão de produção.
_FRACAO_PREFIXO_ROTULO_CAUSAL: Final[float] = 1.0 / 3.0  # noqa: magic-number -- ver comentário acima

#: Piso de barras para o modo causal ter prefixo defensável. Abaixo disso a
#: célula é omitida com aviso, nunca silenciosamente rotulada pelo caminho
#: global (que é o vazamento que este modo existe para evitar).
_MIN_BARS_ROTULO_CAUSAL: Final[int] = 300  # noqa: magic-number -- ver comentário acima

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_PATH: Final[Path] = _REPO_ROOT / "experiments" / "gate_efficiency_report.json"

_SIDES: Final[tuple[int, ...]] = (1, -1)


@dataclass(frozen=True, slots=True)
class GateEfficiencySymbolDetail:
    """1 (resolução, janela, símbolo, side, bucket) -- reusa `_asof_join_
    regime_onto_labels`(`m4_critical_windows`)/`stratum_metrics`
    (`m6_common_factor_hypothesis`), zero join/fórmula nova pros 3 campos
    já existentes (`p_target`/`p_stop`/`e_return_atr`). `is_stress_bucket`
    -- `bucket == identify_stress_state_by_volatility(...)` pro (símbolo,
    janela, resolução) inteiro (1 bucket de stress por célula, não por
    side -- mesma convenção de `AG-114`/`GateQualitySymbolDetail`).
    `n=0` propaga `NaN` em todos os campos de estatística (nunca `0.0`
    silencioso -- "não computável" != "medido zero", mesma disciplina de
    `BarrierFractions`/`Metric.valid`)."""

    resolution_id: str
    window_name: str
    symbol: str
    side: int
    bucket: int
    is_stress_bucket: bool
    n: int
    p_target: float
    p_stop: float
    e_return_atr: float
    p05_return_atr: float
    median_holding_bars: float
    p80_holding_bars: float


@dataclass(frozen=True, slots=True)
class GateEfficiencyResult:
    """1 (resolução, símbolo, side) -- a métrica de "remoção assimétrica"
    (formalização da pergunta original do Manager: "o gate remove uma
    parte desproporcional dos eventos ruins sem destruir demasiadamente
    os bons?"). `P(bucket=stress | desfecho)` -- não `P(desfecho |
    bucket)` -- pergunta invertida de propósito: mede o que o GATE faria
    (bloquear entradas em `bucket=stress`) em termos do que isso
    captura/descarta. Pooling de contagem SL/TP através das 5 janelas
    críticas dentro da resolução (não mediana de taxas pequena-amostra --
    ver docstring do módulo).

    `lift > 1` = o gate captura proporcionalmente mais eventos ruins do
    que bons (útil); `lift <= 1` = não discrimina ou é contraproducente.
    `lift = NaN` se `good_event_cost_rate == 0` (sem base de comparação --
    nunca `inf` silencioso). **Nenhum limiar de "lift mínimo pra valer a
    pena" é fixado aqui** -- TBD, decidido só depois da medição real
    (B23/B20)."""

    resolution_id: str
    symbol: str
    side: int
    bad_event_capture_rate: float
    good_event_cost_rate: float
    lift: float
    n_sl_total: int
    n_tp_total: int
    n_sl_in_stress: int
    n_tp_in_stress: int


def _load_raw_labels_from_parquet(
    resolution_id: str, window_name: str, symbol: str, classifier_id: str
) -> m4.RawLabels | None:
    """Lê o `RawLabels` já persistido pela rodada real do `AG-114`
    (`mcw.RAW_LABELS_OUTPUT_DIR`, `persist_raw_labels=True`, mesmo path
    que `mcw._raw_labels_path` já usa pra ESCREVER) -- `None` se o
    arquivo não existe (célula que falhou/foi pulada, ex. `AG-120`, ou
    símbolo fora de `window.symbols` -- LUNA/FTX são BTC-only). Nunca
    levanta -- ausência é um resultado válido (mesma disciplina AG-019),
    não um erro de programação."""
    path = mcw._raw_labels_path(resolution_id, window_name, symbol, classifier_id)
    if not path.exists():
        return None
    df = pl.read_parquet(path)
    return m4.RawLabels(
        open_time_ms=df["open_time_ms"].cast(pl.Int64).to_numpy(),
        close_time_ms=df["close_time_ms"].cast(pl.Int64).to_numpy(),
        canonical_id=df["canonical_id"].cast(pl.Int64).to_numpy(),
    )


def _tail_and_holding_stats(labels: pl.DataFrame) -> tuple[float, float, float]:
    """`(p05_return_atr, median_holding_bars, p80_holding_bars)` --
    `labels` já filtrado pelo chamador (symbol/side/bucket). `n==0` ou
    nenhuma linha com `atr_at_t0>0` devolve `NaN` nos 3 campos --
    `atr_at_t0` é volatilidade, deveria ser sempre positivo, mas o guard
    é explícito (`unguarded-ratio`) em vez de assumir."""
    if labels.height == 0:
        nan = float("nan")
        return nan, nan, nan
    valid = labels.filter(pl.col("atr_at_t0") > 0)
    if valid.height == 0:
        nan = float("nan")
        return nan, nan, nan
    return_atr = (valid["ret_net"] / valid["atr_at_t0"]).to_numpy()  # noqa: unguarded-ratio -- filtrado por atr_at_t0>0 acima
    holding_bars = valid["n_bars_held"].cast(pl.Float64).to_numpy()
    tail_loss_pctl = float(load_data_constant("gate_efficiency_tail_loss_percentile"))
    holding_time_pctl = float(load_data_constant("gate_efficiency_holding_time_percentile"))
    return (
        float(np.percentile(return_atr, tail_loss_pctl)),
        float(np.median(holding_bars)),
        float(np.percentile(holding_bars, holding_time_pctl)),
    )


def _gate_efficiency_for_symbol_window(
    resolution_id: str,
    window: mcw.CriticalWindow,
    symbol: str,
    regime_raw: m4.RawLabels,
    vol_history: mcw._SymbolForwardVolHistory,
    labels_full: pl.DataFrame,
    *,
    tp_atr_mult: float,
    sl_atr_mult: float,
    maker_fee: float,
    taker_fee: float,
    causal_stress_label: bool = False,
) -> tuple[tuple[GateEfficiencySymbolDetail, ...], pl.DataFrame | None]:
    """1 célula (resolução, janela, símbolo) -- devolve `(rows, joined)`:
    `rows` = 1 `GateEfficiencySymbolDetail` por (side, bucket) presente;
    `joined` = o `DataFrame` do as-of join (`_asof_join_regime_onto_
    labels`) com a coluna `_is_stress` já marcada, reusado pelo chamador
    pra `_pool_asymmetric_removal` -- calcula o join/`identify_stress_
    state_by_volatility` UMA VEZ só, nunca duplicado. `((), None)` se não
    sobrar nenhuma linha depois do as-of join (mesma disciplina AG-019 de
    `_heterogeneity_for_symbol_window` -- ausência de dado não é erro)."""
    canonical_id, _close_ms, realized_vol_short, _fwd_vol = mcw._join_candidate_with_vol_history(
        regime_raw, vol_history
    )
    if canonical_id.shape[0] == 0:
        return (), None

    start_ms = mcw._iso_date_to_epoch_ms(window.start)
    end_ms = mcw._iso_date_to_epoch_ms(window.end)

    # `AG-244-ADDENDUM-3` -- QUAL estado é "stress" é um RÓTULO, e até
    # 2026-08-26 ele era decidido com a média de `realized_vol_short` sobre a
    # série INTEIRA do candidato, que inclui a janela cujo resultado está
    # sendo medido. Não é vazamento de preço (a vol é observável em `t`), é
    # vazamento de SELEÇÃO -- e basta para inflar qualquer efeito
    # condicionado ao rótulo. `AG-127` (Ângulo 1) já tinha encontrado e
    # corrigido a mesma coisa no caminho de PRODUÇÃO (`build_hmm.py`, rótulo
    # por fold sobre o treino); os caminhos de análise ficaram para trás.
    #
    # `causal_stress_label=True` ajusta o rótulo só com barras ANTERIORES ao
    # início da janela e o aplica dentro dela. Default `False` preserva o
    # comportamento histórico bit-exato, para que a comparação entre os dois
    # seja possível -- que é justamente a medição que `AG-244-ADDENDUM-3`
    # deixou pendente.
    # Medido ao implementar: os `RawLabels` persistidos NÃO cobrem a janela
    # declarada inteira -- são a fatia OOS do fold (ex. janela LUNA declara
    # 2021-04-01..2022-07-01 e o parquet cobre 2022-04-01..2022-07-01). Logo
    # "rotular com dado anterior à janela" é inviável: não existe dado
    # anterior neste artefato. O escopo causal disponível é um PREFIXO do
    # próprio período: ajusta o rótulo no primeiro terço e avalia no resto,
    # que é a mesma disciplina de `AG-127` (rótulo do treino aplicado ao
    # teste) no maior escopo que o dado permite.
    fit_mask = None
    eval_start_ms = start_ms
    if causal_stress_label:
        if _close_ms.shape[0] < _MIN_BARS_ROTULO_CAUSAL:
            logger.warning(
                "analysis.gate_efficiency.poucas_barras_para_rotulo_causal",
                resolution_id=resolution_id,
                symbol=symbol,
                window=window.name,
                n_barras=int(_close_ms.shape[0]),
                detail=(
                    "celula omitida sob causal_stress_label=True -- prefixo de "
                    "ajuste ficaria pequeno demais para um rotulo defensavel "
                    "(AG-244-ADDENDUM-3)"
                ),
            )
            return (), None
        corte_idx = int(_close_ms.shape[0] * _FRACAO_PREFIXO_ROTULO_CAUSAL)
        corte_ms = int(_close_ms[corte_idx])
        fit_mask = _close_ms < corte_ms
        # A avaliação exclui o prefixo usado para rotular -- sem isso o
        # vazamento voltaria pela porta dos fundos, apenas menor.
        eval_start_ms = max(start_ms, corte_ms)
        if not bool(fit_mask.any()):
            return (), None
    stress_state_id = identify_stress_state_by_volatility(
        canonical_id, realized_vol_short, fit_mask=fit_mask
    )
    window_labels = labels_full.filter(
        (pl.col("t0").dt.epoch(time_unit="ms") >= eval_start_ms)
        & (pl.col("t0").dt.epoch(time_unit="ms") < end_ms)
    )
    joined = mcw._asof_join_regime_onto_labels(window_labels, regime_raw)
    if joined.height == 0:
        return (), None
    joined = joined.with_columns((pl.col("regime_bucket") == stress_state_id).alias("_is_stress"))

    rows: list[GateEfficiencySymbolDetail] = []
    for side in _SIDES:
        side_df = joined.filter(pl.col("side") == side)
        buckets = sorted(side_df["regime_bucket"].unique().to_list())
        for bucket in buckets:
            bucket_df = side_df.filter(pl.col("regime_bucket") == bucket)
            strat: StratumMetrics = stratum_metrics(
                bucket_df,
                symbol=symbol,
                side=side,
                regime=str(bucket),
                tp_atr_mult=tp_atr_mult,
                sl_atr_mult=sl_atr_mult,
                maker_fee=maker_fee,
                taker_fee=taker_fee,
            )
            p05_return_atr, median_holding, p80_holding = _tail_and_holding_stats(bucket_df)
            rows.append(
                GateEfficiencySymbolDetail(
                    resolution_id=resolution_id,
                    window_name=window.name,
                    symbol=symbol,
                    side=side,
                    bucket=int(bucket),
                    is_stress_bucket=int(bucket) == stress_state_id,
                    n=strat.n,
                    p_target=strat.frac_tp,
                    p_stop=strat.frac_sl,
                    e_return_atr=strat.edge_bruto_atr,
                    p05_return_atr=p05_return_atr,
                    median_holding_bars=median_holding,
                    p80_holding_bars=p80_holding,
                )
            )
    return tuple(rows), joined


def _pool_asymmetric_removal(
    resolution_id: str, symbol: str, side: int, joined_by_window: list[pl.DataFrame]
) -> GateEfficiencyResult:
    """`GateEfficiencyResult` pra 1 (resolução, símbolo, side) -- `joined_
    by_window`: 1 `DataFrame` por janela (saída de `_asof_join_regime_
    onto_labels`, JÁ filtrado por side, com coluna `regime_bucket` E
    `stress_state_id` daquela janela específica marcada via coluna
    booleana `_is_stress` adicionada pelo chamador -- pooling de
    CONTAGEM bruta através das janelas, não média/mediana de taxa
    pequena-amostra (ver docstring do módulo)."""
    if not joined_by_window:
        nan = float("nan")
        return GateEfficiencyResult(
            resolution_id=resolution_id, symbol=symbol, side=side,
            bad_event_capture_rate=nan, good_event_cost_rate=nan, lift=nan,
            n_sl_total=0, n_tp_total=0, n_sl_in_stress=0, n_tp_in_stress=0,
        )
    pooled = pl.concat(joined_by_window)
    sl_df = pooled.filter(pl.col("barrier_hit") == "SL")
    tp_df = pooled.filter(pl.col("barrier_hit") == "TP")
    n_sl_total = sl_df.height
    n_tp_total = tp_df.height
    n_sl_in_stress = sl_df.filter(pl.col("_is_stress")).height
    n_tp_in_stress = tp_df.filter(pl.col("_is_stress")).height

    nan = float("nan")
    bad_event_capture_rate = (
        n_sl_in_stress / n_sl_total if n_sl_total > 0 else nan  # noqa: unguarded-ratio -- guardado por n_sl_total>0
    )
    good_event_cost_rate = (
        n_tp_in_stress / n_tp_total if n_tp_total > 0 else nan  # noqa: unguarded-ratio -- guardado por n_tp_total>0
    )
    if good_event_cost_rate == 0 or np.isnan(good_event_cost_rate):
        lift = nan
    else:
        lift = bad_event_capture_rate / good_event_cost_rate  # noqa: unguarded-ratio -- guardado pelo if acima

    return GateEfficiencyResult(
        resolution_id=resolution_id,
        symbol=symbol,
        side=side,
        bad_event_capture_rate=bad_event_capture_rate,
        good_event_cost_rate=good_event_cost_rate,
        lift=lift,
        n_sl_total=n_sl_total,
        n_tp_total=n_tp_total,
        n_sl_in_stress=n_sl_in_stress,
        n_tp_in_stress=n_tp_in_stress,
    )


def compute_gate_efficiency_for_resolution(
    resolution_id: str,
    classifier_id: str,
    *,
    windows: tuple[mcw.CriticalWindow, ...] = mcw.CRITICAL_WINDOWS,
    labels_by_symbol: dict[str, pl.DataFrame],
    tp_atr_mult: float,
    sl_atr_mult: float,
    maker_fee: float,
    taker_fee: float,
    causal_stress_label: bool = False,
) -> tuple[tuple[GateEfficiencySymbolDetail, ...], tuple[GateEfficiencyResult, ...]]:
    """1 resolução completa -- itera (janela, símbolo) de `windows`,
    carrega `RawLabels` já persistido (`_load_raw_labels_from_parquet`,
    zero fit) + `_SymbolForwardVolHistory` fresco (barato, zero fit),
    devolve `(details, results)`. `classifier_id` sempre explícito do
    caller (B20 -- nunca hardcoded aqui, mesmo sendo `hmm_gaussian_k4_v1`
    na prática desta rodada)."""
    details: list[GateEfficiencySymbolDetail] = []
    joined_by_symbol_side: dict[tuple[str, int], list[pl.DataFrame]] = {}
    vol_history_cache: dict[str, mcw._SymbolForwardVolHistory] = {}

    for window in windows:
        for symbol in window.symbols:
            labels_full = labels_by_symbol.get(symbol)
            if labels_full is None:
                continue
            regime_raw = _load_raw_labels_from_parquet(
                resolution_id, window.name, symbol, classifier_id
            )
            if regime_raw is None:
                logger.warning(
                    "analysis.gate_efficiency.raw_labels_ausente",
                    resolution_id=resolution_id,
                    window=window.name,
                    symbol=symbol,
                    classifier_id=classifier_id,
                )
                continue
            if symbol not in vol_history_cache:
                try:
                    vol_history_cache[symbol] = mcw._compute_symbol_forward_vol_history(
                        symbol, resolution_id
                    )
                except Exception as exc:  # AG-019 -- 1 símbolo falhando não derruba os outros
                    logger.error(
                        "analysis.gate_efficiency.forward_vol_history_failed",
                        resolution_id=resolution_id,
                        symbol=symbol,
                        error=repr(exc),
                    )
                    continue
            vol_history = vol_history_cache[symbol]

            rows, joined = _gate_efficiency_for_symbol_window(
                resolution_id,
                window,
                symbol,
                regime_raw,
                vol_history,
                labels_full,
                tp_atr_mult=tp_atr_mult,
                sl_atr_mult=sl_atr_mult,
                maker_fee=maker_fee,
                taker_fee=taker_fee,
                causal_stress_label=causal_stress_label,
            )
            details.extend(rows)
            if joined is None:
                continue
            for side in _SIDES:
                key = (symbol, side)
                joined_by_symbol_side.setdefault(key, []).append(
                    joined.filter(pl.col("side") == side)
                )

    results: list[GateEfficiencyResult] = []
    for (symbol, side), frames in sorted(joined_by_symbol_side.items()):
        results.append(_pool_asymmetric_removal(resolution_id, symbol, side, frames))

    logger.info(
        "analysis.gate_efficiency.resolution_done",
        resolution_id=resolution_id,
        classifier_id=classifier_id,
        n_details=len(details),
        n_results=len(results),
    )
    return tuple(details), tuple(results)


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão de `m4_critical_windows._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("analysis.gate_efficiency.report_written", path=str(dest_path))


def _raw_labels_provenance(
    classifier_id: str, windows: tuple[mcw.CriticalWindow, ...]
) -> dict[str, Any]:
    """Achado do parecer de auditoria externa (2026-08-20, item 11 --
    `docs/parecer_auditoria_externa_2026-08-20_ag114_ag118.md`): um
    artefato `experiments/` que vira insumo de decisão de risco real
    herda requisito de proveniência, mesmo sem ser um artefato de lake
    formal (`src/io/artifact.py`, ADR-001, ainda não construído). Hash
    de conteúdo (blake2b) de TODOS os parquets de `RawLabels` de fato
    consumidos por esta rodada (ordenados, pra determinismo) + metadados
    de quando a rodada real do AG-114 que os gerou foi produzida
    (`experiments/m4_critical_windows_report.json::generated_at`/
    `code_version`, lidos sem reprocessar nada -- se esse arquivo não
    existir/não tiver os campos, `None` explícito, nunca inventado)."""
    hasher = hashlib.blake2b()
    n_files = 0
    for resolution_id in mcw.RESOLUTIONS:
        for window in windows:
            for symbol in window.symbols:
                path = mcw._raw_labels_path(resolution_id, window.name, symbol, classifier_id)
                if not path.exists():
                    continue
                hasher.update(path.read_bytes())
                n_files += 1

    ag114_generated_at: str | None = None
    ag114_code_version: str | None = None
    ag114_report_path = mcw.EXPERIMENTS_DIR / "m4_critical_windows_report.json"
    if ag114_report_path.exists():
        with ag114_report_path.open("rb") as fh:
            ag114_report = orjson.loads(fh.read())
        ag114_generated_at = ag114_report.get("generated_at")
        ag114_code_version = ag114_report.get("code_version")

    return {
        "raw_labels_content_hash_blake2b": hasher.hexdigest(),
        "raw_labels_n_files_hashed": n_files,
        "ag114_source_report_path": str(ag114_report_path),
        "ag114_source_generated_at": ag114_generated_at,
        "ag114_source_code_version": ag114_code_version,
    }


def run_and_save_gate_efficiency_report(
    classifier_id: str,
    *,
    resolutions: tuple[str, ...] = mcw.RESOLUTIONS,
    windows: tuple[mcw.CriticalWindow, ...] = mcw.CRITICAL_WINDOWS,
    dest_path: Path | None = None,
    causal_stress_label: bool = False,
) -> Path:
    """Ponto de entrada com IO -- carrega `labels.parquet` 1x por símbolo
    (reusado pelas `resolutions`, labels não dependem de resolução de
    regime, mesmo padrão de `run_and_save_critical_windows_report`),
    `tp_atr_mult`/`sl_atr_mult` de `LabelConfig.from_constants`/
    `maker_fee`/`taker_fee` de `config/constants.yaml::risk` -- MESMAS
    fontes já usadas pelo bloco `heterogeneity` existente, nenhuma
    constante nova. Persiste `GateEfficiencySymbolDetail`/
    `GateEfficiencyResult` por resolução, atômico (B29)."""
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    all_symbols = tuple(sorted({symbol for w in windows for symbol in w.symbols}))
    labels_by_symbol = mcw._load_labels_by_symbol(all_symbols)
    label_cfg = LabelConfig.from_constants(tf=mcw._HETEROGENEITY_LABELS_TF)
    tp_atr_mult = label_cfg.tp_atr_mult
    sl_atr_mult = label_cfg.sl_atr_mult
    maker_fee = float(load_risk_constant("maker_fee"))
    taker_fee = float(load_risk_constant("taker_fee"))

    by_resolution: list[dict[str, Any]] = []
    for resolution_id in resolutions:
        logger.info(
            "analysis.gate_efficiency.resolution_starting",
            resolution_id=resolution_id,
            classifier_id=classifier_id,
        )
        details, results = compute_gate_efficiency_for_resolution(
            resolution_id,
            classifier_id,
            windows=windows,
            labels_by_symbol=labels_by_symbol,
            tp_atr_mult=tp_atr_mult,
            sl_atr_mult=sl_atr_mult,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
            causal_stress_label=causal_stress_label,
        )
        by_resolution.append(
            {
                "resolution_id": resolution_id,
                "classifier_id": classifier_id,
                "details": [asdict(d) for d in details],
                "results": [asdict(r) for r in results],
            }
        )

    provenance = _raw_labels_provenance(classifier_id, windows)
    _atomic_write_json(
        {
            "classifier_id": classifier_id,
            "resolutions_evaluated": list(resolutions),
            **provenance,
            "by_resolution": by_resolution,
        },
        dest,
    )
    return dest


if __name__ == "__main__":
    raise SystemExit(
        "src.analysis.gate_efficiency: run_and_save_gate_efficiency_report requer "
        "classifier_id explícito (B20, nunca hardcoded aqui) -- rode manualmente:\n"
        "uv run python -c \"from src.analysis.gate_efficiency import "
        "run_and_save_gate_efficiency_report as r; "
        "r(classifier_id='hmm_gaussian_k4_v1')\""
    )
