"""Testes de `src/models/dataset.py` — `side_subset` (NOFILL fora, warmup
fora, §3.7). `build_modeling_frame`/`date_bounds` fazem IO real (Sprint
4/5/6) e são exercitados na integração de `test_models_alpha.py` (skip se
`labels/v1/labels.parquet` ausente), não aqui — **exceto** os dois testes
na seção "F1 — R0 é 100% warmup" abaixo, que chamam `build_modeling_frame`
de propósito: são o teste de regressão da investigação F1 (CLAUDE.md desta
rodada), e o ponto inteiro é rodar sobre o frame real, não uma amostra
sintética. Custo medido: ~14s por chamada (Sprint 8), aceitável para uma
suíte que já roda ~100s no total."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from src.features import build as features_build
from src.features.build import T1_FEATURE_IDS
from src.labels.triple_barrier import ConfigHashMismatchError, LabelConfig
from src.models import dataset as ds
from src.models._constants import load_constant
from src.models._paths import PREDICTIONS_OUTPUT_DIR
from src.models.pipeline import MODEL_ID_CAMADA1
from src.regime import build as regime_build
from src.regime import build_hmm
from src.validation import cpcv
from src.validation._paths import labels_symbol_tf_dir


def _noop_verify_config_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """As rotas testadas abaixo (roteamento symbol/version/tf/resolution_id
    até `load_labels_v1`) usam `_one_row_labels`, que não tem coluna
    `config_hash` real -- não é o que esses testes existem pra provar (ver
    `AG-140` abaixo pros testes dedicados de `verify_config_hash`)."""
    monkeypatch.setattr(ds, "verify_config_hash", lambda *a, **k: None)

# ============================================================================
# build_modeling_frame -- roteamento symbol/version/tf até load_labels_v1
# (achado 2026-08-13, §15.6 item 4): antes desta correção, `symbol` era
# aceito mas NUNCA chegava a `cpcv.load_labels_v1()`, que sempre carregava
# BTCUSDT por default -- features de um símbolo, labels de outro,
# silenciosamente. Mockado (não IO real) porque o objetivo aqui é provar o
# ROTEAMENTO do argumento, não a corretude do join em si (já coberta pelos
# testes de integração citados no docstring do módulo).
# ============================================================================


def _one_row_labels(t0: datetime) -> pl.DataFrame:
    return pl.DataFrame({"t0": [t0]}).with_columns(pl.col("t0").dt.replace_time_zone("UTC"))


def _one_row_bar_table(t0: datetime) -> pl.DataFrame:
    ms = int(t0.timestamp() * 1000)
    cols: dict[str, Any] = {"open_time": [ms], "close_time": [ms]}
    for fid in T1_FEATURE_IDS:
        cols[fid] = [0.0]
    return pl.DataFrame(cols)


def _one_row_bar_table_with(t0: datetime, extra_ids: tuple[str, ...]) -> pl.DataFrame:
    """`_one_row_bar_table` + colunas extras dummy — pro `join_cols` de
    `build_modeling_frame` (T1_FEATURE_IDS + extra_feature_ids) não
    quebrar com `ColumnNotFoundError` quando o teste passa
    `extra_feature_ids` não coberto pela fixture mínima."""
    base = _one_row_bar_table(t0)
    extra_cols = {fid: [0.0] for fid in extra_ids if fid not in base.columns}
    return base.with_columns(**{k: pl.lit(v[0]) for k, v in extra_cols.items()})


def _one_row_regime(t0: datetime) -> pl.DataFrame:
    return pl.DataFrame(
        {"t0": [t0], "regime": ["R1"], "tradeable": [True]}
    ).with_columns(pl.col("t0").dt.replace_time_zone("UTC"))


def test_build_modeling_frame_roteia_symbol_version_tf_ate_load_labels_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    calls: list[dict[str, Any]] = []

    def _fake_load_labels_v1(
        version: str = "v1",
        *,
        symbol: str = "BTCUSDT",
        tf: str = "15m",
        resolution_id: str | None = None,
    ) -> pl.DataFrame:
        calls.append(
            {"version": version, "symbol": symbol, "tf": tf, "resolution_id": resolution_id}
        )
        return _one_row_labels(t0)

    monkeypatch.setattr(cpcv, "load_labels_v1", _fake_load_labels_v1)
    monkeypatch.setattr(
        features_build,
        "build_t1_features",
        lambda symbol, start, end, **kwargs: _one_row_bar_table(t0),
    )
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end, **kwargs: _one_row_regime(t0)
    )
    _noop_verify_config_hash(monkeypatch)

    # tf="15m" (não "30m" como em versão anterior deste teste): achado de
    # auditoria (audit_engineering, 2026-08-17) mostrou que tf != "15m" sem
    # resolution_id produz frame incoerente (labels/CPCV honrariam tf, mas
    # features/regime ficariam presas em 15m) -- build_modeling_frame agora
    # rejeita isso explicitamente (ver teste dedicado abaixo). "15m" é
    # suficiente pra provar o roteamento de symbol/version/tf que este
    # teste existe pra proteger (achado AG-015 original).
    ds.build_modeling_frame(symbol="ETHUSDT", labels_version="v1", tf="15m")

    assert calls == [
        {"version": "v1", "symbol": "ETHUSDT", "tf": "15m", "resolution_id": None}
    ]


def test_build_modeling_frame_usa_regime_classifier_quantis_nao_hmm_k4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`AG-344` (handoff de `src/models/`, 2026-08-27) -- trava
    explicitamente qual regime engine `build_modeling_frame` de fato usa
    hoje: `classifier.QuantileRegimeClassifier` (via `regime_build.
    build_regimes`, `dataset.py:361`), NÃO `build_hmm.build_hmm_regimes`
    (HMM k=4) -- apesar do `CLAUDE.md` ter declarado HMM k=4 canônico de
    produção (decisão de wireear ou não continua em aberto, fora do
    escopo deste teste). Sem este teste, uma futura divergência entre
    código e documentação só seria pega por auditoria manual meses depois
    -- foi exatamente o que já aconteceu uma vez (corrigido no texto de
    `CLAUDE.md`/`PLANO_MESTRE_PRINCE2.md`, commit `d4c1d4e`, mas nunca
    travado por teste)."""
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    build_regimes_calls: list[str] = []

    def _fake_build_regimes(symbol: str, start: str, end: str, **kwargs: Any) -> pl.DataFrame:
        build_regimes_calls.append(symbol)
        return _one_row_regime(t0)

    def _hmm_nao_deveria_ser_chamado(*args: Any, **kwargs: Any) -> pl.DataFrame:
        raise AssertionError(
            "build_modeling_frame chamou build_hmm.build_hmm_regimes -- hoje o engine "
            "real é classifier.QuantileRegimeClassifier via regime_build.build_regimes "
            "(AG-344). Se isto disparou, o engine mudou de verdade -- revise este teste "
            "E a documentação (CLAUDE.md/PLANO_MESTRE_PRINCE2.md) juntos, não só um dos dois"
        )

    monkeypatch.setattr(cpcv, "load_labels_v1", lambda *a, **k: _one_row_labels(t0))
    monkeypatch.setattr(
        features_build,
        "build_t1_features",
        lambda symbol, start, end, **kwargs: _one_row_bar_table(t0),
    )
    monkeypatch.setattr(regime_build, "build_regimes", _fake_build_regimes)
    monkeypatch.setattr(build_hmm, "build_hmm_regimes", _hmm_nao_deveria_ser_chamado)
    _noop_verify_config_hash(monkeypatch)

    ds.build_modeling_frame()

    assert build_regimes_calls == ["BTCUSDT"]


