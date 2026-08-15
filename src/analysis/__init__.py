"""Camada analysis — atribuição de importância de feature PÓS-HOC
(`attribution.py`: IC de Spearman por regime, gain do XGBoost por lado,
concordância entre os dois). Lê resultado REALIZADO (`ret_net`,
`barrier_hit`) e diagnóstico já persistido em disco — NUNCA insumo de
treino ou seleção de feature (ver docstring de `attribution.py`).

`src.models` e `src.features` não podem importar `src.analysis`
(`pyproject.toml [tool.importlinter]`, contratos "models não importa
analysis" / "features não importa analysis") — a separação é estrutural,
não só documentada.

**Import preguiçoso (PEP 562), não incondicional -- achado CRITICAL de
auditoria (`audit_engineering`, 2026-08-15).** `attribution.py` importa
`numpy`/`polars`/`scipy` no escopo do módulo, sem guarda. Python sempre
termina de executar o `__init__.py` de um pacote ANTES de importar
qualquer submódulo dele -- então `from src.analysis.m2_worker import
(...)` (ou o unpickle de qualquer função de `m2_worker` sob `spawn` em
cada processo filho) disparava este arquivo primeiro e, com o import
incondicional antigo, `attribution.py` -- e portanto numpy/polars/scipy
-- ANTES que o bloco `os.environ.setdefault(OMP_NUM_THREADS=1, ...)` de
`m2_worker.py`/`m2_bar_comparison.py` tivesse qualquer chance de rodar.
Neutralizava as duas defesas redundantes contra oversubscription de BLAS
daqueles dois arquivos por completo -- causa raiz plausível do
`numpy._core._exceptions._ArrayMemoryError` já observado em produção
nesta sessão. `feature_agreement`/`gain_by_side`/`ic_by_regime` agora só
importam `attribution.py` (e portanto numpy/polars/scipy) no primeiro
ACESSO ao atributo, não na execução deste arquivo -- nenhum consumidor
real hoje usa `from src.analysis import feature_agreement` (todos usam
`from src.analysis import attribution as attr`/`import ...`, confirmado
por grep antes desta mudança), então o comportamento observável não
muda pra ninguém, só o MOMENTO em que numpy é importado."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .attribution import feature_agreement, gain_by_side, ic_by_regime

__all__ = ["feature_agreement", "gain_by_side", "ic_by_regime"]

_LAZY_ATTRS = frozenset(__all__)


def __getattr__(name: str) -> Any:
    if name in _LAZY_ATTRS:
        from . import attribution

        return getattr(attribution, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
