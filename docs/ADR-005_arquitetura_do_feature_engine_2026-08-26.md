# ADR-005 — Arquitetura do Feature Engine: estratificar por função e por evidência

**Versão:** 2 (2026-08-26) — reescreve a v1 do mesmo dia; ver §0.2
**Status por parte** (2026-08-26):
- **§1–§9 (estratificação em camadas, critério de evidência): REPROVADO** na revisão independente de `project_assurance` — ver §11. **Não ratificar como está.**
- **§12 (grade de produção): PROPOSTO**, não revisado — `project_assurance` acionado em 2026-08-26 (background). Independente das partes reprovadas — não usa o critério de §2.2 nem a tabela de IC. **Implementação iniciada**: §12.4/§12.5/§12.2 agora têm núcleo puro reproduzível em `src/analysis/production_grade_gate.py` (ver §12.8) — ainda NÃO RODADO (protocolo de execução) nem revisado.
- **§13 (engenharia de ML): PROPOSTO**, não revisado. Achados centrais reverificados por execução; independente de §1–§9. **Delegado para outra sessão** (decisão do Manager, 2026-08-26) — nada implementado aqui.

Nenhum default de produção alterado, nenhuma coluna de feature removida. `src/analysis/production_grade_gate.py` é código novo, decision-support (mesmo status de `feasibility.py`) — não é consumido por nenhum pipeline de treino/execução.

**Nota de numeração:** não há §10. A v1 deste ADR tinha um addendum §10 que foi absorvido por §0.2 na reescrita v2; o número ficou vago e é preservado assim porque `AG-266` e os commits já referenciam §11, §12 e §13 pelos números atuais.
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
- ~~**Não decide a grade de produção.**~~ **SUPERADO em 2026-08-26 por §12**,
  por diretriz do Manager: *"tem que decidir, de alguma forma precisa ter a
  matemática financeira para promover por escrito a grade que entra em
  produção"*. A decisão está em §12.6 — **R3 em 4 ativos**, com `BTCUSDT/R3`
  excluída pelo teto R1 recalculado por ativo. A leitura anterior (`AG-260`,
  "R1 ≈ R2 ≫ R3") é discutida e contestada em §12.1 e §12.7: ela mede lift
  exigido **sob número de trades livre**, e o orçamento de fees é restrição
  inviolável, não parâmetro.
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

---

## §12. A GRADE DE PRODUÇÃO — decisão, com a matemática financeira

**Versão 2 desta seção.** A v1 (commit `f77b8e9`) continha dois erros de
conta, ambos achados por revisão de levantamento econômico independente e
corrigidos aqui: custo por trade tratado como fixo entre grades, e orçamento
de fees multiplicado por 5 em vez de compartilhado. Os dois estão descritos
em §12.7. A conclusão não mudou de direção; a margem mudou.

**Diretriz do Manager (2026-08-26):** §9 dizia "não decide a grade de
produção". Recusado — *"tem que decidir, de alguma forma precisa ter a
matemática financeira para promover por escrito a grade que entra em
produção"*.

**Esta seção NÃO depende das partes reprovadas em §11.** Não usa o critério
de §2.2, não usa a tabela de IC, não seleciona feature. É economia de
execução sobre labels de produção.

### §12.1 Por que `AG-260` não bastava

`AG-260` compara grades pelo **lift exigido em `P(TP)`** e conclui R1 ≈ R2 ≫
R3. Responde "quanto o modelo precisa melhorar a taxa de acerto" — e ignora
que **o número de trades não é livre**. A restrição R3 do projeto
(`fee_budget_monthly`) fixa quanto se pode gastar em fees por mês. Uma grade
com 4× mais barras não produz 4× mais trades: produz 4× mais *candidatos* ao
mesmo orçamento.

E ignora que o custo por trade **muda com a grade**. Como
`notional = equity × risk_per_trade / stop_pct`, uma grade com stop maior
opera nocional menor para o mesmo risco — e paga menos fee por trade.

### §12.2 O teto R1, recalculado por ativo

O `CLAUDE.md` marca como `[DESATUALIZADO]` o teto de stop de 0,758%: é
BTC-único, calculado a US$ 64.940 sob barra de relógio. `AG-190` registra que
**nunca houve remediação**. Recalculei, com `step_size` real do snapshot de
`exchangeInfo` e preço mediano medido por ativo:

`stop_máx = (equity × risk_per_trade) / (2 × step_size × preço)`

| símbolo | `step_size` | preço mediano | `unit_notional` | **teto R1** | `stop_pct` R3 | |
|---|---|---|---|---|---|---|
| BTCUSDT | 0,001 | 76.558,70 | **76,56** | **0,643%** | 0,767% | **VIOLA** |
| ETHUSDT | 0,001 | 2.768,28 | 2,77 | 17,78% | 0,922% | passa |
| BNBUSDT | 0,01 | 628,64 | 6,29 | 7,83% | 0,750% | passa |
| SOLUSDT | 0,01 | 145,92 | 1,46 | 33,73% | 1,262% | passa |
| XRPUSDT | 0,1 | 1,41 | 0,14 | 348,3% | 1,010% | passa |

O `unit_notional` varia **542×** entre BTC e XRP — é `AG-165` com número. O
teto de 0,758% do `CLAUDE.md` é o de BTC e é, de longe, o mais restritivo;
aplicá-lo aos cinco ativos é exatamente o erro que `AG-190` descreve.

**Consequência: `BTCUSDT/R3` é excluída** (stop 0,767% > teto 0,643%). Não é
a grade que cai — é uma célula. R3 segue viável em 4 dos 5 ativos.

Nota: o teto de BTC caiu de 0,758% para 0,643% porque o preço subiu de
US$ 64.940 para US$ 76.559 — é o "teto de preço do BTC" do PRD visto pelo
outro lado, e ele aperta conforme o preço sobe.

### §12.3 O retorno bruto por trade é idêntico nas 15 células

`ret_net` dos labels de produção, excluindo NOFILL (3,04M trades):

| grade | média por trade | desvio |
|---|---|---|
| R1 | −0,00063 a −0,00068 | 0,0047 – 0,0082 |
| R2 | −0,00062 a −0,00066 | 0,0066 – 0,0115 |
| R3 | −0,00062 a −0,00066 | 0,0093 – 0,0163 |

**A média é a mesma em todas as 15.** A grade não muda o retorno bruto —
muda o **desvio**, que dobra de R1 para R3. Como a média é comum, a única
alavanca é a dispersão que o modelo pode explorar ao ordenar.

### §12.4 Capacidade contra demanda

Orçamento **compartilhado** pelos 5 ativos (mesmo equity de USD 196,85):
`3,0% × 196,85 = USD 5,9055/mês`. Custo por trade
`= (equity × risk / stop_pct) × 5,5173 bps`, portanto menor onde o stop é
maior. Demanda = taxa de sinal **medida** (`n_trades/n_eval_long`,
`experiments/alpha_deep_analysis_2026-08-24.json`), não a nominal.

| grade | ativos | custo/trade | **capacidade** | **demanda** | veredito |
|---|---|---|---|---|---|
| R1 | 5 | $0,1230 | 48,0 | 314,4 | **estoura 6,55×** |
| R2 | 5 | $0,0858 | 68,8 | 153,2 | **estoura 2,23×** |
| **R3** | 4 | $0,0570 | **103,6** | **65,1** | **cabe, 37% de folga** |

**R3 é a única grade que satisfaz a restrição R3 do projeto.** E o eixo não é
novo: o PRD já registrava *"R3 volta a ser objeção ativa, não satisfeita"* na
grade de relógio, sem nunca ter sido reaberto por resolução.

### §12.5 A conta de habilidade exigida

Com seleção da fração `q = (capacidade/n_ativos)/barras_mês` de maior score:

```
E[r | top q] ≈ μ + σ · ρ · λ(q),   λ(q) = φ(Φ⁻¹(1−q))/q
ρ_mínimo = −μ / (σ · λ(q))
```

| grade | `q` | `σ` | `λ(q)` | **`ρ` mínimo** | ret/mês (ρ=0,05) |
|---|---|---|---|---|---|
| R1 | 0,333% | 0,00607 | 3,018 | 0,0344 | +1,37% |
| R2 | 0,956% | 0,00851 | 2,680 | 0,0276 | +3,51% |
| **R3** | 3,596% | 0,01202 | 2,197 | **0,0239** | **+7,15%** |