def test_build_modeling_frame_default_bate_com_load_labels_v1_sem_argumentos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default (`symbol=SYMBOL_DEFAULT="BTCUSDT"`, `labels_version="v1"`,
    `tf="15m"`) precisa produzir a MESMA chamada que `load_labels_v1()`
    sem argumento nenhum -- bit-exato pra todo caller existente que não
    passa esses parâmetros."""
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    calls: list[dict[str, Any]] = []

    def _fake_load_labels_v1(
        version: str = "v1",
        *,
        symbol: str = "BTCUSDT",
        tf: str = "15m",
        resolution_id: str | None = None,
    ) -> pl.DataFrame:
        calls.append(
            {"version": version, "symbol": symbol, "tf": tf, "resolution_id": resolution_id}
        )
        return _one_row_labels(t0)

    monkeypatch.setattr(cpcv, "load_labels_v1", _fake_load_labels_v1)
    monkeypatch.setattr(
        features_build,
        "build_t1_features",
        lambda symbol, start, end, **kwargs: _one_row_bar_table(t0),
    )
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end, **kwargs: _one_row_regime(t0)
    )
    _noop_verify_config_hash(monkeypatch)

    ds.build_modeling_frame()

    assert calls == [
        {"version": "v1", "symbol": "BTCUSDT", "tf": "15m", "resolution_id": None}
    ]


# ============================================================================
# resolution_id/vol_estimator_id -- Fase 4 (2026-08-17, AG-036/065, achado
# G2/G4 da revisão project_assurance): peça de orquestração que faltava --
# um único parâmetro de grade, não bar_source/resolution_id independentes.
# ============================================================================


def test_build_modeling_frame_resolution_id_propaga_bar_source_e_vol_estimator_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resolution_id="R1"` propaga a MESMA grade pros três: `load_labels_v1`
    (via `resolution_id`), `build_t1_features`/`build_regimes` (via
    `bar_source="dollar_r1"` derivado) -- prova de fiação via captura de
    kwargs, não execução real (mesmo estilo dos dois testes acima)."""
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    load_labels_calls: list[dict[str, Any]] = []
    features_calls: list[dict[str, Any]] = []
    regime_calls: list[dict[str, Any]] = []

    def _fake_load_labels_v1(
        version: str = "v1",
        *,
        symbol: str = "BTCUSDT",
        tf: str = "15m",
        resolution_id: str | None = None,
    ) -> pl.DataFrame:
        load_labels_calls.append({"resolution_id": resolution_id})
        return _one_row_labels(t0)

    def _fake_build_t1_features(symbol: str, start: str, end: str, **kwargs: Any) -> pl.DataFrame:
        features_calls.append(kwargs)
        return _one_row_bar_table(t0)

    def _fake_build_regimes(symbol: str, start: str, end: str, **kwargs: Any) -> pl.DataFrame:
        regime_calls.append(kwargs)
        return _one_row_regime(t0)

    monkeypatch.setattr(cpcv, "load_labels_v1", _fake_load_labels_v1)
    monkeypatch.setattr(features_build, "build_t1_features", _fake_build_t1_features)
    monkeypatch.setattr(regime_build, "build_regimes", _fake_build_regimes)
    _noop_verify_config_hash(monkeypatch)

    ds.build_modeling_frame(
        symbol="BTCUSDT", resolution_id="R1", vol_estimator_id="parkinson_w20"
    )

    assert load_labels_calls == [{"resolution_id": "R1"}]
    # load_taker_imbalance_1m/load_futures_positioning (achado real,
    # audit_engineering, 2026-08-24, **[CORRIGIDO 2026-08-27, AG-365]**):
    # build_modeling_frame ativa os dois quando a UNIAO de T1_FEATURE_IDS
    # com extra_feature_ids pede D07f/futures-positioning -- aqui extra_
    # feature_ids=() por default, mas T1_FEATURE_IDS (pós-AG-362, 22
    # features) já inclui E14f_toptrader_ls_ratio/E16f_global_ls_ratio,
    # então load_futures_positioning é True incondicionalmente agora
    # (D07f continua False -- nenhuma feature T1 depende dele); build_
    # regimes SEMPRE passa False pros dois (nunca precisa, ver docstring
    # de src/regime/build.py).
    assert features_calls == [
        {
            "bar_source": "dollar_r1",
            "vol_estimator_id": "parkinson_w20",
            "load_taker_imbalance_1m": False,
            "load_futures_positioning": True,
        }
    ]
    assert regime_calls == [
        {
            "bar_source": "dollar_r1",
            "vol_estimator_id": "parkinson_w20",
            "load_taker_imbalance_1m": False,
            "load_futures_positioning": False,
        }
    ]


