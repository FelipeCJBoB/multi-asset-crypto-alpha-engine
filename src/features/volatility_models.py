"""HAR-RV (Corsi 2009) — PRD_V4_1.md §3.2 M1, 1 dos 3 candidatos "fold-aware"
amputados do harness de comparação (`ATRWilder`/`HAR-RV`/`EGARCH(1,1)`
removidos junto com este arquivo em `2436b33`, ver docstring de
`src.analysis.volatility_comparison`) — resgatado e READAPTADO pra grade
dollar-bar por decisão do Manager (`AG-036`, `audit/architecture_gaps_log.
yaml`, `addendum_decisao_escopo_2026_08_17`).

**2º dos 3 resgates, na ordem de prioridade de `addendum_pesquisa_
readaptacao_2026_08_17` (RealizedVol → HAR-RV → EGARCH, custo/dependência
de P-2 ascendente).** `RealizedVolEstimator` (esforço PEQUENO, ~95% reúso)
já foi resgatado em `src.features.volatility` (commit `3890f20`). **Este
arquivo NÃO traz EGARCH(1,1) de volta** — o mesmo addendum classifica
EGARCH como esforço GRANDE, genuinamente BLOQUEADO: ao contrário de HAR-RV
(só a AGREGAÇÃO precisa mudar), a FÓRMULA do EGARCH em si precisaria mudar
(2 rotas plausíveis, ACD-GARCH acoplado ou heurística de escala por
duração — Ghysels & Jasiak 1998, Engle & Russell UHF-GARCH), e a escolha
certa depende de conhecer a forma real da distribuição de duração de
dollar bar (P-2, `docs/refactor_dollar_bar_canonico.md`) de um jeito que
HAR-RV não depende. Trazer EGARCH de volta sem essa decisão de desenho
fingiria um resgate que a pesquisa já identificou como não-mecânico —
fica de fora desta leva, rastreado à parte em `AG-036`.

Base real trazida de `git show 50dd621:src/features/volatility_models.py`
(estado final do arquivo antes da remoção em `2436b33`, confirmado via
`git log --diff-filter=D`) — interface deliberadamente DIFERENTE do
`estimate()` de fórmula fechada de `src.features.volatility.
VolatilityEstimator`: `fit(train) -> HARRVFit` / `predict(fit,
full_series) -> forecast_var`, porque HAR-RV não tem uma resposta sem ver
dado de treino primeiro (regressão OLS por fold, não fórmula fechada) —
não força pro `Protocol` simples dos 5 estimadores fechados (pesquisa já
confirmou isso, ver addendums de `AG-036`). Serve o harness walk-forward
de M1 (`src.analysis.volatility_comparison`, que refit a cada fold); NÃO
está integrado a esse harness nesta leva — reintegração é decisão de
escopo futura (quando M1 rerodar sob dollar bar com os 8 candidatos,
já registrada em `AG-036`), fora do que este módulo resolve sozinho.

**Única mudança real desta readaptação: `_har_components` troca janela em
CONTAGEM DE BARRA fixa (`bars_per_day` caller-supplied, presumia relógio
uniforme — cada barra = mesma duração nominal) por janela causal em
RELÓGIO REAL usando `close_time`** (já persistido em ms epoch tanto em
`schemas.DOLLAR_BARS_R1` quanto em `bars_15m`/grade de tempo). `day[t] =
média(realized_var[i])` para todo `i` com `close_time[i] < close_time[t]`
(ESTRITO, nunca `<=` — uma rajada com `close_time` repetido entre 2+
barras, `AG-061`, vazaria B02 se a comparação fosse `<=`) **e**
`close_time[t] - close_time[i] <= 86_400_000` ms (idem ×7/×30 pra
semana/mês). Sob dollar bar isso soma o que existir dentro do período
real — 1 barra ou 500 — corretamente por construção (distribuição real de
duração medida em `experiments/dollar_bar_duration_distribution.json`,
`AG-061`: mediana 7,5-9,9min, p99 73,6-98,7min, forte assimetria/cauda
pesada). A correção F1 (`fit_end_idx = train_end_idx - 1`, vazamento de 1
barra do achado original de auditoria: o último alvo "dentro do treino"
seria `realized_var[train_end_idx-1] = close[train_end_idx]²`-dependente,
1ª barra de TESTE) permanece INTACTA — não é o que muda aqui.

**Trade-off intencional do relógio real, documentado, não um bug**: sob
`_causal_window_mean`, uma barra com só 1 observação disponível dentro da
janela de 1 dia (regime de baixíssima atividade) recebe uma média válida
(a própria observação), não `NaN` — diferente do comportamento antigo por
contagem-de-barra, que exigia a janela inteira preenchida (`window_n ==
window`) antes de sair do `NaN` de warmup. Essa diferença só aparece na
RAMPA DE WARMUP no início da série (sob relógio uniforme, os valores em
regime estacionário — janela já coberta — são bit-idênticos entre os dois
desenhos, ver `tests/unit/test_features_volatility_models.py`). `NaN`
continua sendo o resultado, explícito e documentado, quando a janela está
literalmente vazia (nenhuma observação anterior); o freio estatístico
contra amostra pequena continua sendo `_MIN_TRAIN_OBS` no nível da
regressão (`fit_har_rv`), não um mínimo por-janela — decisão consciente,
não omissão (ver addendum `addendum_pesquisa_readaptacao_2026_08_17`:
"a janela causal em relógio real já lida com isso corretamente por
construção").

**Limitação diurnal conhecida, PRÉ-EXISTENTE à questão de dollar bar
(preservada aqui, não resolvida)**: o commit original já documentava que
HAR-RV intraday não tem ajuste de padrão diurnal (sazonalidade
intra-dia da volatilidade) — as cascatas dia/semana/mês capturam
sazonalidade de CALENDÁRIO, não de hora-do-dia. Independente do relógio
ser uniforme (grade de tempo) ou real (dollar bar); fora do escopo desta
readaptação.

`mu` (média do retorno) não entra aqui — HAR-RV regride direto em escala
de VARIÂNCIA (`realized_var[t] = r_{t+1}²`, mesma convenção do resto do
módulo — `next_bar_realized_variance`, `volatility_walkforward.py` — o
alvo de previsão em `t`, não a variância já realizada em `t`).

============================================================================
EGARCH(1,1) ACOPLADO — extensão por analogia, NÃO reprodução de paper
============================================================================

3º e último candidato amputado de M1 resgatado (`AG-036`,
`audit/architecture_gaps_log.yaml` — ver especialmente os 3 addendums de
`2026-08-17`: `addendum_decisao_egarch_2026_08_17`,
`addendum_pesquisa_acd_garch_2026_08_17`, `addendum_decisao_final_2026_08_17`).
Base real trazida de `git show 50dd621:src/features/volatility_models.py`
(`EGARCHFit`/`fit_egarch`/`predict_egarch`/`_egarch_log_var_recursion`/
`_egarch_neg_log_likelihood` — estado final antes da remoção em `2436b33`) —
renomeada com sufixo `_coupled` (`EGARCHCoupledFit`/`fit_egarch_coupled`/
`predict_egarch_coupled`/`_egarch_log_var_recursion_coupled`/
`_egarch_neg_log_likelihood_coupled`) para não reintroduzir os nomes sem
sufixo — evita confusão com uma futura versão não-acoplada, se algum dia
necessária.

**Isto NÃO é reprodução de Ghysels & Jasiak (1998).** Pesquisa aprofundada
(`addendum_pesquisa_acd_garch_2026_08_17`) confirmou 2 achados que mudam o
quadro: (1) a equação fechada exata do acoplamento GJ98 não foi
recuperável em fonte alguma acessível (paper de 1998 é scan sem OCR,
working paper CIRANO e réplicas completas atrás de paywall/login-gate —
tentativa real, não desistência prematura); (2) GJ98 acopla ACD a
GARCH(1,1) LINEAR, não ao EGARCH de Nelson (1991), que é o candidato real
deste projeto — famílias matematicamente diferentes. O Manager decidiu
explicitamente (`addendum_decisao_final_2026_08_17`) implementar mesmo
assim: uma extensão NOVA deste projeto, inspirada na ideia GERAL de GJ98
("parâmetros do GARCH viram função da duração", que por sua vez se apoia em
Drost & Nijman 1993/Drost & Werker 1996, teoria de agregação temporal) —
aplicada por analogia à recursão discreta de Nelson-EGARCH, não citação
direta. Toda constante nova aqui é `provenance: ASSUMED`/`DERIVED`-por-
analogia — NUNCA `LITERATURE` — com `sweep_required: true` quando
promovida (Regra Zero, `CLAUDE.md`). Nunca escrever "conforme Ghysels &
Jasiak (1998)" como se fosse a fórmula deles — a formulação abaixo é
"inspirada em"/"por analogia com".

**O que muda vs. o EGARCH original (recursão de Nelson 1991 intacta como
caso particular)**:

1. Recebe `psi: FloatArray` — saída de `src.features.acd.predict_acd`
   (bar-indexado, mesmo comprimento de `log_return`; ver docstring daquele
   módulo pra convenção de índice/NaN de fronteira) — como parâmetro
   adicional em `fit_egarch_coupled`/`predict_egarch_coupled`.
2. `psi_bar = mediana(psi[válidos])` **no TREINO** (`EGARCHCoupledFit.
   psi_bar`, fixo, calculado 1x no fit, mesma convenção de `log_var_seed`)
   — mediana, não média: robusta à cauda pesada de duração real medida em
   `AG-061` (assimetria 2,3–5,7, curtose em excesso 8,6–61,5 nos 5
   símbolos — média seria dominada pelos poucos eventos de duração extrema).
3. `tau_i = psi_i / psi_bar` (razão adimensional de duração relativa).
   Onde `psi_i` é NaN/indisponível (warmup — inclui a barra 0, ver
   `predict_acd`), `tau_i = 1.0` (neutro — reduz à recursão original
   exatamente nessa barra, não inventa comportamento novo pro warmup).
4. Recursão modificada (`_egarch_log_var_recursion_coupled`):

       log_var[t+1] = omega + (beta**tau_t)*log_var[t]
                      + tau_t*(alpha*(|z_t|-E|z|) + gamma*z_t)

   Intuição (qualitativa, não derivação formal — é a mesma direção
   conceitual de Drost&Nijman/GJ98 aplicada por analogia à forma de
   Nelson): duração relativa MAIOR (`tau_i>1`, mais tempo de calendário
   decorrido) → `beta**tau_i` MENOR (já que `0<=beta<1`, ver bound abaixo)
   → reversão à média mais rápida — "mais tempo decorrido, mais a
   variância esquece o estado anterior". E `tau_i·(...)` maior → o choque
   realizado nessa barra entra com peso proporcionalmente maior na
   atualização — a barra "representa" mais tempo de calendário, seu peso
   informacional escala com isso.

**Decisão NÃO coberta explicitamente pela spec desta sessão, tomada aqui e
sinalizada para revisão**: `beta` (persistência do EGARCH) tem bound
`[0.0, 0.999)` em `fit_egarch_coupled` — MAIS RESTRITO que o `(-0.999,
0.999)` do EGARCH original. Motivo, verificado empiricamente antes de
decidir (não suposição): `beta**tau_t` com `tau_t` não-inteiro e `beta`
NEGATIVO produz número COMPLEXO em ponto flutuante Python puro
(`(-0.5)**1.3` → `(-0.239-0.329j)`, sem erro, silencioso) ou `NaN` com
`RuntimeWarning` em numpy escalar/array (`np.float64(-0.5)**1.3` →
`RuntimeWarning: invalid value encountered in power`) — CLAUDE.md proíbe
silenciar warning sem corrigir a causa raiz; restringir o domínio de busca
do otimizador pra onde `beta**tau_t` é sempre real bem-definido é a
correção da causa raiz (o formato de acoplamento só faz sentido
matematicamente pra persistência não-negativa), não um workaround em cima
do sintoma. Confirmado que isso NÃO quebra a propriedade de bit-exatidão
(abaixo): sob `tau_t≡1.0` (relógio uniforme), `beta**1.0 == beta` EXATO
em ponto flutuante para QUALQUER `beta` (positivo ou negativo — o expoente
inteiro 1.0 nunca cai no ramo de potência fracionária, verificado via
`np.float64(-0.5)**1.0 == -0.5`, sem warning) — o teste de bit-exatidão
usa `beta` negativo deliberadamente pra provar isso na RECURSÃO em
qualquer domínio; só o BOUND do OTIMIZADOR (`fit_egarch_coupled`) é mais
estreito que o original, não a recursão em si (`_egarch_log_var_recursion_
coupled` aceita `beta` de qualquer sinal — quem chama com relógio real e
`beta` negativo por fora do fit é responsável por essa escolha).

**Propriedade de sanidade OBRIGATÓRIA (bit-exatidão sob relógio uniforme)**:
sob `tau_i≡1` pra todo `i` (`psi_i≡psi_bar`), a recursão modificada é
bit-idêntica à original (`beta**1.0=beta`, `1.0*(...)=(...)`) — mesma prova
de retrocompatibilidade que HAR-RV/RealizedVol já fizeram (ver
`test_egarch_log_var_recursion_coupled_relogio_uniforme_bit_exato_vs_original`,
`tests/unit/test_features_volatility_models.py`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray
from scipy import optimize

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

_MIN_TRAIN_OBS = 10

# ms num dia real (24h) -- conversão de unidade, não hiperparâmetro de
# domínio (mesmo racional de `_MINUTE_MS`/`_MS_PER_DAY` já estabelecidos em
# src.labels.triple_barrier/src.execution.fill_simulator: fato sobre o
# calendário, não algo com proveniência MEASURED/ASSUMED a declarar).
# x7/x30 pra semana/mês -- convenção HAR-RV (Corsi 2009) de cascata
# dia/semana/mês, cripto 24/7 (não 5/22 dias úteis de bolsa tradicional,
# mesma ressalva já feita pelo módulo original).
_MS_PER_DAY: Final[int] = 86_400_000
_MS_PER_WEEK: Final[int] = _MS_PER_DAY * 7
_MS_PER_MONTH: Final[int] = _MS_PER_DAY * 30


def _causal_window_mean(x: FloatArray, close_time: IntArray, window_ms: int) -> FloatArray:
    """`out[t] = média(x[i])` para todo `i` com `close_time[i] < close_time[t]`
    (ESTRITO -- nunca inclui `t` nem qualquer barra com o MESMO `close_time`
    de `t`, mesmo sob rajada com timestamp repetido, `AG-061`) **e**
    `close_time[t] - close_time[i] <= window_ms`. `NaN` em `x[i]` não entra
    na média (soma/contagem separadas). `out[t]` é `NaN` só quando a janela
    está literalmente vazia (0 observações válidas) -- explícito, não
    silencioso; ver docstring do módulo sobre por que não há mínimo de
    contagem por-janela além disso.

    Substitui a antiga `_rolling_mean_causal` (janela em CONTAGEM DE BARRA
    fixa) -- sob dollar bar essa contagem deixava de corresponder a um
    período de calendário fixo (`AG-036`). `close_time` precisa estar
    ordenado ASCENDENTE (não-decrescente) -- garantido por construção tanto
    em `bars_15m` (`open_time`/`close_time` sequenciais) quanto em
    `dollar_bars_r1` (`schemas.DOLLAR_BARS_R1`); verificado aqui, não
    presumido silenciosamente, porque um `close_time` fora de ordem faria
    `np.searchsorted` devolver resultado incorreto sem erro nenhum.

    Implementação: `np.searchsorted` vetorizado faz o papel de um
    two-pointer causal em O(n log n) -- mesma técnica de
    `src.labels.triple_barrier` (que já usa `np.searchsorted` sobre
    `close_time`/`open_time` real). `hi_idx[t]` = nº de barras com
    `close_time` ESTRITAMENTE `< close_time[t]` (`side="left"` devolve a
    posição da PRIMEIRA ocorrência do valor `close_time[t]`, que é
    exatamente essa contagem -- exclui `t` e qualquer duplicata do mesmo
    `close_time`). `lo_idx[t]` = primeira barra dentro da janela de
    `window_ms`. Soma cumulativa (`csum`/`ccount`) transforma a diferença
    de índices numa soma/contagem de janela em O(1) por barra."""
    n = x.shape[0]
    if close_time.shape[0] != n:
        raise ValueError(
            f"close_time.shape[0]={close_time.shape[0]} != x.shape[0]={n} -- "
            "os dois arrays precisam ter o mesmo comprimento, 1 close_time por barra"
        )
    if n == 0:
        return np.full(0, np.nan, dtype=np.float64)
    if n > 1 and bool(np.any(np.diff(close_time) < 0)):
        raise ValueError(
            "close_time precisa estar ordenado ascendente (não-decrescente) -- "
            "garantido por construção em bars_15m/dollar_bars_r1 (bars ordenadas "
            "por close_time), mas não pelo contrato desta função; ordene antes "
            "de chamar (`.sort('close_time')` no DataFrame de origem)."
        )

    valid = np.isfinite(x)
    x_filled = np.where(valid, x, 0.0)
    csum = np.concatenate(([0.0], np.cumsum(x_filled)))
    ccount = np.concatenate(([0], np.cumsum(valid.astype(np.int64))))

    hi_idx = np.searchsorted(close_time, close_time, side="left")
    lo_idx = np.searchsorted(close_time, close_time - window_ms, side="left")

    window_sum = csum[hi_idx] - csum[lo_idx]
    window_count = ccount[hi_idx] - ccount[lo_idx]

    out = np.full(n, np.nan, dtype=np.float64)
    # `where=` evita a divisão nos índices com window_count==0 -- `out` já
    # é NaN ali por construção. Não há runtime warning pra suprimir porque
    # a divisão nunca roda onde o denominador seria 0 (never remediate,
    # always solve -- guarda de verdade, não np.errstate por cima).
    np.divide(window_sum, window_count, out=out, where=window_count > 0)
    return out


def _har_components(
    realized_var: FloatArray, *, close_time: IntArray
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """`day[t]/week[t]/month[t] = média causal de `realized_var` em janela
    de RELÓGIO REAL de 1 dia/7 dias/30 dias, via `_causal_window_mean` --
    ESTRITAMENTE `close_time < close_time[t]`, nunca usa nada de `t` em
    diante nos regressores (a comparação estrita já garante isso por
    construção, sem precisar deslocar o array de entrada como a versão por
    contagem-de-barra antiga precisava)."""
    day = _causal_window_mean(realized_var, close_time, _MS_PER_DAY)
    week = _causal_window_mean(realized_var, close_time, _MS_PER_WEEK)
    month = _causal_window_mean(realized_var, close_time, _MS_PER_MONTH)
    return day, week, month


@dataclass(frozen=True, slots=True)
class HARRVFit:
    """Coeficientes de `realized_var[t] = intercept + beta_day*day[t] +
    beta_week*week[t] + beta_month*month[t] + erro`, ajustados por OLS
    sobre `realized_var[:train_end_idx]`."""

    intercept: float
    beta_day: float
    beta_week: float
    beta_month: float
    n_train: int


def fit_har_rv(
    realized_var: FloatArray, *, close_time: IntArray, train_end_idx: int
) -> HARRVFit | None:
    """`None` se não houver `_MIN_TRAIN_OBS` pares válidos (dia/semana/mês
    + alvo todos finitos) no treino -- sinal explícito pro chamador pular
    o fold, nunca um ajuste fabricado sobre amostra insuficiente.

    Alvo vai só até `train_end_idx - 2` (não `train_end_idx - 1`): como
    `realized_var[t] = r_{t+1}²` (convenção do módulo), o último alvo
    "dentro do treino" seria `realized_var[train_end_idx-1]`, mas esse
    valor depende de `close[train_end_idx]` -- a primeira barra de TESTE.
    Cortar em `train_end_idx - 1` (exclusive) garante que nenhum par de
    treino depende de preço fora de `[0, train_end_idx)` (correção F1 do
    audit_engineering, 2026-08-11 -- preservada intacta nesta readaptação,
    não é o que mudou pra dollar bar)."""
    day, week, month = _har_components(realized_var, close_time=close_time)
    fit_end_idx = train_end_idx - 1
    y = realized_var[:fit_end_idx]
    x_day = day[:fit_end_idx]
    x_week = week[:fit_end_idx]
    x_month = month[:fit_end_idx]
    mask = np.isfinite(y) & np.isfinite(x_day) & np.isfinite(x_week) & np.isfinite(x_month)
    n_valid = int(np.sum(mask))
    if n_valid < _MIN_TRAIN_OBS:
        return None
    design = np.column_stack(
        [np.ones(n_valid, dtype=np.float64), x_day[mask], x_week[mask], x_month[mask]]
    )
    coeffs, _residuals, _rank, _sv = np.linalg.lstsq(design, y[mask], rcond=None)
    return HARRVFit(
        intercept=float(coeffs[0]),
        beta_day=float(coeffs[1]),
        beta_week=float(coeffs[2]),
        beta_month=float(coeffs[3]),
        n_train=n_valid,
    )


def predict_har_rv(
    fit: HARRVFit, realized_var: FloatArray, *, close_time: IntArray
) -> FloatArray:
    """Forecast de variância (não sigma -- diferente de `VolatilityEstimator.
    estimate()`, HAR-RV regride direto em escala de variância) para toda a
    série -- o chamador (`volatility_comparison.py`, se/quando este módulo
    for reintegrado ao harness) recorta a região de teste do fold
    correspondente a este `fit`. Forecast `<= 0` (regressão linear não
    restringe sinal) vira NaN em vez de variância negativa silenciosa --
    mesma disciplina de `qlike_loss` sobre forecast inválido."""
    day, week, month = _har_components(realized_var, close_time=close_time)
    forecast = fit.intercept + fit.beta_day * day + fit.beta_week * week + fit.beta_month * month
    out: FloatArray = np.where(forecast > 0, forecast, np.nan)
    return out


# ============================================================================
# EGARCH(1,1) ACOPLADO (Nelson 1991 + extensão por analogia a Ghysels &
# Jasiak 1998) -- ver docstring do módulo pra desenho completo/decisões.
# ============================================================================

_EGARCH_MIN_TRAIN_OBS = 50
# exp(50) ~ 5e21 -- mesmo teto de sanidade numérica do original (git show
# 50dd621), nunca atingido por um fit real.
_EGARCH_LOG_VAR_CLIP = 50.0  # noqa: magic-number
# E|z| pra z~N(0,1), termo padrão do EGARCH (Nelson 1991), mesmo do original.
_SQRT_2_OVER_PI = float(np.sqrt(2.0 / np.pi))  # noqa: unguarded-ratio -- np.pi é constante matemática, nunca 0

# Bounds/x0 do otimizador L-BFGS-B -- detalhe de implementação, fora de
# constants.yaml (mesmo precedente do EGARCH original: bounds já eram
# hardcoded, nunca entraram em constants.yaml). alpha/gamma/omega mantêm o
# MESMO valor numérico do original; beta diverge (ver docstring do módulo,
# "Decisão NÃO coberta explicitamente pela spec").
_EGARCH_ALPHA_GAMMA_BOUND = 5.0  # noqa: magic-number -- mesmo bound do original
_EGARCH_BETA_UPPER_BOUND = 0.999  # noqa: magic-number -- mesmo teto do original
_EGARCH_X0_ALPHA = 0.1  # noqa: magic-number -- mesmo x0 do original
_EGARCH_X0_BETA = 0.9  # noqa: magic-number -- mesmo x0 do original
_EGARCH_X0_OMEGA_FRACTION = 0.1  # noqa: magic-number -- mesmo x0 do original (log_var_seed*0.1)
_EGARCH_NEG_LOG_LIK_PENALTY = 1e12  # noqa: magic-number -- mesmo fallback do original


def _egarch_log_var_recursion_coupled(
    log_return: FloatArray,
    *,
    omega: float,
    alpha: float,
    beta: float,
    gamma: float,
    log_var_seed: float,
    psi: FloatArray,
    psi_bar: float,
) -> FloatArray:
    """Mesma estrutura de `_egarch_log_var_recursion` (git show `50dd621`)
    -- ancorada em `log_var_seed` no primeiro retorno válido, recursiva daí
    em diante -- com a extensão por analogia da docstring do módulo:

        z_t = log_return[t] / sigma_t
        tau_t = psi[t]/psi_bar  (ou 1.0 se psi[t] não-finito -- warmup)
        log_var[t+1] = omega + (beta**tau_t)*log_var[t]
                       + tau_t*(alpha*(|z_t|-E|z|) + gamma*z_t)

    Sob `tau_t≡1.0` pra todo `t` (relógio uniforme), reduz-se EXATAMENTE à
    recursão original (`beta**1.0=beta`, `1.0*(...)=(...)`, ver
    `test_egarch_log_var_recursion_coupled_relogio_uniforme_bit_exato_vs_original`).

    `psi` precisa ter o mesmo comprimento de `log_return` (mesma convenção
    bar-indexada de `src.features.acd.predict_acd`)."""
    n = log_return.shape[0]
    if psi.shape[0] != n:
        raise ValueError(
            f"psi.shape[0]={psi.shape[0]} != log_return.shape[0]={n} -- "
            "psi precisa ser bar-indexado, mesmo comprimento de log_return "
            "(saída de src.features.acd.predict_acd sobre o mesmo close_time)"
        )
    log_var = np.full(n, np.nan, dtype=np.float64)
    first_valid = 0
    while first_valid < n and np.isnan(log_return[first_valid]):
        first_valid += 1
    if first_valid >= n:
        return log_var
    log_var[first_valid] = log_var_seed
    for t in range(first_valid, n - 1):
        lv = log_var[t]
        if not np.isfinite(lv):
            break
        sigma_t = float(np.sqrt(np.exp(min(lv, _EGARCH_LOG_VAR_CLIP))))
        eps_t = log_return[t]
        if np.isnan(eps_t) or sigma_t <= 0.0:
            log_var[t + 1] = lv
            continue
        z_t = eps_t / sigma_t
        psi_t = psi[t]
        # psi_bar>0 é validado no CHAMADOR (fit_egarch_coupled: `if not
        # np.isfinite(psi_bar) or psi_bar <= 0.0: return None`, mesma
        # guarda do sample_var/log_var_seed logo acima) -- invariante
        # cross-função, não checagem redundante dentro do laço quente.
        #
        # `psi_t <= 0.0` cai no MESMO fallback que `not isfinite(psi_t)`
        # (achado de project_assurance, 2026-08-17): `src.features.acd.
        # predict_acd` garante `psi>0` por construção (ver docstring de
        # `_acd_psi_recursion`), então isso nunca acontece no caminho real
        # hoje -- mas sem esta guarda, um `psi` vindo de qualquer outro
        # caller que violasse esse contrato produziria `tau_t<=0`, e
        # `beta**tau_t` com `beta=0.0` (extremo do bound, atingível pelo
        # otimizador) e expoente negativo levanta `ZeroDivisionError` não
        # tratado em vez de falhar graciosamente como o resto do módulo
        # (`return None`). Tratar como fronteira neutra (`tau_t=1.0`), não
        # deixar a exceção vazar.
        tau_t = (
            float(psi_t / psi_bar)  # noqa: unguarded-ratio -- psi_bar>0, psi_t>0 aqui, ver comentário acima
            if np.isfinite(psi_t) and psi_t > 0.0
            else 1.0
        )
        next_lv = (
            omega
            + (beta**tau_t) * lv
            + tau_t * (alpha * (abs(z_t) - _SQRT_2_OVER_PI) + gamma * z_t)
        )
        log_var[t + 1] = next_lv if np.isfinite(next_lv) else np.nan
    return log_var


