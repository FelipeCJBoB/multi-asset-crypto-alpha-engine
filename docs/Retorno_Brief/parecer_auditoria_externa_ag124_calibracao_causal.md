# Parecer de auditoria externa — recalibração causal do threshold dollar-bar (AG-124)

**Data:** 2026-08-21
**Escopo:** revisão do brief `brief_auditoria_externa_2026-08-21_calibracao_causal_dollar_bar_ag124.md`
**Base:** exclusivamente o documento fornecido. Onde a conclusão depende de código não incluído, está marcado **[verificar]**.

---

## 0. Veredito

**O vazamento é real e a correção é necessária.** Threshold de barras de janeiro/2020 calibrado com volume observado até 2026, reparticionando o conteúdo das barras — isso é forward-looking no sentido estrito, não deriva de densidade. Essa parte não tem contestação.

**A escolha `7/7` não está bem sustentada pela medição — mas por um motivo diferente do que o brief supõe.** O argumento de sazonalidade semanal está correto e restringe genuinamente um dos dois parâmetros. O erro é aplicá-lo aos dois: **a balança de dia-da-semana é uma restrição sobre `trailing_window_days`, não sobre `cadence_days`.** Tendo amarrado os dois, o time importou uma restrição de 7 dias para o parâmetro que o próprio achado 1 diz que deveria ser o mais curto possível.

**Recomendação: não (a).** Existe um defeito de desenho que precisa ser corrigido *antes* de reprocessar (§3), duas verificações que podem inverter o ranking e custam minutos (§2), e uma checagem operacional pendente que é bloqueante (§4.5). Detalhamento e ordem no §5.

---

## 1. O que a medição de fato sustenta

### 1.1 O experimento mais bem controlado do brief não está sinalizado como tal

A série **7 → 14 → 21** mantém a balança de dia-da-semana **constante por construção** (todos são múltiplos exatos do ciclo) e varia só o comprimento da janela. É a única comparação limpa do documento, e o resultado é inequívoco:

| | 7d | 14d | 21d |
|---|---:|---:|---:|
| BTC | 16,20 | 17,08 | 18,33 |
| ETH | 16,52 | 17,83 | 18,81 |
| BNB | 20,28 | 24,20 | 27,50 |
| XRP | 21,81 | 27,27 | 32,92 |
| SOL | 17,99 | 21,84 | 21,61 |

Monótono crescente em 4 de 5 símbolos, com aliasing controlado. **O achado 1 (deriva secular) está bem identificado** e merece mais confiança do que o brief lhe dá. Janela mais longa é pior, e isso não é artefato de calendário.

### 1.2 A série 1 → 2 → 4 → 7, ao contrário, confunde dois fatores

Ali o comprimento da janela varia **junto** com a balança de dia-da-semana. Não há como separar "mais curto é melhor" de "múltiplo de 7 é melhor" dentro dessa série — os dois efeitos apontam em direções opostas e a soma é o que se observa.

E há um buraco decisivo no grid: **não existe nenhum ponto não-múltiplo-de-7 entre 4 e 14.** A afirmação "7 é um mínimo local" tem como vizinhos testados o 4 (que também não é balanceado, e é mais curto) e o 14 (que é balanceado, e é mais longo). Nenhum dos dois isola a hipótese.

### 1.3 Lida ao pé da letra, a métrica recomenda W=1, não W=7

| | W=1 | W=7 | Δ |
|---|---:|---:|---:|
| BTC | 16,42 | 16,20 | −0,22 |
| ETH | 16,32 | **16,52** | **+0,20** |
| SOL | 11,64 | **17,99** | **+6,35** |
| BNB | 14,21 | **20,28** | **+6,07** |
| XRP | 15,50 | **21,81** | **+6,31** |

W=1 vence claramente em 3 símbolos, vence por margem residual em ETH, e perde para W=7 por 0,22pp apenas em BTC. A frase do §4 — "não é *mais só* a janela empiricamente melhor testada" — pressupõe que 7 era a melhor empiricamente. **Não era.** W=7 é escolhido *apesar* da métrica agregada, não por causa dela.

Isso não invalida a escolha. Invalida a *justificativa dupla*. E força a pergunta certa: se o argumento é estrutural, ele precisa se sustentar sozinho — o que ele quase faz, mas não para os dois parâmetros (§2.3).

---

## 2. Três problemas na métrica, em ordem de gravidade

### 2.1 O corte 2x/0,5x está posicionado exatamente em cima da moda da distribuição

Este é o problema mais sério do brief.

Sábado em BTC roda a **0,593x** da média. Sexta roda acima de 1,1x. Em W=1, a razão típica sábado/sexta é ≈ 0,59/1,15 ≈ **0,51** — a 2% do corte de 0,50.

