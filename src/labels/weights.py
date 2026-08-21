"""Pesos por unicidade (§3.5, AFML cap. 4) — concorrência pontual, unicidade
média por label, `sample_weight` normalizado para média 1.

**B24 — proibido estipular `N_eff` por fórmula fechada** (tamanho da
amostra dividido pelo horizonte, ou `1+s(2h-1)`). Este módulo MEDE a
concorrência ponto a ponto (varredura tipo AFML `numCoEvents`/
`avgUniqueness`) e soma `uniqueness` real — `N_eff = Σ uniqueness` é lido
do resultado, nunca calculado por atalho fechado.

**Concorrência/unicidade calculadas POR LADO** (`side=+1`/`side=-1`
separadamente), porque cada lado alimenta um modelo binário distinto
(M_long/M_short, B18) com seu próprio conjunto de treino/CPCV — overlap
entre uma aposta long e uma aposta short no mesmo `t0` não é a mesma
redundância estatística que overlap entre duas apostas do MESMO lado.
`sample_weight`, porém, é normalizado para média 1 sobre o dataset
COMBINADO (os dois lados juntos), porque a invariante §3.8
(`sample_weight.mean() ≈ 1`) é verificada sobre `labels.parquet` inteiro —
um arquivo só, não um por lado.

**Índice de concorrência = a própria série de `t0`, não um grid de tempo
físico.** Cada linha do lado (`side` fixo) tem exatamente um `t0` (uma
barra de 15m produz um label por lado); a posição de um label na série
ordenada por `t0` FAZ o papel do `closeIdx` do AFML — inclui gaps reais de
dado de graça (um gap não conta como "barras vazias" na concorrência,
porque simplesmente não existe posição pra ele no índice)."""

from __future__ import annotations

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]

logger = structlog.get_logger(__name__)


