"""ADR-008 Fase 4 — walk-forward real sobre o Alpha (fecha o Item 6 da
`ADR-007`). `generate_anchored_walk_forward_splits`
(`src.validation.volatility_walkforward`) já existe pro M1 (comparação de
estimadores de volatilidade formula-fechada, causais por construção, sem
`fit` de modelo nenhum — por isso nunca precisou de purge por `t1`).
Reusado aqui pro Alpha, que AJUSTA um LightGBM real sobre o treino de cada
fold — diferente do M1, a fronteira treino/teste passa a carregar risco de
vazamento por `t1` (B09) que não existia lá: sem purge, uma barra de
TREINO cujo `t1` (fim da barreira tripla) cai DENTRO ou DEPOIS do início
do bloco de TESTE tem seu label determinado por preço que só existe no
futuro em relação ao corte de treino.

`walk_forward_split_to_cpcv_split` — adaptador fino: `WalkForwardSplit`
(índices por trimestre civil ancorado) -> `CPCVSplit` (o contrato mínimo
que `alpha.run_fold` de fato lê — só `train_idx`/`test_idx`/`split_id`/
`path_id`, ver docstring de `run_fold`; os outros 5 campos de `CPCVSplit`
nunca são tocados por `run_fold`). Escrever um adaptador fino em vez de
generalizar a assinatura de `run_fold` (a alternativa que o ADR-008
também considerava) evita qualquer edição na função mais testada do
motor — zero risco novo pra ela.

**Achado real (execução real contra `BTCUSDT/R2`, não hipotético):**
`generate_anchored_walk_forward_splits` exige `open_time_ms` estritamente
crescente (`np.searchsorted`), mas `mf.data`/`labels` (o `df_all` que
`alpha.run_fold` de fato fatia) tem DUAS linhas por barra — uma por lado
(`side=1`/`side=-1`, mesma garantia de `labels.parquet` já documentada em
`alpha._unique_test_bars`) — `t0` REPETE e não é globalmente monótono.
Por isso os índices de `WalkForwardSplit` (posições numa timeline
ÚNICA/ordenada, `unique_t0_ms`, gerada pelo chamador via `np.unique`) são
traduzidos aqui em FRONTEIRAS DE TEMPO (timestamp), aplicadas como filtro
booleano sobre `t0_ms`/`t1_ms` do `df_all` de 2 linhas/barra — nunca como
posição direta (as duas timelines têm tamanhos diferentes). Mesmo idioma
de `src.validation.cpcv.generate_splits`, que já resolve purge por
comparação de VALOR (`t0_ms`/`t1_ms`), não por posição.

Campos de `CPCVSplit` sem equivalente sob uma única fronteira cronológica
contígua (CPCV tem grupos combinatórios espalhados no tempo, com purge E
embargo nos dois sentidos; walk-forward ancorado tem só 1 fronteira, teste
sempre estritamente POSTERIOR ao treino, nunca embaralhado) — documentados
como vazio/zero abaixo, não improvisados: `test_groups=()`,
`train_groups=()`, `path_id=0`, `n_embargoed=0`."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from src.validation.cpcv import CPCVSplit
from src.validation.volatility_walkforward import WalkForwardSplit

IntArray = NDArray[np.int64]


def walk_forward_split_to_cpcv_split(
    wf_split: WalkForwardSplit,
    unique_t0_ms: IntArray,
    t0_ms: IntArray,
    t1_ms: IntArray,
) -> CPCVSplit:
    """`unique_t0_ms` — timeline ÚNICA e ordenada de `t0` (1 valor por
    barra, `np.unique` sobre o `t0` de `df_all`) usada pra GERAR
    `wf_split` (`generate_anchored_walk_forward_splits` exige índice
    estritamente crescente). `t0_ms`/`t1_ms` — arrays paralelos ao
    `df_all` REAL de 2 linhas/barra que `alpha.run_fold` vai fatiar
    (mesma convenção de `alpha._temporal_purged_calib_split`: núcleo
    puro, a extração de `df_all["t0"]`/`df_all["t1"]` fica a cargo do
    chamador, computada uma vez fora do loop de folds).

    Purge (B09, mesmo idioma de `_temporal_purged_calib_split`): descarta
    do treino toda linha cujo `t1` ainda esteja ABERTO quando o bloco de
    teste começa. Levanta `ValueError` se o purge esvaziar o treino
    inteiro — fold degenerado, falha alta em vez de treinar sobre 0
    linhas."""
    n_unique = unique_t0_ms.shape[0]
    test_start_time = int(unique_t0_ms[wf_split.test_start_idx])
    # `test_end_idx` pode ser o comprimento da timeline única (último
    # fold, "até o fim da série") -- sem entrada em `unique_t0_ms` pra
    # ler; `t0_ms.max() + 1` fecha o intervalo à direita sem excluir a
    # última barra real (comparação é `< test_end_time`, exclusiva).
    test_end_time = (
        int(unique_t0_ms[wf_split.test_end_idx])
        if wf_split.test_end_idx < n_unique
        else int(t0_ms.max()) + 1
    )

    train_candidates = np.flatnonzero(t0_ms < test_start_time)
    keep = t1_ms[train_candidates] < test_start_time
    train_idx = train_candidates[keep]
    if train_idx.shape[0] == 0:
        raise ValueError(
            "walk_forward_split_to_cpcv_split: purge por t1 esvaziou o treino do "
            f"fold_id={wf_split.fold_id} (test_start_time={test_start_time}) -- fold "
            "degenerado, horizonte de label cobre todo o prefixo de treino"
        )
    test_idx = np.flatnonzero((t0_ms >= test_start_time) & (t0_ms < test_end_time))
    return CPCVSplit(
        split_id=wf_split.fold_id,
        path_id=0,
        test_groups=(),
        train_groups=(),
        train_idx=train_idx,
        test_idx=test_idx,
        n_train_candidate=int(train_candidates.shape[0]),
        n_purged=int(train_candidates.shape[0] - train_idx.shape[0]),
        n_embargoed=0,
    )
