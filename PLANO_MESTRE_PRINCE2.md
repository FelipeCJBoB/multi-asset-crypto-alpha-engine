# PLANO MESTRE DO PROJETO — BTCUSDT Quant Engine, sob PRINCE2 adaptado

**Versão:** 1.0 · **Data:** 2026-08-12
**Natureza:** camada de governança sobre `PRD_V4_1.md` — não substitui o PRD,
envolve ele. Em termos PRINCE2: este documento é o **produto de gestão**
(Project Initiation Documentation); `PRD_V4_1.md`/`PRD_V3_2_UNIFICADO.md`
continuam sendo os **produtos especialistas** (a especificação técnica do
que está sendo construído). PRINCE2 distingue os dois tipos de produto
formalmente — misturar os dois num documento só seria já a primeira
violação do próprio método que estamos adotando.

> **Por que este documento existe.** No dia 2026-08-11/12, um furo de
> arquitetura real — `triple_barrier.py` (Label Engine, produção) chamando
> `group_c.c01_atr_20` direto em vez de consumir a interface
> `VolatilityEstimator` que `src/features/volatility.py` já expunha desde
> T0.1 — só apareceu porque o Manager perguntou "essa engenharia está
> correta ou é um furo?" depois do trabalho já estar "pronto e commitado".
> Isso não é falha de um agente descuidado — é ausência de PROCESSO que
> obrigasse a pergunta a ser feita ANTES, de forma sistemática, em todo
> arquivo tocado. Este documento formaliza esse processo.

---

## Sumário

