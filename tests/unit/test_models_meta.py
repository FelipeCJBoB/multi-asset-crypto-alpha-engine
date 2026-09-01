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


# ---------------------------------------------------------------------------
# F5 — resolve_tau_meta (§8.3, D-07)
# ---------------------------------------------------------------------------


def test_tau_meta_escolhe_o_quantil_de_maior_pnl() -> None:
    """Caso sem empate: scores crescem, e os trades que sobrevivem a um
    corte mais alto são justamente os mais lucrativos -- a grade deve
    escolher o corte que maximiza a PnL in-fold do subconjunto aceito."""
    scores = np.array([0.1, 0.3, 0.5, 0.7, 0.9], dtype=np.float64)
    ret_net = np.array([-0.02, -0.01, 0.01, 0.02, 0.03], dtype=np.float64)
    grid = (0.0, 0.5, 0.9)

    resultado = meta.resolve_tau_meta(scores, ret_net, quantile_grid=grid, tie_epsilon=0.0)

    # q=0.9 -> tau=quantile(scores,0.9), aceita só o topo (0.03) -> PnL=0.03
    # q=0.5 -> aceita metade de cima -> PnL=0.02+0.03=0.05 (maior)
    # q=0.0 -> aceita tudo -> PnL=0.03 (soma de todos)
    assert resultado.quantile_chosen == pytest.approx(0.5)
    assert resultado.tie_broken is False


def test_tau_meta_empate_real_e_decidido_pelo_menor_pass_rate() -> None:
    """**O teste central de F5.** Dois quantis dão PnL IDÊNTICA (porque os
    trades extras que o quantil mais frouxo aceita têm ret_net=0 exato) --
    empate genuíno, e a regra manda vencer o de MENOR pass-rate (menos
    trades, preferência estrutural contra o otimismo do argmax)."""
    scores = np.array([0.1, 0.2, 0.3, 0.4, 0.9], dtype=np.float64)
    # As 4 primeiras linhas têm ret_net=0 -- aceitá-las ou não não muda a
    # PnL somada, só o pass-rate.
    ret_net = np.array([0.0, 0.0, 0.0, 0.0, 0.05], dtype=np.float64)
    grid = (0.0, 0.5, 0.9)

    resultado = meta.resolve_tau_meta(scores, ret_net, quantile_grid=grid, tie_epsilon=1e-9)

    assert resultado.tie_broken is True
    # q=0.9 tem o MENOR pass-rate entre os empatados (só a última linha).
    assert resultado.quantile_chosen == pytest.approx(0.9)


def test_epsilon_da_v1_perdia_empate_que_o_epsilon_correto_pega() -> None:
    """**Regressão exata do achado da v3.** Fixture com um gap de PnL entre
    dois quantis DELIBERADAMENTE maior que `1e-6` (o epsilon vazio da v1,
    que "nunca dispara" na prática) mas menor que o custo de round-trip de
    1 trade (`meta_tau_tie_epsilon` real, ~0,00055) -- a diferença entre os
    dois candidatos não paga nem um trade a mais, e É esse o "empate" que
    o §8.3 quer capturar. Com o epsilon da v1 o par NÃO seria tratado como
    empate (viraria argmax puro); com o epsilon correto, é."""
    scores = np.array([0.1, 0.2, 0.5, 0.9], dtype=np.float64)
    # q=0.0 aceita tudo: PnL = 0.01 + 0.01 + 0.05 = 0.07
    # q=0.5 aceita as 2 últimas: PnL = 0.01 + 0.05 = 0.06 -- gap = 0.01... grande
    # demais; ajustar pra um gap fino, dentro da janela [1e-6, epsilon real).
    ret_net = np.array([0.0, 0.0002, 0.0, 0.05], dtype=np.float64)
    grid = (0.0, 0.5)

    com_epsilon_da_v1 = meta.resolve_tau_meta(scores, ret_net, quantile_grid=grid, tie_epsilon=1e-6)
    com_epsilon_correto = meta.resolve_tau_meta(
        scores, ret_net, quantile_grid=grid, tie_epsilon=0.00055174
    )

    assert com_epsilon_da_v1.tie_broken is False, "1e-6 é fino demais pra pegar este gap real"
    assert com_epsilon_correto.tie_broken is True, "o custo de 1 trade pega o mesmo gap"
    # Entre os empatados, o epsilon correto prefere o de MENOR pass-rate.
    assert com_epsilon_correto.quantile_chosen == pytest.approx(0.5)


