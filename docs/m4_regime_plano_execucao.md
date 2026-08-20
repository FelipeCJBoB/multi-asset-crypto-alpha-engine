> **Proveniência**: documento de plano (Claude Code, modo Plan), escrito e
> aprovado em 2026-08-17, executado nas Fases 0-5 na mesma sessão.
> Commitado ao repositório em 2026-08-18 por decisão do Manager — achado
> de auditoria (`project_assurance`, independente, sobre
> `src/analysis/m4_regime_comparison.py`) apontou que este plano era
> citado repetidamente (docstring do módulo + várias mensagens de commit)
> como fonte de decisões de desenho irreversíveis do M4, sem nunca ter
> sido versionado — quebra da disciplina "toda regra tem âncora, todo
> histórico via `git log`" que o resto do projeto segue. Texto abaixo é o
> plano tal como aprovado, sem edição retroativa — o estado real de cada
> fase (o que foi feito, achados, commits) está em `docs/SPRINT_LOG.md` e
> no histórico de commit real (`git log`), não neste arquivo.

# M4 — Regime: estudo de comparação, ponta a ponta

## Contexto

M4 (`PRD_V4_1.md` §3.2, linhas 412-424) é o único item pago (consome trial)
da Camada 1 de medições — e foi autorizado nesta sessão como próxima frente
de trabalho, depois de M1/M2/M3/M6 já fechados e da migração dollar-bar/
Parkinson estar com engenharia pronta (retreino real represado por decisão
do Manager).

**Candidatos:** quantis expansivos (baseline, produção atual) · HMM
gaussiano (`dynamax`, k=2/3/4) · Jump Model · BOCPD.
**Métricas de utilidade** (não PnL): separação de retorno condicional
(ANOVA F, ω²) · persistência (duração mediana, taxa de troca) ·
estabilidade entre folds (Rand ajustado) · ortogonalidade contra
volatilidade.
**Achado que motiva o M4** (PRD): a partição atual é FUNÇÃO de
volatilidade (`vol_state` deriva de `C07`, posto expansivo de
`realized_vol(48)`) — e `C07` tem IC negativo simétrico nos dois lados
(aponta pra custo de execução, não direção). A partição pode estar
reforçando esse defeito.
**Terceira via (Q3):** com ρ≈0,91, testar se classificar regime só no BTC
e aplicar aos 5 (via Rand ajustado contra a classificação própria de cada
ativo) é suficiente — a medição decide.
**Gate:** `G-C1-2: M4 emitido com ≤6 trials, canonicalização testada`
(banned pattern B21 — estados ordenados deterministicamente por retorno
médio, desempate por variância).

## O que já existe (reuso, não reescrita)

- `src/regime/classifier.py` já tem `Protocol RegimeClassifier`
  (`classify(features) -> DataFrame`, `n_states`, `classifier_id`) desde a
  Camada 0 (T0.2) e `QuantileRegimeClassifier` — **é o baseline #1, usado
  como está**.
- `src/regime/build.py::build_regimes(symbol, start, end,
  bar_source="dollar_r1")` já roda o baseline sob a grade canônica R1 —
  **zero mudança necessária em `build.py`/`classifier.py`** para o M4
  funcionar. O harness de comparação chama os classificadores DIRETO
  (mesmo padrão de `volatility_comparison.py` com `VolatilityEstimator`),
  não via `build_regimes`.
- **Template estrutural a replicar:** `src/analysis/volatility_comparison.py`
  (M1) — `_baseline_estimator`/`_candidate_estimators`, dataclasses de
  métrica por candidato, `compare_..._for_combination`,
  `run_..._for_symbol`, `run_and_save_..._report` (JSON atômico).
- `src/validation/volatility_walkforward.py::generate_anchored_walk_forward_splits(
  open_time_ms, *, initial_train_years)` é GENÉRICO (só timestamps, splits
  ancorados por trimestre civil) — **reusado sem alteração**. As funções de
  métrica desse módulo (QLIKE/Diebold-Mariano) são específicas de forecast
  de volatilidade — não reusáveis, M4 precisa das próprias (ANOVA/Rand).
