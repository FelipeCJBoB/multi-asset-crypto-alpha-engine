"""Cruzamento eixo 1 x gain em producao -- AG-330, addendum 2026-08-27.

**Por que existe.** `AG-330` (`ADR-005` §14.9) mostra que o eixo 1 (IC
marginal univariado, Spearman feature x retorno futuro) mede a pergunta
ERRADA para features de papel filtro/custo -- `E27f_cost_atr_ratio` (T1,
`TESE_OK`) e "honesta como FILTRO de viabilidade e enganosa como preditor
direcional", e seu zero no eixo 1 e esperado, nao evidencia de falta de
base. O addendum de `AG-330` (2026-08-27, "investigue para propor solucao
com base no uso em producao") mediu isso manualmente contra o gain de
modelos REAIS ja treinados e confirmou a distincao -- este modulo
formaliza essa medicao num relatorio auditavel e repetivel a cada
retreino (Estagio 1 da proposta de solucao do addendum). Nao precisa de
retreino nem de codigo de treino novo: o dado ja existe em
`experiments/alpha_full_analysis_2026-08-24.json` (gain por symbol x
resolution x model_id, ja agregado por fold) e em `experiments/
feature_promotion_criterion_report.json` (contagem de descoberta do eixo
1 por feature, `AG-294`).

**O metodo.** Para cada bloco symbol x resolution x model_id (ate 30:
15 combos x {camada1, camada0}), normaliza `feature_gain.mean_gain.
pooled` em share via `src.models.hhi.compute_concentration` -- o MESMO
nucleo que producao ja usa pra HHI/concentracao (§5.8), nao reimplementa
normalizacao -- sobre o vetor T1 fixo (`T1_FEATURE_IDS`, 7 features;
feature ausente do bloco por gain=0 recebe share=0.0 explicito, contrato
de `compute_concentration`). Agrega media/min/max do share entre os
blocos por feature, e cruza com `n_symbols_discovery` do eixo 1. Baseline
de comparacao e o piso UNIFORME `1/len(T1_FEATURE_IDS)` -- estrutural
(deriva do tamanho do vetor), nao um limiar `ASSUMED` (nao precisa de
entrada em `constants.yaml`).

**Classificacao (`contradiction_flag`).** `n_symbols_discovery == 0` E
`mean_gain_share > uniform_baseline` -- feature que o eixo 1 declara "sem
replicacao direcional" mas que o modelo real usa acima da media. So
descreve o padrao, nao decide o que fazer com ele -- mesma disciplina dos
4 modulos irmaos (`eixo1_power_diagnostic.py`, `eixo1_symbol_
homogeneity.py`, `eixo1_maxt_horizon_permutation.py`, `eixo1_effective_
symbol_count.py`): ferramenta de diagnostico, decisao de uso e do
Manager.

**O que este modulo NAO faz.** Nao e importancia por permutacao
(Estagio 2 da proposta do addendum, gated no retreino represado --
nenhum booster `.bin` existe localmente hoje). `gain` e sabidamente
inflado por correlacao com outras features uteis -- ressalva ja
registrada no addendum de `AG-330` e em `src/models/hhi.py`
(`E27f_cost_atr_ratio` x `C07_vol_pctile_expanding`, ρ=-0,913 num vetor
mais amplo que o T1 atual).

Nucleo puro (Idioma A): `gain_shares_by_block`, `cross_check_features` --
zero IO. A casca (`run_gain_eixo1_cross_check_report`) resolve os dois
arquivos e persiste.

Referencias: `audit/architecture_gaps_log.yaml::AG-330` (addendum
2026-08-27); `docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md`
§13.4, §14.9."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from src.features.build import T1_FEATURE_IDS
from src.models._paths import EXPERIMENTS_DIR
from src.models.hhi import compute_concentration

ALPHA_FULL_ANALYSIS_FILENAME: Final[str] = "alpha_full_analysis_2026-08-24.json"
PROMOTION_REPORT_FILENAME: Final[str] = "feature_promotion_criterion_report.json"
OUTPUT_FILENAME: Final[str] = "eixo1_gain_cross_check_report.json"

#: Nomes de variante usados em `alpha_full_analysis_2026-08-24.json::
#: variants` -- camada1 (Alpha completo) e camada0 (baseline sem Alpha),
#: mesma convencao de `src.models.pipeline`.
MODEL_VARIANTS: Final[tuple[str, ...]] = ("camada1", "camada0")


class Eixo1GainCrossCheckError(RuntimeError):
    """Erro estrutural -- artefato de origem ausente, feature T1 ausente
    do relatorio de descoberta, ou nenhum bloco de gain encontrado."""


# ============================================================================
# Nucleo puro -- zero IO (Idioma A)
# ============================================================================


def gain_shares_by_block(
    blocks: Sequence[Mapping[str, float]], *, feature_ids: Sequence[str] = T1_FEATURE_IDS
) -> list[dict[str, float]]:
    """`blocks[i]` = `{feature: mean_gain}` de UM bloco symbol x
    resolution x model_id (`feature_gain.mean_gain.pooled` de um bloco do
    relatorio real). Devolve os shares normalizados (mesma ordem de
    `blocks`, mesma feature ausente do bloco -> `share=0.0`) via
    `src.models.hhi.compute_concentration` -- reusa o nucleo que producao
    ja usa pra HHI, nao reimplementa normalizacao."""
    return [
        dict(compute_concentration(dict(block), tuple(feature_ids)).shares) for block in blocks
    ]


@dataclass(frozen=True, slots=True)
class FeatureGainEixo1CrossCheck:
    feature: str
    n_symbols_discovery: int
    n_blocks: int
    mean_gain_share: float
    min_gain_share: float
    max_gain_share: float
    uniform_baseline: float
    above_uniform_baseline: bool
    contradiction_flag: bool


def cross_check_features(
    shares_by_block: Sequence[Mapping[str, float]],
    discovery_by_feature: Mapping[str, int],
    *,
    feature_ids: Sequence[str] = T1_FEATURE_IDS,
) -> tuple[FeatureGainEixo1CrossCheck, ...]:
    """Cruza o gain-share agregado (`shares_by_block`, ja normalizado por
    `gain_shares_by_block`) com a contagem de descoberta do eixo 1
    (`discovery_by_feature`, de `feature_promotion_criterion_report.json`
    -- cobre as 72 features candidatas, so as `feature_ids` T1 importam
    aqui). `contradiction_flag` -- ver docstring do modulo.

    Raises:
        Eixo1GainCrossCheckError: `shares_by_block` vazio, ou alguma
            feature de `feature_ids` ausente de `discovery_by_feature`.
    """
    if not shares_by_block:
        raise Eixo1GainCrossCheckError("shares_by_block vazio -- nenhum bloco pra cruzar")
    uniform_baseline = 1.0 / len(feature_ids)  # noqa: unguarded-ratio -- feature_ids nunca vazio (T1 fixo)
    results = []
    for feature in feature_ids:
        if feature not in discovery_by_feature:
            raise Eixo1GainCrossCheckError(
                f"feature {feature!r} (T1) ausente de discovery_by_feature -- "
                "feature_promotion_criterion_report.json deveria cobrir todas as "
                "features candidatas, incluindo as do T1"
            )
        values = [block.get(feature, 0.0) for block in shares_by_block]
        n_discovery = int(discovery_by_feature[feature])
        mean_share = sum(values) / len(values)  # noqa: unguarded-ratio -- shares_by_block checado acima
        above = mean_share > uniform_baseline
        results.append(
            FeatureGainEixo1CrossCheck(
                feature=feature,
                n_symbols_discovery=n_discovery,
                n_blocks=len(values),
                mean_gain_share=mean_share,
                min_gain_share=min(values),
                max_gain_share=max(values),
                uniform_baseline=uniform_baseline,
                above_uniform_baseline=above,
                contradiction_flag=(n_discovery == 0) and above,
            )
        )
    return tuple(results)


# ============================================================================
# Casca -- resolve arquivos, le e persiste.
# ============================================================================


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise Eixo1GainCrossCheckError(f"artefato nao encontrado em {path.resolve()}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _extract_gain_blocks(
    alpha_full_analysis: Sequence[Mapping[str, Any]],
    *,
    model_variants: Sequence[str] = MODEL_VARIANTS,
) -> list[dict[str, float]]:
    """Extrai `feature_gain.mean_gain.pooled` de cada combinacao symbol x
    resolution x model_id presente no relatorio -- ignora blocos sem
    `feature_gain` persistido."""
    blocks: list[dict[str, float]] = []
    for combo in alpha_full_analysis:
        variants = combo.get("variants", {})
        for variant_name in model_variants:
            variant = variants.get(variant_name)
            if variant is None:
                continue
            pooled = variant.get("feature_gain", {}).get("mean_gain", {}).get("pooled")
            if pooled:
                blocks.append(dict(pooled))
    if not blocks:
        raise Eixo1GainCrossCheckError(
            "nenhum bloco feature_gain.mean_gain.pooled encontrado em alpha_full_analysis"
        )
    return blocks


def _extract_discovery_by_feature(promotion_report: Mapping[str, Any]) -> dict[str, int]:
    return {
        entry["feature"]: int(entry["n_symbols_discovery"])
        for entry in promotion_report.get("por_feature", [])
    }


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


def run_gain_eixo1_cross_check_report(
    *,
    out_dir: Path = EXPERIMENTS_DIR,
    alpha_full_analysis_filename: str = ALPHA_FULL_ANALYSIS_FILENAME,
    promotion_report_filename: str = PROMOTION_REPORT_FILENAME,
    feature_ids: Sequence[str] = T1_FEATURE_IDS,
) -> Path:
    """Casca: le `alpha_full_analysis_filename` (gain real, ja persistido
    por symbol/resolution/model) e `promotion_report_filename`
    (descoberta do eixo 1), cruza os dois e persiste
    `experiments/eixo1_gain_cross_check_report.json`. Estagio 1 da
    proposta de solucao do addendum de `AG-330` (2026-08-27) -- sem
    retreino, so agregacao sobre artefato ja existente."""
    alpha_full_analysis = _load_json(out_dir / alpha_full_analysis_filename)
    promotion_report = _load_json(out_dir / promotion_report_filename)

    blocks = _extract_gain_blocks(alpha_full_analysis)
    shares_by_block = gain_shares_by_block(blocks, feature_ids=feature_ids)
    discovery_by_feature = _extract_discovery_by_feature(promotion_report)
    results = cross_check_features(shares_by_block, discovery_by_feature, feature_ids=feature_ids)

    payload: dict[str, Any] = {
        "task": "eixo1_gain_cross_check",
        "pergunta": "Features T1 com zero descoberta no eixo 1 tem gain consistente "
        "com 'sem sinal', ou o modelo real as usa acima da media (AG-330: a pergunta "
        "errada para papel filtro/custo)?",
        "adr_ref": "audit/architecture_gaps_log.yaml::AG-330 (addendum 2026-08-27); "
        "docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md §13.4, §14.9",
        "metodo": "gain_by_column normalizado em share por bloco symbol x resolution x "
        "model_id (src.models.hhi.compute_concentration, mesmo nucleo de producao), "
        f"media entre {len(shares_by_block)} blocos, cruzado com n_symbols_discovery do "
        f"eixo 1. Baseline = piso uniforme 1/{len(feature_ids)} (estrutural, nao ASSUMED).",
        "n_blocks": len(shares_by_block),
        "feature_ids": list(feature_ids),
        "resultados": [asdict(r) for r in results],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    return _write_atomic(
        out_dir / OUTPUT_FILENAME,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    import structlog

    logger = structlog.get_logger(__name__)
    out_path = run_gain_eixo1_cross_check_report()
    logger.info("analysis.eixo1_gain_cross_check.cli_done", report_path=str(out_path.resolve()))
