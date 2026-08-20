# Brief para Auditoria Externa — Motor Quant Multi-Ativo
### Contrato Regime → Features → Label → Pesos → Split → Learner → Calibração → Validação → Meta-Model → Risk → Execução

**Data:** 2026-08-19
**Para:** revisor externo (sem acesso ao repositório — este documento é a fonte completa)
**Formato de referência:** estrutura adaptada de um brief de análise competitiva (escopo → estado atual → comparação → forças/fraquezas → oportunidades → implicações estratégicas) — aqui "competidor" é substituído por "estado atual do pipeline vs. o que falta desenhar"

---

## 0. Como usar este documento

Este projeto já passou por duas rodadas de auditoria: uma sobre **qual método detecta regime melhor** (Trilha A — já auditada, resultado abaixo em §4) e uma sobre **como as camadas se conectam** (Trilha B — parcialmente resolvida, é o foco deste brief). Nenhuma das duas te pede a mesma coisa:

- Onde já existe uma proposta técnica aprovada (4 casos, §5.3), o pedido é **validação cética** — releia com ceticismo genuíno, não aceite "já foi aprovado" como sinal de que está correto.
- Onde não existe proposta nenhuma (a maior parte das fronteiras entre estágios, §7), o pedido é **desenho técnico concreto** — não "existe gap aqui?" (sabemos que sim) nem "o que falta?" (sabemos o quê, não sabemos o como). Proponha o contrato de dado real.
- Onde há uma decisão de escopo pendente (§6), o pedido é uma **recomendação fundamentada**, não uma auditoria.

---

## 1. Contexto do projeto

Motor quant para cripto futures, Binance USDⓈ-M, capital operacional R$ 1.000, execução maker post-only (GTX, cancela no timeout, nunca converte a mercado). Estava BTC-only, construído só até a camada de Alpha — em refatoração ativa para multi-ativo (5 símbolos: BTC/ETH/SOL/BNB/XRP) e multi-resolução (dollar bars R1/R2/R3, ~15min/30min/1h equivalente por frequência média) simultaneamente.

**Mandato do Manager (corrigido nesta sessão, versão final):** o motor **não** opera timeframe fixo por decisão de design (não é "sempre M15"), mas também **não** escolhe dinamicamente em tempo real durante a operação ao vivo. O fluxo real é: **treinar/testar cada combinação (símbolo, resolução) de forma fixa e independente → eliminar numa rodada de pesquisa/retreino periódica o que não performar → operar em produção com a(s) combinação(ões) vencedora(s), fixa(s), até a próxima rodada de reavaliação.** É seleção de modelo offline (mesma classe de problema que escolher hiperparâmetro por backtest), só que o espaço de busca inclui símbolo e resolução como eixos, não apenas parâmetros do modelo. Alvo declarado: os pares que entregarem mais edge no Alpha e no Meta-model sobrevivem; o resto é eliminado.

**Não existe uma "estratégia" no sentido clássico (tese de edge).** O projeto não aposta em mean-reversion, momentum ou qualquer padrão nomeado a priori — é uma metodologia de descoberta: cataloga um universo amplo de features candidatas (§2 abaixo), rotula com triple-barrier, treina classificadores binários e deixa a validação (CPCV/ablação/DSR) decidir o que sobrevive. O "edge", se existir, é o que o processo encontrar — não uma hipótese declarada de antemão.

---

## 2. O que é fixo hoje, e o que mudou nesta sessão

### 2.1 Labels (triple-barrier) — geometria de payoff

| Parâmetro | Valor | Proveniência |
|---|---|---|
| `tp_atr_mult` | 2.0× ATR | `ASSUMED` — "herdado do PRD V2, nunca questionado" |
| `sl_atr_mult` | 1.5× ATR | `ASSUMED` — idem, sweep 2D pendente |
| `time_stop_ms` | 28.800.000 ms (8h) | `DERIVED` — reexpressão de unidade de um valor original também `ASSUMED`, sem sweep de sensibilidade feito |
| Modelo | 2 classificadores binários por lado (`M_long`/`M_short`), XGBoost — nunca multiclasse | fixo por banned pattern do projeto |

