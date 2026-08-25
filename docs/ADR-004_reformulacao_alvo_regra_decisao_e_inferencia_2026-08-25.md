# ADR-004 — Reformulação do alvo, da regra de decisão e da inferência do Alpha

**Data:** 2026-08-25
**Status:** PROPOSTO — nenhuma implementação feita, nenhum default alterado
**Escopo:** raiz matemática de `AG-210`, `AG-211`, `AG-212`, `AG-213`, `AG-214`
**Origem:** auditoria da persona `lgbm-crypto-quant` sobre `src/models/alpha.py`
e árvore, instrumentada em `AG-208`..`AG-218` e medida em
`experiments/alpha_layer1_report_ag208_217_diag.json`
(2026-08-25, BTCUSDT/R1, defaults legados)

---

## §0. Correção prévia: o dado refutou meu primeiro argumento

Este ADR ia se apoiar na tese de que o alvo binário `y = 1{barrier == TP}`
desalinha de `E[ret_net]` porque **ignora os desfechos `TIME`** — a
decomposição sendo

```
E[r | x,s] = P(TP)·(+τ_tp·σ) + P(SL)·(−τ_sl·σ) + P(TIME)·E[r | TIME] − c
```

e `P(TIME)` supostamente material. Antes de escrever, medi
`data/label_engine_runs/label_engine_runs.parquet`:

| combinação | `pct_tp` | `pct_sl` | `pct_time` | `pct_nofill` |
|---|---|---|---|---|
| BTCUSDT / **R1** | 0,4022 | 0,4898 | **0,0008** | 0,1073 |
| SOLUSDT / R1 | 0,4184 | 0,4947 | 0,0005 | 0,0864 |
| XRPUSDT / R1 | 0,4172 | 0,5032 | 0,0006 | 0,0790 |

**`P(TIME) ≈ 0,08%` sob a grade de produção.** A barreira vertical
praticamente nunca é atingida — `time_stop_ms` de 8h é longo demais frente
à velocidade das dollar bars R1. Com `τ_tp = τ_sl = 1,5` (payoff
simétrico), o terceiro termo é desprezível e **maximizar `P(TP)` é, em
ordenação, quase idêntico a maximizar `E[r]`**.

O argumento morre. O que segue é construído só sobre o que o dado sustenta
— e o mesmo dado entrega três fatos que sustentam uma tese diferente e
mais forte.

---

## §1. Os três fatos que o dado entrega

**(F1) O problema é essencialmente binário e quase equiprovável.**
Excluindo NOFILL, BTCUSDT/R1 dá `P(TP) = 0,4022/0,8919 = 45,1%` contra
`P(SL) = 54,9%`. Com payoff 1:1 o break-even é 50%: **o edge bruto
incondicional é `(0,451 − 0,549)·1,5 = −0,147 ATR`, antes de custo.**
Coerente com M6 (`edge_bruto_atr` negativo, `I² = 96,1%/97,8%`).

**(F2) `NOFILL` é 10,7% sob R1** — contra 2–4% na grade de relógio legada.
É exatamente a população que `AG-210(b)` identificou como divergente entre
treino (`side_subset` remove NOFILL) e inferência (`_unique_test_bars` não
remove). A divergência deixou de ser teórica: é uma barra em cada dez.

**(F3) ESS/linhas = 0,3707 global**, batendo com o 0,3645 medido por fold
(`AG-211`). 63% do `n` aparente é redundância.

---

## §2. A raiz: uma probabilidade não tem unidade de retorno

A regra de decisão que este projeto precisa satisfazer é econômica:

- **R2** — custo round-trip ≤ `cost_stop_ratio_max` × stop
- **R3** — fees mensais ≤ `fee_budget_monthly` × equity

As duas são condições sobre **retorno em unidades monetárias**. O estimador
produz `p ∈ [0,1]`, **adimensional**. Não existe forma de escrever
`p > custo` — as unidades não fecham.

É por isso, e só por isso, que `τ` precisa ser calibrado por **quantil**
(`np.quantile(p, 1 − target_signal_rate)`): o quantil é um *proxy* que
força a taxa de sinal a bater um orçamento, sem nunca comparar edge contra
custo. E é exatamente aí que `AG-210` nasce — o proxy é aplicado por lado
sobre populações diferentes, e a taxa total medida deu **3,31% contra
1,89% orçado (1,75×)**, com R3 violada.

