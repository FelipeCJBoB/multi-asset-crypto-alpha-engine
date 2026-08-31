"""ADR-008 Fase 2 — auditoria de distribuição do label/target
(`labels.parquet`, bloco 11 do consultor). Núcleo puro (Idioma A), sem
IO — recebe o frame já carregado.

**`label` é TERNÁRIO no artefato bruto** (`src.labels.triple_barrier.
_LABEL_BY_BARRIER`: `TP=1, TIME=0, SL=-1`), não o alvo binário de
treino — o alvo real que `alpha.fit_side_model` usa é
`y = (label == 1)` (TP vs. {TIME, SL}), ver `alpha.py::y_all =
(train_side_df["label"].cast(pl.Int64) == 1)`. Este módulo reporta os
DOIS: a distribuição ternária bruta (`frac_tp`/`frac_time`/`frac_sl`) E
a binarização real de treino (`n_positive`/`n_negative`/`frac_positive`)
— reportar só o binário esconderia se o "negativo" é dominado por SL ou
por TIME, informação diferente sobre o que o modelo está de fato
aprendendo a separar.

**O que este módulo NÃO reimplementa**: `P(label | prediction bucket)`
já existe em `calibration_diagnostics.decile_profile`
(`rate_tp`/`rate_sl`/`rate_time`/`rate_nofill` por decil). Overlap
ESTRUTURAL de label (mesmo `[t0,t1]` vazando treino→teste) já é
auditado e BLOQUEADO por `cpcv.assert_no_train_t1_leaks_into_test`
(`src.validation.leakage`, teste 6). `label_autocorr_lag1` aqui é uma
estatística DESCRITIVA complementar — o quanto rótulos CONSECUTIVOS
(ordenados por `t0`) tendem a concordar, esperado ser alto sob barreira
triple com janelas sobrepostas (`t1` de uma barra cai dentro de `[t0,t1]`
de outra) — não é um mecanismo de proteção, é o número que o consultor
pediu para aparecer explícito no relatório."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
from scipy.stats import kurtosis, skew

_MIN_OBS_FOR_MOMENT = 2  # noqa: magic-number -- desvio-padrão/skew/kurtose amostrais exigem >=2 pontos
_MIN_OBS_FOR_AUTOCORR = 3  # noqa: magic-number -- lag-1 precisa de >=2 pares defasados (>=3 pontos totais)
_SIDES: tuple[int, ...] = (1, -1)


@dataclass(frozen=True, slots=True)
class LabelDistributionStats:
    side: int
    n_total: int
    n_tp: int
    n_time: int
    n_sl: int
    frac_tp: float
    frac_time: float
    frac_sl: float
    #: alvo BINÁRIO real de treino -- `label == 1` (TP), ver docstring do módulo.
    n_positive: int
    n_negative: int
    frac_positive: float
    ret_net_mean: float
    ret_net_std: float
    ret_net_skew: float
    ret_net_kurtosis: float
    ret_net_p01: float
    ret_net_p05: float
    ret_net_p50: float
    ret_net_p95: float
    ret_net_p99: float
    #: autocorrelação lag-1 do alvo binário, ordenado por `t0` -- descritivo
    #: (overlap de janela ESPERADO sob triple barrier), não um gate.
    label_autocorr_lag1: float


def compute_label_distribution_stats(labels: pl.DataFrame) -> tuple[LabelDistributionStats, ...]:
    """`labels` — `labels.parquet` já carregado (precisa de `t0`, `side`,
    `label`, `ret_net`). Um `LabelDistributionStats` por lado presente no
    frame (`side in {1, -1}`); lado ausente não aparece na saída."""
    required = ("t0", "side", "label", "ret_net")
    ausentes = tuple(c for c in required if c not in labels.columns)
    if ausentes:
        raise ValueError(
            f"compute_label_distribution_stats: labels sem {ausentes} -- "
            f"colunas disponíveis: {sorted(labels.columns)}"
        )

    results: list[LabelDistributionStats] = []
    for side_value in _SIDES:
        sub = labels.filter(pl.col("side") == side_value).sort("t0")
        n_total = sub.height
        if n_total == 0:
            continue

        label_arr = sub["label"].to_numpy().astype(np.int64)
        ret_net = sub["ret_net"].drop_nulls().to_numpy().astype(np.float64)

        n_tp = int((label_arr == 1).sum())
        n_time = int((label_arr == 0).sum())
        n_sl = int((label_arr == -1).sum())
        n_positive = n_tp
        n_negative = n_total - n_tp

        if ret_net.shape[0] >= _MIN_OBS_FOR_MOMENT:
            ret_mean = float(ret_net.mean())
            ret_std = float(ret_net.std(ddof=1))
            ret_skew = float(skew(ret_net))
            ret_kurt = float(kurtosis(ret_net))
            ret_p01 = float(np.quantile(ret_net, 0.01))  # noqa: magic-number -- percentil padrao
            ret_p05 = float(np.quantile(ret_net, 0.05))  # noqa: magic-number -- percentil padrao
            ret_p50 = float(np.quantile(ret_net, 0.50))  # noqa: magic-number -- mediana
            ret_p95 = float(np.quantile(ret_net, 0.95))  # noqa: magic-number -- percentil padrao
            ret_p99 = float(np.quantile(ret_net, 0.99))  # noqa: magic-number -- percentil padrao
        else:
            nan = float("nan")
            ret_mean = ret_std = ret_skew = ret_kurt = nan
            ret_p01 = ret_p05 = ret_p50 = ret_p95 = ret_p99 = nan

        binary = (label_arr == 1).astype(np.float64)
        # exige >=2 PARES defasados (`binary[:-1]`/`binary[1:]`, cada um
        # com >=2 elementos -- ddof=1 indefinido com 1), não só n_total
        # >=2: `corrcoef` sobre 2 arrays de tamanho 1 warna
        # "degrees of freedom <= 0"/divide-by-zero silenciosamente. Achado
        # real ao rodar os testes desta função com `n_total=2` por lado.
        lag0, lag1 = binary[:-1], binary[1:]
        if binary.shape[0] >= _MIN_OBS_FOR_AUTOCORR and lag0.std() > 0.0 and lag1.std() > 0.0:
            autocorr = float(np.corrcoef(lag0, lag1)[0, 1])
        else:
            autocorr = float("nan")

        results.append(
            LabelDistributionStats(
                side=side_value,
                n_total=n_total,
                n_tp=n_tp,
                n_time=n_time,
                n_sl=n_sl,
                frac_tp=n_tp / n_total,
                frac_time=n_time / n_total,
                frac_sl=n_sl / n_total,
                n_positive=n_positive,
                n_negative=n_negative,
                frac_positive=n_positive / n_total,
                ret_net_mean=ret_mean,
                ret_net_std=ret_std,
                ret_net_skew=ret_skew,
                ret_net_kurtosis=ret_kurt,
                ret_net_p01=ret_p01,
                ret_net_p05=ret_p05,
                ret_net_p50=ret_p50,
                ret_net_p95=ret_p95,
                ret_net_p99=ret_p99,
                label_autocorr_lag1=autocorr,
            )
        )
    return tuple(results)
