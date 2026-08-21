"""Comparação final -- Condição A (λ=0,002 fixo, status quo) vs Condição B
(λ calibrado POR ATIVO) do experimento de transferibilidade de
`m4_jump_model_penalty` (AG-087, `audit/architecture_gaps_log.yaml`).
Item 4 autorizado pelo Manager, 2026-08-20.

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar DEPOIS de `tools/diagnostics/calibrate_
jump_model_penalty_per_asset.py` (item 2) e de decidir os 4 valores de λ
a partir da tabela impressa por ele -- este script NUNCA inventa esses
valores (B20):

    uv run python -c "
    from tools.diagnostics.compare_jump_model_lambda_transferability import (
        run_transferability_comparison_and_diff,
    )
    run_transferability_comparison_and_diff(
        jump_penalty_by_symbol={
            'ETHUSDT': <valor medido por calibrate_jump_model_penalty_per_asset.py>,
            'SOLUSDT': <valor medido>,
            'BNBUSDT': <valor medido>,
            'XRPUSDT': <valor medido>,
        }
    )
    "

**NÃO RODE a rodada real das 3 resoluções (~3h, mesma ordem de grandeza
do harness completo por célula) sem autorização explícita do Manager --
mesma disciplina de `run_and_save_m4_report`/`run_and_save_critical_
windows_report`.**

**Desenho do experimento** (contexto completo em `audit/architecture_
gaps_log.yaml::AG-087`). Condição A (status quo): λ=0,002 fixo aplicado
aos 5 símbolos -- já rodado, dado já existe em `experiments/m4_critical_
windows_report.json`, custo zero (só lido daqui pra este diff, nunca
recomputado). Condição B (nova): λ calibrado INDEPENDENTEMENTE por ativo
(ETH/SOL/BNB/XRP -- BTC não entra, já é seu próprio "λ local"), gerada
por `src.analysis.m4_critical_windows.run_jump_model_transferability_
comparison` (baseline + Jump Model só, ~4-6x mais barato que o harness
completo de 6 candidatos -- HMM/BOCPD não mudam com `jump_penalty`).

**Métrica de decisão** (`is_saturated`/`saturation_rate`,
`SymbolCandidateDetail`/`AggregatedCandidateResult`, AG-087) --
desqualifica se a saturação persistir comparável à Condição A mesmo com
λ próprio; mantém λ por ativo se a saturação cair perto de zero.
`persistence_median_duration_bars` entra como leitura complementar (não
critério sozinho -- duração extrema já é esperada mesmo no caso
"saudável", ver `AG-087`/`constants.yaml::m4_jump_model_penalty.source`).

**Secundária/corroborante:** `i_squared_pct`/`p_value_permutation` de
`VolatilityHeterogeneitySymbolDetail` (AG-114, "trabalho desta mesma
sessão"). **Achado real, não hipotético** (checado em runtime dentro de
`run_transferability_comparison_and_diff` via `a_resolution.get(
"volatility_heterogeneity")`, nunca assumido): o `experiments/
m4_critical_windows_report.json` atual (Condição A) foi gerado ANTES da
extensão AG-114 entrar nas dataclasses de `m4_critical_windows.py` --
não tem as chaves `volatility_heterogeneity`/`gate_quality` (confirmado
por grep direto no JSON persistido, 2026-08-20, zero ocorrências das 2
chaves). Este script NUNCA inventa o número que falta: quando a Condição
A não tem `volatility_heterogeneity`, o diff de `i_squared_pct_median`
fica `NaN` do lado A (só o valor B é reportado, informativo, sem
baseline pra comparar) -- logado explicitamente, nunca escondido.

NÃO usa o framework de gate-quality (occupancy/transition-failure/
detection-delay) como critério -- pergunta diferente, limiares ainda
TBD (mesma decisão documentada na task que autorizou este experimento).
`gate_quality` pode aparecer no relatório B (efeito colateral de reusar
`aggregate_critical_windows_results` sem modificação -- ver docstring de
`run_jump_model_transferability_comparison`), mas este script nunca o lê."""

from __future__ import annotations

import math
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import orjson
import structlog

from src.analysis import m4_critical_windows as mcw

logger = structlog.get_logger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_CONDICAO_A_PATH: Final[Path] = _REPO_ROOT / "experiments" / "m4_critical_windows_report.json"
_CONDICAO_B_REPORT_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "m4_jump_model_lambda_transferability_report.json"
)
_VERDICT_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "m4_jump_model_lambda_transferability_verdict.json"
)

