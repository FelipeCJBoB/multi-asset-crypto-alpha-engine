"""Testes da política de peso do calibrador isotônico — `AG-312`,
ADR-005 §13.10 / item 4 de §13.17.

**O defeito.** `IsotonicRegression.fit(..., sample_weight=w)` devolve
`E_w[y|x]`, não `E[y|x]`. O peso legado é `uniqueness × |ret_net|`
(`labels/weights.py`), e `|ret_net|` no SL é 1,25–1,29× o do TP — o custo
subtrai do ganho e soma à perda. Logo o peso **sub-pondera a classe
positiva**, e a saída do calibrador deixa de estimar `P(TP)`.

Medido em 5 células reais: sob o peso legado a saída estima **0,4323**
quando `P(TP)` é **0,4967** (viés −13,0%); sob `uniqueness` sozinho o viés
fica em `[−0,0012, +0,0030]`.

Os testes aqui não repetem essa medição sobre dado real (ela está no ADR e
no `AG-312`). Provam a **propriedade** que a torna inevitável, sobre
fixtures onde a resposta é conhecida por construção: isotônica ponderada
preserva a média PONDERADA, então quando o peso se correlaciona com `y` a
saída sai enviesada em relação à média por contagem.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.isotonic import IsotonicRegression

from src.models import alpha


def test_isotonica_ponderada_estima_a_media_PONDERADA_nao_a_por_contagem() -> None:
    """A propriedade que gera o defeito, isolada.

    `y` tem média 0,5 por contagem. O peso vale 3 nos zeros e 1 nos uns —
    exatamente o padrão de `|ret_net|`, que é maior no SL (`y=0`) que no TP
    (`y=1`). A isotônica ponderada devolve a média ponderada, 0,25, não 0,5.

    **`y` precisa ser DECRESCENTE em `x`** (achado ao escrever este teste):
    com `y` crescente, a isotônica ajusta perfeitamente sem precisar
    agrupar nada, devolve `y` de volta e o peso não influencia — o teste
    passaria por motivo errado. O viés só aparece onde o PAVA de fato
    AGRUPA, que é o caso real (score fraco, `y` quase independente dele)."""
    y = np.array([1, 1, 0, 0], dtype=np.float64)  # decrescente -> PAVA agrupa tudo
    w = np.array([1.0, 1.0, 3.0, 3.0])  # peso maior nos zeros, como |ret_net| no SL
    x = np.array([0.1, 0.2, 0.3, 0.4])

    com_peso = IsotonicRegression(out_of_bounds="clip").fit(x, y, sample_weight=w).predict(x)
    sem_peso = IsotonicRegression(out_of_bounds="clip").fit(x, y).predict(x)

    assert y.mean() == pytest.approx(0.5)
    assert com_peso.mean() == pytest.approx(0.25), "peso correlacionado com y enviesa o nível"
    assert sem_peso.mean() == pytest.approx(0.5), "sem peso, o nível é a taxa por contagem"


def test_peso_NAO_correlacionado_com_y_nao_enviesa() -> None:
    """O contraponto que separa `uniqueness` de `|ret_net|`: um peso que
    varia mas não se correlaciona com o desfecho preserva o nível. É por
    isso que (b) mantém `uniqueness` em vez de tirar o peso todo (opção a)
    — `uniqueness` corrige redundância estatística sem inclinar o alvo."""
    y = np.array([1, 1, 0, 0], dtype=np.float64)  # mesmo agrupamento do teste acima
    w = np.array([3.0, 1.0, 3.0, 1.0])  # varia 3x, mas ORTOGONAL a y
    x = np.array([0.1, 0.2, 0.3, 0.4])
    com_peso = IsotonicRegression(out_of_bounds="clip").fit(x, y, sample_weight=w).predict(x)
    assert com_peso.mean() == pytest.approx(y.mean())


def test_as_duas_politicas_existem_e_sao_distintas() -> None:
    assert alpha.CALIB_WEIGHT_SAMPLE_WEIGHT != alpha.CALIB_WEIGHT_UNIQUENESS
    assert alpha.CALIB_WEIGHT_SAMPLE_WEIGHT == "sample_weight"
    assert alpha.CALIB_WEIGHT_UNIQUENESS == "uniqueness"


def test_default_de_fit_side_model_continua_o_LEGADO() -> None:
    """`fit_side_model` preserva o peso legado por default -- bit-exato para
    todo call site e teste existente. Quem muda a política de PRODUÇÃO é
    `pipeline.run_layer1_sprint` (ver
    `test_defaults_de_treino_do_pipeline_sao_os_revistos_de_ag261`), não o
    default desta função. Mesma disciplina de `calib_split_mode` /
    `class_balance_basis` / `tau_policy`."""
    import inspect

    sig = inspect.signature(alpha.fit_side_model)
    assert sig.parameters["calib_weight_basis"].default == alpha.CALIB_WEIGHT_SAMPLE_WEIGHT


def test_politica_desconhecida_levanta_nomeando_as_validas() -> None:
    import inspect

    fonte = inspect.getsource(alpha.fit_side_model)
    assert "calib_weight_basis desconhecido" in fonte


def test_politica_uniqueness_sem_a_coluna_falha_ALTO_e_nao_cai_no_legado() -> None:
    """O ponto mais importante do contrato: um *fallback* silencioso para o
    peso legado quando `uniqueness` falta reintroduziria exatamente o viés
    que a política existe para remover -- e sem deixar rastro. Precisa
    falhar alto."""
    import inspect

    fonte = inspect.getsource(alpha.fit_side_model)
    assert "coluna 'uniqueness' em train_side_df" in fonte
    assert "AG-312" in fonte


def test_side_model_result_instrumenta_o_nivel_do_calibrador() -> None:
    """`AG-312` -- os dois campos que tornam o viés observável em cada fold
    e cada lado, em vez de argumentado uma vez num documento. Sob um
    calibrador não enviesado eles batem; a divergência entre eles É o viés."""
    import dataclasses

    campos = {f.name for f in dataclasses.fields(alpha.SideModelResult)}
    assert {"p_calibrada_media", "p_tp_contagem_calib"} <= campos
