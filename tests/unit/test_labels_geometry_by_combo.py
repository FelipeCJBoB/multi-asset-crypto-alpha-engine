"""Testes da geometria de barreira por célula (`src.labels.geometry_by_combo`)
e do seu wiring em `LabelConfig.from_constants`.

O invariante mais importante aqui não é o override funcionar — é o
comportamento DEFAULT continuar bit-exato. `tp_atr_mult`/`sl_atr_mult`
entram no `config_hash` (B15), então qualquer mudança acidental no caminho
sem a flag invalidaria todo `labels.parquet` já persistido."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.labels import geometry_by_combo
from src.labels.triple_barrier import LabelConfig

_ESTIMATOR_ID = "atr_wilder_w20"


@pytest.fixture(autouse=True)
def _limpa_cache() -> Any:
    """O loader cacheia em memória (o arquivo não muda durante o processo).
    Sem limpar entre testes, um `monkeypatch` de caminho não teria efeito."""
    geometry_by_combo._cache = None
    yield
    geometry_by_combo._cache = None


def _escreve_yaml(tmp_path: Path, corpo: str) -> Path:
    caminho = tmp_path / "barrier_geometry_by_combo.yaml"
    caminho.write_text(corpo, encoding="utf-8")
    return caminho


# ============================================================================
# Loader
# ============================================================================


def test_combo_coberto_devolve_a_geometria(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    caminho = _escreve_yaml(
        tmp_path,
        "barrier_geometry:\n  BTCUSDT_R1:\n    tp_atr_mult: 2.25\n    sl_atr_mult: 2.25\n",
    )
    monkeypatch.setattr(geometry_by_combo, "BARRIER_GEOMETRY_BY_COMBO_PATH", caminho)
    geom = geometry_by_combo.load_barrier_geometry("BTCUSDT", "R1")
    assert geom is not None
    assert (geom.tp_atr_mult, geom.sl_atr_mult) == (2.25, 2.25)


def test_combo_ausente_devolve_none_nunca_interpola(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """O caller cai no global explicitamente. Interpolar entre combos vizinhos
    seria inventar um valor sem base medida."""
    caminho = _escreve_yaml(
        tmp_path,
        "barrier_geometry:\n  BTCUSDT_R1:\n    tp_atr_mult: 2.25\n    sl_atr_mult: 2.25\n",
    )
    monkeypatch.setattr(geometry_by_combo, "BARRIER_GEOMETRY_BY_COMBO_PATH", caminho)
    assert geometry_by_combo.load_barrier_geometry("BTCUSDT", "R2") is None
    assert geometry_by_combo.load_barrier_geometry("DOGEUSDT", "R1") is None


def test_resolution_id_none_nunca_recebe_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A calibração foi medida sobre R1/R2/R3; a grade de relógio 15m tem
    ~47% de diferença de duração (AG-042) e não é destino válido."""
    caminho = _escreve_yaml(
        tmp_path,
        "barrier_geometry:\n  BTCUSDT_R1:\n    tp_atr_mult: 2.25\n    sl_atr_mult: 2.25\n",
    )
    monkeypatch.setattr(geometry_by_combo, "BARRIER_GEOMETRY_BY_COMBO_PATH", caminho)
    assert geometry_by_combo.load_barrier_geometry("BTCUSDT", None) is None


