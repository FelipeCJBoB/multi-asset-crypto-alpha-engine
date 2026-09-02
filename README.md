# Multi-Asset Crypto Alpha Engine

Motor de pesquisa de alpha para futuros perpétuos cripto (Binance USDⓈ-M) —
multi-ativo (BTC/ETH/SOL/BNB/XRP), bidirecional (long/short), barras de
**dólar** (event-driven, não relógio), validação por **CPCV purgado**,
classificadores LightGBM sob restrição monotônica, calibração isotônica,
busca de hiperparâmetro via Optuna, e uma camada de **governança de
proveniência** que obriga toda constante numérica do pipeline a declarar
de onde veio antes de poder ser usada.

Projeto de pesquisa individual (não produto, não fundo, não sinal à venda).
Existe pra construir — e documentar honestamente — a infraestrutura
hipótese → feature → label → validação → modelo → auditoria de um motor
quant real, não pra provar que cripto é previsível.

## Por que este repositório é diferente de um "bot de trading" no GitHub

A maioria dos projetos públicos de ML aplicado a trading mostra uma curva
de equity subindo e para por aí. Este repositório mostra o oposto por
design: **cada resultado, incluindo os negativos, é medido, registrado e
rastreável até o commit e o experimento que o gerou.**

- **439 entradas em `audit/architecture_gaps_log.yaml`** — todo furo de
  arquitetura encontrado (por mim ou por auditoria externa) fica registrado
  com achado, severidade, resolução e commit — nunca corrigido em silêncio.
- **208 entradas em `audit/evidence_ledger.yaml`** — todo achado
  estatístico medido (edge, Sharpe, IC, gates) com proveniência.
- **`audit/n_lifetime.yaml`** rastreia o orçamento de múltiplos testes
  (`N_lifetime`, usado no cálculo de Deflated Sharpe Ratio) — nunca
  decrementa, mesmo entre sessões, pra que o DSR final não seja inflado por
  amnésia de quantas buscas já foram tentadas.
- **Veredito atual, honesto**: os 5 candidatos mais promissores do motor
  (`ADR-007`/`ADR-008`, walk-forward real fora-da-amostra) passam **0 de 20**
  combinações símbolo×camada×lado nos 3 gates de produção — mesmo depois de
  corrigir um bug de seed compartilhado (`AG-399`) e promover o
  hiperparâmetro re-medido (`AG-420`). Isso não é o projeto "não
  funcionando" — é o gate fazendo exatamente o que existe pra fazer: barrar
  a promoção de um modelo sem edge estatisticamente defensável, em vez de
  reportar um Sharpe otimista de um teste que não sobreviveria a dado novo.

Se o objetivo fosse parecer bem-sucedido, esse veredito não estaria aqui.

## Capital como restrição de design, não parâmetro livre

O motor trata capital como constraint física do desenho (`R$ 1.000` de
referência) — não um número decorativo: ele determina granularidade mínima
de lote, orçamento de trades/mês, e se uma combinação de barreiras TP/SL é
sequer viável para os 5 símbolos simultaneamente (`AG-204`). **É um
parâmetro de design usado consistentemente em todo o dimensionamento do
projeto, não o saldo ao vivo de uma conta hoje.** A decisão de tratar
capital pequeno como restrição de primeira classe (em vez de assumir
capital ilimitado, como a maioria dos backtests acadêmicos faz) é, em si,
um dos achados de engenharia do projeto — ver `PLANO_MESTRE_PRINCE2.md` §0.

## Pipeline

```
ingestão (REST/WS assinado, rate limit, filtros versionados por data)
  → Data Quality Engine (dedupe, gap detection, timestamp monotonicity)
  → construção de barra de dólar (event-driven, não clock-time)
  → Feature Engine (30 features T1 ativas, registry com tese econômica
    declarada + prova de causalidade + teste de paridade lote/streaming)
  → classificação de regime de mercado (HMM canonicalizado por fold,
    Jump Model, histerese contra flapping)
  → Label Engine (triple-barrier em mark price 1m, pesos por unicidade,
    custo de execução e funding modelados por trade)
  → CPCV purgado (Combinatorial Purged Cross-Validation, testes de
    vazamento próprios) + orçamento de múltiplos testes (N_lifetime)
  → Alpha: LightGBM binário por lado (long/short), monotone_constraints,
    calibração isotônica, busca de hiperparâmetro via Optuna
  → walk-forward fora-da-amostra vs. baselines nulos, DSR/PSR
  → Risk Engine (sizing, 18 controles pré-trade, kill switch)
  → simulação de fill maker-only + reconciliação backtest-vs-execução
```

## O que este projeto demonstra tecnicamente

- **Metodologia de validação anti-overfitting real**: CPCV purgado (não
  k-fold ingênuo, que vaza informação temporal), embargo entre splits,
  gates de permanência estatística com correção de Benjamini-Hochberg para
  teste múltiplo, Deflated Sharpe Ratio contra o orçamento real de trials
  já gastos — não contra `N=1` da busca isolada.
