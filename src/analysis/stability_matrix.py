"""ADR-008 Fase 5+7 — stability matrix: cruza Fold × {IC, AUC/LogLoss,
feature gain, decile returns, SHAP} sobre o artefato de walk-forward
real (`src.models.walk_forward.run_walk_forward_for_combo`, Fase 4,
`experiments/alpha_walk_forward_{symbol}_{resolution_id}.json`) — os 5
eixos já existem no artefato desde a Fase 5 parte 1 + Fase 7
(`WalkForwardFoldMetrics.score_quality_by_side`/`decile_profile_by_side`/
`gain_by_column_by_side`/`shap_mean_abs_by_side`), este módulo só CRUZA.

**Por que vive em `src.analysis`, não `src.models`** — é auditoria
exploratória pós-hoc sobre um artefato já escrito, não um insumo de
treino/produção; mesma fronteira que `attribution.py`/`calibration_
diagnostics.py` já ocupam (o import-linter do projeto só proíbe o
sentido contrário, `src.models` importar `src.analysis`).

Núcleo puro (Idioma A) — recebe o payload já carregado (`json.load` do
artefato), IO fica a cargo do chamador.

**Mede ESTABILIDADE, não só tabula.** Três perguntas que a matriz existe
pra responder: (1) quão dispersa é cada métrica ENTRE folds
(`dispersion_by_metric_and_side` — mean/median/std/min/max, `NaN`
descartado antes de agregar, mesma convenção de `backtest_lite.
path_dispersion_stats`/`score_quality._ic_dispersion_stats`); (2) a
MESMA feature domina o gain (`top_feature_frequency_by_side`) e o SHAP
(`top_shap_feature_frequency_by_side`) em todo fold, ou o ranking muda
fold a fold; (3) **gain nativo (conta uso em split) e SHAP (contribuição
real à predição) CONCORDAM sobre qual feature domina, ou divergem**
(`gain_shap_agreement_rate_by_side` — fração dos folds/linhas em que os
dois apontam a MESMA feature #1; divergência sistemática é sinal de que
o gain nativo sozinho engana sobre o que o modelo realmente usa pra
prever, não só pra crescer árvore). Um IC/AUC médio "bom" com dispersão
alta entre folds é um resultado instável, não confiável — exatamente a
leitura que médias sozinhas escondem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

_METRICS: tuple[str, ...] = ("ic_spearman_pooled", "roc_auc", "log_loss", "q10_minus_q1_bps")
_SIDES: tuple[str, ...] = ("long", "short")
_MIN_FOLDS_FOR_STD = 2  # noqa: magic-number -- desvio-padrão amostral (ddof=1) exige >=2 pontos


@dataclass(frozen=True, slots=True)
class StabilityRow:
    fold_id: int
    side: str
    n_trades: int
    ic_spearman_pooled: float
    roc_auc: float
    log_loss: float
    q10_minus_q1_bps: float
    # `None` se o lado treinou mas gain bruto/|SHAP| total foi 0 (booster
    # nunca dividiu em nenhuma feature) -- nunca inventa um "top" sem
    # base real, nos dois eixos.
    top_feature_by_gain: str | None
    top_feature_gain_share: float
    top_feature_by_shap: str | None
    top_feature_shap_share: float


@dataclass(frozen=True, slots=True)
class StabilityMatrixResult:
    symbol: str
    resolution_id: str
    variant: str
    n_folds_total: int
    n_folds_usados: int
    # 1 linha por (fold NÃO-degenerado, lado que treinou) -- lado sem
    # nenhum trade OOF nesse fold ainda aparece (gain/SHAP existem,
    # métricas de trade ficam `NaN`, não ausente): treinar não exige ter
    # sinalizado, e a ausência de sinal é ela mesma informação.
    rows: tuple[StabilityRow, ...]
    dispersion_by_metric_and_side: dict[str, dict[str, dict[str, float]]]
    top_feature_frequency_by_side: dict[str, dict[str, float]]
    top_shap_feature_frequency_by_side: dict[str, dict[str, float]]
    # fração das linhas (fold x lado, ambos os tops definidos) em que
    # `top_feature_by_gain == top_feature_by_shap` -- `NaN` se nenhuma
    # linha do lado tem os dois tops definidos.
    gain_shap_agreement_rate_by_side: dict[str, float]


def _dispersion(values: list[float]) -> dict[str, float]:
    """mean/median/std/min/max sobre `values`, `NaN` descartado antes de
    agregar — mesma convenção de `backtest_lite.path_dispersion_stats`/
    `walk_forward._aggregate_stats` (duplicada aqui, não importada de um
    módulo privado de `src.models` — mesmo princípio de `score_quality.
    _spearman_ic`: ~10 linhas repetidas é mais barato que acoplar a um
    símbolo `_` de outra camada só por isso)."""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.shape[0] == 0:
        nan = float("nan")
        return {"n": 0.0, "mean": nan, "median": nan, "std": nan, "min": nan, "max": nan}
    std = (
        float(finite.std(ddof=1)) if finite.shape[0] >= _MIN_FOLDS_FOR_STD else float("nan")
    )
    return {
        "n": float(finite.shape[0]),
        "mean": float(finite.mean()),
        "median": float(np.median(finite)),
        "std": std,
        "min": float(finite.min()),
        "max": float(finite.max()),
    }


def _float_or_nan(value: float | None) -> float:
    """`None` (JSON `null` — `orjson.dumps` serializa `NaN`/`Infinity`
    como `null` automaticamente, `json.load` devolve `None`, ver
    `src.io.artifact`) normalizado pra `float("nan")` explícito —
    correção 2026-08-31 (achado real de `audit_engineering`, confirmado
    contra artefato real: `experiments/alpha_walk_forward_BTCUSDT_R2.
    json`, `camada0` fold_id=6, `score_quality_by_side.long.roc_auc`
    grava `null`). Sem isso, `None` vazava pra um campo tipado `float`
    de `StabilityRow`, violando o contrato de tipo silenciosamente —
    mascarado hoje só pela coerção implícita `None->NaN` que `np.
    asarray(..., dtype=np.float64)` faz dentro de `_dispersion`, mas
    quebra qualquer consumo direto de `.rows` (ex. `min(rows, key=
    lambda r: r.roc_auc)` levanta `TypeError`, `'<' not supported
    between 'NoneType' and 'float'`)."""
    return float("nan") if value is None else value


def _top_feature(importance: dict[str, float]) -> tuple[str | None, float]:
    """`(feature, share)` — a feature de MAIOR importância (gain bruto
    OU `|SHAP|` médio, mesma fórmula pros dois eixos) e sua fração do
    total do lado nesse fold. `(None, NaN)` se `importance` vazio ou
    soma zero (booster nunca dividiu em nenhuma feature/`|SHAP|` todo
    zero) — nunca inventa um "top" sem base real."""
    if not importance:
        return None, float("nan")
    total = sum(importance.values())
    if total <= 0.0:
        return None, float("nan")
    top_feature = max(importance, key=lambda f: importance[f])
    return top_feature, importance[top_feature] / total


def _top_feature_frequency(
    rows: list[StabilityRow], side: str, *, top_attr: str
) -> dict[str, float]:
    """Fração dos folds (deste `side`) em que cada feature foi #1 por
    `top_attr` (`"top_feature_by_gain"` ou `"top_feature_by_shap"`) —
    ordenado decrescente. Dict vazio se nenhum fold deste lado teve um
    top-feature definido nesse eixo."""
    side_rows = [r for r in rows if r.side == side and getattr(r, top_attr) is not None]
    if not side_rows:
        return {}
    counts: dict[str, int] = {}
    for r in side_rows:
        feature = getattr(r, top_attr)
        assert feature is not None  # já filtrado acima -- só pra mypy
        counts[feature] = counts.get(feature, 0) + 1
    n = len(side_rows)
    return dict(sorted(((f, c / n) for f, c in counts.items()), key=lambda kv: -kv[1]))  # noqa: unguarded-ratio -- n=len(side_rows)>=1 ja garantido pelo early-return acima nesta funcao


def _gain_shap_agreement_rate(rows: list[StabilityRow], side: str) -> float:
    """Fração das linhas (deste `side`, com os DOIS tops definidos) em
    que `top_feature_by_gain == top_feature_by_shap`. `NaN` se nenhuma
    linha do lado tem os dois tops definidos simultaneamente."""
    side_rows = [
        r
        for r in rows
        if r.side == side
        and r.top_feature_by_gain is not None
        and r.top_feature_by_shap is not None
    ]
    if not side_rows:
        return float("nan")
    n_agree = sum(1 for r in side_rows if r.top_feature_by_gain == r.top_feature_by_shap)
    return n_agree / len(side_rows)  # noqa: unguarded-ratio -- len(side_rows)>=1 ja garantido pelo early-return acima nesta funcao


def build_stability_matrix(
    payload: dict[str, Any], *, symbol: str, resolution_id: str, variant: str
) -> StabilityMatrixResult:
    """`payload` — `json.load` de UM `variant` (`"camada1"`/`"camada0"`)
    dentro de `experiments/alpha_walk_forward_{symbol}_{resolution_id}.
    json` (o dict com `fold_results`/`aggregate`/`n_folds_total`/
    `n_folds_usados`, mesmo schema de `dataclasses.asdict(WalkForward
    Result)`). Folds `degenerado=True` (ADR-008 Fase 4) ficam FORA das
    linhas — mesmo critério que já exclui do agregado de sharpe/edge_
    bps/win_rate, por consistência (poucos trades também torna IC/AUC/
    decile/gain sobre esse fold não confiáveis)."""
    fold_results = payload["fold_results"]
    rows: list[StabilityRow] = []
    for fr in fold_results:
        if fr["degenerado"]:
            continue
        for side in _SIDES:
            gain = fr["gain_by_column_by_side"].get(side)
            if gain is None:
                continue
            shap_importance = fr.get("shap_mean_abs_by_side", {}).get(side)
            sq = fr["score_quality_by_side"].get(side)
            decile = fr["decile_profile_by_side"].get(side)
            top_feature_gain, top_share_gain = _top_feature(gain)
            top_feature_shap, top_share_shap = (
                _top_feature(shap_importance)
                if shap_importance is not None
                else (None, float("nan"))
            )
            rows.append(
                StabilityRow(
                    fold_id=fr["fold_id"],
                    side=side,
                    n_trades=sq["n_trades"] if sq else 0,
                    ic_spearman_pooled=(
                        _float_or_nan(sq["spearman_ic_pooled"]) if sq else float("nan")
                    ),
                    roc_auc=_float_or_nan(sq["roc_auc"]) if sq else float("nan"),
                    log_loss=_float_or_nan(sq["log_loss"]) if sq else float("nan"),
                    q10_minus_q1_bps=(
                        _float_or_nan(decile["q10_minus_q1_bps"]) if decile else float("nan")
                    ),
                    top_feature_by_gain=top_feature_gain,
                    top_feature_gain_share=top_share_gain,
                    top_feature_by_shap=top_feature_shap,
                    top_feature_shap_share=top_share_shap,
                )
            )

    dispersion_by_metric_and_side = {
        side: {
            metric: _dispersion([getattr(r, metric) for r in rows if r.side == side])
            for metric in _METRICS
        }
        for side in _SIDES
    }
    top_feature_frequency_by_side = {
        side: _top_feature_frequency(rows, side, top_attr="top_feature_by_gain") for side in _SIDES
    }
    top_shap_feature_frequency_by_side = {
        side: _top_feature_frequency(rows, side, top_attr="top_feature_by_shap") for side in _SIDES
    }
    gain_shap_agreement_rate_by_side = {
        side: _gain_shap_agreement_rate(rows, side) for side in _SIDES
    }

    return StabilityMatrixResult(
        symbol=symbol,
        resolution_id=resolution_id,
        variant=variant,
        n_folds_total=payload["n_folds_total"],
        n_folds_usados=payload["n_folds_usados"],
        rows=tuple(rows),
        dispersion_by_metric_and_side=dispersion_by_metric_and_side,
        top_feature_frequency_by_side=top_feature_frequency_by_side,
        top_shap_feature_frequency_by_side=top_shap_feature_frequency_by_side,
        gain_shap_agreement_rate_by_side=gain_shap_agreement_rate_by_side,
    )
