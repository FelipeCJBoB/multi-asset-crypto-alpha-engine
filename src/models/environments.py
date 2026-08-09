"""Ambientes da Camada 1 (§5.4) — tercil de `E27f_cost_atr_ratio` x regime
estrutural, seis células, calculado SOMENTE sobre as linhas que o chamador
passar (o treino de um fold do CPCV — nunca o dataset inteiro, B02/B06).

**RANGE = R1 ∪ R2, TREND = R3 ∪ R4; R0/R5 excluídos** (literal da task,
§5.4 "seis células"): R0 é warmup (nunca sobra depois do filtro de
`min_warmup_bars` em `src.models.dataset.side_subset`) e R5 é STRESS —
nenhum dos dois expressa "tercil de custo x regime estrutural [tendência
vs faixa]" de forma coerente, então linhas nesses dois regimes recebem
`env = null` e ficam de fora da triagem de estabilidade (não do TREINO do
XGBoost em si — ver docstring de `src.models.dataset.side_subset`).

**"Tercil" aqui é um corte estático sobre a distribuição do PRÓPRIO
subconjunto de treino recebido**, não um quantil expansivo em tempo
corrido (`support.expanding_percentile_rank_strict`, usado por
`src.regime.classifier` para o eixo econômico `econ_regime`). Os dois são
ambientes propositalmente DIFERENTES: `econ_regime` é uma classificação
CAUSAL, ponto-a-ponto, usando só passado, porque alimenta decisão ao vivo;
os ambientes desta Camada 1 são um particionamento IN-FOLD de um conjunto
de treino já fechado (§5.9 passo 1, "só treino"), usado apenas para medir
consistência de sinal — o corte estático sobre a distribuição do próprio
fold é a leitura mais direta de "tercil... calculado só sobre o treino
daquele fold" (texto da task) e evita reintroduzir uma dependência de
ordem cronológica onde os grupos do CPCV não são um prefixo contínuo de
tempo (diferente de walk-forward)."""

from __future__ import annotations

import polars as pl

RANGE_REGIMES: frozenset[str] = frozenset({"R1", "R2"})
TREND_REGIMES: frozenset[str] = frozenset({"R3", "R4"})

_TERCILE_LOW = 1 / 3
_TERCILE_HIGH = 2 / 3

ENVIRONMENTS: tuple[str, ...] = (
    "RANGE_LOW_COST",
    "RANGE_MID_COST",
    "RANGE_HIGH_COST",
    "TREND_LOW_COST",
    "TREND_MID_COST",
    "TREND_HIGH_COST",
)

ENV_COL = "env"


def _structural_group(regime_col: pl.Expr) -> pl.Expr:
    return (
        pl.when(regime_col.is_in(list(RANGE_REGIMES)))
        .then(pl.lit("RANGE"))
        .when(regime_col.is_in(list(TREND_REGIMES)))
        .then(pl.lit("TREND"))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
    )


def assign_environments(
    df: pl.DataFrame, *, cost_col: str = "E27f_cost_atr_ratio", regime_col: str = "regime"
) -> pl.DataFrame:
    """Adiciona a coluna `env` (Utf8, um dos 6 valores de `ENVIRONMENTS` ou
    `null`) a `df`. Os cortes de tercil são calculados sobre `df[cost_col]`
    EXATAMENTE como recebido — cabe ao chamador garantir que `df` já é o
    treino do fold (nunca o dataset inteiro nem o teste)."""
    if df.is_empty():
        return df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(ENV_COL))

    valid_cost = df[cost_col].drop_nulls()
    if valid_cost.len() < 3:  # noqa: magic-number — mínimo trivial p/ 3 cortes existirem
        return df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(ENV_COL))

    q_low = float(valid_cost.quantile(_TERCILE_LOW, interpolation="linear"))  # type: ignore[arg-type]
    q_high = float(valid_cost.quantile(_TERCILE_HIGH, interpolation="linear"))  # type: ignore[arg-type]

    cost_bucket = (
        pl.when(pl.col(cost_col).is_null())
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(pl.col(cost_col) <= q_low)
        .then(pl.lit("LOW_COST"))
        .when(pl.col(cost_col) <= q_high)
        .then(pl.lit("MID_COST"))
        .otherwise(pl.lit("HIGH_COST"))
    )
    structural = _structural_group(pl.col(regime_col))

    env_expr = (
        pl.when(structural.is_null() | cost_bucket.is_null())
        .then(pl.lit(None, dtype=pl.Utf8))
        .otherwise(structural + pl.lit("_") + cost_bucket)
        .alias(ENV_COL)
    )
    return df.with_columns(env_expr)
