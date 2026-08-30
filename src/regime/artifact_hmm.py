"""Persistência do regime HMM canônico (`hmm_gaussian_k4_v1`) como
artefato versionado, via a camada `src.io.artifact` (ADR-001).

**Por que este módulo existe — medição, não preferência de arquitetura.**
`build_hmm.build_hmm_regimes` refita o HMM a CADA fold do walk-forward
ancorado trimestral, sobre a série completa de dollar bars do símbolo
(437.630 barras em BTCUSDT/R1). Medido em 2026-08-30: mais de 15 minutos
para UM símbolo, sem terminar. Recomputar isso dentro de cada
`dataset.build_modeling_frame` é impraticável para 5 símbolos × 3
resoluções, e pior: tornaria o custo de montar um frame de modelagem
dependente de um refit de modelo, o que nenhum outro insumo do pipeline
faz (labels, features e predições são todos lidos de artefato).

Antes deste módulo `hmm_gaussian_k4_v1` era canônico por DECISÃO
(`AG-114`, `constants.yaml::canonical_regime_hmm_n_states`) mas não tinha
nenhum caminho de produção: zero artefatos em disco, e o único chamador de
`build_hmm_regimes` fora de teste era `hmm_gap_check` (triagem). Um
comentário em `src/analysis/gate_efficiency.py` já chamava `build_hmm.py`
de "o caminho de PRODUÇÃO" — era aspiração, não fato.

**`config_hash` inclui a janela `[start, end]`, de propósito.** Um artefato
construído sobre uma janela diferente É um artefato diferente: o
walk-forward ancorado começa em `start`, então mudar `start` remapeia todos
os folds de canonicalização e, com eles, o significado de cada estado
(§6.2). Fazer o hash ignorar a janela produziria reuso silencioso de um
rótulo incomparável — exatamente o modo de falha que V-08 existe para
impedir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import structlog

from src.io import artifact as io_artifact
from src.io.schema import ArtifactSchema, ColumnSpec

from . import build_hmm
from ._constants import load_constant as load_regime_constant
from ._paths import ARTIFACT_ROOT

logger = structlog.get_logger(__name__)

REGIME_HMM_STAGE = "regime_hmm"

#: `t0` em `Datetime[ms,UTC]`: `build_hmm._assemble_output` emite `ns`, mas
#: a origem real é `_open_time_ms` (epoch em MILISSEGUNDOS), então o cast
#: ns→ms é exato, não uma perda de precisão. `ms` é também a convenção de
#: todo o resto dos artefatos (`predictions_alpha`, `labels`), e
#: `src.io.schema` não conhece `Datetime[ns,UTC]`.
REGIME_HMM_ARTIFACT_SCHEMA = ArtifactSchema(
    schema_version="1.0.0",
    primary_key=("t0",),
    columns=(
        ColumnSpec(name="t0", dtype="Datetime[ms,UTC]", nullable=False, role="key"),
        # `-1` = sentinela "sem decode" (os `initial_train_years` iniciais,
        # que o walk-forward ancorado nunca decodifica). NÃO é nulo, é um
        # valor com significado declarado — §6.4 exige política explícita
        # (veto), e nulo viraria imputação por omissão.
        ColumnSpec(name="canonical_id", dtype="Int64", nullable=False),
        ColumnSpec(name="is_stress_state", dtype="Boolean", nullable=False),
        ColumnSpec(name="tradeable", dtype="Boolean", nullable=False),
        # Fold da CANONICALIZAÇÃO (walk-forward ancorado trimestral) — NÃO é
        # o fold do CPCV. Insumo obrigatório da medição de estabilidade do
        # §6.2; sem ele o one-hot de regime não é auditável.
        ColumnSpec(name="fold_id", dtype="Int64", nullable=False),
        ColumnSpec(name="classifier_id", dtype="Utf8", nullable=False),
        ColumnSpec(name="engine_version", dtype="Utf8", nullable=False),
    ),
)


class RegimeHmmArtifactMissingError(io_artifact.ArtifactNotFoundError, FileNotFoundError):
    """O artefato de regime HMM pedido não existe em disco. Mensagem
    acionável com o comando exato — nunca refita de fallback: um refit
    silencioso escondendo um artefato ausente é como o HMM passou a ser
    "canônico" sem nunca ter sido persistido.

    Herda das DUAS: de `ArtifactNotFoundError` porque é isso que ela é na
    taxonomia da camada de artefato (quem já trata artefato ausente de
    forma genérica continua tratando), e de `FileNotFoundError` porque
    `read_regime_hmm` é, para o chamador, uma leitura de arquivo que pode
    não existir. Sem a primeira, um `except ArtifactNotFoundError` a
    deixaria escapar — que foi como o teste desta exceção falhou na
    primeira versão."""


def regime_hmm_config(
    *,
    symbol: str,
    resolution_id: str,
    n_states: int,
    initial_train_years: int,
    seed: int,
    start: str,
    end: str,
) -> dict[str, Any]:
    """Tudo que muda o CONTEÚDO do artefato entra aqui, e nada mais."""
    return {
        "engine_version": build_hmm.ENGINE_VERSION,
        "symbol": symbol,
        "resolution_id": resolution_id,
        "n_states": n_states,
        "initial_train_years": initial_train_years,
        "seed": seed,
        "start": start,
        "end": end,
    }


def regime_hmm_config_hash(config: dict[str, Any]) -> str:
    return io_artifact.compute_config_hash(
        config, schema_version=REGIME_HMM_ARTIFACT_SCHEMA.schema_version
    )


def _resolve_params(
    n_states: int | None, initial_train_years: int | None
) -> tuple[int, int]:
    resolved_states = (
        n_states
        if n_states is not None
        else int(load_regime_constant("canonical_regime_hmm_n_states"))
    )
    resolved_years = (
        initial_train_years
        if initial_train_years is not None
        else int(load_regime_constant("m1_walkforward_initial_train_years"))
    )
    return resolved_states, resolved_years


def build_and_write_regime_hmm(
    symbol: str,
    start: str,
    end: str,
    *,
    resolution_id: str,
    n_states: int | None = None,
    initial_train_years: int | None = None,
    seed: int = 0,
    root: Path = ARTIFACT_ROOT,
    scratch: bool = False,
) -> io_artifact.ArtifactManifest:
    """Roda `build_hmm_regimes` UMA vez e persiste. Caro por construção —
    é justamente por isso que existe."""
    resolved_states, resolved_years = _resolve_params(n_states, initial_train_years)
    config = regime_hmm_config(
        symbol=symbol,
        resolution_id=resolution_id,
        n_states=resolved_states,
        initial_train_years=resolved_years,
        seed=seed,
        start=start,
        end=end,
    )
    logger.info(
        "regime.artifact_hmm.build_start",
        symbol=symbol,
        resolution_id=resolution_id,
        n_states=resolved_states,
        initial_train_years=resolved_years,
        start=start,
        end=end,
        config_hash=regime_hmm_config_hash(config),
    )
    regimes = build_hmm.build_hmm_regimes(
        symbol,
        start,
        end,
        n_states=resolved_states,
        resolution_id=resolution_id,
        initial_train_years=resolved_years,
        seed=seed,
    )
    regimes = regimes.with_columns(pl.col("t0").dt.cast_time_unit("ms"))

    manifest = io_artifact.write_artifact(
        regimes.select([c.name for c in REGIME_HMM_ARTIFACT_SCHEMA.columns]),
        root=root,
        stage=REGIME_HMM_STAGE,
        symbol=symbol,
        resolution=resolution_id,
        config=config,
        schema=REGIME_HMM_ARTIFACT_SCHEMA,
        producer_entrypoint="src.regime.artifact_hmm.build_and_write_regime_hmm",
        scratch=scratch,
    )
    n_sem_decode = int((regimes["canonical_id"] == -1).sum())
    logger.info(
        "regime.artifact_hmm.build_done",
        symbol=symbol,
        resolution_id=resolution_id,
        config_hash=manifest.config_hash,
        n_rows=regimes.height,
        n_sem_decode=n_sem_decode,
        # §6.4 — o bloco sem decode são os `initial_train_years` iniciais,
        # contíguos em calendário. Reportado sempre, nunca só descartado.
        fracao_sem_decode=round(n_sem_decode / max(regimes.height, 1), 4),
        n_folds_canonicalizacao=int(regimes["fold_id"].n_unique()),
    )
    return manifest


def read_regime_hmm(
    symbol: str,
    start: str,
    end: str,
    *,
    resolution_id: str,
    n_states: int | None = None,
    initial_train_years: int | None = None,
    seed: int = 0,
    root: Path = ARTIFACT_ROOT,
    scratch: bool = False,
) -> pl.DataFrame:
    """Lê o artefato correspondente EXATAMENTE a estes parâmetros.

    Sem fallback para refit: se o artefato não existe, levanta com o comando
    que o produz. Um refit silencioso aqui reintroduziria o custo que a
    persistência veio eliminar, e — pior — mascararia o caso em que a janela
    de labels mudou e o rótulo de regime ficou incomparável (§6.2)."""
    resolved_states, resolved_years = _resolve_params(n_states, initial_train_years)
    config = regime_hmm_config(
        symbol=symbol,
        resolution_id=resolution_id,
        n_states=resolved_states,
        initial_train_years=resolved_years,
        seed=seed,
        start=start,
        end=end,
    )
    config_hash = regime_hmm_config_hash(config)
    try:
        regimes, _manifest = io_artifact.read_artifact(
            root=root,
            stage=REGIME_HMM_STAGE,
            config_hash=config_hash,
            symbol=symbol,
            resolution=resolution_id,
            scratch=scratch,
        )
    except (io_artifact.ArtifactNotFoundError, FileNotFoundError) as exc:
        raise RegimeHmmArtifactMissingError(
            f"artefato de regime HMM ausente para {symbol}/{resolution_id} "
            f"(config_hash={config_hash}, janela [{start}, {end}], k={resolved_states}). "
            "Gere com:\n"
            f"  uv run python -m src.models.regime_hmm_backfill --symbol {symbol} "
            f"--resolution-id {resolution_id}\n"
            "Este módulo NUNCA refita de fallback: o refit custa >15min por símbolo, "
            "e um artefato ausente pode significar que a janela de labels mudou — caso "
            "em que o rótulo de regime antigo seria incomparável (§6.2), não apenas velho."
        ) from exc
    return regimes


# NÃO existe CLI aqui, de propósito. Derivar a janela `[start, end]` exige
# ler `labels`, e o contrato de camada do repo (`pyproject.toml`,
# "labels só é lido por models, validation, backtest") proíbe `regime` de
# alcançar `labels` — inclusive por caminho transitivo via
# `src.validation.cpcv`, que foi como uma primeira versão deste módulo
# quebrou o contrato. O produtor não pode depender do consumidor.
#
# A orquestração que precisa da janela mora em
# `src.models.regime_hmm_backfill`, camada que já tem permissão de ler
# labels e de importar `regime`.
