"""Testes de `src/analysis/calibration_diagnostics.py` — Faixa 1
(diagnóstico de calibração de confiança, regime DESCOBERTA). Mesmo padrão
de `test_analysis_attribution.py`: fixtures sintéticas com estrutura
conhecida por bloco (D1 perfil de decil, D2 estratificação, D3 NOFILL +
qui-quadrado, D4 score cru vs calibrado + plateau), mais integração real
(skip se artefato ausente)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from src.analysis import calibration_diagnostics as cd

_T0_DTYPE = pl.Datetime(time_unit="ms", time_zone="UTC")
_BASE = datetime(2024, 1, 1, tzinfo=UTC)


def _t0s(n: int, *, offset_days: int = 0) -> list[datetime]:
    return [_BASE + timedelta(days=offset_days + i) for i in range(n)]


def _pop_df(rows: list[dict[str, object]]) -> pl.DataFrame:
    """Schema de saída de `build_side_population` — usado para testar D1/
    D2/D3/D4 diretamente, sem passar pela junção (que tem seu próprio
    teste dedicado, `test_build_side_population_*`)."""
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=_T0_DTYPE),
            "fold_id": pl.Series([r.get("fold_id", 0) for r in rows], dtype=pl.Int16),
            "side_hat": pl.Series([r.get("side_hat", 1) for r in rows], dtype=pl.Int8),
            "confidence": pl.Series([r["confidence"] for r in rows], dtype=pl.Float64),
            "raw_score": pl.Series(
                [r.get("raw_score", r["confidence"]) for r in rows], dtype=pl.Float64
            ),
            "barrier_hit": pl.Series([r["barrier_hit"] for r in rows], dtype=pl.Utf8),
            "ret_net": pl.Series([r["ret_net"] for r in rows], dtype=pl.Float64),
            "regime": pl.Series([r.get("regime", "R1") for r in rows], dtype=pl.Utf8),
            cd.COST_FEATURE: pl.Series(
                [r.get(cd.COST_FEATURE, 0.5) for r in rows], dtype=pl.Float64
            ),
            cd.E02F_FEATURE: pl.Series(
                [r.get(cd.E02F_FEATURE, 0.0) for r in rows], dtype=pl.Float64
            ),
        }
    )


# ============================================================================
# D1 — decile_profile / _rank_correlations / _mean_excluding_decile
# ============================================================================


def test_decile_profile_conta_nofill_e_filled_separadamente() -> None:
    """10 decis, 2 linhas cada: uma preenchida (TP, bps=10*decil) e uma
    NOFILL. `n=2`, `n_filled=1` em todo decil (rates continuam observadas
    — `rate_nofill=0.5` é frequência, não estimativa); `n_filled=1 <
    FAIXA1_MIN_CELL_N` marca `insuficiente`, então `mean_ret_net_bps`/CI/
    t-stat saem `nan` — "não estimada", não um número pouco confiável."""
    t0s = _t0s(20)
    rows: list[dict[str, object]] = []
    for k in range(1, 11):
        conf_filled = 2.0 * (k - 1)
        conf_nofill = 2.0 * (k - 1) + 1.0
        rows.append(
            {
                "t0": t0s[2 * (k - 1)],
                "confidence": conf_filled,
                "barrier_hit": "TP",
                "ret_net": (10.0 * k) / 10_000.0,
            }
        )
        rows.append(
            {
                "t0": t0s[2 * (k - 1) + 1],
                "confidence": conf_nofill,
                "barrier_hit": "NOFILL",
                "ret_net": 0.0,
            }
        )
    df = _pop_df(rows)
    profile = cd.decile_profile(df)
    assert len(profile) == 10
    for cell in sorted(profile, key=lambda r: r["decile"]):
        assert cell["n"] == 2
        assert cell["n_filled"] == 1
        assert cell["rate_nofill"] == pytest.approx(0.5)
        assert cell["rate_tp"] == pytest.approx(0.5)
        assert cell["insufficient_n"] is True  # 1 < FAIXA1_MIN_CELL_N
        assert math.isnan(cell["mean_ret_net_bps"])  # "não estimada", não um valor pouco confiável
        assert math.isnan(cell["std_ret_net_bps"])
        assert math.isnan(cell["t_stat"])
        assert math.isnan(cell["ci95_low"])
        assert math.isnan(cell["ci95_high"])


def test_decile_profile_acima_do_minimo_estima_normalmente() -> None:
    """Contraste direto com o teste acima: `n_filled >= FAIXA1_MIN_CELL_N`
    -> `insufficient_n=False` e `mean_ret_net_bps` É reportado."""
    t0s = _t0s(cd.FAIXA1_MIN_CELL_N)
    rows = [
        {
            "t0": t0s[i],
            "confidence": float(i),
            "barrier_hit": "TP",
            "ret_net": 5.0 / 10_000.0,
        }
        for i in range(cd.FAIXA1_MIN_CELL_N)
    ]
    df = _pop_df(rows)
    profile = cd.decile_profile(df, n_deciles=1)
    cell = profile[0]
    assert cell["n_filled"] == cd.FAIXA1_MIN_CELL_N
    assert cell["insufficient_n"] is False
    assert cell["mean_ret_net_bps"] == pytest.approx(5.0)


def test_decile_profile_decil_vazio_marca_insuficiente_sem_quebrar() -> None:
    """3 trades, 10 decis pedidos -> 7 decis vazios (mesma convenção de
    `attribution._deciles_for_side`: não omitidos, `n=0`)."""
    t0s = _t0s(3)
    rows = [
        {"t0": t0s[i], "confidence": float(i), "barrier_hit": "TP", "ret_net": 0.001}
        for i in range(3)
    ]
    df = _pop_df(rows)
    profile = cd.decile_profile(df)
    assert len(profile) == 10
    empty = [r for r in profile if r["n"] == 0]
    assert len(empty) == 7
    assert all(r["insufficient_n"] for r in empty)
    assert all(math.isnan(r["mean_ret_net_bps"]) for r in empty)


def test_decile_profile_vazio_devolve_10_celulas_zeradas() -> None:
    profile = cd.decile_profile(_pop_df([]))
    assert len(profile) == 10
    assert all(r["n"] == 0 and r["insufficient_n"] for r in profile)


def test_rank_correlations_monotonico_crescente_da_rho_1() -> None:
    profile = [{"decile": d, "n_filled": 5, "mean_ret_net_bps": float(d)} for d in range(1, 11)]
    out = cd._rank_correlations(profile)
    assert out["spearman_rho"] == pytest.approx(1.0)
    assert out["kendall_tau"] == pytest.approx(1.0)
    # H1 "crescente" bate com o sinal medido -> p pequeno; H1 "decrescente" -> perto de 1
    assert out["monotonic_increasing_p"] < out["monotonic_decreasing_p"]
    assert out["monotonic_increasing_p"] == pytest.approx(out["spearman_p"] / 2.0)


def test_rank_correlations_monotonico_decrescente_da_rho_menos_1() -> None:
    profile = [
        {"decile": d, "n_filled": 5, "mean_ret_net_bps": float(11 - d)} for d in range(1, 11)
    ]
    out = cd._rank_correlations(profile)
    assert out["spearman_rho"] == pytest.approx(-1.0)
    assert out["monotonic_decreasing_p"] < out["monotonic_increasing_p"]


def test_rank_correlations_menos_de_3_decis_usaveis_marca_nan() -> None:
    profile = [
        {"decile": 1, "n_filled": 5, "mean_ret_net_bps": 1.0},
        {"decile": 2, "n_filled": 0, "mean_ret_net_bps": float("nan")},
    ]
    out = cd._rank_correlations(profile)
    assert math.isnan(out["spearman_rho"])
    assert out["n_usable_deciles"] == 1


def test_mean_excluding_decile_pooled_nao_media_das_medias() -> None:
    """3 decis com 1/2/1 trades preenchidos, bps [10]/[20,40]/[30] — média
    excluindo o decil 2 é pooled sobre {10,30} = 20, não a média das
    médias dos decis restantes (que também daria 20 aqui por coincidência
    — o teste força n desigual noutro excluding para desambiguar)."""
    t0s = _t0s(4)
    rows = [
        {"t0": t0s[0], "confidence": 0.0, "barrier_hit": "TP", "ret_net": 10.0 / 10_000.0},
        {"t0": t0s[1], "confidence": 1.0, "barrier_hit": "TP", "ret_net": 20.0 / 10_000.0},
        {"t0": t0s[2], "confidence": 2.0, "barrier_hit": "TP", "ret_net": 40.0 / 10_000.0},
        {"t0": t0s[3], "confidence": 3.0, "barrier_hit": "TP", "ret_net": 30.0 / 10_000.0},
    ]
    df = _pop_df(rows)
    profile = cd.decile_profile(df, n_deciles=3)
    with_decile = cd._assign_deciles(df, n_deciles=3)
    out = cd._mean_excluding_decile(profile, with_decile)
    assert len(out) == 3
    # bucketing por rank (n=4, n_deciles=3): decil1={10,20}, decil2={40}, decil3={30}
    # excluindo decil1 (2 trades) resta {40, 30} pooled = 35, não 20
    excl1 = out["decile_1"]
    assert excl1["n"] == 2
    assert excl1["mean_ret_net_bps"] == pytest.approx(35.0)


# ============================================================================
# D3 — nofill_by_decile / qui-quadrado
# ============================================================================


def test_nofill_by_decile_taxa_e_chi2_significativo_quando_associado() -> None:
    """5 decis 100% NOFILL, 5 decis 0% NOFILL, 40 linhas/decil — associação
    forte e determinística -> chi2 com p muito pequeno."""
    rows: list[dict[str, object]] = []
    t0_counter = 0
    for k in range(1, 11):
        all_nofill = k <= 5
        for j in range(40):
            rows.append(
                {
                    "t0": _t0s(1, offset_days=t0_counter)[0],
                    "confidence": 10.0 * (k - 1) + j / 100.0,
                    "barrier_hit": "NOFILL" if all_nofill else "TP",
                    "ret_net": 0.0 if all_nofill else 0.001,
                }
            )
            t0_counter += 1
    df = _pop_df(rows)
    out = cd.nofill_by_decile(df)
    by_decile = {r["decile"]: r for r in out["by_decile"]}
    for k in range(1, 6):
        assert by_decile[k]["nofill_rate"] == pytest.approx(1.0)
    assert out["chi2_test"]["p"] < 0.01
    # 40 < FAIXA1_MIN_CELL_N=200 -> toda célula sai marcada insuficiente
    assert all(r["insufficient_n"] for r in out["by_decile"])


def test_nofill_by_decile_tabela_degenerada_nao_quebra_chi2() -> None:
    """Todo decil com NOFILL=0 (nenhuma variação) — `chi2_contingency`
    levantaria em coluna de soma zero; o guard evita a chamada e devolve
    `nan`, não uma exceção."""
    t0s = _t0s(10)
    rows = [
        {"t0": t0s[i], "confidence": float(i), "barrier_hit": "TP", "ret_net": 0.001}
        for i in range(10)
    ]
    df = _pop_df(rows)
    out = cd.nofill_by_decile(df)
    assert math.isnan(out["chi2_test"]["p"])
    assert out["chi2_test"]["dof"] is None


# ============================================================================
# D2 — estratificação por regime e tercil de custo
# ============================================================================


def test_stratified_by_regime_so_r1_r4_e_exclui_r0_r5() -> None:
    t0s = _t0s(20)
    rows = []
    regimes_used = ["R0", "R1", "R2", "R3", "R4", "R5"]
    for i, t0 in enumerate(t0s):
        rows.append(
            {
                "t0": t0,
                "confidence": float(i),
                "barrier_hit": "TP",
                "ret_net": 0.001 * (1 + i % 5),
                "regime": regimes_used[i % len(regimes_used)],
            }
        )
    df = _pop_df(rows)
    out = cd.stratified_by_regime(df)
    assert set(out.keys()) == {"R1", "R2", "R3", "R4"}
    for regime in ("R1", "R2", "R3", "R4"):
        assert out[regime]["n_total"] > 0
        assert len(out[regime]["decile_profile"]) == 10


def test_stratified_by_cost_tercile_buckets_por_quantil() -> None:
    t0s = _t0s(30)
    rows = []
    for i, t0 in enumerate(t0s):
        rows.append(
            {
                "t0": t0,
                "confidence": float(i),
                "barrier_hit": "TP",
                "ret_net": 0.001 * (1 + i % 5),
                cd.COST_FEATURE: float(i),  # 0..29, terços claros
            }
        )
    df = _pop_df(rows)
    out = cd.stratified_by_cost_tercile(df)
    assert out["LOW_COST"]["n_total"] == 10
    assert out["MID_COST"]["n_total"] == 10
    assert out["HIGH_COST"]["n_total"] == 10
    assert out["tercile_cuts"]["q33"] < out["tercile_cuts"]["q66"]


def test_stratified_by_cost_tercile_amostra_insuficiente_devolve_zeros() -> None:
    df = _pop_df(
        [
            {"t0": _t0s(1)[0], "confidence": 0.5, "barrier_hit": "TP", "ret_net": 0.001},
        ]
    )
    out = cd.stratified_by_cost_tercile(df)
    for label in cd._COST_TERCILE_LABELS:
        assert out[label]["n_total"] == 0


# ============================================================================
# congruent_incongruent_subsets — reproduz o achado da Fase E
# ============================================================================


def _predictions_df(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=_T0_DTYPE),
            "fold_id": pl.Series([r.get("fold_id", 0) for r in rows], dtype=pl.Int16),
            "side_hat": pl.Series([r["side_hat"] for r in rows], dtype=pl.Int8),
            "is_oof": pl.Series([r.get("is_oof", True) for r in rows], dtype=pl.Boolean),
            "confidence": pl.Series([r.get("confidence", 0.5) for r in rows], dtype=pl.Float64),
            "score_long_raw": pl.Series([r.get("confidence", 0.5) for r in rows], dtype=pl.Float64),
            "score_short_raw": pl.Series(
                [r.get("confidence", 0.5) for r in rows], dtype=pl.Float64
            ),
        }
    )


def _labels_df(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=_T0_DTYPE),
            "side": pl.Series([r["side"] for r in rows], dtype=pl.Int8),
            "barrier_hit": pl.Series([r["barrier_hit"] for r in rows], dtype=pl.Utf8),
            "ret_net": pl.Series([r["ret_net"] for r in rows], dtype=pl.Float64),
        }
    )


def _regimes_df(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": pl.Series([r["t0"] for r in rows], dtype=_T0_DTYPE),
            "regime": pl.Series([r["regime"] for r in rows], dtype=pl.Utf8),
            cd.COST_FEATURE: pl.Series(
                [r.get(cd.COST_FEATURE, 0.5) for r in rows], dtype=pl.Float64
            ),
            cd.E02F_FEATURE: pl.Series([r[cd.E02F_FEATURE] for r in rows], dtype=pl.Float64),
        }
    )


def test_congruent_incongruent_classifica_por_sinal_do_ic_medido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1: `E02f` cresce junto com `ret_net` (IC > 0). R3: `E02f` cresce,
    `ret_net` cai (IC < 0) — mesma estrutura do achado real (Fase E,
    funding inverte entre faixa e tendência). Restrição forçada do long é
    -1: congruente é onde IC medido é NEGATIVO (R3); do short é +1:
    congruente é onde IC medido é POSITIVO (R1). Cada `t0` carrega sinal
    dos dois lados (mesmo `ret_net` nos dois — não muda o sinal pooled de
    `ic_by_regime`, só popula `build_side_population` para os dois lados).

    `E02f_funding_z_expanding` não tem mais entrada em
    `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` desde `AG-032` (2026-08-23, saiu
    de `T1_FEATURE_IDS`) — `monkeypatch` em `cd._forced_constraint_for`
    reproduz o cenário de QUANDO havia restrição forçada (long=-1,
    short=+1, valor real pré-AG-032), pra manter a cobertura do mecanismo
    de classificação em si (`congruent_incongruent_subsets`), que continua
    genérico e será reusado se uma feature futura reocupar o dict. O
    estado REAL de hoje (sem monkeypatch, dict vazio) é coberto por
    `test_congruent_incongruent_reporta_nao_aplicavel_quando_sem_restricao_forcada`
    abaixo."""
    monkeypatch.setattr(
        cd,
        "_forced_constraint_for",
        lambda feature, *, side: {1: -1, -1: 1}[side] if feature == cd.E02F_FEATURE else None,
    )
    n = 10
    t0_r1 = _t0s(n, offset_days=0)
    t0_r3 = _t0s(n, offset_days=100)

    pred_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    regime_rows: list[dict[str, object]] = []
    for i in range(n):
        e02f = float(i + 1)
        ret_r1 = 0.01 * (i + 1)
        ret_r3 = 0.01 * (n - i)
        for side in (1, -1):
            pred_rows.append({"t0": t0_r1[i], "side_hat": side})
            label_rows.append(
                {"t0": t0_r1[i], "side": side, "barrier_hit": "TP", "ret_net": ret_r1}
            )
            pred_rows.append({"t0": t0_r3[i], "side_hat": side})
            label_rows.append(
                {"t0": t0_r3[i], "side": side, "barrier_hit": "TP", "ret_net": ret_r3}
            )
        regime_rows.append({"t0": t0_r1[i], "regime": "R1", cd.E02F_FEATURE: e02f})
        regime_rows.append({"t0": t0_r3[i], "regime": "R3", cd.E02F_FEATURE: e02f})

    predictions = _predictions_df(pred_rows)
    labels = _labels_df(label_rows)
    regimes = _regimes_df(regime_rows)

    populations = {
        1: cd.build_side_population(predictions, labels, regimes, side=1),
        -1: cd.build_side_population(predictions, labels, regimes, side=-1),
    }
    congruent, incongruent = cd.congruent_incongruent_subsets(
        predictions, labels, regimes, populations
    )

    assert congruent["long"]["regimes_included"] == ["R3"]
    assert incongruent["long"]["regimes_included"] == ["R1"]
    assert congruent["short"]["regimes_included"] == ["R1"]
    assert incongruent["short"]["regimes_included"] == ["R3"]
    assert congruent["long"]["not_applicable_reason"] is None
    assert incongruent["short"]["not_applicable_reason"] is None


