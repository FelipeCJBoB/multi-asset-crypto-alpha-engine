"""F6 — Ablação (D-12) — `docs/meta_model_design_doc_2026-08-22.md` §9.

**É o único teste que distingue "o Meta seleciona" de "o Meta reduz
exposição".** Quatro braços: `A0` (Alpha sem filtro), `A1` (Alpha + Meta),
`A2` (nulo — filtro aleatório com a MESMA busca), `A3` (Alpha + top-k por
`p_alpha`, pareado em pass-rate — vira GATE, não só braço informativo).

**Pré-condição bloqueante (§9, travada a priori): o controle positivo
sintético (§4.3, `meta_dataset.run_leakage_positive_control`) precisa ter
passado antes de qualquer resultado deste módulo ser interpretável.** Não
é reverificado aqui — é responsabilidade do chamador confirmar que já
rodou (mesma disciplina de "receber o objeto, não confiar na ordem" do
§4.7); rodar F6 sem essa garantia não é erro de código, é decisão do
Manager de pular uma trava, e não deveria acontecer em silêncio.

## O nulo A2, com a decisão do Manager (2026-08-31) sobre `meta_logit_c`

O §9 lista 5 "escolhas de A1 que consomem grau de liberdade contra o
dado" e que precisam ser replicadas em A2 pela mesma função de busca
(`_search_and_fit`). Decisão do Manager sobre o item 2 (`meta_logit_c`):
**`C` fica FIXO** (lido de `constants.yaml`, nunca buscado em-fold) — não
existe infraestrutura de busca em-fold pra `C` no F4 (`LogitL2Meta` usa
sempre o valor único da constante), e construir uma somaria uma decisão
de grade/critério não especificada no design doc a um mecanismo já
delicado. Consequência: A1 e A2 usam o MESMO `C` fixo — a "replicação" do
item 2 é trivial (nenhuma diferença possível entre os dois), não uma
lacuna.

Isso simplifica os outros 4 itens da tabela do §9 também: (1) `tau_meta`
sobre a grade de quantis — a ÚNICA busca genuinamente em-fold que resta,
já implementada em `meta.resolve_tau_meta`; (3) `meta_include_nofill_in_
training` — constante GLOBAL, lida uma vez por `meta_dataset.build_meta_
signal_table`, não por fold — A1 e A2 partilham o MESMO `meta_training_
set`, logo a mesma decisão, trivial; (4) `p_alpha` vs. `score_alpha_raw`
— os dois JÁ entram no design matrix (§3.4, hierarquia corrigida), não é
uma escolha binária feita em runtime; (5) descarte de coluna por posto —
`meta.check_design_rank` já roda dentro de `build_design_matrix`, que A1
e A2 chamam da MESMA forma (ver `run_meta_fold`). Sobra genuinamente 1
escolha pra `_search_and_fit` replicar: a resolução de `tau_meta`.

**Mecanismo de A2, decorrente do texto do §9** ("A1 e A2 compartilham a
mesma função de busca `_search_and_fit(scores, ...)`, chamada com
`scores` reais em A1 e com `scores` sorteados em A2"): A1 já ajustou o
modelo — os SCORES REAIS (`p_meta` de treino e de teste) já existem em
`MetaFoldResult.train_predictions`/`test_predictions`. Cada réplica de A2
NÃO reajusta o modelo — embaralha esses scores reais (permutação, dentro
de treino e dentro de teste, independentemente — preserva a separação
estrutural treino/teste que o resto do pipeline garante) e roda `_search_
and_fit` (resolve `tau_meta` + aplica o filtro) sobre o embaralhado. Isso
é mais barato E mais fiel ao texto: "filtro aleatório com a MESMA busca"
é literalmente a mesma função de busca de `tau_meta`, alimentada com
scores que não carregam relação real com o resultado."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from . import meta
from . import meta_dataset as mds
from ._constants import load_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

ACCEPT_A0 = "accept_a0"
ACCEPT_A1 = "accept_a1"
ACCEPT_A3 = "accept_a3"


class MetaAblationError(Exception):
    """Base para erros deste módulo."""


# ============================================================================
# Painel obrigatório por braço (§9)
# ============================================================================


@dataclass(frozen=True, slots=True)
class BranchPanel:
    """Painel obrigatório do §9. Métricas de acerto/retorno são sobre o
    subconjunto ACEITO e PREENCHIDO (`barrier_hit != NOFILL`) — `pass_
    rate`/`fill_rate` são as únicas que olham pro funil inteiro. `base_
    rate_*` é medida sobre TODO o universo de sinais preenchidos (não só
    o aceito por este braço) — é o "acaso" contra o qual a accuracy do
    braço se compara (§9: accuracy abaixo da taxa base é o sintoma de
    "reduz exposição, não seleciona").

    `exposure_total` é `n_filled` — proxy DECLARADO de contagem de
    trades, não uma medida de capital-tempo em risco (essa exigiria um
    modelo de dimensionamento de posição que este módulo não tem acesso
    a esta altura do pipeline; `TBD` se uma medida mais precisa vier a
    ser necessária, B23)."""

    n_signals: int
    n_accept: int
    pass_rate: float
    n_filled: int
    fill_rate: float
    accuracy_weighted: float
    accuracy_unweighted: float
    base_rate_weighted: float
    base_rate_unweighted: float
    win_rate: float
    mean_ret: float
    std_ret: float
    sharpe_naive: float
    exposure_total: float


def compute_branch_panel(
    table: pl.DataFrame, *, accept_col: str, weight_col: str = "uniqueness_subpop"
) -> BranchPanel:
    """`table` é o universo INTEIRO de sinais do fold/path (não
    pré-filtrado por aceite) — precisa ter `barrier_hit`/`ret_net`/
    `accept_col`/`weight_col`. `accept_col != 0` define o aceito (mesma
    convenção de `side_final`: 0 é sempre rejeição, nunca inversão de
    lado, D-05)."""
    n_signals = table.height
    universo_preenchido = table.filter(pl.col("barrier_hit") != "NOFILL")
    y_universo = (universo_preenchido["ret_net"] > 0.0).cast(pl.Int8).to_numpy().astype(np.float64)
    w_universo = universo_preenchido[weight_col].to_numpy().astype(np.float64)
    base_rate_unweighted = float(y_universo.mean()) if y_universo.shape[0] > 0 else float("nan")
    base_rate_weighted = (
        float(np.average(y_universo, weights=w_universo))
        if y_universo.shape[0] > 0 and float(w_universo.sum()) > 0.0
        else float("nan")
    )

    aceito = table.filter(pl.col(accept_col) != 0)
    n_accept = aceito.height
    pass_rate = (n_accept / n_signals) if n_signals > 0 else float("nan")  # noqa: unguarded-ratio — guarda inline no ternário

    preenchido = aceito.filter(pl.col("barrier_hit") != "NOFILL")
    n_filled = preenchido.height
    fill_rate = (n_filled / n_accept) if n_accept > 0 else float("nan")  # noqa: unguarded-ratio — guarda inline no ternário

    ret = preenchido["ret_net"].to_numpy().astype(np.float64)
    y = (ret > 0.0).astype(np.float64)
    w = preenchido[weight_col].to_numpy().astype(np.float64)

    win_rate = float(y.mean()) if y.shape[0] > 0 else float("nan")
    accuracy_unweighted = win_rate
    accuracy_weighted = (
        float(np.average(y, weights=w)) if y.shape[0] > 0 and float(w.sum()) > 0.0 else float("nan")
    )
    mean_ret = float(ret.mean()) if ret.shape[0] > 0 else float("nan")
    std_ret = float(ret.std(ddof=1)) if ret.shape[0] > 1 else float("nan")
    sharpe_naive = (mean_ret / std_ret) if std_ret and std_ret > 0.0 else float("nan")  # noqa: unguarded-ratio — guarda inline no ternário

    return BranchPanel(
        n_signals=n_signals,
        n_accept=n_accept,
        pass_rate=pass_rate,
        n_filled=n_filled,
        fill_rate=fill_rate,
        accuracy_weighted=accuracy_weighted,
        accuracy_unweighted=accuracy_unweighted,
        base_rate_weighted=base_rate_weighted,
        base_rate_unweighted=base_rate_unweighted,
        win_rate=win_rate,
        mean_ret=mean_ret,
        std_ret=std_ret,
        sharpe_naive=sharpe_naive,
        exposure_total=float(n_filled),
    )


def jaccard_accept_sets(accept_a: IntArray, accept_b: IntArray) -> float:
    """Jaccard entre os conjuntos ACEITOS de dois braços (posições, não
    valores) — §9: "se alto, o Meta é reparametrização de `tau`, e isso
    tem de aparecer como número". `NaN` se os dois conjuntos forem
    vazios (Jaccard indefinido, não 0 — 0 diria "completamente
    diferentes" quando na verdade não há nada pra comparar)."""
    if accept_a.shape[0] != accept_b.shape[0]:
        raise MetaAblationError(
            f"jaccard_accept_sets: tamanhos diferentes ({accept_a.shape[0]} vs {accept_b.shape[0]})"
        )
    a = accept_a != 0
    b = accept_b != 0
    uniao = int((a | b).sum())
    if uniao == 0:
        return float("nan")
    intersecao = int((a & b).sum())
    return intersecao / uniao


# ============================================================================
# A0 — Alpha sem filtro
# ============================================================================


def build_branch_a0(table: pl.DataFrame) -> pl.DataFrame:
    """A0 — aceita TODO sinal (`accept_a0 = side_hat`, nunca inverte)."""
    return table.with_columns(pl.col("side_hat").alias(ACCEPT_A0))


# ============================================================================
# A2 — nulo: embaralha os SCORES REAIS de A1 (não reajusta o modelo)
# ============================================================================


def _search_and_fit(
    scores_train: FloatArray,
    ret_net_train: FloatArray,
    side_hat_test: IntArray,
    scores_test: FloatArray,
) -> tuple[meta.TauMetaResolution, IntArray]:
    """Núcleo COMPARTILHADO entre A1 e A2 (§9, "a mesma função de
    busca") — resolve `tau_meta` sobre `scores_train` (reais em A1,
    embaralhados em A2) e aplica o filtro a `scores_test`. `run_meta_
    fold` já executa esta mesma sequência inline para A1 (ajuste real);
    esta função existe pra que A2 rode a IDÊNTICA busca sem duplicar a
    lógica de `resolve_tau_meta`/`apply_meta_filter`."""
    tau_res = meta.resolve_tau_meta(scores_train, ret_net_train)
    accept = meta.apply_meta_filter(side_hat_test, scores_test, tau_meta=tau_res.tau_meta)
    return tau_res, accept


def run_a2_null_replicas(
    fold_result: meta.MetaFoldResult,
    *,
    n_seeds: int,
    rng: np.random.Generator,
    weight_col: str = "uniqueness_subpop",
) -> FloatArray:
    """`n_seeds` réplicas do nulo A2 pra UM fold — devolve o array de
    `sharpe_naive` de cada réplica (insumo do p95 do gate). Fold sem
    modelo ajustado (`fold_status != OK`, `train_predictions is None`)
    devolve um array vazio: sem scores reais pra embaralhar, não há
    nulo a construir — a política de pass-through já faz A1==A0 nesse
    fold (ver docstring do módulo), e um nulo degenerado não
    acrescentaria informação."""
    if fold_result.fold_status != mds.META_STATUS_OK or fold_result.train_predictions is None:
        return np.array([], dtype=np.float64)

    train = fold_result.train_predictions
    test = fold_result.test_predictions.filter(pl.col("meta_status") == mds.META_STATUS_OK)
    if test.height == 0:
        return np.array([], dtype=np.float64)

    scores_train_real = train["p_meta"].to_numpy().astype(np.float64)
    ret_net_train = train["ret_net"].to_numpy().astype(np.float64)
    scores_test_real = test["p_meta"].to_numpy().astype(np.float64)
    side_hat_test = test["side_hat"].to_numpy().astype(np.int64)

    sharpes = np.empty(n_seeds, dtype=np.float64)
    for i in range(n_seeds):
        scores_train_shuf = rng.permutation(scores_train_real)
        scores_test_shuf = rng.permutation(scores_test_real)
        _tau_res, accept = _search_and_fit(
            scores_train_shuf, ret_net_train, side_hat_test, scores_test_shuf
        )
        panel = compute_branch_panel(
            test.with_columns(accept_a2=pl.Series(accept)),
            accept_col="accept_a2",
            weight_col=weight_col,
        )
        sharpes[i] = panel.sharpe_naive
    return sharpes


# ============================================================================
# A3 — top-k por p_alpha, pareado em pass-rate no MESMO estrato (§9,
# correção 2: (path_id, meta_split_id, symbol, side_hat), vira GATE
# ============================================================================


def build_branch_a3(table_with_a1: pl.DataFrame) -> pl.DataFrame:
    """A3 — dentro de CADA estrato `(meta_split_id, symbol, side_hat)`,
    aceita as linhas de MAIOR `p_alpha` até igualar o `pass_rate` REAL de
    A1 nesse mesmo estrato — pareamento por estrato (§9, correção 2:
    "`tau_meta` é escolhido por fold, e o pool é multi-símbolo e
    bi-lateral; parear no nível de path não neutraliza concentração em
    folds/símbolos/lados de alto `|ret|`"). `path_id` não entra na chave
    de estrato aqui porque `meta_split_id` já é mais fino que `path_id`
    (cada path agrega 3 `meta_split_id`) — parear no grão mais fino é
    estritamente mais conservador, nunca mais frouxo, que parear em
    `path_id`.

    Requer `accept_a1` já presente (`build_branch_a0`/A1 rodados antes)."""
    if ACCEPT_A1 not in table_with_a1.columns:
        raise MetaAblationError(
            f"build_branch_a3: coluna {ACCEPT_A1!r} ausente — rode A1 antes de A3 "
            "(pareamento de pass-rate depende do pass-rate REAL de A1)."
        )

    partes: list[pl.DataFrame] = []
    for _chave, grupo in table_with_a1.group_by(
        ["meta_split_id", "symbol", "side_hat"], maintain_order=True
    ):
        n = grupo.height
        n_accept_a1 = int((grupo[ACCEPT_A1] != 0).sum())
        if n == 0 or n_accept_a1 == 0:
            partes.append(grupo.with_columns(pl.lit(0, dtype=pl.Int8).alias(ACCEPT_A3)))
            continue
        # ranqueia por p_alpha DESCENDENTE; os top n_accept_a1 viram aceito.
        ordenado = grupo.sort("p_alpha", descending=True).with_row_index("_rank_a3")
        aceito_a3 = (ordenado["_rank_a3"] < n_accept_a1).cast(pl.Int8) * ordenado["side_hat"].cast(
            pl.Int8
        )
        partes.append(ordenado.drop("_rank_a3").with_columns(aceito_a3.alias(ACCEPT_A3)))
    return pl.concat(partes, how="vertical")


# ============================================================================
# Orquestração — 1 combo (symbol, resolution_id, variant), agrega por path
# ============================================================================


@dataclass(frozen=True, slots=True)
class PathAblationResult:
    path_id: int
    n_folds: int
    n_folds_ok: int
    panel_a0: BranchPanel
    panel_a1: BranchPanel
    panel_a3: BranchPanel
    null_sharpes_a2: FloatArray
    p95_null_a2: float
    jaccard_a1_a3: float
    passed: bool


@dataclass(frozen=True, slots=True)
class AblationResult:
    """§9, correção 5: "o writer do artefato de validação recebe
    OBRIGATORIAMENTE o objeto `AblationResult`... e levanta se ausente"
    — este objeto É essa garantia estrutural; nenhum código deste
    projeto grava um veredito de F6 sem passar por aqui primeiro."""

    symbol: str
    resolution_id: str
    variant: str
    path_results: tuple[PathAblationResult, ...]
    n_paths_passed: int
    n_paths_total: int
    min_paths_required: int
    exposure_reduction_suspected: bool
    gate_passed: bool


def _exposure_reduction_suspected(panel_a1: BranchPanel, panel_a0: BranchPanel) -> bool:
    """§9, correção 5 — sinaliza quando A1 reduz exposição SEM melhorar
    discriminação: `accuracy_unweighted` de A1 não supera a taxa base
    (ou seja, não supera o próprio A0 em win rate), mas `pass_rate` caiu
    bastante. Não é o critério do gate (esse é `sharpe` vs. nulo/A3) —
    é um FLAG complementar, o caso concreto do §9 ("accuracy 48%, win
    rate caindo, drawdown -93%: ganho de exposição, zero discriminação")
    materializado como campo, não só prosa."""
    if np.isnan(panel_a1.accuracy_unweighted) or np.isnan(panel_a1.base_rate_unweighted):
        return False
    discrimina = panel_a1.accuracy_unweighted > panel_a1.base_rate_unweighted
    reduziu_exposicao = panel_a1.pass_rate < panel_a0.pass_rate
    return bool(reduziu_exposicao and not discrimina)


def run_ablation_for_combo(
    fold_results: tuple[meta.MetaFoldResult, ...],
    meta_training_set: pl.DataFrame,
    *,
    symbol: str,
    resolution_id: str,
    variant: str,
    n_seeds: int | None = None,
    min_paths_required: int | None = None,
    random_state: int | None = None,
) -> AblationResult:
    """F6 pra UM `(symbol, resolution_id, variant)` — agrega por `path_id`
    (3 `meta_split_id` cada, CPCV de `n_groups=6`/`n_test_groups=2`).

    `fold_results` vem de `meta.run_all_meta_folds` (A1 já embutido);
    `meta_training_set` é a MESMA tabela usada pra gerá-los (`meta_
    dataset.build_meta_signal_table`) — usada aqui só pra reconstruir o
    universo de teste com `symbol`/`p_alpha` (A0/A3 precisam de colunas
    que `MetaFoldResult.test_predictions` já carrega, mas a reconstrução
    explícita evita depender da ordem de concatenação dos folds).

    Path conta como avaliável sse TODOS os seus folds têm `fold_status ==
    OK` (§9, correção 4: "pass-through contaminava a estatística do
    gate" — Sharpe de um path que mistura fold com/sem modelo vira
    ruído). Path com qualquer fold pass-through é reportado (`n_folds_
    ok < n_folds`) mas NUNCA conta como PASS."""
    n_seeds = n_seeds if n_seeds is not None else int(load_constant("alpha_b1_n_seeds"))
    min_paths_required = (
        min_paths_required
        if min_paths_required is not None
        else int(load_constant("alpha_layer1_permanence_min_paths"))
    )
    random_state = (
        random_state if random_state is not None else int(load_constant("alpha_random_seed"))
    )
    rng = np.random.default_rng(random_state)

    # `test_predictions` de cada fold JÁ tem `side_final` — que É `accept_
    # a1` (mesma convenção de D-05: 0 é rejeição, nunca inversão de lado).
    # Não precisa reconstruir por join; só renomear.
    test_all = pl.concat([r.test_predictions for r in fold_results], how="vertical")
    if "symbol" not in test_all.columns:
        test_all = test_all.with_columns(pl.lit(symbol).alias("symbol"))
    universo = build_branch_a0(test_all).rename({"side_final": ACCEPT_A1})
    universo = build_branch_a3(universo)

    path_by_fold = {r.meta_split_id: r.path_id for r in fold_results}
    status_by_fold = {r.meta_split_id: r.fold_status for r in fold_results}
    paths = sorted({r.path_id for r in fold_results})

    path_results: list[PathAblationResult] = []
    for path_id in paths:
        folds_do_path = [fid for fid, pid in path_by_fold.items() if pid == path_id]
        n_folds = len(folds_do_path)
        n_folds_ok = sum(1 for fid in folds_do_path if status_by_fold[fid] == mds.META_STATUS_OK)
        universo_path = universo.filter(pl.col("meta_split_id").is_in(folds_do_path))

        panel_a0 = compute_branch_panel(universo_path, accept_col=ACCEPT_A0)
        panel_a1 = compute_branch_panel(universo_path, accept_col=ACCEPT_A1)
        panel_a3 = compute_branch_panel(universo_path, accept_col=ACCEPT_A3)
        jaccard = jaccard_accept_sets(
            universo_path[ACCEPT_A1].to_numpy(), universo_path[ACCEPT_A3].to_numpy()
        )

        null_sharpes_por_fold = [
            run_a2_null_replicas(
                next(r for r in fold_results if r.meta_split_id == fid), n_seeds=n_seeds, rng=rng
            )
            for fid in folds_do_path
        ]
        null_nao_vazios = [s for s in null_sharpes_por_fold if s.shape[0] > 0]
        # Achado real (2026-08-31, BTCUSDT/R2): um path pode ter TODOS os
        # folds em pass-through (nenhum ajustou modelo) -- `run_a2_null_
        # replicas` devolve vazio pra cada um, `np.concatenate([])`
        # levanta `ValueError` em vez de devolver vazio educadamente.
        null_sharpes = (
            np.concatenate(null_nao_vazios) if null_nao_vazios else np.array([], dtype=np.float64)
        )
        null_validos = null_sharpes[~np.isnan(null_sharpes)]
        # Mesmo percentil do Gate E0 (P0, meta_fp_inventory.py) -- mesmo
        # conceito (p95 do nulo permutado como limiar de decisão), reusado
        # aqui em vez de um literal novo (§16.10, "reusadas" do §11).
        null_percentile = float(load_constant("meta_e0_null_percentile"))
        p95_null = (
            float(np.quantile(null_validos, null_percentile))
            if null_validos.shape[0] > 0
            else float("nan")
        )

        passou = bool(
            n_folds_ok == n_folds
            and not np.isnan(panel_a1.sharpe_naive)
            and not np.isnan(p95_null)
            and not np.isnan(panel_a3.sharpe_naive)
            and panel_a1.sharpe_naive > p95_null
            and panel_a1.sharpe_naive > panel_a3.sharpe_naive
        )
        path_results.append(
            PathAblationResult(
                path_id=path_id,
                n_folds=n_folds,
                n_folds_ok=n_folds_ok,
                panel_a0=panel_a0,
                panel_a1=panel_a1,
                panel_a3=panel_a3,
                null_sharpes_a2=null_sharpes,
                p95_null_a2=p95_null,
                jaccard_a1_a3=jaccard,
                passed=passou,
            )
        )

    n_paths_passed = sum(1 for r in path_results if r.passed)
    panel_a1_geral = compute_branch_panel(universo, accept_col=ACCEPT_A1)
    panel_a0_geral = compute_branch_panel(universo, accept_col=ACCEPT_A0)
    exposure_flag = _exposure_reduction_suspected(panel_a1_geral, panel_a0_geral)

    resultado = AblationResult(
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        path_results=tuple(path_results),
        n_paths_passed=n_paths_passed,
        n_paths_total=len(path_results),
        min_paths_required=min_paths_required,
        exposure_reduction_suspected=exposure_flag,
        gate_passed=bool(n_paths_passed >= min_paths_required and not exposure_flag),
    )
    logger.info(
        "models.meta_ablation.run_ablation_for_combo",
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        n_paths_passed=n_paths_passed,
        n_paths_total=len(path_results),
        min_paths_required=min_paths_required,
        exposure_reduction_suspected=exposure_flag,
        gate_passed=resultado.gate_passed,
    )
    return resultado
