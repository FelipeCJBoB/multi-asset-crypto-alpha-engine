"""ADR-007 Item 4 — correção de múltiplas comparações (resposta direta ao
pedido do Manager, "cuidado com falsos positivos"). Núcleo puro (Idioma A),
sem IO — recebe p-valores já calculados em outro lugar (ex. z-score da
tabela de taxa-base do artefato "Alpha — Base de Pesquisa", H0-H7), nunca
recalcula a estatística de teste em si.

**Por que BH e BY, não Bonferroni** (já descartado em `ADR-007`): Bonferroni
é conservador demais pra 8-15 testes correlacionados (os 3 R1/R2/R3 do
mesmo símbolo não são independentes — vêm do mesmo fluxo de trades e do
mesmo modelo em janelas adjacentes).

**Por que os DOIS métodos, não só BH**: Benjamini-Hochberg (`method="bh"`)
assume independência ou dependência positiva regular (PRDS) entre os
testes — a mesma correlação por símbolo que motivou descartar Bonferroni
também deixa essa premissa do BH não totalmente garantida aqui.
Benjamini-Yekutieli (`method="by"`) controla o FDR sob QUALQUER estrutura
de dependência, ao custo de mais conservador (perde poder). Reportar os
dois, lado a lado, é mais honesto que escolher 1 e esconder a premissa que
ele carrega — mesma disciplina de `hyperparams_optuna.py::ConfirmedCandidate`
(screening vs. mediana lado a lado, nunca só o número que parece melhor)."""

from __future__ import annotations

from dataclasses import dataclass

from scipy.stats import false_discovery_control

from src.models._constants import load_constant


@dataclass(frozen=True, slots=True)
class FdrResult:
    label: str
    p_value_raw: float
    p_value_bh: float
    p_value_by: float
    significant_raw: bool
    significant_bh: bool
    significant_by: bool


def apply_fdr_correction(
    p_values: dict[str, float], *, significance_level: float | None = None
) -> tuple[FdrResult, ...]:
    """`p_values`: `{label: p_valor_bruto}`, testes DE MÃO DUPLA (o chamador
    já deve ter convertido z-score/estatística pra p-valor bilateral antes
    de chamar isto — núcleo puro, não decide qual teste gerou o p-valor).
    `significance_level` (nível de significância desejado — nome da
    literatura de FDR é "alpha", mas colide com o "Alpha" deste projeto,
    ver docstring do módulo) — default `None` resolve de
    `fdr_significance_level` (`constants.yaml`), mesmo padrão sentinela já
    usado em `hyperparams_optuna.py`.

    Ordem de saída = ordem de `p_values` (dict Python 3.7+ preserva
    inserção) — nunca reordenado por p-valor, pra não confundir "ordem de
    processamento do BH" (que É por p-valor, internamente) com "ordem de
    apresentação" (do chamador).

    **Definição operacional de "significativo"** (regra do `CLAUDE.md` —
    "empate" precisa de definição explícita, `AG-114`/`AG-118`/`AG-122` já
    queimaram este projeto uma vez com um limiar sem essa definição):
    `significativo := p_ajustado < significance_level`, ESTRITO — um
    p-valor ajustado EXATAMENTE igual ao limiar (acontece de verdade sob
    BH quando 2+ testes empatam no mesmo ponto de corte da escada, ex.
    `p_adj=0,05` com `significance_level=0,05`) conta como NÃO
    significativo, não o contrário. Escolha deliberada, não a única
    convenção possível na literatura — documentada aqui pra não virar
    ambiguidade resolvida por quem lê o código depois."""
    if not p_values:
        return ()
    alpha = (
        significance_level
        if significance_level is not None
        else float(load_constant("fdr_significance_level"))
    )
    labels = list(p_values.keys())
    raw = [p_values[label] for label in labels]
    adjusted_bh = false_discovery_control(raw, method="bh")
    adjusted_by = false_discovery_control(raw, method="by")
    return tuple(
        FdrResult(
            label=label,
            p_value_raw=p_raw,
            p_value_bh=float(p_bh),
            p_value_by=float(p_by),
            significant_raw=p_raw < alpha,
            significant_bh=float(p_bh) < alpha,
            significant_by=float(p_by) < alpha,
        )
        for label, p_raw, p_bh, p_by in zip(labels, raw, adjusted_bh, adjusted_by, strict=True)
    )


def two_sided_p_from_z(z: float) -> float:
    """`z` de teste padrão-normal (ex. proporção vs. taxa-base, já
    calculado em outro lugar) -> p-valor bilateral. `math.erfc` (não
    `scipy.stats.norm.sf`) — evita puxar `scipy.stats` só pra isso quando
    o chamador já tem `z` pronto; `erfc(|z|/sqrt(2))` é a cauda bilateral
    padrão de uma normal(0,1), identidade de livro-texto, não aproximação."""
    import math

    return math.erfc(abs(z) / math.sqrt(2.0))
