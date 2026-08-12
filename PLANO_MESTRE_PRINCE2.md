# PLANO INSTITUCIONAL DE CONSTRUÇÃO — Binance_Futures

**Também referido como:** Plano Mestre do Projeto, BTCUSDT Quant Engine, sob
PRINCE2 adaptado (nome original deste arquivo — mantido como identidade de
arquivo/git, ver §0 sobre por quê).
**Versão:** 1.2 · **Data:** 2026-08-12
**Natureza:** **base da verdade institucional do projeto** (elevação de
status decidida pelo Manager em 2026-08-12 — v1.0 era só "camada de
governança sobre o PRD"; v1.1 assume o papel de documento organizador de
TODOS os produtos, especialistas e de gestão). Em termos PRINCE2: este é o
**produto de gestão** de topo (Project Initiation Documentation, papel de
Project Product Description); `PRD_V4_1.md`/`PRD_V3_2_UNIFICADO.md`,
`CLAUDE.md`, as skills, e os registros append-only (`audit/*.yaml`) são os
**produtos especialistas e de gestão subordinados** — ver §11 (Product
Breakdown Structure) para o mapa completo. PRINCE2 distingue os tipos de
produto formalmente; a mudança de v1.0→v1.1 não é cosmética, é a correção
de uma inversão: um documento de governança que só "envolve" o PRD sem
organizá-lo desperdiça a técnica de Product-Based Planning que o método
oferece — ver §0 sobre a única peça que ainda não fechou por causa disso.

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

## 0. Duas decisões fechadas agora, uma aberta <a name="0"></a>

**Fechadas por padrão (Manage by Exception — princípio 4, §3): eu adoto e
sigo a partir de agora, você ajusta se discordar, em vez de esperar
aprovação explícita antes de continuar.**

1. **§2 (papéis):** opção 3 — revisão independente via `Agent` obrigatória
   por padrão (skill `project_assurance`, criada 2026-08-12), escalonamento
   pra você só quando o achado for de escopo/negócio, não de engenharia.
2. **§6.2 (formato da Descrição de Produto):** template adotado como está.

Razão de fechar por padrão em vez de perguntar: o próprio v1.0 deste
documento já argumentava (§3, princípio 4) que pausar pra aprovação de todo
detalhe operacional é o oposto de "gerenciar por exceção" — só volta pra
você o que for exceção de verdade. Papéis e template não são isso.

**Aberta, não decidida por mim — decisão de arquitetura maior, escalonamento
correto por §6.5:** `CLAUDE.md`, no topo, declara "Documento mestre:
`PRD_V3_2_UNIFICADO.md`". Se este Plano Institucional agora organiza os
produtos especialistas (§11) — incluindo o PRD — essa linha do `CLAUDE.md`
fica desatualizada, e `CLAUDE.md` é o único documento deste repo marcado
para OVERRIDE de qualquer comportamento padrão. Não troquei essa linha
sozinho: é exatamente o tipo de contradição entre documentos que a
pergunta #16 do checklist de `project_assurance` existe para pegar, e
mudar a declaração de hierarquia institucional do projeto é decisão sua,
não minha, por mais que a mudança pareça mecânica. Proposta concreta em
§13.

