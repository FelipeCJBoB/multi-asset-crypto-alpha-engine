# Parecer de auditoria externa — AG-114 / AG-119 / AG-118

**Data:** 2026-08-20
**Escopo:** revisão cética do brief `brief_auditoria_externa_2026-08-20_gate_efficiency_ag118.md`
**Base:** exclusivamente o documento fornecido. Onde a conclusão depende de código ou dado não incluído, isso está marcado como **[verificar]** — são condicionais, não afirmações.

---

## 0. Veredito em uma página

O brief é honesto, e a disciplina anti-HARKing é real e visível. O problema não é integridade — é **poder de medição**.

A conclusão central do §4.6 ("estrutura genuína, sem utilidade econômica demonstrada") **não está sustentada pela medição apresentada**, e por um motivo específico: pelo menos três das escolhas de instrumentação do AG-118 são, por construção, cegas ao efeito que o gate produziria se ele existisse. `lift ≈ 1` é o resultado esperado dessas escolhas mesmo num mundo onde o gate funciona.

Além disso, a seleção do AG-114 é **menos robusta do que o brief afirma**: quem escolheu `hmm_gaussian_k4_v1` não foi a métrica primária, foi o teto do Gate 1. Sob a faixa mais ampla que a própria pergunta 1 propõe, o vencedor muda.

Recomendação ao §8: **nem (a) nem (b) puro — uma variante de (c)**, detalhada no §4. Não aceitar `lift ≈ 1` como veredito, e não partir direto para as perguntas 7/8 antes de rodar um diagnóstico de 20 minutos que pode encerrar a investigação inteira (§4.1, teste D1).

---

## 1. Quatro achados que **não** estão na lista de 12

Esta é a parte do parecer que justifica uma revisão externa. As 12 perguntas do §7 são boas, mas nenhuma delas cobre o seguinte.

### A. O gate é colinear com a normalização de risco que o sistema já aplica — e a métrica de tail loss é cega a isso por construção

Esta é a observação mais importante do parecer.

`p05_return_atr` é o percentil 5 de `ret_net / atr_at_t0`. O denominador é o ATR no momento da entrada. **[verificar]** Se as barreiras do triple-barrier também são escaladas por ATR em t0 — o que o nome `atr_at_t0` e a existência de `ret_net/atr` como unidade padrão do projeto sugerem fortemente —, então:

> `ret_net / atr_at_t0` é aproximadamente limitado por construção em ±k, onde k é a largura da barreira em ATRs, **independentemente do regime**.

A volatilidade foi dividida fora da métrica. Um estado de "vol alta" não pode aparecer como "tail loss pior" numa unidade que já dividiu pela vol. Medir se um detector de volatilidade prevê risco de cauda **em unidades de volatilidade** é próximo de uma tautologia com resposta garantida ≈ nula.

Isso não é só uma ressalva — **explica as três anomalias do §4.5 simultaneamente e com um único mecanismo**:

| observação do brief | explicação sob barreiras ATR-escaladas + reversão à média da vol |
|---|---|
| `lift` ≈ 1 | o bucket de stress ≈ "ATR alto em t0", que o sizing/barreira já compensa |
| tail loss **menos** negativa no stress (−1,65 vs −1,80) | barreira larga em termos absolutos + vol revertendo → **menos overshoot além da barreira** |
| holding time **maior** no stress (20 vs 17 barras) | barreira larga + vol caindo → preço demora mais a alcançá-la |

As duas "anomalias" que o brief classifica como "direção oposta do esperado" são, sob essa hipótese, **exatamente a direção esperada**. Não são ruído nem contra-evidência: são a assinatura de um sistema que já neutraliza volatilidade a montante.

**Consequência para a decisão:** a pergunta correta nunca foi "regime prevê risco?". É **"regime prevê risco *além do que o ATR em t0 já captura*?"**. O AG-118 não respondeu essa pergunta — respondeu a primeira, numa unidade que embute a resposta.

### B. Quem selecionou k=4 foi o teto do Gate 1, não a métrica primária — e há um empate não reconhecido em R1

