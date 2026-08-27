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
        "layer",
        "quarentena",
        "defeito_construcao",
    }
)
"""Mesmo conjunto de `tests/unit/test_features_build.py::_REQUIRED_FIELDS`
(§2.14) — duplicado aqui de propósito: aquele teste valida o ARQUIVO real
contra o formato uma vez (via CI); este módulo valida CADA ENTRADA no
momento do parse, sempre que qualquer código chama `load_feature_registry`
— falha alto se `registry.yaml` ganhar uma entrada malformada, mesmo fora
do contexto de teste."""


#: Ids de feature BANIDOS -- removidos do vetor por defeito de construção/
#: artefato de fonte CONFIRMADO (não "sem mecanismo", que é veredito de
#: ficha, revisável; banido é fato de engenharia já fechado). Gate MECÂNICO
#: no momento do parse (AG-331) -- mesma ideia de `Laplace_Quant_V17/
#: pipeline/features/feature_sets.py::_BANNED_FEATURE_NAMES`/
#: `BannedFeatureNameError`: um copy-paste futuro de código velho que
#: reintroduza a entrada falha alto aqui, não depende de ninguém lembrar de
#: checar a ficha/AG log primeiro. Nunca editar uma linha existente pra
#: remover um id daqui -- decisão de "não é mais banido" é do Manager e
#: fica registrada como decisão nova, não como silêncio no código.
_BANNED_FEATURE_IDS: frozenset[str] = frozenset(
    {
        # AG-263, ADR-005 §11.4 item 3, 2026-08-26 — halving não é distinção
        # econômica válida pro escopo atual (múltiplos ativos, sem histórico
        # de halving equivalente pra ETH/SOL/BNB/XRP).
        "K08_days_since_halving",
    }
)

#: Camadas canônicas do critério de evidência (ADR-005 §2.1/§14.3-§14.4).
#: `L0` primitiva de cálculo | `L1` insumo do gate de regime | `L2` núcleo
#: de sinal (= `T1_FEATURE_IDS` hoje) | `L3` em observação | `L4`
#: aposentada. Uma entrada pode estar em MAIS de uma camada só no caso
#: deliberado documentado (`E27f_cost_atr_ratio`, `L1`+`L2` — §14.3).
_VALID_LAYERS: frozenset[str] = frozenset({"L0", "L1", "L2", "L3", "L4"})

#: Camadas em que uma feature `tier="T1"` PODE estar — nunca `L0`
#: (primitiva de cálculo, não é preditora) nem `L4` (aposentada, não
#: deveria estar calculada/em produção). `AG-282`.
_VALID_T1_LAYERS: frozenset[str] = frozenset({"L1", "L2", "L3"})


class FeatureRegistryError(ValueError):
    """Entrada de `registry.yaml` sem campo obrigatório, ou com
    `lookback_bars` num formato não reconhecido (nem `int` nem o literal
    `"expanding"`), ou o arquivo inteiro não sendo uma lista no topo."""


class BannedFeatureIdError(FeatureRegistryError):
    """Uma entrada de `registry.yaml` usa um `id` em `_BANNED_FEATURE_IDS`
    (AG-331) — feature removida por defeito de construção/artefato de fonte
    já confirmado; reintroduzi-la exige decisão explícita do Manager (tirar
    o id de `_BANNED_FEATURE_IDS`, nunca só editar `registry.yaml` por
    baixo)."""


class FeatureLayerError(FeatureRegistryError):
    """`layer` de uma entrada contém um valor fora de `_VALID_LAYERS`
    (ADR-005 §14.3-§14.4, campo real desde 2026-08-27 — antes só existia em
    prosa/planilha, nunca em `registry.yaml`)."""


class TierLayerInconsistencyError(FeatureRegistryError):
    """`tier="T1"` com `layer` contendo `L0` ou `L4` — violação do invariante
    proposto em `AG-282`: T2 pode ser qualquer camada (é o espaço de
    candidatas), T1 só pode ser `L1`/`L2`/`L3` (produção nunca é primitiva
    pura `L0` nem aposentada `L4` — as duas leituras são contraditórias por
    definição: uma feature em produção não é "insumo de cálculo, não
    preditora" nem "sem mecanismo e sem sinal, não calculada"). Detecta
    divergência `tier`/`layer` automaticamente como erro de dado, não como
    estado válido — exatamente a regra que `AG-282` propôs em vez de um 3º
    campo de precedência."""


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
    layer: tuple[str, ...]
    """Camada(s) do critério de evidência (§14.3-§14.4) — `tuple` de 1
    elemento na maioria dos casos, 2 só para `E27f_cost_atr_ratio`
    (`("L1", "L2")`, exceção deliberada documentada em §14.3, não erro de
    precedência). Validado contra `_VALID_LAYERS` e o invariante `tier`/
    `layer` (`AG-282`) em `_parse_entry` — nunca um valor livre."""
    quarentena: bool
    """`True` sse a coluna está em quarentena (§2.3) — sinal FORTE mas
    suspeito de artefato de fonte, não ausência de sinal. Ortogonal à
    camada (nunca uma camada própria). Hoje só `E18f_taker_ls_vol_ratio`."""
    defeito_construcao: bool
    """`True` sse a ficha de tese (`audit/feature_thesis/
    fichas_69_2026-08-25.yaml`) marca esta coluna `INCOERENTE_DIMENSIONAL`
    ou `ERRO_CATEGORICO` (§14.3) — construção mede algo DIFERENTE do que diz
    medir, não "sem mecanismo". Ortogonal à camada."""
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


