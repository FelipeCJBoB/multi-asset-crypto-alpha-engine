"""M4 — harness de orquestração da comparação de classificadores de regime
(`PRD_V4_1.md` §3.2), Fase 3 do plano `wise-exploring-panda.md`. Mesma
classe de módulo que `src.analysis.volatility_comparison` (M1)/
`src.analysis.m2_bar_comparison` (M2): ponto de entrada manual, IO real,
NUNCA dentro da suíte automatizada além de 1 smoke test `integration`/
`slow`.

**4 candidatos novos + baseline, 5 trials neste harness + 1 trial da
Terceira via (Q3, `run_q3_common_factor_regime`) = 6 trials no total do
estudo M4 (decisão #5 do plano, confirmação pendente do Manager antes da
Fase 6) — achado de auditoria (`project_assurance`, 2026-08-17): a
itemização abaixo soma 5, não 6; o 6º trial é Q3, fora deste módulo, não
um candidato a mais aqui.** baseline (`QuantileRegimeClassifier`, 0
trial, produção) · HMM gaussiano k=2/3/4 (`src.regime.hmm_gaussian`, 3
trials) · Jump Model contínuo/CJM (`src.regime.jump_model`, 1 trial) ·
BOCPD (`src.regime.bocpd`, 1 trial). Grade de símbolo (5 ativos) NÃO
multiplica trial, mesma convenção de `AG-039`/M1.

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

**Caveat do Jump Model — decode em BLOCO, declarado explicitamente no
relatório final (não escondido), mesmo padrão do débito do baseline acima
— decisão do Manager, 2026-08-18.** `predict_jump_model`
(`src.regime.jump_model`) decodifica o fold de teste inteiro numa única
chamada de `fit.model.predict()` (Viterbi GLOBAL de `jumpmodels.jump.dp`)
— o forward pass é causal, mas o traceback anda de trás pra frente a
partir de `assign[-1]`, então o rótulo canônico numa barra `t` PODE
depender de uma observação em `t' > t` DENTRO DO MESMO FOLD DE TESTE
(confirmado empiricamente, não só por leitura de código — ver docstring
de `src.regime.jump_model` e
`test_perturbar_fim_do_fold_pode_mudar_inicio_do_mesmo_fold`). Isso NUNCA
cruza fronteira de fold e NUNCA toca dado de treino (`fit.model` já está
ajustado — `centers_`/`jump_penalty_mx` congelados — antes de
`predict_jump_model` ser chamada). É DIFERENTE de HMM
(`predict_hmm_gaussian`, via `hmm.filter`, posterior estritamente causal
barra-a-barra mesmo dentro do fold) e de BOCPD (online por construção,
sem noção de fold nenhuma) — os outros 2 candidatos novos nunca veem nada
além do passado, nem dentro do próprio fold. Decisão ratificada: manter
`.predict()` como está (não trocar para `.predict_online()`, que É causal
barra-a-barra mas não replica o desenho real do walk-forward do M4 —
decodificar o fold de teste inteiro de uma vez). Leia o resultado do Jump
Model com essa ressalva: ele pode carregar uma vantagem de decodificação
não relacionada à qualidade real de detecção de regime.
`_JUMP_MODEL_CAUSALITY_CAVEAT` carrega essa frase no payload persistido,
mesmo padrão de `_BASELINE_VOL_ESTIMATOR_CAVEAT`.

**Fase 4 (Q3, terceira via) — IMPLEMENTADA.** Rota (a) da limitação
documentada na Fase 3 (duas rotas foram citadas ali, nenhuma implementada)
foi a escolhida: `_run_fold_refit_candidate`/`_bocpd_candidate_result`/
`_baseline_candidate_result` ganharam um parâmetro `return_raw_labels:
bool = False` (default preserva o contrato exato da Fase 3 — devolve só
`CandidateResult`, testado por `tests/unit/test_analysis_m4_regime_
comparison.py` sem nenhuma mudança de comportamento); quando `True`,
devolvem `tuple[CandidateResult, RawLabels]`. `RawLabels` é um dataclass
IRMÃO de `CandidateResult` (`open_time_ms`/`canonical_id` alinhados por
TIMESTAMP, não por índice posicional — Q3 precisa fazer `join_asof` entre
ativos com timestamps de dollar-bar DIFERENTES, BTC e XRP não têm as
mesmas barras), NUNCA um array dentro do dataclass existente (quebraria a
serialização JSON de `_candidate_to_dict`/`run_and_save_m4_report` e
infiaria o relatório de produção com dado que ele não deveria carregar —
decisão do plano, não decidida sozinha aqui). `RawLabels` expõe
exatamente o subconjunto VÁLIDO usado para calcular as métricas do
`CandidateResult` irmão (pós-exclusão de R0 no baseline, pós-compactação
de fold falho em HMM/Jump Model) — nunca o sentinela `_FOLD_FIT_FAILURE_
SENTINEL`/R0, que não são rótulo de regime real e não deveriam ser
propagados por um `join_asof` como se fossem.

`compare_regime_candidates_for_symbol` propaga o mesmo parâmetro —
internamente SEMPRE chama os 3 helpers com `return_raw_labels=True`
(custo desprezível: só fatiamento de array já calculado, não refit) e
decide expor ou descartar o `dict[str, RawLabels]` resultante conforme o
`return_raw_labels` recebido de fora. Hardcodar o literal internamente
(em vez de repassar a variável `bool` recebida) também resolve um
problema real de tipagem: os 3 helpers são `@overload`ados por
`Literal[True]`/`Literal[False]` (pra que o tipo de retorno mude
corretamente com o valor do parâmetro, sem quebrar `mypy --strict` nos
callers da Fase 3 que nunca passam `return_raw_labels`), e um argumento
de tipo `bool` puro não casa com nenhuma das duas variantes de overload —
só um literal explícito resolve. `run_regime_comparison_for_symbol`
propaga o mesmo parâmetro (IO real), pelo mesmo motivo com um `if/else`
explícito em vez de repassar a variável.

`run_q3_common_factor_regime` (nova): AGNÓSTICA a qual dos 4 candidatos é
testado — recebe `classifier_id` como parâmetro (lookup no dict de
`RawLabels`, nunca um `if classifier_id == "..."` hardcoded) porque qual
candidato "vence" o M4 só é sabido depois da execução real (Fase 6, ainda
não rodou — decisão de escopo do plano, não desta função). Recebe o
resultado JÁ CALCULADO de `compare_regime_candidates_for_symbol(...,
return_raw_labels=True)` pro BTC (reusa, não recomputa — "Terceira via Q3
reusa fits, sem reajuste novo", plano); para cada um dos outros símbolos,
chama `run_regime_comparison_for_symbol(..., return_raw_labels=True)` de
novo com os MESMOS hiperparâmetros — reaproveita a MESMA função da Fase
3/IO real, zero lógica de fold/candidato duplicada (custo aceito, não
escondido: roda os 6 candidatos por ativo, não só o pedido — ver docstring
da função). `_asof_join_btc_labels` faz o `join_asof(strategy="backward")`
— prova de causalidade central do DoD do plano (Q3/as-of join): barra do
ativo em `t` recebe o rótulo de BTC mais recente com timestamp `<= t`,
NUNCA um timestamp futuro. Sobreposição temporal parcial (ex. ativo com
histórico mais curto que BTC — situação REAL: BTC desde 2019-12-31, os 4
alts só desde 2021-12-01) tratada explicitamente: barras do ativo sem
rótulo de BTC disponível ainda são EXCLUÍDAS da métrica antes do Rand
ajustado, nunca um crash.

**Fase B do plano `wise-exploring-panda.md` (`docs/m4_regime_plano_
execucao.md` §"Decisões do Manager") -- `resolution_id` NOVO em
`run_regime_comparison_for_symbol` (mudança de INTERFACE, não de
comportamento).** Antes desta fase, `run_regime_comparison_for_symbol`
tinha `resolution_id="R1"` implícito hardcoded em duas chamadas
independentes (`lake.query_dollar_bars(..., resolution_id=RESOLUTION_ID)`
e `build_regimes(..., bar_source="dollar_r1")`) -- rodar M4 sob R2/R3
("resolução multiplica trial", decisão do Manager 2026-08-18, `AG-042`:
R1/R2/R3 SÃO os 3 timeframes de produção) exigia editar o módulo por
resolução. `resolution_id: str = RESOLUTION_ID` (default `"R1"`, preserva
bit-a-bit todo caller existente que não passa o argumento -- mesmo
protocolo já usado por `return_raw_labels` na Fase 4) agora seleciona as
DUAS chamadas juntas: `lake.query_dollar_bars(..., resolution_id=
resolution_id)` e `build_regimes(..., bar_source=f"dollar_{resolution_id.
lower()}")` -- a mesma convenção `f"dollar_{resolution_id.lower()}"` já
usada por `src.features._sources.load_bars`/`src.data.build_dollar_bars.
_source_name`, não uma nova. `compare_regime_candidates_for_symbol`
(núcleo puro) não muda -- já recebe `bars_df`/`baseline_df` prontos,
agnóstico a qual resolução os produziu. `run_and_save_m4_report`/`run_q3_
common_factor_regime` continuam sem esse parâmetro (fora de escopo desta
fase -- ambos continuam R1-only; o orquestrador de janelas críticas que
consome R2/R3 é `src.analysis.m4_critical_windows`, módulo companheiro
novo, não uma extensão deste arquivo -- ver docstring de lá pro porquê de
não ter entrado aqui: este arquivo já tinha ~1650 linhas antes desta
fase).

**`run_and_save_m4_report` NÃO É CHAMADA POR ESTE MÓDULO.** Todos os
hiperparâmetros de candidato (`jump_n_states`, `jump_penalty`,
`bocpd_hazard_lambda`, `bocpd_n_canonical_buckets`) são obrigatórios (sem
default) — decisão deliberada: os valores calibrados ainda dependem de
confirmação do Manager (Fase 6 do plano) e de constantes que ainda não
existem em `constants.yaml` (bloqueadas de propósito, ver plano seção
"Arquivos modificados"). Chamar esta função com valores inventados seria
exatamente o tipo de "faixa esperada inventada" que B23/CLAUDE.md proíbe.
`if __name__ == "__main__":` deste módulo levanta `SystemExit` com essa
explicação em vez de rodar um report real por engano.

**Throttle de threads BLAS/polars/JAX — achado HIGH de auditoria
(`audit_engineering`, 2026-08-17), corrigido, não só reportado.**
`run_and_save_m4_report` roda até `len(symbols)` processos concorrentes
via `ProcessPoolExecutor`; cada um faz fits de HMM (JAX/dynamax) além de
numpy/scipy/polars. Sem throttle, um ÚNICO processo rodando
`fit_hmm_gaussian` sem guarda abre ~90 threads de SO nesta máquina de 12
núcleos lógicos (medido via `Get-Process <pid> | Threads.Count` durante
um fit real) — mesma classe de bug já confirmada em produção no M2
(`ArrayMemoryError` sob N processos concorrentes cada um multi-thread,
`m2_worker.py`), agora pior porque JAX/dynamax é novo neste módulo (M2/M3
não usam JAX). Bloco `os.environ.setdefault(...)` no topo do arquivo
(antes de qualquer import de terceiro) reduz isso pra ~6 threads/processo
(medido) — `XLA_FLAGS` é a peça nova (`--xla_cpu_multi_thread_eigen=false
intra_op_parallelism_threads=1`), o resto (`OMP_NUM_THREADS`/
`MKL_NUM_THREADS`/`OPENBLAS_NUM_THREADS`/`NUMEXPR_NUM_THREADS`/
`POLARS_MAX_THREADS`) é o mesmo bloco já usado em `m2_worker.py`.

**`mp_context="spawn"` explícito no `ProcessPoolExecutor` — 2º achado HIGH
da mesma auditoria, mesmo motivo raiz (JAX).** Sem isso, o start method é
o padrão da PLATAFORMA -- `spawn` no Windows (onde este módulo roda hoje),
mas `fork` no Linux (produção deste motor). JAX documenta explicitamente
que não é fork-safe (multi-thread internamente; `fork()` depois de
threads ativas é deadlock clássico, `jax-ml/jax#1805`). `run_and_save_m4_
report` agora força `multiprocessing.get_context("spawn")` -- mesmo
comportamento observável no Windows, determinístico em qualquer SO."""

