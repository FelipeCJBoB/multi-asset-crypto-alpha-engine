"""Testes de `src/data/build_dollar_bars.py` -- runner de VALIDAÇÃO de
dollar bar canônico (ver docstring do módulo: escopo é fiação, não a
calibração congelada de produção nem prova de validade estatística).

Testes síncronos (sem IO real de `aggTrades`): `DollarBarCalibration`,
`write_dollar_bars_and_calibration` (escrita atômica, particionamento por
dia, guarda de calibração divergente), `calibrate_dollar_threshold_for_
validation`/`build_dollar_bars_for_window` (IO mockado na fronteira,
`lake.query_bars`/`lake.query_agg_trades`), e round-trip de
`lake.query_dollar_bars` contra o writer novo -- tudo em `tmp_path`.

`lake.query_dollar_bars` (Parte 4 da spec) segue o MESMO padrão de
`query_agg_trades` -- sem parâmetro de root alternativo, "sem lógica nova".
Pra apontar leitura pra `tmp_path` em teste, duas técnicas, ambas já
estabelecidas no repo (nenhuma delas é comportamento novo em `lake.py`):
(1) `monkeypatch.setattr(data_paths, "CAPACITY_DIR", tmp_path)` -- mesmo
padrão de `tests/unit/test_features_sources.py::metrics_dir` -- redireciona
TODAS as fontes, usado nos testes 100% sintéticos abaixo; (2)
`monkeypatch.setattr(lake, "capacity_symbol_dir", ...)` com um wrapper que
só redireciona `source="dollar_bars_r1"` -- usado no teste de integração
real (ver o teste marcado `integration`/`slow` no final deste arquivo),
porque esse precisa continuar lendo `agg_trades`/`klines_1m`/`funding`/
`metrics` REAIS enquanto só a saída de `dollar_bars_r1` vai para `tmp_path`.

Um teste de integração real (`@pytest.mark.integration @pytest.mark.slow`,
skip-if-sem-backfill, mesmo padrão de `test_trades_dependent_bars_btcusdt_
sobre_dado_real_janela_curta` em `tests/unit/test_analysis_m2_worker.py`)
fecha o ciclo ponta a ponta contra dado real -- ver o teste no final deste
arquivo. **Prova fiação (não crasha), NÃO prova validade estatística --
AG-043 continua pendente.**"""

from __future__ import annotations

from pathlib import Path

import orjson
import polars as pl
import pytest

from src.data import _paths as data_paths
from src.data import build_dollar_bars, lake
from src.data._constants import load_constant as load_data_constant
from src.data.bars import LeftoverOverflowError
from src.features import build as features_build

_DAY1_MS = 1_704_067_200_000  # 2024-01-01T00:00:00Z (conferido contra test_data_lake.py)
_DAY_MS = 86_400_000

_BAR_COLUMNS_SCHEMA: dict[str, pl.DataType] = {
    "open_time": pl.Int64(),
    "close_time": pl.Int64(),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "volume": pl.Float64(),
    "quote_volume": pl.Float64(),
    "count": pl.UInt32(),
    "taker_buy_volume": pl.Float64(),
    "taker_buy_quote_volume": pl.Float64(),
}


def _synthetic_bars(*, close_time: list[int]) -> pl.DataFrame:
    n = len(close_time)
    return pl.DataFrame(
        {
            "open_time": [t - 1 for t in close_time],
            "close_time": close_time,
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1.0] * n,
            "quote_volume": [100.0] * n,
            "count": [1] * n,
            "taker_buy_volume": [0.5] * n,
            "taker_buy_quote_volume": [50.0] * n,
        },
        schema=_BAR_COLUMNS_SCHEMA,
    )


def _calibration(
    *, symbol: str = "BTCUSDT", threshold_usdt: float = 1_000_000.0
) -> build_dollar_bars.DollarBarCalibration:
    return build_dollar_bars.DollarBarCalibration(
        symbol=symbol,
        resolution_id="R1",
        threshold_usdt=threshold_usdt,
        calibration_scope="validation",
        calibration_window_start="2024-01-01",
        calibration_window_end="2024-01-02",
        n_trades=1_000,
        calibrated_at="2024-01-01T00:00:00+00:00",
    )


