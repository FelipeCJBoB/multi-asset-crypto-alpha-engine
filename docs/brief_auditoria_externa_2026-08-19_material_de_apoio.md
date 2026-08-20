# Material de Apoio — Brief de Auditoria Externa (2026-08-19)

Companion de `brief_auditoria_externa_2026-08-19_regime_alpha_execucao.md`. Não repete o conteúdo do brief — adiciona o que um revisor externo, sem repositório, sem contexto acumulado, precisa pra chegar rápido ao ponto: glossário, cronologia, um erro real já achado e corrigido nesta própria revisão (calibra o padrão de rigor esperado), perguntas antecipadas com respostas ricas, e um guia de calibração de resposta.

---

## 1. Glossário rápido

| Termo | Significado |
|---|---|
| **Dollar bar** | Barra formada por volume monetário acumulado (não tempo fixo) — R1/R2/R3 são 3 tiers calibrados por frequência MÉDIA equivalente a ~15min/30min/1h |
| **R1-R5 (regime)** | Estados do classificador de regime de produção (R0=warmup, R1-R4 tradeable, R5=stress) — **colisão de nome com R1/R2/R3 de resolução**, são eixos diferentes, cuidado ao ler qualquer citação de "R1" no material |
| **T1/T2/T3 (feature)** | Tiering antigo (descontinuado nesta sessão): T1=vetor de treino, T2=calculada mas fora, T3=bloqueada por fonte ausente |
| **Triple-barrier** | Metodologia de rotulagem: TP/SL/time_stop como 3 barreiras, o rótulo é qual delas é tocada primeiro |
| **CPCV** | Combinatorial Purged Cross-Validation — validação cruzada com purge (remove overlap de horizonte) e embargo (janela extra de segurança) |
| **DSR** | Deflated Sharpe Ratio — penaliza Sharpe por número de trials já gastos (múltiplos testes) |
| **PBO/CSCV** | Probability of Backtest Overfitting — mede, entre várias variantes testadas no mesmo dado, a chance de a vencedora in-sample decepcionar out-of-sample. Citado no brief como não implementado neste repo |
| **N_lifetime** | Ledger manual de trials gastos — descontinuado como orçamento VINCULANTE (não bloqueia mais nada), mas seguido sendo registrado como histórico |
| **Decision Engine** | Camada entre Alpha/Meta e Risk que transforma predição em "intenção de trade" — existe no documento de blueprint original, nunca tinha entrado no inventário de estágios de engenharia até a auditoria mais recente |
| **BOCPD** | Bayesian Online Changepoint Detection (Adams & MacKay 2007) — um dos 4 candidatos de regime, detector de mudança online |
| **Jump Model** | Continuous/Statistical Jump Model — outro candidato, segmentação com penalidade de transição |
| **AG-NNN** | Identificador de achado no ledger de gaps de arquitetura do projeto (`architecture_gaps_log.yaml`) — sequência única, append-only |

---

## 2. Cronologia do processo (por que isto não é a primeira rodada)

1. **Trilha A iniciada** — construção do harness comparando 6 candidatos de regime × 3 resoluções × 5 janelas históricas.
2. **1ª-3ª execuções reais** — achados de metodologia (timestamp de join, tratamento de k=1 em teste estatístico, violação de independência em teste de heterogeneidade, janela de avaliação do BOCPD) corrigidos sequencialmente, cada correção auditada de forma independente antes da próxima execução.
3. **4ª execução real** — resultado nulo generalizado (nenhum candidato mostra heterogeneidade significativa após a correção de independência).
4. **2 auditorias externas brutas** trazidas pelo Manager — processadas, validadas contra código real + literatura, resultado categorizado (redesenho/fix mecânico/habilitação/rejeitado).
5. **Pergunta de virada**: antes de decidir QUAL candidato usar, definir o CONTRATO downstream (quem consome regime, como) — abre a Trilha B.
6. **Auditoria cética da Trilha B** — 3 investigações independentes acham 10 gaps reais na cadeia Regime→Alpha→Decision Engine→Meta→Risk→Execução.
7. **4 rodadas de contestação adversarial** sobre as resoluções propostas — achado real em cada uma das 4 (não é exercício de formalidade).
8. **Aprovação do Manager** das 4 propostas, com decisões residuais explicitamente listadas como pendentes, não decididas por omissão.
9. **Correção de mandato e de premissas** (esta sessão) — o mandato tinha sido mal-entendido (seleção "dinâmica em tempo real" vs. o correto "offline, fixo, eliminação periódica"), "estratégia definida" não procede (é metodologia, não tese), tiering de features foi descontinuado.
10. **Este brief** — ponto de checkpoint pra trazer revisão externa antes de continuar.

