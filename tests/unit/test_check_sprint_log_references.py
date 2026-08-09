"""Testes de `check_sprint_log_references.py` — parsing de diff unificado
--unified=0, janela de parágrafo, e o par mínimo pedido pela tarefa: diff
sintético com número+referência (passa) vs. número sem referência (falha)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lint"))

import check_sprint_log_references as csr

# --------------------------------------------------------------------------
# parse_added_lines — parsing do diff --unified=0
# --------------------------------------------------------------------------


def test_parse_added_lines_simples() -> None:
    diff = "\n".join(
        [
            "diff --git a/f.md b/f.md",
            "--- a/f.md",
            "+++ b/f.md",
            "@@ -3,0 +4 @@ c",
            "+novo com 42 sem ref",
        ]
    )

    added = csr.parse_added_lines(diff)

    assert added == {4: "novo com 42 sem ref"}


def test_parse_added_lines_ignora_linhas_removidas() -> None:
    diff = "\n".join(
        [
            "diff --git a/f.md b/f.md",
            "--- a/f.md",
            "+++ b/f.md",
            "@@ -5,2 +5,1 @@",
            "-linha antiga 1",
            "-linha antiga 2",
            "+linha nova unica",
        ]
    )

    added = csr.parse_added_lines(diff)

    assert added == {5: "linha nova unica"}


def test_parse_added_lines_multiplos_hunks() -> None:
    diff = "\n".join(
        [
            "diff --git a/f.md b/f.md",
            "--- a/f.md",
            "+++ b/f.md",
            "@@ -1,0 +2 @@",
            "+primeira",
            "@@ -10,0 +12 @@",
            "+segunda",
        ]
    )

    added = csr.parse_added_lines(diff)

    assert added == {2: "primeira", 12: "segunda"}


# --------------------------------------------------------------------------
# check_diff — o par mínimo pedido: passa com referência, falha sem
# --------------------------------------------------------------------------


def _diff_for_single_added_line(lineno: int, text: str) -> str:
    return "\n".join(
        [
            "diff --git a/docs/SPRINT_LOG.md b/docs/SPRINT_LOG.md",
            "--- a/docs/SPRINT_LOG.md",
            "+++ b/docs/SPRINT_LOG.md",
            f"@@ -0,0 +{lineno} @@",
            f"+{text}",
        ]
    )


def test_numero_com_referencia_na_mesma_linha_passa() -> None:
    text = "Fill rate medido em 37,3% — ver `src/backtest/fill_reconciliation.py`."
    diff = _diff_for_single_added_line(1, text)
    lines = [text]

    problems = csr.check_diff(diff, lines)

    assert problems == []


def test_numero_sem_referencia_falha() -> None:
    text = "Fill rate medido em 37,3% agregado, bem acima do esperado."
    diff = _diff_for_single_added_line(1, text)
    lines = [text]

    problems = csr.check_diff(diff, lines)

    assert len(problems) == 1
    assert problems[0].line == 1


def test_referencia_via_hash_de_commit_na_mesma_linha_passa() -> None:
    text = "Sharpe subiu para 1,42 no rerun (commit `981b153`)."
    diff = _diff_for_single_added_line(1, text)
    lines = [text]

    assert csr.check_diff(diff, lines) == []


def test_referencia_via_secao_prd_na_mesma_linha_passa() -> None:
    text = "Stop mínimo de 0,275% (§0.2 R2)."
    diff = _diff_for_single_added_line(1, text)
    lines = [text]

    assert csr.check_diff(diff, lines) == []


def test_referencia_na_janela_ao_redor_passa() -> None:
    lines = [
        "Investigação de fill rate no Sprint 9, resultado abaixo.",
        "",
        "O número final ficou em 37,3% de preenchimento agregado, medido",
        "sobre a janela reconciliada — ver `src/backtest/fill_reconciliation.py`",
        "para o código exato.",
    ]
    # a linha adicionada é a 3 (0-based -> 1-based linha 3), sem referência
    # na própria linha, mas a referência está 1 linha abaixo, dentro da janela.
    diff = _diff_for_single_added_line(3, lines[2])

    problems = csr.check_diff(diff, lines)

    assert problems == []


def test_referencia_fora_da_janela_falha() -> None:
    # parágrafo grande o bastante para que a referência (linha 10) fique fora
    # de uma janela de 2 linhas ao redor da linha flagged (linha 5).
    lines = [
        "linha de preenchimento 1",
        "linha de preenchimento 2",
        "Número relevante: 42% de algo.",
        "linha de preenchimento 3",
        "linha de preenchimento 4",
        "referência tardia demais: `src/mod.py`",
    ]
    diff = _diff_for_single_added_line(3, lines[2])

    problems = csr.check_diff(diff, lines, window=2)

    assert len(problems) == 1
    assert problems[0].line == 3


def test_paragrafo_delimita_janela_mesmo_com_window_grande() -> None:
    # referência está no PRÓXIMO parágrafo (separado por linha em branco) —
    # não deve contar mesmo com window grande, porque _paragraph_window para
    # em linha em branco.
    lines = [
        "Número relevante: 42% de algo, sem referência neste parágrafo.",
        "",
        "Parágrafo seguinte, sem relação: `src/outro_mod.py`.",
    ]
    diff = _diff_for_single_added_line(1, lines[0])

    problems = csr.check_diff(diff, lines, window=10)

    assert len(problems) == 1


def test_skip_marker_na_linha_anterior_suprime() -> None:
    lines = [
        csr._SKIP_MARKER,
        "Número solto sem referência: 99 unidades, decisão de prosa.",
    ]
    diff = _diff_for_single_added_line(2, lines[1])

    problems = csr.check_diff(diff, lines)

    assert problems == []


def test_skip_marker_no_final_da_propria_linha_suprime() -> None:
    text = f"Número solto: 99 unidades, decisão de prosa. {csr._SKIP_MARKER}"
    diff = _diff_for_single_added_line(1, text)
    lines = [text]

    problems = csr.check_diff(diff, lines)

    assert problems == []


def test_linha_sem_numero_nao_precisa_de_referencia() -> None:
    text = "Prosa qualquer sem número nenhum aqui."
    diff = _diff_for_single_added_line(1, text)
    lines = [text]

    assert csr.check_diff(diff, lines) == []
