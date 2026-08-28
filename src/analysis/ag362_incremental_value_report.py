"""AG-362 -- valor incremental real das 15 features L3->T1, medido sob
CPCV purgado -- desenho decidido pelo Manager, 2026-08-27.

**Por que existe.** `AG-362` reverteu o gate marginal (Spearman por
feature, `AG-294`/`AG-299`) que barrava 15 features com tese declarada,
sob o argumento de que o LightGBM captura interação nativamente e o
filtro marginal é estruturalmente cego a isso -- mas isso é uma
HIPÓTESE, não uma medição (o próprio `AG-362` registrou isso como
pendente: "medir valor incremental real... decisão/execução da sessão
de ML, fora deste escopo"). Este módulo fecha essa pendência: mede se o
Alpha ganha algo real com as 15 promovidas, comparado contra o vetor
base (7 features), sob os MESMOS caminhos de CPCV purgado (B06,
in-fold) -- não gain/AUC bruto de treino (`ADR-005` §13.13 já provou
que o loop de treino sozinho não sabe dizer "sem sinal": 69 colunas de
ruído gaussiano puro já produzem um modelo calibrado que dispara dentro
de 7% da taxa alvo -- ver docstring completa em
`docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md`).

**Desenho, decidido pelo Manager (2026-08-27).** 3 rodadas sequenciais
de `run_layer1_sprint_all_combinations` (15 combinações cada, symbol x
resolution -- 45 fits reais no total):

1. `stage="off"` -- `T1_FEATURE_IDS` atual (22, pós-`AG-362`) +
   `use_hyperparams_by_combo=False`.
2. `stage="on"` -- `T1_FEATURE_IDS` atual (22) +
   `use_hyperparams_by_combo=True`.
3. `stage="base"` -- lê os 2 relatórios acima do disco, decide o
   vencedor de hiperparâmetro (ver definição operacional abaixo), roda
   `ORIGINAL_T1_FEATURE_IDS` (7, pré-`AG-362`) sob ESSA config vencedora
   -- "Alpha base", única variável isolada = o vetor de features.

Cada estágio é um processo/invocação `--stage` separada (CLI abaixo),
não uma função única de ponta a ponta -- 3 rodadas de 15 combinações
reais custam horas; estágios separados persistem o resultado caro
(`reports_raw`) antes de decidir o próximo passo, então uma falha no
estágio 3 não perde o trabalho dos estágios 1/2.

**Definição operacional do "vencedor" entre 1 e 2** (nenhuma métrica
pós-hoc nova -- reusa a própria régua de decisão que `run_layer1_sprint`
já pré-registra em `layer1_vs_layer0`): contagem de `permanence_pass=
True` entre as 15 combinações. Empate (diferença de contagem == 0)
desempata por soma de `delta_sharpe_mean` entre as 15 combinações
(positivo favorece Camada 1).

**O que este módulo NÃO decide.** Se a rodada 3 (base) ganha de 1 ou 2
(vetor cheio) é a leitura que decide se as 15 promovidas de fato ajudam
-- fica para quem ler o relatório final (Manager), não automatizada
aqui (mesma disciplina dos módulos irmãos `eixo1_*`). Também não decide
quantos trials este episódio vale em `audit/n_lifetime.yaml` --
`run_layer1_sprint_all_combinations` já documenta essa leitura como
"genuinamente aberta, decisão do Manager antes de logar"; este módulo
só deixa os 3 desenhos e os 45 fits explícitos no relatório final pra
essa decisão ser tomada com o número certo na mão.

Núcleo puro (Idioma A): `summarize_combinations`,
`pick_better_hyperparam_config`. A casca (`run_stage`) resolve os 2
arquivos intermediários e persiste via `write_report_atomic` (B29).

Referências: `audit/architecture_gaps_log.yaml::AG-362`;
`docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md` §13.9.3/
§13.12/§13.13."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, Literal

import structlog

from src.features import build as features_build
from src.models._paths import EXPERIMENTS_DIR
from src.models.pipeline import (
    ALL_RESOLUTIONS,
    ALL_SYMBOLS,
    run_layer1_sprint_all_combinations,
    write_report_atomic,
)

logger = structlog.get_logger(__name__)

Stage = Literal["off", "on", "base"]

#: `T1_FEATURE_IDS` pré-`AG-362` (`git show 891bb94:src/features/build.py`)
#: -- congelado aqui como valor LITERAL, não importado de
#: `features/build.py`, de propósito: o vetor "base" desta medição é uma
#: FOTOGRAFIA histórica, não deve mudar se `T1_FEATURE_IDS` mudar de novo
#: no futuro.
ORIGINAL_T1_FEATURE_IDS: Final[tuple[str, ...]] = (
    "A05_ret_vol_norm_4",
    "A13_dist_ema48_atr",
    "B01_rsi_14",
    "E27f_cost_atr_ratio",
    "C06_vol_ratio_12_96",
    "D06f_taker_imbalance_z_48",
    "E10f_oi_change_z_48",
)

STAGE_OFF_FILENAME: Final[str] = "ag362_incremental_value_stage_off.json"
STAGE_ON_FILENAME: Final[str] = "ag362_incremental_value_stage_on.json"
STAGE_BASE_FILENAME: Final[str] = "ag362_incremental_value_stage_base.json"
FINAL_REPORT_FILENAME: Final[str] = "ag362_incremental_value_report.json"


class Ag362IncrementalValueError(RuntimeError):
    """Levantado quando o estágio `base` roda sem os 2 arquivos de `off`/`on`."""


def summarize_combinations(
    reports: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Núcleo puro -- agrega as N combinações de UMA rodada pelos campos
    que `run_layer1_sprint` já pré-registra em `layer1_vs_layer0`, não
    inventa métrica nova.

    AG-367 -- `delta_sharpe_mean` pode ser `NaN` (medido: 5/15 combinações
    de `stage=off`, todas com `n_paths_camada1_supera_camada0=0`, Sharpe
    indefinido em algum caminho). Soma ingênua propaga `NaN` pra TODO o
    agregado (`nan + x == nan`), e `write_report_atomic`/`orjson`
    serializa `NaN` como `null` -- o agregado inteiro vira `None` no
    disco, silenciosamente. Mesma disciplina de `_mean_finite` (`src/
    models/pipeline.py`, já usada pra este exato problema alhures): filtra
    não-finitos ANTES de agregar, e REPORTA quantos foram descartados (não
    esconde -- CLAUDE.md 'nunca silencie sem achar a causa raiz')."""
    n_permanence_pass = 0
    delta_sharpe_finite: list[float] = []
    n_delta_sharpe_non_finite = 0
    per_combo: dict[str, dict[str, Any]] = {}
    for (symbol, resolution_id), report in reports.items():
        block = report["layer1_vs_layer0"]
        permanence_pass = bool(block["permanence_pass"])
        delta_sharpe = float(block["delta_sharpe_mean"])
        if permanence_pass:
            n_permanence_pass += 1
        if math.isfinite(delta_sharpe):
            delta_sharpe_finite.append(delta_sharpe)
        else:
            n_delta_sharpe_non_finite += 1
        per_combo[f"{symbol}_{resolution_id}"] = {
            "permanence_pass": permanence_pass,
            "n_paths_camada1_supera_camada0": block["n_paths_camada1_supera_camada0"],
            "n_paths_total": block["n_paths_total"],
            "delta_sharpe_mean": delta_sharpe if math.isfinite(delta_sharpe) else None,
            "economic_gate": report.get("economic_gate"),
        }
    return {
        "n_combinations": len(reports),
        "n_permanence_pass": n_permanence_pass,
        "n_delta_sharpe_non_finite": n_delta_sharpe_non_finite,
        "delta_sharpe_mean_sum": sum(delta_sharpe_finite) if delta_sharpe_finite else 0.0,
        "delta_sharpe_mean_avg": (
            sum(delta_sharpe_finite) / len(delta_sharpe_finite) if delta_sharpe_finite else 0.0
        ),
        "per_combo": per_combo,
    }


