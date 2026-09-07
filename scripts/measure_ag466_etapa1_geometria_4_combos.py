"""AG-466 Etapa 1 — a celula derivada em SOLUSDT/R3 reduz o gap nos 4
combos NAO VISTOS?

Desenho, limiar e veredito vivem em
`audit/pre_registro/ag466_geometria_m4_h128_generaliza.yaml`, commitado
SOZINHO em `d496398` antes de qualquer numero destes 4 combos existir sob
esta geometria (ordem verificavel por `git log`). Este modulo le o registro
e aplica -- nao decide nada.

**O que a Etapa 1 mede, e o que ela NAO mede.** Mede aritmetica de label
pura: reconstroi as barreiras na celula de PRODUCAO e na celula DERIVADA e
compara `gap_pp = frac_TP - breakeven`. Nenhum modelo entra, `frac_TP` e o
piso de mercado sem selecao. NAO mede se o lift do modelo sobrevive -- isso
e a Etapa 2, e so roda se esta passar.

**Janela dimensionada pelo horizonte real (AG-465).** `window_bars` de
`resolve_barriers_vectorized` deriva de `time_stop_ms`, mas sob dollar bar
o horizonte e `horizon_end_ms` (contagem de barra). Usar o default trunca a
busca em 540 minutos e fabrica `TIME` espurio, justamente nas celulas de
barreira larga -- mediria o proprio defeito. Aqui a janela vem do span real
por chunk de trades.

Uso:

    uv run python -m scripts.measure_ag466_etapa1_geometria_4_combos
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import structlog
import yaml

from src.analysis.feasibility import breakeven_win_rate
from src.data import lake
from src.labels.barrier_sweep import resolve_barriers_vectorized
from src.labels.triple_barrier import TP_TOUCH_SOURCE_MARK_1M, LabelConfig
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging

logger = structlog.get_logger(__name__)

_REPO_ROOT: Path = Path(__file__).resolve().parents[1]
_PRE_REGISTRO: Path = (
    _REPO_ROOT / "audit" / "pre_registro" / "ag466_geometria_m4_h128_generaliza.yaml"
)

#: Os 4 combos de TESTE. `SOLUSDT/R3` NAO entra: ele derivou a celula.
_COMBOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_SIDES: tuple[int, ...] = (1, -1)

#: Celula DERIVADA, espelhada do registro. `_valida_registro` aborta se
#: divergir do YAML commitado -- sem essa checagem o codigo poderia aplicar
#: silenciosamente uma celula diferente da que foi travada antes.
_M_DERIVADO: float = 4.0  # noqa: magic-number -- celula derivada, ver pre-registro
_HORIZON_DERIVADO: int = 128  # noqa: magic-number -- celula derivada, ver pre-registro
_LIMIAR_MELHORA_PP: float = 0.50  # noqa: magic-number -- criterio do pre-registro
_MIN_COMBOS_SUCESSO: int = 4  # noqa: magic-number -- criterio do pre-registro
_MIN_COMBOS_PARCIAL: int = 3  # noqa: magic-number -- criterio do pre-registro

_CHUNK: int = 1500  # noqa: magic-number -- controle de memoria, nao parametro de dominio
_MARGIN_DAYS: int = 3  # noqa: magic-number -- mesma margem de s1_tp_sl_sensitivity
_MINUTE_MS: int = 60_000  # noqa: magic-number -- definicao de calendario
_BPS: float = 10_000.0  # noqa: magic-number -- definicao matematica
_PP: float = 100.0  # noqa: magic-number -- fracao -> ponto percentual


def _valida_registro() -> dict[str, Any]:
    """Le o registro e ABORTA se os numeros espelhados no codigo divergirem
    dele. O texto do YAML esta em portugues e usa VIRGULA decimal; a
    comparacao normaliza o separador (licao do AG-463, onde a checagem
    falhou por ortografia e nunca chegou a olhar o criterio)."""
    with _PRE_REGISTRO.open(encoding="utf-8") as f:
        reg: dict[str, Any] = yaml.safe_load(f)
    if reg.get("id") != "AG-466":
        raise ValueError(f"pre-registro inesperado: id={reg.get('id')!r}")

    combos_reg = [c.replace("/", "_") for c in reg["separacao_derivacao_teste"]["teste"]["combos"]]
    combos_cod = [f"{s}_{r}" for s, r in _COMBOS]
    if combos_reg != combos_cod:
        raise ValueError(
            f"combos de teste divergem do registro: {combos_reg} vs {combos_cod}"
        )
    titulo = str(reg["titulo"]).replace(",", ".")
    for frag in (f"m={_M_DERIVADO:.0f}", f"horizon_bars={_HORIZON_DERIVADO}"):
        if frag not in titulo:
            raise ValueError(f"celula do codigo diverge do registro: {frag!r} ausente do titulo")
    crit = str(reg["etapa_1"]["criterio_por_combo"]).replace(",", ".")
    if f">= {_LIMIAR_MELHORA_PP:.2f}pp" not in crit:
        raise ValueError(
            f"limiar do codigo ({_LIMIAR_MELHORA_PP}) nao aparece no criterio commitado"
        )
    return reg


def _resolve_chunked(
    filled: pl.DataFrame,
    mark_1m: pl.DataFrame,
    funding: pl.DataFrame,
    *,
    side: int,
    m: float,
    cfg: LabelConfig,
    horizon_end: np.ndarray,
    decision_close_ms: np.ndarray,
    last_1m: pl.DataFrame | None,
    resolution_id: str,
) -> list[str]:
    """`barrier_hit` concatenado sobre chunks. Janela por span REAL do
    horizonte (AG-465), nunca por `time_stop_ms`."""
    t_entry = filled["t_entry"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    hits: list[str] = []
    for ini in range(0, filled.height, _CHUNK):
        fim = min(ini + _CHUNK, filled.height)
        h_sub = horizon_end[ini:fim]
        span_ms = int(np.max(h_sub - t_entry[ini:fim]))
        res = resolve_barriers_vectorized(
            filled.slice(ini, fim - ini),
            mark_1m,
            funding,
            side=side,
            tp_atr_mult=m,
            sl_atr_mult=m,
            time_stop_ms=span_ms + _MINUTE_MS,
            maker_fee=cfg.maker_fee,
            taker_fee=cfg.taker_fee,
            adverse_selection_bps=cfg.adverse_selection_bps,
            last_1m=last_1m,
            tf=resolution_id,
            decision_bar_close_time_ms=decision_close_ms,
            horizon_end_ms=h_sub,
        )
        hits.extend(res.barrier_hit)
    return hits


def _celula(
    labels: pl.DataFrame,
    mark_1m: pl.DataFrame,
    funding: pl.DataFrame,
    decision_close_ms: np.ndarray,
    t0_grid: np.ndarray,
    *,
    cfg: LabelConfig,
    last_1m: pl.DataFrame | None,
    resolution_id: str,
    m: float,
    horizon_bars: int,
) -> dict[str, Any]:
    hits_all: list[str] = []
    atrs: list[float] = []
    for side in _SIDES:
        filled = labels.filter(
            (pl.col("side") == side) & (pl.col("barrier_hit") != "NOFILL")
        ).select(["t0", "t_entry", "entry_price_fill", "atr_at_t0"])
        if filled.is_empty():
            continue
        _t0 = filled["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        _idx = np.searchsorted(t0_grid, _t0, side="left") + horizon_bars
        _ok = _idx < t0_grid.shape[0]
        if not bool(_ok.all()):
            filled = filled.filter(pl.Series(_ok))
            _idx = _idx[_ok]
        hits_all.extend(
            _resolve_chunked(
                filled,
                mark_1m,
                funding,
                side=side,
                m=m,
                cfg=cfg,
                horizon_end=t0_grid[_idx],
                decision_close_ms=decision_close_ms,
                last_1m=last_1m,
                resolution_id=resolution_id,
            )
        )
        atrs.append(float(filled["atr_at_t0"].to_numpy().mean()))

    arr = np.array(hits_all)
    atr_med = float(np.mean(atrs))
    frac_tp = float((arr == "TP").mean())
    be = breakeven_win_rate(
        atr_pct=atr_med,
        tp_atr_mult=m,
        sl_atr_mult=m,
        maker_fee=cfg.maker_fee,
        taker_fee=cfg.taker_fee,
        adverse_selection_bps=cfg.adverse_selection_bps,
    )
    return {
        "m": m,
        "horizon_bars": horizon_bars,
        "n": int(arr.size),
        "frac_tp": frac_tp,
        "frac_time": float((arr == "TIME").mean()),
        "breakeven": be,
        "gap_pp": (frac_tp - be) * _PP,
    }


def main(argv: list[str] | None = None) -> int:
    configure_logging(json_output=False)
    _valida_registro()
    vol_estimator_id = str(load_constant("canonical_volatility_estimator"))
    m_prod = float(load_constant("tp_atr_mult"))
    sl_prod = float(load_constant("sl_atr_mult"))
    if m_prod != sl_prod:
        raise ValueError(
            f"geometria de producao nao e simetrica (tp={m_prod}, sl={sl_prod}) -- "
            "a comparacao deste teste pressupoe simetria nas duas celulas"
        )
    h_prod = int(load_constant("horizon_bars"))

    por_combo: list[dict[str, Any]] = []
    for symbol, resolution_id in _COMBOS:
        logger.info("ag466e1.combo_inicio", symbol=symbol, resolution_id=resolution_id)
        cfg = LabelConfig.from_constants(
            estimator_id=vol_estimator_id, resolution_id=resolution_id
        )
        labels = pl.read_parquet(f"data/labels/{symbol}/{resolution_id}/v1/labels.parquet")
        t0_min, t0_max = labels["t0"].min(), labels["t0"].max()
        start = (t0_min.date() - timedelta(days=_MARGIN_DAYS)).isoformat()  # type: ignore[union-attr]
        end = (t0_max.date() + timedelta(days=_MARGIN_DAYS)).isoformat()  # type: ignore[union-attr]
        mark_1m = lake.query_bars(
            symbol, "1m", start, end, source="mark_price_klines_1m", cast_prices=True
        )
        last_1m = (
            lake.query_bars(symbol, "1m", start, end, source="klines_1m", cast_prices=True)
            if cfg.tp_touch_source != TP_TOUCH_SOURCE_MARK_1M
            else None
        )
        funding = lake.query_funding(symbol, start, end)
        bars = lake.query_dollar_bars(symbol, start, end, resolution_id=resolution_id)
        decision_close_ms = bars["close_time"].cast(pl.Int64).to_numpy().astype(np.int64)
        t0_grid = np.sort(
            labels["t0"].unique().dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
        )

        comum = {
            "labels": labels,
            "mark_1m": mark_1m,
            "funding": funding,
            "decision_close_ms": decision_close_ms,
            "t0_grid": t0_grid,
            "cfg": cfg,
            "last_1m": last_1m,
            "resolution_id": resolution_id,
        }
        prod = _celula(**comum, m=m_prod, horizon_bars=h_prod)  # type: ignore[arg-type]
        deriv = _celula(**comum, m=_M_DERIVADO, horizon_bars=_HORIZON_DERIVADO)  # type: ignore[arg-type]
        melhora = deriv["gap_pp"] - prod["gap_pp"]
        passou = bool(melhora >= _LIMIAR_MELHORA_PP)
        por_combo.append(
            {
                "symbol": symbol,
                "resolution_id": resolution_id,
                "producao": prod,
                "derivada": deriv,
                "melhora_pp": melhora,
                "passou": passou,
            }
        )
        logger.info(
            "ag466e1.combo_fim",
            symbol=symbol,
            resolution_id=resolution_id,
            gap_prod=round(float(prod["gap_pp"]), 3),
            gap_deriv=round(float(deriv["gap_pp"]), 3),
            melhora=round(melhora, 3),
            passou=passou,
        )

    n_pass = sum(1 for c in por_combo if c["passou"])
    if n_pass >= _MIN_COMBOS_SUCESSO:
        veredito = "SUCESSO"
    elif n_pass >= _MIN_COMBOS_PARCIAL:
        veredito = "PARCIAL"
    else:
        veredito = "FRACASSO"

    payload = {
        "task": (
            "AG-466 Etapa 1 -- a celula derivada em SOLUSDT/R3 generaliza "
            "(geometria pura, sem modelo)"
        ),
        "pre_registro": str(_PRE_REGISTRO.relative_to(_REPO_ROOT)).replace("\\", "/"),
        "derivacao": {"combo": "SOLUSDT/R3", "commit": "425f599", "ag": "AG-464"},
        "celula_producao": {"m": m_prod, "horizon_bars": h_prod},
        "celula_derivada": {"m": _M_DERIVADO, "horizon_bars": _HORIZON_DERIVADO},
        "limiar_melhora_pp": _LIMIAR_MELHORA_PP,
        "veredito": veredito,
        "n_combos_que_passaram": n_pass,
        "por_combo": por_combo,
        "nota": (
            "gap_pp = frac_TP - breakeven, onde frac_TP e a win rate INCONDICIONAL "
            "(piso de mercado, sem modelo). melhora_pp = gap da celula derivada menos "
            "gap da celula de producao; positivo significa que o modelo precisa "
            "adicionar MENOS. Nenhum modelo entra nesta etapa."
        ),
    }
    destino = EXPERIMENTS_DIR / "ag466_etapa1_geometria.json"
    destino.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("ag466e1.gravado", path=str(destino), veredito=veredito, n_pass=n_pass)
    return 0


if __name__ == "__main__":  # pragma: no cover -- execucao manual
    sys.exit(main())
