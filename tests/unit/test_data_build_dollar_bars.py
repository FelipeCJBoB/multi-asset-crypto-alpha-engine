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

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import orjson
import polars as pl
import pytest

from src.data import _paths as data_paths
from src.data import bars as bars_module
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
# WalkforwardCalibrationIdentity -- AG-124 (2026-08-21)
# ============================================================================


def _wf_identity(**overrides: object) -> build_dollar_bars.WalkforwardCalibrationIdentity:
    defaults: dict[str, object] = {
        "symbol": "BTCUSDT",
        "resolution_id": "R1",
        "trailing_window_days": 30,
        "cadence_days": 7,
    }
    defaults.update(overrides)
    return build_dollar_bars.WalkforwardCalibrationIdentity(**defaults)  # type: ignore[arg-type]


def test_walkforward_calibration_identity_scope_e_walkforward_causal_nunca_validation() -> None:
    identity = _wf_identity()
    assert identity.calibration_scope == build_dollar_bars.CALIBRATION_SCOPE_WALKFORWARD_CAUSAL
    assert identity.calibration_scope != build_dollar_bars.CALIBRATION_SCOPE_VALIDATION


def test_walkforward_calibration_identity_config_hash_deterministico() -> None:
    assert _wf_identity().config_hash == _wf_identity().config_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "ETHUSDT"),
        ("resolution_id", "R2"),
        ("trailing_window_days", 60),
        ("cadence_days", 14),
    ],
)
def test_walkforward_calibration_identity_config_hash_muda_se_campo_mudar(
    field: str, value: object
) -> None:
    base = _wf_identity()
    changed = _wf_identity(**{field: value})
    assert base.config_hash != changed.config_hash


def test_walkforward_calibration_identity_config_hash_e_string_hex_16() -> None:
    config_hash = _wf_identity().config_hash
    assert isinstance(config_hash, str)
    assert len(config_hash) == 16
    # levanta ValueError se não for hex -- não pytest.raises, é o próprio teste
    int(config_hash, 16)


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


def test_write_dollar_bars_and_calibration_aceita_threshold_divergente_sem_overwrite(
    tmp_path: Path,
) -> None:
    """AG-124 (2026-08-21) -- a guarda que rejeitava um 2º threshold
    divergente no mesmo diretório sem `overwrite=True` foi removida
    (`build_dollar_bars_walkforward` PRECISA escrever thresholds
    diferentes, um por período, no mesmo diretório de símbolo, sem
    `overwrite=True` -- ver docstring da função). `_calibration.json` fica
    com o payload da ÚLTIMA chamada (nenhuma checagem de mismatch mais);
    os dias de cada rodada continuam presentes no diretório (só
    `overwrite=True` apaga `*.parquet` antigos, ver teste de overwrite
    abaixo -- comportamento inalterado)."""
    bars_df_1 = _synthetic_bars(close_time=[_DAY1_MS + 3_600_000])
    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df_1, _calibration(threshold_usdt=1_000_000.0), dest_root=tmp_path
    )

    bars_df_2 = _synthetic_bars(close_time=[_DAY1_MS + _DAY_MS + 3_600_000])
    # não levanta -- ao contrário do comportamento pré-AG-124
    build_dollar_bars.write_dollar_bars_and_calibration(
        bars_df_2, _calibration(threshold_usdt=2_000_000.0), dest_root=tmp_path
    )

    symbol_dir = tmp_path / "dollar_bars_r1" / "BTCUSDT"
    # ambos os dias sobrevivem -- sem overwrite=True, nada é apagado entre
    # chamadas (só _calibration.json é sobrescrito, ver abaixo)
    assert sorted(p.name for p in symbol_dir.glob("*.parquet")) == [
        "2024-01-01.parquet",
        "2024-01-02.parquet",
    ]
    payload = orjson.loads((symbol_dir / "_calibration.json").read_bytes())
    assert payload["threshold_usdt"] == pytest.approx(2_000_000.0)  # da última chamada


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
# build_dollar_bars_walkforward (AG-124, Camada 1) -- recalibração rolante
# CAUSAL, dado 100% sintético (lake.query_bars/query_agg_trades mockados na
# fronteira). Calendário sintético usado por todos os testes abaixo:
#   P0 = 2024-01-01..2024-01-30 (30 dias) -- cold-start, DESCARTADO
#   P1 = 2024-01-31..2024-02-29 (30 dias) -- calibrado sobre P0 (rate 1000/dia)
#   P2 = 2024-03-01..2024-03-30 (30 dias) -- calibrado sobre P1 (rate 2000/dia)
# `trailing_window_days=cadence_days=30` faz a janela de calibração de CADA
# período bater EXATAMENTE com o range calendário do período anterior --
# escolha deliberada pra tornar o threshold_usdt esperado computável à mão
# (rate uniforme dentro de cada bucket / mesma contagem de dias na baseline
# sintética -> threshold_usdt == rate do bucket, sem aritmética de ponto
# flutuante escondida).
# ============================================================================

