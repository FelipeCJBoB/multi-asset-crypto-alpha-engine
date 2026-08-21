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


def _dollar_bar_cfg(*, estimator_id: str = "parkinson_w3", horizon_bars: int = 2) -> tb.LabelConfig:
    # AG-116 (2026-08-20) -- horizon_bars agora OBRIGATÓRIO sob
    # resolution_id (__post_init__ levanta ValueError sem ele). Default=2
    # é suficiente pros testes que só exercitam validação/erro ANTES do
    # laço por índice de build_labels (raise no topo da função) -- testes
    # que precisam de reachability real (i+horizon_bars<n) usam bars/
    # horizon_bars dedicados, não este helper.
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
        horizon_bars=horizon_bars,
    )


def test_label_config_horizon_bars_sob_tf_levanta_valueerror() -> None:
    """AG-116, item 9(iii) -- `horizon_bars` setado SEM `resolution_id`
    (grade de tempo, `tf`) é proibido, fail-loud -- nunca ignorado em
    silêncio (mesma disciplina de AG-031/B1 pra time_stop_bars/
    time_stop_ms)."""
    with pytest.raises(ValueError, match="horizon_bars"):
        tb.LabelConfig(
            2.0, 1.5, _TIME_STOP_MS_DEFAULT, 1, _ATR_WINDOW_MS_DEFAULT, 0.0002, 0.0005,
            "atr_wilder_w20", horizon_bars=32,
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
        horizon_bars=4,  # AG-116 -- obrigatório sob resolution_id, valor arbitrário aqui
    )
    assert cfg.resolution_id == "R1"
    assert cfg.tf == "15m"  # default, vestigial


def test_label_config_from_constants_resolution_id_sem_estimator_id_levanta_erro() -> None:
    with pytest.raises(ValueError, match="estimator_id"):
        tb.LabelConfig.from_constants(resolution_id="R1")


def test_label_config_from_constants_resolution_id_sem_estimator_id_e_sem_horizon_bars_erro_e_de_estimator_id() -> None:  # noqa: E501
    """AG-116 -- 'os dois ausentes': `from_constants(resolution_id=...)` sem
    `estimator_id` NEM `horizon_bars` (os dois `None`, seus defaults) tem
    dois candidatos a `ValueError` desde que `horizon_bars` também passou
    a ter uma regra especial sob `resolution_id` (decisão do Manager,
    `PLANO_MESTRE_PRINCE2.md` §15.12.3 item 9(iv)): `estimator_id`
    continua EXIGIDO explícito (levanta), `horizon_bars` NÃO -- carrega
    default de `constants.yaml` em silêncio (nunca levanta por estar
    ausente). Fixa que o erro observado é sempre o de `estimator_id`
    (checado primeiro em `from_constants`, antes de qualquer lógica de
    `horizon_bars`) -- nunca um erro mencionando `horizon_bars`, que não
    existe neste caminho."""
    with pytest.raises(ValueError, match="estimator_id") as exc_info:
        tb.LabelConfig.from_constants(resolution_id="R1")
    assert "horizon_bars" not in str(exc_info.value)


def test_build_labels_resolution_id_sem_estimator_levanta_valueerror() -> None:
    mark = _tp_long_mark()
    with pytest.raises(ValueError, match=r"resolution_id.*estimator|estimator.*resolution_id"):
        tb.build_labels(
            _synthetic_bars(), mark, _EMPTY_FUNDING, side=1, config=_dollar_bar_cfg()
        )