Nenhum dos 3 primeiros números tem validação própria — são herança não-testada de uma versão anterior do blueprint. Isso é relevante pro brief porque QUALQUER arquitetura downstream que assuma esses valores como estáveis está construindo sobre um piso ainda não medido.

### 2.2 Features — mudança de política nesta sessão

**Estado anterior (histórico, código ainda reflete isso hoje):** só 10 features "T1" entravam no vetor de treino do Alpha, escolhidas por ablação dentro do CPCV (k=6,9,12,16,24, critério PBO<0,30) sobre um catálogo maior de ~100 candidatas (T2 calculadas mas não usadas; T3 bloqueadas por fonte de dado ausente).

**Decisão nova do Manager (2026-08-19): a política de tiering T1/T2/T3 como PORTÃO DE ENTRADA foi descontinuada.** Todas as features cujo código/fonte de dado já existe passam a ser canônicas (elegíveis) — o Alpha/Meta-model decide, por conta própria (importância nativa, regularização, seleção dentro do próprio treino), quais são de fato úteis, em vez de um portão humano pré-filtrar 10 antes do treino começar. **Isto ainda não está implementado em código** — `T1_FEATURE_IDS` (`src/features/build.py:29-40`) continua travado nas 10 antigas; é uma decisão de arquitetura registrada, pendente de propagação pro código.

**Ressalva técnica que fica pro auditor externo considerar** (não resolvida aqui): "canônico" não resolve **ausência de fonte de dado**. As features T3 do catálogo abaixo (opções, boa parte do macro) estão bloqueadas porque a fonte de dado não existe no pipeline hoje — nenhuma mudança de política de tiering muda isso. Só T1+T2 (fontes já wired) são de fato utilizáveis sob a nova política; o resto seguirá bloqueado até a fonte existir.

**Catálogo completo (`PRD_V3_2_UNIFICADO.md`, Parte II, grupos A-K):**

| Grupo | Conteúdo | Contagem aprox. | Fonte |
|---|---|---|---|
| A — Preço e retorno | log-retornos, distância a EMA/VWAP, formato de candle | 17 | D03 |
| B — Momentum/reversão | RSI, MACD, efficiency ratio, stochastic, Bollinger | 12 | D03 |
| C — Volatilidade | ATR, realized vol, Parkinson, Garman-Klass, percentis de vol | 17 | D03/D05 |
| D — Volume/fluxo de agressor | z-score de volume, taker imbalance, contagem de trade, order flow | 13 | D01/D03 |
| E — Futuros (funding/OI/basis) | funding z-score, OI change, basis perp-index, posicionamento top-trader | 27 | D04/D07/D10-D13 |
| F — Microestrutura | spread, book imbalance, profundidade, microprice | 14 | D02/D08/D09 — **removido de T1 em 2025-11-20 por quebra de definição real** (ordens RPI ocultas tornam spread/book visível não-comparável antes/depois; não tem relação com este trabalho, mas explica por que microestrutura também não entra no estudo de regime, §4) |
| G — Opções | put/call ratio, max pain, gamma exposure | 6 | D14 — **T3, sem fonte hoje** |
| H — On-chain | netflow, SOPR, MVRV, hash rate | 11 | E01 — **T2 (fonte real já wired), não T3** — excluída de T1 histórico por granularidade diária ("contexto de regime, não entrada"), não por ausência de fonte; sob a política nova, é usável hoje |
| I — Macro/institucional | ETF flow, DXY, yields, correlação BTC-SPX | 10 | E04 — **T3, ETF flow só desde 2024-01** |
| J — Execução (exclusivo do Meta) | prob. de fill, distância ao touch, custo estimado, adverse selection | 5 | modelo de fila — só entra quando Meta existir |
| K — Temporal/calendário | codificação cíclica de hora/dia, sessão, halving | 8 | derivado |