def _trades(n: int, *, price: float = 10.0, quantity: float = 1.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "transact_time": list(range(n)),
            "price": [price] * n,
            "quantity": [quantity] * n,
            "is_buyer_maker": [False] * n,
        },
        schema={
            "transact_time": pl.Int64,
            "price": pl.Float64,
            "quantity": pl.Float64,
            "is_buyer_maker": pl.Boolean,
        },
    )


# ============================================================================
# DollarBarCalibration
# ============================================================================


def test_dollar_bar_calibration_campos_basicos() -> None:
    c = _calibration()
    assert c.symbol == "BTCUSDT"
    assert c.resolution_id == "R1"
    assert c.calibration_scope == "validation"
    assert c.threshold_usdt == pytest.approx(1_000_000.0)


def test_calibration_scope_validation_constante_nunca_e_frozen_production() -> None:
    """Trava o invariante do módulo (docstring, item 2): o único valor de
    escopo que este módulo produz é 'validation'."""
    assert build_dollar_bars.CALIBRATION_SCOPE_VALIDATION == "validation"
    assert build_dollar_bars.CALIBRATION_SCOPE_VALIDATION != "frozen_production"


# ============================================================================
# write_dollar_bars_and_calibration
# ============================================================================


def test_write_dollar_bars_and_calibration_particiona_por_dia_e_e_atomico(
    tmp_path: Path,
) -> None:
    bars_df = _synthetic_bars(
        close_time=[_DAY1_MS + 3_600_000, _DAY1_MS + _DAY_MS + 3_600_000]
    )
    calibration = _calibration()

    written = build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df, calibration, dest_root=tmp_path
    )

    symbol_dir = tmp_path / "dollar_bars_r1" / "BTCUSDT"
    assert written["2024-01-01"] == symbol_dir / "2024-01-01.parquet"
    assert written["2024-01-02"] == symbol_dir / "2024-01-02.parquet"
    assert written["calibration"] == symbol_dir / "_calibration.json"
    assert (symbol_dir / "2024-01-01.parquet").exists()
    assert (symbol_dir / "2024-01-02.parquet").exists()
    assert (symbol_dir / "_calibration.json").exists()
    # nenhum .tmp sobra -- escrita atômica (B29)
    assert list(symbol_dir.glob("*.tmp")) == []

    day1 = pl.read_parquet(symbol_dir / "2024-01-01.parquet")
    assert day1.height == 1
    day2 = pl.read_parquet(symbol_dir / "2024-01-02.parquet")
    assert day2.height == 1

    payload = orjson.loads((symbol_dir / "_calibration.json").read_bytes())
    assert payload["threshold_usdt"] == pytest.approx(1_000_000.0)
    assert payload["calibration_scope"] == "validation"
    assert payload["resolution_id"] == "R1"


def test_write_dollar_bars_and_calibration_guarda_contra_threshold_divergente(
    tmp_path: Path,
) -> None:
    bars_df = _synthetic_bars(close_time=[_DAY1_MS + 3_600_000])
    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df, _calibration(threshold_usdt=1_000_000.0), dest_root=tmp_path
    )

    with pytest.raises(ValueError, match="threshold_usdt"):
        build_dollar_bars.write_dollar_bars_and_calibration(
            bars_df, _calibration(threshold_usdt=2_000_000.0), dest_root=tmp_path
        )

    # a guarda dispara ANTES de escrever qualquer coisa nova -- só o
    # arquivo do 1º write continua lá, não um estado misto/corrompido.
    symbol_dir = tmp_path / "dollar_bars_r1" / "BTCUSDT"
    payload = orjson.loads((symbol_dir / "_calibration.json").read_bytes())
    assert payload["threshold_usdt"] == pytest.approx(1_000_000.0)


def test_write_dollar_bars_and_calibration_mesmo_threshold_nao_levanta(
    tmp_path: Path,
) -> None:
    bars_df = _synthetic_bars(close_time=[_DAY1_MS + 3_600_000])
    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df, _calibration(threshold_usdt=1_000_000.0), dest_root=tmp_path
    )
    # não deve levantar -- mesmo threshold (dentro da tolerância)
    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df, _calibration(threshold_usdt=1_000_000.0), dest_root=tmp_path
    )