def test_congruent_incongruent_reporta_nao_aplicavel_quando_sem_restricao_forcada() -> None:
    """Estado REAL de produção hoje (`AG-032`, 2026-08-23):
    `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` está vazio (`E02f_funding_z_
    expanding` saiu de `T1_FEATURE_IDS`) — `_forced_constraint_for` (não
    monkeypatchado, lido direto da produção real) devolve `None` pros dois
    lados. `congruent_incongruent_subsets` precisa reportar isso
    honestamente (`forced_constraint_sign=None` + `not_applicable_reason`
    explicando o porquê), NUNCA classificar tudo como incongruente por
    engano (comparar sinal medido contra `None` seria sempre falso) nem
    levantar `KeyError` (achado real durante a migração LightGBM do Alpha,
    2026-08-23 — este teste falhava com `KeyError` antes do fix)."""
    n = 4
    t0s = _t0s(n)
    pred_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    regime_rows: list[dict[str, object]] = []
    for i in range(n):
        for side in (1, -1):
            pred_rows.append({"t0": t0s[i], "side_hat": side})
            label_rows.append(
                {"t0": t0s[i], "side": side, "barrier_hit": "TP", "ret_net": 0.01 * (i + 1)}
            )
        regime_rows.append({"t0": t0s[i], "regime": "R1", cd.E02F_FEATURE: float(i + 1)})

    predictions = _predictions_df(pred_rows)
    labels = _labels_df(label_rows)
    regimes = _regimes_df(regime_rows)
    populations = {
        1: cd.build_side_population(predictions, labels, regimes, side=1),
        -1: cd.build_side_population(predictions, labels, regimes, side=-1),
    }

    congruent, incongruent = cd.congruent_incongruent_subsets(
        predictions, labels, regimes, populations
    )

    for side_label in ("long", "short"):
        assert congruent[side_label]["forced_constraint_sign"] is None
        assert incongruent[side_label]["forced_constraint_sign"] is None
        assert congruent[side_label]["not_applicable_reason"] is not None
        assert "AG-032" in congruent[side_label]["not_applicable_reason"]
        assert congruent[side_label]["regimes_included"] == []
        assert incongruent[side_label]["regimes_included"] == []
        # Achado real (`audit_engineering`, 2026-08-23): `decile_profile`/
        # `correlations`/`n_total`, construídos sobre `pop.head(0)` neste
        # branch, precisam ter o MESMO shape que o branch populado --
        # `decile_profile` sempre devolve `FAIXA1_N_DECILES` células
        # (mesmo vazia, `n=0`/`insufficient_n=True`), `correlations`
        # colapsa pro dict all-NaN que `_rank_correlations` já devolve
        # com menos de 3 decis usáveis (nunca `None`/erro/shape diferente
        # que quebraria um consumidor downstream que espera o schema
        # populado).
        for entry in (congruent[side_label], incongruent[side_label]):
            assert entry["n_total"] == 0
            assert len(entry["decile_profile"]) == cd.FAIXA1_N_DECILES
            assert all(cell["n"] == 0 for cell in entry["decile_profile"])
            assert set(entry["correlations"].keys()) == {
                "spearman_rho",
                "spearman_p",
                "kendall_tau",
                "kendall_p",
                "monotonic_increasing_p",
                "monotonic_decreasing_p",
                "n_usable_deciles",
            }
            assert entry["correlations"]["n_usable_deciles"] == 0
            nan_fields = set(entry["correlations"]) - {"n_usable_deciles"}
            assert all(math.isnan(entry["correlations"][k]) for k in nan_fields)