**As 10 que eram T1 até esta sessão** (agora só "as primeiras candidatas testadas", não mais um portão fechado): `A05_ret_vol_norm_4`, `A13_dist_ema48_atr`, `B01_rsi_14`, `E27f_cost_atr_ratio`, `C06_vol_ratio_12_96`, `C07_vol_pctile_expanding`, `D03f_volume_z_expanding`, `D06f_taker_imbalance_z_48`, `E02f_funding_z_expanding`, `E10f_oi_change_z_48`. Mais regime como one-hot (histórico — cardinalidade em aberto, ver §5.3).

**Achado que motivou 2 dessas 10 (contexto real, não decorativo):** `B07_efficiency_ratio_48` (a feature original antes de `E27f` substituí-la) tinha IC medido de +0,042 em 2024 e **−0,031 em 2026** — inverteu de sinal. Ficou como eixo de regime (descrever tendência não exige sinal estável; prever direção, sim). `E27f_cost_atr_ratio` entrou porque custo/ATR foi de 11,0% para 19,4% entre 2021-2026 — a única feature que capta essa degradação estrutural diretamente.

**Pergunta pro auditor**: sob "todas canônicas", o critério de ortogonalidade que existia pra 10 features (`|Spearman| > 0,70` → a de menor importância sai) não escala trivialmente pra ~92 features usáveis (T1+T2, ver o companion deste brief pra contagem exata por grupo). Qual mecanismo de redundância/multicolinearidade é apropriado nessa escala — HHI efetivo (já usado em outro lugar do projeto pra concentração de importância), clustering hierárquico, ou deixar puramente pra regularização L1/L2 do XGBoost decidir?

### 2.3 Os 4 candidatos de detecção de regime (Trilha A) — matemática exata

| Candidato | Fonte de código | Observação (input) | Mecânica | Causalidade do decode |
|---|---|---|---|---|
| **Baseline** (`QuantileRegimeClassifier`, produção hoje) | `src/regime/classifier.py` | `er_quantile` (posto percentil expansivo estrito de B07 — eixo estrutura/tendência) + `vol_pctile` (idem de C07 — eixo volatilidade) | 6 estados R0-R5 por corte de quantil + gatilhos de stress; R0=warmup, R1-R4 tradeable, R5=stress | Causal — `expanding_percentile_rank_strict`, índices `i<t` estritos, implementado via Fenwick tree O(n log n) |
| **HMM Gaussiano** | `src/regime/hmm_gaussian.py`, lib `dynamax` | `[log_return_1, realized_vol_short]`, direto do OHLC da dollar-bar (não do Feature Engine, decisão deliberada de isolar o teste de ortogonalidade) | k=2/3/4 (3 trials separados), fit EM por fold de walk-forward, inicialização k-means só nas médias (covariância inicial substituída por covariância empírica do treino) | Causal — `hmm.filter()` é *forward filtering*, `P(z_t\|y_1:t)`, formalmente distinto de smoothing/Viterbi (confirmado contra Eq. 3 de Adams & MacKay via analogia de teoria de filtragem) |
| **Jump Model** (Continuous/Statistical Jump Model) | `src/regime/jump_model.py`, lib `jumpmodels` | mesmo espaço 2D | `jump_n_states=2`, `jump_penalty=0,002` (calibrado numa fatia recente de ~50.000 barras de BTC, nunca retestado em outros ativos), coordinate-descent minimizando soma de desvios² + penalidade de transição | **Não-causal dentro do fold de teste** — `.predict()` é *dynamic programming* com traceback a partir da ÚLTIMA barra do array passado; confinado ao fold (nunca cruza fronteira treino/teste), mas real |
| **BOCPD** (Bayesian Online Changepoint Detection) | `src/regime/bocpd.py`, formulação de Adams & MacKay 2007 | só `log_return_1`, univariado | `hazard_lambda=65,0` (5× a duração mediana de segmento do baseline, medida sobre o histórico completo do BTC — nota: esse histórico inclui as janelas de teste, sobreposição temporal real, não outcome-hacking mas caveat legítimo), prior Normal-Inverse-Gamma calibrado só sobre as 100 primeiras barras (warmup fixo), `n_canonical_buckets=3` | Causal por construção — recursão estritamente sequencial (`for t in range(n)`, cada passo só usa `obs[t]` + estado de `t-1`); prova matemática feita nesta sessão bate com a definição formal de *filtering distribution* |