def test_write_dollar_bars_and_calibration_overwrite_permite_threshold_divergente(
    tmp_path: Path,
) -> None:
    bars_df = _synthetic_bars(close_time=[_DAY1_MS + 3_600_000])
    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df, _calibration(threshold_usdt=1_000_000.0), dest_root=tmp_path
    )

    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df,
        _calibration(threshold_usdt=2_000_000.0),
        dest_root=tmp_path,
        overwrite=True,
    )

    symbol_dir = tmp_path / "dollar_bars_r1" / "BTCUSDT"
    payload = orjson.loads((symbol_dir / "_calibration.json").read_bytes())
    assert payload["threshold_usdt"] == pytest.approx(2_000_000.0)


def test_write_dollar_bars_and_calibration_overwrite_limpa_dias_orfaos_de_janela_anterior(
    tmp_path: Path,
) -> None:
    """Achado MEDIUM de revisão independente (project_assurance,
    2026-08-16): a 1ª versão de `overwrite=True` só sobrescrevia
    `_calibration.json` e os dias presentes no `bars_df` NOVO -- dias de
    uma rodada anterior calibrada sob janela mais larga (threshold
    diferente) ficavam órfãos no diretório, misturados silenciosamente
    com o conjunto novo sob um único `_calibration.json`. Cenário: 1ª
    rodada cobre 3 dias (`threshold_A`), 2ª rodada (`overwrite=True`)
    cobre só 1 dia de uma janela mais estreita (`threshold_B`) -- os 2
    dias órfãos da 1ª rodada não podem sobreviver."""
    wide_bars = _synthetic_bars(
        close_time=[
            _DAY1_MS + 3_600_000,
            _DAY1_MS + _DAY_MS + 3_600_000,
            _DAY1_MS + 2 * _DAY_MS + 3_600_000,
        ]
    )
    build_dollar_bars.write_dollar_bars_and_calibration(
        wide_bars, _calibration(threshold_usdt=1_000_000.0), dest_root=tmp_path
    )
    symbol_dir = tmp_path / "dollar_bars_r1" / "BTCUSDT"
    assert sorted(p.name for p in symbol_dir.glob("*.parquet")) == [
        "2024-01-01.parquet",
        "2024-01-02.parquet",
        "2024-01-03.parquet",
    ]

    narrow_bars = _synthetic_bars(close_time=[_DAY1_MS + 3_600_000])
    build_dollar_bars.write_dollar_bars_and_calibration(
        narrow_bars,
        _calibration(threshold_usdt=2_000_000.0),
        dest_root=tmp_path,
        overwrite=True,
    )

    # Só o dia da janela nova sobrevive -- os 2 dias órfãos (2024-01-02,
    # 2024-01-03) foram apagados antes da escrita, não deixados pra trás.
    assert sorted(p.name for p in symbol_dir.glob("*.parquet")) == ["2024-01-01.parquet"]
    payload = orjson.loads((symbol_dir / "_calibration.json").read_bytes())
    assert payload["threshold_usdt"] == pytest.approx(2_000_000.0)


