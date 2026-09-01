"""Testes de `src/validation/cpcv.py` — splitter combinatório real, purge
por `t1`, embargo, e 1-fatoração de caminhos de backtest.

`_make_synthetic_labels` cobre a mecânica com dados pequenos e controlados
(fronteiras de grupo conhecidas de antemão). Os testes contra
`labels/v1/labels.parquet` REAL (462.682 linhas, Sprint 6) ficam na seção
final — são o teste 6 do §11.5 (contaminação de label) rodando de verdade,
não só sobre sintético."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.data.resample import step_ms
from src.validation import cpcv
from src.validation._paths import labels_symbol_tf_dir

_BAR_MS = 900_000  # 15m


def _make_synthetic_labels(
    n: int, *, side: int = 1, horizon_bars: int = 4, start_ms: int = 0, bar_ms: int = _BAR_MS
) -> pl.DataFrame:
    """`n` labels sintéticos com `t0` em barras CONSECUTIVAS espaçadas de
    `bar_ms` (default 15m) e `t1 = t0 + horizon_bars * bar_ms` (horizonte
    fixo, análogo a um `time_stop_bars` pequeno) — o suficiente para
    exercitar purge/embargo sem precisar do dataset real.

    `bar_ms` (AG-009) — antes desta correção o espaçamento era sempre
    `_BAR_MS` (15m) independente do `tf` de um `CPCVConfig` associado,
    truque usado pelos testes AG-004 originais para simular um "TF
    diferente" sem reescrever a fixture. Isso agora colide de propósito
    com `assert_grade_consistent` (a própria guarda AG-009/AG-037 que esta
    rodada adiciona) — dado espaçado em 15m analisado com `config.tf="30m"`
    é EXATAMENTE o cenário que a guarda existe para rejeitar. `bar_ms`
    deixa o chamador declarar um espaçamento que bate de verdade com o
    `tf` do `CPCVConfig` usado no teste."""
    t0_ms = [start_ms + i * bar_ms for i in range(n)]
    t1_ms = [t + horizon_bars * bar_ms for t in t0_ms]
    return pl.DataFrame(
        {
            "t0": pl.Series(t0_ms).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "t1": pl.Series(t1_ms).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "side": pl.Series([side] * n, dtype=pl.Int8),
            "sample_weight": pl.Series([1.0] * n, dtype=pl.Float64),
        }
    )


_CFG = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS)


# ============================================================================
# CPCVConfig
# ============================================================================


def test_config_n_splits_e_n_backtest_paths_batem_com_o_prd() -> None:
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=175 * _BAR_MS)
    assert cfg.n_splits == 15  # C(6,2), §11.4
    assert cfg.n_backtest_paths == 5  # C(5,1), §11.4


def test_config_rejeita_n_test_groups_invalido() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.CPCVConfig(n_groups=6, n_test_groups=0, embargo_ms=1)
    with pytest.raises(cpcv.CPCVError):
        cpcv.CPCVConfig(n_groups=6, n_test_groups=6, embargo_ms=1)


def test_config_rejeita_embargo_negativo() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=-1)


def test_config_from_constants_le_constants_yaml() -> None:
    """AG-032/E1 (2026-08-16) -- embargo_ms=347_010_000 (96,39h) é o valor
    MEDIDO real (tools/diagnostics/measure_cpcv_embargo_clock_candidate.py),
    não mais o legado embargo_bars=175 (43,75h) -- ver constants.yaml pra
    proveniência completa."""
    cfg = cpcv.CPCVConfig.from_constants()
    assert cfg.n_groups == 6
    assert cfg.n_test_groups == 2
    assert cfg.embargo_ms == 347_010_000


# ============================================================================
# AG-004 — tf deixa de ser _BAR_MS hardcoded em 15m
# ============================================================================


def test_config_tf_default_e_15m_bit_exato() -> None:
    """Todo caller existente no repo constrói CPCVConfig sem `tf` — o
    default precisa preservar exatamente o comportamento de antes da
    correção AG-004 (_BAR_MS fixo em step_ms("15m"))."""
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS)
    assert cfg.tf == "15m"

    cfg_from_constants = cpcv.CPCVConfig.from_constants()
    assert cfg_from_constants.tf == "15m"


def test_config_rejeita_tf_desconhecido() -> None:
    from src.data.resample import UnsupportedTimeframeError

    with pytest.raises(UnsupportedTimeframeError):
        cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, tf="7m")


def test_embargo_ms_e_invariante_a_tf_nao_escala_mais() -> None:
    """Histórico invertido de propósito, não apagado. O achado real de
    AG-004 (fechado por essa rodada): embargo em 30m tinha que ser 2x o de
    15m pro MESMO embargo_bars, porque cada barra de 30m cobre o dobro do
    tempo -- _BAR_MS fixo em 15m escondia isso silenciosamente. Esse bug
    inteiro deixou de poder EXISTIR com a correção AG-032/E1: `embargo_ms`
    é relógio direto (medido, `constants.yaml::cpcv_embargo_ms`), nunca
    mais `embargo_bars * step_ms(tf)` -- não há mais aritmética de `tf`
    pra escalar errado. Este teste agora prova o INVARIANTE OPOSTO do que
    provava antes: `_embargo_ms` é o MESMO valor não importa qual `tf` o
    `CPCVConfig` declara -- se algum dia alguém reintroduzir uma
    dependência de `tf` aqui (ex. reacoplando embargo a contagem de barra,
    Opção E2 rejeitada em AG-032), este teste quebra."""
    cfg_15m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=4 * _BAR_MS, tf="15m")
    cfg_30m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=4 * _BAR_MS, tf="30m")

    embargo_ms_15m = cpcv._embargo_ms(cfg_15m)
    embargo_ms_30m = cpcv._embargo_ms(cfg_30m)

    assert embargo_ms_15m == 4 * _BAR_MS
    assert embargo_ms_30m == embargo_ms_15m, (
        "embargo_ms não deve variar com tf -- é relógio direto, não mais "
        f"contagem de barra convertida ({embargo_ms_30m} vs {embargo_ms_15m})"
    )


def test_generate_splits_e_assert_embargo_respected_usam_o_mesmo_embargo_ms(
) -> None:
    """`generate_splits` (que aplica o embargo) e `assert_embargo_respected`
    (que checa que ele foi respeitado) precisam usar o MESMO `embargo_ms`
    -- senão a própria checagem (que deveria pegar violação) ficaria
    calibrada pra um valor diferente e passaria silenciosamente. Os dois
    chamam literalmente `_embargo_ms` (extraído em AG-009, simplificado em
    AG-032/E1 pra retornar `config.embargo_ms` direto) em vez de duas
    cópias inline. Continua rodando com `tf="30m"` e dado genuinamente
    espaçado em 30m -- não porque `embargo_ms` dependa de `tf` (não
    depende mais), mas porque `assert_grade_consistent` (AG-009/AG-037,
    ainda ativa por outros motivos) rejeitaria a combinação se não
    batesse."""
    n = 600
    labels = _make_synthetic_labels(n, horizon_bars=1, bar_ms=step_ms("30m"))
    cfg_30m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=4 * step_ms("30m"), tf="30m")
    result = cpcv.generate_splits(labels, cfg_30m)
    assert sum(s.n_embargoed for s in result.splits) > 0
    cpcv.assert_embargo_respected(labels, result)  # não deve levantar


def test_generate_splits_e_assert_no_train_t1_leaks_usam_a_mesma_g_end_effective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`generate_splits` (que aplica o purge do componente 32, item 2b da
    docstring do módulo, AG-032/E4) e `assert_no_train_t1_leaks_into_test`
    (que verifica que ele foi respeitado) precisam usar a MESMA fórmula de
    `g_end_effective` -- senão a própria checagem poderia ficar calibrada
    para uma fronteira mais fraca que a que o purge de fato aplica, e não
    pegaria uma regressão real (achado F1, candidato a AG-129, auditoria
    2026-08-19). Os dois agora chamam literalmente `_g_end_effective`
    (extraída em função própria, mesmo padrão de `_embargo_ms`/AG-009 --
    ver `test_generate_splits_e_assert_embargo_respected_usam_o_mesmo_
    embargo_ms` acima) em vez de duas cópias inline.

    Prova ESTRUTURAL, não só comportamental (comportamento correto já é
    coberto por `test_generate_splits_purge_cobre_lookback_de_feature_de_
    treino_apos_g_end` e por `test_assert_no_train_t1_leaks_detecta_
    vazamento_forjado`): spy sobre a função REAL (não um fake que pula a
    execução -- mesmo padrão de `test_run_all_leakage_tests_repassa_
    symbol_a_generate_splits_dos_testes_6_7_12` em
    tests/unit/test_validation_leakage.py) prova que AMBOS os call-sites de
    fato invocam a MESMA função. Um bug de divergência (alguém
    reintroduzindo a fórmula inline num dos dois lugares, sem tocar no
    outro) faria a contagem de chamadas do lado editado divergir do
    esperado, mesmo que o resultado numérico deste cenário específico ainda
    parecesse correto -- exatamente o tipo de regressão silenciosa que a
    extração em AG-009 já preveniu para `embargo_ms`."""
    n = 1200
    labels = _make_synthetic_labels(n, horizon_bars=20)  # horizonte grande -- overlap real
    cfg_sem_embargo = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=0)

    real_g_end_effective = cpcv._g_end_effective
    calls: list[int] = []

    def _spy_g_end_effective(
        g: int, g_end: int, group_id: np.ndarray, t1_ms: np.ndarray
    ) -> int:
        calls.append(g)
        return real_g_end_effective(g, g_end, group_id, t1_ms)

    monkeypatch.setattr(cpcv, "_g_end_effective", _spy_g_end_effective)

    result = cpcv.generate_splits(labels, cfg_sem_embargo)
    n_calls_apos_generate = len(calls)
    assert n_calls_apos_generate > 0, "generate_splits precisa chamar _g_end_effective"

    cpcv.assert_no_train_t1_leaks_into_test(labels, result)
    assert len(calls) > n_calls_apos_generate, (
        "assert_no_train_t1_leaks_into_test precisa chamar a MESMA _g_end_effective de "
        "generate_splits, não uma cópia inline -- senão a checagem pode validar contra "
        "uma fronteira diferente da que o purge de fato usou"
    )


