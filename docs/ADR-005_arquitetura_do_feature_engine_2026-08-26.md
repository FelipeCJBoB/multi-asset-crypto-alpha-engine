# ADR-005 — Arquitetura do Feature Engine: estratificar por função e por evidência

**Versão:** 2 (2026-08-26) — reescreve a v1 do mesmo dia; ver §0.2
**Status por parte** (2026-08-26):
- **§1–§9 (estratificação em camadas, critério de evidência): REPROVADO** na revisão independente de `project_assurance` — ver §11. **Não ratificar como está.**
- **§14 (v3 — corrige `AG-270`/`AG-271`/`AG-272`/`AG-274`): PROPOSTO, v2 (2026-08-26).** A v1 desta seção foi **REVISADA por `project_assurance` e REPROVADA** — 1 CRITICAL (a alegação "`AG-272` fechado"/"união cobre as 72" era falsa: 23 features sem camada, verificado por reconstrução de conjunto) + 1 HIGH (`E27f` violava a própria regra "nenhuma coluna em duas camadas") + 4 MEDIUM + 2 LOW — ver §14.7 pro detalhe completo e as correções. Todos corrigidos nesta v2: `L4` recalculada pra **43** (era 21 antes desta correção — a v1 de §14 já tinha corrigido de 29 pra 21, mas errou ao não dar camada às `INCOERENTE_DIMENSIONAL`/`ERRO_CATEGORICO`), `E27f` declarado como 2ª exceção deliberada (dupla `L1`+`L2`), união agora verificada = 72 exatas por script. Fecha os 3 pré-requisitos de §11.5 (modelo nulo por símbolo, BH com unidade declarada, eixo 2 persistido — `AG-294`/`AG-299`, ambos em código, com um bug real corrigido no eixo 2 nesta v2 — piso de `n_semestres_validos`). Resultado central inalterado pela correção: `L2` é **vazia** sob o eixo 1 corrigido (nem `E16f` nem as 7 `T1` passam) — `L2` fica definida como as 7 `T1` de hoje, por ausência de candidato, não por validação. **Esta v2 FOI revisada** (2ª rodada, 2026-08-26): 6 das 7 correções CONFIRMADAS por reconstrução independente; a 7ª (sincronia `§3`/`§5.2`/`§5.3`) só PARCIAL — 2 menções desatualizadas a mais achadas em `§2.1`/fim de `§2.2` (corrigidas). A 2ª rodada também achou que o defeito de `E02f`/`C07`/`D03f`/`E15f`/`E17f` citado em `§14.3` não era "sem diagnóstico" — é dívida já aberta do `AG-030` desde 2026-08-17, nunca conectada (corrigido em `§14.3`). Nenhum achado da classe do CRITICAL original desta vez.
- **§12 (grade de produção, decisão manual): PROPOSTO**, decisão de prosa não revisada por `project_assurance` (só o código de apoio foi). Independente das partes reprovadas — não usa o critério de §2.2 nem a tabela de IC. **Implementação em `src/analysis/production_grade_gate.py` REVISADA por `project_assurance` e REPROVADA na 1ª versão** (1 CRITICAL + 2 HIGH, `AG-288`/`AG-289`/`AG-290`) — todos corrigidos e reverificados rodando o script de verdade (ver §12.8): a correção reproduz a decisão de §12.6 (`BTCUSDT/R3` excluída, capacidade de R1 bate com §12.4 dentro de ~3,5%). `AG-293` (achado à parte, não coberto pela revisão original): o backfill de dado real está ~18 dias atrasado — a decisão em si não depende disso, mas rodar o gate com `--asof` de hoje falha até o backfill ser atualizado.
- **§13 (engenharia de ML): PROPOSTO**, não revisado. Achados centrais reverificados por execução; independente de §1–§9. **Delegado para outra sessão** (decisão do Manager, 2026-08-26) — nada implementado pela sessão que escreveu a v1.
- **§13 v2 (engenharia de ML, Data Science, Engenharia de Dados): PROPOSTO**, não revisado. É a sessão delegada acima, entregando: audita a v1 item a item (§13.9), acrescenta 2 achados P0 e 2 P1 (§13.10–§13.13), emenda 3 dos 5 itens de §13.5 (§13.14), arquiva 4 hipóteses refutadas por medição (§13.15) e registra em §13.19 **seis achados próprios que não sobreviveram ao reexame**. Ordem de `§13.17` em execução — **itens 1, 2, 3, 3b, 4, 10 e 11b EXECUTADOS** (ver `§13.20`–`§13.22`); item 11 **parcialmente** (o GATE já pré-existia sem ter sido reconhecido como tal — `§13.22` — e o teto de capacidade por ranking de margem é código novo, opt-in, não promovido); itens 5, 6, 7, 8, 9 **bloqueados** atrás do retreino represado (decisão do Manager, 2026-08-26 — o vetor de 69 features pode cair quando a sessão paralela terminar a reprogramação).
  - Item 1 (`feature_ids` obrigatório, 5 call sites): `AG-298`.
  - Item 2 (NaN→null na fronteira, coluna morta falha alto): `AG-300`.
  - Item 3 (censo de nulos por coluna × célula): `AG-308`.
  - Item 3b (detector de linhagem label↔registro, substitui o 3c rejeitado): `AG-309`.
  - Item 4 (peso do calibrador, opção b): `AG-312`.
  - Item 10 (manifesto completo + verificação na carga): `§13.21`.
  - Item 11 / 11b (`p̂ > breakeven(linha)`, censo de admissibilidade): `§13.20`, `§13.22`.
- **`AG-295` (A13/E10f, achado sobre o Alpha EM PRODUÇÃO, independente de §1–§9/§14): EXECUTADO 2026-08-26** — as 2 correções que o achado descrevia como propostas/investigadas mas não adotadas foram cortadas pra produção, aprovação explícita do Manager. `E10f_oi_change_z_48`: `registry.yaml` v1→v2 (delta calculado na cadência nativa da fonte, não mais depois do alinhamento por barra). `feature_a13_ema_window`: `scaling_invariant` `clock`→`bar_count` (`config/constants.yaml`), `ema_window=48` fixo nas 3 grades — a maquinaria de escala por `bar_source` foi removida de `src/features/build.py`. Ver addendum `2026-08-26b` na entrada `AG-295` do log e `§14.3` (correção `2026-08-26b`) pro detalhe completo.