def test_build_dollar_bars_for_window_propaga_leftover_overflow_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado LOW de revisão independente (project_assurance,
    2026-08-16): o circuit breaker (`LeftoverOverflowError`) tinha
    cobertura na primitiva (`test_data_bars.py`) e no caminho de M2
    (`test_analysis_m2_worker.py`), mas não neste runner especificamente
    -- prova que `max_leftover_trades` passado aqui de fato propaga até
    `bars.dollar_bars_carry`, não só até a assinatura da função."""
    monkeypatch.setattr(
        lake, "query_agg_trades", lambda *a, **k: _trades(5, price=1.0, quantity=1.0)
    )
    with pytest.raises(LeftoverOverflowError, match=r"len\(new_leftover\)=5"):
        build_dollar_bars.build_dollar_bars_for_window(
            "BTCUSDT",
            "2024-01-01",
            "2024-01-01",
            threshold_usdt=1_000_000.0,  # nunca atingido pelos 5 trades de valor 1.0
            max_leftover_trades=3.0,
        )


# ============================================================================
# calibrate_dollar_threshold_for_validation / build_dollar_bars_for_window
# (IO mockado na fronteira -- lake.query_bars/lake.query_agg_trades)
# ============================================================================


def test_calibrate_dollar_threshold_for_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_query_bars(
        symbol: str,
        tf: str,
        start: object,
        end: object,
        *,
        source: str,
        cast_prices: bool,
        **_: object,
    ) -> pl.DataFrame:
        return pl.DataFrame({"close": [1.0] * 10, "close_time": list(range(10))})

    def _fake_query_agg_trades(
        symbol: str, start: object, end: object, **_: object
    ) -> pl.DataFrame:
        return _trades(5, price=100.0, quantity=1.0)  # total_dollar = 500.0

    monkeypatch.setattr(lake, "query_bars", _fake_query_bars)
    monkeypatch.setattr(lake, "query_agg_trades", _fake_query_agg_trades)

    calibration = build_dollar_bars.calibrate_dollar_threshold_for_validation(
        "BTCUSDT", "2024-01-01", "2024-01-01"
    )

    assert calibration.symbol == "BTCUSDT"
    assert calibration.resolution_id == "R1"
    assert calibration.calibration_scope == "validation"
    assert calibration.threshold_usdt == pytest.approx(50.0)  # 500.0 / 10 barras baseline
    assert calibration.n_trades == 5
    # Achado de revisão pessoal (2026-08-16): max_leftover_trades precisa
    # ser populado com a MESMA fórmula de m2_worker._max_leftover_trades --
    # circuit breaker de AG-034 addendum, sem isto o runner novo constrói
    # dollar bar sem a proteção que existe exatamente pra ele.
    safety_mult = float(load_data_constant("bars_threshold_leftover_safety_multiplier"))
    assert calibration.max_leftover_trades == pytest.approx((5 / 10) * safety_mult)


def test_calibrate_dollar_threshold_for_validation_sem_trades_levanta_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lake, "query_agg_trades", lambda *a, **k: pl.DataFrame())
    with pytest.raises(ValueError, match="aggTrades vazio"):
        build_dollar_bars.calibrate_dollar_threshold_for_validation(
            "BTCUSDT", "2024-01-01", "2024-01-01"
        )


# ============================================================================
# resolution_id R2/R3 -- remediação completa de M1 (AG-036, 2026-08-17):
# mesma matemática de calibração de R1, só o TF de baseline muda
# (CALIBRATION_TF_BY_RESOLUTION), não precisa de dado real pra provar isso.
# ============================================================================


@pytest.mark.parametrize(
    ("resolution_id", "expected_tf"), [("R1", "15m"), ("R2", "30m"), ("R3", "1h")]
)
def test_calibrate_dollar_threshold_for_validation_resolution_id_usa_tf_certo(
    monkeypatch: pytest.MonkeyPatch, resolution_id: str, expected_tf: str
) -> None:
    seen_tfs: list[str] = []

    def _fake_query_bars(
        symbol: str,
        tf: str,
        start: object,
        end: object,
        *,
        source: str,
        cast_prices: bool,
        **_: object,
    ) -> pl.DataFrame:
        seen_tfs.append(tf)
        return pl.DataFrame({"close": [1.0] * 10, "close_time": list(range(10))})

    def _fake_query_agg_trades(
        symbol: str, start: object, end: object, **_: object
    ) -> pl.DataFrame:
        return _trades(5, price=100.0, quantity=1.0)  # total_dollar = 500.0

    monkeypatch.setattr(lake, "query_bars", _fake_query_bars)
    monkeypatch.setattr(lake, "query_agg_trades", _fake_query_agg_trades)

    calibration = build_dollar_bars.calibrate_dollar_threshold_for_validation(
        "BTCUSDT", "2024-01-01", "2024-01-01", resolution_id=resolution_id
    )

    assert calibration.resolution_id == resolution_id
    assert calibration.threshold_usdt == pytest.approx(50.0)  # 500.0 / 10 barras baseline
    # confirma que o TF de calibração passado a query_bars é o certo pra
    # essa resolução -- não só que o campo resolution_id "de saída" bate
    # (isso não provaria que a calibração em si usou o baseline certo)
    assert all(tf == expected_tf for tf in seen_tfs)


def test_calibrate_dollar_threshold_for_validation_resolution_id_invalido_levanta_erro() -> None:
    with pytest.raises(ValueError, match="resolution_id"):
        build_dollar_bars.calibrate_dollar_threshold_for_validation(
            "BTCUSDT", "2024-01-01", "2024-01-01", resolution_id="R4"
        )


def test_write_dollar_bars_and_calibration_resolution_id_r2_escreve_em_diretorio_proprio(
    tmp_path: Path,
) -> None:
    bars_df = _synthetic_bars(close_time=[_DAY1_MS + 3_600_000])
    calibration = build_dollar_bars.DollarBarCalibration(
        symbol="BTCUSDT",
        resolution_id="R2",
        threshold_usdt=1_000_000.0,
        calibration_scope="validation",
        calibration_window_start="2024-01-01",
        calibration_window_end="2024-01-02",
        n_trades=1_000,
        calibrated_at="2024-01-01T00:00:00+00:00",
    )

    written = build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df, calibration, dest_root=tmp_path
    )

    symbol_dir = tmp_path / "dollar_bars_r2" / "BTCUSDT"
    assert written["2024-01-01"] == symbol_dir / "2024-01-01.parquet"
    assert (symbol_dir / "2024-01-01.parquet").exists()
    # confirma que NÃO vazou pro diretório de R1 -- resoluções diferentes
    # nunca compartilham diretório, senão barras de thresholds diferentes
    # se misturariam silenciosamente na mesma leitura
    assert not (tmp_path / "dollar_bars_r1" / "BTCUSDT").exists()


def test_build_dollar_bars_for_window(monkeypatch: pytest.MonkeyPatch) -> None:
    # value = price*quantity = 50 por trade; cumsum=[50,100,150,200];
    # threshold=100 -> bar_id=[0,1,1,2] -> 3 barras (mesma matemática de
    # test_data_bars.py::test_dollar_bars_particao_bate_com_calculo_manual)
    monkeypatch.setattr(
        lake, "query_agg_trades", lambda *a, **k: _trades(4, price=10.0, quantity=5.0)
    )
    out = build_dollar_bars.build_dollar_bars_for_window(
        "BTCUSDT", "2024-01-01", "2024-01-01", threshold_usdt=100.0
    )
    assert out.height == 3
    assert out["count"].to_list() == [1, 2, 1]


# ============================================================================
# lake.query_dollar_bars -- round-trip contra o writer novo (síntetico)
# ============================================================================


def test_query_dollar_bars_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data_paths, "CAPACITY_DIR", tmp_path)

    bars_df = _synthetic_bars(
        close_time=[_DAY1_MS + 3_600_000, _DAY1_MS + _DAY_MS + 3_600_000]
    )
    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df, _calibration(), dest_root=tmp_path
    )

    out = lake.query_dollar_bars("BTCUSDT", "2024-01-01", "2024-01-02")

    assert out.height == 2
    assert out["close_time"].is_sorted()
    assert sorted(out["quote_volume"].to_list()) == sorted(
        bars_df["quote_volume"].to_list()
    )


def test_query_dollar_bars_range_fora_de_cobertura_retorna_vazio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data_paths, "CAPACITY_DIR", tmp_path)
    bars_df = _synthetic_bars(close_time=[_DAY1_MS + 3_600_000])
    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df, _calibration(), dest_root=tmp_path
    )
    out = lake.query_dollar_bars("BTCUSDT", "1900-01-01", "1900-01-02")
    assert out.height == 0


def test_query_dollar_bars_resolution_id_r2_le_diretorio_proprio_nao_r1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`resolution_id` default `"R1"` preserva bit-exato todo caller
    existente (testes acima, sem o argumento) -- este trava que passar
    `"R2"` explicitamente lê de `dollar_bars_r2/`, não `dollar_bars_r1/`,
    mesmo com as duas resoluções escritas no mesmo `tmp_path`."""
    monkeypatch.setattr(data_paths, "CAPACITY_DIR", tmp_path)

    r1_bars = _synthetic_bars(close_time=[_DAY1_MS + 3_600_000])
    build_dollar_bars.write_dollar_bars_and_calibration(
        r1_bars, _calibration(), dest_root=tmp_path
    )
    r2_bars = _synthetic_bars(
        close_time=[_DAY1_MS + 3_600_000, _DAY1_MS + _DAY_MS + 3_600_000]
    )
    r2_calibration = build_dollar_bars.DollarBarCalibration(
        symbol="BTCUSDT",
        resolution_id="R2",
        threshold_usdt=1_000_000.0,
        calibration_scope="validation",
        calibration_window_start="2024-01-01",
        calibration_window_end="2024-01-02",
        n_trades=1_000,
        calibrated_at="2024-01-01T00:00:00+00:00",
    )
    build_dollar_bars.write_dollar_bars_and_calibration(
        r2_bars, r2_calibration, dest_root=tmp_path
    )

    out_r1 = lake.query_dollar_bars("BTCUSDT", "2024-01-01", "2024-01-02")
    out_r2 = lake.query_dollar_bars(
        "BTCUSDT", "2024-01-01", "2024-01-02", resolution_id="R2"
    )
    assert out_r1.height == 1
    assert out_r2.height == 2