R3 é **menos seletivo** e ainda assim exige **31% menos habilidade** — σ dobra
e mais que compensa o λ menor.

**Validado sem supor normalidade** (retorno de triple barrier é bimodal),
ordenando por score de `ρ` controlada sobre os retornos reais, 20 repetições:

| grade | ρ=0,02 | ρ=0,05 | ρ=0,10 | oracle |
|---|---|---|---|---|
| R1 | −0,00034 | +0,00009 | +0,00084 | +0,01387 |
| R2 | −0,00028 | +0,00030 | +0,00123 | +0,01637 |
| R3 | −0,00016 | +0,00048 | +0,00165 | +0,01937 |

A medição confirma a analítica: R3 domina em todos os níveis de habilidade e
tem 40% mais teto no oracle.

### §12.6 Decisão

**PROMOVO R3 À GRADE DE PRODUÇÃO, em 4 ativos — ETH, BNB, SOL, XRP.
`BTCUSDT/R3` fica excluída por violar o teto R1.**

Quatro condições, que são parte da decisão:

1. **`target_signal_rate` deixa de ser global.** É fração de barras, derivada
   para a grade de 15m (`2880 × 0,0189 = 54,4`, os "~55 trades/mês" do PRD) e
   aplicada literalmente a três grades com contagens diferentes. Precisa ser
   resolvido por grade a partir da capacidade:
   `q_g = (capacidade/n_ativos)/barras_mês`.
2. **Condicional a `ρ > 0,0239`.** Nada medido mostra que o modelo tem esse
   `ρ`; `AG-244`/`ADR-003` sugerem o contrário — **nenhuma das 15 células tem
   `ret_net` positivo hoje**. R3 ser a melhor grade não significa que o motor
   seja positivo nela; significa que é o alvo mais baixo a vencer.
3. **`BTCUSDT` sai de R3.** E o teto aperta conforme o preço sobe — precisa de
   reavaliação periódica, não uma vez.
4. **O custo é amostra e é heterogeneidade.** R3 tem ~40k barras por ativo
   contra ~163k de R1. E `AG-238` mede I² caindo de 83/61 (R1) para 66/67
   (R3): os ativos ficam **mais parecidos** em R3, o que enfraquece o
   argumento de escopo multi-ativo justamente na grade escolhida.

### §12.7 As objeções, e por que decido assim mesmo

**"Os três eixos são o mesmo fato contado três vezes."** Correto. Fees,
nocional agregado (R5) e `ret_net` real derivam todos de *menos trades ×
nocional menor*. Por trade, R3 é igual ou **pior**: `pnl/n_trades` em BTC é
−0,00124 (R1) contra −0,00316 (R3). R3 não tem mais edge — **gasta menos**.
Num motor com `ret_net` negativo em 15/15, "gasta menos" é indistinguível de
"opera menos", e o limite dessa lógica é operar zero.

O que sustenta a decisão apesar disso: a escolha de grade não é sobre o motor
atual, que é negativo em qualquer grade. É sobre **onde colocar a aposta se o
modelo vier a ter habilidade**. E aí `σ` é o que decide, porque `μ` é comum.
R3 converte qualquer `ρ` em ~5× mais retorno que R1.

**`AG-260` conclui o oposto, e é o único eixo distinguível.** Ele mede lift em
`P(TP)` **sob número de trades livre**; esta seção mede habilidade exigida
**sob orçamento fixo**. A segunda é a pergunta de produção, porque o orçamento
de fees é restrição inviolável e não parâmetro. Mas registro que, no eixo
dele, R3 perde com ~5σ — e que ele é o único com significância estatística
declarada.

**`fee_budget_monthly = 0,03` é `ASSUMED`**, "sem base; inventado", classe A,
`sweep_range: [0,015; 0,045]`. Toda a capacidade deriva dele. Um sweep de ±50%
move a capacidade de R3 entre ~52 e ~155 trades/mês. A **ordenação** entre
grades é robusta (σ não muda com o orçamento); o **nível** não é.

