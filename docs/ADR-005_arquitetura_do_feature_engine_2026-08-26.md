# ADR-005 — Arquitetura do Feature Engine: estratificar por função e por evidência

**Versão:** 2 (2026-08-26) — reescreve a v1 do mesmo dia; ver §0.2
**Status:** **REPROVADO** na revisão independente de `project_assurance` (2026-08-26) — ver §11. Nenhuma implementação feita, nenhum default alterado, nenhuma coluna removida. **Não ratificar como está.**
**Escopo:** desenho do vetor de features (`src/features/`), fronteira com o gate de regime e com o vetor de treino do Alpha
**Origem:** persona `feature-thesis-auditor`, instrumentada em `AG-260` (régua econômica), `AG-263` (ficha de tese das 72 colunas), `AG-264` (barras degeneradas), `AG-265` (curva de IC por horizonte), `AG-266` (o artefato de `E18f`)
**Evidência:** `experiments/ic_by_horizon_report_{R1,R2,R3}.json` (15 células, 2022-01-01..2026-08-07), `audit/feature_thesis/fichas_69_2026-08-25.yaml`, `config/min_alpha_lift_by_combo.yaml`

---

## §0. Duas correções que esta linha de trabalho fez em si mesma

Registro as duas primeiro porque a conclusão depende inteiramente delas, e
porque nos dois casos a versão errada apontava para a recomendação oposta.

### §0.1 O erro do IC (corrigido antes de publicar)

A primeira versão de `ic_by_horizon.py` calculava o erro como o desvio entre
fases de amostragem dividido por `sqrt(h)`. Produzia `|t| ≈ 85` para
`IC = 0,04` e apontava **65 das 72 colunas** como significativas. As `h`
subamostras disjuntas cobrem o **mesmo período**, apenas em fases diferentes —
são redundantes, e o desvio entre elas mede variação de fase, não incerteza.
Corrigido para o erro de uma subamostra disjunta: 65 → 8.

### §0.2 A âncora que caiu (motivo desta v2)

A **v1 deste ADR** elegeu `E18f_taker_ls_vol_ratio` como âncora da camada
`L2`, por aparecer em 15/15 células. A investigação seguinte (`AG-266`)
mostrou que os 15/15 não eram sinal universal — eram **um artefato de fonte
atingindo os cinco ativos ao mesmo tempo**, que é precisamente o que produz
15/15 num critério que só olha células.

O IC mês a mês liga e desliga em degraus: ruído até 2024-02, `+0,15..+0,19`
sustentado de 2024-05 a 2025-06, ruído até 2026-05, e liga de novo em
2026-06. Transições de um mês para o outro, salto de 20×.

O teste que fecha compara o **mesmo mecanismo por origem**:

| feature | origem | DESL | LIG | DESL | LIG |
|---|---|---|---|---|---|
| `E18f_taker_ls_vol_ratio` | fonte externa 5 min | −0,005 | **+0,172** | −0,002 | **+0,124** |
| `D06f_taker_imbalance_z_48` | calculada da barra | −0,003 | +0,003 | +0,004 | +0,022 |
| `D05f_taker_buy_ratio` | calculada da barra | −0,005 | +0,003 | +0,005 | +0,021 |
| `E16f_global_ls_ratio` | fonte externa 5 min | −0,013 | −0,010 | −0,012 | −0,010 |
| `E14f_toptrader_ls_ratio` | fonte externa 5 min | −0,008 | −0,008 | −0,006 | +0,008 |

`D05f`/`D06f` medem o mesmo mecanismo econômico calculado da própria barra e
não mostram nada — não é o mercado. `E16f`/`E14f` vêm da mesma fonte, mesma
cadência de 5 min e mesmo asof-join, e são estáveis — não é a fonte externa
nem o alinhamento. É o campo `sum_taker_long_short_vol_ratio` especificamente.

**A lição de desenho, e ela é o núcleo desta v2:** um critério de evidência
que mede reprodução entre **ativos e grades** é cego a artefato que atinge
todos os ativos no **mesmo período**. Faltava o eixo tempo — §2.2 o adiciona.

