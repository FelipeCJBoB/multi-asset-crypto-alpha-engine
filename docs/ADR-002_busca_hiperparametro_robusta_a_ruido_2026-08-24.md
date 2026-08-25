# ADR-002: Arquitetura de busca de hiperparâmetro/feature-set do Alpha, robusta a ruído de seed

**Status:** Implementada e executada (ETHUSDT/R1) — ver `## Resultado (2026-08-24)`
**Date:** 2026-08-24
**Deciders:** Manager (Felipe)

## Context

A campanha de ablação T2→T1 (`docs/t2_t1_ablation_veredito_duas_analises_2026-08-24.md`)
rodou 3 fases (Fase 0 = diagnóstico de ruído; Fase 1 = grid de 65
combinações `k`×`max_depth`×`num_leaves`; Fase 2 = extensão de fronteira,
16 combinações) e uma confirmação. **Achado real, não hipotético**: os 81
trials de Fase 1+2 usaram **1 seed fixa só** (`alpha_random_seed=42`),
nunca repetida por candidato. Um "vencedor" (`k=32, num_leaves=3,
min_child_samples=500`) emergiu da Fase 2 com `pooled_sharpe=-1,5945`
(gap de só -0,75σ do piso de ruído medido na Fase 0a, contra ~-2,0σ da
Fase 1). Ao confirmar esse ÚNICO candidato com 10 seeds + gate de
permanência real (Camada1 vs Camada0, sem permutação): `pooled_sharpe`
médio caiu pra **-1,9212** (gap real -1,82σ) e o gate de permanência deu
**0 de 5** caminhos — o "achado" não sobreviveu.