def test_build_modeling_frame_resolution_id_none_preserva_bar_source_time_15m(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    features_calls: list[dict[str, Any]] = []

    def _fake_build_t1_features(symbol: str, start: str, end: str, **kwargs: Any) -> pl.DataFrame:
        features_calls.append(kwargs)
        return _one_row_bar_table(t0)

    monkeypatch.setattr(cpcv, "load_labels_v1", lambda *a, **k: _one_row_labels(t0))
    monkeypatch.setattr(features_build, "build_t1_features", _fake_build_t1_features)
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end, **kwargs: _one_row_regime(t0)
    )
    _noop_verify_config_hash(monkeypatch)

    ds.build_modeling_frame()

    # **[CORRIGIDO 2026-08-27, AG-365]** load_futures_positioning=True
    # mesmo sem extra_feature_ids -- T1_FEATURE_IDS (pós-AG-362) já
    # inclui 2 features de futures-positioning, ver comentário no teste
    # de resolution_id="R1" acima.
    assert features_calls == [
        {
            "bar_source": "time_15m",
            "vol_estimator_id": None,
            "load_taker_imbalance_1m": False,
            "load_futures_positioning": True,
        }
    ]


@pytest.mark.parametrize(
    ("extra_feature_ids", "expected_d07f", "expected_futures_positioning"),
    [
        # T1_FEATURE_IDS (pós-AG-362, 22 features) já contém E14f/E16f --
        # futures_positioning sai True mesmo sem pedir nada extra.
        ((), False, True),
        (("D07f_taker_imbalance_1m_agg",), True, True),
        # E18f_taker_ls_vol_ratio (não E14f, que já está em T1 e não prova
        # mais nada isolado) -- mantida fora de T1 de propósito (quarentena,
        # AG-266), prova que extra_feature_ids sozinho também aciona.
        (("E18f_taker_ls_vol_ratio",), False, True),
        (("D07f_taker_imbalance_1m_agg", "E17f_retail_vs_top_spread"), True, True),
    ],
)
def test_build_modeling_frame_ativa_d07f_futures_positioning_por_t1_ou_extra(
    monkeypatch: pytest.MonkeyPatch,
    extra_feature_ids: tuple[str, ...],
    expected_d07f: bool,
    expected_futures_positioning: bool,
) -> None:
    """Achado real (`audit_engineering`, 2026-08-24): `build_t1_features`
    default `load_taker_imbalance_1m=True`/`load_futures_positioning=
    True` pagava custo de IO real (D07f = klines_1m bruto) em TODO
    treino do Alpha, mesmo nada precisando. **[CORRIGIDO 2026-08-27,
    AG-365]** a ativação depende da UNIÃO de `T1_FEATURE_IDS` (sempre
    ativo) com `extra_feature_ids` (opcional) -- não só do segundo. Com
    a composição atual de T1 (pós-`AG-362`), `load_futures_positioning`
    já sai `True` mesmo com `extra_feature_ids=()`; o teste abaixo
    (`..._reage_a_t1_feature_ids_tambem`) monkeypatcha `T1_FEATURE_IDS`
    pra provar a metade da união que este parametrize sozinho não
    consegue isolar."""
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    features_calls: list[dict[str, Any]] = []

    def _fake_build_t1_features(symbol: str, start: str, end: str, **kwargs: Any) -> pl.DataFrame:
        features_calls.append(kwargs)
        return _one_row_bar_table_with(t0, extra_feature_ids)

    monkeypatch.setattr(cpcv, "load_labels_v1", lambda *a, **k: _one_row_labels(t0))
    monkeypatch.setattr(features_build, "build_t1_features", _fake_build_t1_features)
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end, **kwargs: _one_row_regime(t0)
    )
    _noop_verify_config_hash(monkeypatch)

    ds.build_modeling_frame(extra_feature_ids=extra_feature_ids)

    assert features_calls[0]["load_taker_imbalance_1m"] is expected_d07f
    assert features_calls[0]["load_futures_positioning"] is expected_futures_positioning


def test_build_modeling_frame_ativa_futures_positioning_reage_a_t1_feature_ids_tambem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regressão de `AG-365`: a checagem original só olhava
    `extra_feature_ids`, nunca `T1_FEATURE_IDS` -- ficou errada em
    silêncio quando `AG-362` (mesmo dia) promoveu features de
    futures-positioning DIRETO pra `T1_FEATURE_IDS`. Monkeypatcha
    `T1_FEATURE_IDS` pra um conjunto mínimo que NÃO precisa de nenhuma
    das duas fontes, com `extra_feature_ids=()` -- prova que a resposta
    é de fato à UNIÃO (varia com T1, não só com extra), não um valor
    travado por coincidência da composição atual."""
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    features_calls: list[dict[str, Any]] = []

    def _fake_build_t1_features(symbol: str, start: str, end: str, **kwargs: Any) -> pl.DataFrame:
        features_calls.append(kwargs)
        return _one_row_bar_table(t0)

    monkeypatch.setattr(cpcv, "load_labels_v1", lambda *a, **k: _one_row_labels(t0))
    monkeypatch.setattr(features_build, "build_t1_features", _fake_build_t1_features)
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end, **kwargs: _one_row_regime(t0)
    )
    monkeypatch.setattr(features_build, "T1_FEATURE_IDS", ("A05_ret_vol_norm_4",))
    _noop_verify_config_hash(monkeypatch)

    ds.build_modeling_frame()

    assert features_calls[0]["load_taker_imbalance_1m"] is False
    assert features_calls[0]["load_futures_positioning"] is False


def test_build_modeling_frame_regime_nunca_pede_d07f_futures_positioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`build_regimes` (via `build_modeling_frame`) SEMPRE recebe `False`
    pros dois, independente de `extra_feature_ids` -- regime nunca usa
    D07f/futures-positioning, o parâmetro é escopo só do frame de
    FEATURES."""
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    regime_calls: list[dict[str, Any]] = []

    def _fake_build_regimes(symbol: str, start: str, end: str, **kwargs: Any) -> pl.DataFrame:
        regime_calls.append(kwargs)
        return _one_row_regime(t0)

    extra_feature_ids = ("D07f_taker_imbalance_1m_agg", "E17f_retail_vs_top_spread")
    monkeypatch.setattr(cpcv, "load_labels_v1", lambda *a, **k: _one_row_labels(t0))
    monkeypatch.setattr(
        features_build,
        "build_t1_features",
        lambda symbol, start, end, **k: _one_row_bar_table_with(t0, extra_feature_ids),
    )
    monkeypatch.setattr(regime_build, "build_regimes", _fake_build_regimes)
    _noop_verify_config_hash(monkeypatch)

    ds.build_modeling_frame(extra_feature_ids=extra_feature_ids)

    assert regime_calls[0]["load_taker_imbalance_1m"] is False
    assert regime_calls[0]["load_futures_positioning"] is False


