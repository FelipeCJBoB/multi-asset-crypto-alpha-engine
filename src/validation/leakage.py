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
write_labels_atomic`. Achado F5 (candidato a AG-131, auditoria
2026-08-19): `write_leakage_report_atomic`/`write_correlation_scan_report_
atomic` agora mesclam `src.core.provenance.report_provenance()`
(`generated_at`/`code_version`) no payload — mesma convenção já em ~25
módulos de `src/analysis/`/`src/backtest/` (ex.
`src.analysis.m4_regime_comparison`), que este módulo não seguia até
agora.

**`scan_feature_target_correlation` — scan estatístico, não um 15º teste
numerado.** Auditoria de um projeto irmão (Laplace_Quant_V16, 2026-08-09)
trouxe um padrão que os 14 testes de §11.5 não cobrem: correlação Spearman
de CADA feature contra o target, com threshold Bonferroni-corrigido pelo
número de features — pega erro de IMPLEMENTAÇÃO (off-by-one num `.shift()`,
janela errada) que a prova textual `causal_proof` do registry não pega,
porque essa prova documenta a INTENÇÃO causal, não verifica o resultado
numérico. Não entra na lista de 14 (sem âncora §11.5 própria — registrado
em `constants.yaml` + nota do PRD) e **não é um gate binário PASS/FAIL
como os outros 14**: uma checagem MEDIDA nesta mesma auditoria mostrou que
o threshold Bonferroni ingênuo (cópia direta da fonte) marca 4 das 10
features T1 como suspeitas — todas com prova causal já verificada, porque
o Label Engine escala TP/SL por ATR e várias T1 derivam de volatilidade,
criando correlação ESTRUTURAL genuína (não vazamento) com a geometria do
label. Por isso o scan reporta dois campos por feature: `elevated`
(informativo, threshold Bonferroni) e `hard_fail` (bloqueante, threshold
bem mais conservador, calibrado pelo maior |rho| causal já medido — ver
`constants.yaml::feature_leakage_hard_fail_threshold`)."""

from __future__ import annotations

import math
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
from scipy.stats import spearmanr

from src.core.provenance import report_provenance
from src.features import build as features_build
from src.features import registry as features_registry
from src.regime import classifier as regime_classifier
from src.regime import stress as regime_stress

from . import cpcv
from ._constants import load_constant
from ._paths import CONSTANTS_PATH, REPO_ROOT, VALIDATION_REPORTS_DIR

logger = structlog.get_logger(__name__)

IntArray = NDArray[np.int64]

_SRC_ROOT: Path = REPO_ROOT / "src"
_TRIPLE_BARRIER_PATH: Path = _SRC_ROOT / "labels" / "triple_barrier.py"
_ALPHA_PATH: Path = _SRC_ROOT / "models" / "alpha.py"
#: F7 (D-13, §10.3 do design doc do Meta, 2026-09-01) — não existia em
#: lugar nenhum do código até esta correção; teste #11 passa a auditar
#: `meta.py` além de `alpha.py`.
_META_PATH: Path = _SRC_ROOT / "models" / "meta.py"
_META_DATASET_PATH: Path = _SRC_ROOT / "models" / "meta_dataset.py"
_META_DATASET_TEST_PATH: Path = REPO_ROOT / "tests" / "unit" / "test_models_meta_dataset.py"
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
    dedicado por desenho).

    AG-032 item 8 (Fix B, 2026-08-21) — antes desta correção, este módulo
    tinha um parsing ad hoc duplicado de `registry.yaml` (`_load_feature_
    registry`, dict cru sem validação de schema). Agora usa `src.features.
    registry.feature_registry_by_id` (leitor typed, valida campo a campo)
    — mesma lógica, uma única implementação."""
    entries = features_registry.feature_registry_by_id()
    problems: list[str] = []
    evidence: list[str] = []
    for fid in feature_ids:
        entry = entries.get(fid)
        if entry is None:
            problems.append(f"{fid}: ausente do registry.yaml")
            continue
        causal_proof = entry.causal_proof
        if not causal_proof:
            problems.append(f"{fid}: causal_proof vazio")
            continue
        if entry.parity_tested is not True:
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


def _test_06_contaminacao_label(
    labels: pl.DataFrame, *, config: cpcv.CPCVConfig | None = None, symbol: str | None = None
) -> LeakageTestResult:
    name = "contaminação de label (t1 de treino nunca cruza janela de teste)"
    try:
        result = cpcv.generate_splits(labels, config=config, symbol=symbol)
        cpcv.assert_no_train_t1_leaks_into_test(labels, result)
    except (AssertionError, cpcv.CPCVError, ValueError) as exc:
        # `cpcv.CPCVError` (2026-08-17, Fase 4) -- achado ao abrir este
        # teste pra grade dollar-bar: `generate_splits`/`assert_grade_
        # consistent` levantam `CPCVError`, não `AssertionError`, em
        # qualquer divergência de grade (config vs. _calibration.json real,
        # AG-042). Só capturar `AssertionError` deixava esse caso escapar
        # como exceção não tratada, derrubando `run_all_leakage_tests`
        # inteiro em vez de reportar FAIL com detalhe -- contrário ao
        # desenho do módulo (sentinela explícito, nunca crash silencioso).
        # `ValueError` incluído (achado de auditoria, 2026-08-17):
        # `assert_grade_consistent` levanta `ValueError` explícito (não
        # `CPCVError`) quando `grade_id` é dollar-bar e `symbol=None`.
        return LeakageTestResult(6, name, "§11.5 #6", LeakageStatus.FAIL, str(exc))

    summary = cpcv.summarize_splits(result)
    total_purged = int(summary["n_purged"].sum())
    total_embargoed = int(summary["n_embargoed"].sum())
    # n_splits >= n_groups >= 2 por CPCVConfig.__post_init__, nunca <= 0
    avg_purged_per_split = round(total_purged / result.config.n_splits)  # noqa: unguarded-ratio
    detail = (
        f"CPCV real sobre labels/v1/labels.parquet ({labels.height} linhas): "
        f"{result.config.n_splits} splits combinatórios, {result.config.n_backtest_paths} "
        f"caminhos de backtest, {total_purged} linha(s)-split purgada(s) no total "
        f"({avg_purged_per_split} em média por split), "
        f"{total_embargoed} linha(s)-split em janela de embargo. "
        "assert_no_train_t1_leaks_into_test passou nos "
        f"{result.config.n_splits} splits — ZERO t1 de treino cruza qualquer janela de teste."
    )
    return LeakageTestResult(6, name, "§11.5 #6", LeakageStatus.PASS, detail)