# ============================================================================
# AG-009/AG-037 — assert_grade_consistent: guarda cruzada entre a grade real
# de `labels` e `CPCVConfig.grade_id`. `load_labels_v1(tf=...)` e
# `CPCVConfig(tf=...)` são dois parâmetros independentes hoje (nenhuma
# ligação estrutural entre os dois) -- esta guarda mede o espaçamento REAL
# de `t0` contra `step_ms(config.grade_id)` e falha alto se divergirem, em
# vez de computar o embargo na unidade errada silenciosamente. Renomeada de
# `assert_tf_consistent` (AG-037, 2026-08-16) -- ver docstring da função.
# ============================================================================


def test_assert_grade_consistent_aceita_default_15m_bit_exato() -> None:
    """Caso consistente -- dado sintético espaçado em 15m (`_BAR_MS`, o
    default de `_make_synthetic_labels`) contra `CPCVConfig` default
    (`tf="15m"`, `grade_id` deriva pra `"15m"`) não deve levantar, e
    `generate_splits` continua produzindo exatamente os mesmos 15 splits/5
    caminhos de sempre -- a guarda é read-only (não muda `t0_ms`/`t1_ms`/
    grupos/purge/embargo), então bit-exatidão do resultado segue por
    construção, não por coincidência de teste."""
    labels = _make_synthetic_labels(600, horizon_bars=1)
    cpcv.assert_grade_consistent(labels, _CFG)  # não deve levantar

    result = cpcv.generate_splits(labels, _CFG)
    assert len(result.splits) == 15
    assert result.config.n_backtest_paths == 5


def test_assert_grade_consistent_aceita_tf_explicito_consistente() -> None:
    """Não é só o default 15m -- qualquer `tf` suportado cujo dado bata
    com o espaçamento declarado passa (`grade_id` deriva de `tf`)."""
    labels = _make_synthetic_labels(600, horizon_bars=1, bar_ms=step_ms("30m"))
    cfg_30m = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, tf="30m")
    cpcv.assert_grade_consistent(labels, cfg_30m)  # não deve levantar


def test_assert_grade_consistent_aceita_grade_id_explicito_diferente_de_tf() -> None:
    """AG-037 -- `grade_id` passado explícito é RESPEITADO, não só derivado
    de `tf`. `tf="15m"` aqui é decorativo (usado só se `grade_id` fosse
    `None`) -- o `step_ms` real que a guarda mede vem de `grade_id="30m"`,
    então dado espaçado em 30m precisa bater com ISSO, não com `tf`."""
    labels = _make_synthetic_labels(600, horizon_bars=1, bar_ms=step_ms("30m"))
    cfg = cpcv.CPCVConfig(
        n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, tf="15m", grade_id="30m"
    )
    assert cfg.grade_id == "30m"  # não foi sobrescrito por tf
    cpcv.assert_grade_consistent(labels, cfg)  # não deve levantar