def test_build_modeling_frame_resolution_id_nao_mapeado_levanta_valueerror() -> None:
    """Qualquer `resolution_id` fora de `_BAR_SOURCE_BY_RESOLUTION` (hoje
    R1/R2/R3, dict FECHADO por desenho) levanta `ValueError` explícito em
    vez de deixar `_sources.load_bars` levantar um erro menos claro depois.

    `R2`/`R3` foram promovidas de "pesquisa, sem bar_source mapeado" pra
    "escopo de produção" em 2026-08-22 (`AG-100`, condicionado à
    recalibração causal do `AG-124` ter fechado -- fechou) -- este teste
    usa `R99` (identidade que nunca existiu em nenhuma camada) pra
    continuar testando o caminho de erro sem depender de R2/R3
    especificamente."""
    with pytest.raises(ValueError, match="resolution_id"):
        ds.build_modeling_frame(resolution_id="R99")


def test_build_modeling_frame_tf_diferente_de_15m_sem_resolution_id_levanta_valueerror() -> None:
    """Achado de auditoria (audit_engineering, 2026-08-17): antes desta
    correção, `bar_source` era hardcoded `"time_15m"` independente de `tf`
    -- `tf="30m"` chegaria corretamente a `load_labels_v1`/`CPCVConfig.
    grade_id` (via `run_layer1_sprint`) mas features/regime ficariam presas
    em 15m, incoerência silenciosa (não explorável hoje só porque não
    existe `labels/` de 30m/1h em disco ainda -- mas o projeto está
    construindo suporte multi-TF ativamente). `ValueError` explícito agora,
    mesma disciplina do guard de `resolution_id` acima."""
    with pytest.raises(ValueError, match="tf"):
        ds.build_modeling_frame(tf="30m", resolution_id=None)


def test_build_modeling_frame_tf_15m_sem_resolution_id_nao_levanta() -> None:
    """Confirma que o guard novo não é largo demais -- tf="15m" (default e
    único suportado) continua funcionando, sem regressão."""
    with pytest.raises(FileNotFoundError):
        # levanta por labels reais ausentes no ambiente de teste, não pelo
        # guard novo -- prova que tf="15m" passa da validação
        ds.build_modeling_frame(symbol="__SYMBOL_INEXISTENTE__", tf="15m", resolution_id=None)


# ============================================================================
# verify_config_hash (B15) -- AG-140, 2026-08-23: wireado no caminho real de
# build_modeling_frame, o único ponto onde labels.parquet é carregado pra
# montar o frame de treino/backtest. Testes abaixo NÃO mockam
# verify_config_hash (exceto o último, que precisa capturar o argumento) --
# provam a função real integrada, não só que ela foi chamada.
# ============================================================================


def _one_row_labels_with_hash(t0: datetime, config_hash: str) -> pl.DataFrame:
    return _one_row_labels(t0).with_columns(pl.lit(config_hash).alias("config_hash"))


def test_build_modeling_frame_resolution_id_sem_vol_estimator_id_levanta_valueerror() -> None:
    """AG-140: sob resolution_id, vol_estimator_id=None computaria
    features/regime com o estimador default enquanto os labels reais de
    R1/R2/R3 foram gerados com Parkinson explícito (`run_and_write_labels_
    dollar_bar_parkinson`) -- mesma exigência que `LabelConfig.
    from_constants` já impõe, agora também aqui, antes de qualquer IO."""
    with pytest.raises(ValueError, match="vol_estimator_id"):
        ds.build_modeling_frame(resolution_id="R1", vol_estimator_id=None)


def test_build_modeling_frame_config_hash_match_nao_levanta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`labels.config_hash` batendo com `LabelConfig.from_constants` (grade
    default, tf=15m) não levanta nada -- caso são."""
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    expected_hash = LabelConfig.from_constants(estimator_id=None, tf="15m").config_hash

    monkeypatch.setattr(
        cpcv, "load_labels_v1", lambda *a, **k: _one_row_labels_with_hash(t0, expected_hash)
    )
    monkeypatch.setattr(
        features_build,
        "build_t1_features",
        lambda symbol, start, end, **kwargs: _one_row_bar_table(t0),
    )
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end, **kwargs: _one_row_regime(t0)
    )

    ds.build_modeling_frame()  # não levanta


def test_build_modeling_frame_config_hash_mismatch_levanta_confighashmismatcherror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-140 -- o achado central: um `labels.parquet` gerado sob uma
    config diferente da atual (`constants.yaml` mudou depois do backfill,
    ou `tf`/`resolution_id`/`vol_estimator_id` pedido aqui não bate com o
    que os labels reais assumem) precisa travar o build do frame de
    treino, não passar silencioso -- B15."""
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)

    monkeypatch.setattr(
        cpcv,
        "load_labels_v1",
        lambda *a, **k: _one_row_labels_with_hash(t0, "hash_de_uma_config_diferente"),
    )
    monkeypatch.setattr(
        features_build,
        "build_t1_features",
        lambda symbol, start, end, **kwargs: _one_row_bar_table(t0),
    )
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end, **kwargs: _one_row_regime(t0)
    )

    with pytest.raises(ConfigHashMismatchError, match="config_hash"):
        ds.build_modeling_frame()


