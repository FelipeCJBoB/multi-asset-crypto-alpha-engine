"""Diagnóstico de poder do eixo 1 por injeção de sinal sintético (`AG-327`).

**Por que existe.** `AG-327`/`docs/investigacao_falso_negativo_eixo1_
2026-08-26.md` levantaram a hipótese de que o eixo 1
(`feature_promotion_criterion.py`, `AG-294`) pode não ter poder estatístico
suficiente para detectar um sinal econômico real e modesto (IC de Spearman
~0,02-0,05 — a faixa que a indústria trata como útil, Alphalens/Qlib/
WorldQuant), e só reage a efeitos do tamanho de um artefato de dado
(`E18f`, `k=5`, >10.000× o esperado sob H0). Este módulo mede a curva de
poder DE VERDADE, em vez de inferir por analogia (B23 — nunca estipular sem
medir).

**O método.** Para cada `rho_true` numa grade de correlações-alvo:

1. Gera uma série SINTÉTICA por (resolução, símbolo), com correlação de
   Spearman POPULACIONAL aproximadamente `rho_true` contra o retorno futuro
   de referência (`h=1`) — ver `synthetic_correlated_series`.
2. Roda essa série sintética pela MESMA matemática de produção
   (`src.analysis.ic_by_horizon.ic_disjoint`, reaproveitado sem
   reimplementar) para obter `pico_abs_t` sobre os 6 horizontes — exatamente
   o que uma feature real passaria.
3. Injeta esse p-valor sintético (via `feature_promotion_criterion.
   two_sided_p_from_t`) na MESMA família de 72 p-valores REAIS já
   persistidos em `experiments/ic_by_horizon_report_{R}.json` (a candidata
   sintética se torna a 73ª, nunca substitui uma real), roda o MESMO
   Benjamini-Hochberg (`feature_promotion_criterion.benjamini_hochberg`, `q`
   idêntico ao de produção) e verifica se a sintética é descoberta.
4. Repete por Monte Carlo (`n_mc_draws` sorteios independentes), agrega por
   maioria entre as 3 resoluções (`feature_promotion_criterion.
   symbol_is_majority_discovery`, reaproveitado) e conta quantos dos 5
   símbolos "descobrem" a sintética em cada sorteio.
5. A TAXA DE DETECÇÃO em `k_threshold` símbolos, sobre os `n_mc_draws`
   sorteios, é a curva de poder empírica do pipeline atual em `rho_true`.

**O que este módulo NÃO faz.** Não corrige o eixo 1 — devolve a curva de
poder medida, a decisão de o que fazer com ela é do Manager (mesmo espírito
DECISION-SUPPORT de `feature_promotion_criterion.py`/`feature_temporal_
stability.py`). Não decide se `rho_true=0,02` é "o" tamanho de efeito
esperado em cripto — a grade de valores testados é ampla o bastante (inclui
`0,0` como controle negativo, `0,08`/`0,10` como controle positivo) para a
curva inteira ser informativa independente dessa escolha.

**Simplificação declarada, não escondida.** Usa a série de barras COMPLETA
via `load_bars` (sem a máscara de warmup de produção que `build_t1_features`
aplicaria) — dá ao diagnóstico um `N` ligeiramente MAIOR que o real de
produção, portanto uma leitura levemente OTIMISTA do poder (mais `N` = mais
poder estatístico). Reproduzir o `N` exato de produção exigiria replicar a
lógica de warmup (que depende do lookback máximo entre as 72 features, alvo
móvel) — fora de escopo para um diagnóstico.

**Custo.** Cada `rho_true` custa `n_mc_draws × 15` (3 resoluções × 5
símbolos) chamadas a `ic_disjoint` (6 horizontes cada) sobre séries de
~150-170 mil barras — não é gratuito. `close`/`fwd_by_h` são carregados e
pré-computados UMA vez por (resolução, símbolo), fora do laço de Monte
Carlo — só a série sintética muda a cada sorteio.

Núcleo puro (Idioma A): `synthetic_correlated_series`, `peak_abs_t_for_
series`, `p_values_with_synthetic`, `synthetic_is_discovered` — recebem
arrays/mapas já em memória, zero IO. A casca
(`run_eixo1_power_diagnostic_report`) carrega barras/relatórios reais e
persiste.

Referências: `docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md`
§14.9-§14.10; `docs/investigacao_falso_negativo_eixo1_2026-08-26.md` §3.3,
§8 (item 1 da ordem de correção recomendada)."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy.stats import rankdata

from src.analysis.feature_promotion_criterion import (
    benjamini_hochberg,
    symbol_is_majority_discovery,
    two_sided_p_from_t,
)
from src.analysis.ic_by_horizon import (
    DEFAULT_HORIZONS,
    forward_log_return,
    ic_disjoint,
    spearman_ic,
)
from src.labels._constants import load_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

EXPERIMENTS_DIR: Final[Path] = Path("experiments")
RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")
SYMBOLS: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")

#: Nome interno da candidata sintética -- nunca colide com um nome real de
#: feature (todas seguem o padrão `<Grupo><NN>[f]_snake_case`).
_SYNTHETIC_NAME: Final[str] = "__synthetic__"

#: Grade de correlações-alvo testadas. `0,0` é controle negativo (a taxa de
#: detecção deve convergir para perto de `q_bh`, não para 0 nem para 1);
#: `0,02`-`0,05` é a faixa que a indústria (Alphalens/Qlib/WorldQuant) trata
#: como IC útil (`docs/investigacao_falso_negativo_eixo1_2026-08-26.md`
#: §3.4); `0,08`/`0,10` são controle positivo (efeito grande — deve ser
#: quase sempre detectado se o pipeline tem poder nessa escala). Mesma
#: classe de `DEFAULT_HORIZONS` em `ic_by_horizon.py` -- grade de varredura
#: declarada, não constante de negócio (fora do escopo de `provenance` de
#: `constants.yaml`).
DEFAULT_TARGET_RHOS: Final[tuple[float, ...]] = (
    0.0,  # noqa: magic-number -- controle negativo, ver docstring do modulo
    0.01,  # noqa: magic-number -- grade de varredura, ver docstring do modulo
    0.02,  # noqa: magic-number -- grade de varredura, ver docstring do modulo
    0.03,  # noqa: magic-number -- grade de varredura, ver docstring do modulo
    0.05,  # noqa: magic-number -- grade de varredura, ver docstring do modulo
    0.08,  # noqa: magic-number -- controle positivo, ver docstring do modulo
    0.10,  # noqa: magic-number -- controle positivo, ver docstring do modulo
)

#: Sorteios de Monte Carlo por `rho_true`. 100 é um piso prático (erro
#: padrão de uma proporção em torno de 0,5 é ~5pp com `n=100`) -- custa 15
#: chamadas a `ic_disjoint` (x6 horizontes) por sorteio; subir para 300-500
#: reduz o erro padrão mas multiplica o custo de execução proporcionalmente.
DEFAULT_N_MC_DRAWS: Final[int] = 100

DEFAULT_K_THRESHOLDS: Final[tuple[int, ...]] = (1, 2, 3)

#: Semente fixa para reprodutibilidade bit-exata do diagnóstico (mesma
#: convenção de `src/validation/leakage.py::rng=np.random.default_rng(7)` —
#: é semente de RNG, não constante de negócio, fora do escopo de
#: `provenance` de `constants.yaml`).
DEFAULT_SEED: Final[int] = 20260826


class Eixo1PowerDiagnosticError(RuntimeError):
    """Erro estrutural — artefato de origem ausente ou entrada inválida."""


# ============================================================================
# Núcleo puro — zero IO (Idioma A)
# ============================================================================


def synthetic_correlated_series(
    fwd_return_ref: FloatArray, rho_true: float, rng: np.random.Generator
) -> FloatArray:
    """Série sintética com correlação de Spearman POPULACIONAL aproximada
    `rho_true` contra `fwd_return_ref` (tipicamente o retorno futuro de
    `h=1` barra).

    Construção: padroniza `fwd_return_ref` por POSTOS (não por valor —
    evita exigir normalidade da série de retorno real) e soma ruído
    gaussiano independente na proporção que mistura `rho_true` de sinal com
    `sqrt(1-rho_true²)` de ruído. É uma mistura padrão (não um artifício
    nosso) — o valor exato por sorteio varia (isso é desejado: é a
    variabilidade de amostra finita que faz o diagnóstico medir uma TAXA de
    detecção, não um único ponto).

    **Ressalva da revisão independente (2026-08-26): `rho_true` é o
    COEFICIENTE de mistura, não garantidamente idêntico ao Spearman
    POPULACIONAL resultante para valores intermediários** (a identidade só
    é exata nos casos degenerados `rho_true ∈ {-1, 0, 1}` — ver os testes
    dedicados a esses três). Para a faixa intermediária que o diagnóstico
    realmente varre (`0,01`-`0,10`), a relação exata não tem forma fechada
    simples aqui (a base `z` é posto padronizado, não gaussiana — o fator
    clássico `(6/π)·arcsin(rho/2)` de uma normal bivariada não se aplica
    direto). `measure_achieved_spearman_rho` MEDE essa relação por Monte
    Carlo em vez de presumi-la (B23) — `run_eixo1_power_diagnostic_report`
    reporta o Spearman populacional REALMENTE alcançado ao lado do
    `rho_true` nominal, para cada ponto da grade.

    `NaN` em `fwd_return_ref` (ex.: últimas `h` barras sem futuro) produz
    `NaN` na mesma posição — alinhado por índice, nunca por filtragem
    (preserva o comprimento para `ic_disjoint` fatiar por offset de fase
    corretamente).

    Raises:
        Eixo1PowerDiagnosticError: `rho_true` fora de `[-1, 1]`.
    """
    if not -1.0 <= rho_true <= 1.0:
        raise Eixo1PowerDiagnosticError(f"rho_true={rho_true!r} fora de [-1, 1]")
    n = fwd_return_ref.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    valid = np.isfinite(fwd_return_ref)
    n_valid = int(valid.sum())
    if n_valid < 2:
        return out
    ranks = rankdata(fwd_return_ref[valid])
    rank_std = float(ranks.std())
    if rank_std == 0.0:
        return out
    z = (ranks - ranks.mean()) / rank_std
    noise = rng.standard_normal(n_valid)
    mix_weight = math.sqrt(max(0.0, 1.0 - rho_true * rho_true))
    out[valid] = rho_true * z + mix_weight * noise
    return out


#: Tamanho de amostra e número de sorteios do MC de calibração de
#: `measure_achieved_spearman_rho` — não é o `N` da série de barras real
#: (esse vem de `close`/`fwd_by_h`), é só a precisão da MEDIÇÃO de quanto
#: Spearman populacional `synthetic_correlated_series` de fato entrega por
#: `rho_true`. `20000`/`30` dão erro-padrão da média « a diferença que
#: importaria distinguir (~0,01, a menor célula da grade).
_ACHIEVED_RHO_CHECK_N: Final[int] = 20000
_ACHIEVED_RHO_CHECK_DRAWS: Final[int] = 30


def measure_achieved_spearman_rho(rho_true: float, *, seed: int) -> float:
    """Spearman populacional MÉDIO de fato alcançado por
    `synthetic_correlated_series` para um dado `rho_true` — resolve a
    ressalva da revisão independente (2026-08-26): mede a relação entre o
    coeficiente de mistura e o Spearman resultante em vez de presumi-la
    igual (B23). Referência SINTÉTICA (`rng.standard_normal`, não dado
    real) — mede só a propriedade da própria construção, independente de
    qualquer série de preço específica."""
    rng = np.random.default_rng(seed)
    ics = []
    for _ in range(_ACHIEVED_RHO_CHECK_DRAWS):
        ref = rng.standard_normal(_ACHIEVED_RHO_CHECK_N)
        synthetic = synthetic_correlated_series(ref, rho_true, rng)
        ic = spearman_ic(synthetic, ref)
        if math.isfinite(ic):
            ics.append(ic)
    return float(np.mean(ics)) if ics else float("nan")


def peak_abs_t_for_series(feature: FloatArray, fwd_by_horizon: Mapping[int, FloatArray]) -> float:
    """Pico de `|t|` sobre os horizontes já pré-computados em
    `fwd_by_horizon` — MESMA lógica de `ic_by_horizon.peak_horizon`: o
    horizonte escolhido é o de MAIOR `|IC|` (não o de maior `|t|` -- as duas
    seleções divergem porque `stderr` varia por horizonte, `n_s` menor em
    horizontes maiores/menos subamostras disjuntas), e só DEPOIS lê o `|t|`
    DAQUELE horizonte.

    **Achado da revisão independente (2026-08-26): a primeira versão desta
    função maximizava `|ic/stderr|` diretamente sobre os horizontes --
    critério DIFERENTE do de produção, e sistematicamente `>=` ao critério
    correto (maximizar sobre um conjunto de razões é sempre `>=` a razão no
    ponto de máximo do numerador). Sob `rho_true=0,0` (o controle negativo
    do diagnóstico), isso reintroduzia exatamente o viés de peak-hunting não
    corrigido que o `AG-327`/`eixo1_maxt_horizon_permutation.py` existe para
    investigar -- só que a favor da candidata sintética, inflando a taxa de
    detecção medida além do viés de `N` já divulgado no docstring do
    módulo. Corrigido para replicar `peak_horizon` com fidelidade.**

    `NaN` se nenhum horizonte tiver `ic` finito, ou se o horizonte de maior
    `|ic|` não tiver `stderr` finito/positivo -- mesma semântica de
    `peak_horizon` com `pico_ic=None`/pico sem `stderr` utilizável.
    """
    best_abs_ic = -1.0
    best_ic: float | None = None
    best_stderr: float | None = None
    for horizon_bars, fwd in fwd_by_horizon.items():
        ic, stderr, _n_total, _n_sub = ic_disjoint(feature, fwd, horizon_bars)
        if math.isfinite(ic) and abs(ic) > best_abs_ic:
            best_abs_ic, best_ic, best_stderr = abs(ic), ic, stderr
    if best_ic is None or best_stderr is None:
        return float("nan")
    if not math.isfinite(best_stderr) or best_stderr <= 0.0:
        return float("nan")
    return abs(best_ic / best_stderr)  # noqa: unguarded-ratio -- best_stderr>0 verificado acima


def p_values_with_synthetic(
    real_pico_abs_t: Mapping[str, float | None],
    synthetic_pico_abs_t: float,
    *,
    synthetic_name: str = _SYNTHETIC_NAME,
) -> dict[str, float]:
    """Mapa de p-valores `{feature: p}` com a candidata sintética ADICIONADA
    à família real (73ª posição, nunca substituindo uma real) — mesma
    conversão normal padrão de produção (`two_sided_p_from_t`). `None`/
    `NaN` em `real_pico_abs_t` vira `p=1,0` (mesma leitura de
    `feature_promotion_criterion.p_value_from_feature_entry` para coluna sem
    pico — nunca descoberta, mas conta no denominador `m` do BH)."""
    out: dict[str, float] = {}
    for name, t in real_pico_abs_t.items():
        out[name] = two_sided_p_from_t(t) if t is not None and math.isfinite(t) else 1.0
    out[synthetic_name] = (
        two_sided_p_from_t(synthetic_pico_abs_t) if math.isfinite(synthetic_pico_abs_t) else 1.0
    )
    return out


def synthetic_is_discovered(
    real_pico_abs_t: Mapping[str, float | None],
    synthetic_pico_abs_t: float,
    *,
    q: float,
    synthetic_name: str = _SYNTHETIC_NAME,
) -> bool:
    """`True` se a candidata sintética seria descoberta pelo MESMO BH que a
    produção roda (`feature_promotion_criterion.benjamini_hochberg`), quando
    adicionada à família real de 72 p-valores numa única célula (resolução,
    símbolo)."""
    p_values = p_values_with_synthetic(
        real_pico_abs_t, synthetic_pico_abs_t, synthetic_name=synthetic_name
    )
    names = list(p_values.keys())
    discoveries = benjamini_hochberg([p_values[n] for n in names], q=q)
    return discoveries[names.index(synthetic_name)]


# ============================================================================
# Casca — resolve arquivo/barras reais, lê e persiste.
# ============================================================================


def _load_real_report(resolution_id: str, out_dir: Path) -> dict[str, Any]:
    path = out_dir / f"ic_by_horizon_report_{resolution_id}.json"
    if not path.exists():
        raise Eixo1PowerDiagnosticError(
            f"relatório de IC por horizonte de {resolution_id} não encontrado em "
            f"{path.resolve()} -- rode src.analysis.ic_by_horizon antes."
        )
    with path.open(encoding="utf-8") as fh:
        result: dict[str, Any] = json.load(fh)
    return result


def _real_pico_abs_t_by_symbol(report: Mapping[str, Any], symbol: str) -> dict[str, float | None]:
    por_simbolo = report.get("por_simbolo", {})
    sym_block = por_simbolo.get(symbol)
    if sym_block is None:
        raise Eixo1PowerDiagnosticError(f"símbolo {symbol!r} ausente do relatório")
    por_feature = sym_block.get("por_feature", {})
    return {name: entry.get("pico_abs_t") for name, entry in por_feature.items()}


def _close_from_bars(bars: pl.DataFrame) -> FloatArray:
    """Série de close ordenada e deduplicada por `open_time` (mesmo critério
    de `AG-264`/`ic_by_horizon._join_close`: fica a barra de MAIOR
    `close_time` por `open_time` -- barras de duração zero são resíduo do
    gerador, não barra real)."""
    barras = (
        bars.select(["open_time", "close_time", "close"])
        .sort(["open_time", "close_time"])
        .unique(subset=["open_time"], keep="last", maintain_order=True)
    )
    return barras["close"].cast(pl.Float64).to_numpy().astype(np.float64)


def _fwd_by_horizon(close: FloatArray, horizons: Sequence[int]) -> dict[int, FloatArray]:
    return {h: forward_log_return(close, h) for h in horizons}


def _write_atomic(path: Path, content: str) -> Path:
    """B29 -- `.tmp` -> `fsync` -> `rename`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    fd = os.open(tmp, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


@dataclass(frozen=True, slots=True)
class _Cell:
    fwd_by_h: dict[int, FloatArray]
    real_t: dict[str, float | None]
    n_bars: int


def run_eixo1_power_diagnostic_report(
    *,
    symbols: Sequence[str] = SYMBOLS,
    resolutions: Sequence[str] = RESOLUTIONS,
    start: str,
    end: str,
    target_rhos: Sequence[float] = DEFAULT_TARGET_RHOS,
    n_mc_draws: int = DEFAULT_N_MC_DRAWS,
    q: float | None = None,
    k_thresholds: Sequence[int] = DEFAULT_K_THRESHOLDS,
    seed: int = DEFAULT_SEED,
    out_dir: Path = EXPERIMENTS_DIR,
) -> Path:
    """Casca: mede a curva de poder empírica do eixo 1 por injeção de sinal
    sintético, contra os relatórios reais + barras reais. Persiste
    `experiments/eixo1_power_diagnostic_report.json`.

    `resolutions` precisa ter exatamente 3 elementos (`symbol_is_majority_
    discovery` exige isso, mesma restrição de `feature_promotion_
    criterion.py`)."""
    from src.features._sources import load_bars

    if len(resolutions) != 3:
        raise Eixo1PowerDiagnosticError(
            f"esperado exatamente 3 resoluções, recebido {len(resolutions)} "
            "(agregação por maioria exige isso)"
        )

    q_bh = q if q is not None else float(load_constant("feature_promotion_bh_q"))
    horizons = DEFAULT_HORIZONS
    reports = {r: _load_real_report(r, out_dir) for r in resolutions}

    cells: dict[tuple[str, str], _Cell] = {}
    for resolution_id in resolutions:
        bar_source = f"dollar_{resolution_id.lower()}"
        for symbol in symbols:
            bars = load_bars(symbol, start, end, bar_source=bar_source)
            close = _close_from_bars(bars)
            cell = _Cell(
                fwd_by_h=_fwd_by_horizon(close, horizons),
                real_t=_real_pico_abs_t_by_symbol(reports[resolution_id], symbol),
                n_bars=close.shape[0],
            )
            cells[(resolution_id, symbol)] = cell
            logger.info(
                "analysis.eixo1_power_diagnostic.cell_loaded",
                resolution_id=resolution_id,
                symbol=symbol,
                n_bars=cell.n_bars,
            )

    curva_de_poder: list[dict[str, Any]] = []
    for rho_idx, rho_true in enumerate(target_rhos):
        k_symbols_per_draw = np.zeros(n_mc_draws, dtype=np.int64)
        for draw in range(n_mc_draws):
            n_symbols_discovering = 0
            for sym_idx, symbol in enumerate(symbols):
                per_resolution_discovery: list[bool] = []
                for res_idx, resolution_id in enumerate(resolutions):
                    cell = cells[(resolution_id, symbol)]
                    rng = np.random.default_rng([seed, rho_idx, draw, sym_idx, res_idx])
                    synthetic = synthetic_correlated_series(cell.fwd_by_h[1], rho_true, rng)
                    pico_abs_t = peak_abs_t_for_series(synthetic, cell.fwd_by_h)
                    discovered = synthetic_is_discovered(cell.real_t, pico_abs_t, q=q_bh)
                    per_resolution_discovery.append(discovered)
                if symbol_is_majority_discovery(tuple(per_resolution_discovery)):
                    n_symbols_discovering += 1
            k_symbols_per_draw[draw] = n_symbols_discovering

        detection_rate_by_k = {
            k: float(np.mean(k_symbols_per_draw >= k)) for k in k_thresholds
        }
        # MEDE o Spearman populacional REALMENTE entregue por rho_true (achado da
        # revisão independente, 2026-08-26) -- rho_true é o coeficiente de mistura,
        # não garantidamente idêntico ao Spearman resultante fora dos casos
        # degenerados -1/0/1 (ver docstring de synthetic_correlated_series).
        rho_achieved = measure_achieved_spearman_rho(rho_true, seed=seed + rho_idx)
        curva_de_poder.append(
            {
                "rho_true": rho_true,
                "rho_alcancado_medio": rho_achieved,
                "n_mc_draws": n_mc_draws,
                "detection_rate_by_k": detection_rate_by_k,
            }
        )
        logger.info(
            "analysis.eixo1_power_diagnostic.rho_done",
            rho_true=rho_true,
            rho_alcancado_medio=round(rho_achieved, 4) if math.isfinite(rho_achieved) else None,
            detection_rate_by_k=detection_rate_by_k,
        )

    payload: dict[str, Any] = {
        "task": "eixo1_power_diagnostic",
        "pergunta": "O eixo 1 (AG-294) tem poder para detectar um IC populacional "
        "realista (nao so o tamanho de um artefato de dado)? AG-327.",
        "adr_ref": "docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md §14.9/§14.10; "
        "docs/investigacao_falso_negativo_eixo1_2026-08-26.md §3.3, §8 item 1",
        "metodo": "injecao de serie sintetica com correlacao de Spearman populacional "
        "rho_true (referencia h=1), pico_abs_t pela MESMA matematica de "
        "ic_by_horizon.ic_disjoint, injetada como 73a candidata na familia real "
        "de 72 p-valores + BH q identico a producao, maioria >=2/3 resolucoes, "
        "taxa de deteccao por Monte Carlo (n_mc_draws sorteios).",
        "aviso": "DIAGNOSTICO, nao decide promocao -- usa a serie de barras COMPLETA "
        "(sem mascara de warmup de producao), entao N e ligeiramente MAIOR que o "
        "real -- leitura levemente OTIMISTA do poder, declarada, nao escondida.",
        "q_bh": q_bh,
        "n_mc_draws": n_mc_draws,
        "k_thresholds": list(k_thresholds),
        "seed": seed,
        "symbols": list(symbols),
        "resolutions": list(resolutions),
        "janela": {"start": start, "end": end},
        "n_bars_por_celula": {
            f"{r}/{s}": cells[(r, s)].n_bars for r in resolutions for s in symbols
        },
        "curva_de_poder": curva_de_poder,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    report_path = _write_atomic(
        out_dir / "eixo1_power_diagnostic_report.json",
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    logger.info(
        "analysis.eixo1_power_diagnostic.done",
        report_path=str(report_path.resolve()),
        curva_de_poder=curva_de_poder,
    )
    return report_path


if __name__ == "__main__":  # pragma: no cover -- execução manual
    import argparse

    parser = argparse.ArgumentParser(
        description="Diagnostico de poder do eixo 1 por injecao sintetica (AG-327)."
    )
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    parser.add_argument("--resolutions", nargs="+", default=list(RESOLUTIONS))
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--n-mc-draws", type=int, default=DEFAULT_N_MC_DRAWS)
    parser.add_argument("--target-rhos", type=float, nargs="+", default=list(DEFAULT_TARGET_RHOS))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    out_path = run_eixo1_power_diagnostic_report(
        symbols=tuple(args.symbols),
        resolutions=tuple(args.resolutions),
        start=args.start,
        end=args.end,
        target_rhos=tuple(args.target_rhos),
        n_mc_draws=args.n_mc_draws,
        seed=args.seed,
    )
    logger.info("analysis.eixo1_power_diagnostic.cli_done", report_path=str(out_path.resolve()))
