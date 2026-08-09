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
anterior, `b281a18954e224ef`, 462.682 linhas, nada mais mudou). **Achado
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
| Trocar o gate de confiança por um filtro de C07 (vol) melhora o resultado? | Não — `directional_sharpe` do filtro por vol fica no percentil 21 do controle aleatório (pior que a maioria dos sorteios); produção atual (+0,879) continua melhor que as duas alternativas nos dois eixos | Faixa 2, "Teste do C07 como acelerador" acima |
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