def _dollar_bars_multi(n_total: int) -> pl.DataFrame:
    """`n_total` dollar bars sintéticas -- mesmo padrão de preço/high/low
    constante de `_synthetic_bars()` (`+-0.2` de faixa), só que com
    `n_total` linhas em vez de 3. Necessário pros testes de `horizon_bars`
    (AG-116): o horizonte da barreira TIME agora é `i + horizon_bars` em
    ÍNDICE (não mais `t0 + time_stop_ms` em relógio), então precisa de
    barras REAIS o suficiente à frente do índice de decisão pra não cair
    em "cauda incompleta" por CONTAGEM de barra -- `_synthetic_bars()` (3
    barras, só a última com ATR válido) nunca teria `i + horizon_bars <
    n` pra nenhum `horizon_bars >= 1` (índice válido = última posição)."""
    closes = [100.0] * n_total
    open_time = [_BASE_MS + i * _BAR_MS for i in range(n_total)]
    close_time = [t + _BAR_MS - 1 for t in open_time]
    return pl.DataFrame(
        {
            "open_time": open_time,
            "close_time": close_time,
            "open": [c - 0.05 for c in closes],
            "close": closes,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
        }
    )


def test_build_labels_resolution_id_com_estimator_explicito_produz_labels_reais() -> None:
    """Caminho fim-a-fim sob dollar bar: `Bars(resolution_id=...)` em vez
    de `timeframe_minutes=`, `horizon_minutes=0` placeholder,
    `fill_horizon_ms` em relógio fixo (não multiplica por `bar_ms`, que
    nem existe aqui), `horizon_end_ms` agora por ÍNDICE (`i +
    horizon_bars`, AG-116) -- confirma que produz uma linha de label
    real, não vazia/degenerada.

    5 barras, `atr_window=3` (Parkinson) -> ATR válido a partir do índice
    2 (seed_idx=window-1) -- 3 candidatos (índices 2/3/4).

    **Achado real (corrigido 2026-08-20, achado ao rodar a suíte após a
    implementação de AG-116):** o corte de `horizon_idx = i + horizon_bars
    >= n` só é avaliado DEPOIS da entrada preencher (linhas ~1073-1122 de
    `triple_barrier.py`) -- uma barra que NUNCA preenche emite `NOFILL`
    (linha ~1084, `_append_nofill_row`) sem nunca alcançar aquele corte,
    porque a resolução de `NOFILL` depende só de `fill_timeout_ms`, nunca
    de `horizon_bars`. Não são os 3 índices igualmente sujeitos ao corte
    por contagem, como uma versão anterior deste docstring presumia sem
    reproduzir o cenário real:
    - índice 2: preenche (mark cobre `t0+1min`, perto do preço de entrada)
      e bate TP (spike em `t0+5min`) -> emite `barrier_hit=TP`.
    - índice 3: `fill_horizon_ms = t0_arr[3] + fill_timeout_ms` cai ANTES
      do próximo ponto de `mark` -- nunca preenche -> emite `NOFILL`
      (linha emitida de qualquer forma, `horizon_bars` nunca entra na
      conta pra esse desfecho).
    - índice 4: `fill_horizon_ms` ultrapassa `max_mark_open_time` (fim da
      cobertura de `mark_1m`) -- cauda incompleta, ANTES até de chegar no
      corte de `horizon_idx` -- única linha de fato excluída
      (`n_incomplete_tail=1`).
    2 linhas de saída (TP + NOFILL), não 1 -- reproduzido rodando o
    cenário exato via `uv run python -c ...` antes de corrigir esta
    asserção, não presumido. O teste dedicado que prova o corte por
    `horizon_idx` em si (sem ambiguidade de fill) é o próximo desta
    classe, `test_build_labels_resolution_id_time_pousa_exatamente_
    horizon_bars_a_frente` (preço achatado, nunca preenche por spike,
    nunca cai em NOFILL)."""
    bars = _dollar_bars_multi(5)
    t0 = int(bars["close_time"][2])
    horizon_end_ms = int(bars["close_time"][4])
    mark = _mark(
        [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            # spike bem acima de qualquer TP plausível
            (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            (horizon_end_ms, 148.0, 148.0, 148.0, 148.0),  # cobertura até o horizonte
        ]
    )
    cfg = _dollar_bar_cfg(horizon_bars=2)
    out = tb.build_labels(
        bars,
        mark,
        _EMPTY_FUNDING,
        side=1,
        config=cfg,
        estimator=ParkinsonEstimator(window=3),
    )
    assert out.height == 2  # índice 2 (TP) + índice 3 (NOFILL) -- índice 4 é cauda incompleta
    by_barrier = {row["barrier_hit"]: row for row in out.iter_rows(named=True)}
    assert set(by_barrier) == {"TP", "NOFILL"}
    tp_row = by_barrier["TP"]
    assert tp_row["atr_at_t0"] is not None and tp_row["atr_at_t0"] > 0
    assert tp_row["config_hash"] == cfg.config_hash


def test_build_labels_with_stats_conta_warmup_tail_e_tie_break() -> None:
    """F2 (AG-128, achado `audit_engineering` 2026-08-19) -- `LabelBuildStats`
    bate com os 3 contadores já documentados/reproduzidos pelo teste irmão
    acima (mesma fixture exata, só troca `build_labels` por `build_labels_
    with_stats`): 2 barras de warmup (`atr_window=3` via Parkinson,
    `seed_idx=window-1=2`, índices 0/1 sem ATR válido -- "ATR válido a
    partir do índice 2" da docstring do teste acima), 1 cauda incompleta
    (índice 4, `mark_1m` não cobre o horizonte inteiro), 0 tie-break
    (o spike só toca TP, nunca SL no mesmo candle de 1m). Antes desta
    correção, estes 3 contadores só existiam como variáveis locais
    perdidas no `return` de `build_labels` -- só saíam via `logger.info`,
    nunca eram testáveis diretamente."""
    bars = _dollar_bars_multi(5)
    t0 = int(bars["close_time"][2])
    horizon_end_ms = int(bars["close_time"][4])
    mark = _mark(
        [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            # spike bem acima de qualquer TP plausível
            (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            (horizon_end_ms, 148.0, 148.0, 148.0, 148.0),  # cobertura até o horizonte
        ]
    )
    cfg = _dollar_bar_cfg(horizon_bars=2)
    out, stats = tb.build_labels_with_stats(
        bars,
        mark,
        _EMPTY_FUNDING,
        side=1,
        config=cfg,
        estimator=ParkinsonEstimator(window=3),
    )
    assert out.height == 2
    assert stats == tb.LabelBuildStats(n_warmup_dropped=2, n_incomplete_tail=1, n_tie_break=0)
    # build_labels (sem _with_stats) continua bit-exato -- mesmo DataFrame,
    # só descarta o 2º elemento da tupla (wrapper fino, ver triple_barrier.py).
    out_compat = tb.build_labels(
        bars, mark, _EMPTY_FUNDING, side=1, config=cfg, estimator=ParkinsonEstimator(window=3)
    )
    assert out_compat.equals(out, null_equal=True)


def test_build_labels_resolution_id_time_pousa_exatamente_horizon_bars_a_frente() -> None:
    """AG-116, teste novo pedido em `PLANO_MESTRE_PRINCE2.md` §15.12.3-A
    item 7 -- barreira TIME sob `resolution_id` cai exatamente em
    `horizon_bars` índices à frente da barra de decisão, não em
    `t0 + time_stop_ms` (comportamento antigo/tf). Mesma fixture de 5
    barras/`horizon_bars=2` do teste acima, mas com preço achatado (nunca
    toca TP/SL) -- `t1` tem que bater exatamente com `close_time` do
    índice `2+2=4` (a última barra do array), e `n_bars_held ==
    horizon_bars`."""
    bars = _dollar_bars_multi(5)
    t0 = int(bars["close_time"][2])
    horizon_end_ms = int(bars["close_time"][4])
    mark = _mark(
        [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            (horizon_end_ms, 99.9, 99.95, 99.85, 99.9),
        ]
    )
    cfg = _dollar_bar_cfg(horizon_bars=2)
    out = tb.build_labels(
        bars,
        mark,
        _EMPTY_FUNDING,
        side=1,
        config=cfg,
        estimator=ParkinsonEstimator(window=3),
    )
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["barrier_hit"] == "TIME"
    assert row["n_bars_held"] == cfg.horizon_bars
    t1_ms = row["t1"].timestamp() * 1000
    assert t1_ms == pytest.approx(horizon_end_ms, abs=1.0)


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
        horizon_bars=1,  # AG-116 -- obrigatório; ver docstring do teste sobre reachability
    )


def test_build_labels_resolution_id_n_bars_held_degenerado_n_menor_que_2() -> None:
    """`n_bars_held` (AG-061 -> reavaliado sob AG-116, 2026-08-20): ANTES
    de AG-116, `horizon_end_ms` sob `resolution_id` vinha de `t0 +
    cfg.time_stop_ms` (relógio, independente de quantas decision bars
    estavam carregadas) -- com um único decision bar (n=1), isso podia
    produzir `t1 > t0_arr[-1]`, acionando o fallback degenerado de
    `median_bar_ms` (`np.diff` sobre array de 1 elemento é vazio).

    DEPOIS de AG-116, `horizon_end_ms` sob `resolution_id` vem de
    `t0_arr[i + horizon_bars]` -- por construção, SEMPRE `<= t0_arr[-1]`
    quando a linha não é cortada por cauda incompleta antes (`horizon_idx
    = i + horizon_bars >= n` -> `continue`). Com n=1 e `horizon_bars>=1`
    (mínimo permitido por `__post_init__`), `horizon_idx = 0 +
    horizon_bars >= 1 = n` SEMPRE -- a linha agora é excluída como cauda
    incompleta por CONTAGEM antes de qualquer fill/toque de barreira
    acontecer. O fallback `median_bar_ms` (`triple_barrier.py`, ramo
    final do cálculo de `n_bars_held`) fica, na prática, inalcançável pra
    chamadas de `build_labels` sob `resolution_id` que passam por este
    caminho -- este teste agora prova exatamente essa exclusão (célula
    vazia), não mais o valor degenerado de `n_bars_held`. O ramo de
    código em si NÃO foi removido (`PLANO_MESTRE_PRINCE2.md` §15.12.3-A
    item 2: "n_bars_held NÃO precisa mudar") -- fica como salvaguarda
    defensiva, documentada como tal em `build_labels`."""
    bars = _one_bar_dollar_bars()
    cfg = _one_bar_cfg()
    t0 = int(bars["close_time"][-1])
    old_style_horizon = t0 + cfg.time_stop_ms  # só pra dar cobertura de mark -- não é mais lido
    last_px = 148.0
    mark = _mark(
        [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            (old_style_horizon, last_px, last_px, last_px, last_px),
        ]
    )
    out = tb.build_labels(
        bars, mark, _EMPTY_FUNDING, side=1, config=cfg, estimator=ParkinsonEstimator(window=1)
    )
    assert out.height == 0, (
        "AG-116: n=1 decision bar + horizon_bars>=1 -- sempre cauda incompleta por "
        "contagem, nunca alcança o fallback degenerado de n_bars_held"
    )


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
        horizon_bars=1,  # AG-116 -- obrigatório; ver docstring do teste sobre reachability
    )