**Isto ALTERA defaults de produção** (parágrafo acima) — `E10f`/`A13` mudam de valor sob R2/R3 (A13 bit-exato só sob R1); exige relabel/retrain de qualquer modelo já treinado. Fora disso, nenhuma coluna de feature foi removida. `src/analysis/production_grade_gate.py` é código novo, decision-support (mesmo status de `feasibility.py`) — não é consumido por nenhum pipeline de treino/execução.

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
| **L2 — Núcleo de sinal** | passa nos dois eixos de §2.2 | **sim** | ~~`E16f_global_ls_ratio`~~ **VAZIA** — `AG-294` (2026-08-26), ver correção ao fim de §2.2 |
| **L3 — Em observação** | tese declarada, sem evidência suficiente | não, recalculada | ~~as `TESE_OK` restantes`~~ **17** (11 `TESE_OK` + 5 momentum `A01`-`A04`/`A06` + `E18f` via quarentena) — `§14.2`/`§14.3` (2026-08-26) |
| **L4 — Aposentada** | sem mecanismo **e** sem sinal, OU construção comprovadamente quebrada sem outro papel | não, nem calculada | ~~as 29 `SEM_MECANISMO` sem descoberta~~ **43** (21 `SEM_MECANISMO` restante + 22 `INCOERENTE_DIMENSIONAL`/`ERRO_CATEGORICO` sem outro destino) — `§14.3`/`§14.4` (2026-08-26) |

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

**CORREÇÃO 2026-08-26 (`AG-294`) — a tabela do eixo 1 acima estava
calibrada na unidade errada, e a correção implementada é PIOR para `E16f`
do que a estimativa a mão de `AG-270`.** `project_assurance` (`AG-270`)
já tinha achado que a unidade de independência real é o SÍMBOLO (5), não a
CÉLULA (15) — 72% dos blocos símbolo×resolução são perfeitamente
concordantes, e `binomial(15; 0,146)` presume 15 ensaios independentes que
não existem. Isso foi implementado como código reproduzível
(`src.analysis.feature_promotion_criterion`, núcleo puro + 27 testes),
com duas correções adicionais em relação à estimativa a mão do `AG-270`:
símbolo-descoberta é MAIORIA (`≥2/3` resoluções) BH-discovery — binário,
não fração contínua — e `p_símbolo` é MEDIDO empiricamente sobre o painel
(`0,0667`), não herdado do `p=0,146` de célula sem remedir. BH `q=0,10`
agora roda de verdade (o único dado persistido antes era
`pico_significativo`, limiar fixo `|t|≥2`, sem correção de múltiplos
testes nenhuma).

Rodado contra os 3 relatórios reais de IC por horizonte:

| `k ≥` | esperado sob H₀ | observado |
|---|---|---|
| 1 | 21,01 | 19 |
| 2 | 2,79 | 2 (`E18f` + `K04_session_us`, dummy de calendário) |
| 3 | 0,19 | 1 (só `E18f`, o artefato do `AG-266`) |
| 4 | 0,007 | 1 |
| 5 | 9,5·10⁻⁵ | 1 |

**`E16f_global_ls_ratio` cai para 1 símbolo (só `SOLUSDT`)** — dentro do
ruído esperado em `k≥1` (observado 19 contra 21 esperado), não os ~2,3
que `AG-270` estimou a mão. **`L2 = {}`, vazia — não `L2 = {E16f}` com 1
coluna fraca.** Nenhuma feature nova passa no eixo 1 sob o teste
corrigido; os únicos candidatos em `k≥2` são o artefato já quarentenado
(`E18f`) e uma dummy de calendário sem mecanismo econômico plausível.

Consequência: `T1` (as 7 features originais) permanece o único vetor de
treino defensável hoje. A Opção C (§3) continua estruturalmente correta —
ela já separava "sem sinal hoje" de "sem mecanismo". ~~§3/§4 abaixo ainda
usam a versão antiga da tabela e não foram atualizados — é o próximo
passo da v3, não decidido aqui.~~ **JÁ REESCRITO em `§14.5` (2026-08-26)**
— `L2` vazia, `L4=43`; ver lá pra decisão revisada das opções, não aqui.
Detalhe completo, incluindo o achado de borda (`D07f_taker_imbalance_1m_
agg` sem `pico_abs_t` em nenhuma das 15 células, tratado como `p=1,0`,
nunca descoberta): `AG-294`.

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

> **ATUALIZADO em §14.5 (2026-08-26) — este aviso corrigido pra apontar lá,
> achado `project_assurance` que a versão anterior desta nota nunca tinha
> sido trocada por um ponteiro.** As três opções abaixo, junto com §4,
> ainda discutem `L2` como se tivesse 1 coluna (`E16f`) — a correção do
> fim de §2.2 mede `L2` VAZIA, e §14.5 já é a reavaliação das três opções
> com `L2={}`/`L4=43`. Ler §14.5 antes de decidir a partir desta seção.

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
| `E18f` | 1 | **Quarentena** — artefato de fonte (`AG-266`); vive em `L3` (calculada, fora do treino), com `defeito_construcao` também `true` — §14.3 |
| `L4` — sem mecanismo, sem papel estrutural, sem candidatura a sinal | ~~29~~ **43** (`AG-271`/`AG-272`, §14.2-§14.4) | Sem tese e sem evidência, OU construção comprovadamente quebrada (`defeito_construcao`) sem outro papel. Saem também do cálculo. |
| `L3` — tese sem evidência suficiente, OU quarentena | ~~~15~~ **17** (§14.4) | Continuam calculadas; fora do treino até reteste/correção. |
| `L0` — primitivas | 2 | São insumo de outras colunas, não preditores. |
| `L1` — gate de regime | 4 | `ADR-001` §2.7 já tirou regime do vetor; `E27f` é exceção deliberada (também `L2`, §14.3) — as outras 3 ficaram por inércia. |

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
   Implementado (`AG-294`/`AG-299`) sob outros nomes que os originais
   citados aqui: `feature_promotion_bh_q`, `feature_temporal_stability_
   max_ratio`, `feature_temporal_stability_min_direction_frac`,
   `feature_temporal_stability_min_points_per_semester`,
   `feature_temporal_stability_min_semesters` (`config/constants.yaml`).
   **Correção 2026-08-26 (`AG-285`, §11.3, nunca fechada até agora):**
   não são `provenance: DERIVED` — são `ASSUMED`, classe B/C, com a
   ressalva de calibração de §2.2 registrada em cada entrada. `DERIVED`
   implicaria consequência de outra constante já medida; calibrar
   olhando 5 casos conhecidos é o oposto — mais próximo de `ASSUMED`
   honesto do que de uma derivação formal.
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

**Isolado 2026-08-26 (`AG-313`, `tools/diagnostics/measure_ag266_momentum_pearson_spearman_tension.py`, artefato em `experiments/ag266_momentum_pearson_spearman_tension_report.json`).**
A hipótese "caudas cancelam" foi testada DIRETO — cortar simetricamente as
observações de maior `|A01|` (0,1% a 10%) — e **não se sustenta na forma
simples**: em vez de Pearson convergir pra perto de Spearman conforme a
cauda é cortada, ele vai pra **negativo** em todo nível de corte (BNB:
-0,0007 a -0,0045). O que de fato explica a divergência: as 20
observações (de 164.738) com maior contribuição ao numerador de Pearson
somam **341%** do numerador total (10 positivas, 10 negativas, quase se
cancelando) — o resto de ~164.700 observações "normais" contribui um
total líquido NEGATIVO. Pearson só fica levemente positivo por um
desequilíbrio marginal entre um punhado de pares extremos — assinatura
clássica de correlação instável sob curtose alta (BNB = 22,4; XRP = 122,5;
normal = 0).

**Onde o sinal de Spearman realmente mora:** o retorno seguinte MEDIANO
(não médio) por decil de `A01` é monotônico nos 5 símbolos — limpo em
BNB/SOL, com empates em zero (discretização) em XRP, com leve recuo no
último decil em BTC/ETH. O retorno MÉDIO por decil é ruidoso/não-
monotônico em todos — mesma dominância de outlier que quebra Pearson.
Leitura mais defensável: `Pearson≈0` aqui não é evidência de "sem
relação", é evidência de que Pearson é a ferramenta errada pra retorno de
cripto com essa curtose — o que pesa a favor de tratar o momentum de
**BNB** (não necessariamente XRP, cujo Spearman de +0,0027 é uma ordem de
grandeza mais fraco que o de BNB, +0,0152, com curtose 5-10× maior) como
candidato real. **Não é prova** — o Spearman de amostra cheia de BTC saiu
NEGATIVO (-0,0047) apesar do padrão mediano-por-decil majoritariamente
crescente, inconsistência não caracterizada. `AG-313` também registra uma
discrepância não reconciliada: a autocorrelação de Pearson de BTC medida
aqui (-0,0215) não bate com o `-0,0122` que `AG-266` cita pro mesmo
símbolo (mesmo sinal, quase 2× a magnitude — possível diferença de janela
de dado ou de tratamento de borda, não investigada). Faltam, se a
investigação continuar: repetir corte+decomposição por quartil temporal;
reconciliar essa discrepância de BTC; caracterizar a inconsistência
mediana-vs-Spearman de BTC. **Decisão de perseguir ou não a promoção
continua do Manager** — este achado dá mais base, não a substitui.

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

**HIGH:** ~~`AG-272`~~ **(citação órfã, corrigida 2026-08-26)** a partição não
é exaustiva (25 colunas sem camada, entre elas `A13` e `E10f`, ambas T1
vivas) e não tem precedência (`B07` é L1 e candidata a L4 ao mesmo tempo) —
a lição de `AG-122` na letra. O número `AG-272` foi reaproveitado por uma
sessão paralela no mesmo dia para um achado não relacionado (metodologia de
treino do LightGBM, `renumbered_from: AG-261`) — a citação aqui ficou
apontando para o entry errado; o achado original não tem número dedicado no
log, só esta menção em prosa. Fechado em §14 (`defeito_construcao`, estado
ortogonal que nomeia as 25/26 colunas e resolve a precedência). `AG-273`
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

- ~~Gate 0 nunca foi executado e persistido.~~ **FECHADO em 2026-08-26**,
  na 2ª tentativa. A 1ª versão de `src/analysis/production_grade_gate.py`
  (+ `tests/unit/test_analysis_production_grade_gate.py`) foi revisada por
  `project_assurance` (Agent independente) e **REPROVADA**: 1 achado
  CRITICAL (`AG-288` — a agregação por grade somava capacidade por
  símbolo em vez de tirar a média, reintroduzindo o erro-v1 "orçamento ×
  N" um nível acima) e 2 HIGH (`AG-289` — preço não escopado a `asof`,
  lia o histórico inteiro; `AG-290` — schema de demanda incompatível com
  o artefato citado). Os três foram corrigidos, e **`AG-289` teve uma 2ª
  volta**: mesmo escopado a `asof`, usar MEDIANA de 30 dias ainda dava
  preço baixo demais (viés sistemático contra ativo em tendência de alta)
  e deixava de excluir `BTCUSDT/R3` — trocado para ÚLTIMO close da
  janela. Rodado ao vivo (`--equity 196.85 --asof 2026-08-08`, a data
  real de cobertura do dado — ver `AG-293`, o backfill está ~18 dias
  atrasado): `capacidade_trades_mes_grade` R1=49,76 (bate com os 48,0 de
  §12.4 dentro de ~3,5%), e **`BTCUSDT/R3` volta a ser excluída**
  (`stop_max_pct`=0,7585% contra `stop_pct`=0,7671%), reproduzindo a
  decisão de §12.6. `equity`/`asof` seguem parâmetros obrigatórios (B17/
  B01). Detalhe completo: `AG-288`..`AG-293`. Mesma limitação de
  `stop_pct` já registrada abaixo (usa a célula de produção GLOBAL do
  S1, não overrides por combo) — herdada, não escondida.
  **Rodado com o equity REAL do usuário 2026-08-26** (`--equity 213.80`
  — R$ 1.100 convertidos à cotação do dia, ~R$5,145/USD — `--asof
  2026-08-08`, mesma data de cobertura de dado, hoje ainda sem backfill
  novo): **as 15 células passam no teto de quantização R1 — 0
  excluídas**, incluindo `BTCUSDT/R3` (`stop_max_pct`=0,8238% contra
  `stop_pct`=0,7671%), que tinha sido excluída na rodada de verificação
  acima com `equity=196,85`. Não é uma mudança de critério — é o mesmo
  script, `equity` maior relaxa o teto de quantização por construção
  (`stop_max = equity × risk_per_trade / (2 × unit_notional)`, cresce
  com `equity`). **Isto NÃO reproduz a decisão completa de §12.4**
  (capacidade vs. demanda MEDIDA, que concluiu "R3 em 4 ativos") — só o
  eixo de admissibilidade de quantização + capacidade por orçamento de
  fee, sem demanda plugada (`--demand-report` não tem schema real ainda,
  mesmo gap já registrado abaixo).
  **Correção 2026-08-26b (achado da própria varredura de pendências,
  não da rodada original):** o parágrafo anterior desta entrada alegava
  "capacidade escala ~linear com `equity`, um `equity` maior só alarga
  a folga" — **isso está errado**, e a formula já persistida no
  artefato mostra por quê: `capacidade_trades_mes = (fee_budget_monthly
  × equity) / custo_trade`, onde `custo_trade = (equity × risk_per_trade
  / stop_pct) × (cost_bps/10000)` — substituindo, `equity` se CANCELA
  algebricamente (aparece no numerador e no denominador). Capacidade é
  **invariante** a `equity`, não escala com ele. Confirmado empiricamente:
  `capacidade_trades_mes_grade` R1 = 49,76 nas DUAS rodadas
  (`equity=196,85` e `equity=213,80`), valor idêntico. O que de fato
  escala com `equity` é só `stop_max_pct` (o teto de QUANTIZAÇÃO,
  `stop_max = equity × risk_per_trade / (2 × unit_notional)`) — é essa
  variável, não a capacidade, que muda entre as duas rodadas e explica
  `BTCUSDT/R3` deixar de ser excluída. A conclusão prática (0 exclusões
  com `equity=213,80`) continua correta; a explicação causal estava
  errada. Isto NÃO reproduz a decisão completa de §12.4 (capacidade vs.
  demanda MEDIDA, que concluiu "R3 em 4 ativos") — os números exatos de
  §12.4 (baseados em `equity=196,85`) não foram reprocessados com
  `213,80`, e não precisam ser só por causa do equity (capacidade não
  depende dele) — precisariam ser reprocessados se a DEMANDA medida
  mudasse, o que não foi verificado aqui. Artefato:
  `experiments/production_grade_gate_report.json` (sobrescrito, é o
  único caminho de saída do script).
- **O S1 filtra só o piso R2, nunca o teto R1.** Por isso R3 aparece com 7
  células viáveis e R1 com 5 — a comparação entre grades foi feita sobre
  conjuntos filtrados por critérios diferentes.
- **`step_size` em `constants.yaml` é escalar BTC-único.** O dado por ativo
  já está no snapshot de `exchangeInfo`; a constante não o usa —
  `production_grade_gate.py` (abaixo) já lê o real via `load_filters_asof`,
  em vez desta constante. ~~`min_notional: 50,0` nem bate com o snapshot de
  BTC (20).~~ **CORRIGIDO 2026-08-26** (`AG-292`, `project_assurance`):
  errado — o bloco `BTCUSDT` do snapshot tem `min_notional=50`, batendo
  exatamente com `constants.yaml`; o "20" citado é de outro símbolo do
  arquivo (lista todos os pares da Binance Futures, não só os 5 do
  projeto). `production_grade_gate.py` nunca usa `min_notional`, então o
  erro não afetou nenhum código — só a narrativa desta linha.
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

---

# §13 v2 — engenharia de ML, Data Science e Engenharia de Dados

**Status:** PROPOSTO, não revisado por terceiro. Aditivo: `§13.1`-`§13.8`
**não são renumeradas** (`AG-266` e commits já referenciam seções por número,
mesma razão da nota de `§10`).
**Autor:** persona `lgbm-crypto-quant` (`docs/prompts/lgbm-crypto-quant.md`),
2026-08-26. **Antecessor:** `§13 v1`, persona `feature-thesis-auditor`.
**AGs abertos por esta seção:** `AG-296`, `AG-297`.

> **Regra de leitura.** Todo número foi medido contra o dado real ou lido da
> documentação oficial da biblioteca. Onde uma hipótese foi **refutada pela
> própria medição**, ela está em `§13.15`/`§13.19` com o resultado — não
> removida. Seis achados meus não sobreviveram inteiros.

## §13.9 Auditoria de `§13 v1` — o que sustento, o que corrijo, o que refuto

`§13 v1` foi verificado item a item contra o código. **Os três achados
centrais procedem e são graves.** Confirmo-os sem ressalva:

| `§13 v1` | veredito | verificação |
|---|---|---|
| **§13.1** purge dimensionado para 7 features, treino usa 69 | **PROCEDE** | `pipeline.py:580` chama `compute_max_feature_lookback_ms(tf_effective, resolution_id=...)` sem `feature_ids`, com `feature_ids_effective` já resolvido em `:563` |
| **§13.1** `_WINDOW_FIELD_NAMES` cobre só janelas T1 | **PROCEDE** | `build.py:435-446`: 10 campos, `max = 96`; `C08_vol_pctile_rolling_1y` não está entre eles |
| **§13.2** `is_not_null()` deixa NaN passar | **PROCEDE** | `dataset.py:497-503` com `T1_FEATURE_IDS` hardcoded; `build_design_matrix` (`alpha.py:201`) é `df.select(...).to_numpy()`, que materializa null como NaN |
| **§13.2** assimetria treino/teste | **PROCEDE, e é maior que o descrito** | `_unique_test_bars` (`alpha.py:988`) recebe `feature_ids`, `side_subset` não — ver `§13.9.1` |
| **§13.4** constraint sem piso de magnitude | **PROCEDE** | `monotonic.py:158-163`: `dominant = 1 if mean_ic > 0`, sem qualquer teste sobre `|mean_ic|` |
| **§13.5-1/-2/-5** vetor único, NaN→null, manifesto | **ENDOSSO integral** | são contrato, não ajuste; nada a acrescentar |

Três itens de `§13 v1` **precisam de correção antes de virar
implementação**, e um deles é aritmético:

### §13.9.1 A assimetria treino/teste tem **duas** pernas, não uma

`§13.2` nomeia a perna do warmup/NaN. Existe uma segunda, já registrada em
`AG-210(b)` e citada em `ADR-004 §1 (F2)`: **`side_subset` remove `NOFILL`,
`_unique_test_bars` não.** Treino e inferência operam sobre populações que
diferem por dois critérios independentes, não um.

**Boa notícia medida:** `ADR-004 (F2)` dimensiona essa perna em **10,7% —
"uma barra em cada dez"**. Medido hoje sobre os labels de produção:

| célula | `NOFILL` hoje | `NOFILL` citado em `ADR-004` |
|---|---|---|
| BTCUSDT/R1 | **1,54%** | 10,73% |
| ETHUSDT/R1 | **1,27%** | — |
| SOLUSDT/R1 | **2,17%** | — |
| BNBUSDT/R1 | **1,72%** | — |
| XRPUSDT/R1 | **1,21%** | — |

O relabel de `AG-229` (fill por `agg_trades`) reduziu `NOFILL` em **7×**.
A segunda perna encolheu de primeira ordem para ~1,5% — continua sendo
assimetria e continua tendo que ser fechada, mas **não é mais "uma barra em
cada dez"**, e `ADR-004` precisa da ressalva. Isso é sintoma de `§13.11`.

### §13.9.2 A tabela de `§13.3` não fecha com as próprias colunas

`§13.3` publica:

```
BTCUSDT/R1 | linhas 446.223 | ESS 47.549 | ESS/linhas 0,3645
```

`47.549 / 446.223 = 0,1065`, não `0,3645`. As duas colunas são **populações
diferentes**: `ESS` vem de `SideModelResult.sum_uniqueness_train` (um lado,
o treino de um fold) e `linhas` vem de outro lugar. Medido diretamente sobre
`labels.parquet` de hoje:

| célula | linhas (lado=1, pós-NOFILL) | `Σ uniqueness` | razão |
|---|---|---|---|
| BTCUSDT/R1 | 215.442 | 84.028 | **0,3900** |
| XRPUSDT/R1 | 170.953 | 65.201 | 0,3814 |
| BNBUSDT/R2 | 80.748 | 32.159 | 0,3983 |
| ETHUSDT/R3 | 39.485 | 15.316 | 0,3879 |
| SOLUSDT/R3 | 40.659 | 15.911 | 0,3913 |

**A razão de `§13.3` está certa** (0,38–0,40 medido de forma independente,
contra 0,3645–0,3896 declarado) — e a conclusão qualitativa também: ~61% do
`n` aparente é redundância. **A coluna `linhas` é que está errada**, e o
valor `446.223` identifica a fonte: é exatamente `n_labels` da última linha
`BTCUSDT/R1` de `data/label_engine_runs/label_engine_runs.parquet`, que é
**pré-relabel**. O count real hoje é 437.630 (o mesmo que `AG-230-ADDENDUM`
usa). Sintoma de `§13.11`.

### §13.9.3 `§13.3` alarma sobre uma configuração que a produção não usa em 9 de 10 células

`§13.3` calcula: `min_child_samples = 20` → ~7,3 observações independentes
por folha → erro-padrão de `±18,4 pp` contra lift-alvo de ~5 pp → *"cada
folha mínima do default de produção é ruído com amplitude 3,7× o sinal"*.

A aritmética está certa **para o default de `constants.yaml`**
(`alpha_lgbm_min_child_samples: 20`). Mas `config/alpha_hyperparams_by_combo.yaml`
já existe, é `provenance: MEASURED`, e diz:

| `min_child_samples` | células |
|---|---|
| **2.000** | 7 de 10 |
| 500 | 2 de 10 |
| 20 | 1 de 10 (`BNBUSDT_R2`) |

Com `mcs = 2000` e `ESS/linhas = 0,39`, a folha mínima tem **780
observações independentes** → `SE(p) = √(0,25/780) = 1,79 pp`, contra o
`±18,4 pp` de `§13.3`. **Uma ordem de grandeza de diferença.**

E há um segundo motivo, mais forte, para o alarme não valer como escrito:
as 10 células escolheram `max_depth = 2` e `num_leaves ∈ {2,3}` — **tocos**.
Uma árvore de 2 folhas sobre 160 mil linhas não chega perto de `mcs = 2000`
a não ser num split extremamente desbalanceado. **O guardrail não morde
porque a árvore não tem profundidade para fazê-lo morder.**

`§13.3` continua **certo no princípio** (regularização dimensionada em
linhas, não em observações independentes) e **certo sobre o default**. O que
ele não pode afirmar é que descreve a configuração de produção. O caminho
`use_hyperparams_by_combo` existe em `pipeline.py:1246` — qual dos dois é
"produção" é uma pergunta em aberto que `§13.5-5` já tangencia e que
`§13.12` fecha.

---

## §13.10 **P0 — a probabilidade calibrada não é `P(TP)`. Viés medido: −13,0%**

Este é o achado que mais me preocupa, e ele não aparece em `§13 v1`.

### O mecanismo

`alpha.py:906`:

```python
calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
calibrator.fit(raw_calib, y_calib, sample_weight=w_calib)
```

Regressão isotônica ponderada minimiza `Σ wᵢ(yᵢ − f(xᵢ))²`. A solução em cada
patamar é a **média ponderada de `y`**, logo `f(x) = E_w[y | x]`.

E `w` não é uniforme. `src/labels/weights.py:153`:

```python
raw_weight = (out["uniqueness"] * out["ret_net"].abs()).to_numpy()
```

`sample_weight ∝ uniqueness × |ret_net|`. Sob triple barrier, `|ret_net|` é
**sistematicamente maior no `SL` do que no `TP`** — o custo de ida e volta
subtrai do ganho e soma à perda. Medido:

| célula | `|ret_net|` médio no TP | no SL | SL/TP |
|---|---|---|---|
| BTCUSDT/R1 | 0,00388 | 0,00500 | **1,29** |
| BNBUSDT/R1 | 0,00370 | 0,00476 | 1,29 |
| ETHUSDT/R1 | 0,00455 | 0,00568 | 1,25 |
| SOLUSDT/R3 | 0,01399 | 0,01483 | 1,06 |

O calibrador então **sub-pondera exatamente a classe positiva**.

### A medição

Isotônica ajustada sobre os `y` e `w` reais de BTCUSDT/R1 (lado long,
215.442 linhas, score sintético monótono para isolar o efeito do peso):

```
P(TP) real por contagem            : 0,4967
calibrado COM sample_weight (hoje) : 0,4323   viés = −0,0645  (−13,0%)
calibrado SEM sample_weight        : 0,4967   viés = −0,0000
```

**A saída do calibrador não estima `P(TP)`. Estima `P(TP)` sob uma medida
inclinada por `|ret_net|`, e o viés é de −6,45 pontos percentuais.**

### A opção (b) deixou de ser argumento e virou medição (2026-08-26)

A autovalidação desta v2 registrava, como o principal ponto fraco do
documento, que a recomendação (b) era *"argumento de primeiro princípio,
**não uma medição**"* — a medição provava que existe viés, não qual das três
saídas é a certa. Isso foi fechado. `P(TP)` estimada sob cada esquema de
peso, lado long, pós-`NOFILL`:

| célula | contagem (verdadeiro) | **só `uniqueness`** (b) | `uniqueness × \|ret_net\|` (hoje) |
|---|---|---|---|
| BTCUSDT/R1 | 0,4967 | **0,4971** `(+0,0004)` | 0,4323 `(−0,0645)` |
| ETHUSDT/R1 | 0,4990 | **0,4988** `(−0,0002)` | 0,4431 `(−0,0559)` |
| BNBUSDT/R1 | 0,4916 | **0,4904** `(−0,0012)` | 0,4264 `(−0,0652)` |
| SOLUSDT/R3 | 0,4942 | **0,4972** `(+0,0030)` | 0,4815 `(−0,0127)` |
| XRPUSDT/R3 | 0,4959 | **0,4971** `(+0,0013)` | 0,4751 `(−0,0207)` |

O viés de hoje vai de **−0,013 a −0,065**; sob (b), de **−0,0012 a +0,0030**
— **duas ordens de grandeza menor**, e sem sinal sistemático (três células
para cima, duas para baixo, ou seja ruído amostral e não inclinação).

Isso confirma o argumento estrutural: `uniqueness` corrige **redundância
estatística** e não se correlaciona com o desfecho; `|ret_net|` codifica
**importância econômica** e se correlaciona com ele por construção
(`r_SL > r_TP` por causa do custo). (b) mantém a correção que pertence a um
estimador e remove a que pertence a uma função de decisão.

**Ressalva que sobrevive:** (b) não é *provada* livre de viés — está medido
que o mecanismo conhecido foi removido e que o resíduo é da ordem do ruído
amostral em 5 células. Não é o mesmo que uma prova.

### Por que isso é P0

1. **A régua de `§1.1` está denominada em `P(TP)`.**
   `config/min_alpha_lift_by_combo.yaml` declara `p_tp_base`,
   `breakeven_wr` e `min_alpha_lift_ptp` — todos por contagem. Comparar a
   saída calibrada contra essa régua compara **duas grandezas diferentes**.
   O lift exigido é `+7,6%` a `+15,1%`; o viés de nível é `−13,0%`. **São
   da mesma ordem.**
2. **Todo diagnóstico de calibração fica errado.** `src/analysis/
   calibration_diagnostics.py` mede desvio entre probabilidade predita e
   frequência observada. Com o predito 13% baixo por construção, a curva de
   confiabilidade reporta um viés de modelo que é, na verdade, de
   ponderação.
3. **Não é o `scale_pos_weight` que salva.** Medido com LightGBM 4.7.0 (o
   do `uv.lock`), sobre `y`/`w` reais e features de ruído puro:

   | configuração | `p` médio predito |
   |---|---|
   | `spw = w_neg/w_pos = 1,3134` (WEIGHT, pós-`AG-272`) | 0,4999 |
   | `spw = n_neg/n_pos = 1,0132` (COUNT, legado) | 0,4356 |
   | `spw = 1,0` | 0,4324 |
   | **`P(TP)` verdadeiro por contagem** | **0,4967** |

   Nenhuma das três estima `P(TP)`; e o calibrador isotônico **sobrescreve o
   nível do booster de qualquer jeito** — o número que chega ao consumidor é
   sempre o `0,4323` ponderado.

### O que **não** muda, e é importante dizer — este é o limite honesto do achado

Duas coisas me impedem de chamar isto de "corrompe uma decisão automática
hoje", e as duas foram verificadas:

1. **`tau` é um quantil.** `tau = np.quantile(calibrated_train_all,
   1 − target_signal_rate)` (`alpha.py:910`), e quantil é invariante a
   reparametrização monótona. **A decisão de entrar em trade não muda com
   este achado.**
2. **`min_alpha_lift_ptp` não tem consumidor em código.** Verificado por
   varredura: `config/min_alpha_lift_by_combo.yaml` é **escrito** por
   `src/analysis/economic_gate.py:590` e não é lido por nenhum `.py`. A
   régua é hoje um gate aplicado por **pessoa**, lendo o número.

Então o dano atual é de **interpretação**, não de execução — e é precisamente
por isso que a hora de corrigir é agora. O `architecture_gaps_log` já
registra, como opção em aberto, tornar `min_alpha_lift_ptp` *"gate vinculante
de entrada de trial"*. **No dia em que essa opção for exercida, um gate
automático passa a comparar `0,4323` contra uma régua escrita em `0,4967`.**
Corrigir antes custa uma decisão; corrigir depois custa uma decisão mais uma
rodada de artefatos.

Enquanto isso, o que já está errado é toda leitura numérica: régua,
diagnóstico de calibração, e qualquer relatório que diga "o modelo prevê 52%
de chance de TP".

> Nota que reforça o ponto: o próprio `economic_gate.py:453-457` já carrega
> uma ressalva de nível (*"a ORDENAÇÃO é robusta, o NÍVEL absoluto não"*),
> por outro motivo — `round_trip_cost_bps_maker_prob`. São **dois** vieses
> de nível independentes empilhados sobre a mesma régua, cada um registrado
> num lugar diferente e nenhum dos dois no ponto de uso.

### As três saídas, e a recomendação

| opção | o que faz | custo | avaliação |
|---|---|---|---|
| **(a)** calibrador **sem** `sample_weight` | saída volta a ser `P(TP)` | muda o artefato; exige retreino | corrige o sintoma; discorda da unicidade (`B10`) no calibrador |
| **(b)** calibrador com **`uniqueness` apenas**, sem `|ret_net|` | respeita `B10` e remove a inclinação econômica | idem | **RECOMENDADA** |
| **(c)** manter e **renomear** | `p_hat` deixa de se chamar probabilidade; régua reescrita na mesma medida | zero código de treino | honesto, mas espalha a inclinação por todo o resto |

**Recomendo (b)**, e o argumento é de primeiro princípio: `uniqueness` corrige
**redundância estatística** (quantas observações independentes existem) e
pertence a qualquer estimador; `|ret_net|` codifica **importância econômica**
e pertence a uma função de decisão, não a uma estimativa de probabilidade.
Misturar os dois num calibrador produz um objeto que não é nem uma coisa nem
outra — que é exatamente o que a medição mostra.

> **Ressalva que preciso registrar contra mim mesmo:** a opção (b) muda o
> valor de todo modelo treinado. Se o Manager decidir (c), a decisão é
> defensável — mas então `min_alpha_lift_by_combo.yaml` precisa ser
> **recalculado na medida ponderada**, e nenhum documento pode voltar a
> chamar a saída de `P(TP)`. Não fazer nem (b) nem (c) é a única opção ruim.

---

## §13.11 **P0 — o registro do Label Engine descreve labels que não existem mais**

Achado de **Engenharia de Dados**, e ele é a causa-raiz de `§13.9.1` e
`§13.9.2`.

`data/label_engine_runs/label_engine_runs.parquet` é o registro append-only
do Label Engine — a proveniência de todo label de produção. Medido:

```
config_hash em data/labels/BTCUSDT/R1/v1/labels.parquet : 3599b765b7a53ff2
config_hash na última linha R1 do registro             : 67d2193fff4a1fae
config_hash distintos no registro, para R1              : 1
logged_at_utc máximo do registro inteiro                : 2026-08-24 01:12
mtime de labels.parquet                                 : 2026-08-25 15:45
```

**Os hashes não batem, e o registro só conhece um.** O relabel de `AG-229`
(2026-08-25) reescreveu as 15 combinações e **não apendou nenhuma linha de
run**. Idêntico em `HEAD` e no working tree — não é sujeira local.

Magnitude do erro que o registro carrega hoje, para `BTCUSDT/R1`:

| quantidade | registro | disco (medido) | erro |
|---|---|---|---|
| `n_labels` | 446.223 | 437.630 | +2,0% |
| `pct_nofill` | 0,10731 | 0,0154 | **7,0×** |
| `sum_uniqueness` | 137.991 | 167.968 | −17,8% |

### Por que isto é P0, e não higiene

Porque **os documentos de decisão leem esse registro**:

- `ADR-004 §0/§1` constrói `F1`, `F2` e `F3` sobre ele. `F2` ("NOFILL é
  10,7%") está 7× errado. `F1` ("edge bruto incondicional `= (0,451 −
  0,549)·1,5 = −0,147 ATR`") usa `P(TP) = 45,1%`; hoje `P(TP) = 49,67%`, o
  que dá **−0,0099 ATR** — **15× menor**. O fato fundacional de um ADR
  `PROPOSTO` mudou de ordem de grandeza sem que nada avisasse.
- `ADR-005 §13.3` usa `linhas = 446.223` (`§13.9.2`).
- `ADR-005 §12.4` deriva a **demanda** (`n_trades/n_eval_long`) de
  `experiments/alpha_deep_analysis_2026-08-24.json`, de 2026-08-24 — também
  pré-relabel. A decisão de promover **R3** compara capacidade (recalculada
  hoje) contra demanda (medida sob outros labels).
- Detalhe que fecha o diagnóstico: os `pct_tp`/`pct_sl` da tabela de
  `ADR-004 §0` (0,4022 / 0,4898 para BTCUSDT/R1) **não reproduzem nem o
  registro commitado** (0,3452 / 0,5461) **nem o disco**. Não consigo dizer
  de onde vieram — e essa é a definição operacional do problema: hoje não
  existe como saber a qual versão de label um número publicado pertence.

### Correção proposta

1. **`write_labels_atomic` e o append do registro viram uma transação.**
   Escrever `labels.parquet` sem apendar a linha de run passa a ser
   impossível, não improvável.
2. **`config_hash` vira campo obrigatório de todo artefato de análise.**
   Todo `.json` em `experiments/` que consome labels grava o `config_hash`
   de cada célula lida.
3. **Um gate de staleness**, barato e mecânico: um lint que, para cada
   artefato com `config_hash` declarado, compara contra o
   `labels.parquet` vigente e **falha** na divergência. É `B15`
   (`config_hash` do label = o da execução) estendido de
   *label↔execução* para *label↔análise* — mesma disciplina, fronteira
   nova.
4. **Reprocessar o registro** para as 15 células atuais, com a linha
   `renumbered`/`supersedes` apontando para a entrada antiga (append-only
   preservado, nada apagado).

---

## §13.12 **P1 — 10 configurações de hiperparâmetro sobre ~2 problemas independentes**

`config/alpha_hyperparams_by_combo.yaml` (`provenance: MEASURED`, ADR-003
Estágio 2, mediana de 5 seeds) entrega **10 vetores distintos**:

| parâmetro | valores escolhidos |
|---|---|
| `min_child_samples` | 20 · 500 · 2000 |
| `learning_rate` | 0,01 · 0,03 |
| `n_estimators` | 150 · 300 |
| `subsample` | 0,6 · 0,8 · 0,9 |
| `num_leaves` | 2 · 3 |
| `feature_fraction` | **0,3 em `BTCUSDT_R1`**, 1,0 nas outras 9 |

A capacidade total (`learning_rate × n_estimators`) varia de **3,0 a 9,0**
entre células — um fator **3** —, escolhida por busca.

E o arquivo cobre **10 das 15 células**: as outras 5 caem no vetor global de
`constants.yaml`, com warning (`pipeline.py:1248`). A grade de produção é,
portanto, uma **mistura de células calibradas e não calibradas** — o que
torna qualquer comparação entre grades (inclusive a de `§12`) uma comparação
entre objetos configurados por critérios diferentes. É o mesmo defeito que
`§12.8` já nomeia para o filtro S1 ("a comparação entre grades foi feita
sobre conjuntos filtrados por critérios diferentes"), repetido na camada do
hiperparâmetro.

**O problema não é o valor. É o denominador.** Quantas células
independentes existem?

- **Entre símbolos:** `experiments/cross_symbol_ess_report.json` já mede,
  pelo espectro da matriz de correlação dos 5 ativos:
  **`n_eff = 2,03`**, `hhi_effective = 0,492`, autovalor dominante `0,682`
  em 1.706 dias alinhados. Cinco ativos valem por dois.
- **Entre resoluções:** `§11.1` do próprio ADR-005 mede **197 de 275 blocos
  símbolo×feature (72%) perfeitamente concordantes** nas 3 resoluções, e
  conclui que a unidade efetiva é o símbolo, não a célula.

Compondo os dois: as 15 células valem por **~2 problemas independentes**.
Ajustar 10 vetores de hiperparâmetro sobre ~2 problemas independentes é o
mesmo erro que `§0.1` e `§11.1` já corrigiram duas vezes nesta linha de
trabalho — **tratar observações redundantes como independentes** — cometido
agora na camada do modelo, não na da feature.

> `§11.1` diz textualmente: *"O mesmo erro, duas vezes na mesma linha de
> trabalho."* Esta é a terceira, e é a mais cara: cada vetor entrou em
> `N_lifetime` e cada um pesa na deflação do DSR.

### O teste que decide, e ele é barato

Não proponho apagar o arquivo. Proponho **medir se ele carrega informação**:

```
H₀: um único vetor global de hiperparâmetro é indistinguível dos 10 por célula.
Teste: para cada célula, treinar as DUAS configurações sobre os MESMOS
       caminhos de CPCV, com as MESMAS seeds.