---

## §1. Contexto — os fatos medidos

**§1.1 A régua econômica (`AG-260`).** Para o motor apenas empatar, o Alpha
precisa entregar lift em `P(TP)` entre **1,076 e 1,175**, conforme a célula.
O gate de regime mede lift `1,0027` (`AG-244`); as dez medianas do `ADR-003`
são negativas.

**§1.2 A ficha de tese (`AG-263`).** Das 72 colunas, **33 não têm nenhum
mecanismo econômico declarado** — nem no registry, nem em docstring, nem em
`constants.yaml`.

**§1.3 A curva de IC (`AG-265`).** 15 células, `h = 1,2,4,8,16,32` barras,
holding medido `H = 5`. Descobertas por Benjamini-Hochberg `q = 0,10` dentro
de cada célula:

| feature | células | veredito após §2.2 |
|---|---|---|
| `E18f_taker_ls_vol_ratio` | 15/15 | **QUARENTENA** — artefato (`AG-266`) |
| `E16f_global_ls_ratio` | 7/15 | passa nos dois eixos |
| `K04_session_us` | 5/15 | reprovado (abaixo do limiar de células) |
| `C09_range_pctile_expanding` | 5/15 | reprovado |
| `A11_true_range_pct` | 5/15 | reprovado |

**§1.4 O cruzamento tese × sinal.** Zero das 29 colunas sem mecanismo têm
sinal; zero das 16 dimensionalmente incoerentes têm sinal. A ficha foi feita
lendo fórmula e registry, sem olhar retorno, e separou corretamente o
conjunto vazio.

---

## §2. Decisão proposta

**Estratificar o Feature Engine em cinco camadas por FUNÇÃO, com um estado de
QUARENTENA ortogonal, e governar a entrada no vetor de treino por um critério
de evidência de DOIS EIXOS: reprodução entre células e estabilidade no tempo.**

Hoje existe uma lista plana de 72 colunas: todas calculadas sempre, todas
entregues ao Alpha, nenhuma com papel declarado. A distinção
`T1_FEATURE_IDS` vs `SUPPORT_FEATURE_IDS` não corresponde a fronteira real —
`E27f` é T1 e alimenta o gate de regime; `C01`/`C02` são primitivas de cálculo
e estão no vetor; `B07`/`C07`/`E02f` são T2 e são o insumo do classificador.

### §2.1 As cinco camadas (função)

| Camada | O que é | Vai ao Alpha? | Membros hoje |
|---|---|---|---|
| **L0 — Primitiva** | insumo de cálculo de outras colunas | não | `C01_atr_20`, `C02_atr_20_pct` (`atr_20_abs` usado em 10 pontos, `atr_20_pct` em 7) |
| **L1 — Gate de regime** | consumido por `classifier.py` | não (ADR-001 §2.7) | `B07`, `C07`, `E02f`, `E27f` |
| **L2 — Núcleo de sinal** | passa nos dois eixos de §2.2 | **sim** | `E16f_global_ls_ratio` |
| **L3 — Em observação** | tese declarada, sem evidência suficiente | não, recalculada | as `TESE_OK` restantes |
| **L4 — Aposentada** | sem mecanismo **e** sem sinal | não, nem calculada | as 29 `SEM_MECANISMO` sem descoberta |

### §2.2 O critério de evidência — dois eixos, ambos operacionais

Uma coluna entra em `L2` **apenas se passar nos dois**:

**Eixo 1 — reprodução entre células.** Descoberta por Benjamini-Hochberg
`q = 0,10` em **≥ 7 das 15** células.

O limiar não é escolhido, é calibrado sob H₀. A taxa base observada é 10,5
descobertas por célula (de 72), `p = 0,146`. Sob binomial(15, 0,146), o número
esperado de features que apareceriam em `≥ k` células **por acaso**, entre 72:

| `k ≥` | esperado sob H₀ | observado |
|---|---|---|
| 5 | **4,05** | 5 |
| 6 | 1,08 | 2 |
| **7** | **0,22** | 2 |
| 15 | 3·10⁻¹³ | 1 |

