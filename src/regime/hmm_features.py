"""Espaço de observação `[log_return_1, realized_vol_short]` — direto do
OHLC da dollar-bar, NUNCA do Feature Engine (mesma decisão de integração
de `src.analysis.m4_regime_comparison`, decisão #6 do plano M4 original).

Extraído de `src.analysis.m4_regime_comparison` (Fase B do plano
`wise-exploring-panda.md`, 2026-08-21) para `src.regime` — a hierarquia de
camadas (`CLAUDE.md`, `pyproject.toml::[tool.importlinter]`) proíbe
`src.regime` de importar `src.analysis`, mas `src.analysis` já importa
`src.regime` livremente; um builder de produção de regime HMM
(`src.regime.build_hmm`) precisa desta extração sem depender do harness de
comparação M4. `m4_regime_comparison.py` passa a importar `input_obs`/
`valid_start_idx` daqui (re-exportados lá como `_input_obs`/
`_valid_start_idx` para preservar os pontos de teste existentes) — mesmo
comportamento, zero mudança de resultado.

`min_periods`/warmup do início da série (achado real medido no M4, não
presumido): como `log_return_1[0]` é estruturalmente `NaN` (não existe
`close[-1]`), e `polars.rolling_std` propaga `NaN` (não `null`) por toda
janela que o contém, o primeiro valor FINITO de `realized_vol_short` só
aparece no índice `window` (não `window-1`, como seria sem o `NaN`
inicial) — `valid_start_idx` computa esse ponto programaticamente."""

from __future__ import annotations

import numpy as np
import polars as pl
from numpy.typing import NDArray

from src.features import support as features_support
from src.features._constants import load_constant as load_feature_constant

FloatArray = NDArray[np.float64]
Float2DArray = NDArray[np.float64]

__all__ = ["Float2DArray", "FloatArray", "input_obs", "valid_start_idx"]


def input_obs(bars_df: pl.DataFrame) -> tuple[FloatArray, Float2DArray]:
    """`(log_return_1, [log_return_1, realized_vol_short])`, alinhados por
    POSIÇÃO com `bars_df` (mesmo nº de linhas, mesma ordem) -- sem nenhum
    corte/trim aqui (isso é responsabilidade do caller, ver
    `valid_start_idx`/docstring do módulo). `close[t-1]` inexistente pra
    `t=0` -- `log_return_1[0]` é `NaN` por construção, não um erro de dado
    (mesmo padrão de `src.features.build.build_t1_features`/`src.
    validation.volatility_walkforward.next_bar_realized_variance`)."""
    close = bars_df["close"].cast(pl.Float64).to_numpy()
    n = close.shape[0]
    log_return_1 = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            log_return_1[1:] = np.log(
                close[1:] / close[:-1]  # noqa: unguarded-ratio -- preço real, sempre >0 por construção
            )

    short_window = int(load_feature_constant("feature_c06_vol_ratio_short_window"))
    realized_vol_short = features_support.realized_vol(log_return_1, short_window)

    obs_2d: Float2DArray = np.column_stack([log_return_1, realized_vol_short]).astype(np.float64)
    return log_return_1, obs_2d


def valid_start_idx(log_return_1: FloatArray, realized_vol_short: FloatArray) -> int:
    """Primeiro índice em que `log_return_1` E `realized_vol_short` são
    ambos finitos -- ver docstring do módulo pro achado real de que isso é
    `window`, não `window-1` (o `NaN` estrutural de `log_return_1[0]`
    propaga por toda janela que o contém). Levanta `ValueError` se a série
    inteira for inválida (curta demais pra sequer 1 barra pós-warmup)."""
    valid = np.isfinite(log_return_1) & np.isfinite(realized_vol_short)
    if not np.any(valid):
        raise ValueError(
            "valid_start_idx: nenhuma barra com log_return_1 e realized_vol_short ambos "
            "finitos -- série curta demais (<= feature_c06_vol_ratio_short_window barras)?"
        )
    return int(np.argmax(valid))
