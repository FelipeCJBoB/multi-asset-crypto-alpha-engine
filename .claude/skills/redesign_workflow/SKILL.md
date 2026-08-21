---
name: redesign_workflow
description: |
  Use em sessões de trabalho estendido envolvendo redesenho de arquitetura
  ou feature grande — não fix pontual, não ajuste trivial. Triggers:
  "vamos redesenhar X", "preciso de uma arquitetura nova pra Y", "investiga
  e propõe um desenho pra Z", pedido do Manager que mistura auditoria de
  resultado real + decisão de arquitetura + implementação (mesmo padrão da
  sessão que investigou M4/AG-114: medir → decidir regra → aplicar →
  desenhar consumo em produção). NÃO use pra bug isolado, ajuste de 1
  arquivo, ou tarefa já totalmente especificada — nesses casos o workflow
  de 7 fases é fricção, não ajuda.

  Porta pra este projeto o "Feature Development Plugin" (Anthropic,
  `README.md`/`feature-dev.md`/`code-architect.md`/`code-explorer.md`/
  `code-reviewer.md` fornecidos pelo Manager, 2026-08-20) — mesmo workflow
  de 7 fases (Discovery → Exploração → Perguntas → Arquitetura →
  Implementação → Revisão → Resumo), adaptado às regras deste repo
  (protocolo de execução, camadas, proveniência de constante,
  PLANO_MESTRE como destino de decisão).
---

# redesign_workflow — Feature Development de 7 fases, adaptado ao Motor Quant

## Proveniência

Porta do "Feature Development Plugin" (Anthropic, `Sid Bidasaria`) pra
este repo — os 5 arquivos-fonte (`README.md`, `feature-dev.md`,
`code-architect.md`, `code-explorer.md`, `code-reviewer.md`) foram
fornecidos pelo Manager em 2026-08-20, com o pedido explícito "vamos
passar a usar essa skill em momentos de codar estendido para redesenho
como estes" — referência direta à sessão que investigou M4/AG-114
(auditoria de resultado real → regra de decisão → candidato vencedor →
desenho de consumo em produção via AG-118). As 7 fases originais são
preservadas — o que muda é a camada de disciplina do projeto injetada em
cada uma (execução, camadas, proveniência, onde a decisão fica
registrada).

**Os 3 agentes originais (`code-explorer`/`code-architect`/`code-reviewer`)
já existem como agentes deste ambiente Claude Code**, sob o namespace do
plugin (`feature-dev:code-explorer`, `feature-dev:code-architect`,
`feature-dev:code-reviewer`, disponíveis via `Agent` tool,
`subagent_type`) — não foram recriados aqui. Esta skill só ORQUESTRA
esses 3 agentes já existentes, na sequência certa, com o contexto certo
injetado em cada chamada.

## Quando usar (e quando não)

Use pra trabalho do tamanho de "M4/AG-114 desta sessão" — redesenho de
arquitetura, feature grande com decisão de desenho real, qualquer tarefa
onde a resposta não é óbvia de antemão e vale a pena explorar → perguntar
→ desenhar → implementar → revisar como sequência, não pular direto pro
código.

**Não use** pra: fix de 1 linha, ajuste de teste, tarefa já 100%
especificada pelo Manager (nesse caso just implementa), qualquer coisa
que caiba em uma sessão curta sem exploração/decisão de arquitetura real.

## As 7 fases, com a camada deste projeto

### Fase 1 — Discovery

Igual ao original (entender o problema, perguntar se pouco claro) — **mais
o Bootstrap que `CLAUDE.md` já exige antes de qualquer decisão grande**,
que aqui vira parte da própria Discovery, não um passo à parte:

1. `docs/SPRINT_LOG.md` — últimas seções, estado real (⚠️ pode estar
   desatualizado — confira contra `git log`/`architecture_gaps_log.yaml`
   antes de confiar cegamente, achado real desta sessão).
2. `PLANO_MESTRE_PRINCE2.md` §11.4 (Road Map Vivo) — o que já está
   agendado pra qual stage.
3. `audit/architecture_gaps_log.yaml` — gaps abertos (`AG-NNN`) na área
   que o redesenho toca. Um redesenho que ignora um `AG-NNN` já aberto na
   mesma área está resolvendo o problema errado.
