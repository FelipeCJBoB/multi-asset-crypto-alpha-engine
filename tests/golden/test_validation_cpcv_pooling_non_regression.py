"""Golden de NÃO-REGRESSÃO do CPCV, capturado ANTES da mudança de
`AG-151`/`AG-153`/`D-16` (`docs/meta_model_design_doc_2026-08-22.md` §4.5,
§15.2 P1).

**Por que este arquivo existe, e por que ele precisa ser rodado ANTES de
qualquer edição em `src/validation/cpcv.py`.** A correção de `AG-151`
(`edges_ms` sobre a união temporal cross-símbolo) é estritamente aditiva
por desenho: `generate_splits` ganha um parâmetro `edges_ms` opcional, e o
ramo `edges_ms is None` continua chamando `assign_time_groups(t0_ms,
cfg.n_groups)` exatamente como hoje. Só que "por desenho" não é prova. As
15 combinações `(símbolo × resolução)` já treinadas e registradas em
`audit/evidence_ledger.yaml` (sweeps de 2026-08-23 e 2026-08-28, commit
`3a4c896`) dependem dos splits atuais serem *literalmente* os mesmos
depois do refator — se um único índice de treino mudar, aquelas medições
deixam de ser reproduzíveis e ninguém descobre por outro caminho.

**A ordem não é negociável.** Se o fixture for gerado DEPOIS da edição,
ele deixa de ser um "antes": vira uma segunda cópia do "depois", incapaz
de provar não-regressão. Gerar → inspecionar → commitar → só então editar
`cpcv.py`.

**Fingerprint, não contagens.** Contagens iguais (`n_train`/`n_purged`)
não provam que os ÍNDICES são os mesmos. `train_idx`/`test_idx`/`group_id`
entram como SHA-256 dos bytes do array: tão bit-exato quanto comparar os
arrays (qualquer posição diferente muda o hash) e mantém o fixture legível
— `group_id` sozinho tem centenas de milhares de linhas por símbolo.

**Lacuna declarada (não introduzida aqui).** Este golden usa
`max_feature_lookback_ms=0`, não o valor real que a produção calcula via
`features_build.compute_max_feature_lookback_ms`. Ele prova que `cpcv.py`
não regrediu; NÃO prova que o pipeline de treino ponta a ponta reproduz os
15 artefatos. Essa segunda garantia deveria vir de
`tests/golden/test_sprint8_reproducibility.py`, que hoje está inteiramente
`skip`ado por `AG-257` (o baseline commitado é da grade de relógio 15m,
que falha alto em B15 desde `AG-236`). **Consequência: não existe hoje
nenhum golden ativo sobre a grade R1/R2/R3.** Lacuna preexistente, que
este arquivo reduz mas não fecha."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.validation import cpcv
from src.validation._paths import labels_symbol_tf_dir

_ALL_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
_ALL_RESOLUTIONS: tuple[str, ...] = ("R1", "R2", "R3")

# `parkinson_w20` é o estimador canônico decidido em `AG-036`; `labels` de
# R1/R2/R3 foram gerados sob ele, e `load_labels_v1(verify_config=True)`
# levanta `ConfigHashMismatchError` se divergir — é a checagem B15 fazendo
# o trabalho dela, não um parâmetro cosmético.
_VOL_ESTIMATOR_ID = "parkinson_w20"

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cpcv_single_symbol_baseline.json"

# Variável de ambiente que autoriza a ESCRITA do fixture. Sem ela o teste
# nunca sobrescreve o baseline — um golden que se auto-regenera em silêncio
# quando falha não é um golden, é um carimbo.
_WRITE_ENV = "CPCV_GOLDEN_WRITE"


def _cell_key(symbol: str, resolution_id: str) -> str:
    return f"{symbol}/{resolution_id}"


def _sha256_array(array: object) -> str:
    """SHA-256 sobre os bytes crus do array. `tobytes()` inclui dtype e
    ordem — um `int64` e um `int32` com os mesmos valores dão hashes
    diferentes, que é exatamente o que se quer num teste bit-a-bit."""
    return hashlib.sha256(array.tobytes()).hexdigest()  # type: ignore[attr-defined]


def _fingerprint_result(result: cpcv.CPCVResult) -> dict[str, object]:
    return {
        "n_rows": int(result.group_id.shape[0]),
        "edges_ms": [int(e) for e in result.edges_ms],
        "group_id_sha256": _sha256_array(result.group_id),
        "splits": [
            {
                "split_id": split.split_id,
                "path_id": split.path_id,
                "test_groups": list(split.test_groups),
                "train_groups": list(split.train_groups),
                "n_train_candidate": split.n_train_candidate,
                "n_purged": split.n_purged,
                "n_embargoed": split.n_embargoed,
                "n_train": int(split.train_idx.shape[0]),
                "n_test": int(split.test_idx.shape[0]),
                "train_idx_sha256": _sha256_array(split.train_idx),
                "test_idx_sha256": _sha256_array(split.test_idx),
            }
            for split in result.splits
        ],
    }


def _build_result(symbol: str, resolution_id: str) -> cpcv.CPCVResult:
    labels = cpcv.load_labels_v1(
        symbol=symbol,
        resolution_id=resolution_id,
        vol_estimator_id=_VOL_ESTIMATOR_ID,
        verify_config=True,
    )
    config = cpcv.CPCVConfig.from_constants(grade_id=resolution_id)
    # `edges_ms` deliberadamente NÃO passado: é este ramo — o default, o que
    # produziu os 15 artefatos — que precisa ficar bit-a-bit intocado.
    return cpcv.generate_splits(labels, config=config, symbol=symbol)


def _skip_if_labels_missing(symbol: str, resolution_id: str) -> None:
    path = labels_symbol_tf_dir(symbol, "v1", resolution_id=resolution_id) / "labels.parquet"
    if not path.exists():
        pytest.skip(f"{path} ausente — rode o Label Engine para {symbol}/{resolution_id} primeiro")


def _load_fixture() -> dict[str, Any]:
    if not _FIXTURE_PATH.exists():
        pytest.skip(
            f"baseline ausente em {_FIXTURE_PATH}. Este golden precisa ser CAPTURADO "
            "ANTES de qualquer edição em src/validation/cpcv.py (AG-151/AG-153/D-16). "
            f"Gere com: {_WRITE_ENV}=1 uv run pytest "
            "tests/golden/test_validation_cpcv_pooling_non_regression.py "
            "-k captura -q  — depois inspecione e comite o JSON."
        )
    with _FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return dict(json.load(handle))


@pytest.mark.golden
@pytest.mark.slow
@pytest.mark.integration
def test_captura_baseline_dos_15_combos() -> None:
    """FASE 0 — gera `fixtures/cpcv_single_symbol_baseline.json` a partir do
    `cpcv.py` ATUAL, sem nenhuma edição. Só roda com a variável de ambiente
    de escrita setada; caso contrário é `skip`, para nunca sobrescrever o
    baseline por acidente durante uma suíte normal.

    Combos cujo `labels.parquet` não existe localmente entram no fixture
    como ausentes e são reportados — um baseline parcial é honesto, um
    baseline que finge cobrir 15 quando cobriu 6 não é."""
    if os.environ.get(_WRITE_ENV) != "1":
        pytest.skip(
            f"escrita de baseline desarmada — rode com {_WRITE_ENV}=1 para capturar "
            "(só faça isso ANTES de editar src/validation/cpcv.py)"
        )

    fingerprints: dict[str, object] = {}
    ausentes: list[str] = []
    for symbol in _ALL_SYMBOLS:
        for resolution_id in _ALL_RESOLUTIONS:
            path = (
                labels_symbol_tf_dir(symbol, "v1", resolution_id=resolution_id)
                / "labels.parquet"
            )
            if not path.exists():
                ausentes.append(_cell_key(symbol, resolution_id))
                continue
            fingerprints[_cell_key(symbol, resolution_id)] = _fingerprint_result(
                _build_result(symbol, resolution_id)
            )

    if not fingerprints:
        pytest.skip("nenhum labels.parquet de R1/R2/R3 encontrado — nada a capturar")

    payload = {
        "_schema": "cpcv_single_symbol_baseline/1.0.0",
        "_gerado_por": "tests/golden/test_validation_cpcv_pooling_non_regression.py",
        "_proposito": (
            "Baseline bit-a-bit dos splits CPCV single-symbol ANTES da correção de "
            "AG-151 (edges_ms sobre união temporal) e AG-153 (purge_around_block). "
            "Qualquer divergência depois do refator significa que a mudança NÃO foi "
            "aditiva e as 15 medições do evidence_ledger deixaram de ser reproduzíveis."
        ),
        "_vol_estimator_id": _VOL_ESTIMATOR_ID,
        "_combos_ausentes_na_captura": ausentes,
        "combos": fingerprints,
    }

    _FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _FIXTURE_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, _FIXTURE_PATH)

    print(
        f"\nbaseline escrito em {_FIXTURE_PATH} — {len(fingerprints)} combo(s) capturado(s), "
        f"{len(ausentes)} ausente(s): {ausentes}\nINSPECIONE E COMITE ANTES DE EDITAR cpcv.py."
    )


@pytest.mark.golden
@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("resolution_id", _ALL_RESOLUTIONS)
@pytest.mark.parametrize("symbol", _ALL_SYMBOLS)
def test_splits_single_symbol_identicos_ao_baseline(symbol: str, resolution_id: str) -> None:
    """FASE 1 — depois da mudança em `cpcv.py`, cada combo precisa bater
    bit-a-bit com o baseline. Comparação por `==` sobre o dicionário
    inteiro, tolerância zero: `edges_ms`, hash de `group_id`, e para cada
    um dos 15 splits o hash de `train_idx`/`test_idx` mais as contagens."""
    _skip_if_labels_missing(symbol, resolution_id)
    baseline = _load_fixture()
    combos: dict[str, Any] = baseline["combos"]
    key = _cell_key(symbol, resolution_id)
    if key not in combos:
        pytest.skip(f"{key} não estava presente na captura do baseline")

    obtido = _fingerprint_result(_build_result(symbol, resolution_id))

    assert obtido == combos[key], (
        f"{key}: os splits do CPCV DIVERGIRAM do baseline capturado antes de "
        "AG-151/AG-153. A mudança não foi aditiva — as 15 medições registradas "
        "em audit/evidence_ledger.yaml deixaram de ser reproduzíveis. NÃO comite: "
        "reverta a alteração em src/validation/cpcv.py e investigue qual ramo do "
        "código default passou a ser tocado."
    )
