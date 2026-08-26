"""Eixo 2 do critério de evidência (ADR-005 §2.2) — estabilidade temporal,
em código pela primeira vez (`AG-274`).

**Por que existe.** `§2.2` define o eixo 2 em prosa desde a v2: IC medido em
subperíodos semestrais disjuntos, exigindo `max|IC_sub| / mediana|IC_sub| ≤
4` e direção consistente em `≥ 70%` dos subperíodos. Nunca virou código —
os únicos números que existem (`E18f`/`E16f`/`E14f`/`D06f`/`A01`, todos em
BTCUSDT/R1) foram calculados uma vez, à mão, pra calibrar os dois limiares.
`AG-274` (`project_assurance`) achou isso: "eixo 2 não tem código nem
artefato, e 6 termos sem definição operacional". Este módulo fecha o
código; as definições operacionais que faltavam ficam explícitas abaixo,
cada uma com a pergunta que ela resolve.

**As definições que faltavam — as 2 primeiras foram FIXADAS POR REPRODUÇÃO
(2026-08-26), não por leitura da prosa: rodei os 5 casos calibrados de
§2.2 (`E18f`/`E16f`/`E14f`/`D06f`/`A01`, BTCUSDT/R1) contra hipóteses
concorrentes até bater os números publicados exatamente (`ratio` e
`frac_mesma_direcao` nas 3ª/4ª casas decimais, nos 5 casos). A prosa do
§2.2 nunca especificava nenhuma das duas — a 1ª tentativa deste módulo
adivinhou errado nas duas, documentado abaixo porque a tentativa errada
é informativa sobre a ambiguidade real:**

1. **Em qual horizonte o IC de cada subperíodo é medido?** `h=1`, FIXO
   pra toda feature/célula — NÃO o `pico_horizon_bars` do eixo 1 (1ª
   tentativa deste módulo, ERRADA: só reproduzia `E18f`, cujo pico
   também é `h=1` por coincidência; `E16f`/`E14f` picam em `h=32`,
   `D06f`/`A01` em `h=16`, e usar o pico de cada um dava `ratio` bem
   diferente do publicado). A prosa de §2.2 nunca disse "no pico" — foi
   suposição deste módulo, e a suposição não sobreviveu à reprodução.
   Sem justificativa econômica declarada em lugar nenhum pra por que
   `h=1` especificamente (vs. o pico, vs. o holding `H=5`) — registrado
   como lacuna residual, não fingido como decisão deliberada.
2. **"Direção consistente" — consistente com QUAL direção?** Com a
   MAIORIA dos próprios semestres (`max(n_positivos, n_negativos) /
   n_total`) — NÃO o sinal de `pico_ic` do período inteiro (1ª tentativa
   deste módulo, ERRADA: só `D06f` discrimina as duas leituras — maioria
   por contagem simples dá 60%/positiva, `pico_ic` pondera pela série
   inteira e dá 40%/negativa — e só a maioria bate os 60% publicados).
   "Maioria dos próprios semestres" não é circular (preocupação original
   deste módulo): é perguntar se os semestres concordam ENTRE SI, que é
   o que "consistente" significa. Consequência: o piso da métrica é 50%
   por construção, não 0%.
3. **O que é um "subperíodo semestral"?** Semestre de CALENDÁRIO
   (`ano×2 + {0 se mês≤6, 1 senão}`), não uma fatia de tamanho fixo em
   barras — é o eixo desenhado pra pegar o padrão que `AG-266` mostrou
   (blocos de MESES ligando/desligando), não uma partição arbitrária.
4. **`n ≥ 1000` é de quê?** Pontos com feature E retorno futuro finitos
   dentro do semestre, na MESMA célula `(symbol, resolution)`.
5. **`max|IC_sub|`/`mediana|IC_sub|` são sobre qual conjunto?** Os
   `IC_sub` dos semestres que passaram o piso de (4), para UMA célula —
   o eixo 2 roda por célula, como o eixo 1 antes da correção de
   `AG-294`; a agregação por símbolo (maioria das resoluções) é decisão
   de quem consome este relatório, não deste módulo.
6. **O IC de um semestre é a subamostra disjunta de `ic_by_horizon.py`,
   ou o Spearman simples?** Spearman simples (`ic_by_horizon.
   spearman_ic`) sobre as linhas do semestre. A subamostra disjunta
   existe pra separar sobreposição DENTRO de uma janela de retorno
   contígua — aqui a partição em semestres já é, por construção, uma
   partição sem sobreposição de calendário; aplicar a subamostra disjunta
   por cima cortaria o semestre em pedaços ainda menores sem necessidade.

**Verificação exata dos 5 casos (h=1, maioria própria), `2026-08-26`:**

| feature | §2.2 ratio | medido | §2.2 direção | medido |
|---|---|---|---|---|
| `E18f_taker_ls_vol_ratio` | 12,57 | 12,571 | 50% | 50,0% |
| `E16f_global_ls_ratio` | 2,98 | 2,975 | 90% | 90,0% |
| `E14f_toptrader_ls_ratio` | 1,50 | 1,504 | 100% | 100,0% |
| `D06f_taker_imbalance_z_48` | 1,92 | 1,918 | 60% | 60,0% |
| `A01_log_return_1` | 2,28 | 2,277 | 80% | 80,0% |

**O que este módulo NÃO faz.** Não decide o eixo 1 (isso é `AG-294`,
`feature_promotion_criterion.py`). Não promove/aposenta feature — devolve
métricas e veredito por célula, decisão é de quem lê (mesmo espírito
DECISION-SUPPORT de todo o resto desta linha de trabalho). Os limiares
(`max_ratio=4`, `min_direction_frac=0,70`) foram calibrados olhando os 5
casos conhecidos (§2.2, "honestidade sobre a calibração") — `provenance:
ASSUMED`, não `DERIVED`, porque calibração de instrumento sobre casos
conhecidos não é derivação a partir de outra constante medida."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl
import structlog
from numpy.typing import NDArray

from src.analysis.ic_by_horizon import forward_log_return, spearman_ic
from src.labels._constants import load_constant

logger = structlog.get_logger(__name__)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

EXPERIMENTS_DIR: Final[Path] = Path("experiments")
RESOLUTIONS: Final[tuple[str, ...]] = ("R1", "R2", "R3")


class FeatureTemporalStabilityError(RuntimeError):
    """Erro estrutural -- artefato de origem ausente, célula sem semestre
    válido, ou direção de referência indefinida. Nunca cai num veredito
    inventado (Regra Zero)."""


# ============================================================================
# Núcleo puro — zero IO (Idioma A)
# ============================================================================


def semester_bucket_id(open_time_ms: int) -> int:
    """`ano×2 + {0 se mês≤6, 1 senão}` -- bucket inteiro monotônico de
    semestre de CALENDÁRIO a partir de `open_time` (epoch ms, UTC).
    Definição operacional 2 (ver docstring do módulo)."""
    dt = datetime.fromtimestamp(open_time_ms / 1000.0, tz=UTC)  # noqa: magic-number -- ms -> s, conversao de unidade
    half = 0 if dt.month <= 6 else 1
    return dt.year * 2 + half


def semester_label(bucket_id: int) -> str:
    """`'YYYY-H1'`/`'YYYY-H2'` a partir do bucket de `semester_bucket_id`."""
    year, half = divmod(bucket_id, 2)
    return f"{year}-H{half + 1}"


def semester_bucket_ids(open_time_ms: IntArray) -> IntArray:
    """Versão vetorizada de `semester_bucket_id` -- mesma definição,
    aplicada a um array inteiro via aritmética de `datetime64`, não um
    laço Python por linha."""
    as_dt = open_time_ms.astype("datetime64[ms]")
    years = as_dt.astype("datetime64[Y]").astype(np.int64) + 1970
    months = as_dt.astype("datetime64[M]").astype(np.int64) % 12 + 1
    half = (months > 6).astype(np.int64)
    result: IntArray = years * 2 + half
    return result


def ic_per_semester(
    feature: FloatArray,
    fwd_return: FloatArray,
    semester_ids: IntArray,
    *,
    min_points: int,
) -> dict[int, tuple[float, int]]:
    """`{semestre: (ic, n)}`, só para semestres com `n >= min_points`
    observações finitas (feature E retorno). Spearman simples por
    semestre (definição operacional 6) -- não a subamostra disjunta de
    `ic_by_horizon.ic_disjoint`, que resolve um problema diferente
    (sobreposição dentro de uma janela contígua, não entre semestres)."""
    if feature.shape != fwd_return.shape or feature.shape != semester_ids.shape:
        raise FeatureTemporalStabilityError(
            f"shapes diferentes: feature={feature.shape}, fwd_return={fwd_return.shape}, "
            f"semester_ids={semester_ids.shape}"
        )
    valid = np.isfinite(feature) & np.isfinite(fwd_return)
    out: dict[int, tuple[float, int]] = {}
    for sid in sorted(set(semester_ids.tolist())):
        mask = valid & (semester_ids == sid)
        n = int(mask.sum())
        if n < min_points:
            continue
        ic = spearman_ic(feature[mask], fwd_return[mask])
        if np.isfinite(ic):
            out[sid] = (float(ic), n)
    return out


@dataclass(frozen=True, slots=True)
class TemporalStabilityResult:
    n_semestres_validos: int
    max_abs_ic: float
    median_abs_ic: float
    ratio: float
    n_mesma_direcao: int
    frac_mesma_direcao: float
    passa_ratio: bool
    passa_direcao: bool
    passa_eixo_2: bool


def evaluate_temporal_stability(
    ic_by_semester: Mapping[int, tuple[float, int]],
    *,
    max_ratio: float,
    min_direction_frac: float,
    min_semesters: int,
) -> TemporalStabilityResult:
    """Núcleo: aplica os dois critérios do eixo 2 a `{semestre: (ic, n)}`
    já filtrado por `n >= min_points` (`ic_per_semester`).

    **`min_semesters` -- achado `project_assurance` 2026-08-26 (revisão do
    `ADR-005` §14), CONFIRMADO.** Com exatamente 1 semestre válido,
    `median_abs_ic = max_abs_ic` (mediana de 1 elemento é o próprio
    elemento) → `ratio = 1.0` sempre `≤ max_ratio`, e
    `frac_mesma_direcao = 1/1 = 100%` sempre `≥ min_direction_frac` —
    `passa_eixo_2=True` INCONDICIONALMENTE, sem relação com a
    confiabilidade real do IC. A v1 deste módulo só levantava erro com
    `ic_by_semester` vazio, nunca com poucos elementos. `min_semesters`
    fecha isso: abaixo do piso, o resultado é indefinido (levanta), não
    um "passa" vazio de conteúdo.

    **Definição operacional 5, CORRIGIDA por reprodução (2026-08-26).** A
    v1 deste módulo usava o sinal de `pico_ic` (IC do período inteiro) como
    referência, com a ressalva de que usar a maioria dos próprios
    semestres seria circular. Errado: reproduzindo os 5 casos calibrados
    de §2.2 com `h=1` fixo, `D06f_taker_imbalance_z_48` só bate os 60%
    citados (6 de 10 semestres positivos) quando a referência é a MAIORIA
    dos próprios semestres — usar `pico_ic` (que pondera pela série
    inteira, dominada pelos semestres de maior `n`) dava 40%, direção
    oposta. Os outros 4 casos (`E18f`=50%, `E16f`=90%, `E14f`=100%,
    `A01`=80%) batem com qualquer uma das duas leituras porque não têm um
    semestre de peso desproporcional invertendo a maioria — só `D06f`
    discrimina. "Maioria dos próprios semestres" não é circular: é
    perguntar se os semestres concordam ENTRE SI, o que é exatamente o
    que "direção consistente" significa. O piso da métrica é 50% por
    construção (a maioria sempre bate consigo mesma pelo menos na metade),
    não 0% — `min_direction_frac` precisa ser lido nessa escala."""
    if not ic_by_semester:
        raise FeatureTemporalStabilityError(
            "nenhum semestre com dado suficiente -- eixo 2 indefinido pra esta célula"
        )
    if len(ic_by_semester) < min_semesters:
        raise FeatureTemporalStabilityError(
            f"{len(ic_by_semester)} semestre(s) válido(s) < min_semesters={min_semesters} -- "
            "ratio/direção não são confiáveis com tão poucos pontos (ver docstring)"
        )

    ics = [v[0] for v in ic_by_semester.values()]
    abs_ics = [abs(x) for x in ics]
    max_abs = max(abs_ics)
    median_abs = float(np.median(abs_ics))
    ratio = float("inf") if median_abs == 0.0 else max_abs / median_abs  # noqa: unguarded-ratio -- guarda no ternário

    n_positivos = sum(1 for ic in ics if ic > 0.0)
    n_mesma_direcao = max(n_positivos, len(ics) - n_positivos)
    frac_mesma_direcao = n_mesma_direcao / len(ics)  # noqa: unguarded-ratio -- len(ics)>=1, guarda no topo

    passa_ratio = ratio <= max_ratio
    passa_direcao = frac_mesma_direcao >= min_direction_frac

    return TemporalStabilityResult(
        n_semestres_validos=len(ics),
        max_abs_ic=max_abs,
        median_abs_ic=median_abs,
        ratio=ratio,
        n_mesma_direcao=n_mesma_direcao,
        frac_mesma_direcao=frac_mesma_direcao,
        passa_ratio=passa_ratio,
        passa_direcao=passa_direcao,
        passa_eixo_2=passa_ratio and passa_direcao,
    )


# ============================================================================
# Casca -- resolve arquivo, lê e persiste.
# ============================================================================


def _load_eixo1_report(resolution_id: str, out_dir: Path) -> dict[str, Any]:
    path = out_dir / f"ic_by_horizon_report_{resolution_id}.json"
    if not path.exists():
        raise FeatureTemporalStabilityError(
            f"relatório de IC por horizonte de {resolution_id} não encontrado em "
            f"{path.resolve()} -- rode src.analysis.ic_by_horizon antes."
        )
    with path.open(encoding="utf-8") as fh:
        result: dict[str, Any] = json.load(fh)
    return result


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


def run_feature_temporal_stability_report(
    *,
    symbols: Sequence[str],
    resolution_id: str,
    start: str,
    end: str,
    features_filter: Sequence[str] | None = None,
    out_dir: Path = EXPERIMENTS_DIR,
) -> Path:
    """Casca: pra cada `(symbol, feature)` na resolução pedida, recomputa a
    feature/o preço reais, particiona em semestres e aplica o eixo 2 em
    `h=1` fixo (definição operacional 1, fixada por reprodução -- ver
    docstring do módulo). Persiste
    `experiments/feature_temporal_stability_report_{R}.json`.

    O relatório do eixo 1 (`ic_by_horizon_report_{R}.json`) só é usado
    para saber QUAIS features existem por símbolo (lista de nomes) --
    `pico_horizon_bars`/`pico_ic` não são mais lidos dele (definições
    operacionais 1/2 corrigidas).

    `features_filter`: subconjunto de features a avaliar (`None` = todas
    as do relatório do eixo 1) -- rodar as 72×5 é caro; o uso típico é
    focar no que o eixo 1 já sinalizou como candidato."""
    from src.features._sources import load_bars
    from src.features.build import build_t1_features

    from .ic_by_horizon import _feature_arrays, _join_close  # núcleo já testado, reuso

    min_points_semester = int(load_constant("feature_temporal_stability_min_points_per_semester"))
    max_ratio = float(load_constant("feature_temporal_stability_max_ratio"))
    min_direction_frac = float(load_constant("feature_temporal_stability_min_direction_frac"))
    min_semesters = int(load_constant("feature_temporal_stability_min_semesters"))

    eixo1 = _load_eixo1_report(resolution_id, out_dir)
    bar_source = f"dollar_{resolution_id.lower()}"

    por_simbolo: dict[str, Any] = {}
    for symbol in symbols:
        eixo1_symbol = eixo1.get("por_simbolo", {}).get(symbol)
        if eixo1_symbol is None:
            raise FeatureTemporalStabilityError(
                f"{symbol}/{resolution_id}: ausente do relatório do eixo 1 -- rode-o antes"
            )
        eixo1_por_feature = eixo1_symbol.get("por_feature", {})

        df = build_t1_features(
            symbol,
            start,
            end,
            apply_warmup_mask=True,
            bar_source=bar_source,
            vol_estimator_id="parkinson_w20",
            load_taker_imbalance_1m=False,
            load_futures_positioning=True,
        )
        bars = load_bars(symbol, start, end, bar_source=bar_source)
        close = _join_close(df, bars)
        open_time_ms = df["open_time"].cast(pl.Int64).to_numpy()
        semester_ids = semester_bucket_ids(open_time_ms)
        feature_arrays = _feature_arrays(df)
        fwd_return_h1 = forward_log_return(close, 1)

        names = features_filter if features_filter is not None else list(eixo1_por_feature.keys())
        por_feature: dict[str, Any] = {}
        for name in names:
            values = feature_arrays.get(name)
            if values is None:
                continue

            ic_by_sem = ic_per_semester(
                values, fwd_return_h1, semester_ids, min_points=min_points_semester
            )
            if len(ic_by_sem) < min_semesters:
                por_feature[name] = {
                    "n_semestres_validos": len(ic_by_sem),
                    "passa_eixo_2": False,
                }
                continue
            resultado = evaluate_temporal_stability(
                ic_by_sem,
                max_ratio=max_ratio,
                min_direction_frac=min_direction_frac,
                min_semesters=min_semesters,
            )
            por_feature[name] = {
                **asdict(resultado),
                "horizon_bars_usado": 1,
                "semestres": {semester_label(sid): ic for sid, (ic, _n) in ic_by_sem.items()},
            }

        por_simbolo[symbol] = {"n_bars": df.height, "por_feature": por_feature}
        logger.info(
            "analysis.feature_temporal_stability.symbol_done",
            symbol=symbol,
            resolution_id=resolution_id,
            n_bars=df.height,
            n_features=len(por_feature),
        )

    payload = {
        "task": "feature_temporal_stability",
        "pergunta": "ADR-005 §2.2 eixo 2, em codigo pela 1a vez (AG-274).",
        "adr_ref": "docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md §2.2, §11.3 (AG-274)",
        "resolution_id": resolution_id,
        "min_points_por_semestre": min_points_semester,
        "max_ratio": max_ratio,
        "min_direction_frac": min_direction_frac,
        "min_semesters": min_semesters,
        "por_simbolo": por_simbolo,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    report_path = _write_atomic(
        out_dir / f"feature_temporal_stability_report_{resolution_id}.json",
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    logger.info(
        "analysis.feature_temporal_stability.done",
        report_path=str(report_path.resolve()),
        resolution_id=resolution_id,
    )
    return report_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Eixo 2 (estabilidade temporal, ADR-005 §2.2) -- AG-274."
    )
    parser.add_argument("--resolution-id", required=True, choices=RESOLUTIONS)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()

    out_path = run_feature_temporal_stability_report(
        symbols=args.symbols,
        resolution_id=args.resolution_id,
        start=args.start,
        end=args.end,
    )
    logger.info("analysis.feature_temporal_stability.cli_done", report_path=str(out_path.resolve()))
