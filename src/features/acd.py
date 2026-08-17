"""ACD(1,1) (Engle & Russell 1998) — sub-modelo de DURAÇÃO sobre `close_time`
real de barra, 1ª metade do resgate "EGARCH acoplado" do 3º e último
candidato amputado de M1 (`AG-036`, `audit/architecture_gaps_log.yaml` —
ver especialmente os addendums de `2026-08-17`:
`addendum_decisao_egarch_2026_08_17`, `addendum_pesquisa_acd_garch_2026_08_17`,
`addendum_decisao_final_2026_08_17`).

**Isto NÃO é reprodução literal de Engle & Russell (1998).** O modelo ACD em
si (`ψ_i = ω + α·x_{i-1} + β·ψ_{i-1}`) está bem confirmado por múltiplas
fontes convergentes (ver `addendum_pesquisa_acd_garch_2026_08_17`) — essa
parte É fiel à literatura. O que muda por decisão de engenharia DESTA sessão
é a distribuição do erro:

**Weibull, não Gamma generalizada — trade-off documentado, não a única opção.**
A pesquisa de `AG-036` recomenda Gamma generalizada por precedente de
literatura (Bauwens et al. 2004, Fernandes & Grammig 2005) — melhor suporte
publicado pra cauda pesada. Optou-se por Weibull mesmo assim: Gamma
generalizada tem 3 parâmetros e MLE notoriamente instável/mal-identificado
(múltiplos ótimos locais próximos, superfície de verossimilhança achatada —
problema conhecido da família, não escolha de conveniência). Weibull é
2-parâmetros (`shape=κ`, `scale`), bem-comportado, tratável por
`scipy.optimize.minimize` (L-BFGS-B) com a mesma robustez que o resto do
módulo já exige — e ainda assim uma melhoria REAL sobre Exponencial
(descartada por `addendum_pesquisa_acd_garch_2026_08_17`: curtose teórica
da Exponencial é 6, curtose real medida em `AG-061` é 8,6–61,5 nos 5
símbolos — incompatibilidade quantitativa direta, não estética). Weibull
com `κ` livre acomoda cauda mais pesada que Exponencial (κ=1 é o caso
Exponencial, caso particular) sem a instabilidade numérica da Gamma
generalizada. Isto é uma escolha de ENGENHARIA desta sessão — `provenance`
seria `ASSUMED`, não `LITERATURE`, se fosse promovida a `constants.yaml`
(não é — ver decisão de bounds/x0 abaixo).

**O acoplamento ACD→EGARCH (`volatility_models.py::EGARCHCoupledFit` etc.)
é a peça que NÃO tem fonte literal recuperável** — Ghysels & Jasiak (1998)
acopla ACD a GARCH(1,1) LINEAR, não ao EGARCH de Nelson (1991), e a fórmula
exata do paper não foi recuperável (scan sem OCR, réplicas em paywall). Ver
docstring de `EGARCHCoupledFit` em `volatility_models.py` pro desenho
completo dessa extensão por analogia. Este módulo (`acd.py`) fornece só o
sub-modelo de duração — o que ele produz (`predict_acd`) é consumido por
`fit_egarch_coupled`/`predict_egarch_coupled`, mas não depende deles.

**Causalidade**: `ψ[j]` usa só `x[0..j-1]` (durações estritamente
anteriores) — nunca `x[j]` em diante. Ver
`test_acd_psi_recursion_nunca_usa_duracao_no_proprio_indice`
(`tests/unit/test_features_acd.py`), mesmo padrão de
`test_har_components_nunca_usa_realized_var_no_proprio_indice`.

**Decisão de `constants.yaml` (Parte 3 da spec desta sessão, documentada
explicitamente, não deixada implícita)**: bounds/x0 do otimizador L-BFGS-B
(`_ACD_OMEGA_LOWER_BOUND`, `_ACD_ALPHA_UPPER_BOUND`, `_ACD_BETA_UPPER_BOUND`,
`_ACD_KAPPA_LOWER_BOUND`, `_ACD_KAPPA_UPPER_BOUND`, `_ACD_X0_*`) permanecem
constantes Python module-level, FORA de `config/constants.yaml` — mesmo
precedente já confirmado em `fit_egarch` original (`git show
50dd621:src/features/volatility_models.py`): os bounds do EGARCH original
(`(-5.0, 5.0)`, `(-0.999, 0.999)` etc.) já eram hardcoded, nunca entraram em
`constants.yaml`, tratados como detalhe de implementação do otimizador (faixa
numérica de busca), não hiperparâmetro de política de risco/execução.
Nenhum dos bounds do ACD é conceitualmente diferente o bastante desse padrão
pra merecer entrada formal — todos são "faixa razoável pro otimizador
buscar dentro da região estacionária/bem-comportada", mesma natureza dos
bounds do EGARCH. `_ACD_MIN_TRAIN_OBS` segue o mesmo precedente de
`_MIN_TRAIN_OBS` do HAR-RV (`AG-062` Gap 3: ficou como constante Python
com comentário, não entrada YAML) — consistência deliberada, não omissão.

**Achado/decisão que diverge do texto original da spec desta sessão, sinalizado
para revisão**: a spec sugeria `_ACD_MIN_TRAIN_OBS = 30`, justificado como
"maior que o do EGARCH original porque agora há 4 parâmetros, não 4..." —
texto internamente inconsistente (30 < 50 não é "maior que", e pedia
"confirme quantos parâmetros o EGARCH original tinha antes de copiar o
número — não presuma"). Verificação real (`git show
50dd621:src/features/volatility_models.py`, `EGARCHFit`): o EGARCH original
tem exatamente 4 parâmetros livres de MLE (`omega, alpha, beta, gamma`,
`log_var_seed` é semente FIXA, não livre) — o mesmo número de parâmetros
livres que este ACD (`omega, alpha, beta, kappa`, `psi_seed` também semente
fixa). Sem base para "ACD precisa de menos dado que EGARCH" a partir de
contagem de parâmetros (a contagem é IGUAL); ao contrário, duração real sob
dollar bar tem cauda mais pesada que retorno (`AG-061`: curtose 8,6–61,5),
o que argumentaria por MAIS dado pra estimar `κ` com robustez, não menos.
Por isso `_ACD_MIN_TRAIN_OBS` foi fixado em 50 (igual ao EGARCH), não 30 —
decisão desta sessão, documentada aqui, não escondida; reveja se concordar
com a divergência do texto original."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import optimize, special

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

# Ver docstring do módulo: mesmo número de parâmetros livres que
# `_EGARCH_MIN_TRAIN_OBS` (4 vs 4) — sem base pra divergir pra baixo: fixado
# igual, não nos 30 originalmente sugeridos (rationale interno inconsistente,
# ver docstring). Débito futuro nomeado (não corrigido aqui, mesmo padrão do
# Gap 3 de `AG-062` pro `_MIN_TRAIN_OBS` do HAR-RV): sem `# noqa:
# magic-number` explícito porque é `int`, não `float` — `banned_patterns.py`
# só varre `ast.Constant` com `isinstance(value, float)`.
_ACD_MIN_TRAIN_OBS = 50

# Bounds/x0 do otimizador L-BFGS-B -- detalhe de implementação, fora de
# constants.yaml por decisão documentada no docstring do módulo. Nomes de
# parâmetro grego (alpha/beta/kappa/omega) escritos por extenso nos
# comentários (RUF003 -- ambiguidade de homoglifo -- não é ignorada em
# comentários, só em docstrings via RUF002 no pyproject.toml).
_ACD_OMEGA_LOWER_BOUND = 1e-6  # noqa: magic-number -- omega>0 estrito, mesmo estilo do teto de sanidade do EGARCH original
_ACD_ALPHA_UPPER_BOUND = 0.999  # noqa: magic-number -- alpha em [0,1), teto de estacionariedade (ver penalização abaixo)
_ACD_BETA_UPPER_BOUND = 0.999  # noqa: magic-number -- beta em [0,1), teto de estacionariedade
_ACD_KAPPA_LOWER_BOUND = 0.1  # noqa: magic-number -- forma Weibull, evita kappa->0 degenerado
_ACD_KAPPA_UPPER_BOUND = 10.0  # noqa: magic-number -- forma Weibull, teto de sanidade numérica do otimizador
_ACD_X0_ALPHA = 0.05  # noqa: magic-number -- ponto de partida neutro (baixa reação a choque de duração)
_ACD_X0_BETA = 0.9  # noqa: magic-number -- ponto de partida neutro (alta persistência), mesmo padrão do EGARCH original
_ACD_X0_KAPPA = 1.0  # kappa=1 é Exponencial, ponto de partida neutro (1.0 já é literal permitido)
_ACD_X0_OMEGA_FRACTION = 0.1  # noqa: magic-number -- omega inicial = média(x)*0.1, mesmo padrão do EGARCH original

# Estacionariedade (alpha+beta<1) não é expressável como bound linear do
# L-BFGS-B (restrição envolve 2 variáveis simultaneamente) -- imposta como
# penalização na verossimilhança negativa (mesmo mecanismo/valor de
# fallback que `_egarch_neg_log_likelihood` já usa pra "trial inválido
# durante a busca", ver `volatility_models.py`), não como `constraints=`
# do scipy (L-BFGS-B não aceita `constraints` não-linear; `SLSQP`/
# `trust-constr` aceitariam mas mudariam o otimizador do padrão já
# replicado do EGARCH original).
_ACD_NEG_LOG_LIK_PENALTY = 1e12  # noqa: magic-number -- mesmo valor de fallback do EGARCH original


def _assert_close_time_ordered(close_time: IntArray) -> None:
    """Mesma checagem de `_causal_window_mean`
    (`src/features/volatility_models.py`) — `close_time` precisa estar
    ordenado ASCENDENTE (não-decrescente); replicada aqui (não importada,
    `acd.py` é módulo novo autocontido) porque a função original é privada
    de `volatility_models.py`. `close_time[j+1] >= close_time[j]` pra todo
    `j` também garante `x[j] = close_time[j+1]-close_time[j] >= 0` — a
    checagem de duração negativa (`AG-061`: só `x[j]<0` é corrupção, `x[j]
    ==0` é dado válido de rajada real) é implicada por esta, sem precisar
    de uma segunda checagem redundante sobre `x`."""
    n = close_time.shape[0]
    if n > 1 and bool(np.any(np.diff(close_time) < 0)):
        raise ValueError(
            "close_time precisa estar ordenado ascendente (não-decrescente) -- "
            "garantido por construção em bars_15m/dollar_bars_r1, mas não pelo "
            "contrato desta função; ordene antes de chamar. x[j]==0 (close_time "
            "repetido entre barras adjacentes) é dado válido (AG-061, rajada real) "
            "-- só x[j]<0 (close_time decrescente) é corrupção."
        )


def _acd_durations(close_time: IntArray) -> FloatArray:
    """`x[j] = close_time[j+1] - close_time[j]` para `j=0..n-2` -- `n`
    barras produzem `n-1` durações consecutivas. Valida ordenação primeiro
    (`_assert_close_time_ordered`), o que já garante `x[j] >= 0`."""
    _assert_close_time_ordered(close_time)
    n = close_time.shape[0]
    if n < 2:
        return np.full(0, np.nan, dtype=np.float64)
    x: FloatArray = np.diff(close_time).astype(np.float64)
    return x


def _acd_psi_recursion(
    x: FloatArray, *, omega: float, alpha: float, beta: float, psi_seed: float
) -> FloatArray:
    """`ψ[j] = ω + α·x[j-1] + β·ψ[j-1]` para `j=1..n-2` (`n` = nº de barras,
    `x`/`ψ` têm `n-1` elementos, índices `0..n-2`), `ψ[0] = psi_seed`
    (semente FIXA -- média amostral de `x` no treino, mesma convenção de
    `log_var_seed` no EGARCH original: não é ajustada pelo otimizador,
    tratada como dado, não parâmetro livre).

    **Causalidade**: `ψ[j]` depende só de `x[0..j-1]` -- nunca de `x[j]` em
    diante. Verdadeiro por construção da recursão (cada passo só lê `x[j-1]`
    e o estado acumulado `ψ[j-1]`, nunca olha à frente); regressão coberta
    por `test_acd_psi_recursion_nunca_usa_duracao_no_proprio_indice`.

    Sequencial por natureza (não vetorizável -- `ψ[j]` depende de
    `ψ[j-1]`), mesmo estilo de loop que `_egarch_log_var_recursion` já usa
    em `volatility_models.py`. Ao contrário da recursão do EGARCH (escala
    log, pode divergir pra `-inf`/`nan` durante a busca do otimizador), esta
    recursão é estruturalmente mais estável: com `ω>0` (bound
    `_ACD_OMEGA_LOWER_BOUND`), `α,β>=0` (bounds) e `x[j]>=0` (garantido por
    `_acd_durations`), `ψ[j] >= ω > 0` sempre, por indução -- nunca fica
    não-positivo nem diverge pra `inf` sob parâmetros dentro dos bounds. O
    `if not np.isfinite(prev_psi): break` abaixo é defensivo (robustez
    contra `x` patológico fora do padrão esperado), não uma rota esperada
    em uso normal."""
    n = x.shape[0]
    psi = np.full(n, np.nan, dtype=np.float64)
    if n == 0:
        return psi
    psi[0] = psi_seed
    for j in range(1, n):
        prev_psi = psi[j - 1]
        if not np.isfinite(prev_psi):
            break
        next_psi = omega + alpha * x[j - 1] + beta * prev_psi
        psi[j] = next_psi if np.isfinite(next_psi) else np.nan
    return psi


# `close_time` tem resolução de 1ms (Binance) -- uma duração OBSERVADA
# `x==0` não é um zero físico verdadeiro entre trades (impossível: dois
# eventos não ocorrem no mesmo instante), é CENSURA DE QUANTIZAÇÃO: a
# duração real está em `[0,1)ms`, só arredondada pro mesmo carimbo de
# tempo. `_ACD_DURATION_FLOOR_MS=0.5` (ponto médio do intervalo de
# censura) substitui `x==0` pra fins de VEROSSIMILHANÇA -- achado real
# (não hipotético, ver `test_predict_acd_duracao_zero_no_meio_da_serie_
# nao_crasha_ag061`): a densidade Weibull em `x=0` é matematicamente 0
# pra `κ>1` e `+inf` pra `κ<1` (ver docstring de `_acd_weibull_log_pdf`)
# -- qualquer duração real exatamente zero (rajada de liquidez real,
# `AG-061`) torna a log-verossimilhança total não-finita fora de uma
# vizinhança minúscula de `κ=1` (o `x0` do otimizador), travando o
# L-BFGS-B sem gradiente utilizável em qualquer outro ponto -- não é
# bug de implementação, é consequência matemática real de dado censurado
# tratado como não-censurado. Aplicado SÓ na verossimilhança
# (`_acd_weibull_log_pdf`), NUNCA na recursão de `ψ` (`_acd_psi_recursion`
# usa `x` verdadeiro, `alpha*0` é aritmética linear normal, sem
# patologia -- floar ali destorceria `ψ` sem necessidade). Irrelevante
# pra qualquer duração real não-zero (mediana medida em `AG-061`:
# 7,5-9,9 MINUTOS = 450.000-594.000ms -- um piso de 0,5ms é ruído
# desprezível fora do caso de fronteira x==0).
_ACD_DURATION_FLOOR_MS = 0.5  # noqa: magic-number -- ponto médio de [0,1)ms, censura de quantização de timestamp


def _acd_weibull_log_pdf(x: FloatArray, psi: FloatArray, kappa: float) -> FloatArray:
    """`log f(x)` de `x ~ Weibull(shape=κ, scale=λ)` com `λ = ψ/Γ(1+1/κ)` --
    reparametrização de escala que garante `E[x|ψ]=ψ` por construção
    (`E[Weibull(κ,λ)] = λ·Γ(1+1/κ) = ψ`, ver docstring do módulo). Fórmula:

        log f(x) = log(κ/λ) + (κ-1)·log(x/λ) - (x/λ)^κ

    Confirmada bit-a-bit contra `scipy.stats.weibull_min.logpdf` em
    `test_acd_weibull_log_pdf_bate_scipy_weibull_min_num_caso_concreto`
    (`tests/unit/test_features_acd.py`).

    **`x==0` tratado como censura de quantização, não avaliado no limite
    matemático** (ver `_ACD_DURATION_FLOOR_MS` acima) -- acharia
    corrigido em cima do achado real de que o limite matemático exato
    (tentado numa versão anterior desta função) trava o otimizador: a
    densidade Weibull em `x=0` é genuinamente `0` (κ>1) ou `+∞`
    (κ&lt;1), e qualquer duração real exatamente zero torna a
    log-verossimilhança total não-finita fora de κ≈1, sem gradiente
    utilizável. `close_time` tem resolução de 1ms -- `x==0` observado é
    censura (duração real em `[0,1)ms`), não zero físico; substituir por
    `_ACD_DURATION_FLOOR_MS` resolve a causa raiz (dado censurado tratado
    como não-censurado), não é supressão de warning."""
    # Guarda de kappa/lam é EXTERNA a esta função, não um if/assert aqui:
    # kappa é mantido em [_ACD_KAPPA_LOWER_BOUND, _ACD_KAPPA_UPPER_BOUND]
    # (ambos >0) pelo bound do L-BFGS-B (fit_acd); psi>0 é garantido por
    # construção da recursão (_acd_psi_recursion: omega>0, alpha/beta>=0,
    # x>=0, ver docstring dela); gamma(x) de argumento positivo finito é
    # sempre positivo finito (propriedade padrão da função Gamma) -- por
    # isso lam=psi/gamma(...) e kappa/lam nunca são <=0 no caminho real.
    # `np.where(x==0, ...)`, não `np.maximum(x, floor)` -- só a censura
    # verdadeira (x EXATAMENTE 0, o carimbo de tempo colidiu) é corrigida;
    # qualquer x>0 (inclusive fracionário, usado em testes de correção
    # matemática geral contra scipy.stats.weibull_min) passa intocado, sem
    # o floor mascarar precisão que não precisa de correção nenhuma.
    x_censored = np.where(x == 0.0, _ACD_DURATION_FLOOR_MS, x)
    lam = psi / special.gamma(1.0 + 1.0 / kappa)  # noqa: unguarded-ratio -- ver comentário acima
    ratio = x_censored / lam  # noqa: unguarded-ratio -- lam>0 garantido por construção, ver comentário acima
    out: FloatArray = np.log(kappa / lam) + (kappa - 1.0) * np.log(ratio) - ratio**kappa  # noqa: unguarded-ratio -- lam>0, mesmo motivo acima
    return out


def _acd_neg_log_likelihood(params: FloatArray, x_train: FloatArray, psi_seed: float) -> float:
    omega, alpha, beta, kappa = params
    if alpha + beta >= 1.0:
        return _ACD_NEG_LOG_LIK_PENALTY
    psi = _acd_psi_recursion(x_train, omega=omega, alpha=alpha, beta=beta, psi_seed=psi_seed)
    valid = np.isfinite(psi) & np.isfinite(x_train)
    if int(np.sum(valid)) < _ACD_MIN_TRAIN_OBS:
        return _ACD_NEG_LOG_LIK_PENALTY
    log_lik = _acd_weibull_log_pdf(x_train[valid], psi[valid], kappa)
    total = -float(np.sum(log_lik))
    return total if np.isfinite(total) else _ACD_NEG_LOG_LIK_PENALTY


@dataclass(frozen=True, slots=True)
class ACDFit:
    """Coeficientes de ACD(1,1) ajustados por máxima verossimilhança
    (erro Weibull, ver docstring do módulo) sobre as durações de
    `close_time[:train_end_idx]`. `psi_seed` (média amostral das durações de
    treino) é FIXA, não ajustada por MLE junto dos outros 4 -- mesma
    convenção de `log_var_seed` em `EGARCHFit`/`EGARCHCoupledFit`."""

    omega: float
    alpha: float
    beta: float
    kappa: float
    psi_seed: float
    n_train: int


def fit_acd(close_time: IntArray, *, train_end_idx: int) -> ACDFit | None:
    """`None` se `_ACD_MIN_TRAIN_OBS` durações válidas não forem atingidas
    no treino, a semente (`psi_seed`) sair não-finita/não-positiva, ou o
    otimizador (`scipy.optimize.minimize`, L-BFGS-B) não convergir -- nunca
    devolve coeficientes de uma otimização que falhou, mesmo que `x` final
    pareça razoável (mesmo padrão de `fit_egarch`/`fit_har_rv`).

    `train_end_idx` é um índice de BARRA (mesma convenção de
    `fit_har_rv`/`fit_egarch`) -- `close_time[:train_end_idx]` produz
    `train_end_idx - 1` durações de treino."""
    train_close_time = close_time[:train_end_idx]
    if train_close_time.shape[0] < 2:
        return None
    x_train = _acd_durations(train_close_time)
    if x_train.shape[0] < _ACD_MIN_TRAIN_OBS:
        return None
    psi_seed = float(np.mean(x_train))
    if not np.isfinite(psi_seed) or psi_seed <= 0.0:
        return None

    x0 = np.array(
        [psi_seed * _ACD_X0_OMEGA_FRACTION, _ACD_X0_ALPHA, _ACD_X0_BETA, _ACD_X0_KAPPA],
        dtype=np.float64,
    )
    bounds = [
        (_ACD_OMEGA_LOWER_BOUND, None),
        (0.0, _ACD_ALPHA_UPPER_BOUND),
        (0.0, _ACD_BETA_UPPER_BOUND),
        (_ACD_KAPPA_LOWER_BOUND, _ACD_KAPPA_UPPER_BOUND),
    ]
    result = optimize.minimize(
        _acd_neg_log_likelihood,
        x0,
        args=(x_train, psi_seed),
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 200},
    )
    if not result.success or not np.all(np.isfinite(result.x)):
        return None
    omega, alpha, beta, kappa = (float(v) for v in result.x)
    return ACDFit(
        omega=omega,
        alpha=alpha,
        beta=beta,
        kappa=kappa,
        psi_seed=psi_seed,
        n_train=int(x_train.shape[0]),
    )


def predict_acd(fit: ACDFit, close_time: IntArray) -> FloatArray:
    """`ψ_i` pra toda a série, bar-indexado (mesmo comprimento de
    `close_time`, `n`) -- recursão rodada com os coeficientes ajustados
    (`fit.omega/alpha/beta`), não recomputada por fold (mesmo racional de
    `predict_egarch`: sequencial, precisa da trajetória inteira desde o
    início).

    **Convenção de índice, decisão explícita (spec permitia NaN ou o valor
    da semente em `ψ[0]` -- decisão tomada aqui, documentada)**: `ψ_i`
    (duração-indexado, `_acd_psi_recursion`) e índice de BARRA `i` coincidem
    diretamente pra `i=1..n-2` (`ψ[i]` usa `x[i-1] = close_time[i] -
    close_time[i-1]`, informação disponível exatamente no fechamento da
    barra `i` -- causalmente válido pareado com o choque `z_i` da barra `i`
    na recursão acoplada de `EGARCHCoupledFit`, ver `volatility_models.py`).
    `ψ_full[0] = NaN` -- MASCARADO mesmo `ψ[0]=psi_seed` sendo um valor
    definido: a semente é um PRIOR não-condicional (média de todas as
    durações de treino), não uma previsão causal genuína condicionada em
    história observada, diferente de `ψ[i>=1]`. Marcar como NaN distingue
    "previsão causal de verdade" de "valor de bootstrap fixo", e o
    fallback já especificado (`τ_i=1.0` quando `ψ_i` é NaN/indisponível,
    `volatility_models.py::EGARCHCoupledFit`) trata essa barra de fronteira
    de forma neutra -- reduz à recursão EGARCH original exatamente nesse
    ponto, não inventa comportamento novo. `ψ_full[n-1] = NaN` (a última
    barra não tem duração `x[n-1]` definida -- não há "próxima" barra --
    mesma convenção de cauda-NaN de `predict_egarch`/`predict_har_rv`)."""
    _assert_close_time_ordered(close_time)
    n = close_time.shape[0]
    psi_full = np.full(n, np.nan, dtype=np.float64)
    if n < 3:
        # Sem barra suficiente pra nenhuma posição "central" (i=1..n-2)
        # existir -- só semente/cauda, ambas NaN por convenção acima.
        return psi_full
    x = _acd_durations(close_time)
    psi_dur = _acd_psi_recursion(
        x, omega=fit.omega, alpha=fit.alpha, beta=fit.beta, psi_seed=fit.psi_seed
    )
    psi_full[1 : n - 1] = psi_dur[1:]
    return psi_full
