"""Testes de `src/labels/triple_barrier.py`.

Duas camadas: (1) fixtures SINTÉTICAS pequenas, com números conferidos à
mão (script de prototipagem do Sprint 6 — valores no corpo dos testes
abaixo batem exatamente com o que `build_labels` calcula, não são só
"passou, então tá certo"); (2) um recorte REAL de `data/capacity/`
(2024-01-01 a 2024-01-15), rodando o pipeline ponta a ponta e verificando
as seis invariantes do §3.8."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import polars as pl
import pytest

from src.data._paths import CAPACITY_DIR
from src.exchange.filters import NoFiltersAvailableError
from src.features.volatility import ATRWilderEstimator, GarmanKlassEstimator, ParkinsonEstimator
from src.labels import triple_barrier as tb

_FIXTURE_START = "2024-01-01"
_FIXTURE_END = "2024-01-15"

# AG-031/B1 -- 32/20 barras @ 15m (900_000ms), valores canônicos atuais de
# constants.yaml (time_stop_bars/atr_window, superseded por time_stop_ms/
# atr_window_ms) -- usados nas construções de LabelConfig abaixo que só
# testam sensibilidade de config_hash/tf, não a mecânica de horizonte/ATR
# em si. estimator_id="atr_wilder_w20" bate exato com
# _ATR_WINDOW_MS_DEFAULT em tf="15m" (validado por LabelConfig.
# __post_init__ -- ver AG-031/B1 em triple_barrier.py).
_TIME_STOP_MS_DEFAULT = 32 * 900_000
_ATR_WINDOW_MS_DEFAULT = 20 * 900_000


def _skip_if_missing(day: str) -> None:
    path = CAPACITY_DIR / "klines_1m" / "BTCUSDT" / f"{day}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


# ============================================================================
# round_to_tick
# ============================================================================


def test_round_to_tick_compra_arredonda_para_baixo() -> None:
    assert tb.round_to_tick(100.07, 1, Decimal("0.10")) == pytest.approx(100.0)


def test_round_to_tick_venda_arredonda_para_cima() -> None:
    assert tb.round_to_tick(100.07, -1, Decimal("0.10")) == pytest.approx(100.1)


def test_round_to_tick_multiplo_exato_fica_igual() -> None:
    assert tb.round_to_tick(100.10, 1, Decimal("0.10")) == pytest.approx(100.10)
    assert tb.round_to_tick(100.10, -1, Decimal("0.10")) == pytest.approx(100.10)


def test_round_to_tick_side_invalido_levanta_erro() -> None:
    with pytest.raises(ValueError):
        tb.round_to_tick(100.0, 0, Decimal("0.10"))


def test_round_to_tick_size_zero_devolve_preco_original() -> None:
    assert tb.round_to_tick(100.123, 1, Decimal("0")) == 100.123


# ============================================================================
# LabelConfig.config_hash — B15
# ============================================================================


def test_config_hash_deterministico() -> None:
    cfg1 = tb.LabelConfig(
        2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    cfg2 = tb.LabelConfig(
        2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    assert cfg1.config_hash == cfg2.config_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("tp_atr_mult", 2.5),
        ("sl_atr_mult", 1.0),
        ("time_stop_ms", 16 * 900_000),
        ("fill_timeout_ms", 2 * 900_000),
        # +100_000ms (não 14*900_000) -- muda o payload do hash sem mudar
        # window_bars (round(18_100_000/900_000)==20, mesmo de _CFG), senão
        # dispararia a validação de LabelConfig.__post_init__ (AG-031/B1 --
        # estimator_id ficaria "atr_wilder_w20" mas o window_bars real
        # seria 14, inconsistente).
        ("atr_window_ms", _ATR_WINDOW_MS_DEFAULT + 100_000),
        ("maker_fee", 0.0003),
        ("taker_fee", 0.0006),
        ("tf", "30m"),
        ("estimator_id", "garman_klass_w20"),
    ],
)
def test_config_hash_muda_se_qualquer_parametro_mudar(field: str, value: Any) -> None:
    """B15 — a garantia central: mudar QUALQUER parâmetro do bloco de
    barreiras muda o hash. Sem isso, labels calculados com uma config
    diferente da execução passariam despercebidos."""
    from src.data.resample import step_ms

    base = tb.LabelConfig(
        2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    changed_kwargs: dict[str, object] = {field: value}
    if field == "tf":
        # AG-031/B1 -- estimator_id codifica window_bars, que depende de tf;
        # mudar tf sozinho invalidaria estimator_id (LabelConfig.
        # __post_init__ rejeitaria) -- recalcula junto, mesma disciplina
        # que qualquer caller real precisa seguir.
        window_bars = round(base.atr_window_ms / step_ms(value))
        changed_kwargs["estimator_id"] = f"atr_wilder_w{window_bars}"
    changed = replace(base, **changed_kwargs)
    assert base.config_hash != changed.config_hash


def test_config_hash_de_constants_yaml_e_estavel() -> None:
    cfg1 = tb.LabelConfig.from_constants()
    cfg2 = tb.LabelConfig.from_constants()
    assert cfg1.config_hash == cfg2.config_hash
    assert cfg1 == cfg2


# ============================================================================
# LabelConfig.tf — AG-005 (audit/architecture_gaps_log.yaml)
# ============================================================================


def test_label_config_tf_default_e_15m() -> None:
    """Default bit-exato pra todo caller existente (nenhum passava `tf`/
    `decision_tf_minutes` antes do AG-005)."""
    cfg = tb.LabelConfig(
        2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    assert cfg.tf == "15m"


def test_label_config_tf_invalido_levanta_unsupportedtimeframeerror() -> None:
    """AG-005 — a rota escolhida (`tf: str` + `step_ms` no `__post_init__`)
    existe pra ganhar esta validação de graça (o antigo `decision_tf_minutes:
    int` aceitava qualquer inteiro, ex. 45, sem TF real correspondente)."""
    from src.data.resample import UnsupportedTimeframeError

    with pytest.raises(UnsupportedTimeframeError):
        tb.LabelConfig(
            2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005,
            "atr_wilder_w20", tf="45m",
        )


def test_label_config_from_constants_propaga_tf() -> None:
    cfg = tb.LabelConfig.from_constants(tf="30m")
    assert cfg.tf == "30m"
    assert cfg.config_hash != tb.LabelConfig.from_constants(tf="15m").config_hash


# ============================================================================
# verify_config_hash — B15, "teste que quebra se mudar um parâmetro sem
# recalcular labels"
# ============================================================================


def _one_row_labels(config_hash: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "config_hash": [config_hash],
            "ret_net": [0.01],
        }
    )


def test_verify_config_hash_passa_quando_bate() -> None:
    cfg = tb.LabelConfig(
        2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    labels = _one_row_labels(cfg.config_hash)
    tb.verify_config_hash(labels, cfg)  # não levanta


def test_verify_config_hash_quebra_se_parametro_mudou_sem_recalcular() -> None:
    """O cenário real que B15 proíbe: labels calculados com `tp_atr_mult=2.0`,
    execução rodando com `tp_atr_mult=2.5` — tem que quebrar, não passar
    silenciosamente."""
    labels_config = tb.LabelConfig(
        2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    # só tp_atr_mult mudou
    execution_config = tb.LabelConfig(
        2.5, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    labels = _one_row_labels(labels_config.config_hash)
    with pytest.raises(tb.ConfigHashMismatchError):
        tb.verify_config_hash(labels, execution_config)


def test_verify_config_hash_quebra_se_dataset_mistura_configs() -> None:
    cfg_a = tb.LabelConfig(
        2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    cfg_b = tb.LabelConfig(
        2.5, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    labels = pl.DataFrame(
        {"config_hash": [cfg_a.config_hash, cfg_b.config_hash], "ret_net": [0.01, -0.01]}
    )
    with pytest.raises(tb.ConfigHashMismatchError):
        tb.verify_config_hash(labels, cfg_a)


def test_verify_config_hash_dataset_vazio_levanta_erro() -> None:
    cfg = tb.LabelConfig(
        2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005, "atr_wilder_w20"
    )
    empty = pl.DataFrame(schema={"config_hash": pl.Utf8, "ret_net": pl.Float64})
    with pytest.raises(tb.ConfigHashMismatchError):
        tb.verify_config_hash(empty, cfg)


# ============================================================================
# build_labels — fixtures sintéticas, números conferidos à mão
# ============================================================================

_BAR_MS = 900_000
_BASE_MS = int(datetime(2026, 8, 8, 0, 0, tzinfo=UTC).timestamp() * 1000)
# 3 barras -> com atr_window=3, só a ÚLTIMA tem ATR válido (seed_idx =
# 0+3-1=2) -- exatamente 1 linha de decisão por chamada, fixture mínima.
_CLOSES = [100.0, 100.2, 99.9]
_CFG = tb.LabelConfig(
    tp_atr_mult=2.0, sl_atr_mult=1.5, time_stop_ms=4 * _BAR_MS, fill_timeout_ms=_BAR_MS,
    atr_window_ms=3 * _BAR_MS, maker_fee=0.0002, taker_fee=0.0005,
    estimator_id="atr_wilder_w3",
)
_EMPTY_FUNDING = pl.DataFrame(schema={"calc_time": pl.Int64, "last_funding_rate": pl.Float64})


# (open_time_ms, open, high, low, close) -- uma linha de mark_1m sintética
_Row = tuple[int, float, float, float, float]


def _synthetic_bars() -> pl.DataFrame:
    open_time = [_BASE_MS + i * _BAR_MS for i in range(len(_CLOSES))]
    close_time = [t + _BAR_MS - 1 for t in open_time]
    high = [c + 0.2 for c in _CLOSES]
    low = [c - 0.2 for c in _CLOSES]
    # `open` != `close` (offset fixo) -- não usado por ATRWilderEstimator
    # (só high/low/close), mas Garman-Klass/etc. precisam dele; testes de
    # injeção de estimador (abaixo) dependem desta coluna existir.
    open_ = [c - 0.05 for c in _CLOSES]
    return pl.DataFrame(
        {
            "open_time": open_time,
            "close_time": close_time,
            "open": open_,
            "close": _CLOSES,
            "high": high,
            "low": low,
        }
    )


def _t0() -> int:
    return _synthetic_bars()["close_time"][-1]


def _mark(rows: list[_Row]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "open_time": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
        }
    )


def _with_horizon_coverage(rows: list[_Row]) -> list[_Row]:
    """Garante que `mark_1m` cobre até `horizon_end_ms` — sem isso
    `build_labels` descarta a linha por "cauda incompleta" mesmo quando o
    evento de interesse acontece bem antes do fim do horizonte (medido no
    Sprint 6 prototipando este teste — comportamento correto e
    intencional: não dá pra saber de antemão que o resto do horizonte não
    importava)."""
    horizon = _t0() + _CFG.time_stop_ms
    last_px = rows[-1][4]
    return [*rows, (horizon, last_px, last_px, last_px, last_px)]


# ============================================================================
# `estimator` injetável (2026-08-12) -- VolatilityEstimator pluggable em vez
# de group_c.c01_atr_20/c02_atr_20_pct hardcoded. Ver docstring do módulo.
# ============================================================================


def _tp_long_mark() -> pl.DataFrame:
    """Mesmo cenário de `test_build_labels_tp_long` (TP bate de forma
    inequívoca) -- reusado pelos testes de injeção de estimador abaixo,
    que não precisam de um cenário novo, só variar `estimator`."""
    t0 = _t0()
    return _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            ]
        )
    )


def test_build_labels_estimator_none_e_explicito_atr_wilder_batem_bit_exato() -> None:
    """`estimator=None` (default) tem que produzir EXATAMENTE o mesmo
    resultado que passar `ATRWilderEstimator(window=round(cfg.atr_window_ms
    / bar_ms))` explicitamente -- é a alegação central da migração
    (preservar comportamento de produção, não só "parecido")."""
    mark = _tp_long_mark()
    out_default = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    out_explicit = tb.build_labels(
        _synthetic_bars(),
        mark,
        _EMPTY_FUNDING,
        side=1,
        config=_CFG,
        estimator=ATRWilderEstimator(window=_CFG.atr_window_ms // _BAR_MS),
    )
    row_default = out_default.row(0, named=True)
    row_explicit = out_explicit.row(0, named=True)
    assert row_default["atr_at_t0"] == pytest.approx(row_explicit["atr_at_t0"], abs=1e-15)
    assert row_default["tp_price"] == pytest.approx(row_explicit["tp_price"], abs=1e-12)
    assert row_default["sl_price"] == pytest.approx(row_explicit["sl_price"], abs=1e-12)


def test_build_labels_estimator_id_divergente_do_config_levanta_valueerror() -> None:
    """B15 -- passar um `GarmanKlassEstimator` mas deixar `cfg.estimator_id`
    dizendo `"atr_wilder_w3"` (o `_CFG` padrão deste arquivo) tem que
    falhar alto, nunca gerar labels com `config_hash` mentiroso."""
    mark = _tp_long_mark()
    with pytest.raises(ValueError, match="estimator_id"):
        tb.build_labels(
            _synthetic_bars(),
            mark,
            _EMPTY_FUNDING,
            side=1,
            config=_CFG,  # estimator_id="atr_wilder_w3"
            estimator=GarmanKlassEstimator(window=_CFG.atr_window_ms // _BAR_MS),
        )


def test_build_labels_garman_klass_produz_atr_at_t0_diferente_do_wilder() -> None:
    """Confirma que a injeção realmente TROCA o número, não só aceita o
    parâmetro sem efeito -- Garman-Klass e ATR de Wilder são fórmulas
    genuinamente diferentes sobre o mesmo OHLC sintético."""
    mark = _tp_long_mark()
    cfg_gk = replace(_CFG, estimator_id="garman_klass_w3")
    out_wilder = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    out_gk = tb.build_labels(
        _synthetic_bars(),
        mark,
        _EMPTY_FUNDING,
        side=1,
        config=cfg_gk,
        estimator=GarmanKlassEstimator(window=_CFG.atr_window_ms // _BAR_MS),
    )
    atr_wilder = out_wilder.row(0, named=True)["atr_at_t0"]
    atr_gk = out_gk.row(0, named=True)["atr_at_t0"]
    assert atr_wilder != pytest.approx(atr_gk)
    assert out_gk.row(0, named=True)["config_hash"] != out_wilder.row(0, named=True)["config_hash"]


# ============================================================================
# resolution_id (dollar bar, AG-042, 2026-08-17) -- mesmo XOR de
# Bars.timeframe_minutes/resolution_id (src.features.volatility). Não há
# bar_ms fixo sob dollar bar, então `estimator` explícito é obrigatório
# (ATRWilder default não pode ser derivado sem bar_ms).
# ============================================================================


def _dollar_bar_cfg(*, estimator_id: str = "parkinson_w3") -> tb.LabelConfig:
    return tb.LabelConfig(
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        time_stop_ms=4 * _BAR_MS,
        fill_timeout_ms=_BAR_MS,
        atr_window_ms=3 * _BAR_MS,  # vestigial sob resolution_id -- não lido
        maker_fee=0.0002,
        taker_fee=0.0005,
        estimator_id=estimator_id,
        resolution_id="R1",
    )


def test_label_config_resolution_id_invalido_levanta_valueerror() -> None:
    with pytest.raises(ValueError, match="resolution_id"):
        tb.LabelConfig(
            tp_atr_mult=2.0,
            sl_atr_mult=1.5,
            time_stop_ms=4 * _BAR_MS,
            fill_timeout_ms=_BAR_MS,
            atr_window_ms=3 * _BAR_MS,
            maker_fee=0.0002,
            taker_fee=0.0005,
            estimator_id="parkinson_w3",
            resolution_id="R4",
        )


def test_label_config_resolution_id_pula_validacao_atr_wilder() -> None:
    """Sob `resolution_id`, `__post_init__` não chama `step_ms(tf)` --
    `estimator_id` pode divergir da convenção `atr_wilder_w{N}` sem
    levantar (não há `bar_ms` pra validar contra), diferente do
    comportamento sob grade de tempo."""
    cfg = tb.LabelConfig(
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        time_stop_ms=4 * _BAR_MS,
        fill_timeout_ms=_BAR_MS,
        atr_window_ms=999 * _BAR_MS,  # deliberadamente "errado" -- não validado aqui
        maker_fee=0.0002,
        taker_fee=0.0005,
        estimator_id="atr_wilder_w3",  # não bate com atr_window_ms/bar_ms, mas ok
        resolution_id="R1",
    )
    assert cfg.resolution_id == "R1"
    assert cfg.tf == "15m"  # default, vestigial


def test_label_config_from_constants_resolution_id_sem_estimator_id_levanta_erro() -> None:
    with pytest.raises(ValueError, match="estimator_id"):
        tb.LabelConfig.from_constants(resolution_id="R1")


def test_build_labels_resolution_id_sem_estimator_levanta_valueerror() -> None:
    mark = _tp_long_mark()
    with pytest.raises(ValueError, match=r"resolution_id.*estimator|estimator.*resolution_id"):
        tb.build_labels(
            _synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_dollar_bar_cfg()
        )


def test_build_labels_resolution_id_com_estimator_explicito_produz_labels_reais() -> None:
    """Caminho fim-a-fim sob dollar bar: `Bars(resolution_id=...)` em vez
    de `timeframe_minutes=`, `horizon_minutes=0` placeholder,
    `fill_horizon_ms`/`horizon_end_ms` em relógio fixo (não multiplicam
    por `bar_ms`, que nem existe aqui) -- confirma que produz uma linha
    de label real, não vazia/degenerada."""
    mark = _tp_long_mark()
    cfg = _dollar_bar_cfg()
    out = tb.build_labels(
        _synthetic_bars(),
        mark,
        _EMPTY_FUNDING,
        side=1,
        config=cfg,
        estimator=ParkinsonEstimator(window=3),
    )
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["atr_at_t0"] is not None and row["atr_at_t0"] > 0
    assert row["config_hash"] == cfg.config_hash


def test_build_labels_resolution_id_estimator_id_divergente_levanta_valueerror() -> None:
    """B15 continua valendo sob dollar bar -- `estimator.estimator_id` tem
    que bater com `cfg.estimator_id`, mesma disciplina de grade de tempo."""
    mark = _tp_long_mark()
    cfg = _dollar_bar_cfg(estimator_id="garman_klass_w3")  # não bate com Parkinson abaixo
    with pytest.raises(ValueError, match="estimator_id"):
        tb.build_labels(
            _synthetic_bars(),
            mark,
            _EMPTY_FUNDING,
            side=1,
            config=cfg,
            estimator=ParkinsonEstimator(window=3),
        )


# ============================================================================
# n_bars_held sob resolution_id -- branches degenerados de median_bar_ms
# (achado de auditoria, audit_engineering 2026-08-17: só o caso "normal"
# era exercitado por test_build_labels_resolution_id_com_estimator_
# explicito_produz_labels_reais acima, nunca n<2 nem median<=0 -- AG-061
# já confirmou o 2º caso acontecer de verdade em SOLUSDT)
# ============================================================================


def _one_bar_dollar_bars() -> pl.DataFrame:
    """1 único decision bar carregado -- t0_arr.shape[0]==1, não dá pra
    medir `np.diff` (precisa de >= 2 pontos)."""
    close = 99.9
    open_time = _BASE_MS
    close_time = open_time + _BAR_MS - 1
    return pl.DataFrame(
        {
            "open_time": [open_time],
            "close_time": [close_time],
            "open": [close - 0.05],
            "close": [close],
            "high": [close + 0.2],
            "low": [close - 0.2],
        }
    )


def _one_bar_cfg() -> tb.LabelConfig:
    return tb.LabelConfig(
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        time_stop_ms=4 * _BAR_MS,
        fill_timeout_ms=_BAR_MS,
        atr_window_ms=1 * _BAR_MS,
        maker_fee=0.0002,
        taker_fee=0.0005,
        estimator_id="parkinson_w1",
        resolution_id="R1",
    )


def test_build_labels_resolution_id_n_bars_held_degenerado_n_menor_que_2() -> None:
    """`n_bars_held` (AG-061): com um único decision bar carregado (n=1),
    `median_bar_ms` cai direto no fallback `cfg.time_stop_ms` -- sem tentar
    `np.median` sobre um array vazio de diffs. `n_bars_held` esperado:
    `(n-1-i) + ceil((t1-t0_arr[-1])/time_stop_ms)` = `0 + ceil(time_stop_ms/
    time_stop_ms)` = `1` (t1 == horizon == t0 + time_stop_ms)."""
    bars = _one_bar_dollar_bars()
    cfg = _one_bar_cfg()
    t0 = int(bars["close_time"][-1])
    horizon = t0 + cfg.time_stop_ms
    last_px = 148.0
    mark = _mark(
        [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            (horizon, last_px, last_px, last_px, last_px),
        ]
    )
    out = tb.build_labels(
        bars, mark, _EMPTY_FUNDING, side=1, config=cfg, estimator=ParkinsonEstimator(window=1)
    )
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TP"
    assert row["n_bars_held"] == 1


def _two_bar_duplicate_close_time_dollar_bars() -> pl.DataFrame:
    """AG-061 -- rajada real com `close_time` repetido entre 2+ barras
    (SOLUSDT, confirmada em produção). Os dois bars compartilham o MESMO
    `close_time` -- `np.diff(t0_arr) == [0]`, `median == 0`, aciona o
    fallback `median_bar_ms <= 0`."""
    t = _BASE_MS + 5 * _BAR_MS
    closes = [100.0, 99.9]
    return pl.DataFrame(
        {
            "open_time": [t - _BAR_MS, t - _BAR_MS],
            "close_time": [t, t],
            "open": [c - 0.05 for c in closes],
            "close": closes,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
        }
    )


def _two_bar_dup_cfg() -> tb.LabelConfig:
    return tb.LabelConfig(
        tp_atr_mult=2.0,
        sl_atr_mult=1.5,
        time_stop_ms=4 * _BAR_MS,
        fill_timeout_ms=_BAR_MS,
        atr_window_ms=2 * _BAR_MS,
        maker_fee=0.0002,
        taker_fee=0.0005,
        estimator_id="parkinson_w2",
        resolution_id="R1",
    )


def test_build_labels_resolution_id_n_bars_held_degenerado_median_zero() -> None:
    """`n_bars_held` sob rajada real (`close_time` duplicado, AG-061): a
    mediana dos diffs é `0`, não negativa -- guarda `<= 0` (não só `< 0`)
    é a que de fato protege este caso real, não uma cobertura teórica."""
    bars = _two_bar_duplicate_close_time_dollar_bars()
    cfg = _two_bar_dup_cfg()
    t0 = int(bars["close_time"][-1])
    horizon = t0 + cfg.time_stop_ms
    last_px = 148.0
    mark = _mark(
        [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            (horizon, last_px, last_px, last_px, last_px),
        ]
    )
    out = tb.build_labels(
        bars, mark, _EMPTY_FUNDING, side=1, config=cfg, estimator=ParkinsonEstimator(window=2)
    )
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TP"
    assert row["n_bars_held"] == 1


def test_build_labels_tp_long() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),  # preenche a 99.9
                # spike bem acima de qualquer TP plausível
                (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            ]
        )
    )
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TP"
    assert row["label"] == 1
    assert row["entry_price_fill"] == pytest.approx(99.9)
    assert row["exit_price"] == pytest.approx(row["tp_price"])
    assert row["ret_gross"] == pytest.approx(_CFG.tp_atr_mult * row["atr_at_t0"], rel=1e-9)
    expected_net = row["ret_gross"] - _CFG.maker_fee - _CFG.maker_fee
    assert row["ret_net"] == pytest.approx(expected_net, rel=1e-9)


def test_build_labels_mfe_atr_units_tp_long_bate_ao_menos_tp_atr_mult() -> None:
    """D3 (Faixa 2) — quando `barrier_hit=='TP'`, o toque QUE definiu TP já
    é `high >= tp_price` por construção (`_first_barrier_touch`), então
    `mfe_atr_units` tem que ser >= `tp_atr_mult` (a barra que disparou TP
    pode ter ido além do preço exato de TP antes de a barreira ser
    registrada — nunca menos)."""
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            ]
        )
    )
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TP"
    assert row["mfe_atr_units"] >= _CFG.tp_atr_mult - 1e-9


def test_build_labels_mfe_atr_units_time_usa_janela_inteira() -> None:
    """Sem toque de TP/SL, `mfe_atr_units` reflete o melhor preço ATINGIDO
    em toda a janela até `horizon_end_ms` (não só o preço de saída em
    TIME) — a excursão favorável pode ter existido e revertido antes do
    time stop. `tp_price`/`sl_price` desta fixture (`_CFG`, ATR sintético
    fixo) ficam em ~100,77/~99,25 — o pico de 100,5 abaixo fica
    deliberadamente dentro dessa faixa, nunca tocando nenhuma barreira."""
    t0 = _t0()
    rows: list[_Row] = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        # sobe favoravelmente (long) sem tocar TP (~100,77), depois recua
        # sem tocar SL (~99,25) -- exit em TIME, mas o pico de 100,5 é o MFE.
        (t0 + 5 * 60_000, 100.3, 100.5, 100.2, 100.4),
        (t0 + 9 * 60_000, 100.1, 100.2, 99.8, 99.9),
    ]
    mark = _mark(_with_horizon_coverage(rows))
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TIME"
    fill_px = row["entry_price_fill"]
    atr_unit_price = fill_px * row["atr_at_t0"]
    expected_mfe = (100.5 - fill_px) / atr_unit_price
    assert row["mfe_atr_units"] == pytest.approx(expected_mfe, rel=1e-6)


def test_build_labels_mfe_atr_units_nulo_em_nofill() -> None:
    """NOFILL não tem excursão -- nunca houve trade (mesma convenção de
    `entry_price_fill`/`tp_price`/`sl_price`, todos `None`, não `0.0`)."""
    t0 = _t0()
    # limite inatingível -- nunca preenche, produz NOFILL.
    mark = _mark(
        _with_horizon_coverage(
            [(t0 + 1 * 60_000, 200.0, 210.0, 195.0, 205.0)],
        )
    )
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "NOFILL"
    assert row["mfe_atr_units"] is None


def test_build_labels_sl_long() -> None:
    t0 = _t0()
    mark = _mark(
        _with_horizon_coverage(
            [
                (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
                # crash bem abaixo de qualquer SL plausível
                (t0 + 5 * 60_000, 60.0, 65.0, 50.0, 55.0),
            ]
        )
    )
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "SL"
    assert row["label"] == -1
    assert row["exit_price"] == pytest.approx(row["sl_price"])
    assert row["ret_gross"] == pytest.approx(-_CFG.sl_atr_mult * row["atr_at_t0"], rel=1e-9)
    # SL sai a mercado -> taker na saída (§3.4 regra dura 3)
    expected_net = row["ret_gross"] - _CFG.maker_fee - _CFG.taker_fee
    assert row["ret_net"] == pytest.approx(expected_net, rel=1e-9)


def test_build_labels_tp_short_quando_preco_cai() -> None:
    """Para `side=-1`, o desfecho FAVORÁVEL é o preço CAIR — direção
    invertida em relação ao long, testada explicitamente."""
    t0 = _t0()
    rows: list[_Row] = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        (t0 + 5 * 60_000, 55.0, 60.0, 50.0, 52.0),
    ]
    mark = _mark(_with_horizon_coverage(rows))
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=-1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TP"
    assert row["label"] == 1


def test_build_labels_sl_short_quando_preco_sobe() -> None:
    t0 = _t0()
    rows: list[_Row] = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
    ]
    mark = _mark(_with_horizon_coverage(rows))
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=-1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "SL"
    assert row["label"] == -1


def test_build_labels_time_quando_nunca_toca_barreira() -> None:
    t0 = _t0()
    horizon = t0 + _CFG.time_stop_ms
    mark = _mark([(t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9), (horizon, 99.9, 99.95, 99.85, 99.9)])
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TIME"
    assert row["label"] == 0
    assert row["n_bars_held"] == _CFG.time_stop_ms // _BAR_MS
    assert row["exit_price"] == pytest.approx(99.9)
    assert row["ret_net"] == pytest.approx(-_CFG.maker_fee - _CFG.taker_fee, rel=1e-9)


def test_build_labels_n_bars_held_conta_real_e_detecta_gap_no_array_de_decisao() -> None:
    """AG-031/B1 -- n_bars_held vira contagem REAL via busca em `t0_arr`,
    não mais `ceil((t1-t0)/bar_ms)`. Constrói `bars_15m` com um GAP
    deliberado (uma barra de decisão faltando entre a entrada e o
    horizonte) -- a contagem real reflete UMA barra a menos que a
    aritmética teria dado, provando que o mecanismo é sensível a dado
    real (falha de coleta), não é só uma reformulação equivalente da mesma
    divisão. `bars_15m` estende além de `t0` (índices 3,4,5) pra dar à
    busca algo pra encontrar -- essas linhas extras viram NOFILL (mark_1m
    só cobre a janela do índice 2), filtradas antes de assertar."""
    closes = [100.0, 100.2, 99.9, 99.9, 99.9, 99.9]
    open_time = [
        _BASE_MS,
        _BASE_MS + 1 * _BAR_MS,
        _BASE_MS + 2 * _BAR_MS,
        _BASE_MS + 3 * _BAR_MS,
        _BASE_MS + 4 * _BAR_MS,
        _BASE_MS + 6 * _BAR_MS,  # GAP -- pula o slot de 5*_BAR_MS de propósito
    ]
    close_time = [t + _BAR_MS - 1 for t in open_time]
    bars = pl.DataFrame(
        {
            "open_time": open_time,
            "close_time": close_time,
            "open": [c - 0.05 for c in closes],
            "close": closes,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
        }
    )
    t0 = close_time[2]  # atr_window_ms=3*_BAR_MS -> ATR válido a partir do índice 2
    horizon = t0 + _CFG.time_stop_ms
    assert horizon == close_time[5], "fixture mal construída -- horizonte precisa cair no índice 5"

    mark = _mark([(t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9), (horizon, 99.9, 99.95, 99.85, 99.9)])
    out = tb.build_labels(bars, mark, _EMPTY_FUNDING, side=1, config=_CFG)
    filled = out.filter(pl.col("barrier_hit").cast(pl.Utf8) != "NOFILL")
    assert filled.height == 1, "só o índice 2 (t0 alvo) preenche -- 3/4/5 sem cauda de mark"
    row = filled.row(0, named=True)
    assert row["barrier_hit"] == "TIME"

    naive_arithmetic = -(-(horizon - t0) // _BAR_MS)  # ceil division, mesma fórmula antiga
    assert naive_arithmetic == 4
    assert row["n_bars_held"] == 3, "contagem real (índice 5 - índice 2) tem que refletir o gap"
    assert row["n_bars_held"] != naive_arithmetic


def test_build_labels_tf_default_bate_bit_exato_com_tf_explicito_15m() -> None:
    """AG-005 — `config` sem `tf` (default de `LabelConfig`) tem que produzir
    EXATAMENTE o mesmo resultado que `tf="15m"` explícito -- a alegação
    central da correção (preservar produção atual, não só "parecido"),
    mesmo padrão de `test_build_labels_estimator_none_e_explicito_atr_
    wilder_batem_bit_exato` acima."""
    t0 = _t0()
    horizon = t0 + _CFG.time_stop_ms
    mark = _mark([(t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9), (horizon, 99.9, 99.95, 99.85, 99.9)])
    cfg_explicit = replace(_CFG, tf="15m")
    out_default = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    out_explicit = tb.build_labels(
        _synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=cfg_explicit
    )
    assert out_default.equals(out_explicit, null_equal=True)


def test_build_labels_horizon_e_invariante_a_tf_nao_escala_mais() -> None:
    """AG-031/B1 — substitui `test_build_labels_horizon_escala_com_tf_
    diferente_de_15m` (que travava exatamente a convenção que este achado
    corrige: "horizon_end_ms escala com cfg.tf"). Com `time_stop_ms` fixo
    (relógio), `t1` de um cenário TIME tem que ser o MESMO valor absoluto
    em qualquer `tf` — por construção, `t1 == t0 + cfg.time_stop_ms`,
    sem depender de `step_ms(cfg.tf)` nenhuma. `n_bars_held`, ao
    contrário, PASSA a divergir entre TFs (mesmo relógio, `bar_ms`
    diferente -> contagem de barra diferente) — é o efeito colateral
    correto e esperado, não um bug: "nº de barras variável dentro" é
    literal do texto da decisão (AG-031, Manager, 2026-08-16)."""
    from src.data.resample import step_ms

    t0 = _t0()
    cfg_15m = _CFG
    # AG-031/B1 -- estimator_id codifica window_bars, que depende de tf;
    # replace(cfg, tf=novo) sem recalcular junto dispara a validação de
    # LabelConfig.__post_init__ (mesmo raciocínio de não deixar
    # dataclasses.replace invalidar a config silenciosamente). Em vez de
    # reusar _CFG.atr_window_ms (3 barras @ 15m -- mudaria pra 2 barras a
    # 30m, ATR ficaria válido também no índice 1 de _synthetic_bars() e
    # explodiria pra 2 linhas de saída, quebrando a premissa de 1 linha
    # deste teste), atr_window_ms é escolhido especificamente pra manter
    # window=3 TAMBÉM a 30m -- este teste é sobre time_stop/n_bars_held,
    # não sobre atr_window, então mantém o fixture de warmup inalterado.
    cfg_30m = replace(
        _CFG, tf="30m", atr_window_ms=3 * step_ms("30m")
    )
    assert cfg_30m.estimator_id == "atr_wilder_w3"  # window_bars fica 3 nos dois TFs, de propósito

    def _time_only_mark(cfg: tb.LabelConfig) -> pl.DataFrame:
        horizon = t0 + cfg.time_stop_ms
        rows: list[_Row] = [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            (horizon, 99.9, 99.95, 99.85, 99.9),
        ]
        return _mark(rows)

    out_15m = tb.build_labels(
        _synthetic_bars(), _time_only_mark(cfg_15m), _EMPTY_FUNDING, side=1, config=cfg_15m
    )
    out_30m = tb.build_labels(
        _synthetic_bars(), _time_only_mark(cfg_30m), _EMPTY_FUNDING, side=1, config=cfg_30m
    )
    row_15m = out_15m.row(0, named=True)
    row_30m = out_30m.row(0, named=True)
    assert row_15m["barrier_hit"] == "TIME"
    assert row_30m["barrier_hit"] == "TIME"
    # n_bars_held diverge por construção -- mesmo relógio, bar_ms diferente.
    assert row_15m["n_bars_held"] == cfg_15m.time_stop_ms // _BAR_MS
    assert row_30m["n_bars_held"] == cfg_30m.time_stop_ms // step_ms("30m")

    t1_15m_ms = row_15m["t1"].timestamp() * 1000
    t1_30m_ms = row_30m["t1"].timestamp() * 1000
    assert t1_15m_ms == pytest.approx(t0 + cfg_15m.time_stop_ms, abs=1.0)
    assert t1_30m_ms == pytest.approx(t0 + cfg_30m.time_stop_ms, abs=1.0)
    # a garantia central de AG-031/B1: o horizonte NÃO escala mais com tf.
    assert t1_15m_ms == pytest.approx(t1_30m_ms, abs=1.0)


def test_build_labels_nofill_quando_nunca_toca_limite() -> None:
    """§3.2 — NOFILL é desfecho de primeira classe, `label=-2`, `ret=0.0`."""
    t0 = _t0()
    mark = _mark([(t0 + m * 60_000, 100.5, 101.0, 100.5, 100.8) for m in range(1, 16)])
    out = tb.build_labels(_synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "NOFILL"
    assert row["label"] == -2
    assert row["t_entry"] is None
    assert row["entry_price_fill"] is None
    assert row["ret_net"] == 0.0
    assert row["n_bars_held"] == 0


def test_build_labels_side_invalido_levanta_erro() -> None:
    with pytest.raises(ValueError):
        tb.build_labels(_synthetic_bars(), _mark([]), _EMPTY_FUNDING, side=0, config=_CFG)


def test_build_labels_bars_vazio_devolve_frame_vazio() -> None:
    empty_bars = pl.DataFrame(
        schema={
            "open_time": pl.Int64,
            "close_time": pl.Int64,
            "close": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
        }
    )
    out = tb.build_labels(empty_bars, _mark([]), _EMPTY_FUNDING, side=1, config=_CFG)
    assert out.height == 0


# ============================================================================
# assert_label_invariants — §3.8, unidade
# ============================================================================


def test_assert_label_invariants_passa_em_frame_valido() -> None:
    t0 = _t0()
    rows: list[_Row] = [
        (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
        (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
    ]
    mark = _mark(_with_horizon_coverage(rows))
    out = tb.build_labels_both_sides(_synthetic_bars(), mark, _EMPTY_FUNDING, config=_CFG)
    tb.assert_label_invariants(out, time_stop_ms=_CFG.time_stop_ms)


def _ms_utc(values: list[int]) -> pl.Series:
    return pl.Series(values, dtype=pl.Int64).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")


def test_assert_label_invariants_detecta_t1_menor_que_t0() -> None:
    bad = pl.DataFrame(
        {
            "t0": _ms_utc([1000]),
            "t1": _ms_utc([500]),
            "t_entry": _ms_utc([500]),
            "barrier_hit": pl.Series(["TP"], dtype=pl.Categorical),
            "config_hash": ["abc"],
            "sample_weight": [1.0],
            "n_bars_held": [1],
            "uniqueness": [1.0],
        }
    )
    with pytest.raises(AssertionError):
        tb.assert_label_invariants(bad, time_stop_ms=28_800_000)


# ============================================================================
# Integração com dado real — 2024-01-01 a 2024-01-15
# ============================================================================


@pytest.mark.integration
def test_build_labels_for_symbol_strict_levanta_sem_snapshot_historico() -> None:
    """B01 real, não só documentado: por padrão (`historical_filters_fallback`
    não passado), datas anteriores a 2026-08-08 levantam
    `NoFiltersAvailableError` — só existe 1 snapshot no disco (ver
    known_gaps.exchange_info_snapshot_coverage_gap em constants.yaml)."""
    _skip_if_missing(_FIXTURE_START)
    with pytest.raises(NoFiltersAvailableError):
        tb.build_labels_for_symbol("BTCUSDT", _FIXTURE_START, "2024-01-02")


@pytest.mark.integration
def test_build_labels_for_symbol_real_dado_invariantes() -> None:
    _skip_if_missing(_FIXTURE_START)
    cfg = tb.LabelConfig.from_constants()
    out = tb.build_labels_for_symbol(
        "BTCUSDT", _FIXTURE_START, _FIXTURE_END, config=cfg, historical_filters_fallback=True
    )
    assert out.height > 0
    assert list(out.columns) == list(tb.LABEL_COLUMNS)

    tb.assert_label_invariants(out, time_stop_ms=cfg.time_stop_ms)
    tb.verify_config_hash(out, cfg)

    # side só ±1 (item 1 da docstring do módulo — nunca 0)
    assert set(out["side"].unique().to_list()) <= {1, -1}
    # os dois lados presentes (M_long/M_short, B18)
    assert set(out["side"].unique().to_list()) == {1, -1}


@pytest.mark.integration
def test_build_labels_for_symbol_determinismo() -> None:
    _skip_if_missing(_FIXTURE_START)
    cfg = tb.LabelConfig.from_constants()
    out1 = tb.build_labels_for_symbol(
        "BTCUSDT", _FIXTURE_START, "2024-01-05", config=cfg, historical_filters_fallback=True
    )
    out2 = tb.build_labels_for_symbol(
        "BTCUSDT", _FIXTURE_START, "2024-01-05", config=cfg, historical_filters_fallback=True
    )
    assert out1.equals(out2, null_equal=True)


@pytest.mark.integration
def test_build_labels_for_symbol_barrier_hit_cobre_os_quatro_desfechos() -> None:
    """Não é uma garantia estrutural (poderia, em teoria, não ocorrer um dos
    quatro num recorte pequeno) — mas sobre 2 semanas reais de BTCUSDT os
    quatro desfechos aparecem, o que é o comportamento esperado e vale a
    pena travar como regressão."""
    _skip_if_missing(_FIXTURE_START)
    out = tb.build_labels_for_symbol(
        "BTCUSDT", _FIXTURE_START, _FIXTURE_END, historical_filters_fallback=True
    )
    observed = set(out["barrier_hit"].cast(pl.Utf8).unique().to_list())
    assert observed == {"TP", "SL", "TIME", "NOFILL"}


# ============================================================================
# labels_symbol_tf_dir (PRD_V4_1.md T0.3) — layout chaveado novo, convive
# com LABELS_OUTPUT_DIR legado (não migra o artefato existente)
# ============================================================================


def test_labels_symbol_tf_dir_layout_chaveado() -> None:
    from src.labels._paths import DATA_ROOT, labels_symbol_tf_dir

    path = labels_symbol_tf_dir("ETHUSDT", "v1")
    assert path == DATA_ROOT / "labels" / "ETHUSDT" / "15m" / "v1"


def test_labels_symbol_tf_dir_aceita_tf_explicito() -> None:
    from src.labels._paths import DATA_ROOT, labels_symbol_tf_dir

    path = labels_symbol_tf_dir("ETHUSDT", "v1", tf="30m")
    assert path == DATA_ROOT / "labels" / "ETHUSDT" / "30m" / "v1"


def test_write_labels_atomic_dest_dir_override_usa_layout_chaveado(tmp_path) -> None:
    df = pl.DataFrame({"t0": [1], "label": [1]})
    keyed_dir = tmp_path / "ETHUSDT" / "15m" / "v1"
    dest = tb.write_labels_atomic(df, dest_dir=keyed_dir)
    assert dest == keyed_dir / "labels.parquet"
    assert dest.exists()