Reformular o alvo em unidade de retorno não é preferência de estilo: é a
condição necessária para que R2 e R3 possam ser impostas **por construção**
em vez de por calibração.

**Nota sobre `AG-213`:** as restrições monotônicas divergem entre os dois
alvos (2 de 6 features não-forçadas no lado long, medido). A explicação
correta — dado que `TIME ≈ 0` — não é a barreira vertical, é o **custo
variável**: `1{TP}` é uma função monótona de `ret_net` apenas se o custo
for constante. Não é — `E27f_cost_atr_ratio` está no vetor de features
justamente porque varia. Um TP marginal sob custo alto tem `ret_net < 0`.
Os dois alvos divergem precisamente nas barras de custo alto, que são as
que decidem R2.

---

## §3. Solução 1 — alvo em unidade de retorno (`AG-212`, `AG-213`)

Estimar diretamente

```
μ(x, s) = E[ ret_net | x, s ] / σ_t
```

normalizado por volatilidade (a normalização já existe implicitamente nas
barreiras em múltiplos de ATR; explicitá-la no alvo evita que o modelo
gaste capacidade aprendendo volatilidade, que é previsível, em vez de
direção, que não é).

**Estimador:** LightGBM `objective="huber"` ou `"quantile"` — cauda pesada
de cripto torna L2 dominado por outliers. Um regressor por lado.
**Isto não viola B18**: a proibição é de `multi:softprob`/`multiclass`, não
de regressão. Continuam dois modelos, `M_long` e `M_short`.

**Consequências em cascata — dois AGs fecham sem código próprio:**

- **`AG-213` fecha por construção.** `screen_monotone_constraints` já usa
  `target_col="ret_net"` por default. Com o treino no mesmo funcional,
  screening e treino passam a medir a mesma coisa. A divergência de 2/6
  deixa de existir porque deixa de haver dois alvos.
- **`AG-212` fecha por construção.** Sem classe não há `scale_pos_weight`
  (o desalinhamento medido de 1,3519 desaparece), e `|ret_net|` sai do peso
  amostral — vira o alvo. Sobra `sample_weight = uniqueness`, que é o que
  AFML cap. 4 de fato prescreve para redundância. Ponderar um classificador
  por `|y|` é uma forma indireta e enviesada de fazer a regressão que se
  deveria estar fazendo diretamente.

**Custo:** 1 retreino. **Risco:** regressão em sinal fraco tem R² próximo
de zero e pode ser numericamente pior que classificação; mitigação é medir
IC de Spearman (ranking), não R².

---

## §4. Solução 2 — a regra de decisão como problema de orçamento (`AG-210`)

Com `μ` em unidade de retorno, a decisão vira um programa explícito:

```
max_{s}   Σ_t s_t · μ_t
s.a.      Σ_t |s_t| ≤ B          (orçamento de trades — R3)
          s_t ∈ {−1, 0, +1}
```

O relaxamento lagrangiano `L = Σ_t [ s_t·μ_t − λ|s_t| ]` é separável por
`t`, e a solução pontual é imediata:

```
s*_t = sign(μ_t) · 1{ |μ_t| > λ }
```

**Uma única fronteira, em `μ`.** Três consequências estruturais:

1. **A regra de desempate `p_long > p_short` desaparece.** `sign(μ_t)`
   decide o lado por construção. Hoje o desempate é uma heurística
   acoplada aos dois thresholds, e é parte do que torna a taxa total
   não-analítica (é por isso que `resolve_joint_tau` precisa de bisseção).
2. **`λ` é o preço-sombra do orçamento de fees** — o edge mínimo exigido
   por trade, em unidade de retorno. Passa a ser auditável e comparável
   com o custo.
3. **`λ` deveria ser derivado, não calibrado.** A condição de participação
   econômica é `|μ_t| > c_t`, com `c_t` o custo round-trip medido. Então

   ```
   λ_t = max( c_t , λ_B )
   ```

   onde `λ_B` é o multiplicador que satura o orçamento. Se `λ_B > c_t`, o
   binding constraint é o orçamento de fees; se `c_t > λ_B`, é o custo. **R2
   e R3 viram uma condição só**, em vez de duas restrições checadas
   separadamente em lugares diferentes do pipeline.

