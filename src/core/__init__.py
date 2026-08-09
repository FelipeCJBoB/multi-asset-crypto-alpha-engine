"""Camada core — utilitários transversais, sem dependência de nenhuma outra
camada do pipeline (§14.2). Primeiro (e único, nesta rodada) módulo:
`metric.py` — `Metric`/`Unit`/`safe_ratio`, o tipo de retorno para todo
valor numérico REPORTÁVEL (campo público de dataclass de resultado, nunca
cálculo intermediário de laço quente) do resto do repo.

Motivação (auditoria, ver commit): três achados na mesma família — uma
razão que "passa" um gate sem checar o sinal do denominador
(`src.models.decomposition.carry_share`), um número que circulou sem
unidade declarada, e uma contagem lida como série contínua quando eram
caminhos de CPCV somados. Em todos os três, o número certo era calculável a
partir do código, mas não vinha com metadado suficiente para interpretar
sem reler o código-fonte. `Metric` anexa esse metadado (`unit`, `n` +
`n_semantics`, `source`, `valid`/`invalid_reason`) ao valor, no próprio
tipo — não em prosa de docstring que se desatualiza.

Pacote deliberadamente pequeno — não é refatoração do repo inteiro. Só os
campos REPORTÁVEIS (retorno público de função/dataclass que vira número em
relatório ou gate) adotam `Metric`; cálculo interno permanece
`float`/`np.ndarray`."""

from __future__ import annotations

from .metric import Metric, Unit, safe_ratio

__all__ = ["Metric", "Unit", "safe_ratio"]
