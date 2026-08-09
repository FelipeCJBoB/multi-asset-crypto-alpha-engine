"""Faixa 2 E2 — passe de PESQUISA sobre candidatas T2 (§2.2-2.12), sem
curadoria, por instrução explícita do Manager (2026-08-09): "todas as
candidatas T2... num passe de pesquisa (sem registry/paridade), ranquear
por ortogonalidade incremental... e só então promover as vencedoras a
produção com a cerimônia completa."

**Isto NÃO é `src/features/groups/` de produção.** Nenhuma função aqui
tem `causal_proof`/entrada em `registry.yaml`/teste de paridade
lote↔streaming — essa cerimônia é para DEPOIS, só para o que for
promovido. O que se preserva mesmo assim, porque não é "cerimônia" e sim
correção: toda janela é CAUSAL (rolante — a barra `t` pode entrar na
própria janela; ou expansiva estrita — só `< t`, nunca `t`), reusando os
primitivos de `src.features.support` sempre que a definição bate.

**Escopo real, não as ~140 linhas nominais do PRD.** Auditoria de
computabilidade (2026-08-09, agente de pesquisa) encontrou 81 candidatas
T2 nos grupos A/B/C/D/E/H/K (G e I não têm nenhuma fonte de dado local —
D14 opções e E02/E04 macro simplesmente não existem no repo; Grupo F
segue excluído pela regra já existente do §2.7.1, quebra de RPI). Desses
81, 6 são impossíveis por coluna ausente do CSV on-chain (H04/H05/H07/
H09/H10/H11 — `data/capacity/onchain/btc_coinmetrics.csv` não tem
volume-USD on-chain, SOPR, NVT, fluxo de miner, oferta por idade, nem
stablecoin). Deste módulo, mais 7 ficam DE FORA por custo de engenharia
real desta rodada, não por escolha de gosto:

- **A16/A17/B12** (`ctx_dist_ema_2h`/`ctx_dist_ema_1d`/`ctx_rsi_2h`):
  exigem um TERCEIRO padrão de alinhamento causal (resample pra 2h/1d +
  asof-join de volta pro grid de 15m só com barras de contexto já
  FECHADAS) — o mesmo problema que `_sources.asof_align_backward`
  resolve pra funding/OI, mas numa direção nova (klines re-amostradas,
  não uma série auxiliar). Adiado, não implementado às pressas.
- **C08** (`vol_pctile_rolling_1y`): posto percentil numa janela ROLANTE
  de 35.064 barras (1 ano) não tem primitivo O(n log w) pronto —
  `expanding_percentile_rank_strict` é expansiva, não rolante. Um
  `rolling_map` ingênuo custaria ~8 bilhões de comparações em Python.
  Adiado — implementação correta exigiria uma estrutura de dados nova
  (ex. duas heaps balanceadas por janela).
- **D11f/D13f** (`large_trade_ratio`/`trade_run_length`): exigem
  agregação em nível de TRADE sobre `agg_trades` (potencialmente bilhões
  de linhas em 6,6 anos) — percentil-99 de tamanho de trade e
  comprimento de sequência por lado de agressor não são agregações
  simples de `group_by`. D12f (`agg_order_flow_imb`, soma por lado,
  agregação simples) FICA — é o mesmo dado-fonte, complexidade diferente.
- **E23f** (`quarterly_annualized_basis`): exige lógica de rolagem de
  contrato (qual trimestral é o "front month" em cada barra, a partir do
  nome do diretório `BTCUSDT_{YYMMDD}`) — mecanismo novo, não uma
  chamada a primitivo existente. Adiado.

**C13/C14/C15 (BVOL) e a cobertura de 3,1 anos — sinalizado, não
escondido.** `data/raw/bvol_index/` só existe desde 2023-06-20 (não
"2021" como o PRD tabula) — qualquer feature derivada tem ~54% de
histórico nulo antes disso. Computadas mesmo assim (sem curadoria), mas
o relatório de ranking carrega esse aviso lado a lado com o número."""

from __future__ import annotations