def compute_concurrency_and_uniqueness(t0: IntArray, t1: IntArray) -> tuple[IntArray, FloatArray]:
    """`t0`/`t1` (epoch ms, ou qualquer unidade inteira monotonicamente
    comparável) já ORDENADOS por `t0` ascendente, um label por posição —
    exatamente a ordem em que `triple_barrier.build_labels` emite as linhas
    de um mesmo lado.

    Para cada label `i` (posição `i` no array), o intervalo `[t0_i, t1_i]`
    "ocupa" as posições `[i, idx1_i]`, onde `idx1_i` é a última posição `j`
    tal que `t0_j <= t1_i` (busca binária — `np.searchsorted`). Isso é
    literalmente "quantos OUTROS labels começam antes de `t1_i` terminar",
    a definição de concorrência do AFML cap. 4, calculada sobre o índice
    real dos dados (não um grid físico reconstruído).

    Retorna `(concurrency, uniqueness)`, ambos alinhados posicionalmente a
    `t0`/`t1` de entrada: `concurrency[i]` = quantos labels cobrem a
    posição `i` (a própria `t0` do label `i`); `uniqueness[i]` = média de
    `1/concurrency` sobre todas as posições que o label `i` ocupa.

    Achado de auditoria (`project_assurance`, 2026-08-15): a precondição
    "`t0` já ordenado" era só documentada, nunca validada -- se violada,
    `np.searchsorted` (que assume array ordenado) devolve `idx1` sem
    sentido silenciosamente, sem erro, produzindo `uniqueness` plausível
    mas ERRADO. Essa validação mora aqui (não só no chamador de M2) porque
    esta função também é a fronteira real usada por `apply_weights` pra
    calcular `sample_weight` de produção (`07b_PESOS`) -- um bug de
    ordenação silencioso aqui corrompe peso de treino do modelo, não só
    uma métrica de diagnóstico. Custo da checagem é O(n), desprezível
    frente ao `O(n log n)` do `searchsorted` logo abaixo."""
    n = t0.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)
    if n > 1 and np.any(np.diff(t0) < 0):
        raise ValueError(
            "compute_concurrency_and_uniqueness: t0 precisa estar ordenado "
            "ascendente -- precondição documentada, agora validada (achado "
            "de auditoria 2026-08-15); um t0 desordenado produziria "
            "uniqueness silenciosamente errado via np.searchsorted, não um "
            "erro óbvio"
        )

    idx0 = np.arange(n)
    idx1 = np.searchsorted(t0, t1, side="right") - 1
    idx1 = np.clip(idx1, 0, n - 1)
    idx1 = np.maximum(idx1, idx0)  # t1 > t0 (invariante §3.8) garante isso, clip só por segurança

    # Array de diferenças — soma 1 no início do intervalo ocupado, subtrai 1
    # logo após o fim. `cumsum` reconstrói a concorrência por posição em
    # O(n), sem materializar uma matriz indicadora n x n.
    diff = np.zeros(n + 1, dtype=np.int64)
    np.add.at(diff, idx0, 1)
    np.add.at(diff, idx1 + 1, -1)
    concurrency = np.cumsum(diff[:n]).astype(np.int64)

    # Achado de auditoria (audit_engineering, 2026-08-15) --
    # `check_unguarded_ratios.py` aponta as duas divisões abaixo como sem
    # guarda de sinal explícita; ambas são estruturalmente seguras, provado
    # por construção (não por suposição):
    # 1) `concurrency[i] >= 1` para TODO `i` em [0, n-1]: `idx0 = arange(n)`
    #    cobre cada posição exatamente uma vez, então o label `i` sempre
    #    contribui `+1` em `diff[i]` (sua própria posição). O `-1`
    #    correspondente só acontece em `diff[idx1_i + 1]`, e `idx1_i >=
    #    idx0_i = i` é GARANTIDO pelo `np.maximum(idx1, idx0)` logo acima --
    #    ou seja, o `-1` de um label nunca chega antes da posição `i` no
    #    `cumsum`. Toda posição `i` inclui pelo menos a contribuição de si
    #    mesma quando o `cumsum` passa por ela -- `concurrency` nunca é <=0.
    # 2) `span = idx1 - idx0 + 1 >= 1` pela MESMA garantia `idx1 >= idx0`
    #    (linha acima, `np.maximum`) -- nunca zero.
    reciprocal = 1.0 / concurrency.astype(np.float64)  # noqa: unguarded-ratio -- concurrency[i]>=1 sempre, prova acima
    prefix = np.concatenate((np.zeros(1, dtype=np.float64), np.cumsum(reciprocal)))
    span = (idx1 - idx0 + 1).astype(np.float64)
    uniqueness = (prefix[idx1 + 1] - prefix[idx0]) / span  # noqa: unguarded-ratio -- span=idx1-idx0+1>=1 sempre, prova acima
    # `uniqueness` é matematicamente uma média de 1/concorrência, sempre em
    # (0, 1] — o `clip` só absorve ruído de ponto flutuante da soma
    # acumulada (`cumsum`/subtração de prefixos), medido até ~1e-14 acima
    # de 1.0 em dado real, nunca um erro de lógica.
    uniqueness = np.clip(uniqueness, 0.0, 1.0)

    return concurrency, uniqueness


