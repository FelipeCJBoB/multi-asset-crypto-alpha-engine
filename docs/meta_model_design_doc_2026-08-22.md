# Design doc — Meta-model (camada 2, meta-labeling): arquitetura técnica ponta a ponta

**Versão:** v2 (2026-08-22) — reescrita após auditoria adversarial de 3 flancos.
**Status:** desenho travado, **não implementado**. Fase 4 de `redesign_workflow`.
**Autorização:** Manager, 2026-08-22.

**v1 → v2 — o que a auditoria derrubou.** Três auditores independentes
(corretude factual contra o código; rigor estatístico; trade-offs e
alternativas) produziram 6 CRITICAL, ~20 HIGH e ~95 afirmações verificadas
(73 corretas). O changelog completo está no §19. Os quatro que mudaram
decisões:

1. **A prova de impossibilidade do §4.1 da v1 era FALSA.** Existe doador
   simultaneamente OOF e **totalmente cego**, com **zero retreino**
   (§4.2). A v1 afirmava que exigiria CV aninhada a ~6× o custo.
2. **`score_*_raw` foi excluído do design matrix por um argumento errado**
   (monotônico ⇏ colinear; isotônica é *many-to-one* e destrói informação).
   No cenário mais provável `p_alpha` é quase-constante na subpopulação do
   Meta (§3.4).
3. **O purge cross-símbolo não é "questão aberta" — é ausente**, e por um
   motivo estrutural que a v1 não viu (§4.5). Passa a ser bloqueante.
4. **Os gates da v1 não gateavam.** Cinco defeitos somados inclinavam a
   decisão a PASS (§2.6, §9).

**Este documento substitui, como base de desenho do Meta:**
`PRD_V3_2_UNIFICADO.md` PARTE VI (obsoleto por decisão canônica) e
`docs/ADR-001_..._base.md` §3.7/§2.7 — **revogados pelo Manager em
2026-08-22**, verbatim: *"Vou revogar o contrato canônico do Meta-Labeling
pois não me convenceu, pesquise sobre Meta-Labeling no AFML depois pesquise
casos de uso recente modernos"*. A revogação não é retroativa sobre o resto
do ADR-001.

---

## §0 — Sumário das decisões

| # | decisão | v1→v2 |
|---|---|---|
| **D-01** | Regime **entra como feature**, one-hot, nunca ordinal — **condicionado à prova de estabilidade cross-fold** (§6.2) | qualificada |
| **D-02** | Learner **plugável**; logística L2 default e única abaixo do gate; LightGBM atrás de guarda; CatBoost descartado | mantida |
| **D-03** | **Grupo J realocado para depois do Meta** | mantida |
| **D-04** | `y_meta = 1[ret_net > 0]` — PnL líquida, já projetada no lado | mantida |
| **D-05** | Meta **veta ou dimensiona; nunca inverte lado**. Veto-em-zero contra AFML §10.3 | mantida |
| **D-06** | `p_meta` é **filtro binário**, não tamanho | mantida |
| **D-07** | **Sem calibrador no v1** — `tau_meta` por quantil in-fold. **Contrato restrito** (§8.3) | qualificada |
| **D-08** | **Dois braços de CV: `path_matched` (primário, 5 caminhos) e `group_matched` (blindado, 1 caminho)** | **reescrita** |
| **D-09** | Splits gerados no frame **denso**; seleção do subconjunto é **posicional** | mantida |
| **D-10** | Unicidade recalculada na subpopulação, **com grão `(symbol, side)` declarado** | corrigida |
| **D-11** | Regime entra por **join exato**; **o v1 usa a coluna `regime` (Utf8)**, não `canonical_id` | corrigida |
| **D-12** | Ablation com **4 braços e nulo que replica a busca**; **A3 vira gate** | **reescrita** |
| **D-13** | B07/B08 enforced em 5 camadas | corrigida |
| **D-14** | **Gate E0** com regra de agregação declarada e candidato único | **reescrita** |
| **D-15** | **`tau` persistido no schema de predições** — 1 coluna, destrava 3 achados | **nova** |
| **D-16** | **Purge cross-símbolo é pré-requisito bloqueante de F1**, não item aberto | **nova** |
| **D-17** | **Todo modelo do Meta é serializado** — sem isso o desenho é inexecutável ao vivo | **nova** |

---

## §1 — Escopo e premissas

### 1.1 O motor-alvo não é o que está em disco

Manager, 2026-08-22: *"Alpha vai ser refatorado para LightGBM, alpha atual é
obsoleto pois foi desenho de um motor antigo btc only barras casuais time
frame single de 15m."*

Confirmado: `experiments/alpha_layer1_report_t05_janela_comum.json` **não tem
a chave `resolution_id`**, que `src/models/pipeline.py:590` grava — é
anterior ao campo, `"symbol": "BTCUSDT"` (`:831`), grade 15m.

| premissa do motor-alvo | valor |
|---|---|
| Símbolos | **5** — BTC/ETH/SOL/BNB/XRP |
| Grade canônica | **dollar-bar R1** |
| Learner do Alpha | **LightGBM** (§15.14, represada) |
| Regime canônico | `hmm_gaussian_k4_v1` (§15.13) |
| Regime no vetor do Alpha | **fora** desde 2026-08-21 (`src/models/alpha.py:57-68`) |
| Estimador de volatilidade | Parkinson **decidido** (`AG-036`); `constants.yaml:301` ainda `garman_klass_w20` — decisão registrada, flip represado |

**A mudança de 1 para 5 símbolos é a mais consequente:** a amostra
multiplica, a chave passa a incluir `symbol`, e o purge cross-símbolo deixa
de ser refinamento e vira pré-requisito (§4.5).

### 1.2 O estado medido do Alpha legado — registrado, não usado como premissa

`auc_real_pooled = 0,49776` contra `auc_permuted_pooled = 0,49998` (baseline
B4, features embaralhadas), sobre 785.740 + 811.295 avaliações;
`n_paths_camada1_supera_camada0 = 1` de 4 exigidos; `permanence_pass: false`.

O AUC real está **abaixo** do AUC das próprias features embaralhadas. Com
essa amostra não é ruído. **Mas é diagnóstico de um motor descontinuado**
(§1.1) — registrado aqui porque a mesma medição precisa ser repetida sobre o
Alpha novo, não porque decida algo hoje.

### 1.3 Gates externos que este desenho não destrava

1. **Alpha não retreina até o Data Layer (15 estágios) estar 100%** —
   Manager, 2026-08-21. O Meta consome OOF do Alpha ⟹ herda o gate.
2. **`run_layer1_sprint` hoje levanta exceção** — `pipeline.py:427` dispara
   `ExpandingFeatureLookbackError` por 3 features `expanding`
   (`src/features/build.py:154-184`). Decisão pendente, independente do Meta.

**Correção de contradição da v1:** a v1 afirmava em §1.3 que E0 era
executável de imediato e em §2.5 que E0 só roda sobre o Alpha novo. A
resolução é explícita agora: **E0 tem duas execuções distintas**, E0-piloto
(sobre o legado, provisório, não vinculante) e E0-vinculante (sobre o Alpha
novo, pós-E2). Ver §2.6 e §16.

---

## §2 — Por que o Meta existe, e o que o valida

### 2.1 O mecanismo, segundo AFML

- **§3.6** — o primário decide o **lado**; o secundário decide o **tamanho,
  incluindo zero**. O ML secundário **não aprende direção**.
- **§3.7** (`getBins`) — o rótulo é o retorno **projetado no lado**
  (`ret *= side`), `bin ∈ {0,1}` com `bin[ret<=0]=0`. **É PnL, não price
  action.**
- **§3.6** — recall do sistema **≤** recall do primário. O ganho é função do
  **estoque de falsos positivos** do primário.
- **§6.6** — AFML prefere *bagging* a *boosting* em finanças. Nosso GBM
  contraria (§7.4).

**AFML não trata:** features do meta; calibração; amostra mínima; regime;
custos no label; unicidade sobre a **subpopulação**; CV do encadeamento
primário→meta (o exemplo canônico do livro usa primário **não-ML**, então o
problema não existe lá).

### 2.2 A vantagem informacional (D-01)

Sem um input que o primário não tem, o secundário não pode extrair
informação que o primário não extraiu — senão há regressão infinita. Sem
vantagem informacional, meta-labeling só adiciona variância.

Regime **saiu do vetor do Alpha em 2026-08-21** (`alpha.py:57-68`). A Fase A
do §15.13 criou, como efeito colateral, a vantagem informacional.

| evidência | força |
|---|---|
| O experimento canônico do framework (Joubert, `fp_modeling.py`, código aberto) tem braço *regime-aware* sobre dado bi-regime; `bet_sizing.py` condiciona a `pred_regime == 1` | **FORTE** — código do autor |
| *Ensemble Meta-Labeling* (Thumm, Barucca & Joubert, JFDS 5(1):10-26, 2022) lista identificação de regime como 1 dos 3 eixos; ganho aparece **quando há múltiplos regimes** | **FORTE** — abstract oficial |
| Meyer (co-autor de *Meta-Labeling Architecture*, JFDS 4(4):10-24) recomenda features de regime **exclusivas do meta-model** diante de resultado negativo | **FRACO** — thread técnico |

**Nenhum estudo compara feature vs. gate head-to-head.** Lacuna real da
literatura.

Argumento próprio sobre a escala: um gate é o caso-limite da feature —
coeficiente forçado a ±∞ e limiar a priori. Com `n_eff` em centenas a poucos
milhares, a feature custa **1 grau de liberdade**; modelos por-regime custam
**fragmentação por 4**. Ordem: **feature ≻ gate ≻ per-regime**, com o gate
reservado a bloqueios *estruturais* (R2/R3 violados, spread > p95).

### 2.3 A evidência contrária, e o que ela não fecha

`AG-118` mediu `lift ≈ 1,0` em **90 células** (k2/k3/k4 × 3 resoluções × 5
símbolos × 2 lados), sem desvio significativo de 1,0. `lift` é
`bad_event_capture_rate / good_event_cost_rate`
(`src/analysis/gate_efficiency.py:322`; a docstring interpretativa está em
`:147-150`).

`AG-118` mede o lift **incondicional**. O Meta opera sobre a **subpopulação
condicional** (só as barras em que o Alpha disparou). É logicamente possível
que regime separe TP de SL *dentro dos sinais* sem separar no universo — mas
o prior desceu. Essa é a **única hipótese viva**, e é o Gate E0.

### 2.4 O argumento do carimbo de data, aplicado dos dois lados

A v1 usou este argumento para realocar o Grupo J e **não o virou contra
regime**. Correção: regimes são persistentes e formam **blocos contíguos de
calendário**; a partição do CPCV é **cronológica de largura igual, 6 grupos**
(`src/validation/cpcv.py:259-292`). Um one-hot de 4-5 estados sobre 6 blocos
pode ter sobreposição substancial com `group_id`.

Se `regime_R3` for essencialmente "2022", o Meta aprende a taxa de acerto do
Alpha em 2022 e a aplica onde 2022 aparece no teste — AUC in-fold plausível,
feature que não extrapola.

**Diagnóstico obrigatório em E0** (custo zero, artefato existente):
V de Cramér entre `regime` e `group_id` do CPCV, e ocupância de cada regime
por grupo. Associação forte ⟹ D-01 é reavaliada com o mesmo rigor que matou
o Grupo J.

### 2.5 Por que o Grupo J foi realocado (D-03)

**Arg. 1 — a marginalidade de PnL de `p_fill` é exatamente zero, por
construção do label.** `NOFILL ⟹ ret_net = 0.0` literal
(`src/labels/triple_barrier.py:961`; `_append_nofill_row` é o **único**
emissor de NOFILL em todo `src/`). `fill_rate` por caminho:
**0,9665 – 0,9769** (10 caminhos: 2 variantes × 5 paths,
`alpha_layer1_report_t05_janela_comum.json:49-145`). Um `p_fill` **perfeito**
filtraria 2,3–3,4% dos sinais, cada um contribuindo `ret_net = 0`.
**ΔPnL = 0.**

