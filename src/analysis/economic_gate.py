"""Gate econômico — o lift mínimo em `P(TP)` que um modelo precisa entregar
para o motor apenas empatar, por célula `(symbol, resolution_id, side,
geometria)`.

**Por que este módulo existe.** O S1 (`s1_tp_sl_sensitivity`) já persiste,
por célula, as duas quantidades que definem o problema econômico do
projeto: a taxa de acerto base (`frac_tp`) e a taxa de acerto necessária
para cobrir o custo round-trip (`breakeven_wr_cost_adjusted`). O veredito
daquele relatório é literalmente `"TBD -- criterio operacional de
'sobrevive a faixa' e decisao do Manager, nao computado aqui"` — ou seja,
a régua estava no dado e nunca foi aplicada como critério.

A razão entre as duas é a régua:

    required_lift = breakeven_wr_cost_adjusted / frac_tp

Ela responde "quanto o Alpha precisa multiplicar a taxa de acerto base
desta célula para o motor sair do zero". É o gate anterior a qualquer
comparação de Sharpe, DSR ou `ret_net`: um candidato que projete lift
abaixo do exigido não pode ser positivo nesta célula, e não deveria
consumir trial (`audit/n_lifetime.yaml`) para descobrir isso.

**O erro não é opcional aqui — é a razão de o módulo existir.** As
diferenças de `required_lift` entre resoluções são de terceira casa
decimal em alguns pares, e `AG-246` (`src/analysis/ordering_fragility.py`)
mostrou que este projeto já ordenou células por diferenças que não eram
distinguíveis de ruído. Reportar a ordenação sem o erro repetiria
exatamente o defeito que aquele achado registrou. Por isso toda linha sai
com `stderr`/IC, e a comparação entre células é feita por
`is_distinguishable`, nunca por `<`.

**Método (forma fechada, sem bootstrap).** `frac_tp` é uma proporção
binomial sobre `n_filled` trades preenchidos. `breakeven_wr_cost_adjusted`
é determinístico dada a geometria e o custo. Pelo método delta sobre
`L = B/p`:

    sigma(L) = L * sqrt((1 - p) / (p * n))

**Ressalva de proveniência, explícita (não escondida).** `breakeven_wr_
cost_adjusted` deriva de `round_trip_cost_bps_maker_prob`, que por sua vez
usa `p_target_hit`. A entrada de `p_target_hit` em `config/constants.yaml`
registra ela mesma uma "SEGUNDA REMEDIÇÃO PENDENTE": o valor vigente foi
medido antes do relabel de `AG-221`/`AG-229` e a própria entrada prevê que
sobe para ~0,49 depois dele — que é o valor que os relatórios S1 por
resolução de fato mostram. Enquanto essa remediação não acontecer, `B`
está levemente SUPERESTIMADO e portanto `required_lift` também. O viés é
COMUM a todas as células (mesmo custo global), então a ORDENAÇÃO entre
células é robusta a ele; o NÍVEL absoluto não é. Não trate o número
absoluto como final antes da remediação.

Núcleo puro (Idioma A, §Núcleo funcional do `CLAUDE.md`): as funções de
cálculo recebem dado em memória e devolvem dado em memória. A casca
(`run_economic_gate_report`) resolve arquivo, lê e persiste."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import structlog

logger = structlog.get_logger(__name__)

EXPERIMENTS_DIR: Final[Path] = Path("experiments")
CONFIG_DIR: Final[Path] = Path("config")

#: Resoluções cobertas pelos relatórios S1 por grade (`f25e1df`, 2026-08-25).
RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")

#: fração -> basis points (1 = 10.000 bps). Conversão de unidade, não
#: hiperparâmetro.
_BPS_PER_UNIT: Final[float] = 10_000.0  # noqa: magic-number -- conversão de unidade


#: z para IC bilateral de 95% — quantil 0,975 da normal padrão.
_Z_95: Final[float] = 1.959964  # noqa: magic-number -- quantil normal, não parâmetro de negócio


class EconomicGateError(RuntimeError):
    """Erro estrutural do gate econômico — relatório ausente, campo faltando
    ou contagem inválida. Nunca silencia: um insumo ruim vira exceção com
    contexto, não uma linha com `NaN` que se propaga para a decisão."""


# ============================================================================
# Núcleo puro — zero IO
# ============================================================================


@dataclass(frozen=True, slots=True)
class GateRow:
    """Uma célula do gate econômico. `required_lift` é adimensional (razão
    de duas taxas de acerto); `atr_median_bps` fica junto porque é a
    variável que EXPLICA a ordenação (custo é fixo em bps, então o alvo é
    mais fácil onde o ATR é maior)."""

    symbol: str
    resolution_id: str
    side: str
    cell_id: str
    tp_atr_mult: float
    sl_atr_mult: float
    n_filled: int
    atr_median_bps: float
    p_tp: float
    breakeven_wr: float
    required_lift: float
    required_lift_stderr: float
    required_lift_ci95_low: float
    required_lift_ci95_high: float


def required_lift(p_tp: float, breakeven_wr: float) -> float:
    """`breakeven / p_tp` — quanto a taxa de acerto precisa ser multiplicada
    para cobrir o custo. Levanta se `p_tp <= 0`: uma célula sem nenhum toque
    de TP não tem lift definido, e devolver `inf` faria a célula parecer
    apenas "difícil" quando na verdade ela é indefinida."""
    if not (p_tp > 0.0):
        raise EconomicGateError(
            f"p_tp={p_tp!r} não é positivo -- required_lift indefinido "
            "(célula sem toque de TP não é 'difícil', é indeterminada)"
        )
    return breakeven_wr / p_tp


def required_lift_stderr(p_tp: float, breakeven_wr: float, n_filled: int) -> float:
    """Método delta sobre `L = B/p` com `p` binomial de `n` observações:
    `sigma(L) = L * sqrt((1-p) / (p*n))`.

    `B` entra como determinístico — ele deriva do custo global, comum a
    todas as células (ver ressalva de proveniência na docstring do módulo).
    Isso torna o erro aqui um erro de ORDENAÇÃO (válido para comparar
    células entre si), não de NÍVEL absoluto."""
    if n_filled <= 0:
        raise EconomicGateError(
            f"n_filled={n_filled!r} não é positivo -- sem amostra não há erro estimável"
        )
    # `required_lift` já rejeita `p_tp <= 0`, mas a guarda é repetida aqui de
    # propósito: o denominador da variância é `p_tp * n_filled`, e depender de
    # uma checagem feita dentro de outra função deixaria a segurança desta
    # divisão invisível para quem lê (e para check_unguarded_ratios).
    lift = required_lift(p_tp, breakeven_wr)
    if not (p_tp > 0.0 and n_filled > 0):
        raise EconomicGateError(
            f"denominador inválido para a variância: p_tp={p_tp!r}, n_filled={n_filled!r}"
        )
    return lift * math.sqrt(
        (1.0 - p_tp) / (p_tp * n_filled)  # noqa: unguarded-ratio -- p_tp>0 e n_filled>0 verificados nas duas guardas imediatamente acima
    )


def is_distinguishable(a: GateRow, b: GateRow, *, z: float = _Z_95) -> bool:
    """`|L_a - L_b| > z * sqrt(sigma_a^2 + sigma_b^2)`.

    As amostras de células de resoluções diferentes são independentes
    (grades distintas, conjuntos de barras distintos), então as variâncias
    somam. Para células da MESMA grade e mesmo símbolo a independência é
    aproximada (os trades se sobrepõem) e o teste é CONSERVADOR no sentido
    certo: subestimar a covariância positiva infla o erro da diferença e
    torna "distinguível" mais difícil de afirmar, não mais fácil."""
    delta = abs(a.required_lift - b.required_lift)
    pooled = math.sqrt(a.required_lift_stderr**2 + b.required_lift_stderr**2)
    return delta > z * pooled


def _cell_rows(
    report: Mapping[str, Any], *, resolution_id: str
) -> list[GateRow]:
    """Extrai as células de UM relatório S1 já carregado. Puro: recebe o
    dict, não o caminho."""
    by_symbol = report.get("by_symbol")
    if not isinstance(by_symbol, Mapping):
        raise EconomicGateError(
            f"relatório de {resolution_id} sem bloco 'by_symbol' -- schema inesperado"
        )

    rows: list[GateRow] = []
    for symbol, sym_block in by_symbol.items():
        by_side = sym_block.get("by_side", {})
        for side, side_block in by_side.items():
            atr_median = float(side_block["atr_median_side"])
            for cell_id, cell in side_block.get("cells", {}).items():
                p_tp = float(cell["frac_tp"])
                breakeven = float(cell["breakeven_wr_cost_adjusted"])
                n_filled = int(cell["n_filled"])
                lift = required_lift(p_tp, breakeven)
                stderr = required_lift_stderr(p_tp, breakeven, n_filled)
                rows.append(
                    GateRow(
                        symbol=str(symbol),
                        resolution_id=resolution_id,
                        side=str(side),
                        cell_id=str(cell_id),
                        tp_atr_mult=float(cell["tp_atr_mult"]),
                        sl_atr_mult=float(cell["sl_atr_mult"]),
                        n_filled=n_filled,
                        atr_median_bps=atr_median * _BPS_PER_UNIT,
                        p_tp=p_tp,
                        breakeven_wr=breakeven,
                        required_lift=lift,
                        required_lift_stderr=stderr,
                        required_lift_ci95_low=lift - _Z_95 * stderr,
                        required_lift_ci95_high=lift + _Z_95 * stderr,
                    )
                )
    return rows


def build_gate_rows(reports_by_resolution: Mapping[str, Mapping[str, Any]]) -> list[GateRow]:
    """Núcleo: recebe `{resolution_id: relatório_S1_carregado}` e devolve
    todas as células com lift e erro. Ordenado por `required_lift`
    crescente — o alvo mais fácil primeiro."""
    rows: list[GateRow] = []
    for resolution_id, report in reports_by_resolution.items():
        rows.extend(_cell_rows(report, resolution_id=resolution_id))
    return sorted(rows, key=lambda r: r.required_lift)


def best_per_combo(rows: Sequence[GateRow]) -> dict[tuple[str, str], GateRow]:
    """Melhor geometria/lado por `(symbol, resolution_id)` — o menor lift
    exigido que aquela célula de produção poderia enfrentar se a geometria
    fosse escolhida por combinação em vez de global."""
    best: dict[tuple[str, str], GateRow] = {}
    for row in rows:
        key = (row.symbol, row.resolution_id)
        if key not in best or row.required_lift < best[key].required_lift:
            best[key] = row
    return best


def rank_resolutions(rows: Sequence[GateRow]) -> list[dict[str, Any]]:
    """Para cada símbolo, ordena as resoluções pelo melhor lift exigido e
    marca se o 1º é DISTINGUÍVEL do 2º. Um `False` aqui significa que a
    escolha de grade por este critério é ruído — exatamente o que `AG-246`
    encontrou em outros eixos, e a razão de este campo existir em vez de
    um ranking nu."""
    best = best_per_combo(rows)
    symbols = sorted({s for s, _ in best})

    out: list[dict[str, Any]] = []
    for symbol in symbols:
        ranked = sorted(
            (best[(symbol, r)] for r in RESOLUTIONS if (symbol, r) in best),
            key=lambda r: r.required_lift,
        )
        if not ranked:
            continue
        first = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        out.append(
            {
                "symbol": symbol,
                "ordem": [
                    {
                        "resolution_id": r.resolution_id,
                        "required_lift": r.required_lift,
                        "stderr": r.required_lift_stderr,
                        "cell_id": r.cell_id,
                        "side": r.side,
                        "atr_median_bps": r.atr_median_bps,
                    }
                    for r in ranked
                ],
                "vencedor": first.resolution_id,
                "vencedor_distinguivel_do_2o": (
                    is_distinguishable(first, runner_up) if runner_up is not None else None
                ),
                "delta_para_2o": (
                    runner_up.required_lift - first.required_lift
                    if runner_up is not None
                    else None
                ),
            }
        )
    return out


# ============================================================================
# Casca com IO
# ============================================================================


def load_s1_reports(
    *, out_dir: Path = EXPERIMENTS_DIR, resolutions: Sequence[str] = RESOLUTIONS
) -> dict[str, dict[str, Any]]:
    """Lê `s1_tp_sl_sensitivity_report_{R}.json`. Levanta com caminho real
    se faltar — nunca cai silenciosamente no relatório sem sufixo, que é da
    grade de RELÓGIO 15m legada e não é produção (`AG-042`)."""
    reports: dict[str, dict[str, Any]] = {}
    for resolution_id in resolutions:
        path = out_dir / f"s1_tp_sl_sensitivity_report_{resolution_id}.json"
        if not path.exists():
            raise EconomicGateError(
                f"relatório S1 de {resolution_id} não encontrado em {path.resolve()} -- "
                "rode src.analysis.s1_tp_sl_sensitivity para esta resolução antes. "
                "NÃO caia no relatório sem sufixo: ele é da grade 15m legada."
            )
        with path.open(encoding="utf-8") as fh:
            reports[resolution_id] = json.load(fh)
    return reports


def _write_atomic(path: Path, content: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    fd = os.open(tmp, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


def _gate_yaml(rows: Sequence[GateRow], *, source_version: str) -> str:
    """`config/min_alpha_lift_by_combo.yaml` — schema PRÓPRIO, fora de
    `constants.yaml` de propósito: o valor não é escalar único, é uma
    tabela por `(symbol, resolution_id)`. Mesmo precedente de
    `config/alpha_hyperparams_by_combo.yaml` (`ADR-003`)."""
    best = best_per_combo(rows)
    lines = [
        "# config/min_alpha_lift_by_combo.yaml",
        "#",
        "# Lift MÍNIMO em P(TP) que um modelo precisa entregar para o motor",
        "# empatar, por (symbol, resolution_id). Gate econômico anterior a",
        "# qualquer comparação de Sharpe/DSR/ret_net.",
        "#",
        "# provenance: DERIVED -- required_lift = breakeven_wr_cost_adjusted /",
        "# frac_tp, ambos MEASURED e persistidos por",
        "# experiments/s1_tp_sl_sensitivity_report_{R1,R2,R3}.json",
        f"# (code_version={source_version}).",
        "#",
        "# Gerado por src/analysis/economic_gate.py -- NÃO editar à mão.",
        "#",
        "# RESSALVA (ver docstring do módulo): breakeven deriva de",
        "# round_trip_cost_bps_maker_prob, cuja p_target_hit tem remediação",
        "# pendente registrada na própria entrada de constants.yaml. O viés é",
        "# comum a todas as células: a ORDENAÇÃO é robusta, o NÍVEL absoluto",
        "# não. Reexecutar este módulo após a remediação.",
        "",
        "min_alpha_lift_ptp:",
    ]
    for (symbol, resolution_id), row in sorted(best.items()):
        lines.extend(
            [
                f"  {symbol}_{resolution_id}:",
                f"    value: {row.required_lift:.6f}",
                f"    stderr: {row.required_lift_stderr:.6f}",
                f"    ci95: [{row.required_lift_ci95_low:.6f}, {row.required_lift_ci95_high:.6f}]",
                f"    geometria_otima: {row.cell_id}",
                f"    side: {row.side}",
                f"    tp_atr_mult: {row.tp_atr_mult}",
                f"    sl_atr_mult: {row.sl_atr_mult}",
                f"    p_tp_base: {row.p_tp:.6f}",
                f"    breakeven_wr: {row.breakeven_wr:.6f}",
                f"    atr_median_bps: {row.atr_median_bps:.2f}",
                f"    n_filled: {row.n_filled}",
            ]
        )
    return "\n".join(lines) + "\n"


def run_economic_gate_report(
    *, out_dir: Path = EXPERIMENTS_DIR, config_dir: Path = CONFIG_DIR
) -> tuple[Path, Path]:
    """Casca — lê os 3 relatórios S1 por resolução, aplica o núcleo,
    persiste o relatório e a tabela de gate. Devolve `(report_path,
    gate_yaml_path)`."""
    reports = load_s1_reports(out_dir=out_dir)
    source_version = str(reports[RESOLUTIONS[0]].get("code_version", "desconhecido"))

    rows = build_gate_rows(reports)
    ranking = rank_resolutions(rows)

    n_indistinguiveis = sum(
        1 for r in ranking if r["vencedor_distinguivel_do_2o"] is False
    )

    payload: dict[str, Any] = {
        "task": "economic_gate",
        "pergunta": (
            "Quanto lift em P(TP) o Alpha precisa entregar para o motor empatar, "
            "por celula, e a ordenacao entre grades e distinguivel de ruido?"
        ),
        "source_code_version": source_version,
        "formula": "required_lift = breakeven_wr_cost_adjusted / frac_tp",
        "stderr_metodo": "delta sobre L=B/p com p binomial: sigma(L)=L*sqrt((1-p)/(p*n))",
        "ressalva_proveniencia": (
            "breakeven deriva de round_trip_cost_bps_maker_prob (p_target_hit com "
            "remediacao pendente, ver constants.yaml). Vies comum a todas as celulas: "
            "ordenacao robusta, nivel absoluto nao."
        ),
        "n_celulas": len(rows),
        "ranking_por_simbolo": ranking,
        "n_simbolos_com_vencedor_indistinguivel": n_indistinguiveis,
        "melhores_10_celulas": [asdict(r) for r in rows[:10]],
        "piores_5_celulas": [asdict(r) for r in rows[-5:]],
    }

    report_path = _write_atomic(
        out_dir / "economic_gate_report.json",
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    gate_path = _write_atomic(
        config_dir / "min_alpha_lift_by_combo.yaml",
        _gate_yaml(rows, source_version=source_version),
    )

    logger.info(
        "analysis.economic_gate.done",
        report_path=str(report_path.resolve()),
        gate_path=str(gate_path.resolve()),
        n_celulas=len(rows),
        melhor_celula=f"{rows[0].symbol}/{rows[0].resolution_id}/{rows[0].side}/{rows[0].cell_id}",
        melhor_lift=round(rows[0].required_lift, 4),
        n_simbolos_com_vencedor_indistinguivel=n_indistinguiveis,
    )
    return report_path, gate_path


if __name__ == "__main__":
    run_economic_gate_report()