def test_assert_grade_consistent_grade_id_dollar_bar_sem_symbol_levanta_valueerror() -> None:
    """AG-042 (2026-08-17) -- `grade_id` dollar-bar (R1/R2/R3) exige
    `symbol` pra localizar `_calibration.json`; sem ele, `ValueError`
    explícito, nunca pula a checagem silenciosamente (substitui o
    `NotImplementedError` antigo -- o mecanismo agora existe de verdade)."""
    labels = _make_synthetic_labels(600, horizon_bars=1)
    cfg = cpcv.CPCVConfig(
        n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, tf="15m", grade_id="R1"
    )
    with pytest.raises(ValueError, match="symbol"):
        cpcv.assert_grade_consistent(labels, cfg)


def test_assert_grade_consistent_dollar_bar_sem_calibracao_levanta_cpcverror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`grade_id="R1"` com `symbol` mas sem `_calibration.json` no disco --
    CPCVError explícito, não deixa passar silenciosamente."""
    from src.data import _paths as data_paths

    monkeypatch.setattr(data_paths, "CAPACITY_DIR", tmp_path)
    monkeypatch.setattr(cpcv, "CAPACITY_DIR", tmp_path)
    labels = _make_synthetic_labels(600, horizon_bars=1)
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, grade_id="R1")
    with pytest.raises(cpcv.CPCVError, match="calibração"):
        cpcv.assert_grade_consistent(labels, cfg, symbol="BTCUSDT")


def _write_fake_calibration(root: Path, symbol: str, resolution_id: str) -> None:
    import orjson

    from src.data.build_dollar_bars import DollarBarCalibration

    symbol_dir = root / f"dollar_bars_{resolution_id.lower()}" / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    calibration = DollarBarCalibration(
        symbol=symbol,
        resolution_id=resolution_id,
        threshold_usdt=1_000_000.0,
        calibration_scope="validation",
        calibration_window_start="2020-01-01",
        calibration_window_end="2026-08-07",
        n_trades=1_000,
        calibrated_at="2026-08-17T00:00:00+00:00",
    )
    (symbol_dir / "_calibration.json").write_bytes(orjson.dumps(dataclasses.asdict(calibration)))


def test_assert_grade_consistent_dollar_bar_calibracao_batendo_nao_levanta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.data import _paths as data_paths

    monkeypatch.setattr(data_paths, "CAPACITY_DIR", tmp_path)
    monkeypatch.setattr(cpcv, "CAPACITY_DIR", tmp_path)
    _write_fake_calibration(tmp_path, "BTCUSDT", "R1")

    labels = _make_synthetic_labels(600, horizon_bars=1)
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, grade_id="R1")
    cpcv.assert_grade_consistent(labels, cfg, symbol="BTCUSDT")  # não deve levantar

    # generate_splits também aceita e propaga symbol corretamente
    result = cpcv.generate_splits(labels, cfg, symbol="BTCUSDT")
    assert len(result.splits) == 15


def test_assert_grade_consistent_dollar_bar_calibracao_resolution_id_divergente_levanta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calibração real existe, mas foi escrita pra uma resolução diferente
    da que o config espera -- achado de robustez, não deve passar batido."""
    from src.data import _paths as data_paths

    monkeypatch.setattr(data_paths, "CAPACITY_DIR", tmp_path)
    monkeypatch.setattr(cpcv, "CAPACITY_DIR", tmp_path)
    # grava a calibração no diretório de R1, mas com resolution_id="R2" DENTRO
    # do arquivo (payload internamente inconsistente com o próprio path --
    # cenário de corrupção/edição manual, não algo que build_dollar_bars
    # produziria sozinho, mas a guarda precisa pegar mesmo assim).
    symbol_dir = tmp_path / "dollar_bars_r1" / "BTCUSDT"
    symbol_dir.mkdir(parents=True, exist_ok=True)
    import orjson

    from src.data.build_dollar_bars import DollarBarCalibration

    calibration = DollarBarCalibration(
        symbol="BTCUSDT",
        resolution_id="R2",
        threshold_usdt=1_000_000.0,
        calibration_scope="validation",
        calibration_window_start="2020-01-01",
        calibration_window_end="2026-08-07",
        n_trades=1_000,
        calibrated_at="2026-08-17T00:00:00+00:00",
    )
    (symbol_dir / "_calibration.json").write_bytes(orjson.dumps(dataclasses.asdict(calibration)))

    labels = _make_synthetic_labels(600, horizon_bars=1)
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, grade_id="R1")
    with pytest.raises(cpcv.CPCVError, match="divergente"):
        cpcv.assert_grade_consistent(labels, cfg, symbol="BTCUSDT")


def test_assert_grade_consistent_dollar_bar_calibracao_corrompida_levanta_cpcverror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Achado de auditoria (audit_engineering, 2026-08-17): arquivo
    PRESENTE mas corrompido (JSON malformado) não tinha tratamento --
    `orjson.JSONDecodeError` cru escapava em vez de `CPCVError` com
    contexto acionável (mesmo padrão dos dois casos vizinhos, arquivo
    ausente/resolution_id divergente, que já eram cobertos)."""
    from src.data import _paths as data_paths

    monkeypatch.setattr(data_paths, "CAPACITY_DIR", tmp_path)
    monkeypatch.setattr(cpcv, "CAPACITY_DIR", tmp_path)
    symbol_dir = tmp_path / "dollar_bars_r1" / "BTCUSDT"
    symbol_dir.mkdir(parents=True, exist_ok=True)
    (symbol_dir / "_calibration.json").write_bytes(b"{not valid json")

    labels = _make_synthetic_labels(600, horizon_bars=1)
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, grade_id="R1")
    with pytest.raises(cpcv.CPCVError, match="corrompido"):
        cpcv.assert_grade_consistent(labels, cfg, symbol="BTCUSDT")


def test_assert_grade_consistent_dollar_bar_calibracao_schema_divergente_levanta_cpcverror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mesmo achado -- JSON válido, mas faltando campo obrigatório do
    dataclass `DollarBarCalibration` (bump de schema futuro sem
    recalibrar o arquivo em disco). `TypeError` cru escapava antes."""
    import orjson

    from src.data import _paths as data_paths

    monkeypatch.setattr(data_paths, "CAPACITY_DIR", tmp_path)
    monkeypatch.setattr(cpcv, "CAPACITY_DIR", tmp_path)
    symbol_dir = tmp_path / "dollar_bars_r1" / "BTCUSDT"
    symbol_dir.mkdir(parents=True, exist_ok=True)
    (symbol_dir / "_calibration.json").write_bytes(orjson.dumps({"symbol": "BTCUSDT"}))

    labels = _make_synthetic_labels(600, horizon_bars=1)
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, grade_id="R1")
    with pytest.raises(cpcv.CPCVError, match="corrompido"):
        cpcv.assert_grade_consistent(labels, cfg, symbol="BTCUSDT")


