"""Testes de `src/labels/backfill_multi_symbol.py` — só o ROTEAMENTO de
argumentos (`symbol`/`tf`/`version`/`historical_filters_fallback`) até
`build_labels_for_symbol_with_stats`/`write_labels_atomic`/`record_
experiment`, via monkeypatch (sem IO real — `build_labels_for_symbol_
with_stats` já é testada a fundo em `test_labels_triple_barrier.py`, não
precisa ser reexercitada aqui).

AG-128 (F1, achado `audit_engineering` 2026-08-19) — `build_and_write_
labels_for_symbol` passou a chamar `build_labels_for_symbol_with_stats`
(em vez de `build_labels_for_symbol`) e `record_experiment` de verdade.
Todo teste que exercita `build_and_write_labels_for_symbol` precisa
mockar `record_experiment` OU redirecionar `experiment_log.LOG_PATH` pra
`tmp_path` — nunca deixar a chamada real cair no `experiments/label_
engine_runs.parquet` de produção (mesmo cuidado que `_fake_write_labels_
atomic` já tinha com `dest_dir` de produção, ver comentário abaixo)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from src.labels import backfill_multi_symbol as bms
from src.labels import triple_barrier as tb
from src.labels._paths import labels_symbol_tf_dir


def _empty_labels() -> pl.DataFrame:
    """1 linha MÍNIMA VÁLIDA (não 0 linhas) que satisfaz as 6 invariantes de
    `tb.assert_label_invariants` -- chamada real dentro de `build_and_write_
    labels_for_symbol` desde a correção de AG-029 (`src/labels/backfill_
    multi_symbol.py:103`), "falha alto de propósito". Um DataFrame de 0
    linhas não serve: `config_hash.n_unique() == 1` (§3.8) é sempre falso
    sobre uma coluna vazia (`n_unique()` de série vazia é 0, não 1) --
    não dá pra simplesmente completar o schema faltante (`t1`/`t_entry`/
    `barrier_hit`/`config_hash`/`sample_weight`/`uniqueness`) mantendo 0
    linhas, como uma 1ª tentativa desta correção fez e ainda falhava.
    `held_ms=60_000` (1min) fica bem abaixo de qualquer `time_stop_ms` real
    configurado (ordem de horas) -- não hardcoda o valor real, só garante
    folga. Mantém o nome `_empty_labels` (não `_minimal_labels`) porque o
    propósito do teste continua sendo "roteamento de argumentos", não
    conteúdo de label -- só o suficiente pra passar pela validação real que
    o caminho de produção agora aplica.

    `n_bars_held=0` (AG-116, 2026-08-20) -- `assert_label_invariants` sob
    `resolution_id` (dollar bar) agora lê esta coluna pro teto `n_bars_
    held <= horizon_bars` (em vez de `held_ms <= time_stop_ms`, ver
    `build_and_write_labels_for_symbol`). `0` é seguro contra QUALQUER
    `horizon_bars >= 1` real (a validação de `LabelConfig.__post_init__`
    já garante `horizon_bars >= 1`), sem hardcodar o valor real -- mesmo
    espírito de `held_ms=60_000` acima.

    `ret_net=0.001` (AG-128, F1) -- `record_experiment` (agora chamado de
    verdade em `build_and_write_labels_for_symbol`, ver módulo) roda
    `summarize_labels` internamente, que lê `labels["ret_net"]` -- ausente
    até esta correção porque nenhum teste deste arquivo exercitava
    `record_experiment` real. Valor arbitrário não-zero só pra existir a
    coluna com o tipo certo (Float64); nenhum teste aqui afirma nada sobre
    o VALOR de `mean_ret_net`/`std_ret_net` resultante."""
    tz_ms = pl.Datetime("ms", time_zone="UTC")
    return pl.DataFrame(
        {
            "t0": pl.Series([0], dtype=pl.Int64).cast(tz_ms),
            "t1": pl.Series([60_000], dtype=pl.Int64).cast(tz_ms),
            "t_entry": pl.Series([0], dtype=pl.Int64).cast(tz_ms),
            "ret_net": pl.Series([0.001], dtype=pl.Float64),
            "barrier_hit": pl.Series(["TP"], dtype=pl.Categorical),
            "config_hash": ["fake_routing_test"],
            "sample_weight": [1.0],
            "n_bars_held": [0],
            "uniqueness": [1.0],
        }
    )


def test_build_and_write_labels_for_symbol_roteia_ate_build_e_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    build_calls: list[dict[str, Any]] = []
    write_calls: list[dict[str, Any]] = []
    record_calls: list[dict[str, Any]] = []

    def _fake_build_labels_for_symbol_with_stats(
        symbol: str,
        start: Any,
        end: Any,
        *,
        config: tb.LabelConfig | None = None,
        estimator: Any = None,
        historical_filters_fallback: bool = False,
    ) -> tuple[pl.DataFrame, tb.LabelBuildStats]:
        build_calls.append(
            {
                "symbol": symbol,
                "start": start,
                "end": end,
                "tf": config.tf if config is not None else None,
                "historical_filters_fallback": historical_filters_fallback,
            }
        )
        return _empty_labels(), tb.LabelBuildStats(
            n_warmup_dropped=0, n_incomplete_tail=0, n_tie_break=0
        )

    def _fake_write_labels_atomic(
        labels: pl.DataFrame, *, version: str = "v1", dest_dir: Path | None = None
    ) -> Path:
        # Sem IO real de propósito (achado ao rodar o smoke test da Fase 5,
        # 2026-08-17): a versão anterior deste fake fazia `dest_dir.mkdir(...)`
        # sobre o path de PRODUÇÃO real (`data/labels/{symbol}/{grade}/v1/`),
        # deixando diretório vazio pra trás quando o path ainda não existia --
        # inofensivo pro grade de tempo (path já existia, mkdir virava no-op),
        # mas poluiu `data/labels/BTCUSDT/R1/v1/` de verdade, exatamente o
        # path que o backfill real (Fase 5) ia escrever depois. Este teste só
        # precisa provar ROTEAMENTO (dest_dir correto), não criar nada no
        # disco real.
        write_calls.append({"version": version, "dest_dir": dest_dir})
        assert dest_dir is not None
        return dest_dir / "labels.parquet"

    def _fake_record_experiment(
        labels: pl.DataFrame, config: tb.LabelConfig, **kwargs: Any
    ) -> Path:
        # AG-128 (F1) -- mockado de propósito, mesmo motivo de `write_labels_
        # atomic` acima: sem isso, este teste gravaria uma linha real em
        # `data/label_engine_runs/label_engine_runs.parquet` (produção) a cada rodada da
        # suíte. Wiring de verdade (record_experiment REAL sendo chamado e
        # persistindo os 3 campos de LabelBuildStats) é provado à parte, ver
        # test_build_and_write_labels_for_symbol_registra_experiment_log_com_
        # stats abaixo.
        record_calls.append({"symbol": kwargs.get("symbol"), "config_hash": config.config_hash})
        return tmp_path / "fake_runs.parquet"

    monkeypatch.setattr(
        bms, "build_labels_for_symbol_with_stats", _fake_build_labels_for_symbol_with_stats
    )
    monkeypatch.setattr(bms, "write_labels_atomic", _fake_write_labels_atomic)
    monkeypatch.setattr(bms, "record_experiment", _fake_record_experiment)

    bms.build_and_write_labels_for_symbol(
        "ETHUSDT", "2021-12-01", "2026-08-07", version="v1", tf="15m"
    )

    assert build_calls == [
        {
            "symbol": "ETHUSDT",
            "start": "2021-12-01",
            "end": "2026-08-07",
            "tf": "15m",
            "historical_filters_fallback": True,
        }
    ]
    assert write_calls == [
        {"version": "v1", "dest_dir": labels_symbol_tf_dir("ETHUSDT", "v1", tf="15m")}
    ]
    assert len(record_calls) == 1
    assert record_calls[0]["symbol"] == "ETHUSDT"


def test_build_and_write_labels_for_symbol_anexa_contexto_em_qualquer_excecao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG-100 F3 (achado `project_assurance`, 2026-08-22) -- o único
    try/except pré-existente (AG-029) só cobria `AssertionError` de
    `assert_label_invariants`; o crash real do backfill R2/R3 (`ValueError`
    em `_mfe_price`, AG-100 F1) vinha de `build_labels_for_symbol_with_
    stats`, ANTES daquele bloco -- `symbol`/`resolution_id` não sobreviviam
    nem no traceback nem na mensagem, só via reprodução manual fora do
    `ProcessPoolExecutor`. Prova que QUALQUER exceção (não só
    `AssertionError`) agora carrega `symbol`/`tf`/`resolution_id` via
    `exc.add_note` (PEP 678) -- tipo/mensagem originais preservados
    intactos (nunca reconstruídos), `raise` simples re-levanta a MESMA
    exceção."""

    def _raising_build(
        symbol: str,
        start: Any,
        end: Any,
        *,
        config: tb.LabelConfig | None = None,
        estimator: Any = None,
        historical_filters_fallback: bool = False,
    ) -> tuple[pl.DataFrame, tb.LabelBuildStats]:
        raise ValueError("zero-size array to reduction operation maximum which has no identity")

    monkeypatch.setattr(bms, "build_labels_for_symbol_with_stats", _raising_build)

    with pytest.raises(ValueError) as exc_info:
        bms.build_and_write_labels_for_symbol(
            "SOLUSDT", "2021-12-01", "2026-08-07", version="v1", resolution_id="R2"
        )

    exc = exc_info.value
    assert "zero-size array" in str(exc)  # mensagem original preservada, não reconstruída
    notes = getattr(exc, "__notes__", [])
    assert len(notes) == 1
    assert "SOLUSDT" in notes[0]
    assert "R2" in notes[0]