**Arg. 2 — `cost_est_bps` é redundante com o alvo.** `ret_net = ret_gross −
cost_entry_frac − cost_exit_frac − funding_frac`
(`triple_barrier.py:1317`). Sobra `adverse_selection_bps`, genuinamente
marginal (reportado, nunca subtraído) — mas `1.5`, `ASSUMED`, `class: A`,
`review_by: sprint_16` (`constants.yaml:466-473`).

**Arg. 3 — dependência circular.** `calibrate_against_real_fills` levanta
`NotImplementedError` (`src/execution/fill_simulator.py:851`; racional na
docstring do módulo `:58-63`) porque fills reais só existem em Testnet/Paper
(Sprints 15-16) — **depois** do Decision Engine que consome `p_meta`.

**Arg. 4 — cobertura de 13% em bloco contíguo.** `bookTicker` cobre
2023-05-16 → 2024-03-30 (`fill_simulator.py:148-149`; os 320 arquivos foram
medidos para BTCUSDT, `:143-145` — a generalização aos 5 símbolos não está
verificada no docstring). `simulate_window` levanta `ValueError` após a
quebra RPI de 2025-11-20 (`:612`). Labels cobrem 2020-01 → 2026-08
(`src/models/dataset.py:8-12`). Missingness **colinear com época**: o modelo
aprende *"estou em 2023-2024"*, não física de fila.

**Ressalva que impede o argumento de provar demais:** a marginalidade zero
vale para **PnL-por-trade**. Não vale para **rotação de capital** — com ~3
slots, um NOFILL que ocupa margem durante `fill_timeout` tem custo de
oportunidade real. Isso é Risk/Decision Engine, não Meta. O argumento
**realoca**; não desqualifica.

### 2.6 Gate E0 (D-14) — reescrito

**Módulo:** `src/analysis/meta_fp_inventory.py`, em `analysis/` (medição
pós-hoc, fora do `importlinter` de propósito, mesmo precedente de
`gate_efficiency.py`). Zero treino.

**Duas execuções, distintas e rotuladas:**
- **E0-piloto** — sobre `predictions/alpha/alpha_c1_v1_t05_janela_comum/` +
  `data/labels/BTCUSDT/15m/v1/`. Grade 15m legada. **Provisório, não
  vinculante.** Serve para exercitar o módulo e produzir ordens de grandeza.
- **E0-vinculante** — sobre o Alpha novo (5 símbolos, R1, LightGBM),
  pós-E2. É este que decide.

**Definições operacionais travadas a priori** (`CLAUDE.md`, achado
`AG-114`/`AG-122`):

- **Universo.** `side_hat != 0` **e** `is_oof == True`, joinado a `labels`
  por `(t0, side_hat) → (t0, side)`. **`symbol` NÃO é coluna de `labels`** —
  é chave de caminho (`cpcv.py:760-780`); entra como parâmetro do pipeline,
  não como chave de join.
- **Classes** sobre `barrier_hit`: `NOFILL` → classe **N**, fora do
  numerador e denominador (`ret_net = 0,0` exato), reportada em separado;
  `TP` → acerto; `SL` → **FP duro**; `TIME` → `1[ret_net > 0]` (§3.3).
- **Candidato primário `X`: UM SÓ** — o one-hot de regime. `atr_at_t0` e
  hora do dia são **diagnósticos reportados, sem poder de PASS**. Motivo: com
  p95 por candidato e 3 candidatos, a taxa de falso-positivo por path seria
  ~14%, não 5%. Pior: se `atr_at_t0` passasse e regime falhasse, D-01
  estaria refutada e o gate teria dito PASS.
- **Regra de agregação — a correção mais importante.** A v1 definia métricas
  por `(path_id, symbol, side_hat)` — até 50 células — e um critério em 5
  paths, **sem regra que levasse 50 a 5**. Isso é literalmente `AG-114`/
  `AG-122` reproduzido no gate mais consequente. Regra travada:

  > A estatística de path é a **AUC ponderada por `uniqueness_subpop` sobre
  > todas as células daquele path**. O nulo permutado é computado **na mesma
  > agregação** — a permutação absorve a multiplicidade interna. O estimador
  > (`P̂(bin | estado)` empírico ponderado) é **reajustado dentro de cada
  > permutação**, sobre as mesmas linhas e com o mesmo peso; sem isso o nulo
  > não carrega o otimismo do ajuste e a comparação enviesa a favor de PASS.
  > A decomposição por `(symbol, side)` é **diagnóstico obrigatório**, para
  > expor "passou só porque BTC-long carregou".

- **Métricas por path:** `n_fp`, `n_tp`, `n_nofill`,
  `fp_rate = n_fp/(n_fp+n_tp)`; `pnl_fp_total = Σ ret_net | FP` (o **teto
  teórico** de um filtro perfeito é `−pnl_fp_total`; se for menor que o custo
  de fees do próprio filtro, a conversa acaba); `n_eff_subpop = Σ uniqueness`
  (B24, medido).

- **Diagnósticos que a auditoria acrescentou a E0** (custo zero, mudam
  decisões a jusante):
  1. `n_distinct(p_alpha)` na subpopulação, amplitude, e **massa de empate em
     `tau`** — decide §3.4.
  2. V de Cramér entre `regime` e `group_id` — §2.4.
  3. Estabilidade do mapeamento estado↔características entre folds — §6.2.

- **Critério:** `PASS` sse a AUC agregada do path exceder o **p95 do nulo
  permutado** em **≥ 4 dos 5 paths** (`alpha_layer1_permanence_min_paths`).
  **Com a nota de proveniência obrigatória do §4.6.**

**Consequência declarada antes de rodar:** falha em ≥ 2 paths ⟹ registro em
`audit/evidence_ledger.yaml` como evidência negativa e o Meta **sai do
roadmap** até o insumo mudar.

---

## §3 — Contrato do `meta_training_set`

### 3.1 Chave primária

`(symbol, t0, side_hat, fold_id, variant, model_id)`

`model_id` entra como proveniência: um `meta_training_set` montado a partir
de dois runs do Alpha misturaria escalas de probabilidade **sem erro**.

### 3.2 Schema

| coluna | tipo | origem | obrig. | causalidade |
|---|---|---|---|---|
| `symbol` | `Utf8` | parâmetro do pipeline (não é coluna de `labels`) | ✔ | — |
| `t0` | `Datetime("ms","UTC")` | `predictions.t0` (`alpha.py:409`) | ✔ | `close_time` da barra de decisão |
| `t1` | `Datetime` | `labels.t1` (`triple_barrier.py:891`) | ✔ | **nunca feature** — purge e unicidade |
| `_pos` | `UInt32` | `mf.data.with_row_index()` | ✔ | chave posicional vs. `train_idx`/`test_idx` |
| `fold_id` | `Int16` | `predictions.fold_id` (`alpha.py:427`) | ✔ | fold do Alpha doador |
| `path_id` | `Int64` | remapeado de `CPCVSplit.path_id` (não existe em `predictions`) | ✔ | §4.3 |
| `donor_rule` | `Utf8` | `path_matched` \| `group_matched` | ✔ | coluna de auditoria (§4.4) |
| `variant` | `Utf8` | `camada1` \| `camada0` | ✔ | nunca misturados |
| `model_id`, `calibrator_id` | `Utf8` | `alpha.py:418-419` | ✔ | asserção §10.1 |
| `side_hat` | `Int8` ∈ {−1,+1} | `predictions.side_hat` | ✔ | **lado é DADO, nunca aprendido** |
| `p_alpha` | `Float64` | `p_long`/`p_short` calibrados | ✔ | OOF estrutural (§10.1) |
| `score_alpha_raw` | `Float64` | `score_{long,short}_raw` | ✔ | **entra no design matrix** (§3.4) |
| `tau_alpha` | `Float64` | **coluna nova** (D-15) | ✔ | §3.5 |
| `margin` | `Float64` | `side_hat × (p_long − p_short)` | ✔ | §3.4 |
| `regime` | `Utf8` | `mf.data.regime` (`dataset.py:236-240`) | ✔ | §6.1 |
| `regime_ohe_*` | `Int8` | one-hot drop-first, níveis fixos a priori | ✔ | §6.3 |
| `atr_at_t0` | `Float64` | `labels.atr_at_t0` | ✔ | conhecido em `t0` |
| `barrier_hit`, `ret_net` | `Utf8`, `Float64` | `labels` | ✔ | **futuro — só alvo/máscara** |
| `fill_assumed` | `Boolean` | `barrier_hit != "NOFILL"` | ✔ | **nunca feature** |
| `y_meta` | `Int8` \| null | `1[ret_net > 0]`; null se `~fill_assumed` | ✔ | §3.3 |
| `uniqueness_universe` | `Float64` | `labels.uniqueness` | ✔ | diagnóstico §5 |
| `uniqueness_subpop` | `Float64` | recalculado por `(symbol, side)` (§5) | ✔ | peso |
| `meta_sample_weight` | `Float64` | §5 | ✔ | — |
| `is_oof` | `Boolean` | `predictions.is_oof` | ✔ | **vacuoso** (§10.1) |
| `meta_status` | `Utf8` | `OK` \| `INSUFFICIENT_SAMPLE` \| `UNSEEN_REGIME` | ✔ | §6.4, §7.3 |
| `meta_split_id`, `role` | `Int16`, `Utf8` | laço de folds | ✔ | — |

**`META_FORBIDDEN_FEATURES`** (constante de módulo, validada em
`build_meta_design_matrix`, mesma disciplina de `DESIGN_COLUMNS`):
`{t1, barrier_hit, ret_net, y_meta, fill_assumed, meta_sample_weight,
uniqueness_*}`.

### 3.3 Definições operacionais do alvo (D-04)

1. **`y_meta` é PnL, não price action.** `ret_net` **já vem projetado no
   lado** — `triple_barrier` emite uma linha por lado. **Não multiplicar por
   `side` de novo** (dupla projeção; erro fácil ao seguir o snippet do AFML
   literalmente).
2. `ret_net == 0.0` exato → `y_meta = 0`.
3. **`TIME` não é caso especial.** O snippet 3.7 impresso usa
   `sign(ret·side)`; o **Exercício 3.3 (p.55)** sugere 0 na vertical. AFML
   **não trava**. Nossa regra: `1[ret_net > 0]` inclusive em TIME.
4. **`NOFILL` sai do treino** (`y_meta = null`) e **fica no frame** — o
   denominador do ablation precisa da população completa.
5. **`y_meta` ≠ label do Alpha.** O Alpha treina
   `y = 1[barrier_hit == "TP"]` (`alpha.py:229`); o Meta treina PnL líquida.
   **A assimetria é o mecanismo**: o Alpha não otimiza custo e funding.

### 3.4 Design matrix — reescrito (correção de 3 erros da v1)

```
[score_alpha_raw_z, p_alpha, margin, side_hat, regime_ohe_*]
```

**Erro 1 da v1 — `score_raw` excluído por argumento falso.** A v1 marcava
`p_alpha_raw` como *"monotônico em `p_alpha`, logo colinear"*.
**Monotônico ⇏ colinear.** `p_alpha = IsotonicRegression(score_raw)`
(`alpha.py:262-263`) é uma **função escada**: *many-to-one*. `score_raw`
carrega **estritamente mais** informação; a ordenação dentro de cada bloco é
destruída. O argumento inverte a direção da perda.

E o Meta vive exatamente onde o achatamento é pior: `tau` é o quantil
`1 − target_signal_rate = 98,11%` da distribuição **calibrada** do treino
(`alpha.py:265-267`) ⟹ a população do Meta é a **cauda superior** da escada.
Dois cenários, ambos plausíveis:
- **A — achatamento de cauda:** o bloco isotônico do topo cobre a
  subpopulação inteira ⟹ `p_alpha` é **constante** ali enquanto `score_raw`
  ainda ordena.