O próprio brief confirma a consequência sem notar: sábado concentra **50,6%** de erro ruim em BTC sob W=1. Metade dos sábados cruza o corte, metade não. **Isso é a assinatura de um limiar binário assentado sobre o pico da distribuição** — o regime em que a estatística é maximamente instável.

Consequência direta: os 4,5 pontos percentuais que separam W=1, W=2, W=4 e W=7 em BTC/ETH — toda a evidência do "achado 2" — são produzidos por uma contagem cujo corte cai na região de maior densidade. Mover o corte para 0,45 ou 0,55 pode reordenar as linhas. **Nenhum teste de sensibilidade ao corte foi feito**, e ele custa minutos sobre os JSONs que já existem.

Registro que esta é a segunda decisão deste projeto, em duas auditorias, que se sustenta sobre um limiar binário não submetido a sweep — mesmo padrão do teto de 40% do Gate 1 no AG-114. Vale tratar como falha de processo recorrente, não como coincidência: **todo limiar de corte que separa candidatos precisa de sweep, pela mesma regra que o projeto já aplica a constante classe A.**

### 2.2 A contagem binária descarta quase toda a informação, e a informação descartada é a que responde à pergunta 1

`ratio = dollar_per_day real / calib_rate` é, por construção, **o multiplicador de barras-por-dia**. Ratio 2,0 significa o dobro das barras pretendidas naquele dia. Ou seja: a métrica já *é* a consequência física, e o time a está convertendo numa indicadora binária antes de olhar.

Isso responde à pergunta 1 do §8 sem precisar do pipeline downstream. Não é preciso "ancorar o limiar numa consequência real" — basta parar de aplicar o limiar e reportar a **distribuição** da razão, estratificada por dia-da-semana. A propriedade que barras de dólar existem para entregar é densidade de amostragem homogênea; qualquer estrutura de calendário sobrevivente em barras-por-dia é falha de calibração com efeito imediato a jusante.

Sobre a pergunta explícita do §9 (existe convenção na literatura?): **não conheço nenhuma convenção estabelecida para tolerância de erro de calibração em barras de volume/dólar** — o corte 2x/0,5x é razoável como heurística mas não tem lastro canônico. O que a literatura de barras por atividade estabelece é o *objetivo*: retornos mais próximos de IID, menor autocorrelação serial, menor curtose que barras de tempo. Isso dá três âncoras mensuráveis diretamente sobre as barras resultantes, sem pipeline nenhum:

1. variância de barras-por-dia, e especialmente **dispersão de barras-por-dia entre dias-da-semana**;
2. autocorrelação de retornos de barra;
3. curtose / normalidade dos retornos de barra.

Rodar cada candidato de janela contra essas três métricas converte uma métrica de processo numa de impacto, e é a única forma honesta de responder "1,8x importa ou é cosmético?".

### 2.3 O agregado esconde a diferença que realmente separa W=1 de W=7

Aqui está o argumento que eu defenderia no lugar do que o brief usa, e ele é mais forte:

W=1 e W=7 têm erro agregado quase idêntico em BTC. Mas o erro de W=1 é **sistemático e previsível**: segunda-feira 32,0% de erro ruim (calibrada pelo domingo), sábado 50,6% (calibrado pela sexta). O erro de W=7 é comparativamente homogêneo entre dias.

Erro agregado igual, estrutura de erro completamente diferente. E para um consumidor a jusante isso não é indiferente: **um viés de densidade de barras correlacionado com dia-da-semana injeta um ciclo semanal espúrio no espaço de barras, que qualquer modelo de feature ou de regime vai ler como sinal.** Ruído homogêneo não faz isso.

Ou seja: a estatística certa nunca foi o % agregado — é a **dispersão do erro entre dias-da-semana**. Por ela, W=7 ganha de forma decisiva e W=1 perde feio, e a conclusão do time fica mais bem sustentada do que pelo argumento que ele usou. Recomendo trocar a justificativa por esta.

---

## 3. Defeito de desenho: o reset de carry reinjeta um artefato semanal

**Este é o achado que, sozinho, impede autorizar (a).**

O §10 registra: `ThresholdBarsCarry` nunca cruza fronteira de período — cada período recomeça do zero. Combinado com `cadence_days=7`:

- as fronteiras de período caem a cada 7 dias corridos, portanto **sempre no mesmo dia da semana**;
- cada fronteira força uma barra truncada (o volume residual acumulado é descartado ou fechado prematuramente);
- resultado: **uma barra anômala por semana, sempre no mesmo dia da semana**, por 6 anos e 5 símbolos.

