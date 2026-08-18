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

    Levanta `ValueError` se não houver nenhum estado real após excluir
    `ignore_value` (ex. `raw_state_id` inteiro é warmup) — não inventa um
    resultado vazio silencioso."""
    if raw_state_id.shape != response.shape:
        raise ValueError(
            "canonicalize_states: raw_state_id/response precisam do mesmo shape "
            f"(raw_state_id={raw_state_id.shape}, response={response.shape})"
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
        mean_by_raw_state[state] = float(np.mean(state_response))
        # ddof=0 (variância populacional) -- consistente entre estados com
        # tamanhos de amostra diferentes, sem viés de correção de grau de
        # liberdade afetando o desempate.
        var_by_raw_state[state] = float(np.var(state_response, ddof=0))

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