_WF_SYMBOL = "BTCUSDT"
_WF_START = "2024-01-01"
_WF_START_DATE = date(2024, 1, 1)
_WF_END = "2024-03-30"
_WF_TRAILING_DAYS = 30
_WF_CADENCE_DAYS = 30


def _to_date(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


_EPOCH = date(1970, 1, 1)
_DAY_MS_WF = 86_400_000


def _noon_epoch_ms(d: date) -> int:
    """Epoch ms de meio-dia UTC de `d` -- usado como `transact_time`
    sintético. Achado ao rodar a suíte pela 1ª vez: usar `range(n_days)`
    como `transact_time` (0, 1, 2, ...) faz TODO trade sintético cair no
    mesmo dia calendário (1970-01-01, perto do epoch) quando `_aggregate_
    bars`/`_split_bars_by_day` convertem `close_time` pra data -- períodos
    diferentes then colidem no MESMO arquivo `.parquet` e um sobrescreve o
    outro silenciosamente (exatamente o tipo de bug que este teste deveria
    pegar em PRODUÇÃO, não esconder no MOCK). `transact_time` precisa ser
    epoch ms REAL da data calendário sintética, não um índice sequencial."""
    return (d - _EPOCH).days * _DAY_MS_WF + _DAY_MS_WF // 2


def _rate_for_date(d: date, rates: tuple[tuple[date, date, float], ...]) -> float:
    for lo, hi, rate in rates:
        if lo <= d <= hi:
            return rate
    raise AssertionError(
        f"data sintética {d} fora de todo bucket de _rate_for_date -- calendário "
        "do teste (P0/P1/P2) não cobre essa data, ajuste os buckets"
    )


_WF_TRADES_EMPTY_SCHEMA: dict[str, pl.DataType] = {
    "transact_time": pl.Int64(),
    "price": pl.Float64(),
    "quantity": pl.Float64(),
    "is_buyer_maker": pl.Boolean(),
}


def _walkforward_mocks(
    rates: tuple[tuple[date, date, float], ...],
    *,
    history_start: date | None = None,
) -> tuple[Callable[..., pl.DataFrame], Callable[..., pl.DataFrame]]:
    """Constrói o par de mocks (`lake.query_bars`, `lake.query_agg_trades`)
    usado por `calibrate_dollar_threshold_for_validation` (via
    `_chunked_scan.query_baseline`/`scan_trades_totals`) E por
    `build_dollar_bars_for_window` (via `lake.query_agg_trades` direto) --
    determinístico e SÓ função de `(start, end)`, nunca de estado externo
    mutável, então qualquer chamada com o MESMO range sempre devolve o MESMO
    resultado, não importa quantas vezes/de que ordem é chamada -- é essa
    propriedade que torna o teste de prefix-invariance (`test_..._prefix_
    invariance...`) uma prova de verdade sobre a IMPLEMENTAÇÃO (que janela
    ela de fato pergunta pra cada período), não um artefato do mock.

    1 trade/1 linha de baseline por dia calendário -- `total_dollar` de
    `scan_trades_totals` bate EXATO com `rate * n_dias` (soma robusta a
    qualquer sub-chunking interno de `bars_streaming_chunk_days`, já que
    soma dia a dia); `n_bars` (baseline.height) também bate `n_dias` --
    junto, fazem `threshold_usdt = total_dollar / n_bars` colapsar pro
    `rate` do bucket quando o bucket é uniforme dentro da janela (P0/P1/P2
    cada um 100% dentro de 1 bucket só, por desenho).

    `history_start` (AG-124/item 15, 2026-08-21) -- quando informado,
    simula o INÍCIO real de histórico do símbolo: qualquer `start < history_
    start` devolve DataFrame VAZIO (zero trades/zero linhas de baseline),
    mesma superfície de `lake.query_agg_trades`/`query_bars` reais quando
    não há dado antes do listing do símbolo -- é o que faz `calibrate_
    dollar_threshold_for_validation` levantar `ValueError` (`totals.n_ticks
    == 0`) pra uma janela de calibração genuinamente sem histórico, em vez
    de um `AssertionError` de `_rate_for_date` (que só cobre os buckets
    definidos em `rates`, não é uma fronteira de história de verdade).
    `None` (default) preserva o comportamento anterior -- sempre devolve
    dado sintético, nenhuma fronteira de história (usado pelos testes que
    não tocam a janela de lead-in)."""

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
        if history_start is not None and _to_date(start) < history_start:
            return pl.DataFrame({"close": [], "close_time": []}).cast(
                {"close": pl.Float64, "close_time": pl.Int64}
            )
        n_days = (_to_date(end) - _to_date(start)).days + 1
        return pl.DataFrame({"close": [1.0] * n_days, "close_time": list(range(n_days))})

    def _fake_query_agg_trades(
        symbol: str, start: object, end: object, **_: object
    ) -> pl.DataFrame:
        start_d, end_d = _to_date(start), _to_date(end)
        if history_start is not None and start_d < history_start:
            return pl.DataFrame(schema=_WF_TRADES_EMPTY_SCHEMA)
        n_days = (end_d - start_d).days + 1
        days = [start_d + timedelta(days=i) for i in range(n_days)]
        prices = [_rate_for_date(d, rates) for d in days]
        return pl.DataFrame(
            {
                "transact_time": [_noon_epoch_ms(d) for d in days],
                "price": prices,
                "quantity": [1.0] * n_days,  # price*quantity == rate do dia, exato
                "is_buyer_maker": [False] * n_days,
            },
            schema=_WF_TRADES_EMPTY_SCHEMA,
        )

    return _fake_query_bars, _fake_query_agg_trades


_WF_RATES_BASE: tuple[tuple[date, date, float], ...] = (
    (date(2024, 1, 1), date(2024, 1, 30), 1000.0),  # P0
    (date(2024, 1, 31), date(2024, 2, 29), 2000.0),  # P1
    (date(2024, 3, 1), date(2024, 3, 30), 4000.0),  # P2
)


def test_build_dollar_bars_walkforward_cold_start_1o_periodo_nao_quebra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(c) cold-start do 1º período (P0) não levanta exceção -- é
    descartado como warmup, contabilizado, não construído/escrito.
    `history_start=_WF_START` -- simula que NÃO há trade algum antes do
    início do range pedido (início real de histórico do símbolo), então
    mesmo com o lead-in (AG-124/item 15) tentando calibrar P0, não há
    dado disponível e ele continua sendo descartado -- este teste cobre
    o caminho onde o lead-in genuinamente não tem o que recuperar; ver
    `test_build_dollar_bars_walkforward_lead_in_recupera_1o_periodo_
    quando_ha_historico_antes` para o caminho onde ele recupera."""
    fake_bars, fake_trades = _walkforward_mocks(_WF_RATES_BASE, history_start=_WF_START_DATE)
    monkeypatch.setattr(lake, "query_bars", fake_bars)
    monkeypatch.setattr(lake, "query_agg_trades", fake_trades)

    stats = build_dollar_bars.build_dollar_bars_walkforward(
        _WF_SYMBOL,
        _WF_START,
        _WF_END,
        resolution_id="R1",
        trailing_window_days=_WF_TRAILING_DAYS,
        cadence_days=_WF_CADENCE_DAYS,
        dest_root=tmp_path,
    )

    assert stats.n_periods == 3
    assert stats.n_cold_start_dropped == 1
    assert stats.n_periods_written == 2
    p0 = stats.periods[0]
    assert p0.is_cold_start is True
    assert p0.app_start == "2024-01-01"
    assert p0.app_end == "2024-01-30"
    assert p0.threshold_usdt is None
    assert p0.n_bars == 0
    assert p0.written is None
    # nada escrito pro RANGE de P0 (2024-01-01..2024-01-30) -- 2024-01-31
    # É esperado (é o 1º dia de P1, período real, não de P0).
    symbol_dir = tmp_path / "dollar_bars_r1" / _WF_SYMBOL
    written_days = sorted(p.stem for p in symbol_dir.glob("*.parquet"))
    p0_days = {(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(30)}
    assert not (p0_days & set(written_days))
    assert "2024-01-31" in written_days  # 1º dia de P1 -- confirma que não sumiu por engano


def test_build_dollar_bars_walkforward_lead_in_recupera_1o_periodo_quando_ha_historico_antes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AG-124/item 15 (lead-in buffer, 2026-08-21) -- quando HÁ trade real
    disponível antes de `start` (histórico genuíno do símbolo, não fora do
    domínio), o 1º período deixa de ser descartado incondicionalmente. Só
    a LEITURA de calibração olha antes de `start` -- a escrita de barras
    continua começando em `start` (bars de antes de `start` nunca são
    construídas/escritas por esta chamada, só usadas pra calibrar)."""
    lead_in_rate = 500.0
    rates_with_lead_in: tuple[tuple[date, date, float], ...] = (
        (date(2023, 12, 2), date(2023, 12, 31), lead_in_rate),  # cobre a janela de calib de P0
        *_WF_RATES_BASE,
    )
    fake_bars, fake_trades = _walkforward_mocks(
        rates_with_lead_in, history_start=date(2023, 12, 2)
    )
    monkeypatch.setattr(lake, "query_bars", fake_bars)
    monkeypatch.setattr(lake, "query_agg_trades", fake_trades)

    stats = build_dollar_bars.build_dollar_bars_walkforward(
        _WF_SYMBOL,
        _WF_START,
        _WF_END,
        resolution_id="R1",
        trailing_window_days=_WF_TRAILING_DAYS,
        cadence_days=_WF_CADENCE_DAYS,
        dest_root=tmp_path,
    )

    assert stats.n_periods == 3
    assert stats.n_cold_start_dropped == 0  # NADA descartado -- lead-in recuperou P0
    assert stats.n_periods_written == 3
    p0 = stats.periods[0]
    assert p0.is_cold_start is False
    assert p0.app_start == "2024-01-01"  # escrita continua começando em start, não antes
    assert p0.threshold_usdt == pytest.approx(lead_in_rate)
    assert p0.n_bars > 0
    assert p0.written is not None
    for name, path in p0.written.items():
        if name == "calibration":
            continue
        day_df = pl.read_parquet(path)
        assert day_df["threshold_quote"].to_list() == pytest.approx(
            [lead_in_rate] * day_df.height
        )
        # dia escrito é sempre >= start -- lead-in nunca produz barra ANTES do range pedido
        assert name >= _WF_START


def test_build_dollar_bars_walkforward_finish_chamado_1x_por_rodada_nao_por_periodo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AG-124/item 14 -- `threshold_bars_finish` (que trunca/fecha o
    leftover em aberto como barra parcial) só roda 1x pra TODA a rodada
    (no último período), não 1x por período -- é essa mudança que reduz
    o nº de barras subdimensionadas de ~1/período pra ~1/rodada inteira."""
    finish_calls = 0
    original_finish = bars_module.threshold_bars_finish

    def _counting_finish(carry: object) -> pl.DataFrame:
        nonlocal finish_calls
        finish_calls += 1
        return original_finish(carry)  # type: ignore[arg-type]

    fake_bars, fake_trades = _walkforward_mocks(_WF_RATES_BASE, history_start=_WF_START_DATE)
    monkeypatch.setattr(lake, "query_bars", fake_bars)
    monkeypatch.setattr(lake, "query_agg_trades", fake_trades)
    # `build_dollar_bars.py` faz `from . import bars` -- `bars_module` (import
    # direto abaixo) é o MESMO objeto de módulo em memória, então patchar
    # aqui tem efeito idêntico a patchar via `build_dollar_bars.bars`, sem
    # acessar o atributo implícito (mypy strict rejeita `build_dollar_bars.
    # bars` -- "does not explicitly export attribute").
    monkeypatch.setattr(bars_module, "threshold_bars_finish", _counting_finish)

    stats = build_dollar_bars.build_dollar_bars_walkforward(
        _WF_SYMBOL,
        _WF_START,
        _WF_END,
        resolution_id="R1",
        trailing_window_days=_WF_TRAILING_DAYS,
        cadence_days=_WF_CADENCE_DAYS,
        dest_root=tmp_path,
    )

    assert stats.n_periods_written == 2  # P1, P2 (P0 segue cold-start sem lead-in)
    assert finish_calls == 1  # não 2 -- só o ÚLTIMO período fecha o stream


def test_build_dollar_bars_walkforward_cada_barra_carrega_threshold_quote_certo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) cada barra escrita carrega o `threshold_quote` do período em que
    foi construída -- P1 calibrado sobre P0 (rate 1000/dia uniforme,
    30 dias, baseline 30 linhas) -> threshold_usdt esperado == 1000.0; P2
    calibrado sobre P1 (rate 2000/dia) -> esperado == 2000.0."""
    fake_bars, fake_trades = _walkforward_mocks(_WF_RATES_BASE, history_start=_WF_START_DATE)
    monkeypatch.setattr(lake, "query_bars", fake_bars)
    monkeypatch.setattr(lake, "query_agg_trades", fake_trades)

    stats = build_dollar_bars.build_dollar_bars_walkforward(
        _WF_SYMBOL,
        _WF_START,
        _WF_END,
        resolution_id="R1",
        trailing_window_days=_WF_TRAILING_DAYS,
        cadence_days=_WF_CADENCE_DAYS,
        dest_root=tmp_path,
    )

    p1, p2 = stats.periods[1], stats.periods[2]
    assert p1.is_cold_start is False
    assert p1.threshold_usdt == pytest.approx(1000.0)
    assert p2.threshold_usdt == pytest.approx(2000.0)
    assert p1.n_bars > 0
    assert p2.n_bars > 0

    # Lê os parquets diretamente pelos caminhos retornados em
    # WalkforwardPeriodResult.written (já apontam pra tmp_path) -- mais
    # direto que passar por lake.query_dollar_bars (que exigiria também
    # monkeypatchar data_paths.CAPACITY_DIR pra não ler do disco real).
    assert p1.written is not None
    for name, path in p1.written.items():
        if name == "calibration":
            continue
        day_df = pl.read_parquet(path)
        assert day_df.height > 0
        assert (day_df["threshold_quote"] == 1000.0).all()

    assert p2.written is not None
    for name, path in p2.written.items():
        if name == "calibration":
            continue
        day_df = pl.read_parquet(path)
        assert day_df.height > 0
        assert (day_df["threshold_quote"] == 2000.0).all()


def test_build_dollar_bars_walkforward_prefix_invariance_periodo_posterior_nao_afeta_anterior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) mudar o volume de P2 (o período MAIS RECENTE, aplicado por
    último) não muda o threshold_usdt calibrado pra P1 nem pra P0 -- prova
    que a calibração de cada período é estritamente causal (só olha pra
    `[app_start - trailing_window_days, app_start)`), nunca pra frente.
    Roda a rodada inteira 2x, com o único bucket de rate divergente entre
    as duas rodadas sendo o de P2 (2024-03-01..2024-03-30) -- P0/P1 usam a
    MESMA fonte de dado nas duas rodadas."""
    rates_run_a = _WF_RATES_BASE
    rates_run_b = (
        _WF_RATES_BASE[0],  # P0 -- idêntico
        _WF_RATES_BASE[1],  # P1 -- idêntico
        (date(2024, 3, 1), date(2024, 3, 30), 999_999.0),  # P2 -- MUITO diferente
    )

    def _run(
        rates: tuple[tuple[date, date, float], ...], dest_root: Path
    ) -> build_dollar_bars.WalkforwardBarsStats:
        fake_bars, fake_trades = _walkforward_mocks(rates, history_start=_WF_START_DATE)
        monkeypatch.setattr(lake, "query_bars", fake_bars)
        monkeypatch.setattr(lake, "query_agg_trades", fake_trades)
        return build_dollar_bars.build_dollar_bars_walkforward(
            _WF_SYMBOL,
            _WF_START,
            _WF_END,
            resolution_id="R1",
            trailing_window_days=_WF_TRAILING_DAYS,
            cadence_days=_WF_CADENCE_DAYS,
            dest_root=dest_root,
        )

    stats_a = _run(rates_run_a, tmp_path / "run_a")
    stats_b = _run(rates_run_b, tmp_path / "run_b")

    # P1 (calibrado sobre P0, nunca vê dado de P2) -- IDÊNTICO nas 2 rodadas
    assert stats_a.periods[1].threshold_usdt == pytest.approx(stats_b.periods[1].threshold_usdt)
    assert stats_a.periods[1].threshold_usdt == pytest.approx(1000.0)
    # P2 (calibrado sobre P1, também nunca vê o PRÓPRIO dado -- só vê P1,
    # que é idêntico nas 2 rodadas) -- também IDÊNTICO, mesmo com P2 tendo
    # um rate MUITO diferente (4000 vs 999999) entre as rodadas
    assert stats_a.periods[2].threshold_usdt == pytest.approx(stats_b.periods[2].threshold_usdt)
    assert stats_a.periods[2].threshold_usdt == pytest.approx(2000.0)
    # a mudança SÓ aparece onde é esperada: no CONTEÚDO das barras de P2
    # (mesmo threshold_usdt=2000.0 nas 2 rodadas, mas quote_volume por
    # barra é MUITO maior em run_b -- rate/dia 4000 vs 999999, 1 trade/dia
    # -- n_bars não diferencia aqui porque só 1 trade/dia satura em no
    # máximo 1 linha de bar por dia independente da magnitude do rate)
    assert stats_a.periods[2].written is not None
    assert stats_b.periods[2].written is not None
    quote_volume_a = pl.concat(
        [
            pl.read_parquet(path)
            for name, path in stats_a.periods[2].written.items()
            if name != "calibration"
        ]
    )["quote_volume"].sum()
    quote_volume_b = pl.concat(
        [
            pl.read_parquet(path)
            for name, path in stats_b.periods[2].written.items()
            if name != "calibration"
        ]
    )["quote_volume"].sum()
    assert quote_volume_b > quote_volume_a


def test_build_dollar_bars_walkforward_parametros_obrigatorios_rejeita_invalidos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B23 -- `trailing_window_days`/`cadence_days` não têm default; valor
    <= 0 é rejeitado explicitamente (fail-loud), não silenciosamente
    tratado como 'sem recalibração'."""
    fake_bars, fake_trades = _walkforward_mocks(_WF_RATES_BASE, history_start=_WF_START_DATE)
    monkeypatch.setattr(lake, "query_bars", fake_bars)
    monkeypatch.setattr(lake, "query_agg_trades", fake_trades)

    with pytest.raises(ValueError, match="trailing_window_days"):
        build_dollar_bars.build_dollar_bars_walkforward(
            _WF_SYMBOL,
            _WF_START,
            _WF_END,
            resolution_id="R1",
            trailing_window_days=0,
            cadence_days=_WF_CADENCE_DAYS,
            dest_root=tmp_path,
        )
    with pytest.raises(ValueError, match="cadence_days"):
        build_dollar_bars.build_dollar_bars_walkforward(
            _WF_SYMBOL,
            _WF_START,
            _WF_END,
            resolution_id="R1",
            trailing_window_days=_WF_TRAILING_DAYS,
            cadence_days=-1,
            dest_root=tmp_path,
        )


