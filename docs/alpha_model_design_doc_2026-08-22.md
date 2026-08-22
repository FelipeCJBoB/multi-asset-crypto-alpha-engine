# Arquitetura Técnica — Alpha Multi-Ativo × Multi-Resolução (LightGBM) v3

**Status:** Fase 4 — desenho travado, **sem implementação** (escopo confirmado
pelo Manager, 2026-08-22). Nenhum arquivo de `src/` é tocado por este
documento; nenhum trial é consumido; o gate "Alpha não retreina até Data
Layer 100%" segue em vigor e bloqueando execução, não desenho.

**v2 (2026-08-22):** corrige 1 achado CRITICAL e 6 achados IMPORTANT/MODERATE
de uma auditoria adversarial independente (`/engineering:architecture`,
3 revisores paralelos — precisão de citação, ataque aos argumentos centrais,
lacunas de completude).

**v3 (2026-08-22):** corrige achados de uma revisão `project_assurance`
independente (PRINCE2 §6.4 — foco de INTEGRAÇÃO com a governança do
projeto, não qualidade técnica) e adiciona D-18 (GPU obrigatório, pedido do
Manager). Dois achados da v3 **não são fecháveis por este documento** —
exigem decisão do Manager entre textos de governança que já se contradizem
(§12) e confirmação formal de status de AG já pendente (§2.2/§10). Changelog
completo em §14.

**Pedido original:** "Alpha atual é um legado do motor antigo BTC only e
single time-frame M15, além de ser XGBoost. Desenhar a arquitetura técnica
ponta a ponta do Alpha multi-ativo, multi-timeframe R1/R2/R3, com LightGBM ou
CatBoost."

**Três decisões de escopo travadas com o Manager antes deste desenho:**

1. Só desenho (Fase 4) — mesmo padrão do Meta-model v3.
2. Learner = **LightGBM**, mantendo `PLANO_MESTRE_PRINCE2.md` §15.14
   (decisão já registrada, 2026-08-21) — não reaberto, CatBoost descartado.
3. Grão de treino = **modelos independentes por (símbolo, resolução)**, sem
   pooling cross-ativo em v1, com pooling registrado como via de evolução
   futura explicitamente condicionada a `AG-151` fechado (não escondida).

---

## §0 — Sumário executivo

**O achado central deste desenho não é onde esperávamos.** A pergunta trazia
implicitamente três frentes de trabalho — camada de dados/features para
multi-resolução, orquestração multi-ativo, migração de learner — mas a
auditoria de código mostrou que **duas das três já estão prontas em
produção**, uma delas fechada no dia de hoje:

| frente | status real | evidência |
|---|---|---|
| Multi-símbolo (5 ativos) | **já pronto** | `symbol` é parâmetro real em toda a cadeia dados→features→labels→`build_modeling_frame`; bug de symbol mismatch já achado e corrigido (`dataset.py:138-160`) |
| Multi-resolução R1/R2/R3 | **código já funciona**; status formal de `AG-100`/`AG-124` segue **aberto** (correção v3, §2.2) | `dataset.py:80-84` (`_BAR_SOURCE_BY_RESOLUTION`) mapeia as 3 grades e labels R1/R2/R3 já estão em disco para os 5 símbolos — mas `AG-100`/`AG-124` continuam com `status: "aberto"` no log real, e `SPRINT_LOG.md` registra pergunta não respondida ao Manager sobre o escopo do reprocessamento |
| Learner XGBoost→LightGBM | **não existe ainda** | isolado a `src/models/alpha.py` (construtor, extração de importância) e `src/models/persistence.py` (serialização do booster) |

Consequência: este desenho é **muito mais cirúrgico** do que "reconstruir o
Alpha do zero". O escopo real é: (a) trocar o learner, (b) estender a
orquestração de 1 loop (5 símbolos) para 2 eixos (5 símbolos × 3 resoluções =
15 combinações, função já aceita o parâmetro), e (c) corrigir débitos
estruturais de schema que a auditoria encontrou pelo caminho — dois já
catalogados (`AG-150` tau descartado, `AG-154` sem manifesto), dois novos de
código (`AG-157`/`AG-158`, §2.3/D-12) e dois novos de purge/orquestração
(`AG-159`/`AG-160`, §2.5/D-13).

**Achado mais sério, só depois de uma auditoria adversarial independente
(v2, §14):** a solução para `AG-150` (D-05) decide `tau_long`/`tau_short`,
mas o Meta-model v3 já trava o nome **literal** `tau_alpha` como
discriminador de artefato — como escritos, os dois documentos travados se
contradizem. Reconciliação proposta em §12, não aplicada nesta sessão.

---

## §1 — Contexto: o que este documento herda, e não reabre