As três features de 5/15 são indistinguíveis de acaso — esperava-se 4,05,
observou-se 5.

**Eixo 2 — estabilidade temporal.** IC medido em subperíodos **semestrais
disjuntos** (10 semestres em 2022-01..2026-08), exigindo dos que tiverem
`n ≥ 1000`:

- **`max|IC_sub| / mediana|IC_sub| ≤ 4`**, e
- **direção do IC consistente em ≥ 70% dos subperíodos.**

Calibração dos dois limiares, sobre BTCUSDT/R1:

| feature | `max/med` | mesma direção | resultado |
|---|---|---|---|
| `E18f_taker_ls_vol_ratio` | **12,57** | **50%** | reprova nos dois |
| `E16f_global_ls_ratio` | 2,98 | 90% | passa |
| `E14f_toptrader_ls_ratio` | 1,50 | 100% | passa |
| `D06f_taker_imbalance_z_48` | 1,92 | 60% | reprova na direção |
| `A01_log_return_1` | 2,28 | 80% | passa |

**Honestidade sobre a calibração:** os dois limiares foram fixados olhando
estes cinco casos — um artefato confirmado (`E18f`) e quatro colunas de
comportamento conhecido. Isso é calibração de instrumento, legítima, mas
significa que eles **não são a priori para estas cinco**. Para qualquer coluna
nova, passam a ser: o limiar entra em `constants.yaml` com
`provenance: DERIVED` e não se mexe depois de ver o resultado. Sem essa trava,
"promover uma feature" volta a ser julgamento no momento de aplicar — o viés
que travar critério existe para evitar (`AG-122`).

A separação é confortável: `E18f` tem `12,57` contra `2,98` do pior aprovado —
fator 4,2 de folga.

### §2.3 Quarentena — estado, não camada

`quarentena: true` é ortogonal à camada. Marca coluna cujo sinal é **suspeito
de artefato de fonte**, não ausente. Difere de `L4` (sem tese e sem sinal) e
de `L3` (tese sem sinal): aqui há sinal forte e ele é o problema.

Regra: coluna em quarentena **não entra no vetor de treino**, continua sendo
calculada, e só sai da quarentena quando a causa do artefato for conhecida e
tratada — nunca por o IC "voltar ao normal" num período novo, que é
exatamente o que o degrau faz sozinho.

Hoje: `E18f_taker_ls_vol_ratio`.

---

## §3. Opções consideradas

### Opção A — Manter o vetor de 72 (status quo)

| Dimensão | Avaliação |
|---|---|
| Complexidade | Nenhuma |
| Custo | Alto e invisível: 72 colunas por barra em 15 células |
| Custo estatístico | Máximo — cada coluna é grau de liberdade na seleção e pesa na deflação do DSR |
| Risco | `E18f` permaneceria no vetor, com 13 meses de artefato dentro da janela de treino |

**Prós:** zero trabalho; preserva opcionalidade se o IC estiver subestimando alguma coluna.
**Contras:** 29 colunas sem mecanismo e sem sinal seguem consumindo `N_lifetime`; o artefato de `AG-266` entra no treino.

### Opção B — Podar para `L2` apenas

| Dimensão | Avaliação |
|---|---|
| Complexidade | Baixa |
| Custo estatístico | Mínimo — 1 grau de liberdade |
| Risco | **Muito alto**: `L2` tem UMA coluna após `AG-266` |

**Prós:** honesto com a evidência; deflação mínima.
**Contras:** um vetor de 1 coluna não vence a régua de 1,1 de §1.1, e qualquer falha na fonte de `E16f` deixa o motor sem vetor. A v1 deste ADR já considerava frágil com duas colunas; com uma, é inviável.

### Opção C — Cinco camadas + quarentena, podar `L4`, manter `L3` calculada ✅

| Dimensão | Avaliação |
|---|---|
| Complexidade | Média — mudança de contrato, não de cálculo |
| Custo | Reduz ~40% das colunas calculadas |
| Custo estatístico | Baixo — vetor de treino cai de 72 para 1-4 |
| Reversibilidade | Alta: `L3` continua calculada; promover é mudar um campo |

