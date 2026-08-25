"""Guardrail de governança — a grade de decisão de `analysis/` (`AG-233`).

**Por que este arquivo existe.** A grade canônica de produção é dollar bar
(R1/R2/R3) desde `AG-042` (2026-08-16, `canonical_bar_type: dollar`). A
migração fechou o core, mas não foi propagada aos consumidores de
`analysis/` — e isso ficou invisível por nove dias, até uma pergunta direta
do Manager expor o padrão. O custo real já foi medido, não é hipotético:

- `AG-232`/`AG-235` — o S1, que DECIDE `tp_atr_mult`/`sl_atr_mult` (classe
  A), varria a grade de relógio. A decisão registrada em `constants.yaml`
  citava uma medição feita na grade errada.
- `AG-238` — o M6 produziu o `I² = 96–98%` citado como evidência de escopo
  multi-ativo. Na grade de produção o `I²` é 61–83%, e a leitura por lado
  **inverte** (no 15m o SHORT era o lado neutro; em R1/R2/R3 é o pior).

O objetivo aqui não é proibir a string `"15m"` — `m2`/`m3` existem para
comparar grades, e o S1/M6 mantêm o caminho de relógio de propósito, como
caminho legado bit-exato, para que a comparação histórica continue
possível. O objetivo é que **nenhum módulo NOVO** entre nessa condição sem
alguém decidir explicitamente, transformando um achado de auditoria em erro
de build.

Mecanismo: whitelist congelada. Cada entrada carrega o motivo. Um módulo
que passe a tocar a grade de relógio sem estar aqui quebra o build; tirar um
módulo daqui exige migrá-lo de verdade.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "src" / "analysis"

# Padrões que caracterizam "este módulo lê a grade de RELÓGIO 15m".
# `load_bars_15m` em si NÃO é o defeito (`AG-233`): `load_bars()` despacha
# corretamente por `bar_source`. O que este teste vigia é o módulo de
# DECISÃO que a chama sem passar pela grade de produção.
PADROES_GRADE_RELOGIO = (
    re.compile(r"15m/v1/labels"),
    re.compile(r"\bload_bars_15m\b"),
    re.compile(r"""DECISION_TF\s*=\s*["']15m["']"""),
)

# ---------------------------------------------------------------------------
# Whitelist — congelada em 2026-08-25. Motivo obrigatório por entrada.
# ---------------------------------------------------------------------------
# Permitidos POR DESENHO: comparar grades é a função deles. Ficam isentos
# mesmo que hoje não casem nenhum padrão — a permissão é sobre o propósito do
# módulo, não sobre o estado do código num dia específico. Por isso não entram
# na checagem de entrada morta.
POR_DESENHO: dict[str, str] = {
    "m2_bar_comparison.py": (
        "compara tipos de barra (relógio x dollar) — ler 15m É o propósito"
    ),
    "m3_timeframe_choice.py": (
        "compara timeframes de relógio entre si — ler 15m É o propósito"
    ),
}

# Descrevem o ESTADO ATUAL do repo: cada entrada sai daqui quando o módulo
# parar de tocar a grade de relógio. São estas que a checagem de entrada morta
# vigia.
POR_ESTADO: dict[str, str] = {
    # Migrados: rodam sobre R1/R2/R3 via `--resolution-id`. O caminho 15m
    # permanece como default legado, preservado bit-exato de propósito, para
    # que a comparação com o resultado histórico continue possível.
    "s1_tp_sl_sensitivity.py": (
        "MIGRADO (AG-232/AG-235) — roda sobre R1/R2/R3; caminho 15m mantido "
        "como legado bit-exato para comparação histórica"
    ),
    "m6_common_factor_hypothesis.py": (
        "MIGRADO (AG-238) — roda sobre R1/R2/R3; caminho 15m mantido como "
        "legado bit-exato para comparação histórica"
    ),
    # NÃO migrado — débito aberto, registrado para não passar por legítimo.
    "faixa2_e2_research.py": (
        "DÉBITO ABERTO (AG-233) — ainda não migrado. Está aqui para o build "
        "não quebrar, NÃO porque seja legítimo. Qualquer conclusão deste "
        "módulo sobre produção precisa ser relida sob R1/R2/R3 antes de ser "
        "citada em decisão."
    ),
}