def test_epsilon_zero_e_empate_exato_bit_a_bit() -> None:
    """`tie_epsilon=0.0` ainda pega EMPATE EXATO (diferença de PnL
    exatamente zero) -- não é "nunca empata", é "só empata quando a
    diferença é literalmente zero". A distinção importa: um epsilon fino
    demais para gaps REAIS ainda captura o caso degenerado de PnL
    idêntica bit-a-bit (ex. os candidatos extras só têm ret_net=0)."""
    scores = np.array([0.1, 0.2, 0.3, 0.4, 0.9], dtype=np.float64)
    ret_net = np.array([0.0, 0.0, 0.0, 0.0, 0.05], dtype=np.float64)
    grid = (0.0, 0.5, 0.9)

    resultado = meta.resolve_tau_meta(scores, ret_net, quantile_grid=grid, tie_epsilon=0.0)

    assert resultado.tie_broken is True, "as 3 PnLs são EXATAMENTE 0,05 -- empate bit-a-bit"
    assert resultado.quantile_chosen == pytest.approx(0.9), "menor pass-rate entre os empatados"


def test_tau_meta_e_invariante_a_transformacao_monotona() -> None:
    """§8.3 -- quantil é invariante a monótona: aplicar uma transformação
    estritamente crescente aos scores não pode mudar QUAL LINHA é aceita,
    só o valor numérico de `tau_meta`."""
    scores = np.array([0.05, 0.3, 0.55, 0.8, 0.95], dtype=np.float64)
    ret_net = np.array([-0.03, 0.01, 0.02, -0.01, 0.04], dtype=np.float64)
    grid = (0.0, 0.25, 0.5, 0.75)

    base = meta.resolve_tau_meta(scores, ret_net, quantile_grid=grid, tie_epsilon=0.0)
    transformado = meta.resolve_tau_meta(scores**3, ret_net, quantile_grid=grid, tie_epsilon=0.0)

    aceito_base = scores >= base.tau_meta
    aceito_transformado = (scores**3) >= transformado.tau_meta
    np.testing.assert_array_equal(aceito_base, aceito_transformado)


def test_tau_meta_grade_vazia_levanta() -> None:
    with pytest.raises(meta.MetaLearnerError, match="vazia"):
        meta.resolve_tau_meta(
            np.array([0.1]), np.array([0.0]), quantile_grid=(), tie_epsilon=0.0
        )


def test_tau_meta_shapes_incompativeis_levanta() -> None:
    with pytest.raises(meta.MetaLearnerError, match="shape"):
        meta.resolve_tau_meta(
            np.array([0.1, 0.2]), np.array([0.0]), quantile_grid=(0.5,), tie_epsilon=0.0
        )


def test_tau_meta_le_constantes_reais_por_default() -> None:
    """Sem grid/epsilon explícitos, lê `config/constants.yaml` -- prova de
    que o ponto de injeção funciona com os valores REAIS do repo, não só
    com o que os outros testes passam de propósito."""
    rng = np.random.default_rng(0)
    scores = rng.uniform(0, 1, size=200)
    ret_net = rng.normal(0, 0.01, size=200)
    resultado = meta.resolve_tau_meta(scores, ret_net)
    assert resultado.quantile_grid == (0.0, 0.25, 0.50, 0.75, 0.90)
    assert resultado.quantile_chosen in resultado.quantile_grid


# ---------------------------------------------------------------------------
# apply_meta_filter (§8.1/§8.2, D-05/D-06) -- veto-em-zero
# ---------------------------------------------------------------------------


def test_filtro_mantem_side_hat_quando_p_meta_passa() -> None:
    side_hat = np.array([1, -1, 1], dtype=np.int8)
    p_meta = np.array([0.8, 0.9, 0.7], dtype=np.float64)
    out = meta.apply_meta_filter(side_hat, p_meta, tau_meta=0.6)
    np.testing.assert_array_equal(out, side_hat)


def test_filtro_nunca_inverte_o_lado_so_zera() -> None:
    """**A garantia central de D-05.** Mesmo com p_meta bem abaixo de 0,5
    (o cenário em que o snippet do AFML §10.3 inverteria o lado), o único
    valor possível além de `side_hat` é ZERO -- nunca `-side_hat`."""
    side_hat = np.array([1, -1, 1, -1], dtype=np.int8)
    p_meta = np.array([0.01, 0.02, 0.99, 0.98], dtype=np.float64)
    out = meta.apply_meta_filter(side_hat, p_meta, tau_meta=0.5)
    assert set(np.unique(out).tolist()) <= {-1, 0, 1}
    assert out.tolist() == [0, 0, 1, -1]


def test_filtro_shapes_incompativeis_levanta() -> None:
    with pytest.raises(meta.MetaLearnerError, match="shape"):
        meta.apply_meta_filter(np.array([1, -1]), np.array([0.5]), tau_meta=0.5)


