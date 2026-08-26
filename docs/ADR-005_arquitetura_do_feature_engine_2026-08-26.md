# ADR-005 — Arquitetura do Feature Engine: estratificar por função e por evidência

**Data:** 2026-08-26
**Status:** PROPOSTO — nenhuma implementação feita, nenhum default alterado, nenhuma coluna removida
**Escopo:** desenho do vetor de features (`src/features/`), fronteira com o gate de regime e com o vetor de treino do Alpha
**Origem:** persona `feature-thesis-auditor`, instrumentada em `AG-260` (régua econômica), `AG-263` (ficha de tese das 72 colunas), `AG-264` (barras degeneradas), `AG-265` (curva de IC por horizonte)
**Evidência:** `experiments/ic_by_horizon_report_{R1,R2,R3}.json` (15 células, 2022-01-01..2026-08-07), `audit/feature_thesis/fichas_69_2026-08-25.yaml`, `config/min_alpha_lift_by_combo.yaml`

---

## §0. Correção prévia: um erro meu que quase virou achado

A primeira versão de `ic_by_horizon.py` calculava o erro do IC como o desvio
entre fases de amostragem dividido por `sqrt(h)`. Produzia `|t| ≈ 85` para
`IC = 0,04` e apontava **65 das 72 colunas** como significativas.

Está errado, e do lado perigoso. As `h` subamostras disjuntas cobrem o
**mesmo período de calendário**, apenas em fases diferentes — são redundantes
entre si, e o desvio entre elas mede variação de fase, não incerteza
estatística. Corrigido para o erro de uma subamostra disjunta, o número caiu
de 65 para 8 numa célula.

Registro isso primeiro porque a conclusão deste ADR depende inteiramente de o
erro estar certo, e porque a versão errada teria produzido a recomendação
oposta: "o vetor está cheio de sinal".

---

## §1. Contexto — os quatro fatos medidos

**§1.1 A régua econômica (`AG-260`).** Para o motor apenas empatar, o Alpha
precisa entregar lift em `P(TP)` entre **1,076 e 1,175**, conforme a célula.
Não é meta de Sharpe: é o ponto onde o retorno bruto cobre o custo
round-trip. O gate de regime hoje mede lift `1,0027` (`AG-244`) e as dez
medianas do `ADR-003` são negativas.

**§1.2 A ficha de tese (`AG-263`).** Das 72 colunas do vetor (T1 + T2
promovidas por `AG-207`), **33 não têm nenhum mecanismo econômico declarado**
— nem no registry, nem em docstring, nem em `constants.yaml`. A única
justificativa disponível é "indicador clássico".

**§1.3 A curva de IC (`AG-265`, estendida aqui para as 15 células).** Medida
sobre 2022-01-01..2026-08-07, horizontes `h = 1,2,4,8,16,32` barras, holding
medido `H = 5` barras. Descobertas por Benjamini-Hochberg `q = 0,10` dentro
de cada célula:

| feature | células | R1 [B E S N X] | R2 [B E S N X] | R3 [B E S N X] |
|---|---|---|---|---|
| `E18f_taker_ls_vol_ratio` | **15/15** | `XXXXX` | `XXXXX` | `XXXXX` |
| `E16f_global_ls_ratio` | **7/15** | `X.XX.` | `X.X..` | `X.X..` |
| `K04_session_us` | 5/15 | `...XX` | `...XX` | `....X` |
| `C09_range_pctile_expanding` | 5/15 | `...XX` | `...XX` | `....X` |
| `A11_true_range_pct` | 5/15 | `...XX` | `...XX` | `....X` |
| `E12f_price_oi_divergence` | 4/15 | `X...X` | `..X.X` | `.....` |

**§1.4 O limiar não é escolhido, é calibrado.** A taxa base de descoberta é
10,5 features por célula (de 72), ou seja `p = 0,146`. Sob binomial(15,
0,146), o número esperado de features que apareceriam em `≥ k` células **por
acaso**, entre 72:

| `k ≥` | esperado sob H₀ | observado |
|---|---|---|
| 3 | 27,3 | — |
| 5 | **4,05** | **5** |
| 6 | 1,08 | 2 |
| **7** | **0,22** | **2** |
| 15 | 3·10⁻¹³ | 1 |

As três features de 5/15 são **indistinguíveis de acaso** — esperava-se 4,05,
observou-se 5. O critério defensável é `k ≥ 7`, e exatamente duas features o
atravessam.

---

## §2. Decisão proposta

