"""AG-371 item (1), sob pedido direto do Manager de fundamentar a decisão
em matemática financeira real, não remediação barata ("busque por solução
matematica financeira para o algoritmic trading nao casual").

`gain_by_column` (MDI -- Mean Decrease Impurity, a métrica que motivou
constranger `E27f_cost_atr_ratio` em `AG-371-ADDENDUM-6/8`) tem viés
ESTRUTURAL, documentado na literatura (López de Prado, AFML cap. 8 --
"MDI... is biased towards continuous features and high-cardinality
categorical features"): uma árvore de decisão tem MAIS pontos de corte
candidatos numa feature contínua de alcance dinâmico grande (exatamente
o perfil de `E27f = custo/ATR`, ATR varia ordens de magnitude na amostra)
do que numa feature discreta/binária -- MDI sobe SÓ PELA CARDINALIDADE,
sem relação com poder preditivo genuíno. Isso significa que "E27f domina
93% do gain" (AG-371-ADDENDUM-6) pode ser, em parte ou inteiramente,
ARTEFATO DA MÉTRICA, não evidência de que o modelo está genuinamente
"aprendendo" com essa feature mais que as outras.

Este script mede MDA (Mean Decrease Accuracy, AFML cap. 8 -- embaralha
UMA feature de cada vez no conjunto de TESTE out-of-fold, mede a queda
de AUC; ao contrário de MDI, não é enviesado por cardinalidade, porque
mede o efeito real na PREDIÇÃO fora da amostra, não na estrutura da
árvore em si) por feature, pra TODAS as 36 `T1_FEATURE_IDS`, em Camada0
SEM restrição nenhuma (pra ver o quadro bruto) e Camada0 COM a
restrição atual (só E27f) -- reusa os modelos já treinados, sem
retreino adicional pra cada permutação (mesmo padrão de `baselines.
run_b4_feature_shuffle`, que já existe mas embaralha TODAS as features
juntas -- essa função generaliza pra por-feature).

LEITURA: se MDI(E27f) alto MAS MDA(E27f) baixo (queda de AUC pequena
quando só ela é embaralhada) -- confirma que a dominância é artefato de
MDI/busca gulosa, reforça a decisão de restringir (ou até excluir).
Se MDA(E27f) também for alto -- E27f tem poder preditivo OOS genuíno,
mudaria a leitura (a restrição ainda pode ser certa por outros motivos,
mas não seria "está inflando um número que não significa nada").

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"), exceto autorização explícita do Manager na
sessão. Rodar com:

    uv run python tools/diagnostics/measure_ag371_mda_per_feature_camada0.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import polars as pl
import structlog

from src.features import build as features_build
from src.models import alpha
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models.baselines import _pool_auc  # reuso deliberado do interno, mesmo padrao de B4
from src.validation import cpcv

logger = structlog.get_logger(__name__)

_SYMBOL = "BTCUSDT"
_RESOLUTION_ID = "R1"
_TF = "15m"


def _mda_per_feature(
    df_all: pl.DataFrame,
    splits: tuple[cpcv.CPCVSplit, ...],
    fold_results: list[alpha.FoldResult],
    feature_ids: tuple[str, ...],
    *,
    seed: int,
) -> dict[str, float]:
    """MDA_j = AUC_real - AUC_com_feature_j_embaralhada, agrupado (pooled)
    sobre todos os folds/lados -- mesma agregacao de `_pool_auc` que B4
    ja usa. Custo: 1 forward pass extra por feature (36), reusa os
    modelos ja treinados -- sem retreino."""
    rng = np.random.default_rng(seed)
    split_by_id = {s.split_id: s for s in splits}

    y_all: list[np.ndarray] = []
    s_real_all: list[np.ndarray] = []
    per_feature_perm: dict[str, list[np.ndarray]] = {f: [] for f in feature_ids}

    for fr in fold_results:
        split = split_by_id[fr.fold_id]
        test_bars = df_all[split.test_idx]
        for side, model in ((1, fr.long_result.model), (-1, fr.short_result.model)):
            test_side = ds.side_subset(test_bars, side=side, feature_ids=feature_ids)
            if test_side.height == 0:
                continue
            X = alpha.build_design_matrix(test_side, feature_ids=feature_ids)
            y = (test_side["label"].cast(int) == 1).to_numpy().astype(np.int64)
            p_real = np.asarray(model.predict_proba(X))[:, 1]
            y_all.append(y)
            s_real_all.append(p_real)
            for j, feat in enumerate(feature_ids):
                X_perm = X.copy()
                perm_idx = rng.permutation(X_perm.shape[0])
                X_perm[:, j] = X_perm[perm_idx, j]
                p_perm = np.asarray(model.predict_proba(X_perm))[:, 1]
                per_feature_perm[feat].append(p_perm)

    auc_real = _pool_auc(y_all, s_real_all)
    mda: dict[str, float] = {}
    for feat in feature_ids:
        auc_perm = _pool_auc(y_all, per_feature_perm[feat])
        mda[feat] = auc_real - auc_perm
    return mda


def main() -> None:
    feature_ids = features_build.T1_FEATURE_IDS
    logger.info(
        "ag371_mda.setup",
        n_features=len(feature_ids),
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
    )

    mf = ds.build_modeling_frame(
        symbol=_SYMBOL, tf=_TF, resolution_id=_RESOLUTION_ID, vol_estimator_id="parkinson_w20"
    )
    max_lookback = features_build.compute_max_feature_lookback_ms(
        _TF, feature_ids, resolution_id=_RESOLUTION_ID
    )
    cpcv_config = cpcv.CPCVConfig.from_constants(
        tf=_TF, grade_id=_RESOLUTION_ID, max_feature_lookback_ms=max_lookback
    )
    cpcv_result = cpcv.generate_splits(mf.data, config=cpcv_config, symbol=_SYMBOL)
    splits = cpcv_result.splits
    seed = int(load_constant("alpha_random_seed"))

    # Camada0 SEM restrição nenhuma -- quadro bruto, mesma condição que
    # mediu o MDI dominante em AG-371-ADDENDUM-6. `CAMADA0_CONSTRAINED_
    # FEATURES` agora é aplicado INCONDICIONALMENTE em produção
    # (AG-371-ADDENDUM-9) -- monkeypatch LOCAL, só pra reproduzir o
    # "antes" nesta comparação; não é reintrodução do parâmetro
    # experimental removido, não toca nada fora deste processo.
    original_constrained_features = alpha.CAMADA0_CONSTRAINED_FEATURES
    alpha.CAMADA0_CONSTRAINED_FEATURES = frozenset()
    try:
        folds_unconstrained = alpha.run_all_folds(
            mf.data,
            splits,
            variant=alpha.VARIANT_CAMADA0,
            model_id="alpha_c0_mda_diag_unconstrained",
            symbol=_SYMBOL,
            resolution_id=_RESOLUTION_ID,
            feature_ids=feature_ids,
            seed=seed,
            # `run_all_folds` sozinho default pro legado (`CALIB_SPLIT_
            # LEGACY_RANDOM`) -- INCOMPATIVEL com `early_stopping_mode=
            # 'three_way'` de `LGBMHyperparams.from_constants()` (produção
            # real). `run_layer1_sprint` sempre passa `temporal_purged`
            # explicito; replicado aqui por chamar `run_all_folds` direto.
            calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
        )
    finally:
        alpha.CAMADA0_CONSTRAINED_FEATURES = original_constrained_features
    mda_unconstrained = _mda_per_feature(
        mf.data, splits, folds_unconstrained, feature_ids, seed=seed
    )
    ranked_unconstrained = sorted(mda_unconstrained.items(), key=lambda kv: -kv[1])
    logger.info(
        "ag371_mda.unconstrained_top10",
        top10=ranked_unconstrained[:10],
        e27f_mda=mda_unconstrained.get("E27f_cost_atr_ratio"),
        e27f_rank=[f for f, _ in ranked_unconstrained].index("E27f_cost_atr_ratio") + 1,
    )

    # Camada0 COM a restricao ja promovida (so E27f) -- ve se o quadro de
    # MDA muda quando o MDI de E27f fica contido.
    folds_constrained = alpha.run_all_folds(
        mf.data,
        splits,
        variant=alpha.VARIANT_CAMADA0,
        model_id="alpha_c0_mda_diag_constrained",
        symbol=_SYMBOL,
        resolution_id=_RESOLUTION_ID,
        feature_ids=feature_ids,
        seed=seed,
        calib_split_mode=alpha.CALIB_SPLIT_TEMPORAL_PURGED,
    )
    mda_constrained = _mda_per_feature(mf.data, splits, folds_constrained, feature_ids, seed=seed)
    ranked_constrained = sorted(mda_constrained.items(), key=lambda kv: -kv[1])
    logger.info(
        "ag371_mda.constrained_top10",
        top10=ranked_constrained[:10],
        e27f_mda=mda_constrained.get("E27f_cost_atr_ratio"),
        e27f_rank=[f for f, _ in ranked_constrained].index("E27f_cost_atr_ratio") + 1,
    )


if __name__ == "__main__":
    main()