**Dois erros meus na v1 desta seção**, ambos corrigidos acima: tratei o custo
por trade como fixo entre grades (é função de `stop_pct`), e multipliquei o
orçamento por 5 em vez de compartilhá-lo entre os ativos. O primeiro
subestimava a vantagem de R3; o segundo inflava a capacidade de todas em 5×.
A direção não mudou; a margem de R3 sobre R1 caiu de 35% para 31%.

### §12.8 O que falta, e não impede a decisão

- ~~Gate 0 nunca foi executado e persistido.~~ **FECHADO em 2026-08-26**
  por `src/analysis/production_grade_gate.py` (+ `tests/unit/
  test_analysis_production_grade_gate.py`) — núcleo puro das 3 contas
  desta seção (teto R1, custo/capacidade sob orçamento compartilhado,
  `ρ_mínimo`), casca que lê `s1_tp_sl_sensitivity_report_{R}.json`
  (`stop_pct_cell` real, não recalculado), `Filters` reais via
  `load_filters_asof` (não o escalar BTC-único de `constants.yaml`) e
  preço mediano real de `data.lake.query_dollar_bars`. Persiste
  `experiments/production_grade_gate_report.json`. `equity`/`asof` são
  parâmetros obrigatórios (nunca cache de equity, B17; nunca "hoje"
  presumido, B01) — ainda **NÃO RODADO** (protocolo de execução do
  Manager, `CLAUDE.md`: só o usuário roda `.py`) e **NÃO REVISADO**
  (project_assurance pendente sobre esta §12, ver nota no topo do
  documento). Mesma limitação de `stop_pct` já registrada abaixo (usa a
  célula de produção GLOBAL do S1, não overrides por combo) — herdada,
  não escondida.
- **O S1 filtra só o piso R2, nunca o teto R1.** Por isso R3 aparece com 7
  células viáveis e R1 com 5 — a comparação entre grades foi feita sobre
  conjuntos filtrados por critérios diferentes.
- **`step_size`/`min_notional` em `constants.yaml` são escalares BTC-únicos.**
  O dado por ativo já está no snapshot de `exchangeInfo`; a constante não o
  usa. `min_notional: 50,0` nem bate com o snapshot de BTC (20).
- **`ρ` real do modelo por célula** — a quantidade de que a decisão depende.
  Mensurável hoje: Spearman entre a probabilidade OOF do Alpha e `ret_net`.
- **Capacidade de mercado**: NÃO EXISTE medição. Com nocional de $78–$268,
  provavelmente irrelevante — mas é inferência, não medição.

---

## §13. COMO O LIGHTGBM EXERCE A ESTRUTURA — engenharia de ML

**Diretriz do Manager (2026-08-26):** *"como o LightGBM e seus arquivos .py vão
calcular e exercer a aplicação da nova estrutura de features para cada ativo e
time frame? Talvez metade dos problemas do desempenho das features estejam
nesse ponto."*

A suspeita estava certa. Auditoria independente do pipeline de treino, com os
achados centrais **reverificados por execução** antes de entrarem aqui. Os três
primeiros são defeitos de contrato, não de ajuste — nenhum deles é sobre
escolher hiperparâmetro melhor.

### §13.1 O gate de purge é dimensionado para 7 features; o treino usa 69

`src/models/pipeline.py:559` chama:

```python
max_feature_lookback_ms = features_build.compute_max_feature_lookback_ms(
    tf_effective, resolution_id=resolution_id      # <- sem feature_ids
)
```

O parâmetro `feature_ids` cai no default `T1_FEATURE_IDS` (7), embora
`feature_ids_effective` já esteja calculado 16 linhas acima. **Verificado por
execução:**

```
purge dimensionado hoje (default T1, 7 features) : 1.020.378.446 ms = 11,8 dias
com o vetor real de produção (69, AG-207 aditivo): ExpandingFeatureLookbackError
   ofensoras: C09_range_pctile_expanding, C10_vol_expansion_flag,
              C11_vol_compression_flag, E15f_toptrader_ls_z,
              E17f_retail_vs_top_spread
```

