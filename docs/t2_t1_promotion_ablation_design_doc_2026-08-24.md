# Design doc — arquitetura de engenharia da promoção T2→T1 (Alpha, LightGBM)

Status: **PROPOSTA, não implementada.** Produzido via skill
`engineering:system-design`, a pedido explícito do Manager
(2026-08-24): "Aprovado pode seguir para promoção T2 > T1, desenhar
essa arquitetura de engenharia... não é só plug-play, lightGBM precisa
ter os hiperparametros para treinar da melhor forma."

Âncora histórica: `PRD_V3_2_UNIFICADO.md` §2.0.1/§2.13 (metodologia
esqueleto da ablação k=6,9,12,16,24; regra de promoção só via ablação
dentro do CPCV; regra de ortogonalidade |Spearman|>0,70). CLAUDE.md R4
("teto de features = medido, nunca estipulado") é a restrição de
governança que torna esta ablação obrigatória, não opcional.

---

## 1. Requisitos

**Funcional**
- Testar k ∈ {6, 9, 12, 16, 24} features T2 (ordenadas por importância),
  cada k com hiperparâmetros LightGBM otimizados PARA aquele k — não um
  hiperparâmetro fixo herdado do vetor de 7 features atual.
- Medir Sharpe OOS e PBO por k, dentro do CPCV real (`src/validation/
  cpcv.py`), não num holdout simples.