import numpy as np
import polars as pl
from numpy.typing import NDArray

from . import support

FloatArray = NDArray[np.float64]


# ============================================================================
# Primitivos genéricos que faltam em support.py (research-pass: menos
# cerimônia de docstring, mas ainda causal por construção).
# ============================================================================


def log_return_n(close: FloatArray, n: int) -> FloatArray:
    out = np.full(close.shape[0], np.nan, dtype=np.float64)
    if close.shape[0] > n:
        out[n:] = np.log(close[n:] / close[:-n])
    return out


def rolling_median(values: FloatArray, window: int) -> FloatArray:
    s = pl.Series(values)
    out: FloatArray = s.rolling_median(window_size=window, min_samples=window).to_numpy()
    return out


def rolling_std(values: FloatArray, window: int) -> FloatArray:
    s = pl.Series(values)
    out: FloatArray = s.rolling_std(window_size=window, min_samples=window, ddof=1).to_numpy()
    return out


def rolling_corr(x: FloatArray, y: FloatArray, window: int) -> FloatArray:
    """Correlação de Pearson rolante — via somas rolantes (E[xy]-E[x]E[y])
    / (std_x std_y), janela fixa (a barra `t` entra na própria janela)."""
    sx, sy, sxy = pl.Series(x), pl.Series(y), pl.Series(x * y)
    mean_x = sx.rolling_mean(window_size=window, min_samples=window).to_numpy()
    mean_y = sy.rolling_mean(window_size=window, min_samples=window).to_numpy()
    mean_xy = sxy.rolling_mean(window_size=window, min_samples=window).to_numpy()
    std_x = sx.rolling_std(window_size=window, min_samples=window, ddof=0).to_numpy()
    std_y = sy.rolling_std(window_size=window, min_samples=window, ddof=0).to_numpy()
    cov = mean_xy - mean_x * mean_y
    with np.errstate(divide="ignore", invalid="ignore"):
        out: FloatArray = cov / (std_x * std_y)
    return out


# ============================================================================
# GRUPO A — preço e retorno (13 candidatas nesta rodada; A16/A17 adiadas)
# ============================================================================


