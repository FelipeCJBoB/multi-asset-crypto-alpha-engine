"""Learner do Meta-model — F4 de `docs/meta_model_design_doc_2026-08-22.md`
(§3.4 design matrix, §7 learner/D-02, §7.3 guarda de amostra, §7.5 HHI).

**`predict_score`, nunca `predict_proba`** (§7.1). O consumo do v1 é limiar
por quantil in-fold (§8.3) e D-07 removeu o calibrador — o nome não pode
sugerir probabilidade calibrada, porque não é uma. Qualquer transformação
monótona serviria igual; a escolha de devolver a sigmoid é legibilidade,
não uma afirmação de calibração.

**O design matrix (§3.4, hierarquia CORRIGIDA na v3):**

    [score_rank, p_alpha, margin, side_hat, regime_ohe_*]

`score_rank` é o posto de `score_alpha_raw` DENTRO do fold — não o z-score.
A v2 tinha adotado z-score e rebaixado o posto a braço de ablação sem
argumento; a v3 inverteu, e a razão é estrutural: `score_*_raw` já é
`predict_proba(...)[:, 1]`, portanto já vive em `[0,1]` e a escala JÁ é
comparável entre folds. A não-comparabilidade é do **mapeamento
score→P(y)**, que difere por fold porque cada fold treinou um booster
diferente. Z-score é transformação linear: iguala média e variância, não
iguala o mapeamento — mascara, não resolve. O posto é invariante a
qualquer monótona, logo imune tanto ao achatamento isotônico quanto à
heterogeneidade de mapeamento.

**Fora do design matrix, por decisão medida:**
- `regime_tradeable` — `tradeable = decoded_mask & ~is_stress_state` é
  combinação linear EXATA das dummies de regime; incluí-la deixa a matriz
  rank-deficiente. Fica no frame, para estratificação e gate estrutural.
- as features T1 — o Alpha já as viu; incluí-las faz o Meta virar um
  segundo Alpha. Braço de ablação, nunca default.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression

from src.io.artifact import atomic_write_bytes

from . import meta_dataset as mds
from ._constants import load_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

#: Colunas do design matrix que NÃO são dummies de regime, na ordem em que
#: entram na matriz. `side_hat` é o intercepto por lado (§3.4): dentro da
#: subpopulação o sinal de (p_long menos p_short) é o próprio `side_hat`,
#: então um coeficiente
#: único em `spread` imporia efeito de sinal OPOSTO em long e short — quando
#: "margem grande a favor do lado escolhido" deve ser bom nos dois.
DESIGN_BASE_COLUMNS: tuple[str, ...] = ("score_rank", "p_alpha", "margin", "side_hat")

_SERIALIZED_FORMAT = "meta_logit_l2_coef_v1"

# Teto de iteração do lbfgs. NÃO é constante de domínio (não muda nenhuma
# decisão econômica): é critério de parada de um solver determinístico,
# mesma categoria de `_JOINT_TAU_MAX_ITER` em `alpha.py` e de
# `leakage.py::tolerance = 1e-6`. Acima do default 100 do sklearn porque
# `class_weight="balanced"` com pesos amostrais desbalanceados converge mais
# devagar, e um `ConvergenceWarning` silencioso viraria coeficiente errado
# sem ninguém notar.
_LOGIT_MAX_ITER = 1000  # noqa: magic-number


class MetaLearnerError(Exception):
    """Erro de contrato do learner do Meta."""


class MetaLearnerBlockedError(MetaLearnerError):
    """Implementação existe mas está BLOQUEADA na v1 por gate estatístico."""


class InsufficientMetaSampleError(MetaLearnerError):
    """Amostra efetiva abaixo do piso de EPV (§7.3). Falha ALTO — nunca
    degrada em silêncio para um learner mais simples, porque a degradação
    silenciosa é indistinguível de "o desenho funcionou"."""


class RankDeficientDesignError(MetaLearnerError):
    """Bloco categórico do design matrix é rank-deficiente (§3.4)."""


# ---------------------------------------------------------------------------
# Interface (§7.1)
# ---------------------------------------------------------------------------


@runtime_checkable
class MetaLearner(Protocol):
    """D-02 — learner plugável. A interface é deliberadamente estreita: o
    Meta não precisa de `predict_proba`, de `feature_importances_`, nem de
    early stopping. Cada método a mais é uma porta para acoplar o
    orquestrador a um learner específico."""

    def fit(self, X: FloatArray, y: IntArray, w: FloatArray) -> None: ...

    def predict_score(self, X: FloatArray) -> FloatArray: ...

    def coefficient_shares(self) -> dict[str, float]: ...

    def serialize(self, dest: Path) -> None: ...


# ---------------------------------------------------------------------------
# Transformação de score — posto ajustado NO TREINO (B03)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScoreRankTransform:
    """Posto empírico de `score_alpha_raw`, AJUSTADO NO TREINO do fold.

    **Por que não `scipy.stats.rankdata` sobre treino ∪ teste.** O posto
    de uma linha de teste calculado contra a distribuição que a INCLUI é
    função do próprio conjunto de teste — vazamento por construção, e do
    tipo que nenhum teste de `leakage.py` pegaria, porque não há `fit` num
    objeto sklearn para o grep de `_GLOBAL_SCALER_PATTERN` encontrar.

    O que se ajusta no treino é a CDF empírica (os valores de treino
    ordenados); o teste é mapeado através dela por busca binária. Uma
    linha de teste acima de todo o treino recebe 1,0; abaixo de todo,
    0,0. É a mesma disciplina de B03, aplicada a uma transformação que
    não usa nenhuma classe de escalonamento do sklearn — e por isso
    poderia passar despercebida por um grep que procura só por essas
    classes nomeadas (ver `_GLOBAL_SCALER_PATTERN` acima)."""

    sorted_train_values: FloatArray

    @classmethod
    def fit(cls, score_train: FloatArray) -> ScoreRankTransform:
        if score_train.size == 0:
            raise MetaLearnerError(
                "ScoreRankTransform.fit: treino vazio — sem distribuição de "
                "referência não há posto a atribuir."
            )
        return cls(sorted_train_values=np.sort(np.asarray(score_train, dtype=np.float64)))

    def transform(self, score: FloatArray) -> FloatArray:
        n = self.sorted_train_values.shape[0]
        # `side="right"` e divisão por `n`: fração do TREINO que fica <= o
        # valor. Determinístico e monótono, que é tudo que §8.3 exige.
        valores = np.asarray(score, dtype=np.float64)
        pos = np.searchsorted(self.sorted_train_values, valores, side="right")
        return np.asarray(pos / n, dtype=np.float64)


# ---------------------------------------------------------------------------
# Guardas (§7.3, §3.4)
# ---------------------------------------------------------------------------


def assert_sample_sufficient(n_events_eff: float, n_features_effective: int) -> None:
    """§7.3 — piso de EPV sobre a amostra EFETIVA.

    `n_events_eff` é `Σ uniqueness_subpop` da CLASSE MINORITÁRIA no treino
    do fold (B24, medido) — não a contagem bruta de linhas. Contar linhas
    numa população com rótulos sobrepostos superestima a informação
    disponível, que é exatamente o que `uniqueness` existe para corrigir.

    `n_features_effective` é recalculado POR FOLD: o número de colunas muda
    com descarte de dummy e colinearidade (§6.4), e usar um número fixo
    tornaria a guarda mais frouxa justamente nos folds mais degenerados.

    Falha ALTO. O consumidor traduz para `meta_status =
    INSUFFICIENT_SAMPLE` e política de PASS-THROUGH (§7.3): vetar tudo por
    escassez de amostra do FILTRO mataria a estratégia por um problema do
    acessório."""
    epv = float(load_constant("meta_min_events_per_variable"))
    piso = epv * n_features_effective
    if n_events_eff < piso:
        raise InsufficientMetaSampleError(
            f"§7.3: n_events_eff={n_events_eff:.2f} (Σ uniqueness_subpop da classe "
            f"minoritária) abaixo do piso {piso:.2f} = EPV {epv:g} vezes "
            f"{n_features_effective} colunas efetivas. O fold NÃO ajusta modelo; "
            "política declarada é pass-through (accept=True, p_meta=null) com WARNING, "
            "nunca veto — e nunca degradar em silêncio para um learner mais simples."
        )


@dataclass(frozen=True, slots=True)
class DesignRankDiagnostic:
    """§3.4 — substitui a guarda de "variância zero" da v1, que era
    insuficiente: variância zero não pega COLINEARIDADE. `regime_tradeable`
    é o caso arquetípico — variância alta, e ainda assim combinação linear
    exata das dummies."""

    n_columns: int
    matrix_rank: int
    condition_number: float
    is_full_rank: bool


def check_design_rank(X: FloatArray, *, column_names: tuple[str, ...]) -> DesignRankDiagnostic:
    """Posto e número de condição do design matrix, registrados por fold."""
    if X.ndim != 2:
        raise MetaLearnerError(f"check_design_rank: X precisa ser 2D, recebido shape={X.shape}")
    rank = int(np.linalg.matrix_rank(X))
    n_cols = int(X.shape[1])
    # `cond` de matriz rank-deficiente é `inf` — é o valor honesto, não um
    # erro a mascarar.
    with np.errstate(divide="ignore", invalid="ignore"):
        cond = float(np.linalg.cond(X))
    diag = DesignRankDiagnostic(
        n_columns=n_cols,
        matrix_rank=rank,
        condition_number=cond,
        is_full_rank=rank == n_cols,
    )
    if not diag.is_full_rank:
        raise RankDeficientDesignError(
            f"§3.4: design matrix rank-deficiente — rank={rank} de {n_cols} colunas "
            f"({column_names}), número de condição {cond:.3e}. Causa mais provável: uma "
            "coluna é combinação linear exata das dummies de regime (foi assim que "
            "`regime_tradeable` foi excluída do design matrix). A guarda de variância "
            "zero NÃO pega este caso."
        )
    return diag


# ---------------------------------------------------------------------------
# Implementações (§7.2)
# ---------------------------------------------------------------------------


class LogitL2Meta:
    """Default e ÚNICO learner habilitado abaixo do gate de §7.3 (D-02).

    **`class_weight="balanced"` E `sample_weight`, os dois** — herda o
    padrão do Alpha, que trata os dois como ortogonais e não substitutos
    (`scale_pos_weight` mais `sample_weight` de unicidade).

    Nota que só existe porque o §5 foi corrigido em 2026-08-30: enquanto
    `meta_sample_weight` era `uniqueness × |ret_net|`, ele carregava um
    peso de classe implícito de 1,61:1 — e `class_weight="balanced"`
    estaria compondo com um viés não declarado, sem que nada no pipeline
    percebesse. Com o peso corrigido para `uniqueness × atr_at_t0` (razão
    de classe medida em 1,0026), `balanced` faz exatamente e só o que
    promete."""

    def __init__(self, *, random_state: int) -> None:
        self._c = float(load_constant("meta_logit_c"))
        self._random_state = random_state
        self._model: LogisticRegression | None = None
        self._column_names: tuple[str, ...] = ()

    def fit(self, X: FloatArray, y: IntArray, w: FloatArray) -> None:
        # DESVIO DELIBERADO da grafia literal do §7.2, que escreve
        # `LogisticRegression(penalty="l2", ...)`. Medido em 2026-08-30:
        # `scikit-learn` 1.9.0 deprecou `penalty` (o default virou o
        # sentinela `"deprecated"`) e será REMOVIDO em 1.10 — seguir o
        # documento ao pé da letra emite `FutureWarning` hoje e quebra
        # amanhã. A grafia nova de L2 é `l1_ratio=0.0`.
        #
        # Portável nos dois regimes, que é por que ela é explícita e não
        # omitida: em `scikit-learn` 1.5 (o piso de `pyproject.toml`)
        # `l1_ratio` só é lido sob `penalty="elasticnet"` e é ignorado aqui,
        # com o default `penalty="l2"` valendo; em 1.9+ `l1_ratio=0.0` É a
        # declaração de L2. Nos dois casos a penalidade efetiva é L2.
        model = LogisticRegression(
            C=self._c,
            l1_ratio=0.0,
            solver="lbfgs",
            class_weight="balanced",
            random_state=self._random_state,
            max_iter=_LOGIT_MAX_ITER,
        )
        model.fit(X, y, sample_weight=w)
        self._model = model

    def bind_column_names(self, column_names: tuple[str, ...]) -> None:
        """Nomes só para diagnóstico (`coefficient_shares`) — o `fit` opera
        sobre array puro de propósito, para que a ordem das colunas seja
        responsabilidade de UM lugar só (o montador do design matrix)."""
        self._column_names = column_names

    def _fitted(self) -> LogisticRegression:
        if self._model is None:
            raise MetaLearnerError("LogitL2Meta: `fit` não foi chamado.")
        return self._model

    def predict_score(self, X: FloatArray) -> FloatArray:
        proba = self._fitted().predict_proba(X)[:, 1]
        return np.asarray(proba, dtype=np.float64)

    def coefficient_shares(self) -> dict[str, float]:
        """§7.5 — share de |coeficiente|, para o diagnóstico de concentração.

        **O gate de HHI do DoD NÃO se aplica aqui na forma herdada do
        Alpha**, e isso é decisão declarada, não omissão. D-01 afirma que
        regime é A vantagem informacional: o desenho ESPERA que regime
        domine. Se dominar o suficiente para o Meta ter valor,
        `max_share > 0,30` e o DoD reprova; se o DoD passar, é evidência
        CONTRA D-01. Um gate que só pode ser satisfeito quando a hipótese
        central falha é pior que nenhum gate — seria afrouxado na hora de
        aplicar, que é `AG-114` acontecendo de novo.

        Substituído por diagnóstico com semântica própria: share de regime
        contra share de `p_alpha`/`score_rank`/`margin`, REPORTADO SEM
        LIMIAR (B23 impede inventar um)."""
        coef = np.abs(self._fitted().coef_[0]).astype(np.float64)
        total = float(coef.sum())
        nomes = self._column_names or tuple(f"col_{i}" for i in range(coef.size))
        if total <= 0.0:
            return dict.fromkeys(nomes, 0.0)
        return {nome: float(c / total) for nome, c in zip(nomes, coef, strict=True)}

    def _payload(self) -> dict[str, Any]:
        """Núcleo puro da serialização — sem IO, reusado por `serialize`
        (artefato isolado) e por `write_meta_fold_bundle` (F5, junta com
        `tau_meta`/linhagem num único arquivo atômico). Extraído pelo
        mesmo motivo estrutural de sempre neste repo: duas cópias do
        mesmo dicionário divergiriam em silêncio."""
        model = self._fitted()
        return {
            "format": _SERIALIZED_FORMAT,
            "coef": [float(v) for v in model.coef_[0]],
            "intercept": float(model.intercept_[0]),
            "column_names": list(self._column_names),
            "meta_logit_c": self._c,
            "random_state": self._random_state,
            # Sem campo de calibrador: D-07, o v1 não tem um. A ausência é
            # declarada para que ninguém procure por um que nunca existiu.
            "calibrator": None,
        }

    def serialize(self, dest: Path) -> None:
        """D-17/§14.4 — sem `pickle`/`joblib` do objeto sklearn.

        Persiste `coef_`/`intercept_` como JSON: a inferência ao vivo é um
        produto escalar mais uma sigmoid, e não precisa de sklearn no
        runtime. Mesma disciplina que `persistence.py` já provou bit-exata
        para o calibrador isotônico do Alpha (arrays crus mais `np.interp`,
        nunca o objeto serializado)."""
        blob = json.dumps(self._payload(), indent=2, sort_keys=True).encode("utf-8")
        atomic_write_bytes(dest, blob)


class BlockedGBMMeta:
    """LightGBM para o Meta — BLOQUEADO na v1 (D-02).

    `fit` levanta incondicionalmente. Não é um placeholder: é o gate de
    §7.3 materializado num objeto que falha, em vez de num comentário que
    alguém pode não ler. A evidência que sustenta a logística como DEFAULT
    (não como concessão) é que boosting exige amostra 2-3 vezes maior para o
    mesmo erro de calibração sob EPV limitado, e só supera logística em
    confiabilidade acima de `n > 10⁴` — números que o §17 do design doc
    registra como PENDÊNCIA DE PROVENIÊNCIA, não como fato estabelecido.

    Contra nós, e registrado: AFML §6.6 prefere bagging a boosting em
    finanças. Se o gate abrir, `RandomForest` com
    `max_samples = unicidade média` é mais defensável pelo cânone que
    LightGBM. Nota para o Manager, não decisão tomada aqui."""

    def fit(self, X: FloatArray, y: IntArray, w: FloatArray) -> None:
        raise MetaLearnerBlockedError(
            "BlockedGBMMeta está bloqueado na v1 (D-02/§7.2). O gate depende de "
            "`meta_min_neff_for_gbm`, que permanece TBD — medido em F2 apenas o "
            "`n_eff_subpop` (mediana 652,54 por meta-fold em BTCUSDT/R1), sem limiar "
            "declarado a priori para decidir GBM vs. logística. Inventar o limiar aqui "
            "seria criar o gate sem definição operacional que AG-114/AG-122 registram "
            "como modo de falha. `LogitL2Meta` é o único habilitado."
        )

    def predict_score(self, X: FloatArray) -> FloatArray:
        raise MetaLearnerBlockedError("BlockedGBMMeta está bloqueado na v1 (D-02).")

    def coefficient_shares(self) -> dict[str, float]:
        raise MetaLearnerBlockedError("BlockedGBMMeta está bloqueado na v1 (D-02).")

    def serialize(self, dest: Path) -> None:
        raise MetaLearnerBlockedError("BlockedGBMMeta está bloqueado na v1 (D-02).")


# ---------------------------------------------------------------------------
# Montagem do design matrix
# ---------------------------------------------------------------------------


def design_columns_for(regime_levels: tuple[str, ...]) -> tuple[str, ...]:
    """Ordem canônica das colunas (§3.4). Drop-first: o primeiro nível de
    regime é a referência e NÃO ganha dummy."""
    return (
        *DESIGN_BASE_COLUMNS,
        *(f"{mds.REGIME_OHE_PREFIX}{nivel}" for nivel in regime_levels[1:]),
    )


def build_design_matrix(
    train: pl.DataFrame,
    test: pl.DataFrame,
    *,
    regime_levels: tuple[str, ...],
) -> tuple[FloatArray, FloatArray, tuple[str, ...], DesignRankDiagnostic]:
    """Monta `(X_train, X_test, nomes, diagnóstico de posto)`.

    Recebe treino e teste JUNTOS de propósito — não para misturá-los, e sim
    porque a transformação de posto precisa ser AJUSTADA no treino e
    APLICADA ao teste, e separar as duas chamadas deixaria o ponto de
    ajuste implícito no chamador. Aqui ele é explícito e testável.

    `assert_design_matrix_is_clean` roda sobre os nomes antes de qualquer
    coisa: mesma disciplina de `DESIGN_COLUMNS` no Alpha."""
    nomes = design_columns_for(regime_levels)
    mds.assert_design_matrix_is_clean(nomes)

    faltando = sorted(set(nomes) - set(train.columns) - {"score_rank"})
    if faltando:
        raise MetaLearnerError(
            f"build_design_matrix: colunas ausentes no frame: {faltando}. O frame "
            "precisa vir de `meta_dataset.build_meta_signal_table`."
        )

    rank_tf = ScoreRankTransform.fit(train["score_alpha_raw"].to_numpy().astype(np.float64))
    train_ranked = train.with_columns(
        score_rank=pl.Series(rank_tf.transform(train["score_alpha_raw"].to_numpy()))
    )
    test_ranked = test.with_columns(
        score_rank=pl.Series(rank_tf.transform(test["score_alpha_raw"].to_numpy()))
    )

    x_train = train_ranked.select(list(nomes)).to_numpy().astype(np.float64)
    x_test = test_ranked.select(list(nomes)).to_numpy().astype(np.float64)
    diag = check_design_rank(x_train, column_names=nomes)
    logger.info(
        "models.meta.design_matrix",
        n_colunas=diag.n_columns,
        matrix_rank=diag.matrix_rank,
        condition_number=diag.condition_number,
        n_train=int(x_train.shape[0]),
        n_test=int(x_test.shape[0]),
        colunas=nomes,
    )
    return x_train, x_test, nomes, diag


def n_events_effective(train: pl.DataFrame) -> float:
    """§7.3 — `Σ uniqueness_subpop` da CLASSE MINORITÁRIA no treino.

    Minoritária pela soma de unicidade, não pela contagem de linhas: com
    rótulos sobrepostos as duas podem discordar, e é a informação efetiva
    que limita o que o modelo pode aprender."""
    treinaveis = train.filter(pl.col("y_meta").is_not_null())
    if treinaveis.height == 0:
        return 0.0
    por_classe = treinaveis.group_by("y_meta").agg(n_eff=pl.col("uniqueness_subpop").sum())
    minimo = por_classe["n_eff"].min()
    return 0.0 if minimo is None else float(minimo)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# F5 — tau_meta in-fold (§8.3) + serialização com linhagem (D-17)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TauMetaResolution:
    """Resultado de `resolve_tau_meta` — o quantil escolhido e o rastro
    completo da grade, para que a decisão seja auditável, não só o número
    final. `pnl_by_quantile`/`pass_rate_by_quantile` saem alinhados a
    `quantile_grid`, na mesma ordem."""

    tau_meta: float
    quantile_chosen: float
    quantile_grid: tuple[float, ...]
    pnl_by_quantile: tuple[float, ...]
    pass_rate_by_quantile: tuple[float, ...]
    tie_broken: bool


def resolve_tau_meta(
    scores_train: FloatArray,
    ret_net_train: FloatArray,
    *,
    quantile_grid: Sequence[float] | None = None,
    tie_epsilon: float | None = None,
) -> TauMetaResolution:
    """§8.3 — `tau_meta` é o quantil da distribuição de `p_meta` do PRÓPRIO
    TREINO do fold (mesmo mecanismo do Alpha, `alpha.py::resolve_joint_tau`)
    que MAXIMIZA a PnL líquida in-fold do subconjunto aceito
    (`scores_train >= tau`), com empate decidido pelo MENOR pass-rate.

    **Por que quantil, e não um valor absoluto de score.** Quantil é
    invariante a transformação monótona (§8.3) — calibrar `p_meta` depois
    não mudaria o conjunto aceito, então a superfície de vazamento B08 sai
    do escopo por construção, não por disciplina de quem implementa.

    **Restrição do contrato, herdada do §8.3 e não resolvida aqui.** A
    invariância acima vale para UMA transformação monótona por fold. Sob
    `path_matched`, `p_alpha` no mesmo treino vem de até 5 isotônicas
    diferentes (uma por doador) — a MISTURA de monótonas distintas não é
    ela própria monótona. Este contrato é aproximado, não exato, sob
    doadores múltiplos; registrado como limitação conhecida, não como
    "resolvido por invariância" indevidamente generalizado.

    **Correção da v1 sobre o epsilon de empate.** `1e-6` sobre PnL somada
    (fração de equity) nunca dispara — reduz a regra a argmax puro e apaga
    a preferência estrutural que a cláusula de empate existe para expressar
    (menos trades, R3 folgado, contra o otimismo do argmax sobre ruído
    in-fold). O `tie_epsilon` correto é o PnL de UM trade médio: o custo de
    round-trip (`meta_tau_tie_epsilon`, `config/constants.yaml`, `DERIVED`
    de `round_trip_cost_bps_maker_prob`) — "empate" passa a significar
    literalmente "a diferença de PnL não paga nem um trade a mais".

    `ret_net_train` já vem projetado no lado (mesma convenção de `y_meta`,
    `meta_dataset.py`) — não multiplicar por `side_hat` de novo.

    Levanta se `scores_train`/`ret_net_train` tiverem tamanhos diferentes
    ou se a grade estiver vazia — as duas são falhas de contrato do
    chamador, não casos degenerados do fold (esses são "todo quantil dá
    pass-rate zero", que a função trata sem levantar, ver abaixo)."""
    grid_source = (
        quantile_grid
        if quantile_grid is not None
        else load_constant("meta_tau_grid_quantiles")
    )
    grid = tuple(float(q) for q in grid_source)
    eps = float(tie_epsilon if tie_epsilon is not None else load_constant("meta_tau_tie_epsilon"))
    if scores_train.shape != ret_net_train.shape:
        raise MetaLearnerError(
            f"resolve_tau_meta: scores_train.shape={scores_train.shape} != "
            f"ret_net_train.shape={ret_net_train.shape}"
        )
    if len(grid) == 0:
        raise MetaLearnerError("resolve_tau_meta: quantile_grid vazia — nada para escolher.")

    taus = [float(np.quantile(scores_train, q)) for q in grid]
    pnl_by_q: list[float] = []
    pass_rate_by_q: list[float] = []
    n = scores_train.shape[0]
    for tau in taus:
        aceito = scores_train >= tau
        pnl_by_q.append(float(ret_net_train[aceito].sum()) if n > 0 else 0.0)
        pass_rate_by_q.append(float(aceito.sum()) / n if n > 0 else 0.0)

    pnl_arr = np.asarray(pnl_by_q, dtype=np.float64)
    melhor_pnl = float(pnl_arr.max())
    # Empate: todo quantil cuja PnL fica a menos de `eps` do melhor. Com
    # eps=0 (grade degenerada/teste) isto se reduz ao empate exato --
    # nunca produz lista vazia, porque o próprio melhor sempre entra.
    empatados = [i for i, pnl in enumerate(pnl_by_q) if (melhor_pnl - pnl) <= eps]
    escolhido = min(empatados, key=lambda i: pass_rate_by_q[i])
    tie_broken = len(empatados) > 1

    logger.info(
        "models.meta.resolve_tau_meta",
        quantile_grid=grid,
        quantile_chosen=grid[escolhido],
        tau_meta=taus[escolhido],
        pnl_by_quantile=pnl_by_q,
        pass_rate_by_quantile=pass_rate_by_q,
        tie_epsilon=eps,
        n_empatados=len(empatados),
        tie_broken=tie_broken,
    )
    return TauMetaResolution(
        tau_meta=taus[escolhido],
        quantile_chosen=grid[escolhido],
        quantile_grid=grid,
        pnl_by_quantile=tuple(pnl_by_q),
        pass_rate_by_quantile=tuple(pass_rate_by_q),
        tie_broken=tie_broken,
    )


def apply_meta_filter(side_hat: IntArray, p_meta: FloatArray, *, tau_meta: float) -> IntArray:
    """§8.1/§8.2 — `side_final = side_hat` se `p_meta >= tau_meta`, senão 0.

    **Veto-em-zero, contra AFML §10.3 (D-05).** O snippet do livro usa
    `m = side · (2Φ(z) − 1)`; com `p < 0,5` isso pode dar `m < 0`, e
    `side · m` INVERTE o lado — contradizendo o próprio §3.6 do mesmo
    livro. Em meta-labeling `p = P(o primário acertou)`; `p < 0,5`
    significa "não aposte", nunca "aposte ao contrário". Esta função não
    tem nenhum caminho que produza um valor de sinal diferente de
    `side_hat` ou `0` — é a garantia estrutural, não um teste que poderia
    ser esquecido."""
    if side_hat.shape != p_meta.shape:
        raise MetaLearnerError(
            f"apply_meta_filter: side_hat.shape={side_hat.shape} != p_meta.shape={p_meta.shape}"
        )
    aceito = p_meta >= tau_meta
    return np.where(aceito, side_hat, 0).astype(np.int8)


def write_meta_fold_bundle(
    learner: LogitL2Meta,
    dest: Path,
    *,
    tau_meta: float,
    alpha_model_id: str,
    meta_split_id: int,
    variant: str,
    resolution_id: str,
) -> None:
    """D-17/§14.4 — junta o learner serializado com `tau_meta` e a
    linhagem num ÚNICO artefato, escrito atomicamente.

    **Por que um arquivo só, não dois.** `tau_meta` e o learner só fazem
    sentido JUNTOS na inferência (`apply_meta_filter` precisa dos dois) —
    escrevê-los em dois arquivos separados abriria uma janela onde um
    existe e o outro não (processo morto no meio, disco cheio), e um
    consumidor poderia carregar um par inconsistente sem erro nenhum.

    **Linhagem, não enforcement.** `alpha_model_id`/`resolution_id`
    persistidos aqui são só DADO — a checagem de coerência ("este Meta foi
    treinado sobre ESTE Alpha") é trabalho de F7 (§10, teste #10/#11
    estendido), que lê este campo mas não é escrita por esta função. F5
    persiste; F7 verifica."""
    payload = {
        **learner._payload(),  # mesmo módulo -- LogitL2Meta é definida logo acima
        "tau_meta": float(tau_meta),
        "alpha_model_id": alpha_model_id,
        "meta_split_id": int(meta_split_id),
        "variant": variant,
        "resolution_id": resolution_id,
    }
    atomic_write_bytes(dest, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))