# ============================================================================
# D4 (revisado) — score cru vs calibrado, plateau do isotônico
# ============================================================================


def test_plateau_runs_identifica_regioes_planas_por_igualdade_exata() -> None:
    import numpy as np

    raw = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    conf = np.array([0.1, 0.1, 0.1, 0.2, 0.3, 0.3, 0.3, 0.3, 0.9, 0.9])
    runs = cd._plateau_runs(raw, conf)
    widths = [r["width"] for r in runs]
    n_points = [r["n_points"] for r in runs]
    assert n_points == [3, 1, 4, 2]
    assert widths == pytest.approx([2.0, 0.0, 3.0, 1.0])
    widest = max(runs, key=lambda r: r["width"])
    assert widest["n_points"] == 4
    top = runs[-1]
    assert top["n_points"] == 2
    assert top["confidence_value"] == pytest.approx(0.9)


def test_isotonic_plateau_diagnostics_agrega_por_fold() -> None:
    t0s = _t0s(10)
    rows = [
        {
            "t0": t0s[i],
            "confidence": [0.1, 0.1, 0.1, 0.2, 0.3, 0.3, 0.3, 0.3, 0.9, 0.9][i],
            "raw_score": float(i + 1),
            "barrier_hit": "TP",
            "ret_net": 0.001,
            "fold_id": 0,
        }
        for i in range(10)
    ]
    df = _pop_df(rows)
    out = cd.isotonic_plateau_diagnostics(df)
    assert out["widest_plateau_width_max"] == pytest.approx(3.0)
    assert out["widest_plateau_fold_id"] == 0
    assert out["top_plateau_n_points_total"] == 2


