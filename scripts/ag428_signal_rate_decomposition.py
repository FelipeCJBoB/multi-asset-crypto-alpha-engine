"""Diagnostico read-only (AG-428) -- decompoe o gap entre target_signal_rate
nominal e a taxa de sinal REALIZADA (side_hat != 0) nos 10 artefatos
experiments/alpha_walk_forward_predictions_{SYMBOL}_{RES}_{VARIANT}.parquet.

NAO escreve em nenhum artefato de producao. So le os 10 parquets ja
existentes e imprime/escreve um relatorio de texto em
experiments/ag428_signal_rate_decomposition_report.txt.

Hipotese testada (registrada em config/constants.yaml::target_signal_rate):
a regra de decisao `_decision_rule` (src/models/alpha.py) exige
exclusividade mutua por barra (`is_long = p_long>tau_long AND
p_long>p_short`; `is_short = p_short>tau_short AND p_short>p_long AND
~is_long`) -- um lado pode bater o proprio tau e ainda assim ser suprimido
se o outro lado tiver score maior, mesmo sem bater o tau dele ("perder a
corrida interna").

RESULTADO (medido 2026-09-03, pooled sobre os 10 arquivos sob
target_signal_rate=0,10, n=212.782 barras OOF): a exclusividade mutua
responde por so ~6% do gap nominal-vs-realizado -- o gargalo real (~94%)
e que `rate_long_alone`/`rate_short_alone` (cada lado sozinho, sem
nenhuma competicao) ja ficam bem abaixo do nominal. E deriva
treino-vs-teste na propria calibracao de `tau`, nao um efeito da regra de
decisao. Ver `config/constants.yaml::target_signal_rate` pros numeros
completos e `audit/architecture_gaps_log.yaml::AG-428`.

Uso:

    uv run python -m scripts.ag428_signal_rate_decomposition
"""

from __future__ import annotations

import sys

import polars as pl
import structlog

from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_COMBOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_VARIANTS: tuple[str, ...] = ("camada1", "camada0")

_OUT_TXT = EXPERIMENTS_DIR / "ag428_signal_rate_decomposition_report.txt"


def _rate(df: pl.DataFrame, expr: pl.Expr) -> float:
    val = df.select(expr.mean().alias("x"))["x"][0]
    return float(val) if val is not None else float("nan")


def _analyze(df_oof: pl.DataFrame) -> dict[str, float | int]:
    n_oof = df_oof.height

    rate_long_alone = _rate(df_oof, pl.col("p_long") > pl.col("tau_long"))
    rate_short_alone = _rate(df_oof, pl.col("p_short") > pl.col("tau_short"))
    rate_naive_or = _rate(
        df_oof, (pl.col("p_long") > pl.col("tau_long")) | (pl.col("p_short") > pl.col("tau_short"))
    )
    rate_actual = _rate(df_oof, pl.col("side_hat") != 0)

    long_would = df_oof.filter(pl.col("p_long") > pl.col("tau_long"))
    long_suppressed = long_would.filter(pl.col("side_hat") != 1)
    frac_long_lost_race = (
        _rate(long_suppressed, pl.col("p_short") > pl.col("p_long"))
        if long_suppressed.height > 0
        else float("nan")
    )

    short_would = df_oof.filter(pl.col("p_short") > pl.col("tau_short"))
    short_suppressed = short_would.filter(pl.col("side_hat") != -1)
    frac_short_lost_race = (
        _rate(short_suppressed, pl.col("p_long") > pl.col("p_short"))
        if short_suppressed.height > 0
        else float("nan")
    )

    return {
        "n_oof": n_oof,
        "rate_long_alone": rate_long_alone,
        "rate_short_alone": rate_short_alone,
        "rate_naive_or": rate_naive_or,
        "rate_actual": rate_actual,
        "n_long_would": long_would.height,
        "n_long_suppressed": long_suppressed.height,
        "frac_long_suppressed_lost_race": frac_long_lost_race,
        "n_short_would": short_would.height,
        "n_short_suppressed": short_suppressed.height,
        "frac_short_suppressed_lost_race": frac_short_lost_race,
    }


def _fmt(v: float) -> str:
    if v != v:  # NaN
        return "NaN"
    return f"{v:.4f}"