_JUMP_CLASSIFIER_ID: Final[str] = "jump_model_cjm_v1"
_RESOLUTIONS: Final[tuple[str, ...]] = mcw.RESOLUTIONS
_SYMBOLS: Final[tuple[str, ...]] = mcw.JUMP_TRANSFERABILITY_SYMBOLS

# Leitura QUALITATIVA pro Manager decidir -- NÃO é um gate formal (B20:
# nenhum threshold aqui decide sozinho se o λ por ativo "passa"). "Perto
# de zero"/"comparável à Condição A" são rótulos de leitura só pra
# facilitar a varredura da tabela completa -- todos os números brutos
# ficam no JSON persistido, nunca escondidos atrás do rótulo qualitativo.
_SATURATION_NEAR_ZERO_MAX: Final[float] = 0.05  # noqa: magic-number
_SATURATION_COMPARABLE_TO_A_TOLERANCE: Final[float] = 0.10  # noqa: magic-number


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
    logger.info("compare_jump_model_lambda_transferability.report_written", path=str(dest_path))


def _load_condicao_a() -> dict[str, Any]:
    if not _CONDICAO_A_PATH.exists():
        raise FileNotFoundError(
            f"compare_jump_model_lambda_transferability: Condição A ausente em "
            f"{_CONDICAO_A_PATH} -- rode run_and_save_critical_windows_report primeiro "
            "(fora do escopo deste script/experimento)"
        )
    with _CONDICAO_A_PATH.open("rb") as fh:
        data: dict[str, Any] = orjson.loads(fh.read())
    return data


def _find_resolution(report: dict[str, Any], resolution_id: str) -> dict[str, Any] | None:
    by_resolution: list[dict[str, Any]] = report.get("by_resolution", [])
    for r in by_resolution:
        if r.get("resolution_id") == resolution_id:
            return r
    return None


