# Sweep de divergências — Road Map Vivo × PRD_V3_2 × PRD_V4_1 × código real

> Gerado 2026-08-17, a pedido do Manager: *"faça uma varredura pois vc
> compactou no meio da tarefa. Leia novamente o novo roadmap vivo e alinhe
> com o prd 3.2 e o prd 4.1 para garantir que nao perdemos nada"* + *"nao
> esqueça da ML Layer... Live Trading Layer"* + *"onde houver divergência,
> valide no código"*.
>
> Método: 2 Agents independentes leram `PRD_V3_2_UNIFICADO.md` e
> `PRD_V4_1.md` na íntegra e cruzaram contra o texto atual de `§11.4-§11.6`
> do Road Map Vivo. Toda divergência relatada foi reverificada nesta
> sessão direto no código (`grep`/`Read`), não só na prosa dos PRDs. Um
> `project_assurance` (Agent independente) revisou especificamente o item
> de maior exposição financeira (GK vs. Parkinson).

## 1. Achados validados por código — "nossa realidade hoje"

### 1.1 GK vs. Parkinson — decidido, **não** deployado (exposição financeira real)

| fonte | afirma |
|---|---|
| `config/constants.yaml:201` (código, produção real) | `canonical_volatility_estimator.value = "garman_klass_w20"` — **é o que roda hoje** |
| `PRD_V4_1.md` §3.2 linha 374/376 (blueprint, nunca atualizado) | "Garman-Klass é o vencedor de M1" — medição original sob grade de TEMPO, decisão do Manager 2026-08-11 |
| `PLANO_MESTRE_PRINCE2.md` §11.5/§11.6 (roadmap, esta sessão) | "Manager decidiu Parkinson canônico" — medição SEPARADA sob grade DOLLAR-BAR (2026-08-17), 12/15 |

**Não é contradição — são duas medições sob grades diferentes, ambas verdadeiras.** O problema é de comunicação: §11.5/§11.6 emparelham "✅" com "Parkinson canônico" sem repetir que o deploy real não aconteceu — quem lê isolado (o modo real de uso do roadmap: decidir prioridade sem reler código) pode concluir que produção já mudou. `§11.4` já tem o caveat correto ("não executado por decisão do Manager"); `§11.5`/`§11.6` não repetem.

**Achado agravante do `project_assurance`:** este é um padrão RECORRENTE — o mesmo tipo de ambiguidade em torno da palavra "canônico" já foi registrado uma vez antes, pra GK (`AG-003`, citado em `PLANO_MESTRE_PRINCE2.md` linhas 396-400), e se repetiu agora pra Parkinson sem a lição ter sido aplicada de forma uniforme entre as 3 abas.

**Redação validada, já aplicada ao roadmap** (ver commit desta sessão):
- `§11.5`/`§11.6`: nota "**DECIDIDO, NÃO DEPLOYADO**" com o valor literal de `constants.yaml` citado.
- `PRD_V4_1.md` §3.2: ponteiro de 1 linha após a frase original, apontando pra remedição sob dollar-bar — blueprint fica correto sem virar documento de estado.

**Verificação adicional (`project_assurance`):** nenhum outro lugar do repo (código/teste/docstring) trata Parkinson como já deployado. `group_c.py`/`features/build.py`/`registry.yaml` tratam Parkinson corretamente como opt-in via `vol_estimator_id`, default segue ATRWilder/GK. `docs/refactor_parkinson_canonico.md` linhas 315-321 já é explícito ("continuam NÃO executados").

### 1.2 Kill switch — 13 é o número correto hoje, não 15

`src/risk/kill_switch.py:273` implementa exatamente `KILL_SWITCH_TRIGGER_IDS = (K01..K13)` — 13 gatilhos, batendo com roadmap/DoD.

O "15" de `AG-076` vinha de somar §10.2 (13) + §16.3 gatilho 14 (`listenKey` inválido, genuinamente novo, **não implementado**) + §16.7 gatilho 15. Mas gatilho 15, lido no próprio texto do PRD (linha 2746), **é o mesmo K06** ("ordem inesperada... já existia como gatilho 6, agora com procedimento de resposta explícito") — não é um gatilho novo, é o mesmo redescrito. Contagem real de conceitos únicos: **13 implementados + 1 genuinely novo não implementado (gatilho 14) = 14**, nunca 15.

