# BTCUSDT Quant Engine

Motor quantitativo local para **BTCUSDT perpétuo na Binance USDⓈ-M**, decisão a
15 minutos, execução maker post-only, capital de **US$ 196,85**.

A V1 não existe pra provar que BTCUSDT pode ser previsto — existe pra construir a
infraestrutura em que uma hipótese quantitativa possa ser formulada, testada,
invalidada ou aprovada, simulada, monitorada, executada e auditada, com o
capital tratado como restrição física do desenho, não como parâmetro livre.

## Status

**Sprint 8 (rodada 1) de 18 concluído + fatia adiantada do Sprint 10** —
Sprints 1-9 e 12 feitos (12 adiantado) · 552 testes passando · 0 violações de
lint.

⚠️ **O que sabemos agora sobre se existe edge:** o Alpha (Camada 1, restrições
monotônicas) passa o critério arquitetural do PRD, mas **não tem edge
operável ainda** — Sharpe negativo, e um simples buy-and-hold (+0,54) vence os
dois. A decomposição de PnL mostra por quê: **direção e carry somados são
positivos (+3,67)** — o custo de execução, sozinho (-17,71), é o que vira o
resultado negativo. Uma auditoria externa do plano revisou este resultado e
levantou 4 pontos (orçamento de fees, seletividade do fill, robustez do
baseline aleatório, teto de features) — todos verificados contra código e
dado real, não aceitos por plausibilidade (`docs/SPRINT_LOG.md`, seção
"Auditoria externa"). Achados: o baseline aleatório (B1) resiste a uma
comparação mais rigorosa (Alpha no percentil 100 de 1.000 sorteios, 4 dos 5
caminhos); o fill rate baixo **não** esconde os trades vencedores (gap de
seletividade pequeno, -1,72pp); e, na única janela onde dá pra medir fill
real (bookTicker, ~10,5 meses de 6,5 anos), trocar a suposição otimista pelo
fill real do Sprint 9 deixa o Sharpe **menos** negativo, não mais — mas essa
janela específica não é representativa do regime médio do modelo, então a
economia honesta sobre os 6,5 anos completos **continua em aberto**. Detalhes
completos em `docs/SPRINT_LOG.md`.

| Documento | O que é |
|---|---|
| [`PRD_V3_2_UNIFICADO.md`](PRD_V3_2_UNIFICADO.md) | Blueprint técnico completo (v3.3) — a especificação de tudo |
| [`CLAUDE.md`](CLAUDE.md) | Regras operacionais do repo — proveniência de constantes, banned patterns, rotina de git |
| [`docs/SPRINT_LOG.md`](docs/SPRINT_LOG.md) | **Comece aqui pra entender o progresso** — o que foi construído e medido em cada sprint, com os números reais |

## As cinco restrições que definem o desenho

O capital de US$ 196,85 não é um parâmetro — é a restrição estrutural. Lote
mínimo de 0,001 BTC = US$ 64,94 = 33% do equity. Tudo no motor decorre disso:
janela de stop viável entre 0,275% e 0,758%, orçamento de ~55 trades/mês,
alavancagem tratada como liberação de margem, não como controle de risco.
Detalhes em `PRD_V3_2_UNIFICADO.md` §0.

## O que já está medido (não presumido)

- **Distribuição real de desfecho de trade** (462 mil labels, 6,5 anos): TP
  36,5% · SL 51,3% · TIME 6,5% · NOFILL 5,7% — substitui números que o próprio
  PRD documentava como fabricados.
- **Teto de features real**: ~32,4 mil observações efetivas por modelo — acima
  do que o blueprint original especulava.
- **CPCV sem vazamento**: purge testado contra os 462 mil labels reais — zero
  `t1` de treino cruzando pro teste, em 15 de 15 splits.
- **Fill rate maker real**: 37,3% (ver alerta acima) · seleção adversa real
  ~0,6bps, menor que o placeholder assumido de 1,5bps.
- **Distribuição real de regime de mercado**: 97,5% do tempo é tradeable; regime
  de stress (R5) é raro (1,7%).
- **Cobertura real de dado**: a Binance só publica dumps públicos desde
  ~2019-12, não desde 2019-09 como presumido; alguns dumps (bookTicker) têm
  janela de disponibilidade muito mais estreita que o documentado.

Números completos e como cada um foi medido: [`docs/SPRINT_LOG.md`](docs/SPRINT_LOG.md).

## Estrutura

```
src/
├── exchange/     REST/WS assinados, rate limit, filtros versionados por data
├── data/         Data Quality Engine, resample causal, camada DuckDB
├── features/     Feature Engine — 10 features T1, registry, paridade lote/streaming
├── regime/       5 regimes por quantis, histerese, gatilhos de stress
├── labels/       Triple barrier em mark price, pesos por unicidade
├── validation/   CPCV com purge/embargo, 14 testes de vazamento
├── execution/    Simulador de fila (pré-RPI); máquina de estados    (parcial)
├── models/       Alpha Camada 1 + 5 baselines nulos                (Sprint 8, rodada 1)
├── risk/         Sizing, 18 controles, kill switch                 (Sprint 12)
└── backtest/     Reconciliação gate otimista vs fill real          (fatia do Sprint 10; engine completo ainda não)
```

Hierarquia de import verificada estaticamente (`import-linter`, config em
`pyproject.toml`) — `features/` não pode importar `labels/`, `models/` não pode
importar `execution/`, entre outras regras de `CLAUDE.md`.

## Rodando localmente

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy src
uv run python tools/lint/banned_patterns.py --path src --strict
```

## Proveniência de constantes

Nenhuma constante numérica entra em código de pipeline sem uma entrada em
`config/constants.yaml`, com origem declarada (medido / derivado / literatura /
assumido) e classe de risco. `tools/lint/check_constants_provenance.py` verifica
isso. É o mecanismo central que impede um número inventado se passar por
resultado medido — ver `CLAUDE.md` § "Regra zero: proveniência".
