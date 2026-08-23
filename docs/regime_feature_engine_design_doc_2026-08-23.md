# Arquitetura Técnica — Regime Engine + Feature Engine Multi-Ativo × Multi-Resolução v3

**Status:** Fase 4 — só desenho de arquitetura, ZERO implementação de código
nesta sessão (consistente com o precedente do Alpha,
`docs/alpha_model_design_doc_2026-08-22.md`).

**v3 (2026-08-23):** `project_assurance` (PRINCE2 §6.4, revisor independente
sem acesso ao raciocínio de quem escreveu) encontrou 1 achado CRÍTICO real
sobre a v2 — **D-01, como especificado na v2, poderia introduzir vazamento
temporal (B02)**: a técnica citada como precedente (`hmm_gap_check.py`)
calcula mediana/MAD sobre a SÉRIE INTEIRA, correto lá (diagnóstico único,
não-causal por natureza) mas inválido se portado direto para uma função
por-barra plugada em `compute_stress_triggers → _run_state_machine →
regime[t]`, que viola o próprio contrato causal do `RegimeClassifier`
Protocol ("barra t usa apenas índices < t", `classifier.py:419-420`).
Corrigido nesta versão — ver D-01 revisado. Mais 6 achados (1 mapeamento de
consumidores incompleto, 2 correções de citação de precisão, 2 lacunas de
robustez, 1 questão de versionamento) — changelog completo em §14.

**v2 (2026-08-23):** auditoria adversarial (3 revisores independentes)
sobre o v1 — 6 achados, incluindo um 2º call site esquecido em D-02 e uma
reclassificação de "confirmado correto" para gap real (D-04). Ver §14.

**Pedido original (verbatim):** *"Temos alguns arquivos canônicos dentro de
produção que ainda não foram refatorados apesar de já estarem documentados
nos arquivos de governança, seu desafio é desenhar a arquitetura tecnica
ponta a ponta para o novo motor multi-time frame e multi ativos. `src/regime/
stress.py`, `src/regime/classifier.py`, `src/features/build.py`."*

**Decisão de escopo travada antes deste desenho (AskUserQuestion, 2026-08-23):**
o Regime Engine legado (`classifier.py`/`stress.py`) foi tecnicamente
superado como candidato de MODELO pelo HMM (`build_hmm_regimes`, canônico de
produção) — mas o legado continua sendo o que `src.models.dataset.
build_modeling_frame` chama de verdade hoje. Escolhido: **"Legado + caminho
de troca pro HMM"** — desenhar multi-ativo/resolução real para o legado
(urgente, desbloqueia o pipeline do Alpha hoje) **e** um desenho leve (não
uma re-arquitetura do HMM, que já existe) de como o call site em
`dataset.py` trocaria, com critérios de gate declarados — mesmo padrão do
D-16 do Alpha (pooling como evolução futura gated). Ver §11.

---

## §0 — Sumário executivo

Investigação de código (não suposição) encontrou um padrão que já apareceu
no desenho do Alpha: **a maior parte da infraestrutura multi-ativo já está
pronta**. `symbol: str` já é threaded corretamente em toda a cadeia — zero
hardcode de símbolo único nos 3 arquivos-alvo. O gap real não é
multi-ATIVO, é multi-RESOLUÇÃO, e tem quatro pontos de cegueira a
`bar_source` dentro do Regime Engine (D-01, S6 gap de barra — **causal,
não série inteira, correção crítica v2→v3**), Feature Engine (D-02, purge
do CPCV, `AG-159`, dois call sites) e Regime Engine outra vez (D-04,
histerese em contagem de barra).

Um achado estrutural: existe um **segundo Regime Engine**, `regime_hmm_v1`
(`src/regime/build_hmm.py`), promovido a candidato canônico de produção —
fechado por override executivo do Manager, RATIFICADO em 2026-08-22
(`PLANO_MESTRE_PRINCE2.md §15.12.7`) — mas isso é uma decisão de NEGÓCIO
sobre qual candidato estatístico usar, não uma resolução técnica da
fragilidade metodológica original do Gate 1 (correção de linguagem
v2→v3 — v2 dizia "superou a fragilidade metodológica", overclaim). O
legado continua sendo o que `dataset.py::build_modeling_frame` chama de
verdade — este documento desenha os dois: o fechamento do gap real do
legado (§3) e o caminho, gated, de troca pro HMM (§11).

