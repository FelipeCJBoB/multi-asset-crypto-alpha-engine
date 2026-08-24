# Veredito — duas análises (interna + auditoria externa) sobre a ablação T2→T1

Status: síntese crítica, **supersede §9.2 do `docs/t2_t1_promotion_ablation_
design_doc_2026-08-24.md`** (a grade `GridSampler` de 24 combos/k fica
OBSOLETA — ver §5 abaixo). Nada aqui foi implementado. Escrito sob pedido
explícito de máxima criticidade — as duas análises de entrada são tratadas
como material a auditar, não a costurar sem checar, inclusive a análise do
próprio usuário.

Entradas: (1) análise do usuário, verbatim na conversa, 2026-08-24; (2)
análise externa (PDF, `ae66c68f-Com_esses_dados.pdf`); (3) pesquisa web
registrada em `docs/t2_t1_promotion_ablation_design_doc_2026-08-24.md`
§9.1/§9.2 (Optuna/LightGBM docs oficiais, López de Prado 2018 lido na
íntegra).

---

## 1. Onde as duas análises convergem (aceito sem ressalva)

1. AUC ~0,51 uniforme (0,5050–0,5131) é o dado mais importante do projeto
   hoje — sinal quase nulo e ESTÁVEL, não um problema de 1-2 combinações.
2. Otimizar Sharpe OOS pooled, não AUC — uma diferença de AUC de milésimos
   não tem necessariamente relação com qualidade econômica.
3. `num_leaves` e `max_depth` não são eixos independentes — todo desenho
   de busca precisa condicionar um ao outro, nunca varrer livre.
4. PBO nunca deve ser o alvo do sampler — é avaliação PÓS-HOC sobre a
   população de trials já rodados.
5. `N_trials_per_k` não deveria ir a 100+ nesta rodada — as duas análises
   convergem numa faixa modesta (15-40), não numa busca agressiva.
6. Antes de qualquer sweep pesado, existe um risco real de que o problema
   esteja ANTES do hiperparâmetro — a auditoria externa lista 10
   hipóteses candidatas (qualidade de T1, definição de label, assimetria
   long/short, etc.); a análise do usuário vai além: propõe 2
   experimentos concretos, baratos e imediatamente executáveis pra medir
   isso, não só uma lista de suspeitos.

## 2. Onde divergem, e o que eu decido — com auditoria de cada lado

### 2.1 `max_depth = -1` (usuário) vs. `max_depth ∈ {2..6}` condicionado (externa)

O achado técnico do usuário está CORRETO e é mais sério do que uma
preferência de desenho: `max_depth=3` fixo (`sweep_required: false`) +
`num_leaves` com `sweep_range: [4, 64]` declarado (`sweep_required:
true`) em `constants.yaml` hoje é uma declaração **literalmente
enganosa** se lida isolada — uma árvore de profundidade 3 tem no máximo
8 folhas; qualquer trial que sorteasse `num_leaves ∈ {16,32,64}` sob
`max_depth=3` produziria o MESMO modelo de `num_leaves=8` (o teto de
profundidade corta antes), gastando trial (e `N_lifetime`) sem explorar
nada de novo.

**Mas isso não invalida a grade condicional da auditoria externa — invalida
só varrer `num_leaves` sozinho contra o range cru declarado.** A minha
própria grade anterior (§9.2 do design doc, agora superseded) já
condicionava `num_leaves` a `max_depth` (`depth=3→{8,5}`, `depth=4→
{16,10}`) — ou seja, já não caía nessa armadilha na PRÁTICA, mas a
DECLARAÇÃO em `constants.yaml` continua enganosa pra qualquer implementação
futura que leia só o `sweep_range` sem essa nota. **Decisão: adoto a
grade condicional (mais informativa, deixa aberto se profundidade
importa por si — pergunta que `max_depth=-1` fecha antes de perguntar),
E corrijo a declaração em `constants.yaml`** — `alpha_lgbm_max_depth`
passa a `sweep_required: true` com a faixa condicionada documentada
explicitamente no `source`, não um range solto.

### 2.2 O hurdle do DSR — a conta do usuário está certa, a baseline usada está errada

Esta é a correção mais importante desta síntese. O usuário calculou
corretamente que `E[max SR_N] ∝ Φ⁻¹(1-1/N)` cresce de ~1,59σ pra ~2,65σ
saindo de `N≈18` pra `N=250` (~65% de aumento) — a aritmética bate
(verifiquei: `Φ⁻¹(0,9444)≈1,593`, `Φ⁻¹(0,996)≈2,652`, razão 1,665).

**Mas `N≈18` não é a baseline real.** `CLAUDE.md` e `audit/n_lifetime.
yaml` são explícitos: "DSR usa `N_lifetime`, não o N de uma busca
isolada" — e `N_lifetime.counter` hoje é **96**, não 18 (confirmado
lendo o ledger real, não estimado). Refazendo a conta com a baseline
correta:

- `N=96` (hoje): `Φ⁻¹(1-1/96) = Φ⁻¹(0,9896) ≈ 2,313`
- `N=96+250=346` (se a campanha inteira de 250 trials rodasse): `Φ⁻¹(1-
  1/346) = Φ⁻¹(0,99711) ≈ 2,760`
- Razão: `2,760/2,313 ≈ 1,194` — **~19% de aumento no hurdle, não ~65%**.

O argumento QUALITATIVO do usuário continua de pé (mais trials sempre
sobe o hurdle, e com AUC~0,51 a margem é apertada) — mas a MAGNITUDE
específica que ele calculou superestima o custo marginal desta campanha
especificamente, porque comparou contra uma baseline pequena demais. Boa
parte do "dano" ao hurdle já aconteceu ANTES desta decisão (96 trials de
exploração prévia, majoritariamente não relacionada a hiperparâmetro do
Alpha — sweeps de geometria de barreira, comparação de estimador de
volatilidade, etc.) — o que importa pra decidir SE VALE A PENA esta
campanha específica é o custo MARGINAL (~19%), não o custo total
acumulado desde o início do projeto.

### 2.3 `N_trials_per_k` pra hiperparâmetro isolado: "~zero" (usuário) vs. "30-40 mesmo assim" (externa)

Aqui fico do lado do usuário, mas por um motivo ligeiramente diferente do
dele. Não é que o orçamento "correto" seja zero — é que a PERGUNTA "quantos
trials de hiperparâmetro" está fora de ordem antes da Fase 0 (§4)
responder se existe QUALQUER sinal detectável acima do ruído de execução.
A auditoria externa não propõe nenhum teste equivalente — só uma lista de
suspeitos pra investigar "depois". O usuário propõe 2 experimentos
concretos, baratos, que já rodam no pipeline existente sem mudança de
código. **Isso vira Fase 0 do plano abaixo, obrigatória, antes de
comprometer qualquer orçamento de busca.**

### 2.4 Achado novo do usuário, não presente na auditoria externa nem na minha síntese anterior: 3/15 é ruído

Teste binomial sob a hipótese nula (Camada1 ≡ Camada0, cada path uma
moeda): `P(n_better≥4 de 5) = C(5,4)*0,5⁵ + C(5,5)*0,5⁵ = 6/32 = 0,1875`.
Esperado sob o nulo em 15 combinações: `15×0,1875 = 2,8`. Observado: 3.
**Matemática verificada, está correta.** O achado "3/15 (20%) passa o
gate" registrado em `audit/evidence_ledger.yaml::alpha-lightgbm-sweep-
15-combinacoes-2026-08-23` — sem essa contextualização — lê como
sinal fraco mas real; com ela, é **estatisticamente indistinguível de
ruído puro**, e na direção conservadora (paths do CPCV compartilham
dado de treino, não são moedas independentes — variância real maior que
a binomial assumida, tornando a evidência ainda mais fraca).

O mesmo raciocínio se estende às 15 combinações símbolo×resolução: BTC/
ETH/SOL/BNB/XRP são correlacionados entre si, R1/R2/R3 do mesmo símbolo
vêm do mesmo fluxo de trades — **N efetivo real está mais perto de 2-3
que de 15.** Isto tem uma consequência prática direta pro desenho da Fase
2 (§4): "Sharpe OOS pooled" sobre as 15 combinações, se e quando isso
rodar, PODE subestimar a variância real do estimador (tratando réplicas
correlacionadas como independentes) — mitigação proposta: reportar
Sharpe pooled JUNTO COM Sharpe por cluster de símbolo (não só o número
único), pra essa correlação ficar visível, não escondida pela agregação.

**Recomendação de governança**: este achado re-contextualiza uma entrada
já fechada do `evidence_ledger.yaml` sem alterá-la (append-only, nunca se
edita entrada fechada) — se confirmado, merece um `addendum_*` na entrada
`alpha-lightgbm-sweep-15-combinacoes-2026-08-23` apontando pra este
documento. Não fiz essa edição agora — é uma mudança de registro de
governança, fica pra você confirmar antes.

### 2.5 Confusão factual na auditoria externa: `min_data_in_leaf` "não aparece na tabela"

A auditoria externa (PDF) afirma que `min_data_in_leaf` não está
declarado, default da lib (20), "único parâmetro de regularização mais
importante em série financeira e o único que não está declarado nem
marcado `sweep_required`". **Isso está factualmente errado por uma
confusão de nomenclatura**: `min_child_samples` (que ESTÁ no espaço,
`constants.yaml::alpha_lgbm_min_child_samples`, `sweep_required: true`,
`sweep_range: [10, 100]`) É `min_data_in_leaf` — é o mesmo parâmetro do
LightGBM, só com o nome do wrapper scikit-learn (`LGBMClassifier`, que é
a API que `src/models/alpha.py` usa) em vez do nome nativo da API `lgb.
train()`. Não é uma lacuna nova.

**Mas o ponto substantivo por trás da confusão é válido e vale investigar**:
`[10, 100]` é uma faixa estreita pra 223 mil linhas (BTCUSDT/R1) com sinal
quase nulo — um piso de 10-20 amostras por folha, em dado essencialmente
ruído, é permissivo o bastante pra memorizar padrões espúrios. A sugestão
de considerar uma faixa mais alta (a auditoria externa cita 200-5000)
merece entrar como candidata pra Fase 1 (§4) — não como correção
factual do espaço atual (que já existe), mas como hipótese a testar.

### 2.6 Gaps reais, não contestados: `lambda_l1`, `min_gain_to_split`, `n_estimators` sem early stopping

Confirmado — nenhum dos três está declarado em `constants.yaml::
alpha_lgbm_*` (`lambda_l1` e `min_gain_to_split` ficam no default da
lib, ambos 0; `n_estimators=300` é fixo, sem early stopping, achado já
citado na docstring do módulo — "early stopping no fold" citado no PRD,
nunca implementado). **Não entram no espaço de busca desta rodada** —
abrir 3 dimensões novas sem justificativa medida seria o mesmo tipo de
scope creep que o resto deste documento está tentando conter. Registro
como candidatos de uma rodada FUTURA, condicionados a esta campanha
mostrar sinal real que justifique investir mais.

## 3. Contribuição da pesquisa web anterior (`design_doc §9.1/§9.2`) que sobrevive à síntese

- **BigQuery ML "≥10×dimensões"**: pra um espaço de 3 dimensões (`num_
  leaves`/`min_child_samples`/`subsample_freq`, com `max_depth` agora
  condicionando `num_leaves` em vez de ser uma 4ª dimensão livre) dá
  piso ≥30 — bate no meio da faixa 15-40 que as duas análises convergem.
- **LightGBM docs oficiais, exemplo numérico** (`max_depth=7→num_
  leaves=127 overfita, 70-80 é melhor`, ≈55-63% do teto): diretamente
  usado pela grade condicional da auditoria externa (nenhuma das opções
  de `num_leaves` fica sempre no teto — `depth=4→{4,8,16}` inclui pontos
  bem abaixo de 16). Endosso esta grade por isso.
- **López de Prado (2018), lido na íntegra — nuance que nenhuma das duas
  análises de entrada usa**: a posição dele não é "não rode muitos
  trials", é "rode quantos forem úteis, MAS aplique a correção (DSR) de
  verdade no final, sem exceção". Isso não contradiz a cautela do
  usuário — reformula PRA ONDE o risco real está: não é o número de
  trials em si, é a disciplina de aplicar `dsr.py` no resultado final e
  aceitar um veredito negativo se for o que a matemática disser. O
  projeto já tem essa disciplina wired (`src/validation/dsr.py`,
  `N_lifetime` auditado) — o risco de processo é mais baixo do que "não
  deveríamos nem tentar".
- **Optuna `TPESampler.n_startup_trials=10`**: com o orçamento que as
  duas análises convergem (15-40/k), a MAIORIA do orçamento seria sorteio
  aleatório puro antes do TPE atuar de verdade — **em escala tão pequena,
  TPE não tem vantagem real sobre um grid enumerado à mão**. Ver §5.

## 4. Plano final — 3 fases, gate obrigatório entre cada uma

### Fase 0 — Diagnóstico de ruído (NOVA, contribuição do usuário — é o achado mais valioso das duas análises)

Refinado após revisão detalhada do usuário (2026-08-24) + 1 achado da
varredura crítica final que nenhuma das análises anteriores capturou.

**0a — repetição de seed.** 10 execuções, `k=7` (T1 atual), hiperparâmetro
PROD travado, só varia `seed` (LightGBM + sub-split de calibração) →
σ do `directional_sharpe` pooled (mesma definição de `alpha_sharpe_
headline` em `src/models/pipeline.py:661` — média dos Sharpe por path, não
uma nova métrica). **Zero mudança de código** — `run_all_folds(seed=i)`
já aceita isto.

**0b — nulo por permutação de rótulo.** Desenho final, incorporando as 5
qualificações do usuário + 1 achado próprio:

1. Permuta só o TREINO, teste real preservado (confirma a leitura
   original — treino+teste juntos destruiria a estrutura de retorno do
   lado de teste e mediria a variância de um backtest sintético).
2. **Camada0 recebe a MESMA permutação que a Camada1** — senão o nulo
   testado vira "C1 é lixo, C0 é real" (hipótese alternativa), não "as
   duas são equivalentes" (a hipótese nula que o gate precisa).
3. Permutação DEPOIS do split, dentro do bloco de treino de CADA um dos
   15 splits, independente por split — nunca embaralhar antes do split
   (vaza estrutura entre folds, quebra o purge).
4. Permutação POR LADO, separadamente (`train_long`/`train_short` já são
   sub-populações diferentes) — preserva a taxa-base de cada lado, o que
   mantém `scale_pos_weight` (calculado por fold a partir do
   desbalanceamento real) consistente com o run real; só o pareamento
   X↔y é destruído.
5. `tau` não é permutado — vem de `target_signal_rate` fixado in-fold a
   priori, já intocado por construção.

**Achado da varredura final, não estava em nenhuma das duas análises de
entrada**: permutar só `label` não basta. `monotonic.
screen_monotone_constraints` (chamado dentro de `fit_side_model` pra
Camada1) deriva a direção de cada restrição monotônica de `ret_net`
(`target_col` default), NÃO de `label`. Se só `label` for embaralhado e
`ret_net` ficar intacto, a Camada1 continua recebendo `monotone_
constraints` calculados sobre o retorno ECONÔMICO REAL — o nulo fica
contaminado, a Camada1 "trapaceia" com informação genuína mesmo treinada
sobre rótulo de classificação puro ruído. **Correção: `label` e
`ret_net` são permutados JUNTOS, com o MESMO índice de permutação por
linha** (preserva a relação real label↔ret_net daquela linha, quebra só
a relação de ambos com as features `X`). `sample_weight` NÃO é
permutado — reflete unicidade/sobreposição temporal de `t1`, propriedade
estrutural do label, não do resultado econômico, ortogonal ao que o
nulo está testando.

**Implementação**: como a permutação precisa ser por-split E por-lado
(pontos 3-4), e `fit_side_model` já recebe `train_side_df` PÓS-split/
PÓS-`side_subset`, o ponto de injeção certo é dentro de `fit_side_model`
— um parâmetro novo aditivo (`null_permutation_seed: int | None = None`,
default preserva produção bit-exato), aplicado logo antes de `y_all` ser
construído, permutando `label`+`ret_net` juntos via o mesmo índice.
`run_fold`/`run_all_folds` ganham o mesmo parâmetro, repassado como as
outras 6 extensões aditivas já feitas nesta sessão (`feature_ids`,
`device_type`, etc.) — deriva o seed real por (split, lado) via
`_derived_seed`, já existente. **3 arquivos tocados: `fit_side_model`,
`run_fold`, `run_all_folds`, todos em `src/models/alpha.py`** — mesmo
arquivo da extensão `feature_ids`, nenhum arquivo novo em `alpha.py`.

**Permutação i.i.d. na v1, não em blocos.** Bloco por `n_bars_held`
mediano (~7 barras, medido) seria mais correto (rótulo de barreira tem
`t1` sobreposto, autocorrelacionado em blocos — i.i.d. produz nulo mais
estreito que o real, limiar otimista) — mas fica pra v2 SE o resultado
da v1 for ambíguo (perto de fronteira de decisão). v1 reporta o `n_bars_
held` mediano medido junto do resultado, pra "isto é um piso, não a
resposta final" ser quantificado, não só uma ressalva em texto.

**Réplicas: 50, não 20** — revisado a pedido do usuário. Com 20, a
resolução (1/20=5%) fica bem no ponto onde um limiar de α=0,05 precisa
de precisão; 50 dá 1/50=2%. Se o resultado sair perto de uma fronteira
de decisão, escalar pra 100 antes de fechar o limiar — reportar como
intervalo, não como valor único com falsa precisão.

| experimento | trials | saída |
|---|---|---|
| 0a | 10 | σ do Sharpe pooled |
| 0b | 50 | distribuição empírica de `n_better` sob nulo verdadeiro (Camada1 E Camada0 permutadas), com a correlação real entre os 5 paths embutida — não assume Binomial |

**Custo: 60 trials. `N_lifetime` 96 → 156.**

**Medido de verdade em 2026-08-24** (`src/validation/noise_floor_
diagnostics.py --probe-only`, ETHUSDT/R1, dado real): **~29s por execução
completa (15 splits × 2 lados = 30 fits)** — bem mais rápido que o ~2min
que eu vinha citando com ressalva (aquele número era de docstring de
teste unitário, sintético). Fase 0 inteira (60 execuções) estimada em
~29 min, não ~1h.

**Achado de infraestrutura, não de código**: o LightGBM instalado no
ambiente real não tem suporte CUDA compilado
(`lightgbm.basic.LightGBMError: CUDA Tree Learner was not enabled in
this build`) — `device_type="cuda"` (produção, D-18) falha aqui. Fase 0
rodou em `device_type="cpu"` (~29s/execução é rápido o bastante que isso
não importa pro diagnóstico) — mas isso bloqueia qualquer FUTURO retreino
de produção real neste mesmo ambiente até o LightGBM ser recompilado
com `-DUSE_CUDA=1`/`-DUSE_ROCM=1`. Fora do escopo de Fase 0 corrigir
agora, registrado aqui pra não ser esquecido antes de qualquer Fase 1/2
que planeje usar GPU de verdade.

### Resultado real (2026-08-24) — ETHUSDT/R1, 60/60 execuções completas

`audit/n_lifetime.yaml` id 20, `experiments/noise_floor_diagnostics_
ETHUSDT_R1.json`. Achado de implementação real, corrigido no processo:
`orjson` exige chave de dict `str`, `backtest_by_path` devolve
`dict[int, float]` — só quebrou na escrita final do artefato, o compute
das 60 execuções já tinha terminado certo (corrigido em `_pooled_sharpe`,
resultado recuperado do log estruturado, não perdido).

**0a — σ do ruído puro de seed**: `pooled_sharpe` mean=-1,3658,
**std=0,3060** (n=10, k/hiperparâmetro travados, só `seed` varia). Este é
o número que faltava pra calibrar qualquer comparação futura: uma
diferença de Sharpe entre duas configurações (k ou hiperparâmetro) menor
que ~0,3 é indistinguível do ruído de execução puro — não é
hiperparâmetro nem k fazendo diferença, é sorte de seed. Qualquer
resultado de Fase 1/2 precisa ser lido contra este piso.

**0b — nulo calibrado, não Binomial assumido**: distribuição empírica de
`n_better` sob nulo verdadeiro (Camada1 E Camada0 treinadas sobre o MESMO
`label`+`ret_net` permutados, 5 paths do CPCV com a correlação real
embutida): `{0:1, 1:13, 2:21, 3:10, 4:4, 5:1}` (n=50), média=**2,12** —
**abaixo** do 2,5 que `Binomial(5;0,5)` preveria. Achado novo, não estava
em nenhuma das duas análises de entrada: sob ruído puro, a Camada1 (com
`monotone_constraints`) tende a perder MAIS que 50% das vezes contra a
Camada0 (sem restrição) — a restrição monotônica custa algo mesmo quando
não há sinal pra ela capturar corretamente, não é neutra.

`P(n_better≥4 | nulo) = 5/50 = 0,10` — o limiar de produção atual
(`alpha_layer1_permanence_min_paths`) tem **falso-positivo medido de
~10%** nesta combinação específica (não os "5%" que um "α=0,05" informal
sugeriria, mas também não indefensável).

**Achado que muda a leitura de §2.4**: o resultado REAL de produção do
ETHUSDT/R1 (2026-08-23) foi **5/5**, não só ≥4/5. Sob o nulo calibrado
aqui, `P(n_better=5) = 1/50 = 0,02` — **mais extremo que o limiar do gate
sozinho sugeria**. A leitura agregada "3/15 é ruído" (teste binomial,
§2.4) continua correta PARA O AGREGADO das 15 combinações — mas,
especificamente pro ETHUSDT/R1, o resultado real é mais raro sob o nulo
verdadeiro (2%) do que um Binomial ingênuo teria sugerido, evidência
individual mais forte de sinal real nesta combinação do que a leitura
agregada capturava sozinha. Ressalva: este nulo foi calibrado só pra
ETHUSDT/R1 — SOLUSDT/R2 e SOLUSDT/R3 (os outros 2 "passa" do sweep
original, ambos 4/5) precisariam da MESMA calibração rodada neles pra
uma leitura equivalente, não medido ainda.

**Decisão de governança pendente**: registrar como `AG-NNN` (não editar
`constants.yaml` direto — 3 razões já registradas acima) com a
distribuição completa, os 2 achados (Camada1 perde mais sob nulo;
ETHUSDT/R1 é outlier real sob o nulo calibrado) e este p-valor. Decisão
do Manager.

**O que vai no `AG-NNN` de Fase 0b** (não decide sozinho — Manager
decide, motivo em §2.3 mais 3 razões do usuário: o limiar sai
condicionado a `k=7`/hiperparâmetro atual/composição de T1 — muda
quando Fase 1 mudar `k`, uma constante `DERIVED` escrita agora caducaria
na hora; o resultado provável não é "o limiar deveria ser N", é "nenhum
limiar sobre `n_better` separa sinal de ruído com 5 paths correlacionados"
— um critério diferente, não um número diferente; e mudar o gate de
permanência com base em experimento próprio é decisão de graus de
liberdade do projeto, exatamente o que `N_lifetime` existe pra contar,
auditável via `AG-NNN`, não uma edição direta em `constants.yaml`):
distribuição nula COMPLETA de `n_better` (não só o percentil escolhido),
número de réplicas, esquema de permutação (i.i.d. ou blocado), e o
p-valor do `3/15` observado (§2.4) contra essa distribuição — o número
mais informativo pro Manager, mais que o limiar em si.

**Extensão opcional, se custo permitir**: rodar o nulo também com
`n_test_groups` alternativo ou um subconjunto dos paths, pra separar
"quanto da largura da distribuição vem da correlação entre paths" —
responde se o problema é o limiar (4 é baixo demais) ou a estatística (5
paths correlacionados não sustentam nenhum limiar), e as duas conclusões
levam a ações diferentes na Fase 1.

### Fase 1 — Mapa de capacidade (auditoria externa, com a correção de §2.1)

Só roda se Fase 0 não matar a hipótese. Grid enumerado, não Optuna — na
escala orçada (§3), TPE não tem vantagem. 1 ativo de referência (ETHUSDT/
R1, mesmo escolhido antes), demais hiperparâmetros travados em PROD:

| `max_depth` | `num_leaves` testados | qtd |
|---|---|---|
| 2 | {2, 4} | 2 |
| 3 | {4, 8} | 2 |
| 4 | {4, 8, 16} | 3 |
| 5 | {8, 16, 32} | 3 |
| 6 | {8, 16, 32} | 3 |

13 pares (depth, leaves) × 5 valores de `k` (6,9,12,16,24) = **65
trials**. `N_lifetime` 156 → 221. Objetivo: existe relação
`k`↔capacidade consistente (ex. "k=6 melhor em depth 2-3, k=24 instável em
qualquer depth")? Não é achar "o melhor modelo".

`min_child_samples`: 1 ponto adicional testado nesta fase, no valor mais
alto sugerido em §2.5 (ex. 200) contra o valor de produção (20), SÓ na
combinação (k, depth, leaves) que sair melhor do grid acima — não
multiplica a grade inteira por 2. +1 trial. **Total Fase 1: 66 trials,
`N_lifetime` 156 → 222.**

### Fase 2 — Busca dirigida (condicional — só se Fase 0 E Fase 1 mostrarem sinal real)

Se a Fase 1 apontar uma região (k, depth, leaves) consistentemente
melhor: refinar ao redor dela, grid pequeno ou Optuna (decisão adiada
pra quando os dados da Fase 1 existirem — não vale a pena decidir o
sampler antes de saber se o espaço tem alguma estrutura pra explorar).
`N_trials_per_k`: **15-25**, faixa onde as duas análises convergem,
justificada pelo hurdle marginal real (~19%, §2.2, não ~65%).

- Seleção final: **mediana dos top-5 trials**, nunca o melhor isolado
  (recomendação da auditoria externa, adotada — protege contra exatamente
  o tipo de sorte-de-busca que o hurdle do DSR está cobrando).
- Artefato guarda TODO trial: `k`, `max_depth`, `num_leaves`, Sharpe
  pooled + Sharpe por path (1-5) + `ret_net` + `max_drawdown` + `n_better`
  — não só o vencedor (recomendação da auditoria externa, adotada).
- PBO/DSR calculados pós-hoc sobre a população completa, nunca como alvo
  do sampler.
- Escopo (1 ativo vs. matriz completa): decidido pelo resultado da Fase
  1, não pré-comprometido aqui.

**Regra de parada, endossada de ambas as análises**: se nenhuma região de
`(k, depth, leaves)` mostrar melhora econômica consistente até o fim da
Fase 1, **não escala pra Fase 2**. Próximo investimento vai pra
diagnóstico de alpha/features/label (a lista de 10 hipóteses da auditoria
externa), não pra mais busca.

## 5. O que isso muda no design doc original

- §5.3 (busca aninhada via `Optuna GridSampler`, 24 combos/k) —
  **superseded**. Otimização real fica adiada até Fase 1 justificar.
- §9.2 (grade de 24 combos, `N_lifetime` 96→216 só na Fase A) —
  **substituída** pelo plano de 3 fases acima (Fase 0+1 = 126 trials,
  bem mais barato, com 2 gates de decisão em vez de 1 commit único).
- `feature_ids` parametrizável em `alpha.py` (§5.2, já implementado e
  testado nesta sessão) — **continua válido e é pré-requisito de Fase 1**
  (varia `k`); Fase 0 não precisa dele (roda em `k=7` fixo).
- **Nova extensão pendente em `alpha.py`, achado da refinação de Fase
  0b**: `null_permutation_seed: int | None = None`, aditivo, mesmo
  padrão das 7 extensões já feitas (`feature_ids` incluída) — thread por
  `fit_side_model`/`run_fold`/`run_all_folds`, permuta `label`+`ret_net`
  juntos (mesmo índice) dentro de `train_side_df` antes de `y_all`/
  screening de monotonicidade. Único pré-requisito de código pra Fase 0b
  — Fase 0a não precisa de nada novo.
- Optuna: fica em aberto se será wired de verdade — na escala orçada
  aqui, um grid enumerado resolve sem a dívida de engenharia de uma
  dependência nova nunca usada no repo. Decisão adiada pra Fase 2, se
  ela existir.
