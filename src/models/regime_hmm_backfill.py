"""Backfill do artefato de regime HMM canônico (`hmm_gaussian_k4_v1`).

Orquestrador fino: descobre a janela `[start, end]` EXATAMENTE como
`dataset.build_modeling_frame` a descobre, e delega a construção para
`src.regime.artifact_hmm`.

**Por que mora em `models/` e não em `regime/`.** Derivar a janela exige
ler `labels`, e o contrato de camada (`pyproject.toml`, "labels só é lido
por models, validation, backtest") proíbe `regime` de alcançar `labels` —
inclusive transitivamente via `src.validation.cpcv`. `models` tem
permissão para os dois lados, então é aqui que produtor e insumo se
encontram. O módulo de artefato em `regime/` fica puro: recebe a janela
pronta.

**A janela precisa bater byte a byte com a de `build_modeling_frame`**,
senão o `config_hash` diverge e o leitor não acha o artefato que este
comando acabou de escrever. Por isso este módulo não recalcula a janela
por conta própria: chama a MESMA `date_bounds` sobre os MESMOS labels,
carregados com os mesmos parâmetros.

Uso:

    uv run python -m src.models.regime_hmm_backfill --symbol BTCUSDT --resolution-id R1
    uv run python -m src.models.regime_hmm_backfill --all --resolution-id R1
"""

from __future__ import annotations

import argparse

import structlog

from src.regime import artifact_hmm
from src.validation import cpcv

from .dataset import date_bounds

logger = structlog.get_logger(__name__)

#: Universo de produção (§15 do Plano Mestre). Não é constante de domínio
#: (nenhuma decisão econômica depende dela) — é a lista de trabalho do
#: backfill, mesma categoria do universo já repetido em `tests/`.
SYMBOLS_DEFAULT: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
)


def backfill_one(
    symbol: str,
    *,
    resolution_id: str,
    vol_estimator_id: str = "parkinson_w20",
    seed: int = 0,
    scratch: bool = False,
) -> str:
    """Constrói e persiste o artefato de UM `(symbol, resolution_id)`.
    Devolve o `config_hash` escrito."""
    labels = cpcv.load_labels_v1(
        symbol=symbol,
        resolution_id=resolution_id,
        vol_estimator_id=vol_estimator_id,
    )
    start, end = date_bounds(labels)
    manifest = artifact_hmm.build_and_write_regime_hmm(
        symbol,
        start,
        end,
        resolution_id=resolution_id,
        seed=seed,
        scratch=scratch,
    )
    logger.info(
        "models.regime_hmm_backfill.done",
        symbol=symbol,
        resolution_id=resolution_id,
        config_hash=manifest.config_hash,
        n_rows=manifest.n_rows,
        start=start,
        end=end,
    )
    return manifest.config_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--symbol", help="um símbolo específico")
    grupo.add_argument(
        "--all", action="store_true", help=f"todos de {SYMBOLS_DEFAULT}"
    )
    parser.add_argument("--resolution-id", required=True)
    parser.add_argument("--vol-estimator-id", default="parkinson_w20")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scratch", action="store_true")
    args = parser.parse_args(argv)

    symbols = SYMBOLS_DEFAULT if args.all else (args.symbol,)
    falhas: list[tuple[str, str]] = []
    for symbol in symbols:
        try:
            backfill_one(
                symbol,
                resolution_id=args.resolution_id,
                vol_estimator_id=args.vol_estimator_id,
                seed=args.seed,
                scratch=args.scratch,
            )
        except Exception as exc:  # o laço reporta e segue, ver comentário abaixo
            # Um símbolo que falha NÃO aborta os outros: o refit é caro
            # (>15min cada) e perder 4 backfills bons por causa de 1 ruim
            # seria pior. Mas a falha é reportada e o exit code reflete —
            # nunca "terminou OK" com um símbolo faltando em silêncio.
            falhas.append((symbol, f"{type(exc).__name__}: {exc}"))
            logger.error(
                "models.regime_hmm_backfill.falhou",
                symbol=symbol,
                resolution_id=args.resolution_id,
                erro=str(exc),
                tipo=type(exc).__name__,
            )
    if falhas:
        logger.error(
            "models.regime_hmm_backfill.resumo_com_falhas",
            n_ok=len(symbols) - len(falhas),
            n_falhas=len(falhas),
            falhas=falhas,
        )
        return 1
    logger.info(
        "models.regime_hmm_backfill.resumo",
        n_ok=len(symbols),
        resolution_id=args.resolution_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