**Achado novo em v3, que amplia o raio de explosão de D-01 além do que v2
via:** `regime` não é só consumido por diagnóstico/análise — alimenta
`monotone_constraints` do Alpha via uma cadeia real de produção
(`environments.py::assign_environments` → `monotonic.py::
screen_monotone_constraints`, já wired em `pipeline.py::run_layer1_sprint`,
confirmado por leitura de código nesta sessão). D-01 corrigir S6 sob
dollar-bar muda `regime`/`regime_raw` sob R1/R2/R3 — e portanto pode mudar
`monotone_constraints` derivadas para qualquer treino real sob essas
resoluções, não só os 2 relatórios M4 já citados na v2. Ver §7/§11.

---

## §1 — Contexto: o que este documento herda, e não reabre

- **`AG-042`** (Manager, 2026-08-16, `resolved_by_commit: 982b5d4`):
  substitui M15/M30/H1 por `resolution_id` R1/R2/R3. Travado, não reaberto.
- **`§15.12.7` do `PLANO_MESTRE_PRINCE2.md`** (Manager, 2026-08-22): fecha
  `AG-114` — HMM Gaussiano k=4 ratificado como candidato canônico de
  produção, decisão FINAL. **Precisão de linguagem (correção v2→v3):**
  isto é um FECHAMENTO FORMAL DO LEDGER via override executivo do Manager
  — não uma afirmação de que a fragilidade metodológica original do Gate 1
  (occupancy) foi tecnicamente resolvida. As duas coisas são diferentes: a
  decisão de negócio está tomada e travada (não reaberta aqui); a pergunta
  metodológica que motivou `AG-114` originalmente não tem, por si, uma
  resposta técnica nova — só deixou de ser bloqueante para a decisão de
  produção.
- **`AG-030`+addendum**, **`AG-043`**, **`AG-036`**, **`AG-088`**,
  **`AG-095`** — inalterados desde v2, ver v2 para o texto completo
  (não repetido aqui por brevidade; citações intactas em §9).
- **`AG-143`** (2026-08-22, novo em v3): Decision Engine (0% código,
  confirmado por busca ampla) especifica um Gate 01 estruturalmente
  IDÊNTICO ao `control_01_regime_tradeavel` que acabou de ser desligado do
  Risk Engine no mesmo dia (`AG-118`, lift≈1,0 medido, commit `3c0d83d`) —
  se implementado ao pé da letra do PRD original, nasceria repetindo um
  mecanismo já medido como sem efeito. Relevante para §11 (gate a):
  reforça que `regime.tradeable` tem histórico de ser consumido por
  especificação mesmo quando nunca chega a rodar em produção real.
- **`AG-100`/`AG-124`** — **correção de precisão v2→v3:** o v2 deste
  documento generalizou "ambos têm `status: 'aberto'` literal no ledger".
  Verificado diretamente nesta sessão: isso é preciso para `AG-100`
  (`status: "aberto -- decisão de escopo JÁ TOMADA..."`, linha 7262), mas
  **não** para `AG-124` — seu campo `status` (linha 9291) começa
  literalmente com `"STATUS ATUALIZADO 2026-08-22"`, descreve o
  reprocessamento como CONCLUÍDO (15/15 células, validação item 22
  positiva), e só nota que *"trava formal fica com o Manager confirmar por
  escrito quando conveniente"* — palavra "aberto" não aparece nesse campo.
  Ambos os casos descrevem a MESMA situação de fundo (trabalho de
  engenharia concluído, confirmação formal do Manager pendente), mas a
  citação exata precisa ser precisa por AG (mesma disciplina que `AG-163`
  já cobra do documento irmão, Alpha).

---

## §2 — O que já está pronto vs. o que falta de verdade

### 2.1 Multi-símbolo — já pronto, confirmado por leitura de código

Inalterado desde v1/v2. `symbol: str` já threaded corretamente em toda a
cadeia (`build_t1_features`, `build_regimes`, `QuantileRegimeClassifier`,
`discover_filters_hash_snapshots`); `tests/unit/test_features_build.py` já
parametriza 5 símbolos. Nenhuma decisão de desenho necessária aqui.

### 2.2 Multi-resolução — quatro pontos de cegueira a `bar_source`, não dois

1. **S6 (`stress.py`)** — `QuantileRegimeClassifier.classify()` nunca
   repassa `bar_source`/`step_ms`; S6 roda incondicionalmente contra grade
   fixa de 15m. **Fecha em D-01** — com uma correção crítica de v2→v3: a
   técnica de detecção precisa ser CAUSAL (expansiva), não sobre a série
   inteira, para não introduzir vazamento temporal no próprio ato de
   corrigir o gap.