### 2.4 Resultado real da Trilha A (4ª execução, dado real)

Todos os 18 p-valores de permutação (6 candidatos × 3 resoluções, por lado) ficaram entre 0,30 e 0,85 — nada estatisticamente significativo em nenhuma célula, incluindo o BOCPD (que liderava sob a métrica clássica de I², depois identificada como artefato de autocorrelação intra-regime, não heterogeneidade real). Jump Model tem poder estatístico inexistente (mediana de 4 episódios por célula, mínimo 1) em 100% das 102 células — resultados dele não são interpretáveis.

---

## 3. A cadeia de estágios, com os dois papéis do regime separados

```
FEATURES (catálogo completo, §2.2 — 4 fontes de observável distintas)
   │
   ▼
REGIME (Trilha A decide o método — PAPEL 1: vira FEATURE)
   │
   ├────────────────────────────────┐
   ▼                                 │
LABEL → PESOS → SPLIT → LEARNER ◄────┘ (regime entra como coluna, junto do resto)
   │
   ▼
CALIBRAÇÃO → VALIDAÇÃO → META-MODEL
   │
   ▼
DECISION ENGINE ◄── REGIME (PAPEL 2: vira GATE — regime.tradeable)
   │
   ▼
RISK ENGINE ◄── REGIME (mesmo papel de gate, control_01)
   │
   ▼
EXECUÇÃO
```

Regime tem dois papéis que se misturar produz confusão: **feature** (entra no vetor de treino do Learner, junto com as demais) e **gate** (bloqueia entrada/aprova operação, no Decision Engine e no Risk, independente do que o Learner aprendeu). São perguntas de desenho diferentes — "qual regime vira coluna de treino" não é a mesma pergunta que "qual regime bloqueia trade".

---

## 4. Trilha A — status resumido (já auditada, não precisa reabrir)

- 6 candidatos (baseline + HMM k=2/3/4 + Jump Model + BOCPD), 3 resoluções, 5 janelas históricas críticas.
- 2 auditorias externas brutas processadas + validação cruzada própria (código real + pesquisa de literatura: Adams & MacKay 2007, Nystrup/Cortese/Shu para Jump Model, Winkler et al. para block permutation, Bailey/López de Prado para DSR/PBO).
- Resultado categorizado:

| Categoria | Itens |
|---|---|
| **Redesenho** (Estudo 2, não agora) | hierarquia real R3→R1/R2 condicionando o modelo rápido; features de microestrutura nativas em dollar bar; multi-resolution como estudo formal |
| **Fix mecânico** (extensão barata) | separação multi-horizonte + de volatilidade futura; teste de resposta condicional a regime do BTC; estatística por episódio (não só trade); occupancy/transition-failure/detection-delay; coerência cross-resolution; recalibração de `hazard_lambda` restrita a dado pré-teste |
| **Habilitação** (mecanismo já existe, só falta decisão) | excluir Jump Model do Estudo 1; congelar metodologia + locked holdout; reconciliar N_lifetime |
| **Rejeitado** (refutado com evidência) | BOCPD reiniciar por fold (matematicamente impossível de vazar futuro); block bootstrap em vez de block permutation (literatura confirma o desenho atual já é correto); BIC dinâmico como proposta primária pro Jump Model (sem precedente, perdeu para FTIC quando testado formalmente) |

