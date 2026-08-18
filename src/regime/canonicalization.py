"""Canonicalização determinística de estados brutos — M4 (`PRD_V4_1.md`
§3.2), banned pattern B21 (`CLAUDE.md`: "determinístico por quantis;
dynamax na V1.1" — a exigência de determinismo se aplica a QUALQUER
classificador não-determinístico por natureza, não só ao HMM que motivou
a regra original).

**Por que isto existe como módulo próprio, não inline em cada
classificador**: HMM (EM), Jump Model (coordinate descent) e BOCPD
(agrupamento de segmento por quantil) produzem rótulos de estado BRUTOS
cujo número (0, 1, 2, ...) não carrega significado nenhum — é arbitrário
por construção (dois fits do mesmo HMM com seeds diferentes podem rotular
o mesmo estado real como "0" numa rodada e "2" noutra). Historicamente foi
exatamente esse tipo de rótulo instável entre fits/seeds que motivou banir
`hmmlearn` (B21). Canonicalizar UMA vez, num lugar só, reusado pelos 3
candidatos novos, garante que o defeito banido não reapareça duplicado (e
com pequenas divergências de critério) em 3 implementações separadas.

**Critério (`PRD_V4_1.md` §3.2 M4, literal):** "estados ordenados de forma
determinística (média de retorno, desempate por variância)" — ordem
ASCENDENTE: estado com menor retorno médio vira `0`, o de maior vira
`k-1`; em empate exato de média, desempate por variância ASCENDENTE
(menor variância primeiro)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class CanonicalizationResult:
    """`canonical_id`: mesmo shape/alinhamento posicional de `raw_state_id`
    de entrada, valores remapeados para `0..k-1` (ou `-1` nas posições que
    eram `ignore_value`, preservado sem remapear). `mapping`: dicionário
    `raw_state_id -> canonical_id`, só para os estados que de fato
    apareceram em `raw_state_id` (não inclui `ignore_value`).
    `mean_by_raw_state`/`var_by_raw_state`: estatísticas usadas para
    ordenar, chaveadas pelo rótulo BRUTO original — preservadas no
    resultado para auditoria (provar o critério de ordenação sem
    recalcular)."""

    canonical_id: IntArray
    mapping: dict[int, int]
    mean_by_raw_state: dict[int, float]
    var_by_raw_state: dict[int, float]


def canonicalize_states(
    raw_state_id: IntArray,
    response: FloatArray,
    *,
    ignore_value: int | None = None,
) -> CanonicalizationResult:
    """Núcleo puro, sem IO. `raw_state_id` e `response` precisam do mesmo
    shape, alinhados posicionalmente 1:1 (mesmo contrato de alinhamento já
    usado em `src.features._sources`/`src.regime.classifier`).

    `response` é a série de retorno (ou métrica) usada para ordenar — para
    o candidato de regime real ela é o log-retorno de 1 barra à frente
    (`PRD_V4_1.md` M4, item 2 do plano), mas esta função não sabe disso:
    é agnóstica ao significado de `response`, só ordena por ela. Reusada
    também para BOCPD (`bocpd.segments_to_canonical_states`, que primeiro
    reduz segmento->barra e então chama esta função) e, futuramente, para
    qualquer classificador novo que precise do mesmo critério.

    `ignore_value` (ex. `-1` para warmup/estado não atribuído): posições
    com esse valor em `raw_state_id` são excluídas do cálculo de
    média/variância E do remapeamento — saem em `canonical_id` com o
    mesmo `ignore_value`, nunca remapeadas para um estado real (evita a
    classe de bug "warmup vira estado 0 por acidente de ordenação").
    PRECISA ser negativo (`ValueError` caso contrário) -- `canonical_id`
    de estado real sempre começa em `0` e vai até `k-1`; um `ignore_value
    >= 0` colidiria em silêncio com um `canonical_id` real sempre que `k`
    for grande o bastante (`k` é descoberto a partir do dado, varia por
    chamada) -- a mesma ambiguidade de rótulo que este módulo existe pra
    eliminar (B21), só que reintroduzida pelo sentinela em vez do fit.

    `NaN`/`Inf` em `response`: filtrados POR ESTADO antes de calcular
    média/variância (mesmo padrão de `anova_by_group` em
    `src.validation.regime_utility` — `finite_mask = np.isfinite(...)`),
    nunca propagados pro critério de ordenação. Achado real (auditoria
    M4, `PRD_V4_1.md` §3.2): sem este filtro, um único `NaN` em
    `response` faz a média daquele estado virar `NaN`, e comparação
    Python (`sorted()`) com chave `NaN` não é uma ordem total válida —
    QUEBRA a invariância a permutação do rótulo bruto (o teste central
    deste módulo, `test_invariante_a_permutacao_do_rotulo_bruto`) de
    forma silenciosa, sem levantar exceção. Não é hipotético: o próprio
    docstring do módulo documenta que, "para o candidato de regime
    real", `response` é o log-retorno de 1 barra à FRENTE — que tem
    `NaN` estrutural na última barra de qualquer série/fold (mesma razão
    documentada em `src.validation.regime_utility`: "não existe
    close[t+1]"). Posições com `response` não-finito continuam presentes
    em `raw_state_id`/`canonical_id` (não são removidas do output, só
    excluídas do cálculo de média/variância daquele estado) — o mapeamento
    raw->canonical se aplica a TODAS as ocorrências do estado, finitas ou
    não. Levanta `ValueError` se algum estado ficar com zero observações
    finitas em `response` (ordenação indefinida pra esse estado — mesmo
    espírito de "não inventa resultado vazio silencioso" abaixo).

    Levanta `ValueError` se não houver nenhum estado real após excluir
    `ignore_value` (ex. `raw_state_id` inteiro é warmup) — não inventa um
    resultado vazio silencioso."""
    if raw_state_id.shape != response.shape:
        raise ValueError(
            "canonicalize_states: raw_state_id/response precisam do mesmo shape "
            f"(raw_state_id={raw_state_id.shape}, response={response.shape})"
        )
    if ignore_value is not None and ignore_value >= 0:
        raise ValueError(
            "canonicalize_states: ignore_value precisa ser negativo (ex. -1) -- "
            "canonical_id de estado real sempre começa em 0, um ignore_value >= 0 "
            f"colidiria com um canonical_id válido; recebeu ignore_value={ignore_value!r}"
        )

    valid_mask = raw_state_id != ignore_value if ignore_value is not None else np.ones_like(
        raw_state_id, dtype=np.bool_
    )
    unique_states = np.unique(raw_state_id[valid_mask])
    if unique_states.size == 0:
        raise ValueError(
            "canonicalize_states: nenhum estado real após excluir ignore_value "
            f"({ignore_value!r}) — raw_state_id inteiro é ignore_value?"
        )

    mean_by_raw_state: dict[int, float] = {}
    var_by_raw_state: dict[int, float] = {}
    for state in unique_states.tolist():
        state_response = response[raw_state_id == state]
        # NaN/Inf excluídos do cálculo de média/variância (não da ordenação
        # em si -- só das ESTATÍSTICAS deste estado) -- ver docstring da
        # função, "NaN/Inf em response". Mesma filtragem de anova_by_group.
        finite_state_response = state_response[np.isfinite(state_response)]
        if finite_state_response.size == 0:
            raise ValueError(
                f"canonicalize_states: estado bruto {state!r} não tem nenhuma "
                "observação finita em response (todas NaN/Inf) -- ordenação "
                "indefinida para este estado"
            )
        mean_by_raw_state[state] = float(np.mean(finite_state_response))
        # ddof=0 (variância populacional) -- consistente entre estados com
        # tamanhos de amostra diferentes, sem viés de correção de grau de
        # liberdade afetando o desempate.
        var_by_raw_state[state] = float(np.var(finite_state_response, ddof=0))

    # Ordenação estável: média ascendente, desempate por variância
    # ascendente. `sorted()` do Python é estável -- em empate exato de
    # AMBOS os critérios (caso degenerado, praticamente nunca em dado
    # real com float), a ordem final cai pro rótulo bruto original, não
    # aleatória entre execuções -- determinismo preservado até no
    # caso de borda.
    ordered_raw_states = sorted(
        unique_states.tolist(),
        key=lambda s: (mean_by_raw_state[s], var_by_raw_state[s]),
    )
    mapping = {raw: canonical for canonical, raw in enumerate(ordered_raw_states)}

    canonical_id = np.where(
        valid_mask,
        np.vectorize(lambda s: mapping.get(int(s), -1))(raw_state_id),
        raw_state_id if ignore_value is None else ignore_value,
    ).astype(np.int64)

    return CanonicalizationResult(
        canonical_id=canonical_id,
        mapping=mapping,
        mean_by_raw_state=mean_by_raw_state,
        var_by_raw_state=var_by_raw_state,
    )


__all__ = ["CanonicalizationResult", "canonicalize_states"]