- `sklearn.metrics.adjusted_rand_score` e `scipy.stats.f_oneway` já estão
  disponíveis (scikit-learn/scipy já são dependências) — Rand ajustado e
  ANOVA **não exigem dependência nova**.

**Achado no caminho, registrar como débito conhecido (não bloqueia M4):**
`src/features/build.py::compute_t1_features` (linhas 158-168) só aceita
`vol_estimator_id=None` (→ATR-Wilder) ou `"parkinson_w{N}"` — **Garman-Klass
nunca foi fiado em produção**, apesar de `constants.yaml::
canonical_volatility_estimator.value` dizer `garman_klass_w20`. O baseline
do M4 (`QuantileRegimeClassifier`, via `C07_vol_pctile_expanding`) roda
hoje sobre **ATR-Wilder**, não GK nem Parkinson. Não é escopo do M4
consertar, mas o relatório final precisa dizer isso explicitamente — senão
lê como "GK vs. candidatos novos" quando é "ATR-Wilder vs. candidatos
novos".

## Decisões de desenho (as 6 perguntas, resolvidas)

1. **Fit no walk-forward:** refit por fold, expansivo, ancorado no mesmo
   splitter do M1. Não é preferência — `B05` (`CLAUDE.md`) proíbe
   literalmente "HMM/regime ajustado na série toda e predito barra a
   barra", manda "reajustar por fold com purge". HMM e Jump Model refazem
   fit em `[0:train_end_idx]` de cada fold, decodificam só o teste do
   fold. **BOCPD é exceção estrutural**: é online por construção (posterior
   de run-length atualizada recursivamente, sem etapa de fit em lote) —
   uma passada sequencial já é causal por definição, não entra no
   walk-forward de refit.
2. **Retorno condicional (ANOVA):** log-retorno de 1 barra à frente,
   `ln(close[t+1]/close[t])`, direto do OHLC da dollar-bar — **não**
   `ret_net`/Label Engine (evita acoplar M4 a suposições de barreira/fill
   que são de M5). Mesma primitiva de `next_bar_realized_variance` do M1,
   sem elevar ao quadrado.
3. **BOCPD — vendorizar** (`src/regime/bocpd.py`, Adams & MacKay 2007,
   Normal-Inverse-Gamma conjugado, hazard constante). Sem lib PyPI madura
   comparável a `dynamax`/`jumpmodels` (pesquisado). Mesmo precedente desta
   sessão (ACD/EGARCH vendorizados quando não havia lib madura). Zero
   dependência nova — só numpy/scipy.
4. **Canonicalização** — `src/regime/canonicalization.py`, função única
   compartilhada pelos 3 candidatos novos (não duplicada): ordena estados
   por retorno médio ascendente, desempate por variância ascendente,
   `ignore_value` pra warmup. Teste central: **invariância a permutação do
   rótulo bruto** — é exatamente o defeito que motivou banir `hmmlearn`.
5. **Contagem de trials — 6 exatos**, tabela:

   | candidato | trial? |
   |---|---|
   | Quantis expansivos (baseline) | 0 |
   | HMM k=2 | 1 |
   | HMM k=3 | 1 |
   | HMM k=4 | 1 |
   | Jump Model | 1 |
   | BOCPD | 1 |
   | Terceira via Q3 (reusa fits, sem reajuste novo) | 1 |
   | **Total** | **6** |

   Grid de símbolo (5 ativos × mesmo desenho) NÃO multiplica — mesma
   convenção de `AG-039`/M1. **Não decidido sozinho**: esta é minha leitura
   de `AG-039` aplicada a um caso novo — precisa de confirmação explícita
   do Manager antes da Fase 5 (é o número que decide se `G-C1-2` passa).
   **Confirmado pelo Manager em 2026-08-18** (ver `docs/SPRINT_LOG.md`).
6. **Grade: só R1 (dollar-bar canônico)**, não 15m também — dobrar grade
   dobraria desenhos distintos e estouraria o teto de 6; consistente com
   M1/M2/M3/M6 já terem rodado só sob R1 nesta sessão. 15m fica registrado
   como iteração futura, não decidido como "nunca".

