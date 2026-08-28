# Notas de contexto — diretrizes de comportamento

Referenciado por `CLAUDE.md` §"Diretrizes de comportamento", regra
"correção pedida pelo Manager é o comportamento DEFAULT".

## Por que essa regra existe

Decisão do Manager, 2026-08-27, reverte uma convenção seguida
organicamente por sessões anteriores (nunca escrita até então): construir
a correção com `default=False`/comportamento antigo + flag pra ativar
(`enforce_r2`, `use_hyperparams_by_combo`, `run_b1_refinement` etc.),
exigindo uma SEGUNDA ordem do Manager só pra "ligar" o que ele já tinha
mandado corrigir.

Achado real que motivou a mudança: o Manager deu ordem direta de corrigir
6 itens numa sessão (2026-08-27, handoff de `src/models/`), Claude
reportou "corrigido" em cada um, e nenhum dos 6 estava de fato ativo em
produção — só disponível atrás de um parâmetro que ninguém tinha pedido
pra passar. Motor em fase de descoberta de edge, não produção estável com
usuário dependendo do comportamento antigo — mudar constantemente É o
trabalho, `default=legado` deixou de ser a régua de segurança padrão.

## Quando NÃO se aplica

- Não elimina teste real, proveniência declarada, nem nenhum item do
  Definition of Done — corrigir sem testar continua proibido.
- Não se aplica quando a MEDIÇÃO (não a falta de ordem) recomenda contra a
  mudança — ex. `tau_policy` não foi flipado porque `AG-251` mediu 2x de
  dispersão sob a política nova; isso é "discorde do Manager quando o
  dado discordar", não a mesma situação que esta regra corrige. A
  diferença: aqui o Manager NUNCA tinha sido informado de que a correção
  ficaria inerte; lá o Manager foi informado da medição contrária antes
  de qualquer decisão.
- Não se aplica a comparação lado-a-lado pedida explicitamente pelo
  próprio Manager (aí a flag existe porque foi pedida, não por cautela de
  quem implementou).