def _egarch_neg_log_likelihood_coupled(
    params: FloatArray,
    log_return_train: FloatArray,
    log_var_seed: float,
    psi_train: FloatArray,
    psi_bar: float,
) -> float:
    omega, alpha, beta, gamma = params
    log_var = _egarch_log_var_recursion_coupled(
        log_return_train,
        omega=omega,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        log_var_seed=log_var_seed,
        psi=psi_train,
        psi_bar=psi_bar,
    )
    valid = np.isfinite(log_var) & ~np.isnan(log_return_train)
    if int(np.sum(valid)) < _EGARCH_MIN_TRAIN_OBS:
        return _EGARCH_NEG_LOG_LIK_PENALTY
    # var = exp(algo finito) é sempre >0 -- np.exp nunca retorna <=0 pra
    # entrada finita, e o clip acima garante entrada finita.
    var = np.exp(np.clip(log_var[valid], -_EGARCH_LOG_VAR_CLIP, _EGARCH_LOG_VAR_CLIP))
    eps = log_return_train[valid]
    log_lik = -0.5 * (np.log(2.0 * np.pi) + np.log(var) + eps**2 / var)  # noqa: unguarded-ratio -- var>0, ver comentário acima
    total = -float(np.sum(log_lik))
    return total if np.isfinite(total) else _EGARCH_NEG_LOG_LIK_PENALTY


