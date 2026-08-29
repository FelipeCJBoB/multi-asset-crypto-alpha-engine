"""AG-371 -- extrai KPIs dos 2 bracos do Passo 1 (global vs by-combo, 15
celulas, 36 T1_FEATURE_IDS) direto dos relatorios-resumo persistidos
(`experiments/alpha_layer1_report_{symbol}_{resolution_id}_{global,
bycombo}.json`), sem retreinar nada. Cobre 2 usos:

(1) Fecha AG-371-ADDENDUM-9 -- confirma que Camada0 (CAMADA0_CONSTRAINED_
FEATURES, unico E27f_cost_atr_ratio, aplicado incondicionalmente desde a
promocao) produz sinal (n_signals > 0) nas 15 celulas sob 36 features
limpo, nao so nas que ja passavam antes.
(2) Alimenta o artefato de KPIs (HHI, economic_gate, permanence gate,
decomposicao, elapsed_seconds) pras 15 celulas x 2 bracos.

Escreve tools/diagnostics/_ag371_passo1_kpis.json (consumido pelo
artefato) e imprime um resumo tabular no log (structlog).

PENDENTE-DE-EXECUCAO-HUMANA -- rodar com:
    uv run python tools/diagnostics/extract_ag371_passo1_kpis.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import orjson
import structlog

logger = structlog.get_logger(__name__)

_EXPERIMENTS_DIR = _REPO_ROOT / "experiments"
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
_RESOLUTIONS = ("R1", "R2", "R3")
_ARMS = ("global", "bycombo")
_OUT_PATH = Path(__file__).resolve().parent / "_ag371_passo1_kpis.json"


def _load(symbol: str, resolution_id: str, arm: str) -> dict | None:
    path = _EXPERIMENTS_DIR / f"alpha_layer1_report_{symbol}_{resolution_id}_{arm}.json"
    if not path.exists():
        return None
    return orjson.loads(path.read_bytes())


def _n_signals(report: dict, variant: str) -> int:
    key = f"camada{variant}_backtest_by_path"
    return sum(int(p["n_signals"]) for p in report[key].values())


def _n_filled(report: dict, variant: str) -> int:
    key = f"camada{variant}_backtest_by_path"
    return sum(int(p["n_filled_trades"]) for p in report[key].values())


def _cell_kpis(report: dict) -> dict:
    lv = report["layer1_vs_layer0"]
    eg = report.get("economic_gate", {})
    hhi = report.get("hhi", {})
    return {
        "n_signals_camada1": _n_signals(report, "1"),
        "n_signals_camada0": _n_signals(report, "0"),
        "n_filled_camada1": _n_filled(report, "1"),
        "n_filled_camada0": _n_filled(report, "0"),
        "camada1_sharpe_mean": lv["camada1_sharpe_mean"],
        "camada0_sharpe_mean": lv["camada0_sharpe_mean"],
        "delta_sharpe_mean": lv["delta_sharpe_mean"],
        "n_paths_camada1_supera_camada0": lv["n_paths_camada1_supera_camada0"],
        "n_paths_significant": lv["n_paths_significant"],
        "n_paths_total": lv["n_paths_total"],
        "permanence_pass": lv["permanence_pass"],
        "camada1_sharpe_std_between_paths": lv["camada1_sharpe_dispersion"]["std_between_paths"],
        "camada0_sharpe_std_between_paths": lv["camada0_sharpe_dispersion"]["std_between_paths"],
        "economic_gate_long_passes": eg.get("long", {}).get("passes"),
        "economic_gate_short_passes": eg.get("short", {}).get("passes"),
        "economic_gate_long_distinguishable": eg.get("long", {}).get("distinguishable"),
        "economic_gate_short_distinguishable": eg.get("short", {}).get("distinguishable"),
        "mean_hhi_effective": hhi.get("mean_hhi_effective"),
        "mean_n_eff_factors_t1": hhi.get("mean_n_eff_factors_t1"),
        "elapsed_seconds": report.get("elapsed_seconds"),
        "n_rows_modeling_frame": report.get("n_rows_modeling_frame"),
        "hyperparam_feature_mismatch": report.get("hyperparam_feature_mismatch", False),
    }


def main() -> None:
    out: dict[str, dict] = {}
    missing: list[str] = []
    zero_signal_camada0: list[str] = []

    for symbol in _SYMBOLS:
        for resolution_id in _RESOLUTIONS:
            cell_key = f"{symbol}_{resolution_id}"
            out[cell_key] = {}
            for arm in _ARMS:
                report = _load(symbol, resolution_id, arm)
                if report is None:
                    missing.append(f"{cell_key}_{arm}")
                    continue
                kpis = _cell_kpis(report)
                out[cell_key][arm] = kpis
                if arm == "global" and kpis["n_signals_camada0"] == 0:
                    zero_signal_camada0.append(cell_key)

    _OUT_PATH.write_bytes(orjson.dumps(out, option=orjson.OPT_INDENT_2))

    logger.info(
        "ag371_passo1_kpis.extraido",
        n_celulas=len(out),
        arquivos_faltando=missing,
        out_path=str(_OUT_PATH),
    )
    logger.info(
        "ag371_addendum9.checagem_camada0_n_signals",
        celulas_com_camada0_zerado_sob_36_limpo=zero_signal_camada0,
        veredito=(
            "ADDENDUM-9 fecha -- nenhuma celula com Camada0 zerada sob 36 features limpo"
            if not zero_signal_camada0
            else f"ADDENDUM-9 NAO fecha -- {len(zero_signal_camada0)} celula(s) ainda zerada(s)"
        ),
    )
    for cell_key, arms in out.items():
        g = arms.get("global", {})
        logger.info(
            "ag371_passo1_kpis.celula",
            celula=cell_key,
            n_signals_c1=g.get("n_signals_camada1"),
            n_signals_c0=g.get("n_signals_camada0"),
            permanence_pass=g.get("permanence_pass"),
            n_better=g.get("n_paths_camada1_supera_camada0"),
            n_significant=g.get("n_paths_significant"),
            sharpe_c1=g.get("camada1_sharpe_mean"),
            sharpe_c0=g.get("camada0_sharpe_mean"),
        )


if __name__ == "__main__":
    main()