- **B — calibrador degenerado:** `_stratified_calib_split` recorta 25% do
  treino do fold; com sub-split pequeno a isotônica colapsa para 1-2 blocos.
  `p_alpha` vira coluna de variância ~zero. Isso não é colinearidade, é
  inutilidade.

**Consequência de `tau` ser comparação estrita** (`alpha.py:382-383`): se um
bloco plano cair exatamente em `tau`, `>` exclui a massa inteira e `>=` a
inclui; a taxa de sinal realizada **salta descontinuamente** e não iguala
`target_signal_rate` — o orçamento de fees (R3) passa a ser cumprido por
acidente do empate.

**Decisão:** `score_alpha_raw` entra, **padronizado dentro do fold e por
lado** (a escala do score cru não é comparável entre folds). A exclusão vira
**braço de ablação**, não veredito de schema. Regra travada: se
`n_distinct(p_alpha)` na subpopulação ficar abaixo de um piso derivado do
número de blocos isotônicos (`TBD — medir` em E0), **`p_alpha` sai e
`score_raw` fica sozinho**.

*Alternativa registrada, não adotada:* `rank(score_raw)` dentro do fold —
invariante a escala, imune ao achatamento, resolve comparabilidade sem exigir
`tau`. Fica como segundo braço de ablação.

**Erro 2 da v1 — features não projetadas no lado enquanto o alvo é.**
`side_hat = +1 ⟺ p_long > p_short ⟺ spread > 0`, exatamente
(`alpha.py:382-383`) — logo `sign(p_alpha_spread) ≡ side_hat`, e um
coeficiente único em `spread` imporia efeito de sinal **oposto** em long e
short. Mas "margem grande a favor do lado escolhido" deve ser bom nos
**dois**. Correção: `margin = side_hat × (p_long − p_short) = |spread|`, com
`side_hat` como intercepto por lado.

**Erro 3 da v1 — `regime_tradeable` no design matrix.**
`tradeable = decoded_mask & ~is_stress_state` (`src/regime/build_hmm.py:235`),
função do estado decodificado. Excluídas as linhas sem decode (§6.4),
`tradeable` é **combinação linear exata** das dummies ⟹ matriz
rank-deficiente. A guarda de "variância zero" **não pega colinearidade**.
`regime_tradeable` **sai do design matrix** (fica no frame, para
estratificação e gate estrutural).

**Fora do design matrix por decisão:** as 10 features T1. O Alpha já as viu;
incluí-las faz o Meta virar um segundo Alpha. Braço de ablação, nunca
default.

**Padronização ajustada só no treino do fold** — B03.

**Guarda de posto:** checagem de `np.linalg.matrix_rank` / número de condição
do bloco categórico in-fold, registrada por fold. Substitui a guarda de
variância-zero da v1, que era insuficiente.

### 3.5 `tau` persistido (D-15) — a correção de maior retorno por custo

`tau` é calculado (`alpha.py:265-267`) e **descartado** — não está no schema
de predições (`alpha.py:501-519`) nem no payload de diagnóstico
(`pipeline.py:168-210`). Uma coluna `tau_alpha` no schema destrava **três**
coisas de uma vez:

1. a feature de margem `p_alpha − tau` (que a v1 declarou bloqueada em R3);
2. a comparabilidade de `p_alpha` entre folds (o ponto de truncamento passa a
   ser observável);
3. o diagnóstico de massa de empate em `tau` (§3.4).

Custo: um campo. **Requer bump de `schema_version` do artefato** (§14.3).

---

## §4 — Cross-validation

### 4.1 A colisão `(symbol, t0, fold_id)`

`assemble_predictions_table` concatena os 15 folds sem dedup
(`alpha.py:490-498`): cada barra aparece em até 5 folds, "uma vez por caminho
de backtest do CPCV". Esperado, não duplicata.

**Armadilha 1 — nunca deduplique por `t0`.** Média/primeiro/último misturaria
modelos treinados em conjuntos diferentes. Vazamento por agregação.
**Armadilha 2 — nunca treine pooled sobre folds sobrepostos.** O mesmo
`ret_net` contaria até 5 vezes.

### 4.2 A prova de impossibilidade da v1 era falsa

A v1 afirmava: *"com 6 grupos e `n_test_groups=2` não existe fold doador
simultaneamente OOF e cego... cegueira total exigiria CV aninhada com refit do
Alpha (~6× o custo)"*. **Ambas as afirmações são falsas.** Dois quantificadores
escondidos:

- **A prova assumia UM doador global por split.** Ela quantificava `∃f` que
  servisse *todas* as linhas. O requisito é **por linha**: cada linha `r`
  precisa de *algum* `f(r)`. Nada exige que seja o mesmo — e `path_matched`
  já usa doadores múltiplos.
- **A prova fixava `|T_s| = 2` silenciosamente.** O passo "`T_s ⊆ test(f)`
  força `f = s`" só vale porque as cardinalidades são iguais. **Isso é uma
  escolha** (reusar `n_test_groups=2` do CPCV do Alpha), não um fato.

**A construção blindada (`group_matched`):**

> Bloco de teste do Meta = **1 grupo**, `T_s = {g}`.
> Para cada linha de treino no grupo `h ≠ g`: doador `f(r)` = o fold cujo
> `test = {g,h}`.
> - **OOF:** `r ∈ h ⊆ test(f(r))` ✔
> - **Cegueira TOTAL:** `test(f(r)) = {g,h} ⊇ {g} = T_s` ⟹ o doador treinou
>   em `todos \ {g,h}`, que **exclui `g` inteiro** ✔

Esse fold sempre existe: `cpcv_n_groups: 6` × `cpcv_n_test_groups: 2` ⟹
**`C(6,2) = 15` folds — todos os pares** (`constants.yaml:1141-1152`;
confirmado no artefato, `"n_cpcv_splits": 15`). Para `g` fixo há 5
candidatos. E as predições **já estão em disco**.

**Custo real: zero retreino. O custo é poder estatístico** — com `|T_s| = 1`
os 6 blocos ladrilham o dataset **uma vez** ⟹ **1 caminho OOS, não 5** ⟹
perde-se o critério ≥4/5 paths. Por isso `group_matched` não é o braço
primário; é o braço de verificação.

### 4.3 Os dois braços (D-08)

**Braço primário — `path_matched`** (5 caminhos, permite o critério ≥4/5):

> Para o meta-fold `s` (split `s` do Alpha, path `p`):
> **TESTE** = `fold_id == s` e `_pos ∈ splits[s].test_idx`.
> **TREINO** = `fold_id ∈ path(p) \ {s}` **e** `_pos ∈ splits[s].train_idx`.

`_path_assignment` (`cpcv.py:329-337`) usa 1-fatoração round-robin ⟹ dentro
de um `path_id` os blocos de teste **particionam** os grupos ⟹ `(symbol, t0)`
é único no path. Confirmado em auditoria contra a implementação, não só a
docstring. `train_idx` já traz purge + embargo (`cpcv.py:495`).

**Exposição do doador, quantificada corretamente:** a v1 dizia que o melhor
alcançável era "meio-cego" (`|test(f) ∩ T_s| = 1`). **Errado** — dentro do
path a interseção é **0**: o doador é *totalmente vidente* sobre `T_s`. Um
doador com interseção 1 exige `path(f) ≠ p`, o que reintroduz a
pseudo-replicação. **Por isso `half_blind` foi descartado e substituído por
`group_matched`**, que é estritamente melhor: cegueira total em vez de
parcial, e sem cross-path.

**Braço de verificação — `group_matched`** (1 caminho, cegueira total).

**Ordem de leitura travada a priori:**
- concordam ⟹ exposição do doador não é o mecanismo;
- discordam ⟹ `path_matched` está contaminado e **`group_matched` manda**,
  apesar do caminho único.
- **"Discordar" definido operacionalmente:** o veredito binário do gate F6
  muda em ≥1 path, **ou** `|ΔSharpe|` excede o desvio-padrão entre paths do
  braço `path_matched`.

**Controle positivo obrigatório** (a v1 não tinha, e sem ele "não virou" é
ininterpretável): injetar vazamento calibrável em `p_alpha`
(`p_alpha' = (1−λ)·p_alpha + λ·y_meta`, λ pequeno) e **verificar que o
contraste entre braços detecta λ**. Mesma disciplina que §10.2 já exige do
teste #10.

**Colisão residual — `variant`:** construído para um `variant` por vez;
`variant` na chave torna a mistura impossível por engano.

### 4.4 CPCV vs. walk-forward — o braço que faltava

Um modelo CPCV é treinado em blocos que incluem dado **posterior** ao bloco
de teste. O Alpha de produção é treinado só com passado. A estrutura de erro
de um Alpha informado-pelo-futuro é sistematicamente diferente da de um Alpha
causal.

A v1 afirmava que o arranjo `path_matched` era *"exatamente a configuração de
produção"* — **é falso**. Meta-labeling é, por definição, um modelo do **erro
do primário**; se o primário de validação erra por um motivo e o de produção
por outro, o mapa não transfere.

**Correção — gate F6b, bloqueante:** o ablation (§9) é replicado sobre
predições de **walk-forward ancorado**
(`src/validation/volatility_walkforward.py::generate_anchored_walk_forward_splits`,
protocolo que `src/regime/build_hmm.py:174` já consome), com o mesmo critério.
Se A1 > p95(A2) sob CPCV **mas não sob WF**, o resultado CPCV é artefato.

### 4.5 Purge cross-símbolo — bloqueante (D-16)

A v1 tratou isto como intensidade de correlação e mandou para o Manager. **O
problema é estrutural e maior.**

`assign_time_groups` (`cpcv.py:270-278`) faz
`np.linspace(min(t0), max(t0), n_groups+1)` sobre o `t0` **do frame
recebido**, e `load_labels_v1` lê um frame **por símbolo**
(`data/labels/{symbol}/{grade}/{version}/`). BTC (2020-01→2026-08) e
SOL/XRP (históricos mais curtos) produzem **fronteiras de grupo em datas
diferentes**. O grupo 3 do BTC e o do ETH cobrem janelas distintas.

Consequência: uma linha de treino de BTC pode ser **exatamente
contemporânea** de uma linha de teste de ETH, e o purge — que opera por `t1`
dentro do array passado a `generate_splits` — **nunca a vê**. Com ρ
cross-asset de 0,70–0,83 (`AG-144`), é quase o mesmo evento. O purge não fica
fraco: fica **ausente**.

E há um segundo efeito: `fold_id == s` **não designa a mesma janela de
calendário** em símbolos diferentes, o que quebra a premissa de espaço de
índice único do §4.3.

**Correção, pré-requisito de F1:** as fronteiras `edges_ms` são calculadas
**uma vez, sobre a união dos `t0` dos 5 símbolos**, e reaplicadas a cada
símbolo — não por `linspace` per-símbolo. Enquanto isso não existir, **F6
roda por símbolo, nunca pooled**, e o gate exige permanência cross-símbolo em
vez de cross-path. Custo em amostra: `TBD — medir`.

### 4.6 "≥4 de 5 paths" — nota de proveniência obrigatória

Os 5 paths **não são 5 replicações independentes**: cada um reconstrói a
**mesma população de linhas** (`backtest_lite.py:145-151`); só muda qual
modelo-fold produziu `p_alpha`. A correlação entre vereditos é alta.

`alpha_layer1_permanence_min_paths = 4` foi **derivada para o Alpha** (§5.11,
adaptação de "9 de 14 janelas walk-forward"), onde as 14 janelas WF **são**
aproximadamente independentes. O reuso importa o número **sem importar a
propriedade que o justificava**.

**Regra travada:** o reuso é permitido, mas (a) leva nota de proveniência
explícita dizendo que a independência não foi herdada; (b) o critério
**primário** de permanência passa a ser sobre eixos genuinamente
independentes — **os 5 símbolos** e as janelas walk-forward (§4.4) — com os
paths como critério secundário. Desequilíbrio medido no artefato legado:
`n_signals` de 2.599 a 6.739 entre paths (2,6×), e a regra pesa todos igual.

### 4.7 `assert_grade_consistent` (D-09)

