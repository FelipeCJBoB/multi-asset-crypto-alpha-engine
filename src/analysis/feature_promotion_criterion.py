"""Eixo 1 do critério de evidência (ADR-005 §2.2), corrigido — `AG-270`.

**O erro que este módulo corrige.** `ADR-005 §2.2` calibrava o eixo 1 sob
`binomial(15; 0,146)`, tratando as 15 células `(5 símbolos × 3 resoluções)`
como 15 ensaios INDEPENDENTES. `project_assurance` mediu: 197 de 275 blocos
símbolo×feature (72%) são perfeitamente concordantes nas 3 resoluções — são
a MESMA série de preço sob threshold diferente, não observações
independentes. A unidade de independência real é o SÍMBOLO (5), não a
célula (15).

**O que este módulo faz.** Reproduz o eixo 1 do zero, com a correção:

1. Para cada célula `(resolution, symbol)`, aplica Benjamini-Hochberg
   `q=0,10` sobre os 72 p-valores (um por feature, derivado de `pico_abs_t`
   de `experiments/ic_by_horizon_report_{R1,R2,R3}.json` via normal
   padrão — mesma convenção de `economic_gate.py`, `z`/CI, não t de
   Student) — isso NÃO estava em código antes; o `pico_significativo`
   persistido nos relatórios usa limiar fixo `|t|>=2`, sem correção de
   múltiplos testes. É a peça que faltava pra "10,5 descobertas por
   célula" da v1 ser reproduzível, não só citada.
2. Agrega as 3 resoluções de um símbolo por MAIORIA (`>=2 de 3`
   descobertas) — um símbolo só conta como "achado" se o sinal aparece na
   maioria das grades, não em uma célula isolada.
3. Mede `p_símbolo` EMPIRICAMENTE (fração observada de pares
   feature×símbolo que são maioria-descoberta, sobre as 72 features) — não
   assume que `p_símbolo = p_célula` antigo (`0,146`) sem medir.
4. Reexpressa a tabela do §2.2 em `binomial(5; p_símbolo)`.

**O que este módulo NÃO faz.** Não corrige o "peak-hunting" dentro de uma
feature (`pico_abs_t` já é o máximo sobre ~7 horizontes testados por
feature — um segundo problema de múltiplos testes, ortogonal ao que
`AG-270` levantou). Não decide o eixo 2 (estabilidade temporal, §2.2). Não
promove/aposenta nenhuma coluna — devolve a tabela corrigida, a decisão
de que fazer com o resultado é do Manager (mesmo espírito de
`production_grade_gate.py`, DECISION-SUPPORT)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import structlog
from scipy.stats import binom, norm

from src.labels._constants import load_constant

logger = structlog.get_logger(__name__)

EXPERIMENTS_DIR: Final[Path] = Path("experiments")
RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")

#: Maioria de 3 resoluções -- >=2 conta como símbolo-descoberta (§Eixo 1).
_MAJORITY_OF_THREE: Final[int] = 2


class FeaturePromotionCriterionError(RuntimeError):
    """Erro estrutural -- artefato de origem ausente ou schema inesperado."""


# ============================================================================
# Núcleo puro — zero IO (Idioma A)
# ============================================================================


def two_sided_p_from_t(abs_t: float) -> float:
    """`p = 2 * (1 - Φ(|t|))` -- normal padrão, não t de Student (mesma
    convenção de `economic_gate.py`/`z=1,96`). `abs_t` já vem não-negativo
    dos relatórios de origem (`pico_abs_t`); negativo é erro de dado."""
    if abs_t < 0.0:
        raise FeaturePromotionCriterionError(f"abs_t={abs_t!r} negativo -- não é |t|")
    return float(2.0 * norm.sf(abs_t))


def p_value_from_feature_entry(entry: Mapping[str, Any]) -> float:
    """`two_sided_p_from_t(pico_abs_t)`, com um caso de borda REAL: uma
    coluna 100% morta (todo horizonte com `n_points=0`, `ic=NaN`) não tem
    `pico_abs_t` no relatório -- `D07f_taker_imbalance_1m_agg` é
    exatamente esse caso nas 15 células (dead-column sob dollar bar,
    achado independente do `AG-213`/§13 do ADR-005). `p=1,0` (nunca
    descoberta) é a leitura correta, não um erro: sem dado, não há
    evidência de sinal -- e mantém a coluna no denominador `m` do BH
    (ela FOI testada, só não produziu estatística), em vez de mudar
    silenciosamente quantas features entram na correção de múltiplos
    testes."""
    pico_abs_t = entry.get("pico_abs_t")
    if pico_abs_t is None:
        return 1.0
    return two_sided_p_from_t(float(pico_abs_t))


def benjamini_hochberg(p_values: Sequence[float], *, q: float) -> list[bool]:
    """Procedimento BH clássico: ordena os `m` p-valores, acha o maior `i`
    tal que `p_(i) <= (i/m)*q`, rejeita (marca descoberta) todo `p <=`
    esse corte. Devolve booleanos na ORDEM ORIGINAL de `p_values`, não na
    ordem ordenada -- quem chama não precisa desfazer o sort."""
    m = len(p_values)
    if m == 0:
        return []
    if not 0.0 < q < 1.0:
        raise FeaturePromotionCriterionError(f"q={q!r} fora de (0, 1)")
    order = sorted(range(m), key=lambda i: p_values[i])
    threshold = 0.0
    for rank, idx in enumerate(order, start=1):
        if p_values[idx] <= (rank / m) * q:
            threshold = p_values[idx]
    return [p <= threshold for p in p_values]


def symbol_is_majority_discovery(resolution_discoveries: Sequence[bool]) -> bool:
    """Um símbolo conta como "achado" se a MAIORIA das suas resoluções
    (`>=2` de 3) forem descoberta BH -- não uma célula isolada. `AG-270`:
    197/275 blocos símbolo×feature são concordantes nas 3 resoluções
    (mesma série de preço, threshold diferente) -- maioria evita que 1
    resolução ruidosa decida o símbolo sozinha."""
    if len(resolution_discoveries) != 3:
        raise FeaturePromotionCriterionError(
            f"esperado 3 resoluções, recebido {len(resolution_discoveries)}"
        )
    return sum(resolution_discoveries) >= _MAJORITY_OF_THREE


def expected_count_at_least_k(
    *, n_features: int, n_symbols: int, p_symbol: float, k: int
) -> float:
    """`n_features * P(X >= k)` sob `binomial(n_symbols, p_symbol)` --
    quantas features, entre `n_features`, teriam `>= k` símbolos-descoberta
    POR ACASO, se cada símbolo fosse um ensaio Bernoulli independente de
    taxa `p_symbol`. Mesma forma da tabela original do §2.2, unidade
    trocada de célula (15) para símbolo (`n_symbols`, tipicamente 5)."""
    if not 0.0 <= p_symbol <= 1.0:
        raise FeaturePromotionCriterionError(f"p_symbol={p_symbol!r} fora de [0, 1]")
    if k <= 0:
        return float(n_features)
    if k > n_symbols:
        return 0.0
    prob_at_least_k = float(binom.sf(k - 1, n_symbols, p_symbol))
    return n_features * prob_at_least_k


@dataclass(frozen=True, slots=True)
class FeatureSymbolCount:
    feature: str
    n_symbols_discovery: int
    symbols_discovery: tuple[str, ...]


def build_symbol_counts(
    discovery_by_feature_symbol: Mapping[str, Mapping[str, bool]],
) -> list[FeatureSymbolCount]:
    """Núcleo: agrega o mapa `{feature: {symbol: bool}}` (já resolvido por
    maioria, um bool por símbolo) em contagem por feature. Ordenado por
    contagem decrescente -- a mais reproduzida primeiro."""
    rows = []
    for feature, by_symbol in discovery_by_feature_symbol.items():
        hits = tuple(sorted(sym for sym, is_hit in by_symbol.items() if is_hit))
        rows.append(FeatureSymbolCount(feature, len(hits), hits))
    return sorted(rows, key=lambda r: r.n_symbols_discovery, reverse=True)


def empirical_p_symbol(discovery_by_feature_symbol: Mapping[str, Mapping[str, bool]]) -> float:
    """Taxa base MEDIDA de símbolo-descoberta, sobre todos os pares
    feature×símbolo do painel -- não herdada do `p=0,146` de célula da v1
    sem remedir. `AG-270`: "recalcular a expectativa sob H0 por SÍMBOLO"."""
    total = 0
    hits = 0
    for by_symbol in discovery_by_feature_symbol.values():
        for is_hit in by_symbol.values():
            total += 1
            hits += int(is_hit)
    if total == 0:
        raise FeaturePromotionCriterionError("painel vazio -- p_symbol indefinido")
    return hits / total


# ============================================================================
# Casca -- resolve arquivo, lê e persiste.
# ============================================================================


def _load_reports(out_dir: Path, resolutions: Sequence[str]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for resolution_id in resolutions:
        path = out_dir / f"ic_by_horizon_report_{resolution_id}.json"
        if not path.exists():
            raise FeaturePromotionCriterionError(
                f"relatório de IC por horizonte de {resolution_id} não encontrado em "
                f"{path.resolve()} -- rode src.analysis.ic_by_horizon antes."
            )
        with path.open(encoding="utf-8") as fh:
            reports[resolution_id] = json.load(fh)
    return reports


def _discovery_by_feature_symbol_resolution(
    reports: Mapping[str, Mapping[str, Any]], *, q: float
) -> dict[str, dict[str, dict[str, bool]]]:
    """`{feature: {symbol: {resolution: bool}}}` -- BH `q` aplicado DENTRO
    de cada célula `(resolution, symbol)`, sobre os p-valores das 72
    features daquela célula (não entre células, não entre símbolos)."""
    out: dict[str, dict[str, dict[str, bool]]] = {}
    for resolution_id, report in reports.items():
        por_simbolo = report.get("por_simbolo")
        if not isinstance(por_simbolo, Mapping):
            raise FeaturePromotionCriterionError(
                f"{resolution_id}: relatório sem bloco 'por_simbolo'"
            )
        for symbol, sym_block in por_simbolo.items():
            por_feature = sym_block.get("por_feature") or {}
            features = list(por_feature.keys())
            p_values = [p_value_from_feature_entry(por_feature[f]) for f in features]
            discoveries = benjamini_hochberg(p_values, q=q)
            for feature, is_discovery in zip(features, discoveries, strict=True):
                out.setdefault(feature, {}).setdefault(str(symbol), {})[resolution_id] = (
                    is_discovery
                )
    return out


def _majority_by_feature_symbol(
    by_feature_symbol_resolution: Mapping[str, Mapping[str, Mapping[str, bool]]],
    *,
    resolutions: Sequence[str],
) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for feature, by_symbol in by_feature_symbol_resolution.items():
        out[feature] = {}
        for symbol, by_resolution in by_symbol.items():
            ordered = [by_resolution[r] for r in resolutions]
            out[feature][symbol] = symbol_is_majority_discovery(ordered)
    return out


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


def run_feature_promotion_criterion_report(
    *,
    q: float | None = None,
    resolutions: Sequence[str] = RESOLUTIONS,
    out_dir: Path = EXPERIMENTS_DIR,
    k_thresholds: Sequence[int] = (1, 2, 3, 4, 5),
) -> Path:
    """Casca: refaz o eixo 1 do §2.2 sob a unidade de independência
    corrigida (símbolo, não célula). Persiste
    `experiments/feature_promotion_criterion_report.json`. `q=None` (default)
    lê `feature_promotion_bh_q` de `constants.yaml` -- nunca `0.10`
    hardcoded (§16.10)."""
    q_bh = q if q is not None else float(load_constant("feature_promotion_bh_q"))
    reports = _load_reports(out_dir, resolutions)
    by_feature_symbol_resolution = _discovery_by_feature_symbol_resolution(reports, q=q_bh)
    by_feature_symbol = _majority_by_feature_symbol(
        by_feature_symbol_resolution, resolutions=resolutions
    )

    n_features = len(by_feature_symbol)
    n_symbols = len(next(iter(by_feature_symbol.values())))
    p_symbol = empirical_p_symbol(by_feature_symbol)
    counts = build_symbol_counts(by_feature_symbol)

    tabela = []
    for k in k_thresholds:
        observado = sum(1 for c in counts if c.n_symbols_discovery >= k)
        esperado = expected_count_at_least_k(
            n_features=n_features, n_symbols=n_symbols, p_symbol=p_symbol, k=k
        )
        tabela.append({"k": k, "esperado_sob_h0": esperado, "observado": observado})

    payload = {
        "task": "feature_promotion_criterion",
        "pergunta": "ADR-005 §2.2 eixo 1, corrigido: unidade de independencia e o SIMBOLO "
        "(5), nao a CELULA (15) -- AG-270.",
        "adr_ref": "docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md §2.2, §11 (AG-270)",
        "metodo": "BH q dentro de cada celula (resolution,symbol) sobre 72 p-valores "
        "(normal a partir de pico_abs_t); simbolo = maioria (>=2/3) das resolucoes; "
        "p_simbolo medido empiricamente sobre o painel, nao herdado do p=0,146 de celula.",
        "q_bh": q_bh,
        "n_features": n_features,
        "n_symbols": n_symbols,
        "p_symbol_empirico": p_symbol,
        "tabela_h0": tabela,
        "por_feature": [
            {
                "feature": c.feature,
                "n_symbols_discovery": c.n_symbols_discovery,
                "symbols_discovery": list(c.symbols_discovery),
            }
            for c in counts
        ],
    }

    report_path = _write_atomic(
        out_dir / "feature_promotion_criterion_report.json",
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    logger.info(
        "analysis.feature_promotion_criterion.done",
        report_path=str(report_path.resolve()),
        p_symbol_empirico=round(p_symbol, 4),
        top_feature=counts[0].feature if counts else None,
        top_n_symbols=counts[0].n_symbols_discovery if counts else None,
    )
    return report_path


if __name__ == "__main__":
    out_path = run_feature_promotion_criterion_report()
    logger.info(
        "analysis.feature_promotion_criterion.cli_done", report_path=str(out_path.resolve())
    )
