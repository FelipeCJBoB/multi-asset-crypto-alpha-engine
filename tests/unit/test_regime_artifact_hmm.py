"""Testes de `src/regime/artifact_hmm.py` — persistência do regime HMM
canônico como artefato versionado.

Os testes aqui NÃO refitam o HMM (custa >15 min por símbolo, que é
justamente o motivo do módulo existir). O que eles provam é o contrato em
volta do refit: hash determinístico, hash sensível ao que muda o conteúdo,
e ausência de artefato falhando alto com mensagem acionável em vez de cair
num refit de fallback silencioso."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.regime import artifact_hmm


def _config(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "symbol": "BTCUSDT",
        "resolution_id": "R1",
        "n_states": 4,
        "initial_train_years": 2,
        "seed": 0,
        "start": "2019-12-28",
        "end": "2026-08-10",
    }
    base.update(overrides)
    return artifact_hmm.regime_hmm_config(**base)  # type: ignore[arg-type]


def test_config_hash_e_deterministico() -> None:
    assert artifact_hmm.regime_hmm_config_hash(
        _config()
    ) == artifact_hmm.regime_hmm_config_hash(_config())


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("n_states", 3),
        ("initial_train_years", 3),
        ("seed", 1),
        ("resolution_id", "R2"),
        ("symbol", "ETHUSDT"),
    ],
)
def test_config_hash_muda_quando_o_conteudo_muda(campo: str, valor: object) -> None:
    assert artifact_hmm.regime_hmm_config_hash(
        _config()
    ) != artifact_hmm.regime_hmm_config_hash(_config(**{campo: valor}))


@pytest.mark.parametrize("campo", ["start", "end"])
def test_config_hash_muda_quando_a_janela_muda(campo: str) -> None:
    """A janela entra no hash de propósito. O walk-forward ancorado começa
    em `start`, então mudar a janela remapeia TODOS os folds de
    canonicalização e, com eles, o significado de cada estado (§6.2). Um
    hash cego à janela reusaria em silêncio um rótulo incomparável."""
    assert artifact_hmm.regime_hmm_config_hash(
        _config()
    ) != artifact_hmm.regime_hmm_config_hash(_config(**{campo: "2020-06-01"}))


def test_config_carrega_a_versao_do_motor() -> None:
    """V-08 — troca de `engine_version` nunca pode reusar artefato antigo."""
    assert _config()["engine_version"] == artifact_hmm.build_hmm.ENGINE_VERSION


def test_artefato_ausente_levanta_com_o_comando_que_o_produz(tmp_path: Path) -> None:
    """Sem fallback para refit. Um refit silencioso escondendo um artefato
    ausente é EXATAMENTE como `hmm_gaussian_k4_v1` chegou a ser canônico
    (`AG-114`) sem nunca ter sido persistido — o erro precisa ser visível."""
    with pytest.raises(artifact_hmm.RegimeHmmArtifactMissingError) as exc:
        artifact_hmm.read_regime_hmm(
            "BTCUSDT",
            "2019-12-28",
            "2026-08-10",
            resolution_id="R1",
            root=tmp_path,
        )
    mensagem = str(exc.value)
    assert "regime_hmm_backfill" in mensagem, "precisa dizer COMO produzir"
    assert "BTCUSDT" in mensagem and "R1" in mensagem
    assert "NUNCA refita" in mensagem


def test_schema_declara_o_fold_de_canonicalizacao() -> None:
    """`fold_id` aqui é o fold do WALK-FORWARD do HMM, não o do CPCV — é o
    insumo da medição de estabilidade do §6.2. Se ele sumir do schema, a
    comparabilidade do rótulo deixa de ser auditável."""
    nomes = {c.name for c in artifact_hmm.REGIME_HMM_ARTIFACT_SCHEMA.columns}
    assert "fold_id" in nomes
    assert "canonical_id" in nomes
    assert "classifier_id" in nomes


def test_canonical_id_nao_e_nullable() -> None:
    """O sentinela "sem decode" é `-1`, um valor com significado declarado
    (§6.4, política de veto) — nunca nulo, que viraria imputação por
    omissão em quem lesse sem prestar atenção."""
    coluna = next(
        c for c in artifact_hmm.REGIME_HMM_ARTIFACT_SCHEMA.columns if c.name == "canonical_id"
    )
    assert coluna.nullable is False