2. **Purge do CPCV (`build.py::compute_max_feature_lookback_ms`)** — sempre
   `step_ms(tf)`, nunca `resolution_id`. **Fecha em D-02** — 2 call sites
   (`pipeline.py`, `leakage.py`).
3. **Histerese em contagem de barra (`classifier.py`)** — `regime_
   confirmation_bars`/`regime_stress_exit_confirmation_bars`/
   `min_warmup_bars`, amarrados a relógio. **D-04**, gap real registrado,
   não resolvido aqui (B23).
4. **NOVO EM v3 — `ENGINE_VERSION`/`classifier_id` não versionados apesar
   de D-01 mudar semântica computada.** `ENGINE_VERSION="regime_v1"`
   (`classifier.py:54`) e `classifier_id="quantile_regime_v1"`
   (`classifier.py:481`) são literais fixos — D-01 muda o QUE
   `"quantile_regime_v1"` produz sob dollar-bar (S6 deixa de estar
   incorreto), sem mudar o NOME. Qualquer artefato/relatório que cite
   `classifier_id` como identidade (os 2 relatórios M4 já citados no §7
   fazem isso) fica ambíguo sobre qual comportamento de S6 gerou o dado.
   Achado do `project_assurance` — ver D-01 e §7 para a decisão.

### 2.3 Itens auditados e confirmados corretos — sem mudança necessária

Inalterado desde v2: `min_common_history_bars` desabilitado sob
dollar-bar; S7/S2/S4/S8/S9 `NOT_COMPUTABLE` uniforme (gap de dado);
`regime_symbol_tf_dir` já fechado; percentil/z-score do Regime Engine já
corretos por serem adimensionais.

### 2.4 Achado estrutural: dois Regime Engines coexistindo

| | `regime_v1` (legado, alvo desta task) | `regime_hmm_v1` (canônico de produção) |
|---|---|---|
| Módulo | `classifier.py`+`stress.py`+`build.py` | `build_hmm.py`+`hmm_features.py`+`hmm_gaussian.py` |
| Multi-ativo × multi-resolução | Parcial — gaps de §2.2 | **Nasceu pronto** |
| Wired em `dataset.py::build_modeling_frame`? | **Sim, é o que roda hoje** | Não |
| `AG-114` | N/A | Fechado por override executivo (§1) — não é resolução técnica do Gate 1 |
| Schema de saída | `t0, regime(pl.Enum, R0-R5), regime_raw(Enum), er_48, er_quantile, vol_pctile, bars_in_regime, stress_triggers, tradeable, engine_version, cost_atr_ratio, econ_regime` | `t0, canonical_id(int), is_stress_state, tradeable, fold_id, classifier_id, engine_version` |

Schema incompatível — sem tradução matemática honesta entre `canonical_id`
e `regime: Enum(R1..R5)`. Ver §11.

---

## §3 — Decisões de desenho

### D-01 — `bar_source` threading real: S6 dollar-bar-aware, CAUSAL (correção crítica v2→v3)

**Estado atual:** `build_regimes` recebe `bar_source` corretamente, mas
não o repassa até `QuantileRegimeClassifier`. `StressInputs.step_ms` fica
sempre `0` → resolve para 15m incondicional. S6 roda `check_grid_
completeness` sobre premissa de grade fixa, inválida sob dollar-bar.

**Precedente citado — reusável só PARCIALMENTE, achado crítico do
`project_assurance` (v2→v3):** `AG-132` resolveu o equivalente pro HMM
criando `hmm_gap_check.check_bars_gap_before_hmm` — z-score modificado
(Iglewicz & Hoaglin, constantes `0.6745`/`3.5`) sobre `diff(close_time_
ms)`. **Essa função calcula mediana/MAD sobre a SÉRIE INTEIRA passada**
(`bars_df` completo) — correto no contexto ORIGINAL dela: é um diagnóstico
WARNING-only, rodado UMA VEZ pelo caller de `build_hmm_regimes` antes de
consumir o dado, nunca embutido numa decisão por-barra. **Se essa mesma
computação (mediana/MAD sobre a série inteira) fosse portada direto para
uma função por-barra plugada em `compute_stress_triggers →
_run_state_machine → regime[t]`, ela violaria o contrato explícito do
`RegimeClassifier` Protocol** (`classifier.py:419-420`: *"Causal e online:
barra t usa apenas índices < t"*) — a mediana/MAD calculada sobre TODA a
série usa gaps de barras FUTURAS (`t' > t`) para decidir se a barra `t` é
anômala; um gap futuro que muda a mediana/MAD muda retroativamente a
classificação de uma barra passada. Isso seria uma nova instância do
banned pattern **B02** — introduzida pelo próprio fix que deveria fechar
um gap, não pelo código legado.

**Decisão corrigida:** `s06_bar_gap_dollar` calcula mediana/MAD **de forma
EXPANSIVA** — na barra `t`, usa só os gaps `diff(close_time_ms)[:t]`
(estritamente anteriores a `t`), mesma disciplina causal já aplicada em
`support.expanding_percentile_rank_strict` (usada por `vol_pctile`/
`er_quantile` no mesmo módulo). Cada barra `t` é avaliada contra a
distribuição de gaps que já existia ANTES dela, nunca contra uma que
inclui o próprio futuro. Isso muda a implementação de "uma chamada
vetorizada de mediana/MAD sobre o array inteiro" (o que `hmm_gap_check.py`
faz, e o que a v2 deste documento presumia implicitamente sem declarar)
para um cálculo expansivo — mais caro computacionalmente (O(n log n) por
janela crescente, ou uma estrutura incremental de mediana/MAD), mas é o
preço de causalidade real, não uma escolha de estilo.

