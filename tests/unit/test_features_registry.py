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
    "layer": ["L2"],
    "quarentena": False,
    "defeito_construcao": False,
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


# ============================================================================
# Poison-pill de id banido (AG-331)
# ============================================================================


def test_load_feature_registry_id_banido_levanta_banned_feature_id_error(
    tmp_path: Path,
) -> None:
    banned_id = next(iter(registry._BANNED_FEATURE_IDS))
    entry = {**_MINIMAL_ENTRY_FINITA, "id": banned_id}
    path = _write_registry(tmp_path, [entry])
    with pytest.raises(registry.BannedFeatureIdError, match=banned_id):
        registry.load_feature_registry(path=path)


def test_banned_feature_id_error_e_subclasse_de_feature_registry_error() -> None:
    """Quem já captura `FeatureRegistryError` (handler existente em
    qualquer chamador) continua pegando o caso banido sem precisar saber do
    tipo novo -- mesmo padrão de `BannedFeatureNameError`/
    `FeatureLayerError` em `Laplace_Quant_V17/pipeline/features/
    feature_sets.py` que motivou este achado (AG-331)."""
    assert issubclass(registry.BannedFeatureIdError, registry.FeatureRegistryError)


def test_load_feature_registry_arquivo_real_nao_tem_nenhum_id_banido() -> None:
    """O arquivo REAL nunca deveria conter um id banido -- se este teste
    falhar, alguém reintroduziu uma feature removida por defeito confirmado
    sem decisão explícita do Manager."""
    ids_reais = {e.id for e in registry.load_feature_registry()}
    assert ids_reais.isdisjoint(registry._BANNED_FEATURE_IDS)


# ============================================================================
# layer/quarentena/defeito_construcao (ADR-005 §14.3-§14.4, campo real
# desde 2026-08-27 -- antes só existia em prosa/planilha, AG-282)
# ============================================================================


def test_load_feature_registry_real_layer_tipado_corretamente() -> None:
    for entry in registry.load_feature_registry():
        assert isinstance(entry.layer, tuple) and len(entry.layer) >= 1
        assert set(entry.layer) <= registry._VALID_LAYERS
        assert isinstance(entry.quarentena, bool)
        assert isinstance(entry.defeito_construcao, bool)


def test_load_feature_registry_real_e27f_tem_dupla_camada_l1_l2() -> None:
    """Exceção deliberada documentada em §14.3 -- E27f é insumo do gate de
    regime E treina o Alpha, de verdade, no código real."""
    by_id = registry.feature_registry_by_id()
    assert by_id["E27f_cost_atr_ratio"].layer == ("L1", "L2")


def test_load_feature_registry_real_e18f_esta_em_quarentena_e_defeito() -> None:
    by_id = registry.feature_registry_by_id()
    e18f = by_id["E18f_taker_ls_vol_ratio"]
    assert e18f.quarentena is True
    assert e18f.defeito_construcao is True
    assert e18f.layer == ("L3",)


def test_load_feature_registry_real_nenhum_t1_e_l0_ou_l4() -> None:
    """Invariante AG-282, verificado de novo aqui como propriedade
    explícita (além de já ser aplicado como gate fail-loud no parse)."""
    for entry in registry.load_feature_registry():
        if entry.tier == "T1":
            assert set(entry.layer) & registry._VALID_T1_LAYERS
            assert "L0" not in entry.layer
            assert "L4" not in entry.layer


def test_load_feature_registry_layer_ausente_ou_vazio_levanta_erro(tmp_path: Path) -> None:
    entry = {**_MINIMAL_ENTRY_FINITA, "layer": []}
    path = _write_registry(tmp_path, [entry])
    with pytest.raises(registry.FeatureLayerError, match="layer"):
        registry.load_feature_registry(path=path)


def test_load_feature_registry_layer_com_valor_invalido_levanta_erro(tmp_path: Path) -> None:
    entry = {**_MINIMAL_ENTRY_FINITA, "layer": ["L99"]}
    path = _write_registry(tmp_path, [entry])
    with pytest.raises(registry.FeatureLayerError, match="L99"):
        registry.load_feature_registry(path=path)


