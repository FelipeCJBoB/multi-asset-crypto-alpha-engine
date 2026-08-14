# PLANO INSTITUCIONAL DE CONSTRUÇÃO — Binance_Futures

**Também referido como:** Plano Mestre do Projeto (nome original deste
arquivo — mantido como identidade de arquivo/git, ver §0 sobre por quê).
**⚠️ Correção de identidade, 2026-08-12 (achado do Manager, §15):** este
documento chamava o projeto de "BTCUSDT Quant Engine" até v1.6 — **errado**.
O projeto **não é** um motor BTCUSDT. É um **Motor Quant multi-timeframe
(M15, M30, H1) e multi-par (BTC, ETH, SOL, BNB, XRP), bidirecional (long e
short)**, cujo objetivo é adaptar o antigo projeto BTC-only para um motor
onde cada estágio do pipeline (`src/`) suporta **comparação entre múltiplos
modelos/métodos concorrentes** — o padrão que `volatility.py` (M1, 6
candidatos comparados) já estabeleceu, generalizado pra toda a árvore.
Definição registrada pelo Manager, verbatim (§15.1). O rótulo "BTCUSDT
Quant Engine" não aparece mais neste documento a partir daqui.
**Versão:** 2.2 · **Data:** 2026-08-12
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
oferece — ver §0 e §13: a última peça dessa inversão (a linha "Documento
mestre" do `CLAUDE.md`) foi fechada em 2026-08-12, aprovação do Manager.

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

## 0. Três decisões fechadas <a name="0"></a>

**Duas fechadas por padrão (Manage by Exception — princípio 4, §3): eu
adoto e sigo a partir de agora, você ajusta se discordar, em vez de esperar
aprovação explícita antes de continuar. A terceira (CLAUDE.md) foi
escalada corretamente e fechada por aprovação explícita sua, 2026-08-12 —
não é caso de Manage by Exception, era decisão de hierarquia institucional
mesmo (§13).**

1. **§2 (papéis):** opção 3 — revisão independente via `Agent` obrigatória
   por padrão (skill `project_assurance`, criada 2026-08-12), escalonamento
   pra você só quando o achado for de escopo/negócio, não de engenharia.
2. **§6.2 (formato da Descrição de Produto):** template adotado como está.

Razão de fechar por padrão em vez de perguntar: o próprio v1.0 deste
documento já argumentava (§3, princípio 4) que pausar pra aprovação de todo
detalhe operacional é o oposto de "gerenciar por exceção" — só volta pra
você o que for exceção de verdade. Papéis e template não são isso.

**Fechada em 2026-08-12 — "Autorizado, eu aprovo" (Manager):** `CLAUDE.md`
linha 5 mudou de "Documento mestre: `PRD_V3_2_UNIFICADO.md`" para
"Documento mestre: `PLANO_MESTRE_PRINCE2.md`" (v1.6, ver §13 — a proposta
de uma linha ficou pronta e foi aplicada assim que aprovada, nada além do
que estava escrito).

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
13. [Decisão fechada: `CLAUDE.md` "Documento mestre"](#13)
14. [Road_Map Vivo — HTML, atualizado a cada mudança de status](#14)
15. [**Descoberta de Engenharia de `src/` — o Motor Quant multi-ativo validado contra o código**](#15) — resposta ao pedido de refatoração completa

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

**Honestidade sobre o histórico, exigida pelo próprio achado AG-003
(§7):** até o primeiro ciclo real deste documento (2026-08-12), os dois
únicos achados reais em `architecture_gaps_log.yaml` vieram do Manager
(AG-001) e de autorrevisão na mesma sessão do produtor (AG-002) — nenhum
do Agent independente que este parágrafo propõe. Ou seja: o mecanismo
central desta seção tinha **0/2 de histórico prospectivo** até ser
testado de verdade em `PLANO_MESTRE_PRINCE2.md` (AG-003, achado real
pelo Agent independente — ver §14). Um resultado, não é prova estatística
de nada ainda, mas é o primeiro ponto de dado a favor. Tratar isso como
"mecanismo comprovado" antes desse primeiro ciclo teria sido exatamente o
tipo de confiança sem base que este projeto inteiro existe para evitar.

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
que uma decisão de arquitetura maior — ex. "GK devia ser o estimador
padrão do projeto?" — está implícita e não decidida. **Desambiguação de
termo (achado AG-003):** "canônico" foi usado neste repo pra duas coisas
diferentes — a ESCOLHA de qual estimador é o certo (decidida, 2026-08-11,
`docs/refactor_gk_canonico.md`) e o ESTADO de produção (`labels/`
reprocessado com ele, ainda não feito, mesma recomendação registrada em
`docs/refactor_gk_canonico.md` §"Recomendação registrada"). Este é o tipo
de decisão que é Managing by Exception (princípio 4) aplicado ao
processo: eu paro, reporto, você decide, depois eu continuo.

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

**Nível de granularidade desta tabela: diretório, não arquivo.** Para o
inventário file-by-file (~85 arquivos, consumidor real citado por
arquivo, prontidão multi-ativo/TF), ver §15 — que também é a correção
registrada de um erro real desta seção: o §15.5 item 2 documenta que
esta tabela, sozinha, deu impressão de cobertura completa sem nunca ter
sido verificada no nível que decisão de engenharia exige.

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

## 13. Decisão fechada: `CLAUDE.md` "Documento mestre" <a name="13"></a>

**Status: aplicada, 2026-08-12** — "Autorizado, eu aprovo" (Manager).
`CLAUDE.md` linha 5 dizia `Documento mestre: PRD_V3_2_UNIFICADO.md`,
escrito antes deste plano existir e antes até do `PRD_V4_1.md` existir
como blueprint técnico corrente. Passou a dizer, em `CLAUDE.md` v1.6:

```
Documento mestre: PLANO_MESTRE_PRINCE2.md (governança institucional +
Product Breakdown Structure completo, §11) — aprovado pelo Manager,
2026-08-12. Blueprint técnico corrente em dois níveis: arquitetura/
contratos em PRD_V3_2_UNIFICADO.md, emenda de escopo multi-ativo em
PRD_V4_1.md.
```

Exatamente a proposta que estava escrita aqui — nenhuma mudança de
conteúdo além do aprovado, edição de uma linha, aplicada assim que
confirmada (a decisão de qual documento organiza qual continua sendo sua;
o quê tecnicamente manda — os contratos do V3.2, a emenda do V4.1 — não
mudou nem podia mudar por decisão de rótulo).

---

## 14. Road_Map Vivo <a name="14"></a>

**https://claude.ai/code/artifact/a6335e1a-1eb1-42ae-b3af-9b43b87ea3dd**

Mapa ponta a ponta em HTML, publicado a pedido do Manager 2026-08-12,
**vivo** — Claude republica a mesma URL a cada mudança de status ou Área
nova/removida (não um retrato único). Conteúdo: as duas trilhas
reconciliadas explicitamente em vez de forçadas numa sequência única
inventada —

- **Trilha de Sprints** (`PRD_V3_2_UNIFICADO.md` §14.3) — arquitetura/
  infraestrutura, Sprint 0-18, posição atual marcada (Sprint 4).
- **Trilha de Camadas** (`PRD_V4_1.md` Parte VIII) — a emenda de escopo
  multi-ativo, V41-0 a V41-12, com o ponto de reconvergência explícito em
  V41-5 (as duas trilhas voltam a ser uma só a partir daí — o documento
  não finge saber o meio do caminho que ainda não foi medido).
- Tabela de decisões abertas/fechadas (a mesma linha de raciocínio da
  resposta anterior nesta conversa, agora com status atualizado: `CLAUDE.md`
  fechado, recomendação de GK registrada, ciclo do §6 fechado).
- Cartões de governança (skills, `architecture_gaps_log` com as 3 entradas).
- Log do próprio Road_Map — quando cada mudança de status aconteceu, à
  parte do changelog deste documento (são registros de granularidade
  diferente: este documento versiona a si mesmo; o Road_Map versiona o
  ESTADO do projeto).

**Atualização — reconciliação visual com §15 (2026-08-12, a pedido do
Manager):** o Road_Map ganhou uma seção "Modelo de Estágios de
Engenharia" — os 15 estágios de §15.4 lado a lado (Data/ML/Live Trading
Layer), cada um com prontidão real e bloqueador citado, mais um callout
conectando explicitamente M1/M5/M6 (trilha de Camadas, QUANDO o trabalho
acontece) aos estágios 04/13/07 (modelo de engenharia, O QUE EXISTE DE
VERDADE). Os dois eixos — tempo e arquitetura — agora num lugar só, não
dois documentos separados.

**Atualização — T0.5 investigado, critério #3 reavaliado e fechado
(2026-08-12, mesma sessão):** T0.5 **está feito** (commit `5d8c8aa`,
2026-08-10) e dispara o critério de encerramento #3 (`PRD_V4_1.md` §6.5).
Reavaliação pedida pelo Manager ("vamos reavaliar escopo agora") e
confirmada: **não encerrar**. No processo, uma pergunta técnica direta do
Manager expôs um erro meu — eu tinha conectado o `pnl_execução` (-17,11)
ao achado de fill real (42,2%) sem verificar se o número usava esse fill;
não usava (usa o fill simulado ~97% do Label Engine). Corrigido em
`PRD_V4_1.md` §6.5, `CLAUDE.md` e no Road_Map Vivo (§14, link acima), que
tem o alerta completo. Decisão final: M5 (fill, escopo completo) e M6
(fator comum — testa se o problema é específico do BTC) priorizados antes
de M4 (único item pago da Camada 1). Este foi o item de maior prioridade
real desta rodada, maior que qualquer item de processo acima — e o
melhor teste, até aqui, de que "medir antes de afirmar" vale pra mim
também, não só pros números do PRD.

---

## 15. Descoberta de Engenharia de `src/` — o Motor Quant multi-ativo validado contra o código <a name="15"></a>

**Contexto do pedido.** O Manager afirmou ter pedido, antes desta sessão,
que todos os arquivos de `src/` fossem refatorados por causa da mudança de
escopo — e que isso "não foi levado a sério". Evidência concreta do
sintoma: este documento, até v1.6, ainda se chamava a si mesmo "BTCUSDT
Quant Engine" no cabeçalho, enquanto o próprio `PRD_V4_1.md` (que este
documento organiza) já era uma emenda multi-ativo há dias. Isso é um furo
real de consistência que passou por múltiplas revisões deste mesmo
documento sem ser pego — a crítica procede. Corrigido no cabeçalho acima;
esta seção é a resposta de engenharia completa, não só o pedido de
desculpas.

### 15.1 Definição do projeto (registrada pelo Manager, verbatim)

> É uma Motor Quant multi time-frame M15, M30 e H1, multi par SOL, BTC,
> ETH, XRP, BNB, bidirecional Long e Short com objetivo de adaptar o ex
> projeto morto de BTCUSDT only para o novo Motor Quant, afim de
> "comparison" diversos modelos e combinações entre a arvore pipeline de
> `src/` (assim como fizemos com volatility).

Duas implicações técnicas diretas desta definição, que este documento não
tinha capturado antes:

1. **"Comparison" não é um recurso do estágio de volatilidade — é o padrão
   arquitetural que TODO estágio deveria seguir.** `VolatilityEstimator`
   (Protocol + N implementações + harness de comparação) é o exemplo
   único hoje; o objetivo declarado é generalizar esse padrão (interface
   pluggable + comparação medida) para barra, regime, features, barreiras,
   learner, calibração — não é um caso especial isolado, é o modelo de
   referência.
2. **Multi-ativo/multi-TF não é um parâmetro a mais em funções existentes
   — é uma restrição estrutural**, do mesmo tipo que o lote mínimo do BTC é
   uma restrição estrutural (CLAUDE.md, "Comportamento esperado"). Um
   código que aceita `symbol` como kwarg mas nunca foi exercitado fora de
   BTCUSDT não está "pronto para multi-ativo" — está "não-hostil a
   multi-ativo", uma diferença que a descoberta abaixo torna concreta.

### 15.2 Metodologia — não presumir, verificar

6 agentes `Explore` independentes, cada um restrito a 2-4 pacotes de
`src/` (nenhuma sobreposição), instruídos a: (a) listar todo `.py` real
(exclui `__pycache__`), (b) citar consumidor real via grep — nunca
"deveria consumir" —, (c) citar hardcode de símbolo/TF com número de
linha, (d) mapear cada arquivo ao estágio candidato da lista do Manager
ou declarar que não mapeia. Nenhum agente teve acesso ao raciocínio dos
outros — achados convergentes (ex. "REGIME depende de FEATURES", achado
independentemente pelo agente de `features+regime`, consistente com o
diagrama de import do CLAUDE.md quando lido com cuidado) carregam mais
peso que achados isolados.

**Resultado completo (todos os ~85 arquivos, tabela file-by-file):**
**https://claude.ai/code/artifact/38dea9cf-8ead-454c-9fbc-b7e3809ff4c8**

Resumo por camada abaixo — não repete o detalhe do artifact, só a síntese
necessária pra validar/corrigir a proposta do Manager.

| camada | pacotes | prontidão real |
|---|---|---|
| DATA — ingestão/checagem | `exchange/`, `data/` | **A mais pronta.** `symbol`/`tf` são parâmetros de primeira classe já exercitados em `lake.py`/`resample.py`/`download.py` (`DEFAULT_SYMBOLS` cobre os 5 desde o Sprint 3) |
| DATA — vol/regime/features | `features/`, `regime/` | Parcial. Infra de path multi-TF existe mas TF hardcoded em 2 pontos-chave (`_sources.py`, `stress.py`); thresholds globais, não por (symbol,tf) |
| DATA — barreiras/label | `labels/` | Parcial. `symbol` real, **TF hardcoded em 3 lugares independentes** (`triple_barrier.py` 2x, `barrier_sweep.py` 1x) — `decision_tf_minutes` existe no config mas metade do código não o lê |
| ML | `models/`, `validation/` | **1,5 de 5 camadas de ablação do PRD implementadas**; DSR e os 14 testes de leakage existem mas não rodam automaticamente; `model_id` sem símbolo/TF no nome |
| LIVE TRADING | `risk/`, `execution/`, `live/`, `monitoring/` | **~5% implementado.** `risk/` é biblioteca real sem nenhum caller de produção e sem dimensão de símbolo; `execution/`≈0%; `live/`=pacote vazio; `monitoring/`=1 função nunca chamada |
| Suporte | `core/`, `backtest/`, `analysis/` | `core/` é contrato puro, correto como está; `backtest/` tem conteúdo real mas zero consumidor de produção; `analysis/` tem pelo menos 4 arquivos que informam `constants.yaml`/PRD mesmo excluídos do protocolo formal |

### 15.3 O pipeline de 17 estágios proposto — validado, com 6 correções justificadas

O Manager pediu para tratar a proposta como visão, não regra, e validar.
Veredito: **a decomposição em estágios e o agrupamento em 3 camadas estão
certos e são uma melhoria real sobre a ausência de modelo explícito que
este documento tinha até agora.** Seis pontos específicos, porém, não
sobrevivem ao confronto com o código real — cada um com evidência
citável, não opinião:

| # | proposta original | correção, com evidência |
|---|---|---|
| 1 | `04_REGIME` antes de `05_FEATURES` | **Invertido.** `regime/build.py:48` chama `features_build.build_t1_features(...)` antes de classificar; `classifier.py:432-436` lê colunas (`B07`, `C07`, `E02f`, `E27f`) que só existem porque Features já rodou. Não é preferência de design — é dependência de dado hard-coded. Correto: **FEATURES antes de REGIME**. |
| 2 | `03_VOLATILIDADE` como estágio upstream de regime/features | **Reclassificado.** Hoje `VolatilityEstimator` só alimenta `07_LABEL` — zero import em `features/build.py` ou `regime/`. FEATURES/REGIME ainda usam o ATR legado (`group_c.c01_atr_20`). Volatilidade não é "estágio 3" numa cadeia linear hoje — é um serviço que deveria ser injetado em pelo menos 2 pontos (features E labels) e hoje só chega a 1. |
| 3 | `06_BARREIRAS` como estágio separado antes de `07_LABEL` | **Não existe separação real ainda.** `tp_atr_mult`/`sl_atr_mult` vivem no mesmo `LabelConfig`/`config_hash` que fill e custo; `build_labels` resolve tudo numa função. `barrier_sweep.py` parece ser 06 mas na verdade lê fill/ATR já persistidos por 07 — é pós-07, não pré-07. Extrair 06 de verdade é trabalho de refatoração real, não uma reorganização de nome. |
| 4 | `08_META_LABEL` logo após `07_LABEL`, antes do learner | **Erro de categoria.** Zero código de meta-labeling em `src/labels/`. O "Meta Model" real do PRD consome predições OOF do Alpha (`predictions/alpha/{model_id}/predictions.parquet`) — que só existem depois do `10_LEARNER` treinar. Meta-label estruturalmente não pode vir antes do modelo primário existir. Reclassificado como estágio pós-learner (ver tabela §15.4). |
| 5 | `13_PESOS` na ML LAYER | **Não vive lá.** `sample_weight` é computado em `src/labels/weights.py` (DATA LAYER) e só consumido (nunca recalculado) em `alpha.py:229`. Não há módulo de pesos em `models/`/`validation/`. Movido pra DATA LAYER, dentro de `07_LABEL`. |
| 6 | `09_SPLIT_VALIDACAO` e `12_VALIDACAO` como duas fases distintas | **É o mesmo mecanismo (`cpcv.py::CPCVResult`) reusado**, não duas fases sequenciais — treina, audita vazamento e reconstrói caminho de backtest a partir do MESMO objeto de split. A distinção nominal do Manager aponta pra um gap real, mas o gap não é "faltam dois estágios", é "falta um GATE automático pós-calibração" (DSR + os 14 testes de leakage existem mas não rodam dentro de `pipeline.py` hoje — são scripts manuais órfãos). |

### 15.4 Modelo de estágios corrigido

```
DATA LAYER
  01_BARRA            src/data/{resample,lake,download}.py            ✅ pronto multi-ativo/TF
  02_DATA_CHECK        src/data/{checks,validate,schemas}.py           parcial, symbol nunca exercitado
  03_FEATURES          src/features/{build,support,groups/*}.py        TF hardcoded, thresholds globais
  04_VOLATILIDADE      src/features/volatility.py                      ilha — só alimenta labels hoje
  05_REGIME            src/regime/{build,classifier,stress}.py         depende de 03, corrigido de posição
  06_BARREIRAS         (não existe separado — dentro de labels/)       refatoração real necessária
  07_LABEL             src/labels/{triple_barrier,fill_model}.py       TF hardcoded 3x
  07b_PESOS            src/labels/weights.py                           movido da ML LAYER

ML LAYER
  08_SPLIT             src/validation/cpcv.py                          embargo hardcoded em 15m
  09_LEARNER           src/models/{alpha,monotonic}.py                 1,5/5 camadas PRD; stability.py órfã
  09b_CALIBRACAO       (inline em alpha.py — não separável hoje)
  10_VALIDACAO         src/validation/{dsr,leakage}.py                 existe, não wired em pipeline.py
  11_META_MODEL        (não existe — PRD §6.8, fora da V1)              movido de 08 pra cá, pós-learner

LIVE TRADING LAYER
  12_RISK_ENGINE       src/risk/{sizing,limits,kill_switch}.py         real, zero wiring, sem dimensão symbol
  13_EXECUCAO          src/exchange/adapter.py, src/execution/         ~0%, place_order NotImplementedError
  14_MONITORAMENTO     src/monitoring/logging.py                       1 função, nunca chamada
  15_FEEDBACK_POST_TRADE (não existe em nenhuma forma)                 100% green-field
```

Reduzido de 17 para 15 posições numeradas porque dois itens do Manager
(`06_BARREIRAS`, `09b_CALIBRACAO`) não são hoje estágios separáveis sem
refatoração — mantidos na lista como TRABALHO A FAZER, não renomeados
como se já existissem.

### 15.5 Erros identificados neste documento (PLANO_MESTRE_PRINCE2.md, pré-v2.0)

Falhas de desenho/planejamento/arquitetura encontradas nesta rodada,
listadas sem eufemismo — é o que o Manager pediu ("detectar falhas
ocultas"):

1. **Identidade desatualizada por 6 versões.** "BTCUSDT Quant Engine" no
   cabeçalho sobreviveu de v1.0 a v1.6 mesmo com `PRD_V4_1.md` (emenda
   multi-ativo) sendo citado como fonte técnica em todas elas. Nenhuma
   revisão própria (nem a auto-crítica de v1.2-v1.5) pegou isso — só uma
   leitura humana pegou. Corrigido nesta versão.
2. **Product Breakdown Structure (§11) parou no nível de diretório.** "Os
   11 estágios do pipeline: `src/exchange/`, `src/data/`, ..." dava a
   impressão de cobertura completa sem nunca ter aberto um arquivo. Um
   PBS que declara granularidade de diretório como se fosse suficiente
   pra decisão de engenharia é exatamente o tipo de "afirmação não
   re-verificada" que a pergunta #6 de `project_assurance` deveria ter
   pego antes — e não pegou, porque o §11 nunca passou pelo protocolo de
   revisão adversarial (só o documento inteiro passou, uma vez, em outro
   contexto, achando AG-003 sobre coisas diferentes).
3. **Sequenciamento de trabalho guiado por prioridade de MEDIÇÃO (M1→M5→M6
   do PRD), nunca confrontado com prontidão de ENGENHARIA.** Esta sessão
   executou M1 (volatilidade) e começou a planejar M5/M6 sem nunca
   verificar se `src/` como um todo suporta o "comparison... entre a
   árvore pipeline" que é o objetivo declarado do projeto. O achado desta
   seção (TF hardcoded em 4+ lugares, thresholds globais, `risk/` sem
   dimensão de símbolo) mostra que a resposta era "não, ainda não" — e
   isso deveria ter sido perguntado antes de propor M5/M6 como "próximos
   passos rápidos" (erro já corrigido nesta sessão, mas por acidente de
   verificação pontual, não por processo que perguntasse isso
   sistematicamente).
4. **§6.1 (quando o protocolo de Pacote de Trabalho se aplica) nunca foi
   testado contra um arquivo de `src/labels/`, `src/risk/` ou
   `src/execution/` de verdade** — só contra o próprio `PLANO_MESTRE_PRINCE2.md`
   (§10, ciclo 1). O primeiro teste real do protocolo continua pendente.
5. **Nenhum registro RAID (§7) capturava os bloqueadores estruturais de
   multi-ativo/TF antes desta seção** — eles existiam no código (TF
   hardcoded, thresholds globais) mas não existiam como ISSUE
   documentado em lugar nenhum do projeto. Corrigido com AG-004..AG-007
   abaixo.

### 15.6 Recomendação de sequenciamento — o que refatorar primeiro, e por quê

Não recomendo "refatorar tudo antes de continuar" — violaria o próprio
princípio de Manage by Exception e o histórico de "pare na primeira
camada que funcionar" do CLAUDE.md. Recomendo sequenciar pelo que
**bloqueia de verdade** o objetivo de comparação multi-ativo, não pelo
número do estágio:

1. **`validation/cpcv.py::_BAR_MS` hardcoded em 15m** — prioridade mais
   alta de TODOS os achados, porque é o único bloqueador que produziria
   um **erro silencioso** (embargo em unidade errada) em vez de um erro
   visível, se M2/M3 (timeframe) rodarem antes disso ser corrigido.
2. **Conectar a infra multi-symbol/TF que já existe mas está morta**
   (`regime_symbol_tf_dir`, `labels_symbol_tf_dir`,
   `predictions_symbol_tf_dir`) aos writers reais — não é código novo, é
   trocar o destino de escrita, baixo risco.
3. **Migrar `features/build.py`/`group_c.py` pro `VolatilityEstimator`**
   — fecha a duplicação de fórmula ATR (achado desta sessão E da
   anterior) e faz `03_FEATURES`/`05_REGIME` herdarem a escolha do GK
   automaticamente, sem trabalho extra.
4. **Rodar Feature+Label Engine pros outros 4 ativos** (já identificado
   na resposta anterior desta conversa, pré-requisito de M5/M6) — agora
   com o item 1 corrigido primeiro, pra não gerar dado errado silenciosamente.

   **Item 4 executado (2026-08-13) — engenharia de pipeline multi-ativo,
   não wiring.** Investigação (não implementação direta) achou que
   "rodar Feature+Label Engine" escondia dois blocos bem diferentes:

   - **Features e Regime NÃO são artefatos persistidos** — `dataset.
     build_modeling_frame` recomputa os dois em memória a cada chamada
     (~8s, já documentado no módulo). "Rodar Feature/Regime Engine pros
     4 alts" não exige escrever nada novo: `build_t1_features(symbol,
     ...)`/`build_regimes(symbol, ...)` já são 100% parametrizados por
     símbolo, sem hardcode de BTCUSDT — confirmado por leitura, não
     suposto.
   - **Labels PRECISAM ser persistidos** (simulação O(n) cara demais pra
     recomputar por chamada) — e aqui apareceram 3 achados reais, dois
     bloqueadores e um latente:
     1. **`mark_price_klines_1m` nunca existiu pros 4 alts** — confirmado
        via `ls data/capacity/mark_price_klines_1m/`, só BTCUSDT tinha.
        B11 exige essa fonte pra resolução de barreira; sem ela,
        `build_labels_for_symbol` falha por dado ausente. Resolvido:
        `download_mark_price_klines_1m` novo em `src/data/download.py`
        (URL confirmada via `binance/binance-public-data` + sondagem
        HTTP direta em 2 arquivos reais, 2026-08-13) — opt-in, mesmo
        padrão de `agg_trades`/`book_ticker`. No caminho, achado um
        SEGUNDO bug real (não corrigido, fora de escopo desta função):
        `download_klines_1m` trata incorretamente o regime `"daily"`
        pós-cutover como se 1 dia cobrisse o mês inteiro — nunca
        exercitado em produção (manifest só vai até 2022-12), registrado
        como **AG-014**.
     2. **`build_modeling_frame` tinha um bug real e mais grave, achado
        no caminho** — `symbol` nunca chegava a `cpcv.load_labels_v1()`
        (sempre carregava BTCUSDT por default), então mesmo com
        `labels/` gerado pros 4 alts, todo treino continuaria
        silenciosamente usando alvo do BTC contra features de outro
        ativo. Bloqueava M5/M6 de forma mais fundamental que a falta de
        dado — registrado e corrigido como **AG-015**.
     3. Filtros de exchange: só 1 snapshot canônico no disco
        (2026-08-08), cobrindo os 5 símbolos — `historical_filters_
        fallback=True` obrigatório pra qualquer data histórica, mesmo
        mecanismo já usado no backfill original de BTCUSDT (não é achado
        novo, só confirmado).

     Escrito `src/labels/backfill_multi_symbol.py` (orquestra
     `build_labels_for_symbol`+`write_labels_atomic` pros 4 alts, layout
     chaveado T0.3 — a mesma infra que AG-006 achou sem caller de
     produção, agora com um) + testes. **`triple_barrier.py` (arquivo
     crítico) não foi tocado** — toda a correção ficou em módulos
     satélite (`dataset.py`, `download.py`, o módulo novo), preservando a
     cautela já estabelecida sobre esse arquivo.

     Sequência de comandos entregue ao Manager (protocolo de execução —
     Claude não roda `.py`): 1) backfill de `mark_price_klines_1m`, 2)
     `pytest` dos módulos tocados, 3) `backfill_multi_symbol` de verdade
     (escreve `data/labels/{ETH,SOL,BNB,XRP}USDT/15m/v1/labels.parquet`).

     **Os 3 passos executados pelo Manager (2026-08-14) — item 4 fecha
     de verdade.** `labels/` existe agora pros 4 alts pela primeira vez
     no projeto: ETHUSDT (328.409 linhas), BNBUSDT (328.409), XRPUSDT
     (327.448), SOLUSDT. Warning `labels.filters_fallback_used` em
     todos — esperado, mesmo mecanismo que o histórico de BTCUSDT já usa
     (`known_gaps.exchange_info_snapshot_coverage_gap`, Sprint 6, não é
     achado novo). É a prova de que a correção do AG-015 funcionou de
     ponta a ponta: sem ela, esses 4 arquivos existiriam no disco mas
     `build_modeling_frame`/treino continuariam ignorando-os
     silenciosamente. M5/M6 (represados desde a reavaliação do critério
     de encerramento #3) têm agora o pré-requisito de dado que faltava —
     decisão de quando rodá-los continua com o Manager.
5. Só depois disso, decisão do Manager sobre extrair `06_BARREIRAS` como
   estágio real (é refatoração de `triple_barrier.py`, arquivo crítico —
   passa pelo protocolo completo do §6, primeiro teste real dele).

**Item 1 executado (2026-08-12) — primeiro Pacote de Trabalho real do §6
em código de produção.** `src/validation/cpcv.py`: Descrição de Produto →
`CPCVConfig` ganha `tf` (default `"15m"` bit-exato) → `embargo_ms`
computado por `step_ms(cfg.tf)` em vez de constante fixa → 3 testes novos
→ 4 scripts mecânicos autorizados limpos → revisão independente via
`project_assurance` (Agent fresco, não retroativa). A revisão achou 2
coisas reais: um teste mais fraco do que o docstring alegava (corrigido
antes de fechar) e um footgun NOVO — `load_labels_v1(tf=...)` e
`CPCVConfig(tf=...)` são parâmetros independentes sem checagem cruzada,
registrado como **AG-009**, não escondido. AG-004 fecha como "aguarda
confirmação de pytest" — protocolo de execução não muda: eu não rodo o
teste, entrego o comando, o Manager confirma verde.

**Fechamento real (2026-08-13).** Primeira rodada do Manager achou o
teste de escala de embargo falhando (300 vs 140 observado, não 280
esperado pela versão fortalecida). Investigação (não afrouxar a
asserção — "nunca remediar, sempre solucionar", CLAUDE.md) achou a
causa raiz: com `horizon_bars=1` no fixture sintético, a linha de
treino logo à esquerda de cada fronteira de grupo de teste tem
`t1 == g_start` exatamente, satisfazendo a condição de *purge* e sendo
contada em `n_purged`, não `n_embargoed` (dedup proposital do próprio
código, `embargo_mask & ~purge_mask`). Esse desconto é 1 linha
constante por fronteira esquerda, não escala com `embargo_bars`/`tf` —
quebrava a razão exata 2× só nas 20 fronteiras esquerda de 40 totais
(`C(6,2)=15` splits). Fórmula derivada à mão bateu com os dois números
observados (`20×4+20×3=140`; `20×8+20×7=300`) — confirmando que
`generate_splits` estava **correto**; o bug era a premissa do teste.
Corrigido o *fixture* (`horizon_bars=0`, elimina a interação com
purge), não o código-fonte. Segunda rodada do Manager:
**34 passed in 1.78s**. AG-004 fecha de verdade — primeiro ciclo
completo do §6 (Descrição de Produto → implementação → revisão
independente → achado real em revisão → achado real em pytest →
causa raiz → correção → verificação humana) em código de produção.

### 15.7 Preparação de engenharia — AG-007 e AG-008 (2026-08-13)

Os dois achados restantes de §15.6 (AG-007, risco por-símbolo; AG-008,
migração de ATR) não são fixes mecânicos — o primeiro é redesenho real
de arquitetura, o segundo muda valores reais consumidos por modelos já
treinados. Antes de qualquer implementação, rodei pesquisa (2 `Agent`
paralelos, código real + PRD) preparando o terreno de decisão, e o
Manager fez sua própria verificação independente — bateu com a pesquisa
em praticamente todo fato verificável, corrigiu onde o vácuo era maior
do que eu tinha registrado, e acrescentou 3+3 achados novos. Detalhe
completo, não duplicado aqui, vive nos addenda `2026-08-13` das próprias
entradas AG-007/AG-008 em `audit/architecture_gaps_log.yaml` (o código/
dado é a fonte da verdade; este documento é um pointer, não a cópia).

**Resumo executivo:**

- **AG-007** — conta roda em `margin_mode: CROSSED` (PRD_V3_2 §8.6):
  `equity`/`daily_loss_usd`/`equity_peak_usd` são irredutivelmente de
  CONTA, não decomponíveis por símbolo pela própria exchange; só
  `daily_loss_usd`/`consecutive_losses`/nocional são genuinamente
  decomponíveis via trade ledger (`GET /fapi/v1/income`, `REALIZED_PNL`
  por símbolo). Vácuo maior do que "zero caller": também "zero fonte" —
  nenhum módulo de reconciliação de conta existe ainda. **Decisão: não
  redesenhar agora** — schema especificado no vácuo é o mesmo tipo de
  erro que já motivou a correção do `control_10_risco_real`. Addendum
  registrado para quando `risk/` ganhar o primeiro caller real.
- **AG-008** — lacuna real achada: M1 mediu QLIKE (previsão), nunca a
  diferença de NÍVEL entre GK/Wilder no mesmo bar, que é o que decide se
  `econ_regime` desloca. **Decisão: medir agora, em shadow mode** — não
  escreve `constants.yaml`, não regrava `labels/`, não retreina, não
  consome `N_lifetime` (mesma categoria já aprovada da extensão RS/YZ).
  Implementado `src/analysis/gk_vs_wilder_econ_regime_shift.py` +
  testes — mede `median_abs_relative_diff`, `fraction_econ_regime_
  changed`, `adjusted_rand_index` (reaproveita o instrumento que
  PRD_V4_1.md §4.5 já propõe para equivalência de regime BTC-derivado,
  não inventa métrica nova). Decisão de PROMOÇÃO continua represada até
  M2/M3, como já decidido em `docs/refactor_gk_canonico.md`.

  **Resultado medido (2026-08-13) — a hipótese "desprezível" está
  descartada.** Rodado sobre os 5 ativos, história completa: `adjusted_
  rand_index` 0,556–0,618, `fraction_econ_regime_changed` 15,5%–17,7%,
  `median_abs_relative_diff` 33,2%–34,9% — consistente entre os 5 ativos
  independentes (descarta coincidência de amostra). ARI nessa faixa é
  divergência real, não ruído; o nível divergir ~33-35% enquanto o
  ranking (ARI) também diverge de forma substancial confirma que GK não
  é um mero fator de escala sobre Wilder (um fator de escala constante
  preservaria o ranking por construção, dando ARI≈1,0) — é diferença
  real de forma entre os dois estimadores. Não muda o sequenciamento já
  decidido (promoção continua represada até M2/M3), mas informa que a
  migração, quando acontecer, precisa ser tratada como mudança real de
  ambiente de treino — retreino + reavaliação de métricas estratificadas
  por regime econômico —, não como troca de fórmula cosmética. Detalhe
  completo (tabela por símbolo, relatório): addendum de AG-008 em
  `audit/architecture_gaps_log.yaml` e `experiments/gk_vs_wilder_econ_
  regime_shift_report.json`.

### 15.9 AG-013/014 delegados, M6 implementado, M5 pausado por achado real (2026-08-14)

**AG-013/AG-014 delegados a Agents com contexto rico**, mesmo padrão da
rodada anterior — revisados independentemente antes de commitar (diff
lido, scripts mecânicos rerodados por mim). AG-013: `models/*/
diagnostics/` ganha layout chaveado `models_diagnostics_symbol_tf_dir`
(`src/models/_paths.py`), default bit-exato preservado porque esses JSONs
são intencionalmente versionados no git. Achado no caminho, não
corrigido: `run_layer1_sprint`/`run_e02f_short_unforced_variant` ainda
não fiam `dest_dir` pra diagnostics mesmo com `tf` explícito —
**AG-016**, aberto. AG-014: `download_klines_1m` corrigido pra fazer 1
request por dia no regime `"daily"` pós-cutover (mesmo padrão de
`download_mark_price_klines_1m`, escrita na rodada anterior
especificamente pra não repetir esse bug).

**M6 (fator comum) implementado e pronto** —
`src/analysis/m6_common_factor_hypothesis.py`. Confirmado antes de
escrever qualquer código: `edge_bruto_atr`/`custo_atr` vêm só de
`labels.parquet::barrier_hit`/`atr_at_t0` (`src.analysis.feasibility`,
já existente) — nenhum modelo treinado necessário, zero trials genuíno,
sem ambiguidade. Instrumento de falsificação: heterogeneidade de
meta-análise (Cochran's Q/I², DerSimonian & Laird 1986) sobre
`edge_bruto_atr` por símbolo com erro-padrão derivado da variância
multinomial de `frac_TP`/`frac_SL` — mesma classe de instrumento formal
que M4 já usa (Rand ajustado). Comando de execução entregue ao Manager,
ainda não rodado.

**M5 (fill completo) — pausado, achado real antes de gastar orçamento.**
Reli a definição exata do PRD: "escopo completo" exige não só `labels/`
(já feito) mas `predictions.parquet` (via Alpha/CPCV) e `orders.parquet`
(via `fill_simulator`, que já lê `data/raw/book_ticker/` — confirmado
presente pros 5 ativos, 320 arquivos cada) pros 4 alts, dentro da janela
real de `bookTicker` (2023-05-16→2024-03-30). Isso significa treinar
Alpha pela primeira vez pra 4 símbolos novos — e `audit/n_lifetime.yaml`
mostra, em precedentes reais (ids 11/13/14 vs. id 12), que **o Manager
decide explicitamente, caso a caso, se um retreino/variante conta como
trial** — não é uma regra mecânica que eu deva aplicar sozinho, nem
assumir "0 trials" do texto do PRD sem essa confirmação (o próprio PRD já
foi corrigido por decisão do Manager quando o texto e o comportamento
divergiram, várias vezes nesta sessão). Não decidi isso unilateralmente —
apresentado ao Manager para a mesma decisão explícita que os ids
11/13/14 já tiveram, antes de treinar qualquer coisa nos ~15 trials
restantes do orçamento (M4 sozinho ainda precisa de até 6).

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

- **v2.9 (2026-08-14)** — §15.9: AG-013/AG-014 delegados e fechados
  (achado no caminho: AG-016, diagnostics ainda não fiado nos
  orquestradores reais). M6 implementado e pronto pra rodar — zero
  trials confirmado (`edge_bruto_atr` só precisa de `labels.parquet`).
  M5 pausado deliberadamente: escopo completo exige treinar Alpha pra 4
  símbolos novos, e o ledger de `N_lifetime` mostra que essa decisão
  (conta como trial ou não) é do Manager caso a caso, não uma regra que
  eu aplico sozinho — apresentado para decisão explícita antes de gastar
  orçamento.
- **v2.8 (2026-08-14)** — §15.6 item 4 fecha de verdade: Manager rodou os
  3 comandos (backfill de `mark_price_klines_1m`, `pytest` verde,
  `run_and_write_labels_for_alts`). `labels/` existe pela primeira vez
  pros 4 alts (ETHUSDT/BNBUSDT 328.409 linhas, XRPUSDT 327.448, SOLUSDT).
  Warning `labels.filters_fallback_used` em todos — confirmado como
  comportamento esperado (mesmo mecanismo já usado pelo histórico de
  BTCUSDT, `known_gaps.exchange_info_snapshot_coverage_gap`), não um
  achado novo. Pré-requisito de dado do M5/M6 satisfeito.
- **v2.7 (2026-08-13)** — §15.6 item 4 executado: engenharia de pipeline
  multi-ativo (não wiring simples). Achado central: features/regime já
  são 100% multi-símbolo (recomputados em memória, sem hardcode) — o
  bloqueio real era em `labels/` (persistido, caro de recomputar). 3
  achados: `mark_price_klines_1m` nunca existiu pros 4 alts (resolvido,
  `download_mark_price_klines_1m` novo, URL verificada via web research
  + sondagem HTTP real); `download_klines_1m` tem um bug real não
  exercitado no regime diário pós-cutover (AG-014, não corrigido, fora
  de escopo); `build_modeling_frame` nunca passava `symbol` pra
  `load_labels_v1` — bug mais grave que a falta de dado, teria deixado
  todo treino multi-ativo usar alvo do BTC silenciosamente (AG-015,
  corrigido). `triple_barrier.py` não foi tocado. Novo módulo
  `src/labels/backfill_multi_symbol.py` orquestra a geração real dos 4
  ativos — comando ainda não executado pelo Manager.
- **v2.6 (2026-08-13)** — Manager rodou a medição shadow-mode do AG-008
  (`uv run pytest` verde, 4 passed, depois `uv run python -m src.analysis.
  gk_vs_wilder_econ_regime_shift` sobre os 5 ativos). Resultado real:
  `adjusted_rand_index` 0,556–0,618, `fraction_econ_regime_changed`
  15,5%–17,7%, `median_abs_relative_diff` 33,2%–34,9% — consistente nos
  5 ativos, hipótese "desprezível" descartada. Não muda a decisão de
  sequenciamento (promoção continua represada até M2/M3), mas quantifica
  que a migração GK, quando acontecer, é mudança real de ambiente de
  treino, não troca cosmética de fórmula. §15.7 e `audit/architecture_
  gaps_log.yaml` (addendum AG-008) atualizados com a tabela completa.
- **v2.5 (2026-08-13)** — §15.7: preparação de engenharia para AG-007
  (risco por-símbolo) e AG-008 (migração ATR), pedida pelo Manager antes
  de qualquer implementação (nenhum dos dois é fix mecânico). Pesquisa em
  2 Agents paralelos + verificação independente do Manager (bateu com a
  pesquisa em quase tudo, corrigiu o tamanho real do vácuo em AG-007 —
  "zero caller" era só metade do problema, também "zero fonte" — e
  acrescentou o critério de decomponibilidade real via trade ledger da
  Binance). AG-007: decisão de não redesenhar agora, addendum guardado no
  ledger. AG-008: decisão de medir em shadow mode antes de decidir rota —
  implementado `src/analysis/gk_vs_wilder_econ_regime_shift.py`, mede o
  que faltava (diferença de NÍVEL entre GK/Wilder, não só QLIKE de
  previsão) reaproveitando o instrumento de Rand ajustado que PRD_V4_1.md
  §4.5 já propõe. Não consome N_lifetime nem escreve produção — só
  medição. Comando de pytest entregue ao Manager, ainda não confirmado.
- **v2.4 (2026-08-13)** — 3 Pacotes de Trabalho do §6 delegados a Agents
  em paralelo (AG-005, AG-006, AG-009 — arquivos não sobrepostos), cada
  um com contexto rico e protocolo de execução explícito, primeira vez
  que a delegação a agentes é usada pra correções mecânicas em série (não
  só para revisão independente). Antes de delegar: recalibrei o escopo
  do AG-006 (grep real achou que só 1 dos 3 writers tinha caller de
  produção — a suposição original estava imprecisa) e achei/corrigi uma
  corrupção de chaves YAML duplicadas em AG-008 (virou AG-010, ironia
  reconhecida: furo na própria ferramenta de furos). Revisão independente
  de cada resultado antes de commitar, não confiança cega no relato do
  Agent: AG-009 aceito após reler o diff e rerodar os 4 scripts
  mecânicos; AG-005 aceito após verificar à mão que a matemática de
  `date + timedelta` (Python trunca componentes sub-dia) nunca sub-cobre
  o horizonte real; AG-006 devolvido uma vez — a 1ª versão do Agent
  quebrava a bit-exatidão do default (migraria o destino de escrita real
  de `run_layer1_sprint`, orfanando 7 leitores de produção que dependem
  do caminho legado), corrigida na 2ª rodada com um parâmetro sentinela.
  2 achados novos, não fabricados nem corrigidos fora de escopo,
  reportados pelos próprios Agents: AG-011 (terceiro hardcode de "15m"
  em `cost_surface.py`) e AG-012 (segundo caller real de
  `write_predictions_atomic`). AG-007 (redesenho real do `risk/`) e
  AG-008 (migração de ATR que muda valores reais de modelo) ficaram de
  fora da delegação — não são mecânicos, precisam de decisão do Manager.
  **Fechamento real (2026-08-13):** Manager rodou os 3 pytest juntos —
  **106 passed in 9.83s**. AG-005, AG-006 e AG-009 fecham de verdade.
- **v2.3 (2026-08-13)** — AG-004 fecha de verdade: primeira rodada de
  `pytest` do Manager achou o teste de escala de embargo falhando (300 vs
  140, não 280/2× esperado) — investigado até a causa raiz em vez de
  afrouxar a asserção ("nunca remediar, sempre solucionar"). Achado: com
  `horizon_bars=1` no fixture sintético, a linha de treino logo à
  esquerda de cada fronteira de teste tem `t1 == g_start` exatamente,
  sendo contada em `n_purged` em vez de `n_embargoed` (dedup proposital
  do próprio `generate_splits`) — desconto de 1 linha CONSTANTE por
  fronteira esquerda, não escalável com `tf`, que quebrava a razão exata
  2× só nas 20 fronteiras esquerda de 40. Fórmula derivada à mão bateu
  com os dois números observados — `generate_splits` estava correto, o
  bug era a premissa do teste. Corrigido o *fixture* (`horizon_bars=0`),
  não o código-fonte. Segunda rodada: **34 passed in 1.78s**. Primeiro
  ciclo completo do §6 em produção fechado ponta a ponta.
- **v2.2 (2026-08-12)** — Executado o item 1 da recomendação de
  sequenciamento (§15.6): AG-004 corrigido em `src/validation/cpcv.py`,
  primeiro Pacote de Trabalho real do protocolo §6 rodado contra código
  de produção (não retroativo/self-referential como os ciclos anteriores).
  Revisão independente (`project_assurance`) achou AG-009 (novo — cross-
  check de `tf` ausente entre `load_labels_v1`/`CPCVConfig`) e uma
  fraqueza de teste, ambos corrigidos/registrados antes de fechar. AG-004
  fecha como "aguarda pytest" — protocolo de execução do CLAUDE.md
  intacto, comando entregue ao Manager, não rodado por Claude.
- **v2.1 (2026-08-12)** — Road_Map Vivo (§14) ganhou a reconciliação
  visual pedida: os 15 estágios de §15.4 renderizados lado a lado por
  camada (Data/ML/Live Trading), com prontidão e bloqueador por estágio,
  mais um callout ligando M1/M5/M6 (trilha de Camadas) aos estágios
  04/13/07 correspondentes. Cartão de governança e tabela de decisões do
  Road_Map atualizados com AG-004..008.
- **v2.0 (2026-08-12)** — Manager: "não levou a sério" o pedido anterior
  de refatorar `src/` inteiro pra nova amplitude do projeto — evidência
  concreta apontada: este documento ainda se chamava "BTCUSDT Quant
  Engine". Correção de identidade no cabeçalho (§0) + definição do
  projeto registrada verbatim (§15.1: motor multi-TF/multi-par/
  bidirecional, objetivo de comparação entre modelos em toda a árvore de
  `src/`, não um projeto BTC). 6 agentes `Explore` paralelos fizeram
  discovery file-by-file de todo `src/` (~85 arquivos, artifact completo
  linkado em §15.2) para validar a proposta de pipeline de 17 estágios
  do Manager contra o código real — 6 correções justificadas com
  evidência (REGIME depende de FEATURES, não o contrário; VOLATILIDADE é
  ilha isolada hoje; BARREIRAS não é separável de LABEL sem refatoração;
  META_LABEL é category error antes do LEARNER existir; PESOS vive no
  Label Engine, não na ML LAYER; SPLIT/VALIDACAO são o mesmo mecanismo
  CPCV reusado). Modelo de estágios corrigido publicado (§15.4). 5 erros
  de desenho identificados no próprio documento (§15.5), incluindo que o
  PBS do §11 nunca desceu a nível de arquivo. 5 novos achados de
  arquitetura registrados como AG-004..AG-008 (TF hardcoded em CPCV —
  risco de erro silencioso, o mais grave; TF hardcoded 3x em labels/;
  infra multi-symbol/TF existente mas morta; risk/ sem dimensão de
  símbolo; ATR duplicado entre volatility.py e o caminho legado).
  Recomendação de sequenciamento por bloqueio real, não por número de
  estágio (§15.6). Bump de versão maior (1.6→2.0) porque a correção de
  identidade e o novo modelo de estágios mudam como todo trabalho futuro
  deste projeto é enquadrado — não é incremento de conteúdo, é correção
  de norte.
- **v1.6 (2026-08-12)** — Manager disse "pode seguir" pra M5/M6.
  Verifiquei o disco (`data/labels/`, `predictions/alpha/`,
  `execution/fill_simulator/`, `data/raw/book_ticker/`) antes de escrever
  qualquer código — achado dois erros próprios, não do repo: (1)
  `PRD_V4_1.md` §2.4 dizia janela de `bookTicker` até 2025-11, o disco tem
  só até 2024-03; (2) eu tinha chamado M5/M6 "escopo completo, 0 trials"
  como rápidos — `labels`/`predictions`/`orders` só existem pra BTCUSDT,
  estender a 5 ativos exige Feature+Label Engine pros outros 4 primeiro.
  Corrigido em `PRD_V4_1.md`, `CLAUDE.md` v1.9, Road_Map Vivo. Terceira
  vez nesta sessão que verificar antes de escrever pegou algo que eu
  tinha dito com confiança maior do que os dados sustentavam — o padrão
  já é reconhecível o bastante pra virar rotina, não exceção.
- **v1.5 (2026-08-12)** — Reavaliação de escopo do critério de encerramento
  #3 fechada: "não encerrar", M5 (fill, escopo completo) e M6 (fator
  comum) priorizados antes de M4. No caminho, pergunta técnica direta do
  Manager ("como pnl_execução é calculado?") expôs que eu tinha conectado
  esse número ao fill real (42,2%) sem checar — não usava, usava o fill
  simulado (~97%) do Label Engine; corrigido em `PRD_V4_1.md` §6.5,
  `CLAUDE.md`, Road_Map Vivo. Autocrítica registrada: este documento
  cobra "meça antes de afirmar" de todo número do projeto — o mesmo
  padrão vale pra conexões que EU faço entre dois achados, não só pra
  constantes numéricas.
- **v1.4 (2026-08-12)** — Recomendação de GK aceita ("vamos seguir") e
  executada: `canonical_volatility_estimator` travado em
  `config/constants.yaml` (classe A, MEASURED), reprocessamento de
  `labels/` confirmado adiado até M2/M3. Ao responder "próximos passos",
  investigação real corrigiu §14: T0.5 estava marcado "não confirmado" —
  na verdade está feito (commit `5d8c8aa`, 2026-08-10) e dispara o
  critério de encerramento #3 (`PRD_V4_1.md` §6.5), achado real já
  registrado em `audit/evidence_ledger.yaml` desde 2026-08-10 mas nunca
  anotado no §6.5 nem no `CLAUDE.md` — corrigido nos dois agora. Este é o
  achado de maior prioridade da sessão até aqui.
- **v1.3 (2026-08-12)** — Três ações do Manager nesta rodada: (1)
  `CLAUDE.md` "Documento mestre" aprovado e aplicado — §0/§13 fecham,
  `CLAUDE.md` v1.6; (2) primeiro ciclo real do protocolo §6 escolhido —
  este próprio documento, validado antes contra PRD_V4_1/V3_2/`CLAUDE.md`
  — rodado via skill `project_assurance` (`Agent` independente, não
  retroativo), achou 4 itens reais (AG-003): TOC morto (§14 prometido e
  ausente — corrigido, é esta seção), changelog v1.2 não registrava o
  fechamento de §0/§13 (corrigido aqui), mecanismo de revisão
  independente tinha 0/2 de histórico prospectivo antes deste ciclo
  (declarado explicitamente em §2), termo "canônico" usado pra decisão E
  pra estado de produção sem distinção (desambiguado em §6.5); (3)
  recomendação sobre promoção de GK dada e registrada em
  `docs/refactor_gk_canonico.md` — travar a escolha agora, adiar
  reprocessamento até M2/M3 fecharem. Novo §14 — Road_Map Vivo, HTML
  publicado, atualizado a cada mudança de status.
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
