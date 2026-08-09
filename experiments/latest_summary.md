# Resumo — Alpha Camada 1 (Sprint 8, BTCUSDT)

_Gerado em 2026-08-09T14:14:21.548948+00:00 — commit `857d49c`._

Fonte: `experiments/alpha_layer1_report.json` (schema_version 1). Este arquivo é DERIVADO — não edite à mão, rode `uv run python -m src.analysis.summary`.

## PnL (pooled, 36538 trades, 15 splits)

| componente | bps/trade |
|---|---|
| Total | -2.82 bps/trade |
| Direcional | +2.16 bps/trade |
| Carry | +0.78 bps/trade |
| Execução (custo) | -5.76 bps/trade |

## Sharpe (pooled)

- Total: -1.138
- Direcional: +0.879
- `carry_share` (gate3): não computável (denominador -10.30431849118708 <= 0 (ou não-finito))

## Concentração de features (HHI)

- Nominal médio: 0.1096 (< 0,25 OK)
- Efetivo médio (corrigido por correlação, Fase D): 0.1911
- Maior share médio: 0.1679 (< 0,30 OK)

## Baseline aleatório (B1)

- Alpha no percentil 100.0 de 1000 sorteios (amostra 7308 trades)

## Permanência (Camada 1 vs Camada 0)

- 5 de 5 caminhos (mínimo exigido: 4) — PASSA