**Estratificar o Feature Engine em cinco camadas por FUNÇÃO, e governar a
entrada no vetor de treino por EVIDÊNCIA reproduzível entre células.**

Hoje existe uma lista plana de 72 colunas: todas calculadas sempre, todas
entregues ao Alpha, nenhuma com papel declarado, e a distinção `T1_FEATURE_IDS`
vs `SUPPORT_FEATURE_IDS` não corresponde a nenhuma fronteira real — `E27f` é
T1 e alimenta o gate de regime; `C01`/`C02` são primitivas de cálculo e estão
no vetor; `B07`/`C07`/`E02f` são T2 e são o insumo do classificador.

### As cinco camadas

| Camada | O que é | Vai ao Alpha? | Membros hoje |
|---|---|---|---|
| **L0 — Primitiva** | insumo de cálculo de outras colunas | **não** | `C01_atr_20`, `C02_atr_20_pct` (`atr_20_abs` usado em 10 pontos, `atr_20_pct` em 7) |
| **L1 — Gate de regime** | consumido por `classifier.py` | **não** (ADR-001 §2.7) | `B07`, `C07`, `E02f`, `E27f` |
| **L2 — Núcleo de sinal** | evidência em `≥ 7/15` células | **sim** | `E18f` (15/15), `E16f` (7/15) |
| **L3 — Em observação** | tese declarada, sem sinal reproduzível | não, recalculada | as `TESE_OK` restantes (15) |
| **L4 — Aposentada** | sem mecanismo **e** sem sinal | não, **nem calculada** | as 29 `SEM_MECANISMO` sem descoberta |

A regra que torna isso operável: **`L2` é a única camada que entra no vetor de
treino, e a entrada em `L2` é por critério declarado a priori (`≥ 7/15`
células), não por importância `gain` nem por julgamento.**

---

## §3. Opções consideradas

### Opção A — Manter o vetor de 72 (status quo)

| Dimensão | Avaliação |
|---|---|
| Complexidade | Nenhuma (nada muda) |
| Custo | Alto e invisível: 72 colunas calculadas por barra em 15 células |
| Custo estatístico | Máximo — cada coluna é um grau de liberdade na seleção e pesa na deflação do DSR |
| Familiaridade | Total |

**Prós:** zero trabalho; preserva opcionalidade caso o IC esteja subestimando alguma coluna.
**Contras:** 29 colunas sem mecanismo e sem sinal continuam consumindo `N_lifetime`; a régua de `§1.1` exige lift de ~1,1 e não há evidência de que o conjunto o entregue; o vetor continua sem camada de contexto declarada.

### Opção B — Podar para as 2 com evidência (`L2` apenas)

| Dimensão | Avaliação |
|---|---|
| Complexidade | Baixa (é uma lista) |
| Custo | Mínimo |
| Custo estatístico | Mínimo — 2 graus de liberdade |
| Risco | Alto: 2 colunas é um vetor frágil; qualquer falha de fonte derruba o motor |

**Prós:** honesto com a evidência; corta a deflação drasticamente; torna o motor auditável de ponta a ponta.
**Contras:** descarta 15 colunas com tese declarada que podem ter sinal que este teste não detecta (o IC linear-monótono não captura interação nem condicionalidade); um vetor de 2 colunas dificilmente vence lift de 1,1.

### Opção C — Estratificar em 5 camadas, podar `L4`, manter `L3` calculada e fora do treino ✅

| Dimensão | Avaliação |
|---|---|
| Complexidade | Média — é uma mudança de contrato, não de cálculo |
| Custo | Reduz ~40% das colunas calculadas |
| Custo estatístico | Baixo — o vetor de treino cai de 72 para 2-4 |
| Reversibilidade | Alta: `L3` continua calculada, promover é mudar uma lista |

**Prós:** separa "não tem sinal detectável hoje" de "não deveria existir"; `L3` fica disponível para reteste sem custo de deflação; a fronteira `L0`/`L1` corrige uma confusão real de papéis que existe hoje.
**Contras:** exige mudar `T1_FEATURE_IDS`/`SUPPORT_FEATURE_IDS` e o contrato de `build_modeling_frame`; a promoção `L3 → L2` precisa de cadência declarada, senão vira porta dos fundos para mineração.

---

## §4. Trade-off central

A tensão real não é entre A e B — é entre **poder estatístico** e **cobertura
de mecanismo**.

Podar para `L2` maximiza o poder (2 graus de liberdade contra uma régua de
1,1) e minimiza a deflação, mas aposta tudo em duas fontes de derivativos: se
a Binance mudar o schema de `sum_taker_long_short_vol_ratio`, o motor fica
sem vetor. Manter as 72 preserva cobertura mas paga deflação sobre 70 colunas
das quais 29 comprovadamente não têm nem tese nem sinal.

