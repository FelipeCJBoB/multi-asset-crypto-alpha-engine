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
