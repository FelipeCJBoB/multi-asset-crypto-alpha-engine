"""Testes de `src/models/meta.py` — F4 do Meta
(`docs/meta_model_design_doc_2026-08-22.md` §3.4, §7).

Dois testes carregam mais peso que os outros:

* `test_posto_nao_depende_do_conjunto_de_teste` — é a única prova de que a
  transformação de posto respeita B03. O vazamento que ela impede não
  seria pego por `leakage.py`: o teste #11 procura `fit` em objeto sklearn
  via `_GLOBAL_SCALER_PATTERN`, e um `rankdata` sobre treino ∪ teste não
  tem `fit` nenhum para o grep encontrar.
* `test_guarda_de_posto_pega_combinacao_linear_das_dummies` — reproduz o
  arquétipo real (`regime_tradeable`), que tem variância ALTA e por isso
  passaria batido pela guarda de "variância zero" da v1."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.models import meta
from src.models import meta_dataset as mds

_LEVELS = ("S0", "S1", "S2", "S3")


# ---------------------------------------------------------------------------
# ScoreRankTransform — B03
# ---------------------------------------------------------------------------


def test_posto_nao_depende_do_conjunto_de_teste() -> None:
    """**O teste central de F4.** A CDF é ajustada no TREINO; trocar o
    conjunto de teste inteiro não pode mudar o valor atribuído a uma linha.
    Se mudar, o posto virou função do próprio teste — vazamento por
    construção, invisível para `leakage.py`."""
    treino = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64)
    tf = meta.ScoreRankTransform.fit(treino)

    alvo = np.array([0.25], dtype=np.float64)
    sozinho = tf.transform(alvo)
    com_vizinhos = tf.transform(np.array([0.25, 0.99, 0.98, 0.97, 0.96], dtype=np.float64))

    assert sozinho[0] == com_vizinhos[0], "o posto mudou por causa das OUTRAS linhas de teste"
    assert sozinho[0] == pytest.approx(0.5), "2 de 4 valores de treino são <= 0,25"


def test_posto_e_monotono_e_limitado() -> None:
    tf = meta.ScoreRankTransform.fit(np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64))
    out = tf.transform(np.array([0.0, 0.15, 0.35, 0.99], dtype=np.float64))
    assert list(out) == sorted(out), "posto tem de ser monótono no score"
    assert out[0] == 0.0, "abaixo de todo o treino"
    assert out[-1] == 1.0, "acima de todo o treino"


def test_posto_e_invariante_a_transformacao_monotona() -> None:
    """A razão de o §3.4 preferir posto a z-score: o mapeamento score→P(y)
    difere por fold, e z-score (linear) não iguala mapeamento — só média e
    variância. O posto é imune a QUALQUER monótona."""
    treino = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64)
    teste = np.array([0.15, 0.35], dtype=np.float64)
    direto = meta.ScoreRankTransform.fit(treino).transform(teste)
    # Monótona arbitrária aplicada aos DOIS lados.
    transformado = meta.ScoreRankTransform.fit(treino**3).transform(teste**3)
    assert np.allclose(direto, transformado)


def test_posto_sobre_treino_vazio_levanta() -> None:
    with pytest.raises(meta.MetaLearnerError, match="treino vazio"):
        meta.ScoreRankTransform.fit(np.array([], dtype=np.float64))


# ---------------------------------------------------------------------------
# Guarda de amostra (§7.3)
# ---------------------------------------------------------------------------


def test_amostra_suficiente_passa() -> None:
    # EPV = 10 (constants.yaml), 7 colunas -> piso 70.
    meta.assert_sample_sufficient(n_events_eff=100.0, n_features_effective=7)


def test_amostra_insuficiente_levanta_alto() -> None:
    """Falha ALTO, nunca degradação silenciosa para um learner mais
    simples — degradar em silêncio é indistinguível de "funcionou"."""
    with pytest.raises(meta.InsufficientMetaSampleError, match="pass-through"):
        meta.assert_sample_sufficient(n_events_eff=50.0, n_features_effective=7)


def test_piso_escala_com_o_numero_de_colunas_do_fold() -> None:
    """`n_features_effective` é recalculado POR FOLD: usar número fixo
    deixaria a guarda mais frouxa justamente nos folds mais degenerados."""
    meta.assert_sample_sufficient(n_events_eff=45.0, n_features_effective=4)
    with pytest.raises(meta.InsufficientMetaSampleError):
        meta.assert_sample_sufficient(n_events_eff=45.0, n_features_effective=5)


def test_n_events_effective_usa_a_classe_minoritaria_por_unicidade() -> None:
    """Minoritária pela SOMA DE UNICIDADE, não por contagem de linhas — com
    rótulos sobrepostos as duas discordam, e é a informação efetiva que
    limita o que o modelo pode aprender."""
    frame = pl.DataFrame(
        {
            # 4 linhas de y=1 mas cada uma quase redundante; 2 de y=0 únicas.
            "y_meta": pl.Series([1, 1, 1, 1, 0, 0], dtype=pl.Int8),
            "uniqueness_subpop": [0.1, 0.1, 0.1, 0.1, 1.0, 1.0],
        }
    )
    # Por CONTAGEM a minoritária seria y=0 (2 linhas); por unicidade é y=1 (0,4).
    assert meta.n_events_effective(frame) == pytest.approx(0.4)


def test_n_events_effective_ignora_nofill() -> None:
    frame = pl.DataFrame(
        {
            "y_meta": pl.Series([1, 0, None, None], dtype=pl.Int8),
            "uniqueness_subpop": [1.0, 1.0, 99.0, 99.0],
        }
    )
    assert meta.n_events_effective(frame) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Guarda de posto (§3.4)
# ---------------------------------------------------------------------------


def test_guarda_de_posto_aceita_matriz_de_posto_cheio() -> None:
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, 4))
    diag = meta.check_design_rank(X, column_names=("a", "b", "c", "d"))
    assert diag.is_full_rank
    assert diag.matrix_rank == 4
    assert np.isfinite(diag.condition_number)


def test_guarda_de_posto_pega_combinacao_linear_das_dummies() -> None:
    """Reproduz o arquétipo REAL que motivou a guarda: `regime_tradeable`
    é combinação linear exata das dummies. Tem variância ALTA — a guarda
    de "variância zero" da v1 passaria batido."""
    dummies = np.array(
        [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0], [0.0, 0.0]]
    )
    tradeable = (dummies[:, 0] + dummies[:, 1]).reshape(-1, 1)
    assert float(tradeable.var()) > 0.0, "a coluna tem variância alta — esse é o ponto"
    X = np.hstack([dummies, tradeable])

    with pytest.raises(meta.RankDeficientDesignError, match="variância"):
        meta.check_design_rank(X, column_names=("ohe_a", "ohe_b", "regime_tradeable"))


# ---------------------------------------------------------------------------
# Design matrix
# ---------------------------------------------------------------------------


def test_colunas_do_design_sao_drop_first() -> None:
    cols = meta.design_columns_for(_LEVELS)
    assert cols[:4] == ("score_rank", "p_alpha", "margin", "side_hat")
    assert f"{mds.REGIME_OHE_PREFIX}S0" not in cols, "S0 é a referência"
    assert cols[4:] == tuple(f"{mds.REGIME_OHE_PREFIX}{n}" for n in ("S1", "S2", "S3"))


def test_design_nao_contem_nenhuma_coluna_proibida() -> None:
    assert not (set(meta.design_columns_for(_LEVELS)) & mds.META_FORBIDDEN_FEATURES)


def _mk_frame(n: int, seed: int) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    regime = rng.integers(0, 4, size=n)
    dados: dict[str, object] = {
        "score_alpha_raw": rng.uniform(0.3, 0.9, size=n),
        "p_alpha": rng.uniform(0.5, 0.9, size=n),
        "margin": rng.uniform(0.0, 0.3, size=n),
        "side_hat": rng.choice([-1, 1], size=n).astype(np.float64),
    }
    for i, nivel in enumerate(_LEVELS[1:], start=1):
        dados[f"{mds.REGIME_OHE_PREFIX}{nivel}"] = (regime == i).astype(np.float64)
    return pl.DataFrame(dados)


def test_design_matrix_ajusta_o_posto_no_treino_e_aplica_no_teste() -> None:
    treino, teste = _mk_frame(200, seed=1), _mk_frame(60, seed=2)
    x_tr, x_te, nomes, diag = meta.build_design_matrix(treino, teste, regime_levels=_LEVELS)

    assert x_tr.shape == (200, len(nomes))
    assert x_te.shape == (60, len(nomes))
    assert diag.is_full_rank
    # Coluna 0 é o posto: no TREINO cobre (0, 1]; no TESTE pode saturar.
    assert x_tr[:, 0].min() > 0.0 and x_tr[:, 0].max() == pytest.approx(1.0)
    assert x_te[:, 0].min() >= 0.0 and x_te[:, 0].max() <= 1.0


def test_design_matrix_recusa_frame_sem_as_colunas() -> None:
    magro = pl.DataFrame({"p_alpha": [0.5]})
    with pytest.raises(meta.MetaLearnerError, match="build_meta_signal_table"):
        meta.build_design_matrix(magro, magro, regime_levels=_LEVELS)


# ---------------------------------------------------------------------------
# LogitL2Meta (§7.2)
# ---------------------------------------------------------------------------


def _fit_logit(seed: int = 0) -> tuple[meta.LogitL2Meta, np.ndarray, tuple[str, ...]]:
    treino, teste = _mk_frame(300, seed=1), _mk_frame(80, seed=2)
    x_tr, x_te, nomes, _ = meta.build_design_matrix(treino, teste, regime_levels=_LEVELS)
    rng = np.random.default_rng(seed)
    y = (x_tr[:, 0] + rng.normal(scale=0.3, size=x_tr.shape[0]) > 0.5).astype(np.int64)
    w = np.ones(x_tr.shape[0], dtype=np.float64)
    learner = meta.LogitL2Meta(random_state=seed)
    learner.bind_column_names(nomes)
    learner.fit(x_tr, y, w)
    return learner, x_te, nomes


def test_logit_satisfaz_o_protocolo_metalearner() -> None:
    learner, _, _ = _fit_logit()
    assert isinstance(learner, meta.MetaLearner)


def test_predict_score_devolve_um_valor_por_linha_em_zero_um() -> None:
    learner, x_te, _ = _fit_logit()
    s = learner.predict_score(x_te)
    assert s.shape == (x_te.shape[0],)
    assert float(s.min()) >= 0.0 and float(s.max()) <= 1.0


def test_predict_antes_do_fit_levanta() -> None:
    learner = meta.LogitL2Meta(random_state=0)
    with pytest.raises(meta.MetaLearnerError, match="`fit` não foi chamado"):
        learner.predict_score(np.zeros((1, 7)))


def test_coefficient_shares_somam_um_e_cobrem_as_colunas() -> None:
    """§7.5 — reportado SEM limiar. O gate de HHI do DoD não se aplica na
    forma herdada: D-01 espera que regime domine, então um gate que exige
    difusão só passaria se a hipótese central falhasse."""
    learner, _, nomes = _fit_logit()
    shares = learner.coefficient_shares()
    assert set(shares) == set(nomes)
    assert sum(shares.values()) == pytest.approx(1.0)
    assert all(v >= 0.0 for v in shares.values())


def test_serializacao_e_json_sem_pickle_e_sem_calibrador(tmp_path: Path) -> None:
    """D-17/§14.4 — a inferência ao vivo é produto escalar mais sigmoid, e
    não precisa de sklearn no runtime. `calibrator: null` é declarado, não
    omitido: D-07 diz que o v1 não tem um, e a ausência explícita impede
    que alguém procure por um que nunca existiu."""
    learner, _, nomes = _fit_logit()
    dest = tmp_path / "meta_coef.json"
    learner.serialize(dest)

    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload["format"] == "meta_logit_l2_coef_v1"
    assert len(payload["coef"]) == len(nomes)
    assert payload["column_names"] == list(nomes)
    assert payload["calibrator"] is None
    assert isinstance(payload["intercept"], float)


def test_score_reconstruido_do_json_bate_com_o_modelo(tmp_path: Path) -> None:
    """A serialização só vale se o runtime SEM sklearn reproduzir o score.
    Reconstrói por produto escalar mais sigmoid e compara."""
    learner, x_te, _ = _fit_logit()
    dest = tmp_path / "meta_coef.json"
    learner.serialize(dest)
    payload = json.loads(dest.read_text(encoding="utf-8"))

    z = x_te @ np.array(payload["coef"], dtype=np.float64) + payload["intercept"]
    reconstruido = 1.0 / (1.0 + np.exp(-z))
    assert np.allclose(reconstruido, learner.predict_score(x_te))


# ---------------------------------------------------------------------------
# BlockedGBMMeta (§7.2) — o gate materializado num objeto que falha
# ---------------------------------------------------------------------------


def test_gbm_bloqueado_levanta_em_todos_os_metodos(tmp_path: Path) -> None:
    """Não é placeholder: é o gate de §7.3 como objeto que falha, em vez de
    comentário que alguém pode não ler."""
    gbm = BlockedGBM = meta.BlockedGBMMeta()
    with pytest.raises(meta.MetaLearnerBlockedError, match="meta_min_neff_for_gbm"):
        gbm.fit(np.zeros((2, 2)), np.zeros(2, dtype=np.int64), np.ones(2))
    with pytest.raises(meta.MetaLearnerBlockedError):
        gbm.predict_score(np.zeros((2, 2)))
    with pytest.raises(meta.MetaLearnerBlockedError):
        gbm.coefficient_shares()
    with pytest.raises(meta.MetaLearnerBlockedError):
        BlockedGBM.serialize(tmp_path / "x.json")


def test_gbm_bloqueado_ainda_satisfaz_o_protocolo() -> None:
    """A interface precisa ser a mesma — trocar de learner não pode exigir
    mudar o orquestrador."""
    assert isinstance(meta.BlockedGBMMeta(), meta.MetaLearner)