def test_d4_raw_vs_calibrated_sem_troca_quando_rankings_identicos() -> None:
    """`raw_score == confidence` (mesma ordem) -> nenhum trade troca de
    decil entre as duas versões."""
    t0s = _t0s(20)
    rows = [
        {
            "t0": t0s[i],
            "confidence": float(i),
            "raw_score": float(i),
            "barrier_hit": "TP",
            "ret_net": 0.001 * i,
            "fold_id": 0,
        }
        for i in range(20)
    ]
    df = _pop_df(rows)
    out = cd.d4_raw_vs_calibrated(df)
    assert out["fraction_pairs_decile_swap"] == pytest.approx(0.0)
    assert out["n_compared"] == 20


def test_d4_raw_vs_calibrated_troca_quando_rankings_invertidos() -> None:
    """`raw_score` cresce, `confidence` decresce (ordem oposta) — quase
    todo trade muda de decil (exceto o(s) que ficam no meio por simetria
    de bucket, se houver)."""
    t0s = _t0s(20)
    rows = [
        {
            "t0": t0s[i],
            "confidence": float(19 - i),
            "raw_score": float(i),
            "barrier_hit": "TP",
            "ret_net": 0.001 * i,
            "fold_id": 0,
        }
        for i in range(20)
    ]
    df = _pop_df(rows)
    out = cd.d4_raw_vs_calibrated(df)
    assert out["fraction_pairs_decile_swap"] > 0.8