def read_meta_fold_bundle(src: Path) -> dict[str, Any]:
    """Contraparte de leitura de `write_meta_fold_bundle` — só desserializa,
    não reconstrói `LogitL2Meta` (a inferência ao vivo faz o produto
    escalar direto sobre `coef`/`intercept`, sem sklearn no runtime, mesma
    disciplina provada para o calibrador isotônico do Alpha)."""
    payload: dict[str, Any] = json.loads(src.read_text(encoding="utf-8"))
    campos_obrigatorios = {
        "format", "coef", "intercept", "column_names", "tau_meta", "alpha_model_id",
    }
    faltando = sorted(campos_obrigatorios - set(payload))
    if faltando:
        raise MetaLearnerError(
            f"read_meta_fold_bundle: {src} não tem {faltando} -- bundle incompleto."
        )
    return payload


def score_from_bundle(payload: dict[str, Any], X: FloatArray) -> FloatArray:
    """Reconstrução SEM sklearn: produto escalar mais sigmoid, a partir do
    payload de `write_meta_fold_bundle`/`read_meta_fold_bundle`. É a mesma
    conta que `LogitL2Meta.predict_score` faz via `predict_proba` — esta
    versão é a que roda em produção, sem carregar o objeto sklearn."""
    coef = np.asarray(payload["coef"], dtype=np.float64)
    intercept = float(payload["intercept"])
    z = X @ coef + intercept
    return np.asarray(1.0 / (1.0 + np.exp(-z)), dtype=np.float64)
