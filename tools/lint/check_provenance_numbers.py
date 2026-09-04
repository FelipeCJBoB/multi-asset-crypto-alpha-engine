"""Lint AG-440 — números citados na PROSA de `source:` que divergem do
`value:` da constante que a prosa referencia.

**Por que existe.** Numa única sessão (2026-09-03/04) apareceram TRÊS
proveniências obsoletas, todas do mesmo formato: o texto de `source:`
argumenta a partir de um número que já não é o valor vigente.

  1. `round_trip_cost_bps` (`src/features/groups/group_e.py`) justifica o
     `maker_prob` citando "tp_atr_mult=2,0/sl_atr_mult=1,5, distâncias
     assimétricas, P(TP primeiro)=1,5/3,5≈42,9%" — mas `tp_atr_mult` vale
     1,5 desde 2026-08-24, a geometria é SIMÉTRICA e P(TP) medido é ~49%.
  2. `adverse_selection_wr_cost_per_bp` (`config/constants.yaml`) deriva
     seu valor "sobre TP 2,0×ATR / SL 1,5×ATR" — mesma geometria morta.
  3. `cpcv_embargo_ms` registra a ressalva "`max_feature_lookback_ms`
     NÃO cabeado em nenhum caller real de produção ainda" — mas está
     cabeado em `src/models/pipeline.py` e em
     `src/models/hyperparams_optuna.py` desde AG-032 item 8.

Três em uma sessão não é coincidência: é a ausência de teste sobre a
prosa. O `value:` tem lint (`check_constants_provenance.py`); o texto que
o justifica não tinha nenhum.

**O que este lint faz.** Para cada constante de `config/constants.yaml`,
varre o `source:` procurando padrões `nome_de_constante` seguido de um
número (nas formas `nome=1,5`, `nome = 1.5`, `nome vale 1,5`, `nome de
1,5`). Quando o nome citado É uma constante conhecida do próprio arquivo,
compara o número citado com o `value:` real dela. Divergência = violação.

**O que ele NÃO faz, deliberadamente.** Não tenta interpretar prosa livre
nem validar afirmação sobre código (o caso 3 acima não é pegável por
regex — fica como revisão humana). Cobre a classe MAIS COMUM e mais
mecânica: número citado ao lado do nome da constante. Um lint que tenta
adivinhar demais vira ruído e é desligado; este erra pra menos.

Uso:

    python tools/lint/check_provenance_numbers.py
    python tools/lint/check_provenance_numbers.py --strict   # exit 1 se houver violação
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONSTANTS_PATH = _REPO_ROOT / "config" / "constants.yaml"

#: Tolerância relativa ao comparar número citado com `value:`. Não é
#: parâmetro de domínio — é folga de ARREDONDAMENTO de prosa: um texto que
#: escreve "0,494" pra um valor 0,4942 está correto, não obsoleto.
_TOL_REL = 0.02

#: Formas de citação que o lint reconhece. Deliberadamente conservador:
#: exige o nome da constante GRUDADO no número por um conector curto.
_CITACAO = re.compile(
    r"\b(?P<nome>[a-z][a-z0-9_]{3,})\b"
    r"\s*(?:=|==|:|\bvale\b|\bde\b|\bem\b)\s*"
    # captura o token numérico INTEIRO e deixa a desambiguação
    # milhar-vs-decimal para `_to_float` — tentar decidir aqui, no regex,
    # foi a origem de um bug real: a alternativa de milhar casava o prefixo
    # `0,000` de `0,0002` e devolvia 0.
    r"(?P<num>-?\d[\d.,]*\d|-?\d)",
    re.IGNORECASE,
)

#: Marcadores de citação HISTÓRICA deliberada. Um `source:` que narra a
#: evolução de uma constante ("era 0,0284", "valor anterior", "substitui")
#: cita o número ANTIGO de propósito — sinalizar isso seria ruído, e um
#: lint ruidoso é desligado. Procurados na janela imediatamente ANTES da
#: citação. Medido na primeira execução deste lint: sem esta supressão,
#: 4 dos 6 achados eram citação histórica legítima (67% de falso positivo).
_MARCADORES_HISTORICOS: tuple[str, ...] = (
    "era ",
    "eram ",
    "antes",
    "anterior",
    "antigo",
    "antiga",
    "até ",
    "ate ",
    "substitui",
    "obsolet",
    "legado",
    "rodada 1",
    "rodada 2",
    "históric",
    "historic",
    "deixou de",
    "passou de",
    "mudou de",
    "vinha de",
    # construções de PASSADO em pt-br. "foi medido sob X=v" / "foi derivado
    # de X=v" narram a história corretamente -- foram os 2 últimos falsos
    # positivos antes desta adição, ambos em textos que JÁ declaravam a
    # mudança na frase seguinte.
    "foi ",
    "foram ",
)

#: Janela de contexto inspecionada antes da citação. Curta de propósito: o
#: marcador tem que estar na MESMA oração, senão um `source:` longo o
#: bastante suprimiria tudo e o lint viraria decorativo.
_JANELA_CONTEXTO = 90  # noqa: magic-number -- heurística de lint, não parâmetro de domínio


#: Janela DEPOIS da citação. Em pt-br o marcador tanto precede quanto
#: sucede o número ("era 2,0" mas também "2,0 era o valor até o sweep").
#: Menor que a janela anterior de propósito: a construção pós-citada é
#: sempre curta, e uma janela grande depois suprimiria demais.
_JANELA_POSTERIOR = 40  # noqa: magic-number -- heurística de lint, não parâmetro de domínio


def _e_citacao_historica(prosa: str, inicio: int, fim: int) -> bool:
    """`True` quando a citação é cercada por marcador que a declara
    histórica. Olha ANTES e DEPOIS: `X=2,0 era o valor antigo` é tão
    histórico quanto `era X=2,0` — caso real que fez este lint sinalizar
    uma proveniência correta na primeira versão. Ver
    `_MARCADORES_HISTORICOS`."""
    antes = prosa[max(0, inicio - _JANELA_CONTEXTO) : inicio].lower()
    depois = prosa[fim : fim + _JANELA_POSTERIOR].lower()
    return any(m in antes or m in depois for m in _MARCADORES_HISTORICOS)


def _to_float(bruto: str) -> float | None:
    """Aceita `1,5`, `1.5`, `28.800.000` e `1,597,035`. Separador de MILHAR
    e separador DECIMAL convivem no mesmo arquivo (texto em pt-br com
    números de código em en-us), então a desambiguação é posicional: se o
    último separador deixa exatamente 3 dígitos à direita E há mais de um
    separador, é milhar."""
    t = bruto.strip().rstrip(".,")
    if not t:
        return None
    # só milhar: 28.800.000 / 1,597,035. O grupo inicial NÃO pode ser 0 --
    # sem essa guarda, `0,494` (decimal) casa como milhar e vira 494.
    if re.fullmatch(r"-?[1-9]\d{0,2}(?:[.,]\d{3})+", t):
        return float(re.sub(r"[.,]", "", t))
    # milhar + decimal, separadores DIFERENTES: 1.597.035,42
    m = re.fullmatch(r"(-?[1-9]\d{0,2}(?:([.,])\d{3})+)([.,])(\d+)", t)
    if m is not None and m.group(2) != m.group(3):
        return float(re.sub(r"[.,]", "", m.group(1)) + "." + m.group(4))
    # decimal simples: 1,5 / 0,0002 / 1.5
    if re.fullmatch(r"-?\d+[.,]\d+", t):
        return float(t.replace(",", "."))
    if re.fullmatch(r"-?\d+", t):
        return float(t)
    return None


def _valores(doc: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for nome, bloco in doc.items():
        if not isinstance(bloco, dict) or "value" not in bloco:
            continue
        v = bloco["value"]
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[nome] = float(v)
    return out


def _violacoes(doc: dict[str, Any]) -> list[tuple[str, str, float, float, str]]:
    valores = _valores(doc)
    achados: list[tuple[str, str, float, float, str]] = []
    for nome, bloco in doc.items():
        if not isinstance(bloco, dict):
            continue
        prosa = bloco.get("source")
        if not isinstance(prosa, str):
            continue
        for m in _CITACAO.finditer(prosa):
            citado = m.group("nome")
            if citado not in valores or citado == nome:
                continue
            if _e_citacao_historica(prosa, m.start(), m.end()):
                continue
            num = _to_float(m.group("num"))
            if num is None:
                continue
            real = valores[citado]
            # zero exige comparação absoluta; o resto, relativa
            if real == 0.0:
                divergiu = abs(num) > _TOL_REL
            else:
                divergiu = abs(num - real) / abs(real) > _TOL_REL
            if divergiu:
                # trecho ao redor: sem ele, localizar a citação num `source:`
                # de 40 linhas é busca manual -- e um lint que dá trabalho
                # pra agir é um lint que não é acionado.
                ini = max(0, m.start() - 70)
                trecho = " ".join(prosa[ini : m.end() + 40].split())
                achados.append((nome, citado, num, real, trecho))
    return achados


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true", help="exit 1 quando houver violação")
    ap.add_argument("--path", type=Path, default=_CONSTANTS_PATH)
    args = ap.parse_args(argv)

    if not args.path.exists():
        print(f"check_provenance_numbers: {args.path} não existe — nada a verificar.")
        return 0

    doc = yaml.safe_load(args.path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        print("check_provenance_numbers: constants.yaml não é um mapeamento — abortando.")
        return 1

    achados = _violacoes(doc)
    if not achados:
        print("check_provenance_numbers: nenhuma citação numérica divergente na prosa.")
        return 0

    print(f"check_provenance_numbers: {len(achados)} citação(ões) divergente(s):\n")
    for onde, citado, num, real, trecho in achados:
        print(
            f"  [{onde}] a prosa cita `{citado}={num:g}` mas o `value:` vigente é {real:g}"
            f"  (tolerância {_TOL_REL:.0%})"
        )
        print(f"      ...{trecho}...")
    print(
        "\nCada uma é proveniência OBSOLETA: o texto argumenta a partir de um número "
        "que mudou. Corrija o texto (nunca o value pra fazer o lint passar) ou, se a "
        "citação for histórica de propósito, deixe explícito no texto que é o valor ANTIGO."
    )
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