Estatística: diferença de métrica por caminho.
Critério a priori: se |Δ| mediano < σ entre caminhos do CPCV em ≥ 8 das 10
       células, H₀ não é rejeitada e o arquivo vira UM vetor.
```

Isso não gasta `N_lifetime` novo: é **reexecução de configurações já
escolhidas**, não busca. E o retorno é grande — se `H₀` não cair, o projeto
devolve 9 graus de liberdade à deflação e passa a ter **uma** configuração
para auditar em vez de dez.

**A precondição, e ela é intransponível:** este teste só é interpretável
depois de `§13.5-1` e `§13.5-2`. `§13.8` já diz isso, e vale integralmente
aqui.

---

## §13.13 **P1 — o pipeline não sabe dizer "não há sinal"**

Propriedade estrutural, não bug. `tau` é definido em `alpha.py:910` como o
quantil `1 − target_signal_rate` da distribuição de scores. **Um quantil
sempre existe.** O modelo dispara na taxa alvo qualquer que seja o conteúdo
informativo do vetor.

Medido — 69 features de **ruído gaussiano puro**, `y`/`w` reais de
BTCUSDT/R1, treino em 70% e teste nos 30% finais:

| configuração | `sd` do score (treino) | `sd` (teste) | taxa disparada OOS | alvo |
|---|---|---|---|---|
| default `constants.yaml` (`nl=8, md=3, mcs=20`) | 0,01575 | 0,01554 | **1,767%** | 1,89% |
| ADR-003 `BTCUSDT_R1` (`nl=3, mcs=2000`) | 0,01005 | 0,01003 | **1,940%** | 1,89% |

**Zero sinal, e ainda assim uma "probabilidade calibrada" com dispersão
própria e uma taxa de disparo dentro de 7% do alvo.** Nada dentro do laço de
treino pode reportar ausência de edge — só a régua econômica de `§1.1`
pode, e ela vive fora.

**Proposta, e a peça já existe:** `fit_side_model` já aceita
`null_permutation_seed` (`alpha.py:663`), que embaralha `label` e `ret_net`
juntos preservando `sample_weight`. Ele é usado hoje só em investigação
pontual. Proposta: **todo relatório de `run_layer1_sprint` passa a carregar
o nulo de permutação do mesmo pipeline**, `k` réplicas, e reporta a métrica
como percentil contra esse nulo — nunca como número absoluto.

Sem isso, um lift de `1,02` medido é indistinguível, no artefato, dos
`1,767%` de disparo que o ruído puro produz. Custa `k` treinos por célula e
**zero `N_lifetime`** (é nulo, não busca).

---

## §13.14 Correções ao desenho de `§13.5`

Três dos cinco itens de `§13.5` precisam de emenda. Os outros dois
(`-1` vetor único, `-2` NaN→null) endosso sem alteração.

### §13.14.1 `§13.5-3` — dois defeitos reais na fórmula da hessiana (e um que eu inventei e retiro)

`§13.5-3` propõe:

```
min_sum_hessian_in_leaf(célula) = min_child_samples × w̄ × p(1−p)
```

> **RETRATADO — falso positivo meu, achado no reexame.** A primeira redação
> desta v2 acusava a fórmula de ser *"redundante por construção"* por usar
> `w̄` em vez de um quantil inferior de `w`, alegando que *"a folha a pegar
> é a composta de linhas de peso BAIXO"*. **A direção está invertida.** Uma
> folha com `mcs` linhas de peso baixo tem `Σw = mcs·q10(w) < mcs·w̄` — ou
> seja, **o piso pela média exatamente a captura**, e um piso por `q10` a
> deixaria passar por construção. Com `w̄ = 1,0157` contra mediana
> `= 0,8153`, usar a média é o lado **mais** restritivo, que é o desejado.
> O rótulo "redundante" também cai: com `w` indo de 0,82 (mediana) a 35,9
> (máx), contagem e massa mordem em folhas diferentes. **`§13.5-3` está
> certo neste eixo.** Sobram dois defeitos, os dois reais:

**(i) Omite `scale_pos_weight`, que multiplica a hessiana.** Verificado na
fonte do LightGBM (`src/objective/binary_objective.hpp`): a hessiana é
`|r|·(sigmoid − |r|) · label_weight · weight`, e `label_weight` **é**
`scale_pos_weight` para a classe positiva. Com `spw = 1,3134` (base WEIGHT,
o default desde `AG-272`), as linhas positivas carregam **31% mais massa**
do que a fórmula supõe.

**(ii) Trata `p` como a taxa base, mas a hessiana é dinâmica.** `p` na
hessiana é a **predição corrente** naquela iteração de boosting, não a taxa
base. Conforme o boosting avança e os scores se espalham, `p(1−p)` **cai**,
e uma restrição de massa fixa fica **progressivamente mais apertada**. Um
piso derivado de `p̄` descreve a iteração 0 e nenhuma outra.

**Emenda proposta** — a fórmula de `§13.5-3` com os dois termos que faltam:

```
min_sum_hessian_in_leaf(célula) = n_obs_independentes_alvo
                                × (linhas/ESS)      # converte obs. indep. -> linhas
                                × w̄                 # MÉDIA, confirmada correta acima
                                × 0,25              # cota de p(1-p) na iteração 0
                                ÷ scale_pos_weight  # (i): spw infla a massa real
                                × fator_conservador # a priori, <= 1, cobre (ii)