Os I² da §2.1, lado a lado:

| resolução | k=2 | k=3 | k=4 |
|---|---:|---:|---:|
| R1 | **97,8** | 97,4 | 97,4 |
| R2 | **95,3** | 94,5 | 95,0 |
| R3 | 91,7 | 85,7 | **91,8** |

Dois problemas independentes:

1. **k=2 venceria k=4 em R1 e R2 na métrica primária.** k=2 só foi excluído pelo Gate 1 (occupancy 34,1–39,5% contra teto de 40%). O brief admite que k=2 "falha ou fica no limite em toda a faixa" — ou seja, o resultado depende de o teto ter sido fixado em 40% e não em 45%. A pergunta 1 do §7 pergunta se a faixa é ampla o suficiente; **a resposta é não, e a direção importa**: a extremidade superior da faixa é literalmente o que decide o vencedor. A robustez alegada no §2.2 ("passa com folga") descreve k=3 e k=4, mas não descreve a *decisão*, que é marginal.

2. **Em R1, k=3 e k=4 estão empatados na precisão reportada (97,4 vs 97,4).** O §2.3 afirma que "k=4 vence k=3 nas 3 resoluções" — isso não é verdade para R1 conforme a própria tabela. E o Gate 3 (detection delay) foi declarado desnecessário porque "não houve empate", sendo que **"empate" nunca foi definido na regra travada a priori** (§1: "só entra se 2+ candidatos empatarem", sem critério numérico). Na prática, o Gate 3 foi pulado por julgamento, não por regra — o que é a classe de decisão que a disciplina anti-HARKing existe para prevenir.

Nada disso sugere má-fé. Sugere que a regra do AG-114 estava **sub-especificada no momento do travamento**, em dois pontos que acabaram sendo os únicos que importaram.

### C. Occupancy foi medida em espaço de barras; o gate opera em espaço de eventos — e a diferença é ~2x

Gate 1 mediu occupancy do estado de stress em **10,5–12,7%** (mediana, dollar-bar). O AG-118 encontra o bucket de stress em **2–9% dos SL e dos TP** (labels em grade de 15m-calendário).

Isso não é inconsistência — é a consequência esperada do relógio. Dollar bars são amostradas por volume: períodos de stress geram **mais barras por unidade de tempo de calendário**. Occupancy-em-barras portanto **superestima** a cobertura em tempo de calendário, que é onde os labels vivem.

Duas implicações:

- O Gate 1 mediu a coisa certa para "o estado é degenerado?" e a coisa errada para "o gate tem mordida econômica?". O candidato aprovado com a maior folga no Gate 1 (k=4, o de menor occupancy) é também o de **menor cobertura possível** — ~5% dos eventos. Um efeito econômico real em 5% dos eventos é pequeno em termos agregados mesmo quando o gate está certo.
- k=3 (18–21% em barras) e k=2 (34–39%) cobririam ~2x e ~4x mais eventos. **O AG-118 nunca foi rodado neles.** Se os `RawLabels` de k=2/k=3 foram persistidos na mesma rodada, esse teste tem custo zero de fit.

### D. Não há nenhuma quantificação de incerteza sobre `lift` — e a leitura "sem padrão" pode ser exatamente o contrário

O §4.5 reporta 30 estimativas pontuais e conclui "sem padrão consistente" por inspeção visual. Sem intervalo, essa leitura não é sustentável nas duas direções:

- **Pelo n nominal**, `lift` de 0,79 e 1,40 estão a muitos erros-padrão de 1,0. Com `n_sl ≈ 20.000` e taxa de captura ≈ 5%, o erro-padrão relativo do `lift` fica na casa de ~5%. Isso faria de 1,40 um desvio massivo, não ruído.
- **Mas o n nominal está errado**, e para mais: labels de triple-barrier em grade de 15m se sobrepõem pesadamente no tempo, então a amostra efetiva é uma fração pequena da nominal (o problema clássico de unicidade de labels sobrepostos).