# ---------------------------------------------------------------------------
# write_meta_fold_bundle / read_meta_fold_bundle / score_from_bundle (D-17)
# ---------------------------------------------------------------------------


def test_bundle_junta_learner_e_tau_meta_num_arquivo_so(tmp_path: Path) -> None:
    learner, x_te, nomes = _fit_logit()
    dest = tmp_path / "fold_bundle.json"

    meta.write_meta_fold_bundle(
        learner,
        dest,
        tau_meta=0.42,
        alpha_model_id="alpha_c1_v1",
        meta_split_id=3,
        variant="camada1",
        resolution_id="R1",
    )
    payload = meta.read_meta_fold_bundle(dest)

    assert payload["tau_meta"] == pytest.approx(0.42)
    assert payload["alpha_model_id"] == "alpha_c1_v1"
    assert payload["meta_split_id"] == 3
    assert payload["variant"] == "camada1"
    assert payload["resolution_id"] == "R1"
    assert payload["calibrator"] is None
    assert payload["column_names"] == list(nomes)

    reconstruido = meta.score_from_bundle(payload, x_te)
    assert np.allclose(reconstruido, learner.predict_score(x_te))


def test_bundle_incompleto_levanta_ao_ler(tmp_path: Path) -> None:
    dest = tmp_path / "incompleto.json"
    dest.write_text(json.dumps({"format": "x"}), encoding="utf-8")
    with pytest.raises(meta.MetaLearnerError, match="incompleto"):
        meta.read_meta_fold_bundle(dest)


# ---------------------------------------------------------------------------
# Orquestração — run_meta_fold / run_all_meta_folds
# ---------------------------------------------------------------------------

_ORCH_LEVELS = ("S0", "S1", "S2", "S3")


def _mk_orchestration_table(
    *,
    meta_split_id: int,
    path_id: int,
    n_train: int,
    n_test: int,
    seed: int,
    test_meta_status: str = mds.META_STATUS_OK,
) -> pl.DataFrame:
    """Fixture no schema REAL de `meta_dataset.build_meta_signal_table` —
    `score_alpha_raw` correlacionado com `ret_net`/`y_meta` (não ruído
    puro), pra que `LogitL2Meta` aprenda algo real e `resolve_tau_meta`
    tenha PnL não-degenerada pra escolher entre quantis."""
    rng = np.random.default_rng(seed)
    n = n_train + n_test
    regime = rng.integers(0, len(_ORCH_LEVELS), size=n)
    role = [mds.ROLE_TRAIN] * n_train + [mds.ROLE_TEST] * n_test
    score_alpha_raw = rng.uniform(0.3, 0.9, size=n)
    y_bruto = (score_alpha_raw > np.median(score_alpha_raw)).astype(np.int64)
    ret_net = np.where(
        y_bruto == 1,
        rng.uniform(0.005, 0.03, size=n),
        rng.uniform(-0.03, -0.005, size=n),
    )
    dados: dict[str, object] = {
        "meta_split_id": pl.Series([meta_split_id] * n, dtype=pl.Int16),
        "path_id": pl.Series([path_id] * n, dtype=pl.Int64),
        "role": role,
        "meta_status": [mds.META_STATUS_OK] * n_train + [test_meta_status] * n_test,
        "score_alpha_raw": score_alpha_raw,
        "p_alpha": rng.uniform(0.5, 0.9, size=n),
        "margin": rng.uniform(0.0, 0.3, size=n),
        "side_hat": pl.Series(rng.choice([-1, 1], size=n).tolist(), dtype=pl.Int8),
        "y_meta": pl.Series(y_bruto.tolist(), dtype=pl.Int8),
        "ret_net": ret_net,
        "meta_sample_weight": np.ones(n, dtype=np.float64),
        "uniqueness_subpop": np.ones(n, dtype=np.float64),
    }
    for i, nivel in enumerate(_ORCH_LEVELS[1:], start=1):
        dados[f"{mds.REGIME_OHE_PREFIX}{nivel}"] = (regime == i).astype(np.int64)
    return pl.DataFrame(dados)


def test_run_meta_fold_ajusta_modelo_quando_amostra_suficiente() -> None:
    table = _mk_orchestration_table(meta_split_id=0, path_id=0, n_train=200, n_test=40, seed=1)
    result = meta.run_meta_fold(
        table,
        meta_split_id=0,
        regime_levels=_ORCH_LEVELS,
        random_state=0,
        alpha_model_id="alpha_c1_v1",
        variant="camada1",
        resolution_id="R2",
    )
    assert result.fold_status == mds.META_STATUS_OK
    assert result.tau_meta is not None
    assert result.design_rank is not None and result.design_rank.is_full_rank
    assert result.coefficient_shares is not None
    assert result.test_predictions.height == 40
    assert result.test_predictions["p_meta"].null_count() == 0
    assert set(result.test_predictions["side_final"].unique().to_list()) <= {-1, 0, 1}


