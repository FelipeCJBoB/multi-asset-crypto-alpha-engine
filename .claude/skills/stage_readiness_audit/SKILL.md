---
name: stage_readiness_audit
description: |
  Use quando pedirem auditoria de "rota pra produção" de um ou mais
  estágios da Trilha de engenharia — 15 estágios (`PLANO_MESTRE_PRINCE2.md
  §15.4`/Road Map Vivo v2: `01_BARRA`...`15_FEEDBACK_POST_TRADE`).
  Triggers: "mapeia os gaps de produção do estágio X", "code review +
  system design de Y", "qual a rota pra produção de Z", "lança um agente
  pra cada estágio [de uma lista já mapeada]", ou qualquer pedido que
  combine achar bug/gap DENTRO de um estágio com decidir COMO ele chega
  a produção (não só "o que está errado", também "o que fazer a
  respeito, com que trade-off").

  Diferença de `audit_engineering` (achar bug de arquivo/pacote) e de
  `redesign_workflow` (redesenhar UM tópico, 7 fases sequenciais): esta
  skill faz FAN-OUT PARALELO por ESTÁGIO — N agentes independentes, um
  por estágio (ou cluster de estágios que vivem no mesmo pacote real),
  cada um aplicando as mesmas 5 lentes e devolvendo um veredito de rota
  pra produção. Não use pra 1 arquivo isolado (aí é `audit_engineering`
  puro) nem pra 1 redesenho de arquitetura já bem definido (aí é
  `redesign_workflow`).
argument-hint: "<escopo — ex. \"Data Layer\", \"01_BARRA e 02_DATA_CHECK\", \"todos os 15\"> [implementação: sim|não]"
---

# stage_readiness_audit — Code Review + System Design por estágio, rota pra produção

## Uso

```
/stage_readiness_audit <escopo> [implementação: sim|não]
```

- `/stage_readiness_audit Data Layer` — os 9 itens já conhecidos deste
  repo (`01_BARRA`...`07b_PESOS` + `08_SPLIT`), fan-out nos clusters do
  Passo 1 que tocam esses estágios.
- `/stage_readiness_audit 12_RISK_ENGINE, 13_EXECUCAO` — 1 cluster
  específico.
- `/stage_readiness_audit todos` — os 15 estágios completos (~9
  clusters do Passo 1) — fan-out grande, confirme que é intencional.
- `implementação: sim` — habilita `Edit`/`Write` nos agentes (ver
  "Autorização de implementação" no Passo 1); **omitido = `não`**, nunca
  presumido como `sim`.

Sem argumento nenhum, pergunte o escopo antes de prosseguir — nunca
assuma "todos os 15" por padrão (fan-out caro, precisa ser intencional).
Trigger por linguagem natural (descrição acima) continua valendo
igualmente — a sintaxe `/` é só pra quando o Manager preferir invocar
direto.

## Proveniência

Nasceu do mapeamento real do Data Layer (2026-08-21): 4 `Agent` em
paralelo + verificação própria de 2 estágios acharam gaps reais e
específicos por estágio (`AG-100` — labels ausentes pra R2/R3, bloqueio
que mais cascateia; `AG-032` — `max_feature_lookback_ms` sem caller
real; dollar bar nunca passou pelo Data Quality Engine; `T1_FEATURE_IDS`
travado em 10 apesar da decisão de expandir pra ~92; embargo de CPCV
documentado errado em 2 lugares). O Manager pediu formalização como
skill, anexando 2 templates genéricos do "Feature Development"/plugin
de engenharia da Anthropic:

- **`code-review`** (dimensões Security/Performance/Correctness/
  Maintainability) — **já coberto neste repo por `audit_engineering`**
  (lente quádrupla FS/FI/FT/FCN, mais rigorosa e mais específica às 6
  classes de bug já catalogadas aqui). Esta skill REUSA
  `audit_engineering` como método pras Lentes 1-4, não duplica.
- **`system-design`** (Requirements → High-Level Design → Deep Dive →
  Scale/Reliability → Trade-off Analysis) — **não tinha equivalente
  neste repo**. Vira a Lente 5 (nova), adaptada do genérico "o que esse
  sistema precisa fazer" pro vocabulário concreto deste projeto: "o que
  este ESTÁGIO precisa fazer segundo qual documento, o que faz hoje, o
  gap arquitetural (não só bug de linha), e qual a rota concreta pra
  produção com o trade-off explícito".

## Quando usar (e quando não)

Use pra: mapear TODOS os gaps de um conjunto de estágios (a Trilha de
engenharia inteira, ou um subconjunto — ex. "Data Layer" antes de
qualquer retreino de Alpha, decisão do Manager 2026-08-21) E devolver,
pra cada um, não só "o que está errado" mas "o que fazer, em que ordem,
com que trade-off" — insumo direto pra roadmap, não só pra backlog de
bug.

**Não use** pra: auditar 1 arquivo isolado sem intenção de mapear rota
de produção (`audit_engineering` sozinho já resolve, mais barato); um
redesenho de arquitetura já com escopo definido e decisão a tomar
(`redesign_workflow`); estágio que não tem nenhum código ainda
(`Pendente`/`Proposto` puro — não há o que revisar, só registrar como
tal).

## As 5 lentes

### Lentes 1-4 — Code Review (reuso de `audit_engineering`)

**Não reimplementa** — cada agente do fan-out (Passo 2 abaixo) recebe a
instrução explícita de ler `.claude/skills/audit_engineering/SKILL.md`
(Passo 3, "Lente quádrupla") antes de aplicar FS (Falhas Estatísticas) +
FI (Falhas de Implementação) + FT (Falhas Tecnológicas) + FCN (Falhas de
Contrato Negativo) aos arquivos do estágio designado. Roda também os 5
scripts mecânicos de lá (Passo 4: `banned_patterns.py`,
`check_constants_referenced.py`, `check_unguarded_ratios.py`,
`ruff check`, `mypy`) — evidência, não substituto do julgamento.

### Lente 5 — System Design / Rota pra Produção (nova)

Adaptação do template `system-design` genérico pro vocabulário real
deste projeto — nunca "requirements gathering" abstrato, sempre ancorado
em documento real:

1. **Requisito real** — o que este estágio precisa fazer, segundo qual
   âncora (`PRD_V4_1.md §X` histórico, `PLANO_MESTRE_PRINCE2.md §15.4`,
   `ADR-001`, ou `CLAUDE.md` banned pattern/DoD)? Se não há âncora
   nenhuma, isso já é um achado (requisito nunca formalizado).
2. **Desenho atual** — como está implementado HOJE: componentes reais
   (`arquivo:função`), fluxo de dado entre eles, contrato real entre os
   arquivos do estágio (não o que a documentação diz que é, o que o
   código realmente faz — mesma disciplina de `project_assurance`: não
   confiar na palavra do produtor, re-derivar).
3. **Gap arquitetural** — onde o desenho atual diverge do requisito, na
   escala de DESENHO (não de linha de código): cobertura incompleta
   (símbolo/resolução), acoplamento que não deveria existir, ausência de
   fallback/sentinela (`NOT_COMPUTABLE`) em vez de falha silenciosa,
   decisão de escopo nunca tomada formalmente.
4. **Escala/confiabilidade** — aguenta os 5 símbolos × 3 resoluções de
   verdade (testado, não só "deveria aguentar")? Falha graciosamente ou
   quebra/mente quando um deles não está pronto?
5. **Trade-off e rota recomendada** — caminho concreto pra fechar cada
   gap achado (não genérico — arquivo/função/decisão específica),
   sequenciado (o que desbloqueia o quê), com o trade-off explícito
   (custo de implementar vs. risco de deixar aberto, e se aplicável,
   custo de retrabalho se outro estágio mudar primeiro).

## Passo 1 — Escopo e clustering (antes do fan-out)

Antes de disparar agentes, decida o particionamento — **nunca 1 agente
por item nominal da tabela `§15.4` se vários itens vivem no mesmo
pacote real** (2 agentes editando/lendo o mesmo arquivo em paralelo é
exatamente o erro que `feedback_agent_coordination` (memória) já
documentou). Clusters conhecidos deste repo (ajustar se o código mudou):

| cluster | estágios | pacote real |
|---|---|---|
| Barra + Data Check | `01_BARRA`, `02_DATA_CHECK` | `src/data/`, `src/exchange/` |
| Features | `03_FEATURES` | `src/features/` |
| Volatilidade + Regime | `04_VOLATILIDADE`, `05_REGIME` | `src/regime/`, estimadores em `src/features/groups/` |
| Barreiras + Label + Pesos | `06_BARREIRAS`, `07_LABEL`, `07b_PESOS` | `src/labels/` |
| Split | `08_SPLIT` | `src/validation/` (CPCV/purge/leakage) |
| Learner + Calibração | `09_LEARNER`, `09b_CALIBRACAO` | `src/models/` |
| Validação + Meta + Decision | `10_VALIDACAO`, `11_META_MODEL`, `11b_DECISION_ENGINE` | `src/validation/` (walk-forward/PBO), módulo de Meta/Decision (pode não existir ainda) |
| Risk + Execução | `12_RISK_ENGINE`, `13_EXECUCAO` | `src/risk/`, `src/execution/` |
| Monitoramento + Feedback | `14_MONITORAMENTO`, `15_FEEDBACK_POST_TRADE` | `src/monitoring/`, `src/models/decomposition.py` |

**Cluster com estágios em estados diferentes** (ex. `10_VALIDACAO` tem
código real, `11_META_MODEL`/`11b_DECISION_ENGINE` são só proposta de
PBS sem implementação nenhuma) — isso NÃO tira o estágio Pendente/
Proposto do relatório do cluster, só muda o que a Lente 5 registra pra
ele: "Desenho atual" = "nenhum — 0% de código"; "Gap arquitetural" =
"requisito nunca formalizado" (se nem isso existe) ou "requisito
formalizado, zero implementação"; "Rota recomendada" descreve o
PRIMEIRO passo concreto de implementação, nunca "N/A". A exclusão da
seção "Quando usar" (estágio 100% `Pendente`/`Proposto` puro) vale só
pra disparar esta skill num estágio ISOLADO nesse estado (não há Lentes
1-4 pra aplicar sozinho, desperdiça um agente inteiro) — dentro de um
cluster que já tem PELO MENOS 1 estágio com código real, os itens
Pendente do mesmo cluster entram no mesmo relatório, tratados como
acima.

### Autorização de implementação (declarar ANTES do fan-out, nunca implícito)

Cada rodada declara aqui, explicitamente, antes de qualquer `Agent` ser
disparado:

**Implementação autorizada nesta rodada: SIM / NÃO**

- Se **SIM**: listar exatamente quais clusters (da tabela acima) têm
  autorização de `Edit`/`Write` — nunca "todos" por omissão, sempre a
  lista explícita que o Manager deu (via `argument-hint`
  `implementação: sim` ou em linguagem natural).
- Se **NÃO** (padrão, inclusive quando o escopo não menciona nada): todo
  agente do fan-out é só leitura/investigação (`Read`/`Grep`/`Glob`/`git`
  — nunca `Edit`/`Write`) — achado vira relatório + pergunta pro
  Manager, nunca vira código sozinho.

Esta declaração é copiada, **verbatim**, no prompt de CADA agente do
Passo 2 — cada agente é uma sessão nova sem memória desta conversa,
então "o Manager autorizou" só existe pra ele se estiver escrito no
próprio prompt. Isso não muda a regra já existente de nunca repassar
autorização de EXECUÇÃO (rodar `.py`/`pytest`) pra sub-agente
(`feedback_never_relay_execution_permission_to_agents`, memória) — são
categorias diferentes: `Edit`/`Write` (escrever código) pode ser
autorizado por cluster aqui; EXECUÇÃO (rodar código escrito) nunca é
repassada, mesmo que a 1ª esteja autorizada.

## Passo 2 — Fan-out (Agent tool, paralelo)

Um `Agent` (`subagent_type: general-purpose`) por cluster do Passo 1,
todos na MESMA mensagem (paralelo real, não sequencial). Cada prompt
precisa ser autocontido (agente novo, sem memória desta conversa) e
incluir, sempre nesta ordem:

1. Contexto do projeto (Motor Quant Multi-Ativo, 5 símbolos, 3
   resoluções de dollar-bar) e por que este mapeamento está acontecendo
   (motivo real da rodada — ex. "Alpha não retreina até Data Layer
   100%", ou o motivo que o Manager der da vez).
2. **A declaração de autorização de implementação do Passo 1, copiada
   verbatim** — se este cluster está na lista de `SIM`, o agente ganha
   `Edit`/`Write` e a instrução explícita "implementação autorizada
   pro que achar neste cluster"; se não está (ou a declaração for
   `NÃO`), o agente é só leitura (`Read`/`Grep`/`Glob`) e a instrução
   explícita "achado vira relatório, nunca vira código sozinho".
   **Autorizado sempre, independente da resposta acima** (investigação
   histórica é leitura, não execução, mesma exceção já nomeada do
   `CLAUDE.md`): qualquer comando `git` de só-leitura —
   `git log`/`git blame`/`git show`/`git diff` — pra confirmar QUANDO
   um achado foi corrigido/introduzido, não só SE existe hoje (foi
   assim que os agentes de 2026-08-21 desambiguaram "TF hardcoded"
   como achado histórico já corrigido vs. ainda real). Nunca `git
   commit`/`push`/`reset`/qualquer comando que altere estado.
3. O(s) estágio(s)/cluster designado, com os arquivos reais já
   conhecidos (dá um ponto de partida, mas instrui a NÃO confiar nele
   sozinho — grep/read pra confirmar o que existe de verdade hoje).
4. Instrução explícita: ler `.claude/skills/audit_engineering/SKILL.md`
   (Passo 3) antes de aplicar as Lentes 1-4; aplicar a Lente 5 (System
   Design/Rota) conforme descrita acima. **Escala de severidade**:
   exatamente a mesma de `audit_engineering` (Passo 5 lá —
   CRITICAL/P0 bloqueia, HIGH/P1 corrige antes de promover, MEDIUM/P2
   próxima iteração, LOW/P3 backlog) — nunca inventar uma escala nova
   na síntese; achado que não encaixa claramente numa categoria usa a
   mais próxima e explica o porquê na descrição, não vira um 5º nível.
5. Pedido de citar evidência real (`arquivo:linha`, saída de script
   mecânico, teste existente ou ausente) pra toda afirmação — nunca
   aceitar o que a documentação (`PLANO_MESTRE`/Road Map Vivo) já diz
   sem confirmar contra o código, e destacar divergência doc-vs-código
   como achado por si só (foi o padrão mais valioso do mapeamento de
   2026-08-21 — achados como "dollar bar nunca quality-checado" só
   apareceram por essa disciplina).
6. Formato de resposta: usar `stage_audit_report_template.md` (mesmo
   diretório desta skill) como esqueleto — Executive Summary + achados
   Lentes 1-4 (formato `audit_engineering`) + seção Lente 5 (System
   Design/Rota) + classificação final `100% pronto | Parcial | Pendente/
   Proposto` com o que falta EXATO pra 100%.

## Passo 3 — Síntese

Depois que os agentes voltarem (não delegue a síntese — leia os
relatórios reais, mesmo padrão de `redesign_workflow`/Fase 2: resumo de
agente é ponto de partida, não substituto): converge num relatório único
com resumo executivo no topo (contagem de achados por severidade e por
estágio, quantos estágios `100%`/`Parcial`/`Pendente`), e identifica
BLOQUEADORES QUE CASCATEIAM (um gap num estágio anterior que invalida
"100%" de vários estágios seguintes — ex. `AG-100` bloqueando 3 estágios
de uma vez) — isso é sempre a informação de maior valor pra sequenciar a
rota real, não a lista de achados por si só.

## Passo 4 — Registro (mesma disciplina de sempre)

- Achado novo de arquitetura/integração → `AG-NNN` em
  `audit/architecture_gaps_log.yaml`, mesmo formato de sempre
  (`found_by: "Agent stage_readiness_audit, <estágio>"`).
- Achado que já tem `AG-NNN` mas mudou de estado (fechado no código,
  ainda aberto no doc, ou vice-versa) → não reabrir/reescrever
  silenciosamente, `addendum_*`/campo `status_*` novo (append-only,
  mesma regra do arquivo).
- Decisão de rota que exige escolha do Manager (não é óbvia/técnica) →
  não decidir sozinho, listar como pergunta explícita no relatório
  final, mesmo padrão de `redesign_workflow` Fase 3.
- Correção de prosa desatualizada em `PLANO_MESTRE_PRINCE2.md §15.4`/
  Road Map Vivo v2 (não achado de gap, só doc desatualizado) → mesmo
  protocolo do comando "Atualize governança" (`CLAUDE.md`), item 2/3 —
  não fazer solto, agrupar na próxima rodada de governança a menos que o
  Manager peça pra corrigir na hora.

## Anti-patterns (recusar)

- 1 agente cobrindo estágios que vivem em pacotes diferentes achando que
  "economiza" — perde profundidade, mesmo trade-off já documentado em
  `audit_engineering` (modo varredura: 1 agente por pacote, não 1 pra
  tudo).
- 2 agentes com escopo de arquivo sobreposto rodando ao mesmo tempo —
  sempre particionar por pacote/cluster antes do fan-out (Passo 1).
- Aceitar a classificação de status que `PLANO_MESTRE §15.4`/Road Map
  Vivo já tem sem reconfirmar — é exatamente o hábito que gerou `AG-080`
  e que os agentes de 2026-08-21 (achado real) confirmaram continuar
  acontecendo (`AG-123`).
- Pular a Lente 5 achando que as 4 primeiras já bastam — sem ela, o
  relatório vira só mais uma lista de bugs, perde o que o Manager
  explicitamente pediu (rota pra produção, não só diagnóstico).

## Versionamento

```
v1.0 -- 2026-08-21 -- Criação. Formaliza o padrão usado no mapeamento
                       real do Data Layer (4 agentes paralelos + achados
                       AG-100/AG-032/dollar-bar-sem-quality-check).
                       Porta os 2 templates anexados pelo Manager
                       (system-design.txt, code-review.txt do plugin de
                       engenharia da Anthropic) -- Lentes 1-4 reusam
                       audit_engineering como método (não duplica),
                       Lente 5 (System Design/Rota pra Produção) é nova,
                       adaptada do template system-design genérico pro
                       vocabulário real deste projeto (PLANO_MESTRE
                       §15.4, ADR-001, banned patterns).
v1.1 -- 2026-08-21 -- 4 gaps reais achados na revisão do próprio Manager
                       corrigidos, mesmo dia: (1) autorização de Edit/
                       Write era ambígua -- vira declaração explícita no
                       Passo 1 ("Autorização de implementação"), copiada
                       verbatim em cada prompt do Passo 2, nunca
                       implícita; (2) sem sintaxe de invocação -- ganhou
                       `argument-hint` + seção "Uso" (`/stage_readiness_
                       audit <escopo> [implementação: sim|não]`); (3)
                       escala de severidade nunca era citada -- Passo 2
                       agora aponta explicitamente pra escala de
                       `audit_engineering` Passo 5, proíbe inventar
                       escala nova; (4) cluster com estágios em estados
                       diferentes (código real + Pendente/Proposto no
                       mesmo cluster) não tinha instrução -- Passo 1
                       ganhou tratamento explícito (Lente 5 registra
                       "0% de código"/"requisito nunca formalizado" pro
                       item Pendente, nunca exclui do relatório). Também
                       autoriza explicitamente `git log`/`blame`/`show`/
                       `diff` (só-leitura) em todo agente do fan-out,
                       independente da resposta de implementação --
                       pedido à parte do Manager, mesma exceção já
                       nomeada do CLAUDE.md (git não é execução).
```