O ponto do auditor não é qual dos dois vence — é que **o brief não sabe, e o dado para saber já existe**. A leitura honesta do §4.5 hoje não é "sinal fraco"; é **"heterogeneidade transversal grande e não explicada, com incerteza não medida"**. E heterogeneidade grande não explicada é precisamente o que se espera quando o efeito é dependente de lado e/ou de janela e está sendo agregado por cima (perguntas 7 e 8 — que ficam, por esse motivo, mais fortes do que o brief as trata).

O mesmo vale para o I² do AG-114: escolher k=4 sobre k=3 por 95,0 vs 94,5 sem intervalo é uma decisão sem base mensurável. E os p-valores de permutação estão censurados em 0,001 (piso de 1.000 permutações), então não carregam informação de ranking — o que o brief acerta ao não usar, mas vale registrar.

---

## 2. Respostas às 12 perguntas do §7

### Sobre AG-114 e os limiares

**1. A faixa 25/33/40% é ampla o suficiente?**
**Não, e o problema é a extremidade superior.** Ver §1.B: a 45% k=2 entra e vence em 2 de 3 resoluções na métrica primária. A faixa 15–50% que a própria pergunta propõe **mudaria a conclusão**. A verificação de robustez feita testa se k=4 sobrevive; não testa se k=4 continua vencendo — são coisas diferentes, e só a segunda importa.

**2. O Gate 1 é fiel a "medir contra o baseline"?**
**Não, e a reinterpretação foi necessária para o exercício produzir qualquer vencedor.** Baseline em ~3%; um limiar literalmente ancorado nele (digamos 3× = ~9%) **desqualificaria k=4 (10,5–12,7%) e k=3 (18–21,5%) — todos os HMM**. Isso é mais informativo do que "a reinterpretação é aceitável?": significa que a regra travada, na sua leitura literal, não tinha nenhum candidato viável. Uma regra a priori que só produz vencedor sob reinterpretação é uma regra que estava sub-especificada, e isso merece registro formal no log de gaps — não como violação, mas como aprendizado de processo sobre o que "travar a priori" precisa incluir (a definição operacional, não só a métrica).

**3. Mediana-de-medianas trata as 5 janelas como igualmente informativas?**
Pior que isso. **Mediana de 5 valores é o 3º — dois valores podem ser completamente não-influentes.** Se LUNA e FTX (as janelas BTC-only, e as únicas de choque abrupto) forem extremas em qualquer direção, o agregador as descarta por construção. Para um gate de risco, cujo valor plausivelmente se concentra em crise, isso é próximo do pior agregador possível. Não é questão de peso — é de o estimador ser insensível às observações mais informativas.

**4. Baseline perder significância em R3 é evidência real ou artefato?**
A explicação do brief (threshold fixo perde poder sob menos barras) é plausível, mas **há um confundidor não descartado, e ele é decisivo**: **[verificar]** o HMM é ajustado *in-sample* na mesma janela em que é avaliado? O §4.2 confirma que o *decode* é causal (`p(z_t|y_{1:t})`), mas causalidade de decodificação não é causalidade de *fit* — se os parâmetros viram a janela inteira, o HMM tem uma vantagem que o baseline de threshold fixo não tem, e **essa vantagem cresce justamente onde o dado é mais escasso e ruidoso (R3)**. Vantagem que aumenta com a escassez de dado é a assinatura de overfitting, não de superioridade.

Teste que separa as duas hipóteses: ajustar o HMM na janela A, decodificar na janela B, remedir o I² em R3. Se a vantagem sobrevive, é genuína. Sem esse teste, o §2.1 não permite concluir "HMM é melhor" — permite concluir "HMM é mais adaptativo", que é compatível com ambas.

### Sobre Jump Model / Condição C

**5 e 6 (λ=0,02), respondidas juntas.**
Discordo do enquadramento das duas. **Não houve violação de B20** — a escolha foi anterior ao resultado. Mas também **não houve, na prática, nenhuma regra de seleção**: o critério era "o mais parcimonioso que ainda é genuíno", e o §3 reporta que *todo* o grid produziu ≥2-3 estados genuínos para os não-BTC. A restrição nunca foi ativa, então o critério degenerou para "pegue o extremo do grid". λ nunca foi otimizado; a **borda da grade** foi a escolha, e uma grade sem máximo confirmado (pergunta 5) torna essa borda arbitrária.