def _parse_layer(fid: str, raw_value: object, *, tier: str) -> tuple[str, ...]:
    if not isinstance(raw_value, list) or not raw_value:
        raise FeatureLayerError(
            f"registry.yaml: {fid}.layer={raw_value!r} inválido — esperado lista "
            f"não-vazia de valores em {sorted(_VALID_LAYERS)} (§14.3-§14.4)"
        )
    layers = tuple(str(x) for x in raw_value)
    invalid = [x for x in layers if x not in _VALID_LAYERS]
    if invalid:
        raise FeatureLayerError(
            f"registry.yaml: {fid}.layer contém valor(es) fora de "
            f"{sorted(_VALID_LAYERS)}: {invalid} (§14.3-§14.4)"
        )
    if tier == "T1" and not (set(layers) & _VALID_T1_LAYERS):
        raise TierLayerInconsistencyError(
            f"registry.yaml: {fid} tem tier='T1' mas layer={layers!r} não contém "
            f"nenhuma de {sorted(_VALID_T1_LAYERS)} (AG-282 — produção não pode ser "
            "L0 primitiva pura nem L4 aposentada)"
        )
    return layers


def _parse_entry(raw: dict[str, Any]) -> FeatureRegistryEntry:
    fid = str(raw.get("id", "<sem id>"))
    if fid in _BANNED_FEATURE_IDS:
        raise BannedFeatureIdError(
            f"registry.yaml: entrada {fid!r} está em _BANNED_FEATURE_IDS (AG-331) "
            "— removida por defeito de construção/artefato confirmado; reintroduzi-la "
            "exige decisão explícita do Manager, nunca só editar o YAML"
        )
    missing = _REQUIRED_FIELDS - raw.keys()
    if missing:
        raise FeatureRegistryError(
            f"registry.yaml: entrada {fid!r} sem campo(s) obrigatório(s) "
            f"{sorted(missing)} (§2.14)"
        )
    range_raw = raw["range"]
    tier = str(raw["tier"])
    return FeatureRegistryEntry(
        id=fid,
        tier=tier,
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
        layer=_parse_layer(fid, raw["layer"], tier=tier),
        quarentena=bool(raw["quarentena"]),
        defeito_construcao=bool(raw["defeito_construcao"]),
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


def layer2_feature_ids(path: Path | None = None) -> frozenset[str]:
    """`{feature_id}` com `"L2" in layer`, `quarentena=False` e
    `defeito_construcao=False` — a definição de vetor de treino que
    `ADR-005 §5.3` item 7 propôs (`layer == "L2" and not quarentena`),
    derivada do `registry.yaml` real em vez de um id lido de cabeça.

    **Corrigido 2026-08-27 (achado de `project_assurance`, 3ª revisão de
    §14): o filtro original esquecia `defeito_construcao`, apesar da
    docstring do próprio campo (`FeatureRegistryEntry.defeito_construcao`)
    tratar os dois estados como "ortogonais à camada" da mesma forma que
    `quarentena`.** Hoje isso não muda o conjunto retornado (nenhuma
    entrada `L2` real tem `defeito_construcao=True`, verificado contra as
    7 `T1_FEATURE_IDS`) — mas sem o filtro, uma feature T1 encontrada com
    defeito de construção DEPOIS de promovida (já aconteceu com `E10f`,
    `AG-295`) não sairia do conjunto derivado só por ganhar a flag; só a
    demoção manual de `layer` funcionaria.

    **Escopo deliberadamente limitado**: esta função só DERIVA o conjunto —
    não substitui `src.features.build.T1_FEATURE_IDS` como fonte de
    verdade consumida por `src.models.dataset.build_modeling_frame`/
    `src.models.pipeline.run_layer1_sprint` (ambos em `src/models/`, fora
    do escopo desta sessão — ver `tests/unit/test_features_registry.py::
    test_layer2_feature_ids_bate_com_t1_feature_ids` pra a checagem de
    consistência que fecha o gap SEM tocar `src/models/`). Rewiring de
    fato é trabalho da sessão de engenharia de ML (§13), não decidido
    aqui."""
    entries = load_feature_registry(path)
    return frozenset(
        e.id for e in entries if "L2" in e.layer and not e.quarentena and not e.defeito_construcao
    )