### Decisões adicionais (não cobertas pelas 6 perguntas, declaradas aqui)

- **Espaço de features de entrada (HMM/Jump Model/BOCPD):**
  `[log_return_1, realized_vol_short]` calculado direto do OHLC da
  dollar-bar — **não** `C07`/`B07` (se os candidatos novos consumissem o
  próprio `vol_pctile`, o teste de ortogonalidade ficaria viciado por
  construção). BOCPD roda univariado só sobre `log_return_1` (setup
  clássico de Adams & MacKay).
- **BOCPD → estados canônicos:** segmenta por changepoint (MAP
  run-length), calcula retorno médio por segmento, agrupa em
  `m4_bocpd_n_canonical_buckets` buckets por quantil do retorno médio do
  segmento, propaga bucket pra nível de barra, passa pelo MESMO
  `canonicalize_states`.
- **Estabilidade entre folds (mecânica exata):** pra cada par de folds
  adjacentes (k, k+1), decodifica o TESTE do fold k duas vezes — com
  parâmetros do fold k e com parâmetros do fold k+1 (que já viu esse
  trecho no treino, expansão ancorada) — compara via `adjusted_rand_score`.
  Mede se a fronteira muda ao aprender mais dado. Reporta média e mínimo
  entre pares.
- **Ortogonalidade contra volatilidade:** reusa `anova_by_group`, resposta
  = `vol_pctile` do baseline em vez de retorno futuro — ω² ALTO aqui é o
  sinal RUIM (candidato só reencontrou C07).

## Pesquisa aprofundada por candidato (pedido do Manager, antes de codar)

Pesquisa web dedicada por candidato — achados que MUDAM decisões do
rascunho anterior, não só confirmam.

### HMM — qual variante, não só "qual lib"

Existem várias famílias: Gaussian HMM (emissão contínua, a nomeada no
PRD) · Discreta/multinomial · Autoregressiva/Markov-switching (Hamilton) ·
Sticky HDP-HMM (não-paramétrica, infere o próprio k) · Hierárquica
adaptativa (meta-regime, 2026, exótica demais pro escopo). **Achado real:**
HMM gaussiano vanilla tende a SUPER-SEGMENTAR regimes sob baixo
sinal-ruído — exatamente o cenário aqui (retorno cripto é ruidoso) — e
"sticky HDP-HMM reduz trocas de regime por um fator de 4 e produz durações
substancialmente mais longas" vs. HMM vanilla. Isso ataca DIRETO uma das
4 métricas do próprio M4 (persistência). Segundo achado: retorno
financeiro não é gaussiano (cauda pesada, skew) — Gaussian HMM é "o
default conveniente", não necessariamente o mais correto.

**Refinamento proposto, dentro do que o PRD já nomeia** (não é trocar de
família, é configurar a mesma família melhor): usar prior STICKY na
matriz de transição do `dynamax.GaussianHMM` (concentração de Dirichlet
enviesada pra auto-transição) — mitiga a super-segmentação sem sair de
"HMM gaussiano". Fica como HIPERPARÂMETRO dentro do trial de cada k (não
trial novo), mesma lógica de M1 fixar janela a priori sem contar sweep.

**Pergunta pro Manager, não decidida sozinho:** aplicar prior sticky
(config dentro do mesmo trial), ou HMM puro sem qualificação adicional
pra bater literalmente com o texto do PRD?

### Jump Model — qual variante

`jumpmodels` (já escolhido) implementa 3: JM discreto (original,
Bemporad et al.) · **Continuous JM (CJM, Aydınhan et al. 2024)** — estado
generalizado pra vetor de probabilidade, transição suave · Sparse JM
(SJM, seleção de feature embutida). **Achado real, decide a escolha:**
a limitação mais citada de HMM em finanças ("sequências sem persistência
e estabilidade, baixo sinal-ruído, alarmes falsos frequentes") é
exatamente o que o "jump penalty" explícito do JM foi desenhado pra
resolver — e a literatura recente (2024) mostra CJM MAIS ROBUSTO que o
JM discreto original, com interpretação probabilística e validado em
dado real. Precedente direto de domínio: paper 2024/2025 aplicou Sparse
JM especificamente em retorno de criptomoeda.

**Decisão revisada:** candidato #5 vira **CJM (contínuo)**, não JM
discreto — mesmo "Jump Model" citado no PRD (é uma variante da mesma
família, não uma família nova), mas a versão que a literatura recente
recomenda como mais robusta. SJM (seleção de feature) não se aplica —
só 2 features de entrada, sem necessidade de seleção automática. `jump_
penalty` fica como HIPERPARÂMETRO fixado a priori (não sweep — orçamento
de 6 trials não abre espaço pra isso), idealmente via critério de
informação que o próprio pacote/literatura recomenda (não um valor
inventado).

**Pergunta pro Manager:** CJM em vez de JM discreto — confirma? (São a
mesma "família" nomeada no PRD, decisão de variante dentro do escopo já
autorizado, não trial extra — mas é uma leitura minha, não uma citação
literal do texto do PRD.)

### BOCPD — qual verossimilhança

**Achado real, o mais acionável dos 4:** BOCPD "padrão" (Adams & MacKay
2007) usa verossimilhança Gaussiana com prior Normal-Inverse-Gamma sobre
(média, variância) desconhecidas — ao integrar a variância desconhecida
analiticamente, a distribuição PREDITIVA resultante já é Student-t, não
Gaussiana (ponto sutil, frequentemente perdido em implementações
simplificadas que fixam a variância). Isso dá alguma robustez a cauda
pesada "de graça". MAS a literatura 2024/2025 é explícita: "a performance
do BOCPD cai significativamente quando o dado real segue distribuição de
cauda pesada" mesmo com esse tratamento — dado financeiro real ainda é
mais pesado na cauda do que o Student-t implícito do NIG dá conta, e
literatura recomenda verossimilhança Student-t EXPLÍCITA.

**Decisão:** implementar a versão NIG-Gaussiana padrão primeiro (mais
simples, testável, conjugada/tratável, já não é "Gaussiana ingênua" pela
integração da variância) — é a versão de referência da literatura,
testável contra caso sintético conhecido. Documentar explicitamente a
limitação de cauda encontrada na pesquisa como debt conhecido, não
escondido, no relatório final e no docstring do módulo. Não implementar
Student-t explícito nesta rodada — aumenta complexidade de manter
conjugado/tratável, e o candidato #6 do orçamento de 6 trials já está
alocado.

**Pergunta pro Manager:** aceitável começar pela versão padrão
(NIG-Gaussiana) com a limitação de cauda documentada, ou vale abrir
escopo pra Student-t explícito nesta mesma rodada (mais complexo, mesmo
trial)?

### Terceira via (Q3) — o que pesquisar antes de rodar

**Achado real, é um caveat de interpretação, não um bloqueio:** literatura
recente em cripto mostra que a ESTRUTURA de transmissão entre ativos
correlacionados muda por regime (não só a magnitude do spillover) — ou
seja, ρ≈0,91 medido pode não ser constante entre regimes, o que
complica (mas não invalida) o teste "BTC decide o regime dos outros 4":
se o Rand ajustado vier baixo, pode ser porque o regime É idiossincrático
(hipótese que o PRD já prevê como possível) OU porque a correlação em si
já varia por regime — os dois cenários dão o mesmo sintoma (Rand baixo)
por motivos diferentes. Segundo achado: há literatura questionando se
"um único ativo proxy" é o modelo certo pra fator comum em cripto versus
um modelo de correlação mais isotrópico/composto (PCA sobre os 5) — mas
isso NÃO desautoriza o desenho já decidido pelo PRD (BTC como fator,
baseado em ρ real medido nesta sessão)-, só registra uma alternativa
documentada pra SE Q3 falhar.

**Não é decisão a tomar agora** — é uma nota de interpretação a incluir
no relatório final (Rand baixo tem 2 explicações possíveis, não 1) e um
candidato de iteração futura (fator composto/PCA) registrado, não
implementado nesta rodada.

## Perguntas pro Manager antes de codar (consolidado)

1. HMM: aplicar prior sticky no `dynamax.GaussianHMM` (mitiga
   super-segmentação, mesma família nomeada no PRD) ou HMM puro sem
   qualificação? **Resolvido (2026-08-17): sticky.**
2. Jump Model: CJM (contínuo, mais robusto por literatura 2024) em vez
   de JM discreto original — confirma a leitura de que é variante da
   mesma família, não escopo novo? **Resolvido (2026-08-17): CJM.**
3. BOCPD: versão NIG-Gaussiana padrão (com limitação de cauda
   documentada) é aceitável pra esta rodada, ou abre escopo pra
   Student-t explícito agora? **Resolvido (2026-08-17): versão padrão.**
4. Contagem de trials (já sinalizada acima, item 5 das 6 perguntas
   originais): confirmar a leitura de `AG-039` aplicada aqui antes da
   Fase 5. **Resolvido (2026-08-18): confirmado, 6 trials exatos.**

## Arquivos novos

| arquivo | responsabilidade |
|---|---|
| `src/regime/canonicalization.py` | `canonicalize_states(raw_state_id, response, *, ignore_value=None) -> CanonicalizationResult`. Puro, sem IO, sem dependência nova. |
| `src/regime/bocpd.py` | `run_bocpd(obs, *, hazard_lambda) -> BOCPDResult`, `segments_to_canonical_states(...)`. Núcleo NIG-Gaussiano (Adams & MacKay) — preditiva marginal já é Student-t por construção (variância desconhecida integrada), limitação de cauda pesada residual documentada no docstring, não escondida. Puro, numpy/scipy só. `classifier_id="bocpd_v1"`. |
| `src/regime/hmm_gaussian.py` | `fit_hmm_gaussian(obs, *, n_states, train_end_idx, seed, sticky_concentration=None)`, `predict_hmm_gaussian(fit, obs)` — posterior FILTRADA (`dynamax.hmm_filter`), nunca smoother/Viterbi (não-causal). `sticky_concentration` (prior de Dirichlet enviesado pra auto-transição, se aprovado — pergunta 1) mitiga super-segmentação documentada na pesquisa. **Bloqueado por aprovação de dependência.** `classifier_id=f"hmm_gaussian_k{n_states}_v1"`. |
| `src/regime/jump_model.py` | `fit_jump_model(obs, *, n_states, jump_penalty, train_end_idx, continuous=True)`, `predict_jump_model(fit, obs_test_fold)` — decodifica só a fatia do fold passada. `continuous=True` usa CJM (Aydınhan et al. 2024, mais robusto por literatura — pergunta 2), não o JM discreto original. **Bloqueado por aprovação de dependência.** `classifier_id="jump_model_cjm_v1"`. |
| `src/validation/regime_utility.py` | `anova_by_group`, `regime_persistence`, `adjusted_rand` — primitivos puros, paralelo a `volatility_walkforward.py` mas pra M4. |
| `src/analysis/m4_regime_comparison.py` | Harness de orquestração (padrão M1/M2/M3/M6): `_baseline_regime` (reusa `build_regimes`), `_input_obs`, `CandidateResult`/`SymbolResult` (dataclasses), `compare_regime_candidates_for_symbol`, `run_regime_comparison_for_symbol`, `run_q3_common_factor_regime` (as-of backward join do rótulo BTC — causal, nunca timestamp futuro), `run_and_save_m4_report`. |

## Arquivos modificados

- **`pyproject.toml`** — `dynamax`+`jax`/`jaxlib` (CPU) e `jumpmodels`.
  **Bloqueado: aprovação explícita do Manager (Fase 0), decisão dele, não
  minha.**
- **`config/constants.yaml`** — novas entradas, cada uma com `provenance`:
  `m4_hmm_n_states_grid: [2,3,4]` (LITERATURE, literal do PRD) ·
  `m4_forward_return_horizon_bars: 1` (DERIVED) ·
  `m4_bocpd_hazard_lambda` (MEASURED — precisa de medição da duração
  mediana do baseline real antes de fixar, não invento o número) ·
  `m4_bocpd_n_canonical_buckets` (proposta 3 — **confirmação do Manager**,
  PRD não especifica K pra BOCPD/Jump Model, só pra HMM) ·
  `m4_jump_model_n_states` (mesma flag) · `m4_jump_model_penalty` (valor
  final só depois do smoke test da API real, Fase 0) ·
  `m4_duckdb_memory_limit_gb`/`m4_duckdb_threads` (mesma convenção de
  throttle de M1/M2/M3). `initial_train_years` reusa a constante de M1
  (mesmo protocolo do PRD), sem duplicar.

## Sequência de execução — fases

**Regra operacional (Manager, 2026-08-17): não pausar a cada decisão.**
Continuar em loop até finalizar tudo que NÃO depende de julgamento do
Manager. Todo ponto que genuinamente depender de uma decisão dele
(dependência nova, interpretação de contagem de trial, achado de escopo
que um audit revelar, etc.) fica EMPILHADO numa lista — só apresentado
tudo junto, de uma vez, no fim (antes da Fase 6, execução real que
consome orçamento). Delegar pra `Agent`s em paralelo tudo que já estiver
totalmente desenhado/definido neste plano, com contexto rico e
autorização explícita pra rodar `uv`/`.py`/pytest/mecânicos diretamente
(Manager não está no computador — "não os limite").

0. **Fase 0 — dependências + smoke test.** ✅ FEITO.
1. **Fase 1 — primitivos sem risco de dependência.** ✅ FEITO —
   `canonicalization.py`, `bocpd.py`, `regime_utility.py` + testes.
2. **Fase 2 — HMM + Jump Model.** ✅ FEITO — `src/regime/hmm_gaussian.py`
   (commit `61d2ce4`) + `src/regime/jump_model.py` (commit `9b945f9`).
3. **Fase 3 — harness de orquestração.** ✅ FEITO (commit `ec370e0`).
4. **Fase 4 — Terceira via (Q3).** ✅ FEITO (commit `db214aa`).
5. **Fase 5 — Auditoria obrigatória, ANTES de qualquer execução real
   (Manager, 2026-08-17).** ✅ FEITO (commits `6be5960`, `7486620`,
   `8c1ba16`, `e1e6ff4`, `b131e02`).
6. **Fase 6 — execução real (consome orçamento, ≤6 trials).** Só depois
   da Fase 5 fechada. Comando exato pro usuário rodar
   (`uv run python -m src.analysis.m4_regime_comparison`), protocolo de
   execução do `CLAUDE.md` — eu não rodo o run real que consome trial
   (diferente do resto do plano, onde execução de desenvolvimento/teste
   já está autorizada direto).
7. **Fase 7 — fechamento.** ⏸️→🔄 **PAUSADA em 2026-08-18, RETOMADA no
   mesmo dia.** 5 auditorias céticas + RAG encontraram 4 achados reais:
   AG-084/AG-085 (BOCPD, 2 bugs que explicam seu único resultado
   aparentemente positivo), AG-086 (HMM, bug de init real mas testado
   causalmente e REFUTADO como causa do ω²≈0 — achado de HMM considerado
   genuíno), AG-087 (Jump Model, colapso a 1 estado em ~25-29% das
   células). Manager decidiu (mesmo dia): registrar os 4 achados agora,
   correção de código fica pra depois; reconsiderar o critério de Gate
   ANTES de corrigir. 2 auditorias adicionais (literatura + aplicação ao
   desenho real) convergiram numa proposta concreta: **Cochran's Q/I²
   de `edge_bruto_atr` por bucket de regime**, reusando
   `m6_common_factor_hypothesis` sem fórmula nova — **AUTORIZADO e
   IMPLEMENTADO** (`src/analysis/m4_critical_windows.py`,
   `AggregatedHeterogeneityResult`, mecanicamente auditado, testes
   escritos, pronto pra rodar junto da próxima execução real, zero passo
   extra). Nota completa em `PRD_V4_1.md` §3.2, logo após a citação de
   `C07`. Gaps adicionais (R5/stress não modelado pelos 3 candidatos
   novos, wiring hard-coded R1-R5 em `alpha.py`/`classifier.py`/
   `environments.py`, Group DRO inexistente) registrados como
   `AG-088`/`AG-089`, confirmados SEM impacto no M4 atual,
   deliberadamente deferidos. Estudo do veto de R5/stress concluiu que
   os gatilhos S1-S10 já são independentes do classificador de regime
   (confirmado por leitura de código) — recomenda desacoplar num módulo
   próprio, não implementado, só desenhado. Registro em
   `audit/n_lifetime.yaml` e decisão final de candidato/Q3 ficam
   condicionados à RE-EXECUÇÃO com BOCPD/Jump Model corrigidos + novo
   critério — ainda pendente, próximo passo real, não decidido nesta
   sessão.
   **Publicar os resultados como 3ª aba do artefato "Biblioteca de
   Testes"** (`https://claude.ai/code/artifact/59a440dc-f496-4548-
   97be-d980b7786411`, republicar mesma URL — NÃO criar artefato novo)
   — ✅ FEITO (2026-08-18), aba `data-tab="m4"` publicada e mantida em
   sincronia com cada decisão desta rodada.

## Testes (DoD)

- **Causalidade**: mesmo padrão de `test_regime_classifier.py`
  (perturbar futuro não muda passado) para HMM e BOCPD. Jump Model: teste
  que PROVA o compromisso documentado (perturbar fora do fold não muda
  nada; perturbar dentro do mesmo fold de teste pode mudar bars
  anteriores do mesmo fold — medido, não escondido).
- **Canonicalização**: ordenação + desempate + determinismo +
  **invariância a permutação do rótulo bruto** (teste central).
- **Determinismo**: seed fixa → mesmo output (EM/coordinate-descent têm
  múltiplos ótimos locais).
- **Métricas**: `anova_by_group`/`regime_persistence`/`adjusted_rand`
  contra casos sintéticos com resultado conhecido à mão.
- **Harness**: estrutura do resultado com `bars_df` sintético (sem tocar
  disco) + 1 teste `integration`/`slow` opcional sobre 1 símbolo real.
- **Q3/as-of join**: prova que o join do rótulo BTC é `backward`
  (`join_asof`), nunca timestamp futuro.
- Não se aplica: paridade lote↔streaming (harness de análise, não feature
  de produção — mesma classe de `cost_surface.py`/
  `m6_common_factor_hypothesis.py`). Sem golden test (nenhum M1/M2/M3/M6
  tem).

## Riscos

1. **JAX no Windows** — nunca usado neste repo, smoke test isolado
   obrigatório na Fase 0, antes de qualquer código de HMM.
2. **BOCPD vendorizado** — núcleo estatístico precisa de teste de
   correção contra caso conhecido (changepoint sintético único, detectado
   no ponto certo), não só teste de wiring.
3. **Custo computacional** — refit por fold (HMM EM + Jump Model
   coordinate-descent) × 5 símbolos × 4 configs é bem mais caro que M1
   (fórmula fechada). Não medido ainda — pode exigir
   `ProcessPoolExecutor` por (símbolo, candidato).
4. **Jump Model / pandas na fronteira** — `jumpmodels` provavelmente
   exige `pandas.DataFrame`; permitido por B26 (interop de borda), mas
   conversão fica estritamente dentro de `fit_jump_model`/
   `predict_jump_model`, nunca vaza pro harness.
5. **Débito herdado do baseline** (ver seção "O que já existe") — relatório
   final precisa dizer explicitamente que o baseline roda sob ATR-Wilder,
   não GK/Parkinson.

## Verificação end-to-end

1. Smoke tests da Fase 0 (JAX/`dynamax`/`jumpmodels`) — confirmação
   textual antes de prosseguir.
2. 7 comandos mecânicos em todo arquivo novo/tocado.
3. `pytest` completo dos testes novos (protocolo: comando entregue, usuário
   roda) — zero regressão nos ~1370+ testes existentes.
4. Teste de canonicalização (invariância a permutação) como gate humano
   explícito antes da Fase 5 — não avança pra execução real sem isso verde.
5. Relatório real (`experiments/m4_regime_comparison_report.json`)
   revisado manualmente antes de declarar `G-C1-2`.