def test_build_modeling_frame_verify_config_hash_usa_mesmo_vol_estimator_id_do_resto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-140 -- `execution_config` precisa usar o MESMO `vol_estimator_id`
    já propagado pra features/regime (nunca um estimador divergente pra
    label vs. feature -- mesmo princípio de "uma grade só" já documentado
    em `build_modeling_frame`). Prova capturando o `execution_config` real
    passado a `verify_config_hash`."""
    t0 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    captured: list[LabelConfig] = []

    def _capturing_verify_config_hash(
        labels: pl.DataFrame, execution_config: LabelConfig
    ) -> None:
        captured.append(execution_config)

    monkeypatch.setattr(
        cpcv, "load_labels_v1", lambda *a, **k: _one_row_labels_with_hash(t0, "irrelevante")
    )
    monkeypatch.setattr(
        features_build,
        "build_t1_features",
        lambda symbol, start, end, **kwargs: _one_row_bar_table(t0),
    )
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end, **kwargs: _one_row_regime(t0)
    )
    monkeypatch.setattr(ds, "verify_config_hash", _capturing_verify_config_hash)

    ds.build_modeling_frame(symbol="BTCUSDT", resolution_id="R1", vol_estimator_id="parkinson_w20")

    assert len(captured) == 1
    assert captured[0].estimator_id == "parkinson_w20"
    assert captured[0].resolution_id == "R1"


# ============================================================================
# AG-202 (2026-08-24) -- open_time duplicado colide no join de regime.
#
# Causa real (nao um bug em src/data/bars.py -- ver
# audit/architecture_gaps_log.yaml::AG-202, addendum_correcao_diagnostico):
# 2 trades da Binance no mesmo milissegundo, caindo numa fronteira de
# recalibracao do walk-forward, produzem 2 barras dollar com o MESMO
# open_time -- uma "fantasma" (duracao zero, 1 trade, fecha sozinha, mesmo
# comportamento ja testado e deliberado de
# threshold_bars_step) e uma real (duracao > 0, fecha no threshold
# recalibrado). `build_t1_features` devolve as 2; `build_regimes` reusa
# `build_t1_features` internamente e tambem devolve 2 avaliacoes de regime
# (o classificador tem histerese -- processa as 2 linhas em sequencia,
# cada uma avanca o estado). O join `bar_table.join(regime_small, on=
# "_open_time_ms")` (dataset.py) assumia open_time unico -- nunca era
# garantido por bars.py -- e produzia fan-out (2 linhas por t0 x side em
# vez de 1) na tabela final.
# ============================================================================


def _two_row_labels(t0_a: datetime, t0_b: datetime) -> pl.DataFrame:
    return pl.DataFrame({"t0": [t0_a, t0_b]}).with_columns(
        pl.col("t0").dt.replace_time_zone("UTC")
    )


def _bar_table_open_time_duplicado(t0_open: datetime, t0_close_real: datetime) -> pl.DataFrame:
    """2 linhas de `build_t1_features` -- barra-fantasma (`open_time ==
    close_time == t0_open`, valores de feature=0.0) e barra real
    (`open_time=t0_open`, `close_time=t0_close_real`, valores de
    feature=1.0 -- distintos de propósito, pra provar qual sobrevive)."""
    ms_open = int(t0_open.timestamp() * 1000)
    ms_close_real = int(t0_close_real.timestamp() * 1000)
    cols: dict[str, Any] = {
        "open_time": [ms_open, ms_open],
        "close_time": [ms_open, ms_close_real],
    }
    for fid in T1_FEATURE_IDS:
        cols[fid] = [0.0, 1.0]
    return pl.DataFrame(cols)


def _regime_open_time_duplicado(t0_open: datetime) -> pl.DataFrame:
    """2 avaliações de regime pro MESMO `open_time` (histerese processando
    a barra-fantasma e depois a real em sequência) -- `regime`/`tradeable`
    distintos de propósito ("R1"/primeira tick vs. "R2"/estado assentado),
    pra provar que a ÚLTIMA (estado assentado) sobrevive, não a primeira."""
    return pl.DataFrame(
        {
            "t0": [t0_open, t0_open],
            "regime": ["R1", "R2"],
            "tradeable": [False, True],
        }
    ).with_columns(pl.col("t0").dt.replace_time_zone("UTC"))


def test_build_modeling_frame_open_time_duplicado_nao_produz_linha_fantasma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-202 -- reprodução mínima e sintética da colisão real (2 trades no
    mesmo ms numa fronteira de recalibração). Sem o fix, o label cujo `t0`
    bate com o `close_time` da barra REAL sairia DUPLICADO (2 linhas, uma
    por avaliação de regime) em vez de 1. O label cujo `t0` bate com o
    `close_time` da barra FANTASMA (que é o próprio `open_time`, já que a
    fantasma tem duração zero) fica com feature/regime NULOS após o fix --
    consequência aceita e já tratada pelo filtro de nulos existente
    (`side_subset`), não uma duplicata."""
    t0_open = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    t0_close_real = datetime(2024, 1, 1, 0, 20, tzinfo=UTC)

    monkeypatch.setattr(
        cpcv, "load_labels_v1", lambda *a, **k: _two_row_labels(t0_open, t0_close_real)
    )
    monkeypatch.setattr(
        features_build,
        "build_t1_features",
        lambda symbol, start, end, **kwargs: _bar_table_open_time_duplicado(
            t0_open, t0_close_real
        ),
    )
    monkeypatch.setattr(
        regime_build,
        "build_regimes",
        lambda symbol, start, end, **kwargs: _regime_open_time_duplicado(t0_open),
    )
    _noop_verify_config_hash(monkeypatch)

    mf = ds.build_modeling_frame()

    # 2 labels de entrada -> 2 linhas de saida, nunca 3 ou 4 (fan-out do
    # join de regime).
    assert mf.data.height == 2

    row_real = mf.data.filter(pl.col("t0") == t0_close_real)
    assert row_real.height == 1
    assert row_real[T1_FEATURE_IDS[0]][0] == 1.0  # feature da barra REAL, nao da fantasma (0.0)
    assert row_real["regime"][0] == "R2"  # ultima avaliacao (estado assentado), nao a 1a ("R1")
    assert row_real["tradeable"][0] is True

    row_phantom = mf.data.filter(pl.col("t0") == t0_open)
    assert row_phantom.height == 1
    # barra fantasma foi descartada do bar_table (mantida so a com maior
    # close_time) -- o close_time dela (== proprio open_time) nao acha mais
    # par no join, entao a feature fica nula (filtrada depois por
    # side_subset), NUNCA duplicada.
    assert row_phantom[T1_FEATURE_IDS[0]][0] is None