De quebra: dos 13 implementados, só K01/K02/K03/K12/K13 são computáveis hoje (fórmula sobre estado injetado); K04-K11 (8 de 13) são "sensor pronto, sem fonte de dado real" — aguardam Sprint 12+/live.

**Ação:** `AG-076` corrigido (addendum) com esta contagem validada.

### 1.3 Stress scenarios (18 vs. 19) — divergência 100% textual, zero impacto hoje

`src/backtest/` só tem `_paths.py` e `fill_reconciliation.py`. O Stress Engine (Sprint 11, `quant.stress.run`, os 18/19 cenários) **não existe em nenhuma linha de código**. `src/regime/stress.py` é outra coisa — gatilhos de regime R5=STRESS (§4.4), não o Stress Engine de backtest.

Contagem real na prosa do V3.2: linha 2478 (Sprint 11) diz "19"; linha 2557 (DoD item 32) e linha 2506 (CLI) dizem "18", concordando entre si — só a linha do roadmap Sprint 11 é o outlier. Mas como nada disso está implementado, a divergência não afeta nenhuma decisão de hoje — só precisa ser corrigida no V3.2 quando o Sprint 11 for de fato atacado.

**Ação:** já corrigido em `AG-076` (addendum desta sessão).

### 1.4 `aggregate_risk_max` — genuinamente ausente, confirmado

Zero ocorrências em `config/constants.yaml`. `PRD_V4_1.md` §5.3 (linha 581) declara a constante como classe A `ASSUMED`, "varredura obrigatória antes do Gate 3" — mas ela nem existe ainda. Confirma V41-8 ("Controle 19 + sizing por ativo") genuinamente não iniciado — `src/risk/limits.py` só tem `control_01` até `control_18`, nenhum `control_19`.

**Ação:** candidato real a virar linha de sweep no roadmap (junto de Sprint 10/11/16) quando V41-8 começar — não urgente hoje (V41-8 depende de V41-5/6/7 primeiro, ver `§11.6`).

### 1.5 Execução (RPI vs. post-only), Controle 17 — zero código, corretamente distantes

`src/execution/` só tem `fill_simulator.py` (simulação de backtest) — nenhuma infraestrutura de execução live/RPI. O experimento §9.5.1 (Sprint 16/Gate 8) é 100% aspiracional hoje, consistente com Sprint 13-18 ainda não terem começado. Controle 17 (limiar de liquidez, §8.3) existe em código (`control_17_liquidez`, `limits.py:348`) mas a revisão do limiar pendente citada no PRD ("junto com retorno do Grupo F a T1") não tem gatilho de quando revisar.

**Ação:** registrar em `AG-078` (já feito), sem linha de roadmap nova agora — nenhum dos dois é urgente frente a M4/M5.

### 1.6 Split, Learner, Calibração — decisões fixas, zero infraestrutura de comparação

`src/validation/cpcv.py` implementa só CPCV (sem alternativa pluggable); `src/models/alpha.py` importa `XGBClassifier` direto (sem `LearnerProtocol`); `confidence_rank` não aparece em `src/models/` (só em `src/analysis/`, fora do contrato de produção). Confirma: as três decisões (CPCV, XGBoost, isotônica-via-`confidence_rank`-nunca-avaliado) são fixadas por literatura/design, sem nenhum harness de comparação tipo-M1 existente hoje — bate exatamente com o que os PRDs dizem em prosa.

### 1.7 Monitoramento, Feedback pós-trade — código existe, mas escopo estreito

`src/monitoring/` só tem `dollar_bar_drift.py` (já rastreado) e `logging.py` (setup de `structlog`) — o sistema de alertas/dashboard de 6 páginas do §13 do V3.2 não existe. `src/models/decomposition.py::decompose()` existe e implementa a decomposição de PnL (carry/alpha/execução) — método único, sem alternativa, confirma o PRD.

