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
como vazio abaixo, não improvisados: `test_groups=()`, `train_groups=()`,
`n_embargoed=0`. `path_id=wf_split.fold_id` (não `0` fixo) É deliberado,
não sobra do vocabulário CPCV: `backtest_lite.backtest_by_path` agrupa
resultado por `path_id` — usar `fold_id` como `path_id` faz cada fold de
walk-forward virar seu próprio "caminho" de 1 fold, reusando essa função
JÁ TESTADA pra métrica por fold (sharpe/win_rate/edge) em vez de duplicar
a lógica de `realize_trades`/agregação aqui."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
import shap
import structlog
from numpy.typing import NDArray

from src.features.build import T1_FEATURE_IDS
from src.validation.cpcv import CPCVSplit
from src.validation.volatility_walkforward import (
    WalkForwardSplit,
    generate_anchored_walk_forward_splits,
)

from . import alpha, backtest_lite, score_quality
from ._constants import load_constant

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]
_BPS_PER_UNIT = 10_000  # mesma constante nomeada de score_quality.py/hyperparams_optuna.py
_MIN_FOLDS_FOR_STD = 2  # noqa: magic-number -- desvio-padrão amostral (ddof=1) exige >=2 pontos
_AGGREGATE_STAT_NAMES: tuple[str, ...] = ("sharpe", "edge_bps", "win_rate")


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
        path_id=wf_split.fold_id,
        test_groups=(),
        train_groups=(),
        train_idx=train_idx,
        test_idx=test_idx,
        n_train_candidate=int(train_candidates.shape[0]),
        n_purged=int(train_candidates.shape[0] - train_idx.shape[0]),
        n_embargoed=0,
    )


def min_trades_for_non_degenerate_fold() -> int:
    """Piso de TRADES REALIZADOS (`PathBacktestResult.n_filled_trades`,
    a população que `sharpe`/`edge_bps`/`win_rate` de fato agregam) pra
    um fold de walk-forward não ser degenerado — critério operacional
    definido a priori (Manager, 2026-08-31, ADR-008 Fase 4): "fold
    degenerado" = `n_filled_trades < min_trades_for_non_degenerate_fold()`.

    **Correção de desenho, achada por execução real (não hipotética) —
    campanha completa sobre os 5 candidatos, `SOLUSDT/R2` fold_id=9,
    2026-08-31.** A primeira versão gateava em `n_test_bars` (a
    população de INFERÊNCIA, pós `alpha.unique_test_bars`) derivando um
    piso de barras via `ceil(MIN_OCCURRENCES_ABOVE_TAU / target_signal_
    rate)` — assumia implicitamente `n_signals ≈ n_test_bars *
    target_signal_rate`. Essa suposição QUEBRA quando a taxa de sinal
    REALIZADA diverge muito da nominal (achado real: fold_id=9 tinha
    `n_test_bars=2097` — bem acima do piso derivado — mas só
    `n_filled_trades=2`, porque `confidence` raramente cruzou `tau`
    nessa janela). `sharpe_naive` não filtra amostra pequena por
    desenho (`_MIN_TRADES_FOR_SHARPE=2` em `backtest_lite.py` só evita
    `ddof=1` sobre <2 pontos, não é piso de confiabilidade) — sobre 2
    trades quase-idênticos, `std` fica perto de zero sem ZERAR, e
    `mean/std` explode (Sharpe=47.163,5 medido, não hipotético).
    Consequência real: o AGREGADO (`mean`) de `SOLUSDT/R2` ficava
    dominado por um único fold com 2 trades (15.720,5 de mean sharpe
    sobre 12 folds -- ~1/12 do valor patológico).

    Gatear direto em `n_filled_trades` (a população REAL da estatística,
    não uma PROJEÇÃO dela) fecha a classe inteira de erro por
    construção, não só o caso medido. Reusa `alpha.MIN_OCCURRENCES_
    ABOVE_TAU` (10 — o mesmo piso de "amostra grande o bastante pra uma
    leitura de cauda ter sentido" já usado por `alpha._resolve_tau_on_
    common_bars`) diretamente, sem conversão via taxa nominal — não há
    mais população intermediária a projetar."""
    return alpha.MIN_OCCURRENCES_ABOVE_TAU