# União — é o que o guardrail de intruso consulta. Um módulo isento por
# qualquer uma das duas vias não quebra o build.
LEGITIMOS: dict[str, str] = {**POR_DESENHO, **POR_ESTADO}


def _modulos_que_leem_grade_de_relogio() -> dict[str, list[str]]:
    achados: dict[str, list[str]] = {}
    for py in sorted(ANALYSIS_DIR.glob("*.py")):
        texto = py.read_text(encoding="utf-8", errors="replace")
        casados = [p.pattern for p in PADROES_GRADE_RELOGIO if p.search(texto)]
        if casados:
            achados[py.name] = casados
    return achados


def test_nenhum_modulo_novo_de_analysis_le_a_grade_de_relogio() -> None:
    """`AG-233` — o conjunto que toca a grade de relógio é fechado.

    Falha se um módulo fora da whitelist passar a lê-la. Corrigir NÃO é
    adicionar o módulo aqui por conveniência: é decidir, e registrar, se ele
    deve rodar sobre `resolution_id` (o caso normal) ou se comparar grades é
    genuinamente o propósito dele (o caso de `m2`/`m3`).
    """
    achados = _modulos_que_leem_grade_de_relogio()
    intrusos = {k: v for k, v in achados.items() if k not in LEGITIMOS}
    assert not intrusos, (
        "Módulo(s) de analysis/ passaram a ler a grade de RELÓGIO 15m sem "
        f"estar na whitelist de AG-233: {intrusos}. A grade canônica de "
        "produção é dollar bar (R1/R2/R3) desde AG-042 — um módulo de decisão "
        "que leia 15m produz conclusão sobre uma grade que não é produção "
        "(foi assim que AG-232 e AG-238 aconteceram). Migre o módulo para "
        "aceitar `resolution_id`, ou registre o motivo em LEGITIMOS."
    )


def test_whitelist_nao_tem_entrada_morta() -> None:
    """A whitelist não pode virar cemitério.

    Vale só para `POR_ESTADO`. Se um módulo foi migrado de vez e não toca
    mais a grade de relógio, a entrada dele sai — senão a lista deixa de
    descrever o repo e o guardrail afrouxa sem ninguém decidir isso.

    `POR_DESENHO` é isento: a permissão de `m2`/`m3` é sobre o propósito do
    módulo (comparar grades), não sobre casar um padrão de texto hoje.
    """
    achados = _modulos_que_leem_grade_de_relogio()
    mortas = sorted(set(POR_ESTADO) - set(achados))
    assert not mortas, (
        f"Entrada(s) de POR_ESTADO na whitelist de AG-233 que não "
        f"correspondem mais ao código: {mortas}. Remova-as — se o módulo foi "
        "migrado de vez, a entrada cumpriu a função e sai."
    )


@pytest.mark.parametrize("modulo", sorted(LEGITIMOS))
def test_toda_entrada_da_whitelist_tem_motivo_declarado(modulo: str) -> None:
    """Whitelist sem motivo é whitelist que ninguém revisa."""
    motivo = LEGITIMOS[modulo].strip()
    assert len(motivo) >= 40, (
        f"{modulo}: motivo curto demais ({motivo!r}). Declare POR QUE este "
        "módulo pode ler a grade de relógio — comparar grades é o propósito, "
        "é caminho legado preservado, ou é débito aberto?"
    )


def test_modulos_migrados_expoem_resolution_id() -> None:
    """`AG-232`/`AG-238` — um módulo marcado MIGRADO tem que ter, de fato, o
    caminho de produção.

    Sem isto, "MIGRADO" na whitelist seria só uma afirmação em comentário. O
    teste confere contra o código.
    """
    for nome, motivo in LEGITIMOS.items():
        if "MIGRADO" not in motivo:
            continue
        texto = (ANALYSIS_DIR / nome).read_text(encoding="utf-8", errors="replace")
        assert "resolution_id" in texto, (
            f"{nome} está marcado MIGRADO na whitelist de AG-233 mas não "
            "menciona `resolution_id` — ou a migração não aconteceu, ou a "
            "whitelist está mentindo."
        )
        assert "--resolution-id" in texto, (
            f"{nome} está marcado MIGRADO mas não expõe `--resolution-id` na "
            "CLI — o caminho de produção precisa ser alcançável por quem roda "
            "o módulo, não só pela API interna."
        )