A correção do aliasing semanal reintroduz um artefato semanal em espaço de barras, na exata frequência que ela existe para eliminar. E o consumidor a jusante não distingue os dois.

O reset é apresentado como escolha conservadora de memória ("limita o pico de memória ao tamanho de 1 período"). Mas o carry é estado escalar de uma barra parcial, não um buffer de trades — a preocupação de memória era com o chunk de processamento, que é outra coisa. E preservar o carry através da fronteira é **estritamente causal**: o residual depende só de trades passados. Não há razão de vazamento para descartá-lo.

**[verificar]** se `ThresholdBarsCarry` de fato carrega apenas estado agregado (valor acumulado + OHLC parcial). Se sim, preservá-lo através da fronteira é uma mudança pequena e elimina o artefato inteiro. Se por algum motivo não puder ser preservado, então a escolha de `cadence` passa a ter um custo que ninguém mediu — e cadência menor multiplica o artefato (365 fronteiras/ano em vez de 52).

Isso precisa estar resolvido antes do reprocessamento, porque reprocessar 6 anos × 5 símbolos com o artefato embutido significa reprocessar de novo depois.

---

## 4. Respostas às 6 perguntas do §8

**1. O limiar 2x/0,5x tem lastro?**
Não, e o problema é maior que falta de lastro — ele está posicionado sobre a moda (§2.1). Resposta construtiva no §2.2: abandone a contagem binária, reporte a distribuição da razão, e ancore nas três propriedades estatísticas que barras por atividade existem para entregar.

**2. Desacoplar `cadence` de `trailing_window` é lacuna real ou otimização de segunda ordem?**
**Lacuna real, e é o ponto exato onde os dois achados do brief se combinam.** A sazonalidade semanal exige que a *fonte de calibração* seja balanceada em dia-da-semana → `trailing_window` múltiplo de 7. A deriva secular exige que a *aplicação* seja o mais responsiva possível → `cadence` o mais curto possível. Não há conflito: são parâmetros diferentes, e cada achado restringe um deles.

O desenho que os dois achados preveem em conjunto é **`trailing_window=7, cadence=1`** — média semanal rolante, atualizada diariamente. Ele domina `7/7` na dimensão que o achado 1 mede, sem pagar o aliasing que o achado 2 identifica. Não foi medido porque a região foi excluída por construção.

Custo de medir: uma alteração de poucas linhas em `_calibration_errors_for_window` para aceitar comprimentos separados de calibração e aplicação — `calib = rows[i-T : i]`, `apply = rows[i : i+C]`, passo `C`. Nenhum reprocessamento. Isso é barato demais para ficar de fora antes de travar o parâmetro.

Ressalva importante: `cadence=1` só é viável **depois** de resolver o reset de carry (§3). Sem isso, cadência diária multiplica as fronteiras por 7.

**3. Sazonalidade semanal é explicação suficiente ou só a mais visível?**
Suficiente para o efeito medido, provavelmente. O ceticismo sobre feriados é legítimo mas de segunda ordem: Natal/Ano Novo são ~2 semanas/ano (~4% dos dias) e, ao contrário do ciclo semanal, **não** produzem aliasing sistemático contra uma janela de 7 dias — aparecem como choque local que qualquer janela curta absorve. O que uma janela múltipla de 7 não resolve é sazonalidade *anual*, mas isso é indistinguível de deriva secular na escala de medição usada, e a resposta a ambos é a mesma: janela curta.

Não trataria como bloqueante. Trataria como item de verificação depois do reprocessamento, olhando erro residual estratificado por mês.

**4. Corrigir agora ou esperar?**
**Corrigir agora**, com uma observação que o brief não faz: esta medição *é* a verificação de premissa que faltava. Antes dela, era razoável perguntar se o threshold não-causal tinha vindo de um período de referência anterior a todo o dado — nesse caso não haveria vazamento e a opção barata seria defensável. O §1 fecha isso: a calibração usa a janela inteira que depois converte, incluindo futuro. **A opção de aceitar o risco está eliminada por medição, não por preferência.**

Sobre o custo de reabrir resultados: ele é argumento *a favor* de agir cedo, não contra. Todo resultado produzido sobre a grade atual já é provisório — inclusive os do M4/AG-114/AG-118. Esperar não reduz o retrabalho, só aumenta o volume de resultados que herdam a grade errada. O que reduz retrabalho é reprocessar **uma vez só**, o que exige resolver §3 e §2.1 antes, não depois.

