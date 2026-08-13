"""Orquestração multi-símbolo do Label Engine (§15.6 item 4,
`PLANO_MESTRE_PRINCE2.md`) — roda `triple_barrier.build_labels_for_symbol`
+ `write_labels_atomic` pros 4 alts (ETH/SOL/BNB/XRP), escrevendo no
layout chaveado `labels_symbol_tf_dir(symbol, version, tf=tf)` (T0.3) —
infraestrutura que já existia mas nunca teve um caller de produção real
até esta rodada (AG-006, `audit/architecture_gaps_log.yaml`).

**Não é código novo de domínio.** Só orquestra `build_labels_for_symbol`/
`write_labels_atomic`, ambos já corretos e já testados (`triple_barrier.py`
é arquivo crítico — deliberadamente NÃO tocado aqui; este módulo fica
fora dele de propósito, mesmo padrão de separação que `analysis/
cost_surface.py`/`analysis/volatility_comparison.py` já usam ao redor de
`triple_barrier`/`features.volatility`).

**Pré-requisitos medidos antes de escrever este módulo, não assumidos:**

1. **`mark_price_klines_1m` — bloqueador real, achado em 2026-08-13.**
   Nenhum dos 4 alts tinha essa fonte baixada (só BTCUSDT) — confirmado
   via `ls data/capacity/mark_price_klines_1m/{symbol}/`, não suposto.
   B11 exige `mark_1m` pra resolução de barreira; sem essa fonte,
   `build_labels_for_symbol` falha por dado ausente. Resolvido com
   `download_mark_price_klines_1m` (novo, `src/data/download.py`) — rode
   o comando da docstring de `run_and_write_labels_for_alts` ANTES desta
   função.
2. **`klines_1m`/`funding`/`metrics` (open interest)** já cobrem os 4
   alts desde `ALT_START_DATE` (medido do disco, mesma janela de
   `src.analysis.volatility_comparison.SYMBOL_START_DATE` — duplicada
   aqui, não importada, porque `labels/` não deveria acoplar a
   `analysis/`, que é consumidor de `labels/`, não fonte).
3. **Filtros de exchange** — só existe 1 snapshot canônico de
   `exchangeInfo` em disco (`data/raw/snapshots/exchange_info/
   2026-08-08.json`), cobrindo os 5 símbolos. Toda data anterior a
   2026-08-08 (ou seja, toda a história pedida aqui) precisa de
   `historical_filters_fallback=True` — mesmo mecanismo que o backfill
   original de BTCUSDT já usa, marca `is_fallback=True` em cada linha
   (nunca silencioso, `src.exchange.filters.NoFiltersAvailableError`
   levantaria sem o fallback).
4. **`build_modeling_frame` tinha um bug real, corrigido na mesma
   rodada** (`src/models/dataset.py`): `symbol` nunca chegava a
   `cpcv.load_labels_v1()`, que sempre carregava `BTCUSDT` — features de
   um símbolo, labels de outro, silenciosamente. Sem essa correção, gerar
   `labels/` pros 4 alts aqui não teria efeito nenhum no treino (o
   consumidor real continuaria ignorando o `symbol` pedido)."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Final

import structlog

from src.labels._paths import labels_symbol_tf_dir
from src.labels.triple_barrier import (
    DateLike,
    LabelConfig,
    build_labels_for_symbol,
    write_labels_atomic,
)

logger = structlog.get_logger(__name__)

# Janela MEDIDA do disco (ls data/capacity/{klines_1m,funding,metrics}/
# {symbol}/, 2026-08-13) -- duplicada de `src.analysis.volatility_
# comparison.SYMBOL_START_DATE`/`END_DATE` de propósito (ver docstring do
# módulo, item 2). BTCUSDT fora da lista -- já tem `labels/v1/` completo,
# esta rodada é especificamente sobre os 4 alts que nunca tiveram.
ALT_SYMBOLS: Final[tuple[str, ...]] = ("ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
ALT_START_DATE: Final[str] = "2021-12-01"
END_DATE: Final[str] = "2026-08-07"


def build_and_write_labels_for_symbol(
    symbol: str,
    start: DateLike,
    end: DateLike,
    *,
    version: str = "v1",
    tf: str = "15m",
    config: LabelConfig | None = None,
) -> Path:
    """Núcleo de 1 símbolo — `build_labels_for_symbol` +
    `write_labels_atomic(dest_dir=labels_symbol_tf_dir(...))`, o par que
    AG-006 encontrou sem nenhum caller de produção. `historical_filters_
    fallback=True` sempre, não exposto como parâmetro — ver item 3 da
    docstring do módulo, não é uma escolha por combinação, é a única opção
    viável dado que só existe 1 snapshot de filtros no disco."""
    cfg = config if config is not None else LabelConfig.from_constants(tf=tf)
    labels = build_labels_for_symbol(
        symbol, start, end, config=cfg, historical_filters_fallback=True
    )
    dest_dir = labels_symbol_tf_dir(symbol, version, tf=tf)
    dest_path = write_labels_atomic(labels, version=version, dest_dir=dest_dir)
    logger.info(
        "labels.backfill_multi_symbol.symbol_done",
        symbol=symbol, tf=tf, version=version, n_rows=labels.height, dest=str(dest_path),
    )
    return dest_path


def run_and_write_labels_for_alts(
    *,
    symbols: tuple[str, ...] = ALT_SYMBOLS,
    start: DateLike = ALT_START_DATE,
    end: DateLike = END_DATE,
    version: str = "v1",
    tf: str = "15m",
    max_workers: int | None = None,
) -> dict[str, Path]:
    """Ponto de entrada MANUAL — roda os 4 alts em paralelo (cada símbolo é
    totalmente independente dos outros, mesmo padrão de
    `volatility_operational_effect.run_and_save_operational_effect_report`).
    `max_workers=None` usa `os.cpu_count()` — explícito por padrão.

    **PRÉ-REQUISITO — rode ANTES, senão `build_labels_for_symbol` falha
    por dado ausente** (`mark_price_klines_1m` nunca existiu pros 4 alts
    até 2026-08-13, ver item 1 da docstring do módulo):
    ```
    uv run python -m src.data.download --symbols ETHUSDT SOLUSDT BNBUSDT XRPUSDT \\
        --sources mark_price_klines_1m --start 2021-12-01 --end 2026-08-07
    ```

    Chame manualmente, depois do backfill acima:
    `uv run python -m src.labels.backfill_multi_symbol`
    ou `uv run python -c "from src.labels.backfill_multi_symbol import
    run_and_write_labels_for_alts as r; r()"`."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    logger.info(
        "labels.backfill_multi_symbol.starting",
        n_symbols=len(symbols), start=str(start), end=str(end), tf=tf, max_workers=workers,
    )

    results: dict[str, Path] = {}
    with ProcessPoolExecutor(max_workers=min(workers, len(symbols))) as executor:
        future_to_symbol = {
            executor.submit(
                build_and_write_labels_for_symbol, symbol, start, end, version=version, tf=tf
            ): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            results[symbol] = future.result()

    logger.info(
        "labels.backfill_multi_symbol.done",
        n_symbols=len(results), results={k: str(v) for k, v in results.items()},
    )
    return results


if __name__ == "__main__":  # pragma: no cover — execução manual
    run_and_write_labels_for_alts()