def group_a_research(bars_15m: pl.DataFrame, atr_20_pct: FloatArray) -> dict[str, FloatArray]:
    close = bars_15m["close"].cast(pl.Float64).to_numpy()
    high = bars_15m["high"].cast(pl.Float64).to_numpy()
    low = bars_15m["low"].cast(pl.Float64).to_numpy()
    open_ = bars_15m["open"].cast(pl.Float64).to_numpy()
    quote_volume = bars_15m["quote_volume"].cast(pl.Float64).to_numpy()
    volume = bars_15m["volume"].cast(pl.Float64).to_numpy()
    n = close.shape[0]

    prev_close = np.full(n, np.nan, dtype=np.float64)
    prev_close[1:] = close[:-1]
    high_low = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        body_ratio = np.where(high_low > 0, (close - open_) / high_low, 0.0)
        upper_wick_ratio = np.where(high_low > 0, (high - np.maximum(open_, close)) / high_low, 0.0)
        lower_wick_ratio = np.where(high_low > 0, (np.minimum(open_, close) - low) / high_low, 0.0)
        close_location = np.where(high_low > 0, (close - low) / high_low, 0.0)
        true_range_pct = support.true_range(high, low, close) / prev_close
        gap_pct = (open_ - prev_close) / prev_close

    ema_12 = support.ema(close, 12)
    atr_20_abs = support.atr_wilder(high, low, close, 20)

    # A15 VWAP diário: reseta na virada de dia UTC, causal (só o próprio dia
    # até a barra atual -- cumsum de quote_volume/volume por grupo de dia).
    day_key = bars_15m["open_time"].cast(pl.Int64) // 86_400_000
    vwap_df = pl.DataFrame({"day": day_key, "qv": quote_volume, "v": volume}).with_columns(
        pl.col("qv").cum_sum().over("day").alias("cum_qv"),
        pl.col("v").cum_sum().over("day").alias("cum_v"),
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap_d = (vwap_df["cum_qv"] / vwap_df["cum_v"]).to_numpy()
        dist_vwap_d_atr = (close - vwap_d) / atr_20_abs

    # 3.0/2.0: formula literal do PRD (§2.2 A06) -- `ln(C_t/C_{t-12}) /
    # (ATR_20 x sqrt(3) x 2)`, não parametro de dominio.
    a06_sqrt3 = 3.0  # noqa: magic-number
    a06_scale = 2.0  # noqa: magic-number
    a06_ret_vol_norm_12 = log_return_n(close, 12) / (atr_20_pct * np.sqrt(a06_sqrt3) * a06_scale)

    return {
        "A01_log_return_1": log_return_n(close, 1),
        "A02_log_return_2": log_return_n(close, 2),
        "A03_log_return_4": log_return_n(close, 4),
        "A04_log_return_12": log_return_n(close, 12),
        "A06_ret_vol_norm_12": a06_ret_vol_norm_12,
        "A07_body_ratio": body_ratio,
        "A08_upper_wick_ratio": upper_wick_ratio,
        "A09_lower_wick_ratio": lower_wick_ratio,
        "A10_close_location": close_location,
        "A11_true_range_pct": true_range_pct,
        "A12_gap_pct": gap_pct,
        "A14_dist_ema12_atr": (close - ema_12) / atr_20_abs,
        "A15_dist_vwap_d_atr": dist_vwap_d_atr,
    }


# ============================================================================
# GRUPO B — momentum e reversão (10 candidatas; B12 adiada)
# ============================================================================


def group_b_research(bars_15m: pl.DataFrame, atr_20_abs: FloatArray) -> dict[str, FloatArray]:
    close = bars_15m["close"].cast(pl.Float64).to_numpy()
    high = bars_15m["high"].cast(pl.Float64).to_numpy()
    low = bars_15m["low"].cast(pl.Float64).to_numpy()
    n = close.shape[0]

    roc_12 = np.full(n, np.nan, dtype=np.float64)
    if n > 12:
        roc_12[12:] = (close[12:] - close[:-12]) / close[:-12]

    ema_12 = support.ema(close, 12)
    ema_26 = support.ema(close, 26)
    macd_line = ema_12 - ema_26
    macd_signal = support.ema(np.where(np.isnan(macd_line), 0.0, macd_line), 9)
    macd_signal[: support._first_valid_index(macd_line) + 9] = np.nan
    macd_hist_norm = (macd_line - macd_signal) / atr_20_abs

    ema_24 = support.ema(close, 24)
    ema_24_lag6 = np.full(n, np.nan, dtype=np.float64)
    ema_24_lag6[6:] = ema_24[:-6]
    ema_slope_24 = (ema_24 - ema_24_lag6) / atr_20_abs

    ret_4 = log_return_n(close, 4)
    ret_4_lag4 = np.full(n, np.nan, dtype=np.float64)
    ret_4_lag4[4:] = ret_4[:-4]
    momentum_accel = (ret_4 - ret_4_lag4) / (atr_20_abs / np.where(close != 0, close, np.nan))

    zscore_close_48 = support.rolling_zscore(close, 48)

    roll_low_14 = pl.Series(low).rolling_min(window_size=14, min_samples=14).to_numpy()
    roll_high_14 = pl.Series(high).rolling_max(window_size=14, min_samples=14).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        stoch_k_14 = (close - roll_low_14) / (roll_high_14 - roll_low_14)

    ma_20 = pl.Series(close).rolling_mean(window_size=20, min_samples=20).to_numpy()
    std_20 = pl.Series(close).rolling_std(window_size=20, min_samples=20, ddof=1).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        bb_position_20 = (close - ma_20) / (2.0 * std_20)

    return {
        "B02_rsi_48": support.rsi_wilder(close, 48),
        "B03_roc_12": roc_12,
        "B04_macd_hist_norm": macd_hist_norm,
        "B05_ema_slope_24": ema_slope_24,
        "B06_momentum_accel": momentum_accel,
        "B07_efficiency_ratio_48": support.efficiency_ratio(close, 48),
        "B08_efficiency_ratio_16": support.efficiency_ratio(close, 16),
        "B09_zscore_close_48": zscore_close_48,
        "B10_stoch_k_14": stoch_k_14,
        "B11_bb_position_20": bb_position_20,
    }


# ============================================================================
# GRUPO C — volatilidade (12 candidatas nesta rodada; C01/C02 já em
# SUPPORT_FEATURE_IDS, reincluídas por serem tier T2 candidatas a T1;
# C08 adiada acima; C13-15 com aviso de cobertura de 3,1 anos)
# ============================================================================


def group_c_research(
    bars_15m: pl.DataFrame,
    log_return_1: FloatArray,
    atr_20_abs: FloatArray,
    atr_20_pct: FloatArray,
    bvol_aligned: FloatArray | None,
) -> dict[str, FloatArray]:
    close = bars_15m["close"].cast(pl.Float64).to_numpy()
    high = bars_15m["high"].cast(pl.Float64).to_numpy()
    low = bars_15m["low"].cast(pl.Float64).to_numpy()

    # 4.0: constante do estimador de Parkinson (`1/(4 ln 2)`), formula
    # fechada da literatura (Parkinson 1980), não parametro de dominio.
    parkinson_constant = 4.0  # noqa: magic-number
    log_hl = np.log(high / low)
    parkinson_vol_48 = np.sqrt(
        pl.Series(log_hl**2).rolling_mean(window_size=48, min_samples=48).to_numpy()
        / (parkinson_constant * np.log(2.0))
    )

    log_ho = np.log(high / np.where(close != 0, np.roll(close, 1), np.nan))
    log_lo = np.log(low / np.where(close != 0, np.roll(close, 1), np.nan))
    log_co = np.log(close / np.where(close != 0, np.roll(close, 1), np.nan))
    gk_term = 0.5 * log_hl**2 - (2.0 * np.log(2.0) - 1.0) * log_co**2
    garman_klass_48 = np.sqrt(
        np.maximum(
            pl.Series(gk_term).rolling_mean(window_size=48, min_samples=48).to_numpy(), 0.0
        )
    )
    del log_ho, log_lo  # não usados nesta variante simplificada de GK (só H/L/C)

    vol_ratio_12_96 = support.realized_vol(log_return_1, 12) / support.realized_vol(
        log_return_1, 96
    )
    rv48 = support.realized_vol(log_return_1, 48)
    # C08 (vol_pctile_rolling_1y) DEFERIDA: posto percentil numa janela
    # ROLANTE de 35.064 barras (1 ano) não tem primitivo O(n log w) pronto
    # em support.py (expanding_percentile_rank_strict é EXPANSIVA, não
    # rolante). Um `rolling_map` ingênuo com callback Python reavalia até
    # 35 mil comparações por barra em ~230 mil barras (~8 bilhões de
    # operações) -- proibitivo nesta rodada. Mesma categoria de adiamento
    # que D11f/D13f/E23f (custo de engenharia real, não curadoria).

    range_pctile_expanding = support.expanding_percentile_rank_strict(
        support.true_range(high, low, close) / np.where(close != 0, close, np.nan)
    )
    # 0.80/0.20: literal do PRD (§2.4 C10/C11 -- "q_0.80"/"q_0.20"), citado
    # do texto, não escolhido por conveniência.
    expansion_quantile = 0.80  # noqa: magic-number
    compression_quantile = 0.20  # noqa: magic-number
    vol_ratio_pctile = support.expanding_percentile_rank_strict(vol_ratio_12_96)
    vol_expansion_flag = np.where(
        np.isnan(vol_ratio_pctile), np.nan, (vol_ratio_pctile > expansion_quantile).astype(float)
    )
    vol_compression_flag = np.where(
        np.isnan(vol_ratio_pctile), np.nan, (vol_ratio_pctile < compression_quantile).astype(float)
    )
    vol_of_vol_48 = rolling_std(support.realized_vol(log_return_1, 12), 48)

    out: dict[str, FloatArray] = {
        "C03_realized_vol_48": rv48,
        "C04_parkinson_vol_48": parkinson_vol_48,
        "C05_garman_klass_48": garman_klass_48,
        "C09_range_pctile_expanding": range_pctile_expanding,
        "C10_vol_expansion_flag": vol_expansion_flag,
        "C11_vol_compression_flag": vol_compression_flag,
        "C12_vol_of_vol_48": vol_of_vol_48,
    }
    if bvol_aligned is not None:
        bvol_z_90d_window = 8640  # 90 dias x 96 barras/dia (15m) -- janela ROLANTE, não expansiva
        out["C13_bvol_index"] = bvol_aligned
        out["C14_bvol_z_90d"] = rolling_zscore_fixed(bvol_aligned, bvol_z_90d_window)
        # 100.0: BVOL cotado em pontos percentuais anualizados (ex. "45.2"
        # = 45,2% a.a.) -- conversão pra fração, não parametro de dominio.
        # bars_per_year/rv_window: mesma convenção de anualização de
        # `backtest_lite.DAYS_PER_YEAR` (35.064 barras/ano de 15m) sobre a
        # janela de 48 barras já usada por `rv48` acima -- reaproveitada,
        # não redefinida.
        bvol_pct_to_frac = 100.0  # noqa: magic-number
        bars_per_year = 35_064.0  # noqa: magic-number
        rv_window = 48.0  # noqa: magic-number
        annualization = np.sqrt(bars_per_year / rv_window)
        out["C15_iv_rv_spread"] = bvol_aligned / bvol_pct_to_frac - rv48 * annualization
    del atr_20_abs, atr_20_pct
    return out


def rolling_zscore_fixed(values: FloatArray, window: int) -> FloatArray:
    return support.rolling_zscore(values, window)


# ============================================================================
# GRUPO D — volume e fluxo de agressor (9 candidatas; D11f/D13f adiadas)
# ============================================================================


def group_d_research(
    bars_15m: pl.DataFrame, order_flow_imb_1m_agg: FloatArray | None
) -> dict[str, FloatArray]:
    volume = bars_15m["volume"].cast(pl.Float64).to_numpy()
    taker_buy_volume = bars_15m["taker_buy_volume"].cast(pl.Float64).to_numpy()
    count = bars_15m["count"].cast(pl.Float64).to_numpy()
    n = volume.shape[0]

    with np.errstate(divide="ignore", invalid="ignore"):
        taker_buy_ratio = taker_buy_volume / volume
        avg_trade_size = volume / count

    rel_volume_48 = volume / rolling_median(volume, 48)
    rel_volume_4 = volume / rolling_median(volume, 4)
    rel_volume_4_lag4 = np.full(n, np.nan, dtype=np.float64)
    rel_volume_4_lag4[4:] = rel_volume_4[:-4]
    volume_accel = rel_volume_4 - rel_volume_4_lag4

    log_volume = np.log1p(volume)
    abs_ret = np.abs(np.diff(np.log(bars_15m["close"].cast(pl.Float64).to_numpy()), prepend=np.nan))
    volume_z_48 = support.rolling_zscore(log_volume, 48)
    vol_price_divergence = rolling_corr(abs_ret, volume_z_48, 48)

    out: dict[str, FloatArray] = {
        "D01f_volume_z_96": support.rolling_zscore(log_volume, 96),
        "D02f_rel_volume_48": rel_volume_48,
        "D04f_volume_accel": volume_accel,
        "D05f_taker_buy_ratio": taker_buy_ratio,
        "D08f_trade_count_z_48": support.rolling_zscore(count, 48),
        "D09f_avg_trade_size_z": support.rolling_zscore(avg_trade_size, 48),
        "D10f_vol_price_divergence": vol_price_divergence,
    }
    if order_flow_imb_1m_agg is not None:
        out["D07f_taker_imbalance_1m_agg"] = order_flow_imb_1m_agg
    return out


# ============================================================================
# GRUPO E — futuros: funding, OI, basis (13 candidatas; E23f adiada)
# ============================================================================


def group_e_research(
    funding_aligned: FloatArray,
    funding_interval_hours: float,
    oi_notional_aligned: FloatArray,
    oi_contracts_aligned: FloatArray,
    close: FloatArray,
    log_return_12: FloatArray,
    toptrader_ls_aligned: FloatArray,
    global_ls_aligned: FloatArray,
    taker_ls_vol_aligned: FloatArray,
    close_time_ms: FloatArray,
    agg_order_flow_imb: FloatArray | None,
) -> dict[str, FloatArray]:
    n = funding_aligned.shape[0]

    funding_cum_3d = pl.Series(funding_aligned).rolling_sum(window_size=9, min_samples=9).to_numpy()

    ms_per_hour = 3_600_000.0  # noqa: magic-number -- conversão de unidade, não parametro
    interval_ms = funding_interval_hours * ms_per_hour
    time_to_funding_h = (interval_ms - (close_time_ms % interval_ms)) / ms_per_hour

    log_oi = np.log(np.where(oi_contracts_aligned > 0, oi_contracts_aligned, np.nan))
    oi_change_48 = np.full(n, np.nan, dtype=np.float64)
    if n > 48:
        oi_change_48[48:] = log_oi[48:] - log_oi[:-48]

    oi_change_12 = np.full(n, np.nan, dtype=np.float64)
    if n > 12:
        oi_change_12[12:] = log_oi[12:] - log_oi[:-12]
    price_oi_divergence = np.sign(log_return_12) * np.sign(oi_change_12)

    toptrader_ls_z = support.expanding_zscore_strict(toptrader_ls_aligned)
    global_ls_z = support.expanding_zscore_strict(global_ls_aligned)

    out: dict[str, FloatArray] = {
        "E01f_funding_last": funding_aligned,
        "E03f_funding_cum_3d": funding_cum_3d,
        "E05f_time_to_funding_h": time_to_funding_h,
        "E08f_oi_notional": oi_notional_aligned,
        "E09f_oi_contracts": oi_contracts_aligned,
        "E11f_oi_change_1d": oi_change_48,
        "E12f_price_oi_divergence": price_oi_divergence,
        "E13f_oi_pctile_expanding": support.expanding_percentile_rank_strict(oi_notional_aligned),
        "E14f_toptrader_ls_ratio": toptrader_ls_aligned,
        "E15f_toptrader_ls_z": toptrader_ls_z,
        "E16f_global_ls_ratio": global_ls_aligned,
        "E17f_retail_vs_top_spread": global_ls_z - toptrader_ls_z,
        "E18f_taker_ls_vol_ratio": taker_ls_vol_aligned,
    }
    if agg_order_flow_imb is not None:
        out["D12f_agg_order_flow_imb"] = agg_order_flow_imb
    del close
    return out


# ============================================================================
# GRUPO H — on-chain (5 candidatas computáveis; granularidade diária,
# constante por ~96 barras de 15m consecutivas -- mesma ressalva já
# registrada no PRD §2.9, "features de contexto de regime, não de
# entrada" -- computadas mesmo assim, sem curadoria).
# ============================================================================


def group_h_research(onchain_aligned: pl.DataFrame) -> dict[str, FloatArray]:
    flow_in = onchain_aligned["FlowInExUSD"].to_numpy().astype(np.float64)
    flow_out = onchain_aligned["FlowOutExUSD"].to_numpy().astype(np.float64)
    netflow = flow_in - flow_out
    active_addr = onchain_aligned["AdrActCnt"].to_numpy().astype(np.float64)
    mvrv = onchain_aligned["CapMVRVCur"].to_numpy().astype(np.float64)
    hash_rate = onchain_aligned["HashRate"].to_numpy().astype(np.float64)
    sply_cur = onchain_aligned["SplyCur"].to_numpy().astype(np.float64)
    sply_ex = onchain_aligned["SplyExNtv"].to_numpy().astype(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        exchange_balance_pct = sply_ex / sply_cur
    return {
        "H01_exchange_netflow_z": support.expanding_zscore_strict(netflow),
        "H02_exchange_balance_pct": exchange_balance_pct,
        "H03_active_addresses_z": support.expanding_zscore_strict(active_addr),
        "H06_mvrv_z": support.expanding_zscore_strict(mvrv),
        "H08_hash_rate_z": support.expanding_zscore_strict(hash_rate),
    }


# ============================================================================
# GRUPO K — temporal e calendário (6 candidatas, determinísticas)
# ============================================================================

# Datas de halving do BTC (fato público, LITERATURE — não ASSUMED; fonte:
# anúncio da rede Bitcoin, blocos 210000/420000/630000/840000).
_HALVING_DATES_MS: tuple[int, ...] = (
    1354060800000,  # 2012-11-28
    1467993600000,  # 2016-07-09
    1589155200000,  # 2020-05-11
    1713571200000,  # 2024-04-20
)

# Fronteiras de sessão em hora UTC (convenção padrão de mercado — Asia/
# Europe/US — literatura de trading, não medição própria; citação: sessões
# Tóquio/Londres/Nova York em UTC aproximado).
_SESSION_ASIA_START_UTC = 0
_SESSION_EUROPE_START_UTC = 7
_SESSION_US_START_UTC = 13


def group_k_research(open_time_ms: FloatArray) -> dict[str, FloatArray]:
    # Constantes de calendário (conversão de unidade, não parametro de
    # dominio): ms/hora, horas/dia, ms/dia, dias/semana.
    ms_per_hour = 3_600_000.0  # noqa: magic-number
    hours_in_day = 24.0  # noqa: magic-number
    ms_per_day = 86_400_000.0  # noqa: magic-number
    days_in_week = 7.0  # noqa: magic-number
    hour_of_day = (open_time_ms // int(ms_per_hour)) % int(hours_in_day)
    # 1970-01-01 (epoch dia 0) foi uma quinta-feira -- +4 desloca a
    # convenção pra 0=domingo, 6=sábado (verificado empiricamente contra
    # 2024-01-06/07, sábado/domingo conhecidos). Fim de semana = {0,6}
    # NESSA convenção, não {5,6} (que seria sexta/sábado).
    day_of_week = ((open_time_ms // int(ms_per_day)) + 4) % int(days_in_week)

    hour_sin = np.sin(2 * np.pi * hour_of_day / hours_in_day)
    hour_cos = np.cos(2 * np.pi * hour_of_day / hours_in_day)
    dow_sin = np.sin(2 * np.pi * day_of_week / days_in_week)
    dow_cos = np.cos(2 * np.pi * day_of_week / days_in_week)
    is_weekend = ((day_of_week == 0) | (day_of_week == 6)).astype(float)

    is_asia = (hour_of_day >= _SESSION_ASIA_START_UTC) & (hour_of_day < _SESSION_EUROPE_START_UTC)
    is_europe = (hour_of_day >= _SESSION_EUROPE_START_UTC) & (hour_of_day < _SESSION_US_START_UTC)
    session_asia = is_asia.astype(float)
    session_europe = is_europe.astype(float)
    session_us = (hour_of_day >= _SESSION_US_START_UTC).astype(float)

    last_halving = np.full(open_time_ms.shape[0], np.nan, dtype=np.float64)
    for h in _HALVING_DATES_MS:
        mask = open_time_ms >= h
        last_halving[mask] = h
    days_since_halving = (open_time_ms - last_halving) / ms_per_day

    return {
        "K01_hour_sin": hour_sin,
        "K01_hour_cos": hour_cos,
        "K02_dow_sin": dow_sin,
        "K02_dow_cos": dow_cos,
        "K03_is_weekend": is_weekend,
        "K04_session_asia": session_asia,
        "K04_session_europe": session_europe,
        "K04_session_us": session_us,
        "K08_days_since_halving": days_since_halving,
    }
