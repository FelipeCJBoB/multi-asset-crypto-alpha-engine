"""R2 (`CLAUDE.md` §0.2, uma das cinco restrições invioláveis) — núcleo
puro POR LINHA, compartilhado entre medição pós-hoc e treino real.

**Por que isto mora aqui, e não só em `src/analysis/r2_
admissibility_census.py`.** Até 2026-08-27 este núcleo vivia inteiro em
`analysis/` — correto enquanto só alimentava um censo DECISION-SUPPORT
(`run_r2_admissibility_census`, nunca lido por nenhum pipeline de treino).
Achado real (handoff de `src/models/`, 2026-08-27, `AG-296`/`AG-297`): R2
nunca era aplicada em `src/models/` — `src.models.dataset.side_subset`
não filtra por ela, e `src.labels.weights.apply_weights` (`sample_weight
= uniqueness * |ret_net|`) dá peso MAIOR às linhas mais catastróficas,
incluindo as que violam R2. Medido contra `data/labels/BNBUSDT/R1/v1/
labels.parquet`: até 27% das linhas violam R2 (`experiments/r2_
admissibility_census.json`).

`side_subset` (camada `models/`) precisa desta fórmula pra filtrar antes
do treino — e `models/` não pode importar `analysis/` (`CLAUDE.md`, Layer
hierarchy; `pyproject.toml::[tool.importlinter]`, contrato "models não
importa analysis"). Mover o núcleo PURO (`cost_fraction`/`stop_fraction`/
`viola_r2`) pra `labels/` (camada que `models`, `validation`, `backtest`
E `analysis` podem ler) fecha essa violação antes que ela aconteça, mesmo
padrão já usado pra `economic_gate` (`src/models/economic_gate.py`,
2026-08-27). `src/analysis/r2_admissibility_census.py` reimporta estas
três funções DE VOLTA daqui — direção permitida (`analysis` pode ler
`labels`, nenhum contrato proíbe). O que NÃO migrou: `gain_fraction`/
`breakeven_probability`/o censo inteiro (`census_from_arrays`,
`run_r2_admissibility_census`) — são diagnóstico pós-hoc (o breakeven por
linha), não a restrição R2 em si, e continuam só em `analysis/`.

**A régua em si** (não muda com a mudança de arquivo): `custo_round_trip
<= cost_stop_ratio_max * stop`. Como `stop` de produção é `sl_atr_mult *
ATR(t0)` e o ATR varia barra a barra, R2 não é uma propriedade da célula
— é uma propriedade da LINHA. Ver a docstring de
`src.analysis.r2_admissibility_census` pro contexto completo de medição.

Núcleo puro (Idioma A, §Núcleo funcional do `CLAUDE.md`): as três funções
recebem arrays em memória e devolvem arrays em memória. Zero IO."""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]

_BPS_PER_UNIT: Final[float] = 10_000.0  # noqa: magic-number -- conversão de unidade


def cost_fraction(cost_entry_bps: FloatArray, cost_exit_bps: FloatArray) -> FloatArray:
    """Custo de ida e volta como fração do nocional (bps -> fração)."""
    return np.asarray((cost_entry_bps + cost_exit_bps) / _BPS_PER_UNIT, dtype=np.float64)


def stop_fraction(entry_price: FloatArray, sl_price: FloatArray) -> FloatArray:
    """`|SL - entrada| / entrada`. Vale para os dois lados por construção:
    em `side=+1` o SL fica abaixo da entrada, em `side=-1` acima (verificado
    contra `labels.parquet`), e o módulo da diferença é a mesma grandeza
    econômica nos dois casos."""
    return np.asarray(np.abs(sl_price - entry_price) / entry_price, dtype=np.float64)


def viola_r2(cost: FloatArray, stop: FloatArray, *, cost_stop_ratio_max: float) -> BoolArray:
    """R2 literal (`CLAUDE.md` §0.2): `custo_round_trip <= ratio * stop`.
    Devolve a máscara do que **viola**."""
    return np.asarray(cost > (cost_stop_ratio_max * stop), dtype=np.bool_)