# ============================================================================
# ECE — expected_calibration_error / calibration_error_by_side
# ============================================================================


def test_expected_calibration_error_perfeitamente_calibrado_da_zero() -> None:
    """10 bins, cada um com `confidence` == `mean(outcome)` exato do bin
    (n grande o bastante pra média bater exatamente por construção) ->
    ECE = 0."""
    import numpy as np

    n_per_bin = 100
    confidences = []
    outcomes = []
    for b in range(10):
        conf = (b + 0.5) / 10.0  # centro do bin
        n_pos = round(conf * n_per_bin)
        confidences.extend([conf] * n_per_bin)
        outcomes.extend([1] * n_pos + [0] * (n_per_bin - n_pos))
    out = cd.expected_calibration_error(
        np.array(confidences, dtype=np.float64), np.array(outcomes, dtype=np.int64)
    )
    assert out["ece"] == pytest.approx(0.0, abs=1e-9)
    assert out["n"] == 1000
    assert len(out["bins"]) == 10
    assert all(b["n"] == 100 for b in out["bins"])


def test_expected_calibration_error_confianca_excessiva_da_gap_positivo() -> None:
    """`confidence` sempre 0.9, `outcome` sempre 0 (modelo excessivamente
    confiante e sempre errado) -> ECE = 0.9 (todo peso num único bin,
    gap = |0.9 - 0.0|)."""
    import numpy as np

    n = 50
    out = cd.expected_calibration_error(
        np.full(n, 0.9, dtype=np.float64), np.zeros(n, dtype=np.int64)
    )
    assert out["ece"] == pytest.approx(0.9, abs=1e-9)


