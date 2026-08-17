"""Testes de `src/features/build.py` — invariantes §2.15 do PRD que operam
sobre o vetor T1 inteiro (não uma feature isolada): determinismo (1),
warmup uniforme (5) e ortogonalidade de T1 (6). Também valida
`src/features/registry.yaml` contra o formato §2.14 e contra o conjunto
real de features implementadas.

`test_t1_ortogonalidade_spearman_2anos` é o teste mais caro (roda sobre
~2 anos de dado real, dezenas de milhares de barras de 15m) — reporta a
matriz completa via `-s`/log em caso de violação, não só falha muda."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from src.data._paths import CAPACITY_DIR
from src.features import build

_FIXTURE_START = "2024-01-01"
_FIXTURE_END = "2024-02-10"  # 41 dias -> 3936 barras de 15m, >> 200 de warmup

_CORR_START = "2024-08-08"
_CORR_END = "2026-08-07"  # ~2 anos, janela pedida pela task para ortogonalidade real


def _skip_if_missing(day: str) -> None:
    path = CAPACITY_DIR / "klines_1m" / "BTCUSDT" / f"{day}.parquet"
    if not path.exists():
        pytest.skip(f"fixture ausente no backfill local: {path}")


# ============================================================================
# 1. Determinismo
# ============================================================================


@pytest.mark.integration
def test_determinismo_bit_a_bit() -> None:
    _skip_if_missing(_FIXTURE_START)
    out1 = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    out2 = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    assert out1.equals(out2, null_equal=True)


@pytest.mark.integration
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


@pytest.mark.integration
def test_warmup_uniforme_todas_nulas_antes_do_corte() -> None:
    """`warmup=200` -- `min_warmup_bars` recalculado por fórmula (AG-027,
    2026-08-15, `config/constants.yaml`), não mais os 2000 herdados do PRD
    sem justificativa. Este teste nunca tinha sido re-rodado desde essa
    mudança (achado real via pytest do usuário, 2026-08-16) -- ficou
    hardcoded no valor antigo por uma sessão inteira sem ninguém notar."""
    _skip_if_missing(_FIXTURE_START)
    out = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    warmup = 200
    assert out.height > warmup
    feature_cols = [c for c in out.columns if c not in ("open_time", "close_time")]
    head = out.head(warmup).select(feature_cols)
    for col in feature_cols:
        assert head[col].null_count() == warmup, f"{col} tem valor não-null antes do warmup"


@pytest.mark.integration
def test_warmup_uniforme_maioria_valida_depois_do_corte() -> None:
    """Depois do warmup, a esmagadora maioria das linhas deve ter todas as
    features T1 válidas — algumas poucas exceções pontuais são esperadas e
    documentadas (ex.: gap real de 45min com volume=0 em 2024-10-28,
    blips de sum_open_interest<=0 em metrics — ver relatório do Sprint 4),
    mas não devem dominar a amostra."""
    _skip_if_missing(_FIXTURE_START)
    out = build.build_t1_features("BTCUSDT", _FIXTURE_START, _FIXTURE_END)
    tail = out.tail(out.height - 200)  # min_warmup_bars real, ver AG-027
    t1_cols = list(build.T1_FEATURE_IDS)
    n_fully_valid = tail.select(t1_cols).drop_nulls().height
    assert n_fully_valid / tail.height > 0.95


def test_feature_windows_min_common_history_bars_from_constants() -> None:
    """AG-030 (T0.5): min_common_history_bars_15m, config/constants.yaml --
    ~164.256 barras de 15m = histórico comum mínimo entre os 5 ativos
    (2021-12-01 -> 2026-08-07, teto do alt mais novo; ver AG-030 no
    architecture_gaps_log.yaml e o comentário da constante)."""
    windows = build.FeatureWindows.from_constants()
    assert windows.min_common_history_bars == 164256


def test_compute_t1_features_min_common_history_bars_capa_c07_d03f_e02f() -> None:
    """AG-030 (T0.5): com um cap menor que `n`, as primeiras `n - cap`
    barras de C07/D03f/E02f ficam nulas (janela expansiva recomeça no novo
    "início") -- as outras 9 colunas T1/T2 não são afetadas (não usam
    `min_common_history_bars`), provado comparando byte-a-byte contra uma
    rodada sem cap (`windows` default de `from_constants()`).

    `n=200`/`cap=100` (não um par pequeno tipo 40/15): `C07` depende de
    `realized_vol(window=48)` computada ANTES do posto expansivo -- com
    `n` pequeno essa janela de 48 barras nem teria convergido ainda,
    contaminando o teste (toda a coluna já sairia NaN mesmo sem cap nenhum,
    e o teste "passaria" sem provar nada sobre o mecanismo do AG-030).
    `offset = n - cap = 100 > 48` garante que a janela de 48 já convergiu
    bem antes do ponto de corte do cap."""
    n = 200
    cap = 100
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(83)
    # variância real de propósito (não constante) -- E02f é z-score expansivo
    # de Welford, que fica NaN o tempo todo (var==0) sobre série constante,
    # o que mascararia o efeito do cap sendo testado aqui.
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)

    windows_sem_cap = build.FeatureWindows.from_constants()
    windows_com_cap = dataclasses.replace(windows_sem_cap, min_common_history_bars=cap)

    out_sem_cap = build.compute_t1_features(
        bars, funding, oi, windows=windows_sem_cap, apply_warmup_mask=False
    )
    out_com_cap = build.compute_t1_features(
        bars, funding, oi, windows=windows_com_cap, apply_warmup_mask=False
    )

    # `apply_warmup_mask=False` -- os arrays numpy (com `np.nan`, não Polars
    # `None`) entram direto em `pl.DataFrame(columns)` sem passar por
    # `apply_min_warmup_mask` (que é quem converteria pra `null` explícito
    # via `pl.when(...).then(None)`). `.null_count()` NÃO conta `NaN` --
    # são conceitos diferentes em Polars (achado real via pytest do
    # usuário, 2026-08-16: a asserção original dava 0 sempre, mesmo com o
    # mecanismo de cap funcionando corretamente). `.is_nan()` é o jeito
    # certo de checar aqui.
    for col in ("C07_vol_pctile_expanding", "D03f_volume_z_expanding", "E02f_funding_z_expanding"):
        head_nan_count = out_com_cap.head(n - cap)[col].is_nan().sum()
        assert head_nan_count == n - cap, f"{col}: esperava {n - cap} NaN no início do cap"
        # sem cap, o mesmo trecho inicial NÃO deve estar 100% NaN (prova
        # de que o cap muda o resultado, não é um no-op)
        assert out_sem_cap.head(n - cap)[col].is_nan().sum() < n - cap

    # todas as outras colunas T1/T2 (não usam min_common_history_bars) têm
    # que sair IDÊNTICAS com ou sem cap -- prova de isolamento do efeito
    cols_afetadas = {
        "C07_vol_pctile_expanding",
        "D03f_volume_z_expanding",
        "E02f_funding_z_expanding",
    }
    outros_cols = [c for c in build.ALL_OUTPUT_COLUMNS if c not in cols_afetadas]
    assert out_sem_cap.select(outros_cols).equals(out_com_cap.select(outros_cols), null_equal=True)


def _make_synthetic_bars_for_cap_test(n: int) -> pl.DataFrame:
    rng = np.random.default_rng(81)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.5, n)
    volume = rng.uniform(10, 100, n)
    taker_buy_volume = volume * rng.uniform(0.3, 0.7, n)
    open_time = np.arange(n, dtype=np.int64) * 900_000
    close_time = open_time + 899_999
    return pl.DataFrame(
        {
            "open_time": open_time,
            "close_time": close_time,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "taker_buy_volume": taker_buy_volume,
        }
    )


# ============================================================================
# vol_estimator_id — C01 sob Parkinson (2026-08-17, Fase 2, AG-036/065/074)
# ============================================================================


def test_compute_t1_features_vol_estimator_id_none_e_atr_wilder_explicito_sao_bit_exatos() -> None:
    """`vol_estimator_id=None` (default) e o id explícito equivalente
    (`f"atr_wilder_w{atr_window}"`) têm que produzir o MESMO resultado --
    o id explícito existe pra simetria com o caminho Parkinson, não pra
    mudar comportamento."""
    n = 200
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(71)
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)
    windows = build.FeatureWindows.from_constants()

    out_default = build.compute_t1_features(
        bars, funding, oi, windows=windows, apply_warmup_mask=False
    )
    out_explicito = build.compute_t1_features(
        bars,
        funding,
        oi,
        windows=windows,
        apply_warmup_mask=False,
        vol_estimator_id=f"atr_wilder_w{windows.atr_window}",
    )
    assert out_default.equals(out_explicito, null_equal=True)


def test_compute_t1_features_vol_estimator_id_parkinson_muda_c01_preserva_resto() -> None:
    """`vol_estimator_id="parkinson_w{N}"` muda C01_atr_20 (e, por herança,
    C02/A05/A13/E27f -- todas dependem de `atr_20_abs`/`atr_20_pct`), mas
    NÃO muda nenhuma outra coluna T1/T2 (B01, B07, C06, C07, D03f, D06f,
    E02f, E10f não dependem de C01)."""
    n = 200
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(72)
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)
    windows = build.FeatureWindows.from_constants()

    out_wilder = build.compute_t1_features(
        bars, funding, oi, windows=windows, apply_warmup_mask=False
    )
    out_parkinson = build.compute_t1_features(
        bars,
        funding,
        oi,
        windows=windows,
        apply_warmup_mask=False,
        vol_estimator_id=f"parkinson_w{windows.atr_window}",
    )

    cols_afetadas = {
        "C01_atr_20",
        "C02_atr_20_pct",
        "A05_ret_vol_norm_4",
        "A13_dist_ema48_atr",
        "E27f_cost_atr_ratio",
    }
    for col in cols_afetadas:
        valid = ~out_wilder[col].is_nan() & ~out_parkinson[col].is_nan()
        assert valid.sum() > 0
        assert not out_wilder[col].filter(valid).equals(out_parkinson[col].filter(valid)), col

    outros_cols = [c for c in build.ALL_OUTPUT_COLUMNS if c not in cols_afetadas]
    assert out_wilder.select(outros_cols).equals(
        out_parkinson.select(outros_cols), null_equal=True
    )


def test_compute_t1_features_vol_estimator_id_invalido_levanta_valueerror() -> None:
    n = 50
    bars = _make_synthetic_bars_for_cap_test(n)
    funding = pl.Series("f", [None] * n, dtype=pl.Float64)
    oi = pl.Series("oi", [None] * n, dtype=pl.Float64)
    with pytest.raises(ValueError, match="vol_estimator_id"):
        build.compute_t1_features(
            bars, funding, oi, apply_warmup_mask=False, vol_estimator_id="garman_klass_w20"
        )


def test_build_t1_features_desabilita_min_common_history_bars_sob_bar_source_nao_time15m(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fase 2 (2026-08-17), decisão registrada na docstring de
    `build_t1_features`: `min_common_history_bars_15m` (AG-030, calibrado
    em contagem de barra de TEMPO) não é comparável cross-asset sob dollar
    bar -- `build_t1_features` desabilita o cap
    (`windows.min_common_history_bars = None`) sempre que `bar_source !=
    "time_15m"`, em vez de herdar o número silenciosamente. Monkeypatch de
    IO (`_sources.load_bars`/etc.) e de `FeatureWindows.from_constants`
    (cap pequeno o bastante pra ser observável em `n=200`) -- não depende
    de backfill local nem é `integration`."""
    n = 200
    cap = 100
    bars = _make_synthetic_bars_for_cap_test(n)
    rng = np.random.default_rng(73)
    funding = pl.Series("f", rng.normal(0.0001, 0.0002, n), dtype=pl.Float64)
    oi = pl.Series("oi", 90_000.0 + np.cumsum(rng.normal(0, 200, n)), dtype=pl.Float64)

    windows_com_cap = dataclasses.replace(
        build.FeatureWindows.from_constants(), min_common_history_bars=cap
    )
    monkeypatch.setattr(
        build.FeatureWindows, "from_constants", staticmethod(lambda: windows_com_cap)
    )
    monkeypatch.setattr(build._sources, "load_bars", lambda *a, **k: bars)
    monkeypatch.setattr(build._sources, "load_funding_aligned", lambda *a, **k: funding)
    monkeypatch.setattr(build._sources, "load_oi_aligned", lambda *a, **k: oi)

    out_time15m = build.build_t1_features(
        "BTCUSDT", "2024-01-01", "2024-01-01", apply_warmup_mask=False, bar_source="time_15m"
    )
    out_dollar = build.build_t1_features(
        "BTCUSDT", "2024-01-01", "2024-01-01", apply_warmup_mask=False, bar_source="dollar_r1"
    )

    for col in ("C07_vol_pctile_expanding", "D03f_volume_z_expanding", "E02f_funding_z_expanding"):
        assert out_time15m.head(n - cap)[col].is_nan().sum() == n - cap, col
        assert out_dollar.head(n - cap)[col].is_nan().sum() < n - cap, col


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


@pytest.mark.integration
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