def test_run_meta_fold_passthrough_quando_amostra_insuficiente() -> None:
    table = _mk_orchestration_table(meta_split_id=0, path_id=0, n_train=8, n_test=10, seed=2)
    result = meta.run_meta_fold(
        table,
        meta_split_id=0,
        regime_levels=_ORCH_LEVELS,
        random_state=0,
        alpha_model_id="alpha_c1_v1",
        variant="camada1",
        resolution_id="R2",
    )
    assert result.fold_status == mds.META_STATUS_INSUFFICIENT_SAMPLE
    assert result.tau_meta is None
    out = result.test_predictions
    assert out.height == 10
    assert out["p_meta"].null_count() == 10
    assert out["side_final"].to_list() == out["side_hat"].to_list(), "pass-through aceita tudo"


def test_run_meta_fold_passthrough_quando_posto_deficiente() -> None:
    """Achado real (2026-08-31, BTCUSDT/R2, fold real -- não hipotético):
    um fold pequeno pode nunca observar algum nível de regime no treino,
    deixando a dummy correspondente com variância zero e o design matrix
    rank-deficiente -- `check_design_rank` levanta `RankDeficientDesign
    Error`, e `run_meta_fold` precisa converter em pass-through
    (`RANK_DEFICIENT`), não deixar propagar."""
    table = _mk_orchestration_table(meta_split_id=0, path_id=0, n_train=200, n_test=20, seed=13)
    # zera a dummy regime_ohe_S3 inteira no TREINO -- coluna toda-zero é
    # combinação linear trivial (0 * qualquer outra), rank cai em 1.
    table = table.with_columns(
        pl.when(pl.col("role") == mds.ROLE_TRAIN)
        .then(pl.lit(0))
        .otherwise(pl.col(f"{mds.REGIME_OHE_PREFIX}S3"))
        .alias(f"{mds.REGIME_OHE_PREFIX}S3")
    )

    result = meta.run_meta_fold(
        table,
        meta_split_id=0,
        regime_levels=_ORCH_LEVELS,
        random_state=0,
        alpha_model_id="alpha_c1_v1",
        variant="camada1",
        resolution_id="R2",
    )
    assert result.fold_status == mds.META_STATUS_RANK_DEFICIENT
    assert result.tau_meta is None
    assert result.design_rank is None
    out = result.test_predictions
    assert out.height == 20
    assert out["p_meta"].null_count() == 20
    assert out["side_final"].to_list() == out["side_hat"].to_list(), "pass-through aceita tudo"


def test_run_meta_fold_toda_populacao_de_teste_vetada_nao_quebra() -> None:
    """Achado real (2026-08-31, BTCUSDT/R2): um fold pode ter TODA a
    população de teste vetada por regime desconhecido, mesmo com treino
    suficiente -- `sklearn.predict_proba` recusa um array de 0 linhas com
    `ValueError`, não devolve vazio educadamente. O fold ainda ajusta
    modelo (o treino não está vazio), só não há nada pra escorar."""
    treino_only = _mk_orchestration_table(
        meta_split_id=0, path_id=0, n_train=200, n_test=0, seed=11
    )
    teste_todo_vetado = _mk_orchestration_table(
        meta_split_id=0,
        path_id=0,
        n_train=0,
        n_test=8,
        seed=12,
        test_meta_status=mds.META_STATUS_UNSEEN_REGIME,
    )
    table = pl.concat([treino_only, teste_todo_vetado], how="vertical")

    result = meta.run_meta_fold(
        table,
        meta_split_id=0,
        regime_levels=_ORCH_LEVELS,
        random_state=0,
        alpha_model_id="alpha_c1_v1",
        variant="camada1",
        resolution_id="R2",
    )
    assert result.fold_status == mds.META_STATUS_OK  # o treino ajustou modelo
    assert result.tau_meta is not None
    out = result.test_predictions
    assert out.height == 8
    assert out["side_final"].to_list() == [0] * 8
    assert out["p_meta"].null_count() == 8


