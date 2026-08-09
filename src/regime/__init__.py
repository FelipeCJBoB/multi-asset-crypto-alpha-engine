"""Camada regime — classificador determinístico por quantis expansivos
(§4), gatilhos de stress. Importa features/.

Sprint 5: `classifier.py` (R0-R5 + histerese/confirmação + eixo econômico),
`stress.py` (gatilhos S1-S10), `build.py` (IO — monta
`data/regimes/{version}/regimes.parquet`). Nunca importa `src.labels`
(§14.2, verificado estaticamente por `import-linter`)."""

from __future__ import annotations