O problema real é anterior e mais simples: **`n_episodes` é uma função direta e previsível de λ**. Que λ=0,02 produziria 1–8 episódios por célula era calculável *antes* de rodar. Isso não é HARKing — é **ausência de análise de poder no desenho**, que é um defeito mais mundano e mais corrigível.

Saída limpa, que evita transformar a correção em escolha pós-hoc: **pré-registrar agora um critério de poder mínimo** (ex.: `n_episodes ≥ 30` por célula, ou o número que o teste de permutação exige para não ficar censurado) e selecionar mecanicamente o **maior λ que o satisfaz**. É uma regra enunciável hoje, aplicável sem olhar o resultado, e que teria rejeitado λ=0,02 no desenho.

### Sobre AG-118 e o `lift`

**7. Calibrar o gate por lado?**
Sim para a investigação, **não para o enquadramento**. `identify_stress_state_by_volatility` usa só volatilidade realizada — é agnóstico a lado *por construção*, e isso está correto: o regime é propriedade do mercado, não da posição. Escolher um estado de stress diferente para long e short seria conceitualmente incoerente.

O que legitimamente varia por lado é a **ação do gate**, não sua definição: bloquear short no stress e não bloquear long, por exemplo. E o §4.5 já mostra a assinatura disso — R1/BTC tem `lift` 0,88 no short e 1,11 no long, **em direções opostas dentro do mesmo símbolo e resolução**. Isso é barato de abrir (`GateEfficiencySymbolDetail` já é por side) e deve ser aberto. Mas ver §1.D: sem intervalo, 0,88 vs 1,11 ainda pode ser ruído.

**8. O pooling entre janelas esconde heterogeneidade?**
Sim, e o defeito é mais severo do que a pergunta supõe. LUNA e FTX são **BTC-only**. Portanto, para SOL/XRP/BNB/ETH, o `lift` reportado é calculado **inteiramente a partir das 3 janelas não-crise** — a hipótese "o gate funciona só em crise" é **literalmente não-testável em 4 dos 5 símbolos** no desenho atual. E para BTC, o pooling é *por contagem*, então as janelas de crise (curtas) são dominadas pelas janelas longas.

Ou seja: a hipótese que o §7.8 levanta como possibilidade é, no dado atual, **estruturalmente invisível**. Isso sozinho impede aceitar (a).

**9. Tail loss levemente melhor no stress: ruído ou sinal?**
**Nenhum dos dois — é provavelmente artefato de normalização.** Ver §1.A. A resposta correta não vem de um teste de significância na métrica atual; vem de trocar a métrica.

Além disso, mesmo mantendo a métrica, o teste proposto está mal-especificado: comparar mediana de 100 células contra mediana de 298 células ignora que as células são pareadas (o mesmo símbolo/janela/lado/resolução aparece nos dois buckets) e que cada `p05` de célula tem ruído próprio proporcional ao seu n. Uma comparação **pareada dentro de (símbolo, janela, lado, resolução)** é dramaticamente mais poderosa e custa o mesmo.

**10. p05 vs p01?**
Sim, e p01 é a escolha mais informativa aqui **por um motivo específico**. Pelas contagens do §4.5, SL é a barreira majoritária (ex.: 25.096 SL vs 18.290 TP). Então `p05` está bem dentro da massa de SL e mede essencialmente **overshoot além da barreira** — que é justamente a quantidade que barreiras ATR-escaladas mais comprimem. p01 sonda mais fundo na cauda de gap/salto, onde o efeito de regime, se existir, sobrevive à normalização. **Recomendo p01 e p005 além de p05.**

**11. Proveniência dos `RawLabels`?**
**Não é aceitável, e o argumento "é `experiments/`" não se aplica aqui.** O critério não é o diretório — é o uso. O §8 pede uma recomendação sobre desligar ou ligar um gate de risco real com base nesses parquets. No momento em que um artefato experimental vira insumo de decisão de risco, ele herda o requisito de proveniência.