def _find_candidate(resolution_report: dict[str, Any], classifier_id: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = resolution_report.get("candidates", [])
    for c in candidates:
        if c.get("classifier_id") == classifier_id:
            return c
    return None


def _find_volatility_heterogeneity(
    resolution_report: dict[str, Any], classifier_id: str
) -> dict[str, Any] | None:
    vol_het_list: list[dict[str, Any]] = resolution_report.get("volatility_heterogeneity", []) or []
    for v in vol_het_list:
        if v.get("classifier_id") == classifier_id:
            return v
    return None


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _median(values: list[float]) -> float:
    finite = sorted(v for v in values if not _is_nan(v))
    n = len(finite)
    if n == 0:
        return float("nan")
    mid = n // 2
    if n % 2 == 1:
        return finite[mid]
    return (finite[mid - 1] + finite[mid]) / 2.0


def _per_symbol_saturation_and_persistence(
    candidate: dict[str, Any], symbol: str
) -> dict[str, float | int]:
    """Perfura `per_window[].per_symbol[]` (`SymbolCandidateDetail`, já
    serializado por `dataclasses.asdict`) pra extrair a fatia de UM
    símbolo -- `AggregatedCandidateResult.saturation_rate`/`persistence_
    median_duration_bars_median` são agregados sobre TODOS os símbolos/
    janelas (mediana-de-medianas), não quebrados por símbolo. Este helper
    faz o corte "por (símbolo, resolução)" que a task pede e que não
    existe pronto em nenhum dataclass -- sem reimplementar nenhuma
    fórmula de agregação nova (mediana simples sobre as poucas janelas em
    que o símbolo aparece, mesma definição de `_median_or_nan`)."""
    durations: list[float] = []
    n_windows_ok = 0
    n_windows_saturated = 0
    for window in candidate.get("per_window", []):
        for detail in window.get("per_symbol", []):
            if detail.get("symbol") != symbol:
                continue
            n_windows_ok += 1
            if detail.get("is_saturated"):
                n_windows_saturated += 1
            duration = detail.get("persistence_median_duration_bars")
            if duration is not None and not _is_nan(duration):
                durations.append(float(duration))
    saturation_rate = (
        n_windows_saturated / n_windows_ok  # noqa: unguarded-ratio -- guardado por n_windows_ok>0 abaixo
        if n_windows_ok > 0
        else float("nan")
    )
    return {
        "n_windows_ok": n_windows_ok,
        "n_windows_saturated": n_windows_saturated,
        "saturation_rate": saturation_rate,
        "persistence_median_duration_bars_median": _median(durations),
    }


def _per_symbol_i_squared(
    resolution_report: dict[str, Any], classifier_id: str, symbol: str
) -> float:
    """Mesmo corte por símbolo que `_per_symbol_saturation_and_persistence`,
    mas em `volatility_heterogeneity[].per_window[].per_symbol[]`
    (`VolatilityHeterogeneitySymbolDetail.i_squared_pct`, AG-114) --
    `NaN` se o campo não existir no relatório (Condição A pré-AG-114, ver
    docstring do módulo) ou se o símbolo nunca aparecer com `n_buckets>0`."""
    vol_het = _find_volatility_heterogeneity(resolution_report, classifier_id)
    if vol_het is None:
        return float("nan")
    values: list[float] = []
    for window in vol_het.get("per_window", []):
        for detail in window.get("per_symbol", []):
            if detail.get("symbol") != symbol:
                continue
            if int(detail.get("n_buckets", 0)) <= 0:
                continue
            i2 = detail.get("i_squared_pct")
            if i2 is not None and not _is_nan(i2):
                values.append(float(i2))
    return _median(values)


def _verdict(saturation_a: float, saturation_b: float) -> str:
    if _is_nan(saturation_b):
        return "sem_dado_condicao_b"
    if saturation_b <= _SATURATION_NEAR_ZERO_MAX:
        return "mantem_lambda_por_ativo -- saturacao caiu perto de zero"
    if not _is_nan(saturation_a) and abs(saturation_b - saturation_a) <= (
        _SATURATION_COMPARABLE_TO_A_TOLERANCE
    ):
        return "desqualifica -- saturacao comparavel a condicao A mesmo com lambda proprio"
    return "inconclusivo -- saturacao caiu mas nao perto de zero, ver tabela completa"


def run_transferability_comparison_and_diff(
    *,
    jump_penalty_by_symbol: dict[str, float],
    resolutions: tuple[str, ...] = _RESOLUTIONS,
    jump_n_states: int = 2,
    jump_seed: int = 0,
    max_workers: int | None = None,
) -> Path:
    """Gera a Condição B (`mcw.run_jump_model_transferability_comparison`
    por resolução, `jump_penalty_by_symbol` obrigatório -- `ValueError` se
    faltar algum dos 4 ativos, nunca inventado), persiste como JSON
    (`_CONDICAO_B_REPORT_PATH`), carrega a Condição A já existente do
    disco (`experiments/m4_critical_windows_report.json`, custo zero) e
    produz o diff por `(símbolo, resolução)` -- `saturation_rate`
    (critério primário, AG-087), `persistence_median_duration_bars_
    median` (leitura complementar) e `i_squared_pct_median` (secundário/
    corroborante, AG-114, `NaN` do lado A se `volatility_heterogeneity`
    não estiver presente lá -- ver docstring do módulo). Persiste o
    veredito (`_VERDICT_PATH`) e devolve o caminho."""
    logger.info(
        "compare_jump_model_lambda_transferability.starting",
        jump_penalty_by_symbol=jump_penalty_by_symbol,
        resolutions=list(resolutions),
    )

    condicao_a = _load_condicao_a()

    condicao_b_by_resolution: dict[str, dict[str, Any]] = {}
    for resolution_id in resolutions:
        logger.info(
            "compare_jump_model_lambda_transferability.condicao_b_resolution_starting",
            resolution_id=resolution_id,
        )
        report = mcw.run_jump_model_transferability_comparison(
            resolution_id,
            jump_penalty_by_symbol=jump_penalty_by_symbol,
            jump_n_states=jump_n_states,
            jump_seed=jump_seed,
            max_workers=max_workers,
            # True explícito (default de run_jump_model_transferability_comparison é
            # False, mesma assimetria nível-baixo/nível-alto de run_critical_windows_
            # comparison vs. run_and_save_critical_windows_report) -- este script É o
            # "nível alto" que quer o sinal secundário/corroborante (i_squared_pct,
            # AG-114), ver docstring do módulo.
            compute_volatility_heterogeneity=True,
        )
        condicao_b_by_resolution[resolution_id] = asdict(report)
        logger.info(
            "compare_jump_model_lambda_transferability.condicao_b_resolution_done",
            resolution_id=resolution_id,
        )

    _atomic_write_json(
        {
            "jump_penalty_by_symbol": jump_penalty_by_symbol,
            "by_resolution": list(condicao_b_by_resolution.values()),
        },
        _CONDICAO_B_REPORT_PATH,
    )

    verdicts: list[dict[str, Any]] = []
    for resolution_id in resolutions:
        a_resolution = _find_resolution(condicao_a, resolution_id)
        b_resolution = condicao_b_by_resolution.get(resolution_id)
        if a_resolution is None or b_resolution is None:
            logger.warning(
                "compare_jump_model_lambda_transferability.resolution_ausente",
                resolution_id=resolution_id,
                tem_a=a_resolution is not None,
                tem_b=b_resolution is not None,
            )
            continue
        a_candidate = _find_candidate(a_resolution, _JUMP_CLASSIFIER_ID)
        b_candidate = _find_candidate(b_resolution, _JUMP_CLASSIFIER_ID)
        if a_candidate is None or b_candidate is None:
            logger.warning(
                "compare_jump_model_lambda_transferability.candidato_ausente",
                resolution_id=resolution_id,
                tem_a=a_candidate is not None,
                tem_b=b_candidate is not None,
            )
            continue

        a_has_vol_het = bool(a_resolution.get("volatility_heterogeneity"))
        if not a_has_vol_het:
            logger.warning(
                "compare_jump_model_lambda_transferability.condicao_a_sem_volatility_heterogeneity",
                resolution_id=resolution_id,
                nota=(
                    "experiments/m4_critical_windows_report.json foi gerado antes da extensao "
                    "AG-114 (volatility_heterogeneity) -- i_squared_pct_median_condicao_a fica "
                    "NaN, so o valor B e reportado (informativo, sem baseline pra diff, B20)"
                ),
            )

        for symbol in _SYMBOLS:
            a_sat = _per_symbol_saturation_and_persistence(a_candidate, symbol)
            b_sat = _per_symbol_saturation_and_persistence(b_candidate, symbol)
            a_i2 = _per_symbol_i_squared(a_resolution, _JUMP_CLASSIFIER_ID, symbol)
            b_i2 = _per_symbol_i_squared(b_resolution, _JUMP_CLASSIFIER_ID, symbol)

            entry = {
                "resolution_id": resolution_id,
                "symbol": symbol,
                "jump_penalty_condicao_a": 0.002,  # noqa: magic-number -- valor documentado de constants.yaml::m4_jump_model_penalty (status quo, não um literal novo de pipeline)
                "jump_penalty_condicao_b": jump_penalty_by_symbol[symbol],
                "n_windows_ok_condicao_a": a_sat["n_windows_ok"],
                "n_windows_ok_condicao_b": b_sat["n_windows_ok"],
                "saturation_rate_condicao_a": a_sat["saturation_rate"],
                "saturation_rate_condicao_b": b_sat["saturation_rate"],
                "persistence_median_duration_bars_median_condicao_a": a_sat[
                    "persistence_median_duration_bars_median"
                ],
                "persistence_median_duration_bars_median_condicao_b": b_sat[
                    "persistence_median_duration_bars_median"
                ],
                "i_squared_pct_median_condicao_a": a_i2,
                "i_squared_pct_median_condicao_b": b_i2,
                "verdict": _verdict(a_sat["saturation_rate"], b_sat["saturation_rate"]),
            }
            verdicts.append(entry)
            logger.info("compare_jump_model_lambda_transferability.verdict", **entry)

    _atomic_write_json({"verdicts": verdicts}, _VERDICT_PATH)
    logger.info(
        "compare_jump_model_lambda_transferability.done",
        n_verdicts=len(verdicts),
        dest=str(_VERDICT_PATH),
    )
    return _VERDICT_PATH


if __name__ == "__main__":
    raise SystemExit(
        "tools.diagnostics.compare_jump_model_lambda_transferability: "
        "run_transferability_comparison_and_diff requer jump_penalty_by_symbol (4 valores "
        "calibrados por ativo, saída de calibrate_jump_model_penalty_per_asset.py) -- não "
        "inventados aqui (B20) e consome ~3h de fit real (mesma ordem de grandeza do harness "
        "principal por célula) -- não rode este módulo como script sem antes rodar a "
        "calibração E ter autorização explícita do Manager pra Condição B. Ver docstring de "
        "run_transferability_comparison_and_diff para como chamar manualmente depois."
    )
