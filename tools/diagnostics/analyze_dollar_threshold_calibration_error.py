"""Calcula o erro de calibração de threshold dollar-bar (volume real do
PERÍODO AVALIADO ÷ taxa implícita calibrada pela JANELA TRAILING anterior)
a partir de um relatório de deriva contínuo (mensal OU semanal OU diário)
-- mesma lógica usada pra produzir os achados já registrados em `AG-124`
(`audit/architecture_gaps_log.yaml`, resolution: "erro de calibração...
PIORA MONOTONICAMENTE com janela mais longa... XRPUSDT vai de 17,9%...
pra 41,7%"), que na rodada mensal foi calculada ad-hoc (sem script
reusável) -- este script formaliza a mesma metodologia, reusável tanto
pra revalidar o achado mensal quanto pra rodar as extensões semanal/diária
pedidas pelo Manager (AG-124, "teste Semanal"/"quero Diario").

**Metodologia -- reconstruída por engenharia reversa contra os 2 números
já publicados em `AG-124`, não inventada (ver "Validação" abaixo).**
`calibrate_dollar_threshold_for_validation`
(`src/data/build_dollar_bars.py:214-268`) calibra `threshold_usdt =
total_dollar / target_n_bars`, onde `target_n_bars` vem da contagem real
de barras de 1 minuto (`klines_1m`) no período -- aproximadamente
proporcional ao Nº DE DIAS do período (mesmo baseline de barras/dia ao
longo do tempo). Isso cancela nos dois lados de uma razão entre janelas,
então o erro de calibração pode ser medido inteiramente a partir de
`dollar_per_day` (já presente nos relatórios de deriva mensal/semanal/
diário), sem reconstruir `klines_1m`/`target_n_bars` de novo:

    error_ratio = dollar_per_day(período avaliado) /
                  dollar_per_day_pooled(bloco de calibração)

**Janela de calibração (`trailing`) e cadência de aplicação (`cadence`)
são parâmetros SEPARADOS** (`--trailing`/`--cadence` no CLI) -- o caso
`cadence == trailing` (default quando `--cadence` é omitido) é o par
original sugerido em `AG-124` ("trailing_window_days=30,
cadence_days=30") e o único medido até a auditoria externa de
2026-08-21 apontar (parecer, §4 pergunta 2) que os dois nunca tinham
sido desacoplados -- ver `AG-136`/`docs/plano_acao_ag124_pos_auditoria_
2026-08-21.md` item 8/9.

Os períodos são particionados em blocos: pra cada posição `i`, o bloco
`[i, i+trailing)` calibra (pooled: soma `total_dollar` / soma `n_days`
dos `trailing` períodos), e essa MESMA taxa é aplicada a TODO período do
bloco seguinte `[i+trailing, i+trailing+cadence)` -- sem recalibrar
dentro do bloco aplicado. **Isto é um esquema ROLLING, não "calibra-
aplica-pula"**: a iteração seguinte começa em `i+cadence` (não
`i+trailing+cadence`), então quando `cadence < trailing` o bloco de
calibração da iteração seguinte REUSA parte do bloco de calibração
anterior, e quando `cadence == trailing` o bloco de APLICAÇÃO de uma
iteração vira inteiramente o bloco de CALIBRAÇÃO da iteração seguinte --
exatamente como `build_dollar_bars_walkforward` recalibra cada período
usando os `trailing_window_days` estritamente anteriores, avançando
`cadence_days` por vez. (Achado de auditoria externa 2026-08-21,
pergunta 9 do desenvolvedor: uma versão anterior desta docstring descrevia
o mecanismo como um par fixo que "calibra, aplica, e pula" -- o CÓDIGO
sempre foi rolling; só a prosa estava imprecisa.) Só blocos de aplicação
COMPLETOS (exatamente `cadence` períodos) entram na contagem -- o
remanescente final incompleto (quando o histórico não é múltiplo exato)
é descartado, não contado como erro nem como acerto (1ª tentativa,
contando o remanescente, deu XRPUSDT W=6 = 43,14%; só descartando o
remanescente bateu EXATO com o 41,67% publicado -- ver "Validação").

Um período conta como "erro ruim" se `error_ratio >= high_mult` ou
`error_ratio <= low_mult` -- default `2.0`/`0.5` (mesmo critério citado
em `AG-124`), parametrizável via `--high-mult`/`--low-mult` pra sweep de
sensibilidade do próprio corte (achado de auditoria externa 2026-08-21,
parecer §2.1: o corte 2x/0,5x nunca foi testado contra vizinhos).

**Validação (feita, não só recomendada) -- reproduzido EXATO contra os 2
números já publicados em `AG-124`** rodando contra
`dollar_threshold_drift_monthly.json` com `--trailing 1` e `--trailing 6`
(sem `--cadence`, ou seja `cadence == trailing`): XRPUSDT W=1 -> 17,86%
(publicado: "17,9%"), XRPUSDT W=6 -> 41,67% (publicado: "41,7%", bate na
2ª casa decimal). W=1 bate tanto com esta metodologia (blocos) quanto com
uma metodologia mais simples de janela rolante recalibrada todo período
(que foi a 1ª tentativa, descartada) -- só W=6 desambiguou qual das duas
o relatório original usou: a rolante deu 25,49% (não bate), a de blocos
deu 41,67% (bate exato após descartar o remanescente). Antes de tratar
números novos como confiáveis, rodar de novo contra o mensal com
`--trailing 1 6` e conferir que os 2 valores acima continuam batendo --
se o script mudar no futuro e a validação quebrar, é sinal de regressão
na metodologia, não só um refactor cosmético.

**Modo alternativo -- calibração casada por dia-da-semana
(`--weekday-matched-weeks`).** `trailing`/`cadence` em BLOCO DE DIAS
CORRIDOS (acima) só é livre de aliasing quando `trailing` é múltiplo de 7
(garante 1 ocorrência de cada dia-da-semana por bloco) -- um `trailing=3`
corrido, por exemplo, MISTURA dias-da-semana de forma não-controlada e
não testa a hipótese "dá pra usar menos histórico se ele for
seletivamente casado por dia-da-semana" (achado de auditoria externa
2026-08-21, correção do Manager sobre o próprio brainstorming: `trailing=
3,cadence=1` em bloco corrido não fazia sentido matemático pra essa
pergunta). Este modo ataca a sazonalidade DIRETO: pra cada dia aplicado
`d`, calibra usando as `n_weeks` ocorrências mais recentes do MESMO
dia-da-semana (`d - 7`, `d - 14`, ..., `d - 7*n_weeks`) -- estruturalmente
livre de aliasing por CONSTRUÇÃO (todo ponto de calibração compartilha o
dia-da-semana do dia aplicado), não por coincidência de tamanho de bloco.
`n_weeks=3` usa só 3 pontos de dado reais (não um bloco de 21 dias
corridos) e recalibra a cada dia por construção (não há `cadence`
separado -- cada dia tem seu próprio conjunto de defasagens). Dia sem as
`n_weeks` ocorrências completas (gap no relatório, início de série) é
DESCARTADO, nunca interpolado/parcial -- mesma disciplina do modo em
bloco (`calib_days <= 0`).

Rodar:
    uv run python tools/diagnostics/analyze_dollar_threshold_calibration_error.py \
        --report experiments/dollar_threshold_drift_monthly.json --trailing 1 2 3 6
    uv run python tools/diagnostics/analyze_dollar_threshold_calibration_error.py \
        --report experiments/dollar_threshold_drift_daily.json --trailing 5 6 8 9 13 15
    uv run python tools/diagnostics/analyze_dollar_threshold_calibration_error.py \
        --report experiments/dollar_threshold_drift_daily.json --trailing 7 --cadence 1
    uv run python tools/diagnostics/analyze_dollar_threshold_calibration_error.py \
        --report experiments/dollar_threshold_drift_daily.json --trailing 1 2 4 7 \
        --high-mult 1.7 --low-mult 0.6
    uv run python tools/diagnostics/analyze_dollar_threshold_calibration_error.py \
        --report experiments/dollar_threshold_drift_daily.json --trailing 7 \
        --weekday-matched-weeks 3
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
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


def _calibration_errors_for_window(
    rows: list[dict[str, Any]], *, trailing: int, cadence: int | None = None
) -> list[float]:
    """`error_ratio` de todo período dentro de um bloco de aplicação
    COMPLETO (ver docstring do módulo pro esquema ROLLING completo).
    `calib_block = rows[i : i+trailing]` calibra, `apply_block =
    rows[i+trailing : i+trailing+cadence]` aplica a MESMA taxa sem
    recalibrar dentro do bloco, e a iteração seguinte começa em
    `i+cadence` -- quando `cadence is None` (default), `cadence =
    trailing`, reduzindo exatamente ao comportamento original
    (`block_start += window`, bloco de aplicação inteiro vira bloco de
    calibração da iteração seguinte). O bloco de aplicação final, se
    incompleto, é DESCARTADO -- confirmado pela validação contra AG-124
    (ver docstring do módulo): contá-lo produz XRPUSDT W=6=43,14% (não
    bate com o 41,7% publicado); descartá-lo produz 41,67% (bate)."""
    if cadence is None:
        cadence = trailing
    ratios: list[float] = []
    n = len(rows)
    block_start = 0
    while block_start + trailing + cadence <= n:
        calib_block = rows[block_start : block_start + trailing]
        apply_block = rows[block_start + trailing : block_start + trailing + cadence]
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
        block_start += cadence
    return ratios


def _calibration_errors_weekday_matched(
    rows: list[dict[str, Any]], *, n_weeks: int
) -> list[float]:
    """Calibração alternativa a `_calibration_errors_for_window`: em vez
    de um bloco contíguo de dias corridos, usa as `n_weeks` ocorrências
    mais recentes do MESMO dia-da-semana do dia aplicado (defasagem de
    7, 14, ..., 7*n_weeks dias) -- ver docstring do módulo pro porquê.
    Recalibra a cada dia aplicado por construção (cada dia tem seu
    próprio conjunto de defasagens semanais) -- não há `cadence`
    separado aqui. Dia sem as `n_weeks` ocorrências completas (gap de
    dado, início de série) é DESCARTADO -- nunca interpolado."""
    by_date: dict[date, dict[str, Any]] = {date.fromisoformat(r["start"]): r for r in rows}

    ratios: list[float] = []
    for r in rows:
        target_date = date.fromisoformat(r["start"])
        calib_samples: list[dict[str, Any]] = []
        is_complete = True
        for k in range(1, n_weeks + 1):
            sample = by_date.get(target_date - timedelta(days=7 * k))
            if sample is None:
                is_complete = False
                break
            calib_samples.append(sample)
        if not is_complete:
            continue
        calib_dollar = sum(s["total_dollar"] for s in calib_samples)
        calib_days = sum(s["n_days"] for s in calib_samples)
        if calib_days <= 0:
            continue  # pragma: no cover -- n_days sempre >=1 por construção do relatório
        calib_rate = calib_dollar / calib_days
        if calib_rate <= 0:
            continue  # pragma: no cover -- total_dollar sempre >0 (aggTrades não-vazio)
        ratios.append(r["dollar_per_day"] / calib_rate)
    return ratios


def _summarize(
    ratios: list[float], *, high_mult: float = _ERROR_HIGH_MULT, low_mult: float = _ERROR_LOW_MULT
) -> dict[str, Any]:
    n = len(ratios)
    if n == 0:
        return {
            "n_periods_evaluated": 0,
            "pct_error_bad": None,
            "max_ratio": None,
            "min_ratio": None,
        }
    n_bad = sum(1 for r in ratios if r >= high_mult or r <= low_mult)
    return {
        "n_periods_evaluated": n,
        "n_error_bad": n_bad,
        "pct_error_bad": round(100.0 * n_bad / n, 2),  # noqa: magic-number -- fração->%
        "max_ratio": round(max(ratios), 4),
        "min_ratio": round(min(ratios), 4),
    }


def analyze(
    report_path: Path,
    windows: list[int],
    *,
    cadence: int | None = None,
    high_mult: float = _ERROR_HIGH_MULT,
    low_mult: float = _ERROR_LOW_MULT,
    weekday_matched_weeks: list[int] | None = None,
) -> dict[str, Any]:
    """`windows` é a lista de `trailing` testados em modo BLOCO (pode ser
    vazia se só `weekday_matched_weeks` for usado). `cadence`, quando
    informado, aplica o MESMO valor a todos os `windows` (uso típico:
    `windows=[7]`, `cadence=1`, pra medir T=7/C=1) -- quando `None`
    (default), cada `trailing` usa `cadence == trailing` (comportamento
    original, preservado bit-a-bit). `weekday_matched_weeks`, quando
    informado, roda ADICIONALMENTE o modo casado por dia-da-semana (ver
    docstring do módulo) pra cada `n_weeks` da lista, com chave de tabela
    `"wm<n_weeks>"` (distinta das chaves numéricas do modo bloco)."""
    by_symbol = _load_rows(report_path)
    table: dict[str, dict[str, Any]] = {}
    for symbol, rows in sorted(by_symbol.items()):
        table[symbol] = {}
        for window in windows:
            ratios = _calibration_errors_for_window(rows, trailing=window, cadence=cadence)
            summary = _summarize(ratios, high_mult=high_mult, low_mult=low_mult)
            table[symbol][str(window)] = summary
            logger.info(
                "diagnostics.analyze_dollar_threshold_calibration_error.symbol_window_done",
                symbol=symbol,
                trailing=window,
                cadence=window if cadence is None else cadence,
                **summary,
            )
        for n_weeks in weekday_matched_weeks or []:
            ratios = _calibration_errors_weekday_matched(rows, n_weeks=n_weeks)
            summary = _summarize(ratios, high_mult=high_mult, low_mult=low_mult)
            key = f"wm{n_weeks}"
            table[symbol][key] = summary
            logger.info(
                "diagnostics.analyze_dollar_threshold_calibration_error.symbol_weekday_matched_done",
                symbol=symbol,
                n_weeks=n_weeks,
                **summary,
            )
    return {
        **report_provenance(),
        "source_report": str(report_path),
        "trailing_windows_periods": windows,
        "cadence_override_periods": cadence,
        "weekday_matched_weeks": weekday_matched_weeks,
        "error_thresholds": {"high_mult": high_mult, "low_mult": low_mult},
        "methodology": (
            "error_ratio = dollar_per_day(período avaliado) / "
            "dollar_per_day_pooled(janela trailing de `trailing` períodos "
            "imediatamente anteriores) -- esquema ROLLING, cadência de "
            "avanço = `cadence` (default = trailing). Chaves `wm<n>` usam "
            "o modo casado por dia-da-semana (ver docstring do módulo). "
            "Ver docstring do módulo pra por que dollar_per_day sozinho é "
            "equivalente à razão de threshold_usdt real. Período conta "
            "como erro ruim se error_ratio >= high_mult ou <= low_mult."
        ),
        "table": table,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Caminho do relatório de deriva (mensal/semanal/diário)",
    )
    parser.add_argument(
        "--trailing",
        type=int,
        nargs="+",
        default=[],
        help="Janelas de calibração (trailing) em bloco corrido -- 1 valor testado por entrada",
    )
    parser.add_argument(
        "--cadence",
        type=int,
        default=None,
        help="Cadência de aplicação em Nº DE PERÍODOS -- default: igual a cada --trailing",
    )
    parser.add_argument(
        "--weekday-matched-weeks",
        type=int,
        nargs="+",
        default=None,
        help="Modo casado por dia-da-semana: nº de ocorrências do mesmo dia (ver docstring)",
    )
    parser.add_argument(
        "--high-mult",
        type=float,
        default=_ERROR_HIGH_MULT,
        help="Corte superior de erro ruim (default 2.0)",
    )
    parser.add_argument(
        "--low-mult",
        type=float,
        default=_ERROR_LOW_MULT,
        help="Corte inferior de erro ruim (default 0.5)",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Se informado, grava o resultado em JSON aqui"
    )
    args = parser.parse_args()
    if not args.trailing and not args.weekday_matched_weeks:
        parser.error("informe pelo menos um de --trailing ou --weekday-matched-weeks")

    result = analyze(
        args.report,
        args.trailing,
        cadence=args.cadence,
        high_mult=args.high_mult,
        low_mult=args.low_mult,
        weekday_matched_weeks=args.weekday_matched_weeks,
    )

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
        trailing=args.trailing,
        cadence=args.cadence,
        weekday_matched_weeks=args.weekday_matched_weeks,
        high_mult=args.high_mult,
        low_mult=args.low_mult,
        table=result["table"],
    )


if __name__ == "__main__":
    main()