def test_expected_calibration_error_e_ponderado_por_populacao_do_bin() -> None:
    """Bin A: 1 observação, gap=1.0. Bin B: 99 observações, gap=0.0.
    ECE ponderado por n = (1/100)*1.0 + (99/100)*0.0 = 0.01 — NÃO a média
    simples dos gaps (que daria 0.5, a leitura não-ponderada que
    `train_alpha_c1_v14.py` usa e que esta função deliberadamente não
    reproduz, ver docstring)."""
    import numpy as np

    confidences = np.array([0.05] + [0.95] * 99, dtype=np.float64)
    outcomes = np.array([1] + [1] * 99, dtype=np.int64)
    # bin 0 (0.0-0.1): confidence=0.05, outcome=1 -> gap=0.95
    # bin 9 (0.9-1.0): confidence=0.95, outcome=1 -> gap=0.05
    out = cd.expected_calibration_error(confidences, outcomes)
    expected = (1 / 100) * 0.95 + (99 / 100) * 0.05
    assert out["ece"] == pytest.approx(expected, abs=1e-9)
    # média simples (não-ponderada) dos dois gaps seria bem maior — confirma
    # que a ponderação por n realmente muda o número, não só documentação
    unweighted = (0.95 + 0.05) / 2
    assert out["ece"] < unweighted


def test_expected_calibration_error_bin_vazio_nao_quebra() -> None:
    import numpy as np

    out = cd.expected_calibration_error(
        np.array([0.05, 0.95], dtype=np.float64), np.array([0, 1], dtype=np.int64)
    )
    assert len(out["bins"]) == 10
    empty_bins = [b for b in out["bins"] if b["n"] == 0]
    assert len(empty_bins) == 8
    assert all(b["mean_confidence"] != b["mean_confidence"] for b in empty_bins)  # NaN


def test_expected_calibration_error_amostra_vazia() -> None:
    import numpy as np

    out = cd.expected_calibration_error(
        np.array([], dtype=np.float64), np.array([], dtype=np.int64)
    )
    assert out["n"] == 0
    assert out["bins"] == []
    assert out["ece"] != out["ece"]  # NaN


def test_calibration_error_by_side_so_sobre_filled_e_compara_raw_vs_calibrado() -> None:
    t0s = _t0s(4)
    rows = [
        {
            "t0": t0s[0],
            "confidence": 0.9,
            "raw_score": 0.5,
            "barrier_hit": "TP",
            "ret_net": 0.001,
        },
        {
            "t0": t0s[1],
            "confidence": 0.9,
            "raw_score": 0.5,
            "barrier_hit": "SL",
            "ret_net": -0.001,
        },
        {
            "t0": t0s[2],
            "confidence": 0.5,
            "raw_score": 0.5,
            "barrier_hit": "NOFILL",
            "ret_net": 0.0,
        },
        {
            "t0": t0s[3],
            "confidence": 0.5,
            "raw_score": 0.5,
            "barrier_hit": "TIME",
            "ret_net": 0.0,
        },
    ]
    df = _pop_df(rows)
    out = cd.calibration_error_by_side(df)
    assert out["n_filled"] == 3  # NOFILL excluído
    assert out["calibrated"]["n"] == 3
    assert out["raw_score"]["n"] == 3
    assert "ece" in out["calibrated"]
    assert "ece" in out["raw_score"]


# ============================================================================
# build_side_population — retém NOFILL, filtra is_oof/side_hat, dedup regime
# ============================================================================