def test_run_and_write_labels_for_alts_cobre_os_4_alts_sem_btc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BTCUSDT não entra em `ALT_SYMBOLS` -- já tem `labels/v1/` completo,
    esta rodada é especificamente sobre os 4 que nunca tiveram (ver
    docstring do módulo).

    `ProcessPoolExecutor` real spawnaria um subprocesso que reimporta
    `bms` do zero -- o monkeypatch deste processo não alcançaria lá
    dentro, e o teste tentaria IO real (dado ausente pros alts hoje,
    ver docstring do módulo). Troca por `ThreadPoolExecutor` (mesma
    interface `submit`/`as_completed`, executa na mesma memória de
    processo) só pra este teste -- suficiente pra provar o roteamento
    (quais símbolos são chamados, resultado agregado), não uma alegação
    sobre paralelismo real entre processos."""
    assert bms.ALT_SYMBOLS == ("ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    assert "BTCUSDT" not in bms.ALT_SYMBOLS

    seen_symbols: list[str] = []

    def _fake_build_and_write(
        symbol: str,
        start: Any,
        end: Any,
        *,
        version: str = "v1",
        tf: str = "15m",
        config: Any = None,
    ) -> Path:
        seen_symbols.append(symbol)
        return Path(f"/fake/{symbol}/labels.parquet")

    monkeypatch.setattr(bms, "build_and_write_labels_for_symbol", _fake_build_and_write)
    monkeypatch.setattr(bms, "ProcessPoolExecutor", ThreadPoolExecutor)

    # `confirmo_grade_de_relogio_legada=True` (`AG-248`) -- este teste
    # exercita deliberadamente o writer da grade LEGADA, que desde 2026-08-25
    # exige confirmação explícita para não ser acionado por acidente. Passar o
    # flag aqui é declarar essa intenção, não contornar a guarda: o teste
    # continua provando exatamente o que provava (roteamento dos 4 alts, sem
    # BTCUSDT).
    results = bms.run_and_write_labels_for_alts(
        max_workers=1, confirmo_grade_de_relogio_legada=True
    )

    assert set(results) == set(bms.ALT_SYMBOLS)
    assert set(seen_symbols) == set(bms.ALT_SYMBOLS)


# ============================================================================
# Fase 5 (2026-08-17) -- resolution_id/estimator, run_and_write_labels_
# dollar_bar_parkinson
# ============================================================================


def test_build_and_write_labels_for_symbol_resolution_id_usa_path_novo_e_repassa_estimator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resolution_id="R1"` produz um `dest_dir` DIFERENTE de `tf="15m"`
    (guarda anti-colisão, Fase 1) -- e `estimator` chega de fato até
    `build_labels_for_symbol`, não é descartado."""
    from src.features.volatility import ParkinsonEstimator

    build_calls: list[dict[str, Any]] = []
    write_calls: list[dict[str, Any]] = []

    def _fake_build_labels_for_symbol_with_stats(
        symbol: str,
        start: Any,
        end: Any,
        *,
        config: tb.LabelConfig | None = None,
        estimator: Any = None,
        historical_filters_fallback: bool = False,
    ) -> tuple[pl.DataFrame, tb.LabelBuildStats]:
        build_calls.append(
            {
                "resolution_id": config.resolution_id if config is not None else None,
                "estimator_id": estimator.estimator_id if estimator is not None else None,
            }
        )
        return _empty_labels(), tb.LabelBuildStats(
            n_warmup_dropped=0, n_incomplete_tail=0, n_tie_break=0
        )

    def _fake_write_labels_atomic(
        labels: pl.DataFrame, *, version: str = "v1", dest_dir: Path | None = None
    ) -> Path:
        # Sem IO real de propósito -- ver comentário do fake irmão acima
        # (achado do smoke test da Fase 5: mkdir sobre path de produção real
        # deixa diretório vazio pra trás).
        write_calls.append({"dest_dir": dest_dir})
        assert dest_dir is not None
        return dest_dir / "labels.parquet"

    def _fake_record_experiment(
        labels: pl.DataFrame, config: tb.LabelConfig, **kwargs: Any
    ) -> Path:
        # AG-128 (F1) -- mesmo motivo do fake irmão em
        # test_build_and_write_labels_for_symbol_roteia_ate_build_e_write:
        # sem isso, gravaria em data/label_engine_runs/label_engine_runs.parquet real.
        return Path("/fake/runs.parquet")

    monkeypatch.setattr(
        bms, "build_labels_for_symbol_with_stats", _fake_build_labels_for_symbol_with_stats
    )
    monkeypatch.setattr(bms, "write_labels_atomic", _fake_write_labels_atomic)
    monkeypatch.setattr(bms, "record_experiment", _fake_record_experiment)

    estimator = ParkinsonEstimator(window=20)
    cfg = tb.LabelConfig.from_constants(estimator_id=estimator.estimator_id, resolution_id="R1")
    bms.build_and_write_labels_for_symbol(
        "BTCUSDT", "2020-01-01", "2026-08-06", resolution_id="R1", config=cfg, estimator=estimator
    )

    assert build_calls == [{"resolution_id": "R1", "estimator_id": "parkinson_w20"}]
    dest_dir = write_calls[0]["dest_dir"]
    assert "R1" in dest_dir.parts
    assert "15m" not in dest_dir.parts
    assert dest_dir == labels_symbol_tf_dir("BTCUSDT", "v1", resolution_id="R1")


