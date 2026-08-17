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
alvo de previsão em `t`, não a variância já realizada em `t`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

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