**Por que o nome do arquivo não mudou:** `PLANO_MESTRE_PRINCE2.md` já tem
histórico real no git (commit `93ff811`, referenciado em
`audit/architecture_gaps_log.yaml` AG-001/AG-002) e no seu próprio uso
("Li seu @PLANO_MESTRE_PRINCE2.md"). Renomear o arquivo git (`git mv`)
quebra esse link sem necessidade — o título institucional novo já muda
como o documento se apresenta; o caminho de arquivo é identidade técnica,
não a mesma coisa. Se você preferir o rename físico, é reversível e barato
de fazer depois.

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
11. [**Product Breakdown Structure — o mapa institucional completo**](#11)
12. [Referências institucionais externas: SR 26-2 e padrões de execução de hedge fund](#12)
13. [Decisão pendente: `CLAUDE.md` "Documento mestre"](#13)

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

**Decisão fechada por padrão em 2026-08-12 (§0):** (3), com (2) obrigatório
e (1) sob demanda. Isso é literalmente Project Assurance delegado a um
segundo agente — não é uma invenção fora de PRINCE2, é a leitura mais
estrita do princípio "papéis definidos" aplicada a um contexto onde o
segundo humano não existe, mas um segundo AGENTE de IA, com contexto
genuinamente separado, existe e é barato de invocar. **Implementado** como
skill `.claude/skills/project_assurance/SKILL.md` — 16 perguntas (as 5
originais do §6.3 + 11 novas, organizadas nos 3 pilares de validação de
SR 26-2, ver §12), critério de materialidade de 4 eixos que substitui a
lista simples do §6.1 abaixo.

---

## 3. Os 7 princípios — o que se aplica literal, o que exige tradução <a name="3"></a>

| # | princípio | aplicação neste projeto |
|---|---|---|
| 1 | **Justificativa contínua de negócio** | Já existe em DOIS níveis, não um: `PRD_V4_1.md` §6.5 tem os critérios de encerramento da emenda V4.1 (escopo estreito — M1-M6/Camadas); `PRD_V3_2_UNIFICADO.md` §16.9 (RF-032) tem o mecanismo ORIGINAL e mais amplo — `pre_registro` YAML congelado antes de qualquer resultado OOS, 7 critérios de encerramento do PROJETO inteiro (DSR<0,50 em 6 meses, equity<US$150, `N_lifetime`>5.000 sem DSR>0,95, teto de preço do BTC por 30 dias, venue indisponível), e disciplina anti-HARKing explícita ("hipótese reformulada depois de ver os dados é registrada como reformulação, não como confirmação"). v1.1 deste documento só citava o primeiro — omissão corrigida agora. Nenhuma mudança de processo necessária, só formalizar que TODO Pacote de Trabalho (§6) cita qual critério, dos dois níveis, ele serve. |
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

Heurística original (v1.0), mantida como triagem rápida — todo arquivo (ou
grupo de arquivos fortemente acoplados, ex. um módulo + seus testes) que:
- expõe uma interface/abstração nova (Protocol, classe pública, contrato),
- é consumido por mais de um outro módulo, OU
- fica em `src/labels/`, `src/risk/`, `src/execution/`, `src/regime/`
  (camadas críticas — dinheiro real ou label de produção).

Não se aplica a: scripts de análise exploratória em `src/analysis/`/
`research/` de uso único, ajuste de docstring sem mudança de comportamento,
correção de teste sem mudança de produção.

**Substituído no detalhe (v1.1) pelo critério de materialidade de 4 eixos**
em `.claude/skills/project_assurance/SKILL.md` §4 (exposição financeira /
peso da decisão / complexidade / contexto de uso, adaptado de SR 26-2 —
§12) — a heurística acima continua válida como primeiro filtro rápido, mas
quando ela e o critério de 4 eixos discordarem, o critério de 4 eixos
decide, porque distingue "materialidade ALTA → protocolo completo" de
"1 eixo → registro leve", o que esta lista binária não fazia.

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
Trabalho fechado: invoco a skill `project_assurance`
(`.claude/skills/project_assurance/SKILL.md`, criada 2026-08-12), que
formaliza exatamente este passo — spawna `Agent` fresco, sem o contexto de
por que a implementação foi feita daquele jeito, com as 16 perguntas do
checklist (5 originais + 11 novas) e a Descrição de Produto do §6.2 como
entrada. Reusa `audit_engineering` como MÉTODO de qualidade dentro da
revisão, mas o objeto da pergunta é integração, não só correção — ver
`project_assurance/SKILL.md` seção "Diferença de audit_engineering". A
mudança de v1.0→v1.1 é tornar essa invocação **padrão do protocolo, com
ferramenta própria**, não uma escolha pontual nem uma instrução em prosa
sem skill dedicada.

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
- **Proveniência cross-project da metodologia de auditoria (achado da
  releitura de 2026-08-12):** `PRD_V3_2_UNIFICADO.md` §18.7.1 já documenta
  que parte do método por trás de `audit_engineering` veio de comparação
  com um projeto irmão — "Laplace_Quant_V16, forex multi-par" — não foi
  inventado do zero. Fato verificável neste mesmo ambiente, não lembrança:
  o roster de subagentes disponível nesta sessão inclui `auditor`,
  `implementer`, `spec-author`, `verifier-lint`, `verifier-paridade`,
  `verifier-test`, `state-updater`, todos descritos como "Laplace_Quant
  V17" — uma versão sucessora do mesmo projeto citado no PRD, com pipeline
  orquestrado próprio (Skills 03/04/07/12). **Isso não vira trabalho
  agora** — não abri esse projeto, não é deste repo, e usar os agentes
  dele fora de contexto seria misturar dois Product Breakdown Structures
  diferentes. Registrado aqui porque é exatamente o tipo de "aprender com
  a experiência" (princípio 2, §3) que não vem de dentro deste repo — um
  canal de transferência de metodologia entre projetos que já existe e é
  citável, não hipotético.

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

## 11. Product Breakdown Structure — o mapa institucional completo <a name="11"></a>

Product-Based Planning (a técnica de planejamento de PRINCE2 citada no §6)
começa por um **Product Breakdown Structure (PBS)** — decompor tudo que o
projeto produz numa hierarquia, ANTES de planejar atividades. Esta seção é
essa decomposição, feita por inspeção real do repo (`ls` em 2026-08-12), não
por memória — o mesmo padrão de rigor que o resto do projeto exige de
qualquer número. Três camadas:

### 11.1 Produtos de gestão (governam COMO o projeto é conduzido)

| produto | caminho | papel PRINCE2 |
|---|---|---|
| **Este documento** | `PLANO_MESTRE_PRINCE2.md` | Project Product Description + PID — organiza tudo abaixo |
| Regras de execução | `CLAUDE.md` | Termo de referência operacional — banned patterns, protocolo "quem roda o quê", DoD por tipo de tarefa (ver §13 sobre o único ponto de atrito com este documento) |
| Registro de risco/proveniência | `config/constants.yaml` | Risk Register (§7) |
| Log de achados estatísticos | `audit/evidence_ledger.yaml` | Issue Register (parte estatística) |
| Log de furos de arquitetura | `audit/architecture_gaps_log.yaml` | Issue Register (parte integração) — novo, §7 |
| Contagem de trials/otimizações | `audit/n_lifetime.yaml` | controle de multiple-testing — Business Case input |
| Achados de divisão sem guarda | `audit/division_guard_audit.md` | Issue Register especializado (FCN) |
| Progresso legível por humano | `docs/SPRINT_LOG.md` | Highlight Report acumulado (EXECUÇÃO — o que foi feito, sprint a sprint) |
| Diagnósticos descartados catalogados | `docs/audit_discarded_diagnostics.md` | Issue Register especializado |
| Catálogo de fan-in/consumidores | `docs/CODE_DISCOVERY.md` | mapa de Dependencies (RAID) |
| Triagem de 54 divergências PRD↔código (T0.4) | `docs/T0_4_TRIAGEM.md` | Issue Register especializado — omitido da PBS v1.1 por descuido, corrigido agora (ver nota abaixo) |
| Mapa de blast radius de uma migração específica | `docs/refactor_gk_canonico.md` | Product Description de um Pacote de Trabalho em curso |
| Rastreabilidade de requisitos + lições de elaboração do blueprint | `PRD_V3_2_UNIFICADO.md` Parte XIX (54 requisitos rastreados, 9 erros corrigidos, 2 registros de mudança V2→V3/v3.2→v3.3) | Lessons Log — 4º tipo de log do projeto, distinto de SPRINT_LOG (execução)/evidence_ledger (achado estatístico)/architecture_gaps_log (integração); este é sobre o TEXTO do blueprint em si |
| Changelog de semântica de venue | `config/venue_changelog.yaml` | Risk Register especializado — alimenta o check 23 (Data Quality Engine, §1.3 do V3.2) que detecta quebra semântica de fonte sem quebra de schema (ex. rollout de RPI em 2025-11-20) |
| Métodos de Quality Review | `.claude/skills/audit_engineering/`, `.claude/skills/project_assurance/` | Quality Management Approach |
| Scripts de verificação mecânica | `tools/lint/*.py` (`banned_patterns`, `check_constants_provenance`, `check_constants_referenced`, `check_unguarded_ratios`, `check_sprint_log_references`) | parte automatizada da prática de Qualidade |

**Nota sobre `docs/T0_4_TRIAGEM.md` (omissão da v1.1, corrigida agora):**
`ls docs/` já tinha sido rodado na sessão que escreveu a v1.1 deste
documento — o arquivo estava visível e ficou de fora da tabela por
descuido, não por julgamento. Registrado aqui em vez de silenciado, mesma
disciplina que este documento cobra de qualquer Pacote de Trabalho.
**Não confundir com** a tabela de 54 requisitos de `PRD_V3_2_UNIFICADO.md`
Parte XIX (linha acima) — coincidência de contagem (ambas têm 54 itens),
artefatos diferentes: a Parte XIX rastreia requisito↔decisão↔evidência da
ELABORAÇÃO do blueprint original; `T0_4_TRIAGEM.md` classifica divergências
PRD↔código encontradas por leitura mecânica do código atual
(`code_discovery.json`, `code_version: ddc0362`) em `corrigir-PRD` /
`corrigir-código` / `ambiguidade-de-vocabulário`. Não verifiquei se os dois
conjuntos de 54 se sobrepõem — ficaria como afirmação não verificada se eu
dissesse que sim ou que não.

### 11.2 Produtos especialistas (o QUE está sendo construído — a engenharia em si)

| produto | caminho | subordina-se a |
|---|---|---|
| Blueprint técnico corrente — **emenda de escopo** | `PRD_V4_1.md` | este plano organiza, não substitui |
| Blueprint técnico corrente — **arquitetura e contratos** | `PRD_V3_2_UNIFICADO.md` | este plano organiza, não substitui |
| Apresentação pro usuário não-técnico | `README.md` | reflexo simplificado do estado real |
| Os 11 estágios do pipeline (`exchange → data → features → labels → regime → models → validation → backtest → risk → execution → live`) | `src/exchange/`, `src/data/`, `src/features/`, `src/labels/`, `src/regime/`, `src/models/`, `src/validation/`, `src/backtest/`, `src/risk/`, `src/execution/`, `src/live/` | camada verificada estaticamente (hierarquia do CLAUDE.md) |
| Núcleo compartilhado (`Metric`, `ControlOutcome`) | `src/core/` | contrato de dados usado por todas as camadas acima |
| Scripts de análise/pesquisa (M1, feasibility, faixa2) | `src/analysis/` | não-produção, mas informa decisões que VIRAM produção (`constants.yaml`) |
| Testes | `tests/` | prova de que os dois produtos acima cumprem o que prometem |
| Saídas de pipeline versionadas | `experiments/*.json`, `data/quality_reports/*.json`, `models/*/diagnostics/*.json` | evidência, não fonte — sempre derivável do código + dado, nunca a única cópia da verdade |

**Correção 2026-08-12, a pedido do Manager, depois de reler os dois PRDs
inteiros (v1.1 tinha isso errado):** `PRD_V3_2_UNIFICADO.md` não é
"histórico" no sentido de superado — é **obsoleto só no escopo** (BTC-only,
Partes 0/§0.1-§0.6 e as tabelas de capital/janela específicas do único
ativo), **não na arquitetura**. Partes I–XV (Feature/Label/Regime/Alpha/
Meta/Decision/Risk/Execution Engine, Reconciliação, Backtest/Validação,
Quality Gates 0–10, Stack §14.1, Estrutura de software §14.2, DoD §15) e
Partes XVI–XIX (banned patterns novos RF-024..034, proveniência §16.10/
PARTE XVIII, rastreabilidade PARTE XIX) **continuam sendo a fonte viva**
dos contratos que `CLAUDE.md` resume (`Metric`/`ControlOutcome`, hierarquia
de camadas, os 32 banned patterns têm âncora aqui, não em V4.1).
`PRD_V4_1.md` é uma **emenda de escopo** sobre isso — 5 ativos, 3 TFs,
Camadas 0-3 — não um substituto (o próprio cabeçalho do V4.1 diz isso:
"emenda, não substituição"). Tratar V3.2 como puro arquivo de proveniência
teria feito a mesma coisa que o achado do §1.4 já corrigiu uma vez: uma
afirmação factual meio-errada sobre um documento, escrita com confiança.

### 11.3 O que a inspeção real confirma que NÃO existe ainda (não inventar)

`ls` de 2026-08-12 confirma pastas `execution/`, `predictions/`, `research/`,
`scripts/` no nível raiz além do `src/execution/` — **não abri o conteúdo
delas nesta passada**; qualquer afirmação sobre o que têm dentro fica como
`TBD — inspecionar antes de decidir se entram no PBS`, em vez de presumida.
Isso é deliberado: um PBS que finge completude sem ter olhado é exatamente
o tipo de "afirmação não re-verificada" que a pergunta #6 de
`project_assurance` existe pra pegar — inclusive quando quem afirma sou eu,
escrevendo este próprio documento.

---

## 12. Referências institucionais externas: SR 26-2 e padrões de execução de hedge fund <a name="12"></a>

Você pediu para trazer **SR 26-2** e **padrões de execução de hedge fund**
como referência — explicitamente "apenas como referência", não como adoção.
Pesquisa feita 2026-08-12, resumo do que se aplica e do que não:

### 12.1 SR 26-2 — o que é e por que serve de referência

`SR 26-2` é orientação revisada de **Model Risk Management**, emitida
conjuntamente por Federal Reserve/OCC/FDIC em abril de 2026, substituindo a
`SR 11-7` (2011) que era o padrão de-facto da indústria há 15 anos. [Fonte:
Federal Reserve, SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm).
Não se aplica a este projeto por jurisdição — este não é um banco
supervisionado, não tem board, não tem US$ 30 bilhões em ativos (tem
US$ 196,85). **O que se aproveita é a TAXONOMIA, não a burocracia:**

- **3 pilares de validação** — Solidez Conceitual (design/premissas antes
  de tudo), Análise de Resultado (previsto vs. real), Monitoramento
  Contínuo (gatilho de risco, não calendário fixo). Isso organiza as 16
  perguntas de `project_assurance` (§12 lá) em 3 blocos em vez de uma lista
  plana de 16 — mais fácil de lembrar e de saber ONDE um achado novo
  pertence.
- **"Effective challenge" por qualidade, não por posição organizacional**
  — SR 26-2 é explícito que revisão independente não precisa de um
  departamento separado, precisa de expertise E independência de fato. Isso
  valida diretamente a solução do §2: um segundo `Agent`, não um segundo
  humano que não existe neste projeto.
- **Materialidade por 4 eixos** (exposição financeira, peso da decisão,
  complexidade, contexto de uso) — adaptado no §6.1/§4 de
  `project_assurance` pra substituir a heurística binária original.

**O que NÃO se importou:** cadência regulatória fixa, exigência de comitê,
validação anual obrigatória, documentação para auditor externo — nada disso
serve a um projeto de 1 desenvolvedor e seria burocracia pura, violando o
próprio princípio 7 (adaptar ao contexto) deste plano.

### 12.2 Padrões de execução de hedge fund — referência futura, não retroativa

Pesquisa (TCA — Transaction Cost Analysis, best execution) confirma que
fundos sistemáticos usam TCA como ferramenta CONTÍNUA de avaliação de
qualidade de execução, não só relatório periódico — e que governança de
research/versionamento de modelo/capacidade de aposentar modelo é o que
diferencia due diligence séria de superficial. **Isso não vira trabalho
agora:** `src/execution/` ainda não tem caller de produção
(`docs/refactor_gk_canonico.md` item 5 confirma isso pro `sizing.py`) — TCA
sem execução real pra medir é análise de dado que não existe. Fica marcado
aqui como referência **para quando** `execution`/`backtest` forem
implementados: a métrica que vai importar (slippage vs. mid, não só custo
maker/taker teórico) já está identificada, não vai precisar de pesquisa
nova naquele momento.

---

## 13. Decisão pendente: `CLAUDE.md` "Documento mestre" <a name="13"></a>

`CLAUDE.md`, linha 4, declara: `Documento mestre: PRD_V3_2_UNIFICADO.md`.
Isso foi escrito antes deste plano existir — e antes até do `PRD_V4_1.md`
existir como o blueprint técnico corrente (o próprio `CLAUDE.md` já cita
`PRD_V4_1.md` em vários pontos sem ter atualizado essa linha original).

Com a elevação de status deste documento (v1.0→v1.1, §0), a leitura mais
consistente seria:

```
Documento mestre: PLANO_MESTRE_PRINCE2.md (governança + Product Breakdown
Structure completo, §11) — blueprint técnico corrente em PRD_V4_1.md,
regras de execução no restante deste arquivo.
```

**Não apliquei esta mudança.** `CLAUDE.md` é o único documento deste repo
com autoridade de override explícita sobre qualquer comportamento padrão —
mudar a frase que declara SUA PRÓPRIA posição na hierarquia institucional é
uma decisão sobre a hierarquia, não uma correção mecânica de texto
desatualizado (o caso do §1.4 do PRD, corrigido sozinho numa sessão
anterior, era diferente: lá eu havia registrado algo factualmente falso
sobre o PRD; aqui é uma decisão de qual documento manda, que é sua por
princípio 3, papéis definidos). Se você aprovar, é uma edição de uma linha
— fica pronta assim que confirmar.

---

## Fontes desta pesquisa

- [PRINCE2.com — Os 7 princípios, temas e processos](https://www.prince2.com/eur/blog/the-7-principles-themes-and-processes-of-prince2)
- [Axelos — Tailoring PRINCE2 projects](https://www.axelos.com/resource-hub/blog/tailoring_prince2_projects)
- [Projex Academy — Tailoring PRINCE2 para projetos pequenos/simples](https://www.projex.com/tailoring-prince2-for-simple-projects/)
- [Projex Academy — Tailoring PRINCE2 7ª edição para projetos pequenos](https://www.projex.com/how-to-tailor-prince2-7th-edition-for-small-projects/)
- [Projex Academy — A técnica de Quality Review](https://www.projex.com/demystifying-the-prince2-quality-review-technique/)
- [Purple Griffon — O que há de novo no PRINCE2 7](https://purplegriffon.com/blog/whats-new-in-prince2-7)
- [Knowledgehut — Guia de documentos PRINCE2](https://www.knowledgehut.com/blog/project-management/prince2-documents)
- [SR 26-2 — Revised Guidance on Model Risk Management, Federal Reserve/OCC/FDIC, abril/2026](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm)
- [Domino.ai — SR 26-2 explicado, estrutura de 3 pilares de validação](https://domino.ai/data-science-dictionary/sr-26-2)

---

## Changelog

- **v1.2 (2026-08-12)** — Leitura completa de `PRD_V3_2_UNIFICADO.md`
  (TOC + Partes XVI-XIX) a pedido do Manager, pra achar o que faltava
  incluir aqui. §11.2 corrigido: V3.2 não é "histórico", é obsoleto só no
  ESCOPO (BTC-only) — a arquitetura (Partes I-XV, XVI-XIX) continua viva,
  V4.1 é emenda de escopo sobre ela, não substituto. §3 princípio 1
  expandido: o pré-registro original (§16.9/RF-032, `pre_registro` YAML +
  7 critérios de encerramento do PROJETO + anti-HARKing) estava ausente,
  só o critério mais estreito da emenda V4.1 (§6.5) estava citado. §11.1
  ganha 3 linhas que faltavam: `docs/T0_4_TRIAGEM.md` (omitido por
  descuido, não julgamento — corrigido com nota explícita), Parte XIX do
  V3.2 como 4º tipo de log (rastreabilidade/lições de elaboração,
  distinto de SPRINT_LOG/evidence_ledger/architecture_gaps_log),
  `config/venue_changelog.yaml`. §8 ganha nota sobre proveniência
  cross-project da metodologia de auditoria (V3.2 §18.7.1 cita projeto
  irmão "Laplace_Quant_V16"; este ambiente tem um roster de agentes
  "Laplace_Quant V17" ativo — fato verificável, não ação nova).
- **v1.1 (2026-08-12)** — Elevação de status: de "camada de governança sobre
  o PRD" para base da verdade institucional (§0). Fecha §2/§6.2 por padrão
  (Manage by Exception). Adiciona §11 (Product Breakdown Structure — mapa
  completo, por inspeção real do repo), §12 (SR 26-2 e padrões de execução
  de hedge fund como referência de taxonomia, não adoção de framework), §13
  (decisão pendente sobre `CLAUDE.md` "Documento mestre" — escalada, não
  aplicada unilateralmente). Skill `project_assurance` criada e referenciada
  em §2/§6.1/§6.4, substituindo a menção em prosa por ferramenta operável.
- **v1.0 (2026-08-12)** — Criação. Pesquisa da metodologia oficial PRINCE2,
  adaptação a 2 papéis (Manager + Claude), Protocolo de Pacote de Trabalho
  por Arquivo (§6).
