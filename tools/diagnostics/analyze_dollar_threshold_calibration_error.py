"""Calcula o erro de calibração de threshold dollar-bar (volume real do
PERÍODO AVALIADO ÷ taxa implícita calibrada pela JANELA TRAILING anterior)
a partir de um relatório de deriva contínuo (mensal OU semanal) -- mesma
lógica usada pra produzir os achados já registrados em `AG-124`
(`audit/architecture_gaps_log.yaml`, resolution: "erro de calibração...
PIORA MONOTONICAMENTE com janela mais longa... XRPUSDT vai de 17,9%...
pra 41,7%"), que na rodada mensal foi calculada ad-hoc (sem script
reusável) -- este script formaliza a mesma metodologia, reusável tanto
pra revalidar o achado mensal quanto pra rodar a extensão semanal
pedida pelo Manager (AG-124, "teste Semanal").

**Metodologia -- reconstruída por engenharia reversa contra os 2 números
já publicados em `AG-124`, não inventada (ver "Validação" abaixo).**
`calibrate_dollar_threshold_for_validation`
(`src/data/build_dollar_bars.py:214-268`) calibra `threshold_usdt =
total_dollar / target_n_bars`, onde `target_n_bars` vem da contagem real
de barras de 1 minuto (`klines_1m`) no período -- aproximadamente
proporcional ao Nº DE DIAS do período (mesmo baseline de barras/dia ao
longo do tempo). Isso cancela nos dois lados de uma razão entre janelas,
então o erro de calibração pode ser medido inteiramente a partir de
`dollar_per_day` (já presente nos relatórios de deriva mensal/semanal),
sem reconstruir `klines_1m`/`target_n_bars` de novo:

    error_ratio = dollar_per_day(período avaliado) /
                  dollar_per_day_pooled(bloco de calibração)

**Janela = CADÊNCIA (`cadence_days == trailing_window_days`, mesmo par
sugerido em `AG-124`: "trailing_window_days=30, cadence_days=30"), não
"lookback rolante recalibrado a cada período".** Os períodos são
particionados em BLOCOS não sobrepostos de tamanho `window`: o bloco
`[i, i+window)` calibra (pooled: soma `total_dollar` / soma `n_days` dos
`window` períodos), e essa MESMA taxa é aplicada a TODO período do bloco
seguinte `[i+window, i+2*window)` -- sem recalibrar dentro do bloco
aplicado, exatamente como `build_dollar_bars_walkforward` mantém 1
threshold fixo por `cadence_days` inteiro antes de recalibrar. Só blocos
de aplicação COMPLETOS (exatamente `window` períodos) entram na
contagem -- o remanescente final incompleto (quando o histórico não é
múltiplo exato de `window`) é descartado, não contado como erro nem como
acerto (1ª tentativa, contando o remanescente, deu XRPUSDT W=6 =
43,14%; só descartando o remanescente bateu EXATO com o 41,67%
publicado -- ver "Validação").

Um período conta como "erro ≥2x/≤0,5x" se `error_ratio >= 2.0` ou
`error_ratio <= 0.5` -- mesmo critério citado em `AG-124`.

**Validação (feita, não só recomendada) -- reproduzido EXATO contra os 2
números já publicados em `AG-124`** rodando contra
`dollar_threshold_drift_monthly.json`: XRPUSDT W=1 -> 17,86% (publicado:
"17,9%"), XRPUSDT W=6 -> 41,67% (publicado: "41,7%", bate na 2ª casa
decimal). W=1 bate tanto com esta metodologia (blocos) quanto com uma
metodologia mais simples de janela rolante recalibrada todo período
(que foi a 1ª tentativa, descartada) -- só W=6 desambiguou qual das
duas o relatório original usou: a rolante deu 25,49% (não bate), a de
blocos deu 41,67% (bate exato após descartar o remanescente). Antes de
tratar números novos (semanal) como confiáveis, rodar de novo contra o
mensal com `--windows 1 6` e conferir que os 2 valores acima continuam
batendo -- se o script mudar no futuro e a validação quebrar, é sinal de
regressão na metodologia, não só um refactor cosmético.

Rodar:
    uv run python tools/diagnostics/analyze_dollar_threshold_calibration_error.py \
        --report experiments/dollar_threshold_drift_monthly.json --windows 1 2 3 6
    uv run python tools/diagnostics/analyze_dollar_threshold_calibration_error.py \
        --report experiments/dollar_threshold_drift_weekly.json --windows 1 2 4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import orjson
import structlog

from src.core.provenance import report_provenance

logger = structlog.get_logger(__name__)

_ERROR_HIGH_MULT: Final[float] = 2.0
_ERROR_LOW_MULT: Final[float] = 0.5


def _load_rows(report_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Agrupa `results` do relatório por símbolo, ordenado cronologicamente
    (`start`) -- pré-condição de todo o resto: a ordem de `results` no JSON
    já é cronológica por construção (checkpoint incremental processa em
    ordem), mas ordena de novo aqui em vez de assumir, porque o relatório
    pode ter sido gerado por resume/checkpoint fora de ordem em algum
    cenário de borda."""
    payload = orjson.loads(report_path.read_bytes())
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in payload["results"]:
        by_symbol.setdefault(row["symbol"], []).append(row)
    for _symbol, rows in by_symbol.items():
        rows.sort(key=lambda r: r["start"])
    return by_symbol