def test_config_dollar_bar_grade_id_nao_valida_step_ms_na_construcao() -> None:
    """AG-042 -- `CPCVConfig(grade_id="R1")` não levanta na construção
    (diferente de um `tf`/`grade_id` de tempo desconhecido) -- `tf` fica
    vestigial nesse caso, `step_ms` nunca é chamado."""
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, grade_id="R1")
    assert cfg.grade_id == "R1"
    assert cfg.tf == "15m"  # default, nunca lido/validado neste caso


def test_assert_grade_consistent_rejeita_tf_divergente_15m_vs_30m() -> None:
    """O footgun real do AG-009, reproduzido sem precisar do dataset real:
    `labels` espaçado em 30m (como `load_labels_v1(tf="30m")` produziria)
    combinado com um `CPCVConfig` no default `tf="15m"` (como
    `CPCVConfig.from_constants()` sem `tf` explícito) -- os dois lados
    nunca eram checados um contra o outro antes desta correção."""
    labels = _make_synthetic_labels(600, horizon_bars=1, bar_ms=step_ms("30m"))
    cfg_15m_default = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS)
    with pytest.raises(cpcv.CPCVError, match="AG-009"):
        cpcv.assert_grade_consistent(labels, cfg_15m_default)


def test_assert_grade_consistent_rejeita_tf_divergente_15m_vs_1h() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)  # 15m (default bar_ms)
    cfg_1h = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS, tf="1h")
    with pytest.raises(cpcv.CPCVError, match="AG-009"):
        cpcv.assert_grade_consistent(labels, cfg_1h)


def test_assert_grade_consistent_tolera_gaps_minoritarios_na_mediana() -> None:
    """Dado real tem gaps ocasionais (ver `known_gaps`, docstring do
    módulo) -- a guarda usa a MEDIANA do diff entre `t0` consecutivos, não
    o mínimo nem uniformidade estrita, então uma MINORIA de barras
    faltando não pode disparar falso positivo. Simulado removendo ~5% das
    linhas de um grid de 15m antes de checar contra `tf="15m"`."""
    n = 600
    labels = _make_synthetic_labels(n, horizon_bars=1)
    rng = np.random.default_rng(42)
    drop_idx = rng.choice(n, size=n // 20, replace=False)  # noqa: magic-number -- ~5%
    keep_mask = np.ones(n, dtype=bool)
    keep_mask[drop_idx] = False
    labels_com_gaps = labels.filter(pl.Series(keep_mask))
    cpcv.assert_grade_consistent(labels_com_gaps, _CFG)  # não deve levantar


def test_assert_grade_consistent_instancia_unica_nao_levanta() -> None:
    """Sem pelo menos 2 `t0` distintos não há diff pra medir -- a guarda
    não levanta neste caso degenerado (deixa `assign_time_groups`, chamada
    logo depois dentro de `generate_splits`, levantar seu próprio erro
    mais específico de 'instante único não particionável')."""
    labels = _make_synthetic_labels(1, horizon_bars=1)
    cpcv.assert_grade_consistent(labels, _CFG)  # não deve levantar


def test_generate_splits_rejeita_tf_inconsistente_sem_opt_out() -> None:
    """A guarda roda DENTRO de `generate_splits`, sempre, sem opt-out
    (decisão AG-009) -- não só disponível como função separada que o
    caller precisa lembrar de invocar. Prova que a combinação
    `load_labels_v1(tf="30m")` + `CPCVConfig.from_constants()` (default
    `tf="15m"`) descrita no achado é pega automaticamente, não só
    detectável manualmente."""
    labels = _make_synthetic_labels(600, horizon_bars=1, bar_ms=step_ms("30m"))
    cfg_15m_default = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=2 * _BAR_MS)
    with pytest.raises(cpcv.CPCVError, match="AG-009"):
        cpcv.generate_splits(labels, cfg_15m_default)


# ============================================================================
# assign_time_groups — partição cronológica
# ============================================================================


def test_assign_time_groups_particiona_em_blocos_iguais() -> None:
    n = 600
    t0_ms = np.arange(n, dtype=np.int64) * _BAR_MS
    group_id, edges_ms = cpcv.assign_time_groups(t0_ms, 6)
    assert group_id.shape[0] == n
    assert set(np.unique(group_id).tolist()) == {0, 1, 2, 3, 4, 5}
    assert edges_ms.shape[0] == 7
    # cada grupo cronológico tem ~ o mesmo tamanho (tolerância de 1 bucket)
    counts = np.bincount(group_id, minlength=6)
    assert counts.max() - counts.min() <= 1


def test_assign_time_groups_cobre_o_maximo_no_ultimo_grupo() -> None:
    t0_ms = np.array([0, 100, 200, 300, 400, 500], dtype=np.int64)
    group_id, _ = cpcv.assign_time_groups(t0_ms, 3)
    assert group_id[-1] == 2  # o próprio máximo cai no último grupo, não "fora"


def test_assign_time_groups_vazio_levanta_erro() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.assign_time_groups(np.array([], dtype=np.int64), 6)


def test_assign_time_groups_instante_unico_levanta_erro() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.assign_time_groups(np.array([100, 100, 100], dtype=np.int64), 3)


# ============================================================================
# AG-151/D-16 — edges_ms sobre união temporal (purge cross-símbolo)
# ============================================================================


def test_assign_time_groups_edges_ms_informado_ignora_min_max_local() -> None:
    """Fronteiras vindas de fora (ex. pooled) governam o `group_id`, não o
    min/max do `t0_ms` local — a propriedade central de AG-151: dois
    símbolos com o MESMO `edges_ms` compartilham a mesma grade de
    calendário mesmo que os `t0` locais de cada um cubram intervalos
    diferentes."""
    edges_ms = np.array([0, 100, 200, 300], dtype=np.int64)  # 3 grupos externos
    # t0_ms local cobre só [50, 150] -- min/max locais NADA têm a ver com
    # as fronteiras informadas
    t0_ms = np.array([50, 60, 120, 150], dtype=np.int64)
    group_id, returned_edges = cpcv.assign_time_groups(t0_ms, 3, edges_ms=edges_ms)
    np.testing.assert_array_equal(returned_edges, edges_ms)
    np.testing.assert_array_equal(group_id, np.array([0, 0, 1, 1]))


