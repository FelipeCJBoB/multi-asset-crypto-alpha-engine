"""AG-221/AG-227 — tabela ANTES x DEPOIS do relabel (`entry_fill_source`
de `mark_1m` para `agg_trades`), pedida pelo Manager em 2026-08-25.

**Medição PÓS-HOC**, sem retreino e sem reprocessar label nenhum: compara
dois snapshots de `labels.parquet` já materializados.

- **ANTES**: `data/labels_pre_ag221_relabel/` — cópia integral tirada
  imediatamente antes do relabel de produção.
- **DEPOIS**: `data/labels/` — o estado corrente.

**Por que um snapshot em diretório, e não o `config_hash`.** O `config_hash`
distingue os regimes (é para isso que `entry_fill_source` entrou nele), mas
não permite RECUPERAR o valor antigo depois que o arquivo foi sobrescrito.
`write_labels_atomic` substitui o parquet no lugar. Sem a cópia prévia, o
lado ANTES da tabela simplesmente não existiria — e é a mesma lição de
`AG-226`/`AG-218`: identidade de regime precisa de marcação externa quando
o artefato é sobrescrito, não só de um campo dentro dele.

O par (`config_hash` antes, `config_hash` depois) vai na saída justamente
para provar que os dois lados são de regimes diferentes — se vierem iguais,
o relabel não aconteceu e a tabela é uma comparação vazia."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

ANTES_DIR = Path("data/labels_pre_ag221_relabel")
DEPOIS_DIR = Path("data/labels")

# Conversão fração -> basis points. Não é constante de domínio.
_BPS = 10_000


@dataclass(frozen=True, slots=True)
class ComboComparison:
    combo: str
    config_hash_antes: str
    config_hash_depois: str
    regime_mudou: bool
    n_antes: int
    n_depois: int
    p_tp_antes: float
    p_tp_depois: float
    delta_p_tp: float
    pct_nofill_antes: float
    pct_nofill_depois: float
    delta_pct_nofill: float
    ret_gross_bps_antes: float
    ret_gross_bps_depois: float
    delta_ret_gross_bps: float
    ret_net_bps_antes: float
    ret_net_bps_depois: float
    delta_ret_net_bps: float


def _resumo(path: Path) -> dict[str, float | int | str] | None:
    if not path.exists():
        return None
    d = pl.read_parquet(
        path, columns=["barrier_hit", "config_hash", "ret_gross", "ret_net"]
    )
    if d.is_empty():
        return None
    f = d.filter(pl.col("barrier_hit") != "NOFILL")
    # `.to_numpy()` antes de `float(...)` -- mesmo motivo de
    # `labels.weights.apply_weights` e `triple_barrier.assert_label_
    # invariants`: o retorno agregado de `pl.Series.mean()` e um union
    # amplo nos stubs do polars, que `mypy --strict` recusa.
    return {
        "n": d.height,
        "config_hash": str(d["config_hash"][0]),
        "p_tp": float(np.mean((f["barrier_hit"] == "TP").to_numpy())) if f.height else float("nan"),
        "pct_nofill": float(np.mean((d["barrier_hit"] == "NOFILL").to_numpy())),
        "ret_gross_bps": float(np.mean(f["ret_gross"].to_numpy())) * _BPS
        if f.height
        else float("nan"),
        "ret_net_bps": float(np.mean(f["ret_net"].to_numpy())) * _BPS
        if f.height
        else float("nan"),
    }


def compare_all(
    *, antes_dir: Path = ANTES_DIR, depois_dir: Path = DEPOIS_DIR
) -> list[ComboComparison]:
    """Uma linha por combinação `{symbol}/{grade}` presente nos DOIS lados.

    Combinações só de um lado são puladas com aviso — nunca comparadas
    contra zero, que produziria um delta inventado."""
    out: list[ComboComparison] = []
    for p_antes in sorted(antes_dir.rglob("labels.parquet")):
        combo = "/".join(p_antes.parts[-4:-2])  # {symbol}/{grade}
        rel = p_antes.relative_to(antes_dir)
        p_depois = depois_dir / rel

        a, b = _resumo(p_antes), _resumo(p_depois)
        if a is None or b is None:
            logger.warning(
                "analysis.ag221.combo_incompleta",
                combo=combo,
                tem_antes=a is not None,
                tem_depois=b is not None,
            )
            continue

        out.append(
            ComboComparison(
                combo=combo,
                config_hash_antes=str(a["config_hash"]),
                config_hash_depois=str(b["config_hash"]),
                regime_mudou=a["config_hash"] != b["config_hash"],
                n_antes=int(a["n"]),
                n_depois=int(b["n"]),
                p_tp_antes=float(a["p_tp"]),
                p_tp_depois=float(b["p_tp"]),
                delta_p_tp=float(b["p_tp"]) - float(a["p_tp"]),
                pct_nofill_antes=float(a["pct_nofill"]),
                pct_nofill_depois=float(b["pct_nofill"]),
                delta_pct_nofill=float(b["pct_nofill"]) - float(a["pct_nofill"]),
                ret_gross_bps_antes=float(a["ret_gross_bps"]),
                ret_gross_bps_depois=float(b["ret_gross_bps"]),
                delta_ret_gross_bps=float(b["ret_gross_bps"]) - float(a["ret_gross_bps"]),
                ret_net_bps_antes=float(a["ret_net_bps"]),
                ret_net_bps_depois=float(b["ret_net_bps"]),
                delta_ret_net_bps=float(b["ret_net_bps"]) - float(a["ret_net_bps"]),
            )
        )
    return out


def render_markdown(rows: list[ComboComparison]) -> str:
    """Tabela pronta para o relatório do Manager."""
    linhas = [
        "| combo | regime | P(TP) antes → depois | Δ | NOFILL antes → depois | "
        "ret_gross antes → depois | Δ bps |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        marca = "trocado" if r.regime_mudou else "**IGUAL**"
        linhas.append(
            f"| {r.combo} | {marca} | {r.p_tp_antes:.4f} → {r.p_tp_depois:.4f} | "
            f"{r.delta_p_tp:+.4f} | {r.pct_nofill_antes:.2%} → {r.pct_nofill_depois:.2%} | "
            f"{r.ret_gross_bps_antes:+.2f} → {r.ret_gross_bps_depois:+.2f} | "
            f"{r.delta_ret_gross_bps:+.2f} |"
        )
    return "\n".join(linhas)


if __name__ == "__main__":  # pragma: no cover — execução manual
    import sys

    def _run() -> int:
        rows = compare_all()
        dest = Path("experiments") / "ag221_relabel_antes_depois.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps([asdict(r) for r in rows], indent=2), encoding="utf-8"
        )
        md = Path("experiments") / "ag221_relabel_antes_depois.md"
        md.write_text(render_markdown(rows), encoding="utf-8")
        n_trocados = sum(1 for r in rows if r.regime_mudou)
        logger.info(
            "analysis.ag221.relabel_comparison_done",
            n_combos=len(rows),
            n_regime_trocado=n_trocados,
            n_regime_igual=len(rows) - n_trocados,
            json_path=str(dest),
            markdown_path=str(md),
        )
        return 0

    sys.exit(_run())