A Opção C resolve a tensão movendo `L3` para fora do **vetor de treino** sem
tirá-la do **cálculo**: o custo estatístico é o do vetor, não o do pipeline.
Recalcular uma coluna é barato; treinar sobre ela não é.

Uma limitação que a Opção C não resolve e que precisa ficar dita: o IC de
Spearman mede relação monótona marginal. Uma feature que só funciona
condicionada a regime, ou em interação com outra, sai deste teste como plana.
É exatamente por isso que `L3` não é descartada — mas também significa que
`L3 → L2` precisa de um teste diferente do que reprovou a coluna, não de uma
repetição do mesmo.

---

## §5. O que entra, o que sai, o que muda

### §5.1 Entra

**Nada de fonte nova.** O que entra são três correções em colunas existentes,
todas motivadas por defeito medido:

1. **`E18f` com ancoragem corrigida.** Hoje é uma janela de 5 min de
   **relógio** colada numa barra de **fluxo** — cobre ~290% do fluxo da barra
   no p10 e 15,5% no p90 (`AG-263`). É a única coluna com sinal em 15/15
   células e o defeito provavelmente **atenua** o sinal, não o cria: verificado
   que `corr(E18f, duração_da_barra) = −0,008` e que o IC residualizado contra
   duração é idêntico ao bruto (`+0,0237` em ambos, BTCUSDT/R3). O repo já tem
   a construção correta do mesmo mecanismo em `D06f`/`D07f` (agregação sobre a
   própria barra).
2. **`E16f` com horizonte estendido.** O `|IC|` cresce monotonicamente até o
   limite da grade (`−0,0142` em `h=1` → `−0,0419` em `h=32`) e **não atingiu o
   pico**. É a única candidata a coluna de **contexto** — a banda `4–20·H` que
   `AG-263` mostrou vazia. Medir `h = 64, 128, 256` antes de fixar o papel.
3. **Normalização por calibração nas colunas de volume.** Sob dollar bar,
   `quote_volume` tem CV de 2,6% **dentro** de uma janela de threshold, e
   `volume` correlaciona até `+0,987` com `1/preço` (`AG-263`). Nível absoluto
   de volume não mede atividade; a coluna precisa ser normalizada pelo
   `threshold_quote` vigente, ou não existir.

### §5.2 Sai do vetor de treino

| Sai | Quantas | Por quê |
|---|---|---|
| `L4` — sem mecanismo e sem sinal | 29 | Não há tese nem evidência. Saem também do cálculo. |
| `L3` — tese sem sinal reproduzível | 15 | Continuam calculadas; fora do treino até passarem por reteste. |
| `L0` — primitivas | 2 (`C01`, `C02`) | São insumo de outras colunas, não preditores. Estar no vetor é acidente histórico. |
| `L1` — gate de regime | 4 (`B07`, `C07`, `E02f`, `E27f`) | `ADR-001` §2.7 já tirou regime do vetor; `E27f` ficou por inércia. |

**Duas remoções que valem por si, independentes desta arquitetura:**

- **`K08_days_since_halving`** — aplica as 4 datas de halving **do Bitcoin** aos
  5 ativos, sem eixo de símbolo. Para ETH/SOL/BNB/XRP é rampa monótona de
  calendário com nome econômico: dentro do fold identifica o período de treino,
  e no walk-forward os valores de teste caem fora do suporte (árvore extrapola
  constante). É eixo de sobreajuste por época.
- **`A14_dist_ema12_atr` em R3** — `A13` escala `48 → 24 → 12` e `A14` é fixo em
  12; em R3 as duas computam a mesma coluna sob ids diferentes (verificado por
  execução). Duas colunas, uma feature, competindo pela mesma importância.

### §5.3 Muda

1. **`T1_FEATURE_IDS` deixa de ser uma lista e passa a ser uma consulta.** A
   camada de cada coluna vira campo do `registry.yaml` (`layer: L0|L1|L2|L3|L4`),
   e o vetor de treino é derivado (`layer == "L2"`), não digitado. Isso fecha a
   classe de bug de `AG-207` (uma lista hardcoded em `baselines.py` que
   divergiu da real) por construção.
2. **O critério de promoção vira constante declarada.** `feature_promotion_min_cells: 7`
   (de 15), `provenance: DERIVED` a partir da taxa base sob H₀ (§1.4). Sem isso,
   "promover uma feature" volta a ser julgamento no momento de aplicar — o viés
   que travar critério a priori existe para evitar (`AG-122`).