Casos de borda (mantidos de v2, agora reformulados em termos causais):
- Barra `t` com menos de 3 gaps ANTERIORES disponíveis (não "menos de 3
  bars na série inteira", correção de framing v2→v3) → `NOT_COMPUTABLE`,
  convenção dominante de `stress.py` (`_not_computable`).
- Gap não-monotônico (`<=0`) na barra `t` → `TRIGGERED` incondicional,
  independente do z-score expansivo — mesma semântica de integridade de
  dado de `hmm_gap_check.py`.

Assinaturas (aditivas, defaults preservam bit-exato todo caller):
```python
@dataclass(frozen=True, slots=True)
class StressInputs:
    n: int
    open_time_ms: TimeArray
    vol_pctile_expanding: FloatArray
    funding_z_expanding: FloatArray
    step_ms: int = 0
    spread_pctile_expanding: FloatArray | None = None
    filters_hash_snapshots: tuple[tuple[int, str], ...] | None = None
    bar_source: str = "time_15m"
    close_time_ms: TimeArray | None = None
```
`compute_stress_triggers` valida no topo (fail-fast, achado v2, mantido):
```python
if inputs.bar_source != "time_15m" and inputs.close_time_ms is None:
    raise ValueError(...)
```
S6 despacha `s06_bar_gap_dollar(close_time_ms)` (expansivo, causal) vs.
`s06_bar_gap(open_time_ms, step_ms)` (inalterado) por `bar_source`.
`QuantileRegimeClassifier` ganha campo `bar_source: str = "time_15m"`;
`build.py::build_regimes` passa `bar_source=bar_source` no construtor.

**Propagação — confirmado em v2, ampliado em v3 (ver §7):** corrigir S6
muda `stress_state` → `regime`/`regime_raw`/`bars_in_regime` sob
dollar-bar, não só `stress_triggers`/`tradeable`. Em v3, confirmado que
essa mudança se propaga além dos relatórios M4 já citados: `regime`
alimenta `monotone_constraints` via `environments.py`/`monotonic.py` em
produção real (§7, achado novo do `project_assurance`).

**Decisão de versionamento (novo em v3, não resolvida aqui — B23):**
`ENGINE_VERSION`/`classifier_id` deveriam bumped quando D-01 ship, já que
o comportamento sob dollar-bar muda sem mudar o nome? Proponho a
PERGUNTA, não a resposta — decisão do Manager, mesma classe de decisão de
`calibration_version`/`config_hash` já praticada em outras partes do repo.

### D-02 — CPCV purge lookback resolution-aware (fecha `AG-159`) — dois call sites, guarda de runtime (ressalva 3 reforçada)

**Estado atual e correção v1→v2 (2 call sites):** inalterado desde v2 —
`pipeline.py:427` E `src/validation/leakage.py:792` (via `leakage.py:749`,
que já recebe `resolution_id` sem repassá-lo) precisam mudar juntos, ou a
suíte de vazamento reporta PASS falso sob R2/R3. Ver v2 (§14) para o
achado completo — mantido sem alteração de fundo em v3.

```python
def compute_max_feature_lookback_ms(
    tf: str,
    feature_ids: tuple[str, ...] = T1_FEATURE_IDS,
    *,
    windows: FeatureWindows | None = None,
    resolution_id: str | None = None,
) -> int:
    assert_no_expanding_lookback_in_active_set(feature_ids)
    bar_duration_ms = (
        step_ms(tf) if resolution_id is None
        else int(load_constant("label_prefetch_p99_bar_duration_ms"))
    )
    return max_feature_window_bars(windows) * bar_duration_ms
```

**Quatro ressalvas — a 4ª é achado novo do `project_assurance` (v2→v3):**

1. Efeito prático hoje é ZERO (gate de features `expanding` bloqueia
   incondicionalmente) — inalterado.
2. Magnitude não sanity-checada, ~25 dias — inalterado.
3. Modelo de custo do proxy `p99` (prefetch tolera sub-cobertura; purge
   não) — inalterado, com a verificação adicional já proposta em v2
   (agregar máximo real de janela de 96 barras consecutivas sobre os
   parquets persistidos).
4. **NOVO (v3) — a ressalva 3 propõe uma verificação OFFLINE, antes de
   produção; o `project_assurance` pede uma GUARDA EM CÓDIGO, não só uma
   checagem manual pré-deploy.** Consistente com a disciplina de
   fail-loud já praticada no resto do repo (`_BAR_SOURCE_BY_RESOLUTION`,
   `s06_bar_gap_dollar` acima): proponho que, quando o dado necessário
   para a verificação da ressalva 3 estiver disponível (o agregado de
   duração máxima real de 96 barras consecutivas, por símbolo×resolução),
   ele vire uma constante `MEASURED` em `constants.yaml` e
   `compute_max_feature_lookback_ms` emita um `structlog.warning` (não
   `raise` — mesma decisão de severidade que `hmm_gap_check.py` já tomou
   pra gap anômalo, §3/D-01) quando o valor calculado (`96 × p99`) for
   MENOR que esse máximo medido — sinalizando ativamente a situação que a
   ressalva 3 hoje só descreve em prosa. Não implementado aqui (a
   MEDIÇÃO ainda não existe — B23); a arquitetura fica pronta para
   receber a constante quando medida.

### D-03 — Itens confirmados corretos por auditoria (sem decisão de desenho necessária)

Inalterado desde v2.

### D-04 — Histerese em contagem de barra sob dollar-bar (gap real, não resolvido aqui)

Inalterado desde v2. `regime_confirmation_bars`/`regime_stress_exit_
confirmation_bars`/`min_warmup_bars` amarrados a relógio, mesma classe de
`min_common_history_bars_15m`, já medido em `docs/refactor_dollar_bar_
canonico.md:206-207` e nunca fechado por nenhum AG. Registrado como
achado novo (§8), não resolvido (B23).

---

## §4 — Arquitetura técnica ponta a ponta (pós-D-01/D-02)

```
CLI (--symbol --resolution-id)
  -> pipeline.run_layer1_sprint(symbol, resolution_id, ...)
       -> dataset.build_modeling_frame(symbol, resolution_id=..., ...)
            bar_source = _BAR_SOURCE_BY_RESOLUTION[resolution_id]   # já existe
            -> regime_build.build_regimes(symbol, ..., bar_source=bar_source)         # já existe
                 -> classifier.QuantileRegimeClassifier(
                        symbol=symbol, bar_source=bar_source, ...
                    ).classify(features_df)
                      -> stress.StressInputs(..., bar_source=bar_source, close_time_ms=...)  # D-01
                      -> stress.compute_stress_triggers(inputs)
                           S6 = s06_bar_gap_dollar(close_time_ms)  # D-01: CAUSAL/expansivo, não série inteira
                              if bar_source != "time_15m" else s06_bar_gap(...)
            [regime/regime_raw mudam sob dollar-bar -> environments.py::assign_environments
             -> monotonic.py::screen_monotone_constraints -- consumidor real, achado v3]
       -> features_build.compute_max_feature_lookback_ms(tf, resolution_id=resolution_id)  # D-02, 2 call sites
       -> validation.leakage.run_all_leakage_tests(..., resolution_id=resolution_id)        # D-02
```

---

## §5 — Contrato de dados afetado

Inalterado desde v2 (campos aditivos em `StressInputs`/
`QuantileRegimeClassifier`/`compute_max_feature_lookback_ms`; schema de
`classify_regimes` inalterado na FORMA; conteúdo de `regime`/`regime_raw`/
`bars_in_regime`/`stress_triggers`/`tradeable` muda sob dollar-bar uma vez
D-01 implementado). `regime`/`regime_raw`: `pl.Enum`, não `Utf8`.

---

## §6 — Persistência

Inalterado desde v2.

---

## §7 — Pré-requisitos bloqueantes

1. D-02 só produz efeito real após a política de features `expanding` ser
   decidida (Manager, "08_SPLIT") — herdado.
2. Magnitude do purge sob D-02 precisa de sanity check em duas direções —
   herdado de v2, ver D-02 ressalva 4 (nova) pra guarda em código.
3. D-01 depende de `close_time` no DataFrame — já está, validação
   fail-fast cobre o caso não-padrão.
4. Dois call sites de D-02 mudam juntos, não em sequência — herdado de v2.
5. **Herdado de v2, escopo AMPLIADO em v3:** 2 relatórios M4 já publicados
   (`experiments/m4_critical_windows_report.json`, `experiments/
   m4_jump_model_extended_features_condicao_c_report.json`) usam `regime`
   como rótulo de referência sob o S6 hoje incorreto — precisam de decisão
   do Manager sobre re-execução/status provisório.
6. **NOVO (v3) — achado do `project_assurance`, mapeamento de consumidores
   incompleto em v1/v2:** `regime` alimenta `monotone_constraints` do
   Alpha via cadeia de produção REAL, não só análise/diagnóstico —
   `src/models/environments.py::assign_environments`
   (`RANGE_REGIMES={"R1","R2"}`/`TREND_REGIMES={"R3","R4"}`, linhas 31-32)
   é importado e chamado por `src/models/monotonic.py::
   screen_monotone_constraints` (`monotonic.py:42,196`), que por sua vez é
   consumido pelo pipeline real de treino do Alpha via `pipeline.py::
   run_layer1_sprint` (confirmado por leitura de código, não por
   docstring). **Consequência:** D-01 corrigir S6 sob dollar-bar muda
   `regime` sob R1/R2/R3, o que pode mudar `monotone_constraints`
   derivadas em qualquer treino real sob essas resoluções — não é só um
   problema de 2 relatórios de pesquisa já publicados, é um efeito
   colateral potencial em qualquer treino FUTURO do Alpha sob dollar-bar,
   uma vez D-01 implementado. Nenhuma decisão tomada aqui sobre se isso é
   aceitável (é — o comportamento CORRIGIDO é o que deveria valer) ou se
   precisa de aviso/teste de estabilidade dedicado antes do primeiro
   treino real sob R2/R3 pós-D-01. Ver §10 (teste sugerido pelo revisor).
7. **NOVO (v3), menor:** `AG-143` (Decision Engine, ainda 0% código)
   especifica um gate baseado em `regime.tradeable` estruturalmente
   idêntico ao já desligado `control_01_regime_tradeavel` — relevante para
   §11 (gate a), não bloqueia D-01/D-02.

---

## §8 — Governança: achados a registrar (proposto, não aplicado nesta sessão)

**Novos em v3 (`project_assurance`):**

- **Novo (AG a atribuir) — CRÍTICO:** D-01, como especificado na v2,
  poderia introduzir vazamento temporal (B02) se a técnica de
  `hmm_gap_check.py` (mediana/MAD sobre série inteira) fosse portada sem
  adaptação causal para uma função por-barra embutida na composição de
  regime. Corrigido nesta versão (D-01 revisado, computação expansiva) —
  registrar como achado fechado PELO PRÓPRIO DESENHO, não como pendência.
- **Novo (AG a atribuir) — HIGH:** mapeamento de consumidores de `regime`
  incompleto em v1/v2 — `environments.py`→`monotonic.py`→`alpha.py`
  (produção real, `monotone_constraints`), `AG-143` (Decision Engine,
  especificação pendente). Corrigido em §7/§11 desta versão.
- **Novo (AG a atribuir) — MÉDIA:** `dataset.py::side_subset` docstring
  (linhas ~290-300) afirma que `regime` entra como one-hot no vetor de
  treino do Alpha — stale desde a Fase A (`§15.13`, 2026-08-21, quando
  isso foi removido). Doc-drift, não código de produção incorreto — fora
  de escopo de correção nesta sessão (Fase 4), citado para registro.
- **Novo (AG a atribuir) — MÉDIA:** `ENGINE_VERSION`/`classifier_id` não
  versionados apesar de D-01 mudar semântica computada sob dollar-bar
  (§2.2 item 4).
- **Correção de citação (não achado de código):** v1/v2 citaram `AG-100`
  E `AG-124` como tendo `status: "aberto"` literal — preciso só pra
  `AG-100`; `AG-124` usa framing diferente ("STATUS ATUALIZADO", trabalho
  concluído, confirmação formal pendente). Corrigido em §1.
- **Correção de linguagem (não achado de código):** v1/v2 caracterizaram
  o fechamento de `AG-114` como "superando a fragilidade metodológica" —
  impreciso; é um fechamento de ledger por override executivo, não uma
  resolução técnica nova da questão original do Gate 1. Corrigido em §0/§1/§11.

**Herdados de v2 (inalterados):** `AG-159` (escopo ampliado, 2 call
sites); histerese em contagem de barra (D-04); zero cobertura de teste
multi-símbolo do Regime Engine.

---

## §9 — Referências (arquivo:linha)

Todas as referências de v2 permanecem válidas (ver v2 no histórico git
deste arquivo, ou §14 para o resumo). Novas em v3:

- `src/regime/classifier.py:416-420` (`RegimeClassifier` Protocol,
  contrato causal explícito — base do achado crítico D-01).
- `src/regime/hmm_gap_check.py:168-169` (`gaps = np.diff(close_time_ms)`
  sobre `bars_df` inteiro — confirma o cálculo não-causal do precedente).
- `src/models/environments.py:31-32,49-60` (`RANGE_REGIMES`/
  `TREND_REGIMES`/`_structural_group`, consumo real de `regime`).
- `src/models/monotonic.py:42,196` (`from .environments import
  assign_environments`, `df_env = assign_environments(df_train_side)` —
  cadeia de produção confirmada).
- `audit/architecture_gaps_log.yaml`: `AG-124` linha 9291 (`status:`
  completo, verificado), `AG-143` linhas 10696-10711 (Decision Engine).
- `PLANO_MESTRE_PRINCE2.md §15.12.7` (fechamento de `AG-114`, linguagem
  precisa).

---

## §10 — Definition of Done: testes afetados

Itens de v2 mantidos, com D-01 atualizado para refletir a correção causal:

- [ ] Novo teste: `s06_bar_gap_dollar` — determinismo, MAD=0, `n<3` gaps
  ANTERIORES (não da série inteira), não-monotonicidade. **Novo em v3:
  teste de NÃO-VAZAMENTO explícito** — construir uma série sintética onde
  um gap anômalo aparece SÓ no futuro (barras tardias) e confirmar que a
  classificação de barras ANTERIORES a esse gap não muda entre "com" e
  "sem" esse gap futuro presente na série (prova direta de causalidade,
  não só ausência de erro).
- [ ] **Novo em v3, sugerido pelo `project_assurance`:** teste de
  integração/estabilidade — `environments.py::assign_environments`/
  `monotonic.py::screen_monotone_constraints` sob `resolution_id="R2"`/
  `"R3"`, antes e depois de D-01, para medir concretamente o raio de
  explosão em `monotone_constraints` citado em §7 item 6. Comando
  sugerido (PENDENTE-DE-EXECUÇÃO-HUMANA, formulado pelo revisor
  independente):
  ```bash
  uv run pytest tests/unit/test_models_environments.py tests/unit/test_models_monotonic.py -m "not slow"
  ```
- [ ] Demais itens de v2 (fixtures `test_models_pipeline_paths.py`/
  `test_validation_leakage.py` quebrando por `resolution_id` keyword-only,
  parametrização `_SYMBOLS`-style, teste de unidade de D-02 nos 2 call
  sites) — mantidos sem alteração.

---

## §11 — Caminho de troca pro HMM (evolução futura, gated — não implementado aqui)

**Correção de linguagem v2→v3 (gate b):** o v2 já corrigia o v1 dizendo
que o gate "AG-114 resolvido" estava satisfeito. Precisão adicional: está
satisfeito no sentido de "ledger fechado, decisão de negócio travada" —
não no sentido de "a pergunta metodológica original tem resposta técnica
nova". Isso não muda a conclusão (o gate não bloqueia mais o caminho),
só a razão declarada.

**Gate (a) — "regime categórico ainda necessário downstream?" — escopo
ampliado em v3 (achado do `project_assurance`):** v1/v2 caracterizavam o
uso de `regime` como "hoje só filtro/diagnóstico... consumido por
`analysis/`" — impreciso. Consumidor de PRODUÇÃO real e confirmado:
`environments.py`→`monotonic.py`→`monotone_constraints` do Alpha (§7 item
6). Isso torna o gate (a) mais concreto e mais difícil de responder
trivialmente "não, pode descontinuar": `canonical_id` do HMM não tem
tradução natural para `RANGE_REGIMES`/`TREND_REGIMES` (que dependem da
semântica R1..R4 de estrutura×volatilidade cruzada, não de um cluster
estatístico sem ordem) — um swap pro HMM sem resolver este gate quebraria
`assign_environments` silenciosamente ou exigiria reescrevê-lo, ecoando
exatamente o gap já registrado em `AG-088`. Também relevante:
`AG-143` (Decision Engine, ainda sem código) especifica outro consumidor
de `regime.tradeable` — mesma pergunta de "ainda necessário?" se aplica.

**Demais gates (schema incompatível, sem caminho live, risco de
investimento avaliado) — inalterados desde v2.**

**Gates declarados antes de andar por este caminho (3):**
- (a) decisão sobre `regime` categórico downstream — **mais concreto
  agora**: pelo menos `environments.py`/`monotonic.py` e potencialmente
  `AG-143` precisam de uma resposta, não é mais uma pergunta abstrata;
- (b) ~~`AG-114`~~ — já satisfeito (ledger fechado, decisão de negócio
  travada — linguagem corrigida acima);
- (c) caminho de persistência/decode live construído (`src/live/`);
- (d) `is_stress_state` (HMM) substitui S1-S10 ou coexiste.

**Decisão deste documento:** inalterada — não andar por este caminho
agora. Investir em D-01/D-02/D-04 primeiro.

---

## §12 — Próximos passos (não decididos aqui, dependem do Manager)

1. Confirmar classificação de severidade dos achados de §8 (Manager).
2. Decidir a política pendente de features `expanding` ("08_SPLIT").
3. Rodar os sanity checks de magnitude de purge (§7.2, D-02 ressalvas 3/4).
4. Decidir o destino dos 2 relatórios M4 já publicados (§7.5).
5. **Novo (v3):** decidir se um teste de estabilidade de `monotone_
   constraints` sob R2/R3 pré/pós-D-01 (§10) é pré-requisito do primeiro
   treino real sob essas resoluções, ou pode ser verificado depois.
6. Se/quando avançar o caminho HMM (§11), resolver os 3 gates,
   com atenção especial ao gate (a) agora mais concreto.
7. Aplicar governança — só quando explicitamente solicitado.

---

## §13 — Changelog v1

Desenho inicial. D-01 (bar_source-aware S6, sem especificar causalidade —
gap que a v3 corrigiu), D-02 (só `pipeline.py`), D-03 (incluía, por erro,
histerese em contagem de barra). §11 com 4 gates, incluindo `AG-114` como
aberto (impreciso).

## §14 — Changelog v1 → v2 (auditoria adversarial, 3 revisores paralelos)

Críticos: D-02 ganhou 2º call site (`leakage.py:792`); histerese em
contagem de barra reclassificada como D-04 (gap real). Correções de
citação: `AG-114` fechado (não aberto); `AG-100`/`AG-124` "fechado" era
overclaim; `regime`/`regime_raw` são `pl.Enum`, não `Utf8`. Completude:
casos de borda de `s06_bar_gap_dollar` especificados; validação fail-fast
de `close_time_ms`; escopo de D-01 corrigido (`regime`/`regime_raw`, não
só `stress_triggers`); fixtures de teste quebrando por keyword-only.
Ressalva nova em D-02 (modelo de custo do proxy p99).

## §15 — Changelog v2 → v3 (`project_assurance`, revisor independente)

**Crítico:** D-01 corrigido para computação CAUSAL/expansiva de
mediana/MAD em `s06_bar_gap_dollar` — a v2 presumia implicitamente que a
técnica de `hmm_gap_check.py` (série inteira) era diretamente portável;
não é, geraria B02. Ver §3/D-01.

**Alto:** mapeamento de consumidores de `regime` corrigido — `environments.
py`/`monotonic.py`/`monotone_constraints` (produção real) e `AG-143`
(Decision Engine) não estavam no v1/v2. Amplia §7 (pré-requisitos) e §11
(gate a).

**Correções de citação/linguagem:** `AG-100`/`AG-124` — só `AG-100` tem
`status: "aberto"` literal; `AG-124` usa framing diferente (trabalho
concluído, confirmação formal pendente). Fechamento de `AG-114`
recaracterizado como override executivo/ledger, não resolução técnica.

**Médio:** `ENGINE_VERSION`/`classifier_id` sem versionamento apesar de
D-01 mudar semântica computada (§2.2 item 4); `dataset.py::side_subset`
docstring stale (registrado, fora de escopo de correção); D-02 ressalva 3
ganhou uma 4ª ressalva propondo guarda de runtime em vez de só checagem
offline.

**Teste novo proposto:** prova explícita de não-vazamento para
`s06_bar_gap_dollar` (§10); teste de estabilidade de `monotone_
constraints` sob R2/R3 pré/pós-D-01, comando formulado pelo revisor
(PENDENTE-DE-EXECUÇÃO-HUMANA).