**Causa raiz, não sintoma**: escolher o melhor candidato entre muitos
avaliados sob ruído (σ medido ≈0,2-0,3 em unidades de `pooled_sharpe`,
Fase 0a/confirmação) infla sistematicamente o valor aparente do
escolhido — vieé de seleção / "winner's curse", a mesma matemática que
`src/validation/dsr.py::expected_max_sharpe_under_n_trials` já implementa
neste repo, só que aplicada até hoje à seleção de MODELO/ESTRATÉGIA, nunca
à própria busca de hiperparâmetro. O design doc original já previa a
mitigação certa ("seleção final: mediana dos top-5 trials, nunca o melhor
isolado", §4) — nunca foi implementada; a seleção real usou `max()` sobre
score de 1 seed só, tanto na Fase 1 quanto na Fase 2.

**Gap adicional, não relacionado ao ruído**: 5 dos 9 hiperparâmetros do
LightGBM (`learning_rate`, `subsample`, `feature_fraction`, `lambda_l2`,
`n_estimators`) nunca foram variados em nenhuma fase — travados no valor
de produção o tempo todo. Qualquer conclusão "definitiva" sobre T2 sem
cobrir esse espaço é prematura, porque não descarta que um regime de
hiperparâmetro diferente destrave valor das features T2.

**Restrições que o desenho precisa respeitar**: CPCV de 5 paths (fixo,
`config/constants.yaml::cpcv_*`); LightGBM só roda `device_type="cpu"`
nesta máquina (`AG-201`, NCCL não compila no Windows); `N_lifetime` é
recurso AUDITADO mas não é mais gate vinculante (`AG-077`) — orçamento
deve ser explícito, não ilimitado; harnesses já existentes
(`src/validation/t2_t1_capacity_map.py`, `t2_t1_capacity_map_fase2.py`,
`t2_t1_fase2_confirmation.py`) devem ser reusados como blocos de
construção, não descartados — a lógica de treino/backtest neles já está
correta, o que faltou foi a CAMADA DE ORQUESTRAÇÃO em torno deles.

## Decision

Adotar **Opção A — busca em 3 estágios com custo crescente** (screen →
confirm → gate), com correção formal de viés de seleção em cada
transição de estágio.

### Estágio 1 — Screening (1 seed, barato, já parcialmente feito)

- **k / max_depth / num_leaves / min_child_samples**: grid já rodado
  (Fase 1 + Fase 2, 81 combinações) — REUSADO, não refeito. Tratado
  explicitamente como SCREENING (nunca decisão), não como achado
  confirmado — isso é a correção de enquadramento, não um novo trial.
- **learning_rate / subsample / feature_fraction / lambda_l2 /
  n_estimators**: NOVO — coordenada-descendente, não grid cheio (5
  dimensões × mesmo nº de pontos cada explodiria combinatorialmente).
  Fixa a melhor região de `(k, depth, leaves, mcs)` encontrada no
  screening acima, varia CADA um dos 5 hiperparâmetros isoladamente ao
  redor do valor de produção (3-4 pontos cada, ex.
  `learning_rate ∈ {0,01; 0,03(PROD); 0,05; 0,08}`), mantendo os outros 4
  travados em PROD a cada passe. ~15-20 trials novos, 1 seed cada (mesmo
  regime de custo do screening já feito — não é o estágio caro).
- Saída: lista de candidatos ordenada por score de 1 seed — **explicitamente
  rotulada como enviesada pra cima (winner's curse), nunca reportada como
  estimativa final**.

### Estágio 2 — Confirmação (multi-seed, nos top-K, não no top-1)

- Pega os **top-5** candidatos do Estágio 1 (não só o argmax) — implementa
  de fato a regra que o design doc original já declarava e nunca foi
  codificada.
- Cada um dos 5 roda com **N=5 seeds** (`_derived_seed(base, i)`,
  i=0..4 — metade do orçamento da confirmação atual de 10 seeds, porque
  agora são 5 candidatos, não 1; ajustável se o orçamento permitir mais).
- Seleção final pela **mediana** dos 5 seeds por candidato (não a média —
  mediana é mais robusta a um seed outlier, e é literalmente o que o
  design doc pedia). Vencedor = candidato com maior mediana.
- Reporta OS DOIS números lado a lado sempre: score de 1 seed do Estágio 1
  (o que causou a seleção) e mediana do Estágio 2 (a estimativa real) —
  a diferença entre os dois É a medida direta do viés de seleção nesta
  rodada, não precisa da fórmula de `dsr.py` pra ver isso quando os dois
  números já estão lado a lado.
- Custo: 5 candidatos × 5 seeds = 25 trials.

### Estágio 3 — Gate de permanência (só o vencedor final, repetido)

- **Novo, não existia**: o candidato final do Estágio 2 passa por
  `run_permanence_check_fase2`-style (Camada1 vs Camada0, dado real, sem
  permutação) repetido **N=5-10 seeds**, não 1 tiro só — mesma disciplina
  que a Fase 0b já aplica ao NULO, agora aplicada ao candidato REAL.
- Critério de promoção: **mediana** de `n_better` sobre as repetições
  `>= alpha_layer1_permanence_min_paths` (constante já existe,
  `config/constants.yaml`) — nunca uma única realização.
- Custo: 5-10 trials (pares Camada1+Camada0, mesmo critério de contagem
  já usado no `n_lifetime.yaml`: par = 1 trial).

### Orçamento total (Estágios 1+2+3, novo)

| estágio | trials novos | custo (1 trial ≈ 55-65s medido) |
|---|---|---|
| 1 — coordenada-descendente dos 5 hiperparâmetros | ~20 | ~20 min |
| 2 — confirmação top-5 × 5 seeds | 25 | ~25 min |
| 3 — gate de permanência × 5-10 seeds | 5-10 | ~10-20 min |
| **total novo** | **~50-55** | **~55-65 min** |

`N_lifetime` 250 → ~300-305. Sunk cost dos 149 trials de Fase 1+2 é
reusado (não descartado, não recontado) — só reclassificado como
"screening", não como "achado".

## Options Considered

### Option A: Screen (1 seed) → Confirm top-5 (5 seeds, mediana) → Gate repetido (5-10 seeds) — ESCOLHIDA

| Dimensão | Avaliação |
|---|---|
| Complexidade | Média — 3 estágios, mas cada um reusa harness já escrito |
| Custo (N_lifetime) | ~50-55 trials novos, ~55-65 min |
| Robustez a viés de seleção | Alta — mediana de top-5, não argmax de top-1 |
| Cobre os 5 hiperparâmetros faltantes | Sim, via coordenada-descendente |
| Reusa infraestrutura existente | Sim — `t2_t1_capacity_map*.py` viram os blocos de Estágio 1/2, `fase2_confirmation.py` vira o Estágio 3 |
| Risco residual | Coordenada-descendente não explora INTERAÇÕES entre os 5 hiperparâmetros novos (assume que otimizar 1 de cada vez captura o essencial) |

**Pros:** custo controlado, implementa a regra que já estava documentada
e nunca foi codificada, corrige o erro concreto encontrado hoje sem
reescrever a infraestrutura de treino.
**Cons:** coordenada-descendente pode perder ótimo se os 5 hiperparâmetros
novos interagirem fortemente entre si (ex. `learning_rate` baixo
combinado com `n_estimators` alto — clássica interação de LightGBM não
capturada variando 1 de cada vez).

### Option B: Grid completo multi-seed desde o início (força bruta robusta)

| Dimensão | Avaliação |
|---|---|
| Complexidade | Baixa — sem estágios, sem lógica de seleção-de-top-K |
| Custo (N_lifetime) | Alto — grid já tinha ~150 pontos; ×5 seeds = ~750 trials só pra repetir o que já existe, antes dos 5 hiperparâmetros novos |
| Robustez a viés de seleção | Alta por construção (sem seleção precoce) |
| Cobre os 5 hiperparâmetros faltantes | Só se expandir o grid pra 5 dimensões novas — combinatorialmente proibitivo (mesmo 3 pontos cada = 243× o grid atual) |
| Reusa infraestrutura existente | Sim, mas sem economia de custo |

**Pros:** conceitualmente mais simples, zero risco de viés de seleção.
**Cons:** custo proibitivo mesmo só pra reavaliar o que já existe — a
maior parte do grid está longe do ótimo e não precisa de 5 seeds pra
saber disso; desperdiça a maior parte do orçamento em candidatos
claramente ruins.

### Option C: Otimizador Bayesiano/sequencial (Optuna) com objetivo ruidoso

| Dimensão | Avaliação |
|---|---|
| Complexidade | Alta — Optuna nunca foi wireado neste repo; sampler padrão (TPE) não modela ruído nativamente, exigiria wrapper de repetição-e-média por trial |
| Custo (N_lifetime) | Variável, potencialmente mais eficiente por trial que grid, mas `n_startup_trials` (10 default) ainda seria sorteio aleatório puro na escala orçada aqui |
| Robustez a viés de seleção | Média — depende de como o wrapper de ruído é desenhado, não é automático |
| Cobre os 5 hiperparâmetros faltantes | Sim, nativamente (essa é a força de Optuna — múltiplas dimensões simultâneas) |
| Reusa infraestrutura existente | Parcial — harnesses de treino sim, orquestração de busca não |

**Pros:** a ferramenta certa se a campanha crescer muito mais (múltiplos
símbolos × resoluções, dezenas de hiperparâmetros) — decisão já **adiada
2 vezes** neste projeto (§9.1/§3 do design doc original) com o mesmo
motivo: escala pequena demais pra justificar a dívida de engenharia de
uma dependência nova nunca usada no repo.
**Cons:** dívida de engenharia real (dependência nova, sampler custom pra
ruído), tempo de implementação provavelmente maior que o Estágio 1+2+3
inteiro da Opção A.

## Trade-off Analysis

A pergunta central não é "qual método acha o ótimo global" — é "qual
método é barato o bastante pra rodar hoje E honesto o bastante pra não
repetir o erro de hoje". Opção B é honesta mas cara demais pra escala
atual (~150 pontos já gastos). Opção C é elegante mas é dívida de
engenharia nova pra um problema que Opção A resolve com a infraestrutura
que já existe. Opção A é o meio-termo desenhado especificamente pro erro
diagnosticado (seleção sobre 1 seed) — não é a busca teoricamente ótima,
é a busca que não teria produzido o resultado falso-positivo de hoje.

## Consequences

- **Fica mais fácil**: interpretar corretamente o resultado de qualquer
  busca futura — todo "vencedor" reportado carrega o score enviesado E a
  mediana confirmada lado a lado, o viés de seleção fica visível, não
  escondido.
- **Fica mais difícil**: obter um "resultado" rápido — 3 estágios em vez
  de 1 relatório de grid; ~55-65 min de wall-clock a mais antes de
  qualquer decisão de promoção.
- **Precisa ser revisitado**: se a campanha se expandir pras outras 14
  combinações símbolo×resolução, o custo do Estágio 2/3 multiplica por
  15 — nesse ponto, reavaliar Opção C (Optuna) deixa de ser prematuro.
- **Achado que N_lifetime consumido nesta campanha (250) já ultrapassa
  em muito** o teto histórico de 60 citado no `PRD_V4_1.md` (documento
  obsoleto, mas o número foi citado como referência em `AG-077`) — não é
  um problema por si (`counter` não é mais gate vinculante), mas reforça
  que orçamento explícito por estágio (tabela acima) é obrigatório daqui
  pra frente, não op­cional.

## Action Items

1. [x] Implementar Estágio 1b (coordenada-descendente dos 5 hiperparâmetros
   faltantes) — `src/validation/t2_t1_stage1_hyperparam_screen.py`.
2. [x] Implementar Estágio 2 (confirmação top-5 × 5 seeds, seleção por
   mediana) — `src/validation/t2_t1_stage2_3_robust_confirm.py::run_stage2_confirm`.
3. [x] Implementar Estágio 3 (gate de permanência repetido, N=5 seeds,
   critério de mediana) — `t2_t1_stage2_3_robust_confirm.py::run_stage3_permanence_gate`.
4. [x] Rodar os 3 estágios sobre ETHUSDT/R1 — concluído 2026-08-24, ver
   `## Resultado` abaixo. Generalizar pras outras 14 combinações continua
   sem justificativa (resultado negativo).
5. [x] Registrado em `audit/n_lifetime.yaml` por estágio (ids 25/26/27,
   counter 250→288), não em bloco único.
6. [x] Re-contextualizado (não editado) via addendum em prosa nas seções
   `## Context`/`## Resultado` desta ADR e nota cruzada no id=27 do
   `n_lifetime.yaml` apontando pro id=24 (Fase 2) como leitura
   substituída, não apagada.

## Resultado (2026-08-24)

Estágios 1b/2/3 rodados ponta a ponta sobre ETHUSDT/R1 (labels
relabeled 2× nesta sessão — fix `tp_atr_mult`/`sl_atr_mult` e depois
`AG-205`/`gap_aware_sl_v1` — `config_hash` verificado igual antes de
cada retreino).

- **Estágio 1b** (13 treinos novos, 1 seed cada, ancorado no vencedor
  Fase 2): achado mais chamativo da campanha inteira —
  `n_estimators=150` → `pooled_sharpe=-0,8478`. Rotulado explicitamente
  como screening enviesado pra cima, não como achado.
- **Estágio 2** (20 treinos novos, top-5 × 5 seeds, seleção por
  mediana): confirma o viés — esse mesmo candidato caiu pra
  `median_pooled_sharpe=-1,6198` (`selection_bias_estimate=+0,772`, o
  maior viés de seleção medido no projeto até agora). O vencedor real
  por mediana foi outro candidato (`learning_rate=0,01`,
  `n_estimators=300`, resto = produção):
  `median_pooled_sharpe=-1,1355`, sem viés de seleção
  (`selection_bias_estimate=-0,135`).
- **Estágio 3** (5 treinos novos, gate de permanência repetido sobre o
  vencedor do Estágio 2): `n_better` por seed = `[2,3,0,1,0]` de 5
  paths, `median_n_better=1,0` — muito abaixo do limiar de produção
  (`≥4`). **`permanence_pass=false`.**

**Veredito**: mesmo cobrindo os 5 hiperparâmetros que faltavam e
corrigindo o viés de seleção que invalidou a leitura da Fase 2, T2
(features de suporte, `k=32`) **não sobrevive** ao gate de permanência
real em ETHUSDT/R1. A crítica do Manager estava certa — a Fase 2 não
tinha metodologia definitiva pra fechar — mas o resultado final,
agora com metodologia completa, é o mesmo veredito negativo que o
`id=24` do `n_lifetime.yaml` já apontava, só que agora sem a lacuna
que o tornava contestável. Detalhe completo:
`audit/evidence_ledger.yaml::adr002-t2-t1-stage2-3-veredito-robusto-2026-08-24`,
`n_lifetime.yaml` ids 25-27 (counter 250→288).

Não decidido aqui, permanece com o Manager: se vale a pena repetir
este mesmo protocolo de 3 estágios nas outras 14 combinações
símbolo×resolução, dado o custo (~38 trials por combinação) e o
resultado uniformemente negativo até agora.