# ============================================================================
# AG-128 (F1/F2) — record_experiment de verdade, wiring completo até
# experiment_log (não mockado, diferente dos testes acima)
# ============================================================================


def test_build_and_write_labels_for_symbol_registra_experiment_log_com_stats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prova de wiring de ponta a ponta (F1+F2, AG-128): `build_and_write_
    labels_for_symbol` chama `record_experiment` de VERDADE (a função real
    de `src.labels.experiment_log`, não um fake) — só `build_labels_for_
    symbol_with_stats`/`write_labels_atomic` são substituídos (sintético,
    sem IO real de mercado, mesmo padrão dos testes acima) e `experiment_
    log.LOG_PATH` é redirecionado pra `tmp_path` (sem isso, a chamada real
    cairia em `data/label_engine_runs/label_engine_runs.parquet` de produção).

    Antes desta correção, `record_experiment` NUNCA era chamado neste
    caminho apesar do schema já existir e já ser testado isoladamente
    (`test_labels_experiment_log.py`) -- este teste falharia (0 linhas no
    log) contra o código pré-AG-128."""
    from src.labels import experiment_log as experiment_log_module

    log_path = tmp_path / "runs.parquet"
    monkeypatch.setattr(experiment_log_module, "LOG_PATH", log_path)

    stats = tb.LabelBuildStats(n_warmup_dropped=3, n_incomplete_tail=1, n_tie_break=2)

    def _fake_build_labels_for_symbol_with_stats(
        symbol: str,
        start: Any,
        end: Any,
        *,
        config: tb.LabelConfig | None = None,
        estimator: Any = None,
        historical_filters_fallback: bool = False,
    ) -> tuple[pl.DataFrame, tb.LabelBuildStats]:
        return _empty_labels(), stats

    def _fake_write_labels_atomic(
        labels: pl.DataFrame, *, version: str = "v1", dest_dir: Path | None = None
    ) -> Path:
        assert dest_dir is not None
        return dest_dir / "labels.parquet"

    monkeypatch.setattr(
        bms, "build_labels_for_symbol_with_stats", _fake_build_labels_for_symbol_with_stats
    )
    monkeypatch.setattr(bms, "write_labels_atomic", _fake_write_labels_atomic)
    # `record_experiment` NÃO é mockado aqui -- é a função real de
    # `bms.record_experiment` (importada em backfill_multi_symbol.py), a
    # mesma que test_labels_experiment_log.py exercita isoladamente. O
    # ponto deste teste é provar que ELA é chamada, não substituí-la.

    cfg = tb.LabelConfig.from_constants(tf="15m")
    bms.build_and_write_labels_for_symbol(
        "ETHUSDT", "2021-12-01", "2021-12-02", version="v1", tf="15m", config=cfg
    )

    out = experiment_log_module.load_experiment_log(log_path)
    assert out.height == 1
    assert out["symbol"][0] == "ETHUSDT"
    assert out["period_start"][0] == "2021-12-01"
    assert out["period_end"][0] == "2021-12-02"
    assert out["stage"][0] == "labels_build"
    assert out["config_hash"][0] == cfg.config_hash
    assert out["n_warmup_dropped"][0] == 3
    assert out["n_incomplete_tail"][0] == 1
    assert out["n_tie_break"][0] == 2


def test_run_and_write_labels_dollar_bar_parkinson_cobre_os_5_simbolos_incluindo_btc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diferente de `run_and_write_labels_for_alts` (exclui BTCUSDT de
    propósito), esta função cobre os 5 -- nenhum símbolo tem `labels/`
    sob R1 ainda."""
    assert bms.ALL_SYMBOLS == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    assert set(bms.SYMBOL_START_DATE) == set(bms.ALL_SYMBOLS)
    assert bms.SYMBOL_START_DATE["BTCUSDT"] == "2020-01-01"
    for alt in bms.ALT_SYMBOLS:
        assert bms.SYMBOL_START_DATE[alt] == bms.ALT_START_DATE

    calls: list[dict[str, Any]] = []

    def _fake_build_and_write(
        symbol: str,
        start: Any,
        end: Any,
        *,
        version: str = "v1",
        resolution_id: str | None = None,
        config: Any = None,
        estimator: Any = None,
    ) -> Path:
        calls.append(
            {
                "symbol": symbol,
                "start": start,
                "resolution_id": resolution_id,
                "estimator_id": estimator.estimator_id if estimator is not None else None,
                "grade_id": config.resolution_id if config is not None else None,
            }
        )
        return Path(f"/fake/{symbol}/labels.parquet")

    monkeypatch.setattr(bms, "build_and_write_labels_for_symbol", _fake_build_and_write)
    monkeypatch.setattr(bms, "ProcessPoolExecutor", ThreadPoolExecutor)

    results = bms.run_and_write_labels_dollar_bar_parkinson(max_workers=1)

    assert set(results) == set(bms.ALL_SYMBOLS)
    calls_by_symbol = {c["symbol"]: c for c in calls}
    assert set(calls_by_symbol) == set(bms.ALL_SYMBOLS)
    for symbol, call in calls_by_symbol.items():
        assert call["start"] == bms.SYMBOL_START_DATE[symbol]
        assert call["resolution_id"] == "R1"
        assert call["grade_id"] == "R1"
        assert call["estimator_id"] == "parkinson_w20"