Documento completo com toda a evidência: seção própria já arquivada no repositório (`docs/m4_regime_auditoria_externa_2026-08-19_validacao_cruzada.md`), não reproduzido aqui por já estar fechado.

---

## 5. Trilha B — o que já foi auditado e resolvido

### 5.1 Como foi descoberto

3 investigações independentes (código real cross-referenciado com os documentos de planejamento) encontraram 10 gaps reais na cadeia Regime→Alpha→Decision Engine→Meta-Label→Risk→Execução — cada um com citação exata de arquivo/linha, não hipótese.

### 5.2 Como foi resolvido (parcialmente) — 4 rodadas de contestação adversarial

Processo: rascunho de resolução técnica → auditoria adversarial independente (agente sem contato com o raciocínio de quem rascunhou, obrigado a re-verificar tudo) → repete até estabilizar. Achados reais em TODAS as 4 rodadas (nada foi rubber-stamp):

| Rodada | Achado |
|---|---|
| 1 | O cap de posições concorrentes proposto dependia de um rastreador de posição ao vivo que não existe (mesma classe de gap já catalogada em outro contexto) |
| 2 | O módulo pra esse rastreador teria um problema real de prioridade de rate-limit (a chamada mais importante seria a primeira adiada, justamente sob a rajada de tráfego que mais importa) |
| 3 | Uma das opções pra resolver isso violava uma garantia de segurança já codificada (prioridade absoluta de rate-limit pra chamadas de execução/kill-switch) |
| 4 | A mesma opção, mesmo corrigida quanto à violação de segurança, não resolvia o problema original de jeito nenhum — removida |

### 5.3 As 4 propostas aprovadas pelo Manager (2026-08-19) — pedido de validação cética aqui

**(A) Decision Engine entra no inventário de estágios de engenharia.** Mecânico, sem controvérsia — pular esta.

**(B) Gate de posição por linha, não global.** O texto de planejamento original (nunca emendado) dizia "uma posição por vez, projeto inteiro". Sob multi-ativo isso trava a operação concorrente de múltiplos símbolos. Resolução: gate vira "posição atual no MESMO (símbolo, resolução) ≠ FLAT → bloqueia entrada" — permite símbolos diferentes concorrentes, preserva a proteção original contra duplicar sinal na mesma linha. **Dependência não resolvida**: um cap de posições concorrentes totais (proteção de portfólio, complementar a um controle de risco agregado que hoje não computa nada por falta de rastreador de posição ao vivo) precisa desse rastreador ser construído primeiro — 2 caminhos ficaram abertos (cache local com TTL curto vs. aceitar defasagem com gatilho de reconciliação), nenhum escolhido, valor do cap em si não medido.

**(C) Convenção de contagem de trials para seleção de linha.** Cada combinação (símbolo, resolução) avaliada com backtest/medição individual conta como 1 trial no orçamento de múltiplos testes do projeto — sempre, independente de quantas acabam promovidas (a tentativa inicial de regra usava o RESULTADO da rodada como critério de contagem, o que gerava uma circularidade real com o próprio gate estatístico; corrigido para um critério estrutural — exige backtest novo por candidata, sempre verdade aqui).

**(D) Gatilho de proteção quando regime piora com posição aberta.** A proposta original (apertar o stop-loss) foi refutada por pesquisa de prática de mercado — apertar stop sob alta volatilidade aumenta risco de saída prematura por ruído, não reduz o risco de execução (uma vez disparado, o stop vira ordem sujeita ao mesmo book fino independente da distância). Mecanismo revisado: encurtar o horizonte máximo de holding da posição (não mexer no preço do stop) — reduz a janela de exposição sem esse efeito colateral. Valor exato do encurtamento não medido; depende de uma camada de execução que ainda não existe (`place_order` continua sem implementação real).

**Pedido específico**: essas 4 já passaram por auditoria interna repetida — o valor de uma segunda opinião aqui é achar o que um processo estruturalmente correlacionado (mesma família de modelo revisando o próprio trabalho, mesmo com contexto limpo a cada rodada) pode ter em ponto cego sistemático.