Dois ramos (`cpcv.py:428-481`): o **dollar-bar** (`:455-463`) faz
short-circuit para `_assert_dollar_bar_grade_consistent`, que lê
`_calibration.json` e **nunca olha `labels`** — sobre subconjunto esparso
passa **silenciosamente**, o que é pior que quebrar; o **de tempo**
(`:465-481`) compara a mediana de `diff(unique(t0))` contra `step_ms` e
quebra com `CPCVError` espúrio.

**Decisão: não relaxar a guarda; não chamá-la sobre o subconjunto.** Splits
gerados sobre o frame denso; seleção **posicional**:

```
splits         = cpcv.generate_splits(df_dense, config=cfg, symbol=symbol)
meta_train_pos = intersect(splits[s].train_idx, signal_positions)
meta_test_pos  = intersect(splits[s].test_idx,  signal_positions)
```

Purge e embargo ficam no **relógio real**; zero mudança em `cpcv.py`.
**Anti-padrões rejeitados:** `grade_id` "efetivo" derivado do subconjunto;
`allow_sparse=True`.

**Guarda falsificável** (correção da v1, que propunha um grep contraditório
com §12 — `meta.py` contém o orquestrador e precisa dos splits): `meta.py`
**recebe `CPCVResult` como parâmetro**, e uma asserção de runtime verifica
`frame_passado.height == df_dense.height`. Substitui o teste de string, que
seria driblável por import indireto.

Nota: a taxa de sinal realizada é **~3,4%** (`n_signals` por caminho ≈
5.400-6.400 sobre 163.584 barras no artefato legado), não os 1,89% de
`target_signal_rate` — que é quantil **por lado** (`alpha.py:267`), e a união
dos dois lados é maior.

---

## §5 — Pesos e unicidade (D-10)

**O que existe:** `apply_weights` (`src/labels/weights.py:120-196`) calcula
concorrência **por lado, sobre o universo**, em laço (`:140-149`), e
normaliza `sample_weight = uniqueness × |ret_net|` para média 1 global
(produto em `:153`, normalização em `:188-195`).
`compute_concurrency_and_uniqueness(t0, t1)` (`:40`) é pura, e **levanta
`ValueError` se `t0` não vier ascendente** (`:71-78`).

**Por que herdar do universo está errado:** (a) a concorrência foi contada
contra todas as barras, não contra a população sinalizada; (b) a normalização
"média 1" não vale num subconjunto; (c) concorrência global conta vizinhos
que estão **no bloco de teste** ⟹ o peso de uma linha de treino codifica a
densidade de sinal do teste.

**AFML não decide isso** (Cap. 4 não trata da subpopulação em que o primário
disparou).

**Regra travada, com o grão explícito** (correção da v1, que chamava a função
uma vez sobre a subpopulação pooled):

```
para cada meta-fold, sobre as linhas de TREINO daquele fold:
    groupby(symbol, side_hat) -> sort(t0)
        -> compute_concurrency_and_uniqueness(t0_ms, t1_ms)
    concatenar
meta_sample_weight = uniqueness_subpop * |ret_net|,
                     normalizado para média 1 DENTRO do treino do fold
```

Sem o `groupby`, a chamada ou levanta `ValueError` (linhas concatenadas por
`fold_id` não são ordenadas) ou conta um evento de BTC como concorrente de um
de ETH e um short como concorrente de um long — e `n_eff_subpop` sairia
subestimado por ~5×, mandando todos os folds para `INSUFFICIENT_SAMPLE`.
Isso seria lido como "a amostra matou o desenho" quando foi um bug de
agrupamento.

*Se a decisão for contar concorrência cross-símbolo de propósito (defensável
dado ρ = 0,70–0,83), precisa ser decisão declarada com proveniência, não
efeito colateral da assinatura.*

**Correção da justificativa (a v1 estava factualmente errada).** A v1 mandava
escrever no docstring: *"é o módulo, não o sinal — não vaza `y_meta`"*.
**Falso:** com `tp_atr_mult = 2.0` e `sl_atr_mult = 1.5`
(`constants.yaml:178-193`), `E[|ret_net| | y=1] ≈ 1,33 × E[|ret_net| | y=0]`
— o módulo é quase um classificador do sinal. A justificativa correta:

> Peso derivado de rótulos de **treino** não é vazamento. Ele **é**
> correlacionado com o alvo, por construção das barreiras 2,0/1,5 — e a
> consequência é que o modelo não estima `P(y=1|X)`, estima uma versão
> inclinada, concentrada em eventos de alta volatilidade.

**Consequências que a v1 não tirava:** (a) o painel §9 precisa reportar
**accuracy ponderada e taxa base ponderada** ao lado das não-ponderadas —
comparar accuracy não-ponderada com um modelo ponderado pode acusar "abaixo
do acaso" num modelo funcionando; (b) medir `corr(|ret_net|, y_meta)` no
fold — se for alta, `weight_hhi` deixa de ser diagnóstico e vira gate.

**Diagnóstico obrigatório** (`UniquenessDivergenceDiagnostic`):
`n_eff_universe_restricted`, `n_eff_subpop`, `uniqueness_inflation_ratio`,
`mean_concurrency` de ambos, `weight_hhi` (HHI de `meta_sample_weight` —
**sobre linhas**, e `hhi.compute_concentration` recebe dict coluna→ganho
(`hhi.py:65-70`), então isto exige um wrapper, não é "de graça" como
`coefficient_shares`).

**Dívida nomeada:** não declaro limiar de `weight_hhi` — B23. Precisa ser
**derivado** do HHI do Alpha (`hhi_importancia`, `alpha.py:403-405`) como
referência. Item para o Manager.

---

## §6 — Regime

### 6.1 Join causal e a coluna que o v1 realmente usa (D-11)

`build_modeling_frame` junta em duas etapas **exatas**
(`dataset.py:232-245`):

```
features(open_time, close_time) ⋈ regime(t0 = open_time)  por _open_time_ms
                                ⋈ labels                   por _close_time_ms == labels.t0
```

Funciona porque `build_regimes` e `build_t1_features` recebem o mesmo
`bar_source`. Não há as-of, logo não há `tolerance` a escolher — o que sob
dollar-bar (barras de duração variável) seria inventar um número (B23).

**Correção factual da v1:** o frame carrega do regime apenas
`regime` (Utf8) e `tradeable` (`dataset.py:236-240`, `join_cols` em `:244`).
As colunas `canonical_id`, `is_stress_state`, `fold_id` **só existem no
builder HMM** (`build_hmm.py:78-107`) e **não chegam** por este caminho. A v1
especificou um schema inatingível pelo caminho "zero mudança" que ela mesma
recomendava.

**Consequência:** o **v1 do Meta usa `regime` (Utf8, níveis fixos do
classificador) como base do one-hot**, não `canonical_id`. Isso mantém D-01
com substrato real e zero mudança em `dataset.py`.

**Migração para o HMM (quando o Manager mandar):** **não é drop-in** — o join
exige uma coluna chamada `regime` e `_assemble_output` emite `canonical_id`;
a troca falha com `ColumnNotFoundError`, não silenciosamente. É **adaptador
de schema** em `dataset.py`, não um parâmetro. A afirmação da v1 de que o
contrato já era "candidato-agnóstico" vale **apenas para `tradeable`**
(`build_hmm.py:26-32`), não para o resto.

**Dívidas registradas:** `close_time` em `_assemble_output` (3 linhas, só se
o HMM for a produção); e **AG novo** — todo `join_asof` cross-grade exige
`tolerance` explícita (o de `m4_critical_windows.py:1119-1121` não tem).

### 6.2 Estabilidade cross-fold — pré-requisito de D-01

Sob o builder HMM, a canonicalização é **por fold do walk-forward**
(`build_hmm.py:207-220`, fix de vazamento) e por **retorno ascendente** com
desempate por variância (`canonicalization.py:173-177`). Logo o estado "R2"
do fold 3 e o do fold 7 estão ligados apenas por *rank de retorno dentro do
próprio fold* — **não são o mesmo objeto**. Empilhar linhas de múltiplos
`regime_fold_id` numa única coluna one-hot pressupõe uma comparabilidade que
ninguém verificou.

Se o efeito real existe mas com sinal oposto em folds distintos, ele
**cancela** e D-01 é rejeitada por artefato de rotulagem. Se não cancelar, é
edge fantasma.

**Regra travada:** medir a estabilidade do mapeamento estado↔características
entre folds **em E0**, antes de qualquer treino. Se o rótulo não for estável,
o AUC de E0 já é ininterpretável, e as opções são (a) ancorar a
canonicalização a quantis de volatilidade do universo congelados a priori, ou
(b) incluir `regime_fold_id` como efeito, assumindo o custo em graus de
liberdade.

*Isto se aplica ao builder HMM. O classificador por quantis do v1 (§6.1) usa
níveis nominais fixos (`R0..R5`) e não tem este problema — mais uma razão
para o v1 usá-lo.*

### 6.3 One-hot, nunca ordinal

Níveis **fixos a priori**, drop-first, nunca derivados do fold. Motivos: (a)
sob canonicalização por retorno, "R2 < R3" não significa volatilidade
(`AG-121`) e um learner linear aprenderia relação inexistente; (b) níveis
derivados do fold fariam o número de colunas mudar por fold.

### 6.4 Salvaguardas — corrigidas

- **Regime ausente do treino mas presente no teste** (o caso que a v1 não
  viu, e o mais provável): descartar a coluna faria uma linha de teste em R4
  ter todas as dummies em 0 — que sob drop-first é **exatamente a codificação
  do nível de referência**. Predição errada, não erro. **Correção:** manter a
  coluna com coeficiente forçado a 0 e marcar a linha como
  `meta_status = "UNSEEN_REGIME"`, com política declarada: **veto**, coerente
  com D-05 ("não aposte").
- **Sentinela `canonical_id = −1` / `fold_id = −1`** (sem decode,
  `build_hmm.py:143-148`): a v1 só tinha regra para treino ("excluir"). Mas
  `m1_walkforward_initial_train_years = 2` (`constants.yaml:1175`) ⟹ os **2
  primeiros anos de cada símbolo** são `−1`, e esse bloco é **contíguo em
  calendário**, caindo inteiro no grupo 0 da partição cronológica. Em teste e
  produção, exclusão não é opção. **Política declarada: veto**, e reportar por
  fold quantas linhas de teste caem em `−1` ou `UNSEEN_REGIME`.
- **Asserção pós-join:** 100% das linhas com `regime` não-nulo e
  `regime_classifier_id` constante. Nulo ⟹ `ValueError` com contagem e
  intervalo. **Nunca imputação silenciosa.**
- **Nunca ler volatilidade da ordem do id** (`AG-121`).

---

## §7 — Learner (D-02)

### 7.1 Interface

```python
class MetaLearner(Protocol):
    learner_id: str
    def fit(self, X: FloatArray, y: IntArray, w: FloatArray) -> None: ...
    def predict_score(self, X: FloatArray) -> FloatArray: ...
    def coefficient_shares(self) -> dict[str, float]: ...
    def serialize(self, dest: Path) -> None: ...        # D-17, §14.4
```

`predict_score`, não `predict_proba`: o consumo v1 é limiar por quantil
(§8.3), e o nome não deve sugerir probabilidade calibrada.

### 7.2 Implementações

- **`LogitL2Meta`** — default e único habilitado abaixo do gate.
  `LogisticRegression(penalty="l2", C=meta_logit_c, solver="lbfgs")`.
  **Sobre `class_weight`:** o Alpha faz as **duas** coisas —
  `scale_pos_weight = n_neg/n_pos` (`alpha.py:239-241`, passado em `:253`)
  **e** `sample_weight` de unicidade (`:259`). São tratados lá como
  ortogonais, não substitutos. `y_meta = 1[ret_net > 0]` pode ter taxa base
  longe de 0,5 sob R2. **Decisão:** herdar o padrão do Alpha —
  `class_weight="balanced"` **e** `sample_weight`, com a divergência da v1
  registrada como corrigida.