```

com **todos** os termos medidos in-fold e `n_obs_independentes_alvo` /
`fator_conservador` declarados a priori. E — importante — o parâmetro só
passa a valer a pena **se `max_depth` subir**: com `num_leaves ∈ {2,3}`,
nenhum piso de folha morde (`§13.9.3`). **Prioridade baixa**: sem a mudança
de profundidade, esta emenda corrige uma fórmula que rege um parâmetro
inerte.

### §13.14.2 `§13.5-4` — o bloqueio proposto guarda um canal que carrega 0,08% do dado

`§13.5-4` propõe transformar `screen_target_agreement` em **bloqueio**:
discordância entre o alvo do IC (`ret_net`) e o do modelo (`P(TP)`) zera a
constraint.

O mecanismo que `AG-213` descreve para essa discordância é, na própria
docstring de `monotonic.py:270`: *"uma feature que melhora `ret_net`
sobretudo tornando os desfechos `TIME` menos ruins, sem mover P(TP)"*.

`ADR-004 §0` já mediu, e eu confirmei nos labels de hoje: **`P(TIME)` é
0,08%.** BTCUSDT/R1: 180 desfechos `TIME` em 215.442. ETHUSDT/R3: **4 em
39.485**. A barreira vertical praticamente nunca é atingida.

**O canal DECLARADO está fechado — mas não é o único, e a primeira redação
desta v2 concluiu demais.**

Medida a decomposição de variância de `ret_net` em BTCUSDT/R1 (lado long):

```
variância total          2,673e-05
  entre ramos (TP/SL)    73,8%
  DENTRO do ramo         26,2%
```

**26% da variância de `ret_net` vive dentro dos ramos** — preço de fill,
`funding_bps`, `adverse_selection_bps`. Uma feature que se correlacione com
fill melhor, sem mover `P(TP)`, produz discordância genuína entre os dois
alvos por um canal que **não** é `TIME` e **não** é ruído.

Então o veredito se divide:

- **A justificativa de `§13.5-4` está errada** e precisa ser reescrita: o
  mecanismo que a docstring de `AG-213` invoca carrega 0,08% do dado.
- **A conclusão "logo não bloquear" NÃO se sustenta** como eu escrevi. Existe
  um canal vivo de 26%.
- **O que sobra, e é suficiente:** as discordâncias reportadas estão em
  `|mean_ic| ≈ 0,007` contra `SE ≈ 0,005` — **~1,4σ**. Nesse nível, o
  **piso de magnitude** (`|mean_ic| ≥ k·SE(ESS)`, `k` a priori) já as
  elimina antes de a pergunta da concordância ter sujeito.

**Recomendação revista: implementar o piso de magnitude PRIMEIRO e só então
remedir a concordância.** Se, com constraints acima do piso, ainda houver
discordância, ela é real (canal de 26%) e aí sim o bloqueio se justifica —
com a justificativa certa. Bloquear agora seria empilhar um filtro sobre
ruído que o piso já remove.

`screen_target_agreement` continua **relatório** até essa remedição.

### §13.14.3 `§13.5-5` — `early_stopping` sobre o split de calibração usa o mesmo dado duas vezes

`§13.5-5` propõe: *"`early_stopping` sobre o sub-split de calibração — que
já existe, já é purgável e já não é o `fit`."*

O sub-split de calibração é o insumo do **calibrador isotônico**
(`alpha.py:904-906`). Usá-lo também para escolher `n_estimators` significa
que o calibrador é ajustado sobre o mesmo dado que **selecionou o modelo que
ele calibra**. É `B08` de novo, um nível acima: `B08` proíbe calibrar sobre
o próprio OOF; isto calibra sobre o próprio conjunto de parada.

Com `alpha_calibration_holdout_frac = 0,25` e `num_leaves ∈ {2,3}`, o efeito
é pequeno — mas é exatamente a classe de atalho que este projeto já pagou
para descobrir.

**Emenda:** partição em **três**, dentro do treino do fold e com purge por
`t1` nas duas fronteiras — `fit` / `stop` / `calib`. Se o custo de amostra
for julgado alto demais em R3 (`ESS ≈ 9.200`), a alternativa honesta é
**não usar early stopping** e manter `n_estimators` fixo, declarado — não
reaproveitar o split.

---

## §13.15 Quatro hipóteses que matei por medição

Registro aqui para que ninguém gaste trial nelas. Todas foram levantadas
por mim nesta sessão e **derrubadas pelo meu próprio teste**.

### (H1) `boost_from_average` desalinhado por `scale_pos_weight` — **real, mas imaterial**

Verificado na fonte do LightGBM: `BoostFromScore` calcula `pavg` usando
**apenas** `weights_`, **sem** `label_weights_`. Logo o score inicial
corresponde à taxa base *não* rebalanceada, enquanto todo gradiente
posterior *é* rebalanceado. Medido, BTCUSDT/R1 long:

| base | `spw` | init do LightGBM | init ótimo | desalinhamento |
|---|---|---|---|---|
| COUNT (legado) | 1,0132 | −0,2726 | −0,2595 | +0,0131 |
| **WEIGHT (pós-`AG-272`)** | 1,3134 | −0,2726 | +0,0000 | **+0,2726** |

Ou seja: **a mudança que eu mesmo apliquei em `AG-272` aumentou o
desalinhamento em 20×.** Previ que isso consumiria orçamento de boosting.
**Errado.** Comparando a configuração de hoje (A) contra a matematicamente
equivalente com init correto (B, `spw` dobrado no `sample_weight`):

```
A spw=WEIGHT (init errado)     sd(logodds)=0,04415   p_med=0,4999
B peso rebalanceado (init ok)  sd(logodds)=0,04383   p_med=0,4999
correlação de rank A×B = 0,979
```

Converge dentro de 300 árvores; efeito na ordenação ≈ nulo. **Não é para
corrigir.** Registro a condição em que morderia: orçamento de encolhimento
baixo (`learning_rate × n_estimators ≲ 3`, que é o caso de `BNBUSDT_R1` e
`ETHUSDT_R3` com `lr = 0,01`). Um teste barato antes de baixar `lr`.

> Nota lateral que sobrevive: `corr(A, spw=1,0) = 0,980` — praticamente a
> mesma. **`scale_pos_weight` quase não muda a ordenação** com `p ≈ 0,49`.
> O que ele muda é o **nível**, e o nível é sobrescrito pelo calibrador
> (`§13.10`). O achado (2) de `AG-272` está conceitualmente certo e é
> operacionalmente quase inerte.

### (H2) `monotone_constraints_method = basic` — **sem dano medível nesta profundidade**

A doc oficial diz que `basic` (o default, e o que o projeto usa sem
declarar) *"over-constrains the predictions"*, e que `intermediate` *"is
much less constraining… and should significantly improve the results"*. Com
~62×2 constraints por célula, parecia grave. Medido, 69 features (3 com
sinal monótono plantado, 66 ruído), `max_depth = 3`:

| método | AUC OOS |
|---|---|
| `basic` | 0,54269 |
| `intermediate` | 0,54284 |
| `advanced` | 0,54270 |

Diferenças de `1,5·10⁻⁴`. **O `basic` só sobre-restringe quando a restrição
propaga por muitos níveis; com `max_depth ∈ {2,3}` os três métodos
coincidem.** Não implementar. Reabrir **se e somente se** `max_depth ≥ 5`
entrar em jogo.

### (H3) `tau` in-sample distorce a taxa de sinal realizada — ~~não sustentada~~ **CONFIRMADA, e por 4×**

> **FALSO POSITIVO MEU, e o pior deles.** Eu declarei esta hipótese "não
> sustentada" com base num teste sintético — e **a medição real já existia
> no repo, em `src/analysis/tau_diagnostics.py`, com um teste `xfail`
> dedicado que a documenta.** Eu não procurei antes de concluir. É
> exatamente a lição de `AG-249` (*"ler a proveniência antes de propor
> remedir — o campo já tinha a resposta"*), repetida.

O que eu mediu, com `X` de ruído puro: `sd_treino ≈ sd_teste`
(0,01575 vs 0,01554), taxa realizada 0,93× e 1,03× o alvo → conclusão
"não há folga de sobreajuste a explorar".

**O que o repo já media, sobre dado real** (`tests/unit/
test_analysis_tau_diagnostics.py`, `xfail` com motivo declarado):

| versão | `mean_ratio_to_target` | dispersão entre caminhos de CPCV |
|---|---|---|
| `pre_fill` | **0,2558** | 1,2683 |
| `post_fill` | **0,2373** | 1,2839 |

**A taxa de sinal realizada OOS é ~1/4 do alvo nominal**, e a dispersão
entre caminhos passa de 1,25×. O `xfail` diz textualmente: *"tau IN-FOLD
generaliza pior OOS do que o quantil nominal sugere… NÃO ajustar o critério
para passar (Regra Zero)"*.

**Por que meu teste não pegou:** com `X` de ruído puro não há estrutura a
memorizar, então in-sample e OOS coincidem por construção. **O teste
sintético estava desenhado para não poder falhar.**

**Consequências, e elas reforçam o resto do documento:**

1. **`target_signal_rate = 0,0189` não é entregue.** O valor realizado é
   ~0,0045. Toda conta que suponha a taxa nominal — inclusive a
   **capacidade** de `§12.4` — descreve um motor que não existe.
2. **`§13.16.4` fica mais forte, não mais fraco.** `tau` não só ignora o
   breakeven por linha (`§13.16.3`); ele nem entrega a taxa que promete.
   Um limiar absoluto derivado de quantidades conhecidas em `t0` não tem
   esse modo de falha.
3. **`§13.13` continua válido** e agora com número melhor: o pipeline não
   sabe dizer "não há sinal" **e** não sabe dizer quanto vai falar.

### (H4) `bin_construct_sample_cnt = 200000` limita a resolução de cauda — **não morde**

O default sorteia 200 mil linhas para construir as fronteiras de bin, e a
cauda é onde vivem os eventos que importam em cripto. Mas o maior conjunto
de `fit` do projeto é BTCUSDT/R1: 215.442 linhas por lado × `(1 − 0,25)` de
holdout de calibração = **161.581**, ainda menor dentro de um fold de CPCV.
**Sempre abaixo de 200.000 — as bins usam o dado inteiro em todas as 15
células.** Nada a fazer. Registrar em `constants.yaml` por proveniência
continua valendo (é `AG-208`), mas não há defeito.

---

## §13.16 A decisão estrutural que fica para o Manager

Dois itens que **não** proponho executar — proponho **decidir**. Ambos são
maiores que `§13`, e ambos são a diferença entre consertar o motor e trocar
o motor.

### §13.16.1 Quinze modelos por símbolo, contra um modelo do painel

Hoje: `run_layer1_sprint(symbol=...)` treina **um modelo por
símbolo × resolução**. Quinze modelos, quinze conjuntos de hiperparâmetros,
quinze deflações — sobre `ESS` que vai de **9.202** (ETHUSDT/R3) a
**84.028** (BTCUSDT/R1 por lado).

O padrão de referência da literatura vai na direção oposta: Gu, Kelly & Xiu
(2020), o trabalho canônico de ML em apreçamento empírico, treina **um**
modelo sobre o painel inteiro (~30.000 ações), justamente porque o gargalo é
amostral. Um modelo por ativo é o desenho que a literatura abandonou.

Números deste projeto, todos já medidos, que sustentam a pergunta:

| fato | valor | fonte |
|---|---|---|
| `n_eff` dos 5 símbolos por autovalores | **2,03** | `experiments/cross_symbol_ess_report.json` |
| concordância entre as 3 resoluções | **72%** | `ADR-005 §11.1` |
| `I²` entre ativos, R1 → R3 | 83/61 → **66/67** | `AG-238`, via `§12.6` |

O terceiro é o mais interessante e está lido ao contrário no ADR. `§12.6`
condição 4 apresenta a queda do `I²` em R3 como **custo** ("os ativos ficam
mais parecidos, o que enfraquece o argumento de escopo multi-ativo"). É
custo para "diversificação". Mas **homogeneidade é exatamente a precondição
de poolar**: em R3 — a grade que `§12` promove — os ativos são mais
parecidos, logo um modelo do painel é mais defensável ali do que em R1.
O mesmo número é objeção num enquadramento e argumento no outro.

Ganho potencial: `ESS` por modelo multiplicado por até 5× nominal (~2× em
observações independentes), e o número de modelos, de configurações e de
deflações caindo de 15 para 3 (ou 1).

**A restrição de dado, e ela é real:** dollar bars fecham em instantes
diferentes por símbolo. Poolar com `symbol` como categórica **não** exige
alinhamento e é implementável hoje. **Ranking transversal** (o `lambdarank`
com `group = timestamp` que a persona recomenda, e que remove o beta de
mercado do alvo) **exige um relógio comum e não é implementável sob
`canonical_bar_type: dollar` sem uma decisão de grade nova.** São duas
perguntas, não uma, e só a primeira está no alcance.

### §13.16.1-bis REBAIXADO A CHALLENGER — três superfícies de quebra silenciosa

> **Revisão de 2026-08-26, sob questionamento do Manager** (*"muda a raiz da
> proposta do motor como um todo"*). O reexame encontrou um mecanismo que eu
> não tinha visto e que **enfraquece materialmente** a recomendação. Ela deixa
> de ser item de plano e passa a **challenger gated**.

**(1) `uniqueness` é intra-série. Poolar corrompe a contabilidade de ESS.**

`compute_concurrency_and_uniqueness` mede sobreposição de labels **dentro de
uma série** (AFML cap. 4, `numCoEvents`/`avgUniqueness`). Num painel, um label
de BTC e um de ETH que se sobrepõem no tempo **não são independentes** —
correlação par a par medida 0,50–0,76 (diária) e 0,61–0,84 (15 min), e
`n_eff = 2,03` para 5 símbolos.

`Σ uniqueness` sobre um painel de 4 símbolos reportaria **~4× o ESS de um
símbolo**; a informação independente real é **~2×**. **O ESS poolado sairia
superestimado por um fator ~2.**

E o ESS alimenta a derivação de regularização (`§13.14.1`), o `SE` do piso
das constraints (`§13.14.2`) e a deflação do DSR. **Poolar sem corrigir isso
faz o motor acreditar que tem o dobro da amostra que tem** — exatamente a
classe de erro que `§0.1`, `§11.1` e `§13.12` já corrigiram três vezes nesta
linha de trabalho. Seria a quarta.

Correção obrigatória se o challenger avançar: ESS poolado explicitamente
**two-factor** — `uniqueness` intra-símbolo × `n_eff` transversal, os dois
declarados e persistidos separadamente.

**(2) `assign_environments` deixa de significar o que diz.**

Os 6 ambientes são tercil de `E27f_cost_atr_ratio` × regime estrutural, com o
tercil calculado **sobre a distribuição do próprio treino**
(`environments.py`, docstring). Poolado, essa distribuição mistura símbolos
cujo `unit_notional` varia **542×** (`§12.2`). O ambiente `LOW_COST` passaria
a ser dominado por qual símbolo é estruturalmente mais barato — **deixa de
significar "momento barato" e passa a significar "ativo barato"**, quebrando
em silêncio a triagem de consistência que **decide as constraints
monotônicas**. Saída: tercil dentro de símbolo, ou 6 × 4 = 24 células com
menos observação cada.

**(3) CPCV de painel é a superfície de vazamento.**

`generate_splits(labels, config, symbol=symbol)` opera um símbolo por vez, e
`_assert_dollar_bar_grade_consistent` lê `_calibration.json` por símbolo
(`cpcv.py:387,419`). Poolado, a fronteira de fold precisa ser por *timestamp*
com **todos os símbolos do mesmo lado**, e o purge por `t1` precisa cobrir
todos. Feito errado, cria vazamento **entre ativos com correlação 0,70–0,83**
— pior que o problema que se está resolvendo.

**(4) E o que fecha: poolar sem `§13.16.4` é pior que não poolar.**

Um modelo poolado produz **um** score. Sob `tau` global, ele selecionaria
preferencialmente do símbolo com distribuição de score mais larga, ignorando
que o breakeven daquele símbolo é maior (mediana 0,5706 em BTC/R1 contra
0,5207 em SOL/R3). **`§13.16.4` é pré-requisito estrutural, não só ordem.**

**Regime revisto:**

| antes | agora |
|---|---|
| item 12 da ordem de implementação | **fora da ordem** |
| "recomendação" | **challenger gated** |
| — | módulo de pesquisa em `src/validation/`, escreve em `experiments/`, **não toca `predictions/` nem `models/`** (precedente: os `t2_t1_*` do `ADR-003`) |
| — | promovido **só** se vencer o incumbente por mais que σ entre caminhos, **nos mesmos caminhos**, com ESS two-factor declarado |

**Se a escolha for entre `§13.16.4` e este item: fazer `§13.16.4` e
possivelmente nunca fazer este.** O ganho aqui é `√2` em precisão de
estimação, comprado ao preço de um viés de ~2× na medida que audita esse
mesmo ganho.

### Desenho, se o challenger for autorizado

**Forma intermediária, não os extremos.**

A pergunta não é "poolado *ou* por símbolo". É **quanto encolhimento entre
símbolos**, e a forma intermediária deixa o próprio learner decidir: com
`symbol` como feature categórica, a árvore **divide por símbolo quando o
dado sustenta e agrupa quando não sustenta**. É estritamente mais geral que
os dois extremos, e é o que Gu/Kelly/Xiu fazem.

```
hoje    15 modelos  (5 símbolos × 3 resoluções) × 2 lados = 30 boosters
proposto 3 modelos  (1 por resolução, symbol categórico)  × 2 lados =  6
sob §12.6 (só R3, 4 ativos): 1 modelo × 2 lados = 2 boosters
```

Manter a separação **por resolução** é deliberado: R1/R2/R3 são regimes de
amostragem genuinamente diferentes (duração mediana 10,2 / 21,5 / 45,1 min),
e `§13.16.3` mede que a fração de linhas que **violam R2** difere entre elas
por mais de uma ordem de grandeza (9,5–27,1% em R1 contra 0,0–1,1% em R3).
Poolar entre resoluções misturaria populações com legalidade econômica
diferente; entre símbolos, não.

**Bônus:** isto **subsume o teste `H₀` de `§13.12`**. Se um modelo poolado com
`symbol` categórico empatar ou vencer os 15 separados nos mesmos caminhos de
CPCV, as duas perguntas foram respondidas de uma vez — "as células são
independentes?" e "devemos poolar?".

**O custo real, e é onde mora o risco:** o CPCV precisa virar **consciente de
painel**. A fronteira de fold passa a ser por *timestamp*, com **todos os
símbolos do mesmo lado dela** — hoje `generate_splits(mf.data, symbol=symbol)`
opera um símbolo por vez. Fazer isso errado cria vazamento entre ativos
correlacionados, que é pior do que o problema que se está resolvendo. É a
linha "Painel (multi-ativo): fold corta no meio de um instante" da própria
persona.

**Ordem: depois de `§13.17` itens 1–4.** O ganho de poolar é de **precisão de
estimação** (`√2` no erro-padrão), não de edge — e precisão sobre uma medição
não interpretável (`§13.8`) não vale nada.

### §13.16.2 O alvo: `1{TP}` ponderado por `|ret_net|` não é uma escolha que alguém fez

O que o pipeline otimiza hoje é um híbrido: **classificação binária de
`1{TP}`, com a perda ponderada por `uniqueness × |ret_net|`, calibrada sob a
mesma inclinação, decidida por um quantil.** Nenhum documento escolhe esse
objeto; ele é o resultado de três decisões locais defensáveis.

Os fatos que tornam a pergunta urgente, todos medidos hoje:

- `P(TIME) = 0,08%` → é uma barreira **dupla**, não tripla; o alvo é um
  indicador de **primeira passagem**.
- `P(TP) = 0,4916–0,5026` nas 10 células → quase martingale, como esperado
  sob payoff simétrico. **O sinal, se existir, é fraco por construção.**
- O payoff **não** é simétrico depois do custo: `|ret_net|` no SL é 1,06–1,29×
  o do TP. O breakeven em `P(TP)` que derivo de forma independente —
  `r_SL/(r_TP + r_SL)` sobre os `ret_net` realizados — dá **0,5146 a 0,5629**
  por célula, e o lift exigido correspondente **1,041 a 1,145**.
  `min_alpha_lift_by_combo.yaml` declara **1,076 a 1,151** nas 15 células.
  **Não são o mesmo número e não deveriam ser:** a régua é calculada sob a
  *geometria ótima* de cada célula (`tp_atr_mult = sl_atr_mult ∈ {1,5; 2,25}`),
  a minha sob a geometria que os labels de produção de fato usaram. O que a
  coincidência de faixa e de ordenação estabelece é que **a régua não é
  arbitrária** — dois caminhos independentes chegam ao mesmo lugar. Registro
  também que a faixa real é `1,076–1,151`, não o `1,076–1,175` que `§1.1`
  publica: `AG-278` já apontou, e confirmei lendo as 15 entradas.
- A discriminação OOS já medida é `AUC = 0,5088` pooled
  (`alpha_deep_analysis_2026-08-24.json`, `n ≈ 1,99M`), ou seja
  `D = 2·AUC − 1 = 0,0176` — **abaixo do `ρ ≥ 0,0239` que `§12.5` exige**,
  e medida sob o purge quebrado de `§13.1` (portanto, otimista) e sob os
  labels antigos.

### §13.16.3 A medição que reposiciona a pergunta: o breakeven **não é da célula, é da linha**

A régua de `§1.1` e `min_alpha_lift_by_combo.yaml` publicam **um** breakeven
por célula. Mas o breakeven é uma identidade contábil de quantidades
**conhecidas em `t0`** — `entry_price_limit`, `tp_price`, `sl_price`,
`cost_entry_bps`, `cost_exit_bps`, todas em `labels.parquet`:

```
g_tp = (tp_price − entry)/entry − custo     g_sl = (entry − sl_price)/entry + custo
breakeven(linha) = g_sl / (g_tp + g_sl)
```

**A identidade que isto revela, e ela é o ponto central:**

```
breakeven(linha) = 0,5 + custo / (2 · τ · ATR)
R2 do projeto:     custo ≤ cost_stop_ratio_max · stop = 0,20 · τ · ATR
        ⟹  R2 por linha  ⟺  breakeven(linha) ≤ 0,60
