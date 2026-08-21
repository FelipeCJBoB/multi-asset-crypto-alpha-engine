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

from src.features.volatility import ParkinsonEstimator, VolatilityEstimator
from src.labels._paths import labels_symbol_tf_dir
from src.labels.triple_barrier import (
    DateLike,
    LabelConfig,
    assert_label_invariants,
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

# Fase 5 (2026-08-17, AG-036/065) -- janela real por símbolo pro
# reprocessamento R1+Parkinson, medida contra os labels 15m REAIS já em
# disco (`data/labels/{symbol}/15m/v1/labels.parquet`, `t0.min()`), não
# estipulada: BTCUSDT começa em 2020-01-01 (2 anos antes dos alts),
# confirmado dentro da cobertura real de `dollar_bars_r1` (2019-12-31 a
# 2026-08-07). Os 4 alts reusam `ALT_START_DATE` -- mesma janela de
# sempre, também dentro da cobertura real de `dollar_bars_r1` pra eles
# (2021-12-01 a 2026-08-07).
ALL_SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", *ALT_SYMBOLS)
SYMBOL_START_DATE: Final[dict[str, str]] = {
    "BTCUSDT": "2020-01-01",
    "ETHUSDT": ALT_START_DATE,
    "SOLUSDT": ALT_START_DATE,
    "BNBUSDT": ALT_START_DATE,
    "XRPUSDT": ALT_START_DATE,
}


def build_and_write_labels_for_symbol(
    symbol: str,
    start: DateLike,
    end: DateLike,
    *,
    version: str = "v1",
    tf: str = "15m",
    resolution_id: str | None = None,
    config: LabelConfig | None = None,
    estimator: VolatilityEstimator | None = None,
) -> Path:
    """Núcleo de 1 símbolo — `build_labels_for_symbol` +
    `write_labels_atomic(dest_dir=labels_symbol_tf_dir(...))`, o par que
    AG-006 encontrou sem nenhum caller de produção. `historical_filters_
    fallback=True` sempre, não exposto como parâmetro — ver item 3 da
    docstring do módulo, não é uma escolha por combinação, é a única opção
    viável dado que só existe 1 snapshot de filtros no disco.

    `resolution_id`/`estimator` (2026-08-17, Fase 5 da migração
    Parkinson+dollar-bar) — `None`/`None` (default) preserva bit-exato
    todo caller existente (`run_and_write_labels_for_alts`, grade de
    tempo, `ATRWilderEstimator` implícito de `LabelConfig.from_constants`).
    Setar `resolution_id` SEM também passar `estimator` levantaria dentro
    de `build_labels_for_symbol` (AG-036: `estimator` é obrigatório sob
    dollar bar) — falha alto lá, não escondida aqui. `dest_dir` agora usa
    `resolution_id` (quando setado) como segmento de grade em vez de
    `tf` — mesma guarda anti-colisão de `labels_symbol_tf_dir` (Fase 1):
    sem isso, escrever sob `resolution_id="R1"` com `tf` no default
    `"15m"` colidiria com `data/labels/{symbol}/15m/v1/`, os labels REAIS
    de produção dos 5 `model_id` já treinados."""
    cfg = config if config is not None else LabelConfig.from_constants(tf=tf)
    labels = build_labels_for_symbol(
        symbol, start, end, config=cfg, estimator=estimator, historical_filters_fallback=True
    )
    # AG-029 (audit/architecture_gaps_log.yaml) -- assert_label_invariants
    # existia desde §3.8 mas nunca era chamada no caminho real de escrita,
    # só em teste sobre dado sintético; sample_weight/n_bars_held/uniqueness
    # de PRODUÇÃO nunca passavam por nenhuma validação entre calcular e
    # persistir. Falha alto de propósito (mesma disciplina de apply_weights,
    # src/labels/weights.py) -- symbol/tf reinjetados na mensagem porque
    # run_and_write_labels_for_alts roda em ProcessPoolExecutor, e um
    # AssertionError sem contexto não diria qual dos 4 alts falhou.
    try:
        # AG-116 (2026-08-20) -- assert_label_invariants agora exige XOR
        # entre time_stop_ms/horizon_bars (mesmo par tf/resolution_id de
        # LabelConfig) -- roteado aqui pelo mesmo campo que já decide qual
        # dos dois é a fonte de horizonte real desta config.
        if cfg.resolution_id is not None:
            assert_label_invariants(labels, horizon_bars=cfg.horizon_bars)
        else:
            assert_label_invariants(labels, time_stop_ms=cfg.time_stop_ms)
    except AssertionError as exc:
        raise AssertionError(
            f"build_and_write_labels_for_symbol: invariante de label violada "
            f"para {symbol}/{tf} (AG-029) -- {exc}"
        ) from exc
    dest_dir = labels_symbol_tf_dir(symbol, version, tf=tf, resolution_id=resolution_id)
    dest_path = write_labels_atomic(labels, version=version, dest_dir=dest_dir)
    logger.info(
        "labels.backfill_multi_symbol.symbol_done",
        symbol=symbol,
        tf=tf,
        resolution_id=resolution_id,
        version=version,
        n_rows=labels.height,
        dest=str(dest_path),
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


def run_and_write_labels_dollar_bar_parkinson(
    *,
    symbols: tuple[str, ...] = ALL_SYMBOLS,
    end: DateLike = END_DATE,
    version: str = "v1",
    resolution_id: str = "R1",
    vol_estimator_window: int = 20,
    max_workers: int | None = None,
) -> dict[str, Path]:
    """Fase 5 (2026-08-17, `docs/refactor_parkinson_canonico.md`) --
    reprocessa `labels/` pros 5 símbolos sob `resolution_id="R1"` +
    `ParkinsonEstimator`, mesmo padrão de paralelização de
    `run_and_write_labels_for_alts` (cada símbolo independente).

    Cobre BTCUSDT TAMBÉM (diferente de `run_and_write_labels_for_alts`,
    que exclui BTCUSDT de propósito -- ele já tinha `labels/` de grade de
    TEMPO; aqui os 5 precisam da grade NOVA, nenhum tem ainda). `start`
    por símbolo vem de `SYMBOL_START_DATE` (medido contra os labels 15m
    reais em disco, não estipulado) -- BTCUSDT começa 2 anos antes dos
    4 alts, cada um dentro da cobertura real de `data/capacity/
    dollar_bars_r1/{symbol}/` (confirmado antes desta rodada).

    `vol_estimator_window=20` -- mesmo `atr_window` (`constants.yaml`) e
    mesma convenção `parkinson_w{N}` usada por M1 (`AG-036`/`AG-065`,
    `experiments/volatility_dollar_bar_report.json`: Parkinson venceu
    especificamente em `window=20`, não um valor novo escolhido aqui.

    Escreve em `data/labels/{symbol}/R1/v1/labels.parquet` (path novo,
    guarda anti-colisão de `labels_symbol_tf_dir` — nunca
    `.../15m/v1/`, onde vivem os labels reais dos 5 `model_id` de
    produção já treinados). `mark_price_klines_1m` já existe pros 5
    símbolos (confirmado antes desta rodada, `ls data/capacity/
    mark_price_klines_1m/{symbol}/`) — sem pré-requisito de download
    pendente, diferente de `run_and_write_labels_for_alts` (item 1 da
    docstring do módulo, já resolvido em 2026-08-13)."""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    logger.info(
        "labels.backfill_multi_symbol.dollar_bar_parkinson_starting",
        n_symbols=len(symbols),
        end=str(end),
        resolution_id=resolution_id,
        vol_estimator_window=vol_estimator_window,
        max_workers=workers,
    )

    results: dict[str, Path] = {}
    with ProcessPoolExecutor(max_workers=min(workers, len(symbols))) as executor:
        future_to_symbol = {}
        for symbol in symbols:
            start = SYMBOL_START_DATE[symbol]
            estimator = ParkinsonEstimator(window=vol_estimator_window)
            cfg = LabelConfig.from_constants(
                estimator_id=estimator.estimator_id, resolution_id=resolution_id
            )
            future = executor.submit(
                build_and_write_labels_for_symbol,
                symbol,
                start,
                end,
                version=version,
                resolution_id=resolution_id,
                config=cfg,
                estimator=estimator,
            )
            future_to_symbol[future] = symbol
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            results[symbol] = future.result()

    logger.info(
        "labels.backfill_multi_symbol.dollar_bar_parkinson_done",
        n_symbols=len(results),
        results={k: str(v) for k, v in results.items()},
    )
    return results


if __name__ == "__main__":  # pragma: no cover — execução manual
    run_and_write_labels_for_alts()
