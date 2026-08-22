# Brief para Auditoria Externa — 3 decisões residuais de risco condicionadas a regime apoiadas em fundação refutada ou contradita pela evidência do dia

### Um mecanismo de posição-por-linha já refutado (AG-108) sustenta 2 decisões pendentes; a 3ª propõe adotar, sob valor não-medido, um gate irmão do que acabou de ser desligado por falta de sinal econômico

**Data:** 2026-08-22
**Para:** revisor externo (sem acesso ao repositório — este documento é
a fonte completa)
**Documentos canônicos deste projeto:** `PLANO_MESTRE_PRINCE2.md`
(governança/decisões) e o ADR-001 completo (~1900 linhas). `PRD_V3_2_
UNIFICADO.md`/`PRD_V4_1.md` são OBSOLETOS — citados só quando relevante
pra explicar divergência histórica, nunca como justificativa de desenho
atual.

---

## 0. Como usar este documento

Este brief cobre **3 de 7** decisões que uma sessão anterior deste
projeto (2026-08-19) deixou registradas como "residuais" — as outras 4
já foram fechadas ou avançaram o suficiente para não precisarem de
ceticismo externo (resumidas no §7, por completude, mas sem pergunta
associada). As 3 aqui têm uma característica em comum: dependem, direta
ou indiretamente, de um mecanismo (contagem de posição "por linha
símbolo×resolução") que uma auditoria externa ANTERIOR já refutou como
mal-especificado (`AG-108`, resumido no §2) — ou dependem da mesma
evidência estatística que, na mesma sessão em que este brief foi
escrito, levou o projeto a desligar um controle de risco irmão por
falta de sinal econômico (`AG-118`, §3).

Não depende de nenhum brief anterior para ser lido, mas referencia 2
achados de auditorias externas já concluídas neste projeto (`AG-108`,
`AG-118`) — os trechos relevantes de ambos estão colados no §8, não
precisa confiar em resumo.

**Pedido concreto, adiantado em 1 frase** (detalhado no §6): valide se
a leitura "as 3 decisões deveriam esperar uma correção arquitetural em
`AG-108` antes de qualquer valor numérico ser fixado" está certa, ou se
há um caminho de implementação que não depende dessa correção.

---

## 1. Contexto

Este é um motor de trading quantitativo multi-ativo (5 criptomoedas,
futuros perpétuos na Binance) com capital pequeno (~R$1.000) e uma
disciplina de governança pesada: toda constante numérica tem
proveniência declarada (`MEASURED`/`DERIVED`/`LITERATURE`/`ASSUMED`),
nenhum threshold é escolhido depois de ver o resultado que ele produz,
e qualquer achado de auditoria vira registro formal versionado.

Em 2026-08-19, uma rodada de auditoria interna encontrou 10 gaps de
arquitetura no contrato entre o módulo que detecta "regime de mercado"
(calmo/stress) e os módulos que consomem essa informação (dimensionamento
de posição, kill switches, motor de decisão de entrada). Quatro rodadas
de contestação adversarial resolveram a maior parte — mas 7 sub-decisões
ficaram formalmente "abertas, não decididas por omissão". Este brief
cobre as 3 dessas 7 que ainda carregam tensão técnica real.

**Nomenclatura rápida pra quem não viu o projeto**: `K01`-`K13` são os
13 gatilhos de "kill switch" (paradas de emergência) já implementados —
`K01` é "perda diária excede 2% do capital", por exemplo. `hmm_
gaussian_k4_v1` é o classificador de regime de mercado que "venceu" a
seleção de candidatos (um modelo de Markov oculto com 4 estados
ocultos) — sua identidade exata não importa para este brief, o que
importa é que ele produz um rótulo binário "regime está em stress?"
por barra de preço.

---

## 2. O mecanismo que 2 das 3 decisões pressupõem, já refutado (AG-108)

As decisões residuais 1 e 2 (abaixo, §4) nasceram de um mecanismo
aprovado em 2026-08-19: um "gate" no motor de decisão que bloqueia
sinal de entrada numa combinação `(símbolo, resolução_temporal)` se já
existe posição aberta NESSA combinação especificamente — permitindo
posições concorrentes em resoluções DIFERENTES do mesmo símbolo (ex.
BTC numa resolução de 15 minutos E BTC numa resolução de 1 hora, ao
mesmo tempo).

Uma auditoria externa posterior (2026-08-20) refutou essa premissa
contra a API real da exchange (Binance USDⓈ-M Futures):

> Em modo "One-way" existe exatamente 1 posição por símbolo por conta.
> Em modo "Hedge" existem 2 buckets por símbolo (comprado/vendido),
> nunca por resolução temporal — e o modo é configurado por CONTA
> inteira, não por símbolo individual. Se as posições "BTC em 15min" e
> "BTC em 1h" sobreviverem à seleção de linhas de negociação (cenário
> que o projeto pretende), elas compartilham UMA posição física na
> exchange. A pergunta "a posição da linha de 1h está fechada?" não tem
> resposta no estado real da conta — a exchange não sabe que essas duas
> "posições lógicas" existem separadamente.

Essa refutação está registrada e **segue sem resolução formal** — a
recomendação da mesma auditoria (reduzir de "por linha" pra "por
símbolo", texto completo no §8) nunca foi ratificada pelo Manager do
projeto.

---

## 3. A evidência que motivou desligar o gate irmão, no mesmo dia deste brief

Paralelamente, um segundo controle de risco — que bloqueia ENTRADA de
novo trade quando o regime detectado está em "stress" — foi
formalmente medido (2026-08-21) e o resultado foi nulo: em 90 células
de teste (3 classificadores candidatos × 3 resoluções temporais × 5
símbolos × 2 direções de trade), a métrica de utilidade econômica do
gate (`lift`, essencialmente "esse gate evita mais perda do que
oportunidade que ele bloqueia?") não desviou de 1,0 (= nenhum efeito)
em nenhuma célula, com intervalo de confiança calculado corretamente.

Na mesma sessão em que este brief é escrito (2026-08-22), o projeto
**desligou esse gate de produção** — ele existia no código de decisão
antes da medição que o justificaria, e a decisão foi que manter um
controle ativo sob evidência negativa e definitiva custa mais
(oportunidade perdida, risco de contaminar métricas futuras) do que
desligar.

A decisão residual 3 (abaixo, §4) propõe adotar um gate DIFERENTE mas
**do mesmo tipo** (bloquear/forçar saída baseado no mesmo rótulo de
regime) — com um parâmetro numérico ainda não medido.

---

## 4. As 3 decisões

### 4.1 — Cache local com validade limitada vs. aceitar dado potencialmente desatualizado (rastreamento de posição concorrente)

Se/quando o projeto implementar o rastreamento de posições abertas por
linha (bloqueado por §2 acima), como manter esse dado atualizado? A
consulta à exchange que informaria isso tem prioridade BAIXA de
requisição (a exchange limita quantas chamadas por segundo, e
requisições de execução de ordem têm prioridade sobre consultas de
status) — sob rajada de atividade de trading (justamente quando esse
controle mais importa), a consulta de posição é a primeira a ser
adiada. Cache local evita depender dessa consulta a cada decisão, mas
arrisca decidir com dado desatualizado; aceitar a consulta ao vivo é
mais simples mas mais lento sob estresse.

### 4.2 — Valor exato do teto de posições simultâneas

Um "backstop" numérico de quantas posições podem estar abertas ao mesmo
tempo, independente de correlação entre ativos. Já existe um controle
de risco mais sofisticado (soma ponderada por matriz de correlação
entre os 5 ativos, correlação medida em ~0,91 entre pares) implementado
e testado, mas **nunca ativo em produção** — sempre retorna "não
computável" porque nenhum módulo hoje monta a matriz de correlação em
tempo real que ele precisa. O teto simples seria um substituto
temporário.

### 4.3 — Adotar um gatilho de saída forçada por regime, com valor não-medido, ou adiar

Um 14º kill switch, condicionado a "regime em stress E existe posição
aberta nessa linha" — dispararia encurtando o prazo máximo de
permanência do trade (não mexendo no stop-loss de preço, que é uma
decisão já tomada e não está em questão aqui). O valor exato de quanto
encurtar (`TBD — medir`, nunca fixado) e a decisão de adotar agora com
um valor provisório-mas-não-medido, ou esperar uma medição real, estão
em aberto.

Uma auditoria externa (a mesma citada no §2) identificou um problema
metodológico separado com esse mecanismo, que segue sem resolução: o
modelo estatístico do projeto que decide "esse trade vale a pena
entrar" é treinado assumindo um prazo máximo fixo de 8 horas. Se o
prazo real for encurtado ao vivo sob regime de stress, o modelo estaria
decidindo sobre uma coisa (trade com até 8h de prazo) mas o sistema
executaria outra (trade com prazo menor) — quebra de consistência entre
o que foi aprendido e o que é executado, não uma simples aproximação.

---

## 5. Verificação mecânica já feita

- Os 13 kill switches existentes (`K01`-`K13`) foram relidos linha a
  linha nesta sessão — nenhum código para um 14º gatilho existe hoje
  (nem stub, nem teste, nem constante de configuração).
- O controle de risco por correlação (§4.2) foi confirmado como
  implementado e testado, mas sempre inerte em produção por falta de
  dado de entrada — não é um bug, é uma dependência não-implementada.
- A consulta de posição à exchange citada no §4.1 tem exatamente 1
  definição no código e zero chamadores reais — confirmado por busca
  textual completa no repositório.

---

## 6. Achados colaterais (não bloqueantes, registrados por transparência)

- O gate de entrada por regime (§3) foi desligado horas antes deste
  brief ser escrito, e a documentação de decisão do projeto (2 lugares)
  descrevia o gate como ainda ativo até essa inconsistência ser pega e
  corrigida na mesma sessão — mencionado aqui não como falha a
  investigar, mas como contexto de quão recente é a mudança que motiva
  a pergunta central deste brief.
- Uma das 7 decisões residuais originais (não coberta aqui — ver §7)
  já tinha sido citada incorretamente, em uma sessão anterior, como
  parte deste grupo quando na verdade já estava resolvida e
  implementada há dias — corrigido, mas registrado como lembrete de que
  listas "residuais" precisam ser reverificadas contra o código real, não
  contra prosa antiga, antes de qualquer decisão nova se apoiar nelas.

---

## 7. As outras 4 decisões residuais (fora de escopo deste brief, por completude)

Não incluídas porque já foram resolvidas ou não carregam tensão
metodológica real hoje: (a) qual conta usar como denominador de um
kill switch de perda diária — recomendação técnica já limpa, falta só
ratificação formal; (b) se uma resolução temporal secundária deveria
virar escopo de produção — já decidido, pré-requisito técnico já
cumprido, resta só execução mecânica; (c) se um módulo futuro (ainda
não construído) deveria consumir o rótulo de regime como insumo — já
respondido estruturalmente (não deveria, por uma decisão de arquitetura
mais ampla já ratificada); (d) uma decisão já citada incorretamente
como parte deste grupo (ver §6) — na verdade já fechada há dias, não é
mais uma pergunta em aberto.

---

## 8. Perguntas que um revisor cético deveria fazer

1. **A refutação do §2 (posição "por linha" não mapeia pra estado real
   de conta) já invalida qualquer valor numérico fixado para §4.1/§4.2
   antes dessa correção arquitetural acontecer?** Se sim, as 2
   decisões não deveriam nem ser tratadas como "pendentes de medição"
   — deveriam ser reclassificadas como "bloqueadas por dependência não
   resolvida", o que muda a prioridade de quem trabalha nelas a
   seguir.
2. **A mesma evidência que justificou desligar o gate de entrada por
   regime (§3, 90 células sem sinal) deveria pesar contra adotar §4.3
   (gate de saída por regime) com um valor não-medido?** Os dois
   mecanismos usam o MESMO rótulo de regime pra decisões diferentes
   (bloquear entrada vs. encurtar prazo de saída) — é razoável tratá-los
   como evidências independentes, ou a falta de sinal econômico num
   deveria ser lida como evidência (não prova, mas sinal) contra o
   outro também?
3. **O problema de quebra de consistência entre treino e execução
   citado em §4.3 (modelo aprende sobre prazo de 8h fixo, sistema
   executaria prazo variável) é resolvível sem re-treinar o modelo do
   zero, ou é uma objeção que só se resolve adiando o mecanismo até o
   próximo ciclo de retreino?**
4. **Dado que o controle de risco por correlação (§4.2) já existe
   implementado e testado, mas inerte por falta de módulo de
   rastreamento de posição ao vivo — faz sentido investir num teto
   simples "temporário" (§4.2), ou o esforço deveria ir direto pra
   destravar o controle mais sofisticado que já existe?**

---

## 9. O que pedimos exatamente

1. **Valide ou refute** nossa leitura provisória: as decisões §4.1 e
   §4.2 deveriam esperar a correção arquitetural de `AG-108` (§2) antes
   de qualquer valor numérico ser fixado — fixar um número agora
   arrisca precisar refazer o trabalho quando a unidade de posição for
   corrigida de "linha" pra "símbolo".
2. **Valide ou refute**: a evidência de `AG-118` (§3) é motivo
   suficiente para adiar §4.3 até uma medição real do valor de
   encurtamento existir, em vez de adotar um valor provisório
   `ASSUMED` agora.
3. **Recomende, entre opções nomeadas**: pra §4.1, cache local com
   validade limitada, aceitar dado potencialmente desatualizado com
   reconciliação periódica, ou uma terceira via que nenhuma das duas
   cobre?
4. Se você discordar da priorização deste brief (§0, por que só estas 3
   das 7 decisões originais foram trazidas) — diga isso explicitamente,
   é informação útil por si só.
5. Qualquer achado fora do escopo das 3 perguntas acima que pareça
   relevante — reportado por transparência, não descartado por não
   estar na lista.

---

## 10. Anexos técnicos

### 10.1 — Refutação do mecanismo "posição por linha" (AG-108, trecho relevante)

> `(símbolo, resolução)` não é uma entidade de posição na Binance
> USDⓈ-M. Em One-way mode existe 1 posição por símbolo/conta; em Hedge
> mode, 2 buckets/símbolo, nunca por resolução — e o modo é configurado
> por CONTA, não por símbolo. Se `BTCUSDT:R1` e `BTCUSDT:R3`
> sobreviverem à seleção de linha, elas compartilham UMA posição física
> na exchange. "A posição de R3 está FLAT?" não tem resposta no estado
> real da conta.
>
> Recomendação (não ratificada): ledger local via stream de eventos da
> exchange (push, não polling — fora do orçamento de taxa de requisição
> "quente"), consulta REST só para reconciliação periódica, gate falha
> fechado (bloqueia entrada nova, nunca bloqueia saída/parada de
> emergência).

### 10.2 — Resultado nulo do gate de entrada por regime (AG-118, trecho relevante)

> `lift` (utilidade econômica do gate) medido em 90 células (3
> classificadores candidatos × 3 resoluções × 5 símbolos × 2 direções),
> intervalo de confiança calculado corretamente — não desvia de 1,0 em
> NENHUMA célula, robusto ao classificador escolhido. Achado mecanístico
> complementar: o preço de saída de um trade vencedor/perdedor É o
> próprio preço do gatilho de saída (por construção do sistema de
> rotulagem), o que torna qualquer métrica de perda de cauda
> quase-determinística em função da volatilidade recente — só a fração
> de trades que efetivamente batem o alvo de lucro vs. o de perda
> depende do caminho real de preço, e é exatamente aí que a medição não
> achou sinal.

### 10.3 — Estado do código citado (referências internas, não navegáveis por quem não tem o repositório)

- 13 gatilhos de parada de emergência existentes, nenhum 14º
  implementado (zero stub, zero teste, zero constante de configuração).
- Controle de risco por correlação: implementado e testado, sempre
  retorna "não computável" em produção — nenhum módulo hoje monta a
  matriz de correlação em tempo real necessária.
- Consulta de posição à exchange citada em §4.1: 1 definição no
  código, zero chamadores reais confirmados por busca textual completa.
- Suporte a "prazo de saída configurável" (relógio fixo vs. contagem de
  barra) já existe na camada de rotulagem — infraestrutura reusável se
  §4.3 for adotado, mas o mecanismo de "encurtar ao vivo sob regime"
  em si não está implementado.