def test_assign_time_groups_edges_ms_tamanho_errado_levanta_erro() -> None:
    edges_ms_curto = np.array([0, 100, 200], dtype=np.int64)  # 3, esperado 4 (n_groups=3)
    with pytest.raises(cpcv.CPCVError):
        cpcv.assign_time_groups(np.array([50], dtype=np.int64), 3, edges_ms=edges_ms_curto)


def test_assign_time_groups_edges_ms_nao_crescente_levanta_erro() -> None:
    edges_ms_invalido = np.array([0, 200, 100, 300], dtype=np.int64)
    with pytest.raises(cpcv.CPCVError):
        cpcv.assign_time_groups(np.array([50], dtype=np.int64), 3, edges_ms=edges_ms_invalido)


def test_assign_time_groups_edges_ms_none_bit_exato_ao_comportamento_antigo() -> None:
    """Guarda de não-regressão da própria assinatura: `edges_ms=None`
    (default) precisa produzir EXATAMENTE o mesmo resultado do ramo único
    que existia antes de AG-151 — a garantia que o golden de
    `tests/golden/test_validation_cpcv_pooling_non_regression.py` assume."""
    t0_ms = np.arange(600, dtype=np.int64) * _BAR_MS
    group_id, edges_ms = cpcv.assign_time_groups(t0_ms, 6)
    t_min, t_max = int(t0_ms.min()), int(t0_ms.max())
    edges_esperado = cpcv._linspace_edges_ms(t_min, t_max, 6)
    np.testing.assert_array_equal(edges_ms, edges_esperado)
    group_id_direto, _ = cpcv.assign_time_groups(t0_ms, 6, edges_ms=edges_esperado)
    np.testing.assert_array_equal(group_id, group_id_direto)


def test_compute_pooled_edges_ms_usa_uniao_min_max_entre_simbolos() -> None:
    t0_a = np.array([0, 500, 1000], dtype=np.int64)
    t0_b = np.array([2000, 3000], dtype=np.int64)  # estende o máximo da união
    edges_ms = cpcv.compute_pooled_edges_ms({"A": t0_a, "B": t0_b}, 4)
    assert int(edges_ms[0]) == 0  # união do mínimo (t0_a)
    assert int(edges_ms[-1]) == 3001  # união do máximo (t0_b) + 1


def test_compute_pooled_edges_ms_bit_exato_para_simbolo_de_maior_extensao() -> None:
    """Propriedade central do fix (docstring de `compute_pooled_edges_ms`):
    símbolo de maior extensão do pool (aqui, "BTC") não tem sua medição
    invalidada -- as fronteiras pooled são IDÊNTICAS às que ele produziria
    sozinho, porque a união não estende nem o mínimo nem o máximo dele."""
    t0_btc = np.arange(1000, dtype=np.int64) * _BAR_MS  # cobre [0, 999*bar]
    t0_sol = t0_btc[300:700]  # subconjunto estrito, dentro do range do BTC

    _, edges_btc_sozinho = cpcv.assign_time_groups(t0_btc, 6)
    edges_pooled = cpcv.compute_pooled_edges_ms({"BTCUSDT": t0_btc, "SOLUSDT": t0_sol}, 6)

    np.testing.assert_array_equal(edges_pooled, edges_btc_sozinho)


def test_compute_pooled_edges_ms_vazio_levanta_erro() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.compute_pooled_edges_ms({}, 6)


def test_compute_pooled_edges_ms_instante_unico_levanta_erro() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv.compute_pooled_edges_ms(
            {"A": np.array([100], dtype=np.int64), "B": np.array([100], dtype=np.int64)}, 3
        )


def test_generate_splits_edges_ms_pooled_e_usado_em_vez_do_local() -> None:
    """`generate_splits(..., edges_ms=pooled)` propaga a fronteira pooled
    pro `CPCVResult` -- não recalcula sobre o `t0` local de `labels`
    (que é o defeito original de AG-151, reproduzido aqui com um
    `edges_ms` deliberadamente diferente do que o `t0` local produziria)."""
    labels = _make_synthetic_labels(400, horizon_bars=1)
    t0_ms_local = labels["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    cfg = cpcv.CPCVConfig(n_groups=4, n_test_groups=2, embargo_ms=0)

    # edges_ms "pooled" artificial: dobra a largura da união (como se outro
    # símbolo estendesse o máximo bem além do que t0_ms_local sozinho cobre)
    t_min_local = int(t0_ms_local.min())
    t_max_local = int(t0_ms_local.max())
    edges_pooled = cpcv._linspace_edges_ms(t_min_local, 2 * t_max_local, cfg.n_groups)

    result = cpcv.generate_splits(labels, cfg, edges_ms=edges_pooled)
    np.testing.assert_array_equal(result.edges_ms, edges_pooled)

    result_local = cpcv.generate_splits(labels, cfg)
    assert not np.array_equal(result.edges_ms, result_local.edges_ms)


# ============================================================================
# 1-fatoração de K_n — n_backtest_paths
# ============================================================================


def test_1_fatoracao_k6_cobre_todos_os_15_pares_exatamente_uma_vez() -> None:
    rounds = cpcv._round_robin_1_factorization(6)
    assert len(rounds) == 5
    all_pairs: list[tuple[int, int]] = []
    for pairs in rounds:
        assert len(pairs) == 3  # 6 grupos / 2 por par
        covered = {g for pair in pairs for g in pair}
        assert covered == {0, 1, 2, 3, 4, 5}  # cada rodada cobre todos os grupos 1x
        all_pairs.extend(pairs)
    assert len(all_pairs) == 15
    assert len(set(all_pairs)) == 15  # todos distintos — nenhum par repetido entre rodadas
    from itertools import combinations

    assert set(all_pairs) == set(combinations(range(6), 2))


def test_1_fatoracao_rejeita_n_impar_ou_menor_que_2() -> None:
    with pytest.raises(cpcv.CPCVError):
        cpcv._round_robin_1_factorization(5)
    with pytest.raises(cpcv.CPCVError):
        cpcv._round_robin_1_factorization(0)


def test_path_assignment_e_consistente_com_generate_splits() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    # cada path cobre os 6 grupos de teste exatamente uma vez, batendo com a
    # verificação de generate_splits contra dado real (test_validation_cpcv real, abaixo)
    coverage: dict[int, set[int]] = {}
    for s in result.splits:
        coverage.setdefault(s.path_id, set()).update(s.test_groups)
    assert len(coverage) == 5
    for groups in coverage.values():
        assert groups == {0, 1, 2, 3, 4, 5}


# ============================================================================
# generate_splits — mecânica de purge/embargo com fronteiras controladas
# ============================================================================


def test_generate_splits_produz_15_splits_para_6_grupos_2_teste() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    assert len(result.splits) == 15
    assert {s.split_id for s in result.splits} == set(range(15))


def test_generate_splits_test_idx_e_train_idx_nunca_se_intersectam() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=3)
    result = cpcv.generate_splits(labels, _CFG)
    for s in result.splits:
        assert np.intersect1d(s.train_idx, s.test_idx).size == 0