def test_build_dollar_bars_walkforward_calibration_json_registra_identidade_do_algoritmo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_calibration.json` sob modo walk-forward registra a IDENTIDADE do
    algoritmo (janela causal, cadência, resolution_id) -- NÃO um
    threshold_usdt escalar (esse não existe mais como conceito de
    diretório, ver docstring de `WalkforwardCalibrationIdentity`)."""
    fake_bars, fake_trades = _walkforward_mocks(_WF_RATES_BASE, history_start=_WF_START_DATE)
    monkeypatch.setattr(lake, "query_bars", fake_bars)
    monkeypatch.setattr(lake, "query_agg_trades", fake_trades)

    stats = build_dollar_bars.build_dollar_bars_walkforward(
        _WF_SYMBOL,
        _WF_START,
        _WF_END,
        resolution_id="R1",
        trailing_window_days=_WF_TRAILING_DAYS,
        cadence_days=_WF_CADENCE_DAYS,
        dest_root=tmp_path,
    )

    symbol_dir = tmp_path / "dollar_bars_r1" / _WF_SYMBOL
    payload = orjson.loads((symbol_dir / "_calibration.json").read_bytes())
    assert "threshold_usdt" not in payload
    assert payload["trailing_window_days"] == _WF_TRAILING_DAYS
    assert payload["cadence_days"] == _WF_CADENCE_DAYS
    assert payload["resolution_id"] == "R1"
    assert payload["calibration_scope"] == build_dollar_bars.CALIBRATION_SCOPE_WALKFORWARD_CAUSAL
    assert isinstance(stats.calibration_identity.config_hash, str)
    assert len(stats.calibration_identity.config_hash) == 16


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


# ============================================================================
# _parse_cli_args -- wiring do modo causal no CLI (AG-138, 2026-08-23). O
# gap real era o operador rodando `python -m src.data.build_dollar_bars` (o
# comando mais óbvio) sem nenhum aviso de que reproduz o vazamento de
# 18,18x medido em AG-124 -- estes testes cobrem só o parsing/validação de
# argv, não IO real (mesma fronteira dos testes síncronos acima do arquivo).
# ============================================================================


def test_parse_cli_args_default_mode_e_single_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_dollar_bars.py",
            "--symbol", "BTCUSDT",
            "--start", "2024-01-01",
            "--end", "2024-01-02",
        ],
    )
    args = build_dollar_bars._parse_cli_args()
    assert args.mode == "single_window"
    assert args.trailing_window_days is None
    assert args.cadence_days is None


def test_parse_cli_args_walkforward_sem_trailing_window_days_levanta_systemexit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_dollar_bars.py",
            "--symbol", "BTCUSDT",
            "--start", "2024-01-01",
            "--end", "2024-01-02",
            "--mode", "walkforward",
            "--cadence-days", "7",
        ],
    )
    with pytest.raises(SystemExit):
        build_dollar_bars._parse_cli_args()


def test_parse_cli_args_walkforward_sem_cadence_days_levanta_systemexit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_dollar_bars.py",
            "--symbol", "BTCUSDT",
            "--start", "2024-01-01",
            "--end", "2024-01-02",
            "--mode", "walkforward",
            "--trailing-window-days", "30",
        ],
    )
    with pytest.raises(SystemExit):
        build_dollar_bars._parse_cli_args()


def test_parse_cli_args_walkforward_com_ambos_parseia_corretamente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_dollar_bars.py",
            "--symbol", "BTCUSDT",
            "--start", "2024-01-01",
            "--end", "2024-01-02",
            "--mode", "walkforward",
            "--trailing-window-days", "30",
            "--cadence-days", "7",
        ],
    )
    args = build_dollar_bars._parse_cli_args()
    assert args.mode == "walkforward"
    assert args.trailing_window_days == 30
    assert args.cadence_days == 7
