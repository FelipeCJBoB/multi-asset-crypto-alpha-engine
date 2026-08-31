# ADR-007: Arquitetura de medição de hiperparâmetro em produção — 15 combos, gate duplo, guardrails contra falso-positivo

**Status:** Item 1 concluído 2026-08-30 (1.800/1.800 trials, 0 falhas, 2h32m18s) — Item 2 concluído 2026-08-31 (720/720 confirmações, 0 falhas, 1h00m51s — **ZERO dos 6 combos passam o gate duplo**; `BTCUSDT/R3`, único combo que passava sob H10, não sobrevive ao orçamento maior) — Item 4 concluído (FDR aplicado à taxa-base H0-H7) — Item 3 em preparação, Item 5 aguarda Item 3 (ver Action Items)
**Date:** 2026-08-30
**Deciders:** Manager (Felipe)

## Context

`AG-382`/`AG-383` fecharam a primeira campanha Optuna real do projeto: 900
trials de busca (15 combos × 2 camadas × 30 trials/study) + 450 retreinos
de confirmação multi-seed (Sharpe) + 450 retreinos de recampanha sob gate
duplo (Sharpe + edge bruto, `AG-383`-addendum) + 75 retreinos de
diagnóstico (win rate + ranking de gain, id=37). Resultado real, sob o
vetor oficial de 36 features (`T1_FEATURE_IDS`, `AG-372`) e o gate duplo:
**1 de 15 combos** (`BTCUSDT/R3`) sobrevive aos dois testes (Sharpe
relativo `n_better≥4/5` E edge bruto absoluto `>0bps` com cobertura
`≥30` trades).

**Achado novo, mesma sessão**: olhando os 15 resultados junto (H10/H11 do
artefato "Alpha — Base de Pesquisa"), dois padrões se repetem de forma
consistente o bastante pra merecer ação:

- **`BNBUSDT`** tem edge bruto negativo nas 3 resoluções, sem exceção
  (-5,37 / -4,63 / -6,52 bps), e o win rate mais perto de 50% (cluster
  mais apertado, 50,21-50,45%) de qualquer símbolo — sinal de ausência de
  skill real, não uma resolução isolada ruim.
- **Resolução `R1`**, em todos os 5 símbolos, tem o pior edge bruto médio
  (-4,27 bps, contra +5,27 em R2 e +3,39 em R3) e o win rate médio mais
  perto de 50% (50,52%) — mesmo com `n_better` médio mais alto que R2/R3
  (puxado por `ETHUSDT/R1`, que passa Sharpe mas tem o pior edge do
  grupo) — exatamente o modo de falha que motivou construir o gate duplo.

Decisão do Manager (mesma sessão): manter o desenho atual de Camada1/
Camada0 (ablação de restrição monotônica, não de feature set — ver
docstring de `fit_side_model`, `alpha.py:1319-1337`), **deprioritizar**
(não remover ainda) `BNBUSDT` e `R1` do próximo orçamento de busca
expandido, e formalizar aqui a arquitetura de medição pros 5+ itens já
esboçados em conversa, com atenção explícita a falso-positivo — pedido
direto do Manager ("Cuidado com falsos positivos").

**5 lacunas identificadas antes desta ADR** (não resolvidas por H8-H11):

1. Orçamento de busca raso — 30 trials/study, ~10-20× menos que a regra
   prática de TPE pra 12 dimensões (Bergstra & Bengio).
2. Só top-3 candidatos confirmados — o vencedor real por mediana pode não
   estar entre eles se o screening de 1 seed (já medido enviesado, `AG-383`)
   não o colocou no top-3.
3. `AG-220` (poder estatístico do gate) nunca foi calibrado sob o vetor
   de 36 features nem sob o gate duplo atual — só existe calibração
   antiga (ETHUSDT/R1, Fase 0b do ADR-002, vetor de 7-62 features,
   gate de Sharpe puro).
4. Variância entre seeds de confirmação já medida alta (`BTCUSDT/R2`:
   `n_better` de 2 a 5 só trocando seed) — 5 seeds pode não ser
   suficiente pra uma mediana estável.
5. A busca inteira (900+450+450+75 = 1875 trials/retreinos até aqui)
   avalia sempre contra os MESMOS 5 caminhos do CPCV — walk-forward real
   (`V41-11`, `src/validation/walk_forward.py`, não existe ainda) é o
   único jeito de medir sobreajuste do PROCESSO de busca, não só do
   trial individual.

**Restrições que o desenho precisa respeitar**: LightGBM só roda
`device_type="cpu"` nesta máquina (medido nesta sessão: CPU ≈ CUDA neste
hardware/tamanho de dado, `AG-379`/`AG-380`/`AG-381`); custo médio medido
por retreino ≈ 9,1-15s (H8: 9,1s/trial; recampanhas de confirmação:
9,7-15s/retreino, variação por contenção de CPU concorrente na sessão);
`N_lifetime` é recurso AUDITADO mas não gate vinculante (`AG-077`) —
orçamento deve ser explícito por item, não ilimitado; Camada1/Camada0
continuam com o MESMO desenho de ablação (decisão do Manager, não
reaberta aqui).

## Correção de validação (2026-08-30, mesma sessão, antes de qualquer execução)

Ao revalidar esta ADR (pedido explícito do Manager, "cuidado com falsos
positivos"), recomputei a média de edge bruto por SÍMBOLO (3 resoluções
cada) e achei uma inconsistência real na versão original do Item 1:

| símbolo | edge médio (3 resoluções) | padrão |
|---|---|---|
| `ETHUSDT` | **-6,98 bps** | negativo nas 3, sem exceção — **pior que `BNBUSDT`** |
| `BNBUSDT` | -5,51 bps | negativo nas 3, sem exceção |
| `BTCUSDT` | +2,61 bps | 2 de 3 positivas |
| `XRPUSDT` | +6,66 bps | 2 de 3 positivas |
| `SOLUSDT` | +10,51 bps | 3 de 3 positivas |

A lista original de "8 combos promissores" excluía `BNBUSDT` e `R1`
mecanicamente, sem recalcular a média por símbolo — resultado:
**`ETHUSDT/R2` (-1,66bps) e `ETHUSDT/R3` (-13,19bps, o PIOR edge de
todas as 15 combinações) ficavam dentro do orçamento expandido**, e
`SOLUSDT/R1` (+1,17bps, individualmente positivo) ficava fora só por ser
R1. `ETHUSDT` tem o MESMO padrão que motivou deprioritizar `BNBUSDT`
(negativo nas 3 resoluções) — só passou despercebido porque
`ETHUSDT/R1` passa o gate de Sharpe (`n_better=4,0`), mascarando o edge
bruto ruim nas 3 resoluções.

**Correção**: aplicar a MESMA regra de forma consistente — símbolo com
edge médio negativo nas 3 resoluções fica fora do orçamento expandido.
`BNBUSDT` E `ETHUSDT` saem (não só `BNBUSDT`). `R1` continua fora mesmo
recalculado só sobre os 3 símbolos restantes (`BTC`/`SOL`/`XRP`): média
R1 = -3,30bps, ainda a pior das 3 resoluções. **Item 1 passa de 8 pra 6
combos**: `BTCUSDT/R2`, `BTCUSDT/R3`, `SOLUSDT/R2`, `SOLUSDT/R3`,
`XRPUSDT/R2`, `XRPUSDT/R3`. Custo cai proporcionalmente (ver tabela de
orçamento atualizada abaixo). `SOLUSDT/R1` fica deprioritizado apesar do
edge individual positivo — critério aplicado por GRUPO (símbolo ou
resolução, n=3 ou n=5), não por célula individual (n=1, amostra fraca
demais pra decidir sozinha, mesma ressalva já registrada no Item 5).

Também verificado nesta revisão: `scipy.stats.false_discovery_control`
(Item 4) existe de verdade na versão instalada (`scipy 1.18.0`,
`uv.lock`) — citação conferida, não assumida.

## Decision

Adotar **6 itens sequenciados por dependência e custo**, cada um com
orçamento declarado ANTES de rodar (mesma disciplina do `ADR-002`), 4
deles com plano de execução real e 2 como decisão de escopo (não
executados nesta ADR).

### Item 1 — Orçamento de busca expandido, escopado nos 6 combos promissores

`alpha_optuna_n_trials` 30→150 (regra prática ~10-20× a dimensionalidade
da busca — 12 campos buscados). **Só nos 6 combos cujo SÍMBOLO tem edge
bruto médio positivo (3 de 3 resoluções, ou 2 de 3) E que não são R1**
(ver `## Correção de validação` acima): `BTCUSDT/R2`, `BTCUSDT/R3`,
`SOLUSDT/R2`, `SOLUSDT/R3`, `XRPUSDT/R2`, `XRPUSDT/R3` — os 9 restantes
(`BNBUSDT` completo, `ETHUSDT` completo, `R1` de `BTC`/`SOL`/`XRP`) ficam
de fora deste orçamento (economia de 60% do custo total de expandir pra
15/15).

- Custo: 6 combos × 2 camadas × 150 trials = 1.800 trials novos.
- Tempo estimado: 1.800 × 9,1-15s ≈ **4,5h-7,5h CPU** (faixa larga porque
  o custo por trial já variou nesta sessão por contenção; medir os
  primeiros ~100 trials reais antes de comprometer a estimativa final,
  mesma disciplina do `AG-371-ADDENDUM-17`).
- `N_lifetime`: +1.800.

### Item 2 — Confirmação mais profunda, sobre os mesmos 6 combos

`top_k` 3→6 candidatos confirmados, `confirmation_seeds` 5→10 seeds —
sobre o estudo JÁ expandido do Item 1 (zero busca nova).

- Custo: 6 combos × 6 candidatos × 10 seeds × 2 camadas = 720 retreinos.
- Tempo estimado: 720 × ~12s (média medida) ≈ **2,4h CPU**.
- `N_lifetime`: +720.
- **Não reduz rigor por aumentar `K`** — a seleção final continua por
  MEDIANA entre seeds (nunca argmax), a mesma disciplina que já corrigiu
  o winner's-curge medido (`AG-383`, viés médio +0,309); mais candidatos
  confirmados só reduz a chance de descartar o vencedor real antes de
  medir (lacuna #2), não afrouxa o critério de escolha entre eles.

### Item 3 — Calibração do gate (`AG-220`) sob o vetor/gate atuais

Repete a metodologia Fase 0b do `ADR-002` (permutar `label`+`ret_net`
JUNTOS, dentro do treino, por lado — nunca só `label`, senão a restrição
monotônica "trapaceia" com informação real) — mas agora mede a
distribuição NULA do **gate duplo inteiro** (Sharpe E edge bruto), não só
do Sharpe como da vez anterior, e sob os 36 features atuais, não os 7-62
da calibração antiga.

- **Escopo inicial: 3 combos representativos**, não os 15 — 1 que passa
  hoje (`BTCUSDT/R3`), 1 borderline (`n_better` mais alto entre os que
  falham — candidato: `ETHUSDT/R1`, `n_better=4` mas falha edge), 1
  claramente fraco (`BNBUSDT/R1`). Generalizar pros 8 (ou 15) só se o
  resultado variar por combo — não gastar o orçamento cheio sem saber se
  precisa.
- Custo: 3 combos × 50 execuções × 2 camadas = 300 retreinos.
- Tempo estimado: 300 × ~12s ≈ **1h CPU**.
- `N_lifetime`: +300.
- **Produz o número que falta pra responder "cuidado com falsos
  positivos" de verdade**: taxa real de falso-positivo do critério
  `n_better≥4 E edge>0 E trades≥30` sob ruído puro (sem sinal real) —
  hoje esse número simplesmente não existe pro desenho atual.

### Item 4 — Correção de múltiplas comparações (novo, resposta direta ao pedido de cuidado com falso-positivo)

Nenhum item anterior corrige o fato de estarmos testando **15 (ou 8, após
poda) combinações símbolo×resolução simultaneamente** sem ajustar o
limiar de significância — o mesmo problema já registrado na tabela de
taxa-base do artefato (`lim.01`: "a 5% de falso-positivo esperaríamos
~0,75 por acaso; 7/15 significativos é mais que ruído, mas cada
combinação individual merece cautela"). Aplicar **Benjamini-Hochberg
(FDR)**, não Bonferroni puro (Bonferroni é conservador demais pra 8-15
testes correlacionados — os 3 R1/R2/R3 do mesmo símbolo não são
independentes, vêm do mesmo fluxo de trades) sobre os p-valores da tabela
de taxa-base E sobre qualquer veredito de gate duplo daqui pra frente.

- Custo: zero trial novo — é código (`scipy.stats.false_discovery_control`
  ou equivalente) aplicado sobre resultado JÁ medido.
- Ação: nova função em `src/validation/` (ou `src/analysis/`, a
  decidir conforme fronteira de camada), testada, aplicada
  retroativamente à tabela de taxa-base do H0-H7 do artefato E ao
  resultado do Item 1/2 quando sair.

### Item 5 — Critério operacional de poda (`BNBUSDT` + `ETHUSDT` + `R1`)

Trava a priori, com definição operacional explícita (regra do
`CLAUDE.md` — decisão travada sem definição de termo é o viés que travar
a priori existe pra evitar):

> **Poda definitiva** de um símbolo ou resolução do treino do Alpha
> exige: `edge bruto médio < 0` (calculado sobre TODAS as resoluções do
> símbolo, ou todos os símbolos da resolução) **sob o orçamento expandido
> do Item 1** (`n_trials≥150`, não os 30 atuais) **E** `AG-220` (Item 3)
> confirmando que o gate tem poder estatístico suficiente pra essa
> conclusão não ser majoritariamente ruído (taxa de falso-positivo
> calibrada `<20%`, piso arbitrário sujeito a revisão — `sweep_required`
> registrado em `constants.yaml`).

Até lá, `BNBUSDT`/`ETHUSDT`/`R1` ficam **deprioritizados** (fora do Item
1/2), não removidos — continuam existindo nos artefatos já gerados
(H8-H11), só não recebem o orçamento expandido nesta rodada.

- Custo: zero trial novo — decisão + constante nova em `constants.yaml`
  (`alpha_prune_min_edge_bps_threshold`, `alpha_prune_max_gate_fpr` —
  `class: B`, `provenance: ASSUMED`, `sweep_required: true`).

### Item 6 — Walk-forward real (decisão de escopo, não executado aqui)

Lacuna #5 (busca inteira reusa os mesmos 5 caminhos do CPCV) só se fecha
com dado que a busca NUNCA viu — `src/validation/walk_forward.py`
(`V41-11` do Road Map Vivo, Sprint 11) não existe ainda. **Fora do
orçamento desta ADR** — é construção de infraestrutura nova, não "rodar
mais" como os Itens 1-3. Registrado aqui como risco residual EXPLÍCITO
que sobrevive mesmo depois dos Itens 1-4: qualquer combo que passar o
gate duplo expandido continua sem confirmação walk-forward até esse item
ser decidido separadamente.

### Orçamento total (Itens 1-3, os únicos com custo de trial)

| item | trials/retreinos novos | tempo estimado | depende de |
|---|---|---|---|
| 1 — busca expandida (6 combos) | 1.800 | 4,5h-7,5h | nada, pode começar já |
| 2 — confirmação profunda (6 combos) | 720 | ~2,4h | Item 1 completo |
| 3 — calibração `AG-220` (3 combos) | 300 | ~1h | independente, pode rodar em paralelo ao Item 1 |
| **total** | **2.820** | **~8h-10,5h CPU** | — |

`N_lifetime`: 2.636 (counter atual, id=37) → **~5.456** ao final dos 3
itens. Itens 4/5 não consomem `N_lifetime` (são código/decisão, não
retreino).

## Options Considered

### Option A: Expandir tudo (15 combos, todos os itens juntos) — REJEITADA

Custo ≈ 2,5× o desenhado nos Itens 1-2 (15 combos em vez de 6
promissores) — 4.500+1.800=6.300 trials/retreinos, **~15h-23h CPU** só
nos itens 1-2. Rejeitada porque gasta orçamento igual em combos já
mostrando sinal fraco (`BNBUSDT`/`ETHUSDT`/`R1`) e em combos promissores,
quando o Item 5 já declara um critério de poda que deveria vir DEPOIS de
medir com orçamento de verdade, não antes.

### Option B: Não expandir nada, aceitar H8-H11 como veredito final — REJEITADA

Barata (zero custo novo) mas ignora as 5 lacunas já documentadas —
em particular, "só `BTCUSDT/R3` passa" sob um orçamento de busca de 30
trials (lacuna #1) e sem calibração do gate (lacuna #3) é uma conclusão
frágil demais pra decisão de escopo do projeto inteiro. Rejeitada por
não responder ao pedido explícito do Manager de tratar isso como
medição obrigatória, não opcional.

### Option C (escolhida): Itens 1-3 escopados (6+3 combos) + Itens 4-5 sem custo de trial + Item 6 como decisão separada

Meio-termo: cobre as 4 lacunas mais baratas de fechar (#1/#2/#3/#4 via
Itens 1/2/3/4) com orçamento real declarado, trata a poda como decisão
CONDICIONAL a medição futura (Item 5) em vez de já executada, e não
finge que a lacuna #5 (walk-forward) está resolvida só porque é a mais
cara — fica registrada como risco aberto.

## Trade-off Analysis

A pergunta central não é "qual orçamento acha o hiperparâmetro ótimo" —
é "qual orçamento é grande o bastante pra não repetir o erro de tratar
um resultado de 30 trials como veredito final, sem gastar trials
adicionais em combos que 2 métricas independentes (edge bruto + win
rate), agregadas por SÍMBOLO (não por célula isolada — a correção de
validação acima é exatamente essa disciplina aplicada), já sugerem
fraco". Option A é mais completa mas cara demais pra decisão de escopo
que ainda depende de calibrar o próprio instrumento de medição
(`AG-220`, Item 3) antes de confiar no resultado. Option C é o ponto que
resolve a lacuna mais urgente (orçamento raso) sem gastar nos 9 combos
que a poda (Item 5) provavelmente vai descartar de qualquer forma — se
errar (9 combos deprioritizados escondem edge real em algum deles), o
custo de descobrir depois é rodar o mesmo Item 1 neles, não maior que
rodar agora.

## Consequences

- **Fica mais fácil**: interpretar "1/15 passa" com o contexto certo —
  cada resultado futuro carrega o orçamento que o produziu (30 vs. 150
  trials) e a calibração de falso-positivo do gate que o julgou, em vez
  de um número solto.
- **Fica mais difícil**: obter resposta rápida — ~8h-10,5h CPU antes da
  próxima leitura de "quantos combos passam", contra as ~4h totais que
  H8-H11 levaram até aqui.
- **Precisa ser revisitado**: se o Item 3 (calibração `AG-220`) mostrar
  que o gate tem taxa de falso-positivo alta mesmo nos 3 combos
  representativos, o critério de poda do Item 5 (que depende do gate
  calibrado) fica bloqueado até o gate em si ser redesenhado — não dá
  pra travar a poda num instrumento que a própria ADR está admitindo não
  ter poder medido ainda.
- **Achado que N_lifetime vai passar de 6.000** só nesta ADR — reforça
  que orçamento explícito por item (tabela acima) continua obrigatório,
  não op­cional, mesma lição do `ADR-002`.

## Action Items

1. [x] Promover `top_k`/`confirmation_seeds` de default hardcoded no CLI
   (`hyperparams_optuna.py::_run_cli`) pra `constants.yaml`
   (`alpha_optuna_confirm_top_k=6`, `alpha_optuna_confirm_seeds=[101..1010]`
   — `class: B`, `ASSUMED`) — CONCLUÍDO, commit `f97d1b2`. 20/20 testes
   pré-existentes continuam passando.
2. [x] `alpha_optuna_n_trials` 30→150 em `constants.yaml` (source
   atualizada com a regra prática TPE ~10-20×dimensionalidade) —
   CONCLUÍDO, commit `908896e`.
3. [x] Rodar Item 1 (busca expandida, 6 combos) — CONCLUÍDO 2026-08-30,
   1.800/1.800 trials, 0 falhas, 2h32m18s real (bem abaixo da estimativa
   de 4,5h-7,5h — ~5,08s/trial medido, não os 9,1-15s de campanhas
   anteriores). Achado: `SOLUSDT/R2` com as 2 camadas em `best_value`
   extremo (22,22/8,96 vs. p95≈0,82 da campanha) — ver
   `audit/n_lifetime.yaml::id=38` e o artefato "ADR-007 — Painel de
   Execução" pro detalhamento completo. Não tratado como sinal real até
   o Item 2.
4. [ ] Rodar Item 3 (calibração `AG-220`, 3 combos representativos:
   `BTCUSDT/R3`, `ETHUSDT/R1`, `BNBUSDT/R1`) — código e testes prontos
   (`src/validation/ag220_dual_gate_calibration.py`, commit `28708f2`),
   aguardava só o Item 2 terminar pra evitar contenção de CPU (`AG-381`
   já mediu ~54% de piora de throughput sob concorrência neste
   hardware) — Item 2 concluiu 2026-08-31 00:12:11, próximo passo real.
5. [x] Rodar Item 2 (confirmação profunda, 6 combos) — CONCLUÍDO
   2026-08-31, 720/720 confirmações, 0 falhas, 1h00m51s
   (23:11:20→00:12:11). **ZERO dos 6 combos passam o gate duplo.**
   `BTCUSDT/R3` (único combo que passava sob H10/confirmação original,
   `median_n_better=4,0`) cai para `2,5` sob o orçamento maior (top-6,
   10 seeds) — `n_better_by_seed` varia de 1 a 5 só trocando seed, o
   mesmo hiperparâmetro vencedor. Demais combos: `BTCUSDT/R2`=3,0;
   `SOLUSDT/R2`=2,5 (a anomalia de screening do Item 1 confirma-se como
   ruído puro, viés de seleção +8,356, recorde do projeto);
   `SOLUSDT/R3`=3,0 (o mais próximo — edge +27,08bps, viés baixo
   +0,185); `XRPUSDT/R2`=2,0 (Camada0/baseline supera Camada1);
   `XRPUSDT/R3`=2,5. Ver `audit/n_lifetime.yaml::id=39` e o artefato
   "ADR-007 — Painel de Execução" pro detalhamento completo por combo.
6. [x] Implementar correção FDR (Item 4) — `src/validation/fdr_correction.py`
   (commit `5a322c6`), testada (7 testes), aplicada à tabela de
   taxa-base existente (H0-H7, 15 z-scores reais): 7/15 significativos
   sem correção → 4/15 sob BH → 3/15 sob BY. **Ainda não aplicada ao
   resultado dos Itens 1-2** — Item 2 mede `median_n_better`/edge
   pareado por seed, não um z-score/p-valor único por combo; requer
   decidir a estatística de teste correta antes de aplicar FDR em cima
   (candidato natural: taxa de `n_better>=4` sobre as 10 seeds como
   proporção, testada contra 50% via binomial — não decidido ainda,
   registrar como lacuna aberta, não inventar a estatística sem
   validar).
7. [ ] Registrar constantes de poda (Item 5) em `constants.yaml` — sem
   aplicar a poda ainda (condicional ao resultado dos Itens 1/3).
8. [ ] `audit/architecture_gaps_log.yaml` — nova entrada (`AG-384` ou
   próximo livre) referenciando esta ADR, ao fechar cada item.
9. [ ] `docs/SPRINT_LOG.md` — nova seção ao fechar o primeiro item real.