4. `audit/n_lifetime.yaml` — se a tarefa envolve otimização/sweep/retreino.
5. `config/constants.yaml` — se toca em constante nova ou existente.

Cria a lista de todos (`TodoWrite`) com as 7 fases já no início.

### Fase 2 — Exploração do código

Lança 2-3 agentes `feature-dev:code-explorer` em paralelo (via `Agent`
tool, `subagent_type: "feature-dev:code-explorer"`), cada um com foco
diferente — mesmo padrão do original, mas o prompt de cada agente deve
citar explicitamente **a camada** (`exchange → data → features → labels →
regime → models → validation → backtest ← risk ← execution ← live`,
`CLAUDE.md`) que ele está explorando, pra já vir com o contrato de import
(`importlinter`) em mente, não descobrir depois que violou fronteira de
camada.

Depois que os agentes voltarem, leia os arquivos-chave que cada um
apontou — não pule essa leitura achando que o resumo do agente basta
(mesma disciplina de `project_assurance`: resumo de agente é ponto de
partida, não substituto).

### Fase 3 — Perguntas de esclarecimento

**Não pule.** Use `AskUserQuestion` (ferramenta nativa deste ambiente,
preferível a só escrever a lista em texto) quando a decisão for
genuinamente do Manager — preferência de abordagem, trade-off sem
resposta técnica única, escopo. Antes de perguntar, cruze com o que já
foi descoberto na Fase 1/2:

- Alguma constante relevante está `ASSUMED`/`TBD` em `constants.yaml`?
  Isso pode ser uma das perguntas (ou pode virar sweep de sensibilidade
  depois, não decisão de pergunta).
- Algum `AG-NNN` aberto já contém uma decisão parcial sobre isso? Cite,
  não repita a pergunta que já foi respondida.

Se o Manager disser "o que você achar melhor", dê a recomendação e peça
confirmação explícita — nunca proceda calado.

### Fase 4 — Desenho de arquitetura

Lança 2-3 agentes `feature-dev:code-architect` em paralelo (focos:
mudança mínima / arquitetura limpa / equilíbrio pragmático — mesmo
original). **Cada prompt de agente deve incluir, como restrição não
negociável, não como sugestão:**

- Nenhum literal numérico novo fora de `config/constants.yaml` (banned
  patterns, `tools/lint/banned_patterns.py`).
- Toda constante nova precisa de `provenance` declarada
  (`MEASURED`/`DERIVED`/`LITERATURE`/`ASSUMED` + `class`).