## 2. Pergunta de escopo real — não resolvida aqui, decisão do Manager (`AG-079`)

Você definiu "comparison" (múltiplos candidatos medidos contra métrica, como M1/M2) como o padrão de referência pra TODO estágio (`PLANO_MESTRE_PRINCE2.md` §15.1, sua citação verbatim). Validado contra código, estes 6 itens **não têm nenhum estudo desse tipo definido em nenhum PRD, nem código de comparação**:

| item | camada | decisão hoje | precisa de rigor tipo-M1? |
|---|---|---|---|
| Data check | Data | nenhuma comparação de método de validação/qualidade existe | ? |
| Label (esquema, distinto de Barreiras) | Data | triple-barrier fixado a priori (`PRD_V4_1.md` §4.2) | ? |
| Split (CPCV vs. alternativas) | ML | fixado por citação de literatura (Arian et al. 2024) | ? |
| Learner (XGBoost vs. alternativas) | ML | fixado por citação de literatura (tree ensembles > NN em tabular) | ? |
| Monitoramento | Live Trading | esquema único (§13 do V3.2), nunca comparado | ? |
| Feedback pós-trade | Live Trading | fórmula única de decomposição, nunca comparada | ? |

Isso é **decisão de escopo, não achado de arquitetura** — abrir 6 estudos novos custa trial real (mesmo com `N_lifetime` descontinuado como gate vinculante, `AG-077`, cada medição ainda consome tempo/complexidade). Duas saídas possíveis:

1. **Sim, precisa** — vira escopo novo, entra na fila depois de M4/M5 (já priorizados).
2. **Não, as decisões já fixadas bastam** — aí o roadmap ganha uma linha explícita "decisão fechada por literatura/desenho único, não comparação medida", pra nenhuma sessão futura reabrir a mesma pergunta.

**Não decidi isso sozinho** — registrado em `AG-079`, aberto.

## 2b. Divergência interna ao próprio `PLANO_MESTRE_PRINCE2.md` (`AG-080`)

O Manager pediu explicitamente: *"o Roadmap vivo tem que estar alinhado a ele também [ao PLANO_MESTRE], se hoje houver divergência entre ambos também entra no sweep_divergencias."* Achado real, maior do que uma checagem de rotina: o próprio documento tem **duas estruturas de governança paralelas, nunca reconciliadas**.

`§15` ("Descoberta de Engenharia de `src/`", 2026-08-12..15) mapeou um modelo de 15 estágios em **DATA LAYER / ML LAYER / LIVE TRADING LAYER** (`§15.4`) — e é literalmente a origem dos nomes "Data check", "Split", "Learner", "Monitoramento", "Feedback pós-trade" que motivaram a seção 2 acima. `§15` nunca foi cruzada com `§11.4-§11.6` (reescrita nesta sessão) — as duas respondem à mesma pergunta ("o que falta, em que ordem") de ângulos diferentes (prontidão de ENGENHARIA vs. medição estatística tipo-M1), sem se citarem.

Achados adicionais, todos validados por leitura de código:

| achado | validação |
|---|---|
| `§15.2` (tabela de prontidão) desatualizada | `src/features/_sources.py:39-55` já branch por `bar_source` — a linha "TF hardcoded em `_sources.py`" não é mais verdade, corrigida pela Fase 3/4 do refactor Parkinson sem `§15` ser atualizada |
| `§15.6` item 2 (conectar infra multi-symbol/TF) | **endereçado** pela Fase 4 desta sessão (`build_modeling_frame`/`run_layer1_sprint`/`leakage.py`/`fill_reconciliation.py` parametrizados) — nunca marcado como "executado" como os itens 1/4 foram |
| `§15.6` item 3 (migrar pro `VolatilityEstimator`) | endereçado por **mecanismo diferente** do especificado — `group_c.py:18-20` confirma `c01_atr_20` ainda chama `atr_wilder` direto, não injeta o Protocol; existe uma função irmã (`c01_atr_20_parkinson`) selecionável por string. Resultado prático similar, desenho diferente |
| `§15.9` ("M5 pausado... decisão pendente do Manager sobre trial") | framing desatualizado — escrito sob o regime `N_lifetime`-como-gate, descontinuado em `AG-077`; a decisão que o parágrafo apresenta como aberta já foi tomada (`§11.6`) |
| `§14` ("Road_Map Vivo", artefato HTML externo) | não republicado desde 2026-08-12 apesar de se autodeclarar "vivo" — descreve "Sprint 4" e uma Trilha de Camadas anterior a toda a migração dollar-bar/Parkinson, à descontinuação do `N_lifetime` e à priorização de M4/M5 |