def _synthetic_frame() -> pl.DataFrame:
    n = 6
    cols: dict[str, object] = {
        "side": pl.Series([1, 1, 1, -1, -1, -1], dtype=pl.Int8),
        "barrier_hit": pl.Series(["TP", "SL", "NOFILL", "TP", "TIME", "NOFILL"]),
        # `enforce_r2=True` é o default de produção desde 2026-08-27 (ver
        # CLAUDE.md "Diretrizes de comportamento") -- colunas de custo/
        # preço folgadas o bastante pra NUNCA violar R2 (stop=5%, custo
        # total=2bps, ratio=0,0004 << cost_stop_ratio_max=0,20), pra estes
        # testes continuarem provando SÓ NOFILL/warmup, não R2.
        "entry_price_limit": pl.Series([100.0] * n, dtype=pl.Float64),
        "sl_price": pl.Series([95.0] * n, dtype=pl.Float64),
        "cost_entry_bps": pl.Series([1.0] * n, dtype=pl.Float64),
        "cost_exit_bps": pl.Series([1.0] * n, dtype=pl.Float64),
        "funding_bps": pl.Series([0.0] * n, dtype=pl.Float64),
    }
    for i, fid in enumerate(T1_FEATURE_IDS):
        # última linha do lado long (índice 2, que já é NOFILL) e uma
        # extra (índice 0) com feature nula para provar o filtro de warmup
        # independente do filtro de NOFILL.
        values: list[float | None] = [0.1 * i + j for j in range(n)]  # noqa: magic-number
        if i == 0:
            values[0] = None
        cols[fid] = pl.Series(values, dtype=pl.Float64)
    return pl.DataFrame(cols)


def test_side_subset_descarta_nofill() -> None:
    df = _synthetic_frame()
    out = ds.side_subset(df, side=1, feature_ids=T1_FEATURE_IDS)
    assert "NOFILL" not in out["barrier_hit"].to_list()


def test_side_subset_descarta_warmup_feature_nula() -> None:
    df = _synthetic_frame()
    out = ds.side_subset(df, side=1, feature_ids=T1_FEATURE_IDS)
    # a linha 0 (side=1, TP, mas feature nula) tem que sumir
    assert out.height == 1  # só a linha 1 (side=1, SL, sem null) sobrevive
    assert out["barrier_hit"].to_list() == ["SL"]


def test_side_subset_lado_short() -> None:
    df = _synthetic_frame()
    out = ds.side_subset(df, side=-1, feature_ids=T1_FEATURE_IDS)
    assert set(out["barrier_hit"].to_list()) <= {"TP", "TIME"}
    assert "NOFILL" not in out["barrier_hit"].to_list()


def test_side_subset_exige_feature_ids_e_nao_aceita_vazio() -> None:
    """`AG-300` -- `feature_ids` deixou de ter default. O default (`T1_
    FEATURE_IDS`, 7) era exatamente o defeito: o treino filtrava warmup por
    7 colunas enquanto `unique_test_bars` (o lado de TESTE) ja recebia o
    conjunto real, entao treino e teste ficavam com populacoes diferentes."""
    df = _synthetic_frame()
    with pytest.raises(TypeError):
        ds.side_subset(df, side=1)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="feature_ids vazio"):
        ds.side_subset(df, side=1, feature_ids=())


def test_side_subset_coluna_ausente_no_frame_falha_com_o_nome() -> None:
    df = _synthetic_frame()
    with pytest.raises(ValueError, match="ausente"):
        ds.side_subset(df, side=1, feature_ids=(*T1_FEATURE_IDS, "Z99_nao_existe"))


def test_side_subset_coluna_100pct_nula_falha_alto_nomeando_a_coluna() -> None:
    """`AG-300` -- o caso `D07f_taker_imbalance_1m_agg` sob dollar bar, em
    forma sintetica: uma coluna sem NENHUM valor finito.

    Sem esta guarda o filtro de warmup zera o conjunto de treino, e "0
    linhas" nao diz QUAL das colunas causou. Com ela, o nome sai na
    mensagem. Este teste tambem prova que a fronteira `nan_to_null=True`
    (`src/features/build.py`) importa: se a coluna chegasse aqui como
    `NaN` em vez de `null`, `is_not_null()` a deixaria passar inteira e
    nem a guarda nem o filtro veriam problema nenhum."""
    df = _synthetic_frame().with_columns(
        pl.lit(None, dtype=pl.Float64).alias("D07f_taker_imbalance_1m_agg")
    )
    fids = (*T1_FEATURE_IDS, "D07f_taker_imbalance_1m_agg")
    with pytest.raises(features_build.DeadFeatureColumnError) as exc:
        ds.side_subset(df, side=1, feature_ids=fids)
    msg = str(exc.value)
    assert "D07f_taker_imbalance_1m_agg" in msg
    assert "side=1" in msg


def test_side_subset_coluna_com_UM_valor_finito_nao_e_considerada_morta() -> None:
    """A guarda e sobre coluna MORTA (100% nula), nao sobre coluna com
    muito nulo -- warmup longo e legitimo e nao pode falhar."""
    df = _synthetic_frame()
    quase_morta = [None, 1.0, None, None, None, None]
    df = df.with_columns(pl.Series("W01_quase_morta", quase_morta, dtype=pl.Float64))
    out = ds.side_subset(df, side=1, feature_ids=(*T1_FEATURE_IDS, "W01_quase_morta"))
    assert out.height == 1  # so a linha 1, que tem a coluna preenchida


def test_side_subset_side_invalido_levanta_erro() -> None:
    df = _synthetic_frame()
    with pytest.raises(ValueError):
        ds.side_subset(df, side=0, feature_ids=T1_FEATURE_IDS)


# ============================================================================
# enforce_r2 -- achado real 2026-08-27 (handoff de src/models/, AG-296/
# AG-297): R2 nunca era aplicada nesta camada. Ratio lido de constants.yaml
# de verdade (não hardcodado) para o teste continuar válido se o valor
# medido mudar -- só a POSIÇÃO relativa ao ratio importa aqui.
# ============================================================================


