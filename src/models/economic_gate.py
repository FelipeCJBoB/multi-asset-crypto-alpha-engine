"""Gate econômico — núcleo de decisão (camada `models/`).

**Por que isto mora aqui, e não em `src/analysis/economic_gate.py`.**
Até 2026-08-27 este núcleo vivia inteiro em `analysis/` — correto enquanto
`evaluate_economic_gate`/`load_min_alpha_lift_by_combo` eram só medição
pós-hoc, nunca chamadas por nenhum treino real (`AG-260` ponto b, "não
wireado em nenhum orquestrador de trial"). Ao desenhar esse orquestrador
(`/redesign_workflow`, 2026-08-27, decisão do Manager) ficou claro que
`evaluate_economic_gate` estava prestes a virar **insumo real de
`run_layer1_sprint`** — e `CLAUDE.md` (Layer hierarchy) é explícito:
`analysis/` "fica fora do contrato `importlinter` de propósito... nunca
pode virar insumo de treino/seleção de feature". Mover o núcleo de
DECISÃO pra `models/` (mesma camada de `hyperparams_by_combo.py`, mesmo
padrão de tabela-por-combo) fecha essa violação antes que ela aconteça,
em vez de depois.

O que NÃO mora aqui: a derivação da tabela a partir do sweep S1
(`build_gate_rows`, `recommend_geometry_per_combo`, `run_economic_gate_
report` e o resto da geração/escrita de `config/min_alpha_lift_by_combo.
yaml`) continua em `src/analysis/economic_gate.py` — é medição pós-hoc
genuína (lê `experiments/s1_tp_sl_sensitivity_report_*.json`, nunca é
chamada durante um treino real), e mover isso pra `models/` faria o
inverso do problema que este módulo resolve. `analysis/economic_gate.py`
importa `GateRow`/`EconomicGateError` DE VOLTA daqui — direção permitida
(`analysis` pode ler `models`, nunca o contrário).

**A régua em si** (não muda com a mudança de arquivo): `required_lift =
breakeven_wr / p_tp_base` — quanto o Alpha precisa multiplicar a taxa de
acerto base pra cobrir o custo round-trip. Ver a docstring de `src.
analysis.economic_gate` pro contexto completo (`AG-260`, ressalvas de
proveniência de `p_target_hit`/calibrador).

Núcleo puro (Idioma A): `evaluate_economic_gate`/`lookup_pre_trial_gate`/
`suggested_n_lifetime_delta` recebem dado em memória (ou um `Mapping` já
carregado) e devolvem dado em memória. Só `load_min_alpha_lift_by_combo`
toca disco (casca fina, leitura)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

CONFIG_DIR: Final[Path] = Path("config")

#: z para IC bilateral de 95% — quantil 0,975 da normal padrão.
_Z_95: Final[float] = 1.959964  # noqa: magic-number -- quantil normal, não parâmetro de negócio


class EconomicGateError(RuntimeError):
    """Erro estrutural do gate econômico — tabela ausente, campo faltando
    ou contagem inválida. Nunca silencia: um insumo ruim vira exceção com
    contexto, não uma linha com `NaN` que se propaga para a decisão."""


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


@dataclass(frozen=True, slots=True)
class EconomicGateVerdict:
    """Resultado de comparar o `p_tp` ACHIEVED de um candidato real (não o
    `frac_tp` base da célula) contra `breakeven_wr` da mesma célula --
    mesma disciplina estatística do resto do módulo: nunca `>`/`<` cru,
    sempre com erro (`distinguishable`, não só `passes`)."""

    symbol: str
    resolution_id: str
    side: str
    candidate_p_tp: float
    candidate_p_tp_stderr: float
    breakeven_wr: float
    margin: float
    passes: bool
    distinguishable: bool
    side_matches_threshold: bool


def evaluate_economic_gate(
    candidate_p_tp: float,
    n_candidate: int,
    threshold: GateRow,
    *,
    side: str,
    z: float = _Z_95,
) -> EconomicGateVerdict:
    """Compara `candidate_p_tp` (achieved por um candidato REAL, não a
    `frac_tp` base que `threshold` já embute) contra `threshold.
    breakeven_wr` da MESMA célula `(symbol, resolution_id)`.

    `passes` = `candidate_p_tp > breakeven_wr` (naive, reportado por
    transparência). `distinguishable` = a MESMA leitura, mas exigindo que
    a margem supere `z` erros-padrão do candidato (erro binomial padrão
    sobre `n_candidate` -- `breakeven_wr` entra determinístico, mesma
    convenção já declarada em `src.analysis.economic_gate` pra
    `required_lift_stderr`). É `distinguishable`, não `passes`, que
    deveria decidir qualquer gate binding -- `passes` sozinho repete
    exatamente o defeito que `AG-246`/`is_distinguishable`
    (`src.analysis.economic_gate`) existem pra evitar.

    `side_matches_threshold` -- `min_alpha_lift_by_combo.yaml` guarda só
    UMA linha por `(symbol, resolution_id)` (`best_per_combo`, o lado/
    geometria de MENOR lift exigido -- a combinação mais fácil de bater
    dentro daquela célula, não a mais exigente) -- `False` sinaliza que
    `threshold` foi medido pro lado OPOSTO ao do candidato: `breakeven_wr`
    ainda é o número certo (é função de custo/geometria, não de lado),
    mas quem chama deve saber que o lado gravado no relatório não é o que
    está sendo avaliado.

    Raises:
        EconomicGateError: `candidate_p_tp` não positivo, ou
            `n_candidate` não positivo (mesmas guardas de
            `required_lift`/`required_lift_stderr` em
            `src.analysis.economic_gate`).
    """
    if not (candidate_p_tp > 0.0):
        raise EconomicGateError(
            f"candidate_p_tp={candidate_p_tp!r} não é positivo -- gate econômico "
            "indefinido pra um candidato sem nenhum toque de TP"
        )
    if n_candidate <= 0:
        raise EconomicGateError(
            f"n_candidate={n_candidate!r} não é positivo -- sem amostra não há erro estimável"
        )
    candidate_p_tp_stderr = math.sqrt(
        (candidate_p_tp * (1.0 - candidate_p_tp))
        / n_candidate  # noqa: unguarded-ratio -- n_candidate>0 verificado acima
    )
    margin = candidate_p_tp - threshold.breakeven_wr
    return EconomicGateVerdict(
        symbol=threshold.symbol,
        resolution_id=threshold.resolution_id,
        side=side,
        candidate_p_tp=candidate_p_tp,
        candidate_p_tp_stderr=candidate_p_tp_stderr,
        breakeven_wr=threshold.breakeven_wr,
        margin=margin,
        passes=margin > 0.0,
        distinguishable=margin > z * candidate_p_tp_stderr,
        side_matches_threshold=side == threshold.side,
    )


def load_min_alpha_lift_by_combo(
    path: Path = CONFIG_DIR / "min_alpha_lift_by_combo.yaml",
) -> dict[tuple[str, str], GateRow]:
    """Casca -- lê `config/min_alpha_lift_by_combo.yaml` (escrito por
    `src.analysis.economic_gate._gate_yaml`) de volta em `GateRow` por
    `(symbol, resolution_id)`. Schema mapeia 1:1 pros campos de `GateRow`
    (`value`->`required_lift`, `geometria_otima`->`cell_id`,
    `p_tp_base`->`p_tp`, resto por nome).

    Raises:
        EconomicGateError: arquivo ausente, ou uma entrada sem todos os
            campos esperados.
    """
    if not path.exists():
        raise EconomicGateError(
            f"{path} não encontrado -- rode src.analysis.economic_gate."
            "run_economic_gate_report() antes"
        )
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    entries = (raw or {}).get("min_alpha_lift_ptp") or {}
    out: dict[tuple[str, str], GateRow] = {}
    for combo_key, entry in entries.items():
        try:
            symbol, resolution_id = combo_key.split("_", 1)
            ci95_low, ci95_high = entry["ci95"]
            row = GateRow(
                symbol=symbol,
                resolution_id=resolution_id,
                side=str(entry["side"]),
                cell_id=str(entry["geometria_otima"]),
                tp_atr_mult=float(entry["tp_atr_mult"]),
                sl_atr_mult=float(entry["sl_atr_mult"]),
                n_filled=int(entry["n_filled"]),
                atr_median_bps=float(entry["atr_median_bps"]),
                p_tp=float(entry["p_tp_base"]),
                breakeven_wr=float(entry["breakeven_wr"]),
                required_lift=float(entry["value"]),
                required_lift_stderr=float(entry["stderr"]),
                required_lift_ci95_low=float(ci95_low),
                required_lift_ci95_high=float(ci95_high),
            )
        except (KeyError, ValueError) as exc:
            raise EconomicGateError(
                f"{path}: entrada {combo_key!r} malformada -- {exc}"
            ) from exc
        out[(symbol, resolution_id)] = row
    return out


# ============================================================================
# Orquestrador de trial -- /redesign_workflow, 2026-08-27, decisão do
# Manager. Escopo desta rodada: SOFT-FLAG apenas -- nenhuma das duas
# funções abaixo bloqueia treino nem escrita de artefato; `run_layer1_
# sprint`/`run_layer1_sprint_all_combinations` (src/models/pipeline.py)
# as chamam de forma OPT-IN (`use_economic_gate`, default `False`,
# preserva bit-exato). Tornar o gate binding é decisão FUTURA, separada,
# ainda não tomada -- não construída aqui de propósito (B23: não
# antecipar um limiar/comportamento que ninguém decidiu ainda).
# ============================================================================


def lookup_pre_trial_gate(
    symbol: str,
    resolution_id: str,
    *,
    table: Mapping[tuple[str, str], GateRow] | None = None,
) -> GateRow | None:
    """Ponto de injeção zero-IO (`table=`, testável sem disco) -- default
    carrega `load_min_alpha_lift_by_combo()`. `None` (parâmetro OU
    retorno) significa "sem tabela econômica pra esta célula ainda" --
    nunca inventa um `GateRow`, e o caller decide o que fazer (hoje: só
    logar, nunca pular a célula -- ver módulo `pipeline.py`)."""
    resolved = table if table is not None else load_min_alpha_lift_by_combo()
    return resolved.get((symbol, resolution_id))


def suggested_n_lifetime_delta(*, trained: bool) -> int:
    """`1` se um treino real aconteceu nesta chamada, `0` caso contrário --
    mesma definição de "trial" já usada no cabeçalho de `audit/
    n_lifetime.yaml` (recompute de fit/backtest genuíno = 1 trial).
    **NUNCA escreve em `audit/n_lifetime.yaml`** -- o ledger é mantido à
    mão por decisão do Manager (nenhum código escreve nele hoje); esta
    função só devolve o número pra aparecer num campo de relatório/log,
    pra um humano revisar e registrar manualmente. Não confundir "sugerir
    um número" com "contabilizar" -- a definição formal de trial pra
    rodadas multi-célula (`run_layer1_sprint_all_combinations`, 15 combos
    de uma vez) segue em aberto (D-14, `src/models/pipeline.py`) e esta
    função não a resolve, só soma o caso mais simples (1 chamada = 1
    treino, se treinou)."""
    return 1 if trained else 0
