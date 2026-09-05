---
name: update-governance
description: Protocolo dos 7 documentos de governança do projeto. Use quando o usuário disser "atualize governança" ou "busque nos docs de governança" — duas faces do mesmo alvo, lista fixa definida pelo Manager (2026-08-17), substitui qualquer versão anterior.
---

# update-governance — Protocolo "atualize governança" / "busque nos docs de governança"

Escrever/atualizar usa os 7 itens abaixo; procurar informação usa os
mesmos 7, nenhum outro. Não é "reler tudo de memória" — é verificação
ativa, item por item, contra o código real quando aplicável. Protocolo
herdado do sweep de 2026-08-17 (`docs/roadmap_sweep_divergencias_2026-08-17.md`):
existe porque uma vez `§11.4` foi tratado como fonte completa sem checar
contra o PRD real (`AG-051`/`AG-052`).

1. **Commits** (`git log`) — o que realmente aconteceu desde a última
   atualização, ANTES de tocar em qualquer doc. Base factual pros outros
   6, não um dos 6.
2. **`PLANO_MESTRE_PRINCE2.md`** — documento INTEIRO, não só `§11.4-§11.6`
   (`§14`/`§15` também ficam desatualizados e passam batido se só a aba do
   roadmap for revisada — foi o furo que gerou `AG-080`).
3. **Road Map Vivo v2** (artefato publicado, link em `§14` do
   `PLANO_MESTRE_PRINCE2.md`) — republicar SE o item 2 mudou de forma
   material, **na mesma sessão, não depois**. O v1 ficou 5 dias sem sync
   apesar de se autodeclarar "vivo" (`AG-080`) — é o erro que este passo
   existe pra não repetir.
4. **`audit/architecture_gaps_log.yaml`** — todo achado novo vira `AG-NNN`
   (append-only; entrada fechada nunca se edita, só ganha `addendum_*`).
   Todo item fechado tem `resolved_by_commit`/`status` reais.
5. **`config/constants.yaml`** — toda constante nova com `provenance`
   declarada (ver `CLAUDE.md` §Proveniência).
6. **`audit/evidence_ledger.yaml`** — achado ESTATÍSTICO medido (M1-M6,
   comparação de candidatos) entra aqui; achado de ARQUITETURA/integração
   vai pro item 4 — são registros de natureza diferente, não duplicar.
7. **`docs/SPRINT_LOG.md`** — nova seção narrativa se algo mudou desde a
   última entrada; tabela "Estado atual" no fim, atualizada.

## Deliberadamente FORA desta lista (decisão do Manager, não esquecimento)

- **`audit/n_lifetime.yaml`** — **DESCONTINUADO como controle**
  (decisão do Manager, 2026-09-04, `AG-458`). Não é gate vinculante desde
  2026-08-17 (`AG-077`), não entra na varredura de rotina, e desde
  2026-09-04 não precisa mais ser consultado nem incrementado. O arquivo
  fica no repositório porque `src/analysis/faixa2_dsr_and_b2_check.py`
  ainda lê `::counter` — o valor está CONGELADO em 10.060, e quem for
  usar o DSR precisa saber que é um piso histórico, não uma contagem
  viva.
- **`PRD_V3_2_UNIFICADO.md`/`PRD_V4_1.md`** — categoria "blueprint
  técnico", não "governança". Só ganham correção pontual (ponteiro de 1
  linha, nota de proveniência) quando um achado contradiz o texto — nunca
  reescrita, e nunca como parte de rotina de "atualize governança".
- **Relatórios de sweep datados** (`docs/roadmap_sweep_divergencias_*.md`)
  — investigação pontual, não documento vivo; não se atualizam a cada
  rodada, só se cria um novo quando fizer sentido.