- **Governança de proveniência aplicada a código, não só a documento**:
  `tools/lint/check_constants_provenance.py`/`check_unguarded_ratios.py`
  rodam em CI e bloqueiam merge se uma constante classe A (a que invalida o
  desenho se estiver errada) não tiver origem declarada — medido, derivado,
  literatura ou assumido, cada um com tratamento e limiar diferentes.
- **Engenharia de feature com tese, não só correlação**: cada feature em
  `src/features/registry.yaml` declara mecanismo econômico ("quem está do
  outro lado"), prova de causalidade testada, e passa por uma sequência de
  5 gates (auditoria algébrica → mecanismo → alinhamento de horizonte →
  redundância → valor incremental walk-forward) **antes** de qualquer
  leitura de importância de modelo (SHAP/gain) — decisão deliberada para
  evitar o mesmo erro estrutural que motivou abandonar um gate de correlação
  marginal anterior (`AG-362`).
  ([exemplo completo de auditoria de decisão registrada nesta sessão, incluindo override explícito sobre a própria regra do projeto: `AG-421`](audit/architecture_gaps_log.yaml))
- **Auditoria adversarial real, não cosmética**: múltiplas rodadas de
  auditoria externa (`docs/AUDITORIA_EXTERNA_*.md`,
  `docs/brief_auditoria_externa_*.md`) confrontaram o desenho do motor —
  achados aceitos quando o código confirma, refutados com evidência quando
  não confirma (ex. `docs/m4_regime_auditoria_externa_2026-08-19_validacao_cruzada.md`,
  que cruza duas auditorias externas divergentes contra leitura direta de
  código e literatura acadêmica).

## Estrutura

```
src/
├── exchange/     REST/WS assinado, rate limit, filtros versionados por data
├── data/         Data Quality Engine, resample causal, DuckDB
├── features/     Feature Engine — registry com tese declarada, paridade lote/streaming
├── regime/       Classificação de regime (HMM, Jump Model), histerese
├── labels/       Triple-barrier em mark price, pesos por unicidade
├── validation/   CPCV com purge/embargo, testes de vazamento, FDR
├── models/       Alpha (LightGBM), busca Optuna, walk-forward, meta-labeling
├── risk/         Sizing, 18 controles pré-trade, kill switch
├── execution/    Simulador de fill maker-only
├── backtest/     Reconciliação backtest-vs-execução real
├── analysis/     Medição pós-hoc (nunca insumo de treino) — atribuição, concordância, decomposição
└── core/         Tipos compartilhados (ex. `Metric`, com unidade/n/proveniência sempre explícitos)

audit/      Log de furos de arquitetura, ledger de achados estatísticos, orçamento de trials
config/     Constantes com proveniência declarada (measured/derived/literature/assumed)
docs/       ADRs numerados, sprint log, auditorias externas, design docs
scripts/    Campanhas de retreino/busca/análise, executadas sob autorização explícita
tests/      pytest — 2.983 testes coletados (unit + property + golden + integration)
tools/lint/ Verificadores mecânicos de governança (proveniência, padrões banidos, contratos de import)
```

Hierarquia de import verificada estaticamente (`import-linter`,
`pyproject.toml`) — `features/` não importa `labels/`, `models/` não
importa `execution/`, entre outras regras documentadas em `CLAUDE.md`.

## Stack

Python 3.12+ · `uv` · Polars (lazy, Arrow) · DuckDB · Parquet+zstd ·
LightGBM · scikit-learn (calibração isotônica) · Optuna · SHAP ·
structlog+orjson · Pydantic+YAML · pytest+hypothesis · ruff · mypy strict

## Rodando localmente

```bash
uv sync --all-groups
uv run pytest -m "not slow and not integration"   # ciclo rápido
uv run ruff check .
uv run mypy src   # strict=true já configurado em pyproject.toml
uv run python tools/lint/banned_patterns.py --path src --strict
uv run python tools/lint/check_constants_provenance.py
```

Dados de mercado não são versionados (`data/*` no `.gitignore`) —
reconstruíveis por download determinístico da API pública da Binance. Ver
`CLAUDE.md` para a rotina completa de bootstrap e as regras de governança
que todo código deste repositório segue.

## Onde ler mais

| Documento | Conteúdo |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Regras de engenharia do projeto — proveniência, banned patterns, rotina de git, diretrizes de comportamento |
| [`PLANO_MESTRE_PRINCE2.md`](PLANO_MESTRE_PRINCE2.md) | Governança, decisões, roadmap — documento canônico |
| [`docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md`](docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md) | Arquitetura de artefatos e contratos (canônico) |
| [`docs/SPRINT_LOG.md`](docs/SPRINT_LOG.md) | Estado atual, sprint a sprint, com números reais |
| [`audit/architecture_gaps_log.yaml`](audit/architecture_gaps_log.yaml) | Todo furo de arquitetura encontrado e como foi resolvido |

---

Projeto individual, código aberto para fins de portfólio técnico. Não é
recomendação de investimento, produto financeiro, nem sinal de trading.