def test_build_labels_resolution_id_n_bars_held_degenerado_median_zero() -> None:
    """`n_bars_held` sob rajada real (`close_time` duplicado, AG-061) --
    reavaliado sob AG-116 (2026-08-20), mesmo raciocínio do teste irmão
    acima (`..._n_menor_que_2`): com `horizon_end_ms` agora por ÍNDICE
    (`t0_arr[i + horizon_bars]`, sempre `<= t0_arr[-1]` quando a linha
    sobrevive ao corte de cauda incompleta), o fallback `median_bar_ms`
    fica inalcançável sob `resolution_id` pra este fixture (n=2,
    `horizon_bars>=1` -> `horizon_idx = 1 + horizon_bars >= 2 = n`
    sempre). Mantido como regressão -- agora provando a EXCLUSÃO da
    linha, não mais o valor degenerado de `n_bars_held`."""
    bars = _two_bar_duplicate_close_time_dollar_bars()
    cfg = _two_bar_dup_cfg()
    t0 = int(bars["close_time"][-1])
    old_style_horizon = t0 + cfg.time_stop_ms  # só pra dar cobertura de mark -- não é mais lido
    last_px = 148.0
    mark = _mark(
        [
            (t0 + 1 * 60_000, 99.9, 100.0, 99.8, 99.9),
            (t0 + 5 * 60_000, 145.0, 150.0, 140.0, 148.0),
            (old_style_horizon, last_px, last_px, last_px, last_px),
        ]
    )
    out = tb.build_labels(
        bars, mark, _EMPTY_FUNDING, side=1, config=cfg, estimator=ParkinsonEstimator(window=2)
    )
    assert out.height == 0, (
        "AG-116: n=2 decision bars + horizon_bars>=1 -- sempre cauda incompleta por "
        "contagem, nunca alcança o fallback degenerado de n_bars_held"
    )


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


