"""Triagem de gap de dado ANTES de `build_hmm.build_hmm_regimes` consumir
`lake.query_dollar_bars` -- achado F3, cluster de fixes mecânicos
2026-08-21 (auditoria M4, escopo restrito, ver task original). O baseline
(`src.regime.stress.s06_bar_gap`) já detecta gap de barra reusando
`src.data.checks.check_grid_completeness` -- mas `build_hmm_regimes`
nunca roda checagem nenhuma antes de computar `log_return_1`/
`realized_vol_short` sobre `bars_df`.

**Deliberadamente NÃO adicionado dentro de `build_hmm.py`** (fora de
escopo desta rodada: a única edição autorizada em `build_hmm_regimes` em
si é NENHUMA -- ver task). Este módulo expõe `check_bars_gap_before_hmm`
como função separada que o CALLER de `build_hmm_regimes` roda antes,
mesmo padrão de uso de `src.data.validate` rodando checks antes de um
pipeline consumir o dado.

**Decisão de design #1 -- por que não reusar `check_grid_completeness`
literalmente (documentada, exigida pela task original):**
`check_grid_completeness`/`stress.s06_bar_gap` assumem uma grade de TEMPO
FIXA (`step_ms` constante entre timestamps esperados consecutivos) --
premissa válida para barra de TEMPO (15m/30m/1h) mas que dollar-bar
estruturalmente não satisfaz: uma dollar-bar fecha quando o volume
nocional acumulado atinge o alvo (`threshold_usdt`), não em um
`close_time` prevísivel a priori (`src.data.build_dollar_bars`). Chamar
`check_grid_completeness` sobre `close_time_ms` de dollar-bar exigiria
inferir um `step_ms` médio -- que já seria, ele mesmo, uma aproximação
sujeita ao viés que esta checagem tenta detectar (regime de baixa
atividade legitimamente produz barras mais espaçadas, o que não é um
gap de DADO). Este módulo detecta gap ANÔMALO no intervalo entre
`close_time` de barras CONSECUTIVAS, relativo à distribuição empírica
de intervalos da própria série (`np.diff(close_time_ms)`) -- estatística
robusta (mediana + MAD, "modified z-score" de Iglewicz & Hoaglin 1993,
"How to Detect and Handle Outliers", *The ASQC Basic References in
Quality Control: Statistical Techniques*, vol. 16 -- threshold 3.5 é o
valor citado pelos autores como equivalente a ~3-sigma sob normalidade,
prática ESTABELECIDA de detecção de outlier univariado robusto, não um
número inventado especificamente para este módulo). MAD=0 (maioria dos
gaps positivos EXATAMENTE idêntica, cadência muito regular) usa o
fallback padrão da literatura pra esse caso -- desvio absoluto médio
como escala alternativa -- em vez de esconder o outlier atrás de uma
divisão indefinida (ver comentário inline em `check_bars_gap_before_hmm`,
achado real desta sessão).

**Decisão de design #2 -- por que a constante do modified z-score NÃO
está em `config/constants.yaml` (documentada, não escondida):** a
autorização desta rodada de fixes mecânicos restringe edição de
`constants.yaml` só à entrada específica do Fix 3 (canonical_volatility_
estimator) -- ver task original. `_MODIFIED_Z_SCORE_ANOMALY_THRESHOLD`/
`_MODIFIED_Z_SCORE_CONSTANT` ficam como constantes de MÓDULO
(`# noqa: magic-number`, mesmo padrão de `_DEFAULT_STICKY_CONCENTRATION`
em `hmm_gaussian.py`) -- se esta triagem for promovida a gate de
BLOQUEIO real (hoje é WARNING, ver abaixo), a constante deveria migrar
pra `constants.yaml` como guardrail classe C (`provenance: LITERATURE`,
citação exata acima), não ficar ASSUMED-e-escondida por conveniência de
escopo.

**Decisão de design #3 -- fail-hard vs. WARNING (decisão explícita desta
função, tomada aqui, não do chamador):** `structlog.warning`, NUNCA
bloqueia a execução -- mesmo padrão de `src.regime.stress` (nenhum
gatilho de stress impede o pipeline de rodar, só marca estado). Um gap
real merece investigação antes de confiar no HMM daquele trecho, mas
bloquear a construção INTEIRA do candidato de produção por causa de um
gap isolado em dollar-bar é desproporcional pra um sinal de TRIAGEM --
gaps largos em dollar-bar cripto de cauda (liquidez fina num fim de
semana/feriado, ex.) são plausíveis sem serem falha de coleta. O
mecanismo real de "não confie neste trecho" já existe no Regime Engine
(`tradeable=False`/sentinela -1 em `build_hmm.build_hmm_regimes` quando
um fold degenera) -- esta função só garante que o SINAL de gap não fica
em silêncio total como estava antes (achado F3), não duplica o
mecanismo de bloqueio."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]

# Mínimo de barras pra que mediana/MAD de intervalos tenham sentido
# estatístico -- com < 3 barras há no máximo 1 intervalo, sem distribuição
# nenhuma pra comparar contra (B23: "não computável" é o estado honesto,
# não "0 gaps").
_MIN_BARS_FOR_GAP_CHECK = 3

# Iglewicz & Hoaglin (1993) -- ver docstring do módulo, decisão de design
# #2. `0.6745` é a constante de consistência que faz o modified z-score
# reduzir ao z-score usual sob normalidade (MAD ~= sigma * 0.6745 pra
# distribuição normal); `3.5` é o limiar citado pelos autores.
_MODIFIED_Z_SCORE_CONSTANT = 0.6745  # noqa: magic-number -- ver docstring do módulo, Iglewicz & Hoaglin 1993
_MODIFIED_Z_SCORE_ANOMALY_THRESHOLD = 3.5  # noqa: magic-number -- ver docstring do módulo, Iglewicz & Hoaglin 1993


@dataclass(frozen=True, slots=True)
class GapCheckResult:
    """`computable=False` -- série curta demais (`n_bars <
    _MIN_BARS_FOR_GAP_CHECK`) ou sem nenhum intervalo positivo (todo
    `close_time` consecutivo não-crescente) pra estabelecer uma cadência
    típica; `median_gap_ms`/`mad_gap_ms` ficam `0.0` nesse caso -- não
    "gap zero medido", B23/mesma distinção de
    `TriggerState.NOT_COMPUTABLE` em `stress.py`.

    `n_gaps_non_monotonic` -- intervalo `<= 0` entre `close_time`
    consecutivos (timestamp duplicado ou fora de ordem): problema de
    integridade de dado À PARTE do julgamento estatístico de "anômalo",
    sinalizado incondicionalmente (não depende do modified z-score).

    `anomalous_gap_close_time_ms` -- `close_time_ms` da barra que FECHA
    um gap anômalo ou não-monotônico (a barra de "retomada"), mesma
    convenção de `stress.s06_bar_gap` (`TRIGGERED` na primeira barra
    presente depois do gap, não nas barras ausentes)."""

    n_bars: int
    computable: bool
    n_gaps_anomalous: int
    n_gaps_non_monotonic: int
    median_gap_ms: float
    mad_gap_ms: float
    max_gap_ms: float
    anomalous_gap_close_time_ms: tuple[int, ...]

    @property
    def has_anomalous_gap(self) -> bool:
        return self.n_gaps_anomalous > 0 or self.n_gaps_non_monotonic > 0


def check_bars_gap_before_hmm(bars_df: pl.DataFrame) -> GapCheckResult:
    """Triagem de gap ANTES de `build_hmm.build_hmm_regimes` consumir
    `bars_df` (mesmo `lake.query_dollar_bars(...)` que `build_hmm_regimes`
    chamaria) -- caller roda esta função primeiro, ex.:

        bars_df = lake.query_dollar_bars(symbol, start, end, resolution_id=resolution_id)
        gap_result = check_bars_gap_before_hmm(bars_df)  # loga warning se houver gap
        regimes = build_hmm.build_hmm_regimes(symbol, start, end, resolution_id=resolution_id)

    Assume `bars_df` já ordenado por `close_time` (mesma premissa que
    `build_hmm_regimes` já faz sobre `open_time` -- não reordena aqui;
    reordenar silenciosamente mascararia um bug real de ordenação em vez
    de expô-lo). Requer só a coluna `close_time` (`Int64`, epoch ms --
    schema de `src.data.schemas.DOLLAR_BARS_R1`).

    Nunca levanta exceção por gap detectado (ver docstring do módulo,
    decisão de design #3) -- só por `bars_df` sem a coluna `close_time`
    (precondição de schema, não um caso de gap)."""
    if "close_time" not in bars_df.columns:
        raise ValueError(
            "check_bars_gap_before_hmm: bars_df precisa da coluna 'close_time' "
            f"(colunas recebidas: {bars_df.columns})"
        )

    n_bars = bars_df.height
    if n_bars < _MIN_BARS_FOR_GAP_CHECK:
        return GapCheckResult(
            n_bars=n_bars,
            computable=False,
            n_gaps_anomalous=0,
            n_gaps_non_monotonic=0,
            median_gap_ms=0.0,
            mad_gap_ms=0.0,
            max_gap_ms=0.0,
            anomalous_gap_close_time_ms=(),
        )

    close_time_ms: IntArray = bars_df["close_time"].cast(pl.Int64).to_numpy()
    gaps = np.diff(close_time_ms).astype(np.float64)
    non_monotonic_mask = gaps <= 0.0
    n_non_monotonic = int(np.sum(non_monotonic_mask))

    positive_gaps = gaps[~non_monotonic_mask]
    if positive_gaps.size == 0:
        # Sem nenhum intervalo positivo -- não há cadência típica pra
        # comparar (não é "0 gaps anômalos", é não-computável, mesma
        # distinção de TriggerState.NOT_COMPUTABLE em stress.py); a
        # não-monotonicidade em si já é um achado real, sempre reportada.
        result = GapCheckResult(
            n_bars=n_bars,
            computable=False,
            n_gaps_anomalous=0,
            n_gaps_non_monotonic=n_non_monotonic,
            median_gap_ms=0.0,
            mad_gap_ms=0.0,
            max_gap_ms=float(np.max(gaps)),
            anomalous_gap_close_time_ms=tuple(
                int(t) for t in close_time_ms[1:][non_monotonic_mask]
            ),
        )
        logger.warning(
            "regime.hmm_gap_check.close_time_nao_monotonico",
            n_bars=n_bars,
            n_gaps_non_monotonic=n_non_monotonic,
        )
        return result

    median_gap = float(np.median(positive_gaps))
    abs_dev = np.abs(positive_gaps - median_gap)
    mad_gap = float(np.median(abs_dev))
    # MAD=0 é comum quando a MAIORIA dos gaps positivos é IDÊNTICA (cadência
    # muito regular, plausível em dollar-bar de liquidez estável) -- sob
    # MAD=0 literal, o modified z-score de QUALQUER desvio não-nulo tende a
    # infinito, o que é matematicamente correto (variância estruturalmente
    # zero -> qualquer desvio é um outlier), mas ingênuo demais pra
    # implementar direto (achado real desta sessão, ver
    # test_regime_hmm_gap_check.py::
    # test_gap_anomalo_detectado_com_cadencia_quase_toda_identica -- a
    # primeira versão desta função tratava MAD=0 como "nenhum gap anômalo
    # possível", o que ESCONDIA justamente o outlier que a checagem existe
    # pra pegar). Fallback padrão da literatura de detecção de outlier
    # robusto pra MAD=0: usa o desvio absoluto MÉDIO como escala
    # alternativa (menos robusto que MAD a múltiplos outliers, mas MAD já
    # não é uma opção neste caso).
    scale = mad_gap if mad_gap > 0.0 else float(np.mean(abs_dev))

    if scale > 0.0:
        modified_z = (
            _MODIFIED_Z_SCORE_CONSTANT * (gaps - median_gap) / scale
        )  # denominador guardado por `scale > 0.0` acima -- ver check_unguarded_ratios.py
        anomalous_mask = (~non_monotonic_mask) & (modified_z > _MODIFIED_Z_SCORE_ANOMALY_THRESHOLD)
    else:
        # scale==0 só ocorre se TODO gap positivo for EXATAMENTE idêntico
        # (cadência perfeitamente regular, sem outlier nenhum pra achar) --
        # qualquer gap que ainda assim divergisse do valor típico seria
        # anômalo por definição (desvio não-nulo sobre variância
        # estruturalmente zero), sem precisar de z-score pra essa
        # conclusão; não há divisão neste ramo.
        anomalous_mask = (~non_monotonic_mask) & (gaps != median_gap)

    n_anomalous = int(np.sum(anomalous_mask))
    combined_mask = anomalous_mask | non_monotonic_mask
    anomalous_close_time = tuple(int(t) for t in close_time_ms[1:][combined_mask])

    result = GapCheckResult(
        n_bars=n_bars,
        computable=True,
        n_gaps_anomalous=n_anomalous,
        n_gaps_non_monotonic=n_non_monotonic,
        median_gap_ms=median_gap,
        mad_gap_ms=mad_gap,
        max_gap_ms=float(np.max(gaps)),
        anomalous_gap_close_time_ms=anomalous_close_time,
    )

    if result.has_anomalous_gap:
        logger.warning(
            "regime.hmm_gap_check.bars_gap_detected",
            n_bars=n_bars,
            n_gaps_anomalous=n_anomalous,
            n_gaps_non_monotonic=n_non_monotonic,
            median_gap_ms=median_gap,
            mad_gap_ms=mad_gap,
            max_gap_ms=result.max_gap_ms,
        )
    return result


__all__ = ["GapCheckResult", "check_bars_gap_before_hmm"]