**Aplicado nesta sessão:** notas-ponteiro curtas (não reescrita do histórico) em `§14`, `§15.2`, `§15.4`, `§15.6` (itens 2-3), `§15.9`, todas apontando pra `§11.4-§11.6` como fonte de estado atual. **Não aplicado, decisão sua:** republicar o artefato HTML de `§14`; decidir se `§15.4` e `§11.6` devem virar uma estrutura só (a pergunta de fundo é a mesma do `AG-079` — os itens de `§15.4` sem equivalente M1-M6 precisam de rigor de medição, ou prontidão de engenharia já basta?). Registrado como `AG-080`.

## 3. O que já foi aplicado ao Road Map Vivo nesta sessão

- `§11.5`/`§11.6`: nota "DECIDIDO, NÃO DEPLOYADO" no item M1/Parkinson, com o valor literal de `constants.yaml` citado.
- `PRD_V4_1.md` §3.2: ponteiro de 1 linha pra remedição sob dollar-bar.
- `audit/architecture_gaps_log.yaml::AG-076`: addendum corrigindo a contagem de stress (só o roadmap Sprint 11 diverge, DoD+CLI concordam em 18) e de kill switch (13 é o número real, "15" era leitura ingênua — gatilho 15 = K06 duplicado) + 4ª colisão de nomenclatura (`R1`-`R5` com 3 sentidos ativos).
- `audit/architecture_gaps_log.yaml::AG-078`: itens (1)-(5) registrados, todos confirmados por código nesta rodada — nenhum urgente frente a M4/M5.
- `audit/architecture_gaps_log.yaml::AG-079`: pergunta de escopo dos 6 itens acima, aberta, aguardando sua decisão.

## 4. O que ficou pendente — resolvido em rodadas seguintes desta mesma sessão

Todos os 5 itens abaixo foram levados a um pacote de 10 recomendações
(`project_assurance` + Claude, convergentes em 8/10, discordância leve em
2/10) e autorizados pelo Manager. Estado final de cada um:

1. **Decisão de escopo (6 itens, `AG-079`)** — FECHADO. 6/6 não precisam de estudo tipo-M1 (motivo por item registrado em `AG-079`). `Label` ganhou proveniência escrita em `PRD_V4_1.md` §4.2; `Learner` ganhou nota sobre `N_lifetime=62` obsoleto em §4.3.
2. **Tabela Sprint-N↔V41-N** — mantida como proposta, sem revisão formal linha-a-linha (custo real considerado maior que o benefício).
3. **`aggregate_risk_max` + RPI vs. M4/M5** — `aggregate_risk_max` IMPLEMENTADO (`control_19_risco_agregado`, `AG-081`, desacoplado de V41-8 por decisão do Manager — o risco já estava quantificado). RPI segue sem linha de roadmap, correto — Sprint 16 ainda distante.
4. **Artefato HTML de `§14`** — **CORRIGIDO nesta rodada**: a primeira execução tratou isso como "aposentar" (erro de leitura meu — o Manager pediu explicitamente pra não apagar o antigo e criar um novo, já que o objetivo de todo o sweep sempre foi REFATORAR, não abandonar). Publicado **[Road Map Vivo — v2](https://claude.ai/code/artifact/82d1a3ad-1ffd-427e-b120-a07d33a17637)** (2026-08-17), síntese visual de `§11.4-§11.6` + `§15.2/§15.4` + `AG-075..081`. v1 preservado como referência histórica, link no rodapé do v2.
5. **`§15.4` vs. `§11.6`** — mantidas como duas lentes separadas, com tabela de cross-reference formal adicionada a `§11.6` (19 linhas).
