"""Testes do eixo 2 (`src.analysis.feature_temporal_stability`).

Cobrem o NÚCLEO PURO (`semester_bucket_id`, `semester_bucket_ids`,
`semester_label`, `ic_per_semester`, `evaluate_temporal_stability`) --
nenhum toca disco. A casca (`run_feature_temporal_stability_report`) lê
`ic_by_horizon_report_{R}.json` reais e reconstrói features/barras via
`build_t1_features` -- fora do escopo deste arquivo (precisaria de
`integration`/skip-if-ausente, não escrito aqui)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from src.analysis import feature_temporal_stability as fts

# ============================================================================
# semester_bucket_id / semester_label
# ============================================================================


def _ms(year: int, month: int, day: int = 15) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


@pytest.mark.parametrize(
    ("year", "month", "expected_half"),
    [
        (2024, 1, 0),
        (2024, 6, 0),
        (2024, 7, 1),
        (2024, 12, 1),
    ],
)
def test_semester_bucket_id_divide_no_mes_6_7(year: int, month: int, expected_half: int) -> None:
    bucket = fts.semester_bucket_id(_ms(year, month))
    assert bucket == year * 2 + expected_half


def test_semester_label_roundtrip() -> None:
    bucket = fts.semester_bucket_id(_ms(2024, 8))
    assert fts.semester_label(bucket) == "2024-H2"
    bucket_h1 = fts.semester_bucket_id(_ms(2024, 3))
    assert fts.semester_label(bucket_h1) == "2024-H1"


def test_semester_bucket_ids_vetorizado_bate_com_escalar() -> None:
    """A versão vetorizada tem que reproduzir exatamente o escalar,
    ponto a ponto -- é a mesma definição, só a implementação muda."""
    timestamps = [_ms(2022, 3), _ms(2022, 9), _ms(2023, 1), _ms(2024, 12), _ms(2024, 6)]
    arr = np.array(timestamps, dtype=np.int64)
    vetorizado = fts.semester_bucket_ids(arr)
    escalar = [fts.semester_bucket_id(t) for t in timestamps]
    np.testing.assert_array_equal(vetorizado, escalar)


# ============================================================================
# ic_per_semester
# ============================================================================


def test_ic_per_semester_so_inclui_semestres_com_n_suficiente() -> None:
    rng = np.random.default_rng(1)
    feature = rng.normal(0, 1, 2500)
    fwd_return = feature * 0.5 + rng.normal(0, 1, 2500)
    # semestre 0: 1500 pontos (passa min_points=1000); semestre 1: 1000 (nao passa)
    semester_ids = np.array([0] * 1500 + [1] * 1000, dtype=np.int64)
    result = fts.ic_per_semester(feature, fwd_return, semester_ids, min_points=1200)
    assert 0 in result
    assert 1 not in result  # 1000 < 1200


def test_ic_per_semester_min_points_exclui_semestre_pequeno() -> None:
    feature = np.concatenate([np.random.default_rng(2).normal(0, 1, 200), np.full(50, np.nan)])
    fwd_return = np.random.default_rng(3).normal(0, 1, 250)
    semester_ids = np.array([0] * 200 + [1] * 50, dtype=np.int64)
    result = fts.ic_per_semester(feature, fwd_return, semester_ids, min_points=100)
    assert 0 in result
    assert 1 not in result  # 50 < 100


def test_ic_per_semester_levanta_com_shapes_diferentes() -> None:
    with pytest.raises(fts.FeatureTemporalStabilityError, match="shapes"):
        fts.ic_per_semester(
            np.zeros(10), np.zeros(10), np.zeros(5, dtype=np.int64), min_points=1
        )


# ============================================================================
# evaluate_temporal_stability
# ============================================================================


def test_evaluate_temporal_stability_bate_com_conta_manual() -> None:
    ic_by_semester = {0: (0.01, 2000), 1: (0.02, 2000), 2: (0.005, 2000), 3: (-0.03, 2000)}
    resultado = fts.evaluate_temporal_stability(
        ic_by_semester, max_ratio=4.0, min_direction_frac=0.70, min_semesters=1
    )
    abs_ics = [0.01, 0.02, 0.005, 0.03]
    esperado_max = max(abs_ics)
    esperado_med = float(np.median(abs_ics))
    assert resultado.max_abs_ic == pytest.approx(esperado_max)
    assert resultado.median_abs_ic == pytest.approx(esperado_med)
    assert resultado.ratio == pytest.approx(esperado_max / esperado_med)
    assert resultado.n_mesma_direcao == 3  # 3 positivos de 4
    assert resultado.frac_mesma_direcao == pytest.approx(0.75)


def test_evaluate_temporal_stability_reproduz_e18f_reprova_nos_dois() -> None:
    """§2.2: E18f tem max/med=12,57 e 50% mesma direcao -- reprova nos
    dois critérios. Construído sintético com essa razão e essa fração."""
    ic_by_semester = {
        0: (0.1257, 3000),
        1: (0.01, 3000),
        2: (-0.01, 3000),
        3: (-0.01, 3000),
    }
    resultado = fts.evaluate_temporal_stability(
        ic_by_semester, max_ratio=4.0, min_direction_frac=0.70, min_semesters=1
    )
    assert resultado.passa_ratio is False  # 12.57 >> 4
    assert resultado.frac_mesma_direcao == pytest.approx(0.5)
    assert resultado.passa_direcao is False
    assert resultado.passa_eixo_2 is False


def test_evaluate_temporal_stability_reproduz_e16f_passa() -> None:
    """§2.2: E16f tem max/med=2,98, 90% mesma direcao -- passa nos dois."""
    ic_by_semester = {i: (-0.02 if i != 9 else 0.01, 3000) for i in range(10)}
    # max=0.02, med=0.02 -> ratio=1 (nao reproduz 2.98 exato, so a direcao passa/reprova)
    resultado = fts.evaluate_temporal_stability(
        ic_by_semester, max_ratio=4.0, min_direction_frac=0.70, min_semesters=1
    )
    assert resultado.frac_mesma_direcao == pytest.approx(0.9)
    assert resultado.passa_direcao is True
    assert resultado.passa_ratio is True
    assert resultado.passa_eixo_2 is True


def test_evaluate_temporal_stability_direcao_e_maioria_propria_nao_media_ponderada() -> None:
    """Achado real (reprodução de D06f_taker_imbalance_z_48, BTCUSDT/R1,
    h=1): 6 de 10 semestres positivos (maioria=60%), mas os 4 negativos
    têm magnitude maior -- a MÉDIA dos IC's é negativa. Usar a média como
    referência dava 40% (direção errada); usar a maioria própria dá 60%,
    que é o número publicado em §2.2. Este teste trava essa escolha."""
    ic_by_semester = {
        0: (-0.05, 3000),
        1: (-0.05, 3000),
        2: (-0.05, 3000),
        3: (-0.05, 3000),
        4: (0.001, 3000),
        5: (0.001, 3000),
        6: (0.001, 3000),
        7: (0.001, 3000),
        8: (0.001, 3000),
        9: (0.001, 3000),
    }
    # media = (4*-0.05 + 6*0.001)/10 = -0.0194 -> negativa, mas maioria (6/10) e positiva
    assert np.mean([v[0] for v in ic_by_semester.values()]) < 0.0
    resultado = fts.evaluate_temporal_stability(
        ic_by_semester, max_ratio=100.0, min_direction_frac=0.70, min_semesters=1
    )
    assert resultado.n_mesma_direcao == 6
    assert resultado.frac_mesma_direcao == pytest.approx(0.6)


def test_evaluate_temporal_stability_levanta_com_mapa_vazio() -> None:
    with pytest.raises(fts.FeatureTemporalStabilityError, match="nenhum semestre"):
        fts.evaluate_temporal_stability({}, max_ratio=4.0, min_direction_frac=0.70, min_semesters=1)


def test_evaluate_temporal_stability_piso_da_metrica_e_50_por_cento() -> None:
    """Empate exato (5 positivos, 5 negativos) -- maior contagem entre os
    dois lados é sempre >= metade, então o piso da métrica é 50%, não
    0% (definição operacional 2, ver docstring do módulo)."""
    ic_by_semester = {i: (0.01 if i < 5 else -0.01, 2000) for i in range(10)}
    resultado = fts.evaluate_temporal_stability(
        ic_by_semester, max_ratio=100.0, min_direction_frac=0.70, min_semesters=1
    )
    assert resultado.frac_mesma_direcao == pytest.approx(0.5)


def test_evaluate_temporal_stability_ratio_infinito_quando_mediana_zero() -> None:
    ic_by_semester = {0: (0.05, 2000), 1: (0.0, 2000), 2: (-0.0, 2000)}
    resultado = fts.evaluate_temporal_stability(
        ic_by_semester, max_ratio=4.0, min_direction_frac=0.70, min_semesters=1
    )
    assert resultado.ratio == float("inf")
    assert resultado.passa_ratio is False


def test_evaluate_temporal_stability_um_semestre_passaria_trivial_sem_o_piso() -> None:
    """Achado real de `project_assurance` (revisão do ADR-005 §14,
    2026-08-26): com 1 único semestre válido, `ratio=1,0` (mediana de 1
    elemento é o próprio elemento) e `frac_mesma_direcao=100%` SEMPRE --
    `passa_eixo_2=True` incondicional, sem relação com confiabilidade
    real. Confirma que, SEM o piso, o resultado seria trivialmente
    positivo -- por isso `min_semesters` é obrigatório, não cosmético."""
    ic_by_semester = {0: (0.0001, 5000)}
    resultado_sem_piso = fts.evaluate_temporal_stability(
        ic_by_semester, max_ratio=4.0, min_direction_frac=0.70, min_semesters=1
    )
    assert resultado_sem_piso.ratio == pytest.approx(1.0)
    assert resultado_sem_piso.frac_mesma_direcao == pytest.approx(1.0)
    assert resultado_sem_piso.passa_eixo_2 is True  # trivial, e é exatamente o problema


def test_evaluate_temporal_stability_levanta_abaixo_do_piso_de_semestres() -> None:
    ic_by_semester = {0: (0.0001, 5000), 1: (0.0002, 5000)}
    with pytest.raises(fts.FeatureTemporalStabilityError, match="min_semesters"):
        fts.evaluate_temporal_stability(
            ic_by_semester, max_ratio=4.0, min_direction_frac=0.70, min_semesters=4
        )
