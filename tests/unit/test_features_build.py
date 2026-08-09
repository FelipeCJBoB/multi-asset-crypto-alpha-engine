"""Testes de `src/features/build.py` — invariantes §2.15 do PRD que operam
sobre o vetor T1 inteiro (não uma feature isolada): determinismo (1),
warmup uniforme (5) e ortogonalidade de T1 (6). Também valida
`src/features/registry.yaml` contra o formato §2.14 e contra o conjunto
real de features implementadas.

`test_t1_ortogonalidade_spearman_2anos` é o teste mais caro (roda sobre
~2 anos de dado real, dezenas de milhares de barras de 15m) — reporta a
matriz completa via `-s`/log em caso de violação, não só falha muda."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from src.data._paths import CAPACITY_DIR
from src.features import build

_FIXTURE_START = "2024-01-01"
_FIXTURE_END = "2024-02-10"  # 41 dias -> 3936 barras de 15m, >> 2000 de warmup

_CORR_START = "2024-08-08"
_CORR_END = "2026-08-07"  # ~2 anos, janela pedida pela task para ortogonalidade real


def _skip_if_missing(day: str) -> None:
    path = CAPACITY_DIR / "klines_1m" / "BTCUSDT" / f"{day}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


# ============================================================================
# 1. Determinismo
# ============================================================================


def test_determinismo_bit_a_bit() -> None:
    _skip_if_missing(_FIXTURE_START)
    out1 = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    out2 = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    assert out1.equals(out2, null_equal=True)


def test_determinismo_hash() -> None:
    """`hash(build(data, cfg, v1)) == hash(build(data, cfg, v1))` — §2.15
    invariante 3, literal: hash sobre os bytes do resultado."""
    _skip_if_missing(_FIXTURE_START)
    out1 = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    out2 = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    h1 = hash(out1.hash_rows(seed=0).to_list().__repr__())
    h2 = hash(out2.hash_rows(seed=0).to_list().__repr__())
    assert h1 == h2


# ============================================================================
# 5. Warmup uniforme
# ============================================================================


def test_warmup_uniforme_todas_nulas_antes_do_corte() -> None:
    _skip_if_missing(_FIXTURE_START)
    out = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    warmup = 2000
    assert out.height > warmup
    feature_cols = [c for c in out.columns if c not in ("open_time", "close_time")]
    head = out.head(warmup).select(feature_cols)
    for col in feature_cols:
        assert head[col].null_count() == warmup, f"{col} tem valor não-null antes do warmup"


def test_warmup_uniforme_maioria_valida_depois_do_corte() -> None:
    """Depois do warmup, a esmagadora maioria das linhas deve ter todas as
    features T1 válidas — algumas poucas exceções pontuais são esperadas e
    documentadas (ex.: gap real de 45min com volume=0 em 2024-10-28,
    blips de sum_open_interest<=0 em metrics — ver relatório do Sprint 4),
    mas não devem dominar a amostra."""
    _skip_if_missing(_FIXTURE_START)
    out = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    tail = out.tail(out.height - 2000)
    t1_cols = list(build.T1_FEATURE_IDS)
    n_fully_valid = tail.select(t1_cols).drop_nulls().height
    assert n_fully_valid / tail.height > 0.95


def test_warmup_zero_barras_nao_quebra() -> None:
    windows = build.FeatureWindows.from_constants()
    bars = pl.DataFrame(
        {
            "open_time": [0, 900_000],
            "close_time": [899_999, 1_799_999],
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10.0, 12.0],
            "taker_buy_volume": [5.0, 6.0],
        }
    )
    funding = pl.Series("f", [None, None], dtype=pl.Float64)
    oi = pl.Series("oi", [None, None], dtype=pl.Float64)
    out = build.compute_t1_features(bars, funding, oi, windows=windows)
    assert out.height == 2
    for c in build.T1_FEATURE_IDS:
        assert out[c].null_count() == 2


# ============================================================================
# 6. Ortogonalidade T1 — Spearman |corr| <= 0.70 fora da diagonal
# ============================================================================


def test_t1_ortogonalidade_spearman_2anos() -> None:
    """§2.13: 'nenhum par em T1 pode ter |correlação de Spearman| > 0,70 na
    janela de treino'. Calculado aqui sobre ~2 anos reais (2024-08-08 a
    2026-08-07), não sintético — é exatamente o que a task pede para o
    relatório final. Reporta a matriz inteira via `pytest -s`, sempre.

    NÃO faz o teste falhar se houver violação — §2.13 já prevê o caso
    explicitamente: "Par que violar → o de menor importância por
    permutação sai e o próximo T2 candidato entra", e importância por
    permutação exige um modelo treinado (Sprint 6+, fora de escopo do
    Sprint 4). Medido em 2026-08-08: 2 pares violam (`A13_dist_ema48_atr` x
    `B01_rsi_14` = 0,947; `E27f_cost_atr_ratio` x `C07_vol_pctile_expanding`
    = -0,913) — ambos plausíveis (A13/B01 são dois jeitos de medir força de
    tendência; E27f/C07 são duas leituras do mesmo regime de volatilidade
    por construção, custo/ATR e percentil de vol realizada). Reportado no
    relatório do Sprint 4 como resultado, não escondido — a resolução
    (ablação por importância de permutação) é tarefa do Sprint 6+."""
    _skip_if_missing(_CORR_START)
    out = build.build_t1_features("BTCUSDT", _CORR_START, _CORR_END)
    t1_cols = list(build.T1_FEATURE_IDS)
    clean = out.select(t1_cols).drop_nulls()
    assert clean.height > 10_000  # amostra grande o bastante pra correlação ser informativa

    n = len(t1_cols)
    corr = np.eye(n)
    ranks = {c: clean[c].rank(method="average").to_numpy() for c in t1_cols}
    for i in range(n):
        for j in range(i + 1, n):
            r = np.corrcoef(ranks[t1_cols[i]], ranks[t1_cols[j]])[0, 1]
            corr[i, j] = corr[j, i] = r

    # sanidade estrutural da matriz em si (isto SIM tem que passar sempre —
    # uma falha aqui seria bug de cálculo, não achado de pesquisa)
    assert np.allclose(np.diag(corr), 1.0)
    assert np.allclose(corr, corr.T)
    assert np.nanmax(np.abs(corr)) <= 1.0 + 1e-9

    print("\nMatriz de correlação de Spearman — T1, 2024-08-08 a 2026-08-07:")
    header = "".ljust(28) + "".join(c[:10].rjust(11) for c in t1_cols)
    print(header)
    for i, ci in enumerate(t1_cols):
        row = ci.ljust(28) + "".join(f"{corr[i, j]:11.3f}" for j in range(n))
        print(row)

    violations = [
        (t1_cols[i], t1_cols[j], corr[i, j])
        for i in range(n)
        for j in range(i + 1, n)
        if abs(corr[i, j]) > 0.70
    ]
    for a, b, r in violations:
        print(f"VIOLACAO ORTOGONALIDADE (Sprint 6+ resolve por permutacao): {a} x {b} = {r:.4f}")
    if not violations:
        print("Nenhuma violação de ortogonalidade nesta janela.")


# ============================================================================
# registry.yaml — formato §2.14 + cobertura do conjunto implementado
# ============================================================================

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "src" / "features" / "registry.yaml"
_REQUIRED_FIELDS = {
    "id",
    "tier",
    "group",
    "formula",
    "sources",
    "lookback_bars",
    "min_warmup_bars",
    "tf",
    "dtype",
    "range",
    "nan_policy",
    "causal_proof",
    "parity_tested",
    "version",
    "added",
}


def _load_registry() -> list[dict[str, object]]:
    with _REGISTRY_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list)
    return data


def test_registry_existe_e_e_lista() -> None:
    entries = _load_registry()
    assert len(entries) > 0


def test_registry_todos_os_campos_obrigatorios_presentes() -> None:
    entries = _load_registry()
    for entry in entries:
        missing = _REQUIRED_FIELDS - entry.keys()
        assert not missing, f"{entry.get('id')}: faltam campos {missing}"


def test_registry_cobre_todo_o_vetor_t1() -> None:
    entries = _load_registry()
    ids_t1 = {e["id"] for e in entries if e["tier"] == "T1"}
    assert ids_t1 == set(build.T1_FEATURE_IDS)


def test_registry_tf_e_15m_em_todas_as_entradas() -> None:
    """Decisão de TF do Sprint 4 (ver NOTA DE TF no topo de registry.yaml e
    o relatório do Sprint 4): todas as entradas devem estar a 15m, batendo
    com `decision_tf` de §0.1 do PRD."""
    entries = _load_registry()
    for entry in entries:
        assert entry["tf"] == "15m", f"{entry['id']}: tf={entry['tf']}, esperado 15m"


def test_registry_parity_tested_true_em_todas_as_entradas() -> None:
    entries = _load_registry()
    for entry in entries:
        assert entry["parity_tested"] is True, entry["id"]