def _test_07_labels_sobrepostos(
    labels: pl.DataFrame, *, config: cpcv.CPCVConfig | None = None, symbol: str | None = None
) -> LeakageTestResult:
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

    try:
        result = cpcv.generate_splits(labels, config=config, symbol=symbol)
    except (AssertionError, cpcv.CPCVError, ValueError) as exc:
        # Fase 4 (2026-08-17) achou este gap em _test_06 -- achado de
        # auditoria (audit_engineering, 2026-08-17) confirmou que _test_07
        # e _test_12 tinham o MESMO risco (mesmo config/symbol, mesma
        # generate_splits) sem a mesma proteção -- corrigido nos 3 juntos.
        # ValueError incluído: assert_grade_consistent levanta ValueError
        # (não CPCVError) quando grade dollar-bar e symbol=None.
        return LeakageTestResult(7, name, "§11.5 #7", LeakageStatus.FAIL, str(exc))
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
    """F7 (D-13, §10.2 do design doc do Meta, 2026-09-01) — sai de
    `NOT_APPLICABLE_V1_1`: o Meta ganhou escopo real nesta sessão (F0-F6b
    implementados, `PLANO_MESTRE_PRINCE2.md` §15.19+). Camada 1
    (`meta_dataset.assert_no_meta_leakage`, as 4 asserções falsificáveis
    do §10.1) já existe — auditoria estática confirma (a) presença das 4
    asserções no código-fonte E (b) o CONTROLE POSITIVO obrigatório do
    §10.2: um teste por asserção, construindo um frame que a viola e
    confirmando que o builder levanta `MetaLeakageError` — sem ele o
    teste não pode falhar e não prova nada, mesma crítica que este
    módulo já faz de si mesmo no teste 12."""
    name = "encadeamento de modelo (assert_no_meta_leakage roda de verdade, com controle positivo)"
    if not _META_DATASET_PATH.exists():
        return LeakageTestResult(
            10, name, "§11.5 #10", LeakageStatus.FAIL, f"{_META_DATASET_PATH} não existe."
        )
    source = _META_DATASET_PATH.read_text(encoding="utf-8")
    has_assert_fn = "def assert_no_meta_leakage(" in source
    has_check_a = "§10.1(a)" in source
    has_check_b = "§10.1(b)" in source
    has_check_c = "§10.1(c)" in source
    has_check_d = "§10.1(d)" in source

    test_source = (
        _META_DATASET_TEST_PATH.read_text(encoding="utf-8")
        if _META_DATASET_TEST_PATH.exists()
        else ""
    )
    # Literais com barra invertida ESCAPADA de propósito: o texto real do
    # arquivo de teste contém `10\.1\(a\)` (regex de `pytest.raises(...,
    # match=r"...")`) — buscar o literal exato, não uma versão
    # desescapada, é o que confirma que É o mesmo `match=` que os testes
    # 8/13 já verificam contra referência real (não confiar no texto).
    positive_control_a = "10\\.1\\(a\\)" in test_source
    positive_control_b = "10\\.1\\(b\\)" in test_source
    positive_control_c = "10\\.1\\(c\\)" in test_source
    positive_control_d = "10\\.1\\(d\\)" in test_source

    ok = bool(
        has_assert_fn
        and has_check_a
        and has_check_b
        and has_check_c
        and has_check_d
        and positive_control_a
        and positive_control_b
        and positive_control_c
        and positive_control_d
    )
    status = LeakageStatus.PASS if ok else LeakageStatus.FAIL
    detail = (
        f"meta_dataset.assert_no_meta_leakage existe: {has_assert_fn}. As 4 asserções "
        f"falsificáveis do §10.1 estão presentes no código: (a) {has_check_a}, "
        f"(b) {has_check_b}, (c) {has_check_c}, (d) {has_check_d}. Controle positivo "
        f"obrigatório (§10.2) — 1 teste por asserção confirmando `MetaLeakageError`: "
        f"(a) {positive_control_a}, (b) {positive_control_b}, (c) {positive_control_c}, "
        f"(d) {positive_control_d}."
    )
    note = (
        "Auditoria estática (mesmo padrão dos testes 13/14) — confirma presença do "
        "mecanismo + do controle positivo por referência de código real, não reexecuta "
        "assert_no_meta_leakage contra artefato aqui (isso é tests/unit/"
        "test_models_meta_dataset.py, que já roda via pytest -m 'not slow', não via este "
        "runner). F7 fecha D-13/§10 do design doc do Meta — Camada 1 (runtime) e Camada 2 "
        "(este teste) prontas."
    )
    return LeakageTestResult(10, name, "§11.5 #10", status, detail, note)


