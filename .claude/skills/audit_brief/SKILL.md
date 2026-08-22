---
name: audit_brief
description: Cria um brief autocontido de auditoria externa sobre uma decisão técnica/estatística em disputa ou não-trivial deste projeto (achado contra-intuitivo, metodologia sob questionamento, veredito que muda o motor real), pra um revisor sem acesso ao repositório dar segunda opinião cética. Processa o parecer de volta quando ele chegar. Use quando "vou levar isso pra fora"/"preciso de uma segunda opinião externa" — não pra relatórios internos de governança (isso é `stage_readiness_audit`/`audit_engineering`).
argument-hint: "<achado, decisão ou AG-NNN a levar pra revisão externa>"
---

# audit_brief — Brief de auditoria externa + processamento do parecer

## Proveniência

Porta o padrão estrutural de `competitive-brief` (skill genérica de análise
competitiva, Anthropic, fornecida pelo Manager 2026-08-21 como template de
FORMA — frontmatter, fases numeradas, seção de output, tips) pro USO REAL
que este projeto já pratica informalmente há 3 rodadas antes desta skill
existir: `docs/brief_auditoria_externa_2026-08-19_regime_alpha_execucao.md`,
`docs/brief_auditoria_externa_2026-08-19_material_de_apoio.md`,
`docs/brief_auditoria_externa_2026-08-20_gate_efficiency_ag118.md` — e o
parecer que voltou, `docs/parecer_auditoria_externa_2026-08-20_ag114_ag118.md`,
que **achou 4 problemas reais que as 12 perguntas do brief original não
cobriam** (o mais grave: `p05_return_atr` divide por `atr_at_t0`, a MESMA
unidade que já escala a barreira — torna a métrica quase-tautológica,
mecanismo que sozinho explica as 3 "anomalias" do `AG-118` original).
Essa skill não inventa o padrão — formaliza o que já funcionou, pra não
depender de reconstruir a estrutura do zero a cada rodada.

**Diferença de `stage_readiness_audit`/`audit_engineering`**: aquelas
produzem relatório de auditoria PARA CONSUMO INTERNO (Claude/Manager, com
acesso total ao repo, achados registrados direto em `AG-NNN`). Esta produz
documento PARA CONSUMO EXTERNO — revisor sem acesso ao código, sem contexto
de sessão, só o que o brief carrega. Isso muda a exigência de
autocontenção: nenhuma referência a "veja o código" sem colar o trecho
relevante (§9), nenhuma sigla do projeto sem explicar na primeira vez.

## Quando usar

Achado contra-intuitivo que merece ceticismo de fora antes de virar
decisão (`lift`≈1 do `AG-118`, resultado nulo generalizado do M4);
metodologia sob questionamento real, não retórico (Gate 1 do `AG-114`
misturando critérios); veredito que muda o motor de produção (promoção de
candidato de regime, mudança de arquitetura ratificada tipo ADR-001).

**Não usar** pra: relatório de rotina de governança (`stage_
readiness_audit`), auditoria de qualidade de código com acesso total ao
repo (`audit_engineering`), decisão já óbvia/sem tensão real — um brief
que não tem nenhuma pergunta cética genuína no §7 é sinal de que a skill
errada foi chamada.

## Fase 1 — Escopo

Antes de escrever qualquer coisa, confirme com o Manager (ou infira do
pedido, mas declare a inferência):

- **Qual é o achado/decisão central?** (1 frase — o brief inteiro existe
  pra sustentar ou questionar essa frase)
- **Qual é a TENSÃO real?** Um brief sem tensão genuína (resultado limpo,
  sem ambiguidade) não precisa de revisão externa — se não há tensão,
  pare e pergunte se o pedido não é melhor atendido por um registro
  `AG-NNN` direto.