O custo do conserto é trivial e desproporcionalmente menor que o risco: gravar no `gate_efficiency_report.json` o hash de conteúdo dos parquets consumidos + o `config_hash`/timestamp da rodada AG-114 de origem. Sem isso, daqui a três meses o relatório é irreproduzível e não auditável — e a decisão que ele sustenta fica sem lastro verificável.

### Sobre hierarquia de documentos

**12. AG-121 muda urgência ou justificativa?**
Muda a **justificativa**, não a urgência — mas cria uma dívida de tipo diferente da que o brief descreve. Hoje o workaround (`identify_stress_state_by_volatility`) é correto e a produção não está bloqueada; a urgência real é baixa. O risco não é o bug, é a **armadilha latente**: existe em `src/regime/canonicalization.py` uma ordenação por retorno cujo nome (`canonical_id`) sugere uma semântica que ela não tem, e todo consumidor futuro precisa saber disso por tradição oral.

A mitigação certa não é a migração (que pode esperar pelo action item 3 do ADR-001) — é **tornar a armadilha inerte agora**: renomear o campo para explicitar o critério (`canonical_id_by_return`) ou adicionar uma asserção/docstring que falhe alto se alguém tratar a ordem como volatilidade. Custo de minutos, e remove a dependência de memória institucional.

Sobre "não decidir é decidir": concordo, e a resposta a "quanto tempo é aceitável" é **até o primeiro consumidor novo**, não uma data. Amarre a resolução ao gatilho, não ao calendário.

---

## 3. Validação do §4.6 (pedido 2 do §8)

**Refuto a leitura, mas não a honestidade dela.**

A afirmação "AG-114 e AG-118 tinham respostas diferentes, e isso foi medido, não decidido" está correta como descrição do processo. A inferência que o brief tira — que a estrutura genuína não se traduz em utilidade econômica — **não está suportada**, porque três dos instrumentos usados não conseguiriam mostrar o efeito nem se ele existisse:

1. tail loss e retorno em unidades de ATR, com barreiras ATR-escaladas **[verificar]** — cego por construção (§1.A);
2. pooling por contagem entre janelas, com as janelas de crise ausentes em 4 de 5 símbolos — a hipótese mais plausível é invisível (§2.8);
3. cobertura de ~5% dos eventos, com o candidato de menor mordida econômica entre os aprovados, e k=2/k=3 nunca testados (§1.C).

Sobre a pergunta da literatura: sim, o padrão "estrutura estatística forte, valor econômico fraco" é comum e bem documentado em regime-switching aplicado a risco — modelos que ajustam bem in-sample frequentemente não sobrevivem à conversão em decisão, sobretudo depois de custos. **Mas invocar esse padrão aqui seria confortável demais**: ele explicaria um nulo *bem medido*, e este nulo ainda não é bem medido. Aceitar a explicação da literatura agora é encerrar a investigação pelo argumento mais lisonjeiro disponível — exatamente o tipo de movimento que o resto do brief evita com rigor. (Se quiser, posso levantar as referências específicas dessa literatura, incluindo verificar Cortese/Kolm/Lindström 2023 conforme citado no §3.)

**Reformulação que eu defenderia:** o AG-118 não mostra que regime é inútil como gate. Mostra que **regime, medido em unidades já normalizadas por volatilidade, não adiciona nada além do ATR** — o que é uma hipótese muito mais forte, muito mais defensável e diretamente testável (§4.1).

---

## 4. Recomendação (pedido 3 do §8)

**Nem (a) nem (b) — variante de (c).**

Contra (a): três instrumentos incapazes de detectar o efeito não produzem um veredito, produzem um não-resultado. Contra (b) puro: as perguntas 7 e 8 são boas, mas caras de investigar bem, e há um teste anterior a elas que pode **encerrar a questão inteira em qualquer direção** por uma fração do custo.

### 4.1 Diagnósticos ordenados — todos sobre dado já existente, zero refits