O gate **existe, funciona e falharia alto** — e nunca é chamado com o conjunto
real. É precisamente a "opção A" que `AG-032` item 8 registra como escolha do
Manager (*"a feature listada precisa ser removida do conjunto ativo OU o CPCV
precisa rodar CONSCIENTEMENTE sem proteção de purge pra ela"*), desligada por
omissão de um argumento.

Agravante: `max_feature_window_bars` lê apenas os 10 campos de
`_WINDOW_FIELD_NAMES`, que cobrem só janelas T1. `C08_vol_pctile_rolling_1y`
(17.520 barras), `E03f_funding_cum_3d` (288) e `B10_stoch_k_14` não estão lá —
então a guarda de staleness também não dispara.

**O mecanismo de degradação:** o purge protege ~96 barras de alcance enquanto a
feature de maior lookback finito do conjunto ativo alcança 17.520 — **182× a
mais**. Uma linha de treino logo após a fronteira do bloco de teste carrega,
dentro de `C08`/`C09`/`C10`/`C11`, estatística acumulada sobre o território de
teste inteiro. Não é vazamento de rótulo (B09 cobre isso via `t1`) — é
**vazamento de janela de feature**, e não há banned pattern que o nomeie.

Os outros dois call sites herdam o defeito: `src/validation/leakage.py:798` (a
suíte de vazamento reporta PASS contra uma proteção que não é a do treino) e
`src/validation/noise_floor_diagnostics.py:86`, usada por **toda** a campanha
`ADR-003`. Isso torna os Estágios 0–3 e o
`config/alpha_hyperparams_by_combo.yaml` não interpretáveis.

### §13.2 O filtro de warmup não filtra: `is_not_null()` deixa NaN passar

`src/models/dataset.py:497-503` (`side_subset`, o lado de **treino**) tem
`T1_FEATURE_IDS` hardcoded — sem parâmetro `feature_ids` — e filtra com
`is_not_null()`. **Verificado por execução:**

```
Polars: is_not_null() sobre [1.0, NaN, None, 3.0] -> [True, True, False, True]
NaN passa pelo filtro: True
```

E o efeito no dado real (BTCUSDT/R1, 16.696 barras):

```
D07f_taker_imbalance_1m_agg : 16.696 NaN de 16.696 -- ZERO valores finitos
colunas com algum NaN       : 69 de 69
colunas 100% mortas         : ['D07f_taker_imbalance_1m_agg']
```

`D07f` é 100% morta sob dollar bar por construção — `build.py:1038` só carrega
`klines_1m` quando `bar_source == "time_15m"`. Ela atravessa o pipeline inteiro
e chega ao relatório como `{"constraint": 0, "mean_ic": null,
"n_consistent": 0}`: uma coluna inexistente ocupando 1/69 do vetor, sem erro,
warning ou gate. Se o filtro fosse `is_not_null() & is_not_nan()`, o conjunto
de teste seria **vazio** e o defeito teria falhado alto na primeira execução.
Passou porque a guarda não guarda.

**Assimetria treino/teste, e ela é a parte que degrada o modelo:**
`_unique_test_bars` (`alpha.py:977`) **recebe** `feature_ids` e filtra por
todas; `side_subset` não. As duas populações diferem sistematicamente no
prefixo temporal de cada símbolo. LightGBM aprende uma *default direction* para
o missing de `C08`/`C09`/`E15f` que é, na prática, um indicador de "início da
série" — regime de 2020-2021 — e essa direção **nunca é exercida no teste**,
porque lá aquelas linhas foram removidas. Ganho in-fold inflado por um split
que é marcador de calendário, com zero transferência OOS.

### §13.3 A regularização é dimensionada em linhas, não em observações independentes

`ESS = Σ uniqueness` está medido e persistido (`AG-211`) e **nunca é consumido
por nenhuma decisão**:

| célula | linhas | **ESS** | ESS/linhas |
|---|---|---|---|
| BTCUSDT/R1 | 446.223 | 47.549 | 0,3645 |
| BNBUSDT/R2 | 164.219 | 19.085 | 0,3896 |
| ETHUSDT/R3 | 79.969 | 9.202 | 0,3896 |

Razão R1/R3 = **5,17×** — e o mesmo `n_estimators=300`, `learning_rate=0,03`,
`num_leaves=8`, `min_child_samples=20` e `max_bin=255` atende as duas.

`min_child_samples` conta **linhas**. Com `ESS/linhas = 0,3645`, uma folha
mínima de 20 linhas tem **≈7,3 observações independentes**. O erro-padrão de
`p` nessa folha é `√(0,45·0,55/7,3) ≈ 0,184` — **±18,4 pontos percentuais**,
contra um lift-alvo de ~5pp. **Cada folha mínima do default de produção é
ruído com amplitude 3,7× o sinal procurado.** Foi isso que a campanha do
`ADR-003` descobriu por força bruta ao eleger `min_child_samples = 2000` em 7
de 10 combos.

E `min_sum_hessian_in_leaf = 0,001` é **estruturalmente inerte**: sob
`objective="binary"`, a hessiana por amostra é `p(1−p)·w`; com `p = 0,4505` e
`w̄ ≈ 1,12`, o piso que `min_child_samples` já impõe é `≈5,5` (mcs=20) ou
`≈555` (mcs=2000). O valor configurado está 3 a 5 ordens de grandeza abaixo do
ponto de mordida — e o `sweep_range` declarado termina em 5,0. Evidência
independente: no Estágio 1 do `ADR-003`, os três valores varridos
(0,1 / 1,0 / 5,0) devolvem `pooled_sharpe = −3,2502095193836498`
**bit-idêntico** entre si e à âncora. **30 trials foram cobrados de
`N_lifetime` para responder uma pergunta que a álgebra já respondia.**

### §13.4 As restrições monotônicas são impostas sem piso de magnitude

`monotonic.py::_assign_from_ic` decide o sinal por `mean_ic > 0` e impõe a
restrição sempre que `n_consistent >= 6`. **Não há teste sobre `|mean_ic|`.**
No artefato real: `A08_upper_wick_ratio` recebe `+1` com `mean_ic = 0,00726`;
`E05f_time_to_funding_h` recebe `+1` com `0,00780`. Com `ESS = 47.549`, o
erro-padrão de um IC é `≈0,0046` — restrições saindo a **~1,6σ**.

Os 6 "ambientes" não são réplicas independentes: `environments.py` particiona
**a mesma série** por tercil de custo × regime. Sob IC nulo e independência
ideal, `P(6/6) = 3,1%`; com 62 features × 2 lados são **~4 restrições espúrias
esperadas** antes de contar a correlação entre ambientes.

E a restrição é **dura**: se o sinal estiver errado ela não degrada
suavemente — proíbe a forma correta. Com `num_leaves = 2..3` (o que a campanha
elegeu), uma restrição invertida numa feature de gain alto é ~1/3 do modelo.

Somado: `AG-213` já documenta que o IC é medido contra `ret_net` e a restrição
é aplicada sobre `P(TP)`, com 3 discordâncias em 7 features T1 — e
`fit_side_model:769` usa a constraint derivada de `ret_net` **sem consultar**
`screen_target_agreement`. O diagnóstico existe, é reportado, e não bloqueia
nada.

### §13.5 O desenho novo

Cinco mudanças de contrato. Nenhuma é escolha de hiperparâmetro.

**(1) O vetor é resolvido uma vez e atravessa o pipeline inteiro.**
`feature_ids_effective` passa a ser argumento obrigatório de
`compute_max_feature_lookback_ms`, `side_subset`, `_unique_test_bars`,
`leakage.run_all_leakage_tests` e `noise_floor_diagnostics`. Nenhuma dessas
funções mantém default de `T1_FEATURE_IDS` — o default é o que permitiu o
defeito. Um teste trava que os cinco recebem o mesmo objeto.

**(2) NaN é erro, não silêncio.** Na fronteira (`build.py:879`), NaN vira null
(`nan_to_null=True`), e o filtro passa a ser `is_not_null()` de verdade. Toda
coluna 100% nula em qualquer célula levanta `ValueError` nomeando a coluna e a
célula — `D07f` sob dollar bar deve **falhar o build**, não chegar ao
relatório. O censo de nulos por coluna × célula é persistido como artefato:
com 69 de 69 colunas contendo NaN, isso é informação de primeira ordem sobre a
amostra efetiva e hoje não existe em lugar nenhum.

**(3) A regularização escala com `ESS`, não com linhas.** Por célula:

```
min_child_samples(célula) = ceil(n_obs_independentes_alvo / (ESS/linhas))
min_sum_hessian_in_leaf(célula) = min_child_samples × w̄ × p(1−p)
```

com `n_obs_independentes_alvo` declarado a priori (o número que decide o
erro-padrão aceitável por folha) e `w̄`, `p` medidos in-fold. Isso substitui
dois `ASSUMED` por uma derivação — e é o que o próprio `source` de
`constants.yaml` já pede, com `TBD` explícito porque `w̄` "ainda não foi
medido". `early_stopping` sobre o sub-split de calibração — que já existe, já é
purgável e já não é o `fit` — resolve `n_estimators` por célula sem gastar
trial.

**(4) Constraint monotônica exige magnitude, não só sinal.** Piso
`|mean_ic| ≥ k · SE(ESS)` com `k` declarado a priori; `screen_target_agreement`
vira **bloqueio**, não relatório — discordância entre o alvo do IC (`ret_net`)
e o alvo do modelo (`P(TP)`) zera a constraint em vez de impô-la. E
`_ECONOMIC_FORCED_CONSTRAINT` falha alto quando a feature referenciada por
string não está no vetor, em vez de virar no-op.

**(5) A célula é a unidade de configuração, e ela declara o que usou.** O
manifesto de cada modelo passa a conter `feature_ids`, `ESS`, `min_child_
samples` derivado, `purge_ms` efetivo e o hash do conjunto — e a carga verifica
`manifest.feature_ids == booster.feature_name()`. Hoje
`alpha_hyperparams_by_combo.yaml` declara `feature_ids_ref: SUPPORT_FEATURE_IDS`
("substitui T1, nunca soma"), premissa que o Manager **retificou** em
`AG-223-ADDENDUM` — os hiperparâmetros foram medidos sob um vetor que não é o
de produção, e sobre labels pré-`AG-229`. `load_hyperparams_by_combo` não
verifica nem um nem outro.

### §13.6 Interação com §12 — por que isto muda a decisão de grade

`§12` decidiu R3 sob um `ρ` hipotético. `§13.3` mostra que o `ρ` **realizável**
depende da célula: com `ESS = 9.202` em ETHUSDT/R3 e `min_child_samples = 20`,
as folhas têm ~7,8 observações independentes sobre um total de 9.202 — o modelo
não consegue estimar nada com granularidade útil. R3 tem a melhor economia por
trade **e** a pior amostra; sem a correção (3), a vantagem econômica de R3 é
consumida pela variância de estimação.

Isso não inverte a decisão de grade — reforça que ela é **condicional à
correção do pipeline**. Promover R3 com `min_child_samples = 20` seria escolher
a grade certa e destruí-la na configuração.

### §13.7 Ordem de implementação

1. **`feature_ids` obrigatório nos 5 call sites** (§13.5-1). Vai fazer o gate
   falhar alto com as 5 features expanding — comportamento correto, e força a
   decisão do Manager sobre elas.
2. **NaN → null na fronteira + falha alta em coluna morta** (§13.5-2). Fecha
   `D07f` e a assimetria treino/teste.
3. **Censo de nulos por coluna × célula**, persistido. Barato, e é o insumo de 3.
4. **Regularização derivada de `ESS`** (§13.5-3), com `w̄` medido — fecha o
   `TBD` que `constants.yaml` declara.
5. **`early_stopping` sobre o split de calibração.**
6. **Piso de magnitude nas constraints** (§13.5-4).
7. **Manifesto completo por célula** (§13.5-5).

Os itens 1 e 2 são pré-requisito de tudo: enquanto o purge for dimensionado
para 7 features e o filtro deixar NaN passar, **nenhuma medição do Alpha é
interpretável** — inclusive as que sustentam `AG-244`, `ADR-003` e o `ρ` de
que §12 depende.

### §13.8 O que isto responde à pergunta do Manager

*"Talvez metade dos problemas do desempenho das features estejam nesse ponto."*

Não dá para quantificar "metade" sem rodar as correções. O que dá para afirmar,
verificado: **as três medições que o projeto usa para julgar features —
`AG-244` (lift do gate), `ADR-003` (campanha de hiperparâmetro) e os
diagnósticos de `gain` — foram todas produzidas sob um purge dimensionado para
um décimo do vetor, com uma coluna 100% morta dentro dele e com populações de
treino e teste filtradas por critérios diferentes.** Nenhuma delas é evidência
sobre as features enquanto isso não for corrigido.