def _aggregate_stats(values: list[float]) -> dict[str, float]:
    """mean/median/std/min/max sobre `values`, `NaN` descartado antes de
    agregar (nunca propagado como se fosse zero) — mesma convenção de
    `backtest_lite.path_dispersion_stats`. `std` exige `>=2` pontos
    finitos (desvio-padrão amostral indefinido com 1 ponto)."""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.shape[0] == 0:
        nan = float("nan")
        return {"n": 0.0, "mean": nan, "median": nan, "std": nan, "min": nan, "max": nan}
    std = (
        float(np.std(finite, ddof=1)) if finite.shape[0] >= _MIN_FOLDS_FOR_STD else float("nan")
    )
    return {
        "n": float(finite.shape[0]),
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "std": std,
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
    }


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _shap_mean_abs_by_feature(
    model: lgb.LGBMClassifier, x_test: alpha.FloatArray, feature_ids: tuple[str, ...]
) -> dict[str, float]:
    """ADR-008 Fase 7 — média de `|SHAP value|` por feature sobre `x_test`
    (`shap.TreeExplainer`, exato pra árvores de decisão, não uma
    aproximação amostrada). Medição real (2026-08-31, `BTCUSDT/R2`
    fold_id=1, 672 linhas × 36 features): 0,005s — custo desprezível
    sobre o treino (0,68s), sem necessidade de orçamento separado.

    `shap_values` pode devolver `list[ndarray]` (1 array por classe —
    contrato de versões antigas do shap pra classificador binário) ou
    um `ndarray` único (a classe positiva direto — o que a versão
    instalada devolve na prática) -- trata os dois formatos, não supõe
    um sem checar."""
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(x_test)
    values = shap_values[1] if isinstance(shap_values, list) else shap_values
    mean_abs = np.abs(values).mean(axis=0)
    return {fid: float(v) for fid, v in zip(feature_ids, mean_abs, strict=True)}