def test_build_side_population_retem_nofill_e_filtra_lado() -> None:
    t0_fill = _t0s(1, offset_days=0)[0]
    t0_nofill = _t0s(1, offset_days=1)[0]
    t0_outro_lado = _t0s(1, offset_days=2)[0]
    t0_nao_oof = _t0s(1, offset_days=3)[0]

    predictions = _predictions_df(
        [
            {"t0": t0_fill, "side_hat": 1, "is_oof": True},
            {"t0": t0_nofill, "side_hat": 1, "is_oof": True},
            {"t0": t0_outro_lado, "side_hat": -1, "is_oof": True},
            {"t0": t0_nao_oof, "side_hat": 1, "is_oof": False},
        ]
    )
    labels = _labels_df(
        [
            {"t0": t0_fill, "side": 1, "barrier_hit": "TP", "ret_net": 0.01},
            {"t0": t0_nofill, "side": 1, "barrier_hit": "NOFILL", "ret_net": 0.0},
            {"t0": t0_outro_lado, "side": -1, "barrier_hit": "TP", "ret_net": 0.01},
            {"t0": t0_nao_oof, "side": 1, "barrier_hit": "TP", "ret_net": 0.01},
        ]
    )
    regimes = _regimes_df(
        [
            {"t0": t0_fill, "regime": "R1", cd.E02F_FEATURE: 0.0},
            {"t0": t0_nofill, "regime": "R1", cd.E02F_FEATURE: 0.0},
            {"t0": t0_outro_lado, "regime": "R1", cd.E02F_FEATURE: 0.0},
            {"t0": t0_nao_oof, "regime": "R1", cd.E02F_FEATURE: 0.0},
        ]
    )
    pop = cd.build_side_population(predictions, labels, regimes, side=1)
    assert pop.height == 2  # só t0_fill e t0_nofill — outro lado e nao-oof fora
    assert set(pop["barrier_hit"].to_list()) == {"TP", "NOFILL"}


def test_build_side_population_regime_duplicado_por_t0_nao_infla() -> None:
    t0 = _t0s(1)[0]
    predictions = _predictions_df([{"t0": t0, "side_hat": 1, "is_oof": True}])
    labels = _labels_df([{"t0": t0, "side": 1, "barrier_hit": "TP", "ret_net": 0.01}])
    regimes = pl.concat(
        [
            _regimes_df([{"t0": t0, "regime": "R1", cd.E02F_FEATURE: 0.0}]),
            _regimes_df([{"t0": t0, "regime": "R1", cd.E02F_FEATURE: 0.0}]),
        ],
        how="vertical",
    )
    pop = cd.build_side_population(predictions, labels, regimes, side=1)
    assert pop.height == 1


def test_build_side_population_side_invalido_levanta_valueerror() -> None:
    with pytest.raises(ValueError, match="side"):
        cd.build_side_population(_predictions_df([]), _labels_df([]), _regimes_df([]), side=0)


# ============================================================================
# verify_step0_premises — delega para confidence_deciles_by_side
# ============================================================================


def test_verify_step0_premises_devolve_spearman_e_decil_10_por_lado() -> None:
    """`confidence_deciles_by_side` roda os dois lados incondicionalmente
    — um lado sem NENHUM trade produz zero linhas para ele (não um decil
    vazio, ver docstring de `attribution.confidence_deciles_by_side`), o
    que quebraria `verify_step0_premises` ao indexar `decile==10`. Um
    punhado de trades `short` (irrelevantes para as asserções, que miram
    só `long`) evita esse caso degenerado — o mesmo vale para o dado real,
    que sempre tem os dois lados."""
    bps_values: list[float] = []
    for k in range(1, 11):
        bps_values.extend([2.0 * k - 1.0, 2.0 * k + 1.0])
    t0s = _t0s(20)
    t0s_short = _t0s(3, offset_days=100)
    predictions = pl.concat(
        [
            _predictions_df(
                [{"t0": t0s[i], "side_hat": 1, "confidence": float(i)} for i in range(20)]
            ),
            _predictions_df(
                [{"t0": t0s_short[i], "side_hat": -1, "confidence": float(i)} for i in range(3)]
            ),
        ],
        how="vertical",
    )
    labels = pl.concat(
        [
            _labels_df(
                [
                    {
                        "t0": t0s[i],
                        "side": 1,
                        "barrier_hit": "TP",
                        "ret_net": bps_values[i] / 10_000.0,
                    }
                    for i in range(20)
                ]
            ),
            _labels_df(
                [
                    {"t0": t0s_short[i], "side": -1, "barrier_hit": "TP", "ret_net": 0.001}
                    for i in range(3)
                ]
            ),
        ],
        how="vertical",
    )
    out = cd.verify_step0_premises(predictions, labels)
    assert "long" in out
    assert out["long"]["decile_10_n"] == 2
    assert out["long"]["decile_10_mean_bps"] == pytest.approx(20.0)
    assert out["long"]["decile_sizes_equal_within_1"] is True
    assert out["long"]["spearman_rho"] == pytest.approx(1.0)


# ============================================================================
# run_faixa1_diagnostic — smoke test da orquestração completa
# ============================================================================