def _test_11_calibracao_vazada() -> LeakageTestResult:
    """Sprint 8 implementou `src/models/alpha.py::fit_side_model` — este
    teste sai de `PENDING_SPRINT_8` para uma auditoria estática real (mesmo
    padrão do teste 13): confirma, no CÓDIGO FONTE, que o calibrador
    isotônico nunca vê o próprio OOF nem o teste do fold (B08).

    Duas propriedades verificadas, ambas necessárias:

    1. **Isolamento por construção** — `fit_side_model` recebe um único
       parâmetro de dado (`train_side_df`), sem nenhum parâmetro de
       teste/OOF — arquiteturalmente impossível vazar dado que a função
       nunca recebe (mesmo argumento do teste 12 para o "seletor
       fictício"). `run_fold` só chama `fit_side_model` com
       `train_long`/`train_short` (nunca `test_bars`).
    2. **Sub-split interno real** — o calibrador (`IsotonicRegression`) é
       ajustado sobre `X_calib`/`y_calib`/`w_calib`, que vêm de
       `_stratified_calib_split(y_all, ...)` aplicado ao PRÓPRIO
       `train_side_df` (nunca sobre `X_all` inteiro nem sobre o teste)."""
    if not _ALPHA_PATH.exists():
        return LeakageTestResult(
            11,
            "calibração vazada (calibrador ajustado em sub-split interno)",
            "§11.5 #11",
            LeakageStatus.PENDING_SPRINT_8,
            "src/models/alpha.py ainda não existe.",
            note="Reexecutar assim que src/models/alpha implementar o passo de calibração.",
        )

    source = _ALPHA_PATH.read_text(encoding="utf-8")

    def_match = re.search(r"def fit_side_model\(\s*train_side_df: pl\.DataFrame,", source)
    no_test_param = def_match is not None and not re.search(
        r"def fit_side_model\([^)]*\btest\w*\s*:", source, re.DOTALL
    )
    only_called_with_train = not _grep_source(
        re.compile(r"fit_side_model\(\s*test"), (_SRC_ROOT / "models",)
    )
    calib_split_from_train = bool(re.search(r"_stratified_calib_split\(\s*y_all,", source))
    # AG-312 -- o check era por STRING LITERAL exata e quebrou quando o peso
    # do calibrador virou politica (`w_calib` -> `w_calib_iso`). O guard
    # estava certo em disparar: renomear um argumento do calibrador e algo
    # que ele DEVE notar. Mas checar o literal amarra o teste a um nome, nao
    # a propriedade -- e a propriedade e que os TRES argumentos venham do
    # split de CALIBRACAO, nunca de `raw_train_all` nem do teste.
    # Passa a checar isso: score e alvo sao os do split de calibracao, e o
    # peso e um vetor indexado por `calib_idx` (qualquer politica de
    # AG-312), nunca `w_all`/`raw_train_all` crus.
    _calib_fit = re.search(
        r"calibrator\.fit\(\s*(\w+),\s*(\w+),\s*sample_weight=(\w+)\s*\)", source
    )
    calibrator_fits_on_calib_split = bool(
        _calib_fit
        and _calib_fit.group(1) == "raw_calib"
        and _calib_fit.group(2) == "y_calib"
        and _calib_fit.group(3).startswith("w_calib")
        # o peso do calibrador nunca pode ser o vetor de treino inteiro
        and _calib_fit.group(3) not in ("w_all", "w_fit")
        # e a politica `uniqueness` precisa fatiar por `calib_idx`, nao usar
        # `u_all` inteiro -- e o mesmo erro que `w_all` seria
        and (
            "w_calib_iso = u_all[calib_idx]" in source
            or "CALIB_WEIGHT_UNIQUENESS" not in source
        )
    )

    alpha_ok = bool(
        def_match
        and no_test_param
        and only_called_with_train
        and calib_split_from_train
        and calibrator_fits_on_calib_split
    )

    # F7 (§10.3) — extensão pro Meta. As 4 checagens de ARQUIVO acima
    # (def_match/no_test_param, calib_split_from_train,
    # calibrator_fits_on_calib_split — `only_called_with_train` já varre
    # `src/models/` inteiro, de graça, sem precisar de extensão) viram 3
    # propriedades no Meta, que não tem calibrador (D-07): (a) `LogitL2Meta.
    # fit` sem parâmetro de teste — mesma propriedade de def_match+no_test_
    # param; (b) `ScoreRankTransform.fit` (a normalização do Meta, análoga
    # ao scaler global do teste #8) ajustada só com dado de TREINO — mesma
    # propriedade de calib_split_from_train; (c) `resolve_tau_meta` (o
    # limiar de decisão do Meta, análogo ao calibrador do Alpha) derivado
    # só de `score_train`/`ret_net_train` — mesma propriedade de
    # calibrator_fits_on_calib_split.
    if not _META_PATH.exists():
        meta_ok = False
        meta_detail = f"{_META_PATH} não existe."
    else:
        meta_source = _META_PATH.read_text(encoding="utf-8")
        meta_fit_def_match = re.search(
            r"def fit\(\s*self,\s*X: FloatArray,\s*y: IntArray,\s*w: FloatArray\s*\)",
            meta_source,
        )
        meta_fit_no_test_param = meta_fit_def_match is not None and not re.search(
            r"def fit\([^)]*\btest\w*\s*:", meta_source, re.DOTALL
        )
        meta_rank_fit_from_train = bool(
            re.search(r"ScoreRankTransform\.fit\(\s*\n?\s*train\[", meta_source)
        )
        meta_tau_from_train = bool(
            re.search(r"resolve_tau_meta\(\s*score_train,\s*ret_net_train", meta_source)
        )
        meta_ok = bool(
            meta_fit_def_match
            and meta_fit_no_test_param
            and meta_rank_fit_from_train
            and meta_tau_from_train
        )
        meta_detail = (
            f"LogitL2Meta.fit(self, X, y, w) sem parâmetro de teste/OOF: "
            f"{meta_fit_def_match is not None and meta_fit_no_test_param}. "
            f"ScoreRankTransform.fit chamado só com dado de treino (train[...]): "
            f"{meta_rank_fit_from_train}. resolve_tau_meta chamado só com "
            f"score_train/ret_net_train (nunca score_test/ret_net_test): "
            f"{meta_tau_from_train}."
        )

    ok = alpha_ok and meta_ok
    status = LeakageStatus.PASS if ok else LeakageStatus.FAIL
    detail = (
        f"[alpha.py] fit_side_model(train_side_df: pl.DataFrame, ...) sem parâmetro de "
        f"teste/OOF: {def_match is not None and no_test_param}. Nenhuma chamada em "
        f"src/models/ passa dado de teste para fit_side_model: {only_called_with_train}. "
        f"Sub-split de calibração (_stratified_calib_split) aplicado a y_all (derivado de "
        f"train_side_df, não de X_all bruto nem do teste): {calib_split_from_train}. "
        f"IsotonicRegression.fit chamado com raw_calib/y_calib/w_calib* fatiado por "
        f"calib_idx, qualquer que seja a politica de peso de AG-312 (não raw_train_all "
        f"nem dado de teste): {calibrator_fits_on_calib_split}. [meta.py] {meta_detail}"
    )
    note = (
        "Auditoria estática do código-fonte (mesmo padrão do teste 13), não execução real "
        "sobre labels/v1/labels.parquet — a execução real (Sprint 8) já rodou via "
        "src.models.pipeline.run_layer1_sprint e produziu "
        "predictions/alpha/{alpha_c1_v1,alpha_c0_baseline_v1}/predictions.parquet, "
        "verificados em tests/unit/test_models_alpha.py (schema + invariantes §5.13). "
        "Extensão F7/§10.3 (2026-09-01): meta.py auditado com as mesmas 4 checagens, "
        "adaptadas — Meta não tem calibrador (D-07), então 'calibrador ajustado no "
        "sub-split' vira 'resolve_tau_meta derivado só do treino'."
    )
    name = "calibração vazada (calibrador/threshold ajustado em dado de treino, alpha.py + meta.py)"
    return LeakageTestResult(11, name, "§11.5 #11", status, detail, note)