- Escolher o maior k com PBO < 0,30, sujeito a: (a) parar se Sharpe OOS
  não crescer monotonicamente até k=6 ("não é número de features, é
  ausência de sinal", §2.0.1); (b) nenhum par no T1 final com
  |Spearman| > 0,70.
- `T1_FEATURE_IDS := k` escolhido — mudança de 1 linha em
  `src/features/build.py`, mas só DEPOIS da ablação completa.

**Não funcional**
- Todo trial real (retreino/backtest novo) incrementa
  `audit/n_lifetime.yaml` — orçamento declarado a priori, não
  descoberto durante a execução.
- Determinismo: mesma seed → mesmo resultado bit-a-bit (já é invariante
  do treino atual, `deterministic=True`/`force_row_wise=True`,
  `src/models/alpha.py:357,367`).
- Núcleo funcional / casca imperativa (CLAUDE.md) — a função que
  calcula "Sharpe/PBO de um FoldResult" tem que ser pura, testável sem
  IO.

**Restrições**
- Nenhum literal numérico novo fora de `constants.yaml`; toda constante
  nova com `provenance` declarada.
- Layer hierarchy (`CLAUDE.md`): `models/` não importa `execution/`;
  só `models/`, `validation/`, `backtest/`, `analysis/` leem `labels/`;
  `analysis/` é "medição pós-hoc, nunca insumo de treino/seleção de
  feature" — **restrição que descarta `src/analysis/` como lar do
  harness** (ver §3).
- Claude não executa `.py`/`pytest`/`uv run` — implementação (quando
  aprovada) segue o protocolo de execução de sempre.

---

## 2. Achado crítico — isto NÃO é plug-and-play em dois níveis, não um

O pedido do Manager já assumia que hiperparâmetro fixo por k seria
ingênuo. Lendo `src/models/alpha.py` linha a linha, o problema é mais
profundo: **o conjunto de features está hardcoded em 3 pontos dentro do
caminho de treino, não é parâmetro em lugar nenhum.**

```
fit_side_model()                                    [alpha.py:236]
  ├─ monotonic.screen_monotone_constraints(
  │      train_side_df, T1_FEATURE_IDS, ...)         [linha 272-277]  ← constante do módulo
  ├─ build_design_matrix(train_side_df)               [linha 286]
  │      └─ df.select(DESIGN_COLUMNS)                 [DESIGN_COLUMNS = T1_FEATURE_IDS, linha 81]
  └─ model.fit(..., feature_name=list(DESIGN_COLUMNS)) [linha 380]
```

Nenhuma das 3 referências a `T1_FEATURE_IDS`/`DESIGN_COLUMNS` é
parâmetro de `fit_side_model`, `run_fold` ou `run_all_folds` — só
`hyper: LGBMHyperparams` é injetável hoje (`run_all_folds`,
`alpha.py:632`). Testar k≠7 exigiria reatribuir os globais do módulo
por trial (frágil, não é thread-safe, descartado) ou — a correção certa
— adicionar um parâmetro `feature_ids: tuple[str, ...] = T1_FEATURE_IDS`
que se propaga pelas 3 chamadas acima, com default preservando bit-exato
todo call site existente. É o mesmo padrão aditivo já usado 6× nesta
sessão (`unforce_features_by_side`, `device_type`, `bar_source`,
`extra_feature_ids`, `load_taker_imbalance_1m`,
`load_futures_positioning`) — não é invenção de padrão novo, é aplicar
o padrão já validado do repo.

**Segundo achado, dentro do mesmo arquivo de constantes**
(`config/constants.yaml:1858`, `alpha_lgbm_max_depth`): a proveniência
do `max_depth=3` documenta explicitamente que `num_leaves` foi calibrado
como `2^max_depth=8` **"exatamente pra emular o teto que max_depth
sozinho dava no XGBoost"** — os dois hiperparâmetros têm uma relação
de acoplamento já registrada, não são eixos independentes. Isso importa
DIRETO pro desenho da busca: `alpha_lgbm_num_leaves` já tem
`sweep_required: true, sweep_range: [4, 64]` (`constants.yaml:1921-1927`)
— mas varrer `num_leaves` até 64 com `max_depth` travado em 3 recria
exatamente o problema que a calibração `num_leaves ≤ 2^max_depth` existe
pra evitar (`num_leaves=64` sob `max_depth=3` volta a tornar `max_depth`
inefetivo, mesmo comportamento do default de biblioteca 31 que o D-11
já rejeitou por este motivo). **Conclusão de desenho: `max_depth` entra
no espaço de busca junto com `num_leaves`, não fica de fora — e o
sampler precisa respeitar `num_leaves ≤ 2^max_depth` como restrição do
trial, não como dois eixos livres.**

---

## 3. Onde o harness mora — achado de camada

`CLAUDE.md`, Layer hierarchy: `analysis/` "fica fora do contrato
`importlinter` de propósito — é medição pós-hoc, **nunca pode virar
insumo de treino/seleção de feature**." Mas o resultado desta ablação
(qual k, quais hiperparâmetros) É, por definição, insumo de seleção de
feature — vira `T1_FEATURE_IDS` de produção. Colocar o harness em
`src/analysis/` (onde os passes de pesquisa anteriores — E2/E3,
`n_lifetime.yaml` ids 11/13 — viveram) violaria essa regra por
construção, mesmo sem o `importlinter` acusar (a regra é de propósito
declarado, não só de import).

`src/validation/` já lê `labels/`, já é o lar de `cpcv.py`/`dsr.py`, e
sua função declarada é medir qualidade de modelo dentro do CPCV — sem a
ressalva "nunca insumo de seleção". **Recomendação: o harness mora em
`src/validation/t2_t1_ablation.py`**, importando `models/alpha.py` (
`validation` fica downstream de `models` na hierarquia, import permitido)
e `validation/cpcv.py`. `analysis/` fica só como consumidor read-only do
artefato de resultado (ex. um script de plotting/relatório), nunca como
onde a decisão é calculada.

---

## 4. Desenho de alto nível

```
                    ┌─────────────────────────────────────────┐
                    │  Passo 0 — ranking + ortogonalidade      │
                    │  (1 trial, precedente ids 11/13)         │
                    │  stability_screen(T2 pool) → T2 ordenado │
                    │  + filtro guloso |Spearman| ≤ 0,70       │
                    └───────────────────┬───────────────────────┘
                                        │ lista ordenada de 62 candidatas
                    ┌───────────────────▼───────────────────────┐
                    │  Passo 1 — para cada k ∈ {6,9,12,16,24}:  │
                    │    Optuna TPE sobre (max_depth, num_leaves│
                    │    com num_leaves≤2^max_depth,             │
                    │    min_child_samples, subsample_freq)     │
                    │    objetivo = Sharpe OOS agregado do CPCV │
                    │    N_trials_k declarado a priori           │
                    └───────────────────┬───────────────────────┘
                                        │ FoldResults por trial (path_id)
                    ┌───────────────────▼───────────────────────┐
                    │  Passo 2 — PBO/CSCV (NOVO, não existe)     │
                    │  reusa os n_backtest_paths do CPCV como    │
                    │  substrato CSCV; agrega Sharpe por caminho │
                    │  → PBO(k)                                  │
                    └───────────────────┬───────────────────────┘
                                        │
                    ┌───────────────────▼───────────────────────┐
                    │  Passo 3 — seleção: maior k, PBO<0,30,     │
                    │  monotonicidade até k=6 (senão aborta)     │
                    └─────────────────────────────────────────────┘
```

Camadas tocadas: `features/` (nenhuma mudança — T2 já computado),
`models/alpha.py` (extensão aditiva `feature_ids`), `validation/`
(harness novo + PBO novo), `models/stability.py` (reuso do Passo 0).
Nenhuma mudança em `execution/`, `risk/`, `regime/`.

---

## 5. Deep dive

### 5.1 Passo 0 — ranking de importância + ortogonalidade

Reusa `src.models.stability.stability_screen` (Camada 2, já
implementada e usada em produção de pesquisa — precedente direto:
`n_lifetime.yaml` id 13, "Nenhum modelo retreinado... contado como 1
trial"). Aplicar aos 62 T2 candidatos: mesma métrica
`estabilidade = força × consistência²` já em uso, mesmo filtro guloso
de ortogonalidade incremental já usado no id 11 (`hhi_efetivo/
n_eff_factors`). **Custo: 1 trial** (mesma contagem do precedente —
passe de ranking, não retreino por feature).

Saída: lista ordenada + máscara de exclusão por par correlacionado
(|Spearman| > 0,70) — top-k desta lista, já filtrada, é o que cada
variante de k usa.

### 5.2 Extensão mínima de `alpha.py`

```python
def fit_side_model(..., feature_ids: tuple[str, ...] = T1_FEATURE_IDS):
    ic_results = monotonic.screen_monotone_constraints(
        train_side_df, feature_ids, side=side, ...)
    X_all = build_design_matrix(train_side_df, feature_ids=feature_ids)
    ...
    model.fit(..., feature_name=list(feature_ids))

def build_design_matrix(df, feature_ids: tuple[str, ...] = T1_FEATURE_IDS):
    return df.select(feature_ids).to_numpy().astype(np.float64)
```

`run_fold`/`run_all_folds` ganham o mesmo parâmetro, repassado sem
alteração. Default preserva todo call site de produção
(`run_layer1_sprint`) bit-exato — mesma disciplina de
`device_type`/`unforce_features_by_side`. **Este é código de produção
mínimo que precisa existir ANTES do harness rodar** — não é o harness
em si, é pré-requisito de plumbing.

`build_modeling_frame` já expõe `extra_feature_ids` (`dataset.py:145`),
mas seu próprio guard (`dataset.py:303-309`) REJEITA overlap com
`T1_FEATURE_IDS` por design — ele nunca foi pensado como mecanismo de
treino, só de coluna auxiliar pós-hoc. O harness monta `mf.data` com
`extra_feature_ids=<candidatas T2 do k atual>` (uso LEGÍTIMO do
parâmetro — features T2 não fazem parte de `T1_FEATURE_IDS`, então o
guard não dispara) e passa o `feature_ids` explícito pro
`fit_side_model` estendido apontar pro subconjunto certo dentro de
`mf.data`.

### 5.3 Busca de hiperparâmetro — aninhada, não conjunta

**Decisão: para cada k, um estudo Optuna independente** (não uma busca
conjunta única sobre k×hiperparâmetro). Ver §7 para o trade-off
completo — resumo: k tem uma regra de seleção própria já definida pelo
PRD (maior k com PBO<0,30) que precisa de um Sharpe/PBO "limpo" por k;
misturar k no mesmo espaço de busca do Optuna borra o que PBO está
medindo (overfitting de CONFIGURAÇÃO vs. escolha de TAMANHO de vetor
são perguntas estruturalmente diferentes).

Espaço de busca por k (Optuna TPE, `optuna.create_study`):
- `max_depth` — NOVO no espaço de busca (não tinha `sweep_required`
  antes; entra aqui porque acopla com `num_leaves`, ver §2). Faixa
  proposta: `TBD — Manager declara `sweep_range` em constants.yaml
  antes da Fase 5.13 rodar (mesma disciplina de toda constante classe
  B/A — não invento aqui).
- `num_leaves` — já `sweep_range: [4, 64]`, mas amostrado
  CONDICIONALMENTE: `num_leaves ≤ 2^max_depth` do mesmo trial
  (constraint, não dois eixos livres).
- `min_child_samples` — já `sweep_range: [10, 100]`.
- `subsample_freq` — já `sweep_range: [1, 10]`.
- `n_estimators`, `learning_rate`, `subsample`, `feature_fraction`,
  `lambda_l2` — **fora do espaço de busca nesta rodada** (todos
  `sweep_required: false`, sem evidência de acoplamento com k; incluir
  sem justificativa medida seria scope creep sobre o que o projeto já
  decidiu não varrer ainda — se o Passo 1 mostrar sinal de que algum
  destes importa, isso vira achado NOVO pro Manager decidir, não
  decisão unilateral do harness).

Objetivo do Optuna: Sharpe OOS agregado (pooled sobre os
`n_backtest_paths` do CPCV, mesma métrica `directional_sharpe` já usada
em `decomposition.py`) — **não PBO**. PBO precisa comparar MUITOS
trials entre si (é uma estatística sobre a distribuição de ranks OOS
entre configurações, não um sinal por-trial que o Optuna consiga
otimizar de forma sã com poucas dezenas de trials); usar Sharpe como
alvo do sampler e computar PBO como AVALIAÇÃO PÓS-HOC do conjunto de
trials já rodados é a separação certa (ver §5.4).

### 5.4 PBO — não existe, precisa ser construído do zero

`src/validation/dsr.py:8` (docstring, texto literal): **"DSR/PSR/PBO
ainda não implementados"** — confirmado, não é suposição. `src/
validation/__init__.py` registra a mesma lacuna. Nenhuma implementação
de Probability of Backtest Overfitting (Bailey et al. 2014, CSCV)
existe em `src/`.

**Achado que reduz o risco desta lacuna**: `cpcv.py` já produz
`n_backtest_paths` via 1-fatoração round-robin (`§3` da docstring do
módulo, φ=5 caminhos completos que cobrem os 6 grupos cronológicos) —
essa é EXATAMENTE a estrutura combinatória que o método CSCV de Bailey
usa como substrato (particiona em blocos, reconstrói caminhos OOS,
mede degradação de rank in-sample→out-of-sample). `FoldResult.path_id`
(`alpha.py:440`) já rastreia isso por resultado. PBO não precisa de um
novo splitter — precisa de uma função de AGREGAÇÃO pura sobre
`list[FoldResult]` já produzidos: por caminho, ordena as configurações
testadas por Sharpe IS, pega a que rankeou melhor IS, mede se o rank
dela OOS caiu abaixo da mediana → fração de caminhos onde isso acontece
é o PBO. Núcleo funcional puro (recebe `list[FoldResult]` +
`list[trial_configs]`, devolve `float`), zero IO — inclusive já seguindo
o princípio "núcleo funcional / casca imperativa" do CLAUDE.md sem
esforço extra.

**Local proposto**: `src/validation/pbo.py`, núcleo puro +
`src/validation/t2_t1_ablation.py` como casca que chama Optuna + PBO +
grava artefato.

### 5.5 Artefato de saída

Convenção já estabelecida (`experiments/*.json`, ids 10/11/13/16 do
ledger): `experiments/t2_t1_ablation_{symbol}_{resolution_id}.json`
com, por k: lista de trials (hiperparâmetros, Sharpe OOS, seed),
melhor trial, PBO(k), decisão final (k escolhido + motivo, ou "abortado
por não-monotonicidade" com o k onde quebrou).

---

## 6. Orçamento de N_lifetime e faseamento

`audit/n_lifetime.yaml::counter = 96` hoje (não é mais gate vinculante
desde AG-077, mas DSR/`src/validation/dsr.py` lê o contador de
verdade — continua sendo custo real, não cosmético).

**Estimativa de escala, ANTES de comprometer**: 5 valores de k × N
trials Optuna por k. Se `N_trials_per_k` ficar em 15-25 (faixa razoável
pra TPE em espaço de 3-4 dimensões, não é medido, é heurística de
literatura de Optuna — declarar isso honestamente), e isso rodar nos 5
símbolos × 3 resoluções (15 combinações, mesma escala do retreino real
de 2026-08-23, id 18) → **até 5 × 20 × 15 ≈ 1.500 trials**. Isso é
15x o `counter` atual — desproporcional pra validar um MÉTODO que ainda
não foi testado nem uma vez.

**Recomendação de faseamento (staged, não big-bang):**

1. **Fase A — 1 ativo/resolução de referência** (proponho BTCUSDT/R1 —
   maior histórico, maior liquidez, já é a base de todo o PRD
   histórico). Roda o Passo 0 + Passo 1 (5 k × N trials) + Passo 2/3
   completos SÓ nesta combinação. Custo: `5 × N_trials_per_k`, delta
   real no ledger quando rodar (não estimado aqui — `N_trials_per_k`
   ainda é TBD, decisão do Manager antes da Fase 5).
2. **Checkpoint de decisão**: o k* escolhido e os hiperparâmetros
   vencedores em BTCUSDT/R1 generalizam pros outros 14 pares
   símbolo×resolução, ou cada um precisa da própria ablação? Isto é
   medido no checkpoint (comparando k*/hiperparâmetros ótimos contra
   uma reamostra rápida nos outros ativos), não assumido a priori —
   evita multiplicar por 15 um método ainda não validado.
3. **Fase B** (só se o checkpoint mostrar necessidade real): estende
   pros demais 14 pares, com o `N_trials_per_k` recalibrado pelo que a
   Fase A já ensinou (provavelmente menor, se a Fase A convergir rápido).

Cada fase gera 1 entrada no ledger, granularidade "após o fato" (mesmo
padrão do id 18 — "15 combinações" registrado como um delta só, não 15
entradas), com o `delta` real medido, não estimado.

---

## 7. Trade-offs

| decisão | opção escolhida | alternativa descartada | por quê |
|---|---|---|---|
| k×hiperparâmetro | busca ANINHADA (hiperparâmetro dentro de cada k) | busca CONJUNTA (1 espaço k+hiperparâmetro) | PBO mede overfitting de configuração; k tem regra de seleção própria do PRD (maior k, PBO<0,30) que precisa de um sinal por-k limpo. Conjunta borra as duas perguntas em uma, mais difícil de interpretar E de orçar a priori. |
| sampler | Optuna TPE | grid search sobre os 3 ranges já declarados | Optuna é o stack nominalmente exigido (`CLAUDE.md`) nunca usado de verdade — esta é a primeira vez que vale a pena fechar essa dívida; grid sobre 4 dims (com max_depth incluído) explode rápido, TPE é mais eficiente em amostra. |
| escopo inicial | 1 ativo de referência (Fase A) | matriz completa 5×3 de uma vez | `counter` atual (96) não comporta 1.500 trials pra validar um método nunca testado; staged respeita "meça antes de afirmar". |
| onde mora o harness | `src/validation/t2_t1_ablation.py` | `src/analysis/` (onde passes de pesquisa anteriores viveram) | `analysis/` é explicitamente "nunca insumo de seleção de feature" no CLAUDE.md — este harness É insumo de seleção, colocá-lo lá violaria a regra de propósito mesmo sem o importlinter acusar. |
| alvo do Optuna | Sharpe OOS pooled | PBO diretamente | PBO precisa de população de trials pra ser calculado (estatística sobre ranks), não é gradiente-amigável trial-a-trial com poucas dezenas de amostras. |
| onde computar PBO | novo `validation/pbo.py`, núcleo puro sobre `FoldResult`+`path_id` já existentes | novo splitter CSCV do zero | `cpcv.py` já produz a estrutura combinatória (`n_backtest_paths`) que CSCV precisa — reusar evita duplicar purge/embargo, que já é validado e testado. |

---

## 8. Pronto vs. precisa ser construído

| item | status |
|---|---|
| `T1_FEATURE_IDS`/pipeline dinamicamente dimensionado (auditoria anterior desta sessão) | ✅ pronto |
| `hyper: LGBMHyperparams` injetável em `run_all_folds` | ✅ pronto |
| CPCV real (purge/embargo/paths) | ✅ pronto |
| `feature_ids` parametrizável em `fit_side_model`/`build_design_matrix`/`run_fold`/`run_all_folds` | ✅ pronto (2026-08-24) — 9 referências hardcoded corrigidas (7 em `fit_side_model`, incluindo HHI/HHI-efetivo que o esboço original do §5.2 não previa; mais `_unique_test_bars` — achado de correção, não só plumbing, filtro de warmup tinha que usar as MESMAS `feature_ids` do trial — e a coluna `features_selecionadas` de `predictions.parquet`). Testes em `tests/unit/test_models_alpha.py`. Default preserva bit-exato todo call site de produção |
| Espaço de busca `max_depth` em `constants.yaml` (`sweep_range` declarado) | ❌ Manager declara antes da Fase 5.13 |
| Wiring Optuna (nunca usado no repo real) | ❌ construir |
| PBO/CSCV (`src/validation/pbo.py`) | ❌ construir do zero (`dsr.py:8` confirma lacuna) |
| Reuso de `stability_screen` pro ranking T2 (Passo 0) | ✅ pronto, só precisa ser chamado sobre os 62 candidatos |
| Artefato `experiments/t2_t1_ablation_*.json` | ❌ construir (schema segue convenção existente) |

---

## 9. Decisões pendentes do Manager antes da implementação

### 9.1/9.2 — resolvidas por decisão (2026-08-24)

3. **Ativo de referência da Fase A: ETHUSDT/R1** (decisão do Manager,
   substitui a proposta original BTCUSDT/R1 deste doc).
4. **Sequenciamento aprovado**: extensão de `feature_ids` em
   `alpha.py` (§5.2) roda como unidade de trabalho separada, ANTES do
   harness/PBO. **Concluída em 2026-08-24** — ver §8. Próxima unidade:
   `src/validation/pbo.py` + `src/validation/t2_t1_ablation.py` (harness
   + grade do Optuna `GridSampler` de §9.2), ainda não iniciada.

### 9.1 — `N_trials_per_k` — pesquisa aplicada (persona ML engineer)

Pesquisa dedicada (Optuna/TPE docs oficiais, LightGBM Parameters
Tuning oficial, López de Prado 2018 "A Practical Solution to the
Multiple-Testing Crisis" lido na íntegra, Bailey & López de Prado 2014
DSR) — relatório completo arquivado nesta sessão. **Achados centrais:**

- **Optuna oficial não tem regra publicada** ligando nº de trials a
  dimensões do espaço — verificado por fetch direto da FAQ e de uma
  discussão aberta no GitHub (`optuna/optuna#5668`, sem resposta desde
  set/2024). Gap real de documentação, não omissão da pesquisa.
- **Único piso numérico oficial encontrado**: BigQuery ML docs (Google
  Cloud) — "at least 10 trials per hyperparameter" → **≥ 40 trials**
  para as 4 dimensões do sweep (`max_depth`, `num_leaves`,
  `min_child_samples`, `subsample_freq`). Tratado como PISO, não ótimo.
- **`TPESampler.n_startup_trials=10`** (default oficial) — com budget
  pequeno (15-25), a maior parte do orçamento seria sorteio aleatório
  puro, não busca guiada — argumento contra os valores baixos citados
  na minha proposta original deste doc.
- **A própria documentação do Optuna recomenda `GridSampler` (não TPE)
  quando o espaço é pequeno e discreto o bastante para cobertura
  exaustiva** — relevante porque, com a restrição `num_leaves ≤
  2^max_depth`, o espaço real É pequeno e discreto se `max_depth` ficar
  numa faixa estreita (ver 9.2).
- **López de Prado (2018), citação direta, FAQ #5 do paper**: *"there
  is no reason to limit the 'number of shots' given to researchers"* —
  a posição dele **não apoia** "sinal fraco → teste menos
  configurações" como regra de teto por SNR. O mecanismo de custo real
  dele é a fórmula do DSR (`E[max SR] ∝ √(2 ln N)`), que cresce
  SUBLINEAR em N — custo marginal de 96→111 trials é pequeno vs.
  96→246. Isto é raciocínio de síntese aplicado ao projeto, não
  citação direta do paper para este caso específico (ele trata de
  configurações de estratégia, não de hiperparâmetro de modelo).

**Recomendação (engenharia, não decisão final — Manager aprova o
número):** usar `GridSampler` do próprio Optuna (mantém o stack exigido
pelo CLAUDE.md, elimina a pergunta "quantos trials bastam" porque o
espaço fica conhecido e finito) sobre uma grade disciplinada, não TPE
com budget arbitrário — ver tabela combinada em 9.2.

### 9.2 — `sweep_range` de `max_depth` + grade combinada — tabela para aprovação

**Achado que muda a proposta original deste doc** (`[2, 6]` era
placeholder, não pesquisado): a doc oficial do LightGBM
(`Parameters-Tuning.html`, citação direta) dá um exemplo numérico —
"`max_depth=7` → `num_leaves=127` (=2^7, o teto) causa overfitting;
`num_leaves=70-80` (≈55-63% do teto) tem melhor acurácia" — ou seja,
**a própria documentação trata a igualdade `num_leaves = 2^max_depth`
(configuração de produção atual) como o exemplo do que NÃO fazer**, não
como ponto de partida seguro. Isso muda o desenho: `num_leaves` não
deve ficar preso em `2^max_depth` (como o placeholder original deste
doc quase sugeria implicitamente ao tratá-lo só como teto), mas também
não deve virar uma variável livre contínua até 64 (o
`sweep_range` já declarado) sem relação com `max_depth` — precisa ser
testado como FRAÇÃO do teto, condicionado ao `max_depth` do próprio
trial.

**Proposta de grade (`GridSampler`, não amostragem contínua):**

| dimensão | grade proposta | ancoragem |
|---|---|---|
| `max_depth` | `{3, 4}` | 3 = produção atual; 4 = 1 passo acima, testa se mais profundidade ajuda quando k cresce (6→24 features) sem abrir o range completo do exemplo oficial (que vai até 7) — ambiente de sinal fraco (AUC~0,51 medido) pesa contra abrir mais que isso nesta 1ª rodada |
| `num_leaves` (condicional a `max_depth`) | `max_depth=3 → {8, 5}`; `max_depth=4 → {16, 10}` | 1 ponto no teto (=2^max_depth, replica a config atual) + 1 ponto em ~60-65% do teto (replica a proporção do exemplo oficial da doc, 70-80/127≈55-63%) |
| `min_child_samples` | `{10, 20, 40}` | 20 = produção atual (centro da grade); 10/40 = 1 passo pra cada lado dentro do `sweep_range: [10,100]` já declarado |
| `subsample_freq` | `{1, 3}` | 1 = produção atual; 3 = ponto intermediário dentro do `sweep_range: [1,10]` já declarado, sem ir ao extremo |

**Custo resultante (grade completa, `GridSampler` = enumeração
exaustiva, sem incerteza de "convergiu ou não"):**

2 (`max_depth`) × 2 (`num_leaves`, condicional) × 3
(`min_child_samples`) × 2 (`subsample_freq`) = **24 combinações por
k**. × 5 valores de k (6,9,12,16,24) = **120 trials para a Fase A**
inteira (só ETHUSDT/R1).

| item | valor |
|---|---|
| `N_lifetime` antes | 96 |
| delta desta Fase A | +120 |
| `N_lifetime` depois | 216 (~2,25× o atual) |

Comparado às alternativas descartadas: TPE com piso BigQuery (40/k ×
5k = 200) custaria mais E manteria a incerteza "quantos trials
bastavam" que o grid elimina; a "regra de 59-60" (atribuição não
100% verificada) custaria 300 (~3× o atual) só para o degrau de
`max_depth`/`num_leaves`, sem sequer cobrir as outras 2 dimensões.

**Isto NÃO é uma decisão fechada — é a proposta de engenharia pronta
para sua aprovação (ou ajuste dos números/faixas).** Se aprovado, os 4
valores acima viram entradas em `constants.yaml`
(`alpha_lgbm_max_depth.sweep_range: [3,4]`,
`alpha_t2_t1_ablation_grid_*`, classe B, `provenance: ASSUMED`, fonte
citando este doc + a pesquisa acima) antes da Fase 5.13 (implementação)
começar.

**Nada neste doc foi implementado.** Peço aprovação da grade (ou dos
pontos específicos que precisam ajuste) antes de tocar em código.