def pick_better_hyperparam_config(
    summary_off: Mapping[str, Any], summary_on: Mapping[str, Any]
) -> tuple[str, str]:
    """Núcleo puro -- decide 'off'/'on' pela definição operacional
    declarada na docstring do módulo: 1) maior `n_permanence_pass`; 2)
    empate (diferença == 0) desempata por `delta_sharpe_mean_sum` maior.
    Retorna `(vencedor, motivo)`."""
    n_off = int(summary_off["n_permanence_pass"])
    n_on = int(summary_on["n_permanence_pass"])
    if n_off != n_on:
        winner = "off" if n_off > n_on else "on"
        return winner, f"n_permanence_pass: off={n_off} on={n_on}"
    sharpe_off = float(summary_off["delta_sharpe_mean_sum"])
    sharpe_on = float(summary_on["delta_sharpe_mean_sum"])
    winner = "off" if sharpe_off >= sharpe_on else "on"
    return winner, (
        f"empate em n_permanence_pass ({n_off}) -- desempate por "
        f"delta_sharpe_mean_sum: off={sharpe_off:.4f} on={sharpe_on:.4f}"
    )


def _run_full_vector_stage(
    *,
    use_hyperparams_by_combo: bool,
    vol_estimator_id: str,
    symbols: tuple[str, ...],
    resolutions: tuple[str, ...],
    dest_path: Any,
) -> dict[str, Any]:
    stage_name = "on" if use_hyperparams_by_combo else "off"
    t_start = time.monotonic()
    logger.info(
        "ag362_incremental_value.stage_start",
        stage=stage_name,
        config="22_features",
        use_hyperparams_by_combo=use_hyperparams_by_combo,
        n_combinations=len(symbols) * len(resolutions),
    )
    # AG-366 -- `feature_ids=None` (o default de `run_layer1_sprint_all_
    # combinations`) NÃO entra no `config_hash` do artefato de predições
    # (`src/io/artifact.py::compute_config_hash`, via `alpha_train_config_
    # extra` em `pipeline.py`) -- só entra quando explícito. Como o vetor
    # T1 GLOBAL mudou de composição (`AG-362`, 7->22) sem `feature_ids`
    # nunca ter sido passado explicitamente em nenhum caller de produção,
    # `feature_ids=None` aqui colidiria (`ArtifactExistsError`) com
    # QUALQUER artefato já persistido sob o T1 antigo (7) OU sob uma
    # tentativa anterior deste mesmo comando -- medido ao vivo (BTCUSDT/R1,
    # camada0, hash `4979fd69f0a404d2` já existia). Passar o vetor
    # explícito garante um `config_hash` que reflete de fato o que foi
    # treinado, distinto de qualquer rodada anterior sob outra composição.
    #
    # AG-368 -- mesmo com `feature_ids` explícito, `stage=on` pode colidir
    # com `stage=off` numa célula SEM calibração própria em `config/
    # alpha_hyperparams_by_combo.yaml` (5 das 15): `hyper` resolve pra
    # `None` de qualquer forma, então o `config_hash` fica idêntico ao de
    # `off` -- medido ao vivo (ETHUSDT/R1, hash `2237b15540119fd0`).
    # `scratch=True` é o mecanismo já existente de `write_artifact`
    # (ADR-001, "iteração exploratória") pra exatamente essa situação --
    # nenhuma das 3 rodadas deste módulo é o retreino canônico, então
    # nenhuma delas deve escrever no caminho imutável de produção.
    reports_raw = run_layer1_sprint_all_combinations(
        symbols=symbols,
        resolutions=resolutions,
        vol_estimator_id=vol_estimator_id,
        feature_ids=features_build.T1_FEATURE_IDS,
        use_hyperparams_by_combo=use_hyperparams_by_combo,
        scratch=True,
    )
    summary = summarize_combinations(reports_raw)
    elapsed_s = time.monotonic() - t_start
    payload = {
        "stage": stage_name,
        "config": "22_features",
        "feature_ids": list(features_build.T1_FEATURE_IDS),
        "feature_ids_n": len(features_build.T1_FEATURE_IDS),
        "use_hyperparams_by_combo": use_hyperparams_by_combo,
        "vol_estimator_id": vol_estimator_id,
        "elapsed_seconds": elapsed_s,
        "summary": summary,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    write_report_atomic(payload, dest_path=dest_path)
    logger.info(
        "ag362_incremental_value.stage_done",
        stage=stage_name,
        n_permanence_pass=summary["n_permanence_pass"],
        n_combinations=summary["n_combinations"],
        elapsed_seconds=elapsed_s,
    )
    return payload


def run_stage(
    stage: Stage,
    *,
    vol_estimator_id: str = "parkinson_w20",
    symbols: tuple[str, ...] = ALL_SYMBOLS,
    resolutions: tuple[str, ...] = ALL_RESOLUTIONS,
) -> dict[str, Any]:
    """Casca -- roda UM dos 3 estágios (D-13, `run_layer1_sprint_all_
    combinations`) e persiste. `stage="base"` exige que `off`/`on` já
    tenham sido persistidos (lê do disco, não recomputa) e também
    escreve o relatório final consolidado (`FINAL_REPORT_FILENAME`)."""
    if stage in ("off", "on"):
        stage_filename = STAGE_ON_FILENAME if stage == "on" else STAGE_OFF_FILENAME
        return _run_full_vector_stage(
            use_hyperparams_by_combo=(stage == "on"),
            vol_estimator_id=vol_estimator_id,
            symbols=symbols,
            resolutions=resolutions,
            dest_path=EXPERIMENTS_DIR / stage_filename,
        )

    off_path = EXPERIMENTS_DIR / STAGE_OFF_FILENAME
    on_path = EXPERIMENTS_DIR / STAGE_ON_FILENAME
    if not off_path.exists() or not on_path.exists():
        raise Ag362IncrementalValueError(
            f"stage='base' exige {off_path.name} e {on_path.name} já persistidos -- "
            "rode 'off' e 'on' primeiro."
        )
    import json

    payload_off = json.loads(off_path.read_text(encoding="utf-8"))
    payload_on = json.loads(on_path.read_text(encoding="utf-8"))
    winner, winner_reason = pick_better_hyperparam_config(
        payload_off["summary"], payload_on["summary"]
    )
    winner_use_hyperparams_by_combo = winner == "on"

    t_start = time.monotonic()
    logger.info(
        "ag362_incremental_value.stage_start",
        stage="base",
        config="7_features_base",
        use_hyperparams_by_combo=winner_use_hyperparams_by_combo,
        winner_source=winner,
        winner_reason=winner_reason,
        n_combinations=len(symbols) * len(resolutions),
    )
    reports_base = run_layer1_sprint_all_combinations(
        symbols=symbols,
        resolutions=resolutions,
        vol_estimator_id=vol_estimator_id,
        feature_ids=ORIGINAL_T1_FEATURE_IDS,
        use_hyperparams_by_combo=winner_use_hyperparams_by_combo,
        scratch=True,  # AG-368 -- mesma razão dos 2 estágios anteriores
    )
    summary_base = summarize_combinations(reports_base)
    elapsed_s = time.monotonic() - t_start
    payload_base = {
        "stage": "base",
        "config": "7_features_base",
        "feature_ids": list(ORIGINAL_T1_FEATURE_IDS),
        "feature_ids_n": len(ORIGINAL_T1_FEATURE_IDS),
        "use_hyperparams_by_combo": winner_use_hyperparams_by_combo,
        "vol_estimator_id": vol_estimator_id,
        "elapsed_seconds": elapsed_s,
        "summary": summary_base,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    write_report_atomic(payload_base, dest_path=EXPERIMENTS_DIR / STAGE_BASE_FILENAME)
    logger.info(
        "ag362_incremental_value.stage_done",
        stage="base",
        n_permanence_pass=summary_base["n_permanence_pass"],
        n_combinations=summary_base["n_combinations"],
        elapsed_seconds=elapsed_s,
    )

    final_payload = {
        "task": "ag362_incremental_value_report",
        "pergunta": (
            "As 15 features L3->T1 promovidas por AG-362 fazem o Alpha ganhar "
            "algo real, medido sob CPCV purgado (não gain/AUC bruto, ver "
            "ADR-005 §13.13)?"
        ),
        "adr_ref": (
            "audit/architecture_gaps_log.yaml::AG-362; "
            "docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md "
            "§13.9.3/§13.12/§13.13"
        ),
        "vol_estimator_id": vol_estimator_id,
        "n_symbols": len(symbols),
        "n_resolutions": len(resolutions),
        "n_combinations_per_rodada": len(symbols) * len(resolutions),
        "definicao_operacional_vencedor_hiperparametro": (
            "1) maior contagem de permanence_pass=True entre as 15 "
            "combinações; 2) empate (diferença==0) desempata por soma de "
            "delta_sharpe_mean maior"
        ),
        "rodadas": {
            "22_features_hyperparam_off": payload_off,
            "22_features_hyperparam_on": payload_on,
            f"7_features_base_hyperparam_{winner}": payload_base,
        },
        "vencedor_hiperparametro_1_vs_2": {"winner": winner, "reason": winner_reason},
        "n_lifetime_nota": (
            "run_layer1_sprint_all_combinations documenta que quantos trials "
            "estas rodadas valem em audit/n_lifetime.yaml é leitura em aberto, "
            "decisão do Manager -- não logado automaticamente aqui. 3 desenhos "
            "fixos testados contra dado real (45 fits totais: 3 rodadas x 15 "
            "combinações), número exato pra essa decisão."
        ),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    write_report_atomic(final_payload, dest_path=EXPERIMENTS_DIR / FINAL_REPORT_FILENAME)
    logger.info(
        "ag362_incremental_value.done",
        report_path=str(EXPERIMENTS_DIR / FINAL_REPORT_FILENAME),
    )
    return final_payload


if __name__ == "__main__":  # pragma: no cover -- execução manual
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="AG-362 -- mede valor incremental das 15 features promovidas, 3 estágios."
    )
    parser.add_argument("--stage", required=True, choices=["off", "on", "base"])
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    args = parser.parse_args()
    run_stage(args.stage, vol_estimator_id=args.vol_estimator_id)
    sys.exit(0)
