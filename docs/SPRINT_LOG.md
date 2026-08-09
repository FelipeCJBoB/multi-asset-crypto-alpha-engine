# Sprint Log — BTCUSDT Quant Engine

> Registro narrativo, para humanos, do que foi construído e medido em cada sprint.
> Complementa o `git log` (que registra o *quê* e o *porquê* técnico) e o `CLAUDE.md`
> (que registra as *regras*). Aqui fica o *resultado* — os números que saíram de
> cada etapa, as decisões tomadas e os achados que mudaram alguma suposição do PRD.
>
> Atualizado a cada sprint concluído. Não é um resumo escrito depois — é atualizado
> na hora, com números conferidos contra o repo real antes de entrar aqui.

---

## Como ler este documento

Cada sprint tem: o que foi construído, o que foi **medido** (o que importa — este
projeto existe pra parar de aceitar números plausíveis sem checar), decisões
tomadas, e a tag/commit do GitHub onde aquele estado do repo pode ser visto.

Link do repositório: **[github.com/FelipeCJBoB/btcusdt-quant-engine](https://github.com/FelipeCJBoB/btcusdt-quant-engine)** (privado).

---

## Sprint 0 — Descoberta e limpeza (2026-08-08, antes do Sprint 1)

Antes de escrever qualquer código do PRD V3.2, o repo já tinha conteúdo de um
projeto anterior e distinto: um estudo de viabilidade sub-1h (`btc-sub1h-
feasibility`) que **aprovou T1** (razão custo/movimento, 18,3% no candidato de
15 minutos — é por isso que o PRD V3.2 escolheu 15m) mas deixou **T2 e T3
bloqueados** — desde 2025-11-20 existem ordens RPI (Retail Price Improvement) na
Binance, invisíveis à API pública, que contaminam qualquer medição de taxa de
preenchimento e seleção adversa feita sobre dado histórico.

**Decisão:** os artefatos de código daquele estudo (`src/bars/`, `src/data/`
antigos) foram excluídos — eram específicos de um problema mais estreito, não do
motor completo do PRD V3.2. Os dados brutos já baixados (`data/capacity/`, ~23GB)
foram **mantidos**, pois batiam com o catálogo de fontes do próprio PRD (§1.1).

**Achado que mudou o PRD:** a lacuna RPI não estava documentada em lugar nenhum do
blueprint de 3.328 linhas. Isso virou a v3.3 do PRD (ver abaixo).

---

## PRD → v3.3 — incorporação do fato RPI (2026-08-08)

10 edições aplicadas a `PRD_V3_2_UNIFICADO.md`, mais **11 inconsistências
adicionais** encontradas e corrigidas de tabelas que citavam o T1 antigo de 12
features (agora 10 — Grupo F, microestrutura, saiu por quebra de definição).

**Principais mudanças:**
- Nova fonte `F06 rpiDepth` (coleta forward, sem dump histórico possível).
- `T1` passa de 12 para **10 features** — `F02f_spread_pctile` e
  `F04f_book_imbalance_l1` saem por quebra de definição, não por desempenho.
- Simulador de fila (§9.5) explicitamente dividido em pré/pós-2025-11-20 — fills
  depois dessa data **não são simuláveis** a partir de dump público.
- Sensibilidade de seleção adversa medida: cada 1 bp custa 0,91pp de win rate
  exigido; margem confortável até 4,3bps; o Gate 0 rompe em 7,6bps.

---

## Sprints 1–3 — Infraestrutura (2026-08-08) · commit `162014a`

**Sprint 1 — scaffolding:** repositório git, `uv`+`pyproject.toml` (64 pacotes),
hierarquia de camadas verificada por `import-linter`, `config/constants.yaml` com
proveniência obrigatória, `tools/lint/banned_patterns.py` (12 dos 32 padrões do
CLAUDE.md automatizados), `structlog`+`orjson` com mascaramento automático de
segredo, `audit/n_lifetime.yaml` (ledger de trials), CI.

**Sprint 2 — ExchangeAdapter (`src/exchange/`):** cliente REST Binance USDⓈ-M com
assinatura HMAC correta (percent-encode antes de assinar — inverter a ordem
quebra com erro -1022), gerenciador de rate limit (orçamento de peso e de
contagem de ordens independentes, fila de prioridade), filtros de instrumento
versionados por data (`load_filters_asof`), ciclo de vida do `listenKey`
(keepalive/backoff/watchdog). 43 testes.

**Sprint 3 — Data Quality Engine (`src/data/`):** as verificações de qualidade do
PRD §1.3, resample causal (1m→5m/15m/30m/1h/2h/1d), camada DuckDB fina sobre o
lake. 74 testes.

**Achado real:** rodado contra 60 dias de `metrics` (Open Interest), o validador
encontrou **2 duplicatas e 1 gap genuínos** em `2026-06-12`/`2026-06-21` — dois
arquivos que quebram a convenção de fronteira que o resto da série segue. Não é
bug do validador. Fica registrado em `data/quality_reports/quality_report_
metrics_v1.json` (versionado no git — é evidência de auditoria, não dado bruto).

### Backfill de dados (paralelo aos Sprints 1-3)

**Achado principal:** o PRD assumia a série começando em 2020-01/2020-09. Medido
via listagem completa do S3 da Binance: **a publicação pública de dumps começa em
~2019-12-23/31**, não antes — o contrato foi lançado em 2019-09-08, mas a Binance
só passou a publicar dumps históricos ~3,5 meses depois. Não é falha de coleta —
é limite real do que existe.

**Resultado do backfill** (D01/D03/D04/D07/D10/D11 completos desde a origem real
até hoje; D05 completo desde 2023-06-20, único início real; D08/D09 bookTicker
baixado por completo mas só existe publicamente 2023-05-16→2024-03-30 — a Binance
aparentemente descontinuou esse dump depois disso):

| Fonte | Cobertura real |
|---|---|
| D01 aggTrades | 2019-12-31 → 2026-07-31 |
| D03 klines 1m | 2019-12-31 → 2026-08-07 |
| D04 metrics | 2020-09-01 → 2026-08-07 |
| D05 BVOLIndex | 2023-06-20 → 2026-08-07 |
| D07 funding | 2020-01 → 2026-07 |
| D10 markPriceKlines | 2019-12-23 → 2026-08-07 |
| D11 premiumIndexKlines | 2019-12-24 → 2026-08-07 |
| D08/D09 bookTicker | 2023-05-16 → 2024-03-30 (janela completa, única disponível) |

---

## Sprint 4 — Feature Engine (2026-08-08) · commit `b549bd9`, tag `sprint-4-done`

As 10 features T1 da v3.3 + `B07_efficiency_ratio_48` (insumo do Regime Engine).
Paridade lote↔streaming: **0,0 de desvio exato** (tolerância exigida era 1e-8).
206 testes.

**Achado — inconsistência de timeframe resolvida:** as tabelas de fórmula do PRD
(§2.2-2.6) diziam TF=30m pra quase toda feature, mas a decisão real do projeto é
15m desde a v3.1 (§0.4). Confirmado por leitura cruzada do documento inteiro —
era resíduo não atualizado. Todas as features implementadas a 15m.

**Achado — ortogonalidade real medida** (Spearman, ~68 mil barras, 2024-08→2026-08):
dois pares violam o limite de |ρ|≤0,70 do §2.13:
- `A13_dist_ema48_atr` × `B01_rsi_14` = **0,947**
- `E27f_cost_atr_ratio` × `C07_vol_pctile_expanding` = **-0,913**

Resolução exige importância por permutação de modelo treinado (Sprint 8) —
registrado, não escondido nem podado agora.

**Achado — qualidade de dado:** 31 pontos isolados de `sum_open_interest == 0.0`
no histórico (fisicamente impossível pra Open Interest) — teriam envenenado
`E10f` com `log(0)`. Mascarados para null na fonte.

---

## Sprints 5 e 6 — Regime Engine + Label Engine, em paralelo (2026-08-08)
### commits `53ef7a4` / `d023fd9` / `766036a`, tag `sprint-5-6-done`

**Sprint 5 — Regime Engine (`src/regime/`):** classificador R0-R5 por quantis
expansivos, histerese assimétrica (R5 entra imediato, sai só com 4 barras de
confirmação), eixo econômico por tercil de `cost_atr_ratio`. 43 testes.

**Achado — mapa de computabilidade dos 10 gatilhos de stress (S1-S10):** investigado
contra o dado real, não assumido:

| Computável hoje | Não computável (e por quê) |
|---|---|
| S1 vol extremo, S3 funding extremo, S6 gap de barra | S2 spread (Grupo F fora de T1), S4 basis (falta índice de preço, nunca baixado), S5/S8/S9 (sinais só-ao-vivo ou fonte nunca coletada), S7 liquidez (book_depth existe mas em buckets errados), S10 filtro mudou (só 1 snapshot no disco) |

Cada gatilho não-computável retorna um sentinela explícito — nunca `False`
silencioso (que pareceria "não disparou" quando na verdade é "não sei").

**Distribuição real de regime** (2019-12-31→2026-08-07, 231.552 barras de 15m):
R0=0,86% · R1=45,97% · R2=10,61% · R3=30,45% · R4=10,44% · R5=1,67%.
**97,47% do tempo é tradeable.**

**2 bugs reais encontrados e corrigidos** durante a implementação: um `Enum` com
mixin de `str` quebrava comparação vetorizada do numpy silenciosamente (virava
sempre `False`, sem erro); `Polars.value_counts()` não garante ordem entre duas
chamadas separadas.

**Sprint 6 — Label Engine (`src/labels/`):** triple barrier avaliado em mark price
real (1 minuto, primeiro toque cronológico), fill model simplificado e
explicitamente marcado como otimista (o simulador de fila de verdade é o Sprint
9), pesos por unicidade (AFML cap. 4). 58 testes.

**Achado principal — distribuição real medida sobre 6,5 anos** (462.682 labels,
2020-01→2026-08, os dois lados), substituindo os números fabricados do PRD antigo:

| Desfecho | Medido | Fabricado (PRD antigo, banido) |
|---|---|---|
| TP | 36,5% | 30–40% |
| SL | **51,3%** | 35–45% |
| TIME | 6,5% | 20–30% |
| NOFILL | 5,7% | 10–25% |

Barreiras resolvem muito mais decisivamente (menos `TIME`/`NOFILL`) e com mais
`SL` do que a suposição antiga previa.

**Achado — teto de features revisado:** `N_eff` (Σ unicidade) medido pela primeira
vez: **32.608 (long) / 32.236 (short)** por modelo — **acima** do topo da faixa
que o PRD especulava (3.241–20.740, §0.2 R4). O teto de features por modelo sobe
proporcionalmente; reconciliar com a ablação do Sprint 8.

---

## Sprints 7 e 9 (adiantado) — em paralelo (2026-08-08)
### commits `26be2a5` / `2444ab3` / `abcc3fc`, tag `sprint-7-9-done`

**Sprint 7 — CPCV + testes de vazamento (`src/validation/`):** splitter real (6
grupos cronológicos, 15 splits combinatórios, 5 caminhos de backtest via
1-fatoração de K₆) sobre os 462.682 labels reais. Purge usa o `t1` real de cada
label — mais estrito que a leitura literal do PRD, que sugeria uma margem fixa.

**Resultado do purge sobre dado real: 15/15 splits, zero `t1` de treino vazando
pro teste.** `n_purged` 0–54/split, `n_embargoed` 321–1.377/split — ambos bem
abaixo de 1% de cada fold (~308 mil linhas).

**Os 14 testes de vazamento do §11.5**, cada um com status explícito: **11
PASS**, 2 `PENDING_SPRINT_8` (shuffle de alvo pra AUC e vazamento de calibrador
— nenhum dos dois é testável sem modelo treinado, que só existe no Sprint 8), 1
`NOT_APPLICABLE_V1_1` (encadeamento do Meta — Meta está fora da V1 por desenho,
não é pendência). **Zero teste fingido.**

**Achado — 2 bugs reais de documentação, corrigidos:** a auditoria dos testes
2/3/9 achou que `registry.yaml` citava um teste de causalidade pra `E27f` que
não existia mais com esse nome, e afirmava que `A13` tinha teste de causalidade
dedicado quando só `A05` tinha (resíduo de copy-paste do Sprint 4) — corrigidos,
não só documentados.

**Achado — TF do embargo:** os "175 barras ≈ 88h" do §11.4 só batem a 30m; na
decisão real de 15m são **43,75h**. Registrado no comentário da constante.

**Sprint 9 (adiantado) — Simulador de fila (`src/execution/fill_simulator.py`):**
reconstrução de posição na fila a partir de `bookTicker` (topo do livro) +
`aggTrades` (volume agressor), sobre a única janela real disponível — 2023-05-16
a 2024-03-30, inteiramente pré-RPI. Bloqueio explícito no código contra simular
qualquer janela que cruze 2025-11-20.

**Achado principal — a medição mais importante até agora**, 60.650 ordens
simuladas nos dois lados:

| Métrica | Medido | Referência |
|---|---|---|
| `p_fill` | **37,3%** (compra 36,7% / venda 37,9%) | PRD §9.6: abaixo de 60%, "a economia do desenho maker evapora" |
| markout 1m/5m/30m | -0,586 / -0,643 / -0,590 bps | placeholder era 1,5bps (`adverse_selection_bps`) |

**Duas direções opostas.** A seleção adversa real (~0,6bps) é ~2,5x **menor**
que o placeholder assumido — boa notícia pro breakeven. Mas o `p_fill` medido
(37,3%) fica **abaixo do piso de 60%** que o próprio PRD cita como o ponto de
inviabilidade do desenho maker. É limite inferior pessimista (o modelo não
modela cancelamento nem fila além do topo do livro — só o Testnet/Paper,
Sprints 15-16, dão o número calibrado de verdade), mas é a primeira medição
real desse número, e a direção preocupa, não tranquiliza. Registrado como item
a reconciliar antes do Gate 5.

---

## Sprint 12 (adiantado) — Risk Engine (2026-08-09) · commit `981b153`

`src/risk/`: sizing quantizado via `Decimal`+`floor_to_step` (reusa `Filters` do
Sprint 2), os 18 controles do §8.3 em ordem, kill switch com os 13 gatilhos do
§10.2. Validado contra o exemplo numérico do próprio PRD (stop 0,50% → 3
unidades → risco real 0,495% — bate exato).

**Achado:** as outras 3 linhas da tabela ilustrativa do §8.3 só reproduzem com
arredondamento pro mais próximo, não com `floor_to_step` (o algoritmo que o
próprio §8.2 manda usar) — resolvido a favor do floor, o lado mais seguro.
Também achou e corrigiu um bug real nos próprios testes: o controle 17
(liquidez) não checava corretamente a metade "profundidade" de uma composição
de três valores, deixando passar profundidade insuficiente em silêncio.

16 dos 18 controles e 5 dos 13 gatilhos são totalmente computáveis hoje; o
resto fica com sensor pronto, sem fonte de dado real ainda (mesmo padrão do
Regime Engine). 89 testes novos.

## Sprint 8 (rodada 1) — Alpha, Camada 1 (2026-08-09) · commit `8654500`, tag `sprint-8-layer1-done`

Dois modelos binários (`M_long`/`M_short`, §5.2), restrições monotônicas
(Camada 1, §5.3) atribuídas *in-fold* sobre 6 ambientes (tercil de
custo/ATR × regime estrutural, §5.4 — não 7, como uma leitura literal de §5.3
sugeria; investigado e resolvido como resíduo de contaminação com a tabela de
IC anual do §17.2, a mesma que o próprio §5.3 proíbe usar pra configurar o
modelo). Calibração isotônica corrigida (sub-split interno, fecha o teste de
vazamento 11 que o Sprint 7 tinha deixado pendente).

**O critério de permanência da Camada 1 passa**: supera a Camada 0 (sem
restrição) em 4 de 5 caminhos do CPCV. HHI passa com folga (0,113 < 0,25).

**Mas isso não é "o Alpha tem edge pronto pra operar" — é importante não
confundir os dois:**

| Medição | Resultado |
|---|---|
| Sharpe (ingênuo) Camada 1 / Camada 0 | -0,81 / -1,18 — **os dois negativos** |
| B2 buy-and-hold | **+0,54 — positivo, vence os dois variantes do Alpha** |
| B4 (AUC real, sem embaralhar) | ~0,50 (0,497 long / 0,503 short) — pouca discriminação individual mesmo antes do teste de embaralhamento |
| Decomposição §16.6 (30.623 trades) | direção +1,60 · carry +2,07 · **execução -17,71** · total -14,03 |

**A leitura honesta**: sem custo de execução, direção+carry somam **+3,67 —
positivo**. É o custo de execução, sozinho, que vira o resultado negativo — não
falta de sinal direcional (`directional_sharpe = +0,194`, positivo). Isso
conecta direto com o achado do fill rate (37,3%, ver investigação abaixo): o
motor pode ter um fiozinho real de sinal, mas a economia de execução está
consumindo ele inteiro e mais.

**Achado metodológico a carregar pro Sprint 10**: o backtest deste sprint
(`backtest_lite.py`) usa a convenção otimista do Label Engine (`barrier_hit !=
NOFILL`, fill rate ~83-93%) — **ainda não incorpora o fill rate realista de
37,3% medido pelo simulador de fila do Sprint 9.** O Sharpe de -1,69 pooled
provavelmente fica pior, não melhor, quando essa reconciliação acontecer.
Registrado para não ser esquecido.

**Próximo passo em aberto**: já que a Camada 1 passa o gate arquitetural do
§5.11, a Camada 2 (triagem de estabilidade) é candidata a próxima rodada — mas
a pergunta mais urgente pode ser reconciliar com o fill rate real antes de
investir mais camadas em cima de um custo de execução ainda otimista.

## Investigação — o fill rate de 37,3% é real ou artefato? (2026-08-08) · commit `d3bcc79`

Antes de avançar pro Sprint 8, o achado do Sprint 9 (fill rate abaixo do piso de
60% que o PRD cita) foi investigado a fundo em 5 frentes, todas sobre dado real:
curva de tempo-até-preenchimento, timeout 15min vs 30min, estratificação por
regime e hora UTC, sensibilidade a postar 1 tick melhor, e correlação entre
velocidade de preenchimento e seleção adversa.

**Conclusão: o número é real, não artefato do modelo simplificado.** Sobrevive
a todos os testes — mediana de tempo-até-fill é 4 segundos (72,5% do que vai
preencher já preencheu em 30s), dobrar o timeout pra 30min move o número de
37,3% pra só 40,7%, a estratificação por regime mostra direção consistente com
a teoria mas efeito pequeno (~8,5pp) e nenhum regime nem horário chega perto de
60%.

**Mas o achado mais importante foi sobre o próprio piso de comparação**: "fill
rate mínimo 60%" (PRD §9.6) está **literalmente listado em §18.5.4 do PRD como
número fabricado**, sem derivação, mesma categoria do `adverse_selection_bps`
que o Sprint 9 já tinha mostrado errado por ~2,5x. Comparar uma medição real
contra um limiar inventado é o mesmo erro de sempre, só que do lado do limiar.
**Recomendação registrada**: derivar o fill rate realmente necessário (não
aceitar 60% a priori) quando o Alpha existir (Sprint 8+) — não é remedição, é
trabalho que depende do modelo.

Sensibilidade testada (não adotada como novo padrão): postar 1 tick melhor
(furar fila) só é possível em 25% dos pontos, e onde é possível, dobra o fill
rate mas piora a seleção adversa em 71%. Registrado como pista futura, não
mudança de desenho.

## Índice rápido — onde encontrar cada número

| Pergunta | Resposta | Onde |
|---|---|---|
| Quantos testes passam hoje? | 384 (1 skip esperado) | `pytest tests/ -q` |
| Distribuição real de TP/SL/TIME/NOFILL? | 36,5/51,3/6,5/5,7% | `labels/v1/labels.parquet`, Sprint 6 acima |
| N_eff real (teto de features)? | ~32,4 mil por modelo | Sprint 6 acima |
| Quais gatilhos de stress funcionam? | 3 de 10 (S1,S3,S6) | `src/regime/stress.py`, Sprint 5 acima |
| Distribuição real de regime? | R1 domina (46%), R5 raro (1,7%) | Sprint 5 acima |
| Cobertura real de dado por fonte? | tabela acima | Sprint 0/backfill acima, `config/constants.yaml::known_gaps` |
| Correlação real entre features T1? | 2 pares violam 0,70 | Sprint 4 acima |
| CPCV vaza treino pro teste? | Não — 0 de 462.682 labels, medido | Sprint 7 acima |
| Quantos dos 14 testes de leakage passam? | 11 PASS, 2 pendem de modelo, 1 N/A | Sprint 7 acima |
| Fill rate real (maker)? | **37,3%** — abaixo do piso de 60% do §9.6 | Sprint 9 acima, **item mais crítico em aberto** |
| Seleção adversa real medida? | ~0,6bps (menor que o placeholder de 1,5bps) | Sprint 9 acima |
