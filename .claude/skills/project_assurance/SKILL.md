# project_assurance — Revisão independente obrigatória (Project Assurance, PRINCE2 §6.4)

## Proveniência

Esta skill operacionaliza `PLANO_MESTRE_PRINCE2.md` §6.4 ("Revisão independente —
obrigatória, não por escolha"). Nasceu do achado AG-001
(`audit/architecture_gaps_log.yaml`): `src/labels/triple_barrier.py` chamou
`group_c.c01_atr_20` direto por dias, em vez de consumir a interface
`VolatilityEstimator` (T0.1) já pronta — e isso só apareceu porque o Manager
perguntou, não porque o processo obrigava a pergunta. **O produtor de um
artefato não pode ser o revisor independente do próprio artefato** — é o
mesmo princípio por trás de Quality Review Technique (PRINCE2) e de
"effective challenge" (SR 26-2 — ver §3 abaixo). Um segundo `Agent`, invocado
numa sessão fresca sem o contexto de por que a primeira implementação foi
feita daquele jeito, é a forma barata de ter isso com apenas 2 pessoas no
projeto.

**Diferença de `audit_engineering`:** aquela skill audita QUALIDADE de código
(lentes FS/FI/FT/FCN, achados de correção/vazamento/robustez). Esta skill
audita INTEGRAÇÃO — "o que foi construído está de fato conectado ao que
deveria consumir, ou é uma interface órfã que parece pronta mas não é
usada?". `project_assurance` invoca `audit_engineering` como MÉTODO de
verificação de qualidade (Passo 3 abaixo), mas o objeto da pergunta é
diferente: não "este código está correto", e sim "este código está
mentindo, por omissão, sobre o quanto do sistema real ele toca".

## Quando usar

Invocar **sempre** que um Pacote de Trabalho (PLANO_MESTRE_PRINCE2.md §6.1)
terminar: arquivo expõe interface/abstração nova, é consumido por mais de um
módulo, OU vive em `src/labels/`, `src/risk/`, `src/execution/`,
`src/regime/`. Ver §4 abaixo para o critério de materialidade completo
(adaptado de SR 26-2, mais afiado que a heurística original do §6.1).

Não usar para: scripts de análise de uso único, ajuste de docstring sem
mudança de comportamento, correção de teste sem mudança de produção — mesmas
exclusões do §6.1.

## Passo 1 — Descrição de Produto (entrada obrigatória, não opcional)

O invocador (eu, na sessão principal) chega com o template do §6.2 já
preenchido:

```
ARQUIVO: <caminho>
PROPÓSITO: <uma frase>
CONSUMIDORES REAIS HOJE: <caminho:linha, ou "nenhum ainda">
CONSUMIDORES PRETENDIDOS: <segundo PRD/design>
GAP CONHECIDO: <se real != pretendido, dito explicitamente>
CRITÉRIOS DE QUALIDADE: <lente(s) audit_engineering aplicável>
MÉTODO DE VERIFICAÇÃO: <golden test? paridade? integração ponta a ponta?>
```

Sem isso preenchido, a skill não roda — não é o revisor quem inventa o
propósito do arquivo, é quem o escreveu quem declara, e o revisor
confere/refuta.

## Passo 2 — Invocar o Agent independente

```
Agent({
  description: "Project Assurance -- <arquivo>",
  subagent_type: "general-purpose",
  prompt: <ver template abaixo>
})
```

**Regras da invocação, sem exceção:**

- O agente recebe a Descrição de Produto (Passo 1), o diff real (`git diff`
  ou caminho completo do arquivo + dos arquivos consumidores citados), e as
  perguntas do Passo 3 — **nunca** o raciocínio de por que a implementação
  foi feita daquele jeito. Contexto de justificativa contamina a
  independência; se o agente já "entende por que", ele para de procurar o
  que está errado.
- O agente é instruído a **não confiar em nenhuma afirmação do docstring/
  commit message sobre quem consome o quê** — re-derivar via Grep próprio.
  Um docstring que diz "consumido por X" é uma alegação do produtor, não um
  fato verificado.
- **O agente NUNCA executa `.py`/`pytest`/`uv run` via Bash** — mesma regra
  de `CLAUDE.md` ("Protocolo de execução"), sem exceção mesmo estando numa
  sessão separada. Se uma verificação mecânica (`ruff`, `mypy`,
  `banned_patterns.py`, `pytest`) for necessária, o agente formula o comando
  exato e devolve como PENDENTE-DE-EXECUÇÃO-HUMANA no relatório, nunca roda
  sozinho. *(Nota: `audit_engineering` v1.0 Passo 4, escrito em
  2026-08-09, um dia antes deste protocolo existir em CLAUDE.md v1.2
  [2026-08-10], ainda instruía "rodar" os scripts diretamente — corrigido
  nesta sessão, ver `audit/architecture_gaps_log.yaml` AG-002.)*

### Template do prompt

```
Você é um revisor de Project Assurance independente (PRINCE2 §6.4,
projeto BTCUSDT Quant Engine). NÃO escreveu o código abaixo e não tem
acesso ao raciocínio de quem escreveu -- isso é intencional. Sua função é
achar o que o produtor não viu, não confirmar o que ele já disse.

DESCRIÇÃO DE PRODUTO DECLARADA PELO PRODUTOR:
<colar Passo 1>

ARQUIVO(S) EM REVISÃO:
<conteúdo completo ou diff>

CONSUMIDORES CITADOS COMO REAIS -- verifique cada um com Grep, não assuma:
<lista>

Responda às 16 perguntas da seção "Checklist" abaixo, em ordem, cada uma
com resposta honesta -- "não verificável sem rodar X" é resposta válida,
"provavelmente está tudo bem" não é. Para cada resposta que revele um
gap real, classifique severidade (CRITICAL/HIGH/MEDIUM/LOW, escala de
audit_engineering) e escreva a entrada pronta para
audit/architecture_gaps_log.yaml (schema: id, date, file, found_by,
gap, severity, layer, consequence, status).

Você NUNCA executa .py/pytest/uv run. Se precisar de verificação
mecânica, formule o comando exato e marque PENDENTE-DE-EXECUÇÃO-HUMANA.
```

## Passo 3 — Checklist (16 perguntas, 3 blocos)

Os 5 originais (§6.3 do PLANO_MESTRE) mais 11 novos, organizados nos 3
pilares que SR 26-2 (Fed/OCC/FDIC, guidance revisada de gestão de risco de
modelo, abril/2026) usa para estruturar validação de modelo — citado aqui
como **referência de estrutura, não como framework adotado**: este projeto
não é um banco, não tem board, não é supervisionado; o que se aproveita é a
TAXONOMIA (3 blocos de pergunta), não a burocracia bancária. [Fonte: SR
26-2, Federal Reserve](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm).

### Bloco A — Solidez conceitual (o design está certo, antes de perguntar se a execução está certa)

1. Quem no pipeline de PRODUÇÃO consome isto de verdade? (caminho:linha, não "deveria")
2. Se este arquivo fosse apagado hoje, o que quebraria DE VERDADE?
3. Existe caminho paralelo mais antigo fazendo a mesma coisa, podendo divergir silenciosamente?
4. O TODO/"trabalho subsequente" citado no próprio docstring já foi fechado, ou está adiado permanentemente sem prazo?
5. Que teste PROVARIA a integração real, não só a unidade isolada?
6. Cada afirmação factual do docstring/commit ("consumido por X", "medido", "confirmado") foi re-verificada por Grep próprio, ou é herdada da palavra do produtor sem checagem?
7. O que foi entregue bate com a Descrição de Produto declarada — nem mais, nem menos escopo (scope-fidelity)? Escopo extra não pedido é tão suspeito quanto escopo faltando.
8. Toda constante nova tem entrada em `constants.yaml` com `provenance` SEMANTICAMENTE correta (marcada `MEASURED` de fato foi medida, não só rotulada)?

### Bloco B — Análise de resultado (o que foi construído realmente prova o que afirma provar)

9. Os testes novos provam integração real, ou reproduzem a própria implementação (ground truth circular — o teste deriva do mesmo código que testa)?
10. Existe caso de borda que o autor não tentou construir ATIVAMENTE para este código específico (NaN/Inf/vazio/n=1/duplicata/warmup insuficiente), não só herdado de outro teste do arquivo?
11. A mesma classe de bug corrigida aqui já existe em outro lugar do repo? (varredura ativa por grep do padrão, não assumir isolado — a classe #1 do `audit_engineering` reapareceu de forma independente em Sprint 12 depois de corrigida em Sprint 8; isso não é hipotético)
12. Alguma tolerância de teste foi alargada (ex. `abs=`, `rel=`) para o teste passar, sem o gap subjacente estar de fato reconciliado — e isso está documentado como gap aberto ou como se fosse normal?

### Bloco C — Monitoramento/integridade estrutural (o que isso quebra silenciosamente daqui pra frente)

13. A mudança altera o significado de um artefato JÁ PERSISTIDO (schema, `config_hash`, formato Parquet) sem versionamento/nota de migração?
14. Handling de exceção novo é silencioso (`except: pass`, `except Exception:` sem `raise`) onde a invariante quebrada deveria parar o pipeline?
15. Escrita de I/O nova é atômica em TODO caminho, incluindo o de exceção (`.tmp`→`fsync`→`rename`, B29)?
16. Alguma seção de `PRD_V4_1.md`/`CLAUDE.md`/outro doc agora contradiz este arquivo, e ninguém atualizou o texto?

## Passo 4 — Critério de materialidade (adaptado de SR 26-2, substitui a heurística simples do §6.1)

SR 26-2 dimensiona rigor de validação por 4 eixos: exposição financeira,
peso da decisão, complexidade, e contexto de uso ("pode ser mal aplicado?").
Adaptado a 1 desenvolvedor + capital de R$ 1.000:

| eixo | pergunta | materialidade ALTA se... |
|---|---|---|
| exposição financeira | este código participa do dimensionamento de posição/preço real? | sim, direto (`sizing.py`, `triple_barrier.py`, `execution/`) |
| peso da decisão | uma predição/número daqui decide entrar/sair de trade, ou é só diagnóstico? | decide, não só descreve |
| complexidade | tem lógica condicional não-trivial, estado, ou é fórmula pura de 1 linha? | condicional/estado real, não wrapper fino |
| contexto de uso | pode ser chamado com um parâmetro errado sem erro óbvio (ex. `estimator_id` divergente, unidade trocada bps↔fração)? | sim |

**Materialidade ALTA em ≥2 eixos → protocolo completo (16 perguntas)
obrigatório.** 1 eixo ou nenhum → registro leve: só as perguntas 1, 2 e 13
(existe consumidor real, o que quebra se sumir, quebra algo persistido),
sem Agent dedicado — pode ser feito inline pelo produtor mesmo, com o
achado registrado se houver.

## Passo 5 — Output

O Agent devolve achados no formato de `audit_report_template.md`
(`audit_engineering`), mas o destino do achado depende da NATUREZA, não é
sempre `architecture_gaps_log.yaml`:

- Gap de integração/arquitetura (interface órfã, caminho paralelo, escopo
  divergente, artefato persistido invalidado silenciosamente) →
  `audit/architecture_gaps_log.yaml`, `found_by: "Agent Project Assurance,
  <arquivo>"`.
- Gap de correção estatística/vazamento (lentes FS clássicas) →
  segue o fluxo normal de `audit_engineering` (`audit/code_reviews/`).
- Gap que revela decisão de ESCOPO/NEGÓCIO não tomada (ex. "GK devia ser
  canônico?") → não é fechado pelo Agent nem por mim — escalona pro Manager
  per PLANO_MESTRE_PRINCE2.md §6.5, registrado como `status: "aberto —
  aguarda decisão do Manager"`.

## Anti-patterns (recusar)

- Rodar a revisão na MESMA sessão/contexto de quem implementou → não é
  independente, é o produtor relendo o próprio texto. Sempre `Agent` fresco.
- Passar o "porquê" da implementação no prompt do Agent → contamina a busca
  por pontos cegos.
- Aceitar "código parece bem estruturado" como resposta a uma das 16
  perguntas → cada pergunta exige verificação (Grep, leitura do
  consumidor real), não impressão geral.
- Pular perguntas do Bloco C porque "é só um arquivo pequeno" → o tamanho
  do arquivo não prevê o raio de explosão de um schema/hash silenciosamente
  invalidado.

## Fontes

- [SR 26-2 — Revised Guidance on Model Risk Management, Federal Reserve/OCC/FDIC, abril/2026](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm)
- [Domino.ai — SR 26-2 explicado, estrutura de 3 pilares de validação](https://domino.ai/data-science-dictionary/sr-26-2)
- `PLANO_MESTRE_PRINCE2.md` §6 (protocolo de origem)
- `.claude/skills/audit_engineering/SKILL.md` (método de qualidade reusado no Passo 2/3)

## Versionamento

```
v1.0 -- 2026-08-12 -- Criação. Opera PLANO_MESTRE_PRINCE2.md §6.4. 5
                       Perguntas de Integração originais + 11 novas
                       (Blocos B/C), organizadas segundo a taxonomia de 3
                       pilares de SR 26-2 (referência de estrutura, não
                       adoção de framework bancário). Critério de
                       materialidade do §6.1 do PLANO_MESTRE substituído
                       por versão de 4 eixos adaptada de SR 26-2 §4.
```
