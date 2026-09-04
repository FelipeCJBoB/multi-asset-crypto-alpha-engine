"""Mede o que o `edge_bps` do walk-forward NÃO mede: quanto do edge sobra
depois da quantização real da exchange e do orçamento de fees, ao capital
de referência de R$ 1.000.

**Por que existe** (AG-435, auditoria externa adversarial 2026-09-03,
achados N9 e N2/B1). Dois furos distintos que este módulo fecha juntos:

1. **Quantização nunca entrou no backtest.** `floor_to_step` existe e é
   usado em `src/risk/sizing.py`, `src/risk/limits.py` e
   `src/exchange/filters.py` — o caminho de PRODUÇÃO. Não existe em
   `src/models/backtest_lite.py`. O revisor externo leu isso como "falta
   aplicar `floor_to_step` no `backtest_lite`"; a especificação está
   errada e não foi aplicada assim: `backtest_lite` opera inteiramente em
   espaço de RETORNO (`ret_net`, fração por trade) — não existe `qty`,
   `notional` nem `mark_price` no módulo inteiro, então não há nada ali
   pra quantizar. O erro de quantização não enviesa `edge_bps` (retorno
   por trade é livre de escala); ele limita QUANTO desse edge é
   capturável com R$ 1.000. São perguntas diferentes, e a resposta certa
   é uma camada NOVA que mede a segunda, não uma mudança na primeira.

2. **Nenhum script do AG-427/AG-428 chamou o código real de risco.** O
   teto econômico de 5,88%/mês que o Manager autorizou foi calculado
   replicando a fórmula de `control_13_orcamento_fees` à mão, num cálculo
   ad-hoc que nunca foi commitado. A fórmula estava certa (conferida
   linha a linha), mas "conferi que copiei certo" não é o mesmo que
   "chamei a função de produção". Este módulo importa e executa
   `compute_sizing_asof` e `control_13_orcamento_fees` de verdade, sobre
   os trades OOF reais — se a réplica divergir da função, ele mostra.

**Método.** Para cada candidato de produção, junta as predições OOF
(`experiments/alpha_walk_forward_predictions_*.parquet`, `is_oof==True`,
`side_hat != 0`) aos labels (`atr_at_t0`, `entry_price_fill`, `ret_net`)
por `t0`, e para CADA sinal roda o sizing de produção com os filtros
vigentes NA DATA (`load_filters_asof` via `compute_sizing_asof`, B01-safe).
Reporta, por combo × camada:

- `frac_abaixo_min_qty` / `frac_abaixo_min_notional`: sinais que a
  exchange simplesmente não aceita a R$ 1.000 — edge inalcançável, não
  reduzido.
- `quant_error_*`: erro de quantização (`SizingResult.quant_error`) — o
  quanto o risco REAL desvia do risco pedido por causa do `step_size`.
- `edge_bps_nominal` vs `edge_bps_ponderado_por_nocional`: o edge que o
  gate Alpha vê vs. o edge ponderado pelo nocional que de fato seria
  aberto. Divergem quando os trades bons e os ruins recebem tamanhos
  diferentes por acidente de quantização.
- `control_13`: veredito do controle de orçamento de fees de produção,
  chamado de verdade.

Uso:

    uv run python -m scripts.measure_capital_feasibility
    uv run python -m scripts.measure_capital_feasibility --equity 1000
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import structlog

from src.exchange.filters import NoFiltersAvailableError
from src.labels._paths import labels_symbol_tf_dir
from src.models._constants import load_constant
from src.models._paths import EXPERIMENTS_DIR
from src.monitoring.logging import configure_logging
from src.risk.limits import ControlOutcome, control_13_orcamento_fees
from src.risk.sizing import SizingResult, compute_sizing_asof

logger = structlog.get_logger(__name__)

_BPS_PER_UNIT = 10_000
# Conversoes de unidade de tempo -- aritmetica de calendario, nao
# parametro de dominio (nada a varrer, nada a proveniencia).
_S_POR_DIA = 86_400.0  # noqa: magic-number
_MS_POR_S = 1_000.0  # noqa: magic-number
_DIAS_POR_MES = 30.0  # noqa: magic-number -- conversao de calendario, nao parametro de dominio

# Os 5 candidatos de produção x 2 camadas.
_CANDIDATOS: tuple[tuple[str, str], ...] = (
    ("BTCUSDT", "R2"),
    ("SOLUSDT", "R2"),
    ("SOLUSDT", "R3"),
    ("XRPUSDT", "R2"),
    ("XRPUSDT", "R3"),
)
_VARIANTS: tuple[str, ...] = ("camada1", "camada0")

_OUT_PATH = EXPERIMENTS_DIR / "capital_feasibility_report.json"


@dataclass(frozen=True, slots=True)
class CelulaResult:
    symbol: str
    resolution_id: str
    variant: str
    n_sinais: int
    n_sizing_ok: int
    n_sem_filtros: int
    frac_abaixo_min_qty: float
    frac_abaixo_min_notional: float
    frac_executavel: float
    quant_error_mediano: float
    quant_error_p95: float
    notional_mediano_usd: float
    edge_bps_nominal: float
    edge_bps_ponderado_por_nocional: float
    edge_bps_perdido_por_inexecutavel: float
    trades_por_mes: float
    custo_mensal_usd: float
    custo_mensal_frac_equity: float
    control_13_outcome: str


def _labels_path(symbol: str, resolution_id: str) -> Path:
    return labels_symbol_tf_dir(symbol, "v1", tf=resolution_id) / "labels.parquet"


def _carrega_sinais(symbol: str, resolution_id: str, variant: str) -> pl.DataFrame | None:
    pred_path = (
        EXPERIMENTS_DIR
        / f"alpha_walk_forward_predictions_{symbol}_{resolution_id}_{variant}.parquet"
    )
    labels_path = _labels_path(symbol, resolution_id)
    if not pred_path.exists() or not labels_path.exists():
        logger.warning(
            "capital_feasibility.artefato_ausente",
            symbol=symbol,
            resolution_id=resolution_id,
            variant=variant,
            pred_existe=pred_path.exists(),
            labels_existe=labels_path.exists(),
        )
        return None

    pred = (
        pl.read_parquet(pred_path)
        .filter(pl.col("is_oof") & (pl.col("side_hat") != 0))
        .select("t0", "side_hat")
    )
    if pred.is_empty():
        return None

    # `side` do label tem que bater com `side_hat` da predição -- o custo e o
    # resultado do trade dependem do LADO, e os labels trazem os 2 lados por
    # `t0`. Juntar sem casar o lado misturaria o outcome do lado errado.
    labels = pl.read_parquet(
        labels_path,
        columns=["t0", "side", "atr_at_t0", "entry_price_fill", "ret_net", "barrier_hit"],
    ).filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")

    return pred.join(
        labels, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
    ).drop_nulls(["atr_at_t0", "entry_price_fill", "ret_net"])


def _sizing_por_sinal(
    df: pl.DataFrame, *, symbol: str, equity: Decimal
) -> tuple[list[SizingResult | None], int]:
    """Roda o sizing de PRODUÇÃO sinal a sinal. `None` na lista = sizing
    impossível naquela data (sem snapshot de filtros aplicável); contado à
    parte, nunca silenciado nem tratado como 'executável'."""
    resultados: list[SizingResult | None] = []
    n_sem_filtros = 0
    t0s = df["t0"].to_list()
    atrs = df["atr_at_t0"].to_list()
    precos = df["entry_price_fill"].to_list()
    for t0, atr_pct, mark_price in zip(t0s, atrs, precos, strict=True):
        t0_dt = t0 if isinstance(t0, datetime) else datetime.fromtimestamp(t0 / _MS_POR_S, tz=UTC)
        if t0_dt.tzinfo is None:
            t0_dt = t0_dt.replace(tzinfo=UTC)
        try:
            resultados.append(
                compute_sizing_asof(
                    t0=t0_dt,
                    equity=equity,
                    atr_pct=atr_pct,
                    mark_price=mark_price,
                    symbol=symbol,
                )
            )
        except NoFiltersAvailableError:
            n_sem_filtros += 1
            resultados.append(None)
    return resultados, n_sem_filtros


def _mede_celula(
    symbol: str, resolution_id: str, variant: str, *, equity: Decimal
) -> CelulaResult | None:
    df = _carrega_sinais(symbol, resolution_id, variant)
    if df is None or df.is_empty():
        return None

    sizings, n_sem_filtros = _sizing_por_sinal(df, symbol=symbol, equity=equity)
    ret_net = df["ret_net"].to_numpy().astype(np.float64)

    min_qty = np.array(
        [
            bool(s is not None and s.qty < s.filters.min_qty)
            for s in sizings
        ],
        dtype=bool,
    )
    min_notional = np.array(
        [
            bool(s is not None and s.notional_real < s.filters.min_notional)
            for s in sizings
        ],
        dtype=bool,
    )
    executavel = np.array(
        [
            bool(
                s is not None
                and s.qty >= s.filters.min_qty
                and s.notional_real >= s.filters.min_notional
                and s.qty > 0
            )
            for s in sizings
        ],
        dtype=bool,
    )
    quant_err = np.array(
        [float(s.quant_error) if s is not None else np.nan for s in sizings],
        dtype=np.float64,
    )
    notional = np.array(
        [float(s.notional_real) if s is not None else np.nan for s in sizings],
        dtype=np.float64,
    )

    n = int(ret_net.shape[0])
    n_ok = int(np.count_nonzero(executavel))

    edge_nominal = float(np.mean(ret_net)) * _BPS_PER_UNIT
    # Edge que o capital de fato captura: só os sinais executáveis, cada um
    # pesado pelo nocional REAL que seria aberto. Um sinal inexecutável
    # contribui 0 -- não é "excluído da amostra", é um trade que não
    # aconteceu.
    if n_ok and np.isfinite(notional[executavel]).any():
        w = notional[executavel]
        soma_w = float(np.sum(w))
        edge_ponderado = (
            float(np.sum(ret_net[executavel] * w) / soma_w) * _BPS_PER_UNIT  # noqa: unguarded-ratio -- guardado por `if n_ok and ...` acima; soma de nocionais positivos
            if soma_w > 0
            else float("nan")
        )
    else:
        edge_ponderado = float("nan")

    # Quanto de edge some por inexecutabilidade: a diferença entre a média
    # sobre TODOS os sinais e a média sobre os que o capital alcança.
    edge_perdido = (
        edge_nominal - float(np.mean(ret_net[executavel])) * _BPS_PER_UNIT
        if n_ok
        else float("nan")
    )

    # Custo/mês e `control_13` REAIS, com a função de produção.
    span_dias = _span_dias(df)
    trades_mes = (n_ok / span_dias * _DIAS_POR_MES) if span_dias > 0 else float("nan")  # noqa: unguarded-ratio -- guardado pelo ternario
    round_trip_bps = float(load_constant("round_trip_cost_bps"))
    notional_mediano = float(np.nanmedian(notional[executavel])) if n_ok else float("nan")
    custo_mes = (
        notional_mediano * round_trip_bps / _BPS_PER_UNIT * trades_mes  # noqa: unguarded-ratio -- _BPS_PER_UNIT e constante literal 10_000
        if np.isfinite(notional_mediano) and np.isfinite(trades_mes)
        else float("nan")
    )

    outcome = ControlOutcome.NOT_COMPUTABLE
    primeiro_ok = next((s for s in sizings if s is not None), None)
    if primeiro_ok is not None and np.isfinite(custo_mes):
        # Chamada REAL do controle de produção -- o ponto do achado B1.
        # `fees_mtd_usd` = o custo do mês inteiro projetado acima: a
        # pergunta é "no fim de um mês típico, este candidato ainda cabe no
        # orcamento?", não "cabe a primeira ordem?" (essa passa sempre).
        outcome = control_13_orcamento_fees(
            primeiro_ok, fees_mtd_usd=Decimal(str(round(custo_mes, 8)))
        )

    return CelulaResult(
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        n_sinais=n,
        n_sizing_ok=n_ok,
        n_sem_filtros=n_sem_filtros,
        frac_abaixo_min_qty=float(np.count_nonzero(min_qty) / n) if n else float("nan"),  # noqa: unguarded-ratio -- guardado pelo ternario
        frac_abaixo_min_notional=(
            float(np.count_nonzero(min_notional) / n) if n else float("nan")  # noqa: unguarded-ratio -- guardado pelo ternario
        ),
        frac_executavel=float(n_ok / n) if n else float("nan"),  # noqa: unguarded-ratio -- guardado pelo ternario
        quant_error_mediano=float(np.nanmedian(quant_err)) if n else float("nan"),
        quant_error_p95=float(np.nanpercentile(quant_err, 95)) if n else float("nan"),  # noqa: magic-number -- p95, quantil de relatório
        notional_mediano_usd=notional_mediano,
        edge_bps_nominal=edge_nominal,
        edge_bps_ponderado_por_nocional=edge_ponderado,
        edge_bps_perdido_por_inexecutavel=edge_perdido,
        trades_por_mes=trades_mes,
        custo_mensal_usd=custo_mes,
        custo_mensal_frac_equity=(
            custo_mes / float(equity) if np.isfinite(custo_mes) else float("nan")  # noqa: unguarded-ratio -- equity>0 garantido pelo argparse
        ),
        control_13_outcome=outcome.name,
    )


def _span_dias(df: pl.DataFrame) -> float:
    t0 = df["t0"]
    if t0.is_empty():
        return float("nan")
    lo, hi = t0.min(), t0.max()
    if isinstance(lo, datetime) and isinstance(hi, datetime):
        return (hi - lo).total_seconds() / _S_POR_DIA
    return (float(hi) - float(lo)) / (_S_POR_DIA * _MS_POR_S)  # type: ignore[arg-type]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--equity",
        type=float,
        default=None,
        help="capital de referência; default = `capital_inicial_brl` de constants.yaml",
    )
    args = parser.parse_args()
    equity_f = (
        args.equity if args.equity is not None else float(load_constant("capital_inicial_brl"))
    )
    if equity_f <= 0:
        raise SystemExit("--equity tem que ser > 0")
    equity = Decimal(str(equity_f))

    resultados: list[CelulaResult] = []
    for symbol, resolution_id in _CANDIDATOS:
        for variant in _VARIANTS:
            r = _mede_celula(symbol, resolution_id, variant, equity=equity)
            if r is None:
                continue
            resultados.append(r)
            logger.info(
                "capital_feasibility.celula",
                combo=f"{symbol}/{resolution_id}",
                variant=variant,
                n_sinais=r.n_sinais,
                frac_executavel=round(r.frac_executavel, 4),
                quant_error_mediano=round(r.quant_error_mediano, 4),
                edge_bps_nominal=round(r.edge_bps_nominal, 2),
                edge_bps_ponderado=round(r.edge_bps_ponderado_por_nocional, 2),
                custo_mensal_frac_equity=round(r.custo_mensal_frac_equity, 4),
                control_13=r.control_13_outcome,
            )

    payload = {
        "equity_referencia": equity_f,
        "n_celulas": len(resultados),
        "celulas": [r.__dict__ for r in resultados],
    }
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUT_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.info("capital_feasibility.gravado", path=str(_OUT_PATH), n_celulas=len(resultados))


if __name__ == "__main__":
    configure_logging(json_output=False)
    main()
