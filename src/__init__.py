"""Hierarquia de camadas do motor BTCUSDT (PRD V3.3 §14.2), verificada
estaticamente por import-linter (contratos em pyproject.toml [tool.importlinter]):

    exchange -> data -> features -> labels -> regime -> models -> validation
                                                            |
                              backtest <- risk <- execution <- live

Regras explícitas do PRD, mais fortes que a leitura literal do diagrama acima:
  - features/   NAO pode importar labels/
  - models/     NAO pode importar execution/
  - labels/     só é lido por models/, validation/, backtest/ (todo o resto proibido)
  - models.alpha NAO pode importar models.meta (zero realimentação, §5.8) —
    contrato a formalizar quando alpha.py/meta.py existirem (Sprint 8+)

Violação quebra o build (CI). Nao é convenção — é invariante.
"""

from __future__ import annotations