def _test_12_selecao_feature_vazada(
    labels: pl.DataFrame, *, config: cpcv.CPCVConfig | None = None, symbol: str | None = None
) -> LeakageTestResult:
    name = "seleção de feature vazada (seleção dentro de cada fold)"
    try:
        result = cpcv.generate_splits(labels, config=config, symbol=symbol)
    except (AssertionError, cpcv.CPCVError, ValueError) as exc:
        # Mesma correção de _test_06/_test_07 (achado de auditoria,
        # 2026-08-17) -- mesmo config/symbol, mesma generate_splits, mesmo
        # risco de crash não tratado em divergência de grade.
        return LeakageTestResult(12, name, "§11.5 #12", LeakageStatus.FAIL, str(exc))
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


def run_all_leakage_tests(
    labels: pl.DataFrame | None = None,
    *,
    feature_ids: tuple[str, ...],
    symbol: str = "BTCUSDT",
    tf: str = "15m",
    resolution_id: str | None = None,
) -> list[LeakageTestResult]:
    """Roda os 14 testes do §11.5 na ordem da tabela.

    `feature_ids` (2026-08-26, `ADR-005 §13 v2 §13.1`/`AG-296`) —
    OBRIGATORIO, sem default, de proposito. Antes esta funcao chamava
    `compute_max_feature_lookback_ms(tf, resolution_id=...)` sem o
    conjunto, caindo no default de 7 features enquanto o treino real usa
    69: a suite de vazamento reportava PASS contra uma protecao de purge
    que NAO era a do pipeline que ela deveria auditar. Um default aqui
    reintroduziria exatamente esse defeito, entao nao existe default --
    quem chama declara sobre qual vetor esta afirmando ausencia de
    vazamento. `labels` é carregado
    de `labels/v1/labels.parquet` via `cpcv.load_labels_v1()` se não
    passado — só é de fato usado pelos testes 6/7/12 (`_TESTS_NEEDING_LABELS`,
    documentando explicitamente quais dependem de dado real).

    `symbol`/`tf`/`resolution_id` (2026-08-17, Fase 4 da migração
    Parkinson+dollar-bar, achado G6 da revisão `project_assurance`) — antes
    desta mudança, os testes 6/7/12 chamavam `cpcv.generate_splits(labels)`
    SEM `config`/`symbol`, sempre assumindo grade `"15m"` por baixo,
    independente de qual `labels` fosse de fato passado. Contra `labels`
    de grade de tempo isso é inofensivo (mesmo default de sempre); contra
    `labels` dollar-bar, `assert_grade_consistent` falharia alto (bom,
    não é vazamento silencioso) — mas o runner não tinha como rodar de
    verdade contra R1, que é exatamente o que a Fase 5 desta migração
    precisa antes de qualquer retreino real ser confiável (`CLAUDE.md`:
    "os 14 testes de vazamento precisam rodar de verdade contra R1").
    Defaults (`symbol="BTCUSDT"`, `tf="15m"`, `resolution_id=None`)
    preservam bit-exato todo caller existente — `load_labels_v1()` sem
    argumentos é idêntico a `load_labels_v1(symbol="BTCUSDT", tf="15m")`,
    e `CPCVConfig.from_constants(tf="15m", grade_id="15m")` é idêntico ao
    `config=None` implícito de antes. Quando `labels` é passado
    explicitamente pelo chamador (bypassa `load_labels_v1` aqui), `symbol`/
    `tf`/`resolution_id` continuam valendo só para construir o
    `CPCVConfig` dos testes 6/7/12 — é responsabilidade do chamador que
    `labels` de fato corresponda à grade declarada."""
    labels_df = (
        labels
        if labels is not None
        else cpcv.load_labels_v1(symbol=symbol, tf=tf, resolution_id=resolution_id)
    )
    grade_id = resolution_id if resolution_id is not None else tf
    # AG-032 item 8 (Fix A, 2026-08-21) -- mesmo helper compartilhado que
    # src.models.pipeline.run_layer1_sprint usa pra max_feature_lookback_ms
    # (componente 96, docstring de src.validation.cpcv). Corrigir só um dos
    # dois call-sites deixaria o leakage suite reportando PASS pros testes
    # 6/7/12 enquanto o pipeline real de treino usa proteção diferente --
    # mesma classe de risco que AG-009 já corrigiu pra _embargo_ms. Levanta
    # features_build.ExpandingFeatureLookbackError se o conjunto ativo
    # (T1_FEATURE_IDS) tiver feature com lookback_bars='expanding' no
    # registry -- hoje DISPARA (3 features expanding conhecidas); ver
    # docstring de features_build.assert_no_expanding_lookback_in_active_set.
    # D-02 (AG-159, docs/regime_feature_engine_design_doc_2026-08-23.md
    # §3) -- resolution_id propagado pra usar bar_duration_ms correto sob
    # dollar-bar (label_prefetch_p99_bar_duration_ms), não step_ms(tf).
    # models.pipeline.run_layer1_sprint precisa do MESMO resolution_id --
    # os dois call sites mudam juntos, senão a suíte de vazamento reporta
    # PASS falso sob R2/R3 enquanto o pipeline real usa proteção diferente.
    # ADR-005 §13 v2 §13.1 / AG-296 -- `feature_ids` explicito. Antes caia
    # no default de 7 features, entao a suite de vazamento reportava PASS
    # contra uma protecao que NAO era a do treino (69 features).
    max_feature_lookback_ms = features_build.compute_max_feature_lookback_ms(
        tf, feature_ids, resolution_id=resolution_id
    )
    cpcv_config = cpcv.CPCVConfig.from_constants(
        tf=tf, grade_id=grade_id, max_feature_lookback_ms=max_feature_lookback_ms
    )

    results = [
        _test_01_close_futuro(),
        _test_02_high_low_futuro(),
        _test_03_volume_futuro(),
        _test_04_funding_futuro(),
        _test_05_regime_futuro(),
        _test_06_contaminacao_label(labels_df, config=cpcv_config, symbol=symbol),
        _test_07_labels_sobrepostos(labels_df, config=cpcv_config, symbol=symbol),
        _test_08_normalizacao_global(),
        _test_09_lookahead_resample(),
        _test_10_encadeamento_modelo(),
        _test_11_calibracao_vazada(),
        _test_12_selecao_feature_vazada(labels_df, config=cpcv_config, symbol=symbol),
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
        symbol=symbol,
        tf=tf,
        resolution_id=resolution_id,
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
    payload = {
        **report_provenance(),
        "schema_version": 1,
        "tests": [r.to_dict() for r in results],
    }
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.leakage.report_written", path=str(out_path))
    return out_path


# ============================================================================
# Scan estatístico de leakage por correlação — complementar aos 14 testes,
# ver docstring do módulo.
# ============================================================================

_MIN_OBS_CORRELATION_SCAN = 3  # noqa: magic-number — mínimo matemático do spearmanr, não constante de domínio


@dataclass(frozen=True, slots=True)
class FeatureLeakageScanEntry:
    feature: str
    spearman_rho: float
    n: int
    bonferroni_threshold: float
    hard_fail_threshold: float
    elevated: bool
    hard_fail: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "spearman_rho": self.spearman_rho,
            "n": self.n,
            "bonferroni_threshold": self.bonferroni_threshold,
            "hard_fail_threshold": self.hard_fail_threshold,
            "elevated": self.elevated,
            "hard_fail": self.hard_fail,
        }