def test_load_feature_registry_t1_com_layer_l0_levanta_tier_layer_error(
    tmp_path: Path,
) -> None:
    entry = {**_MINIMAL_ENTRY_FINITA, "layer": ["L0"]}
    path = _write_registry(tmp_path, [entry])
    with pytest.raises(registry.TierLayerInconsistencyError, match="T1"):
        registry.load_feature_registry(path=path)


def test_load_feature_registry_t1_com_layer_l4_levanta_tier_layer_error(
    tmp_path: Path,
) -> None:
    entry = {**_MINIMAL_ENTRY_FINITA, "layer": ["L4"]}
    path = _write_registry(tmp_path, [entry])
    with pytest.raises(registry.TierLayerInconsistencyError, match="T1"):
        registry.load_feature_registry(path=path)


def test_load_feature_registry_t2_com_layer_l0_e_permitido(tmp_path: Path) -> None:
    """T2 pode ser qualquer camada -- é o espaço de candidatas (AG-282)."""
    entry = {**_MINIMAL_ENTRY_FINITA, "tier": "T2", "layer": ["L0"]}
    path = _write_registry(tmp_path, [entry])
    entries = registry.load_feature_registry(path=path)
    assert entries[0].layer == ("L0",)


def test_tier_layer_inconsistency_error_e_subclasse_de_feature_registry_error() -> None:
    assert issubclass(registry.TierLayerInconsistencyError, registry.FeatureRegistryError)


def test_feature_layer_error_e_subclasse_de_feature_registry_error() -> None:
    assert issubclass(registry.FeatureLayerError, registry.FeatureRegistryError)


# ============================================================================
# layer2_feature_ids -- consistência com T1_FEATURE_IDS (§5.3 item 7)
# ============================================================================


def test_layer2_feature_ids_bate_com_t1_feature_ids() -> None:
    """`layer=='L2' and not quarentena`, derivado do registry.yaml real,
    tem que bater EXATAMENTE com `T1_FEATURE_IDS` (mantido à mão em
    build.py) -- prova que as duas fontes não divergiram. Não rewireia
    src/models/ pra consumir isto (fora de escopo, §13) -- só prova que a
    fonte manual e a derivada concordam hoje."""
    from src.features.build import T1_FEATURE_IDS

    assert registry.layer2_feature_ids() == frozenset(T1_FEATURE_IDS)


def test_layer2_feature_ids_exclui_quarentena(tmp_path: Path) -> None:
    entries = [
        {**_MINIMAL_ENTRY_FINITA, "id": "X_l2_livre", "layer": ["L2"], "quarentena": False},
        {
            **_MINIMAL_ENTRY_FINITA,
            "id": "X_l2_quarentena",
            "layer": ["L2"],
            "quarentena": True,
        },
    ]
    path = _write_registry(tmp_path, entries)
    assert registry.layer2_feature_ids(path=path) == frozenset({"X_l2_livre"})


def test_layer2_feature_ids_exclui_defeito_construcao(tmp_path: Path) -> None:
    """Achado de `project_assurance` (3ª revisão de §14, 2026-08-27): o
    filtro original esquecia `defeito_construcao`, tratando-a de forma
    diferente de `quarentena` apesar da docstring dizer que as duas são
    "ortogonais à camada" igualmente. Sem este teste, uma feature T1 com
    defeito de construção confirmado DEPOIS de promovida (já aconteceu
    com E10f, AG-295) continuaria no conjunto derivado."""
    entries = [
        {**_MINIMAL_ENTRY_FINITA, "id": "X_l2_livre", "layer": ["L2"], "defeito_construcao": False},
        {
            **_MINIMAL_ENTRY_FINITA,
            "id": "X_l2_defeito",
            "layer": ["L2"],
            "defeito_construcao": True,
        },
    ]
    path = _write_registry(tmp_path, entries)
    assert registry.layer2_feature_ids(path=path) == frozenset({"X_l2_livre"})