@dataclass(frozen=True, slots=True)
class EGARCHCoupledFit:
    """Coeficientes de EGARCH(1,1) acoplado (ver docstring do módulo)
    ajustados por MLE sobre `log_return[:train_end_idx]`. `log_var_seed`
    (log da variância amostral do treino) e `psi_bar` (mediana de `psi`
    válidos no treino) são FIXOS, não ajustados por MLE junto dos outros 4
    -- mesma convenção do `EGARCHFit` original pra `log_var_seed`."""

    omega: float
    alpha: float
    beta: float
    gamma: float
    log_var_seed: float
    psi_bar: float
    n_train: int


def fit_egarch_coupled(
    log_return: FloatArray, psi: FloatArray, *, train_end_idx: int
) -> EGARCHCoupledFit | None:
    """`None` se `_EGARCH_MIN_TRAIN_OBS` não for atingido, variância
    amostral do treino for não-positiva/não-finita, `psi_bar` sair
    não-finito/não-positivo (nenhum `psi` válido no treino), ou o
    otimizador (`scipy.optimize.minimize`, L-BFGS-B) não convergir -- nunca
    devolve coeficientes de uma otimização que falhou (mesmo padrão de
    `fit_egarch`/`fit_har_rv`/`fit_acd`).

    `psi` precisa ter o mesmo comprimento de `log_return` (saída de
    `src.features.acd.predict_acd` sobre o mesmo `close_time`)."""
    if psi.shape[0] != log_return.shape[0]:
        raise ValueError(
            f"psi.shape[0]={psi.shape[0]} != log_return.shape[0]={log_return.shape[0]} -- "
            "psi precisa ser bar-indexado, mesmo comprimento de log_return"
        )
    train = log_return[:train_end_idx]
    psi_train = psi[:train_end_idx]
    valid_train = train[~np.isnan(train)]
    if valid_train.size < _EGARCH_MIN_TRAIN_OBS:
        return None
    sample_var = float(np.var(valid_train))
    if not np.isfinite(sample_var) or sample_var <= 0.0:
        return None
    log_var_seed = float(np.log(sample_var))

    psi_train_valid = psi_train[np.isfinite(psi_train)]
    if psi_train_valid.size == 0:
        return None
    psi_bar = float(np.median(psi_train_valid))
    if not np.isfinite(psi_bar) or psi_bar <= 0.0:
        return None

    x0 = np.array(
        [log_var_seed * _EGARCH_X0_OMEGA_FRACTION, _EGARCH_X0_ALPHA, _EGARCH_X0_BETA, 0.0],
        dtype=np.float64,
    )
    bounds = [
        (-_EGARCH_LOG_VAR_CLIP, _EGARCH_LOG_VAR_CLIP),
        (-_EGARCH_ALPHA_GAMMA_BOUND, _EGARCH_ALPHA_GAMMA_BOUND),
        (0.0, _EGARCH_BETA_UPPER_BOUND),
        (-_EGARCH_ALPHA_GAMMA_BOUND, _EGARCH_ALPHA_GAMMA_BOUND),
    ]
    result = optimize.minimize(
        _egarch_neg_log_likelihood_coupled,
        x0,
        args=(train, log_var_seed, psi_train, psi_bar),
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 200},
    )
    if not result.success or not np.all(np.isfinite(result.x)):
        return None
    omega, alpha, beta, gamma = (float(v) for v in result.x)
    return EGARCHCoupledFit(
        omega=omega,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        log_var_seed=log_var_seed,
        psi_bar=psi_bar,
        n_train=int(valid_train.size),
    )