**Referências:** Grinold & Kahn (transfer coefficient sob restrição);
Gârleanu & Pedersen (2013), *Dynamic Trading with Predictable Returns and
Transaction Costs*, para a versão dinâmica com custo quadrático e
aversão a risco — o caso em que `λ` deixa de ser escalar e vira função do
estado (posição atual, previsão de decaimento do sinal).

### §4.1 — Evidência empírica: o instrumento foi caracterizado, não a variante

**Adicionado 2026-08-25, após o experimento pareado de 3 braços
(`AG-220` + addendum, `evidence_ledger::alpha-tau-calibracao-experimento-
pareado-3-bracos-2026-08-25`).** Este parágrafo foi escrito DEPOIS do
resto do ADR e muda o status do §4: de proposta com argumento dimensional
para a única saída com suporte empírico.

Três rodadas reais BTCUSDT/R1, pareadas de forma estrita (mesmo seed,
mesmo desenho de modelo, mesmas features, mesma janela, mesmos 15 splits),
variando **apenas** onde e como o quantil de `p` é tirado:

| braço | `tau_policy` | `calib_split_mode` | taxa de sinal | vs. orçamento 1,89% | `permanence_pass` |
|---|---|---|---|---|---|
| A | `legacy_per_side` | `legacy_random` | 3,315% | 1,75× | false |
| B | `total_common_oof` | `legacy_random` | 3,157% | 1,67× | **true** |
| C | `total_common_oof` | `temporal_purged` | **6,687%** | **3,54×** | false |

Nenhum braço entrega R3. Corrigir escopo e população do quantil (A→B)
moveu **0,16 ponto percentual**; adicionar a calibração purgada (B→C)
**dobrou** a taxa em vez de reduzi-la.

Em **todos os três**, `|Δ| < σ` entre caminhos (0,72<0,83 ; 0,81<1,12 ;
0,10<1,09) — o gate §5.11 nunca teve poder estatístico neste dataset. E o
veredito oscilou `false → true → false` governado só por escolhas de
calibração que não mudam modelo, features nem dado.

**A leitura correta é sobre o instrumento, não sobre a variante.** Três
formas de escolher o quantil produziram 3,16% a 6,69% sobre o mesmo alvo
de 1,89%. Quantis de probabilidade não transferem entre treino e teste sob
não-estacionariedade: o solver acerta o alvo *in-sample* por construção e a
taxa OOS não segue. A fronteira `|μ| > λ` proposta acima não tem essa
fragilidade porque não depende da distribuição de `p` ser estável — depende
de `μ` e `c` estarem na mesma unidade, que é uma propriedade de construção,
não uma hipótese estatística.

**Autocrítica registrada:** as duas correções testadas nos braços B e C
(`AG-209` e `AG-210`) foram propostas e implementadas nesta mesma
investigação. Ativadas isoladamente, **pioraram** a métrica que deveriam
melhorar. Os dois diagnósticos seguem corretos — o sub-split aleatório
vaza informação para o calibrador, e o quantil por lado contradiz
`fee_budget_is_per_side=false`. O que o experimento mostra é que **corrigir
dois defeitos de um instrumento errado não o torna certo.**

**Recomendação operacional:** não varrer mais variantes de calibração de
`tau`. O instrumento está caracterizado por três pontos; mais pontos gastam
`N_lifetime` sem informação nova. Ir direto para a Fase 1+2 do §7.

**Custo:** grátis, dentro da Solução 1. `decide_side`/`resolve_joint_tau`
(já implementados em `AG-210`) viram o caso degenerado desta formulação em
espaço de `p`.

---

## §5. Solução 3 — ESS composto e inferência sem `n` (`AG-211`, `AG-216`)

`Σ uniqueness` (AFML cap. 4) corrige **uma** fonte de dependência:
sobreposição de rótulo. Faltam duas.

| fonte | instrumento | estado no repo |
|---|---|---|
| sobreposição de rótulo | `Σ uniqueness` | ✅ medido (0,3707) |
| dependência serial residual | `n_eff = n / (1 + 2Σ_k ρ_k w_k)` (Newey-West / Kiefer-Vogelsang) | ❌ ausente |
| dependência transversal (5 ativos) | `n_eff = (Σλ)² / Σλ²` sobre a correlação entre símbolos | ❌ ausente (`AG-216`) — **mas a função existe**: `hhi.compute_effective_concentration` é exatamente esse participation ratio, hoje aplicado a features. Reusar, não reescrever. |