```

**A regra `p̂ > breakeven(linha)` não é um gate novo — é a restrição R2,
aplicada por linha.** Hoje R2 só é avaliada em `src/analysis/` (`m3`, `s1`,
`volatility_operational_effect`); **`grep` em `src/models/` não retorna
nenhuma aplicação de `cost_stop_ratio_max`**. A camada de modelagem nunca
viu R2.

Medido linha a linha (lado long, pós-`NOFILL`), com o teste R2 exato:

| célula | **% que VIOLA R2** | be mediano | be p99 | amplitude entre os que passam |
|---|---|---|---|---|
| BTCUSDT/R1 | **25,0%** | 0,5706 | 0,7108 | 0,0833 |
| BNBUSDT/R1 | **27,1%** | 0,5728 | 0,7161 | 0,0799 |
| ETHUSDT/R1 | **12,7%** | 0,5579 | 0,6748 | 0,0804 |
| XRPUSDT/R1 | **9,5%** | 0,5530 | 0,6387 | 0,0839 |
| ETHUSDT/R3 | **0,3%** | 0,5282 | 0,5810 | 0,0672 |
| BNBUSDT/R3 | **1,1%** | 0,5355 | 0,6016 | 0,0816 |
| SOLUSDT/R3 | **0,0%** | 0,5207 | 0,5533 | 0,0475 |
| XRPUSDT/R3 | **0,0%** | 0,5259 | 0,5658 | 0,0585 |

**Dois achados, e o primeiro é novo:**

1. **Entre 9,5% e 27,1% das linhas de R1 violam R2 — e estão no conjunto de
   treino, são pontuadas, e são elegíveis para seleção por `tau`.** São
   linhas em que o custo de ida e volta consome mais de 20% do stop:
   estruturalmente não operáveis, independentemente do modelo. Em **R3 isso
   é 0,0%–1,1%**.
2. **Entre as linhas legais, o limiar ainda varia 8,0–8,4 pp em R1 e
   4,8–8,2 pp em R3**, contra um edge procurado de **6,6 pp**. A regra de
   hoje é `p̂ > tau`, com **um `tau` global por célula** (`alpha.py:910`) —
   ela não sabe que a linha custa caro.

**Corolário — e este é o argumento de `§12` por um caminho independente:**
a diferença R1 × R3 **não** é de homogeneidade residual (0,080–0,084 contra
0,048–0,082 — faixas que se sobrepõem). É de **contaminação**: R1 carrega um
quarto de linhas estruturalmente não operáveis dentro do treino; R3 não
carrega. `§12.6` acerta a grade, e este número diz *por que* em termos de uma
restrição inviolável que já existe, em vez de um conceito novo.

### §13.16.4 Recomendação — trocar a **regra de decisão**, não o objetivo

Retifico o que a primeira redação desta seção propunha (regressão sobre
`ret_net/atr_at_t0`). Depois de medir `§13.16.3`, **não recomendo trocar o
`objective`.** Três razões:

1. Com `P(TIME) = 0,08%`, `ret_net` é praticamente uma variável de **dois
   pontos**. Regressão L2 sobre variável de dois pontos estima `p` disfarçado
   — e a logloss é a regra de pontuação **própria e eficiente** para
   Bernoulli; erro quadrático não é. Trocaria um estimador eficiente por um
   pior para estimar a mesma coisa.
2. `r_tp` e `r_sl` **são conhecidos em `t0`**. Não há nada a *aprender* sobre
   eles — há que *aplicá-los*. Pedir ao modelo que os reaprenda a partir das
   features é gastar capacidade num mapa que já existe em forma fechada.
3. A regressão descarta a interpretação de probabilidade, que é justamente
   o que a régua consome.

**Proposta:**

```
manter  objective="binary" sobre 1{barrier == TP}
corrigir o peso do calibrador (§13.10, opção b)  ->  p̂ é P(TP) de verdade
trocar   p̂ > tau            (limiar global, quantil)
por      p̂ > breakeven(linha) (identidade contábil, conhecida em t0)
manter   o teto de capacidade: entre os que passam, os top-q por margem,
         com q derivado do fee_budget (§12.6 condição 1)