def scan_feature_target_correlation(
    df: pl.DataFrame,
    feature_ids: Sequence[str],
    *,
    target_col: str = "ret_net",
) -> list[FeatureLeakageScanEntry]:
    """Spearman(feature, `target_col`) por feature — `df` já deve estar
    restrito à população que faz sentido correlacionar (ex.: trades
    preenchidos, `barrier_hit != "NOFILL"`; NOFILL tem `ret_net == 0` por
    construção e diluiria o rho sem informação nova, mesmo cuidado de
    `src.analysis.attribution.confidence_deciles_by_side`). Não decide
    nada — `elevated`/`hard_fail` são dados calculados, quem chama decide
    o que fazer (ver docstring do módulo para a diferença entre os dois)."""
    if not feature_ids:
        raise ValueError("scan_feature_target_correlation: feature_ids vazio — nada para medir")
    if target_col not in df.columns:
        raise ValueError(f"scan_feature_target_correlation: target_col '{target_col}' ausente")

    bonferroni_factor = float(load_constant("feature_leakage_bonferroni_factor"))
    hard_fail_threshold = float(load_constant("feature_leakage_hard_fail_threshold"))
    n_total = df.height
    n_features = len(feature_ids)
    # max(n_total, 1) já clampa o denominador -- nunca <= 0
    bonferroni_ratio = bonferroni_factor / math.sqrt(max(n_total, 1))  # noqa: unguarded-ratio
    bonferroni_threshold = bonferroni_ratio * math.sqrt(n_features)

    y = df[target_col].to_numpy().astype(np.float64)
    entries: list[FeatureLeakageScanEntry] = []
    for feature in feature_ids:
        if feature not in df.columns:
            raise ValueError(f"scan_feature_target_correlation: feature '{feature}' ausente em df")
        x = df[feature].to_numpy().astype(np.float64)
        mask = np.isfinite(x) & np.isfinite(y)
        n_valid = int(mask.sum())
        if n_valid < _MIN_OBS_CORRELATION_SCAN or np.std(x[mask]) == 0.0 or np.std(y[mask]) == 0.0:
            entries.append(
                FeatureLeakageScanEntry(
                    feature,
                    float("nan"),
                    n_valid,
                    bonferroni_threshold,
                    hard_fail_threshold,
                    False,
                    False,
                )
            )
            continue
        rho, _p = spearmanr(x[mask], y[mask])
        rho = float(rho) if np.isfinite(rho) else float("nan")
        elevated = math.isfinite(rho) and abs(rho) > bonferroni_threshold
        hard_fail = math.isfinite(rho) and abs(rho) > hard_fail_threshold
        entries.append(
            FeatureLeakageScanEntry(
                feature,
                rho,
                n_valid,
                bonferroni_threshold,
                hard_fail_threshold,
                elevated,
                hard_fail,
            )
        )

    logger.info(
        "validation.leakage.correlation_scan",
        n_features=n_features,
        n_total=n_total,
        bonferroni_threshold=round(bonferroni_threshold, 6),
        hard_fail_threshold=hard_fail_threshold,
        n_elevated=sum(1 for e in entries if e.elevated),
        n_hard_fail=sum(1 for e in entries if e.hard_fail),
    )
    return entries