- **`BlockedGBMMeta`** (LightGBM) — `fit()` levanta
  `MetaLearnerBlockedError` incondicionalmente na v1.

### 7.3 Guarda de amostra — corrigida

```python
def assert_sample_sufficient(n_events_eff: float, n_features_effective: int) -> None:
    epv   = float(load_constant("meta_min_events_per_variable"))
    floor = epv * n_features_effective
    if n_events_eff < floor:
        raise InsufficientMetaSampleError(...)
```

- `n_events_eff` = **`Σ uniqueness_subpop` da classe minoritária** no treino
  do fold (B24 — medido).
- `n_features_effective` é **recalculado por fold** (o número de colunas muda
  com descarte/colinearidade, §6.4).
- **Falha alto**, não degrada em silêncio para a logística.
- **`INSUFFICIENT_SAMPLE` ⟹ pass-through** (`accept = True`,
  `p_meta = null`), com `WARNING`. Vetar tudo por escassez de amostra do
  *filtro* mataria a estratégia por um problema do acessório.

**Correção da v1 sobre a classe da constante:** `meta_min_events_per_variable`
foi declarada **classe C**. `CLAUDE.md` §Proveniência regra 3: *"Guardrails
classe C são quantis, nunca número redondo."* `10` é o número redondo
arquetípico. E ela decide se um fold **ajusta modelo ou não** — isso é classe
B no mínimo. Além disso, a v1 chamou o piso de `DERIVED`; **não é** — EPV=10
foi estabelecida para logística **não-penalizada** contando **eventos brutos
independentes**, e aqui é aplicada a logística **L2** contando **`Σ
uniqueness`**. Duas substituições, nenhuma validada. Ver §11.

**O risco simétrico, que a v1 não nomeou:** R4 dizia "o erro seria baixar o
EPV para fazer caber". O risco oposto é o EPV estar **errado por transplante**
e matar o desenho sem motivo — e em classe C com `sweep_required: false`,
nada obrigaria a testar a sensibilidade. Corrigido em §11.

### 7.4 Por que não CatBoost, e o que fica registrado contra nós

**CatBoost descartado:** (i) o ganho isolado do *ordered boosting* em função
de `n` **nunca foi replicado independentemente** — os revisores do NeurIPS
2018 suspeitaram de tuning assimétrico das baselines; (ii) **em CPU o default
é `Plain`**, não `Ordered` — o mecanismo não vem ligado; (iii) terceira stack
de GBM, API distinta de `monotone_constraints`; (iv) o ganho concentra-se em
categóricas de alta cardinalidade, que este Meta não tem.

**Contra nós:** AFML §6.6 prefere bagging a boosting em finanças; se o gate
abrir, `RandomForest` com `max_samples = unicidade média` é **mais defensável
pelo cânone** que LightGBM. Nota para o Manager.

**Sobre a evidência de amostra pequena** (que sustenta a logística como
default, não concessão): simulações clínicas com estrutura análoga (binária,
baixo SNR, EPV limitado) mostram boosting exigindo amostra 2–3× maior que
logística para o mesmo erro de calibração, e LightGBM superando a logística em
confiabilidade só acima de `n > 10⁴`. **Estes números são load-bearing para
D-02 e precisam de citação nominal antes de o documento ir a governança** —
registrado como pendência de proveniência (§17), não como fato estabelecido.

### 7.5 O gate de HHI do DoD não se aplica na forma herdada

O DoD de "código de modelo" exige HHI < 0,25 e maior share < 0,30. Mas D-01
afirma que **regime é a vantagem informacional** — isto é, o desenho *espera*
que regime domine. Se dominar o suficiente para o Meta ter valor,
`max_share > 0,30` e o DoD reprova; se o DoD passar, é evidência contra D-01.

**Um gate que só pode ser satisfeito quando a hipótese central falha é pior
que nenhum gate** — será afrouxado no momento de aplicar (`AG-114`).

**Decisão declarada antes de rodar:** o DoD de HHI **não se aplica ao Meta na
forma numérica herdada do Alpha** (10 features T1, expectativa de difusão).
Substituído por diagnóstico com semântica própria: share de regime vs. share
de `p_alpha`/`score_raw`/`margin`, **reportado, sem limiar** (B23 impede
inventar um). Registrado como decisão, não deixado implícito.

---

## §8 — Consumo de `p_meta`

### 8.1 Filtro binário (D-06)

```
side_final = side_hat  se p_meta >= tau_meta,  senão 0
```

Com lote mínimo = 33% do equity (R1), os tamanhos realizáveis são ≈ {0,1,2,3}
unidades. `compute_sizing` (`src/risk/sizing.py:102-186`) deriva
`notional_req = risk_usd / stop_pct`, depois `qty_raw = notional_req /
mark_price`, depois `floor_to_step` — e **não recebe probabilidade**, nem vai
receber (`risk ↛ models`). A discretização de tamanho do AFML §10.5 já está
satisfeita **pela física do lote**.

### 8.2 Veto-em-zero, contra AFML §10.3 (D-05)

AFML §10.3: `m = side · (2Φ(z) − 1)`. Com ‖X‖=2 e `p < 0,5`, `m < 0` ⟹
`side · m` **inverte o lado** — contradizendo o §3.6 do mesmo livro.
Resolução: **veto-em-zero**. Em meta-labeling `p = P(o primário acertou)`;
`p < 0,5` significa "não aposte", não "aposte ao contrário". `meta.py` não
tem função que escreva em `side_hat`, e isso é testado.

### 8.3 `tau_meta` a priori, e o contrato restrito de D-07

`tau_meta` = quantil da distribuição de score do **próprio treino do fold**
(mesmo mecanismo do Alpha, `alpha.py:21-25`). Quantil é **invariante a
transformação monótona** ⟹ calibrar não muda o conjunto aceito ⟹ a superfície
B08 sai do escopo.

**Restrição do contrato (correção da v1).** A invariância vale para **uma**
transformação monótona. Sob `path_matched`, `p_alpha` num mesmo conjunto de
treino vem de **até 5 isotônicas diferentes** — e a mistura de transformações
monótonas *distintas* **não é ela própria monótona**. Logo:

> D-07 cobre o caso de doador único. Sob doadores múltiplos, a invariância é
> **aproximada**, não exata. `group_matched` sofre do mesmo em grau menor
> (5 doadores por caminho, mas cegos). Isto é registrado como limitação
> conhecida, e é mais um motivo para persistir `p_meta` contínuo (§14.4).

**Se a calibração entrar:** **Platt (2 parâmetros) ou beta (3 parâmetros)**,
não isotônica — que precisa de >1.000–2.000 amostras (Niculescu-Mizil &
Caruana 2005, ICML e UAI; doc do scikit-learn desaconselha com ≪1000). Beta
domina Platt em dois casos que provavelmente temos: escores assimétricos e
classificador já aproximadamente calibrado (a família logística **não contém
a identidade**, logo pode *descalibrar*; Kull et al. 2017). Ojeda et al.
(2023, *Statistics in Medicine*) achou logística e beta consistentemente
melhores em simulação. *O código publicado dos autores de meta-labeling usa
isotônica — mas sobre ~6.000 observações sintéticas IID, acima do limiar e
sem CPCV.*

**Definição operacional do quantil.** Grade a priori
(`meta_tau_grid_quantiles`); escolhe-se o quantil que maximiza a **PnL
líquida realizada in-fold do subconjunto aceito**; **empate** ⟹ vence o menor
pass-rate.

**Correção da v1 — o epsilon de empate era vazio.** `1e-6` sobre PnL somada
faz o empate nunca ocorrer, reduzindo a regra a argmax puro. A cláusula existe
para injetar preferência estrutural (menos trades, R3 folgado) contra o
otimismo do argmax. **Correção:** declarar a **unidade** de PnL (fração de
equity, somada sobre trades aceitos) e derivar o epsilon do **custo
round-trip de um trade médio** — "empate" = diferença menor que o PnL de um
trade. Isso o torna `DERIVED` e economicamente significativo (§11).

### 8.4 Onde `p_meta` encontra o Risk — e onde não

`src.models ↛ src.execution`; `src.risk ↛ {src.execution, src.models}`
(`pyproject.toml:178-197`). **Nenhum import** liga `meta.py` a `risk/`. O
caminho é **artefato de dado**:

```
src/models/meta.py ─escreve─▶ predictions/meta/{symbol}/{tf}/{model_id}/predictions.parquet
                                          │
                                Decision Engine (src/decision/, não existe)
                                          │
                                RiskEngineInputs ─▶ src/risk/limits.py::evaluate_all
```

Precedente: `regime_tradeable` já é campo de `RiskEngineInputs` alimentado por
bool pré-computado, **não por import**.

**`p_meta` NÃO vira `control_20`.** Os controles são **restrições de
segurança**; `p_meta` é **seleção de sinal**. Misturar os dois foi o erro do
gate de regime — wireado antes da medição que o justificasse e desligado em
2026-08-22 (`src/risk/limits.py:575-581`).

**Decision Engine:** pacote **novo** `src/decision/`. Não pode ser
`src/risk/` (`risk ↛ models`) nem `src/models/` (inverteria o pipeline). Fora
do escopo; registrado como dependência.

---

## §9 — Ablation (D-12) — reescrito

**É o único teste que distingue "o Meta seleciona" de "o Meta reduz
exposição".** A armadilha, num caso documentado: drawdown −93% com **accuracy
48% (abaixo do acaso)** e win rate **caindo** de 49,3% para 43,0% — ganho
100% de exposição, zero discriminação. *(Este caso carece de citação nominal;
ver §17.)*

**Quatro braços:**

| braço | descrição |
|---|---|
| **A0** | Alpha sem filtro |
| **A1** | Alpha + Meta (`p_meta ≥ tau_meta`) |
| **A2** | Alpha + **filtro aleatório com a MESMA BUSCA** (correção crítica) |
| **A3** | Alpha + filtro por `p_alpha` top-k, pareado em pass-rate no mesmo estrato |

**Correção 1 — o nulo A2 da v1 estava enviesado a favor de passar.** A1
escolhe `tau_meta` maximizando PnL in-fold sobre 5 quantis; a A2 da v1 apenas
sorteava com probabilidade fixa, **sem busca**. O nulo media a pergunta errada.
**Cada réplica de A2 deve executar a mesma busca:** sortear scores aleatórios,
aplicar `meta_tau_grid_quantiles`, escolher o quantil de maior PnL in-fold, e
só então medir OOS. É a única forma de o nulo carregar o mesmo otimismo.

**Correção 2 — pareamento por estrato**, não por path: `(path_id, fold_id,
symbol, side_hat)`. `tau_meta` é escolhido por fold, e o pool é multi-símbolo
e bi-lateral; parear no nível de path não neutraliza concentração em
folds/símbolos/lados de alto `|ret|`.

**Correção 3 — A3 vira gate.** A v1 tinha A3 como braço sem poder de decisão:
o desenho poderia aprovar um segundo modelo, com CV própria, artefato próprio
e 12 fases, **sem nunca demonstrar que bate reduzir `target_signal_rate`**,
que custa uma linha de config. E é o resultado nulo mais provável dado §3.4.

**Detalhe que impede viés:** o sorteio de A2 acontece sobre a população de
**SINAIS** (incluindo `NOFILL`); a máscara de fill é aplicada **depois**. Se
o nulo sorteasse só entre preenchidos, o Meta ganharia de graça caso
aceitasse barras que preenchem.

**Critério de aprovação, travado a priori:**

> F6 passa sse `sharpe(A1) > p95(nulo A2)` **E** `sharpe(A1) > sharpe(A3)`,
> em **≥4 dos 5 paths** — contando **apenas paths cujos folds têm todos
> `meta_status == OK`**. Paths com qualquer pass-through são reportados em
> separado e contam como "não superou".
> **F6b:** o mesmo, replicado sobre walk-forward ancorado (§4.4).