def main() -> int:
    target_signal_rate = float(load_constant("target_signal_rate"))
    lines: list[str] = []

    def emit(s: str = "") -> None:
        lines.append(s)
        if s:
            logger.info("scripts.ag428_signal_rate_decomposition.linha", texto=s)

    emit("Diagnostico AG-428 -- decomposicao do gap nominal vs realizado")
    emit(f"target_signal_rate (config/constants.yaml) = {target_signal_rate}")
    emit("")

    per_file_frames: list[pl.DataFrame] = []
    per_file_results: list[dict[str, float | int | str]] = []

    for symbol, res in _COMBOS:
        for variant in _VARIANTS:
            fname = f"alpha_walk_forward_predictions_{symbol}_{res}_{variant}.parquet"
            path = EXPERIMENTS_DIR / fname
            if not path.exists():
                emit(f"AUSENTE: {fname}")
                continue
            df = pl.read_parquet(path)
            required = {
                "p_long",
                "p_short",
                "tau_long",
                "tau_short",
                "side_hat",
                "is_oof",
                "fold_id",
            }
            missing = required - set(df.columns)
            if missing:
                emit(f"ERRO schema em {fname}: faltam colunas {sorted(missing)}")
                continue
            df_oof = df.filter(pl.col("is_oof"))
            r: dict[str, float | int | str] = dict(_analyze(df_oof))
            r.update(
                {"symbol": symbol, "resolution_id": res, "variant": variant, "n_total": df.height}
            )
            per_file_results.append(r)
            per_file_frames.append(df_oof)

    emit("=== POR ARQUIVO (is_oof == True) ===")
    for r in per_file_results:
        combo = f"{r['symbol']}_{r['resolution_id']}_{r['variant']}"
        emit(f"-- {combo} -- n_total={r['n_total']} n_oof={r['n_oof']}")
        emit(
            f"   rate_long_alone={_fmt(r['rate_long_alone'])}  "  # type: ignore[arg-type]
            f"rate_short_alone={_fmt(r['rate_short_alone'])}  "  # type: ignore[arg-type]
            f"rate_naive_or={_fmt(r['rate_naive_or'])}  "  # type: ignore[arg-type]
            f"rate_actual={_fmt(r['rate_actual'])}"  # type: ignore[arg-type]
        )
        emit(
            f"   long:  n_bateu_tau={r['n_long_would']}  n_suprimido={r['n_long_suppressed']}  "
            f"frac_suprimido_por_perder_corrida={_fmt(r['frac_long_suppressed_lost_race'])}"  # type: ignore[arg-type]
        )
        emit(
            f"   short: n_bateu_tau={r['n_short_would']}  n_suprimido={r['n_short_suppressed']}  "
            f"frac_suprimido_por_perder_corrida={_fmt(r['frac_short_suppressed_lost_race'])}"  # type: ignore[arg-type]
        )
        emit("")

    if not per_file_frames:
        emit("Nenhum arquivo valido encontrado -- abortando pooled.")
        _OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
        return 1

    pooled = pl.concat(per_file_frames, how="vertical_relaxed")
    rp = _analyze(pooled)

    emit("=== POOLED (10 arquivos, is_oof == True) ===")
    emit(f"n_oof_pooled = {rp['n_oof']}")
    emit(f"rate_long_alone  = {_fmt(rp['rate_long_alone'])}")
    emit(f"rate_short_alone = {_fmt(rp['rate_short_alone'])}")
    emit(f"rate_naive_or    = {_fmt(rp['rate_naive_or'])}")
    emit(f"rate_actual      = {_fmt(rp['rate_actual'])}")
    emit(
        f"long:  n_bateu_tau={rp['n_long_would']}  n_suprimido={rp['n_long_suppressed']}  "
        f"frac_suprimido_por_perder_corrida={_fmt(rp['frac_long_suppressed_lost_race'])}"
    )
    emit(
        f"short: n_bateu_tau={rp['n_short_would']}  n_suprimido={rp['n_short_suppressed']}  "
        f"frac_suprimido_por_perder_corrida={_fmt(rp['frac_short_suppressed_lost_race'])}"
    )
    emit("")

    target = target_signal_rate
    rate_actual_p = float(rp["rate_actual"])
    rate_naive_or_p = float(rp["rate_naive_or"])
    gap_total = target - rate_actual_p
    gap_drift = target - rate_naive_or_p
    gap_exclusion = rate_naive_or_p - rate_actual_p

    emit("=== DECOMPOSICAO (pooled) ===")
    emit(
        "identidade: (target - rate_actual) = "
        "(target - rate_naive_or) + (rate_naive_or - rate_actual)"
    )
    emit(f"gap_total (target - rate_actual)          = {_fmt(gap_total)}")
    emit(f"gap_drift (target - rate_naive_or)        = {_fmt(gap_drift)}")
    emit(f"gap_exclusion (rate_naive_or - rate_actual) = {_fmt(gap_exclusion)}")
    if gap_total != 0:
        emit(f"  -> gap_drift / gap_total     = {gap_drift / gap_total * 100:.1f}%")
        emit(f"  -> gap_exclusion / gap_total = {gap_exclusion / gap_total * 100:.1f}%")
    emit(f"checagem soma = {_fmt(gap_drift + gap_exclusion)} (deve bater com gap_total)")

    _OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    emit("")
    emit(f"[relatorio tambem salvo em: {_OUT_TXT}]")
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    configure_logging(json_output=False)
    sys.exit(main())
