"""F6b — replica a ablação do Meta (F6, `meta_ablation.py`) sobre a
timeline CAUSAL do Alpha (walk-forward ancorado) — `docs/meta_model_
design_doc_2026-08-22.md` §4.4/§9.

**Por que existe.** §4.4 é taxativo: um modelo CPCV é treinado em blocos
que incluem dado POSTERIOR ao bloco de teste; o Alpha de produção só vê
passado. F6 (`meta_ablation.py`, `AG-409`) mediu 0/5 símbolos sob CPCV —
F6b confirma (ou refuta) se a mesma reprovação se sustenta sob a
estrutura de erro real de produção, causal, sem olhar-pra-frente nenhum.

**Decisão do Manager (2026-09-01) — split ÚNICO, não k-folds
aninhados.** A regra de doador `path_matched` do CPCV
(`meta_dataset.donor_folds_for_path_matched`) não existe sob walk-forward
ancorado: cada fold de WF É seu próprio `path_id`
(`src/models/walk_forward.py`, "path_id=wf_split.fold_id... deliberado"),
então aplicar `path_matched` sem adaptação zeraria o treino do Meta em
TODO fold por construção (achado real, verificado ANTES deste módulo
existir — não hipotético, não uma suposição). Réplicas aninhadas
exigiriam uma primitiva de purge nova sobre uma timeline já muito mais
curta que o dado denso (a OOS do Alpha, não o histórico inteiro) — custo
e risco que o Manager decidiu não pagar agora. Registrado em `AG-413`.

Consequência: F6b produz 1 avaliação A0/A1/A2(nulo)/A3 por combo — não
uma família de "paths" comparável à de F6/CPCV. O critério primário do
§9/§4.6 já era sobre SÍMBOLOS, não paths — isto não perde poder de
decisão nenhum, só reduz uma dimensão secundária que nunca era o
critério de fato."""

from __future__ import annotations

from typing import Any

import polars as pl
import structlog

from src.validation.volatility_walkforward import generate_anchored_walk_forward_splits

from . import alpha
from . import meta as meta_mod
from . import meta_ablation as ab
from . import meta_dataset as mds
from . import walk_forward as wf
from ._constants import load_constant

logger = structlog.get_logger(__name__)


def run_meta_walk_forward_ablation_for_combo(
    mf_data: pl.DataFrame,
    *,
    symbol: str,
    resolution_id: str,
    variant: str,
    hyper: alpha.LGBMHyperparams,
    alpha_model_id: str,
    seed: int,
    regime_source: str = "quantile_classifier_v1",
    n_seeds: int | None = None,
    random_state: int | None = None,
    initial_train_years: int | None = None,
    device_type: str = "cpu",
) -> dict[str, Any]:
    """F6b ponta a ponta pra UM combo `(symbol, resolution_id, variant)`.

    1. Retreina o Alpha via walk-forward ancorado REAL
       (`walk_forward.run_walk_forward_for_combo`, `keep_predictions=
       True` — a única diferença de comportamento que essa opção
       introduz, ver docstring dela).
    2. Concatena as predições OOS reais dos folds não-degenerados numa
       única timeline causal.
    3. Resolve UMA fronteira temporal sobre essa timeline
       (`generate_anchored_walk_forward_splits`, mesma constante
       `initial_train_years` do Alpha — reusada, não uma nova) e monta
       o `meta_training_set` de split único
       (`meta_dataset.build_meta_signal_table_wf_single_split`).
    4. Roda o Meta (`meta.run_meta_fold`, `meta_split_id=0`) e o MESMO
       mecanismo de ablação de F6 (`meta_ablation.run_ablation_for_
       combo`, `min_paths_required=1` — existe exatamente 1 path por
       construção, não um afrouxamento do limiar `≥4/5` do CPCV).

    `regime_source` default `quantile_classifier_v1` — mesma configuração
    real que F6/`AG-409` usou (o artefato HMM k=4 nunca foi persistido,
    `PLANO_MESTRE_PRINCE2.md` §15.38). Passe `hmm_gaussian_k4_v1`
    explicitamente se/quando esse artefato existir."""
    wf_result = wf.run_walk_forward_for_combo(
        mf_data,
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        hyper=hyper,
        seed=seed,
        device_type=device_type,
        initial_train_years=initial_train_years,
        keep_predictions=True,
    )
    preds_por_fold = [
        fr.predictions for fr in wf_result.fold_results if fr.predictions is not None
    ]
    if not preds_por_fold:
        raise mds.MetaDatasetError(
            f"run_meta_walk_forward_ablation_for_combo: {symbol}/{resolution_id} -- "
            "nenhum fold de walk-forward do Alpha produziu predições (todos "
            "degenerados por 0 barras de teste válidas). Sem OOS real não há "
            "timeline pra montar o Meta."
        )
    wf_predictions = pl.concat(preds_por_fold, how="vertical")

    initial_train_years_eff = (
        initial_train_years
        if initial_train_years is not None
        else int(load_constant("m1_walkforward_initial_train_years"))
    )
    unique_t0_ms = wf_predictions["t0"].dt.epoch(time_unit="ms").unique().sort().to_numpy()
    meta_wf_splits = generate_anchored_walk_forward_splits(
        unique_t0_ms, initial_train_years=initial_train_years_eff
    )
    if not meta_wf_splits:
        raise mds.MetaDatasetError(
            f"run_meta_walk_forward_ablation_for_combo: {symbol}/{resolution_id} -- "
            "timeline OOS do Alpha curta demais pra gerar sequer 1 fronteira de "
            f"split (initial_train_years={initial_train_years_eff})."
        )
    # Só a PRIMEIRA fronteira importa (decisão do Manager: split único) —
    # tudo que vem depois dela, na timeline OOS inteira, vira teste do
    # Meta; não há um segundo/terceiro fold aninhado.
    test_start_ms = int(unique_t0_ms[meta_wf_splits[0].test_start_idx])

    table = mds.build_meta_signal_table_wf_single_split(
        dense=mf_data,
        wf_predictions=wf_predictions,
        test_start_ms=test_start_ms,
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        regime_source=regime_source,
        origem=f"run_meta_walk_forward_ablation_for_combo({symbol}/{resolution_id}/{variant})",
    )
    regime_levels = mds.regime_levels_for_source(regime_source)
    meta_random_state = (
        random_state if random_state is not None else int(load_constant("alpha_random_seed"))
    )
    fold_result = meta_mod.run_meta_fold(
        table,
        meta_split_id=0,
        regime_levels=regime_levels,
        random_state=meta_random_state,
        alpha_model_id=alpha_model_id,
        variant=variant,
        resolution_id=resolution_id,
    )

    ablation = ab.run_ablation_for_combo(
        (fold_result,),
        table,
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        n_seeds=n_seeds,
        min_paths_required=1,
        random_state=meta_random_state,
    )

    logger.info(
        "models.meta_walk_forward.combo_concluido",
        symbol=symbol,
        resolution_id=resolution_id,
        n_wf_folds_alpha_usados=wf_result.n_folds_usados,
        n_wf_folds_alpha_total=wf_result.n_folds_total,
        test_start_ms=test_start_ms,
        meta_fold_status=fold_result.fold_status,
        n_train_meta=table.filter(pl.col("role") == mds.ROLE_TRAIN).height,
        n_test_meta=table.filter(pl.col("role") == mds.ROLE_TEST).height,
        gate_passed=ablation.gate_passed,
    )

    return {
        "symbol": symbol,
        "resolution_id": resolution_id,
        "wf_result": wf_result,
        "meta_table": table,
        "meta_fold_result": fold_result,
        "ablation": ablation,
    }
