"""Checagem manual do cache Numba de `_tick_imbalance_loop`
(`src/data/bars.py`) através de FRONTEIRA DE PROCESSO real -- reusa
`src.analysis.m2_worker.warm_numba_cache_in_worker` (mesma função usada
como `initializer` do pool real em `m2_bar_comparison.py`).

**Correção de metodologia (achado de auditoria `audit_engineering`,
2026-08-15): a versão anterior chamava a função 2x no MESMO processo --
isso só demonstra a memoização em MEMÓRIA do `Dispatcher` do Numba, que
acontece com ou sem `cache=True` e não prova nada sobre reuso do cache em
DISCO entre processos (o mecanismo que de fato importa pra
`ProcessPoolExecutor`, onde cada worker é um processo novo).** Este
script agora roda a função em 2 SUBPROCESSOS separados de verdade --
compare o `elapsed_s` das duas linhas de log impressas: se o cache em
disco estiver funcionando, a 2ª invocação (processo novo, mas cache já
escrito pela 1ª) deveria ser sensivelmente mais rápida que a 1ª (que
compila do zero se `__pycache__` estiver limpo).

Motivação (achado de auditoria, corrigido nesta sessão -- ver docstring
de `m2_worker.warm_numba_cache_in_worker`): `numba/numba#8755` documenta
um hang de PROCESSO ÚNICO no Windows (`ensure_cache_path()` travando
sob certas condições de permissão do diretório de cache), não uma
corrida entre processos concorrentes -- rodar isolado, aqui ou via o
`initializer` do pool, não elimina esse hang, só o move pra mais cedo
(mais fácil de diagnosticar) e o mantém isolado por processo."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WARM_CALL = "from src.analysis.m2_worker import warm_numba_cache_in_worker as w; w()"


def _run_once(label: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _WARM_CALL],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    logger.info(
        "diagnostics.warm_tick_imbalance_cache.subprocess_done",
        label=label,
        returncode=result.returncode,
        stdout=result.stdout.strip() or None,
        stderr=result.stderr.strip() or None,
    )


def main() -> None:
    _run_once("1a invocacao")
    _run_once("2a invocacao")


if __name__ == "__main__":
    main()
