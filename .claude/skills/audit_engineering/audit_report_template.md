# Audit Report — `{filepath}`

**Auditor:** Claude (skill `audit_engineering` v1.0)
**Data:** YYYY-MM-DD HH:MM UTC
**Âncora PRD:** §X.Y (se aplicável)

## Executive Summary

- **Total de achados:** N
- **CRITICAL:** N (P0 — bloqueia)
- **HIGH:** N (P1 — corrige antes de promover o módulo)
- **MEDIUM:** N (P2 — próxima iteração)
- **LOW:** N (P3 — backlog)
- **Banned patterns violados:** {lista de IDs B01-B32} ou "nenhum"
- **Recomendação:** {APROVADO | APROVADO_COM_RESSALVAS | RETRABALHO_NECESSARIO | REJEITADO}

## Pesquisa web realizada (Passo 2)

Queries:
- "{query 1}"
- "{query 2}"

Achados: {resumo, ou "nenhuma atualização relevante encontrada"}

## Scripts mecânicos rodados (Passo 4)

| Script | Resultado |
|---|---|
| `banned_patterns.py --strict` | {N violações, ou limpo} |
| `check_constants_referenced.py` | {N referências sem entrada, ou limpo} |
| `check_unguarded_ratios.py` | {N não-guardadas, ou limpo} |
| `ruff check` | {N erros, ou limpo} |
| `mypy` | {N erros, ou limpo} |

## Achados (ordenados por severidade)

### F1 — {Título curto} [SEVERIDADE] [PRIORIDADE]

**Lente:** FS / FI / FT / FCN
**Classe conhecida?** {uma das 6 classes já catalogadas na skill, ou "nova"}
**Banned pattern:** {#Bnn se aplicável, ou "n/a"}
**Localização:** `{arquivo}:{linha}`

**Descrição:** {explicação técnica clara}

**Evidência:**
```python
{trecho de código}
```

**Por que é problema:** {conexão com princípio do CLAUDE.md, achado histórico
desta investigação, ou risco operacional concreto}

**Recomendação de correção:** {direção concreta, código alternativo se aplicável}

**Trade-offs da correção:** {se houver}

---

### F2 — ...

## Cross-checks

- [ ] CLAUDE.md banned patterns: {N verificados, IDs violados listados}
- [ ] `audit/division_guard_audit.md`: {já cobria este arquivo? situação mudou?}
- [ ] `docs/audit_discarded_diagnostics.md`: {candidato novo encontrado?}
- [ ] `config/constants.yaml`: {toda constante nova tem proveniência?}
- [ ] PRD §X.Y: {alinhamento, se aplicável}

## Candidato a escalonamento?

{Novo banned pattern candidato? Novo script mecânico candidato? Refator
estrutural necessário? Ver seção "Escalonamento" da skill.}

## Próximos passos

1. {ação concreta 1}
2. {ação concreta 2}

## Metadados da auditoria

- Lentes aplicadas: FS ✓ FI ✓ FT ✓ FCN ✓
- Pesquisa web realizada: ✓
- Scripts mecânicos rodados: ✓
- Cross-checks realizados: ✓
- Tempo de auditoria: {minutos}