**5. O circuit breaker foi reconferido contra os picos de ~14x da medição diária?**
Pelo texto, é checagem pendente. **É bloqueante para (a)**, e por um motivo concreto: sob `7/7`, uma semana cujo volume real seja 14x a taxa da semana anterior gera um threshold 14x pequeno demais, ou seja ~14x mais barras que o previsto, concentradas num único período. Esse é exatamente o perfil da falha operacional já documentada no §7 (travamento de 9h+ sem log) — e ela apareceria no meio de um reprocessamento de 6 anos × 5 símbolos, o run mais caro de reverter.

Fechar essa checagem custa muito menos que descobrir na metade da execução.

**6. Deriva secular e aliasing foram genuinamente decompostos?**
**A deriva secular, sim** — a série 7/14/21 controla aliasing por construção e é evidência limpa (§1.1). O brief subestima a força do próprio achado aqui.

**O aliasing, não** — pelo buraco do grid descrito no §1.2. O teste que decide é barato e usa dados que já existem: preencher **W = 5, 6, 8, 9** e **W = 13, 15**. Se a hipótese está certa, o perfil deve mostrar dente-de-serra com mínimos locais em 7 e 14 relativamente aos vizinhos imediatos. Se W=6 e W=8 forem indistinguíveis de W=7, o "achado 2" é comprimento de janela, não periodicidade, e a justificativa estrutural de `7` cai — restando o argumento do §2.3, que continua válido e é o mais forte de qualquer forma.

---

## 5. Recomendação (§9)

**Não (a). Uma variante de (b), com lista fechada e curta.**

Nada abaixo exige reprocessamento; tudo roda sobre JSONs e código que já existem. A estimativa é de horas, não dias — e protege uma ação de 6 anos × 5 símbolos que é cara de refazer.

**Bloqueantes antes de qualquer reprocessamento:**

- **B1 — Preservar o carry através da fronteira de período** (§3). Sem isso o reprocessamento embute uma barra truncada semanal em dia fixo, e precisa ser refeito.
- **B2 — Fechar a checagem do circuit breaker contra os picos de ~14x** da medição diária (§4.5).

**Medições antes de travar o parâmetro (todas sobre dado existente):**

- **M1 — Sweep do corte de erro** (0,4/0,5/0,6 e 1,7/2,0/2,5). Verifica se o ranking entre W=1, 2, 4 e 7 sobrevive. Minutos. Se não sobreviver, o achado 2 precisa ser reescrito.
- **M2 — Preencher o grid em 5, 6, 8, 9, 13, 15.** Único teste que separa "múltiplo de 7" de "mais curto é melhor" (§4.6).
- **M3 — Desacoplar `T` e `C`**, medindo pelo menos `T=7, C=1` contra `7/7` (§4.2). Alteração de poucas linhas no script de análise.
- **M4 — Trocar a métrica de decisão**: distribuição da razão estratificada por dia-da-semana, em vez de contagem binária (§2.2, §2.3). É também a resposta à pergunta 1.

**Depois:** travar o par escolhido, reprocessar **uma vez**, e verificar no resultado real as três propriedades do §2.2 (dispersão de barras-por-dia por dia-da-semana, autocorrelação, curtose) — não como validação cerimonial, mas porque são a primeira medição de impacto real que o projeto terá sobre essa decisão.

**Sobre travar `7` como `trailing_window`:** minha expectativa é que sobreviva a M1 e M2, e o argumento do §2.3 o sustenta mesmo se M2 for ambíguo. **Sobre travar `7` como `cadence`:** não sustentado por nada na medição atual, e contrariado pelo achado 1. Esse é o parâmetro que M3 precisa decidir.

---

## 6. O que este parecer não contesta

- O diagnóstico do vazamento está correto e bem argumentado. A distinção entre "algoritmo causal dado um threshold" e "valor do threshold não-causal" é precisa, e a consequência (`bar_id = cum_value // threshold` reparticiona o mesmo trade em barras diferentes) é o argumento certo.
- `_trailing_calibration_window` está correto: `calib_end = app_start − 1 dia`, sem inclusão de `app_start`. Sem vazamento residual.
- O mecanismo de sazonalidade foi investigado, não suposto — e recalculado independentemente do JSON bruto. Isso é o padrão certo.
- A verificação de que o CPCV opera em timestamp e não em identificador de barra é um achado que simplifica o desenho e foi corretamente sinalizado.
- Descartar o primeiro período de cada símbolo por cold-start é a decisão certa.

Uma correção de framing, não de mérito: a reprodução dos números 17,86% e 41,67% valida a **implementação** contra uma implementação anterior — confirma que o script mede o que a rodada anterior mediu. Não valida a **metodologia**, que é o que o §2 deste parecer questiona. O brief usa "metodologia validada antes de confiar nela", e isso é mais forte do que o teste sustenta.
