"""`experiments/latest_summary.md` — resumo legível de `experiments/
alpha_layer1_report.json`, números-manchete em bps/trade
(`Metric.per_unit()`, não fração somada), com `generated_at`/
`code_version` (`src.core.provenance`) — Faixa 0, item 4.

**Por que isto existe.** Achado real desta investigação (mesma rodada,
item 2/3): números copiados de `alpha_layer1_report.json` já circularam
com o `n` de um momento diferente do `value` que acompanhavam, em três
consumidores distintos — o JSON bruto (dezenas de campos, aninhado em
`decomposition_pnl.pooled_all_15_splits`/`hhi`/`baselines`/
`layer1_vs_layer0`) não é pensado pra leitura humana rápida.
`latest_summary.md` não substitui o JSON (continua sendo a fonte de
verdade), só dá um único lugar correto pra olhar primeiro.

**Modo manual, mesmo padrão de `src.analysis.cost_surface`.** Não é
chamado por `src.models.pipeline.run_layer1_sprint()` — essa integração
(gerar o resumo automaticamente ao final de cada sprint) fica pra quando
`src/models/` não estiver fora de escopo (CLAUDE.md, Faixa 0 "não
fazer": "não tocar em src/models/ nem em src/features/ nesta faixa" —
mesmo conflito e mesma resolução do item 2, `src.core.provenance`).
Hoje: rode manualmente depois de `run_layer1_sprint()`:
`uv run python -m src.analysis.summary`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final

import orjson
import structlog

from src.core.metric import Metric, Unit
from src.core.provenance import report_provenance

logger = structlog.get_logger(__name__)

# src/analysis/summary.py -> parents[0]=src/analysis, [1]=src, [2]=raiz do
# repo — mesmo padrão de src/analysis/cost_surface.py (duplicado, não
# importado: cada pacote resolve seu próprio caminho de saída).
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "alpha_layer1_report.json"
DEFAULT_SUMMARY_PATH: Final[Path] = EXPERIMENTS_DIR / "latest_summary.md"


def _metric_from_json(d: dict[str, Any]) -> Metric:
    """Reconstrói um `Metric` a partir do dict que `Metric.to_json()`
    produziu. `value=None` no JSON (NaN não é serializável em JSON padrão,
    `orjson`/`json` gravam `null`) volta a ser `float('nan')` — mesma
    convenção de `Metric` inválido, não um caso novo."""
    value = d["value"]
    return Metric(
        value=float(value) if value is not None else float("nan"),
        unit=Unit(d["unit"]),
        n=d["n"],
        n_semantics=d["n_semantics"],
        source=d.get("source", ""),
        valid=d["valid"],
        invalid_reason=d.get("invalid_reason"),
    )


def _fmt_metric(d: dict[str, Any], *, as_bps_per_trade: bool, fmt: str = "+.3f") -> str:
    """`as_bps_per_trade=True` chama `Metric.per_unit()` (só vale pra
    `Unit.FRACTION_OF_NOTIONAL`/`n_semantics="trades"`, ex. `pnl_total`);
    `False` formata `.value` cru com `fmt` (ex. Sharpe, já numa unidade
    humana). `Metric.valid=False` sempre vira "não computável (motivo)",
    independente do modo — nunca imprime `nan` cru."""
    m = _metric_from_json(d)
    if not m.valid:
        return f"não computável ({m.invalid_reason})"
    if as_bps_per_trade:
        return f"{m.per_unit().value:+.2f} bps/trade"
    return format(m.value, fmt)


def build_summary_markdown(report: dict[str, Any]) -> str:
    """Função pura — `report` é o dict já carregado de
    `alpha_layer1_report.json` (ou equivalente, mesmo schema). Não lê nem
    escreve arquivo; `write_latest_summary_atomic` faz a parte de IO."""
    prov = report_provenance()
    dp = report["decomposition_pnl"]["pooled_all_15_splits"]
    hhi = report["hhi"]
    b1 = report["baselines"]["b1_random_entry"]
    perm = report["layer1_vs_layer0"]

    lines = [
        f"# Resumo — Alpha Camada 1 (Sprint {report['sprint']}, {report['symbol']})",
        "",
        f"_Gerado em {prov['generated_at']} — commit `{prov['code_version']}`._",
        "",
        "Fonte: `experiments/alpha_layer1_report.json` "
        f"(schema_version {report.get('schema_version', '?')}). Este arquivo é "
        "DERIVADO — não edite à mão, rode `uv run python -m src.analysis.summary`.",
        "",
        f"## PnL (pooled, {dp['pnl_total']['n']} trades, "
        f"{report.get('n_cpcv_splits', '?')} splits)",
        "",
        "| componente | bps/trade |",
        "|---|---|",
        f"| Total | {_fmt_metric(dp['pnl_total'], as_bps_per_trade=True)} |",
        f"| Direcional | {_fmt_metric(dp['pnl_direcional'], as_bps_per_trade=True)} |",
        f"| Carry | {_fmt_metric(dp['pnl_carry'], as_bps_per_trade=True)} |",
        f"| Execução (custo) | {_fmt_metric(dp['pnl_execucao'], as_bps_per_trade=True)} |",
        "",
        "## Sharpe (pooled)",
        "",
        f"- Total: {_fmt_metric(dp['total_sharpe'], as_bps_per_trade=False)}",
        f"- Direcional: {_fmt_metric(dp['directional_sharpe'], as_bps_per_trade=False)}",
        "- `carry_share` (gate3): "
        f"{_fmt_metric(dp['carry_share'], as_bps_per_trade=False, fmt='+.4f')}",
        "",
        "## Concentração de features (HHI)",
        "",
        f"- Nominal médio: {hhi['mean_hhi']:.4f} "
        f"({'< 0,25 OK' if hhi['gate3_4_hhi_lt_025'] else 'ACIMA de 0,25'})",
        f"- Efetivo médio (corrigido por correlação, Fase D): {hhi['mean_hhi_effective']:.4f}",
        f"- Maior share médio: {hhi['mean_max_share']:.4f} "
        f"({'< 0,30 OK' if hhi['gate3_4_max_share_lt_030'] else 'ACIMA de 0,30'})",
        "",
        "## Baseline aleatório (B1)",
        "",
        f"- Alpha no percentil {b1['percentile_of_alpha']:.1f} de {b1['n_seeds']} sorteios "
        f"(amostra {b1['sample_size']} trades)",
        "",
        "## Permanência (Camada 1 vs Camada 0)",
        "",
        f"- {perm['n_paths_camada1_supera_camada0']} de {perm['n_paths_total']} caminhos "
        f"(mínimo exigido: {perm['min_paths_required']}) — "
        f"{'PASSA' if perm['permanence_pass'] else 'NÃO PASSA'}",
        "",
    ]
    return "\n".join(lines)


def write_latest_summary_atomic(
    report: dict[str, Any] | None = None,
    *,
    report_path: Path | None = None,
    dest_path: Path | None = None,
) -> Path:
    """Carrega `report_path` (default `alpha_layer1_report.json`) se
    `report` não for passado, monta o markdown, e escreve `dest_path`
    (default `latest_summary.md`) atomicamente (B29: `.tmp` -> `fsync` ->
    `rename`, mesmo padrão de `src.analysis.cost_surface._atomic_write_json`,
    adaptado pra texto)."""
    if report is None:
        source_path = report_path if report_path is not None else DEFAULT_REPORT_PATH
        report = orjson.loads(source_path.read_bytes())

    markdown = build_summary_markdown(report)

    dest = dest_path if dest_path is not None else DEFAULT_SUMMARY_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + ".tmp")
    blob = markdown.encode("utf-8")
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest)
    logger.info("analysis.summary.written", path=str(dest))
    return dest


if __name__ == "__main__":
    write_latest_summary_atomic()