def _frame_for_r2(
    *,
    side: int,
    entry: list[float],
    sl: list[float],
    cost_bps_total: list[float],
    funding_bps: list[float] | None = None,
) -> pl.DataFrame:
    """Frame mínimo pra `enforce_r2` -- `side`/`barrier_hit`="TP" (passa o
    filtro de NOFILL) + feature T1 preenchida (passa o filtro de warmup) +
    as colunas de preço/custo que `viola_r2` usa. `cost_bps_total` é o
    custo de ida e volta JÁ SOMADO -- dividido igual entre entry/exit.
    `funding_bps` (`AG-249` Problema A) -- default zero em toda linha,
    não afeta os testes que não passam a intenção explícita de medir seu
    efeito."""
    n = len(entry)
    cols: dict[str, object] = {
        "side": pl.Series([side] * n, dtype=pl.Int8),
        "barrier_hit": pl.Series(["TP"] * n),
        "entry_price_limit": pl.Series(entry, dtype=pl.Float64),
        "sl_price": pl.Series(sl, dtype=pl.Float64),
        "cost_entry_bps": pl.Series([c / 2.0 for c in cost_bps_total], dtype=pl.Float64),
        "cost_exit_bps": pl.Series([c / 2.0 for c in cost_bps_total], dtype=pl.Float64),
        "funding_bps": pl.Series(
            funding_bps if funding_bps is not None else [0.0] * n, dtype=pl.Float64
        ),
    }
    for fid in T1_FEATURE_IDS:
        cols[fid] = pl.Series([1.0] * n, dtype=pl.Float64)
    return pl.DataFrame(cols)


def _r2_frame_uma_ok_uma_viola() -> pl.DataFrame:
    ratio = float(load_constant("cost_stop_ratio_max"))
    stop = 0.01  # |99 - 100| / 100
    cost_ok = 0.5 * ratio * stop  # bem dentro do limite
    cost_viola = 2.0 * ratio * stop  # bem acima do limite
    return _frame_for_r2(
        side=1,
        entry=[100.0, 100.0],
        sl=[99.0, 99.0],
        cost_bps_total=[cost_ok * 10_000.0, cost_viola * 10_000.0],
    )


def test_side_subset_enforce_r2_false_reproduz_o_comportamento_anterior() -> None:
    df = _r2_frame_uma_ok_uma_viola()
    out = ds.side_subset(df, side=1, feature_ids=T1_FEATURE_IDS, enforce_r2=False)
    assert out.height == 2  # nenhuma linha filtrada por R2 -- explícito, não default


def test_side_subset_enforce_r2_default_e_true_e_de_fato_filtra() -> None:
    """**[PROMOVIDO A DEFAULT DE PRODUÇÃO 2026-08-27]** -- sem passar
    `enforce_r2` nenhum, o comportamento já é o corrigido (filtra a linha
    que viola R2), não o legado."""
    df = _r2_frame_uma_ok_uma_viola()
    out = ds.side_subset(df, side=1, feature_ids=T1_FEATURE_IDS)
    assert out.height == 1


def test_side_subset_enforce_r2_true_filtra_a_linha_que_viola() -> None:
    df = _r2_frame_uma_ok_uma_viola()
    out = ds.side_subset(df, side=1, feature_ids=T1_FEATURE_IDS, enforce_r2=True)
    assert out.height == 1
    # a linha que sobrevive é a de custo baixo (índice 0 do frame de entrada)
    assert out["cost_entry_bps"].to_list()[0] < df["cost_entry_bps"].to_list()[1]


def test_side_subset_enforce_r2_fronteira_custo_igual_ratio_vezes_stop_passa() -> None:
    """R2 é `<=`, não `<` (`CLAUDE.md` §0.2) -- testado exatamente no ponto,
    mesma disciplina de `test_analysis_r2_admissibility_census.py`."""
    ratio = float(load_constant("cost_stop_ratio_max"))
    stop = 0.01
    cost_na_fronteira = ratio * stop
    df = _frame_for_r2(
        side=1, entry=[100.0], sl=[99.0], cost_bps_total=[cost_na_fronteira * 10_000.0]
    )
    out = ds.side_subset(df, side=1, feature_ids=T1_FEATURE_IDS, enforce_r2=True)
    assert out.height == 1


def test_side_subset_enforce_r2_inclui_funding_bps_no_custo() -> None:
    """`AG-249` Problema A (2026-08-27) -- uma linha exatamente na
    fronteira de R2 (custo == ratio*stop) SEM funding passa; a MESMA
    linha, com `funding_bps` que empurra o custo pra além da fronteira,
    passa a violar -- prova que `enforce_r2` de fato lê a coluna."""
    ratio = float(load_constant("cost_stop_ratio_max"))
    stop = 0.01
    cost_na_fronteira = ratio * stop
    sem_funding = _frame_for_r2(
        side=1, entry=[100.0], sl=[99.0], cost_bps_total=[cost_na_fronteira * 10_000.0]
    )
    out_sem_funding = ds.side_subset(
        sem_funding, side=1, feature_ids=T1_FEATURE_IDS, enforce_r2=True
    )
    assert out_sem_funding.height == 1

    com_funding = _frame_for_r2(
        side=1,
        entry=[100.0],
        sl=[99.0],
        cost_bps_total=[cost_na_fronteira * 10_000.0],
        funding_bps=[1.0],  # noqa: magic-number -- qualquer valor > 0 empurra a linha além da fronteira exata
    )
    out = ds.side_subset(com_funding, side=1, feature_ids=T1_FEATURE_IDS, enforce_r2=True)
    assert out.height == 0


# ============================================================================
# F1 — R0 é 100% warmup, não um efeito de tau/threshold do Alpha
#
# Achado (investigado nesta mesma rodada, CLAUDE.md "Contexto"): zero das
# 30.623 trades realizadas do Alpha caem em regime R0 (~0,8% da história).
# R0 cobre exatamente o início da série (as barras mais antigas do dataset,
# medido de novo por `build_modeling_frame` abaixo — o valor exato migra
# um pouco entre rodadas conforme o backfill de dados avança, por isso os
# testes aqui checam a PROPRIEDADE ["100% de R0 sem T1 válido"], não um
# `N_R0_BARS` fixo). As janelas rolantes das 10 features T1
# (`T1_FEATURE_IDS`) ainda não têm histórico suficiente nessas barras para
# produzir valor não-nulo — é warmup estrutural, não um efeito do modelo:
# `src.models.dataset.side_subset` (treino) e
# `src.models.alpha.unique_test_bars` (inferência/teste) filtram QUALQUER
# linha com T1 nulo antes de o Alpha ver o dado, então R0 nunca teve
# população válida para gerar sinal, independente de `tau` ou de qualquer
# outro hiperparâmetro.
# ============================================================================