**Correção 4 — pass-through contaminava a estatística do gate.** §7.3 diz
para estratificar por `meta_status`, mas a v1 aplicava o gate ao Sharpe do
path, que agrega 3 folds e pode misturar folds com modelo e sem. Se 2 de 3
forem pass-through, o Sharpe do path é o do Alpha, A1 e A2 convergem, e o
veredito vira ruído — que depois entra na contagem com peso total.

**Correção 5 — mecanismo em vez de declaração.** A v1 dizia *"a escrita do
artefato é condicionada ao ablation ter rodado"* sem mecanismo, logo após
escrever *"gate que depende de alguém lembrar de rodar não é gate"*.
**Correção:** o writer do artefato de validação **recebe obrigatoriamente o
objeto `AblationResult`** (não um bool, não flag de config) e levanta se
ausente — mesma disciplina de "receber o objeto, não confiar na ordem" do
§4.7. E o FLAG de win-rate **escreve um campo `exposure_reduction_suspected`
no artefato**, que o gate lê e converte em falha do path.

**Painel obrigatório, por braço:** `n_signals`, `n_accept`, `pass_rate`,
`n_filled`, `fill_rate`, **accuracy ponderada e não-ponderada vs. taxa base
ponderada e não-ponderada** (§5), `win_rate`, `mean/std trade ret`,
`sharpe_naive`, Sharpe por path + `permanence_count`, `decomposition.decompose`
sobre o aceito, **exposição total**, e **Jaccard do conjunto aceito entre A1 e
A3** — se alto, o Meta é reparametrização de `tau`, e isso tem de aparecer
como número.

**Nota:** `run_b1_side_shuffle` **não** substitui A2 — aquele sorteia *lado*
mantendo a barra; A2 sorteia *aceitação* mantendo o lado.

---

## §10 — Enforcement de B07/B08 (D-13)

**Estado:** `tools/lint/banned_patterns.py:55-56` marca B07/B08
`automated=False`; teste #10 é `NOT_APPLICABLE_V1_1`
(`leakage.py:554-566`); teste #11 é regex **só sobre `_ALPHA_PATH`**
(`leakage.py:102`); contrato `alpha ↛ meta` é **TODO comentado**
(`pyproject.toml:228-230`).

### 10.1 Camada 1 — runtime, falha alto

**`is_oof` é constante `True` por construção** (`alpha.py:428`) — asseri-lo é
tautologia. Asserções falsificáveis:

```
(a) toda linha:        _pos ∈ splits[fold_id].test_idx
(b) linhas de TREINO:  _pos ∈ splits[meta_split_id].train_idx     ← FALTAVA na v1
(c) linhas de TREINO:  donor_fold != meta_split_id
(d) proveniência:      n_unique(calibrator_id) == 2 × n_unique(fold_id)
                       e n_unique(model_id) == 1
```

**(b) é a correção mais importante desta seção.** Sem ela, uma implementação
que colete as linhas do path por `fold_id` e **esqueça a interseção
posicional** satisfaz (a) e (c), produz um dataset maior (parece melhor), e
**desliga B09 inteiro em silêncio**. `train_idx` é o único objeto que carrega
purge + embargo (`cpcv.py:495`). É o modo de falha mais provável da
implementação de F3.

**(d) corrige um erro da v1**, que exigia `== n_unique(fold_id)` e **falharia
sempre**: há **dois** `calibrator_id` por fold, um por lado
(`alpha.py:389-392`).

`raise MetaLeakageError` — **nunca `assert`** (some sob `python -O`), **nunca
`filter()`** (mascara a causa raiz).

### 10.2 Camada 2 — teste #10 real, com controle positivo

Sai de `NOT_APPLICABLE_V1_1` e executa (a)-(d) sobre artefato real, com
`pytest.skip` condicional (`integration`). **Controle positivo obrigatório:**
frames deliberadamente violando cada uma das 4 asserções, afirmando que o
builder levanta. Sem ele o teste não pode falhar e não prova nada — crítica
que o próprio `leakage.py:562-564` já faz.

### 10.3 Camada 3 — teste #11 estendido

`_META_PATH` em `leakage.py:102`; verificar no fonte que (a) o fit recebe só
`X_train/y_train/w_train`; (b) o `StandardScaler` é ajustado no treino do
fold (reusa `_GLOBAL_SCALER_PATTERN`, `leakage.py:187-189`); (c) `tau_meta` é
derivado do treino.

### 10.4 Camada 4 — lint, com allowlist

**Correção da v1:** a regra proposta (*"todo arquivo em `src/models/` que
menciona `predictions.parquet`/`p_alpha`/`p_long`/`p_short` precisa mencionar
`is_oof`"*) **quebraria o build imediatamente**: `pipeline.py` (4 menções do
gatilho, 0 de `is_oof`) e `_paths.py` (1 e 0) são falsos positivos legítimos —
orquestrador e helper de caminho, e `banned_patterns.py` roda em pre-commit.

**Regra corrigida:** só arquivos que mencionem o gatilho **e** `fit`/`train`,
com allowlist explícita para `pipeline.py`/`_paths.py`. A descrição do
`Pattern` declara que é grep, não prova — **cobertura parcial declarada >
`automated=False`**.

### 10.5 Camada 5 — import-linter

```toml
[[tool.importlinter.contracts]]
name = "alpha não importa meta (§5.8, zero realimentação)"
type = "forbidden"
source_modules = ["src.models.alpha"]
forbidden_modules = ["src.models.meta"]
```

`meta → alpha` continua permitido (o Meta lê o schema). Contratos de pacote já
barram `meta → execution` e `meta → analysis`.

---

## §11 — Constantes

| nome | papel | value | provenance | class | sweep |
|---|---|---|---|---|---|
| `meta_logit_c` | inverso da regularização L2 | `1.0` | `ASSUMED` — convenção sklearn | **B** | `true`, **`[0.5, 1.5]`** (±50% real) |
| `meta_min_events_per_variable` | EPV — insumo do piso (§7.3) | `10` | `LITERATURE (transplantada — EPV=10 é para logística NÃO-penalizada sobre contagem bruta; aqui aplica-se a L2 sobre Σuniqueness; transferência não validada)` | **B** *(era C)* | **`true`, `[5, 20]`** |
| `meta_tau_grid_quantiles` | grade a priori de limiares | `[0.0, 0.25, 0.50, 0.75, 0.90]` | `ASSUMED` — grade declarada a priori (B20) | **B** | **`false`** *(era `true`)* |
| `meta_tau_tie_epsilon` | definição de "empate" (§8.3) | **derivado do custo round-trip de 1 trade** | `DERIVED` *(era ASSUMED)* | **C** *(era D)* | `false` |
| `meta_include_nofill_in_training` | máscara de treino | `false` | `ASSUMED` — decisão de política: NOFILL tem `ret_net=0` por construção, logo sem valor em PnL-por-trade; efeito em `pass_rate` e rotação de capital **não medido** | **B** | **`true`** (booleano, ablation barata) |

**Correções da v1:** (a) `[0.5, 2.0]` era rotulado "±50%" — 2,0 é +100%, e
±50% é o critério que `CLAUDE.md` §16.10 item 4 nomeia; (b) o EPV estava em
classe C violando a regra "classe C são quantis, nunca número redondo", e sem
sweep apesar de decidir se um fold ajusta modelo; (c)
`meta_tau_grid_quantiles` com `sweep_required: true` **autorizava buscar sobre
a busca** — precisamente o que R5 diz que caracterizaria falha do desenho,
escrito na tabela de constantes do mesmo documento; (d)
`meta_include_nofill_in_training` era `DERIVED`, mas a derivação prova que
*prever preenchimento* tem ΔPnL zero, não que NOFILL deva sair do treino —
isso é política.

**Reusadas:** `alpha_random_seed`, `alpha_b1_n_seeds`,
`alpha_layer1_permanence_min_paths` (com a nota de proveniência do §4.6),
`target_signal_rate`, `fee_budget_monthly`, `cpcv_embargo_ms`.

**NÃO criadas (B23):** `meta_min_neff_for_gbm` (`TBD — medir` em F2; até lá o
GBM é bloqueado por `raise`, que não precisa de número); `meta_p_threshold`
(derivado in-fold); `meta_min_lift`/`meta_min_auc_gain` (o gate é percentil do
nulo); limiar de `weight_hhi` (derivar do HHI do Alpha); limiar de HHI do DoD
(§7.5); **ganho esperado do Meta**.

**Orçamento de trials — declarado antes de F1** (correção de R5 da v1, que
mandava declarar "antes de F4", tarde demais porque E0 já teria consumido). A
contabilidade real inclui: E0 (candidato único × 5 paths, com a agregação do
§2.6); os dois braços de doador (§4.3); F6 + F6b; o sweep de `meta_logit_c`;
os braços de ablação de features (§3.4). **`N_lifetime` incrementa por
trial, não uma vez por fase.**

---

## §12 — Onde o código mora

**Novos:**

| arquivo | papel | camada |
|---|---|---|
| `src/analysis/meta_fp_inventory.py` | Gate E0 (§2.6) | `analysis` |
| `src/models/meta_dataset.py` | `build_meta_signal_table`, `donor_fold_for`, asserções §10.1 | `models` |
| `src/models/meta.py` | `MetaLearner`+impls, `run_meta_fold`, `run_all_meta_folds`, `run_meta_sprint` + `__main__` | `models` |
| `src/models/meta_ablation.py` | Braços A0-A3 (§9) | `models` |
| `tests/unit/test_models_meta*.py` | `integration`/`slow` | — |

**Modificados:**

| arquivo | mudança |
|---|---|
| `src/models/alpha.py:407-430, 501-519` | **`tau_alpha` no schema** (D-15); bump de `schema_version` |
| `src/models/backtest_lite.py:79-130` | extrair `join_signals_to_labels(signals, df_all, *, carry=())`; `realize_trades` delega. **Critério: teste `golden` de igualdade bit-a-bit** (§14.5), não "os testes passam" |
| `src/models/pipeline.py:72-98` | `write_predictions_atomic(..., family=, schema_columns=)` |
| `src/models/_paths.py` | criar `predictions_meta_symbol_tf_dir()`. **`predictions/meta/` não está reservado em código** — é prosa em docstring (`:82`) |
| `src/validation/cpcv.py` | `edges_ms` sobre união temporal (§4.5) — **única mudança em `cpcv.py`, e é pré-requisito** |
| `src/models/baselines.py` | `run_b6_random_filter` com busca replicada (§9) |
| `src/validation/leakage.py:102,554-566,569-636` | `_META_PATH`; teste #10 real + controle positivo; #11 estendido |
| `pyproject.toml:228-230` | ativar `alpha ↛ meta` |
| `config/constants.yaml` | 5 constantes (§11) |
| `tools/lint/banned_patterns.py:55` | B07 `automated=True` **com allowlist** |

---

## §13 — Requisitos não-funcionais *(seção nova — lacuna da v1)*

| dimensão | requisito | estado |
|---|---|---|
| Tempo de treino do Meta | `TBD — medir`. Referência: o Alpha leva ~117s por rodada de retreino (`pipeline.py:143`) | não medido |
| Memória | O frame denso de 5 símbolos × R1 é o pico. `TBD — medir` | não medido |
| Latência de inferência ao vivo | Uma barra por vez, ~1 predição. Deve ser ≪ o intervalo de decisão | trivial, mas exige §14.4 |
| Reprodutibilidade | Seeds derivadas (padrão `_derived_seed`, `alpha.py:130-138`); teste `golden` de tolerância zero | herdado |
| Determinismo | ⚠️ `n_jobs=-1` com `tree_method="hist"` **não garante bit-exatidão entre máquinas com contagem de núcleos diferente** (risco herdado do Alpha, sem teste `golden` hoje) | dívida herdada |
| Operabilidade | O que um operador vê quando o Meta veta? `meta_status` + `reason_code` no artefato | §14.2 |

---

## §14 — Ciclo de vida *(seção nova — 5 lacunas da v1)*

### 14.1 Cadência de retreino e o acoplamento Alpha↔Meta