def write_correlation_scan_report_atomic(
    entries: Sequence[FeatureLeakageScanEntry], dest_path: Path | None = None
) -> Path:
    """B29 — mesmo padrão de `write_leakage_report_atomic`."""
    default_path = VALIDATION_REPORTS_DIR / "feature_leakage_scan_report.json"
    out_path = dest_path if dest_path is not None else default_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **report_provenance(),
        "schema_version": 1,
        "entries": [e.to_dict() for e in entries],
    }
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    blob = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
    with tmp_path.open("wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)
    logger.info("validation.leakage.correlation_scan_report_written", path=str(out_path))
    return out_path


if __name__ == "__main__":  # pragma: no cover — execução manual
    # Mesmo padrão de `src.data.validate`/`src.validation.cpcv`: bloco para
    # `python -m src.validation.leakage`; um entry point real
    # (`scripts/run_validation_leakage.py`) chamaria `configure_logging()`
    # antes de invocar o núcleo.
    import argparse
    import sys

    def _parse_args() -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description=(
                "Roda os 14 testes de vazamento (§11.5). Sem argumentos: "
                "comportamento identico ao de sempre (BTCUSDT, grade 15m, "
                "escreve em data/validation_reports/leakage_report.json)."
            )
        )
        parser.add_argument("--symbol", default="BTCUSDT")
        parser.add_argument(
            "--tf",
            default=None,
            help="grade de RELOGIO (ex. 15m) -- legada, substituida por dollar "
            "bar em AG-042. Passar isto exige intencao explicita (AG-248)",
        )
        parser.add_argument(
            "--resolution-id",
            default=None,
            help="grade dollar-bar (ex. R1) -- vence sobre --tf quando setado, "
            "mesmo desenho de UM parametro de grade das Fases 2-4",
        )
        return parser.parse_args()

    def _run_cli() -> int:
        # `resolution_id`/`tf`/`symbol` (2026-08-17, Fase 5 da migração
        # Parkinson+dollar-bar) -- antes desta mudança, run_all_leakage_
        # tests() era chamada SEM argumento nenhum aqui, sempre BTCUSDT/15m
        # -- não havia como rodar os 14 testes de verdade contra R1 pela
        # CLI (só via chamada Python direta). Defaults preservam bit-exato:
        # symbol="BTCUSDT"/tf="15m"/resolution_id=None reproduz a mesma
        # chamada de sempre, mesmo dest_path default.
        args = _parse_args()
        # `AG-248` -- a GRADE deixou de ter default. Antes, `--tf` caia em
        # "15m" e `--resolution-id` em None, entao `python -m
        # src.validation.leakage` sem flag nenhuma rodava os 14 testes contra
        # a grade de RELOGIO -- e, pior, era exatamente esse run que escrevia
        # no `leakage_report.json` CANONICO. O relatorio que o projeto cita
        # como garantia de ausencia de vazamento era, por construcao, o da
        # grade que deixou de ser producao em AG-042.
        if args.tf is None and args.resolution_id is None:
            raise SystemExit(
                "\n".join(
                    (
                        "src.validation.leakage exige a grade explicita (AG-248).",
                        "",
                        "  PRODUCAO -- dollar bar, grade canonica:",
                        "    uv run python -m src.validation.leakage "
                        f"--symbol {args.symbol} --resolution-id R1",
                        "",
                        "  GRADE LEGADA 15m -- so para comparacao historica:",
                        "    uv run python -m src.validation.leakage "
                        f"--symbol {args.symbol} --tf 15m",
                    )
                )
            )
        if args.tf is not None and args.resolution_id is not None:
            raise SystemExit(
                "src.validation.leakage: --tf e --resolution-id sao mutuamente "
                "exclusivos (XOR de grade). Passe um dos dois."
            )
        tf_efetivo = args.tf if args.tf is not None else "15m"
        # AG-296 -- o vetor de PRODUCAO e aditivo (T1 + T2, 69 features;
        # AG-207/AG-234 ratificados pelo Manager), nao os 7 T1. Declarado
        # aqui, no ponto de entrada, em vez de herdado de um default.
        feature_ids_producao = (
            features_build.T1_FEATURE_IDS + features_build.SUPPORT_FEATURE_IDS
        )
        test_results = run_all_leakage_tests(
            feature_ids=feature_ids_producao,
            symbol=args.symbol,
            tf=tf_efetivo,
            resolution_id=args.resolution_id,
        )
        grade = args.resolution_id if args.resolution_id is not None else args.tf
        # O `leakage_report.json` canonico passa a ser reservado a grade de
        # PRODUCAO. Rodar na grade de relogio nunca mais sobrescreve o
        # relatorio que o projeto cita como garantia.
        if args.resolution_id is None:
            logger.warning(
                "validation.leakage.grade_de_relogio_legada",
                grade=grade,
                detail=(
                    "os 14 testes rodaram contra a grade de RELOGIO, que nao e "
                    "producao desde AG-042. O relatorio vai para um arquivo "
                    "com sufixo -- o leakage_report.json canonico e reservado "
                    "a grade de producao (AG-248)."
                ),
            )
        dest_path = (
            None
            if args.symbol == "BTCUSDT" and args.resolution_id is not None
            else VALIDATION_REPORTS_DIR / f"leakage_report_{args.symbol}_{grade}.json"
        )
        write_leakage_report_atomic(test_results, dest_path=dest_path)
        return 1 if any(r.status == LeakageStatus.FAIL for r in test_results) else 0

    sys.exit(_run_cli())
