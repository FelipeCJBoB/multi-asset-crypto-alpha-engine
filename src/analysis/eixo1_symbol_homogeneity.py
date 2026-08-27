"""Teste de homogeneidade entre símbolos do eixo 1 (`AG-328`).

**Por que existe.** O eixo 1 (`feature_promotion_criterion.py`, `AG-294`)
testa `binomial(n_symbols=5, p_symbol_empírico)`, tratando os 5 símbolos
como ensaios de Bernoulli i.i.d. de taxa comum. `docs/investigacao_
falso_negativo_eixo1_2026-08-26.md` (auditoria independente) mediu isso
como FALSO nos próprios dados: de 24 pares (feature,símbolo)-descoberta,
15 (62,5%) são `BNBUSDT` — taxa de descoberta de `BNBUSDT` (~20,8% das 72
features) é ~6,7× a taxa combinada dos outros 4 símbolos (~3,1%), com
contagem de barras comparável entre os 5 (não é histórico mais curto). Este
módulo formaliza esse achado como teste estatístico — qui-quadrado de
homogeneidade de proporções (tabela de contingência `n_symbols × 2`, símbolo
× descoberta/não-descoberta sobre as 72 features) — em vez de uma leitura
visual da tabela.

**O que este módulo NÃO faz.** Não corrige o modelo binomial pooled — só
testa formalmente se a premissa de homogeneidade que ele assume é
sustentável. Se `p_value < alpha` (rejeita homogeneidade), o modelo
`binomial(5, p_symbol)` de `feature_promotion_criterion.py` está
mal-especificado e a tabela `k>=1..5` dele não deve ser lida como calibrada;
a decisão de trocar por outro modelo (número efetivo de testes ajustado por
correlação, residualizar o fator de mercado comum, Fama-MacBeth) é do
Manager — ver `docs/investigacao_falso_negativo_eixo1_2026-08-26.md` §3.2.

Núcleo puro (Idioma A): `discovery_matrix_from_report`,
`test_symbol_homogeneity` — recebem dados já em memória, zero IO. A casca
(`run_symbol_homogeneity_report`) lê o relatório real do eixo 1 e persiste.

Referências: `docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md`
§14.9-§14.10; `docs/investigacao_falso_negativo_eixo1_2026-08-26.md` §3.2,
§4.3, §8 (item 2 da ordem de correção recomendada)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import structlog
from scipy.stats import chi2_contingency

logger = structlog.get_logger(__name__)

EXPERIMENTS_DIR: Final[Path] = Path("experiments")
SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")

#: Nível de significância do teste de homogeneidade -- convenção estatística
#: genérica (não hiperparâmetro do projeto), declarado a priori, mesma
#: classe de `ic_by_horizon._T_SIGNIFICANCE`. Fora do escopo de
#: `provenance` de `constants.yaml`.
DEFAULT_ALPHA: Final[float] = 0.05  # noqa: magic-number -- convencao estatistica, ver docstring


class Eixo1SymbolHomogeneityError(RuntimeError):
    """Erro estrutural -- artefato de origem ausente ou entrada vazia."""


# ============================================================================
# Núcleo puro — zero IO (Idioma A)
# ============================================================================


def discovery_matrix_from_report(
    por_feature: Sequence[Mapping[str, Any]], symbols: Sequence[str]
) -> dict[str, dict[str, bool]]:
    """`{feature: {symbol: bool}}` reconstruído de `por_feature` (lista com
    campos `feature`/`symbols_discovery`) do relatório real
    (`feature_promotion_criterion_report.json`). Um símbolo ausente de
    `symbols_discovery` conta como `False` -- o relatório só lista os
    símbolos que efetivamente descobriram."""
    out: dict[str, dict[str, bool]] = {}
    for entry in por_feature:
        feature = str(entry["feature"])
        discovered = set(entry.get("symbols_discovery", []))
        out[feature] = {s: (s in discovered) for s in symbols}
    return out


@dataclass(frozen=True, slots=True)
class SymbolHomogeneityResult:
    symbols: tuple[str, ...]
    n_features: int
    discoveries_by_symbol: dict[str, int]
    rate_by_symbol: dict[str, float]
    chi2_statistic: float
    p_value: float
    degrees_of_freedom: int
    homogeneo: bool


def test_symbol_homogeneity(
    discovery_matrix: Mapping[str, Mapping[str, bool]],
    *,
    symbols: Sequence[str],
    alpha: float,
) -> SymbolHomogeneityResult:
    """Qui-quadrado de homogeneidade de proporções (tabela `len(symbols) x
    2`, símbolo × descoberta/não-descoberta) sobre `discovery_matrix`.

    `homogeneo=True` se `p_value >= alpha` (não rejeita a hipótese de taxa
    comum entre símbolos) -- é exatamente a premissa que
    `binomial(n_symbols, p_symbol)` de `feature_promotion_criterion.py`
    precisa para ser válida.

    **Ressalva de poder da revisão independente (2026-08-26):** com poucas
    descobertas totais (contagem esperada por célula perto de ~5, no limite
    usual de validade da aproximação assintótica qui-quadrado), o `p_value`
    literal pode ser impreciso mesmo quando a conclusão QUALITATIVA (rejeita
    ou não homogeneidade) é robusta a esse ruído — o achado real de `AG-328`
    (BNBUSDT ~6,7× os outros 4) é grande o bastante pra não depender dessa
    aproximação. Se o `p_value` estiver perto do `alpha` em vez de
    claramente de um lado, considerar um teste exato (Fisher generalizado)
    ou simulação de permutação como verificação cruzada antes de decidir.

    Raises:
        Eixo1SymbolHomogeneityError: `discovery_matrix` vazio, ou `alpha`
            fora de `(0, 1)`.
    """
    if not 0.0 < alpha < 1.0:
        raise Eixo1SymbolHomogeneityError(f"alpha={alpha!r} fora de (0, 1)")
    n_features = len(discovery_matrix)
    if n_features == 0:
        raise Eixo1SymbolHomogeneityError("discovery_matrix vazio -- nada para testar")

    discoveries_by_symbol = {
        s: sum(1 for by_symbol in discovery_matrix.values() if by_symbol.get(s, False))
        for s in symbols
    }
    table = np.array(
        [[discoveries_by_symbol[s], n_features - discoveries_by_symbol[s]] for s in symbols],
        dtype=np.float64,
    )
    chi2_stat, p_value, dof, _expected = chi2_contingency(table)
    rate_by_symbol = {
        s: discoveries_by_symbol[s] / n_features  # noqa: unguarded-ratio -- n_features>0 verificado acima
        for s in symbols
    }
    return SymbolHomogeneityResult(
        symbols=tuple(symbols),
        n_features=n_features,
        discoveries_by_symbol=discoveries_by_symbol,
        rate_by_symbol=rate_by_symbol,
        chi2_statistic=float(chi2_stat),
        p_value=float(p_value),
        degrees_of_freedom=int(dof),
        homogeneo=bool(p_value >= alpha),
    )


# ============================================================================
# Casca — resolve arquivo, lê e persiste.
# ============================================================================


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


def run_symbol_homogeneity_report(
    *,
    symbols: Sequence[str] = SYMBOLS,
    alpha: float = DEFAULT_ALPHA,
    out_dir: Path = EXPERIMENTS_DIR,
) -> Path:
    """Casca: lê `experiments/feature_promotion_criterion_report.json` (já
    persistido por `AG-294`, não recomputa nada), testa homogeneidade entre
    símbolos e persiste `experiments/eixo1_symbol_homogeneity_report.json`.

    Raises:
        Eixo1SymbolHomogeneityError: relatório de origem ausente.
    """
    source_path = out_dir / "feature_promotion_criterion_report.json"
    if not source_path.exists():
        raise Eixo1SymbolHomogeneityError(
            f"relatório do eixo 1 não encontrado em {source_path.resolve()} -- "
            "rode src.analysis.feature_promotion_criterion antes."
        )
    with source_path.open(encoding="utf-8") as fh:
        report = json.load(fh)

    por_feature = report.get("por_feature", [])
    matrix = discovery_matrix_from_report(por_feature, symbols)
    resultado = test_symbol_homogeneity(matrix, symbols=symbols, alpha=alpha)

    payload: dict[str, Any] = {
        "task": "eixo1_symbol_homogeneity",
        "pergunta": "Os 5 simbolos tem taxa de descoberta homogenea -- premissa que "
        "binomial(n_symbols, p_symbol) de feature_promotion_criterion.py exige? "
        "AG-328.",
        "adr_ref": "docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md §14.9/§14.10; "
        "docs/investigacao_falso_negativo_eixo1_2026-08-26.md §3.2, §4.3, §8 item 2",
        "metodo": "qui-quadrado de homogeneidade de proporcoes (scipy.stats."
        "chi2_contingency), tabela simbolo x descoberta/nao-descoberta sobre as "
        "features do relatorio real do eixo 1. NAO recomputa o eixo 1 -- le o "
        "relatorio ja persistido.",
        "fonte": str(source_path.resolve()),
        "alpha": alpha,
        **asdict(resultado),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    report_path = _write_atomic(
        out_dir / "eixo1_symbol_homogeneity_report.json",
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    logger.info(
        "analysis.eixo1_symbol_homogeneity.done",
        report_path=str(report_path.resolve()),
        homogeneo=resultado.homogeneo,
        p_value=round(resultado.p_value, 6),
        rate_by_symbol=resultado.rate_by_symbol,
    )
    return report_path


if __name__ == "__main__":  # pragma: no cover -- execução manual
    import argparse

    parser = argparse.ArgumentParser(
        description="Teste de homogeneidade entre simbolos do eixo 1 (AG-328)."
    )
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    args = parser.parse_args()

    out_path = run_symbol_homogeneity_report(symbols=tuple(args.symbols), alpha=args.alpha)
    logger.info("analysis.eixo1_symbol_homogeneity.cli_done", report_path=str(out_path.resolve()))
