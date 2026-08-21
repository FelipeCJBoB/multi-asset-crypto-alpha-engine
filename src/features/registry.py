"""`src/features/registry.py` — leitor typed de `registry.yaml` (§2.14).

Fatia 1 do módulo reservado por `docs/ADR-001_arquitetura_artefatos_e_
contratos_2026-08-19_base.md` (linha ~1774-1775): "`src/features/
registry.py` | lê `registry.yaml`, deriva `feature_manifest` | novo". Esta
rodada (AG-032 item 8, Fix B, 2026-08-21) implementa só a LEITURA typed do
YAML real — `feature_manifest`/versionamento/`design_hash` ficam fora de
escopo (trabalho maior, não estipulado aqui).

`src/validation/leakage.py::_load_feature_registry` tinha uma implementação
ad hoc duplicada do mesmo parsing (`yaml.safe_load` bruto, sem validação de
schema, retornando `list[dict]` cru) — movida pra cá; `leakage.py` agora
importa deste módulo em vez de reimplementar. Nenhum contrato
`[tool.importlinter]` em `pyproject.toml` proíbe `validation -> features`
(os únicos contratos `forbidden` declarados são `features -> labels`,
`models -> execution`, `risk -> execution|models`, `models -> analysis`,
`features -> analysis`, `data -> analysis`, mais a restrição "labels só é
lido por models/validation/backtest") — o import é seguro sob a hierarquia
de camadas do `CLAUDE.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

_REGISTRY_PATH: Path = Path(__file__).resolve().parent / "registry.yaml"

_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
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
)
"""Mesmo conjunto de `tests/unit/test_features_build.py::_REQUIRED_FIELDS`
(§2.14) — duplicado aqui de propósito: aquele teste valida o ARQUIVO real
contra o formato uma vez (via CI); este módulo valida CADA ENTRADA no
momento do parse, sempre que qualquer código chama `load_feature_registry`
— falha alto se `registry.yaml` ganhar uma entrada malformada, mesmo fora
do contexto de teste."""


class FeatureRegistryError(ValueError):
    """Entrada de `registry.yaml` sem campo obrigatório, ou com
    `lookback_bars` num formato não reconhecido (nem `int` nem o literal
    `"expanding"`), ou o arquivo inteiro não sendo uma lista no topo."""


@dataclass(frozen=True, slots=True)
class FeatureRegistryEntry:
    """Uma linha de `registry.yaml` — schema real do arquivo (§2.14),
    validada campo a campo em `load_feature_registry` (nenhum default
    inventado para campo ausente: falha alto, não finge presença)."""

    id: str
    tier: str
    group: str
    formula: str
    sources: tuple[str, ...]
    lookback_bars: int | Literal["expanding"]
    """§2.14: toda feature declara `lookback_bars` como contagem FINITA de
    barras (`int`) ou o literal `"expanding"` (janela expansiva desde
    `t0_dataset`, sem valor finito honesto — `C07_vol_pctile_expanding`/
    `D03f_volume_z_expanding`/`E02f_funding_z_expanding` hoje). Ver
    política fail-fast em `src.features.build.compute_max_feature_
    lookback_ms` (AG-032 item 8) pra por que essa distinção importa pro
    purge do CPCV."""
    min_warmup_bars: int
    tf: str
    dtype: str
    range: tuple[float, float]
    nan_policy: str
    causal_proof: str
    parity_tested: bool
    version: str
    added: str
    nota: str | None = None

    @property
    def is_expanding(self) -> bool:
        """`True` sse `lookback_bars == "expanding"` — sem valor finito
        honesto pra proteger via purge de CPCV."""
        return self.lookback_bars == "expanding"


def _parse_lookback_bars(fid: str, raw_value: object) -> int | Literal["expanding"]:
    if raw_value == "expanding":
        return "expanding"
    if isinstance(raw_value, int) and not isinstance(raw_value, bool):
        return raw_value
    raise FeatureRegistryError(
        f"registry.yaml: {fid}.lookback_bars={raw_value!r} inválido — esperado int "
        "(nº de barras) ou o literal 'expanding' (§2.14)"
    )


def _parse_entry(raw: dict[str, Any]) -> FeatureRegistryEntry:
    fid = str(raw.get("id", "<sem id>"))
    missing = _REQUIRED_FIELDS - raw.keys()
    if missing:
        raise FeatureRegistryError(
            f"registry.yaml: entrada {fid!r} sem campo(s) obrigatório(s) "
            f"{sorted(missing)} (§2.14)"
        )
    range_raw = raw["range"]
    return FeatureRegistryEntry(
        id=fid,
        tier=str(raw["tier"]),
        group=str(raw["group"]),
        formula=str(raw["formula"]),
        sources=tuple(str(s) for s in raw["sources"]),
        lookback_bars=_parse_lookback_bars(fid, raw["lookback_bars"]),
        min_warmup_bars=int(raw["min_warmup_bars"]),
        tf=str(raw["tf"]),
        dtype=str(raw["dtype"]),
        range=(float(range_raw[0]), float(range_raw[1])),
        nan_policy=str(raw["nan_policy"]),
        causal_proof=str(raw["causal_proof"]),
        parity_tested=bool(raw["parity_tested"]),
        version=str(raw["version"]),
        added=str(raw["added"]),
        nota=str(raw["nota"]) if raw.get("nota") is not None else None,
    )


def load_feature_registry(path: Path | None = None) -> tuple[FeatureRegistryEntry, ...]:
    """Parse typed de `registry.yaml` inteiro (§2.14). `path` default lê o
    catálogo real do repo (`src/features/registry.yaml`); o parâmetro
    existe só pra teste (fixture YAML isolada, sem tocar o arquivo real)."""
    registry_path = path if path is not None else _REGISTRY_PATH
    with registry_path.open(encoding="utf-8") as f:
        raw_entries = yaml.safe_load(f) or []
    if not isinstance(raw_entries, list):
        raise FeatureRegistryError(
            f"{registry_path}: esperado uma lista de entradas no topo do YAML, "
            f"recebido {type(raw_entries).__name__}"
        )
    return tuple(_parse_entry(e) for e in raw_entries)


def feature_registry_by_id(path: Path | None = None) -> dict[str, FeatureRegistryEntry]:
    """`{feature_id: FeatureRegistryEntry}` — acesso O(1) por id."""
    return {e.id: e for e in load_feature_registry(path)}


def feature_lookback_bars(path: Path | None = None) -> dict[str, int | Literal["expanding"]]:
    """`{feature_id: lookback_bars}` — fatia mínima pedida (AG-032 item 8/
    Fix B): `int | Literal["expanding"]` por feature, sem carregar os
    demais campos pra quem só precisa disso (ex. o gate fail-fast de
    `src.features.build.compute_max_feature_lookback_ms`)."""
    return {e.id: e.lookback_bars for e in load_feature_registry(path)}