@dataclass(frozen=True, slots=True)
class WalkForwardFoldMetrics:
    fold_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    # Linhas CANDIDATAS ao treino pós-purge, 2 lados somados, ANTES do
    # filtro por lado/R2/warmup (`ds.side_subset` dentro de `alpha.
    # run_fold`) -- correção 2026-08-31 (audit_engineering/ADR-008):
    # renomeado de `n_train_bars` (nome enganoso, não é contagem de
    # barras -- é `cpcv_split.train_idx.shape[0]`, 2 linhas por barra).
    # Informativo (paridade com o log de purge), NUNCA usar pra
    # diagnosticar população real de treino -- usar `n_train_long`/
    # `n_train_short` abaixo pra isso.
    n_train_rows_candidatas: int
    n_purged: int
    n_test_bars: int
    degenerado: bool
    sharpe: float
    edge_bps: float
    win_rate: float
    n_signals: int
    n_filled_trades: int
    # AG-395 -- `tau` é fixado in-fold sobre o treino do lado (`alpha.
    # SideModelResult.tau`, já existente, nunca escolhido por métrica OOS
    # -- ver alpha.py:29-35). Antes calculado e descartado neste módulo
    # (achado de auditoria adversarial externa, docs/prompts/
    # REFUTACAO_CONSOLIDADA_0de20_20260831.md achado N6/roadmap ação 1) --
    # persistido aqui pra permitir medir o gap entre a taxa de sinal
    # ORÇADA (`target_signal_rate`, constante) e a REALIZADA por fold sem
    # precisar re-rodar a campanha. `NaN` quando o fold é degenerado por 0
    # barras de teste válidas (run_fold nunca chamado, nenhum tau existe
    # pra reportar).
    tau_long: float
    tau_short: float
    # `n_signals / n_test_bars` -- taxa de sinal REALIZADA no teste deste
    # fold, pra comparar direto contra `target_signal_rate` (AG-395). NaN
    # se `n_test_bars == 0` (mesmo caso degenerado acima).
    signal_rate_realized: float
    # AG-393 item 3 -- `True` por lado quando `y_calib` daquele fold/lado
    # tinha 1 classe só (`SideModelResult.calib_target_single_class`) --
    # a calibração isotônica colapsou pra uma constante, achado real em
    # SOLUSDT/R2 fold_id=3/short. `{}` (dict vazio) quando o fold é
    # degenerado por 0 barras de teste (run_fold nunca chamado, nenhum
    # `SideModelResult` existe pra reportar).
    calib_degenerate_by_side: dict[str, bool]
    # AG-401 -- piso de trades REALIZADOS aplicado por lado, não só ao
    # fold combinado (`backtest_lite.PathBacktestResult.n_filled_long`/
    # `_short`, novos). Não substitui `degenerado` (continua gateando o
    # agregado de Sharpe/edge_bps/win_rate do fold, ambos os lados juntos
    # -- mudar esse contrato é decisão separada) -- é informação ADICIONAL
    # pra quem quiser saber se um lado específico do fold é confiável.
    # `{}` no fold degenerado por 0 barras de teste (mesmo contrato dos
    # campos acima).
    degenerado_by_side: dict[str, bool]
    # População REAL de treino por lado, pós-filtro (`ds.side_subset`,
    # R2/warmup/NOFILL já aplicados) -- `alpha.FoldResult.n_train_long`/
    # `n_train_short`, calculados por `run_fold` e antes DESCARTADOS
    # aqui (achado de auditoria 2026-08-31, classe "diagnóstico
    # calculado e descartado"). `0` nos 2 quando o fold é degenerado por
    # 0 barras de teste válidas (run_fold nunca chamado, honesto -- não
    # treinou, não tem população de treino a reportar).
    n_train_long: int
    n_train_short: int
    # 1 entrada por lado com trade válido (mesmo contrato de
    # `score_quality.compute_score_quality`) -- lado sem trade fica
    # ausente do dict, não aparece com `NaN`. Mede informação marginal
    # DENTRO da cauda que o modelo já selecionou (confidence>tau E venceu
    # a competição de lado) -- não poder discriminativo populacional, ver
    # `score_quality_full_population_by_side` abaixo (AG-394).
    score_quality_by_side: dict[str, dict[str, Any]]
    # AG-394 (auditoria adversarial externa, prova D1) -- MESMA forma,
    # população DIFERENTE: toda barra de teste com outcome realizado, sem
    # o filtro por `tau`/competição de lado (`score_quality.
    # compute_score_quality_full_population`). As duas colunas nunca
    # devem ser lidas como a mesma pergunta -- ver docstring da função.
    score_quality_full_population_by_side: dict[str, dict[str, Any]]
    # ADR-008 Fase 5 (stability matrix, eixo "decile returns") -- mesmo
    # contrato de ausência: lado com <10 trades fica fora do dict.
    decile_profile_by_side: dict[str, dict[str, Any]]
    # ADR-008 Fase 5 (eixo "feature gain") -- gain BRUTO por coluna
    # deste fold (`SideModelResult.gain_by_column_raw`, já calculado por
    # `fit_side_model`, sem custo adicional). "long"/"short" sempre
    # presentes (o fold sempre treina os 2 lados, diferente de `score_
    # quality_by_side`/`decile_profile_by_side`, que dependem de ter
    # trade OOF -- treinar não exige ter sinalizado).
    gain_by_column_by_side: dict[str, dict[str, float]]
    # ADR-008 Fase 7 -- média de |SHAP value| por feature sobre o bloco
    # de teste do fold (`shap.TreeExplainer`, exato pra árvores de
    # decisão). Mesmo contrato de presença de `gain_by_column_by_side`
    # ("long"/"short" sempre presentes quando o fold treinou) -- eixo
    # COMPLEMENTAR ao gain nativo do booster (SHAP explica CONTRIBUIÇÃO
    # à predição por linha, gain nativo conta uso em split; concordam
    # ou divergem é o que a stability matrix audita).
    shap_mean_abs_by_side: dict[str, dict[str, float]]
    # Meta F6b (docs/meta_model_design_doc_2026-08-22.md Sec4.4) -- as
    # predicoes OOS reais do Alpha deste fold (`alpha.FoldResult.
    # predictions`), so quando `run_walk_forward_for_combo(...,
    # keep_predictions=True)`. `None` por padrao (`keep_predictions=
    # False`, todo chamador existente do ADR-008/ADR-007 nao muda de
    # comportamento) -- o Meta e o UNICO consumidor que precisa das
    # predicoes por fold pra montar sua propria tabela de sinal sobre
    # janelas causais; os consumidores do Alpha (score_quality/SHAP/
    # gain acima) ja leem `fold_result.predictions` direto dentro do
    # loop, sem precisar dele sobrevivendo na estrutura devolvida.
    predictions: pl.DataFrame | None = None


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    symbol: str
    resolution_id: str
    variant: str
    n_folds_total: int
    n_folds_degenerados: int
    n_folds_usados: int
    min_trades_threshold: int
    fold_results: tuple[WalkForwardFoldMetrics, ...]
    aggregate: dict[str, dict[str, float]]
    # P3 do Exhibit VIII ("Caso 0/20") -- `score_quality.
    # compute_train_val_test_gap` sobre os `alpha.FoldResult` reais desta
    # combo (fit/stop/calib in-sample, pooled entre folds por lado).
    # Custo ZERO adicional -- `fold_results_ok` (a lista de `alpha.
    # FoldResult`) já existe em memória pra `backtest_lite.backtest_by_
    # path`, só nunca tinha sido repassada pra essa metrica. Sempre
    # populado (não é opt-in como `keep_predictions` -- não guarda dado
    # OOF nem aumenta o artefato de forma proporcional ao numero de
    # trades, só os 3 sub-splits pooled).
    train_val_test_gap: tuple[dict[str, Any], ...] = ()


