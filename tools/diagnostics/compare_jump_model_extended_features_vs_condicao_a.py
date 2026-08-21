"""Comparação final -- Condição A (Jump Model excluído dos 4 ativos
não-BTC, status quo) vs "Condição C" (Jump Model com espaço de observação
ESTENDIDO -- 4 features + `jump_n_states=3` -- rodado nos 4 ativos
não-BTC) do experimento de transferibilidade de Jump Model (`AG-119`,
`audit/architecture_gaps_log.yaml`). Autorização do Manager, 2026-08-20
("autorizado pode rodar").

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar DEPOIS de `tools/diagnostics/retest_
jump_model_extended_features_k3.py` (AG-119) terminar pros 4 ativos
(SOLUSDT/BNBUSDT/XRPUSDT já concluído; ETHUSDT em andamento na sessão que
escreveu este script) e de decidir os 4 valores de λ a partir da tabela
impressa por ele -- este script NUNCA inventa esses valores (B20):

    uv run python -c "
    from tools.diagnostics.compare_jump_model_extended_features_vs_condicao_a import (
        run_condicao_c_and_diff,
    )
    run_condicao_c_and_diff(
        jump_penalty_by_symbol={
            'ETHUSDT': <valor medido por retest_jump_model_extended_features_k3.py, K=3>,
            'SOLUSDT': <valor medido>,
            'BNBUSDT': <valor medido>,
            'XRPUSDT': <valor medido>,
        }
    )
    "

**NÃO RODE a rodada real das 3 resoluções (~3h, mesma ordem de grandeza
do harness completo por célula, K=3 é ~4-8x mais caro por fit que K=2 --
ver duração real medida no log do reteste) sem autorização explícita do
Manager -- mesma disciplina de `run_and_save_m4_report`/`run_and_save_
critical_windows_report`/`compare_jump_model_lambda_transferability.py`
(Condição B, mesmo padrão espelhado aqui).**

**Desenho do experimento** (contexto completo em `audit/architecture_
gaps_log.yaml::AG-119`, decisão original em `AG-117`). Condição A (status
quo): Jump Model roda SÓ para BTCUSDT no relatório real
(`experiments/m4_critical_windows_report.json`, `include_jump_model =
symbol == "BTCUSDT"` em `m4_critical_windows._run_one_cell`) -- já
rodado, custo zero (só lido daqui pra este diff, nunca recomputado).
"Condição C" (nova): Jump Model com observação 4D (`log_return_1,
realized_vol_short, realized_vol_long, downside_deviation`) +
`jump_n_states=3`, gerada por `src.analysis.m4_critical_windows.
run_jump_model_extended_features_comparison` (baseline + Jump Model só,
mesmo custo relativo de `run_jump_model_transferability_comparison`/
Condição B -- HMM/BOCPD não mudam com `jump_penalty`/espaço de
observação, recomputá-los seria custo puro).

**Por que "Condição C", não uma correção in-place da Condição A/B.** O
reteste isolado (`AG-119`) mostrou que o espaço de 2 features + K=2 fixo
(usado nas Condições A e B) estava CONFUNDIDO com 2 outras variáveis
(espaço de features estreito, K forçado em 2) -- não é uma recalibração
de λ dentro do MESMO desenho (isso já é a Condição B), é um desenho de
observação DIFERENTE. Diff é feito contra a Condição A (status quo real
persistido), não contra a Condição B (que usa o espaço de 2 features
antigo e nunca foi rodada no harness real de 3 resoluções -- só existe
como script pronto, `compare_jump_model_lambda_transferability.py`).

**Métrica de decisão** (`is_saturated`/`saturation_rate`,
`SymbolCandidateDetail`/`AggregatedCandidateResult`, mesmo campo
reaproveitado de AG-087) -- mantém "Condição C" candidata a entrar na
disputa do AG-114 se a saturação cair perto de zero (consistente com o
reteste isolado, que já mediu 100% `is_genuine_oos=True` no grid pros 4
ativos); desqualifica se a saturação persistir comparável à Condição A.
`persistence_median_duration_bars` entra como leitura complementar (não
critério sozinho, mesma ressalva de Condição B).

**Secundária/corroborante:** `i_squared_pct`/`p_value_permutation` de
`VolatilityHeterogeneitySymbolDetail` (AG-114) -- mesma checagem em
runtime de `a_resolution.get("volatility_heterogeneity")` que
`compare_jump_model_lambda_transferability.py` já faz (Condição A pode ou
não ter esse campo dependendo de quando foi gerada; nunca inventado se
ausente, `NaN` explícito do lado A).

**Achado real já documentado, não escondido** (`AG-119`, resolução): o
grid de λ testado (`[0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02]`)
SATUROU NO TOPO pros 4 ativos -- todo ponto do grid deu `is_genuine_oos=
True`, então `jump_penalty` recomendado (maior valor testado, mais
parcimonioso/mais regularizado dentro do que foi medido) é `0.02` pros 4,
mas o TETO REAL não foi medido (poderia ser maior). Isso é reportado
explicitamente no log deste script (`jump_penalty_by_symbol` recebido é
ecoado no payload persistido), nunca escondido atrás de um número que
pareça "calibrado com folga"."""

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
_CONDICAO_C_REPORT_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "m4_jump_model_extended_features_condicao_c_report.json"
)
_VERDICT_PATH: Final[Path] = (
    _REPO_ROOT / "experiments" / "m4_jump_model_extended_features_condicao_c_verdict.json"
)