---

## 6. Decisões pendentes — cada uma com contexto técnico completo

1. **Cache-TTL vs. aceitar-defasagem** para o módulo de contagem de posição ao vivo (pré-requisito de B acima). A chamada relevante da API tem prioridade baixa no orçamento de rate-limit do projeto, e esse orçamento garante hoje que chamadas de execução (cancelar ordem, fechar posição, kill-switch) nunca perdem espaço — não pode ser sacrificado. Qual dos dois caminhos é mais defensável sob stress de mercado, dado que a chamada de baixa prioridade é exatamente a que fica pra trás quando mais importa?
2. **Valor do cap de posições concorrentes.** Referência textual de "2 posições simultâneas, 3 já violam" existe num documento de planejamento, nunca medida contra a correlação real entre os 5 ativos.
3. **Denominador do controle de perda diária sob posições concorrentes.** A conta opera em modo cruzado (margem/equity compartilhada entre símbolos, não segregável pela própria exchange) — o teto de perda diária (2% de equity) é sobre a equity total compartilhada, ou algum nocional de referência dividido por linha ativa? A primeira é o que a exchange de fato reporta sem trabalho extra; a segunda exige inventar uma alocação que não existe nativamente.
4. **Adotar o gatilho de proteção (D acima) agora, com parâmetro provisório, ou aceitar o risco documentado e adiar?** O gap é pré-existente à expansão multi-ativo — só fica mais caro porque mais posições ficam expostas simultaneamente sob stress.
5. **Heurística de partida pro valor de encurtamento de horizonte (D acima).** Existe prática de mercado geral pra "sair mais cedo sob volatilidade alta", mas nada específico pro quanto cortar sem medição própria.
6. **Comprometer trabalho de engenharia real pra habilitar as resoluções mais lentas em produção agora, ou rodar a primeira rodada de seleção só na resolução mais rápida?** O motor de features/regime já aceita as 3 resoluções tecnicamente; o motor de labels (que precisa persistir artefato, não recomputa em memória) só tem histórico gerado pra 1 das 3, em nenhum dos 5 símbolos além do original.
7. **Quando o Meta-Model for construído, ele consome regime como input, e de qual candidato/resolução?** O critério de entrada do Meta (5 condições quantitativas: amostra efetiva mínima, modelo de fila calibrado, ganho de precisão estável, DSR positivo, Brier score) não menciona regime em nenhuma delas — decisão de desenho separada, sem urgência (Meta ainda não existe).
8. **Ortogonalidade/redundância entre features sob "todas canônicas"** (§2.2) — mecanismo pra substituir o corte simples de correlação pareada que só funcionava em escala pequena (10 features).
9. **Se a delegação de seleção de feature pro Alpha/Meta (§2.2) muda a contagem de trials do DSR.** A metodologia antiga (ablação buscando o melhor k) contava cada k testado como trial. Se a seleção agora acontece DENTRO de um único treino regularizado (não uma busca externa sobre variantes), isso reduz a multiplicidade de testes real, ou só move a busca pra dentro do modelo sem eliminar o problema de fundo?

---

## 7. Fronteiras sem desenho nenhum — pedido de proposta técnica, não de auditoria

Nenhuma das fronteiras abaixo tem contrato de dado especificado hoje (schema, formato, regra de decisão). Pra cada uma, o pedido é: dado o que entra e o que precisa sair, **proponha o contrato concreto**.