```

O que essa troca fecha, de uma vez:

| problema | fechado por |
|---|---|
| `§13.13` — o pipeline não sabe dizer "não há sinal" | `breakeven` é limiar **absoluto**; se nenhum `p̂` o supera, não há trade |
| `§12.6` condição 1 — `target_signal_rate` global | vira teto de capacidade, deixa de ser a decisão |
| `§13.10` — `p̂` precisa ser `P(TP)` de verdade | passa a ser **pré-requisito da regra**, não só de relatório |
| `AG-213` — dois alvos no mesmo pipeline | a economia sai do screen de IC e vai para a regra, onde é exata |
| `§1.1` — régua por célula | vira teste por linha; a régua agregada continua como diagnóstico |

**Custo: zero `N_lifetime`.** Não é busca — é substituir um quantil por uma
identidade contábil. E é a única proposta deste documento que pode **mudar o
sinal do resultado** em vez de só torná-lo interpretável.

**Não recomendo executar antes de `§13.17` itens 1–4**, e o motivo é `§13.8`:
com o purge dimensionado para 7 features e `p̂` enviesado em −13%, o teste
`p̂ > breakeven` compara um número errado contra um limiar certo. **A ordem
importa: primeiro `p̂` honesto, depois a regra.**

---

## §13.17 Ordem de implementação revista

`§13.7` está certo na ordem e nos dois pré-requisitos. Insiro os achados
novos e marco o que muda artefato.

| # | item | origem | muda artefato? | gasta `N_lifetime`? | status |
|---|---|---|---|---|---|
| 1 | `feature_ids` obrigatório nos 5 call sites | `§13.5-1` | não (vai **falhar alto**) | não | **EXECUTADO** (`AG-298`) |
| 2 | NaN → null na fronteira + falha alta em coluna morta | `§13.5-2` | **sim** (`config_hash`) | não | **EXECUTADO** (`AG-300`) |
| 3 | Censo de nulos por coluna × célula, persistido | `§13.7-3` | não | não | **EXECUTADO** (`AG-308`) |
| **3b** | **Transação `labels ↔ registro` + gate de staleness por `config_hash`** | **`§13.11`** | não | não | **EXECUTADO** (`AG-309`) |
| **3c** | **Reprocessar `label_engine_runs` para as 15 células atuais** | **`§13.11`** | não (append) | não | **REJEITADO** — ver `§13.11`; substituído pelo 3b + rerun real (`AG-309`, `6ec2af9`) |
| **4** | **Decisão do Manager sobre o peso do calibrador (a/b/c)** | **`§13.10`** | **sim**, se (a)/(b) | não | **EXECUTADO**, opção (b) (`AG-312`) |
| 5 | Nulo de permutação em todo relatório de `run_layer1_sprint` | `§13.13` | não | **não** (é nulo) | bloqueado (retreino represado) |
| 6 | Piso de magnitude nas constraints (`|mean_ic| ≥ k·SE`) | `§13.5-4` emendado | sim | não | bloqueado (retreino represado) |
| 7 | Teste `H₀`: um vetor global vs. 10 por célula | `§13.12` | não | não (reexecução) | bloqueado (retreino represado) |
| 8 | Regularização derivada de `ESS`, fórmula emendada | `§13.14.1` | sim | não | bloqueado, prioridade baixa (parâmetro medido inerte) |
| 9 | `early_stopping` com partição em **três** | `§13.14.3` | sim | não | bloqueado (retreino represado) |
| 10 | Manifesto completo por célula + verificação na carga | `§13.5-5` | não | não | **EXECUTADO** — schema + verificação (`§13.21`, `AG-314`); wiring em produção fechado no mesmo dia (`§13.21.1`, `AG-141`) |
| **11** | **Regra de decisão: `p̂ > breakeven(linha)` — que é R2 por linha** | **`§13.16.4`** | **sim** (decisão, não modelo) | **não** | **PARCIAL** — gate pré-existia sem reconhecimento (`§13.22`, `AG-315`); teto por margem é código novo, opt-in; promoção a produção é decisão do Manager |
| **11b** | **Censo de linhas que violam R2 no conjunto de treino, por célula** | **`§13.16.3`** | não | não | **EXECUTADO** (`§13.20`, `AG-296`/`AG-297`) |

**Fora da ordem, deliberadamente:**

- **Poolar por resolução (`§13.16.1-bis`)** — rebaixado a **challenger
  gated**, não item de plano. Motivo: `uniqueness` é intra-série e o ESS
  poolado sairia superestimado ~2×, na mesma ordem do ganho prometido.
  Roda como pesquisa em `src/validation/`, sem tocar `predictions/`.
- **Emenda da fórmula da hessiana (`§13.14.1`)** — prioridade baixa; rege um
  parâmetro que `§13.9.3` mede como inerte em `num_leaves ∈ {2,3}`.
- **Bloqueio de concordância de alvo (`§13.14.2`)** — só depois do piso de
  magnitude (item 6) e de uma remedição.

**Itens 1, 2, 3b e 3c são pré-requisito de tudo o mais.** `§13.8` já afirma
isso para 1 e 2; `§13.11` estende a afirmação: enquanto o registro descrever
labels que não existem, **nenhum número publicado é rastreável à sua
origem** — inclusive os de `ADR-004 §0/§1`, `ADR-005 §12.4` e `§13.3`.

Itens 4 e 7 são **decisões**, não tarefas. Nenhuma delas deve ser tomada por
quem implementa.

---

## §13.18 O que esta v2 explicitamente NÃO decide

- **Não altera nenhum default, constante ou artefato.** Tudo aqui é
  proposta.
- **Recomenda, mas não decide, o alvo e o pooling** (`§13.16.4`,
  `§13.16.1`). As duas recomendações são explícitas e fundamentadas; a
  decisão é do Manager. Em particular, `§13.16.4` **retifica** a primeira
  redação desta v2, que propunha regressão sobre `ret_net/atr_at_t0` — a
  medição de `§13.16.3` mostrou que a alavanca está na regra de decisão, não
  no `objective`. A retificação está no corpo, não escondida.
- **Não decide ranking transversal.** `lambdarank` com `group = timestamp`
  exige relógio comum e é incompatível com `canonical_bar_type: dollar` sem
  decisão de grade nova. Fica fora de escopo, nomeado.
- **Não revisa `§1`–`§9`**, que seguem `REPROVADOS` por `§11`. Nada aqui
  depende deles.
- **Não fecha o gap da régua.** Se depois de todas as correções o lift
  continuar em `1,0`, a conclusão será sobre o mercado, não sobre o
  pipeline — e `§9` já garante que este projeto pode alcançá-la. As
  correções de `§13` mudam o que é **interpretável**; nenhuma delas
  **cria** edge, e nenhuma linha desta v2 deve ser lida como se criasse.
- **Não substitui triagem in-fold (`B06`).** O teste de `§13.12` e o nulo de
  `§13.13` operam sobre configuração e sobre significância, nunca sobre
  seleção de feature.

---

## §13.19 Reexame bloco a bloco — os falsos positivos da própria v2

Executado a pedido do Manager (*"reexamine cada Bloco para pegar falsos
positivos como esse"*), depois de o questionamento sobre `§13.16.1` ter
revelado o mecanismo do `uniqueness`. **Seis achados meus não sobreviveram
inteiros** — quatro nesta varredura e mais dois durante a implementação de
`§13.20`. Todos corrigidos no corpo; o registro fica aqui.

| # | Onde | O que eu afirmei | O que o reexame mostrou | Status |
|---|---|---|---|---|
| **FP1** | `§13.16.1` | Poolar é recomendação; ganho `√2` em precisão | `uniqueness` é intra-série; ESS poolado sairia **superestimado ~2×** — mesma ordem do ganho. Mais 2 quebras silenciosas (`assign_environments`, CPCV de painel) | **REBAIXADO** a challenger gated, fora da ordem |
| **FP2** | `§13.14.1` | Fórmula da hessiana é *"redundante por construção"*; usar `q10(w)` em vez de `w̄` | **Direção invertida.** Folha de `mcs` linhas de peso baixo tem `Σw = mcs·q10 < mcs·w̄` → o piso pela **média a captura**, `q10` a deixaria passar. `§13.5-3` está certo neste eixo | **RETRATADO** (2 dos 3 defeitos caem) |
| **FP3** | `§13.16.3` | Breakeven varia **19,4 pp**, *"3× maior que o edge"*; R3 é *"radicalmente mais homogêneo"* (0,048 vs 0,194) | 25% das linhas de BTC/R1 **violam R2** e inflavam a amplitude. Entre linhas legais: **8,3 pp** (1,26× o edge), e R1 0,080–0,084 contra R3 0,048–0,082 — **faixas que se sobrepõem** | **CORRIGIDO**, e substituído por achado melhor (ver abaixo) |
| **FP4** | `§13.14.2` | Canal de `TIME` morto ⟹ *"não implementar o bloqueio"* | **26,2% da variância de `ret_net` é DENTRO do ramo** (fill, funding, adverse selection) — canal vivo que não é `TIME` nem ruído. A justificativa de `§13.5-4` cai; a conclusão não segue | **SUAVIZADO** para "piso de magnitude primeiro, remedir depois" |
| **FP5** | `§13.15` H3 | `tau` in-sample *"não sustentada"*, com teste sintético | **A medição real já existia no repo** (`src/analysis/tau_diagnostics.py` + `xfail` dedicado): taxa realizada é **0,2373–0,2558 do alvo** — ~1/4 —, dispersão 1,27 entre caminhos. Meu `X` de ruído puro **não podia** falhar: sem estrutura a memorizar, in-sample e OOS coincidem por construção | **REVERTIDO** — hipótese **CONFIRMADA** |
| **FP6** | `r2_admissibility_census.py` | Guarda de degenerescência sobre o **denominador** (`g_tp + g_sl > 0`) | Condição fraca demais: ganho 5 bps / stop 5 bps / custo 60 bps dá denominador `+0,001`, passa na guarda, e o breakeven sai **6,5** — "probabilidade" > 1 sem erro. Pego pelo teste que eu mesmo escrevi | **CORRIGIDO** para `ganho − custo > 0`; e a correção **achou 177 linhas reais** |

### O que o reexame de FP3 produziu de novo, e é melhor que o achado original

Ao procurar por que a amplitude estava inflada, apareceu a identidade:

```
R2 do projeto:  custo ≤ cost_stop_ratio_max · stop  ⟺  breakeven(linha) ≤ 0,60
```

E daí dois fatos que ninguém tinha medido:

1. **`grep cost_stop_ratio_max src/models/` não retorna nada.** R2 só é
   avaliada em `src/analysis/`. **A camada de modelagem nunca viu R2.**
2. **9,5% a 27,1% das linhas de R1 violam R2 e estão no treino**, contra
   0,0%–1,1% em R3.

O achado original (heterogeneidade de limiar) era real mas inflado. O que o
substitui é mais forte, porque não é conceito novo: **é uma das 5 restrições
invioláveis do projeto, nunca aplicada na camada onde o modelo aprende.**

### Blocos que sobreviveram sem emenda

Verificados nesta passada e **mantidos**:

| Bloco | Verificação adicional feita | Resultado |
|---|---|---|
| A (contrato do vetor) | leitura de `pipeline.py:563,580`, `dataset.py:497-503`, `build.py:435-446`, `alpha.py:201,988` | procede |
| B (calibrador) | ressalva declarada: medição usa score sintético → calibrador plano. PAVA preserva a soma ponderada por bloco, então o viés persiste bloco a bloco com score real — **mas isso é argumento, não medição** | procede, com a ressalva agora explícita |
| C (linhagem) | risco de falso positivo checado: `experiment_log.py:334` grava `config.config_hash`, **a mesma** `LabelConfig.config_hash` que vai no parquet → comparação é maçã com maçã. E **só 17 de 153** `experiments/*.json` carregam `config_hash` | procede, reforçado |
| D (multiplicidade) | `n_eff = 2,03` é sobre **retornos diários**, não sobre a estrutura de previsibilidade — proxy, não medida direta. Sob equicorrelação de 0,70 (15 min), `n_eff` cairia para ~1,7, ou seja o número usado é **conservador** | procede, com a natureza de proxy declarada |
| G (as 4 refutações) | `bin_construct_sample_cnt` "nunca morde" é **condicional à arquitetura por símbolo** — um painel de 4 símbolos passaria de 200.000 | procede, com a condicional registrada |

---

## §13.20 EXECUTADO — item 11b: censo de admissibilidade R2 (`AG-296`/`AG-297`)

Primeira peça da ordem de `§13.17` implementada. Escolhida antes dos itens
1–2 por um motivo: **este censo é interpretável mesmo com o purge de `§13.1`
quebrado** — não lê nenhuma feature, nenhum modelo, nenhuma predição, só
preços de barreira e custos, todos conhecidos em `t0`.

**Entregue:** `src/analysis/r2_admissibility_census.py` (núcleo puro Idioma A
+ casca de IO), `tests/unit/test_analysis_r2_admissibility_census.py`
(13 testes, zero IO), `experiments/r2_admissibility_census.json` (30 células).
`ruff`, `mypy --strict` e `banned_patterns` limpos; suíte
**2122 passed, 2 skipped, 2 xfailed**.

### Resultado — `AG-296`: R2 nunca foi aplicada em `src/models/`

`% de linhas que violam R2` (lado long; monotônico em resolução nos 5 símbolos):

| símbolo | R1 | R2 | R3 |
|---|---|---|---|
| BNBUSDT | **27,12%** | 8,55% | 1,12% |
| BTCUSDT | **24,95%** | 7,12% | 0,91% |
| ETHUSDT | 12,69% | 2,23% | 0,27% |
| XRPUSDT | 9,50% | 0,64% | **0,00%** |
| SOLUSDT | 2,28% | 0,14% | 0,03% |

Queda de ~3× por degrau de resolução, **nos cinco símbolos**. `R2` de projeto
cai por um fator de 27 entre `BNBUSDT/R1` e `BNBUSDT/R3`. É `§12.6` medido
por linha, em termos de uma restrição inviolável que já existe.

`payoff_simetrico = true` nas 30 células (medido, não presumido) — o que
autoriza a identidade `R2 ⟺ breakeven ≤ 0,60` citada em `§13.16.3`.

### Achado não previsto — `AG-297`: 177 labels economicamente impossíveis

A guarda de degenerescência **disparou em dado real na primeira execução**:

| célula | linhas com `ganho ≤ custo` | fração | pior razão ganho/custo |
|---|---|---|---|
| SOLUSDT/R1 | 148 | 0,0454% | **0,4113** |
| SOLUSDT/R2 | 29 | 0,0178% | 0,6953 |
| demais 13 | 0 | — | — |

São labels em que o TP vale **menos que o custo do trade** — no pior caso,
41% dele. **Não existe `p` em [0,1] que os faça empatar**: acertar o TP em
100% das vezes ainda perde dinheiro. Volume desprezível (0,006% de 3,04M),
natureza não: nada no Label Engine detecta a condição, então ela não tem
piso, e as 177 linhas entram no treino com `sample_weight` proporcional a
`|ret_net|` — não com peso zero.

**Decisão de desenho tomada por causa disso:** a função de **cálculo**
(`breakeven_probability`) falha alto (o valor é indefinido ali); o **censo**
classifica em campo próprio (`n_tp_nao_cobre_custo`) e segue. Contar
patologia é o trabalho de um censo — abortar uma célula inteira por 0,006%
seria trocar informação por silêncio.

### O que isto NÃO faz

Não filtra, não altera nenhum artefato, não é lido por nenhum pipeline de
treino ou execução — mesmo status DECISION-SUPPORT de `feasibility.py` e
`production_grade_gate.py`. **A remediação é decisão do Manager** e está
registrada como ABERTA nos dois `AG`.

---

## §13.21 EXECUTADO — item 10: manifesto completo por célula + verificação na carga (`AG-314`)

`src/models/persistence.py` (AG-141) já existia — booster + calibrador +
manifest, escrita atômica, formato versionado — mas **não é chamado por
nenhum caminho de produção** (`alpha.py::run_fold`/`pipeline.py` nunca
invocam `write_model_bundle`; achado já registrado, não novo, ver
addendum de `AG-141` no log de 2026-08-23). Este item fecha o SCHEMA e a
VERIFICAÇÃO que `§13.5-5` pede; a integração em produção continua sendo
o gap separado que `AG-141` já nomeia — as duas coisas não são a mesma
tarefa, e confundi-las estenderia o escopo deste item além do que
`§13.17` pediu.

**Entregue:**

- `ModelBundleManifest` ganha `ess` (`Σ uniqueness` do treino, já medido
  como `SideModelResult.sum_uniqueness_train`, `AG-211`), `purge_ms_
  effective` (saída de `compute_max_feature_lookback_ms` para o vetor
  REAL, item 1/`AG-298`), `min_child_samples` e `feature_set_hash`
  (`sha256` do CONJUNTO ordenado alfabeticamente de `feature_ids`).
- `min_child_samples` grava o valor REALMENTE usado no treino — não
  "derivado por ESS" (`§13.5-3`/item 8 seguem `ASSUMED`, bloqueados atrás
  do retreino represado). Proveniência honesta hoje; passa a refletir a
  fórmula de `§13.5-3` no dia em que o item 8 for implementado, sem outra
  migração de schema.
- `read_model_bundle` levanta `ManifestFeatureMismatchError` se
  `manifest.feature_ids != tuple(booster.feature_name())` — **ordenado,
  não como conjunto**: `LoadedSideModel.predict_proba_calibrated` seleciona
  colunas por `manifest.feature_ids` antes de virar array posicional para
  o booster cru; uma divergência de ORDEM (não só de conteúdo) produziria
  inferência silenciosamente errada se não fosse pega aqui. É exatamente
  a checagem que `§13.5-5` pede.

**Testes:** `tests/unit/test_models_persistence.py` — 10 call sites
existentes migrados para os 3 novos kwargs obrigatórios (sem default,
mesma disciplina de `feature_ids` no item 1: nenhum valor honesto pra
assumir por trás do caller), round-trip estendido pra cobrir os 4 campos
novos, + 1 teste novo que PROVA o bug que a verificação existe pra evitar
(`feature_ids` gravado como permutação do `feature_name()` real do
booster → `read_model_bundle` recusa). 14 testes, todos verdes.
`ruff`/`mypy --strict`/`banned_patterns` limpos.

**O que isto NÃO faz (no momento em que foi escrito):** não fechava
`AG-141` — ver `§13.21.1` abaixo, fechado na mesma sessão, algumas horas
depois.

### §13.21.1 EXECUTADO — `AG-141` fechado: wiring em produção

A metade de escopo deixada de fora acima foi fechada no mesmo dia,
mesma sessão. `src/models/pipeline.py` ganha `write_all_fold_model_
bundles` — chamado na CASCA (`run_layer1_sprint`), não dentro de
`alpha.py::run_fold`: os campos que o manifesto precisa (`hyper`,
`purge_ms_effective`, `feature_ids`) já são resolvidos UMA VEZ em
`run_layer1_sprint`, e persistir em disco é efeito colateral de IO, não
parte do núcleo de treino (`Núcleo funcional, casca imperativa`).

**Opt-in** (`persist_model_bundles: bool = False` em `run_layer1_sprint`)
— default preserva bit-exato todo call site/teste existente, nenhum
grava bundle hoje. Gate adicional `path_tf is not None` (mesmo sentinela
de `dest_dir_diag_c1`/`c0`, os dois blocos de diagnóstico): o caminho
legado plano nunca persiste bundle, mesmo com `persist_model_bundles=
True` — `symbol`/`resolution_id` sozinhos não bastam pra nomear a
partição sem colisão sob a grade de tempo legada.

**`tau` gravado é o EFETIVAMENTE APLICADO** (`predictions["tau_long"/
"tau_short"][0]`), não `long_result.tau`/`short_result.tau` — os dois só
coincidem sob `TAU_POLICY_LEGACY_PER_SIDE`; sob `TAU_POLICY_TOTAL_
COMMON_OOF` o per-side fica stale (`run_fold` resolve os dois JUNTOS
depois de computar `long_result`/`short_result`). Mesmo motivo pelo qual
`predictions.parquet` persiste o aplicado, não o per-side — um teste
dedicado prova a divergência com números diferentes de propósito, não só
com o caminho legado onde os dois coincidiriam por acaso.

`ModelBundleExistsError` propaga sem tratamento — reexecutar sobre uma
partição já persistida FALHA, nunca sobrescreve nem pula em silêncio
(imutabilidade de `AG-141` preservada pela integração, não relaxada).

**Testes:** `tests/unit/test_models_pipeline.py` (4 novos, mecânica com
booster/calibrador reais sobre dado sintético — contagem de bundles,
tau efetivo vs. per-side, `ess`/`NaN` passado adiante sem reescrita,
imutabilidade na reexecução) + `tests/unit/test_models_pipeline_paths.py`
(4 novos, roteamento — default nunca chama, `persist_model_bundles=True`
sem `tf`/`resolution_id` explícito nunca chama, `tf`/`resolution_id`
explícito chama as duas variantes com os kwargs corretos). `ruff`/
`mypy --strict`/`banned_patterns` limpos; suíte completa (`-m "not
slow"`) verde.

**`AG-141` fechado.** Nenhuma célula REAL ganhou manifesto ainda — o
efeito só se materializa quando `persist_model_bundles=True` for passado
num run real, e o retreino segue represado (decisão do Manager).

---

## §13.22 EXECUTADO parcial — item 11: `p̂ > breakeven(linha)` (`AG-315`)

**Achado real ao implementar isto:** o GATE do item 11 já existia em
código, sem ter sido reconhecido como tal. `ADR-004` Fase 2
(`decide_side_cost_derived`/`resolve_joint_lambda`, medição opt-in desde
2026-08-25) compara `mu_side > max(cost_atr_ratio, lambda_b)`. Sob payoff
simétrico (geometria de produção vigente, medida em `§13.20` como
`payoff_simetrico = true` nas 30 células), com `lambda_b =
-payoff_atr_mult` (o valor mais permissivo — nunca vincula, pois
`cost_atr_ratio >= 0 > -payoff_atr_mult` sempre) o piso vira
`cost_atr_ratio` puro, e:

```
mu > cost_atr_ratio
payoff*(2p-1) > cost_atr_ratio
p > 0,5 + cost_atr_ratio/(2*payoff)
p > breakeven(linha)                <- a fórmula de §13.16.4, exatamente
```

Verificado por dois testes independentes, não só por álgebra: um contra
`decide_side_cost_derived(..., lambda_b=-payoff)` (a equivalência
declarada), outro contra `p > breakeven` recalculado à parte, sem passar
pela família de fórmula `mu`-baseada — se as duas famílias divergissem
por erro de sinal ou escala, só o segundo teste pegaria. Os dois batem
bit-a-bit sobre 2.000 linhas sintéticas.

### O que NÃO pré-existia: o teto de capacidade por ranking de margem

`§13.16.4` propõe, além do gate: *"entre os que passam, os top-q por
margem"*. `resolve_joint_lambda` resolve um `lambda_b` **escalar**, que
vira um SEGUNDO LIMIAR sobre `mu` — não um ranking sobre a margem
(`mu - cost_atr_ratio`). Os dois mecanismos **divergem de verdade** quando
`cost_atr_ratio` varia entre linhas: um limiar escalar em `mu` trata igual
duas linhas de `mu` idêntico e custo diferente, mesmo que a margem delas
seja diferente. Construído um caso mínimo que prova a divergência com
número real (`test_decide_side_breakeven_topq_diverge_de_lambda_threshold_
quando_custo_varia`): 4 linhas de `mu` idêntico, custo `[0,05; 0,55; 0,05;
0,55]`, `target_signal_rate=0,5` — o ranking por margem retém as 2 de
custo baixo (a leitura literal de "top-q por margem"); o limiar-em-mu não
consegue distinguir as 4 (mu é idêntico), então qualquer `lambda_b`
seleciona as 4 ou nenhuma, nunca 2 de 4.

**Entregue (`src/models/alpha.py`):**

- `breakeven_from_cost_atr_ratio` — `P(TP)` de breakeven direto de
  `cost_atr_ratio` (`E27f_cost_atr_ratio`, já feature T1 de produção).
  Mesma identidade que `r2_admissibility_census.breakeven_probability`
  mede sobre preço (`labels.parquet`); as duas não compartilham código
  (`models/` não importa `analysis/`, Layer hierarchy do `CLAUDE.md`), mas
  são a mesma fórmula sob a mesma premissa de payoff simétrico.
- `decide_side_breakeven` — o gate puro, wrapper deliberado de
  `decide_side_cost_derived(..., lambda_b=-payoff_atr_mult)`, não uma
  reimplementação (mesmo princípio de `decide_side`/`resolve_joint_tau`:
  "a mesma LINHA de código, não duas cópias que podem divergir
  silenciosamente").
- `select_top_q_by_margin` — núcleo puro do ranking por margem.
- `decide_side_breakeven_topq` — item 11 completo: gate + teto por
  ranking.

**Nenhuma das quatro é chamada por `run_fold`** — mesmo status de medição
opt-in que `decide_side_cost_derived` teve antes de `resolve_joint_lambda`
existir. `side_hat`/`predictions.parquet` continuam bit-exatos sob a
política ativa (`tau_policy`). **A decisão de QUAL mecanismo de teto
(limiar em `mu` vs. ranking por margem) vira produção é do Manager** —
`§13.17` já lista o item 11 como "decisão, não modelo"; as duas opções
seguem testáveis e medíveis lado a lado até essa decisão, e a promoção a
`run_fold` real fica pra depois dela (mesmo motivo de não ter aberto essa
frente pro item 10: sem o retreino represado reaberto, não há dado real
pra medir a diferença entre as duas políticas de teto em produção).

**Testes:** `tests/unit/test_models_alpha_breakeven_item11.py`, 12 testes
novos — cobrem a fórmula fechada, a equivalência ao gate pré-existente
por DUAS vias independentes, a fronteira estrita (`>`, não `>=`), o
ranking por margem (incluindo população vazia e `q` fora de `(0,1]`), o
teto como subconjunto estrito do gate puro, a taxa realizada batendo o
alvo quando há oferta, e a divergência estrutural medida contra
`resolve_joint_lambda`. `ruff`/`mypy --strict`/`banned_patterns` limpos;
suíte completa (`-m "not slow"`) **2267 passed, 2 skipped, 2 xfailed, 0
failed** depois desta mudança.

---

## Referências externas

- LightGBM 4.7.0 — [Parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html):
  `monotone_constraints_method` (default `basic`, *"over-constrains the
  predictions"*); `min_data_in_leaf` (*"this is an approximation based on
  the Hessian, so occasionally you may observe splits which produce leaf
  nodes that have less than this many observations"* — relevante a
  `§13.14.1`); `bin_construct_sample_cnt = 200000`; `data_random_seed`;
  `deterministic` (*"used only with cpu device type"*).
- LightGBM — [`src/objective/binary_objective.hpp`](https://github.com/microsoft/LightGBM/blob/master/src/objective/binary_objective.hpp):
  hessiana `= |r|·(sigmoid − |r|)·label_weight·weight`; `BoostFromScore`
  usa `weights_` **sem** `label_weights_` (base de `§13.15` H1).
- Gu, S., Kelly, B., Xiu, D. (2020). *Empirical Asset Pricing via Machine
  Learning*, **Review of Financial Studies** 33(5):2223–2273 —
  [OUP](https://academic.oup.com/rfs/article/33/5/2223/5758276) ·
  [NBER w25398](https://www.nber.org/system/files/working_papers/w25398/w25398.pdf).
  Painel único em vez de um modelo por ativo (base de `§13.16.1`).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*,
  cap. 4 (unicidade média, concorrência de rótulo) e cap. 7 (purged K-fold,
  embargo) — base de `Σ uniqueness` e do `ESS` usados aqui.
- Bailey, D. & López de Prado, M. (2014). *The Deflated Sharpe Ratio* —
  base do custo de deflação citado em `§13.12`.

---

## Autovalidação

Executada contra este próprio documento, antes de entregar.

**1. Toda afirmação numérica é reproduzível?** Sim, com uma exceção
declarada. Cada tabela vem de leitura de `labels.parquet`/`.json`/`.yaml` do
repo ou de execução de LightGBM 4.7.0 do `.venv`. A exceção: `§13.15` H2 e
H3 usam `X` **sintético** (ruído gaussiano), o que está dito em cada um. H2
adicionalmente derivou as constraints do IC calculado sobre o dado inteiro
(incluindo teste) — logo o resultado *"66 constraints de ruído não
prejudicaram"* **não é confiável** e não foi usado como conclusão; a
conclusão de H2 é apenas a comparação `basic`/`intermediate`/`advanced`, que
é interna ao mesmo dado e não sofre desse defeito.

**2. Alguma conclusão contradiz outra parte do documento?** Uma tensão real,
e a registro em vez de escondê-la: `§13.14.1` propõe uma fórmula melhor de
`min_sum_hessian_in_leaf` e, no mesmo parágrafo, diz que o parâmetro não
morde com `num_leaves ∈ {2,3}`. **É deliberado** — a fórmula só entra em
vigor se `max_depth` subir, e está escrito. Implementar o item 8 de `§13.17`
sem essa condição é gastar trabalho num parâmetro inerte, e `AG-272` já
mediu que ele é inerte hoje.

**3. Estou contradizendo decisão ratificada pelo Manager?** Sim, em um
ponto, e declaro: `§13.14.2` recomenda **não** implementar `§13.5-4` como
bloqueio. `§13.5` é `PROPOSTO`, não ratificado, então não é reversão de
decisão — mas é discordância explícita do documento que estou estendendo, e
está nomeada como tal.

**4. Estou repetindo achado alheio como se fosse meu?** Verificado e
corrigido: `P(TIME) ≈ 0,08%` é de `ADR-004 §0`, creditado em `§13.14.2`.
`ESS/linhas ≈ 0,37` é de `AG-211`/`ADR-004 (F3)`, creditado em `§13.9.2`.
`n_eff = 2,03` é artefato pré-existente. A unidade efetiva ser o símbolo é
de `§11.1`. O que é meu: `§13.10` (viés do calibrador), `§13.11`
(`config_hash` do registro), `§13.12` (aplicar `§11.1` aos hiperparâmetros),
`§13.13` (nulo obrigatório), `§13.14` (as três emendas) e `§13.15` (as
quatro refutações).

**5. Onde este documento pode estar errado?** Três lugares, por ordem de
risco:

- **`§13.10` opção (b).** Afirmo que `uniqueness` pertence ao calibrador e
  `|ret_net|` não. É argumento de primeiro princípio, **não uma medição**.
  A medição (−13,0%) prova que existe viés; **não** prova qual das três
  saídas é a certa. O Manager decide.
- **`§13.12`.** Componho `n_eff = 2,03` (entre símbolos, sobre retornos
  diários) com 72% de concordância (entre resoluções, sobre descoberta de
  feature) para dizer "~2 problemas independentes". As duas medições são de
  populações e de objetos diferentes; a composição é **heurística**, não
  um cálculo. O que sobrevive sem ela: o número de células independentes é
  **muito menor que 15**, e 10 vetores de hiperparâmetro precisam justificar
  isso. O teste `H₀` que proponho não depende da heurística — ele a torna
  desnecessária.
- **`§13.9.3`.** Concluo que `mcs` não morde com `num_leaves ∈ {2,3}` por
  argumento de crescimento leaf-wise, **sem medir a distribuição real de
  tamanho de folha**. Mensurável em uma execução (`booster_.trees_to_
  dataframe()`), e deveria ser medido antes do item 8 de `§13.17`.

**6. Algum número que citei pode ser stale?** Verificado, e é o assunto de
`§13.11`: `alpha_deep_analysis_2026-08-24.json` (`AUC = 0,5088`, usado em
`§13.16.2`) é **pré-relabel e pré-correção de purge**. Está declarado no
próprio ponto de uso. Não o corrigi porque é o único dado de discriminação
OOS que existe — e o fato de ser o único e ser stale é, ele mesmo, parte do
argumento.

**7. A severidade que atribuí sobrevive à verificação?** Uma foi rebaixada
por mim durante a redação. A primeira versão de `§13.10` afirmava que o viés
do calibrador corrompe a comparação contra a régua. Ao procurar o consumidor
de `min_alpha_lift_ptp`, descobri que **não existe consumidor em código** — a
régua é aplicada por pessoa. `§13.10` foi reescrito: o dano hoje é de
interpretação, e vira dano de execução no dia em que a régua for automatizada
(opção já registrada em `architecture_gaps_log`). Mantive `P0` porque a
ordem de correção importa mais que a severidade instantânea — mas a
severidade instantânea está declarada, não inflada.

**8-bis. O reexame de `§13.19` invalida esta autovalidação?** Parcialmente,
e é o achado mais importante sobre o próprio método. A autovalidação original
tinha 8 perguntas e **nenhuma delas pegou os 4 falsos positivos de
`§13.19`**. O que os pegou foi um questionamento externo do Manager sobre um
item específico, que me obrigou a reabrir um argumento que eu já tinha dado
por fechado. Conclusão operacional: **autovalidação por checklist detecta
inconsistência interna e proveniência, não erro de direção em raciocínio
próprio.** Para essa classe, o que funciona é adversarial externo — e é por
isso que `§13.16.1-bis` foi rebaixado a challenger em vez de corrigido no
lugar: um item que sobreviveu a uma rodada de auto-revisão e caiu na primeira
pergunta externa não merece confiança de item de plano.

**9. Foi tudo medido, ou algo foi presumido do meu conhecimento da
biblioteca?** Duas afirmações sobre o LightGBM eu sabia antes de verificar —
que `BoostFromScore` ignora `label_weights_`, e que `monotone_constraints_
method` tem default `basic`. **Nas duas eu fui à fonte antes de escrever**
(código C++ do objetivo binário; página de parâmetros da versão instalada),
e nas duas o resultado bateu. Registro porque a ordem certa é essa, e porque
uma delas — H1 — eu teria reportado como achado grave se tivesse parado na
confirmação da doc e não medido o efeito.

---

## §14. v3 — arquitetura corrigida (2026-08-26): `L2` vazia, `defeito_construção` nomeado

**Fecha parcialmente `§11.5`.** Dos 3 instrumentos que `§11.5` exige antes de
uma v3 existir: **o modelo nulo por símbolo está pronto** (`src.analysis.
feature_promotion_criterion`, `AG-294`) e **o BH está no payload com unidade
declarada** (mesmo módulo — `q_bh`, `p_symbol_empirico`, `n_symbols`, tudo
persistido em `experiments/feature_promotion_criterion_report.json`). **O
eixo 2 (estabilidade temporal) continua sem código** — não construído nesta
sessão, por escopo (§14.6). Esta v3 é honesta sobre isso: decide o que já dá
pra decidir (eixo 1 sozinho já fecha a pergunta de §14.1), e declara em
aberto o que falta pro critério de dois eixos ser real, não só citado.

### §14.1 O resultado que muda tudo: `L2 = {}`, não `L2 = {E16f}`

`AG-294` rodou o eixo 1 corrigido (unidade = símbolo, não célula; BH
`q=0,10` de verdade; `p_símbolo` medido, não herdado) contra os 3 relatórios
reais. Resultado, 72 features, 5 símbolos:

| `k ≥` símbolos | esperado sob H₀ | observado |
|---|---|---|
| 1 | 21,0 | 19 |
| 2 | 2,79 | 2 (`E18f` + `K04_session_us`, dummy de calendário) |
| 3 | 0,19 | 1 (só `E18f`) |

`E16f_global_ls_ratio` — a âncora de `L2` na v2 — cai para **1 símbolo**
(`SOLUSDT`), dentro do ruído. Nenhuma feature nova passa. **E, verificado a
pedido do Manager: nem as 7 features `T1` passam.** Rodadas pela mesma
régua: `B01_rsi_14`/`E27f_cost_atr_ratio`/`C06_vol_ratio_12_96`/
`D06f_taker_imbalance_z_48` têm **zero** símbolos; `A05_ret_vol_norm_4`/
`A13_dist_ema48_atr`/`E10f_oi_change_z_48` têm **1**.

Isso não invalida `T1`: essas 7 nunca foram promovidas por este teste, foram
escolhidas antes, por outro processo. Mas significa que **eixo 1, sozinho,
decide a pergunta de promoção de hoje** — não há candidato para o eixo 2
avaliar. `L2` fica definida como **exatamente o que já está em produção**
(`T1_FEATURE_IDS`, 7 colunas) — não porque este critério as validou, mas
porque nada mais bate a régua, e mexer em produção sem motivo positivo não é
decisão desta ADR.

### §14.2 `AG-271` fechado: os 8 recortes que `L4` precisa respeitar

**Revisado 2026-08-26 (`project_assurance` reprovou a v1 desta seção — ver
nota no fim).** A v2 mandava aposentar as 29 `SEM_MECANISMO` sem checar
sobreposição com produção/gate. Recortes obrigatórios, cada um por um
motivo estrutural diferente (verificado por cruzamento de
`T1_FEATURE_IDS`/gate de regime contra
`audit/feature_thesis/fichas_69_2026-08-25.yaml`):

| feature(s) | motivo do recorte | destino |
|---|---|---|
| `A01`–`A06` (6) | momentum de 1 barra é mecanismo econômico RECONHECIDO na literatura (autocorrelação de curto prazo, efeito clássico de microestrutura) — o veredito `SEM_MECANISMO` da ficha reflete que a ficha não creditou esse mecanismo, não que ele esteja ausente | `L3` (em observação) para `A01`/`A02`/`A03`/`A04`/`A06`; `A05` já é `L2` (é `T1`) |
| `B01_rsi_14` | `T1` vivo hoje | `L2` (produção vence veredito de ficha) |
| `B07_efficiency_ratio_48` | insumo do gate de regime (`classifier.py:535`) | `L1` |

**Correção 2026-08-26 (`project_assurance`, achado MEDIUM): a v1 desta
seção justificava o recorte de `A01`–`A06` citando §7 ("9 de 12 features
mantêm sinal em 4 quartis") — essa MESMA alegação já tinha sido marcada
estatisticamente incorreta em `AG-284` (§11.3: "não tem o nulo certo, as 12
são pré-selecionadas por sinal e 6 são colineares"), e a v1 nunca revisitou
isso antes de usar §7 como base.** A justificativa acima não depende mais
de `AG-284`: é só o reconhecimento de que "retorno defasado" é uma
categoria de mecanismo padrão em finanças, independente de qualquer
resultado estatístico específico — a evidência quantitativa de que o sinal
é REAL (não só que o mecanismo é plausível) continua em aberto (eixo 1,
`AG-294`, mostra que nem `A01` passa a régua corrigida — ver §14.1). `L3`
é exatamente o destino certo pra essa situação: mecanismo plausível,
evidência estatística ainda insuficiente.

`L4` a partir de `SEM_MECANISMO`: **29 − 8 = 21** features.

### §14.3 `AG-272` — o estado `defeito_construção`, ortogonal, com precedência explícita

**Revisado 2026-08-26.** A partição `L0`–`L4` nunca teve lugar pras 16
`INCOERENTE_DIMENSIONAL` + 10 `ERRO_CATEGORICO` da ficha (26 no total).
Essas não são "sem mecanismo" (`L4`) nem "tese sem evidência" (`L3`) — são
construção que **mede algo diferente do que diz medir**, às vezes só numa
fração das barras (`E10f`, `AG-295`), às vezes mudando de papel entre
grades (`A13`, `AG-295`).

Novo estado, mesmo desenho de `quarentena` (§2.3) — **ortogonal à camada,
nunca uma camada própria**:

```
defeito_construcao: true | false
```

**Correção 2026-08-26 (`project_assurance`, achado CRITICAL): a v1 desta
seção tratava `defeito_construcao` como a única marcação que essas 26
colunas precisavam — sem nunca decidir a CAMADA delas quando não eram já
`L0`/`L1`/`L2` por outro motivo. Resultado medido por reconstrução de
conjunto (não a alegação da v1, a reconstrução real): 23 das 72 features
não caíam em NENHUMA camada — a MESMA classe de furo que `AG-272` original
descrevia (25 sem camada), reduzida de 25 para 23, não fechada, apesar do
título desta seção dizer "fechado".** Regra que faltava, agora explícita:

**Regra de default para `INCOERENTE_DIMENSIONAL`/`ERRO_CATEGORICO`: `L4`
(não calculada), a menos que a precedência abaixo já resolva a coluna pra
`L0`/`L1`/`L2`/quarentena.** Justificativa: uma coluna com construção
comprovadamente quebrada é uma aposta pior que "sem mecanismo" — não se
sabe nem se ela mede o que diz medir, então o default seguro é NÃO
calculá-la até alguém investigar, não deixá-la calculada por omissão (que
é exatamente o que "24 não investigadas, sem camada" fazia na v1).

**Precedência completa (versão corrigida — `E27f` é uma SEGUNDA exceção
deliberada, não resolvida por ordem, ver abaixo):**

1. `L0` (primitiva de cálculo) — vence qualquer veredito de ficha.
2. `L1` (insumo do gate de regime) — vence `L3`/`L4`.
3. `L2` = `T1_FEATURE_IDS` hoje — produção vence veredito de ficha.
4. **Quarentena** (`E18f`, §2.3) — vai pra `L3` (mesma consequência
   operacional: calculada, fora do treino), com `quarentena: true` E
   `defeito_construcao: true` simultâneos (o veredito dela na ficha é
   `ERRO_CATEGORICO` — as duas flags descrevem o mesmo fato por dois
   ângulos: fonte suspeita de artefato E construção categoricamente
   errada).
5. `SEM_MECANISMO` (com os recortes de §14.2) → `L4`.
6. `INCOERENTE_DIMENSIONAL`/`ERRO_CATEGORICO` restante (não resolvido por
   1-4) → `L4` + `defeito_construcao: true` (regra de default acima).
7. `TESE_OK` restante → `L3`.

**`E27f_cost_atr_ratio` é uma exceção deliberada à regra "nenhuma coluna
em duas camadas" — não um erro de precedência.** `E27f` está em
`T1_FEATURE_IDS` (treina o Alpha) E é lida por `classifier.py` (gate de
regime) — as DUAS coisas são verdade no código real, simultaneamente, não
uma ambiguidade a resolver por ordem. Aplicar a precedência acima
mecanicamente (que colocaria `E27f` só em `L1`, por vir antes de `L2` na
ordem) mentiria sobre o que o código faz. `defeito_construcao` já era
citado como "a única exceção deliberada" na v1 desta seção — errado: são
DUAS, `defeito_construcao` (flag ortogonal a qualquer camada) e `E27f`
(dupla camada `L1`+`L2`, por desenho real do código, não folga da regra).

**Correção 2026-08-26 (`project_assurance`, achado novo na 2ª revisão):
o diagnóstico de `E02f` não estava "sem mecanismo conhecido" — a v1 desta
frase chegou a essa conclusão sem checar o addendum já existente do
`AG-030`.** O defeito da ficha pra `E02f`/`C07`/`D03f`/`E15f`/`E17f` é o
cap `min_common_history_bars_15m` (164.256, calibrado em contagem de
barra de RELÓGIO) aplicado cru — mas VERIFICADO no código
(`src/features/build.py:1163`) que esse cap está DESABILITADO
(`min_common_history_bars = None`) sob `bar_source != "time_15m"`,
exatamente a grade de produção (R1/R2/R3, `AG-042`). O defeito específico
que a ficha descreve não está ativo em produção — mas isso NÃO significa
"sem problema": desabilitar o cap reabre o problema ORIGINAL do
`AG-030` (nenhum piso comum de histórico entre os 5 ativos sob janela
expansiva), já registrado como dívida ABERTA desde 2026-08-17
(`AG-030::addendum_reabertura_sob_dollar_bar_2026_08_17`, "Manager
autorizou fechar isso... Pendente: medir um equivalente NATIVO... nenhuma
medição nova feita ainda"). `E15f`/`E17f` (Lote C, 2026-08-24) nunca
foram conectadas a esse addendum porque não existiam quando ele foi
escrito. `C09`/`C10`/`C11` usam o mesmo parâmetro (verificado,
`build.py:876-886`) mas não estão em `defeito_construcao` (vereditos
`TESE_OK`/`SEM_MECANISMO`, não `ERRO_CATEGORICO`/`INCOERENTE_DIMENSIONAL`).
`E02f`/`C07` são `L1` — a dívida do `AG-030` está ativa no gate de regime
em produção hoje, não numa feature candidata hipotética; mesma classe de
risco de `B07`. Investigação proposta, não feita: medir o "equivalente
nativo" que o addendum do `AG-030` já pede, não recorrigir a conversão
calendário→barra que a ficha descreve (esse caminho já foi rejeitado em
2026-08-17).

**Correção 2026-08-26b — `A13` e `E10f` cortados pro fix, `defeito_
construcao` da ficha agora descreve implementação DESATIVADA (`AG-295`,
aprovação explícita do Manager, ver addendum na entrada do log).** As duas
correções que este parágrafo (acima) e o corpo de `AG-295` descreviam
como "proposta, NÃO adotada"/"investigado, NÃO implementado" foram
adotadas em produção nesta sessão: `E10f_oi_change_z_48` usa
`e10f_oi_change_z_48_from_native_delta` (registry v1→v2); `feature_a13_
ema_window` foi RECLASSIFICADO `clock`→`bar_count`
(`config/constants.yaml`), `ema_window=48` fixo nas 3 grades — a
maquinaria de escala em `src/features/build.py` foi removida, não só
desligada. **Isso NÃO reclassifica A13/E10f pra fora de
`defeito_construcao` nas contagens de `§14.1`/`§14.4`/`§14.6` abaixo —
essa reclassificação exigiria regerar a ficha (`audit/feature_thesis/
fichas_69_2026-08-25.yaml`) rodando o diagnóstico de novo sobre o código
corrigido, não reescrever o veredito por inferência.** A ficha atual
(`fichas_69_2026-08-25.yaml`) ainda descreve a implementação ANTIGA — os
vereditos `INCOERENTE_DIMENSIONAL`(A13)/`ERRO_CATEGORICO`(E10f) são fatos
históricos corretos sobre o código que existia até 2026-08-26, não mais
uma descrição do código de produção hoje. Regenerar a ficha dessas 2
colunas é trabalho pendente, não feito aqui (B23 — não estipular o
veredito novo sem medir).

### §14.4 Tabela de camadas corrigida

**Revisado 2026-08-26 — números recalculados e verificados por
reconstrução de conjunto EM CÓDIGO (não a prosa deste documento), depois
de `project_assurance` mostrar que a v1 desta tabela alegava cobertura
completa sem tê-la de fato:**

| Camada | Membros | Nota |
|---|---|---|
| `L0` | `C01`, `C02` (2) | sem mudança |
| `L1` | `B07`, `C07`, `E02f`, `E27f` (4) | `E27f` também é `L2` — dupla camada deliberada (§14.3) |
| `L2` | as 7 `T1_FEATURE_IDS` | inclui `E27f` (dupla com `L1`) — `E16f` NÃO entra (§14.1) |
| `L3` | 17 (11 `TESE_OK` restantes + 5 momentum `A01`-`A04`/`A06` + `E18f` via quarentena) | +1 vs. a v1 desta tabela (ganhou `E18f`) |
| `L4` | 43 (21 `SEM_MECANISMO` restante + 22 `INCOERENTE_DIMENSIONAL`/`ERRO_CATEGORICO` sem outro destino) | **+22 vs. a v1 desta tabela** — é a correção do achado CRITICAL |
| `defeito_construcao` (flag ortogonal) | 26 (3 já `L1`/`L2`: `A13`, `E10f`, `E02f`; 1 em `L3` via quarentena: `E18f`; 22 em `L4`) | fecha `AG-272` de verdade agora |

**Verificado por reconstrução de conjunto (script, não prosa):**
`L0 ∪ L1 ∪ L2 ∪ L3 ∪ L4` = as 72 features exatas, `0` faltando, `0`
sobrando. A soma bruta das 5 camadas (`2+4+7+17+43=73`) excede 72 em
exatamente `1` — a dupla-camada deliberada de `E27f` (§14.3), não um erro
de contagem.

Das 26 em `defeito_construcao`: **2 têm investigação + correção proposta**
(`A13`/`E10f`, `AG-295`); **24 não foram auditadas individualmente nesta
sessão**, incluindo `E02f` (a única das 24 que já é insumo de produção via
`L1`) e `E18f` (já tem sua própria investigação separada, `AG-266`, sobre
a causa do artefato — não sobre a construção em si).

### §14.5 Opções, revisadas

Com `L2 = T1` (7, não 1 e não 72), a tensão da v2 (§4 — "poda agressiva
concentra o motor numa fonte só") **desaparece**: não há nada novo pra
concentrar risco em cima. As opções de §3 ficam assim:

- **Opção A (manter as 72 no cálculo/vetor de treino)** — mesma avaliação
  da v2: custo estatístico máximo, sem justificativa nova.
- **Opção B (podar pra `L2` apenas)** — deixa de ser "1 coluna instável" e
  vira **"não fazer nada"**: `L2` já é `T1`. Deixa de ser opção de risco —
  é o estado atual, por ausência de candidato.
- **Opção C (5 camadas + quarentena + `defeito_construção`, podar `L4`
  corrigida, manter `L3` calculada) ✅** — continua a recomendação, e fica
  MAIS barata de justificar: não exige nenhuma promoção contestável (`L2`
  não muda), só reduz o que é calculado sem propósito (`L4`, **43** —
  corrigido 2026-08-26, era 21 na v1 desta tabela, ver §14.3/§14.4) e
  nomeia o que precisa de engenharia antes de significar algo
  (`defeito_construção`, 26). `L4=43` (60% das 72) parar de ser calculada
  é uma redução MAIOR do que a v1 desta seção estimava — o custo evitado
  é maior, não menor, com a partição corrigida.

### §14.6 O que esta v3 ainda não fecha

- ~~Eixo 2 (estabilidade temporal) sem código.~~ **FECHADO 2026-08-26**
  (`AG-299`) — a pedido do Manager, mesmo com §14.1 já zerando o pool de
  candidatos via eixo 1 sozinho. `src/analysis/feature_temporal_
  stability.py`, núcleo puro + 16 testes. Duas das definições
  operacionais que faltavam (`AG-274`) foram fixadas por REPRODUÇÃO, não
  por leitura da prosa — a 1ª tentativa deste módulo errou nas duas: o
  horizonte do IC por semestre é `h=1` fixo (não o pico de cada feature —
  só reproduzia `E18f`, cujo pico coincide com `h=1` por coincidência), e
  "direção consistente" é maioria dos PRÓPRIOS semestres (não o sinal do
  IC do período inteiro — só `D06f` discrimina as duas leituras, e só a
  maioria bate os 60% publicados). Os 5 casos calibrados de §2.2 batem
  exatamente com a correção (`ratio`/`frac_mesma_direção` na 3ª/4ª casa
  decimal, incluindo `D06f` reprovando na direção como o original).
  Rodado contra as 15 células completas (não só os 5 casos): `E18f`
  reprova o eixo 2 em **15/15**, confirmação independente de `AG-266`
  por um teste que nunca usou informação sobre o artefato. Os 3
  pré-requisitos de `§11.5` estão fechados agora — modelo nulo por
  símbolo, BH com unidade declarada (`AG-294`) e eixo 2 persistido
  (`AG-299`). `h=1` sem justificativa econômica declarada continua
  como lacuna residual (por que `h=1` e não o pico, ou o holding `H=5`?)
  — registrada, não fabricada.
- ~~19 das 26 colunas em `defeito_construção` seguem sem investigação
  individual~~ **FECHADO 2026-08-26 (item 2 dos 4 itens de continuação)**
  — as 19 restantes (eram 24; `A13`/`E10f` já tinham `AG-295`, `E02f`/
  `C07`/`D03f`/`E15f`/`E17f` já conectadas ao `AG-030`) foram verificadas
  contra código real por 4 agentes independentes, agrupadas por causa
  raiz compartilhada: **`AG-321`** — degeneração de volume sob dollar
  bar (`D01f`/`D02f`/`D04f`/`D09f`/`D10f`: `volume ≈ threshold/preço`
  por construção do fechamento de barra, confirmado em `src/data/
  bars.py`; 5 transformações da MESMA quantidade degenerada, não 5
  teses — implica contagem de graus de liberdade inflada em qualquer
  filtro de ortogonalidade/HHI/`N_lifetime` que as trate como
  independentes). **`AG-322`** — `B02`/`B09` (erro de TAXONOMIA: grupo
  "momentum" sem papel alternativo declarado, ao contrário de `B07`,
  que tem) vs. `C03`/`C04`/`C05` (erro real de CÁLCULO/especificação:
  fator `√48≈6,93` de escala incomparável entre a "mesma família" de
  estimador, mais ausência de normalização temporal sob duração de
  barra variável em Parkinson/GK). **`AG-316`** — `A12` (erro de
  DEFINIÇÃO irremediável por config: mecanismo de "gap" não existe em
  mercado 24/7 contíguo) vs. `K01`/`K04` (erro de CALIBRAÇÃO/
  acoplamento: mecanismo econômico real existe, mas corte de sessão mal
  posicionado — `K04_europe` inclui 31% da abertura do caixa
  americano). **`AG-317`** — `C08`: erro aritmético JÁ NA PRÓPRIA
  `constants.yaml` (17520 barras a 15m = 6 meses, não 1 ano — a conta
  original já nasceu errada, antes até da barra dollar). **`AG-318`**
  — `D07f`: 100% NaN em toda produção real (R1/R2/R3), `registry.yaml`
  lista como T2 disponível sem soletrar a consequência. **`AG-319`** —
  `E03f`: footprint de purge sub-declarado (1,59×), mas a guarda que
  isso violaria já foi corrigida por `AG-296` (falha alto hoje, não só
  avisa — boa notícia achada no processo). **`AG-320`** — `E11f`: mesma
  classe de bug que `A13` tinha antes da correção desta sessão (nome
  "1d" mentindo, `LoteAWindows` não escala), ainda sem correção
  equivalente. Nenhuma das 19 está em `T1_FEATURE_IDS` — sem urgência
  de produção, mas o pool T2/candidatos agora tem 7 achados registrados
  e verificados em vez de só a ficha original. `AG-321`/`AG-322`
  renumeradas de colisão de ID com a sessão paralela (mesmo
  procedimento de `AG-272`/`AG-296`/`AG-312`).
- **`A01`–`A06` seguem sem resolução da tensão Pearson-vs-Spearman** (§7) —
  `L3`, não `L2`, precisamente por isso. A justificativa do recorte pra
  `L3` foi corrigida em §14.2 pra não depender mais de `AG-284`.
- **Nenhum código de produção foi alterado por §14.1-§14.5.**
  `T1_FEATURE_IDS`/`registry.yaml` continuam como estavam — `layer`/
  `quarentena`/`defeito_construcao` são desenho proposto (§5.3 item 1 da
  v2 ainda vale), não campos que existem hoje. (`src/analysis/feature_
  temporal_stability.py` teve um bug de código real corrigido — ver §14.7
  — mas é módulo novo, decision-support, não produção.)

### §14.7 Revisão independente (`project_assurance`, 2026-08-26) — achados e correções

A v1 de §14 (§14.1-§14.6, tabela original) foi revisada por `project_assurance`
e **REPROVADA** — 1 CRITICAL, 1 HIGH, 4 MEDIUM, 2 LOW. Todos corrigidos
nesta versão de §14.2-§14.6, exceto onde marcado.

| severidade | achado | correção |
|---|---|---|
| **CRITICAL** | "`AG-272` fechado"/"união cobre as 72" era FALSO — reconstrução de conjunto real dava 49, não 72 (23 `INCOERENTE_DIMENSIONAL`/`ERRO_CATEGORICO` sem camada nenhuma, mesma classe de furo do `AG-272` original) | Regra de default `INCOERENTE_DIMENSIONAL`/`ERRO_CATEGORICO` → `L4` adicionada (§14.3); `L4` recalculada pra 43; reverificado por script (não prosa): união = 72 exatas |
| **HIGH** | Regra "nenhuma coluna em duas camadas, exceto a flag" violada pelo próprio documento — `E27f` aparece em `L1` E `L2` na tabela da v1 | `E27f` declarado explicitamente como 2ª exceção deliberada (dupla camada real no código, não erro de precedência) — §14.3 |
| MEDIUM | §3 (nota "não atualizado"), §5.2 (`L4: 29`) e §5.3 ("todos DERIVED") não foram sincronizados com §14 — padrão `AG-123` | Corrigidos (ver §3, §5.2, §5.3 abaixo) |
| MEDIUM | `evaluate_temporal_stability` sem piso de `n_semestres_validos` — com 1 semestre, `passa_eixo_2=True` incondicional | `min_semesters` adicionado (constante nova, `feature_temporal_stability_min_semesters=4`), com teste dedicado. 3 relatórios reais regenerados |
| MEDIUM | Recorte de `A01`-`A06` pra `L3` (§14.2) se apoiava em `§7`/"9 de 12 quartis", já invalidado por `AG-284` no mesmo documento | Justificativa reescrita: reconhecimento de mecanismo (momentum é categoria clássica), não a evidência quantitativa contestada — §14.2 |
| LOW | Docstring de `feature_promotion_criterion.py` citava "97/275" (deveria ser "197/275", `AG-270`) | Corrigido |
| LOW | 2 divisões em `feature_temporal_stability.py` sem comentário `noqa: unguarded-ratio` reconhecido pelo linter, apesar de estruturalmente seguras | Comentários adicionados nas linhas certas, `check_unguarded_ratios.py` confirma 0 pendentes |

**Esta versão corrigida de §14 (v2) ainda NÃO foi revisada por
`project_assurance`** — mesma situação de `§12`/`§13`: proposto, não
ratificado. Dado que a v1 já foi reprovada uma vez com achado CRITICAL
verificado por reconstrução independente, uma segunda rodada de revisão
antes de tratar §14 como fechado é o padrão que este projeto já aplicou
duas vezes (`§1`-`§9` v1→v2, `production_grade_gate.py` v1→v2) — não
decidido aqui se/quando rodar.
