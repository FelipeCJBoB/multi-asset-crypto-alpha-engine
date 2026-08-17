"""MECANISMO do alarme de deriva de `threshold_usdt` de dollar bar —
`audit/architecture_gaps_log.yaml::AG-042`, Opção A′ ("threshold fixo por
símbolo/resolução + alarme de deriva"), item 2 dos 3 registrados. Bloqueador
2 já foi decidido pelo Manager; este módulo implementa SÓ o item 2 (o
alarme em si) — NÃO decide o item 3 (`calibration_version`, regra formal de
quando/como incrementar a versão congelada em produção), que continua
aberto, decisão de negócio do Manager. Mesma disciplina de escopo que
`src.data.build_dollar_bars` já documenta para `calibration_scope=
"validation"`: este módulo nunca decide qual threshold vira produção, só
mede quanto um threshold recalibrado numa janela nova diverge de um
baseline já congelado, e sinaliza quando essa divergência passa de um
limiar declarado.

**Achado real que motiva este módulo, não hipotético.**
`tools/diagnostics/measure_dollar_threshold_drift.py` mediu BTCUSDT com
`drift_ratio=18,18x` entre a janela `2020_h1` (2020-01) e `etf` (2024-03) —
`experiments/dollar_threshold_drift.json`. Esse script é um DIAGNÓSTICO
PONTUAL (roda, gera JSON, acaba); não tem noção de "alarme" (limiar que
dispara flag) nem é reusável como função importável — ele mede densidade
histórica entre janelas fixas, não compara um threshold CONGELADO contra
uma janela nova em tempo de operação. Este módulo formaliza esse 2º cálculo
como função pública com resultado estruturado + limiar declarado em
`config/constants.yaml` (nunca um número solto no código, Regra Zero).

**Decisão de import `monitoring -> data` — verificada, não presumida.**
`pyproject.toml::[tool.importlinter]` tem exatamente 7 contratos
`forbidden`: `features !-> labels`, `models !-> execution`, `{exchange,
data, features, regime, risk, execution, live, monitoring} !-> labels`,
`risk !-> {execution, models}`, `models !-> analysis`, `features !->
analysis`, `data !-> analysis`. Nenhum deles proíbe `monitoring -> data`.
`src/monitoring/logging.py` (único outro módulo do pacote hoje) já
documenta a direção pretendida: "`exchange/` não precisa importar
`monitoring/` para logar" — ou seja, camadas de baixo NUNCA dependem de
`monitoring`, mas o inverso (monitoring lendo de baixo pra observar) é
exatamente o papel de um módulo de observabilidade, e nada mecanicamente
impede. Por isso `measure_new_window_drift` abaixo importa
`src.data._chunked_scan` diretamente (`date_chunks`/`scan_trades_totals`/
`query_baseline`/`target_n_bars`) — MESMA fórmula de `src.data.
build_dollar_bars.calibrate_dollar_threshold_for_validation`
(`threshold_usdt = total_dollar/target_n_bars`, baseline de `klines_1m` em
`tf="15m"`), não reimplementada às cegas: é o mesmo cálculo de uma linha,
citado aqui explicitamente para que uma mudança de fórmula em
`calibrate_dollar_threshold_for_validation` saiba que precisa atualizar
este módulo também (o motivo de não chamar aquela função diretamente é que
ela descarta `total_dollar` depois de calcular `threshold_usdt` — este
módulo precisa dos dois, ver `DollarBarDriftResult.new_window_total_
dollar`, e reimplementar o wrapper aqui evita escanear `aggTrades` 2x pra
medir a mesma janela).

Mesmo assim, `evaluate_drift` — a função que decide `alarm_triggered` — é
DELIBERADAMENTE pura: recebe os totais já medidos (n_trades, total_dollar,
threshold recalibrado) como parâmetro, não mede sozinha. Não é porque o
import fosse proibido (não é, ver acima) — é separação de concern: a lógica
"isto é deriva demais?" precisa ser testável com números fixos (inclusive
os REAIS já medidos hoje, BTCUSDT 18,18x) sem precisar de DuckDB/backfill
local. `tests/unit/test_monitoring_dollar_bar_drift.py` cobre `evaluate_
drift` inteiro sem tocar em `aggTrades`/`klines_1m` reais.

**O que este módulo NÃO faz.** Não decide `calibration_version` (item 3 de
AG-042). Não conecta a nenhum caller de produção/live — `src/live/` está
vazio hoje (só 3 linhas, docstring + `from __future__`), não existe
nenhum runner que consome isto ainda; o CLI abaixo é só para invocação
manual do operador contra um `_calibration.json` já escrito por
`src.data.build_dollar_bars.write_dollar_bars_and_calibration`."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import orjson
import structlog

from src.data import _chunked_scan
from src.data.build_dollar_bars import DollarBarCalibration

from ._constants import load_constant

logger = structlog.get_logger(__name__)

#: `tf` de calibração usada para o baseline de `klines_1m` que deriva
#: `target_n_bars` — precisa ser a MESMA que `src.data.build_dollar_bars.
#: calibrate_dollar_threshold_for_validation` usa internamente (lá,
#: `_CALIBRATION_TF`, privada ao módulo, não importável daqui) para que
#: `new_window_threshold_usdt` seja comparável ao `threshold_usdt` do
#: baseline: mesma fórmula, mesmo baseline de klines_1m, única variável
#: sendo a janela.
_BASELINE_TF: Final[str] = "15m"


@dataclass(frozen=True, slots=True)
class DollarBarDriftResult:
    """Resultado estruturado de UMA avaliação de deriva — mesmo padrão de
    `src.data.build_dollar_bars.DollarBarCalibration` (frozen, slots, sem
    dict solto). `drift_ratio` é sempre >= 1.0 por construção (razão entre
    o maior e o menor dos dois thresholds, símile de `vs_min_ratio`/
    `drift_ratio` já usados em `tools/diagnostics/measure_dollar_threshold_
    drift.py`) — captura a magnitude da deriva independente da direção
    (threshold subiu ou caiu)."""

    symbol: str
    resolution_id: str
    baseline_threshold_usdt: float
    baseline_window_start: str
    baseline_window_end: str
    new_window_start: str
    new_window_end: str
    new_window_threshold_usdt: float
    new_window_n_trades: int
    new_window_total_dollar: float
    drift_ratio: float
    alarm_threshold_ratio: float
    alarm_triggered: bool
    evaluated_at: str  # datetime.now(UTC).isoformat()


def evaluate_drift(
    baseline: DollarBarCalibration,
    *,
    new_window_start: str,
    new_window_end: str,
    new_window_n_trades: int,
    new_window_total_dollar: float,
    new_window_threshold_usdt: float,
    alarm_threshold_ratio: float | None = None,
) -> DollarBarDriftResult:
    """Função PURA (sem I/O) — compara `new_window_threshold_usdt` (já
    recalibrado, ver `measure_new_window_drift`) contra
    `baseline.threshold_usdt` e decide `alarm_triggered`. Recebe os totais
    já medidos como parâmetro em vez de medir sozinha — ver docstring do
    módulo (não é limitação de import, é separação deliberada entre
    medição/IO e decisão de alarme).

    `alarm_threshold_ratio=None` (default) lê `dollar_bar_drift_alarm_
    ratio_max` de `constants.yaml` — passar um valor explícito só serve
    para teste/override pontual, nunca para hardcodar o limiar de volta em
    código de chamador (Regra Zero).

    Regra do alarme: dispara (`alarm_triggered=True`) se `drift_ratio >
    alarm_threshold_ratio` — estritamente maior, não `>=`. No limiar exato
    (`drift_ratio == alarm_threshold_ratio`), o alarme NÃO dispara."""
    if baseline.threshold_usdt <= 0:
        raise ValueError(
            f"baseline.threshold_usdt precisa ser > 0, recebido "
            f"{baseline.threshold_usdt!r} ({baseline.symbol}/{baseline.resolution_id})"
        )
    if new_window_threshold_usdt <= 0:
        raise ValueError(
            f"new_window_threshold_usdt precisa ser > 0, recebido "
            f"{new_window_threshold_usdt!r} ({baseline.symbol}/{baseline.resolution_id}, "
            f"janela {new_window_start}..{new_window_end})"
        )

    resolved_alarm_ratio = (
        alarm_threshold_ratio
        if alarm_threshold_ratio is not None
        else float(load_constant("dollar_bar_drift_alarm_ratio_max"))
    )
    if resolved_alarm_ratio <= 1.0:
        raise ValueError(
            "dollar_bar_drift_alarm_ratio_max precisa ser > 1.0 (drift_ratio é sempre "
            f">= 1.0 por construção -- um limiar <= 1.0 dispararia sempre), recebido "
            f"{resolved_alarm_ratio!r}"
        )

    higher = max(new_window_threshold_usdt, baseline.threshold_usdt)
    lower = min(new_window_threshold_usdt, baseline.threshold_usdt)
    drift_ratio = higher / lower  # noqa: unguarded-ratio -- ambos > 0, guardado acima
    alarm_triggered = drift_ratio > resolved_alarm_ratio

    result = DollarBarDriftResult(
        symbol=baseline.symbol,
        resolution_id=baseline.resolution_id,
        baseline_threshold_usdt=baseline.threshold_usdt,
        baseline_window_start=baseline.calibration_window_start,
        baseline_window_end=baseline.calibration_window_end,
        new_window_start=new_window_start,
        new_window_end=new_window_end,
        new_window_threshold_usdt=new_window_threshold_usdt,
        new_window_n_trades=new_window_n_trades,
        new_window_total_dollar=new_window_total_dollar,
        drift_ratio=drift_ratio,
        alarm_threshold_ratio=resolved_alarm_ratio,
        alarm_triggered=alarm_triggered,
        evaluated_at=datetime.now(UTC).isoformat(),
    )
    logger.info(
        "monitoring.dollar_bar_drift.evaluated",
        symbol=result.symbol,
        resolution_id=result.resolution_id,
        baseline_threshold_usdt=result.baseline_threshold_usdt,
        new_window_threshold_usdt=result.new_window_threshold_usdt,
        drift_ratio=round(result.drift_ratio, 4),
        alarm_threshold_ratio=result.alarm_threshold_ratio,
        alarm_triggered=result.alarm_triggered,
    )
    return result


def measure_new_window_drift(
    baseline: DollarBarCalibration,
    new_window_start: str,
    new_window_end: str,
    *,
    alarm_threshold_ratio: float | None = None,
) -> DollarBarDriftResult:
    """Mede a janela nova via `src.data._chunked_scan` — MESMA fórmula de
    `src.data.build_dollar_bars.calibrate_dollar_threshold_for_validation`
    — e chama `evaluate_drift`. Único ponto deste módulo que toca I/O real
    (DuckDB/`aggTrades`/`klines_1m`); `evaluate_drift` continua pura. Reusa
    `_chunked_scan.date_chunks`/`scan_trades_totals`/`query_baseline`/
    `target_n_bars` diretamente em vez de chamar `calibrate_dollar_
    threshold_for_validation` — ver docstring do módulo (aquela função
    descarta `total_dollar`, este módulo precisa dele)."""
    chunk_days = int(load_constant("bars_streaming_chunk_days"))
    chunks = _chunked_scan.date_chunks(new_window_start, new_window_end, chunk_days=chunk_days)

    totals = _chunked_scan.scan_trades_totals(baseline.symbol, _BASELINE_TF, chunks)
    if totals.n_ticks == 0:
        raise ValueError(
            f"aggTrades vazio para {baseline.symbol} na janela nova "
            f"{new_window_start}..{new_window_end} -- não dá pra medir deriva sem trades"
        )

    baseline_klines = _chunked_scan.query_baseline(
        baseline.symbol, _BASELINE_TF, start=new_window_start, end=new_window_end
    )
    n_bars = _chunked_scan.target_n_bars(
        baseline.symbol,
        _BASELINE_TF,
        baseline_klines,
        start=new_window_start,
        end=new_window_end,
    )
    new_threshold = totals.total_dollar / n_bars  # noqa: unguarded-ratio -- target_n_bars levanta ValueError se <=0

    return evaluate_drift(
        baseline,
        new_window_start=new_window_start,
        new_window_end=new_window_end,
        new_window_n_trades=totals.n_ticks,
        new_window_total_dollar=totals.total_dollar,
        new_window_threshold_usdt=new_threshold,
        alarm_threshold_ratio=alarm_threshold_ratio,
    )


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Alarme de deriva de threshold_usdt de dollar bar (AG-042, Opção A' "
            "(threshold fixo + alarme de deriva), item 2/3 -- MECANISMO do alarme, "
            "não decide calibration_version/item 3). "
            "Compara um threshold_usdt CONGELADO (lido de _calibration.json, mesmo "
            "formato escrito por src.data.build_dollar_bars.write_dollar_bars_and_"
            "calibration) contra o threshold recalibrado numa janela NOVA. NÃO conecta "
            "a nenhum caller de produção/live -- invocação manual do operador."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--baseline-calibration-path",
        required=True,
        type=Path,
        help="caminho para _calibration.json (formato de "
        "write_dollar_bars_and_calibration) -- baseline congelado a comparar",
    )
    parser.add_argument("--new-window-start", required=True, help="ISO date, ex. 2026-07-01")
    parser.add_argument("--new-window-end", required=True, help="ISO date, ex. 2026-07-07")
    parser.add_argument(
        "--alarm-threshold-ratio",
        type=float,
        default=None,
        help="override de dollar_bar_drift_alarm_ratio_max (constants.yaml) -- "
        "default: lê do YAML",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_cli_args()
    payload: dict[str, Any] = orjson.loads(args.baseline_calibration_path.read_bytes())
    baseline = DollarBarCalibration(**payload)

    result = measure_new_window_drift(
        baseline,
        args.new_window_start,
        args.new_window_end,
        alarm_threshold_ratio=args.alarm_threshold_ratio,
    )

    logger.info(
        "monitoring.dollar_bar_drift.done",
        symbol=result.symbol,
        baseline_threshold_usdt=result.baseline_threshold_usdt,
        new_window_threshold_usdt=result.new_window_threshold_usdt,
        drift_ratio=round(result.drift_ratio, 4),
        alarm_threshold_ratio=result.alarm_threshold_ratio,
        alarm_triggered=result.alarm_triggered,
    )


if __name__ == "__main__":
    main()