**B22 proíbe retreino por sequência de perdas e exige cadência fixa declarada
a priori.** A v1 não declarava nada — **violação de B22 esperando acontecer**.

**Regra travada:** o Meta é **sempre retreinado junto com o Alpha**, no mesmo
evento, sobre as predições OOF do Alpha novo. **Nunca em cadência própria.**
Motivo: `p_alpha` é feature do Meta; um Alpha retreinado muda a distribuição
da feature, e um Meta calibrado sobre a distribuição antiga é um modelo
aplicado fora do domínio.

**Janela de inconsistência:** entre o retreino do Alpha e o do Meta, o par é
incoerente. Política: **o Meta é desligado (pass-through) até ser retreinado**
— nunca aplicado a predições de um Alpha que ele não viu. Enforcement:
`model_id` do Alpha é gravado no artefato do Meta, e o consumidor **compara**;
divergência ⟹ pass-through com `WARNING`, nunca aplicação silenciosa.

### 14.2 Rollback

Precedente que mostra a falta: o gate de regime foi desligado de
`evaluate_all()` em 2026-08-22 **ad hoc** (`src/risk/limits.py:575-581`).

**Regra travada:** `meta_enabled` é flag de configuração, não de código.
Desligado ⟹ pass-through (`accept = True` para todo sinal), idêntico ao
comportamento de `INSUFFICIENT_SAMPLE`. **Critério de desligamento declarado a
priori:** `TBD — declarar antes de F6`, junto com quem decide e em quanto
tempo. O padrão é que o critério de desligamento seja **o mesmo do gate de
entrada**, medido em janela móvel.

### 14.3 Versionamento de artefato

O relatório do Alpha já tem `schema_version` (`:829`); o artefato de predições
não herda isso. **Regra:** `predictions/meta/` carrega `schema_version`,
`meta_model_id`, `alpha_model_id`, `alpha_schema_version`,
`config_hash`, `code_version`. Leitor com `schema_version` desconhecido
**levanta**, nunca degrada. O bump de D-15 (`tau_alpha`) é o primeiro
exercício desse contrato.

### 14.4 Persistência para scoring ao vivo (D-17) — reusar, não construir

> **Correção de 2026-08-22, posterior à auditoria** — as três versões
> anteriores desta seção (e o §18 da v1) afirmavam que *"não existe
> `save_model`/`joblib`/`pickle` em lugar nenhum de `src/`"* e propunham
> abrir um AG novo. **Factualmente errado no momento da escrita**: a
> infraestrutura foi construída no mesmo dia, em paralelo a este desenho.
> O erro veio de o levantamento ter sido feito antes dos commits
> `2866f2e`/`36862eb`. Registrado em vez de silenciosamente corrigido.

**O que já existe** (verificado, não assumido):

- **`AG-141`** — já aberto, com exatamente este escopo, e com o histórico da
  decisão de sequenciamento do Manager (desacoplar da migração LightGBM).
- **`src/models/persistence.py`** — `write_model_bundle`/`read_model_bundle`,
  **desenho agnóstico ao learner** (`PLANO_MESTRE_PRINCE2.md §15.18`). Só a
  serialização do booster conhece o formato do learner; calibrador, manifesto
  e escrita atômica são reusáveis.
- **`src/io/artifact.py` / `src/io/schema.py`** — writer versionado com
  proveniência-por-hash (ADR-001 action item 2, `§15.16`).
- Achado relevante já registrado ali: o ADR-001 §4.9 assumia calibração
  Platt (2 coeficientes); o código real usa `IsotonicRegression`, persistido
  como `X_thresholds_`/`y_thresholds_` com reconstrução por `np.interp`,
  **verificado bit-exato** (`max abs diff = 0,0`).

**Estado real do `AG-141`: infraestrutura pronta e testada, integração
NÃO feita.** Falta `persist_root` em `alpha.py::run_fold` e a chamada a
`write_model_bundle` após cada `fit_side_model` — deliberadamente não
integrado sem revisão independente. **`AG-141` permanece ABERTO.**

**Consequência para D-17 — o requisito não muda, o plano muda:** o Meta
**reusa `src/models/persistence.py`**, não constrói nada. `MetaLearner.serialize`
delega às primitivas de `src.io.artifact`, e o bundle do Meta carrega, além do
modelo: `tau_meta`, os **níveis do one-hot** de regime (senão a matriz de
inferência não alinha), os parâmetros do `StandardScaler`, e o manifesto de
linhagem (§14.3).

**Nenhum AG novo é aberto para persistência** — seria duplicata de `AG-141`.
O que se registra é a **dependência**: F5 do Meta depende da integração do
`AG-141` no Alpha, porque um Meta serializado consumindo um Alpha não
serializado continua sendo um sistema meio-serializado.

**Achado colateral, registrado como `AG-149`:** `src/models/persistence.py`
(working tree, não commitado no momento desta escrita) referencia **`AG-148`**
em sua docstring, e `AG-148` **não existe** em
`audit/architecture_gaps_log.yaml` — a numeração do log termina em `AG-145`.
Referência órfã: ou o AG está por criar, ou houve colisão de numeração (o
repo já teve uma real, `AG-125`). Este documento numera a partir de `AG-149`
justamente para não colidir com 146-148 em voo.

### 14.5 Critério de "refator puro"

A v1 operacionalizava como *"os testes existentes passam sem edição"*. Isso é
cobertura dos testes existentes, **não bit-exatidão** — e R8 identificava
corretamente que o refator toca `backtest_by_path`, B1/B2/B5 e a decomposição
de PnL já publicadas.

**Correção:** o projeto já tem o marcador `golden` para isto. Gravar o output
de `realize_trades`/`backtest_by_path` **antes** do refator, commitar o hash,
e o critério passa a ser um teste `golden` de igualdade bit-a-bit.

---

## §15 — Sequência

### 15.1 O caminho de 20% — roda sobre artefato em disco, zero treino

```
P1. tau_alpha no schema de predições (D-15) — 1 coluna
    -> destrava a feature de margem, a comparabilidade entre folds,
       e o diagnóstico de empate. Custo trivial.

P2. Diagnóstico de saturação isotônica sobre os predictions.parquet existentes:
    n_distinct(p_alpha) na subpopulação, massa de empate em tau,
    variância p_alpha vs score_raw, n de blocos isotônicos.
    -> responde §3.4 empiricamente, sem treinar nada.

P3. E0-piloto (FP inventory + separabilidade condicional + V de Cramér
    regime×group_id + estabilidade cross-fold do regime).
    -> ordens de grandeza; PROVISÓRIO, grade 15m legada.
```

**P1+P2+P3 respondem as três perguntas caras** — o Meta deve existir?
`p_alpha` carrega informação? regime é um carimbo de data? — **antes de
escrever uma linha de `meta.py`.**

### 15.2 Sequência completa

```
E1  Data Layer 15 estágios -> 100%                    (gate do Manager)
E2  Retreino do Alpha em R1 + migração LightGBM       (§15.14, represada)
    + decisão sobre as 3 features `expanding`
E3  E0-VINCULANTE sobre o Alpha novo (§2.6)
    >>> GATE: falha em >=2 paths -> evidence_ledger + Meta sai do roadmap <<<

F-1 PRÉ-REQUISITO BLOQUEANTE: edges_ms sobre união temporal (§4.5)
    Sem isto, F1..F6 rodam POR SÍMBOLO, nunca pooled.
F0  Refator puro com teste `golden` (§14.5); write_predictions_atomic
    parametrizado; predictions_meta_symbol_tf_dir
F1  meta_dataset.py — build_meta_signal_table + donor_fold_for
    + META_FORBIDDEN_FEATURES + as 4 asserções de §10.1
F2  Unicidade com grão (symbol, side) + UniquenessDivergenceDiagnostic (§5)
    >>> entrega n_eff_subpop medido — decide o gate de GBM <<<
F3  Seleção posicional + os DOIS braços de doador (§4.3)
    + controle positivo sintético de vazamento
F4  MetaLearner + LogitL2Meta + BlockedGBMMeta + assert_sample_sufficient
    + guarda de posto do bloco categórico (§3.4)
F5  tau_meta in-fold (§8.3) + serialização (D-17) + escrita atômica
F6  meta_ablation.py — A0/A1/A2(com busca)/A3 + mecanismo de gate (§9)
    >>> GATE: A1 > p95(A2) E A1 > A3, em >=4/5 paths, só folds OK <<<
F6b Replicação sobre walk-forward ancorado (§4.4)
    >>> GATE bloqueante: se CPCV passa e WF não, o resultado é artefato <<<
F7  Enforcement: teste #10 + controle positivo; #11 estendido;
    import-linter; B07 automated=True com allowlist   [paralelo a F4-F6]
F8  constants.yaml — preencher TBD com valores MEDIDOS. N_lifetime++.
```

**Comandos para o Manager colar** (Claude não executa `.py`):

```
python tools/lint/banned_patterns.py --path src/models/meta.py --strict
python tools/lint/check_constants_provenance.py
python tools/lint/check_constants_referenced.py --src src/models
python tools/lint/check_unguarded_ratios.py --path src/models/meta.py
uv run ruff check src/models/meta.py src/models/meta_dataset.py src/models/meta_ablation.py
uv run mypy src/models/meta.py
uv run lint-imports
uv run pytest tests/unit/test_models_backtest_lite.py -q
uv run pytest -m golden -q
```

---

## §16 — Riscos

**R1 — Exposição do doador.** Sob `path_matched` o doador é **totalmente
vidente** sobre o bloco de teste do Meta (interseção 0, não 1 — correção da
v1). **Mitigação real:** braço `group_matched` (cegueira total, zero
retreino) + controle positivo calibrável. Regra de leitura em §4.3.

**R2 — `p_alpha` degenerado.** Provável, não hipotético (§3.4). Mitigação:
`score_raw` no design matrix + diagnóstico em E0. Se o Meta virar um modelo
puramente de regime, isso é **legítimo** — mas o relatório tem de **dizer
isso**, não vender "meta-labeling".

**R3 — `tau` varia por fold e por lado.** Resolvido por D-15 (`tau_alpha`
persistido) + `margin` invariante.

**R4 — A amostra pode matar o desenho, e isso é um resultado.** Risco
simétrico nomeado: o EPV pode estar **errado por transplante** e matar o
desenho sem motivo — por isso virou classe B com sweep (§11). **O erro seria
baixar o EPV para fazer caber; o erro simétrico é não testá-lo.**

**R5 — Multiplicidade.** Orçamento declarado **antes de F1** (§11).
Candidato de regime é **UM**, fixado a priori.

**R6 — `tau_meta` por PnL in-fold.** Não é seleção OOS (B20 respeitado), mas
consome `N_lifetime` e é fonte de otimismo — agora **replicada no nulo**
(§9), que é a correção que a torna auditável. Reportar sensibilidade a
`tau_meta` fixo no meio da grade.

**R7 — `p_meta` não comparável entre folds/símbolos.** Preço de D-07, agora
com o contrato restrito (§8.3). Nomear a coluna `score_meta` além de
`p_meta`; docstring proíbe uso não-limiar sem calibração.

**R8 — Refator toca caminho de produção.** Mitigado por teste `golden`
(§14.5).

**R9 — Erro de categoria de grade.** E0-piloto vs. E0-vinculante rotulados
(§2.6, §1.3).

**R10 — O maior risco não é técnico.** A pressão para reinterpretar um
resultado marginal como sucesso é máxima quando o resto do motor não produz
edge. A defesa não é código: é o gate declarado **antes** de medir. **A v1
falhava aqui** — cinco defeitos somados (nulo sem busca, paths dependentes,
E0 sem agregação, pass-through no gate, ausência de gate contra A3)
inclinavam a decisão a PASS. Corrigidos. **Se forem afrouxados depois de ver o
resultado, todo o resto deste documento é decoração.**