**Prós:** separa "sem sinal detectável hoje" de "não deveria existir" e de "sinal suspeito"; `L3` fica disponível para reteste sem custo de deflação; a fronteira `L0`/`L1` corrige confusão real de papéis.
**Contras:** exige mudar `T1_FEATURE_IDS`/`SUPPORT_FEATURE_IDS` e o contrato de `build_modeling_frame`; a promoção `L3 → L2` precisa de protocolo, senão vira porta dos fundos para mineração.

---

## §4. Trade-off central

A tensão é entre **poder estatístico** e **cobertura de mecanismo**, e
`AG-266` a deslocou.

A v1 argumentava que podar para `L2` maximiza poder (2 graus de liberdade
contra régua de 1,1) ao custo de apostar em duas fontes de derivativos. Com
`L2 = {E16f}`, esse argumento inverte: **a poda agressiva agora concentra
todo o motor numa única coluna de uma única fonte externa** — precisamente o
tipo de fonte que acabou de produzir um artefato de 13 meses.

Isso não é argumento para manter as 72. É argumento para que a Opção C mova
`L3` para fora do **vetor de treino** sem tirá-la do **cálculo**: o custo
estatístico é o do vetor, não o do pipeline. Recalcular uma coluna é barato;
treinar sobre ela não é.

Uma limitação que a Opção C não resolve: o IC de Spearman mede relação
monótona marginal. Uma coluna que só funciona condicionada a regime, ou em
interação, sai deste teste como plana. É por isso que `L3` não é descartada —
e também por que `L3 → L2` precisa de um teste **diferente** do que reprovou
a coluna, não de uma repetição do mesmo.

---

## §5. O que entra, o que sai, o que muda

### §5.1 Entra

**Nenhuma fonte nova.** Três correções em colunas existentes, todas por
defeito medido:

1. **`E16f` com horizonte estendido.** O `|IC|` cresce monotonicamente até o
   limite da grade (`−0,0142` em `h=1` → `−0,0419` em `h=32`) e **não atingiu
   o pico**. É a única candidata a coluna de **contexto** — a banda `4–20·H`
   que `AG-263` mostrou vazia. Medir `h = 64, 128, 256` antes de fixar papel.
2. **Normalização por calibração nas colunas de volume.** Sob dollar bar,
   `quote_volume` tem CV de 2,6% **dentro** de uma janela de threshold e
   `volume` correlaciona até `+0,987` com `1/preço` (`AG-263`). Nível absoluto
   de volume não mede atividade; a coluna precisa ser normalizada pelo
   `threshold_quote` vigente, ou não existir.
3. **Investigar o momentum de BNB/XRP** — o único candidato a sinal genuíno
   que esta linha de trabalho produziu, e que **não estava** no `L2` da v1.
   Ver §7.

**Sai da lista de §5.1 da v1:** corrigir a ancoragem de `E18f`. Suspenso até
a causa de `AG-266` ser conhecida.

### §5.2 Sai do vetor de treino

| Sai | Quantas | Por quê |
|---|---|---|
| `E18f` | 1 | **Quarentena** — artefato de fonte (`AG-266`) |
| `L4` — sem mecanismo e sem sinal | 29 | Sem tese e sem evidência. Saem também do cálculo. |
| `L3` — tese sem evidência suficiente | ~15 | Continuam calculadas; fora do treino até reteste. |
| `L0` — primitivas | 2 | São insumo de outras colunas, não preditores. |
| `L1` — gate de regime | 4 | `ADR-001` §2.7 já tirou regime do vetor; `E27f` ficou por inércia. |

**Duas remoções que valem por si, independentes desta arquitetura:**

- **`K08_days_since_halving`** — aplica as 4 datas de halving **do Bitcoin**
  aos 5 ativos, sem eixo de símbolo. Para ETH/SOL/BNB/XRP é rampa monótona de
  calendário com nome econômico: dentro do fold identifica o período de
  treino, e no walk-forward os valores de teste caem fora do suporte. É eixo
  de sobreajuste por época.
