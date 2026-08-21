# Stage Readiness Audit — `{cluster/estágio(s)}`

**Auditor:** Claude (skill `stage_readiness_audit` v1.0)
**Data:** YYYY-MM-DD HH:MM UTC
**Estágio(s) `§15.4`:** `{ex. 06_BARREIRAS, 07_LABEL, 07b_PESOS}`
**Pacote(s) real(is):** `{ex. src/labels/}`
**Âncora:** `{PLANO_MESTRE_PRINCE2.md §X / ADR-001 §Y / PRD §Z, se aplicável}`

## Executive Summary

- **Classificação real:** `{100% pronto | Parcial | Pendente/Proposto}`
- **Divergência doc-vs-código encontrada?** `{sim/não — se sim, é o achado #1}`
- **Total de achados (Lentes 1-4):** N — CRITICAL N / HIGH N / MEDIUM N / LOW N
- **Bloqueador que cascateia pra outro estágio?** `{sim (qual) / não}`
- **Rota recomendada (1 frase):** `{resumo da Lente 5}`

## Lentes 1-4 — Code Review (método: `audit_engineering`)

### Scripts mecânicos rodados

| Script | Resultado |
|---|---|
| `banned_patterns.py --strict` | {N violações, ou limpo} |
| `check_constants_referenced.py` | {N referências sem entrada, ou limpo} |
| `check_unguarded_ratios.py` | {N não-guardadas, ou limpo} |
| `ruff check` | {N erros, ou limpo} |
| `mypy` | {N erros, ou limpo} |

### Achados (ordenados por severidade)

#### F1 — {Título curto} [SEVERIDADE] [PRIORIDADE]

**Lente:** FS / FI / FT / FCN
**Localização:** `{arquivo}:{linha}`

**Descrição:** {explicação técnica clara, evidência real}

**Por que é problema:** {conexão com CLAUDE.md/PLANO_MESTRE/achado histórico}

**Recomendação de correção:** {direção concreta}

---

#### F2 — ...

## Lente 5 — System Design / Rota pra Produção

### 1. Requisito real

{O que este estágio precisa fazer — âncora exata (§X.Y de qual
documento). Se não há âncora nenhuma, isso É o achado.}

### 2. Desenho atual (verificado, não presumido)

{Componentes reais (`arquivo:função`), fluxo de dado entre eles,
contrato real entre os arquivos do estágio — confirmado por leitura
direta, não por citação de doc.}

### 3. Gap arquitetural

{Onde o desenho diverge do requisito, na escala de DESENHO — cobertura
incompleta (símbolo/resolução), acoplamento indevido, ausência de
sentinela `NOT_COMPUTABLE`, decisão de escopo nunca formalizada.}

### 4. Escala/confiabilidade

{Aguenta os 5 símbolos × 3 resoluções de verdade (testado)? Falha
graciosamente ou quebra/mente quando algo não está pronto?}

### 5. Trade-off e rota recomendada

| passo | ação concreta | desbloqueia | trade-off |
|---|---|---|---|
| 1 | {arquivo/função/decisão específica} | {o quê} | {custo vs. risco de deixar aberto} |
| 2 | ... | ... | ... |

## O que falta pra 100%

{Lista curta e objetiva, cada item acionável — não genérico.}

## Perguntas que exigem decisão do Manager (não decididas aqui)

{Se houver — mesmo padrão de `redesign_workflow` Fase 3, nunca decidir
escopo/trade-off de negócio sozinho.}

## Registro sugerido

- [ ] `AG-NNN` novo? {gap de arquitetura/integração genuinamente novo}
- [ ] `AG-NNN` existente muda de estado? {qual, `addendum_*`/`status_*` sugerido}
- [ ] Correção de prosa desatualizada em `PLANO_MESTRE_PRINCE2.md §15.4`/Road Map Vivo v2? {qual trecho, o que deveria dizer}

## Metadados

- Lentes aplicadas: FS ✓ FI ✓ FT ✓ FCN ✓ SD (System Design) ✓
- Scripts mecânicos rodados: ✓
- Divergência doc-vs-código checada explicitamente: ✓
