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
37,3% medido pelo simulador de fila do Sprint 9.** ~~O Sharpe de -1,69 pooled
provavelmente fica pior, não melhor, quando essa reconciliação acontecer.~~
Errado — ver "Auditoria externa + reconciliação parcial" abaixo: dentro da
janela onde dá pra medir de verdade, o gate real deixa o Sharpe **menos**
negativo, não mais. A intuição registrada aqui não bateu com a medição.

**Próximo passo em aberto**: já que a Camada 1 passa o gate arquitetural do
§5.11, a Camada 2 (triagem de estabilidade) é candidata a próxima rodada — mas
a pergunta mais urgente pode ser reconciliar com o fill rate real antes de
investir mais camadas em cima de um custo de execução ainda otimista.
**Resolvido parcialmente — ver seção seguinte.**

## Auditoria externa do Sprint 8 + reconciliação parcial (2026-08-09) · commits `f81e26e`/`6c35065`/`756a196`

Antes de decidir entre Camada 2 e reconciliação, o resultado do Sprint 8 foi
enviado pra revisão externa (quem desenhou o plano junto). A crítica levantou
4 pontos; cada um foi verificado contra o código e os dados reais antes de
aceitar ou refutar — não por plausibilidade.

**1. "Backtest roda 7x acima do orçamento de fees (12,71 trades/dia)"** — a
crítica tinha o instinto certo mas a aritmética errada: os 30.623 trades do
relatório original são a SOMA dos 5 caminhos de backtest do CPCV, cada um dos
quais reconstrói os ~6,5 anos inteiros de forma independente (é a definição
de "caminho" em CPCV). Somar os 5 e dividir por um único calendário conta o
mesmo período cinco vezes. O número certo já estava no relatório, por
caminho: `trades_per_year` médio ≈ 941,7/ano ≈ 2,58/dia — **~1,4x acima do
orçamento R3 (~660/ano), não 7x**. Também confirmado: `target_signal_rate`
(1,89%) já é aplicado in-fold via `tau` em `alpha.py` — não é sinal cru.

**2. "Fill rate de 37,3% pode ser alívio, não problema — testar
P(TP|fill) vs P(TP|miss)"** — correto e agora medido (Módulo B da
reconciliação, achado abaixo): gap pequeno, **não é o vilão**.

**3. "AUC ~0,50 é zero discriminação; falta o baseline B1 decisivo"** — B1 já
existia (só não tinha entrado na síntese anterior) e o resultado favorece
"há sinal": Alpha no percentil 100 de 1.000 sorteios aleatórios. Refinado
nesta rodada (achado abaixo) porque a comparação original tinha uma
mistura de variância entre média-de-5-caminhos e sorteio único.

**4. "N_eff medido é 16x a folga que o PRD especulava"** — confirmado,
consistente com o já registrado no Sprint 6.

**B1 refinado** (`src/models/baselines.py`,
`experiments/alpha_b1_refinement_report.json`): três testes mais rigorosos
que a comparação original (que misturava a variância de uma MÉDIA de 5
caminhos com sorteios de amostra única — inflava o percentil a favor do
Alpha mesmo que as distribuições fossem idênticas).

| Teste | Resultado |
|---|---|
| Por caminho (nulo do próprio tamanho de amostra) | 4 de 5 caminhos no percentil 100; **caminho 4 (o pior, Sharpe -1,96) cai pra 70,9** |
| Nulo de variância pareada (mesma estrutura de promediação do Alpha) | percentil 100 |
| Pool total (30.623 trades vs `pooled_all_15_splits.total_sharpe`=-1,686) | percentil 100 |

O percentil=100 original sobrevive ao escrutínio mais rigoroso na maior
parte — só o caminho 4 individualmente era mais fraco do que a média
sugeria. Não vira "prova fechada" de edge real, mas pesa contra a leitura
"é só beta".

**Reconciliação de fill real** (`src/backtest/fill_reconciliation.py`, novo —
primeiro conteúdo real da camada `src/backtest/`, vazia desde o Sprint 1;
fatia adiantada e estreita do Sprint 10, só a reconciliação, não o motor de
backtest completo): troca o gate otimista do Label Engine
(`barrier_hit != NOFILL`) pelo gate real do simulador de fila (`filled`),
restrita à janela onde há dado de bookTicker de verdade (2023-05-16 a
2024-03-30 — nunca extrapolado além dela, mesmo limite que o simulador já
respeita).

Duas correções de método encontradas medindo, não assumindo: `orders.t_post`
casa com `labels.t_entry`, não `labels.t0` (uma junção ingênua por `t0`
devolve zero linhas); `barrier_hit==NOFILL` tem `t_entry` nulo por
construção — tratado como `filled=False`, verificado com zero
contra-exemplos do oposto nos dados reais.

| | Otimista (`barrier_hit != NOFILL`) | Real (`filled` do simulador) |
|---|---|---|
| Fill rate (2.116 sinais em comum) | 97,1% | 42,2% |
| Sharpe ingênuo | -9,25 | **-4,27 — menos negativo** |
| Direção + carry | negativos nos dois | negativos nos dois |

**Leitura importante, não simplificar**: trocar o gate melhora o Sharpe
dentro desta janela, mas direção+carry são NEGATIVOS nos dois gates aqui —
diferente do +1,60 pooled sobre os 6,5 anos completos do Sprint 8. Esta
janela específica (~10,5 meses) não parece representativa do regime médio
do modelo, então este resultado **não confirma nem descarta** se o -17,71
de execução original vira positivo com fill real — só mostra que, onde dá
pra medir de verdade, o gate otimista superestimava o dano de execução mais
do que subestimava. Reconciliar a economia dos 6,5 anos completos continua
sem resposta — não há dado de bookTicker fora desta janela pra medir.

**Teste de seletividade** (Módulo B, 60.650 pontos de grade — não só sinais
do Alpha): P(TP|filled)=36,6% vs P(TP|não-filled)=38,3%, gap=-1,72pp,
custo em EV ≈ -1,12bps. **Pequeno** — fill rate baixo não esconde uma
concentração de vencedores do lado que não preenche, consistente com a
seleção adversa quase nula (~0,6bps) já medida no Sprint 9. Responde
diretamente ao ponto 2 da revisão externa: alívio confirmado, não problema.

**Gap ainda aberto**: a reconciliação acima só cobre a janela do bookTicker
(~10,5 meses de 6,5 anos). A economia honesta do Sharpe -1,69 pooled sobre a
história completa continua sem uma resposta direta — só o Testnet/Paper
(Sprints 15-16) mede fill real fora da janela de bookTicker disponível.

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

## Sprint de engenharia — "faltou proveniência de valor derivado" (2026-08-09)
### commits `ff68873`/`5221396`/`713c5db`/`b387dd7`/`39ac296`

A auditoria externa do Sprint 8 (seção acima) expôs 6 achados que pareciam
independentes mas eram a mesma causa raiz: **número derivado circula sem os
metadados que o tornam interpretável.** `constants.yaml` sempre exigiu
proveniência de toda CONSTANTE — nunca exigiu o mesmo de nenhum valor
DERIVADO. Entrada tinha proveniência; saída não tinha. Timeboxed, escopo
fechado a priori (Fases A/B/C1-C2/G; D/E/F/H ficam para depois, não
iniciadas).

**Fase A — parar a hemorragia de diagnóstico.** `alpha.py` calculava
`gain_by_column`/`concentration` por fold × lado, todo run, e descartava
depois de alimentar o HHI agregado — recuperar isso para a investigação de
importância de features custou um retreino completo (~117s). Agora persiste
em `models/{model_id}/diagnostics/fold_{k}_{side}.json` (60 arquivos reais,
gain bruto + normalizado, HHI, n_trees, n_amostras). Inventário (não
corrigido) de 7 outros candidatos ao mesmo padrão em
`docs/audit_discarded_diagnostics.md` — prioridade máxima:
`monotonic.py::FeatureICResult.ic_by_env`, o irmão direto do bug que
motivou esta fase inteira.

**Fase B — o tipo `Metric`.** `src/core/metric.py` (novo, deliberadamente
pequeno): `Metric(value, unit, n, n_semantics, source, valid,
invalid_reason)` + `safe_ratio()` com guarda estrutural de denominador.
Aplicado nos campos reportáveis de `decomposition.py`,
`backtest/fill_reconciliation.py`, `hhi.py`. **Mudança de comportamento
real, não só cosmética**: `carry_share = pnl_carry/pnl_total` agora é
`Metric` inválido quando `pnl_total <= 0` (é, nos dados reais) —
`gate3_carry_share_ok` vira `False` em vez de passar por acidente
aritmético, visível ponta a ponta no rerun final do pipeline (era `true`,
virou `false`). A fórmula em si (`pnl_carry/(pnl_direcional+pnl_carry)`)
fica para outra rodada — só a guarda de validade entrou agora.

**Fase C1/C2 — auditoria de divisões sem guarda (tabela, sem corrigir).**
13 divisões de razão variável varridas em `risk/limits.py`,
`risk/kill_switch.py`, `decomposition.py`, `backtest/*`, `validation/*` —
**2 RISCO REAL**. Além do `carry_share` já conhecido: **`risk/limits.py:228`
(`control_10_risco_real`) guarda só `equity==0`, não `equity<=0`** — com
`risk_real` estruturalmente ≥0, um `equity` negativo (perda extrema — lote
mínimo já é 33% do equity de US$196,85) faz a razão sair ≤0, que passa
trivialmente o limiar. O controle de "estouro de risco" aprovaria
automaticamente na pior hora. O mesmo campo `equity`, no mesmo sprint, é
guardado corretamente em `kill_switch.py::k01_daily_loss` — só não em
`limits.py`. **Não corrigido nesta rodada** (tabela completa em
`audit/division_guard_audit.md`), fica pendente de decisão explícita.

**Fase G — golden-file de reprodutibilidade.** A investigação de
importância de features assumiu que XGBoost com seed fixo reproduziria os
números do Sprint 8 sem nunca conferir isso — suposição certa, mas
suposição. `tests/golden/test_sprint8_reproducibility.py` reproduz o fold 0
(as 4 combinações variante×lado) com a config real e compara contra os
artefatos commitados da Fase A, tolerância zero, comparação por igualdade
de ponto flutuante. Passou de primeira. O rerun final completo do pipeline
(que gerou os artefatos commitados) também reproduziu bit-a-bit os 15
splits inteiros contra a rodada anterior — só `elapsed_seconds` e
`gate3_carry_share_ok` (o achado da Fase B, esperado) mudaram.

585 testes (era 552), 0 violação de lint, 4/4 contratos de import-linter
mantidos.

**Não iniciado nesta rodada, ponto de parada explícito**: Fase D (HHI
efetivo, correção por correlação entre features), Fase E (módulo de
explicabilidade pós-hoc, `src/analysis/`, com contrato de import-linter
proibindo `models/`/`features/` de importar dele — separação crítica de
insumo-de-treino vs. diagnóstico-pós-hoc), Fase F (sentinela de ausência
para R0 = zero trades), Fase H (hooks de CI pra fechar as costuras já
vistas: proveniência fora de commit, análise decisiva em script
descartável).

## Sprint de engenharia — Fases D/E/F/H (2026-08-09)
### commits `fe7f705`/`43b8865`/`2fae0d9`/`32e8422`

Continuação da rodada acima, depois do ponto de parada.

**Fase D — HHI efetivo** (`hhi.py::compute_effective_concentration`):
número efetivo de fatores via participation ratio dos autovalores da
matriz de correlação das T1 ponderada por gain (`N_eff = (Σλ)²/Σλ²`,
`hhi_effective = 1/N_eff`) — prova matemática de que `hhi_effective >=
hhi_nominal` sempre, igualdade só sem correlação. **Achado real, rerun
completo**: nominal 0,1131 (bate exato com o já reportado) vs **efetivo
0,1888 — 67% maior**. Em média só **5,3 dos 10 fatores T1 carregam
informação genuinamente independente**. Gate 3.4 passa a avaliar o
efetivo (nominal preservado ao lado, nunca substituído) — não muda de
veredito (0,189 < 0,25 também), mas a concentração real é pior do que o
número "saudável" original sugeria.

**Fase E — `src/analysis/attribution.py`**: formaliza a análise ad hoc de
IC-por-regime feita numa investigação anterior (e deletada depois) como
módulo testado. Reproduziu, sobre dado real, o mesmo achado: funding
inverte de sinal entre regime de faixa (R1/R2) e tendência (R3/R4), pico
em R5 (+0,199). Dois contratos novos de import-linter (`models`/`features`
não importam `analysis`) tornam a separação treino-vs-explicação
estrutural, não só documentada — mesma classe de proteção do banned
pattern B06.

**Fase F**: confirmado ponta a ponta — R0 (0,81% da história) é **100%
warmup**, zero barras com T1 válido, não efeito de `tau`. `not_computable()`
adicionado ao `Metric`, formalizando o padrão `NOT_COMPUTABLE` já usado em
Regime/Risk.

**Fase H**: dois hooks de CI fecham as lacunas de processo já vistas —
`check_constants_referenced.py` (AST-scan de `load_constant()` contra
`constants.yaml` **no índice do git**, não a working tree — é o mecanismo
que teria pego o incidente real das ~280 linhas fora de commit) e
`check_sprint_log_references.py` (heurístico, `continue-on-error` no CI,
documentado como tal).

**646 testes** (era 585), 0 violação de lint, **6/6 contratos** de
import-linter mantidos (2 novos desta rodada). As 8 fases (A/B/C/D/E/F/G/H)
do sprint de engenharia estão completas.

## Tarefas quant pós-auditoria — T0 a T5 (2026-08-09)
### commits `c1ca0ae`/`cef8e46`/`f6abdf3`/`faa9b3c`/`19c73aa`

Retomada da lista que o criador do plano deixou pra depois do sprint de
engenharia, agora com `Metric` em vigor. 715 testes (era 646).

**T0 — restrição monotônica grátis, achado positivo real**: `E02f_funding_z`
forçado por identidade contábil (-1 no long, +1 no short — mesmo padrão de
`E27f_cost_atr_ratio`, mas sinal por lado), sem custo de `n_lifetime`
(confirmado lendo o único writer do ledger, não assumido). Substituiu
`alpha_c1_v1` (mesma variante). **`directional_sharpe` pooled saltou de
0,194 pra 0,879, permanência foi de 4/5 pra 5/5 caminhos** — a primeira
melhora real e gratuita medida no Alpha desde o Sprint 8.

**T1 — decis de confiança não ordenam retorno**: Spearman entre rank do
decil e retorno realizado ≈0 nos dois lados (não significativo). Achado
mais preocupante: **no long, o decil de MAIOR confiança é o de PIOR
desempenho** (-25,6bps, t=-3,0) — anti-padrão, não ruído. Sem ranking
explorável pra Camada 2+. O número de contexto citado numa devolutiva
anterior ("edge 0,427 vs 2,273bps") não reproduziu com `ret_net` — melhor
hipótese, não forçada: confusão com `ret_gross`.

**T2+T3 — carry não é o motor do percentil=100, mas não decompõe por
percentil sozinho**: a previsão registrada (cair pra ~65-70% sem carry)
não se confirmou — os três testes (B1 original, carry-stripped, B1' só-lado)
saturam em 100. Mas o **z-score** (não usado antes) decompõe: tirar o carry
quase não move o z (14,0→13,2); fixar timing real e sortear só o lado
derruba mais (14,0→~9-11), sobrando um resíduo grande atribuível à escolha
de lado em si. Lido junto com T1: o modelo parece acertar a direção binária
melhor que cara-ou-coroa, mas não calibra bem a magnitude de confiança.

**T4 — o invariante do tau passa sobre a história completa**: a dispersão
de 4,9x que preocupava era específica da janela restrita do bookTicker
(10,5 meses), não do sistema inteiro. Sobre os 6,5 anos: realizado/alvo
≈1,01 (pré-fill) / 0,85 (pós-fill), dispersão entre caminhos 1,52x — dentro
do critério proposto (±20%/dispersão<2x).

**T5 — superfície de custo 2D, 9 células, história completa (não amostra)**:
custo vai de 5,37bps (tp solto/sl solto) a 6,25bps (tp apertado/sl
apertado); base atual 5,84bps. Achado de leitura de código: **TIME também
paga taker, não só SL** — revisa a leitura anterior "TP=maker,SL=taker"
para "TP=maker,{SL,TIME}=taker". Share do taker no custo total: 42-60%
conforme `sl_atr_mult`, confirma essa constante como a alavanca real.

**Leitura conjunta T0-T5**: o Alpha tem um componente direcional real
(T0 melhora de graça, T2+T3 mostra resíduo de direção que sobrevive a
timing e carry) mas não sabe se auto-avaliar (T1, decis não ordenam) —
duas capacidades diferentes, só uma presente. `tau`/orçamento de trades
não são mais suspeitos (T4). Custo de execução tem alavanca clara e
quantificada pra otimizar depois (T5).

## Skill de auditoria de engenharia + script mecânico de divisões (2026-08-09)
### commit `07ac7a6`

Motivado por um achado concreto: a mesma classe de bug (divisão sem guarda de
sinal) apareceu em dois subsistemas diferentes, construídos em momentos
diferentes por agentes diferentes (`decomposition.py`, Sprint 8; `risk/
limits.py`, Sprint 12) — prova de que não é específica de onde a atenção
esteve. ~6.900 linhas (`exchange/`, `data/`, `labels/`, `execution/`,
`risk/sizing.py`, `monitoring/`) nunca passaram pelo checklist de engenharia
desta investigação (só `models/`, `backtest/`, `validation/`, `risk/limits.py`
e `kill_switch.py` receberam essa atenção até agora).

**`tools/lint/check_unguarded_ratios.py`** — AST-scan repo-wide, mecaniza a
pergunta que a Fase C1/C2 fez à mão sobre só 5 arquivos. Achado real ao rodar
pela primeira vez: `pathlib.Path.__truediv__` (junção de caminho) usa o mesmo
nó AST de divisão aritmética — gerou 182 falsos-positivos de 206 antes de um
filtro heurístico (literal string ou nome terminando em `_DIR`/`_ROOT`/
`_PATH`). Depois do filtro: **83 divisões reais, 59 sem guarda** —
incluindo `src/risk/sizing.py:131` (`notional_real / equity_d`), o MESMO
`equity` que já tinha o bug confirmado em `limits.py`, achado de forma
independente pelo script. Escape hatch `# noqa: unguarded-ratio — <motivo>`,
mesmo padrão de `# noqa: magic-number` já usado no repo.

**`.claude/skills/audit_engineering/`** — skill nova, adapta a metodologia de
lente quádrupla (FS estatística / FI implementação / FT tecnológica / FCN
contrato negativo) de um projeto irmão, cross-referenciando os banned
patterns do CLAUDE.md e as 6 classes de bug confirmadas nesta investigação em
vez das do outro projeto. Pesquisa web obrigatória antes de auditar,
fundamentada em metodologia estabelecida: Sculley et al. 2015 ("Hidden
Technical Debt in ML Systems"), Breck et al. 2017 (Google, "ML Test Score"),
e um paper de 2026 que formaliza vazamento temporal como propriedade
verificável (base da pergunta central da lente FS). Modo varredura usa
`Workflow` pra particionar por pacote quando o pedido for mais que 1-2
arquivos — ordem sugerida pro primeiro sweep: `exchange/` → `data/` →
`labels/` → `execution/` → `risk/sizing.py` → `monitoring/`.

729 testes (era 715), 0 violação de lint, 6/6 contratos de import-linter.

**Fase H concluída** (rodada separada) — `tools/lint/check_constants_referenced.py` (referência `load_constant("...")` em `src/` sem entrada em `constants.yaml`, verificado contra o índice do git — o que teria pego o incidente acima) e `tools/lint/check_sprint_log_references.py` (heurístico: linha nova aqui com número sem referência por perto); testes em `tests/unit/test_check_constants_referenced.py` e `tests/unit/test_check_sprint_log_references.py`, hooks em `.pre-commit-config.yaml`/`.github/workflows/ci.yml`.

## Faixa 1 — diagnóstico de calibração de confiança (2026-08-09)

Retomada do achado de T1 ("decis de confiança não ordenam retorno",
Sprint acima): T1 media só o agregado pooled, sem NOFILL, sem
estratificação, sem testar se o antipadrão sobrevive ao score cru. Regime
DESCOBERTA — medição pura, nenhum decil/threshold/calibrador/feature de
produção alterado. Módulo novo `src/analysis/calibration_diagnostics.py`
(consolidado: join predictions+labels+regime SEM filtrar NOFILL, reusado
por D1-D4), `tests/unit/test_analysis_calibration_diagnostics.py` (23
testes, 1 integração real com skip-if-ausente). Resultado completo em
`experiments/faixa1_calibration_diagnostic.json`.

**STEP 0 — as 5 premissas `[HIPÓTESE]` do prompt, todas confirmadas no
disco** via `src.analysis.attribution.confidence_deciles_by_side` (o
método que gerou os números de T1 originalmente): decis equal-sized por
lado (±1, mecânico); `-25,6bps`/`t=-3,00` e `+4,69bps` na mesma unidade
(bps por trade) reproduzidos bit-a-bit; `pnl_total=-10,30` é SOMA sobre
`n=36.538` (não média — confirmado em `alpha_layer1_report.json`);
`carry_share=26,6%` é a leitura `pnl_carry/(pnl_direcional+pnl_carry)` =
`2,858/(7,892+2,858)` = `0,2658` (a fórmula hoje em código,
`pnl_carry/pnl_total`, dá inválida por `pnl_total<0`, guard já existente —
achado da auditoria anterior, nunca reescrita); `predictions.parquet`
retém a linha mesmo com `barrier_hit=="NOFILL"` (confirmado: 2.681 linhas
NOFILL no lado long, 4.353 no short, sobrevivem à junção sem filtro).
Nenhuma premissa refutada — gate passou, D1-D4 rodaram.

**D1 — perfil completo de decil, população cheia (filled+NOFILL, não só
preenchidos como em T1)**: Spearman confiança×retorno **long ρ=0,139
p=0,70; short ρ=-0,20 p=0,58** — nem um nem outro significativo, mesma
leitura direcional de T1 (sem ranking explorável), números levemente
diferentes por desenho (decis aqui rankeiam sobre TODOS os sinais, não só
os preenchidos — necessário pra D3 medir taxa de NOFILL sem ser
trivialmente zero). `mean_excluding_decile_k`: 10 valores por lado, sem
comentário (ver JSON).

**D2 — por regime estrutural**: `by_regime` cobre R1-R4 (R0/R5 fora, mesma
convenção de `src.models.environments`); 1 de 8 blocos regime×lado
(`long/R1`, n_total=1.808) sai 10/10 células `insuficiente` (n<200);
`short/R1` 1/10 e `short/R2` 3/10 insuficientes; os demais 5 blocos, 0/10.
`by_cost_tercile` (tercis de `E27f_cost_atr_ratio` sobre a população
pooled de cada lado): 0/10 insuficiente em qualquer tercil, os dois lados.
**"Insuficiente" não é só uma flag ao lado do número** — `mean_ret_net_bps`/
CI95/t-stat saem `null` nessas células (literal do prompt: "não estimada"),
`n`/`n_filled`/as taxas TP·SL·TIME·NOFILL continuam reportadas (frequência
observada, não estimativa com incerteza amostral). Regra aplicada no mesmo
ponto do código pras 4 chamadas de `_decile_cell` (D1 pooled, D2, D2-tercil,
congruente/incongruente) — nenhuma das outras três tinha célula abaixo de
200 nos dados reais, então só D2-regime muda de fato.

**Subconjunto congruente/incongruente com a restrição forçada de
`E02f_funding_z_expanding`**: IC medido por regime (reprodução da Fase E,
`ic_by_regime` pooled) — **R1 IC=+0,038 (n=3.702), R2 IC=+0,109
(n=6.611), R3 IC=-0,026 (n=11.055), R4 IC=-0,082 (n=9.599)**, todos
`ic_valid=true`. Restrição forçada é -1 no long / +1 no short (§5.3,
`src.models.monotonic`, lida direto do código de produção — não
duplicada): congruente do **long é {R3,R4}** (n=12.228), incongruente
{R1,R2} (n=7.135); congruente do **short é {R1,R2}** (n=5.478),
incongruente {R3,R4} (n=11.263). Confirma numericamente a inversão de
sinal RANGE↔TREND já registrada na Fase E.

**Correção de framing (Faixa 1.6, Bloco 1, 2026-08-09):** o IC acima é
medido sobre a população OOF/realizada (`predictions.parquet`,
`side_hat != 0`) — a população que a triagem in-fold (§5.3, `screen_
monotone_constraints`) efetivamente usa pra decidir a restrição é outra
(TREINO do fold, todas as barras, antes de qualquer seleção). As duas
populações não são intercambiáveis: IC de treino é NEGATIVO uniforme em
R1-R4 nos 15/15 folds (Faixa 1.6, Bloco 1) — não há "inversão" nesse
IC. A tabela acima descreve a população NEGOCIADA (útil pra D1/D2), não
o insumo da triagem — não usar como se fosse a mesma medição. Ver
`experiments/faixa1_6_reconciliation.json::ic_reconciliation` e
`PRD_V3_2_UNIFICADO.md` §5.3.

**D3 — NOFILL por decil, SEM filtrar**: qui-quadrado decil×NOFILL
**altamente significativo nos dois lados — long χ²=194,5 (p≈4,7e-37, gl=9),
short χ²=655,2 (p≈3,0e-135, gl=9)**. A taxa de NOFILL varia com o decil de
confiança; a tabela completa (10 taxas + IC95 por lado) está no JSON, sem
leitura de direção registrada aqui (medição, não veredito).

**D4 (revisado — correção recebida em andamento, D4 original com 3
calibradores ajustados foi descartado antes de rodar sobre dado real;
`n_lifetime` não incrementa, não há variante de modelo nem de calibrador)
— score CRU vs score CALIBRADO, mesma população**:

| | long | short |
|---|---|---|
| Spearman sobre score cru | **ρ=-0,818, p=0,0038** (H1 decrescente: p=0,0019) | **ρ=+0,685, p=0,029** (H1 crescente: p=0,0144) |
| Spearman sobre score calibrado (=D1) | ρ=0,139, p=0,70 | ρ=-0,20, p=0,58 |
| fração de trades que trocam de decil | 0,747 (16.172/21.639) | 0,761 (16.687/21.933) |
| plateau mais largo do isotônico (unidade de score) | 0,201 (fold 9) | 0,099 (fold 6) |
| pontos no plateau do topo (soma dos 15 folds) | 457 | 50 |

Sem conclusão registrada aqui — os números falam por si e a decisão
(`(a)` do prompt: "se as duas tabelas forem iguais, o antipadrão é do
modelo, não do calibrador") é do Manager. **Hipótese do executor, marcada
como tal, não como achado**: as duas tabelas não são iguais — o score CRU
mostra relação monotônica MAIS forte e estatisticamente significativa que
o score calibrado nos dois lados (inclusive de sinal OPOSTO ao antipadrão
no long-decrescente vira ainda mais decrescente, não mais fraco), e ~75%
dos trades trocam de decil entre as duas versões; a leitura mais direta
desses três números juntos aponta pro calibrador diluindo/invertendo um
sinal que já existe no score cru, não o modelo criando um antipadrão que
o calibrador preserva — mas essa é uma leitura, não uma medição, e outras
são possíveis (ex. o isotônico pode estar corrigindo um viés real do score
cru que os 457+50 pontos no plateau do topo escondem). Fica para o Manager
decidir com o JSON completo em mãos.

**`n_lifetime`: incrementado em 0.** Correção recebida do Manager depois
da primeira versão do D4 (que ajustava Platt + isotônico-bin-mínimo sobre
`raw_score`, contaria +2) — a versão que rodou não ajusta calibrador
nenhum, só lê `raw_score`/`confidence` já persistidos em
`predictions.parquet` e a estrutura de plateau que eles implicam.
`audit/n_lifetime.yaml::counter` permanece em 3, não tocado.

776 testes (era 752 antes desta rodada — 24 novos, todos em
`tests/unit/test_analysis_calibration_diagnostics.py`), contagem completa
`pytest tests/`. 0 violação de `banned_patterns`, 6/6 contratos de
import-linter.

## Auditoria comparativa — projeto irmão Laplace_Quant_V16 (2026-08-09)

Comparação de engenharia contra um projeto irmão mais maduro (forex
multi-par, mesmo autor). Três achados aplicados nesta rodada, dois
registrados para o Sprint 6 (§18.7.1 do PRD), e uma auditoria cross-file
mais ampla reportada ao Manager sem mudança de código (achados de outro
projeto, não deste repo — não há o que aplicar aqui além do que já foi
listado).

**Aplicado — ECE em `calibration_diagnostics.py::expected_calibration_error`/
`calibration_error_by_side`.** Complementa D1-D4 da Faixa 1 (que medem
ORDENAÇÃO por decil) com uma métrica de MAGNITUDE (Guo et al. 2017,
ponderada por população do bin — deliberadamente diferente da leitura
não-ponderada do projeto irmão, ver docstring). Achado real, dado
real: **calibração isotônica MELHORA o ECE nos dois lados** (long
0,256→0,200; short 0,234→0,155) mesmo **piorando a ordenação por decil**
(D4, rodada anterior) — são propriedades diferentes da mesma
calibração, uma medida cada, nenhuma prevista pela outra.

**Aplicado — scan estatístico de leakage em `src/validation/leakage.py::
scan_feature_target_correlation`.** Não é um 15º teste do §11.5 (sem
âncora própria, PRD recebeu nota de rodapé). Medido antes de virar gate:
o threshold Bonferroni ingênuo (cópia direta da fonte) marcaria 4 das 10
T1 como suspeitas — `E27f_cost_atr_ratio` sozinho mede `rho=+0,142`
contra `ret_net`, porque o Label Engine escala TP/SL por ATR e várias T1
derivam de volatilidade — correlação ESTRUTURAL genuína, não vazamento.
Copiar o número do projeto irmão sem essa verificação teria produzido um
gate quebrado desde o primeiro commit. Por isso dois campos por feature:
`elevated` (informativo, Bonferroni) e `hard_fail` (bloqueante, threshold
calibrado no maior `rho` causal medido — `constants.yaml::
feature_leakage_hard_fail_threshold`, classe C, sweep_required). Rodado
sobre as 10 T1 reais: nenhuma estoura `hard_fail`
(`test_scan_sobre_dataset_real_nenhuma_feature_t1_hard_falha`).

**Registrado, não implementado — PRD §18.7.1.** (a) varredura 2D de
`tp_atr_mult`×`sl_atr_mult` do Sprint 6 deve rodar separada por lado, não
assumir simetria (motivada pela própria Faixa 1: long/short já medidos
como estruturalmente diferentes em quase toda dimensão observada); (b)
técnica de vetorização via `sliding_window_view` para a busca, em vez de
rotular a série inteira por célula do grid.

**Achados cross-file do projeto irmão, não aplicáveis a este repo** (reportados
ao Manager, sem ação neste código): arquitetura `multi:softprob` 3-classes
em produção — confirma a decisão de B18 aqui (dois binários), e o próprio
Laplace já está migrando pra 4 trainers binários por razão semelhante;
seleção de threshold por métrica OOS no gate de escolha de estratégia
Phase2 (`train_alpha_c1_v14.py`) — violação viva de B20, achada por
inspeção direta de código, não hipotética; divergência de lista de pares
entre 7+ arquivos, autocatalogada em `audit/pair_divergence_matrix.md`
do projeto irmão; `live_engine` recalcula features inline em vez de usar
o parquet de treino (Achado #17 catalogado como severidade ALTA lá,
correção mandatória antes de live) — exatamente a classe de bug que
nosso §2.0 Princípio 3 (caminho único batch/streaming) e o teste de
paridade < 1e-8 do DoD previnem por desenho aqui, não por correção
posterior; ausência de motor de backtest dedicado (confirmado por grep,
zero módulo, só 2 menções incidentais em comentário); 3 constantes de
latência (`LATENCY_KILL_MS`/`LATENCY_CRIT_MS`/`HEARTBEAT_INTERVAL_S`)
importadas mas nunca referenciadas fora do import — "circuit breaker" de
2000ms citado como decisão fechada na doc do projeto irmão não tem
nenhum código que de fato mate algo hoje.

## Faixa 1.5 — pré-requisitos do walk-forward (2026-08-09)

Seis blocos, regime declarado por bloco (Blocos 1/2/3/5 DESCOBERTA — medem,
não concluem; Bloco 4 CONSTRUTIVO). Módulo novo
`src/analysis/faixa1_5_prerequisites.py` (13 testes, 1 integração real
skip-if-ausente), resultado completo em
`experiments/faixa1_5_prerequisites.json`.

**STEP 0 — todas as premissas confirmadas no disco**, com uma nota: o
prompt citava "barras/ano = 35.064 (365×96)", mas 365×96=35.040, não
35.064 — a fórmula certa é 365,25×96=35.064 EXATO (`backtest_lite.
DAYS_PER_YEAR`, já a convenção de anualização usada em todo o resto do
repo). O valor-alvo (35.064) está correto, só a anotação da fórmula no
prompt tinha uma imprecisão — reproduzido aqui como aritmética
(`DAYS_PER_YEAR × SECONDS_PER_DAY / 900`), nunca um literal solto.
`predictions.parquet` confirmado retendo `score_{side}_raw` por
`fold_id` — Bloco 4 seguiu adiante.

**Bloco 1 — varredura de `fee_budget_monthly`**: no ponto central (0,030),
orçamento implicado é **1.325 trades/ano** (2 lados, `target_signal_rate
× 2 × bars_per_year`); os 5 `trades_per_year` REAIS por caminho ficam
entre 858 e 1.307 — nenhum excede o orçamento no ponto central (GATE 1
não dispara). 8 de 8 células lado×regime têm `n` suficiente no ponto
central — o "7 células" do prompt não se confirmou; todas as 8 têm dado.
Escala assumida linear (`target_signal_rate_ajustada = target_signal_rate
× candidato/atual`) — decisão de modelagem declarada, não verificada no
repo (não existe fórmula fechada documentada da derivação original).

**Correção (Faixa 1.6, Bloco 3, 2026-08-09):** o "2 lados" acima está
ERRADO — `PRD_V3_2_UNIFICADO.md:95-101` (§0.2 R3) deriva o orçamento sem
termo de lado (661/ano TOTAL, não por lado). Orçamento correto no ponto
central: **662,7 trades/ano** — os 5 caminhos reais (858-1.307) TODOS
excedem, 1,3x a 2,0x. Ver seção "Faixa 1.6" abaixo.

**Bloco 2 — checagem de Simpson**: recomputado por lado×regime e
lado×tercil de custo (`decompose()` reusado, não reimplementado). Achado
estrutural: `total_sharpe` pooled **long=-1,297 vs short=-0,164** —
os dois lados negativos, mas de magnitude bem diferente, já visível no
agregado (mesma direção da assimetria estrutural entre lados que a Faixa
1 já vinha medindo em outras dimensões). HHI "estratificado" é uma
APROXIMAÇÃO declarada (média de HHI por fold ponderada pela fração de
trades do fold no subconjunto — HHI é propriedade do modelo por fold, não
do trade individual; refit condicional a regime exigiria retreino, fora
de escopo). Nenhuma célula saiu `insufficient_n` nos dados reais.

**Bloco 3 — dispersão entre paths**: Spearman `n_filled` × `ret_net`
médio **ρ=0,10, p=0,87, n=5** — sem relação detectável (amostra
pequena, ressalva explícita no JSON). Fração de `t0` compartilhado entre
paths varia de 67% (path 0) a 91% (path 4). **Limitação registrada, não
corrigida nesta rodada**: os CI95 por path tratam trades como i.i.d.,
mas a mesma barra aparece em até 5 paths com `ret_net` correlacionado
(mesma barreira, modelo-fold diferente) — CIs provavelmente OTIMISTAS,
mesma família do §16.5 (Lo 2002) só que por duplicação ENTRE paths, não
autocorrelação intra-path.

**Bloco 4 — `confidence_rank`**: campo novo em `predictions.parquet`
(percentil do score cru DENTRO do `fold_id`, via `.rank().over("fold_id")`
— invariante verificado: Spearman(score cru, rank) = 1,0 dentro de
qualquer fold). Não recalibra sobre OOF empilhado. D1/D4 reexecutados
sobre as três versões (cru/calibrado/rank) com a mesma rubrica da Faixa
1 — três perfis completos no JSON, sem escolha entre eles feita aqui.
`§5.12` do PRD atualizado. **`n_lifetime`: 3 → 4**
(`audit/n_lifetime.yaml`, id 4).

**Bloco 5 — E02f in-fold**: `compute_ic_by_env`/`_assign_from_ic`
rodados nos 15 folds × 2 lados × 6 ambientes, sobre TREINO do fold
(nunca teste), sem retreinar. `alpha_monotonic_consistency_min_envs=6`
(consistência precisa ser 6/6, não 6/7 como o texto do §5.3 sugere —
já investigado e resolvido em rodada anterior). **Hipótese do executor,
marcada como tal, não como achado**: contando os 15 folds, o sinal que a
triagem estatística padrão atribuiria (`screen_sign_if_not_forced`,
ignorando a restrição forçada) nunca DISCORDA do sinal forçado quando
tem evidência suficiente pra decidir — 8/15 folds no long, 1/15 no
short chegam a 6/6 de consistência, e 100% desses concordam com o sinal
econômico (`_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE`); os outros folds
(7/15 long, 14/15 short) simplesmente não atingem 6/6, não apontam pro
lado oposto. Leitura possível: a restrição forçada de E02f não parece
estar sendo usada pra "salvar" um sinal que os dados contradizem — onde
os dados têm poder estatístico suficiente pra opinar, eles concordam;
o problema (se houver) é mais estatístico (n_consistent baixo,
especialmente no short) que de direção errada. Mas isso é leitura, não
medição — nenhuma regra por regime foi hardcoded, `monotonic.py` não
foi tocado, a decisão entre manter/remover a restrição forçada continua
do Manager.

**Verificação**: `banned_patterns --strict` limpo, `check_unguarded_ratios`
revisado (11 achados, todos seguros por construção — documentado no
docstring do módulo), `check_constants_referenced` OK, 6/6 import-linter,
mypy limpo. `pytest tests/` — 13 testes novos, todos passam (1 integração
real, skip-if-ausente).

## Faixa 1.6 — reconciliação de medições e correções (2026-08-09)

A Faixa 1.5 expôs uma contradição entre dois artefatos do próprio repo: o
IC de E02f medido pooled (Fase E) e o mesmo IC medido in-fold (Bloco 5 da
Faixa 1.5) divergiam em SINAL pro subconjunto RANGE. Cinco blocos, regime
declarado por bloco. Módulo novo `src/analysis/faixa1_6_reconciliation.py`
(18 testes novos), resultado completo em
`experiments/faixa1_6_reconciliation.json`.

**STEP 0** confirmou as 5 premissas do prompt (mesmo alvo `ret_net`, mesma
coluna/janela de E02f, `tau` fixado por fold, restrição forçada
estruturalmente separável por lado, mapeamento fold→path já existente) e
descobriu um sexto fator fora da lista original: `calibration_diagnostics.
congruent_incongruent_subsets` mistura long e short numa ÚNICA correlação
por regime, enquanto o in-fold é sempre separado por lado — testado
explicitamente no Bloco 1 como candidato "side_mixing".

**Bloco 1 — reconciliação do IC.** Reproduzido byte-a-byte o número já
persistido (R1 +0,0383, R2 +0,1094, R3 -0,0257, R4 -0,0821 — bate exato).
**Mistura de lado NÃO é o mecanismo dominante**: o long sozinho, OOF, já
mostra o mesmo padrão (RANGE=+0,083, TREND=-0,085) que o pooled misturado
(RANGE=+0,084, TREND=-0,052); o short sozinho não inverte (RANGE=+0,062,
TREND=+0,005).

**Correção de framing (2026-08-09, revisão pós-Bloco 1) — não é "OOF vs
treino" generalizando mal, é POPULAÇÃO SELECIONADA vs POPULAÇÃO
COMPLETA, e não há inversão a explicar.** IC de treino (pooled-concat)
dá as 4 regiões negativas (R1=-0,016, R2=-0,016, R3=-0,014, R4=-0,037 —
bate com o Bloco 5 da Faixa 1.5, 15/15 folds negativos); IC sobre OOF
inverte R1/R2 pro positivo (R1=+0,056, R2=+0,093). Mas OOF-long é, por
construção, só a fração que cruzou `tau` (~1,89% de TODAS as barras) —
e essa seleção está LONGE de ser uniforme por regime, medido
diretamente: **0,34% das barras de R1 viram sinal long, contra 4,34% em
R2, 2,01% em R3, 4,27% em R4** (`n_scored`/`n_side_hat_long` sobre
`predictions.parquet` inteiro). Condicionar num evento (`tau` cruzado)
que é função não-linear de TODAS as 10 features T1 — inclusive a
própria E02f — muda a distribuição conjunta por construção (viés de
seleção/Berkson, categoria diferente de vazamento temporal ou
autocorrelação). As duas medições estão CORRETAS; respondem perguntas
diferentes — treino é o insumo real da triagem (§5.3), OOF descreve a
população negociada. `§5.3` do PRD ganhou uma nota citando isso como
armadilha distinta da já existente (tabela de IC de 7 anos). Composição
de fold (fração de R2 dentro de RANGE no treino) foi testada e NÃO
explica a dispersão restante do OOF (Spearman ρ=0,025, p=0,93 —
descartado). Não decide qual medição é autoritativa (B06 governa o USO
da tabela, não a medição) — mas a frente de remover/ajustar a restrição
de E02f com base no IC pooled/OOF cai: essa medição nunca foi o insumo
da triagem, então não há contradição a resolver ali.

**Bloco 2 — sanidade do threshold, Fase A encontrou bug real.**
`threshold_effective_confidence_quantile` tomava o quantil sobre a
população JÁ SELECIONADA (`side_hat != 0`) em vez de todo bar OOF scored
do path — quantil-de-um-quantil. Path 0 media exatamente 1,0000 com
7.162 trades preenchidos (contradição óbvia: threshold no máximo
produziria zero trades). Corrigido em
`src.analysis.faixa1_5_prerequisites.path_dispersion` (agora recebe
`predictions`); os 5 valores caem de uma faixa 0,74-1,00 pra uma faixa
estreita e plausível 0,55-0,60. Fase B não rodou (instrução do prompt:
parar quando a Fase A encontra defeito de medição).

**Bloco 3 — correção real do fator ×2 no orçamento.** `PRD_V3_2_
UNIFICADO.md:95-101` (§0.2 R3) deriva o orçamento sem termo de lado
(661/ano TOTAL). `src/analysis/tau_diagnostics.py` introduziu um fator
×2,0 ("2 lados") no alvo nominal; `faixa1_5_prerequisites.py::fee_budget_
sweep` herdou por citação. Removido dos dois sites; `config/
constants.yaml::fee_budget_is_per_side` (`false`, DERIVED) formaliza a
constante que antes só existia implícita. Orçamento correto no ponto
central: **662,7 trades/ano** (era 1.325,4) — os 5 caminhos reais
(858-1.307) TODOS excedem agora, 1,3x a 2,0x no incondicional, 2,6x a
3,9x no pior ponto do sweep. `experiments/faixa1_5_prerequisites.json`
reemitido com as duas correções (Bloco 2 + Bloco 3). Teste de regressão
em `test_analysis_tau_diagnostics.py`/`test_analysis_faixa1_5_
prerequisites.py` trava contra reintrodução do fator.

**Bloco 4 — variante do short sem restrição forçada de E02f (retreino
real).** Parâmetro novo `unforce_features_by_side` (aditivo, default
`None` em toda a cadeia `screen_monotone_constraints` → `fit_side_model`
→ `run_fold` → `run_all_folds`; `run_layer1_sprint` nunca passa esse
argumento — `alpha_c1_v1`/`alpha_c0_baseline_v1` saem bit-a-bit
idênticos). Retreinados os 15 folds × 2 lados (long INTOCADO, só o short
perde a restrição forçada), model_id novo `alpha_c1_e02f_short_
unforced_v1`, artefatos persistidos (predictions.parquet + 30
diagnostics). **Achado central**: `directional_sharpe` pooled cai de
0,879 (baseline atual, os dois lados forçados) pra **0,282** — quase
todo o ganho do T0 (0,194→0,879) vinha do SHORT, não do long (long
sozinho, sem o short forçado, mal sai do pré-T0: 0,282 vs 0,194 de
partida). Isso é surpreendente à luz do Bloco 5 da Faixa 1.5: a triagem
estatística quase NUNCA confirmaria essa restrição no short sozinha
(1/15 folds com unanimidade 6/6) — a restrição que os dados quase nunca
"aprovam" é a que está fazendo a maior parte do trabalho. Efeito colateral
medido: 12.637 barras trocam de lado vencedor (`argmax(p_long,p_short)`)
entre baseline e variante — os dois binários são independentes em peso
mas acoplados na SELEÇÃO, então a diferença não é uma decomposição
aditiva limpa (mesmo `directional_sharpe` do long muda ligeiramente,
0,167→0,140, sem seu próprio modelo ter mudado). Permanência da variante
contra Camada 0: 5/5 caminhos (`min_paths_required=4`) — ainda supera
"sem restrição nenhuma", só não supera a Camada 1 atual.
**`n_lifetime`: 4 → 5** (`audit/n_lifetime.yaml`, id 5).

**Correção de método (2026-08-09) — decomposição direcional por lado,
não `ret_net`.** Uma leitura anterior ("long ordena, short é beta de
regime") foi construída sobre `ret_net`/`total_sharpe` estratificado,
que mistura direção + carry + execução (`src.models.decomposition`) —
método errado pra falar de skill direcional. Refeito com
`directional_sharpe` (já persistido em `stratified_headlines.by_side_
regime`, sem retreino): **short é POSITIVO nos 4 regimes** (R1=+1,19,
R2=+1,22, R3=+1,73, R4=+0,28 — nunca negativo), **long OSCILA
violentamente** (R1=+0,25, R2=**-2,52**, R3=+4,35, R4=+2,00). O pooled
long (+0,167) é quase inteiramente cancelamento entre R2 (forte
negativo) e R3/R4 (fortes positivos); o pooled short (+1,25) é
consistência, não cancelamento. Isso inverte a leitura anterior — se
"ordena" significa "skill direcional estável", é o SHORT que ordena
melhor por essa métrica, não o long. `total_sharpe`/`ret_net`
continuam válidos pra decisão de portfólio (o que efetivamente entra no
bolso), só não servem pra atribuir skill direcional — os dois números
respondem perguntas diferentes, mesma classe de cuidado do Bloco 1
acima.

**Anomalia a controlar antes de canonizar o achado do T0 — pendente,
não resolvida nesta rodada.** A restrição de E02f é justificada por
identidade CONTÁBIL de carry (funding penaliza long, paga short), mas
`monotonic.compute_ic_by_env` mede IC contra `ret_net` TOTAL, nunca
isolado em `PnL_carry` — a justificativa econômica (carry) e o alvo
estatístico (retorno total) já divergiam antes desta rodada. O efeito
medido no Bloco 4 (0,879→0,282) aparece em `directional_sharpe`, não em
`carry_share` — não é necessariamente evidência de que o mecanismo seja
diferente do anunciado (o desenho nunca isolou carry do resto), mas
também não confirma que seja carry. Controle proposto, barato, ainda
não rodado: forçar SINAL ALEATÓRIO (não o econômico) no short, várias
sementes — ganho similar ao medido ⟹ o efeito é regularização
genérica (forçar qualquer sinal monotônico reduz variância), não
conteúdo de E02f; ganho ausente ⟹ o conteúdo é real e específico da
feature, valendo então medir o IC separado nas caudas de funding
(hipótese: cascata de liquidação em funding extremo, não-linear,
lavada pelo Spearman na faixa inteira — consistente com a triagem
dizer "ruído" em 14/15 folds no short sem contradição). Terceira
hipótese em aberto, não testada: o efeito é real mas não tem nada a
ver com carry — E02f pode correlacionar com outra estrutura de
mercado/regime que carrega sinal direcional genuíno por razão
diferente da anunciada. Nenhuma das três é assumida; a variante do
short (Bloco 4 acima) e o "ganho do T0" permanecem NÃO canônicos até
o controle rodar.

**Bloco 5 — varredura pooled vs estratificado (escopo declarado, não
exaustivo).** 4 categorias: HHI efetivo, ratio de tau realizado, B3/B5
(baselines estáticos) por regime, e as 10 features T1 do scan de
leakage por regime (scan nunca tinha sido rodado contra dado real antes
desta rodada — `data/validation_reports/feature_leakage_scan_report.json`
gerado agora, 0/10 hard_fail, confirma o achado da auditoria comparativa
anterior). Maior divergência: B5 (short permanente) e B3 (regra
estática R3/R4), ambos ~72-75% de divergência relativa entre pooled e
por-regime — mas sem sign_flip (Sharpe sempre negativo, só a magnitude
varia). **Achado novo**: `D06f_taker_imbalance_z_48` também inverte de
sinal entre regimes (R1/R2/R4 positivos, R3 negativo) — pooled é
essencialmente zero (-0,0003), não elevado nem hard_fail no scan de
leakage, mas é o SEGUNDO caso (depois de E02f) de uma feature T1 cuja
correlação pooled esconde heterogeneidade por regime.

**Verificação**: 18 testes novos (`test_analysis_faixa1_6_
reconciliation.py`) + 2 de regressão do Bloco 3 + 2 de
`unforce_features_by_side` em `test_models_monotonic.py`, todos passam.
`banned_patterns` limpo, `check_constants_referenced` OK, 6/6
import-linter, mypy limpo.

**Revisão externa da Faixa 1.6 (2026-08-09).** Confirmou o Bloco 1
(seleção não-uniforme por regime, 0,34% em R1 a 4,34% em R2 — modelo
dispara **12,8x mais em R2 que em R1**) e nomeou um padrão que estava
implícito nos dois números sem estar unificado: **é o mesmo antipadrão
do decil de confiança (Faixa 1, D1: decis não ordenam retorno), agora
em granularidade de regime** — onde o modelo tem mais convicção
(R2/R4, alta taxa de seleção), o `directional_sharpe` do long é pior
(-2,52 em R2). Ponderado pela composição real de trades (27,5% do long
cai em R2), o pooled +0,167 é cancelamento com peso pesado no pior
regime, não "skill fraca" — quantitativo, não qualitativo.

Identificou um confound que o blueprint do walk-forward (§11.4.1) não
cobria: a composição de regime varia entre as 14 janelas, e a amplitude
de `directional_sharpe` entre regimes é MUITO maior no long (6,87) que
no short (1,45) — sem reportar composição por janela, G-WF-2
(meia-vida) e G-WF-3 (≥9/14 positivas) medem mix de regime, não
decaimento. **Corrigido em §11.4.1** (nova saída `composicao_regime_
por_janela` + nota de interpretação condicionada) antes do Sprint 11
rodar.

Propôs um teste mais barato que o controle de sinal aleatório pra
decidir a anomalia carry-vs-direcional: medir o IC de E02f contra
`PnL_carry` e `PnL_direcional` SEPARADAMENTE (ambos já existem por
trade via `src.models.decomposition`, sem retreino) — se carry for
forte e direcional for ruído, a identidade contábil se confirma.
**Não rodado nesta sessão** — próximo passo recomendado, ver seção de
recomendações abaixo.

Levantou que `N_lifetime` (em 5) conta variantes de modelo/retreinos/
constantes classe B, mas não comparações estatísticas feitas durante
análise exploratória (7 células lado×regime na Faixa 1, 8 células
direcionais + a escolha do subconjunto congruente na Faixa 1.6).
Verificado contra §16.9/§16.10.2/§9.5.1: o escopo hoje documentado de
`N_lifetime` é result de decisão (retreino, challenger, constante
otimizada, decisão de protocolo tipo RPI-vs-post-only) — não há
precedente escrito pra contar comparação descritiva de EDA. É uma
preocupação legítima de inferência seletiva (multiplicidade de
comparações), mas categoricamente diferente do que `N_lifetime` rastreia
hoje — decisão de escopo (estender `N_lifetime` ou criar mecanismo
separado) fica para o Manager decidir antes do Gate 3
(`§16.10.3` exige `N_lifetime` "declarado e versionado", não define o
que conta).

**Pendente — próxima rodada (2026-08-09).** Discussão sobre o mecanismo
por trás da seleção 12,8x maior em R2 (a mais escolhida contra a pior
performance direcional, `long_R2 directional_sharpe=-2,52`) levantou
4 medições ainda não feitas:

1. `directional_sharpe`/`ret_net` de R2 por ANO — decidir se a perda é
   estrutural (uniforme em todo ano com R2) ou de cauda (dominada por
   um ano específico, ex. 2021, o de maior prevalência de R2 medida:
   21,3%, contra 2,8% em 2023 — quase 8x de variação entre anos).
2. SHAP (ou gain_by_column) CONDICIONADO por regime — não só o gain
   global já medido (`regime_R2` dummy é só ~0,95% do gain médio; quem
   domina são features vol-sensíveis: `E27f_cost_atr_ratio`,
   `B01_rsi_14`, `C06_vol_ratio_12_96`, `A05_ret_vol_norm_4`) — precisa
   confirmar se são essas mesmas features que dirigem os splits
   especificamente dentro de barras R2.
3. `rate_nofill` cruzado com `E27f_cost_atr_ratio` — R2 já tem a pior
   NOFILL entre R1-R4 (16,7% vs 8,8% em R3); testar se é a interação
   custo×regime que explica isso.
4. Baseline B1 (entrada aleatória) estratificado por regime — nunca
   feito (mesma lacuna de escopo do Bloco 5 acima). Decide se o padrão
   R2-ruim/R3-bom é dirigido pela FEATURE (skill do Alpha) ou pela
   GEOMETRIA da barreira (`tp_atr_mult=2,0 > sl_atr_mult=1,5` favorece
   estruturalmente regimes de tendência, mesmo com entrada aleatória).

**Resolvidas na Faixa 1.7, abaixo.**

## Faixa 1.7 — edge ou beta+regularização? (2026-08-09)

Diferente das rodadas anteriores por instrução explícita: existe pra
produzir uma decisão, não só medir. Módulo novo
`src/analysis/faixa1_7_edge_or_beta.py` (9 testes), resultado completo em
`experiments/faixa1_7_edge_or_beta.json`. Critério de decisão
**pré-registrado abaixo, antes de rodar** — a aplicação aos números vem
depois, não embutida no JSON (sem campo `passed`/`ok`/`conclusion`).

**Duas perguntas de status, resolvidas primeiro:**

1. **Sweep assimétrico de `tp_atr_mult`/`sl_atr_mult` por lado (a técnica
   trazida da comparação com Laplace_Quant, §18.7.1)** — verificado contra
   `git log` e `src/`: **nunca implementado**, nem a varredura por lado nem
   `sliding_window_view`. Continua exatamente o que era — uma nota
   registrada pro Sprint 6, não uma dívida esquecida silenciosamente.
2. **Backtest usa fill otimista do Label Engine, não o simulador de fila
   (37,3%)** — a caracterização "nunca foi feito, sempre parece melhor do
   que é" está PARCIALMENTE certa e precisa de nuance: a reconciliação FOI
   feita, uma vez, dentro da janela onde há bookTicker real (2023-05 a
   2024-03, ~10,5 meses de 6,5 anos — ver "Auditoria externa do Sprint 8"
   acima). O resultado, medido, foi o OPOSTO do intuitivo: trocar pro gate
   real deixou o Sharpe MENOS negativo (-9,25 → -4,27), não mais — mas
   direção+carry ficaram NEGATIVOS nos dois gates nessa janela específica,
   diferente do +1,60 positivo do pooled de 6,5 anos. **A reconciliação da
   economia completa continua sem resposta** — não há bookTicker fora
   dessa janela pra medir, só Testnet/Paper (Sprints 15-16) resolve isso
   de verdade. Todo número desta Faixa 1.x continua sobre fill otimista;
   a direção do viés, onde já foi medida, não é "sempre parece melhor" —
   é desconhecida fora da janela de 10,5 meses.

### Critério pré-registrado (antes de ver qualquer número abaixo)

**Q1 — existe edge, ou é beta + regularização?**
- R3 partido por direção de tendência: lucra nas duas direções (skill) vs.
  só na direção favorável (beta).
- B1/B2 por regime: se o baseline sem seletividade já reproduz o padrão
  R2-ruim/R3-bom, é geometria — Alpha precisa SUPERAR essas células, não
  só repetir o sinal.
- IC de E02f contra carry vs. direcional: `|IC_carry| >> |IC_direcional|`
  confirma a identidade contábil; comparável ou invertido não invalida o
  T0 mas muda a explicação.

**Q2 — a confiança é consertável?**
- Regime one-hot ausente da matriz → dar informação, não filtrar. Presente
  → o problema é peso/interação, não ausência.
- Confiança residualizada (removida a componente linear de vol) ordena
  retorno por decil (Spearman p<0,05) → consertável por essa via. Resíduo
  continua sem ordenar → não é (só) contaminação por vol.

### Resultados

**Q1, medição 1 — R3 partido por direção (retorno de 48 barras, causal).**
R3-alta: n=6.067 (85,8% do book long em R3), `directional_sharpe=+4,62`,
`ret_net=+6,38bps`. R3-baixa: n=378 (5,6%), `directional_sharpe=-0,33`,
`ret_net=-9,33bps`. **Critério aponta pra BETA**: o book é 86% concentrado
onde "estar comprado numa tendência de alta" já é o resultado trivial
esperado; a fatia pequena que aposta contra a tendência imediata (a
prova de skill real) é neutra-a-negativa, não positiva.

**Q1, medição 2 — B1 (qualquer entrada) e B2 (exposição contínua) por
regime.** B1 (ambos os lados, todo trade não-NOFILL da regime): TODOS os
4 regimes negativos, mas R1/R3 são os PIORES (-20,1/-15,8), R2/R4 "menos
ruins" (-5,6/-5,8) — **não reproduz** o padrão do Alpha (que tem R3 como
melhor regime). B2 (sempre comprado, retorno bar-a-bar marcado pelo
regime de ORIGEM): R2 é o MELHOR regime pra ficar simplesmente comprado
(+1,53), R1 quase zero (-0,01), R3/R4 modestos (+0,21/+0,36) — **inverte**
o padrão do Alpha. Isso é mais rico que o critério previa: não é "a
geometria reproduz o padrão" nem "não reproduz" — é que ficar comprado o
tempo todo em R2 teria sido OK, mas as entradas SELETIVAS do Alpha em R2
perdem feio. Isso aponta pra um problema de TIMING de entrada dentro de
R2, não ausência de oportunidade ali. B1 mal-comparável (mistura os dois
lados numa regime onde direção importa, então qualquer aposta sem direção
apanha) — registrado, não usado como decisivo sozinho.

**Q1, medição 3 — IC de E02f contra `PnL_carry` vs. `PnL_direcional`,
separados.** Long: `IC_carry=-0,354` vs. `IC_direcional=+0,034` (razão
10,5x). Short: `IC_carry=+0,175` vs. `IC_direcional=-0,005` (razão 36,3x).
**Critério aponta pra identidade contábil CONFIRMADA** — a correlação de
E02f com o resultado é quase inteiramente carry, direcional é
essencialmente ruído. A anomalia da Faixa 1.6 (efeito do T0 aparecendo em
`directional_sharpe`) fica mais bem explicada por um efeito de SEGUNDA
ORDEM (a restrição muda quais barras são selecionadas, isso desloca
`directional_sharpe` indiretamente) do que por E02f carregar informação
direcional própria — reduz a prioridade do controle de sinal aleatório
(ainda não rodado, mas menos urgente à luz disso).

**Q2, medição 4 — regime one-hot na matriz.** Confirmado presente
(`DESIGN_COLUMNS = T1_FEATURE_IDS + REGIME_DUMMY_COLUMNS`,
`src/models/alpha.py`). **Critério aponta pra**: o problema não é
informação ausente — é peso baixo (gain médio ~0,95%) relativo às 10
features contínuas.

**Q2, medição 5 — confiança ortogonalizada contra volatilidade
(`C07_vol_pctile_expanding`).** Contaminação CONFIRMADA e forte:
Spearman(confiança, vol)=+0,239 long / +0,101 short, p≈0 nos dois.
Decil da confiança ORIGINAL: ρ=0,139 (p=0,70 long), ρ=-0,20 (p=0,58
short) — bate com o achado da Faixa 1 (não ordena). Decil da confiança
RESIDUALIZADA (removida a componente linear de vol): ρ=0,164 (p=0,65
long), ρ=+0,19 (p=0,60 short) — **continua sem ordenar, praticamente sem
mudança no p-valor**. **Critério aponta pra NÃO consertável por essa
via** — a contaminação por vol é real e mensurável, mas removê-la
(residualização linear simples) não revela um sinal de confiança
escondido. Ressalva: é diagnóstico global de uma variável, não uma
residualização robusta/não-linear por fold — não fecha a porta de
vez, só refuta a hipótese mais simples.

**As 3 medições pendentes do turno anterior, resolvidas:**
- **R2 por ano**: NÃO é viés estrutural uniforme nem puro risco de cauda
  de um ano só — varia bastante: 2020/2021 fortemente negativos (`directional_
  sharpe` -3,38/-4,44), 2022-2025 majoritariamente positivos (pico +7,36
  em 2025), 2026 parcial volta fortemente negativo (-8,79). Os piores
  anos (2020, 2021) coincidem com os anos de MAIOR prevalência de R2
  (14,9%/21,3%) — sugestivo de que R2 piora quando é mais dominante, não
  só "acontece mal às vezes".
- **Distribuição de feature R2 vs. tendência (proxy de SHAP-por-regime,
  não SHAP real — Boosters não persistidos, exigiria retreino)**: a
  hipótese anterior ("features vol-sensíveis ficam mais extremas em R2")
  **NÃO se confirma** — nas 4 features de maior gain, TREND (R3/R4) tem
  desvio-padrão e p90 iguais ou MAIORES que R2, não menores. Corrigindo
  a própria especulação de duas rodadas atrás: o mecanismo de por que o
  modelo dispara mais em R2 não está explicado por extremos univariados
  de feature — pode ser a dummy de regime (baixo peso, mas não-zero),
  interação entre features, ou limiar de split específico, não
  investigado além disso aqui.
- **NOFILL × tercil de custo dentro de R2**: confirma a hipótese do
  usuário — `rate_nofill` cai monotonicamente com o custo
  (LOW_COST=19,9%, MID_COST=10,9%, HIGH_COST=4,1%) — o tercil de MENOR
  custo relativo ao ATR é onde o preenchimento falha mais dentro de R2.

**Medição 6 (MFE por regime) — deliberadamente NÃO rodada.** Exige
re-caminhar `mark_1m` por trade (computação nova, não reuso de coluna já
existente como as outras 8). Desenho recomendado se for feita: estender
`build_labels` pra persistir `mfe_atr_units` no mesmo laço que já varre
`path_high`/`path_low`, não recomputar à parte.

### Síntese — aplicando o critério pré-registrado

**Q1: mais consistente com beta + regularização do que com edge
direcional limpo.** R3 é 86% concentrado em "comprado durante alta", a
fatia contrária é neutra; B2 (sem seletividade nenhuma) já lucra mais em
R2 do que o Alpha SELETIVO no mesmo regime, invertendo a expectativa; e
E02f — a peça do T0 mais citada como "achado positivo real" — é
majoritariamente carry, não direção. Nenhuma medição isolada fecha o
caso, mas as três apontam na mesma direção.

**Q2: não consertável pela via mais simples (remover vol linear).** A
contaminação existe e é forte, mas removê-la não recupera ordenação.

**Nenhuma decisão de arquitetura foi tomada a partir disso** — `monotone_
constraints` intocado, nenhum filtro de regime implementado, T0 e a
variante do short continuam NÃO canônicos (Faixa 1.6). A leitura acima é
a aplicação do critério já declarado, não uma conclusão nova sobre o que
fazer — essa decisão é do Manager.

### Extensão — gap Alpha-menos-passivo por lado × regime (2026-08-09,
pedido pós-síntese)

Pergunta mais fina que a original: não "o Alpha bate um nulo aleatório",
mas **"a SELEÇÃO de entrada do Alpha bate simplesmente ficar exposto o
tempo todo, no MESMO lado, no MESMO regime?"** — `directional_sharpe`
seletivo do Alpha MENOS Sharpe de exposição contínua (`entry_price_
limit` bar-a-bar, marcado pelo regime de origem, os dois lados
derivados do mesmo `bar_ret`, short = long invertido).

| lado | regime | Alpha (seletivo) | passivo (contínuo) | gap |
|---|---|---|---|---|
| long | R1 | +0,25 | -0,01 | +0,27 |
| long | **R2** | **-2,52** | **+1,53** | **-4,05** |
| long | R3 | +4,35 | +0,21 | +4,14 |
| long | R4 | +2,00 | +0,36 | +1,63 |
| short | R1 | +1,19 | +0,01 | +1,18 |
| short | R2 | +1,22 | -1,53 | +2,75 |
| short | R3 | +1,73 | -0,21 | +1,94 |
| short | R4 | +0,28 | -0,36 | +0,64 |

**Achado mais preciso desta investigação inteira**: `long × R2` é o
ÚNICO gap negativo grande da tabela — e não por falta de oportunidade
(o passivo ali era o TERCEIRO melhor da tabela inteira, +1,53), mas
porque a SELEÇÃO do Alpha escolhe especificamente momentos ruins dentro
de um regime que, sem seleção nenhuma, teria sido bom. Isso é diferente
de "ausência de edge" — é seleção ATIVAMENTE prejudicial, um alvo mais
cirúrgico de investigação do que "R2 é ruim".

**Short bate o passivo em TODOS os 4 regimes**, sem exceção — o achado
mais consistente e robusto da rodada. Mas partido por direção de
tendência (mesma técnica da Medição 1, agora nos 4 pares lado×regime
R3/R4): short-R3 tem 89,6% do book em "short durante baixa" (trivial,
dir_sharpe +1,73), só 10,4% em "short durante alta" (contrário, fraco,
+0,30, n=506); short-R4 tem 73,6% em "durante baixa" (+1,42), 26,4% em
"durante alta" (**-1,92**, negativo). Long-R4 é menos concentrado que
long-R3 (59%/41% em vez de 86%/14%), mas a fatia contrária (compra
durante baixa) continua negativa (-0,59).

**Leitura, não conclusão**: o padrão de concentração é PARECIDO nos dois
lados (a maior parte do book está no lado "trivial"/a-favor-da-tendência
em ambos) — então o gap positivo do short não é reversão pura tanto
quanto RECONHECIMENTO de regime/tendência aplicado à decisão de lado
(saber quando NÃO ficar exposto compra mais do que saber prever
reversão). Isso ainda bate o passivo de forma robusta e consistente —
não é nada, mas é um tipo de skill mais estreito (filtro adaptativo)
do que "mean reversion" como a justificativa original das features
(A05/B01/D06f, forçadas -1) sugeria.

**Verificação**: 13 testes (4 novos: espelho short do B2, gap positivo/
negativo/None, join do split lado×regime), `ruff`/`mypy` limpos,
`banned_patterns` sem violação nova, suíte completa (793 rápidos +
xfails esperados) passa.

## Faixa 2 — caminho B com critério de encerramento (2026-08-09)

Decisão do Manager após a Faixa 1.7 (Q1/Q2 negativos para o long): uma
tentativa estrutural nos dois parâmetros definidos por erro e nunca
corrigidos (T1=10 features quando N_eff medido no Sprint 6 suporta 65-163;
`tp_atr_mult`/`sl_atr_mult` herdados do V2, nunca varridos) — critério de
encerramento C1/C2/C3 pré-registrado, aplicado por script na FASE 3. Módulo
novo `src/analysis/faixa2_caminho_b.py`, resultado em
`experiments/faixa2_caminho_b.json`.

### FASE 0 — pré-requisitos

**F0.1 — N_lifetime auditado.** `audit/n_lifetime.yaml::counter` 5 → **23**
(ids 6-9, delta +18): 7 comparações lado×regime da Faixa 1 (D2 por decil —
8 blocos existiam, 1 [long/R1] saiu 100% insuficiente, então 7 produziram
estatística), 8 células direcionais da Faixa 1.5 Bloco 2
(`stratified_headlines.by_side_regime`), 2 escolhas do subconjunto
congruente/incongruente da Faixa 1 (uma por lado), 1 split direcional de R3
da Faixa 1.7. Escopo explicitamente PARCIAL — não inclui as demais
medições exploratórias da Faixa 1.7 (B1/B2, IC carry/direcional, R2 por
ano, distribuição de feature, extensão do gap por lado×regime), por
instrução literal da task; nota deixada no próprio YAML para reabrir se o
Manager quiser exaustividade completa.

**F0.2 — orçamento de fees por cenário** (teto: 662,7 trades/ano, ponto
central corrigido da Faixa 1.6):

| cenário | paths que excedem | razão média vs. orçamento |
|---|---|---|
| sistema atual (long+short) | 5/5 | 1,69x |
| só short | 1/5 | 0,81x |
| long sem R2 | 1/5 | 0,68x |
| só short + long sem R2 | 5/5 | 1,49x |

Short sozinho e long-sem-R2 isolados cabem no orçamento na maioria dos
caminhos; a COMBINAÇÃO dos dois ainda excede em todos — remover só R2 do
long não é suficiente para o sistema caber no orçamento de fees sozinho
(threshold/T1 têm que fazer parte da conta, não só a exclusão de regime).

**F0.3 — declaração de escopo do fill**, anexada a todo relatório desta
Faixa: todos os números derivam de fill otimista do Label Engine; a única
janela verificável (2023-05→2024-03, 10,5 de 6,5 anos) teve
direcional+carry NEGATIVOS nos dois gates, diferente do pooled positivo;
direção do viés fora da janela é DESCONHECIDA, não "sempre otimista".

### FASE 1 — diagnósticos (sem retreino)

**D1 — taxa base direcional + lift + qui-quadrado, por regime.** O achado
mais preciso desta fase: em **R2 o lift do long é 1,02 (não-significativo,
p=0,18)** — o modelo NÃO segue a tendência de 48 barras em R2 de forma
detectável, bem diferente de R3 (lift 1,72, p≈0) e R4 (lift 1,35,
p≈3,7e-137). O antipadrão de R2 não é "segue a tendência errada" — é
"não segue tendência nenhuma", mecanismo genuinamente distinto do resto do
livro. Short tem lift significativo em TODOS os regimes (1,22 a 1,93,
todos p<1e-30).

**D2 — long×R2, selecionado vs. visto-e-não-disparado.** `bars_in_regime`
(posição no ciclo do regime) é a única variável testada com efeito
detectável: selecionado tem média 20,1 barras dentro do regime contra
18,7 do não-selecionado (KS p=1,1e-5, mas Cohen's d=0,08 — estatisticamente
real, materialmente pequeno). As 10 features T1 (KS+Cohen's d) não mostram
divergência de distribuição maior que ruído — **a hipótese de "features
mais extremas" continua refutada**, agora também dentro de R2 (não só
R2-vs-tendência, já refutado na Faixa 1.7). O que diferencia trade
selecionado de trade ignorado dentro de R2 permanece sem explicação
univariada — candidato a interação/limiar de split específico, não medido
aqui.

**D3 — MFE por regime e lado** (`mfe_atr_units`, coluna nova persistida em
`labels/v1/labels.parquet` — `src/labels/triple_barrier.py` estendido no
mesmo laço que já varria `path_high`/`path_low`, `config_hash` idêntico ao
anterior, `b281a18954e224ef`, 462.682 linhas, nada mais mudou).
**[DESATUALIZADO 2026-08-23]** `b281a18954e224ef` deixou de ser o
`config_hash` real de `labels/v1` — predatava 5 migrações de schema do
hash (`AG-005`/`031`/`042`/`116`) e foi reprocessado, ver `AG-140`
adiante nesta mesma tabela cronológica e `PLANO_MESTRE_PRINCE2.md
§15.24-F`. **Achado
que refuta a hipótese original da task**: a mediana de MFE fica em
1,27-1,40 ATR em TODOS os 8 blocos lado×regime — R2 NÃO é
sistematicamente pior que os outros regimes nesta dimensão (long-R2:
mediana 1,36; long-R3: 1,34; long-R4: 1,27). 60-65% de TODO trade
preenchido, em qualquer regime/lado, nunca alcança 2,0 ATR de excursão
favorável — `tp_atr_mult=2,0` parece ambicioso demais estruturalmente,
não seletivamente em R2. Isto pesa diretamente na grade de E1 abaixo.

**D4 — E10f como candidata.** Estabilidade (`|IC|×consistência²`) baixa
nos dois lados (long 0,0054, short 0,0013) — mesma ordem de grandeza da
fragilidade já medida para E02f. Correlação pooled com B07 (eixo de
estrutura já em T1 indiretamente, via Regime Engine) é praticamente nula
(ρ=0,028, n=206.624) — E10f não é redundante com B07, mas também não
mostra sinal individual forte. Não decide inclusão/exclusão (por
instrução da task).

**Verificação**: 36 testes em `test_labels_triple_barrier.py` (era 33 — 3
novos para `mfe_atr_units`: TP bate >= `tp_atr_mult`, TIME usa a janela
inteira, NOFILL fica nulo), suíte completa 832 passam (era 793), `ruff`/
`mypy` limpos, `banned_patterns` sem violação nova (3 literais novos
justificados com `# noqa: magic-number`, mesma convenção do resto do
repo), 6/6 import-linter.

### FASE 2, E1 — varredura de barreiras 3x3 por lado (§18.7.1 pago)

Grade DECLARADA antes da busca (B20): `tp_atr_mult ∈ {1,5·2,0·2,5}` x
`sl_atr_mult ∈ {1,0·1,5·2,0}`, independente por lado — 18 variantes.
Módulo novo `src/labels/barrier_sweep.py` — resolução de barreira
vetorizada via `numpy.lib.stride_tricks.sliding_window_view` (§18.7.1,
"nunca implementado" até esta rodada). Resultado em
`experiments/faixa2_e1_barrier_sweep.json`. `n_lifetime`: 23 → **41**
(`audit/n_lifetime.yaml`, id 10, delta +18).

**Insight que tornou a varredura barata**: o FILL (se/quando a ordem
limite preenche) não depende de `tp_atr_mult`/`sl_atr_mult` — só de
`limit_price`/`fill_timeout_bars`, ambos fixos na varredura. Reusado
direto de `labels/v1/labels.parquet` (`t_entry`/`entry_price_fill`/
`atr_at_t0`, qualquer config), a varredura só recalcula TP/SL/TIME por
célula. Resultado: **18 células em 35,8s** (vs. ~426,5s medidos em
`cost_surface.py` para um grid comparável 9-células-ambos-os-lados com o
motor em laço — mais de 10x mais rápido), sem re-rodar o Label Engine.

**Correção verificada, não assumida.** `resolve_barriers_vectorized`
reproduz `triple_barrier.build_labels` byte-a-byte em 5 cenários
sintéticos (TP/SL/TIME/desempate-mesmo-candle/múltiplos-trades) e sobre
2024 completo real (`ret_net` máx diff < 1e-6, zero divergência de
`barrier_hit`) — `tests/unit/test_labels_barrier_sweep.py`, 7 testes.

**Sanidade do centro da grade — PASSOU.** `tp=2,0/sl=1,5` (config de
produção) reproduz a distribuição pooled do Sprint 6 com
`max_abs_diff=2,3e-5` (TP 36,54% vs. 36,54% referência; SL/TIME/NOFILL
igualmente exatos).

**Achado estrutural, população INCONDICIONAL (todo trade rotulado, sem
seleção de modelo — nenhum modelo foi retreinado nesta rodada).** `edge_
atr_units_mean` (`ret_gross/atr_at_t0`) é NEGATIVO nas 18 células, os dois
lados — consistente com o B1 já medido na Faixa 1.7 (todo regime negativo
sem seletividade). Isto não é um achado novo sobre existir edge ou não —
é a confirmação de que a geometria de barreira SOZINHA, sem o Alpha
selecionando quando entrar, nunca foi desenhada para ser lucrativa; a
pergunta de C1/C2 (FASE 3) exige a seleção do modelo, que a FASE 2 E1 não
recria.

**Trade-off geometria mensurável**: `tp=1,5` reduz TIME para 1,2-6,8% do
book (barreira mais fácil de alcançar) contra 4,8-15,6% em `tp=2,5`; custo
médio por trade fica entre 5,4 e 6,2bps, subindo com `tp_atr_mult` e caindo
com `sl_atr_mult` (mais SL/TIME = mais saída taker, mas TP mais apertado
tem menos chance de sair maker também — os dois efeitos interagem).
~~Estes números alimentam a escolha de célula pra retreinar em E2/FASE
3~~ — **superado pela conclusão abaixo: nenhuma célula deste grid vira
configuração vencedora.**

**Verificação**: 7 testes novos (`test_labels_barrier_sweep.py`), suíte
completa 838 passam (era 832), `ruff`/`mypy` limpos, `banned_patterns` sem
violação nova, 6/6 import-linter.

### Conclusão do E1 e correção de escopo (Manager, 2026-08-09) — geometria de barreira NÃO é o gargalo

**Extensão do grid (proposta em pré-E2 (1)): NEGADA.** `n_lifetime` NÃO
gasta os +8 propostos — a proposta fica registrada como avaliada e
rejeitada, não como pendente.

**A matemática que fecha o caso.** Edge necessário pra empatar o custo
round-trip: `cost_frac / atr_pct_mediano`. Com o custo médio medido
(~5,76bps) e o ATR mediano citado na proveniência de
`adverse_selection_wr_cost_per_bp` (`constants.yaml`, 0,305% a 15m):
`0,000576 / 0,00305 ≈ 0,189 ATR`. **Verificado nesta rodada com o ATR
mediano recalculado sobre o dataset completo atual (0,3592%, discrepância
de fonte registrada, não escondida): `0,000576/0,003592 ≈ 0,160 ATR`** —
os dois pontos de referência (0,160 a 0,189) convergem na mesma ordem de
grandeza. **A melhor célula do grid inteiro (`long tp=1,5/sl=2,0`) dá
edge médio de 0,028 ATR — entre 15% e 18% do necessário**, não uma
diferença de ajuste fino.

**Contraste com a população JÁ SELECIONADA (Alpha atual, barreiras
antigas).** `long×R3`, população selecionada e preenchida: edge médio
verificado nesta rodada = **0,226 ATR** (Manager citou 0,200 — mesma
ordem de grandeza, ~106-113% do breakeven pelos dois cálculos) —
CONFORTAVELMENTE acima do breakeven. **Ressalva não descartável**: a
MEDIANA dessa mesma população é ≈ -0,002 ATR (essencialmente zero/
levemente negativa) — a distribuição é fortemente assimétrica, o edge
médio positivo é puxado por uma cauda de vencedores grandes, não pelo
trade típico. Isso não muda a conclusão do Manager (o gap de 0,13-0,16
ATR entre o que a geometria sozinha entrega e o que a SELEÇÃO já entrega
é real e grande de qualquer forma), mas é uma nuance a não perder ao
citar "106%" como se fosse robusto ao trade mediano.

**Reforço estrutural**: a varredura 3×3 mostrou amplitude de CENTÉSIMOS
de ATR entre células (ex. long: -0,009 a -0,082 de edge médio); a lacuna
a fechar é de décimos. Nenhuma extensão de grade plausível fecha essa
lacuna por geometria de barreira sozinha. `tp_atr_mult < 1,35` cai abaixo
da mediana de MFE medida em D3 (1,27-1,40 ATR conforme o bloco) — barreira
ali não é só "mais difícil", é estruturalmente inalcançável com
frequência maior, elevando o win rate de breakeven exigido.

**Conclusão registrada**: a geometria de barreira não é o gargalo do
sistema. O gargalo está na SELEÇÃO (o que o Alpha escolhe operar), não em
qual múltiplo de ATR define TP/SL.

**Correção de escopo do E1 — limitação de desenho, não resultado.** E1
foi varrido sobre a população INCONDICIONAL (todo trade rotulado, sem
seleção de modelo) — `frac_tp`/`frac_sl`, e portanto `edge_atr_closed_
form`, são estimados sobre essa população, mas a realidade operacional é
CONDICIONAL à seleção do Alpha (que já muda a composição de barreira
tocada, como toda a Faixa 1.x mediu repetidamente). **`tp=1,5` NÃO é uma
configuração vencedora** — é o ótimo dentro de um espaço de busca com a
premissa errada (população errada). O ótimo de barreira real só pode ser
recomputado DEPOIS de E2/E3, sobre a população SELECIONADA pelo modelo
retreinado — registrado aqui como limitação de desenho do E1, a corrigir
na próxima rodada de varredura (se houver), não como um achado a carregar
adiante.

### Pré-E2 — 3 medições pedidas pelo Manager antes de liberar E2 (2026-08-09)

E2 (ampliar T1) segue PAUSADO por instrução explícita — as 3 medições
abaixo são pré-requisito, não abertura de escopo. Resultado completo em
`experiments/faixa2_caminho_b.json` (itens 1 e 3) e
`experiments/faixa2_e2_prereq_permutation_importance.json` (item 2).

**(1) Edge em unidades de ATR por célula do E1, por lado e por regime —
forma fechada, não `directional_sharpe` incondicional.** `edge =
frac_tp(regime) x tp − frac_sl(regime) x sl`. Achado central: a melhor
célula (média dos 4 regimes) fica em `tp=1,5` (a BORDA INFERIOR do grid
original) nos dois lados — e por regime, `tp=1,5` vence em 7 dos 8 blocos
lado×regime (só `short×R1` prefere `sl=1,0` em vez de `sl=2,0`, mas ainda
com `tp=1,5`). `long×R2` é a única célula com edge positivo do lado long
(+0,028 em `tp=1,5/sl=2,0`). Gatilho do critério pré-registrado do
Manager disparado (`toca_borda_inferior_tp=true`) — proposta de estender
o grid para `tp_atr_mult ∈ {1,0 · 1,25}` **AVALIADA E NEGADA pelo Manager
(ver seção "Conclusão do E1" acima)**: mesmo a melhor célula (0,028 ATR)
fica a ~15-18% do edge necessário pra empatar o custo (~0,16-0,19 ATR) —
a lacuna é de ordem de grandeza maior que a amplitude do grid inteiro
(centésimos), estender não fecharia. `n_lifetime` NÃO gastou os +8.

**(2) Importância por permutação (AUC drop) + resolução dos 2 pares de
ortogonalidade.** Retreino em memória da Camada 1 (mesma config/seed de
`alpha_c1_v1`), NUNCA persistido em disco — verificado **bit-idêntico**
contra o modelo de produção (0 `side_hat` divergente, `max_confidence_
abs_diff=0.0` em 1.147.280 linhas comparadas) antes de confiar em
qualquer número, `n_lifetime += 0` (é o mesmo modelo já contado, não uma
variante nova). Achado notável: `E27f_cost_atr_ratio` tem importância por
permutação **NEGATIVA** (-0,0065 pooled) — embaralhar seus valores
MELHORA levemente o AUC do modelo, apesar de ser uma das features de
maior `gain`/uso em splits — divergência clássica entre as duas métricas
(gain mede USO na árvore, permutação mede CONTRIBUIÇÃO preditiva real).
Resolvendo os pares pela regra pedida (descarta o de MENOR importância):
`E27f_cost_atr_ratio` descartada (perde para `C07_vol_pctile_expanding`,
+0,0033 vs -0,0065) e `A13_dist_ema48_atr` descartada (perde para
`B01_rsi_14`, +0,0016 vs +0,0019, margem pequena). `hhi_efetivo`:
**0,191 → 0,179** (10→8 features) — reproduz exatamente o
`mean_hhi_effective` já persistido em `alpha_layer1_report.json`
(cross-validação da própria metodologia). Nenhuma promoção/remoção de T1
foi aplicada em produção — isto é medição para quando E2 for liberado.

**(3) Configurações viáveis de orçamento, por path, sem escolher.**

| cenário | paths viáveis | totalmente viável? |
|---|---|---|
| sistema atual (long+short) | 0/5 | não |
| só short | 4/5 (falha path 1, razão 1,05x) | não |
| long sem R2 | 4/5 (falha path 3, razão 1,04x) | não |
| só short + long sem R2 | 0/5 | não |

Nenhuma das 4 configurações já testadas cabe no orçamento em TODOS os 5
caminhos — "só short" e "long sem R2" isolados chegam perto (1 path cada
falha por margem pequena, 1,04-1,05x), a combinação dos dois falha em
todos. Emitido sem decidir entre eles.

**Correção de prioridade (Manager, 2026-08-09), com uma discrepância
numérica verificada e corrigida.** Instrução do Manager: as falhas de
1,04-1,05x de "só short"/"long sem R2" não devem ser tratadas como
restrição real ainda, por serem menores que a inconsistência do
threshold efetivo já medida — citando "quantil efetivo 0,743 a 1,000
entre paths, Faixa 1.5 Bloco 3". **Verificado nesta rodada contra
`experiments/faixa1_5_prerequisites.json` (dado atual, não de memória):
o valor 0,743-1,000 é o NÚMERO COM BUG (quantil-de-um-quantil, já
documentado e corrigido na Faixa 1.6 Bloco 2) — o valor CORRIGIDO,
persistido hoje, é 0,554-0,599** (5 caminhos: 0,5537 / 0,5619 / 0,5872 /
0,5986 / 0,5575), uma dispersão relativa de ~8%, não ~35% como o número
citado sugeriria. Isso enfraquece a comparação quantitativa (8% vs. a
margem de 4-5% do orçamento é a mesma ordem de grandeza, não claramente
"menor") — mas a decisão operacional do Manager (corrigir o threshold
antes de remedir o orçamento, não tratar essas duas falhas como bloqueio
ainda) permanece válida por si só, não depende do número exato para fazer
sentido como ordem de prioridade. Registrado aqui para não perpetuar o
número desatualizado. **A combinação "só short + long sem R2" falhando
5/5 continua de pé como restrição real** (margem de 18-67%, ainda bem
maior que a dispersão do threshold em qualquer uma das duas leituras).

### FASE 2, E2 — passe de pesquisa sem curadoria, 70 candidatas T2 (2026-08-09)

Liberado pelo Manager sem curadoria (ver "Conclusão do E1" acima): "todas
as candidatas T2 do §2.2-2.12 em passe de pesquisa (sem registry/
paridade), ranquear por ortogonalidade incremental contra o T1 corrente,
parar em `hhi_efetivo` de 12-15... conta como 1 trial, não um por
feature." Resultado completo em `experiments/faixa2_e2_research.json`.

**Escopo computável, medido antes de escrever qualquer candidata**
(`src/features/_sources_research.py`, `src/features/research_t2.py`):
grupos A (retorno/preço), B (momentum/reversão), C (volatilidade), D
(volume/fluxo), E (funding/OI/basis) e K (temporal/calendário) — todos
com dado real disponível. H (on-chain) parcial, com aviso de cobertura
(granularidade diária, ~96 barras de 15m constantes por observação; série
com 75 dias de defasagem na cauda, 2026-05-24). F excluído por decisão já
tomada (quebra de RPI, §2.7.1). G (opções) e I (macro) sem dado. J
excluído por desenho (§5.8, Meta-exclusive). Deferidos dentro dos grupos
computáveis, por razão específica: A16/A17/B12 (dependem de fonte ainda
não mapeada), C08 (percentil rolante ingênuo ≈ 8 bilhões de comparações
sobre 35.064 barras, sem primitiva O(n log w) disponível — não é
"esqueceu", é infeasível como escrito), D11f/D13f (agregação por
percentil/comprimento-de-sequência a nível de trade dentro do bucket de
15m, não é `SUM`/`GROUP BY` simples como D12f), E23f (não mapeada).
**70 candidatas efetivamente computadas e avaliadas** (72 - 2 já
descartadas no pré-E2 (2), `E27f_cost_atr_ratio`/`A13_dist_ema48_atr`,
explicitamente excluídas da re-seleção — decisão fechada por um critério
diferente, ortogonalidade não reabre importância por permutação).

**Correlação com o proxy de vol, medida e reportada por candidata**
(orientação explícita do Manager, dado que `E27f` mostrou o vetor
"saturado de volatilidade"): `C15_iv_rv_spread` correlaciona -0,80 com
`C07_vol_pctile_expanding`, `C03_realized_vol_48` +0,79, `C02_atr_20_pct`
+0,76 — confirma a preocupação como MEDIÇÃO real, várias candidatas de
volatilidade são de fato quase-redundantes com o proxy já em T1.

**Seleção gulosa, `n_eff_factors` 6,479 → 15,825 em 10 passos, alvo
[12,15] atingido no passo 10** (não estourou o teto): `A12_gap_pct`,
`E05f_time_to_funding_h`, `E12f_price_oi_divergence`,
`K08_days_since_halving`, `H01_exchange_netflow_z`, `E11f_oi_change_1d`,
`A08_upper_wick_ratio`, `K02_dow_sin`, `D04f_volume_accel`,
`E17f_retail_vs_top_spread`. **Nenhuma das 10 selecionadas está sinalizada
como saturada de vol** (`vol_saturated_flags_in_selection: []`,
threshold de correlação 0,60 com `C07`) — a preocupação do Manager era
real e mensurável (parágrafo acima), mas o algoritmo de ortogonalidade
já a penaliza estruturalmente: candidatas de vol quase-redundante
(`C03`/`C02`/`C15`/`C04`/`C05`/`C09`/`C12`) nunca entram porque adicionar
uma feature correlacionada não move `n_eff_factors`, e a seleção gulosa
sempre prefere quem move mais. O aviso não foi ignorado — foi confirmado
como já resolvido pelo próprio critério de seleção, não por curadoria
manual.

**Nada disto é T1 de produção.** `registry.yaml`/`T1_FEATURE_IDS` não
foram tocados — é medição de ranking para o E3 (triagem in-fold do §5.4)
decidir quais das 10 sobrevivem fora da amostra, por fold. `n_lifetime`
id 11, delta=1 (não 70) por instrução explícita do Manager — ver
`audit/n_lifetime.yaml`. Contador: 41 → **42**.

### Correção do Manager pré-E3 — ortogonalidade recompensa estrutura, não informação (2026-08-09)

O Manager apontou um defeito real no próprio critério de E2: ortogonalidade
é cega a CONTEÚDO — uma variável determinística (função pura do relógio)
é ortogonal a tudo por construção, sem carregar nenhuma informação de
mercado, e ainda assim conta ponto cheio de `n_eff_factors`. Pediu 3
ajustes antes do E3 e citou um cálculo (+0,967/+0,973/+0,977 somando
2,92 de 9,35, ~31% do ganho) para quantificar o efeito.

**Verificação do cálculo contra `experiments/faixa2_e2_research.json`
(`selection_history`), por instrução própria do CLAUDE.md de medir antes
de aceitar qualquer número, inclusive os do Manager.** O ponto
qualitativo está correto e a proporção é aproximadamente essa — mas os
três deltas citados (0,967/0,973/0,977) não são das três candidatas
determinísticas por construção. São dos **três primeiros passos da
seleção gulosa** (`A12_gap_pct` +0,967, `E05f_time_to_funding_h` +0,970,
`E12f_price_oi_divergence` +0,972) — e `A12_gap_pct`/`E12f_price_oi_divergence`
são features de MERCADO reais (gap de preço, divergência preço×OI), não
determinísticas. As três REALMENTE determinísticas por construção entre
as 10 selecionadas são `E05f_time_to_funding_h` (passo 2, +0,970),
`K08_days_since_halving` (passo 4, +0,940) e `K02_dow_sin` (passo 8,
+0,921) — soma **2,831**, não 2,92; **30,3%** do ganho total (9,347), não
"~31%" por coincidência de arredondamento, não por ele ter acertado a
composição. **Leitura correta do ganho de mercado: ~6,52 (9,347 − 2,831),
não ~6,4.**

**Achado adicional, não pedido mas decorrente da verificação**: o defeito
é mais estrutural do que o exemplo do Manager sugere. `A12_gap_pct` e
`E12f_price_oi_divergence` — features de mercado genuínas — também têm
delta ~0,97, maior que os das determinísticas (~0,92-0,97). Isso é porque
o ganho marginal de `n_eff_factors` (razão de participação) é maior nos
PRIMEIROS passos independente do conteúdo informacional — é propriedade
da métrica (adicionar 1 eixo ortogonal a um conjunto pequeno move mais a
razão de participação que adicionar o mesmo eixo a um conjunto já maior),
não das features específicas. Ou seja: não é só "determinística ganha de
graça" — é "cedo ganha de graça", determinística ou não. Isso reforça o
ponto do Manager (ortogonalidade ≠ informação) além do que os 30,3%
capturam sozinhos, mas não muda nenhuma decisão desta rodada — registrado
para o desenho do E3 considerar.

**Os 3 ajustes, registrados como critério para o E3 (nenhum bloqueante,
nenhum rodado ainda — E3 não existe como módulo):**

1. **`K08_days_since_halving` — escrutínio prioritário.** Periodicidade de
   4 anos, ~1,6 ciclos na amostra (2020-01 a 2026-08), os dois ciclos
   observados com desfecho OPOSTO (ciclo 1: +519%; ciclo 2: pico em
   ~115k, volta a ~64k, -3%) — mesma fase de ciclo mapeando pra sinais
   contrários é sub-amostragem clássica, não estabilidade real. Critério
   registrado para quando o E3 rodar: IC estratificado por ciclo (PRE
   2024-04-19 vs POST), não promover se o sinal vier de um ciclo só.
2. **`H01_exchange_netflow_z` — latência verificada, CORRIGIDA nesta
   rodada.** Hipótese do Manager estava certa: os "75 dias de defasagem"
   eram CSV local desatualizado (`data/capacity/onchain/btc_coinmetrics.csv`,
   última linha 2026-05-24, arquivo baixado em 2026-08-04), não latência
   estrutural — verificado contra `community-api.coinmetrics.io`, que
   publica com ~1 dia de atraso real. Arquivo atualizado via download
   direto (2.443 linhas, 2019-12-01→2026-08-08; original preservado como
   `btc_coinmetrics.csv.stale_2026-05-24.bak`, fora do git —
   `data/capacity/onchain/` é gitignored). Passo de pesquisa E2
   RE-RODADO com o dado corrigido para confirmar robustez: seleção final
   IDÊNTICA, `n_eff_factors` 15,825459850990606 → 15,825275447201294
   (Δ -0,0002, ruído) — `n_lifetime` id 12, **delta=0** (confirmação, não
   busca nova; mesmo tratamento do bit-idêntico de pré-E2 (2)). O
   problema real que SOBREVIVE à correção, como o Manager já esperava, é
   a granularidade diária (~96 barras de 15m constantes por observação,
   reduz amostra efetiva e infla correlação serial) — registrado no
   `coverage_warnings` do relatório, agora medido dinamicamente a cada
   rodada em vez de citar uma data fixa (a mensagem antiga ficou FALSA
   silenciosamente assim que o CSV foi atualizado uma vez; a nova lê o
   último `_ts_ms` real do CSV a cada execução).
3. **`E05f_time_to_funding_h` e `K02_dow_sin` — mantidas, mas o E3 deve
   reportar a estabilidade das determinísticas SEPARADA das de mercado.**
   São ortogonais por construção; se sobreviverem à triagem in-fold do
   §5.4, o número de `estabilidade` (força × consistência²) precisa
   aparecer isolado antes de qualquer promoção a T1 de produção.

**Não feito, por instrução explícita — registrado como alternativa, não
como tarefa**: reexecutar a seleção com uma trava de `|IC|` in-fold como
piso. Duplicaria o que a triagem do §5.4 já faz in-fold, custaria +1
`n_lifetime`, e filtrar por IC marginal descartaria features que só
valem em interação (o próprio raciocínio do Manager para não pedir).

### FASE 2, E3 — Camada 2 implementada, ambientes de triagem esclarecidos (2026-08-09)

**Ambientes do E3 — por que 6, não 12** (resolvendo a inconsistência de
vocabulário que eu mesmo levantei antes de codificar). O PRD usa "regime
estrutural" para duas coisas de granularidade diferente: os 6 AMBIENTES
DE TRIAGEM de §5.4/§5.7 (`RANGE = R1∪R2`, `TREND = R3∪R4`, × tercil de
`cost_atr_ratio`) e os 4 REGIMES DE REPORTE R1..R4 de §5.11/Gate 4
("Sharpe > 0 em CADA regime R1..R4"). `src/models/environments.py` (já
existente, criado durante o Sprint 8, verificado linha a linha nesta
rodada) já resolvia isso corretamente — o "6 células" do PRD estava
certo, a citação paralela em R1..R4 é sobre outro eixo. Decisão do
Manager: **manter 6, corrigir o PRD** (não mudar o código). Duas razões
técnicas, não só terminológicas, para não ir a 12:
- R1..R4 já É estrutura × vol (`trend_state × vol_state`), e
  `cost_atr_ratio` é proxy de vol — cruzar de novo duplicaria o eixo de
  volatilidade consigo mesmo.
- `alpha_monotonic_consistency_min_envs` exige UNANIMIDADE (6 de 6,
  `constants.yaml`). P(unanimidade sob ruído puro) = 2×0,5⁶ = **3,125%**
  com 6 ambientes; com 12, 2×0,5¹² = **0,049%** — 64x mais restritivo. A
  12 células a triagem provavelmente não aprovaria NADA, indistinguível
  de "não há sinal" — perderíamos o experimento sem saber que perdemos.

`rpi_regime` (PRE/POST, quebra em 2025-11-20) **saiu da fórmula de
estabilidade, virou diagnóstico** (`stability.ic_by_rpi_regime`): a
dimensão foi desenhada para o Grupo F (microestrutura), que já saiu de T1
na v3.3 — nenhuma das 18 candidatas (T1-8 + E2-10) é microestrutura, a
dimensão perdeu o alvo. Cruzar mesmo assim fragmentaria os ~8-9 meses de
POST em fatias pequenas demais para Spearman estável. PRD corrigido
(§5.4) com as duas decisões e a matemática acima.

**Implementação** (`src/models/stability.py`, 9 testes unitários):
`estabilidade = forca × consistencia²`, denominador FIXO 6 nos dois
termos (mesma convenção já resolvida em `monotonic.py` para
`min_consistent_envs` — um ambiente sem dado não deve inflar nem força
nem consistência). Reusa `environments.assign_environments` e
`monotonic.compute_ic_by_env` — nenhum motor novo, só a fórmula do §5.4
em cima da mesma infraestrutura que §5.3 já usa e já tem teste. `limiar`
declarado em `constants.yaml::alpha_stability_screen_limiar` (classe A,
ASSUMED=0,02, sweep_range [0,01; 0,03], `review_by: sprint_11`).

**Resultado — rodado sobre os 15 splits REAIS do CPCV × 2 lados (30
células), não uma amostra** (`src/analysis/faixa2_e3_stability.py`,
`experiments/faixa2_e3_stability.json`, ~99s):

| feature | sobrevive (30) @0,01 | @0,02 | @0,03 |
|---|---|---|---|
| `C07_vol_pctile_expanding` (T1) | 30 | 30 | 30 |
| `D03f_volume_z_expanding` (T1) | 30 | 30 | 30 |
| `E02f_funding_z_expanding` (T1) | 23 | 13 | 0 |
| `E17f_retail_vs_top_spread` (E2) | 21 | 11 | 5 |
| `H01_exchange_netflow_z` (E2) | 17 | 11 | 5 |
| `E12f_price_oi_divergence` (E2) | 16 | 0 | 0 |
| `C06_vol_ratio_12_96` (T1) | 11 | 3 | 0 |
| `K02_dow_sin` (E2) | 11 | 2 | 0 |
| `E05f_time_to_funding_h` (E2) | 10 | 0 | 0 |
| `K08_days_since_halving` (E2) | 7 | 3 | 1 |
| `B01_rsi_14` / `D06f_taker_imbalance_z_48` (T1) | 7 | 0 | 0 |
| `E11f_oi_change_1d` / `A08_upper_wick_ratio` (E2) | 5 | 0 | 0 |
| `E10f_oi_change_z_48` (T1) | 1 | 0 | 0 |
| `A05_ret_vol_norm_4` (T1) / `A12_gap_pct` / `D04f_volume_accel` (E2) | 0 | 0 | 0 |

**Só 2 das 18 são robustas em TODA a vizinhança do sweep_range**:
`C07_vol_pctile_expanding` e `D03f_volume_z_expanding` — 30/30 em
0,01/0,02/0,03, sem exceção. Todo o resto é sensível ao limiar (ranking
embaralha entre as 3 colunas) — exatamente o tipo de "pico estreito" que
CLAUDE.md pede pra não tratar como resultado definitivo (varredura de
sensibilidade ainda pendente, formal, antes do Gate 3).

**Confirma a suspeita original do Manager, de um ângulo diferente**: das
10 candidatas do E2 (selecionadas por ORTOGONALIDADE, não por
estabilidade), só `H01_exchange_netflow_z` e `E17f_retail_vs_top_spread`
mostram sobrevivência não-trivial (37% em @0,02); as outras 8 — incluindo
as 3 determinísticas apontadas na correção acima (`E05f`, `K08`,
`K02_dow_sin`) — ficam em 0-10%. Ortogonalidade e estabilidade são
critérios genuinamente diferentes: o E2 mediu diversidade de eixo: o E3
mede se o eixo tem sinal consistente. A maioria das 10 tem o primeiro sem
o segundo. Do T1 atual (8), o quadro é parecido: só 2 de 8
(`C07`/`D03f`) são robustas; `E02f_funding_z_expanding` é forte mas
sensível ao limiar (23→13→0); os outros 5 T1 também caem a zero ou perto
disso na vizinhança alta do sweep.

**Diagnóstico PRE/POST** (`rpi_regime_diagnostic_pre_post`, pooled por
lado, fora da fórmula): nenhuma das 18 candidatas mostra inversão de
sinal PRE↔POST em nenhum dos dois lados — o IC muda de magnitude (ex.
`K02_dow_sin` no long: -0,002 PRE → -0,056 POST) mas não de direção.
Nenhum alarme, consistente com "nenhuma candidata é microestrutura".

**Nada disto é produção.** `registry.yaml`/`T1_FEATURE_IDS` intocados —
é ranking para decidir depois, junto com a varredura formal de
`alpha_stability_screen_limiar` (classe A, ainda pendente) e a FASE 3.
`n_lifetime` id 13, delta=1 (1 trial, mesmo raciocínio do E2). Contador:
42 → **43**.

### Pré-FASE 3 — 3 perguntas sobre o JSON do E3, sem retreino, sem n_lifetime (2026-08-09)

Pedido do Manager antes de liberar a FASE 3: caracterizar o E3 mais a
fundo usando só o que já foi computado (`experiments/
faixa2_e3_stability.json`, campos novos: `ic_by_env` por célula,
`env_sizes_by_cell`, `robust_survivors_ic_sign_by_env_and_side`,
`c07_d03f_pair_analysis`). Nenhum retreino, nenhum trial novo.

**(1) Sinal do IC de C07/D03f, por lado e por ambiente — decide a
interpretação do E3 inteiro.** Resultado: **negativo em TODAS as 6×2×15 =
180 combinações** para cada feature — unanimidade total, não só nos 6
ambientes por fold. `C07_vol_pctile_expanding`: mediana entre -0,057 e
-0,141 conforme o ambiente; `D03f_volume_z_expanding`: entre -0,021 e
-0,063. Confirma a hipótese do Manager NA DIREÇÃO certa — vol/volume alto
prediz retorno líquido PIOR — mas com uma correção relevante: **a
magnitude é quase simétrica entre long e short** (ex. `C07`
`RANGE_LOW_COST`: -0,1048 no long vs -0,1033 no short — praticamente
igual), não assimétrica. Isso confirma "vol alta piora a entrada nova,
nos dois lados igualmente" — o mesmo padrão de contaminação por
volatilidade já medido na Faixa 1.7 (ρ=0,24 confiança×vol) — mas SOZINHO
não explica a assimetria long-falha-em-R2/short-bate-passivo-em-4-regimes
que o Manager citou como possível consequência: se o efeito fosse
simétrico nos dois lados, ele não deveria gerar essa assimetria por si
só. A assimetria long/short precisa de outro mecanismo (ou de uma
interação entre vol e alguma outra variável), não decorre deste sinal
isolado.

**(2) Correlação C07×D03f + hhi_efetivo do par.** `ρ = 0,46` (Pearson,
pooled, 458.912 linhas), `n_eff_factors = 1,65` de um teto de 2,
`hhi_efetivo = 0,606`. **Não confirma "é um fator só"** — 1,65 está mais
perto do meio do intervalo [1,2] que de colapsar a 1. Há redundância real
(as duas se movem juntas quando o mercado está mais líquido/ativo — leitura
econômica plausível: mais volume tende a vir com mais volatilidade), mas
não ao ponto de serem intercambiáveis. As duas sobreviverem juntas na
triagem não é um artefato de estarem medindo a mesma coisa.

**(3) Poder da triagem — |IC| mediano por feature, ao lado da
sobrevivência.** Emitido (`summary_by_feature.median_abs_ic_by_env`),
tabela completa abaixo. Confirma o ponto do Manager: a maioria das 14
"zeros" tem IC mediano entre 0,004 e 0,021 — perto do limiar de força
necessário pra sobreviver com consistência unânime (`limiar/1,0² =
0,02-0,03`), não zero. **Correção de uma premissa do cálculo de poder do
Manager**: N por (fold, lado, ambiente) medido é **~22.891 (mediana),
não ~5.000** — a estimativa assumia `n_rows_train/6` igualmente
distribuído entre os 6 ambientes, mas RANGE e TREND não são
metade-metade da amostra (R1∪R2 vs R3∪R4 têm proporções bem diferentes,
ver `regime_counts` do Sprint 5: R1=46%, R2=11%, R3=30%, R4=10%). Com N
~4-5x maior que o assumido, o erro-padrão de Spearman (~1/√N) é ~2x
menor — a probabilidade de unanimidade de sinal para um IC populacional
pequeno e real é MAIOR do que a conta original sugeria, não menor. Ou
seja: os "zeros" são, se algo, mais informativos (mais prováveis de
refletir efeito genuinamente perto de nulo) do que a estimativa inicial
indicava — não menos.

| feature | sobrev./30 | \|IC\| mediano |
|---|---|---|
| `C07_vol_pctile_expanding` (T1) | 30 | 0,0889 |
| `D03f_volume_z_expanding` (T1) | 30 | 0,0479 |
| `E17f_retail_vs_top_spread` (E2) | 11 | 0,0259 |
| `E02f_funding_z_expanding` (T1) | 13 | 0,0214 |
| `K02_dow_sin` (E2) | 2 | 0,0204 |
| `H01_exchange_netflow_z` (E2) | 11 | 0,0203 |
| `E05f_time_to_funding_h` (E2) | 0 | 0,0152 |
| `E11f_oi_change_1d` (E2) | 0 | 0,0137 |
| `E12f_price_oi_divergence` (E2) | 0 | 0,0136 |
| `C06_vol_ratio_12_96` (T1) | 3 | 0,0136 |
| `B01_rsi_14` (T1) | 0 | 0,0129 |
| `K08_days_since_halving` (E2) | 3 | 0,0123 |
| `D06f_taker_imbalance_z_48` (T1) | 0 | 0,0094 |
| `A05_ret_vol_norm_4` (T1) | 0 | 0,0078 |
| `A08_upper_wick_ratio` (E2) | 0 | 0,0074 |
| `E10f_oi_change_z_48` (T1) | 0 | 0,0070 |
| `A12_gap_pct` (E2) | 0 | 0,0064 |
| `D04f_volume_accel` (E2) | 0 | 0,0041 |

**Declaração pedida sobre `min_consistent_envs`** (não varrida, só
declarada — o Manager pediu a posição antes de decidir se vale rodar):
**mantenho 6/6 (atual)**, não recomendo 5/6. Com 18 candidatas avaliadas
simultaneamente, o número esperado de "sobreviventes" por chance pura sob
ruído é `18 × FPR`: a 6/6 (FPR=3,125%) isso dá ~0,56 — sob 1, controlado;
a 5/6 (FPR=21,9%) dá ~3,9 — quase 4 das 18 aaprovariam por acaso, o que
contaminaria a leitura dado que só 2 sobrevivem hoje de forma robusta.
5/6 tornaria "sobreviver" quase não-informativo neste N de candidatas. Se
uma varredura for feita, o valor a testar não é o `limiar` de força (o
Manager já mostrou que ele não muda o veredito pras 2 robustas) — é
exatamente este, e a pergunta certa é "o FPR agregado esperado continua
< ~1 sobrevivente espúrio" pra qualquer valor considerado.

**FASE 3 continua em espera**, por instrução explícita, até estas 3
perguntas serem avaliadas pelo Manager. Nenhum `n_lifetime` gasto nesta
rodada (recomputação sobre o mesmo passe já contado no id 13, não uma
busca nova).

### Validação da análise do Manager sobre o E3 — "os zeros invertem, não faltam" (2026-08-09)

Manager pediu validação/aprimoramento (modo "ultrathink") da própria
leitura da Pré-FASE 3 acima, com metodologia de engenharia: não aceitar
a conta sem recomputar, verificar cada número citado como "dado que já
tínhamos" contra o artefato real. Três verificações independentes,
recomputadas do zero (não da memória):

**(a) Tabela esperado-vs-real do Manager (SE=1/√N, N=22.891, `p =
Φ(|IC|/SE)`, `esperado = 30·p⁶`).** Reproduzida ponto a ponto — todos os
8 valores citados batem exatamente (`C07`→30,0, `E17f`→30,0,
`E02f`→29,9, `K02_dow_sin`→29,8, `E05f`→28,1, `B01`→25,7, `A05`→14,0).
Metodologia sólida: `forca`/`median_abs_ic` (que usa `|IC|`) e
`consistencia` (que usa SINAL) são estatisticamente independentes o
suficiente para a comparação ser informativa, não circular.

**(b) Citações "dado que já tínhamos" — todas conferem, com precisão
maior que a citada.** Recomputado direto de `predictions/alpha/
alpha_c1_v1/predictions.parquet` (OOF) + regime real: taxa de disparo
long R1=**0,340%**, R2=**4,337%** → razão **12,76x** (Manager citou
"0,34% / 4,34% / 12,8x" — exato). TP rate long fired: R2=**28,35%**,
R3=**42,42%** (Manager citou "28,3% / 42,4%" — exato). R2 é
RANGE+vol-alta, confirmado em `src/regime/classifier.py` (`is_high_vol_raw
and not is_trend_raw -> R2`) — mas **R4 (TREND+vol-alta) dispara AINDA
MAIS** (long 4,27%, short 5,28%, medido nesta verificação, não citado
pelo Manager) — achado adicional que reforça o padrão "dispara mais em
vol alta" além do par R1/R2 citado.

**(c) Refinamento do "16 de 18 invertem"** — o achado central, testado
diretamente contra `ic_by_env` bruto (não só a via indireta SE/esperado).
Para cada feature, reorganizado por ambiente: sinal dominante DENTRO de
cada um dos 6 ambientes (agregando os 15 folds × 2 lados = até 30
valores por ambiente) e SE esse sinal dominante muda entre ambientes.
Resultado: **não é uniforme — dois padrões distintos, não um só**:

- **Ruído genuíno** (`A12_gap_pct`, `D04f_volume_accel`, e em grau menor
  `B01_rsi_14`): IC mediano perto de zero E fração de sinal perto de
  50/50 em CADA um dos 6 ambientes individualmente, não só no agregado.
  Aqui "instabilidade" é a leitura certa — não há estrutura pra
  recuperar.
- **Estrutura condicional a custo, real** (`K02_dow_sin`,
  `E02f_funding_z_expanding`, `E17f_retail_vs_top_spread`): sinal FORTE
  e consistente (77-83% dos folds concordam, não 50%) especificamente em
  ambientes de custo ALTO ou MÉDIO, mas fraco/misto em custo BAIXO — ex.
  `K02_dow_sin` em `TREND_HIGH_COST`: 27 de 30 negativos (90%,
  IC mediano -0,022); em `RANGE_LOW_COST`: 15/15 empatado. `E17f` em
  `RANGE_MID_COST`/`TREND_MID_COST`: 25 de 30 negativos (83%) nos dois;
  em `RANGE_LOW_COST`/`RANGE_HIGH_COST`: perto de empate ou até sinal
  oposto. Isso não é "sinal que inverte ao acaso" — é sinal cuja DIREÇÃO
  depende sistematicamente do ambiente de custo, exatamente o tipo de
  heterogeneidade que a fórmula de unanimidade do §5.4 (por desenho) não
  consegue creditar, mas que `E27f_cost_atr_ratio` como dimensão de
  ambiente já estava, em certo sentido, tentando capturar. Acaso pareça
  "zero" na triagem atual, mas seria candidato natural a um termo de
  interação (feature × tercil de custo) ou ao Camada 5 / Group DRO
  (§5.7, já no PRD, ainda não implementado) — que existe PRECISAMENTE
  pra tratar heterogeneidade entre ambientes sem descartar a feature.

**Conclusão refinada, não substitui a do Manager — precisa ela**: dos 16
"reprovados", pelo menos 3 (`K02_dow_sin`, `E02f_funding_z_expanding`,
`E17f_retail_vs_top_spread`) parecem ter sinal condicional REAL perdido
pela agregação, não ruído puro; pelo menos 2 (`A12_gap_pct`,
`D04f_volume_accel`) parecem ruído genuíno mesmo. Os outros ficam entre
os dois extremos, não caracterizados individualmente nesta rodada. A
tese central do Manager sobrevive e fica mais forte: a maioria das 18
não tem estabilidade INCONDICIONAL de sinal — só muda a explicação
de "por quê" caso a caso.

**Endosso confirmado, `min_consistent_envs` mantido em 6/6** — cálculo
do Manager (FPR agregado 0,56 vs 3,9 espúrios em 18 candidatas) é o
argumento certo, sem ressalva.

**Proposta do Manager — filtro de admissão por percentil de `C07`,
remedir sem retreinar**: desenho sólido, avaliado — **rodada** (ver
próxima entrada abaixo).

### Teste do C07 como acelerador — NÃO confirma a hipótese (2026-08-09)

Rodado conforme o desenho do Manager (`src/analysis/
faixa2_vol_accelerator_test.py`, `experiments/
faixa2_vol_accelerator_test.json`, ~38s), filtro sobre predições JÁ
EXISTENTES de `alpha_c1_v1` — SEM retreino:

1. `side_hat` recomputado como `argmax(p_long, p_short)` — threshold de
   confiança no mínimo que ainda produz sinal, gate de admissão único
   vira o percentil de `C07`.
2. Percentil calibrado A PRIORI só pelo orçamento (bisseção sobre
   `trades_per_year`, nunca sobre performance, evita B20):
   `P = 0,01077` (1,08% inferior de `C07`) — precisa ser MUITO mais
   restritivo que o "vol baixa" informal, porque remover o gate de
   confiança expõe ~100% das barras ao filtro (antes só ~1,89% chegava
   a disparar); `trades_per_year` resultante = 662,75, contra o
   orçamento de 662,71 (bate).
3. Braço de controle: corte aleatório com a MESMA contagem por path
   (4.676 cada), 1.000 sementes (`alpha_b1_n_seeds`/`alpha_random_seed`,
   mesma convenção de `run_b1_random_entry`).

**Resultado — não confirma a hipótese, numa direção específica e
informativa:**

| | `directional_sharpe` | `ret_net` médio (bps/trade) |
|---|---|---|
| Produção atual (gate de confiança) | **+0,879** | -2,82 |
| Filtro por `C07` (substituindo o gate) | -1,011 | -6,12 |
| Controle aleatório (mediana de 1.000 sorteios, mesmo N) | -0,696 | -6,71 |
| Filtro por `C07` vs. controle, percentil | **21,3** (pior que ~79% dos sorteios aleatórios) | 84,3 (melhor que a maioria, ainda muito negativo) |

O filtro por `C07` NÃO bate o controle aleatório em `directional_sharpe`
— fica no percentil 21, ou seja, pior que a maioria dos sorteios
aleatórios de mesmo tamanho. Bate o controle em `ret_net` (percentil
84,3), mas mesmo assim continua bem pior que a produção atual (-6,12 vs
-2,82 bps/trade). A produção atual — apesar da confiança não ordenar
dentro do conjunto disparado (ρ≈0, achado já registrado) — continua
sendo a melhor das três opções nos dois eixos, por margem grande.

**Leitura, sem forçar a mão**: isto é consistente com o próprio
mecanismo já medido — o IC de `C07` é contra `ret_net` (líquido de
execução), não contra `ret_gross`/direção (a métrica que
`directional_sharpe` isola). Filtrar só por vol recupera parte do custo
de execução evitado (`ret_net` melhora vs. aleatório), mas não devolve
nenhuma informação DIRECIONAL — e ao remover o gate de confiança
inteiro, perde-se o que quer que a produção atual estivesse capturando
que NÃO é "vol baixa" (o gate de confiança, mesmo sem ordenar bem
dentro do conjunto disparado, parece funcionar como um filtro grosso
razoável — hipótese a investigar depois, não resolvida aqui). O teste
foi desenhado pra decidir, e decidiu: **não trocar o acelerador por
`C07` sozinho.** Substituir por vol pareceria uma "correção óbvia" olhando
só o sinal isolado (180/180 unânime) — o braço de controle é exatamente
o que impede esse erro.

`n_lifetime` id 14, delta=1 — variante de MECANISMO DE SELEÇÃO (não
medição pura), por instrução do Manager. Contador: 43 → **44**. Nenhuma
promoção a produção — `alpha_c1_v1` continua intocado.

### Correção do teste (2026-08-09) — COMPOR, não substituir: confirma, mas assimétrico

Autocrítica do Manager sobre o teste acima, verificada e confirmada
antes de rodar de novo: o erro não foi o diagnóstico (C07 mede execução,
não direção) — foi a ação (usar um sinal de custo como porta
DIRECIONAL). Verifiquei o achado colateral que expôs isso: no corte de
1,08% do teste anterior, ATR% mediano cai pra **0,093%** (contra 0,405%
na mediana geral — números próprios, não os do Manager, mas mesma ordem
de grandeza e mesma conclusão), custo/ATR sobe pra **62%** (contra 14%),
e o stop de 1,5×ATR (~0,139%) fica ABAIXO do piso de viabilidade de R1
(0,275%, CLAUDE.md) — o corte anterior empurrou o sistema pra uma região
onde a geometria de barreira já não é válida, não pra "vol baixa"
genuína. Isso explica a performance ruim do teste anterior sem precisar
de uma teoria nova sobre o que C07 mede.

**Teste corrigido** (`run_vol_accelerator_test_composed`,
`experiments/faixa2_vol_accelerator_test_composed.json`, ~19s): gate de
confiança de produção INTACTO; C07 filtra só o conjunto JÁ DISPARADO
(~1,89% das barras, não 100%); percentil calibrado a priori pelo mesmo
orçamento cai em **85,3%** (bloqueia os 14,7% de maior vol DENTRO do
conjunto já disparado), retendo 57,9%; controle aleatório sorteia do
MESMO conjunto disparado (não do universo), 1.000 sementes.

**Resultado pooled — CONFIRMA, de forma decisiva:**

| | produção (sem filtro) | produção + C07 | controle aleatório (mediana, mesmo N) | percentil vs. controle |
|---|---|---|---|---|
| `directional_sharpe` | +0,879 | **+3,015** | +0,670 | **100,0** |
| `ret_net` (bps/trade) | -2,82 | **-0,61** | -2,82 | **99,7** |

Bate o controle aleatório do MESMO conjunto disparado em praticamente
100% das 1.000 réplicas — isto não é "negociar menos ajuda" (o controle
já negocia o mesmo tanto), é C07 fazendo trabalho real dentro do
conjunto que a produção já dispara.

**Mas o resultado pooled esconde uma assimetria forte por lado — o
oposto do que a leitura de "vol alta piora os dois lados igualmente"
(E3, achado do item 1 da rodada anterior) sugeriria à primeira vista:**

| lado | `total_sharpe` (sem filtro → +C07) | `ret_net` bps (sem filtro → +C07) |
|---|---|---|
| long | -1,30 → **+0,50** (positivo!) | -4,97 → **+1,07** (positivo!) |
| short | -0,16 → **-1,21** (piora) | -0,50 → **-2,82** (piora) |

Por regime, o mecanismo fica claro: o filtro remove desproporcionalmente
`long×R2` (a pior célula do sistema, -22,86 bps, `n` 4435→1832) enquanto
preserva quase intacto `long×R3` (a melhor, +5,46 bps, `n` 6445→6436) —
realocação correta para o long. Para o short, porém, `R2` e `R4` (vol
alta) eram células BOAS ou toleráveis em produção (`short×R2`: +7,95
bps!) — o mesmo corte de vol, aplicado ao short, remove essas células
boas (`n` 2176→539 em R2, 5098→1625 em R4) e o que sobra piora
(`short×R2`: +7,95→-0,52; `short×R4`: -2,82→-13,04).

**Leitura**: C07 tem valor real, mas o valor é `long`-específico (ou
mais precisamente, `long×R2`-específico) — um corte GLOBAL (mesmo
percentil nos dois lados) capta o ganho do long e paga um preço real no
short. Isso não invalida o resultado pooled (que já bate o controle
aleatório por construção, incluindo o efeito líquido dessa troca) — mas
significa que um desenho `side`-específico (ou `side×regime`) provavelmente
captura mais do ganho sem o custo do short. Não testado nesta rodada —
registrado como próxima pergunta, não decidido aqui.

`n_lifetime` id 15, delta=1 (variante de mecanismo, mesmo raciocínio do
id 14). Contador: 44 → **45**. Nenhuma promoção a produção.

### DSR formal + comparação com B2 — o "long + C07" não passa o piso do Gate 6 (2026-08-09)

Pedido do Manager, ANTES de qualquer novo teste: emitir o DSR (Deflated
Sharpe Ratio, Bailey & López de Prado 2014) formal da config "long +
filtro C07" (`total_sharpe` +0,4966, `n_lifetime`=45), e comparar contra
B2 buy-and-hold no mesmo período. **Primeira implementação de DSR/PSR
neste repo** (`src/validation/dsr.py`, 12 testes, §11.6 — citado como
pendente desde `backtest_lite.py`/`validation/__init__.py`; escopo aqui
é só o suficiente pra esta config, não o módulo formal completo do
Sprint 11 — PBO continua fora). Isto é INTERPRETAÇÃO ESTATÍSTICA de um
resultado já medido (id 15), não um trial novo — `n_lifetime` não
incrementa.

**DSR** (`src/analysis/faixa2_dsr_and_b2_check.py`,
`experiments/faixa2_dsr_and_b2_check.json`, ~46s). Reconstruída a
população long+C07 com a MESMA calibração do id 15 (percentil 0,8527,
calibrado sobre os DOIS lados juntos — achei e corrigi um bug próprio
antes de rodar: calibrar só sobre o long contra o orçamento cheio dava
`P=1,0`, "nenhum filtro", porque o long sozinho já cabe perto do
orçamento total; o percentil certo é o do sistema completo, aplicado
depois ao subconjunto long — `n_trades`=12.291, bate exato com o `id 15`).

| | valor |
|---|---|
| `N_lifetime` (trials, auditado) | 45 |
| `SR` observado, anualizado | +0,497 |
| skewness / excess kurtosis (real, não Normal assumido) | +0,168 / -1,574 |
| `SR_0` (piso esperado por acaso, N=45), anualizado | **+0,874** |
| **DSR** | **0,167** (16,7%) |
| Passa o limiar convencional de 0,95? | **Não** |

`SR_0` = +0,874 fica ACIMA do `SR` observado (+0,497) — a configuração
não fecha a distância até o piso de significância. `DSR`=0,167 está
longe de 0,95: sob `N_lifetime`=45 trials já gastos, a probabilidade de
que este Sharpe reflita habilidade real (e não o melhor resultado
esperado por puro acaso depois de 45 tentativas) é baixa. **Isto
confirma a direção do cálculo do Manager (a config não fecha a
distância até o piso), mas com um piso mais baixo que a estimativa
preliminar deles (~1,60)** — `sigma_SR` aqui vem do erro-padrão do
próprio Sharpe observado (proxy padrão da literatura quando a
distribuição real de Sharpe entre os 45 trials não foi rastreada
individualmente, mesmo proxy do exemplo numérico de López de Prado em
AFML cap. 8), calculado com skewness/kurtose REAIS da amostra, não
Normal assumida — a estimativa exata de `sigma_SR`/`SR_0` é uma escolha
metodológica onde a literatura não tem consenso único quando falta o
histórico completo por trial; o veredito qualitativo (DSR muito abaixo
de 0,95, gap real e grande) não depende de qual das duas estimativas de
piso se usa.

**Comparação com B2** — dois números, não um: B2 pooled no MESMO período
(2019-12-29 a 2026-08-09) = **+0,539** (bate o "+0,54" citado pelo
Manager, quase exato). Mas o "+0,497" da config long+C07 usa
anualização POR TRADE (`sqrt(trades_per_year)`, convenção de
`backtest_lite.sharpe_naive` usada no resto do projeto) — **comparar
direto contra o +0,539 de B2 (anualização diária) não é mesma unidade**.
Refeito com o MESMO método (agregação diária, soma de `ret_net` por dia,
0 nos dias sem trade): long+C07 diário anualizado = **+0,121**, bem
mais baixo que os +0,497 originais e muito abaixo de B2 (+0,539). Teste
de diferença por bootstrap em blocos (2.000 réplicas, blocos de 20 dias,
séries PAREADAS dia-a-dia — evita depender de uma fórmula fechada de
covariância tipo Jobson-Korkie/Memmel reconstruída de memória): diferença
observada -0,022, IC95% [-0,066; +0,028], **p=0,397 — não significativa**.
A config só opera em 928 de 2.416 dias (38,4%) — a diluição por dias
"flat" (0 de exposição, vs. B2 sempre 100% exposto) reduz o poder do
teste diário mais do que reflete a diferença real de qualidade —
limitação estrutural de comparar uma estratégia de apostas esparsas
contra um benchmark sempre-investido pela mesma régua diária, não um
defeito do teste em si.

**Retratação registrada** (pedida pelo Manager, verificada — não havia
nada a corrigir nos artefatos deste repo): a estimativa anterior de que
a correção de Lo(2002) levaria +0,50 a +0,37 nunca foi usada nem
persistida em nenhum artefato desta Faixa (`grep` confirmado limpo) — a
correção de Lo continua PENDENTE, sinal do efeito DESCONHECIDO, como já
documentado em `backtest_lite.py` desde o Sprint 8.

**Veredito, na moldura do próprio Manager**: DSR=0,167 é o resultado do
Gate 6 pra esta config especificamente — não passa o limiar convencional
de 0,95, por margem grande o suficiente pra não depender da escolha
exata de `sigma_SR`. `n_lifetime` NÃO incrementa (interpretação
estatística de trial já medido). Nenhuma promoção a produção.

### FASE 3 (C1/C2/C3) — em espera

Precisa rodar sobre "a melhor configuração da FASE 2" — como nenhuma FASE
2 recria a seleção do Alpha sem retreinar, C1/C2 (que comparam
`directional_sharpe` do Alpha, não da população incondicional) exigem
retreinar a Camada 1 pelo menos uma vez sob a config vencedora de
E1+E2+E3. **Instrução explícita do Manager (2026-08-09)**: se o item (1)
acima confirmar um mecanismo coerente (aqui, parcialmente confirmado —
sinal negativo unânime, mas simétrico entre lados, não explica a
assimetria sozinho), o retreino deve ser sobre uma configuração honesta
(o fator que sobrevive + o que interage com ele), NÃO sobre "as 18 menos
as reprovadas" — escolher pelo resultado da triagem seria usar um
critério que a própria triagem já consumiu como trial. Config exata do
retreino ainda em aberto, aguardando revisão do Manager sobre os 3 itens
acima.

## Índice rápido — onde encontrar cada número

| Pergunta | Resposta | Onde |
|---|---|---|
| Existe edge direcional real, ou é beta + regularização? | Misto, não uniforme: long-R2 é seleção ATIVAMENTE pior que ficar passivo (gap -4,05, o pior de toda a tabela); short bate o passivo nos 4 regimes (gap sempre positivo), mas concentrado no lado "trivial" da tendência (reconhecimento de regime, não reversão pura) | Faixa 1.7 abaixo |
| A confiança é consertável removendo contaminação por volatilidade? | Não pela via simples — contaminação confirmada (ρ=0,24 long, p≈0) mas resíduo continua sem ordenar retorno | Faixa 1.7 abaixo |
| Onde a seleção do Alpha é PIOR que não selecionar nada? | Só `long × R2` — gap Alpha-menos-passivo -4,05, o único grande negativo da tabela lado×regime | Faixa 1.7 abaixo, extensão |
| Onde a seleção do Alpha bate consistentemente ficar passivo? | Short, nos 4 regimes sem exceção (gap +0,64 a +2,75) | Faixa 1.7 abaixo, extensão |
| O sweep assimétrico tp/sl por lado (trazido do Laplace_Quant) foi implementado? | Não — continua só nota registrada em §18.7.1, Sprint 6 | Faixa 1.7 abaixo |
| Backtest reconciliado com fill real (37,3%) fora da janela de bookTicker? | Não — só a janela de 10,5 meses (2023-05 a 2024-03) foi reconciliada; direção do viés fora dela é desconhecida, não "sempre otimista" | Faixa 1.7 abaixo, Sprint 8 auditoria externa acima |
| Quantos testes passam hoje? | 384 (1 skip esperado) | `pytest tests/ -q` |
| Distribuição real de TP/SL/TIME/NOFILL? | 36,5/51,3/6,5/5,7% | `labels/v1/labels.parquet`, Sprint 6 acima |
| N_eff real (teto de features)? | ~32,4 mil por modelo | Sprint 6 acima |
| Quais gatilhos de stress funcionam? | 3 de 10 (S1,S3,S6) | `src/regime/stress.py`, Sprint 5 acima |
| Distribuição real de regime? | R1 domina (46%), R5 raro (1,7%) | Sprint 5 acima |
| Long segue a tendência de 48b em R2? | Não detectavelmente — lift 1,02, p=0,18 (contra 1,72/p≈0 em R3) | Faixa 2, FASE 1 D1 acima |
| MFE por regime é pior em R2? | Não — mediana ~1,3-1,4 ATR em TODOS os 8 blocos lado×regime; tp_atr_mult=2,0 parece ambicioso estruturalmente, não seletivamente em R2 | Faixa 2, FASE 1 D3 acima |
| N_lifetime atual, auditado? | 41 (era 5 — +18 retroativo F0.1, +18 varredura E1; +8 de extensão do grid AVALIADO e NEGADO, não gasto) | `audit/n_lifetime.yaml`, Faixa 2 F0.1/E1 acima |
| Geometria de barreira é o gargalo do sistema? | Não — melhor célula do grid (0,028 ATR) fica a 15-18% do breakeven (~0,16-0,19 ATR); extensão do grid NEGADA pelo Manager | Faixa 2, "Conclusão do E1" acima |
| tp=1,5 é a configuração vencedora pra carregar adiante? | Não — E1 rodou sobre população INCONDICIONAL; o ótimo real só é computável DEPOIS de E2/E3, sobre a população selecionada | Faixa 2, "Conclusão do E1" acima |
| E27f_cost_atr_ratio ajuda o modelo a prever? | Importância por permutação NEGATIVA (-0,0065) — embaralhar melhora o AUC; descartada no par contra C07 | Faixa 2, Pré-E2 (2) acima |
| Alguma config de orçamento (short-só/long-sem-R2) cabe em TODOS os 5 paths? | Não — mas as falhas de 1,04-1,05x NÃO são tratadas como restrição ainda (menores que a inconsistência de threshold já medida); a combinação falhando 5/5 continua de pé como restrição real | Faixa 2, Pré-E2 (3) acima |
| E2 (passe de pesquisa T2, sem curadoria) — quantas candidatas e quais entraram? | 70 avaliadas, 10 selecionadas por ortogonalidade incremental (`n_eff_factors` 6,479→15,825): A12, E05f, E12f, K08, H01, E11f, A08, K02_dow_sin, D04f, E17f | Faixa 2, FASE 2 E2 acima |
| A preocupação de "vetor saturado de vol" (E27f) se confirma nas candidatas T2? | Sim como medição (C15 correlaciona -0,80 com C07, C03 +0,79) — mas 0 das 10 selecionadas fica sinalizada, o critério de ortogonalidade já as penaliza estruturalmente | Faixa 2, FASE 2 E2 acima |
| N_lifetime atual, auditado (pós-E2)? | 42 (era 41 — +1 pelo passe de pesquisa E2, contado como 1 trial por instrução do Manager, não 70; +0 pela correção de dado on-chain, confirmação não busca nova) | `audit/n_lifetime.yaml`, Faixa 2 E2 acima |
| Dos 10 selecionados em E2, quantos são determinísticos por construção (função do relógio, zero informação de mercado)? | 3 — `E05f_time_to_funding_h`, `K08_days_since_halving`, `K02_dow_sin` — somam 2,831 de 9,347 de ganho (30,3%); leitura correta do ganho de MERCADO é ~6,52, não 9,35 | Faixa 2, "Correção do Manager pré-E3" acima |
| O aviso de defasagem on-chain de 75 dias (H01/H02/H03/H06/H08) era latência real da fonte? | Não — CSV local desatualizado; CoinMetrics publica com ~1 dia de atraso real. Corrigido, seleção do E2 confirmada robusta (Δn_eff ruído) | Faixa 2, "Correção do Manager pré-E3" acima |
| Quantas das 18 candidatas (T1-8 + E2-10) sobrevivem à triagem de estabilidade (§5.4) de forma robusta, não só num ponto do limiar? | Só 2 — `C07_vol_pctile_expanding` e `D03f_volume_z_expanding`, 30/30 células em toda a vizinhança 0,01-0,03 do sweep_range | Faixa 2, FASE 2 E3 acima |
| Ambientes de triagem do E3 são 6 ou 12 (regime R1..R4)? | 6 (RANGE/TREND × tercil de custo) — "12" cruzaria vol com ela mesma e, com unanimidade exigida, ficaria 64x mais restritivo sob ruído (0,049% vs 3,125%); PRD corrigido para não confundir com o regime de reporte R1..R4 | Faixa 2, FASE 2 E3 acima |
| `rpi_regime` (PRE/POST) entra na fórmula de estabilidade do E3? | Não — virou diagnóstico separado (`ic_by_rpi_regime`); perdeu o alvo depois que o Grupo F saiu de T1 na v3.3 | Faixa 2, FASE 2 E3 acima |
| N_lifetime atual, auditado (pós-E3)? | 43 (era 42 — +1 pelo passe de pesquisa E3, 1 trial) | `audit/n_lifetime.yaml`, Faixa 2 E3 acima |
| C07/D03f (únicas 2 robustas do E3) têm IC negativo consistente contra `ret_net`? | Sim — negativo em 180/180 combinações (6 ambientes × 2 lados × 15 folds), mas magnitude QUASE SIMÉTRICA entre long/short — não explica sozinho a assimetria long-falha-R2/short-bate-passivo | Faixa 2, Pré-FASE 3 acima |
| C07 e D03f são o mesmo fator (correlação alta)? | Parcialmente — ρ=0,46, n_eff_factors=1,65 de um teto de 2 (redundância real, não colapso a 1 fator) | Faixa 2, Pré-FASE 3 acima |
| A triagem do E3 tem poder suficiente pra distinguir "sem sinal" de "sinal fraco"? | Discutível — N real por ambiente é ~22.891 (não ~5.000 como estimado), maior poder que o assumido; a maioria dos "zeros" tem \|IC\| mediano 0,004-0,021, perto do limiar de força, não zero | Faixa 2, Pré-FASE 3 acima |
| Os "zeros" do E3 são sinal fraco ou sinal que inverte? | Misto, verificado direto no `ic_by_env` bruto — `A12_gap_pct`/`D04f_volume_accel` são ruído genuíno (~50/50 em todo ambiente); `K02_dow_sin`/`E02f_funding_z_expanding`/`E17f_retail_vs_top_spread` têm sinal REAL condicional a tercil de custo (77-90% de consistência em ambientes de custo alto/médio) que a fórmula de unanimidade não credita | Faixa 2, "Validação da análise do Manager" acima |
| O modelo dispara mais e fica mais confiante em vol alta, apesar do sinal mais estável dizer o oposto? | Sim, confirmado com precisão: disparo long 0,340% (R1) vs 4,337% (R2) = 12,76x; TP rate 28,35% (R2) vs 42,42% (R3); R4 (tendência+vol alta) dispara ainda mais (long 4,27%, short 5,28%) | Faixa 2, "Validação da análise do Manager" acima |
| Trocar o gate de confiança por um filtro de C07 (vol) melhora o resultado? | Não, como SUBSTITUTO — percentil 21 do controle, pior que a maioria; o corte empurrou o sistema pra ATR abaixo do piso de viabilidade R1 | Faixa 2, "Teste do C07 como acelerador" acima |
| Compor C07 COM o gate de confiança (não substituir) melhora o resultado? | Sim, decisivo no pooled — `directional_sharpe` +0,879→+3,015 (percentil 100 vs. controle aleatório do mesmo conjunto), `ret_net` -2,82→-0,61 bps (percentil 99,7) — mas TODO o ganho é do long (`total_sharpe` -1,30→+0,50); short piora (-0,16→-1,21) | Faixa 2, "Correção do teste — COMPOR" acima |
| A config "long + C07" passa o DSR (Gate 6, N_lifetime=45)? | Não — DSR=0,167 (limiar convencional 0,95); SR observado +0,497 fica abaixo do piso esperado por acaso SR_0=+0,874 | Faixa 2, "DSR formal + comparação com B2" acima |
| "long + C07" bate B2 buy-and-hold no mesmo período, mesmo método? | Não — B2 diário=+0,539, long+C07 diário=+0,121 (comparação por trade, +0,497, usava anualização diferente, não era mesma unidade); diferença não significativa no teste bootstrap (p=0,397) por baixo poder — estratégia só opera 38% dos dias | Faixa 2, "DSR formal + comparação com B2" acima |
| sliding_window_view (§18.7.1) foi implementado? | Sim — `src/labels/barrier_sweep.py`, 18 células em 35,8s, reproduz Sprint 6 com max_abs_diff=2,3e-5 | Faixa 2, FASE 2 E1 acima |
| A geometria de barreira sozinha (sem seleção de modelo) tem edge positivo em algum ponto do grid? | Não — negativo nas 18 células, os dois lados (população incondicional, mesmo padrão do B1 já medido) | Faixa 2, FASE 2 E1 acima |
| Cobertura real de dado por fonte? | tabela acima | Sprint 0/backfill acima, `config/constants.yaml::known_gaps` |
| Correlação real entre features T1? | 2 pares violam 0,70 | Sprint 4 acima |
| CPCV vaza treino pro teste? | Não — 0 de 462.682 labels, medido | Sprint 7 acima |
| Quantos dos 14 testes de leakage passam? | 11 PASS, 2 pendem de modelo, 1 N/A | Sprint 7 acima |
| Fill rate real (maker)? | **37,3%** agregado (42,2% dentro da janela reconciliada) — abaixo do piso de 60% do §9.6, que é ele mesmo fabricado (§18.5.4) | Sprint 9 acima |
| Seleção adversa real medida? | ~0,6bps (menor que o placeholder de 1,5bps) | Sprint 9 acima |
| Gate otimista vs gate real muda o Sharpe do Alpha? | Sim, pra melhor, dentro da janela medível (-9,25 → -4,27) — mas não resolve a economia dos 6,5 anos completos | Auditoria externa acima, **item mais crítico ainda em aberto** |
| Fill rate baixo esconde os trades vencedores? | Não — gap P(TP\|fill) vs P(TP\|miss) é só -1,72pp | Auditoria externa acima |
| B1 (Alpha vence entrada aleatória) resiste a comparação mais rigorosa? | Sim, 4 de 5 caminhos + nulo pareado + pool total no percentil 100; caminho 4 fica em 70,9 | Auditoria externa acima |
| Decis de confiança ordenam retorno? | Não, nos dois lados (ρ_long=0,14 p=0,70; ρ_short=-0,20 p=0,58) — mas o score CRU (pré-calibração) ordena SIGNIFICATIVAMENTE (long ρ=-0,82 p=0,004; short ρ=+0,69 p=0,03), com ~75% dos trades trocando de decil entre score cru e calibrado | Faixa 1 acima, `experiments/faixa1_calibration_diagnostic.json` |
| NOFILL varia com a confiança? | Sim, associação forte nos dois lados (χ²long p≈5e-37, χ²short p≈3e-135) | Faixa 1 acima |
| E02f_funding_z inverte de sinal RANGE↔TREND? | Sim, medido: R1=+0,04/R2=+0,11/R3=-0,03/R4=-0,08 | Faixa 1 acima, reproduz Fase E |
| Calibração isotônica melhora ou piora a confiança? | As duas coisas — piora ORDENAÇÃO (D4) e melhora MAGNITUDE/ECE (long 0,256→0,200; short 0,234→0,155) | Auditoria Laplace_Quant_V16 acima |
| Alguma T1 vaza informação futura (scan estatístico)? | Não — 0 de 10 estoura o `hard_fail_threshold`; 4 ficam `elevated` por correlação estrutural com ATR, não vazamento | Auditoria Laplace_Quant_V16 acima, `src/validation/leakage.py::scan_feature_target_correlation` |
| `fee_budget_monthly` no valor central cabe no orçamento? | **Não** (corrigido na Faixa 1.6) — orçamento correto é 662,7 trades/ano, os 5 caminhos reais (858-1.307) TODOS excedem, 1,3x-2,0x | Faixa 1.6 abaixo, `experiments/faixa1_5_prerequisites.json::fee_budget_sweep` |
| E02f in-fold: a triagem estatística discorda do sinal forçado? | Não em nenhum dos 15 folds (0 discordâncias) — mas só 1/15 folds no short chega a 6/6 de consistência pra opinar | Faixa 1.5 acima (hipótese do executor, não medição) |
| CIs por path do Alpha são confiáveis? | Não totalmente — trades duplicados entre até 5 paths (mesma barra, mesma barreira) tornam os CI95 por path provavelmente otimistas; não corrigido ainda | Faixa 1.5 acima |
| Por que o IC de E02f "inverte" de sinal pooled vs in-fold em RANGE? | Não inverte — não é a mesma medição. Treino (insumo real da triagem) é negativo uniforme, 15/15 folds. OOF é população SELECIONADA (~1,89% das barras, 0,34%-4,34% conforme o regime) — condicionar na saída do modelo muda a distribuição por construção (viés de seleção, não vazamento) | Faixa 1.6 abaixo, PRD §5.3 |
| `threshold_effective_confidence_quantile` media o que o nome diz? | Não até 2026-08-09 — quantil de população já selecionada, corrigido (path 0 saía 1,0000 com 7.162 trades preenchidos) | Faixa 1.6 abaixo |
| Quanto do ganho do T0 (0,194→0,879) vem do short vs do long? | Quase todo do short — sem a restrição forçada no short, pooled cai pra 0,282. **Não canônico**: mecanismo (carry vs direcional vs regularização) pendente de controle de sinal aleatório | Faixa 1.6 abaixo, `n_lifetime` id 5 |
| `directional_sharpe` por regime — long ordena melhor que short? | Não — é o oposto do que se pensava com `ret_net`: short é positivo nos 4 regimes (+0,28 a +1,73), long oscila violentamente (-2,52 a +4,35) e o pooled (+0,167) é cancelamento, não skill fraca | Faixa 1.6 abaixo (correção de método) |
| Alguma outra feature T1 além de E02f inverte de sinal por regime? | Sim — `D06f_taker_imbalance_z_48` (pooled ~0, mas R1/R2/R4 positivos e R3 negativo) | Faixa 1.6 abaixo, `features/registry.yaml` |
| Onde está o mapa de todo edge/winrate já medido, do Sprint 8 até aqui? | Artifact publicado (trilha cronológica em Mermaid + 3 matrizes lado×regime + 8 perguntas abertas + tabela de 160 registros), gerado a partir de `audit/evidence_ledger.yaml` | "Discovery — mapa canônico de evidência" abaixo |
| `research_t2.py`/`_sources_research.py` ainda vivem em `src/features/`? | Não — movidos pra `research/` em 2026-08-09 (grau de pesquisa, fora de `root_packages` do import-linter); `README.md` lá explica o critério e como promover uma candidata | "Discovery — mapa canônico de evidência" abaixo |

## Discovery — mapa canônico de evidência + reorganização canônico/andaime (2026-08-09)

Pedido do Manager, com um critério explícito de classificação: **"o critério
não é 'isto foi útil', é 'se sumisse, quanto custaria refazer'."** Duas
entregas.

**1 — Inventário mecânico de todo caminho de edge/winrate medido, Sprint 8
até a Faixa 2.** 3 agentes em paralelo (Fundação/Alpha C1 · Faixa 1+1.5 ·
Faixa 1.6+1.7) + leitura direta da Faixa 2, cada um extraindo registros
estruturados (lado, regime, feature/filtro, métrica, n, status, fonte) de
`docs/SPRINT_LOG.md` e de `experiments/*.json` — nunca de memória de
conversa. **160 registros** (68 vermelho / 56 amarelo / 28 verde / 8
cinza), persistidos como novo ledger canônico de DADO,
`audit/evidence_ledger.yaml` (append-only, mesma convenção do
`n_lifetime.yaml` — corrigir é adicionar `superseded_by`/`supersedes`,
nunca editar ou apagar uma entrada). Publicado também como Artifact
navegável: trilha cronológica (Mermaid), 3 matrizes lado×regime (Alpha
canônico · gap Alpha-menos-passivo · depois do filtro C07), e 8 perguntas
abertas geradas mecanicamente do próprio inventário (ex.: o modelo dispara
12,76x mais em R2/vol-alta apesar de C07/D03f dizerem que vol alta piora o
retorno; `D06f_taker_imbalance_z_48` é o 2º caso de feature que inverte de
sinal por regime, nunca tratado como E02f foi). Nenhuma decisão de
arquitetura tomada — é discovery, FASE 3 continua em espera.

**2 — Reorganização canônico vs. andaime**, aplicando o mesmo critério de
custo-de-refazer:

- **Canônico como código** (verificado que existe, nenhum movido):
  `src/labels/barrier_sweep.py`, `src/models/stability.py`,
  `src/core/metric.py` (+ `safe_ratio`), `src/models/environments.py`,
  `src/models/monotonic.py`, `src/validation/dsr.py`,
  `src/execution/fill_simulator.py`, `tools/lint/check_constants_referenced.py`.
- **Canônico como dado**: `audit/n_lifetime.yaml`, `config/constants.yaml`,
  `labels/v1/labels.parquet` (distribuições de barreira do Sprint 6),
  `tests/golden/test_sprint8_reproducibility.py`, e o novo
  `audit/evidence_ledger.yaml` acima.
- **Andaime, arquivado não apagado**: `research_t2.py` e
  `_sources_research.py` (70 candidatas T2 em grau de pesquisa) movidos de
  `src/features/` pra `research/` (`git mv`, imports relativos corrigidos
  pra absolutos — `from . import support` → `from src.features import
  support`, etc.), com `research/README.md` explicando o porquê e o
  caminho de promoção. Saem de `root_packages` do import-linter de
  propósito — nunca passaram pela cerimônia de produção (`registry.yaml`,
  `causal_proof`, paridade), e forçá-los pra dentro escondia isso.

**Verificação**: `ruff`/`mypy` limpos nos arquivos tocados,
`import-linter` 6/6 contratos mantidos, `banned_patterns` sem violação
nova, suíte completa `not slow and not integration`: 851 passam (era 851,
mesma contagem — só reorganização, nenhum teste novo nem quebrado), 1
skip/2 xfail pré-existentes e não relacionados.

<!-- check-sprint-log: skip -->
## M1 — comparação de estimadores de volatilidade (2026-08-11)

4 dos 6 estimadores candidatos (ATRWilder baseline, Parkinson, Garman-Klass,
HAR-RV) rodados sobre as 15 combinações reais (5 ativos × 3 TFs) por QLIKE
walk-forward ancorado (`experiments/volatility_comparison_report.json`,
commit `2410bc1`). **Garman-Klass venceu 14/15** contra ATRWilder.
Extensão pós-M1 testou mais dois candidatos (Rogers-Satchell, Yang-Zhang)
contra o vencedor — GK seguiu vencendo 10/15, nenhum dos 8 supera
(`experiments/volatility_rs_yz_vs_gk_report.json`, commit `2436b33`).

**Achado de engenharia real, não cosmético:** um `RuntimeWarning` do numpy
em `diebold_mariano` não era ruído — `d = loss_candidate - loss_baseline`
podia envolver QLIKE `inf`, e `finite - inf = ±inf` (não `NaN`) passava
direto pelo filtro `~np.isnan(d)` aplicado DEPOIS da subtração. Um único bar
degenerado num candidato corrompia o teste inteiro sem barreira. Corrigido
filtrando `isfinite` dos dois lados ANTES de subtrair — não abafando o
warning com `np.errstate`. Virou diretriz permanente ("nunca remediar,
sempre solucionar") em `CLAUDE.md`.

**Decisão do Manager, 2026-08-11:** Garman-Klass é o vencedor de M1,
registrado em `config/constants.yaml::canonical_volatility_estimator`.
Travado 2026-08-12 ("aceito sua recomendação"). **Deployment explicitamente
adiado** até M2 (barra) e M3 (timeframe) fecharem — mudar qualquer um dos
dois força relabeling de qualquer forma, reprocessar duas vezes seria
retrabalho. Detalhe: `docs/refactor_gk_canonico.md`.

<!-- check-sprint-log: skip -->
## M2 — comparação de tipo de barra, dollar bar vira canônico (2026-08-15 → 2026-08-16)

Comparou barra de tempo (baseline, klines) contra dollar/volume/tick-imbalance
bars construídas trade-a-trade de `aggTrades` real (27GB/20GB comprimidos só
BTC/ETH — não cabem em memória de uma vez em nenhuma concorrência, motivou
desenho streaming chunked em `src/data/bars.py` com paridade lote↔streaming
testada em `tests/unit/test_data_bars.py`).

**3 bugs reais corrigidos no caminho** (`src/data/bars.py`,
`src/analysis/m2_stats.py`), cada um achado rodando contra dado real, não
em teste sintético:
- Streaming de dollar/volume bars fechava "barra fantasma" — cumsum
  recomeçava do zero a cada chunk, perdendo o resto de barras que fecham
  sem bater exato no threshold. Achado via teste de paridade streaming↔lote
  (`tests/unit/test_data_bars.py`).
- `duckdb.connect()` sem `SET memory_limit`/`SET threads` assume até 80% da
  RAM da máquina POR CONEXÃO, sem coordenação entre processos concorrentes
  — travado explicitamente (`config/constants.yaml::m2_duckdb_memory_limit_gb`).
- Colisão de `temp_directory` do DuckDB entre processos concorrentes
  (`audit/architecture_gaps_log.yaml::AG-033`) + limiar de plausibilidade
  do teste ADF calibrado só contra caso sintético patológico (30,0), não
  dado real de série longa — recalibrado pra 2000,0 com evidência de
  escala √n.

**Run canônico completo (histórico inteiro) travou por esgotamento de
memória sob concorrência plena** (`audit/architecture_gaps_log.yaml::AG-034`)
— 12 processos × estado acumulado sem orçamento agregado, nunca corrigido.
Em vez de reduzir concorrência ou encolher pra 1 mês recente (perderia
diversidade de regime), M2 rodou em **5 janelas deliberadamente escolhidas
por regime**: LUNA/UST (2022-05), FTX (2022-11), crypto winter (2023-06),
ETF/halving (2024-03), recente (2026-07). Suporte a `--start`/`--end`/
`--max-workers` adicionado a `src/analysis/m2_bar_comparison.py`.

**Resultado: dollar bars venceu 4 das 5 janelas + o pooled** sobre o
baseline de tempo (volume venceu a 5ª, winter, por margem pequena) — bate
o baseline em toda métrica (JB/Ljung-Box/unicidade) exceto ADF (empate,
100% em todo tipo). `tick_imbalance` falhou 5/5 (JB/LB=0% em toda janela).
Resultado completo por janela: `experiments/m2_report_luna.json` e as 4
janelas irmãs (`ftx`/`winter`/`etf`/`recente`), mesmo diretório.

**Causa raiz do `tick_imbalance` investigada**
(`audit/architecture_gaps_log.yaml::AG-035`) — produzia 250x-1000x mais
barras que o alvo em toda combinação (ex. BNBUSDT 15m LUNA: alvo 2.976,
real 969.263). `src/analysis/m2_worker.py::_build_tick_imbalance_config`
calibrava com a MESMA fórmula de dollar/volume bars
(`n_ticks/target_n_bars`), que assume implicitamente desequilíbrio de
ordem ≈100% por tick — falso pra mercado líquido, onde o desequilíbrio
real fica em ~0,1%-1%. **Não é evidência de que tick imbalance bars sejam
ruins pra cripto — é calibração quebrada da harness de M2.** Não invalida
a vitória de dollar sobre TEMPO.

**Decisão do Manager, 2026-08-16:** dollar bar é o vencedor de M2, travado
em `config/constants.yaml::canonical_bar_type=dollar`. `AG-034`/`AG-035`
fechados por decisão explícita — risco aceito, não corrigidos (reabrir se
histórico completo precisar reprocessar, ou se tick_imbalance voltar a ser
cogitado). **Deployment não iniciado** — todo o pipeline (Feature/Regime/
Label Engine) foi construído sobre barra de tempo até aqui.

Resultado completo, por janela e pooled: artefato "Biblioteca de Testes" (aba M2, publicado 2026-08-16) — link em posse do Manager, não versionado no repo. <!-- check-sprint-log: skip -->

<!-- check-sprint-log: skip -->
## Governança pós-M2 — T1 extinto, bloqueadores do redesenho dollar-bar (2026-08-16)

**Investigação de arquitetura ponta-a-ponta delegada** (Agent, contexto
rico) mapeando o que muda em cada camada (`exchange` → `live`) na migração
pra dollar bar. Entregue como `docs/refactor_dollar_bar_canonico.md` (~13
camadas). 8 achados-chave:

- Nenhuma dollar bar foi construída sobre o histórico completo de nenhum
  ativo — o run canônico nunca terminou uma célula sequer; as 5 janelas de
  M2 são toda a evidência empírica que existe.
- `canonical_bar_type` ainda não é lido por nenhuma linha de código — é
  registro de decisão puro, mesmo padrão do GK.
- `src/validation/cpcv.py::assert_tf_consistent` é uma trava dura
  (`rtol=0,05` contra `step_ms(tf)` nominal) que bloqueia CPCV pra
  qualquer grade não-tempo — **sem solução escolhida ainda**.
- O contrato `estimate(bars, horizon_minutes=...)` de TODO estimador de
  volatilidade (inclusive GK, `src/features/volatility.py`) exige
  `horizon_minutes == timeframe_minutes` — dollar bar não tem isso.
  Bloqueia M1, Feature Engine (grupo C do `features/registry.yaml`) e
  Label Engine simultaneamente. Virou
  `audit/architecture_gaps_log.yaml::AG-036` (aberto): M1 (8 estimadores)
  precisa ser remedido do zero quando a refatoração de barra terminar; GK
  continua válido só pra grade de TEMPO até lá.
- 3 bloqueadores nomeados apresentados com opções e trade-offs, sem
  recomendação (decisão reservada ao Manager): `AG-031` (horizonte do
  label sob dollar bars), redefinição de "M15/M30/H1" sob dollar bars
  (4 opções: threshold fixo · recalibração periódica · EWMA causal ·
  abandonar os nomes por "camadas de resolução"), `AG-032` (embargo do
  CPCV sob dollar bars) — ver `docs/refactor_dollar_bar_canonico.md` §2-4.
- Construção de dollar bar em produção não tem nada pronto — `src/live/`
  é 3 linhas, sem stream assinado em lugar nenhum.
- `control_05_frescor_dados` (`src/risk/limits.py`) vai rejeitar trades
  durante períodos legitimamente quietos sob dollar bar (medido em
  segundos, dollar bar não tem "segundos entre barras" garantidos).
- Custo real de reprocessamento medido (`docs/refactor_dollar_bar_
  canonico.md` §5.3): 61GB de `aggTrades` vs 0,5GB de klines, 3,4 bilhões
  de trades só de BTC.

**T1 extinto** (decisão do Manager, 2026-08-16, expandida no mesmo dia):
as 13 features do registry atual (não as ~64 do pool `research/` — fora de
escopo, decisão separada) viram pool candidato único, sem cap de 10,
ranqueadas por desempenho via o procedimento já definido em
`PRD_V3_2_UNIFICADO.md` §2.0.1 (Sprint 6: mede `N_eff` real; Sprint 8:
ablação dentro do CPCV, k=6,9,12,16,24, PBO<0,30 como critério de parada —
as 5 variantes de k custam 5 trials de `N_lifetime`). **Sem dependência
técnica dos 3 bloqueadores dollar-bar** — pode rodar agora, no grid de
tempo atual; precisará ser remedido sob dollar bar depois (mesmo padrão de
`AG-036`). Achado do relatório (`docs/refactor_dollar_bar_canonico.md`
§1.6): T1 está acoplado posicionalmente em ≥8 lugares de `src/models/`
(`alpha.py::DESIGN_COLUMNS`, `monotone_constraints` como tupla posicional,
denominadores diferentes do HHI nominal×efetivo em `models/hhi.py`,
`CURRENT_T1` hardcoded em `src/analysis/faixa2_e2_research.py`) — remover
o cap exige tornar essas referências dinâmicas, não só editar o registry.

**Revisão independente disparada** (`project_assurance`, Agent fresco, sem
contexto de justificativa) sobre `docs/refactor_dollar_bar_canonico.md` —
reverifica os 8 achados por Grep próprio, responde se
`src/validation/cpcv.py::assert_tf_consistent` precisa de redesenho
separado das 4 opções do bloqueador de TF, reconfirma o acoplamento de T1,
e checa se existe regra explícita de custo de sweep classe A em
`audit/n_lifetime.yaml` (não achada em nenhum doc até aqui). Resultado
pendente.

**Explicação visual do orçamento `N_lifetime`** (`audit/n_lifetime.yaml`)
publicada como artefato — `counter=45`/teto `60`/**15 trials restantes**;
critério de encerramento #5 do PRD (`PRD_V4_1.md` §6.5).

**Correção do Manager, mesmo dia:** a 1ª versão do artefato apresentou as
13 constantes classe A ainda `ASSUMED` (`tp_atr_mult`, `sl_atr_mult`,
`atr_window`, `time_stop_bars`, `cost_stop_ratio_max`, `fee_budget_monthly`,
`regime_er_cutoff`/`_exit`, `regime_vol_cutoff`/`_exit`,
`adverse_selection_bps`, `max_notional_multiple`,
`alpha_stability_screen_limiar`) como se fossem orçamento de `N_lifetime`
em risco agora — errado. Cada uma já tem `review_by` (sprint 5/6/10/11/16)
em `config/constants.yaml`, esperado desde a decisão de ir multi-TF/
multi-ativo, não um achado novo. Só custa trial quando o sweep de fato
roda, no sprint declarado. Lugar certo pra essa agenda: `PLANO_MESTRE_
PRINCE2.md` §11.4 (Road Map Vivo, novo). O único item desta rodada com
custo real de `N_lifetime` continua sendo `AG-036` (remedição de M1,
disparada pelo achado de M2 — não agendada previamente, por isso é trial
de verdade, diferente dos 13). Protótipo de medição DuckDB-nativo vs.
Polars-vetorizado pra construção de dollar bar aprovado e escrito
(`tools/diagnostics/prototype_dollar_bar_duckdb_vs_polars.py`), execução
pendente do usuário.

## M1 remedido sob dollar bar + migração Parkinson canônico (2026-08-17) <!-- check-sprint-log: skip -->

**M1 remedido por completo sob grade dollar-bar** — 5 símbolos × 3
resoluções (R1/R2/R3) × 6 candidatos (RealizedVol/ATRWilder/Parkinson/
RogersSatchell/HAR-RV/EGARCH-acoplado) vs. baseline GarmanKlass,
`experiments/volatility_dollar_bar_report.json`. Resultado: **Parkinson
bate GK, significativo, em 12/15 combinações**; empate estatístico em
2/15; GK vence sem contestação em 1/15 (SOLUSDT×R3) — `audit/
architecture_gaps_log.yaml::AG-065`/`AG-074`. Manager decidiu: **Parkinson
é a nova volatilidade canônica** (`AG-036::addendum_decisao_manager_
2026_08_17`), pedindo pra tratar isso junto da comutação real de produção
pra grade dollar-bar (`resolution_id=R1`) — os dois planos que ficaram
parados em "decisão registrada, deployment adiado" (`docs/
refactor_gk_canonico.md` original) viraram um plano só, `docs/
refactor_parkinson_canonico.md`.

`N_lifetime` (`audit/n_lifetime.yaml`) chegou a `counter=63`, acima do
orçamento total da V4.1 (`PRD_V4_1.md:625`, 60) — critério de
encerramento §6.5-5 disparado. Manager autorizou explicitamente estourar
o orçamento pra esta migração (id 17, `budget_override_manager`,
`delta=0` — a autorização em si não gasta trial; retreino real, quando
rodar, conta normalmente).

<!-- check-sprint-log: skip -->
**Migração executada em 6 fases**, plano completo revisado por
`project_assurance` (Agent fresco) antes de começar — achou 5 gaps <!-- check-sprint-log: skip -->
CRITICAL na 1ª versão do plano (peça de orquestração faltando, desenho <!-- check-sprint-log: skip -->
do Bloqueador 2 assumindo metadado inexistente, risco real de colisão de <!-- check-sprint-log: skip -->
path, `leakage.py` fora do blast radius, `min_common_history_bars_15m` <!-- check-sprint-log: skip -->
sob dollar bar não endereçado), todos incorporados antes da execução —
commits por fase citados abaixo:

- **Fase 0** (`e32b7a4`) — decisão registrada + `assert_grade_consistent`
  corrigido (`src/validation/cpcv.py`, lê `_calibration.json` real em vez
  de assumir espaçamento de relógio).
- **Fase 1** (`5df33c3`) — Label Engine ganha `resolution_id`, path de
  escrita novo com guarda anti-colisão contra os labels reais de
  produção. Achado no processo: `fill_timeout_bars` multiplicava por
  `bar_ms` (mesma classe de bug de `time_stop_bars`, AG-031, não pega na
  1ª rodada) — corrigido pra `fill_timeout_ms`.
- **Fase 2** (`3449471`) — Feature Engine ganha `vol_estimator_id`
  selecionável (`c01_atr_20_parkinson`, default ATR de Wilder bit-exato).
- **Fase 3** (`9a4c3c5`) — Regime Engine ganha `bar_source`/
  `vol_estimator_id`.
- **Fase 4** (`b5760fe`) — orquestração ponta a ponta (`dataset.py`,
  `pipeline.py`, `leakage.py`, `fill_reconciliation.py`) — corrige bug
  real onde `tf` era validado mas nunca repassado adiante.
- **Fase 5/6** (`304b00b`) — Manager pediu explicitamente pra NÃO rodar o
  corte real de produção ainda ("run canônico de produção agora seria
  desperdício de tempo", já agendado junto de outras mudanças no
  roadmap) — governança fechada nesse estado (engenharia pronta,
  aplicação adiada), não "medido e aplicado".

<!-- check-sprint-log: skip -->
**Auditoria final** (`audit_engineering`, 4 agentes paralelos por pacote,
commit `d03d207`) — zero CRITICAL, 3 HIGH reais corrigidos (proteção
contra `CPCVError` faltando em 2 dos 3 testes de vazamento que tocam
CPCV; paridade lote↔streaming nunca exercida sob Parkinson/dollar-bar,
DoD do CLAUDE.md; `build_modeling_frame` amarrava `bar_source` só a
`resolution_id`, nunca a `tf` — `tf="30m"` chegaria a labels/CPCV mas
features/regime ficariam presas em 15m, achado real ainda não <!-- check-sprint-log: skip -->
explorável hoje mas ativo assim que labels 30m/1h existirem). <!-- check-sprint-log: skip -->

<!-- check-sprint-log: skip -->
**Correção de escopo do Manager, mesma conversa** (`6219d02`): labels/
testes de vazamento/Feature-Regime liberados pra execução REAL — só o
retreino do Alpha ficou fora ("solucione, mas não execute — deixe
pronto"). Executado de verdade: `data/labels/{symbol}/R1/v1/
labels.parquet` pros 5 símbolos (BTCUSDT 463.034/ETHUSDT 328.452/
SOLUSDT 327.461/BNBUSDT 328.440/XRPUSDT 327.488 linhas; 15m de
produção confirmado intocado); 14 testes de
vazamento contra R1 pros 5 (**12 PASS/0 FAIL/2 sentinela em todos — zero
vazamento**, `data/validation_reports/leakage_report_{symbol}_R1.json`);
`build_modeling_frame` pros 5 (zero regime nulo, features T1 sãs).
Achado no processo: 2 MEDIUM da auditoria diziam "fechar antes de
qualquer backfill real" — rodei o backfill primeiro, corrigi depois
(`n_bars_held` Int16→Int32 preventivo; 2 testes novos pros branches
degenerados de `median_bar_ms`, AG-061) e reprocessei os 5 símbolos de <!-- check-sprint-log: skip -->
novo com o schema corrigido.

`run_layer1_sprint` (retreino do Alpha) ganhou `--tf`/`--resolution-id`/
`--vol-estimator-id` no CLI — comando pronto, **não executado**.
`constants.yaml::canonical_volatility_estimator.value` continua
`garman_klass_w20` até o retreino real acontecer (não antes, pra não
haver janela onde o config mente sobre o que está em produção).

**Pendente pra fechar de vez** (ver `PLANO_MESTRE_PRINCE2.md` §11.4/
§11.5): retreino real de Alpha Camada 1 sob R1+Parkinson (5 símbolos) +
flip de `value` — agendado junto de outras mudanças já previstas no
roadmap, decisão do Manager de quando.

<!-- check-sprint-log: skip -->
## M4 — comparação de classificadores de Regime (2026-08-17 → 2026-08-18)

**Harness completo implementado e auditado** (`PRD_V4_1.md` §3.2 M4,
único item pago da Camada 1) — baseline (`QuantileRegimeClassifier`,
produção) vs. 3 candidatos novos: HMM gaussiano (`dynamax`, prior sticky,
k=2/3/4), Jump Model contínuo/CJM (`jumpmodels`), BOCPD (vendorizado,
Adams & MacKay 2007) — mais Terceira via Q3 (BTC como fator comum,
aplicado aos outros 4 ativos via `join_asof` causal `strategy="backward"`).
Plano completo commitado em `docs/m4_regime_plano_execucao.md` (achado
de `project_assurance`: o plano original só existia como documento de
sessão, nunca versionado — quebrava a disciplina "toda regra tem âncora,
todo histórico via `git log`").

<!-- check-sprint-log: skip -->
**Fases 0-6 do desenho original** — dependências aprovadas + smoke test
(`6158442`), primitivos puros (`canonicalization.py`/`bocpd.py`/
`regime_utility.py`), HMM+Jump Model (`61d2ce4`/`9b945f9`, delegados a
`Agent`s, 1 bug real corrigido — init de covariância do `dynamax` ignora
escala do dado real), harness de orquestração (`ec370e0`), Terceira via
(`db214aa`). **Auditoria obrigatória** (`audit_engineering`+
`project_assurance`, 6 agentes em paralelo) — **4 bugs CRITICAL/HIGH
reais corrigidos**: `canonicalization.py` (`NaN`/`Inf` em `response`
quebrava a invariância a permutação de rótulo, o defeito central que o
módulo existe pra eliminar, B21); `jump_model.py` (`Inf` degenerava o
decode silenciosamente); `tools/lint/banned_patterns.py` (`--path
<arquivo único>` escaneava zero arquivos silenciosamente, mesma classe
de bug já corrigida uma vez em 2 scripts irmãos — achado por 2 agentes
independentes em paralelo — expôs `AG-082`, 25 violações `MAGIC_NUMBER`
pré-existentes em 7 arquivos, backlog aceito não corrigido);
`m4_regime_comparison.py` (oversubscription de threads BLAS/JAX sob
<!-- check-sprint-log: skip -->
`ProcessPoolExecutor`, ~90 threads/processo medido, mesma classe do M2 — <!-- check-sprint-log: skip -->
mais falta de `mp_context="spawn"` explícito, risco de deadlock por fork
em produção/Linux, corrigido em `b131e02`).

<!-- check-sprint-log: skip -->
**Decisões do Manager, 2026-08-18** (5 itens empilhados, resolvidos de
uma vez ao fim da auditoria, commits `8d92bed`/`874c21b`): (1) contagem
<!-- check-sprint-log: skip -->
de trials confirmada — 6 exatos (baseline=0, HMM k2/k3/k4=3, Jump
Model=1, BOCPD=1, Q3=1); (2) ANOVA F clássica → **Welch's F**
(`statsmodels.stats.oneway.anova_oneway`, `omega_squared` migrado pra
fórmula "AnL" — Albers & Lakens, 2018, `J. Experimental Social <!-- check-sprint-log: skip -->
Psychology` — com prova algébrica de equivalência ao caso clássico) —
motivo: regimes de volatilidade violam homocedasticidade por
construção, contradição interna usar teste que assume variância igual
pra medir se a variância é diferente; (3) causalidade em bloco do Jump <!-- check-sprint-log: skip -->
Model (decode Viterbi do fold inteiro, pode "ver" o próprio futuro do
fold) — documentada como caveat explícito no relatório, `.predict()`
mantido; (4) backlog `AG-082` aceito, não corrigido agora. <!-- check-sprint-log: skip -->

<!-- check-sprint-log: skip -->
**Hiperparâmetros de candidato calibrados via medição real** (nunca
<!-- check-sprint-log: skip -->
inventados, `config/constants.yaml`, commit `93723a5`) —
`jump_penalty=0,002` (grade manual sobre BTCUSDT real, fronteira de <!-- check-sprint-log: skip -->
saturação da decodificação OOS medida entre 0,002 e 0,005;
`jumpmodels` não expõe seleção via BIC/CV, confirmado por leitura do
código-fonte); `bocpd_hazard_lambda=65,0` (5× a mediana real de duração
de segmento do baseline, 13 barras — valor bruto é patológico, 55 mil
segmentos, confirma achado já documentado em `bocpd.py`);
`bocpd_n_canonical_buckets=3`/`jump_n_states=2` (DERIVED, PRD não
especifica K pra esses 2 candidatos, escolha justificada por
comparabilidade com o grid HMM). Commit `93723a5`.

<!-- check-sprint-log: skip -->
**Extensão pós-calibração — janelas críticas + multi-resolução**
(pedido do Manager, 2026-08-18, motivo quantificado: smoke test de 3 <!-- check-sprint-log: skip -->
meses/2 folds levou ~29min pro símbolo mais lento — histórico completo,
~15-18 folds/símbolo, levaria várias horas). Plano de extensão passou
por novo ciclo de Plan Mode + pesquisa (leitura do artefato "Biblioteca
de Testes" pra entender a metodologia real do M2 de "5 janelas críticas
em vez de histórico completo", `AG-034`). **Fase A** (`3f1502e`) —
`src/features/_sources.py::load_bars` ganha `dollar_r2`/`dollar_r3`
(R1/R2/R3 SÃO os "3 timeframes" de produção, substituíram M15/M30/H1
como identidade, `PLANO_MESTRE_PRINCE2.md` `AG-042`) — débito conhecido
não resolvido (`AG-043`, janelas do Feature Engine em contagem de barra,
não tempo real, sob R2/R3). **Fase B** (`32171f9`/`ccb50f1`) — módulo
novo `src/analysis/m4_critical_windows.py`, orquestrador de 5 janelas
(LUNA/mai-2022, FTX/nov-2022 — só BTCUSDT, sem runway suficiente nos 4
alts — Crypto Winter/jun-2023, ETF-Halving/mar-2024, Recente — 5/5) × 3
resoluções, agregação mediana-de-medianas (símbolo→janela→geral).
Aritmética das janelas verificada empiricamente contra
`generate_anchored_walk_forward_splits` real (não presumida) — achado
real: o evento-alvo cai sempre no fold 1 do walk-forward, não fold 0
(efeito de fronteira de dia civil na primeira barra real devolvida).
**Fase C** (auditoria, 3 agentes) — 1 HIGH real corrigido (`AG-083`,
`ccb50f1`: relatório só persistia depois das 3 resoluções completarem,
sem checkpoint incremental — mesmo padrão AG-019 já corrigido no M2 —
falha tardia descartaria horas de fit real).

<!-- check-sprint-log: skip -->
**Decisão de trial accounting da extensão, Manager 2026-08-18** (via
`AskUserQuestion`): resolução MULTIPLICA trial (mesmo precedente já
usado no M1, `audit/n_lifetime.yaml` id16 — cada resolução exige refit
novo) — `G-C1-2` revisado de `≤6` pra **`≤18 trials`** (6
candidatos-trial × 3 resoluções); janela histórica NÃO multiplica
(réplica de robustez, mesmo raciocínio de símbolo/fold — 5 janelas
agregadas dentro de cada trial, não 5 trials a mais). Achado de
`project_assurance`: essa revisão não estava sincronizada em nenhum
documento formal (`PRD_V4_1.md`/`docs/m4_regime_plano_execucao.md`/
`config/constants.yaml` ainda citavam `≤6`) — sincronizado nesta
atualização de governança.

<!-- check-sprint-log: skip -->
**Fase D — execução real, autorizada explicitamente pelo Manager**
(2026-08-18, `AskUserQuestion`, "estou em acesso remoto, execute você
mesmo") — 18 trials, `run_and_save_critical_windows_report`, ver
`experiments/m4_critical_windows_report.json` (checkpoint incremental
por resolução, `AG-083`) quando fechar. Ver seção "Estado atual" abaixo
pro status no momento desta atualização — **ainda em andamento**, não
presumir resultado.

<!-- check-sprint-log: skip -->
## M4 — resultado real da 4ª execução, auditoria cética, pausa, e abertura da Trilha B (2026-08-19)

**Antes da execução real: 4 achados metodológicos novos, propostos e
autorizados** (`AG-090`-`AG-093`, `audit_engineering` em cada arquivo
editado antes do run) — join causal por `close_time_ms` em vez de
`open_time_ms` (`AG-090`); `k=1` em Cochran's Q retorna `NaN` explícito
em vez de `Q=0` (`AG-091`, achado colateral: a citação original de
"metafor/meta tratam k=1 como NA" era falsa, os dois pacotes hard-codam
`Q=0` — corrigido pra justificativa própria do projeto); teste de
permutação em bloco por episódio (`AG-092`, corrige violação de i.i.d.
do Cochran's Q clássico sob autocorrelação intra-regime — a causa real
de I²=70-98% "universal" em todos os candidatos); BOCPD avaliado só na
fatia OOS real do walk-forward, não na janela crítica inteira (`AG-093`,
~5× redução de amostra). Todos implementados, auditados de forma
independente (0 CRITICAL/HIGH), Manager autorizou a 4ª execução.

**4ª execução concluída, resultado real** (`experiments/
m4_critical_windows_report.json`, 10029,9s, 0 falhas/skips): **os 18
p-valores de permutação (6 candidatos × 3 resoluções, por lado) ficam
entre 0,30 e 0,85 — nenhuma célula estatisticamente significativa**,
BOCPD incluso — sua liderança sob I² clássico (métrica pré-`AG-092`) era
artefato de autocorrelação intra-regime, confirmado pela correção: seus
próprios p-valores (0,47-0,85) estão entre os MENOS significativos.
Jump Model com poder estatístico inexistente (mediana 4 episódios/
célula, mínimo 1, 100% das 102 células <15) — resultado dele não
interpretável, causa combinada de 3 problemas independentes (decode não-
causal confinado ao fold, poder nulo, `jump_penalty` calibrado numa
fatia só de BTC nunca retestada). Tratado como achado válido (regime
construído sobre estas dimensões não modula o edge deste alpha, nestas
janelas), não como estudo com bug.

**2 auditorias externas brutas trazidas pelo Manager + validação cruzada
própria** (código real + literatura: Adams & MacKay 2007 pro BOCPD,
Nystrup/Cortese/Shu pro Jump Model, Winkler et al. pro block permutation,
Bailey/López de Prado pro DSR/PBO) — resolveu 2 discordâncias diretas
entre as auditorias (BOCPD "fit único" REFUTADO como look-ahead —
matematicamente impossível dado que a recursão é estritamente
sequencial; Jump Model λ — testar transferibilidade favorecido sobre
BIC dinâmico, literatura confirma) e achou 7 gaps que nenhuma das duas
tinha identificado. Resultado categorizado em redesenho/fix mecânico/
habilitação/rejeitado — documento completo:
`docs/m4_regime_auditoria_externa_2026-08-19_validacao_cruzada.md`.

**M4 pausado por decisão do Manager** — antes de continuar refinando
candidatos de regime, travar o contrato de quem consome regime downstream
(Alpha/Decision Engine/Meta/Risk/Execução), porque escolher método sem
saber o contrato mede a pergunta errada. Abre a **Trilha B**.

**Trilha B — contrato Regime→Alpha→Decision Engine→Meta-Label→Risk→
Execução.** 3 investigações independentes acharam 10 gaps de arquitetura
(`AG-094`-`AG-100` + addenda em `AG-007`/`AG-088`) — Decision Engine
existia no blueprint original (Parte VII) mas nunca tinha entrado no
inventário de estágios de engenharia; gate de posição "uma por vez,
projeto inteiro" nunca emendado contradiz o Controle 19 (que pressupõe
posições concorrentes); nenhum mecanismo de seleção/eliminação entre
combinações symbol×resolution existe, e o texto do próprio PRD trata
esse cenário como violação literal de banned pattern (B20) quando
acontece em pesquisa. 4 rodadas de contestação adversarial sobre as
resoluções propostas — achado real em CADA rodada (`AG-101`-`AG-105`,
incluindo um caso onde uma correção resolvia um problema diferente do
que motivou a correção anterior, `AG-105`) — nenhuma aceita sem
contestar. 4 mecanismos aprovados pelo Manager (2026-08-19): Decision
Engine no PBS; gate de posição por linha, não global; convenção
estrutural de contagem de N pra seleção de linha; gatilho de proteção
por regime via encurtamento de `time_stop` (não aperto de SL — premissa
original refutada por pesquisa de mercado). 7 decisões residuais ficam
explicitamente registradas como pendentes, não decididas por omissão —
detalhe completo em `PLANO_MESTRE_PRINCE2.md` §15.11.

**Mandato do Manager corrigido nesta sessão**: não é seleção dinâmica em
tempo real — é seleção offline, fixa por rodada, eliminação periódica
(treina cada combinação symbol×resolução de forma independente, elimina
o que não performa, opera em produção com o(s) vencedor(es) fixo(s) até
a próxima rodada). **Tiering de features (T1/T2/T3) descontinuado** —
todas as ~92 features com fonte real já wired (T1+T2 do catálogo do
`PRD_V3_2_UNIFICADO.md` Parte II) passam a ser canônicas, seleção
delegada ao próprio Learner/Meta-model — decisão registrada, ainda não
implementada em código.

**2 documentos de brief comissionados** (`docs/brief_auditoria_
externa_2026-08-19_regime_alpha_execucao.md` + `..._material_de_apoio.md`)
pro Manager levar a auditores externos — pedido de validação cética nos
4 mecanismos aprovados, recomendação nas 7 decisões residuais, desenho
técnico concreto nas 7 fronteiras de estágio (Features→Label→Pesos→
Split→Learner→Calibração→Validação→Meta-Model) que ainda não têm
contrato de dado especificado. Protocolo de triagem do retorno já
definido: verificação independente de cada achado antes de aceitar,
mesmo rigor das 4 rodadas adversariais internas — nenhum achado externo
entra direto, "veio de fora" não é atalho pra pular a contestação.

**Road Map Vivo v2 republicado** na mesma sessão (`AG-080`, disciplina
de não deixar o artefato visual driftar do texto) — mesma URL, refletindo
M4 pausado e a Trilha B aberta.

<!-- check-sprint-log: skip -->
## M4 — Gate Efficiency (AG-118), reabertura do AG-114, e HMM k=4 promovido a candidato canônico de produção (2026-08-20/21)

<!-- check-sprint-log: skip -->
**ADR-001 ratificado** (2026-08-20, §2.7) — regime é GATE de risco, não
FEATURE preditiva, na v1. Isso muda a pergunta que decide promoção de
candidato: não mais heterogeneidade de RETORNO (resultado nulo já
medido, ver seção anterior), e sim qualidade como GATE — occupancy do
estado de stress, taxa de falso-positivo de transição, heterogeneidade
de VOLATILIDADE futura entre buckets. `AG-114` trava a regra de decisão
(3 gates de desqualificação + 1 métrica primária de ranking) ANTES de
qualquer medição — disciplina anti-HARKing (B20).

<!-- check-sprint-log: skip -->
**Execução real da regra (2026-08-20)**, números extraídos direto de
`experiments/m4_critical_windows_report.json` (`by_resolution[].gate_
quality`/`.volatility_heterogeneity`): `hmm_gaussian_k4_v1` declarado
vencedor nas 3 resoluções — Gate 1 (occupancy ≤~33%) desqualifica
`hmm_gaussian_k2_v1` (34-40%, acima do teto testado), `hmm_gaussian_k4_v1`
vence a métrica primária (I²) contra `hmm_gaussian_k3_v1` nas 3
resoluções.

<!-- check-sprint-log: skip -->
**REABERTO no mesmo dia** — auditoria externa (Manager, papel de
auditor) achou que o Gate 1 foi aplicado com 2 critérios misturados
(mediana de resolução vs. máximo por janela) sem declarar qual decide.

<!-- check-sprint-log: skip -->
Sob o critério literal de mediana, no mesmo teto alternativo de 40%
(já testado como sweep de sensibilidade em `experiments/m4_critical_
windows_report.json`), `hmm_gaussian_k2_v1` PASSA o Gate 1 e VENCE a
métrica primária em 2 das 3 resoluções (I²: 97,82 vs. 97,44 em R1;
95,31 vs. 94,98 em R2 — só em R3 `k4` vence, 91,77 vs. 91,66, margem
mínima).

<!-- check-sprint-log: skip -->
`AG-114` fica **status ainda aberto** quanto à metodologia de seleção
— nenhuma decisão de re-especificar o Gate 1/Gate 3 foi tomada.

<!-- check-sprint-log: skip -->
**AG-118 (Gate Efficiency) implementado e processado ponta a ponta** —
`src/analysis/gate_efficiency.py`, mede `P(stop|regime)`/`P(target|
regime)`/`tail_loss`/`holding_time` + `lift` (remoção assimétrica de
entrada no bucket de stress) com IC 95% via método de Katz ponderado por
`n_eff` (Σuniqueness de label, reuso da infra de peso já existente no
projeto, não bootstrap inventado). Fila de diagnósticos da auditoria
externa processada inteira (R3, D1-D5, R1-R2) — achado central, medido
em `experiments/gate_efficiency_full_diagnostics_report.json`: `lift`
não desvia de 1,0 em **90 células** (3 candidatos k2/k3/k4 × 3 resoluções
× 5 símbolos × 2 lados), só 2/90 excluem 1,0 no IC (ambas marginais,
consistente com ruído puro), robusto ao candidato. Mecanismo (D1+D4,
verificado direto no código do Label Engine): `exit_price` de TP/SL
(`triple_barrier.py`) é o PRÓPRIO PREÇO DA BARREIRA — isso torna
QUALQUER métrica de tail-loss derivada de `ret_net` quase-determinística
em `atr_pct`, normalizada por ATR ou não; nem a métrica original
(ATR-normalizada) nem a reversão aparente em termos brutos (que quase
foi reportada como achado novo antes de a auto-verificação identificar
que é o MESMO mecanismo D1) são evidência independente de risco de
cauda além do que ATR já captura. `AG-118` **RESOLVIDO** — a pergunta
foi respondida (sem sinal econômico), não ficou em aberto.

**Manager autoriza `hmm_gaussian_k4_v1` como candidato de regime
CANÔNICO DE PRODUÇÃO (2026-08-21) mesmo com os 2 achados acima na
mesa** — override de negócio explícito, registrado como tal
(`PLANO_MESTRE_PRINCE2.md §15.13`), nunca como resolução da metodologia
ou alegação de edge medido. **Correção 2026-08-22**: o gate de risco
citado abaixo foi DESLIGADO nesta mesma data (`control_01_regime_
tradeavel` removido de `evaluate_all()`, commit `3c0d83d`) — a mesma
evidência negativa (`lift`≈1,0) que justificava "bloquear é barato
mesmo sem prova" acabou sendo lida, no mesmo dia, como razão pra
desligar de vez (manter ligado sob evidência negativa custava
opcionalidade, era o erro maior). `hmm_gaussian_k4_v1` segue candidato
canônico do BUILDER (ratificado, `AG-114` fechado definitivamente,
mesmo dia) — só o CONSUMO como gate mudou. Escopo completo implementado
na sessão de 2026-08-21:

- **Fase A** — regime SAI do vetor de treino do Alpha
  (`src/models/alpha.py::DESIGN_COLUMNS`, 14→10 colunas, só as features
  T1) — decisão do ADR-001 §2.7 nunca tinha sido aplicada ao código até
  agora. Efeito real represado atrás de retreino (`run_layer1_sprint()`
  não executado nesta sessão).
- **Fase B** — novo builder de produção `src/regime/build_hmm.py::
  build_hmm_regimes` (walk-forward ancorado trimestral, mesmo contrato
  de fold do M4) + `src/regime/hmm_features.py` (espaço de observação
  extraído do harness M4 pra um módulo público em `src.regime`, sem
  quebrar a hierarquia de camadas — `m4_regime_comparison.py` continua
  funcionando idêntico via re-export). Sem persistência em disco ainda
  — não há orquestrador vivo consumindo.
- **Fase C** — Risk Engine candidato-agnóstico (`src/risk/limits.py`):
  `control_01_regime_tradeavel`/`RiskEngineInputs` deixam de decodificar
  vocabulário `R1..R4`, passam a receber `regime_tradeable: bool` já
  resolvido pelo builder — mesmo campo alimentado por baseline ou HMM
  sem tradução, evita reintroduzir o erro que `AG-121` já documenta.
- **Fase D** — `canonical_regime_hmm_n_states=4` em `constants.yaml`,
  classe B, `provenance: MEASURED` com a narrativa completa do override
  (não uma medição limpa) no campo `source`.
- **Fase E** — testes novos (`test_regime_hmm_features.py`, `test_
  regime_build_hmm.py` — valor conhecido via ARI, caso degenerado sem
  exceção, fold individual degenerado isolado via monkeypatch
  determinístico, causalidade/prefix-invariance do loop de fold,
  determinismo) + `test_risk_limits.py`/`test_models_alpha.py`
  atualizados. 78 testes rápidos + 4 `slow` confirmados passando pelo
  Manager.
- **Fase F** — `PLANO_MESTRE_PRINCE2.md §15.13` documenta o override;
  `AG-114` ganha campo `status_override_producao_2026_08_21` (append,
  status antigo preservado) — **AG-114 continua tecnicamente aberto**.

<!-- check-sprint-log: skip -->
**Achados colaterais desta sessão**: `AG-120` (BNBUSDT/RECENTE/R2,
desalinhamento de timestamp, isolado por `AG-019`, não investigado a
fundo); `AG-121` (canonicalização por RETORNO, não volatilidade —
ADR-001 recomenda volatilidade, código segue o critério do PRD
obsoleto — mitigado via docstring, migração completa pendente do action
item 3 do ADR-001); `AG-122` (achado mecanístico central de AG-118,
detalhado acima); `AG-123` (rodada de "Atualize governança" desta
sessão: `PLANO_MESTRE_PRINCE2.md §15.2/§15.4` ficaram desatualizadas no
MESMO commit que mudou os fatos que descreviam — Risk Engine ganhou
caller, Alpha perdeu regime — só achado porque esta rodada leu o
documento inteiro; mesma classe de furo de `AG-080`, recorrente,
corrigido pontualmente sem processo que previna a 3ª ocorrência). Rodada
de governança também achou e corrigiu 2 bugs de sintaxe YAML
PRÉ-EXISTENTES em `audit/evidence_ledger.yaml` (`#N`/`:` sem aspas
dentro de escalar multi-linha, interpretado como comentário/nova chave
pelo parser — nunca detectado antes porque o arquivo nunca tinha sido
validado com `yaml.safe_load` estrito).

<!-- check-sprint-log: skip -->
**Road Map Vivo v2 republicado** na mesma sessão (mesma URL) —
hero-meta, card M4, card AG-114/AG-118 na Trilha B, `12_RISK_ENGINE`,
governança aberta (2 cards novos) e "Próximos passos" (lista inteira
trocada pela fila real pós-resultado) todos atualizados.

<!-- check-sprint-log: skip -->
**Nova skill `stage_readiness_audit` (v1.1) criada e usada na mesma
sessão** — decisão do Manager de gatear retreino do Alpha até o Data
Layer (`01_BARRA`–`07b_PESOS`) + `08_SPLIT` estarem 100% prontos exigiu <!-- check-sprint-log: skip -->
uma auditoria real de prontidão, não só releitura de doc. Skill combina
as 4 lentes de `audit_engineering` (FS/FI/FT/FCN) com uma 5ª lente nova <!-- check-sprint-log: skip -->
(System Design/Rota pra Produção), portada do "Feature Development
Plugin" (Anthropic) fornecido pelo Manager, com 4 gaps corrigidos após <!-- check-sprint-log: skip -->
revisão do Manager (autorização de implementação explícita no Passo 1, <!-- check-sprint-log: skip -->
sintaxe de invocação, escala de severidade citada, tratamento de
cluster misto código+Pendente).

<!-- check-sprint-log: skip -->
**Fan-out de 5 clusters rodado (só leitura/investigação, sem
implementação autorizada nesta rodada)** — `Barra+Data Check`,
`Features`, `Volatilidade+Regime`, `Barreiras+Label+Pesos`, `Split`, um
`Agent` por cluster. Resultado: **36 achados** (3 CRITICAL / 8 HIGH / 12 <!-- check-sprint-log: skip -->
MEDIUM / 13 LOW) em 9 estágios — **nenhum chega a 100% pronto**. 5 <!-- check-sprint-log: skip -->
bloqueadores que cascateiam, em ordem de impacto: (1) `AG-100` (labels <!-- check-sprint-log: skip -->
ausentes R2/R3, confirmado por 3 clusters, puramente execução); (2) <!-- check-sprint-log: skip -->
achado NOVO mais fundamental que `AG-100` — calibração não-causal do <!-- check-sprint-log: skip -->
threshold da dollar-bar (deriva 18,18x medida, afeta a GRADE, não só o
threshold da dollar-bar (deriva 18,18x medida, afeta a GRADE, não só o
conteúdo — `AG-124`); (3) `AG-032` quantificado pela 1ª vez — margem
NEGATIVA de ~7,6h em H1 pro `max_feature_lookback_ms` nunca wireado,
indeterminada em dollar-bar (addendum `AG-032`); (4) achado NOVO —
`build_hmm_regimes::is_stress_state/tradeable` calculado globalmente
por chamada, não causal por fold (`AG-127`); (5) trilha de auditoria do
Label Engine órfã desde 2026-08-09, 6 reprocessamentos reais sem
registro (`AG-128`). Relatório consolidado publicado como artefato
(`stage_readiness_audit_data_layer_2026-08-21.md`).

<!-- check-sprint-log: skip -->
**21 fixes mecânicos delegados a 6 agentes paralelos + execução real
autorizada (`uv`/`pytest`), auditados ao concluir** — commit `d592bc6`.
Implementado: `validate_dollar_bars()` (dollar bar nunca passava pelo
Data Quality Engine, `AG-133`); `QualityReport` ganha campo `symbol`
(`AG-125`, parcial — migração retroativa dos 5 relatórios existentes
segue decisão pendente); testes parametrizados nos 5 símbolos em
Features/Split (`AG-130`); `hmm_gap_check.py` novo — triagem de gap <!-- check-sprint-log: skip -->
antes do HMM consumir dollar-bar, baseline já tinha via `s06_bar_gap` <!-- check-sprint-log: skip -->
(`AG-132`); `experiment_log.record_experiment` finalmente wireado no <!-- check-sprint-log: skip -->
caminho real de produção do Label Engine + `LabelBuildStats` persistido
(`AG-128`); `_g_end_effective` extraída em `cpcv.py`, estava duplicada <!-- check-sprint-log: skip -->
(mesma classe `AG-009`, `AG-129`); `report_provenance()` em relatórios <!-- check-sprint-log: skip -->
de leakage (`AG-131`). **Não implementado, por decisão correta do <!-- check-sprint-log: skip -->
agente**: wireup de `max_feature_lookback_ms` — 3 das 10 features T1 <!-- check-sprint-log: skip -->
ativas têm `lookback_bars: expanding` (sem limite finito honesto),
agente recusou inventar heurística em vez de reportar o bloqueador
(ver addendum `AG-032` acima). **Bônus**: bug pré-existente achado e
corrigido em `test_analysis_gate_efficiency.py` (dado sintético
ancorado em epoch 0, não relacionado a nenhum dos 6 agentes, confirmado
via `git log`). **Risco de processo observado**: 2 dos 6 agentes
rodaram `git stash` sem autorização (só leitura/`git log` liberado)
durante escrita paralela — autodenunciado, sem perda de dado (verificado
via `git status` cruzado contra os 6 relatórios); recomendação: proibir
`git stash` explicitamente em prompts futuros de multi-agente, não só
omitir da lista de autorizados.

<!-- check-sprint-log: skip -->
**Registro `AG-124`–`AG-133` + addendum a `AG-032`** —
`audit/architecture_gaps_log.yaml`. 4 abertos (decisão pendente do
Manager): `AG-124` (calibração não-causal do threshold, 18,18x),
`AG-126` (ambiguidade de sequenciamento do catálogo de features),
`AG-127` (`build_hmm_regimes` não-causal). `AG-125` parcial (schema
corrigido, migração retroativa pendente). 6 fechados: `AG-128`,
`AG-129`, `AG-130`, `AG-131`, `AG-132` (função pronta, sem caller de <!-- check-sprint-log: skip -->
produção ainda), `AG-133`. <!-- check-sprint-log: skip -->

**`AG-124` (calibração causal do threshold dollar-bar) — linha de
investigação concluída (2026-08-21/22).** Implementação real:
`build_dollar_bars_walkforward` (`src/data/build_dollar_bars.py`)
recalibra causalmente por período (`[app_start-trailing_window_days,
app_start)`, estritamente anterior); `ThresholdBarsCarry` agora
persiste através da fronteira de período (item 14 — 1 barra
subdimensionada por RODADA, não por período); lead-in buffer recupera
histórico real antes de `start` pra calibração (item 15); circuit
breaker (`max_leftover_trades`) validado com folga contra pico de
volume ~14x medido (item 16). Semântica de troca de threshold com
barra em aberto — antes implicitamente indefinida — formalizada e
testada com asserts de valor exato.

Decisão de parâmetro, após 6 rodadas de auditoria externa (parecer +
adendo genuínos, mais 1 documento descartado por não-confiável —
colisão real de numeração `AG-125`): `trailing_window_days=7` (elimina
aliasing de sazonalidade semanal, medido). `cadence_days=7` preferido
sobre `cadence_days=1` — `C=1` vencia a métrica de rastreio de
calibração por margem grande nos 5 símbolos (robusto a sweep do corte
de decisão), mas exercita 7,25x mais eventos de transição de threshold
(365 vs. ~52/ano/símbolo — cada evento viola o invariante que define
uma dollar-bar). Retorno `|z|` associado a evento de fronteira é maior
sob `C=1` que sob `C=7` na mesma janela de calendário (teste decisivo
contra confundimento de hora-do-dia, 5/5 símbolos) — elo real, modesto.
Decisão apoiada também em 3 argumentos de engenharia de sistema:
tipo de erro (suave em `C=7`, absorvido por feature normalizada;
discreto em `C=1`, nada absorve, relevante com ~79 features futuras
ainda não avaliadas); assimetria de custo de estar errado (sem métrica
de sucesso final registrada — confirmado —, `C=7` errado é reversível/
barato); superfície de paridade lote↔streaming ao vivo (`src/live/`
ainda vazio, `C=1` multiplica por 7x os pontos de divergência
backtest↔produção). Constantes registradas em `constants.yaml`
(`dollar_bar_walkforward_trailing_window_days`/`_cadence_days`,
`provenance: MEASURED`). **Reprocessamento real dos 5 símbolos × 3
resoluções disparado** (`tools/diagnostics/run_ag124_production_
reprocessing.py`, `data/capacity/dollar_bars_r{1,2,3}/`, substitui
calibração não-causal antiga). `AG-120` (desalinhamento `t0`/
`open_time`) — varredura completa das 51 células da amostra do M4
confirmou escopo ISOLADO (só a célula já conhecida diverge), não
sistêmico. Histórico completo de retratações honestas (2 achados que
pareciam sólidos e foram corrigidos após teste decisivo proposto por
auditoria externa) preservado em `docs/plano_acao_ag124_pos_auditoria_
2026-08-21.md` e `audit/architecture_gaps_log.yaml::AG-124` (10
addenda) — nada escondido, inclusive o que mudou de lado.

**S1 (sweep `tp_atr_mult`/`sl_atr_mult`) aberto na sequência** — maior
lacuna aberta do projeto (constantes classe A, `sweep_required: true`
desde sprint_6, nunca executado; definem a variável dependente de todo
experimento de M4/AG-114/AG-118 já medido). Desenho iniciado via skill
`redesign_workflow` (Fase 1-4, não implementado ainda): reparametrização
obrigatória `R=tp_atr_mult/sl_atr_mult` (controla o breakeven implícito)
× `S=sl_atr_mult` (controla taxa de eventos/holding time) — mesmo erro
de acoplamento que `T`/`C` do AG-124 custou 6 rodadas de auditoria pra
descobrir, não repetido aqui por desenho. Achado real da exploração de
código (Fase 2): **já existe um motor vetorizado quase pronto**
(`src/labels/barrier_sweep.py` + precedente real `src/analysis/
faixa2_caminho_b.py::run_fase2_e1`, grade 3×3 já rodada uma vez) — o
fill não depende de `tp_atr_mult`/`sl_atr_mult`, então o sweep pode
resolver TP/SL/TIME vetorizado sobre uma população de trades já
preenchida, sem rodar o Label Engine escalar 9× por símbolo. Design doc
+ auditoria independente (`project_assurance`) em andamento.

**Fechamento do dia seguinte (2026-08-22)** — 2 marcos concluídos:

1. **Reprocessamento real do `AG-124` CONCLUÍDO**: 15/15 células (5
   símbolos × 3 resoluções), zero erro
   (`experiments/ag124_production_reprocessing_summary.json`). Item 22
   do plano de ação (validação sobre dado REAL, histórico completo, não
   amostra — script novo `tools/diagnostics/measure_ag124_post_
   reprocessing_validation.py`) deu resultado **positivo**: curtose em
   excesso praticamente inalterada ao excluir barras de fronteira (ex.
   BTCUSDT/R1 53,12 vs. 53,15) — sobre a série real completa, o artefato
   de recalibração que motivou 6 rodadas de auditoria é desprezível; a
   curtose alta observada é 100% evento de mercado genuíno (as 5 barras
   mais extremas por célula batem com Celsius/3AC jun/2022, Black
   Thursday COVID mar/2020, colapso FTX nov/2022 — inclusive coincidindo
   quase exatamente com `m4_ftx_event_onset_ts_ms` já registrado no M4).
   Achado colateral não-bloqueante, `AG-137`: o 1º período (cold-start,
   sem histórico causal válido) é corretamente pulado na escrita, mas o
   arquivo `.parquet` da calibração NÃO-causal antiga que já existia
   nesse caminho não é removido — `cadence_days` (=7) dias iniciais de
   cada uma das 15 células ainda refletem o método antigo, excluído da
   medição do item 22 por discriminador de schema, decisão de limpeza
   pendente do Manager.
2. **Design doc do S1 concluído e auditado**: síntese de 2 agentes
   `code-architect` independentes (foco reuso mínimo / foco rigor de
   contrato) + decisão de arquitetura própria (sem maquinária ADR-001
   Parte II — não ratificada, não implementada em nenhum lugar do repo
   hoje). `project_assurance` (nível meta, auditando o documento, não
   código) achou 4 achados HIGH reais — função "promovida" que quebraria
   por coluna ausente, 2ª célula de grade fora de faixa não capturada,
   `assert` de identidade sem guarda de `NaN` que abortaria a execução
   inteira, contagem de trial (9 vs. 18 vs. 1) decidida em silêncio sem
   confrontar a regra escrita do próprio `n_lifetime.yaml` — todos
   corrigidos no documento. Nenhum invalida a decisão de arquitetura
   central. `docs/s1_design_doc_sweep_tp_sl_reward_risk_2026-08-22.md`,
   8 riscos explícitos aguardando decisão do Manager antes da Fase 5
   (implementação).

**Meta-model — arquitetura ponta a ponta travada, e um contrato canônico
revogado (2026-08-22).** Pedido do Manager: desenhar o Meta-model ponta a
ponta, incluindo como ele consome Regime. Conduzido via `redesign_workflow`
(7 fases). Logo na Fase 3 apareceu uma contradição direta entre o pedido e o
documento canônico: o **ADR-001 §2.7**, ratificado pelo próprio Manager em
2026-08-20, diz que *regime NÃO entra como feature do Meta* e que "as 5
condições de entrada não mencionarem regime está certo, não é lacuna".
Apresentada a contradição, o Manager **revogou o contrato canônico do
Meta-Labeling** (§3.7/§2.7 do ADR-001) e pediu base nova: AFML primeiro,
literatura moderna depois.

A pesquisa **sustentou a revogação**. Três fontes independentes tratam regime
como input do secundário — inclusive o **código aberto do experimento
canônico** do framework formal de meta-labeling (Joubert, `fp_modeling.py`),
que implementa um braço explicitamente regime-aware. E o argumento decisivo é
deste motor, não da literatura: sem uma vantagem informacional — um input que
o primário não tem — meta-labeling não tem mecanismo, cai na regressão
infinita e só adiciona variância. **Regime saiu do vetor de treino do Alpha em
2026-08-21** (Fase A do §15.13): a remoção do one-hot criou, sem querer,
exatamente a vantagem que o Meta precisa. A evidência contrária de `AG-118`
(`lift ≈ 1,0` em 90 células) não foi descartada — ela mede o lift
**incondicional**, e a única hipótese que ela não fecha (regime separa TP de
SL *dentro dos sinais do Alpha*?) virou o Gate E0 do desenho.

**Uma segunda decisão do Manager foi revertida na mesma sessão, por medição.**
Ele havia decidido construir o modelo de fila (Grupo J) antes do Meta. Três
fatos verificados em `src/labels/triple_barrier.py` e
`src/execution/fill_simulator.py` derrubaram a ordem: `NOFILL ⟹ ret_net = 0.0`
literal (`src/labels/triple_barrier.py:961`) torna a marginalidade de PnL de
`p_fill` **exatamente zero** — um `p_fill` perfeito filtraria ~3% dos sinais,
cada um contribuindo zero; `cost_est_bps` é redundante com o alvo
(`src/labels/triple_barrier.py:1317`), não marginal a ele; e
`calibrate_against_real_fills` (`src/execution/fill_simulator.py:851`) depende
de fills de Testnet/Paper que vêm **depois** do Decision Engine que consome
`p_meta` — circular. Somado à cobertura de 10,5 meses em bloco contíguo de
calendário (`src/execution/fill_simulator.py:148-149` — carimbo de data
disfarçado de feature), o Grupo J foi **realocado** para depois do Meta, não
desqualificado (segue valioso para rotação de capital, no Risk/Decision
Engine).

**A auditoria adversarial de 3 flancos foi o passo mais produtivo da sessão.**
Rodada via `/engineering:architecture` em modo *evaluate a design*: corretude
factual contra o código, rigor estatístico, e trade-offs/alternativas.
Resultado sobre o desenho v1: **6 CRITICAL, ~20 HIGH**, 95 afirmações
verificadas (73 corretas), **40 correções** incorporadas numa v2. As quatro
que mudaram decisões, todas verificadas em `src/validation/cpcv.py` e
`src/models/alpha.py`: (1) **uma prova de impossibilidade do v1 era FALSA** —
o documento afirmava que não existe fold doador simultaneamente OOF e cego e
que cegueira total custaria ~6× o treino; ambas falsas, a prova tinha dois
quantificadores escondidos, e como `src/validation/cpcv.py:329-337` gera
C(6,2)=15 folds (todos os pares), a construção blindada custa **zero
retreino** — o custo real é 1 caminho OOS em vez de 5; (2) `score_raw` fora
do design matrix por argumento de colinearidade errado —
`IsotonicRegression` (`src/models/alpha.py:262-263`) é *many-to-one* e
**destrói** informação, e o Meta vive no topo da escada onde `p_alpha` pode
ser constante; (3) o purge cross-símbolo **não é fraco, é ausente** —
`assign_time_groups` (`src/validation/cpcv.py:259-292`) faz `linspace`
per-símbolo, logo históricos diferentes produzem fronteiras de grupo em datas
diferentes e uma linha de treino de BTC pode ser contemporânea de uma de
teste de ETH sem o purge ver (`AG-151`, bloqueante); (4) **os gates não
gateavam** — cinco defeitos somados inclinavam a decisão a PASS, incluindo o
Gate E0 com 50 células e nenhuma regra de agregação, que é literalmente
`AG-114`/`AG-122` reproduzido no gate mais consequente do documento.

O padrão da falha foi nomeado no próprio documento para não se repetir: *os
riscos eram identificados com precisão e depois **mitigados por declaração em
vez de mecanismo*** — o FLAG que só imprime, a escrita "condicionada" sem
enforcement, o "bit-exato" operacionalizado como "os testes passam".

**E o item 1 do protocolo de governança preveniu um erro real.** O design doc
afirmava, em três versões, que "não existe `save_model` em lugar nenhum de
`src/`" e propunha abrir um AG novo para persistência. Errado: `AG-141`,
`src/models/persistence.py` e `src/io/artifact.py` foram construídos no
**mesmo dia**, em paralelo. O levantamento fora feito antes desses commits.
Corrigido: o Meta **reusa** a infraestrutura, nenhum AG duplicado foi aberto,
e o que se registra é a dependência (F5 do Meta depende da integração do
`AG-141` no Alpha). É exatamente o furo que "commits ANTES de tocar em docs"
existe para prevenir.

**E então a v2 foi submetida a `project_assurance` — e não passou.** A
auditoria adversarial de 3 flancos tinha elevado muito o nível factual, mas a
v2 que nasceu dela **nunca foi revisada por ninguém**. Dois revisores
independentes (PRINCE2 §6.4, sem acesso ao raciocínio do produtor)
re-derivaram ~110 alegações `arquivo:linha`: **~102 corretas** — a acurácia
factual se sustentou — e **3 CRITICAL + 4 HIGH** estruturais. Veredito: *"não
é base sólida para implementar"*.

O pior deles: **`group_matched`, o braço de CV que a v2 apresentava como
"estritamente melhor, cegueira total", não tinha purge nem embargo — era o
único dos dois sem B09.** `generate_splits` rejeita `n_test_groups != 2`
(`src/validation/cpcv.py:544-548`), logo sob 1 grupo de teste não existe
`CPCVSplit` nem `train_idx` — o único objeto que carrega purge; e as linhas de
treino do Meta ficam no `test_mask` do fold doador
(`src/validation/cpcv.py:565`). A v2 ainda fechara a porta para a correção ao
declarar que `edges_ms` seria a "única mudança em `cpcv.py`". O segundo: o
**Gate E0 não tinha esquema de permutação declarado**, e o único precedente do
repo é i.i.d. linha a linha (`src/models/baselines.py:819`) — com rótulos
sobrepostos e regimes em blocos contíguos, isso faria **o gate que decide se o
Meta existe ser o mais fácil de passar do documento inteiro**. O terceiro: o
nulo A2 replicava **1 de 5** fontes de otimismo, com o problema declarado
resolvido.

**A lição de processo vale mais que os achados.** Em
`docs/meta_model_design_doc_2026-08-22.md`, a versão anterior diagnosticou o
próprio padrão de falha com precisão cirúrgica — *"riscos identificados com
precisão e depois mitigados por declaração em vez de mecanismo"* — e
**repetiu o padrão exatamente nas três peças que apresentava como suas
maiores conquistas**. Uma
auditoria adversarial genérica não pegou isso; foi preciso uma segunda rodada,
com skill diferente e mandato diferente (integração, não qualidade). Duas
lentes distintas não foram redundância — foram o que separou um documento que
parecia pronto de um que estava.

**Status: v3, 17 decisões travadas, ZERO linhas implementadas**
(`docs/meta_model_design_doc_2026-08-22.md`, `PLANO_MESTRE_PRINCE2.md`
§15.19). O caminho antes de `src/models/meta.py` existir foi **reordenado pela
revisão**: travar e **validar** o nulo do E0 primeiro, depois o purge
cross-símbolo (`AG-151`), depois o diagnóstico de saturação isotônica, e só
então E0-piloto — rodar o gate antes de o nulo estar calibrado é gastar o
gate. `AG-150` (persistir `tau`) saiu do "caminho de 20%": `tau` só existe
dentro do processo de treino, então popular exige **retreinar**, e a v2
afirmava custo zero. Falha do E0 ⟹ o Meta sai do roadmap com evidência em
`audit/evidence_ledger.yaml`. AGs novos da revisão: `AG-153` a `AG-156`.

## Alpha multi-ativo × multi-resolução (LightGBM + GPU) — arquitetura ponta a ponta travada (2026-08-22) <!-- check-sprint-log: skip -->

Pedido do Manager: *"Alpha atual é um legado do motor antigo BTC only e
single time-frame M15, além de ser XGBoost. Seu desafio é desenhar a
arquitetura tecnica ponta a ponta do Alpha multi ativo, multi time-frame R1,
R2 e R3 com LightGBM ou Catboost."* Documento completo:
`docs/alpha_model_design_doc_2026-08-22.md` (v3), governança em
`PLANO_MESTRE_PRINCE2.md` §15.20.

**O achado central não era onde a pergunta apontava.** Multi-símbolo (5
ativos) e multi-resolução (R1/R2/R3, dollar-bar) já estavam prontos em
produção — `_BAR_SOURCE_BY_RESOLUTION` (`src/models/dataset.py:80-84`)
mapeia as 3 grades desde `AG-100`/`AG-124` (trabalho de engenharia
concluído no mesmo dia deste desenho, commit `7924f2c`). A frente que
faltava de verdade era só o learner. Consequência: 18 decisões (D-01..D-18)
cirúrgicas — trocar XGBoost por LightGBM, estender a orquestração de 5 para
15 combinações (função já aceita `resolution_id`), corrigir débitos
estruturais de schema pelo caminho.

**Três decisões de escopo travadas antes do desenho:** só desenho (Fase 4,
mesmo padrão do Meta-model v3); learner = LightGBM, mantendo `§15.14` (não
reaberto, CatBoost descartado); grão de treino = modelos independentes por
(símbolo, resolução), sem pooling em v1 — pesquisa AFML (`§8.5`) + caso de
uso 2026 (arXiv:2505.08180, ganho de R² medido sob boosted trees) citados
para justificar pooling como evolução **gated** em `AG-151`, não decisão
silenciosa.

**Duas rodadas de revisão independente** sobre
`docs/alpha_model_design_doc_2026-08-22.md`, mesmo padrão do Meta-model v3.
Auditoria adversarial (3 revisores, v1→v2): 1 CRITICAL — `tau_long`/
`tau_short` (D-05) não verificado contra o `tau_alpha` que o Meta-model v3
trava literalmente, produziria `LegacyPredictionsError` **permanente** em
produção — mais 6 IMPORTANT/MODERATE (compatibilidade retroativa de
`predictions.parquet` nunca tratada, nenhuma seção de DoD/testes, purge do
CPCV medido em wall-clock sub-protegendo R2/R3, sweep de hiperparâmetro <!-- check-sprint-log: skip -->
compartilhado como canal de vazamento cross-símbolo, determinismo bit-exato
do LightGBM tratado como herdado sem verificação).

`project_assurance` (foco de integração, v2→v3, mesmo
`docs/alpha_model_design_doc_2026-08-22.md`) achou que o problema de
`tau_alpha` era maior do que a v2 resolveu: o nome/formato já estava travado
em **mais dois** artefatos de governança (`PLANO_MESTRE_PRINCE2.md`, campo
`status` de `AG-150` em `audit/architecture_gaps_log.yaml`) que a v2 não
tinha visto, ambos mais próximos da correção proposta para o Meta do que da
decisão real de D-05 — **não é um patch de 2 documentos, é 3 artefatos que
já diziam uma coisa enquanto D-05 decidia outra, escalado ao Manager
(`AG-162`, CRITICAL)**. Achou também que o documento citava `AG-100`/
`AG-124` como "fechados" 3× quando o status formal de ambos continua
`"aberto"` em `audit/architecture_gaps_log.yaml` — corrigido, também
escalado (`AG-163`, HIGH). E que o documento em si estava não commitado e
sem âncora de governança (`AG-161` — esta seção e `PLANO_MESTRE_PRINCE2.md`
§15.20 fecham essa lacuna).

**GPU (D-18 de `docs/alpha_model_design_doc_2026-08-22.md`), pedido direto
do Manager, aplicado aos dois motores.** Para o Alpha, direto (learner já
travado). Para o Meta (`docs/meta_model_design_doc_2026-08-22.md`), colidia
com uma decisão já travada — LightGBM é braço **bloqueado** por padrão no
Meta v3 (`D-02`, `MetaLearnerBlockedError` incondicional, default real é
logística L2, porque boosting exige amostra 2-3× maior pra mesma
calibração). Esclarecido: GPU configurado no braço bloqueado para quando/se
o gate abrir, sem desbloquear nada agora. Três ressalvas declaradas no
D-18, não escondidas: pré-requisito de build GPU-enabled via `uv` não <!-- check-sprint-log: skip -->
verificado, tensão real com o determinismo bit-exato de reload já exigido
(`deterministic` do LightGBM é mais forte em CPU que em GPU), payoff de
desempenho não medido (`TBD`).

**Status: v3, 18 decisões travadas, ZERO linhas implementadas.** AGs novos
da revisão: `AG-157` a `AG-164`. Duas pendências escaladas ao Manager, não
fecháveis por revisão: `AG-162` (qual desenho de `tau_alpha` vale) e
`AG-163` (confirmar fechamento formal de `AG-100`/`AG-124`, responder se o
reprocessamento cobre features/regime/CPCV). Bloqueado por: gate "Data Layer
100%" (0/9 estágios livres de gap conhecido, inalterado por este desenho).

**Motor multi-timeframe R1/R2/R3 — mapa de dívida técnica BTC/M15 residual,
Grupo 1+2 implementados e validados (2026-08-22).** Sweep de 10 agentes
paralelos varrendo `src/` inteiro (130 arquivos) atrás de código que ainda
travava em BTC-only/M15 — 10 achados reais (`AG-165`–`AG-179`). Grupo 1
(sem pré-requisito externo: `fill_simulator.py`, `models/_paths.py`+
`regime/_paths.py`, `dataset.py`, `fill_model.py`) e Grupo 2 parcial
(`validate.py` — código generalizado; `registry.yaml` deliberadamente NÃO
tocado, freeze ativo `AG-126`) implementados, commit `72e02c7`.

<!-- check-sprint-log: skip -->
Revisão independente (`audit_engineering`, `AG-170`-`AG-173`, fan-out de 3
auditores paralelos, sem contato com o raciocínio da implementação) achou
<!-- check-sprint-log: skip -->
e a mesma rodada corrigiu **2 CRITICAL reais** (`AG-170`, `AG-171`) que a
implementação original não previu:
`load_filters_asof` sem tratamento
crashava a JANELA DEFAULT INTEIRA de `simulate_window()` (único snapshot
de `exchangeInfo` em disco é posterior a toda a janela histórica do
módulo, `AG-170`) — corrigido com `historical_filters_fallback` opt-in, <!-- check-sprint-log: skip -->
mesmo padrão já provado em `triple_barrier.py`; e `resolution_id` fora de
BTCUSDT/R1 crashava com `FileNotFoundError` sem contexto acionável
(`AG-171`). Mais 1 HIGH (`AG-172`, zero medido vs. nunca medido
conflados) e 1 MEDIUM (`AG-173`, cobertura de teste incompleta)
corrigidos no mesmo commit; 2 achados HIGH/MEDIUM pré-existentes em
`validate_resampled_bars` (`AG-174`/`AG-175`, finge "PASS" sem checar
nada de fato) ficaram registrados, não corrigidos (fora do escopo do
achado original).

1682 testes (suíte completa) verdes, sem regressão, `lint-imports` 7/7
mantidos. Achados fora do escopo desta rodada, mapeados em desenho
profundo mas não implementados: `src/regime/stress.py`/`classifier.py`
(`AG-177` — convergência confirmada com investigação independente da
sessão paralela, `docs/regime_feature_engine_design_doc_2026-08-23.md`,
que passa a ser a referência primária) e o purge do CPCV em
`pipeline.py:427` (`AG-178`, duplicata confirmada de `AG-159`, já
registrado pela auditoria adversarial do Alpha). Detalhe completo:
`PLANO_MESTRE_PRINCE2.md §15.21`.

**`docs/regime_feature_engine_design_doc_2026-08-23.md` evoluiu v1→v3 na
mesma sessão paralela** (auditoria adversarial + `project_assurance`,
mesmo processo em duas camadas já usado pro Alpha `§15.20`). Achado mais
importante: `project_assurance` pegou, ANTES de virar código, que a
correção de S6 proposta na v1/v2 (portar `hmm_gap_check.
check_bars_gap_before_hmm`, já ratificada por `AG-132`) introduziria uma
nova instância de B02 — mediana/MAD calculadas sobre a série inteira, o
que é seguro no uso original (diagnóstico único, não-causal) mas viola o
contrato causal explícito do `RegimeClassifier` Protocol se plugado numa
função por-barra dentro da composição de regime. Corrigido na v3 (
computação expansiva, mesma disciplina de `expanding_percentile_rank_
strict`). Mais 3 achados reais: escopo de `AG-159` (purge do CPCV)
ampliado — 2º call site em `src/validation/leakage.py:792`, não só
`pipeline.py:427`; mapeamento de consumidores de `regime` corrigido —
`environments.py`→`monotonic.py`→`monotone_constraints` já consome
`regime` em produção real (`AG-088` addendum), não só diagnóstico; gap
genuinamente novo registrado (`AG-180`) — histerese em contagem de barra
(`regime_confirmation_bars`/`min_warmup_bars`) amarrada a relógio, mesma
classe de `AG-030`, achado prévio (`docs/refactor_dollar_bar_
canonico.md:206-207`) nunca antes fechado por nenhum AG. Zero linhas de
código implementadas. Detalhe completo: `PLANO_MESTRE_PRINCE2.md §15.21.1`.

**D-01/D-02 implementados, commit `6902352` (2026-08-23).** S6
(`stress.s06_bar_gap_dollar`, nova) ganhou versão causal/expansiva via
`pl.Series.rolling_median` deslocada em 1 posição — reusa a implementação
nativa do Polars pra manter O(n log n) em vez de custódia de estrutura de
dados própria, sem abrir mão da causalidade que a v3 do design doc exigia.
`StressInputs`/`compute_stress_triggers`/`QuantileRegimeClassifier`/
`build_regimes` propagam `bar_source` ponta a ponta (fecha `AG-177`).
`compute_max_feature_lookback_ms` ganhou `resolution_id`, os 2 call sites
(`pipeline.py`/`leakage.py`) mudaram juntos (fecha o componente de UNIDADE
de `AG-159` — a ressalva de MAGNITUDE do proxy p99 segue aberta, sem
guarda de runtime, B23). Revisão independente (`project_assurance`, 2
agentes paralelos, um por decisão de desenho) achou e a mesma rodada
corrigiu **1 achado real antes do commit** (`AG-183`): a primeira versão
<!-- check-sprint-log: skip -->
de `s06_bar_gap_dollar` usava critério BILATERAL de anomalia
(`abs(modified_z) > threshold`), divergente do precedente citado
<!-- check-sprint-log: skip -->
(`hmm_gap_check.py`, unilateral) e semanticamente errado — S6 detecta
AUSÊNCIA de barra, não excesso de atividade; uma rajada de liquidez sob
dollar-bar dispararia stress sem motivo real, mudando `monotone_
constraints` do Alpha via `environments.py`→`monotonic.py`→`alpha.py`.
Corrigido pra unilateral antes de qualquer treino real rodar sob o
<!-- check-sprint-log: skip -->
comportamento incorreto. Mais 2 achados menores corrigidos no mesmo ciclo
<!-- check-sprint-log: skip -->
(`AG-181`, cobertura de teste do gate de segurança sob a combinação real
`resolution_id`+`feature_ids`; `AG-182`, docstring overclaiming). Um bug
de fixture pré-existente (`test_regime_build.py`, faltava coluna
`close_time`) também corrigido — não era bug de produção. `1695 passed,
0 failed` (suíte completa `-m "not slow and not integration"`). Fora de
escopo, como previsto: `AG-180` (D-04) e §11 do design doc (caminho HMM)
seguem sem código. Detalhe completo: `PLANO_MESTRE_PRINCE2.md §15.21.2`.

**Fecha `AG-174`/`AG-175`/`AG-176`, entrega medição pra `AG-180` (commit
`d44c7f9`, 2026-08-23).** `validate_resampled_bars` (`src/data/
validate.py`) tinha `missing_bars`/`duplicates`/`invalid_rows` literais
hardcoded em `0` — corrigido reusando `validate_klines_like` por inteiro
(schemas novos `BARS_15M`/`BARS_30M`/`BARS_1H` em `schemas.py`, `grid_
step_ms` via `resample.step_ms`, fecha `AG-174`/`AG-175`). `AG-176`
(guarda `resolution_id` duplicada em 4 pacotes) fechado com a opção B do
Manager — script mecânico novo (`tools/lint/check_resolution_id_guard_
parity.py`) confirma as 4 cópias comportamentalmente idênticas, sem
remover a duplicação. `AG-180` (histerese sob dollar-bar) ganhou script
de medição (`tools/diagnostics/measure_regime_hysteresis_bar_window_
duration.py`, mede janela real de N barras consecutivas, não percentil
<!-- check-sprint-log: skip -->
de 1 barra extrapolado) — **rodado pelo Manager no mesmo dia**
(`experiments/regime_hysteresis_bar_window_duration.json`, 45/45
combinações). Achado real: pra `min_warmup_bars=200`, a mediana da
janela sob R1 fica próxima do equivalente de 15m (~50h), mas R2 sai
~2× maior e R3 ~4× maior — o warmup fica MAIS longo em resolução mais
grosseira, não mais curto como a suspeita original ("40 segundos numa
rajada") isoladamente sugeria; as duas coisas coexistem (mediana cresce
<!-- check-sprint-log: skip -->
com a resolução, mas o pior caso de rajada — `p1` — ainda produz janelas
<!-- check-sprint-log: skip -->
de 25min a poucas horas dependendo do símbolo). `AG-180` segue `aberto`
— medição não decide a fórmula de conversão, decisão fica com o
<!-- check-sprint-log: skip -->
Manager. Achado real durante a implementação: os 3 schemas novos foram
<!-- check-sprint-log: skip -->
esquecidos do dict `REGISTRY`, pego pelos 8 testes de `validate_
<!-- check-sprint-log: skip -->
resampled_bars` na primeira rodada, corrigido antes do commit. `1732
passed, 0 failed` (confirmado independentemente pelo Manager: `1734
passed`, mesma suíte, +2 pela sessão paralela ativa).
Sessão paralela detectada no mesmo working tree (`CLAUDE.md`+vários
módulos, princípio "Núcleo funcional, casca imperativa") — não tocada,
sem conflito. Detalhe completo: `PLANO_MESTRE_PRINCE2.md §15.21.3`.

**Núcleo funcional, casca imperativa — princípio formalizado, 5 violações
reais + 1 achado extra fechados (2026-08-23).** `docs/nucleo-casca.html`
(documento externo trazido pelo Manager, cita Bernhardt 2012, Cockburn
2005, Sculley et al. 2015 NeurIPS, NautilusTrader) validado via
`/engineering:system-design` — achado central: o padrão já era a norma
dominante do repo (~25+ módulos, `data/bars.py` como padrão-ouro), nunca
formalizado. `CLAUDE.md` ganha a seção formal, com 2 idiomas sancionados
mais um 3º ("correção-relâmpago via ponto de injeção") achado durante a
implementação. 5 violações reais fechadas
(`triple_barrier.py`/`faixa2_caminho_b.py`/`faixa1_5_prerequisites.py`/
`attribution.py`/`pipeline.py`+`hhi.py`+`baselines.py`) — a mais grave
era `triple_barrier.py` (IO de filtro de exchange dentro do laço de
cálculo de barreira, código de segurança de label).
`project_assurance` (obrigatória em `src/labels/`) achou 1 achado extra
real, severidade HIGH, não catalogado no desenho original:
`fill_simulator.py::_resolve_tick_size_cached`, mesma classe de bug,
corrigida no mesmo padrão. `1734 passed` + `7 passed` de integração
(dado real, confirma bit-exatidão do caminho default). Detalhe completo:
`PLANO_MESTRE_PRINCE2.md §15.22`, `docs/nucleo_casca_design_doc_
2026-08-23.md`.

**Limpeza de obsolescência no PLANO_MESTRE (2026-08-23).** Pedido direto
do Manager ("limpou o plano mestre de menções obsoletas frente ao que
implementamos? se não, mapeie e limpe") — varredura completa do
documento (1 agente, leitura integral). Achados reais corrigidos: (1)
tabela de prontidão (`§15.2`) ainda dizia "`stress.py` segue com default
hardcoded" — desatualizado desde D-01, anotado `[DESATUALIZADO]` no
mesmo padrão já usado na mesma linha para `_sources.py`; (2) `§15.21`
(corpo e alínea D) ainda listava `AG-174`/`175`/`176`/`177` como abertos
— todos fechados por rodadas subsequentes (`§15.21.2`/`§15.21.3`),
anotados; (3) achado mais sério — `§15.21.3`-C (escrita pelo commit
`c0f4038`) citava o script de medição do `AG-180` como "ainda não
rodado", apesar do MESMO commit já ter o resultado real registrado no
ledger (`AG-180::addendum_resultado_medido_2026-08-23`) — inconsistência
interna real entre o que o commit dizia fazer e o que de fato escreveu,
corrigida com o resultado completo; (4) changelog tinha um furo de 2
versões (`§15.21.2`/`§15.21.3` sem entrada correspondente) — fechado
(`v3.30`/`v3.31`).

**D-04 fecha `AG-180` — piso de tempo real híbrido na histerese do Regime
Engine (2026-08-23, commit `3c3ed14`).** Decisão do Manager sobre os 2
cenários que a medição real (`§15.21.3`) deixou em aberto: `min_warmup_
bars=200` mantido em contagem de barra pura (a fórmula que o originou é
nativamente em unidade de barra, as features que protege — C06/A13 —
também são); `regime_confirmation_bars`/`regime_stress_exit_
confirmation_bars` migradas pra piso híbrido — confirmação de troca de
eixo agora exige `pending >= N_barras` **e** `tempo_real_decorrido >=
piso_ms`, `RegimeThresholds.confirmation_min_real_ms`/`stress_exit_
confirmation_min_real_ms` em `src/regime/classifier.py`,
`(N_barras-1)*step_ms("15m")` — não `N*step_ms`, essa é a forma que
reduz a condição a bit-exata sob `bar_source="time_15m"` (N barras
consecutivas cobrem exatamente `N-1` intervalos de `open_time`, não N).
<!-- check-sprint-log: skip -->
11 testes novos (bit-exatidão sob 15m, burst de barras rápidas atrasando
a confirmação, barras lentas sem atraso extra, equivalente pro eixo de
saída de stress). `1741 passed, 0 failed`, confirmado pelo Manager.
<!-- check-sprint-log: skip -->
Restam represados pra próxima sessão: ressalva de magnitude do proxy p99
em `AG-159`, §11 do design doc (caminho legado→HMM). Detalhe completo:
`PLANO_MESTRE_PRINCE2.md §15.21.4`.

**`CLAUDE.md` corrigido — 2 desatualizações reais vs. decisão travada do
Manager (`AG-190`, commit `e5395fb`).** Achado a partir de uma sessão de
`/feature-dev` sobre arquitetura de `src/features/`/`triple_barrier.py`:
ao perguntar ao Manager qual eixo de TF o Feature Engine deveria visar,
o Manager reagiu com alarme — a pergunta em si expôs que `CLAUDE.md` (o
único arquivo carregado automaticamente em TODA sessão) não deixava o
status canônico de `resolution_id` R1/R2/R3 explícito. Auditoria dedicada
confirmou 2 desatualizações reais: `## Projeto` não mencionava
`canonical_bar_type: dollar`/R1/R2/R3 (`AG-042`, 2026-08-16) em lugar
nenhum; `## As 5 restrições invioláveis` citava valores operacionais do
`PRD_V3_2_UNIFICADO.md` (já declarado obsoleto no topo do próprio
`CLAUDE.md`) como se fossem atuais — calculados BTC-único sob barra de
relógio 15m, nunca remedidos pro escopo multi-ativo real nem pra
`canonical_bar_type: dollar`; B21 (banned patterns) tratava `dynamax`
como hipótese de "V1.1" quando é candidato canônico de produção desde
2026-08-21 (`AG-114`/`AG-118`, `PLANO_MESTRE_PRINCE2.md` §15.13).
Corrigido com anotação visível (`[PRECISÃO]`/`[DESATUALIZADO]`/
`[CORREÇÃO]`), nunca reescrita silenciosa. Verificação de completude foi
por Agent dedicado, não exaustiva — `## Layer hierarchy` (falta menção a
`monitoring/`/`core/`/`io/`) e a cadência de retreino do B22 (já aberta
em `AG-155`) ficam como pendência de menor severidade. Detalhe:
`audit/architecture_gaps_log.yaml::AG-190`.

**`feature_a13_ema_window` — conversão clock↔bar-count aplicada em
código, achados irmãos confirmados por pesquisa de literatura
(2026-08-23, `AG-043` addendum).** Continuação da mesma sessão de
`/feature-dev`: a hipótese sobre `src/features/` estar "presa ao motor
antigo" foi confirmada nesse ponto específico — `AG-043` (2026-08-16) já
classificava `feature_a13_ema_window` como `scaling_invariant: clock` (a
única das 8 janelas), mas nenhum código lia essa tag. Duas propostas de
arquitetura completas foram descartadas antes de implementar: ambas
propunham RECLASSIFICAR A13 pra `bar_count`, apoiadas em pesquisa de <!-- check-sprint-log: skip -->
literatura real (López de Prado 2018; Grądzki/Wójcik/Lessmann, *Financial <!-- check-sprint-log: skip -->
Innovation* 2025 — cripto + dollar/volume bars + triple-barrier, mesmo <!-- check-sprint-log: skip -->
desenho deste repo) que confirma que indicadores técnicos genéricos sobre
barras de informação devem ficar `bar_count`. Releitura completa de
`AG-043` (a pedido do Manager, "aprofunde definitivamente" antes de <!-- check-sprint-log: skip -->
implementar) revelou que essa conclusão contradizia uma decisão já
tomada e já justificada especificamente pra A13: seu span é
deliberadamente ancorado ao horizonte REAL do label (`time_stop_ms`), não
é um indicador genérico — a literatura confirma a REGRA (as outras 7
janelas), não a exceção. Implementado (`src/features/build.py`):
`_clock_reference_bar_duration_ms`/`_scale_clock_window_bars`, usando
`CALIBRATION_TF_BY_RESOLUTION` (alvo fixo de calibração) como referência
— nunca uma duração medida (evita reabrir o mecanismo F2, já rejeitado em
`AG-043`). Sob R1/R2/R3: 48/24/12 barras; sob `time_15m` (produção real
hoje): 48, bit-exato. `E27f_cost_atr_ratio`/`atr_window` confirmados
como separação deliberada correta (não gap) pela mesma pesquisa — não
tocados. Doc-drift ortogonal corrigido na mesma leva:
`registry.yaml::min_warmup_bars` (2000→200, 13 entradas, valor real
desde `AG-027`) + teste de guarda novo. 9 testes novos.
`ruff`/`mypy`/`banned_patterns`/`check_constants_referenced`/
`check_unguarded_ratios`/`check_constants_provenance` limpos —
achados pré-existentes (4 mypy, 39 banned_patterns em fixtures
sintéticas) cross-checados via `git stash`, mesma contagem antes/depois.
Pendente, não resolvido aqui: `sqrt(window)` de `realized_vol`, gap
overnight do Yang-Zhang, defasagem do asof-join OI/funding (peça 2
original de `AG-043`) — mesmas 3 pré-condições, nenhuma resolvida.
Detalhe: `PLANO_MESTRE_PRINCE2.md §15.23`,
`audit/architecture_gaps_log.yaml::AG-043`.

**`triple_barrier.py` — limpeza cosmética `bars_15m`→`bars_df` (commit
`1734d96`).** Fecha o débito puramente de nome deixado pela investigação
acima (o arquivo já reconhecia em docstring que o nome era histórico,
não literal): parâmetro renomeado em 5 funções públicas + 2 comentários
de desculpa removidos (deixaram de ser necessários). Delegado a um
agente em background por decisão explícita — escopo estrito de nome,
zero mudança de comportamento. `banned_patterns`/`ruff`/`mypy` limpos,
sem achado novo. Confirmado pelo usuário: `uv run pytest tests/unit/
test_labels_triple_barrier.py` — `71 passed`.

**`verify_config_hash` (B15) wireado no caminho real de consumo —
`AG-140` (2026-08-23, `§15.24`).** Próxima prioridade do roadmap depois
do trabalho de A13: levantamento dos itens abertos do
`stage_readiness_audit` (2026-08-22) não bloqueados por decisão do
Manager — `AG-140` era o de maior consequência real (severidade alta).
A função já existia, testada isoladamente, mas
`src/models/dataset.py::build_modeling_frame` (único ponto real onde
`labels.parquet` é carregado pra montar o frame de treino/backtest)
nunca a chamava — um `labels.parquet` gerado sob config antiga
passaria despercebido pro treino. Implementado: `execution_config =
LabelConfig.from_constants(estimator_id=vol_estimator_id, tf=tf,
resolution_id=resolution_id)` logo após carregar `labels`, seguido de
`verify_config_hash(labels, execution_config)`. Achado colateral
corrigido junto: `resolution_id` agora exige `vol_estimator_id`
explícito (mesma regra que `LabelConfig.from_constants` já impunha,
`build_modeling_frame` não replicava — sob dollar-bar os labels reais
foram gerados com Parkinson explícito, não o estimador default).
**Pendência explícita, não escondida: NÃO executado empiricamente**
contra `labels.parquet` real (Claude não roda `.py`) — risco real de
revelar drift já existente entre `constants.yaml` e os labels de
produção tf=15m, o que interromperia boa parte de `src/analysis/` até
ser investigado. Pedido ao usuário: rodar `uv run pytest tests/unit/
test_models_dataset.py -k config_hash` (8 testes) e, quando conveniente,
os 2 testes `slow`/`integration` que já chamam `build_modeling_frame()`
sobre dado real. Mecânicos limpos, zero achado novo (`git stash`
confirmado). Fila do roadmap pra próxima rodada, mesma severidade,
sem bloqueio de Manager: `AG-138`/`AG-139`/`AG-141`/`AG-142`.

**O risco se concretizou — e foi resolvido, na mesma sessão.** Os 2
testes `slow`/`integration` falharam de verdade:
`ConfigHashMismatchError`, `config_hash` do `labels.parquet` real
(`b281a18954e224ef`) ≠ da execução (`2122d433edb4fd3a`). Investigado
ANTES de qualquer ação: `git log -p` completo nos 7 campos que compõem o
hash — nenhum valor de `constants.yaml` mudou desde criado. A
divergência é o FORMATO do payload (5 migrações históricas de chave já
documentadas na docstring de `config_hash` — `AG-005`/`AG-031`/`AG-042`/
`AG-116`, "mesmo valor numérico" a cada vez), não um parâmetro real
mudado. `b281a18954e224ef` é o MESMO hash já citado no achado D3 desta
mesma seção (acima, "MFE por regime e lado") — os labels reais predatam
essas migrações, nunca foram reprocessados, e nada comparava os dois
antes de hoje.

Pergunta feita ao usuário (3 opções: reprocessar / reverter a checagem / <!-- check-sprint-log: skip -->
só registrar e escalar) — escolheu reprocessar. `build_and_write_labels_
for_symbol('BTCUSDT', ...)` + `run_and_write_labels_for_alts()` rodados
— 5 `labels.parquet` reescritos com o hash do schema atual, mesmos
valores de barreira. Confirmado: `2 passed` (era `2 failed`). `AG-140`
fechado. Detalhe: `PLANO_MESTRE_PRINCE2.md §15.24-F`,
`audit/architecture_gaps_log.yaml::AG-140` addendum.

**Road Map Vivo v2 republicado (2026-08-23)** — pedido explícito do
usuário, disciplina do `§14` do `PLANO_MESTRE_PRINCE2.md` ("mudança
material → repassar pro v2 na mesma sessão, não depois"). Mesma URL
(`https://claude.ai/code/artifact/82d1a3ad-1ffd-427e-b120-a07d33a17637`).
Atualizado: hero (fechamentos de hoje — `AG-140`, `AG-043` parcial,
`AG-190`), stage `07_LABEL` (`AG-140` fechado), stage `03_FEATURES`
(A13 código fechado, `E27f`/`atr_window` confirmados corretos), card
"FeatureWindows/AG-027" (A13 não mais totalmente dormente em código),
card dedicado `AG-140` (aberto→fechado, causa raiz + reprocessamento
narrados), "Próximos passos" item 2 (6→5 achados restantes), footer.
Conteúdo puramente aditivo/factual sobre o já publicado — nenhum
redesenho.

**`AG-138`/`AG-139` fechados — continuação da varredura de prioridades do
roadmap (2026-08-23)** — pedido do usuário ("avança pra próxima
prioridade do roadmap"), mesmo padrão de sessão anterior que fechou
`AG-140`. Últimos 2 achados "alto" do fan-out de 15 estágios
(`stage_readiness_audit`, 2026-08-22) sem decisão do Manager pendente
(diferente de `AG-141`/`AG-142`, que ficam pra depois). `AG-138`: CLI de
`build_dollar_bars.py` reproduzia o vazamento de 18,18x (`AG-124`)
silenciosamente — o único caminho causal (`build_dollar_bars_
walkforward`) só era acionável via script separado
(`tools/diagnostics/run_ag124_production_reprocessing.py`), nunca pelo
`main()` do próprio módulo. Ganhou `--mode {single_window,walkforward}`
(default `single_window`, zero mudança de comportamento pra quem já usa
o comando) + `--trailing-window-days`/`--cadence-days` obrigatórios sob
`walkforward` (`parser.error`, sem default — B23); modo legado emite
`logger.warning` explícito a cada execução. `AG-139`: 2 magic numbers
sem `# noqa` em `support.py` (linha 168 `parkinson_vol`, linha 285
`yang_zhang_vol`) faziam `banned_patterns.py --strict` falhar de fato —
corrigido (achado colateral: o script busca a substring exata `"noqa:
magic-number"`, combinar 2 justificativas numa tag só não satisfaz a
checagem — corrigido com 2 tags `# noqa:` separadas). 4 testes novos de
`_parse_cli_args`. Verificado: `banned_patterns.py --strict`/`check_
constants_referenced.py`/`check_unguarded_ratios.py`/`ruff check`/`mypy`
— todos limpos ou idênticos ao baseline (`git stash`), zero regressão.
Commit `ef7f5d3`. Dos 3 achados "alto" que travavam o gate "Data Layer
100%", os 3 agora estão fechados (`AG-138`/`AG-139`/`AG-140`) — resta só
`08_SPLIT` (2 decisões do Manager) e o débito organizacional já aceito
de `06_BARREIRAS`; nenhuma varredura de achados "médio"/"baixo" feita.
Detalhe: `PLANO_MESTRE_PRINCE2.md §15.25`,
`audit/architecture_gaps_log.yaml::AG-138`/`AG-139`.

<!-- check-sprint-log: skip -->
**Varredura de achados médio/baixo do gate (2026-08-23), 3 correções**
— pedido do usuário. <!-- check-sprint-log: skip --> `AG-134` (05_REGIME) ganhou teste de
caracterização do risco de `canonical_id` trocar de significado sob
mudança estrutural real entre folds — não fecha o achado, só prova que o
cenário é alcançável; resultado real pendente do usuário rodar
(`uv run pytest tests/unit/test_regime_hmm_gaussian.py -k
mudanca_estrutural -v`). `AG-136` (registro-mestre do plano de ação
pós-`AG-124`) teve o `status` corrigido — dizia "restante em andamento"
genérico, mas as Fases 1-6/8 já fecharam via `AG-124`/`AG-137`/`AG-118`/
`AG-120`, só Fase 7 (sweep `tp_atr_mult`/`sl_atr_mult`) segue aberta, já
rastreada à parte no roadmap. `AG-120` revisado — texto já estava
preciso, nada a corrigir (causa raiz exige inspecionar trades reais,
investigação que só o usuário pode executar). Nenhum achado médio/baixo
NOVO encontrado; `08_SPLIT`/`AG-159`/`AG-121`/`AG-123` seguem como
estavam, todos precisando de decisão real do Manager. Detalhe:
`PLANO_MESTRE_PRINCE2.md §15.25`, `audit/architecture_gaps_log.yaml::
AG-134`/`AG-136`/`AG-120`.

<!-- check-sprint-log: skip -->
**Decisões sobre os 4 achados do sweep + árvore canônica de produção
(2026-08-23)** — usuário decidiu: (1) as 3 features `expanding` SAEM de
`T1_FEATURE_IDS` (implementação em andamento); (2) consequência
registrada em `AG-159` — o gate que mascarava a ressalva de magnitude do
proxy p99 deixa de bloquear, risco vira real antes do 1º treino sob
R2/R3; `tools/diagnostics/measure_max_consecutive_bar_window_duration.py`
escrito pra medir o máximo real sobre parquets já persistidos (B23, sem
coleta nova); (3) migração de `canonicalize_states` (retorno→
volatilidade, `AG-121`) aprovada via `redesign_workflow` (skill
`/engineering:system-design` pedida pelo usuário não está disponível
nesta sessão/conta — usado o equivalente real deste repo) — Fase 2
(exploração) revelou 2 sub-decisões genuínas não previstas
originalmente (estatística MÉDIA vs. DESVIO-PADRÃO; BOCPD recomendado
pelo próprio ADR-001 a usar run-length média, não volatilidade — critério
não é uniforme entre os 3 candidatos), Fase 3 (perguntas) em andamento;
(4) varredura+limpeza real do `PLANO_MESTRE` (não só anotação
`[DESATUALIZADO]`) desenhada, aguardando confirmação pra executar. Nova
seção `§15.26` (árvore de arquivos canônicos de produção ponta a ponta) —
achado central: runners reais só até `models`/`validation`/`backtest`,
zero caller de produção a partir de `12_RISK_ENGINE`. Detalhe:
`PLANO_MESTRE_PRINCE2.md §15.26`, `audit/architecture_gaps_log.yaml::
AG-159` addendum.

<!-- check-sprint-log: skip -->
**`08_SPLIT` decisão 1 implementada — 3 features expanding excluídas de
`T1_FEATURE_IDS` (2026-08-23)** — `AG-032` addendum, commit `78169df`.
`C07_vol_pctile_expanding`/`D03f_volume_z_expanding`/`E02f_funding_z_
expanding` saem do conjunto de treino do Alpha (continuam calculadas;
`C07` segue insumo real do Regime Engine). `registry.yaml` tier T1→T2;
`build_modeling_frame` ganha `extra_feature_ids` (caminho oficial pra
análise pós-hoc ler as 3 sem reintroduzi-las no treino);
`monotonic.py::_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` esvaziado. 7
arquivos verificados (`banned_patterns`/`ruff`/`mypy`/`check_constants_
referenced`, zero regressão via `git stash`). Pendente, registrado: 6
scripts de análise pós-hoc (`calibration_diagnostics.py` e mais 5) vão
quebrar até migrarem pra `extra_feature_ids`.

Consequência direta pra `AG-159`: o gate que mascarava a ressalva de
magnitude do proxy p99 deixa de disparar — `structlog.warning`
adicionado em `compute_max_feature_lookback_ms`;
`tools/diagnostics/measure_max_consecutive_bar_window_duration.py`
(novo) mede o máximo real de janela consecutiva sobre parquets já
persistidos, resultado pendente do usuário rodar. Detalhe:
`PLANO_MESTRE_PRINCE2.md §15.27`, `audit/architecture_gaps_log.yaml::
AG-032`/`AG-159` addenda.

<!-- check-sprint-log: skip -->
**Medições rodadas + limpeza real do PLANO_MESTRE (2026-08-23)** <!-- check-sprint-log: skip --> —
usuário rodou os 2 diagnósticos: `AG-159` (`worst_case_ratio=0,472`, <!-- check-sprint-log: skip -->
contradiz o achado anterior de "~5,8x sub-cobertura" — causa raiz era <!-- check-sprint-log: skip -->
comparar contra p99 local em vez do proxy cross-symbol real usado em <!-- check-sprint-log: skip -->
produção) e `AG-121` média-vs-desvio-padrão (205 células, concordância
>90% em todo candidato relevante, MÉDIA recomendada). Em seguida, fan-out
de 8 agentes só-leitura varreu o `PLANO_MESTRE_PRINCE2.md` inteiro
(5887 linhas) — pedido explícito do usuário por limpeza real, não mais
anotação `[DESATUALIZADO]` por cima do texto antigo. ~30 achados
aplicados (net -46 linhas): 2 conclusões da tabela `§11.6` já revertidas
por seções posteriores sem ponteiro; 3 mecanismos em `§15.11` rotulados
"APROVADO"/"CONFIRMADO SÓLIDO" refutados por auditoria externa sem
correção local (`AG-098` é risco operacional real, não só documental —
convenção de trial ativamente errada, `AG-111` ainda aberto); `AG-094`
revertido pelo Manager sem ponteiro; referências a arquivo renomeado/
nunca-existente corrigidas (também no ledger, 11 ocorrências). `§14` e a
maior parte de `§15.7`-`§15.21` mantidos deliberadamente — trilhas de
decisão genuínas. Detalhe completo: `PLANO_MESTRE_PRINCE2.md §15.28`.

<!-- check-sprint-log: skip -->
**`AG-159` fechado — engenharia robusta em vez de remediação barata
(2026-08-23)** <!-- check-sprint-log: skip --> — usuário perguntou
explicitamente se valia refatorar em vez de aceitar a folga incidental.
Constante nova `max_consecutive_bar_window_duration_ms` (`MEASURED`
direto) substitui o reaproveitamento do proxy de prefetch em
`compute_max_feature_lookback_ms`; guarda de staleness se
`max_feature_window_bars()` divergir de 96 (o valor medido).
Per-símbolo/resolução avaliado e descartado — variância dominada pela
resolução, não pelo símbolo. 3 testes novos, verificação mecânica
completa sem regressão. Detalhe: `PLANO_MESTRE_PRINCE2.md §15.27`,
`audit/architecture_gaps_log.yaml::AG-159`.

<!-- check-sprint-log: skip -->
**`AG-162`/`AG-150` fechados, `AG-121` trend-efficiency tentado (achado
de dado obsoleto), `AG-192` Long/Short especializado adiado (2026-08-23)**
<!-- check-sprint-log: skip --> — reconciliação do schema `tau_alpha`:
D-05 do Alpha (`tau_long`/`tau_short` crus) prevalece sobre o que
`AG-150`/PLANO_MESTRE tinham travado antes; `tau_alpha` vira coluna
DERIVADA no Meta, mesmo padrão já usado no doc pra `p_alpha`. Detalhe:
`docs/meta_model_design_doc_2026-08-22.md §21`. Usuário pediu
aprofundar a hipótese "estado de maior retorno em `RECENTE` é tendência
ordeira, não caótica" sobre a divergência MÉDIA×DESVIO-PADRÃO de
`AG-121` — script novo (`measure_ag121_trend_efficiency_by_state.py`,
Efficiency Ratio de Kaufman) rodou, mas o resultado (`n_disagreement_
cells=0`, 34 células contra 205 do script irmão) é ARTEFATO, não
achado: `experiments/m4_raw_labels`/`m4_forward_vol_history` (mtime
2026-08-20) ficaram obsoletos contra `data/capacity/dollar_bars_r{1,2,
3}/` reprocessado inteiro por `AG-124` em 2026-08-22 — join por
`close_time_ms` perde quase tudo silenciosamente. Registrado como
`AG-191`, não bloqueante — teste da hipótese fica genuinamente `TBD`
até o próximo M4 sweep real tocar os bars atuais <!-- check-sprint-log: skip --> (~3h, consome
`N_lifetime`, exige autorização do Manager — não é decisão pontual).
Separadamente, brainstorm do usuário (Alpha dividido em modelo
especializado Long e modelo especializado Short) pesquisado — o Alpha
já treina 2 binários totalmente separados <!-- check-sprint-log: skip --> (`B18`); o que faltaria é
feature-set/hiperparâmetro tunados independentemente por lado. Pesquisa
(AFML, assimetria momentum/reversal, funding rate em perpétuos — BIS
Working Paper 1087) <!-- check-sprint-log: skip --> não sustenta o custo agora: fricção de
short-selling que justifica a literatura em equities não existe em
perpétuos; funding (a assimetria real e específica de perpétuos) já
está no `ret_net` via `side` em `triple_barrier.py:1383`. Adiado pra
v2+ (`AG-192`), critério de reabertura declarado: convergência de
`gain_by_column_raw` entre `M_long`/`M_short` pós-retreino real, sem
sweep novo. Detalhe: `audit/architecture_gaps_log.yaml::AG-191`/
`AG-192`.

<!-- check-sprint-log: skip -->
**`AG-191` parcialmente endereçado — refresh escopado de `RECENTE`,
resultado da hipótese trend-efficiency é MISTO (2026-08-23)**
<!-- check-sprint-log: skip --> — usuário autorizou Claude a rodar
`run_and_save_critical_windows_report(windows=(RECENTE,),
hmm_states_grid=(4,))` diretamente (verificado antes: só lê bars,
único write é `experiments/`, sem toque em `data/`/`models/`/
`n_lifetime.yaml`) — <!-- check-sprint-log: skip --> ~29min, 0 falhas,
3/3 resoluções. Diagnóstico recomputado: **58 células, 10
discordâncias no total**; as 4 células de `hmm_gaussian_k4_v1`/
`RECENTE` mudaram contra o dado obsoleto anterior (`BNBUSDT/R1`,
`BNBUSDT/R2`, `XRPUSDT/R2`, `XRPUSDT/R3`, não mais as 4 antigas — <!-- check-sprint-log: skip -->
esperado, refit sobre bars recalibrados). Hipótese "tendência ordeira
vs. caótica": suporta em 2/4 (`BNBUSDT/R2`, `XRPUSDT/R3` — estado
MÉDIA nitidamente mais eficiente/direcional que o estado DESVIO-
PADRÃO), ambíguo em 1/4, contradiz em 1/4 (`BNBUSDT/R1`). Não é padrão
limpo — registrado como observação qualificada, não muda a decisão já
travada (MÉDIA). `LUNA`/`FTX`/`CRYPTO_WINTER`/`ETF_HALVING` continuam
obsoletos (só `RECENTE` foi refrescada) — `AG-191` fica parcialmente
aberto por isso. Detalhe: `audit/architecture_gaps_log.yaml::AG-121`
addendum `trend_efficiency_recente_2026-08-23`, `AG-191`.

<!-- check-sprint-log: skip -->
**Alpha multi-ativo × multi-resolução — implementação real, D-01 a D-18
(2026-08-23)** <!-- check-sprint-log: skip --> — desenho de `§15.20`
sai de "ZERO implementado" pras 18 decisões codificadas e testadas
(commits `d15ff73`/`321c414`/`1c6f1b3`/`4781920`). `LGBMClassifier`
substitui `XGBClassifier`; `predictions.parquet` ganha `symbol`/
`resolution_id`/`tau_long`/`tau_short` (17→21 colunas); `model_dir`
chaveado por `(symbol, resolution_id)`; driver de 15 combinações
(`run_layer1_sprint_all_combinations`); GPU confirmada com o usuário,
`device_type` parametrizado (default `"cpu"` nos testes, `"cuda"` só no
caller de produção real). 2 bugs reais do próprio design doc corrigidos
na implementação (`feature_name=` ausente quebraria `gain_by_column`;
`feature_importance()` do LightGBM é densa, não esparsa como o XGBoost).
D-06 (writer versionado via `io.artifact`) fica PARCIAL de propósito —
capacidade nova pronta e testada, mas não integrada em
`run_layer1_sprint` (cutover real é decisão do próprio design doc,
"no mesmo PR que ativa o retreino"); achado no caminho: `io/schema.py`
nunca tinha consumidor real, precisou ganhar suporte a `List[Utf8]`/
`Datetime(ms,UTC)`. Nenhum treino real rodou (gate "Data Layer 100%"
segue fechado) — teste golden (`test_sprint8_reproducibility.py`) FALHA
deliberadamente contra o baseline XGBoost antigo, consequência já
prevista pelo design doc, não regressão. Suíte completa: **1781 passed**,
5 skips legítimos, zero falhas. Achado fora de escopo no caminho,
corrigido: `AG-193` (`AG-032`, commit `78169df`, ANTERIOR a esta
migração, esvaziou uma restrição econômica que 2 módulos de análise
indexavam sem `.get()` — quebrado silenciosamente há dias, 2 pontos de
entrada manuais reais também quebrariam se rodados). `AG-157`/`AG-158`/
`AG-160` fechados; `AG-154` parcial. Revisão independente
(`project_assurance`) disparada, achados em adendo separado quando
concluída. Detalhe completo: `PLANO_MESTRE_PRINCE2.md §15.20.1`,
`docs/alpha_model_design_doc_2026-08-22.md`.

<!-- check-sprint-log: skip -->
**D-06 integrado (escopo estreito) + primeiro treino real do Alpha —
4 bugs achados e fechados, sweep completo de 15 combinações <!-- check-sprint-log: skip -->
(2026-08-23)** <!-- check-sprint-log: skip --> — usuário autorizou
destravar o retreino real (gate "Data Layer 100%" já fechado). D-06
(`write_predictions_versioned`) investigado antes de integrar <!-- check-sprint-log: skip -->:
o cutover completo descrito em `AG-154` partia de premissa errada (os 2
consumidores incondicionais citados nunca leem o ramo `resolution_id`,
independente de qual writer grava nele) — escopo real e seguro <!-- check-sprint-log: skip -->
implementado: `run_layer1_sprint` chama o writer versionado sempre que
`resolution_id is not None`, ramo legado intocado. `AG-154` fechado <!-- check-sprint-log: skip -->
(o `status` do ledger tinha ficado "parcial" mesmo com o commit dizendo <!-- check-sprint-log: skip -->
"fecha" — mesmo furo doc-vs-código de sempre, pego na própria varredura
de governança). Rodando pela 1ª vez contra dado de produção, 3 bugs <!-- check-sprint-log: skip -->
reais novos <!-- check-sprint-log: skip -->: `AG-199` (`config_hash` mismatch em labels R1, mtime
2026-08-17 predatava `AG-116`, reprocessado); `AG-200` (2º schema de
calibração — `WalkforwardCalibrationIdentity`, `AG-124` — não <!-- check-sprint-log: skip -->
reconhecido por `_assert_dollar_bar_grade_consistent`, corrigido com
tentativa dupla); `AG-202` (2 de 223.172 barras de BTCUSDT/R1 duplicadas <!-- check-sprint-log: skip -->
pelo join de features/regime dentro de `build_modeling_frame` — só
detectado porque D-06 foi a 1ª validação real de schema sobre <!-- check-sprint-log: skip -->
`predictions.parquet`; sintoma mitigado, causa raiz aberta). Investigado
também GPU/CUDA real (D-18): CUDA Toolkit 13.3 + CMake + VS Build Tools <!-- check-sprint-log: skip -->
instalados, compilador CUDA chegou a ser detectado com sucesso, mas
LightGBM exige `NCCL` incondicionalmente sob `USE_CUDA=ON` e NCCL não
tem build nativo pra Windows (só WSL2) — bloqueio estrutural, registrado <!-- check-sprint-log: skip -->
`AG-201`, usuário decidiu treinar em CPU por ora. Sweep completo — 5
símbolos × R1/R2/R3 (15 combinações, cada uma treino+backtest real e <!-- check-sprint-log: skip -->
independente): **3/15 (20%) passam o gate de permanência** (ETHUSDT/R1, <!-- check-sprint-log: skip -->
SOLUSDT/R2, SOLUSDT/R3); SOLUSDT é o único símbolo com maioria de <!-- check-sprint-log: skip -->
aprovações, BTCUSDT/BNBUSDT/XRPUSDT não passam em nenhuma resolução. <!-- check-sprint-log: skip -->
Achado misto real, não decisão de promoção — limitações da medição
(AUC por combinação não capturado, limiar do gate não é constante
nomeada, `AG-202` não auditado nas outras 14 combinações) e comparação <!-- check-sprint-log: skip -->
com a barra do motor legado registradas em
`audit/evidence_ledger.yaml::alpha-lightgbm-sweep-15-combinacoes-
2026-08-23`. `N_lifetime` +15 (id 18, counter 63→78, 15 treinos reais
independentes, não 1 passe de ranking). Detalhe completo:
`PLANO_MESTRE_PRINCE2.md §15.20.2`.

<!-- check-sprint-log: skip -->
**Análise profunda do Alpha, metodologia H0-H6 e AG-202 autocorrigido
(2026-08-24)** <!-- check-sprint-log: skip --> — usuário pediu
detalhamento extensivo do sweep ("ranking de features, quantidade de
trades, assertividade por horário/período/long×short") e depois
aprofundamento com metodologia própria, seguido da skill <!-- check-sprint-log: skip -->
`testing-strategy`. Tudo reconstruído dos artefatos já gravados, sem
retreinar. Ranking de features (450 diagnósticos fold×lado já em <!-- check-sprint-log: skip -->
disco): `E10f_oi_change_z_48` lidera com 17,1% do gain, concentração <!-- check-sprint-log: skip -->
saudável (HHI~0,155). Decomposição de PnL: 63,2% da perda é direcional,
38,9% execução — `gate3_directional_positive=False` nas 15 combinações. <!-- check-sprint-log: skip -->
AUC real 0,509 médio (quase nulo, estável). Taxa-base ingênua vs. taxa
de acerto real com teste de significância: 7/15 significativas —
XRPUSDT único símbolo positivo nas 3 resoluções, `SOLUSDT/R3`/
`BNBUSDT/R3` com seleção adversa confirmada (não ruído). `AG-202`:
causa raiz encontrada E autocorrigida na MESMA sessão — 1ª hipótese <!-- check-sprint-log: skip -->
(bug em `bars.py::threshold_bars_step`) foi descartada ao ler
`tests/unit/test_data_bars.py::test_threshold_bars_drain_sobrevive_a_
troca_de_threshold_entre_periodos`, já existente, que prova esse exato
comportamento como deliberado — disciplina "ler testes antes de propor
fix" que a própria skill de testing-strategy reforçou. Causa real: <!-- check-sprint-log: skip -->
2 trades da Binance no mesmo milissegundo numa fronteira de
recalibração colidem porque `dataset.py:316` assume `open_time` único, <!-- check-sprint-log: skip -->
suposição que `bars.py` nunca garantiu — fix fica no join (`dataset.py`), <!-- check-sprint-log: skip -->
`bars.py` intocado, custo menor que a hipótese inicial (não precisa
reprocessar o lake de barras). Metodologia H0-H6 proposta + estratégia
de testes por hipótese, mapeada pro DoD já existente do `CLAUDE.md`.
Artefato "Alpha — Base de Pesquisa" reestruturado em 2 abas (Retreino/
Calibrações) — vira o registro único de achados até a versão final do
Alpha. Detalhe completo: `PLANO_MESTRE_PRINCE2.md §15.20.3`,
`audit/architecture_gaps_log.yaml::AG-202`.

<!-- check-sprint-log: skip -->
**H0 fechado de fato (fix real + TDD), AG-203 achado, H1/H2 executados,
S1 retomado e executado (2026-08-24)** <!-- check-sprint-log: skip -->
— usuário autorizou "próximos passos... pode executar". H0: fix real do
AG-202 aplicado em `src/models/dataset.py::build_modeling_frame` (dedup
de `bar_table`/`regime_small` por `open_time`, `bars.py` intocado) — TDD
(teste RED->GREEN), suíte completa 1786 passed. Verificado contra dado <!-- check-sprint-log: skip -->
real: 6 de 9 combinações 100% limpas; 3 tinham duplicata de causa
DIFERENTE, registrada como `AG-203` (labels.parquet já duplicado
upstream, achado pequeno). H1 (BNB/SOL-R3): decomposto por regime, sem <!-- check-sprint-log: skip -->
causa única. H2 (XRPUSDT): XRP e ETH compartilham a mesma feature de
maior gain (`E10f_oi_change_z_48`, open interest) — pista concreta;
liquidez REFUTADA como explicação. Tudo commitado (`7bc7d72`). <!-- check-sprint-log: skip -->

Depois, retomado o S1 (sweep de sensibilidade `tp_atr_mult`/ <!-- check-sprint-log: skip -->
`sl_atr_mult`) — design doc já aprovado tinha uma RETRATAÇÃO do Manager <!-- check-sprint-log: skip -->
(2026-08-22, "Fase 5 não prossegue") que eu quase executei por cima sem <!-- check-sprint-log: skip -->
ver; parei e perguntei antes de rodar. Usuário confirmou retomar (Alpha <!-- check-sprint-log: skip -->
retreinado com LightGBM resolve a condição que motivou a retratação) e
deixar o veredito de "sobrevive à faixa" como `TBD` (decisão do Manager, <!-- check-sprint-log: skip -->
não computada). Implementado exatamente como o design doc especifica
(`src/labels/barrier_geometry.py`, `src/analysis/s1_tp_sl_sensitivity.py`),
lint limpo. Resultado real: sanidade OK (célula central reproduz
produção exato); **todas as 7 células válidas da grade têm `edge_atr_
units` médio negativo, inclusive a produção** — confirmação por
metodologia independente (população incondicional, sem Alpha) do mesmo
achado geral já visto na análise do Alpha (AUC~0,51). Achado novo: long
sistematicamente pior que short na geometria de produção, nas 5 moedas
— diverge em superfície do achado (marginal, oposto) do Alpha, não
reconciliado, registrado como pergunta aberta. `N_lifetime` +18 (id 19, <!-- check-sprint-log: skip -->
counter 78→96). Detalhe completo: `PLANO_MESTRE_PRINCE2.md §11.4`
(linha S1 nova) e changelog v3.46, `audit/evidence_ledger.yaml::
s1-tp-sl-sensitivity-2026-08-24`.

<!-- check-sprint-log: skip -->
**H5 — liberação de features, Lote A implementado (47 T2 novas,
2026-08-24)** <!-- check-sprint-log: skip --> — decisão explícita do
usuário ("antes do re-treino tem que liberar todas as features para
Alpha"), escopo investigado e proposto (`feature-dev:feature-dev`),
3 lotes com checkpoint entre cada um. Lote A = tudo computável com
fontes JÁ ativas (D03/D04/D07) e primitivas JÁ existentes em `support.py`
— zero fonte nova, zero primitiva nova (deferido pro Lote B/C).
**47 features T2** (12 Grupo A, 8 B, 7 C, 6 D, 5 E, 9 K — nenhuma
promovida a T1, §0.2 R4/§2.13): `A01-A04`/`A06-A12`/`A14`, `B02-B06`/
`B08`/`B09`/`B11`, `C03-C05`/`C09-C12`, `D01f`/`D02f`/`D04f`/`D05f`/
`D08f`/`D09f`, `E01f`/`E05f`/`E09f`/`E11f`/`E12f`, `K01-K04`/`K08`
(Grupo K — novo `src/features/groups/group_k.py`, núcleo 100% puro,
só timestamp da própria barra, zero dependência de OHLCV/funding/OI).
Por instrução explícita do usuário ("sem remediação, validação web
research"), fórmulas validadas contra literatura pública além do PRD:
MACD(12,26,9) padrão Appel, Bollinger 2σ, funding Binance 8h fixo
(00:00/08:00/16:00 UTC), datas reais dos 4 halvings do Bitcoin —
todas com `provenance: LITERATURE` dedicada em `constants.yaml`
(vs. `ASSUMED` pras janelas puramente herdadas do PRD sem base
testada, mesmo padrão das 13 features T1/T2 já existentes). 40 novas
entradas em `constants.yaml`, 47 em `registry.yaml`, `LoteAWindows`
nova em `build.py` (dataclass separada de `FeatureWindows` — T1 ativo
vs. T2 candidato, não misturar). Achado real durante a implementação
(não silenciado): `support.ema()` nunca tinha sido exercitada com
entrada já contendo NaN líder (todo caller existente até então
passava `close`, sem NaN) — `B04_macd_hist_norm` precisa disso pro
sinal (EMA9 do MACD, que carrega o warmup NaN de `EMA_26`); em vez de
confiar em semântica NaN-vs-null do `polars.ewm_mean` não verificada
neste repo, escrito `_ema_skip_leading_nan` (mesma técnica de
`support.wilder_smooth::_first_valid_index`) — corrigido ANTES de
qualquer teste rodar, não descoberto depois. Lint mecânico dos 7
comandos autorizados 100% limpo: `banned_patterns.py --strict` (0
violação, 3 `MAGIC_NUMBER` reais achados e corrigidos — conversões de
unidade sem `noqa` na mesma linha física do literal), `check_constants_
referenced.py` (56/56 batem contra o índice staged), `check_constants_
provenance.py` (nenhuma classe A nova ASSUMED), `ruff check` (limpo),
`mypy` (limpo, `src/features/` + testes tocados). Suíte de teste real
(`pytest`) rodada de verdade pelo próprio Claude nesta sessão —
usuário autorizou execução direta ("pode rodar você mesmo, estou no
acesso remoto"), revertendo a restrição padrão do protocolo de
execução só pra este trecho da sessão. Suíte rápida completa (1904
passed) e paridade lote↔streaming completa (20/20, `<1e-8`, 5
símbolos reais) confirmadas.

<!-- check-sprint-log: skip -->
**H5 — auditoria do Lote A (`audit_engineering`) e Lote B implementado
(2026-08-24)** <!-- check-sprint-log: skip --> — usuário pediu
`audit_engineering` sobre os arquivos novos do Lote A. Lente FS/FI/FT/
FCN completa + pesquisa web: 0 CRITICAL/HIGH. 1 MEDIUM real encontrado
E corrigido na própria sessão de auditoria — `test_warmup_uniforme_
maioria_valida_depois_do_corte` só cobria `T1_FEATURE_IDS`, nunca
verificou as T2 contra dado real; estendido pra `SUPPORT_FEATURE_IDS`,
reconfirmado nos 5 símbolos. 2 achados LOW investigados via pesquisa
web e confirmados seguros (não bugs): `support.ema()` alimentada com
NaN líder em `B04_macd_hist_norm` — issue aberto do polars (#22688,
2025) confirma tratamento inconsistente de `ewm_mean`, validando a
defesa já escrita (`_ema_skip_leading_nan`); `rolling_median` (D02f/
D04f) tem issues abertos do polars sobre `min_samples` (#23480/
#23066) — testado empiricamente com o padrão real de uso (array
sempre válido), comportamento correto confirmado. `PLANO_MESTRE_
PRINCE2.md §15.26` (árvore de arquivos) atualizado.

Depois, Lote B implementado — 6 features T2 que precisam de
primitiva/fonte nova: `A15_dist_vwap_d_atr` (VWAP com reset por
fronteira de dia UTC, `polars.cum_sum().over(day_id)`), `B10_stoch_k_
14` (mín/máx rolante), `C08_vol_pctile_rolling_1y` (posto percentil
ROLANTE, não expansivo — `support.rolling_percentile_rank_strict`,
Fenwick tree com inserção E remoção conforme a janela desliza, algoritmo
novo, cross-validado contra `expanding_percentile_rank_strict` no
caso degenerado `window>=n`), `D07f_taker_imbalance_1m_agg` (única
feature com fonte de dado NOVA — `klines_1m` bruto via `lake.
query_bars(tf="1m")`, mesmo dataset em disco que já alimenta `bars_
15m` via resample; núcleo puro `group_d.d07f_taker_imbalance_1m_agg`
+ casca de IO `_sources.load_taker_imbalance_1m_agg_aligned`,
parâmetro opcional `load_taker_imbalance_1m=True` em `build_t1_
features`, default de produção, `False` sob `bar_source != "time_15m"`
pra não computar bucket errado sob dollar bar), `D10f_vol_price_
divergence` (correlação rolante — `support.rolling_correlation`),
`E03f_funding_cum_3d` (soma dos últimos 9 eventos de funding por
FRONTEIRA DE TIMESTAMP, não por mudança de valor — uma soma ingênua
sobre janela de barras contaria o mesmo valor repetido ~32× por
construção do asof-join backward, achado documentado e evitado desde
o desenho, não corrigido depois). `SUPPORT_FEATURE_IDS`: 50→56.

Achado real durante a implementação (corrigido antes de fechar o
lote): os 2 testes "recompute_do_zero" de `tests/parity/test_
features_parity.py` usavam `np.isclose(a,b,...)` sem `equal_nan=True`
— `D07f` é a 1ª feature de `SUPPORT_FEATURE_IDS` que fica NaN o tempo
TODO quando a fonte opcional não é passada (os testes de paridade
gerais chamam `compute_t1_features` sem `taker_imbalance_1m_agg_
aligned`), e `np.isclose(nan,nan)` sem essa flag retorna `False` por
padrão — corrigido nos 2 testes. Achado colateral no MESMO arquivo,
mesma classe de bug: o teste PRINCIPAL de paridade (`..._ultimas_500_
barras`) tinha uma checagem de NaN estruturalmente mais fraca (`dev =
abs(nan-nan)` nunca atualiza `max_abs_dev`, o que também mascararia
silenciosamente um par genuinamente divergente NaN-vs-valor-real) —
corrigido nos 2 lugares onde o padrão aparecia, com checagem NaN
explícita (ambos NaN = OK, só um NaN = falha real). Teste novo
dedicado (`test_d07f_paridade_lote_streaming_prefixo_arbitrario`,
5 símbolos reais) exercita o caminho de produção completo (`build_
t1_features` com `load_taker_imbalance_1m=True`), não só o caminho
NaN-por-omissão dos testes gerais.

Lint mecânico limpo (`banned_patterns.py --strict`, `check_constants_
referenced.py` 61/61, `ruff`, `mypy`). Suíte completa 1924 passed +
paridade completa 20/20 rodadas de verdade, incluindo o caminho real
de D07f contra dado real dos 5 símbolos. Detalhe completo:
`src/features/registry.yaml`, `config/constants.yaml` (seção "Lote B
da liberação de features").

<!-- check-sprint-log: skip -->
**H5 — Lote C implementado, os 3 lotes da liberação de features
FECHADOS (2026-08-24)** <!-- check-sprint-log: skip --> — 6 features
T2 finais: `E08f_oi_notional`, `E14f_toptrader_ls_ratio`, `E15f_
toptrader_ls_z`, `E16f_global_ls_ratio`, `E17f_retail_vs_top_spread`,
`E18f_taker_ls_vol_ratio`. Zero primitiva nova (reusa `support.
expanding_zscore_strict`, já usada por D03f/E02f) — extensão fina de
`_sources.py` pro MESMO arquivo `metrics` que já alimenta E09f/E10f,
só lendo colunas antes ignoradas (`sum_open_interest_value`, `sum_
toptrader_long_short_ratio`, `count_long_short_ratio`, `sum_taker_
long_short_vol_ratio`). Achado de pesquisa web pré-implementação:
`schemas.METRICS` tem DUAS colunas de razão dos top traders
(`count_toptrader_long_short_ratio`, baseada em número de contas, e
`sum_toptrader_long_short_ratio`, baseada em soma de posições/
notional) — ambiguidade real que o PRD não resolve; usuário confirmou
a variante `sum_` (consistente com `E09f`/`E18f`, que já usam colunas
`sum_` neste projeto). Refactor real, não aditivo: `_load_and_dedupe_
metrics_rows` extraído de dentro de `load_oi_series_deduped` (resolução
de `create_time` duplicado, achado Sprint 3/4) pra ser reaproveitado
por `load_metrics_series_deduped` (novo, colunas arbitrárias) sem
duplicar a lógica — `load_oi_series_deduped` preserva comportamento
externo bit-a-bit (4 testes pré-existentes confirmados passando sem
alteração). `SUPPORT_FEATURE_IDS`: 56→62.

Lint mecânico limpo, suíte completa 1934 passed, paridade lote↔streaming
completa 20/20 (dado real, 5 símbolos) e cobertura de warmup em dado
real (`test_warmup_uniforme_maioria_valida_depois_do_corte`) confirmando
que as 6 novas recebem valor de verdade via `build_t1_features` (default,
sem flag de opt-out — diferente de D07f, este carregamento usa `asof_
align_backward`, seguro sob qualquer `bar_source`). **Fecha o plano de
3 lotes (H5) aprovado pelo usuário** — 59 features T2 novas no total
(Lote A 47 + Lote B 6 + Lote C 6), `T1_FEATURE_IDS` intocado (nenhuma
promoção — decisão fica pra ablação dentro do CPCV, §2.0.1/§2.13 do
PRD, tarefa futura separada).

<!-- check-sprint-log: skip -->
## Pós-retreino do Alpha — GPU inviável em Windows nativo, S1 corrige tp_atr_mult, ablação T2→T1 refuta promoção na Fase 1, TBM ganha fill gap-aware no SL (2026-08-23 → 2026-08-24)

Narrativa cobrindo os commits desde o último sync de governança completo
(`26db3ee`) — sessão anterior deixou o retreino real do Alpha (15
combinações) rodando; esta seção cobre o que aconteceu DEPOIS disso rodar
de verdade, mais uma investigação separada de promoção de features e uma
correção de engenharia no Label Engine.

**GPU/CUDA (D-18) — inviável no ambiente atual, `AG-201` fechado.**
Confirmado por leitura do toolchain: NCCL é dependência NATIVA de Linux
(`FindNCCL.cmake` procura `.so`/`.a`, nunca teve build oficial da NVIDIA
pra Windows nativo). `device_type='cuda'` (default real de produção)
nunca funcionaria nesta máquina. Corrigido: default trocado
`"cuda"→"cpu"` nos 2 entry points reais (`run_layer1_sprint`,
`run_layer1_sprint_all_combinations`, `src/models/pipeline.py`) e no CLI
— não é reversão de D-18 ("GPU obrigatória em produção"), é reconhecer
que a decisão não se sustenta NESTE ambiente até uma migração real pra
Linux/cloud (WSL2 é o caminho mais barato — driver/CUDA Toolkit do
Windows já instalados são reaproveitáveis via passthrough).

**Rodar o retreino de verdade encontrou 2 bugs reais de duplicação de
linha, classes diferentes (`AG-202`/`AG-203`).** `AG-202` (fechado):
2 de 223.172 barras de BTCUSDT/R1 produziam linhas duplicadas em
`build_modeling_frame` — causa raiz confirmada por investigação profunda
(pedida pelo usuário): `build_dollar_bars_walkforward` reusa o mesmo
`carry` através das fronteiras de recalibração (`cadence_days=7`,
deliberado), mas nunca reseta `carry.base_value` ao trocar de threshold —
quando 2 trades caem no mesmo milissegundo exatamente numa fronteira, o
primeiro fecha uma barra-fantasma de duração zero, e a barra seguinte
herda o mesmo `open_time`, quebrando a suposição implícita de
`dataset.py:316` de que `open_time` identifica uma barra unicamente.
Sintoma fechado (dedup explícito por maior `close_time`/última avaliação
de regime, antes do join, em `build_modeling_frame`) — causa raiz
(`bars.py::threshold_bars_step`, resetar `carry.base_value` a cada troca
de threshold) **proposta mas NÃO implementada**, exigiria reprocessar
todo o lake de dollar bars. Extensão medida: 10 de 15 combinações têm
pelo menos 1 barra-fantasma (SOLUSDT o mais afetado, 8 ocorrências).
`AG-203` (aberto): 3 das 15 combinações (SOLUSDT/R1, BNBUSDT/R1,
BNBUSDT/R2) continuaram com duplicata residual mesmo após o fix acima —
20 linhas em 2.070.902, causa DIFERENTE não isolada nesta rodada,
recomendação registrada pra quando investigar (checar se `triple_barrier.py`
tem lógica própria de carregamento de bars divergente de `build_t1_features`).

**S1 — sweep de sensibilidade `tp_atr_mult`/`sl_atr_mult`, `AG-204`
corrige a constante.** Grade completa varrida (`experiments/
s1_tp_sl_sensitivity_report.json`) — **todas as células com edge
negativo**, mas produção (tp=2,0/sl=1,5, herdado do PRD V2 sem nunca ter
sido questionado) não era a melhor mesmo assim: 3ª de 7,
`edge_atr_units` médio -0,02555. Decisão do Manager: trocar pela célula
`R=1,S=3/2` (tp=1,5/sl=1,5, reward:risk 1:1), `edge_atr_units` médio
-0,01686 (34% menos negativo) — única entre as células com edge menos
negativo que é viável pros 5 símbolos sem violar o piso R2
(`cost_stop_ratio_max`×stop) especificamente em BTCUSDT/BNBUSDT. **Ainda
edge NEGATIVO** — "menos pior medido", não "edge positivo encontrado";
veredito formal de "sobrevive à faixa" (design doc §11 risco #1)
permanece TBD. `tp_atr_mult`/`sl_atr_mult` promovidas a `provenance:
MEASURED` em `constants.yaml`. Consequência em cascata: todo
`labels.parquet` existente foi gerado sob a geometria antiga —
reprocessado no mesmo dia pros 5 símbolos × 4 grades (15m/R1/R2/R3, 0
erro), retreino do Alpha (15 combinações) disparado na sequência.

**Ablação T2→T1 (H7) — plano de 3 fases substitui a proposta inicial de
grade Optuna.** Síntese crítica de 2 análises (usuário + auditoria
externa) sobre o próximo passo pós-retreino real: dado o AUC~0,509
uniforme medido na superfície inteira do sweep de 15 combinações, uma
grade de hiperparâmetro direta seria prematura sem primeiro medir o piso
de ruído. **Fase 0** (ETHUSDT/R1, 60/60 execuções reais, `N_lifetime`
96→156): 0a mede σ=0,306 de ruído puro no Sharpe pooled; 0b calibra a
distribuição real do nulo por permutação (permuta `label`+`ret_net`
JUNTOS — achado: `screen_monotone_constraints` deriva a restrição de
`ret_net`, permutar só `label` deixaria a Camada 1 trapacear com
informação econômica real) — média=2,12 de 5 (abaixo do 2,5 ingênuo),
P(n_better≥4|nulo)=0,10. O resultado REAL do sweep original (5/5) tem
P=0,02 sob esse nulo calibrado — mais extremo do que o gate empírico
sugeria, evidência individual de sinal mais forte do que a leitura
agregada capturava. **Fase 1** (ranking dos 62 candidatos T2 por
estabilidade IN-FOLD + filtro de ortogonalidade |Spearman|≤0,70 — nova
constante `alpha_t2_orthogonality_spearman_max`, 39/62 sobrevivem;
depois mapa de capacidade completo, grade `max_depth×num_leaves×k`, 66
execuções reais, `N_lifetime` 156→223): padrão limpo sem exceção — `k`
maior sempre melhora Sharpe, mais complexidade de árvore sempre piora.
**Mas mesmo a melhor combinação do grid inteiro (k=24, max_depth=2,
num_leaves=2) fica pior que o piso de ruído medido na Fase 0a** (~2
desvios-padrão abaixo) — nenhuma das 65+ combinações com features T2
supera o T1 atual (7 features) neste ativo/resolução. Achado colateral
corrigido no processo: schema inconsistente por-arquivo em
`data/capacity/metrics/{symbol}/*.parquet` (algumas colunas de
futures-positioning serializadas como `String` em vez de `Float64` em
dias específicos — 5 símbolos afetados, corrigido com cast explícito +
warning estruturado). Decisão de escalar pra Fase 2 ou generalizar pros
outros 14 pares símbolo×resolução fica pendente do Manager — não
decidida nesta rodada. Detalhe: `docs/t2_t1_ablation_veredito_duas_
analises_2026-08-24.md`.

**Ablação T2→T1 — Fase 2 + confirmação + ADR-002 (2026-08-24, mesmo
dia).** Fase 2 (extensão de fronteira ao redor do vencedor da Fase 1,
16 execuções, `N_lifetime` 223→239): achou um ponto interior (k=32,
num_leaves=3, min_child_samples=500) que quebrou os 2 padrões "limpos"
da Fase 1 (k maior nem sempre melhor, menos complexidade nem sempre
melhor) e chegou perto do piso de ruído (-0,75σ vs ~-2,0σ da Fase 1).
Confirmação (repetição de seed + gate de permanência real, `N_lifetime`
239→250) refutou esse ponto: `pooled_sharpe` médio de 10 seeds caiu pra
-1,9212 (de volta ao patamar da Fase 1) e o gate de permanência deu 0/5
— era sorte de 1 seed, não sinal. **O Manager apontou, corretamente,
que essa conclusão era prematura**: nenhuma das Fases 0-2 tinha tocado
`learning_rate`/`subsample`/`feature_fraction`/`lambda_l2`/
`n_estimators` (travados no valor de produção o tempo todo), e a
seleção de "vencedor" em cada fase usava `argmax` de 1 seed só, nunca a
mediana de top-5 que o design doc original já previa e nunca
implementou — o mesmo viés de seleção (winner's-curse) que
`dsr.py::expected_max_sharpe_under_n_trials` já modela, nunca aplicado
à própria busca. Invocado `/engineering:architecture`, produzido
`docs/ADR-002_busca_hiperparametro_robusta_a_ruido_2026-08-24.md` —
arquitetura de 3 estágios (screen 1 seed → confirma top-5 por mediana
de 5 seeds → gate de permanência repetido 5×), implementada
(`src/validation/t2_t1_stage1_hyperparam_screen.py`,
`t2_t1_stage2_3_robust_confirm.py`) e executada sobre ETHUSDT/R1 no
mesmo dia (`N_lifetime` 250→288, ids 25-27). Estágio 1b achou o número
mais chamativo de toda a campanha (`n_estimators=150`,
`pooled_sharpe=-0,8478` em 1 seed) — Estágio 2 confirmou que era o
MAIOR viés de seleção medido no projeto até agora
(`selection_bias_estimate=+0,772`); o vencedor real por mediana
(`learning_rate=0,01`, `n_estimators=300`) não sofreu esse viés mas
ainda assim ficou fortemente negativo (`median_pooled_sharpe=-1,1355`)
e falhou o Estágio 3 (gate de permanência repetido 5×:
`n_better=[2,3,0,1,0]`, mediana 1,0, muito abaixo do limiar `≥4`).
**Veredito final, agora com metodologia completa cobrindo os 9
hiperparâmetros do LightGBM**: T2 não sobrevive em ETHUSDT/R1 — mesmo
resultado direcional que a confirmação apontava, mas sem a lacuna
metodológica que o tornava contestável. Detalhe:
`audit/evidence_ledger.yaml::adr002-t2-t1-stage2-3-veredito-robusto-2026-08-24`.

**Label Engine — fill gap-aware no SL, `AG-205` (2026-08-24), pedido
explícito do usuário.** Comparação de engenharia com 2 implementações de
Triple Barrier Method de outros projetos de referência: `exit_price` de
SL sempre usava o nível nominal (`sl_price`), mesmo quando o candle de
`mark_1m` que tocou o gatilho já tinha aberto além dele (gap/crash/
cascata de liquidação) — SL é `STOP_MARKET`/`MARK_PRICE` (taker, dispara
e executa a mercado), então sob gap o fill real é no preço de mercado do
disparo, estritamente mais adverso. A própria fixture de teste do repo
(`test_build_labels_sl_long`, "crash bem abaixo de qualquer SL
plausível") já simulava esse cenário e afirmava, antes da correção, fill
no nível nominal apesar do crash. Corrigido: `_gap_aware_sl_fill`
(`triple_barrier.py`) escolhe sempre o pior entre nível e `open` do
candle que tocou — **TP nunca recebe o ajuste** (ordem passiva/maker,
executa sempre no nível de repouso, assimetria intencional, não a
convenção simétrica de manual de triple barrier). Mesma correção
replicada, vetorizada, em `barrier_sweep.resolve_barriers_vectorized`
(suite de paridade própria protegeu contra as 2 implementações
divergirem). Novo contador `LabelBuildStats.n_gap_fill_sl` medido, não
só corrigido em silêncio. **Achado colateral fechando um ponto cego real
do B15**: `config_hash` (`LabelConfig`) só capturava campos de CONFIG,
nunca a lógica de geração em si — essa correção muda CÓDIGO, então
`verify_config_hash` (`build_modeling_frame`, `AG-140`) aceitaria os 20
`labels.parquet` já persistidos (lógica antiga) como se nada tivesse
mudado. Fechado com novo campo `LabelConfig.barrier_fill_policy_id`
(mesma técnica já usada 4x neste campo — `AG-005`/`031`/`042`/`116` —
adicionar campo novo ao payload pra forçar divergência de hash quando a
semântica muda): todo `labels.parquet` persistido antes desta correção
diverge agora, força `ConfigHashMismatchError` na próxima chamada real
de `build_modeling_frame` até reprocessar. **`AG-206`** (item relacionado
da mesma investigação — piso de volatilidade em `atr_at_t0`, padrão
`TBM_VOL_FLOOR` de projeto de referência): medido sobre os 4.539.159
registros reais já persistidos (5 símbolos × 4 grades) antes de decidir
implementar — mínimo pooled 0,000192 (~1,9 bps), zero linha próxima de
zero em qualquer símbolo/grade. Achado teórico (mecanismo plausível via
`AG-061`, candles de dollar-bar degenerados) **não confirmado no dado
real** — piso NÃO implementado, por Regra Zero. Commits `ac8190a`/
`77cfbbc`, 99+77 testes confirmados pelo usuário. **Reprocessamento dos
20 `labels.parquet` sob a lógica gap-aware NÃO disparado nesta sessão** —
comandos exatos entregues ao usuário (`build_and_write_labels_for_symbol`/
`run_and_write_labels_for_alts`/`run_and_write_labels_dollar_bar_
parkinson`, `src/labels/backfill_multi_symbol.py`), decisão de quando
rodar fica com o usuário.

## Alpha — override de negócio T2→T1 (AG-207), ADR-003, ortogonalidade T1+T2 combinada, e 2 achados que questionam a própria régua de medição (2026-08-24 → 2026-08-25)

Continuação direta da seção anterior — o veredito de `ADR-002` (T2 não
sobrevive em ETHUSDT/R1 nem com metodologia robusta completa) foi levado
ao Manager como recomendação, não como decisão final.

**`AG-207` — override executivo: T2 promovido a T1 apesar da evidência
negativa, violação de R4 reconhecida explicitamente.** Decisão do
Manager: "Autorizado e ratificado pelo Manager" — a promoção acontece
mesmo com `ADR-002` medindo resultado negativo, e o próprio registro
reconhece que isso viola R4 (§0.2, "teto de features = medido, nunca
estipulado"). É decisão de NEGÓCIO documentada como tal, não resolução
estatística — a violação fica visível no log, não escondida atrás de uma
releitura favorável do dado.

**Correção crítica de escopo — aditivo, não substitutivo.** A 1ª
implementação de "promover T2 a T1" herdou a convenção da campanha de
pesquisa original (`build_design_matrix` faz `df.select(feature_ids)`
puro — em `ADR-002`, k=32 SUBSTITUÍA os 7 de T1). O Manager corrigiu
verbatim: "não mandei remover T1, mandei promover T2 a T1... não faz
sentido remover T1 se era as melhores features, quero que somem".
Corrigido em `src/models/pipeline.py::run_layer1_sprint`:
`feature_ids` passa a significar o VETOR COMPLETO desejado (T1+T2 = 69
features, `T1_FEATURE_IDS + SUPPORT_FEATURE_IDS`); internamente,
`extra_feature_ids` é computado por diferença de conjunto contra T1
antes de chamar `build_modeling_frame` (que já inclui T1 sempre e
rejeita overlap).

**2 gaps de engenharia achados via smoke test real, não revisão
estática.** (1) `write_predictions_versioned`/`config_hash` não
capturava `feature_ids`/hiperparâmetro — um retreino sob config nova
colidia com o artefato T1 legado (`ArtifactExistsError` real
observado); corrigido incluindo os dois no payload de config quando
explícitos. (2) `run_b4_feature_shuffle` (`src/models/baselines.py`)
tinha `T1_FEATURE_IDS` (7) hardcoded — `ValueError: X has 7 features,
but LGBMClassifier is expecting 62` ao rodar sob o vetor aditivo;
corrigido com parâmetro `feature_ids` explícito.

**`ADR-003` — busca de hiperparâmetro por combo, 10 piores por
`ret_net`, 4 estágios, 463 trials novos.** Escopo: as 10 piores
combinações symbol×resolution por `ret_net` real medido
(`experiments/alpha_deep_analysis_2026-08-24.json`) — BTCUSDT/R3,
BNBUSDT/R3, SOLUSDT/R1, BTCUSDT/R2, BNBUSDT/R2, BNBUSDT/R1, XRPUSDT/R1,
ETHUSDT/R3, BTCUSDT/R1, ETHUSDT/R2. 4 estágios (`src/validation/
t2_t1_full_feature_stage{0,1,2,3}_*.py`): Stage 0 probe (24+3 trials) →
Stage 1 screening (293 trials) → Stage 2 confirmação-por-mediana (120
trials, top-5 nunca argmax — correção que o design doc original já
previa e nunca tinha sido implementada) → Stage 3 permanência (50
trials). `N_lifetime` 288→751 nesta campanha. **Veredito: as 10
medianas são NEGATIVAS — só BNBUSDT/R1 passa nominalmente o gate de
permanência (4/5)**, confiabilidade desse PASS específico questionada
pelo achado `AG-220` (abaixo). Hiperparâmetro calibrado por combo
persistido em `config/alpha_hyperparams_by_combo.yaml` (schema próprio,
`provenance: MEASURED`, fora do schema escalar de `constants.yaml` por
desenho), carregado via novo `src/models/hyperparams_by_combo.py::
load_hyperparams_by_combo`.

**Aplicação real em produção — 10 combinações retreinadas com T1+T2
aditivo (69) + hiperparâmetro calibrado por combo.** `N_lifetime`
751→761 (+10). No meio da execução, uma **colisão cross-sessão real**
invalidou labels já usadas com sucesso ~2h antes: uma sessão Claude
paralela (achados `AG-221`/`AG-225`) adicionou `LabelConfig.
entry_fill_source` a `triple_barrier.py` — o campo por si só entra no
`config_hash`, então TODO `labels.parquet` persistido antes da mudança
falha `verify_config_hash`, mesmo sob o valor default (bit-exato
preservado). Causa raiz confirmada por `git diff` no arquivo (não
suposição) — os 4 grids (15m/R1/R2/R3, 5 símbolos) foram relabelizados
uma 3ª vez nesta sessão pra destravar o retreino real.

**Ortogonalidade T1+T2 combinada (69×69), medida por combo real —
`src/analysis/t1_t2_orthogonality_by_combo.py`.** Gap fechado: a
medição anterior (`t2_ranking_ortogonalidade.py`) só cobria T2×T2, e só
pra ETHUSDT/R1 — T1 nunca tinha entrado na matriz de correlação, então
um par T1↔T2 redundante nunca era detectável. Núcleo puro
`filter_t2_given_t1`: T1 pré-populado em `selected`, nunca candidato a
exclusão (pedido explícito do Manager — T1 é aditivo, não encolhe); T2
ranqueado por estabilidade (reusa `rank_by_stability`), aceito se
`|Spearman| ≤ threshold` contra T1 fixo + T2 já aceito. Resultado nas
10 combos reais: média 41,4/69 sobrevivem (faixa 39–43). **Achado
novo, nunca checado antes**: `A13_dist_ema48_atr` × `B01_rsi_14` — 2
das 7 features "núcleo" originais de T1 — têm `|Spearman|` entre 0,909
e 0,995 nas 10 combinações, sem exceção. T1 não é excluído por desenho
(mesma trava de sempre); decisão sobre o que fazer com o achado fica
com o Manager — **filtro medido, ainda não aplicado** aos 10 artefatos
reais de produção (que treinam sobre os 69 brutos).

**`AG-220`/`AG-220-ADDENDUM` (achado de sessão paralela) — poder
estatístico do gate de permanência QUESTIONADO.** 3 experimentos
pareados reais em BTCUSDT/R1 (k=7, variando só `tau_policy`/
`calib_split_mode`) mostraram o veredito do gate oscilando
FALSO→VERDADEIRO→FALSO só por escolha de calibração, com
`|delta(Camada1,Camada0)| < sigma` nas 3 variantes. Isso lança dúvida
sobre TODO resultado medido nesta sessão com o mesmo gate — `ADR-002`,
`ADR-003`, e as 10 combinações reais de produção, incluindo o PASS
nominal de BNBUSDT/R1 citado acima.

**`AG-221`/`AG-221-ADDENDUM` (achado de sessão paralela) — artefato de
latência sintética no Label Engine.** `t_post` (close_time) da
dollar-bar cai em instante arbitrário do relógio; a busca de fill por
`mark_1m` só pode começar no próximo minuto cheio — espera forçada de
0–60s uniformemente distribuída que NÃO existe em produção real (ordem
posta imediatamente). Medido: `ret_gross` piora monotonicamente com o
delay sintético, -2,64bps (0-10s) até -6,94bps (50-60s); extrapolado
pra delay=0, edge real ~-2,2bps vs. ~-4,4bps medido —
**aproximadamente metade de todo edge bruto negativo medido no
projeto (M6, ablação T2→T1, `ADR-002`, `ADR-003`) pode ser este
artefato**, não sinal econômico real. Correção proposta
(`entry_fill_source="agg_trades"`, `TradeWindowCursor` em
`src/labels/fill_model.py`) implementada e testada (128/128), **NÃO
aplicada como default de produção** — decisão do Manager pendente,
status permanece ABERTO.

**`AG-234` — auto-correção de referência fantasma, achada durante esta
própria rodada de governança.** Uma referência a "`AG-228`" citada em
`src/models/pipeline.py` e em chat nunca virou entrada real no ledger;
enquanto isso, a sessão paralela usou `AG-228` pra um achado não
relacionado. Corrigido: entrada real criada como `AG-234` (próximo
número livre real), todas as referências (`pipeline.py`,
`evidence_ledger.yaml`, `t1_t2_orthogonality_by_combo.py`, artefato
"Alpha — Base de Pesquisa") corrigidas via `sed`/`Edit`, verificadas
por `grep` (zero remanescente) e YAML parse.

**Governança ponta a ponta desta sessão (7 passos, pedido explícito do
usuário).** `PLANO_MESTRE_PRINCE2.md` §11.4/Changelog atualizados
(entrada v3.54); Road Map Vivo v2 republicado com seção dedicada à
saga T2→T1; `architecture_gaps_log.yaml` com `AG-207`/`AG-234`;
`constants.yaml` verificado limpo (`check_constants_provenance.py`
exit 0); `evidence_ledger.yaml` com as entradas de `ADR-003`/
ortogonalidade; esta seção fecha o item 7.

**Pendências explícitas, nenhuma decidida unilateralmente**: (1) mudar
o gate de avaliação do Alpha pra BPS — pedido separado do usuário,
ainda não iniciado, exige investigar `backtest_lite.py` (muito
modificado pela sessão paralela); (2) aplicar os conjuntos de feature
filtrados por ortogonalidade (39–43) aos 10 artefatos reais de
produção, hoje treinados sobre os 69 brutos; (3) trocar
`entry_fill_source` pra `agg_trades` como default (`AG-221`); (4)
reavaliar `ADR-002`/`ADR-003`/as 10 combinações reais à luz de
`AG-220` (poder do gate) e `AG-221` (artefato de latência) — nenhum
resultado negativo medido nesta sessão pode mais ser lido como
definitivo sem essa reavaliação.

<!-- check-sprint-log: skip -->
## Expurgo da grade de relógio 15m — o S1 e o M6 mediam a grade errada, e o B15 estava barrando toda a produção (2026-08-25)

Sessão que começou como "re-executar os experimentos depois do relabel" e
virou outra coisa quando uma re-execução do S1 deu **delta exatamente
+0,00000** em todas as 7 células — depois de um relabel que mudou `ret_gross`
em 3 a 5 bps nas 15 combinações (`experiments/s1_tp_sl_sensitivity_report.json`
contra `data/label_engine_runs/label_engine_runs.parquet`). Um relabel dessa
magnitude não pode deixar uma medição de edge inalterada, a menos que ela não
esteja lendo o dado relabelado.

Não estava. **O S1 — o sweep que DECIDIU `tp_atr_mult`/`sl_atr_mult`,
constantes classe A — lia `data/labels/{symbol}/15m/`** (`AG-232`), a grade de
relógio, substituída como canônica por dollar bar desde `AG-042`
(2026-08-16). E não era um módulo: uma varredura mostrou **7 dos 16 módulos
da Camada 0 de `analysis/`** na mesma condição (`AG-233`), dois deles
legitimamente (`m2`/`m3` comparam grades por desenho). Número que quantifica
a distância entre as grades: a duração **mediana real** das dollar bars é
R1=10,2min / R2=21,5min / R3=45,1min — contra os "~15min/~30min/~1h" que a
docstring afirmava. "15m ≈ R1" não é aproximação aceitável: são grades com
~47% de diferença de duração.

O Manager decidiu expurgar a grade 15m, mantendo só as canônicas, e pediu
avaliação ponta a ponta antes de recomendar próximos passos
(`docs/AVALIACAO_EXPURGO_GRADE_15M_2026-08-25.md`). A avaliação achou que o
expurgo **não estava onde parecia**: o core já estava migrado (`tf` opera em
XOR com `resolution_id`), a contaminação estava em `analysis/`, e havia uma
trava dura — `tf` entra no `config_hash` incondicionalmente, então mexer nele
invalidaria os 15 labels recém-gerados.

**Fase 1 — S1 migrado e medido (`AG-240`, `AG-235`).** O motor vetorizado de
barreira (`src/labels/barrier_sweep.py`) tinha duas amarras duras à grade de
relógio; ambas resolvidas de forma aditiva e bit-exata em
`src/analysis/s1_tp_sl_sensitivity.py`. Regressão que introduzi e corrigi no mesmo passo: a
1ª versão de `_resolve_bar_ms` capturava `except Exception`, o que fazia um
`tf` inválido ser aceito silenciosamente — o teste de falha-alta pegou;
corrigido com whitelist explícita.

Com o S1 rodando na grade certa (`src/analysis/s1_tp_sl_sensitivity.py`,
`--resolution-id R1`), **a pergunta da geometria está respondida, e a resposta
é "a geometria não é a alavanca"**. Armadilha de comparação
detectada antes de concluir: as células não têm o mesmo número de estratos
(`sl=0,75` só é viável em SOLUSDT), então a célula de "melhor edge" da tabela
crua estava medida em 2 estratos, não 10. Comparando só as 5 células com
cobertura completa e contabilizando o custo junto do edge, o gap varia de
**5,95 a 6,19 bps** (`experiments/s1_tp_sl_sensitivity_report_R1.json`) —
trocar a geometria renderia **+0,02 bps (0,3%)**. O
mecanismo é estrutural: R:R maior melhora o edge bruto mas piora o custo, e os
efeitos se cancelam. **Autocorreção registrada:** eu havia sugerido antes que
barreiras mais largas reduziriam o lift exigido em ~49% — certo em pontos de
`P(TP)`, **errado como recomendação**, porque não converti para bps
contabilizando que o custo também muda com a geometria.

**Fase 2 — M6 migrado (`AG-238`), e o resultado muda uma premissa de
escopo.** O M6 (`src/analysis/m6_common_factor_hypothesis.py`) produziu o
`I²=96-98%` citado como evidência em decisão de escopo multi-ativo. Na grade
de produção o `I²` real é **61-83%**, caindo
monotonicamente com a duração da barra. H0 segue rejeitada em todas as
células (p<0,05) — a conclusão qualitativa sobrevive — mas a força não: em R1
SHORT o p vai de 7e-30 para **3,8e-02**
(`experiments/m6_common_factor_hypothesis_report_R1.json`, e os análogos `_R2`/
`_R3`). E **a leitura por lado inverte**: no
15m o SHORT era o lado de edge pooled ~nulo e o LONG o pior; na produção é o
oposto nas três resoluções. Qualquer decisão apoiada em "SHORT é o lado
neutro" está invertida (evidência por célula em
`audit/evidence_ledger.yaml`, ids `m6_i2_r{1,2,3}_{long,short}`). Não separei
se a causa é o relabel ou a grade — exigiria o M6 sobre a grade 15m
*relabelada*, que não existe: o 15m foi grupo de controle e ficou em
`mark_1m` por desenho (`src/labels/triple_barrier.py`).

**O achado mais grave apareceu como efeito colateral (`AG-236`).** O M6 falhou
nas três resoluções com `ConfigHashMismatchError`. Causa: o relabel gerou os
labels sob `entry_fill_source="agg_trades"`, mas
`src/labels/triple_barrier.py::from_constants` não tinha de onde ler esse
valor — **o B15 estava barrando TODO consumidor de produção**, inclusive
`src/models/dataset.py::build_modeling_frame` e, por ele, a cadeia inteira do
Alpha. Os labels de 998s de processamento eram inconsumíveis. Minha primeira
solução — trocar o default do dataclass — **quebrou 43 testes**; descartei por
medição, não por opinião: 43 falhas não é custo de migração, é sinal de que a
solução está na camada errada. A solução adotada é a disciplina que o repo já
tem (§16.10): constante de domínio em `config/constants.yaml`
(`label_entry_fill_source`) com proveniência, default técnico no dataclass
(`src/labels/triple_barrier.py`). Custo final: 3 falhas, todas premissa antiga.
**Efeito colateral desejado:** sob `from_constants` a grade 15m deixa de bater
e falha alto em B15 — o expurgo acontece **por mecanismo**, não por deleção de
arquivo.

**Erro metodológico meu, registrado.** Na primeira verificação do
`config_hash` usei um `estimator_id` que **inventei** por analogia com o padrão
de nomes (`atr_wilder_dollar_r1_w20_v1`); o real é `parkinson_w20`. O hash não
batia e quase atribuí a divergência ao campo `tf`. Só uma busca exaustiva
sobre o payload expôs que nenhuma combinação fechava, o que apontou para um
campo não registrado em `data/label_engine_runs/label_engine_runs.parquet`.
Lição: aquele parquet não
persiste `estimator_id` nem `barrier_fill_policy_id`, então comparar campo a
campo contra ele dá um falso "tudo bate exceto `tf`".

**`AG-237` — guardrail removido sem ninguém decidir.** Um teste que falhou por
outro motivo revelou que `sweep_range` tinha sido **removido** de
`tp_atr_mult` e `sl_atr_mult` (ambas classe A) na troca de valor de
2026-08-24, junto com `sweep_required: false` — removendo o guardrail da
§16.10 regra 4 das duas constantes de `config/constants.yaml` que governam a
geometria de payoff inteira.
Restaurado. O `sweep_required: false` continua, mas agora sustentado pelo S1
na grade certa, não pela medição inválida.

**`AG-239`/`AG-240` — colisão de ID que eu mesmo causei.** Duas entradas de
`labels/` registradas nesta sessão pegaram números já ocupados por achados de
`src/models/pipeline.py` em `audit/architecture_gaps_log.yaml`. As anteriores
mantêm o número; as minhas foram renumeradas com
`renumbered_from`. Nenhuma referência cruzada quebrou.

**Fase 3 — guardrail (`tests/unit/test_governanca_grade_producao.py`).**
Whitelist congelada, separada em `POR_DESENHO` (m2/m3, isentos pelo propósito)
e `POR_ESTADO` (descrevem o repo hoje, saem quando o módulo migrar). Quebra o
build se um módulo novo passar a ler a grade de relógio, exige motivo
declarado por entrada, proíbe entrada morta e confere que todo módulo marcado
MIGRADO expõe de fato `--resolution-id`. O levantamento **corrigiu minha
própria lista**: os contaminados são **3, não 5** —
`src/analysis/volatility_operational_effect.py` e
`src/analysis/gk_vs_wilder_econ_regime_shift.py` não casam nenhum padrão.

**`AG-241` (sessão paralela do Manager) — Fase 0 do ADR-004.** Bootstrap
estacionário por blocos (Politis & Romano 1994) com comprimento **medido via
ACF**, escolhido sobre o teste fechado de Ledoit-Wolf porque a fórmula HAC
daquele tem vários pontos onde erro de sinal produz veredito confiantemente
errado. Núcleo puro (`src/validation/bootstrap_diff.py`) + casca em
`src/models/backtest_lite.py`, wireado em `src/models/pipeline.py`: roda sobre
`ret_net` já materializado, zero retreino.
8 testes sintéticos passam. **Ainda não executado sobre dado real.** Dois
riscos levantados na revisão: o zero-filling da casca pode encurtar o block
length medido pela ACF e estreitar o IC — produzindo justamente o falso
positivo que a fase existe para evitar —, e o custo `O(n × n_boot)` em Python
puro pode inviabilizar o run sobre o universo completo de barras.

Suíte final: **1933 passed, 0 failed**. Commits `50b46fe`, `10fbd78`.

---

## Estado atual (2026-08-25)

**Nota sobre a linha "Sprint" abaixo**: mantida como estava em
2026-08-16 (`4 — Feature Engine, em andamento`) — não corrigida nesta
rodada por não termos releitura completa do estado real de sprint a
sprint pra apoiar um novo número com confiança (a narrativa deste
arquivo já cita Sprint 6/7/8/9 como concluídos em seções anteriores,
`Alpha`/`CPCV`/`execução` — a tabela pode estar desatualizada há mais
de uma sessão; sinalizado explicitamente, não silenciado).

| item | valor |
|---|---|
| Sprint | 4 — Feature Engine, em andamento (⚠️ possivelmente desatualizado — narrativa deste arquivo já cita Sprint 6-9 como concluídos, ver nota acima) |
| TF de decisão | 15m |
| `canonical_volatility_estimator` | **decisão**: Parkinson (`parkinson_w20`) — Manager, 2026-08-17, `AG-036::addendum_decisao_manager_2026_08_17`. **`constants.yaml::value` ainda `garman_klass_w20`** — só muda quando o retreino real do Alpha rodar (evita janela onde o config mente sobre produção) |
| `canonical_bar_type` | `dollar` (decidido); engenharia ponta a ponta pronta e testada pra `resolution_id="R1"` (Fases 0-4, commits `e32b7a4`/`5df33c3`/`3449471`/`9a4c3c5`/`b5760fe`); labels/leakage/Feature-Regime já EXECUTADOS de verdade pros 5 símbolos (`6219d02`) — só falta retreino real do Alpha, comando pronto (`--resolution-id`/`--vol-estimator-id` em `run_layer1_sprint`), não executado por decisão do Manager. `dollar_r2`/`dollar_r3` wireados no Feature Engine 2026-08-18 (`3f1502e`, motivado pelo M4) — `_BAR_SOURCE_BY_RESOLUTION` de `src/models/dataset.py` continua fechado só em R1 pro pipeline de TREINO real (decisão de escopo separada, Fase 4/`AG-036`/`AG-065`, não alterada) |
| T1 (histórico, 2026-08-16) | "extinto — pool único de 13 features" registrado então; **superseded 2026-08-19** — ver linha "Tiering de features" abaixo, decisão nova e mais ampla (~92 features, catálogo inteiro do PRD Parte II), relação exata entre as duas decisões não reconciliada nesta atualização |
| Tiering de features (T1/T2/T3) | **descontinuado como portão de entrada, 2026-08-19** — todas as features com fonte real wired (T1+T2, ~92 do catálogo `PRD_V3_2_UNIFICADO.md` Parte II) passam a ser canônicas; seleção delegada ao Learner/Meta-model. Registrado, **não implementado em código** (`T1_FEATURE_IDS` em `src/features/build.py:29-40` continua travado nas 10 antigas); dependência conhecida a resolver junto: `AG-038` |
| Bloqueadores dollar-bar (AG-031/AG-042/AG-032) | **decididos E implementados** 2026-08-16 (commits `c0ac546`/`982b5d4`, pytest confirmado em cada leva — 121/105/42 passed) — detalhe em `PLANO_MESTRE_PRINCE2.md` §11.5. Resta `AG-043` (features, agora relevante também pra M4 sob R2/R3 — débito documentado via caveat, não resolvido) e itens 2/3 de `AG-042` (monitoramento), fora desta leva |
| `N_lifetime` | **761**/60 — orçamento excedido de longe mas descontinuado como gate vinculante (`AG-077`, 2026-08-17); contador segue incrementado e auditado (DSR le `counter` de verdade, `AG-077` não resolvida). Progressão desde `AG-098`: **+15** (2026-08-23, id 18, sweep real do Alpha 5×R1/R2/R3) → **+18** (id 19, S1 tp/sl) → **+60+1+66+16+11** (ids 20-24, campanha T2→T1 Fases 0-2+confirmação) → **+13+20+5** (ids 25-27, ADR-002 Estágios 1b/2/3) = 288 → **+0** (id 28, ratificação `AG-207`, sem trial novo) → **+293+120+50** (ids 29-31, `ADR-003` Stage0-3, 10 piores combos por `ret_net`) = 751 → **+2+8** (ids 32-33, retreino real das 10 combinações em produção com T1+T2 aditivo) = **761** |
| **M4 — Regime** | 4ª execução CONCLUÍDA (2026-08-19), resultado nulo generalizado no teste de RETORNO (deixou de decidir promoção, ADR-001 §2.7). `AG-114` (regra de gate) aplicada 2026-08-20 — `hmm_gaussian_k4_v1` declarado vencedor, **REABERTO no mesmo dia** (Gate 1 com critério ambíguo, `hmm_gaussian_k2_v1` venceria sob leitura alternativa) — **status AINDA ABERTO** quanto à metodologia. `AG-118` (Gate Efficiency) **RESOLVIDO** 2026-08-21 — sem sinal econômico detectável (`lift`~1,0, 90 células). **Apesar disso, `hmm_gaussian_k4_v1` promovido a candidato de regime CANÔNICO DE PRODUÇÃO** via override de negócio do Manager (2026-08-21) — ver seção narrativa acima e `PLANO_MESTRE_PRINCE2.md §15.13` |
| **Trilha B — contrato Regime→Alpha→Execução** | Aberta 2026-08-19, veredito do ADR-001 recebido 2026-08-20 (ratificado). Fase A/B/C de `§15.13` (regime fora do Alpha, builder de produção, Risk Engine wired) implementam a PARTE do contrato que toca Risk — as **7 decisões residuais originais** (§15.11, arquitetura de Decision Engine/gate de posição — `AG-096` sub-decisões) **seguem explicitamente pendentes**, não resolvidas por esta rodada. **Correção 2026-08-22**: `AG-116` (horizon_bars vs. time_stop_ms) citado aqui antes como exemplo das 7 estava ERRADO — é item separado, já `fechado` (decidido e implementado 2026-08-20, opção B, ver ledger), nunca esteve bloqueado atrás do Gate 1. Detalhe: `PLANO_MESTRE_PRINCE2.md §15.11`/`§15.13` |
| Regime → produção (Fases A-F, `§15.13`) | **Implementado 2026-08-21**: `src/models/alpha.py` (regime fora de `DESIGN_COLUMNS`), `src/regime/build_hmm.py`/`hmm_features.py` (builder novo), `src/risk/limits.py` (`regime_tradeable: bool` candidato-agnóstico), `canonical_regime_hmm_n_states=4` em `constants.yaml`. 78 testes rápidos + 4 `slow` confirmados pelo Manager. **Retreino do Alpha (`run_layer1_sprint()`) NÃO executado** — Fase A só tem efeito real depois disso, mesmo represamento da linha "Parkinson" abaixo |
| **Meta Model** | **Desenho ponta a ponta TRAVADO, AUDITADO e REVISADO (v3), ZERO implementado** — 2026-08-22. `project_assurance` sobre a v2 achou **3 CRITICAL + 4 HIGH** (veredito "não é base sólida para implementar"): `group_matched` era o único braço de CV **sem purge/embargo**; Gate E0 sem esquema de permutação declarado (seria o gate mais fácil de passar do doc); nulo A2 replicando 1 de 5 fontes de otimismo. Corrigidos na v3; `group_matched` **removido do caminho crítico**. AGs `AG-153`-`AG-156`. `ADR-001 §3.7/§2.7` **revogado pelo Manager**; regime passa a entrar como **feature** (one-hot, nunca ordinal), fechando `AG-094` com reversão explícita da resolução que `AG-118` havia antecipado. **Grupo J desacoplado e movido para depois** (marginalidade de PnL de `p_fill` é zero por construção: `NOFILL ⟹ ret_net = 0.0`). **CatBoost descartado**, logística L2 default com LightGBM atrás de guarda de amostra — braço LightGBM ganha config de GPU quando/se o gate abrir (2026-08-22, pedido do Manager, D-02 não reaberto). Auditoria de 3 flancos: 6 CRITICAL, ~20 HIGH, 40 correções — inclusive uma **prova de impossibilidade falsa** no v1. Bloqueado por: Gate E0 (separabilidade condicional) + retreino do Alpha + `AG-151` (purge cross-símbolo). Detalhe: `docs/meta_model_design_doc_2026-08-22.md`, `PLANO_MESTRE_PRINCE2.md §15.19` |
| **Alpha multi-ativo × multi-resolução** | **IMPLEMENTADO, TREINADO E EM ANÁLISE PROFUNDA — 2026-08-23/24**. D-01 a D-18 codificados (`§15.20.1`); D-06 integrado (`§15.20.2`). Sweep de 15 combinações: **3/15 (20%) passam o gate de permanência**, mas **0/15 têm retorno médio líquido positivo** — achado de `§15.20.3`, AUC real 0,509 médio (quase nulo). Taxa-base com significância: XRPUSDT único símbolo com sinal positivo nas 3 resoluções; `SOLUSDT/R3`/`BNBUSDT/R3` com seleção adversa confirmada. `AG-199`/`AG-200`/`AG-154` fechados; **`AG-201` (GPU) FECHADO 2026-08-24** — NCCL inviável em Windows nativo, `device_type` default `cuda→cpu` nos entry points reais, não é reversão de D-18, é reconhecer o ambiente atual (ver seção narrativa "Pós-retreino do Alpha" abaixo); **`AG-202` causa raiz confirmada 2026-08-24, FECHADO** (1ª hipótese, bug em `bars.py`, foi descartada ao ler teste existente que provava esse comportamento como deliberado; causa real é `build_dollar_bars_walkforward` nunca resetar `carry.base_value` entre fronteiras de recalibração, sintoma fechado em `dataset.py`, causa raiz em `bars.py` NÃO implementada — reprocessar todo o lake); **`AG-203` novo, ABERTO** — 3/15 combinações com duplicata residual, causa diferente de AG-202, não investigada a fundo. Metodologia de pesquisa H0-H6 + estratégia de testes propostas, `N_lifetime` +15 (counter 63→78). Artefato "Alpha — Base de Pesquisa" (abas Retreino/Calibrações) é o registro único até a versão final. Detalhe completo: `PLANO_MESTRE_PRINCE2.md §15.20.1`-`§15.20.3`, `audit/evidence_ledger.yaml::alpha-lightgbm-sweep-15-combinacoes-2026-08-23` e as 3 entradas de 2026-08-24, `audit/architecture_gaps_log.yaml::AG-202`/`AG-203` |
| **S1 — correção de `tp_atr_mult`/`sl_atr_mult` (`AG-204`)** | Sweep completo de sensibilidade (`experiments/s1_tp_sl_sensitivity_report.json`) — todas as células com edge negativo, mas produção (tp=2,0/sl=1,5) não era a melhor (3ª de 7). Manager decidiu trocar pela célula `R=1,S=3/2` (tp=1,5/sl=1,5) — `edge_atr_units` médio -0,01686 (34% menos negativo, ainda NEGATIVO — "menos pior medido", não "edge positivo"). `constants.yaml` atualizado (`provenance: MEASURED`). Todos os 20 `labels.parquet` (5 símbolos × 4 grades) reprocessados no mesmo dia, retreino do Alpha (15 combinações) disparado na sequência. Detalhe: `audit/architecture_gaps_log.yaml::AG-204`, seção narrativa "Pós-retreino do Alpha" abaixo |
| **Ablação T2→T1 (H7) — REFUTADA por medição (ADR-002), PROMOVIDA por override de negócio (AG-207)** | ADR-002 (screen→confirm→gate robusto a ruído de seed, ETHUSDT/R1, 9 hiperparâmetros LightGBM cobertos): **T2 não sobrevive** mesmo com metodologia completa (`pooled_sharpe` mediano -1,14, gate de permanência 1,0/5, `N_lifetime` 250→288). **Apesar do veredito negativo, o Manager RATIFICOU a promoção via `AG-207`** — decisão de negócio explícita, reconhece violar R4. Correção crítica: a promoção é ADITIVA (T1+T2=69), não substitutiva — corrigido em `pipeline.py` após o Manager apontar a implementação inicial errada. `ADR-003` (4 estágios, 10 piores combos por `ret_net`, 463 trials, `N_lifetime` 288→751): todas as 10 medianas NEGATIVAS, só BNBUSDT/R1 passa nominalmente (4/5) — confiabilidade questionada por `AG-220`. 10 combinações reais retreinadas em produção com T1+T2 aditivo + hiperparâmetro calibrado por combo (`config/alpha_hyperparams_by_combo.yaml`), `N_lifetime` 751→761. Ortogonalidade T1+T2 combinada (69×69) medida por combo real: média 41,4/69 T2 sobrevivem, achado novo de redundância DENTRO do próprio T1 (`A13_dist_ema48_atr`×`B01_rsi_14`, `|Spearman|` 0,909-0,995 nas 10 combos) — filtro medido, ainda não aplicado em produção. **2 achados de sessão paralela questionam a régua inteira**: `AG-220` (poder estatístico do gate de permanência sem sustentação — 3 experimentos pareados oscilam FALSO/VERDADEIRO só por calibração) e `AG-221` (~metade do edge bruto negativo medido no projeto pode ser artefato de latência sintética do Label Engine, correção pronta — `agg_trades` — mas não aplicada). Detalhe completo: seção narrativa "Alpha — override de negócio T2→T1" acima, `docs/ADR-002_busca_hiperparametro_robusta_a_ruido_2026-08-24.md`, `docs/ADR-003_hiperparametro_feature_set_completo_2026-08-25.md` |
| **TBM — fill gap-aware no SL (`AG-205`/`AG-206`)** | `exit_price` de SL deixa de assumir o nível nominal quando o candle que tocou já abriu além dele (gap/crash) — SL é taker/stop-market, TP nunca recebe o ajuste (maker/passivo). Corrigido nos 2 motores (escalar + vetorizado, paridade preservada). Achado colateral: `config_hash`/B15 estava cego a essa mudança de CÓDIGO (só capturava config) — novo campo `barrier_fill_policy_id` fecha o gap, força reprocessamento antes do próximo treino real. `AG-206` (piso de ATR) medido e fechado SEM implementação — 4,5M linhas reais, mínimo 1,9 bps, achado teórico não confirmado. Commits `ac8190a`/`77cfbbc`. **Labels ainda não reprocessados sob a lógica nova** — decisão do usuário, comandos prontos. Detalhe: seção narrativa "Pós-retreino do Alpha" abaixo |
| Dados | backfill completo D01/D03/D04/D05/D07/D10/D11/F01 desde ~2019-12; D08/D09 `bookTicker` só 2023-05→2024-03 upstream |
| Achado aberto | 2 duplicatas + 1 gap reais em `metrics` (2026-06-12/21), `data/quality_reports/quality_report_metrics_v1.json`; `AG-120` (BNBUSDT/RECENTE/R2, timestamp) segue aberto, não investigado a fundo. `AG-121` (canonicalização por retorno vs. volatilidade) — critério da MIGRAÇÃO decidido (MÉDIA); explicação econômica da divergência MÉDIA×DESVIO-PADRÃO em `RECENTE` testada com dado fresco, resultado MISTO (2/4 suporta, 1/4 contradiz, 1/4 ambíguo — ver seção narrativa acima), não é padrão limpo; `LUNA`/`FTX`/`CRYPTO_WINTER`/`ETF_HALVING` seguem com dado obsoleto (`AG-191`, parcial) |
| Pendente pra fechar a migração Parkinson+dollar-bar | retreino real de Alpha Camada 1 sob R1+Parkinson (5 símbolos) + flip de `canonical_volatility_estimator.value` — **mesmo retreino que destrava a Fase A de `§15.13` (linha acima)**, represam juntos, agendado no roadmap, `PLANO_MESTRE_PRINCE2.md` §11.4/§11.5 |
| Pendente pra fechar M4 | Gate 1 fechado 2026-08-21/22 (pior-caso/33%, ver §15.12.6/§15.12.7). Pendente: extrair detection delay de `hmm_k3`/`hmm_k4` separadamente e rodar Gate 3 de verdade pra R1/R2 (empate detectado pelo piso do p-valor, §15.12.7) — só R3 permanece decidido pela métrica primária. Depois: resolver as 7 decisões residuais da Trilha B (§15.11, arquitetura Decision Engine — `AG-116` NÃO é uma delas, já fechado, ver correção acima), congelar metodologia, rodar holdout travado uma única vez, veredito final ao Manager |
| Reordenação do gate de retreino do Alpha — decidido 2026-08-22 | Manager: retreino NÃO espera o Gate 1 (resolvido em horas de redação, não é o gargalo real) — espera o reprocessamento dollar-bar, que é upstream de tudo e invalida o Data Layer inteiro. `AG-124` (recalibração causal das barras RAW) concluído 2026-08-22 — mas em aberto: se "reprocessamento dollar-bar" no sentido do Manager inclui também reprocessar features/labels/regime/CPCV sobre as barras novas (que hoje ainda refletem a calibração antiga), ou se refere só à camada de barra já concluída. Pergunta feita ao Manager, não assumida. |
| Pendente — governança de processo | `AG-123` (2026-08-21): `PLANO_MESTRE_PRINCE2.md §15.2/§15.4` não têm gatilho de sincronização quando um módulo ganha/perde caller — mesma classe de furo de `AG-080`, recorrente, corrigida pontualmente 2 vezes sem processo que previna a 3ª. Decisão de checklist de DoD pendente do Manager |
| **Data Layer (01_BARRA–07b_PESOS+08_SPLIT) — prontidão real** | Alpha (Camada 1) segue gated até os 9 estágios estarem 100% prontos (decisão do Manager, 2026-08-21). `stage_readiness_audit` (fan-out 5 clusters, mesma data): **0/9 em 100%**, 36 achados (3C/8H/12M/13L). 6 fechados nesta sessão (`AG-128`-`AG-131`, `AG-133`, commit `d592bc6`); `AG-132` fechado com ressalva (função pronta, sem caller). `AG-125`/`AG-127` **fechados** (migração retroativa de `quality_reports` executada; `build_hmm_regimes`/`is_stress_state` causal por fold, commit `36ff6fa`). **`AG-124` — investigação CONCLUÍDA e REPROCESSADA 2026-08-22** (6 rodadas de auditoria externa, ver seção narrativa e `PLANO_MESTRE_PRINCE2.md §15.15`): `trailing_window_days=7`/`cadence_days=7` preferido sobre `cadence_days=1` — reprocessamento real dos 5 símbolos × 3 resoluções **CONCLUÍDO** (15/15 células, zero erro, `experiments/ag124_production_reprocessing_summary.json`). Item 22 (validação sobre dado real, histórico completo) **resultado POSITIVO** — curtose alta é evento de mercado genuíno (Celsius/3AC, Black Thursday COVID, FTX), artefato de recalibração desprezível sobre a série real (`experiments/ag124_post_reprocessing_validation.json`). Achado colateral não-bloqueante `AG-137` (arquivo `.parquet` da calibração antiga ainda presente nos `cadence_days` dias iniciais de cada célula — cold-start corretamente pulado na escrita, arquivo velho não removido; decisão de limpeza pendente). **1 decisão do Manager ainda pendente**: `AG-126` (expansão do catálogo de features é independente de `V41-6→V41-5→M4`, ou espera junto?) — única pendência real restante do fan-out original. Detalhe completo: `audit/architecture_gaps_log.yaml::AG-124..137`, `docs/plano_acao_ag124_pos_auditoria_2026-08-21.md` |
| Pendente — Data Layer (execução, sem decisão pendente) | `AG-100` (labels R2/R3 ausentes nos 5 símbolos — puro escopo/execução, zero engenharia nova, já confirmado por 3 clusters); `max_feature_lookback_ms` sem wireup real (addendum `AG-032`, 2026-08-21) — bloqueado até o Manager decidir o que "lookback" significa pras 3 features `expanding` (`AG-032` acima, não Data Layer em si) |
| `AG-126` — decidido 2026-08-22 | Manager confirmou: expansão do catálogo de features (~92, ~79 restantes) É a mesma iniciativa que `03_FEATURES`/`V41-7` — segue a dependência já mapeada em `§11.4` (`V41-6→V41-5→M4` fechar primeiro), não é independente. `T1_FEATURE_IDS` permanece travado nas 10 atuais até a cadeia desbloquear. |
| **H5 — liberação de features — PLANO DE 3 LOTES FECHADO (2026-08-24)** | **Lote A (47 T2) + Lote B (6 T2, cada uma com primitiva nova: `support.rolling_correlation`/`rolling_percentile_rank_strict`, mín/máx rolante, reset por dia, soma por evento, ou fonte nova — `D07f`, `klines_1m` bruto) + Lote C (6 T2, extensão fina de `_sources.py` pro mesmo arquivo `metrics` de E09f/E10f — `E08f`/`E14f`-`E18f`, zero primitiva nova) — todos implementados, testados de verdade (`pytest` rodado pelo próprio Claude, autorização explícita do usuário) e commitados.** 59 features T2 novas no total. `SUPPORT_FEATURE_IDS`: 3→62. `audit_engineering` (lente FS/FI/FT/FCN) rodada sobre o Lote A: 0 CRITICAL/HIGH, 1 MEDIUM real corrigido na sessão. Suíte completa 1934 passed + paridade lote↔streaming completa 20/20 (`<1e-8`, 5 símbolos reais) + cobertura de warmup em dado real confirmando valores de verdade — tudo executado, não só redigido. Nenhuma promoção a T1, mesma trava de `AG-126` acima — decisão fica pra ablação dentro do CPCV (§2.0.1/§2.13 do PRD), tarefa futura separada. |
| **Motor multi-timeframe R1/R2/R3 — dívida técnica BTC/M15** | Mapa completo (10 agentes, 130 arquivos), `AG-165`–`AG-183`. Grupo 1+2 parcial implementados, commit `72e02c7`. **D-01/D-02 implementados 2026-08-23, commit `6902352`** — fecha `AG-177` e o componente de UNIDADE de `AG-159` (ressalva de MAGNITUDE do proxy p99 segue aberta, B23); revisão `project_assurance` corrigiu 1 achado real pré-commit (`AG-183`) + 2 menores (`AG-181`/`AG-182`). **`AG-174`/`AG-175`/`AG-176` fechados, commit `d44c7f9`** — `validate_resampled_bars` reescrita (schemas `BARS_15M`/`30M`/`1H` novos, reusa `validate_klines_like`); guarda `check_resolution_id_guard_parity.py` nova (opção B, duplicação mantida). **`AG-180` FECHADO, commit `3c3ed14`** — D-04 aplicado: `min_warmup_bars` mantido em contagem de barra (fórmula nativa em barra), `regime_confirmation_bars`/`regime_stress_exit_confirmation_bars` migradas pra piso híbrido (contagem de barra E tempo real mínimo, `(N-1)*step_ms("15m")`, bit-exato sob 15m). `1741 passed, 0 failed`. Detalhe: `PLANO_MESTRE_PRINCE2.md §15.21.2`/`§15.21.3`/`§15.21.4`. `registry.yaml` NÃO tocado (freeze `AG-126` ativo). Pendente: `AG-179` (fora de escopo por desenho), ressalva de magnitude de `AG-159`, §11 do design doc (caminho HMM) — represados pro Manager |
| **Núcleo funcional, casca imperativa** | Princípio formalizado (`CLAUDE.md`), 5 violações reais + 1 achado extra (HIGH, `project_assurance`) fechados. `triple_barrier.py`/`fill_simulator.py` (ponto de injeção `filters_by_date`/`tick_size_by_date`), `faixa1_5_prerequisites.py` (`hhi_df`), `attribution.py` (split `_load_payloads`/`_aggregate_payloads`), `pipeline.py`+`hhi.py`+`baselines.py` (`gate3_4_passes`/`gate3_4_max_share_passes`/`b1_sample_size`). `1734 passed` + `7 passed` de integração. Pendente: teste sintético completo pra `compute_fase2_e1` (18 células) — arquitetura fechada, cobertura parcial, registrado como pendência explícita. Detalhe: `PLANO_MESTRE_PRINCE2.md §15.22`, `docs/nucleo_casca_design_doc_2026-08-23.md`, `AG-184`–`AG-189` |
| **`CLAUDE.md` — governança do próprio arquivo de instruções** | `AG-190` fechado, commit `e5395fb`. `## Projeto` ganhou nota `[PRECISÃO]` apontando pra `AG-042`/`canonical_bar_type: dollar`/R1/R2/R3 (deixa explícito que "R1 = 15m equivalente" é leitura errada); `## As 5 restrições invioláveis` ganhou nota `[DESATUALIZADO]` (valores vêm do PRD_V3_2 obsoleto, BTC-único, nunca remedidos multi-ativo/dollar-bar); B21 reescrito pra refletir `dynamax.GaussianHMM` k=4 como candidato canônico de produção real (não mais "V1.1" hipotético). Verificação não-exaustiva — `## Layer hierarchy` (falta `monitoring/`/`core/`/`io/`) e cadência de B22 (`AG-155`, já aberto) ficam como pendência menor |
| **`feature_a13_ema_window` — clock↔bar-count em código** | `AG-043` addendum, `§15.23`. Único campo `scaling_invariant: clock` do Feature Engine ganhou implementação real (`_clock_reference_bar_duration_ms`/`_scale_clock_window_bars`, `src/features/build.py`) — 48/24/12 barras sob R1/R2/R3, bit-exato sob `time_15m`. Correção de rumo registrada: 2 propostas de reclassificar A13 pra `bar_count` (apoiadas em literatura real) descartadas após releitura de `AG-043` mostrar que a exceção já era deliberada e justificada. `E27f_cost_atr_ratio`/`atr_window` confirmados como separação correta, não gap. Doc-drift `registry.yaml::min_warmup_bars` (2000→200) corrigido junto. 9 testes novos, mecânicos limpos. **`triple_barrier.py`**: `bars_15m`→`bars_df` renomeado (cosmético, delegado, commit `1734d96`) — `71 passed` confirmado pelo usuário |
| `AG-137` — decidido e fechado 2026-08-22 | Manager decidiu deletar. 104 arquivos `.parquet` stale (calibração não-causal antiga, `cadence_days` dias iniciais de cada uma das 15 células) removidos de `data/capacity/dollar_bars_r{1,2,3}/`. Verificado: 0 restante, cada célula agora começa exatamente em `SYMBOL_START_DATE + cadence_days` — gap honesto, não dado errado. Levantada e respondida no mesmo momento: a pergunta de como isso vai se comportar no Live (ver `PLANO_MESTRE_PRINCE2.md §15.15` addendum) — cold-start é um artefato de BORDA DO HISTÓRICO, não recorre no lançamento do Live pros 5 símbolos existentes (haverá anos de histórico real disponível); o gap real e ainda não resolvido é que `build_dollar_bars_walkforward` hoje é uma função de LOTE (intervalo finito), não um processo contínuo — não existe ainda o equivalente ao vivo (`src/live/` vazio, Sprint 12+). |
| **`verify_config_hash` (B15) no caminho real de consumo** | `AG-140` FECHADO, `§15.24`. `src/models/dataset.py::build_modeling_frame` verifica `config_hash` dos labels contra a config de execução antes de montar o frame. `resolution_id` agora exige `vol_estimator_id` explícito (achado colateral). Confirmação empírica achou drift REAL contra `labels/v1` de produção — investigado (git log: nenhum parâmetro mudou, é o FORMATO do hash que migrou 5x historicamente, `AG-005`/`031`/`042`/`116`) — usuário reprocessou os 5 símbolos (`build_and_write_labels_for_symbol`/`run_and_write_labels_for_alts`), `2 passed` (era `2 failed`). `AG-138`/`AG-139` (mesmo fan-out, mesma severidade "alto") **fechados na sessão seguinte, mesmo dia** — ver linha "CLI causal + magic-number lint" abaixo. Fila real restante: `AG-141`/`142` (persistência de modelo/diagnóstico, trabalho de integração maior, não correção pontual) |
| **CLI causal + magic-number lint (`AG-138`/`AG-139`)** | Ambos FECHADOS, `§15.25`, commit `ef7f5d3`. `build_dollar_bars.py` ganhou `--mode {single_window,walkforward}` — `walkforward` aciona `build_dollar_bars_walkforward` (recalibração causal, `AG-124`) direto do CLI, antes só via script separado; `single_window` (legado) emite `logger.warning` explícito sobre o vazamento de 18,18x. `support.py` ganhou os 2 `# noqa: magic-number` faltando — `banned_patterns.py --strict` volta a passar limpo. 4 testes novos de CLI. Dos 3 achados "alto" que travavam o gate "Data Layer 100%" (`§15.14`), os 3 estão fechados agora (`AG-138`/`139`/`140`) — resta só `08_SPLIT` (2 decisões do Manager) e o débito já aceito de `06_BARREIRAS`; achados "médio"/"baixo" do mesmo fan-out não varridos |
| **Expurgo da grade de relógio 15m — Fases 1-3 CONCLUÍDAS** | `AG-232`/`AG-233`/`AG-235`/`AG-238`/`AG-240`. S1 e M6 migrados para R1/R2/R3 e re-medidos; guardrail `tests/unit/test_governanca_grade_producao.py` quebra o build se módulo novo de `analysis/` ler a grade de relógio. **Geometria de barreira: pergunta RESPONDIDA** — todas as células viáveis dão gap 5,95-6,19 bps, trocar renderia +0,02 bps; recomendação é NÃO trocar `tp_atr_mult`/`sl_atr_mult`. **Pendente:** Fase 4 (mover artefatos 15m para `data/labels_pre_ag221_relabel/`) e `faixa2_e2_research` (único módulo não migrado, débito registrado na whitelist) |
| **`I²` do M6 re-medido — premissa de escopo multi-ativo enfraquecida** | `AG-238`. O `I²=96-98%` citado em decisão de escopo era da grade errada; o real na grade de produção é **61-83%**, caindo monotonicamente com a duração da barra. H0 segue rejeitada (p<0,05) mas em R1 SHORT o p vai de 7e-30 para 3,8e-02. **A leitura POR LADO inverte** — no 15m o SHORT era o lado de edge pooled ~nulo, na produção é o pior nas três resoluções: decisão apoiada em "SHORT é o lado neutro" está invertida. **Causa da inversão NÃO separada** (relabel x grade) — exigiria M6 sobre a grade 15m relabelada, que não existe. Evidência: `audit/evidence_ledger.yaml::m6_i2_r{1,2,3}_{long,short}` |
| **B15 estava barrando toda a produção — `AG-236` FECHADO** | O relabel de `AG-229` gerou os labels sob `entry_fill_source="agg_trades"` mas `from_constants()` não tinha de onde ler o valor: `build_modeling_frame` e a cadeia inteira do Alpha falhavam em `verify_config_hash`. Resolvido por `config/constants.yaml::label_entry_fill_source` (DERIVED, classe A, sweep EXECUTADO) + default técnico no dataclass — 1ª tentativa (flipar o default do dataclass) quebrou 43 testes e foi descartada por medição. Hashes de produção reproduzidos bit-exato. **A grade 15m agora falha alto em B15 — o expurgo acontece por MECANISMO, não por deleção** |
| **`AG-237` — guardrail de sweep removido sem decisão** | `sweep_range` tinha sido removido de `tp_atr_mult`/`sl_atr_mult` em `config/constants.yaml` (ambas classe A) na troca de valor de 2026-08-24, junto com `sweep_required: false` — removendo o guardrail da §16.10 regra 4 das duas constantes que governam a geometria de payoff. Restaurado `[1.0, 3.0]`; `sweep_required: false` mantido, mas agora sustentado pelo S1 na grade CERTA (`AG-235`), não pela medição inválida. Detectado por um teste que falhou por outro motivo |
| **ADR-004 Fase 0 — `AG-241`, implementada e NÃO executada** | Bootstrap estacionário por blocos (Politis & Romano 1994), block length MEDIDO via ACF (B23), escolhido sobre Ledoit-Wolf porque a fórmula HAC tem pontos onde erro de sinal produz veredito confiantemente errado. Roda dentro de `run_layer1_sprint` sobre `ret_net` já materializado — zero retreino. 8 testes sintéticos passam; **nenhum resultado real ainda**. **Dois riscos a medir antes de confiar no 1º veredito:** (a) o zero-filling da casca pode encurtar o block length e estreitar o IC, produzindo o FALSO POSITIVO que a fase existe para evitar; (b) custo `O(n × n_boot)` em Python puro. Prompt de continuação: `docs/prompts/execucao_adr004_fases_1_a_3_2026-08-25.md` |
| Pendente — governança e re-execução | (1) **Road Map Vivo dessincronizado** — republicado por sessão paralela, contradiz 4 achados desta sessão (mesmo padrão `AG-080`/`AG-123`); (2) tabela antes×depois dos 78 experimentos derivados de label, pedida pelo Manager, não feita; (3) Camada 0 interrompida no `src/analysis/m3_timeframe_choice.py` — 14 módulos na fila, agora re-executáveis porque S1/M6 já migraram; (4) **`AG-230` aguarda decisão do Manager** — viés de amostra isolado em BTCUSDT (−1,9%, jan-fev/2021, `n_empty_mark_window` 0→6149): causalmente correto, mas remove barras de regime de rajada |

---

## 2026-08-26 — ADR-005 §13 v2, itens 1-4/10/11b/11 da ordem de `§13.17`

**Nota de staleness explícita:** a tabela "Estado atual (2026-08-25)" acima
não foi reconciliada com o trabalho abaixo nem com o resto do dia
(`ADR-005` v2 completo, `§14` v2/v3, expurgo de features `AG-295`) — sinalizado
em vez de deixar passar em silêncio (mesmo espírito da nota já existente sobre
o número de Sprint). Quem quiser o estado real de hoje usa `git log
--oneline` + `docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md`
(canônico da frente de ML/Feature Engine desde 2026-08-20), não esta tabela.

Persona `lgbm-crypto-quant`, convocada pelo Manager para assumir `ADR-005
§13` depois que a sessão paralela (`feature-thesis-auditor`) fechou o
desenho de features. Ordem de execução autorizada item a item
(`§13.17`), **não** em lote.

- **Itens 1/2/3/3b (pré-requisito de tudo, `§13.8`/`§13.11`)** —
  `feature_ids` obrigatório nos 5 call sites (`AG-298`); NaN→null na
  fronteira, coluna 100% nula falha o build (`AG-300`); censo de nulos
  por coluna×célula persistido (`AG-308`); detector de linhagem
  `labels↔registro` (`AG-309`) — achado real: o registro de
  `label_engine_runs.parquet` descrevia labels que já não existiam mais
  (20/20 artefatos divergentes), causa parcialmente estabelecida <!-- check-sprint-log: skip -->
  (`build_and_write_labels_for_symbol` chama `record_experiment`, mas a
  chamada é sequência, não transação). Item 3c ("reprocessar o registro <!-- check-sprint-log: skip -->
  retroativamente") **rejeitado por mim mesmo** — fabricaria proveniência
  de auditoria pra fazer um lint passar, exatamente o que um log
  append-only existe pra impedir.
- **Item 4 — peso do calibrador isotônico (`AG-312`)** — decisão do <!-- check-sprint-log: skip -->
  Manager, opção (b): `IsotonicRegression.fit(..., sample_weight=w)`
  devolve `E_w[y|x]`, não `E[y|x]`; o peso legado (`uniqueness *
  |ret_net|`) sub-ponderava a classe positiva e enviesava a saída do
  calibrador em até −13,0% (`P(TP)` medido 0,4967, calibrador legado <!-- check-sprint-log: skip -->
  entregava 0,4323). Sob `uniqueness` sozinho o viés cai pra <!-- check-sprint-log: skip -->
  `[−0,0012, +0,0030]`. Política nomeada `calib_weight_basis`, default <!-- check-sprint-log: skip -->
  de `fit_side_model` continua legado (bit-exato), default de PRODUÇÃO
  vira `uniqueness`. **Achado colateral não previsto por mim**, levantado
  pela sessão paralela ao revisar a proposta: `alpha.py` escolhe o lado
  comparando `p_long > p_short`, e os dois vinham de calibradores
  DIFERENTES com viés diferente — viés sistemático a favor do LONG. A
  opção (b) reduz isso (|viés| por lado de até 0,072 para no máximo
  0,003) mas não zera o diferencial residual (+0,0005 a +0,0063) — fica
  registrado como item aberto próprio, não argumento contra (b).
- **Label Engine reprocessado ponta a ponta** (mesmo commit do item 4,
  `6ec2af9`) — `run_and_write_labels_dollar_bar_parkinson` rodado pras 15
  células reais (R1/R2/R3 × 5 símbolos). Resultado: **15/15 idênticas**
  ao snapshot pré-rerun (mesmo `n`, mesmo `config_hash`, mesmo `NOFILL`)
  — o risco declarado antes de rodar ("o lake pode ter crescido, o
  arquivo pode sair diferente") não se materializou, e só dava pra saber
  medindo. Lint de linhagem caiu de 20 divergências pra 5 — as 5 que <!-- check-sprint-log: skip -->
  sobram são a grade de relógio 15m legada, deliberadamente não rodada
  (exige `confirmo_grade_de_relogio_legada=True`, `AG-248`, decisão
  explícita pendente do Manager).
- **Item 10 — manifesto completo por célula + verificação na carga
  (`AG-314`, `§13.21`)** — `src/models/persistence.py` (`AG-141`) já
  existia mas não tinha `ess`/`purge_ms_effective`/`min_child_samples`/
  hash do conjunto, e `read_model_bundle` não verificava
  `manifest.feature_ids == booster.feature_name()` na carga — sem essa
  checagem, um manifest com `feature_ids` na ordem errada produziria
  inferência silenciosamente errada. `ManifestFeatureMismatchError` nova,
  1 teste prova o bug que ela existe pra evitar. **Não fecha `AG-141`** —
  o wiring em produção (`run_fold` chamando `write_model_bundle`) segue
  aberto, por decisão de escopo.
- **Item 11 — `p̂ > breakeven(linha)` (`AG-315`, `§13.22`)** — achado
  central do dia: o GATE já existia em código sem reconhecimento, como
  caso degenerado de `decide_side_cost_derived` (ADR-004 Fase 2,
  `lambda_b = -payoff_atr_mult`). Verificado por 2 vias independentes
  (contra a função irmã E contra a fórmula fechada recalculada à parte).
  O que não existia: o teto de capacidade por RANKING de margem que o
  ADR pede ("top-q por margem") — `resolve_joint_lambda` (mecanismo já
  em produção-de-medição) aplica um limiar ESCALAR sobre `mu`, que
  DIVERGE do ranking por margem quando o custo varia entre linhas
  (provado com caso mínimo real, não só descrito). 4 funções núcleo puro
  novas, nenhuma chamada por `run_fold` ainda — qual mecanismo de teto
  vira produção é decisão do Manager, `§13.17` já lista o item como
  "decisão, não modelo".
- **Item 11b — censo de admissibilidade R2 por linha (`AG-296`/`AG-297`,
  `§13.20`)** — R2 nunca era aplicada em `src/models/` (só em 3 módulos
  de `analysis/`); medido por linha, R2 viola 27,12% (BNBUSDT/R1) até
  0,00% (XRPUSDT/R3), monotônico em resolução nos 5 símbolos. Achado
  colateral: 177 labels (0,006%) com `ganho ≤ custo` — geometricamente
  impossível de empatar, concentrado em SOLUSDT/R1-R2.
- **Deslize de coordenação, resolvido sem perda:** o commit `6ec2af9`
  incluiu por acidente a entrada `AG-313` da sessão paralela (`git add`
  amplo demais no `architecture_gaps_log.yaml` append-only). Sem dano —
  o log é append-only, nada corrompeu — mas o código/artefato que
  acompanhava a entrada ficou de fora do meu commit. A sessão paralela
  commitou o resto por cima (`ee0a83d`) reconhecendo que a entrada já
  estava logada; nenhuma duplicata, nenhuma ação corretiva necessária.
- **Mesmo deslize, na direção oposta, também sem perda:** entre eu
  escrever `§13.21`/`§13.22` + `AG-314`/`AG-315` (ainda não commitados)
  e eu tentar commitá-los, a sessão paralela commitou `0f9e915` no MESMO
  working tree — viu `AG-314`/`AG-315` já ocupados no arquivo (minhas
  edições, ainda em disco) e renumerou os próprios achados novos pra
  `AG-321`/`AG-322` (mesmo procedimento de colisão já usado hoje 6x).
  O commit deles arrastou minhas edições de `ADR-005`/`architecture_
  gaps_log.yaml` junto (working tree compartilhado). Conferido byte a
  byte: nenhuma linha minha apareceu como remoção no diff deles, `git
  status` bateu zero depois — meu conteúdo sobreviveu intacto, só sob a
  mensagem de commit deles. Nada a corrigir; só registrado pra explicar
  por que esses dois arquivos não aparecem no commit que eu de fato fiz
  (`df113c3`, só `persistence.py`/`alpha.py`/testes/`SPRINT_LOG.md`).
- **`AG-141` fechado no mesmo dia** (`§13.21.1`) — a metade de
  integração do item 10 que tinha ficado de fora deliberadamente:
  `pipeline.write_all_fold_model_bundles`, chamado por `run_layer1_
  sprint` (opt-in, `persist_model_bundles=False` por default, gate
  adicional `path_tf is not None`). Grava o `tau` EFETIVAMENTE aplicado
  (de `predictions`, não o per-side de `fit_side_model`) — os dois só
  coincidem sob a política legada; um teste prova a divergência com
  números diferentes de propósito. `ModelBundleExistsError` propaga sem
  tratamento -- reexecutar sobre uma partição já persistida falha, nunca
  sobrescreve. 8 testes novos (4 mecânica + 4 roteamento). <!-- check-sprint-log: skip -->

Suíte completa (`-m "not slow"`) verde nas três rodadas do dia: 2267
passed (itens 10/11) → 2267 passed (confirmação pós-noqa) → **2275
passed, 2 skipped, 2 xfailed, 0 failed** (com o wiring de `AG-141`, +8
testes novos). `ruff`/`mypy --strict`/`banned_patterns` limpos em todos
os módulos tocados.

- **Pedido do Manager: "valide e aplique cada Fix mecânico" — itens 5,
  6, 8, 9 de `§13.17` (`AG-323`–`AG-326`)** — todos aplicados como
  código opt-in, testado, default preservando bit-exato (mesmo molde do
  resto do dia). Item 6 (piso de magnitude, `se_spearman_fisher` +
  `ic_magnitude_floor_k`), item 8 (regularização por ESS,
  `derive_ess_regularization`, INERTE sob a árvore rasa atual), item 5
  (nulo de permutação, `compute_permutation_null_headline` + `backtest_
  lite.percentile_rank`), item 9 (`early_stopping` em 3 partições,
  `_temporal_purged_three_way_split`, achado de implementação: `eval_
  set` está deprecated no LightGBM 4.7.0, usa `eval_X`/`eval_y`). 6
  constantes novas em `constants.yaml`, todas `ASSUMED`/classe B/sweep
  declarado -- nenhuma medida neste projeto, escolhas de engenharia
  declaradas a priori. **Nenhum dos quatro foi promovido a default de
  produção** -- promoção é decisão do Manager, cada um muda o que o
  modelo treinado de fato é.
- **Achado da varredura, sharpened em decisão concreta**: o "retreino
  represado" tem uma causa técnica imediata além da decisão de escopo
  -- reproduzido ao vivo, `compute_max_feature_lookback_ms` com o vetor
  ativo real (68 features, não mais 69 -- `AG-295` cortou uma) levanta <!-- check-sprint-log: skip -->
  `ExpandingFeatureLookbackError` HOJE, nomeando 5 features de janela <!-- check-sprint-log: skip -->
  expansiva. Já registrado (`AG-298`, 2026-08-26 mais cedo), mas nunca
  isolado como item de decisão próprio -- duas saídas nomeadas
  (remedir a constante de janela, ou excluir as 5 do vetor ativo, mesmo
  caminho já usado com outras 3 via `AG-032`). Publicado como artefato
  "Pauta §13" -- tabela completa de pendências do Manager, fix mecânico
  e itens que ainda exigem elaboração/teste, ponta a ponta do escopo
  `§13`.

Suíte completa (`-m "not slow"`) ao final: **2316 passed, 2 skipped, 2
xfailed, 0 failed** (+41 testes novos). `ruff`/`mypy --strict`/
`banned_patterns` limpos em todos os módulos tocados. Item 7 de `§13.17`
segue como decisão pendente do Manager (autorizar a reexecução do teste
H₀, zero `N_lifetime`, critério já declarado a priori) -- não é mais
"bloqueado por retreino", é bloqueado pela mesma trava de vetor que os
outros quatro, mais a autorização em si.

- **`AG-330` investigado, addendum registrado, Estágio 1 codificado e <!-- check-sprint-log: skip -->
  EXECUTADO** — eixo 1 mede a pergunta errada pra features de papel <!-- check-sprint-log: skip -->
  filtro/custo (`E27f_cost_atr_ratio`, T1). Medido contra gain de <!-- check-sprint-log: skip -->
  modelos REAIS já treinados (`experiments/alpha_full_analysis_2026-08- <!-- check-sprint-log: skip -->
  24.json`, 30 blocos): `E27f` é a feature de maior gain em 25 dos 30 <!-- check-sprint-log: skip -->
  (~38% de excesso sobre o piso uniforme) apesar de zero descoberta no <!-- check-sprint-log: skip -->
  eixo 1 — confirma a tese, não fica no hipotético. `src/analysis/ <!-- check-sprint-log: skip -->
  eixo1_gain_cross_check.py` (núcleo puro + casca, 13 testes) formaliza <!-- check-sprint-log: skip -->
  a medição, sem retreino. Achado de rigor: minha primeira leitura
  manual (amostra de 1 bloco) errou o caso de `C06_vol_ratio_12_96`
  (classificou "sem contradição"; a agregação completa mostra que
  também cruza o piso, por margem bem mais fraca que `E27f`) — corrigido
  no próprio addendum antes de reportar. Manager autorizou execução
  direta (`uv run`/`.py`) nesta sessão.
- **Manager ratifica B/C/E/F da "Pauta §13" — cada item revalidado
  contra código real antes de aplicar** ("modo chief architect", houve
  mudanças de outra sessão paralela em features desde a rodada
  anterior). **B** (teto de capacidade, item 11): medir os dois
  mecanismos lado a lado no próximo retreino, não escolher agora —
  `alpha.compare_cap_mechanisms` (núcleo puro novo, 4 testes) roda <!-- check-sprint-log: skip -->
  `resolve_joint_lambda` e `decide_side_breakeven_topq` sobre a mesma
  população e reporta a divergência, pronto pra quando o retreino
  desbloquear. **E** (objetivo): `objective="binary"` ratificado,
  decisão fechada — documentação atualizada, zero código (já é o
  default). **F** (grade 15m legada): "não rodar, obsoleta e morta" —
  verificado contra `AG-229` antes de aplicar (grupo de controle já
  intacto/congelado, a ratificação não contradiz nada) e contra o disco
  real (exatamente as 5 células `{symbol}/15m` divergentes hoje, os 15
  cells de dollar bar seguem fechados). `src.labels.experiment_log.
  KNOWN_LEGACY_GRADE_LINEAGE_GAPS` + `accepted_gap` formalizam a exceção
  no detector (`AG-309`) — a divergência continua visível, só deixa de
  falhar o lint (`exit 0` confirmado contra dado real, autorização do
  Manager pra execução direta). **C** (H₀ do item 7): ratificado em <!-- check-sprint-log: skip -->
  princípio ("assim que item A destravar"), mas A segue bloqueado —
  reverificado ao vivo, `ExpandingFeatureLookbackError` continua ativo
  pras mesmas 5 features. Achado lateral registrado (`AG-335`), não <!-- check-sprint-log: skip -->
  decidido: 4 dessas 5 já aparecem `layer: [L4]` num campo NÃO commitado
  de uma sessão paralela (census L0-L4), sem ficha de suporte — pode
  coincidir com a recomendação já registrada pra A, mas não é base
  estável pra agir sem revisão; nenhum código de `SUPPORT_FEATURE_IDS`
  tocado. `AG-315`/`AG-309` ganharam addendum cada; nenhuma célula real
  de produção alterada pelas quatro ratificações.

Suíte completa (`-m "not slow"`) ao final: **2406 passed, 2 skipped, 2
xfailed, 0 failed** (+13 do Estágio 1 do `AG-330` + 4 do item B + 4 do
item F = 21 testes novos desde a rodada anterior). `ruff`/`mypy
--strict`/`banned_patterns`/`check_unguarded_ratios`/`check_constants_
referenced`/`check_constants_provenance` limpos em todos os módulos
tocados. Nada commitado ainda nesta rodada — pendente de o Manager
confirmar quando fechar em commit.

- **Pedido do Manager: "abra investigação ponta a ponta para os 4 itens
  que podem ser fechados sem full run do Alpha"** — os 4 itens
  restantes da tabela de decisão (A/C/D/G). **A fechado nos DOIS
  degraus, não só o primeiro** (`AG-298`/`AG-335`): as 5 features
  `lookback_bars: expanding` saíram de `SUPPORT_FEATURE_IDS` (a
  classificação `layer: L4` que uma sessão paralela tinha deixado
  não-commitada virou base real no meio da investigação — commitada em
  `ff63edd` com instrução explícita do Manager por trás). Achado NOVO,
  não resolvido só tirando as 5: sem elas, o vetor ainda exigia
  `window_bars=69673` (`C08_vol_pctile_rolling_1y`) — medir isso de
  verdade (depois de corrigir `tools/diagnostics/measure_max_
  consecutive_bar_window_duration.py`, que ainda lia a função CEGA ao
  registry, o mesmo defeito que o achado original documentou) revelou
  que R2 exigiria ~4,2 anos de janela e **R3 não tem 69.673 barras em <!-- check-sprint-log: skip -->
  nenhum dos 5 símbolos** — não era uma constante desatualizada, era <!-- check-sprint-log: skip -->
  irrealizável. `C08` saiu também (também `layer: L4`) — vetor caiu <!-- check-sprint-log: skip -->
  pra `288` bars (`E03f_funding_cum_3d`), `max_consecutive_bar_window_ <!-- check-sprint-log: skip -->
  duration_ms` remedido sob esse valor (15/15 combinações reais, pior <!-- check-sprint-log: skip -->
  caso SOLUSDT/R3=606,53h). Verificado end-to-end: `compute_max_ <!-- check-sprint-log: skip -->
  feature_lookback_ms` resolve limpo pro vetor de produção real (61 <!-- check-sprint-log: skip -->
  features, era 69) nas 3 resoluções E na grade 15m legada. **C <!-- check-sprint-log: skip -->
  exigindo treino real, só a precondição fechou. **D** — a razão
  "ESS pooled superestimado sem correção two-factor" ganhou precisão:
  o fator transversal já estava medido (`n_eff=2,03`, `AG-255`,
  2026-08-25) e tinha sido esquecido da conversa; falta compor com o
  fator intra-símbolo, trabalho estatístico real, deliberadamente NÃO
  tentado por risco de derivação errada. Recomendação (não autorizar
  agora) não muda. **G** — `evaluate_economic_gate`/`load_min_alpha_
  lift_by_combo` novos em `src/analysis/economic_gate.py` (10 testes,
  39 no arquivo): mecanismo de comparação candidato-vs-breakeven pronto,
  não wireado em nenhum orquestrador (nenhum existe ainda) — decisão de
  tornar o gate binding continua do Manager.

Suíte completa (`-m "not slow"`) ao final desta rodada: **2418 passed, 2
skipped, 2 xfailed, 0 failed** (+12 testes novos desde a rodada anterior
-- 10 de `evaluate_economic_gate`/`load_min_alpha_lift_by_combo`, 2 de
ajuste nos testes de `test_features_build.py` que passaram a cobrir o
vetor de produção real em vez de `T1_FEATURE_IDS` isolado).
`ruff`/`mypy --strict`/`banned_patterns`/`check_constants_provenance`
limpos em todos os módulos tocados (`src/features/build.py`,
`tools/diagnostics/measure_max_consecutive_bar_window_duration.py`,
`config/constants.yaml`, `src/analysis/economic_gate.py`,
`tests/unit/test_features_build.py`, `tests/unit/test_economic_gate.py`).
Nada commitado ainda.

## 2026-08-27 — orquestrador de trial do gate econômico (AG-260 ponto b)

**Pedido do Manager: "execute o orquestrador ponta a ponta"** — via
`/redesign_workflow` (7 fases completas), fechando o ponto (a) do
`status` de `AG-260` ("um orquestrador de trial pra plugar nele — não
existe ainda"). O item G da rodada anterior (`evaluate_economic_gate`/
`load_min_alpha_lift_by_combo`, mecanismo pronto e dormant) ganhou um
ponto de entrada real.

**Decisão de arquitetura (resposta do Manager, via pergunta explícita
nesta sessão):** `EconomicGateError`/`GateRow`/`EconomicGateVerdict`/
`evaluate_economic_gate`/`load_min_alpha_lift_by_combo` migraram de
`src/analysis/economic_gate.py` para um módulo novo, `src/models/
economic_gate.py` — essas funções estavam prestes a virar insumo real
de TREINO (chamadas por `pipeline.py`), e `analysis/` fica fora do
contrato `importlinter` de propósito, nunca pode virar isso (`CLAUDE.md`,
Layer hierarchy). Confirmado contra `pyproject.toml::[tool.
importlinter]` que a direção `analysis → models` é a permitida (nunca o
inverso) — `analysis/economic_gate.py` reimporta `GateRow`/
`EconomicGateError` de volta via reexport explícito (`import X as X`,
mesmo padrão de `ARTIFACT_ROOT`/`MODELS_DIR`, `AG-154`). A derivação da
tabela a partir do sweep S1 continua em `analysis/` — é medição pós-hoc
genuína, não migrou.

**Mecanismo novo** em `src/models/economic_gate.py`: `lookup_pre_trial_
gate(symbol, resolution_id, *, table=None)` — ponto de injeção zero-IO,
`None` no miss ou no retorno, nunca inventa — e `suggested_n_lifetime_
delta(*, trained)` — devolve 1/0, NUNCA escreve em `audit/n_lifetime.
yaml` (ledger continua mantido à mão pelo Manager, confirmado via
pergunta direta nesta sessão sobre a relação entre os dois).

**Wiring** em `src/models/pipeline.py`: `use_economic_gate: bool =
False` em `run_layer1_sprint`/`run_layer1_sprint_all_combinations` —
default preserva bit-exato. `True` LOGA (nunca bloqueia — "soft-flag
apenas", decisão explícita do Manager) antes do treino (`required_lift`/
`breakeven_wr` da célula) e depois (`report["economic_gate"]` com
veredito por lado via `_economic_gate_verdicts_by_side`, núcleo puro que
recebe o `GateRow` já resolvido — uma só leitura do YAML por chamada, não
duas — e `report["n_lifetime_suggested_delta"]`).

**Fase 6 (3 agentes `code-reviewer` em paralelo — corretude, simplicidade/
DRY, convenções/arquitetura):** zero achado de corretude ≥80 confiança.
5 achados de qualidade corrigidos antes de fechar: IO escondida na função
de pós-treino (chamava `lookup_pre_trial_gate` de novo em vez de
reaproveitar o já resolvido — corrigido, função virou testável sem disco);
`_Z_95` duplicado sem motivo real (trocado por import); `logger` morto em
`models/economic_gate.py` (removido — módulo é núcleo puro por desenho);
campo de log `erro=` divergindo da convenção `error=` do resto do
arquivo; namespace de log com 4 segmentos divergindo do padrão de 3.
Docstring de `evaluate_economic_gate` também corrigida (descrevia
`best_per_combo` como "o lado mais exigente" quando na verdade é o de
MENOR lift — erro de descrição, sem efeito em comportamento).

**O que continua em aberto, sem mudança:** SE o gate deve ser vinculante
(ponto (b) de `AG-260`) — decisão de política de risco do Manager, fora
do escopo desta implementação por desenho. O caminho `use_economic_
gate=True` dentro de um `run_layer1_sprint` real (CPCV completo) não foi
exercitado ponta a ponta — só a função `_economic_gate_verdicts_by_side`
isolada, com dado sintético (mesmo racional de custo de `test_models_
pipeline_paths.py`, evita pagar ~117s de retreino por um teste de
roteamento já coberto no nível da função pura).

Suíte completa (`-m "not slow"`) ao final: **2429 passed, 2 skipped, 2
xfailed, 0 failed** (+5 testes novos desde a rodada anterior --
`tests/unit/test_models_pipeline_economic_gate.py`; os 17 de `tests/
unit/test_models_economic_gate.py` e o trim de `test_economic_gate.py`
já estavam somados no `2424` intermediário desta mesma rodada). 7 checks
mecânicos (`banned_patterns`/`check_unguarded_ratios`/`check_constants_
referenced`/`check_constants_provenance`/`check_sprint_log_references`/
`ruff`/`mypy --strict`) limpos em todos os módulos tocados/novos
(`src/models/economic_gate.py`, `src/analysis/economic_gate.py`,
`src/models/pipeline.py`, `tests/unit/test_economic_gate.py`,
`tests/unit/test_models_economic_gate.py`, `tests/unit/test_models_
pipeline_economic_gate.py`) — comparados contra `HEAD` pré-sessão pra
isolar débito pré-existente de regressão nova. `AG-260` ganhou addendum
(`audit/architecture_gaps_log.yaml`). Nenhuma entrada nova em
`PLANO_MESTRE_PRINCE2.md` — julgamento de que é correção arquitetural
de implementação sobre gap já rastreado, não decisão de governança/
roadmap nova; sinalizado ao Manager pra override se discordar.

## 2026-08-27 — handoff de `src/models/` (4 achados + adendo AG-343/AG-344), validados de forma independente

**Pedido do Manager: handoff de uma sessão paralela com 4 achados reais
em `src/models/`, mais um adendo de 2 achados novos — "validar cada um
de forma independente (não confiar cegamente na descrição) e aplicar a
correção onde a validação confirmar".** Todos os 6 confirmados por
leitura direta de código/medição, nenhum aceito por presunção — 2
divergências reais entre a descrição do handoff e o que a medição
mostrou, corrigidas antes de agir (ver abaixo).

**1. CLI de `pipeline.py` revertia silenciosamente `AG-272`** — <!-- check-sprint-log: skip -->
`_parse_args` declarava os defaults LEGADOS de `--calib-split-mode`/
`--class-balance-basis` e sempre os passava explícitos pra `run_layer1_
sprint`, mascarando a promoção real da função (`TEMPORAL_PURGED`/
`WEIGHT`). Confirmado com prova de dano real: 8 relatórios em
`experiments/*_ag207_k62.json` gravam os valores legados. Fix: `default=
None` nos dois + `_optional_policy_kwargs` (nova função testável) só
inclui a chave quando o usuário passa a flag — nunca mais duplica um
literal que já vive na assinatura da função, mesmo se ela for promovida
de novo no futuro. 4 testes novos
(`tests/unit/test_models_pipeline_cli.py`).

**2. R2 (`CLAUDE.md` §0.2) nunca era aplicada em `src/models/`, e
`sample_weight` amplificava justamente as linhas que violam** —
`side_subset` não filtrava por custo/stop; `apply_weights` (`uniqueness
* |ret_net|`) dá peso MAIOR às linhas mais catastróficas. Medido contra
o censo já existente (`experiments/r2_admissibility_census.json`,
`AG-296`/`AG-297`): 27,12%/26,71% das linhas de BNBUSDT/R1 violam R2 —
**divergência corrigida em relação ao handoff**: os "177 linhas" citados
no texto original eram de uma métrica DIFERENTE (`n_tp_nao_cobre_custo`,
o subconjunto degenerado onde nem 100% de acerto cobriria o custo,
0,006% GLOBAL concentrado em SOLUSDT) — não a contagem de violação de
R2 em si. Núcleo puro (`cost_fraction`/`stop_fraction`/`viola_r2`)
movido de `src/analysis/r2_admissibility_census.py` pra um novo `src/
labels/r2_admissibility.py` (mesmo padrão do split de `economic_gate`
do dia anterior — `models/` não pode importar `analysis/`, mas pode
importar `labels/`). `side_subset` ganhou `enforce_r2: bool = False`
(opt-in, default bit-exato), repassado por `run_fold`/`run_all_folds`
(`alpha.py`) — mesma profundidade de wiring de `evaluate_cost_derived_
lambda` (não chega em `pipeline.py`/CLI, precedente real já existente
no mesmo arquivo). 13 testes novos.

**3. `E11f_oi_change_1d` (`defeito_construcao: true`) já entrou num
LightGBM real sem gate nenhum** — confirmado via `monotone_constraints_
example_fold0` em `experiments/alpha_layer1_report_BTCUSDT_R1_ag207_
k62.json`. `T1_FEATURE_IDS`/`SUPPORT_FEATURE_IDS` são tuplas hardcoded,
zero enforcement contra o registry. Fix: `assert_no_defeito_construcao_
in_active_set`/`DefeitoConstrucaoFeatureError` em `features/build.py`,
mesmo padrão EXATO de `assert_no_expanding_lookback_in_active_set`/
`ExpandingFeatureLookbackError` (`AG-032`) já existente no mesmo
arquivo — fail-fast, sem exclusão silenciosa, chamado em `run_layer1_
sprint` ANTES de `build_modeling_frame` (trabalho caro de IO). 6 testes
novos, incluindo um que prova a ordem (levanta sem tentar IO real).

**4. 2 combos de `use_hyperparams_by_combo` (`AG-227`, "FECHADO
2026-08-25") rodaram sob labels/purge stale** — confirmado por MEDIÇÃO
direta (não presumido): `labels_config_hash` de `experiments/_
smoketest_production_wiring_BNBUSDT_R3.json` (`a554e71d5437efdc`) não
bate nem com o `config_hash` real de hoje (`ff8dcb98fa579975`) nem com o
snapshot "antes do relabel AG-221" (`921fb547f8d1c7ff`) — três hashes
distintos, confirmando múltiplas mudanças de config, não só o relabel
citado no handoff. Artefato movido pra `experiments/_stale_use_
hyperparams_by_combo/` (mesmo padrão de `pre_ag221_relabel/`) com
`STALE.md`. Não localizei o artefato equivalente de BTCUSDT/R3 citado no
handoff — `AG-227` já registra que essa tentativa colidiu de propósito
com um artefato existente (guarda de imutabilidade); pode não ter
persistido nada novo. `AG-227` ganhou addendum. Sem ação de re-treino
aqui — prevista pra acontecer junto do retreino real das 15 combinações <!-- check-sprint-log: skip -->
já autorizado, não isolada (a própria orientação do handoff).

**Adendo — `AG-343`/`AG-344`, achados de uma revisão `project_assurance`
posterior na mesma sessão paralela.** `AG-343`: docstring de `side_
subset` afirmava que `regime` entra como one-hot no vetor de treino —
falso desde 2026-08-21 (`alpha.py::DESIGN_COLUMNS`, ADR-001 §2.7,
"regime = gate de risco, não feature preditiva"); corrigido. `AG-344`:
nenhum teste travava qual regime engine `build_modeling_frame` de fato
usa (`classifier.QuantileRegimeClassifier` via `regime_build.build_
regimes`, não `build_hmm.build_hmm_regimes`/HMM k=4, apesar do `CLAUDE.
md` já ter corrigido o texto — decisão de wireear HMM continua em
aberto, fora de escopo) — 1 teste novo que levanta `AssertionError`
explícito se `build_hmm_regimes` for chamado, travando a divergência
código/documentação pra CI, não auditoria manual meses depois.

Suíte completa (`-m "not slow"`) ao final: **2461 passed, 2 skipped, 2
xfailed, 0 failed** (+32 testes novos desde a rodada anterior). 7 checks
mecânicos limpos em todos os módulos tocados/novos (`src/models/
pipeline.py`, `src/models/alpha.py`, `src/models/dataset.py`, `src/
labels/r2_admissibility.py`, `src/analysis/r2_admissibility_census.py`,
`src/features/build.py`, mais os 6 arquivos de teste novos/tocados) —
comparados contra `HEAD` pré-sessão pra isolar débito pré-existente de
regressão nova em cada um. `AG-227` ganhou addendum; nenhuma entrada
nova em `PLANO_MESTRE_PRINCE2.md` (mesmo julgamento do item anterior —
correção de código sobre gaps já rastreados, não decisão de
governança/roadmap nova).

## 2026-08-27 — handoff de `src/models/`, 3 desenhos de arquitetura já decididos, mais adendo `funding_bps`

**Pedido do Manager: handoff de arquitetura delegada (sessão paralela,
7 agentes read-only) — 3 itens com a DECISÃO já tomada, meu trabalho era <!-- check-sprint-log: skip -->
validar contra o código real e implementar exatamente a decisão, mais um
adendo pontual de 1 item.** Todos os 4 confirmados por leitura direta. <!-- check-sprint-log: skip -->

**1. Wiring unificado — `regularization_basis`/`early_stopping_mode`/
`ic_magnitude_floor_k` presos em `fit_side_model`** — os 3 (`AG-324`/
`AG-325`/`AG-326`, "IMPLEMENTADO e verde... política NÃO promovida a
default") tinham zero caller acima capaz de setá-los (`run_fold`/
`run_all_folds` nunca os repassavam). Fix: os 3 viraram campos de
`LGBMHyperparams` — `hyper` já atravessa as 3 camadas intacto, então
`run_fold` só precisou ler `hyper.regularization_basis`/etc. e repassar
pros dois `fit_side_model` (long/short), zero parâmetro novo em `run_
fold`/`run_all_folds`/`run_layer1_sprint`. `LGBMHyperparams.from_
constants(use_ic_magnitude_floor: bool = False)` fecha a desconexão
constante↔código de `AG-324` (`alpha_monotonic_ic_magnitude_floor_k`
agora é lida por nome) sem promover o default. Promoção a default de
produção continua decisão do Manager nos 3 casos — não tomada aqui, como
o handoff exigiu explicitamente. 5 testes novos. <!-- check-sprint-log: skip -->

**2. `TIE_REQUIRES_MARGIN` aposentado, `permanence_pass` passa a exigir
significância** — `ADR-004` §6 já tinha decidido que "empate" não é um
margin escalar (nunca calibrado, B23), e sim "o IC de 95% da diferença
exclui zero" — o mesmo instrumento que `AG-220`
(`permanence_significance_by_path`/`n_paths_significant`) já calculava e
o relatório ignorava. `TIE_REQUIRES_MARGIN`/`min_margin` removidos de
`permanence_count` (só a política legada resta — o viés que `AG-214`
documenta continua existindo nessa contagem isolada, de propósito: ela
nunca decide sozinha). Novo `backtest_lite.permanence_pass_criterion`:
`n_better >= min_paths_required AND n_paths_significant >=
min_paths_required` — reusa o piso já declarado, nenhum número novo
(B23). 8 testes novos/atualizados. <!-- check-sprint-log: skip -->

**3. `baselines.py` — família B1 refinada, diagnóstico opt-in** — 4 <!-- check-sprint-log: skip -->
funções que corrigem um viés de variância real (documentado no próprio
módulo) tinham zero caller de produção. **Achado mais sério, registrado
como `AG-360` novo**: a comparação que RODA DE VERDADE (`b1 = <!-- check-sprint-log: skip -->
run_b1_random_entry(..., alpha_sharpe=alpha_sharpe_headline)`, <!-- check-sprint-log: skip -->
`alpha_sharpe_headline` = média de 5 Sharpes) usa exatamente a <!-- check-sprint-log: skip -->
comparação que a docstring do módulo documenta como enviesada (média
com variância reduzida por promediação contra nulo de sorteio único) —
inconsistência ativa entre o que o código documenta como certo e o que
roda. Fix: `run_b1_refinement: bool = False` (opt-in, mesmo padrão de <!-- check-sprint-log: skip -->
`persist_model_bundles`) roda as 4 funções e escreve <!-- check-sprint-log: skip -->
`report["baselines"]["b1_refinement"]`, side-by-side com <!-- check-sprint-log: skip -->
`b1_random_entry` — NÃO substitui (decisão maior, separada, do Manager). <!-- check-sprint-log: skip -->
`_summarize_b1_result` extraído (DRY) pro achatamento numpy→JSON que já <!-- check-sprint-log: skip -->
existia só pra `b1`, reusado nos 3 novos blocos que precisavam do mesmo <!-- check-sprint-log: skip -->
achatamento.

**Adendo — `AG-249` Problema A, `funding_bps` em `side_subset`.** A <!-- check-sprint-log: skip -->
sessão paralela já tinha wireado `funding_bps` opcional em
`src.labels.r2_admissibility.cost_fraction` (default `None`, bit-exato); <!-- check-sprint-log: skip -->
faltava `side_subset` (o call site real de `enforce_r2`, `AG-296`/ <!-- check-sprint-log: skip -->
`AG-297`) passar a coluna. 1 argumento em `dataset.py`, mais o mesmo <!-- check-sprint-log: skip -->
wiring espelhado em `r2_admissibility_census.py` (censo DECISION-SUPPORT <!-- check-sprint-log: skip -->
alinhado com o que `enforce_r2` de fato mede — escolha própria, não <!-- check-sprint-log: skip -->
pedida explicitamente, pra evitar os dois consumidores da mesma fórmula
divergirem). 3 testes novos (2 em `test_models_dataset.py`, mais os já <!-- check-sprint-log: skip -->
existentes de `funding_bps` em `cost_fraction`).

Suíte completa (`-m "not slow"`) ao final: **2479 passed, 2 skipped, 2
xfailed, 0 failed** (+18 testes novos desde a rodada anterior). 7 checks
mecânicos limpos em todos os módulos tocados/novos (`src/models/alpha.py`,
`src/models/backtest_lite.py`, `src/models/pipeline.py`, `src/models/
dataset.py`, `src/analysis/r2_admissibility_census.py`, mais os arquivos
de teste tocados) — comparados contra `HEAD` corrente (que avançou 3x
durante esta rodada, sessão paralela commitando ao vivo no mesmo
working tree) pra isolar débito pré-existente. `AG-324`/`AG-325`/
`AG-326`/`AG-214` ganharam addendum; `AG-360` novo registrado. Nenhuma
entrada nova em `PLANO_MESTRE_PRINCE2.md` (mesmo julgamento das rodadas
anteriores). Escopo deliberadamente NÃO coberto: teste de integração
ponta a ponta de `run_b1_refinement=True` (exigiria fixture de fold real
completo, custo/complexidade desproporcional ao risco — mecanismo já
testado nas 4 funções individuais, mypy strict limpo na wiring nova, <!-- check-sprint-log: skip -->
mesmo padrão de cobertura já aceito pra `evaluate_cost_derived_lambda`
neste mesmo arquivo).

## 2026-08-27 — mudança de política: correção pedida pelo Manager vira default imediatamente, não atrás de flag opt-in <!-- check-sprint-log: skip -->

**Achado do Manager, direto**: reportei os 6 itens do handoff anterior <!-- check-sprint-log: skip -->
como "corrigidos", mas nenhum estava de fato ativo em produção — todos
opt-in, `default=False`/legado, esperando uma SEGUNDA ordem explícita
pra "ligar". Na visão do Manager, isso é atraso, não proteção: "se eu já
dei a ordem pra codar a mudança no arquivo de produção, não tenho que
mandar run com a atualização". Motor em fase de descoberta de edge —
mudar constantemente é o trabalho, `default=legado` não é a régua de
segurança que deveria ser aqui.

**`CLAUDE.md` ganhou regra nova em "Diretrizes de comportamento"**:
correção/mudança pedida pelo Manager é o comportamento DEFAULT a partir
do commit que a aplica, nunca atrás de flag opt-in preservando legado
"por via das dúvidas". Duas exceções explícitas, registradas na própria
regra: (1) quando a MEDIÇÃO recomenda contra a mudança (ex. `tau_policy` <!-- check-sprint-log: skip -->
não foi flipado por causa de `AG-251` medir 2x de dispersão — isso é <!-- check-sprint-log: skip -->
"discorde do Manager quando o dado discordar", situação diferente); (2) <!-- check-sprint-log: skip -->
comparação lado-a-lado pedida explicitamente pelo próprio Manager.

**6 defaults flipados nesta rodada** (os do handoff de `src/models/`
anterior — todos já implementados/testados, só esperando o switch):
`side_subset`/`run_fold`/`run_all_folds::enforce_r2` (`AG-296`/`AG-297`)
`False→True`; `LGBMHyperparams.regularization_basis` (`AG-325`)
`FIXED→ESS_DERIVED` (documentado como INERTE sob `num_leaves` atual,
zero efeito real hoje); `LGBMHyperparams.early_stopping_mode` (`AG-326`)
`FIXED→THREE_WAY` — **ressalva registrada explicitamente**: este é
diferente em natureza dos outros 5, nunca foi exercitado contra dado <!-- check-sprint-log: skip -->
real (só RNG sintético), promover o default É a 1ª exposição real, não <!-- check-sprint-log: skip -->
aplicação de uma correção já validada por medição prévia;
`LGBMHyperparams.from_constants(use_ic_magnitude_floor=...)`
(`AG-324`) `False→True`; `run_layer1_sprint::use_economic_gate` <!-- check-sprint-log: skip -->
(`AG-260`) `False→True` (natureza soft-flag não muda, só o log deixa de <!-- check-sprint-log: skip -->
precisar de segunda ordem); `run_layer1_sprint::run_b1_refinement` <!-- check-sprint-log: skip -->
(`AG-360`) `False→True`. <!-- check-sprint-log: skip -->

**Escopo desta rodada, explícito**: só os 6 flags de HOJE. Flags <!-- check-sprint-log: skip -->
pré-existentes de sessões anteriores (`tau_policy`, `calib_split_mode`,
`class_balance_basis`, `use_hyperparams_by_combo`, `use_geometry_by_
combo`) NÃO foram tocados nesta rodada — não por hesitação, mas porque
não tenho contexto completo sobre cada um pra vouch pela correção (e
pelo menos `tau_policy` tem medição real recomendando NÃO flipar,
`AG-251`). Se o Manager quiser essa varredura também, é um pedido à <!-- check-sprint-log: skip -->
parte.

10 arquivos de teste ajustados pra refletir os novos defaults (fixtures
sintéticas sem colunas de R2 precisaram ganhar `entry_price_limit`/
`sl_price`/`cost_entry_bps`/`cost_exit_bps`/`funding_bps` pra não
quebrar quando `enforce_r2=True` passou a ser o caminho padrão; testes
que afirmavam "default reproduz o legado" viraram "default é o
corrigido", com um teste explícito novo pra quem quiser o legado via
`False`). Suíte completa (`-m "not slow"`) ao final: **2481 passed, 2
skipped, 2 xfailed, 0 failed** (mesmo total de antes — a mudança é de
DEFAULT, não de comportamento novo, os testes só passaram a exercitar o
caminho que antes era só o opt-in). 7 checks mecânicos limpos. `AG-260`/
`AG-296`/`AG-324`/`AG-325`/`AG-326`/`AG-360` ganharam addendum
registrando a promoção — nenhuma entrada fechada foi editada, só
addendum novo (append-only).

### 2026-08-27 — `vol_estimator_id` também corrigido, mesma política, achado pela varredura de produção <!-- check-sprint-log: skip -->

Pedido do Manager: listar os comandos PowerShell do retreino canônico e
varrer o repo por algo que tivesse passado despercebido. Achado real:
`config/constants.yaml::canonical_volatility_estimator` foi flipado pra <!-- check-sprint-log: skip -->
`parkinson_w20` no commit imediatamente anterior (`4f3b231`), mas
nenhum código lia essa constante por nome — confirmado por grep, zero
ocorrências antes desta correção. `run_layer1_sprint`/`run_layer1_
sprint_all_combinations` (o caminho real de produção) tinham `vol_
estimator_id: str | None = None` resolvendo, através de `build_modeling_
frame` até `features/build.py`, sempre pro ATRWilder legado — rodar
`--all-combinations` sem `--vol-estimator-id parkinson_w20` explícito
revertia a decisão do próprio commit que a declarou, em silêncio.
Mesmo padrão do handoff de ontem (`AG-272`), achado antes de qualquer
comando real ter rodado.

Aplicada a mesma política registrada na seção acima, no mesmo turno: <!-- check-sprint-log: skip -->
correção vira DEFAULT, não flag opt-in. `run_layer1_sprint` agora
resolve `vol_estimator_id_effective = vol_estimator_id ou load_
constant("canonical_volatility_estimator")` antes de chamar `build_
modeling_frame` — `None` deixa de significar "ATRWilder" e passa a
significar "o que `constants.yaml` decidiu" (hoje `parkinson_w20`).
`report["vol_estimator_id"]` grava o valor efetivo, não o parâmetro
cru. Núcleo (`features/build.py`, seleção `c01_atr_20`/`c01_atr_20_
parkinson`) INTOCADO de propósito — só a casca de produção mudou de
significado; os ~20 call sites de pesquisa/validação que chamam `build_
modeling_frame` direto continuam recebendo ATRWilder sob `None`, sem
mudança de comportamento. Legado continua acessível via `vol_estimator_
id="atr_wilder_w20"` explícito. <!-- check-sprint-log: skip -->

`tests/unit/test_models_pipeline_paths.py` — 1 assertion existente
atualizada pro novo default (`"parkinson_w20"`, valor real de `constants.
yaml`, não invenção do teste), 1 teste novo prova que o legado explícito
ainda vence sobre o default. `banned_patterns`/`ruff`/`mypy`/`check_
constants_referenced` rodados, limpos. `AG-361` registrado (severidade <!-- check-sprint-log: skip -->
alta — feature ATR-derivada é insumo de 4 features do vetor T1 ativo:
`A05`/`A13`/`C02`/`E27f`). Comando canônico de produção já sai correto
com `--vol-estimator-id parkinson_w20` explícito (redundante agora,
mas inofensivo — deixa o comando autoexplicativo mesmo que o default
mude de novo no futuro).

### 2026-08-27 — `AG-365`: retreino canônico crashou no 1º fold, causa raiz era um furo entre `AG-362` e `AG-300` <!-- check-sprint-log: skip -->

Comando de retreino (`--all-combinations --vol-estimator-id <!-- check-sprint-log: skip -->
parkinson_w20`) rodou de verdade e crashou no 1º fold (BTCUSDT/R1) com <!-- check-sprint-log: skip -->
`DeadFeatureColumnError` em `side_subset`: `E14f_toptrader_ls_ratio`/ <!-- check-sprint-log: skip -->
`E16f_global_ls_ratio` 100% nulas em 94232 linhas. Pedido explícito do
Manager: "não faça remediação barata, entregue solução robusta".

Causa raiz, não sintoma: `AG-362` (sessão paralela, MESMO DIA) promoveu <!-- check-sprint-log: skip -->
15 features L3→T1 (`T1_FEATURE_IDS` de 7 pra 22), incluindo 2 features
que dependem de `load_futures_positioning=True` em `build_t1_features`.
`build_modeling_frame` (`src/models/dataset.py`) decidia esse kwarg
olhando SÓ `extra_feature_ids` (parâmetro de análise pós-hoc) contra
`_FUTURES_POSITIONING_FEATURE_IDS` — nunca `T1_FEATURE_IDS`, o vetor de
treino real. Premissa segura quando essa checagem foi escrita
(`audit_engineering`, 24/08, T1 tinha 7 features, nenhuma dependente).
`AG-362` mudou a composição de T1 sem nenhuma checagem cruzada com esse <!-- check-sprint-log: skip -->
módulo — 91 testes verdes + lint limpo, mas nenhum deles exercita <!-- check-sprint-log: skip -->
`dataset.py`, então a mudança ficou isolada do módulo que a consome de
verdade em produção. Mesma classe de defeito que `AG-300` já tinha <!-- check-sprint-log: skip -->
fechado uma vez (conjunto checado divergente do que de fato treina) —
reaparece um nível acima, na decisão de qual dado CARREGAR.

Correção estrutural: `_needs_d07f`/`_needs_futures_positioning` agora
checam a UNIÃO de `T1_FEATURE_IDS` com `extra_feature_ids`, nunca só o
segundo — autocorrige se T1 mudar de composição de novo, sem exigir
sincronização manual entre `features/build.py` e `models/dataset.py`
outra vez. Custo de IO adicional: zero — as 2 features já exigiam esse
dado pra existir, a correção só faz o carregamento necessário
acontecer. `tests/unit/test_models_dataset.py`: 2 assertions
atualizadas pro valor correto, 1 case do parametrize trocado (`E14f` já
está em T1 incondicionalmente, não prova mais nada isolado — trocado
por `E18f_taker_ls_vol_ratio`, mantida fora de T1 por quarentena
`AG-266`), 1 teste novo monkeypatcha `T1_FEATURE_IDS` pra provar que a
resposta reage a T1 de verdade, não é coincidência da composição atual.
`banned_patterns`/`ruff`/`mypy` limpos. `AG-365` registrado. Retreino <!-- check-sprint-log: skip -->
ainda não confirmado ponta a ponta — próximo passo é o Manager rodar de
novo o mesmo comando.

### 2026-08-27/28 — `AG-362` addendum: comparação pareada 22 vs. 7 features, sob CPCV purgado <!-- check-sprint-log: skip -->

Pedido do Manager: medir o valor incremental real das 15 features <!-- check-sprint-log: skip -->
promovidas por `AG-362`, não só a hipótese. Desenho de 3 rodadas
decidido pelo Manager: (1) `T1_FEATURE_IDS` atual (22) +
`use_hyperparams_by_combo=False`; (2) 22 features + `True`; (3) vencedor
de hiperparâmetro entre 1/2 aplicado a `ORIGINAL_T1_FEATURE_IDS` (7,
pré-`AG-362`) — `src/analysis/ag362_incremental_value_report.py`, novo,
3 estágios independentes (`--stage off/on/base`), cada um persiste antes
do próximo. 45 fits reais (15 combinações × 3 rodadas).

3 bugs reais encontrados e corrigidos ao vivo durante a execução, cada
um registrado em `audit/architecture_gaps_log.yaml`: `AG-366`
(`feature_ids=None` não entra no `config_hash`, colidia com artefato
pré-`AG-362`), `AG-367` (`delta_sharpe_mean` `NaN` propagava e sumia no
agregado via serialização `orjson`→`null`), `AG-368` (`scratch=True`
threaded até `write_artifact`, resolve colisão de hash entre os 2
designs de hiperparâmetro numa célula sem calibração própria).

Resultado (`experiments/ag362_incremental_value_report.json`, também
`audit/evidence_ledger.yaml::ag362_incremental_value_22_vs_7_features_
2026-08-27`): **zero das 15 combinações passa `permanence_pass` nas 3
rodadas** — não é defeito específico do vetor de 22, aparece nas 3.
Sinal MISTO entre 22 features e a base de 7 features nas métricas mais
finas: por soma de `delta_sharpe_mean`, 22+hiperparâmetro-por-combo
lidera (23,84 contra 16,86 da base), mas dominado por 2 células isoladas
(`BTCUSDT_R3`/`SOLUSDT_R1`, ~9,6 cada, 80% da soma). Por caminhos
vencidos (menos sensível a outlier) e por gate econômico pós-trial
(ADR-005 §13.13 já mostrou que gain/AUC bruto não distingue sinal de
ruído), a BASE de 7 features lidera nas duas: 33/75 caminhos contra
22/75 do 22+on; 17/25 lados no gate econômico (68%) contra 10/27 (37%).
Vencedor da comparação de hiperparâmetro 1v2 (usado no desenho 3):
`on`, por definição operacional pré-registrada (maior `n_permanence_
pass`; empate 0=0 desempatado por soma de `delta_sharpe_mean`). <!-- check-sprint-log: skip -->

Não decide se as 15 promovidas "ajudam" no sentido que `AG-362` propôs <!-- check-sprint-log: skip -->
(captura de interação via splits) — mede resultado agregado, não
importância por permutação (Estágio 2 da proposta do `AG-330`, pendente <!-- check-sprint-log: skip -->
de booster `.bin` persistido). Artefato visual publicado pro Manager
revisar os 45 resultados lado a lado. `N_lifetime`: quantos trials estas <!-- check-sprint-log: skip -->
3 rodadas valem (1, 3 ou 45) é leitura em aberto, decisão do Manager — <!-- check-sprint-log: skip -->
não logado automaticamente (`run_layer1_sprint_all_combinations` <!-- check-sprint-log: skip -->
documenta a mesma leitura em aberto desde `D-14`).

### 2026-08-28 — Retreino canônico real: 22 features + `use_hyperparams_by_combo=True`, 15/15 escritos em `artifacts/predictions_alpha/` <!-- check-sprint-log: skip -->

Pedido do Manager: rodar o retreino canônico de produção com o desenho
vencedor da comparação 1v2 (`on`). CLI `--all-combinations` ganhou
`--use-hyperparams-by-combo` e passou a sempre injetar `feature_ids=
T1_FEATURE_IDS` explícito (fecha `AG-366` no caminho de produção,
`src/models/pipeline.py`, commit `3c43350`).

3 combinações (`BTCUSDT/R1,R2,R3`) já tinham artefato canônico completo
de uma tentativa anterior desta mesma sessão que crashou em `ETHUSDT/R1`
(`AG-368`, antes de `scratch` existir) — reaproveitadas, não retreinadas
de novo. Célula sem calibração própria em `config/alpha_hyperparams_by_
combo.yaml` (5 das 15: `SOLUSDT_R2/R3`, `ETHUSDT_R1`, `XRPUSDT_R2/R3`)
resolve pro MESMO hiperparâmetro global que `off` já tinha escrito
canonicamente — `write_artifact` recusou reescrever (comportamento
correto, imutabilidade). As 7 combinações restantes (`BNBUSDT` completo,
`ETHUSDT_R2/R3`, `SOLUSDT_R1`, `XRPUSDT_R1`) treinadas de fato agora.
15/15 relatórios completos persistidos em `experiments/alpha_layer1_
report_{symbol}_{resolution}.json` (5 deles + os 3 de `BTCUSDT`
recompostos via `scratch=True` só pra recapturar o JSON de métricas — a
predição canônica já existia e não foi reescrita).

Resultado agregado (idêntico ao já medido em `22_features_hyperparam_ <!-- check-sprint-log: skip -->
on` da comparação pareada, cross-validado): **0/15 permanence_pass**, <!-- check-sprint-log: skip -->
22/75 caminhos vencidos, 10/27 lados no gate econômico. Achado NOVO <!-- check-sprint-log: skip -->
desta rodada (métricas completas nunca extraídas antes): `N_eff`
efetivo mediano = 2,86 de 22 features — 7/15 combinações concentram o
gain em menos de 2,5 fatores efetivos, mesmo com o vetor de 22
disponível. 5/15 combinações têm Sharpe da Camada 0 indefinido
(`BNBUSDT_R1/R2`, `BTCUSDT_R1`, `ETHUSDT_R1`, `XRPUSDT_R1`) — nessas o
gate de permanência não é interpretável, e coincidem com AUC real vs.
embaralhado (B4) alta (features discriminam) mas percentil B1 baixo
(pior que ruído aleatório em Sharpe) — separação de classe não convertendo
em lucro, possível problema de calibração de `tau`, não de sinal.

Artefato visual publicado com as 15 combinações e todas as métricas <!-- check-sprint-log: skip -->
(permanência, gate econômico, B1/B4, HHI/N_eff, decomposição de PnL). <!-- check-sprint-log: skip -->
`N_lifetime` deste retreino: mesma leitura em aberto da rodada anterior,
não logada automaticamente.

### 2026-08-28 — `AG-372`/ADR-006: 7 features novas (momentum/reversão/impacto) construídas em torno do H real medido <!-- check-sprint-log: skip -->

Usuário auditou o veredito do retreino contra `fichas_69_2026-08-25.yaml` <!-- check-sprint-log: skip -->
(A07-A11 candlestick, B02-B11 momentum/reversão) e mostrou que boa parte
das rejeições vinha de parâmetro herdado de indicador de barra de relógio,
nunca recalibrado pro motor real — não falta de mecanismo. Medi `H` de
verdade: `n_bars_held` (labels.parquet, população completa exceto NOFILL)
tem mediana=1, p75=3, estável entre BTCUSDT/SOLUSDT × R1/R2/R3. <!-- check-sprint-log: skip -->

Desenvolvido com `/feature-dev:feature-dev` (Fases 1-5), autorização <!-- check-sprint-log: skip -->
explícita do Manager pra "focar no plano ponta a ponta": 7 features, direto
a T1 (não L3 primeiro) — `A11_true_range_pct` (reativada, estava `layer:
L4`, já reprovada uma vez sob o gate marginal antigo, tese NOVA de impacto
de preço, override deliberado não coberto pela anistia de `AG-362`),
`A16_return_3`, `A17_true_range_per_overshoot`, `B12_close_location_h3` <!-- check-sprint-log: skip -->
(consolida A10/B09/B10/B11), `B13_extension_h3`, `B14_rejection_after_ <!-- check-sprint-log: skip -->
extension` (feature de exaustão, conceito novo), `B15_efficiency_ratio_h3`. <!-- check-sprint-log: skip -->
`T1_FEATURE_IDS` 22→29. Detalhe completo: `docs/ADR-006_momentum_reversao_ <!-- check-sprint-log: skip -->
impacto_dollar_bar_2026-08-28.md`. <!-- check-sprint-log: skip -->

`quote_volume`/`threshold_quote` (colunas de dollar bar já persistidas, <!-- check-sprint-log: skip -->
nunca extraídas pelo Feature Engine até agora) alimentam A17 — achado no
caminho: `quote_volume` cru é quase degenerado sob dollar bar (`AG-321`,
~igual ao threshold), a quantidade que varia de verdade é o overshoot
(`quote_volume - threshold_quote`).

12 testes de causalidade/faixa novos (`tests/unit/test_features_groups. <!-- check-sprint-log: skip -->
py`). `banned_patterns`/`ruff`/`mypy` limpos nos arquivos tocados.
`registry.yaml` (76 entradas) validado por `yaml.safe_load`. NÃO validado
por execução real (protocolo): `test_layer2_feature_ids_bate_com_t1_
feature_ids` e a suíte de paridade lote↔streaming, que agora cobre as 7
novas automaticamente. Comando de validação entregue ao Manager, não
rodado por Claude.

Nota de processo permanente adicionada ao cabeçalho de `src/features/ <!-- check-sprint-log: skip -->
registry.yaml`: sequência de gate (algébrica → mecanismo → horizonte →
redundância → walk-forward/incremental → LightGBM → SHAP) — SHAP/gain só
como confirmação pós-hoc, nunca descoberta primária, mesma disciplina que
`AG-371` já mostrou ser necessária (importância pode estar contaminada por <!-- check-sprint-log: skip -->
hiperparâmetro desincronizado do vetor).

Nenhuma medição de valor incremental real ainda — mesma ressalva que <!-- check-sprint-log: skip -->
`AG-362` já registrou pras 15 anteriores. Retreino sob o vetor de 29 é
decisão separada, ainda não tomada.

### 2026-08-28 — Lote D2: 7 candle features novas por raciocínio próprio + spec do usuário validado, `T1_FEATURE_IDS` 29→36 <!-- check-sprint-log: skip -->

Usuário perguntou por que nenhuma candle feature tinha sido desenvolvida <!-- check-sprint-log: skip -->
por raciocínio próprio (não só reconsolidação das antigas), depois trouxe
uma especificação técnica externa (~20 famílias, Pandas/numpy, pipeline de <!-- check-sprint-log: skip -->
8 gates), com autorização condicional: "você pode criar mais se validado". <!-- check-sprint-log: skip -->

Validação ANTES de implementar rejeitou boa parte do spec: Pandas inteiro <!-- check-sprint-log: skip -->
(viola B26); `candle_open_gap` já é `A12_gap_pct`, removida por `AG-316`
(gap de sessão não existe em cripto 24/7); família wick/position re-deriva <!-- check-sprint-log: skip -->
a identidade algébrica de A07-A10 e ainda escondia uma redundância NOVA que <!-- check-sprint-log: skip -->
o spec do usuário não tinha percebido (`open_location = close_location −
A07`); família Z-score (N∈{5,10,20,50}) repete o erro de janela nunca <!-- check-sprint-log: skip -->
calibrada contra H. Sobraram 6 candidatos genuinamente novos do spec + 1 <!-- check-sprint-log: skip -->
(engolfo) de raciocínio próprio anterior ao spec = 7 implementadas:
`A18_body_log`, `A19_log_range`, `A20_log_duration`, `A21_log_dollar_
velocity`, `B16_log_range_ratio_1`, `B17_directional_pressure_h3`, `B18_
engulfing_atr`. `T1_FEATURE_IDS` 29→36. Detalhe completo: addendum Lote D2
em `docs/ADR-006_momentum_reversao_impacto_dollar_bar_2026-08-28.md` e
`AG-372::addendum_lote_d2`.

Achado no caminho: `A20_log_duration` é CONSTANTE (não `NaN`) sob <!-- check-sprint-log: skip -->
`bar_source=time_15m` (duração fixa ~15min por definição), quebrando
`test_t1_ortogonalidade_spearman_2anos` (stddev=0 zera a matriz de <!-- check-sprint-log: skip -->
correlação) — corrigido excluindo a coluna do teste de correlação, não do
vetor real (que roda sob dollar bar).

9 testes de causalidade/edge-case novos. Diferente do Lote D anterior, <!-- check-sprint-log: skip -->
desta vez VALIDADO por execução real (autorização ampla do Manager nesta
sessão): suíte alvo de features 196 passed; suíte completa 2524 passed, 2
skipped, 3 failed. As 3 falhas são pré-existentes/não relacionadas —
`tests/unit/test_analysis_tau_diagnostics.py` quebra com `trades_per_year
=None` num `experiments/alpha_layer1_report.json` real modificado pelo
retreino que o usuário rodou mais cedo nesta sessão; módulo `src/analysis/
tau_diagnostics.py` não foi tocado por este lote. Achado separado, ainda
não investigado — sinalizar ao Manager. `T1_FEATURE_IDS` (36) confirmado
idêntico a `layer2_feature_ids()` via `uv run python` real. `banned_
patterns`/`check_unguarded_ratios`/`ruff`/`mypy` limpos nos arquivos
tocados (1 `noqa` obsoleto removido em `tools/lint/check_unguarded_ratios.
py`, achado cosmético do ruff sem relação com este lote).

Mesma ressalva de sempre: abre elegibilidade, não prova o ganho. Retreino <!-- check-sprint-log: skip -->
sob o vetor de 36 é decisão separada, ainda não tomada.

**Nota de staleness explícita (2026-08-28, protocolo "atualizar <!-- check-sprint-log: skip -->
governança"):** a tabela "Estado atual (2026-08-25)" (acima, `§linha
4584`) e a nota de staleness anterior (`§linha 4640`, dated 2026-08-26,
que já apontava pra `ADR-005` como canônico) estão AINDA MAIS
desatualizadas agora — nem citam `AG-362` (reversão do critério de
promoção T2→T1, 2026-08-27), nem o retreino canônico real sob 22
features, nem `AG-371` (zero-sinal em 5 células), nem `ADR-006`/`AG-372`
(Lote D/D2, `T1_FEATURE_IDS` 22→36, ainda não commitado no momento desta
nota). Quem quiser o estado real usa `git log --oneline` +
`docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md` (Feature
Engine até 2026-08-26) + `docs/ADR-006_momentum_reversao_impacto_dollar_
bar_2026-08-28.md` (Feature Engine 2026-08-28 em diante) +
`audit/architecture_gaps_log.yaml` (append-only, sempre a fonte mais
recente por construção) — nunca a tabela "Estado atual" isolada.

### 2026-08-28 (continuação) — Validação ML das 14 features + achado crítico de contaminação cross-sessão + `AG-373` corrigido <!-- check-sprint-log: skip -->

Manager pediu agente sob persona de ML Feature Engineer pra validar <!-- check-sprint-log: skip -->
ponta a ponta a matemática financeira das 14 features do Lote D/D2, mais
"atualize governança". Dois agentes em paralelo.

**Validação das 14 features**: 11/14 PASS sem ressalva. 2 gaps de teste <!-- check-sprint-log: skip -->
baratos corrigidos (`test_b12_guarda_range_flat_produz_ponto_medio`,
`test_compute_t1_features_b14_usa_a16_deslocado_um_bar`). 1 achado real <!-- check-sprint-log: skip -->
— `A17_true_range_per_overshoot` não era adimensional (`TR` em unidade <!-- check-sprint-log: skip -->
de preço, `overshoot` em notional) — logado como `AG-373`. <!-- check-sprint-log: skip -->

**Achado crítico, independente da validação de features**: reconciliação <!-- check-sprint-log: skip -->
de governança contra 96 commits descobriu uma SESSÃO PARALELA autorizada
rodando no mesmo working tree, investigando `AG-371` (zero-sinal em 5 <!-- check-sprint-log: skip -->
células) — e ela já tinha documentado (`AG-371-ADDENDUM-10`, severidade <!-- check-sprint-log: skip -->
CRÍTICA) que o Lote D/D2 desta sessão contaminou a validação da correção <!-- check-sprint-log: skip -->
de `E27f` dela: o teste comparou baseline sob 22 features contra <!-- check-sprint-log: skip -->
"corrigido" sob 36 (Lote D2 já tinha aterrissado no working tree
compartilhado quando aquele retreino rodou). Confirmado por leitura
direta da entrada. Nenhuma ação destrutiva tomada por nenhum dos dois
lados; 3 decisões seguem explicitamente do Manager (qual `T1_FEATURE_
IDS` é autoritativo — 22/29/36; remedir `E27f` sob 22 limpo; como as 2
sessões devem coordenar). `PLANO_MESTRE_PRINCE2.md` ganhou `§15.29`
sincronizando tudo isso, sem tomar nenhuma das 3 decisões.

**`AG-373` corrigido no mesmo dia** (não deixado como achado aberto — <!-- check-sprint-log: skip -->
defeito de FÓRMULA, dimensional analysis não precisa de medição pra
decidir): `A17_true_range_per_overshoot` → `A17_log_tr_per_overshoot_
ratio` — `ln1p((TR_t/C_{t-1})/(overshoot_t/threshold_quote_t))`, razão
de 2 quantidades adimensionais (a primeira é literalmente `A11`), `ln1p`
no mesmo estilo de A18-A21/B16 do lote. Verificado por
`test_a17_invariante_a_nivel_de_preco` (escala preço por 37×, saída não
muda — teria falhado sob a fórmula antiga). Achado secundário no
caminho: `build.py` não definia `threshold_quote` no branch
`bar_source=time_15m`, corrigido. Suíte alvo de features: 199 passed. <!-- check-sprint-log: skip -->
`registry.yaml` (`version: v2`), `ADR-006` (addendum), `AG-373` (status) <!-- check-sprint-log: skip -->
atualizados. Nada disso resolve a pergunta maior de qual `T1_FEATURE_IDS` <!-- check-sprint-log: skip -->
é autoritativo — só corrige a matemática de uma feature que só existe
nas versões 29/36. <!-- check-sprint-log: skip -->

### 2026-08-28 (continuação) — `AG-077` FECHADO: "pronto" redefinido de DSR/`N_lifetime` para lucro em Live Demo <!-- check-sprint-log: skip -->

Manager, decisão direta: "pode fechar AG077, o que define 'pronto' é <!-- check-sprint-log: skip -->
entregar lucro Live Demo." Resposta à pergunta que `AG-077` (2026-08-17)
tinha deixado registrada em aberto desde a descontinuação de `N_lifetime`
como orçamento vinculante: "o que substitui a penalidade de multiple-
testing no Gate 6/DSR". Resposta: nada substitui por outra fórmula <!-- check-sprint-log: skip -->
estatística — o próprio Gate 6 (`PRD_V4_1.md::V41-12`, "DSR final com <!-- check-sprint-log: skip -->
`N_lifetime`=60") deixa de ser a definição de sucesso do projeto, <!-- check-sprint-log: skip -->
substituído por resultado empírico real (lucro em Live Demo).

Escopo da mudança, registrado explicitamente pra não confundir: só o <!-- check-sprint-log: skip -->
Gate 6 POSITIVO (quando declarar sucesso). Os critérios de encerramento
#5/#6 (`PRD_V4_1.md` §6.5 — guardrail contra busca infinita sem edge,
pergunta de quando ABANDONAR, diferente de "quando declarar pronto") e
os Gates 0-5 (promoção de artefato/constante individual) não foram
tocados. `src/validation/dsr.py`/`_audited_n_lifetime()` (código real que
ainda lê `N_lifetime`) também não foi alterado — decisão de
implementação (remover, marcar non-binding, ou manter como diagnóstico
auxiliar) separada, ainda não tomada.

Fechar `AG-077` abriu um gap novo, registrado à parte (`AG-374`, mesma <!-- check-sprint-log: skip -->
disciplina de `AG-114`/`AG-118`/`AG-122` já citada no `CLAUDE.md`): "lucro
em Live Demo" ainda não tem definição operacional — o que conta como
"lucro" (PnL positivo uma vez, ou distinguível de ruído sobre amostra
mínima?), o que é exatamente "Live Demo" (testnet/paper/capital real
reduzido?), sobre qual capital e por quanto tempo. Sem consequência
imediata (projeto longe de ter candidato real a Live Demo hoje, `AG-371`)
— mas decidir isso antes de existir um candidato na mesa evita o mesmo
viés que B20 já existe pra prevenir noutro contexto. `PLANO_MESTRE_
PRINCE2.md` (`§11.4`/`§11.6`, changelog v3.56) e `PRD_V4_1.md` (§6.1/§6.5/
V41-12, pointers de 1 linha, sem reescrita) atualizados.

**Continuação, mesmo dia — `AG-374` 2/3 termos definidos.** 3 perguntas <!-- check-sprint-log: skip -->
diretas ao Manager (`AskUserQuestion`), as 3 recomendadas aceitas.
"Lucro" = PnL positivo E distinguível de ruído (mesmo framework de
`economic_gate.py::is_distinguishable`/`AG-246`, não "PnL>0 uma vez" —
rejeitado por vulnerável a variância de amostra pequena). "Live Demo" =
capital real reduzido, dentro de `capital_inicial_brl` (R$ 1.000, `§0`)
— não testnet, não paper (só capital real prova liquidez/slippage/fill
real, e esta sessão já mediu que isso importa — fill 42,2% vs. 97,1%
otimista). Capital/janela PARCIAL: R$ 1.000, mínimo 1 mês — **N mínimo
de trades continua TBD**, não inventado (B23): candidato de precedência
(`evidence_ledger.yaml::n>=200`) foi calibrado pra amostra de backtest,
não pro ritmo real de sinal de Live Demo (`AG-371` já mostrou células
que ficam dias sem sinal), aplicar sem checar factibilidade repetiria o
erro que o próprio `AG-374` existe pra evitar. `AG-374` status:
PARCIALMENTE FECHADO. `PLANO_MESTRE_PRINCE2.md` §11.4/§11.6 atualizados
com a definição operacional; `audit/architecture_gaps_log.yaml::AG-374`
ganhou campo `resolution`.

### 2026-08-29 — `AG-371` fechado por Optuna real (não recalibração); GPU real via WSL2+CUDA; `AG-375`-`AG-378` <!-- check-sprint-log: skip -->

Manager decidiu aposentar `config/alpha_hyperparams_by_combo.yaml` — o <!-- check-sprint-log: skip -->
YAML estático que já tinha ficado *stale* de verdade uma vez (a própria
origem de `AG-371`) — e a campanha manual de grade/coordinate-descent que
o alimentava, substituindo por Optuna real (`optuna>=4.0`, dependência
declarada desde sempre, nunca importada em `src/` até agora). Escopo
estrito `src/models/` (produção; `src/validation/` é medição, intocado
por pedido explícito). Commit `40b8255`.

`src/models/hyperparams_optuna.py` (novo): TPESampler sobre 12 campos de <!-- check-sprint-log: skip -->
`LGBMHyperparams` (8 já tinham `sweep_range`; `learning_rate`/
`n_estimators`/`subsample`/`lambda_l2` ganharam agora, por decisão do
Manager). Duas perguntas de desenho tiradas deliberadamente do histórico
do próprio `AG-371` (Manager pediu explicitamente pra não usar como
âncora) e resolvidas por pesquisa de metodologia atual: Camada1 e Camada0
recebem *studies* Optuna independentes, não uma herdando da outra
(comparação de ablação exige HPO nos dois lados — Probst et al.,
*Tunability*, JMLR 20(53)); resultado vencedor por
`(symbol, resolution_id, variant)` gravado como artefato content-
addressed via `src.io.artifact` em vez de outro YAML estático — fecha a
classe de bug inteira por CONSTRUÇÃO, hash muda sozinho se `feature_ids`/
`search_space`/`variant` mudarem. `src/models/hyperparams_by_combo.py`
reescrito (sem tupla, sem `HyperparamFeatureMismatchError`/
`allow_feature_mismatch` — deixam de ser estado alcançável em runtime).
`src/models/pipeline.py::run_layer1_sprint` ganha `hyper_camada1`/
`hyper_camada0`. `config/alpha_hyperparams_by_combo.yaml` removido
(`git rm`, histórico preservado). Itens (b)/(c) do status PARCIAL
anterior de `AG-371` (teste diferencial + recalibração sob 22 features)
ficam OBSOLETOS — a pergunta que faziam deixou de existir junto com o
arquivo. `AG-371-ADDENDUM-18` registra o fechamento;
`audit/architecture_gaps_log.yaml::AG-375`-`AG-378` recebem também
`resolved_by_commit` real nesta rodada de governança (estavam `null`
apesar de `status: fechado` — corrigido).

Testes reais (autorização explícita do Manager pra `uv run`/`pytest` <!-- check-sprint-log: skip -->
nesta sessão, com limite explícito: não rodar a campanha completa sob
CPU): suíte alvo verde, 2 bugs próprios achados e corrigidos pelos
próprios testes antes do commit — `max_depth` erroneamente incluído nos
campos buscáveis (contradiz o desenho — redundante com `num_leaves` sob
crescimento leaf-wise, já documentado); `SchemaValidationError` em
`write_search_artifact` por inferência de dtype `Null` do Polars sobre
DataFrame de 1 linha com `None` (corrigido com `schema=` explícito). <!-- check-sprint-log: skip -->

**Avance para WSL2+CUDA** — infraestrutura real de GPU (RTX 4060 Ti), <!-- check-sprint-log: skip -->
não só planejamento. `tools/infra/wsl2_cuda_setup.sh` (novo, idempotente,
7 passos) provisiona CUDA Toolkit 12.6 + NCCL 2.24.3 + LightGBM 4.7.0
recompilado com `USE_CUDA=ON`. `AG-201` ("GPU/CUDA inviável no Windows
nativo") deixa de ser bloqueio — a correção não foi rodar no Windows, foi
migrar o treino GPU pro WSL2 na mesma máquina. Confirmado com treino CUDA
real: dado sintético (accuracy=0,9974) e depois dado real do projeto <!-- check-sprint-log: skip -->
(Camada0 e Camada1, 1 fold cada, `device_type=cuda`, ambos OK). <!-- check-sprint-log: skip -->

3 bugs de infraestrutura investigados até causa raiz (pedido direto do <!-- check-sprint-log: skip -->
Manager: "estude e investigue a raiz... correção robusta sem remediação
barata", depois "pode implementar") — `audit/architecture_gaps_log.yaml
::AG-375`/`AG-376`/`AG-377`, commit `b6d16c4`:

- **NCCL/CUDA-toolkit desencontrados** (`AG-375`) — `apt-get install <!-- check-sprint-log: skip -->
  libnccl2` sem versão resolvia pra `2.31.2-1+cuda13.3` (build mais
  recente do repo apt da NVIDIA) mesmo com toolkit 12.6 instalado; link
  final do LightGBM falhava com `nvlink error: Uncompress failed`,
  mensagem opaca. Causa raiz via `apt-cache show`/`madison`: NCCL e
  CUDA-toolkit têm ZERO dependência apt cruzada — o apt nunca garante o
  pareamento de versão, é responsabilidade inteira do operador. Corrigido
  fixando o par exato (`libnccl2=2.24.3-1+cuda12.6`) +
  `apt-mark hold` (protege contra `apt upgrade` futuro puxar de volta a
  versão desencontrada).
- **`uv run` revertia o build CUDA pro wheel CPU** (`AG-376`) — <!-- check-sprint-log: skip -->
  comportamento OFICIAL e documentado do uv (sincronização implícita
  contra o lockfile antes de qualquer comando), não bug. `tool.uv.sources`
  +`extra` (a rota "correta" documentada pelo uv) avaliado e REJEITADO —
  issues abertas do próprio projeto uv (`astral-sh/uv#17732`/`#17967`)
  arriscariam quebrar o caminho CPU/Windows de produção real deste
  projeto pra resolver um problema só do ambiente GPU/WSL2 opcional.
  Corrigido isolando o venv CUDA inteiramente fora do lockfile
  (`UV_PROJECT_ENVIRONMENT` separado, `~/.venvs/binance-futures-cuda`,
  nunca `uv run`/`uv sync` nesse contexto).
- **`.venv/` compartilhado Windows/WSL2 corrompido** (`AG-377`) — mesmo <!-- check-sprint-log: skip -->
  caminho físico NTFS, layouts de venv incompatíveis entre SOs (`uv sync`
  do WSL2 criou `.venv/lib64` symlink POSIX; `uv` do Windows não
  conseguia mais remover, `Acesso negado`). Corrigido pela mesma
  separação de `AG-376` — ambiente Windows recriado do zero e confirmado
  saudável antes de prosseguir.

**Crash real bisecado à causa exata** (`AG-378`, commit `f15ca8e`) — <!-- check-sprint-log: skip -->
`[CUDA] an illegal memory access`, processo inteiro morre, sem exceção
Python capturável. Bisecado campo a campo dos 12 hiperparâmetros
buscados: só `max_bin` reproduz; por valor exato, `max_bin=256` treina
limpo, `257` crasha — limite EXATO de um índice de bin de 8 bits.
Confirmado como bug upstream conhecido e ainda sem patch
(`microsoft/LightGBM#6512`) — a reprodução deste projeto é mais precisa
que a da issue original (dataset pequeno, ~40k barras, vs. "dataset
grande" citado lá). ~57% do `sweep_range` atual de `max_bin` (256-511)
está na zona insegura sob CUDA. Corrigido com `CudaMaxBinUnsupportedError`
nova em `fit_side_model` (antes de `LGBMClassifier.fit()` rodar) +
`catch=` no `study.optimize` — crash de processo vira trial falhado
tratável (mesmo mecanismo que já existe pra NaN), não derruba a campanha
inteira. `sweep_range` NÃO capado por device (manteria `config_hash`
portável entre devices, decisão deliberada — documentada no docstring de
`compute_search_config_hash`). Achado colateral, só exposto depois deste
fix (antes o processo crashava antes de qualquer trial completar): "todos
os trials falharam" virou estado alcançável (15/15 numa rodada real de <!-- check-sprint-log: skip -->
smoke test, seed=7, ETHUSDT/R3) — sem guarda, `study.best_trial` levantava <!-- check-sprint-log: skip -->
`ValueError: Record does not exist` opaco do SQLAlchemy; guarda nova
levanta `ValueError` explícito com contagem sucesso/falha + caminho do
storage sqlite.

**Pendente**: campanha Optuna real (~8h CPU pior caso, medido em <!-- check-sprint-log: skip -->
`AG-371-ADDENDUM-17`) e benchmark CPU-vs-GPU real seguem NÃO EXECUTADOS —
o usuário decide quando disparar. `ModelBundleManifest` continua sem
campo `device_type` (`AG-196`, gap pré-existente, não tocado). `src/
analysis/ag362_incremental_value_report.py` muda de comportamento
(`use_hyperparams_by_combo=True` sem `allow_feature_mismatch` passa de
"falha alto se stale" pra "cai no global com warning") — avisado, fora do
escopo `src/models/` desta rodada.

**Governança**: `PLANO_MESTRE_PRINCE2.md` Changelog `v3.57`, correção <!-- check-sprint-log: skip -->
inline em §15.20 (alínea D, `AG-201`) e §15.29 (`AG-371`, marca
`[SUPERADO]`); Road Map Vivo v2 republicado com seção dedicada "Alpha —
Optuna real substitui campanha manual + GPU via WSL2" — gap de
reconciliação 2026-08-26/27/28 (`AG-362`-`AG-370`, retreino canônico sob
`T1_FEATURE_IDS` reestruturado 7→22) declarado explicitamente no
artefato, não reconstruído nesta rodada (fora do escopo pedido — "atualize
governança" sobre o trabalho desta sessão, não um sweep histórico
represado de 3 dias). <!-- check-sprint-log: skip -->

**Nota de staleness, mesma disciplina de sempre**: a tabela "Estado <!-- check-sprint-log: skip -->
atual (2026-08-25)" (`§linha 4584`) segue não-reconciliada — nem cita
`AG-362` a `AG-378`. Quem quiser o estado real usa `git log --oneline` +
`audit/architecture_gaps_log.yaml` (append-only, sempre a fonte mais
recente por construção) + `PLANO_MESTRE_PRINCE2.md` Changelog `v3.57`,
não esta tabela.