- **`A14_dist_ema12_atr` em R3** — `A13` escala `48 → 24 → 12` e `A14` é fixo
  em 12; em R3 as duas computam a mesma coluna sob ids diferentes (verificado
  por execução).

### §5.3 Muda

1. **`T1_FEATURE_IDS` deixa de ser lista e passa a ser consulta.** A camada e
   o estado de quarentena viram campos do `registry.yaml` (`layer`,
   `quarentena`), e o vetor de treino é derivado (`layer == "L2" and not
   quarentena`), não digitado. Fecha por construção a classe de bug de
   `AG-207` (lista hardcoded em `baselines.py` que divergiu da real).
2. **O critério de promoção vira constante declarada, nos dois eixos.**
   `feature_promotion_min_cells: 7`, `feature_promotion_max_ic_ratio: 4.0`,
   `feature_promotion_min_direction_frac: 0.70` — todos `provenance: DERIVED`,
   com a ressalva de calibração de §2.2 registrada na entrada.
3. **A ficha de tese vira pré-requisito de registry.** Nenhuma coluna nova
   entra sem `mecanismo_economico` e `quem_esta_do_outro_lado`. "É um
   indicador clássico" é reprovação.
4. **A fronteira `L0`/`L1` fica explícita.** Hoje é preciso ler
   `classifier.py` para descobrir que quatro colunas do vetor são insumo do
   gate.
5. **Toda coluna de fonte externa ganha o teste de degrau na cadência de
   dados.** `AG-266` passou despercebido porque nada vigiava estabilidade
   temporal de IC. O teste de §2.2 eixo 2 deveria rodar como diagnóstico
   periódico, não só na promoção.

---

## §6. Consequências

**Fica mais fácil:** auditar o vetor (cada coluna tem camada, estado e tese);
cortar a deflação do DSR; detectar artefato de fonte antes que entre no
treino; explicar por que uma coluna existe.

**Fica mais difícil:** adicionar feature por intuição — que é o objetivo; e
justificar `L3`, que custa cálculo e não entra no treino.

**Precisa ser revisitado:** os limiares de §2.2 foram calibrados sobre cinco
casos e sobre a taxa base observada; se a taxa base mudar (mais dado, outro
período), recalibrar — e recalibrar **antes** de medir o candidato, nunca
depois.

---

## §7. O que a investigação de `AG-266` deixou em pé

**O momentum de BNB/XRP é parcialmente real e não estava no vetor proposto.**
Por quartil temporal em BNBUSDT/R1, 9 das 12 primeiras features descobertas
mantêm o sinal nos quatro quartis — `A01`..`A06` (retornos defasados) com IC
de `+0,008` a `+0,024`, consistente. É momentum de 1 barra, estável no tempo.
`A01` passa nos dois eixos de §2.2 em BTCUSDT (`max/med = 2,28`, direção 80%)
mas só atinge o limiar de células em BNB/XRP.

A tensão a resolver antes de promover: a autocorrelação de **Pearson** do
retorno de BNB é `+0,0009` (nula), mas o IC de **Spearman** de `A01` contra o
retorno seguinte é `~+0,017` e consistente. Divergirem nessa direção significa
relação no **corpo** da distribuição com caudas que a cancelam — o que é
compatível tanto com microestrutura real quanto com efeito de discretização
que ainda não isolei.

**Descartadas, com medição, como explicação da heterogeneidade BNB/XRP:**
discretização de preço (SOL tem mais retornos zero que BNB e um décimo das
descobertas); autocorrelação (BNB tem a menor de todas); cadência ou cobertura
da fonte de métricas (288 linhas/dia, sem lacuna, 2023-11..2026-08); duração
de barra (Q2 tem mais barras curtas que Q3 e IC 20× menor).

---

## §8. Ordem de implementação, por custo crescente

1. **Campos `layer` e `quarentena` no `registry.yaml`** — documentação, zero
   efeito em cálculo. Torna a arquitetura legível antes de mudar comportamento.
2. **Tirar `E18f` do vetor de treino** (quarentena). Independente do resto e
   é o item com maior risco se ficar parado.
