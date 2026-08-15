"""Testes de `src/analysis/__init__.py` -- achado CRITICAL de auditoria
(`audit_engineering`, 2026-08-15): o `__init__.py` importava
`attribution.py` (numpy/polars/scipy) incondicionalmente. Python sempre
termina de executar o `__init__.py` de um pacote ANTES de importar
qualquer submódulo dele -- então `from src.analysis.m2_worker import
(...)` disparava `attribution.py`, e portanto numpy/polars/scipy, ANTES
do bloco `os.environ.setdefault(OMP_NUM_THREADS=1, ...)` de
`m2_worker.py`/`m2_bar_comparison.py` ter qualquer chance de rodar --
neutralizando as duas defesas redundantes contra oversubscription de BLAS
por completo (causa raiz plausível do `_ArrayMemoryError` já observado em
produção nesta sessão).

Os testes aqui rodam em SUBPROCESSO LIMPO, nunca no processo do próprio
pytest (que já tem numpy importado via outros arquivos de teste, o que
mascararia o bug) -- mesma disciplina que a revisão desta sessão exigiu
de `warm_tick_imbalance_cache.py`: medir através de fronteira de
PROCESSO de verdade, não assumir pela leitura do código nem por uma
chamada repetida no mesmo processo."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_script(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.slow
def test_import_src_analysis_nao_importa_numpy_transitivamente() -> None:
    """O fix real: importar só o pacote `src.analysis` (sem acessar
    `feature_agreement`/`gain_by_side`/`ic_by_regime`) não deveria puxar
    `attribution.py` -- e portanto não deveria puxar numpy -- por conta do
    import preguiçoso (PEP 562 `__getattr__`). Esta é a checagem que
    diretamente falsificaria a regressão: antes do fix, este assert
    falhava."""
    script = (
        "import sys\n"
        "import src.analysis\n"
        "assert 'numpy' not in sys.modules, ("
        "'src.analysis.__init__ ainda importa numpy transitivamente -- '"
        "'a preguica do __getattr__ quebrou'"
        ")\n"
        "print('OK')\n"
    )
    result = _run_script(script)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout


@pytest.mark.slow
def test_import_src_analysis_m2_worker_nao_importa_numpy_antes_do_bloco_env_vars() -> None:
    """Regressão direta do achado CRITICAL: `from src.analysis.m2_worker
    import (...)` -- a forma real como `m2_bar_comparison.py` importa e
    como o Windows `spawn` reconstrói cada worker -- não deveria disparar
    `attribution.py`/numpy por trás do `__init__.py` do pacote. Roda ANTES
    de `m2_worker` ser importado, então numpy só deveria aparecer em
    `sys.modules` DEPOIS que o bloco `os.environ.setdefault` do próprio
    `m2_worker.py` já rodou (o import de `numpy`/`polars`/`duckdb` que
    `m2_worker.py` faz por conta própria vem DEPOIS do bloco de env vars no
    arquivo -- ver `src/analysis/m2_worker.py`)."""
    script = (
        "import os, sys\n"
        "assert 'numpy' not in sys.modules\n"
        "from src.analysis.m2_worker import compute_time_bar_for_symbol\n"
        "for var in ("
        "'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', "
        "'NUMEXPR_NUM_THREADS', 'POLARS_MAX_THREADS'"
        "):\n"
        "    assert os.environ.get(var) == '1', f'{var}={os.environ.get(var)!r}'\n"
        "print('OK')\n"
    )
    result = _run_script(script)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout
