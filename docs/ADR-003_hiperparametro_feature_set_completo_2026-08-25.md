# ADR-003: Busca de hiperparâmetro para o feature-set T2 completo (62 features), rollout obrigatório de produção

**Status:** Executada ponta a ponta (Estágios 0-3, 10 combos) — ver `## Resultado` no fim. Ressalva crítica sobre a validade do gate de permanência (`AG-220`) descoberta em sessão paralela durante a execução — não invalida a calibração de hiperparâmetro, mas invalida a leitura do pass/fail do Estágio 3 como sinal.
**Date:** 2026-08-25
**Deciders:** Manager (Felipe)

## Context

`AG-207` (`audit/architecture_gaps_log.yaml`) — Manager ratificou por
escrito, 2026-08-25, a promoção mandatória de T2→T1 pra produção,
reconhecendo explicitamente a violação de R4 (`PLANO_MESTRE_PRINCE2.md`
§0.2: "teto de features = medido, nunca estipulado") e o fato de a única
evidência medida (Fase 0→1→2→confirmação→ADR-002, `n_lifetime.yaml` ids
20-27, 192 trials) apontar na direção oposta — T2 nunca bateu T1 em
nenhuma configuração testada em ETHUSDT/R1. Registrado como decisão de
NEGÓCIO explícita (`n_lifetime.yaml` id=28, `budget_override_manager`),
não como conclusão suportada por dado.

**Correção de entendimento, 2026-08-25 — importante**: a campanha
Fase 1/Fase 2/ADR-002 inteira testou `feature_ids` como os `k` candidatos
T2 **SUBSTITUINDO** os 7 `T1_FEATURE_IDS` no vetor de treino, nunca
somando (`src/models/alpha.py::build_design_matrix`/`run_all_folds`,
docstring: "vetor de k features candidatas **em vez do** T1 fixo";
`src/analysis/t2_ranking_ortogonalidade.py::build_k_feature_sets` nunca
inclui `T1_FEATURE_IDS` na lista ranqueada). O artefato "Alpha — Base de
Pesquisa" (H7) tinha uma legenda errada ("k = nº features T2 além das 7
T1") — corrigida nesta mesma sessão. Isso muda o que "62 completos"
significa: **62, não 69** — os 62 `SUPPORT_FEATURE_IDS` substituindo os 7
`T1_FEATURE_IDS`, mantendo a MESMA convenção usada em toda a campanha já
medida (comparável, não uma convenção nova).

**Escopo definitivo** (Manager, 2026-08-25):
- Feature set: todos os 62 `SUPPORT_FEATURE_IDS` (substituindo os 7 T1,
  convenção herdada — ver correção acima). Nunca testado nesta campanha
  (maior `k` testado até aqui: 39).
- Bancada de validação: as **10 piores combinações símbolo×resolução**
  por `ret_net` médio, dentre as 12 que falharam o gate de permanência no
  sweep original de 15 (`n_lifetime.yaml` id=18, `evidence_ledger.yaml::
  alpha-lightgbm-sweep-15-combinacoes-2026-08-23`) — excluídas as 3 que já
  passam (ETHUSDT/R1, SOLUSDT/R2, SOLUSDT/R3).
  Medido agora, 0 trials novos, a partir de `experiments/
  alpha_deep_analysis_2026-08-24.json::{i}.decomposition.pnl_total.value /
  n_trades` (mesmo dado já persistido do H0/H1/H2 do dia anterior):

  | rank (pior→menos pior) | símbolo | resolução | ret_net médio | sharpe (Camada1) |
  |---|---|---|---|---|
  | 1 | BTCUSDT | R3 | -0,0032 | -2,886 |
  | 2 | BNBUSDT | R3 | -0,0020 | -3,105 |
  | 3 | SOLUSDT | R1 | -0,0019 | -5,346 |
  | 4 | BTCUSDT | R2 | -0,0019 | -5,505 |
  | 5 | BNBUSDT | R2 | -0,0016 | -4,571 |
  | 6 | BNBUSDT | R1 | -0,0015 | -7,958 |
  | 7 | XRPUSDT | R1 | -0,0013 | -3,749 |
  | 8 | ETHUSDT | R3 | -0,0013 | -1,603 |
  | 9 | BTCUSDT | R1 | -0,0012 | -5,816 |
  | 10 | ETHUSDT | R2 | -0,0012 | -2,453 |

  Fora da lista (menos ruins dentre os 12 que falham, não selecionadas):
  XRPUSDT/R2 (-0,0010), XRPUSDT/R3 (-0,0010).

- Objetivo mudou: não é mais decidir SE T2 tem valor (já decidido,
  mandatório) — é achar os melhores hiperparâmetros LightGBM pra esse
  feature-set fixo de 62, nesses 10 casos.

**Lições da campanha anterior que este desenho preserva**: nunca
selecionar por argmax de 1 seed (winner's-curse medido repetidamente,
maior caso: +0,772 em unidades de Sharpe); mediana de top-K, não top-1;
`k=62` é território não calibrado — `k` maior historicamente favoreceu
menos complexidade de árvore e `min_child_samples` maior, mas isso foi
medido só até `k=39`, não pode ser presumido em `k=62` (B23).

## Decision

4 estágios — um Estágio 0 novo que não existia no ADR-002, pra evitar
redescobrir a mesma estrutura 10 vezes de forma cega e cara.

### Estágio 0 — sondagem de estrutura (2 combos representativos, 1 seed)

`src/validation/t2_t1_full_feature_stage0_probe.py` — grid pequeno
(`max_depth`×`num_leaves` ∈ {(2,2),(2,3),(3,3)}, mesma região que a Fase 2
já estabeleceu como mais promissora até k=39; `min_child_samples` ∈
{20(PROD), 500, 1000, 2000}, os 2 últimos NOVOS, estendendo a sondagem já
que k=62 é ~1,6x maior que qualquer coisa testada) = 12 combinações × 2
combos (BTCUSDT/R3, o pior; XRPUSDT/R1, o 7º de 10 — representativo do
meio) = **24 trials**.

Critério de decisão pro Estágio 1: se os 2 combos concordarem na direção
geral (mesmo sinal de "menor complexidade/maior mcs vence"), Estágio 1
usa grid ESTREITO (~6-8 pontos) nos outros 8 combos. Se DIVERGIREM,
Estágio 1 usa grid cheio (~12 pontos) em todos os 10 — mais caro, mas
honesto sobre a incerteza medida aqui, não presumido.

### Estágio 1 — screening por combo (coordenada-descendente, 1 seed)

Pra cada um dos 10 combos: grid de `(max_depth, num_leaves,
min_child_samples)` (estreito ou cheio, decidido pelo Estágio 0) +
coordenada-descendente sobre os 5 hiperparâmetros do ADR-002
(`learning_rate`/`subsample`/`feature_fraction`/`lambda_l2`/
`n_estimators`), ancorado no melhor ponto do grid próprio de cada combo
(não reusa a âncora de ETHUSDT/R1 do ADR-002 — k mudou de 32→62, âncora
antiga não se aplica). Estimativa: 6-12 (grid) + 13 (coordenada-
descendente, mesma estrutura do ADR-002 Estágio 1b) ≈ **19-25
trials/combo × 10 = 190-250 trials**.

### Estágio 2 — confirmação (top-3 por combo, mediana de 5 seeds)

Top-3 (não top-5 do ADR-002 original — orçamento controlado dado o
multiplicador ×10) candidatos de cada combo, cada um confirmado com 5
seeds, seleção pela MEDIANA — nunca argmax. 3×4 seeds novos (1 seed
reusa o screening) = **12 trials/combo × 10 = 120 trials**.

### Estágio 3 — gate de permanência repetido (vencedor por combo, 5 seeds)

Vencedor do Estágio 2 de cada combo, gate de permanência real (Camada1 vs
Camada0) repetido 5 seeds, critério = mediana de `n_better`. **5
trials/combo × 10 = 50 trials**.

### Orçamento total

| estágio | trials |
|---|---|
| 0 — sondagem (2 combos) | 24 |
| 1 — screening (10 combos) | 190-250 |
| 2 — confirmação (10 combos) | 120 |
| 3 — permanência (10 combos) | 50 |
| **total** | **~384-444** |

`N_lifetime` 288 → ~672-732 depois desta campanha inteira (contador
auditado, não gate vinculante desde `AG-077`, mas DSR real o lê).

Tempo estimado: `k=62` (~1,6x o maior `k` já medido, `k=39`) deve treinar
mais devagar que `k=32` — sem medição própria ainda (B23). O Estágio 0
mede `elapsed_seconds` real antes de qualquer projeção de tempo total pros
Estágios 1-3 — não estimado aqui pra não inventar faixa (B23).

## Options Considered

### Option A: 4 estágios com sondagem prévia (Estágio 0) — ESCOLHIDA

Ver `## Decision` acima. Reduz o risco de rodar grid cheio 10× às cegas
quando 2 sondagens baratas já respondem a pergunta estrutural.

### Option B: Reusar direto os hiperparâmetros calibrados do ADR-002 (k=32) em k=62, sem nova sondagem

**Pros**: zero custo de Estágio 0/1 — vai direto pra confirmação (Estágio
2) com o vencedor do ADR-002 (`learning_rate=0,01, n_estimators=300,
max_depth=2, num_leaves=3, min_child_samples=500`) aplicado a `k=62`.
**Cons**: `k=62` é quase 2x `k=32` — presumir que a mesma calibração vale
é exatamente o tipo de extrapolação sem medição que o projeto já payou
caro por evitar (Fase 1→Fase 2 já mostrou que "k maior sempre melhor" NÃO
generalizava de k≤24 pra k=32; não há razão pra assumir k=32→k=62
generaliza sem checar). Rejeitada — barato demais pra confiança que a
decisão de produção mandatória exige.

### Option C: Grid completo (sem Estágio 0) em todos os 10 combos desde o início

**Pros**: mais robusto individualmente por combo, sem depender de 2
combos representativos generalizarem pros outros 8.
**Cons**: ~12 pontos de grid × 10 combos = 120 trials só de estrutura,
antes até de tocar nos 5 hiperparâmetros novos — sem saber se um grid
ESTREITO já bastaria. Rejeitada por custo, mas é o fallback automático se
o Estágio 0 mostrar divergência entre os 2 combos (ver critério de
decisão acima).

## Trade-off Analysis

A pergunta central é a mesma do ADR-002: barato o bastante pra rodar
agora, honesto o bastante pra não estipular uma calibração sem medir.
Diferente do ADR-002 (1 combo, ETHUSDT/R1), aqui são 10 — o custo
marginal de uma sondagem errada multiplica por 10, o que justifica gastar
24 trials baratos (Estágio 0) pra decidir se o Estágio 1 pode ser mais
barato (grid estreito) ou precisa ser caro (grid cheio) por combo.

## Consequences

- **Fica mais fácil**: decidir o grid do Estágio 1 com base em medição
  real de `k=62`, não em extrapolação de `k≤39`.
- **Fica mais difícil**: esta é a maior campanha de trials desta sessão
  (~384-444, vs. 192 da campanha T2→T1 original inteira) — vários
  comandos reais que o Manager precisa rodar e colar o output (protocolo
  de execução do projeto), não fire-and-forget.
- **Precisa ser revisitado**: se o Estágio 0 mostrar padrão muito
  diferente do esperado (ex. `k=62` favorece MAIS complexidade, não
  menos), o grid do Estágio 1 pode precisar ser redesenhado antes de
  rodar nos 10 combos — reportado antes de prosseguir, não estourado
  silenciosamente.
- Diferente do ADR-002: aqui não há mais pergunta de "T2 tem valor?" — a
  promoção já é mandatória (`AG-207`). O gate de permanência do Estágio 3
  segue rodando (é a métrica de produção real), mas seu resultado NÃO
  decide se a promoção acontece — só informa a calibração final de
  hiperparâmetro por combo. Se o gate falhar mesmo assim (como falhou em
  ETHUSDT/R1 até aqui), a promoção ocorre do mesmo jeito, por decisão de
  negócio já ratificada.

## Action Items