- Respeitar a hierarquia de camadas — o desenho não pode propor um import
  que o `importlinter` rejeitaria (`features/` não importa `labels/`,
  `models/` não importa `execution/`, etc., `CLAUDE.md` "Layer
  hierarchy").
- Nunca estipular faixa esperada/threshold que deveria ser medido (B23) —
  se o desenho precisa de um número que não existe ainda, ele declara
  `TBD — medir`, não inventa.

Depois de revisar as propostas, decida qual recomendar (não delegue essa
decisão de volta pro Manager sem opinião — mesma disciplina do agente
original: "form your opinion"). Ao apresentar, **marque explicitamente
quais decisões desta arquitetura merecem entrada em
`PLANO_MESTRE_PRINCE2.md`** (decisão de desenho com motivo, não só "o quê")
— nunca em `PRD_V3_2_UNIFICADO.md`/`PRD_V4_1.md` (que são blueprint
técnico, só ganham ponteiro de 1 linha, `feedback_plano_mestre_canonico`).

Pergunte qual abordagem o Manager prefere antes de implementar.

### Fase 5 — Implementação

**Não começa sem aprovação explícita.** Depois de aprovado:

- Claude escreve/edita código normalmente (`Write`/`Edit` não é
  "execução" pelo protocolo deste projeto).
- **Claude nunca executa `.py`/`pytest`/`uv run <subcomando>` via
  Bash/PowerShell** — só os 7 comandos mecânicos nomeados
  (`banned_patterns.py`, `check_constants_referenced.py`,
  `check_constants_provenance.py`, `check_unguarded_ratios.py`,
  `check_sprint_log_references.py`, `ruff check`, `mypy`) são exceção
  (autorização nomeada do Manager, `CLAUDE.md`). Qualquer outra
  verificação (teste de unidade, rodar um script novo, `uv run quant
  ...`) — entregue o comando EXATO, pronto pra colar, e espere o Manager
  colar o output antes do próximo passo. **Exceção**: sessões onde o
  Manager já deu autorização ampla e explícita de execução (aconteceu
  nesta mesma sessão, "Pode autorizar executar uv e .py") — só vale
  enquanto durar essa autorização explícita, nunca assumida por padrão,
  e nunca repassada a sub-agentes desta skill (eles nunca executam,
  sempre devolvem comando pronto — achado real desta sessão:
  `feedback_never_relay_execution_permission_to_agents`).
- Segue o DoD por tipo de tarefa do `CLAUDE.md` (feature/modelo/execução)
  quando aplicável.
- Atualiza o `TodoWrite` conforme progride.

### Fase 6 — Revisão de qualidade

Duas opções, escolha pela materialidade do que foi tocado (mesmo
critério de 4 eixos de `project_assurance`: exposição financeira, peso
da decisão, complexidade, contexto de uso):

- **Baixa/média materialidade** (a maioria dos redesenhos de análise/
  ferramenta): 3 agentes `feature-dev:code-reviewer` em paralelo
  (simplicidade/DRY, bugs/corretude, convenções) — mesmo original,
  filtro de confiança ≥80.
- **Alta materialidade** (toca `src/labels/`, `src/risk/`,
  `src/execution/`, `src/regime/`, ou expõe interface nova consumida por
  mais de 1 módulo): invoque `audit_engineering` (lente quádrupla
  FS/FI/FT/FCN) e/ou `project_assurance` (revisão de integração
  independente) EM VEZ DE ou ALÉM DOS 3 `code-reviewer` genéricos — são
  mais específicas às 6 classes de bug já catalogadas neste projeto.

Testes: os agentes/skills de revisão podem apontar que teste falta —
**Claude nunca roda o `pytest` sozinho** (mesma restrição da Fase 5).
Entrega o comando exato (`uv run pytest tests/unit/test_X.py -m "not
slow" -q`) pro Manager rodar.

Apresenta os achados e pergunta: corrige agora, corrige depois, ou segue
como está — mesmo original.

### Fase 7 — Resumo

Marca todos completos. Resume o que foi construído, decisões-chave,
arquivos modificados, próximos passos — mesmo original — **mais**:

- Se alguma decisão de arquitetura foi tomada, ela está registrada em
  `PLANO_MESTRE_PRINCE2.md` (não só na conversa)?
- Se o redesenho resolveu ou abriu algum `AG-NNN`, o status está
  atualizado em `audit/architecture_gaps_log.yaml`?
- Commit é só quando o Manager pedir explicitamente (`CLAUDE.md`, git) —
  nunca proativo no fim da Fase 7.

## Diferenças deliberadas vs. o plugin original

| Original | Aqui |
|---|---|
| Fase 6 roda testes/lint direto | Claude nunca executa — entrega comando pronto (protocolo de execução) |
| Fase 4 não fala de camadas/constantes | Restrição obrigatória em todo prompt de `code-architect` |
| Fase 7 não fala de onde documentar | Decisão de arquitetura → `PLANO_MESTRE_PRINCE2.md`, nunca PRD |
| 1 tipo de revisão (code-reviewer genérico) | 2 trilhas por materialidade — genérico OU `audit_engineering`/`project_assurance` |
| Nenhuma menção a `AG-NNN` | Fase 1 cruza gaps abertos; Fase 7 atualiza status |

## Versionamento

```
v1.0 -- 2026-08-20 -- Criação, porta do Feature Development Plugin
                       (Anthropic) fornecido pelo Manager. Reusa os 3
                       agentes já existentes no ambiente
                       (feature-dev:code-explorer/code-architect/
                       code-reviewer), não recria. Injeta disciplina do
                       projeto (execução, camadas, proveniência,
                       PLANO_MESTRE, materialidade de revisão) nas 7
                       fases originais, sem mudar a sequência.
```