from __future__ import annotations

import os

# Oversubscription de threads BLAS/polars/JAX -- `run_and_save_m4_report`
# paraleliza no nível de PROCESSO via `ProcessPoolExecutor` (até
# `len(symbols)` workers, tipicamente 5). Sem isso, cada um dos N
# processos TAMBÉM deixa numpy/scipy (BLAS), polars E JAX/dynamax
# (`fit_hmm_gaussian`, `src.regime.hmm_gaussian`) abrirem seu próprio
# pool de threads interno -- N processos x M threads cada competem pelos
# mesmos núcleos. Mesma causa raiz já confirmada em `m2_worker.py`
# (`numpy._core._exceptions._ArrayMemoryError` sob 12 processos
# concorrentes cada um multi-thread, 2026-08-15) -- aqui medido de novo,
# pior: um ÚNICO processo rodando `fit_hmm_gaussian` (JAX/dynamax) SEM
# throttle abre ~90 threads de SO nesta máquina de 12 núcleos lógicos
# (medido via `Get-Process <pid> | Threads.Count` amostrado durante um
# fit real, sessão de auditoria 2026-08-17); com o throttle abaixo
# (`XLA_FLAGS` + `OMP_NUM_THREADS=1` etc.) cai pra ~6. `XLA_FLAGS` é
# NOVO aqui (M2/M3 não usam JAX) -- `--xla_cpu_multi_thread_eigen=false`
# desliga o pool Eigen da XLA CPU backend, `intra_op_parallelism_
# threads=1` reforça; os demais são o mesmo bloco de `m2_worker.py`
# (numpy/scipy/polars). Precisa ser setado ANTES de importar
# jax/numpy/polars/scipy -- no Windows (spawn, não fork) cada worker do
# `ProcessPoolExecutor` reexecuta o módulo inteiro do zero, então isso
# vale em CADA processo filho, não só no principal (mesmo raciocínio de
# `m2_worker.py`, ver docstring de lá).
os.environ.setdefault(
    "XLA_FLAGS", "--xla_cpu_multi_thread_eigen=false intra_op_parallelism_threads=1"
)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("POLARS_MAX_THREADS", "1")

import multiprocessing
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Literal, overload

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
from src.regime import classifier, hmm_features
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

# R5 (stress, sempre o ÚLTIMO índice do Enum REGIME_LABELS -- mesma
# fonte/confirmação de _BASELINE_R0_PHYSICAL_ID). Extensão de qualidade-
# de-gate (AG-114, 2026-08-20): o baseline já tem rótulo semântico de
# stress (R5, `src.regime.classifier.TRADEABLE_REGIMES`), diferente dos
# outros 4 candidatos que só expõem `canonical_id` cru -- ver
# `src.validation.regime_utility.identify_stress_state_by_volatility` pra
# convenção equivalente nesses. Usado em `m4_critical_windows.py`, não
# neste módulo diretamente.
_BASELINE_R5_PHYSICAL_ID: Final[int] = len(classifier.REGIME_LABELS) - 1

# Sentinela de fold sem fit bem-sucedido (fit_hmm_gaussian/fit_jump_model
# retornam None em convergência degenerada/dado insuficiente) -- nunca um
# canonical_id real (canonicalize_states/predict_* sempre devolvem >= 0
# nos caminhos usados aqui, nenhum ignore_value é passado).
_FOLD_FIT_FAILURE_SENTINEL: Final[int] = -1


# ============================================================================
# Espaço de features -- direto do OHLC da dollar-bar, sem IO
# ============================================================================
#
# Extraído para `src.regime.hmm_features` (Fase B do plano
# `wise-exploring-panda.md`, 2026-08-21) -- `src.regime.build_hmm` (builder
# de produção do candidato HMM canônico) precisa desta extração sem
# depender deste harness de comparação. Re-exportado aqui sob o nome
# privado original (`_input_obs`/`_valid_start_idx`) para preservar os ~9
# pontos de teste existentes (`tests/unit/test_analysis_m4_regime_
# comparison.py`) sem nenhuma mudança de comportamento -- mesmo código,
# módulo diferente.


_input_obs = hmm_features.input_obs
_valid_start_idx = hmm_features.valid_start_idx


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


def _forward_realized_vol(realized_vol_short: FloatArray, window: int) -> FloatArray:
    """`forward_realized_vol[t] = realized_vol_short[t+window]` --
    generalização de `_forward_return` (h=1 -> h=`window`) pra métrica
    primária de ranking da extensão de qualidade-de-gate (AG-114,
    2026-08-20, `PLANO_MESTRE_PRINCE2.md §15.12.1`): separação de
    VOLATILIDADE futura entre buckets de regime, não retorno -- ADR-001
    §2.7 (ratificado) decide que regime é GATE, não feature, na v1, e um
    gate precisa detectar risco de cauda elevado, não prever retorno
    médio.

    Reusa o array que `_input_obs` já computa (`realized_vol_short` é uma
    janela ROLANTE BACKWARD de `window` barras terminando em `t`, mesma
    função `features_support.realized_vol` usada por
    `RealizedVolEstimator`) -- deslocar essa mesma série `window` posições
    pra frente dá exatamente a volatilidade realizada sobre `(t, t+window]`
    sem reimplementar a fórmula: `realized_vol_short[t+window]` já é "vol
    realizada nas `window` barras que terminam em `t+window`", que é a
    janela `(t, t+window]` quando lida a partir de `t`. Últimas `window`
    posições -> `NaN` (mesmo padrão de `_forward_return`, sem `t+window`
    disponível)."""
    n = realized_vol_short.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n > window:
        out[: n - window] = realized_vol_short[window:]
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
class RawLabels:
    """Rótulos canônicos por barra, alinhados por TIMESTAMP (não índice
    posicional) — Fase 4 (Q3), exposta só quando `return_raw_labels=True`
    nas funções que constroem `CandidateResult` (ver docstring do módulo,
    seção Fase 4). `open_time_ms`/`close_time_ms`/`canonical_id` sempre
    mesmo shape, alinhados posição-a-posição.

    Representa exatamente o subconjunto VÁLIDO usado para calcular as
    métricas do `CandidateResult` irmão (mesma barra que entrou em
    `separation`/`orthogonality`/`persistence`) — nunca o sentinela
    `_FOLD_FIT_FAILURE_SENTINEL` (fold sem fit bem-sucedido, HMM/Jump
    Model) nem R0 (warmup, baseline): nenhum dos dois é um rótulo de
    regime real, e propagá-los por um `join_asof` (Q3) como se fossem
    inventaria um "regime" onde não houve medição.

    **`close_time_ms` -- adicionado 2026-08-19, achado de auditoria cética
    (AG-090):** o rótulo de regime de uma barra só é CONHECÍVEL quando a
    barra FECHA (`log_return_1`/features derivadas dela exigem o preço de
    fechamento) -- `open_time_ms` é identidade da barra (útil pra
    debug/rastreio), nunca o timestamp certo pra um `join_asof` causal
    contra outra grade. Confirmado que `t0` de `labels.parquet`
    (`src/labels/triple_barrier.py:913`, `t0_arr = bars["close_time"]`) JÁ
    é o `close_time` da barra -- os dois consumidores de `join_asof`
    causal deste módulo (`_asof_join_btc_labels`/Q3,
    `m4_critical_windows._asof_join_regime_onto_labels`/heterogeneidade)
    precisam chavear em `close_time_ms` nos dois lados, não `open_time_ms`
    -- usar `open_time_ms` deixaria uma barra "conhecida" antes dela
    fechar de verdade, vazamento temporal clássico (B02, mesma classe)."""

    open_time_ms: IntArray
    close_time_ms: IntArray
    canonical_id: IntArray