def test_assert_label_invariants_xor_time_stop_ms_horizon_bars() -> None:
    """AG-116 -- `time_stop_ms`/`horizon_bars` são mutuamente exclusivos,
    mesmo XOR de `LabelConfig.tf`/`resolution_id`: nenhum dos dois E os
    dois juntos levantam `ValueError` explícito, antes de qualquer
    assert de invariante rodar."""
    frame = pl.DataFrame(
        {
            "t0": _ms_utc([1000]),
            "t1": _ms_utc([2000]),
            "t_entry": _ms_utc([1000]),
            "barrier_hit": pl.Series(["TP"], dtype=pl.Categorical),
            "config_hash": ["abc"],
            "sample_weight": [1.0],
            "n_bars_held": [1],
            "uniqueness": [1.0],
        }
    )
    with pytest.raises(ValueError, match="XOR"):
        tb.assert_label_invariants(frame)  # nenhum dos dois
    with pytest.raises(ValueError, match="XOR"):
        tb.assert_label_invariants(frame, time_stop_ms=1000, horizon_bars=3)  # os dois


def test_assert_label_invariants_horizon_bars_passa_quando_dentro_do_teto() -> None:
    """AG-116 -- teto correto sob `resolution_id` é `n_bars_held <=
    horizon_bars` (contagem de barra, coluna já existe desde AG-031/B1),
    não mais `t1 - t0 <= time_stop_ms`."""
    ok = pl.DataFrame(
        {
            "t0": _ms_utc([1000]),
            "t1": _ms_utc([2000]),
            "t_entry": _ms_utc([1000]),
            "barrier_hit": pl.Series(["TIME"], dtype=pl.Categorical),
            "config_hash": ["abc"],
            "sample_weight": [1.0],
            "n_bars_held": [3],
            "uniqueness": [1.0],
        }
    )
    tb.assert_label_invariants(ok, horizon_bars=3)  # não levanta -- 3 <= 3


def test_assert_label_invariants_horizon_bars_detecta_n_bars_held_acima_do_teto() -> None:
    """AG-116 -- teste novo pedido em `PLANO_MESTRE_PRINCE2.md` §15.12.3-A
    item 7: `n_bars_held > horizon_bars` tem que quebrar, sob
    `resolution_id`, mesma disciplina do teto antigo em relógio
    (`test_assert_label_invariants_detecta_t1_menor_que_t0` acima cobre o
    caso `t1 <= t0`; este cobre o teto NOVO)."""
    bad = pl.DataFrame(
        {
            "t0": _ms_utc([1000]),
            "t1": _ms_utc([2000]),
            "t_entry": _ms_utc([1000]),
            "barrier_hit": pl.Series(["TIME"], dtype=pl.Categorical),
            "config_hash": ["abc"],
            "sample_weight": [1.0],
            "n_bars_held": [5],
            "uniqueness": [1.0],
        }
    )
    with pytest.raises(AssertionError, match="n_bars_held"):
        tb.assert_label_invariants(bad, horizon_bars=3)


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
