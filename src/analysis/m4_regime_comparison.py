"""M4 — harness de orquestração da comparação de classificadores de regime
(`PRD_V4_1.md` §3.2), Fase 3 do plano `wise-exploring-panda.md`. Mesma
classe de módulo que `src.analysis.volatility_comparison` (M1)/
`src.analysis.m2_bar_comparison` (M2): ponto de entrada manual, IO real,
NUNCA dentro da suíte automatizada além de 1 smoke test `integration`/
`slow`.

**4 candidatos, 6 trials (decisão #5 do plano, confirmação pendente do
Manager antes da Fase 6):** baseline (`QuantileRegimeClassifier`, 0 trial,
produção) · HMM gaussiano k=2/3/4 (`src.regime.hmm_gaussian`, 3 trials) ·
Jump Model contínuo/CJM (`src.regime.jump_model`, 1 trial) · BOCPD
(`src.regime.bocpd`, 1 trial). Grade de símbolo (5 ativos) NÃO multiplica
trial, mesma convenção de `AG-039`/M1.

**Fit por fold — só HMM/Jump Model (decisão #1 do plano, B05).** Refit
expansivo ancorado no mesmo `WalkForwardSplit` do M1
(`src.validation.volatility_walkforward.generate_anchored_walk_forward_
splits`): `fit_*(obs, train_end_idx=split.train_end_idx)`, decodifica só
`obs[split.test_start_idx:split.test_end_idx]`. BOCPD é online por
construção — roda **uma vez** sobre a série causal inteira (nunca refeito
por fold); o baseline é uma state machine determinística, também sem
conceito de fold. Para os dois, "estabilidade entre folds" é `1.0` POR
CONSTRUÇÃO — não uma medição vazia, é consequência direta de nunca haver
mais de um "fit" para comparar (ver `CandidateResult.fold_stability_by_
construction`).

**Espaço de features dos 3 candidatos novos — direto do OHLC da dollar-bar,
NUNCA do Feature Engine (decisão #6 do plano).** `log_return_1[t] =
ln(close[t]/close[t-1])` (primeira barra `NaN`, sem `close[t-1]`).
`realized_vol_short` reusa `src.features.support.realized_vol` (mesma
primitiva usada por `C06_vol_ratio_12_96`/`C07_vol_pctile_expanding` —
`σ(log_return) × √window`, janela rolante CAUSAL de
`feature_c06_vol_ratio_short_window` barras, `min_samples=window` estrito,
não parcial) — decisão de integração: reusar a primitiva de baixo nível
(`support.realized_vol`) não é o mesmo que consumir `C07_vol_pctile_
expanding` (proibido, vicia o teste de ortogonalidade por construção); é
só a mesma fórmula de desvio-padrão rolante já usada em produção, aplicada
aqui a um propósito diferente. BOCPD usa só `log_return_1` (univariado);
HMM/Jump Model usam `[log_return_1, realized_vol_short]` (2D).

**`min_periods`/warmup do início da série — achado real medido nesta
sessão, não presumido.** Como `log_return_1[0]` é estruturalmente `NaN`
(não existe `close[-1]`), e `polars.rolling_std` propaga `NaN` (não
`null`) por todo janela que o contém, o primeiro valor FINITO de
`realized_vol_short` só aparece no índice `window` (não `window-1` como
seria sem o `NaN` inicial) — confirmado por medição direta
(`rolling_std(window_size=12, min_samples=12)` sobre um array com `NaN` na
posição 0 dá 12 `NaN`s, não 11). `_valid_start_idx` computa esse ponto
programaticamente (primeiro índice em que `log_return_1` E
`realized_vol_short` são ambos finitos) e **todo o resto do pipeline desta
função — `bars_df`/`open_time_ms`/`obs`/`forward_return`/`vol_pctile`/
`regime` do baseline — é cortado nesse mesmo ponto, uniformemente, antes de
gerar os splits de walk-forward.** Decisão de integração: sem esse corte
uniforme, `run_bocpd` (que deriva o prior NIG da janela de warmup via
`np.median`/`np.var`) e `fit_hmm_gaussian`/`fit_jump_model` (que não
filtram `NaN`) receberiam lixo/degenerariam de forma silenciosa nas
primeiras `window` barras — mesma classe de bug já encontrada e corrigida
em `bocpd.py`/`hmm_gaussian.py` nesta sessão (prior/covariância calibrados
sem olhar pra escala/domínio real do dado). O custo é desprezível
(`window` barras, tipicamente 12, perto do início de uma série de
dezenas de milhares) e uniforme entre baseline e candidatos — comparação
continua justa.

**Alinhamento `bars_df` ↔ `baseline_df` — confirmado, não presumido.**
`run_regime_comparison_for_symbol` carrega os dois com o MESMO
`(symbol, start, end)` (`lake.query_dollar_bars` e `build_regimes(...,
bar_source="dollar_r1")`, que por baixo chama `lake.query_dollar_bars(
symbol, start, end)` sem filtro adicional — mesma fonte, mesma janela).
`compare_regime_candidates_for_symbol` (núcleo puro) não CONFIA nisso
silenciosamente: `_assert_bars_baseline_aligned` checa altura E
`open_time`/`t0` barra-a-barra antes de prosseguir, levanta `ValueError`
claro se algum caller passar os dois desalinhados (ex. janelas de data
diferentes).

**Baseline — R0 excluído das métricas, não da contagem de estados.** R0 é
warmup (`t < min_warmup_bars`, puramente por índice — nunca reaparece
depois, confirmado em `classifier._run_state_machine`), não um regime real
observável; incluí-lo em `anova_by_group`/`regime_persistence` inflaria a
"separação" artificialmente (R0 não tem retorno característico, é só
"ainda não sei"). `CandidateResult.n_states` do baseline continua `6`
(`len(classifier.REGIME_LABELS)`, R0..R5 — o nº NOMINAL de estados que o
classificador declara), distinto de quantos aparecem de fato nas métricas
pós-filtro — mesma distinção que HMM `k=4` faz entre "estados pedidos" e
"estados que sobreviveram no fold" (`fit_hmm_gaussian` retorna `None` se
colapsar).

**Débito herdado do baseline, declarado explicitamente no relatório final
(não escondido) — mesmo achado already registrado no plano.**
`QuantileRegimeClassifier` roda hoje sobre `C07_vol_pctile_expanding`, que
`compute_t1_features` constrói sobre **ATR-Wilder** (`vol_estimator_id=
None`), não Garman-Klass/Parkinson — apesar de `constants.yaml::
canonical_volatility_estimator` declarar `garman_klass_w20`,
`compute_t1_features` só aceita `vol_estimator_id=None` (ATR-Wilder) ou
`"parkinson_w{N}"`. Ler este relatório como "ATR-Wilder vs. candidatos
novos", não "GK vs. candidatos novos" — `_BASELINE_VOL_ESTIMATOR_CAVEAT`
carrega essa frase no payload persistido, pra quem só lê o JSON também
veja.

**Fase 4 (Q3, terceira via) — reuso pretendido, limitação real documentada
aqui, não resolvida.** O plano pede que `compare_regime_candidates_for_
symbol`/os fits fiquem reusáveis pela Fase 4 sem reescrita.
`CandidateResult`, como está, só expõe MÉTRICAS AGREGADAS (ANOVA/
persistência/estabilidade) — não os arrays `canonical_id` por barra nem os
objetos de fit por fold. Q3 (classificar regime só no BTC, aplicar aos
outros 4 via as-of join causal, comparar via Rand ajustado contra a
classificação própria de cada ativo) precisa exatamente desses artefatos
brutos, que este módulo hoje descarta depois de calcular as métricas.
Duas rotas ficam abertas pra Fase 4 (nenhuma implementada aqui): (a)
adicionar um retorno "raw" opcional (`return_raw_labels: bool = False`) a
`_run_fold_refit_candidate`/`_bocpd_candidate_result`/`_baseline_candidate_
result` que devolve os arrays por barra junto do `CandidateResult`
agregado, ou (b) a Fase 4 chamar `fit_hmm_gaussian`/`fit_jump_model`/
`run_bocpd`/`build_regimes` diretamente e reimplementar o laço de fold —
duplicando a lógica de fatiamento já provada aqui. (a) é preferível
(zero duplicação), mas fica pra quem implementar a Fase 4 decidir, não
decidido sozinho aqui.

**`run_and_save_m4_report` NÃO É CHAMADA POR ESTE MÓDULO.** Todos os
hiperparâmetros de candidato (`jump_n_states`, `jump_penalty`,
`bocpd_hazard_lambda`, `bocpd_n_canonical_buckets`) são obrigatórios (sem
default) — decisão deliberada: os valores calibrados ainda dependem de
confirmação do Manager (Fase 6 do plano) e de constantes que ainda não
existem em `constants.yaml` (bloqueadas de propósito, ver plano seção
"Arquivos modificados"). Chamar esta função com valores inventados seria
exatamente o tipo de "faixa esperada inventada" que B23/CLAUDE.md proíbe.
`if __name__ == "__main__":` deste módulo levanta `SystemExit` com essa
explicação em vez de rodar um report real por engano."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray

from src.core.provenance import report_provenance
from src.data import lake
from src.data._constants import load_constant as load_data_constant
from src.features import support as features_support
from src.features._constants import load_constant as load_feature_constant
from src.regime import classifier
from src.regime.bocpd import run_bocpd, segments_to_canonical_states
from src.regime.build import build_regimes
from src.regime.canonicalization import canonicalize_states
from src.regime.hmm_gaussian import (
    fit_hmm_gaussian,
    hmm_gaussian_classifier_id,
    predict_hmm_gaussian,
)
from src.regime.jump_model import CLASSIFIER_ID as JUMP_MODEL_CLASSIFIER_ID
from src.regime.jump_model import fit_jump_model, predict_jump_model
from src.validation import volatility_walkforward as vwf
from src.validation._constants import load_constant as load_validation_constant
from src.validation.regime_utility import (
    ANOVAResult,
    PersistenceMetrics,
    adjusted_rand,
    anova_by_group,
    regime_persistence,
)

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
# Mesmo tipo estrutural de FloatArray -- só documenta o shape esperado
# (T, emission_dim), mesma convenção de src/regime/hmm_gaussian.py.
Float2DArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR: Final[Path] = _REPO_ROOT / "experiments"
DEFAULT_REPORT_PATH: Final[Path] = EXPERIMENTS_DIR / "m4_regime_comparison_report.json"

ALL_SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
RESOLUTION_ID: Final[str] = "R1"

# Cobertura real medida do disco nesta sessão (mesma convenção de
# src.analysis.volatility_comparison.SYMBOL_START_DATE) -- não presumida.
SYMBOL_START_DATE: Final[dict[str, str]] = {
    "BTCUSDT": "2019-12-31",
    "ETHUSDT": "2021-12-01",
    "SOLUSDT": "2021-12-01",
    "BNBUSDT": "2021-12-01",
    "XRPUSDT": "2021-12-01",
}
END_DATE: Final[str] = "2026-08-07"

# `bocpd.py` não exporta um `CLASSIFIER_ID` (diferente de `jump_model.py`)
# -- valor literal citado na própria docstring do módulo (`classifier_id=
# "bocpd_v1"`), duplicado aqui por não haver de onde importar. Não é uma
# suposição: é o mesmo texto já documentado em src/regime/bocpd.py.
BOCPD_CLASSIFIER_ID: Final[str] = "bocpd_v1"

# R0 (warmup, sempre índice 0 do Enum REGIME_LABELS -- confirmado via
# `.to_physical()`) excluído das métricas do baseline, não da contagem
# nominal de estados (ver docstring do módulo).
_BASELINE_R0_PHYSICAL_ID: Final[int] = 0
_BASELINE_N_STATES: Final[int] = len(classifier.REGIME_LABELS)

# Sentinela de fold sem fit bem-sucedido (fit_hmm_gaussian/fit_jump_model
# retornam None em convergência degenerada/dado insuficiente) -- nunca um
# canonical_id real (canonicalize_states/predict_* sempre devolvem >= 0
# nos caminhos usados aqui, nenhum ignore_value é passado).
_FOLD_FIT_FAILURE_SENTINEL: Final[int] = -1


# ============================================================================
# Espaço de features -- direto do OHLC da dollar-bar, sem IO
# ============================================================================


def _input_obs(bars_df: pl.DataFrame) -> tuple[FloatArray, Float2DArray]:
    """`(log_return_1, [log_return_1, realized_vol_short])`, alinhados por
    POSIÇÃO com `bars_df` (mesmo nº de linhas, mesma ordem) -- sem nenhum
    corte/trim aqui (isso é responsabilidade do caller, ver
    `_valid_start_idx`/docstring do módulo). `close[t-1]` inexistente pra
    `t=0` -- `log_return_1[0]` é `NaN` por construção, não um erro de dado
    (mesmo padrão de `src.features.build.build_t1_features`/`src.
    validation.volatility_walkforward.next_bar_realized_variance`)."""
    close = bars_df["close"].cast(pl.Float64).to_numpy()
    n = close.shape[0]
    log_return_1 = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            log_return_1[1:] = np.log(
                close[1:] / close[:-1]  # noqa: unguarded-ratio -- preço real, sempre >0 por construção
            )

    short_window = int(load_feature_constant("feature_c06_vol_ratio_short_window"))
    realized_vol_short = features_support.realized_vol(log_return_1, short_window)

    obs_2d: Float2DArray = np.column_stack([log_return_1, realized_vol_short]).astype(np.float64)
    return log_return_1, obs_2d


def _valid_start_idx(log_return_1: FloatArray, realized_vol_short: FloatArray) -> int:
    """Primeiro índice em que `log_return_1` E `realized_vol_short` são
    ambos finitos -- ver docstring do módulo pro achado real de que isso é
    `window`, não `window-1` (o `NaN` estrutural de `log_return_1[0]`
    propaga por toda janela que o contém). Levanta `ValueError` se a série
    inteira for inválida (curta demais pra sequer 1 barra pós-warmup)."""
    valid = np.isfinite(log_return_1) & np.isfinite(realized_vol_short)
    if not np.any(valid):
        raise ValueError(
            "_valid_start_idx: nenhuma barra com log_return_1 e realized_vol_short ambos "
            "finitos -- série curta demais (<= feature_c06_vol_ratio_short_window barras)?"
        )
    return int(np.argmax(valid))


def _forward_return(log_return_1: FloatArray) -> FloatArray:
    """`forward_return[t] = log_return_1[t+1]` -- decisão #2 do plano M4
    ("log-retorno de 1 barra à frente, direto do OHLC, não `ret_net`/Label
    Engine"). Última barra sem `t+1` -> `NaN` (filtrado por
    `anova_by_group`, não um erro)."""
    n = log_return_1.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        out[:-1] = log_return_1[1:]
    return out


# ============================================================================
# Dataclasses de resultado
# ============================================================================


@dataclass(frozen=True, slots=True)
class CandidateResult:
    """`fold_stability_adjusted_rand_min` -- campo ADICIONAL além do
    contrato original do plano (que só citava a média): o plano pede
    explicitamente "reporta média e mínimo entre pares" na mecânica de
    estabilidade entre folds -- reportar só a média perderia o pior caso
    (uma fronteira que muda muito entre 1 par de folds adjacentes fica
    escondida atrás de uma média boa nos outros pares). `NaN` (não erro)
    quando não há nenhum par de folds adjacentes com fit bem-sucedido dos
    dois lados (< 2 folds avaliados) -- ausência de medição, não zero."""

    classifier_id: str
    n_states: int
    separation: ANOVAResult
    orthogonality: ANOVAResult
    persistence: PersistenceMetrics
    fold_stability_adjusted_rand_mean: float
    fold_stability_adjusted_rand_min: float
    fold_stability_by_construction: bool
    n_oos_obs: int
    n_folds_evaluated: int


@dataclass(frozen=True, slots=True)
class SymbolResult:
    symbol: str
    n_bars: int
    n_folds: int
    baseline: CandidateResult
    candidates: tuple[CandidateResult, ...]


# ============================================================================
# Núcleo puro -- uma combinação (symbol), bars_df/baseline_df já em memória
# ============================================================================


def _oos_slice(splits: tuple[vwf.WalkForwardSplit, ...]) -> tuple[int, int]:
    return splits[0].test_start_idx, splits[-1].test_end_idx


def _assert_bars_baseline_aligned(
    bars_df: pl.DataFrame, baseline_df: pl.DataFrame, *, symbol: str
) -> None:
    """"Confirme alinhamento, não presuma" (instrução explícita da task).
    `run_regime_comparison_for_symbol` carrega os dois via o MESMO
    `(symbol, start, end)` -- deveriam bater sempre -- mas este núcleo
    puro não confia nisso silenciosamente: um caller futuro (Fase 4/Q3,
    por exemplo) que passe `bars_df`/`baseline_df` de janelas diferentes
    por engano precisa de um erro claro aqui, não um `ValueError`/`IndexError`
    críptico 200 linhas depois dentro de `anova_by_group`."""
    if bars_df.height != baseline_df.height:
        raise ValueError(
            f"compare_regime_candidates_for_symbol({symbol!r}): bars_df tem {bars_df.height} "
            f"linhas, baseline_df tem {baseline_df.height} -- não alinhados (mesmo "
            "symbol/start/end nos dois carregamentos?)"
        )
    bars_open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()
    baseline_open_time_ms = baseline_df["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    if not np.array_equal(bars_open_time_ms, baseline_open_time_ms):
        raise ValueError(
            f"compare_regime_candidates_for_symbol({symbol!r}): bars_df/baseline_df não "
            "estão alinhados por timestamp -- t0 (baseline_df) diverge de open_time "
            "(bars_df) em pelo menos uma posição"
        )


def _anova_or_degenerate(group_labels: IntArray, response: FloatArray) -> ANOVAResult:
    """Wrapper de `anova_by_group` tolerante ao caso "candidato degenerou
    num único estado na região OOS inteira" -- achado real medido nesta
    sessão (rodando `test_run_regime_comparison_for_symbol_btcusdt_sobre_
    dado_real` E o teste sintético equivalente): `fit_jump_model` com
    `jump_penalty` não calibrado pra escala do dado de entrada satura
    facilmente num único `canonical_id` em TODA a janela de teste
    trimestral (mesmo achado de escala documentado em `src.regime.
    jump_model`, item 6 do docstring do módulo -- "jump_penalty >= ~0.1
    já satura o modelo num único estado", e medido aqui que mesmo `0.01`
    satura em dado real de BTC/dollar-bar). O mesmo pode, em princípio,
    acontecer com HMM (`sticky_concentration` alto demais) ou BOCPD
    (`hazard_lambda` que nunca dispara changepoint).

    `anova_by_group` levanta `ValueError` nesse caso -- correto PARA ELA
    (é um primitivo genérico e `k<2` grupos não tem F-stat/ω² com sentido
    matemático) -- mas no M4 "o candidato degenerou" é em si uma MEDIÇÃO
    válida (prova que aquele hiperparâmetro é ruim pra este símbolo/fold),
    não um erro que deveria derrubar o resto da comparação (baseline +
    outros candidatos) do mesmo símbolo -- especialmente porque
    `run_and_save_m4_report` isola falha por SÍMBOLO (AG-019), não por
    candidato: sem este wrapper, 1 candidato degenerado perderia a
    medição dos outros 4+1 candidatos daquele símbolo inteiro. Retorna
    `ANOVAResult` com `f_stat`/`omega_squared`/`p_value` = `NaN`,
    `k_groups`/`n` reais (não inventados) -- logado via `structlog`, não
    escondido (B28)."""
    finite_mask = np.isfinite(response)
    n = int(np.sum(finite_mask))
    n_groups = int(np.unique(group_labels[finite_mask]).size) if n > 0 else 0
    if n_groups < 2 or n <= n_groups:
        logger.warning(
            "analysis.m4_regime_comparison.anova_degenerada",
            n_groups=n_groups,
            n=n,
        )
        return ANOVAResult(
            f_stat=float("nan"),
            omega_squared=float("nan"),
            p_value=float("nan"),
            k_groups=n_groups,
            n=n,
        )
    return anova_by_group(group_labels, response)


def _persistence_or_degenerate(group_labels: IntArray) -> PersistenceMetrics:
    """Mesma tolerância de `_anova_or_degenerate`, pro caso ainda mais
    extremo de `group_labels` vazio (TODOS os folds falharam o fit --
    `regime_persistence` levanta `ValueError` em array vazio, contrato
    correto pra um primitivo genérico, não pro harness que precisa
    reportar "nada mediu" sem derrubar o símbolo inteiro)."""
    if group_labels.shape[0] == 0:
        logger.warning("analysis.m4_regime_comparison.persistence_degenerada_vazia")
        return PersistenceMetrics(
            median_duration_bars=float("nan"), switch_rate=float("nan"), n_segments=0
        )
    return regime_persistence(group_labels)


def _compact_valid(
    labels: IntArray, *response_arrays: FloatArray
) -> tuple[IntArray, tuple[FloatArray, ...]]:
    """Remove posições com `_FOLD_FIT_FAILURE_SENTINEL` de `labels` E das
    respostas paralelas -- usado só pelos candidatos com refit por fold
    (HMM/Jump Model), onde um fold pode falhar isoladamente (dado
    insuficiente/convergência degenerada) sem invalidar os outros.

    **Caveat documentado, não escondido:** compactar (em vez de manter o
    buraco como `NaN`/gap) muda a interpretação de `regime_persistence`
    nas poucas barras adjacentes a um fold que falhou -- duas barras que
    não eram vizinhas na série real passam a ser vizinhas no array
    compactado, podendo criar/quebrar um "segmento" artificial na costura.
    Mesma classe de trade-off já aceita em
    `volatility_comparison._har_rv_forecast_var_dollar_bar` (pula fold sem
    ajuste, loga, segue) -- esperado ser raro (fits só falham com dado
    insuficiente/degenerado, incomum com `initial_train_years` real) e
    round-off pequeno frente ao tamanho da série OOS inteira quando
    ocorre."""
    valid_mask = labels != _FOLD_FIT_FAILURE_SENTINEL
    return labels[valid_mask], tuple(arr[valid_mask] for arr in response_arrays)


def _make_hmm_fit_fn(n_states: int, seed: int) -> Callable[[Float2DArray, int], Any]:
    """Fábrica de `fit_fn` fechado sobre `(n_states, seed)` -- função
    nomeada em vez de `lambda ... k=k: ...` dentro do generator de
    `hmm_states_grid`: mypy não consegue inferir o tipo de uma `lambda`
    definida dentro de uma expressão geradora sem essa indireção (achado
    real ao rodar `mypy --strict` sobre este módulo), e a captura tardia
    de `k` por `lambda` sem parâmetro default seria um bug clássico de
    closure (todas as 3 lambdas fechando sobre o MESMO `k` final do loop)
    -- o parâmetro explícito aqui evita as duas armadilhas de uma vez."""

    def _fit(obs: Float2DArray, train_end_idx: int) -> Any:
        return fit_hmm_gaussian(obs, n_states=n_states, train_end_idx=train_end_idx, seed=seed)

    return _fit


def _run_fold_refit_candidate(
    classifier_id: str,
    n_states: int,
    obs_2d: Float2DArray,
    splits: tuple[vwf.WalkForwardSplit, ...],
    *,
    fit_fn: Callable[[Float2DArray, int], Any],
    predict_fn: Callable[[Any, Float2DArray], IntArray],
    forward_return: FloatArray,
    vol_pctile: FloatArray,
) -> CandidateResult:
    """Núcleo compartilhado por HMM e Jump Model -- os dois têm o MESMO
    contrato de fold (B05: refit expansivo ancorado em `obs[:train_end_
    idx]`, decodifica só `obs[test_start_idx:test_end_idx]`), só diferem
    em `fit_fn`/`predict_fn`. `fit_fn(obs_2d, train_end_idx)` recebe o
    array COMPLETO (já cortado por `_valid_start_idx` no caller) + o
    índice -- o próprio `fit_hmm_gaussian`/`fit_jump_model` faz o corte
    `obs[:train_end_idx]` internamente (contrato já testado em
    `test_regime_hmm_gaussian.py`/`test_regime_jump_model.py`); este
    helper não pré-fatia pra não duplicar essa responsabilidade.

    **Estabilidade entre folds (decisão "adicionais" do plano):** para
    cada par de folds adjacentes `(k, k+1)` com fit bem-sucedido nos dois,
    decodifica o TESTE do fold `k` duas vezes -- com `fit[k]` e com
    `fit[k+1]` (que já viu esse trecho no treino, expansão ancorada) --
    compara via `adjusted_rand`. Mede se a fronteira de decisão muda ao
    aprender mais dado."""
    oos_start, oos_end = _oos_slice(splits)
    canonical_oos = np.full(oos_end - oos_start, _FOLD_FIT_FAILURE_SENTINEL, dtype=np.int64)

    fits: list[Any] = []
    n_folds_evaluated = 0
    for split in splits:
        fit = fit_fn(obs_2d, split.train_end_idx)
        fits.append(fit)
        if fit is None:
            logger.warning(
                "analysis.m4_regime_comparison.fold_fit_none",
                classifier_id=classifier_id,
                fold_id=split.fold_id,
                train_end_idx=split.train_end_idx,
            )
            continue
        n_folds_evaluated += 1
        labels = predict_fn(fit, obs_2d[split.test_start_idx : split.test_end_idx])
        canonical_oos[split.test_start_idx - oos_start : split.test_end_idx - oos_start] = labels

    aris: list[float] = []
    for k in range(len(splits) - 1):
        fit_k, fit_next = fits[k], fits[k + 1]
        if fit_k is None or fit_next is None:
            continue
        split_k = splits[k]
        test_slice = obs_2d[split_k.test_start_idx : split_k.test_end_idx]
        labels_own = predict_fn(fit_k, test_slice)
        labels_under_next_fold_params = predict_fn(fit_next, test_slice)
        aris.append(adjusted_rand(labels_own, labels_under_next_fold_params))

    labels_valid, (forward_return_valid, vol_pctile_valid) = _compact_valid(
        canonical_oos, forward_return[oos_start:oos_end], vol_pctile[oos_start:oos_end]
    )
    separation = _anova_or_degenerate(labels_valid, forward_return_valid)
    orthogonality = _anova_or_degenerate(labels_valid, vol_pctile_valid)
    persistence = _persistence_or_degenerate(labels_valid)

    return CandidateResult(
        classifier_id=classifier_id,
        n_states=n_states,
        separation=separation,
        orthogonality=orthogonality,
        persistence=persistence,
        fold_stability_adjusted_rand_mean=float(np.mean(aris)) if aris else float("nan"),
        fold_stability_adjusted_rand_min=float(np.min(aris)) if aris else float("nan"),
        fold_stability_by_construction=False,
        n_oos_obs=int(labels_valid.shape[0]),
        n_folds_evaluated=n_folds_evaluated,
    )


def _bocpd_candidate_result(
    log_return_1: FloatArray,
    oos_start: int,
    oos_end: int,
    *,
    hazard_lambda: float,
    n_canonical_buckets: int,
    forward_return: FloatArray,
    vol_pctile: FloatArray,
) -> CandidateResult:
    """BOCPD roda UMA VEZ sobre a série causal INTEIRA (`log_return_1`, já
    cortado por `_valid_start_idx` no caller) -- nunca por fold (decisão
    #1 do plano: online por construção, refazer por fold seria uma
    re-execução artificial que o plano proíbe explicitamente). As MÉTRICAS
    ainda são avaliadas só sobre `[oos_start:oos_end]` -- mesma janela
    temporal que HMM/Jump Model/baseline, pra comparação justa (só o FIT
    é diferente, não a janela de avaliação).

    Composição estados brutos -> canônico (decisão "adicionais" do plano):
    `segments_to_canonical_states` primeiro agrupa segmentos em `n_
    canonical_buckets` por quantil do retorno médio do segmento (já produz
    uma ordem ascendente por construção, ver docstring de `bocpd.py`), e o
    resultado passa de novo por `canonicalize_states` -- não é redundante:
    garante o MESMO critério exato (média ascendente, desempate por
    variância) usado por HMM/Jump Model, em vez de confiar no critério de
    ordenação por quantil de segmento (que não empata do mesmo jeito)."""
    bocpd_out = run_bocpd(log_return_1, hazard_lambda=hazard_lambda)
    bucket_by_bar = segments_to_canonical_states(
        bocpd_out.segment_id, log_return_1, n_buckets=n_canonical_buckets
    )
    canonical_id_full = canonicalize_states(bucket_by_bar, log_return_1).canonical_id

    labels_oos = canonical_id_full[oos_start:oos_end]
    separation = _anova_or_degenerate(labels_oos, forward_return[oos_start:oos_end])
    orthogonality = _anova_or_degenerate(labels_oos, vol_pctile[oos_start:oos_end])
    persistence = _persistence_or_degenerate(labels_oos)

    return CandidateResult(
        classifier_id=BOCPD_CLASSIFIER_ID,
        n_states=n_canonical_buckets,
        separation=separation,
        orthogonality=orthogonality,
        persistence=persistence,
        # Por construção, não medido -- ver docstring do módulo/CandidateResult.
        fold_stability_adjusted_rand_mean=1.0,
        fold_stability_adjusted_rand_min=1.0,
        fold_stability_by_construction=True,
        n_oos_obs=separation.n,
        n_folds_evaluated=0,
    )


def _baseline_candidate_result(
    regime_physical: IntArray,
    oos_start: int,
    oos_end: int,
    *,
    forward_return: FloatArray,
    vol_pctile: FloatArray,
    classifier_id: str,
) -> CandidateResult:
    """`QuantileRegimeClassifier` -- state machine determinística causal,
    sem fit nenhum (mesmo raciocínio do BOCPD pra `fold_stability_by_
    construction=True`: não existe "outro fit" pra comparar). R0
    (`_BASELINE_R0_PHYSICAL_ID`) excluído das métricas -- ver docstring do
    módulo."""
    regime_oos = regime_physical[oos_start:oos_end]
    forward_return_oos = forward_return[oos_start:oos_end]
    vol_pctile_oos = vol_pctile[oos_start:oos_end]

    non_r0_mask = regime_oos != _BASELINE_R0_PHYSICAL_ID
    labels_valid = regime_oos[non_r0_mask]
    forward_return_valid = forward_return_oos[non_r0_mask]
    vol_pctile_valid = vol_pctile_oos[non_r0_mask]

    separation = _anova_or_degenerate(labels_valid, forward_return_valid)
    orthogonality = _anova_or_degenerate(labels_valid, vol_pctile_valid)
    persistence = _persistence_or_degenerate(labels_valid)

    return CandidateResult(
        classifier_id=classifier_id,
        n_states=_BASELINE_N_STATES,
        separation=separation,
        orthogonality=orthogonality,
        persistence=persistence,
        fold_stability_adjusted_rand_mean=1.0,
        fold_stability_adjusted_rand_min=1.0,
        fold_stability_by_construction=True,
        n_oos_obs=separation.n,
        n_folds_evaluated=0,
    )


def compare_regime_candidates_for_symbol(
    symbol: str,
    bars_df: pl.DataFrame,
    baseline_df: pl.DataFrame,
    *,
    initial_train_years: int,
    hmm_states_grid: tuple[int, ...] = (2, 3, 4),
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = 0,
    jump_seed: int = 0,
) -> SymbolResult | None:
    """Núcleo puro (sem IO) -- recebe `bars_df`/`baseline_df` já
    carregados (mesmo `(symbol, start, end)`, ver `_assert_bars_baseline_
    aligned`), monta as métricas dos 3+1 candidatos sobre os folds OOS do
    walk-forward. Retorna `None` se não houver folds suficientes (dado
    insuficiente pra `initial_train_years` de treino inicial) -- mesmo
    contrato de `volatility_comparison.compare_estimators_for_
    combination`, sinal explícito pro chamador pular o símbolo."""
    _assert_bars_baseline_aligned(bars_df, baseline_df, symbol=symbol)

    log_return_1_full, obs_2d_full = _input_obs(bars_df)
    valid_start_idx = _valid_start_idx(log_return_1_full, obs_2d_full[:, 1])

    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()[valid_start_idx:]
    log_return_1 = log_return_1_full[valid_start_idx:]
    obs_2d = obs_2d_full[valid_start_idx:]
    forward_return = _forward_return(log_return_1)
    vol_pctile = baseline_df["vol_pctile"].cast(pl.Float64).to_numpy()[valid_start_idx:]
    regime_physical = (
        baseline_df["regime"].to_physical().cast(pl.Int64).to_numpy()[valid_start_idx:]
    )
    baseline_classifier_id = str(baseline_df["classifier_id"][0])

    splits = vwf.generate_anchored_walk_forward_splits(
        open_time_ms, initial_train_years=initial_train_years
    )
    if not splits:
        logger.warning(
            "analysis.m4_regime_comparison.folds_insuficientes",
            symbol=symbol,
            n_bars=bars_df.height,
            n_bars_pos_trim=int(obs_2d.shape[0]),
        )
        return None
    oos_start, oos_end = _oos_slice(splits)

    baseline_result = _baseline_candidate_result(
        regime_physical,
        oos_start,
        oos_end,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
        classifier_id=baseline_classifier_id,
    )

    hmm_results = tuple(
        _run_fold_refit_candidate(
            hmm_gaussian_classifier_id(k),
            k,
            obs_2d,
            splits,
            fit_fn=_make_hmm_fit_fn(k, hmm_seed),
            predict_fn=predict_hmm_gaussian,
            forward_return=forward_return,
            vol_pctile=vol_pctile,
        )
        for k in hmm_states_grid
    )

    jump_result = _run_fold_refit_candidate(
        JUMP_MODEL_CLASSIFIER_ID,
        jump_n_states,
        obs_2d,
        splits,
        fit_fn=lambda obs, train_end_idx: fit_jump_model(
            obs,
            n_states=jump_n_states,
            jump_penalty=jump_penalty,
            train_end_idx=train_end_idx,
            seed=jump_seed,
        ),
        predict_fn=predict_jump_model,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
    )

    bocpd_result = _bocpd_candidate_result(
        log_return_1,
        oos_start,
        oos_end,
        hazard_lambda=bocpd_hazard_lambda,
        n_canonical_buckets=bocpd_n_canonical_buckets,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
    )

    return SymbolResult(
        symbol=symbol,
        n_bars=bars_df.height,
        n_folds=len(splits),
        baseline=baseline_result,
        candidates=(*hmm_results, jump_result, bocpd_result),
    )


# ============================================================================
# Ponto de entrada com IO -- um símbolo, ou os 5
# ============================================================================


def run_regime_comparison_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = None,
    hmm_states_grid: tuple[int, ...] = (2, 3, 4),
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = 0,
    jump_seed: int = 0,
) -> SymbolResult | None:
    """Carrega `bars_df` (`lake.query_dollar_bars`) e `baseline_df`
    (`build_regimes(..., bar_source="dollar_r1")`) reais do disco, com o
    MESMO `(symbol, start, end)` nos dois (garante o alinhamento que
    `_assert_bars_baseline_aligned` confirma no núcleo puro), delega o
    resto pra `compare_regime_candidates_for_symbol`.

    `initial_train_years=None` (default) resolve pra `m1_walkforward_
    initial_train_years` (`constants.yaml`) -- mesmo protocolo do M1,
    reusado, não duplicado (decisão #6/plano: M4 reusa o splitter do M1
    sem alterar).

    `build_regimes` não expõe throttle de DuckDB (`memory_limit_gb`/
    `threads`) -- gap conhecido, herdado do módulo, não corrigido aqui
    (fora do escopo do harness M4; `bars_df` (carregado diretamente por
    esta função) É throttled via `m4_duckdb_memory_limit_gb`/`m4_duckdb_
    threads`, mesma convenção de M1/M2/M3 sob `ProcessPoolExecutor`)."""
    train_years = (
        initial_train_years
        if initial_train_years is not None
        else int(load_validation_constant("m1_walkforward_initial_train_years"))
    )

    throttle = lake.DuckDBThrottle(
        memory_limit_gb=float(load_data_constant("m4_duckdb_memory_limit_gb")),
        threads=int(load_data_constant("m4_duckdb_threads")),
    )
    bars_df = lake.query_dollar_bars(
        symbol,
        start,
        end,
        resolution_id=RESOLUTION_ID,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    baseline_df = build_regimes(symbol, start, end, bar_source="dollar_r1")

    logger.info(
        "analysis.m4_regime_comparison.bars_loaded",
        symbol=symbol,
        n_bars=bars_df.height,
        n_bars_baseline=baseline_df.height,
        start=start,
        end=end,
    )
    return compare_regime_candidates_for_symbol(
        symbol,
        bars_df,
        baseline_df,
        initial_train_years=train_years,
        hmm_states_grid=hmm_states_grid,
        jump_n_states=jump_n_states,
        jump_penalty=jump_penalty,
        bocpd_hazard_lambda=bocpd_hazard_lambda,
        bocpd_n_canonical_buckets=bocpd_n_canonical_buckets,
        hmm_seed=hmm_seed,
        jump_seed=jump_seed,
    )


# ============================================================================
# Relatório -- JSON atômico, mesmo padrão de volatility_comparison.py
# ============================================================================

_BASELINE_VOL_ESTIMATOR_CAVEAT: Final[str] = (
    "QuantileRegimeClassifier (baseline) roda hoje sobre C07_vol_pctile_expanding, que "
    "compute_t1_features constroi sobre ATR-Wilder (vol_estimator_id=None), NAO "
    "Garman-Klass/Parkinson -- apesar de constants.yaml::canonical_volatility_estimator "
    "declarar garman_klass_w20, compute_t1_features so aceita vol_estimator_id=None "
    "(ATR-Wilder) ou 'parkinson_w{N}'. Leia este relatorio como 'ATR-Wilder vs. "
    "candidatos novos', nao 'GK vs. candidatos novos' (ver PRD_V4_1.md M4 e plano "
    "wise-exploring-panda.md, secao 'O que ja existe')."
)

_Q3_COMMON_FACTOR_NOTE: Final[str] = (
    "Terceira via (Q3, BTC como fator comum via as-of join causal) e a Fase 4 do plano "
    "wise-exploring-panda.md, NAO implementada neste relatorio. "
    "compare_regime_candidates_for_symbol foi desenhada para a Fase 4 reusar, mas "
    "CandidateResult hoje so expoe metricas agregadas (nao os arrays de canonical_id "
    "por barra nem os objetos de fit por fold) -- ver docstring do modulo, secao Q3."
)


def _candidate_to_dict(result: CandidateResult) -> dict[str, Any]:
    return {
        "classifier_id": result.classifier_id,
        "n_states": result.n_states,
        "separation": asdict(result.separation),
        "orthogonality": asdict(result.orthogonality),
        "persistence": asdict(result.persistence),
        "fold_stability_adjusted_rand_mean": result.fold_stability_adjusted_rand_mean,
        "fold_stability_adjusted_rand_min": result.fold_stability_adjusted_rand_min,
        "fold_stability_by_construction": result.fold_stability_by_construction,
        "n_oos_obs": result.n_oos_obs,
        "n_folds_evaluated": result.n_folds_evaluated,
    }


def _symbol_result_to_dict(result: SymbolResult) -> dict[str, Any]:
    return {
        "symbol": result.symbol,
        "n_bars": result.n_bars,
        "n_folds": result.n_folds,
        "baseline": _candidate_to_dict(result.baseline),
        "candidates": [_candidate_to_dict(c) for c in result.candidates],
    }


def _atomic_write_json(payload: dict[str, Any], dest_path: Path) -> None:
    """B29 -- mesmo padrão de `volatility_comparison._atomic_write_json`."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)
    logger.info("analysis.m4_regime_comparison.report_written", path=str(dest_path))