# ============================================================================
# AG-248 — guardas de grade no writer (achado de AG-247)
# ============================================================================


def test_writer_da_grade_legada_exige_confirmacao_explicita() -> None:
    """`AG-248` — `run_and_write_labels_for_alts` é o ÚNICO caminho no repo
    que grava em `data/labels/{symbol}/15m/v1/`, a grade substituída como
    canônica por dollar bar em `AG-042`.

    Até 2026-08-25 ela era o `__main__` do módulo: `python -m
    src.labels.backfill_multi_symbol` gravava na grade legada sem argumento
    nenhum e sem aviso. `AG-233` registrou que os cinco `labels.parquet` de
    15m foram regravados por processo externo sem registro em
    `label_engine_runs`, e `AG-247` identificou esta função como o único
    caminho capaz de fazê-lo.

    Se este teste falhar, gravar na grade substituída voltou a ser possível
    por acidente."""
    with pytest.raises(ValueError, match="confirmo_grade_de_relogio_legada"):
        bms.run_and_write_labels_for_alts(max_workers=1)


def test_main_do_modulo_nao_grava_nada_e_exige_escolha_de_writer() -> None:
    """`AG-248` — o `__main__` deixou de ter entrada default: a escolha da
    grade é decisão, não default. Ele deve levantar `SystemExit` citando os
    DOIS writers, para que quem rodar saiba qual quer."""
    import runpy

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("src.labels.backfill_multi_symbol", run_name="__main__")
    msg = str(exc.value)
    assert "run_and_write_labels_dollar_bar_parkinson" in msg
    assert "run_and_write_labels_for_alts" in msg
    assert "AG-248" in msg