3. **Rodar o teste de degrau (§2.2 eixo 2) sobre as 72 colunas.** `AG-266` foi
   achado por acaso; nada garante que seja o único. É barato e sem retreino.
4. **Estender a grade de horizonte para `E16f`** (`h = 64, 128, 256`). Decide
   se o vetor terá camada de contexto.
5. **Isolar o momentum de BNB/XRP (§7)** — Pearson vs Spearman, e testar
   discretização como causa.
6. **Remover `K08`** e deduplicar `A13`/`A14` em R3.
7. **Derivar o vetor de treino de `layer == "L2" and not quarentena`** — muda
   contrato de `build_modeling_frame`/`run_layer1_sprint`, exige `config_hash`
   novo.
8. **Parar de calcular `L4`.** Último, porque é irreversível na prática.

---

## §9. O que este ADR explicitamente NÃO decide

- **Não remove coluna alguma.** Tudo aqui é proposta; nenhuma coluna foi
  retirada do repo.
- **Não decide a grade de produção.** `AG-260` mostrou R1 ≈ R2 indistinguíveis
  e R3 pior em custo; é outro eixo.
- **Não resolve a causa de `AG-266`.** Por que `sum_taker_long_short_vol_ratio`
  muda de comportamento em blocos de meses não é resolvível por medição
  interna — exige checar a fonte ou rebaixar o dado.
- **Não resolve o gap da régua.** Mesmo com o vetor perfeito, §1.1 exige lift
  de ~1,1 e nada medido chega perto. Podar o vetor melhora deflação e
  honestidade — **não cria edge**. Se depois da poda o lift continuar em 1,0,
  a conclusão será sobre o mercado, não sobre o vetor, e este projeto precisa
  poder alcançá-la.
- **Não substitui triagem in-fold (B06).** A tabela de IC é descritiva e
  pós-hoc. Usá-la para escolher o vetor de treino é o que B06 proíbe — a
  promoção `L3 → L2` precisa de protocolo in-fold, e este ADR não o
  especifica.


---

## §11. REPROVADO na revisão independente (2026-08-26)

`project_assurance` reprovou este ADR com 18 achados, dois CRITICAL. Os dois
foram **reverificados por medição** antes de eu aceitá-los, e os dois
procedem. Registro aqui o essencial; as entradas completas estão em
`audit/architecture_gaps_log.yaml::AG-270`..`AG-287`.

### §11.1 `AG-270` — o eixo 1 repete o erro do §0.1, um nível acima

O critério `≥ 7 de 15 células` calibra sob binomial(15; 0,146), presumindo
**15 ensaios independentes**. As 15 células são 5 símbolos × 3 resoluções, e
as 3 resoluções de um símbolo são a mesma série de preço sob thresholds
diferentes. Medido nos próprios relatórios: **197 de 275 blocos
símbolo×feature (72%) são perfeitamente concordantes** nas 3 resoluções
(0/3 ou 3/3).

A unidade efetiva é o **símbolo** (n=5), não a célula (n=15). `E16f` não tem
"7 de 15 células" — tem **BTC 3/3, SOL 3/3, BNB 1/3, ETH 0/3, XRP 0/3**, isto
é ~2,3 símbolos. Sob binomial(5; 0,146), `P(X≥3 símbolos) = 0,0247` → **1,78
features esperadas por acaso entre 72**.

E o documento não precisa dessa correção para cair: **pelo seu próprio nulo**,
retirando `E18f` (artefato confirmado) das 2 observadas em `k≥7`, sobra 1
contra 0,22 esperada → `P(X≥1) = 0,197` sob Poisson. Não significativo.

**Consequência: a camada `L2` fica VAZIA, não com uma coluna.** Toda a
discussão de §3 e §4 — que usa "`L2` tem UMA coluna" como o argumento que
descarta a Opção B — precisa ser refeita.

O mesmo erro, duas vezes na mesma linha de trabalho: §0.1 corrigiu "tratar
observações redundantes como independentes" **dentro** da célula (fases de
amostragem); §2.2 o cometeu **entre** células.

