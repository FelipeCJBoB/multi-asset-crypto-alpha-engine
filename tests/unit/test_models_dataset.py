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
from src.models import dataset as ds
from src.models._paths import PREDICTIONS_OUTPUT_DIR
from src.models.pipeline import MODEL_ID_CAMADA1
from src.regime import build as regime_build
from src.validation import cpcv
from src.validation._paths import labels_symbol_tf_dir

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
        version: str = "v1", *, symbol: str = "BTCUSDT", tf: str = "15m"
    ) -> pl.DataFrame:
        calls.append({"version": version, "symbol": symbol, "tf": tf})
        return _one_row_labels(t0)

    monkeypatch.setattr(cpcv, "load_labels_v1", _fake_load_labels_v1)
    monkeypatch.setattr(
        features_build, "build_t1_features", lambda symbol, start, end: _one_row_bar_table(t0)
    )
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end: _one_row_regime(t0)
    )

    ds.build_modeling_frame(symbol="ETHUSDT", labels_version="v1", tf="30m")

    assert calls == [{"version": "v1", "symbol": "ETHUSDT", "tf": "30m"}]


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
        version: str = "v1", *, symbol: str = "BTCUSDT", tf: str = "15m"
    ) -> pl.DataFrame:
        calls.append({"version": version, "symbol": symbol, "tf": tf})
        return _one_row_labels(t0)

    monkeypatch.setattr(cpcv, "load_labels_v1", _fake_load_labels_v1)
    monkeypatch.setattr(
        features_build, "build_t1_features", lambda symbol, start, end: _one_row_bar_table(t0)
    )
    monkeypatch.setattr(
        regime_build, "build_regimes", lambda symbol, start, end: _one_row_regime(t0)
    )

    ds.build_modeling_frame()

    assert calls == [{"version": "v1", "symbol": "BTCUSDT", "tf": "15m"}]


def _synthetic_frame() -> pl.DataFrame:
    n = 6
    cols: dict[str, object] = {
        "side": pl.Series([1, 1, 1, -1, -1, -1], dtype=pl.Int8),
        "barrier_hit": pl.Series(["TP", "SL", "NOFILL", "TP", "TIME", "NOFILL"]),
    }
    for i, fid in enumerate(T1_FEATURE_IDS):
        # última linha do lado long (índice 2, que já é NOFILL) e uma
        # extra (índice 0) com feature nula para provar o filtro de warmup
        # independente do filtro de NOFILL.
        values = [0.1 * i + j for j in range(n)]  # noqa: magic-number
        if i == 0:
            values[0] = None
        cols[fid] = pl.Series(values, dtype=pl.Float64)
    return pl.DataFrame(cols)


def test_side_subset_descarta_nofill() -> None:
    df = _synthetic_frame()
    out = ds.side_subset(df, side=1)
    assert "NOFILL" not in out["barrier_hit"].to_list()


def test_side_subset_descarta_warmup_feature_nula() -> None:
    df = _synthetic_frame()
    out = ds.side_subset(df, side=1)
    # a linha 0 (side=1, TP, mas feature nula) tem que sumir
    assert out.height == 1  # só a linha 1 (side=1, SL, sem null) sobrevive
    assert out["barrier_hit"].to_list() == ["SL"]


def test_side_subset_lado_short() -> None:
    df = _synthetic_frame()
    out = ds.side_subset(df, side=-1)
    assert set(out["barrier_hit"].to_list()) <= {"TP", "TIME"}
    assert "NOFILL" not in out["barrier_hit"].to_list()


def test_side_subset_side_invalido_levanta_erro() -> None:
    df = _synthetic_frame()
    with pytest.raises(ValueError):
        ds.side_subset(df, side=0)


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
# `src.models.alpha._unique_test_bars` (inferência/teste) filtram QUALQUER
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
    frame = ds.build_modeling_frame().data
    r0 = frame.filter(pl.col(ds.REGIME_COL) == "R0")
    # a checagem abaixo só tem conteúdo se R0 de fato aparecer no frame —
    # um R0 vazio não provaria "100% warmup", provaria "R0 sumiu".
    msg = "regime R0 não apareceu no frame real — investigação F1 pressupõe que existe"
    assert r0.height > 0, msg
    # linha só conta como "T1 completo" se as 10 features forem não-nulas
    # simultaneamente — `pl.all_horizontal` é a versão vetorizada exata do
    # "AND" que `side_subset`/`_unique_test_bars` aplicam feature a feature.
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
    0` — porque `src.models.alpha._unique_test_bars` já filtra T1 nulo do
    lado de teste antes de qualquer inferência, então R0 nunca chega a ser
    avaliado pelo modelo, não só nunca gera sinal acima do threshold `tau`."""
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