def _calibration_errors_for_window(rows: list[dict[str, Any]], window: int) -> list[float]:
    """`error_ratio` de todo período dentro de um bloco de aplicação
    COMPLETO (ver docstring do módulo -- blocos não sobrepostos de
    `window` períodos: `[i, i+window)` calibra, `[i+window, i+2*window)`
    aplica a MESMA taxa sem recalibrar dentro do bloco, `cadence ==
    window`, mesmo par que `build_dollar_bars_walkforward` usa
    `trailing_window_days`/`cadence_days`). O bloco de aplicação final,
    se incompleto (histórico não múltiplo exato de `window`), é
    DESCARTADO -- confirmado pela validação contra AG-124 (ver docstring
    do módulo): contá-lo produz XRPUSDT W=6=43,14% (não bate com o
    41,7% publicado); descartá-lo produz 41,67% (bate)."""
    ratios: list[float] = []
    n = len(rows)
    block_start = 0
    while block_start + 2 * window <= n:
        calib_block = rows[block_start : block_start + window]
        apply_block = rows[block_start + window : block_start + 2 * window]
        calib_dollar = sum(r["total_dollar"] for r in calib_block)
        calib_days = sum(r["n_days"] for r in calib_block)
        if calib_days <= 0:
            continue  # pragma: no cover -- n_days sempre >=1 por construção do relatório
        calib_rate = calib_dollar / calib_days
        if calib_rate <= 0:
            # pragma: no cover -- total_dollar sempre >0 (aggTrades não-vazio no relatório)
            continue
        for r in apply_block:
            ratios.append(r["dollar_per_day"] / calib_rate)
        block_start += window
    return ratios


def _summarize(ratios: list[float]) -> dict[str, Any]:
    n = len(ratios)
    if n == 0:
        return {
            "n_periods_evaluated": 0,
            "pct_error_ge2x_or_le0_5x": None,
            "max_ratio": None,
            "min_ratio": None,
        }
    n_bad = sum(1 for r in ratios if r >= _ERROR_HIGH_MULT or r <= _ERROR_LOW_MULT)
    return {
        "n_periods_evaluated": n,
        "n_error_ge2x_or_le0_5x": n_bad,
        "pct_error_ge2x_or_le0_5x": round(100.0 * n_bad / n, 2),  # noqa: magic-number -- fração->%
        "max_ratio": round(max(ratios), 4),
        "min_ratio": round(min(ratios), 4),
    }


def analyze(report_path: Path, windows: list[int]) -> dict[str, Any]:
    by_symbol = _load_rows(report_path)
    table: dict[str, dict[str, Any]] = {}
    for symbol, rows in sorted(by_symbol.items()):
        table[symbol] = {}
        for window in windows:
            ratios = _calibration_errors_for_window(rows, window)
            summary = _summarize(ratios)
            table[symbol][str(window)] = summary
            logger.info(
                "diagnostics.analyze_dollar_threshold_calibration_error.symbol_window_done",
                symbol=symbol,
                window=window,
                **summary,
            )
    return {
        **report_provenance(),
        "source_report": str(report_path),
        "windows_periods": windows,
        "error_thresholds": {"high_mult": _ERROR_HIGH_MULT, "low_mult": _ERROR_LOW_MULT},
        "methodology": (
            "error_ratio = dollar_per_day(período avaliado) / "
            "dollar_per_day_pooled(janela trailing de W períodos imediatamente "
            "anteriores) -- ver docstring do módulo pra por que dollar_per_day "
            "sozinho é equivalente à razão de threshold_usdt real. Período conta "
            "como erro ruim se error_ratio >= 2.0 ou <= 0.5."
        ),
        "table": table,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, required=True, help="Caminho do relatório de deriva (mensal/semanal)"
    )
    parser.add_argument(
        "--windows",
        type=int,
        nargs="+",
        required=True,
        help="Janelas trailing em Nº DE PERÍODOS do relatório",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Se informado, grava o resultado em JSON aqui"
    )
    args = parser.parse_args()

    result = analyze(args.report, args.windows)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
        logger.info(
            "diagnostics.analyze_dollar_threshold_calibration_error.written", out=str(args.out)
        )

    # Tabela legível direto no stdout -- DoD "output autoexplicativo" (CLAUDE.md).
    # B28 -- print() banido em src/, mas este é tools/diagnostics/ (CLI de
    # investigação, não pipeline de produção); usa structlog mesmo assim,
    # por consistência com o resto do módulo.
    logger.info(
        "diagnostics.analyze_dollar_threshold_calibration_error.summary",
        report=str(args.report),
        windows=args.windows,
        table=result["table"],
    )


if __name__ == "__main__":
    main()