1. [x] Corrigir o artefato "Alpha — Base de Pesquisa" (legenda "k = T2
   além dos 7 T1" estava errada — é substituição, não soma).
2. [x] Implementar Estágio 0 (`t2_t1_full_feature_stage0_probe.py`) — lint
   limpo (ruff/banned_patterns), pronto pra rodar.
3. [x] Rodar Estágio 0 nos 2 combos representativos (BTCUSDT/R3,
   XRPUSDT/R1) — DIVERGIRAM (ver `## Resultado`).
4. [x] Decidir grid estreito vs. cheio do Estágio 1 — divergência ⇒ grid
   cheio nos 10 combos, regra pré-declarada aplicada.
5. [x] Implementar e rodar Estágios 1-3 nos 10 combos.
6. [x] Registrado em `audit/n_lifetime.yaml` por estágio (ids 29-31,
   counter 288→751).

## Resultado (2026-08-25)

**Estágio 0** (24+3 trials, 2 combos): estrutura DIVERGIU — BTCUSDT/R3
prefere `num_leaves=2`/`min_child_samples=500` (formato em U); XRPUSDT/R1
prefere `num_leaves=3`/`min_child_samples` alto, ainda melhorando na
borda testada (2000) — extensão a 3000/4000/6000 mostrou variação da
ordem do ruído de 1 seed (spread ~0,43 vs. σ≈0,3 medido na Fase 0a),
teto do grid mantido em 2000 por decisão medida.

**Estágio 1** (293 trials, grid completo + 6 hiperparâmetros por combo):
`max_depth=2` vence nos 10/10 sem exceção. `min_sum_hessian_in_leaf`
(AG-217) **bit-idêntico ao PROD nos 10/10** — hipótese não confirmada.
`feature_fraction<1,0` **piorou em 9/10** — também contraria AG-217.
Melhor screening por combo: -0,0345 (BTCUSDT/R3) a -2,8404 (BTCUSDT/R1).

**Estágio 2** (120 trials, mediana de 5 seeds): winner's-curse mais
extremo da campanha — o candidato de melhor screening de BTCUSDT/R3
caiu de -0,0345 para -0,6476 sob mediana (viés +0,513). Nenhuma das 10
medianas é positiva; melhor = BNBUSDT/R3 (-0,1463).

**Estágio 3** (50 trials, gate de permanência × 5 seeds): 1 de 10 passa
nominalmente (BNBUSDT/R1, mediana 4/5); os outros 9 ficam entre 1 e 3.

**Ressalva crítica, descoberta durante a execução (não pelo ADR-003 em
si) — `AG-220`/`AG-220-ADDENDUM`**: uma sessão paralela mediu, em 3
experimentos pareados reais sobre BTCUSDT/R1 (k=7), o MESMO gate de
permanência (mesma config de produção, `tau_policy=legacy_per_side`)
oscilando FALSE→TRUE→FALSE só por calibração de threshold, com
`|delta(Camada1,Camada0)| < sigma` nas 3 variantes — o gate lê ruído da
variância de path do CPCV, não sinal, pelo menos sob k=7. O mecanismo é
estrutural (5 paths não-independentes), não específico do feature-set —
a expectativa é que o resultado do Estágio 3 acima (inclusive o "1 de
10 passa") esteja igualmente dentro do ruído, mas isso é inferência por
analogia, não medido diretamente aqui (não persistimos σ/dispersão por
path no Estágio 3, só `n_better` por seed — lacuna pra fechar antes de
qualquer leitura forte do resultado).

**Consequência prática**: a decisão de negócio (`AG-207`) já manda
promover T2 independente deste resultado — o valor real desta campanha
é a CALIBRAÇÃO de hiperparâmetro por combo (Estágios 1-2), não a
decisão de promover. Recomendação: usar o vencedor do Estágio 2 (mediana
de 5 seeds, não o screening de 1 seed) como hiperparâmetro de produção
por combo, e tratar qualquer leitura do Estágio 3 como não-confiável até
`AG-220` ser resolvido (ADR-004) ou σ/dispersão ser medido para os 10
combos especificamente. Detalhe completo:
`audit/evidence_ledger.yaml::adr003-k62-10-piores-combinacoes-veredito-2026-08-25`.
