"""Atribuição de importância de feature — IC de Spearman por regime
(`ic_by_regime`) e gain do XGBoost por lado (`gain_by_side`), uma métrica
de concordância entre os dois rankings (`feature_agreement`), e monotonia
de retorno por decil de confiança calibrada (`confidence_deciles_by_side`).

**PÓS-HOC, EXPLICATIVO, NUNCA INSUMO DE TREINO OU SELEÇÃO DE FEATURE.**
Este módulo lê resultado REALIZADO (`ret_net`, `barrier_hit` — o que
aconteceu DEPOIS da decisão de trade) e diagnóstico já persistido em disco
(`gain_by_column`/`concentration_shares` por fold×lado). Se qualquer saída
daqui um dia alimentar seleção de feature, treino, ou tuning de
hiperparâmetro, é vazamento temporal — mesma classe de erro do banned
pattern B06 do CLAUDE.md ("tabela de IC de 7 anos usada para configurar
modelo"). Isso é estrutural, não só documentado: `pyproject.toml
[tool.importlinter]` tem dois contratos (`"models não importa analysis"`,
`"features não importa analysis"`) que quebram o build de qualquer código
de `src.models`/`src.features` que importe `src.analysis` — rode
`uv run lint-imports` para verificar.

**Contraste explícito com `src.models.monotonic`.** Aquele módulo TAMBÉM
calcula IC de Spearman contra `ret_net`, mas roda IN-FOLD (só sobre o
treino de um fold do CPCV, nunca o OOF) e É insumo de treino direto — vira
`monotone_constraints` do XGBoost (§5.3). Este módulo aqui é o oposto em
todo eixo relevante: roda SOBRE o OOF (`is_oof=True`), mistura dado de
TODOS os folds/regimes de uma vez, e o resultado nunca volta a alimentar
nenhum modelo. Os dois casos de uso são deliberadamente separados e NÃO
compartilham código — nenhuma função deste módulo importa
`src.models.monotonic` nem vice-versa, mesmo onde a lógica de correlação
se pareceria (mesmo raciocínio do parágrafo acima: compartilhar código
entre os dois criaria um caminho de acoplamento que o import-linter não
consegue bloquear, porque a violação estaria dentro de `src.models`, não
na fronteira entre pacotes).

**Fonte dos três achados que motivaram este módulo:** uma investigação ad
hoc (script depois deletado) juntou `predictions/alpha/{model_id}/
predictions.parquet` (OOF) com `labels/v1/labels.parquet` (`ret_net`,
`barrier_hit`) e uma coluna de regime, e mediu IC de Spearman por feature
T1 fatiado por regime R0-R5 — achado real: `E02f_funding_z_expanding`
muda de sinal entre regimes de faixa e de tendência. `ic_by_regime`
reproduz esse cálculo de forma testável. `gain_by_side` agrega o
`gain_by_column`/`concentration_shares` já persistido por
`src.models.pipeline.write_fold_diagnostics_atomic` (Fase A) — dado real
em disco, nenhum retreino. `feature_agreement` quantifica o quanto os dois
rankings (gain vs IC) concordam.

**`confidence_deciles_by_side` responde uma pergunta diferente das três
acima.** Não é "a feature carrega informação" (`ic_by_regime`) nem "o
booster usou a feature" (`gain_by_side`) — é "a PROBABILIDADE CALIBRADA
final do Alpha (`p_long`/`p_short`/`confidence`) ordena os trades por
retorno realizado, separado por lado". Isto testa monotonia da calibração,
não o sinal médio (que já é medido em outro lugar, ex.
`src.backtest.fill_reconciliation`): um Alpha com sinal médio positivo mas
SEM monotonia por confiança não teria o que uma Camada 2+ (Meta Model,
§6.8, hoje fora da V1) pudesse explorar — a informação de ranking já
estaria saturada na Camada 1. Reusa o MESMO padrão de junção de
`ic_by_regime` (`is_oof=True`, `side_hat` do lado em questão, join com
`labels` por `(t0, side)`, descarta `barrier_hit == "NOFILL"`), mas não
compartilha código com ela (nova junção dedicada por lado, ver
`_deciles_for_side`) — mesmo raciocínio dos parágrafos acima sobre não
amarrar lógica de análise a um único caminho de código."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy.stats import spearmanr

from src.core.metric import Metric, Unit, not_computable

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

# Mínimo de observações válidas (não-NaN, variância > 0 nos dois lados) para
# um Spearman ter sentido — abaixo disso o resultado é `Metric(valid=False)`.
# Mesmo valor/mesma categoria de `src.models.monotonic._MIN_OBS_PER_ENV`
# (mínimo matemático, não constante de domínio — `spearmanr` degenera com
# < 3 pontos; ver docstring de `monotonic.py`), duplicado aqui em vez de
# importado — ver docstring do módulo, "não compartilham código".
_MIN_OBS_SPEARMAN = 5  # noqa: magic-number

_REGIME_COL = "regime"
_T0_COL = "t0"
_RET_NET_COL = "ret_net"
_BARRIER_HIT_COL = "barrier_hit"
_NOFILL = "NOFILL"
_N_SEMANTICS_TRADES = "trades"
_N_SEMANTICS_FEATURES = "features"

_CONFIDENCE_COL = "confidence"
# `side_hat`/`side` (`Int8`, {-1, 0, 1}) -> rótulo de lado usado na saída de
# `confidence_deciles_by_side` — mesma convenção de `gain_by_side`
# (`side_label` "long"/"short"), não o inteiro cru do schema de
# `predictions.parquet`/`labels.parquet`.
_SIDE_LABEL_BY_HAT: dict[int, str] = {1: "long", -1: "short"}
_N_DECILES_DEFAULT = 10
# `ret_net` (fração) -> bps. Mesma conversão de
# `src.backtest.fill_reconciliation._mean_bps` (`* 10_000`), duplicada aqui
# por design: `src.analysis` e `src.backtest` são pacotes irmãos sem
# contrato de import entre si (nenhum contrato de `[tool.importlinter]`
# amarra os dois), então importar de lá criaria um acoplamento que o
# import-linter não verifica — mesmo raciocínio de não-compartilhamento de
# código descrito na docstring do módulo. `10_000` é definição de unidade
# (1 bps = 1/10000), não constante de domínio — não é `float`, não cai na
# Regra 1 do lint de proveniência (`tools/lint/banned_patterns.py` só marca
# literais `float`).
_BPS_PER_UNIT = 10_000

# Convenção de dtype de `t0` em `predictions.parquet`/`labels/v1/labels.parquet`
# (ver schemas reais, `src.models.alpha.PREDICTIONS_SCHEMA_COLUMNS`/
# `src.labels.triple_barrier.LABEL_COLUMNS`) — usado para normalizar a coluna
# `t0` de `regimes` antes do join, porque essa terceira tabela pode vir de
# `src.regime.build.build_regimes()` diretamente, cujo `t0` é
# `Datetime(time_unit="ns", ...)` (ver `src.regime.classifier.classify_regimes`,
# `.dt.cast_time_unit("ns")`) — sem essa normalização o join silenciosamente
# não bateria nenhuma linha em vez de levantar um erro claro.
_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")

_IC_OUTPUT_SCHEMA: pl.Schema = pl.Schema(
    {
        "feature": pl.Utf8,
        "regime": pl.Utf8,
        "ic_value": pl.Float64,
        "ic_unit": pl.Utf8,
        "ic_n": pl.Int64,
        "ic_n_semantics": pl.Utf8,
        "ic_source": pl.Utf8,
        "ic_valid": pl.Boolean,
        "ic_invalid_reason": pl.Utf8,
    }
)

_GAIN_OUTPUT_SCHEMA: pl.Schema = pl.Schema(
    {
        "feature": pl.Utf8,
        "side": pl.Utf8,
        "model_id": pl.Utf8,
        "gain_mean": pl.Float64,
        "gain_std": pl.Float64,
        "share_mean": pl.Float64,
        "share_std": pl.Float64,
        "n_folds": pl.Int64,
    }
)

_DECILE_OUTPUT_SCHEMA: pl.Schema = pl.Schema(
    {
        "side": pl.Utf8,
        "decile": pl.Int64,
        "n": pl.Int64,
        "confidence_min": pl.Float64,
        "confidence_max": pl.Float64,
        "mean_ret_net_bps_value": pl.Float64,
        "mean_ret_net_bps_unit": pl.Utf8,
        "mean_ret_net_bps_n": pl.Int64,
        "mean_ret_net_bps_n_semantics": pl.Utf8,
        "mean_ret_net_bps_source": pl.Utf8,
        "mean_ret_net_bps_valid": pl.Boolean,
        "mean_ret_net_bps_invalid_reason": pl.Utf8,
        "std_ret_net_bps": pl.Float64,
        "t_stat": pl.Float64,
    }
)


def _require_columns(df: pl.DataFrame, required: tuple[str, ...], *, df_name: str) -> None:
    missing = sorted(set(required) - set(df.columns))
    if missing:
        raise ValueError(f"{df_name}: coluna(s) obrigatória(s) ausente(s): {missing}")


def _infer_predictions_source(predictions: pl.DataFrame) -> str:
    """`Metric.source` derivado da própria coluna `model_id` de
    `predictions` — nenhum parâmetro extra na assinatura de `ic_by_regime`
    (o dado já carrega sua proveniência, não precisa de outro argumento
    para redizer o mesmo)."""
    if predictions.height == 0 or "model_id" not in predictions.columns:
        return "predictions/alpha/<vazio>/predictions.parquet"
    model_ids = sorted(predictions["model_id"].drop_nulls().unique().to_list())
    if not model_ids:
        return "predictions/alpha/<vazio>/predictions.parquet"
    if len(model_ids) > 1:
        logger.warning(
            "analysis.attribution.multiplos_model_id_em_predictions", model_ids=model_ids
        )
    return f"predictions/alpha/{'+'.join(model_ids)}/predictions.parquet"


def ic_by_regime(
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
    regimes: pl.DataFrame,
    features: tuple[str, ...],
) -> pl.DataFrame:
    """IC de Spearman entre cada feature de `features` e `ret_net`,
    fatiado por regime (R0-R5) — reprodução testável da investigação ad
    hoc descrita na docstring do módulo.

    **Junção, em duas etapas:**
    1. `predictions` (filtrado `is_oof=True` e `side_hat != 0`) com
       `labels` via `(t0, side_hat == side)` — restringe ao lado que o
       modelo de fato decidiu naquele `t0`, pegando o resultado REALIZADO
       daquele lado (`ret_net`, `barrier_hit`). Descarta em seguida
       `barrier_hit == "NOFILL"` (ruído de execução, não sinal).
    2. O resultado com `regimes` via `t0`, para trazer `regime` e o valor
       bruto de cada feature de `features`. `regimes` PRECISA conter as
       colunas `t0`, `regime` e cada uma de `features` — não importa se
       veio de `src.models.dataset.build_modeling_frame().data` (já traz
       tudo isso, `t0` na convenção `close_time`) ou de uma junção manual
       de `src.regime.build.build_regimes()` (`t0` = `open_time`!) com
       `src.features.build.build_t1_features()`: quem monta `regimes` é
       responsável por alinhar a convenção de `t0` com a de
       `predictions`/`labels` (`close_time`) ANTES de chamar esta função —
       a normalização de dtype feita aqui (`_T0_DTYPE`) evita erro de tipo
       no join, mas não pode detectar um desalinhamento semântico de uma
       barra (open_time vs close_time), que é silencioso por natureza.
       `regimes` é deduplicado por `t0` antes do join (`keep="first"`) —
       regime/features não variam por lado, então múltiplas linhas por
       `t0` em `regimes` (ex.: saída de `build_modeling_frame`, uma por
       lado do label) são redundantes, não um erro.

    Cada IC vira um `Metric` (`Unit.RATIO`, `n` = contagem real de trades
    naquele regime após os dois joins e os dois filtros, `n_semantics=
    "trades"`, `source` apontando para `model_id` de `predictions`) —
    `n < 5` ou variância nula em qualquer um dos dois lados marca o
    `Metric` `valid=False` com `value=nan` em vez de reportar uma
    correlação sem sentido estatístico (mesmo guard de
    `src.models.monotonic.compute_ic_by_env`, duplicado aqui por design —
    ver docstring do módulo).

    Retorna uma linha por `(feature, regime)` com o `Metric` serializado em
    colunas separadas prefixadas `ic_` (`ic_value`, `ic_unit`, `ic_n`,
    `ic_n_semantics`, `ic_source`, `ic_valid`, `ic_invalid_reason`) — mais
    fácil de filtrar/ordenar num `pl.DataFrame` do que uma coluna struct."""
    if not features:
        raise ValueError("ic_by_regime: features vazio — nada para medir")

    _require_columns(predictions, ("t0", "side_hat", "is_oof"), df_name="predictions")
    _require_columns(labels, ("t0", "side", "barrier_hit", "ret_net"), df_name="labels")
    _require_columns(regimes, (_T0_COL, _REGIME_COL, *features), df_name="regimes")

    source = _infer_predictions_source(predictions)

    preds_filtered = (
        predictions.filter(pl.col("is_oof") & (pl.col("side_hat") != 0))
        .select(["t0", "side_hat"])
        .with_columns(pl.col("t0").cast(_T0_DTYPE))
    )
    labels_small = labels.select(["t0", "side", _BARRIER_HIT_COL, _RET_NET_COL]).with_columns(
        pl.col("t0").cast(_T0_DTYPE)
    )

    joined = preds_filtered.join(
        labels_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
    ).filter(pl.col(_BARRIER_HIT_COL).cast(pl.Utf8) != _NOFILL)

    n_before_regime_join = joined.height

    regimes_small = (
        regimes.select([_T0_COL, _REGIME_COL, *features])
        .with_columns(pl.col(_T0_COL).cast(_T0_DTYPE))
        .unique(subset=[_T0_COL], keep="first")
    )
    joined = joined.join(regimes_small, on="t0", how="inner")

    logger.info(
        "analysis.attribution.ic_by_regime_joined",
        n_predictions_oof_com_lado=preds_filtered.height,
        n_apos_join_labels_e_nofill=n_before_regime_join,
        n_apos_join_regimes=joined.height,
        n_features=len(features),
        source=source,
    )

    regime_values = sorted(
        v for v in joined[_REGIME_COL].drop_nulls().cast(pl.Utf8).unique().to_list()
    )

    rows: list[dict[str, Any]] = []
    for regime_label in regime_values:
        sub = joined.filter(pl.col(_REGIME_COL).cast(pl.Utf8) == regime_label)
        y = sub[_RET_NET_COL].to_numpy().astype(np.float64)
        for feature in features:
            x = sub[feature].to_numpy().astype(np.float64)
            metric = _spearman_metric(x, y, n_semantics=_N_SEMANTICS_TRADES, source=source)
            rows.append({"feature": feature, "regime": regime_label, **_prefixed_metric(metric)})

    if not rows:
        return pl.DataFrame(schema=_IC_OUTPUT_SCHEMA)
    return pl.DataFrame(rows, schema=_IC_OUTPUT_SCHEMA)


def _prefixed_metric(metric: Metric) -> dict[str, Any]:
    return {f"ic_{k}": v for k, v in metric.to_json().items()}


def _spearman_metric(x: FloatArray, y: FloatArray, *, n_semantics: str, source: str) -> Metric:
    """Núcleo puro compartilhado por `ic_by_regime` e `feature_agreement` —
    `x`/`y` alinhados posicionalmente, `nan`/`inf` mascarados antes da
    correlação (mesmo tratamento de
    `src.models.monotonic.compute_ic_by_env`, duplicado por design — ver
    docstring do módulo)."""
    mask = np.isfinite(x) & np.isfinite(y)
    n_valid = int(mask.sum())
    if n_valid < _MIN_OBS_SPEARMAN or np.std(x[mask]) == 0.0 or np.std(y[mask]) == 0.0:
        reason = (
            f"n_valid={n_valid} < {_MIN_OBS_SPEARMAN} ou variância nula"
            if n_valid < _MIN_OBS_SPEARMAN
            else "variância nula em x ou y"
        )
        return Metric(
            value=float("nan"),
            unit=Unit.RATIO,
            n=n_valid,
            n_semantics=n_semantics,
            source=source,
            valid=False,
            invalid_reason=reason,
        )
    rho, _p = spearmanr(x[mask], y[mask])
    value = float(rho) if np.isfinite(rho) else float("nan")
    return Metric(
        value=value,
        unit=Unit.RATIO,
        n=n_valid,
        n_semantics=n_semantics,
        source=source,
        valid=math.isfinite(value),
        invalid_reason=None if math.isfinite(value) else "spearmanr retornou nao-finito",
    )


def gain_by_side(diagnostics_dir: Path, model_id: str) -> pl.DataFrame:
    """Agrega `gain_by_column` (bruto) e `concentration_shares`
    (normalizado) já persistidos por
    `src.models.pipeline.write_fold_diagnostics_atomic` (Fase A) — média e
    desvio-padrão AMOSTRAL (`ddof=1`, `0.0` se só 1 fold) entre folds, por
    `(feature, side)`. Nenhum retreino: só leitura dos JSON já em disco.

    `diagnostics_dir` já deve apontar para o diretório
    `models/{model_id}/diagnostics/` (ex.:
    `src.models.pipeline.MODELS_DIR / model_id / "diagnostics"`) — este
    módulo não conhece a convenção de path de `src.models` (ver restrição
    de arquitetura na docstring do módulo: `src.analysis` não importa
    `src.models`), então não resolve o caminho sozinho. `model_id` é usado
    para (a) rotular a coluna `model_id` da saída e (b) checagem cruzada
    contra o campo `model_id` de cada JSON (`ValueError` se algum arquivo
    pertencer a outro `model_id` — sinal de `diagnostics_dir` errado).

    "feature" na saída inclui tanto as features T1 quanto as colunas
    dummy de regime (`regime_R2`..`regime_R5`) — o mesmo conjunto de
    `gain_by_column`/`concentration_shares` no JSON bruto
    (`src.models.alpha.DESIGN_COLUMNS`), sem filtrar. Colunas ausentes de
    `gain_by_column` num fold específico (o booster pode não ter usado
    aquela coluna em nenhuma divisão) entram como `0.0` nesse fold — mesma
    convenção de `src.models.hhi.compute_concentration`
    (`gain_by_column.get(col, 0.0)`), não são omitidas da média."""
    long_files = sorted(diagnostics_dir.glob("fold_*_long.json"))
    short_files = sorted(diagnostics_dir.glob("fold_*_short.json"))
    if not long_files and not short_files:
        raise FileNotFoundError(
            f"gain_by_side: nenhum fold_*_{{long,short}}.json em {diagnostics_dir}"
        )

    rows: list[dict[str, Any]] = []
    for side_label, files in (("long", long_files), ("short", short_files)):
        if not files:
            logger.warning(
                "analysis.attribution.gain_by_side_lado_sem_arquivos",
                side=side_label,
                diagnostics_dir=str(diagnostics_dir),
            )
            continue
        rows.extend(_aggregate_side(files, side_label=side_label, model_id=model_id))

    if not rows:
        return pl.DataFrame(schema=_GAIN_OUTPUT_SCHEMA)
    return pl.DataFrame(rows, schema=_GAIN_OUTPUT_SCHEMA)


def _aggregate_side(files: list[Path], *, side_label: str, model_id: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in files:
        payload: dict[str, Any] = orjson.loads(path.read_bytes())
        if payload.get("model_id") != model_id:
            raise ValueError(
                f"gain_by_side: {path} tem model_id={payload.get('model_id')!r}, "
                f"esperado {model_id!r} — diagnostics_dir provavelmente errado"
            )
        payloads.append(payload)

    all_columns: set[str] = set()
    for payload in payloads:
        all_columns.update(payload["gain_by_column"].keys())
        all_columns.update(payload["concentration_shares"].keys())

    n_folds = len(payloads)
    rows: list[dict[str, Any]] = []
    for col in sorted(all_columns):
        gain_vals = np.array(
            [float(p["gain_by_column"].get(col, 0.0)) for p in payloads], dtype=np.float64
        )
        share_vals = np.array(
            [float(p["concentration_shares"].get(col, 0.0)) for p in payloads], dtype=np.float64
        )
        rows.append(
            {
                "feature": col,
                "side": side_label,
                "model_id": model_id,
                "gain_mean": float(np.mean(gain_vals)),
                "gain_std": float(np.std(gain_vals, ddof=1)) if n_folds > 1 else 0.0,
                "share_mean": float(np.mean(share_vals)),
                "share_std": float(np.std(share_vals, ddof=1)) if n_folds > 1 else 0.0,
                "n_folds": n_folds,
            }
        )
    return rows


def _single_score_column(df: pl.DataFrame, *, df_name: str) -> str:
    """`feature_agreement` espera `gain_ranking`/`ic_ranking` já reduzidos
    a uma linha por feature: coluna `"feature"` + exatamente UMA coluna
    numérica de score (nome livre — ex. `gain_mean`, `ic_value` médio
    entre regimes). Agregar `gain_by_side`/`ic_by_regime` (que têm uma
    linha por `side`/`regime`) até esse formato é responsabilidade de quem
    chama (ex.: `ic_df.group_by("feature").agg(pl.col("ic_value").mean())`)
    — `feature_agreement` não adivinha qual redução fazer (média? só um
    regime? peso por `n`?), isso é uma decisão de análise, não mecânica."""
    if "feature" not in df.columns:
        raise ValueError(f"{df_name}: coluna 'feature' ausente")
    other = [c for c in df.columns if c != "feature"]
    if len(other) != 1:
        raise ValueError(
            f"{df_name}: esperado 'feature' + exatamente 1 coluna de score, "
            f"encontrado {other} — agregue antes de chamar feature_agreement "
            "(ver docstring)"
        )
    if df["feature"].n_unique() != df.height:
        raise ValueError(
            f"{df_name}: coluna 'feature' tem valores repetidos — "
            "agregue para uma linha por feature antes de chamar feature_agreement"
        )
    return other[0]


def feature_agreement(
    gain_ranking: pl.DataFrame,
    ic_ranking: pl.DataFrame,
    *,
    source: str = "src.analysis.attribution.feature_agreement",
) -> Metric:
    """Spearman entre o ranking de features por gain (`gain_ranking`) e
    por IC (`ic_ranking`) — o quanto os dois métodos concordam sobre quais
    features importam. Cada argumento precisa ter exatamente as colunas
    `"feature"` + 1 coluna numérica de score, uma linha por feature (ver
    `_single_score_column`) — tipicamente `gain_by_side(...).filter(pl.col
    ("side") == "long").select(["feature", "gain_mean"])` e `ic_by_regime
    (...).group_by("feature").agg(pl.col("ic_value").mean().alias
    ("ic_value"))`, ou qualquer outra redução que o chamador julgue
    apropriada (a função não impõe UMA forma de reduzir side/regime a um
    score único — ver docstring de `_single_score_column`).

    Junta os dois por `"feature"` (`inner` — só features presentes nos
    dois rankings entram na correlação) e devolve um `Metric` único
    (`Unit.RATIO`, `n` = nº de features em comum, `n_semantics=
    "features"`). Mesmo guard de `n < 5`/variância nula de
    `ic_by_regime`/`src.models.monotonic` (`_spearman_metric`, núcleo
    compartilhado)."""
    gain_col = _single_score_column(gain_ranking, df_name="gain_ranking")
    ic_col = _single_score_column(ic_ranking, df_name="ic_ranking")

    joined = gain_ranking.select(["feature", gain_col]).join(
        ic_ranking.select(["feature", ic_col]), on="feature", how="inner"
    )
    logger.info(
        "analysis.attribution.feature_agreement_joined",
        n_features_gain=gain_ranking.height,
        n_features_ic=ic_ranking.height,
        n_features_em_comum=joined.height,
    )

    x = joined[gain_col].to_numpy().astype(np.float64)
    y = joined[ic_col].to_numpy().astype(np.float64)
    return _spearman_metric(x, y, n_semantics=_N_SEMANTICS_FEATURES, source=source)


def confidence_deciles_by_side(
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
    *,
    n_deciles: int = _N_DECILES_DEFAULT,
) -> pl.DataFrame:
    """Testa se a probabilidade calibrada do Alpha (`confidence` —
    `max(p_long, p_short)`, que por construção é `p_long` quando
    `side_hat=1` e `p_short` quando `side_hat=-1`, ver
    `src.models.alpha.run_fold`) ordena os trades por retorno REALIZADO,
    para cada lado separadamente. Pergunta diferente de "o sinal médio é
    positivo" — é "a confiança carrega informação MONOTÔNICA": decil 10
    (mais confiante) deveria, se a calibração for informativa, entregar
    `mean_ret_net_bps` maior que decil 1 (menos confiante). Ver docstring
    do módulo para o motivo desta função existir (avalia se uma Camada 2+
    do Alpha teria o que explorar, §5.11/§6.8).

    **Junção — mesmo padrão de `ic_by_regime`, uma vez por lado:**
    `predictions` filtrado por `is_oof=True` e `side_hat == side` (não
    `!= 0` — aqui o lado é fixo por iteração, não "qualquer lado
    decidido") é juntado com `labels` por `(t0, side_hat == side)`, e
    `barrier_hit == "NOFILL"` é descartado (ruído de execução, não sinal
    de confiança). `predictions` precisa conter `t0`, `side_hat`,
    `is_oof` e `confidence`; `labels` precisa conter `t0`, `side`,
    `barrier_hit` e `ret_net`.

    **Decis por RANK, não por valor (`qcut`).** Dentro de cada lado, os
    trades juntados são ordenados por `confidence` ascendente — decil 1 =
    confiança mais baixa, decil `n_deciles` = mais alta — com desempate
    determinístico por `t0` (o calibrador isotônico produz platôs de
    `confidence` idêntica; sem desempate estável a atribuição de decil
    dependeria da ordem de chegada das linhas no parquet, que não é
    garantida — `assemble_predictions_table` concatena folds por `t0`, não
    por confiança). O índice de decil de cada linha é
    `(posição_no_rank * n_deciles) // n_total_do_lado + 1`: bucketing por
    RANK garante grupos do mesmo tamanho (a menos de ±1) mesmo com muitos
    empates de valor, ao contrário de `qcut` por quantil de VALOR (que
    pode colapsar vários decis num só se houver platô grande o bastante).
    Se `n_total_do_lado < n_deciles`, alguns índices de decil não recebem
    nenhuma linha — essas linhas saem com `n=0`,
    `mean_ret_net_bps_valid=False` (`not_computable`) e `t_stat=nan`, não
    são omitidas da tabela (o buraco em si é informação: poucos trades
    naquele lado para a granularidade de decil pedida).

    **Cada decil vira uma linha** com `side`, `decile` (1..`n_deciles`),
    `n` (contagem de trades REALIZADOS naquele decil — mesmo valor que
    `mean_ret_net_bps_n`, duplicado como coluna própria por legibilidade
    direta, sem precisar desempacotar o `Metric`), `confidence_min`/
    `confidence_max` (bordas do decil, para reportar a faixa de
    probabilidade que ele cobre), o `Metric` da média de `ret_net` em BPS
    (`ret_net * 10_000`, `Unit.BPS_PER_TRADE`, `n_semantics="trades"`)
    achatado em colunas prefixadas `mean_ret_net_bps_*` (mesmo padrão de
    `ic_by_regime`/`_prefixed_metric`, mas com prefixo próprio — não reusa
    `_prefixed_metric` porque aquele helper está fixado ao prefixo `ic_`;
    ver docstring do módulo sobre não amarrar lógica de análise a um único
    caminho de código), `std_ret_net_bps` (desvio-padrão AMOSTRAL,
    `ddof=1`, `0.0` se só 1 trade — mesma convenção de `gain_by_side`), e
    `t_stat` (`mean_ret_net_bps / (std_ret_net_bps / sqrt(n))`, testando
    se a média do decil é diferente de zero — `nan` se `n < 2` ou
    `std_ret_net_bps == 0.0`, denominador indefinido/nulo, nunca
    `ZeroDivisionError`/`inf` silencioso).

    **Não decide nada.** Esta função só mede — não aplica os critérios do
    achado (candidatura a operar em frequência menor se decil 10 tiver
    `mean_ret_net_bps >= 6.0` com `t > 2.0`; evidência contra Camada 2+ se
    todos os decis ficarem entre 0,5 e 2,5 bps sem ordenação clara) nem
    escreve de volta em nenhum lugar do pipeline — isso é leitura de quem
    chama, no relatório, não comportamento do módulo (mesma fronteira
    PÓS-HOC/nunca-insumo da docstring do módulo)."""
    if n_deciles < 1:
        raise ValueError(f"confidence_deciles_by_side: n_deciles={n_deciles} — precisa ser >= 1")

    _require_columns(
        predictions, ("t0", "side_hat", "is_oof", _CONFIDENCE_COL), df_name="predictions"
    )
    _require_columns(labels, ("t0", "side", _BARRIER_HIT_COL, _RET_NET_COL), df_name="labels")

    source = _infer_predictions_source(predictions)
    labels_small = labels.select(["t0", "side", _BARRIER_HIT_COL, _RET_NET_COL]).with_columns(
        pl.col("t0").cast(_T0_DTYPE)
    )

    rows: list[dict[str, Any]] = []
    for side_value, side_label in _SIDE_LABEL_BY_HAT.items():
        preds_side = (
            predictions.filter(pl.col("is_oof") & (pl.col("side_hat") == side_value))
            .select(["t0", "side_hat", _CONFIDENCE_COL])
            .with_columns(pl.col("t0").cast(_T0_DTYPE))
        )
        joined = preds_side.join(
            labels_small, left_on=["t0", "side_hat"], right_on=["t0", "side"], how="inner"
        ).filter(pl.col(_BARRIER_HIT_COL).cast(pl.Utf8) != _NOFILL)

        logger.info(
            "analysis.attribution.confidence_deciles_by_side_joined",
            side=side_label,
            n_predictions_oof_lado=preds_side.height,
            n_apos_join_labels_e_nofill=joined.height,
            n_deciles=n_deciles,
            source=source,
        )

        if joined.height == 0:
            logger.warning(
                "analysis.attribution.confidence_deciles_sem_trades_no_lado", side=side_label
            )
            continue

        rows.extend(
            _deciles_for_side(joined, side_label=side_label, n_deciles=n_deciles, source=source)
        )

    if not rows:
        return pl.DataFrame(schema=_DECILE_OUTPUT_SCHEMA)
    return pl.DataFrame(rows, schema=_DECILE_OUTPUT_SCHEMA)


def _deciles_for_side(
    joined: pl.DataFrame, *, side_label: str, n_deciles: int, source: str
) -> list[dict[str, Any]]:
    """Núcleo de bucketing por rank + agregação, uma chamada por lado (ver
    `confidence_deciles_by_side`). `joined` já passou pelos dois filtros
    (`is_oof`/`side_hat`/`NOFILL`) — aqui só ordena, atribui decil e agrega."""
    ordered = joined.sort([_CONFIDENCE_COL, "t0"])
    n_total = ordered.height
    idx = np.arange(n_total, dtype=np.int64)
    decile_idx = (idx * n_deciles) // n_total + 1  # sempre em [1, n_deciles], ver docstring
    ordered = ordered.with_columns(pl.Series("decile", decile_idx, dtype=pl.Int64))

    rows: list[dict[str, Any]] = []
    for decile in range(1, n_deciles + 1):
        sub = ordered.filter(pl.col("decile") == decile)
        rows.append(
            _decile_row(
                sub, side_label=side_label, decile=decile, n_deciles=n_deciles, source=source
            )
        )
    return rows


def _decile_row(
    sub: pl.DataFrame, *, side_label: str, decile: int, n_deciles: int, source: str
) -> dict[str, Any]:
    n = sub.height
    if n == 0:
        metric = not_computable(
            Unit.BPS_PER_TRADE,
            _N_SEMANTICS_TRADES,
            source,
            f"decil {decile}/{n_deciles} sem trades no lado {side_label} "
            f"(n_total_do_lado < n_deciles)",
        )
        return {
            "side": side_label,
            "decile": decile,
            "n": 0,
            "confidence_min": float("nan"),
            "confidence_max": float("nan"),
            **{f"mean_ret_net_bps_{k}": v for k, v in metric.to_json().items()},
            "std_ret_net_bps": float("nan"),
            "t_stat": float("nan"),
        }

    bps = sub[_RET_NET_COL].to_numpy().astype(np.float64) * _BPS_PER_UNIT
    confidence = sub[_CONFIDENCE_COL].to_numpy().astype(np.float64)

    mean_bps = float(np.mean(bps))
    std_bps = float(np.std(bps, ddof=1)) if n > 1 else 0.0
    t_stat = mean_bps / (std_bps / math.sqrt(n)) if n > 1 and std_bps > 0.0 else float("nan")

    metric = Metric(
        value=mean_bps,
        unit=Unit.BPS_PER_TRADE,
        n=n,
        n_semantics=_N_SEMANTICS_TRADES,
        source=source,
        valid=True,
        invalid_reason=None,
    )
    return {
        "side": side_label,
        "decile": decile,
        "n": n,
        "confidence_min": float(np.min(confidence)),
        "confidence_max": float(np.max(confidence)),
        **{f"mean_ret_net_bps_{k}": v for k, v in metric.to_json().items()},
        "std_ret_net_bps": std_bps,
        "t_stat": t_stat,
    }
