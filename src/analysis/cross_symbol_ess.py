"""ESS transversal (`AG-216`/`AG-255`) — quantas apostas genuinamente
independentes os 5 símbolos correlacionados de fato representam, pro
`dsr_n_trials` do DSR (`AG-215`) parar de usar a contagem BRUTA de
combinações como se fossem 5 (ou 15) apostas independentes.

**Escopo desta implementação — decisão explícita, não a recomendação
"melhor" do `AG-216-ADDENDUM`.** O addendum recomendava a matriz 15×15
(as 15 combinações símbolo×resolução, que é o que de fato alimenta
`dsr_n_trials`) sobre a 5×5 (só os 5 símbolos). A 15×15 exige `ret_net`
REALIZADO (predictions + labels) de 15 combinações treinadas, alinhado
numa grade comum — trabalho de reconstrução equivalente a um retreino
parcial. A 5×5 usa o `ret_net` BRUTO do label (side=1, grade de RELÓGIO
15m, já comum entre os 5 símbolos por construção — sem o problema de
alinhamento assíncrono do dollar-bar que o addendum apontava) — zero
retreino, dado já persistido. Responde uma pergunta um pouco diferente
("os 5 ATIVOS têm processos de retorno correlacionados?" em vez de "as
15 COMBINAÇÕES treinadas têm P&L correlacionado?"), mas é a metade
barata e imediatamente mensurável do gap — a versão 15×15 fica como
próximo passo explícito, não escondida.

**Alinhamento "por t0" — resolvido por AGREGAÇÃO DIÁRIA, não por
resample de barra.** Mesma técnica já usada em
`src.analysis.faixa2_dsr_and_b2_check._daily_returns_from_trades`: soma
`ret_net` por dia de calendário, grade diária completa preenchida com
`0.0` nos dias sem barra -- isso já resolve o alinhamento por
construção (dia de calendário é comum a todo símbolo, mesmo timezone),
sem precisar declarar uma grade de clock-time intermediária.

**Peso uniforme (`1/5`), não gain_share.** `weighted_participation_
ratio` (extraído de `src.models.hhi`, ver docstring de lá) não tem
opinião sobre a origem do peso -- aqui não existe equivalente de
`gain_by_column` pra símbolo (nenhum modelo dá "importância" a um
ativo). Peso uniforme é a convenção padrão de "número efetivo de
apostas" quando nenhum critério econômico de ponderação foi declarado
(Meucci, effective number of bets, sob risco igualmente distribuído) --
decisão explícita, registrada aqui por não haver outra base."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.models._paths import EXPERIMENTS_DIR
from src.models.hhi import weighted_participation_ratio
from src.validation.cpcv import load_labels_v1

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

SYMBOLS_DEFAULT: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def _daily_ret_net_side1(symbol: str) -> pl.DataFrame:
    """Soma `ret_net` (side=1, grade de relógio 15m) por dia de
    calendário para `symbol` -- núcleo de IO fino, delega a agregação
    para `_aggregate_daily` (núcleo puro, testável sem carregar
    `labels.parquet` de verdade). `load_labels_v1(verify_config=False)`
    direto (não `build_modeling_frame`) -- só precisa de `t0`/`side`/
    `ret_net`, computar features T1 seria custo puro sem uso; e evita o
    `ConfigHashMismatchError` de uma sessão paralela ativa mexendo em
    `LabelConfig` no mesmo dia (mesma classe de colisão de AG-221/AG-225
    já vivida nesta sessão) -- aceitável aqui porque a pergunta é sobre a
    ESTRUTURA de correlação do `ret_net`, não sobre o valor econômico
    exato, e não há comparação entre cargas de hash diferente (só uma
    carga por símbolo, mesmo snapshot)."""
    labels = load_labels_v1(symbol=symbol, verify_config=False)
    long_rows = labels.filter(pl.col("side") == 1).select("t0", "ret_net")
    return _aggregate_daily(long_rows, symbol=symbol)


def _aggregate_daily(long_rows: pl.DataFrame, *, symbol: str) -> pl.DataFrame:
    """Núcleo puro (Idioma A) -- soma `ret_net` por `t0.date()`, uma
    coluna nomeada `{symbol}` (não `ret_net_day` genérico, pra sobreviver
    ao `join` de múltiplos símbolos sem colisão de nome)."""
    return (
        long_rows.with_columns(pl.col("t0").dt.date().alias("_day"))
        .group_by("_day")
        .agg(pl.col("ret_net").sum().alias(symbol))
        .sort("_day")
    )


@dataclass(frozen=True, slots=True)
class CrossSymbolESSResult:
    symbols: tuple[str, ...]
    n_days_aligned: int
    correlation_matrix: FloatArray
    n_eff: float
    hhi_effective: float
    eigenvalues: tuple[float, ...]


def compute_cross_symbol_ess(symbols: tuple[str, ...] = SYMBOLS_DEFAULT) -> CrossSymbolESSResult:
    """Casca -- carrega `ret_net` diário (side=1, grade 15m) dos
    `symbols`, alinha por INTERSECÇÃO de dias (`how="inner"`, não
    zero-fill: um dia sem histórico para um símbolo mais novo não é o
    mesmo que um dia sem sinal — zero-fill aqui inflaria correlação
    espúria nos primeiros meses de um símbolo lançado depois do BTC),
    correlaciona, aplica `weighted_participation_ratio` com peso
    uniforme."""
    per_symbol = [_daily_ret_net_side1(s) for s in symbols]
    joined = per_symbol[0]
    for df in per_symbol[1:]:
        joined = joined.join(df, on="_day", how="inner")
    n_days = joined.height
    matrix = joined.select(list(symbols)).to_numpy().astype(np.float64)
    corr = np.corrcoef(matrix, rowvar=False)
    weights = np.full(len(symbols), 1.0 / len(symbols), dtype=np.float64)
    n_eff, hhi_effective, eigenvalues = weighted_participation_ratio(corr, weights)
    logger.info(
        "analysis.cross_symbol_ess.compute_cross_symbol_ess_done",
        symbols=symbols,
        n_days_aligned=n_days,
        n_eff=n_eff,
        hhi_effective=hhi_effective,
    )
    return CrossSymbolESSResult(
        symbols=symbols,
        n_days_aligned=n_days,
        correlation_matrix=corr,
        n_eff=n_eff,
        hhi_effective=hhi_effective,
        eigenvalues=eigenvalues,
    )


def write_report_atomic(result: CrossSymbolESSResult) -> Path:
    """B29 -- `.tmp` -> `fsync` -> `rename`."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPERIMENTS_DIR / "cross_symbol_ess_report.json"
    payload: dict[str, Any] = {
        **{k: v for k, v in asdict(result).items() if k != "correlation_matrix"},
        "correlation_matrix": result.correlation_matrix.tolist(),
    }
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("analysis.cross_symbol_ess.report_written", path=str(out_path))
    return out_path


def _run_cli() -> int:
    result = compute_cross_symbol_ess()
    out_path = write_report_atomic(result)
    logger.info(
        "analysis.cross_symbol_ess.cli_done",
        n_eff=result.n_eff,
        n_days_aligned=result.n_days_aligned,
        report_path=str(out_path),
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_run_cli())
