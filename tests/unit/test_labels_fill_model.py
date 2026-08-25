"""Testes de `src/labels/fill_model.py` — modelo de preenchimento
simplificado (Sprint 6, `simulate_fill_arrays`/`simulate_fill`). Cobre a
lógica pura primeiro (arrays sintéticos, sem IO) e depois confirma contra
um recorte real de `mark_1m` que o schema é klines-like (`open`/`high`/
`low`/`close`), a premissa que o módulo documenta ter verificado — não
presumido — antes de decidir usar `high`/`low` em vez de comparar só
contra um valor único por minuto."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.data import lake
from src.data._paths import CAPACITY_DIR
from src.labels import fill_model


def _skip_if_missing(day: str) -> None:
    path = CAPACITY_DIR / "mark_price_klines_1m" / "BTCUSDT" / f"{day}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


# ============================================================================
# simulate_fill_arrays — núcleo numérico
# ============================================================================


def test_fill_long_toca_limite_primeiro_candle() -> None:
    open_time = np.array([0, 60_000, 120_000], dtype=np.int64)
    low = np.array([100.5, 99.5, 98.0], dtype=np.float64)
    high = np.array([101.0, 100.5, 99.0], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms == 60_000
    assert result.fill_price == 100.0


def test_fill_short_toca_limite_por_cima() -> None:
    open_time = np.array([0, 60_000, 120_000], dtype=np.int64)
    low = np.array([98.0, 99.0, 99.5], dtype=np.float64)
    high = np.array([99.5, 100.5, 101.0], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=-1
    )
    assert result.t_entry_ms == 60_000
    assert result.fill_price == 100.0


def test_fill_nunca_toca_e_nofill() -> None:
    open_time = np.array([0, 60_000, 120_000], dtype=np.int64)
    low = np.array([100.5, 100.6, 100.7], dtype=np.float64)
    high = np.array([101.0, 101.1, 101.2], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms is None
    assert result.fill_price is None


def test_fill_pega_o_primeiro_toque_nao_o_ultimo() -> None:
    """Vários candles tocam o limite dentro da janela — tem que devolver o
    PRIMEIRO em ordem cronológica, não qualquer um."""
    open_time = np.array([0, 60_000, 120_000, 180_000], dtype=np.int64)
    low = np.array([100.5, 99.9, 99.8, 99.7], dtype=np.float64)
    high = np.array([101.0, 100.5, 100.4, 100.3], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=240_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms == 60_000  # não 120_000 nem 180_000


def test_fill_janela_estritamente_apos_t_post() -> None:
    """Candle EXATAMENTE em t_post não conta — a janela é `(t_post,
    horizon_ms]`, estritamente posterior a `t_post` (a ordem foi postada
    NAQUELE instante; o toque relevante é depois)."""
    open_time = np.array([0, 60_000], dtype=np.int64)
    low = np.array([50.0, 100.5], dtype=np.float64)  # candle em t_post=0 tocaria, mas é excluído
    high = np.array([100.5, 101.0], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=120_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms is None


def test_fill_janela_inclui_horizon_ms() -> None:
    open_time = np.array([60_000], dtype=np.int64)
    low = np.array([99.0], dtype=np.float64)
    high = np.array([100.5], dtype=np.float64)
    result = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=60_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms == 60_000


def test_fill_side_invalido_levanta_erro() -> None:
    open_time = np.array([0], dtype=np.int64)
    low = np.array([100.0], dtype=np.float64)
    high = np.array([100.0], dtype=np.float64)
    with pytest.raises(ValueError):
        fill_model.simulate_fill_arrays(
            open_time, low, high, t_post_ms=0, horizon_ms=60_000, limit_price=100.0, side=0
        )


def test_fill_horizon_antes_de_t_post_levanta_erro() -> None:
    open_time = np.array([0], dtype=np.int64)
    low = np.array([100.0], dtype=np.float64)
    high = np.array([100.0], dtype=np.float64)
    with pytest.raises(ValueError):
        fill_model.simulate_fill_arrays(
            open_time, low, high, t_post_ms=60_000, horizon_ms=0, limit_price=100.0, side=1
        )


# ============================================================================
# simulate_fill — wrapper polars, deve concordar com a versão numpy
# ============================================================================


def test_wrapper_polars_concorda_com_versao_numpy() -> None:
    mark = pl.DataFrame(
        {
            "open_time": [0, 60_000, 120_000],
            "low": [100.5, 99.5, 98.0],
            "high": [101.0, 100.5, 99.0],
        }
    )
    open_time = mark["open_time"].to_numpy().astype(np.int64)
    low = mark["low"].to_numpy()
    high = mark["high"].to_numpy()

    via_arrays = fill_model.simulate_fill_arrays(
        open_time, low, high, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=1
    )
    via_wrapper = fill_model.simulate_fill(
        mark, t_post_ms=0, horizon_ms=180_000, limit_price=100.0, side=1
    )
    assert via_arrays == via_wrapper


def test_wrapper_polars_janela_vazia_e_nofill() -> None:
    mark = pl.DataFrame({"open_time": [0], "low": [100.0], "high": [100.0]})
    result = fill_model.simulate_fill(
        mark, t_post_ms=1_000_000, horizon_ms=2_000_000, limit_price=100.0, side=1
    )
    assert result.t_entry_ms is None
    assert result.fill_price is None


# ============================================================================
# Confirmação de schema real — a premissa que o módulo documenta ter
# verificado (mark_1m é klines-like, não um único valor por minuto).
# ============================================================================

_SCHEMA_FIXTURE_DAY = "2024-01-15"


@pytest.mark.integration
def test_mark_1m_e_klines_like_nao_valor_unico_por_minuto() -> None:
    _skip_if_missing(_SCHEMA_FIXTURE_DAY)
    df = lake.query_bars(
        "BTCUSDT", "1m", _SCHEMA_FIXTURE_DAY, _SCHEMA_FIXTURE_DAY, source="mark_price_klines_1m"
    )
    assert not df.is_empty()
    for col in ("open_time", "open", "high", "low", "close"):
        assert col in df.columns
    # high >= low em toda linha — só faz sentido se for de fato um candle
    # OHLC, não um valor escalar repetido em 4 colunas por acidente.
    assert bool((df["high"] >= df["low"]).all())
    # pelo menos uma barra com high > low de verdade (variação real intra-minuto)
    assert bool((df["high"] > df["low"]).any())


# ============================================================================
# AG-221 — simulate_fill_from_trades (granularidade de TRADE)
# ============================================================================


def test_fill_trades_long_preenche_no_primeiro_trade_abaixo_do_limite() -> None:
    tt = np.array([1_000, 2_000, 3_000, 4_000], dtype=np.int64)
    px = np.array([101.0, 100.5, 99.0, 98.0], dtype=np.float64)
    res = fill_model.simulate_fill_from_trades(
        tt, px, t_post_ms=0, horizon_ms=10_000, limit_price=100.0, side=1
    )
    assert res.t_entry_ms == 3_000  # primeiro com price <= 100, nao o mais fundo
    assert res.fill_price == 100.0  # sem melhora de preco (mesma convencao do modelo de 1m)


def test_fill_trades_short_preenche_no_primeiro_trade_acima_do_limite() -> None:
    tt = np.array([1_000, 2_000, 3_000], dtype=np.int64)
    px = np.array([99.0, 100.5, 102.0], dtype=np.float64)
    res = fill_model.simulate_fill_from_trades(
        tt, px, t_post_ms=0, horizon_ms=10_000, limit_price=100.0, side=-1
    )
    assert res.t_entry_ms == 2_000
    assert res.fill_price == 100.0


def test_fill_trades_nunca_toca_devolve_nofill() -> None:
    tt = np.array([1_000, 2_000], dtype=np.int64)
    px = np.array([101.0, 102.0], dtype=np.float64)
    res = fill_model.simulate_fill_from_trades(
        tt, px, t_post_ms=0, horizon_ms=10_000, limit_price=100.0, side=1
    )
    assert res.t_entry_ms is None
    assert res.fill_price is None


def test_fill_trades_janela_estritamente_apos_t_post() -> None:
    """MESMA convenção de `simulate_fill_arrays` — um trade exatamente em
    `t_post` não conta. É o que mantém a comparação entre as duas fontes
    limpa: só a granularidade muda, não a fronteira causal (AG-221)."""
    tt = np.array([1_000, 2_000], dtype=np.int64)
    px = np.array([99.0, 99.0], dtype=np.float64)
    res = fill_model.simulate_fill_from_trades(
        tt, px, t_post_ms=1_000, horizon_ms=10_000, limit_price=100.0, side=1
    )
    assert res.t_entry_ms == 2_000


def test_fill_trades_janela_inclui_horizon_ms() -> None:
    tt = np.array([5_000], dtype=np.int64)
    px = np.array([99.0], dtype=np.float64)
    res = fill_model.simulate_fill_from_trades(
        tt, px, t_post_ms=0, horizon_ms=5_000, limit_price=100.0, side=1
    )
    assert res.t_entry_ms == 5_000


def test_fill_trades_elimina_a_espera_sintetica_do_mark_1m() -> None:
    """O achado do AG-221 em forma de teste: com a MESMA série de preços,
    o fill por trade acontece no instante do toque, enquanto o fill por
    candle de 1m só pode acontecer no `open_time` do próximo candle — uma
    espera que é pura fase de relógio e não existe em produção."""
    # decisao em t_post=10 (fase arbitraria dentro do minuto)
    t_post = 10
    # trade toca o limite 500ms depois
    tt = np.array([510], dtype=np.int64)
    px = np.array([99.0], dtype=np.float64)
    por_trade = fill_model.simulate_fill_from_trades(
        tt, px, t_post_ms=t_post, horizon_ms=120_000, limit_price=100.0, side=1
    )
    # o mesmo toque, visto por candles de 1m: so o candle que abre em 60_000
    mark_open_time = np.array([0, 60_000], dtype=np.int64)
    mark_low = np.array([99.0, 99.0], dtype=np.float64)
    mark_high = np.array([101.0, 101.0], dtype=np.float64)
    por_candle = fill_model.simulate_fill_arrays(
        mark_open_time,
        mark_low,
        mark_high,
        t_post_ms=t_post,
        horizon_ms=120_000,
        limit_price=100.0,
        side=1,
    )
    assert por_trade.t_entry_ms == 510
    assert por_candle.t_entry_ms == 60_000
    # a diferenca e a espera sintetica: ~59,5s de fase de relogio
    assert por_candle.t_entry_ms - por_trade.t_entry_ms > 59_000


def test_fill_trades_rejeita_side_invalido() -> None:
    tt = np.array([1_000], dtype=np.int64)
    px = np.array([99.0], dtype=np.float64)
    with pytest.raises(ValueError, match="side deve ser"):
        fill_model.simulate_fill_from_trades(
            tt, px, t_post_ms=0, horizon_ms=10_000, limit_price=100.0, side=0
        )


def test_fill_trades_rejeita_horizonte_invalido() -> None:
    tt = np.array([1_000], dtype=np.int64)
    px = np.array([99.0], dtype=np.float64)
    with pytest.raises(ValueError, match="deve ser posterior"):
        fill_model.simulate_fill_from_trades(
            tt, px, t_post_ms=5_000, horizon_ms=5_000, limit_price=100.0, side=1
        )


# ============================================================================
# AG-221 — wiring de entry_fill_source em LabelConfig (contrato B15)
# ============================================================================


def test_entry_fill_source_default_tecnico_difere_do_valor_de_producao() -> None:
    """AG-236 -- os dois valores sao DIFERENTES DE PROPOSITO, e o teste
    trava os dois lados.

    O default do DATACLASS e `mark_1m`: fixture sintetica que exercita o
    caminho de candle constroi `LabelConfig(...)` direto e nao tem (nem
    deveria ter) `agg_trades` para oferecer. Trocar esse default quebrou
    43 testes -- medido, nao suposto.

    O valor de PRODUCAO e `agg_trades`, e entra so por `from_constants()`,
    que le `constants.yaml::label_entry_fill_source` (§16.10: constante de
    dominio mora no YAML com proveniencia, o dataclass guarda so o default
    tecnico).

    Se um dia os dois convergirem, este teste falha -- e deve falhar, porque
    a separacao e o mecanismo."""
    import dataclasses

    from src.labels.triple_barrier import (
        ENTRY_FILL_SOURCE_AGG_TRADES,
        ENTRY_FILL_SOURCE_MARK_1M,
        LabelConfig,
    )

    campo = next(
        f for f in dataclasses.fields(LabelConfig) if f.name == "entry_fill_source"
    )
    assert campo.default == ENTRY_FILL_SOURCE_MARK_1M

    cfg = LabelConfig.from_constants(estimator_id="parkinson_w20", resolution_id="R1")
    assert cfg.entry_fill_source == ENTRY_FILL_SOURCE_AGG_TRADES


def test_entry_fill_source_muda_o_config_hash() -> None:
    """B15 -- trocar a fonte do fill muda TODO ret_net do artefato, entao
    `verify_config_hash` precisa enxergar isso. Se este teste falhar, um
    relabel poderia ser consumido como se fosse do regime antigo."""
    import dataclasses

    from src.labels.triple_barrier import (
        ENTRY_FILL_SOURCE_AGG_TRADES,
        ENTRY_FILL_SOURCE_MARK_1M,
        LabelConfig,
    )

    producao = LabelConfig.from_constants(
        estimator_id="parkinson_w20", resolution_id="R1"
    )
    assert producao.entry_fill_source == ENTRY_FILL_SOURCE_AGG_TRADES
    antigo = dataclasses.replace(producao, entry_fill_source=ENTRY_FILL_SOURCE_MARK_1M)
    assert producao.config_hash != antigo.config_hash


def test_entry_fill_source_desconhecido_falha_alto() -> None:
    """Diferente de `barrier_fill_policy_id` (marcador livre), este campo
    SELECIONA a funcao de fill -- um valor nao reconhecido cairia no ramo
    default e produziria labels do regime errado sob um config_hash que
    afirma outra coisa."""
    import dataclasses

    from src.labels.triple_barrier import LabelConfig

    base = LabelConfig.from_constants(estimator_id="parkinson_w20", resolution_id="R1")
    with pytest.raises(ValueError, match="entry_fill_source"):
        dataclasses.replace(base, entry_fill_source="fonte_inventada")


def test_agg_trades_obrigatorio_quando_a_fonte_e_agg_trades() -> None:
    """Falha alta e acionavel em vez de AttributeError cru la dentro do
    laco quente. AG-227: a fonte agg_trades aceita DUAS formas de entrega
    -- DataFrame inteiro (teste/dataset pequeno) ou feeder de chunks
    (producao) -- e o guard exige pelo menos uma delas."""
    import dataclasses

    from src.labels.triple_barrier import (
        ENTRY_FILL_SOURCE_AGG_TRADES,
        LabelConfig,
        build_labels_with_stats,
    )

    # Grade de TEMPO de proposito: sob `resolution_id` a validacao de
    # `estimator` dispara ANTES deste guard (ordem de validacao, nao bug),
    # e o teste passaria a medir a mensagem errada.
    cfg = dataclasses.replace(
        LabelConfig.from_constants(),
        entry_fill_source=ENTRY_FILL_SOURCE_AGG_TRADES,
    )
    with pytest.raises(ValueError, match="agg_trades_feeder"):
        build_labels_with_stats(
            pl.DataFrame({"open_time": [], "close": []}),
            pl.DataFrame({"open_time": [], "open": [], "high": [], "low": [], "close": []}),
            pl.DataFrame({"funding_time": [], "funding_rate": []}),
            side=1,
            config=cfg,
            agg_trades=None,
        )


# ============================================================================
# AG-227 — TradeWindowCursor (buffer deslizante, nucleo puro)
# ============================================================================


def _cursor_com(trades: list[tuple[int, float]]) -> fill_model.TradeWindowCursor:
    c = fill_model.TradeWindowCursor()
    if trades:
        c.feed(
            np.array([t for t, _ in trades], dtype=np.int64),
            np.array([p for _, p in trades], dtype=np.float64),
        )
    return c


def test_cursor_window_e_estritamente_posterior_a_t_from() -> None:
    """MESMA convencao de simulate_fill_arrays/from_trades -- um trade
    exatamente em t_post nao conta. Se divergir, o cursor entregaria uma
    janela diferente da que as duas funcoes de fill assumem."""
    c = _cursor_com([(100, 1.0), (200, 2.0), (300, 3.0)])
    t, p = c.window(100, 300)
    assert t.tolist() == [200, 300]
    assert p.tolist() == [2.0, 3.0]


def test_cursor_advance_to_descarta_o_passado() -> None:
    c = _cursor_com([(100, 1.0), (200, 2.0), (300, 3.0)])
    c.advance_to(200)
    assert c.n_buffered == 1
    assert c.last_time_ms == 300


def test_cursor_advance_to_e_idempotente_e_monotonico() -> None:
    """Chamar duas vezes com o mesmo t nao descarta a mais; chamar com t
    menor (nao deveria acontecer no laco real) nao ressuscita nada."""
    c = _cursor_com([(100, 1.0), (200, 2.0), (300, 3.0)])
    c.advance_to(200)
    n = c.n_buffered
    c.advance_to(200)
    c.advance_to(50)
    assert c.n_buffered == n


def test_cursor_needs_more_ate_cobrir_o_horizonte() -> None:
    c = fill_model.TradeWindowCursor()
    assert c.needs_more(1_000) is True  # buffer vazio sempre precisa
    c.feed(np.array([500], dtype=np.int64), np.array([1.0], dtype=np.float64))
    assert c.needs_more(1_000) is True  # 500 < 1000, ainda nao cobre
    c.feed(np.array([1_500], dtype=np.int64), np.array([2.0], dtype=np.float64))
    assert c.needs_more(1_000) is False


def test_cursor_feed_rejeita_arrays_desalinhados() -> None:
    c = fill_model.TradeWindowCursor()
    with pytest.raises(ValueError, match="paralelos"):
        c.feed(np.array([1, 2], dtype=np.int64), np.array([1.0], dtype=np.float64))


def test_cursor_feed_vazio_e_noop() -> None:
    c = _cursor_com([(100, 1.0)])
    c.feed(np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64))
    assert c.n_buffered == 1


def test_cursor_reproduz_o_fill_do_dataset_inteiro() -> None:
    """O teste que importa: alimentar em CHUNKS e deslizar tem que dar
    exatamente o mesmo fill que passar o array inteiro de uma vez. E a
    invariante que autoriza trocar 35 GB por 29 MB (AG-227)."""
    rng = np.random.default_rng(11)
    n = 5_000
    tt = np.sort(rng.integers(0, 1_000_000, size=n)).astype(np.int64)
    px = (100.0 + rng.normal(scale=2.0, size=n)).astype(np.float64)

    barras = [(int(t), int(t) + 50_000) for t in range(0, 900_000, 30_000)]

    # (a) referencia: dataset inteiro em memoria
    ref = [
        fill_model.simulate_fill_from_trades(
            tt, px, t_post_ms=tp, horizon_ms=hz, limit_price=100.0, side=1
        )
        for tp, hz in barras
    ]

    # (b) streaming: chunks de 100k ms, cursor deslizando
    cursor = fill_model.TradeWindowCursor()
    prox_chunk = 0
    chunk_ms = 100_000
    got = []
    for tp, hz in barras:
        while cursor.needs_more(hz) and prox_chunk <= 1_000_000:
            m = (tt >= prox_chunk) & (tt < prox_chunk + chunk_ms)
            cursor.feed(tt[m], px[m])
            prox_chunk += chunk_ms
        cursor.advance_to(tp)
        wt, wp = cursor.window(tp, hz)
        got.append(
            fill_model.simulate_fill_from_trades(
                wt, wp, t_post_ms=tp, horizon_ms=hz, limit_price=100.0, side=1
            )
        )

    assert [r.t_entry_ms for r in got] == [r.t_entry_ms for r in ref]
    assert [r.fill_price for r in got] == [r.fill_price for r in ref]
    assert any(r.t_entry_ms is not None for r in ref), "fixture degenerada: nenhum fill"