**R11 — O padrão de falha da v1, nomeado para não repetir.** Os riscos eram
identificados com precisão e depois **mitigados por declaração em vez de
mecanismo** — o FLAG que só imprime, a escrita "condicionada" sem enforcement,
o `half_blind` sem regra de inferência, o "bit-exato" que era "os testes
passam". §10 mostrava que a diferença era conhecida e não aplicada. Toda
mitigação desta v2 tem de apontar para um objeto que levanta, um teste que
falha, ou um campo que o gate lê.

---

## §17 — O que este desenho NÃO decide

- **Ganho esperado do Meta** — `TBD — medir`.
- `meta_min_neff_for_gbm` — `TBD — medir` em F2.
- Limiar de `weight_hhi` — derivar do HHI do Alpha.
- Substituto do gate de HHI do DoD (§7.5) — reportado sem limiar.
- Critério de desligamento do Meta (§14.2) — `TBD — declarar antes de F6`.
- Custo em amostra do purge cross-símbolo (§4.5) — `TBD — medir`.
- Onde exatamente mora o Decision Engine — `src/decision/` é a recomendação.
- **Se o Meta deve existir** — decidido pelo Gate E0.
- **Pendência de proveniência:** os números de literatura de §7.4 (boosting
  2-3×, `n > 10⁴`) e o caso de §9 (−93%/48%) são **load-bearing** e estão sem
  citação nominal. Precisam de fonte com o mesmo rigor da tabela de §2.2
  antes de o documento ir a governança, ou ser rebaixados a argumento
  qualitativo.

---

## §18 — Registro de governança

**Numeração verificada em 2026-08-22** (protocolo `CLAUDE.md`, item 1 —
commits antes de docs): a última seção do PLANO_MESTRE é **§15.18**; o último
AG do log é **AG-145**. Os AGs novos começam em **AG-149**, deixando 146-148
reservados ao trabalho em voo que `src/models/persistence.py` referencia
(§14.4).

1. `PLANO_MESTRE_PRINCE2.md` **§15.19** — D-01..D-17, a revogação do ADR-001
   §3.7/§2.7 pelo Manager, a auditoria de 3 flancos, e o changelog v1→v2.
2. `PLANO_MESTRE_PRINCE2.md` **§11.4 / §15.4** — a linha `11_META_MODEL`
   muda de "⬜ não iniciado, reaberto" para "desenho travado v2, auditado,
   aguardando Gate E0". Mudança material ⟹ **Road Map Vivo v2 republicado na
   mesma sessão** (`§14`, disciplina de `AG-080`).
3. `audit/architecture_gaps_log.yaml`:
   - **`AG-094`** — ganha `addendum_*` de **reversão explícita**. `AG-118` já
     havia registrado a resolução **oposta** como antecipada (*"AG-094 fecha
     como 'Meta não consome nenhum candidato'"*). O log é append-only e
     entrada fechada só ganha addendum — registra-se a reversão com o motivo,
     nunca um fechamento como se não houvesse posição anterior contrária.
   - **`AG-149`** — referência órfã a `AG-148` em `src/models/persistence.py`
     (§14.4).
   - **`AG-150`** — `tau` calculado e descartado; não está no schema de
     predições nem no diagnóstico (D-15, §3.5).
   - **`AG-151`** — purge cross-símbolo: `assign_time_groups` faz `linspace`
     per-símbolo ⟹ fronteiras desalinhadas ⟹ purge **ausente** no pool
     (§4.5).
   - **`AG-152`** — `join_asof` cross-grade sem `tolerance`
     (`m4_critical_windows.py:1119-1121`).
   - **NENHUM AG de persistência** — seria duplicata de `AG-141`, que já
     existe e está aberto (§14.4).
   - **Cadência Alpha↔Meta** não vira AG — era violação de B22 *esperando
     acontecer*, e foi **resolvida por desenho** (§14.1). Registra-se no
     PLANO_MESTRE como decisão, não no log como gap.
4. `config/constants.yaml` — **nada a adicionar nesta rodada.** As 5
   constantes de §11 só nascem com o código que as lê; criá-las agora
   produziria constantes órfãs que `check_constants_referenced.py` reprova.
   Registrado como decisão deliberada, não esquecimento.
5. `audit/evidence_ledger.yaml` — o achado `auc_real_pooled = 0,4978` vs.
   `auc_permuted_pooled = 0,4999` é **estatístico e medido**, e pertence aqui
   (não ao gaps log, que é de arquitetura/integração). Entra com a
   qualificação de §1.2: mede o **motor legado**, descontinuado.
6. `PRD_V3_2_UNIFICADO.md` PARTE VI — ponteiro de **1 linha**, nunca
   reescrita.
7. `docs/SPRINT_LOG.md` — seção narrativa + linha "Meta Model" da tabela de
   estado (hoje diz "fora da V1").

---

## §19 — Changelog da auditoria (v1 → v2)

Três auditores independentes: corretude factual contra o código (95
afirmações verificadas, 73 corretas, 22 problemas); rigor estatístico (6
CRITICAL, 12 HIGH); trade-offs e alternativas.

**Correções que mudaram decisões:**

| # | v1 | v2 | fonte |
|---|---|---|---|
| 1 | "não existe doador OOF e cego; exigiria CV aninhada a ~6× o custo" | **Falso.** `group_matched` é OOF e totalmente cego, com **zero retreino**; o custo é 1 caminho em vez de 5 (§4.2) | trade-offs |
| 2 | `score_raw` fora do design matrix ("monotônico logo colinear") | **Argumento falso.** Isotônica é *many-to-one*; `p_alpha` provavelmente quase-constante na subpopulação. `score_raw` entra (§3.4) | estatístico + trade-offs |
| 3 | `tau` "não recuperável de nenhum artefato" | Persistir é **1 coluna**; destrava 3 achados (D-15) | trade-offs |
| 4 | purge cross-símbolo = "questão aberta para o Manager" | **Ausente, não fraco** — `linspace` per-símbolo desalinha fronteiras. Bloqueante (§4.5) | estatístico |
| 5 | nulo A2 sorteia com taxa fixa | **Enviesado a favor de PASS** — o nulo tem de replicar a busca de `tau` (§9) | estatístico |
| 6 | E0 com métricas em 50 células e critério em 5 paths | **Sem regra de agregação** = `AG-114` reproduzido. Agregação declarada + candidato único (§2.6) | estatístico |
| 7 | "≥4/5 paths" como robustez | Paths **não são independentes**; nota de proveniência + eixos independentes como critério primário (§4.6) | estatístico |
| 8 | `path_matched` = "exatamente a configuração de produção" | **Falso** — CPCV vê blocos futuros; produção é causal. Gate F6b sobre walk-forward (§4.4) | estatístico |
| 9 | `regime_tradeable` no design matrix | **Colinear exato** com o one-hot; sai (§3.4) | estatístico |
| 10 | `p_alpha_spread` como feature | `sign(spread) ≡ side_hat`; features não projetadas enquanto o alvo é. Vira `margin` (§3.4) | estatístico |
| 11 | unicidade em uma chamada sobre a subpopulação | Precisa de `groupby(symbol, side) → sort` — senão `ValueError` ou `n_eff` 5× errado (§5) | factual + estatístico |
| 12 | "é o módulo, não o sinal, logo não vaza" | **Factualmente falso** (`tp=2,0`/`sl=1,5` ⟹ razão 1,33). Justificativa correta + accuracy ponderada no painel (§5) | estatístico |
| 13 | colunas `canonical_id`/`is_stress_state`/`fold_id` no schema | **Não chegam** por `build_modeling_frame`; o v1 usa `regime` (Utf8) (§6.1) | factual |
| 14 | trocar para o HMM = "parâmetro" | **Não é drop-in** — `ColumnNotFoundError`; é adaptador de schema (§6.1) | factual |
| 15 | asserção `n_unique(calibrator_id) == n_unique(fold_id)` | **Falharia sempre** — há 2 por fold, um por lado. `== 2 ×` (§10.1) | factual |
| 16 | 3 asserções de runtime | **Faltava a que protege o purge** (`_pos ∈ train_idx`) — o modo de falha mais provável de F3 (§10.1) | estatístico |
| 17 | B07 `automated=True` com regra ampla | **Quebraria o build** — `pipeline.py` e `_paths.py` são falsos positivos. Allowlist (§10.4) | factual |
| 18 | `meta_min_events_per_variable` classe C, `DERIVED` | Viola "classe C são quantis"; é transplante não validado. Classe **B** com sweep (§11) | estatístico |
| 19 | `meta_tau_grid_quantiles` `sweep_required: true` | **Autorizava buscar sobre a busca** — o que R5 dizia caracterizar falha. `false` (§11) | estatístico |
| 20 | `meta_tau_tie_epsilon = 1e-6` | Empate nunca ocorreria ⟹ regra vazia. Derivado do custo round-trip (§8.3) | estatístico |
| 21 | pass-through no cálculo do gate | Contamina; só paths com todos os folds `OK` contam (§9) | estatístico |
| 22 | A3 como braço sem poder | **Vira gate** — senão o desenho aprova um modelo sem bater "apertar `tau`" (§9) | estatístico |
| 23 | FLAG que imprime; escrita "condicionada" | **Mecanismo:** `AblationResult` obrigatório no writer; campo que o gate lê (§9) | estatístico |
| 24 | "refator puro = os testes passam" | Teste **`golden`** de igualdade bit-a-bit (§14.5) | estatístico |
| 25 | guarda anti-regressão por grep de string | Contraditória com §12; vira asserção de runtime falsificável (§4.7) | factual |
| 26 | regime ausente do treino ⟹ descartar coluna | Vira **nível de referência em silêncio**. `UNSEEN_REGIME` + veto (§6.4) | estatístico |
| 27 | sentinela `−1` só com regra de treino | 2 anos por símbolo; política de teste/produção declarada (§6.4) | estatístico |
| 28 | argumento do carimbo de data só contra o Grupo J | Aplicado também a regime — V de Cramér em E0 (§2.4) | estatístico |
| 29 | gate de HHI do DoD "de graça" | **Só passa quando D-01 falha.** Substituído por diagnóstico sem limiar (§7.5) | estatístico |
| 30 | `class_weight=None` | O Alpha faz **as duas** coisas; herdar o padrão (§7.2) | factual |
| 31 | E0 executável de imediato *e* exige Alpha novo | Contradição; E0-piloto vs. E0-vinculante (§1.3, §2.6) | factual |
| 32 | sem requisitos não-funcionais, rollback, versionamento, cadência, persistência | **5 seções novas** (§13, §14) — a última é a mais grave: nenhuma fase da v1 produzia modelo carregável | trade-offs |
| 33 | `fill_rate` "0,9665–0,9741, 9 caminhos" | **0,9665–0,9769, 10 caminhos** — e ia entrar em `constants.yaml` como `DERIVED` (§2.5) | factual |
| 34 | `AG-094` fecha simples | `AG-118` registrou a resolução oposta; §18 registra **reversão explícita** | factual |
| 35 | citações de linha imprecisas | `cpcv.py:495` (não `:496`); `weights.py:188-195`; `gate_efficiency.py:322`; `fill_simulator.py:851`; `build_hmm_regimes` em `:111`; sizing = `notional_req` | factual |
| 36 | "~1,89% das barras" | **~3,4%** — `target_signal_rate` é quantil por lado; a união é maior (§4.7) | factual |
| 37 | `[0.5, 2.0]` rotulado "±50%" | 2,0 é +100%; corrigido para `[0.5, 1.5]` (§11) | factual |
| 38 | Parkinson como estado | É **decisão** registrada; `constants.yaml:301` ainda `garman_klass_w20` (§1.1) | factual |
| 39 | orçamento de trials "antes de F4" | Tarde demais — E0 já teria consumido. **Antes de F1** (§11) | estatístico |
| 40 | `meta_include_nofill_in_training: DERIVED` | A derivação prova ΔPnL=0 de *prever fill*, não a política de treino. `ASSUMED`, sweep (§11) | estatístico |

**Veredito da auditoria sobre a v1:** §10 (enforcement B07/B08) aprovado e
independente; E0 aprovável após correções de texto; **F1–F6 exigiam
retrabalho estrutural**. Esta v2 é esse retrabalho.