O padrão que se repete nas etapas 2, 6-7 e 9: cada rodada de escrutínio (interna ou externa) achou pelo menos uma coisa real, nunca zero. Isso não é uma previsão de que a próxima rodada (a sua) vai achar algo — é uma calibração honesta de que o processo até aqui não convergiu por esgotamento de achados, convergiu por decisão de parar numa rodada específica.

---

## 3. Um erro real, achado escrevendo este próprio documento de apoio

Ao revisar o brief pra este companion, o Grupo H (on-chain) estava classificado como "T3, sem fonte real" — **errado**. Conferido direto no `PRD_V3_2_UNIFICADO.md` (linhas 647-661): as 11 features do Grupo H são **T2**, com fonte real já wired (`E01`), excluídas de T1 historicamente por granularidade diária (inflam correlação serial, "features de contexto de regime, não de entrada"), não por ausência de dado. Já corrigido no brief. Isso muda a contagem de "features usáveis hoje sob a política nova":

| Grupo | Contagem | Usável (T1/T2, fonte real) |
|---|---|---|
| A — Preço/retorno | 17 | 17 |
| B — Momentum/reversão | 12 | 12 |
| C — Volatilidade | 17 | 15 (2 T3: C16 DVOL Deribit, C17 skew 25d) |
| D — Volume/fluxo | 13 | 13 |
| E — Futuros | 27 | 17 (10 T3, majoritariamente basis/premium index que dependem de fonte D10-D13 ainda não confirmada) |
| F — Microestrutura | 14 | **0 sob a exclusão atual** — não é problema de tiering, é quebra de definição real (RPI oculto desde 2025-11-20); "canônico" não resolve isso, só a coluna `rpi_regime` + ≥6 meses de coleta pós-quebra resolveria |
| G — Opções | 6 | 0 (T3, sem fonte) |
| H — On-chain | 11 | **11 (corrigido — era T3, é T2)** |
| I — Macro | 10 | 0 (T3, sem fonte) |
| J — Execução (Meta) | 5 | N/A pro Alpha, exclusivo do Meta quando existir |
| K — Temporal | 8 | 7 (K06 é gatilho de risco, não feature) |

**Total usável hoje pro Alpha, sob "todas canônicas": ~92 features**, não as ~80 citadas de forma aproximada no brief original. Isso é uma tabulação manual contra o texto do PRD — o próprio projeto declara `features/registry.yaml` como fonte de verdade formal (§2.14 do PRD), não a prosa — se houver divergência entre esta tabela e o registry real, o registry vence.

---

## 4. Perguntas antecipadas, com respostas ricas

### Sobre o mandato (§1 do brief)

**P: Se a seleção de linha é offline e periódica (não em tempo real), por que o Decision Engine ainda precisa de um gate por linha e de um cap de posições concorrentes? Não bastaria um único gate global, já que só as linhas "vencedoras" operam?**

R: Porque "vencedora(s)" é plural por desenho — o alvo declarado é "os PARES que entregarem mais edge", não "o par". Múltiplos símbolos (cada um possivelmente com sua própria resolução vencedora) podem sobreviver à eliminação e operar concorrentemente em produção, de forma fixa, até a próxima rodada. O gate por linha impede duplicar posição na MESMA linha (proteção básica). O cap de posições concorrentes é sobre a SOMA das N linhas ativas simultaneamente — proteção de portfólio, não de seleção. São dois controles com propósitos diferentes que coexistem mesmo sob seleção fixa.

**P: Quantas linhas "vencedoras" o projeto espera manter — é um número-alvo, ou aceita qualquer quantidade que passar no critério de edge?**

R: **Não especificado em nenhum documento do projeto — achado deste companion, não do brief original.** O único número citado em qualquer lugar ("2 posições simultâneas, cap efetivo — 3 já violam") é sobre RISCO agregado de correlação entre posições ABERTAS, não sobre quantas linhas sobrevivem à seleção de edge. São perguntas diferentes: quantas linhas PASSAM no critério (pode ser qualquer número, de 0 a 15) vs. quantas podem estar com posição aberta ao mesmo tempo (limitado por risco). Se muitas linhas sobreviverem à seleção mas o cap de risco for baixo, falta uma regra de PRIORIZAÇÃO entre linhas aprovadas quando mais de uma quer abrir posição no mesmo instante (round-robin? maior edge medido primeiro? ordem alfabética de símbolo?) — isso não existe em lugar nenhum. Recomenda-se que o auditor trate isso como um item de decisão pendente adicional, não coberto no brief original.

