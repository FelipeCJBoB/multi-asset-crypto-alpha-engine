"""Calcula o `feature_ids_hash` que falta no header de `config/
alpha_hyperparams_by_combo.yaml` (AG-371, `audit/architecture_gaps_
log.yaml`) -- não escreve no YAML sozinho, mesma disciplina de
`calibrate_jump_model_penalty_per_asset.py` (decisão/edição de config
fica com quem roda, script só mede). Cole o valor logado na chave
`feature_ids_hash:` do header, substituindo `null`.

PENDENTE-DE-EXECUÇÃO-HUMANA -- Claude não executa `.py` (CLAUDE.md,
"Protocolo de execução"). Rodar com:

    uv run python tools/diagnostics/backfill_ag371_hyperparams_feature_hash.py

**O que este script faz.** `alpha_hyperparams_by_combo.yaml` (ADR-003,
2026-08-25) foi calibrado sob `SUPPORT_FEATURE_IDS` como era NAQUELA
data -- 62 features, substituindo os 7 `T1_FEATURE_IDS` da época (nunca
somando). `AG-362` (2026-08-27) reestruturou `T1_FEATURE_IDS` pra 22 sem
recalibrar este arquivo -- `src.models.hyperparams_by_combo.
load_hyperparams_by_combo` agora recusa (`HyperparamFeatureMismatchError`)
até o header ganhar um `feature_ids_hash` real pra comparar. O vetor de
62 features de 25/08 não existe mais em `src.features.build` (foi
reduzido a 4 pelo AG-362) -- por isso o vetor histórico está CONGELADO
como literal abaixo (mesmo padrão de `ORIGINAL_T1_FEATURE_IDS` em
`src.analysis.ag362_incremental_value_report`), lido de `git show
10fbd78:src/features/build.py` (2026-08-25, HEAD de `build.py` na data
da campanha ADR-003, imediatamente anterior às mudanças de 26-27/08)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import structlog

from src.features import build as features_build
from src.models.hyperparams_by_combo import compute_feature_ids_hash

logger = structlog.get_logger(__name__)

#: `SUPPORT_FEATURE_IDS` tal como existia em `git show 10fbd78:src/
#: features/build.py` (2026-08-25, commit imediatamente anterior às
#: mudanças de 26-27/08 que o alteraram) -- vetor real sob o qual a
#: campanha ADR-003 mediu (62 features, confirmado por contagem manual
#: nesta investigação, AG-371). Congelado aqui como literal, não
#: importado de `features/build.py` -- o vetor ATUAL desse módulo não é
#: mais este (AG-362 reduziu `SUPPORT_FEATURE_IDS` pra 4).
SUPPORT_FEATURE_IDS_ADR003_2026_08_25: tuple[str, ...] = (
    "C01_atr_20",
    "C02_atr_20_pct",
    "B07_efficiency_ratio_48",
    "A01_log_return_1",
    "A02_log_return_2",
    "A03_log_return_4",
    "A04_log_return_12",
    "A06_ret_vol_norm_12",
    "A07_body_ratio",
    "A08_upper_wick_ratio",
    "A09_lower_wick_ratio",
    "A10_close_location",
    "A11_true_range_pct",
    "A12_gap_pct",
    "A14_dist_ema12_atr",
    "B02_rsi_48",
    "B03_roc_12",
    "B04_macd_hist_norm",
    "B05_ema_slope_24",
    "B06_momentum_accel",
    "B08_efficiency_ratio_16",
    "B09_zscore_close_48",
    "B11_bb_position_20",
    "C03_realized_vol_48",
    "C04_parkinson_vol_48",
    "C05_garman_klass_48",
    "C09_range_pctile_expanding",
    "C10_vol_expansion_flag",
    "C11_vol_compression_flag",
    "C12_vol_of_vol_48",
    "D01f_volume_z_96",
    "D02f_rel_volume_48",
    "D04f_volume_accel",
    "D05f_taker_buy_ratio",
    "D08f_trade_count_z_48",
    "D09f_avg_trade_size_z",
    "E01f_funding_last",
    "E05f_time_to_funding_h",
    "E09f_oi_contracts",
    "E11f_oi_change_1d",
    "E12f_price_oi_divergence",
    "K01_hour_sin",
    "K01_hour_cos",
    "K02_dow_sin",
    "K02_dow_cos",
    "K03_is_weekend",
    "K04_session_asia",
    "K04_session_europe",
    "K04_session_us",
    "K08_days_since_halving",
    "A15_dist_vwap_d_atr",
    "B10_stoch_k_14",
    "C08_vol_pctile_rolling_1y",
    "D07f_taker_imbalance_1m_agg",
    "D10f_vol_price_divergence",
    "E03f_funding_cum_3d",
    "E08f_oi_notional",
    "E14f_toptrader_ls_ratio",
    "E15f_toptrader_ls_z",
    "E16f_global_ls_ratio",
    "E17f_retail_vs_top_spread",
    "E18f_taker_ls_vol_ratio",
)


def main() -> None:
    n = len(SUPPORT_FEATURE_IDS_ADR003_2026_08_25)
    if n != 62:
        raise AssertionError(
            f"SUPPORT_FEATURE_IDS_ADR003_2026_08_25 tem {n} entradas, esperado 62 "
            "(ADR-003/AG-371) -- vetor congelado neste script não bate com o "
            "documentado, não gere hash sobre um vetor errado"
        )
    hash_adr003 = compute_feature_ids_hash(SUPPORT_FEATURE_IDS_ADR003_2026_08_25)
    hash_t1_atual = compute_feature_ids_hash(features_build.T1_FEATURE_IDS)

    logger.info(
        "ag371.backfill_feature_ids_hash",
        feature_ids_hash_adr003_62_features=hash_adr003,
        n_features_adr003=n,
        acao="cole este valor em config/alpha_hyperparams_by_combo.yaml::"
        "feature_ids_hash, substituindo o `null` atual",
    )
    logger.info(
        "ag371.backfill_confirmacao_mismatch_real",
        hash_t1_feature_ids_atual_22_features=hash_t1_atual,
        n_features_t1_atual=len(features_build.T1_FEATURE_IDS),
        bate_com_calibracao=hash_t1_atual == hash_adr003,
        leitura="False esperado -- confirma que o retreino canonico de "
        "28/08 (T1_FEATURE_IDS, 22) rodou sob hash diferente do que "
        "calibrou este arquivo (SUPPORT_FEATURE_IDS de 25/08, 62); é "
        "exatamente o mismatch que HyperparamFeatureMismatchError agora recusa",
    )


if __name__ == "__main__":
    main()