def test_run_meta_fold_veta_teste_com_regime_desconhecido_mesmo_com_fold_ok() -> None:
    """§6.4/D-05 — vetada INCONDICIONALMENTE, mesmo o fold tendo ajustado
    modelo (amostra de treino suficiente)."""
    ok = _mk_orchestration_table(meta_split_id=0, path_id=0, n_train=200, n_test=20, seed=3)
    vetado = _mk_orchestration_table(
        meta_split_id=0,
        path_id=0,
        n_train=0,
        n_test=5,
        seed=4,
        test_meta_status=mds.META_STATUS_UNSEEN_REGIME,
    )
    table = pl.concat([ok, vetado], how="vertical")

    result = meta.run_meta_fold(
        table,
        meta_split_id=0,
        regime_levels=_ORCH_LEVELS,
        random_state=0,
        alpha_model_id="alpha_c1_v1",
        variant="camada1",
        resolution_id="R2",
    )
    assert result.fold_status == mds.META_STATUS_OK
    out = result.test_predictions
    assert out.height == 25
    vetadas = out.filter(pl.col("meta_status") == mds.META_STATUS_UNSEEN_REGIME)
    assert vetadas.height == 5
    assert vetadas["side_final"].to_list() == [0] * 5
    assert vetadas["p_meta"].null_count() == 5


def test_run_meta_fold_escreve_bundle_quando_dest_dado(tmp_path: Path) -> None:
    table = _mk_orchestration_table(meta_split_id=0, path_id=0, n_train=200, n_test=10, seed=5)
    dest = tmp_path / "fold_0.json"
    result = meta.run_meta_fold(
        table,
        meta_split_id=0,
        regime_levels=_ORCH_LEVELS,
        random_state=0,
        alpha_model_id="alpha_c1_v1",
        variant="camada1",
        resolution_id="R2",
        bundle_dest=dest,
    )
    assert dest.exists()
    payload = meta.read_meta_fold_bundle(dest)
    assert result.tau_meta is not None
    assert payload["tau_meta"] == pytest.approx(result.tau_meta.tau_meta)
    assert payload["alpha_model_id"] == "alpha_c1_v1"
    assert payload["meta_split_id"] == 0
    assert payload["variant"] == "camada1"
    assert payload["resolution_id"] == "R2"


def test_run_meta_fold_sem_dest_nao_escreve_nada(tmp_path: Path) -> None:
    table = _mk_orchestration_table(meta_split_id=0, path_id=0, n_train=200, n_test=10, seed=5)
    meta.run_meta_fold(
        table,
        meta_split_id=0,
        regime_levels=_ORCH_LEVELS,
        random_state=0,
        alpha_model_id="alpha_c1_v1",
        variant="camada1",
        resolution_id="R2",
    )
    assert list(tmp_path.iterdir()) == []


def test_run_meta_fold_meta_split_id_ausente_levanta() -> None:
    table = _mk_orchestration_table(meta_split_id=0, path_id=0, n_train=10, n_test=5, seed=6)
    with pytest.raises(meta.MetaLearnerError, match="sem linhas"):
        meta.run_meta_fold(
            table,
            meta_split_id=99,
            regime_levels=_ORCH_LEVELS,
            random_state=0,
            alpha_model_id="alpha_c1_v1",
            variant="camada1",
            resolution_id="R2",
        )


def test_run_all_meta_folds_roda_cada_meta_split_id() -> None:
    fold0 = _mk_orchestration_table(meta_split_id=0, path_id=0, n_train=200, n_test=20, seed=7)
    fold1 = _mk_orchestration_table(meta_split_id=1, path_id=0, n_train=200, n_test=20, seed=8)
    table = pl.concat([fold0, fold1], how="vertical")
    results = meta.run_all_meta_folds(
        table,
        regime_levels=_ORCH_LEVELS,
        random_state=0,
        alpha_model_id="alpha_c1_v1",
        variant="camada1",
        resolution_id="R2",
    )
    assert len(results) == 2
    assert {r.meta_split_id for r in results} == {0, 1}
    assert all(r.fold_status == mds.META_STATUS_OK for r in results)


def test_run_all_meta_folds_grava_um_bundle_por_fold(tmp_path: Path) -> None:
    fold0 = _mk_orchestration_table(meta_split_id=0, path_id=0, n_train=200, n_test=10, seed=9)
    fold1 = _mk_orchestration_table(meta_split_id=1, path_id=0, n_train=200, n_test=10, seed=10)
    table = pl.concat([fold0, fold1], how="vertical")
    meta.run_all_meta_folds(
        table,
        regime_levels=_ORCH_LEVELS,
        random_state=0,
        alpha_model_id="alpha_c1_v1",
        variant="camada1",
        resolution_id="R2",
        bundle_dir=tmp_path,
    )
    assert (tmp_path / "fold_0.json").exists()
    assert (tmp_path / "fold_1.json").exists()