def run_walk_forward_for_combo(
    mf_data: pl.DataFrame,
    *,
    symbol: str,
    resolution_id: str,
    variant: str,
    hyper: alpha.LGBMHyperparams,
    seed: int,
    device_type: str = "cpu",
    tau_policy: str = alpha.TAU_POLICY_LEGACY_PER_SIDE,
    calib_split_mode: str = alpha.CALIB_SPLIT_TEMPORAL_PURGED,
    class_balance_basis: str = alpha.CLASS_BALANCE_WEIGHT,
    calib_weight_basis: str = alpha.CALIB_WEIGHT_UNIQUENESS,
    initial_train_years: int | None = None,
    model_id_prefix: str = "walk_forward",
    keep_predictions: bool = False,
) -> WalkForwardResult:
    """Walk-forward real (RETREINO, um `alpha.run_fold` por fold ancorado)
    sobre `mf_data` já carregado pelo chamador — `build_modeling_frame`
    (~20s) fica FORA desta função de propósito, pra ser chamado 1 vez só
    e reusado entre Camada1/Camada0 do mesmo combo (esta função é
    per-`variant`, mesmo padrão de `alpha.run_fold`/`run_all_folds`).

    `initial_train_years=None` (default) resolve pra `constants.yaml::
    m1_walkforward_initial_train_years` (protocolo M1, PRD_V4_1.md §3.2 —
    mesmo valor que `src.regime.build_hmm`/`src.analysis.m4_*` já usam).

    `keep_predictions=False` (default, comportamento IDÊNTICO ao de
    antes desta opção existir) — `True` popula `WalkForwardFoldMetrics.
    predictions` com as predições OOS reais do fold (Meta F6b, §4.4);
    todo chamador do ADR-007/ADR-008 fica exatamente como estava.

    Levanta `ValueError` se `generate_anchored_walk_forward_splits`
    devolver 0 folds (série curta demais) — falha alta, nunca um
    resultado vazio silencioso."""
    initial_train_years_eff = (
        initial_train_years
        if initial_train_years is not None
        else int(load_constant("m1_walkforward_initial_train_years"))
    )
    t0_ms = mf_data["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    t1_ms = mf_data["t1"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    unique_t0_ms = np.unique(t0_ms)
    wf_splits = generate_anchored_walk_forward_splits(
        unique_t0_ms, initial_train_years=initial_train_years_eff
    )
    if not wf_splits:
        raise ValueError(
            f"run_walk_forward_for_combo: {symbol}/{resolution_id} -- 0 folds gerados "
            f"(série curta demais pra initial_train_years={initial_train_years_eff})"
        )

    min_trades = min_trades_for_non_degenerate_fold()
    model_id = f"{model_id_prefix}_{symbol}_{resolution_id}_{variant}"

    def _fold_boundaries_iso(wf_split: WalkForwardSplit) -> tuple[str, str, str, str]:
        test_end_bar_idx = min(wf_split.test_end_idx, unique_t0_ms.shape[0]) - 1
        return (
            _ms_to_iso(int(unique_t0_ms[0])),
            _ms_to_iso(int(unique_t0_ms[wf_split.train_end_idx - 1])),
            _ms_to_iso(int(unique_t0_ms[wf_split.test_start_idx])),
            _ms_to_iso(int(unique_t0_ms[test_end_bar_idx])),
        )

    fold_metrics: list[WalkForwardFoldMetrics] = []
    pending: list[tuple[WalkForwardSplit, CPCVSplit, alpha.FoldResult]] = []
    for wf_split in wf_splits:
        cpcv_split = walk_forward_split_to_cpcv_split(wf_split, unique_t0_ms, t0_ms, t1_ms)
        train_start_iso, train_end_iso, test_start_iso, test_end_iso = _fold_boundaries_iso(
            wf_split
        )

        # Achado real (BTCUSDT/R2, fold_id=2, 2026-08-31, primeira execução
        # real da campanha): um fold com 0 barras de teste válidas
        # (`alpha.unique_test_bars` vazio -- ex. gap de dado real numa
        # feature específica, ver E14f_toptrader_ls_ratio) faz `alpha.
        # run_fold` quebrar dentro do `predict_proba` do LightGBM
        # (`ValueError` de array vazio) DEPOIS de já ter treinado os dois
        # lados -- checar aqui evita o treino desperdiçado e trata como
        # degenerado direto, sem chamar `run_fold`.
        test_bars_check = alpha.unique_test_bars(mf_data[cpcv_split.test_idx])
        if test_bars_check.height == 0:
            logger.warning(
                "models.walk_forward.fold_sem_barra_de_teste_valida",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                fold_id=wf_split.fold_id,
                detail="0 barras de teste com feature valida -- fold pulado (run_fold "
                "quebraria no predict_proba), tratado como degenerado direto",
            )
            fold_metrics.append(
                WalkForwardFoldMetrics(
                    fold_id=wf_split.fold_id,
                    train_start=train_start_iso,
                    train_end=train_end_iso,
                    test_start=test_start_iso,
                    test_end=test_end_iso,
                    n_train_rows_candidatas=int(cpcv_split.train_idx.shape[0]),
                    n_purged=int(cpcv_split.n_purged),
                    n_test_bars=0,
                    degenerado=True,
                    sharpe=float("nan"),
                    edge_bps=float("nan"),
                    win_rate=float("nan"),
                    n_signals=0,
                    n_filled_trades=0,
                    tau_long=float("nan"),
                    tau_short=float("nan"),
                    signal_rate_realized=float("nan"),
                    calib_degenerate_by_side={},
                    degenerado_by_side={},
                    n_train_long=0,
                    n_train_short=0,
                    score_quality_by_side={},
                    score_quality_full_population_by_side={},
                    decile_profile_by_side={},
                    # `run_fold` nunca chamado -- nenhum `SideModelResult`
                    # existe pra este fold, gain/SHAP ficam vazios
                    # (honesto: não treinou, não tem gain/SHAP, não é
                    # `0.0` inventado).
                    gain_by_column_by_side={},
                    shap_mean_abs_by_side={},
                )
            )
            continue

        fold_result = alpha.run_fold(
            mf_data,
            cpcv_split,
            variant=variant,
            hyper=hyper,
            model_id=model_id,
            seed=seed,
            symbol=symbol,
            resolution_id=resolution_id,
            device_type=device_type,
            tau_policy=tau_policy,
            calib_split_mode=calib_split_mode,
            class_balance_basis=class_balance_basis,
            calib_weight_basis=calib_weight_basis,
        )
        pending.append((wf_split, cpcv_split, fold_result))
        logger.info(
            "models.walk_forward.fold_concluido",
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            fold_id=wf_split.fold_id,
            n_folds_total=len(wf_splits),
            n_train_rows_candidatas=int(cpcv_split.train_idx.shape[0]),
            n_train_long=fold_result.n_train_long,
            n_train_short=fold_result.n_train_short,
            n_test_bars=fold_result.n_test_bars,
        )

    fold_results_ok = [fr for _, _, fr in pending]
    by_path = backtest_lite.backtest_by_path(fold_results_ok, mf_data) if fold_results_ok else {}

    for wf_split, cpcv_split, fold_result in pending:
        path_result = by_path.get(cpcv_split.path_id)
        sq = score_quality.compute_score_quality(fold_result.predictions, mf_data)
        sq_by_side = {r.side: asdict(r) for r in sq}
        # AG-394 -- mesma forma, população completa de teste (sem o
        # filtro por tau/competição de lado que `compute_score_quality`
        # aplica). Métrica NOVA, nome distinto por design -- ver
        # docstring de `compute_score_quality_full_population`.
        sq_full = score_quality.compute_score_quality_full_population(
            fold_result.predictions, mf_data
        )
        sq_full_by_side = {r.side: asdict(r) for r in sq_full}
        # ADR-008 Fase 5 -- eixos "decile returns" (mesma população de
        # `sq`, join compartilhado por baixo) e "feature gain" (já
        # calculado por `fit_side_model`, zero custo adicional aqui).
        decile_profile = score_quality.compute_decile_profile(fold_result.predictions, mf_data)
        decile_by_side = {r.side: asdict(r) for r in decile_profile}
        gain_by_side = {
            "long": dict(fold_result.long_result.gain_by_column_raw),
            "short": dict(fold_result.short_result.gain_by_column_raw),
        }
        # ADR-008 Fase 7 -- SHAP (TreeExplainer, exato pra árvores),
        # eixo complementar ao gain nativo. Recomputa `x_test` (o
        # `run_fold` já monta o mesmo internamente pra inferência, mas
        # não o expõe) via as MESMAS 2 funções públicas que ele usa por
        # baixo -- zero edição em `alpha.run_fold`.
        test_bars_unique = alpha.unique_test_bars(mf_data[cpcv_split.test_idx])
        x_test = alpha.build_design_matrix(test_bars_unique)
        shap_by_side = {
            "long": _shap_mean_abs_by_feature(
                fold_result.long_result.model, x_test, T1_FEATURE_IDS
            ),
            "short": _shap_mean_abs_by_feature(
                fold_result.short_result.model, x_test, T1_FEATURE_IDS
            ),
        }
        n_filled_trades = path_result.n_filled_trades if path_result else 0
        # degenerado = poucos TRADES REALIZADOS, não poucas barras de
        # teste (ver docstring de `min_trades_for_non_degenerate_fold` --
        # correção de desenho a partir de execução real, SOLUSDT/R2
        # fold_id=9: sharpe patológico sobre n=2 trades apesar de
        # n_test_bars alto).
        degenerado = n_filled_trades < min_trades
        train_start_iso, train_end_iso, test_start_iso, test_end_iso = _fold_boundaries_iso(
            wf_split
        )
        n_signals_fold = path_result.n_signals if path_result else 0
        fold_metrics.append(
            WalkForwardFoldMetrics(
                fold_id=wf_split.fold_id,
                train_start=train_start_iso,
                train_end=train_end_iso,
                test_start=test_start_iso,
                test_end=test_end_iso,
                n_train_rows_candidatas=int(cpcv_split.train_idx.shape[0]),
                n_purged=int(cpcv_split.n_purged),
                n_test_bars=fold_result.n_test_bars,
                degenerado=degenerado,
                sharpe=path_result.sharpe_naive if path_result else float("nan"),
                edge_bps=(
                    path_result.mean_trade_ret * _BPS_PER_UNIT if path_result else float("nan")
                ),
                win_rate=path_result.win_rate if path_result else float("nan"),
                n_signals=n_signals_fold,
                n_filled_trades=n_filled_trades,
                tau_long=fold_result.long_result.tau,
                tau_short=fold_result.short_result.tau,
                signal_rate_realized=(
                    n_signals_fold / fold_result.n_test_bars  # noqa: unguarded-ratio -- guardado pelo ternario: só divide quando n_test_bars>0
                    if fold_result.n_test_bars > 0
                    else float("nan")
                ),
                calib_degenerate_by_side={
                    "long": fold_result.long_result.calib_target_single_class,
                    "short": fold_result.short_result.calib_target_single_class,
                },
                degenerado_by_side=(
                    {
                        "long": path_result.n_filled_long < min_trades,
                        "short": path_result.n_filled_short < min_trades,
                    }
                    if path_result
                    else {}
                ),
                n_train_long=fold_result.n_train_long,
                n_train_short=fold_result.n_train_short,
                score_quality_by_side=sq_by_side,
                score_quality_full_population_by_side=sq_full_by_side,
                decile_profile_by_side=decile_by_side,
                gain_by_column_by_side=gain_by_side,
                shap_mean_abs_by_side=shap_by_side,
                predictions=(fold_result.predictions if keep_predictions else None),
            )
        )
        if degenerado:
            logger.warning(
                "models.walk_forward.fold_degenerado",
                symbol=symbol,
                resolution_id=resolution_id,
                variant=variant,
                fold_id=wf_split.fold_id,
                n_filled_trades=n_filled_trades,
                min_trades_threshold=min_trades,
                detail="trades realizados insuficientes pra sharpe/edge_bps/win_rate "
                "terem sentido -- fold excluido do agregado, mantido no artefato",
            )

    fold_metrics.sort(key=lambda fm: fm.fold_id)
    usaveis = [fm for fm in fold_metrics if not fm.degenerado]
    stat_lists = {name: [getattr(fm, name) for fm in usaveis] for name in _AGGREGATE_STAT_NAMES}
    per_stat = {name: _aggregate_stats(values) for name, values in stat_lists.items()}
    aggregate = {
        stat_key: {name: per_stat[name][stat_key] for name in _AGGREGATE_STAT_NAMES}
        for stat_key in ("mean", "median", "std", "min", "max")
    }

    train_val_test_gap = tuple(
        asdict(r) for r in score_quality.compute_train_val_test_gap(fold_results_ok)
    )

    logger.info(
        "models.walk_forward.combo_concluido",
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        n_folds_total=len(fold_metrics),
        n_folds_degenerados=len(fold_metrics) - len(usaveis),
        sharpe_mean=aggregate["mean"]["sharpe"],
        edge_bps_mean=aggregate["mean"]["edge_bps"],
    )

    return WalkForwardResult(
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        n_folds_total=len(fold_metrics),
        n_folds_degenerados=len(fold_metrics) - len(usaveis),
        n_folds_usados=len(usaveis),
        min_trades_threshold=min_trades,
        fold_results=tuple(fold_metrics),
        aggregate=aggregate,
        train_val_test_gap=train_val_test_gap,
    )
