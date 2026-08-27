"""Número efetivo de símbolos independentes para o binomial do eixo 1 (`AG-328`).

**Por que existe.** `AG-328` (confirmado FORMALMENTE 2026-08-27,
`eixo1_symbol_homogeneity.py`, `χ²=30,09`, `p=4,69e-06`) rejeita a premissa
i.i.d. que `binomial(n_symbols=5, p_symbol)` de `feature_promotion_
criterion.py` assume ao calibrar a tabela `k≥1..5` sob H0 — `AG-294`. Este
módulo implementa a correção recomendada pela pesquisa externa
(`docs/investigacao_falso_negativo_eixo1_2026-08-26.md` §3.2, §9.3): em vez
de tratar os 5 símbolos como 5 ensaios independentes, mede quantos ensaios
EFETIVAMENTE independentes existem, dado quão correlacionados os
RESULTADOS DE TESTE são entre símbolos — Li & Ji (2005)/Galwey (2009),
literatura de "número efetivo de testes" para testes correlacionados
(originalmente genômica de SNPs correlacionados; aqui, `pico_abs_t` por
feature faz o papel do SNP).

**O método.** Matriz de correlação `5×5` de Pearson entre os vetores de
`pico_abs_t` (features com pico finito nos 5 símbolos simultaneamente, grade
`R1` — maior `N`, mesma convenção de §2.2 "calibração sobre BTCUSDT/R1")
de cada símbolo — mede correlação REAL dos RESULTADOS DE TESTE, não uma
proxy indireta como correlação de preço bruto (nunca medida neste repo; a
cifra "0,7-0,9" citada na investigação era estimativa de mercado, não
medição). `M_eff` via Galwey (2009): `(Σ√λᵢ)² / Σλᵢ` sobre os autovalores
POSITIVOS da matriz de correlação — forma mais simples que Li & Ji (não
precisa de piso de fração por autovalor), mesma família conceitual.

**Arredondamento, declarado.** `scipy.stats.binom` não aceita `n`
não-inteiro (verificado: `binom.sf(0, 3.7, p)` devolve `NaN`, não um valor
generalizado via função beta). `M_eff` é arredondado por `floor` antes de
entrar no binomial — direção CONSERVADORA: menos ensaios "efetivos"
creditados, não mais, então a correção nunca fica mais permissiva do que a
medição sozinha justificaria.

**O que este módulo NÃO faz.** Não decide se pooling com `M_eff` ou
residualização de fator comum (a outra opção citada em §3.2/§9.3) é a
correção certa — devolve o número efetivo medido e a tabela `k≥1..5`
recalculada com ele, para comparação lado a lado com a tabela naive
(`n_symbols=5`) que `AG-294` usa hoje. Não substitui `feature_promotion_
criterion.py` — ferramenta de diagnóstico paralela, mesma disciplina dos
outros 3 módulos irmãos (`eixo1_power_diagnostic.py`, `eixo1_symbol_
homogeneity.py`, `eixo1_maxt_horizon_permutation.py`). Decisão de adotar é
do Manager.

Núcleo puro (Idioma A): `build_symbol_statistic_matrix` (recebe o dict do
relatório já carregado, não faz IO por si), `effective_number_of_tests_
galwey` — zero IO. A casca (`run_effective_symbol_count_report`) resolve
arquivo e persiste.

Referências: `docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md`
§14.9-§14.10; `docs/investigacao_falso_negativo_eixo1_2026-08-26.md` §3.2,
§9.3."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from src.analysis.feature_promotion_criterion import expected_count_at_least_k

FloatArray = NDArray[np.float64]

EXPERIMENTS_DIR: Final[Path] = Path("experiments")
SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")

#: Grade usada pra medir a correlação entre símbolos -- R1 tem o maior N
#: (mais barras, estimativa de correlação mais estável), mesma convenção de
#: §2.2 do ADR-005 ("calibração sobre BTCUSDT/R1"). `ASSUMED`, não
#: `DERIVED` -- escolha de instrumento, não medição.
DEFAULT_RESOLUTION_ID: Final[str] = "R1"

DEFAULT_K_THRESHOLDS: Final[tuple[int, ...]] = (1, 2, 3, 4, 5)

#: Contagem naive de símbolos que `AG-294`/`feature_promotion_criterion.py`
#: usa hoje -- referência fixa pra tabela comparativa, não um parâmetro de
#: negócio.
_NAIVE_N_SYMBOLS: Final[int] = 5  # noqa: magic-number -- referencia fixa da tabela AG-294, ver docstring


class Eixo1EffectiveSymbolCountError(RuntimeError):
    """Erro estrutural -- artefato de origem ausente, símbolo ausente do
    relatório, ou matriz de correlação degenerada."""


# ============================================================================
# Núcleo puro — zero IO (Idioma A)
# ============================================================================


def build_symbol_statistic_matrix(
    report: Mapping[str, Any], symbols: Sequence[str]
) -> tuple[tuple[str, ...], FloatArray]:
    """`(nomes_das_features_usadas, matriz)` -- matriz `len(symbols) ×
    n_features_comuns` de `pico_abs_t`, uma linha por símbolo. SÓ inclui
    features com `pico_abs_t` finito nos `len(symbols)` símbolos
    SIMULTANEAMENTE -- dropa colunas com `None`/`NaN` em qualquer símbolo
    (ex. `D07f_taker_imbalance_1m_agg`, 100% NaN nas 15 células, `AG-318`)
    em vez de tratamento pairwise, que complicaria sem necessidade real: só
    1 das 72 features cai nesse caso hoje.

    Raises:
        Eixo1EffectiveSymbolCountError: algum símbolo ausente do relatório,
            ou nenhuma feature com `pico_abs_t` finito comum a todos.
    """
    por_simbolo = report.get("por_simbolo", {})
    per_symbol: dict[str, dict[str, float | None]] = {}
    for symbol in symbols:
        sym_block = por_simbolo.get(symbol)
        if sym_block is None:
            raise Eixo1EffectiveSymbolCountError(f"símbolo {symbol!r} ausente do relatório")
        por_feature = sym_block.get("por_feature", {})
        per_symbol[symbol] = {name: entry.get("pico_abs_t") for name, entry in por_feature.items()}

    common = set(per_symbol[symbols[0]].keys())
    for symbol in symbols[1:]:
        common &= set(per_symbol[symbol].keys())

    def _finite(symbol: str, feature: str) -> bool:
        value = per_symbol[symbol].get(feature)
        return value is not None and math.isfinite(value)

    usable = sorted(f for f in common if all(_finite(s, f) for s in symbols))
    if not usable:
        raise Eixo1EffectiveSymbolCountError(
            "nenhuma feature com pico_abs_t finito em todos os símbolos simultaneamente"
        )
    matrix = np.array([[per_symbol[s][f] for f in usable] for s in symbols], dtype=np.float64)
    return tuple(usable), matrix


def effective_number_of_tests_galwey(corr_matrix: FloatArray) -> float:
    """Galwey (2009): `M_eff = (Σ√λᵢ)² / Σλᵢ`, sobre os autovalores
    POSITIVOS de `corr_matrix`. Ruído de ponto flutuante pode produzir um
    autovalor levemente negativo numa matriz que é semi-definida positiva
    por construção teórica (correlação de Pearson) -- filtrado aqui, não
    tratado como erro.

    Raises:
        Eixo1EffectiveSymbolCountError: nenhum autovalor positivo (matriz
            degenerada -- não deveria acontecer com uma matriz de
            correlação válida, mas falha alto em vez de propagar NaN).
    """
    eigenvalues = np.linalg.eigvalsh(corr_matrix)
    positive = eigenvalues[eigenvalues > 0.0]
    if positive.size == 0:
        raise Eixo1EffectiveSymbolCountError(
            "nenhum autovalor positivo na matriz de correlação -- degenerada"
        )
    sum_sqrt = float(np.sum(np.sqrt(positive)))
    sum_pos = float(np.sum(positive))
    return (sum_sqrt * sum_sqrt) / sum_pos  # noqa: unguarded-ratio -- sum_pos>0 verificado acima


# ============================================================================
# Casca — resolve arquivo, lê e persiste.
# ============================================================================


def _load_ic_report(resolution_id: str, out_dir: Path) -> dict[str, Any]:
    path = out_dir / f"ic_by_horizon_report_{resolution_id}.json"
    if not path.exists():
        raise Eixo1EffectiveSymbolCountError(
            f"relatório de IC por horizonte de {resolution_id} não encontrado em "
            f"{path.resolve()} -- rode src.analysis.ic_by_horizon antes."
        )
    with path.open(encoding="utf-8") as fh:
        result: dict[str, Any] = json.load(fh)
    return result


def _load_promotion_report(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "feature_promotion_criterion_report.json"
    if not path.exists():
        raise Eixo1EffectiveSymbolCountError(
            f"relatório do eixo 1 não encontrado em {path.resolve()} -- "
            "rode src.analysis.feature_promotion_criterion antes."
        )
    with path.open(encoding="utf-8") as fh:
        result: dict[str, Any] = json.load(fh)
    return result


def _write_atomic(path: Path, content: str) -> Path:
    """B29 -- `.tmp` -> `fsync` -> `rename`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    fd = os.open(tmp, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


@dataclass(frozen=True, slots=True)
class EffectiveSymbolCountResult:
    n_features_usadas: int
    n_eff_bruto: float
    n_eff_floor: int
    correlacao_media_pares: float


def run_effective_symbol_count_report(
    *,
    symbols: Sequence[str] = SYMBOLS,
    resolution_id: str = DEFAULT_RESOLUTION_ID,
    k_thresholds: Sequence[int] = DEFAULT_K_THRESHOLDS,
    out_dir: Path = EXPERIMENTS_DIR,
) -> Path:
    """Casca: mede `M_eff` a partir do relatório real de IC por horizonte,
    lê `p_symbol_empírico`/`n_features` já persistidos por `AG-294` (não
    recomputa o eixo 1), recalcula a tabela `k≥1..5` sob `n_eff` e compara
    lado a lado com a tabela naive (`n_symbols=5`). Persiste
    `experiments/eixo1_effective_symbol_count_report.json`."""
    ic_report = _load_ic_report(resolution_id, out_dir)
    promotion_report = _load_promotion_report(out_dir)

    feature_names, matrix = build_symbol_statistic_matrix(ic_report, symbols)
    corr: FloatArray = np.asarray(np.corrcoef(matrix), dtype=np.float64)
    n_eff_bruto = effective_number_of_tests_galwey(corr)
    n_eff_floor = max(1, math.floor(n_eff_bruto))

    off_diag_mask = ~np.eye(len(symbols), dtype=bool)
    off_diagonal: FloatArray = corr[off_diag_mask]
    correlacao_media_pares = float(np.mean(off_diagonal)) if off_diagonal.size else float("nan")

    resultado = EffectiveSymbolCountResult(
        n_features_usadas=len(feature_names),
        n_eff_bruto=n_eff_bruto,
        n_eff_floor=n_eff_floor,
        correlacao_media_pares=correlacao_media_pares,
    )

    p_symbol = float(promotion_report["p_symbol_empirico"])
    n_features_total = int(promotion_report["n_features"])

    tabela: list[dict[str, Any]] = []
    for k in k_thresholds:
        esperado_naive = expected_count_at_least_k(
            n_features=n_features_total, n_symbols=_NAIVE_N_SYMBOLS, p_symbol=p_symbol, k=k
        )
        esperado_corrigido = expected_count_at_least_k(
            n_features=n_features_total, n_symbols=n_eff_floor, p_symbol=p_symbol, k=k
        )
        observado = sum(
            1
            for entry in promotion_report.get("por_feature", [])
            if int(entry.get("n_symbols_discovery", 0)) >= k
        )
        tabela.append(
            {
                "k": k,
                "esperado_naive_n5": esperado_naive,
                "esperado_corrigido_n_eff": esperado_corrigido,
                "observado": observado,
            }
        )

    payload: dict[str, Any] = {
        "task": "eixo1_effective_symbol_count",
        "pergunta": "Quantos simbolos EFETIVAMENTE independentes existem, dado o quanto "
        "os resultados de teste sao correlacionados entre eles? AG-328.",
        "adr_ref": "docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md §14.9/§14.10; "
        "docs/investigacao_falso_negativo_eixo1_2026-08-26.md §3.2, §9.3",
        "metodo": "matriz de correlacao 5x5 de Pearson entre os vetores de pico_abs_t "
        f"({resolution_id}, {resultado.n_features_usadas} features com pico finito "
        "em todos os simbolos); M_eff via Galwey (2009), (sum sqrt(lambda))^2 / "
        "sum(lambda) sobre autovalores positivos; arredondado por floor (conservador) "
        "antes de entrar no binomial -- scipy.stats.binom nao aceita n nao-inteiro.",
        "resolution_id": resolution_id,
        "symbols": list(symbols),
        **asdict(resultado),
        "p_symbol_empirico": p_symbol,
        "n_features_total": n_features_total,
        "tabela_h0_naive_vs_corrigida": tabela,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    report_path = _write_atomic(
        out_dir / "eixo1_effective_symbol_count_report.json",
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    return report_path


if __name__ == "__main__":  # pragma: no cover -- execução manual
    import argparse

    import structlog

    logger = structlog.get_logger(__name__)

    parser = argparse.ArgumentParser(
        description="Numero efetivo de simbolos independentes pro binomial do eixo 1 (AG-328)."
    )
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    parser.add_argument(
        "--resolution-id", default=DEFAULT_RESOLUTION_ID, choices=["R1", "R2", "R3"]
    )
    args = parser.parse_args()

    out_path = run_effective_symbol_count_report(
        symbols=tuple(args.symbols), resolution_id=args.resolution_id
    )
    logger.info(
        "analysis.eixo1_effective_symbol_count.cli_done", report_path=str(out_path.resolve())
    )