def test_generate_splits_test_idx_e_exatamente_os_grupos_de_teste() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    for s in result.splits:
        test_groups_observed = set(result.group_id[s.test_idx].tolist())
        assert test_groups_observed <= set(s.test_groups)


def test_generate_splits_purge_remove_overlap_na_borda() -> None:
    """Horizonte de label deliberadamente GRANDE (20 barras) pra forçar
    overlap real entre um label de treino perto da borda de um grupo e o
    grupo de teste seguinte — prova que `n_purged > 0` quando o cenário
    exige, não só que o splitter roda sem erro."""
    n = 1200  # 6 grupos de 200 barras cada
    labels = _make_synthetic_labels(n, horizon_bars=20)
    cfg_sem_embargo = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=0)
    result = cpcv.generate_splits(labels, cfg_sem_embargo)

    total_purged = sum(s.n_purged for s in result.splits)
    assert total_purged > 0


def test_generate_splits_purge_cresce_com_horizonte_do_label() -> None:
    """Horizonte de label maior tem que produzir >= purge que um horizonte
    menor, split a split — prova que o purge usa o `t1` REAL de cada linha
    (item 2 da docstring do módulo), não uma margem fixa desacoplada do
    horizonte. Não assume purge==0 para horizonte pequeno: como as
    fronteiras de grupo são cronológicas (`assign_time_groups`, partição
    por tempo) e não alinhadas à grade de barras, mesmo um horizonte de 1
    barra pode cruzar uma fronteira que caia no meio dela — comportamento
    correto do AFML (purge por t1 exato), não um bug."""
    n = 1200
    cfg_sem_embargo = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=0)
    labels_curto = _make_synthetic_labels(n, horizon_bars=1)
    labels_longo = _make_synthetic_labels(n, horizon_bars=20)
    result_curto = cpcv.generate_splits(labels_curto, cfg_sem_embargo)
    result_longo = cpcv.generate_splits(labels_longo, cfg_sem_embargo)

    for s_curto, s_longo in zip(result_curto.splits, result_longo.splits, strict=True):
        assert s_longo.n_purged >= s_curto.n_purged

    total_curto = sum(s.n_purged for s in result_curto.splits)
    total_longo = sum(s.n_purged for s in result_longo.splits)
    assert total_longo > total_curto


def test_generate_splits_purge_cobre_lookback_de_feature_de_treino_apos_g_end() -> None:
    """AG-032/E4 — critério de aceite explícito (item 2b da docstring do
    módulo). 'Purge usa o t1 real do teste' fecha o componente 32
    (horizonte do LABEL de teste esticando pra FRENTE, além de `g_end`) —
    mas isso sozinho NÃO cobre o componente 96 (janela de LOOKBACK de uma
    feature de TREINO, ex. `feature_c06_vol_ratio_long_window`, esticando
    pra TRÁS através de `g_end`, pra dentro do território de teste). São
    duas direções mecanicamente diferentes da mesma cegueira de fronteira.

    Isola SÓ o componente 96: toda a base usa `horizon_bars=1` (label
    curtíssimo — nenhum `t1`, nem de teste nem de treino, chega perto de
    cruzar fronteira nenhuma sozinho), então qualquer purge observado aqui
    só pode vir do parâmetro novo, não de overlap de label.

    Prova as duas metades do critério de aceite: (a) com
    `max_feature_lookback_ms=0` (default, comportamento de sempre), uma
    linha de treino no "vão" logo após `g_end` sobrevive no treino — prova
    que o componente 96 NÃO é pego sem o parâmetro; (b) com
    `max_feature_lookback_ms` cobrindo o vão, a MESMA linha é purgada."""
    n = 400  # 4 grupos de ~100 barras cada
    base = _make_synthetic_labels(n, horizon_bars=1)
    cfg_probe = cpcv.CPCVConfig(n_groups=4, n_test_groups=2, embargo_ms=0)
    t0_ms_base = base["t0"].dt.epoch(time_unit="ms").to_numpy().astype(np.int64)
    _, edges_ms = cpcv.assign_time_groups(t0_ms_base, cfg_probe.n_groups)
    g1_end = int(edges_ms[2]) - 1  # borda direita do grupo 1 (fronteira exclusiva)

    # Linha extra R: t0 dez barras DEPOIS de g1_end -- cai no grupo 2
    # (candidato de treino quando test_groups=(0,1)), label curtíssimo
    # (horizon_bars=1, igual à base). offset_bars=10 é deliberadamente
    # generoso: g_end_effective do grupo 1 pode crescer até 1 bar acima de
    # g1_end (a última linha do grupo pode ter t1=t0+1bar ultrapassando a
    # fronteira, mesmo sob horizon=1) -- 10 barras de folga garante R
    # sobrevive em (a) mesmo no pior caso desse efeito de arredondamento.
    offset_bars = 10
    r_t0_ms = g1_end + 1 + offset_bars * _BAR_MS
    r_row = pl.DataFrame(
        {
            "t0": pl.Series([r_t0_ms]).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"),
            "t1": pl.Series([r_t0_ms + _BAR_MS])
            .cast(pl.Datetime("ms"))
            .dt.replace_time_zone("UTC"),
            "side": pl.Series([1], dtype=pl.Int8),
            "sample_weight": pl.Series([1.0], dtype=pl.Float64),
        }
    )
    labels = pl.concat([base, r_row])
    r_idx = n  # última linha (R é a única acrescentada após os `n` da base)

    # (a) default -- sem max_feature_lookback_ms, componente 96 não é pego.
    cfg_sem_lookback = cpcv.CPCVConfig(n_groups=4, n_test_groups=2, embargo_ms=0)
    result_sem = cpcv.generate_splits(labels, cfg_sem_lookback)
    split0_sem = result_sem.splits[0]
    assert split0_sem.test_groups == (0, 1), "premissa do teste: 1º split cobre grupos 0+1"
    assert r_idx in split0_sem.train_idx.tolist(), (
        "sem max_feature_lookback_ms, a linha do vão sobrevive no treino -- "
        "comportamento ATUAL, prova que o componente 96 não é pego por padrão"
    )

    # (b) lookback cobrindo o vão (11 barras >= offset_bars+1) -- mesma
    # linha precisa ser purgada agora.
    lookback_ms = (offset_bars + 1) * _BAR_MS
    cfg_com_lookback = cpcv.CPCVConfig(
        n_groups=4, n_test_groups=2, embargo_ms=0, max_feature_lookback_ms=lookback_ms
    )
    result_com = cpcv.generate_splits(labels, cfg_com_lookback)
    split0_com = result_com.splits[0]
    assert split0_com.test_groups == (0, 1)
    assert r_idx not in split0_com.train_idx.tolist(), (
        "com max_feature_lookback_ms cobrindo o vão, a MESMA linha precisa ser "
        "purgada -- prova que o parâmetro fecha o componente 96 (AG-032, "
        "critério de aceite de E4)"
    )
    assert split0_com.n_purged >= split0_sem.n_purged + 1