def _skip_if_labels_missing() -> None:
    path = labels_symbol_tf_dir("BTCUSDT", "v1") / "labels.parquet"
    if not path.exists():
        pytest.skip(f"{path} ausente — rode o Label Engine (Sprint 6) primeiro")


@pytest.mark.slow
@pytest.mark.integration
def test_regime_r0_e_100_por_cento_warmup_sem_t1_valido() -> None:
    """Teste de regressão da causa estrutural do achado F1, sobre o frame
    real (`build_modeling_frame`, ~14s medido — não uma amostra sintética,
    de propósito: a pergunta original era sobre o dado real, e um fixture
    sintético não provaria nada sobre warmup real). Confirma diretamente
    que TODA barra com `regime == "R0"` tem pelo menos uma das 10 features
    T1 nula — a mesma checagem, operacionalizada, que
    `n_missing_t1_first_feature` (logado por `build_modeling_frame`) já
    sugere de forma agregada."""
    _skip_if_labels_missing()
    # `AG-257` — `build_modeling_frame()` sem `resolution_id` resolve para a
    # grade de RELÓGIO 15m, cujos labels ficaram em `mark_1m` (grupo de
    # controle de `AG-229`); desde `AG-236` isso falha alto em B15, que é o
    # comportamento pretendido. O que este teste afirma — que R0 é 100%
    # warmup e não tem `t1` válido — é estrutural e não depende da grade,
    # então MIGRA para a grade de produção em vez de ser congelado na legada.
    frame = ds.build_modeling_frame(
        resolution_id="R1", vol_estimator_id="parkinson_w20"
    ).data
    r0 = frame.filter(pl.col(ds.REGIME_COL) == "R0")
    # a checagem abaixo só tem conteúdo se R0 de fato aparecer no frame —
    # um R0 vazio não provaria "100% warmup", provaria "R0 sumiu".
    msg = "regime R0 não apareceu no frame real — investigação F1 pressupõe que existe"
    assert r0.height > 0, msg
    # linha só conta como "T1 completo" se as 10 features forem não-nulas
    # simultaneamente — `pl.all_horizontal` é a versão vetorizada exata do
    # "AND" que `side_subset`/`unique_test_bars` aplicam feature a feature.
    tem_t1_completo = pl.all_horizontal([pl.col(fid).is_not_null() for fid in T1_FEATURE_IDS])
    n_r0_com_t1_completo = r0.filter(tem_t1_completo).height
    assert n_r0_com_t1_completo == 0


def _predictions_path(model_id: str) -> Path:
    return PREDICTIONS_OUTPUT_DIR / "alpha" / model_id / "predictions.parquet"


def _skip_if_predictions_missing() -> None:
    if not _predictions_path(MODEL_ID_CAMADA1).exists():
        pytest.skip(
            "predictions/alpha/.../predictions.parquet ausente — rode "
            "src.models.pipeline.run_layer1_sprint() primeiro (Sprint 8)"
        )


@pytest.mark.slow
@pytest.mark.integration
def test_predictions_reais_do_alpha_zero_sinais_em_r0() -> None:
    """Segundo teste do achado F1 — dado real ponta a ponta (não só a
    causa estrutural do teste acima): junta `predictions/alpha/{model_id}/
    predictions.parquet` (Sprint 8, sinais reais do Alpha, OOF) com o
    `regime` reconstruído por `build_modeling_frame` via `t0` — a mesma
    chave que `src.models.alpha.run_fold` usa para escrever
    `predictions["t0"] = test_bars_unique["t0"]` — e confirma que nenhuma
    linha com `side_hat != 0` (sinal de fato emitido, B18: dois binários
    `M_long`/`M_short`) cai em R0.

    Achado mais forte do que o exigido, também verificado aqui: NENHUMA
    linha de `predictions.parquet` cai em R0, nem sequer com `side_hat ==
    0` — porque `src.models.alpha.unique_test_bars` já filtra T1 nulo do
    lado de teste antes de qualquer inferência, então R0 nunca chega a ser
    avaliado pelo modelo, não só nunca gera sinal acima do threshold `tau`."""
    pytest.skip(
        "AG-257 -- este teste junta `predictions/alpha/` (treinadas sob a "
        "grade de RELOGIO 15m) com `build_modeling_frame`. Desde AG-236 o "
        "frame na grade legada falha alto em B15 (comportamento pretendido), "
        "e migrar o frame para R1 quebraria o join por `t0` -- as grades sao "
        "diferentes. NAO ha predictions equivalentes em R1: o retreino sob a "
        "grade canonica ainda nao foi persistido. GATILHO DE REATIVACAO: "
        "quando existir `predictions/alpha/{symbol}/R1/{model_id}/"
        "predictions.parquet`, remover este skip e repontar o teste para elas.",
    )
    _skip_if_predictions_missing()
    preds = pl.read_parquet(_predictions_path(MODEL_ID_CAMADA1))
    frame = ds.build_modeling_frame().data
    regime_by_t0 = frame.select("t0", ds.REGIME_COL).unique(subset=["t0"])

    joined = preds.join(regime_by_t0, on="t0", how="left")
    assert joined.height == preds.height  # join 1:1 -- t0 é único em regime_by_t0
    # todo t0 de predictions precisa ter regime conhecido pós-join (sem nulls).
    assert int(joined[ds.REGIME_COL].null_count()) == 0

    sinais_em_r0 = joined.filter((pl.col(ds.REGIME_COL) == "R0") & (pl.col("side_hat") != 0))
    assert sinais_em_r0.height == 0

    # achado mais forte (ver docstring): nem sequer aparece UMA linha de
    # R0 em predictions, independente de side_hat.
    linhas_em_r0 = joined.filter(pl.col(ds.REGIME_COL) == "R0")
    assert linhas_em_r0.height == 0