def test_arquivo_ausente_e_caminho_valido(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sem o arquivo, todo combo cai no global — não é erro."""
    monkeypatch.setattr(
        geometry_by_combo, "BARRIER_GEOMETRY_BY_COMBO_PATH", tmp_path / "nao_existe.yaml"
    )
    assert geometry_by_combo.load_barrier_geometry("BTCUSDT", "R1") is None
    assert geometry_by_combo.covered_combos() == ()


def test_yaml_sem_combo_algum_devolve_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Caso real do gerador quando nenhum ganho é distinguível."""
    caminho = _escreve_yaml(tmp_path, "barrier_geometry:\n  {}\n")
    monkeypatch.setattr(geometry_by_combo, "BARRIER_GEOMETRY_BY_COMBO_PATH", caminho)
    assert geometry_by_combo.load_barrier_geometry("BTCUSDT", "R1") is None


def test_covered_combos_lista_ordenada(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    caminho = _escreve_yaml(
        tmp_path,
        "barrier_geometry:\n"
        "  XRPUSDT_R1:\n    tp_atr_mult: 2.25\n    sl_atr_mult: 2.25\n"
        "  BTCUSDT_R1:\n    tp_atr_mult: 2.25\n    sl_atr_mult: 2.25\n",
    )
    monkeypatch.setattr(geometry_by_combo, "BARRIER_GEOMETRY_BY_COMBO_PATH", caminho)
    assert geometry_by_combo.covered_combos() == ("BTCUSDT_R1", "XRPUSDT_R1")


# ============================================================================
# Wiring em LabelConfig.from_constants — o invariante de bit-exatidão
# ============================================================================


def test_default_sem_flag_e_bit_exato(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mesmo com um arquivo de geometria presente e cobrindo o combo, um
    caller que NÃO pede o override tem que produzir o mesmo `config_hash`
    de sempre."""
    caminho = _escreve_yaml(
        tmp_path,
        "barrier_geometry:\n  BTCUSDT_R1:\n    tp_atr_mult: 2.25\n    sl_atr_mult: 2.25\n",
    )
    monkeypatch.setattr(geometry_by_combo, "BARRIER_GEOMETRY_BY_COMBO_PATH", caminho)
    cfg = LabelConfig.from_constants(estimator_id=_ESTIMATOR_ID, resolution_id="R1")
    assert (cfg.tp_atr_mult, cfg.sl_atr_mult) == (1.5, 1.5)


def test_flag_com_combo_coberto_aplica_override_e_muda_o_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Mudar geometria PRECISA mudar o `config_hash` — é o B15 funcionando,
    não um efeito colateral: labels gerados sob outra barreira não podem
    passar por válidos."""
    caminho = _escreve_yaml(
        tmp_path,
        "barrier_geometry:\n  BTCUSDT_R1:\n    tp_atr_mult: 2.25\n    sl_atr_mult: 2.25\n",
    )
    monkeypatch.setattr(geometry_by_combo, "BARRIER_GEOMETRY_BY_COMBO_PATH", caminho)
    base = LabelConfig.from_constants(estimator_id=_ESTIMATOR_ID, resolution_id="R1")
    com_override = LabelConfig.from_constants(
        estimator_id=_ESTIMATOR_ID,
        resolution_id="R1",
        symbol="BTCUSDT",
        use_geometry_by_combo=True,
    )
    assert (com_override.tp_atr_mult, com_override.sl_atr_mult) == (2.25, 2.25)
    assert com_override.config_hash != base.config_hash


def test_flag_com_combo_ausente_cai_no_global_bit_exato(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    caminho = _escreve_yaml(
        tmp_path,
        "barrier_geometry:\n  BTCUSDT_R1:\n    tp_atr_mult: 2.25\n    sl_atr_mult: 2.25\n",
    )
    monkeypatch.setattr(geometry_by_combo, "BARRIER_GEOMETRY_BY_COMBO_PATH", caminho)
    base = LabelConfig.from_constants(estimator_id=_ESTIMATOR_ID, resolution_id="R2")
    com_flag = LabelConfig.from_constants(
        estimator_id=_ESTIMATOR_ID,
        resolution_id="R2",
        symbol="BTCUSDT",
        use_geometry_by_combo=True,
    )
    assert com_flag.config_hash == base.config_hash


def test_flag_sem_symbol_levanta() -> None:
    """Sem símbolo não há célula — resolver para o global silenciosamente
    faria o caller pensar que pediu o override e recebeu."""
    with pytest.raises(ValueError, match="exige symbol"):
        LabelConfig.from_constants(
            estimator_id=_ESTIMATOR_ID, resolution_id="R1", use_geometry_by_combo=True
        )
