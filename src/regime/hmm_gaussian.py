"""HMM gaussiano (`dynamax.GaussianHMM`) — M4 (`PRD_V4_1.md` §3.2), candidato
k=2/3/4. Núcleo puro, sem IO, mesmo estilo de `src/regime/bocpd.py`: expõe
`fit_hmm_gaussian`/`predict_hmm_gaussian` como funções puras com params
explícitos — não decide orquestração de fold (isso é do harness, Fase 3,
fora do escopo deste módulo). Cada `n_states` é um trial separado (k=2, k=3,
k=4 são 3 chamadas distintas desta função, não um objeto parametrizável em
lote).

**Correção-relâmpago via ponto de injeção (2026-08-24, achado de varredura
de `tools/lint/banned_patterns.py`)**: `num_em_iters`/`sticky_concentration`
eram literais hardcoded (`_DEFAULT_NUM_EM_ITERS=100`, `_DEFAULT_
STICKY_CONCENTRATION=10.0`), invisíveis a `constants.yaml`/governança de
proveniência (o `int` nem era verificado pelo lint até esta rodada — só o
`float` tinha `# noqa: magic-number`). `src.regime.build_hmm.
build_hmm_regimes` (builder de produção do candidato canônico
`hmm_gaussian_k4_v1`) chama `fit_hmm_gaussian` SEM passar nenhum dos dois —
os 2 defaults deste módulo são, de fato, o que roda em produção hoje
(confirmado por leitura direta de `build_hmm.py`, não suposto). Registrados
em `config/constants.yaml` (`hmm_gaussian_sticky_concentration_default`/
`hmm_gaussian_num_em_iters`, `provenance: ASSUMED`, `class: B`) com os
MESMOS valores (10.0/100) -- esta rodada é fiação/governança, não
recalibração.

Resolvidos via `ponto de injeção`, não como default literal do parâmetro
(mesmo padrão do §"Núcleo funcional, casca imperativa" do `CLAUDE.md`):
`sticky_concentration`/`num_em_iters` continuam `| None = None`, e só
chamam `load_regime_constant(...)` (IO real, leitura de
`config/constants.yaml`) DENTRO do corpo da função, no ramo tomado quando o
chamador omite o parâmetro. Chamador que passa valor explícito (todo teste
de `tests/unit/test_regime_hmm_gaussian.py` exceto o smoke test dedicado,
qualquer sweep/trial do harness Fase 3) nunca toca disco — a alternativa
óbvia (`num_em_iters: int = load_regime_constant(...)` como default literal
do parâmetro, avaliado 1x na DEFINIÇÃO da função, ou seja no IMPORT do
módulo) foi descartada de propósito: isso tornaria TODO import deste
módulo uma operação de IO, quebrando a alegação "núcleo puro, sem IO" do
parágrafo acima de um jeito que nenhum outro módulo de `src/` faz hoje
(confirmado: nenhum módulo em `src/` atribui `load_constant(...)` direto a
uma constante de nível de módulo -- todo uso existente é dentro de função/
classmethod, chamado sob demanda pela casca). O resultado aqui é HÍBRIDO,
não puro de verdade -- honesto sobre isso, não overclaim: `fit_hmm_gaussian`
só evita IO se o chamador injetar o valor; no caminho default (produção
real, via `build_hmm.py`) ela toca disco, uma vez por chamada, igual a
qualquer outra função deste pacote que já lê `constants.yaml` sob demanda
(`classifier.py::RegimeThresholds.from_constants`, `stress.py`).

**API real do `dynamax` confirmada nesta sessão (2026-08-17), não citada de
memória** — ver `.venv/Lib/site-packages/dynamax/hidden_markov_model/`:

- `GaussianHMM(num_states, emission_dim, transition_matrix_stickiness=k)`:
  o prior STICKY pedido pelo plano tem API NATIVA — não precisou de
  pós-processamento manual da matriz de transição. `transition_matrix_
  stickiness` soma `k * eye(K)` à concentração de Dirichlet de cada linha
  da matriz de transição (`StandardHMMTransitions.__init__`,
  `dynamax/hidden_markov_model/models/transitions.py`): `A_k ~
  Dir(beta*1_K + kappa*e_k)` — literalmente o "prior de Dirichlet
  enviesado pra auto-transição" que o plano pediu, sem precisar inventar
  API que não existe.
- `hmm.initialize(key, method=..., emissions=...) -> (params, props)`,
  `hmm.fit_em(params, props, obs, num_iters=N, verbose=...) -> (params,
  log_probs)`, `hmm.filter(params, obs) -> HMMPosteriorFiltered`.
- `HMMPosteriorFiltered` (`dynamax/hidden_markov_model/inference.py`) tem
  EXATAMENTE 3 campos: `marginal_loglik`, `filtered_probs` (shape
  `(T, n_states)`, `p(z_t | y_{1:t})` — causal, é o que este módulo usa),
  `predicted_probs` (shape `(T, n_states)`, `p(z_t | y_{1:t-1})`). **Não
  existe `.count`/`.index`** (a instrução original especulava isso como
  "provavelmente" — checado direto no source, não existe; não inventado
  aqui).

**Achado real #1 (2026-08-17, medido): `GaussianHMM.initialize(...,
method="kmeans")` inicializa a covariância de TODO estado como matriz
IDENTIDADE (`GaussianHMMEmissions.initialize`,
`dynamax/hidden_markov_model/models/gaussian_hmm.py`, ramo `kmeans`:
`_emission_covs = jnp.tile(jnp.eye(emission_dim)[None], (num_states,1,1))`),
**independente da escala real do dado**.** Para o espaço de entrada real do
M4 (`[log_return_1, realized_vol_short]`, magnitude típica de retorno de
dollar-bar cripto ~1e-3 a 1e-4, variância ~1e-6 a 1e-8) isso é
catastrófico: a covariância inicial (escala 1.0) fica 6-8 ordens de
grandeza mais larga que a dispersão real dos dois clusters, então a
responsabilidade do E-step na primeira iteração é quase uniforme entre
estados (todo ponto plausível sob qualquer média a essa largura) e o EM
converge pra um ótimo local degenerado. Medido diretamente: dado sintético
2 clusters bem separados (`N(-5e-4, 1e-4)` vs `N(+5e-4, 1e-4)`, 400 pontos)
com inicialização kmeans padrão do dynamax dá **Rand ajustado = 0.0**
(nenhuma separação) — o mesmíssimo dado em escala unitária (`N(-1, 0.1)`
vs `N(1, 0.1)`) dá ARI = 1.0 com o mesmo código. Não é falta de sinal no
dado, é descalibração do prior de covariância inicial — mesma classe de
bug do achado do BOCPD nesta sessão (prior calibrado pra escala unitária,
aplicado sem ajuste a dado de escala real). **Fix aplicado**: usa
`method="kmeans"` só pelas MÉDIAS (centróides do k-means, robustos à
escala), mas substitui a covariância inicial pela covariância EMPÍRICA do
`obs` de treino (`_scale_aware_init_covariance`), escala correta por
construção. Confirmado que o fix resolve o caso sintético de escala real
(ARI 0.0 -> 0.98) sem quebrar o caso de escala unitária (ARI 1.0 mantido).
Achado válido para `dynamax==0.1.5` (versão fixada em `pyproject.toml`);
se a lib for atualizada, revalidar.

**`jax_enable_x64`**: habilitado neste módulo porque o resto do projeto
usa `float64` em todo lugar (`FloatArray = NDArray[np.float64]` em quase
todo módulo de `src/`) e o default do JAX é `float32` — decisão
INDEPENDENTE do achado #1 acima (o bug de covariância acontece nas duas
precisões, não é causado por float32; confirmado rodando o caso de escala
real já com x64 ligado e ainda assim ARI=0.0 antes do fix de covariância).
Habilitar x64 aqui é sobre consistência de precisão com o resto do repo
para as magnitudes pequenas de `log_return_1` (variância ~1e-8, perto do
piso de precisão relativa do float32), não sobre o bug em si. É uma flag
GLOBAL do processo JAX (`jax.config.update`, não escopada a este módulo) —
checado nesta sessão (2026-08-17) que este é hoje o único consumidor de
`jax`/`dynamax` no repo: `src/regime/jump_model.py` (Fase 2 do mesmo
plano, já escrito) usa a lib `jumpmodels` (`from jumpmodels.jump import
JumpModel`), sklearn-style, não importa `jax` em nenhum lugar — não há
conflito de inicialização dupla do backend JAX conhecido nesta sessão —
mas se um módulo futuro também consumir `jax` e rodar uma computação
ANTES deste import, revisar (JAX avisa/pode se comportar de forma
inesperada se `jax_enable_x64` for setado depois do backend já
inicializado).

**Contrato de fold (não decidido aqui, só implementado)**: `fit_hmm_gaussian`
ajusta (`fit_em`) só sobre `obs[:train_end_idx]` — expansivo, ancorado,
igual ao resto do M4 (`B05`/`CLAUDE.md`, "reajustar por fold com purge").
`predict_hmm_gaussian` decodifica o `obs` COMPLETO que recebe — quem chama
(harness, Fase 3) é responsável por só usar a fatia do fold de teste; este
módulo não sabe de fold.

**Canonicalização ancorada no FIT, não no `obs` de `predict_hmm_gaussian`**
— decisão de design não trivial, resolvida aqui, documentada (não
escondida): `predict_hmm_gaussian` reusa `canonicalize_states` de verdade
(`src.regime.canonicalization`), mas com `response` = a média AJUSTADA de
`log_return_1` por estado (`fit.params.emissions.means[:, 0]`, um valor
por estado, direto do parâmetro do modelo), não a média EMPÍRICA das
barras de `obs` decodificadas em `predict_hmm_gaussian`. Dois motivos
medidos, não hipotéticos:

1. **Mapping sempre completo.** Com `n_states` fixo, a matriz de médias
   ajustadas tem exatamente uma entrada por estado, sempre. Ordenar pelas
   barras DECODIFICADAS de `obs` (`canonicalize_states(raw_state_id,
   obs[:, 0])`) quebra se algum estado nunca for o argmax em nenhuma barra
   da fatia passada (plausível em folds de teste curtos ou k=4 com um
   estado raro) — `canonicalize_states` levanta `ValueError` nesse caso
   ("nenhum estado real"), ou pior, deixa um raw id sem entrada no
   `mapping` se SÓ ALGUNS estados sumirem (não todos).
2. **Causal de ponta a ponta.** Com a média ajustada (calculada 100% a
   partir de `obs[:train_end_idx]`, nunca do `obs` passado pra
   `predict_hmm_gaussian`), o `canonical_id` de saída é garantidamente
   causal — testado diretamente (`test_causalidade_perturbar_futuro_nao_
   muda_passado`, mesmo padrão de `test_regime_bocpd.py`): perturbar
   `obs[t+1:]` não muda `canonical_id[:t+1]`, ponta a ponta, sem ressalva.
   Ordenar pela média EMPÍRICA do `obs` decodificado em `predict_hmm_
   gaussian` quebraria isso — a média de um estado sobre o fold de teste
   pode depender de quanto do fold já foi observado, então o MAPEAMENTO
   raw->canonical (não o estado bruto em si) poderia mudar retroativamente
   se mais teste for revelado depois. `BOCPD.segments_to_canonical_states`
   não tem essa opção (não existe parâmetro ajustado equivalente a "média
   por segmento" — segmento é descoberto, não paramétrico); para o HMM
   gaussiano, a média ajustada por estado JÁ EXISTE como parâmetro do
   modelo e é estritamente melhor pra este propósito.

Continua sendo uma chamada real de `canonicalize_states` (não duplica o
critério média-ascendente/desempate-por-variância) — só escolhe QUAL
"resposta" alimentar de um jeito que é ao mesmo tempo mais robusto (nunca
falta estado) e mais correto (causal)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jax.numpy as jnp
import numpy as np
import structlog
from dynamax.hidden_markov_model import GaussianHMM
from jax import config as jax_config
from jax import random as jax_random
from jax import tree_util as jax_tree_util
from numpy.typing import NDArray

from ._constants import load_constant as load_regime_constant
from .canonicalization import canonicalize_states

# Ver docstring do módulo, seção "jax_enable_x64" -- consistência de
# precisão com o resto do repo (float64 em todo `src/`), decisão
# independente do achado #1 (bug de covariância inicial). `jax.config`
# não publica stubs de tipo pra `update` (mypy vê como função não anotada).
jax_config.update("jax_enable_x64", True)  # type: ignore[no-untyped-call]

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
# Mesmo tipo estrutural de FloatArray -- numpy.typing não carrega shape no
# sistema de tipos, o nome distinto só documenta a forma esperada (T,
# emission_dim), contrato de `fit_hmm_gaussian`/`predict_hmm_gaussian`.
Float2DArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

# Nomes das entradas em `config/constants.yaml` -- única fonte do literal
# (mesmo padrão de `_CLASSIFIER_ID_TEMPLATE` logo abaixo: 1 constante de
# nome, nunca a string duplicada em mais de 1 lugar). Resolvidos via `load_
# regime_constant` DENTRO de `fit_hmm_gaussian`, não aqui em nível de
# módulo -- ver "Correção-relâmpago via ponto de injeção" no docstring do
# módulo pra por que (import deste módulo não pode virar IO).
_NUM_EM_ITERS_CONSTANT_NAME = "hmm_gaussian_num_em_iters"
_STICKY_CONCENTRATION_CONSTANT_NAME = "hmm_gaussian_sticky_concentration_default"
# Piso de regularização da covariância inicial (ver achado #1 no docstring
# do módulo) -- mesmo estilo de piso de estabilidade numérica de
# `bocpd.py` (`max(var, 1e-12)`), evita covariância inicial exatamente
# singular se `obs` de treino tiver pontos idênticos/degenerados.
_INIT_COV_EPSILON: float = 1e-12  # noqa: magic-number -- ver comentário acima

_CLASSIFIER_ID_TEMPLATE = "hmm_gaussian_k{n_states}_v1"


def hmm_gaussian_classifier_id(n_states: int) -> str:
    """`classifier_id` determinístico a partir de `n_states` -- única fonte
    do template (`HMMFit.classifier_id` chama esta função; não duplicar o
    literal em outro lugar, ver instrução original da task)."""
    return _CLASSIFIER_ID_TEMPLATE.format(n_states=n_states)


@dataclass(frozen=True, slots=True)
class HMMFit:
    """`params`: pytree `ParamsGaussianHMM` ajustado (tipo real do
    `dynamax`, não modelado explicitamente aqui -- `Any` é deliberado,
    este módulo só precisa passar `params` de volta pro `dynamax`, nunca
    inspeciona campos além de `emissions.means` em `predict_hmm_gaussian`).
    Campos extras além do contrato mínimo (`params`/`n_states`/
    `train_end_idx`) existem pra trilha de auditoria (SR 11-7): `seed`/
    `sticky_concentration` reproduzem o fit exatamente, `final_log_prob`
    permite o harness (Fase 3) comparar qualidade de convergência entre
    fits sem precisar guardar a curva de `log_probs` inteira."""

    params: Any
    n_states: int
    train_end_idx: int
    emission_dim: int
    seed: int
    sticky_concentration: float
    final_log_prob: float

    @property
    def classifier_id(self) -> str:
        return hmm_gaussian_classifier_id(self.n_states)


def _all_finite(pytree: Any) -> bool:
    """`True` sse todo leaf do pytree (arrays JAX) é finito -- usado pra
    detectar fit numericamente degenerado (NaN/Inf em params ou em
    log_probs) sem precisar conhecer a estrutura exata de `ParamsGaussianHMM`."""
    leaves = jax_tree_util.tree_leaves(pytree)
    return bool(all(bool(np.all(np.isfinite(np.asarray(leaf)))) for leaf in leaves))


def _scale_aware_init_covariance(train_obs: Float2DArray, n_states: int) -> Any:
    """Covariância inicial = covariância EMPÍRICA de `train_obs`, ladrilhada
    pra todo estado -- fix do achado #1 (docstring do módulo): o `method=
    "kmeans"` nativo do dynamax inicializa com identidade, descalibrado pra
    qualquer dado fora de escala unitária. `ddof=0` (população, não
    amostral) -- consistente com `canonicalization.py` (mesmo pacote) e
    evita divisão por zero se `train_obs` tiver só 1 observação (`N-ddof=0`
    com `ddof=1`); `+ eps*I` evita singularidade exata em dado degenerado
    (pontos idênticos). `jnp.atleast_2d` cobre `emission_dim==1` (onde
    `jnp.cov` devolveria escalar 0-d em vez de matriz `(1,1)`) -- não usado
    pelo candidato real do M4 (`emission_dim=2` sempre), mas a função fica
    genérica sem custo extra."""
    emission_dim = train_obs.shape[1]
    train_obs_jax = jnp.asarray(train_obs)
    empirical_cov = jnp.atleast_2d(jnp.cov(train_obs_jax.T, ddof=0))
    regularized_cov = empirical_cov + _INIT_COV_EPSILON * jnp.eye(emission_dim)
    result: Any = jnp.tile(regularized_cov[None, :, :], (n_states, 1, 1))
    return result


def fit_hmm_gaussian(
    obs: Float2DArray,
    *,
    n_states: int,
    train_end_idx: int,
    seed: int,
    num_em_iters: int | None = None,
    sticky_concentration: float | None = None,
) -> HMMFit | None:
    """Ajusta `GaussianHMM(n_states, emission_dim)` via `fit_em` só sobre
    `obs[:train_end_idx]` (`B05`, refit por fold expansivo ancorado --
    contrato do CHAMADOR decidir qual fatia é `train_end_idx`, este módulo
    só executa). `obs[:, 0]` precisa ser `log_return_1` por convenção do
    M4 (mesma convenção de `predict_hmm_gaussian`/canonicalização) --
    função não recalcula features, só consome o array pronto.

    `sticky_concentration=None`/`num_em_iters=None` (ambos default) resolvem
    pra `config/constants.yaml` (`hmm_gaussian_sticky_concentration_default`/
    `hmm_gaussian_num_em_iters`, via `load_regime_constant` -- ver
    "Correção-relâmpago via ponto de injeção" no docstring do módulo)
    -- `None` explícito é o sinal de "usa o default", não "zero"/"sem
    iteração" (`sticky_concentration=0.0` seria vanilla HMM; passar `0.0`
    explicitamente É uma forma válida de desligar o prior sticky pra
    comparação/sweep, diferente de não passar nada -- `num_em_iters` não
    tem um `0` operacionalmente válido, mas o mesmo sentinela `None`
    "usa o default" é mantido por simetria/consistência de API entre os
    dois parâmetros). Passar QUALQUER valor explícito (`0`/`10`/`100`...)
    nunca toca `constants.yaml` -- só o caminho `None` (chamador omitiu o
    kwarg) executa `load_regime_constant`, real leitura de disco.

    Determinismo: `seed` fixa a `jax.random.PRNGKey` usada tanto pra
    inicialização k-means (média) quanto pra amostragem do prior de
    transição/estado inicial -- mesma seed, mesmo `obs`, mesmo resultado,
    sempre (EM é determinístico dado um ponto de partida fixo).

    Retorna `None` (não levanta exceção) se o fit COMPLETAR mas convergir
    pra um resultado degenerado DETECTÁVEL -- dois casos, ambos logados via
    `structlog` (não escondido):

    1. NaN/Inf em `params` ajustado ou na curva de `log_probs` do EM.
    2. Colapso de estado: decodifica o próprio TREINO com os params
       ajustados e confere que os `n_states` aparecem de fato como argmax
       da posterior filtrada em pelo menos 1 barra cada -- um EM que
       "esvazia" um estado (log-verossimilhança/params continuam finitos,
       mas o estado nunca vence o argmax) não é erro numérico, mas é uma
       convergência degenerada pro propósito do M4: um HMM k=3 que na
       prática só usa 2 estados não é o candidato k=3 que o trial paga
       pra medir.

    Já `train_end_idx` menor que `n_states` é um erro de PRECONDIÇÃO, não
    uma convergência degenerada -- levanta `ValueError` (mesmo padrão de
    `bocpd.run_bocpd`/`canonicalize_states`: entrada inválida falha rápido
    com mensagem clara, não retorna `None` silenciosamente)."""
    if obs.ndim != 2:
        raise ValueError(
            f"fit_hmm_gaussian: obs precisa ser 2D (T, emission_dim), recebeu shape {obs.shape}"
        )
    if obs.shape[1] < 1:
        raise ValueError(f"fit_hmm_gaussian: emission_dim precisa ser >= 1, recebeu {obs.shape[1]}")
    if n_states < 1:
        raise ValueError(f"fit_hmm_gaussian: n_states precisa ser >= 1, recebeu {n_states}")
    n_total = obs.shape[0]
    if not (1 <= train_end_idx <= n_total):
        raise ValueError(
            f"fit_hmm_gaussian: train_end_idx={train_end_idx} fora de [1, {n_total}] "
            "(n_total de obs)"
        )
    train_obs = obs[:train_end_idx]
    if train_obs.shape[0] < n_states:
        raise ValueError(
            f"fit_hmm_gaussian: train_end_idx={train_end_idx} dá {train_obs.shape[0]} observações "
            f"de treino, menos que n_states={n_states} -- EM não tem como estimar um estado sem "
            "nenhuma observação atribuível a ele"
        )

    emission_dim = obs.shape[1]
    # `load_regime_constant` só é chamado nesta linha (ramo `is None`) --
    # ver "Correção-relâmpago via ponto de injeção" no docstring do módulo.
    # Chamador que passa valor explícito nunca executa a leitura de disco.
    resolved_sticky = (
        float(load_regime_constant(_STICKY_CONCENTRATION_CONSTANT_NAME))
        if sticky_concentration is None
        else sticky_concentration
    )
    resolved_num_em_iters = (
        int(load_regime_constant(_NUM_EM_ITERS_CONSTANT_NAME))
        if num_em_iters is None
        else num_em_iters
    )

    hmm = GaussianHMM(n_states, emission_dim, transition_matrix_stickiness=resolved_sticky)
    rng_key = jax_random.PRNGKey(seed)
    train_obs_jax = jnp.asarray(train_obs)

    # kmeans só pelas MÉDIAS (robustas à escala) -- a covariância que o
    # dynamax devolveria aqui é identidade, descalibrada (achado #1,
    # docstring do módulo); substituída logo abaixo.
    init_params, props = hmm.initialize(rng_key, method="kmeans", emissions=train_obs_jax)
    scale_aware_covs = _scale_aware_init_covariance(train_obs, n_states)
    init_params = init_params._replace(
        emissions=init_params.emissions._replace(covs=scale_aware_covs)
    )

    fitted_params, log_probs = hmm.fit_em(
        init_params, props, train_obs_jax, num_iters=resolved_num_em_iters, verbose=False
    )

    log_probs_np = np.asarray(log_probs)
    if not _all_finite(fitted_params) or not bool(np.all(np.isfinite(log_probs_np))):
        logger.warning(
            "regime.hmm_gaussian.fit_degenerate_non_finite",
            n_states=n_states,
            train_end_idx=train_end_idx,
            seed=seed,
        )
        return None

    train_posterior = hmm.filter(fitted_params, train_obs_jax)
    train_raw_states = np.asarray(np.argmax(np.asarray(train_posterior.filtered_probs), axis=1))
    n_states_used = int(np.unique(train_raw_states).size)
    if n_states_used < n_states:
        logger.warning(
            "regime.hmm_gaussian.fit_degenerate_state_collapse",
            n_states=n_states,
            n_states_used=n_states_used,
            train_end_idx=train_end_idx,
            seed=seed,
        )
        return None

    return HMMFit(
        params=fitted_params,
        n_states=n_states,
        train_end_idx=train_end_idx,
        emission_dim=emission_dim,
        seed=seed,
        sticky_concentration=float(resolved_sticky),
        final_log_prob=float(log_probs_np[-1]),
    )


def predict_hmm_gaussian(fit: HMMFit, obs: Float2DArray) -> IntArray:
    """Decodifica `obs` via posterior FILTRADA (`hmm.filter`, causal --
    `p(z_t | y_{1:t})`, NUNCA `smoother`/Viterbi, que usariam observações
    futuras), argmax por barra, depois canonicaliza via
    `canonicalize_states` ancorado nas médias AJUSTADAS de `fit` (ver
    "Canonicalização ancorada no FIT" no docstring do módulo -- não na
    média empírica deste `obs`).

    Reconstrói um `GaussianHMM(fit.n_states, fit.emission_dim)` "limpo"
    (sem `transition_matrix_stickiness`) só pra ter um objeto com os
    métodos certos -- `stickiness`/concentração só afetam o PRIOR (usado
    em `initialize`/`log_prior`/M-step), `filter` só lê `params.
    transitions.transition_matrix` já ajustado (`_compute_transition_
    matrices` devolve o array direto, ignora a config do objeto) --
    confirmado por smoke test (`filter` com objeto "limpo" reproduz
    bit-a-bit o resultado do objeto original usado no fit).

    Causal de ponta a ponta: perturbar `obs[t+1:]` não muda `canonical_id[
    :t+1]` -- decodificação é uma recursão forward pura (mesma
    causalidade estrutural de `bocpd.run_bocpd`) E a canonicalização não
    depende de nada deste `obs` (só de `fit.params`, que só viu `obs[
    :fit.train_end_idx]` do FIT original)."""
    if obs.ndim != 2 or obs.shape[1] != fit.emission_dim:
        raise ValueError(
            f"predict_hmm_gaussian: obs precisa ser 2D com emission_dim={fit.emission_dim} "
            f"(mesmo do fit), recebeu shape {obs.shape}"
        )
    if obs.shape[0] == 0:
        raise ValueError("predict_hmm_gaussian: obs vazio")

    hmm = GaussianHMM(fit.n_states, fit.emission_dim)
    posterior = hmm.filter(fit.params, jnp.asarray(obs))
    raw_state_id = np.asarray(np.argmax(np.asarray(posterior.filtered_probs), axis=1)).astype(
        np.int64
    )

    # Uma entrada por estado (grupo singleton) -- média = o próprio valor,
    # variância = 0.0 sempre (var de 1 ponto), então o desempate por
    # variância de `canonicalize_states` fica inerte e a ordenação é
    # puramente pela média ajustada, exatamente o critério pretendido.
    state_means = np.asarray(fit.params.emissions.means)[:, 0].astype(np.float64)
    state_order = canonicalize_states(
        np.arange(fit.n_states, dtype=np.int64), state_means
    )
    canonical_id: IntArray = np.vectorize(state_order.mapping.get)(raw_state_id).astype(np.int64)
    return canonical_id


__all__ = [
    "HMMFit",
    "fit_hmm_gaussian",
    "hmm_gaussian_classifier_id",
    "predict_hmm_gaussian",
]