**P: Sem uma tese de edge declarada, como o projeto se defende de estar fazendo puro data dredging sobre ~92 features e um espaço de 15 combinações símbolo×resolução?**

R: A defesa real do projeto tem 3 peças: (1) CPCV com purge+embargo, que impede vazamento de horizonte entre treino/teste; (2) critério de parada declarado a priori no próprio PRD ("se o Sharpe OOS não crescer monotonicamente até k=6, o problema não é número de features — é ausência de sinal. Nesse caso, voltar ao Gate 0"); (3) DSR, que deflaciona Sharpe pelo número de trials já gastos. A honestidade que falta: a 3ª peça (DSR) está atualmente **sem orçamento vinculante** — o ledger de trials (`N_lifetime`) foi descontinuado como GATE por decisão do Manager numa sessão anterior ("mal implementado desde o começo"), e nada o substituiu formalmente ainda (gap aberto, catalogado, sem resolução). Ou seja: a defesa metodológica existe no papel, mas uma das 3 pernas está capenga hoje. Isso é exatamente o tipo de coisa que vale um auditor externo cutucar com força.

### Sobre features/labels (§2 do brief)

**P: TP=2.0×ATR e SL=1.5×ATR nunca foram testados (sweep) — isso não deveria ser prioridade zero antes de qualquer arquitetura de conexão entre camadas?**

R: É um argumento defensável, e o brief já sinaliza isso como risco não mitigado. O contra-argumento do projeto seria que a geometria de payoff (uma decisão sobre o alvo de rotulagem) é conceitualmente ortogonal ao contrato de dado entre estágios (o que este brief cobre) — dá pra desenhar a arquitetura de conexão sem saber ainda se TP=2.0 ou TP=1.8 é melhor, porque o CONTRATO (schema, causalidade, quem consome o quê) não muda com o valor do multiplicador. Mas a honestidade completa: se o sweep mudar a taxa de acerto estruturalmente (breakeven WR é função direta desse número, citado no próprio `constants.yaml`), isso pode mudar QUANTAS linhas sobrevivem à seleção — então não é zero-risco deixar pra depois. Recomendação pro auditor: tratar como paralelo, não bloqueante, mas sinalizar se achar razão pra discordar dessa priorização.

**P: A mudança "todas as features canônicas" não contradiz o próprio princípio do projeto de que o teto de features deve ser medido, nunca estipulado?**