# ============================================================================
# Integração real (mesmo padrão de skip-guard de
# test_trades_dependent_bars_btcusdt_sobre_dado_real_janela_curta em
# tests/unit/test_analysis_m2_worker.py) -- prova FIAÇÃO ponta a ponta
# (calibrar -> construir -> escrever -> ler -> alimentar build_t1_features),
# NÃO prova validade estatística. AG-043 continua pendente.
# ============================================================================


@pytest.mark.integration
@pytest.mark.slow
def test_build_dollar_bars_fiacao_e2e_btcusdt_janela_curta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prova que a fiação `calibrate_dollar_threshold_for_validation` ->
    `build_dollar_bars_for_window` -> `write_dollar_bars_and_calibration`
    (`tmp_path`, nunca `data/capacity/` real) -> `lake.query_dollar_bars`
    -> `features.build.build_t1_features(..., bar_source="dollar_r1")`
    RODA SEM EXCEÇÃO sobre uma janela real pequena de BTCUSDT.

    **Isto prova fiação (não crasha), NÃO prova validade estatística --
    AG-043 (sqrt(window) em support.realized_vol, gap overnight do
    Yang-Zhang, defasagem do asof-join OI/funding) continua pendente.**

    `lake.capacity_symbol_dir` (não `_paths.CAPACITY_DIR` inteiro) é
    monkeypatchado com um wrapper que só redireciona `source=
    "dollar_bars_r1"` pra `tmp_path` -- `agg_trades`/`klines_1m`/`funding`/
    `metrics` continuam lidos do backfill REAL (`data/capacity/`), porque
    `build_t1_features` precisa deles de verdade pra este ser um teste de
    integração honesto, não só do particionamento sintético (já coberto
    pelos testes acima)."""
    from src.data._paths import CAPACITY_DIR
    from src.data._paths import capacity_symbol_dir as _real_capacity_symbol_dir

    symbol = "BTCUSDT"
    start, end = "2026-07-01", "2026-07-03"
    if not (CAPACITY_DIR / "agg_trades" / symbol / f"{start}.parquet").exists():
        pytest.skip(f"backfill local de agg_trades/{symbol}/{start} ausente")
    if not (CAPACITY_DIR / "klines_1m" / symbol / f"{start}.parquet").exists():
        pytest.skip(f"backfill local de klines_1m/{symbol}/{start} ausente")

    def _fake_capacity_symbol_dir(source: str, symbol_: str = "BTCUSDT") -> Path:
        if source == "dollar_bars_r1":
            return tmp_path / source / symbol_
        return _real_capacity_symbol_dir(source, symbol_)

    # `lake.capacity_symbol_dir` não é re-exportado explicitamente (mypy
    # strict recusa `lake.capacity_symbol_dir` como attr-defined) -- o alvo
    # de `monkeypatch.setattr` é uma string, não uma expressão de atributo,
    # então isso não esbarra na mesma checagem.
    monkeypatch.setattr(lake, "capacity_symbol_dir", _fake_capacity_symbol_dir)

    calibration = build_dollar_bars.calibrate_dollar_threshold_for_validation(
        symbol, start, end
    )
    assert calibration.threshold_usdt > 0
    assert calibration.calibration_scope == "validation"
    assert calibration.max_leftover_trades is not None and calibration.max_leftover_trades > 0

    bars_df = build_dollar_bars.build_dollar_bars_for_window(
        symbol,
        start,
        end,
        threshold_usdt=calibration.threshold_usdt,
        max_leftover_trades=calibration.max_leftover_trades,
    )
    assert bars_df.height > 0, "nenhuma barra fechada na janela de 3 dias"

    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df, calibration, dest_root=tmp_path
    )

    read_back = lake.query_dollar_bars(symbol, start, end)
    assert read_back.height == bars_df.height

    features_df = features_build.build_t1_features(
        symbol, start, end, bar_source="dollar_r1"
    )
    assert features_df.height > 0
    for col in features_build.T1_FEATURE_IDS:
        assert col in features_df.columns