1. [Por que PRINCE2, e o que "adaptado" significa aqui](#1)
2. [Os 2 papéis — e o problema real que eles resolvem](#2)
3. [Os 7 princípios — o que se aplica literal, o que exige tradução](#3)
4. [As 7 práticas — mapeadas ao que já existe no repo](#4)
5. [Os 7 processos — mapeados ao ciclo de vida já em uso](#5)
6. [**O Protocolo de Pacote de Trabalho por Arquivo**](#6) — o núcleo prático
7. [Registros RAID — o que já existe, o que falta](#7)
8. [Relação com PRD_V4_1.md e com as skills existentes](#8)
9. [Caso trabalhado: aplicando o protocolo retroativamente a `volatility.py`](#9)
10. [Primeiro ciclo real: o próximo arquivo a ser tocado](#10)

---

## 1. Por que PRINCE2, e o que "adaptado" significa aqui <a name="1"></a>

PRINCE2 (PRojects IN Controlled Environments) é organizado em quatro
elementos integrados: **7 princípios** (não-negociáveis — um projeto sem
todos os 7 não é "um projeto PRINCE2", só usa o vocabulário), **7 práticas**
(chamadas "temas" até a 6ª edição; a 7ª edição, mais recente, renomeou para
"práticas" — uso os dois nomes abaixo porque a literatura ainda mistura os
termos), **7 processos** (o ciclo de vida, do início ao encerramento), e
**tailoring** — o próprio método exige adaptação ao contexto, e um dos 7
princípios É "adaptar para servir ao projeto", não o contrário. [Fontes:
PRINCE2.com — 7 princípios/temas/processos](https://www.prince2.com/eur/blog/the-7-principles-themes-and-processes-of-prince2),
[Axelos — tailoring PRINCE2](https://www.axelos.com/resource-hub/blog/tailoring_prince2_projects),
[Projex Academy — tailoring para projetos simples](https://www.projex.com/tailoring-prince2-for-simple-projects/).

**Isso não é burocracia importada de indústria errada.** Este projeto já
pratica, de forma orgânica e sem nomear, pelo menos 4 dos 7 princípios:

| princípio PRINCE2 | já existe neste repo, sem o nome |
|---|---|
| Continued Business Justification | §6.5 critérios de encerramento, DSR/`N_lifetime` — "vale a pena continuar gastando trials?" |
| Manage by Exception | `sweep_range`/tolerâncias em `constants.yaml`, R1-R3 como limites duros |
| Focus on Products | `Metric`/`ControlOutcome`/`VolatilityEstimator` como contratos explícitos, não números soltos |
| Learn from Experience | `docs/SPRINT_LOG.md`, `audit/evidence_ledger.yaml` (append-only, `superseded_by`) |

**O que NÃO existe, e é exatamente o gap que o incidente de `volatility.py`
expôs:** um processo de **Quality Review** obrigatório, com um **revisor
independente do produtor**, aplicado no grão certo (por arquivo/módulo, não
só por Sprint/Gate). PRINCE2 chama isso de **Project Assurance** — e o
próprio manual é explícito: quem produz o item não deve ser quem preside a
revisão dele. [Fonte: Projex — Quality Review Technique, papéis](https://www.projex.com/demystifying-the-prince2-quality-review-technique/).
Isso é fisicamente impossível de violar por acidente numa organização com
separação de papéis — mas é EXATAMENTE o que acontece por padrão quando um
único agente (eu) escreve E acha que revisou o próprio código na mesma
janela de contexto. Formalizar isso é a peça central deste documento (§6).

**Tailoring aplicado agora, explicitamente, não implícito:** com 2 pessoas
(você + eu) e sem Team Managers, PRINCE2 recomenda literalmente consolidar
papéis e reduzir a suíte de documentos — "é possível gerenciar um projeto
pequeno com apenas 4 conjuntos de documentação". [Fonte: Projex — tailoring
para equipes pequenas](https://www.projex.com/how-to-tailor-prince2-7th-edition-for-small-projects/).
Não vou propor 26 documentos PRINCE2 canônicos — isso violaria o próprio
princípio de tailoring. Vou propor o mínimo que fecha o gap real.

---

## 2. Os 2 papéis — e o problema real que eles resolvem <a name="2"></a>

PRINCE2 tem, na forma completa: Project Board (Executive + Senior User +
Senior Supplier), Project Manager, Team Manager, Project Assurance, Project
Support, Change Authority. Para 2 pessoas, a orientação oficial é combinar
Executive+Senior User (lado "cliente") e deixar o Project Manager acumular
Team Manager + Project Support (lado "entrega"). [Fonte: mesma referência
de tailoring acima.]

| papel PRINCE2 | quem, aqui | responsabilidade real |
|---|---|---|
| **Executive + Senior User** | **Manager (você)** | Business Case (vale a pena continuar?), aceita risco, decide escopo/prioridade — já é literalmente como CLAUDE.md descreve seu papel hoje |
| **Project Manager + Team Manager + Project Support** | **Claude (eu)** | Planeja, executa, reporta progresso, mantém os registros |
| **Project Assurance** | **⚠️ Ver abaixo — este é o papel que faltava** | Verifica de forma independente que o que foi entregue é o que devia ser entregue |

**O problema de desenho real:** Project Assurance existe em PRINCE2
precisamente para NÃO depender da boa vontade do produtor de notar o
próprio ponto cego. Eu, sozinho, na mesma sessão que escrevo
`triple_barrier.py`, não sou um assurance independente de mim mesmo — sou
o produtor. Três formas de resolver isso, em ordem de rigor:

1. **Você faz as "Perguntas de Integração" (§6.3) manualmente**, como já
   fez com `volatility.py` — funciona, mas depende de você lembrar de
   perguntar toda vez, e seu tempo é o recurso mais escasso do projeto
   (você mesmo disse: "extensão e pouca mão de obra").
2. **Um segundo agente Claude, sessão nova, sem o contexto de por que a
   primeira implementação foi feita daquele jeito**, revisa
   adversarialmente — isso é literalmente o skill `audit_engineering`
   já existente no repo, mas hoje ele é invocado por escolha, não por
   protocolo obrigatório. Ferramentas disponíveis: `Agent` (subagente
   fresco) ou `Workflow` (fan-out com revisor adversarial dedicado).
3. **Os dois juntos, no grão certo** — (2) roda por padrão em todo
   arquivo tocado que atinja os critérios do §6.1; (1) é o escalonamento
   quando (2) sinaliza algo que precisa de julgamento de negócio (não só
   engenharia) — exatamente o tipo de pergunta "vale a pena continuar" que
   só o Manager responde.

**Decisão proposta (você aprova ou ajusta):** (3), com (2) obrigatório e
(1) sob demanda. Isso é literalmente Project Assurance delegado a um
segundo agente — não é uma invenção fora de PRINCE2, é a leitura mais
estrita do princípio "papéis definidos" aplicada a um contexto onde o
segundo humano não existe, mas um segundo AGENTE de IA, com contexto
genuinamente separado, existe e é barato de invocar.

---

## 3. Os 7 princípios — o que se aplica literal, o que exige tradução <a name="3"></a>

| # | princípio | aplicação neste projeto |
|---|---|---|
| 1 | **Justificativa contínua de negócio** | Já existe: §6.5 critérios de encerramento pré-registrados, DSR, `N_lifetime`. Nenhuma mudança necessária — só formalizar que TODO Pacote de Trabalho (§6) precisa citar qual critério de M1-M6/Camada ele serve. |
| 2 | **Aprender com a experiência** | Já existe: `docs/SPRINT_LOG.md`, `audit/evidence_ledger.yaml`. Falta: um **Lessons Log** curto e pesquisável especificamente de FUROS DE ARQUITETURA (não achados estatísticos) — proponho `audit/architecture_gaps_log.yaml` (§7). |
| 3 | **Papéis e responsabilidades definidos** | Resolvido no §2. |
| 4 | **Gerenciar por exceção** | Já existe parcialmente (`sweep_range`, R1-R3). Falta aplicar ao PROCESSO, não só aos números: definir tolerância de escopo por Pacote de Trabalho (§6.2) — se o trabalho for além do arquivo/gap declarado, isso é uma exceção que precisa voltar pra você, não decisão unilateral minha. |
| 5 | **Gerenciar por estágios** | Já existe: Camada 0/1/2/3 do PRD, cada uma com Gate. Sem mudança estrutural — só nomear os Gates como o que já são (Stage Boundaries, §5). |
| 6 | **Foco em produtos** | Parcialmente presente (`Metric`, `ControlOutcome`, `VolatilityEstimator` como contratos). Falta: **Descrição de Produto** explícita por arquivo/módulo ANTES de escrever código — é o §6.2, o núcleo deste documento. |
| 7 | **Adaptar ao contexto** | Este documento inteiro é a aplicação deste princípio — 4 documentos, não 26; 2 papéis, não 7. |

---

## 4. As 7 práticas — mapeadas ao que já existe <a name="4"></a>

| prática PRINCE2 | equivalente hoje neste repo | gap |
|---|---|---|
| **Business Case** | §6.5 (critérios de encerramento), §6.1 (orçamento de trials), DSR | nenhum — já formal |
| **Organização** | CLAUDE.md ("Comportamento esperado"), protocolo de execução | resolvido no §2 |
| **Planos** | PRD_V4_1.md Camada 0-3, roadmap Parte VIII | falta Product-Based Planning no grão de arquivo — §6 |
| **Qualidade** | `audit_engineering` skill, `banned_patterns.py`, golden tests, `check_unguarded_ratios.py` | falta **obrigatoriedade** + **independência do revisor** — §6 |
| **Risco** | `constants.yaml` (`provenance`/`class`/`sweep_required`) | falta um Risk Register que não seja só sobre CONSTANTES numéricas — §7 |
| **Issues** (mudança) | `docs/audit_discarded_diagnostics.md`, achados do SPRINT_LOG | falta registro estruturado e PESQUISÁVEL de furos de integração — §7 |
| **Progresso** | git log, `docs/SPRINT_LOG.md`, commits | já bom; só formalizar cadência de Highlight Report (§5, processo CS) |

---

## 5. Os 7 processos — mapeados ao ciclo já em uso <a name="5"></a>

| processo PRINCE2 | equivalente neste projeto | status |
|---|---|---|
| **SU — Starting up** | Camada 0 (T0.1-T0.6) | ✅ em andamento/feito |
| **IP — Initiating** | A própria escrita do PRD_V4_1.md | ✅ feito |
| **DP — Directing** | "Decisão do Manager" (já o vocabulário usado em todo o PRD) | ✅ já é assim |
| **CS — Controlling a Stage** | Trabalho dentro de um M1-M6/Camada, dia a dia | ✅ acontece, sem nome formal |
| **MP — Managing Product Delivery** | **Cada arquivo/módulo tocado** | ⚠️ **é aqui que falta processo — §6** |
| **SB — Managing Stage Boundaries** | Os Gates (G-C0-1..7, G-C1-1..6) | ✅ já existe, quase verbatim PRINCE2 |
| **CP — Closing** | V41-12, Gate 6 | planejado, não chegou ainda |

**Achado da própria pesquisa:** este PRD já reinventou 5 dos 7 processos
PRINCE2 organicamente, sem o vocabulário. O único processo genuinamente
ausente é **Managing Product Delivery** no grão certo — não porque
ninguém "entrega produtos" (todo commit é uma entrega), mas porque não
existe uma Descrição de Produto ANTES da entrega nem uma revisão
INDEPENDENTE depois. É isso que o §6 resolve.

---

## 6. O Protocolo de Pacote de Trabalho por Arquivo <a name="6"></a>

Esta é a resposta direta a "a metodologia para descobertas desse nível tem
que ser um processo arquitetado". Adaptação do **Product-Based Planning**
(a técnica de planejamento de PRINCE2 — definir o QUE antes do COMO) e da
**Quality Review Technique** (papéis: Chair, Presenter, Reviewer(s),
Administrator — "o produtor não deve presidir a revisão do próprio
produto"). [Fonte: Projex — Quality Review Technique.](https://www.projex.com/demystifying-the-prince2-quality-review-technique/)

### 6.1 Quando este protocolo se aplica

Todo arquivo (ou grupo de arquivos fortemente acoplados, ex. um módulo +
seus testes) que:
- expõe uma interface/abstração nova (Protocol, classe pública, contrato),
- é consumido por mais de um outro módulo, OU
- fica em `src/labels/`, `src/risk/`, `src/execution/`, `src/regime/`
  (camadas críticas — dinheiro real ou label de produção).

Não se aplica a: scripts de análise exploratória em `src/analysis/`/
`research/` de uso único, ajuste de docstring sem mudança de comportamento,
correção de teste sem mudança de produção.

### 6.2 Antes de tocar o arquivo — Descrição de Produto (5 minutos, não 5 páginas)

Template mínimo — eu escreno isto e coloco na mensagem ANTES de editar,
não depois:

```
ARQUIVO: <caminho>
PROPÓSITO: <por que este arquivo existe, em uma frase — qual pergunta ele responde>
CONSUMIDORES REAIS HOJE: <quem chama isto agora, com caminho:linha — "ninguém
                           ainda" é uma resposta válida, mas TEM que ser
                           dita explicitamente>
CONSUMIDORES PRETENDIDOS: <quem DEVERIA chamar isto, segundo o PRD/design>
GAP CONHECIDO: <se consumidores reais != pretendidos, isso já é um achado
               ANTES de eu escrever uma linha de código>
CRITÉRIOS DE QUALIDADE: <lente(s) do audit_engineering aplicável — FS/FI/FT/FCN>
MÉTODO DE VERIFICAÇÃO: <golden test? paridade batch/streaming? teste de
                        integração ponta a ponta? qual?>
```

**Isto sozinho já teria capturado o furo de `volatility.py`** — a linha
"CONSUMIDORES REAIS HOJE" para `ATRWilderEstimator` em 2026-08-11 teria
que dizer "nenhum caller de produção, só `volatility_comparison.py`", e
essa frase, escrita ANTES de eu seguir em frente, é exatamente a pergunta
que só foi feita depois, por você.

### 6.3 As 5 Perguntas de Integração — checklist obrigatório, não sugestão

Derivadas diretamente do incidente real. Aplicadas a QUALQUER Pacote de
Trabalho que crie ou modifique uma interface/abstração:

1. **Quem no pipeline de PRODUÇÃO consome isto de verdade?** — liste
   caminho:linha, não "deveria consumir".
2. **Se este arquivo fosse apagado hoje, o que quebraria DE VERDADE?**
   (não o que "deveria" quebrar — rode o grep, não confie na memória)
3. **Existe um caminho paralelo mais antigo fazendo a mesma coisa?**
   Os dois podem divergir silenciosamente sem nenhum teste pegar?
4. **O "trabalho subsequente"/TODO citado no próprio docstring do arquivo
   já foi fechado, ou está proposital e permanentemente adiado?** (se a
   resposta é "adiado há mais de 1 Sprint", isso é um Issue, não um TODO)
5. **Que teste PROVARIA que a integração real — não a unidade isolada —
   funciona?** Se a resposta é "nenhum teste hoje prova isso", essa é a
   próxima linha de código a escrever, não a corrente.

### 6.4 Revisão independente — obrigatória, não por escolha

Depois que eu termino a implementação, ANTES de considerar o Pacote de
Trabalho fechado: invoco `Agent` (subagente fresco, sem o contexto de por
que decidi implementar daquele jeito) com uma instrução adversarial —
"aqui está o arquivo X e seus consumidores reais (liste); as 5 Perguntas
de Integração acima têm resposta completa e honesta? Encontre o que eu não
vi." Isso usa a infraestrutura que já existe (`audit_engineering`, skill
já escrita, quad-lens FS/FI/FT/FCN) — a mudança é tornar essa invocação
**padrão do protocolo**, não uma escolha pontual.

Se o segundo agente achar algo: vira entrada no `architecture_gaps_log`
(§7), não é silenciosamente corrigido e esquecido — mesma disciplina de
"não remediar, sempre solucionar" que já está no CLAUDE.md.

### 6.5 Quando escalar pra você (Manager)

O segundo agente resolve gaps de ENGENHARIA (o código faz o que diz que
faz, está integrado, está testado). Ele NÃO decide gaps de NEGÓCIO/ESCOPO
— isso volta pra você, mesmo que descoberto no meio de um Pacote de
Trabalho pequeno. Sinal de escalonamento: a resposta às 5 Perguntas revela
que uma decisão de arquitetura maior (ex. "GK devia ser canônico em
produção?") está implícita e não decidida — isso é Managing by Exception
(princípio 4) aplicado ao processo: eu paro, reporto, você decide,
depois eu continuo.

---

## 7. Registros RAID — o que já existe, o que falta <a name="7"></a>

RAID = Risks, Assumptions, Issues, Dependencies — a forma simplificada que
PRINCE2 recomenda para projetos pequenos em vez dos registros separados.
[Fonte: Projex — tailoring, "single RAID-style log".](https://www.projex.com/how-to-tailor-prince2-7th-edition-for-small-projects/)

| componente RAID | onde já vive | o que falta |
|---|---|---|
| **Risks** (riscos de premissa numérica) | `config/constants.yaml` (`provenance`/`class`/`sweep_required`) | nada — já é um Risk Register de verdade, só não tem esse nome |
| **Assumptions** | mesma coisa, campo `provenance: ASSUMED` | nada |
| **Issues** (achados que exigem decisão) | `docs/SPRINT_LOG.md`, `audit/evidence_ledger.yaml` | **furos de ARQUITETURA/INTEGRAÇÃO não têm registro próprio** — são achados de natureza diferente de "medição estatística" |
| **Dependencies** | import-linter (`pyproject.toml`), layer hierarchy do CLAUDE.md | nada estrutural — só falta official citá-lo como Dependency Register |

**Novo, proposto:** `audit/architecture_gaps_log.yaml` — append-only,
mesmo padrão de `evidence_ledger.yaml` (nunca editar, só `superseded_by`).
Schema mínimo:

```yaml
- id: AG-001
  date: "2026-08-11"
  file: "src/labels/triple_barrier.py"
  found_by: "Manager, questionando resumo de sessão"  # ou "Agent adversarial, Pacote de Trabalho X"
  gap: "Produção chamava group_c.c01_atr_20 direto; VolatilityEstimator (T0.1) nunca injetado no ponto de maior criticidade"
  severity: "alto"  # baixo/médio/alto — mesma escala do audit_engineering
  resolved_by_commit: "2341a96"
  status: "fechado"  # aberto | fechado | aceito-como-débito-técnico
```

Isso dá ao projeto, pela primeira vez, uma pergunta respondível
mecanicamente: **"quantos furos de arquitetura já encontramos, em quais
arquivos, quem achou primeiro (eu ou você)?"** — essa última coluna
(`found_by`) é a métrica mais importante do processo: se depois de alguns
ciclos ela continuar dizendo "Manager" na maioria das vezes, o protocolo
do §6 não está funcionando e precisa de ajuste, não só o código.

---

## 8. Relação com PRD_V4_1.md e com as skills existentes <a name="8"></a>

- **`PRD_V4_1.md`** continua sendo a fonte técnica — Camadas, M1-M6,
  critérios de encerramento, roadmap. Em vocabulário PRINCE2: é onde vivem
  as Descrições de Produto de ALTO NÍVEL (por Camada/Gate) — este
  documento adiciona a camada de BAIXO NÍVEL (por arquivo).
- **`CLAUDE.md`** continua sendo as regras de execução (banned patterns,
  protocolo "quem roda o quê", git). Nada aqui substitui isso.
- **Skill `audit_engineering`** vira o MÉTODO DE QUALIDADE citado em toda
  Descrição de Produto do §6.2 — já escrita, só passa a ser invocação
  obrigatória via `Agent` independente, não opcional.
- **`audit/evidence_ledger.yaml`** e **`audit/n_lifetime.yaml`** continuam
  exatamente como estão — são Risk/Business-Case registers que já
  funcionam. `audit/architecture_gaps_log.yaml` (§7) é o único registro
  genuinamente novo proposto aqui.

---

## 9. Caso trabalhado: aplicando o protocolo retroativamente a `volatility.py` <a name="9"></a>

Pra provar que o protocolo é operacional, não só teórico — a Descrição de
Produto que DEVERIA ter existido antes da sessão de 2026-08-11:

```
ARQUIVO: src/features/volatility.py
PROPÓSITO: interface VolatilityEstimator + implementações, pra que os 135
           pontos de fan-in de ATR migrem pra um contrato único (T0.1)
CONSUMIDORES REAIS HOJE: nenhum caller de produção -- só
                         src/analysis/volatility_comparison.py (harness de
                         comparação M1) e testes
CONSUMIDORES PRETENDIDOS: src/labels/triple_barrier.py (dimensiona TP/SL),
                          src/features/build.py (Grupo A/E), possivelmente
                          src/risk/sizing.py (stop_pct)
GAP CONHECIDO: SIM -- a própria docstring do módulo já dizia isso ("migração
               completa dos 135 pontos é trabalho subsequente"), mas
               "trabalho subsequente" não tinha prazo nem Pacote de
               Trabalho aberto -- ficou implícito indefinidamente
CRITÉRIOS DE QUALIDADE: FCN (o contrato promete algo que o sistema real não
                         cumpre -- interface existe, integração não)
MÉTODO DE VERIFICAÇÃO: nenhum teste hoje prova que build_labels usa
                        VolatilityEstimator -- essa ausência DEVERIA ter
                        sido a entrada do backlog, não uma surpresa depois
```

Com essa Descrição de Produto escrita ANTES (mesmo que em 2026-08-08,
quando T0.1 foi implementado), a resposta à Pergunta de Integração #4
("o TODO já foi fechado ou está adiado permanentemente?") já teria
disparado um Issue formal — e o trabalho de fechar isso (feito em
2026-08-12, commit `2341a96`) provavelmente teria acontecido 4 dias
antes, sem precisar de você perguntar.

---

## 10. Primeiro ciclo real: o próximo arquivo a ser tocado <a name="10"></a>

Proponho aplicar o protocolo do §6 a partir do PRÓXIMO arquivo que
tocarmos — não retroativamente a todo `src/` de uma vez (isso seria uma
Camada 0 nova inteira, orçamento e tempo que você não pediu aqui). Sugiro:

1. Você aprova (ou ajusta) a estrutura de papéis do §2 e o formato de
   Descrição de Produto do §6.2 — são as duas decisões que mais afetam
   como trabalhamos daqui pra frente.
2. Eu crio `audit/architecture_gaps_log.yaml` (vazio, schema definido) e
   registro retroativamente o achado `AG-001` (o próprio caso de
   `triple_barrier.py`/`volatility.py`) — dá ao log um primeiro registro
   real, não um template vazio.
3. O próximo arquivo tocado (qualquer que seja — sua escolha de prioridade
   continua sendo a autoridade, princípio "papéis definidos") passa pelo
   protocolo completo: Descrição de Produto → implementação → revisão
   adversarial via `Agent` → registro se achar algo.

Isso é deliberadamente pequeno pra começar — Managing by Exception:
rodamos um ciclo, medimos se ele realmente captura furos que eu sozinho
não capturaria, e ajustamos o processo em vez de assumir que acertamos o
desenho na primeira tentativa (o próprio princípio "aprender com a
experiência" aplicado ao PROCESSO, não só ao código).

---

## Fontes desta pesquisa

- [PRINCE2.com — Os 7 princípios, temas e processos](https://www.prince2.com/eur/blog/the-7-principles-themes-and-processes-of-prince2)
- [Axelos — Tailoring PRINCE2 projects](https://www.axelos.com/resource-hub/blog/tailoring_prince2_projects)
- [Projex Academy — Tailoring PRINCE2 para projetos pequenos/simples](https://www.projex.com/tailoring-prince2-for-simple-projects/)
- [Projex Academy — Tailoring PRINCE2 7ª edição para projetos pequenos](https://www.projex.com/how-to-tailor-prince2-7th-edition-for-small-projects/)
- [Projex Academy — A técnica de Quality Review](https://www.projex.com/demystifying-the-prince2-quality-review-technique/)
- [Purple Griffon — O que há de novo no PRINCE2 7](https://purplegriffon.com/blog/whats-new-in-prince2-7)
- [Knowledgehut — Guia de documentos PRINCE2](https://www.knowledgehut.com/blog/project-management/prince2-documents)