**D1 — Tabulação cruzada `is_stress_bucket` × decil de `atr_at_t0`. Faça isto primeiro.**
Se o bucket de stress for aproximadamente "decis superiores de ATR em t0", então o gate é colinear com a normalização que o sistema já aplica, e a conclusão correta muda de *"regime não funciona"* para *"regime é redundante com ATR nesta configuração"* — defensável, publicável internamente, e encerra a linha de investigação com base sólida. Se **não** for colinear, então existe informação em regime que o ATR não tem, e todo o resto da fila passa a valer a pena. Um teste, dois desfechos úteis, custo de minutos.

**D2 — `lift` reaberto por janela, com LUNA/FTX separadas.**
Responde a pergunta 8 e determina se "o gate serve só em crise" é sequer testável neste dado. Reporte também `n` efetivo por janela.

**D3 — Intervalos de confiança em tudo.**
Bootstrap em bloco por janela (a maquinaria de permutação em bloco já existe) ou ponderação por unicidade de label. Sem isso, "0,79–1,40" não tem leitura — nem como nulo, nem como sinal (§1.D).

**D4 — Tail loss fora de unidades de ATR.**
Retorno bruto e/ou overshoot relativo à barreira, com p01/p005 além de p05, em comparação **pareada** dentro de (símbolo, janela, lado, resolução). Responde 9 e 10 corretamente.

**D5 — `lift` por lado mantido desagregado.** Barato, responde 7 (§2.7).

### 4.2 Reabertura parcial do AG-114 — independente e paralela

**R1 — Rodar o AG-118 em k=3 e, se os labels existirem, em k=2.** Custo próximo de zero se os `RawLabels` foram persistidos; um refit caso contrário. Justificativa em §1.C: cobrem ~2x e ~4x mais eventos, e k=2 vence k=4 na métrica primária em 2 de 3 resoluções. Testar o gate econômico só no candidato de menor cobertura é o pior desenho possível para detectar mordida econômica.

**R2 — Registrar formalmente os dois gaps de regra do §1.B**: (i) o teto de 40% do Gate 1 é load-bearing e a decisão não é robusta a ele; (ii) "empate" nunca foi definido, e R1 apresenta empate na precisão reportada, de modo que o Gate 3 foi pulado por julgamento. Correção estrutural para o futuro: toda regra travada a priori precisa incluir **definição operacional** (o que conta como empate, qual precisão), não só métrica e limiar.

**R3 — Confirmar se o fit do HMM é OOS ou in-sample** (§2.4). Se for in-sample, o §2.1 não sustenta "HMM > baseline" e o achado colateral do R3 precisa ser reescrito.

### 4.3 Correções de baixo custo, independentes de tudo acima

- Hash de proveniência da rodada AG-114 no `gate_efficiency_report.json` (§2.11).
- Renomear `canonical_id` ou adicionar guarda que falhe alto, tornando a armadilha do AG-121 inerte sem esperar a migração (§2.12).
- Pré-registrar o critério de poder mínimo para seleção de λ antes de qualquer novo teste do Jump Model (§2.5-6).

---

## 5. O que este parecer **não** contesta

Registro explícito para não confundir ceticismo com rejeição:

- A separação AG-114 / AG-118 (estrutura vs. economia) é a decomposição certa, e fazer as duas perguntas separadamente foi acertado.
- Reportar `lift ≈ 1` sem suavização, sendo o resultado desconfortável, é o comportamento correto e é o motivo de esta auditoria ter matéria-prima com que trabalhar.
- A verificação de `decode_mode=filter` no código-fonte em vez de assumir conformidade (§4.2.3) é exatamente o padrão certo.
- A confirmação de que o Jump Model não destrona o vencedor, feita apesar de a contestação ter vindo do Manager, com o bug de `downside_deviation` achado e corrigido no caminho, é trabalho de boa fé.
- Deixar o limiar de "lift mínimo" sem fixar até existir dado real (§4.4) é a decisão certa e deve ser mantida — inclusive depois dos diagnósticos acima.

A crítica deste parecer é sobre instrumentação e especificação de regra. Não é sobre integridade do processo, que se sustenta.