def test_generate_splits_embargo_remove_bordas_mesmo_sem_overlap_de_t1() -> None:
    n = 1200
    labels = _make_synthetic_labels(n, horizon_bars=1)  # sem overlap de t1
    result = cpcv.generate_splits(labels, _CFG)  # embargo_ms=2*_BAR_MS
    total_embargoed = sum(s.n_embargoed for s in result.splits)
    assert total_embargoed > 0


def test_generate_splits_embargo_zero_desativa_a_janela() -> None:
    n = 1200
    labels = _make_synthetic_labels(n, horizon_bars=1)
    cfg_sem_embargo = cpcv.CPCVConfig(n_groups=6, n_test_groups=2, embargo_ms=0)
    result = cpcv.generate_splits(labels, cfg_sem_embargo)
    assert all(s.n_embargoed == 0 for s in result.splits)


def test_generate_splits_rejeita_n_test_groups_diferente_de_2() -> None:
    labels = _make_synthetic_labels(600, horizon_bars=1)
    cfg = cpcv.CPCVConfig(n_groups=6, n_test_groups=1, embargo_ms=0)
    with pytest.raises(cpcv.CPCVError):
        cpcv.generate_splits(labels, cfg)


def test_generate_splits_vazio_levanta_erro() -> None:
    empty = _make_synthetic_labels(0)
    with pytest.raises(cpcv.CPCVError):
        cpcv.generate_splits(empty, _CFG)


# ============================================================================
# assert_no_train_t1_leaks_into_test — teste 6 do §11.5, mecânica sintética
# ============================================================================


def test_assert_no_train_t1_leaks_passa_no_caso_normal() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    cpcv.assert_no_train_t1_leaks_into_test(labels, result)  # não deve levantar


def test_assert_no_train_t1_leaks_detecta_vazamento_forjado() -> None:
    """Forja um split com `train_idx` incluindo uma linha cujo `[t0, t1]`
    cai DENTRO do primeiro grupo de teste — prova que a função detecta a
    violação, não só que "passa quando tudo está certo" (o mesmo cuidado já
    tomado em `test_data_resample.py::
    test_assert_no_lookahead_detecta_close_time_futuro_forjado`)."""
    n = 1200
    labels = _make_synthetic_labels(n, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)

    real_split = result.splits[0]
    g0 = real_split.test_groups[0]
    g0_start = int(result.edges_ms[g0])
    # linha cujo t0 cai dentro do grupo de teste g0 -- índice = a própria
    # posição do primeiro elemento do grupo de teste no array
    test_row_idx = int(real_split.test_idx[0])
    assert int(labels["t0"].dt.epoch(time_unit="ms")[test_row_idx]) >= g0_start

    forged_train_idx = np.concatenate([real_split.train_idx, np.array([test_row_idx])])
    forged_split = cpcv.CPCVSplit(
        split_id=real_split.split_id,
        path_id=real_split.path_id,
        test_groups=real_split.test_groups,
        train_groups=real_split.train_groups,
        train_idx=forged_train_idx,
        test_idx=real_split.test_idx,
        n_train_candidate=real_split.n_train_candidate,
        n_purged=real_split.n_purged,
        n_embargoed=real_split.n_embargoed,
    )
    forged_result = cpcv.CPCVResult(
        config=result.config,
        group_id=result.group_id,
        edges_ms=result.edges_ms,
        splits=(forged_split, *result.splits[1:]),
    )
    with pytest.raises(AssertionError):
        cpcv.assert_no_train_t1_leaks_into_test(labels, forged_result)


def test_assert_embargo_respected_passa_no_caso_normal() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=1)
    result = cpcv.generate_splits(labels, _CFG)
    cpcv.assert_embargo_respected(labels, result)  # não deve levantar


# ============================================================================
# summarize_splits
# ============================================================================


def test_summarize_splits_soma_train_test_purge_embargo_bate_com_candidato() -> None:
    labels = _make_synthetic_labels(1200, horizon_bars=3)
    result = cpcv.generate_splits(labels, _CFG)
    summary = cpcv.summarize_splits(result)
    assert summary.height == 15
    # n_train + n_purged + n_embargoed == n_train_candidate, para cada split
    check = summary.select(
        (
            pl.col("n_train") + pl.col("n_purged") + pl.col("n_embargoed")
            == pl.col("n_train_candidate")
        ).alias("ok")
    )
    assert bool(check["ok"].all())


# ============================================================================
# load_labels_v1 + dataset REAL (labels/v1/labels.parquet, Sprint 6)
# ============================================================================

# Universo de 5 símbolos do projeto (§15, PLANO_MESTRE_PRINCE2.md) — mesmo
# tuple literal já usado em src/labels/backfill_multi_symbol.py::ALL_SYMBOLS
# e src/analysis/m6_common_factor_hypothesis.py::ALL_SYMBOLS (convenção do
# repo: cada módulo declara o próprio tuple em vez de importar entre
# pacotes de camadas diferentes — aqui é um teste, não módulo de src/, mas
# segue a mesma convenção por consistência). Achado F2 (candidato a AG-130,
# auditoria 2026-08-19): antes desta correção, os testes de integração
# abaixo chamavam cpcv.load_labels_v1() sem argumento, sempre resolvendo
# symbol="BTCUSDT" -- os outros 4 símbolos nunca eram exercitados pelo CPCV
# de verdade, só pelo runner de leakage completo via outro caminho.
_ALL_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def _skip_if_labels_missing(symbol: str = "BTCUSDT") -> None:
    path = labels_symbol_tf_dir(symbol, "v1") / "labels.parquet"
    if not path.exists():
        pytest.skip(f"{path} ausente — rode o Label Engine (Sprint 6) primeiro")


def test_load_labels_v1_inexistente_levanta_filenotfound() -> None:
    with pytest.raises(FileNotFoundError):
        cpcv.load_labels_v1(version="versao_que_nao_existe_12345")


