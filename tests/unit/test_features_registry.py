"""Testes de `src/features/registry.py` — leitor typed de `registry.yaml`
(§2.14, AG-032 item 8/Fix B).

Contra o arquivo REAL: confirma que o parse cobre pelo menos uma feature
`lookback_bars: expanding` e uma finita (as duas formas do schema §2.14) e
que os campos saem tipados corretamente. Contra fixture isolada (`tmp_path`,
nunca o arquivo real): cobre os caminhos de erro (campo obrigatório
ausente, `lookback_bars` num formato não reconhecido, topo do YAML não
sendo uma lista) — `tests/unit/test_features_build.py::_REQUIRED_FIELDS`
já valida o FORMATO do arquivo real uma vez; este módulo valida o LEITOR
typed, chamado toda vez que qualquer código lê o registry."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.features import registry

_MINIMAL_ENTRY_FINITA: dict[str, object] = {
    "id": "X_finita",
    "tier": "T1",
    "group": "X",
    "formula": "f(t)",
    "sources": ["D03"],
    "lookback_bars": 48,
    "min_warmup_bars": 2000,
    "tf": "15m",
    "dtype": "float64",
    "range": [0.0, 1.0],
    "nan_policy": "n/a",
    "causal_proof": "n/a",
    "parity_tested": True,
    "version": "v1",
    "added": "2026-08-21",
}

_MINIMAL_ENTRY_EXPANDING: dict[str, object] = {
    **_MINIMAL_ENTRY_FINITA,
    "id": "X_expanding",
    "lookback_bars": "expanding",
}


def _write_registry(tmp_path: Path, entries: list[dict[str, object]]) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return path


# ============================================================================
# Arquivo real -- pelo menos 1 feature expanding e 1 finita, tipos corretos
# ============================================================================


def test_load_feature_registry_real_arquivo_inclui_expanding_e_finita() -> None:
    entries = registry.load_feature_registry()
    by_id = {e.id: e for e in entries}
    assert len(entries) > 0

    expanding_entry = by_id["C07_vol_pctile_expanding"]
    assert expanding_entry.lookback_bars == "expanding"
    assert expanding_entry.is_expanding is True

    finite_entry = by_id["C06_vol_ratio_12_96"]
    assert finite_entry.lookback_bars == 96
    assert isinstance(finite_entry.lookback_bars, int)
    assert finite_entry.is_expanding is False


def test_load_feature_registry_todas_as_entradas_tipadas_corretamente() -> None:
    for entry in registry.load_feature_registry():
        assert isinstance(entry.id, str) and entry.id
        assert isinstance(entry.sources, tuple)
        assert isinstance(entry.range, tuple)
        assert len(entry.range) == 2
        assert isinstance(entry.range[0], float) and isinstance(entry.range[1], float)
        assert isinstance(entry.parity_tested, bool)
        assert isinstance(entry.min_warmup_bars, int)
        assert isinstance(entry.lookback_bars, int) or entry.lookback_bars == "expanding"


def test_feature_registry_by_id_chave_por_id() -> None:
    by_id = registry.feature_registry_by_id()
    assert by_id["C06_vol_ratio_12_96"].id == "C06_vol_ratio_12_96"
    assert "FEATURE_QUE_NAO_EXISTE" not in by_id


def test_feature_lookback_bars_fatia_minima_id_para_lookback() -> None:
    lookback = registry.feature_lookback_bars()
    assert lookback["C07_vol_pctile_expanding"] == "expanding"
    assert lookback["D03f_volume_z_expanding"] == "expanding"
    assert lookback["E02f_funding_z_expanding"] == "expanding"
    assert lookback["C06_vol_ratio_12_96"] == 96


# ============================================================================
# Fixture isolada -- parse feliz + caminhos de erro (nunca toca o arquivo real)
# ============================================================================


def test_load_feature_registry_fixture_isolada_finita_e_expanding(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, [_MINIMAL_ENTRY_FINITA, _MINIMAL_ENTRY_EXPANDING])
    entries = registry.load_feature_registry(path=path)
    assert len(entries) == 2
    by_id = {e.id: e for e in entries}
    assert by_id["X_finita"].lookback_bars == 48
    assert by_id["X_expanding"].lookback_bars == "expanding"
    assert by_id["X_expanding"].is_expanding is True


def test_load_feature_registry_campo_obrigatorio_ausente_levanta_erro(tmp_path: Path) -> None:
    entry = dict(_MINIMAL_ENTRY_FINITA)
    del entry["causal_proof"]
    path = _write_registry(tmp_path, [entry])
    with pytest.raises(registry.FeatureRegistryError, match="causal_proof"):
        registry.load_feature_registry(path=path)


def test_load_feature_registry_lookback_bars_invalido_levanta_erro(tmp_path: Path) -> None:
    entry = {**_MINIMAL_ENTRY_FINITA, "lookback_bars": "banana"}
    path = _write_registry(tmp_path, [entry])
    with pytest.raises(registry.FeatureRegistryError, match="lookback_bars"):
        registry.load_feature_registry(path=path)


def test_load_feature_registry_topo_nao_e_lista_levanta_erro(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"nao": "lista"}), encoding="utf-8")
    with pytest.raises(registry.FeatureRegistryError):
        registry.load_feature_registry(path=path)