### §11.2 `AG-271` — o documento se contradiz sobre as colunas que manda apagar

§1.4 afirma "zero das 29 colunas sem mecanismo têm sinal" e §2.1/§5.2 usam
isso para definir `L4`, que §8 item 8 manda **parar de calcular**, chamando
de irreversível.

§7 do mesmo documento diz que `A01`..`A06` são "o único candidato a sinal
genuíno que esta investigação produziu". Verificado na ficha: `A01`, `A02`,
`A03`, `A04`, `A05`, `A06` têm **todas** `veredito: SEM_MECANISMO`. São
membros de `L4`.

Agravante, verificado em `T1_FEATURE_IDS`: `A05_ret_vol_norm_4` e `B01_rsi_14`
são `SEM_MECANISMO` e são features **de produção hoje**. E
`B07_efficiency_ratio_48` é `SEM_MECANISMO` **e** é lido por
`src/regime/classifier.py:535` — aplicar a regra de `L4` mecanicamente
derruba o gate de regime.

§1.4 também é resultado de **BTCUSDT/R1 sozinho** (é a tabela do `AG-265`,
cujo status diz "rodado só em BTCUSDT/R1"), apresentado logo abaixo da tabela
de 15 células de §1.3.

### §11.3 Os demais achados, por severidade

**HIGH:** `AG-272` a partição não é exaustiva (25 colunas sem camada, entre
elas `A13` e `E10f`, ambas T1 vivas) e não tem precedência (`B07` é L1 e
candidata a L4 ao mesmo tempo) — a lição de `AG-122` na letra; `AG-273`
violação de B06, declarada em §9 e cometida em §2.2; `AG-274` o eixo 2 não
tem código nem artefato, e 6 termos sem definição operacional; `AG-275`
descasamento de alvo (o gate mede IC contra retorno de `h` barras; o Alpha
treina `1{barrier == TP}`); `AG-276` o BH não está nos relatórios e
`pico_abs_t` é um máximo sobre 6 horizontes correlacionados; `AG-277`
atribuição errada de `ADR-001` §2.7, que trata do Meta consumir o **estado**
de regime, não das features cruas.

**MEDIUM:** `AG-278` a faixa "1,076 a 1,175" não existe em nenhum artefato (a
real é 1,076–1,151); `AG-279` os relatórios persistidos descrevem o método de
erro **refutado**; `AG-280` 33 vs 29 são campos diferentes apresentados como a
mesma população; `AG-281` "todas as 72 entregues ao Alpha" é falso (o default
são 7); `AG-282` o registry já tem `tier`, e `layer` seria taxonomia
sobreposta sem precedência; `AG-283` o ADR reverte `AG-207`/`ADR-003` —
decisão ratificada pelo Manager — sem declarar que reverte; `AG-284` o "9 de
12 em 4 quartis" não tem o nulo certo (as 12 são pré-selecionadas por sinal, e
6 delas são colineares); `AG-285` as 3 constantes seriam `ASSUMED`/`classe A`,
não `DERIVED`.

**LOW:** `AG-286` "10 e 7 pontos" são contagens de grep, não de consumo (6 e
4); `AG-287` a janela de cobertura citada é mais estreita que a real.

### §11.4 O que sobrevive

Quatro peças não dependem de nenhum achado acima e podem ser executadas:

1. A separação entre **custo de cálculo** e **custo estatístico** (§4).
2. A **quarentena como estado ortogonal** (§2.3), com a regra de saída
   ("nunca por o IC voltar ao normal").
3. `K08_days_since_halving` e a colisão `A13`/`A14` em R3 (§5.2) — achados
   reais, verificados, independentes da arquitetura.
4. A **normalização de volume pelo `threshold_quote`** (§5.1 item 2) — defeito
   dimensional real.

### §11.5 O que uma v3 precisaria antes de existir

`AG-270`, `AG-274` e `AG-276` exigem instrumento que não existe: o modelo nulo
por símbolo, o eixo 2 persistido, e o BH emitido no payload com unidade
declarada. Escrever uma v3 antes disso seria repor a mesma classe de erro com
números diferentes.
