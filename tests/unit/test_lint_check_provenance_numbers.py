"""Testes do lint `tools/lint/check_provenance_numbers.py` (AG-440).

**Por que estes testes existem, e não só o lint.** Um lint de heurística
pode ser ajustado até parar de reclamar — e aí "0 violações" deixa de
significar "está limpo" e passa a significar "está cego". A primeira
execução real deste lint teve 67% de falso positivo e foi calibrada em
3 iterações; sem um teste que PLANTE uma violação conhecida, não haveria
como distinguir "a calibração ficou boa" de "a calibração matou o lint".

Então cada supressão que eu adicionei ao lint tem aqui o par: um caso que
ela deve suprimir E um caso vizinho que ela NÃO pode suprimir."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_LINT_PATH = Path(__file__).resolve().parents[2] / "tools" / "lint" / "check_provenance_numbers.py"
_spec = importlib.util.spec_from_file_location("check_provenance_numbers", _LINT_PATH)
assert _spec is not None and _spec.loader is not None
_lint = importlib.util.module_from_spec(_spec)
sys.modules["check_provenance_numbers"] = _lint
_spec.loader.exec_module(_lint)


def _doc(**blocos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tp_atr_mult": {"value": 1.5, "source": "geometria vigente"},
        "maker_fee": {"value": 0.0002, "source": "taxa maker"},
        "time_stop_ms": {"value": 28_800_000, "source": "horizonte"},
    }
    base.update(blocos)
    return base


# ============================================================================
# O caso que o lint EXISTE para pegar
# ============================================================================


def test_pega_citacao_obsoleta_sem_marcador_historico() -> None:
    """Violação plantada: a prosa argumenta a partir de `tp_atr_mult=2,0`
    no PRESENTE, enquanto o valor vigente é 1,5. É exatamente o defeito
    real que motivou o lint (`round_trip_cost_bps` justificando `maker_prob`
    com uma geometria assimétrica que não existe mais)."""
    doc = _doc(
        alguma_constante={
            "value": 0.42,
            "source": "a geometria assimétrica tp_atr_mult=2,0 prevê P(TP)=42,9%",
        }
    )
    achados = _lint._violacoes(doc)

    assert len(achados) == 1
    onde, citado, num, real, _trecho = achados[0]
    assert (onde, citado) == ("alguma_constante", "tp_atr_mult")
    assert num == pytest.approx(2.0)
    assert real == pytest.approx(1.5)


def test_lint_nao_fica_cego_apos_as_supressoes() -> None:
    """Contraprova direta da calibração: mesmo com TODOS os marcadores
    históricos ativos, uma citação obsoleta em tempo PRESENTE continua
    sendo pega. Se este teste passar a falhar, alguma supressão foi longe
    demais e o lint virou decorativo."""
    doc = _doc(
        outra={"value": 1.0, "source": "o cálculo usa maker_fee=0,0009 como insumo"}
    )
    achados = _lint._violacoes(doc)
    assert [(a[1], a[2]) for a in achados] == [("maker_fee", pytest.approx(0.0009))]


# ============================================================================
# Supressões — cada uma com o par "suprime" / "não suprime"
# ============================================================================


@pytest.mark.parametrize(
    "prosa",
    [
        "tp_atr_mult=2,0 era o valor até o sweep S1",
        "0,42 foi medido sob tp_atr_mult=2,0",
        "a geometria anterior usava tp_atr_mult=2,0",
        "substitui a leitura de tp_atr_mult=2,0",
    ],
)
def test_suprime_citacao_declaradamente_historica(prosa: str) -> None:
    """Prosa que NARRA a mudança está correta e não pode ser sinalizada --
    era 67% dos achados da 1ª execução real."""
    assert _lint._violacoes(_doc(x={"value": 1.0, "source": prosa})) == []


def test_marcador_historico_longe_demais_nao_suprime() -> None:
    """A janela de contexto é curta de propósito: um `source:` longo não
    pode virar salvo-conduto para qualquer citação obsoleta lá no fim."""
    prosa = "era assim antigamente. " + ("blá " * 40) + "usa tp_atr_mult=2,0 hoje"
    achados = _lint._violacoes(_doc(x={"value": 1.0, "source": prosa}))
    assert len(achados) == 1


# ============================================================================
# Parsing de número -- o bug real que a 1ª versão tinha
# ============================================================================


def test_separador_de_milhar_nao_e_lido_como_decimal() -> None:
    """`time_stop_ms=28.800.000` é o valor CORRETO e não pode ser
    sinalizado. A 1ª versão lia `28.8` e reclamava."""
    doc = _doc(x={"value": 1.0, "source": "com time_stop_ms=28.800.000 o horizonte fecha"})
    assert _lint._violacoes(doc) == []


def test_decimal_com_zeros_a_esquerda_nao_vira_zero() -> None:
    """Bug real da 1ª versão: a alternativa de milhar casava o prefixo
    `0,000` de `0,0002` e devolvia 0.0, gerando violação fantasma contra
    `maker_fee`."""
    assert _lint._to_float("0,0002") == pytest.approx(0.0002)
    assert _lint._to_float("28.800.000") == pytest.approx(28_800_000)
    assert _lint._to_float("1,5") == pytest.approx(1.5)
    assert _lint._to_float("1.597.035,42") == pytest.approx(1_597_035.42)
    # `0,494` casava como grupo de milhar e virava 494 -- bug pego por
    # ESTE arquivo de teste, nao pelo constants.yaml real (que por acaso
    # nao tinha nenhum decimal nessa forma).
    assert _lint._to_float("0,494") == pytest.approx(0.494)
    assert _lint._to_float("0,000") == pytest.approx(0.0)


def test_tolerancia_absorve_arredondamento_de_prosa() -> None:
    """Texto que escreve `0,494` para um valor 0,4942 está certo, não
    obsoleto -- a tolerância existe para isso e não para mascarar
    divergência real."""
    doc = _doc(
        maker_prob={"value": 0.4942, "source": "base"},
        x={"value": 1.0, "source": "usa maker_prob=0,494 no cálculo"},
    )
    assert _lint._violacoes(doc) == []

    doc_ruim = _doc(
        maker_prob={"value": 0.4942, "source": "base"},
        x={"value": 1.0, "source": "usa maker_prob=0,42 no cálculo"},
    )
    assert len(_lint._violacoes(doc_ruim)) == 1


def test_autorreferencia_nao_conta() -> None:
    """Uma constante citando o PRÓPRIO nome e valor não é violação."""
    doc = _doc(tp_atr_mult={"value": 1.5, "source": "tp_atr_mult=1,5 desde 2026-08-24"})
    assert _lint._violacoes(doc) == []