def test_load_labels_v1_tf_default_preserva_caminho_15m_existente() -> None:
    """`tf` é novo (AG-004) — o default precisa continuar resolvendo pro
    MESMO caminho de sempre (data/labels/{symbol}/15m/{version}/), não um
    caminho novo que quebraria o artefato real já gravado."""
    with pytest.raises(FileNotFoundError) as exc_info:
        cpcv.load_labels_v1(version="versao_que_nao_existe_12345")
    assert "\\15m\\" in str(exc_info.value) or "/15m/" in str(exc_info.value)


def test_load_labels_v1_tf_explicito_muda_o_caminho_resolvido() -> None:
    with pytest.raises(FileNotFoundError) as exc_info:
        cpcv.load_labels_v1(version="versao_que_nao_existe_12345", tf="30m")
    assert "\\30m\\" in str(exc_info.value) or "/30m/" in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _ALL_SYMBOLS)
def test_cpcv_sobre_dataset_real_15_splits_zero_vazamento(symbol: str) -> None:
    """O teste central — §11.5 #6 rodando contra `labels/{symbol}/15m/v1/
    labels.parquet` real, não sintético. Confirma: 15 splits, 5 caminhos, e
    ZERO t1 de treino cruzando qualquer janela de teste em qualquer split.

    Parametrizado pros 5 símbolos do universo (achado F2, candidato a
    AG-130, auditoria 2026-08-19) — skip automático (`_skip_if_labels_
    missing`) por símbolo cujo backfill local ainda não existe, mesmo
    padrão de sempre, agora por símbolo em vez de só BTCUSDT."""
    _skip_if_labels_missing(symbol)
    labels = cpcv.load_labels_v1(symbol=symbol)
    result = cpcv.generate_splits(labels, symbol=symbol)

    assert result.config.n_splits == 15
    assert result.config.n_backtest_paths == 5
    assert len(result.splits) == 15

    cpcv.assert_no_train_t1_leaks_into_test(labels, result)
    cpcv.assert_embargo_respected(labels, result)

    summary = cpcv.summarize_splits(result)
    assert summary.height == 15
    # todo split tem treino e teste não-vazios sobre o dataset real
    assert bool((summary["n_train"] > 0).all())
    assert bool((summary["n_test"] > 0).all())
    # teste cobre uma fração razoável do dataset (2 de 6 grupos ~= 1/3)
    total = labels.height
    for row in summary.iter_rows(named=True):
        assert 0.2 < row["n_test"] / total < 0.45


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _ALL_SYMBOLS)
def test_cpcv_sobre_dataset_real_grupos_cobrem_series_completa(symbol: str) -> None:
    """Parametrizado pros 5 símbolos (achado F2, candidato a AG-130) —
    ver docstring de `test_cpcv_sobre_dataset_real_15_splits_zero_vazamento`.

    Bound de span por grupo é relativo ao span TOTAL medido do símbolo, não
    um número absoluto de dias fixo -- BTCUSDT cobre ~6,6 anos
    (2019-12-31->2026-08-07), os 4 alts cobrem só ~4,7 anos
    (2021-12-01->2026-08-07, teto comum medido em AG-030/constants.yaml::
    min_common_history_bars_15m) -- "~1 ano por grupo" (§11.4) é
    CONSEQUÊNCIA do histórico de BTCUSDT sob n_groups=6, não um invariante
    independente do símbolo. A asserção original (hardcoded em
    [300, 450] dias) era implicitamente BTCUSDT-específica e quebraria nos
    4 alts (~1711/6 ~= 285 dias por grupo, abaixo do piso de 300) --
    generalizada aqui pra continuar provando o que a partição cronológica
    de `assign_time_groups` de fato garante (grupos de largura ~igual),
    sem herdar um número específico do calendário do BTC."""
    _skip_if_labels_missing(symbol)
    labels = cpcv.load_labels_v1(symbol=symbol)
    result = cpcv.generate_splits(labels, symbol=symbol)
    assert set(np.unique(result.group_id).tolist()) == {0, 1, 2, 3, 4, 5}
    total_span_ms = int(result.edges_ms[-1]) - int(result.edges_ms[0])
    expected_span_days = (total_span_ms / (24 * 60 * 60 * 1000)) / 6  # noqa: magic-number
    for g in range(6):
        span_ms = int(result.edges_ms[g + 1]) - int(result.edges_ms[g])
        span_days = span_ms / (24 * 60 * 60 * 1000)  # noqa: magic-number
        # ±20% de folga em torno do span esperado (total/6) -- linspace
        # particiona em largura ~exatamente igual por construção
        # (assign_time_groups), a folga é pra tolerar arredondamento, não
        # porque se espera variação real de verdade entre grupos.
        assert expected_span_days * 0.8 < span_days < expected_span_days * 1.2  # noqa: magic-number


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _ALL_SYMBOLS)
def test_cpcv_sobre_dataset_real_purge_e_embargo_sao_pequenos_face_ao_dataset(
    symbol: str,
) -> None:
    """`time_stop_bars` (32 barras, 8h) e `cpcv_embargo_ms` (AG-032/E1,
    2026-08-16 -- 96,39h medido, substitui o legado embargo_bars=175/
    43,75h) são desprezíveis frente a grupos de ~1 ano — purge+embargo por
    split não deveria remover mais que uma fração pequena do treino
    candidato. embargo_ms cresceu 2,2x em relação ao valor legado -- se
    este teste falhar, é sinal real de que o limiar de 2% precisa ser
    revisto com o número novo, não um bug de teste.

    Parametrizado pros 5 símbolos (achado F2, candidato a AG-130). Nota
    honesta sobre o limiar herdado: `cpcv_embargo_ms` é um valor de RELÓGIO
    FIXO (não escala com símbolo), medido como ~1% da largura de grupo do
    BTCUSDT (~402 dias); os 4 alts têm grupos ~29% menores (~285 dias,
    ver `test_cpcv_sobre_dataset_real_grupos_cobrem_series_completa`), o
    que faz a MESMA janela de embargo representar uma fração
    proporcionalmente maior do grupo (~1,4% em vez de ~1%). Ainda assim
    esperado ficar abaixo do limiar de 2% (mesma lógica do docstring
    original: se não ficar, é achado real sobre o símbolo, não bug desta
    parametrização)."""
    _skip_if_labels_missing(symbol)
    labels = cpcv.load_labels_v1(symbol=symbol)
    result = cpcv.generate_splits(labels, symbol=symbol)
    summary = cpcv.summarize_splits(result)
    frac_removed = (summary["n_purged"] + summary["n_embargoed"]) / summary["n_train_candidate"]
    assert bool((frac_removed < 0.02).all())  # noqa: magic-number