def test_writer_de_producao_nao_sobrescreve_entry_fill_source_por_default() -> None:
    """`AG-248` — o defeito mais perigoso que a auditoria de `AG-247`
    encontrou neste módulo, porque era SILENCIOSO e ia na direção de desfazer
    trabalho já feito.

    `run_and_write_labels_dollar_bar_parkinson` tinha
    `entry_fill_source: str = ENTRY_FILL_SOURCE_MARK_1M` na assinatura, e
    aplicava esse valor por cima do que `LabelConfig.from_constants` acabava
    de resolver. Depois de `AG-236`, `from_constants` entrega `agg_trades`
    (de `constants.yaml::label_entry_fill_source`) — então rodar o writer de
    PRODUÇÃO sem argumentos regravaria os 15 artefatos sob o regime de fill
    enviesado, desfazendo o relabel de `AG-229` sem erro nem aviso.

    O default agora é `None` = "não sobrescreva".
    """
    import inspect

    sig = inspect.signature(bms.run_and_write_labels_dollar_bar_parkinson)
    assert sig.parameters["entry_fill_source"].default is None, (
        "entry_fill_source voltou a ter um default que sobrescreve "
        "constants.yaml::label_entry_fill_source (AG-248)"
    )
    assert sig.parameters["vol_estimator_window"].default is None, (
        "vol_estimator_window voltou a ter literal no default em vez de "
        "derivar de constants.yaml::atr_window (AG-248/§16.10 regra 1)"
    )
