"""Carregamento causal das fontes auxiliares do Feature Engine T1: barras
de 15m (via `src.data.lake` + `src.data.resample`, Sprint 2 — reuso, não
reimplementação) e as duas séries de futuros que faltam no schema de
klines: funding (D07) e open interest (D04/`metrics`), cada uma alinhada
barra a barra ao grid de 15m por asof-join CAUSAL (último evento com
timestamp `<= close_time` da barra — nunca um evento futuro).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import structlog

from src.data import lake
from src.data._util import metrics_timestamp_to_ms
from src.data.resample import step_ms

from ._paths import capacity_symbol_dir
from .groups import group_d
from .support import FloatArray

logger = structlog.get_logger(__name__)

DateLike = date | str


def _as_date(value: DateLike) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def load_bars_15m(symbol: str, start: DateLike | None, end: DateLike | None) -> pl.DataFrame:
    """Barras de 15m via `src.data.lake.query_bars`, que já delega para
    `src.data.resample.resample_klines` (Sprint 2) — não existe um segundo
    resample aqui, só reuso do caminho já testado (142 testes)."""
    return lake.query_bars(symbol, "15m", start, end, source="klines_1m", cast_prices=True)


def load_bars(
    symbol: str, start: DateLike | None, end: DateLike | None, *, bar_source: str = "time_15m"
) -> pl.DataFrame:
    """Dispatcher de fonte de barra pro Feature Engine T1 (validação de
    fiação de dollar bar canônico, 2026-08-16 — `src.data.build_dollar_
    bars`). `"time_15m"` (default) chama `load_bars_15m` sem nenhuma
    mudança — bit-exato, mesma função, callers existentes que não passam
    `bar_source` continuam idênticos a antes. `"dollar_r1"`/`"dollar_r2"`/
    `"dollar_r3"` chamam `src.data.lake.query_dollar_bars` com o
    `resolution_id` correspondente (barras `dollar_bars_r1`/`_r2`/`_r3` —
    mesma função/schema pros 3, já confirmado em
    `src.data.lake.query_dollar_bars`; R2/R3 wireados nesta extensão,
    2026-08-18, motivada pelo M4 rodar sob os 3 "timeframes" de produção
    reais — R1/R2/R3 SUBSTITUÍRAM M15/M30/H1 como identidade de dollar-bar,
    `PLANO_MESTRE_PRINCE2.md` AG-042). Qualquer outro valor levanta
    `ValueError` — nunca cai silenciosamente pro default.

    **Débito conhecido, não resolvido aqui (`AG-043`,
    `audit/architecture_gaps_log.yaml`, "parcialmente fechado"):** todas
    as janelas do Feature Engine (`FeatureWindows`, ex. `ema=48`) são em
    CONTAGEM DE BARRA, não tempo de calendário — sob R2 (~30min/barra) e
    R3 (~1h/barra) o mesmo "48 barras" representa um horizonte de tempo
    real bem diferente do que sob R1 (~15min/barra). Wireup mecânico
    (este dispatcher) não depende de resolver isso — mas qualquer
    consumidor que compare features/regime ENTRE resoluções precisa
    tratar essa limitação explicitamente (não é um bug deste dispatcher,
    é debt já deferido em outro lugar)."""
    if bar_source == "time_15m":
        return load_bars_15m(symbol, start, end)
    if bar_source == "dollar_r1":
        return lake.query_dollar_bars(symbol, start, end, resolution_id="R1")
    if bar_source == "dollar_r2":
        return lake.query_dollar_bars(symbol, start, end, resolution_id="R2")
    if bar_source == "dollar_r3":
        return lake.query_dollar_bars(symbol, start, end, resolution_id="R3")
    raise ValueError(
        f"bar_source={bar_source!r} desconhecido -- valores aceitos: 'time_15m', "
        "'dollar_r1', 'dollar_r2', 'dollar_r3'"
    )


def asof_align_backward(
    bars_15m: pl.DataFrame, aux: pl.DataFrame, aux_ts_col: str, value_col: str
) -> pl.Series:
    """Alinha `value_col` de `aux` a cada barra de `bars_15m` via asof-join
    estratégia `backward`: cada barra recebe o valor do último evento de
    `aux` com `aux_ts_col <= close_time` da própria barra — nunca um evento
    futuro (banned pattern B02). Barras sem nenhum evento de `aux` anterior
    (início da série, antes do primeiro dado da fonte auxiliar) recebem
    null, não um valor inventado.

    Retorna uma `pl.Series` posicionalmente alinhada 1:1 com `bars_15m` na
    ORDEM DE LINHA de entrada — não a ordem de `open_time` (que coincide
    com a ordem de linha no caminho real, `_sources.load_bars_15m`, mas o
    contrato aqui é mais forte que isso de propósito: um índice de linha
    explícito garante o comportamento mesmo se algum chamador futuro passar
    `bars_15m` fora de ordem)."""
    if aux.is_empty():
        return pl.Series(value_col, [None] * bars_15m.height, dtype=pl.Float64)

    bars_indexed = bars_15m.select(["open_time", "close_time"]).with_row_index("_row_idx")
    bars_sorted = bars_indexed.sort("close_time")
    aux_sorted = aux.select([aux_ts_col, value_col]).sort(aux_ts_col)
    joined = bars_sorted.join_asof(
        aux_sorted,
        left_on="close_time",
        right_on=aux_ts_col,
        strategy="backward",
    )
    joined = joined.sort("_row_idx")
    return joined[value_col]


def load_funding_aligned(
    bars_15m: pl.DataFrame, symbol: str, start: DateLike | None, end: DateLike | None
) -> pl.Series:
    """`funding_last` (D07) alinhado ao grid de 15m — §2.6 E01f/E02f."""
    funding = lake.query_funding(symbol, start, end)
    if funding.is_empty():
        return pl.Series("last_funding_rate", [None] * bars_15m.height, dtype=pl.Float64)
    funding = funding.with_columns(pl.col("last_funding_rate").cast(pl.Float64))
    return asof_align_backward(bars_15m, funding, "calc_time", "last_funding_rate")


def _list_metrics_day_files(symbol: str, start: date, end: date) -> list[Path]:
    symbol_dir = capacity_symbol_dir("metrics", symbol)
    files = []
    for p in sorted(symbol_dir.glob("*.parquet")):
        try:
            file_date = date.fromisoformat(p.stem)
        except ValueError:
            continue  # arquivo fora do padrão yyyy-mm-dd.parquet
        if file_date < start or file_date > end:
            continue
        files.append(p)
    return files


def _load_and_dedupe_metrics_rows(
    symbol: str, start: date, end: date, value_cols: tuple[str, ...]
) -> pl.DataFrame:
    """Núcleo COMPARTILHADO de `load_oi_series_deduped` (Sprint 3/4) e
    `load_metrics_series_deduped` (Lote C da liberação de features, H5,
    2026-08-24) — extraído aqui pra não duplicar a resolução de
    `create_time` duplicado (achado real, ver docstring de `load_oi_
    series_deduped`) quando um segundo chamador precisou ler OUTRAS
    colunas do mesmo arquivo `metrics`. `value_cols` é lido de `frames`
    junto de `create_time`/`_file_date`; devolve só `create_time` +
    `value_cols` deduplicados, SEM nenhuma limpeza de domínio específica
    de coluna (isso fica pro chamador — `sum_open_interest<=0 -> null`
    é uma regra física de OI, não generalizável às demais métricas sem
    medir separadamente se cada uma tem o mesmo tipo de leitura
    inválida; `load_oi_series_deduped` aplica essa limpeza DEPOIS de
    chamar esta função, `load_metrics_series_deduped` não aplica
    nenhuma)."""
    files = _list_metrics_day_files(symbol, start, end)
    if not files:
        schema = {"create_time": pl.Utf8, **dict.fromkeys(value_cols, pl.Float64)}
        return pl.DataFrame(schema=schema)

    # Achado real (2026-08-24, 1ª carga completa dos 62 candidatos T2 —
    # pré-requisito da Fase 1 da ablação T2→T1): schema por-arquivo
    # INCONSISTENTE em `data/capacity/metrics/{symbol}/*.parquet` — sem
    # dtype declarado na escrita original, `pl.read_parquet` infere o
    # dtype de cada arquivo diário isoladamente, e alguns dias sérializam
    # `value_cols` como String em vez de Float64 (valores numéricos
    # legítimos, ex. "1.31481877" — não corrupção, só serialização
    # diferente naquele dia). Sistêmico nos 5 símbolos (1-3 arquivos de
    # ~1700-2200 cada, confirmado por varredura antes desta correção),
    # não um caso isolado de ETHUSDT. `pl.concat(..., how="vertical")`
    # sem normalizar o dtype por arquivo falha com `SchemaError` assim
    # que o primeiro arquivo "torto" aparece na lista — cast explícito
    # aqui, por arquivo, ANTES do concat, é o ponto certo (a função já é
    # o núcleo compartilhado de leitura, não duplicar a normalização em
    # cada chamador). `strict=False` converte string numérica válida;
    # qualquer valor genuinamente não-numérico vira `null` (mesmo
    # tratamento de leitura inválida que `sum_open_interest<=0` já
    # recebe no chamador `load_oi_series_deduped`), nunca decidido aqui
    # em silêncio — contagem de casts reais logada.
    frames = []
    n_files_recast = 0
    for f in files:
        df = pl.read_parquet(f, columns=["create_time", *value_cols])
        needs_cast = [c for c in value_cols if df.schema[c] != pl.Float64]
        if needs_cast:
            n_files_recast += 1
            df = df.with_columns(
                [pl.col(c).cast(pl.Float64, strict=False) for c in needs_cast]
            )
        df = df.with_columns(pl.lit(f.stem).alias("_file_date"))
        frames.append(df)
    if n_files_recast > 0:
        logger.warning(
            "features.metrics_schema_inconsistente_por_arquivo",
            symbol=symbol,
            n_files_total=len(files),
            n_files_recast=n_files_recast,
            detail="schema inferido por arquivo diario inconsistente (String em vez de "
            "Float64) -- recast explicito aplicado, valores numericos preservados",
        )
    raw = pl.concat(frames, how="vertical")

    raw = raw.with_columns(pl.col("create_time").str.slice(0, 10).alias("_create_date"))

    dup_keys = (
        raw.filter(pl.col("create_time").is_duplicated())
        .select("create_time")
        .unique()
        .sort("create_time")
        .to_series()
        .to_list()
    )
    if dup_keys:
        logger.warning(
            "features.metrics_duplicate_create_time",
            symbol=symbol,
            value_cols=value_cols,
            n_duplicate_keys=len(dup_keys),
            example_keys=dup_keys[:10],
            resolution="mantida a linha do arquivo cujo nome bate com a data do create_time",
        )

    raw = raw.with_columns((pl.col("_file_date") == pl.col("_create_date")).alias("_is_native"))
    deduped = (
        raw.sort(["create_time", "_is_native"], descending=[False, True], maintain_order=True)
        .unique(subset=["create_time"], keep="first", maintain_order=True)
        .sort("create_time")
        .drop(["_file_date", "_create_date", "_is_native"])
    )
    return deduped


def load_metrics_series_deduped(
    symbol: str, start: DateLike, end: DateLike, value_cols: tuple[str, ...]
) -> pl.DataFrame:
    """Lote C da liberação de features (H5, 2026-08-24) — E08f/E14f/
    E16f/E18f. Generalização de `load_oi_series_deduped` (mesma
    resolução de `create_time` duplicado, `_load_and_dedupe_metrics_
    rows`) pra QUALQUER subconjunto das colunas de `schemas.METRICS`
    além de `sum_open_interest` — `sum_open_interest_value`
    (E08f_oi_notional), `sum_toptrader_long_short_ratio`
    (E14f_toptrader_ls_ratio), `count_long_short_ratio`
    (E16f_global_ls_ratio), `sum_taker_long_short_vol_ratio`
    (E18f_taker_ls_vol_ratio). Sem limpeza de domínio (diferente de
    `load_oi_series_deduped`, que trata `sum_open_interest<=0` como
    leitura inválida) — nenhuma medição própria feita ainda pras
    outras colunas sobre o que conta como valor inválido nelas."""
    start_d = _as_date(start)
    end_d = _as_date(end)
    deduped = _load_and_dedupe_metrics_rows(symbol, start_d, end_d, value_cols)
    if deduped.is_empty():
        empty_schema = {
            "create_time": pl.Utf8,
            **dict.fromkeys(value_cols, pl.Float64),
            "_ts_ms": pl.Int64,
        }
        return pl.DataFrame(schema=empty_schema)
    result: pl.DataFrame = metrics_timestamp_to_ms(deduped, create_time_col="create_time")
    return result


def load_oi_series_deduped(symbol: str, start: DateLike, end: DateLike) -> pl.DataFrame:
    """`sum_open_interest` (D04/`metrics`) por `create_time`, sem
    duplicatas cross-arquivo.

    Achado do Data Quality Engine (Sprint 3 — ver
    `data/quality_reports/quality_report_metrics_v1.json`, `failed_checks:
    ["3_duplicates", "5_8_monotonic"]`): os arquivos diários de `metrics`
    normalmente cobrem `[dia 00:05, dia+1 00:00]` — o ÚLTIMO ponto de um
    dia é o `00:00:00` do dia seguinte. Em dois dias medidos
    (`2026-06-12`, `2026-06-21`) esse padrão quebra: o arquivo do PRÓPRIO
    dia também inclui seu `00:00:00` (janela `[dia 00:00, dia 23:55]`), o
    que produz uma chave `create_time` duplicada entre o fim do arquivo
    anterior e o início deste — e não é um duplicado inofensivo: os
    valores DIVERGEM (medido: `sum_open_interest=98329.492` no arquivo de
    `2026-06-11` vs `98289.208` no de `2026-06-12`, ambos com
    `create_time="2026-06-12 00:00:00"`). Real ambiguidade de fonte, não
    reconciliável a partir dos dados sozinhos.

    Resolução determinística: para cada `create_time` duplicado, mantém a
    linha do arquivo cujo NOME (`yyyy-mm-dd`) bate com a própria data do
    `create_time` — o arquivo "nativo" daquele ponto, não a sobra do dia
    anterior. Loga via `structlog` toda vez que isso acontece (não fica
    silencioso). Não assume que o resto da série está limpo: a checagem de
    duplicata roda sobre TODO o intervalo pedido, não só nas duas datas
    conhecidas — se aparecer um terceiro dia com o mesmo problema, o log
    pega."""
    start_d = _as_date(start)
    end_d = _as_date(end)
    value_cols = ("sum_open_interest",)
    deduped = _load_and_dedupe_metrics_rows(symbol, start_d, end_d, value_cols)
    if deduped.is_empty():
        empty_schema = {"create_time": pl.Utf8, "sum_open_interest": pl.Float64, "_ts_ms": pl.Int64}
        return pl.DataFrame(schema=empty_schema)

    # Achado adicional do Sprint 4, fora dos 2 dias já conhecidos pelo Data
    # Quality Engine (Sprint 3): pontos ISOLADOS de sum_open_interest == 0.0
    # no meio de uma série normal (~70 mil), medido em produção real, ex.
    # BTCUSDT 2024-08-12 09:25:00 (vizinhos 70.954,593 / 70.988,883) — não
    # nas duas datas de duplicata, e não pego por nenhum check do
    # quality_report_metrics_v1.json (que não tem checagem de positividade
    # de OI). Open interest fisicamente não pode ser zero ou negativo para
    # um perpétuo líquido; é uma leitura ruim da API, não um dado real.
    # `Δln(oi)` de E10f explodiria pra -inf num desses pontos (log(0)) e
    # contaminaria a janela rolante de 48 barras inteira ao redor dele se
    # não fosse tratado — tratado aqui como null (evento ausente), não como
    # "OI caiu a zero", propagando como gap causal comum via o mesmo
    # asof-join backward que já lida com o dia faltante de 2026-06-13.
    bad_oi = deduped.filter(pl.col("sum_open_interest") <= 0)
    if bad_oi.height:
        logger.warning(
            "features.metrics_non_positive_open_interest",
            symbol=symbol,
            n_bad_points=bad_oi.height,
            example_create_times=bad_oi["create_time"].to_list()[:10],
            resolution="sum_open_interest <= 0 tratado como null (leitura inválida, não evento)",
        )
        deduped = deduped.with_columns(
            pl.when(pl.col("sum_open_interest") <= 0)
            .then(None)
            .otherwise(pl.col("sum_open_interest"))
            .alias("sum_open_interest")
        )

    result: pl.DataFrame = metrics_timestamp_to_ms(deduped, create_time_col="create_time")
    return result


def load_oi_aligned(
    bars_15m: pl.DataFrame, symbol: str, start: DateLike, end: DateLike
) -> pl.Series:
    """`sum_open_interest` (D04) alinhado ao grid de 15m — §2.6 E09f/E10f."""
    oi = load_oi_series_deduped(symbol, start, end)
    if oi.is_empty():
        return pl.Series("sum_open_interest", [None] * bars_15m.height, dtype=pl.Float64)
    return asof_align_backward(bars_15m, oi, "_ts_ms", "sum_open_interest")


def load_taker_imbalance_1m_agg_aligned(
    bars_15m: pl.DataFrame, symbol: str, start: DateLike | None, end: DateLike | None
) -> FloatArray:
    """D07f (§2.5) — Lote B da liberação de features (H5, 2026-08-24).
    Única feature deste lote que precisa de fonte NOVA: `klines_1m`
    BRUTO (não o já-resampled-pra-15m que o resto do Feature Engine
    consome) — via `lake.query_bars(..., tf="1m")`, mesma função/mesmo
    dataset em disco que `load_bars_15m` já usa (`tf="15m"` reamostra;
    `tf="1m"` devolve cru, sem reamostragem — `lake.query_bars` linha
    "if tf == '1m': return df").

    Ponto de entrada com IO (casca) — carrega o dado bruto, resolve
    `bucket_id` em AMBOS os grids (`open_time // step_ms("15m")`, mesma
    fronteira de relógio fixa nos dois lados, causal por construção) e
    delega o cálculo em si pro núcleo puro `group_d.d07f_taker_
    imbalance_1m_agg` — esta função não faz nenhuma aritmética de
    feature, só resolve os buckets."""
    bucket_ms = step_ms("15m")
    bars_1m = lake.query_bars(symbol, "1m", start, end, source="klines_1m", cast_prices=True)
    if bars_1m.is_empty():
        return np.full(bars_15m.height, np.nan, dtype=np.float64)

    bucket_id_1m = (bars_1m["open_time"].cast(pl.Int64) // bucket_ms).to_numpy()
    bucket_id_15m = (bars_15m["open_time"].cast(pl.Int64) // bucket_ms).to_numpy()
    out: FloatArray = group_d.d07f_taker_imbalance_1m_agg(
        bars_1m["taker_buy_volume"].cast(pl.Float64).to_numpy(),
        bars_1m["volume"].cast(pl.Float64).to_numpy(),
        bucket_id_1m,
        bucket_id_15m,
    )
    return out


#: Lote C da liberação de features (H5, 2026-08-24) — mapeamento feature ->
#: coluna real de `schemas.METRICS`. `toptrader_ls_ratio` usa a variante
#: `sum_` (baseada em SOMA de posições/notional, não `count_` baseada em
#: número de contas) — decisão do Manager, 2026-08-24: consistente com
#: `E09f_oi_contracts`/`E18f_taker_ls_vol_ratio`, que já usam colunas
#: `sum_` neste projeto (peso de capital, não contagem de contas).
_FUTURES_POSITIONING_COLS: dict[str, str] = {
    "oi_notional": "sum_open_interest_value",
    "toptrader_ls_ratio": "sum_toptrader_long_short_ratio",
    "global_ls_ratio": "count_long_short_ratio",
    "taker_ls_vol_ratio": "sum_taker_long_short_vol_ratio",
}


def load_futures_positioning_aligned(
    bars_15m: pl.DataFrame, symbol: str, start: DateLike, end: DateLike
) -> dict[str, pl.Series]:
    """Lote C da liberação de features (H5, 2026-08-24) — E08f_oi_
    notional/E14f_toptrader_ls_ratio/E16f_global_ls_ratio/E18f_taker_ls_
    vol_ratio, cada uma alinhada ao grid de 15m por asof-join backward
    (mesmo contrato causal de `load_oi_aligned`/`load_funding_aligned`).
    1 leitura/dedup só dos arquivos de `metrics`
    (`load_metrics_series_deduped`, as 4 colunas de uma vez) — evita
    reler e rededuplicar o MESMO parquet 4× pra 4 asof-joins separados
    (mesmos arquivos que `load_oi_series_deduped` já lê pra `sum_open_
    interest`)."""
    metrics = load_metrics_series_deduped(
        symbol, start, end, value_cols=tuple(_FUTURES_POSITIONING_COLS.values())
    )
    out: dict[str, pl.Series] = {}
    for feature_name, raw_col in _FUTURES_POSITIONING_COLS.items():
        if metrics.is_empty():
            out[feature_name] = pl.Series(feature_name, [None] * bars_15m.height, dtype=pl.Float64)
        else:
            out[feature_name] = asof_align_backward(bars_15m, metrics, "_ts_ms", raw_col)
    return out