R: Ao contrário — é mais consistente com esse princípio do que a política antiga. A regra invariável do projeto (uma das 5 restrições estruturais declaradas) é "teto de features = medido, nunca estipulado". A política antiga (T1 fixo em 10) era, ironicamente, uma estipulação — um portão humano decidindo hoje uma cardinalidade de amanhã. A política nova deixa o próprio processo de treino (regularização, importância nativa) medir o que sobrevive, em vez de fixar um número a priori. O risco genuíno não é filosófico, é prático: escala. O mecanismo de corte de redundância que funcionava pra 10 features (correlação de Spearman pareada > 0,70 → a de menor importância sai) não escala trivialmente pra ~92 — com esse volume, o número de pares a checar cresce quadraticamente e a interpretação de "qual sai" fica ambígua quando 3+ features formam um cluster mutuamente correlacionado (par a par pode não capturar isso). Essa é uma pergunta real e aberta que o brief já lista (decisão pendente #8) — vale aprofundamento técnico do auditor.

**P: Grupo F (microestrutura) foi excluído por quebra de definição real (RPI oculto) — isso afeta só o Alpha, ou também alguma feature usada em Regime ou em custo de execução (ex. `E27f_cost_atr_ratio`, que usa "custo round-trip")?**

R: **Não verificado com confiança neste momento — sinalizado honestamente, não inventado.** `E27f_cost_atr_ratio` deriva de `custo_round_trip_bps`, que PODE depender de spread real (que seria afetado pela quebra RPI) ou pode vir de uma fonte de custo diferente (taxa de exchange fixa + slippage estimado por outro caminho). O brief não verificou essa dependência a fundo. Recomenda-se que o auditor trate isso como pergunta em aberto, não como fato assumido em qualquer direção.

### Sobre os candidatos de regime (§2.3-2.4 do brief)

**P: Jump Model é "não-causal dentro do fold" — isso não deveria ter reprovado ele sumariamente, sem precisar de mais nenhuma análise?**

R: A não-causalidade é real mas **confinada estritamente ao fold de teste** — o `.predict()` faz traceback só dentro do array daquele fold específico, nunca cruza a fronteira treino/teste nem cruza folds diferentes. Isso é um compromisso metodológico já documentado e testado no próprio código do projeto (não uma descoberta nova), aceito como escopo limitado — diferente de um vazamento genuíno que contaminaria a avaliação. A razão real da exclusão do Jump Model do Estudo 1 não foi essa não-causalidade sozinha — foi a COMBINAÇÃO de 3 problemas independentes: (1) essa não-causalidade confinada, (2) poder estatístico praticamente inexistente (mediana de 4 episódios por célula, mínimo 1, em 100% de 102 células testadas), e (3) o hiperparâmetro de penalidade calibrado numa única fatia de BTC, nunca retestado em outros ativos, com colapso a 1 estado em 25-29% das células — sintoma consistente com hiperparâmetro mal-calibrado, não necessariamente ausência real de regime. Nenhum dos 3 sozinho seria motivo suficiente de exclusão; os 3 juntos, sim.

**P: `hazard_lambda` do BOCPD foi calibrado sobre o histórico completo do BTC, que inclui as janelas de teste — isso não invalida os resultados do BOCPD no estudo?**

R: É uma sobreposição temporal real e já sinalizada como caveat legítimo — mas é estruturalmente diferente de outcome-hacking. A calibração usou uma estatística ESTRUTURAL (duração mediana de segmento medida no classificador BASELINE, um método diferente do BOCPD) como alvo, não olhou separação, heterogeneidade nem p-valor de nenhum candidato antes de fixar o valor. Isso afasta o cenário mais grave (ajustar o hiperparâmetro até o resultado favorito aparecer), mas não elimina completamente a preocupação de que o histórico usado pra calibrar "sabe" sobre o período de teste de um jeito que um walk-forward puro não permitiria. Recomendação já registrada no projeto (não executada ainda): um teste de sensibilidade barato — recomputar a calibração usando só dado anterior a cada janela de teste, e verificar se o valor de hazard_lambda escolhido seria o mesmo. Se sim, o caveat vira nota de rodapé; se não, é achado real.

### Sobre a Trilha B / achados de arquitetura (§5 do brief)

**P: Por que confiar num processo de "auditoria adversarial interna" — mesmo repetido 4 vezes — se são todos agentes da mesma família de modelo revisando o próprio trabalho?**

R: É exatamente por isso que este brief está sendo comissionado — o processo interno é necessário mas reconhecidamente insuficiente. Ele resolveu bem a pergunta "esse mecanismo específico, do jeito que está escrito, tem um furo lógico ou técnico?" (achou 5 furos reais em 4 rodadas, todos genuínos, nenhum forçado pra preencher espaço). O que ele estruturalmente não resolve bem é "existe um enquadramento inteiro diferente que ninguém dessa família de modelo considerou?" — viés de correlação de treino, não de raciocínio superficial. O pedido explícito ao auditor externo (§5.3 do brief) é focar nisso, não em reencontrar os mesmos 5 furos de novo.

**P: O orçamento de rate-limit (prioridade de execução vs. leitura de posição) foi só verificado por leitura de código, ou testado sob carga real?**

R: Só por leitura de código e lógica estática — não existe hoje nenhuma execução real (`place_order` continua sem implementação), então não há tráfego de produção real pra testar esse invariante sob rajada de verdade. É um risco a documentar explicitamente: o desenho está correto NO PAPEL (confirmado por releitura repetida do código do orçamento de rate-limit), mas "correto no papel, nunca exercitado sob carga real" é uma categoria de risco por si só — vale o auditor considerar se recomenda algum teste de carga simulado antes da primeira operação real, mesmo que a arquitetura de execução ainda não exista pra rodar isso hoje.

### Sobre decisões pendentes e fronteiras sem desenho (§6-7 do brief)

**P: Por que desenhar o mecanismo do gatilho de proteção (encurtar `time_stop` sob regime de stress) antes mesmo de a camada de Execução existir? Não é desenhar em cima de areia?**

R: A lógica de sequenciamento aqui é deliberada: o MECANISMO (a regra de decisão — o que aciona, o que ele faz) é barato de desenhar agora e não depende de código de execução pronto pra ser especificado corretamente. O que de fato depende da Execução é só a IMPLEMENTAÇÃO final (como cancelar/reenviar uma ordem real). Adiar o desenho da regra até a Execução existir arriscaria descobrir tarde que a regra em si tinha um problema conceitual (como aconteceu com a primeira versão, que propunha apertar o stop — refutada por pesquisa de mercado antes de qualquer linha de código de execução ser escrita). A ressalva honesta: ainda existe risco real de retrabalho se, quando a Execução for implementada, surgir uma restrição técnica não antecipada aqui. É uma aposta calculada, não uma garantia.

**P: Como um revisor sem acesso ao repositório propõe um "contrato de dado concreto" pra uma fronteira (ex. Split→Learner) sem ter visto o código de nenhum dos dois lados?**

R: Boa objeção, e o pedido não é "adivinhe o código real" — é "aplique prática padrão de engenharia de ML pra esse TIPO de fronteira, informado pelas restrições específicas já dadas neste material" (causalidade estrita, pesos de unicidade, embargo temporal, ~92 features candidatas, 3 resoluções × 5 símbolos como espaço de busca). Isso é consultoria de desenho a partir de padrões conhecidos e das restrições declaradas, não auditoria de código que o revisor nunca viu. Se o revisor achar que não tem informação suficiente pra propor algo concreto numa fronteira específica, a resposta certa é dizer exatamente isso — "preciso saber X sobre o lado esquerdo/direito desta fronteira antes de propor" — não inventar um contrato sem base.

---

## 5. Guia de calibração — o que diferencia uma resposta forte de uma fraca

**Fraca**: "Essa área parece bem estruturada, só sugiro mais testes." — não diz o quê, não diz por quê, não é acionável.

**Forte** (padrão real já produzido neste processo, pra referência): "A regra de contagem de N para seleção de linha usa o resultado da rodada como critério — isso é circular porque o `n_trials` de que a linha depende pra calcular seu próprio DSR só é conhecido depois que a rodada inteira (incluindo linhas avaliadas depois dela) termina. O critério correto, já declarado no próprio ledger do projeto, é estrutural (exige backtest novo por candidata), não depende de quantas acabam promovidas." — isso identifica o mecanismo exato, explica a consequência concreta, e cita a fonte de verdade que resolve.

Peça isso ao revisor de forma explícita, se ele hesitar: "não preciso de opinião geral, preciso do mecanismo específico que quebra ou que falta, com a consequência concreta."

---

## 6. Protocolo de pesquisa — RAG Vetorial adaptado (passo a passo)

Pra qualquer recomendação apoiada em literatura/prática de mercado (§6 e §7 do brief principal, e boa parte das perguntas da seção 4 acima), siga esta disciplina antes de escrever a conclusão. Não é burocracia — é o que separa "citei uma fonte" de "a fonte realmente sustenta o que eu disse". A base é o mesmo princípio de um pipeline de RAG vetorial (retrieval-augmented generation) — decomposição de query, recuperação ampla antes de gerar, reranking por relevância, fundamentação explícita contra alucinação — traduzido de infraestrutura de banco vetorial pra disciplina manual de busca, porque você não necessariamente tem um índice vetorial próprio rodando, mas pode seguir a MESMA disciplina com as ferramentas de busca que tiver.

1. **Decomponha antes de buscar.** Quebre a pergunta de auditoria em 2-5 sub-perguntas específicas e pesquisáveis isoladamente. Não busque "como gerenciar risco de posições concorrentes em cripto" de uma vez — separe em "cap de posições simultâneas por correlação de portfólio", "prioridade de rate-limit sob rajada de execução em exchange de derivativos", "prática de kill-switch em perpetual futures".

2. **Expanda cada sub-pergunta em 2-3 formulações diferentes** antes de buscar (paráfrase, termo técnico alternativo, inglês e português quando fizer sentido). Vocabulário diferente encontra fontes diferentes — "position sizing crypto futures" não retorna as mesmas fontes que "risk budget concurrent positions perpetual futures" ou "portfolio margin correlated positions".

3. **Recupere amplo antes de sintetizar.** Busque múltiplas fontes por sub-pergunta ANTES de escrever qualquer conclusão. Não aceite a primeira fonte plausível — mínimo 3-4 buscas por sub-pergunta relevante, mesmo padrão já usado nas auditorias anteriores deste projeto (a que refutou "apertar o stop sob volatilidade" citou 3 fontes independentes antes de concluir).

4. **Rerankeie por relevância e qualidade, não por ordem de chegada.** Priorize: (a) relevância semântica direta à sub-pergunta, não tangencial; (b) qualidade da fonte — paper peer-reviewed/documentação oficial de exchange > blog técnico sério com autor identificável > fórum/opinião anônima; (c) recência, quando o assunto muda rápido (regra de exchange, versão de biblioteca, prática de mercado corrente).

5. **Fundamente cada afirmação num trecho específico recuperado, não em memória geral do modelo.** Se a busca não achou nada que sustente um ponto, marque isso explicitamente ("não encontrei base direta pra isso") — não preencha com plausibilidade. É exatamente a mesma disciplina que os documentos deste processo já seguem: "não verificado com confiança" é resposta válida, "provavelmente está tudo bem" não é.

6. **Cite com âncora específica, não só a URL.** Padrão já usado nas auditorias anteriores deste projeto: URL + a frase/trecho exato que sustenta o ponto — nunca "segundo estudos, é comum..." sem apontar qual estudo, onde.

7. **Triangule — cruze fontes independentes antes de concluir.** Se 2+ fontes independentes convergem, isso é sinal mais forte; diga isso explicitamente. Se divergem, reporte a divergência — não escolha uma versão silenciosamente e esconda o desacordo.

8. **Passo corretivo, antes de desistir.** Se a primeira rodada de busca voltou fraca (fontes escassas, conflitantes, ou tangenciais), reformule a sub-pergunta e busque de novo antes de declarar "literatura escassa". Só declare "sem base" depois de pelo menos 1 reformulação de verdade, não na primeira tentativa.

**Fontes desta pesquisa (metodologia RAG em si, não do domínio quant):**
- [9 advanced RAG techniques to know & how to implement them — Meilisearch](https://www.meilisearch.com/blog/rag-techniques)
- [Advanced RAG techniques for high-performance LLM applications — Neo4j](https://neo4j.com/blog/genai/advanced-rag-techniques/)
- [Citation-Aware RAG: Fine Grained Citations in Retrieval and Response Synthesis — Tensorlake](https://www.tensorlake.ai/blog/rag-citations)
- [Best Practices for Implementing RAG Systems in Production — Unstructured](https://unstructured.io/insights/rag-systems-best-practices-unstructured-data-pipeline)
- [RAG in 2026: A Practical Blueprint for Retrieval-Augmented Generation — DEV Community](https://dev.to/suraj_khaitan_f893c243958/-rag-in-2026-a-practical-blueprint-for-retrieval-augmented-generation-16pp)

---

## 7. Índice cruzado — referência rápida

| Assunto | Seção do brief | Status |
|---|---|---|
| Mandato de seleção offline | §1 | Corrigido nesta sessão |
| Geometria de payoff (TP/SL/horizonte) | §2.1 | `ASSUMED`, sweep pendente |
| Política de features (todas canônicas) | §2.2 | Decisão registrada, não implementada em código |
| Matemática dos 4 candidatos de regime | §2.3 | Fechado, Trilha A |
| Resultado nulo da Trilha A | §2.4 | Fechado |
| Cadeia de estágios / papéis do regime | §3 | Estrutural, editável |
| Trilha A completa (redesenho/fix/habilitação/rejeitado) | §4 | Fechado, documento próprio arquivado |
| Descoberta dos 10 gaps de arquitetura | §5.1 | Fechado |
| As 4 rodadas de contestação adversarial | §5.2 | Fechado |
| As 4 propostas aprovadas — pedido de validação | §5.3 | **Aberto pro auditor** |
| 9 decisões pendentes | §6 | **Aberto pro auditor** |
| 7 fronteiras sem desenho | §7 | **Aberto pro auditor — foco principal** |
| Cadência da rodada de seleção de linha | (não coberto no brief) | **Achado deste companion — falta até virar item da lista** |
| Regra de priorização entre linhas aprovadas concorrentes | (não coberto no brief) | **Achado deste companion — falta até virar item da lista** |
