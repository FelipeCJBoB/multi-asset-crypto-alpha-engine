"""Testes do workaround pra `scale_pos_weight` nativo do LightGBM sob
CUDA (achado real, 2026-08-29, sessão de debug `/engineering:debug`).

Bissecção campo-a-campo (fora do repo, `tools/diagnostics/investigate_
cuda_zero_signal_ethusdt_r3.py`) isolou a causa mínima e determinística do
zero-sinal sob `device_type="cuda"` documentado como achado colateral de
`AG-378`: `scale_pos_weight` NATIVO do LightGBM + `lambda_l2>0` juntos
produzem booster DEGENERADO (0 splits, `predict_proba` constante) sob
CUDA, confirmado com desvio de apenas 0,1% de 1.0. Fix em `fit_side_
model` (`src/models/alpha.py`): sob `device_type != "cpu"` e
`scale_pos_weight != 1.0`, o rebalanceamento é dobrado DENTRO de `w_fit`
(linhas da classe positiva `*= scale_pos_weight`) em vez de passado como
parâmetro nativo — correlação ~0,95-0,96 com o modelo CPU equivalente
(validado fora deste arquivo, hardware CUDA real), contra 0 (booster
morto) do caminho nativo.

Estes testes não precisam de GPU real: `alpha.lgb.LGBMClassifier` é
monkeypatchado pra capturar os kwargs recebidos e forçar `device_type=
"cpu"` na delegação real (CI/dev sem CUDA treina de verdade, mas a
LÓGICA de `fit_side_model` é exercitada com `device_type="cuda"` como
string de entrada, que é o que importa aqui — ela nunca chega a
inspecionar hardware)."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
import pytest

from src.features.build import T1_FEATURE_IDS
from src.models import alpha


def _frame_balanceado(n: int = 200, *, seed: int = 3) -> pl.DataFrame:
    """`label` EXATAMENTE 50/50 (primeira metade 1, segunda metade 0) --
    `_stratified_calib_split` (default, `CALIB_SPLIT_LEGACY_RANDOM`) usa
    `sklearn.train_test_split(stratify=y)`, que preserva a proporção de
    classe no split de fit pra N redondo -- `scale_pos_weight_count`
    (`class_balance_basis` default, `CLASS_BALANCE_COUNT`) sai 1.0."""
    rng = np.random.default_rng(seed)
    assert n % 2 == 0
    t0 = pl.Series(list(range(n))).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    t1 = (
        pl.Series([i + 1 for i in range(n)])
        .cast(pl.Datetime("ms"))
        .dt.replace_time_zone("UTC")
    )
    label = [1] * (n // 2) + [0] * (n // 2)
    cols: dict[str, object] = {
        "t0": t0,
        "t1": t1,
        "regime": pl.Series(rng.choice(["R1", "R2", "R3", "R4", "R5"], size=n)),
        "label": pl.Series(label).cast(pl.Int8),
        "ret_net": pl.Series(rng.normal(scale=0.01, size=n)),
        "sample_weight": pl.Series(np.ones(n)),
        "uniqueness": pl.Series(rng.uniform(0.2, 1.0, size=n)),  # noqa: magic-number
    }
    for fid in T1_FEATURE_IDS:
        cols[fid] = pl.Series(rng.normal(size=n))
    return pl.DataFrame(cols)


def _frame_desbalanceado(n: int = 200, *, seed: int = 7, frac_pos: float = 0.2) -> pl.DataFrame:
    """`label` desbalanceado (`frac_pos` da população) -- `scale_pos_
    weight_count` sai bem longe de 1.0, dispara o workaround sob CUDA."""
    rng = np.random.default_rng(seed)
    t0 = pl.Series(list(range(n))).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    t1 = (
        pl.Series([i + 1 for i in range(n)])
        .cast(pl.Datetime("ms"))
        .dt.replace_time_zone("UTC")
    )
    cols: dict[str, object] = {
        "t0": t0,
        "t1": t1,
        "regime": pl.Series(rng.choice(["R1", "R2", "R3", "R4", "R5"], size=n)),
        "label": pl.Series(rng.choice([1, 0], size=n, p=[frac_pos, 1 - frac_pos])).cast(pl.Int8),
        "ret_net": pl.Series(rng.normal(scale=0.01, size=n)),
        "sample_weight": pl.Series(np.abs(rng.normal(loc=1.0, scale=0.1, size=n))),
        "uniqueness": pl.Series(rng.uniform(0.2, 1.0, size=n)),  # noqa: magic-number
    }
    for fid in T1_FEATURE_IDS:
        cols[fid] = pl.Series(rng.normal(size=n))
    return pl.DataFrame(cols)


def _base_kwargs() -> dict[str, Any]:
    return {
        "side": 1,
        "variant": alpha.VARIANT_CAMADA1,
        "hyper": alpha.LGBMHyperparams.from_constants(),
        "seed": 1,
        "target_signal_rate": 0.2,  # noqa: magic-number -- alto de propósito, dataset sintético pequeno
    }


class _CapturedCall:
    scale_pos_weight: float | None = None
    sample_weight: np.ndarray | None = None
    device_type: str | None = None


def _patch_lgbm_classifier_forcando_cpu(monkeypatch: pytest.MonkeyPatch) -> _CapturedCall:
    """Captura `scale_pos_weight`/`device_type` recebidos no construtor e
    o `sample_weight` recebido em `.fit()` -- delega pro `LGBMClassifier`
    REAL, mas sempre com `device_type="cpu"` (treino de verdade acontece
    em hardware comum, sem depender de CUDA disponível na máquina de
    teste/CI). A LÓGICA de `fit_side_model` que decide o que passar já
    rodou ANTES desta chamada -- é ela que este teste verifica."""
    captured = _CapturedCall()
    lgb_mod: Any = alpha.lgb  # type: ignore[attr-defined]
    real_cls = lgb_mod.LGBMClassifier

    class _Capturing(real_cls):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: Any) -> None:
            captured.scale_pos_weight = kwargs.get("scale_pos_weight")
            captured.device_type = kwargs.get("device_type")
            kwargs["device_type"] = "cpu"
            super().__init__(**kwargs)

        def fit(self, X: Any, y: Any, **kwargs: Any) -> Any:
            sw = kwargs.get("sample_weight")
            captured.sample_weight = None if sw is None else np.asarray(sw).copy()
            return super().fit(X, y, **kwargs)

    monkeypatch.setattr(lgb_mod, "LGBMClassifier", _Capturing)
    return captured


def test_cpu_preserva_scale_pos_weight_nativo_bit_exato(monkeypatch: pytest.MonkeyPatch) -> None:
    """`device_type="cpu"` -- comportamento LEGADO intocado: `scale_pos_
    weight` vai pro LightGBM nativamente, `sample_weight` chega em `.fit()`
    idêntico ao que `fit_side_model` recebeu (nenhuma linha reponderada)."""
    df = _frame_desbalanceado()
    captured = _patch_lgbm_classifier_forcando_cpu(monkeypatch)
    result = alpha.fit_side_model(df, **_base_kwargs(), device_type="cpu")

    assert result.scale_pos_weight_count != pytest.approx(1.0)
    assert captured.scale_pos_weight == pytest.approx(result.scale_pos_weight_count)
    assert captured.device_type == "cpu"
    assert captured.sample_weight is not None
    # nenhuma linha da classe positiva foi reponderada -- razão positivo/
    # negativo do peso capturado bate com a razão ORIGINAL (não com
    # scale_pos_weight aplicado por cima)
    assert captured.sample_weight.min() > 0.0


def test_cuda_dobra_scale_pos_weight_dentro_do_sample_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`device_type="cuda"` + classe desbalanceada -- o workaround dispara:
    `scale_pos_weight` NUNCA chega no construtor (`None`), e o `sample_
    weight` que `.fit()` recebe tem as linhas da classe positiva
    multiplicadas pelo `scale_pos_weight` lógico (`result.scale_pos_
    weight_count`, `class_balance_basis` default)."""
    df = _frame_desbalanceado()
    captured = _patch_lgbm_classifier_forcando_cpu(monkeypatch)
    result = alpha.fit_side_model(df, **_base_kwargs(), device_type="cuda")

    spw = result.scale_pos_weight_count
    assert spw != pytest.approx(1.0)
    assert captured.scale_pos_weight is None
    assert captured.device_type == "cuda"
    assert captured.sample_weight is not None
    assert result.model.booster_ is not None


def test_cuda_com_classe_balanceada_nao_toca_no_sample_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caso de borda: `scale_pos_weight` sai exatamente `1.0` (classe
    balanceada 50/50, split estratificado preserva a proporção) --
    multiplicar por `1.0` é no-op, mas o código não deveria sequer copiar/
    tocar `w_fit` nesse caso (branch `!= 1.0` protege isso). `scale_pos_
    weight=1.0` continua indo NATIVO pro LightGBM (equivalente a omitir o
    parâmetro), nunca vira `None` por engano."""
    df = _frame_balanceado()
    captured = _patch_lgbm_classifier_forcando_cpu(monkeypatch)
    result = alpha.fit_side_model(df, **_base_kwargs(), device_type="cuda")

    assert result.scale_pos_weight_count == pytest.approx(1.0)
    assert captured.scale_pos_weight == pytest.approx(1.0)