def predict_egarch_coupled(
    fit: EGARCHCoupledFit, log_return: FloatArray, psi: FloatArray
) -> FloatArray:
    """`forecast_var[t] = sigma_{t+1}²` -- mesma convenção de
    `predict_egarch`/`predict_har_rv`. Recomputa a recursão inteira desde o
    início da série com os coeficientes deste fit (mesmo racional de
    `predict_egarch`: sequencial, não dá pra "aplicar" o fit numa janela
    isolada).

    Forecast não-finito ou `<=0` vira NaN explicitamente (mesmo padrão de
    `predict_har_rv`) -- redundante com o range de `exp()` sob a fórmula
    atual (sempre `>0` se finito), mas explícito por defesa em profundidade
    contra mudança futura da fórmula de acoplamento, não só propagação
    implícita de NaN."""
    if psi.shape[0] != log_return.shape[0]:
        raise ValueError(
            f"psi.shape[0]={psi.shape[0]} != log_return.shape[0]={log_return.shape[0]} -- "
            "psi precisa ser bar-indexado, mesmo comprimento de log_return"
        )
    log_var = _egarch_log_var_recursion_coupled(
        log_return,
        omega=fit.omega,
        alpha=fit.alpha,
        beta=fit.beta,
        gamma=fit.gamma,
        log_var_seed=fit.log_var_seed,
        psi=psi,
        psi_bar=fit.psi_bar,
    )
    n = log_return.shape[0]
    forecast_var = np.full(n, np.nan, dtype=np.float64)
    if n > 1:
        with np.errstate(over="ignore", invalid="ignore"):
            raw = np.exp(np.clip(log_var[1:], -_EGARCH_LOG_VAR_CLIP, _EGARCH_LOG_VAR_CLIP))
        forecast_var[:-1] = np.where(np.isfinite(raw) & (raw > 0), raw, np.nan)
    return forecast_var
