"""Fragilidade de ordenação — quanta da ordenação que este projeto usa para
decidir é distinguível de ruído (`AG-246`).

**Por que este módulo existe.** Em 2026-08-25 três módulos independentes
mostraram a mesma assinatura, cada um por um caminho próprio:

- `AG-235-ADDENDUM-2` — o ranking de células de geometria (`tp`/`sl`) do S1
  não sobrevive à troca de resolução: `tp=3,0/sl=1,5` é 1º de 5 em R1 e 7º
  de 7 em R3.
- `AG-244` — o `lift` do gate de regime colapsa de `1,0249` para `1,0027`
  quando medido sobre labels sem o viés de fill, com a dispersão caindo pela
  metade.
- `AG-245-ADDENDUM` — o conjunto de features que sobrevive ao filtro de
  ortogonalidade muda entre resoluções (Jaccard R1×R3 de 0,72 a 0,89) e
  entre regimes de label, mantendo a cardinalidade quase idêntica.

Três módulos, mesma fragilidade. A pergunta que este módulo responde é se
isso é defeito de cada um — ou se **a ordenação nunca teve base**, e o que
mudou foi só o instrumento ficar bom o suficiente para mostrar isso.

**A distinção que importa, e que nenhum dos três achados fez.** "O ranking
mudou" e "o ranking era ruído" são afirmações diferentes. Um ranking pode
mudar entre condições porque o efeito real é diferente em cada condição
(informação), ou porque não há efeito e a ordem é sorteada a cada medição
(ruído). Separá-las exige comparar a dispersão ENTRE os itens ordenados
contra a incerteza DE CADA item — que é exatamente o que nenhum dos três
relatórios reporta hoje: todos dão a estimativa pontual e nenhum dá o erro.

**Método.** Nada aqui é bootstrap ou simulação: as duas quantidades saem em
forma fechada dos contadores que os relatórios já persistem.

1. `lift` do gate é uma razão de duas proporções binomiais independentes
   (`n_sl_in_stress/n_sl_total` sobre `n_tp_in_stress/n_tp_total`). O erro
   do log da razão sai pelo método delta — a mesma fórmula do *risk ratio*
   em epidemiologia (Katz et al. 1978), e o IC é simétrico em log, não em
   nível.
2. O S1 persiste média, mínimo e máximo do edge across 10 estratos, mas não
   o desvio. A amplitude estima o desvio por `sigma = range / d2(n)`, o
   estimador clássico de carta de controle (Tippett 1925) — menos eficiente
   que o desvio amostral, mas é o que o dado permite, e é conservador no
   sentido certo: superestima levemente sigma para distribuições de cauda
   mais leve que a normal.

Núcleo puro (Idioma A, §Núcleo funcional): as funções de cálculo não tocam
disco. A casca (`run_ordering_fragility_report`) resolve arquivo e delega.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import structlog

logger = structlog.get_logger(__name__)

EXPERIMENTS_DIR: Final[Path] = Path("experiments")

#: z para IC bilateral de 95% — quantil 0,975 da normal padrão.
_Z_95: Final[float] = 1.959964  # noqa: magic-number -- quantil normal, não parâmetro de negócio

#: `d2(n)` — fator de correção de amplitude para estimar `sigma` a partir do
#: range de uma amostra normal de tamanho `n` (Tippett 1925; tabelado em
#: qualquer texto de controle estatístico de processo). Só os `n` que este
#: projeto de fato produz; `n` fora da tabela levanta em vez de interpolar,
#: porque interpolar aqui inventaria precisão que a tabela não tem (B23).
_D2_BY_N: Final[dict[int, float]] = {
    # Constantes MATEMATICAS tabeladas (E[range]/sigma de uma normal, por
    # tamanho de amostra) -- nao sao parametro de negocio e nao podem ir para
    # constants.yaml, porque nao sao escolha de ninguem: muda-las seria erro
    # de transcricao, nao decisao de projeto. Mesmo tratamento de _Z_95 acima;
    # o marcador nas linhas seguintes existe so para o lint local.
    2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704,  # noqa: magic-number
    8: 2.847, 9: 2.970, 10: 3.078, 11: 3.173, 12: 3.258,  # noqa: magic-number
}


@dataclass(frozen=True, slots=True)
class RatioCI:
    """IC de uma razão de proporções. `excludes_one` é o que interessa: se
    False, esta célula não é distinguível de "sem efeito"."""

    point: float
    ci_low: float
    ci_high: float
    log_se: float
    excludes_one: bool


def log_ratio_ci(
    k1: int, n1: int, k2: int, n2: int, *, z: float = _Z_95
) -> RatioCI | None:
    """IC da razão `(k1/n1) / (k2/n2)` pelo método delta sobre o log.

    `Var(log p̂) ≈ (1-p)/(n·p)`, e as duas proporções são independentes, então
    as variâncias somam. O IC é construído em log e exponenciado — por isso
    é assimétrico em nível, que é o correto para uma razão (o intervalo de
    uma razão não pode ser simétrico em torno do ponto sem admitir valores
    negativos).

    Devolve `None` se qualquer contagem for zero: o log da razão não existe,
    e substituir por uma correção de continuidade (somar 0,5) mudaria a
    estimativa pontual sem que ninguém tivesse decidido isso.
    """
    if k1 <= 0 or k2 <= 0 or n1 <= 0 or n2 <= 0 or k1 > n1 or k2 > n2:
        return None
    p1, p2 = k1 / n1, k2 / n2
    var = (1.0 - p1) / (n1 * p1) + (1.0 - p2) / (n2 * p2)
    se = math.sqrt(var)
    log_r = math.log(p1 / p2)
    lo, hi = math.exp(log_r - z * se), math.exp(log_r + z * se)
    return RatioCI(
        point=p1 / p2, ci_low=lo, ci_high=hi, log_se=se,
        excludes_one=(lo > 1.0 or hi < 1.0),
    )


def sigma_from_range(range_value: float, n: int) -> float:
    """`sigma` estimado pela amplitude: `range / d2(n)`."""
    if n not in _D2_BY_N:
        raise ValueError(
            f"sigma_from_range: d2 não tabelado para n={n} "
            f"(disponíveis: {sorted(_D2_BY_N)}). Interpolar inventaria "
            "precisão que a tabela não tem."
        )
    if range_value < 0.0:
        raise ValueError(f"sigma_from_range: range negativo ({range_value})")
    return range_value / _D2_BY_N[n]


def separation_ratio(means: Sequence[float], se_of_mean: Sequence[float]) -> float:
    """Razão sinal/ruído de uma ORDENAÇÃO: dispersão entre itens sobre a
    incerteza típica de cada item.

    `>> 1` significa que os itens estão realmente separados e a ordem carrega
    informação. `<= 1` significa que a distância entre os itens é da ordem do
    erro com que cada um foi medido — ordenar é ordenar ruído.

    Usa o desvio POPULACIONAL dos meios (os itens são a população de
    interesse, não uma amostra dela) e a média quadrática dos erros-padrão.
    """
    k = len(means)
    if k < 2 or len(se_of_mean) != k:
        return float("nan")
    mu = sum(means) / k
    spread = math.sqrt(sum((m - mu) ** 2 for m in means) / k)
    noise = math.sqrt(sum(s * s for s in se_of_mean) / k)
    return spread / noise if noise > 0 else float("inf")


def kendall_tau_b(a: Sequence[float], b: Sequence[float]) -> float:
    """Kendall tau-b entre duas ordenações dos MESMOS itens (trata empates).

    `tau = 0` é o valor esperado sob independência — se duas medições da
    mesma grandeza em condições diferentes dão `tau ~ 0`, a ordem não se
    reproduz.
    """
    n = len(a)
    if n < 2 or len(b) != n:
        return float("nan")
    conc = disc = ties_a = ties_b = 0
    for i in range(n):
        for j in range(i + 1, n):
            da, db = a[i] - a[j], b[i] - b[j]
            # um par empatado nos DOIS conta em ties_a E em ties_b -- nao sao
            # ramos exclusivos. Errar isso infla o denominador e comprime |tau|
            # em direcao a zero, que aqui seria o pior erro possivel: faria uma
            # ordenacao reprodutivel parecer ruido. Pego por
            # test_kendall_tau_trata_empates_sem_estourar.
            if da == 0:
                ties_a += 1
            if db == 0:
                ties_b += 1
            if da == 0 or db == 0:
                continue
            if (da > 0) == (db > 0):
                conc += 1
            else:
                disc += 1
    total = n * (n - 1) // 2
    den = math.sqrt((total - ties_a) * (total - ties_b))
    return (conc - disc) / den if den > 0 else float("nan")


# ---------------------------------------------------------------------------
# Casca — resolve arquivos e delega ao núcleo acima
# ---------------------------------------------------------------------------


def _analisa_gate(path: Path) -> dict[str, Any]:
    d = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    por_res: dict[str, Any] = {}
    rank_por_res: dict[str, dict[str, float]] = {}
    for blk in d["by_resolution"]:
        rid = blk["resolution_id"]
        cells, sig = [], 0
        for r in blk["results"]:
            ci = log_ratio_ci(
                r["n_sl_in_stress"], r["n_sl_total"],
                r["n_tp_in_stress"], r["n_tp_total"],
            )
            if ci is None:
                continue
            chave = f"{r['symbol']}|{r['side']}"
            cells.append((chave, ci))
            sig += int(ci.excludes_one)
        if not cells:
            continue
        rank_por_res[rid] = {c: ci.point for c, ci in cells}
        means = [ci.point for _, ci in cells]
        # SE em nivel ~ point * log_se (delta method de volta ao nivel)
        ses = [ci.point * ci.log_se for _, ci in cells]
        por_res[rid] = {
            "n_celulas": len(cells),
            "n_significativas_ic95": sig,
            "lift_medio": sum(means) / len(means),
            "separation_ratio": separation_ratio(means, ses),
            "exemplo_ic": {
                "celula": cells[0][0],
                "lift": round(cells[0][1].point, 4),
                "ic95": [round(cells[0][1].ci_low, 4), round(cells[0][1].ci_high, 4)],
            },
        }
    taus = {}
    rids = sorted(rank_por_res)
    for i, a in enumerate(rids):
        for b in rids[i + 1:]:
            comuns = sorted(set(rank_por_res[a]) & set(rank_por_res[b]))
            if len(comuns) >= 2:
                taus[f"{a}x{b}"] = kendall_tau_b(
                    [rank_por_res[a][c] for c in comuns],
                    [rank_por_res[b][c] for c in comuns],
                )
    return {"por_resolucao": por_res, "kendall_tau_entre_resolucoes": taus}


def _analisa_s1(paths: dict[str, Path]) -> dict[str, Any]:
    por_res: dict[str, Any] = {}
    rank: dict[str, dict[str, float]] = {}
    for rid, p in paths.items():
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        agg = d["aggregate_by_cell"]
        itens = list(agg.items()) if isinstance(agg, dict) else [
            (f"tp{v['tp_atr_mult']}_sl{v['sl_atr_mult']}", v) for v in agg
        ]
        means, ses, chaves = [], [], []
        for k, v in itens:
            n = v.get("n_estratos_symbol_side")
            if n != 10:
                continue
            rng = v["edge_atr_units_max_across_strata"] - v["edge_atr_units_min_across_strata"]
            sigma = sigma_from_range(rng, n)
            chaves.append(k)
            means.append(v["edge_atr_units_mean_across_strata"])
            ses.append(sigma / math.sqrt(n))
        if len(means) < 2:
            continue
        rank[rid] = dict(zip(chaves, means, strict=True))
        # quantas celulas sao distinguiveis da MELHOR?
        melhor = max(range(len(means)), key=lambda i: means[i])
        distinguiveis = sum(
            1 for i in range(len(means))
            if i != melhor
            and abs(means[melhor] - means[i]) > _Z_95 * math.sqrt(ses[melhor] ** 2 + ses[i] ** 2)
        )
        por_res[rid] = {
            "n_celulas_cobertura_completa": len(means),
            "separation_ratio": separation_ratio(means, ses),
            "se_tipico_da_media": sum(ses) / len(ses),
            "spread_entre_celulas": max(means) - min(means),
            "n_distinguiveis_da_melhor_ic95": distinguiveis,
            "n_comparacoes": len(means) - 1,
        }
    taus = {}
    rids = sorted(rank)
    for i, a in enumerate(rids):
        for b in rids[i + 1:]:
            comuns = sorted(set(rank[a]) & set(rank[b]))
            if len(comuns) >= 2:
                taus[f"{a}x{b}"] = kendall_tau_b(
                    [rank[a][c] for c in comuns], [rank[b][c] for c in comuns]
                )
    return {"por_resolucao": por_res, "kendall_tau_entre_resolucoes": taus}


def run_ordering_fragility_report(*, out_dir: Path = EXPERIMENTS_DIR) -> Path:
    """Casca — lê os relatórios em disco, aplica o núcleo, persiste."""
    gate_path = out_dir / "gate_efficiency_report.json"
    s1_paths = {r: out_dir / f"s1_tp_sl_sensitivity_report_{r}.json" for r in ("R1", "R2", "R3")}

    payload: dict[str, Any] = {
        "gap_id": "AG-246",
        "pergunta": (
            "A ordenacao que este projeto usa para decidir (celulas de geometria, "
            "lift do gate de regime) e distinguivel de ruido?"
        ),
        "gate_efficiency": _analisa_gate(gate_path) if gate_path.exists() else None,
        "s1_geometria": _analisa_s1(s1_paths),
    }
    out = out_dir / "ordering_fragility_report.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out)
    logger.info("analysis.ordering_fragility.done", report_path=str(out.resolve()))
    return out


if __name__ == "__main__":
    run_ordering_fragility_report()
