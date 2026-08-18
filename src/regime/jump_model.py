"""Jump Model / Continuous Jump Model (CJM) vendorizado via `jumpmodels` --
M4 (`PRD_V4_1.md` §3.2), Aydınhan et al. 2024. Candidato #5 dos 3 novos do
estudo de comparação de classificadores de regime -- decisão do Manager
(plano `wise-exploring-panda.md`, "Jump Model -- qual variante"): **CJM
(contínuo)**, não o JM discreto original (Bemporad et al.) citado
literalmente no PRD -- mesma família nomeada, variante que a literatura
2024 mostra mais robusta (interpretação probabilística, validada em dado
real). Decisão já ratificada, não re-decidida aqui.

**API real confirmada por smoke test (2026-08-17)** contra
`jumpmodels.jump.JumpModel` (código-fonte lido em
`.venv/Lib/site-packages/jumpmodels/{jump,base}.py` + `utils/*.py`, não
adivinhado):

1. `JumpModel(n_components=K, jump_penalty=LAMBDA, cont=True,
   random_state=SEED)` -- `cont=True` ativa o CJM (vs. discreto por
   default). `.fit(X, sort_by="cumret")` ajusta via coordinate descent
   (E-step = DP tipo Viterbi sobre a matriz de penalidade de jump; M-step
   = média ponderada por cluster).

2. `X` pode ser `numpy.ndarray` OU `pandas.DataFrame` -- o pacote aceita
   os dois internamente (`DF_ARR_TYPE = Union[np.ndarray, pd.DataFrame]`,
   `utils/validation.py`) -- mas este módulo SEMPRE converte pra
   `pandas.DataFrame` antes de chamar `jumpmodels` (decisão de desenho do
   plano, item 8, não uma exigência estrita medida da lib): mantém o
   contrato B26 (pandas só em interop de borda, confinado a ESTE módulo)
   em vez de depender de um comportamento da lib não documentado
   formalmente. Índice: `pandas.RangeIndex` default basta -- `jumpmodels`
   só exige índice "de verdade" quando alinha DOIS objetos pandas entre
   si (`align_index`, usado só se `ret_ser` for passado a `.fit()` -- este
   módulo nunca passa `ret_ser`, canonicaliza os rótulos por conta própria
   depois, ver item 3 abaixo).

3. **`labels_`/`.predict()` SEMPRE devolvem rótulo DURO (inteiro), mesmo
   com `cont=True`** -- achado real do smoke test, contraria a expectativa
   ingênua de "`cont=True` implica soft-assignment exposto no output". A
   natureza contínua do CJM vive em `centers_`/`proba_` (o estado É um
   ponto na simplex de probabilidade discretizada --
   `jumpmodels.jump.discretize_prob_simplex` -- e a penalidade de
   transição é a distância L1 entre esses pontos, elevada ao quadrado),
   mas o atributo público `labels_` (`reduce_proba_to_labels(proba_)`,
   sempre `argmax` por linha internamente) e o retorno de `.predict()` já
   são rótulo duro em `{0..K-1}`. Não precisamos fazer nosso próprio
   argmax -- só chamar `.predict()` e canonicalizar o resultado.

4. **Determinismo**: `random_state` no construtor
   (`sklearn.utils.check_random_state` por baixo, usado em k-means++ pra
   gerar os `n_init` conjuntos de centros iniciais) -- confirmado por
   smoke test E por `test_determinismo_mesma_seed_mesmo_input` neste
   módulo: mesmo `random_state` + mesmo input -> `labels_` bit-idêntico
   entre execuções.

5. **`n_samples < n_components`** levanta `ValueError` de dentro de
   `sklearn.cluster.kmeans_plusplus` ("n_samples=X should be >=
   n_clusters=Y") -- capturado por `fit_jump_model` e traduzido em
   retorno `None` (contrato explícito da função: falha de DADO detectável
   em runtime, nunca escondida -- logada via `structlog`, não engolida em
   silêncio, B28).

6. **Escala do `jump_penalty`**: a matriz de penalidade do CJM é
   `jump_penalty * (dist_L1_simplex ** 2)` -- na MESMA escala da perda
   `0.5 * dist_euclidiana_quadrada(X, centers)`. Achado real de smoke
   test: sobre `[log_return_1, realized_vol_short]` (escala ~1e-2/1e-3),
   `jump_penalty >= ~0.1` já satura o modelo num único estado (a
   penalidade domina a perda de todos os dados, zero transições) --
   o valor final calibrado fica fora do escopo deste módulo (harness/
   `constants.yaml`, decisão de desenho #5 do plano), mas o
   hiperparâmetro é sensível à escala das features, não um "valor
   universal razoável" -- documentado aqui pra quem calibrar não
   reinventar essa descoberta.

**Compromisso de causalidade -- decodificação em BLOCO, não barra-a-barra**
(decisão de desenho #1 do plano, `CLAUDE.md` B05): `.predict()` decodifica
TODAS as linhas do array passado numa única chamada de Programação
Dinâmica tipo Viterbi (`jumpmodels.jump.dp`) -- o forward pass é causal
(cada `values[t]` só usa `loss_mx[0..t]`), mas o TRACEBACK (escolha do
caminho ótimo final) anda de trás pra frente: `assign[t-1]` é escolhido em
função de `assign[t]`, que por sua vez foi influenciado por TODA a
sequência através do ponto de partida `assign[-1] = argmin(values[-1])`.
Ou seja: uma observação em `t' > t`, DENTRO do MESMO array passado a uma
chamada de `.predict()`, PODE mudar o rótulo decodificado em `t` --
confirmado EMPIRICAMENTE (não só por leitura do código-fonte): perturbar
as últimas 30 barras de um fold sintético de 50 barras mudou os 20
rótulos anteriores (ambíguos, próximos ao centro dos 2 estados) em 100%
dos casos no smoke test, e reproduzido como teste formal em
`tests/unit/test_regime_jump_model.py::
test_perturbar_fim_do_fold_pode_mudar_inicio_do_mesmo_fold`.

Existe `.predict_online()` na lib, que É causal barra-a-barra (usa só
`X[:i+1]` pra decodificar a linha `i`) -- mas o plano decidiu
deliberadamente pelo decode em BLOCO (`.predict()`) sobre o fold de teste
inteiro, replicando o desenho real do walk-forward do M4 (decodificar o
fold de teste inteiro de uma vez, não streaming barra-a-barra dentro do
fold -- plano, decisão 1: "decodificam só o teste do fold", não "barra
por barra dentro do fold"). O compromisso é ACEITO e DOCUMENTADO, não
escondido: dentro do fold de teste, barras anteriores podem, em
princípio, ser influenciadas por observações posteriores no MESMO fold --
mas NUNCA cruza fronteira de fold (o array passado a `.predict()` é
SEMPRE só a fatia do fold, nunca a série inteira) e NUNCA toca o treino
(o modelo já está ajustado antes de `predict_jump_model` ser chamada --
`centers_`/`jump_penalty_mx` fixos, ver `test_perturbar_fora_do_fold_
nao_muda_decode_do_fold`). Diferente de HMM (posterior filtrada, causal
por-barra mesmo dentro do fold) e BOCPD (online por construção, sem noção
de "fold" nenhuma) -- essa é a característica estrutural do Jump Model
que o diferencia dos outros 2 candidatos novos do M4, não um bug deste
módulo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd  # noqa: interop-only -- fronteira de jumpmodels, confinada a este módulo (B26)
import structlog
from jumpmodels.jump import JumpModel
from numpy.typing import NDArray

from src.regime.canonicalization import canonicalize_states

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

logger = structlog.get_logger(__name__)

# `classifier_id` deste candidato -- exportado pra o harness (`m4_regime_
# comparison.py`, ainda não escrito) referenciar sem re-hardcodar a string.
CLASSIFIER_ID = "jump_model_cjm_v1"

_DEFAULT_SEED = 0


@dataclass(frozen=True, slots=True)
class JumpFit:
    """Resultado de `fit_jump_model` -- retém o `JumpModel` já ajustado
    (`model`, tipo `Any` porque é um objeto externo de `jumpmodels`, não
    reimplementamos os atributos dele aqui) mais os metadados do fold que
    o gerou (`n_states`, `train_end_idx`), úteis pra auditoria/logging no
    harness, não pela decodificação em si (que só precisa de `model` --
    `centers_`/`jump_penalty_mx`, já congelados pós-`.fit()`). Nenhum
    dado de treino bruto (`obs[:train_end_idx]`) é retido aqui além do
    que a própria `jumpmodels` já guarda dentro de `model` -- não há
    referência solta que permita `predict_jump_model` "espiar" o treino
    por acidente."""

    model: Any
    n_states: int
    train_end_idx: int


def fit_jump_model(
    obs: FloatArray,
    *,
    n_states: int,
    jump_penalty: float,
    train_end_idx: int,
    seed: int = _DEFAULT_SEED,
) -> JumpFit | None:
    """Ajusta o CJM (`cont=True`, sempre -- este módulo É o candidato CJM
    do M4, JM discreto não é escopo, não é um parâmetro exposto) só sobre
    `obs[:train_end_idx]` -- refit expansivo ancorado por fold de
    walk-forward (B05, decisão de desenho #1 do plano). `obs` é
    `[log_return_1, realized_vol_short]` na convenção do M4 (decisão #6),
    mas esta função não assume 2 colunas -- só usa `obs.shape[1]`.

    `jump_penalty`: hiperparâmetro fixado a priori pelo CALLER (harness/
    `constants.yaml`, fora do escopo deste módulo) -- não é sweepado
    aqui, não tem default "razoável" embutido porque é sensível à escala
    das features (ver módulo docstring, achado #6). `n_states`: mesma
    responsabilidade do caller (`m4_jump_model_n_states` em
    `constants.yaml`, decisão de desenho #4 do plano -- 3, mas não
    hardcoded aqui).

    `seed`: passado direto pra `JumpModel(random_state=seed)`
    (`sklearn.utils.check_random_state` por baixo) -- confirmado
    determinístico por smoke test e por
    `test_determinismo_mesma_seed_mesmo_input`: mesma seed + mesmo
    `obs[:train_end_idx]` -> `labels_` bit-idêntico entre chamadas.

    Retorna `None` (não levanta) se `.fit()` falhar por um motivo de DADO
    detectável em runtime -- ex. `train_end_idx` estruturalmente válido
    (`0 < train_end_idx <= len(obs)`) mas pequeno demais pro k-means++
    inicializar `n_states` centros (`n_samples < n_components`,
    `sklearn.cluster.kmeans_plusplus` levanta `ValueError`), ou NaN em
    `obs[:train_end_idx]` (`jumpmodels` levanta `AssertionError`) --
    logado via `structlog` (`regime.jump_model.fit_failed`), nunca
    engolido em silêncio (B28, "nunca silencie sem achar a causa raiz" --
    a causa raiz aqui É o dado insuficiente/inválido, reportada no log).

    Levanta `ValueError` (não retorna `None`) pra erros ESTRUTURAIS do
    CALLER -- `train_end_idx` fora de `(0, len(obs)]`, `obs` não-2D,
    `n_states < 2`: esses não são "o fit tentou e falhou por causa do
    dado", são "a chamada em si não faz sentido", mesma distinção que
    `run_bocpd` já aplica pra `hazard_lambda`/`obs` vazio."""
    if obs.ndim != 2:
        raise ValueError(
            f"fit_jump_model: obs precisa ser 2D (n_bars, n_features), recebeu shape {obs.shape}"
        )
    n_bars = obs.shape[0]
    if train_end_idx <= 0 or train_end_idx > n_bars:
        raise ValueError(
            f"fit_jump_model: train_end_idx={train_end_idx} fora de (0, {n_bars}] "
            f"(obs tem {n_bars} barras)"
        )
    if n_states < 2:
        raise ValueError(f"fit_jump_model: n_states={n_states} precisa ser >= 2")

    train_slice = obs[:train_end_idx]
    x_train = pd.DataFrame(train_slice)

    model = JumpModel(
        n_components=n_states, jump_penalty=jump_penalty, cont=True, random_state=seed
    )
    try:
        # sort_by="cumret" sem passar `ret_ser` NÃO ordena por retorno de
        # verdade -- lendo `jumpmodels.base.sort_states_from_ret`: com
        # `ret_ser=None` cai no ramo `elif "proba_" in best_res:
        # sort_param_dict(..., sort_by="freq")`, ignorando o `sort_by`
        # pedido aqui. Inofensivo: este módulo canonicaliza os rótulos
        # brutos por conta própria logo depois (`predict_jump_model` ->
        # `canonicalize_states`), então qualquer permutação/ordenação
        # interna da lib é desfeita de qualquer jeito -- mantido só como
        # intenção documentada, não por efeito funcional real.
        model.fit(x_train, sort_by="cumret")
    except (ValueError, AssertionError) as exc:
        logger.warning(
            "regime.jump_model.fit_failed",
            n_states=n_states,
            jump_penalty=jump_penalty,
            train_end_idx=train_end_idx,
            seed=seed,
            error=str(exc),
        )
        return None

    return JumpFit(model=model, n_states=n_states, train_end_idx=train_end_idx)


def predict_jump_model(fit: JumpFit, obs_test_fold: FloatArray) -> IntArray:
    """Decodifica SÓ `obs_test_fold` (a fatia do fold de teste passada
    pelo caller -- nunca a série inteira, nunca o treino) via
    `fit.model.predict()`, depois canonicaliza os rótulos brutos via
    `src.regime.canonicalization.canonicalize_states` (resposta =
    `obs_test_fold[:, 0]` = `log_return_1`, convenção do espaço de
    features do M4 -- decisões de desenho #3/#6 do plano: "resposta
    usada pra ordenar é `log_return_1`, mesma convenção do resto do M4")
    antes de devolver. `classifier_id = "jump_model_cjm_v1"`
    (`CLASSIFIER_ID`, exportado deste módulo).

    **Compromisso de causalidade -- decode em BLOCO, não barra-a-barra**
    (ver módulo docstring pra prova/derivação completa): `.predict()` roda
    uma DP tipo Viterbi sobre TODO `obs_test_fold` de uma vez -- uma
    observação em `t' > t` DENTRO do MESMO fold PODE mudar o rótulo
    decodificado em `t` (provado empiricamente, não só por leitura de
    código, em `test_perturbar_fim_do_fold_pode_mudar_inicio_do_mesmo_
    fold`). O que NÃO acontece (também provado, não só assumido): nada
    FORA de `obs_test_fold` -- nem o treino usado por `fit_jump_model`,
    nem um fold futuro -- influencia esta chamada, porque `fit.model` já
    está ajustado (centros/penalidade congelados) e `obs_test_fold` é o
    ÚNICO dado novo que entra aqui (`test_perturbar_fora_do_fold_nao_
    muda_decode_do_fold`).

    Levanta `ValueError` se `obs_test_fold` não for 2D, estiver vazio, tiver
    um número de features diferente do usado no `fit`, ou contiver NaN/Inf
    (achado real de auditoria, 2026-08-17, não hipotético -- reproduzido
    empiricamente, não só lido no código-fonte: NaN em `obs_test_fold` NÃO
    é pego por nenhuma das 3 checagens acima -- `check_2d_array` de dentro
    de `jumpmodels` (`assert_na=True` default) o pega DEPOIS, mas levanta
    `AssertionError` sem contexto nenhum (`"input numerical object contains
    NaNs."`, sem symbol/fold/classifier_id), crashando o caller de forma
    opaca em vez do `ValueError` limpo e contextual que este módulo já usa
    pras outras 3 checagens. Inf é ainda mais grave: `jumpmodels` só checa
    NaN (`pd.isna`, que NÃO cobre Inf) -- Inf passa batido por TODAS as
    checagens, entra na DP tipo Viterbi (`jumpmodels.jump.dp`), e o
    `cdist(..., "sqeuclidean")` produz `loss_mx[t, :] = [inf, inf, ...]`
    pra aquela barra; como `values[t] = loss_mx[t] + (values[t-1][:, None]
    + penalty_mx).min(axis=0)`, o `inf` se propaga PRA FRENTE por TODO o
    resto do fold (não só a barra afetada) -- rótulos completamente
    degenerados devolvidos SEM NENHUM sinal de erro, log ou exceção
    (confirmado rodando `predict_jump_model` com 1 valor `inf` isolado:
    devolve um array de rótulos "normal" na aparência, sem qualquer aviso).
    Checagem de finitude aqui, ANTES de entrar em `jumpmodels`, fecha os
    dois buracos de uma vez: mesma classe de erro cedo e claro que as
    outras 3 checagens já dão, e nunca depende de qual validação interna
    da lib (se alguma) captura o quê."""
    if obs_test_fold.ndim != 2:
        raise ValueError(
            "predict_jump_model: obs_test_fold precisa ser 2D (n_bars, n_features), "
            f"recebeu shape {obs_test_fold.shape}"
        )
    if obs_test_fold.shape[0] == 0:
        raise ValueError("predict_jump_model: obs_test_fold vazio")

    n_features_train = fit.model.centers_.shape[1]
    if obs_test_fold.shape[1] != n_features_train:
        raise ValueError(
            f"predict_jump_model: obs_test_fold tem {obs_test_fold.shape[1]} features, "
            f"fit foi treinado com {n_features_train}"
        )

    finite_mask = np.isfinite(obs_test_fold)
    if not finite_mask.all():
        n_non_finite = int((~finite_mask).sum())
        raise ValueError(
            f"predict_jump_model: obs_test_fold contém {n_non_finite} valor(es) "
            f"não-finito(s) (NaN/Inf) de {obs_test_fold.size} -- decode silenciosamente "
            "degenerado (Inf propaga pra frente por todo o resto do fold via a DP) ou "
            "AssertionError sem contexto (NaN) se não barrado aqui, ver docstring desta função"
        )

    x_test = pd.DataFrame(obs_test_fold)
    raw_labels = np.asarray(fit.model.predict(x_test), dtype=np.int64)

    response = obs_test_fold[:, 0]  # log_return_1, convenção do espaço de features do M4
    canonical = canonicalize_states(raw_labels, response)
    return canonical.canonical_id


__all__ = ["CLASSIFIER_ID", "JumpFit", "fit_jump_model", "predict_jump_model"]