3. **A ficha de tese vira pré-requisito de registry.** Nenhuma coluna nova entra
   sem `mecanismo_economico` e `quem_esta_do_outro_lado` preenchidos. "É um
   indicador clássico" é reprovação, não justificativa.
4. **A fronteira `L0`/`L1` fica explícita no código.** Hoje é preciso ler
   `classifier.py` para descobrir que quatro colunas do vetor são, na verdade,
   insumo do gate.

---

## §6. Consequências

**Fica mais fácil:** auditar o vetor (cada coluna tem camada e tese); explicar
por que uma coluna existe; cortar a deflação do DSR (2-4 graus de liberdade em
vez de 72); detectar quando uma coluna nova é redundante (a camada obriga a
declarar função).

**Fica mais difícil:** adicionar feature por intuição — que é o objetivo;
justificar `L3` para quem quiser resultado rápido, já que ela custa cálculo e
não entra no treino.

**Precisa ser revisitado:** o critério `≥ 7/15` foi calibrado sobre a taxa base
observada; se a taxa base mudar (mais dado, outro período), recalibrar. E a
heterogeneidade entre ativos de §7 pode invalidar a contagem por células.

---

## §7. O achado que este ADR não explica e não deve esconder

As descobertas por célula são **grosseiramente heterogêneas entre ativos**:

| | BTC | ETH | SOL | BNB | XRP |
|---|---|---|---|---|---|
| R1 | 3 | 2 | 6 | **39** | **34** |
| R2 | 2 | 2 | 5 | **23** | **26** |
| R3 | 3 | 1 | 2 | 3 | 7 |

BNB e XRP em R1/R2 produzem 10× mais descobertas que BTC/ETH/SOL, e o efeito
**desaparece em R3**. Isso não tem explicação no material atual e é grande
demais para ser ignorado: ou esses dois ativos são genuinamente mais
previsíveis nas grades rápidas, ou há uma propriedade de dado que infla a
estatística ali. Três das cinco features de `5/15` devem sua contagem
inteiramente a essas duas colunas da tabela — e é exatamente por isso que o
limiar de §1.4 as reprova.

**Investigar antes de aplicar §5.** Se a heterogeneidade for artefato, a
contagem por células precisa ser refeita.

---

## §8. Ordem de implementação, por custo crescente

1. **Campo `layer` no `registry.yaml`** — documentação, zero efeito em cálculo.
   Torna a arquitetura legível antes de mudar comportamento.
2. **Investigar a heterogeneidade BNB/XRP (§7)** — bloqueia tudo abaixo.
3. **Estender a grade de horizonte para `E16f`** (`h = 64, 128, 256`). Barato,
   sem retreino, e decide se o vetor terá camada de contexto.
4. **Corrigir a ancoragem de `E18f`** e remedir. Se o sinal subir, a única
   coluna robusta do motor melhora; se cair, a tese muda.
5. **Remover `K08`** e deduplicar `A13`/`A14` em R3. Independentes do resto.
6. **Derivar o vetor de treino de `layer == "L2"`** — muda contrato de
   `build_modeling_frame`/`run_layer1_sprint`, exige `config_hash` novo.
7. **Parar de calcular `L4`.** Último, porque é irreversível na prática (quem
   quiser retestar precisa recalcular a série inteira).

---

## §9. O que este ADR explicitamente NÃO decide

- **Não decide remover coluna alguma.** Tudo aqui é proposta; `AG-263`/`AG-265`
  são diagnóstico e nenhuma coluna foi retirada do repo.
- **Não decide a grade de produção.** `AG-260` mostrou que R1 ≈ R2 são
  indistinguíveis e R3 é pior em custo; isso é outro eixo.
- **Não resolve o gap da régua.** Mesmo com o vetor perfeito, `§1.1` exige lift
  de ~1,1 e nada medido até hoje chega perto. Podar o vetor melhora a
  deflação e a honestidade do processo — **não cria edge**. Se depois da poda o
  lift continuar em 1,0, a conclusão será sobre o mercado, não sobre o vetor, e
  essa é uma conclusão que este projeto precisa poder alcançar.
- **Não substitui triagem in-fold (B06).** A tabela de IC é descritiva e
  pós-hoc. Usá-la para escolher o vetor de treino é exatamente o que B06 proíbe
  — por isso a promoção `L3 → L2` precisa de um protocolo in-fold, e este ADR
  não o especifica.