def apply_weights(labels: pl.DataFrame) -> pl.DataFrame:
    """Adiciona `concurrency`, `uniqueness` (por lado) e `sample_weight`
    (`uniqueness * |ret_net|`, normalizado para média 1 sobre o dataset
    COMBINADO — ver docstring do módulo) a `labels` (schema pré-pesos de
    `triple_barrier._PRE_WEIGHT_SCHEMA`, colunas `side`/`t0`/`t1`/`ret_net`
    obrigatórias). Levanta `ValueError` se QUALQUER linha individual de
    `uniqueness * |ret_net|` for não-finita (achado de auditoria
    `audit_engineering`, 2026-08-15 — ver comentário no corpo da função),
    OU se a média for zero/não-finita — dataset degenerado (ex.: todo
    `ret_net` == 0), não é possível normalizar para média 1 sem dividir por
    zero, e um `sample_weight` silenciosamente `NaN`/`inf` seria pior do
    que falhar alto."""
    if labels.is_empty():
        return labels.with_columns(
            pl.Series("concurrency", [], dtype=pl.Int16),
            pl.Series("uniqueness", [], dtype=pl.Float64),
            pl.Series("sample_weight", [], dtype=pl.Float64),
        )

    parts: list[pl.DataFrame] = []
    for side_value in sorted(labels["side"].unique().to_list()):
        subset = labels.filter(pl.col("side") == side_value).sort("t0")
        t0_ms = subset["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        t1_ms = subset["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        concurrency, uniqueness = compute_concurrency_and_uniqueness(t0_ms, t1_ms)
        subset = subset.with_columns(
            pl.Series("concurrency", concurrency).cast(pl.Int16),
            pl.Series("uniqueness", uniqueness).cast(pl.Float64),
        )
        parts.append(subset)

    out = pl.concat(parts, how="vertical")

    raw_weight = (out["uniqueness"] * out["ret_net"].abs()).to_numpy()
    # Achado de auditoria (audit_engineering, 2026-08-15): a versão anterior
    # usava `np.nanmean(raw_weight)` aqui. `nanmean` só emite warning/produz
    # NaN quando TODAS as entradas são não-finitas (confirmado contra a doc
    # oficial do numpy) -- se só ALGUMAS linhas forem NaN/inf (ex.: um
    # `ret_net` corrompido upstream numa única linha), `nanmean` calcula a
    # média das demais SILENCIOSAMENTE, o guard de `mean_w` abaixo passa
    # normal, e a divisão `raw_weight / mean_w` propaga NaN só NAQUELA
    # linha para `sample_weight` -- exatamente o "silenciosamente NaN/inf"
    # que a docstring desta função diz querer evitar, sem na prática evitar.
    # `assert_label_invariants` (triple_barrier.py) pegaria isso via
    # `np.mean` comum (que propaga NaN em vez de ignorar) -- AG-029
    # (commit a9d5d80, 2026-08-16) ligou essa checagem no caminho real de
    # escrita (`backfill_multi_symbol.build_and_write_labels_for_symbol`
    # chama `assert_label_invariants` entre `build_labels_for_symbol` e
    # `write_labels_atomic`, "falha alto de propósito"), então esta função
    # NÃO é mais a única linha de defesa. Continua sendo uma linha de
    # defesa ADICIONAL que vale a pena manter: `apply_weights` roda ANTES
    # de `assert_label_invariants` no pipeline real (calcula `sample_
    # weight`, que a invariante depois valida) -- sem esta validação aqui,
    # um `ret_net`/`uniqueness` corrompido upstream produziria um
    # `sample_weight` NaN/inf que só seria pego alguns passos depois (ou,
    # em qualquer caminho de teste/uso direto de `apply_weights` que não
    # passe por `build_and_write_labels_for_symbol`, nunca seria pego).
    # Validar TODAS as entradas antes de usar a média, não só a média
    # agregada, continua sendo o comportamento certo aqui mesmo com a
    # invariante downstream já existindo.
    if raw_weight.size and not np.isfinite(raw_weight).all():
        n_bad = int((~np.isfinite(raw_weight)).sum())
        raise ValueError(
            f"apply_weights: {n_bad}/{raw_weight.size} linha(s) de "
            "uniqueness*|ret_net| não-finita(s) (NaN/inf) -- provável "
            "ret_net ou uniqueness corrompido upstream; um sample_weight "
            "silenciosamente NaN/inf seria pior do que falhar alto"
        )
    mean_w = float(np.mean(raw_weight)) if raw_weight.size else 0.0
    if not np.isfinite(mean_w) or mean_w <= 0.0:
        raise ValueError(
            f"apply_weights: média de uniqueness*|ret_net| = {mean_w!r} — dataset "
            "degenerado (ex.: todo ret_net == 0), não é possível normalizar "
            "sample_weight para média 1 sem dividir por zero"
        )
    sample_weight = raw_weight / mean_w
    out = out.with_columns(pl.Series("sample_weight", sample_weight, dtype=pl.Float64))
    out = out.sort(["side", "t0"])

    # `.to_numpy()` antes do `int()` -- mesmo motivo de
    # `assert_label_invariants` (triple_barrier.py): o retorno agregado de
    # `pl.Series.min()`/`.max()` é uma união ampla nos stubs de tipo do
    # polars (mypy strict reclama de `int(...)` direto sobre ela).
    concurrency_arr = out["concurrency"].to_numpy()
    logger.info(
        "labels.weights.applied",
        n_rows=out.height,
        n_sides=len(parts),
        mean_raw_weight=mean_w,
        concurrency_min=int(concurrency_arr.min()),
        concurrency_max=int(concurrency_arr.max()),
    )
    return out
