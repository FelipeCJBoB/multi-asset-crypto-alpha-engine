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
**Versão:** 3.49 · **Data:** 2026-08-24
**Nota de proveniência desta linha (2026-08-17):** achado ao atualizar a
governança — este cabeçalho estava em "3.5" enquanto o `## Changelog`
(abaixo) já tinha chegado a v3.14; o mesmo tipo de drift já tinha sido
corrigido uma vez antes (`git log`: "PLANO_MESTRE -- v3.0 no changelog,
faltava registrar a versao do doc"). Não é prática automática deste
documento manter os dois sincronizados a cada entrada de changelog —
registrado aqui pra não repetir o mesmo achado como se fosse novo numa
sessão futura.
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
14. [Road_Map Vivo — v1 substituído por v2, HTML consolidado 2026-08-17 (`AG-080`)](#14)
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

**Gatilho adicional (v3.1, achado AG-027): lente FE de `audit_engineering`.**
Além dos critérios acima, o protocolo completo (incluindo a lente
condicional FE — Falha de Especificação Econômica, `.claude/skills/
audit_engineering/SKILL.md` Passo 3) dispara nestes 3 eventos, mesmo que o
arquivo em si não bata na heurística de materialidade padrão (o risco aqui
não é "este arquivo específico é crítico", é "este EVENTO muda o escopo
implícito de números já em produção"):
1. Feature Engine ganha o 1º timeframe além de 15m (`src/features/build.py`/
   `_sources.py` deixam de hardcodar um TF único).
2. Qualquer constante `class: B, provenance: ASSUMED` entra no vetor de
   treino de um modelo promovido além de research (Gate 3/4) —
   `python tools/lint/check_constants_provenance.py` lista essas constantes
   com `review_by` (achado AG-028).
3. Antes de `12_RISK_ENGINE`/`13_EXECUCAO` (§15.4) ganharem o 1º caller real
   — toda constante ainda `ASSUMED` nesse ponto vira bloqueio de Gate, não
   nota de rodapé.

**Regra de segurança orçamentária (v3.2, achado AG-027 addendum ponto 1,
2026-08-15).** A lente FE é 0 trials por desenho — lê `constants.yaml`,
código-fonte e artefato já persistido, nunca abre sweep/Optuna por conta
própria. Isso importa porque `audit/n_lifetime.yaml::counter=45`, teto 60
(`PRD_V4_1.md`, critério de encerramento 5: `N_lifetime > 60 sem Camada 2
fechada → encerrar`) — restam 15 trials. Interpretar um achado da lente FE
("N janelas ASSUMED") como autorização pra varrer todas gastaria esse
orçamento inteiro numa sessão e poderia disparar o encerramento do projeto
sem nenhuma decisão do Manager. Sequência obrigatória, sempre nesta ordem:
10 perguntas (0 trials) → medição descritiva sobre dado já existente, sem
sweep (achado-modelo: `round_trip_cost_bps` corrigido por contagem direta
em `labels.parquet` já gravado) → registro em `architecture_gaps_log.yaml`
com a magnitude medida → só então, se material, escalar ao Manager citando
o `N_lifetime` restante explicitamente na própria pergunta. Detalhe completo
em `.claude/skills/audit_engineering/SKILL.md` v1.5.

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

**Classe de defeito nomeada (v3.1, 4ª ocorrência confirmada — deixa de ser
"achado avulso" e vira categoria própria do RAID): "parâmetro carrega
escopo implícito (timeframe/ativo) nunca declarado nem testado".**
Confirmada 4x, sempre pelo mesmo mecanismo — uma constante expressa numa
unidade (barras, não relógio; um TF fixo, não uma lista) só vira problema
visível quando o escopo real do projeto (multi-TF, multi-ativo) se expande
de fato:

| # | arquivo | manifestação |
|---|---|---|
| AG-004 | `src/validation/cpcv.py` | embargo de CPCV hardcoded em unidades de barra de 15m, sem parâmetro `tf` pra sobrescrever |
| AG-005 | `src/labels/triple_barrier.py`, `barrier_sweep.py` | TF hardcoded 3x, de forma duplicada e independente, apesar de `LabelConfig.decision_tf_minutes` existir e parecer configurável |
| AG-017 | `src/analysis/m2_bar_comparison.py` | `BASELINE_TF="15m"` fixo, apesar de `TIMEFRAMES` já existir num import vizinho e `PLANO_MESTRE_PRINCE2.md` §15.6 item 1 já ter previsto esse risco por nome antes do módulo existir |
| AG-027 | `src/features/groups/*.py`, `src/regime/classifier.py` | 8 janelas de feature em contagem de barra, `provenance:ASSUMED`, "convenção herdada do PRD, nunca testada" — Feature Engine roda hardcoded em 15m, decisão bar-count×clock-time nunca tomada |

Raiz mecânica confirmada (AG-028): `check_constants_provenance.py` só
processava constantes `class: A` — o campo `review_by`, presente em toda
constante `class: B` `ASSUMED` (incluindo as 4 ocorrências acima), nunca
tinha nenhum enforcement/visibilidade mecânica. Corrigido — ver lente FE
(`.claude/skills/audit_engineering/SKILL.md` Passo 3) pro protocolo de
prevenção de uma 5ª ocorrência.

**AG-030 (2026-08-15) — defeito relacionado, mas de classe distinta: não é
"parâmetro carrega escopo implícito", é "feature carrega ESCALA DE HISTÓRICO
implícita".** `C07_vol_pctile_expanding`, `D03f`, `E02f` (`src/features/
groups/group_c.py`, `group_d.py`, `group_e.py`) usam janela EXPANSIVA desde a
origem de cada ativo, não fixa — o mesmo valor bruto produz percentil/z-score
diferente por ativo dependendo só de quanto histórico aquele ativo já
acumulou (BTCUSDT: até 231.552 barras de 15m desde 2019-12-31; os 4 alts: até
164.256 desde 2021-12-01, medido a partir de `SYMBOL_START_DATE`). Não é
vazamento temporal — é não-comparabilidade entre ativos que confunde
diretamente H0 do M6 (`edge_bruto_atr` igual entre os 5 ativos, §15/T0.5):
qualquer diferença medida pode ser artefato de warmup expansivo desigual, não
edge real. **Fechado 2026-08-16** — `min_common_history_bars_15m`
implementado e testado (94 passed), decisão do Manager já tomada e artefato
afetado regenerado. Ver `audit/architecture_gaps_log.yaml::AG-030` (status
real; esta seção ficou desatualizada por um dia — ver `AG-052`).

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
| Mapa de blast radius de uma migração específica | `docs/refactor_parkinson_canonico.md` | Product Description de um Pacote de Trabalho em curso |
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

### 11.4 Road Map Vivo — agenda por stage, alinhada ao PRD

**Refatorado 2026-08-17 (achado do Manager: esta seção manteve a
estrutura Sprint-N do `PRD_V3_2_UNIFICADO.md` mesmo depois do projeto
migrar pro `PRD_V4_1.md`).** Nada foi apagado — reorganizado. Ver
**`§11.6`** pra tabela completa de reconciliação Sprint-N↔V41-N e pro
raciocínio de por que só PARTE do Sprint-N ficou obsoleta:

> `PRD_V4_1.md` (Camadas 0-3, roadmap V41-0..12) redefine só o que
> corresponde aproximadamente ao Sprint 1-11 do V3.2 (dados → features
> → volatilidade → barra → timeframe → regime → barreiras → pesos →
> calibração → Meta-Model → walk-forward → DSR, até o Gate 6). **Sprint
> 12-18 do V3.2 (Risk Engine, Execution Engine, Testnet, Paper, Live)
> NÃO são tocados pelo V4.1** — não estão obsoletos, só ainda não foram
> alcançados, e continuam válidos na linguagem Sprint-N original porque
> nenhum PRD mais novo os redefiniu.

Esta tabela agora lista só o que **não tem equivalente em nenhuma aba
dedicada** (`§11.5` dollar-bar, `§11.6` Camadas 0-3): sweeps Sprint-N
ainda genuinamente nativos do V3.2 (não redefinidos por V4.1) + achados
de arquitetura (`AG-NNN`) sem stage de PRD associado — categoria
diferente de item de roadmap, mantida aqui só por não ter aba própria
ainda.

| stage | item agendado | fonte |
|---|---|---|
| ~~Sprint 6 (Label Engine) — sweep `tp_atr_mult`/`sl_atr_mult`~~ — **SUPERSEDIDO 2026-08-17** | `V41-6` (`§11.6`) rederiva por distribuição de MFE, não por grid sweep — muda o MÉTODO, não só o valor. `time_stop_bars`/`atr_window` como constantes isoladas (fora do escopo de barreira) seguem `AG-031`/`AG-046`, seção própria | `PRD_V4_1.md` §4.1, `§11.6` |
| **S1 — verificação de robustez de `tp_atr_mult`/`sl_atr_mult` (§16.10 regra 4) — EXECUTADO 2026-08-24** | Linha NOVA, não substitui a de cima — propósito diferente (robustez do valor JÁ escolhido, nunca busca de novo ótimo, ver design doc §2). Retomado após retratação do Manager de 2026-08-22 (motivo: Alpha retreinado de verdade com LightGBM nesta sessão). Resultado: célula de produção reproduz exato (sanidade OK); **TODAS as 7 células válidas têm `edge_atr_units` médio negativo**, inclusive a produção — achado convergente com AUC~0,51 do Alpha (metodologia independente, população incondicional, sem modelo). `veredito` de "sobrevive à faixa" fica `TBD` (decisão do Manager, não computada). `N_lifetime` +18 (counter 78→96). **[CORREÇÃO 2026-08-24, Changelog v3.51, `AG-204`]** apesar do veredito formal continuar `TBD`, o Manager decidiu trocar a constante de produção pela célula `R=1,S=3/2` (tp=1,5/sl=1,5) — "menos pior medido", não "edge positivo" — 20 `labels.parquet` reprocessados, retreino do Alpha redisparado. **[SUPERADO 2026-08-25, `AG-232`/`AG-235`]** a medição acima leu a grade de RELÓGIO 15m, não a de produção (R1/R2/R3) — reexecutada sobre R1: gap edge-custo real 5,95-6,19bps em todas as células viáveis, trocar renderia +0,02bps (0,3%). Recomendação final: NÃO trocar `tp_atr_mult`/`sl_atr_mult` — geometria não é a alavanca. Detalhe completo do callout de correção: linha ~3404 deste documento | `docs/s1_design_doc_sweep_tp_sl_reward_risk_2026-08-22.md`, `audit/evidence_ledger.yaml::s1-tp-sl-sensitivity-2026-08-24`, `audit/architecture_gaps_log.yaml::AG-204,AG-232,AG-235` |
| Sprint 10 (não redefinido por V4.1) | sweep `cost_stop_ratio_max`, `fee_budget_monthly`, `max_notional_multiple` | `config/constants.yaml` |
| Sprint 11 (não redefinido por V4.1) | sweep `alpha_stability_screen_limiar` | `config/constants.yaml` |
| Sprint 16 (não redefinido por V4.1 — Paper/experimento RPI, §9.5.1) | sweep `adverse_selection_bps` | `config/constants.yaml` |
| ~~Quando reprocessamento dollar-bar concluir~~ — **fechado 2026-08-17** | remedição de M1 (Parkinson bate GK em 12/15, Manager decidiu Parkinson canônico); engenharia + reprocessamento real de `labels/`/leakage validado pros 5 símbolos sob R1; só falta retreino real do Alpha (código pronto, `--resolution-id`/`--vol-estimator-id` no CLI, não executado por decisão do Manager) | `audit/architecture_gaps_log.yaml::AG-036`, `docs/refactor_parkinson_canonico.md`, §11.5 |
| ~~Decisão do Manager, sem stage travado ainda~~ — **RESOLVIDO 2026-08-27/28** | flip de `canonical_volatility_estimator.value` pra `parkinson_w20` aplicado em produção (commit `4f3b231`) + wiring do default real (`AG-361`, mesmo dia — a constante não tinha código lendo-a por nome, `--all-combinations` sem `--vol-estimator-id` explícito revertia a decisão em silêncio). Retreino de Alpha Camada 1 sob R1+Parkinson aconteceu, mas não isolado como esta linha previa — junto da mudança muito maior de `T1_FEATURE_IDS` (7→22, `AG-362`), ver `§15.29` | `docs/refactor_parkinson_canonico.md`, `audit/n_lifetime.yaml` id 17, `audit/architecture_gaps_log.yaml::AG-361`, `§15.29` |
| ~~Decisão do Manager, sem stage travado ainda~~ — **decididos e implementados 2026-08-16** | 3 bloqueadores dollar-bar (`AG-031` horizonte do label, `AG-042` redefinição M15/M30/H1, `AG-032` embargo CPCV) — detalhe linha a linha em §11.5 | `docs/refactor_dollar_bar_canonico.md`, §11.5 |
| ~~Decisão do Manager, sem stage travado ainda~~ — **fechado 2026-08-16** | remédio pra `AG-030` (janela expansiva não-comparável cross-asset) — implementado, testado (94 passed), M6 desbloqueado | `audit/architecture_gaps_log.yaml::AG-030` |
| ~~Decisão do Manager, sem stage travado ainda~~ — **fechado 2026-08-16** | convenção de contagem de trial pra sweep classe A (1 trial em bloco vs. N por ponto) — registrada em `audit/n_lifetime.yaml`, autorizada pelo Manager. **`N_lifetime` descontinuado 2026-08-17 como orçamento vinculante — ver nota abaixo** | `audit/architecture_gaps_log.yaml::AG-039` |
| Decisão do Manager, sem stage travado ainda | `AG-050` (achado de arquitetura, não item de PRD): `src/risk/`, `src/execution/`, `src/regime/` nunca passaram por revisão independente (§6.4) — diferente de `src/labels/`, que tem histórico denso disso; `risk/sizing.py`/`limits.py`/`kill_switch.py` batem 4/4 eixos de materialidade. **Parcialmente endereçado 2026-08-17/18** — os 4 módulos NOVOS de `src/regime/` criados pra M4 (`canonicalization.py`/`bocpd.py`/`jump_model.py`/`hmm_gaussian.py`) já passaram por `audit_engineering`/`project_assurance` (Fase 5 do M4, commits `6be5960`/`7486620`/`8c1ba16`/`e1e6ff4`/`b131e02`); o código PRÉ-EXISTENTE do módulo (`build.py`/`classifier.py`/`stress.py`) continua sem essa revisão — `AG-050` não fechado, só reduzido em escopo | `audit/architecture_gaps_log.yaml::AG-050` |
| Decisão do Manager, sem stage travado ainda | `AG-055` (achado de arquitetura, não item de PRD): 5 constantes `provenance: MEASURED` sem fonte verificável (`maker_fee`, `taker_fee`, `bnb_discount`, `capital_inicial_brl`, `usd_brl_ref`) — nenhuma classe A, não bloqueia build, mas rótulo semanticamente frágil | `audit/architecture_gaps_log.yaml::AG-055` |
| Backlog condicionado a `AG-036` (extinção do T1) virar trabalho real — **adicionado ao roadmap 2026-08-17, autorizado pelo Manager** — **[REABRIR, 2026-08-28]** o gatilho original supunha extinção do T1; o gatilho real virou CHURN de composição (7→22→29→36 no mesmo dia/janela, `§15.29`), mecanismo diferente do previsto — item continua válido, mas o texto original não cobre este cenário; verificar `faixa2_caminho_b.py:1229` contra o `T1_FEATURE_IDS` real antes de fechar, não reescrever sem checar o código | `audit/architecture_gaps_log.yaml::AG-038` |
| Decisão pendente do Manager — **adicionado 2026-08-28** | `AG-362` reverte o critério de promoção marginal (`ADR-005 §2.2`) por decisão direta; `T1_FEATURE_IDS` 7→22 commitado, retreino canônico real sob 22 features tem sinal misto (0/15 `permanence_pass`). `AG-371` acha e corrige um viés estrutural real de Camada 0 (`E27f` domina 93% do gain), mas a VALIDAÇÃO da correção fica confundida por uma sessão paralela que mudou `T1_FEATURE_IDS` no meio do teste (22→29→36, Lote D/D2, `ADR-006`, não commitados). Decisão pendente: qual vetor é autoritativo, e se remedir a correção de `E27f` sob 22 features limpo | `audit/architecture_gaps_log.yaml::AG-362,AG-371,AG-371-ADDENDUM-10`, `§15.29` |
| Decisão pendente do Manager — **adicionado 2026-08-28** | `AG-342`: os 4 cutoffs do classificador de regime REALMENTE ativo (`regime_er_cutoff`/`regime_vol_cutoff`, entrada/saída) são classe A `provenance: ASSUMED`, `sweep_required: true`, `review_by: sprint_5` — nunca varridos apesar do projeto estar muito além do sprint 5; por regra do próprio `CLAUDE.md` isso deveria bloquear build de produção, e não bloqueia | `audit/architecture_gaps_log.yaml::AG-342`, `§15.29` |
| ~~Decisão pendente do Manager~~ — **CORRIGIDO 2026-08-28, mesma sessão (ainda não commitado)** | `AG-373`: `A17_true_range_per_overshoot` (Lote D/D2) tinha defeito dimensional real (`TR/overshoot` não era adimensional) — redesenhada pra `A17_log_tr_per_overshoot_ratio`, razão de 2 quantidades adimensionais em `ln1p`, verificada por teste de invariância a nível de preço | `audit/architecture_gaps_log.yaml::AG-373`, `§15.29`, `docs/ADR-006_momentum_reversao_impacto_dollar_bar_2026-08-28.md` (addendum) |

**`N_lifetime` DESCONTINUADO como orçamento vinculante (2026-08-17,
decisão do Manager: "pode descontinuar, não nos será útil pra esse
projeto, foi mal implementado desde o começo").** `audit/n_lifetime.yaml`
mantido como registro histórico (append-only, nunca apagado), mas deixa
de ser um GATE — nenhuma linha desta tabela nem de `§11.6` é mais
bloqueada por `counter > 60`. **Consequência real, não resolvida
sozinha aqui**: o próprio `PRD_V4_1.md` §6.1/§6.5 usa `N_lifetime` como
insumo direto da fórmula de DSR (Deflated Sharpe Ratio) e do critério de
encerramento #5 ("`N_lifetime` > 60 sem Camada 2 fechada → encerrar") —
descontinuar o contador sem redefinir o que substitui essas duas coisas
deixa **Gate 6 e o critério de encerramento #5 sem definição operacional
clara**. Não inventei uma substituição aqui (decisão estatística/de
governança que não é minha pra tomar sozinho) — registrado como
`AG-077`. **Decisão do Manager, 2026-08-28, `AG-077` FECHADO**: nada
substitui a penalidade de multiple-testing por outra fórmula — o
próprio Gate 6 deixa de ser "DSR final com `N_lifetime`=60" e passa a
ser resultado empírico ("pronto" = lucro entregue em Live Demo). O
critério de encerramento #5 (`PRD_V4_1.md` §6.5, guardrail contra busca
infinita, pergunta diferente de "quando declarar sucesso") não foi
tocado por esta decisão. Detalhe completo, incluindo o novo gap que essa
decisão abriu (definição operacional de "lucro"/"Live Demo" ainda
pendente): `§11.6` abaixo, `audit/architecture_gaps_log.yaml::AG-077`/
`AG-374`.

**Regra de leitura:** sweeps desta tabela (Sprint 10/11/16) não custam
`N_lifetime` — a mecânica de "conta quando roda" segue documentada por
completude histórica, mesmo com o contador descontinuado como gate.
Atualizar esta tabela quando um `review_by` mudar em
`config/constants.yaml`, ou quando um bloqueador ganhar stage decidido.

### 11.5 M1+M2 — Refactor dollar-bar canônico, ponta a ponta <a name="11-5"></a>

Aba dedicada (Manager, 2026-08-16) — rastreio único do redesenho completo
que M2 (`canonical_bar_type=dollar`) e M1 (remedição de volatilidade,
`AG-036`) disparam, camada por camada (`exchange → data → features →
labels → regime → models → validation → backtest → risk → execution →
live`, hierarquia do `CLAUDE.md`), **para não perder o fio entre sessões**.
Atualizada a cada commit que muda status de uma linha — não é retrospecto
escrito no fim, é o estado real.

| camada | o que muda | status | referência |
|---|---|---|---|
| `data` (`src/data/bars.py`) | dollar bar já vetorizada (`cumsum`/`floor`), paridade lote↔streaming por construção | ✅ pronto (já existia antes de M2 decidir) | `bars.py:222` |
| `validation` (`src/validation/cpcv.py`) | purge cobre componente 32 (`t1` real de teste) + componente 96 (lookback de feature de treino) | ✅ implementado, testado (42/42), revisado (`project_assurance`), wireado nos 2 call-sites reais (`pipeline.py:432`, `leakage.py:798`). Decisão sobre as 3 features expanding: EXCLUÍDAS de `T1_FEATURE_IDS` (commit `78169df`, `AG-032`, 2026-08-23) — ressalva de magnitude do proxy p99 (`AG-159`/D-02) FECHADA com constante dedicada MEASURED (`§15.27`) | `AG-032`, `AG-159`, commit `78169df` |
| `validation` (`src/validation/cpcv.py`) | embargo (E1) em relógio fixo, `cpcv_embargo_bars` aposentado | ✅ implementado, testado (42/42), commitado | `AG-032`, commit `3b19c20` |
| `labels` (`src/labels/triple_barrier.py` + `barrier_sweep.py`/`cost_surface.py`/`backfill_multi_symbol.py`/`experiment_log.py`) | horizonte do label em relógio fixo (B1 = Opção 2), `time_stop_bars`→`time_stop_ms`, `atr_window`→`atr_window_ms` (Label Engine só), `n_bars_held` vira contagem real | ✅ pronto — confirmado empiricamente (`uv run pytest`, 121 passed), commitado e pushed | `AG-031`, `AG-044`..`048`, commit `c0ac546` |
| `analysis`/`config` (`m2_worker.py`, `constants.yaml`) | ontologia `resolution_id` (R1/R2/R3) substitui M15/M30/H1 como identidade de dollar/volume/tick_imbalance bars (B2 = A′+D, parte 1 — `threshold_usdt` como identidade formal fica pra quando dollar bar for implantado) | ✅ pronto — confirmado empiricamente (`uv run pytest`, 105 passed), commitado e pushed | `AG-042`, commit `982b5d4` |
| `validation` (`assert_grade_consistent`, `src/validation/cpcv.py`) | `CPCVConfig` ganha `grade_id` (deriva de `tf`, retrocompatível); guard renomeado de `assert_tf_consistent`, `NotImplementedError` explícito fora do dict de `step_ms` (mecânica de checagem em si continua `rtol` pra grade de tempo — igualdade discreta exigiria coluna nova em `labels.parquet`, fora de escopo sem caller real) | ✅ pronto — confirmado empiricamente (`uv run pytest`, 105 passed), commitado e pushed, ~15 callers reais auditados sem mudança | `AG-037`, commit `982b5d4` |
| `features` (`constants.yaml`) | `scaling_invariant` ganha `activity`; A13 vira F1 explícito; B01 reclassificado `bar_count` | ✅ pronto (classificação F3) | `AG-043` |
| `features` (`support.py`/`group_e.py`/`_sources.py`) | correção de código de `sqrt(window)`/Yang-Zhang/asof-join | ⬜ deferido deliberadamente — precisa Bloqueador 1+2 fechados (✅ já estão) + distribuição real de duração de dollar bar medida | `AG-043` |
| `data` (`src/data/bars.py`) | redesenho de `threshold_bars_step` — amplificação de memória por chunk eliminada (busca binária, numpy), circuit breaker (`max_leftover_trades`/`LeftoverOverflowError`) contra threshold não-estacionário | ✅ pronto — confirmado empiricamente (`uv run pytest`, 49 passed), 3 camadas de revisão, commitado | `AG-034` addendum |
| `data` (`src/data/build_dollar_bars.py`) | calibração causal do threshold dollar-bar (`build_dollar_bars_walkforward`) decidida e reprocessada em produção real — `trailing_window_days=7`/`cadence_days=7`, 5 símbolos × 3 resoluções, 15/15 células sem erro | ✅ pronto — decisão + reprocessamento real (`AG-124`, `§15.15`); CLI (`--mode single_window\|walkforward`) fechado (`AG-138`, commit `ef7f5d3`) | `AG-034` addendum, `AG-124`, `AG-138` |
| `monitoring` (`src/monitoring/dollar_bar_drift.py`) | alarme de deriva de threshold (item 2) | ✅ pronto — `evaluate_drift`/`measure_new_window_drift`, 12 testes, medido com número real (BTCUSDT `drift_ratio=18,18x`) — **linha corrigida 2026-08-17, estava desatualizada** (dizia "não iniciado"; achado ao sincronizar a governança). Zero caller de produção/live ainda — só invocação manual (mesma disciplina de escopo de `build_dollar_bars.py`), decisão explícita de não comissionar `project_assurance` (abaixo do limiar de materialidade, mesma lógica de `AG-050`) | `AG-042::addendum_item2_alarme_de_deriva_2026_08_16` |
| `monitoring` (regra de incremento de `calibration_version`, item 3) | regra formal de QUANDO/COMO recalibrar em produção | ⬜ não iniciado — Manager aceitou `calibration_scope="validation"` como base da produção por enquanto (mitigado pelo alarme de deriva do item 2), item 3 em si continua aberto, decisão de negócio | `AG-042::addendum_decisao_calibration_scope_2026_08_17` |
| `features` (M1, `src/features/volatility.py`) | remedição dos 8/6 candidatos sob grade dollar (5 símbolos × R1/R2/R3) | ✅ pronto — Parkinson bate GK em 12/15 combinações (`AG-065`/`AG-074`), Manager decidiu Parkinson canônico 2026-08-17. **DEPLOYADO 2026-08-27** (commit `4f3b231`): `constants.yaml::canonical_volatility_estimator.value` = `parkinson_w20`, Parkinson em produção. Gap de wiring achado e fechado no mesmo dia (`AG-361` — a constante não tinha código lendo-a por nome) | `AG-036` addendums `medicao_completa`/`decisao_manager_2026_08_17`, `AG-361`, `§15.29` |
| `labels`/`features`/`regime`/orquestração (Parkinson+dollar-bar, Fases 0-4) | `LabelConfig.resolution_id`, `vol_estimator_id` selecionável em `build_t1_features`/`build_regimes`, `build_modeling_frame`/`run_layer1_sprint`/`leakage.py`/`fill_reconciliation.py` parametrizados por grade única (`resolution_id="R1"` deriva `bar_source`/`grade_id`, nunca dois parâmetros independentes) | ✅ pronto — 1305/1305 sem regressão, commits `5df33c3` (labels), `3449471` (features), `9a4c3c5` (regime), `b5760fe` (orquestração) | `docs/refactor_parkinson_canonico.md`, `AG-036` addendum `engenharia_pronta_producao_adiada_2026_08_17` |
| `data` (reprocessamento real de `labels/`, 5 símbolos, R1+Parkinson) | `data/labels/{symbol}/R1/v1/labels.parquet` — BTCUSDT 463.034/ETHUSDT 328.452/SOLUSDT 327.461/BNBUSDT 328.440/XRPUSDT 327.488 linhas; labels 15m de produção confirmados intocados | ✅ pronto — executado 2026-08-17, `run_and_write_labels_dollar_bar_parkinson()` | `src/labels/backfill_multi_symbol.py`, `docs/refactor_parkinson_canonico.md` |
| `validation` (14 testes de vazamento contra R1, 5 símbolos) | 12 PASS/0 FAIL/2 sentinela em TODOS os 5 — zero vazamento | ✅ pronto — executado 2026-08-17, CLI nova (`--resolution-id`) | `data/validation_reports/leakage_report_{symbol}_R1.json` |
| `features`+`regime` (join real via `build_modeling_frame` sob R1+Parkinson, 5 símbolos) | zero regime nulo, 6 rótulos presentes, features T1 dependentes de Parkinson finitas/não-degeneradas | ✅ pronto — executado 2026-08-17 (sem artefato em lote, recomputado on-the-fly por desenho) | `src/models/dataset.py::build_modeling_frame` |
| `models` (retreino real de Alpha Camada 1, 5 símbolos) + `config` (flip de `canonical_volatility_estimator.value`) | Alpha Camada 1 retreinado sob R1+Parkinson, `value` flipado | ⬜ **código pronto, execução deliberadamente NÃO feita 2026-08-17** — Manager: "expanda a review e solucione, mas não execute. Deixe pronto"; `run_layer1_sprint` ganhou `--tf`/`--resolution-id`/`--vol-estimator-id` no CLI, comando pronto em `docs/refactor_parkinson_canonico.md` | `audit/n_lifetime.yaml` id 17 (`budget_override_manager`), `docs/refactor_parkinson_canonico.md` |

**Regra desta aba:** nenhuma linha muda de status sem um commit real
apontável (âncora na coluna "referência") — "planejado" não é um status
válido aqui, só "não iniciado", "em andamento" ou "pronto".

---

### 11.6 `PRD_V4_1.md` Camadas 0-3 — M1-M6 + Roadmap V41-N <a name="11-6"></a>

Aba dedicada (2026-08-17, achado do Manager, `AG-075`/`AG-076`) — até
esta linha, o Road Map Vivo não tinha NENHUMA linha rastreável pra M4
(Regime), V41-6 (Barreiras), V41-7 (Pesos+Features), V41-8..12
(Controle 19, Calibração, Meta-Model, Walk-forward, DSR final). Existiam
só enterrados em texto de changelog. Mesmo padrão de furo que
`AG-051`/`AG-052` já tinham achado uma vez (§11.4 tratado como fonte
completa sem checar contra o PRD real) — desta vez numa camada inteira
de medições com orçamento de trial real, não achados de arquitetura
soltos.

**⚠️ Aviso de nomenclatura, leia antes de citar "M1"-"M6" ou "Parte
VIII" em qualquer lugar deste projeto:**

- **`PRD_V3_2_UNIFICADO.md` (§18.6) já usa os rótulos `M1`-`M6` pra
  outra coisa** — mecanismos de PREVENÇÃO de erro de proveniência de
  constante (M1=CI bloqueia `ASSUMED` classe A; M2=varredura ±50% antes
  do Gate 3; M3=guardrails como quantis, não número redondo;
  M4=distribuição esperada vem de simulação, nunca fabricada;
  M5=`N_lifetime` vitalício; M6=pré-registro de valores classe A).
  **Nada a ver** com `M1`-`M6` de `PRD_V4_1.md` §3.2 (medições
  empíricas: Volatilidade/Barra/Timeframe/Regime/Fill/Fator comum).
  Citar "M2" sem dizer qual PRD é ambíguo — **sempre desambiguar**:
  `M2(V4.1)` = Barra, `M2(V3.2)` = varredura ±50%.
- **`PRD_V3_2_UNIFICADO.md` também tem uma "Parte VIII"** — Risk Engine
  e Position Sizing (linha 1528) — diferente da "Parte VIII — ROADMAP"
  de `PRD_V4_1.md` (linha 707). Mesmo número romano, assuntos
  diferentes, documentos diferentes.
- **Dentro do próprio `PRD_V3_2_UNIFICADO.md` já existem DUAS listas
  "Camada 1-5" colidentes** (§5.3-5.11: camadas do modelo Alpha —
  monotônico/triagem/bagging/DoubleEnsemble/DRO; §17.3.2: camadas do
  estudo de não-estacionariedade — estacionariedade/cost-ATR/
  similaridade/regime/walk-forward) — dívida de nomenclatura
  pré-existente do V3.2, não introduzida por esta aba, registrada aqui
  só pra quem for procurar "Camada 3" saber que precisa desambiguar
  também.

**Relação Sprint-N (`PRD_V3_2_UNIFICADO.md`) ↔ V41-N (`PRD_V4_1.md`) —
NÃO existe mapeamento formal declarado em nenhum documento** (V3.2 é
anterior, não podia citar V4.1; V4.1 nunca declara "isto substitui o
Sprint N"; `docs/SPRINT_LOG.md` usa numeração de Sprint de V3.2 o tempo
todo). A tabela abaixo é uma **reconstrução com base em evidência
indireta** (ex.: `G-WF-1..6` é literalmente o mesmo esquema de gate nos
dois documentos, `PRD_V3_2_UNIFICADO.md` §11.4.1 linha 2154 e
`PRD_V4_1.md` linha 515 — não coincidência, V4.1 herda por citação),
**não uma citação de fato já escrito em algum lugar**. Tratar como
proposta a confirmar, não como verdade estabelecida:

| V3.2 Sprint/Gate | V4.1 Camada/V41-N | relação (evidência) |
|---|---|---|
| Sprint 1-4 (infra, dados, features) | Camada 0 (T0.1-T0.4, V41-0) | V41-0 refatora as MESMAS interfaces que Sprint 1-4 já entregou (`VolatilityEstimator`/`RegimeClassifier` são retrofit sobre `group_c.c01_atr_20`/`QuantileRegimeClassifier` do Sprint 4-5) |
| Sprint 6 (Label Engine), Sprint 8 (Alpha) | T0.5 (V41-1, baseline janela comum) | T0.5 roda `alpha_c1_v1` (o modelo do Sprint 8) sem alteração, só reprocessado — é o MESMO artefato, janela nova |
| Sprint 3 ("refazer ATR sobre série completa", §18.7 item 1) | M1 (V41-2) | mesma ação (remedir volatilidade), V4.1 generaliza pros 5 ativos/3 TFs |
| — (sem equivalente direto em V3.2, dollar bar não existia na V1) | M2 (V41-3) | conceito novo do V4.1, sem precedente em V3.2 |
| — (`decision_tf` era fixo desde §0.1 da V1, nunca varrido) | M3 (V41-3) | conceito novo (multi-TF), sem precedente em V3.2 |
| Sprint 5 (Regime Engine) | M4 (V41-4) | Sprint 5 entregou o BASELINE (quantis expansivos); M4 testa se esse baseline é o vencedor contra HMM gaussiano, Jump Model contínuo (CJM), BOCPD e a Terceira via Q3 (BTC como fator comum) — harness completo, execução real em andamento (§11.6) |
| Sprint 9-10 (fill simulator, backtest) | M5 (V41-2/parcial) | `fill_reconciliation.py` do Sprint 9-10, mesmo módulo, escopo estendido pros 5 ativos |
| — (sem equivalente — teste de proposição novo do V4.1) | M6 (V41-3) | conceito novo, sem precedente direto |
| Sprint 6 item "varredura 2D tp×sl" (§18.7 item 2) | V41-6 (Barreiras) | mesma ação, adiada desde V3.2 pra depois de M1/M4 fecharem |
| Sprint 6 ("similaridade", §17.3.2 camada 3) + Sprint 4 (features) | V41-7 (Pesos+Features) | mesma dívida do V3.2 ("especificado e nunca rodado", §11.3.1), agora com trial declarado |
| Sprint 12 (Risk Engine, 18 controles) | V41-8 (Controle 19 + sizing) | controle NOVO (19º), não existia no V3.2 — I4/§5.3 do V4.1 é achado genuinamente novo da emenda multi-ativo |
| §5.12 do V3.2 (`confidence_rank`, nunca avaliado) | V41-9 (Calibração) | mesma dívida herdada, sem sprint numerado explícito em V3.2 |
| §6.8 do V3.2 (critério de entrada do Meta) | V41-10 (Meta-Model) | V3.2 fechou Meta com "argumento que caiu" (§0.3 do V4.1); V41-10 reabre |
| Sprint 11 (`walk_forward.py`, DSR/PBO/Lo, Gate 4/6) | V41-11 (Walk-forward+PBO+Lo) | MESMO módulo (`G-WF-1..6` idêntico nos dois documentos, ver aviso acima) |
| Sprint 11 (Gate 6, DSR final) | V41-12 (DSR final) | mesmo Gate 6, `N_lifetime` recalculado pro escopo multi-ativo (60, não mais o valor original de V3.2) |

**Status real de cada Camada/medição do PRD_V4_1.md (fonte: `PRD_V4_1.md` §3, Parte VIII, lido integralmente em 2026-08-17):**

| item | trials | status | referência |
|---|---|---|---|
| Camada 0 — T0.1-T0.6 (V41-0), T0.5 baseline janela comum (V41-1) | 0 | ✅ fechada — `G-C0-1..7` todos citados como cumpridos no texto do PRD | `PRD_V4_1.md` §3.1 |
| **M1(V4.1) — Volatilidade** | 0 | ✅ medido (2026-08-11/12) — GK venceu originalmente, **remedido sob dollar-bar nesta sessão** (2026-08-17): Parkinson vence 12/15, Manager decidiu Parkinson canônico. **DEPLOYADO 2026-08-27** (commit `4f3b231`) — `constants.yaml::canonical_volatility_estimator.value` = `parkinson_w20`, roda em produção; gap de wiring achado e fechado no mesmo dia (`AG-361`) | `PRD_V4_1.md` §3.2 M1, `AG-036`/`AG-065`, `AG-361`, `§15.29` |
| **M2(V4.1) — Barra** | 0 | ✅ medido e decidido — dollar bar canônico (`canonical_bar_type=dollar`) | `PRD_V4_1.md` §3.2 M2, `AG-034` |
| **M3(V4.1) — Timeframe** | 0 | ✅ medido (2026-08-14) — BTC não-monótono em TF, achado real; decisão de qual TF adotar fica pra V41-5 (ainda não escrito) | `PRD_V4_1.md` §3.2 M3 |
| **M4(V4.1) — Regime** | `≤18` ratificado de fato pela execução real (6 candidatos × 3 resoluções) — **contagem formal em `N_lifetime` segue pendente de `AG-077`** (mesma decisão de sempre, não resolvida por esta atualização) | 🟡 **4ª execução real CONCLUÍDA (2026-08-19) com AG-090/091/092/093 corrigidas e auditadas — resultado nulo generalizado, tratado como achado válido, não como estudo com bug.** Todos os 18 p-valores de permutação (6 candidatos × 3 resoluções, por lado) ficaram entre 0,30 e 0,85 — nenhuma célula significativa, incluindo BOCPD (líder sob a métrica clássica de I², depois identificada como artefato de autocorrelação intra-regime via correção de permutação em bloco, não heterogeneidade real). Jump Model com poder estatístico inexistente (mediana de 4 episódios/célula, mínimo 1, em 100% das 102 células) — resultados dele não interpretáveis, 3 problemas independentes combinados (decode não-causal confinado ao fold, poder nulo, λ calibrado numa fatia só de BTC nunca retestada). 2 auditorias externas brutas processadas + validação cruzada própria (código real + literatura: Adams & MacKay 2007, Nystrup/Cortese/Shu, Winkler et al., Bailey/López de Prado) — resultado categorizado em redesenho/fix mecânico/habilitação/rejeitado, documento próprio: `docs/m4_regime_auditoria_externa_2026-08-19_validacao_cruzada.md`. **M4 PAUSADO** (decisão do Manager, 2026-08-19) — a sequência de retomada (transferibilidade de λ do Jump Model → recalibração de `hazard_lambda` restrita a pré-teste → enriquecimento do painel diagnóstico → congelamento + locked holdout → veredito final) não recomeça até a Trilha B (linha abaixo) travar o contrato downstream, porque escolher candidato de regime sem saber o contrato de consumo mede a pergunta errada. **Atualização 2026-08-20 — Trilha B travou (ADR-001 ratificado, §15.12) e mudou o critério de retomada, não só destravou a data**: ADR-001 §2.7 decide regime como GATE (papel 2), não FEATURE (papel 1), na v1 — "gate não precisa prever, precisa evitar". O resultado nulo do M4 mediu heterogeneidade de RETORNO (utilidade de feature), pergunta que deixou de importar pra decisão de promoção. A pergunta que importa agora (heterogeneidade de VOLATILIDADE futura, occupancy do estado de stress, transition failure rate, detection delay — qualidade como gate) nunca foi medida, apesar de já estar catalogada como extensão barata em `docs/m4_regime_auditoria_externa_2026-08-19_validacao_cruzada.md` ("fix mecânico") — registrado como `AG-114`. Retomada de M4 aguarda autorização do Manager pra rodar esses 4 diagnósticos antes do veredito final, não mais só "esperar a Trilha B" **Atualização 2026-08-21 — diagnósticos RODADOS, fila fechada**: `AG-118` (Gate Efficiency) implementado e **RESOLVIDO** — `lift` não desvia de 1,0 em 90 células, sem sinal econômico detectável, robusto ao candidato (k2/k3/k4). `AG-114` (candidato vencedor) foi **REABERTO** no mesmo dia por auditoria externa — Gate 1 aplicado com 2 critérios misturados (mediana vs. máximo-por-janela); sob o critério literal, `hmm_gaussian_k2_v1` venceria em 2 das 3 resoluções. Manager autorizou `hmm_gaussian_k4_v1` como candidato de regime **canônico de produção** (override de negócio explícito, não resolução do Gate 1 na época) — regime saiu do vetor de treino do Alpha, novo builder `src/regime/build_hmm.py`, Risk Engine wired de forma candidato-agnóstica. **Atualização 2026-08-21 — Gate 1 RE-OPERACIONALIZADO (§15.12.6)**: Manager travou o critério em pior-caso (não mediana), `hmm_gaussian_k2_v1` passa a falhar o Gate 1 nas 3 resoluções sob esse critério — veredito `hmm_gaussian_k4_v1` inicialmente lido como "confirmado e robusto" nesta atualização, **mas `§15.12.7` (1 dia depois, mesma trilha) refuta essa leitura como ALEGAÇÃO ESTATÍSTICA**: `AG-114` segue tecnicamente aberto quanto à metodologia (empate detectado pelo piso do p-valor em R1/R2). O que de fato sustenta `hmm_gaussian_k4_v1` como candidato canônico de produção hoje é **override de negócio explícito do Manager** (`§15.13`), não uma resolução estatística limpa do Gate 1 — não confundir as duas coisas. Detalhe completo: `§15.12.6`, `§15.12.7`, `§15.13` | `PRD_V4_1.md` §3.2 M4 (secundário), `AG-075`, `AG-077`, `AG-083` a `AG-093`, `AG-114`, `AG-118`, `AG-122`, `docs/m4_regime_plano_execucao.md`, `docs/m4_regime_auditoria_externa_2026-08-19_validacao_cruzada.md`, `docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md` §2.7, `§15.13` |
| **Trilha B(2026-08-19/20) — Contrato Regime→Alpha→Decision Engine→Meta→Risk→Execução** — item novo, sem stage V41-N formal (achado de arquitetura transversal, não medição M-style) | não aplicável (auditoria de arquitetura, não trial de modelo) | 🟠 **Auditoria externa (`ADR-001`, 2026-08-20) devolveu veredito: 2 dos 4 mecanismos aprovados internamente REFUTADOS como especificados, 1 parcialmente errado, 1 ganhou os contratos que faltavam.** (B) gate por linha — refutado: `(símbolo,resolução)` não é entidade de posição na Binance (`AG-108`, N-01). (C) convenção de trials — sobre-conta por correlação e mantém resíduo de circularidade (`AG-111`). (D) gatilho de proteção — mecanismo revisado repete, deslocado, o mesmo defeito de paridade treino-live da versão já refutada (`AG-110`). O achado original citado aqui como "mais severo do ADR inteiro" (`AG-109`, saída executável sob GTX) foi **REFUTADO no mesmo dia** (`AG-115`, 2026-08-20, `§15.12.2`) — `src/exchange/adapter.py::place_order` segue `NotImplementedError` hoje, então a assimetria de execução que `AG-109` descrevia nunca chegou a ser um problema de produção real; ver `§15.12.2` pro argumento completo. (A) Decision Engine — sem controvérsia no mecanismo, mas faltavam os 4 contratos que tocam dinheiro (Meta→Decision→Risk→Execução→Ledger), agora propostos. Achados novos não cobertos pelas 4 rodadas internas: granularidade de lote vs. capital (`AG-112`, viés sistemático de seleção ~24× entre símbolos) e pré-filtro de custo grátis que pode eliminar metade do espaço de busca antes de qualquer backtest (`AG-113`). Decisão de arquitetura de dados também recebida: lake local endereçado por conteúdo (4 invariantes INV-A..D), status `Proposed` — pendente de ratificação formal como `D-###` (nota do próprio ADR). Recomendações fundamentadas recebidas pras 9 decisões antes pendentes (ver `§15.12`). 10 gaps originais (`AG-094`-`AG-100`), 4 rodadas de contestação adversarial interna (`AG-101`-`AG-105`), mandato corrigido (seleção offline, fixa por rodada, eliminação periódica) e tiering de features descontinuado (T1 fixo → todas canônicas, `~92` usáveis, ainda não implementado em código) seguem válidos como histórico — não invalidados pela auditoria externa, só o desenho de consumo em cima deles **Atualização 2026-08-21**: o wiring de consumo real do contrato Regime→Risk foi implementado — `src/risk/limits.py::control_01_regime_tradeavel` deixou de decodificar vocabulário `R1..R4`, passa a receber `regime_tradeable: bool` já resolvido pelo builder de regime (candidato-agnóstico, mesmo campo pra baseline ou HMM). **Atualização 2026-08-22**: `control_01_regime_tradeavel` foi DESLIGADO de `evaluate_all()` (commit `3c0d83d`) — `AG-118` mediu ausência de sinal econômico (`lift`≈1,0 em 90 células), o gate continua definido/testado/exportado mas não é chamado em produção. Detalhe: `§15.13` | `audit/architecture_gaps_log.yaml::AG-094` a `AG-113`, `§15.11`/`§15.12`/`§15.13` deste documento, `docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md`, `docs/brief_auditoria_externa_2026-08-19_*.md` |
| **M5(V4.1) — Reconciliação de fill** | 0 | 🔵 **PRÓXIMA FRENTE (autorizado 2026-08-17)**, ainda 🟡 parcial — fill real medido em BTCUSDT (42,2% vs. 97,1% otimista); escopo completo (5 ativos) precisa de `predictions.parquet`/`orders.parquet` pros 4 alts (via Feature Engine + Label Engine + Alpha + `fill_simulator`, que hoje só rodaram pra BTC) — engenharia real de pipeline, 0 trials, não busca | `PRD_V4_1.md` §3.2 M5, `AG-077` |
| **M6(V4.1) — Fator comum** | 0 | ⚠️ **RE-MEDIDO 2026-08-25 (`AG-238`) — o `I²=96-98%` era da grade ERRADA.** Fechamento original (2026-08-14) mediu a grade de relógio 15m, substituída como canônica desde `AG-042` (2026-08-16). Na grade de produção: **I²=61-83%**, caindo monotonicamente com a duração da barra. H0 **segue rejeitada** em R1/R2/R3 (p<0,05), então a conclusão qualitativa sobrevive — mas a força não: em R1 SHORT o p vai de 7e-30 para **3,8e-02**. **Não cite `96-98%` como suporte de escopo multi-ativo.** E a leitura POR LADO **inverte** (ver `§11.6` addendum abaixo) | `PRD_V4_1.md` §3.2 M6 · `AG-238` |
| V41-5 — PRD V4.2 escrito com os resultados | 0 | ⬜ não iniciado — depende de M4 fechar primeiro | `PRD_V4_1.md` Parte VIII |
| V41-6 — Barreiras rederivadas | ≤4 | ⬜ não iniciado — depende de V41-5 | `PRD_V4_1.md` §4.1 |
| V41-7 — Pesos + Features | ≤3 | ⬜ não iniciado — depende de V41-6 | `PRD_V4_1.md` §4.2 |
| V41-8 — Controle 19 (risco agregado) + sizing por ativo | 0 | 🟡 **parcial** — Controle 19 (`control_19_risco_agregado`, `src/risk/limits.py`) IMPLEMENTADO 2026-08-17, desacoplado da sequência (`AG-081`, autorizado pelo Manager): risco já quantificado (§5.3, ρ≈0,91 = 4,82x, cap efetivo 2 posições), não precisava esperar V41-5/6/7. `NOT_COMPUTABLE` em produção até existir rastreador de posições live + série de correlação (Sprint 12+). `aggregate_risk_max` (classe A, `ASSUMED`) e "sizing por ativo" (§5.4) seguem não iniciados. **[CORRIGIDO 2026-08-22, `AG-144`]**: `ρ≈0,91` nunca teve janela/proveniência declarada — remedido sobre dado real (5 símbolos, log-retornos 15m, 4 janelas): média entre pares fica em 0,70 (histórica completa) a 0,83 (180d), nunca 0,91; instável (range até 0,23/par). Multiplicador de 5 posições recalculado: 4,36x-4,65x, não 4,82x — mas **o cap efetivo de 2 posições é ROBUSTO à correção** (precisaria ρ≤0,167 pra N=3 caber no limite de 1,00%, nenhuma janela medida chega perto). Achado colateral: a mesma correlação mais baixa/instável enfraquece a leitura de que os 5 ativos "seriam ~1 aposta só" (§2.8) — converge com `M6` (Fator Comum, H0 rejeitada, I²=96-98%, componente idiossincrático real). Detalhe completo: `audit/evidence_ledger.yaml::ag144-correlacao-cross-asset-15m-4-janelas`, `audit/architecture_gaps_log.yaml::AG-144` | `PRD_V4_1.md` §5.3, `AG-081`, `AG-144` |
| V41-9 — Calibração + `confidence_rank` | 0 | ⬜ não iniciado — `confidence_rank` existe (§5.12 do V3.2) mas nunca foi avaliado | `PRD_V4_1.md` §4.4 |
| V41-10 — Meta-Model + Grupo J | ≤2 ⚠️ | 🔴 **F0-F5 implementados, Gate E0 REAL reprova os 5 candidatos** (2026-08-30/31, `§15.30`/`§15.31`); desenho travado v3 em 2026-08-22 (`§15.19`) — ADR-001 §3.7/§2.7 revogado pelo Manager; regime entra como feature, fonte **HMM k=4** por decisão do Manager (2026-08-30, mas artefato ainda não persistido — Gate E0 rodou sob `quantile_classifier_v1`); **Grupo J desacoplado e movido para DEPOIS**. `P1`/`AG-151` **fechado** 2026-08-31 (`§15.34`). `P0` **medido** 2026-08-31 (`§15.36`) — 9/10 calibrado. **`P3`/Gate E0 REAL rodou 2026-08-31 (`§15.38`) contra os 5 combos de produção — 0 de 5 passam** (`AG-404`). **F6 (ablação real) rodou 2026-09-01 (`§15.39`) — 0 de 5 SÍMBOLOS passam o critério primário** (`AG-409`) — Jaccard(A1,A3)=1,000 exato na maioria dos combos (Meta ≈ reparametrização de `tau`). **F6b (ablação sobre walk-forward ancorado) rodou 2026-09-01 (`§15.40`) — 0 de 5, MAIS decisivo: os 5 caem em `INSUFFICIENT_SAMPLE`, o Meta nunca ajusta modelo sob causalidade real, nem `BTCUSDT/R2`** (`AG-413`). QUATRO medições independentes convergentes (Alpha `AG-391`, Gate E0 `AG-404`, F6 `AG-409`, F6b `AG-413`). **F7 (enforcement B07/B08, D-13/§10, as 5 camadas) fechado 2026-09-01 (`§15.41`)**: runtime + teste #10 real + teste #11 estendido (`_META_PATH`) + B07 `automated=True` + import-linter `alpha↛meta`. **F8 (`§15.42`) fecha o roadmap por CONFIRMAÇÃO — nenhuma das 6 constantes "não criadas" do `§11` precisava ser criada** (mecanismo/já-sem-limiar-declarado/gate-bloqueado/fabricação), `N_lifetime++` (ids 43/44). **Roadmap F0-F8 completo.** Consequência pré-declarada do design doc ("Meta sai do roadmap") NÃO aplicada — decisão explícita do Manager: "não é impeditivo agora, finalize a construção mesmo assim". ⚠️ **o orçamento `≤2` é inconsistente** com a contabilidade do §11 do próprio design doc por 1-2 ordens de grandeza — não reconciliado; `N_lifetime` deixou de ser gate vinculante em `AG-077` | `docs/meta_model_design_doc_2026-08-22.md`, `§15.19`, `§15.30`, `§15.34`, `§15.36`-`§15.42` |
| — (novo, sem V41-N formal — item de arquitetura, não medição M-style) | Alpha multi-ativo × multi-resolução (LightGBM + GPU) | 🟢 **IMPLEMENTADO E TREINADO DE VERDADE (2026-08-23, `§15.20.2`)** — D-01 a D-18 codificados (`§15.20.1`), D-06 integrado (escopo estreito, fecha `AG-154`), 4 bugs reais achados e fechados rodando pela primeira vez contra dado de produção (`AG-199`/`AG-200`/`AG-202` fechados; `AG-201` aberto — GPU/CUDA inviável no Windows nativo, treino real rodou em CPU). Primeiro sweep completo (5 símbolos × R1/R2/R3 = 15 combinações): **3/15 (20%) passam o gate de permanência** (ETHUSDT/R1, SOLUSDT/R2, SOLUSDT/R3) — achado misto real, registrado em `audit/evidence_ledger.yaml::alpha-lightgbm-sweep-15-combinacoes-2026-08-23`, não decisão de promoção pra produção ainda. **Atualização 2026-08-27/28 (`AG-207`→`AG-362`→`AG-371`, ver `§15.29`)**: o sweep de 3/15 acima ficou obsoleto em 3 camadas — override T2→T1 (`AG-207`), reversão do gate marginal de `ADR-005 §2.2` (`AG-362`, `T1_FEATURE_IDS` 7→22), retreino canônico real sob 22 features (**0/15 `permanence_pass`**, sinal misto). `AG-371` corrigiu um viés estrutural real de Camada 0, mas a validação ficou CONFUNDIDA por uma sessão paralela mudando `T1_FEATURE_IDS` no meio do teste (22→29→36, últimos 2 não commitados) — decisão pendente do Manager sobre qual vetor é autoritativo. **Não citar "3/15 (20%)" nem "0/15" como veredito definitivo sem ler `§15.29`**. **[CORREÇÃO 2026-08-29, Changelog v3.57]** `AG-201` ("GPU/CUDA inviável no Windows nativo") **corrigido** — GPU real funciona via WSL2, ver §15.20 alínea D; `AG-371` **FECHADO** por reformulação (Optuna real substitui o YAML estático de hiperparâmetro por combo, não recalibração). **[CORREÇÃO 2026-08-30/31, ADR-007/ADR-008 — Governança item 2, 40 commits desde `022b0bd`]** `AG-371` (Optuna real) executado em produção pela primeira vez: campanha completa 1.800 trials (6 combos × 2 camadas × 150, `ADR-007` Item 1) → confirmação profunda 720 trials/10 seeds (Item 2) → **ZERO dos 6 combos passa o gate duplo** (`median_n_better`: `BTCUSDT/R3`=2,5, `BTCUSDT/R2`=3,0, `SOLUSDT/R2`=2,5, `SOLUSDT/R3`=3,0, `XRPUSDT/R2`=2,0, `XRPUSDT/R3`=2,5 — nenhum atinge o piso). `SOLUSDT/R2` confirma viés de seleção **+8,356, recorde do projeto** (Item 2). Calibração do FPR do gate duplo sob ruído puro (Item 3, `AG-220`): 8,0%/0,0%/0,0% — o gate não é impossível de passar por acaso, a ausência de sinal é real. Correção FDR aplicada à taxa-base H0-H7 (Item 4): 7/15 → 4/15 (BH) → 3/15 (BY). **Apesar da reprovação formal, o Manager autorizou override manual promovendo 5 candidatos a produção canônica** (`BTCUSDT/R2`, `SOLUSDT/R2`, `SOLUSDT/R3`, `XRPUSDT/R2`, `XRPUSDT/R3` — `BTCUSDT/R3` excluído deliberadamente; `config/constants.yaml::alpha_production_hyperparam_override`, `N_lifetime` id=38-40). **Auditoria institucional independente em seguida (`ADR-008`, 9 fases + correção de thresholds + auditoria de engenharia adversarial, `n_lifetime` id=42): walk-forward real refuta os 5 — AUC out-of-time≈0,50 na maioria dos combos/lados, `0 de 20` combo×variant×lado passa os 3 gates codificados (Data/Model/Alpha) mesmo após sweep de sensibilidade ±50%+ confirmar robustez do limiar.** Nenhum dos 5 candidatos promovidos sobrevive à avaliação fora-da-amostra no tempo — achado consolidado, decisão de produção sobre os 5 candidatos segue com o Manager. **[ATUALIZAÇÃO 2026-08-31/2026-09-01, auditoria adversarial, `§15.43`]** Sessão dedicada tentou REFUTAR "0/20" por 8 ângulos independentes (incluindo poder estatístico do gate Model/Alpha via meta-análise, bootstrap em bloco, condicionamento por regime barra-a-barra com n~70.000, causa raiz isolada de uma melhora de 8/10 células vista numa campanha de correção de `t0_end`) — **nenhum reverteu o veredito**; achado colateral real corrigido no caminho: seed do sampler Optuna era GLOBAL compartilhada entre as 10 studies de produção (`AG-399`), corrigido pra derivação por combo, mas os hiperparâmetros JÁ EM PRODUÇÃO não foram re-promovidos só por isso (melhorar sobre um canônico bugado não prova generalização). Detalhe completo: `docs/ADR-007_medicao_producao_hiperparametro_optuna_15_combos_2026-08-30.md`, `docs/ADR-008_auditoria_ml_alpha_institucional_score_quality_walkforward_2026-08-31.md`, `audit/architecture_gaps_log.yaml::AG-389`-`AG-392`,`AG-394`-`AG-419` | `docs/alpha_model_design_doc_2026-08-22.md`, `§15.20`, `§15.20.2`, `§15.29`, `§15.32`, `§15.33`, `§15.43` |
| V41-11 — Walk-forward + PBO + Lo | 0 | ⬜ não iniciado — `src/validation/walk_forward.py` não existe ainda | `PRD_V4_1.md` §4.6/§4.7 |
| V41-12 — ~~DSR final, `N_lifetime`=60~~ — **REDEFINIDO 2026-08-28** | 0 | 🟡 Gate 6 = lucro entregue em Live Demo (`AG-077`, fechado). Definição operacional: "lucro" = PnL positivo E distinguível de ruído (mesmo framework de `economic_gate.py::is_distinguishable`); "Live Demo" = capital real reduzido (não testnet/paper), dentro de `capital_inicial_brl` (R$ 1.000, §0); janela mínima 1 mês. **N mínimo de trades e semântica AND/OR entre janela e N seguem TBD** (`AG-374`, parcial) | `PRD_V4_1.md` §6.1, `audit/architecture_gaps_log.yaml::AG-077`, `AG-374` |

**Regra desta aba:** mesma de §11.5 — nenhuma linha muda de status sem
commit real apontável. `N_lifetime` orçado pra V4.1 completa era 15
trials (M4=6, V41-6=4, V41-7=3, V41-10=2) sobre a base de 45 —
**descontinuado como gate vinculante 2026-08-17** (decisão do Manager,
`§11.4`) — M4/V41-6/V41-7/V41-10 não ficam mais bloqueadas por
`counter=63 > 60`. `V41-12` (linha acima) e o critério de encerramento
#5 (`PRD_V4_1.md` §6.5) ficaram **sem definição operacional clara** até
o Manager decidir o que (se algo) substitui a penalidade de multiple-
testing no Gate 6 — **decisão tomada 2026-08-28, ver `AG-077`
(fechado)/`AG-374` (novo gap aberto pela própria decisão) logo abaixo**.

**Nota de proveniência, 2026-08-18 (achado ao atualizar a governança):**
a aritmética acima ("M4=6... base de 45") é texto HISTÓRICO da época em
que M4 tinha 6 trials — não reescrita retroativamente. Desde então, a
extensão de M4 (janelas críticas + R1/R2/R3, linha `M4(V4.1) — Regime`
acima) mudou a leitura pra `≤18` (ainda pendente de ratificação formal,
ver nota naquela linha) — se ratificado, a soma "base de 45" também
mudaria pra 57. Como `N_lifetime` já está descontinuado como gate
vinculante (não é mais aritmética operante), o impacto prático é baixo,
mas o texto fica impreciso se lido como referência sem este ponteiro.

**Atualização, 2026-08-19 (governança):** `≤18` de M4 agora está
ratificado por execução real (4ª rodada, ver linha `M4(V4.1) — Regime`
acima) — deixa de ser "sob revisão" e passa a ser fato consumado, mesmo
com `N_lifetime` não-vinculante. `AG-077` (o que substitui a penalidade
de multiple-testing no Gate 6) segue sem decisão do Manager — mas ganhou
um precedente parcial relevante na Trilha B (`AG-098`, ver `§15.11`):
seleção de linha symbol×resolution (o próximo eixo de busca do projeto,
pós-M4) foi resolvida com uma convenção de contagem ESTRUTURAL (backtest
individual por candidata = 1 trial, nunca colapsa por resultado da
rodada) — não fecha `AG-077` sozinha (é sobre uma dimensão nova, não
sobre o Gate 6 em geral), mas é o tipo de precedente que a decisão final
de `AG-077` provavelmente vai precisar reconciliar.

**Atualização, 2026-08-28 (`AG-077` FECHADO) — Gate 6 deixa de ser
estatístico, vira empírico.** Decisão direta do Manager: "o que define
'pronto' é entregar lucro Live Demo". Nada substitui `N_lifetime`/DSR
por outra fórmula de multiple-testing — o próprio Gate 6 (`V41-12`,
linha acima) deixa de ser "DSR final com N_lifetime=60" e passa a ser
resultado empírico real (lucro em ambiente de Live Demo). Escopo da
mudança: só o Gate 6 POSITIVO (definição de sucesso/conclusão) — os
critérios de ENCERRAMENTO #5/#6 de `PRD_V4_1.md §6.5` (guardrail contra
busca infinita sem edge) e os Gates 0-5 (promoção de artefato/constante
individual, `§16.1`/`§16.10`) são mecanismos distintos, não tocados por
esta decisão. `src/validation/dsr.py`/`_audited_n_lifetime()` (código
real que ainda lê `N_lifetime`) também não foi tocado — se deve ser
removido, marcado non-binding, ou mantido como diagnóstico auxiliar é
decisão de implementação separada, ainda não tomada.

**Fechar `AG-077` abriu um gap novo** (`AG-374`, mesma disciplina de
`AG-114`/`AG-118`/`AG-122` — toda regra de decisão travada a priori
precisa de definição operacional de cada termo, `CLAUDE.md`) — **2 dos 3
termos já definidos no mesmo dia, via 3 perguntas diretas ao Manager**:

- **"Lucro"** = PnL positivo **E** distinguível de ruído — mesmo
  framework já usado em `economic_gate.py::is_distinguishable`/`AG-246`
  (método delta, erro combinado), aplicado ao PnL realizado de Live Demo
  (não a um backtest). Rejeitado explicitamente "qualquer PnL positivo
  uma vez" — vulnerável a variância de amostra pequena.
- **"Live Demo"** = capital real reduzido, dentro do `capital_inicial_
  brl` já travado (R$ 1.000, `§0`) — NÃO testnet, NÃO paper trading. Só
  capital real prova liquidez/slippage/fill real — e esta sessão já
  mediu que isso importa de verdade (fill 42,2% vs. 97,1% otimista,
  `PRD_V4_1.md §6.5` critério 3).
- **Capital/janela — PARCIAL**: capital R$ 1.000 (mesmo de cima, não é
  grau de liberdade livre), janela mínima 1 mês corrido. **N mínimo de
  trades continua TBD, não inventado** (B23) — candidato de precedência
  no próprio repo (`evidence_ledger.yaml::n>=200` pra status "verde") foi
  calibrado pra amostra de BACKTEST, não pro ritmo real de sinal de Live
  Demo (`AG-371` já mostrou células que ficam dias sem sinal) — aplicar
  sem checar factibilidade repetiria o erro que este próprio gap existe
  pra evitar. Semântica entre janela e N (as duas condições precisam
  valer, ou uma basta) também não travada ainda.

Sem consequência imediata — o projeto está longe de ter um candidato
real a Live Demo hoje (`AG-371`) — mas fechar isso antes de existir um
candidato na mesa evita o mesmo viés que B20 (`PRD_V4_1.md §6.3`) já
existe pra prevenir em outro contexto. Detalhe completo:
`audit/architecture_gaps_log.yaml::AG-374`.

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

**⚠️ [DESATUALIZADO, 2026-08-20] O trecho de `CLAUDE.md` v1.6 citado acima
não é mais o texto real do arquivo.** Decisão posterior do Manager
(2026-08-20, ratificação do ADR-001) reclassificou `PRD_V3_2_UNIFICADO.md`/
`PRD_V4_1.md` de "blueprint técnico corrente" pra **OBSOLETOS** — nunca
base de decisão de produção, só ponteiro de 1 linha vindo deste
documento. Os 2 únicos documentos canônicos hoje são este
(`PLANO_MESTRE_PRINCE2.md`) e o ADR-001 completo (`docs/ADR-001_
arquitetura_artefatos_e_contratos_2026-08-19_base.md`, ~1900 linhas) —
ver cabeçalho de `CLAUDE.md` (versão corrente) pro texto real. Esta
seção (`§13`) fica como registro histórico de QUANDO/COMO a decisão
original de 2026-08-12 foi aplicada, não como descrição do estado atual.

---

## 14. Road_Map Vivo — v1 SUBSTITUÍDO por v2 <a name="14"></a>

> **🔵 SUBSTITUÍDO (`AG-080`, 2026-08-17) — correção de rumo do Manager:**
> a leitura inicial desta rodada tratou "não republicar" como "aposentar
> o conceito" — **errado**. O objetivo de todo o discovery/conciliação
> desta sessão (Sprint-N↔V41-N, `§15.4`↔`§11.6`, `AG-075..081`) sempre
> foi REFATORAR o Road_Map Vivo, não abandoná-lo. O artefato original
> (link abaixo) fica como referência histórica — não é mais atualizado.
> **O sucessor é este:**
>
> ➡️ **[Road Map Vivo — v2](https://claude.ai/code/artifact/82d1a3ad-1ffd-427e-b120-a07d33a17637)**
> (publicado 2026-08-17, síntese consolidada das duas trilhas reconciliadas)
>
> `§11.4-§11.6` continua a fonte de estado TEXTUAL primária (o que este
> documento versiona linha a linha); o artefato v2 é a síntese VISUAL
> derivada dela — atualizar um dos dois sem o outro é exatamente o drift
> que gerou esta correção, então a disciplina agora é: mudança material
> em `§11.4-§11.6` → repassar pro v2 na mesma sessão, não depois.

### Histórico — v1 (⚠️ NÃO é mais atualizado, ver callout acima)

O texto abaixo descreve o artefato v1 como ele era ATÉ 2026-08-17 (tempo
presente/"vivo" no texto original, preservado como está escrito então) —
lido em sequência com o callout "SUBSTITUÍDO" acima, pode confundir:
desde `AG-080` a URL corrente é a do v2 (link no callout), esta aqui
ficou congelada.

**https://claude.ai/code/artifact/a6335e1a-1eb1-42ae-b3af-9b43b87ea3dd**

Mapa ponta a ponta em HTML, publicado a pedido do Manager 2026-08-12,
era **vivo** até 2026-08-17 — Claude republicava a mesma URL a cada
mudança de status ou Área nova/removida (não um retrato único).
Conteúdo à época: as duas trilhas reconciliadas explicitamente em vez de
forçadas numa sequência única inventada —

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
| DATA — vol/regime/features | `features/`, `regime/` | Parcial. Infra de path multi-TF existe mas TF hardcoded em 2 pontos-chave (`_sources.py`, `stress.py`); thresholds globais, não por (symbol,tf). **[DESATUALIZADO, `AG-080`]** `_sources.py:39-55` já branch por `bar_source` (`time_15m`/`dollar_r1`) desde a migração Parkinson/dollar-bar (§11.5). **[DESATUALIZADO 2026-08-23, `AG-177` fechado por D-01, `§15.21.2`]** `stress.py` não usa mais default hardcoded — `s06_bar_gap_dollar` despacha por `bar_source`, causal/expansivo (commit `6902352`) |
| DATA — barreiras/label | `labels/` | Parcial. `symbol` real, **TF hardcoded em 3 lugares independentes** (`triple_barrier.py` 2x, `barrier_sweep.py` 1x) — `decision_tf_minutes` existe no config mas metade do código não o lê |
| ML | `models/`, `validation/` | **1,5 de 5 camadas de ablação do PRD implementadas**; DSR e os 14 testes de leakage existem mas não rodam automaticamente; `model_id` sem símbolo/TF no nome |
| LIVE TRADING | `risk/`, `execution/`, `live/`, `monitoring/` | **~5% implementado.** `risk/` é biblioteca real sem nenhum caller de produção e sem dimensão de símbolo; `execution/`≈0%; `live/`=pacote vazio; `monitoring/`=1 função nunca chamada. **[DESATUALIZADO, `AG-123`, ver `§15.13`]** `risk/limits.py::control_01_regime_tradeavel` ganhou caller de produção conceitual em 2026-08-21 (`regime_tradeable: bool` resolvido por `src/regime/build_hmm.py`/`src/regime/classifier.py`) — ainda sem loop vivo (`live/` continua vazio, "caller" aqui é código pronto/testado, não execução real, `§15.13` limite de escopo explícito) |
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

> **Cross-reference formal com `§11.4-§11.6` (`AG-080`, 2026-08-17, ver
> tabela após o modelo abaixo).** Os nomes "Data Layer/ML Layer/Live
> Trading Layer" e seus itens (Data check, Split, Learner, Calibração,
> Monitoramento, Feedback pós-trade) vêm exatamente daqui. `§11.6`
> rastreia MEDIÇÃO (M1-M6/V41-N); esta seção rastreia PRONTIDÃO DE
> ENGENHARIA — perguntas ortogonais, mantidas como duas lentes separadas
> por decisão do Manager (2026-08-17), não fundidas (fundir perderia a
> informação 2D — ex. `14_MONITORAMENTO` pode ser "vermelho" em
> engenharia e "não precisa de comparação tipo-M1" ao mesmo tempo,
> `AG-079`, fechado).

```
DATA LAYER
  01_BARRA            src/data/{resample,lake,download,bars,build_dollar_bars}.py  🟢 pronto -- [CORRIGIDO
                                                                       2026-08-23, AG-138] recalibração causal
                                                                       FECHADA 2026-08-22 (AG-124, 15/15 células
                                                                       reprocessadas, zero vazamento residual
                                                                       real -- AG-137 limpou os 7 dias stale
                                                                       remanescentes). CLI (build_dollar_bars.py)
                                                                       ganhou --mode {single_window,walkforward}
                                                                       -- walkforward aciona o modo causal direto
                                                                       do CLI (antes só via script separado);
                                                                       single_window (legado) emite
                                                                       logger.warning explícito. AG-138 fechado,
                                                                       commit ef7f5d3
  02_DATA_CHECK        src/data/{checks,validate,schemas}.py           `symbol` suportado desde 2026-08-21
                                                                       (AG-125/AG-133): validate_dollar_bars()
                                                                       + campo symbol em QualityReport,
                                                                       testado p/ ETH/SOL
  03_FEATURES          src/features/{build,support,groups/*}.py        [CORRIGIDO 2026-08-23, AG-139] "TF
                                                                       hardcoded" obsoleto desde 2026-08-18
                                                                       (dispatcher multi-grade real,
                                                                       _sources.load_bars). "thresholds
                                                                       globais" segue correto (AG-043).
                                                                       banned_patterns.py --strict voltou a
                                                                       passar limpo (2 magic numbers sem noqa
                                                                       em support.py, linhas 168/285,
                                                                       corrigidos) -- AG-139 fechado, commit
                                                                       ef7f5d3
  04_VOLATILIDADE      src/features/volatility.py                      ilha — só alimenta labels hoje
  05_REGIME            src/regime/{build,classifier,stress}.py         [DESATUALIZADO, ver §15.13] HMM k=4
                                                                       ratificado por override executivo do
                                                                       Manager (AG-114, 2026-08-22) como
                                                                       candidato canônico, builder de produção
                                                                       real (build_hmm.py) pronto e causal --
                                                                       SEM consumidor real hoje ESPECIFICAMENTE
                                                                       pro CANDIDATO HMM (nem backtest nem
                                                                       live; o gate no Risk Engine que o
                                                                       consumiria foi desligado no mesmo dia,
                                                                       ver 12_RISK_ENGINE abaixo). [CORRIGIDO
                                                                       2026-08-23, achado de
                                                                       stage_readiness_audit] Isso NÃO significa
                                                                       "Regime Engine sem consumidor real" --
                                                                       o classificador BASELINE (build.py/
                                                                       classifier.py, mesmos arquivos desta
                                                                       linha) é consumido em produção desde o
                                                                       Sprint 8 via environments.py ->
                                                                       monotonic.py -> alpha.py::fit_side_model
                                                                       (monotone_constraints do Alpha derivados
                                                                       de IC estratificado por regime) --
                                                                       consumidor real, não downstream
                                                                       hipotético. D-01 (AG-177/183, 2026-08-23)
                                                                       já confirmou esse mesmo caminho de
                                                                       consumo
  06_BARREIRAS         (não existe separado — dentro de labels/)       refatoração real necessária, represada
                                                                       deliberadamente pós-Data-Layer-100%
                                                                       (confirmado ainda correto, 2026-08-22)
  07_LABEL             src/labels/{triple_barrier,fill_model}.py       [DESATUALIZADO] "TF hardcoded 3x"
                                                                       obsoleto desde AG-005 (2026-08-15) --
                                                                       resolution_id/dollar-bar suportado
                                                                       ponta a ponta desde AG-042/AG-116/
                                                                       AG-124. Bug CRITICAL real encontrado E
                                                                       corrigido 2026-08-22 (AG-100 F1: janela
                                                                       mark_1m vazia sob rajada de dollar-bar,
                                                                       crashava SOLUSDT/XRPUSDT R2/R3 --
                                                                       backfill real re-rodado com sucesso,
                                                                       5 símbolos x 2 resoluções). [CORRIGIDO
                                                                       2026-08-23] verify_config_hash (B15)
                                                                       wireado em src/models/dataset.py::
                                                                       build_modeling_frame -- AG-140,
                                                                       FECHADO. Confirmação empírica achou
                                                                       drift real de schema de hash (não de
                                                                       parâmetro -- git log confirma) contra
                                                                       labels/v1 de produção; reprocessado
                                                                       pelo usuário, 2 testes slow/integration
                                                                       confirmam. Ver §15.24-F
                                                                       [NOVO 2026-08-24, `AG-205`] fill de SL
                                                                       ganhou ajuste gap-aware (D4) --
                                                                       `config_hash` ganhou campo `barrier_
                                                                       fill_policy_id` pra fechar ponto cego
                                                                       do B15 (mudança de CÓDIGO não invalidava
                                                                       hash antes). Todo labels.parquet
                                                                       persistido diverge agora, reprocessamento
                                                                       NÃO disparado. Ver §15.24-H, Changelog
                                                                       v3.53
  07b_PESOS            src/labels/weights.py                           movido da ML LAYER

ML LAYER
  08_SPLIT             src/validation/cpcv.py                          embargo_ms=347010000 (96,39h,
                                                                       MEASURED, invariante a tf) -- AG-032/E1.
                                                                       [CORRIGIDO 2026-08-23] mecanismo/
                                                                       política de proteção do componente-96
                                                                       (max_feature_lookback_ms) FECHADO
                                                                       2026-08-21 (AG-032), wireado nos 2
                                                                       call-sites reais (pipeline.py:432,
                                                                       leakage.py:798, fail-fast por desenho).
                                                                       [DECIDIDO E IMPLEMENTADO 2026-08-23]
                                                                       decisão (a) -- as 3 features expanding
                                                                       SAEM de T1_FEATURE_IDS (commit 78169df,
                                                                       AG-032 addendum). Consequência: o gate
                                                                       que mascarava (b) foi removido -- AG-159/
                                                                       D-02 (ressalva de MAGNITUDE do proxy
                                                                       p99, até 5,8x sob-cobertura em
                                                                       SOLUSDT/R3) deixa de ser dormente, vira
                                                                       pré-requisito real antes do 1º treino
                                                                       sob R2/R3 com purge ativo. Diagnóstico
                                                                       novo escrito (tools/diagnostics/
                                                                       measure_max_consecutive_bar_window_
                                                                       duration.py), resultado pendente do
                                                                       usuário rodar. Ver §15.21.2/§15.26
  09_LEARNER           src/models/{alpha,monotonic}.py                 1,5/5 camadas PRD wired em produção
                                                                       (run_layer1_sprint só chama Camada 0/1);
                                                                       regime CONFIRMADO removido do vetor de
                                                                       treino (Fase A, §15.13, 2026-08-21).
                                                                       [CORRIGIDO 2026-08-23, achado de
                                                                       stage_readiness_audit] "stability.py
                                                                       órfã" era FALSO desde a origem (2026-
                                                                       08-12) -- tem caller real desde a
                                                                       própria criação (faixa2_e3_stability.py,
                                                                       mesmo commit b02087b, 2026-08-09),
                                                                       implementa a Camada 2 formal do PRD
                                                                       (§5.4), já rodada sobre 15 splits reais
                                                                       de CPCV x 2 lados. O que falta não é
                                                                       uso -- é PROMOÇÃO A PRODUÇÃO (resultado
                                                                       é ranking, T1_FEATURE_IDS intocado;
                                                                       threshold alpha_stability_screen_limiar
                                                                       segue ASSUMED, sweep pendente). Gap real
                                                                       de AG-141: NÃO é "zero persistência" --
                                                                       src/models/persistence.py existe,
                                                                       testado (12 testes, booster/calibrador
                                                                       bit-exatos), revisado por
                                                                       project_assurance (3 MEDIUM corrigidos,
                                                                       AG-146/147/148, commit 96b3c3a) desde
                                                                       2026-08-22. Falta só a INTEGRAÇÃO ao
                                                                       pipeline real: alpha.py::run_fold não
                                                                       chama write_model_bundle (confirmado,
                                                                       zero ocorrências hoje) -- AG-141 segue
                                                                       aberto, por esse motivo específico
                                                                       [NOVO 2026-08-24, H7, Changelog v3.52]
                                                                       ablação T2->T1 deixou de ser "tarefa
                                                                       futura" (ver linha 09_LEARNER acima, nota
                                                                       antiga) -- Fase 0 (piso de ruído, nulo
                                                                       calibrado) + Fase 1 (mapa de capacidade,
                                                                       ETHUSDT/R1) EXECUTADAS. Resultado: T2
                                                                       NÃO supera T1 (7 features) nesta rodada
                                                                       -- mesmo a melhor combinação do grid
                                                                       fica ~2 desvios-padrão pior que o piso
                                                                       de ruído medido. T1_FEATURE_IDS
                                                                       permanece intocado. Escalar pra Fase 2
                                                                       ou generalizar pendente do Manager. Ver
                                                                       `docs/t2_t1_ablation_veredito_duas_
                                                                       analises_2026-08-24.md`
                                                                       [ATUALIZADO 2026-08-25, Changelog v3.54]
                                                                       Campanha completa: Fase 2 (extensão de
                                                                       fronteira, achou ponto perto do piso de
                                                                       ruído) + confirmação (repetição de seed +
                                                                       gate real -- REFUTOU Fase 2, era sorte de
                                                                       1 seed) + `ADR-002` (redesenho robusto a
                                                                       viés de seleção, 5 hiperparâmetros nunca
                                                                       testados cobertos, mediana de top-5 em vez
                                                                       de argmax) -- veredito final confirmado:
                                                                       T2 não sobrevive em ETHUSDT/R1, mesmo com
                                                                       metodologia completa. **Manager RATIFICOU
                                                                       promoção mandatória T2->T1 mesmo assim
                                                                       (`AG-207`), decisão de NEGÓCIO explícita
                                                                       reconhecendo violação de R4 (§0.2, "teto
                                                                       de features = medido, nunca estipulado")
                                                                       -- primeiro override deste tipo no
                                                                       projeto.** `ADR-003` calibrou
                                                                       hiperparâmetro pra essa promoção nas 10
                                                                       piores combinações por `ret_net` (não as
                                                                       15 inteiras). Escopo real corrigido em
                                                                       tempo real 2x: (1) "T2 substitui T1"
                                                                       (convenção de pesquisa) -> "T2 soma a T1"
                                                                       (69 features, mandato real do Manager,
                                                                       `AG-234`); (2) ortogonalidade T1+T2
                                                                       combinada nunca medida -- medida depois,
                                                                       média 41,4/69 sobrevivem, achado novo:
                                                                       `A13_dist_ema48_atr`×`B01_rsi_14` (2 dos 7
                                                                       T1 originais) correlacionados 0,91-0,995
                                                                       nos 10 combos, sem exceção -- T1 nunca
                                                                       tinha sido checado por redundância
                                                                       interna. 10/10 combos com artefato real
                                                                       de produção gravado (69 brutos, filtro
                                                                       ainda não aplicado). 2 achados críticos
                                                                       de sessão paralela pesam sobre TUDO isso:
                                                                       `AG-220` (gate de permanência mede ruído
                                                                       de variância de path do CPCV, não sinal,
                                                                       medido em 3 experimentos pareados reais)
                                                                       e `AG-221` (metade do edge bruto negativo
                                                                       medido na campanha inteira é artefato de
                                                                       latência sintética da granularidade
                                                                       mark_1m, não mercado -- correção proposta
                                                                       via `agg_trades`, implementada, não
                                                                       aplicada como default). `T1_FEATURE_IDS`
                                                                       nos módulos de produção real (`run_
                                                                       layer1_sprint`) já aceita `feature_ids`/
                                                                       `hyper` explícitos (`AG-227`) -- D-11 do
                                                                       design doc do Alpha ("hiperparâmetro
                                                                       único v1, ASSUMED até sweep") fica
                                                                       parcialmente fechado só pras 10
                                                                       combinações calibradas. Pendente do
                                                                       Manager: aplicar conjunto filtrado
                                                                       (39-43) em vez do bruto (69); decidir
                                                                       `agg_trades`; investigação de gate em
                                                                       BPS ainda não iniciada. Ver `docs/
                                                                       ADR-003_hiperparametro_feature_set_
                                                                       completo_2026-08-25.md`,
                                                                       `audit/architecture_gaps_log.yaml::
                                                                       AG-207/AG-220/AG-221/AG-227/AG-234`
                                                                       [NOVO 2026-08-30/31, ADR-007/ADR-008,
                                                                       Governança item 2] Optuna real (AG-371)
                                                                       rodou em produção pela 1a vez: 1.800+720
                                                                       trials -- ZERO dos 6 combos passa o gate
                                                                       duplo mesmo sob confirmação profunda (10
                                                                       seeds); SOLUSDT/R2 confirma viés de
                                                                       seleção +8,356 (recorde do projeto);
                                                                       FPR do gate sob ruído puro calibrado em
                                                                       8,0%/0,0%/0,0% (AG-220). Manager
                                                                       autorizou override manual promovendo 5
                                                                       candidatos (BTCUSDT/R2, SOLUSDT/R2,
                                                                       SOLUSDT/R3, XRPUSDT/R2, XRPUSDT/R3) a
                                                                       produção apesar da reprovação formal.
                                                                       Auditoria institucional independente em
                                                                       seguida (ADR-008, walk-forward real, 9
                                                                       fases + correção de thresholds +
                                                                       auditoria de engenharia adversarial):
                                                                       AUC out-of-time≈0,50 na maioria dos
                                                                       combos/lados, 0 de 20 combo×variant×lado
                                                                       passa os 3 gates codificados mesmo após
                                                                       sweep de sensibilidade ±50%+ -- nenhum
                                                                       dos 5 candidatos promovidos sobrevive à
                                                                       avaliação fora-da-amostra no tempo. Ver
                                                                       `docs/ADR-007_medicao_producao_
                                                                       hiperparametro_optuna_15_combos_2026-08-
                                                                       30.md`, `docs/ADR-008_auditoria_ml_alpha_
                                                                       institucional_score_quality_walkforward_
                                                                       2026-08-31.md`, §15.32, §15.33
  09b_CALIBRACAO       (inline em alpha.py — não separável hoje)       sem gate de amostra pequena (n_cal_eff)
  10_VALIDACAO         src/validation/{dsr,leakage}.py                 existe (CPCV wired em produção real via
                                                                       pipeline.py; DSR/leakage existem mas
                                                                       não são gate de nada) -- ver linha 1205
                                                                       da tabela de cross-reference abaixo,
                                                                       as duas se complementam, não contradizem
  11_META_MODEL        (src/models/meta.py+meta_dataset.py — F0-F5 de §15.19/§15.30/§15.31)  movido de 08 pra cá, pós-learner
  11b_DECISION_ENGINE  (não existe — PRD_V3_2 Parte VII §7.1-7.3)       AG-095 (2026-08-19): consome regime.tradeable
                                                                        direto, ficou fora deste modelo até agora.
                                                                        AG-143 (2026-08-22, aberto): o Gate 01
                                                                        especificado (§7.3) replicaria o mesmo
                                                                        regime.tradeable recém-desligado do Risk
                                                                        Engine por falta de sinal econômico --
                                                                        decisão do Manager necessária ANTES do
                                                                        1º commit deste estágio

LIVE TRADING LAYER
  12_RISK_ENGINE       src/risk/{sizing,limits,kill_switch}.py         Gate de regime
                                                                        (control_01_regime_tradeavel) definido/
                                                                        testado/exportado, mas DESLIGADO de
                                                                        evaluate_all() desde 2026-08-22
                                                                        (AG-114/AG-118, commit 3c0d83d) --
                                                                        lift≈1,0 em 90 células, sem sinal
                                                                        econômico detectável. Sizing por ativo
                                                                        segue ausente. Ver §15.13
  13_EXECUCAO          src/exchange/adapter.py, src/execution/         ~0%, place_order NotImplementedError
                                                                        (confirmado ainda correto, 2026-08-22)
  14_MONITORAMENTO     src/monitoring/{logging,dollar_bar_drift}.py    dollar_bar_drift.py (315 linhas, 16
                                                                        testes, existe desde 2026-08-16) --
                                                                        real/testado mas sem caller de
                                                                        produção, cobre só 1 alarme
                                                                        auto-inventado (AG-042), não os 12
                                                                        alertas/6 páginas de §13.1/§13.2.
                                                                        logging.py: 1 função nunca chamada
  15_FEEDBACK_POST_TRADE src/models/decomposition.py                  existe desde 2026-08-09, 3 famílias de
                                                                        caller real, decomposição por trade
                                                                        individual ainda não exposta (só
                                                                        agregada/por-path). Opera só sobre
                                                                        trade SIMULADO de backtest -- versão
                                                                        "live" gated por 13_EXECUCAO
```

**Tabela de cross-reference formal, `§15.4` (prontidão de engenharia) ↔
`§11.6` (medição M1-M6/V41-N) — `AG-080`, 2026-08-17:**

| estágio `§15.4` | equivalente `§11.6` | nota |
|---|---|---|
| `01_BARRA` | M2 (Barra) | dollar bar canônico. **[CORRIGIDO 2026-08-23]** recalibração causal FECHADA 2026-08-22 (`AG-124`); `AG-138` (CLI legado não-causal por padrão) fechado 2026-08-23, ver linha `01_BARRA` da tabela ASCII acima |
| `02_DATA_CHECK` | sem equivalente | `AG-079` fechado — checklist determinístico, não precisa de comparação tipo-M1. **[DESATUALIZADO]** `symbol` já exercitado desde 2026-08-21 (`AG-125`/`AG-133`) |
| `03_FEATURES` | V41-7 (Pesos+Features, parcial) | depende de V41-6 primeiro. **[CORRIGIDO 2026-08-23]** "TF hardcoded" da tabela ASCII acima é obsoleto desde 2026-08-18; `AG-139` (banned_patterns --strict falhando) fechado 2026-08-23 |
| `04_VOLATILIDADE` | M1 (Volatilidade) | ✅ medido, Parkinson decidido — DECIDIDO, NÃO DEPLOYADO (§11.5) |
| `05_REGIME` | M4 (Regime) | 🟡 Fase D re-executada (2026-08-18) com `AG-084`-`AG-087` corrigidos, mas BOCPD liderando de novo sob Cochran's Q/I² disparou auditoria cética nova — `AG-090`/`AG-091`/`AG-092`/`AG-093` TODAS implementadas E auditadas de forma independente (0 CRITICAL/HIGH remanescente, 2026-08-19) — 4ª re-execução autorizada, comando entregue ao Manager (§11.6). **[ATUALIZAÇÃO 2026-08-22]** resultado final: `hmm_gaussian_k4_v1` ratificado por override executivo (`AG-114`/`§15.13`), não por resolução estatística limpa — Gate 1/Gate 3 permanecem tecnicamente frágeis, registrado |
| `06_BARREIRAS` | V41-6 (Barreiras) | ⬜ não iniciado, depende de V41-5 |
| `07_LABEL` | sem equivalente de medição | `AG-079` fechado — proveniência de literatura fechada em `PRD_V4_1.md` §4.2, não estudo M-style. **[DESATUALIZADO 2026-08-23]** "sem equivalente" segue correto, mas ver linha `07_LABEL` da tabela ASCII acima — `AG-100`/`AG-140` (`AG-140` corrigido, ver §15.24). **[NOVO 2026-08-24]** fill gap-aware de SL (`AG-205`) + `config_hash` fechando ponto cego do B15 (§15.24-H) |
| `07b_PESOS` | V41-7 (Pesos+Features) | mesmo item de `03_FEATURES` |
| `08_SPLIT` | sem equivalente de medição | `AG-079` fechado — `G-WF-1..6` (CPCV↔walk-forward) já é comparação de facto |
| `09_LEARNER` | sem equivalente ativo | `AG-079` fechado — gatilho de reabertura declarado em §4.3, não decisão sem critério. **[ATUALIZADO 2026-08-23]** deixou de ser hipotético: LightGBM treinado de verdade em 15 combinações reais (`§15.20.2`), resultado 3/15 gate de permanência — ver `evidence_ledger.yaml::alpha-lightgbm-sweep-15-combinacoes-2026-08-23`. **[NOVO 2026-08-24]** `AG-204` corrige `tp_atr_mult`/`sl_atr_mult` de produção pós-S1, retreino redisparado; ablação T2→T1 (H7) refuta promoção na Fase 1 — ver linha `09_LEARNER` da tabela ASCII acima. **[NOVO 2026-08-30/31]** Optuna real (`ADR-007`) + auditoria walk-forward (`ADR-008`) — 0/20 combo×variant×lado passa os 3 gates codificados, nenhum dos 5 candidatos promovidos sobrevive; ver linha `09_LEARNER` da tabela ASCII acima e `§15.32`/`§15.33`. **[NOVO 2026-08-31/2026-09-01]** auditoria adversarial dedicada tentou refutar "0/20" por 8 ângulos + roadmap de 17 itens — nenhum reverteu, ver `§15.43` |
| `09b_CALIBRACAO` | V41-9 (Calibração+`confidence_rank`) | ⬜ não iniciado |
| `10_VALIDACAO` | V41-11 (Walk-forward+PBO+Lo) | ⬜ não iniciado, `walk_forward.py` não existe. **Nota de leitura (`stage_readiness_audit`, 2026-08-22): esta linha e a linha `10_VALIDACAO` da tabela ASCII acima não se contradizem** — CPCV (`cpcv.py`) está completo e wired em produção real (`pipeline.py`); DSR/leakage (`dsr.py`/`leakage.py`) existem e são maduros mas não são gate de nada; PBO/CSCV e `walk_forward.py` (medição de decaimento do Alpha treinado, diferente de `volatility_walkforward.py`/`regime_utility.py`, que são seleção de componente M1/M4) simplesmente não existem — as duas linhas, juntas, dão o quadro completo |
| `11_META_MODEL` | V41-10 (Meta-Model) — **Grupo J desacoplado, movido para depois** (`§15.19`) | 🔴 **F0-F8 COMPLETO, QUATRO medições convergentes reprovam** (2026-08-30 a 2026-09-01, `§15.30`/`§15.31`/`§15.38`-`§15.42`): `src/models/meta_dataset.py`, `src/models/meta.py` (orquestração F5.5 completa — `run_meta_fold`/`run_all_meta_folds`/`run_meta_sprint`), `src/models/meta_ablation.py` (F6 — A0/A1/A2-nulo/A3), `src/models/meta_walk_forward.py` (F6b — split causal único), `src/validation/leakage.py` (F7 — testes #10/#11 reais), `src/validation/cpcv.py` (`AG-151` fechado), `src/analysis/meta_fp_inventory.py` (P0-P3 completos). `P0`/`P1` fechados 2026-08-31 (9/10 calibrado, `AG-402` não bloqueante). **`P3`/Gate E0 REAL rodou 2026-08-31 contra os 5 combos de produção — 0 de 5 passam** (`AG-404`, vermelho). **F6 (ablação real) rodou 2026-09-01 — 0 de 5 SÍMBOLOS passam o critério primário** (`AG-409`, vermelho): 2 combos (SOLUSDT/R3, XRPUSDT/R3) sem nenhum fold capaz de ajustar modelo, Jaccard(A1,A3)=1,000 exato na maioria (Meta ≈ reparametrização de `tau`). **F6b (walk-forward ancorado, `§4.4`) rodou 2026-09-01 — 0 de 5, ainda mais decisivo** (`AG-413`, vermelho): os 5 combos caem em `INSUFFICIENT_SAMPLE`, o Meta nunca chega a ajustar modelo sob a estrutura causal real, nem `BTCUSDT/R2`. **F7 (enforcement B07/B08, D-13/`§10`, as 5 camadas) fechado 2026-09-01** — runtime (já existia) + teste #10 real com controle positivo + teste #11 estendido (`_META_PATH`, 3 propriedades análogas) + B07 `automated=True` (0 violações novas contra `src/`) + import-linter `alpha↛meta` (8 contratos mantidos). **F8 fecha por CONFIRMAÇÃO 2026-09-01** — nenhuma das 6 constantes "não criadas" do `§11` precisava ser criada (mecanismo/já-sem-limiar/gate-bloqueado/fabricação dado o resultado medido), `N_lifetime++` (ids 43/44, `counter` 5520→5530). Quatro achados convergem por metodologia totalmente diferente: Alpha "0/20" (`AG-391`), Gate E0 "0/5" (`AG-404`), F6 "0/5 símbolos" (`AG-409`), F6b "0/5, sem amostra pra tentar" (`AG-413`). Consequência pré-declarada do design doc ("Meta sai do roadmap") NÃO aplicada — decisão explícita do Manager, 2026-09-01: "não é impeditivo agora, finalize a construção mesmo assim, eu investigo isso depois" | `docs/meta_model_design_doc_2026-08-22.md`, `§15.19`, `§15.35`-`§15.42`, `AG-404`, `AG-409`, `AG-413` |
| `11b_DECISION_ENGINE` | sem equivalente de medição | ⬜ não iniciado — `AG-095` (2026-08-19): estágio adicionado à tabela nesta data, existia no PRD_V3_2 (Parte VII) desde sempre mas nunca tinha entrado neste modelo; consome `regime.tradeable` (gate 01, §7.3) — consumidor real de Regime. **[DESATUALIZADO, `AG-123`]** lista original citava "Alpha" como um dos consumidores de Regime — caiu na Fase A de `§15.13` (2026-08-21): regime SAIU do vetor de treino do Alpha (`DESIGN_COLUMNS` só as 10 features T1), ADR-001 §2.7 ratificado (regime = gate, não feature). Consumidores reais hoje: Risk (`§15.13` Fase C, hoje desligado — ver `12_RISK_ENGINE`), Decision Engine (esta linha, não implementado — `AG-143`), Meta/Execução (não implementados) |
| `12_RISK_ENGINE` | V41-8 (Controle 19+sizing) | 🟡 parcial — Controle 19 implementado (`AG-081`), sizing por ativo não. **[DESATUALIZADO, 3ª ocorrência confirmada `AG-123`]** "Regime wired" foi DESLIGADO de `evaluate_all()` em 2026-08-22 (`AG-114`/`AG-118`, commit `3c0d83d`) — função mantida definida/testada/exportada, não chamada |
| `13_EXECUCAO` | sem equivalente de medição hoje | RPI vs. post-only (`§9.5.1`, `AG-078`) é Sprint 16, ainda distante |
| `14_MONITORAMENTO` | sem equivalente | `AG-079` fechado — zero código digno de comparação tipo-M1 (continua correto), **não** zero código tout court — ver linha `14_MONITORAMENTO` da tabela ASCII acima (`dollar_bar_drift.py` real desde 2026-08-16), addendum `AG-080` 2026-08-22 |
| `15_FEEDBACK_POST_TRADE` | sem equivalente | `AG-079` fechado — identidade contábil, não estimador com candidatos (continua correto). **[DESATUALIZADO]** "sem equivalente" refere-se à ausência de medição M-style, não à ausência de código — ver linha `15_FEEDBACK_POST_TRADE` da tabela ASCII acima (`decomposition.py` real desde 2026-08-09), addendum `AG-080` 2026-08-22 |
| (sem estágio dedicado) | M3 (Timeframe) | `decision_tf` atravessa vários estágios, não é um estágio único |
| (sem estágio dedicado) | M6 (Fator comum) | teste de hipótese cross-asset, não um estágio de pipeline — ✅ fechado |
| (sem estágio dedicado) | V41-5 (PRD V4.2 escrito) | deliverable de documentação, não de código |

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
   **Item 2 endereçado (2026-08-16/17, Fase 4 do refactor Parkinson/
   dollar-bar, `AG-080`)** — `build_modeling_frame`/`run_layer1_sprint`/
   `leakage.py`/`fill_reconciliation.py` agora parametrizados por
   `resolution_id`/`tf`, roteando pra path real em vez de default morto.
   Nunca marcado como "executado" nesta seção até agora.
3. **Migrar `features/build.py`/`group_c.py` pro `VolatilityEstimator`**
   — fecha a duplicação de fórmula ATR (achado desta sessão E da
   anterior) e faz `03_FEATURES`/`05_REGIME` herdarem a escolha do GK
   automaticamente, sem trabalho extra.
   **Item 3 endereçado por mecanismo DIFERENTE do especificado
   (2026-08-16/17, `AG-080`)** — `c01_atr_20` (`group_c.py:18-20`)
   continua chamando `support.atr_wilder` direto, não injeta o Protocol
   `VolatilityEstimator`; o que existe é uma função irmã
   (`c01_atr_20_parkinson`) selecionável por `vol_estimator_id` (string).
   Resultado prático similar (estimador pluggable), desenho diferente do
   originalmente proposto — registrado com a nuance, não como "feito
   100%".
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
  não inventa métrica nova). A promoção de GK nunca chegou a "represada
  até M2/M3" — foi SUPERADA antes de completar: o Manager decidiu
  Parkinson (não GK) como estimador canônico em 2026-08-17, depois que
  M1 foi remedido sob dollar-bar (`AG-036`, 12/15 combinações). Medição
  abaixo segue válida como evidência histórica de que GK≠Wilder é
  diferença real; `docs/refactor_gk_canonico.md` foi renomeado pra
  `docs/refactor_parkinson_canonico.md` no mesmo momento da decisão —
  ver `config/constants.yaml::canonical_volatility_estimator` pro
  estimador real hoje.

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
que M4 já usa (Rand ajustado). M6 rodou e fechou no mesmo dia em que
este parágrafo foi escrito (2026-08-14, antes do resultado chegar) — H0
rejeitada nos 2 lados, I²=96-98%; ver `§11.6` linha `M6(V4.1)` pro
resultado real.

> **CORREÇÃO 2026-08-25 (`AG-238`) — o `I²=96-98%` acima está medido na
> grade ERRADA e não deve ser citado.** O M6 lia `data/labels/{symbol}/15m/`
> — grade de relógio, substituída como canônica por dollar bar (R1/R2/R3)
> desde `AG-042` (2026-08-16). Re-executado nas três resoluções de produção:
>
> | grade | I² LONG | I² SHORT | p SHORT | edge pooled LONG / SHORT (ATR) |
> |---|---|---|---|---|
> | 15m (legado) | 93,92% | 97,20% | 7,2e-30 | −0,032765 / −0,000906 |
> | **R1** | 83,28% | **60,56%** | **3,8e-02** | −0,009082 / −0,028398 |
> | **R2** | 79,81% | 81,03% | 3,1e-04 | −0,007407 / −0,019857 |
> | **R3** | 65,90% | 66,77% | 1,7e-02 | −0,007512 / −0,011926 |
>
> Três leituras: (1) H0 **segue rejeitada** em todas as células (p<0,05) —
> a conclusão qualitativa "os ativos não são o mesmo ativo" sobrevive, mas
> citar `96-98%` virou **overclaim**; (2) `I²` cai monotonicamente com a
> duração da barra, então a resposta **depende da resolução** e não deve ser
> poolada entre grades (`AG-043`); (3) **a leitura POR LADO inverte** — no
> 15m o SHORT era o lado de edge pooled ~nulo e o LONG o pior; na grade de
> produção é o **oposto nas três resoluções**. Qualquer decisão apoiada em
> "SHORT é o lado neutro/barato" está invertida. Evidência:
> `audit/evidence_ledger.yaml::m6_i2_r{1,2,3}_{long,short}`.

**M5 (fill completo) — pausado inicialmente (2026-08-14) pra decisão
explícita do Manager sobre contagem de trial.** Reli a definição exata
do PRD: "escopo completo" exige não só `labels/` (já feito) mas
`predictions.parquet` (via Alpha/CPCV) e `orders.parquet` (via
`fill_simulator`) pros 4 alts — treinar Alpha pela primeira vez pra 4
símbolos novos, decisão que `audit/n_lifetime.yaml` (precedentes ids
11/13/14 vs. id 12) mostra não ser mecânica, precisa de confirmação
explícita do Manager caso a caso. Esse regime (`N_lifetime` vinculante)
foi descontinuado em 2026-08-17 (`AG-077`) — M4+M5 já foram priorizados
diretamente pelo Manager desde então; ver `§11.4`/`§11.6` pro estado
real e pro orçamento/valor atual de M4 (`≤18`, não mais "até 6").

### 15.10 AG-017 — §15.1 previu o risco por nome, M2 caiu nele mesmo assim (2026-08-15)

**A previsão de §15.6 item 1 se confirmou, no módulo que ela citou por
nome.** `m2_bar_comparison.py` (escrito nesta sessão, depois de §15
existir) foi implementado com `BASELINE_TF = "15m"` hardcoded — media
dollar/volume/tick_imbalance bars só contra 15m, apesar do PRD_V4_1.md
§0.4 exigir os 3 TFs "obrigatórios ponta a ponta". Achado não veio de
revisão própria — veio de o usuário perguntar "os dollar/volume/
tick_imbalance vão sair para os 3 timeframes?" depois de eu já ter
fechado (na minha cabeça) o módulo como pronto.

**Por que isso importa mais do que "mais um bug corrigido":** a
informação estava disponível em DOIS lugares antes de eu escrever a
primeira linha do módulo — (1) `TIMEFRAMES` já definido em
`volatility_comparison.py`, um `import` de distância do que eu já estava
importando desse mesmo arquivo; (2) este documento, §15.6 item 1, já
tinha escrito literalmente "é o único bloqueador que produziria um erro
silencioso... se **M2/M3** rodarem antes disso ser corrigido" — nomeando
M2 como risco previsto, antes de M2 existir. Ter o registro RAID (AG-004,
sobre `cpcv.py::_BAR_MS`) não impediu a MESMA classe de bug reaparecer
num módulo novo, porque nada no processo de escrever um módulo novo
consultava esse registro antes de codar.

**Correção de código:** commit `67a1426` — `m2_bar_comparison.py` itera
`TIMEFRAMES` (mesmo padrão de `m3_timeframe_choice.py`), topologia do
pool preservada, `time_stop_ms` corrigido pra não recalcular por TF
(achado embutido — ver `AG-017`, `audit/architecture_gaps_log.yaml`).

**Correção de processo, pra não reaparecer uma 3ª vez:** nova pergunta
explícita na Lente FI de `audit_engineering` — todo módulo novo em
`src/analysis/`/`src/features/`/`src/labels/`/etc. precisa declarar se
itera `TIMEFRAMES` ou por que não. Isso não elimina a classe de bug
sozinho (a skill só roda quando alguém pede auditoria — este módulo não
foi auditado antes de "pronto"), mas registra o critério de julgamento
num lugar que uma auditoria futura vai consultar.

### 15.11 Resoluções propostas — AG-095/096/098/099 (2026-08-19, aprovado pelo Manager após 4 rodadas de contestação adversarial)

Contexto: auditoria cética comissionada pelo Manager sobre o desenho de
consumo de Regime por Alpha/Decision Engine/Meta-Label/Risk/Execução sob
o mandato novo (operar dinamicamente a combinação símbolo×resolução que
entregar mais edge, eliminando o resto) achou 10 gaps reais
(`audit/architecture_gaps_log.yaml::AG-094..AG-100` + addenda em AG-007/
AG-088). Seis deles exigem decisão do Manager antes de qualquer
implementação — mas metade dessas seis já tem resposta tecnicamente
informada, não é página em branco. Processo adotado (decisão do Manager,
2026-08-19, "pode seguir"): eu rascunho a resolução técnica, ela entra
aqui marcada **PROPOSTO**, uma auditoria adversarial independente
(`project_assurance`, agente sem contato com este raciocínio) contesta o
rascunho, repete até 2 rodadas seguidas sem achado CRITICAL/gap novo — só
depois disso o Manager confirma e só depois disso (se fizer sentido) um
auditor externo entra, pra estressar um desenho maduro, não pra descobrir
do zero.

**Rodada 1 (2026-08-19) — resultado: 1 SÓLIDO, 1 gap novo, 2 "precisa
revisão".** AG-095 confirmado sem achado. AG-096 escondia um segundo gap
do mesmo tipo de AG-007 (registrado como `AG-101`). AG-098 e AG-099
tinham lacunas reais de especificação.

**Rodada 2 (2026-08-19) — resultado: 1 CONVERGIU, 2 gaps novos.** AG-099
confirmado sem ressalva (as 3 frentes atacadas — reuso de conceito vs.
código, status "PROPOSTO" vs. dependência de Execução, literatura de
exit por tempo — não produziram achado real). `AG-101` tinha um problema
de latência/prioridade de rate-limit não endereçado (`AG-102`). O item 2
de `AG-098` usava resultado da rodada como critério de contagem, quando
o ledger já tem um critério ESTRUTURAL formal — gerava circularidade
real com o gate de DSR (`AG-103`, já corrigido no mesmo dia, ver
`resolution` da entrada). O loop adversarial fez de novo exatamente o
que deveria: achar problema real numa proposta que já tinha passado por
uma rodada — a rodada adversarial funciona precisamente porque um
rascunho concreto expõe gap mais afiado que uma folha em branco.

**Rodada 3 (2026-08-19) — resultado: 1 CONVERGIU, 1 gap novo.** AG-098
confirmado sólido (consistente com o critério "OU" de `n_lifetime.yaml`,
sem ambiguidade real no cenário de reuso de fit do M4). A lista de 3
caminhos pra `AG-096`/`AG-101`/`AG-102` tinha uma opção ("orçamento
dedicado") redigida de um jeito que reverteria a garantia de prioridade
absoluta de execução já codificada em `Budget.cap_for()` — `AG-104`,
corrigido no mesmo dia.

**Rodada 4 (2026-08-19, escopo estreito) — resultado: 1 gap novo.** A
correção de `AG-104` era tecnicamente correta mas resolvia um problema
diferente do que `AG-102` tinha levantado — `Budget` só tem 2 níveis de
prioridade, então tráfego de execução sozinho já esgota o teto de
não-execução inteiro antes de qualquer sub-fatia interna a P2/P3
importar. Opção removida da lista — `AG-105`, corrigido no mesmo dia.
Loop encerrado aqui por decisão de escopo (4 rodadas, retorno
decrescente, achados cada vez mais estreitos) — **Manager aprovou o
consolidado em 2026-08-19** ("aprovado"), com as sub-decisões abaixo
explicitamente registradas como ainda abertas, não decididas por
omissão.

**AG-095 (Decision Engine no PBS) — CONFIRMADO SÓLIDO (Rodada 1).**
`11b_DECISION_ENGINE` adicionado à tabela de `§15.4` e à tabela de
cross-reference logo abaixo, mesma convenção de sufixo `b` já usada por
`07b_PESOS`/`09b_CALIBRACAO`. Nenhuma renumeração dos estágios 12-15 —
inserção não-disruptiva. Revisão adversarial confirmou formatação/
numeração íntegras, sem achado.

**AG-096 (gate "uma posição por vez" vs. Controle 19) — mecanismo PROPOSTO 2026-08-19, especificação REFUTADA por auditoria externa (`AG-108`, `§15.12`): `(symbol, resolution_id)` não é entidade de posição na Binance USDⓈ-M. Arquitetura final (`LineState`/`SymbolExposure` por SÍMBOLO) ratificada 2026-08-22 — ver "Decisões abertas" no fim desta seção. Raciocínio de engenharia abaixo (latência/rate-limit) segue válido como referência técnica, não como o mecanismo vigente.**
`PRD_V3_2_UNIFICADO.md:1499` nunca foi emendado pelo V4.1; o Controle 19
(`PRD_V4_1.md` §5.3) pressupõe múltiplas posições concorrentes. Correção
de enquadramento (achado da Rodada 1): isto NÃO é emenda pontual a um
gate já implementado — zero código de Decision Engine existe hoje, e
`PRD_V3_2_UNIFICADO.md` §10.4 documenta uma única máquina de estados
GLOBAL de posição (`FLAT→LONG_PENDING→LONG→EXIT_PENDING→FLAT`), sem
nenhuma dimensão por linha a reaproveitar. É desenho greenfield inteiro,
não um patch — não muda a decisão, muda a expectativa de esforço.
Resolução proposta, em duas partes:

1. **Gate 04 do Decision Engine nasce por linha, não global**: "posição
   atual no MESMO `(symbol, resolution_id)` != FLAT → NO_SIGNAL" —
   permite candidatas concorrentes em linhas diferentes, preserva a
   proteção original contra duplicar sinal na MESMA linha.
2. **Cap interino de posições concorrentes, fora do Controle 19 — agora
   com pré-requisito explícito.** Controle 19 (`sigma_agg` via matriz de
   correlação) é `NOT_COMPUTABLE` sempre hoje — sem rastreador de posição
   ao vivo, ele não gateia nada na prática (`AG-007`). A Rodada 1 achou
   que o cap interino proposto ("total de posições abertas
   simultaneamente ≥ max_concurrent_positions → NO_SIGNAL") tem
   exatamente o mesmo problema — é, ele mesmo, um rastreador de posição
   ao vivo (versão não-ponderada), e nenhum módulo hoje consulta
   `get_position_risk` (`src/exchange/adapter.py:119-120`, `GET
   /fapi/v2/positionRisk`, primitivo já existe, zero caller) — registrado
   como **`AG-101`**. Ordem de implementação corrigida: (a) módulo mínimo
   de contagem ao vivo de posições abertas por símbolo ANTES de (b) o cap
   poder gatear qualquer coisa de verdade.
   **A Rodada 2 achou que (a) como descrita em `AG-101` era subespecificada
   até o ponto de gerar risco de latência real (`AG-102`)**: `get_position_
   risk` é `Priority.P2` em `src/exchange/rate_limit.py`, e `Budget.
   cap_for()` NUNCA deixa P2 tocar a reserva de orçamento de execução
   (P0/P1) — ou seja, sob rajada de tráfego de execução (justamente o que
   acontece sob STRESS, o mesmo regime em que o cap importa mais), a
   consulta de posição é a primeira a ser deferida. Piora porque R1/R2/R3
   são dollar bars calibradas por frequência MÉDIA (`PRD_V4_1.md:386`) —
   fecham mais rápido sob volume alto, então o Decision Engine avaliaria
   sinais com mais frequência exatamente nos mesmos picos que já disputam
   o orçamento P0/P1. A alternativa "user data stream" citada antes não é
   um atalho pronto — `src/exchange/ws.py` só tem ciclo de vida de
   `listenKey`, sem parsing de `ACCOUNT_UPDATE` e sem lib de WebSocket
   ainda em `pyproject.toml` — é MAIS trabalho que o REST, não menos.
   **Decisão de desenho que fica aberta pra quando `AG-101` for
   implementada — reduzida a 2 caminhos reais (Rodada 4, `AG-105`)**:
   uma 3ª opção ("orçamento de rate-limit dedicado pra `position_risk`,
   recortado de dentro do pool de P2/P3") foi considerada e descartada —
   não por violar o invariante de execução (isso já tinha sido corrigido
   em `AG-104`), mas porque `Budget` (`src/exchange/rate_limit.py:70-96`)
   só reconhece 2 níveis (execução = teto cheio; não-execução = teto×
   (1-reserve_pct)), com um único contador `used` COMPARTILHADO por P2 e
   P3 — não existe sub-alocação dentro do pool de não-execução pra
   proteger `position_risk` especificamente. Pior: tráfego de P0/P1
   sozinho já pode esgotar o teto de não-execução inteiro (com
   `ip_weight_limit_1m=2400`/`rate_limit_reserve_pct=0.30`, basta `used`
   passar de 1680) ANTES de qualquer chamada P2/P3 ser sequer avaliada —
   uma fatia "dedicada" dentro do P2/P3 não mudaria isso, porque o corte
   que importa (P0/P1 vs. P2/P3) já aconteceu antes. Ou seja: essa opção
   nunca resolveria o cenário que `AG-102` levantou (contagem de posição
   deferida sob rajada de execução), só um cenário diferente (perder pra
   `account_info`/`backfill`/`research`) que ninguém tinha pedido pra
   resolver. Restam 2 caminhos reais: **cache local com TTL curto**
   (aceita staleness limitada, sem tráfego extra por avaliação de sinal);
   ou **aceitar staleness maior com um gatilho de reconciliação separado**
   (mais simples, mas o cap gateria com dado potencialmente desatualizado
   durante o pico de STRESS). Nenhum escolhido aqui — decisão do Manager
   quando `AG-101` for implementada. Valor do cap em si segue
   `TBD — medir` (B23), ponto de partida "2 posições simultâneas"
   (`PRD_V4_1.md:591`), não valor final — precisa de sweep contra
   correlação real entre os 5 ativos antes de virar constante em
   `constants.yaml` (classe A).

Questão de negócio que sobra pro Manager, não resolvida por este desenho:
o denominador do K01 (`daily_loss_usd`/equity) quando há posições
concorrentes em símbolos diferentes — equity compartilhada entre todas,
ou algum nocional de referência por linha (addendum `2026-08-19` de
`AG-007`).

**AG-098 (N do DSR para seleção de linha) — ⚠️ NÃO CONFIAR: rotulado "CONFIRMADO SÓLIDO" abaixo (Rodada 3, 2026-08-19), mas a convenção "1 trial por linha avaliada" foi REFUTADA por auditoria externa no dia seguinte (`AG-111`, `§15.12`): sobre-conta por correlação entre linhas (N efetivo ~2, não 15, dado ρ≈0,8) e mantém resíduo de circularidade. `AG-111` segue ABERTO hoje (2026-08-23) — nenhuma convenção de substituição foi decidida. Risco real, não só documental: aplicar esta convenção numa seleção de linha real contaminaria `N_lifetime`/DSR sem detecção. NÃO usar esta seção como base de contagem até `AG-111` fechar.**

1. **Convenção de contagem**: cada `(symbol, resolution_id)` avaliada
   como candidata a promoção pra produção, no momento em que uma decisão
   real de manter/descartar é tomada, conta como 1 trial em
   `N_lifetime` — mesmo grão de `id 10` do ledger (célula que exige
   recálculo de backtest individual), explicitamente NÃO o grão de
   `id 16` (símbolo como leito de robustez de UMA escolha uniforme —
   categoria diferente, não aplicável aqui porque a seleção de linha é
   diferencial por construção).
2. **Regra corrigida (a Rodada 1 achou o cenário-armadilha certo, mas a
   1ª tentativa de regra estava errada — a Rodada 2 achou por quê e
   corrigiu no mesmo dia).** Tentativa original: contar como `id-10`-símil
   SE pelo menos 1 linha fosse promovida, `id-11`-símil se zero
   promoções — usava o RESULTADO da rodada como critério. Errado: o
   ledger já declara, no próprio cabeçalho (`audit/n_lifetime.yaml:
   19-29`), que a distinção id-10/id-11 é ESTRUTURAL (exige ajuste de
   modelo/backtest novo POR candidata, ou reusa artefato já ajustado sem
   backtest novo) — nunca depende de quantas candidatas acabam
   promovidas. Usar resultado como critério criava circularidade real
   com o gate de DSR (`n_trials` da rodada dependeria de "alguma linha
   foi promovida", que inclui a própria decisão sendo tomada —
   `src/validation/dsr.py::compute_dsr` alimenta `n_trials` direto em
   `sr0_per_trade`/`dsr`, então a penalidade de multiple-testing de uma
   linha dependeria do resultado que ela mesma ajuda a decidir).
   **Regra final: seleção de linha SEMPRE conta como `id-10`-símil — 1
   trial POR linha efetivamente avaliada com backtest/medição individual
   (N=15 se as 15 forem avaliadas), independente de quantas acabam
   promovidas.** Nunca colapsa a 1 trial pela rodada — o precedente
   `id 11` (70 features rankeadas por correlação já computada, sem
   backtest novo por candidata) é estruturalmente diferente e não se
   aplica aqui.
3. **Regra nova (gap da Rodada 1): re-teste da mesma linha após mudança
   de código conta como trial novo.** Código mudou (novo candidato de
   regime, nova feature, novo hiperparâmetro) ⇒ é estatisticamente uma
   linha diferente da que foi testada antes ⇒ conta de novo, mesmo se
   `(symbol, resolution_id)` for idêntico ao já testado.
4. **Registro segue mesmo com `N_lifetime` não-vinculante** (`AG-077`):
   contar agora, mesmo sem gate ativo, evita o problema já confirmado de
   reconstrução retroativa incerta (Q12 da auditoria de 2026-08-19 sobre
   M4) se/quando o DSR voltar a ser vinculante.
5. **Recomendação adicional, não bloqueante**: PBO/CSCV (Bailey, Borwein,
   López de Prado & Zhu) é o instrumento formal desenhado exatamente pra
   "várias variantes testadas sobre o mesmo dado, qual promover" — mais
   direto que a penalidade de N do DSR pra este caso específico. Não
   implementado neste repo hoje (`src/validation/dsr.py` já cita PBO como
   fora de escopo). Proposta: item de backlog do V41-11 (Walk-forward+
   PBO+Lo, `§15.4`), não pré-requisito pra começar a seleção de linha —
   a convenção de contagem dos itens 1-3 já é uma salvaguarda mínima
   suficiente pra não operar sem nenhum controle.

**AG-099 (posição aberta sob mudança de regime) — mecanismo PROPOSTO 2026-08-19, REFUTADO por auditoria externa (`AG-110`, `§15.12`): mesmo defeito de paridade treino-live da versão já refutada, deslocado (encurtar `time_stop` ao vivo usa `p` treinado sobre horizonte fixo pra decidir outro evento). Conclusão operacional (não adotar K15 ainda) já está correta no fim desta seção ("RESOLVIDO — ADIADO", 2026-08-22) — só o cabeçalho ficava desalinhado se lido isoladamente.**
Novo gatilho de Kill Switch, `K15` (`K14` já citado como "reservado" no
achado original — correção: o addendum `2026-08-17` da entrada de
origem usa a contagem ordinal "gatilho 14", nunca escreve literalmente
"K14" — extrapolação razoável pro nome, não uma citação exata; K15
confirmado livre por busca direta em `KILL_SWITCH_TRIGGER_IDS`,
`src/risk/kill_switch.py:273-275`, que tem exatamente 13 elementos,
K01-K13): `REGIME_STRESS_COM_POSICAO_ABERTA` — dispara quando
`regime_state(symbol, resolution) → R5/STRESS` E existe posição aberta
nessa linha.

**Mecanismo revisado — a Rodada 1 refutou a premissa original.** A
versão anterior propunha apertar o stop-loss; pesquisa de mercado da
revisão adversarial (OANDA, Optimus Futures, TradingView — práticas de
stop sob volatilidade) mostra o oposto do que a proposta original
assumia: apertar o stop sob alta volatilidade aumenta a chance de
stopout prematuro por ruído sem reduzir slippage de execução (uma vez
disparado, o stop vira ordem sujeita ao mesmo book fino independente da
distância). **Mecanismo novo: encurtar o `time_stop` (horizonte máximo
de holding) da posição, não tocar no preço do stop.** Reusa o conceito
de barreira TIME já existente no Label Engine (`src.labels.
triple_barrier::_BarrierTouch("TIME", ...)`) em vez de inventar mecânica
de amend de preço nova — reduz a JANELA de exposição ao regime adverso
sem alterar a distância do SL (elimina o risco de stopout prematuro por
ruído que motivou a correção). O SL original (preço) fica intocado —
elimina também o problema de janela-sem-proteção do amend-de-preço
(achado (b) da Rodada 1: `PRD_V3_2_UNIFICADO.md` §16.8/
`place_or_amend_stop` é cancela-e-reposta, sem endpoint nativo de amend
na Binance Futures — criaria uma janela breve sem SL ativo, pior momento
possível durante STRESS; correção também de citação — B14 rege ordem de
postagem TP/SL pós-fill, não mecânica de amend de SL já ativo, citação
anterior era non sequitur). **Questão mecânica residual, honesta, não
escondida**: forçar saída num horizonte antecipado ainda exige alguma
ação de execução real (`src/exchange/adapter.py::place_order` continua
`NotImplementedError` — nenhum código de execução existe hoje pra
verificar como isso se comportaria) — o desenho reduz o RISCO do
mecanismo (não mexe no SL), mas não elimina a dependência de a camada de
Execução existir. **Valor exato do encurtamento (ex. cortar X% do
horizonte restante): `TBD — medir` (B23)** — não inventado aqui, precisa
de medição de taxa de reversão-pós-stopout-prematuro vs. tamanho de
perda evitada antes de virar parâmetro real (métrica explícita, não só
"impacto em backtest" genérico). Decisão que sobra pro Manager: adotar o
gatilho agora (parâmetro por medir, valor conservador provisório com
`provenance: ASSUMED` explícito) ou aceitar o risco documentado por
enquanto e adiar pro Estudo 2 — gap é pré-existente ao multi-ativo (já
valia no V1 single-asset), a urgência vem só de multi-ativo multiplicar
quantas posições ficam expostas simultaneamente.

**Decisões abertas, registradas aqui pra não se perderem sob a aprovação
do consolidado (2026-08-19) — nenhuma delas foi decidida por omissão:**

> **Atualização 2026-08-22 (fechamento)**: das 7 decisões abaixo,
> **as 7 estão resolvidas ou ratificadas** nesta data. Itens 3, 4, 6, 7
> já eram resolvidos/sem tensão real desde antes (confirmado sem
> precisar de auditoria externa). Itens 1, 2, 5 dependiam de um
> mecanismo refutado (`AG-108`) ou da mesma evidência que desligou o
> gate irmão (`AG-118`) — resolvidos via síntese de 2 pareceres
> externos sobre `docs/brief_auditoria_externa_2026-08-22_decisoes_
> residuais_risco_regime.md` + ratificação do Manager no mesmo dia.
> Nenhum item fica "decidido por omissão" — cada um tem resolução
> registrada abaixo, com pontuação do que ainda é trabalho de
> implementação (não mais decisão de arquitetura).

1. **AG-096** — cache-local-com-TTL vs. aceitar-staleness-com-
   reconciliação, pra quando `AG-101` (módulo de contagem de posição ao
   vivo) for implementado. **RESOLVIDO 2026-08-22** — Manager autorizou
   a recomendação do `AG-108` (ledger local por evento, REST só
   reconciliação, falha-fechado) como direção de arquitetura. Falta
   implementação (`src/decision/line_state.py`, ADR-001 action item
   10) e a política de alocação de PnL entre linhas, ainda não
   decidida — ver `AG-108`/`AG-096` (addendum `ratificacao_manager_
   2026-08-22`).
2. **AG-096** — valor exato do cap de posições concorrentes (`TBD —
   medir`, ponto de partida 2). **RESOLVIDO na parte arquitetural,
   2026-08-22** — teto simples e controle 19 (correlação-ponderado)
   são controles COMPLEMENTARES, não fundidos em 1 (ratificado,
   `AG-096`/`AG-144`). Valor numérico "2" confirmado ROBUSTO à
   remedição real de ρ (`AG-144`: 0,70-0,83, não 0,91) mas ainda sem
   sweep formal contra correlação real (classe A, §16.10) — pendência
   de EXECUÇÃO, não de decisão.
3. **AG-096/AG-007** — denominador do K01 (`daily_loss_usd`/equity) sob
   posições concorrentes em símbolos diferentes — compartilhado ou por
   linha. **RATIFICADO 2026-08-22** — equity total da conta
   (`wallet_balance + unrealized_pnl`), ancorada 00:00 UTC (`AG-007`
   addendum `ratificacao_manager_2026-08-22`, recomendação técnica do
   `ADR-001` §2.3).
4. **AG-099** — adotar `K15` agora com valor provisório `ASSUMED`, ou
   aceitar o risco e adiar pro Estudo 2. **RESOLVIDO 2026-08-22** —
   ADIADO, confirmado (§4.3 do brief de decisões residuais).
5. **AG-099** — valor exato do encurtamento de `time_stop` (`TBD —
   medir`). **RESOLVIDO junto com o item 4** — adiado, fila de
   reativação registrada (fração horizonte-vs-barreira → semântica →
   contrafactual → valor), nada medido ainda.
6. **AG-100** (fora desta rodada de rascunho, ainda pendente) — R2/R3
   virar escopo de produção agora ou depois. **RESOLVIDO** — R2/R3
   wireado, backfill real rodado (5 símbolos), commitado e pushed
   (2026-08-22).
7. **AG-094** (idem, baixa urgência) — Meta-Label consome regime quando
   for implementado, e de qual resolução/candidato. **RESOLVIDO
   estruturalmente** — `ADR-001` §2.7: "de nenhum, por ora"; se um dia
   consumir, mesma linha/`method_id` do Alpha que filtra.

---

### 15.12 ADR-001 — Auditoria externa do contrato de dado (2026-08-20) — refuta parte do §15.11, resolve as 9 decisões pendentes

Contexto: os 2 briefs de auditoria externa citados no fechamento de
`§15.11`/`§11.6` (`docs/brief_auditoria_externa_2026-08-19_*.md`) voltaram
com um parecer completo — recebido nesta sessão como anexo, transcrito
como `docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md`. O
veredito central: **o loop adversarial interno (4 rodadas, `§15.11`)
funcionou pra achar furo lógico DENTRO do mecanismo escrito, mas tem um
ponto cego sistemático** — nenhum dos 5 achados internos atravessava uma
fronteira de SISTEMA (exchange↔motor, rótulo↔execução); os achados novos
da auditoria externa vêm todos de fora dessa fronteira (posição real da
Binance, política de execução declarada, granularidade de lote). É por
isso que 4 rodadas não os pegaram — não é raciocínio superficial, é
correlação de família de revisor.

**Status: `Ratificado` pelo Manager, 2026-08-20** ("ADR-001 Ratificado.").
O documento original marcava isso como decisão arquitetural major (toca
fonte-canônica, gates, SPEC) e sugeria um registro formal `D-###` via
`effective_challenge` — termo do próprio texto do parecer, não uma
convenção que já existisse neste projeto (`§6.5` deste plano é "Quando
escalar pra você", não um log de decisões numerado; não existe hoje
nenhuma entrada `D-001..D-NNN` em nenhum documento do repo). Registrado
aqui, sem inventar numeração nova: esta seção (`§15.12`) + os achados
`AG-108` a `AG-114` (ver abaixo) SÃO o registro de decisão — vinculante a
partir de 2026-08-20. Consequência prática da ratificação: os 4
invariantes (INV-A..D) e a arquitetura de lake local passam a ser a
direção oficial pra `src/io/artifact.py`/`schema.py` quando esse trabalho
começar; e a reescrita de `AG-096`/`AG-099` (itens `AG-108`/`AG-110`) deixa
de ser "acionável quando o Manager decidir" e passa a ser trabalho
pendente reconhecido, na fila atrás de `AG-109` (prioridade 1, ver Action
Items do ADR).

**Decisão de arquitetura de dados proposta:** lake local endereçado por
conteúdo, artefatos imutáveis, manifestos encadeados por hash
(`INV-A` chave canônica local a `bars.config_hash` · `INV-B` proveniência
por hash + escrita atômica via `_SUCCESS` · `INV-C` causalidade declarada
por coluna · `INV-D` paridade por classe `exact`/`tolerance`) — não DVC/
lakeFS (granularidade de linhagem é o arquivo, este projeto precisa de
granularidade de COLUNA), não convenção leve sem manifesto (é o estado
atual, e foi o que produziu os 10 gaps da Trilha B). Detalhe completo,
inclusive os 12 defeitos de engenharia que a própria proposta tinha e já
corrigiu inline (`V-01` a `V-12`): `docs/ADR-001_...md`.

**As 4 propostas de `§15.11` sob o veredito externo:**

| Proposta | Veredito | Rastreio |
|---|---|---|
| (A) Decision Engine no PBS | Sem controvérsia no mecanismo — mas faltavam os 4 contratos que tocam dinheiro (Meta→Decision→Risk→Execução→Ledger) | contratos propostos no ADR |
| (B) Gate por linha (`AG-096`) | **Refutado como especificado** — `(símbolo, resolução)` não é entidade de posição na Binance USDⓈ-M (One-way = 1 posição/símbolo/conta; Hedge = 2 buckets/símbolo, nunca por resolução) | `AG-108` |
| (C) Convenção de trials (`AG-098`) | **Errada nas 2 direções** — sobre-conta por correlação entre linhas (N efetivo da ordem de 2, não 15, dado ρ≈0,8) e mantém resíduo de circularidade (cardinalidade da rodada muda DSR de linha já promovida) | `AG-111` |
| (D) Gatilho de proteção (`AG-099`) | **Mesmo defeito da versão já refutada, deslocado** — encurtar `time_stop` ao vivo usa `p` treinado sobre horizonte 8h fixo pra decidir outro evento (quebra paridade treino-live no rótulo, não no preço) | `AG-110` |

**Achado mais severo de todo o ADR, anterior a (D) e a qualquer outra
decisão:** nenhuma versão do gatilho de proteção — nem a refutada
(apertar SL) nem a aprovada (encurtar horizonte) — tem saída executável
sob a política declarada (maker post-only GTX, cancela no timeout, nunca
converte a mercado). Isso não afeta só (D): afeta o **próprio SL do
triple-barrier** — os rótulos assumem `sl_px` como preço de saída, mas
sob GTX sem conversão a mercado, tocar `sl_px` só prova que o preço
atravessou o nível enquanto a ordem passiva ficava do lado errado. Toda a
geometria de payoff (TP=2,0×ATR/SL=1,5×ATR/8h) descreve uma estratégia
que a política de execução declarada não consegue executar como rotulada.
Registrado como `AG-109` — recomendação: admitir `reduceOnly` a mercado
só pra SAÍDAS (mantendo post-only pra entradas), ~3bps/perna de custo
adicional contra o risco de perda de cauda ilimitada por não sair.

**As 9 decisões antes pendentes (`§15.11` "Decisões abertas" + `§2.2`) —
todas com recomendação fundamentada agora, nenhuma decidida por este
registro (recomendação, não ratificação):**

| # | Decisão | Recomendação recebida |
|---|---|---|
| 1 | Cache-TTL vs. defasagem (rastreador de posição) | Nenhum dos dois — ledger local via push (`ACCOUNT_UPDATE`/`ORDER_TRADE_UPDATE`, fora do orçamento de rate-limit quente), REST só reconciliação, gate falha fechado (bloqueia entrada nova, nunca saída/kill-switch) |
| 2 | Valor do cap de posições concorrentes | 2 como backstop, mas controle vinculante é risco agregado (`Σ notional×stop_dist ≤ R_max×equity`), não contagem pura |
| 3 | Denominador do K01 | Equity total da conta, ancorada 00:00 UTC — atribuição por linha só como observabilidade |
| 4 | Adotar (D) agora ou adiar | Terceira via: relabelar condicional a regime primeiro (barato), shadow mode depois; resolver `AG-109` independente de tudo, é maior e anterior |
| 5 | Heurística de encurtamento de `time_stop` | Percentil empírico `p80(tempo até 1ª barreira \| regime, símbolo, resolução)`, medido só no fold de treino |
| 6 | Resoluções lentas agora ou só a rápida | Pré-filtro de custo primeiro (`AG-113`, grátis, 1 trial); gerar histórico de rótulo pra resolução MAIS LENTA também — é a que tem o pior hurdle, não a que tem menos prioridade |
| 7 | Meta consome regime, de qual candidato? | De nenhum por ora — Trilha A não deu evidência de poder condicional (18/18 p-valores nulos); como gate (não feature) não precisa de significância |
| 8 (`§2.2`) | Redundância entre ~92 features | Clustering hierárquico + cMDA por CLUSTER dentro do CPCV — rejeita "deixar pro L1/L2 do XGBoost" (árvores diluem por substituição, não eliminam) |
| 9 (`§2.2`) | Delegação de seleção muda contagem de trials? | Não elimina o viés, só move a busca pra dentro do modelo — precisa de busca aninhada nos folds + `N_eff` calculado (não contado) + PBO/CSCV como gate primário |

**Achados novos, sem precedente nas 3 investigações/4 rodadas internas
(fora da fronteira de sistema que o loop adversarial correlacionado não
alcançava):**

- **`AG-108`** — `(símbolo,resolução)` não é entidade de posição na
  exchange (N-01) — refuta `AG-096` como especificado.
- **`AG-109`** — saída executável ausente sob a política GTX declarada —
  atinge o SL do próprio triple-barrier. Severidade máxima do conjunto.
- **`AG-110`** — mecanismo revisado de `AG-099` repete o defeito de
  paridade treino-live da versão refutada, deslocado pro rótulo.
- **`AG-111`** — convenção de `AG-098` sobre-conta trials por correlação e
  mantém resíduo de circularidade.
- **`AG-112`** — granularidade de lote vs. capital: viés sistemático de
  seleção ~24× entre símbolos (BTC vs. SOL/XRP), grade discreta de ~3
  níveis em BTC quebra paridade treino-live no sizing.
- **`AG-113`** — `n_eff` invariante à resolução (~1.095/ano/linha,
  resolução não compra estatística); pré-filtro de custo grátis (1 trial
  pela própria convenção `AG-098`) pode eliminar metade do espaço de
  busca antes de qualquer backtest.

**O que isto NÃO faz:** não reabre nem invalida o histórico de `§15.11`
(as 4 rodadas internas, os 10 gaps originais `AG-094`-`AG-100`, o mandato
corrigido, a descontinuação do tiering de features) — esse trabalho segue
válido como registro do processo. O que muda é o VEREDITO sobre o
CONTEÚDO de 2 das 4 propostas que saíram desse processo, mais 6 achados
que o processo interno não tinha coberto. Consistente com o padrão já
observado em toda a Trilha B (`§15.11`, nota de abertura): cada rodada de
escrutínio, interna ou externa, achou algo real — nunca zero.

A transcrição completa do parecer (Partes I/II do ADR) foi persistida
no mesmo dia (`docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_
base.md`, ~1900 linhas) — deixou de ser "próximo passo". `AG-109` (citado
como premissa a resolver antes de `AG-108`) foi REFUTADO no mesmo dia
(`AG-115`, `§15.12.2` abaixo) — a decisão de sequenciamento entre os
dois deixou de se aplicar.

### 15.12.1 AG-114 — regra de decisão pra retomada do M4 (aprovada pelo Manager, 2026-08-20)

Consequência direta da ratificação do ADR-001 §2.7 (regime = gate, não
feature, na v1): o critério que o M4 usava pra medir os 6 candidatos
(heterogeneidade de RETORNO futuro) deixou de ser a pergunta que decide
promoção — regime não vai ocupar o papel de feature que esse teste
avaliava. `AG-114` (`audit/architecture_gaps_log.yaml`) registra o achado
completo; esta seção registra a REGRA aprovada, travada **antes** de
qualquer execução — precondição de `B20` (threshold nunca escolhido por
métrica OOS, sempre a priori), o mesmo motivo pelo qual `AG-098`/(C) teve
que ser corrigida quando a 1ª tentativa usava o resultado da rodada como
critério.

**Estrutura aprovada — 3 gates de desqualificação + 1 métrica primária de ranking:**

| # | Papel | Métrica | Limiar |
|---|---|---|---|
| Gate 1 | desqualifica | Occupancy / `effective_number_of_states` — estado de stress não pode ser degenerado (nem ausente, nem dominante) | `TBD — medir` contra o baseline em produção (B23, nunca inventado) |
| Gate 2 | desqualifica | Transition failure rate — candidato que oscila sem parar é inoperável, independente de separação | `TBD — medir` |
| Gate 3 | **desempate** (decidido, 2026-08-20) | Detection delay vs. eventos econômicos independentes | só entra em jogo se 2+ candidatos empatarem na métrica primária — não desqualifica sozinho |
| Métrica primária | ranking entre sobreviventes dos gates | Heterogeneidade de **volatilidade futura** entre buckets (Welch's F/ω², mesmo desenho já validado — permutação em bloco por episódio, correção de múltiplos testes já em uso no M4) | significância + tamanho de efeito decidem o rank |

**Regra completa e travada, 2026-08-20** — os 4 papéis (Gate 1/2/3 +
métrica primária) e a ordem de aplicação (gates primeiro, ranking depois,
desempate por último) estão fixados. **O que fica aberto, explicitamente:**
só os valores numéricos dos 2 limiares dos Gates 1/2 (`TBD` até medição
real) — e isso é deliberado, não pendência esquecida: fixar um número
antes de medir seria a mesma estipulação que `B23` proíbe. Nada do que
falta pode ser decidido depois de ver o resultado das 4 métricas nos 6
candidatos — isso reintroduziria exatamente o viés que a ordem "regra
antes do dado" existe pra evitar.

**Próximo passo:** planejar a extensão de M4 que mede as 4 métricas
(occupancy, transition failure rate, detection delay, separação de
volatilidade futura) nas mesmas 5 janelas críticas × 3 resoluções já
usadas (reusa `m4_critical_windows.py`, sem redesenho) — só depois de
medir, preencher os limiares TBD com o valor real e aplicar a regra já
travada, que nesse ponto vira aritmética, não escolha.

### 15.12.2 Auditoria do desenho técnico de labels — ADR-001 vs. PRD real (2026-08-20)

Pedido do Manager: auditar como está o desenho técnico de labels em
ADR-001 vs. `PLANO_MESTRE_PRINCE2.md`. Verificação direta contra
`PRD_V3_2_UNIFICADO.md` §9.1 e `src/labels/triple_barrier.py` (código
real da Label Engine) achou 1 correção importante e 1 tensão de desenho
genuína, nenhuma das duas presumida — as duas registradas em
`audit/architecture_gaps_log.yaml`.

**`AG-115` — `AG-109` REFUTADO.** O achado de maior severidade de todo o
parecer do ADR-001 ("nenhuma versão do gatilho de proteção tem saída
executável... afeta o STOP-LOSS do próprio triple-barrier") não se
sustenta. A política de execução real (`PRD_V3_2_UNIFICADO.md` §9.1,
linhas 1700-1727) é ASSIMÉTRICA por desenho, não uniformemente
post-only: só a ENTRADA é `LIMIT/GTX/on_timeout=CANCEL`. O STOP-LOSS é
`STOP_MARKET/MARK_PRICE/reduce_only` (ordem condicional nativa,
execução GARANTIDA — taker — uma vez disparada). O TIME_STOP é `MARKET
reduce_only` explícito (também garantido). Só o TAKE_PROFIT é
maker/pode-não-encher — e se não encher, a posição sai via TIME_STOP, que
é garantido. `src/labels/triple_barrier.py` (comentário 8 do módulo) já
implementa essa assimetria de custo em produção — não é proposta nova, é
desenho já vigente desde antes do parecer existir. Economia já
quantificada no PRD: "Execução maker assimétrica... breakeven 53,4% →
48,1%" (§0.3/linha 3369/3450). O auditor externo não tinha acesso ao
repositório (nota de escopo do próprio ADR-001) e generalizou a política
de ENTRADA pra toda a política de execução, incluindo saídas — erro de
leitura, não achado real. **Consequência prática:** `src/exchange/
adapter.py::place_order` continua `NotImplementedError` — nenhum código
de execução real existe ainda —, mas o trabalho que falta é IMPLEMENTAR
uma decisão já tomada, não decidir algo novo. O passo "Resolver AG-109
antes de qualquer outra coisa" no Road Map Vivo v2 e a citação de AG-109
como prioridade 1 em `§15.12` (achados/ação recomendada do ADR-001, texto
acima) ficam desatualizados por esta correção — Road Map Vivo atualizado
na mesma sessão (ver rodapé).

**`AG-116` — tensão real, não decidida: `horizon_bars` (ADR-001) vs.
`time_stop_ms` (`AG-031`, já em produção).** ADR-001 recomenda
`horizon_bars` (contagem de barra da resolução) como campo canônico da
barreira vertical — "barreira vertical em milissegundos sobre relógio de
dollar bar é erro de unidade" (§3.1/§4.3). Verificado: `horizon_end_ms =
t0 + cfg.time_stop_ms` (`triple_barrier.py:1000`) é INCONDICIONAL, roda
igual sob `tf` (calendário) e sob `resolution_id` (dollar-bar, `AG-042`).
**Isto não é omissão** — é decisão deliberada, registrada 3x em
`PRD_V4_1.md` (§2.7 I2/§3.2 M1/§4.2, "horizonte em relógio fixo") e
formalizada em `AG-031`/B1, provavelmente motivada pelo alinhamento com o
ciclo de funding de 8h da Binance (conceito de relógio, não de
informação/volume) — razão plausível, não confirmada por citação direta
nesta auditoria. `AG-031` é anterior tanto ao paradigma dollar-bar
(`AG-042`) quanto ao parecer do ADR-001 — nunca foi revisitado à luz de
nenhum dos dois. **Decisão pendente do Manager, registrada sem
inclinação:** (a) manter relógio fixo, com a justificativa de funding
tornada explícita (hoje é inferência desta auditoria, não citação
documentada); ou (b) migrar pra `horizon_bars` só sob `resolution_id`,
preservando `time_stop_ms` sob `tf` — os 2 modos já coexistem via XOR no
mesmo `LabelConfig`, então (b) não exige escolher 1 filosofia pros 2
mundos.

**Atualização 2026-08-20 — Manager autorizou a opção (b) ("horizon_bars
Autorizado") e pediu mapeamento + pesquisa de literatura ANTES de
aplicar, sem codar ainda.** Os 2 levantamentos completos (plano de
migração técnico + pesquisa de literatura pras 2 ambiguidades que
sobraram do mapeamento) ficam registrados em `§15.12.3` — nenhum código
foi escrito, isto é só o material que a implementação futura vai
consumir.

### 15.12.3 AG-116 — plano de migração completo + pesquisa de literatura (2026-08-20)

**Escopo confirmado com o Manager:** opção (b) — `horizon_bars` só sob
`resolution_id` (dollar-bar), `time_stop_ms` preservado sob `tf`
(calendário), sem forçar 1 filosofia única pros 2 modos.

#### A. Plano de migração técnico (mapeamento por leitura integral de `triple_barrier.py`, sem editar nada)

**Achado prévio relevante:** o texto integral do ADR-001 que `AG-116`
cita ("§3.1 cláusula 1"/"§4.3") **não está persistido no repo** —
`docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md` é um
resumo condensado, e o próprio arquivo declara (`Action item 2`) que o
corpo completo (Partes I/II, ~2000 linhas) ainda não foi transcrito.
A recomendação de `horizon_bars` só existe hoje via paráfrase — não
bloqueia o mapeamento (a direção já foi decidida pelo Manager), mas é
lacuna de rastreabilidade a considerar quando o ADR-001 completo for
transcrito.

**1. Campo novo em `LabelConfig`:** `horizon_bars: int | None = None`,
último campo do dataclass (default `None` preserva os ~15 callers
posicionais existentes). Validação em `__post_init__`, acoplada ao XOR
`tf`/`resolution_id` já existente (mesma disciplina de `estimator_id`
sob `resolution_id`): `resolution_id is not None` exige
`horizon_bars >= 1` explícito (`ValueError` caso contrário); e
`horizon_bars is not None` sob `tf` (sem `resolution_id`) também levanta
`ValueError` — proibição ativa, não ignorar em silêncio (mesma classe de
bug que `AG-031` corrigiu para `time_stop_bars`/`time_stop_ms`; é
escolha de estilo, não necessidade lógica — confirmar com o Manager se é
fricção desnecessária). `from_constants()` ganha parâmetro espelhando
`estimator_id`, com default carregável de `constants.yaml` quando
`resolution_id` setado sem `horizon_bars` explícito.

**2. `build_labels` (~linha 1000) — troca do cálculo de `horizon_end_ms`:**
```python
if cfg.resolution_id is not None:
    horizon_idx = i + cfg.horizon_bars
    if horizon_idx >= n:
        n_incomplete_tail += 1
        continue
    horizon_end_ms = int(t0_arr[horizon_idx])
else:
    horizon_end_ms = t0 + cfg.time_stop_ms  # AG-031/B1, inalterado
```
`n_bars_held` (linhas 1041-1082) **não precisa mudar** — já é
bar-count-aware desde `AG-031`/B1 e recupera `n_bars_held == horizon_bars`
por busca posicional sem branch novo.

**Consequência em cascata não trivial — prefetch de `mark_1m`/`funding`/
`bars_15m` em `build_labels_for_symbol` (~linha 1258):** hoje
`horizon_ms = max(cfg.time_stop_ms, cfg.fill_timeout_ms)` dimensiona a
folga de prefetch — sob `resolution_id`, `cfg.time_stop_ms` fica
vestigial, e usá-lo pra dimensionar a folga é arbitrário/potencialmente
incorreto (dollar bar em baixa atividade pode levar muito mais wall-clock
que `horizon_bars` barras cobririam sob alta atividade). Ver seção C
abaixo (pesquisa de literatura, Pergunta 2) pra abordagens.

**3. `config_hash` — precisa incluir `horizon_bars`** (confirmado por
leitura da property, linhas 379-426; mesmo padrão dos 3 precedentes já
documentados: `AG-005`, `AG-031`/B1, `AG-042`).

**4. `assert_label_invariants` (linha 456) — teto físico hoje é em ms
(`held_ms <= time_stop_ms`), precisa virar XOR com `horizon_bars` (teto
correto sob `resolution_id` é `n_bars_held <= horizon_bars`, coluna já
existe). Call site que muda: `src/labels/backfill_multi_symbol.py:136`
(hoje incondicional, precisa virar condicional em `cfg.resolution_id`).

**5. `experiment_log.py`** — schema (`_SCHEMA`) precisa de coluna
`horizon_bars: pl.Int32` nova (mesmo padrão diagonal-concat já usado
pra `time_stop_bars→time_stop_ms`), e o helper que grava linha de config
precisa gravar o campo.

**6. Pontos que NÃO precisam mudar (confirmado por leitura, fora de
escopo):** `barrier_sweep.py`/`cost_surface.py`/`faixa2_caminho_b.py`
(não suportam `resolution_id`, declaração própria); `m2_worker.py`/
`m2_bar_comparison.py`/`m2_stats.py` (conceito próprio de `time_stop_ms`,
deliberadamente fixo entre bar types pra comparação M2, não usa
`LabelConfig`).

**7. Testes afetados** — `tests/unit/test_labels_triple_barrier.py`:
`_dollar_bar_cfg()` (helper usado por 5+ testes) precisa de
`horizon_bars=` novo; 3 testes novos necessários (barreira TIME sob
`resolution_id` cai exatamente em `horizon_bars` índices à frente;
proibição de `horizon_bars` sob `tf`; teto de `n_bars_held` em
`assert_label_invariants`). `test_labels_backfill_multi_symbol.py:203`
só quebra se `from_constants` não tiver default carregável (motivo a
mais pra preferir default carregável). Golden tests (`test_features_
volatility.py`, `test_sprint8_reproducibility.py`) — confirmado
intocados, operam em universo `tf`/`resolution_id=None`.

**8. Artefato já persistido que a migração invalida:**
`data/labels/{BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT}/R1/v1/labels.parquet`
— gerados sob `time_stop_ms` incondicional atual. Reprocessar muda o
VALOR econômico de `t1`/`ret_net`/`n_bars_held`/`barrier_hit` em toda
linha onde a barreira TIME foi tocada, não só o `config_hash`.
Downstream real (não hipotético): `src/models/dataset.py`, o próprio M4/
M6 em andamento (`m4_critical_windows.py`/`m4_regime_comparison.py`/
`m6_common_factor_hypothesis.py`), `src/validation/leakage.py`/`cpcv.py`,
`src/backtest/fill_reconciliation.py`. **Recomendação: não reprocessar
`labels/R1/v1/` até o M4/M6 em andamento fechar**, ou coordenar
explicitamente antes.

**9. Ambiguidades reais que sobraram do mapeamento técnico puro** — as 2
que motivaram a pesquisa de literatura da seção C, mais 2 menores de
estilo (não bloqueiam decisão): (i) horizonte compartilhado entre
R1/R2/R3 vs. por resolução; (ii) dimensionamento de prefetch sem teto a
priori; (iii) proibir `horizon_bars` sob `tf` — fail-loud, ou ignorar em
silêncio?; (iv) `from_constants(resolution_id=..., horizon_bars=None)`
carrega default de `constants.yaml`, ou exige explícito como
`estimator_id`? Recomendação do mapeamento original: default carregável
(risco menor — `horizon_bars` é hiperparâmetro puro, não risco de
"mentir sobre qual estimador rodou" que motiva a exigência em
`estimator_id`).

**10. Ordem sugerida de implementação (não implementado, só ordem):**
decidir (i)/(ii) [seção C] → `LabelConfig` (campo+validação+
`from_constants`+`config_hash`) → `build_labels` (horizonte por índice)
→ implementar (ii) em `build_labels_for_symbol` → `assert_label_
invariants`+call site → `experiment_log.py` schema → testes (item 7) →
decidir se/quando reprocessar `labels/R1/v1/` (item 8, coordenar com
M4/M6) → só então fechar `AG-116` com `resolved_by_commit`.

#### B. Entrada real em `config/constants.yaml` (proposta abaixo já
decidida e implementada — `horizon_bars.value: 32`, `provenance: DERIVED`,
ver a entrada real do arquivo pro `source` completo)

#### C. Pesquisa de literatura (agente dedicado, ≥12 fontes/pergunta, 2026-08-20)

**C.1 — `horizon_bars` compartilhado entre R1/R2/R3, ou calibrado por resolução?**

*O que a literatura diz:* López de Prado, "Advances in Financial Machine
Learning" (2018), capítulo "Labeling"/"The Triple-Barrier Method",
trata o horizonte NATIVAMENTE em contagem de barra (citação via 2
reproduções secundárias convergentes — RiskLab AI e QuantStrategy.io;
PDF primário bloqueado por acesso, 403/limite de tamanho — sinalizado
como limitação da pesquisa, não fato verificado em 1ª mão). Tensão
interna não resolvida no próprio ecossistema AFML: o Snippet 3.4 do
livro ("Adding a Vertical Barrier"), reproduzido por 2 portes de código
independentes (`mlfinlab`/Hudson & Thames, `BlackArbsCEO/Adv_Fin_
ML_Exercises`), implementa o horizonte em TEMPO DE RELÓGIO
(`pd.Timedelta`) mesmo operando sobre séries de dollar bars — o livro
nunca reconcilia isso. O método "Trend-Scanning" do mesmo autor
(lecture notes AFML 3/10, `mlfinlab`) define a janela de look-forward
`L` diretamente em número de barras — reforça, por 2ª via metodológica
independente, a preferência conceitual do autor por horizonte
bar-count. Fundamento estatístico de fundo (não sobre múltiplas
resoluções): Mandelbrot (1967), Ané & Geman ("Order flow, transaction
clock and normality of asset returns", *Journal of Finance*, 2000),
Easley/López de Prado/O'Hara ("The Volume Clock", *Journal of Portfolio
Management*, 2012) — retornos em tempo de atividade/informação se
aproximam mais de i.i.d. Gaussiano que em tempo de relógio, justificando
medir grandezas econômicas (inclusive horizontes) em unidades de
informação. **Nenhuma fonte localizada trata múltiplas resoluções/
thresholds simultâneas do mesmo instrumento** — o cenário deste projeto
(R1/R2/R3 coexistindo) não aparece na literatura pesquisada. **Nenhuma
fonte cruza bars de informação com custos periódicos de carrego
(funding de perpétuo)** — busca multi-ângulo confirmada (volume clock +
funding; business-time + carry cost; perpetual + event-time), gap
genuíno, esperado (literaturas de gerações/domínios diferentes que ainda
não se cruzaram). Perpetual futures pricing (Ackerer/Hugonnier/Jermann,
*Mathematical Finance*, 2026; arXiv:2212.06888) confirma funding como
mecanismo em RELÓGIO (8h, path-dependent), intrínseco ao instrumento —
não à forma de amostragem rio abaixo.

*Recomendação do agente (não é citação, é leitura dele sobre o caso
deste projeto especificamente):* `threshold_usdt` de cada resolução já
é calibrado (`AG-042`) pra que a contagem MÉDIA de barras aproxime
15m/30m/1h — ou seja, já existe vínculo MEDIDO (não estipulado) entre
bar-count e relógio, na média da população. Um `horizon_bars`
COMPARTILHADO entre R1/R2/R3 não abre mão de comparabilidade de relógio
tanto quanto pareceria à primeira vista, porque o horizonte de relógio
esperado já deveria sair aproximadamente proporcional entre resoluções
como subproduto da própria calibração de `AG-042`. Combinado com a
preferência conceitual convergente do autor-fonte E o fato de que
`time_stop_ms` continua disponível sob `tf` pra quem quiser preservar
alinhamento a funding explicitamente (XOR já existente, migrar
`resolution_id` não remove essa opção) — a leitura do agente pende para
(a) `horizon_bars` compartilhado. **Mas isso não deveria ser aceito por
dedução** — é afirmação empírica testável com dado que o projeto já tem:
medir (B23) a distribuição REALIZADA de duração-em-relógio de
`horizon_bars=N` por resolução, post-hoc, sobre o histórico de dollar
bars já calculado. Se a proporcionalidade esperada por `AG-042` se
confirmar, evidência a favor de (a); se divergir materialmente,
evidência a favor de (b) — decisão final sai da medição direta, não da
literatura sozinha.

**C.2 — dimensionamento de prefetch sem teto a priori**

*O que a literatura diz:* literatura financeira/quant específica
**não existe** para este problema — motivo estrutural: todo tratamento
publicado de dollar/volume/tick bars localizado (AFML, `mlfinlab`,
NautilusTrader) opera em regime BATCH/offline (série de barras inteira
já materializada a partir de fita de ticks histórica completa) — o
problema "não sei quanto relógio N barras futuras vão cobrir" só existe
em contexto incremental/produção, fora de onde essa literatura opera.
Confirmado por busca multi-ângulo, gap genuíno e esperado. Literatura
GERAL de engenharia de dados/streaming oferece 3 padrões estabelecidos
diretamente transferíveis: (1) *guess-and-double* — estimativa de teto
inicial, dobra ao ultrapassar, poucas correções logarítmicas até
convergir; (2) *watermarks/allowed lateness* — Akidau et al., "The
Dataflow Model" (VLDB 2015, paper fundacional do Google Cloud Dataflow/
Apache Beam), Begoli et al., "Watermarks in Stream Processing Systems"
(VLDB 2021, compara Flink/Dataflow) — limite tolerado de atraso
declarado, estado aberto por essa janela, dado além do limite descartado
ou desviado EXPLICITAMENTE (nunca truncamento silencioso); (3)
*estimativa conservadora via percentil alto* (p99/p99.9 + margem, não
média/mediana) da distribuição histórica medida de "tempo pra acumular N
eventos" — padrão comum de ETL, sem framework específico associado.

*Recomendação do agente:* para o estágio atual (pipeline de pesquisa/
backtest, não produção ao vivo) — abordagem (3): medir, sobre o
histórico de dollar bars já calculado, a distribuição de "ms decorridos
para `horizon_bars` barras consecutivas" por R1/R2/R3, usar percentil
alto + margem como folga fixa, virar constante `MEASURED` em
`constants.yaml` (não estipulada) — com fallback explícito
(NOFILL/não-resolvível, mesmo espírito do pipeline de labels já
existente) para os casos de cauda que ultrapassarem o teto, nunca
truncamento silencioso. Padrão (2)/watermark-style vale manter em mente
para quando a execução AO VIVO for construída (`uv run quant live run`)
— nesse momento a pergunta muda de natureza (o futuro deixa de existir
de fato, não é só "desconhecido a priori mas já gravado em disco") —,
mas é provavelmente over-engineering para o estágio atual (Feature/
Regime Engine hoje é recomputado on-the-fly a cada chamada, não persiste
em lote incremental, per `CLAUDE.md`).

**Status:** decisão final de C.1/C.2 continua com o Manager — pesquisa
completa, sem citação forçada onde a literatura é omissa (declarado
explicitamente nos 2 gaps centrais: multi-resolução simultânea em C.1,
prefetch incremental específico de bars em C.2). Nenhum código escrito.

**Atualização 2026-08-20 (mesmo dia) — DECIDIDO e IMPLEMENTADO.** C.1:
compartilhado entre R1/R2/R3 (`horizon_bars=32`, DERIVED, mesmo padrão de
`time_stop_ms`). C.2: percentil alto MEDIDO, não estipulado
(`label_prefetch_p99_bar_duration_ms=22.506.187ms`, medido sobre as 15
combinações símbolo×resolução reais, `experiments/dollar_bar_duration_
p99_by_resolution.json`). Ponta a ponta em `src/labels/triple_barrier.py`
(+ `backfill_multi_symbol.py`/`experiment_log.py`), suíte completa
validada (1508 passed). Ver `AG-116` (`audit/architecture_gaps_log.yaml`,
status fechado) pro registro completo.

---

### 15.12.4 AG-118 — Gate efficiency: desenho e implementação inicial (2026-08-20; ver §15.13/§15.19 pra evolução/resolução final — RESOLVIDO 2026-08-21, lift≈1,0 em 90 células, ver ledger AG-118)

**Origem:** pergunta do Manager, 2026-08-20 — "como Alpha/Meta vão ler/ver
o regime, mantendo Alpha/Meta responsável pela seleção de oportunidades?
Isso combina com o triple_barrier: `P(stop|regime)`, `P(target|regime)`,
`E[return|regime]`, `tail_loss|regime`, `holding_time|regime`, e
principalmente se o gate remove uma parte desproporcional dos eventos
ruins sem destruir demasiadamente os bons." Duas perguntas de escopo
levantadas antes de desenhar: (1) o ADR-001 já trata isso? (2) como isso
concilia os 2 itens já registrados como abertos (`AG-094`/Trilha B item
7, e o valor do encurtamento de `time_stop` de `AG-099`)?

#### A. O ADR-001 trata isso? — Não, confirmado por busca direta no texto

Grep no corpo persistido (`docs/ADR-001_arquitetura_artefatos_e_
contratos_2026-08-19.md`) por `tail_loss`/`CVaR`/`holding_time`/`p80`:
**1 único resultado** — recomendação #5 das 9 decisões pendentes:

> "Heurística de partida pro encurtamento de `time_stop`: Percentil
> empírico `p80(tempo até 1ª barreira | regime, símbolo, resolução)`,
> medido só no fold de treino — não número de relógio."

Ou seja: o ADR-001 propõe `holding_time | regime` **só** como heurística
pontual pro valor de um parâmetro específico (`AG-099`), nunca como um
framework de avaliação do gate como um todo. `P(stop|regime)`,
`P(target|regime)`, `E[return|regime]`, `tail_loss|regime` e a métrica de
"remoção assimétrica" **não aparecem em lugar nenhum do ADR-001** — não é
lacuna de leitura, é lacuna real do parecer. Este desenho preenche essa
lacuna.

#### B. O que já existe no código (reuso, não reinvenção)

`StratumMetrics`/`m6.stratum_metrics` (`src/analysis/m6_common_factor_
hypothesis.py:92-189`), já em produção desde antes desta sessão (bloco
`heterogeneity`, G-C1-2, `m4_critical_windows.py`), **já computa 3 das 5
métricas pedidas**, por `(symbol, side, regime)`:

| Métrica pedida | Já existe? | Campo real |
|---|---|---|
| `P(target\|regime)` | ✅ sim | `StratumMetrics.frac_tp` |
| `P(stop\|regime)` | ✅ sim | `StratumMetrics.frac_sl` |
| `E[return\|regime]` | ✅ sim (normalizado por ATR) | `StratumMetrics.edge_bruto_atr` |
| `tail_loss\|regime` | ❌ não | — |
| `holding_time\|regime` | ❌ não | — |
| remoção assimétrica (recall de eventos ruins vs. custo de eventos bons) | ❌ não | — |

O join causal que alimenta tudo isso (`_asof_join_regime_onto_labels`,
`m4_critical_windows.py:1088-1122`) já existe, já é causal (as-of
BACKWARD por `close_time_ms`, corrigido `AG-090`), e já é reusado sem
duplicação pelo bloco `heterogeneity`. Este desenho REUSA o mesmo join —
não cria pipeline de dado novo, só novas estatísticas sobre o resultado
dele.

#### C. Desenho técnico — 2 peças novas, nenhuma implementada ainda

**C.1 — Extensão das 2 métricas que faltam.** Novo dataclass,
`GateEfficiencySymbolDetail` (não estende `StratumMetrics` diretamente —
`StratumMetrics` é compartilhado com `m6_common_factor_hypothesis.py`
pra uma pergunta diferente, criar campo novo lá arriscaria escopo
alheio; melhor um dataclass irmão, mesma fonte de dado, propósito
próprio):

```python
@dataclass(frozen=True, slots=True)
class GateEfficiencySymbolDetail:
    """Por (symbol, side, bucket) -- reusa _asof_join_regime_onto_labels,
    zero pipeline novo. Mede se o candidato VENCEDOR do AG-114 é útil
    como GATE de risco pro triple-barrier real -- pergunta diferente de
    AG-114 (que mede se o candidato TEM estrutura suficiente pra ser um
    bom detector, antes de qualquer geometria de trade)."""
    symbol: str
    side: int
    bucket: int              # canonical_id
    is_stress_bucket: bool   # via identify_stress_state_by_volatility (AG-114, já travado)
    n: int
    p_target: float          # = frac_tp (StratumMetrics, reexposto -- não recalculado)
    p_stop: float             # = frac_sl
    e_return_atr: float       # = edge_bruto_atr
    p05_return_atr: float     # NOVO -- tail loss, percentil 5 de ret_net/atr_at_t0
    median_holding_bars: float  # NOVO -- mediana de n_bars_held
    p80_holding_bars: float     # NOVO -- p80 de n_bars_held (ADR-001 rec#5, AG-099)
```

**C.2 — A métrica de "remoção assimétrica" (peça genuinamente nova,
formalização da pergunta do Manager):**

```python
@dataclass(frozen=True, slots=True)
class GateEfficiencyResult:
    """P(bucket=stress | desfecho) -- não P(desfecho | bucket) --
    pergunta invertida de propósito: mede o que o GATE faria (bloquear
    entradas em bucket=stress) em termos do que isso captura/descarta."""
    symbol: str
    side: int
    bad_event_capture_rate: float   # P(bucket=stress | barrier_hit=SL) -- recall dos eventos ruins
    good_event_cost_rate: float     # P(bucket=stress | barrier_hit=TP) -- custo em eventos bons
    lift: float                     # bad_event_capture_rate / good_event_cost_rate
    n_sl_total: int
    n_tp_total: int
```

`lift > 1` = o gate captura proporcionalmente mais eventos ruins do que
bons (útil); `lift <= 1` = o gate não discrimina ou é contraproducente
(bloqueia tanto ou mais bons quanto ruins). **Nenhum limiar de "lift
mínimo pra valer a pena" é fixado aqui** — mesma disciplina de `B23`/
`AG-114`: `TBD — medir`, decidido só depois da medição real, nunca
antes.

#### D. Sequenciamento — Fase 2 do funil, não um gate concorrente

```
FASE 1 (AG-114, já travada)          FASE 2 (este desenho, AG-118)
────────────────────────────         ──────────────────────────────
"Este candidato TEM estrutura        "O candidato VENCEDOR é útil
 suficiente pra ser um bom            como GATE econômico pro
 detector de regime?"                 triple-barrier real, e que
 Gates 1/2/3 + heterogeneidade         parâmetro isso implica pro
 de volatilidade futura                Risk/Decision Engine?"
        │                                      │
        ▼                                      ▼
  escolhe 1 candidato/resolução  ──────►  GateEfficiencySymbolDetail +
  (estrutura, abstrato)                   GateEfficiencyResult
                                           (economia real, concreto)
```

Roda **só** sobre o candidato que já passou pelos 3 gates do `AG-114` —
não é um 4º gate concorrente disputando o mesmo veredito, é a pergunta
seguinte, feita só depois que a primeira já tem resposta. Reusa
`_asof_join_regime_onto_labels` + o join já existente pro `heterogeneity`
— custo incremental é só as estatísticas novas sobre um join que já
acontece, não uma rodada de fit adicional.

#### E. Reconciliação — os 2 itens abertos, ambos resolvidos por este desenho

**`AG-094` / Trilha B §15.11, "Decisões abertas" item 7** — *"Meta-Label
consome regime quando for implementado, e de qual resolução/candidato?"*
**Resposta na época (2026-08-20): Meta consumiria de NENHUM candidato**
(ADR-001 recomendação #7, regime como gate, não feature). **[REVERTIDO
2026-08-22]** Manager revogou esta posição — regime passou a entrar como
FEATURE do Meta (one-hot, nunca ordinal), com REVERSÃO EXPLÍCITA da
resolução que `AG-118` havia antecipado (`audit/architecture_gaps_log.
yaml::AG-094` addendum). Ver `§15.19` pro desenho vigente — não tratar a
resposta original acima como decisão corrente.

**`AG-099`, "valor exato do encurtamento de `time_stop`"** — resolvido
diretamente por `GateEfficiencySymbolDetail.p80_holding_bars` sob
`bucket=stress`, exatamente a heurística que o ADR-001 recomendação #5
já propunha (`p80(holding_time | regime, símbolo, resolução)`, medido só
no fold de treino) — este desenho é a infraestrutura concreta que faltava
pra essa recomendação deixar de ser só uma frase e virar número real.

#### F. O que este desenho explicitamente NÃO decide (B23/B20)

- Nenhum valor de `lift` mínimo pra promover o gate a produção.
- Nenhum valor de `p80_holding_bars` — só a fórmula/fonte de onde ele
  viria (join causal real, fold de treino), nunca um número aqui.
- Não decide COMO o Risk/Decision Engine efetivamente consome o sinal
  (bloqueia entrada nova? reduz nocional? só o encurtamento de
  `time_stop` de `AG-099`?) — isso é implementação, fase posterior,
  depois que os números de `GateEfficiencyResult` existirem de verdade.
- Não implementado nem testado ainda — este é o passo de travar a
  estrutura, mesmo protocolo de `AG-114`/`B20`: desenho primeiro, código
  depois, número por último.

**Status:** desenho travado, aguardando autorização do Manager pra
implementar (`GateEfficiencySymbolDetail`/`GateEfficiencyResult` +
testes, mesmo padrão de rigor de `AG-114`/`AG-116`) — roda depois que o
`AG-114` tiver um candidato vencedor real (esta fase consome o
resultado da Fase 1, não pode rodar antes dela).

**Atualização 2026-08-20 (mesmo dia) — IMPLEMENTADO.** Manager autorizou
via `redesign_workflow` ("implemente AG-118... usando
hmm_gaussian_k4_v1"). Novo módulo `src/analysis/gate_efficiency.py` —
os 2 dataclasses exatamente como travados acima. Verificação prévia
contra o ADR-001 COMPLETO (não o resumo de 222 linhas — o Manager colou
o parecer original, ~1900 linhas, `docs/ADR-001_..._base.md`) confirmou
3 pontos: (1) o contrato `regime()` de ADR-001 §3.4 já reserva um campo
`tradeable: Boolean` pra exatamente este papel — este módulo produz a
EVIDÊNCIA (`lift`), não o campo formal (que espera `src/io/artifact.py`,
ainda não construído); (2) este módulo NÃO é bloqueado pela ordem de
implementação do ADR-001 (é análise pós-hoc, `src/analysis/`, nunca
artefato de produção consumido a jusante); (3) `decode_mode=filter`
(causal) de `hmm_gaussian_k4_v1` confirmado no código real, não
assumido. Achado colateral registrado como `AG-121` (não bloqueante):
divergência real entre a recomendação de canonicalização por
volatilidade do ADR-001 e a implementação real por retorno
(`PRD_V4_1.md` §3.2) — este módulo evita o problema por construção.
Custo zero fits novos (lê `RawLabels` já persistidos pela rodada real
do `AG-114`). Detalhe completo, incluindo as 2 constantes novas
(`gate_efficiency_tail_loss_percentile`/`gate_efficiency_holding_time_
percentile`) e os 12 testes: `AG-118` (adendo de implementação),
`audit/architecture_gaps_log.yaml`.

### 15.12.5 AG-114 — aplicação da regra sobre o resultado real da extensão de M4 (2026-08-20, candidato vencedor declarado)

**Insumo:** `experiments/m4_critical_windows_report.json` (rodada real
concluída 2026-08-20, 10.891,9s, `run_and_save_critical_windows_report`
com `compute_gate_quality=True`) — 0 células falhas em R1/R3, **1 célula
falha em R2** (`BNBUSDT`/`RECENTE`, isolada por `AG-019`, não afeta o
agregado — ver `AG-120` abaixo, achado novo desta auditoria). Números
abaixo são extraídos DIRETO do JSON persistido (script de extração
`orjson`, não lidos de memória de sessão anterior nem recalculados à
mão) — reproduzíveis por qualquer pessoa com acesso ao arquivo.

#### A. Números medidos — as 4 métricas da regra `AG-114`, medianas por resolução

| resolução | classificador | eff\_n\_states | stress\_occ | tfr\_n5 | i²(%) | p\_perm |
|---|---|---:|---:|---:|---:|---:|
| R1 | `quantile_regime_v1` (baseline) | 4,26 | 2,8% | 0,150 | 94,7 | 0,001 |
| R1 | `hmm_gaussian_k2_v1` | 1,90 | **34,1%** | 0,196 | 97,8 | 0,001 |
| R1 | `hmm_gaussian_k3_v1` | 2,77 | 18,3% | 0,177 | 97,4 | 0,001 |
| R1 | `hmm_gaussian_k4_v1` | 3,44 | 12,7% | 0,224 | 97,4 | 0,001 |
| R1 | `bocpd_v1` | 2,88 | 23,7% | **0,529** | 84,1 | 0,085 |
| R2 | `quantile_regime_v1` | 4,12 | 3,2% | 0,162 | 91,6 | 0,002 |
| R2 | `hmm_gaussian_k2_v1` | 1,91 | **34,9%** | 0,162 | 95,3 | 0,001 |
| R2 | `hmm_gaussian_k3_v1` | 2,77 | 18,4% | 0,210 | 94,5 | 0,001 |
| R2 | `hmm_gaussian_k4_v1` | 3,62 | 11,1% | 0,224 | 95,0 | 0,001 |
| R2 | `bocpd_v1` | 2,83 | 29,7% | **0,557** | 80,0 | 0,188 |
| R3 | `quantile_regime_v1` | 4,03 | 3,1% | 0,171 | 83,4 | 0,075 |
| R3 | `hmm_gaussian_k2_v1` | 1,96 | **39,5%** | 0,219 | 91,7 | 0,007 |
| R3 | `hmm_gaussian_k3_v1` | 2,79 | 21,5% | 0,195 | 85,7 | 0,005 |
| R3 | `hmm_gaussian_k4_v1` | 3,44 | 10,5% | 0,228 | 91,8 | 0,003 |
| R3 | `bocpd_v1` | 2,70 | 28,8% | **0,472** | 52,0 | 0,341 |

`jump_model_cjm_v1` omitido desta tabela por decisão já registrada
(`AG-117`, `jump_model_excluded_from_ranking_caveat` no próprio JSON) —
BTC-only, composição de amostra não comparável aos outros 5 candidatos.
Confirmação adicional nesta auditoria: `eff_n_states` de 1,17-1,39 (quase
1 estado único) e `occupancy` variando de 1,0 (CRYPTO_WINTER, totalmente
degenerado) a 0,04-0,56 (as outras 4 janelas) — instável demais pra ser
lido como candidato nesta configuração, INDEPENDENTE da exclusão por
BTC-only. Isso é sobre a config ANTIGA (2 features, K=2) — substituída
pelo trabalho de `AG-119`/"Condição C", **concluído no mesmo dia desta
auditoria**: rodada real (4D+K=3+λ=0,02) confirma validade ESTRUTURAL
pra SOLUSDT/XRPUSDT (saturação 0% nas 3 resoluções) e majoritariamente
BNBUSDT, mas **não muda o veredito de vencedor** — utilidade como gate
continua sem demonstração, `n_episodes` por célula fica 1-8 (vs. 37-622
do baseline nas mesmas células), mesmo problema de poder estatístico da
execução original do M4, agora por regularização alta (`λ=0,02`
produz poucos episódios muito longos) em vez de saturação/
degenerescência. `i²` fica 0,0% pra SOL/BNB/XRP nas 3 resoluções.
Detalhe completo: `AG-119` (adendo final).

**Achado colateral, não hipotético:** a métrica primária (heterogeneidade
de volatilidade) do PRÓPRIO baseline deixa de ser significativa a 5% em
R3 (p=0,075) — os 3 HMM continuam significativos em R3 (p=0,003-0,007).
R3 (~1h/barra dollar) é a resolução mais grosseira das 3 testadas; sob
menos barras por episódio, o baseline (definição fixa por quantil) perde
poder de separação, enquanto HMM (ajustado ao dado real de cada
resolução) mantém.

#### B. Gate 1 — occupancy não pode ser degenerado ("nem ausente, nem dominante")

**Metodologia proposta** (nunca escolhida depois de olhar qual candidato
ganharia — ver verificação de robustez abaixo, que é o motivo de propor
faixa em vez de valor único): stress\_occupancy\_median não pode
caracterizar o estado como **dominante** — mais de ~1/3 do tempo. Não é
"deve igualar o baseline" (3%, ~11-13× menor que qualquer candidato —
exigir isso desqualificaria os 5 candidatos de uma vez, o que
descartaria regime-como-gate inteiro na v1, não é a leitura razoável de
"nem ausente, nem dominante"). É ancorado na função ECONÔMICA do gate:
um "estado de risco elevado" que ocupa >1/3 do histórico não é mais uma
minoria identificável — usá-lo pra restringir entrada cortaria
throughput de trade de um jeito que colide direto com R3 (§0.2,
~55 trades/mês).

Verificação de robustez (mesmo espírito do sweep ±50% de constante
classe A, `§16.10` regra 4) — testado o limiar em 25%/33%/40%:

| candidato | occ. mediana (R1-R3) | occ. por janela (min-max, R1) | passa 25%? | passa 33%? | passa 40%? |
|---|---|---|---|---|---|
| `hmm_k2` | 34,1-39,5% | 8,8%-43,9% | não | limítrofe/não | limítrofe |
| `hmm_k3` | 18,3-21,5% | 4,1%-21,1% | sim | sim | sim |
| `hmm_k4` | 10,5-12,7% | 3,0%-15,6% | sim | sim | sim |
| `bocpd` | 23,7-29,7% | 20,8%-35,8% | limítrofe/não | sim/limítrofe | sim |

`hmm_k3`/`hmm_k4` passam em QUALQUER ponto da faixa testada — decisão
não sensível ao valor exato do limiar. `hmm_k2` falha ou fica no limite
em toda a faixa (inclusive por janela: `ETF_HALVING`/`RECENTE` em
R1 chegam a 44%/43%) — não é um caso limítrofe de 1 medição, é
consistente entre janelas e resoluções.

#### C. Gate 2 — transition failure rate não pode indicar oscilação sem parar

**Metodologia proposta**, mesma disciplina: tfr\_n5\_mediana não pode
exceder ~2-3× a do baseline (candidato não pode ser categoricamente
menos estável que a referência já em produção). Baseline tfr\_n5:
0,150/0,162/0,171 (R1/R2/R3) → banda 2×-3× = 0,30-0,51.

| candidato | tfr\_n5 (R1/R2/R3) | vs. baseline (mediana across-res) | passa 2×? | passa 2,5×? | passa 3×? |
|---|---|---|---|---|---|
| `hmm_k2` | 0,196/0,162/0,219 | ~1,2× | sim | sim | sim |
| `hmm_k3` | 0,177/0,210/0,195 | ~1,2× | sim | sim | sim |
| `hmm_k4` | 0,224/0,224/0,228 | ~1,4× | sim | sim | sim |
| `bocpd` | **0,529/0,557/0,472** | **~3,3×** | não | não | limítrofe só em R3 isolado |

`bocpd` falha em QUALQUER ponto da faixa testada (2×-3×) quando avaliado
pela mediana entre resoluções (a única janela onde um limiar de 3× quase
passaria — R3 isolado, 0,472 vs. 0,513 — não sobrevive quando agregado
com R1/R2, que falham por margem grande). Os 3 HMM passam com folga em
toda a faixa. Achado consistente com a suspeita já registrada nesta
sessão (BOCPD é bom pra detectar CHOQUE abrupto, ruim pra manter um
label de regime sustentado sem flicker).

#### D. Gate 3 (desempate) — não precisou entrar em jogo

Sobreviventes dos Gates 1/2: `hmm_k3`, `hmm_k4` (baseline não é
candidato a promover, já está em produção). Na métrica primária
(heterogeneidade de volatilidade, i²/p\_perm), `hmm_k4` vence `hmm_k3`
nas 3 resoluções — R1 (97,44 vs. 97,40, marginal), R2 (94,98 vs. 94,54,
marginal), **R3 (91,77 vs. 85,65, diferença clara)**. Não é empate — não
há necessidade de invocar detection delay (`m4_luna_event_onset_ts_ms`/
`m4_ftx_event_onset_ts_ms`, `AG-118` prep) como desempate.

**Leitura secundária, não decisória:** `bocpd` tem o menor detection
delay das 5 (81-143M ms ≈ 1-1,7 dia, vs. 94-202M ms dos HMM e ~2,9-3,4×10⁸ ms
do baseline) — mas já está desqualificado pelo Gate 2, então essa
velocidade nunca chega a pesar no ranking. Registrado como leitura pra
referência futura (ex. se algum dia BOCPD for reconfigurado pra reduzir
o flicker), não como argumento pra reabrir o veredito agora.

#### E. Veredito — candidato vencedor do AG-114

**`hmm_gaussian_k4_v1` (HMM Gaussiano, K=4)** — passa os 3 gates com
folga (robusto a ±40-50% de variação nos limiares propostos), vence a
métrica primária nas 3 resoluções, com a maior margem justamente na
resolução mais grosseira (R3) onde baseline/`hmm_k3` perdem poder de
separação. `hmm_gaussian_k3_v1` é o runner-up defensável (mesma folga
nos gates, métrica primária só ligeiramente atrás em R1/R2, atrás com
folga em R3).

Isto fecha a Fase 1 da cadeia desenhada em `§15.12.4` (AG-118) —
candidato vencedor: `hmm_gaussian_k4_v1`. AG-118 (Fase 2, Gate
Efficiency) foi implementado e rodado no mesmo dia; auditoria externa
(Manager, papel de auditor —
`docs/brief_auditoria_externa_2026-08-20_gate_efficiency_ag118.md` +
parecer de resposta) achou 2 problemas sérios, ambos VERIFICADOS contra
código/dado real, não só aceitos por autoridade:

1. **O veredito "`hmm_gaussian_k4_v1` vence" acima não é robusto.** O
   Gate 1 foi aplicado misturando 2 critérios (mediana de resolução vs.
   máximo por janela) sem declarar qual decide. Sob o critério literal
   (mediana, no próprio teto de 40% já testado nesta seção) —
   `hmm_gaussian_k2_v1` PASSA o Gate 1 (34,1/34,9/39,5%, todos <40%) e
   VENCE a métrica primária em R1 (97,82 vs 97,44) e R2 (95,31 vs
   94,98). A tabela de sensibilidade acima testou se k=4 SOBREVIVE à
   faixa de limiares — não testou se k=4 CONTINUA VENCENDO, que é a
   pergunta que importa.
2. **A conclusão de `lift`≈1 do AG-118 está mal-instrumentada, confirmado
   com dado real.** `p05_return_atr` divide `ret_net` pelo MESMO
   `atr_at_t0` que já escala a largura da barreira TP/SL
   (`triple_barrier.py:1130-1131`) — tautológico por construção.
   Diagnóstico D1 (`tools/diagnostics/crosscheck_stress_bucket_vs_
   atr_decile.py`, rodado nesta sessão): **60,5% dos labels com
   `is_stress_bucket=True` caem nos 2 decis superiores de `atr_at_t0`**
   (vs. ~20% esperado sob independência, n=972.798) — o bucket de
   stress do HMM k=4 é fortemente colinear com ATR alto em t0.

Detalhe completo, fila de diagnósticos priorizada (D1-D5/R1-R3, custo
crescente) e reformulação da conclusão: `AG-122`
(`audit/architecture_gaps_log.yaml`). `AG-114`/`AG-118` REABERTOS —
`hmm_gaussian_k4_v1` não deve ser tratado como vencedor definitivo nem
"regime não funciona como gate" como conclusão até essa fila ser
processada.

`AG-118` RESOLVIDO 2026-08-21 (fila `AG-122` processada): `lift` bem
medido (IC via efetivo-N ponderado por `uniqueness`, método de Katz) em
90 células (k2/k3/k4 × 3 resoluções × 5 símbolos × 2 sides), sem sinal
econômico — achado mecanístico: `exit_price` de TP/SL é o próprio preço
da barreira (`triple_barrier.py`, convenção documentada, não bug),
tornando qualquer tail-loss derivado de `ret_net` quase-determinística
em `atr_at_t0`. `AG-114` (fragilidade do Gate 1, k=2 vs. k=4) permaneceu
aberto até ser resolvido no mesmo dia — Manager travou o critério em
pior-caso (não mediana), `§15.12.6`. 1 hipótese alternativa (HMM com
vantagem em R3 por fit in-sample) foi checada e REFUTADA — fit é
walk-forward genuíno.

**`AG-120` (achado novo desta auditoria, registrado em
`audit/architecture_gaps_log.yaml`):** `BNBUSDT`/`RECENTE`/R2 falhou com
`ValueError` de desalinhamento `t0`(baseline)↔`open_time`(bars) —
isolado por `AG-019`, não muda o agregado (`n_windows_ok` de R2 conta
uma célula a menos pros candidatos afetados), mas é um gap de qualidade
de dado real, não investigado a fundo aqui (fora do escopo desta
auditoria de resultado) — aberto pra investigação futura.

### 15.12.6 AG-114 — Gate 1 re-operacionalizado, fragilidade resolvida (2026-08-21)

**Decisão do Manager** (Tabela 1 da rodada `stage_readiness_audit`, item
6): "B, documentado — pior-caso é o critério certo para desqualificador".
Trava por escrito o critério que `§15.12.5` bloco B deixou ambíguo entre
mediana-por-resolução e máximo-por-janela: **Gate 1 usa PIOR-CASO —
`max(stress_state_occupancy)` entre TODOS os pares símbolo×janela
avaliados** (25 células por candidato por resolução — 5 janelas × até 5
símbolos), não a mediana. Teto mantido em ~1/3 (33%), mesmo racional
econômico já documentado ("nem ausente, nem dominante").

Recomputado direto de `experiments/m4_critical_windows_report.json`
(`by_resolution[].gate_quality[].per_window[].per_symbol[].stress_
state_occupancy`), sem nova execução — o dado já existia, só a
agregação estava indefinida:

| candidato | pior caso R1 | pior caso R2 | pior caso R3 | passa 33% nas 3 resoluções? |
|---|---|---|---|---|
| `hmm_gaussian_k2_v1` | 54,2% | 55,4% | 56,4% | **NÃO — falha nas 3** |
| `bocpd_v1` | 43,2% | 54,3% | 55,0% | **NÃO — falha nas 3** (já desqualificado por Gate 2 de qualquer forma) |
| `hmm_gaussian_k3_v1` | 34,9% | 28,0% | 28,3% | não — falha em R1 (34,9% > 33%), passa em R2/R3 |
| `hmm_gaussian_k4_v1` | 16,6% | 17,6% | 25,8% | **SIM — único candidato robusto nas 3 resoluções** |

**Sob o critério agora travado, `hmm_gaussian_k2_v1` FALHA o Gate 1 nas
3 resoluções** — nunca chega a competir na métrica primária, ao
contrário do que a leitura por mediana sugeria (§15.12.5, onde k2
passava e vencia em R1/R2). `hmm_gaussian_k4_v1` continua vencendo a
métrica primária contra `hmm_k3` entre os sobreviventes (mesmos números
de `§15.12.5` bloco D — R1 97,44 vs 97,40; R2 94,98 vs 94,54; R3 91,77
vs 85,65).

**Veredito do `AG-114` (`hmm_gaussian_k4_v1`) CONFIRMADO — não muda,
fica mais robusto**: o candidato que quase venceu sob a leitura ambígua
(`hmm_k2`) deixa de ser sequer um competidor viável sob o critério
corretamente especificado. `AG-114` considerado **FECHADO** quanto à
fragilidade original do Gate 1. Qualquer comunicação futura sobre "k=4
venceu o M4" não precisa mais da ressalva do Gate 1 — a ressalva sobre
`AG-118`/`AG-122` (sem sinal econômico detectável do gate em si,
questão ortogonal) continua valendo.

**Item residual, não bloqueante**: definição operacional de "empate"
pro Gate 3 (desempate por detection delay) segue sem definição
explícita — não importou nesta rodada (Gate 3 nunca precisou entrar,
`hmm_k4` venceu com margem clara em R3 e marginal-mas-decisiva em
R1/R2), fica pendente pra uma futura reavaliação onde a métrica
primária ficar mais próxima entre 2 candidatos. Detalhe completo:
`audit/architecture_gaps_log.yaml::AG-114::status_gate1_criterio_
operacionalizado_2026_08_21`.

### 15.12.7 AG-114 — definição operacional de "empate" travada; consequência: Gate 3 precisa rodar de verdade (2026-08-22)

**Reconciliação de registro, não recontagem**: o Manager citou k2 a
"43-44%" em `ETF_HALVING`/`RECENTE` — número correto de `§15.12.5`
(2026-08-20), mas que é um agregado POR JANELA (através dos 5 símbolos).
`§15.12.6` (2026-08-21) recomputou célula a célula (25 pares
símbolo×janela por candidato/resolução) e achou pior-caso real de
54,2/55,4/56,4% (R1/R2/R3) — mais alto porque é o pico de UM símbolo
específico (BTCUSDT/BNBUSDT) dentro da janela, não a agregação através
dos 5. **O critério "máximo por janela/pior-caso" pedido agora já estava
travado e aplicado em `§15.12.6` com o número CORRETO** (célula, não
janela-agregada) — k2 falha o Gate 1 de forma ainda mais decisiva sob a
leitura certa (54-56% vs. o teto de 33%), não menos. Nada muda no
resultado do Gate 1 em si — só o registro fica reconciliado entre as 2
seções.

**O que não estava resolvido — definição operacional de "empate" pro
Gate 3.** `§15.12.5` bloco D tratou R1 (`hmm_k4` 97,44 vs. `hmm_k3`
97,40) e R2 (94,98 vs. 94,54) como "não é empate — margem marginal mas
decisiva", sem nunca declarar o que separaria "marginal-decisivo" de
"empate de verdade". Ambos os p-valores de permutação em R1/R2 estão no
mesmo piso de resolução do teste (`p ≈ 1/(n_permutations+1) ≈ 0,001` —
nenhuma permutação superou o valor observado, pra NENHUM dos dois
candidatos) — o teste, pelo seu próprio desenho, não tem poder pra
afirmar que um superou o outro com mais confiança do que "ambos
atingiram o teto de significância que este desenho consegue medir".

**Critério travado agora, a partir do argumento acima — não da tabela**:
dois candidatos sobreviventes dos Gates 1/2 empatam na métrica primária
(portanto Gate 3 é obrigatório) quando **qualquer uma** das condições
vale: (a) os p-valores de permutação de ambos estão no MESMO piso de
resolução do teste (`1/(n_permutations+1)`, nenhuma permutação superou o
observado pra nenhum dos dois); (b) os intervalos de confiança (bootstrap
ou método apropriado à métrica primária — a computar, não existe hoje
pra `i²`/heterogeneidade neste código) se sobrepõem. (a) é suficiente
sozinho pra disparar Gate 3 mesmo sem (b) computado — não decidir
"parece próximo o bastante" por julgamento.

**Consequência direta, registrada como item em aberto, não decidida
aqui**: sob este critério, R1 (`hmm_k4` 97,44 vs. `hmm_k3` 97,40, ambos
p≈0,001) e provavelmente R2 (94,98 vs. 94,54, mesmo padrão de p-valor a
confirmar) RETROATIVAMENTE contam como empate — Gate 3 (detection delay
vs. `m4_luna_event_onset_ts_ms`/`m4_ftx_event_onset_ts_ms`) deveria ter
sido invocado pra decidir entre `hmm_k3`/`hmm_k4` nessas 2 resoluções, e
não foi. `§15.12.5` bloco D já tem detection delay agregado pros HMM
como grupo (94-202M ms), mas não quebrado por candidato — não
suficiente pra resolver Gate 3 sem nova leitura dos dados já existentes
em `experiments/m4_critical_windows_report.json`. **Não fiz essa leitura
agora** (fora do escopo desta rodada — travar o critério, não aplicá-lo)
— fica como próximo passo explícito: extrair detection delay de `hmm_k3`
vs. `hmm_k4` separadamente em R1/R2 e aplicar Gate 3 de verdade. Só em
R3 (91,77 vs. 85,65, diferença clara, `§15.12.5`) o veredito por métrica
primária permanece sem precisar de Gate 3.

Status do veredito `hmm_gaussian_k4_v1`: **não invalidado, mas não mais
"decidido só pela métrica primária" em R1/R2** — depende de Gate 3
rodar. Detalhe: `audit/architecture_gaps_log.yaml::AG-114::
status_empate_gate3_definido_2026_08_22`.

**Gate 3 aplicado de verdade (mesmo dia, 2026-08-22) — resultado REFUTA
"hmm_k4 vence nas 3 resoluções".** Extraído direto de `experiments/
m4_critical_windows_report.json` (`volatility_heterogeneity[]` pra
métrica primária, `gate_quality[].detection_delay_ms_median` pro Gate
3):

| resolução | p_perm k3 | p_perm k4 | empate? | Gate 3 (delay) | vencedor |
|---|---|---|---|---|---|
| R1 | 0,000999 | 0,000999 | SIM (idênticos) | k3=95,1M ms (~26h) vs k4=197,1M ms (~55h) | **hmm_k3** |
| R2 | 0,000999 | 0,000999 | SIM (idênticos) | k3=200,533413M ms = k4=200,533413M ms (idênticos) | **NENHUM — Gate 3 empata de novo** |
| R3 | 0,004995 | 0,002997 | não | não precisa | **hmm_k4** (separação real) |

`hmm_gaussian_k4_v1` está WIREADO em produção
(`constants.yaml::canonical_regime_hmm_n_states=4`) sob a justificativa
"vencedor robusto nas 3 resoluções" — **essa justificativa não é mais
sustentável**, mesmo com o controle de risco já desligado (`§15.13`
abaixo).

**Correção crítica, mesmo dia — "hmm_k3 vence R1" NÃO é robusto.**
Quebra por janela (`gate_quality[].per_window[]`, só BTCUSDT tem onset
computável em LUNA/FTX):

| janela | resolução | k3 delay | k4 delay | razão k4/k3 |
|---|---|---|---|---|
| LUNA | R1 | 25,0 min | 43,4h | **104,2x** |
| FTX | R1 | 52,4h | 66,2h | 1,262x |
| LUNA | R3 | — | — | 1,0165x |
| FTX | R3 | — | — | 1,0050x |

A "mediana" de R1 reportada (95,1M vs 197,1M ms) é, com `n=2`, a MÉDIA
aritmética de LUNA+FTX — confirmado por cálculo direto. O "k4 é 2,07x
mais lento" que decidiu R1 é o outlier de 104x de LUNA arrastando a
média, não uma propriedade estável — 25 minutos pra detectar regime de
stress após um onset real é rápido a ponto de merecer investigação
(artefato de índice? coincidência não-causal?) antes de aceitar o
número. R3, em contraste, mostra as 2 janelas concordando em direção E
ordem de grandeza (~0,5-1,6%) — diferença real mas pequena, não um
outlier. R2 empata IDÊNTICO por janela (não só na média) — o mais
robusto dos 3 resultados.

**Estado real**: R2 empata de verdade (regra de 2º nível ainda não
existe). R3 tem diferença pequena mas genuína (k4 marginalmente mais
lento). R1 não deveria decidir nada até o outlier LUNA ser investigado.
`hmm_gaussian_k4_v1` como "vencedor robusto nas 3 resoluções" está
refutado enquanto ALEGAÇÃO ESTATÍSTICA — mas "hmm_k3 vence" não deveria
substituir por uma alegação igualmente frágil.

**RATIFICAÇÃO FINAL, mesmo dia (2026-08-22)**: Manager ratifica
`hmm_gaussian_k4_v1` como decisão DEFINITIVA de produção — override
executivo explícito, não resolução técnica da ambiguidade acima (que
continua verdadeira como registro histórico). `AG-114` **fechado
definitivamente**. Daqui pra frente, qualquer comunicação sobre "por
que k=4" cita esta ratificação como a razão de produção — nunca mais
"vencedor robusto nas 3 resoluções" como se fosse conclusão estatística
limpa. `constants.yaml::canonical_regime_hmm_n_states=4` mantido, sem
mudança de código. Detalhe: `audit/architecture_gaps_log.yaml::AG-114::
status_ratificacao_final_manager_2026_08_22`.

### 15.13 HMM k=4 como candidato canônico de produção — override do Manager sobre AG-114/AG-118 (2026-08-21)

> **`[CORREÇÃO DE SINCRONIZAÇÃO, 2026-08-22 — achado por agente de
> pesquisa, mesma classe de furo que `AG-123` existe pra pegar]`** O
> texto abaixo (escrito 2026-08-21) descreve o gate de risco como
> LIGADO ("bloquear trade nesse bucket tem custo baixo de
> oportunidade"). **Isso deixou de ser verdade em 2026-08-22** —
> `control_01_regime_tradeavel` foi DESLIGADO de `evaluate_all()`
> (commit `3c0d83d`, `src/risk/limits.py`) na mesma sessão, por decisão
> do Manager: `AG-118` mediu evidência negativa e definitiva
> (`lift`≈1,0 em 90 células), o gate tinha sido wireado ANTES dessa
> medição existir, e manter ligado sob evidência negativa custava
> opcionalidade — pior erro que desligar. Ver
> `audit/architecture_gaps_log.yaml::AG-114::status_gate2_regime_
> desligado_2026_08_22` e `§15.12.7` acima (ratificação final de
> `hmm_gaussian_k4_v1`, mesmo dia). **O que continua verdade do texto
> abaixo**: `hmm_gaussian_k4_v1` segue como candidato canônico do
> BUILDER de regime (`build_hmm_regimes`, `canonical_regime_hmm_n_
> states=4`) — só o CONSUMO desse regime como gate de risco em
> `evaluate_all()` que mudou. Corrigir aqui em vez de reescrever a
> seção inteira (histórico preservado, não apagado).

> **`[CORREÇÃO DE SINCRONIZAÇÃO, 2026-08-27 — achado por revisão
> independente project_assurance, audit/architecture_gaps_log.yaml::
> AG-341, CRÍTICO]`** A correção acima (2026-08-22) já restringia a
> afirmação de "canônico" ao BUILDER de regime, não ao consumo como
> gate — mas ainda ficava implícito que o PIPELINE DE TREINO do Alpha
> consumia `hmm_gaussian_k4_v1`. **Isso nunca foi verdade.** Verificado
> por leitura direta de código (não presumido): `src/models/dataset.py
> :46,361-369` — o único ponto que monta o `ModelingFrame` real de
> treino — importa `src.regime.build as regime_build` e chama
> `regime_build.build_regimes(...)`, que em `src/regime/build.py:
> 116-118` instancia `classifier.QuantileRegimeClassifier(...)
> .classify(...)` — o classificador de quantis "legado", não
> `build_hmm.py::build_hmm_regimes`. Grep completo do repo confirma que
> `build_hmm_regimes` tem só 3 chamadores, todos scripts de análise/
> pesquisa (`hmm_gap_check.py`, `gate_efficiency.py`,
> `m4_regime_comparison.py`) — nunca `dataset.py`/`alpha.py`/
> `pipeline.py`. **O que isso muda**: "canônico de produção" nesta
> seção sempre descreveu uma DECISÃO (override do Manager, válida como
> tal) que nunca chegou a ser WIREADA no pipeline real de treino — o
> gap entre decisão e implementação nunca foi fechado, e não havia
> registro explícito disso até agora. **O que continua verdade**: a
> decisão do Manager (override sobre `AG-114`/`AG-118`) permanece
> válida como decisão; `build_hmm.py` existe, é testado, e é o
> candidato que DEVERIA ser usado. Decisão pendente (nenhuma tomada
> nesta correção): (a) wireear `dataset.py` pra de fato consumir
> `build_hmm_regimes` — muda comportamento real de produção, exige
> retreino, ou (b) aceitar que o classificador de quantis é o que roda
> hoje e tratar o wiring de HMM k=4 como trabalho futuro explícito, não
> mais implícito. Ver `audit/architecture_gaps_log.yaml::AG-341` pro
> achado completo, `::AG-342` (cutoffs do classificador realmente ativo
> nunca varridos) e `::AG-343`/`::AG-344` (achados colaterais).

**Estado real no momento desta decisão, não escondido:** `AG-114`
continua **ABERTO** — a fragilidade do Gate 1 (§15.12.5 acima: sob o
critério literal de mediana, `hmm_gaussian_k2_v1` passaria o Gate 1 e
venceria a métrica primária em 2 das 3 resoluções) não foi resolvida por
nenhum diagnóstico da fila `AG-122`; só uma hipótese alternativa (fit
in-sample) foi checada e refutada, o que NÃO é o mesmo que validar o
Gate 1 como especificado. `AG-118` está **RESOLVIDO**, e o resultado é
que o gate de risco (bloquear entrada no bucket de stress do HMM) **não
tem sinal econômico detectável** — `lift` não desvia de 1,0 em 90
células (3 candidatos × 3 resoluções × 5 símbolos × 2 sides, IC via
método de Katz ponderado por unicidade de label), robusto ao candidato
(k=2/3/4 dão o mesmo resultado nulo).

**Isto é um override de negócio, registrado como tal — não uma
re-especificação do Gate 1 nem uma alegação de edge medido.** O Manager
autorizou `hmm_gaussian_k4_v1` como candidato de regime canônico de
produção mesmo com os dois achados acima na mesa, como "segurança extra
de baixo custo": o bucket de stress do HMM ocupa só ~5-12% do tempo
(medido em `AG-114`), então bloquear trade nesse bucket tem custo baixo
de oportunidade mesmo sem prova de que reduz risco de cauda real além do
que ATR já captura (`AG-122`, achado mecanístico: `exit_price` de
TP/SL é o próprio preço da barreira, o que torna qualquer tail-loss
derivado de `ret_net` quase-determinístico em `atr_pct`). Qualquer
comunicação futura sobre "k=4 venceu o M4" precisa carregar a ressalva
do Gate 1 — este override não fecha essa pergunta.

**Escopo entregue** (plano completo, sessão 2026-08-21,
`C:\Users\Felipe_a_Lenda\.claude\plans\wise-exploring-panda.md`):

- **Fase A** — regime SAIU do vetor de treino do Alpha
  (`src/models/alpha.py`): `DESIGN_COLUMNS` deixa de incluir o one-hot
  de 4 colunas (`R2..R5`), passa a ser só as 10 features T1. Decisão do
  ADR-001 §2.7 ("regime = gate de risco, não feature preditiva",
  ratificada pelo Manager em `§15.12`) nunca tinha sido aplicada ao
  código até agora. **Ação operacional separada, fora deste escopo:**
  só tem efeito real depois que `src.models.pipeline.run_layer1_sprint()`
  for reexecutado — os artefatos de predição atuais ainda refletem o
  modelo antigo (14 colunas) até lá.
- **Fase B** — novo builder de produção `src/regime/build_hmm.py::
  build_hmm_regimes` (walk-forward ancorado trimestral, mesmo contrato
  de fold de `B05`/M4), reusando `identify_stress_state_by_volatility`
  (`src/validation/regime_utility.py`, já usado no M4 pra identificar o
  bucket de stress sem rótulo semântico). Espaço de observação extraído
  pra `src/regime/hmm_features.py` (antes vivia só dentro do harness
  `src.analysis.m4_regime_comparison`, que continua funcionando
  idêntico via re-export). Sem persistência em disco nesta fase — não
  há orquestrador vivo consumindo ainda.
- **Fase C** — Risk Engine candidato-agnóstico
  (`src/risk/limits.py`): `control_01_regime_tradeavel` e
  `RiskEngineInputs.regime_tradeable` passam a receber `bool` já
  resolvido pelo builder de regime, não mais `regime: str` comparado
  contra o vocabulário `TRADEABLE_REGIMES` do baseline. Tanto
  `build_regimes()["tradeable"]` (baseline) quanto
  `build_hmm_regimes()["tradeable"]` (HMM) alimentam o MESMO campo sem
  tradução de vocabulário — evita reintroduzir o erro que `AG-121` já
  documenta (mapear `canonical_id` do HMM pros rótulos R1-R4 seria uma
  segunda fonte de verdade inventada).
- **Constante nova** — `canonical_regime_hmm_n_states` (valor 4,
  `config/constants.yaml`, classe B, `provenance: MEASURED` com a
  narrativa completa do override no campo `source`, não uma medição
  limpa).

**Cadência de refit** — trimestral civil ancorado (mesmo
`generate_anchored_walk_forward_splits` do M1/M4), declarada a priori
por reuso de constante já existente (`m1_walkforward_initial_train_years`)
— sem constante nova de cadência (B22: retreino em cadência fixa
declarada, nunca reativo a sequência de perdas).

**Limite de escopo explícito, não uma lacuna a preencher agora:** não
existe nenhum caminho live/streaming no repo (`src/live/__init__.py`
vazio) — "canônico de produção" aqui significa código pronto, testado, e
com a interface certa, não "rodando ao vivo" (Sprint 12+, fora de
escopo). `AG-121` (canonicalização por retorno, não volatilidade) segue
sem resolução — `build_hmm_regimes` contorna corretamente via
`identify_stress_state_by_volatility`, migração completa continua
pendente do action item 3 do ADR-001.

### 15.14 Decisão registrada: Alpha migra de XGBoost pra LightGBM (execução represada, 2026-08-21)

**Status: decisão registrada, NÃO implementada em código.** Manager
decidiu trocar o learner do Alpha (Camada 1, `src/models/alpha.py`) de
XGBoost (`binary:logistic`, `Stack 2026` de `CLAUDE.md`) pra LightGBM.
Motivo não detalhado nesta sessão — registrar aqui em vez de inventar
justificativa (§16.10, nunca estipular proveniência que não foi dada).

**Execução deliberadamente represada** — mesmo motivo de
`canonical_volatility_estimator` (§11.4/§11.5): o Manager decidiu
separadamente (mesma sessão, 2026-08-21) que **Alpha não é retreinado
até a Trilha de engenharia — 15 estágios, Data Layer inteiro
(`01_BARRA` a `07b_PESOS` + `08_SPLIT`, `§15.4`) estar 100% pronto** —
não só o item pontual que motivou uma sugestão de retreino. Ver
mapeamento real do Data Layer nesta mesma data (achado central:
`AG-100`, labels ausentes pra R2/R3, é o bloqueador que mais cascateia).
`src/models/alpha.py` continua XGBoost até essa migração de código
acontecer, junto do retreino represado — não migrar o learner ANTES do
retreino, pra não ter 2 janelas separadas de "código não bate com o que
está rodando".

**O que muda quando a migração de código acontecer** (não decidido
ainda, registrado aqui pra não esquecer quando chegar a hora): B18
(`multi:softprob` proibido) e B19 (`colsample_bytree < 1.0` proibido) em
`CLAUDE.md` usam nomenclatura ESPECÍFICA do XGBoost — o equivalente
LightGBM de B19 é `feature_fraction` (não existe `colsample_bytree` na
API do LightGBM); B18 (`multi:softprob`) nem existe como conceito no
LightGBM (`multiclass`/`multiclassova` são os objectives multi-classe
de lá) — de qualquer forma o motivo por trás de B18 (nunca usar softmax
multi-classe, sempre 2 binários `M_long`/`M_short`) continua válido
architeturalmente, só o literal do padrão banido muda de nome.
`monotone_constraints` (DoD "código de modelo") tem equivalente direto
no LightGBM (mesmo nome de parâmetro) — não precisa mudar.

**[ATUALIZADO 2026-08-23, achado `project_assurance` sobre a migração
LightGBM do Alpha — ver `§15.20.1`]** Esta seção dizia "não migrar o
learner ANTES do retreino, pra não ter 2 janelas separadas". Isso
mudou: o usuário pediu explicitamente a implementação completa do
design doc do Alpha (D-01 a D-18, `docs/alpha_model_design_doc_
2026-08-22.md`) nesta sessão, ANTES do retreino real (que segue
bloqueado pelo gate "Data Layer 100%") — `src/models/alpha.py` já é
LightGBM em `master` (commits `d15ff73`/`321c414`/`1c6f1b3`/`4781920`),
não mais XGBoost. A janela que este parágrafo queria evitar ("código
não bate com o que está rodando") existe agora deliberadamente: o
learner mudou, mas nenhum modelo foi retreinado com ele ainda — os 5
`predictions.parquet`/artefatos de modelo em disco continuam do
XGBoost antigo até o retreino real acontecer. B18/B19 de `CLAUDE.md` e
o `Stack 2026` (linha "XGBoost `binary:logistic`") também desatualizados
por esta mudança, corrigidos no mesmo commit desta nota.

### 15.15 AG-124 — recalibração causal do threshold dollar-bar: `T=7,C=7` preferido, reprocessamento em execução (2026-08-21/22)

**Contexto**: `AG-124` (`§15.14` anterior nesta mesma sessão de
"Atualize governança", achado do fan-out `stage_readiness_audit`)
registrou vazamento temporal real na calibração do threshold dollar-bar
(`threshold_usdt` calibrado sobre a MESMA janela sendo construída —
deriva de até 42,7x medida, BTCUSDT, histórico completo). Remediação:
recalibração causal rolante (`build_dollar_bars_walkforward`,
`src/data/build_dollar_bars.py`), calibrando cada período só sobre
`[app_start-trailing_window_days, app_start)`, estritamente anterior.

**Linha de investigação concluída nesta sessão** (auditoria externa em
várias rodadas, 13 addenda registrados no ledger — parecer + adendo dos mesmos 2 documentos, `docs/Retorno_
Brief/`, mais 1 documento de auditoria descartado por não-confiável,
colisão de numeração `AG-125` real + claims técnicos sem base no
código): `trailing_window_days=7` travado (elimina aliasing de
sazonalidade semanal, sábado ~0,59x a média em BTC/ETH, medido). Sobre
`cadence_days`, testado `7` vs. `1` desacoplado (achado que os dois
nunca tinham sido testados independentemente até esta sessão — mesmo
padrão de furo de parâmetros acoplados, 2ª ocorrência confirmada na
mesma investigação):

- `T7,C1` vence a métrica de rastreio de calibração por margem grande
  nos 5 símbolos, robusto a sweep do corte de decisão (M1 redux) — item
  6/§14.4 do plano de ação.
- Mas `C1` exercita **7,25x mais eventos de transição de threshold**
  que `C7` (365 vs. ~52/ano/símbolo) — cada evento é um ponto onde a
  barra viola o invariante que define uma dollar-bar (tamanho por
  volume, não por troca de threshold com acumulação em voo). Medido:
  taxa de barra subdimensionada por evento é estatisticamente igual
  entre os 2 braços (~50%, controlado — não é defeito de `C1`), mas o
  retorno `|z|` associado a um evento de fronteira é maior sob `C1` que
  sob `C7` na MESMA janela de calendário (5/5 símbolos, teste decisivo
  contra confundimento de hora-do-dia) — elo real, embora modesto.
- Decisão final apoiada em 3 argumentos de engenharia de sistema,
  independentes da estatística de cauda: **tipo de erro** (`C7` erra de
  forma suave, absorvida por feature normalizada por ATR; `C1` erra de
  forma discreta, nada absorve, relevante com ~79 features futuras
  ainda não avaliadas quanto a isso); **assimetria de estar errado**
  (sem métrica de sucesso final registrada — confirmado nesta sessão —,
  errar com `C7` é reversível/barato, errar com `C1` significa 7x mais
  artefato gravado em 6+ anos × 5 símbolos); **superfície de paridade
  lote↔streaming ao vivo** (`src/live/` ainda vazio — `C1` multiplica
  por 7x os pontos onde calibração atrasada/janela incompleta/restart
  no horário errado diverge grade backtest↔produção).

**Decisão**: `trailing_window_days=7`, `cadence_days=7` — registrados em
`config/constants.yaml` (`dollar_bar_walkforward_trailing_window_days`/
`dollar_bar_walkforward_cadence_days`, `provenance: MEASURED`, valor
marcado explicitamente como candidato PREFERIDO por esta linha de
investigação, não mais "provisório por motivo em aberto"). Trava formal
fica com o Manager confirmar por escrito quando conveniente — a
investigação técnica está concluída, sem pergunta em aberto identificada
por nenhuma das 2 partes (dev + auditor externo).

**Reprocessamento real CONCLUÍDO** (2026-08-22, `tools/diagnostics/
run_ag124_production_reprocessing.py`, 5 símbolos × 3 resoluções,
histórico completo — `SYMBOL_START_DATE`/`END_DATE`,
`volatility_comparison.py` — `overwrite=True` sobre
`data/capacity/dollar_bars_r{1,2,3}/` real, substitui a calibração
não-causal antiga): **15/15 células, zero erro**
(`experiments/ag124_production_reprocessing_summary.json`,
`code_version=eee33eb`, isolamento de falha por célula `AG-019` não
precisou disparar). `n_cold_start_dropped=1` em toda célula — esperado
(1º período de cada símbolo genuinamente sem histórico antes de
`SYMBOL_START_DATE`).

**Item 22 concluído (2026-08-22) — validação sobre dado REAL
reprocessado**: `tools/diagnostics/measure_ag124_post_reprocessing_
validation.py`, 15 células, histórico completo (não amostra),
`experiments/ag124_post_reprocessing_validation.json`. **Resultado
positivo**: curtose em excesso praticamente INALTERADA ao excluir
barras de fronteira (ex. BTCUSDT/R1 53,12 vs. 53,15; XRPUSDT/R1 122,46
vs. 122,49) — sobre histórico real completo, o artefato de
recalibração que motivou a investigação de 6 rodadas é desprezível;
curtose alta observada é 100% evento de mercado genuíno, não
metodológico. Autocorrelação lag-1 pequena em todas as 15 células
(|r|<0,03). As 5 barras mais extremas por célula são todas não-boundary
e batem com eventos reais conhecidos (BTCUSDT 2022-06-13 contágio
Celsius/3AC, 2020-03-12 Black Thursday COVID; XRPUSDT 2022-11-08 —
coincide quase exatamente com `m4_ftx_event_onset_ts_ms` já registrado
no M4).

**Achado colateral do item 22 (`AG-137`) — fechado 2026-08-22**: os
`cadence_days` (=7) dias iniciais de cada célula ainda tinham o arquivo
`.parquet` da calibração NÃO-causal antiga (cold-start corretamente
pulado na escrita, arquivo velho não removido). Manager decidiu
deletar — 104 arquivos removidos, verificado 0 restante; cada célula
agora começa exatamente em `SYMBOL_START_DATE + cadence_days`, gap
honesto no lugar de dado com vazamento residual.

**Nota registrada (2026-08-22) — calibração causal no Live não é o
mesmo problema que o cold-start do AG-137**: cold-start é um artefato
de BORDA DO HISTÓRICO (não existe trade antes de `SYMBOL_START_DATE`
pra calibrar contra) — não recorre no lançamento do Live pros 5
símbolos já existentes, porque nessa data já existirão anos de
histórico real disponível pra calibrar o 1º período causalmente. O gap
real, genuíno e ainda NÃO desenhado: `build_dollar_bars_walkforward`
hoje é uma função de LOTE (intervalo `[start,end]` finito, processado
período a período em memória) — não existe um processo CONTÍNUO
equivalente pro Live (recalibrar a cada `cadence_days` de forma
perpétua, com recovery de restart/downtime bem definido, e teste de
paridade lote↔streaming provando que o resultado é idêntico ao que o
builder de backtest produziria pra mesma janela — DoD já exigido pra
"código de feature" no `CLAUDE.md`). `src/live/` está vazio por
desenho (Sprint 12+, fora do escopo atual) — não é um bug a corrigir
agora, é um item de arquitetura a desenhar quando o Live entrar em
pauta, registrado aqui pra não ser silenciosamente assumido como
"já resolvido" quando chegar a hora.

**Achados colaterais fechados na mesma linha**: item 14 (`Threshold
BarsCarry` agora persiste através da fronteira de período — 1 barra
subdimensionada por RODADA, não por período — pré-condição pra `C=1`
ter sido sequer viável de medir), item 15 (lead-in buffer recupera ~1
semana real por símbolo antes descartada sem necessidade), item 16
(circuit breaker validado com folga contra pico de volume ~14x medido),
`AG-120` (varredura de integridade em todas as 51 células da amostra do
M4 — só a célula já conhecida diverge, confirmado ISOLADO, não
sistêmico, causa raiz do trade-level ainda pendente mas não bloqueante).
Semântica de troca de threshold com barra em aberto — antes "não
trivial"/implicitamente indefinida — formalizada e testada com asserts
de valor exato (`src/data/build_dollar_bars.py::build_dollar_bars_
walkforward`, docstring + `tests/unit/test_data_bars.py`).

**[PONTEIRO 2026-08-23]** `build_dollar_bars_walkforward` (a função) era
causal desde esta sessão, mas o CLI do módulo (`main()`, `python -m
src.data.build_dollar_bars`) continuou default para a família legada
vazadora até `AG-138` ser fechado em 2026-08-23 — ver `§15.25`.

Detalhe completo (todos os números, todas as retratações honestas
registradas): `docs/plano_acao_ag124_pos_auditoria_2026-08-21.md`;
ledger completo: `audit/architecture_gaps_log.yaml::AG-124` (13 addenda).

> **STATUS SUPERADO 2026-08-25 (`AG-232`/`AG-235`) — o S1 deixou de ser
> lacuna aberta, e a resposta é "a geometria não é a alavanca".** Duas
> coisas aconteceram desde que o parágrafo abaixo foi escrito. (1) Descobriu-se
> que o S1 lia a grade de RELÓGIO 15m (`AG-232`): a troca de `tp_atr_mult`
> para 1,5 em 2026-08-24 foi decidida sobre uma grade que não é produção.
> (2) Corrigido e re-executado sobre R1 (`AG-235`), com armadilha de
> comparação detectada antes de concluir — as células não têm o mesmo número
> de estratos, porque o filtro de R2 por símbolo torna `sl=0,75` viável só em
> SOLUSDT. Comparando **apenas as 5 células com cobertura completa**
> (`n_estratos=10`) e contabilizando o CUSTO junto do edge, o gap edge-custo
> varia de **5,95 a 6,19 bps** — spread de 0,24 bps sobre um gap de ~6.
> **Trocar a geometria renderia +0,02 bps (0,3%).** O mecanismo é estrutural:
> R:R maior melhora o edge bruto mas piora o custo (P(TP) cai, mais saídas
> viram taker), e os dois efeitos se cancelam — contrapartida empírica do
> resultado teórico de que, sob martingale, o edge bruto é ZERO para qualquer
> geometria simétrica. **Recomendação: NÃO trocar `tp_atr_mult`/`sl_atr_mult`.**
> Ressalva honesta: a grade do S1 não cobre células mais largas (`tp=sl=3,0`);
> estender é barato agora que o módulo roda na grade certa, mas o cancelamento
> edge↔custo é estrutural, não específico das células testadas. Correlato:
> `AG-237` — o `sweep_range` das duas constantes tinha sido REMOVIDO junto com
> a troca de valor, removendo o guardrail da §16.10 regra 4; restaurado.

**S1 — maior lacuna aberta do projeto, independente de tudo acima**:
`tp_atr_mult`/`sl_atr_mult` (constantes classe A, `provenance: ASSUMED`,
"herdado do PRD V2, nunca questionado") — define a variável dependente
de todo experimento de M4/AG-114/AG-118 já medido. **Estado atual
(2026-08-22)**: design doc completo e auditado (`docs/s1_design_doc_
sweep_tp_sl_reward_risk_2026-08-22.md`), Fase 5 (implementação) NÃO
iniciada — Manager decidiu que não é acionável agora (cadeia real:
Data Layer 100% → retreino do Alpha, represado até refatoração pra
LightGBM → V41-6 condicionado na população que o Alpha dispara).

Metodologia decidida: seguir `ADR-001 §5` item 10 (maximizar razão
payoff esperado/hurdle de custo via distribuição empírica de tempo-até-
barreira), não o percentil de MFE do `PRD_V4_1.md §4.1` — reusa
`feasibility.py`/`barrier_sweep.py` existentes, sem precisar de coluna
nova (`mae_atr_units`) no Label Engine.

**`[ABERTO, decisão adiada — 2026-08-22]` Forma exata da otimização
(razão precisa a maximizar, papel da distribuição de tempo-até-barreira
na função objetivo, método de otimização concreto)**: delegado a agente
de desenho (`redesign_workflow` Fase 4), recomendação em andamento no
momento desta atualização — decisão final fica pro Manager quando a
cadeia acima destravar. Trabalho feito enquanto isso, sem depender da
população do Alpha: filtro R2 aplicado ao espaço de `sl` (ATR% mediano
medido nos 5 símbolos — `S=0,75` viola R2 pra BTCUSDT/BNBUSDT
especificamente), diagnóstico de distribuição de MFE rodado como
fixture de validação (não fonte de valor).

---

### 15.16 ADR-001 action item 2 — `src/io/artifact.py`/`src/io/schema.py` implementados (2026-08-22)

**Autorização**: Manager, mesma sessão — "autorizado e ratifico as
recomendações, pode mapear o código e implementar tudo via skill
recomendada" (`redesign_workflow`, 7 fases). Escopo desta rodada: só o
action item 2 do ADR-001 ("`src/io/artifact.py`/`src/io/schema.py`...
antes de qualquer outro módulo") — os outros 12 action items ficam
sequenciados atrás, não tentados de uma vez.

**Fase 2 (exploração)**, 3 agentes paralelos mapeando `labels/`,
`features/registry.yaml`, `weights.py`/`regime/`/`importlinter`: achado
colateral novo registrado como `AG-145` (`audit/architecture_gaps_log.
yaml`) — corrida de leitura-modificação-escrita real em
`experiment_log.py::record_experiment` sob `ProcessPoolExecutor`, sem
lock (verificado contra dado real: não perdeu linha no backfill de
`AG-100`, mas o risco é real, não travado — exatamente o problema que
V-06 do ADR resolve).

**Fase 4 (desenho)**, 3 propostas (`code-architect`, mudança mínima/
arquitetura limpa/equilíbrio pragmático) — decisões finais, com
divergência explícita do texto literal do ADR onde há razão real:

1. **`config_hash`: sha256+orjson+16-hex, NÃO blake2b** (o ADR cita
   blake2b em pseudocódigo). Reusa o padrão já em produção em 3 lugares
   (`LabelConfig.config_hash`, `bars_calibration_hash`, `_hash_filters`)
   — introduzir um segundo primitivo de hash sem benefício medido seria
   inconsistência gratuita.
2. **Funções livres, não classes** (`write_artifact`/`read_artifact`/
   `scan_artifact`, não `ArtifactWriter`/`ArtifactReader`) — consistente
   com o resto do repo (`write_labels_atomic`, `write_regimes_atomic`
   já são funções livres, não há precedente de classe com estado pra
   I/O neste projeto).
3. **`bar_id` (INV-A) é OPCIONAL, não fabricado.** Nenhum artefato real
   hoje tem `bar_id` monótono — tudo é timestamp. `ArtifactSchema`
   aceita qualquer `primary_key`; SE um schema futuro declarar `bar_id`
   na chave, a validação já exige uma coluna `*_ts_ns` companheira
   (V-01) — pronta pra quando o primeiro produtor de `bar_id` existir,
   sem forçar migração de nada hoje.
4. **Writer de 1 tabela (DataFrame) por artefato, NÃO a abstração
   genérica "bundle multi-arquivo"** que uma das 3 propostas
   sugeria para já suportar `snapshot/`/`promotion/`/`bundle/` (action
   items 5/9) de forma unificada. Decisão: construir isso quando esses
   estágios realmente começarem — a abstração genérica é uma ideia
   real, mas construir agora pra estágio que não existe é desenho para
   requisito hipotético (CLAUDE.md). Registrado aqui pra não se perder
   quando os action items 5/9 chegarem.
5. **`scratch=True` incluído nesta rodada** — mitigação nomeada
   explicitamente no próprio texto do ADR ("Consequências": "iterar
   rápido... modo scratch/ fora do lake, explicitamente
   não-promovível"). Escreve em `{root}/scratch/...`, permite
   sobrescrita, nunca aparece em `scan_artifact` do lake real.
6. **`gc_incomplete()` incluído nesta rodada** — metade autocontida de
   V-11 (action item 3): remove/lista diretórios sem `_SUCCESS` (lixo
   de escrita interrompida). A outra metade (GC por referência de
   `trial_registry`/`promotion/`) fica pendente dos action items 5/9.
7. **`os.rename` (não `os.replace`) pra imutabilidade** — no Windows,
   `os.rename` levanta `FileExistsError` nativamente se o destino já
   existe, dando guarda TOCTOU-livre sem checagem `exists()` prévia
   separada do rename.

**Fase 5 (implementação)**: `src/io/__init__.py`, `src/io/schema.py`,
`src/io/artifact.py`, `tests/unit/test_io_schema.py`,
`tests/unit/test_io_artifact.py`. `src/io/` segue o mesmo padrão de
`src/core/` (infra transversal, sem restrição de import —
`pyproject.toml::[tool.importlinter]` confirmado com os 7 contratos
mantidos, 0 quebrado, depois da adição). `banned_patterns`/`ruff`/
`mypy` limpos nos arquivos.

**Fase 6 (revisão, `audit_engineering`, lente FCN)**: achados reais, 4
corrigidos nesta mesma rodada (não deixados como TODO):

1. **HIGH — durabilidade inconsistente entre os 5 arquivos do bundle.**
   `schema.json`/`config.json` eram escritos sem `fsync` (só
   `manifest.json`/parquet tinham). Cenário real: crash logo depois do
   `os.rename()` retornar sucesso, antes do write-back do SO persistir
   `schema.json`/`config.json` — artefato marcado completo (`_SUCCESS`
   presente) com 2 dos 5 arquivos potencialmente truncados. Corrigido:
   `_atomic_write_bytes` único, aplicado uniformemente aos 4 arquivos
   pequenos do bundle.
2. **MEDIUM-HIGH — `input_manifest_hash` por concatenação de string sem
   separador seguro, E 0% de cobertura de teste no caminho de
   `upstream=`** (núcleo de INV-B). Corrigido: mesmo primitivo de
   `compute_config_hash` (orjson + `OPT_SORT_KEYS` sobre lista
   estruturada, não concat ad hoc) + teste novo cobrindo `upstream`
   não-vazio e determinismo sob reordenação.
3. **MEDIUM — `tmp_dir` órfão sem `try/finally` se a escrita falhar no
   meio.** Corrigido: corpo de `write_artifact` envolto em
   `try/except Exception: shutil.rmtree(tmp_dir); raise` + teste com
   `monkeypatch` forçando falha real depois de `tmp_dir` já existir.
4. **MEDIUM — retry genérico em `OSError` sem log e sem distinguir
   `ENOSPC` (disco cheio).** Corrigido: log de cada tentativa +
   fail-fast imediato em `ENOSPC` (retry nunca libera espaço em disco).

Não corrigido nesta rodada, aceito como escopo (documentado no achado
original, não esquecido): janela não-atômica em `scratch=True`
(`rmtree` antes do `rename`) — `scratch/` é explicitamente exploratório/
não-promovível, dado recriável rerodando o pipeline, LOW-MEDIUM.

**Resultado final**: 27 testes em `src/io/` (2 novos desta revisão),
suíte completa do projeto (1647 testes) verde — nenhuma regressão.
`banned_patterns`/`ruff`/`mypy`/`check_unguarded_ratios`/`import-linter`
todos limpos (3 achados de `check_unguarded_ratios` confirmados falsos
positivos — junção de `Path`, não divisão aritmética).

**Nenhuma constante nova em `config/constants.yaml`** — parâmetros de
retry de I/O (`_WRITE_RETRIES=5`, `_WRITE_RETRY_BACKOFF_S=0.1`) ficam
como constante de módulo, mesma categoria de `_DATE_BUFFER_DAYS`
(`src/models/dataset.py:61`) — infraestrutura de engenharia, não
parâmetro de domínio quant sujeito a `§16.10`.

**Escopo explicitamente NÃO coberto nesta rodada** — fica sequenciado
atrás, action items do ADR-001 ainda pendentes: 1 (ratificação formal
`D-###`), 3 (`impact --dry-run` + GC por referência), 4 (migrar
`weights.py`/`features/build.py`/`experiment_log.py` pro writer novo —
inclui o fix real de `AG-145`), 5 (`trial_registry/` um-arquivo-por-
trial), 6 (`pbo.py`), 7 (`parity_class` retrofit no registry existente
de features), 8 (pré-filtro de custo, independente, pode rodar em
paralelo), 9 (`snapshot/`/`promotion/`/`bundle/`), 11
(`barrier_collision_rule`), 12 (`dropped_signals.jsonl`), 13 (ρ em
relógio comum — parcialmente atendido por `AG-144` já, ver addendum
lá).

### 15.17 AG-145 fechado — lock entre processos em `experiment_log.py` (2026-08-22)

**Fix aplicado, não o padrão completo V-06.** `record_experiment`
(`src/labels/experiment_log.py`) ganhou um mutex entre PROCESSOS via
criação exclusiva de arquivo (`os.open(lock_path, O_CREAT|O_EXCL|
O_WRONLY)`, portátil Windows/POSIX, zero dependência nova) envolvendo
todo o corpo de leitura-modificação-escrita — fecha a corrida que
`AG-145` documentou. Lock stale (>60s) é removido à força; timeout de
30s levanta erro explícito em vez de travar pra sempre.

**Decisão deliberada de escopo, registrada aqui**: NÃO implementei
V-06 (um-arquivo-por-trial + compactação, `src/registry/trials.py`,
action item 5 do ADR-001) para este log específico. Volume real
medido é ~dezenas de linhas/ano (21 desde 2026-08-09) — não é escala
de trial do Optuna que V-06 resolve. Migrar o formato de 21 linhas
históricas com 35 colunas tipadas pra JSON individual agora seria mais
risco (serialização correta de tipos, principalmente `Datetime("ms",
"UTC")`) do que benefício nessa escala. Um lock simples é proporcional
ao risco medido — mesma disciplina de não desenhar pra requisito
hipotético que guiou as decisões do `§15.16`. `src/registry/trials.py`
fica pra quando um consumidor de volume real existir (V41-11/PBO).

**Validado com o mecanismo EXATO do bug real**, não só unitariamente:
novo teste roda 8 chamadas de `record_experiment` em 8 PROCESSOS
separados (`ProcessPoolExecutor`, não threads) contra o mesmo
`log_path` — confirma 8 linhas, `experiment_id` 1-8, sem duplicata nem
lacuna. Mais 2 testes (lock stale recupera sozinho; timeout falha
explícito). 12/12 testes de `experiment_log.py`, suíte completa do
projeto (1650 testes) verde — zero regressão.
`backfill_multi_symbol.py` não muda nenhuma linha — migração
transparente pro caller.

**Achado relacionado, registrado mas NÃO corrigido** (fora de escopo):
`src/execution/fill_simulator.py::record_experiment` tem a MESMA forma
de read-modify-write sem lock, sobre arquivo diferente
(`EXPERIMENT_LOG_PATH`) — sem confirmação de exposição real a execução
paralela hoje (parece invocado como script sequencial). Mesma classe
de risco, prioridade menor por falta de evidência de exposição.

### 15.18 AG-141 — persistência de modelo/calibrador, desenho agnóstico ao learner (2026-08-22)

**Decisão de sequenciamento revista.** `AG-141` (`audit/architecture_
gaps_log.yaml`) estava registrado como "decisão de quando fica pro
Manager" — a recomendação original era esperar a migração XGBoost→
LightGBM (`§15.14`, represada) pra não construir a persistência duas
vezes. Manager autorizou reformulação: desenhar a persistência de
forma **agnóstica ao learner**, reusando as primitivas de `src.io.
artifact` (item `§15.16`) — `atomic_write_bytes`/`atomic_rename_dir`/
`sha256_bytes` promovidas de privadas pra públicas nesta rodada,
exatamente pra serem reusáveis fora do writer DataFrame-centric.
Isso resolve o motivo original do adiamento sem esperar a migração
acontecer primeiro: só a serialização do booster (`.ubj` hoje) muda
quando o LightGBM chegar — calibrador, manifest, escrita atômica são
100% reusáveis.

**Novo módulo `src/models/persistence.py`** — `write_model_bundle`/
`read_model_bundle` por `(model_id, fold_id, side, variant)`, formato
versionado no manifest (`booster_format`/`calibrator_format`, um
formato desconhecido levanta erro explícito em vez de desserializar às
cegas). `LoadedSideModel.predict_proba_calibrated(x)` reproduz a
inferência de treino sem `XGBClassifier` nem sklearn no runtime.

**Achado real durante o desenho**: o `ADR-001` §4.9 assume calibração
via Platt scaling (`1/(1+exp(A*p+B))`, 3 linhas). O código real usa
`IsotonicRegression` (não-paramétrico, não reduz a 2 coeficientes) —
persistido como os arrays `X_thresholds_`/`y_thresholds_` fitted,
reconstrução via `np.interp`. **Verificado empiricamente, não
assumido**: `np.interp(x, X_thresholds_, y_thresholds_)` reproduz
`IsotonicRegression.predict(x)` com `max abs diff = 0,0` (`out_of_
bounds="clip"` tem a mesma semântica de `np.interp` nas pontas).
Booster: `Booster.save_raw("ubj")` → `Booster().load_model(...)`
também bit-exato (`max abs diff = 0,0`), e `Booster.predict(DMatrix)`
bate bit-exato com `XGBClassifier.predict_proba()[:,1]` pra
`objective="binary:logistic"` — não precisa da classe wrapper pra
inferência.

**Escopo explícito desta rodada — infraestrutura, NÃO wiring**: 6
testes novos (round-trip real com XGBoost/IsotonicRegression, não
mocks), suíte completa (1656 testes) verde, `banned_patterns`/`ruff`/
`mypy`/`import-linter` limpos. **NÃO integrado ao pipeline de produção
ainda** — ponto de integração identificado e documentado, não
executado: `src/models/alpha.py::run_fold` (linha 337), logo após cada
chamada de `fit_side_model` (side=1 e side=-1), precisaria de um
parâmetro novo (`persist_root: Path | None = None`, default
preservando comportamento atual) pra chamar `persistence.
write_model_bundle` com `fold_id=str(split.split_id)`/`model_id`/
`side`/`variant` já disponíveis no escopo. Decisão deliberada de não
integrar nesta mesma rodada — `run_layer1_sprint` é pipeline de
produção real (15 folds × 2 variantes × 2 lados, 7 leitores
downstream reais) e essa integração merece sua própria rodada,
depois de revisão independente da infraestrutura em si.

**Revisão independente `project_assurance` (2026-08-22) — "aprovado
com ressalvas", 3 achados MEDIUM, todos corrigidos no mesmo lote:**

1. **`AG-146`** — `predict_proba_calibrated` não tinha guarda de
   ordem/contagem de coluna. **Autocorreção descoberta durante o
   próprio fix**: a 1ª tentativa (setar `feature_names` no booster +
   `DMatrix(feature_names=...)`) não funcionava de verdade — o
   `DMatrix` sempre era rotulado com o MESMO `manifest.feature_ids`,
   nunca podia divergir de si mesmo, guarda morta. Fix real: a função
   passa a receber `pl.DataFrame` (não `NDArray`), seleciona por NOME
   (`df.select(feature_ids)`) — ordem do `df` do caller nunca importa,
   coluna faltando levanta `ColumnNotFoundError` explícito.
2. **`AG-147`** — `write_model_bundle` omitia `os.getpid()` no nome do
   `tmp_dir` (só `write_artifact` tinha), mesma classe de risco de
   `AG-145` reintroduzida mais fraca no mesmo commit. Fix de 1 linha.
3. **`AG-148`** — docstring alegava "verificado empiricamente" pra
   casos de borda do calibrador isotônico (fora do range treinado,
   degenerado) que o teste original não exercitava — eram DEDUÇÃO por
   leitura do sklearn, não medição. 2 testes novos fecham a lacuna,
   docstring corrigido pra distinguir os dois.

Achado colateral descoberto durante a correção do achado 1 (não pela
revisão original): `write_model_bundle` mutava o `booster` do CALLER
como efeito colateral — corrigido com `booster.copy()` antes de mutar.
Ponteiro de correção adicionado em `docs/ADR-001_..._base.md §4.9`
(doc canônico — Platt scaling vs. Isotonic real, achado 4 da revisão).
12 testes (6 novos/reescritos), suíte completa (1662 testes) verde.

---

### 15.19 Meta-model — arquitetura ponta a ponta travada, ADR-001 §3.7/§2.7 revogado pelo Manager (2026-08-22)

**Origem:** pedido do Manager, verbatim — *"Além de Risk Engine e Decision
Engine que vão consumir Regime, Meta-model também precisa consumir da
maneira correta para nosso motor. Meta-model será LightGBM ou Catboost, o
que melhor se aplicar. Seu desafio é desenhar a arquitetura tecnica ponta a
ponta de Meta-model."* Conduzido via skill `redesign_workflow` (7 fases).
Documento completo: `docs/meta_model_design_doc_2026-08-22.md` (v2).

#### A. A revogação — e por que ela se sustenta

Confrontado com o fato de que o ADR-001 §2.7 (ratificado por ele mesmo em
2026-08-20) dizia o **oposto** do que pedia — *"regime NÃO entra como
feature do Meta na primeira versão... as 5 condições de entrada do Meta não
mencionarem regime está certo, não é lacuna"* — o Manager respondeu,
verbatim: *"Vou revogar o contrato canônico do Meta-Labeling pois não me
convenceu, pesquise sobre Meta-Labeling no AFML depois pesquise casos de uso
recente modernos"*.

A pesquisa subsequente **sustentou a revogação**, por três vias
independentes:

1. O experimento canônico do framework formal de meta-labeling (Joubert,
   `theory_and_framework/fp_modeling.py`, código aberto) implementa três
   braços, e o terceiro é explicitamente **regime-aware** (retornos +
   informação de regime) sobre dado sintético bi-regime; `bet_sizing.py`
   condiciona o sizing a `pred_regime == 1`.
2. *Ensemble Meta-Labeling* (Thumm, Barucca & Joubert, JFDS 5(1):10-26,
   2022) lista "identificação de regime" como um dos três eixos
   experimentais e conclui que o ganho aparece **quando o dado tem múltiplos
   regimes**.
3. Um co-autor de *Meta-Labeling Architecture* (JFDS 4(4):10-24), diante de
   um resultado negativo público, recomenda incluir features de regime
   **exclusivas do meta-model**.

**O argumento que fecha, e que é próprio deste motor:** sem uma vantagem
informacional — um input que o primário não tem — meta-labeling não tem
mecanismo; cai na regressão infinita e só adiciona variância. Aqui isso não
é hipótese: **regime saiu do vetor de treino do Alpha em 2026-08-21**
(`src/models/alpha.py:57-68`, Fase A do `§15.13`). A remoção do one-hot
criou, como efeito colateral não planejado, exatamente a vantagem
informacional que o Meta precisa para existir.

**A evidência contrária permanece registrada, não silenciada:** `AG-118`
mediu `lift ≈ 1,0` em 90 células, sem sinal econômico do regime como gate.
Mas `AG-118` mede o lift **incondicional**; o Meta opera sobre a
subpopulação **condicional** (só as barras em que o Alpha disparou). Essa é
a única hipótese que `AG-118` não fechou, e virou o Gate E0 do desenho.

**A revogação não é retroativa** sobre o resto do ADR-001, que segue
canônico naquilo que não toca o Meta.

#### B. Decisão revertida na mesma sessão — Grupo J sai da frente do Meta

O Manager havia decidido construir o modelo de fila (Grupo J) **antes** do
Meta, apoiado no `PRD_V3_2_UNIFICADO.md` §6.4 (restrição de marginalidade).
Após medição, reverteu. Os três argumentos, todos verificados no código:

1. **A marginalidade de PnL de `p_fill` é exatamente zero, por construção do
   label.** `NOFILL ⟹ ret_net = 0.0` literal
   (`src/labels/triple_barrier.py:961`; `_append_nofill_row` é o único
   emissor de NOFILL em todo `src/`). `fill_rate` medido: 0,9665–0,9769 (10
   caminhos). Um `p_fill` **perfeito** filtraria 2,3–3,4% dos sinais, cada
   um contribuindo `ret_net = 0`. **ΔPnL = 0.**
2. **`cost_est_bps` é redundante com o alvo**, não marginal a ele —
   `ret_net` já é líquido (`triple_barrier.py:1317`). Sobra
   `adverse_selection_bps`, que é `ASSUMED`/classe A/`review_by: sprint_16`.
3. **Dependência circular:** `calibrate_against_real_fills` levanta
   `NotImplementedError` porque fills reais só existem em Testnet/Paper
   (Sprints 15-16) — **depois** do Decision Engine que consome `p_meta`.

Somado: a cobertura do Grupo J é de **10,5 meses num bloco contíguo de
calendário** (`bookTicker` 2023-05-16→2024-03-30), ~13% do histórico de
labels. Sob CPCV, missingness colinear com época — o modelo aprenderia
*"estou em 2023-2024"*, não física de fila. **Carimbo de data disfarçado de
feature.**

**Ressalva que impede o argumento de provar demais:** a marginalidade zero
vale para PnL-por-trade, **não** para rotação de capital — com lote mínimo =
33% do equity, um NOFILL que ocupa margem tem custo de oportunidade real.
Isso é Risk/Decision Engine, não Meta. O Grupo J foi **realocado** (feature
do Meta v2, pós-calibração real), não desqualificado.

#### C. As 17 decisões travadas

`D-01` regime como feature (condicionada a prova de estabilidade cross-fold)
· `D-02` learner plugável, logística L2 default, LightGBM atrás de guarda,
**CatBoost descartado** · `D-03` Grupo J depois · `D-04`
`y_meta = 1[ret_net > 0]` · `D-05` veta ou dimensiona, **nunca inverte
lado** · `D-06` `p_meta` é filtro, não tamanho · `D-07` sem calibrador no
v1 · `D-08` dois braços de CV · `D-09` seleção posicional · `D-10`
unicidade na subpopulação com grão `(symbol, side)` · `D-11` join exato ·
`D-12` ablation com nulo que replica a busca · `D-13` B07/B08 em 5 camadas ·
`D-14` Gate E0 · `D-15` `tau` persistido · `D-16` purge cross-símbolo
bloqueante · `D-17` reusar `src/models/persistence.py`.

Duas escolhas que merecem registro aqui por contrariarem o cânone ou o
pedido original:

- **CatBoost descartado** apesar de nomeado pelo Manager. O argumento a
  favor era *ordered boosting* contra target leakage em amostra pequena. Mas
  o ganho isolado em função de `n` nunca foi replicado independentemente (os
  revisores do NeurIPS 2018 suspeitaram de tuning assimétrico das
  baselines), e **em CPU o default do CatBoost é `Plain`, não `Ordered`** —
  o mecanismo não vem ligado.
- **AFML §6.6 prefere bagging a boosting em finanças.** Nosso GBM contraria.
  Registrado: se o gate de amostra abrir, `RandomForest` com
  `max_samples = unicidade média` é mais defensável pelo cânone que
  LightGBM. Decisão do Manager quando chegar a hora.

#### D. Auditoria adversarial de 3 flancos — 40 correções

O desenho v1 foi submetido a três auditores independentes (corretude factual
contra o código; rigor estatístico; trade-offs e alternativas), via
`/engineering:architecture` em modo *evaluate a design*. Resultado: **6
CRITICAL, ~20 HIGH**, 95 afirmações verificadas (73 corretas). O changelog
completo v1→v2 está em `§19` do design doc. As quatro que mudaram decisões:

1. **Uma prova de impossibilidade do v1 era FALSA.** O v1 afirmava que não
   existe fold doador simultaneamente OOF e cego, e que cegueira total
   exigiria CV aninhada a ~6× o custo. **Ambas falsas.** A prova tinha dois
   quantificadores escondidos: assumia um doador *global* (quando o
   requisito é por linha) e fixava `|T_s| = 2` silenciosamente (quando é
   escolha, não fato). Com bloco de teste do Meta = 1 grupo, o fold cujo
   teste é `{g,h}` é OOF **e totalmente cego**, e existe sempre —
   `C(6,2) = 15` folds cobrem todos os pares, e as predições já estão em
   disco. **Custo real: zero retreino**; o custo é 1 caminho OOS em vez de 5.
2. **`score_raw` fora do design matrix por argumento falso** — monotônico
   ⇏ colinear; `IsotonicRegression` é *many-to-one* e **destrói**
   informação. Como `tau` é o quantil 98,11% da distribuição calibrada, o
   Meta vive no topo da escada, onde `p_alpha` pode ser literalmente
   constante.
3. **Purge cross-símbolo não é fraco — é ausente.** `assign_time_groups` faz
   `linspace` sobre o `t0` **de cada símbolo**; históricos diferentes ⟹
   fronteiras de grupo em datas diferentes ⟹ uma linha de treino de BTC pode
   ser contemporânea de uma de teste de ETH e o purge nunca a vê. Com ρ
   cross-asset de 0,70–0,83 (`AG-144`), é quase o mesmo evento.
   Vira `AG-151`, pré-requisito bloqueante.
4. **Os gates do v1 não gateavam.** Cinco defeitos somados inclinavam a
   decisão a PASS: nulo sem busca replicada, paths não-independentes tratados
   como replicações, Gate E0 com 50 células e nenhuma regra de agregação
   (literalmente `AG-114`/`AG-122` reproduzido), pass-through contaminando a
   estatística, e nenhum gate contra "só apertar o `tau` do Alpha".

**O padrão da falha, nomeado no §16-R11 do design doc para não repetir:** os
riscos eram identificados com precisão e depois **mitigados por declaração
em vez de mecanismo** — o FLAG que só imprime, a escrita "condicionada" sem
enforcement, o "bit-exato" operacionalizado como "os testes passam". Regra
adotada: toda mitigação aponta para um objeto que levanta, um teste que
falha, ou um campo que o gate lê.

#### E. Correção factual desta rodada de governança (protocolo item 1)

O design doc afirmava, em três versões, que *"não existe
`save_model`/`joblib`/`pickle` em lugar nenhum de `src/`"* e propunha abrir
um AG novo para persistência. **Errado no momento da escrita** — `AG-141`,
`src/models/persistence.py` e `src/io/artifact.py` foram construídos no
**mesmo dia**, em paralelo a este desenho (commits `2866f2e`/`36862eb`,
`§15.16`/`§15.18`). O levantamento foi feito antes desses commits.

Corrigido no design doc §14.4: o Meta **reusa** `src/models/persistence.py`,
nenhum AG de persistência é aberto (seria duplicata de `AG-141`), e o que se
registra é a **dependência** — F5 do Meta depende da integração do `AG-141`
no Alpha, porque um Meta serializado consumindo um Alpha não serializado
continua sendo um sistema meio-serializado.

É exatamente o furo que o item 1 do comando "Atualize governança" (`commits
ANTES de tocar em docs`) existe para prevenir, e desta vez preveniu.

#### F. Status e o que vem antes de qualquer código

**Desenho travado, ZERO linhas implementadas.** O caminho declarado antes de
`meta.py` existir — tudo sobre artefato já em disco, zero treino, zero
`N_lifetime`:

1. `tau_long`/`tau_short` no schema de predições (`AG-150`, reconciliado
   com `AG-162` em 2026-08-23) — 2 colunas cruas, uma por lado; `tau_alpha`
   deixa de ser física e vira coluna derivada no Meta (§15.20-C/-E).
2. Diagnóstico de saturação isotônica (`n_distinct(p_alpha)` na
   subpopulação, massa de empate em `tau`).
3. **Gate E0** — inventário de falsos positivos + separabilidade condicional
   do regime, com regra de agregação declarada e candidato único.

**E0 tem duas execuções distintas e rotuladas:** E0-piloto (sobre o artefato
legado 15m — provisório, não vinculante) e E0-vinculante (sobre o Alpha novo
sob R1/LightGBM, pós-retreino). Falha em ≥2 dos 5 paths ⟹ registro em
`audit/evidence_ledger.yaml` e **o Meta sai do roadmap**.

**Sobre o Alpha legado:** `auc_real_pooled = 0,49776` contra
`auc_permuted_pooled = 0,49998` (baseline B4, 1,6M avaliações),
`permanence_pass: false`. O Manager qualificou, verbatim: *"alpha atual é
obsoleto pois foi desenho de um motor antigo btc only barras casuais time
frame single de 15m"* — confirmado pela ausência da chave `resolution_id` no
relatório. Registrado em `audit/evidence_ledger.yaml` **com a qualificação**,
por ser medição estatística real que não pode desaparecer, e por definir o
que o retreino precisa superar.

#### G. `project_assurance` sobre a v2 — a revisão que a auditoria não substituiu (v3)

A v2 incorporou 40 correções de uma auditoria adversarial e **nunca foi
revisada**. Rodada `project_assurance` (PRINCE2 §6.4, 2 revisores
independentes sem acesso ao raciocínio do produtor, ~110 alegações
`arquivo:linha` re-derivadas): **~102 corretas** — a acurácia factual da v2 se
sustentou —, mas **3 CRITICAL + 4 HIGH** estruturais. Veredito: *"não é base
sólida para implementar"*. A v3 é a correção. Detalhe: §20 do design doc.

**Os três CRITICAL:**

1. **`group_matched` não tinha purge nem embargo.** O braço que a v2
   apresentava como "estritamente melhor, cegueira total" era o **único dos
   dois sem B09**. Motivo verificado no código: `generate_splits` levanta
   `CPCVError` incondicionalmente se `n_test_groups != 2`
   (`src/validation/cpcv.py:544-548`) ⟹ sob `|T_s| = 1` não existe
   `CPCVSplit`, e com ele não existe `train_idx` — o único objeto que carrega
   purge + embargo; e as linhas de treino do Meta ficam no `test_mask` do
   fold doador, excluídas de `train_candidate_mask` (`:565`). A v2 ainda
   fechou a porta para a correção ao declarar que `edges_ms` seria a "única
   mudança em `cpcv.py`". **Removido do caminho crítico**; vira item opcional
   com custo declarado (primitiva de purge nova + regra de doador do lado do
   teste + contabilidade de caminhos refeita).
2. **O Gate E0 não tinha esquema de permutação declarado** — só *que* o
   estimador é reajustado dentro da permutação. O único precedente do repo é
   i.i.d. linha a linha (`src/models/baselines.py:819`); com rótulos
   sobrepostos e regimes que o próprio documento descreve como blocos
   contíguos de calendário, o nulo teria variância governada pelo número de
   **linhas** em vez de **blocos** ⟹ p95 estreito demais ⟹ **o gate que
   decide se o Meta existe seria o mais fácil de passar do documento**.
   Travado: circular-shift por bloco, comprimento = largura de grupo do CPCV,
   **mais validação obrigatória do próprio nulo** (rodar sobre feature sem
   sinal mas com a mesma estrutura de blocos; taxa de PASS ≈ 5%, senão E0 não
   roda).
3. **O nulo A2 replicava 1 de 5 fontes de otimismo**, e a v2 declarava o
   problema resolvido. Enumeração exaustiva das 5, com enforcement por
   **função de busca compartilhada** entre A1 e A2 — uma escolha nova entra
   no nulo automaticamente, sem depender de alguém lembrar.

**Reversão de uma decisão registrada na alínea anterior desta seção:** a v2
concluiu que a cadência de retreino Alpha↔Meta "não vira AG, foi resolvida por
desenho". **Errado.** Acoplar o Meta ao Alpha é restrição de *acoplamento*,
não *cadência* — se o gatilho do Alpha for sequência de perdas, B22 é violado
nos dois. E não existe cadência de retreino de modelo declarada em lugar
nenhum do repo (`grep` por `cadence` em `constants.yaml` devolve só
calibração de barra). **O Alpha tem a mesma lacuna.** Vira `AG-155`,
escalado ao Manager como decisão de escopo.

**AGs abertos pela revisão** — nenhum é gap do documento (corrigidos na v3);
todos são do código/projeto: `AG-153` (não existe primitiva de purge por
bloco arbitrário — todo purge está acoplado à geometria de pares, limita o
espaço de desenho de CV do projeto), `AG-154` (`predictions.parquet` sem
manifesto nem versão — bloqueia `AG-150` de ser mudança segura),
`AG-155` (cadência de retreino), `AG-156` (nulo i.i.d. em B4 — **com a
qualificação de que o viés vai na direção conservadora**, logo o achado do
Alpha legado no `evidence_ledger` não é invalidado, é reforçado).

**O achado que vale registrar como lição de processo:** a v2 diagnosticou o
padrão de falha da v1 com precisão — *"riscos identificados com precisão e
depois mitigados por declaração em vez de mecanismo"* — e **repetiu o padrão
exatamente nas três peças que apresentava como suas maiores conquistas**. Uma
auditoria adversarial genérica elevou muito o nível factual e **não** aplicou
o critério que o próprio documento havia estabelecido às peças que ela mesma
motivou. Foi preciso uma segunda rodada, com skill diferente e mandato
diferente (integração, não qualidade), para pegar isso. **Duas rodadas de
revisão com lentes distintas não foi redundância — foi o que separou um
documento que parecia pronto de um que estava.**

---

### 15.20 Alpha multi-ativo × multi-resolução (LightGBM + GPU) — arquitetura ponta a ponta travada (2026-08-22)

**Origem:** pedido do Manager, verbatim — *"Alpha atual é um legado do motor
antigo BTC only e single time-frame M15, além de ser XGBoost. Seu desafio é
desenhar a arquitetura tecnica ponta a ponta do Alpha multi ativo, multi
time-frame R1, R2 e R3 com LightGBM ou Catboost."* Documento completo:
`docs/alpha_model_design_doc_2026-08-22.md` (v3).

#### A. Três decisões de escopo travadas antes do desenho

1. Só desenho (Fase 4), mesmo padrão do Meta-model v3 — sem implementação.
2. Learner = LightGBM, mantendo `§15.14` (não reaberto; CatBoost descartado).
3. Grão de treino = modelos independentes por (símbolo, resolução) — sem
   pooling cross-ativo em v1, pesquisa AFML (`§8.5`, pooling/stacked feature
   importance) + caso de uso 2026 (arXiv:2505.08180, ganho de R² medido sob
   XGBoost) citada para justificar pooling como via de evolução **gated**
   em `AG-151` fechado, não como decisão silenciosa.

#### B. O achado central — infraestrutura já pronta

Multi-símbolo (5 ativos) e multi-resolução (R1/R2/R3, dollar-bar) **já
estavam prontos em produção** quando o desenho começou — a frente que
faltava de verdade era só o learner. `_BAR_SOURCE_BY_RESOLUTION`
(`src/models/dataset.py:80-84`) mapeia as 3 grades desde `AG-100`/`AG-124`
(trabalho de engenharia concluído no mesmo dia deste desenho, commit
`7924f2c`); regime e features já despacham corretamente via `bar_source`.
Consequência: o redesenho é cirúrgico — trocar o learner, estender o loop
de orquestração de 5 para 15 combinações (função já aceita
`resolution_id`), e corrigir débitos estruturais de schema encontrados pelo
caminho (18 decisões, D-01..D-18).

#### C. Duas rodadas de revisão independente — mesmo padrão do Meta-model v3

**Auditoria adversarial (`/engineering:architecture`, 3 revisores
paralelos — precisão de citação, ataque aos argumentos centrais, lacunas de
completude), v1→v2:** 1 CRITICAL — D-05 (`tau_long`/`tau_short`) não
verificado contra o nome `tau_alpha` que o Meta-model v3 trava
literalmente, o que produziria `LegacyPredictionsError` **permanente** em
produção. 6 IMPORTANT/MODERATE: compatibilidade retroativa de
`predictions.parquet` nunca tratada (5 artefatos reais em disco,
consumidores hardcoded); nenhuma seção de Definition-of-Done/testes
afetados; purge do CPCV medido sempre em wall-clock, sub-protegendo R2/R3;
sweep de hiperparâmetro compartilhado como canal de vazamento cross-símbolo
que `AG-151`/D-02 não cobrem; determinismo bit-exato do LightGBM tratado
como herdado do XGBoost sem verificação (não é — `deterministic=False` é o
default).

**`project_assurance` (PRINCE2 §6.4, foco de integração — não qualidade),
v2→v3:** achou que o problema de `tau_alpha` era maior do que a v2
resolveu. O nome/formato "`tau_alpha`, 1 coluna derivada por seleção de
lado" já estava travado em **mais dois** artefatos que a v2 não tinha visto
— o próprio texto desta seção antes da correção (então alínea F, item 1) e
o campo `status` de `AG-150` — ambos mais próximos da correção que a v3
propõe para o Meta do que da decisão real de D-05. **Não é um patch de 2
documentos, é 3 artefatos de governança que já diziam uma coisa enquanto
D-05 decidia outra — escalado ao Manager (`AG-162`, CRITICAL).**

**[RECONCILIADO 2026-08-23]** D-05 do Alpha PREVALECE como escrito —
`tau_long`/`tau_short` crus (2 colunas). `AG-150` e esta seção são os que
cedem, não o design doc do Alpha. `tau_alpha` deixa de ser física em
`predictions.parquet` e vira coluna DERIVADA dentro do Meta
(`src/models/meta_dataset.py::build_meta_signal_table`, `tau_alpha =
tau_long if side_hat == 1 else tau_short`). Justificativa: o design doc do
Meta v3 já usa exatamente esse padrão — raw-em-2-colunas-no-Alpha,
derivado-por-seleção-de-lado-no-Meta — para `p_alpha`/`score_alpha_raw`
(`docs/meta_model_design_doc_2026-08-22.md` §3.2); estender o mesmo padrão
a `tau_alpha` não introduz mecanismo novo. Custo de migração zero — nem
Alpha nem Meta tinham código real implementado no momento da decisão, sem
artefato legado a migrar. `AG-150`/`AG-162` fechados, ver
`audit/architecture_gaps_log.yaml`. Achado adicional: o design doc citava
`AG-100`/`AG-124`
como "fechados" 3×, mas o status formal de ambos continua `"aberto"`, e
`SPRINT_LOG.md` tem pergunta ainda não respondida sobre se o
reprocessamento cobre features/regime/CPCV — corrigido para refletir
status real (`AG-163`, HIGH). Também achou que o próprio documento estava
não commitado e sem âncora de governança (`AG-161`) — esta seção fecha
essa lacuna.

#### D. GPU — pedido do Manager, aplicado aos dois motores com ressalvas declaradas

*"garanta que Alpha e Meta vai usar GPU"* — para o Alpha, direto (D-18,
`device_type="cuda"`, learner já travado). Para o Meta, o pedido colidia
com uma decisão já travada (D-02 do Meta v3: LightGBM é braço **bloqueado**
por padrão, `MetaLearnerBlockedError` incondicional — default real é
regressão logística L2, porque boosting exige 2-3× mais amostra que
logística pra mesma calibração). Esclarecido com o Manager: GPU configurado
no braço bloqueado para quando/se o gate estatístico abrir, sem desbloquear
nada agora — nota adicionada em `docs/meta_model_design_doc_2026-08-22.md`
§7.2, D-02 do Meta não reaberto. Três ressalvas declaradas no D-18 do
Alpha, não escondidas: pré-requisito de build GPU-enabled via `uv` não
verificado; tensão real com a garantia de reload bit-exato (`deterministic`
do LightGBM é mais forte em CPU que em GPU); payoff de desempenho não
medido (`TBD`, ~230k barras/10 features é porte moderado, não presumido
como vitória automática).

#### E. Status e pendências escaladas ao Manager

**Status: v3, 18 decisões travadas, ZERO linhas implementadas.** Uma
pendência fechada, uma segue aberta com ressalva — escaladas per `§6.5`:

- **`AG-162` (CRITICAL) — [FECHADO 2026-08-23]:** D-05
  (`tau_long`/`tau_short`, 2 colunas cruas) prevalece sobre o que
  `AG-150`/esta seção tinham travado antes (`tau_alpha`, 1 coluna
  derivada). `tau_alpha` vira coluna DERIVADA no Meta
  (`meta_dataset.py::build_meta_signal_table`), mesmo padrão já usado no
  próprio doc do Meta para `p_alpha`/`score_alpha_raw`. Detalhe completo:
  alínea C acima; `audit/architecture_gaps_log.yaml::AG-150`/`AG-162`.
- **`AG-163` (HIGH):** confirmar por escrito o fechamento formal de
  `AG-124`; atualizar `AG-100.status` para `"fechado"`; responder a
  pergunta pendente em `SPRINT_LOG.md` sobre escopo do reprocessamento
  (features/regime/CPCV inclusos ou não — afeta a premissa central da
  alínea B acima).

AGs novos da revisão: `AG-157`-`AG-164`. Bloqueado por: gate "Data Layer
100%" — **[ATUALIZADO 2026-08-23]** dos 3 achados "alto" que travavam o
gate, os 3 fecharam (`AG-138`/`AG-139`/`AG-140`, `§15.25`); `08_SPLIT`
tinha 2 decisões pendentes -- **ambas fechadas agora** (decisão 1
implementada, `§15.27`; decisão 2/`AG-159`, ressalva de MAGNITUDE do
proxy de purge, fechada com constante MEASURED dedicada,
`max_consecutive_bar_window_duration_ms`, mesmo dia -- **[CORRIGIDO
2026-08-23]** esta linha dizia "fechamento formal pendente", estava
desatualizada contra `audit/architecture_gaps_log.yaml::AG-159::status`,
que já dizia "fechado"). Resta só o débito organizacional já aceito de
`06_BARREIRAS` (represado por decisão, não bloqueante) -- ver `§15.4`
pro estado real por estágio antes de tratar o gate como automaticamente
livre (não reconciliado aqui contra os itens `alto` residuais `AG-141`/
`AG-142` do mesmo fan-out original, que podem ou não estar dentro do
escopo formal "01_BARRA..07b_PESOS+08_SPLIT" deste gate -- verificar
antes de consumir orçamento de trial num retreino real).

### 15.20.1 Implementação — código real, D-01 a D-18 (2026-08-23)

**Status muda de "ZERO linhas implementadas" (alínea E) para as 18
decisões codificadas e testadas** — commits `d15ff73` (D-01/03/04/05/07/
08/09/11/12, troca de learner + schema), `321c414` (D-06 parcial/D-13/
D-14), `1c6f1b3` (fecha `AG-160` de fato), `4781920` (D-18, GPU). Nenhum
treino real rodou — o gate "Data Layer 100%" segue fechado (alínea E
acima); tudo abaixo é código, verificado com dado sintético e com o teste
golden pré-existente (que falha deliberadamente, ver "O que NÃO foi
feito" abaixo).

**A. `alpha.py`/`persistence.py` — learner + schema.** `LGBMClassifier`
substitui `XGBClassifier`; `PREDICTIONS_SCHEMA_COLUMNS` de 17 para 21
colunas (`symbol`, `resolution_id`, `tau_long`, `tau_short`); `model_dir`
(`persistence.py`) chaveado também por `(symbol, resolution_id)`, fecha
`AG-158`. Dois bugs reais do próprio design doc corrigidos durante a
implementação (não estavam previstos em D-08): (1) `LGBMClassifier.fit`
sobre `NDArray` puro grava `booster_.feature_name()` como `"Column_N"`
sem `feature_name=` explícito — quebraria `gain_by_column`/HHI
silenciosamente; (2) `feature_importance()` do LightGBM devolve array
DENSO (inclui `gain=0.0`), diferente do dict esparso do XGBoost — sem
filtro explícito, quebraria a garantia "só colunas usadas" que os testes
já exigiam. Um terceiro achado na verificação mecânica (`mypy --strict`):
stubs do LightGBM tipam `predict_proba` como `list`, não `ndarray` —
corrigido com `np.asarray(...)` explícito em `alpha.py` e `baselines.py`
(que reusa `SideModelResult.model`).

**B. D-06 (writer versionado) — PARCIAL, deliberado.**
`write_predictions_versioned` (`pipeline.py`) usa `src.io.artifact.
write_artifact` de verdade — mas achado real: `io/schema.py`/
`io/artifact.py` (ADR-001, `§15.16`) nunca tinham consumidor real até
agora, e `v1` só cobria tipos escalares — quebrava contra `List[Utf8]`
(`features_selecionadas`) e contra `pl.Datetime(time_unit="ms",
time_zone="UTC")` (`t0` — convenção real de TODO artefato do projeto,
não `Int64` nanoseconds como a convenção `*_ts_ns` do docstring de
`io/artifact.py` sugeria). Estendido `_PARAMETRIZED_DTYPE_BY_NAME` pros
dois, testado isolado antes de usar em predições. **NÃO integrado em
`run_layer1_sprint`** — decisão do próprio design doc (§13): cutover real
(trocar writer de produção, regenerar as 15 combinações, atualizar os 2
consumidores reais incondicionais — `fill_reconciliation.py`,
`calibration_diagnostics.py` —, descartar os 5 `predictions.parquet`
legados) acontece "no mesmo PR que ativa o retreino", gate ainda fechado.
`AG-154` fica `status: "parcial"`, não fechado.

**C. D-13/D-14 — orquestração + N_lifetime declarado.**
`run_layer1_sprint_all_combinations` (driver fino, 15 chamadas — 5
símbolos × {R1,R2,R3}) com `report_path`/`run_tag` único por combinação
(fecha `AG-160` de fato — o commit `321c414` já dizia isso, mas o campo
`status` do ledger só foi atualizado em `1c6f1b3`, mesmo furo doc-vs-
código que `AG-123`/`AG-157` catalogam, desta vez cometido pelo próprio
Claude). D-14: custo de `N_lifetime` (15× vs. hoje) declarado na
docstring do driver, decisão de contagem real (15 trials vs. 1 desenho ×
15 mercados) deixada explicitamente para o Manager quando o gate abrir —
não inventada (B23).

**D. D-18 — GPU, confirmado com o usuário.** GPU NVIDIA/CUDA disponível
no ambiente de treino, confirmado por escrito. `device_type` parametrizado
(`fit_side_model`→`run_fold`→`run_all_folds`, default `"cpu"` preserva
todo teste existente sem depender de GPU na máquina/CI) — só
`run_layer1_sprint` (único caller de produção real) tem default `"cuda"`.
Ressalva de determinismo (tensão com D-12) permanece TBD — nenhum treino
real sob GPU rodou nesta sessão pra confirmar se `deterministic=True`
garante bit-exato lá também; saída já nomeada no design doc (§3 D-18) se
não garantir.

**E. Achado fora de escopo, corrigido no caminho — `AG-193`.** Rodar a
suíte completa expôs 3 testes falhando por causa de `AG-032` (commit
`78169df`, ANTERIOR a esta migração, não relacionado a ela):
`monotonic._ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` ficou vazio quando
`E02f_funding_z_expanding` saiu de `T1_FEATURE_IDS`, mas 2 módulos de
análise (`calibration_diagnostics.py`, `faixa1_5_prerequisites.py`)
indexavam o dict direto (sem `.get()`) em vez do acessor seguro já
existente — quebrado silenciosamente desde `78169df`, confirmado
pré-existente via `git stash`. Achado mais sério que os testes: os 2
pontos de entrada MANUAIS reais (`run_and_save_faixa1_report`,
`run_and_save_faixa1_5`) quebrariam com `ColumnNotFoundError` se alguém
rodasse o diagnóstico Faixa 1/1.5 hoje. Corrigido (acessor seguro +
`extra_feature_ids`), registrado como `AG-193`, fechado.

**F. Verificação.** Suíte completa (`-m "not slow and not integration
and not golden"`) — 1781 testes verdes, 5 skips legítimos (2 sobre
artefato real ausente, 1 sobre schema legado pré-migração, esperado, ver
alínea G), zero falhas. `ruff`/`mypy --strict`/`banned_patterns.py`/
`check_constants_referenced.py`/`check_unguarded_ratios.py` limpos em
todo arquivo tocado (violações remanescentes em `src/analysis/*` são
pré-existentes, confirmadas contra o estado do repo antes desta
migração). `AG-157`/`AG-158`/`AG-160` fechados; `AG-154` parcial (alínea
B); `AG-150`/`AG-162` já fechados por sessão anterior (commit `fe943e6`).

**G. O que NÃO foi feito, deliberadamente.** Nenhum treino real (gate
fechado). Teste golden (`tests/golden/test_sprint8_reproducibility.py`)
FALHA (não pula) contra o baseline XGBoost antigo commitado — esperado,
consequência já prevista pelo design doc (§11): só regenera "Fase A2"
LightGBM quando o gate abrir e o retreino real acontecer. 2 testes de
integração (`test_models_alpha.py`) fazem skip graceful contra os 5
`predictions.parquet` legados (schema 17 colunas) em vez de falhar.
Cutover de produção de D-06 (alínea B) explicitamente adiado.

**H. Revisão independente (`project_assurance`, PRINCE2 §6.4).**
Disparada sobre `alpha.py`/`persistence.py`/`pipeline.py` (+ `io/
schema.py`/`baselines.py`/`faixa1_6_reconciliation.py`/
`faixa2_caminho_b.py`) — 3 achados reais fechados (commit `ac3eb5d`).

---

### 15.20.2 D-06 integrado (escopo estreito) + primeiro treino real do Alpha — 4 bugs achados e fechados, sweep completo de 15 combinações (2026-08-23)

**Origem.** Continuação direta de `§15.20.1` — usuário autorizou destravar
o gate "Data Layer 100%" (já fechado, `§15.27`/`§15.28`) e rodar o
primeiro retreino real. Sequência: validação de prontidão → fix de
`AG-199` → integração de D-06 → smoke test → 3 bugs reais achados rodando
contra dado de produção pela primeira vez → sweep completo autorizado
("dispare o retreino completo").

**A. D-06 integrado, escopo ESTREITO (fecha `AG-154` de fato).**
`write_predictions_versioned` investigado antes de integrar: o "cutover
completo" que o achado original descrevia (trocar o writer de produção +
atualizar 2 consumidores incondicionais + descartar 5 `predictions.
parquet` legados) partia de premissa errada — `write_predictions_versioned`
exige `resolution_id: str` não-opcional (só serve o ramo dollar-bar) e os
2 consumidores citados (`fill_reconciliation.py::load_predictions`,
`calibration_diagnostics.py`) não aceitam `symbol`/`resolution_id` —
nunca liam o ramo novo, independente do writer. Escopo real implementado:
`pipeline.py::run_layer1_sprint` chama `write_predictions_versioned`
sempre que `resolution_id is not None` (as 2 variantes, Camada1/Camada0,
`config_hash` distinto via `variant`); ramo legado intocado, zero risco
aos consumidores existentes. Commit `9adf356`. `AG-154` fechado (o campo
`status` do ledger tinha ficado "parcial" mesmo depois do commit dizer
"fecha" — mesmo furo doc-vs-código que `AG-123` cataloga, desta vez pego
na própria varredura de governança que gerou esta seção).

**B. `AG-199` (alto, fechado) — `config_hash` mismatch real em labels R1.**
Confirmado empiricamente (não falso positivo, como o usuário suspeitava
que pudesse ser confundido com o achado de D-06): `ConfigHashMismatchError`
real, labels R1 (mtime 2026-08-17) predatavam `AG-116` (2026-08-20,
`horizon_bars` no payload). Reprocessados os 5 símbolos via
`run_and_write_labels_dollar_bar_parkinson(resolution_id='R1')`.

**C. `AG-200` (alto, fechado) — 2º schema de calibração não reconhecido.**
`_assert_dollar_bar_grade_consistent` (`cpcv.py`) só sabia parsear
`DollarBarCalibration` (schema de janela única); `AG-124` (2026-08-21)
introduziu `WalkforwardCalibrationIdentity` no MESMO arquivo
`_calibration.json` — bloquearia as 15 combinações reais na primeira
chamada de `generate_splits`. Corrigido com tentativa dupla de schema.

**D. `AG-201` (alto, ABERTO) — GPU/CUDA inviável no Windows nativo.**
D-18 (GPU obrigatória em produção) investigado a fundo: CUDA Toolkit
13.3 instalado e funcional (RTX 4060 Ti confirmada via `nvidia-smi`), CMake
+ Visual Studio Build Tools 2022 (2026 falhou — sem integração MSBuild-CUDA
ainda) chegaram a compilar e detectar o compilador CUDA com sucesso.
Bloqueio final, estrutural: LightGBM 4.7.0 exige `NCCL` incondicionalmente
sob `USE_CUDA=ON` (`CMakeLists.txt:243`, sem flag de escape) — NCCL é
biblioteca nativa de Linux, sem build oficial pra Windows (só via WSL2).
Decisão do usuário: treinar em CPU agora, GPU real fica pra projeto de
infraestrutura separado (WSL2), sem prazo definido.

**[CORREÇÃO 2026-08-24, Changelog v3.50] `AG-201` FECHADO** — narrativa
acima preservada como estava no momento do achado (histórico, não
reescrita), mas o status "ABERTO" está desatualizado: `device_type`
default trocado `cuda→cpu` nos 2 entry points reais (`run_layer1_sprint`,
`run_layer1_sprint_all_combinations`, CLI), não é reversão de D-18, é
reconhecer que a decisão não se sustenta neste ambiente até migração
Linux/cloud. Ver `audit/architecture_gaps_log.yaml::AG-201`, Changelog
v3.50.

**[CORREÇÃO 2026-08-29, Changelog v3.57] Migração Linux/cloud ACONTECEU
— GPU real funciona.** "sem prazo definido" (2026-08-24) estava
desatualizado em menos de uma semana: `tools/infra/wsl2_cuda_setup.sh`
provisiona WSL2 Ubuntu-22.04 + CUDA Toolkit 12.6 + NCCL 2.24.3 (pareados
explicitamente — `AG-375` achou que apt não garante o casamento entre os
dois) + LightGBM 4.7.0 recompilado com `USE_CUDA=ON`, confirmado com
treino real (dado sintético e dado real do projeto, Camada0 e Camada1,
`device_type="cuda"`, ambos OK). O bloqueio estrutural descrito acima
(NCCL exige Linux) segue tecnicamente correto — a correção é que "Linux"
não exigia trocar de máquina, só rodar dentro do WSL2 na mesma máquina
Windows. `device_type="cpu"` continua o default de produção (benchmark
CPU-vs-GPU real ainda não executado); `cuda` agora é uma opção que
funciona de verdade, não uma opção teórica. 3 bugs de infra adicionais
achados nesse provisionamento (`AG-375`/`AG-376`/`AG-377`) e 1 bug de
crash do LightGBM CUDA Tree Learner exposto pela busca Optuna
(`AG-378`, bug upstream confirmado `microsoft/LightGBM#6512`) — ver
Changelog v3.57 e Road Map Vivo v2, seção "Alpha — Optuna real substitui
campanha manual + GPU via WSL2".

**E. `AG-202` (médio, sintoma mitigado, causa raiz ABERTA) — `t0` duplicado.**
2 de 223.172 barras de BTCUSDT/R1 (0,0009%) produzem linhas duplicadas em
`mf.data`, rastreado até o join de features/regime dentro de
`build_modeling_frame` (bars/labels limpos antes do join, sujo depois) —
causa raiz exata não localizada. Só detectado porque D-06 (alínea A) foi a
PRIMEIRA vez que `predictions.parquet` passou por validação real de schema
(`primary_key=(t0,fold_id)`) — o writer legado nunca teria pego isto.
Sintoma fechado (`_unique_test_bars` deduplica de verdade, aviso alto se
acontecer), causa raiz recomendada como investigação futura (não bloqueia
produção, taxa ínfima).

**F. Sweep completo — primeiro resultado real do Alpha novo.** 15
combinações (5 símbolos × R1/R2/R3), cada uma treino+backtest completo e
independente (CPU, `n_jobs=-1`). **3 de 15 (20%) passam o gate de
permanência** — ETHUSDT/R1, SOLUSDT/R2, SOLUSDT/R3; SOLUSDT é o único
símbolo com maioria de aprovações (2 de 3 resoluções); BTCUSDT/BNBUSDT/
XRPUSDT não passam em nenhuma resolução. Detalhe completo, limitações da
medição (AUC por combinação não capturado, limiar do gate não é constante
nomeada, `AG-202` não auditado nas outras 14 combinações) e comparação
com a barra do motor legado: `audit/evidence_ledger.yaml::alpha-lightgbm-
sweep-15-combinacoes-2026-08-23`. `N_lifetime` incrementado em +15
(`audit/n_lifetime.yaml`, id 18) — 15 treinos+backtests reais, não 1 passe
de ranking. **Não é decisão de promoção pra produção** — achado misto
registrado, decisão de investigar a causa da divergência por símbolo
(ou aceitar como esperado dado o tamanho pequeno da amostra de paths)
fica com o Manager.

---

### 15.20.3 Análise profunda do Alpha — decomposição de PnL, AUC real, taxa-base com significância, AG-202 causa raiz (com autocorreção), metodologia H0-H6 e estratégia de testes (2026-08-24)

**Origem.** Continuação direta de `§15.20.2` — usuário pediu detalhamento
extensivo do resultado ("ranking de features, quantidade de trades,
taxas de assertividade em horários/períodos/long×short") e depois
aprofundamento explícito ("continuar nessa direção... metodologia
própria ponta a ponta"), seguido de `/engineering:testing-strategy`
aplicado ao achado do dia. Toda a análise abaixo reconstruída dos
artefatos já gravados pelo sweep de `§15.20.2` — **zero retreino, zero
custo de `N_lifetime`** — validada bit-a-bit contra o único relatório
completo sobrevivente (XRPUSDT/R3) antes de aplicar às outras 14.

**A. Ranking de features + decomposição de PnL + AUC real + calibração.**
450 diagnósticos por fold×lado já em disco deram o ranking de features
sem retreino: `E10f_oi_change_z_48` (17,1% do gain) > `C06_vol_ratio_
12_96` (14,8%) > `E27f_cost_atr_ratio` (14,5%, maior variância entre
combinações) > `A05_ret_vol_norm_4` > `B01_rsi_14` > `D06f_taker_
imbalance_z_48` > `A13_dist_ema48_atr` — concentração saudável, HHI
médio ≈0,155. Decomposição de PnL (`src.models.decomposition.decompose`
chamado sobre trades reconstruídos): **63,2% da perda agregada é
direcional, 38,9% execução** — `gate3_directional_positive=False` nas
15 combinações, sem exceção. AUC real (score pré-calibração vs. label,
mesmo filtro `side_subset` do B4 oficial): média 0,509, faixa
0,505-0,513 — validado bit-exato (`auc_long`) contra XRPUSDT/R3.
Calibração (correlação probabilidade×acerto por quintil): média −0,177,
9 de 15 negativas — amostra pequena, reportado como hipótese, não
conclusão fechada. Detalhe: `audit/evidence_ledger.yaml::alpha-lightgbm-
decomposicao-pnl-auc-calibracao-2026-08-24`.

**B. Taxa-base ingênua vs. taxa de acerto real (achado que reenquadra
"win rate ~40%").** O label bruto (sem NENHUM modelo) já tem TP como
classe minoritária (38,7%-41,0%) em TODAS as 15 combinações — a taxa de
acerto medida antes não era tão dramática isoladamente quanto parecia.
O que importa é o delta (Alpha vs. taxa-base), testado com significância
(z, sem correção multiple-testing pras 15 comparações): **7 de 15
significativas** — positivas em BTCUSDT/R1, ETHUSDT/R1, XRPUSDT/R1/R2/R3
(XRPUSDT é o ÚNICO símbolo positivo nas 3 resoluções); negativas em
`SOLUSDT/R3` (z=−2,18) e `BNBUSDT/R3` (z=−2,83) — **seleção adversa
real, não ruído**, confirmada estatisticamente. `BTCUSDT/R3` (pior
percentil do baseline B1 de entrada aleatória, 2,4) NÃO tem delta
significativo — mecanismo DIFERENTE de BNB/SOL-R3, provavelmente
tamanho/variância de trade, não taxa de acerto. Detalhe: `audit/
evidence_ledger.yaml::alpha-basetate-significancia-ag202-2026-08-24`.

**C. `AG-202` — causa raiz confirmada, COM AUTOCORREÇÃO na mesma sessão.**
1ª hipótese (bug em `bars.py::threshold_bars_step`, `carry.base_value`
nunca resetado ao trocar de threshold) foi proposta, mas antes de
qualquer código ser alterado — disciplina de "ler os testes existentes
primeiro" (skill `testing-strategy`) — achado `tests/unit/test_data_
bars.py::test_threshold_bars_drain_sobrevive_a_troca_de_threshold_
entre_periodos` (já existente, não escrito nesta sessão): esse teste
já documenta e testa o EXATO comportamento suspeitado como **correto e
deliberado** ("comportamento real, verificado à mão, não um bug a
esconder", docstring literal). Hipótese descartada, corrigida no mesmo
dia, registrada por transparência (não apagada). **Causa real**:
confirmada no trade lake bruto — 2 trades da Binance caem no mesmo
milissegundo (`transact_time=1738626900274`, `agg_trade_id` 2559075427/
2559075428) exatamente numa fronteira de recalibração; o comportamento
testado/correto de `bars.py` fecha o 1º como barra-fantasma e o 2º abre
a barra seguinte — como os dois compartilham `transact_time`, as barras
adjacentes compartilham `open_time`. `src/models/dataset.py:316`
(`bar_table.join(regime_small, on="_open_time_ms")`) assume implicitamente
que `open_time` identifica barra de forma única — contrato que `bars.py`
nunca garantiu. **O bug real está no consumidor (`dataset.py`), não no
núcleo de barras** — `close_time` permanece único nas 15 combinações,
candidato de chave/tie-break mais seguro. Fix proposto (não aplicado):
tornar o join de regime robusto a `open_time` duplicado — `bars.py`
fica intocado, escopo e custo MENORES que a 1ª hipótese (não precisa
reprocessar o lake de barras dollar, só `build_modeling_frame`). Detalhe
completo, incluindo os 2 addenda (hipótese descartada + correção):
`audit/architecture_gaps_log.yaml::AG-202`.

**[NOVO 2026-08-24, Changelog v3.50] `AG-203` (médio, ABERTO) — duplicata
residual, causa DIFERENTE de `AG-202`.** Achado ao verificar dado real
pós-fix de `AG-202`: 6 de 9 combinações previamente afetadas ficaram
limpas (0 duplicatas), mas 3 continuaram com duplicata residual
(SOLUSDT/R1, BNBUSDT/R1, BNBUSDT/R2 — 20 linhas em 2.070.902 linhas de
label somadas, achado pequeno e contido, não generalizado). Investigado
até confirmar que NÃO é o mesmo bug de `AG-202` (`labels.parquet` já
chega duplicado, upstream do join de regime) — origem exata (`triple_
barrier.py` ou a fonte de bars que ele consome) não isolada nesta
rodada, fora do escopo autorizado (H0 específico). Recomendação
registrada pra quando investigar: checar se `triple_barrier.py` consome
a MESMA fonte de bars que `build_t1_features` e se tem lógica própria de
carregamento/dedup divergente. Detalhe: `audit/architecture_gaps_log.
yaml::AG-203`.

**D. Metodologia de pesquisa proposta (H0-H6) + estratégia de testes.**
7 hipóteses priorizadas por custo pra achar a causa do AUC~0,51 e
melhorar winrate/edge antes da versão final do Alpha: H0 (AG-202,
confirmado) → H1 (seleção adversa BNB/SOL-R3, confirmado, causa exata
aberta) → H2 (XRPUSDT como único sinal positivo consistente, não
iniciado) → H3 (sweep S1 tp_atr_mult×sl_atr_mult, design doc já existe,
"maior lacuna aberta do projeto") → H4 (variar `target_signal_rate`,
depende de H6) → H5 (conjunto de features raso — só 7 de ~92
catalogadas, maior custo) → H6 (integrar `persistence.py`, zero
integração hoje, pré-requisito de H4 e de qualquer AUC sob features
embaralhadas real). Estratégia de testes (skill `testing-strategy`)
aplicada ao H0: plano de 5 camadas (caracterização → unidade → não-
regressão do teste existente → integração nas 15 combinações →
sentinela no `_unique_test_bars`); aos H1-H6: disciplina de teste
mapeada pro DoD já existente do `CLAUDE.md` (feature/modelo/execução),
sem reinventar. Tudo consolidado no artefato **"Alpha — Base de
Pesquisa"** (reestruturado em 2 abas: Retreino = resultado do gate;
Calibrações = investigação viva, atualizada a cada rodada até a versão
final).

---

### 15.21 Motor multi-timeframe R1/R2/R3 — mapa de dívida técnica BTC/M15 residual, Grupo 1+2 implementados (2026-08-22)

**Origem:** sweep de 10 agentes paralelos varrendo `src/` inteiro (130
arquivos) atrás de código que ainda travava em BTC-only/M15 quando deveria
ser multi-ativo/multi-resolução (dollar-bar R1/R2/R3) — 10 achados reais, 3
já tinham rastro em prosa não-formalizada no Plano Mestre, 7 genuinamente
ausentes de qualquer documento do projeto. Trabalho registrado como
`AG-165`–`AG-179` (`audit/architecture_gaps_log.yaml`).

#### A. Classificação — 3 grupos por materialidade e pré-requisito

1. **Grupo 1 — vira canônico com esforço pequeno, sem pré-requisito
   externo:** `src/execution/fill_simulator.py` (tick_size/bar_ms),
   `src/models/_paths.py`+`src/regime/_paths.py` (resolution_id ausente),
   `src/models/dataset.py`+`src/labels/fill_model.py` (prosa
   dessincronizada). **Implementado nesta rodada.**
2. **Grupo 2 — código pode virar canônico, valor real depende de algo fora
   de controle imediato:** `src/data/validate.py` (código generalizado
   agora; dado nativo 15m/1h continua ausente, decisão de custo/escopo
   separada) — **implementado**. `src/features/registry.yaml` — **NÃO
   tocado**, freeze ativo (`AG-126`, aguarda `V41-6→V41-5→M4` fechar por
   completo; só M4 fechou até agora).
3. **Grupo 3 — não deveria virar "canônico de produção", categoria
   diferente por desenho:** `src/analysis/faixa1_7_edge_or_beta.py` (fora
   da hierarquia de camadas por CLAUDE.md, investigação arquivada) — **NÃO
   implementado**, só achado registrado (`AG-179`).

Achados adicionais fora dos 10 originais, mapeados em desenho profundo
(camada, uso offline/live, governança, arquitetura ponta a ponta):
`src/regime/stress.py`/`classifier.py` (`AG-177`, fechado por D-01,
commit `6902352`, ver `§15.21.2`) e o purge do CPCV em `pipeline.py:427`
(`AG-178`, duplicata confirmada de `AG-159`, que segue aberto — ver
`§15.27`).

#### B. Implementação (commit `72e02c7`) — validada por 3 auditores independentes

Fan-out `audit_engineering` (3 agentes paralelos, sem contato com o
raciocínio da implementação) achou e a mesma rodada corrigiu **2 CRITICAL
reais** que a implementação original não previu:

- **`AG-170`:** `load_filters_asof` sem tratamento crashava a JANELA
  DEFAULT INTEIRA de `simulate_window()` — único snapshot de `exchangeInfo`
  em disco é de 2026-08-08, inteiramente posterior à janela histórica do
  módulo (2023-05-16..2024-03-30). Corrigido replicando
  `historical_filters_fallback` (opt-in explícito, B01), mesmo padrão já
  provado em `triple_barrier._resolve_filters_cached`.
- **`AG-171`:** `resolution_id` fora de BTCUSDT/R1 crashava com
  `FileNotFoundError` sem contexto (só BTC tem `dollar_bars_r{1,2,3}/` no
  disco) — mensagem reescrita, comportamento de falhar alto preservado.

Mais 1 HIGH (`AG-172`, zero medido vs. nunca medido conflados) e 1 MEDIUM
(`AG-173`, teste ponta-a-ponta cobria só metade dos 4 call sites de
`pipeline.py`) corrigidos no mesmo commit. 2 achados HIGH/MEDIUM
pré-existentes em `validate_resampled_bars` (`AG-174`, `AG-175`) foram
descobertos pela auditoria mas **não corrigidos** — fora do escopo do
achado original (`validate.py` só generalizou o CLI, não tocou a função
de validação em si).

#### C. Verificação

1682 testes (suíte completa, `not slow`/`not integration`) verdes, mesmos
4 skips pré-existentes, sem regressão. `lint-imports` 7/7 contratos
mantidos (3 imports novos: `models`/`regime → src.data.build_dollar_bars`,
`execution → src.exchange.filters`, nenhum viola a hierarquia real de
camadas). `ruff`/`mypy`/`banned_patterns.py`/`check_constants_referenced.py`/
`check_unguarded_ratios.py` limpos — as 3 divisões sem guarda já
existentes em `fill_simulator.py` são pré-existentes, confirmadas via
`git show HEAD`, não introduzidas por este trabalho.

#### D. Pendências explícitas, não esquecidas

- `AG-174`/`AG-175` (`validate_resampled_bars` fingia "PASS" mesmo sem
  checar nada de fato) — fechados, ver `§15.21.3`-A, commit `d44c7f9`.
- `AG-176` (4 cópias independentes da mesma guarda `resolution_id` em 4
  pacotes `_paths.py`) — fechado via guarda mecânica
  (`check_resolution_id_guard_parity.py`, opção B: duplicação aceita),
  ver `§15.21.3`-B, commit `d44c7f9`.
- `AG-179` (`faixa1_7_edge_or_beta.py`, docstring de quebra incompleta) —
  aberto, baixa prioridade, fora do escopo de produção por desenho. Ainda
  correto, não fechado por nenhuma das rodadas subsequentes.

### 15.21.1 `docs/regime_feature_engine_design_doc_2026-08-23.md` — v1→v3, achado crítico corrigido antes da implementação (2026-08-23)

**Origem:** o documento citado em `§15.21`-D como referência primária de
`AG-177` (`stress.py`/`classifier.py` cegos a `bar_source`) passou pelo
mesmo processo de revisão em duas camadas já usado pro Alpha (`§15.20`):
auditoria adversarial (3 revisores paralelos, sem acesso ao raciocínio de
quem escreveu) seguida de `project_assurance` (PRINCE2 §6.4, revisor
independente). Zero linhas de código implementadas — Fase 4, só desenho.

**A. Achado mais importante — `project_assurance` pegou um bug ANTES dele
existir.** A correção proposta na v1/v2 pro gatilho S6 (`stress.
s06_bar_gap`, cego a `bar_source` desde a Fase 3 da migração dollar-bar,
2026-08-17) portava a técnica de `hmm_gap_check.check_bars_gap_before_hmm`
(já ratificada por `AG-132`) sem adaptação: mediana/MAD calculadas sobre a
SÉRIE INTEIRA — correto lá (diagnóstico único, não-causal por natureza),
mas uma nova instância de **B02** se plugada como estava numa função
por-barra dentro de `compute_stress_triggers → _run_state_machine →
regime[t]`, que viola o contrato causal explícito do `RegimeClassifier`
Protocol ("barra t usa apenas índices < t"). Corrigido na v3: computação
EXPANSIVA (só gaps estritamente anteriores a cada barra), mesma disciplina
já usada por `expanding_percentile_rank_strict` no mesmo módulo. Nenhum
código chegou a ser escrito com o defeito — achado de desenho, não de
implementação, mas registrado com a mesma disciplina de um achado real
(`audit/architecture_gaps_log.yaml::AG-177`, addendum v3).

**B. Escopo de `AG-159` (purge do CPCV) ampliado — 2 call sites, não 1.**
`src/validation/leakage.py:792` (suíte de vazamento, testes 6/7/12) chama
a mesma função (`compute_max_feature_lookback_ms`) que `pipeline.py:427`
— corrigir só um dos dois deixaria a suíte de vazamento reportando PASS
falso sob R2/R3 enquanto o treino real já usaria purge diferente. Achado
por completude na auditoria adversarial, incorporado ao desenho (`AG-159`,
addendum v3).

**C. `regime` tem um consumidor de produção real, não só diagnóstico —
correção de escopo.** v1/v2 caracterizavam `regime` como "hoje só filtro/
análise" pra fins da pergunta "ainda é necessário sob um eventual swap pro
HMM?" (§11 do design doc). `project_assurance` confirmou por leitura de
código: `src/models/environments.py::assign_environments` →
`src/models/monotonic.py::screen_monotone_constraints` já consome `regime`
em produção real, via `pipeline.py::run_layer1_sprint`, pra derivar
`monotone_constraints` do Alpha — achado relacionado mas distinto do
vazamento de vocabulário já registrado em `AG-088` (esse é sobre
ATRIBUIÇÃO de barra a regime mudar sob a correção de S6, não sobre
incompatibilidade de vocabulário). Consequência prática: a correção de S6
(item A) pode mudar `monotone_constraints` derivadas em qualquer treino
real sob R2/R3, não só nos 2 relatórios M4 já publicados que `AG-177`
cita — comportamento CORRIGIDO, não um novo bug, mas recomendação de um
teste de estabilidade dedicado antes do primeiro treino real sob essas
resoluções pós-fix.

**D. Um gap genuinamente novo — D-04, histerese em contagem de barra.**
`regime_confirmation_bars`/`regime_stress_exit_confirmation_bars`/
`min_warmup_bars` são contagens de barra amarradas implicitamente a
relógio, mesma classe estrutural de `AG-030`, mas nunca registradas como
tal — achado prévio real (`docs/refactor_dollar_bar_canonico.md:206-207`,
2026-08-16) nunca virou entrada no ledger até esta rodada. Registrado como
`AG-180`; não resolvido (B23 — sem medição de equivalente nativo sob
dollar-bar, nenhuma conversão numérica é inventada).

**E. Status e pendências.** AGs desta rodada: addenda em `AG-159`,
`AG-088`, `AG-177`, `AG-163`, `AG-179`; nova entrada `AG-180`. Nenhuma
decisão do Manager tomada nesta seção — apenas o desenho evoluiu e as
correções foram registradas. Pendências que seguem do design doc: política
de features `expanding` no conjunto T1 ativo (pré-requisito de `AG-159`
ter efeito prático); sanity check de magnitude do purge; destino dos 2
relatórios M4 já publicados sob o S6 hoje incorreto; teste de estabilidade
de `monotone_constraints` (item C). Road Map Vivo **não republicado nesta
rodada** — atualização é de materialidade baixa (o status "desenhado, não
implementado" de `AG-177` não muda) frente a uma republicação extensa e
recente da mesma sessão paralela no mesmo dia; mesma disciplina já
registrada no próprio artefato ("Nota de transparência — sessões
concorrentes").

---

### 15.21.2 D-01/D-02 implementados — S6 dollar-bar causal + purge CPCV resolution-aware (2026-08-23)

**Origem:** implementação do desenho travado em `§15.21.1` (v3 do design
doc), commit `6902352`. Sequência: implementação → revisão independente
(`project_assurance`, 2 agentes paralelos, um por decisão de desenho) →
1 achado real corrigido antes do commit → testes (1695 passed, 0 failed) →
governança.

**A. D-01 — S6 dollar-bar-aware, causal/expansiva (fecha `AG-177`).**
`src/regime/stress.py` ganhou `s06_bar_gap_dollar` — mediana/MAD
calculadas via `pl.Series.rolling_median(window_size=len(série),
min_samples=1)` deslocada em 1 posição (janela ≥ comprimento total se
comporta como expansiva por construção — reusa a implementação nativa do
Polars em vez de estrutura de dados customizada, técnica não prevista
literalmente no design doc mas que satisfaz a mesma exigência de
causalidade da v3 com custo O(n log n), não O(n²)). `StressInputs` ganhou
`bar_source`/`close_time_ms`; `compute_stress_triggers` valida fail-fast
(`ValueError`) e despacha S6 pelo `bar_source`. `QuantileRegimeClassifier`/
`build_regimes` propagam `bar_source` ponta a ponta — antes desta mudança
o parâmetro chegava até `build_t1_features` mas nunca ia além.

**B. D-02 — purge do CPCV resolution-aware (fecha o componente de UNIDADE
de `AG-159`).** `compute_max_feature_lookback_ms` ganhou `resolution_id` —
sob dollar-bar usa `label_prefetch_p99_bar_duration_ms` em vez de
`step_ms(tf)`. Os 2 call sites (`pipeline.py:427`, `leakage.py:792`)
mudaram na mesma unidade de trabalho, como `AG-159` exigia.

**C. 1 achado real da revisão independente, corrigido antes do commit —
critério de S6 era bilateral, deveria ser unilateral (`AG-183`).**
`s06_bar_gap_dollar`, como implementada inicialmente, disparava tanto em
gap MAIOR quanto MENOR que o típico (`abs(modified_z) > threshold`) —
divergente do precedente citado (`hmm_gap_check.py`, unilateral) e
semanticamente errado: S6 detecta AUSÊNCIA de barra, um intervalo
anomalamente curto é o oposto disso (atividade densa, não problema de
dado). Cenário de falha real que o revisor identificou: uma rajada de
liquidez sob dollar-bar dispararia stress (R5, `tradeable=False`) sem
motivo, alterando `monotone_constraints` do Alpha via a cadeia
`environments.py`→`monotonic.py`→`alpha.py::fit_side_model` (confirmada
como consumidor de produção real pela revisão, não só análise). Corrigido
pra unilateral antes do commit — nenhum treino real rodou sob o
comportamento incorreto.

**D. Achados menores, também corrigidos no mesmo ciclo.** `AG-181`
(faltava teste provando que `assert_no_expanding_lookback_in_active_set`
dispara primeiro mesmo com `resolution_id` setado, sob o conjunto ativo
REAL — cobertura fechada). `AG-182` (docstring de
`compute_max_feature_lookback_ms` overclaimava "unidade correta" sem
qualificar que a ressalva de MAGNITUDE do proxy p99 segue aberta —
corrigido). Um bug pré-existente de fixture (`tests/unit/
test_regime_build.py::_make_synthetic_regime_features`, faltava coluna
`close_time`) também foi corrigido — não era bug de produção, a fixture
sintética é que estava incompleta frente ao novo contrato de `classify()`.

**E. `AG-159` — fechado só o componente de UNIDADE nesta rodada, não a
entrada inteira.** [FECHADO 2026-08-23, ver `§15.27`] A ressalva de
MAGNITUDE fechou de vez com uma constante dedicada MEASURED
(`max_consecutive_bar_window_duration_ms`), substituindo o
reaproveitamento do proxy de prefetch — `AG-159` está `status:
"fechado"` no ledger hoje.

**F. O que fica de fora, como previsto.** `AG-180` (D-04, histerese em
contagem de barra) e §11 do design doc (caminho de troca pro HMM)
continuam abertos, sem código novo — decisão explícita, não esquecimento.

**G. Verificação.** `1695 passed, 4 skipped, 0 failed` (`-m "not slow and
not integration"`, suíte completa). `ruff`/`mypy`/`banned_patterns.py`/
`check_constants_referenced.py`/`check_unguarded_ratios.py` limpos nos
arquivos tocados. Nenhuma constante nova em `constants.yaml` (reuso de
`label_prefetch_p99_bar_duration_ms`, já `MEASURED`).

---

### 15.21.3 Fecha `AG-174`/`175`/`176`, entrega script de medição para `AG-180` (2026-08-23)

**Origem:** pedido direto do Manager, resposta a "o que falta pra esses 5
pontos fecharem?" sobre os achados residuais do mapa de dívida técnica
(`§15.21`). Decisão por item: `AG-180` = medir; `AG-174`/`AG-175` =
desenhar checagem real + testes (com pesquisa de metodologia); `AG-176` =
opção B (aceitar duplicação, guarda mecânica); `§11`/ressalva de
magnitude de `AG-159` = próxima sessão.

**A. `AG-174`/`AG-175` — `validate_resampled_bars` finge PASS, fechado.**
Causa raiz: `missing_bars`/`duplicates`/`invalid_rows`/`gap_
classification` eram literais hardcoded em `0`, `gate`/`quality_score`
nunca refletiam defeito real — diferente de toda outra função `validate_*`
do mesmo arquivo. Correção: `bars_{timeframe}` (saída de `resample_
klines`) tem a MESMA forma que `klines_1m` (OHLCV + grade de relógio
fixa) — schemas `BARS_15M`/`BARS_30M`/`BARS_1H` registrados
(`src/data/schemas.py`, `grid_step_ms` derivado de `resample.step_ms`,
não duplicado — mesma fonte de verdade que `resample_klines` já usa,
evita a classe de bug de TF hardcoded já vista 3× no repo, `AG-004`/
`AG-005`/`AG-017`), e `validate_resampled_bars` passou a reusar
`validate_klines_like` por inteiro — os mesmos 12 checks reais rodam,
com o check 16 (paridade cross-source, específico de dado resampled)
sobreposto por cima. 11 testes novos.

**B. `AG-176` — guarda `resolution_id` duplicada em 4 pacotes, opção B
aplicada.** Decisão do Manager: aceitar a duplicação (dentro da convenção
já documentada do repo), só adicionar verificação mecânica. `tools/lint/
check_resolution_id_guard_parity.py` — varre `**/_paths.py` via AST,
confirma que toda guarda contra `CALIBRATION_TF_BY_RESOLUTION` levanta
`ValueError` e tem a MESMA forma de condição em todo site (mesmo
espírito de `check_unguarded_ratios.py`). Rodado contra o repo real:
achou exatamente os 4 sites conhecidos (`models`/`regime`/`labels`/
`validation`), todos consistentes. 15 testes, incluindo 1 de integração
que trava esse estado (4 sites, 1 forma) como regressão.

**C. `AG-180` — histerese do Regime Engine sob dollar-bar, medição
entregue E rodada, resultado real medido, fórmula ainda não decidida.**
**[CORREÇÃO 2026-08-23 — esta seção citava o script como "ainda não
rodado" apesar do commit que a escreveu já registrar o resultado real no
ledger (`audit/architecture_gaps_log.yaml::AG-180::addendum_resultado_
medido_2026-08-23`) — texto desta alínea C corrigido pra bater com o que
já estava commitado.]** `tools/diagnostics/measure_regime_hysteresis_
bar_window_duration.py` mede a duração real de janelas de N barras
CONSECUTIVAS (não percentil de 1 barra extrapolado — barras rápidas se
agrupam em rajada, extrapolação assumiria independência que não está
confirmada), pros 3 N's que a histerese usa hoje
(`regime_confirmation_bars`/`regime_stress_exit_confirmation_bars`/
`min_warmup_bars`, lidos de `constants.yaml`, nunca hardcoded), por
símbolo×resolução, sobre o dado já persistido. Rodado pelo Manager —
`experiments/regime_hysteresis_bar_window_duration.json` (45/45
combinações, 0 skipped). Achado real: pra `min_warmup_bars=200`, a
MEDIANA da janela real diverge sistematicamente do equivalente sob 15m
(50h) — R1 fica próximo (~45-49h, 90-98% do valor sob 15m), R2 sai ~2×
maior (~95-104h), R3 ~4× maior (~202-209h) — warmup fica MAIS longo em
resolução mais grosseira, não mais curto como a suspeita original isolada
de `docs/refactor_dollar_bar_canonico.md` sugeria. As duas coisas
coexistem: no caso TÍPICO (mediana), a janela cresce com a resolução; no
caso de RAJADA (pior caso p1), janelas continuam curtas (25min-2h,
dependendo do símbolo — XRPUSDT consistentemente o mais curto).
**PENDENTE ainda é só a decisão de fórmula de conversão** (B20/B23 — não
inventada aqui, medição só descarta "sempre mais curto"/"sempre mais
longo" como descrição completa). `AG-180` permanece `aberto` até essa
decisão do Manager.

**D. Achado real durante a implementação, corrigido antes do commit.**
`BARS_15M`/`BARS_30M`/`BARS_1H` foram definidos em `schemas.py` mas
esquecidos do dict `REGISTRY` — os 8 testes novos de `validate_
resampled_bars` pegaram isso na primeira rodada (`KeyError` em toda
chamada), corrigido antes de qualquer commit.

**E. Sessão paralela ativa detectada durante o trabalho.** `git status`
revelou edições concorrentes em `CLAUDE.md` + `src/analysis/
attribution.py`/`faixa1_5_prerequisites.py`/`faixa2_caminho_b.py` +
`src/labels/triple_barrier.py` + `src/models/baselines.py`/`hhi.py`/
`pipeline.py`/`src/execution/fill_simulator.py` — princípio novo "Núcleo
funcional, casca imperativa" (`docs/nucleo_casca_design_doc_2026-08-23.md`).
Nada tocado; confirmado sem conflito com este trabalho (diff de
`pipeline.py` não se sobrepõe).

**F. Verificação.** `1732 passed, 4 skipped, 0 failed` (`-m "not slow and
not integration"`, suíte completa). `ruff`/`mypy`/`banned_patterns.py`/
`check_constants_referenced.py`/`check_unguarded_ratios.py` limpos nos
arquivos tocados. Commit `d44c7f9`; governança nesta mesma rodada.

---

### 15.21.4 D-04 (`AG-180`) fechado — piso de tempo real híbrido na histerese do Regime Engine (2026-08-23)

**Origem:** decisão do Manager sobre os 2 cenários que a medição real de
`AG-180` (§15.21.3) deixou em aberto — pedido explícito de recomendação
técnica, seguido de autorização pra desenhar e aplicar.

**A. Recomendação apresentada e autorizada — NÃO uma resposta única pras
3 constantes.** `min_warmup_bars=200`, `regime_confirmation_bars=2` e
`regime_stress_exit_confirmation_bars=4` protegem coisas diferentes, com
proveniências diferentes (`constants.yaml`):

- **`min_warmup_bars` — mantido em contagem de barra pura.** A fórmula
  que o originou (`DERIVED`: `max` lookback fixo de qualquer feature T1/
  T2 + convergência de suavização exponencial, ~3 meias-vidas além do
  maior span EMA/Wilder ativo) é nativamente em unidade de BARRA — as
  features que protege (C06, janela de 96 barras; A13, EMA de 48 barras)
  operam em contagem de barra, não em tempo. Manter fixo é consistente
  com o que está sendo protegido; o efeito colateral medido (mais tempo
  real de warmup sob R2/R3 — mediana ~2×/~4× o equivalente de 15m,
  §15.21.3) é o lado CONSERVADOR do erro, não o arriscado, dado o perfil
  de risco do motor (capital pequeno, ainda validando infraestrutura).
- **`regime_confirmation_bars`/`regime_stress_exit_confirmation_bars` —
  migradas pra piso híbrido.** Proveniência `LITERATURE` (PRD §4.5,
  "mudança de regime só é efetivada após 2 barras consecutivas"),
  escrito num mundo só-15m — a intenção real por trás de "N barras
  consecutivas" é confirmação de mercado por um intervalo real de
  relógio, não N observações discretas independente de quanto tempo
  isso leva sob dollar-bar. O dado medido (§15.21.3, p1 de
  `min_warmup_bars`) já mostrava o risco concreto: mantendo só contagem
  de barra, uma rajada de liquidez confirmaria a troca de regime em
  minutos — exatamente no momento de MAIOR incerteza do mercado, o
  oposto do que um filtro de ruído deveria fazer.

**B. Implementação (commit `3c3ed14`).** `RegimeThresholds`
(`src/regime/classifier.py`) ganhou 2 properties —
`confirmation_min_real_ms`/`stress_exit_confirmation_min_real_ms`,
`(N_barras - 1) * step_ms("15m")`. **Não** `N_barras * step_ms(...)`: N
barras consecutivas cobrem exatamente `N-1` intervalos de `open_time` a
`open_time`, não N — essa é a forma matematicamente exata que reduz a
condição híbrida a BIT-EXATA sob `bar_source="time_15m"` (grade fixa de
relógio: a barra que confirma por contagem pura sempre satisfaz a
igualdade exata `open_time[confirma] - open_time[primeira_pendente] ==
(N-1)*step_ms("15m")`). Consequência: `regime_confirmation_bars=2` →
piso de 15min reais; `regime_stress_exit_confirmation_bars=4` → piso de
45min reais (correção de precisão sobre a conversa que motivou a
decisão, que citou "~30min"/"~1h" de cabeça — a conta exata usa `N-1`,
não `N`). `_run_state_machine` ganhou parâmetro `open_time_ms`; a
confirmação de troca de eixo (tendência/volatilidade/saída de stress)
agora exige `pending >= N_barras` **E** `tempo_real_decorrido >=
piso_ms` — o mais restritivo dos dois, nos 3 eixos. `min_warmup_bars`
não foi alterado (segue índice puro, como já era).

**C. Verificação.** 11 testes novos: bit-exatidão sob grade de 15m
(regressão direta contra o comportamento antigo), burst de barras
rápidas (confirmação atrasada pelo piso mesmo com contagem de barra já
satisfeita), barras lentas (piso nunca atrasa além do que a contagem de
barra já exigia — sem regressão de sensibilidade quando dollar-bar
acontece ser mais devagar que 15m), equivalente pro eixo de saída de
stress. `1741 passed, 0 failed` (suíte completa, confirmado
independentemente pelo Manager). Confirmado que os 3 commits da sessão
paralela ativa (`d0a0764`/`db62daf`/`aae6bbc`, "núcleo funcional, casca
imperativa", §15.22 abaixo) não tocam `src/regime/classifier.py` nem seu
teste — sem conflito.

**D. `AG-180` fechado**, `resolved_by_commit: 3c3ed14`. Fecha o item 4
dos 5 pontos que motivaram esta sequência de sessões (medir → desenhar →
autorizar → aplicar). Restam represados pra próxima sessão: ressalva de
magnitude do proxy p99 em `AG-159`, e §11 do design doc
(`docs/regime_feature_engine_design_doc_2026-08-23.md`, caminho
legado→HMM).

---

### 15.22 Núcleo funcional, casca imperativa — princípio formalizado, 5 violações reais fechadas (2026-08-23)

**Origem:** `docs/nucleo-casca.html` (documento externo trazido pelo
Manager) validado via `/engineering:system-design` — cita Bernhardt 2012
(*Functional Core, Imperative Shell*), Cockburn 2005 (Hexagonal
Architecture) e Sculley et al. 2015 NeurIPS (*training-serving skew*)
como base teórica; NautilusTrader como prova de existência no domínio
quant. Investigação de código (3 agentes paralelos) achou que o padrão
**já era a norma dominante do repo** (~25+ módulos, `data/bars.py` como
padrão-ouro), nunca formalizado nos documentos canônicos — não era
decisão de adotar algo novo, era fechar doc-drift + as violações reais
encontradas. Desenho completo: `docs/nucleo_casca_design_doc_
2026-08-23.md`.

**A. Formalização.** Nova seção em `CLAUDE.md` ("Núcleo funcional, casca
imperativa") — vocabulário fixado (núcleo = zero IO; casca/"ponto de
entrada com IO" = camada de resolução+delegação), 2 idiomas sancionados
(A — recompute sobre prefixo crescente, default; B — carry/step/finish,
`data/bars.py`), mais um 3º padrão aceito achado pelo `project_assurance`
durante a implementação: **correção-relâmpago via ponto de injeção**
(parâmetro `Mapping | None = None` que substitui IO por lookup em memória
numa função já grande demais pra separar com segurança) — DoD de "Código
de modelo"/"Código de execução" ampliado.

**B. 5 violações reais fechadas + 1 achado extra do `project_assurance`
(6 no total).**

1. `src/labels/triple_barrier.py::build_labels_with_stats` — parâmetro
   `filters_by_date`, elimina IO do laço principal de cálculo de
   barreira. 2 testes novos.
2. `src/analysis/faixa2_caminho_b.py::run_fase2_e1` — split em
   `compute_fase2_e1` (núcleo puro) + `run_fase2_e1` (casca IO). **Sem
   teste sintético completo** — reconstruir fixtures pras 18 células
   (`CPCVSplit`, `predictions`, 4 regimes) sem poder rodar pytest tornava
   o risco de teste sutilmente quebrado maior que o valor; registrado
   como item de acompanhamento, não escondido.
3. `src/analysis/faixa1_5_prerequisites.py::run_faixa1_5` — parâmetro
   `hhi_df`, elimina IO invisível (`_hhi_by_fold_side()` chamada sem
   argumento, fora da assinatura). 2 testes de plumbing via stub.
4. `src/analysis/attribution.py::_aggregate_side` — split em
   `_load_payloads` (IO) + `_aggregate_payloads` (núcleo puro). 1 teste
   que bloqueia leitura de disco ativamente.
5. `src/models/pipeline.py` — 2 fórmulas de decisão inline (tamanho de
   amostra B1, gates 3.4) viram funções nomeadas testáveis
   (`baselines.b1_sample_size`, `hhi.gate3_4_passes`/
   `gate3_4_max_share_passes`). 7 testes novos.
6. **Achado extra do `project_assurance` (HIGH, não estava nas 5
   originais):** `src/execution/fill_simulator.py::_resolve_tick_size_
   cached` — mesma classe de entrelaçamento IO+cálculo, dentro do laço
   principal de `simulate_window`. Mesma correção (`tick_size_by_date`),
   2 testes novos.

**C. Revisão independente (`project_assurance`, obrigatória em
`src/labels/`).** Achados reais, nenhum CRITICAL: (1) descrição do
produtor overclaimava "fecha uma violação arquitetural" quando o padrão
entregue (item 1 acima) é o 3º idioma — injeção, não núcleo separado de
verdade — corrigido na própria redação do princípio (§A); (2) achado HIGH
extra — `fill_simulator.py`, item 6 acima, corrigido antes desta seção;
(3) bug real no fixture de teste (`_with_horizon_coverage` usava a data
errada, funcionava por coincidência de magnitude, não por desenho) —
corrigido; (4) nenhum caller de produção passa os novos parâmetros
opcionais hoje — comportamento de produção 100% inalterado, só a
testabilidade muda; achados MEDIUM de comunicação/rastreabilidade
(governança pendente, teste de regressão bit-exata) — este item, e os
testes de integração (7 passed, dado real de `triple_barrier.py`
confirmando bit-exatidão do caminho default), fecham ambos.

**D. Verificação.** `1734 passed, 4 skipped, 0 failed` (`-m "not slow and
not integration"`) + `7 passed` (testes de integração dos 4 arquivos com
dado real). `ruff`/`mypy`/`banned_patterns.py`/`check_constants_
referenced.py`/`check_unguarded_ratios.py` limpos nos 8 arquivos
tocados — achados pré-existentes de linters cross-checados contra o
arquivo original (`git stash`) e confirmados não-introduzidos por este
trabalho.

**E. Pendências explícitas, não esquecidas.**

- Teste sintético completo pra `compute_fase2_e1` (item B.2) — deferido,
  risco > valor sem poder rodar pytest iterativamente.
- Caso de borda `filters_by_date`/`tick_size_by_date` PARCIAL (cobre só
  algumas datas, não todas) — comportamento correto por leitura de
  código (`KeyError` fail-fast), não coberto por teste dedicado.
- Nenhum caller de produção usa os 3 novos parâmetros de injeção hoje —
  são pontos de teste, não mudança de comportamento real.

---

### 15.23 `feature_a13_ema_window` — conversão clock↔bar-count aplicada em código, achados irmãos confirmados por pesquisa de literatura (2026-08-23)

**A. Origem.** `/feature-dev` sobre a arquitetura de `src/features/`/
`src/labels/triple_barrier.py` (hipótese do Manager: "Feature Engine
preso ao motor antigo BTC-only/15m-only, impacta Alpha/Meta-model
diretamente"). Exploração confirmou a hipótese SÓ parcialmente:
`triple_barrier.py` já estava bem desenhado (4 correções documentadas,
`AG-005`/`AG-031`/`AG-042`/`AG-116`); o gap real estava em
`src/features/` — `AG-043` (2026-08-16) já tinha classificado
`feature_a13_ema_window` como `scaling_invariant: clock` (a única das 8
janelas), mas NENHUM código lia essa tag nem aplicava conversão.

**B. Correção de rumo, não escondida.** As duas primeiras propostas de
arquitetura (espelhar `LabelConfig` da `triple_barrier.py`, ou uma
versão minimalista equivalente) assumiam, sem reler `AG-043` a fundo,
que A13 deveria ser RECLASSIFICADO pra `bar_count` — baseado em pesquisa
de literatura mostrando que indicadores técnicos genéricos sobre barras
de informação (dollar/volume bars) devem manter contagem de barra fixa
(López de Prado 2018; Grądzki/Wójcik/Lessmann, *Financial Innovation*
2025, mesmo desenho deste repo: cripto + dollar/volume bars +
triple-barrier). Releitura completa de `AG-043` revelou que essa
conclusão contradizia uma decisão JÁ TOMADA e JÁ JUSTIFICADA
especificamente pra A13 (2026-08-15/16): seu span é deliberadamente
ancorado ao horizonte REAL do label (`time_stop_ms`), não é um
indicador técnico genérico — a mesma distinção que já separou A13 de
B01 (reclassificado `bar_count`) na sessão original. A literatura
confirma a REGRA (7 das 8 janelas ficam `bar_count`), não a exceção —
A13 continua `clock`, só ganhou implementação.

**C. Implementado** (`src/features/build.py`):
`_clock_reference_bar_duration_ms`/`_scale_clock_window_bars` escalam só
`ema_window`, usando `CALIBRATION_TF_BY_RESOLUTION`
(`src.data.build_dollar_bars`, alvo FIXO de calibração) como referência
— nunca uma duração medida (evitaria reabrir o mecanismo F2, já
rejeitado em `AG-043`, "reintroduz a não-estacionariedade do Bloqueador
2 dentro da própria feature"). Sob R1/R2/R3: 48/24/12 barras; sob
`bar_source="time_15m"` (todo caller de produção hoje): 48, bit-exato.
9 testes novos provam que as outras 9 janelas de `FeatureWindows` ficam
intocadas sob qualquer `bar_source`.

**D. Achado irmão, confirmado como correto e não um bug:**
`E27f_cost_atr_ratio` (feature, `atr_window` bar-count) segue
deliberadamente separado do ATR que dimensiona TP/SL no label
(`atr_window_ms`, clock — `AG-031`). A mesma pesquisa de literatura
confirma esta separação (feature = estimador estatístico estável; label
= restrição econômica real de tempo) — decisão de NÃO reconciliar,
documentada com citação em `constants.yaml`.

**E. Doc-drift ortogonal, corrigido na mesma leva:**
`src/features/registry.yaml::min_warmup_bars` dizia `2000` (herdado do
PRD, nunca lido em runtime) nas 13 entradas — valor real é `200` desde
`AG-027` (2026-08-15). Corrigido + teste de guarda novo.

**F. Verificação.** `ruff`/`mypy`/`banned_patterns.py`/`check_constants_
referenced.py`/`check_unguarded_ratios.py`/`check_constants_
provenance.py` limpos nos arquivos tocados — achados pré-existentes
cross-checados via `git stash` e confirmados não-introduzidos (4 erros
de mypy pré-existentes em `test_features_build.py`, 39 violações
`banned_patterns` pré-existentes em fixtures sintéticas — mesma contagem
antes/depois).

**G. Pendências explícitas, não resolvidas aqui.** `support.py`'s
`sqrt(window)` de `realized_vol`, gap overnight do Yang-Zhang, defasagem
do asof-join OI/funding (peça 2 original de `AG-043`) seguem deferidos —
bloqueados pelas mesmas 3 pré-condições já registradas (distribuição
real de duração de dollar bar ainda não medida). Detalhe completo:
`audit/architecture_gaps_log.yaml::AG-043` (addendum
`addendum_2026_08_23_aplicacao_em_codigo_de_a13`), `docs/SPRINT_LOG.md`.

---

### 15.24 `verify_config_hash` (B15) wireado no caminho real de consumo — `AG-140` (2026-08-23)

**A. Origem.** Continuação da varredura de prioridades do roadmap depois
do trabalho de `§15.23`: levantamento dos itens abertos, não bloqueados
por decisão do Manager, do `stage_readiness_audit` (fan-out 15 estágios,
2026-08-22) que ainda travam o gate "Data Layer 100%". `AG-140` era o de
maior consequência real: `verify_config_hash` (B15 — "config_hash do
label difere do hash da execução") já existia, testado isoladamente (4
testes), mas `src/models/dataset.py::build_modeling_frame` — o único
ponto real onde `labels.parquet` é carregado pra montar o frame de
treino/backtest — nunca a chamava. Um `labels.parquet` gerado sob uma
config antiga (`tp_atr_mult`/`sl_atr_mult`/`time_stop_ms`/`atr_window_ms`/
fees mudados em `constants.yaml` depois do backfill) passaria despercebido
para o treino do Alpha.

**B. Implementado** (`src/models/dataset.py`): logo após carregar
`labels`, `execution_config = LabelConfig.from_constants(estimator_id=
vol_estimator_id, tf=tf, resolution_id=resolution_id)` — MESMO
`vol_estimator_id` já propagado pra `build_t1_features`/`build_regimes`
(nunca um estimador separado/divergente pra label vs. feature, mesmo
princípio de "uma grade só" já documentado na função). `verify_config_
hash(labels, execution_config)` levanta `ConfigHashMismatchError` (falha
alta) se o hash divergir.

**C. Guarda nova, achado colateral da implementação:** `resolution_id`
setado agora EXIGE `vol_estimator_id` explícito em `build_modeling_frame`
— mesma regra que `LabelConfig.from_constants` já impunha, mas que
`build_modeling_frame` não replicava. Sem essa exigência, `vol_estimator_
id=None` computaria features/regime com o estimador default (ATR-Wilder)
enquanto os labels reais de R1/R2/R3 foram gerados com Parkinson explícito
(`run_and_write_labels_dollar_bar_parkinson`, `vol_estimator_window=20`)
— inconsistência silenciosa que nenhum teste cobria até este achado.
Confirmado sem regressão: nenhum caller real do repo passa `resolution_id`
sem `vol_estimator_id` hoje (`src/models/pipeline.py` é o único caller com
`resolution_id`, já propaga os dois juntos).

**D. Não executado empiricamente — pendência explícita, não escondida.**
Claude não roda `.py` (`CLAUDE.md`, protocolo de execução). Existe um
risco real, não hipotético: se `constants.yaml` já divergiu de quando os
labels `tf=15m` de produção foram gerados (BTC + 4 alts), esta correção
vai revelar isso na primeira chamada real de `build_modeling_frame()` —
usado por praticamente todo o pipeline de `src/analysis/` (`faixa1_5`,
`faixa1_6`, `faixa1_7`, `faixa2_*`, `calibration_diagnostics`,
`m6_common_factor_hypothesis`) além do treino real do Alpha
(`run_layer1_sprint`). Se isso acontecer, é um achado genuíno a registrar
(a correção estaria fazendo exatamente o que B15 existe pra fazer), não
um bug desta implementação — mas é uma mudança que pode interromper
scripts de análise que hoje rodam sem erro. **Ação pedida ao usuário:**
rodar `uv run pytest tests/unit/test_models_dataset.py -k config_hash` (7
testes novos, mock — confirma a lógica) e, quando conveniente, `uv run
pytest tests/unit/test_models_dataset.py -m "slow and integration"` (os 2
testes F1 que já chamam `build_modeling_frame()` sobre dado real) pra
confirmar contra produção de verdade.

**E. Verificação mecânica.** `banned_patterns`/`check_constants_
referenced`/`check_unguarded_ratios`/`ruff`/`mypy` limpos em
`src/models/dataset.py` e `tests/unit/test_models_dataset.py` — achado
pré-existente (1 erro mypy, 0 banned_patterns novos) cross-checado via
`git stash`, mesma contagem antes/depois. 4 testes existentes ganharam
mock de `verify_config_hash` (não testavam essa lógica, testavam
roteamento — `_one_row_labels` não tem `config_hash` real); 4 testes
novos dedicados à lógica de `AG-140` (guarda `vol_estimator_id`, match,
mismatch propagando `ConfigHashMismatchError`, `execution_config` usando
o `vol_estimator_id` correto).

**F. Confirmação empírica — o risco nomeado em D se concretizou, causa
raiz investigada e resolvida (mesma sessão).** Os 2 testes `slow`/
`integration` falharam de verdade contra `data/labels/BTCUSDT/15m/v1/
labels.parquet` real: `config_hash` do arquivo `b281a18954e224ef` ≠
`config_hash` da execução `2122d433edb4fd3a`. Investigado ANTES de
qualquer ação (`git log -p` completo nos 7 campos que compõem o hash):
NENHUM valor de `constants.yaml` mudou desde criado — a divergência é o
FORMATO do payload, que migrou 5 vezes historicamente (`estimator_id`,
`AG-005`, `AG-031`, `AG-042`, `AG-116`, cada uma já documentada na
docstring de `config_hash`, "mesmo valor numérico" a cada vez). Os
labels reais predatam essas migrações e nunca foram reprocessados —
`b281a18954e224ef` é literalmente o mesmo hash já citado em
`docs/SPRINT_LOG.md` (achado D3, sessão anterior) como referência
estável, sem que ninguém tivesse cruzado contra o schema atual porque
nada chamava `verify_config_hash` antes de hoje.

Usuário escolheu reprocessar (das 3 opções oferecidas: reprocessar /
reverter a checagem / só registrar e escalar). `build_and_write_labels_
for_symbol('BTCUSDT', ...)` + `run_and_write_labels_for_alts()` rodados
pelo usuário — reescreve os 5 `labels.parquet` com o `config_hash` do
schema atual, mesmos valores de barreira (nenhum parâmetro mudou, só o
hash). Confirmado: `uv run pytest tests/unit/test_models_dataset.py -m
"slow and integration"` — **2 passed** (antes: 2 failed). Zero teste do
repo tinha o hash antigo hardcoded — nenhuma outra reconciliação
necessária. `AG-140` fechado.

**G. Fila do roadmap, não atacados nesta rodada** — mesmo fan-out do
`stage_readiness_audit`, mesma severidade "alto", sem bloqueio de decisão
do Manager: ~~`AG-138`~~/~~`AG-139`~~ **fechados a seguir, mesma sessão —
ver `§15.25`**, `AG-141` (persistência de booster/calibrador —
`persistence.py` já existe, falta integração ao pipeline), `AG-142`
(diagnóstico de IC-por-ambiente não persistido).

**H. [NOVO 2026-08-24, `AG-205` addendum, Changelog v3.53] `config_hash`
tinha ponto cego real: só capturava campos de CONFIG, nunca a lógica de
geração em si.** Achado ao responder pergunta do usuário sobre o fill
gap-aware de SL (D4, ver `§11.4`/`docs/SPRINT_LOG.md`): a correção mudou
CÓDIGO (`triple_barrier._first_barrier_touch`), não nenhum campo de
`LabelConfig` — `config_hash` de qualquer config antes/depois da correção
seria IDÊNTICO, então `verify_config_hash` (`B`/`C` acima) aceitaria os 20
`labels.parquet` já persistidos (lógica antiga) como se nada tivesse
mudado. Fechado com novo campo `LabelConfig.barrier_fill_policy_id`
(default `"gap_aware_sl_v1"`), sempre presente no payload do hash — mesma
técnica já usada 4x neste campo (`AG-005`/`031`/`042`/`116`): adicionar
campo novo ao payload força divergência quando a semântica de geração
muda. Efeito: todo `labels.parquet` persistido antes desta correção
diverge agora do `config_hash` que `LabelConfig.from_constants()` produz
— `ConfigHashMismatchError` na próxima chamada real de
`build_modeling_frame` até reprocessar. **Reprocessamento NÃO disparado
nesta rodada** — decisão do usuário, comandos prontos (`build_and_write_
labels_for_symbol`/`run_and_write_labels_for_alts`/`run_and_write_labels_
dollar_bar_parkinson`, `src/labels/backfill_multi_symbol.py`). Detalhe:
`audit/architecture_gaps_log.yaml::AG-205` (addendum), 2 testes novos em
`tests/unit/test_labels_triple_barrier.py`.

### 15.25 `AG-138`/`AG-139` fechados — últimos 2 achados "alto" do fan-out de 15 estágios sem decisão pendente do Manager (2026-08-23)

**Origem.** Continuação direta de `§15.24-G` — os únicos 2 itens do
`stage_readiness_audit` (2026-08-22) com severidade "alto" que não
dependiam de decisão do Manager pra implementar (diferente de `AG-141`/
`AG-142`, que ficam pra depois: persistência de modelo/diagnóstico são
trabalho de integração maior, não correção pontual).

**`AG-138` — CLI de `build_dollar_bars.py` reproduzia o vazamento de
18,18x silenciosamente.** O módulo tinha 2 famílias de calibração (legada,
vazamento medido/corrigido por `AG-124`; causal nova,
`build_dollar_bars_walkforward`) mas só a causal gerava dado real em
disco — via um script SEPARADO
(`tools/diagnostics/run_ag124_production_reprocessing.py`). O `main()` do
próprio módulo, o comando mais óbvio e documentado
(`python -m src.data.build_dollar_bars ...`), continuava chamando só a
família legada, sem aviso. Implementadas as 2 correções que o agente
recomendou ("e/ou" resolvido como "e", não escolhido um só):
`--mode {single_window,walkforward}` (default `single_window` — zero
mudança de comportamento pra quem já usa o comando hoje) +
`--trailing-window-days`/`--cadence-days` obrigatórios sob `walkforward`
(`parser.error`, sem default — B23); `--mode walkforward` aciona
`build_dollar_bars_walkforward` direto do CLI; `--mode single_window`
(legado) ganhou `logger.warning` explícito citando o vazamento medido e a
alternativa, a cada execução; `--help` agora cita `AG-124`/`AG-138`. 4
testes novos de `_parse_cli_args` (default, `walkforward` sem cada um dos
2 argumentos obrigatórios levanta `SystemExit`, com ambos parseia
corretamente).

**`AG-139` — `banned_patterns.py --strict` falhava de fato em
`src/features/support.py`.** 2 magic numbers sem `# noqa: magic-number`
(`4.0` em `parkinson_vol` linha 168, `0.34`/`1.34` em `yang_zhang_vol`
linha 285) — mesma classe de constante de fórmula fechada da literatura
já isenta 6x no resto do pacote (`garman_klass_vol`/`rogers_satchell_vol`).
Correção trivial, mas achado colateral real na aplicação: `banned_
patterns.py` busca a SUBSTRING literal `"noqa: magic-number"` — combinar
`# noqa: unguarded-ratio, magic-number -- ...` numa tag só (1ª tentativa)
NÃO satisfaz a checagem (a substring exata não aparece). Corrigido com 2
tags `# noqa:` separadas na mesma linha.

**Verificação mecânica (ambos).** `banned_patterns.py --strict`: 0
violações em `src/features/support.py` (era 1) e em
`src/data/build_dollar_bars.py`/`tests/unit/test_data_build_dollar_bars.py`
(43 `MAGIC_NUMBER` pré-existentes no arquivo de teste, todos em fixtures
de dado sintético anteriores a esta mudança, confirmados via baseline
`git stash` — zero novos). `check_constants_referenced.py`/`check_
unguarded_ratios.py`: 0 achados novos. `ruff check`: limpo nos 3 arquivos
(1 `E501` introduzido e corrigido nesta mesma rodada, antes de commitar).
`mypy`: 0 issues, baseline idêntico via `git stash` nos 3 arquivos. Não
executado empiricamente por Claude (protocolo de execução, `CLAUDE.md`) —
os 4 testes novos de CLI são só parsing de `argv`, sem IO, mas pytest em
si continua rodado pelo usuário.

Commit: `ef7f5d3`.

**Consequência pro gate "Data Layer 100%" (`§15.14`).** Dos 3 achados
"alto" do fan-out de 15 estágios (2026-08-22) que travavam esse gate,
todos os 3 agora estão fechados: `AG-138`/`AG-139` (esta seção) +
`AG-140` (`§15.24`, sessão anterior a esta). O que resta explicitamente
aberto no gate, por estágio (`§15.4`): `08_SPLIT` tem 2 decisões
genuinamente pendentes do Manager, não gap de implementação (incluir/
excluir as 3 features expanding de `T1_FEATURE_IDS`; ressalva de
magnitude de `AG-159`/D-02) — **[DECIDIDO 2026-08-23, ver §15.4 linha
`08_SPLIT` e `§15.27`]** a 1ª decisão foi tomada (excluir) e implementada
(commit `78169df`); a 2ª (`AG-159`) deixou de ser dormente por causa
disso, diagnóstico novo escrito, resultado pendente do usuário rodar;
`06_BARREIRAS` continua deliberadamente sem
extração própria (vive dentro de `labels/`, refatoração represada pós-
Data-Layer-100% por decisão já confirmada 2026-08-22 — débito
organizacional, não gap funcional, a lógica de barreira já roda dentro de
`07_LABEL`). Não verificado nesta rodada se algum outro achado "médio"/
"baixo" do mesmo fan-out ainda está aberto em algum dos 15 estágios — só
os 3 "alto" foram varridos. Não afirmar "Data Layer 100%" sem essa
varredura completa.

**Varredura médio/baixo do gate (2026-08-23, pedido do usuário).**
Cobriu os 2 fan-outs (`stage_readiness_audit` 2026-08-21/2026-08-22) +
itens cruzados de `05_REGIME` — não achou nenhum achado médio/baixo NOVO,
só 3 itens já registrados que precisavam de correção/complemento:

- **`AG-134`** (05_REGIME, identificabilidade de `canonical_id` entre
  folds sob mudança estrutural real) — não bloqueante, decisão de QUANDO
  priorizar fica com o Manager. Ganhou o teste de caracterização sugerido
  na própria entrada (`test_canonicalizacao_pode_trocar_de_significado_
  sob_mudanca_estrutural_entre_folds`, commit `bed805e`) — não fecha o
  achado (prova que o cenário de risco é alcançável, não resolve
  identificabilidade formalmente), resultado real pendente do usuário
  rodar.
- **`AG-136`** (registro-mestre do plano de ação de 31 itens pós-AG-124)
  — status corrigido: dizia "restante em andamento" de forma genérica;
  na prática as Fases 1-6/8 já fecharam via `AG-124`/`AG-137`/`AG-118`/
  `AG-120`, só Fase 7 (sweep `tp_atr_mult`/`sl_atr_mult`) segue aberta —
  e já tem rastro próprio no roadmap (`§11.4`, Sprint 10/V41-6), não
  precisa de 2 ponteiros. Mesma classe de furo de `AG-123` (status
  desatualizado), não código.
- **`AG-120`** (BNBUSDT/RECENTE/R2, 2 posições de timestamp divergentes)
  — revisado, confirmado que o texto já estava preciso (nada a
  corrigir). Causa raiz exata exige inspecionar trades reais na janela —
  investigação empírica que só o usuário pode executar (protocolo de
  execução), não um fix de código.

`08_SPLIT`/`AG-159`/`AG-121`/`AG-123` (causa raiz do processo de
documentação) seguem exatamente como descrito acima — nenhuma mudança,
todos precisam de decisão real do Manager, não de correção mecânica.

### 15.26 Árvore de arquivos canônicos de produção, ponta a ponta (2026-08-23)

Pedido do usuário — mapeamento por leitura de código real (`grep -rn "if
__name__" src tools`), não por citação de doc, cruzado com a tabela de
15 estágios (`§15.4`) e o achado de `docs/nucleo_casca_design_doc_
2026-08-23.md`. **`docs/nucleo-casca.html` confirmado genérico** — único
hit de qualquer termo do projeto é uma coincidência de nome
(`triple_barrier.py` na árvore hipotética `core/`+`scripts/` do ensaio
original de Gary Bernhardt) — é leitura de apoio, não spec deste repo
(já dito em `CLAUDE.md`, confirmado aqui por varredura real).

**Vocabulário** (`CLAUDE.md`, "Núcleo funcional, casca imperativa"):
🟢 = tem runner de produção real (`if __name__ == "__main__":` que
orquestra IO real, não script de análise pontual); 📚 = núcleo pronto
(Idioma A/B), mas consumido só como biblioteca — sem CLI/runner próprio;
⬜ = não existe (nem núcleo nem casca).

```
exchange ─┐
data      │  01_BARRA          src/data/{resample,lake,download,bars,   🟢
          │                    build_dollar_bars}.py -- build_dollar_
          │                    bars.py::main é o runner canônico
          │                    (--mode single_window|walkforward,
          │                    AG-138); download.py/validate.py também
          │                    têm runner próprio (ingestão/quality
          │                    report)
          │  02_DATA_CHECK     src/data/{checks,validate,schemas}.py    🟢 (validate.py::main)
features  │  03_FEATURES       src/features/{build,support,groups/*}.py 📚 -- núcleo Idioma A
          │                    pronto (compute_t1_features), SEM CLI
          │                    própria -- consumido via
          │                    models/dataset.py::build_modeling_frame.
          │                    `groups/*` ganhou `group_k.py` (2026-08-24,
          │                    Lote A da liberação de features/H5) --
          │                    status 📚 inalterado, ver nota abaixo
          │  04_VOLATILIDADE   src/features/volatility.py               📚 -- ilha, só alimenta labels
regime    │  05_REGIME         src/regime/{build,classifier,build_hmm,  📚 -- build_hmm.py é builder de
          │                    stress}.py                               produção real (causal), SEM CLI
          │                    própria; classificador baseline
          │                    consumido via environments.py→
          │                    monotonic.py→alpha.py; candidato HMM
          │                    sem consumidor real (gate desligado,
          │                    AG-114/118)
labels    │  06_BARREIRAS      (não existe separado -- dentro de        ⬜ (represado pós-Data-Layer-100%)
          │                    labels/, decisão já confirmada)
          │  07_LABEL          src/labels/{triple_barrier,fill_model,   🟢 (backfill_multi_symbol.py::main)
          │                    backfill_multi_symbol}.py
          │  07b_PESOS         src/labels/weights.py                    📚
models    │  08_SPLIT          src/validation/cpcv.py                   🟢 (wired em pipeline.py, sem CLI
          │                                                             própria -- roda dentro do runner
          │                                                             do Learner)
          │  09_LEARNER        src/models/{pipeline,alpha,monotonic,    🟢 (pipeline.py::run_layer1_sprint)
          │                    persistence}.py                          -- persistence.py pronto/testado,
          │                                                             NÃO integrado (AG-141)
          │  09b_CALIBRAÇÃO    inline em alpha.py -- não separável hoje ⬜ (sem gate de amostra pequena)
validation│  10_VALIDAÇÃO      src/validation/{dsr,leakage}.py           🟢 (leakage.py::main, 14 testes) --
          │                                                             maduro, mas NÃO é gate de nada
          │  11_META_MODEL     não existe -- desenho travado v3         ⬜ (§15.19, ZERO implementado)
          │  11b_DECISION_     não existe                               ⬜ (§11.6, AG-143 -- decisão do
          │  ENGINE                                                     Manager necessária antes do 1º
          │                                                             commit)
backtest  │  --                src/backtest/fill_reconciliation.py      🟢
          │                    src/execution/fill_simulator.py          🟢 (simulação, não live)
risk      │  12_RISK_ENGINE    src/risk/{sizing,limits,kill_switch}.py  ⬜ ZERO caller de produção -- funções
          │                                                             puras testadas, nada as invoca;
          │                                                             gate de regime desligado de
          │                                                             evaluate_all() (AG-114/118)
execution │  13_EXECUÇÃO       src/exchange/adapter.py                  ⬜ place_order = NotImplementedError
live      │  --                src/live/                                ⬜ vazio (docstring só, 3 linhas)
monitor.  │  14_MONITORAMENTO  src/monitoring/{logging,dollar_bar_      ⬜ dollar_bar_drift.py real/testado
          │                    drift}.py                                (315 linhas, 16 testes), SEM caller
          │                                                             de produção; logging.py "1 função
          │                                                             nunca chamada"
feedback  │  15_FEEDBACK_      src/models/decomposition.py              🟢 -- só sobre trade SIMULADO de
          │  POST_TRADE                                                 backtest, versão live gated por 13
```

**Leitura honesta do estado real** (achado do mapeamento, não só uma
listagem): runners de produção que de fato orquestram IO real existem
ponta a ponta só até `models`/`validation`/`backtest` (estágios 01-10,
mais 15 no modo simulado) — **a partir de `12_RISK_ENGINE` em diante
(Risk/Execução/Live, metade do Monitoramento), não existe NENHUM caller
de produção**, confirmado por `grep` direto (zero `__main__`/`argparse`/
`def main(` nesses módulos). `features`/`regime` (03/04/05), apesar de
terem núcleo pronto e testado (Idioma A, `build_hmm.py` causal), também
não têm CLI própria — rodam só como biblioteca dentro de
`models/dataset.py::build_modeling_frame` (o próprio `CLAUDE.md`, seção
"Comandos", já registra isso: "Feature/Regime Engine não persistem
artefato em lote... recomputados on-the-fly").

**2 execuções reais de produção fora de `src/` (não confundir com os
~40 scripts de diagnóstico read-only de `tools/diagnostics/`, todos
"leitura-only sobre amostra/tempdir", nunca escrevem em produção):**
`tools/diagnostics/run_ag124_production_reprocessing.py` (reprocessa
`data/capacity/dollar_bars_r{1,2,3}/` completo) e
`tools/diagnostics/run_ag100_labels_r2_r3_backfill.py` (backfill real de
labels R2/R3) — nomeados `run_*`, não `measure_*`/`compare_*`, de
propósito.

**5 violações núcleo/casca já catalogadas** (`docs/nucleo_casca_
design_doc_2026-08-23.md`, não duplicadas aqui) — mais grave:
`triple_barrier.py::build_labels_with_stats` mistura IO (`load_filters_
asof`) dentro do loop de barreira, sem ponto de injeção; padrão de
correção sancionado (D-03) reusa o par `compute_sizing`/
`compute_sizing_asof` de `src/risk/sizing.py` como referência — desenho
feito, zero linha implementada.

Detalhe completo por arquivo/camada: `docs/nucleo_casca_design_doc_
2026-08-23.md`; tabela de status por estágio: `§15.4`.

**Atualização 2026-08-24 (Lote A da liberação de features, H5) — `03_
FEATURES` ganhou arquivo novo, status do estágio não muda.**
`src/features/groups/group_k.py` (Grupo K — temporal/calendário) é o
único arquivo novo desta leva; as outras 47 features T2 (`A01-A04`/
`A06-A12`/`A14`, `B02-B06`/`B08`/`B09`/`B11`, `C03-C05`/`C09-C12`,
`D01f`/`D02f`/`D04f`/`D05f`/`D08f`/`D09f`, `E01f`/`E05f`/`E09f`/`E11f`/
`E12f`) foram apendadas aos 5 arquivos `group_{a,b,c,d,e}.py` já
existentes — nenhuma T1, nenhuma fonte/primitiva nova (zero mudança de
`02_DATA_CHECK`/`01_BARRA`). `03_FEATURES` continua 📚 (núcleo pronto,
sem CLI própria) — a natureza do estágio não mudou, só o tamanho do
catálogo T2 disponível (`SUPPORT_FEATURE_IDS`: 3→50). Verificado via
`audit_engineering` (lente FS/FI/FT/FCN completa, pedido do usuário,
2026-08-24): nenhum CRITICAL/HIGH. Um achado MEDIUM real (`test_warmup_
uniforme_maioria_valida_depois_do_corte`, `tests/unit/test_features_
build.py`, só cobria `T1_FEATURE_IDS` — as 50 T2 nunca tinham essa
checagem em dado real) foi corrigido na própria sessão da auditoria, já
verificado passando nos 5 símbolos reais. Suíte completa 1904 passed +
paridade lote↔streaming completa (`tests/parity/test_features_parity.py`,
20/20, `<1e-8`, 5 símbolos × 4 variantes) rodadas de verdade — ambas
cobrem as 50 T2 automaticamente (iteram `T1_FEATURE_IDS +
SUPPORT_FEATURE_IDS`), não é alegação sem medição. Lote B (features que
exigem primitiva nova: `A15`/`B10`/`C08`/`D07f`/`D10f`/`E03f`) e Lote C
(extensão de `_sources.py` pra OI-notional/long-short-ratio) ficam pra
depois — plano de 3 lotes com checkpoint entre cada um, aprovado pelo
usuário. Detalhe completo: `docs/SPRINT_LOG.md` (seção "H5 — liberação
de features, Lote A"), `src/features/registry.yaml`, `config/
constants.yaml` (seção "Lote A da liberação de features").

### 15.27 `08_SPLIT` — decisão 1 tomada e implementada, decisão 2 (`AG-159`) deixa de ser dormente (2026-08-23)

Continuação direta de `§15.25`/`§15.26` — usuário decidiu os 3 achados
médio/baixo que precisavam de decisão real (não mecânica).

**Decisão 1 — as 3 features expanding SAEM de `T1_FEATURE_IDS`.**
`C07_vol_pctile_expanding`/`D03f_volume_z_expanding`/`E02f_funding_z_
expanding` removidas do conjunto ativo de treino do Alpha (`AG-032`
addendum, commit `78169df`). As 3 continuam sendo CALCULADAS
(`compute_t1_features` não filtra por `T1_FEATURE_IDS`) — `C07` segue
como insumo real do Regime Engine (`src.regime.classifier`, leitura
direta da coluna); análise pós-hoc ganha caminho oficial pra ler as 3
sobre `ModelingFrame` real (`build_modeling_frame(...,
extra_feature_ids=(...))`, novo parâmetro, default preserva
comportamento anterior byte a byte). `registry.yaml` tier das 3: T1→T2.
`monotonic.py::_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` esvaziado (E02f era
o único exemplo real da restrição side-dependent) — mecanismo mantido
pra feature futura da mesma categoria (funding/basis/custo de carrego,
comum em cripto).

**Pendente, registrado, não corrigido nesta rodada**: 6 scripts de
análise pós-hoc (`calibration_diagnostics.py` — módulo compartilhado,
maior risco; `faixa1_5/6/7_*`; `faixa2_caminho_b.py`;
`faixa2_vol_accelerator_test.py`) hardcodam `C07`/`E02f` lendo direto de
`mf.data`, não via `extra_feature_ids` (que não existia antes desta
mudança) — vão quebrar (`ColumnNotFoundError`, falha visível, não
silenciosa) na próxima execução real até migrarem. Não é gap de
produção — são scripts `pós-hoc, exploratório, zero trials`, fora do
caminho de treino real.

**Decisão 2 — consequência direta da Decisão 1, não uma escolha nova.**
O gate que mascarava a ressalva de magnitude de `AG-159`/D-02
(`assert_no_expanding_lookback_in_active_set` bloqueando
incondicionalmente) deixa de disparar no caminho default —
`compute_max_feature_lookback_ms` agora EXECUTA de verdade sob
`resolution_id` (R2/R3), usando um proxy (`label_prefetch_p99_bar_
duration_ms`) medido pra um modelo de custo diferente (prefetch, não
purge) — o risco deixou de ser dormente, é pré-requisito real antes do
1º treino sob R2/R3 com purge ativo. Ação tomada: `structlog.warning`
explícito adicionado em `compute_max_feature_lookback_ms` (dispara toda
vez que roda sob `resolution_id`, sem inventar número novo, B23);
`tools/diagnostics/measure_max_consecutive_bar_window_duration.py`
(novo) mede o máximo real de janela de `max_feature_window_bars()`
barras consecutivas, por símbolo × resolução, sobre os parquets já
persistidos — comando pra rodar:

```bash
uv run python tools/diagnostics/measure_max_consecutive_bar_window_duration.py
```

**[FECHADO 2026-08-23]** Usuário rodou o diagnóstico e perguntou
explicitamente: refatorar pra engenharia robusta, ou remediação barata
(aceitar a folga incidental) basta? Decisão: garantia formal.
Resultado real (`worst_case_ratio=0,472` — contradiz a leitura anterior
de "~5,8x sub-cobertura", causa raiz era comparar contra p99 LOCAL em
vez do proxy cross-symbol real) mostrou que o proxy já era seguro na
prática, mas por construção incidental. `max_consecutive_bar_window_
duration_ms` (constante nova, `MEASURED` direto, `config/constants.yaml`)
substitui o reaproveitamento do proxy de prefetch —
`compute_max_feature_lookback_ms` retorna o máximo real medido
diretamente sob `resolution_id`, com guarda de staleness (`structlog.
warning` se `max_feature_window_bars()` divergir do valor medido, 96).
Per-símbolo/resolução avaliado e descartado — variância é dominada pela
RESOLUÇÃO, não pelo símbolo (fator ~1,8x dentro de cada resolução vs.
~3,4x cross-tudo); um único valor global segue o mesmo precedente já
estabelecido pra este tipo de constante de segurança neste projeto
(`label_prefetch_p99_bar_duration_ms`, mesma filosofia). `AG-159`
fechado no ledger.

Verificação mecânica completa (`banned_patterns`/`ruff`/`mypy`/
`check_constants_referenced`/`check_constants_provenance`) em todos os
arquivos tocados — zero regressão. Detalhe: `audit/architecture_gaps_
log.yaml::AG-032` addendum `addendum_decisao_08_split_2026-08-23`,
`AG-159` addendum `addendum_solucao_definitiva_2026-08-23`.

### 15.28 Varredura de acurácia + limpeza real do documento inteiro (2026-08-23)

Pedido explícito do usuário — não mais uma camada de anotação
`[DESATUALIZADO]` por cima do texto antigo (convenção histórica deste
documento), e sim deletar/fundir de verdade o que não condiz mais com a
arquitetura/código atuais. Motivo: o mesmo furo de sincronização
(seção editada, resto do documento não revisado) já tinha se repetido 4
vezes registradas em `AG-123`.

**Metodologia**: fan-out de 8 agentes só-leitura, cada um cobrindo uma
faixa contígua das 5887 linhas então existentes, cruzando toda afirmação
de "estado atual" contra código real, `git log`, e
`audit/architecture_gaps_log.yaml` — não contra a prosa do próprio
documento. Cada achado classificado em DELETAR (texto errado hoje E já
corrigido em outro lugar, não soma nada) / FUNDIR (par original+correção
que vira 1 parágrafo atual, sem o andaime "isto dizia X, mas na verdade
é Y") / MANTER COMO HISTÓRICO (documenta o MOTIVO de uma decisão —
memória institucional real, mesmo com detalhes técnicos desatualizados).

**Resultado**: ~50 achados no total, ~30 aplicados (net -46 linhas, já
contando as correções adicionadas). Achados de maior valor:

- **`§11.6` (tabela M4/Trilha B)** tinha 2 células afirmando conclusões
  já revertidas por seções posteriores do PRÓPRIO documento (`hmm_
  gaussian_k4_v1` "confirmado e robusto" quando `§15.13` diz `AG-114`
  "continua ABERTO"; wiring Regime→Risk "implementado" quando foi
  desligado 1 dia depois) — corrigidas.
- **`§15.11` (AG-096/098/099)** — 3 mecanismos rotulados "MECANISMO
  APROVADO"/"CONFIRMADO SÓLIDO" que a auditoria externa (`§15.12`)
  refutou como especificados, sem nenhum ponteiro no local original.
  `AG-098` é o mais sério: a convenção de contagem de trial que ele
  aprova está ATIVAMENTE ERRADA (`AG-111`, ainda aberto hoje) — se
  aplicada por engano numa seleção de linha real, contaminaria
  `N_lifetime`/DSR sem detecção. Não é achado de limpeza de texto, é
  risco operacional real — sinalizado com aviso explícito no local.
- **`§15.12.4` (AG-094)** — conclusão "Meta não consome regime" revertida
  pelo Manager em 2026-08-22 (regime virou feature one-hot do Meta), sem
  nenhum ponteiro apontando pra frente — corrigido.
- Tabela ASCII `§15.4` — 4 linhas com anotação `[DESATUALIZADO]` órfã
  (correção presente, mas sem mostrar o que estava sendo corrigido,
  lendo de forma confusa) — reescritas como declaração limpa.
- Referências a `docs/refactor_gk_canonico.md` (arquivo renomeado
  2026-08-17) e a `docs/ADR-001_..._2026-08-19.md` (nome sem `_base`,
  nunca existiu no git) — corrigidas pros nomes reais.
- 2 TODOs já cumpridos no mesmo dia em que foram escritos (transcrição
  do ADR-001 completa; sequenciamento `AG-109`→`AG-108` que deixou de se
  aplicar quando `AG-109` foi refutado) — removidos.

**Não aplicado nesta rodada** (achados de severidade baixa, custo/
benefício menor): citações de número de linha desatualizadas em
`§15.12.3`/`§15.3` (apontam pro arquivo certo, só o número exato mudou);
inconsistência numérica pequena entre 2 fontes quase-canônicas (1508 vs.
1520 testes, `§15.12.3`); 1 anotação redundante mas já corrigida em
`§15.21.3`-C. Nenhum destes muda uma decisão nem confunde um leitor —
registrados aqui, não silenciados.

**`§14` (histórico do Road Map Vivo v1) e a maior parte de `§15.7`-
`§15.21` foram deliberadamente MANTIDOS como estão** — são trilhas de
decisão genuínas (medir → decidir → auditar → corrigir), memória
institucional real mesmo com detalhes técnicos superados por seções
posteriores. Apagar o "antes" perderia exatamente a lição que motivou
este pedido de limpeza.

Verificação: `check_sprint_log_references.py` não se aplica a este
arquivo (é específico de `SPRINT_LOG.md`); revisão manual de contagem de
cabeçalhos (`## `/`### `) confirma nenhum título removido por acidente
(70 antes, 70 depois).

---

### 15.29 `AG-362` reabre L3→T1 por decisão direta (poda `ADR-005 §2.2`), retreino canônico sob 22 features é misto, e `AG-371` acha — mas não termina de validar — um viés estrutural de Camada 0 (2026-08-27/28)

**Origem.** `ADR-005` (`docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md`,
2026-08-26/27) estratificou o catálogo (~90 features) por camada de
evidência (`L1`-`L4`) e travou um critério de promoção `L3`→`L2` via
Benjamini-Hochberg marginal por símbolo (`§2.2`, corrigido de célula pra
símbolo em `AG-294`) + estabilidade temporal — ~50 achados de engenharia
nesses 2 dias (censo de nulos, purge dimensionado pelo vetor real,
detector de linhagem label↔registro, R2 nunca aplicada em `src/models/`,
`AG-298` a `AG-336`), não detalhados aqui (ver `SPRINT_LOG` 2026-08-26/27
e o próprio ADR). Resultado do critério: `L2` ficou VAZIA — zero promoção
desde a criação do gate — apesar de 15 features `L3` com tese declarada e
sem defeito confirmado.

**`AG-362` (2026-08-27) — o Manager reverte o GATE, não o dado medido.**
Achado que motivou: o teste marginal é estruturalmente cego a interação
entre features (informação sinérgica, McGill 1954); o LightGBM que de
fato consome o vetor captura interação via splits sequenciais, então o
filtro de ENTRADA era calibrado por um instrumento mais fraco que o
modelo que deveria proteger. Decisão direta do Manager: feature `L3` com
tese declarada e sem `defeito_construcao`/`quarentena` confirmado passa a
ser promovível sem protocolo formal de medição prévia — a régua nova é
"o Alpha, sob CPCV purgado, ganha algo com a feature", medição que fica
com `src/models/`, não mais gate de entrada em `src/features/`. 15
features `L3`→`T1` (momentum A01-A04/A06, `C12_vol_of_vol_48`,
`D05f_taker_buy_ratio`, `D08f_trade_count_z_48`, `E01f_funding_last`,
`E05f_time_to_funding_h`, `E12f_price_oi_divergence`, `K03_is_weekend`,
`K04_session_asia`, `E14f_toptrader_ls_ratio`, `E16f_global_ls_ratio`) —
`T1_FEATURE_IDS` vai de **7 pra 22**; 35 features `L4` saem de
`SUPPORT_FEATURE_IDS` (poda real, endereça o achado de `AG-336` —
"classificar `layer` não bastava, faltava podar"). 91 testes verdes,
`banned_patterns`/`ruff`/`mypy` limpos — mas nenhum exercitava
`src/models/dataset.py`, o consumidor real.

**A mudança ficou isolada do módulo que a consome (`AG-365`).**
`build_modeling_frame` decidia carregar dado caro de futures-positioning
olhando só `extra_feature_ids` (parâmetro de análise pós-hoc), nunca
`T1_FEATURE_IDS` (o vetor real) — 2 das 15 promovidas (`E14f`/`E16f`)
dependem desse dado; retreino canônico crashava no 1º fold
(`DeadFeatureColumnError`). Corrigido estruturalmente (união dos dois
conjuntos, não sincronização manual) — mesma classe de defeito que
`AG-300` já tinha fechado uma vez, um nível abaixo na pilha. 3 bugs
adicionais de engenharia de medição (`AG-366` config_hash não capturava
composição de T1 sob `feature_ids=None`; `AG-367` `NaN` de Sharpe
indefinido contaminava o agregado; `AG-368` colisão de hash entre
designs de hiperparâmetro) achados e corrigidos ao vivo durante a própria
medição de valor incremental.

**Valor incremental das 15 promovidas — medido, resultado misto.**
Desenho de 3 rodadas (`off`/`on`/`base`) sobre as 15 combinações reais,
sob CPCV purgado: **zero das 15 passa `permanence_pass` em qualquer das
3** — 22 features não é pior nem melhor que a base de 7 nesse critério
binário. Nas métricas finas o sinal é MISTO: por soma de
`delta_sharpe_mean`, 22+hiperparâmetro-por-combo lidera (23,84 vs 16,86),
dominado por 2 células isoladas (80% da soma); por caminhos vencidos e
gate econômico pós-trial, a base de 7 lidera nos dois (33/75 vs 22/75;
17/25 vs 10/27 lados). Vencedor de hiperparâmetro (decide o desenho do
retreino canônico): "on" (por combo), por definição pré-registrada.

**Retreino canônico real (2026-08-28) — 22 features + hiperparâmetro por
combo, 15/15 escritas em `artifacts/predictions_alpha/`.** Resultado
idêntico ao já medido na comparação pareada: **0/15 `permanence_pass`**,
22/75 caminhos vencidos, 10/27 lados no gate econômico. Achado novo:
`N_eff` efetivo mediano = **2,86 de 22 features** — 7/15 combinações
concentram o gain em menos de 2,5 fatores efetivos mesmo com o vetor de
22 disponível, CONTRA a premissa de "captura de interação ampla" que
motivou `AG-362`. 5/15 (`BNBUSDT_R1/R2`, `BTCUSDT_R1`, `ETHUSDT_R1`,
`XRPUSDT_R1`) têm Sharpe da Camada 0 indefinido — discriminação real
(Delta AUC B4 0,12-0,15) não convertendo em Sharpe positivo (percentil
B1 baixo), hipótese aberta de calibração de `tau`.

**`AG-371` — causa dupla das 5 células zeradas.** (1) Hiperparâmetro
stale: `config/alpha_hyperparams_by_combo.yaml` (10 combos) foi calibrado
25/08 pra um vetor de 62 features que `AG-362` já não deixou existir
nessa forma — nunca recalibrado. Trava fail-closed implementada e
VERIFICADA (autorização de execução do Manager): hash de conteúdo do
vetor confirma mismatch real; `HyperparamFeatureMismatchError` bloqueia
o arquivo stale até recalibração. (2) Viés estrutural, mais fundo (7
addenda): as 5 células têm `n_signals=0` nos 5 caminhos do CPCV, nas
duas pontas — ausência determinística de sinal, só na variante SEM
restrição monotônica (Camada 0, por desenho). Mecanismo: `E27f_cost_
atr_ratio` (maior `|IC|` entre as 22) domina **93% do gain** de Camada 0;
2 hipóteses de correção via hiperparâmetro puro (`feature_fraction`,
`lambda_l2`) TESTADAS e REFUTADAS por medição direta — espaço de
hiperparâmetro padrão exaurido, causa é estrutural (nenhum freio contra
feature contínua de alta correlação dominar a busca gulosa de split).
Correção AUTORIZADA pelo Manager: restrição monotônica só em `E27f`
dentro de Camada 0 — promovida a comportamento DEFAULT (política
`34ae285`, não flag), 391 testes verdes.

**[SUPERADO 2026-08-29, Changelog v3.57]** O mecanismo do item (1) acima
(`config/alpha_hyperparams_by_combo.yaml` + `HyperparamFeatureMismatchError`
fail-closed) foi **removido**, não recalibrado — decisão do Manager de
aposentar o YAML estático inteiro (já tinha ficado *stale* uma vez de
verdade, é a própria origem deste parágrafo) em favor de Optuna real
gravando resultado como artefato content-addressed (`AG-371-ADDENDUM-18`,
commit `40b8255`). A trava fail-closed descrita acima cumpriu seu papel
histórico (impediu o retreino canônico de ler um arquivo stale sem
avisar) e deixa de existir como código — a classe de bug que ela vigiava
fica fechada por construção no mecanismo novo. O achado estrutural do
item (2) (`E27f` dominando 93% do gain, correção monotônica) não é
afetado por esta mudança — é ortogonal ao mecanismo de hiperparâmetro por
combo.

**Confundido antes de confirmado — sessão paralela mudou o vetor embaixo
da investigação, retreino de validação cancelado (`AG-371-ADDENDUM-10`,
severidade CRÍTICA).** O retreino disparado pra validar a correção de
`E27f` foi CANCELADO pelo Manager a meio caminho; investigando por que o
log mostrava `feature_ids_n=36` (esperado 22), achou-se uma 2ª sessão
autorizada rodando NO MESMO working tree, não commitada:
`T1_FEATURE_IDS` foi de 22 (HEAD) pra 29 (Lote D, `AG-372`/`ADR-006`) e
depois 36 (Lote D2) enquanto `AG-371` corria. Checado por timestamp
exato contra `git diff` de `build.py`: o teste que isola
hiperparâmetro-stale-vs-estrutural (`ADDENDUM-3`) rodou limpo sob 22
features, conclusão sobrevive; mas o TESTE DA PRÓPRIA CORREÇÃO de `E27f`
(`ADDENDUM-8`, "n_signals 0→2407") comparou um baseline sob 22 features
contra um "corrigido" sob 36 — 2 variáveis mudando ao mesmo tempo, não
dá pra atribuir a melhoria só à correção. O código promovido continua
correto por construção; a MEDIÇÃO que justificou promovê-lo está
confundida, não refutada. **2 decisões seguem em aberto do Manager**:
(1) qual `T1_FEATURE_IDS` é autoritativo agora — 22 (commitado), 29 ou 36
(Lote D/D2, só no working tree); (2) remedir a correção de `E27f` sob 22
features limpo antes de confiar na promoção.

**Achado irmão, mesma sessão de Lote D/D2 — `AG-373`, CORRIGIDO no
mesmo dia.** `A17_true_range_per_overshoot` (uma das 14 features do Lote
D/D2) tinha defeito dimensional real: `TR_t` (unidade de preço) dividido
por `overshoot_t` (unidade de notional em dólar) não cancelava — a razão
tinha unidade residual `1/coin`, ao contrário de todas as outras 13
features do lote. Risco de deriva de escala dentro do histórico de um
único símbolo (preço nominal variando por ordens de grandeza ao longo
dos anos de treino), eixo diferente do confundidor entre-símbolos já
mitigado por treinar por `(symbol, resolution_id)`. Achado por auditoria
independente (persona ML Feature Engineer, autorizada pelo Manager),
confirmado por leitura direta de `support.true_range`/`bars.py::_value`.
Corrigido por normalização estrutural — renomeada `A17_log_tr_per_
overshoot_ratio`, razão de 2 quantidades adimensionais (`TR/C_{t-1}`,
`overshoot/threshold_quote`) em `ln1p` — verificada por teste que prova
invariância a nível de preço (falharia sob a fórmula antiga). Detalhe
completo: `AG-373`, addendum de `ADR-006`.

**Regime — 1 gap fechado, 1 gap novo aberto.**
`canonical_volatility_estimator.value` flipado pra `parkinson_w20` em
produção (commit `4f3b231`, 2026-08-27, decisão do Manager) — fecha o
"DECIDIDO, NÃO DEPLOYADO" rastreado desde 2026-08-17 (`§11.4`/`§11.6`).
Achado no mesmo dia: a constante não tinha NENHUM código lendo-a por
nome — `--all-combinations` sem `--vol-estimator-id` explícito revertia
a decisão em silêncio (`AG-361`, mesma classe de `AG-341`/`AG-365`) —
corrigido pela mesma política (default agora lê a constante). `AG-341`
(HMM k=4 nunca wireado no pipeline real, `dataset.py` usa
`QuantileRegimeClassifier`) **já corrigido em `§15.13` por commit
`d4c1d4e`, sem ação pendente aqui**. Achado NOVO e ABERTO, mesma revisão
`project_assurance`: `AG-342` — os 4 cutoffs do classificador REALMENTE
ativo (`regime_er_cutoff`/`regime_vol_cutoff`, entrada/saída) são classe
A `provenance: ASSUMED`, `sweep_required: true`, `review_by: sprint_5`
— nunca varridos apesar do projeto estar muito além do sprint 5; por
regra do próprio `CLAUDE.md` isso deveria bloquear build de produção, e
não bloqueia.

**Registro à parte** (`CLAUDE.md`, sem consequência de dado): regra nova
(commit `34ae285`, 2026-08-27) — correção pedida pelo Manager vira
comportamento DEFAULT a partir do commit que a aplica, nunca opt-in
"por via das dúvidas" — e split estrutural em `.claude/rules/
execution-exceptions.md`/`behavior-notes.md` (`a656312`, mesmo dia).
Explica por que vários achados desta seção (`AG-296`, `AG-324`-`326`,
`AG-360`, `AG-361`) viraram default imediato.

**Nota de estado, pra não confundir quem ler daqui pra frente**: no
momento em que esta seção foi escrita, `T1_FEATURE_IDS` tem **22**
features no HEAD commitado (`730b2ec`); **29** (Lote D) e **36** (Lote
D2) existem só no working tree de uma sessão paralela, ainda não
commitados, ainda não reconciliados com `AG-371`. Nenhuma afirmação
nesta seção deve ser lida como "T1 tem 36 features" sendo verdade de
produção — decisão de qual vetor é autoritativo pendente do Manager
(`AG-371-ADDENDUM-10`).

---
### 15.30 Meta-model — F0-F3 implementados, regime canônico vira HMM k=4, e o peso de treino ponderava a CLASSE (2026-08-30)

Execução do `docs/meta_model_design_doc_2026-08-22.md` (v3, travado desde
2026-08-22) sob autorização direta do Manager: *"F0-F8 completo"*, *"rodar
E0 com o critério como está"*, *"N_lifetime não é mais gate"*. Escopo
entregue nesta rodada: **F0, F1, F2 e F3**. F4-F8 seguem pendentes.

**O desenho envelheceu 201 commits.** Levantamento antes de escrever
código: dos gates externos do `§15.2` do design doc, **E1 e E2 caíram**
(Data Layer destravado em 2026-08-23; Alpha retreinado 2× em 08-23 e
08-28, `tau_long`/`tau_short` já no schema, 17→21 colunas), e sobraram
justamente os dois que o documento tratava como pré-requisito mecânico:
**`P0`** (esquema de permutação do nulo do E0 travado em documento, mas
validação nunca executada) e **`P1`/`AG-151`** (purge cross-símbolo
ausente). O E0 vinculante segue **não executado**.

**Correção do Manager no meio da execução: o regime é HMM k=4.**
Apuração: `canonical_regime_hmm_n_states = 4` com `provenance: MEASURED`
(`AG-114`), mas **`hmm_gaussian_k4_v1` não tinha caminho de produção
nenhum** — zero artefatos em disco, e o único chamador de
`build_hmm_regimes` fora de teste era `hmm_gap_check` (triagem).
`build_modeling_frame` entregava o classificador por quantis (`R0..R5`).
Um comentário em `src/analysis/gate_efficiency.py` já chamava
`build_hmm.py` de *"o caminho de PRODUÇÃO"* — era aspiração, não fato
(`AG-384`).

Resolvido com adaptador de schema em `dataset.py` (`regime_source`) +
persistência como artefato versionado (`src/regime/artifact_hmm.py`),
decisão do Manager depois de medido que `build_hmm_regimes` custa **horas
por símbolo** (refita por fold do walk-forward ancorado; >2h40 de relógio
e ~8.840 s de CPU por símbolo, medido em 2026-08-30). Recomputar dentro de
cada `build_modeling_frame` é inviável — e tornaria o custo de montar um
frame de modelagem dependente de um refit de modelo, coisa que nenhum
outro insumo do pipeline faz. Preenche o `TBD — medir` do `§13` do design
doc para a dimensão "tempo".

O default de `regime_source` continua o classificador por quantis, e isso
**não é "correção atrás de flag"**: a coluna `regime` desse frame alimenta
o gate de risco de produção (`src.risk.limits::control_01_regime_tradeavel`),
e trocar o default mudaria o gate de carona numa mudança feita para o
Meta. Decisão separada do Manager.

**O achado que mais muda o desenho: o peso de treino ponderava a classe.**
Medindo `corr(|ret_net|, y_meta)` — que o próprio `§5` do design doc
manda medir — sobre BTCUSDT/R1 camada1 (n=11.859):

```
η² (classe explica a variância de |ret_net|)      = 0,4872
corr(|ret_net|, y_meta)                           = −0,698
peso de classe implícito mean(w|y=0)/mean(w|y=1)  =  1,6082
```

Ou seja, `meta_sample_weight = uniqueness_subpop × |ret_net|` era, na
prática, **um peso de classe de 1,61:1 a favor dos perdedores** — nunca
escolhido, nunca declarado. Causa raiz medida: as barreiras hoje são
**simétricas** (`tp_atr_mult = sl_atr_mult = 1,5`) e o retorno bruto é
simétrico (+0,002261 no TP contra −0,002269 no SL); a assimetria inteira
vem do **custo de execução** (saída maker de 2,00 bps no TP contra taker
de 5,00 bps no SL). O design doc afirmava o oposto em magnitude E direção
(*"com `tp_atr_mult = 2.0`... `E[|ret_net| | y=1] ≈ 1,33 ×`"*); o medido
é **0,63 ×**.

Importa porque peso de classe no treino desloca a escala de `p_meta`, e
**D-07 removeu o calibrador** que absorveria o deslocamento. A assimetria
de custo é econômica e real, mas o lugar dela é a regra de decisão
(`tau_meta`, `§8.3`), como parâmetro declarado — não o peso de treino,
onde entra duas vezes e sem controle.

Corrigido para `uniqueness_subpop × atr_at_t0` (a magnitude **em risco**,
conhecida em `t0`). Verificado sobre dado real nos 12 folds: peso de
classe 1,6082 → **1,0026**; `corr(peso, y)` −0,698 → **0,006**; η² 0,487 →
**0,000**; e `corr(atr, |ret_net|)` **dentro** da classe 0,89/0,97 — a
ordenação econômica é preservada. Registrado em
`audit/evidence_ledger.yaml`. **O mesmo defeito existe no Alpha**
(`src.labels.weights.apply_weights`, peso de classe medido em **1,3027**)
e está escalado ao Manager como `AG-388`, não corrigido de carona.

**F2 entregou o número que o `§15.2` declarava como seu propósito.**
`n_eff_subpop` sobre BTCUSDT/R1 camada1: total 10.220,17 no treino,
mediana 652,54 por meta-fold, mínimo 140,72;
`uniqueness_inflation_ratio` mediana 2,4340. Consequência para `§7.3`: com
7 colunas no design matrix sob HMM k=4, o **EPV medido é 93 na mediana e
20 no pior fold** — a logística L2 é sustentada com folga em todos os
folds. `meta_min_neff_for_gbm` permanece `TBD` (B23, não inventado).

**Contexto de escassez, medido no mesmo passo:** das 15 combinações de
fold do Alpha, **só 8 produzem qualquer sinal**; 6.142 sinais em 411.600
linhas de predição; `meta_training_set` fica com 18.280 linhas (12.138
treino + 6.142 teste). Somado ao `N_eff = 2,03 de 5 símbolos` do
`cross_symbol_ess` e ao **1/15 combos sobrevivendo ao gate duplo**
(`AG-383-addendum`, `63081ee`), a viabilidade de amostra do Meta é bem
mais apertada do que o design doc supõe.

**Quatro correções de especificação, todas medidas contra artefato real:**

1. **`§10.1(d)` está errado.** Manda asserir `n_unique(calibrator_id) ==
   2 × n_unique(fold_id)` (=30 para 15 folds); o real nunca é 30 (10, 12,
   18 ou 26 conforme a rodada), porque existe o valor literal `"n/a"` e
   porque 8 dos 15 folds não sinalizam. A asserção do documento
   reprovaria todo artefato real que existe. Substituída por verificação
   **estrutural linha a linha** contra
   `{model_id}_side{side}_fold{fold}_calibrator` — mais forte, porque uma
   contagem certa com atribuição trocada passaria no documento e falha
   aqui. Validada: 0 divergências em 6.142 linhas de sinal.
2. **`§10.1(c)` é logicamente redundante** dadas (a) e (b): `test_idx[s]`
   e `train_idx[s]` são disjuntos, então (b) sempre dispara antes.
   Mantida assim mesmo (barata, e `AG-153` abre o espaço de CV com blocos
   sobrepostos onde ela passa a ser a única a pegar o caso).
3. **A chave primária do `§3.1` não é única** — falta `meta_split_id`: sob
   `path_matched` uma linha é treino de 2 meta-folds e teste de 1.
4. **O `§12` aponta para o writer errado.** Manda parametrizar
   `write_predictions_atomic`, que **nunca** é chamado no ramo
   `resolution_id` (`pipeline.py:1327-1328` é o ramo `tf` legado; R1 vai
   por `write_predictions_versioned`, `:1212`/`:1250`).

**Rede de reprodutibilidade criada antes de mexer em `cpcv.py`.**
`tests/golden/test_validation_cpcv_pooling_non_regression.py` capturou o
baseline bit-a-bit dos **15 combos** (5 símbolos × R1/R2/R3) sobre o
`cpcv.py` atual, por SHA-256 de `train_idx`/`test_idx`/`group_id` —
contagens iguais não provam que os índices são os mesmos. Sem esse
"antes", `AG-151` não teria como provar que não invalidou as medições já
registradas. Achado colateral: **não existe hoje nenhum golden ATIVO sobre
a grade R1/R2/R3** (`test_sprint8_reproducibility.py` está inteiramente
`skip`ado por `AG-257`) — `AG-386`.

**AGs abertos nesta rodada:** `AG-384` (HMM canônico sem caminho de
produção — fechado no mesmo commit), `AG-385` (`regime_labels_present`
calculado e nunca lido), `AG-386` (sem golden ativo em R1/R2/R3),
`AG-387` (`realize_trades` devolve schemas diferentes nos dois ramos),
`AG-388` (peso de classe implícito de 1,3027 no Alpha).

**Nota de procedência:** esta rodada correu com uma **sessão paralela no
mesmo working tree**. `config/constants.yaml::meta_include_nofill_in_training`
foi escrita aqui mas entrou no repo por `ee46c25`, cuja mensagem trata de
outro assunto. Conteúdo íntegro; a justificativa da constante está no
commit `9becbaa`.

---

### 15.31 Meta-model — F4/F5 (learner, tau_meta, serialização), e a otimização de EM do regime HMM (2026-08-30)

Continuação direta de `§15.30`, mesmo dia.

**F4 — `src/models/meta.py`.** `MetaLearner` (Protocol runtime-checkable):
`fit`/`predict_score`/`coefficient_shares`/`serialize`. `predict_score`,
nunca `predict_proba` (§7.1) — o consumo é por quantil in-fold e D-07
removeu o calibrador, então o nome não pode sugerir probabilidade
calibrada. `LogitL2Meta` (default e único habilitado) e `BlockedGBMMeta`
(levanta em todos os métodos — não é placeholder, é o gate de §7.3
materializado num objeto que falha em vez de um comentário que alguém
pode não ler). `assert_sample_sufficient` (piso EPV sobre `Σ
uniqueness_subpop` da classe minoritária, recalculado por fold) e
`check_design_rank` (substitui a guarda de "variância zero" da v1, que
não pega colinearidade — arquétipo real: `regime_tradeable`).

`ScoreRankTransform` implementa a correção da v3 sobre o §3.4: o default
do design matrix é `rank(score_alpha_raw)` dentro do fold, não z-score —
`score_*_raw` já é `predict_proba(...)[:,1]`, já vive em `[0,1]`; a
não-comparabilidade entre folds é do MAPEAMENTO score→P(y), que z-score
(linear) não corrige. A implementação respeita B03 de um jeito que o
design doc não detalhava: a CDF empírica é ajustada NO TREINO e o teste é
mapeado através dela por busca binária — um `rankdata` sobre treino ∪
teste vazaria de um jeito invisível a `leakage.py` (o teste #11 procura
`fit` de objeto sklearn, e `rankdata` não tem `fit` nenhum).

Warning investigado até a causa raiz, não silenciado: o §7.2 escreve
`LogisticRegression(penalty="l2", ...)` literalmente; medido que
`scikit-learn` 1.9.0 deprecou `penalty` (será removido em 1.10) — trocado
por `l1_ratio=0.0`, portável também ao piso 1.5 de `pyproject.toml`.

**F5 — `tau_meta` in-fold (§8.3) + serialização com linhagem (D-17).**
`resolve_tau_meta`: grade de quantis a priori
(`meta_tau_grid_quantiles`), escolhe o que MAXIMIZA a PnL líquida in-fold
do subconjunto aceito, empate decidido pelo MENOR pass-rate. Corrige o
mesmo defeito que a v3 já tinha identificado no epsilon de empate da v1
(`1e-6` sobre PnL somada nunca dispara, reduz a regra a argmax puro):
`meta_tau_tie_epsilon = 0,00055174`, `DERIVED` da mesma fórmula de
`round_trip_cost_bps` (`maker_fee=0,0002`, `taker_fee=0,0005`,
`round_trip_cost_bps_maker_prob=0,4942`) — verificado por cálculo direto
nesta sessão, não copiado de proposta anterior sem checar. Teste
dedicado reproduz o defeito exato: um gap de PnL de 0,0002 (maior que o
`1e-6` da v1, menor que o custo real de 1 trade) não é tratado como
empate sob o epsilon antigo e É tratado como empate sob o corrigido.

`apply_meta_filter` — veto-em-zero contra AFML §10.3 (D-05): a função não
tem nenhum caminho que produza valor de sinal diferente de `side_hat` ou
`0` — é garantia estrutural, não um teste que poderia ser esquecido.

`write_meta_fold_bundle`/`read_meta_fold_bundle`/`score_from_bundle` —
junta o learner serializado com `tau_meta` e a linhagem
(`alpha_model_id`/`meta_split_id`/`variant`/`resolution_id`) num ÚNICO
artefato atômico: os dois só fazem sentido juntos na inferência, e
escrevê-los separado abriria janela de inconsistência (processo morto no
meio, disco cheio). A linhagem aqui é só DADO — o enforcement de
coerência é trabalho de F7, que lê o campo mas não é escrito por F5.

**Regressão própria achada e corrigida no caminho**: o teste #8 de
`leakage.py` (grep estático por scaler global) começou a falhar porque a
docstring de `ScoreRankTransform` continha o token literal
`StandardScaler` ao explicar que a transformação NÃO é uma — falso
positivo do grep, corrigido reescrevendo sem o token, sem enfraquecer o
teste.

**A otimização de EM identificada em `§15.30` foi aplicada** (pedido
direto do Manager, depois de matar os 5 backfills — nenhum código até F5
chama `read_regime_hmm`, a necessidade real era só medir; ver
`docs/SPRINT_LOG.md`, seção "o backfill de regime HMM foi interrompido").
`src.regime.hmm_gaussian._fit_em_until_converged`: chama `fit_em` em
blocos de 5 iterações, para quando a melhora relativa da
log-verossimilhança cai abaixo de `hmm_gaussian_em_convergence_tol`
(nova, `1e-6`, `ASSUMED`, classe B, `sweep_required: true` — corrigindo
de propósito o erro já cometido com `hmm_gaussian_num_em_iters`, que
nasceu `sweep_required: false` sem justificativa). Garantia validada, não
suposta: chamar `fit_em` em blocos é bit-a-bit idêntico a uma única
chamada com a soma das iterações (M-step de forma fechada e sem estado
entre chamadas). Magnitude real da economia: `TBD — medir com 1 símbolo`
(decisão explícita do Manager de deixar a medição para quando o backfill
for retomado). Correção de citação: "437.630 barras" (commit `9becbaa`,
`AG-384`) estava errado — são **223.160** observações reais; `AG-384`
(fechado) não foi editado, `AG-384-ADDENDUM-1` registra a correção
(append-only).

**Testes**: 36 em `test_models_meta.py` (F4+F5), 22 em
`test_regime_hmm_gaussian.py` (16 pré-existentes + 6 novos, zero
regressão). 254 passed no conjunto dos módulos do Meta. Commits:
`d0168d6` (F4), `326e05c` (otimização de EM + correções), `6707ca7` (F5).

---
### 15.32 ADR-007 — Optuna real em produção, ZERO de 6 combos no gate duplo, override manual de 5 candidatos (2026-08-30/31)

Resposta ao pedido do Manager de medir, com Optuna real (`AG-371`
fechado por reformulação — substitui o YAML estático de hiperparâmetro
por combo) e rigor contra falso-positivo, os 5 gaps abertos após
`AG-382`/`AG-383` (H10). Documento completo: `docs/ADR-007_medicao_
producao_hiperparametro_optuna_15_combos_2026-08-30.md`.

**Item 1** (busca expandida, `alpha_optuna_n_trials` 30→150, 6 combos
com edge bruto médio positivo, não-R1): 1.800/1.800 trials, 0 falhas,
2h32m18s. `SOLUSDT/R2` com `best_value` extremo nas 2 camadas (22,22/
8,96 vs. p95≈0,82 da campanha) — não tratado como sinal real, aguardou
confirmação.

**Item 2** (confirmação profunda, top-6 × 10 seeds × 2 camadas):
720/720 confirmações, 0 falhas. **ZERO dos 6 combos passa o gate
duplo** (`median_n_better`: `BTCUSDT/R3`=2,5, `BTCUSDT/R2`=3,0,
`SOLUSDT/R2`=2,5, `SOLUSDT/R3`=3,0, `XRPUSDT/R2`=2,0, `XRPUSDT/R3`=2,5
— nenhum atinge o piso 4,0). `SOLUSDT/R2` confirma a anomalia do Item
1 como ruído puro de screening — **viés de seleção +8,356, recorde do
projeto** (anterior: +0,772, `ADR-002`).

**Item 3** (calibração `AG-220`, FPR do gate duplo sob permutação
nula, 3 combos representativos): 300/300 retreinos, 2 bugs reais
achados e corrigidos na primeira execução real (`vol_estimator_id` sob
R3; `feature_ids=None` sobrescrevendo default de `run_all_folds`).
FPR sob ruído puro: `BTCUSDT/R3`=8,0%, `ETHUSDT/R1`=0,0%,
`BNBUSDT/R1`=0,0% — abaixo do piso `alpha_prune_max_gate_fpr=0,20`. O
gate NÃO é impossível de passar por acaso; o "ZERO combos" do Item 2
não é instrumento quebrado, a ausência de sinal é real.

**Item 4** (correção FDR, BH+BY, `src/validation/fdr_correction.py`):
aplicada à taxa-base H0-H7 (15 z-scores reais): 7/15 significativos
sem correção → 4/15 (BH) → 3/15 (BY). Ainda não aplicada ao resultado
dos Itens 1-2 (estatística de teste correta não decidida, `AG-389`).

**Item 5** (critério operacional de poda): registrado
(`alpha_prune_min_edge_bps_threshold`/`alpha_prune_max_gate_fpr`), não
aplicado — decisão de mudar o escopo de treino fica com o Manager.

**Decisão do Manager, fora do escopo formal da ADR (mesma sessão)**:
apesar da reprovação nos 5 itens acima, **override manual promovendo 5
candidatos a produção canônica** — `BTCUSDT/R2`, `SOLUSDT/R2`,
`SOLUSDT/R3`, `XRPUSDT/R2`, `XRPUSDT/R3` (`BTCUSDT/R3` excluído
deliberadamente). `config/constants.yaml::alpha_production_
hyperparam_override`. `N_lifetime`: 2.636 → 5.510 nesta ADR (`id=38`
a `id=40`). Ver `§15.33` — os mesmos 5 candidatos foram em seguida
auditados sob walk-forward real e nenhum sobrevive.

### 15.33 ADR-008 — Auditoria institucional ML/Alpha, walk-forward real refuta os 5 candidatos do ADR-007 (2026-08-31)

Especificação do Manager (14 blocos + prioridade 10 — leakage,
walk-forward, Rank IC, IC IR, quantile returns, feature/SHAP
stability, regime stability, reprodutibilidade), auditada por agente
contra código real, sequenciada em 9 fases por dependência. Documento
completo: `docs/ADR-008_auditoria_ml_alpha_institucional_score_
quality_walkforward_2026-08-31.md`.

**Fases 0-3** (infraestrutura de medição, zero custo de retreino):
paridade de proveniência; `score_quality.py` (IC/Rank IC/IC IR,
AUC/PR-AUC/LogLoss/Brier, Q10-Q1 sobre o `confidence` calibrado —
nunca medido antes pro output final do modelo); 4 itens paralelos
(feature/label audit, trajetória Optuna completa, estratificação
temporal); `train_val_test_gap` (generalization gap in-sample).

**Fase 4** (walk-forward real, ancorado, `initial_train_years=2`,
passo trimestral): campanha completa sobre os 5 candidatos, 3 bugs
reais corrigidos rodando pela primeira vez (2 linhas/barra não-
monotônico em `t0`; fold com 0 barras de teste válidas quebrando
`predict_proba`; critério de "fold degenerado" corrigido de
`n_test_bars` pra `n_filled_trades<10` depois de um Sharpe patológico
de 47.163,5 sobre 2 trades). **Achado bruto**: taxa de fold degenerado
alta em TODOS os 5 candidatos, Sharpe/edge majoritariamente
NEGATIVOS — quadro oposto ao CPCV que embasou a promoção (`n_lifetime`
id=41, todos positivos). `n_lifetime` id=42.

**Fase 5** (stability matrix — cruza Fold × IC/AUC/gain/decile): AUC
out-of-time perto de 0,50 (às vezes exatamente 0,500, std=0,000) na
maioria dos combos/lados; dispersão de IC entre folds tipicamente
MAIOR que a própria média (ruído, não sinal); gain concentrado em 1-2
features na maioria dos combos.

**Fase 6** (gates codificados Data/Model/Alpha): **0 de 10
combo×variant passam os 3 gates simultaneamente**.

**Fase 7** (SHAP, `TreeExplainer`): concordância gain×SHAP varia de
0,00 a 1,00 entre combos/lados — gain nativo e SHAP frequentemente
apontam features DIFERENTES como #1 (medem coisas diferentes: uso de
split vs. contribuição real à predição).

**Fase 8** (cartão final): consolida as 6 métricas reais + 2 `TBD`
deliberados (B23 — `regime_stability_pct`/`generalization_gap_pct`
nunca medidos). **1 de 20** combo×variant×lado passava sob o threshold
original.

**Correção pós-Fase-8** ("investigar e medir os thresholds
corretamente", Manager): os 2 thresholds da Fase 6 eram `ASSUMED`,
explicitamente "arbitrário por ora". Medidos contra os 62 fold-lado
reais: gate Model virou teste-t (Hanley-McNeil 1982 mostrou
`SE(AUC|H0=0,5)` entre 0,13-0,19 por fold, piso fixo de 0,52 sem poder
estatístico real); gate Data virou piso ABSOLUTO de 10 folds usáveis
(não fração). Sob a forma corrigida: **0 de 20** (o único caso que
passava tinha só `n=2` folds computáveis).

**Auditoria de engenharia** (Workflow adversarial, 5 agentes + segundo
revisor cético por módulo): 6 defeitos reais confirmados e corrigidos
(bucketing de decil não-determinístico; correlação/AUC degenerada com
`n=2`; diagnóstico de treino por lado descartado; gate estatístico sem
FDR e com convenção divergente em `std=0`; métrica de nível errado no
cartão final; `None`/JSON-`null` vazando pra campo `float`). Veredito
final não muda (0/20), fica mais rigoroso.

**Decisão final** (Manager delegou ao Chief Architect): sweep de
sensibilidade ±50%+ (classe A) confirma robustez — veredito composto
0/10 em TODA a grade testada. Thresholds **travados**. `AG-392` (4
achados de metodologia da auditoria): 3 resolvidos por medição/decisão
(autocorrelação lag-1 do AUC predominantemente NEGATIVA, não sustenta
teste anti-conservador; denominadores Data/Model not-a-bug; piso de 10
validado empiricamente pro papel de Sharpe), 1 adiado deliberadamente
(`Metric`/`Unit` não adotado, backlog).

**Conclusão consolidada**: nenhum dos 5 candidatos promovidos em
`ADR-007` (§15.32) sobrevive ao gate duplo desta auditoria sob
avaliação walk-forward estritamente fora-da-amostra no tempo. Decisão
sobre os 5 candidatos em produção segue com o Manager. Dashboard ao
vivo: artefato "ADR-007 — Painel de Execução"
(`https://claude.ai/code/artifact/ed42926f-90e2-4acd-bf61-58a9e05d9604`),
aba "ADR-008 — Fases 0-8". `audit/architecture_gaps_log.yaml::AG-391`
(aberto, achado consolidado)/`AG-392` (3/4 resolvidos).

### 15.34 Meta-model — P1/`AG-151` fechado: `edges_ms` sobre união temporal cross-símbolo (D-16) (2026-08-31)

Sessão paralela à `ADR-007`/`ADR-008` (§15.32/§15.33) — retomei o
Meta-model (`docs/meta_model_design_doc_2026-08-22.md` §15.2) onde F5
parou. F6 segue bloqueado por P0 (nulo do Gate E0) e P1 (`AG-151`,
purge cross-símbolo). Com o Alpha medindo 0/20 (`§15.33`), confirmei
com o Manager se valia priorizar infra do Meta mesmo assim — decisão:
sim, P1 é código puro ortogonal ao edge do Alpha, serve de infra
`hipótese→teste` (`CLAUDE.md`) independente do resultado da outra
trilha, e não conflita com os arquivos que a sessão do ADR-008 edita
ao vivo.

`src/validation/cpcv.py` (commit `cc83208`): `assign_time_groups`
particionava `[min(t0), max(t0)]` LOCAL de cada símbolo via `linspace`
— símbolos de histórico diferente (BTC desde 2020-01 vs. listagens
posteriores) produzem fronteiras de grupo em datas diferentes, e
`group_id == g` deixa de identificar a mesma janela de calendário
entre símbolos; sob pooling cross-símbolo (correlação medida 0,70-0,83,
`AG-144`), o purge por `t1` nunca veria essa correlação. Fix aditivo:
`assign_time_groups`/`generate_splits` ganham `edges_ms` opcional —
`None` (default) é bit-exato ao comportamento de sempre, provado pelo
golden capturado no F0 (commit `7b86a16`) ANTES da edição. Nova
`compute_pooled_edges_ms(t0_ms_by_symbol, n_groups)` calcula as
fronteiras sobre a UNIÃO de `t0` — bit-exata para o símbolo de maior
extensão do pool (BTCUSDT), não invalida medições single-symbol já
feitas. `_linspace_edges_ms` extraído como núcleo puro compartilhado
entre os dois caminhos.

**Verificação**: 9 testes novos (72/72 em `test_validation_cpcv.py`,
incluindo a prova de bit-exatidão pro BTCUSDT), golden de não-regressão
15/15 nos combos símbolo×resolução reais (`tests/golden/test_
validation_cpcv_pooling_non_regression.py`), suíte `unit` completa
2709/2710 (1 falha pré-existente em `test_analysis_tau_diagnostics.py`,
zero dependência de `cpcv`/`validation`, confirmada via `git stash`).

`AG-151` fechado (`resolved_by_commit: cc83208`). Escopo deliberadamente
contido à primitiva — orquestração de carregamento pooled multi-símbolo
é o próprio F1 de pooling cross-símbolo do Meta, ainda não construído;
custo em amostra sob calendário compartilhado continua `TBD — medir
quando o pooling for exercitado`.

**Próximo passo**: P0 (validação do nulo do Gate E0, circular-shift-
by-block) — módulo novo `src/analysis/meta_fp_inventory.py`, ainda não
iniciado; exige rodar validação empírica contra dado real (§2.6 do
design doc).

### 15.35 Meta-model — P0: esquema de permutação do Gate E0 travado + validação obrigatória do nulo (D-14) (2026-08-31)

`src/analysis/meta_fp_inventory.py` (novo, commit `df5e9cf`) — as duas
peças bloqueantes de P0 (`docs/meta_model_design_doc_2026-08-22.md`
§2.6, §15.1/§15.2). Zero treino, camada `analysis/` (mesmo precedente
de `gate_efficiency.py`).

**`circular_shift_by_time`** — a primitiva "circular-shift por bloco"
travada na v3. **Decisão de interpretação documentada** (o texto do
design doc não fecha 100% a granularidade do deslocamento): rotação
circular em TEMPO CONTÍNUO da série inteira, via busca binária contra
a função em degrau original — preserva estrutura de blocos contíguos
por construção (nenhuma reordenação interna), sem quantizar o
deslocamento em múltiplos de largura de grupo. Justificativa: `alpha_
b1_n_seeds = 1000` (a constante que o próprio §2.6 aponta para `n_
seeds`) é ordens de grandeza maior que `n_groups = 6` — um esquema
quantizado só teria 6 deslocamentos distintos possíveis. "Comprimento
de bloco... largura de grupo do CPCV" entra como diagnóstico reportado
(`effective_block_count`), não como granularidade do sorteio. **Se
essa leitura divergir da intenção original do design doc, sinalizar
antes de tratar P0 como fechado** — mesma classe de gap que motivou
`AG-114`/`AG-118`/`AG-122`.

**`weighted_state_auc`** — a estatística agregada do gate: AUC
ponderada por `uniqueness` entre `y_fp` (`SL`→FP duro, `TP`→acerto,
`TIME`→`1[ret_net>0]`, `NOFILL` excluído do numerador/denominador) e
`P̂(y=1|estado)` do próprio regime — REAJUSTADA a cada chamada, nunca
cacheada entre permutações (texto literal do §2.6: "o estimador é
reajustado dentro de cada permutação").

**`validate_null_calibration`** — a validação OBRIGATÓRIA e
BLOQUEANTE do próprio nulo (§2.6: "se o nulo não rejeita ruído
estruturado, E0 não roda"). Roda o procedimento completo (observado +
nulo + p95 + PASS/FAIL) `n_trials` vezes sobre uma feature sabidamente
sem sinal, mede a taxa de PASS empírica. "Materialmente acima de 5%"
operacionalizado via intervalo de confiança binomial de 95% (Wilson,
`scipy.stats.binomtest`), não uma banda de tolerância inventada.
Desenho deliberadamente NÃO tautológico — documentado em detalhe no
docstring do módulo ("por que a validação não é tautológica"): o
"observado" de cada trial usa uma família de amostragem diferente dos
deslocamentos do nulo interno daquele mesmo trial.

**3 constantes novas**: `meta_e0_null_percentile` (0,95, LITERATURE,
texto literal do §2.6 — "PASS sse... exceder o p95 do nulo"), `meta_
e0_null_calibration_target` (0,05, DERIVED de `meta_e0_null_
percentile`), `meta_e0_null_calibration_confidence_level` (0,95,
LITERATURE, convenção de IC — constante DIAGNÓSTICA, distinta do
critério do gate em si).

**Verificação**: 21 testes novos, 100% sintéticos/determinísticos (sem
dependência de dado real) — propriedades da rotação (identidade em
shift=0, preserva multiset, preserva blocos contíguos, wraparound
correto), AUC ponderada (estado perfeitamente discriminativo → 1,0;
sem relação → ~0,5; guardas de <2 classes/<2 estados → `NaN`),
`evaluate_path_null`/`validate_null_calibration` (sinal forte tende a
passar, sem relação real fica com taxa de PASS plausível perto de 5%).
117 passed no conjunto com `meta.py`/`meta_dataset.py`, 7/7 contratos
do `importlinter` mantidos.

**Achado, não corrigido nesta sessão**: tentativa de medir a validação
do nulo contra `BTCUSDT/15m` REAL bloqueada por B15 — `config_hash`
dos labels legados (`9492d29c36b06cb1`) não bate com NENHUMA variante
atual de `LabelConfig.from_constants` testada (`parkinson_w20`/`gk_
yz_w20`/default). Grade 15m já era "provisória" por desenho (§2.6,
E0-piloto) — a medição real fica para quando essa reconciliação de
config for feita, não presumida como já calibrada.

**Escopo desta rodada**: só a primitiva de permutação + sua
auto-validação estatística. A inventariação completa de FP/TP sobre
`predictions.parquet` real (universo `side_hat != 0 ∧ is_oof`,
diagnósticos completos do §2.6: `n_distinct(p_alpha)`, V de Cramér,
estabilidade cross-fold) é P3/E0-piloto — **ainda não construída**,
próximo passo real depois de reconciliar a config dos labels legados
(ou decidir pular direto para dado R1/5-símbolos, e assim descartar
E0-piloto como "provisório" mesmo).

### 15.36 Meta-model — P0: medição real contra 5 símbolos × R2/R3 — 9/10 calibrado, 1 achado real (AG-402) (2026-08-31)

Decisão do Manager: "pula pro R2 e R3 dado real de 5 símbolos, 15m e
R1 não estou treinando no Alpha" — resolve a pendência do `§15.35`
sem precisar reconciliar o `config_hash` dos labels legados de 15m
(fora de escopo agora). Os 10 combos (5 símbolos × {R2,R3}) verificam
`config_hash` limpo sob `parkinson_w20`, sem o `B15` que bloqueava a
grade legada.

`tools/diagnostics/measure_meta_e0_null_calibration.py` (commit
`8734ec0`) roda `validate_null_calibration` real: universo =
`build_modeling_frame` por (símbolo, resolução) — quantile classifier
(sem artefato HMM persistido ainda) — sem replicar os 5 paths do CPCV
(cada path, reconstruído sem modelo real, cobre 100% do dataset; os 5
dariam a mesma população pra este teste puramente estatístico). Proxy
"sabidamente sem sinal": regime de OUTRO símbolo alinhado por
POSIÇÃO, em anel pelos 5 símbolos (texto literal do §2.6).
`n_trials=100`, `n_seeds_per_trial=100` por combo, ~37min total.

**2 bugs reais corrigidos no caminho** (commit `288fbc1`), nenhum
escondido: (1) `sys.path` faltando `src` ao rodar `.py` direto —
mesmo padrão já usado alhures em `tools/diagnostics/`; (2)
`SOLUSDT/R2` tem 2 linhas com `regime` nulo NO MEIO da série (não
warmup — `build_modeling_frame` já media/logava `n_missing_regime=2`)
— o mapeamento regime→int do script não filtrava, produzindo o
sentinela de overflow `int64` e derrubando a medição com `IndexError`
sem contexto no 2º de 10 combos. Corrigido na causa (filtro no
script) E na defesa (`meta_fp_inventory.py::weighted_state_positive_
rate` agora valida `state_ids ∈ [0, n_states)` e levanta
`MetaFpInventoryError` com contexto, protegendo qualquer chamador
futuro).

**Resultado** (`experiments/meta_e0_null_calibration_2026-08-31.json`,
`audit/evidence_ledger.yaml::meta-p0-validacao-do-nulo-9-de-10-2026-
08-31`): **9 de 10 combos BEM CALIBRADOS** — taxa de PASS entre 2% e
8%, todos com IC de 95% cobrindo o alvo nominal de 5%. **1 de 10 NÃO
calibrado**: `XRPUSDT/R3` (proxy `BTCUSDT`) — taxa de PASS 14%, IC
`[7,9%; 22,4%]`. Verificado por cálculo direto que NÃO é ruído
amostral: `z=4,13` sob H0 (`p0=5%`, `n=100`), `P(X≥14)=0,00046` —
sobrevive correção Bonferroni por 10 testes (`α` por teste ajustado a
0,005) com folga de 10×.

Investigação parcial (não esgotada, Regra Zero — não inventar
conclusão): a distribuição MARGINAL de estados do proxy `BTCUSDT/R3`
truncado (2020-01-07 a 2025-02-21) e a de `XRPUSDT/R3` completa são
muito parecidas (estado dominante ~34k em ambas, proporções batendo
dentro de ~10%) — descarta desalinhamento GROSSEIRO. Hipótese de
trabalho, NÃO confirmada: persistência/autocorrelação do regime de
BTC pode diferir da de XRP o bastante pra produzir uma configuração
de alinhamento posicional ocasionalmente "ressonante" que o nulo (que
só re-embaralha a MESMA fatia do proxy) não captura — BTC e XRP são o
par de maior assimetria de histórico entre os 5 símbolos (~6,6 anos
vs ~4,7 anos, o único par nesta configuração de anel com esse gap).
Registrado em `audit/architecture_gaps_log.yaml::AG-402` (aberto,
severidade média).

**Veredito de P0**: a primitiva do esquema de permutação FUNCIONA na
esmagadora maioria dos casos reais testados — medido, não presumido.
`AG-402` fica aberto, NÃO bloqueante pra considerar P0 validado, mas
relevante antes de tratar a calibração como uniformemente confiável
pra qualquer par de símbolos no E0-vinculante real — especialmente
envolvendo `XRPUSDT` (o símbolo de histórico mais curto dos 5).

**Próximo passo**: P2 (diagnóstico de saturação isotônica) e P3
(E0-piloto), OU investigar `AG-402` primeiro (proxy alternativo pra
`XRPUSDT/R3`, ex. `SOLUSDT` em vez de `BTCUSDT` — histórico mais
próximo, testaria diretamente a hipótese de assimetria) se o Manager
priorizar fechar essa dúvida antes de seguir adiante — decisão do
Manager, não tomada aqui.

### 15.37 Meta-model — P2: saturação isotônica real, 5 combos de produção (2026-08-31)

Manager: "Pode executar ponta a ponta" — em vez de retreinar Alpha em
R2/R3 pra gerar `predictions.parquet`, descoberto que os artefatos JÁ
EXISTEM em disco (`artifacts/predictions_alpha/`, escritos por
`run_layer1_sprint` numa sessão anterior, mesma que gerou os relatórios
`_adr007canonico.json` de hoje). `config_hash` de cada combo calculado
localmente (`hyperparams_by_combo.load_production_override` +
`io_artifact.compute_config_hash`, determinístico, sem executar nada) e
todos os 10 hashes (5 combos × 2 camadas) bateram com diretórios já
existentes — **zero retreino necessário**, só leitura.

`tools/diagnostics/measure_meta_p2_isotonic_saturation.py` mede
`n_distinct(p_alpha)` vs `n_distinct(score_raw)` na subpopulação
`side_hat != 0 ∧ is_oof`, por lado, sobre os 5 combos de produção reais
(`BTCUSDT/R2`, `SOLUSDT/R2`, `SOLUSDT/R3`, `XRPUSDT/R2`, `XRPUSDT/R3`
— os únicos com hiperparâmetro confirmado, não os 5 símbolos × 2
resoluções inteiros).

**Resultado**: razão de saturação (`p_alpha`/`score_raw`) consistentemente
BAIXA — entre 0,081 (`BTCUSDT/R2` short) e 0,667 (`SOLUSDT/R2` short,
mas `n=36`, amostra minúscula). O calibrador isotônico colapsa 77-92%
dos scores brutos distintos em poucos níveis de probabilidade (ex.
`BTCUSDT/R2` long: 1.370 scores brutos → só 144 níveis de `p_alpha`).
Esperado de regressão isotônica (função em degrau), mas a magnitude é
real — relevante pra resolução da seleção de `tau_meta` por quantil
(§8.3) se o Meta chegar a essa etapa. Registrado em `evidence_ledger.yaml`
(`meta-p2-saturacao-isotonica-2026-08-31`, status amarelo — achado real,
não necessariamente invalidante sozinho).

### 15.38 Meta-model — P3: Gate E0 REAL — 0 de 5 combos passam (AG-404) (2026-08-31)

**A peça consequente.** `tools/diagnostics/measure_meta_p3_e0_piloto.py`
roda o inventário completo de FP/TP + a decisão REAL do Gate E0 (não
mais "piloto"/legado — decisão do Manager, R2/R3, dado real) sobre os
mesmos 5 combos de produção, Camada1. Universo: `side_hat != 0 ∧
is_oof`, joinado a `labels` por `(t0, side_hat) → (t0, side)` via
`meta_fp_inventory.join_predictions_to_universe` (novo). `path_id` via
`meta_fp_inventory.path_id_by_fold` (mapeia `fold_id` → `path_id` do
CPCV). `n_seeds = alpha_b1_n_seeds = 1000` — o orçamento de PRODUÇÃO
(P0 já validou a calibração do esquema com orçamento reduzido, `§15.36`).
Runtime real: ~106s pros 5 combos (populações pequenas, ~260-2800 linhas
por combo — nada a ver com o custo do P0, que rodava sobre o dataset
inteiro).

**Resultado: 0 de 5 combos passam o Gate E0** (critério travado do
§2.6: PASS sse AUC ponderada observada exceder o p95 do nulo em ≥4 dos
5 paths). `BTCUSDT/R2`: 0/5 paths — nenhum chega perto (AUC observada
0,53-0,57 contra p95 do nulo 0,56-0,62 em TODOS os 5). `SOLUSDT/R2`:
3/5 — o melhor resultado dos 5 combos, ainda abaixo do piso de 4.
`SOLUSDT/R3`, `XRPUSDT/R2`, `XRPUSDT/R3`: 1/5 cada.

`fp_rate` (taxa de falso-positivo entre trades preenchidos) entre 40,8%
e 45,5% nos 5 combos — próximo de moeda honesta, **mesma ordem de
grandeza do achado independente "0/20" do próprio Alpha** (`AG-391`,
ADR-008, `§15.33`). `pnl_fp_total` (teto teórico de um filtro perfeito)
negativo nos 5. V de Cramér (`regime` × `group_id` do CPCV): 0,155 a
0,301 — fraca-a-moderada, não sustenta "regime é só carimbo de data"
mas também não é desprezível. Estabilidade estado→característica:
estado `R0` (o mais raro, ~0,1% das barras globalmente) teve **zero
ocorrências na subpopulação sinalizada em TODOS os 5 combos** — o
Alpha praticamente nunca sinaliza sob esse regime.

**Por que isto importa mais do que um resultado isolado**: converge com
o achado "0/20" do Alpha (`§15.33`) por um caminho de medição
COMPLETAMENTE DIFERENTE — ADR-008 mede AUC out-of-time do próprio score
do Alpha via walk-forward ancorado real; este Gate E0 mede se `regime`
discrimina FP de TP DENTRO do universo já sinalizado pelo Alpha, via
permutação circular-shift-by-block (a mesma primitiva que `§15.36`
validou contra dado real, `AG-402`). Duas medições independentes,
metodologias diferentes, mesma conclusão qualitativa: nenhum sinal
robusto detectável fora da amostra em NENHUMA das duas camadas do
motor (Alpha nem Meta), nos 5 candidatos reais medidos.

**Consequência pré-declarada, não executada unilateralmente**: o
próprio design doc declara ANTES de qualquer número real existir
(§15.2, P3): *"falha em ≥2 paths ⟹ registro em evidence_ledger + Meta
sai do roadmap."* Os 5 combos falham com 2 a 5 paths reprovados cada —
a consequência pré-declarada está tecnicamente disparada pelos números
medidos. **Esta sessão NÃO aplicou essa consequência unilateralmente**
— é decisão do Manager, não de código, registrada como tal em
`evidence_ledger.yaml` (`meta-p3-gate-e0-0-de-5-2026-08-31`, vermelho)
e `architecture_gaps_log.yaml::AG-404` (aberto, severidade alta, achado
consolidado — mesmo padrão de `AG-391`).

**Decisões que ficam com o Manager, não tomadas aqui**: (a) aplicar a
consequência pré-declarada como escrita; (b) revisitar à luz do quadro
mais amplo (Alpha TAMBÉM em 0/20 — a decisão pode ser sobre o motor
inteiro, não só o Meta); (c) investigar mais antes de decidir (os 2
casos menos ruins — `SOLUSDT/R2` 3/5, e o path de `XRPUSDT/R3` com
AUC=0,80 mas `n=26` — merecem uma segunda olhada antes do veredito
final, se o Manager quiser essa investigação extra).

### 15.39 Meta-model — F6: ablação REAL — 0 de 5 símbolos passam o critério primário (AG-409) (2026-09-01)

**Decisão do Manager (2026-08-31/09-01)**: "Não é impeditivo agora,
finalize a construção do meta model mesmo assim... continue" — a
consequência pré-declarada do `§9` (`AG-404`) não bloqueia F6+.

**Peça que faltava antes de F6 poder existir**: `meta.py` tinha o
learner/`tau_meta`/bundle (F4/F5) mas não a orquestração fold-a-fold.
`run_meta_fold`/`run_all_meta_folds`/`run_meta_sprint` (novo, commit
`90061dc`) treinam/avaliam por fold e assembleiam as predições OOS —
equivalente de `pipeline.run_layer1_sprint` pro Meta. Recebe `predictions`/
`dense`/`cpcv_result` do CHAMADOR (§4.7), não resolve o hiperparâmetro do
Alpha internamente.

**Duas políticas de veto**: linha de TESTE `meta_status != OK` (regime
nunca visto) vetada incondicionalmente; fold inteiro incapaz de ajustar
modelo → pass-through (`accept=True`, `p_meta=null`). 2 causas
distintas sob a mesma política: `INSUFFICIENT_SAMPLE` (piso de EPV,
§7.3) e `RANK_DEFICIENT` (achado real, novo — `META_STATUS_RANK_
DEFICIENT`, `meta_dataset.py` — um fold pequeno pode nunca observar
algum nível de regime, deixando a dummy colinear; o design doc nunca
declarou este caso operacionalmente, decisão por analogia ao §7.3).

**`meta_ablation.py`** (F6, commit `8951b7f`) — A0 (Alpha sem filtro),
A1 (reusa `test_predictions`), A2 (nulo — embaralha os SCORES REAIS de
A1, não reajusta modelo, roda a MESMA busca de `tau_meta` sobre o
embaralhado), A3 (top-k por `p_alpha` pareado em pass-rate por estrato
`meta_split_id`/`symbol`/`side_hat`, vira gate). **Decisão do Manager,
perguntada antes de implementar**: `meta_logit_c` fica FIXO, sem busca
em-fold — o design doc lista 5 "escolhas de A1 replicadas em A2" mas só
dá o range de `C` (`[0.5,1.5]`), nunca a grade nem confirma busca real;
construir infraestrutura nova arriscava mais que resolvia. Consequência:
dos 5 itens, só 1 (resolução de `tau_meta`) precisa de lógica de
replicação própria — os outros 4 são triviais (constante global
compartilhada ou builder de design matrix já compartilhado por A1/A2).

**Resultado real** (`tools/diagnostics/measure_meta_f6_ablation.py`, 5
combos de produção, `n_seeds=200`, `experiments/meta_f6_ablation_2026-
09-01.json`): **0 de 5 símbolos passam o critério PRIMÁRIO** (§9:
permanência sobre símbolos, não paths) — nenhum combo tem sequer 1 path
aprovado (precisa ≥4/5). Dois achados adicionais medidos, não previstos
a priori:

1. `SOLUSDT/R3` e `XRPUSDT/R3` têm **ZERO de 15 folds** ajustando
   modelo — grade R3 (dollar bar mais grosso) tem sinal escasso demais
   pro piso de EPV (90 eventos efetivos, §7.3). O Meta NUNCA treina de
   verdade nesses 2 combos.
2. **Jaccard(A1,A3) = 1,000 EXATO** em quase todos os paths de 4 dos 5
   combos (exceção parcial: `BTCUSDT/R2`, 0,817-1,000) — o conjunto
   aceito pelo Meta é IDÊNTICO ao do baseline ingênuo top-k por
   `p_alpha`. Sinal direto: o filtro aprendido é, na prática, uma
   reparametrização de `tau` sobre `p_alpha`, não seleção baseada em
   `regime` — o resultado nulo que o próprio §3.4 já identificava como
   o mais provável, e evidência CONTRA D-01 (regime como vantagem
   informacional central).

`XRPUSDT/R2` disparou `exposure_reduction_suspected=True` — o modo de
falha concreto que abre o §9 (accuracy não supera a taxa base, mas
`pass_rate` caiu), materializado como campo medido, não só prosa de
aviso.

**Terceira medição negativa independente, convergente**: `AG-391`
(Alpha via walk-forward real, 0/20, `§15.33`), `AG-404` (Gate E0 via
permutação, 0/5, `§15.38`), agora `AG-409` (F6 via ablação com nulo de
score embaralhado, 0/5 símbolos). Três metodologias completamente
diferentes, mesma conclusão qualitativa. Registrado, **não bloqueante**
por decisão explícita do Manager — F7/F8 seguem.

**Addendum 2026-09-01 (`AG-412`) — a pré-condição bloqueante do `§4.3`
nunca tinha rodado.** Revisando o design doc antes de iniciar F6b:
`§4.3` declara o controle positivo sintético (injeta
`p_alpha' = (1−λ)·p_alpha + λ·y_meta` numa grade a priori, verifica
Sharpe crescente em λ) **pré-condição bloqueante de F6** — "Falha ⟹ F6
não roda". `meta_ablation.py` já documentava que não reverifica isso
("é responsabilidade do chamador"); `measure_meta_f6_ablation.py`
nunca chamou `run_leakage_positive_control`. A trava foi pulada **em
silêncio** antes da medição real que produziu `AG-409`.

Fechado retroativamente (`tools/diagnostics/measure_meta_positive_
control.py`, novo): só **`BTCUSDT/R2` detecta** o vazamento injetado
(0,1056→0,1729, estritamente crescente) — é também o único combo com
maioria de folds ajustando modelo de verdade (10/15, `AG-409`),
confirmando que a reprovação de F6 ali é medição interpretável, não
artefato de harness cego. Os outros 4 combos não detectam — corolário
direto da amostra insuficiente já documentada em `AG-409`
(`SOLUSDT/R3`/`XRPUSDT/R3` 0/15 folds, `SOLUSDT/R2` 1/15,
`XRPUSDT/R2` 2/15 com detecção parcial: cresce em 4 dos 5 passos da
grade, empata no último). Não muda nenhum veredito de `AG-409` — fecha
uma lacuna de disciplina de medição, não descobre um resultado novo.
Achado colateral corrigido no mesmo commit: "λ"/"Σ" gregos em mensagens
de log de `run_leakage_positive_control`/`inject_synthetic_leakage`
quebravam `logger.info` em console Windows cp1252 (mesma classe de bug
já fechada uma vez em `meta.py::assert_sample_sufficient`). Detalhe
completo: `evidence_ledger.yaml::meta-controle-positivo-retroativo-2026-
09-01`, `architecture_gaps_log.yaml::AG-412`.

### 15.40 Meta-model — F6b: ablação sobre walk-forward ancorado — 0 de 5, mais decisivo que F6 (AG-413) (2026-09-01)

**§4.4 é taxativo**: um modelo CPCV é treinado em blocos com dado
POSTERIOR ao bloco de teste; o Alpha de produção só vê passado. "Gate
bloqueante": se a ablação passa sob CPCV mas não sob walk-forward
ancorado, o resultado CPCV é artefato. F6 (`AG-409`) já reprovou sob
CPCV — F6b confirma se a MESMA reprovação se sustenta sob a estrutura
de erro causal real.

**Decisão de design consultada ao Manager antes de implementar**
(`AskUserQuestion`, não inventada em silêncio): a regra de doador
`path_matched` do CPCV (`meta_dataset.donor_folds_for_path_matched`)
depende de múltiplos splits compartilhando o mesmo `path_id` —
propriedade EXCLUSIVA do CPCV. Sob walk-forward ancorado cada fold É
seu próprio `path_id` (`walk_forward.py`, "path_id=wf_split.fold_id...
deliberado") — aplicar `path_matched` sem adaptação zeraria o treino do
Meta em TODO fold por construção (verificado antes de escrever
qualquer código, não hipotético). O Manager escolheu **split causal
ÚNICO por combo**, não k-folds aninhados — menos código novo, evita
reproduzir uma primitiva de purge nova sobre uma timeline já muito mais
curta que o dado denso.

**Implementado**: `walk_forward.run_walk_forward_for_combo` ganhou
`keep_predictions: bool=False` (default preserva 100% do comportamento
de todo chamador do ADR-007/ADR-008 — mudança puramente aditiva).
`meta_dataset.build_meta_signal_table_wf_single_split` (novo) parte a
timeline OOS já causal do Alpha numa ÚNICA fronteira temporal
(`generate_anchored_walk_forward_splits` reusada, só a primeira
fronteira importa), purge por `t1` (B09, sem donor). `meta_walk_
forward.py` (novo) orquestra ponta a ponta. `meta_ablation.run_
ablation_for_combo` (F6, já existente) reusado SEM alteração,
`min_paths_required=1` — existe exatamente 1 path por construção, não
afrouxamento do limiar `≥4/5` do CPCV.

**Resultado real** (`tools/diagnostics/measure_meta_f6b_walk_
forward.py`, 5 combos de produção, `n_seeds=200`): **0 de 5 combos
passam** — mais severo que `AG-409`: os 5 caem em `INSUFFICIENT_
SAMPLE`, o Meta NUNCA ajusta modelo sob causalidade real, nem mesmo
`BTCUSDT/R2` (o único combo que ajustava em 10/15 folds sob
CPCV/`AG-409`). A timeline OOS causal é curta demais: `BTCUSDT/R2` usa
só 8 de 19 folds do Alpha (resto degenerado por trades insuficientes),
sobrando 94 linhas de treino do Meta (`n_events_eff=32,44` contra piso
`90,00`, §7.3). `SOLUSDT/R2` usa só 1 de 12 folds, sobrando 4 linhas de
TESTE.

**Quarta medição negativa independente, convergente**: `AG-391` (Alpha
walk-forward real, 0/20), `AG-404` (Gate E0 permutação, 0/5), `AG-409`
(F6/CPCV, 0/5 símbolos), agora `AG-413`. F6b é a MAIS decisiva das
quatro — não mede "sem edge detectável apesar de amostra suficiente",
mede "sem amostra suficiente pra sequer tentar" sob a estrutura causal
real de produção. Achado ACIONÁVEL: independente de D-01 estar certa
ou errada sobre regime, o Meta v1 não tem dado causal suficiente pros 5
candidatos reais HOJE — se reconsiderado no futuro, aumentar o
histórico causal disponível (ou pooling cross-símbolo via `AG-151`, já
fechado como primitiva) é PRÉ-REQUISITO antes de qualquer novo teste de
edge, não um detalhe de configuração. Consequência pré-declarada do
design doc ("Meta sai do roadmap") segue NÃO aplicada — decisão
explícita do Manager, mesma sessão. F7/F8 seguem. Detalhe completo:
`evidence_ledger.yaml::meta-f6b-walk-forward-0-de-5-2026-09-01`,
`architecture_gaps_log.yaml::AG-413`.

### 15.41 Meta-model — F7: enforcement de B07/B08 (D-13, §10) — as 5 camadas fechadas (2026-09-01)

**Estado antes desta correção** (design doc §10, texto original):
`banned_patterns.py:55-56` marcava B07/B08 `automated=False`; teste #10
era `NOT_APPLICABLE_V1_1`; teste #11 era regex só sobre `_ALPHA_PATH`;
contrato `alpha ↛ meta` era TODO comentado em `pyproject.toml`. Nenhum
achado novo aqui — é o gap que o próprio design doc já documentava,
fechado agora que F0-F6b deram ao Meta escopo real.

**Camada 1 (runtime, §10.1)** — já existia: `meta_dataset.assert_no_
meta_leakage` implementa as 4 asserções falsificáveis ((a) toda linha
OOF do próprio fold; (b) treino respeita purge/embargo do meta-fold —
"a mais importante"; (c) doador nunca é o próprio meta-fold; (d)
proveniência de `calibrator_id`/`model_id`), `raise MetaLeakageError`
nunca `assert`/`filter`. Não precisou de trabalho novo.

**Camada 2 (teste #10 real, §10.2)** — saiu de `NOT_APPLICABLE_V1_1`
pra auditoria estática real: confirma que as 4 asserções existem no
código-fonte E que cada uma tem CONTROLE POSITIVO obrigatório (1 teste
por asserção em `test_models_meta_dataset.py`, já existente desde F1,
confirmando que o builder levanta `MetaLeakageError` quando violado) —
sem controle positivo o teste não prova nada, mesma crítica que
`leakage.py` já fazia de si mesmo no teste 12.

**Camada 3 (teste #11 estendido, §10.3)** — `_META_PATH` adicionado
(não existia em lugar nenhum do código). Das 4 checagens de arquivo do
teste #11 original (Alpha), 3 propriedades análogas auditadas em
`meta.py`: (a) `LogitL2Meta.fit(self, X, y, w)` sem parâmetro de
teste/OOF; (b) `ScoreRankTransform.fit` (a normalização do Meta,
análoga ao scaler global) ajustada só com `train[...]`; (c)
`resolve_tau_meta` (o limiar de decisão, análogo ao calibrador do
Alpha — o Meta não tem calibrador, D-07) derivado só de
`score_train`/`ret_net_train`. `only_called_with_train` (a 4ª checagem
Alpha) já varria `src/models/` inteiro — sem extensão, conforme o
próprio §10.3 já apontava.

**Camada 4 (lint B07, §10.4)** — `automated=True` com allowlist.
Achado real rodando a checagem pela primeira vez: a regra ingênua
("arquivo em `src/models/` que menciona sinal do Alpha E `fit`/`train`
precisa mencionar `is_oof`") disparava em `meta.py`/`meta_ablation.py`
(sinal real, sem menção de `is_oof`) E em `persistence.py` (falso
positivo — formato de serialização, agnóstico a OOF). Corrigido:
adicionada uma nota de proveniência de `is_oof` no docstring de `meta.py`/
`meta_ablation.py` (a garantia vem de `assert_no_meta_leakage`,
documentada não reimplementada) e `persistence.py` entrou na allowlist
junto de `pipeline.py`/`_paths.py`. Verificado: 0 violações B07 novas
contra `src/` inteiro (50 `MAGIC_NUMBER` pré-existentes, não tocados —
fora de escopo desta tarefa).

**Camada 5 (import-linter, §10.5)** — contrato `alpha não importa meta`
formalizado (`source_modules=["src.models.alpha"]`,
`forbidden_modules=["src.models.meta", "meta_dataset", "meta_ablation",
"meta_walk_forward"]`). Verificado: `alpha.py` nunca importava nenhum
módulo do Meta antes desta correção — contrato trava o estado atual,
não corrige uma violação existente. `lint-imports`: 8 contratos
mantidos, 0 quebrados.

**Verificação real, não afirmada**: 165 testes (`test_validation_
leakage.py` + os 3 arquivos de teste do Meta) passam, incluindo 3
testes que citavam `NOT_APPLICABLE_V1_1` pro teste #10 e precisaram ser
atualizados pra `PASS`. F7 fecha D-13/§10 do design doc do Meta por
completo — as 5 camadas. Próximo: F8 (preencher `constants.yaml` com
valores MEDIDOS onde hoje é `TBD`, `N_lifetime++`).

### 15.42 Meta-model — F8: fecha o roadmap do design doc (2026-09-01)

**`N_lifetime++`** (`audit/n_lifetime.yaml`, ids 43/44, `counter`
5520→5530): F6 (`AG-409`, delta=5 — 1 ciclo de ajuste+avaliação por
combo, hiperparâmetro `meta_logit_c` fixo, sem busca) e F6b (`AG-413`,
delta=5 — idem, sob split causal único; o retreino do ALPHA em si
dentro de F6b NÃO é trial novo, é o mesmo cálculo determinístico já
contado no id 42). O controle positivo sintético (`AG-412`) NÃO
conta — é diagnóstico de sensibilidade do harness contra sinal
INJETADO/conhecido, não busca de edge real, mesma categoria de um
teste de regressão.

**Constantes `TBD` do `§11`** — revisadas uma a uma contra o estado
REAL do código (não a lista do design doc de cor):

- `meta_min_neff_for_gbm` — **segue `TBD`, corretamente**.
  `BlockedGBMMeta` levanta incondicionalmente (D-02); o gate não tem
  como abrir enquanto isso for verdade, e os achados desta sessão
  (`AG-409`/`AG-413`) tornam a pergunta ainda mais moot: se a
  LOGÍSTICA já não tem amostra suficiente pra ajustar em 4/5 combos
  sob CPCV e em TODOS os 5 sob walk-forward, um gate GBM (que exige
  amostra maior ainda) não tem nenhum caso real pra decidir hoje.
  Inventar um número agora violaria B23 sem propósito.
- `meta_p_threshold` — não é uma lacuna: já é resolvido por MECANISMO
  (`meta.resolve_tau_meta`, in-fold, §8.3), não por constante fixa.
  Confirmado no código, não apenas na prosa do design doc.
- `meta_min_lift`/`meta_min_auc_gain` — idem: o gate É o percentil do
  nulo (`meta_e0_null_percentile`, já existe e é usado em `meta_
  ablation.run_ablation_for_combo`/`meta_fp_inventory.evaluate_gate_
  e0`). Constante separada seria redundante.
- limiar de `weight_hhi` (§7.5, HHI do DoD sobre `coefficient_
  shares`) — **já implementado corretamente SEM limiar**, e por
  decisão DECLARADA no código (`meta.py::LogitL2Meta.coefficient_
  shares`, docstring): "o gate de HHI do DoD NÃO se aplica aqui na
  forma herdada do Alpha — um gate que só pode ser satisfeito quando
  a hipótese central (D-01) falha é pior que nenhum gate". Reportado
  sem limiar, por B23. Confirmado no código.
- limiar de `weight_hhi` (§5, `UniquenessDivergenceDiagnostic.weight_
  hhi`, `meta_dataset.py`) — mesma situação: docstring já declara
  "sem limiar de aprovação, de propósito (B23)... reporta o número;
  quem decide o critério é o Manager". Já correto.
- **"ganho esperado do Meta"** — segue `TBD`, e deve seguir: a medição
  REAL desta sessão, por QUATRO metodologias independentes
  (`AG-391`/`AG-404`/`AG-409`/`AG-413`), converge em zero/negativo ou
  "amostra insuficiente pra medir". Declarar um "ganho esperado"
  agora seria inventar um número que o próprio dado contradiz — a
  violação de B23 mais direta possível.

**Veredito de F8**: nenhuma constante nova precisava ser criada — as
6 listadas como "não criadas (B23)" no `§11` do design doc já eram,
uma a uma, corretamente não-criadas por desenho (2 resolvidas por
mecanismo, 2 já reportadas sem limiar por decisão declarada, 1 moot
por gate bloqueado, 1 que seria fabricação dado o resultado medido).
F8 fecha por CONFIRMAÇÃO, não por preenchimento. **Roadmap do design
doc completo: F0-F8, todas as fases fechadas.** Quatro medições
negativas independentes convergentes permanecem registradas
(`AG-391`/`AG-404`/`AG-409`/`AG-413`), decisão de produção sobre o
Meta-model segue com o Manager — não decidida unilateralmente aqui.

### 15.43 "Caso 0/20" — auditoria adversarial do veredito ADR-008 + roadmap de 17 itens, nenhum reverte "0/20" (2026-08-31/2026-09-01)

Sessão paralela à `§15.33`-`§15.42` (track Meta-model) — mandato
distinto: auditar o PRÓPRIO veredito "0/20" (`§15.33`) tentando
REFUTÁ-LO por ângulos novos, não confirmá-lo de novo. Pedido do
Manager: "Auditor de ML/Algo-Trading... refute um ângulo diferente,
não apenas confirme". Registro completo em artefato publicado ("Caso
0/20", `https://claude.ai/code/artifact/0323cb66-1042-4247-b07a-
1f58d81a3958`) e 2 documentos: `docs/adendo_angulos_7_8_pooled_meta_
analise_gate_model_alpha_2026-08-31.md` (autoria própria) e `docs/
prompts/REFUTACAO_CONSOLIDADA_0de20_20260831.md` (auditoria externa
consolidada pelo Manager). `audit/architecture_gaps_log.yaml::AG-394`
a `AG-419` (26 entradas), 33 commits, todos em `origin/master`.

**Fase 1 — 6 ângulos originais + 2 novos (Ângulos 7/8), nenhum
refuta**: vazamento temporal, viés de sobrevivência (exclusão de fold
degenerado), inversão de AUC, causa raiz da divergência CPCV-vs-
walk-forward, integridade de dado 2023-2026, recomputo independente
do "0/20" do zero (reproduz dígito a dígito) — todos SUSTENTAM.
Ângulo 7 (poder do gate Model via meta-análise de variância inversa):
AUC pooled portfólio = 0,5025 (Camada1)/0,4951 (Camada0), com poder
estatístico suficiente pra detectar AUC≥0,54-0,55 se existisse.
Ângulo 8 (gate Alpha sem teste, aplicando um via identidade
`t_stat=sharpe_naive·√(span_years)`): edge pooled = -3,32bps
(Camada1)/-0,84bps (Camada0), z negativo. Achado colateral real:
`BTCUSDT/R2` tinha bloco de coluna nula não documentado; `SOLUSDT/R2`
fold_id=3/short com calibrador isotônico colapsado (`y_calib` de 1
classe só) — corrigido com campo de visibilidade novo (`AG-393`).

**Fase 2 — consolidação em roadmap de 17 itens (P0-P3)**, fundindo o
adendo próprio com a auditoria externa (skill `frontend-design`, a
pedido do Manager). P0 (correções sem trade-off) e P2 (medições sem
retreino) fecham primeiro; P1 (achados que exigem retreino/decisão) e
P3 (backlog próprio) depois. Correções reais de produção aplicadas no
caminho: bug de `numpy.float64` vazando pro `ic_tstat` e quebrando
serialização JSON (achado ao rodar `train_val_test_gap` pela primeira
vez, corrigido em `score_quality.py`); gate Alpha vira teste-t real
com `edge_bps_std`/`edge_bps_p_value` (`AG-400`); correção FDR
consolidada nos 3 gates (`AG-405`); disclosure de que `edge_bps` é
bruto de spread/seleção adversa, decisão B23 deliberada, não bug
(`AG-408`); poder real dos gates medido por Monte Carlo — 31,2%
pra AUC=0,55, 23,8% pra edge=10bps, mesmo pós-correção (`AG-406`).

**Achado mais consequente da Fase 2 — `AG-399`**: seed do sampler
TPE Optuna era GLOBAL (42) compartilhada por TODAS as 10 studies de
produção, não derivada por combo/variant — `learning_rate` idêntico
até a 16ª casa entre `BTCUSDT/R2 C1` e `XRPUSDT/R3 C0`, `min_child_
samples=77` em 4 de 10 vencedores (`P≈2,9×10⁻⁶` sob sorteio
independente). Confirmado em código e corrigido (`_derived_sampler_
seed`, sha256 por combo) — vira default de produção pra qualquer
busca NOVA a partir de `a60c8c2`, mas os hiperparâmetros JÁ EM
PRODUÇÃO (`alpha_production_hyperparam_override`) continuam sendo os
achados sob o bug antigo, não re-promovidos por este achado sozinho
(ver Fase 4 abaixo).

**Fase 3 — P3 (backlog próprio, sem custo de retreino)**: bootstrap
em bloco substituindo a aproximação normal dos Ângulos 7/8 — AUC
pooled fica com SE MENOR que o paramétrico (reforça "0/20" com menos
incerteza), edge pooled fica com SE 2-2,5× MAIOR (a identidade via
`sharpe_naive` subestimava a incerteza real, sem mudar o veredito).
Condicionamento por regime (proxy fold-a-fold, `E05f_time_to_
funding_h`/`E16f_global_ls_ratio`, as 2 features SHAP-dominantes):
`E16f` varia >2× entre folds em 3 dos 5 combos — contradiz `R10` do
documento-fonte parcialmente — mas sem correlação detectável com
performance na granularidade de fold (n=36-46, poder baixo).

**Fase 4 — item 12 (corte `t0_end` na busca Optuna) rodado em escala
completa (150 trials × 10 studies) e sua CONFUSÃO real com `AG-399`
identificada e resolvida por campanha de controle**: a campanha com
corte de data mostrou 8/10 células melhorando vs. produção — mas essa
campanha TAMBÉM corrigia o bug do seed na mesma rodada, sem controle
isolando qual das duas mudanças produzia a melhora. Campanha de
CONTROLE (mesma escala, MESMO seed corrigido, SEM corte de data)
resolveu a pergunta: controle sozinho já melhora 7/10 células (mediana
+12,47bps) — quase idêntico ao resultado com corte (mediana
+13,44bps). Comparando as duas campanhas diretamente (seed igual nos
dois lados): 5 de 9 células favorecem NÃO ter corte, 4 favorecem TER
corte — sem direção consistente. **Conclusão: a melhora observada é
majoritariamente efeito colateral do seed corrigido, não do corte de
data em si.** Nenhuma das 2 campanhas justifica promover hiperparâmetro
novo pra produção — melhorar sobre um canônico BUGADO não é evidência
de generalização real (`AG-411`/`AG-416`/`AG-419`).

**Fase 5 — retreino com `keep_predictions=True` (hiperparâmetro de
PRODUÇÃO inalterado) fecha os 3 itens restantes**: condicionamento por
regime na granularidade IDEAL (barra-a-barra, n~70.000 por bucket
via o mesmo núcleo do `AG-394`) — AUC condicional varia só 0,4955 a
0,5112 entre tercis, nenhum perto do limiar de ~0,54-0,55 necessário
pra edge líquido, mesmo com poder ordens de magnitude maior que
qualquer teste anterior (`AG-418`, converge com o proxy de `AG-415`).
`edge_bps`/`sharpe` por trade individual (não só por fold): a mediana
por trade é consistentemente MAIOR que a média na maioria das células
— skew negativo real, perdas individuais raras e grandes (mínimo
-999,89bps, ~10% num único trade) arrastam a média pra baixo,
`frac_trades_positivos`~50% na maioria (`AG-417`). Gap in-sample/
out-of-sample (`train_val_test_gap`) fica populado de graça nos 5
artefatos, sem custo adicional (`compute_train_val_test_gap` já
existia, testado, nunca tinha sido chamado no caminho real).

**Conclusão consolidada**: das 6 pendências reais que restaram depois
do roadmap original (`Exhibit VIII` do artefato — condicionamento de
regime barra-a-barra, edge por trade, gap in-sample/OOS, causa raiz do
sampler Optuna, resposta causal do item 12, `SOLUSDT/R2` n=1), todas
foram fechadas nesta sessão, autorizadas explicitamente pelo Manager
(incluindo gasto real de `n_lifetime` em 2 campanhas completas de 150
trials × 10 studies cada). **Nenhum dos 17 itens do roadmap, nenhum
dos 8 ângulos de auditoria, nenhuma das 6 pendências finais reverteu
"0/20, nenhum dos 5 candidatos sobrevive" (`§15.33`)** — o veredito
segue sobredeterminado depois da investigação mais extensa possível
dentro do escopo desta sessão. Decisão de produção sobre os 5
candidatos (incluindo se/como re-promover hiperparâmetro sob o seed
corrigido de `AG-399`) segue com o Manager.

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

- **v3.60 (2026-08-31)** — `ADR-008` fecha: auditoria institucional
  ML/Alpha (score_quality/Rank IC/IC IR, walk-forward real ancorado,
  stability matrix, gates codificados, SHAP, cartão final, 9 fases),
  seguida de correção de forma dos 2 thresholds (Fase 6) e de uma
  auditoria de engenharia adversarial (5 agentes + segundo revisor
  cético por módulo, 6 defeitos reais corrigidos) e de uma rodada de
  decisão final (sweep de sensibilidade ±50%+, thresholds travados,
  `AG-392` 3/4 resolvido). Achado consolidado: **nenhum dos 5
  candidatos promovidos em `ADR-007` (v3.59) sobrevive ao gate walk-
  forward** — `0 de 20` combo×variant×lado, AUC out-of-time≈0,50 na
  maioria. Ver `§15.33`.
- **v3.59 (2026-08-30/31)** — `ADR-007` fecha: campanha Optuna real em
  produção pela 1ª vez (`AG-371`, v3.57) — 1.800+720 trials, **ZERO dos
  6 combos passa o gate duplo** mesmo sob confirmação profunda (10
  seeds), `SOLUSDT/R2` com viés de seleção recorde do projeto
  (+8,356), FPR do gate calibrado (`AG-220`, 8,0%/0,0%/0,0%), correção
  FDR aplicada à taxa-base. Apesar da reprovação, Manager autoriza
  override manual promovendo 5 candidatos a produção canônica
  (`BTCUSDT/R2`, `SOLUSDT/R2`, `SOLUSDT/R3`, `XRPUSDT/R2`,
  `XRPUSDT/R3`). Ver `§15.32`.
- **v3.58 (2026-08-30, retroativo)** — Meta-model F4/F5: `LogitL2Meta`/
  `BlockedGBMMeta` (learner), `resolve_tau_meta` in-fold (§8.3),
  `apply_meta_filter` (veto-em-zero, D-05), `write_meta_fold_bundle`
  (linhagem, D-17); otimização de EM do regime HMM (convergência
  antecipada, para de rodar iterações desperdiçadas) + correção de
  citação de proveniência (`AG-384` "437.630 barras" → `AG-384-
  ADDENDUM-1`, 223.160 observações reais). 254 passed no conjunto dos
  módulos do Meta. Ver `§15.30`/`§15.31`.
- **v3.57 (2026-08-29)** — `AG-371` FECHADO por reformulação arquitetural
  (`ADDENDUM-18`, commit `40b8255`): Optuna real (`optuna>=4.0`,
  dependência declarada desde sempre, nunca importada em `src/` até
  agora) substitui `config/alpha_hyperparams_by_combo.yaml` — o YAML
  estático que já tinha ficado *stale* uma vez de verdade — e a campanha
  manual de grade/coordinate-descent que o alimentava. Escopo estrito
  `src/models/` (produção; `src/validation/` é medição, intocado).
  `src/models/hyperparams_optuna.py` (novo): TPESampler sobre 12 campos
  de `LGBMHyperparams`; Camada1 e Camada0 recebem *studies* independentes
  (comparação de ablação exige HPO nos dois lados — Probst et al.,
  *Tunability*, JMLR 20(53) — não o achado histórico do próprio `AG-371`
  que o Manager pediu explicitamente pra não usar como âncora de
  desenho); resultado vencedor por `(symbol, resolution_id, variant)`
  gravado como artefato content-addressed via `src.io.artifact` — fecha a
  classe de bug do YAML *por construção*, hash muda sozinho se
  `feature_ids`/`search_space`/`variant` mudarem. Itens (b)/(c) do status
  PARCIAL anterior de `AG-371` (teste diferencial + recalibração sob 22
  features) ficam OBSOLETOS, não executados — a pergunta que faziam
  deixou de existir junto com o arquivo que a motivava.

  Autorização direta do Manager pra Claude executar `uv run`/`pytest`
  nesta sessão (com limite explícito: não rodar a campanha completa sob
  CPU) permitiu avançar de verdade pra infraestrutura WSL2+CUDA (GPU real
  — RTX 4060 Ti) em vez de só planejamento: `tools/infra/wsl2_cuda_
  setup.sh` (novo, idempotente, 7 passos) provisiona CUDA Toolkit 12.6 +
  NCCL 2.24.3 + LightGBM 4.7.0 recompilado com `USE_CUDA=ON`, confirmado
  com treino real (dado sintético e dado real do projeto, Camada0 e
  Camada1). `AG-201` (GPU/CUDA inviável no Windows nativo) deixa de ser
  bloqueio — corrigido não no Windows nativo, mas migrando o treino GPU
  pro WSL2. 3 bugs de infra encontrados e corrigidos via investigação até
  causa raiz (não tentativa-e-erro), registrados como `AG-375`/`AG-376`/
  `AG-377` (commit `b6d16c4`): NCCL/CUDA-toolkit desencontrados (zero
  dependência apt cruzada entre os dois, confirmado via `apt-cache show`/
  `madison`); `uv run` revertendo silenciosamente o build CUDA pro wheel
  CPU (comportamento oficial documentado do uv — `tool.uv.sources`+
  `extra` avaliado e rejeitado por risco real ao caminho CPU/Windows de
  produção, issues abertas `astral-sh/uv#17732`/`#17967`); `.venv/`
  compartilhado Windows/WSL2 corrompido (mesmo caminho físico NTFS,
  layouts de venv incompatíveis entre SOs). Os 3 corrigidos pela mesma
  mudança estrutural: venv CUDA isolado inteiramente fora do lockfile do
  projeto (`UV_PROJECT_ENVIRONMENT` separado).

  `AG-378` (commit `f15ca8e`): crash `[CUDA] an illegal memory access`
  (processo inteiro morre, sem exceção Python capturável) bisecado à
  causa exata — `max_bin>256` (limite de índice de 8 bits), confirmado
  como bug upstream conhecido e ainda sem patch (`microsoft/LightGBM
  #6512`); reprodução deste projeto é mais precisa que a da issue
  original (dataset pequeno, ~40k barras, limite exato 256/257).
  `CudaMaxBinUnsupportedError` nova em `fit_side_model` + `catch=` no
  `study.optimize` convertem o crash de processo em trial falhado
  tratável pelo Optuna, sem derrubar a campanha inteira; `sweep_range` de
  `max_bin` NÃO capado por device (mantém `config_hash` portável entre
  devices, decisão deliberada). Achado colateral exposto só depois deste
  fix: "todos os trials falharam" virou estado alcançável (15/15 numa
  rodada real de smoke test) — guarda nova antes de `study.best_trial`
  levanta `ValueError` explícito em vez do erro opaco do SQLAlchemy.

  Campanha Optuna real (~8h CPU pior caso, medido em `AG-371-ADDENDUM-17`)
  e benchmark CPU-vs-GPU seguem NÃO EXECUTADOS — pendentes do usuário
  disparar. Road Map Vivo v2 republicado com seção dedicada; gap de
  reconciliação 2026-08-26/27/28 (`AG-362`–`AG-370`, retreino canônico
  sob `T1_FEATURE_IDS` reestruturado 7→22) declarado explicitamente no
  artefato, não reconstruído nesta rodada (fora do escopo pedido pelo
  Manager — "atualize governança" sobre o trabalho desta sessão, não um
  sweep histórico represado).

- **v3.56 (2026-08-28)** — `AG-077` FECHADO (decisão direta do Manager):
  Gate 6 deixa de ser "DSR final com `N_lifetime`=60" — "pronto" agora é
  lucro entregue em Live Demo, não penalidade estatística de multiple-
  testing. Critérios de encerramento #5/#6 (`PRD_V4_1.md` §6.5,
  guardrail de abandono) e Gates 0-5 (promoção de artefato/constante)
  não foram tocados — mudança escopada só ao Gate 6 positivo.
  `src/validation/dsr.py` não alterado — decisão de implementação
  (remover/marcar non-binding/manter como diagnóstico auxiliar) separada,
  ainda não tomada. Abriu `AG-374` (aberto): "lucro em Live Demo" ainda
  sem definição operacional (o que conta como lucro, sobre qual capital/
  duração, o que é exatamente "Live Demo") — mesma disciplina de
  `AG-114`/`AG-118`/`AG-122`. `§11.4`/`§11.6`/`PRD_V4_1.md` §6.1/§6.5/
  V41-12 atualizados com pointers.

- **v3.55 (2026-08-28)** — `§15.29`: `AG-362` reverte o critério de
  promoção marginal de `ADR-005 §2.2` (decisão direta do Manager, não
  mais protocolo de medição formal) — `T1_FEATURE_IDS` 7→22 (commitado);
  retreino canônico real sob 22 features + hiperparâmetro por combo:
  0/15 `permanence_pass`, sinal misto. `AG-371`: achado e corrigido um
  viés estrutural real de Camada 0 (`E27f` domina 93% do gain sem freio
  monotônico) — mas a VALIDAÇÃO da correção ficou confundida por uma
  sessão paralela que mudou `T1_FEATURE_IDS` no meio do teste (22→29→36,
  Lote D/D2, `ADR-006`, ainda não commitados) — decisão pendente do
  Manager sobre qual vetor é autoritativo, e se remedir sob 22 limpo
  antes de confiar na promoção. `AG-373`: `A17_true_range_per_overshoot`
  tinha defeito dimensional real (`TR/overshoot` não era adimensional) —
  CORRIGIDO no mesmo dia, redesenhada pra `A17_log_tr_per_overshoot_
  ratio`, verificada por teste de invariância a nível de preço.
  `canonical_
  volatility_estimator` flipado pra `parkinson_w20` em produção (fecha
  gap aberto desde 2026-08-17), gap de wiring achado e fechado no mesmo
  dia (`AG-361`). `AG-342` novo (aberto): cutoffs do classificador de
  regime ativo nunca varridos, classe A `ASSUMED`. `§11.4`/`§11.6`
  atualizados (linhas S1, retreino Parkinson, Alpha multi-ativo,
  M1(V4.1)); Road Map Vivo v2 a republicar.

- **v3.54 (2026-08-25)** — Ablação T2→T1: veredito final + promoção
  mandatória. Fase 2 (extensão de fronteira) + confirmação (repetição de
  seed + gate real, REFUTOU Fase 2) + `ADR-002` (redesenho robusto a
  viés de seleção — mediana de top-5, não argmax; cobre os 5
  hiperparâmetros LightGBM nunca testados) — veredito: T2 não sobrevive
  em ETHUSDT/R1, mesmo com metodologia completa. **Manager RATIFICOU
  promoção mandatória T2→T1 mesmo assim (`AG-207`)** — decisão de
  NEGÓCIO explícita, reconhecendo por escrito a violação de R4 (§0.2,
  "teto de features = medido, nunca estipulado"), primeiro override
  deste tipo no projeto (`n_lifetime.yaml` id=28, mesmo padrão de
  `budget_override_manager` do id=17, mas aceitando prosseguir CONTRA a
  medição, não a favor dela). `ADR-003` calibrou hiperparâmetro pra essa
  promoção nas 10 piores combinações por `ret_net` (não as 15 inteiras).
  Escopo corrigido em tempo real 2×: (1) "T2 substitui T1" (convenção
  herdada da pesquisa) → "T2 soma a T1" (69 features, mandato real,
  `AG-234`); (2) ortogonalidade T1+T2 combinada nunca tinha sido medida
  — medida depois nos 10 combos: média 41,4/69 sobrevivem; achado novo
  `A13_dist_ema48_atr`×`B01_rsi_14` (2 dos 7 T1 originais) correlacionados
  0,91-0,995 nos 10 combos sem exceção — T1 nunca tinha passado por
  filtro formal de redundância interna. `run_layer1_sprint` ganhou
  `feature_ids`/`hyper` explícitos (`AG-227`, 2 gaps reais de engenharia
  corrigidos no processo: `config_hash` não capturava a config do Alpha,
  `baselines.py::run_b4_feature_shuffle` quebrava com shape mismatch) —
  10/10 combos com artefato real de produção gravado (69 brutos, filtro
  de ortogonalidade medido mas ainda não aplicado). **2 achados críticos
  de sessão paralela pesam sobre toda a campanha**: `AG-220` (gate de
  permanência mede ruído de variância de path do CPCV, não sinal —
  medido em 3 experimentos pareados reais, veredito oscilou
  FALSE→TRUE→FALSE só por calibração de threshold) e `AG-221` (metade do
  edge bruto negativo medido em TODA a campanha — M6, T2→T1, ADR-002,
  ADR-003 — é artefato de latência sintética da granularidade `mark_1m`,
  não mercado; correção via `agg_trades` implementada, não aplicada como
  default). Pendente do Manager: aplicar conjunto filtrado (39-43) em
  vez do bruto (69); decidir `agg_trades`; investigação de gate em BPS
  ainda não concluída. Detalhe: `docs/ADR-002_busca_hiperparametro_
  robusta_a_ruido_2026-08-24.md`, `docs/ADR-003_hiperparametro_feature_
  set_completo_2026-08-25.md`, `audit/architecture_gaps_log.yaml::
  AG-207/AG-217/AG-220/AG-221/AG-227/AG-234`, `audit/evidence_ledger.
  yaml::adr003-k62-10-piores-combinacoes-veredito-2026-08-25`/
  `t1-t2-ortogonalidade-combinada-2026-08-25`, `docs/SPRINT_LOG.md`.
- **v3.53 (2026-08-24)** — Label Engine: fill gap-aware no SL (D4,
  `AG-205`), pedido explícito do usuário, comparação de engenharia com 2
  implementações de Triple Barrier Method de outros projetos de
  referência. `exit_price` de SL deixa de assumir sempre o nível nominal
  — quando o candle de `mark_1m` que tocou o gatilho já abriu além dele
  (gap/crash/cascata de liquidação), o fill reflete o `open` real do
  candle (mais adverso), nunca o inverso. **TP nunca recebe o ajuste**
  (ordem passiva/maker, executa sempre no nível de repouso; SL é
  `STOP_MARKET`/`MARK_PRICE`, taker, dispara e executa a mercado — a
  assimetria é intencional, não a convenção simétrica de manual de
  triple barrier). Corrigido nos 2 motores (`triple_barrier.
  _first_barrier_touch` escalar + `barrier_sweep.resolve_barriers_
  vectorized`), suíte de paridade própria preservada. Novo contador
  `LabelBuildStats.n_gap_fill_sl` medido, propagado a `experiment_log.py`.
  **Achado colateral fechando ponto cego real do B15**: `config_hash`
  (`LabelConfig`) só capturava campos de CONFIG, nunca a lógica de
  geração em si — mudança de CÓDIGO não invalidava hash nenhum,
  `verify_config_hash` (`build_modeling_frame`, `AG-140`) aceitaria os 20
  `labels.parquet` já persistidos (lógica antiga) sem detectar nada.
  Fechado com novo campo `LabelConfig.barrier_fill_policy_id` (mesma
  técnica já usada 4x neste campo — `AG-005`/`031`/`042`/`116`, adicionar
  campo ao payload força divergência de hash quando a semântica muda) —
  todo `labels.parquet` persistido antes desta correção diverge agora,
  força `ConfigHashMismatchError` na próxima chamada real de
  `build_modeling_frame` até reprocessar (comandos prontos, não
  disparados — decisão do usuário). `AG-206` (item relacionado, mesma
  investigação): piso de volatilidade estilo `TBM_VOL_FLOOR` medido sobre
  4.539.159 registros reais (5 símbolos × {15m,R1,R2,R3}) ANTES de
  implementar (disciplina FE, 0 trials) — mínimo pooled 0,000192 (~1,9
  bps), zero linha próxima de zero. Achado teórico (`AG-061`) NÃO
  confirmado no dado real — piso não implementado, Regra Zero. Commits
  `ac8190a`/`77cfbbc`, 99+77 testes confirmados pelo usuário. Detalhe:
  `docs/SPRINT_LOG.md`, `audit/architecture_gaps_log.yaml::AG-205`/
  `AG-206`.
- **v3.52 (2026-08-24)** — Ablação T2→T1 (H7): plano de 3 fases
  substitui a proposta inicial de grade Optuna direta, síntese crítica de
  2 análises (usuário + auditoria externa) sobre o próximo passo
  pós-retreino real do Alpha (dado AUC~0,509 uniforme medido em toda a
  superfície do sweep de 15 combinações). Fase 0 (ETHUSDT/R1, 60/60
  execuções reais, `N_lifetime` 96→156, id 20): piso de ruído medido
  (σ=0,306 no Sharpe pooled); nulo por permutação calibrado (permuta
  `label`+`ret_net` JUNTOS — achado: `screen_monotone_constraints` deriva
  a restrição de `ret_net`, permutar só `label` deixaria a Camada 1
  trapacear com informação econômica real) — P(n_better≥4|nulo)=0,10; o
  resultado REAL do sweep original (5/5) tem P=0,02 sob esse nulo, sinal
  mais forte do que a leitura agregada capturava. Fase 1 (ranking dos 62
  candidatos T2 por estabilidade IN-FOLD + filtro de ortogonalidade
  |Spearman|≤0,70 — nova constante `alpha_t2_orthogonality_spearman_max`,
  39/62 sobrevivem; mapa de capacidade completo, grade `max_depth×
  num_leaves×k`, 66 execuções reais, `N_lifetime` 156→223, id 21/22):
  padrão limpo sem exceção — k maior sempre melhora Sharpe, mais
  complexidade de árvore sempre piora — **mas mesmo a melhor combinação
  do grid inteiro fica ~2 desvios-padrão pior que o piso de ruído da Fase
  0a**, nenhuma das 65+ combinações com T2 supera o T1 atual (7
  features) neste ativo/resolução. Decisão de escalar pra Fase 2 ou
  generalizar pros outros 14 pares símbolo×resolução fica pendente do
  Manager. Detalhe: `docs/t2_t1_ablation_veredito_duas_analises_2026-08-
  24.md`, `docs/SPRINT_LOG.md`.
- **v3.51 (2026-08-24)** — `AG-204`: decisão real sobre `tp_atr_mult`/
  `sl_atr_mult` a partir do S1 (v3.46) — produção (tp=2,0/sl=1,5) não era
  a melhor célula medida (3ª de 7, `edge_atr_units` médio -0,02555).
  Manager decidiu trocar pela célula `R=1,S=3/2` (tp=1,5/sl=1,5,
  reward:risk 1:1) — `edge_atr_units` médio -0,01686 (34% menos
  negativo, ÚNICA entre as células com edge menos negativo viável pros 5
  símbolos sem violar o piso R2 `cost_stop_ratio_max`×stop em BTCUSDT/
  BNBUSDT). **Ainda edge NEGATIVO** — "menos pior medido", não "edge
  positivo encontrado"; veredito formal de "sobrevive à faixa" (§11
  risco #1) segue TBD. `tp_atr_mult`/`sl_atr_mult` promovidas a
  `provenance: MEASURED` em `constants.yaml`. Consequência em cascata:
  todos os 20 `labels.parquet` (5 símbolos × 4 grades) reprocessados no
  mesmo dia, 0 erro; retreino do Alpha (15 combinações) disparado na
  sequência (já finalizado, análise pendente de registro formal).
  Detalhe: `audit/architecture_gaps_log.yaml::AG-204`, `docs/SPRINT_
  LOG.md`.
- **v3.50 (2026-08-24)** — Rodar o retreino real do Alpha encontrou 3
  achados novos. `AG-201` FECHADO — GPU/CUDA (D-18) confirmado INVIÁVEL
  em Windows nativo (NCCL é dependência nativa de Linux, nunca teve build
  oficial da NVIDIA pra Windows); `device_type` default trocado
  `cuda→cpu` nos 2 entry points reais (`run_layer1_sprint`, `run_
  layer1_sprint_all_combinations`) e no CLI — não é reversão de D-18, é
  reconhecer que a decisão não se sustenta NESTE ambiente até migração
  real pra Linux/cloud (WSL2 mais barato, driver/CUDA Toolkit do Windows
  reaproveitáveis via passthrough). `AG-202` FECHADO — causa raiz de
  linhas duplicadas em `build_modeling_frame` confirmada (não em
  `bars.py`, 1ª hipótese descartada por teste existente que já provava
  esse comportamento como deliberado): `build_dollar_bars_walkforward`
  nunca reseta `carry.base_value` entre fronteiras de recalibração
  (`cadence_days=7`) — 2 trades no mesmo milissegundo numa fronteira
  produzem barra-fantasma de duração zero com `open_time` repetido,
  quebrando a suposição implícita de `dataset.py:316` de que `open_time`
  identifica uma barra unicamente. Sintoma fechado (dedup explícito
  pré-join); causa raiz (resetar `carry.base_value` em `bars.py`)
  proposta, NÃO implementada — exige reprocessar todo o lake de dollar
  bars. `AG-203` ABERTO — 3 de 15 combinações com duplicata residual
  (20 linhas em 2.070.902), causa DIFERENTE de `AG-202`, não investigada
  a fundo. Detalhe: `audit/architecture_gaps_log.yaml::AG-201`/`AG-202`/
  `AG-203`, `docs/SPRINT_LOG.md`.
- **v3.49 (2026-08-24)** — Lote C IMPLEMENTADO — fecha o plano de 3
  lotes da liberação de features (H5). 6 features T2 finais (`E08f_
  oi_notional`, `E14f_toptrader_ls_ratio`, `E15f_toptrader_ls_z`,
  `E16f_global_ls_ratio`, `E17f_retail_vs_top_spread`, `E18f_taker_ls_
  vol_ratio`), zero primitiva nova — extensão fina de `_sources.py` pro
  MESMO arquivo `metrics` que já alimenta `E09f`/`E10f`. Refactor real:
  `_load_and_dedupe_metrics_rows` extraído de `load_oi_series_deduped`
  (resolução de `create_time` duplicado, Sprint 3/4) pra ser
  reaproveitado por `load_metrics_series_deduped` (colunas
  arbitrárias) sem duplicar a lógica — comportamento externo de
  `load_oi_series_deduped` preservado bit-a-bit (4 testes
  pré-existentes confirmados sem alteração). Achado de pesquisa web:
  `schemas.METRICS` tem 2 colunas de razão dos top traders (`count_`
  baseada em contas, `sum_` baseada em posições/notional) —
  ambiguidade real que o PRD não resolve; Manager confirmou `sum_`
  (consistente com `E09f`/`E18f`, que já usam colunas `sum_` neste
  projeto). `SUPPORT_FEATURE_IDS`: 56→62 (59 T2 novas no total nos 3
  lotes). Suíte completa 1934 passed + paridade completa 20/20 (dado
  real) + cobertura de warmup em dado real confirmando as 6 novas com
  valor de verdade via `build_t1_features` (default, sem flag de
  opt-out). **Plano de 3 lotes (H5) fechado** — próximo passo real é a
  ablação dentro do CPCV (§2.0.1/§2.13 do PRD) pra decidir promoção
  T2→T1, tarefa futura separada, não decidida aqui. Detalhe:
  `docs/SPRINT_LOG.md`.
- **v3.48 (2026-08-24)** — `audit_engineering` rodada sobre o Lote A
  (0 CRITICAL/HIGH, 1 MEDIUM real corrigido na sessão — cobertura de
  warmup só em `T1_FEATURE_IDS`, estendida pra `SUPPORT_FEATURE_IDS`).
  Lote B IMPLEMENTADO — 6 features T2 (`A15_dist_vwap_d_atr`,
  `B10_stoch_k_14`, `C08_vol_pctile_rolling_1y`, `D07f_taker_
  imbalance_1m_agg`, `D10f_vol_price_divergence`, `E03f_funding_
  cum_3d`), cada uma com primitiva nova (`support.rolling_correlation`/
  `rolling_percentile_rank_strict`) ou fonte nova (`D07f`, `klines_1m`
  bruto, casca de IO dedicada em `_sources.py`). `SUPPORT_FEATURE_IDS`:
  50→56. 2 achados reais fechados durante a implementação: 2 testes de
  paridade sem `equal_nan=True` (D07f é a 1ª feature que fica NaN o
  tempo todo sem fonte opcional carregada) e uma checagem de NaN
  estruturalmente fraca no teste PRINCIPAL de paridade (mesma classe de
  bug, corrigida nos 2 lugares). Suíte completa 1924 passed + paridade
  completa 20/20 rodadas de verdade pelo próprio Claude (autorização
  explícita do usuário pra execução direta). `§15.26` (árvore de
  arquivos) e Changelog v3.47 seguem válidos, sem alteração estrutural
  nesta versão. Detalhe: `docs/SPRINT_LOG.md`.
- **v3.47 (2026-08-24)** — H5, Lote A da liberação de features
  IMPLEMENTADO — 47 features T2 novas (Grupos A/B/C/D/E/K, arquivo novo
  `group_k.py`), zero fonte/primitiva nova, nenhuma promovida a T1. 40
  constantes novas em `constants.yaml` (`provenance` dedicada — MACD/
  Bollinger/funding-8h/halvings do Bitcoin validados via pesquisa web,
  não só herdados do PRD), 47 entradas em `registry.yaml`. Auditado via
  `audit_engineering` (lente FS/FI/FT/FCN completa) a pedido do usuário
  — 0 CRITICAL/HIGH; 1 MEDIUM real (cobertura de warmup só em
  `T1_FEATURE_IDS`) corrigido na mesma sessão. Suíte completa (1904
  passed) e paridade lote↔streaming completa (20/20, `<1e-8`, 5 símbolos
  reais) rodadas de verdade. `§15.26` atualizado (árvore de arquivos).
  Detalhe: `docs/SPRINT_LOG.md`, `§15.26` acima.
- **v3.46 (2026-08-24)** — S1 (sweep de sensibilidade `tp_atr_mult`/
  `sl_atr_mult`) EXECUTADO — retomado após retratação do Manager de
  2026-08-22 (Alpha retreinado de verdade com LightGBM nesta sessão
  resolveu a condição que motivou a retratação). Implementado exatamente
  como o design doc já aprovado especifica (`src/labels/barrier_
  geometry.py`, `src/analysis/s1_tp_sl_sensitivity.py`), veredito de
  "sobrevive à faixa" deixado `TBD` por decisão explícita (Manager).
  Resultado: sanidade OK (célula central reproduz produção exato);
  **todas as 7 células válidas da grade têm `edge_atr_units` médio
  negativo, inclusive a produção** — confirmação por metodologia
  independente (população incondicional, sem Alpha) do mesmo achado geral
  da análise do Alpha (AUC~0,51). Achado novo: long sistematicamente pior
  que short na geometria de produção, nas 5 moedas — não reconciliado com
  o achado oposto (marginal) da análise do Alpha, registrado como
  pergunta aberta. `N_lifetime` +18 (id 19, counter 78→96, seguindo o
  critério mecânico já escrito no ledger, mesma leitura do precedente
  `id=10`). Linha nova em `§11.4` (não reescreve a linha "SUPERSEDIDO").
  Detalhe: `audit/evidence_ledger.yaml::s1-tp-sl-sensitivity-2026-08-24`.
- **v3.45 (2026-08-24)** — Análise profunda do Alpha (sem retreino):
  ranking de features, decomposição de PnL (63,2% da perda é direcional,
  não custo), AUC real (0,509 médio, quase nulo), calibração (média
  −0,177, fragilidade declarada). Taxa-base ingênua vs. taxa de acerto
  real com significância — 7/15 combinações significativas: XRPUSDT
  único símbolo positivo nas 3 resoluções, `SOLUSDT/R3`/`BNBUSDT/R3` com
  seleção adversa confirmada. `AG-202` — causa raiz encontrada E
  autocorrigida na mesma sessão: 1ª hipótese (bug em `bars.py`) foi
  descartada ao ler um teste existente que já provava esse comportamento
  como deliberado; causa real é o join de regime em `dataset.py:316`
  assumir `open_time` único, que `bars.py` nunca garantiu — 2 trades no
  mesmo milissegundo numa fronteira de recalibração colidem. Fix real
  não toca `bars.py`, custo menor que a hipótese inicial. Metodologia de
  pesquisa H0-H6 proposta + estratégia de testes (skill
  `testing-strategy`) por hipótese. Artefato "Alpha — Base de Pesquisa"
  reestruturado em 2 abas (Retreino/Calibrações). Nova seção `§15.20.3`.
  Detalhe: `audit/evidence_ledger.yaml::alpha-lightgbm-decomposicao-pnl-
  auc-calibracao-2026-08-24`/`alpha-basetate-significancia-ag202-
  2026-08-24`, `audit/architecture_gaps_log.yaml::AG-202`.
- **v3.44 (2026-08-23)** — Primeiro treino real do Alpha pós-migração
  LightGBM. D-06 integrado em escopo estreito (fecha `AG-154` de fato,
  o `status` do ledger tinha ficado desatualizado apesar do commit
  dizer "fecha" — mesmo furo doc-vs-código de sempre, pego na própria
  varredura de governança). 4 bugs reais achados e fechados rodando
  pela 1ª vez contra dado de produção: `AG-199` (config_hash mismatch
  em labels R1), `AG-200` (2º schema de calibração não reconhecido),
  `AG-202` (t0 duplicado no join features/regime, sintoma mitigado,
  causa raiz aberta); `AG-201` (GPU/CUDA inviável no Windows nativo,
  NCCL é dependência Linux-only) permanece aberto, treino real rodou em
  CPU por decisão do usuário. Sweep completo: 5 símbolos × R1/R2/R3 (15
  combinações), **3/15 (20%) passam o gate de permanência** (ETHUSDT/R1,
  SOLUSDT/R2, SOLUSDT/R3) — achado misto real, não decisão de promoção.
  `N_lifetime` +15 (id 18, counter 63→78). Nova seção `§15.20.2`.
  Detalhe completo: `audit/evidence_ledger.yaml::alpha-lightgbm-
  sweep-15-combinacoes-2026-08-23`.
- **v3.43 (2026-08-23)** — Implementação real do Alpha multi-ativo ×
  multi-resolução, D-01 a D-18 (commits `d15ff73`/`321c414`/`1c6f1b3`/
  `4781920`) — `§15.20.1` nova. Learner XGBoost→LightGBM;
  `predictions.parquet` 17→21 colunas; `model_dir` chaveado por
  `(symbol, resolution_id)`; driver de 15 combinações; GPU confirmada
  com o usuário, `device_type` parametrizado. D-06 parcial (cutover
  de produção adiado pro PR do retreino real, decisão do próprio design
  doc). Achado fora de escopo corrigido no caminho: `AG-193` (bug
  pré-existente em `AG-032`, indexação insegura de restrição econômica
  esvaziada). 1781 testes verdes. `AG-157`/`AG-158`/`AG-160` fechados.
  Road Map Vivo v2 republicado (edição cirúrgica do card Alpha). Revisão
  independente `project_assurance` disparada, resultado em adendo
  separado. Detalhe: `§15.20.1`, `docs/SPRINT_LOG.md`.
- **v3.42 (2026-08-23)** — `AG-162` (CRITICAL) e `AG-150` FECHADOS —
  reconciliação do schema `tau_alpha`. D-05 do Alpha (`tau_long`/
  `tau_short` crus, 2 colunas) prevalece sobre o que `AG-150`/`§15.20-E`
  tinham travado antes (`tau_alpha`, 1 coluna derivada). `tau_alpha` deixa
  de ser física em `predictions.parquet` e vira coluna DERIVADA no Meta
  (`meta_dataset.py::build_meta_signal_table`), espelhando o padrão já
  usado no mesmo doc para `p_alpha`/`score_alpha_raw` (§3.2). Custo de
  migração zero — nem Alpha nem Meta tinham código implementado.
  `docs/meta_model_design_doc_2026-08-22.md` atualizado em 6 pontos
  (schema, prosa §3.5, regra travada, checklist, diagrama, risco R3).
  Detalhe: `§15.19-F`, `§15.20-C`, `§15.20-E`.
- **v3.41 (2026-08-23)** — `AG-159` FECHADO — constante dedicada
  `max_consecutive_bar_window_duration_ms` (MEASURED) substitui o
  reaproveitamento do proxy de prefetch em `compute_max_feature_
  lookback_ms`. Detalhe: `§15.27`. Usuário pediu engenharia robusta em
  vez de remediação barata; per-símbolo/resolução avaliado e
  descartado (variância dominada por resolução, não símbolo — mesmo
  precedente de `label_prefetch_p99_bar_duration_ms`). Guarda de
  staleness nova se `max_feature_window_bars()` divergir do valor
  medido (96).
- **v3.40 (2026-08-23)** — Limpeza real do documento inteiro (não só
  anotação), fan-out de 8 agentes só-leitura cobrindo as 5887 linhas
  então existentes. Detalhe: `§15.28`. ~30 achados aplicados (net -46
  linhas): 2 conclusões revertidas na tabela `§11.6` sem ponteiro;
  3 mecanismos rotulados "APROVADO"/"CONFIRMADO SÓLIDO" em `§15.11`
  refutados por auditoria externa sem correção local — `AG-098` é risco
  operacional real (convenção de trial ativamente errada, ainda sem
  substituto); `AG-094` revertido pelo Manager sem ponteiro; 4 linhas
  com anotação órfã na tabela `§15.4`; referências a arquivo renomeado/
  nunca-existente corrigidas; 2 TODOs já cumpridos removidos. `§14` e a
  maior parte de `§15.7`-`§15.21` mantidos deliberadamente — trilhas de
  decisão genuínas, não lixo.
- **v3.39 (2026-08-23)** — `08_SPLIT` decisão 1 implementada: 3 features
  expanding saem de `T1_FEATURE_IDS` (`AG-032`, commit `78169df`).
  Detalhe: `§15.27`. Consequência direta: `AG-159` (magnitude do purge
  sob R2/R3) deixa de ser dormente — `structlog.warning` adicionado,
  diagnóstico novo escrito (`measure_max_consecutive_bar_window_
  duration.py`), resultado pendente do usuário rodar. Pendente,
  registrado: 6 scripts de análise pós-hoc vão quebrar até migrarem pra
  `extra_feature_ids` (novo parâmetro de `build_modeling_frame`).
- **v3.38 (2026-08-23)** — Nova seção `§15.26`, árvore de arquivos
  canônicos de produção ponta a ponta (pedido do usuário) — mapeamento
  por leitura de código real (`grep "if __name__"`), cruzado com `§15.4`
  e `docs/nucleo_casca_design_doc_2026-08-23.md`. Confirma
  `docs/nucleo-casca.html` como leitura de apoio genérica (Gary
  Bernhardt), não spec deste repo. Achado central: runners de produção
  reais existem ponta a ponta só até `models`/`validation`/`backtest`
  (01-10, +15 em modo simulado) — a partir de `12_RISK_ENGINE` em
  diante, zero caller de produção; `features`/`regime` (03/04/05) têm
  núcleo pronto mas rodam só como biblioteca, sem CLI própria.
- **v3.37 (2026-08-23)** — **Varredura de achados médio/baixo do gate
  "Data Layer 100%", 3 correções mecânicas.** Detalhe: `§15.25`.
  `AG-134` ganhou teste de caracterização (risco de troca de significado
  de `canonical_id` sob mudança estrutural, não fecha o achado, commit
  `bed805e`); `AG-136` teve o `status` corrigido (dizia "em andamento"
  genérico, na prática só Fase 7/sweep tp-sl segue aberta, já rastreada
  à parte); `AG-120` revisado, texto já estava preciso, nada a corrigir
  (causa raiz exige investigação empírica que só o usuário executa).
  Nenhum achado médio/baixo NOVO encontrado. `08_SPLIT`/`AG-159`/
  `AG-121`/`AG-123` seguem precisando de decisão real do Manager, sem
  mudança.
- **v3.36 (2026-08-23)** — **`AG-138`/`AG-139` fechados — últimos 2
  achados "alto" do fan-out de 15 estágios sem decisão do Manager
  pendente.** Detalhe: `§15.25`. `AG-138`: CLI de `build_dollar_bars.py`
  ganhou `--mode {single_window,walkforward}` — `walkforward` aciona a
  recalibração causal (`build_dollar_bars_walkforward`, `AG-124`) direto
  do CLI, antes só acessível via script separado; `single_window`
  (legado) ganhou `logger.warning` explícito sobre o vazamento de 18,18x
  medido. `AG-139`: 2 magic numbers sem `# noqa` em `support.py`
  corrigidos, `banned_patterns.py --strict` volta a passar limpo. 4
  testes novos de CLI, verificação mecânica completa (lint/mypy/
  banned_patterns, baseline `git stash`, zero regressão). Commit
  `ef7f5d3`. Consequência: dos 3 achados "alto" que travavam o gate
  "Data Layer 100%" (`§15.14`), os 3 agora estão fechados
  (`AG-138`/`AG-139`/`AG-140`) — resta só `08_SPLIT` (2 decisões do
  Manager, não gap de implementação) e o débito organizacional já aceito
  de `06_BARREIRAS`; nenhuma varredura de achados "médio"/"baixo" feita
  nesta rodada.
- **v3.35 (2026-08-23)** — **`AG-140` fechado — confirmação empírica
  achou drift real (schema de hash, não parâmetro) contra
  `labels/v1` de produção, reprocessado.** Detalhe: `§15.24-F`. Os 2
  testes `slow`/`integration` (v3.34 pedia essa confirmação) falharam de
  verdade: `config_hash` do `labels.parquet` real (`b281a18954e224ef`)
  divergia do da execução atual. Investigado ANTES de agir (`git log -p`
  nos 7 campos do hash): nenhum valor mudou — a divergência é o FORMATO
  do payload, que migrou 5x historicamente (`AG-005`/`031`/`042`/`116`,
  já documentado na docstring de `config_hash`), e os labels reais
  predatam essas migrações. Usuário escolheu reprocessar (de 3 opções
  oferecidas). `build_and_write_labels_for_symbol`/`run_and_write_
  labels_for_alts` rodados — 5 `labels.parquet` reescritos com o hash do
  schema atual, mesmos valores de barreira. Confirmado: `2 passed` (era
  `2 failed`). Zero teste do repo tinha o hash antigo hardcoded.
- **v3.34 (2026-08-23)** — **`verify_config_hash` (B15) wireado no
  caminho real de consumo.** Detalhe: `§15.24`. `AG-140` — a função já
  existia, testada isoladamente, mas `src/models/dataset.py::
  build_modeling_frame` (único ponto real de consumo de
  `labels.parquet`) nunca a chamava. Achado colateral: `resolution_id`
  agora exige `vol_estimator_id` explícito (mesma regra que
  `LabelConfig.from_constants` já impunha). **Não executado
  empiricamente** contra `labels.parquet` real — risco real de revelar
  drift já existente entre `constants.yaml` e os labels de produção;
  pedido explícito ao usuário pra rodar os testes e confirmar. 4 testes
  novos + 4 existentes ajustados.
- **v3.33 (2026-08-23)** — **`feature_a13_ema_window` — conversão
  clock↔bar-count aplicada em código, achados irmãos confirmados por
  pesquisa de literatura.** Detalhe: `§15.23`. `AG-043` (2026-08-16) já
  classificava A13 como `scaling_invariant: clock`, mas nenhum código
  aplicava a conversão — `src/features/build.py` ganhou
  `_clock_reference_bar_duration_ms`/`_scale_clock_window_bars`
  (48/24/12 barras sob R1/R2/R3, bit-exato sob `time_15m`). Correção de
  rumo registrada: duas propostas de arquitetura iniciais propunham
  RECLASSIFICAR A13 pra `bar_count` com base em pesquisa de literatura
  (López de Prado 2018; Grądzki/Wójcik/Lessmann 2025) — releitura de
  `AG-043` mostrou que isso contradizia uma decisão já tomada e
  justificada (A13 ancorado ao horizonte real do label, diferente de
  RSI/B07/vol_ratio/C07/D06f/E10f). `E27f_cost_atr_ratio`/`atr_window`
  confirmados como separação deliberada correta (não gap) pela mesma
  pesquisa. Doc-drift `registry.yaml::min_warmup_bars` (2000→200, 13
  entradas) corrigido na mesma leva. 9 testes novos.
- **v3.32 (2026-08-23)** — **Núcleo funcional, casca imperativa —
  princípio formalizado (`CLAUDE.md`), 5 violações reais fechadas + 1
  achado HIGH extra do `project_assurance`.** Detalhe: `§15.22`. Achado
  central: o padrão (Bernhardt 2012) já era a norma dominante do repo
  (~25+ módulos), nunca formalizado — não é adoção nova, é fechar
  doc-drift + violações reais. `triple_barrier.py`/`fill_simulator.py`/
  `faixa1_5_prerequisites.py`/`attribution.py`/`pipeline.py`+`hhi.py`+
  `baselines.py` corrigidos, todos com teste novo exceto
  `faixa2_caminho_b.py` (split feito, teste sintético completo deferido
  — risco>valor sem execução iterativa de pytest). `project_assurance`
  achou `fill_simulator.py::_resolve_tick_size_cached` como 2ª instância
  real HIGH da mesma classe de bug, não catalogada no desenho original —
  corrigida antes desta seção. `1734 passed` + `7 passed` de integração
  (bit-exatidão do caminho default confirmada com dado real). Nenhum
  caller de produção usa os novos parâmetros de injeção ainda —
  comportamento de produção 100% inalterado.
- **v3.31 (2026-08-23)** — **Fecha `AG-174`/`175`/`176`, entrega + roda
  script de medição para `AG-180`.** Detalhe: `§15.21.3`. `validate_
  resampled_bars` parava de fingir PASS (schemas `BARS_15M`/`30M`/`1H`
  registrados, reusa `validate_klines_like` por inteiro, 11 testes) —
  fecha `AG-174`/`AG-175`. Guarda mecânica nova
  (`check_resolution_id_guard_parity.py`) confirma os 4 sites de
  `resolution_id` consistentes (opção B do Manager, aceitar duplicação) —
  fecha `AG-176`. `AG-180`: script de medição entregue E rodado pelo
  Manager (45/45 combinações) — resultado real registrado no ledger e
  corrigido nesta mesma rodada de limpeza em `§15.21.3`-C (a versão
  original do commit `c0f4038` citava o script como "não rodado" apesar
  do próprio commit já ter o resultado no ledger — inconsistência
  interna corrigida). `min_warmup_bars=200`: mediana da janela real sob
  R1 fica próxima do equivalente 15m, mas R2/R3 saem 2×/4× MAIORES, não
  menores como a suspeita original previa isoladamente — fórmula de
  conversão segue pendente do Manager, `AG-180` continua `aberto`.
  Commits `d44c7f9` (implementação) + `c0f4038` (governança).
- **v3.30 (2026-08-23)** — **Regime/Feature Engine — D-01/D-02
  implementados, fecham `AG-159`/`AG-177`.** Detalhe: `§15.21.2`. `src/
  regime/stress.py` ganha `s06_bar_gap_dollar` (mediana/MAD via `pl.
  Series.rolling_median` deslocada, expansiva por construção — reusa
  primitiva nativa do Polars, não estrutura customizada). `bar_source`
  propagado ponta a ponta (`QuantileRegimeClassifier`/`build_regimes`).
  `compute_max_feature_lookback_ms` ganha `resolution_id`, os 2 call
  sites (`pipeline.py`/`leakage.py`) corrigidos juntos. Revisão
  independente (`project_assurance`, 2 agentes) achou e corrigiu 1
  achado real antes do commit: critério de S6 era bilateral, deveria ser
  unilateral (`AG-183`) — rajada de liquidez dispararia stress sem
  motivo, mudando `monotone_constraints` via `environments.py`→
  `monotonic.py`→`alpha.py::fit_side_model` (confirmado consumidor de
  produção real, não só análise). 1695 passed. Commits `6902352`
  (implementação) + `2905f16` (governança).
- **v3.29 (2026-08-23)** — **Regime/Feature Engine multi-ativo × multi-
  resolução: design doc v1→v3, achado crítico corrigido antes de virar
  código.** Detalhe: `§15.21.1` (`§15.21`, dívida técnica BTC/M15, foi
  registrado por sessão paralela mais cedo no mesmo dia — commit
  `9719031`). `docs/regime_feature_engine_design_doc_2026-08-23.md`
  redesenha `src/regime/stress.py`/`classifier.py` (S6 cego a
  `bar_source`, `AG-177`) e o purge do CPCV (`AG-159`). Auditoria
  adversarial (v1→v2): 2º call site de `AG-159` esquecido
  (`src/validation/leakage.py:792`) + histerese em contagem de barra
  reclassificada de "sem mudança" pra gap real (`AG-180`, novo).
  `project_assurance` (v2→v3): achado CRÍTICO — a correção de S6 proposta
  na v1/v2 introduziria B02 se implementada como estava (mediana/MAD
  sobre série inteira, portada sem adaptação causal de
  `hmm_gap_check.py`) — corrigido pra computação expansiva antes de
  qualquer linha de código existir. Mapeamento de consumidores de
  `regime` corrigido (`environments.py`/`monotonic.py`/
  `monotone_constraints`, produção real — `AG-088` addendum). Zero linhas
  implementadas. Road Map Vivo deliberadamente não republicado nesta
  rodada (baixa materialidade frente à republicação extensa e recente da
  sessão paralela no mesmo dia).
- **v3.28 (2026-08-22)** — **Alpha multi-ativo × multi-resolução (LightGBM +
  GPU): arquitetura ponta a ponta travada v3, 2 rodadas de revisão
  independente.** Detalhe: `§15.20`. Achado central: multi-símbolo e
  multi-resolução (R1/R2/R3) já estavam prontos em produção — o redesenho
  real é o learner (XGBoost→LightGBM) + orquestração (5→15 combinações) +
  4 débitos de schema. Auditoria adversarial (v1→v2): 1 CRITICAL
  (`tau_long`/`tau_short` não verificado contra o `tau_alpha` que o Meta v3
  trava — `LegacyPredictionsError` permanente se implementado sem
  correção) + 6 IMPORTANT/MODERATE. `project_assurance` (v2→v3): o problema
  de `tau_alpha` é maior — já travado em 3 artefatos de governança
  divergentes, não 2; escalado ao Manager (`AG-162`, CRITICAL), não
  fechado por revisão. `AG-100`/`AG-124` citados como "fechados" quando o
  status formal segue "aberto" — corrigido, também escalado (`AG-163`,
  HIGH). GPU (D-18) adicionado a pedido do Manager nos dois motores, com 3
  ressalvas declaradas (build via `uv`, tensão com determinismo bit-exato,
  payoff não medido); para o Meta, aplicado só ao braço LightGBM já
  bloqueado por D-02, sem desbloquear o gate. AGs novos: `AG-157`-`AG-164`.
- **v3.27 (2026-08-22)** — **`project_assurance` sobre o design doc v2 do
  Meta-model: 3 CRITICAL + 4 HIGH, veredito "não é base sólida para
  implementar". v3 escrita.** Detalhe: `§15.19` alínea G. Os três CRITICAL:
  (1) **`group_matched` não tinha purge nem embargo** — o braço anunciado
  como "estritamente melhor, cegueira total" era o único dos dois **sem
  B09**, porque `generate_splits` rejeita `n_test_groups != 2`
  (`cpcv.py:544-548`) e as linhas de treino do Meta ficam no `test_mask` do
  doador; removido do caminho crítico; (2) **Gate E0 sem esquema de
  permutação declarado** — o precedente do repo é i.i.d.
  (`baselines.py:819`), que com rótulos sobrepostos e regimes em blocos
  contíguos faria o gate mais consequente do desenho passar praticamente
  qualquer coisa; travado circular-shift por bloco + validação obrigatória do
  próprio nulo; (3) **nulo A2 replicava 1 de 5 fontes de otimismo** com o
  problema declarado resolvido; enumeração exaustiva + enforcement por função
  compartilhada. HIGH: lado do teste de `group_matched` nunca definido; D-15
  com plano de migração inexecutável (`predictions.parquet` **não tem**
  `schema_version`) e custo mal declarado (`tau` não está em disco — popular
  exige retreinar); §14.1 **não** resolve B22. **Reversão explícita** de
  decisão da v3.26: cadência Alpha↔Meta **vira AG** (`AG-155`), não foi
  resolvida por desenho. AGs novos: `AG-153` (não existe primitiva de purge
  por bloco arbitrário — todo purge acoplado à geometria de pares), `AG-154`
  (predições sem manifesto/versão), `AG-155`, `AG-156` (nulo i.i.d. em B4,
  com a qualificação de que o viés é conservador e **não** invalida o achado
  do Alpha legado). Lição de processo registrada: a v2 diagnosticou o padrão
  "mitigado por declaração em vez de mecanismo" e **repetiu o padrão nas três
  peças que apresentava como suas maiores conquistas** — duas rodadas de
  revisão com lentes distintas não foi redundância.
- **v3.26 (2026-08-22)** — **Meta-model: arquitetura ponta a ponta travada,
  `ADR-001 §3.7/§2.7` REVOGADO pelo Manager.** Detalhe completo em `§15.19`.
  Regime passa a entrar como FEATURE do Meta (one-hot, nunca ordinal),
  revertendo a recomendação #7 do ADR-001 — sustentado por 3 fontes
  independentes e pelo fato de que regime saiu do vetor do Alpha em
  2026-08-21 (`§15.13` Fase A), criando a vantagem informacional sem a qual
  meta-labeling não tem mecanismo. **Grupo J revertido na mesma sessão** —
  sai da frente do Meta: `NOFILL ⟹ ret_net = 0.0`
  (`triple_barrier.py:961`) torna a marginalidade de PnL de `p_fill`
  exatamente zero; mais dependência circular (`calibrate_against_real_fills`
  precisa de Testnet/Paper, que vem depois do Decision Engine) e cobertura
  de 13% em bloco contíguo de calendário (carimbo de data disfarçado de
  feature). **CatBoost descartado** apesar de nomeado pelo Manager (ganho do
  ordered boosting nunca replicado independentemente; em CPU o default é
  `Plain`). 17 decisões travadas (`D-01`..`D-17`), ZERO linhas
  implementadas. **Auditoria adversarial de 3 flancos via
  `/engineering:architecture`: 6 CRITICAL, ~20 HIGH, 40 correções** — entre
  elas uma **prova de impossibilidade FALSA** no desenho v1 (existe doador
  OOF e totalmente cego com zero retreino; o custo é 1 caminho OOS em vez de
  5), `score_raw` excluído por argumento de colinearidade errado
  (isotônica é *many-to-one*), e cinco defeitos que inclinavam os gates a
  PASS. Padrão da falha nomeado para não repetir: riscos identificados com
  precisão e mitigados **por declaração em vez de mecanismo**. AGs novos:
  `AG-149` (referência órfã a `AG-148`), `AG-150` (`tau` calculado e
  descartado), `AG-151` (purge cross-símbolo ausente — `linspace`
  per-símbolo desalinha fronteiras entre símbolos, pré-requisito
  bloqueante), `AG-152` (`join_asof` cross-grade sem `tolerance`).
  `AG-094` FECHADO com **reversão explícita** da resolução que `AG-118`
  havia antecipado. Correção factual capturada pelo item 1 do protocolo
  (commits antes de docs): o design doc afirmava que nada era persistido em
  `src/` — `AG-141`/`persistence.py`/`src/io/artifact.py` foram construídos
  no mesmo dia; o Meta **reusa**, não constrói, e nenhum AG duplicado foi
  aberto. Doc: `docs/meta_model_design_doc_2026-08-22.md` (v2).
- **v3.25 (2026-08-22)** — `AG-124` reprocessamento real CONCLUÍDO: 15/15
  células (5 símbolos × 3 resoluções), zero erro. Item 22 (validação
  sobre dado real) concluído com resultado POSITIVO — curtose alta é
  100% evento de mercado genuíno (Celsius/3AC, Black Thursday, FTX),
  artefato de recalibração desprezível sobre histórico completo. Achado
  colateral não-bloqueante `AG-137` (arquivo stale pré-causal nos
  primeiros `cadence_days` dias de cada célula, decisão de limpeza
  pendente). Design doc do S1 (`docs/s1_design_doc_sweep_tp_sl_
  reward_risk_2026-08-22.md`) produzido via `redesign_workflow` (2
  agentes `code-architect` + síntese própria) e auditado por
  `project_assurance` — 4 achados HIGH corrigidos no documento antes de
  qualquer implementação, decisão de arquitetura central preservada.
  Road Map Vivo v2 republicado refletindo todo o estado acima.
- **v3.24 (2026-08-21/22)** — `AG-124` (calibração causal do threshold
  dollar-bar): linha de investigação CONCLUÍDA após 6 rodadas de
  auditoria externa (parecer+adendo genuínos, docs/Retorno_Brief/, mais
  1 documento descartado por não-confiável — colisão de numeração
  `AG-125` real, claims sem base no código). `trailing_window_days=7`
  travado (elimina aliasing semanal). `cadence_days=7` preferido sobre
  `cadence_days=1` (que vencia a métrica de rastreio por margem grande,
  mas exercita 7,25x mais eventos de transição de threshold — cada um
  viola o invariante que define dollar-bar; taxa de subdimensionamento
  por evento é igual nos 2 braços, mas retorno associado é maior sob
  `C=1` na mesma janela de calendário, testado contra confundimento de
  hora-do-dia) — decisão apoiada também em 3 argumentos de sistema
  (tipo de erro suave vs. discreto, assimetria de custo de estar
  errado, superfície de paridade lote↔streaming ao vivo). Detalhe:
  `§15.15`. Reprocessamento real dos 5 símbolos × 3 resoluções
  disparado (`data/capacity/dollar_bars_r{1,2,3}/`, substitui
  calibração não-causal antiga). Achados colaterais fechados: carry
  persistente através de fronteira de período, lead-in buffer, circuit
  breaker validado, varredura completa de `AG-120` (isolado, confirmado
  não-sistêmico). S1 (sweep `tp_atr_mult`/`sl_atr_mult`, reparametrizado
  `R=tp/sl`×`S=sl`) aberto na sequência, desenho em andamento.

- **v3.23 (2026-08-21)** — Ponte de governança sobre o arco 2026-08-19→21
  (a série v3.22 e anteriores para no meio deste arco — este item
  fecha a lacuna, achado da rodada de "Atualize governança" desta
  sessão, não reescreve entradas antigas). Resumo, detalhe completo em
  `§15.12`-`§15.13`: **4ª execução real do M4 concluída** (18/18
  p-valores de permutação 0,30-0,85, nenhuma célula significativa,
  tratado como achado válido); **ADR-001 ratificado** (regime = gate de
  risco, não feature, na v1); **Trilha B** (contrato Regime→Alpha→
  Execução) aberta e fechada com 4 mecanismos aprovados + 7 decisões
  residuais pendentes; **`AG-114`** (regra de decisão de 3 gates +
  métrica primária) aplicada sobre resultado real, `hmm_gaussian_k4_v1`
  declarado vencedor — **REABERTO** no mesmo dia por auditoria externa
  (Gate 1 aplicado com 2 critérios misturados; sob o critério literal,
  `hmm_gaussian_k2_v1` venceria em 2 das 3 resoluções) — **status ainda
  aberto** quanto à metodologia de seleção; **`AG-118`** (Gate
  Efficiency) implementado e **RESOLVIDO** (lift ~1,0 em 90 células, sem
  sinal econômico detectável, robusto ao candidato — mecanismo: `exit_
  price` de TP/SL é o próprio preço da barreira, torna tail-loss
  quase-determinístico em `atr_pct`); Manager autoriza `hmm_gaussian_
  k4_v1` como candidato de regime **canônico de produção** mesmo com o
  Gate 1 ainda fragilizado (override de negócio explícito, `§15.13`) —
  regime sai do vetor de treino do Alpha, novo builder `src/regime/
  build_hmm.py`, Risk Engine passa a receber `regime_tradeable: bool`
  candidato-agnóstico. Rodada de governança desta sessão também achou e
  corrigiu 2 bugs de sintaxe YAML pré-existentes (nunca detectados
  antes) em `audit/evidence_ledger.yaml` — `#N`/`:` sem aspas dentro de
  escalar multi-linha é interpretado como comentário/nova chave — e
  abriu `AG-123` (tabela de prontidão dos 15 estágios, `§15.2`/`§15.4`,
  sem gatilho de sincronização quando um módulo ganha/perde caller —
  mesma classe de furo que gerou `AG-080`, recorrente).

- **v3.22 (2026-08-19)** — M4 (Regime), continuação da v3.21 no mesmo
  dia: Manager autorizou "AG-093 + 4ª re execução". `AG-093` (BOCPD
  avaliado sobre a janela crítica inteira, ~5x mais amostra que os
  outros 5 candidatos) implementado — `SymbolResult` (`m4_regime_
  comparison.py`) ganhou `oos_start_ms`/`oos_end_ms`, a fronteira real
  do walk-forward que baseline/HMM/Jump Model já usam, computada de
  graça a partir do MESMO `close_time_ms`/`oos_start`/`oos_end` já
  calculado internamente (zero IO/fit adicional). `_bocpd_metrics_for_
  window` (`m4_critical_windows.py`) passou a receber essa fronteira
  diretamente em vez de derivar de `window.start`/`window.end` — o
  BOCPD agora é avaliado sobre a mesma janela (~1 trimestre) que os
  outros 5 candidatos.

  Auditoria independente concluída no mesmo dia — 0 CRITICAL/0 HIGH. A
  fórmula da fronteira (`close_time_ms[oos_end-1]+1`, evita índice fora
  dos limites) foi confirmada correta por leitura direta de `generate_
  anchored_walk_forward_splits` (o último fold SEMPRE cobre até o fim
  da série carregada, não é caso especial). 1 achado MEDIUM corrigido
  no mesmo dia: o teste de regressão só provava que a fronteira era um
  superconjunto válido dos dados reais (containment), não que era a
  fronteira EXATA — reforçado com igualdade direta contra um split
  recomputado de forma independente + checagem de escala.

  Com isso, as 4 correções desta rodada de investigação (`AG-090`/
  `AG-091`/`AG-092`/`AG-093`) estão **todas implementadas e auditadas de
  forma independente**, 0 CRITICAL/HIGH remanescente em qualquer uma.
  4ª re-execução do M4 autorizada e pronta pra disparar — comando
  entregue ao Manager pra rodar manualmente (protocolo de execução do
  `CLAUDE.md`).

- **v3.21 (2026-08-19)** — M4 (Regime), continuação da v3.20 no mesmo
  dia: auditoria independente de `AG-092` concluída (2 agentes frescos
  em paralelo — matemática do núcleo + integração/ordenação temporal),
  0 CRITICAL nos dois. Núcleo: 6 alegações centrais verificadas
  matematicamente à mão (equivalência de fórmulas, episódio nunca
  quebrado, caso analítico `p=1.0` exato, poder estatístico, `k`
  preservado, refatoração neutra) — nenhum contra-exemplo. Pesquisa web
  confirmou fundamento na literatura (permutação em bloco por cluster,
  correção `+1` de Phipson & Smyth). 3 MEDIUM corrigidos (fórmula de SE
  duplicada extraída pra fonte única `_edge_variance_multinomial`;
  degradação de resolução do p-valor com poucos episódios documentada;
  viés de exclusão de permutação degenerada registrado como observação
  não-bloqueante). Integração: **1 HIGH real** — a garantia de que
  `join_asof` preserva ordem cronológica (pré-requisito crítico pra
  extração de episódio, que é puramente posicional) não é um contrato
  público do Polars tão forte quanto `.filter()` — o próprio Polars já
  teve uma regressão real dessa propriedade (corrigida jan/2026).
  Corrigido no mesmo dia: assertion de runtime (`np.diff(t0_ms)>=0`,
  falha ruidosa em vez de episódio artificial silencioso) + teste de
  regressão com buckets intercalados cronologicamente (discrimina uma
  reordenação silenciosa que a fixture antiga nunca pegaria, por
  bucket-contiguidade coincidir com tempo-contiguidade lá por
  construção). As outras 7 perguntas de integração confirmadas
  corretas, 0 achados. Mecanicamente limpo em todos os arquivos.

  Com isso, as "3 propostas autorizado" (`AG-090`/`AG-091`/`AG-092`)
  estão **implementadas e auditadas de forma independente**, 0
  CRITICAL/HIGH remanescente em nenhuma das 3. Pendente: re-execução do
  M4 (4ª rodada) — próxima decisão é do Manager, considerando também
  `AG-093` (BOCPD sobre janela cheia em vez de slice OOS, achado mas
  sem autorização de fix) antes de comprometer o custo computacional de
  um novo run completo.

- **v3.20 (2026-08-19)** — M4 (Regime), continuação da v3.19 no mesmo
  dia. Auditoria independente de `AG-090`/`AG-091` (2 agentes frescos,
  1 por arquivo) concluída — veredito "APROVADO_COM_RESSALVAS" nos dois,
  **0 CRITICAL/0 HIGH** (os 2 fixes estão logicamente completos e
  corretos nos consumidores reais). `AG-091` teve 1 achado HIGH real,
  mas sobre PROVENIÊNCIA, não comportamento: a citação original ("
  `metafor`/`meta` no R e Higgins & Thompson 2002 tratam `k=1` como
  indefinido") era FALSA — os agentes leram o código-fonte real dos 2
  pacotes R e confirmaram que ambos fazem o OPOSTO (`Q=0`/`I²=0%` por
  convenção, incluído na agregação). A escolha `NaN`/excluir continua
  válida, mas por razão específica a este repo (evitar recompensar
  candidato degenerado com score "limpo"), não precedente de biblioteca
  — docstring corrigido. 3 achados MEDIUM (testes de regressão faltando
  nos pontos mais sensíveis a desalinhamento silencioso — fold
  parcialmente falho, máscara de janela do BOCPD, cenário real de
  `n_buckets=1` no consumidor) — todos corrigidos no mesmo dia. 5
  achados LOW documentados como backlog, sem urgência.

  `AG-092` (invalidade estatística do Cochran's Q/I² sob autocorrelação
  intra-episódio) **implementado** no mesmo dia — teste de permutação em
  bloco por episódio de regime, substituindo o p-valor assintótico
  `chi²(k-1)` por um p-valor empírico. `src/validation/regime_utility.py`
  ganhou `segment_boundaries` (extraído de `regime_persistence`, mesma
  lógica de run-length, agora reusável). `src/analysis/m6_common_factor_
  hypothesis.py` ganhou `permutation_heterogeneity_test` (núcleo
  vetorizado via `np.bincount`, equivalência com `cochrans_q_
  heterogeneity` provada por teste dedicado — sem custo de refit,
  centenas/milhares de permutações por célula em milissegundos).
  `m4_critical_windows.py` threaded com 2 constantes novas
  (`m4_heterogeneity_n_permutations=1000`/`m4_heterogeneity_permutation_
  seed=42`, `constants.yaml`) por toda a cadeia de agregação. Auditoria
  independente disparada (2 agentes, 1 pra matemática do núcleo, 1 pra
  integração/ordenação temporal no pipeline) — resultado pendente no
  momento deste registro.

  Critério de decisão combinando p-valor < α com magnitude econômica, e
  t-stat de Ibragimov-Müller pra agregação entre janelas — deliberadamente
  NÃO implementados nesta rodada (ficam pra quando `G-C1-2` for de fato
  avaliado). `AG-093` (BOCPD avaliado sobre a janela crítica inteira em
  vez do slice OOS, ~5x mais amostra que os outros candidatos) segue
  ABERTO, sem autorização de fix ainda. Re-execução do M4 (4ª rodada)
  segue pendente — aguarda resultado das 2 auditorias de `AG-092` antes
  de comprometer o custo computacional de um novo run completo.

- **v3.19 (2026-08-19)** — M4 (Regime), continuação da v3.18: Manager
  autorizou auditoria cética sobre o resultado real da Fase D re-
  executada (BOCPD liderando de novo as 3 resoluções sob Cochran's Q/I²,
  padrão suspeito repetido). Achados novos, registrados `AG-090` a
  `AG-093`: (1) `AG-090`, ALTO — `join_asof` causal de Q3 e de
  heterogeneidade chaveava em `open_time_ms` (abertura da barra), não
  `close_time_ms` (quando o rótulo de regime é de fato conhecível) —
  vazamento temporal confirmado contra `t0` real de `labels.parquet`
  (já é `close_time`, `src/labels/triple_barrier.py:913`); (2) `AG-091`,
  MÉDIO — `cochrans_q_heterogeneity` com `k=1` (`df=0`) produzia
  `i_squared_pct=100,0` por ruído de ponto flutuante em vez de `NaN`
  explícito (caso real medido: `q_statistic=3,857e-32`, não `0,0`); (3)
  `AG-092`, ALTO — Cochran's Q/I² assume estratos independentes,
  violado pela autocorrelação intra-episódio de regime (`I²` satura
  70-99% quase universalmente no relatório real, consistente com o
  mecanismo de inflação da literatura, não com heterogeneidade real tão
  extrema); (4) `AG-093`, ALTO — `_bocpd_metrics_for_window` (correção
  `AG-084`) avalia métricas sobre a janela crítica INTEIRA (~15 meses)
  em vez do slice OOS que os outros 5 candidatos usam (~1 trimestre) —
  amostra ~5x maior infla `I²` do BOCPD artificialmente, principal fator
  medido por trás da liderança suspeita.

  Manager autorizou implementação de `AG-090`/`AG-091`/`AG-092`
  ("3 propostas autorizado") — `AG-093` ficou de fora dessa autorização
  (achado no mesmo round de investigação, mas não coberto pelo pedido).
  Implementados nesta sessão: `AG-090` (`close_time_ms` como campo
  obrigatório novo em `RawLabels`/`_BocpdFullHistory`, roteado por todos
  os pontos de construção, `_asof_join_btc_labels`/`_asof_join_regime_
  onto_labels` corrigidos, testes de regressão dedicados provando a
  diferença com um caso construído) e `AG-091` (early-return `df==0` →
  `NaN` explícito, nunca `0,0`/`100,0`). `AG-092` (teste de permutação em
  bloco por episódio de regime, reusando `regime_persistence`) —
  desenhado, autorizado, AINDA NÃO implementado. `AG-093` — achado,
  fix desenhado, implementação NÃO autorizada ainda.

  Mecanicamente limpo (ruff/mypy/banned_patterns/check_constants_
  referenced/check_unguarded_ratios) nos arquivos tocados por `AG-090`/
  `AG-091`. Auditoria independente (`audit_engineering`, agentes
  frescos, 1 por unidade de mudança) disparada em 2026-08-19 sobre os
  dois fixes ANTES de qualquer nova re-execução real do M4 — resultado
  pendente no momento deste registro. Re-execução (4ª rodada) aguarda
  tanto o resultado dessa auditoria quanto a implementação de `AG-092`
  (o instrumento estatístico central do critério de Gate revisado não
  pode ser considerado confiável sem essa correção).

- **v3.18 (2026-08-18)** — M4 (Regime), continuação da v3.17 no mesmo
  dia: Manager autorizou "corrigir e rodar". BOCPD corrigido nos 2 bugs
  (`AG-084`/`AG-085` — série causal completa + canonicalização causal via
  `expanding_percentile_rank_strict`); Jump Model (`AG-087`) recebeu
  transparência de saturação (`is_saturated`/`saturation_rate`), não o
  resweep completo — decisão consciente de escopo. Detalhe completo na
  linha `M4(V4.1) — Regime` de `§11.6` (fonte canônica, não repetido
  aqui). Mecanicamente auditado, testes novos escritos, ainda não
  commitado nem re-executado — próximo passo real é a Fase D de novo.

- **v3.17 (2026-08-18)** — M4 (Regime), continuação da v3.16 no mesmo
  dia: Fase D (18 trials reais) concluiu com 0 falhas/pulos
  (`elapsed_seconds_total≈9737s`, `experiments/m4_critical_windows_
  report.json`). Manager rejeitou aceitar o resultado bruto ("não
  confiar, auditar desde a raiz") — despachou 5 auditorias céticas + RAG
  em paralelo (BOCPD, HMM, Jump Model, validade da métrica/baseline,
  orquestração/wiring). Achados reais, registrados `AG-084` a `AG-087`:
  BOCPD (único candidato com separação não-nula) tem 2 bugs empilhados —
  `m4_critical_windows.py` reseta o prior bayesiano dele a cada janela
  crítica (precisa de série causal contínua pra amadurecer) E
  `segments_to_canonical_states` (`bocpd.py`) usa a média do PRÓPRIO
  segmento (incluindo barras futuras) pra definir o rótulo, testado
  depois contra retorno futuro — leakage mecânico, reproduzido por
  decaimento de defasagem; Jump Model colapsa a 1 estado em ~25-29% das
  células (hiperparâmetro `jump_penalty=0,002` calibrado numa única
  fatia de BTC); HMM tinha bug real de k-means sem padronização de
  escala, mas TESTADO CAUSALMENTE (EM completo, init real vs. padronizado,
  ambos até convergência) e REFUTADO como causa do ω²≈0 — único achado
  tratado como genuíno. Baseline (ortogonalidade≈0,94 vs. volatilidade)
  é quase-tautológico por construção (`vol_pctile` é um dos 2 eixos que
  definem o próprio `regime` do baseline).

  Manager decidiu (via `AskUserQuestion`, "Opção 1 + Opção 3"): registrar
  os achados agora (feito) e reconsiderar o critério de Gate ANTES de
  corrigir código. 2 auditorias adicionais (literatura de regime-
  switching/DRO + aplicação ao desenho real do motor) convergiram,
  independentemente, na MESMA proposta: "separação de retorno a 1 barra
  via ANOVA de Welch" nunca é como a literatura valida regime que
  alimenta um modelo a jusante (DRO/veto) — substituído por **Cochran's
  Q/I² de `edge_bruto_atr` condicionado por bucket de regime**, reusando
  `m6_common_factor_hypothesis.cochrans_q_heterogeneity`/`stratum_
  metrics` sem fórmula nova. **Autorizado e implementado** no mesmo dia
  — `src/analysis/m4_critical_windows.py` ganhou `AggregatedHeterogeneity
  Result`/`CriticalWindowsReport.heterogeneity` (as-of join causal entre
  `labels.parquet` e o regime de cada candidato, mesma disciplina de Q3),
  auditoria mecânica limpa (ruff/mypy/banned_patterns/constants/
  unguarded-ratios), testes novos escritos. Q3 (Terceira via) também
  ficou pronto pra rodar junto (decisão do Manager: "guarde Q3 pra rodar
  junto aos demais depois que aplicarmos os 3 fix") — `_run_one_cell`
  passou a sempre coletar `RawLabels` (custo zero, já era calculado
  internamente) e a agregação de Q3/heterogeneidade reusa esse dado, sem
  nenhum fit adicional.

  3 gaps adicionais registrados `AG-088`/`AG-089`, ambos CONFIRMADOS sem
  impacto no M4 atual (verificado por leitura de imports — `m4_critical_
  windows.py`/`m4_regime_comparison.py` não importam `alpha`/
  `environments`/`dataset`) e deliberadamente deferidos: nenhum dos 3
  candidatos novos modela o veto de risco R5/stress (estudo dedicado
  confirmou que os gatilhos S1-S10 já são independentes do classificador
  de regime por leitura de código — `src/regime/stress.py` não referencia
  nenhum estado da máquina de histerese — recomenda desacoplar num
  módulo `veto.py` reusável por qualquer candidato, não implementado, só
  desenhado); vocabulário R1-R5 hard-coded em `alpha.py`/`classifier.py`/
  `environments.py` bloqueia promoção futura de candidato (`AG-088`);
  Group DRO (Camada 5) não existe em código ainda (`AG-089`) — Manager
  confirmou: continuar M4 mesmo assim, "errado seria criar consumidor
  pra consumir o que nem foi definido ainda".

  Correção de precisão, também nesta rodada: 2 dos 5 agentes reproduziram
  `generate_anchored_walk_forward_splits` real e encontraram que cada
  janela crítica produz 2 folds de teste, não 3 como documentado — o
  mês-alvo cai no fold 0, não no fold 1 (não muda nenhum número agregado,
  só a narrativa de cobertura) — corrigido em `_TARGET_FOLD_CAVEAT`/
  docstring do módulo. **Próximo passo real, ainda não feito**: corrigir
  os 3 bugs de código (BOCPD ×2, Jump Model) e re-rodar tudo junto
  (candidatos + Q3 + heterogeneidade) numa única execução — `G-C1-2`
  segue sem valor final ratificado.

- **v3.16 (2026-08-18)** — M4 (Regime): harness completo, calibrado,
  auditado, estendido — execução real (Fase D) em andamento no momento
  desta atualização, resultado ainda desconhecido. Harness ponta a ponta
  (baseline + HMM gaussiano `dynamax` k=2/3/4 + Jump Model contínuo/CJM
  + BOCPD vendorizado + Terceira via Q3, 19 commits `6158442`..`ccb50f1`).
  Plano completo commitado em `docs/m4_regime_plano_execucao.md` (achado
  `project_assurance`: só existia como doc de sessão, nunca versionado).
  Auditoria (`audit_engineering`+`project_assurance`, 6 agentes) achou e
  corrigiu 4 bugs CRITICAL/HIGH reais: canonicalização quebrava sob
  `NaN`/`Inf` (defeito central que o módulo existe pra eliminar, B21);
  Jump Model degenerava sob `Inf` silenciosamente; bug no próprio
  `tools/lint/banned_patterns.py` (`--path <arquivo>` escaneava zero
  arquivos, expôs `AG-082`, 25 `MAGIC_NUMBER` pré-existentes, backlog
  aceito); oversubscription de threads BLAS/JAX sob `ProcessPoolExecutor`
  + falta de `mp_context="spawn"` explícito (risco de deadlock por fork
  em produção/Linux). Manager decidiu (5 itens empilhados): ANOVA F
  clássica → Welch's F (`statsmodels`, regimes de volatilidade violam
  homocedasticidade por construção); causalidade em bloco do Jump Model
  documentada como caveat, `.predict()` mantido; contagem de 6 trials
  confirmada pro desenho original. Hiperparâmetros calibrados via
  medição real (`jump_penalty=0,002`, `bocpd_hazard_lambda=65,0`, nunca
  inventados). **Extensão pós-calibração** (pedido do Manager, motivo
  quantificado — histórico completo levaria várias horas): M4 passou a
  rodar sob 5 janelas históricas críticas (LUNA/FTX só BTCUSDT, Crypto
  Winter/ETF-Halving/Recente 5/5 ativos) × 3 resoluções R1/R2/R3 (que
  SÃO os "3 timeframes" de produção, `AG-042`) — `src/features/
  _sources.py` ganhou wiring de `dollar_r2`/`dollar_r3`; módulo novo
  `src/analysis/m4_critical_windows.py` orquestra janela×resolução×
  símbolo com agregação mediana-de-medianas. Manager decidiu (via
  `AskUserQuestion`) que resolução MULTIPLICA trial (mesmo precedente já
  usado em M1, `audit/n_lifetime.yaml` id16) — `G-C1-2` revisado de
  `≤6` pra `≤18` (**ainda não ratificado formalmente em `PRD_V4_1.md`/
  `docs/m4_regime_plano_execucao.md`, ver §11.6**); janela histórica NÃO
  multiplica. Auditoria da extensão achou e corrigiu 1 HIGH real
  (`AG-083`: relatório sem checkpoint incremental por resolução, mesma
  classe de gap já corrigida no M2 — falha tardia descartaria horas de
  fit real). `docs/SPRINT_LOG.md` ganhou seção narrativa completa +
  tabela "Estado atual" atualizada na mesma sessão.

- **v3.15 (2026-08-17)** — Migração Parkinson canônico + dollar-bar
  (`resolution_id=R1`) ponta a ponta. M1 remedido sob dollar bar (5
  símbolos × 3 resoluções × 6 candidatos) — Parkinson bate GK em 12/15,
  Manager decidiu Parkinson canônico (`AG-036::addendum_decisao_
  manager_2026_08_17`). §11.5 ganhou linhas novas pras Fases 0-4 (Label/
  Feature/Regime Engine + orquestração, commits `e32b7a4`/`5df33c3`/
  `3449471`/`9a4c3c5`/`b5760fe`, 1305/1305 sem regressão) + auditoria
  final (`audit_engineering`, 4 agentes, `d03d207`, 3 HIGH corrigidos).
  §11.4 (linha "quando reprocessamento dollar-bar concluir") fechada —
  Manager autorizou execução real de labels/leakage/Feature-Regime pros
  5 símbolos (`6219d02`: 12 PASS/0 FAIL/2 sentinela nos 14 testes de
  vazamento contra R1, todos os símbolos), mas explicitamente NÃO o
  retreino real do Alpha nem o flip de `canonical_volatility_estimator.
  value` — nova linha registra essa pendência como decisão do Manager,
  não esquecida. `N_lifetime` (`audit/n_lifetime.yaml`) excedeu o
  orçamento (63/60) — override autorizado e registrado (id 17,
  `delta=0`). `docs/SPRINT_LOG.md` (fora deste doc, mas parte da mesma
  correção de governança) estava desatualizado desde 2026-08-16, sem
  nenhuma menção a essa migração inteira — corrigido na mesma sessão.

- **v3.14 (2026-08-16)** — `AG-042`/`AG-037` fechados (escopo M2 +
  `grade_id`). Manager escolheu o escopo completo entre 2 opções
  apresentadas (M2 sozinho, ou M2 + `cpcv.py`) depois de eu achar que
  `AG-042` dependia de `grade_id` (`AG-037`) como pré-requisito real —
  inversão de ordem não percebida antes. `BarComparisonMetrics` ganha
  `resolution_id` (R1/R2/R3), separado de `tf` (que vira só parâmetro de
  calibração) — fecha a "mentira operacional" de M15/M30/H1 em dollar/
  volume/tick_imbalance bars (§3.5, Opção D). `CPCVConfig` ganha
  `grade_id` (deriva de `tf`, retrocompatível); `assert_tf_consistent`
  renomeada `assert_grade_consistent`, `NotImplementedError` explícito
  fora do dict de `step_ms` em vez de fingir verificar identidade de
  grade dollar sem mecanismo. ~15 callers reais de `generate_splits`
  auditados, nenhuma mudança de comportamento. 2 bugs de raiz achados
  pelo pytest do usuário: um meu (`dict(zip(...))` com argumentos
  invertidos, pego pelo próprio teste de regressão que escrevi) e um
  pré-existente (fakes de teste desatualizados desde commit `f0bd28c`,
  mesma classe já documentada no arquivo). `105 passed`, commit `982b5d4`.
  Alarme de deriva (`src/monitoring/`) e regra de `calibration_version`
  seguem fora de escopo — sem caller real até dollar bar ser implantado.

- **v3.13 (2026-08-16)** — Bug de raiz corrigido, achado pelo usuário
  rodando pytest sobre v3.12: `estimator_id` (convenção `atr_wilder_w{N}`)
  depende de `atr_window_ms` E `tf` juntos, mas `dataclasses.replace(cfg,
  tf=novo)` só atualiza `tf` — mesma classe de risco que a docstring da
  classe já citava pra `atr_window_ms` sozinho, dependência de `tf` não
  reconhecida. Solução: validação em `LabelConfig.__post_init__` (falha na
  construção, não 2-3 chamadas depois dentro de `build_labels`). Expôs de
  quebra um bug pré-existente mais antigo (11 construções de teste com
  `atr_window_ms=20` literal, devia ser `20*900_000`) e 3 call-sites de
  teste com `replace(cfg, tf=X)` incompletos — nenhum caller de produção
  real afetado. Detalhe completo em `AG-031`.

- **v3.12 (2026-08-16)** — AG-031/B1 fechado com escopo COMPLETO. Manager
  pediu releitura de `docs/refactor_dollar_bar_canonico.md` + artefato
  "Bloqueadores Dollar Bar" pra checar alinhamento — achou duas divergências
  entre o que v3.11 tinha entregue e o que estava decidido: (1) linha 403
  do doc é taxativa que `time_stop`/`atr_window` têm que fechar no MESMO
  pacote, mais forte do que o texto do AG-031 sozinho sugeria; (2) linha
  379 pede `n_bars_held` como contagem REAL, não só o invariante trocado.
  Manager decidiu incluir os dois. `atr_window` implementado como
  `atr_window_ms` (mesmo padrão de `time_stop_ms`, nova constante
  `constants.yaml`, `constants.yaml::atr_window` original preservada pro
  Feature Engine que a usa em paralelo, deliberadamente em barras).
  Achado de processo: a exclusão original de `atr_window` citava o
  `NotImplementedError` de `ATRWilderEstimator.estimate()` como bloqueio —
  leitura equivocada (esse guard protege `horizon_minutes`, não `window`).
  `n_bars_held` vira contagem real via busca em array (`t0_arr` no motor
  escalar, novo parâmetro opcional `decision_bar_close_time_ms` no
  vetorizado), com fallback aritmético pra cauda sem buffer e testes novos
  provando detecção de gap real (não é reformulação equivalente da
  aritmética). `AG-047`/`AG-048` registram as duas decisões do Manager.

- **v3.11 (2026-08-16)** — AG-031/B1 implementado: `LabelConfig.
  time_stop_bars`→`time_stop_ms` (relógio fixo), mesma classe de bug do
  AG-004/AG-032 (parâmetro interpretado incompatível por `triple_barrier.py`
  vs. `m2_bar_comparison.py`). 7 arquivos de produção + 4 de teste tocados;
  3 testes que travavam a convenção ANTIGA ("horizonte escala com TF")
  reescritos pro invariante correto. `atr_window` (mesma I2) EXCLUÍDO do
  escopo por decisão de implementação — `ATRWilderEstimator` não tem
  conversão relógio↔barra, constante compartilhada com Feature Engine,
  mudança não seria neutra (muda suavização real do Wilder ATR entre TFs).
  Revisão independente (`project_assurance`, Agent fresco) achou 4 gaps
  reais, não no núcleo técnico: `AG-044` (alto — mecanismo de tolerância
  a schema antigo em `experiment_log.py` nunca tinha sido testado contra
  schema real, corrigido na hora com teste novo), `AG-045` (médio — risco
  de `SchemaError` em pooling se regeneração de `labels.parquet` ficar
  parcial entre os 5 símbolos, corrigido na hora com `vertical_relaxed`),
  `AG-046` (médio — `time_stop_bars`/`time_stop_ms` sem guard de
  sincronização, mesmo trade-off já aceito em `cpcv_embargo_bars`/`_ms`,
  registrado não corrigido), `AG-047` (médio — este próprio changelog não
  registrava a restrição de escopo do `atr_window`, corrigido). Pendente:
  confirmação de pytest antes de commitar.

- **v3.10 (2026-08-16)** — E1 fechado. Usuário confirmou `uv run pytest
  tests/unit/test_validation_cpcv.py -v` → **42 passed in 2,37s**, nenhuma
  regressão. Commitado (`3b19c20`) e pushed pra `origin/master`, junto com
  os dois artefatos de medição (`experiments/cpcv_embargo_clock_
  candidate.json`, `experiments/prototype_dollar_bar_duckdb_vs_polars.
  json`) como evidência. Dependência em aberto registrada (não fechada
  aqui): `max_feature_lookback_ms` (E4, componente 96) ainda não tem
  nenhum caller de produção real que o wire-e — só o teste sintético prova
  o mecanismo.

- **v3.9 (2026-08-16)** — E1 (embargo do CPCV) implementado. Usuário mediu
  o candidato real (`tools/diagnostics/measure_cpcv_embargo_clock_
  candidate.py`, dataset real 462.682 linhas): **96,39h**, 2,2x o legado
  (43,75h) — confirma por medição a suspeita já registrada em
  `constants.yaml::cpcv_embargo_bars` (nunca antes verificada). Corrige
  hipótese própria anterior desta sessão que presumiu "menor" sem medir.
  `CPCVConfig.embargo_bars`→`embargo_ms`, nova constante `cpcv_embargo_ms`
  (MEASURED), `step_ms(tf)` sai do cálculo de embargo especificamente.
  Teste `test_embargo_ms_escala_com_tf_nao_fica_preso_em_15m` reescrito
  pro invariante oposto (embargo não escala mais com `tf`). Pendente:
  confirmação de pytest antes de commitar.

- **v3.8 (2026-08-16)** — Nova seção **§11.5 M1+M2 — Refactor dollar-bar
  canônico, ponta a ponta**: aba dedicada de rastreio camada-por-camada
  (10 linhas, `exchange`→`live`) pro redesenho completo disparado por M2/
  M1, a ser atualizada a cada commit real (regra explícita: sem commit
  apontável, sem mudança de status). Primeira linha fechada: `validation`/
  purge (`AG-032`/E4) — componentes 32+96, 42/42 testes, revisão
  independente sem achado bloqueante, commit `a7e7e16`.

- **v3.7 (2026-08-16)** — Correção do Manager sobre a resposta de N_lifetime
  da v3.6: as 13 constantes classe A ainda `ASSUMED` NÃO são orçamento de
  trials em risco agora — cada uma já tem `review_by` (sprint) em
  `config/constants.yaml`, esperado desde a decisão de multi-TF/multi-ativo,
  não um achado novo. Nova seção **§11.4 Road Map Vivo** — rollup por
  stage de tudo que já tem sprint/gatilho de revisão declarado, pra essa
  informação ter um lugar certo em vez de virar narrativa de "decisão
  pendente" fora de contexto. Único item com custo real de `N_lifetime`
  desta rodada continua sendo `AG-036` (M1 remedido, disparado pelo achado
  de M2 — diferente dos 13 porque não estava agendado).

- **v3.6 (2026-08-16)** — Objetivação dos 5 pontos em aberto de v3.5: (1)
  `project_assurance` disparado (Agent independente) sobre `docs/refactor_
  dollar_bar_canonico.md`, escopo focado em 3 perguntas prioritárias —
  `assert_tf_consistent` precisa de redesenho separado dos 4 opções do
  Bloqueador 2? acoplamento posicional de T1 em `src/models/` está completo
  no relatório? a regra "sweep classe A = 1 trial em bloco ou N por ponto"
  existe em algum lugar? — resultado pendente. (2) **T1 — escopo
  expandido**: as 13 features do registry atual (não as ~64 de
  `research/`, fora de escopo) viram pool único sem cap, ranqueadas via o
  procedimento já definido em `PRD_V3_2_UNIFICADO.md` §2.0.1 (Sprint 6:
  `N_eff` medido; Sprint 8: ablação por `k` dentro do CPCV, 5 variantes = 5
  trials). Achado: **não há dependência técnica dos 3 bloqueadores
  dollar-bar** — o adiamento registrado em v3.5 foi escolha de
  sequenciamento, não necessidade estrutural; pode rodar agora no grid de
  TEMPO (Sprint 4, atual), com remedição futura sob dollar bar (mesmo
  padrão de AG-036/M1). (3) Protótipo de medição DuckDB-nativo vs.
  Polars-vetorizado para construção de dollar bar aprovado e escrito
  (`tools/diagnostics/prototype_dollar_bar_duckdb_vs_polars.py`), aguarda
  execução do usuário. (4) Explicação visual de `N_lifetime`/constantes
  classe A entregue como artefato — sem mudança de `constants.yaml`.

- **v3.5 (2026-08-16)** — Fechamento de governança do pós-M2 (segue direto
  de v3.4). **AG-034** (esgotamento de memória sob concorrência plena) e
  **AG-035** (calibração quebrada de `tick_imbalance`) fechados por
  decisão explícita do Manager, risco aceito e registrado, não silenciado
  — nenhum dos dois é pré-requisito de `canonical_bar_type=dollar`, que já
  estava decidido sem depender deles. **Nova decisão do Manager**: remover
  o limitador de T1 (10 features curadas) — todas as features do registry
  passam a canônicas pro Alpha. Decisão registrada, implementação
  explicitamente adiada até os 3 bloqueadores abaixo fecharem.

  **3 bloqueadores identificados pro redesenho dollar-bar, delegados a
  investigação dedicada** (Agent, contexto rico, ponta a ponta data layer
  → ML layer, retorno em Markdown — resultado ainda não incorporado a este
  documento no momento deste changelog):
  (1) **AG-031** — `time_stop_bars`/horizonte do label não tem
  correspondência de relógio nenhuma sob dollar bars ("32 barras" deixa de
  significar "8h"); (2) **redefinição de M15/M30/H1** — cada TF hoje é
  calibrado pra bater a frequência média histórica daquele TF em dollar
  bars, mas volume muda estruturalmente ano a ano (confirmado nas 5
  janelas de M2) — precisa decisão de design entre threshold fixo travado
  numa data vs. recalibração periódica; (3) **AG-032** — unidade do
  embargo do CPCV (128 barras) precisa da mesma reavaliação.

- **v3.4 (2026-08-16)** — **M2 fechado: `canonical_bar_type=dollar`**
  (`config/constants.yaml`, decisão do Manager, mesmo padrão de governança
  já usado pro `canonical_volatility_estimator`/GK em M1). Sequência real:
  1º run canônico completo achou 2 bugs (`AG-033`, fechados na hora —
  colisão de `temp_directory` do DuckDB entre os 12 processos
  concorrentes; limiar de plausibilidade do ADF calibrado contra caso
  sintético, nunca verificado contra dado real de produção, disparando
  falso-positivo em 13/13 tasks de barra de tempo); 2º run travou de novo,
  desta vez por esgotamento de memória real sob concorrência plena
  (`AG-034`, aberto — `SET memory_limit` do DuckDB só cobre o buffer
  interno, não o estado Python acumulado nem a soma de 12 processos).
  Em vez de reduzir concorrência ou encolher pra um mês só (perderia
  diversidade de regime, o próprio objetivo do teste), M2 rodou em 5
  janelas escolhidas deliberadamente por evento/regime real (LUNA/UST
  2022-05, FTX 2022-11 — confirmado no dado via anomalia real de funding
  do SOL, crypto winter 2023-06, ETF/halving 2024-03, recente 2026-07) —
  `--start`/`--end` viraram parâmetro de `m2_bar_comparison.py`. Dollar
  bars venceu tempo (baseline) em 4 das 5 janelas + no pooled, em toda
  métrica (Jarque-Bera, Ljung-Box r/r², unicidade) exceto ADF (empate —
  ADF passa 100% em todo tipo de barra, não discrimina neste teste).

  **Achado à parte, investigado a pedido do Manager**: `tick_imbalance`
  falhou em 5/5 janelas de forma tão sistemática (JB/Ljung-Box=0%,
  unicidade ~300x menor) que parecia sinal estrutural, não ruído — e era,
  mas não do jeito hipotetizado. Causa raiz encontrada lendo
  `src/data/bars.py` linha a linha (`AG-035`, aberto): a calibração da
  harness de M2 pra esse candidato específico (`_build_tick_imbalance_
  config`) usa a MESMA fórmula de dollar/volume bars
  (`exp_num_ticks_init = n_ticks/target_n_bars`) — mas tick imbalance bars
  não fecham após consumir um nº fixo de ticks, fecham quando o
  DESEQUILÍBRIO LÍQUIDO acumulado atinge `exp_num_ticks × |ewma_b|`. A
  fórmula da harness assume implicitamente desequilíbrio ≈100% por tick
  (todo tick na mesma direção) — falso pra qualquer mercado líquido, onde
  o desequilíbrio real tick-a-tick fica na casa de 0,1%-1%. Resultado
  observado (250x-1000x mais barras que o alvo, em toda combinação, sem
  exceção) bate com essa causa. Conclusão: o resultado mede uma
  calibração quebrada, não que tick imbalance bars sejam ruins pra cripto
  — a decisão de `canonical_bar_type` seguiu adiante mesmo assim porque a
  vitória de dollar sobre TEMPO (o baseline que de fato importa) não
  depende do resultado de tick_imbalance.

  **Efeito colateral de governança**: as duas condições do gate de
  reprocessamento do GK (`canonical_volatility_estimator`, "adiado até M2
  e M3 fecharem") estão as duas satisfeitas agora — M3 (TF=15m) já
  estava decidido, M2 fechou hoje. Isso NÃO inicia reprocessamento
  sozinho, só remove o bloqueio formal; decisão de quando/se reprocessar
  `labels/`+Feature+Regime Engine pra grade dollar-bar segue pendente,
  registrada como pendência explícita, não como trabalho em andamento.

  Artefato "Biblioteca de Testes" (antes só M1/GK) ganhou aba M2 —
  1ª vez que um artefato deste projeto vira multi-teste em vez de
  single-use, a pedido do Manager ("quero que aquele HTML se torne a
  biblioteca dos testes que fazemos").

- **v3.3 (2026-08-15)** — 5 agentes em paralelo (contexto rico) resolvem o
  que era medível/pesquisável a custo 0 do panorama consolidado de AG-027:
  **AG-031** (novo) — `time_stop_bars=32` interpretado de forma
  incompatível por `m2_bar_comparison.py` (relógio fixo, 8h) e
  `triple_barrier.py` pós-AG-005 (contagem de barra fixa, escala com TF) —
  achado maior do que o esperado: o PRD_V4_1.md JÁ DECIDIU esta questão
  três vezes (§2.7/§3.2/§4.2 + changelog formal V4.0→V4.1), três dias
  antes do commit de AG-005, que corrigiu só o bug de unidade sem
  consultar essa decisão. `atr_window` carrega a mesma pendência
  (`"ressalva herdada"`, nem M1 nem M3 resolveram). Recomendação (relógio
  fixo, custo zero hoje — nenhum label em 30m/1h existe no disco) NÃO
  implementada, decisão do Manager. **AG-032** (novo) — proposta de
  reclassificar `cpcv_embargo_bars` pra `DERIVED` com "96 basta" está
  mecanicamente incorreta: o piso real, dado como `purge_mask`/
  `embargo_mask` funcionam hoje em `cpcv.py`, é 128 (32+96), não 96 —
  175 ainda cobre com folga, mas a fórmula proposta subestimaria o piso
  em 25%. Mantido `LITERATURE`, não `DERIVED`. **AG-027, pendências 2 e 3
  resolvidas** — "ER (16,48)" do PRD são DUAS features (B07 T1 + B08 T2,
  esta última testada uma vez em pesquisa exploratória 2026-08-09 e nunca
  promovida, não "candidato descartado"); validade de B07 como eixo de
  regime confirmada como convenção nunca testada, decisão do Manager
  pendente. Dois scripts de medição descritiva entregues, aguardando
  execução: `sample_weight` médio por `econ_regime` (Canal 3 do Manager —
  hipótese de subponderação de regime hostil via unicidade) e
  sazonalidade de funding em ΔOI por símbolo (E10f).

  Decisões do Manager sobre o panorama, mesma sessão: custo de funding
  fica fora de `round_trip_cost_bps` por escolha deliberada de escopo
  (não indecisão); **AG-029 fechado** — `assert_label_invariants` cabeado
  em `build_and_write_labels_for_symbol`, falha alto com `symbol`/`tf` no
  erro; whitelist do lint (`0,5`/`2,0` em `round_trip_cost_bps`/`a05`)
  ganha entrada própria em `constants.yaml`
  (`round_trip_cost_bps_maker_prob`/`feature_a05_vol_norm_divisor`) e
  marcador inline no código — visibilidade corrigida, VALOR mantido
  (Regra Zero); teste `slow` de calibração desproporcional corrigido
  (baseline escopado à janela do teste, não ao histórico inteiro); AG-030
  e a atualização de `docs/refactor_gk_canonico.md` explicitamente
  adiados pro Road Map Vivo como pendência (não agora); discovery de
  arquitetura pra triagem IC in-fold multi-horizonte (§5.4, resposta ao
  vão "features validadas contra 32 barras, label resolve em 7")
  delegado a agente antes de desenhar a infraestrutura de verdade.

- **v3.2 (2026-08-15)** — Manager entrega "Continuando Ultrathink" (7 pontos
  sobre AG-027), todos verificados por Claude via leitura direta de código/
  dado antes de aceitar. Ponto mais crítico (#1): rodar a lente FE
  ingenuamente arriscava disparar o critério de encerramento #5 sozinho —
  `N_lifetime` tem só 15 trials restantes (counter=45, teto=60). §6.1 ganha
  "Regra de segurança orçamentária": as 10 perguntas da lente FE são 0
  trials por desenho, nenhuma resposta autoriza sweep sem escalar ao Manager
  com o orçamento restante explícito (mesma regra espelhada em
  `audit_engineering` v1.5). §7 ganha AG-030 (achado #5 do Manager) —
  features expansivas desde a origem do ativo (C07/D03f/E02f) confundem H0
  do M6 por escala de histórico desigual entre BTC (231.552 barras) e os 4
  alts (164.256), decisão necessária antes do M6 rodar. AG-027 recebe
  addendum com os 7 pontos completos: Q2 já tinha resposta medida em
  `backtest_fill_reconciliation_report.json` (59,9% SL — mais assimétrico
  que a teoria); vencedor do M1 (GK canônico) é condicional ao tipo de
  barra do M2, razão de adiamento hoje registrada em `docs/
  refactor_gk_canonico.md` é mais fraca que a real; whitelist de literais
  do lint (`_ALLOWED_NUMERIC_LITERALS`) esconde 2 premissas de domínio sem
  proveniência (0,5 do split maker/taker, 2,0 de `a05_ret_vol_norm_4`);
  `sweep_required: false` nas 8 janelas reclassificado de "furo a corrigir"
  pra "decisão de Business Case pendente do Manager".
- **v3.1 (2026-08-15)** — §6.1/§7: AG-027 (Manager, lente Feature/Alpha/
  Signal Researcher — 8 janelas de feature `ASSUMED`/nunca testadas em
  contagem de barra, Feature Engine hardcoded em 15m; `round_trip_cost_bps`
  assume 50/50 de qual barreira toca primeiro, viés quantificado ~4% via
  rederivação matemática independente — não hipótese) + AG-028
  (`check_constants_provenance.py` nunca lia `review_by` de constantes
  classe B, corrigido). Nomeia a classe de defeito "parâmetro carrega
  escopo implícito nunca declarado" (4ª ocorrência: AG-004→AG-005→
  AG-017→AG-027) como categoria própria do RAID em §7, e adiciona os 3
  eventos de transição de escopo que disparam a nova lente FE de
  `audit_engineering` (v1.4) em §6.1. Header corrigido de "2.2" pra "3.1"
  — estava desatualizado desde 2026-08-12 enquanto o Changelog já tinha
  passado por v2.3-v3.0 (mesma classe de defeito já nomeada em §15.5
  item 1 pro CLAUDE.md, agora confirmada também neste documento).
- **v3.0 (2026-08-15)** — §15.10: AG-017 — `m2_bar_comparison.py` escrito
  com TF único (15m) hardcoded, apesar do PRD_V4_1.md §0.4 exigir os 3
  TFs "obrigatórios ponta a ponta" E de §15.6 item 1 (escrito ANTES de M2
  existir) já ter citado M2 por nome como risco previsto. Corrigido
  (commit `67a1426`) — módulo agora itera `TIMEFRAMES`, mesmo padrão de
  `m3_timeframe_choice.py`. Registra por que o registro RAID sozinho não
  bastou (nada no processo de escrever código novo consultava esse
  registro antes de codar) e a correção de processo (nova pergunta na
  Lente FI de `audit_engineering`, v1.3). Mesma sessão: M2 também
  corrigido pra streaming (não cabia inteiro em RAM) e pra travar
  `memory_limit`/`threads` do DuckDB por conexão (oversubscription sob
  processos concorrentes) — ver `AG-017` completo em
  `audit/architecture_gaps_log.yaml`.
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