- **Este brief depende de outro já existente?** (mesmo padrão do exemplo:
  o brief do `AG-118` dependia do `AG-114` — declarado explicitamente no
  §0 "Como usar este documento", "3 entregas sequenciais, cada uma
  dependente da anterior")
- **Precisa de um "material de apoio" companion?** (dado bruto extenso,
  tabelas completas que poluiriam o brief principal — mesmo padrão do
  `..._material_de_apoio.md` já usado)

## Fase 2 — Reunir contexto (bootstrap, não pule)

Mesmo bootstrap de `CLAUDE.md`, aplicado ao ESCOPO do achado específico,
não ao projeto inteiro:

1. `audit/architecture_gaps_log.yaml` — a(s) entrada(s) `AG-NNN`
   relevante(s), lidas por INTEIRO (histórico + todos os `addendum_*`,
   não só o campo `status` mais recente).
2. `PLANO_MESTRE_PRINCE2.md` — seção(ões) que registram a decisão/regra
   sendo questionada.
3. `experiments/*.json` relevantes — dado REAL medido, nunca reescreva um
   número de memória; leia o JSON de novo antes de citar.
4. Rode os mecânicos aplicáveis (`banned_patterns.py`, `ruff`, `mypy` nos
   arquivos citados) — o brief declara "isto já foi checado", não deixa
   o revisor externo perder tempo com lint.
5. Confirme os 2 documentos canônicos do momento (`PLANO_MESTRE_PRINCE2.md`
   + ADR-001 completo — nunca os PRDs, exceto citação histórica pontual)
   — vai no cabeçalho do brief, sempre.

## Fase 3 — Gerar o brief

Estrutura fixa (não é sugestão, é o que os 3 briefs reais já usam):

```markdown
# Brief para Auditoria Externa — <título que resume a pergunta central>

### <subtítulo — o arco narrativo em 1 linha>

**Data:** <YYYY-MM-DD>
**Para:** revisor externo (sem acesso ao repositório — este documento é
a fonte completa)
**Documentos canônicos deste projeto:** `PLANO_MESTRE_PRINCE2.md`
(governança/decisões) e o ADR-001 completo (~1900 linhas). `PRD_*` são
OBSOLETOS — citados só quando relevante pra explicar divergência
histórica, nunca como justificativa de desenho atual.

---

## 0. Como usar este documento
<dependências entre seções, se houver; o que o revisor deveria ler antes
de responder; pedido concreto adiantado em 1 frase, detalhado no §final>

## 1. Contexto
<recap pra quem não viu nada antes — por que a pergunta importa, o que
mudou pra ela existir>

## 2..N. Corpo técnico
<a narrativa real, com TABELAS DE DADO MEDIDO (nunca invente célula —
toda tabela cita o experiments/*.json ou constants.yaml de origem),
metodologia explicada (não só o resultado — POR QUE essa métrica, POR
QUE essa faixa de teste), achado central destacado>

## N+1. Verificação mecânica
<o que já foi checado antes deste brief — ruff/mypy/banned_patterns/
testes — pra o revisor focar em lógica/metodologia, não sintaxe>

## N+2. Achados colaterais (não bloqueantes, registrados por transparência)
<qualquer coisa encontrada no caminho que não é o foco central mas não
deveria ficar escondida>

## N+3. Perguntas que um <papel> cético deveria fazer
<NUMERADAS, cada uma com tensão REAL — não retórica. Padrão de cada
pergunta: "X foi decidido/medido assim — Y seria a alternativa, e a
escolha entre elas muda Z". Uma pergunta que já tem resposta óbvia não
entra aqui>

## N+4. O que pedimos exatamente
<3-5 itens concretos — nunca "revise isso" genérico. Inclui pelo menos
1 pedido de "valide OU refute [leitura específica]" e 1 pedido de
recomendação de próximo passo entre opções nomeadas>

## N+5. Anexos técnicos
<trechos de código REAIS citados no corpo, colados aqui — o revisor não
tem acesso ao repo, não pode abrir o arquivo>
```

**Regras não-negociáveis** (mesma disciplina de `CLAUDE.md`, aplicada ao
gênero "documento pra fora"):

- Nenhuma tabela com número que não venha de um `experiments/*.json`/
  `constants.yaml`/teste real já rodado — B23 aplica aqui igual a código.
- O brief NUNCA decide o veredito por conta própria — apresenta a tensão,
  pede a leitura de fora. Se você (Claude) já tem uma opinião forte, ela
  vai no §N+4 como "nossa leitura provisória é X, valide ou refute", nunca
  apresentada como fato assentado.
- §N+3 (perguntas céticas) é o coração do documento — se sair fraco
  (perguntas óbvias, sem tensão), o brief inteiro falhou seu propósito.
  Teste: cada pergunta deveria ser capaz de, em tese, mudar a decisão se
  respondida na direção "errada".
- Idioma/tom: mesmo pt-br técnico do resto do projeto, mas sem pressupor
  que o leitor viu qualquer coisa desta sessão — cada sigla (`AG-NNN`,
  `CPCV`, nomes de constante) precisa de 1 frase de contexto na primeira
  aparição.

## Fase 4 — Onde salvar

`docs/brief_auditoria_externa_{YYYY-MM-DD}_{tema_curto}.md` — mesmo padrão
dos 3 já existentes. Se houver dado extenso demais pro corpo principal,
`..._material_de_apoio.md` ao lado. **Pergunte antes de salvar** se não
foi pedido explicitamente "salva"/"arquiva" — rascunho pode ficar só na
resposta.

## Fase 5 — Quando o parecer voltar (o Manager cola a resposta externa)

Não é fase opcional nem automática — só roda quando o parecer chega.

1. **Leia o parecer inteiro antes de reagir a qualquer achado isolado** —
   mesmo padrão do parecer real (`docs/parecer_auditoria_externa_2026-08-20_
   ag114_ag118.md`): abre com "Veredito em uma página", achados numerados
   depois. Não pule pro achado #1 sem ler o veredito.
2. **Ceticismo é bidirecional — não aceite o parecer cegamente.** O parecer
   pediu ceticismo do revisor sobre o brief; aplique o mesmo padrão de
   volta: cada achado do parecer precisa de verificação contra código/dado
   real antes de virar `AG-NNN` (mesmo achado marcado **[verificar]** no
   próprio parecer é candidato a isso — o parecer real já demonstrou essa
   disciplina, marcando explicitamente onde a conclusão dependia de código
   não incluído).
3. **Cada achado real do parecer vira registro formal**, mesma disciplina
   do resto do projeto: `AG-NNN` novo se é gap de arquitetura/integração
   não catalogado antes; addendum a `AG-NNN` existente (nunca reescrita)
   se é achado novo sobre algo já registrado; decisão de arquitetura em
   `PLANO_MESTRE_PRINCE2.md` se muda o desenho ratificado.
4. **Nunca implementar a correção de um achado do parecer sem confirmação
   do Manager** — mesmo protocolo de qualquer achado de auditoria deste
   projeto (`redesign_workflow` Fase 3/4), o parecer é insumo pra decisão,
   não decisão em si, mesmo quando teoricamente correto.
5. Se o parecer revelar que o brief original tinha um erro de framing
   (não só um achado novo — ex. a métrica embutia a resposta por
   construção, caso real do `AG-122`), documente ISSO explicitamente
   como achado próprio, não só os achados derivados dele — é o tipo de
   coisa que `audit_engineering` chamaria de Classe #3/achado
   mecanístico central, vale o mesmo peso.

## Anti-patterns (recusar)

- "Resume rapidinho, sem as perguntas céticas" → recusa — sem tensão
  real, não é um brief de auditoria externa, é um resumo.
- Citar um número sem apontar o `experiments/*.json`/`constants.yaml`
  de origem → recusa, mesmo que o número esteja "na cabeça" de uma
  sessão anterior.
- Aceitar um achado do parecer e já implementar a correção no mesmo
  fôlego, sem checagem própria nem confirmação do Manager → recusa,
  mesmo que o achado pareça obviamente certo.
- Aceitar um achado do parecer e não registrar como AG-NNN "porque já
  foi discutido no chat" → recusa — se não está no ledger, não
  aconteceu, pro propósito deste projeto.

## Versionamento

```
v1.0 -- 2026-08-21 -- Criação. Porta a FORMA de `competitive-brief`
                       (Anthropic, fornecida pelo Manager) pro padrão
                       REAL já em uso neste projeto há 3 rodadas
                       (2 briefs + 1 material de apoio + 1 parecer real
                       recebido, achou 4 problemas reais não cobertos
                       pelas 12 perguntas originais). Fase 5
                       (processar o parecer) formalizada a partir do
                       que o parecer real de 2026-08-20 já demonstrou
                       (ceticismo bidirecional, achados [verificar]
                       marcados explicitamente).
```