def test_run_faixa1_diagnostic_monta_todas_as_chaves_da_rubrica() -> None:
    n = 60
    t0s = _t0s(n)
    regimes_cycle = ["R1", "R2", "R3", "R4"]
    pred_rows = []
    label_rows = []
    regime_rows = []
    for i in range(n):
        side = 1 if i % 2 == 0 else -1
        pred_rows.append({"t0": t0s[i], "side_hat": side, "confidence": float(i % 10) / 10.0})
        barrier = "NOFILL" if i % 7 == 0 else ("TP" if i % 2 == 0 else "SL")
        label_rows.append(
            {
                "t0": t0s[i],
                "side": side,
                "barrier_hit": barrier,
                "ret_net": 0.0 if barrier == "NOFILL" else 0.001 * ((i % 10) - 5),
            }
        )
        regime_rows.append(
            {
                "t0": t0s[i],
                "regime": regimes_cycle[i % len(regimes_cycle)],
                cd.COST_FEATURE: float(i % 30),
                cd.E02F_FEATURE: float((i % 5) - 2),
            }
        )
    predictions = _predictions_df(pred_rows)
    labels = _labels_df(label_rows)
    regimes = _regimes_df(regime_rows)

    payload = cd.run_faixa1_diagnostic(predictions, labels, regimes)

    expected_keys = {
        "step0_premises_reproduced",
        "spearman_by_side",
        "spearman_p_by_side",
        "kendall_by_side",
        "kendall_p_by_side",
        "monotonic_increasing_p",
        "monotonic_decreasing_p",
        "decile_mean_bps",
        "mean_excluding_decile_k",
        "nofill_rate_by_decile",
        "by_regime",
        "by_cost_tercile",
        "constraint_congruent_subset",
        "constraint_incongruent_subset",
        "calibrator_comparison",
        "expected_calibration_error",
    }
    assert expected_keys <= set(payload.keys())
    for side_label in ("long", "short"):
        assert side_label in payload["decile_mean_bps"]
        assert len(payload["decile_mean_bps"][side_label]) == 10
        assert side_label in payload["calibrator_comparison"]
        assert "isotonic_plateau" in payload["calibrator_comparison"][side_label]
        assert side_label in payload["expected_calibration_error"]
        assert "calibrated" in payload["expected_calibration_error"][side_label]
        assert "raw_score" in payload["expected_calibration_error"][side_label]


# ============================================================================
# Integração real — skip se predictions/labels/mf ainda não existirem
# ============================================================================


def _skip_if_real_artifacts_missing() -> None:
    from src.models._paths import PREDICTIONS_OUTPUT_DIR
    from src.models.pipeline import MODEL_ID_CAMADA1
    from src.validation._paths import labels_symbol_tf_dir

    preds_path = PREDICTIONS_OUTPUT_DIR / "alpha" / MODEL_ID_CAMADA1 / "predictions.parquet"
    labels_path = labels_symbol_tf_dir("BTCUSDT", "v1") / "labels.parquet"
    missing = [str(p) for p in (preds_path, labels_path) if not p.exists()]
    if missing:
        pytest.skip(f"artefato(s) real(is) ausente(s), rode o pipeline primeiro: {missing}")


@pytest.mark.slow
@pytest.mark.integration
def test_integracao_real_run_faixa1_diagnostic() -> None:
    from src.features.build import T1_FEATURE_IDS
    from src.models import dataset as ds
    from src.models._paths import PREDICTIONS_OUTPUT_DIR
    from src.models.pipeline import MODEL_ID_CAMADA1
    from src.validation import cpcv

    _skip_if_real_artifacts_missing()
    model_id = MODEL_ID_CAMADA1
    predictions = pl.read_parquet(
        PREDICTIONS_OUTPUT_DIR / "alpha" / model_id / "predictions.parquet"
    )
    labels = cpcv.load_labels_v1()
    assert cd.COST_FEATURE in T1_FEATURE_IDS
    # `E02F_FEATURE` SAIU de `T1_FEATURE_IDS` (AG-032, 2026-08-23) --
    # `compute_t1_features` continua calculando a coluna, só não entra
    # mais no join default de `build_modeling_frame` (precisa de
    # `extra_feature_ids` explícito, ver abaixo). Achado real durante a
    # migração LightGBM do Alpha (2026-08-23) -- esta asserção (e a
    # ausência de `extra_feature_ids` abaixo) já estava desatualizada
    # desde `AG-032`, nunca exercitada porque este teste é `integration`.
    assert cd.E02F_FEATURE not in T1_FEATURE_IDS
    mf = ds.build_modeling_frame(extra_feature_ids=(cd.E02F_FEATURE,))
    regimes = mf.data.select(["t0", "regime", cd.COST_FEATURE, cd.E02F_FEATURE])

    payload = cd.run_faixa1_diagnostic(predictions, labels, regimes)

    for side in ("long", "short"):
        assert len(payload["decile_mean_bps"][side]) == 10
        n_total = sum(r["n"] for r in payload["decile_mean_bps"][side])
        assert n_total > 0
        assert set(payload["by_regime"][side].keys()) == {"R1", "R2", "R3", "R4"}
        assert set(payload["by_cost_tercile"][side].keys()) >= {
            "LOW_COST",
            "MID_COST",
            "HIGH_COST",
        }
        n_by_decile = payload["step0_premises_reproduced"][side]["n_by_decile"]
        assert sum(n_by_decile) > 0