@dataclass(frozen=True, slots=True)
class SymbolResult:
    """`oos_start_ms`/`oos_end_ms` -- adicionado 2026-08-19 (AG-093,
    `audit/architecture_gaps_log.yaml`): fronteira `[oos_start_ms,
    oos_end_ms)` do walk-forward ancorado desta combinação (symbol,
    janela, resolução) -- MESMA janela temporal que baseline/HMM/Jump
    Model usam pra suas métricas (`close_time_ms[oos_start]` até
    `close_time_ms[oos_end-1]+1`, half-open, consistente com o resto do
    módulo pós-AG-090). Existe pra permitir que `m4_critical_windows.
    _bocpd_metrics_for_window` alinhe a janela de AVALIAÇÃO do BOCPD
    (histórico causal completo, fatiado depois) a essa mesma fronteira,
    em vez do range calendário `[window.start, window.end)` inteiro (que
    inflava a amostra do BOCPD ~5x em relação aos outros 5 candidatos,
    achado real que explicava boa parte de sua liderança suspeita em
    Cochran's Q/I²)."""

    symbol: str
    n_bars: int
    n_folds: int
    baseline: CandidateResult
    candidates: tuple[CandidateResult, ...]
    oos_start_ms: int
    oos_end_ms: int


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
    escondido (B28).

    **Extensão 2026-08-18 -- Welch's F (`src.validation.regime_utility.
    anova_by_group`) tem 2 precondições NOVAS por grupo que a F clássica
    não tinha** (ela só precisava de `n_total > k_groups`, já coberto pelo
    `n <= n_groups` abaixo): `n_i>=2` (variância amostral por grupo exige
    `ddof=1`) e variância amostral `> 0` (Welch pondera por `n_i/var_i`,
    `var_i=0` é divisão por zero). Sem alargar o critério de degeneração
    pra cobrir os dois, um candidato cuja fronteira de decisão isola um
    estado raro numa janela OOS com só 1 barra (plausível -- mesma classe
    de saturação já documentada acima pra Jump Model/HMM/BOCPD) levantaria
    `ValueError` de dentro de `anova_by_group` e derrubaria o símbolo
    inteiro; com Welch isso é tão "candidato degenerou, é uma medição
    válida" quanto o caso de 1 estado só já tratado acima -- mesma
    filosofia, não um caso novo de verdade."""
    finite_mask = np.isfinite(response)
    labels_valid = group_labels[finite_mask]
    response_valid = response[finite_mask]
    n = int(response_valid.shape[0])
    unique_groups = np.unique(labels_valid)
    n_groups = int(unique_groups.size)
    degenerate = n_groups < 2 or n <= n_groups
    if not degenerate:
        for g in unique_groups:
            group_response = response_valid[labels_valid == g]
            if group_response.size < 2 or float(np.var(group_response, ddof=1)) == 0.0:
                degenerate = True
                break
    if degenerate:
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


@overload
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
    open_time_ms: IntArray | None = ...,
    close_time_ms: IntArray | None = ...,
    return_raw_labels: Literal[False] = ...,
) -> CandidateResult: ...


@overload
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
    open_time_ms: IntArray,
    close_time_ms: IntArray,
    return_raw_labels: Literal[True],
) -> tuple[CandidateResult, RawLabels]: ...


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
    open_time_ms: IntArray | None = None,
    close_time_ms: IntArray | None = None,
    return_raw_labels: bool = False,
) -> CandidateResult | tuple[CandidateResult, RawLabels]:
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
    aprender mais dado.

    **Fase 4 (Q3) -- `return_raw_labels`/`open_time_ms` (default
    preserva o contrato exato da Fase 3):** quando `True`, devolve
    `(CandidateResult, RawLabels)` -- `RawLabels.canonical_id` é
    EXATAMENTE `labels_valid` (o mesmo array usado abaixo para calcular
    `separation`/`orthogonality`/`persistence`, já sem os folds falhos) e
    `RawLabels.open_time_ms`/`.close_time_ms` são os timestamps
    correspondentes sob a MESMA máscara -- nunca o sentinela
    `_FOLD_FIT_FAILURE_SENTINEL`.
    `open_time_ms`/`close_time_ms` (alinhados 1:1 com `obs_2d`/
    `forward_return`/`vol_pctile`) são obrigatórios (`ValueError`) quando
    `return_raw_labels=True`; ignorados quando `False`."""
    if return_raw_labels and (open_time_ms is None or close_time_ms is None):
        raise ValueError(
            "_run_fold_refit_candidate: open_time_ms/close_time_ms obrigatórios quando "
            "return_raw_labels=True"
        )
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

    valid_mask = canonical_oos != _FOLD_FIT_FAILURE_SENTINEL
    labels_valid, (forward_return_valid, vol_pctile_valid) = _compact_valid(
        canonical_oos, forward_return[oos_start:oos_end], vol_pctile[oos_start:oos_end]
    )
    separation = _anova_or_degenerate(labels_valid, forward_return_valid)
    orthogonality = _anova_or_degenerate(labels_valid, vol_pctile_valid)
    persistence = _persistence_or_degenerate(labels_valid)

    result = CandidateResult(
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
    if not return_raw_labels:
        return result
    assert open_time_ms is not None and close_time_ms is not None  # checado no topo da função
    raw_open_time_ms = open_time_ms[oos_start:oos_end][valid_mask]
    raw_close_time_ms = close_time_ms[oos_start:oos_end][valid_mask]
    return result, RawLabels(
        open_time_ms=raw_open_time_ms, close_time_ms=raw_close_time_ms, canonical_id=labels_valid
    )


@overload
def _bocpd_candidate_result(
    log_return_1: FloatArray,
    oos_start: int,
    oos_end: int,
    *,
    hazard_lambda: float,
    n_canonical_buckets: int,
    forward_return: FloatArray,
    vol_pctile: FloatArray,
    open_time_ms: IntArray | None = ...,
    close_time_ms: IntArray | None = ...,
    return_raw_labels: Literal[False] = ...,
) -> CandidateResult: ...


@overload
def _bocpd_candidate_result(
    log_return_1: FloatArray,
    oos_start: int,
    oos_end: int,
    *,
    hazard_lambda: float,
    n_canonical_buckets: int,
    forward_return: FloatArray,
    vol_pctile: FloatArray,
    open_time_ms: IntArray,
    close_time_ms: IntArray,
    return_raw_labels: Literal[True],
) -> tuple[CandidateResult, RawLabels]: ...


def _bocpd_candidate_result(
    log_return_1: FloatArray,
    oos_start: int,
    oos_end: int,
    *,
    hazard_lambda: float,
    n_canonical_buckets: int,
    forward_return: FloatArray,
    vol_pctile: FloatArray,
    open_time_ms: IntArray | None = None,
    close_time_ms: IntArray | None = None,
    return_raw_labels: bool = False,
) -> CandidateResult | tuple[CandidateResult, RawLabels]:
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
    ordenação por quantil de segmento (que não empata do mesmo jeito).

    **Fase 4 (Q3) -- `return_raw_labels`/`open_time_ms`** (mesmo contrato
    de `_run_fold_refit_candidate`, ver docstring lá): quando `True`,
    devolve `(CandidateResult, RawLabels)` com `canonical_id=labels_oos`
    (BOCPD não tem conceito de fold falho -- toda a janela OOS é válida
    por construção, sem máscara/compactação) e `open_time_ms`/
    `close_time_ms` a fatia correspondente de `[oos_start:oos_end]`."""
    if return_raw_labels and (open_time_ms is None or close_time_ms is None):
        raise ValueError(
            "_bocpd_candidate_result: open_time_ms/close_time_ms obrigatórios quando "
            "return_raw_labels=True"
        )
    bocpd_out = run_bocpd(log_return_1, hazard_lambda=hazard_lambda)
    bucket_by_bar = segments_to_canonical_states(
        bocpd_out.segment_id, log_return_1, n_buckets=n_canonical_buckets
    )
    canonical_id_full = canonicalize_states(bucket_by_bar, log_return_1).canonical_id

    labels_oos = canonical_id_full[oos_start:oos_end]
    separation = _anova_or_degenerate(labels_oos, forward_return[oos_start:oos_end])
    orthogonality = _anova_or_degenerate(labels_oos, vol_pctile[oos_start:oos_end])
    persistence = _persistence_or_degenerate(labels_oos)

    result = CandidateResult(
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
    if not return_raw_labels:
        return result
    assert open_time_ms is not None and close_time_ms is not None  # checado no topo da função
    return result, RawLabels(
        open_time_ms=open_time_ms[oos_start:oos_end],
        close_time_ms=close_time_ms[oos_start:oos_end],
        canonical_id=labels_oos,
    )


@overload
def _baseline_candidate_result(
    regime_physical: IntArray,
    oos_start: int,
    oos_end: int,
    *,
    forward_return: FloatArray,
    vol_pctile: FloatArray,
    classifier_id: str,
    open_time_ms: IntArray | None = ...,
    close_time_ms: IntArray | None = ...,
    return_raw_labels: Literal[False] = ...,
) -> CandidateResult: ...


@overload
def _baseline_candidate_result(
    regime_physical: IntArray,
    oos_start: int,
    oos_end: int,
    *,
    forward_return: FloatArray,
    vol_pctile: FloatArray,
    classifier_id: str,
    open_time_ms: IntArray,
    close_time_ms: IntArray,
    return_raw_labels: Literal[True],
) -> tuple[CandidateResult, RawLabels]: ...


def _baseline_candidate_result(
    regime_physical: IntArray,
    oos_start: int,
    oos_end: int,
    *,
    forward_return: FloatArray,
    vol_pctile: FloatArray,
    classifier_id: str,
    open_time_ms: IntArray | None = None,
    close_time_ms: IntArray | None = None,
    return_raw_labels: bool = False,
) -> CandidateResult | tuple[CandidateResult, RawLabels]:
    """`QuantileRegimeClassifier` -- state machine determinística causal,
    sem fit nenhum (mesmo raciocínio do BOCPD pra `fold_stability_by_
    construction=True`: não existe "outro fit" pra comparar). R0
    (`_BASELINE_R0_PHYSICAL_ID`) excluído das métricas -- ver docstring do
    módulo.

    **Fase 4 (Q3) -- `return_raw_labels`/`open_time_ms`** (mesmo contrato
    dos outros 2 candidatos, ver docstring de `_run_fold_refit_candidate`):
    quando `True`, devolve `(CandidateResult, RawLabels)` com
    `canonical_id=labels_valid` (mesmo array pós-exclusão de R0 usado nas
    métricas abaixo -- R0 não é um regime real, não deveria ser herdado
    por um `join_asof` como se fosse) e `open_time_ms`/`close_time_ms` a
    fatia correspondente sob a MESMA máscara `non_r0_mask`."""
    if return_raw_labels and (open_time_ms is None or close_time_ms is None):
        raise ValueError(
            "_baseline_candidate_result: open_time_ms/close_time_ms obrigatórios quando "
            "return_raw_labels=True"
        )
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

    result = CandidateResult(
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
    if not return_raw_labels:
        return result
    assert open_time_ms is not None and close_time_ms is not None  # checado no topo da função
    raw_open_time_ms = open_time_ms[oos_start:oos_end][non_r0_mask]
    raw_close_time_ms = close_time_ms[oos_start:oos_end][non_r0_mask]
    return result, RawLabels(
        open_time_ms=raw_open_time_ms, close_time_ms=raw_close_time_ms, canonical_id=labels_valid
    )


@overload
def compare_regime_candidates_for_symbol(
    symbol: str,
    bars_df: pl.DataFrame,
    baseline_df: pl.DataFrame,
    *,
    initial_train_years: int,
    hmm_states_grid: tuple[int, ...] = ...,
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = ...,
    jump_seed: int = ...,
    include_jump_model: bool = ...,
    return_raw_labels: Literal[False] = ...,
) -> SymbolResult | None: ...


@overload
def compare_regime_candidates_for_symbol(
    symbol: str,
    bars_df: pl.DataFrame,
    baseline_df: pl.DataFrame,
    *,
    initial_train_years: int,
    hmm_states_grid: tuple[int, ...] = ...,
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = ...,
    jump_seed: int = ...,
    include_jump_model: bool = ...,
    return_raw_labels: Literal[True],
) -> tuple[SymbolResult, dict[str, RawLabels]] | None: ...


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
    include_jump_model: bool = True,
    return_raw_labels: bool = False,
) -> SymbolResult | tuple[SymbolResult, dict[str, RawLabels]] | None:
    """Núcleo puro (sem IO) -- recebe `bars_df`/`baseline_df` já
    carregados (mesmo `(symbol, start, end)`, ver `_assert_bars_baseline_
    aligned`), monta as métricas dos 3+1 candidatos sobre os folds OOS do
    walk-forward. Retorna `None` se não houver folds suficientes (dado
    insuficiente pra `initial_train_years` de treino inicial) -- mesmo
    contrato de `volatility_comparison.compare_estimators_for_
    combination`, sinal explícito pro chamador pular o símbolo.

    `include_jump_model=True` (default, preserva o contrato exato de
    antes) -- `AG-117` (`audit/architecture_gaps_log.yaml`, 2026-08-20):
    experimento de transferibilidade de λ mostrou que Jump Model não tem
    estrutura de 2 regimes detectável em NENHUM ponto de grid testado
    pra SOLUSDT/BNBUSDT/XRPUSDT (mesmo in-sample), e recalibrar λ pra
    ETHUSDT (único não-BTC com λ genuíno) piora ou empata a saturação
    nas janelas críticas -- nunca melhora. `include_jump_model=False`
    pula o fit de Jump Model inteiro (não aparece em `SymbolResult.
    candidates` nem em `raw_labels_by_classifier_id`) -- usado pelo
    orquestrador do M4 (`m4_critical_windows._run_one_cell`) pra símbolo
    != BTCUSDT (que continua elegível -- `m4_jump_model_penalty=0,002` é
    seu próprio λ local, nunca transplantado).

    **Fase 4 (Q3) -- `return_raw_labels: bool = False`** (default
    preserva o contrato exato da Fase 3, testado em `tests/unit/test_
    analysis_m4_regime_comparison.py` sem nenhuma mudança): quando
    `True`, devolve `(SymbolResult, dict[str, RawLabels])` -- o dict é
    chaveado por `classifier_id` (baseline + os 3 HMM + Jump Model +
    BOCPD, sempre as mesmas 6 chaves que `SymbolResult.baseline`/
    `.candidates` já expõem). Internamente esta função SEMPRE chama
    `_run_fold_refit_candidate`/`_bocpd_candidate_result`/`_baseline_
    candidate_result` com `return_raw_labels=True` (custo desprezível --
    só fatiamento de array já calculado, nunca refit) e decide expor ou
    descartar o dict conforme o `return_raw_labels` recebido aqui --
    hardcodar o literal `True` internamente (em vez de repassar esta
    variável `bool`) é o que permite os 3 helpers `@overload`ados
    resolverem o tipo de retorno certo sem quebrar `mypy --strict`."""
    _assert_bars_baseline_aligned(bars_df, baseline_df, symbol=symbol)

    log_return_1_full, obs_2d_full = _input_obs(bars_df)
    valid_start_idx = _valid_start_idx(log_return_1_full, obs_2d_full[:, 1])

    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()[valid_start_idx:]
    close_time_ms = bars_df["close_time"].cast(pl.Int64).to_numpy()[valid_start_idx:]
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

    # Fase 4 (Q3) -- literal True hardcoded nas 3 chamadas abaixo (não
    # repassa `return_raw_labels`, que é só `bool`) -- ver docstring desta
    # função/módulo: os 3 helpers são `@overload`ados por `Literal`, um
    # `bool` puro não casaria com nenhuma das duas variantes.
    baseline_result, baseline_raw_labels = _baseline_candidate_result(
        regime_physical,
        oos_start,
        oos_end,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
        classifier_id=baseline_classifier_id,
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        return_raw_labels=True,
    )
    raw_labels_by_classifier_id: dict[str, RawLabels] = {
        baseline_classifier_id: baseline_raw_labels
    }

    hmm_pairs = [
        _run_fold_refit_candidate(
            hmm_gaussian_classifier_id(k),
            k,
            obs_2d,
            splits,
            fit_fn=_make_hmm_fit_fn(k, hmm_seed),
            predict_fn=predict_hmm_gaussian,
            forward_return=forward_return,
            vol_pctile=vol_pctile,
            open_time_ms=open_time_ms,
            close_time_ms=close_time_ms,
            return_raw_labels=True,
        )
        for k in hmm_states_grid
    ]
    hmm_results = tuple(candidate_result for candidate_result, _ in hmm_pairs)
    for k, (_, hmm_raw_labels) in zip(hmm_states_grid, hmm_pairs, strict=True):
        raw_labels_by_classifier_id[hmm_gaussian_classifier_id(k)] = hmm_raw_labels

    # AG-117, 2026-08-20 -- Jump Model pulado inteiro quando
    # include_jump_model=False (experimento de transferibilidade mostrou
    # ausência de estrutura de 2 regimes detectável, ver docstring desta
    # função). Não entra em candidates/raw_labels_by_classifier_id.
    jump_candidates: tuple[CandidateResult, ...] = ()
    if include_jump_model:
        jump_result, jump_raw_labels = _run_fold_refit_candidate(
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
            open_time_ms=open_time_ms,
            close_time_ms=close_time_ms,
            return_raw_labels=True,
        )
        raw_labels_by_classifier_id[JUMP_MODEL_CLASSIFIER_ID] = jump_raw_labels
        jump_candidates = (jump_result,)

    bocpd_result, bocpd_raw_labels = _bocpd_candidate_result(
        log_return_1,
        oos_start,
        oos_end,
        hazard_lambda=bocpd_hazard_lambda,
        n_canonical_buckets=bocpd_n_canonical_buckets,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        return_raw_labels=True,
    )
    raw_labels_by_classifier_id[BOCPD_CLASSIFIER_ID] = bocpd_raw_labels

    # AG-093 -- fronteira OOS em timestamp (half-open), ver docstring de
    # SymbolResult. close_time_ms[oos_end - 1] + 1 (não close_time_ms
    # [oos_end], que estaria fora de índice quando o último fold cobre
    # até o fim da série -- caso normal do walk-forward ancorado).
    oos_start_ms = int(close_time_ms[oos_start])
    oos_end_ms = int(close_time_ms[oos_end - 1]) + 1

    symbol_result = SymbolResult(
        symbol=symbol,
        n_bars=bars_df.height,
        n_folds=len(splits),
        baseline=baseline_result,
        candidates=(*hmm_results, *jump_candidates, bocpd_result),
        oos_start_ms=oos_start_ms,
        oos_end_ms=oos_end_ms,
    )
    if return_raw_labels:
        return symbol_result, raw_labels_by_classifier_id
    return symbol_result


# ============================================================================
# Núcleo puro -- SÓ baseline + Jump Model (experimento de transferibilidade
# de jump_penalty por ativo, AG-087, `audit/architecture_gaps_log.yaml`).
# IRMÃ de `compare_regime_candidates_for_symbol`, não uma variação dela --
# pula os 3 HMM e o BOCPD de propósito (custo ~4-6x menor por célula: o
# experimento só precisa medir `is_saturated`/`saturation_rate` do Jump
# Model sob λ por ativo, recomputar HMM/BOCPD que não mudam com λ seria
# desperdício puro de N_lifetime/tempo). Reusa `_run_fold_refit_candidate`
# (núcleo genérico compartilhado com HMM) e `_baseline_candidate_result`
# -- ZERO lógica de fold nova, mesmo padrão exato de chamada que
# `compare_regime_candidates_for_symbol` já usa pro Jump Model (linhas
# ~1192-1210 acima).
# ============================================================================


@overload
def compare_jump_model_only_for_symbol(
    symbol: str,
    bars_df: pl.DataFrame,
    baseline_df: pl.DataFrame,
    *,
    initial_train_years: int,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = ...,
    return_raw_labels: Literal[False] = ...,
) -> SymbolResult | None: ...


@overload
def compare_jump_model_only_for_symbol(
    symbol: str,
    bars_df: pl.DataFrame,
    baseline_df: pl.DataFrame,
    *,
    initial_train_years: int,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = ...,
    return_raw_labels: Literal[True],
) -> tuple[SymbolResult, dict[str, RawLabels]] | None: ...


def compare_jump_model_only_for_symbol(
    symbol: str,
    bars_df: pl.DataFrame,
    baseline_df: pl.DataFrame,
    *,
    initial_train_years: int,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = 0,
    return_raw_labels: bool = False,
) -> SymbolResult | tuple[SymbolResult, dict[str, RawLabels]] | None:
    """Núcleo puro (sem IO) -- IRMÃ de `compare_regime_candidates_for_symbol`,
    mesmo contrato de entrada/saída (`SymbolResult | None`, mesmo
    `_assert_bars_baseline_aligned`/`_valid_start_idx`/walk-forward), mas
    roda SÓ baseline (custo ~zero, state machine determinística) + Jump
    Model -- nunca os 3 HMM nem o BOCPD. `SymbolResult.candidates` tem
    exatamente 1 elemento (`(jump_result,)`), não 4 -- 100% compatível com
    a maquinaria de agregação de `m4_critical_windows.py`
    (`_aggregate_one_candidate`/`_collect_classifier_ids` só procuram
    `classifier_id` dentro de `symbol_result.candidates`, nunca assumem
    quantidade fixa de candidatos).

    Existe especificamente para o experimento de transferibilidade de
    `m4_jump_model_penalty` por ativo (AG-087): `constants.yaml::
    m4_jump_model_penalty` (0,002) foi calibrado SÓ em BTCUSDT e é
    transplantado sem reteste pra ETH/SOL/BNB/XRP, medindo ~25-29% de
    saturação (`is_saturated`/`switch_rate==0.0`) nas células não-BTC.
    Testar se um λ calibrado POR ATIVO reduz essa saturação exigiria, com
    `compare_regime_candidates_for_symbol`, recomputar HMM k=2/3/4 e BOCPD
    a cada célula -- candidatos que NÃO dependem de `jump_penalty`, custo
    desperdiçado. Esta função isola só o que muda com o hiperparâmetro
    sendo testado.

    `return_raw_labels: bool = False` -- mesmo protocolo/motivo de tipagem
    de `compare_regime_candidates_for_symbol` (`@overload` por `Literal`,
    `RawLabels` do baseline + Jump Model, nunca um `bool` puro repassado
    internamente). `True` alimenta a heterogeneidade de volatilidade
    (AG-114, `m4_critical_windows.VolatilityHeterogeneitySymbolDetail`)
    como sinal secundário/corroborante do experimento -- não custa refit
    extra, mesmo fatiamento de array já calculado que o resto do módulo já
    aceita como desprezível."""
    _assert_bars_baseline_aligned(bars_df, baseline_df, symbol=symbol)

    log_return_1_full, obs_2d_full = _input_obs(bars_df)
    valid_start_idx = _valid_start_idx(log_return_1_full, obs_2d_full[:, 1])

    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()[valid_start_idx:]
    close_time_ms = bars_df["close_time"].cast(pl.Int64).to_numpy()[valid_start_idx:]
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
            "analysis.m4_regime_comparison.jump_only_folds_insuficientes",
            symbol=symbol,
            n_bars=bars_df.height,
            n_bars_pos_trim=int(obs_2d.shape[0]),
        )
        return None
    oos_start, oos_end = _oos_slice(splits)

    # Literal True hardcoded (não repassa `return_raw_labels`) -- mesmo
    # motivo de tipagem de `compare_regime_candidates_for_symbol`: os 2
    # helpers são `@overload`ados por `Literal`, um `bool` puro não
    # casaria com nenhuma das duas variantes.
    baseline_result, baseline_raw_labels = _baseline_candidate_result(
        regime_physical,
        oos_start,
        oos_end,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
        classifier_id=baseline_classifier_id,
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        return_raw_labels=True,
    )
    raw_labels_by_classifier_id: dict[str, RawLabels] = {
        baseline_classifier_id: baseline_raw_labels
    }

    jump_result, jump_raw_labels = _run_fold_refit_candidate(
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
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        return_raw_labels=True,
    )
    raw_labels_by_classifier_id[JUMP_MODEL_CLASSIFIER_ID] = jump_raw_labels

    # AG-093 -- mesma fronteira OOS em timestamp (half-open) que
    # compare_regime_candidates_for_symbol já usa, ver docstring de
    # SymbolResult.
    oos_start_ms = int(close_time_ms[oos_start])
    oos_end_ms = int(close_time_ms[oos_end - 1]) + 1

    symbol_result = SymbolResult(
        symbol=symbol,
        n_bars=bars_df.height,
        n_folds=len(splits),
        baseline=baseline_result,
        candidates=(jump_result,),
        oos_start_ms=oos_start_ms,
        oos_end_ms=oos_end_ms,
    )
    if return_raw_labels:
        return symbol_result, raw_labels_by_classifier_id
    return symbol_result


# ============================================================================
# Ponto de entrada com IO -- um símbolo, ou os 5
# ============================================================================


@overload
def run_regime_comparison_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = ...,
    resolution_id: str = ...,
    hmm_states_grid: tuple[int, ...] = ...,
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = ...,
    jump_seed: int = ...,
    include_jump_model: bool = ...,
    return_raw_labels: Literal[False] = ...,
) -> SymbolResult | None: ...


@overload
def run_regime_comparison_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = ...,
    resolution_id: str = ...,
    hmm_states_grid: tuple[int, ...] = ...,
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = ...,
    jump_seed: int = ...,
    include_jump_model: bool = ...,
    return_raw_labels: Literal[True],
) -> tuple[SymbolResult, dict[str, RawLabels]] | None: ...


def run_regime_comparison_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = None,
    resolution_id: str = RESOLUTION_ID,
    hmm_states_grid: tuple[int, ...] = (2, 3, 4),
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = 0,
    jump_seed: int = 0,
    include_jump_model: bool = True,
    return_raw_labels: bool = False,
) -> SymbolResult | tuple[SymbolResult, dict[str, RawLabels]] | None:
    """Carrega `bars_df` (`lake.query_dollar_bars`) e `baseline_df`
    (`build_regimes(..., bar_source=f"dollar_{resolution_id.lower()}")`)
    reais do disco, com o MESMO `(symbol, start, end)` nos dois (garante o
    alinhamento que `_assert_bars_baseline_aligned` confirma no núcleo
    puro), delega o resto pra `compare_regime_candidates_for_symbol`.

    `include_jump_model: bool = True` -- repassado direto, ver docstring
    de `compare_regime_candidates_for_symbol`/`AG-117`.

    `resolution_id: str = RESOLUTION_ID` (default `"R1"`, Fase B do plano
    `wise-exploring-panda.md` -- ver docstring do módulo) seleciona R1/R2/
    R3 nas DUAS chamadas de carga juntas (`query_dollar_bars`/
    `build_regimes`) -- nunca uma sem a outra, senão `_assert_bars_
    baseline_aligned` levantaria por desalinhamento de fonte.

    `initial_train_years=None` (default) resolve pra `m1_walkforward_
    initial_train_years` (`constants.yaml`) -- mesmo protocolo do M1,
    reusado, não duplicado (decisão #6/plano: M4 reusa o splitter do M1
    sem alterar).

    `build_regimes` não expõe throttle de DuckDB (`memory_limit_gb`/
    `threads`) -- gap conhecido, herdado do módulo, não corrigido aqui
    (fora do escopo do harness M4; `bars_df` (carregado diretamente por
    esta função) É throttled via `m4_duckdb_memory_limit_gb`/`m4_duckdb_
    threads`, mesma convenção de M1/M2/M3 sob `ProcessPoolExecutor`).

    **Fase 4 (Q3) -- `return_raw_labels: bool = False`** (default
    preserva o contrato exato da Fase 3): propagado pra
    `compare_regime_candidates_for_symbol`. O `if/else` explícito abaixo
    (em vez de repassar a variável `return_raw_labels`) é o mesmo motivo
    de tipagem documentado no módulo/em `compare_regime_candidates_for_
    symbol`: a função de destino é `@overload`ada por `Literal`, um `bool`
    puro não resolveria a variante certa."""
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
        resolution_id=resolution_id,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    baseline_df = build_regimes(symbol, start, end, bar_source=f"dollar_{resolution_id.lower()}")

    logger.info(
        "analysis.m4_regime_comparison.bars_loaded",
        symbol=symbol,
        resolution_id=resolution_id,
        n_bars=bars_df.height,
        n_bars_baseline=baseline_df.height,
        start=start,
        end=end,
    )
    if return_raw_labels:
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
            include_jump_model=include_jump_model,
            return_raw_labels=True,
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
        include_jump_model=include_jump_model,
        return_raw_labels=False,
    )


# ============================================================================
# Ponto de entrada com IO -- SÓ baseline + Jump Model (ver docstring de
# compare_jump_model_only_for_symbol/AG-087, experimento de
# transferibilidade de jump_penalty por ativo)
# ============================================================================


@overload
def run_jump_model_only_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = ...,
    resolution_id: str = ...,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = ...,
    return_raw_labels: Literal[False] = ...,
) -> SymbolResult | None: ...


@overload
def run_jump_model_only_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = ...,
    resolution_id: str = ...,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = ...,
    return_raw_labels: Literal[True],
) -> tuple[SymbolResult, dict[str, RawLabels]] | None: ...


def run_jump_model_only_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = None,
    resolution_id: str = RESOLUTION_ID,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = 0,
    return_raw_labels: bool = False,
) -> SymbolResult | tuple[SymbolResult, dict[str, RawLabels]] | None:
    """IRMÃ de `run_regime_comparison_for_symbol` -- carrega `bars_df`/
    `baseline_df` reais do disco com o MESMO `(symbol, start, end,
    resolution_id)`, delega pra `compare_jump_model_only_for_symbol` (só
    baseline + Jump Model, ver docstring de lá). Usada pelo laço de
    transferibilidade de `jump_penalty` por ativo
    (`m4_critical_windows.run_jump_model_transferability_comparison`,
    AG-087) -- IO isolado do harness completo de 6 candidatos pelo mesmo
    motivo: HMM/BOCPD não mudam com `jump_penalty`, recomputá-los por
    célula seria custo puro sem informação nova."""
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
        resolution_id=resolution_id,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    baseline_df = build_regimes(symbol, start, end, bar_source=f"dollar_{resolution_id.lower()}")

    logger.info(
        "analysis.m4_regime_comparison.jump_only_bars_loaded",
        symbol=symbol,
        resolution_id=resolution_id,
        n_bars=bars_df.height,
        n_bars_baseline=baseline_df.height,
        start=start,
        end=end,
    )
    if return_raw_labels:
        return compare_jump_model_only_for_symbol(
            symbol,
            bars_df,
            baseline_df,
            initial_train_years=train_years,
            jump_n_states=jump_n_states,
            jump_penalty=jump_penalty,
            jump_seed=jump_seed,
            return_raw_labels=True,
        )
    return compare_jump_model_only_for_symbol(
        symbol,
        bars_df,
        baseline_df,
        initial_train_years=train_years,
        jump_n_states=jump_n_states,
        jump_penalty=jump_penalty,
        jump_seed=jump_seed,
        return_raw_labels=False,
    )


# ============================================================================
# "Condição C" -- Jump Model com espaço de observação ESTENDIDO (AG-119,
# 2026-08-20). Reteste isolado (tools/diagnostics/retest_jump_model_
# extended_features_k3.py) mostrou que SOLUSDT/BNBUSDT/XRPUSDT (que
# AG-117 tinha excluído -- nenhum λ funcionava no espaço estreito de 2
# features) mostram estrutura de regime genuína quando testados com
# espaço de 4 features (log_return_1/realized_vol_short/
# realized_vol_long/downside_deviation) + jump_n_states=3, alinhado à
# literatura (Cortese/Kolm/Lindström 2023, único paper cripto-específico,
# acha K=3 melhor que K=2). Esta seção reproduz o MESMO espaço/K no
# harness REAL do M4 (não no script de diagnóstico isolado), pra colocar
# Jump Model de volta na disputa do AG-114 com essa configuração.
# ============================================================================


def _extended_jump_model_obs(bars_df: pl.DataFrame) -> tuple[FloatArray, FloatArray]:
    """`(log_return_1, obs_4d)` -- MESMA mecânica de `_input_obs`, mas com
    2 colunas extras (`realized_vol_long`/`downside_deviation`,
    `AG-119`). Corte de warmup PRÓPRIO (não reusa `_valid_start_idx`
    puro): as 2 colunas novas têm janela própria (`feature_c06_vol_
    ratio_long_window`, tipicamente maior que a curta) e podem ficar
    `NaN` além de onde `log_return_1`/`realized_vol_short` já ficariam
    finitos -- corta na primeira posição em que as 4 colunas são finitas
    SIMULTANEAMENTE, não só as 2 originais (achado real do reteste
    isolado: 84 barras extras de warmup vs. o corte de 2 colunas)."""
    log_return_1_full, obs_2d_full = _input_obs(bars_df)
    valid_start_idx = _valid_start_idx(log_return_1_full, obs_2d_full[:, 1])
    log_return_1 = log_return_1_full[valid_start_idx:]
    realized_vol_short = obs_2d_full[valid_start_idx:, 1]

    short_window = int(load_feature_constant("feature_c06_vol_ratio_short_window"))
    long_window = int(load_feature_constant("feature_c06_vol_ratio_long_window"))
    realized_vol_long_full = features_support.realized_vol(log_return_1_full, long_window)
    realized_vol_long = realized_vol_long_full[valid_start_idx:]
    downside_dev_full = features_support.downside_deviation(log_return_1_full, short_window)
    downside_dev = downside_dev_full[valid_start_idx:]

    obs_4d = np.column_stack(
        [log_return_1, realized_vol_short, realized_vol_long, downside_dev]
    ).astype(np.float64)

    extra_valid = np.all(np.isfinite(obs_4d), axis=1)
    if not np.any(extra_valid):
        raise ValueError(
            "_extended_jump_model_obs: nenhuma barra com as 4 colunas finitas -- "
            "long_window/downside_deviation maiores que o histórico disponível?"
        )
    extra_start_idx = int(np.argmax(extra_valid))
    return log_return_1[extra_start_idx:], obs_4d[extra_start_idx:]


@overload
def compare_jump_model_extended_features_for_symbol(
    symbol: str,
    bars_df: pl.DataFrame,
    baseline_df: pl.DataFrame,
    *,
    initial_train_years: int,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = ...,
    return_raw_labels: Literal[False] = ...,
) -> SymbolResult | None: ...


@overload
def compare_jump_model_extended_features_for_symbol(
    symbol: str,
    bars_df: pl.DataFrame,
    baseline_df: pl.DataFrame,
    *,
    initial_train_years: int,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = ...,
    return_raw_labels: Literal[True],
) -> tuple[SymbolResult, dict[str, RawLabels]] | None: ...


def compare_jump_model_extended_features_for_symbol(
    symbol: str,
    bars_df: pl.DataFrame,
    baseline_df: pl.DataFrame,
    *,
    initial_train_years: int,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = 0,
    return_raw_labels: bool = False,
) -> SymbolResult | tuple[SymbolResult, dict[str, RawLabels]] | None:
    """IRMÃ de `compare_jump_model_only_for_symbol` -- mesmo contrato de
    entrada/saída, mesmo núcleo (`_run_fold_refit_candidate`,
    `_baseline_candidate_result`, walk-forward ancorado idêntico), mas
    consome `_extended_jump_model_obs` (4 features) em vez de `_input_obs`
    (2 features) -- único ponto de diferença real, tudo o resto é a
    mesma orquestração. `AG-119` (`audit/architecture_gaps_log.yaml`) --
    "Condição C" do experimento de transferibilidade de λ, com espaço de
    observação alinhado à literatura de Jump Model."""
    _assert_bars_baseline_aligned(bars_df, baseline_df, symbol=symbol)

    log_return_1, obs_4d = _extended_jump_model_obs(bars_df)
    extra_start_idx = bars_df.height - log_return_1.shape[0]

    open_time_ms = bars_df["open_time"].cast(pl.Int64).to_numpy()[extra_start_idx:]
    close_time_ms = bars_df["close_time"].cast(pl.Int64).to_numpy()[extra_start_idx:]
    forward_return = _forward_return(log_return_1)
    vol_pctile = baseline_df["vol_pctile"].cast(pl.Float64).to_numpy()[extra_start_idx:]
    regime_physical = (
        baseline_df["regime"].to_physical().cast(pl.Int64).to_numpy()[extra_start_idx:]
    )
    baseline_classifier_id = str(baseline_df["classifier_id"][0])

    splits = vwf.generate_anchored_walk_forward_splits(
        open_time_ms, initial_train_years=initial_train_years
    )
    if not splits:
        logger.warning(
            "analysis.m4_regime_comparison.jump_extended_folds_insuficientes",
            symbol=symbol,
            n_bars=bars_df.height,
            n_bars_pos_trim=int(obs_4d.shape[0]),
        )
        return None
    oos_start, oos_end = _oos_slice(splits)

    baseline_result, baseline_raw_labels = _baseline_candidate_result(
        regime_physical,
        oos_start,
        oos_end,
        forward_return=forward_return,
        vol_pctile=vol_pctile,
        classifier_id=baseline_classifier_id,
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        return_raw_labels=True,
    )
    raw_labels_by_classifier_id: dict[str, RawLabels] = {
        baseline_classifier_id: baseline_raw_labels
    }

    jump_result, jump_raw_labels = _run_fold_refit_candidate(
        JUMP_MODEL_CLASSIFIER_ID,
        jump_n_states,
        obs_4d,
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
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        return_raw_labels=True,
    )
    raw_labels_by_classifier_id[JUMP_MODEL_CLASSIFIER_ID] = jump_raw_labels

    oos_start_ms = int(close_time_ms[oos_start])
    oos_end_ms = int(close_time_ms[oos_end - 1]) + 1

    symbol_result = SymbolResult(
        symbol=symbol,
        n_bars=bars_df.height,
        n_folds=len(splits),
        baseline=baseline_result,
        candidates=(jump_result,),
        oos_start_ms=oos_start_ms,
        oos_end_ms=oos_end_ms,
    )
    if return_raw_labels:
        return symbol_result, raw_labels_by_classifier_id
    return symbol_result


@overload
def run_jump_model_extended_features_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = ...,
    resolution_id: str = ...,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = ...,
    return_raw_labels: Literal[False] = ...,
) -> SymbolResult | None: ...


@overload
def run_jump_model_extended_features_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = ...,
    resolution_id: str = ...,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = ...,
    return_raw_labels: Literal[True],
) -> tuple[SymbolResult, dict[str, RawLabels]] | None: ...


def run_jump_model_extended_features_for_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    initial_train_years: int | None = None,
    resolution_id: str = RESOLUTION_ID,
    jump_n_states: int,
    jump_penalty: float,
    jump_seed: int = 0,
    return_raw_labels: bool = False,
) -> SymbolResult | tuple[SymbolResult, dict[str, RawLabels]] | None:
    """IRMÃ de `run_jump_model_only_for_symbol` -- carrega `bars_df`/
    `baseline_df` reais do disco, delega pra `compare_jump_model_
    extended_features_for_symbol`. `AG-119` -- "Condição C"."""
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
        resolution_id=resolution_id,
        duckdb_memory_limit_gb=throttle.memory_limit_gb,
        duckdb_threads=throttle.threads,
    )
    baseline_df = build_regimes(symbol, start, end, bar_source=f"dollar_{resolution_id.lower()}")

    logger.info(
        "analysis.m4_regime_comparison.jump_extended_bars_loaded",
        symbol=symbol,
        resolution_id=resolution_id,
        n_bars=bars_df.height,
        n_bars_baseline=baseline_df.height,
        start=start,
        end=end,
    )
    if return_raw_labels:
        return compare_jump_model_extended_features_for_symbol(
            symbol,
            bars_df,
            baseline_df,
            initial_train_years=train_years,
            jump_n_states=jump_n_states,
            jump_penalty=jump_penalty,
            jump_seed=jump_seed,
            return_raw_labels=True,
        )
    return compare_jump_model_extended_features_for_symbol(
        symbol,
        bars_df,
        baseline_df,
        initial_train_years=train_years,
        jump_n_states=jump_n_states,
        jump_penalty=jump_penalty,
        jump_seed=jump_seed,
        return_raw_labels=False,
    )


# ============================================================================
# Fase 4 (Q3) -- terceira via: BTC como fator comum de regime
# ============================================================================

# Os ativos não-BTC, na ordem de ALL_SYMBOLS -- default de `other_symbols`
# em `run_q3_common_factor_regime`.
_Q3_DEFAULT_OTHER_SYMBOLS: Final[tuple[str, ...]] = tuple(s for s in ALL_SYMBOLS if s != "BTCUSDT")

# Abaixo disso, adjusted_rand_score não é uma medição com sentido
# estatístico (ARI com 0 ou 1 par comparável é degenerado/indefinido) --
# NaN explícito em vez de um número sem base, mesma disciplina de
# `_anova_or_degenerate`/`_persistence_or_degenerate` (ausência de
# medição, não erro, não zero inventado).
_Q3_MIN_BARS_COMPARED: Final[int] = 2


@dataclass(frozen=True, slots=True)
class Q3AssetResult:
    """Q3, um ativo não-BTC: Rand ajustado entre a classificação PRÓPRIA
    do ativo (mesmo `classifier_id`/hiperparâmetros de `Q3Result`, rodada
    independentemente sobre o dado do próprio ativo) e a classificação
    DERIVADA de BTC via as-of join causal (`_asof_join_btc_labels`,
    `strategy="backward"`, nunca timestamp futuro). Rand ALTO -> BTC
    basta pra este ativo; Rand baixo -> regime é idiossincrático POR
    ATIVO **ou** a correlação BTC-ativo em si varia por regime -- os dois
    cenários dão o mesmo sintoma por motivos diferentes (caveat de
    interpretação já registrado no plano `wise-exploring-panda.md`, não
    resolvido por esta função, só citado).

    `n_bars_compared`: tamanho da região de SOBREPOSIÇÃO temporal entre
    BTC e o ativo (barras do ativo com um rótulo de BTC de timestamp
    `<=` o seu próprio já disponível) -- pode ser menor que o total de
    barras OOS do ativo (ex. ativo com histórico mais curto que BTC),
    nunca um crash. `adjusted_rand_own_vs_btc_derived` é `NaN` (não um
    valor inventado) se `n_bars_compared < _Q3_MIN_BARS_COMPARED`."""

    symbol: str
    n_bars_compared: int
    adjusted_rand_own_vs_btc_derived: float


@dataclass(frozen=True, slots=True)
class Q3Result:
    """`classifier_id`: qual dos 4 candidatos do M4 (baseline/HMM k=2|3|4/
    Jump Model CJM/BOCPD) foi testado via Q3 -- QUAL candidato usar é
    decisão de Fase 6/7 (não desta função, que é agnóstica por design, ver
    docstring de `run_q3_common_factor_regime`). `assets`: até
    `len(other_symbols)` resultados (normalmente os 4 não-BTC) -- um
    símbolo sem folds suficientes é excluído com log, não derruba os
    outros (mesmo padrão AG-019 do resto do módulo)."""

    classifier_id: str
    btc_n_bars: int
    assets: tuple[Q3AssetResult, ...]


def _asof_join_btc_labels(btc_raw: RawLabels, asset_raw: RawLabels) -> tuple[IntArray, IntArray]:
    """`join_asof` BACKWARD do rótulo de BTC nos timestamps do ativo --
    prova de causalidade central de Q3 (DoD do plano `wise-exploring-
    panda.md`, seção "Q3/as-of join"): cada barra do ativo recebe o
    rótulo de BTC mais recente que já existia ATÉ aquele timestamp
    (`close_time_ms` de BTC `<=` o do ativo), NUNCA um rótulo futuro.
    `strategy="backward"` do `polars.DataFrame.join_asof` é exatamente
    essa semântica -- trocar por `"nearest"`/`"forward"` vazaria rótulo
    futuro pro ativo (o próprio DoD pede um teste que capture essa troca,
    `test_asof_join_btc_labels_e_estritamente_backward_nunca_futuro`).
    Mesmo primitivo já usado em produção pra alinhar dado auxiliar de
    timestamp diferente (`src.features._sources.asof_align_backward`,
    `src.validation.leakage._test_04_funding_futuro`) -- não uma técnica
    nova, reaplicada aqui a rótulo de regime em vez de feature.

    **`close_time_ms`, não `open_time_ms` -- corrigido 2026-08-19, AG-090
    (achado de auditoria cética):** o rótulo de BTC só é CONHECÍVEL
    quando a barra de BTC FECHA -- chavear em `open_time_ms` deixaria o
    ativo "herdar" um rótulo de BTC calculado sobre uma barra que ainda
    nem tinha fechado no timestamp de referência, vazamento temporal
    (mesma classe de B02). `close_time_ms` do ativo é o lado certo da
    comparação também -- é quando a PRÓPRIA barra do ativo se torna
    conhecível/comparável, ver docstring de `RawLabels`.

    BTC e o ativo têm timestamps de dollar-bar DIFERENTES (dollar-bar é
    disparada por volume negociado, não por tempo -- BTC e XRP não têm as
    mesmas barras) -- por isso o join é por TIMESTAMP, nunca por índice
    posicional.

    Barras do ativo ANTERIORES ao primeiro timestamp de BTC em `btc_raw`
    não têm rótulo de BTC pra herdar (nenhum "backward" existe ainda) --
    `join_asof` devolve `null` nessas posições, filtradas aqui
    explicitamente (nunca tratado como um rótulo real) -- cobre o caso
    real medido nesta sessão (BTC com dado desde 2019-12-31, os 4 alts só
    desde 2021-12-01: nesse caso real específico a sobreposição costuma
    ser total, mas esta função trata o caso geral, não assume isso).

    Retorna `(labels_own, labels_btc_derived)` só na região de
    sobreposição (pode ser menor que `asset_raw` inteiro) -- nunca
    levanta por sobreposição parcial/vazia; `run_q3_common_factor_regime`
    decide o que fazer com `n_compared` pequeno/zero (`NaN`, não crash)."""
    btc_df = pl.DataFrame(
        {"close_time_ms": btc_raw.close_time_ms, "btc_canonical_id": btc_raw.canonical_id}
    ).sort("close_time_ms")
    asset_df = pl.DataFrame(
        {"close_time_ms": asset_raw.close_time_ms, "own_canonical_id": asset_raw.canonical_id}
    ).sort("close_time_ms")

    joined = asset_df.join_asof(btc_df, on="close_time_ms", strategy="backward")
    overlap = joined.filter(pl.col("btc_canonical_id").is_not_null())

    labels_own: IntArray = overlap["own_canonical_id"].cast(pl.Int64).to_numpy()
    labels_btc_derived: IntArray = overlap["btc_canonical_id"].cast(pl.Int64).to_numpy()
    return labels_own, labels_btc_derived


def run_q3_common_factor_regime(
    btc_result: SymbolResult,
    btc_raw_labels: dict[str, RawLabels],
    *,
    classifier_id: str,
    other_symbols: tuple[str, ...] = _Q3_DEFAULT_OTHER_SYMBOLS,
    end: str = END_DATE,
    initial_train_years: int | None = None,
    hmm_states_grid: tuple[int, ...] = (2, 3, 4),
    jump_n_states: int,
    jump_penalty: float,
    bocpd_hazard_lambda: float,
    bocpd_n_canonical_buckets: int,
    hmm_seed: int = 0,
    jump_seed: int = 0,
) -> Q3Result:
    """Terceira via (Q3) do M4 (`PRD_V4_1.md` §3.2) -- com ρ≈0,91 de
    correlação de preço entre BTC e os outros 4 ativos, testa se
    classificar regime só no BTC e aplicar aos outros 4 (as-of, causal) é
    suficiente, comparado contra a classificação PRÓPRIA de cada ativo
    (mesmo candidato/config, rodado independentemente sobre o dado
    daquele ativo).

    **AGNÓSTICA a qual dos 4 candidatos do M4 (baseline/HMM/Jump Model/
    BOCPD) é usado** -- `classifier_id` é um parâmetro (lookup no dict de
    `RawLabels`, nunca um `if classifier_id == "..."` hardcoded aqui).
    QUAL candidato "vence" o M4 só é sabido depois da execução real (Fase
    6, ainda não rodou) -- decisão de escopo do plano `wise-exploring-
    panda.md`: esta função só entrega a CAPACIDADE de rodar Q3 pra
    qualquer candidato, não decide qual.

    `btc_result`/`btc_raw_labels`: resultado JÁ CALCULADO de
    `compare_regime_candidates_for_symbol(symbol="BTCUSDT", ...,
    return_raw_labels=True)` -- reusa, não recomputa (mesma leitura do
    plano: "Terceira via Q3 (reusa fits, sem reajuste novo)"). Levanta
    `ValueError` se `btc_result.symbol != "BTCUSDT"` (Q3 testa
    especificamente BTC como fator comum, não outro símbolo -- decisão já
    fechada no plano/PRD, não um parâmetro livre aqui) ou se
    `classifier_id` não estiver em `btc_raw_labels`.

    Para cada um dos `other_symbols` (default os 4 não-BTC de
    `ALL_SYMBOLS`): chama `run_regime_comparison_for_symbol(...,
    return_raw_labels=True)` de novo, com os MESMOS hiperparâmetros
    passados aqui (garante "mesmo candidato/config" entre BTC e o ativo,
    exigência do desenho de Q3) -- reaproveita a MESMA função da Fase
    3/IO real, zero lógica de fold/candidato duplicada. Decisão de
    desenho aceita, não escondida: isso roda os 6 candidatos (baseline +
    3 HMM + Jump Model + BOCPD) por ativo, não só o `classifier_id`
    pedido -- o custo extra dos 5 candidatos descartados não foi medido
    (TBD -- medir se/quando a Fase 6/7 rodar isto de verdade contra os 5
    símbolos completos); aceitável para uma função que ainda NÃO é
    chamada em produção (ver `run_and_save_m4_report`, que não invoca
    Q3). Um ativo sem folds suficientes (`run_regime_comparison_for_
    symbol` retorna `None`) é logado e EXCLUÍDO de `Q3Result.assets`, não
    derruba os outros ativos (mesmo padrão AG-019 do resto do módulo).

    Para cada ativo com dado suficiente: `_asof_join_btc_labels` (backward,
    causal) + `adjusted_rand` na região de sobreposição -- ver
    `Q3AssetResult`/`_asof_join_btc_labels` para o tratamento de
    sobreposição parcial (excluída da métrica, nunca um crash) e de
    `n_compared` pequeno/zero (`NaN`, não um valor inventado).

    Hiperparâmetros de candidato sem default (mesma disciplina de
    `run_and_save_m4_report`/`compare_regime_candidates_for_symbol`) --
    ainda dependem de calibração/confirmação do Manager (Fase 6). Esta
    função não é chamada por nenhum script de produção neste módulo."""
    if btc_result.symbol != "BTCUSDT":
        raise ValueError(
            f"run_q3_common_factor_regime: btc_result.symbol={btc_result.symbol!r}, esperado "
            "'BTCUSDT' -- Q3 testa BTC como fator comum de regime, não outro símbolo"
        )
    if classifier_id not in btc_raw_labels:
        raise ValueError(
            f"run_q3_common_factor_regime: classifier_id={classifier_id!r} não encontrado em "
            f"btc_raw_labels (chaves disponíveis: {sorted(btc_raw_labels)}) -- confirme que "
            "compare_regime_candidates_for_symbol(..., return_raw_labels=True) foi chamada com "
            "os MESMOS hiperparâmetros passados aqui"
        )
    btc_raw = btc_raw_labels[classifier_id]

    assets: list[Q3AssetResult] = []
    for symbol in other_symbols:
        asset_computed = run_regime_comparison_for_symbol(
            symbol,
            SYMBOL_START_DATE[symbol],
            end,
            initial_train_years=initial_train_years,
            hmm_states_grid=hmm_states_grid,
            jump_n_states=jump_n_states,
            jump_penalty=jump_penalty,
            bocpd_hazard_lambda=bocpd_hazard_lambda,
            bocpd_n_canonical_buckets=bocpd_n_canonical_buckets,
            hmm_seed=hmm_seed,
            jump_seed=jump_seed,
            return_raw_labels=True,
        )
        if asset_computed is None:
            logger.warning("analysis.m4_regime_comparison.q3_folds_insuficientes", symbol=symbol)
            continue
        _asset_symbol_result, asset_raw_labels = asset_computed
        if classifier_id not in asset_raw_labels:
            raise ValueError(
                f"run_q3_common_factor_regime: classifier_id={classifier_id!r} não encontrado "
                f"em asset_raw_labels de {symbol!r} (chaves disponíveis: "
                f"{sorted(asset_raw_labels)})"
            )
        asset_raw = asset_raw_labels[classifier_id]

        labels_own, labels_btc_derived = _asof_join_btc_labels(btc_raw, asset_raw)
        n_compared = int(labels_own.shape[0])
        if n_compared < _Q3_MIN_BARS_COMPARED:
            logger.warning(
                "analysis.m4_regime_comparison.q3_sobreposicao_insuficiente",
                symbol=symbol,
                n_bars_compared=n_compared,
            )
            ari = float("nan")
        else:
            ari = adjusted_rand(labels_own, labels_btc_derived)

        assets.append(
            Q3AssetResult(
                symbol=symbol,
                n_bars_compared=n_compared,
                adjusted_rand_own_vs_btc_derived=ari,
            )
        )

    return Q3Result(
        classifier_id=classifier_id,
        btc_n_bars=int(btc_raw.open_time_ms.shape[0]),
        assets=tuple(assets),
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
    "Terceira via (Q3, BTC como fator comum via as-of join causal) esta implementada "
    "(run_q3_common_factor_regime, Fase 4 do plano wise-exploring-panda.md) mas NAO e "
    "chamada por este relatorio -- decisao de escopo (Fase 6/7 decide qual candidato "
    "testar via Q3, nao este script). compare_regime_candidates_for_symbol/"
    "run_regime_comparison_for_symbol expoem os rotulos brutos por barra via "
    "return_raw_labels=True (RawLabels, dataclass irmao de CandidateResult, nunca um "
    "array dentro dele) -- ver docstring do modulo, secao Fase 4 (Q3)."
)

_JUMP_MODEL_CAUSALITY_CAVEAT: Final[str] = (
    "Jump Model (jump_model_cjm_v1) decodifica o fold de teste em BLOCO via "
    "predict_jump_model -> fit.model.predict() (Viterbi global de jumpmodels.jump.dp) -- "
    "o forward pass e causal (values[t] so usa loss_mx[0..t]), mas o TRACEBACK anda de "
    "tras pra frente a partir de assign[-1]=argmin(values[-1]), entao o rotulo canonico "
    "numa barra t PODE depender de uma observacao em t' > t DENTRO DO MESMO FOLD DE "
    "TESTE (confirmado empiricamente, nao so por leitura de codigo -- ver docstring de "
    "src.regime.jump_model e test_perturbar_fim_do_fold_pode_mudar_inicio_do_mesmo_fold). "
    "Isso NUNCA cruza fronteira de fold e NUNCA toca dado de treino (fit.model ja esta "
    "ajustado -- centers_/jump_penalty_mx congelados -- antes de predict_jump_model ser "
    "chamada; ver test_perturbar_fora_do_fold_nao_muda_decode_do_fold). E DIFERENTE de "
    "HMM (predict_hmm_gaussian via hmm.filter, posterior estritamente causal barra-a-"
    "barra mesmo dentro do fold) e de BOCPD (online por construcao, sem nocao de fold "
    "nenhuma) -- os outros 2 candidatos novos nunca veem nada alem do passado, nem "
    "dentro do proprio fold. Decisao do Manager (2026-08-18): manter .predict() como "
    "esta (nao trocar para predict_online(), que e causal barra-a-barra mas nao replica "
    "o desenho real do walk-forward do M4 -- decodificar o fold de teste inteiro de uma "
    "vez); leia o resultado do Jump Model com essa ressalva -- ele pode carregar uma "
    "vantagem de decodificacao (olhar o fold de teste inteiro de uma vez) que nao esta "
    "relacionada a qualidade real de deteccao de regime, ao contrario de HMM/BOCPD."
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
    bocpd_hazard_lambda=..., bocpd_n_canonical_buckets=...)"`

    **`mp_context="spawn"` explícito -- achado HIGH de auditoria
    (`audit_engineering`, 2026-08-17).** Sem isso, `ProcessPoolExecutor`
    usa o start method PADRÃO da plataforma -- `spawn` no Windows (onde
    este módulo roda hoje, `fork` inexistente), mas `fork` no Linux (até
    Python 3.13; produção deste motor é tipicamente Linux). JAX (via
    `src.regime.hmm_gaussian`, importado no topo deste módulo, portanto
    já inicializado no processo PAI antes de qualquer `submit`) documenta
    explicitamente que NÃO é fork-safe -- JAX é multi-thread internamente,
    e `fork()` depois de threads já ativas é o padrão clássico de deadlock
    (`jax-ml/jax#1805`, discussão `#21073`: "JAX's computational model is
    not compatible with multiprocessing" sob fork). Forçar `spawn`
    explicitamente elimina a dependência implícita da plataforma --
    comportamento idêntico ao já observado no Windows, mas agora
    determinístico em qualquer SO, sem depender de qual máquina roda o
    comando."""
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
    mp_context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp_context) as executor:
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
        "jump_model_causality_caveat": _JUMP_MODEL_CAUSALITY_CAVEAT,
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