_JUMP_CLASSIFIER_ID: Final[str] = "jump_model_cjm_v1"
_RESOLUTIONS: Final[tuple[str, ...]] = mcw.RESOLUTIONS
_SYMBOLS: Final[tuple[str, ...]] = mcw.JUMP_TRANSFERABILITY_SYMBOLS

# Leitura QUALITATIVA pro Manager decidir -- NÃO é um gate formal (B20:
# nenhum threshold aqui decide sozinho se "Condição C" passa). Mesmos
# limiares de `compare_jump_model_lambda_transferability.py` (Condição
# B), reusados por consistência de leitura entre os 2 experimentos.
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
    logger.info(
        "compare_jump_model_extended_features_vs_condicao_a.report_written", path=str(dest_path)
    )


def _load_condicao_a() -> dict[str, Any]:
    if not _CONDICAO_A_PATH.exists():
        raise FileNotFoundError(
            f"compare_jump_model_extended_features_vs_condicao_a: Condição A ausente em "
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
    """Mesmo corte "por (símbolo, resolução)" de `compare_jump_model_
    lambda_transferability._per_symbol_saturation_and_persistence` --
    perfura `per_window[].per_symbol[]` já serializado, sem reimplementar
    nenhuma fórmula de agregação nova."""
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
    """Mesmo corte por símbolo de `compare_jump_model_lambda_
    transferability._per_symbol_i_squared` -- `NaN` se o campo não
    existir no relatório ou se o símbolo nunca aparecer com
    `n_buckets>0`."""
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


def _verdict(saturation_a: float, saturation_c: float) -> str:
    if _is_nan(saturation_c):
        return "sem_dado_condicao_c"
    if saturation_c <= _SATURATION_NEAR_ZERO_MAX:
        return "candidata_a_entrar_no_ranking_ag114 -- saturacao caiu perto de zero"
    if not _is_nan(saturation_a) and abs(saturation_c - saturation_a) <= (
        _SATURATION_COMPARABLE_TO_A_TOLERANCE
    ):
        return "desqualifica -- saturacao comparavel a condicao A mesmo com espaco 4D+K=3"
    return "inconclusivo -- saturacao caiu mas nao perto de zero, ver tabela completa"


def run_condicao_c_and_diff(
    *,
    jump_penalty_by_symbol: dict[str, float],
    resolutions: tuple[str, ...] = _RESOLUTIONS,
    jump_n_states: int = 3,
    jump_seed: int = 0,
    max_workers: int | None = None,
) -> Path:
    """Gera "Condição C" (`mcw.run_jump_model_extended_features_
    comparison` por resolução, `jump_penalty_by_symbol` obrigatório --
    `ValueError` se faltar algum dos 4 ativos, nunca inventado), persiste
    como JSON (`_CONDICAO_C_REPORT_PATH`), carrega a Condição A já
    existente do disco (`experiments/m4_critical_windows_report.json`,
    custo zero) e produz o diff por `(símbolo, resolução)` --
    `saturation_rate` (critério primário, mesmo campo de AG-087),
    `persistence_median_duration_bars_median` (leitura complementar) e
    `i_squared_pct_median` (secundário/corroborante, AG-114, `NaN` do
    lado A se `volatility_heterogeneity` não estiver presente lá).
    Persiste o veredito (`_VERDICT_PATH`) e devolve o caminho."""
    logger.info(
        "compare_jump_model_extended_features_vs_condicao_a.starting",
        jump_penalty_by_symbol=jump_penalty_by_symbol,
        jump_n_states=jump_n_states,
        resolutions=list(resolutions),
    )

    condicao_a = _load_condicao_a()

    condicao_c_by_resolution: dict[str, dict[str, Any]] = {}
    for resolution_id in resolutions:
        logger.info(
            "compare_jump_model_extended_features_vs_condicao_a.condicao_c_resolution_starting",
            resolution_id=resolution_id,
        )
        report = mcw.run_jump_model_extended_features_comparison(
            resolution_id,
            jump_penalty_by_symbol=jump_penalty_by_symbol,
            jump_n_states=jump_n_states,
            jump_seed=jump_seed,
            max_workers=max_workers,
            # True explícito (default de run_jump_model_extended_features_comparison é
            # False, mesma assimetria nível-baixo/nível-alto já usada em Condição B) --
            # este script É o "nível alto" que quer o sinal secundário/corroborante
            # (i_squared_pct, AG-114), ver docstring do módulo.
            compute_volatility_heterogeneity=True,
        )
        condicao_c_by_resolution[resolution_id] = asdict(report)
        logger.info(
            "compare_jump_model_extended_features_vs_condicao_a.condicao_c_resolution_done",
            resolution_id=resolution_id,
        )

    _atomic_write_json(
        {
            "jump_penalty_by_symbol": jump_penalty_by_symbol,
            "jump_n_states": jump_n_states,
            "by_resolution": list(condicao_c_by_resolution.values()),
        },
        _CONDICAO_C_REPORT_PATH,
    )

    verdicts: list[dict[str, Any]] = []
    for resolution_id in resolutions:
        a_resolution = _find_resolution(condicao_a, resolution_id)
        c_resolution = condicao_c_by_resolution.get(resolution_id)
        if a_resolution is None or c_resolution is None:
            logger.warning(
                "compare_jump_model_extended_features_vs_condicao_a.resolution_ausente",
                resolution_id=resolution_id,
                tem_a=a_resolution is not None,
                tem_c=c_resolution is not None,
            )
            continue
        a_candidate = _find_candidate(a_resolution, _JUMP_CLASSIFIER_ID)
        c_candidate = _find_candidate(c_resolution, _JUMP_CLASSIFIER_ID)
        if a_candidate is None or c_candidate is None:
            logger.warning(
                "compare_jump_model_extended_features_vs_condicao_a.candidato_ausente",
                resolution_id=resolution_id,
                tem_a=a_candidate is not None,
                tem_c=c_candidate is not None,
            )
            continue

        a_has_vol_het = bool(a_resolution.get("volatility_heterogeneity"))
        if not a_has_vol_het:
            logger.warning(
                "compare_jump_model_extended_features_vs_condicao_a."
                "condicao_a_sem_volatility_heterogeneity",
                resolution_id=resolution_id,
                nota=(
                    "experiments/m4_critical_windows_report.json foi gerado antes da extensao "
                    "AG-114 (volatility_heterogeneity) OU o campo esta ausente por outro motivo "
                    "-- i_squared_pct_median_condicao_a fica NaN, so o valor C e reportado "
                    "(informativo, sem baseline pra diff, B20)"
                ),
            )

        for symbol in _SYMBOLS:
            a_sat = _per_symbol_saturation_and_persistence(a_candidate, symbol)
            c_sat = _per_symbol_saturation_and_persistence(c_candidate, symbol)
            a_i2 = _per_symbol_i_squared(a_resolution, _JUMP_CLASSIFIER_ID, symbol)
            c_i2 = _per_symbol_i_squared(c_resolution, _JUMP_CLASSIFIER_ID, symbol)

            entry = {
                "resolution_id": resolution_id,
                "symbol": symbol,
                "jump_penalty_condicao_c": jump_penalty_by_symbol[symbol],
                "jump_n_states_condicao_c": jump_n_states,
                "n_windows_ok_condicao_a": a_sat["n_windows_ok"],
                "n_windows_ok_condicao_c": c_sat["n_windows_ok"],
                "saturation_rate_condicao_a": a_sat["saturation_rate"],
                "saturation_rate_condicao_c": c_sat["saturation_rate"],
                "persistence_median_duration_bars_median_condicao_a": a_sat[
                    "persistence_median_duration_bars_median"
                ],
                "persistence_median_duration_bars_median_condicao_c": c_sat[
                    "persistence_median_duration_bars_median"
                ],
                "i_squared_pct_median_condicao_a": a_i2,
                "i_squared_pct_median_condicao_c": c_i2,
                "verdict": _verdict(a_sat["saturation_rate"], c_sat["saturation_rate"]),
            }
            verdicts.append(entry)
            logger.info(
                "compare_jump_model_extended_features_vs_condicao_a.verdict", **entry
            )

    _atomic_write_json({"verdicts": verdicts}, _VERDICT_PATH)
    logger.info(
        "compare_jump_model_extended_features_vs_condicao_a.done",
        n_verdicts=len(verdicts),
        dest=str(_VERDICT_PATH),
    )
    return _VERDICT_PATH


if __name__ == "__main__":
    raise SystemExit(
        "tools.diagnostics.compare_jump_model_extended_features_vs_condicao_a: "
        "run_condicao_c_and_diff requer jump_penalty_by_symbol (4 valores calibrados por "
        "ativo, saída de retest_jump_model_extended_features_k3.py, AG-119) -- não inventados "
        "aqui (B20) e consome ~3h+ de fit real (K=3 é mais caro por fit que K=2, mesma ordem "
        "de grandeza do harness principal por célula) -- não rode este módulo como script sem "
        "antes rodar o reteste E ter autorização explícita do Manager pra rodada real de "
        "'Condição C'. Ver docstring de run_condicao_c_and_diff para como chamar manualmente "
        "depois."
    )
