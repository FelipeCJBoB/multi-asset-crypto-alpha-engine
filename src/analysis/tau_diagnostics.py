"""Diagnóstico de realização de `tau` — quão perto do alvo NOMINAL de taxa
de sinal fica o que a Camada 1 de fato produziu fora da amostra.

**Contexto (não é um gate operacional).** `src.models.alpha.fit_side_model`
fixa `tau` IN-FOLD, a priori, como o quantil `1 - target_signal_rate` da
distribuição de probabilidade calibrada do PRÓPRIO treino daquele lado
(`target_signal_rate = 0,0189`, `constants.yaml`, §0.2 R3) — nunca por
métrica OOS (B20, CLAUDE.md). Esse desenho garante, POR CONSTRUÇÃO, que a
taxa de sinal IN-FOLD bata o orçamento. A pergunta que este módulo responde
é diferente: aplicado OOS (nos 5 caminhos de backtest do CPCV, já
materializados em `experiments/alpha_layer1_report.json::
camada1_backtest_by_path`), o `tau` assim fixado produz uma frequência de
sinal PRÓXIMA da nominal, ou o quantil IN-FOLD generaliza mal? Isso é
diagnóstico, não vira insumo de treino nem seleção de modelo — mesma
fronteira que `src.analysis.attribution` já declara (PÓS-HOC, lê resultado
REALIZADO já persistido em disco, nenhum retreino).

**Alvo nominal — antes de qualquer atrito de preenchimento.**
`target_signal_rate × bars_per_year` — é a própria definição do quantil
(`1 - target_signal_rate` da massa de probabilidade calibrada) aplicada a
um ano inteiro de barras. Não depende de nenhum dado de backtest — é
aritmética pura sobre os dois parâmetros de entrada.

**Correção (Faixa 1.6, Bloco 3, 2026-08-09) — o fator `2.0` (lados) foi
removido daqui.** Este módulo introduziu o fator originalmente, com o
comentário "2.0 é contagem estrutural de lados, não hiperparâmetro" — mas
a derivação do orçamento em `PRD_V3_2_UNIFICADO.md:95-101` (§0.2 R3) não
tem termo de lado: `trades/mês ≤ (fee_budget_monthly × equity) / (N × c)`,
onde `c` é custo POR TRADE, agnóstico de lado, e o resultado (`661/ano ·
1,89% das barras`) já é uma contagem TOTAL. `target_signal_rate` foi
DERIVADO desse total (`661 / 35.064 ≈ 0,0189`), então multiplicar de volta
por 2 aqui dobra o orçamento de fees implícito — não é uma leitura
alternativa legítima, é o mesmo orçamento contado duas vezes. Ver
`config/constants.yaml::fee_budget_is_per_side` (provenance DERIVED) e
`src/analysis/faixa1_6_reconciliation.py` (Bloco 3) para a auditoria
completa, incluindo onde esse fator se propagou (`src/analysis/
faixa1_5_prerequisites.py::fee_budget_sweep`, mesmo `git blame`).

**Realizado — DUAS versões, deliberadamente não escolhidas uma pela
outra.** `camada1_backtest_by_path` carrega, por caminho de CPCV,
`n_signals` (toda barra em que `p_side > tau` para o lado escolhido — ver
docstring de `src.models.alpha`, "inferência roda sobre a barra", não
filtrada por resultado de preenchimento) e `n_filled_trades`/
`trades_per_year` (`src.models.backtest_lite.backtest_by_path`, já
restrito a `barrier_hit != "NOFILL"` — uma camada de atrito de execução já
aplicada). As duas comparações contra o alvo respondem perguntas
diferentes:

- `n_signals`/ano (**pré-fill**) — o mais parecido com a definição pura do
  quantil, porque não carrega nenhuma suposição sobre preenchimento.
  Compara `tau` contra o que ele foi desenhado para produzir.
- `n_filled_trades`/ano == `trades_per_year` do relatório (**pós-fill**,
  já anualizado por `src.models.backtest_lite.sharpe_naive`) — o que de
  fato vira posição executada. Mistura a generalização de `tau` com a taxa
  de preenchimento do Label Engine (§9, fill otimista — não é medição de
  execução real, ver `src.backtest.fill_reconciliation` para a versão com
  book real).

Este módulo calcula as duas e nomeia cada uma explicitamente nos campos de
saída (`n_signals_per_year`/`ratio_pre_fill_to_target` vs.
`n_filled_per_year`/`ratio_post_fill_to_target`) — nunca reduz a uma única
"a realizada", porque isso esconderia qual pergunta está sendo respondida.

**Anualização de `n_signals` — aproximação declarada.** O relatório grava
`trades_per_year` já anualizado (`n_filled_trades / período_anos`, onde
`período_anos` vem do span de calendário coberto pelos `t0` dos trades
FILTRADOS/preenchidos — `span_seconds(filled["t0"])` em
`src.models.backtest_lite.backtest_by_path`), mas não grava o span próprio
de `n_signals` (todos os sinais, antes do filtro de preenchimento). Este
módulo back-deriva `período_anos = n_filled_trades / trades_per_year` e
aplica o MESMO período para anualizar `n_signals` — assume que o span de
calendário dos sinais não preenchidos não difere materialmente do span dos
preenchidos (razoável quando o preenchimento não se concentra numa fatia
estreita do tempo, mas não é medido diretamente aqui; se um dia importar,
`n_signals` por caminho precisaria do próprio `t0` mín/máx, hoje fora do
schema do relatório). Declarado aqui em vez de silencioso (Regra Zero,
CLAUDE.md).

**Dispersão entre caminhos.** `max(valor) / min(valor)` sobre os 5
caminhos válidos — mede o quanto a generalização de `tau` varia por
recorte temporal do CPCV, calculada separadamente para pré-fill e
pós-fill (as duas podem divergir: preenchimento não é uniforme no tempo).

Cada valor numérico sai como `Metric` (`src.core.metric`) — nunca um
`float` solto — para que quem ler o resultado não precise reler este
módulo pra saber o que o número significa."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from src.core.metric import Metric, Unit, not_computable, safe_ratio

logger = structlog.get_logger(__name__)

_CAMADA1_KEY = "camada1_backtest_by_path"
_N_BACKTEST_PATHS_KEY = "n_backtest_paths"
_DEFAULT_SOURCE = "experiments/alpha_layer1_report.json"

_N_SEMANTICS_PATHS = "cpcv_paths"
_N_SEMANTICS_SIGNALS = "signals"
_N_SEMANTICS_TRADES = "trades"
_N_SEMANTICS_BARS = "bars"

_REQUIRED_PATH_FIELDS = ("path_id", "n_signals", "n_filled_trades", "trades_per_year")


@dataclass(frozen=True, slots=True)
class TauPathRealization:
    """Um caminho de CPCV — as duas anualizações (`n_semantics` distingue
    qual) e a razão de cada uma contra `TauDiagnosticResult.
    target_nominal_per_year` (mesmo `Metric`, herdado via `safe_ratio`, ver
    docstring do módulo)."""

    path_id: int
    n_signals_per_year: Metric  # pré-fill — ver docstring do módulo
    n_filled_per_year: Metric  # pós-fill — == trades_per_year do relatório
    ratio_pre_fill_to_target: Metric
    ratio_post_fill_to_target: Metric


@dataclass(frozen=True, slots=True)
class TauDiagnosticResult:
    """Saída completa de `tau_realization_diagnostic` — alvo nominal, um
    `TauPathRealization` por caminho (ordenado por `path_id`), médias
    através dos caminhos e dispersão (`max/min`), pré-fill e pós-fill em
    campos separados o tempo todo (ver docstring do módulo — nunca reduz a
    uma versão só)."""

    target_nominal_per_year: Metric
    paths: tuple[TauPathRealization, ...]
    mean_n_signals_per_year: Metric
    mean_n_filled_per_year: Metric
    mean_ratio_pre_fill_to_target: Metric
    mean_ratio_post_fill_to_target: Metric
    dispersion_pre_fill: Metric
    dispersion_post_fill: Metric


def _require_path_fields(entry: dict[str, Any], *, path_key: str) -> None:
    missing = sorted(set(_REQUIRED_PATH_FIELDS) - set(entry.keys()))
    if missing:
        raise ValueError(
            f"tau_realization_diagnostic: caminho {path_key!r} sem campo(s) "
            f"obrigatório(s) {missing} em '{_CAMADA1_KEY}'"
        )


def _finite_valid(metrics: Sequence[Metric]) -> list[Metric]:
    return [m for m in metrics if m.valid and math.isfinite(m.value)]


def _mean_metric(
    metrics: Sequence[Metric], *, unit: Unit, n_semantics: str, source: str
) -> Metric:
    """Média aritmética sobre os caminhos com `Metric` válido — caminhos
    inválidos (span de fill degenerado, ver `_annualize_path`) são
    excluídos e logados, não tratados como `0.0` silencioso (mesmo
    princípio de `not_computable`, `src.core.metric`)."""
    valid = _finite_valid(metrics)
    if not valid:
        return not_computable(
            unit, n_semantics, source, "nenhum caminho com métrica válida para média"
        )
    if len(valid) < len(metrics):
        logger.warning(
            "analysis.tau_diagnostics.media_com_caminhos_invalidos_excluidos",
            n_total=len(metrics),
            n_validos=len(valid),
            source=source,
        )
    mean_value = sum(m.value for m in valid) / len(valid)
    return Metric(
        value=mean_value, unit=unit, n=len(valid), n_semantics=n_semantics, source=source
    )


def _dispersion_metric(metrics: Sequence[Metric], *, source: str) -> Metric:
    """`max(valor) / min(valor)` sobre os caminhos com `Metric` válido —
    `NOT_COMPUTABLE` com menos de 2 caminhos válidos (dispersão de 1 ponto
    é trivialmente 1.0, não mede nada sobre variação entre caminhos)."""
    valid = _finite_valid(metrics)
    # mínimo matemático p/ "dispersão entre caminhos" existir — int, não precisa constants.yaml
    if len(valid) < 2:
        return not_computable(
            Unit.RATIO,
            _N_SEMANTICS_PATHS,
            source,
            f"apenas {len(valid)} caminho(s) válido(s) — dispersão exige >= 2",
        )
    max_metric = max(valid, key=lambda m: m.value)
    min_metric = min(valid, key=lambda m: m.value)
    max_wrapped = Metric(
        value=max_metric.value,
        unit=max_metric.unit,
        n=len(valid),
        n_semantics=_N_SEMANTICS_PATHS,
        source=source,
    )
    min_wrapped = Metric(
        value=min_metric.value,
        unit=min_metric.unit,
        n=len(valid),
        n_semantics=_N_SEMANTICS_PATHS,
        source=source,
    )
    return safe_ratio(
        max_wrapped,
        min_wrapped,
        require_den_positive=True,
        unit=Unit.RATIO,
        n_semantics=_N_SEMANTICS_PATHS,
        source=source,
    )


def _annualize_path(entry: dict[str, Any], *, path_source: str) -> tuple[Metric, Metric]:
    """`(n_signals_per_year, n_filled_per_year)` para um caminho —
    `n_filled_per_year` é `trades_per_year` do relatório, direto (já
    anualizado por `src.models.backtest_lite.sharpe_naive` sobre o span de
    calendário dos trades PREENCHIDOS). `n_signals_per_year` back-deriva o
    mesmo período implícito (`n_filled_trades / trades_per_year`) e aplica
    a `n_signals` — ver docstring do módulo, seção "Anualização de
    n_signals", para a suposição que isso carrega.

    Caminho com `n_filled_trades <= 0` ou `trades_per_year` não-finito/
    <= 0 não tem período implícito válido — as duas métricas voltam
    `NOT_COMPUTABLE` em vez de dividir por algo degenerado."""
    n_signals = int(entry["n_signals"])
    n_filled = int(entry["n_filled_trades"])
    raw_trades_per_year = entry["trades_per_year"]
    # `backtest_by_path` serializa NaN (caminho sem nenhum trade preenchido)
    # como `null` de JSON -- `float(None)` explodiria antes da guarda de
    # `period_valid` abaixo ter a chance de tratar isso como degenerado.
    filled_per_year_value = (
        float(raw_trades_per_year) if raw_trades_per_year is not None else float("nan")
    )

    period_valid = (
        n_filled > 0 and math.isfinite(filled_per_year_value) and filled_per_year_value > 0.0
    )
    if not period_valid:
        reason = (
            f"n_filled_trades={n_filled}, trades_per_year={filled_per_year_value!r} — "
            "período implícito degenerado, não é possível anualizar"
        )
        return (
            not_computable(Unit.COUNT, _N_SEMANTICS_SIGNALS, path_source, reason),
            not_computable(Unit.COUNT, _N_SEMANTICS_TRADES, path_source, reason),
        )

    n_filled_per_year = Metric(
        value=filled_per_year_value,
        unit=Unit.COUNT,
        n=n_filled,
        n_semantics=_N_SEMANTICS_TRADES,
        source=path_source,
    )
    implied_period_years = n_filled / filled_per_year_value
    n_signals_per_year_value = n_signals / implied_period_years
    n_signals_per_year = Metric(
        value=n_signals_per_year_value,
        unit=Unit.COUNT,
        n=n_signals,
        n_semantics=_N_SEMANTICS_SIGNALS,
        source=path_source,
    )
    return n_signals_per_year, n_filled_per_year


def tau_realization_diagnostic(
    report: dict[str, Any],
    *,
    target_signal_rate: float,
    bars_per_year: float,
    source: str = _DEFAULT_SOURCE,
) -> TauDiagnosticResult:
    """Diagnóstico completo — ver docstring do módulo para a definição de
    cada peça. `report` é `experiments/alpha_layer1_report.json` já
    carregado (`orjson.loads`/`json.load`) pelo chamador — este módulo não
    resolve o caminho do arquivo (mesma convenção de
    `src.analysis.attribution.gain_by_side`, que recebe `diagnostics_dir`
    já resolvido: `src.analysis` não conhece a convenção de path de
    `src.models`).

    `target_signal_rate`/`bars_per_year` são parâmetros explícitos, não
    lidos de `constants.yaml` por este módulo — o chamador (tipicamente um
    teste, via `load_constant("target_signal_rate")` de algum pacote com
    `_constants.py`) decide a proveniência; este módulo só faz a
    aritmética, coerente com a fronteira do módulo (nenhum import de
    `src.models` — ver contratos de import-linter em `pyproject.toml`,
    `"models não importa analysis"`/`"features não importa analysis"`)."""
    if target_signal_rate <= 0.0:
        raise ValueError(
            f"tau_realization_diagnostic: target_signal_rate={target_signal_rate} <= 0"
        )
    if bars_per_year <= 0.0:
        raise ValueError(f"tau_realization_diagnostic: bars_per_year={bars_per_year} <= 0")
    if _CAMADA1_KEY not in report:
        raise ValueError(f"tau_realization_diagnostic: '{_CAMADA1_KEY}' ausente do report")
    by_path: dict[str, Any] = report[_CAMADA1_KEY]
    if not by_path:
        raise ValueError(f"tau_realization_diagnostic: '{_CAMADA1_KEY}' vazio — nada para medir")

    declared_n_paths = report.get(_N_BACKTEST_PATHS_KEY)
    if declared_n_paths is not None and int(declared_n_paths) != len(by_path):
        raise ValueError(
            f"tau_realization_diagnostic: '{_N_BACKTEST_PATHS_KEY}'={declared_n_paths} "
            f"diverge de len('{_CAMADA1_KEY}')={len(by_path)}"
        )

    # alvo nominal — quantil (1 - target_signal_rate) aplicado a um ano
    # inteiro de barras. SEM fator de lado (Faixa 1.6 Bloco 3 — ver
    # docstring do módulo, "Correção": target_signal_rate já é uma taxa
    # TOTAL, derivada de §0.2 R3 sem termo de lado; dobrar aqui dobraria o
    # orçamento de fees implícito).
    target_value = target_signal_rate * bars_per_year
    target = Metric(
        value=target_value,
        unit=Unit.COUNT,
        n=round(bars_per_year),
        n_semantics=_N_SEMANTICS_BARS,
        source=f"{source}::target_signal_rate={target_signal_rate}::bars_per_year={bars_per_year}",
    )

    paths: list[TauPathRealization] = []
    for path_key in sorted(by_path, key=int):
        entry = by_path[path_key]
        _require_path_fields(entry, path_key=path_key)
        path_id = int(entry["path_id"])
        path_source = f"{source}::{_CAMADA1_KEY}::path_{path_id}"

        n_signals_per_year, n_filled_per_year = _annualize_path(entry, path_source=path_source)
        ratio_pre = safe_ratio(
            n_signals_per_year,
            target,
            require_den_positive=True,
            unit=Unit.RATIO,
            n_semantics=_N_SEMANTICS_SIGNALS,
            source=path_source,
        )
        ratio_post = safe_ratio(
            n_filled_per_year,
            target,
            require_den_positive=True,
            unit=Unit.RATIO,
            n_semantics=_N_SEMANTICS_TRADES,
            source=path_source,
        )
        paths.append(
            TauPathRealization(
                path_id=path_id,
                n_signals_per_year=n_signals_per_year,
                n_filled_per_year=n_filled_per_year,
                ratio_pre_fill_to_target=ratio_pre,
                ratio_post_fill_to_target=ratio_post,
            )
        )

    mean_signals = _mean_metric(
        [p.n_signals_per_year for p in paths],
        unit=Unit.COUNT,
        n_semantics=_N_SEMANTICS_PATHS,
        source=source,
    )
    mean_filled = _mean_metric(
        [p.n_filled_per_year for p in paths],
        unit=Unit.COUNT,
        n_semantics=_N_SEMANTICS_PATHS,
        source=source,
    )
    mean_ratio_pre = safe_ratio(
        mean_signals,
        target,
        require_den_positive=True,
        unit=Unit.RATIO,
        n_semantics=_N_SEMANTICS_PATHS,
        source=source,
    )
    mean_ratio_post = safe_ratio(
        mean_filled,
        target,
        require_den_positive=True,
        unit=Unit.RATIO,
        n_semantics=_N_SEMANTICS_PATHS,
        source=source,
    )
    dispersion_pre = _dispersion_metric([p.n_signals_per_year for p in paths], source=source)
    dispersion_post = _dispersion_metric([p.n_filled_per_year for p in paths], source=source)

    logger.info(
        "analysis.tau_diagnostics.tau_realization_diagnostic_done",
        target_nominal_per_year=target.value,
        mean_n_signals_per_year=mean_signals.value,
        mean_n_filled_per_year=mean_filled.value,
        mean_ratio_pre_fill_to_target=mean_ratio_pre.value,
        mean_ratio_post_fill_to_target=mean_ratio_post.value,
        dispersion_pre_fill=dispersion_pre.value,
        dispersion_post_fill=dispersion_post.value,
        n_paths=len(paths),
    )

    return TauDiagnosticResult(
        target_nominal_per_year=target,
        paths=tuple(paths),
        mean_n_signals_per_year=mean_signals,
        mean_n_filled_per_year=mean_filled,
        mean_ratio_pre_fill_to_target=mean_ratio_pre,
        mean_ratio_post_fill_to_target=mean_ratio_post,
        dispersion_pre_fill=dispersion_pre,
        dispersion_post_fill=dispersion_post,
    )