def run_and_save_m4_report(
    *,
    symbols: tuple[str, ...] = ALL_SYMBOLS,
    dest_path: Path | None = None,
    max_workers: int | None = None,
    initial_train_years: int | None = None,
    hmm_states_grid: tuple[int, ...] = (2, 3, 4),
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = 0,
    jump_seed: int = 0,
) -> Path:
    """Ponto de entrada real -- roda os `len(symbols)` símbolos (5 por
    default) em paralelo (`ProcessPoolExecutor`, um processo por símbolo,
    mesmo padrão de `run_and_save_volatility_comparison_report`), persiste
    o relatório atômico (B29).

    **NÃO CHAME esta função contra os 5 símbolos completos sem autorização
    explícita do Manager** (Fase 6 do plano `wise-exploring-panda.md`) --
    consome orçamento de trial (`G-C1-2: M4 emitido com <=6 trials`,
    `audit/n_lifetime.yaml`). Todos os hiperparâmetros de candidato são
    obrigatórios (sem default) de propósito -- ver docstring do módulo.

    Chame manualmente (só depois da autorização acima):
    `uv run python -c "from src.analysis.m4_regime_comparison import
    run_and_save_m4_report as r; r(jump_n_states=..., jump_penalty=...,
    bocpd_hazard_lambda=..., bocpd_n_canonical_buckets=...)"`"""
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    logger.info(
        "analysis.m4_regime_comparison.starting",
        n_symbols=len(symbols),
        max_workers=workers,
    )

    t0 = time.perf_counter()
    results: list[SymbolResult] = []
    skipped: list[dict[str, str]] = []
    failed_tasks: list[dict[str, str]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_to_symbol = {
            executor.submit(
                run_regime_comparison_for_symbol,
                symbol,
                SYMBOL_START_DATE[symbol],
                END_DATE,
                initial_train_years=initial_train_years,
                hmm_states_grid=hmm_states_grid,
                jump_n_states=jump_n_states,
                jump_penalty=jump_penalty,
                bocpd_hazard_lambda=bocpd_hazard_lambda,
                bocpd_n_canonical_buckets=bocpd_n_canonical_buckets,
                hmm_seed=hmm_seed,
                jump_seed=jump_seed,
            ): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            # AG-019 -- 1 task falhando não derruba as outras (mesmo
            # padrão de volatility_comparison/m2_bar_comparison).
            try:
                result = future.result()
            except Exception as exc:
                failed_tasks.append({"symbol": symbol})
                logger.error(
                    "analysis.m4_regime_comparison.task_failed", symbol=symbol, error=repr(exc)
                )
                continue
            if result is None:
                skipped.append({"symbol": symbol, "reason": "folds_insuficientes"})
                continue
            results.append(result)
            logger.info(
                "analysis.m4_regime_comparison.symbol_done",
                symbol=symbol,
                n_folds=result.n_folds,
                baseline_separation_omega_sq=round(result.baseline.separation.omega_squared, 6),
            )

    if failed_tasks:
        logger.warning(
            "analysis.m4_regime_comparison.tasks_failed",
            n_failed=len(failed_tasks),
            n_symbols=len(symbols),
            failed=failed_tasks,
        )

    elapsed_s = time.perf_counter() - t0
    # ProcessPoolExecutor.as_completed devolve em ordem de conclusão --
    # ordena pra o relatório final ser determinístico.
    results.sort(key=lambda r: r.symbol)

    payload: dict[str, Any] = {
        **report_provenance(),
        "n_symbols_requested": len(symbols),
        "n_symbols_evaluated": len(results),
        "skipped": skipped,
        "failed": failed_tasks,
        "elapsed_seconds_total": elapsed_s,
        "baseline_volatility_estimator_caveat": _BASELINE_VOL_ESTIMATOR_CAVEAT,
        "q3_common_factor_note": _Q3_COMMON_FACTOR_NOTE,
        "symbols": [_symbol_result_to_dict(r) for r in results],
    }
    dest = dest_path if dest_path is not None else DEFAULT_REPORT_PATH
    _atomic_write_json(payload, dest)
    logger.info(
        "analysis.m4_regime_comparison.done",
        n_symbols_evaluated=len(results),
        n_skipped=len(skipped),
        n_failed=len(failed_tasks),
        elapsed_seconds_total=round(elapsed_s, 1),
        dest=str(dest),
    )
    return dest


if __name__ == "__main__":
    raise SystemExit(
        "src.analysis.m4_regime_comparison: run_and_save_m4_report requer "
        "hiperparâmetros calibrados (jump_n_states, jump_penalty, bocpd_hazard_lambda, "
        "bocpd_n_canonical_buckets) que ainda dependem de confirmação do Manager "
        "(Fase 6 do plano wise-exploring-panda.md) -- não rode este módulo como script "
        "ainda. Ver docstring de run_and_save_m4_report para como chamar manualmente "
        "depois da autorização."
    )
