"""Curva de IC por horizonte — para qual horizonte cada feature realmente
serve, medido em vez de presumido.

**A pergunta.** `AG-263` produziu a ficha de tese das 72 colunas do vetor e
achou 33 sem nenhum mecanismo econômico declarado. Isso responde "há tese?",
não "há sinal?". As duas perguntas são independentes e o cruzamento delas é
o que decide o destino de cada coluna:

    tese declarada + IC pica perto do holding  -> coerente, manter
    tese declarada + IC plano                  -> tese sem sinal
    sem tese + IC pica perto do holding        -> tese a descobrir
    sem tese + IC plano                        -> nada, descartar

**O que a curva mostra.** O IC da feature contra o retorno futuro de `h`
barras, para `h` em `1, 2, 4, 8, 16, 32`. O pico revela o horizonte para o
qual a feature de fato serve. Pico muito além do holding significa que a
feature foi desenhada para outro jogo — nesse caso o certo é reclassificar
o papel ou descartar, **nunca** ajustar o span até o IC subir, que é
sobreajuste com passos extras.

O holding medido deste motor é `H = 5 barras` (mediana nas 3 grades), então
o horizonte de interesse fica entre `h=4` e `h=8`.

---

**B06 — ESTE RELATÓRIO NÃO CONFIGURA MODELO.** O banned pattern B06 do
`CLAUDE.md` proíbe usar uma tabela de IC de amostra cheia para configurar
modelo; a triagem que decide feature tem que ser in-fold. Esta medição é
descritiva e pós-hoc, feita sobre a série inteira e portanto contaminada
por look-ahead de SELEÇÃO se usada para escolher colunas. É por isso que
ela vive em `analysis/` — o pacote deliberadamente fora do contrato
`importlinter` (`CLAUDE.md`, §Layer hierarchy), justamente para nunca poder
virar insumo de treino.

Use para: entender o desenho, achar incoerência entre span e horizonte,
priorizar o que investigar. Não use para: escolher o vetor de treino,
ajustar janela, ordenar features por importância.

---

**O erro, e a armadilha que ele esconde.** Retornos futuros de `h` barras
se sobrepõem, então observações consecutivas não são independentes e o erro
ingênuo de Spearman superestima a significância. A construção usada aqui é
a subamostra DISJUNTA: para o horizonte `h` existem `h` fases (offsets
`0..h-1`, passo `h`), e cada uma é livre de sobreposição por construção.

O IC reportado é a média entre as fases. O ERRO, porém, é o de UMA fase
(`1/sqrt(n_s - 1)`, com `n_s = n/h` pontos disjuntos), **não** o desvio
entre fases dividido por `sqrt(h)`.

A distinção não é pedante — a primeira versão deste módulo fez errado e o
resultado passou perto de ser reportado como achado. As `h` fases cobrem o
MESMO período de calendário, apenas em pontos de partida diferentes: elas
são fortemente redundantes, e o desvio entre elas mede variação de FASE de
amostragem, não incerteza estatística. Dividido por `sqrt(h)`, produzia
`|t|` da ordem de 85 para `IC` de 0,04 — número que não existe em série
financeira e que teria transformado ruído em sinal. Acrescentar fases não
traz período novo, logo não melhora a precisão.

O desvio entre fases continua sendo calculado, como `dispersao_entre_fases`
— diagnóstico de estabilidade da relação ao longo da barra, nunca erro.

Sobre B24: o banned pattern proíbe PRESUMIR `N_eff = n/h` como constante em
vez de medir a unicidade. Aqui `n_s` não é presumido — é a contagem das
subamostras disjuntas que o código de fato constrói e usa.

Núcleo puro (Idioma A): as funções de cálculo recebem arrays e devolvem
números. A casca (`run_ic_by_horizon_report`) resolve símbolo/grade, chama o
Feature Engine e persiste."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray
from scipy.stats import rankdata

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]

EXPERIMENTS_DIR: Final[Path] = Path("experiments")

#: Horizontes em BARRAS. Escala geométrica cobrindo de 1 barra a ~6x o
#: holding medido (H=5), que é o que revela se o pico está dentro ou fora
#: do jogo que este motor joga.
DEFAULT_HORIZONS: Final[tuple[int, ...]] = (1, 2, 4, 8, 16, 32)

#: Holding medido (mediana nas 3 grades, `experiments/
#: gate_efficiency_report.json`). Usado SÓ para rotular a coluna
#: `h_sobre_H` do relatório — não entra em nenhum cálculo de IC.
HOLDING_BARS: Final[int] = 5

#: |t| a partir do qual um pico de IC deixa de ser indistinguível de zero.
#: 2 é a convenção de ~95% para normal; declarado a priori, não escolhido
#: depois de ver as curvas.
_T_SIGNIFICANCE: Final[float] = 2.0  # noqa: magic-number -- limiar declarado a priori


#: Mínimo de pontos numa subamostra disjunta para o IC dela ser usado.
#: Abaixo disso o Spearman é ruído e entra `NaN` em vez de um número que
#: parece medição.
_MIN_POINTS: Final[int] = 100  # noqa: magic-number -- piso de sanidade amostral, não hiperparâmetro


class ICError(RuntimeError):
    """Erro estrutural do cálculo de IC — entrada inconsistente. Nunca
    silencia: array de tamanho errado vira exceção, não um `NaN` que se
    propaga para o relatório parecendo medição."""


# ============================================================================
# Núcleo puro — zero IO
# ============================================================================


@dataclass(frozen=True, slots=True)
class ICPoint:
    """IC de uma feature num horizonte, com o erro medido entre subamostras
    disjuntas."""

    feature: str
    horizon_bars: int
    h_sobre_holding: float
    ic: float
    ic_stderr: float
    n_points: int
    n_disjoint_subsamples: int
    n_points_por_subamostra: int
    abs_t_stat: float
    dispersao_entre_fases: float


def forward_log_return(close: FloatArray, horizon_bars: int) -> FloatArray:
    """`log(close[t+h] / close[t])`, com `NaN` nas últimas `h` posições
    (não há futuro para elas). Alinhado por posição com `close`."""
    if horizon_bars < 1:
        raise ICError(f"horizon_bars={horizon_bars!r} precisa ser >= 1")
    n = close.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n > horizon_bars:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[:-horizon_bars] = np.log(
                close[horizon_bars:] / close[:-horizon_bars]  # noqa: unguarded-ratio -- preço real, sempre > 0 por construção
            )
    return out


def spearman_ic(x: FloatArray, y: FloatArray) -> float:
    """Correlação de Spearman = Pearson sobre os postos. `rankdata` com
    empates resolvidos por média — importa aqui porque várias colunas do
    vetor são flags ou têm massa em zero, e tratar empates por ordem de
    chegada inventaria ordenação que o dado não tem.

    Devolve `NaN` se qualquer lado for constante (correlação indefinida,
    não zero — um lado sem variância não é "sem relação")."""
    if x.shape != y.shape:
        raise ICError(f"shapes diferentes: {x.shape} vs {y.shape}")
    if x.shape[0] < 2:
        return float("nan")
    rx = rankdata(x)
    ry = rankdata(y)
    sx = float(rx.std())
    sy = float(ry.std())
    if sx == 0.0 or sy == 0.0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def ic_disjoint(
    feature: FloatArray, fwd_return: FloatArray, horizon_bars: int
) -> tuple[float, float, int, int]:
    """IC médio e erro, medidos sobre as `h` subamostras DISJUNTAS do
    horizonte (offsets `0..h-1`, passo `h`).

    Devolve `(ic_medio, ic_stderr, n_pontos_totais, n_subamostras_usadas)`.

    Por que assim: retornos de `h` barras se sobrepõem, e o erro ingênuo de
    Spearman trataria observações fortemente dependentes como independentes.
    Cada subamostra de passo `h` é livre de sobreposição POR CONSTRUÇÃO —
    nenhuma suposição sobre a autocorrelação, e nenhuma fórmula de `N_eff`
    constante (B24)."""
    if feature.shape != fwd_return.shape:
        raise ICError(f"shapes diferentes: {feature.shape} vs {fwd_return.shape}")
    valid = np.isfinite(feature) & np.isfinite(fwd_return)
    n_total = int(valid.sum())
    if n_total < _MIN_POINTS:
        return float("nan"), float("nan"), n_total, 0

    f_valid = feature[valid]
    r_valid = fwd_return[valid]

    ics: list[float] = []
    for offset in range(horizon_bars):
        fs = f_valid[offset::horizon_bars]
        rs = r_valid[offset::horizon_bars]
        if fs.shape[0] < _MIN_POINTS:
            continue
        ic = spearman_ic(fs, rs)
        if math.isfinite(ic):
            ics.append(ic)

    if not ics:
        return float("nan"), float("nan"), n_total, 0

    ic_mean = float(np.mean(ics))

    # ERRO -- correção de uma versão anterior deste módulo, que dividia o
    # desvio entre offsets por `sqrt(len(ics))`. Estava ERRADO e do lado
    # perigoso: as `h` subamostras cobrem o MESMO período de calendário, só
    # em fases diferentes. Elas são fortemente redundantes entre si, então o
    # desvio ENTRE elas mede variação de FASE de amostragem, não incerteza
    # estatística -- e dividi-lo por `sqrt(h)` produzia `|t|` da ordem de 85
    # para `IC` de 0,04, que é absurdo em qualquer série financeira.
    #
    # O erro honesto é o de UMA subamostra disjunta: acrescentar offsets não
    # traz período novo, então a precisão não melhora com `h`. Cada
    # subamostra tem `n_total/h` pontos genuinamente não sobrepostos e o
    # erro de Spearman nela é `1/sqrt(n_s - 1)`.
    #
    # Sobre B24: o banned pattern proíbe PRESUMIR `N_eff = n/h` como
    # constante em lugar de medir a unicidade. Aqui `n_s` não é presumido —
    # é a contagem das subamostras disjuntas que o laço acima de fato
    # construiu e usou. A distinção é entre estimar uma quantidade por
    # fórmula e contar a que se tem em mãos.
    n_s = min(int(np.isfinite(f_valid[o::horizon_bars]).sum()) for o in range(horizon_bars))
    stderr = 1.0 / math.sqrt(n_s - 1) if n_s > 1 else float("nan")
    return ic_mean, stderr, n_total, len(ics)


def phase_dispersion(
    feature: FloatArray, fwd_return: FloatArray, horizon_bars: int
) -> float:
    """Desvio do IC ENTRE os offsets de fase — diagnóstico, NUNCA o erro
    estatístico (ver a nota em `ic_disjoint`).

    Serve para outra pergunta: se o IC muda muito conforme a fase de
    amostragem, a relação não é estável ao longo da barra e o número médio
    esconde heterogeneidade."""
    valid = np.isfinite(feature) & np.isfinite(fwd_return)
    if int(valid.sum()) < _MIN_POINTS:
        return float("nan")
    f_valid = feature[valid]
    r_valid = fwd_return[valid]
    ics = [
        ic
        for o in range(horizon_bars)
        if f_valid[o::horizon_bars].shape[0] >= _MIN_POINTS
        and math.isfinite(ic := spearman_ic(f_valid[o::horizon_bars], r_valid[o::horizon_bars]))
    ]
    return float(np.std(ics, ddof=1)) if len(ics) > 1 else float("nan")


def ic_curve(
    features: dict[str, FloatArray],
    close: FloatArray,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    holding_bars: int = HOLDING_BARS,
) -> list[ICPoint]:
    """Curva completa: um `ICPoint` por (feature, horizonte). Puro — recebe
    arrays já em memória."""
    fwd_by_h = {h: forward_log_return(close, h) for h in horizons}
    out: list[ICPoint] = []
    for name, values in features.items():
        for h in horizons:
            ic, stderr, n_points, n_sub = ic_disjoint(values, fwd_by_h[h], h)
            disp = phase_dispersion(values, fwd_by_h[h], h)
            abs_t = (
                abs(ic / stderr)  # noqa: unguarded-ratio -- stderr>0 verificado na condição
                if math.isfinite(ic) and math.isfinite(stderr) and stderr > 0.0
                else float("nan")
            )
            out.append(
                ICPoint(
                    feature=name,
                    horizon_bars=h,
                    h_sobre_holding=h / holding_bars,
                    ic=ic,
                    ic_stderr=stderr,
                    n_points=n_points,
                    n_disjoint_subsamples=n_sub,
                    n_points_por_subamostra=n_points // h if h else 0,
                    abs_t_stat=abs_t,
                    dispersao_entre_fases=disp,
                )
            )
    return out


def peak_horizon(points: Sequence[ICPoint]) -> dict[str, Any]:
    """Horizonte de |IC| máximo de UMA feature, e se o pico é distinguível
    de zero. Um pico com `|t| < 2` não é pico — é a curva plana com ruído,
    e chamar isso de "a feature serve para h=16" seria inventar desenho."""
    finitos = [p for p in points if math.isfinite(p.ic)]
    if not finitos:
        return {"pico_horizon_bars": None, "pico_ic": None, "pico_significativo": None}
    melhor = max(finitos, key=lambda p: abs(p.ic))
    return {
        "pico_horizon_bars": melhor.horizon_bars,
        "pico_h_sobre_holding": melhor.h_sobre_holding,
        "pico_ic": melhor.ic,
        "pico_abs_t": melhor.abs_t_stat,
        "pico_significativo": bool(
            math.isfinite(melhor.abs_t_stat) and melhor.abs_t_stat >= _T_SIGNIFICANCE
        ),
    }


# ============================================================================
# Casca com IO
# ============================================================================


def _write_atomic(path: Path, content: str) -> Path:
    """B29 — `.tmp` -> `fsync` -> `rename`."""
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


def _feature_arrays(df: pl.DataFrame) -> dict[str, FloatArray]:
    """Extrai as colunas de feature do frame do Feature Engine. Colunas de
    tempo e não-numéricas ficam de fora."""
    excluir = {"open_time", "close_time", "open", "high", "low", "close", "volume"}
    features: dict[str, FloatArray] = {}
    for name, dtype in zip(df.columns, df.dtypes, strict=True):
        if name in excluir or not dtype.is_numeric():
            continue
        features[name] = df[name].cast(pl.Float64).to_numpy().astype(np.float64)
    return features


def _join_close(features_df: pl.DataFrame, bars_df: pl.DataFrame) -> FloatArray:
    """`close` alinhado ao frame de features por `open_time`.

    `build_t1_features` não devolve `close` — ele devolve features. O join
    é por CHAVE, nunca por posição: um `apply_warmup_mask` ou um corte de
    borda que mudasse a contagem de linhas entre os dois frames produziria,
    sob alinhamento posicional, um deslocamento silencioso entre feature e
    preço — que é exatamente a classe de bug que este módulo existiria para
    detectar, não para cometer."""
    if "open_time" not in features_df.columns:
        raise ICError("frame de features sem `open_time` -- não há chave para o join com barras")
    # AG-264 -- `open_time` NÃO é único nas dollar bars de produção: 9 das 15
    # combinações contêm barras de DURAÇÃO ZERO (`close_time == open_time`)
    # com volume muito abaixo do threshold, e algumas colidem no `open_time`
    # da barra real seguinte. Sem tratar, o join à esquerda multiplicaria
    # linhas e desalinharia feature e preço.
    #
    # Critério de desempate: fica a barra de MAIOR `close_time` — a que tem
    # duração real. Não é arbitrário: uma barra que abre e fecha no mesmo
    # instante não é uma barra, é resíduo do gerador. O `AG-202` já tinha
    # visto o sintoma a jusante (`.unique(subset=["t0"])` em `alpha.py`) sem
    # que a causa em `data/` fosse tratada -- aqui a escolha fica explícita e
    # contada, nunca silenciosa.
    barras = (
        bars_df.select(["open_time", "close_time", "close"])
        .sort(["open_time", "close_time"])
        .unique(subset=["open_time"], keep="last", maintain_order=True)
    )
    n_descartadas = bars_df.height - barras.height
    if n_descartadas:
        logger.warning(
            "analysis.ic_by_horizon.barras_duplicadas_descartadas",
            n_descartadas=n_descartadas,
            n_barras=bars_df.height,
            criterio="maior close_time por open_time (AG-264)",
        )
    juntado = features_df.select("open_time").join(
        barras.select(["open_time", "close"]), on="open_time", how="left"
    )
    if juntado.height != features_df.height:
        raise ICError(
            f"join de close alterou a contagem de linhas ({features_df.height} -> "
            f"{juntado.height}) -- `open_time` ainda duplicado após a dedupe"
        )
    close = juntado["close"].cast(pl.Float64).to_numpy().astype(np.float64)
    n_faltando = int(np.isnan(close).sum())
    if n_faltando:
        raise ICError(
            f"{n_faltando} de {close.shape[0]} barras sem `close` após o join -- "
            "features e barras vêm de janelas diferentes"
        )
    return close


def run_ic_by_horizon_report(
    *,
    symbols: Sequence[str],
    resolution_id: str,
    start: str,
    end: str,
    vol_estimator_id: str = "parkinson_w20",
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    out_dir: Path = EXPERIMENTS_DIR,
) -> Path:
    """Casca — constrói as features de cada símbolo na grade pedida, mede a
    curva de IC e persiste um relatório por resolução."""
    from src.features._sources import load_bars
    from src.features.build import build_t1_features

    bar_source = f"dollar_{resolution_id.lower()}"
    por_simbolo: dict[str, Any] = {}

    for symbol in symbols:
        df = build_t1_features(
            symbol,
            start,
            end,
            apply_warmup_mask=True,
            bar_source=bar_source,
            vol_estimator_id=vol_estimator_id,
            load_taker_imbalance_1m=False,
            load_futures_positioning=True,
        )
        bars = load_bars(symbol, start, end, bar_source=bar_source)
        features = _feature_arrays(df)
        close = _join_close(df, bars)
        pontos = ic_curve(features, close, horizons=horizons)

        por_feature: dict[str, Any] = {}
        for name in features:
            do_feature = [p for p in pontos if p.feature == name]
            por_feature[name] = {
                "curva": [asdict(p) for p in do_feature],
                **peak_horizon(do_feature),
            }
        por_simbolo[symbol] = {"n_bars": df.height, "por_feature": por_feature}
        logger.info(
            "analysis.ic_by_horizon.symbol_done",
            symbol=symbol,
            resolution_id=resolution_id,
            n_bars=df.height,
            n_features=len(features),
        )

    payload: dict[str, Any] = {
        "task": "ic_by_horizon",
        "pergunta": (
            "Para qual horizonte cada coluna do vetor realmente serve, e o pico "
            "e distinguivel de zero?"
        ),
        "B06_AVISO": (
            "DESCRITIVO E POS-HOC, medido sobre a serie inteira. B06 proibe usar "
            "tabela de IC de amostra cheia para configurar modelo -- a triagem que "
            "decide feature tem que ser in-fold. NAO usar para escolher vetor de "
            "treino, ajustar janela nem ordenar features."
        ),
        "metodo_erro": (
            "IC medio sobre as h subamostras DISJUNTAS do horizonte (offsets 0..h-1, "
            "passo h), erro = desvio entre elas / sqrt(h). Sem formula de N_eff "
            "constante (B24). Para h=1, erro analitico de Spearman 1/sqrt(n-1)."
        ),
        "resolution_id": resolution_id,
        "horizons_bars": list(horizons),
        "holding_bars": HOLDING_BARS,
        "t_significancia": _T_SIGNIFICANCE,
        "janela": {"start": start, "end": end},
        "vol_estimator_id": vol_estimator_id,
        "por_simbolo": por_simbolo,
    }
    destino = out_dir / f"ic_by_horizon_report_{resolution_id}.json"
    caminho = _write_atomic(destino, json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info("analysis.ic_by_horizon.done", report_path=str(caminho.resolve()))
    return caminho


if __name__ == "__main__":  # pragma: no cover -- execução manual
    import argparse

    ap = argparse.ArgumentParser(description="Curva de IC por horizonte (AG-263).")
    ap.add_argument("--resolution-id", default="R1", choices=["R1", "R2", "R3"])
    ap.add_argument("--symbols", default="BTCUSDT")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default="2026-08-07")
    ap.add_argument("--vol-estimator-id", default="parkinson_w20")
    args = ap.parse_args()

    run_ic_by_horizon_report(
        symbols=tuple(s.strip() for s in args.symbols.split(",") if s.strip()),
        resolution_id=args.resolution_id,
        start=args.start,
        end=args.end,
        vol_estimator_id=args.vol_estimator_id,
    )