| Fronteira | O que existe hoje | O que falta |
|---|---|---|
| Features → Label | Loosely acoplado — labels usam ATR (de Features) pra geometria de barreira, mas o contrato formal (quais features exatamente o Label Engine pode ler, causalidade entre os dois) não está escrito | Contrato de dependência explícito |
| Label → Pesos | Existe código (`weights.py`), sem documentação de contrato externo revisada nesta rodada | Verificar se está alinhado com a mudança "todas features canônicas" |
| Pesos → Split | Split usa embargo temporal — não há contrato formal de como pesos de unicidade interagem com o novo espaço de seleção de linha (símbolo × resolução como dimensão de busca) | Contrato explícito |
| Split → Learner | Camada existe parcialmente (~1,5 de 5 camadas planejadas) — sem contrato de quantas camadas são realmente necessárias sob a política de features "todas canônicas" | Redesenho do número de camadas dado o novo espaço de features |
| Learner → Calibração | Calibração hoje é inline no próprio código do Learner, nunca foi separada como estágio próprio | Decisão: separar ou manter inline, e por quê |
| Calibração → Validação | Validação (CPCV/DSR/PBO) existe como código mas não está conectada a um pipeline de produção real | Contrato de quando/como a validação roda automaticamente |
| Validação → Meta-Model | Meta ainda não existe — ver decisão pendente #7 acima | Desenho completo, zero precedente |

---

## 8. O que pedimos exatamente

- **§5.3 (as 4 propostas aprovadas):** validação cética — não aceite que "já foi aprovado" significa correto; ataque o mecanismo de novo, com foco em pontos cegos que um processo de revisão correlacionado (mesma família de modelo) tende a ter.
- **§6 (9 decisões pendentes):** recomendação fundamentada para cada uma, não descoberta — já sabemos que a decisão está em aberto, queremos um ponto de vista técnico sobre qual caminho escolher.
- **§7 (fronteiras sem desenho):** proposta de arquitetura concreta — schema de dado, formato, regra de decisão — não uma confirmação de que "falta desenhar aqui" (já sabemos).
- **Bônus, se o revisor tiver disposição:** olhar §2.2/§6.8/§6.9 — a mudança de política de features (T1 fixo → todas canônicas) é recente e pode ter implicações que ninguém neste projeto ainda mapeou completamente.

---

## 9. Formato de resposta esperado

Por item: veredito direto, evidência ou raciocínio explícito (não opinião solta), e se discordar de algo já aprovado, dizer isso explicitamente — nada aqui é imune a contestação por já ter passado por uma rodada interna.

Onde a recomendação depender de literatura ou prática de mercado (§6/§7 em especial), siga o protocolo de pesquisa do material de apoio (companion deste documento) antes de concluir — não é opcional, é o que diferencia uma recomendação fundamentada de uma opinião.

---

## 10. Anexos técnicos — código citado

```python
# Cadência de contagem de N (DSR / múltiplos testes) — regra formal do projeto
# "N trials = combinações de parâmetro que exigem AJUSTE DE MODELO OU
#  RECÁLCULO DE BACKTEST novo por combinação"
# vs.
# "1 trial = passe de ranking/triagem que reusa artefato já ajustado,
#  sem novo backtest por candidata"
```

```python
# BOCPD — núcleo da recursão (prova de causalidade)
for t in range(n):
    x = float(obs[t])
    log_pred = _log_predictive(x, mu, kappa, alpha, beta)
    log_joint = log_r + log_pred
    log_growth = log_joint + log_one_minus_hazard
    log_cp = logsumexp(log_joint + log_hazard)
    log_r_new = np.concatenate(([log_cp], log_growth))
    log_r_new -= logsumexp(log_r_new)
    # cada iteração só consome obs[t] + estado de t-1 — nunca obs[t+1:]
```

```python
# Alpha — cardinalidade de regime hard-coded (fonte de um dos gaps ainda abertos)
REGIME_ONEHOT_LEVELS: tuple[str, ...] = ("R2", "R3", "R4", "R5")
DESIGN_COLUMNS: tuple[str, ...] = (*T1_FEATURE_IDS, *REGIME_DUMMY_COLUMNS)
```

Qualquer coisa além destes 3 trechos, o revisor deve tratar como não-verificável sem acesso ao repositório — pedir esclarecimento em vez de assumir.