**A saída moderna, porém, é não corrigir `n`.** Um ESS escalar assume uma
forma de dependência. O padrão robusto é **bootstrap por blocos
estacionário** (Politis & Romano, 1994) com comprimento de bloco escolhido
automaticamente por Politis & White (2004): produz intervalo de confiança
direto para qualquer estatística (Sharpe, ΔSharpe, IC) sob dependência de
forma desconhecida, sem precisar declarar um `n_eff`.

O ESS continua valendo como **número de comunicação** ("36% do `n`
aparente" é o choque útil que faltava no relatório) — mas não deve ser o
insumo do teste.

---

## §6. Solução 4 — comparar duas estratégias com o instrumento certo (`AG-214`)

O critério atual conta vitórias em 5 caminhos que reconstroem o **mesmo**
dataset. É um teste de sinal com `n` efetivo ≈ 1, e com empate exato
contando a favor da Camada 1.

| pergunta | instrumento correto | estado |
|---|---|---|
| "C1 é melhor que C0?" | **Ledoit & Wolf (2008)**, teste robusto para *diferença* de Sharpe com retornos autocorrelacionados e não-normais (HAC + bootstrap por blocos) | ❌ ausente |
| "este Sharpe sobrevive ao número de tentativas?" | **DSR** (Bailey & López de Prado) | ✅ existe, agora wireado (`AG-215`), falta `N_lifetime` |
| "o ranking in-sample se sustenta OOS?" | **PBO via CSCV** (Bailey et al., 2017) | ❌ ausente |

**A definição operacional de "empate" deixa de ser um limiar inventado.**
A regra passa a ser: *o IC de 95% da diferença exclui zero*. Isso resolve
o que `AG-214` deixou deliberadamente em aberto (B23 — deixei
`min_margin` sem default por não haver base para estipular um número).

Com os valores medidos — `Δ = −0,7208`, `σ_entre_caminhos ≈ 0,83`, 5
caminhos não-independentes — o IC quase certamente contém zero. O veredito
correto é **indeterminado**, que é diferente do `permanence_pass = false`
que o relatório emite hoje e que se lê como um veredito.

---

## §7. Ordem de implementação, por custo crescente

| fase | o que | custo | fecha |
|---|---|---|---|
| **0** | Bootstrap por blocos + Ledoit-Wolf sobre os `ret_net` **já materializados** | zero retreino | responde "a diferença C1/C0 é real?" hoje |
| **1** | Alvo `μ` (regressão Huber/quantile) | 1 retreino | `AG-212`, `AG-213` |
| **2** | Regra lagrangiana `s = sign(μ)·1{|μ|>λ}`, `λ = max(c, λ_B)` | grátis (dentro da 1) | `AG-210`, unifica R2+R3 |
| **3** | ESS composto (serial + transversal) e PBO/CSCV | baixo | `AG-211`, `AG-216`, completa `AG-214` |

A Fase 0 é a que dá mais informação por unidade de custo e **não consome
`N_lifetime`** — não há ajuste de modelo novo, só inferência sobre
resultado já materializado.

---

## §8. O que isto explicitamente NÃO resolve

> **REVISADO 2026-08-25 — `AG-221`.** A afirmação original desta seção
> usava o número `−0,147 ATR` como se fosse propriedade do mercado.
> **Metade dele é artefato de instrumento.** `t_post = t0` é o `close_time`
> da dollar bar (instante arbitrário) e `simulate_fill_arrays` só oferece
> oportunidade de fill em minutos cheios de `mark_1m` — o que cria uma
> espera sintética uniformemente distribuída em `[0, 60s]` que **não
> existe em produção**. O edge bruto é função monotônica dessa espera
> (`−2,64 bps` na faixa 0–10s → `−6,94 bps` na faixa 50–60s, com `n`
> idêntico em cada faixa, confirmando fase de relógio). Extrapolando para
> `delay = 0`: **`≈ −2,2 bps`**, não `−4,4`.
> Ver `AG-221` para a cadeia completa de evidência e a correção proposta
> (usar `agg_trades`, que o repo já baixa, como fonte do fill de entrada).

> **ADENDO 2026-08-25 (segunda revisão) — os dois números deste parágrafo
> foram MEDIDOS desde que ele foi escrito, e ambos mudaram.**
>
> **1. O `−2,2 bps` era extrapolação; agora há medição.** Aquele valor veio
> de extrapolar a curva edge×latência para `delay = 0`. O relabel completo
> de produção (`AG-229`: 15 combinações, 998s, `entry_fill_source =
> agg_trades`) substituiu a extrapolação por medição direta. O que se mediu:
> `P(TP)` foi de 0,4505–0,4768 para **0,4917–0,4969** — todas as 15
> combinações dentro de 0,83pp do 0,50 que a martingale prevê para barreiras
> simétricas, que é o valor TEORICAMENTE correto —, e o gap edge-custo caiu
> de 10,50 para **6,10 bps (−41,9%)**. Ou seja: a direção do argumento
> estava certa, a magnitude não era conhecida. Grupo de controle preservado
> (as 5 combinações de grade 15m ficaram em `mark_1m` por desenho e saíram
> bit-idênticas), o que separa "o relabel mudou o número" de "o dado mudou
> sozinho".
>
> **2. O `I² = 96–98%` estava medido na grade ERRADA.** O M6 lia a grade de
> relógio 15m, substituída como canônica desde `AG-042`. Re-executado nas
> três resoluções de produção (`AG-238`), o `I²` real é **61–83%**, e cai
> monotonicamente com a duração da barra (15m ~93–97 > R1 61–83 > R3 ~66).
> O fator comum **segue rejeitado** em todas as células (p<0,05), então a
> conclusão qualitativa deste parágrafo sobrevive — mas a FORÇA da evidência
> não: em R1 SHORT o p-valor vai de 7e-30 para **3,8e-02**. Citar
> "`I² = 96–98%`" como suporte de escopo multi-ativo virou overclaim.
>
> **3. Achado que este ADR não podia conhecer: a leitura por lado INVERTE.**
> Na grade 15m o SHORT era o lado de edge pooled ~nulo (`−0,000906`) e o
> LONG o pior (`−0,032765`). Na grade de produção é o oposto nas três
> resoluções: SHORT é o pior. Qualquer raciocínio deste ADR que trate os
> dois lados como simétricos, ou que use o SHORT como referência neutra,
> precisa ser relido.
>
> **O que NÃO muda:** o edge bruto corrigido continua negativo contra o
> custo, e o argumento central do §8 — "nada aqui cria edge; o valor destas
> reformulações é diagnóstico" — fica INTACTO. O gap a vencer é menor do que
> se pensava, não inexistente.

Com essa correção incorporada: nada aqui cria edge. O edge bruto
incondicional **corrigido** é da ordem de `−2,2 bps` contra `≈ 5,6 bps` de
custo explícito medido — continua negativo, e M6 rejeitou fator comum com
`I² = 96–98%`. Um estimador melhor e uma fronteira melhor não mudam isso.
O que muda é a **magnitude do gap a vencer**, que estava sendo reportada
com o dobro do tamanho real.

O valor destas reformulações é **diagnóstico**: hoje, um resultado negativo
é ambíguo — pode ser o alvo em unidade errada, pode ser o threshold
calibrado por proxy sobre a população errada, pode ser ausência de sinal.
Com o alvo em unidade de retorno e a fronteira derivada do custo, um
resultado negativo passa a ser **informativo**: significa que o sinal não
existe, e isso é uma conclusão que se pode levar ao Manager com
convicção — que é, pela ordem de prioridade declarada no `CLAUDE.md`,
mais valioso do que continuar otimizando.

---

## §9. Decisões que este ADR NÃO toma

- Não altera nenhum default. Tudo em `AG-208`..`AG-215` continua opt-in.
- Não decide se o alvo muda — isso é decisão de desenho do Manager, e
  implica reprocessar as 15 combinações.
- Não fixa `λ`, `B`, nem comprimento de bloco: todos são **medidos**, não
  estipulados (B23).
- Não reabre `time_stop_ms`, embora `P(TIME) = 0,08%` sob R1 sugira que a
  barreira vertical está inativa na prática — achado colateral desta
  investigação, registrado aqui e merecedor de item próprio.