- **`PLANO_MESTRE_PRINCE2.md` §15.14** (linhas 3065-3099, 2026-08-21): Manager
  já decidiu migrar o Alpha (Camada 1) de XGBoost para LightGBM. Motivo não
  detalhado no documento original (disciplina de proveniência — não inventar
  justificativa, §16.10). Represada, junto com o retreino, até o gate de
  Data Layer 100% abrir. **Este documento não reabre essa escolha** — o
  Manager confirmou LightGBM ao ser perguntado se o pedido atual ("LightGBM
  ou CatBoost") reabria `§15.14` ou a mantinha.
- **`AG-100`/`AG-124`** (2026-08-16 → trabalho de engenharia concluído
  2026-08-22, **status formal ainda "aberto"** — correção da v3, achado
  `project_assurance`): Manager confirmou R2/R3 como escopo de
  **produção** — revoga a citação obsoleta de `PRD_V4_1.md` ("R2/R3 são
  pesquisa, nunca alvo de produção") —, condicionado à recalibração causal
  do threshold dollar-bar. O trabalho de código aconteceu **no dia em que
  este documento foi escrito** (`dataset.py:70-79`: "15/15 células
  reprocessadas, validação item 22 positiva", commit `7924f2c`). **Mas a v2
  deste documento errou ao chamar isso de "fechado"** — `AG-100.status` e
  `AG-124.status` continuam `"aberto"` em `audit/architecture_gaps_log.
  yaml`, com texto não atualizado desde antes do commit que fez o trabalho;
  `AG-124` explicitamente diz que a trava formal "fica com o Manager
  confirmar por escrito quando conveniente" — ainda não confirmada;
  `docs/SPRINT_LOG.md` continua listando `AG-100` como pendência na tabela
  "Estado atual" mais recente, com uma pergunta **explicitamente não
  respondida** ao Manager: se o reprocessamento cobre só a camada de barra
  ou também features/regime/CPCV. **Este documento passa a tratar
  "multi-resolução pronta" como leitura de código correta, mas com fechamento
  formal pendente de confirmação do Manager** — não mais como fato
  encerrado. Se a resposta for "sim, cobre features/regime/CPCV também", a
  premissa central de §2.2 precisa ser revisitada.
- **`AG-042`** (2026-08-16, reafirmado 6× — `AG-004/005/017/027/031/037`):
  Manager já decidiu abandonar a nomenclatura wall-clock M15/M30/H1 em favor
  de `resolution_id` R1/R2/R3 (dollar bars), justamente porque "R1 ≈ 15m"
  provou ser uma equivalência operacionalmente enganosa. **"Multi-timeframe"
  neste documento significa R1/R2/R3, nunca M15/M30/H1 literal.** O cabeçalho
  do `CLAUDE.md` ("multi-timeframe M15/M30/H1") ficou desatualizado em
  relação a essa decisão — dívida de documentação registrada em §9, não
  corrigida aqui (fora do escopo deste desenho).
- **Gate "Alpha não retreina até Data Layer 100%"** (memória do projeto):
  segue em vigor. Nenhum dos 8 estágios (`01_BARRA`→`08_SPLIT`) está livre de
  gap conhecido hoje — ver §8.

---

## §2 — O que já está pronto (auditoria de código, não suposição)

### 2.1 Multi-símbolo

`symbol` é parâmetro real e testado em toda a cadeia:
`src/data/download.py::DEFAULT_SYMBOLS`, `src/data/lake.py::query_bars`,
`src/features/build.py::build_t1_features(symbol, ...)`,
`src/labels/triple_barrier.py` (todo `LabelConfig`/`build_labels_for_symbol`),
`src/models/dataset.py::build_modeling_frame(symbol, ...)`.

Labels já existem em disco para os 5 símbolos (`data/labels/{symbol}/...`).
Um bug real de symbol-mismatch já foi encontrado e corrigido uma vez
(`dataset.py:138-160`: `cpcv.load_labels_v1()` era chamado sem `symbol=`,
sempre carregando `BTCUSDT` independente do símbolo pedido — "features de
ETH, alvo de BTC", silenciosamente incoerente). Esse histórico é o motivo
direto de **D-03** (§3): a mesma classe de bug, em escala 15× maior
(5 símbolos × 3 resoluções), não pode continuar dependendo só de convenção de
nome/caminho.

### 2.2 Multi-resolução R1/R2/R3

Confirmado por leitura direta do código, não da documentação (a
documentação, como §2.3 mostra, está parcialmente desatualizada):

```python
# src/models/dataset.py:80-84
_BAR_SOURCE_BY_RESOLUTION: dict[str, str] = {
    "R1": "dollar_r1",
    "R2": "dollar_r2",
    "R3": "dollar_r3",
}
```

Este dict foi atualizado **hoje** (comentário `dataset.py:70-79`: "R2/R3
adicionados 2026-08-22 (AG-100, decisao_manager_2026-08-21)... condicionado à
recalibração CAUSAL do threshold dollar-bar (`AG-124`) ter fechado — fechou
2026-08-22"). `build_t1_features(symbol, start, end, bar_source=...)`
(`features/build.py:343-420`) já despacha para `dollar_r1/r2/r3` via
`_sources.load_bars`, reusando as mesmas 13 fórmulas de feature — o parâmetro
`bars_15m` do código interno é um nome legado, não uma restrição funcional
(confirmado pela docstring de `build_t1_features:359-364`, que documenta
exatamente essa fiação). `build_regimes` (`src/regime/build.py:26-99`)
propaga o mesmo `bar_source` para o mesmo despachante — regime também já
funciona sob R1/R2/R3 sem trabalho novo.

`registry.yaml` anota `tf: 15m` em toda feature — **isso é metadado de
proveniência histórica** (a nota no topo do arquivo, linhas 1-60, explica que
"15m" é a grade de cálculo original do vetor T1, resíduo do PRD), não um
gate de execução. O gate de execução real é `bar_source`, e esse já aceita
`dollar_r1/r2/r3`.

**Ressalva explícita, herdada, não nova:** sob `bar_source != "time_15m"`,
`build_t1_features` desliga deliberadamente `min_common_history_bars`
(`features/build.py:410-411`, `AG-030`) em vez de herdar silenciosamente uma
calibração pensada para 15m — decisão já tomada e documentada, não uma
lacuna deste desenho. E a comparabilidade calendário-a-calendário das 3
features `expanding` (C07/D03f/E02f) entre grades diferentes **não é
medida** — "trabalho novo de medição, não estipulado (B23)... registrado
como dívida (`AG-030`), não bloqueia esta fase" (docstring
`build.py:380-391`). Herdo essa mesma ressalva sem tentar resolvê-la aqui.

### 2.3 Achado novo: doc-drift em duas mensagens de erro

A leitura direta encontrou uma inconsistência textual real, criada pela
própria mudança de hoje: `dataset.py:176-179` (docstring) e
`dataset.py:201-206` (texto da `ValueError`) ainda dizem *"Só `'R1'` tem
`bar_source` mapeado hoje... R2/R3 continuam só pesquisa"* — mas o dict que
essas mesmas linhas descrevem (`:80-84`) **já mapeia R1, R2 e R3**. O espelho
exato do mesmo texto obsoleto existe em `src/models/pipeline.py:396-401`
("...R2/R3 são só pesquisa" — comentário sobre por que o gate largo não é
duplicado ali).

**Não é bug funcional** — o dict já libera R2/R3 corretamente; se
`resolution_id="R2"` for chamado hoje, funciona. É comentário/mensagem de
erro que, se disparada por um `resolution_id` fora do mapa (ex. `"R4"`),
citaria R2/R3 como "só pesquisa" de forma falsa. Baixa severidade, fix
trivial (só texto), registrado como `AG-157` (§9) — não corrigido aqui
porque o escopo desta sessão é só desenho, sem tocar `src/`.

### 2.4 O que falta de verdade

Três frentes, todas isoladas e pequenas comparadas ao que já existe:

1. **Learner** — `alpha.py` (construtor do modelo, extração de importância)
   e `persistence.py` (serialização do booster). §4-§6.
2. **Orquestração** — estender o loop de 1 eixo (5 símbolos) para 2 eixos
   (5 × 3 = 15 combinações). `pipeline.py::run_layer1_sprint` já aceita
   `resolution_id` e o CLI já expõe `--resolution-id` (`pipeline.py:315`,
   `:727-732`) — não é trabalho novo de assinatura, é trabalho de driver/loop.
   §7.
3. **Hardening de schema** — `symbol`/`resolution_id` como colunas
   explícitas, `tau` persistido (`AG-150`), manifesto de versão (`AG-154`).
   §5-§6.

### 2.5 Achado novo (v2): purge do CPCV medido em wall-clock, não em grade

A auditoria adversarial encontrou um furo real sob a afirmação "regime
também já funciona sob R1/R2/R3 sem trabalho novo" (§2.2) e sob D-10 ("CPCV:
reuso sem mudança"). O único caller de produção,
`run_layer1_sprint` (`pipeline.py:427`), calcula a janela de purge via
`features_build.compute_max_feature_lookback_ms(tf_effective)`, onde
`tf_effective` é **sempre** a grade wall-clock (`"15m"` por padrão) —
`resolution_id` nunca entra nessa chamada. `step_ms()`
(`src/data/resample.py:70-76`) nem aceita `"R1"/"R2"/"R3"` — levanta
`UnsupportedTimeframeError`. Ou seja: o componente de 96 barras de lookback
do purge (`AG-032`) é sempre medido em milissegundos de grade 15m, mesmo
quando o treino roda sob R2 (~30 min/barra) ou R3 (~1h/barra) — sob R3, a
janela real de 96 barras cobre ~4× mais tempo de relógio do que os
96×15min usados no cálculo, **sub-protegendo o purge especificamente para
R2/R3**.

Hoje isso está mascarado por um gate independente: `compute_max_feature_
lookback_ms` chama `assert_no_expanding_lookback_in_active_set` primeiro,
que sempre levanta `ExpandingFeatureLookbackError` porque as 3 features
`expanding` (C07/D03f/E02f) continuam ativas no vetor T1 — o mesmo bloqueio
de política já citado em §8 ("08_SPLIT... decisão de política pendente do
Manager"). **No dia em que esse gate for resolvido, o bug de unidade fica
ativo silenciosamente**, e é específico de R2/R3, não de R1 (onde
`tf_effective="15m"` coincidentemente bate com a grade real). Registrado
como `AG-159` (§9) — corrige a formulação de D-10 (não é mais "sem
mudança" sem ressalva).

---

## §3 — Decisões de desenho

| # | decisão | classe |
|---|---|---|
| D-01 | Learner = LightGBM | herdada, não reaberta |
| D-02 | Grão de treino = independente por (symbol, resolution_id) | travada com o Manager |
| D-03 | `symbol`/`resolution_id` como colunas explícitas do schema | nova |
| D-04 | `DESIGN_COLUMNS` continua sem regime | preservada do Alpha atual |
| D-05 | `tau` persistido (fecha `AG-150`) | nova, junto do retreino represado |
| D-06 | `predictions` ganha manifesto/versão (fecha `AG-154`) | nova |
| D-07 | `monotone_constraints`: reuso sem mudança | herdada |
| D-08 | Extração de importância: reescrita para API LightGBM | nova |
| D-09 | Calibração isotônica: sem mudança de arquitetura | herdada |
| D-10 | CPCV: reuso sem mudança | herdada, `AG-151` não bloqueia (por D-02) |
| D-11 | Hiperparâmetros LightGBM: conjunto único v1, `ASSUMED` até sweep | nova |
| D-12 | Persistência: formato texto + `model_dir` chaveado (fecha `AG-158`) | nova |
| D-13 | Orquestração: loop 15 combinações, sem mudança de assinatura | nova |
| D-14 | `N_lifetime`: multiplicador 15× declarado, não escondido | governança |
| D-15 | Contrato com Meta-model v3: preservado, com 1 nota de sincronismo | verificação |
| D-16 | Pooling cross-ativo: evolução futura, gated em `AG-151` | evolução |
| D-17 | Combinação de sinais R1/R2/R3 pelo Decision Engine | fora de escopo |
| D-18 | Treino em GPU obrigatório (`device_type="cuda"`), tensão com D-12 declarada | nova, pedido do Manager |

### D-01 — Learner = LightGBM

Confirmado com o Manager: mantém `§15.14`. Não avaliado CatBoost — reabrir
exigiria justificar tecnicamente por que reverteria uma decisão já
registrada, e não foi esse o caso.

### D-02 — Grão de treino = independente por (símbolo, resolução)

**Pesquisa feita a pedido do Manager antes de travar esta decisão** (AFML +
literatura recente), porque o argumento ingênuo — "mais dado é sempre
melhor" — não é a pergunta certa aqui.

**AFML (López de Prado), §8.5 "Parallelized vs. Stacked Feature
Importance"**: o próprio livro nomeia a técnica de agregar (`stack`) datasets
de múltiplos instrumentos e treinar um único modelo sobre todos
simultaneamente — com aviso explícito de que o dataset combinado precisa
ficar balanceado, senão o modelo vira enviesado para o instrumento mais
prevalente/volátil. É precedente direto do autor, não uma técnica importada
de fora do framework do projeto.

**Caso de uso recente (arXiv 2505.08180, previsão de volume intradiário em
ações, 2026).** Compara 3 esquemas com XGBoost (mesma família de árvore de
gradient boosting do LightGBM): modelo único por ativo (SAM, R²=0,532),
modelo por cluster de ativos correlacionados (CAM, R²=0,600), e **modelo
único treinado sobre o pool de todos os ativos** (UAM, R²=0,622) — ganho
real (+17% de R² relativo a SAM), atribuído a comunalidade genuína entre
ativos (fluxos de hedge/rebalanceamento que movem vários ativos ao mesmo
tempo). **O paper não discute vazamento, purge/embargo cross-ativo, nem
desbalanceamento entre ativos** — silêncio total no ponto que mais importa
para este projeto.

**Leitura combinada, e por que a decisão foi "independente agora, pooling
depois":** pooling tem upside real e medido para exatamente a família de
modelo escolhida (boosted trees) — mas **nenhuma das duas fontes valida que
seja seguro sem purge cross-ativo**. `AG-151` (aberto, `cpcv.py:259-292`)
documenta que `assign_time_groups` faz `linspace` **por símbolo**, então as
fronteiras de grupo do CPCV caem em datas diferentes por símbolo — sob
pooling, uma linha de treino de BTC pode ser exatamente contemporânea a uma
linha de teste de ETH (correlação medida 0,70-0,83, `AG-144`) sem proteção
nenhuma de purge. Nem sequer existe primitiva de purge por bloco arbitrário
em `cpcv.py` ainda (`AG-153`, só suporta pares).

**Decisão:** v1 treina 15 modelos independentes — um por (símbolo,
resolução) — mesmo grão que labels/predictions já usam hoje, evitando
`AG-151` **por construção**, não por sorte. Pooling entra como evolução
futura explícita (D-16), gated no fechamento de `AG-151`, não escondida como
"decisão implícita de v1".

### D-03 — `symbol`/`resolution_id` como colunas explícitas do schema

Hoje, `PREDICTIONS_SCHEMA_COLUMNS` (`alpha.py:501-519`, 17 colunas — ver
§5.2) não tem `symbol` nem qualquer eixo de grade; a identidade do
(símbolo, resolução) vive só na convenção de nome do `model_id`
(`f"{model_id}_side1_fold{split.split_id}_calibrator"`, `alpha.py:389-390`) e
no diretório onde o parquet é escrito. É exatamente a mesma classe de risco
do bug já corrigido em §2.1 (features de um ativo casadas com label de
outro) — só que agora multiplicada por 15 combinações em vez de 1.

**Verificação de compatibilidade com o Meta-model v3, feita antes de travar
esta decisão** (não presumida): `docs/meta_model_design_doc_2026-08-22.md`
§3.2 já lista `symbol` como coluna do **próprio** `meta_training_set`, com a
nota "parâmetro do pipeline (não é coluna de `labels`)" — ou seja, o Meta já
precisa de `symbol` e hoje o injeta manualmente a partir do contexto externo
do pipeline, porque nem `labels.parquet` nem `predictions.parquet` o
carregam nativamente. Adicionar `symbol`/`resolution_id` a
`predictions.parquet` **não quebra** esse contrato — deixa a etapa de
injeção manual do Meta redundante (removível depois, não obrigatória agora),
sem mudar nenhum valor.

**Decisão:** `symbol: Utf8` e `resolution_id: Utf8` entram como colunas
obrigatórias novas no schema de `predictions.parquet` (ver §5.2 para o schema
completo). `persistence.py::model_dir` passa a ser chaveado também por esses
dois campos (fecha `AG-158`, ver D-12).

### D-04 — `DESIGN_COLUMNS` continua sem regime

`DESIGN_COLUMNS = T1_FEATURE_IDS` (`alpha.py:68`) — regime saiu do vetor de
treino do Alpha em 2026-08-21 (`ADR-001` §2.7, ratificado pelo Manager,
comentário `alpha.py:57-67`). **Este desenho não reabre essa remoção.** O
Meta-model v3 depende estruturalmente dela: §2.2 do design doc do Meta chama
isso de "a vantagem informacional" — sem um input que o Alpha não tem, o Meta
não pode extrair informação nova (regressão infinita, argumento central de
por que o Meta existe). Reintroduzir regime como feature do Alpha
desmoronaria essa premissa e exigiria reabrir o Meta-model v3 inteiro — fora
do escopo deste documento, e sem motivo técnico levantado para tal.

Nenhuma feature nova entra no vetor de treino por causa da migração de
learner ou da expansão de resolução — `T1_FEATURE_IDS` (10 features) é
agnóstico a symbol/resolução por construção (fórmulas em contagem de barras,
não em unidade de calendário), e `resolution_id` não é ele próprio uma
feature (é chave de partição — cada um dos 15 modelos treina só na sua fatia,
`resolution_id` é constante dentro de um treino, não carrega informação).

### D-05 — `tau` persistido (fecha `AG-150`)

`SideModelResult.tau` (`alpha.py:298`, calculado como quantil da
probabilidade calibrada — `np.quantile(calibrated_train_all, 1.0 -
target_signal_rate)`, linha 267) é hoje calculado e **descartado** — não está
em `PREDICTIONS_SCHEMA_COLUMNS` nem em nenhum artefato de diagnóstico.
`AG-150` já recomendava sequenciar esse fix junto do retreino represado por
`§15.14` — é exatamente este documento.

**Consequência para o Meta-model v3:** o design doc do Meta (D-15, §3.4)
declara `p_alpha − tau` como feature bloqueada até `tau` existir no schema, e
nota explicitamente que popular essa coluna **exige retreinar** (não é
retrofit em artefato existente, §15.1 do doc do Meta: "D-15 sai do caminho de
20% e vai para E2"). Este documento **é** essa E2 — ver D-15 abaixo.

**Decisão:** duas colunas novas, `tau_long`/`tau_short` (não uma só —
`alpha.py:389-392` confirma dois calibradores por fold, um por lado, cada um
com seu próprio `tau`), tipo `Float64`, preenchidas no mesmo fold/lado em que
`tau` já é calculado hoje.

**CRITICAL, achado da auditoria adversarial (v2): esta decisão, como
travada em v1, contradiz o Meta-model v3.** `docs/meta_model_design_doc_
2026-08-22.md` §3.5 trava o nome **literal** `tau_alpha` como discriminador
de artefato — o leitor do Meta levanta `LegacyPredictionsError` quando essa
coluna exata não existe (linhas 374, 516, 541-546, 1707 do doc do Meta). Sob
esta decisão (duas colunas, `tau_long`/`tau_short`), **nenhum**
`predictions.parquet` gerado por este desenho teria uma coluna chamada
`tau_alpha` — todo artefato pós-migração LightGBM seria classificado como
"pré-D-15" e rejeitado **permanentemente**, não temporariamente. Os dois
documentos travados são inconsistentes um com o outro no único ponto em que
ambos citam o nome literal da coluna em disco.

**Reconciliação, análoga ao padrão que o próprio Meta v3 já usa:** o Meta já
deriva `p_alpha`/`score_alpha_raw` por seleção de lado (`p_long` se
`side_hat=+1`, `p_short` se `side_hat=-1`) em vez de exigir uma coluna
`p_alpha` física em `predictions.parquet` — o mesmo padrão resolve isso aqui:
`tau_alpha = tau_long if side_hat == 1 else tau_short`, calculado no
`meta_dataset.py::build_meta_signal_table` do Meta, não escrito pelo Alpha.
**Este documento mantém `tau_long`/`tau_short`** (schema fiel à estrutura
real de dois calibradores por lado, §3 D-05) — a correção correspondente
(`§3.5` do Meta v3 passar a derivar `tau_alpha` por seleção de lado, em vez
de exigir a coluna física) é um patch **no documento do Meta**, não neste. Não
aplicado aqui — fora do escopo desta sessão (Fase 4 do Alpha) — mas é
**bloqueante** para qualquer implementação: sem essa correção no Meta v3, a
inconsistência produz `LegacyPredictionsError` permanente em produção.
Registrado como item de ação em §13.

### D-06 — `predictions` ganha manifesto/versão (fecha `AG-154`)

`predictions.parquet` não tem `schema_version` nem manifesto — `AG-154`
documenta isso como bloqueio para qualquer mudança segura de schema (e este
documento propõe 4 colunas novas: `symbol`, `resolution_id`, `tau_long`,
`tau_short`). `src/io/artifact.py`/`src/io/schema.py` (a camada ADR-001,
`io/`) já implementam exatamente esse padrão — `artifact_dir` (`artifact.py:
168-181`) já trata `symbol`/`resolution` como segmentos de caminho de
primeira classe (`{stage}/config_hash={h}/symbol={S}/resolution={R}/`) — mas
`predictions.parquet` hoje usa um caminho ad-hoc próprio
(`predictions/alpha/{symbol}/{tf}/{model_id}/`, `_paths.py:42`), paralelo ao
writer versionado que já existe e não é usado ali (achado repetido de
`AG-154`, já registrado contra o Meta).

**Decisão:** migrar a escrita de `predictions.parquet` para o writer de
`io/artifact.py` (reuso, não nova infraestrutura) — resolve `AG-154` para o
Alpha e para o Meta ao mesmo tempo, já que o Meta consome exatamente este
artefato. `resolution_id` no schema (D-03) faz o papel do segmento
`{resolution}` que `artifact_dir` já espera — sem precisar inventar uma nova
convenção de path.

**IMPORTANT, lacuna corrigida na v2: compatibilidade retroativa.** A v1 não
tratou o que acontece com o que já existe. A auditoria confirmou por leitura
direta de disco: **existem 5 `predictions.parquet` reais hoje**, formato
legado de 17 colunas, caminho ad-hoc plano
(`predictions/alpha/{model_id}/predictions.parquet`) — incluindo
`alpha_c1_v1`, que corresponde a `MODEL_ID_CAMADA1`. Mais grave: 6 arquivos
foram citados na v2 como "módulos de produção que leem esse caminho legado,
hardcoded" — **correção v3 (`project_assurance` verificou os 6
individualmente; a v2 não tinha checado):** só **2 são leitores reais e
incondicionais** — `src/backtest/fill_reconciliation.py:127` (reconciliação
de backtest, categoria sensível B17) e
`src/analysis/calibration_diagnostics.py:910`. **1 é condicional**
(`src/analysis/faixa1_5_prerequisites.py:118` lê o caminho legado só como
*default*, tem parâmetro `dest_dir` de override). **3 foram citados por
engano** — não leem `predictions.parquet`: `src/validation/leakage.py:632`
é nota de prosa dentro de um teste estático sobre `alpha.py`, não sobre o
parquet; `src/analysis/attribution.py:184-192` só constrói uma string de
proveniência a partir de `model_id` já carregado, nunca toca disco;
`src/models/baselines.py:581` é docstring descrevendo shape de input, não
leitura real. **A decisão D-06 não muda** — os 2 consumidores reais (um
deles B17-sensível) já bastam para justificar o plano de compatibilidade —
mas a alegação "6 módulos" da v2 não se sustentava; é exatamente o tipo de
afirmação herdada sem checagem que `project_assurance` existe para pegar.
Um teste real e não-skipado quebra no momento em que
`PREDICTIONS_SCHEMA_COLUMNS` for de 17 para 21 colunas:
`tests/unit/test_models_alpha.py::test_predictions_parquet_real_schema_e_
invariantes:290-303` (`assert tuple(preds.columns) ==
alpha.PREDICTIONS_SCHEMA_COLUMNS` contra o parquet legado em disco).

**Decisão explícita (não presente na v1):** os 5 `predictions.parquet`
legados são artefatos reconstruíveis (`.gitignored`, não histórico de git) de
um Alpha que está sendo substituído por este próprio desenho — a mudança de
schema/caminho é **ato deliberado de regeneração**, não drift silencioso. A
migração real (quando o gate de Data Layer abrir) precisa, no mesmo PR que
ativa o retreino: (a) regenerar as 15 combinações sob o schema/caminho novo,
(b) atualizar os 6 consumidores acima para o caminho novo
(`predictions_symbol_tf_dir`/`io.artifact`, não o legado plano), (c)
descartar ou arquivar os 5 artefatos legados. Este documento não implementa
isso (Fase 4) — mas o deixa explícito como item de DoD, não como lacuna
implícita. Ver §13.

### D-07 — `monotone_constraints`: reuso sem mudança

`monotonic.screen_monotone_constraints` produz uma tupla `{-1,0,1}` por
feature, consumida hoje por `xgb.XGBClassifier(monotone_constraints=...)`
(`alpha.py:252`). LightGBM aceita a mesma convenção posicional
(`LGBMClassifier(monotone_constraints=[...])`) — nenhuma mudança em
`monotonic.py`. `PLANO_MESTRE_PRINCE2.md` §15.14 já registrava isso (correção
de citação da v2 — v1 atribuía a `CLAUDE.md`, que não tem numeração `§X.Y`
própria; a citação certa é a mesma seção já referenciada em §1 deste
documento): "`monotone_constraints` tem equivalente direto (mesmo nome de
parâmetro) — não precisa mudar."

### D-08 — Extração de importância: reescrita para API LightGBM

Hoje (`alpha.py:269-279`):

```python
booster = model.get_booster()
gain_by_fidx = booster.get_score(importance_type="total_gain")
gain_by_column = {
    DESIGN_COLUMNS[int(k[1:])]: float(v)
    for k, v in gain_by_fidx.items()
    if k.startswith("f")
}
```

Isso é inteiramente específico do XGBoost — o parsing de `"f0"`, `"f1"`, ...
não existe em nenhum outro learner. Sob LightGBM:

```python
booster = model.booster_
gains = booster.feature_importance(importance_type="gain")
names = booster.feature_name()
gain_by_column = dict(zip(names, (float(g) for g in gains), strict=True))
```

`hhi.compute_concentration`/`compute_effective_concentration` recebem
`dict[str, float]` e não mudam nada — confirmado agnóstico ao learner (Agente
1, leitura de `hhi.py`).

### D-09 — Calibração isotônica: sem mudança de arquitetura

`IsotonicRegression(out_of_bounds="clip", ...)` (`alpha.py:262-263`) treina
sobre `model.predict_proba(X_calib)[:, 1]` — `predict_proba` é interface
sklearn padrão, LightGBM's `LGBMClassifier` a implementa de forma idêntica.
Zero mudança na lógica de calibração, no holdout estratificado
(`_stratified_calib_split`), ou na seleção de `tau` a priori pelo orçamento
de fees (B20).

### D-10 — CPCV: reuso da lógica de split, com uma ressalva de unidade (v2)

`cpcv.generate_splits` não depende de learner. Sob D-02 (grão independente
por símbolo × resolução), cada um dos 15 treinos chama `generate_splits`
sobre seu próprio frame de labels — exatamente o padrão de hoje, repetido 15
vezes em vez de 5. `AG-151` (purge cross-símbolo ausente) **não bloqueia**
este desenho porque nenhum split cruza símbolo ou resolução.

**Correção da v2 — "sem mudança" era otimista demais.** A lógica de split em
si (`assign_time_groups`, `generate_splits`) não muda. Mas a **largura da
janela de purge** (`compute_max_feature_lookback_ms`) é hoje calculada
sempre em unidade wall-clock, mesmo sob R2/R3 — ver §2.5 (`AG-159`). Esse bug
está mascarado por outro gate hoje (features `expanding` bloqueando o
caminho inteiro), então não se manifesta nesta fase, mas precisa ser
corrigido **antes** do primeiro treino real sob R2/R3, não é herdado
"de graça" como a formulação da v1 sugeria.

### D-11 — Hiperparâmetros LightGBM: conjunto único v1, `ASSUMED` até sweep

`XGBHyperparams` (`alpha.py:74-96`) tem 7 campos, todos carregados de
`constants.yaml::alpha_xgb_*`: `max_depth`, `n_estimators`, `learning_rate`,
`subsample`, `colsample_bytree`, `min_child_weight`, `reg_lambda`. Mapeamento
para LightGBM (ver tabela completa em §4):

- **Renomeação direta** (mesmo conceito, nome/API diferente):
  `colsample_bytree`→`feature_fraction`, `reg_lambda`→`lambda_l2`,
  `max_depth`→`max_depth` (idêntico).
- **`min_child_weight` (soma de hessian) → `min_child_samples` (contagem de
  amostras) não é conversão direta.** São semânticas diferentes — herdar o
  valor numérico já tunado do XGBoost para o nome novo seria exatamente o
  tipo de erro de proveniência que a disciplina de `constants.yaml` existe
  para impedir (um número `MEASURED`/tunado sob uma definição migrando para
  `ASSUMED` sob outra, sem declarar isso). `alpha_lgbm_min_child_samples`
  entra como constante nova, `provenance: ASSUMED`, `class: B`,
  `sweep_required: true`.
- **`num_leaves` é hiperparâmetro novo**, sem equivalente no vetor XGBoost
  atual (regra prática: `num_leaves ≤ 2^max_depth`, mas não é derivação
  automática — precisa da própria entrada em `constants.yaml`, mesma
  disciplina).

**Decisão de escopo, não só de valor:** um único conjunto de hiperparâmetros
`alpha_lgbm_*` para as 15 combinações (símbolo, resolução) em v1 — não
particionado por resolução, mesmo padrão do XGBoost atual (um conjunto
global aplicado a todos os símbolos hoje). R1/R2/R3 têm densidade de barra e
estrutura de threshold genuinamente diferentes, então isso é um candidato
real de ablação futura — mas introduzir esse eixo de complexidade
simultaneamente com a troca de learner violaria §5.11 do `CLAUDE.md` ("pare
na primeira camada que atender o critério de parada... cada camada extra
custa `N_lifetime`"). Registrado como pergunta aberta para ablação, não
decidido por suposição — `TBD — medir` quando o Sprint de retreino acontecer.

**IMPORTANT, achado da auditoria adversarial (v2): o sweep futuro é um canal
de vazamento cross-símbolo que D-02 não fecha.** O argumento "`AG-151` não
bloqueia por construção" (D-02) só cobre pooling de **dados** — nenhum split
cruza símbolo. Mas se o sweep de hiperparâmetro futuro que decide o valor de
`alpha_lgbm_min_child_samples`/`num_leaves` avaliar desempenho agregado
através dos 5 símbolos × 3 resoluções simultaneamente antes de travar UM
valor global compartilhado pelos 15 modelos, isso é vazamento de informação
cross-símbolo por uma porta que não passa pelo CPCV nem pelos dados de
treino — a mesma classe de risco que motivou D-02 (correlação cross-ativo
0,70-0,83, `AG-144`), só que na seleção de hiperparâmetro em vez do pooling
de dados. **Não decidido nesta fase** (o sweep em si já é `TBD`) — mas a
metodologia do sweep, quando definida, precisa da mesma disciplina de
isolamento por símbolo que motivou D-02: ex. avaliar por símbolo e agregar
por estatística robusta (mediana), não por loss pooled. Registrado como
restrição de metodologia, não como decisão de valor.

**MODERATE, achado da auditoria (v2): tratamento de `NaN` não examinado.**
`E10f_oi_change_z_48` documenta NaN real de produção (pontos isolados de
`sum_open_interest == 0.0`, `_sources.py::load_oi_series_deduped:203-230`)
que sobrevive como `NaN` numérico (não `null` do Polars) através de rajadas
de ~48 barras — e `side_subset`/`_unique_test_bars` filtram só `.is_not_
null()`, que não captura `NaN`. XGBoost e LightGBM aprendem direção de split
default para valor faltante por mecanismos diferentes, com interação
diferente com `monotone_constraints` — não examinado nesta v1. Não bloqueia
o desenho (o comportamo atual sob XGBoost já convive com isso), mas precisa
entrar no DoD da implementação como item de verificação — ver §13.

**MODERATE, achado da auditoria (v2): `alpha_xgb_*` fica órfão.** Confirmado
por leitura direta — não há nenhum bundle XGBoost persistido em produção
hoje (`pipeline.py::run_layer1_sprint` nunca chama `persistence.write_
model_bundle`), então não há risco de perda de artefato. Mas D-01 trata a
migração como substituição direta — as 7 entradas `alpha_xgb_*` em
`constants.yaml` (`:1349-1404`) viram configuração morta, sinalizável pela
ferramenta mecânica `tools/lint/check_constants_referenced.py` já nomeada em
`CLAUDE.md`. Não declarado na v1 se são removidas ou mantidas com
justificativa — item de DoD, §13.

### D-12 — Persistência: formato texto + `model_dir` chaveado (fecha `AG-158`)

`src/models/persistence.py` é hoje **XGBoost-only por desenho deliberado**
(docstring própria, linhas 8-22: "a ÚNICA peça que muda quando a migração
LightGBM acontecer"):

- `_BOOSTER_NAME = "booster.ubj"`, `_BOOSTER_FORMAT = "xgboost_ubj_v1"`
  (`:92,101`) — formato binário XGBoost.
- `booster_to_save.save_raw(raw_format="ubj")` / `xgb.Booster().load_model(
  bytearray(...))` (`:314, :374-375`).
- `LoadedSideModel.predict_proba_calibrated` usa `xgb.DMatrix(x,
  feature_names=...)` (`:237-238`) — sem equivalente em LightGBM (que aceita
  array numpy puro em `predict`).

O calibrador (`IsotonicRegression` → `X_thresholds_`/`y_thresholds_` →
`np.interp`, `:192-255`) já é agnóstico ao learner — **sem mudança**.

**Mudança de formato:** `booster_.save_model(path)` (texto) ou
`booster_.model_to_string()` para bytes, com `lgb.Booster(model_str=...)`
para carregar — `_BOOSTER_NAME = "booster.txt"`,
`_BOOSTER_FORMAT = "lightgbm_txt_v1"`. Predição sob carga: array numpy direto
via `booster.predict(x)`, sem wrapper `DMatrix`.

**IMPORTANT, correção da v2: "mesmo padrão de teste, alvo diferente" era uma
suposição não verificada, não uma garantia herdada.** O teste atual
(`test_write_read_round_trip_reproduz_inferencia_bit_exata`) exige
igualdade bit-a-bit exata (`np.max(np.abs(...)) == 0.0`, não `pytest.
approx`). Isso funciona para XGBoost porque `.ubj` é formato binário que
preserva o padrão de bits IEEE754 exatamente. Duas diferenças reais de
mecanismo que a v1 não examinou: (a) serialização em **texto** depende de a
biblioteca formatar `double` com dígitos suficientes para round-trip exato —
não é garantia herdada do padrão binário `.ubj`; (b) LightGBM expõe um
parâmetro `deterministic` (**default `false`**) especificamente porque soma
de gradiente em histograma sob treino multi-thread não é bit-exata por
padrão (soma de ponto flutuante não é associativa sob paralelismo) — a
tabela §4 trata `n_jobs=-1`/`random_state=` como suficientes, mas para
LightGBM isso **não basta** pra garantia de reprodutibilidade bit-a-bit que
o resto do projeto trata como padrão (`golden` tests, B29).

**Decisão adicionada na v2:** `deterministic=True` entra como parâmetro
explícito do construtor `LGBMClassifier`, não opcional — com o trade-off de
performance de treino declarado (não medido nesta fase, `TBD`). Sem isso, o
teste de reload bit-exato equivalente (mesmo padrão, `tests/unit/test_
models_persistence.py`, alvo LightGBM) não tem garantia teórica de passar de
forma estável — precisa ser verificado na implementação, não assumido aqui.

**Achado novo (`AG-158`):** `model_dir` (`persistence.py:105-117`) particiona
só por `(model_id, fold_id, side, variant)` — **sem `symbol`/`resolution_id`
no caminho**, ao contrário de `_paths.py:42/68`
(`predictions_symbol_tf_dir`, `models_diagnostics_symbol_tf_dir`), que já
usam esse eixo. É a peça mais nova do pipeline (`AG-141`, construída na
mesma sessão que o Meta-model v3) e não segue a convenção que o resto do
projeto já estabeleceu. Sob 15 combinações, colisão de `model_dir` entre
(BTC, R1) e (ETH, R1) treinados com o mesmo `model_id` textual é um risco
real, não hipotético — a mesma classe de bug de §2.1, uma terceira vez.

**Decisão:** `model_dir` passa a incluir `symbol` e `resolution_id` como
segmentos de caminho, mesma convenção de `_paths.py`.

### D-13 — Orquestração: loop de 15 combinações

`run_layer1_sprint(symbol, resolution_id=None, ...)` (`pipeline.py:311-315`)
**já aceita `resolution_id`** — o CLI já expõe `--resolution-id`
(`pipeline.py:727-732`, flag adicionada na Fase 5 da migração; o parâmetro
da função em si é da Fase 4, `AG-030/036/065` — `pipeline.py:380`).
Nenhuma mudança de assinatura é necessária. O trabalho real é um driver fino
que chama essa função 15 vezes (5 símbolos × {R1, R2, R3}) — não uma
reescrita de orquestração.

**MODERATE, achado da auditoria adversarial (v2): `report_path` colide entre
as 15 chamadas.** `run_layer1_sprint`'s `report_path` (`pipeline.py:101-104,
321,756`) tem default **compartilhado** — `experiments/alpha_layer1_report.
json`, sem chave por `symbol`/`resolution_id`. Só é desviado se o caller
passar `--run-tag` explicitamente. `write_report_atomic` é atômico por
chamada (`.tmp → rename`), então cada uma das 15 chamadas **sobrescreve
inteiramente** o relatório da anterior — isso já acontece hoje mesmo em
execução puramente sequencial (não é um risco novo de paralelismo, é um bug
de sobrescrita existente que a expansão de 5 para 15 chamadas agrava). Os
artefatos científicos (predições, modelos) já são corretamente chaveados por
symbol/tf (`pipeline.py:500-509`) — só o relatório de experimento (metadado
de auditoria/sprint) tem esse problema. **Decisão adicionada na v2:** o
driver de D-13 passa `report_path`/`run_tag` únicos por combinação
(`{symbol}_{resolution_id}`), não usa o default compartilhado. Registrado
como `AG-160` (§9).

### D-14 — `N_lifetime`: multiplicador declarado

Nenhum trial roda nesta fase (desenho, não execução). Mas quando o gate abrir,
o custo real de `N_lifetime` é **15× o de hoje** (uma busca de hiperparâmetro
por combinação, se D-11 for revisto para per-resolução; 1× se o conjunto
único v1 for mantido). Declarado aqui para não ser descoberto como surpresa
no Sprint de retreino — mesma disciplina que o Meta-model v3 já aplicou
("orçamento de trials declarado antes de F1, não depois").

### D-15 — Contrato com o Meta-model v3: verificação ponto a ponto

Tabela de compatibilidade, verificada linha a linha contra
`docs/meta_model_design_doc_2026-08-22.md` (não presumida):

| dependência do Meta v3 | preservada? | nota |
|---|---|---|
| `score_alpha_raw` = `predict_proba(...)[:,1]` bruto por lado | **sim** | `LGBMClassifier.predict_proba` tem interface idêntica |
| `p_alpha` via `IsotonicRegression` por fold | **sim** | D-09, sem mudança |
| `DESIGN_COLUMNS` sem regime (vantagem informacional, §2.2 do Meta) | **sim** | D-04, não reaberto |
| `tau` persistido (D-15 do Meta, bloqueado até E2) | **existência sim; nome não** | D-05 — `tau_long`/`tau_short` ≠ `tau_alpha` travado no Meta v3 §3.5; reconciliação pendente, ver D-05 |
| 2 `calibrator_id` por fold (um por lado) | **sim** | estrutura de `run_fold` não muda, só o `model`/`booster` interno |
| `is_oof` via `train_idx`/`test_idx` do CPCV | **sim** | D-10, CPCV não muda |
| `symbol` como coluna (§3.2 do Meta) | **melhora, não quebra** | hoje injetado manualmente pelo Meta a partir do contexto do pipeline; D-03 deixa isso redundante, não obrigatório |
| `PREDICTIONS_SCHEMA_COLUMNS` (17 colunas) | **estende, não remove** | +4 colunas (`symbol`, `resolution_id`, `tau_long`, `tau_short`) |

**Nota de sincronismo para o Meta-model v3 (não resolvida aqui, registrada
para quando o doc do Meta for revisitado):** o §15.2 do Meta v3 descreve seu
próprio pré-requisito E2 como "Retreino do Alpha **em R1**" — singular. Este
documento cobre R1, R2 **e** R3 (escopo de produção confirmado pelo Manager
em `AG-100`/`AG-124`, ainda que o status formal desses dois AGs continue
`"aberto"` — ver §2.2). O Meta v3 precisa decidir, quando chegar a hora, se
processa as 3 resoluções (replicando seu próprio D-02 equivalente) ou
continua restrito a R1 — decisão do Meta, não deste documento.
**Achado `project_assurance` (v3, `AG-164`):** o Meta v3, como documento,
não tem NENHUMA menção a `resolution_id` como coluna de `meta_training_set`
nem como parâmetro de leitura de artefato em nenhuma seção — `grep
"resolution_id"` no documento inteiro (1948 linhas) retorna 1 ocorrência, de
passagem, em §1.1. `io.artifact.artifact_dir` (que D-06 deste documento
propõe como writer) exige `resolution` como keyword-argument obrigatório,
sem default — quem implementar `build_meta_signal_table` (F1 do Meta) não
tem orientação escrita sobre este eixo. Risco mecânico baixo hoje (a
assinatura força escolha explícita, sem glob), mas é acidente de API bem
desenhada, não contrato declarado. Registrado como `AG-164` (§9).

### D-16 — Pooling cross-ativo: evolução futura, gated em `AG-151`

Não faz parte do v1 (D-02). Registrado explicitamente como via de evolução,
não como possibilidade vaga: quando `AG-151` fechar (unificar `edges_ms` via
união dos `t0` dos 5 símbolos, em vez do `linspace` per-símbolo atual) **e**
`AG-153` fechar (primitiva de purge por bloco arbitrário), um modelo único
com pool cross-ativo — ou cross-resolução — vira uma opção real, com
justificativa empírica já citada (§ D-02: ganho de R² medido em literatura
recente para exatamente esta família de modelo). Até lá, permanece fora do
caminho crítico.

### D-17 — Fora de escopo: combinação de sinais R1/R2/R3 pelo Decision Engine

Este documento cobre o contrato de treino e inferência do Alpha por
(símbolo, resolução) — não decide como o Decision Engine consome/combina os
3 sinais de resolução por símbolo em uma decisão de trade única (ex.: R1
para timing de entrada, R3 para confirmação de regime, ou as 3 como features
paralelas de um Meta/Decision Engine mais acima). É decisão de arquitetura do
Decision Engine, respeitando a hierarquia de camadas do projeto
(`models ↛ execution`) — referenciada aqui, não resolvida.

### D-18 — Treino em GPU obrigatório (adicionado na v3, pedido direto do Manager)

Pedido do Manager: "garanta que Alpha e Meta vai usar GPU". Para o Alpha,
sem ambiguidade — D-01 já trava LightGBM incondicionalmente, então GPU é
parâmetro de construtor, não decisão de learner.

**Decisão:** `LGBMClassifier(..., device_type="cuda", ...)` — CUDA
preferido sobre o backend `"gpu"` (OpenCL, mais antigo, portável a AMD/
Intel) por desempenho, condicionado a hardware NVIDIA disponível no
ambiente de treino (`TBD` — não verificado nesta sessão, decisão de
desenho, não de infraestrutura confirmada).

**Três ressalvas, declaradas explicitamente em vez de silenciadas (mesma
disciplina de "nunca silencie" do projeto):**

1. **Pré-requisito de build não resolvido aqui.** O wheel padrão de
   `lightgbm` via PyPI não inclui suporte GPU habilitado — exige instalação
   com flag de build GPU/CUDA (`--config-settings` ou equivalente) ou build
   a partir do source com toolkit CUDA instalado. O projeto usa `uv` (B27,
   pip/conda proibidos) — o mecanismo exato de obter um wheel GPU-enabled
   via `uv` não foi verificado nesta sessão. Item de infraestrutura, não de
   arquitetura — registrado como pré-requisito de implementação, `TBD`.
2. **Tensão real com D-12 (determinismo bit-exato de reload).** A garantia
   documentada de `deterministic=True` no LightGBM é mais forte para CPU;
   treino em GPU historicamente não tem a mesma garantia de reprodução
   bit-a-bit entre execuções (ordem de redução de ponto flutuante em
   histograma paralelo em GPU não é a mesma disciplina que a soma
   determinística de CPU). **Não resolvido aqui** — duas saídas possíveis
   para a implementação decidir: (a) treinar em GPU mas validar/re-derivar
   o teste de reload bit-exato especificamente em CPU; (b) trocar o teste
   de igualdade bit-a-bit por tolerância numérica pequena sob GPU,
   documentando a mudança de garantia. `deterministic=True` continua
   declarado (D-12) independente de qual saída for escolhida — reduz, não
   elimina, o risco.
3. **Ganho de desempenho não medido, não presumido (B23).** O histórico de
   BTC a R1/15m tem ~230.784 barras (nota de `registry.yaml`, período
   2020-01-01 a 2026-07-31) — dataset de porte moderado, 10 features T1.
   Aceleração de GPU em gradient boosting tende a compensar mais em
   datasets maiores/com mais features; com árvores rasas e poucas colunas,
   overhead de transferência de dado pode parcialmente compensar o ganho de
   paralelismo. `TBD — medir` no Sprint de retreino, não presumido como
   vitória automática — a decisão é do Manager (GPU obrigatório), a medição
   de payoff é separada e vem depois.

---

## §4 — Migração XGBoost → LightGBM: tabela de API completa

| XGBoost (`alpha.py` hoje) | LightGBM | nota |
|---|---|---|
| `xgb.XGBClassifier(objective="binary:logistic", ...)` (`:243-258`) | `lgb.LGBMClassifier(objective="binary", ...)` | |
| `monotone_constraints=(...)` tupla | `monotone_constraints=[...]` lista | mesma convenção posicional, sem mudança em `monotonic.py` (D-07) |
| `scale_pos_weight=` | `scale_pos_weight=` | idêntico, sem mudança de cálculo |
| `colsample_bytree=hyper.colsample_bytree` | `feature_fraction=` | renomeação direta (§15.14 já citava) |
| `reg_lambda=hyper.reg_lambda` | `lambda_l2=` | renomeação direta |
| `min_child_weight=hyper.min_child_weight` (soma de hessian) | `min_child_samples=` (contagem) | **não é conversão numérica direta** — nova entrada `ASSUMED` (D-11) |
| `max_depth=hyper.max_depth` | `max_depth=` | idêntico |
| — (não existe) | `num_leaves=` | hiperparâmetro novo, entrada `ASSUMED` própria (D-11) |
| `tree_method="hist"` | (histograma é o default) | parâmetro removido, não portado |
| `n_estimators=`, `learning_rate=`, `subsample=` | mesmos nomes | idênticos |
| `random_state=`, `n_jobs=-1` | mesmos nomes | idênticos |
| `model.get_booster()` (`:269`) | `model.booster_` | atributo, não método |
| `booster.get_score(importance_type="total_gain")` → `dict{"fN": v}` (`:274`) | `booster_.feature_importance(importance_type="gain")` + `booster_.feature_name()` → arrays paralelos | remap reescrito (D-08); `hhi.py` recebe o mesmo `dict[str,float]`, sem mudança |
| `xgb.DMatrix(x, feature_names=...)` + `booster.predict(dmatrix)` (`persistence.py:237-238`) | `booster.predict(x)` (array numpy direto) | sem wrapper equivalente necessário |
| `.save_raw(raw_format="ubj")` / `xgb.Booster().load_model(bytearray(...))` (`persistence.py:314,374-375`) | `booster_.save_model(path)` / `lgb.Booster(model_str=...)` | formato binário → texto; `_BOOSTER_FORMAT` novo (D-12) |
| `IsotonicRegression` (calibração) | **sem mudança** | D-09 |
| `model.predict_proba(X)[:, 1]` | **sem mudança** (mesma interface sklearn) | |

---

## §5 — Schema de dados

### 5.1 `PREDICTIONS_SCHEMA_COLUMNS` — antes/depois

Hoje (`alpha.py:501-519`, 17 colunas): `t0, p_long, p_short,
score_long_raw, score_short_raw, side_hat, confidence, ensemble_std,
n_models_agree, model_id, calibrator_id, feature_version,
features_selecionadas, hhi_importancia, wf_window_id, fold_id, is_oof`.

**Depois (21 colunas — 17 + 4 novas):**

| coluna nova | tipo | origem | decisão |
|---|---|---|---|
| `symbol` | `Utf8` | parâmetro de `run_fold`, propagado do pipeline | D-03 |
| `resolution_id` | `Utf8` | parâmetro de `run_fold`, `None`→`"time_15m"` legado ou `"R1"/"R2"/"R3"` | D-03 |
| `tau_long` | `Float64` | `SideModelResult.tau` do lado long | D-05 |
| `tau_short` | `Float64` | `SideModelResult.tau` do lado short | D-05 |

### 5.2 Manifesto (fecha `AG-154`)

Migração da escrita de `predictions.parquet` para o writer de
`io/artifact.py`/`io/schema.py` (D-06) — `schema_version` explícito,
`config_hash` já suportado pela camada ADR-001, `symbol`/`resolution` como
segmentos de `artifact_dir` (já implementado, reuso, não nova infra).

---

## §6 — Persistência de modelo (fecha `AG-158`)

`persistence.py::model_dir` passa de `(model_id, fold_id, side, variant)`
para `(symbol, resolution_id, model_id, fold_id, side, variant)` — mesma
convenção que `_paths.py` já usa para predictions/diagnostics. Serialização:
ver D-12 e tabela §4.

---

## §7 — Arquitetura técnica ponta a ponta

```
para (symbol, resolution_id) em 5 símbolos × {R1, R2, R3}:        [15 combinações, D-02/D-13]

  ds.build_modeling_frame(symbol, resolution_id=resolution_id)     [§2.1/§2.2 -- já pronto]
      -> labels ⋈ 10 features T1 ⋈ regime (bar_source já resolvido
         por _BAR_SOURCE_BY_RESOLUTION, dataset.py:80-84)

  cpcv.generate_splits(mf.data, symbol=symbol)                     [D-10 -- sem mudança]
      -> 15 splits CPCV, purge+embargo dentro do símbolo/resolução

  alpha.run_all_folds(df_all, splits, variant=...)                 [D-01/D-07/D-08/D-09]
      para cada split, cada lado (long/short):
        fit_side_model:  LGBMClassifier (D-01)
                          monotone_constraints reusado (D-07)
                          IsotonicRegression reusado (D-09)
                          tau calculado E persistido (D-05)
                          importância via booster_.feature_importance (D-08)
        -> SideModelResult com tau, calibrador, hhi

  predictions (schema estendido, D-03/D-05, §5.1)
      symbol, resolution_id, tau_long, tau_short + 17 colunas hoje

  persistence.write_model_bundle                                   [D-12]
      model_dir chaveado por (symbol, resolution_id, ...)

  io.artifact — manifesto/versão                                   [D-06]
```

Camadas tocadas: `models` (`alpha.py`, `dataset.py` sem mudança de
assinatura, `pipeline.py` driver), `io` (reuso). Nenhuma mudança em
`features/`, `regime/`, `labels/`, `validation/cpcv.py` — confirmado por
D-04/D-07/D-09/D-10. Hierarquia de camadas (`models ↛ execution`) preservada.

---

## §8 — Pré-requisitos bloqueantes

**Gate do Manager, confirmado ainda em vigor:** Alpha não retreina até
Data Layer 100%. Nenhum dos 8 estágios (`01_BARRA`→`08_SPLIT`) está livre de
gap conhecido hoje — `01_BARRA` (`AG-138`), `03_FEATURES`/`07b_PESOS`
(`AG-139`), `07_LABEL` (`AG-140`), `08_SPLIT` (features `expanding` quebram
`leakage.py` sem bypass manual, decisão de política pendente do Manager).
Este documento não desbloqueia esse gate — é o desenho que roda **quando**
ele abrir, não uma justificativa para abri-lo antes.

Nada neste documento depende de `AG-151` (D-02 evita por construção) nem de
`AG-153` (só relevante para D-16, evolução futura).

---

## §9 — Governança: achados a registrar (proposto, não aplicado nesta sessão)

Escopo desta sessão é só desenho — os itens abaixo são **candidatos** a
registro em `audit/architecture_gaps_log.yaml`, não aplicados aqui. Próximos
números livres confirmados: `AG-157`..`AG-164`.

| id proposto | achado | severidade |
|---|---|---|
| `AG-157` | `dataset.py:176-179,201-206` e `pipeline.py:396-401` — texto de docstring/`ValueError` diz "R2/R3 são só pesquisa", desatualizado em relação a `_BAR_SOURCE_BY_RESOLUTION` (`:80-84`), que já mapeia as 3 grades desde hoje (`AG-100`/`AG-124`). Não é bug funcional — R2/R3 já funcionam; é mensagem enganosa se disparada por um `resolution_id` inválido. | baixa |
| `AG-158` | `persistence.py::model_dir` (`:105-117`) não chaveia por `symbol`/`resolution_id`, inconsistente com `_paths.py` — risco real de colisão sob as 15 combinações deste desenho (D-12 fecha). | média |
| `AG-159` | `pipeline.py:427` mede a janela de purge do CPCV sempre em wall-clock (`tf_effective`), nunca em `resolution_id` — sub-protege o purge sob R2/R3 quando o gate de features `expanding` (§8) for resolvido. Mascarado hoje por esse mesmo gate independente (§2.5). | média |
| `AG-160` | `pipeline.py`'s `report_path` default (`experiments/alpha_layer1_report.json`) não é chaveado por symbol/resolution — as 15 chamadas de D-13 se sobrescrevem sequencialmente sem `--run-tag` explícito (bug existente, agravado 15×, §D-13). | baixa-média |
| `AG-161` | **achado `project_assurance`, v3.** Este documento estava não commitado e não referenciado por nenhum outro artefato do repo (`grep -r "alpha_model_design_doc"` fora do próprio arquivo: zero hits) — sem âncora de governança (nenhum `PLANO_MESTRE §15.20` equivalente ao `§15.19` do Meta, nenhuma linha em `SPRINT_LOG.md`). Risco de perda silenciosa, incluindo o achado CRITICAL de `AG-162`. | média |
| `AG-162` | **achado `project_assurance`, v3, CRITICAL.** `tau_alpha` (1 coluna, derivada por seleção de lado) já travado em `PLANO_MESTRE §15.19-F` e no campo `status` de `AG-150` — D-05 deste documento diverge dos 3 (decide `tau_long`/`tau_short`, 2 colunas cruas), não só do Meta v3 como a v2 pensava. Não fechável por revisão — ver §12. | critical |
| `AG-163` | **achado `project_assurance`, v3.** Este documento (v2) citou `AG-100`/`AG-124` como "fechados" 3×; ambos continuam `status: "aberto"` no log real, e `SPRINT_LOG.md` tem pergunta não respondida ao Manager sobre escopo do reprocessamento (features/regime/CPCV incluídos ou não). Corrigido em §2.2/§1 desta v3. | high |
| `AG-164` | **achado `project_assurance`, v3.** `docs/meta_model_design_doc_2026-08-22.md` não menciona `resolution_id` como coluna/parâmetro em nenhuma seção de sequência (F0-F9) — `io.artifact.artifact_dir` exige `resolution` obrigatório, sem orientação escrita para quem implementar F1 do Meta. | média |

Referenciados, não reabertos: `AG-150` (fecha via D-05 — **mas ver `AG-162`,
D-05 diverge do que `AG-150` já recomendava**), `AG-151` (permanece aberto,
gateia D-16), `AG-154` (fecha via D-06, com plano de compatibilidade
retroativa — §13), `AG-155` (cadência de retreino — aplica-se ao Alpha tanto
quanto ao Meta, segue sem decisão do Manager).

---

## §10 — Referências

- `PLANO_MESTRE_PRINCE2.md` §15.14 (decisão LightGBM, 2026-08-21), §0.2
  (R1-R5), §11.4 (Road Map Vivo).
- `audit/architecture_gaps_log.yaml`: `AG-042` (R1/R2/R3 vs. M15/M30/H1),
  `AG-100`/`AG-124` (R2/R3 produção, fechado 2026-08-22), `AG-030`
  (comparabilidade cross-grade das features `expanding`, não medida),
  `AG-138/139/140` (Data Layer, gate aberto), `AG-141` (persistência,
  `persistence.py`), `AG-144` (correlação cross-ativo 0,70-0,83), `AG-150`,
  `AG-151`, `AG-153`, `AG-154`, `AG-155`, `AG-159`, `AG-160` (novos, v2).
- `docs/meta_model_design_doc_2026-08-22.md` §2.2 (vantagem informacional),
  §3.2 (schema, `symbol` como coluna), §3.4 (D-15, `tau` bloqueado até E2),
  §3.5 (nome literal `tau_alpha`, discriminador de `LegacyPredictionsError`),
  §15.1-15.2 (sequência, E2).
- López de Prado, M. — *Advances in Financial Machine Learning* (2018),
  §8.5 "Parallelized vs. Stacked Feature Importance".
- "Forecasting Intraday Volume in Equity Markets with Machine Learning",
  arXiv:2505.08180 (2026) — SAM/CAM/UAM, R² 0,532→0,600→0,622 sob XGBoost.

---

## §11 — Definition of Done: testes afetados (adicionado na v2)

A v1 não tinha esta seção — lacuna real apontada pela auditoria (o resto do
documento é detalhista com número de linha exato para achados bem menores).
Lista concreta do que muda na suíte de testes quando a implementação
acontecer — não decidida/resolvida aqui, só declarada:

| arquivo | impacto | ação |
|---|---|---|
| `tests/unit/test_models_persistence.py` | **reescrita substancial** — a fixture `_fit_real_side_model()` (todos os 11 testes) constrói `xgb.XGBClassifier`/`xgb.Booster` diretamente; `booster.predict(xgb.DMatrix(x))` (D-12) e `booster.feature_names is None` (`AG-146`) são API específica do XGBoost | reescrever fixture + asserções para LightGBM |
| `tests/golden/test_sprint8_reproducibility.py` | **baseline fica inválido** — compara `hhi`/`gain_by_column`/`n_trees` bit-a-bit contra `models/{id}/diagnostics/*.json` versionado no git; determinismo bit-exato do XGBoost não se transfere automaticamente (D-12) | commitar novo baseline "Fase A" sob LightGBM |
| `tests/unit/test_models_persistence.py::test_read_model_bundle_formato_de_booster_desconhecido_levanta_erro` | corrompe deliberadamente o manifest trocando `"xgboost_ubj_v1"` por `"lightgbm_txt_v1"` como exemplo de "versão futura desconhecida" — pós-migração isso é o formato **real** | inverter/reescrever a premissa do teste |
| `tests/unit/test_models_alpha.py` | `XGBHyperparams.from_constants()` chamado em ≥4 testes como classe nomeada — D-11 não decide se a classe é renomeada | decidir rename vs. manter nome genérico na implementação |
| `tests/unit/test_models_alpha.py::test_predictions_parquet_real_schema_e_invariantes` | quebra contra os 5 `predictions.parquet` legados em disco quando o schema for de 17→21 colunas (D-03/D-05) | regenerar artefatos, ver D-06/§13 |

---

## §12 — `tau_alpha`: não é um patch de 2 documentos, é 3 — escalado ao Manager (correção v3)

A v2 tratou isto como CRITICAL mas de escopo simples: um patch pontual no
Meta v3, trocando a exigência de coluna física `tau_alpha` por derivação em
`meta_dataset.py` (`tau_alpha = tau_long if side_hat == 1 else tau_short`,
mesmo padrão de seleção por lado que o Meta já usa para `p_alpha`/
`score_alpha_raw`). **A revisão `project_assurance` (v3) achou que isso é
menos simples do que parecia: o texto "`tau_alpha`, 1 coluna" já está
travado em MAIS DOIS lugares que a v2 não viu:**

1. `PLANO_MESTRE_PRINCE2.md` §15.19-F (o documento canônico, não o design
   doc do Meta): *"1. `tau_alpha` no schema de predições (`AG-150`) — 1
   coluna."*
2. O campo `status` da própria entrada `AG-150` (`audit/architecture_gaps_
   log.yaml`, aberta, nunca editada desde a criação): *"fix recomendado:
   coluna `tau_alpha` (Float64) ... preenchida com o tau do lado
   efetivamente sinalizado (`side_hat`)"*.

**Os dois textos de governança já existentes descrevem uma coluna ÚNICA
derivada por seleção de lado — estruturalmente mais próxima da correção que
esta v3 propõe para o Meta do que da decisão que D-05 realmente trava
(`tau_long`/`tau_short`, 2 colunas cruas, sem seleção).** Ou seja: não é
"Alpha decide 2 colunas, Meta espera 1 coluna diferente" — é "3 artefatos de
governança já diziam 1 coluna, e D-05 diverge dos 3 sem ter visto isso".

**Não fechável por este documento.** Corrigir só o Meta v3 (como a v2
planejava) deixaria `PLANO_MESTRE §15.19-F` e o texto de `AG-150`
desatualizados e mutuamente inconsistentes com a implementação real —
qualquer um dos três lido isoladamente por um implementador futuro leva a
um schema diferente do que D-05 realmente decide hoje. **Escalado ao
Manager (`PLANO_MESTRE §6.5`, `AG-162`):** qual dos dois desenhos vale —
D-05 (`tau_long`/`tau_short` crus, schema mais fiel à estrutura real de dois
calibradores por fold) ou o já registrado em `AG-150`/`§15.19-F` (`tau_alpha`
único, derivado) — precisa ser decidido uma vez e propagado aos 3 lugares no
mesmo commit. Este documento não escolhe por conta própria.

---

## §13 — Próximos passos (não decididos aqui, dependem do Manager)

1. **`AG-162` (CRITICAL, escalado, §12):** decidir entre D-05
   (`tau_long`/`tau_short`) e o já registrado em `AG-150`/`§15.19-F`
   (`tau_alpha` único, derivado) — propagar a mesma escolha aos 3 lugares
   no mesmo commit.
2. **`AG-163` (HIGH, escalado, §2.2):** confirmar por escrito o fechamento
   formal de `AG-124`; atualizar `AG-100.status` para `"fechado"`
   referenciando o commit `7924f2c`; responder a pergunta pendente em
   `SPRINT_LOG.md` sobre se o reprocessamento cobre features/regime/CPCV.
3. **`AG-161` (governança, §9):** commitar este documento + criar
   `PLANO_MESTRE_PRINCE2.md §15.20` (mesmo padrão de `§15.19`) + linha
   "Alpha multi-ativo" na tabela "Estado atual" de `SPRINT_LOG.md` — a menos
   que o Manager prefira manter como rascunho até mais decisões fecharem.
4. Confirmar se os achados de §9 (`AG-157`..`AG-164`) devem ser registrados
   em `audit/architecture_gaps_log.yaml` agora ou só quando a implementação
   começar.
5. Aplicar (ou não) o patch de `AG-164` (`resolution_id` no Meta v3) —
   decisão separada, documento diferente.
6. Decisão do Manager pendente, não deste documento: cadência de retreino
   (`AG-155`) — afeta Alpha e Meta igualmente, segue sem resposta.
7. Pré-requisito de infraestrutura não verificado (D-18): confirmar
   ambiente com GPU/CUDA disponível para treino, e decidir mecanismo de
   instalação de LightGBM GPU-enabled via `uv`.

---

## §14 — Changelog v1 → v2

Correções da auditoria adversarial independente (3 revisores paralelos —
precisão de citação, ataque aos argumentos centrais, lacunas de
completude), ranqueadas por severidade:

| # | sev. | v1 | v2 | § |
|---|---|---|---|---|
| 1 | **CRITICAL** | D-05 decidia `tau_long`/`tau_short` sem checar contra o nome que o Meta v3 trava | Meta v3 §3.5 exige literalmente `tau_alpha`, senão `LegacyPredictionsError` **permanente**. Reconciliação: Meta deriva por seleção de lado (padrão já usado para `p_alpha`), não Alpha renomeia. Patch pendente no Meta v3, não aplicado aqui | D-05, §12 |
| 2 | HIGH | D-06 ("migrar pra `io/artifact.py`") sem tratar o que já existe | 5 `predictions.parquet` reais em disco, 6+ consumidores hardcoded no caminho legado (`fill_reconciliation.py` inclusive, B17), 1 teste real quebra no schema novo. Decisão explícita: regeneração deliberada, não drift | D-06, §11 |
| 3 | HIGH | Nenhuma seção de DoD/testes | `test_models_persistence.py` (reescrita substancial), `test_sprint8_reproducibility.py` (baseline golden inválido), `XGBHyperparams` (rename não decidido) | §11 (nova) |
| 4 | IMPORTANT | D-10 "CPCV: reuso sem mudança" | Purge medido sempre em wall-clock (`pipeline.py:427`), sub-protege R2/R3 quando o gate de features `expanding` abrir — mascarado hoje, não "de graça" | D-10, §2.5, `AG-159` |
| 5 | IMPORTANT | D-11 "conjunto único, `AG-151` não bloqueia" | O sweep futuro (não os dados) é canal de vazamento cross-símbolo se avaliado pooled antes de travar um valor global — `AG-151`/D-02 só cobrem o lado de dados | D-11 |
| 6 | IMPORTANT | D-12 "mesmo padrão de teste, alvo diferente" | Suposição não verificada — LightGBM não é bit-exato por padrão (`deterministic=False` default); `deterministic=True` entra como decisão explícita | D-12 |
| 7 | MODERATE | D-13 "driver fino, sem mudança de orquestração" | `report_path` default compartilhado entre as 15 chamadas — sobrescrita silencial existente, agravada 15×; driver precisa `report_path`/`run_tag` únicos | D-13, `AG-160` |
| 8 | MODERADO | D-11 não examinava NaN nem `alpha_xgb_*` órfão | NaN real comprovadamente atravessa `.is_not_null()` hoje (`E10f`); `alpha_xgb_*` vira config morta pós-migração (sem risco de artefato perdido — confirmado, nenhum bundle XGBoost persistido em produção) | D-11 |
| 9 | factual | D-07 citava `CLAUDE.md §15.14` | Seção não existe em `CLAUDE.md` (que não tem numeração própria) — é `PLANO_MESTRE_PRINCE2.md` §15.14, mesma citada em §1 do próprio documento | D-07 |
| 10 | factual | D-13 atribuía "Fase 4 anterior" ao flag da CLI | `pipeline.py:731` diz Fase 5 para o flag; Fase 4 é do parâmetro da função (`pipeline.py:380`) | D-13 |

**Confirmado correto pela auditoria, não alterado:** ~40 citações de linha
verificadas (§2.2/§2.3, `alpha.py` inteiro, `persistence.py` inteiro,
`pipeline.py`, `_paths.py`, `io/artifact.py`, cross-check contra
`meta_model_design_doc_2026-08-22.md`) — quase todas exatas (**exceção:
a lista de "6 módulos consumidores" do item 2 acima não foi verificada
individualmente pela v2 e continha 3 citações erradas — corrigido na v3,
§14.1 abaixo**). O argumento central "`symbol` não quebra o contrato do
Meta v3" (D-03) **sobrevive** ao ataque adversarial sem ressalva — só o de
`tau` (D-05) tinha furo. O dispatch de features/regime para R1/R2/R3 (§2.2)
também sobrevive linha a linha — o furo estava um nível abaixo, na largura
de purge (D-10), não no dispatch em si.

---

## §14.1 — Changelog v2 → v3

Correções de uma revisão `project_assurance` independente (PRINCE2 §6.4 —
foco de INTEGRAÇÃO com a governança do projeto, não qualidade técnica), mais
D-18 (GPU, pedido direto do Manager):

| # | sev. | v2 | v3 | § |
|---|---|---|---|---|
| 1 | **CRITICAL** | D-05/§12 tratava `tau_alpha` como patch de 1 documento (só o Meta v3) | O nome/formato "`tau_alpha`, 1 coluna derivada" já está travado em MAIS DOIS artefatos que a v2 não viu (`PLANO_MESTRE §15.19-F`, campo `status` de `AG-150`) — ambos mais próximos da correção proposta do que da decisão real de D-05. Não fechável por este documento — escalado ao Manager | §12, `AG-162` |
| 2 | HIGH | §0/§1/§2.2/§10 declaravam `AG-100`/`AG-124` "fechados" | Ambos continuam `status: "aberto"` no log real; `SPRINT_LOG.md` tem pergunta não respondida ao Manager sobre escopo do reprocessamento (features/regime/CPCV inclusos?). Corrigido para "trabalho de código feito, fechamento formal pendente" | §1, §2.2, `AG-163` |
| 3 | MODERADO | D-06 citava "6 módulos de produção" consumindo o caminho legado | Só 2 são leitores reais incondicionais, 1 é condicional, 3 foram citados por engano (não leem `predictions.parquet`). Decisão D-06 não muda (os 2 reais bastam) — mas a alegação "todas as citações exatas" da v2 não se sustentava para este cluster | D-06 |
| 4 | MODERADO | Nenhuma menção a `resolution_id` no Meta v3 | Meta v3 (1948 linhas) tem 1 ocorrência de passagem de `resolution_id`, nunca como coluna/parâmetro declarado — `artifact_dir` exige `resolution` obrigatório sem orientação escrita para F1 do Meta | D-15, `AG-164` |
| 5 | governança | Documento não commitado, sem âncora em `PLANO_MESTRE`/`SPRINT_LOG` | Registrado como risco real de perda silenciosa (incluindo o próprio achado `AG-162`) — ação em §13 | `AG-161` |
| 6 | nova decisão | — | D-18: GPU obrigatório para treino (pedido do Manager), com 3 ressalvas declaradas — pré-requisito de build via `uv` não verificado, tensão real com D-12 (determinismo), payoff não medido | D-18 |

**Confirmado pela `project_assurance`, não alterado:** a decisão D-02
(grão independente por símbolo×resolução) e a P1 do Meta v3 (purge
cross-símbolo bloqueante) convergem de forma coerente, apesar de escritas em
documentos diferentes sem coordenação explícita. `AG-141` genuinamente não
integrado (`write_model_bundle` nunca chamado) — confirmado de novo,
independente. Os 5 `predictions.parquet` legados e o teste que quebra
(`test_predictions_parquet_real_schema_e_invariantes`) existem exatamente
como descrito.
