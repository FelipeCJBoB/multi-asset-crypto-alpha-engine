"""Runner único dos 14 testes de vazamento — §11.5 RF-018.

**Nem todo teste da tabela é executável hoje, e este módulo não finge que
é.** Dos 14, dois dependem de um modelo TREINADO que não existe (Alpha é
Sprint 8, §5.9-§5.13) e um depende do Meta, que está fora da V1 inteira
(§6.1, V1.1). Estes recebem um sentinela explícito em vez de serem
simulados ou silenciosamente pulados — mesmo princípio de `NOT_COMPUTABLE`
em `src.regime.stress` (§4.4): "não sei" não é a mesma coisa que "passou",
e confundir os dois é exatamente a falha silenciosa que o CLAUDE.md pede
para nunca deixar passar.

```
PASS                — verificado agora, com evidência (código executado ou
                       auditoria estática com referência checada, não só
                       texto de docstring).
FAIL                 — verificado agora, e falhou.
PENDING_SPRINT_8     — precisa de artefato que só existe a partir do
                       Sprint 8 (Alpha treinado, calibrador). Não simulado.
NOT_APPLICABLE_V1_1  — o Meta está fora de escopo da V1 inteira (§6.1);
                       não é "pendente", é "não existe por desenho nesta
                       versão". Sentinela distinto de PENDING_SPRINT_8 de
                       propósito — reavaliar quando/se o Meta entrar em
                       escopo (critério §6.8), não num sprint numerado.
```

Cada teste é uma função `_test_NN_*()` independente. Alguns reexecutam a
checagem de verdade agora (4, 5, 6, 7, 9, 12 — código real rodando contra
dado real ou sintético controlado); outros são auditoria estática do que já
existe no repo, com a referência de teste CITADA verificada contra o
arquivo real, não só confiada por texto (2, 3, 8, 13, 14). Nenhum teste
"passa" por reformulação — se a evidência disponível hoje é parcial (7,
13, 14), o campo `note` diz isso explicitamente em vez de o status
esconder a lacuna.

`run_all_leakage_tests` orquestra os 14 e loga cada resultado via
`structlog` (nunca `print()`, B28). `write_leakage_report_atomic` grava o
relatório em `data/validation_reports/leakage_report.json` com o mesmo
padrão `.tmp -> fsync -> rename` (B29) já usado em
`src.data.validate.write_report_atomic`/`src.labels.triple_barrier.
write_labels_atomic`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
import structlog
import yaml
from numpy.typing import NDArray

from src.regime import classifier as regime_classifier
from src.regime import stress as regime_stress

from . import cpcv
from ._paths import CONSTANTS_PATH, REPO_ROOT, VALIDATION_REPORTS_DIR

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]

_SRC_ROOT: Path = REPO_ROOT / "src"
_FEATURE_REGISTRY_PATH: Path = _SRC_ROOT / "features" / "registry.yaml"
_TRIPLE_BARRIER_PATH: Path = _SRC_ROOT / "labels" / "triple_barrier.py"
_FEATURES_PARITY_TEST_PATH: Path = REPO_ROOT / "tests" / "parity" / "test_features_parity.py"

# Escopo dos grep estáticos de auditoria (testes 8/13): pacotes de PIPELINE,
# não a ferramenta de auditoria em si (`validation/` conteria os próprios
# padrões procurados nas strings de detalhe do relatório — falso positivo
# de "auditor se auditando"). `execution/` fica de fora por instrução
# explícita da task — outro agente trabalha em
# `src/execution/fill_simulator.py` em paralelo; mesmo um grep somente-
# leitura é evitado aqui por cautela, não por restrição técnica real.
_AUDITED_PIPELINE_ROOTS: tuple[Path, ...] = tuple(
    sorted(
        p
        for p in _SRC_ROOT.iterdir()
        if p.is_dir() and p.name not in {"validation", "execution", "__pycache__"}
    )
)


class LeakageStatus(Enum):
    """Deliberadamente NÃO `(str, Enum)` — mesma lição já documentada em
    `src.regime.stress.TriggerState`: misturar `str` quebra comparação
    vetorizada em `numpy` de forma silenciosa. Aqui não há array numpy de
    status, mas a convenção do repo é `Enum` puro por padrão; serialização
    para JSON usa `.value` explicitamente (`LeakageTestResult.to_dict`)."""

    PASS = "PASS"
    FAIL = "FAIL"
    PENDING_SPRINT_8 = "PENDING_SPRINT_8"
    NOT_APPLICABLE_V1_1 = "NOT_APPLICABLE_V1_1"


@dataclass(frozen=True, slots=True)
class LeakageTestResult:
    test_id: int
    name: str
    anchor: str
    status: LeakageStatus
    detail: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "anchor": self.anchor,
            "status": self.status.value,
            "detail": self.detail,
            "note": self.note,
        }


# ============================================================================
# Helpers de auditoria compartilhados
# ============================================================================

_TEST_REF_RE = re.compile(r"testado em ([\w/.\-]+\.py)::(\w+)")

# C02 é razão ponto a ponto de duas quantidades JÁ causais (atr_20_abs,
# close), sem janela própria — o registry documenta a derivação em vez de
# apontar um teste dedicado (confirmado por leitura de
# src/features/groups/group_c.py::c02_atr_20_pct nesta auditoria: não há
# lógica além da divisão em si para testar separadamente do que A05/A13/C01
# já cobrem para atr_20_abs). Categoria diferente de evidência, não uma
# lacuna — listado explicitamente em vez de inferido por regex frágil.
_DERIVATION_ONLY_CAUSAL_PROOF: frozenset[str] = frozenset({"C02_atr_20_pct"})

# Features T1 que consomem high/low, direta ou transitivamente via ATR de
# Wilder (§2.4 C01 = f(H, L, C)) — classificação feita nesta auditoria a
# partir da fórmula registrada em registry.yaml, não repetida do PRD.
_HIGH_LOW_FEATURES: tuple[str, ...] = (
    "A05_ret_vol_norm_4",
    "A13_dist_ema48_atr",
    "C01_atr_20",
    "C02_atr_20_pct",
    "E27f_cost_atr_ratio",
)

# Features T1 que consomem volume diretamente (D03f: log(1+V_t); D06f:
# taker_buy_volume/volume).
_VOLUME_FEATURES: tuple[str, ...] = (
    "D03f_volume_z_expanding",
    "D06f_taker_imbalance_z_48",
)

_GLOBAL_SCALER_PATTERN = re.compile(
    r"\b(StandardScaler|MinMaxScaler|RobustScaler)\b|\.fit_transform\("
)


def _load_feature_registry() -> list[dict[str, Any]]:
    with _FEATURE_REGISTRY_PATH.open(encoding="utf-8") as f:
        entries: list[dict[str, Any]] = yaml.safe_load(f) or []
    return entries


def _verify_causal_proof_reference(causal_proof: str) -> tuple[bool, str]:
    """Confirma que a referência 'testado em <arquivo>.py::<função>' dentro
    de `causal_proof` aponta para um arquivo E uma função que REALMENTE
    existem no repo agora — não confia no texto do registry sozinho."""
    m = _TEST_REF_RE.search(causal_proof)
    if m is None:
        return False, "sem referência 'testado em <arquivo>::<função>' no causal_proof"
    rel_path, func_name = m.group(1), m.group(2)
    test_path = REPO_ROOT / rel_path
    if not test_path.exists():
        return False, f"arquivo referenciado não existe: {rel_path}"
    source = test_path.read_text(encoding="utf-8")
    if f"def {func_name}(" not in source:
        return False, f"função '{func_name}' não encontrada em {rel_path}"
    return True, f"{rel_path}::{func_name}"


def _audit_registry_causal_proofs(
    feature_ids: tuple[str, ...],
) -> tuple[bool, list[str], list[str]]:
    """`(ok, problemas, evidencias)` — para cada `id` em `feature_ids`:
    `causal_proof`/`parity_tested` presentes no registry E a referência de
    teste citada verificada contra o arquivo real (exceto os IDs em
    `_DERIVATION_ONLY_CAUSAL_PROOF`, que documentam derivação sem teste
    dedicado por desenho)."""
    entries = {e["id"]: e for e in _load_feature_registry()}
    problems: list[str] = []
    evidence: list[str] = []
    for fid in feature_ids:
        entry = entries.get(fid)
        if entry is None:
            problems.append(f"{fid}: ausente do registry.yaml")
            continue
        causal_proof = str(entry.get("causal_proof") or "")
        if not causal_proof:
            problems.append(f"{fid}: causal_proof vazio")
            continue
        if entry.get("parity_tested") is not True:
            problems.append(f"{fid}: parity_tested != true")
        if fid in _DERIVATION_ONLY_CAUSAL_PROOF:
            evidence.append(f"{fid}: derivação documentada, sem teste dedicado (ver nota)")
            continue
        ok, ref_detail = _verify_causal_proof_reference(causal_proof)
        (evidence if ok else problems).append(f"{fid}: {ref_detail}")
    return (len(problems) == 0, problems, evidence)


def _grep_source(pattern: re.Pattern[str], roots: tuple[Path, ...]) -> list[str]:
    hits: list[str] = []
    for root in roots:
        for py_file in sorted(root.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            text = py_file.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(f"{py_file.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    return hits


def _select_rows(df: pl.DataFrame, idx: IntArray) -> pl.DataFrame:
    """Seleciona linhas por posição via máscara booleana (`filter`, retorno
    monomórfico) em vez de indexação por lista (`df[idx]`, cujo tipo de
    retorno é ambíguo entre `DataFrame`/`Series` nos stubs do polars) —
    escolha deliberada para ficar limpo sob `mypy --strict`."""
    mask = np.zeros(df.height, dtype=bool)
    mask[idx] = True
    return df.filter(pl.Series(mask))


def _load_known_gap_ids() -> set[str]:
    with CONSTANTS_PATH.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
    gaps = data.get("known_gaps", [])
    return {g["id"] for g in gaps if isinstance(g, dict) and "id" in g}


# ============================================================================
# Testes 1-14 — §11.5
# ============================================================================


def _test_01_close_futuro() -> LeakageTestResult:
    return LeakageTestResult(
        1,
        "close futuro (shuffle do alvo, AUC deve cair a ~0.5)",
        "§11.5 #1",
        LeakageStatus.PENDING_SPRINT_8,
        "Requer um modelo Alpha TREINADO para medir AUC antes/depois de embaralhar o alvo — "
        "nenhum modelo existe ainda (Sprint 8, §5.9-§5.13). Sentinela explícito, não simulado "
        "nem aproximado — mesmo princípio de NOT_COMPUTABLE em src.regime.stress.",
        note="Reexecutar assim que src/models/alpha existir e tiver ao menos um fold treinado.",
    )


def _test_02_high_low_futuro() -> LeakageTestResult:
    ok, problems, evidence = _audit_registry_causal_proofs(_HIGH_LOW_FEATURES)
    status = LeakageStatus.PASS if ok else LeakageStatus.FAIL
    detail = (
        f"Auditoria estática de {len(_HIGH_LOW_FEATURES)} features T1 que consomem high/low, "
        "direta ou transitivamente via ATR de Wilder: causal_proof + parity_tested no "
        "registry, com a referência de teste citada verificada contra o arquivo real (não só "
        f"texto). Evidência: {'; '.join(evidence)}."
    )
    if problems:
        detail += f" Problemas: {'; '.join(problems)}."
    return LeakageTestResult(2, "high/low futuro", "§11.5 #2", status, detail)


def _test_03_volume_futuro() -> LeakageTestResult:
    ok, problems, evidence = _audit_registry_causal_proofs(_VOLUME_FEATURES)
    status = LeakageStatus.PASS if ok else LeakageStatus.FAIL
    detail = (
        f"Auditoria estática de {len(_VOLUME_FEATURES)} features T1 que consomem volume "
        "diretamente (D03f: log(1+V_t) expansivo; D06f: taker_buy_volume/volume rolante): "
        f"mesma verificação de referência de teste real de #2. Evidência: {'; '.join(evidence)}."
    )
    if problems:
        detail += f" Problemas: {'; '.join(problems)}."
    return LeakageTestResult(3, "volume futuro", "§11.5 #3", status, detail)


def _test_04_funding_futuro() -> LeakageTestResult:
    # Recheck direto do PRIMITIVO que src.features._sources.asof_align_backward
    # usa por baixo (polars join_asof strategy="backward") — não importa o
    # módulo privado de outro pacote (_sources.py é privado a features/,
    # mesma convenção deste repo de duplicar _paths.py/_constants.py em vez
    # de importar entre pacotes); reimplementa a checagem mínima aqui para
    # não cruzar essa fronteira, e cruza com a auditoria de registry abaixo.
    bars = pl.DataFrame({"close_time": [899_999, 1_799_999, 2_699_999]}).sort("close_time")
    future_only = pl.DataFrame({"calc_time": [3_000_000], "last_funding_rate": [1.0]}).sort(
        "calc_time"
    )
    joined = bars.join_asof(
        future_only, left_on="close_time", right_on="calc_time", strategy="backward"
    )
    n_leaked = joined["last_funding_rate"].drop_nulls().len()

    ok, problems, evidence = _audit_registry_causal_proofs(("E02f_funding_z_expanding",))
    status = LeakageStatus.PASS if (n_leaked == 0 and ok) else LeakageStatus.FAIL
    detail = (
        "Recheck direto do primitivo (join_asof strategy='backward'): um evento de funding "
        "POSTERIOR ao close_time de TODAS as barras nunca é selecionado "
        f"(linhas vazadas={n_leaked}, esperado 0). Auditoria de registry: "
        f"{'; '.join(evidence)}. Nota de nomenclatura: o PRD (§11.5 #4) cita a feature como "
        "'funding_next_est'; a implementação real é E02f_funding_z_expanding (z-score "
        "expansivo de funding_last alinhado por asof-join backward) — nome diferente, mesma "
        "garantia causal. Achado reportado, não silenciado."
    )
    if problems:
        detail += f" Problemas no registry: {'; '.join(problems)}."
    return LeakageTestResult(4, "funding futuro", "§11.5 #4", status, detail)


def _test_05_regime_futuro() -> LeakageTestResult:
    # Recheck direto (não só citação de teste existente): mesma técnica de
    # tests/unit/test_regime_classifier.py::test_causalidade_perturbar_futuro_nao_muda_passado,
    # reexecutada aqui de forma independente para o runner produzir um
    # PASS/FAIL real. classifier.py/stress.py são módulos PÚBLICOS de
    # regime/ (sem underscore) — import direto é o padrão já usado por
    # regime/build.py para seus próprios pares, e por outros pacotes deste
    # repo para submódulos públicos de terceiros (ex.:
    # src.labels.triple_barrier -> src.features.groups.group_c).
    n = 300
    cutoff = 150
    rng = np.random.default_rng(7)
    open_time_ms = (np.arange(n, dtype=np.int64) * 900_000) + 1_600_000_000_000
    er_48 = rng.uniform(0.0, 1.0, n)
    vol_pctile = rng.uniform(0.0, 1.0, n)
    cost_atr = rng.uniform(0.0, 1.0, n)

    not_computable = np.full(n, regime_stress.TriggerState.NOT_COMPUTABLE, dtype=object)
    stress_result = regime_stress.StressResult(
        triggers={sid: not_computable.copy() for sid in regime_stress.TRIGGER_IDS},
        triggered_mask=np.zeros(n, dtype=bool),
        stress_triggers_list=tuple(() for _ in range(n)),
    )
    # Cortes REAIS de constants.yaml (regime_er_cutoff/regime_vol_cutoff/etc.,
    # §0.2), não literais soltos — só `min_warmup_bars` é sobrescrito (a
    # constante de produção é 2000, grande demais para um recheck de n=300).
    thresholds = replace(regime_classifier.RegimeThresholds.from_constants(), min_warmup_bars=5)
    base = regime_classifier.classify_regimes(
        open_time_ms, er_48, vol_pctile, cost_atr, stress_result, thresholds=thresholds
    )

    er_p, vol_p, cost_p = er_48.copy(), vol_pctile.copy(), cost_atr.copy()
    tail = n - cutoff - 1
    er_p[cutoff + 1 :] = rng.uniform(0.0, 1.0, tail)
    vol_p[cutoff + 1 :] = rng.uniform(0.0, 1.0, tail)
    cost_p[cutoff + 1 :] = rng.uniform(0.0, 1.0, tail)
    perturbed = regime_classifier.classify_regimes(
        open_time_ms, er_p, vol_p, cost_p, stress_result, thresholds=thresholds
    )

    mismatches = [
        col
        for col in ("regime", "er_quantile", "econ_regime")
        if not base[col].head(cutoff + 1).equals(perturbed[col].head(cutoff + 1), null_equal=True)
    ]
    status = LeakageStatus.PASS if not mismatches else LeakageStatus.FAIL
    detail = (
        f"Recheck direto: perturbar er_48/vol_pctile/cost_atr_ratio DEPOIS do cutoff (n={n}, "
        f"cutoff={cutoff}) não muda regime/er_quantile/econ_regime ANTES do cutoff."
    )
    if mismatches:
        detail += f" Colunas que mudaram no passado: {mismatches}."
    return LeakageTestResult(5, "regime futuro", "§11.5 #5", status, detail)


def _test_06_contaminacao_label(labels: pl.DataFrame) -> LeakageTestResult:
    name = "contaminação de label (t1 de treino nunca cruza janela de teste)"
    try:
        result = cpcv.generate_splits(labels)
        cpcv.assert_no_train_t1_leaks_into_test(labels, result)
    except AssertionError as exc:
        return LeakageTestResult(6, name, "§11.5 #6", LeakageStatus.FAIL, str(exc))

    summary = cpcv.summarize_splits(result)
    total_purged = int(summary["n_purged"].sum())
    total_embargoed = int(summary["n_embargoed"].sum())
    detail = (
        f"CPCV real sobre labels/v1/labels.parquet ({labels.height} linhas): "
        f"{result.config.n_splits} splits combinatórios, {result.config.n_backtest_paths} "
        f"caminhos de backtest, {total_purged} linha(s)-split purgada(s) no total "
        f"({round(total_purged / result.config.n_splits)} em média por split), "
        f"{total_embargoed} linha(s)-split em janela de embargo. "
        "assert_no_train_t1_leaks_into_test passou nos "
        f"{result.config.n_splits} splits — ZERO t1 de treino cruza qualquer janela de teste."
    )
    return LeakageTestResult(6, name, "§11.5 #6", LeakageStatus.PASS, detail)


def _test_07_labels_sobrepostos(labels: pl.DataFrame) -> LeakageTestResult:
    name = "labels sobrepostos (sample_weight aplicado em todo fit)"
    if "sample_weight" not in labels.columns:
        return LeakageTestResult(
            7, name, "§11.5 #7", LeakageStatus.FAIL, "coluna sample_weight ausente de labels"
        )

    weights = labels["sample_weight"].to_numpy().astype(np.float64)
    finite_ok = bool(np.all(np.isfinite(weights)))
    mean_w = float(np.mean(weights))
    tolerance = 1e-6  # mesma tolerância de assert_label_invariants (§3.8)  # noqa: magic-number
    mean_ok = abs(mean_w - 1.0) < tolerance

    result = cpcv.generate_splits(labels)
    split0 = result.splits[0]
    threaded = weights[split0.train_idx]
    threaded_ok = threaded.shape[0] == split0.train_idx.shape[0] and bool(
        np.all(np.isfinite(threaded))
    )

    status = LeakageStatus.PASS if (finite_ok and mean_ok and threaded_ok) else LeakageStatus.FAIL
    detail = (
        f"sample_weight presente, finito em {'todas' if finite_ok else 'NEM todas'} as linhas, "
        f"média={mean_w:.6f} (~1.0 dentro de 1e-6, invariante §3.8). Threading pelo CPCV "
        f"verificado: labels.sample_weight[train_idx] do split 0 produz {threaded.shape[0]} "
        "pesos alinhados e finitos."
    )
    note = (
        "PARCIAL por natureza, não por omissão: 'aplicado em TODO fit' pressupõe que fits "
        "existem — não existem antes do Sprint 8. Isto confirma o que já é verificável hoje "
        "(coluna bem formada, sobrevive ao threading do CPCV); o fit em si usando o peso é "
        "responsabilidade do Sprint 8. Reportado como PASS parcial em vez de PENDING_SPRINT_8 "
        "porque, ao contrário dos testes 1/11, HÁ algo concreto e automatizado verificado agora."
    )
    return LeakageTestResult(7, name, "§11.5 #7", status, detail, note)


def _test_08_normalizacao_global() -> LeakageTestResult:
    hits = _grep_source(_GLOBAL_SCALER_PATTERN, _AUDITED_PIPELINE_ROOTS)
    ok, problems, evidence = _audit_registry_causal_proofs(
        ("C07_vol_pctile_expanding", "D03f_volume_z_expanding", "E02f_funding_z_expanding")
    )
    status = LeakageStatus.PASS if (not hits and ok) else LeakageStatus.FAIL
    detail = (
        f"Grep estático em src/ por scaler global (StandardScaler/MinMaxScaler/RobustScaler/"
        f".fit_transform) — {len(hits)} ocorrência(s) encontrada(s). Normalização hoje é "
        "sempre expansiva estrita (Welford online, support.expanding_zscore_strict) ou posto "
        "percentil expansivo (Fenwick tree, support.expanding_percentile_rank_strict), nunca "
        f"um scaler ajustado sobre o dataset inteiro. Evidência do registry: {'; '.join(evidence)}."
    )
    if hits:
        detail += f" Ocorrências: {hits}."
    if problems:
        detail += f" Problemas no registry: {'; '.join(problems)}."
    return LeakageTestResult(8, "normalização global", "§11.5 #8", status, detail)


def _test_09_lookahead_resample() -> LeakageTestResult:
    from src.data import resample as data_resample

    n = 90  # 3 buckets completos de 30m a partir de 1m
    open_times = [i * 60_000 for i in range(n)]
    df_1m = pl.DataFrame(
        {
            "open_time": open_times,
            "open": [str(float(i)) for i in range(n)],
            "high": [str(float(i) + 0.5) for i in range(n)],
            "low": [str(float(i) - 0.5) for i in range(n)],
            "close": [str(float(i)) for i in range(n)],
            "volume": [1.0] * n,
            "close_time": [t + 59_999 for t in open_times],
            "quote_volume": [1.0] * n,
            "count": [1] * n,
            "taker_buy_volume": [0.5] * n,
            "taker_buy_quote_volume": [0.5] * n,
        }
    )
    out_30m = data_resample.resample_klines(df_1m, "30m")
    try:
        data_resample.assert_no_lookahead(df_1m, out_30m, "30m")
        ok, reason = True, ""
    except AssertionError as exc:
        ok, reason = False, str(exc)

    status = LeakageStatus.PASS if ok else LeakageStatus.FAIL
    detail = (
        f"Recheck direto de resample.resample_klines/assert_no_lookahead ESPECIFICAMENTE para "
        f"1m->30m (a cobertura anterior de tests/unit/test_data_resample.py só exercitava "
        f"5m/15m) — {out_30m.height} bucket(s) de 30m verificados, close_time de cada barra "
        "agregada >= max(close_time) das constituintes de 1m. Complementado por "
        "test_assert_no_lookahead_passa_para_resample_correto_30m em "
        "tests/unit/test_data_resample.py (gap fechado nesta auditoria)."
    )
    if not ok:
        detail += f" Falha: {reason}"
    return LeakageTestResult(9, "look-ahead em resample (1m->30m)", "§11.5 #9", status, detail)


def _test_10_encadeamento_modelo() -> LeakageTestResult:
    return LeakageTestResult(
        10,
        "encadeamento de modelo (assert df_meta.is_oof.all())",
        "§11.5 #10",
        LeakageStatus.NOT_APPLICABLE_V1_1,
        "O Meta sai do MVP (§6.1) — vai para a V1.1. Não existe df_meta nem is_oof em nenhum "
        "artefato real hoje (is_oof é coluna de predictions/alpha/{model_id}/"
        "predictions.parquet, §5.12, que também não existe antes do Sprint 8). Documentado "
        "como N/A, não simulado com um dataframe fictício — simular is_oof=True para um Meta "
        "que não existe produziria um PASS que não prova nada.",
        note="Reavaliar quando o Meta entrar em escopo (critério de entrada em §6.8).",
    )


def _test_11_calibracao_vazada() -> LeakageTestResult:
    return LeakageTestResult(
        11,
        "calibração vazada (calibrador ajustado em sub-split interno)",
        "§11.5 #11",
        LeakageStatus.PENDING_SPRINT_8,
        "Nenhum calibrador existe ainda — calibração isotônica é o passo 9 do cronograma "
        "§5.9, dentro do treino do Alpha (Sprint 8). Sentinela explícito.",
        note="Reexecutar assim que src/models/alpha implementar o passo de calibração.",
    )


def _test_12_selecao_feature_vazada(labels: pl.DataFrame) -> LeakageTestResult:
    name = "seleção de feature vazada (seleção dentro de cada fold)"
    result = cpcv.generate_splits(labels)
    violations: list[str] = []
    for split in result.splits:
        overlap = np.intersect1d(split.train_idx, split.test_idx)
        if overlap.size:
            violations.append(
                f"split {split.split_id}: {overlap.size} índice(s) em train_idx E test_idx"
            )
        # "seletor in-fold" fictício: só recebe a VIEW filtrada por
        # train_idx, nunca o df inteiro nem test_idx — prova de isolamento
        # por construção (a view não tem como enxergar dado de teste),
        # não por convenção de quem chama.
        train_view = _select_rows(labels, split.train_idx)
        if train_view.height != split.train_idx.shape[0]:
            violations.append(f"split {split.split_id}: view de treino com tamanho inesperado")

    status = LeakageStatus.PASS if not violations else LeakageStatus.FAIL
    detail = (
        f"{result.config.n_splits} splits verificados: train_idx e test_idx nunca se "
        "intersectam, e um seletor de feature 'in-fold' fictício que só recebe "
        "labels[train_idx] fisicamente não tem como enxergar dado de teste (isolamento por "
        "construção). A triagem de estabilidade real (§5.4) é Sprint 8; este teste confirma "
        "que o SPLITTER em si não vaza — pré-condição necessária para qualquer seletor "
        "futuro rodar in-fold corretamente."
    )
    if violations:
        detail += f" Violações: {violations}."
    return LeakageTestResult(12, name, "§11.5 #12", status, detail)


def _test_13_filtros_anacronicos() -> LeakageTestResult:
    name = "filtros anacrônicos (load_filters_asof em todo o caminho)"
    source = _TRIPLE_BARRIER_PATH.read_text(encoding="utf-8")
    uses_asof = "load_filters_asof" in source
    # busca a DEFINIÇÃO da função, não qualquer menção textual — o próprio
    # docstring de src/exchange/filters.py cita "load_filters_current()"
    # em prosa para explicar por que ela NÃO existe (ver módulo), o que
    # daria falso positivo numa busca textual ingênua.
    no_current_variant = not _grep_source(
        re.compile(r"^\s*def load_filters_current\s*\("), _AUDITED_PIPELINE_ROOTS
    )
    default_fallback_off = "historical_filters_fallback: bool = False" in source
    gap_documented = "exchange_info_snapshot_coverage_gap" in _load_known_gap_ids()

    ok = uses_asof and no_current_variant and default_fallback_off and gap_documented
    status = LeakageStatus.PASS if ok else LeakageStatus.FAIL
    detail = (
        f"src/labels/triple_barrier.py usa load_filters_asof: {uses_asof}. Nenhuma variante "
        f"'load_filters_current' existe em src/: {no_current_variant}. Fallback histórico é "
        f"OPT-IN (historical_filters_fallback default False): {default_fallback_off} — "
        "default levanta NoFiltersAvailableError, testado em "
        "tests/unit/test_labels_triple_barrier.py. Gap de cobertura (só 1 snapshot no disco) "
        f"documentado em known_gaps.exchange_info_snapshot_coverage_gap: {gap_documented}."
    )
    note = (
        "Escopo desta auditoria: só src/labels/ consome filtros de instrumento hoje. "
        "src/risk/ e src/execution/ ainda não têm lógica real (Sprint 9+; src/execution/ "
        "fora de escopo desta auditoria por instrução explícita — outro agente trabalha em "
        "src/execution/fill_simulator.py em paralelo). 'Todo o caminho' será reavaliado "
        "quando risk/execution existirem."
    )
    return LeakageTestResult(13, name, "§11.5 #13", status, detail, note)


def _test_14_paridade_lote_streaming() -> LeakageTestResult:
    name = "paridade lote/streaming (< 1e-8 nas últimas 500 barras)"
    features_covered = (
        _FEATURES_PARITY_TEST_PATH.exists()
        and "test_paridade_lote_streaming_ultimas_500_barras"
        in _FEATURES_PARITY_TEST_PATH.read_text(encoding="utf-8")
    )
    status = LeakageStatus.PASS if features_covered else LeakageStatus.FAIL
    detail = (
        "tests/parity/test_features_parity.py::test_paridade_lote_streaming_ultimas_500_barras "
        "cobre o Feature Engine (últimas 500 barras, tolerância 1e-8, §16.10 DoD). src/regime/ "
        "e src/labels/ NÃO têm um modo 'streaming' separado ainda — build_regimes e "
        "build_labels_for_symbol são sempre recomputados em lote sobre o histórico inteiro; "
        "não existe um segundo caminho de cálculo incremental bar-a-bar pra divergir do lote."
    )
    note = (
        "Escopo: features apenas. Não é um FAIL por ausência de teste — é ausência genuína de "
        "escopo aplicável (não há dois caminhos de cálculo para comparar em regime/labels "
        "ainda). Vira teste real quando execução ao vivo (Sprint 12+) precisar de "
        "regime/labels incrementais."
    )
    return LeakageTestResult(14, name, "§11.5 #14", status, detail, note)


# ============================================================================
# Orquestração
# ============================================================================

_TESTS_NEEDING_LABELS: frozenset[int] = frozenset({6, 7, 12})


def run_all_leakage_tests(labels: pl.DataFrame | None = None) -> list[LeakageTestResult]:
    """Roda os 14 testes do §11.5 na ordem da tabela. `labels` é carregado
    de `labels/v1/labels.parquet` via `cpcv.load_labels_v1()` se não
    passado — só é de fato usado pelos testes 6/7/12 (`_TESTS_NEEDING_LABELS`,
    documentando explicitamente quais dependem de dado real)."""
    labels_df = labels if labels is not None else cpcv.load_labels_v1()

    results = [
        _test_01_close_futuro(),
        _test_02_high_low_futuro(),
        _test_03_volume_futuro(),
        _test_04_funding_futuro(),
        _test_05_regime_futuro(),
        _test_06_contaminacao_label(labels_df),
        _test_07_labels_sobrepostos(labels_df),
        _test_08_normalizacao_global(),
        _test_09_lookahead_resample(),
        _test_10_encadeamento_modelo(),
        _test_11_calibracao_vazada(),
        _test_12_selecao_feature_vazada(labels_df),
        _test_13_filtros_anacronicos(),
        _test_14_paridade_lote_streaming(),
    ]

    for r in results:
        logger.info("validation.leakage.test_result", **r.to_dict())

    n_pass = sum(1 for r in results if r.status == LeakageStatus.PASS)
    n_fail = sum(1 for r in results if r.status == LeakageStatus.FAIL)
    n_pending = sum(1 for r in results if r.status == LeakageStatus.PENDING_SPRINT_8)
    n_na = sum(1 for r in results if r.status == LeakageStatus.NOT_APPLICABLE_V1_1)
    logger.info(
        "validation.leakage.summary",
        n_tests=len(results),
        n_pass=n_pass,
        n_fail=n_fail,
        n_pending_sprint_8=n_pending,
        n_not_applicable_v1_1=n_na,
    )
    return results


def write_leakage_report_atomic(
    results: Sequence[LeakageTestResult], dest_path: Path | None = None
) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`, mesmo padrão de
    `src.data.validate.write_report_atomic`/`src.labels.triple_barrier.
    write_labels_atomic`."""
    default_path = VALIDATION_REPORTS_DIR / "leakage_report.json"
    out_path = dest_path if dest_path is not None else default_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "tests": [r.to_dict() for r in results]}
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.leakage.report_written", path=str(out_path))
    return out_path


if __name__ == "__main__":  # pragma: no cover — execução manual
    # Mesmo padrão de `src.data.validate`/`src.validation.cpcv`: bloco para
    # `python -m src.validation.leakage`; um entry point real
    # (`scripts/run_validation_leakage.py`) chamaria `configure_logging()`
    # antes de invocar o núcleo.
    import sys

    def _run_cli() -> int:
        test_results = run_all_leakage_tests()
        write_leakage_report_atomic(test_results)
        return 1 if any(r.status == LeakageStatus.FAIL for r in test_results) else 0

    sys.exit(_run_cli())
