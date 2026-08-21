# Brief para Auditoria Externa — M4 (Regime): resultado real, candidato vencedor, Gate Efficiency (AG-118)

### Do resultado nulo da Trilha A ao candidato vencedor real, e da estrutura à economia do gate

**Data:** 2026-08-20
**Para:** revisor externo (sem acesso ao repositório — este documento é a fonte completa)
**Documentos canônicos deste projeto (só 2, decisão do Manager 2026-08-20):** `PLANO_MESTRE_PRINCE2.md` (governança/decisões) e o ADR-001 completo (~1900 linhas, Partes I/II — parecer de arquitetura + layout físico de artefatos). **`PRD_V3_2_UNIFICADO.md`/`PRD_V4_1.md` são OBSOLETOS** — citados aqui só quando relevante pra explicar uma divergência histórica, nunca como justificativa de desenho atual.

---

## 0. Como usar este documento

Este brief cobre 3 entregas sequenciais da mesma sessão, cada uma dependente da anterior:

1. **AG-114** — regra de decisão travada *a priori* (antes de qualquer execução) pra escolher um candidato de regime como GATE de risco, não como feature preditiva. Rodada real executada, candidato vencedor declarado: `hmm_gaussian_k4_v1`.
2. **AG-119/"Condição C"** — investigação paralela sobre se o Jump Model tinha sido descartado por bug de configuração (não por ausência real de sinal). Resultado final, honesto: parcialmente sim (estrutura reconfirmada), mas não muda o vencedor.
3. **AG-118** — dado o vencedor do item 1, mede se ele é **economicamente** útil como gate (não só estruturalmente válido). Resultado: **sinal fraco/inconsistente** — a notícia menos confortável deste brief, reportada sem suavização.

Pedido concreto no final (§8): revisão cética dos 3 blocos, com foco nas perguntas explícitas do §7 — nenhuma delas tem resposta óbvia, e nenhuma foi decidida por conveniência.

---

## 1. Contexto — por que a pergunta mudou (recap para quem não viu o brief anterior)

Até 2026-08-19, o M4 (módulo de detecção de regime) media se 6 candidatos (baseline por quantil + HMM Gaussiano k=2/3/4 + Jump Model + BOCPD) explicavam heterogeneidade de **retorno médio futuro** do Alpha entre buckets de regime — a pergunta certa **se** regime fosse virar *feature* do modelo. Resultado real (4ª execução, dado real): **18/18 p-valores de permutação entre 0,30 e 0,85** — nenhum candidato significativo, nenhuma resolução.

O ADR-001 (auditoria externa de arquitetura, ratificado pelo Manager em 2026-08-20) decide algo que muda a pergunta: **regime não entra como feature do Alpha/Meta na v1 — fica exclusivamente como GATE de risco.** Um gate "não precisa prever, precisa evitar" — não exige significância de retorno, exige identificar corretamente período de risco de cauda elevado. O resultado nulo acima passou a responder a pergunta ERRADA para o papel que regime de fato vai ter.

**AG-114** (`audit/architecture_gaps_log.yaml`) registra esse achado e trava uma regra nova, ANTES de qualquer nova execução (disciplina anti-HARKing do projeto — nunca escolher critério depois de ver o resultado):

| # | Papel | Métrica | Limiar |
|---|---|---|---|
| Gate 1 | desqualifica | Occupancy / `effective_number_of_states` do estado de stress — não pode ser degenerado (nem ausente, nem dominante) | `TBD` até medição real contra o baseline |
| Gate 2 | desqualifica | Transition failure rate — candidato que oscila sem parar é inoperável | `TBD` até medição real |
| Gate 3 | **desempate only** | Detection delay vs. eventos econômicos independentes (LUNA/FTX) | só entra se 2+ candidatos empatarem na métrica primária |
| Primária | ranking | Heterogeneidade de **volatilidade futura** entre buckets (Cochran's Q/I², permutação em bloco — mesmo instrumento estatístico já validado pro teste de retorno original) | maior significância/efeito vence, entre os que passam nos gates |

---

## 2. Resultado real do AG-114 — a rodada que mede as 4 métricas

Extensão executada 2026-08-20 sobre `experiments/m4_critical_windows_report.json` — **10.891,9s (~3h1min)**, 5 janelas críticas × 3 resoluções (R1/R2/R3, dollar-bar) × até 5 símbolos, 0 falhas exceto 1 célula isolada (§6.1 abaixo).

### 2.1 Números medidos — medianas por resolução

| resolução | classificador | estados efetivos | occupancy stress | transition failure (n=5) | I² (%) | p permutação |
|---|---|---:|---:|---:|---:|---:|
| R1 | baseline (`quantile_regime_v1`) | 4,26 | 2,8% | 0,150 | 94,7 | 0,001 |
| R1 | HMM k=2 | 1,90 | **34,1%** | 0,196 | 97,8 | 0,001 |
| R1 | HMM k=3 | 2,77 | 18,3% | 0,177 | 97,4 | 0,001 |
| R1 | **HMM k=4** | 3,44 | 12,7% | 0,224 | **97,4** | 0,001 |
| R1 | BOCPD | 2,88 | 23,7% | **0,529** | 84,1 | 0,085 |
| R2 | baseline | 4,12 | 3,2% | 0,162 | 91,6 | 0,002 |
| R2 | HMM k=2 | 1,91 | **34,9%** | 0,162 | 95,3 | 0,001 |
| R2 | HMM k=3 | 2,77 | 18,4% | 0,210 | 94,5 | 0,001 |
| R2 | **HMM k=4** | 3,62 | 11,1% | 0,224 | **95,0** | 0,001 |
| R2 | BOCPD | 2,83 | 29,7% | **0,557** | 80,0 | 0,188 |
| R3 | baseline | 4,03 | 3,1% | 0,171 | 83,4 | 0,075 |
| R3 | HMM k=2 | 1,96 | **39,5%** | 0,219 | 91,7 | 0,007 |
| R3 | HMM k=3 | 2,79 | 21,5% | 0,195 | 85,7 | 0,005 |
| R3 | **HMM k=4** | 3,44 | 10,5% | 0,228 | **91,8** | 0,003 |
| R3 | BOCPD | 2,70 | 28,8% | **0,472** | 52,0 | 0,341 |

**Achado colateral não trivial:** o próprio baseline deixa de ser significativo a 5% em R3 (p=0,075) — os 3 HMM continuam significativos (p=0,003–0,007). R3 é a resolução mais grosseira (dollar-bar mais lenta); sob menos barras por episódio, um classificador de threshold FIXO (o baseline) perde poder de separação, enquanto o HMM (ajustado ao dado real de cada resolução) mantém.

### 2.2 Metodologia dos 2 limiares — nunca escolhida depois de ver quem ganharia

Em vez de fixar 1 número (risco de HARKing, mesmo escolhendo antes de rodar — o valor exato ainda seria visto no mesmo momento da decisão), testamos **faixa de limiares** e checamos se a decisão é sensível ao ponto exato (mesmo espírito do sweep ±50% exigido para constante classe A):

**Gate 1 (occupancy ≤ ~1/3 — não pode ser "dominante"):** testado em 25%/33%/40%.

| candidato | occupancy (R1-R3) | passa em qualquer ponto da faixa? |
|---|---|---|
| HMM k=2 | 34,1–39,5% | **Não** — falha ou fica no limite em toda a faixa, inclusive por janela individual (ETF_HALVING/RECENTE em R1 chegam a 43-44%) |
| HMM k=3 | 18,3–21,5% | Sim, com folga |
| HMM k=4 | 10,5–12,7% | Sim, com folga |
| BOCPD | 23,7–29,7% | Limítrofe (mas já desqualificado pelo Gate 2, ver abaixo) |

**Gate 2 (transition failure ≤ ~2-3× o baseline):** baseline fica 0,150-0,171; banda 2×-3× = 0,30-0,51.

| candidato | tfr (n=5) | vs. baseline (mediana entre resoluções) | passa em qualquer ponto 2×-3×? |
|---|---|---|---|
| HMM k=2/k=3/k=4 | 0,16–0,23 | ~1,2-1,4× | Sim, com folga |
| BOCPD | **0,47–0,56** | **~3,3×** | **Não** — falha mesmo no limite superior (3×) quando avaliado pela mediana entre resoluções |

### 2.3 Veredito — `hmm_gaussian_k4_v1`

Sobreviventes dos 2 gates: HMM k=3 e HMM k=4 (baseline não é candidato a promover — já está em produção). Na métrica primária, **k=4 vence k=3 nas 3 resoluções**, com a margem mais clara em R3 (91,8 vs. 85,7) — justamente onde baseline e k=3 perdem poder. Não houve empate → Gate 3 (detection delay) não precisou ser invocado.

**Leitura secundária, não decisória:** BOCPD tem o menor detection delay dos 5 (1-1,7 dia vs. 1,1-2,3 dias dos HMM) — mas já desqualificado pelo Gate 2, nunca chega a pesar.

---

## 3. Jump Model / "Condição C" — investigação paralela, resultado final honesto

O Manager contestou a exclusão original do Jump Model (AG-087/AG-117) citando literatura que o trata como forte candidato sob dollar-bar. Investigação achou que a configuração testada (2 features cruas, K=2 forçado, critério de λ não-padrão) diverge de **toda** aplicação publicada de sucesso, em 3 eixos simultâneos — não um teste limpo do método.

**Reteste isolado** (espaço de 4 features + K=3, alinhado à literatura cripto-específica — Cortese/Kolm/Lindström 2023): reversão completa para os 4 ativos não-BTC — todo o grid de λ testado (0,0001 a 0,02) produz ≥2-3 estados genuínos OOS. Um bug real de ponto flutuante (`downside_deviation` retornando `NaN` silencioso por cancelamento numérico) foi achado e corrigido nesse processo.

**Rodada real no harness do M4 ("Condição C", λ=0,02, o mais parcimonioso do grid medido):**

| achado | resultado |
|---|---|
| Validade ESTRUTURAL (≥2-3 estados, não degenerado) | Reconfirmada para SOLUSDT/XRPUSDT (saturação 0% nas 3 resoluções) e majoritariamente BNBUSDT (falha só em R3). ETHUSDT ficou pior (33% de saturação nas 3 resoluções) |
| Utilidade como GATE (métrica primária do AG-114) | **Não demonstrada** — `n_episodes` por célula fica entre 1 e 8 (vs. 37-622 do baseline nas mesmas células), mesmo problema de poder estatístico nulo já visto na execução original do M4. I²=0,0% pra SOL/BNB/XRP nas 3 resoluções |
| Causa raiz do poder nulo | λ=0,02 (escolhido por ser o mais regularizado dentro do que foi medido) produz poucos episódios MUITO longos (persistência mediana 98-2.230 barras) — resolve degenerescência à custa de poder estatístico |

**Conclusão: Jump Model NÃO destrona `hmm_gaussian_k4_v1`** — continua não-competitivo na métrica primária, agora por um motivo bem medido (trade-off regularização-vs-poder), não por saturação. Pergunta explicitamente deixada em aberto, não respondida (evita B20 — nunca escolher hiperparâmetro depois de ver o resultado): um λ menor teria mais poder estatístico?

---

## 4. AG-118 — do candidato vencedor à economia real do gate

### 4.1 A pergunta, e por que é diferente da do AG-114

AG-114 mede se um candidato **tem estrutura** suficiente pra ser um bom detector (abstrato — occupancy, transições, separação de volatilidade). AG-118 mede se o candidato **já escolhido** é útil como gate **econômico** pro triple-barrier real: `P(stop|regime)`, `P(target|regime)`, `E[return|regime]`, `tail_loss|regime`, `holding_time|regime`, e a pergunta original do Manager — "o gate remove uma parte desproporcional dos eventos ruins sem destruir demasiadamente os bons?"

### 4.2 Verificação contra o ADR-001 completo, antes de escrever qualquer código

O arquivo lido em sessões anteriores (222 linhas) era um resumo condensado feito pela própria sessão — não o parecer original. O Manager colou o documento completo (~1900 linhas, Partes I/II) nesta sessão. 3 achados relevantes da releitura:

1. **O contrato `regime()` proposto no ADR-001 (§3.4 Cláusula 2) já reserva um campo `tradeable: Boolean` — "papel 2, o GATE".** AG-118 produz a EVIDÊNCIA (o `lift`, §4.5 abaixo) que justificaria ligar esse campo pro candidato vencedor — não implementa o campo formal em si, que pertence à camada de lake/manifest (`src/io/artifact.py`/`src/io/schema.py`, ADR-001 action item 3, **ainda não construída**).
2. **AG-118 não é bloqueado pela ordem de implementação do ADR-001** ("implementar `src/io/artifact.py` antes de qualquer outro módulo novo") — esse item é sobre a camada de artefato de PRODUÇÃO (consumida por outros estágios do pipeline); AG-118 é análise/medição pós-hoc (`src/analysis/`, fora do contrato de camadas de propósito), nunca produz artefato consumido como insumo de treino.
3. **`decode_mode` obrigatório (§3.4) — só `filter` (causal) é consumível.** Verificado direto no código: `predict_hmm_gaussian` já implementa `p(z_t|y_{1:t})`, nunca smoother/Viterbi — `hmm_gaussian_k4_v1` está em conformidade, confirmado, não assumido.

### 4.3 Arquitetura — fluxo de dado completo

```
Rodada real do AG-114 (já concluída, 2026-08-20)
   │
   ├── RawLabels de hmm_gaussian_k4_v1 persistidos em disco
   │   experiments/m4_raw_labels/{resolução}/{janela}/{símbolo}/hmm_gaussian_k4_v1.parquet
   │   (open_time_ms, close_time_ms, canonical_id — causal, decode_mode=filter)
   │
   ▼
AG-118 (novo, src/analysis/gate_efficiency.py) — CUSTO ZERO EM FITS NOVOS
   │
   ├── 1. Lê RawLabels do parquet já persistido (nenhum refit)
   ├── 2. Recomputa _SymbolForwardVolHistory fresco (barato — só IO + numpy,
   │      sem fit; mesma função já usada pelo bloco gate_quality do AG-114)
   ├── 3. Join causal (_join_candidate_with_vol_history) → canonical_id +
   │      realized_vol_short alinhados por close_time_ms
   ├── 4. identify_stress_state_by_volatility(canonical_id, realized_vol_short)
   │      → identifica qual dos 4 estados do HMM é "stress" (maior vol média)
   ├── 5. As-of join causal (_asof_join_regime_onto_labels, backward, nunca
   │      timestamp futuro) → cada linha de labels.parquet (grade 15m-
   │      calendário) recebe o bucket de regime ATIVO no seu t0
   ├── 6. Por (símbolo, side, bucket): stratum_metrics() [reuso do M6,
   │      3 campos já existentes] + 2 estatísticas NOVAS (tail loss via
   │      percentil de ret_net/atr_at_t0, holding time via n_bars_held)
   │      → GateEfficiencySymbolDetail
   └── 7. Pooling de contagem SL/TP através das 5 janelas (dentro de cada
          resolução) → P(bucket=stress | SL) vs. P(bucket=stress | TP)
          → GateEfficiencyResult (o "lift")
```

### 4.4 Os 2 dataclasses (schema completo)

```python
GateEfficiencySymbolDetail:
    resolution_id: str; window_name: str; symbol: str; side: int; bucket: int
    is_stress_bucket: bool          # bucket == identify_stress_state_by_volatility(...)
    n: int
    p_target: float                 # P(target|regime) = frac_tp (StratumMetrics, reuso)
    p_stop: float                   # P(stop|regime) = frac_sl (StratumMetrics, reuso)
    e_return_atr: float             # E[return|regime] = edge_bruto_atr (StratumMetrics, reuso)
    p05_return_atr: float           # NOVO — tail_loss|regime, percentil 5 de ret_net/atr_at_t0
    median_holding_bars: float      # NOVO — holding_time|regime
    p80_holding_bars: float         # NOVO — heurística ADR-001 recomendação #5 (percentil de holding)

GateEfficiencyResult:
    resolution_id: str; symbol: str; side: int
    bad_event_capture_rate: float   # P(bucket=stress | barrier_hit=SL) -- recall de eventos ruins
    good_event_cost_rate: float     # P(bucket=stress | barrier_hit=TP) -- custo em eventos bons
    lift: float                     # bad_event_capture_rate / good_event_cost_rate
    n_sl_total: int; n_tp_total: int; n_sl_in_stress: int; n_tp_in_stress: int
```

`lift > 1` = o gate captura proporcionalmente mais eventos ruins do que bons (útil); `lift ≤ 1` = não discrimina ou é contraproducente. **Nenhum limiar de "lift mínimo pra valer a pena" foi fixado no código** — decisão explicitamente deixada pro Manager (B20/B23), não estipulada antes de existir dado real.

### 4.5 Resultado medido — o achado mais importante deste brief

30 células (3 resoluções × 5 símbolos × 2 lados), pooling de contagem SL/TP dentro de cada resolução:

| resolução | symbol | side | bad_capture | good_cost | **lift** | n_sl | n_tp |
|---|---|---:|---:|---:|---:|---:|---:|
| R1 | BTCUSDT | −1 | 0,063 | 0,072 | **0,88** | 25.096 | 18.290 |
| R1 | BTCUSDT | +1 | 0,071 | 0,064 | **1,11** | 24.393 | 17.511 |
| R1 | XRPUSDT | +1 | 0,032 | 0,023 | **1,40** | 16.724 | 10.416 |
| R1 | SOLUSDT | −1 | 0,049 | 0,058 | **0,84** | 15.404 | 11.801 |
| R2 | BNBUSDT | −1 | 0,062 | 0,047 | **1,32** | 9.282 | 7.036 |
| R3 | ETHUSDT | +1 | 0,061 | 0,073 | **0,83** | 15.474 | 11.393 |
| *(30 células completas em `experiments/gate_efficiency_report.json`)* | | | | | **0,79 – 1,40** | | |

**`lift` fica entre 0,79 e 1,40 em quase todas as 30 combinações, a maioria pertinho de 1,0 — sem padrão consistente.** Só 2-9% dos SL e dos TP caem no bucket de stress (minoritário, como já esperado do occupancy medido no AG-114), mas dentro dessa minoria a proporção SL/TP não difere sistematicamente do resto.

**Pior — tail loss e holding time vão na direção OPOSTA do esperado de um gate de risco útil:**

| métrica | bucket de stress (mediana, 100 células) | bucket não-stress (mediana, 298 células) |
|---|---:|---:|
| `p05_return_atr` (tail loss, mais negativo = pior) | −1,65 | **−1,80** |
| `p80_holding_bars` (tempo até 1ª barreira) | 20,0 | 17,0 |

O bucket de stress tem tail loss **menos** negativa (levemente melhor) e holding time **maior** que o resto — nem sinal claro de "pior" nem consistente com a intuição de "estado de risco elevado".

### 4.6 Leitura honesta

`hmm_gaussian_k4_v1` venceu o AG-114 porque tem estrutura genuína — detecta heterogeneidade real de volatilidade futura, gates de occupancy/estabilidade passados com folga. Mas essa estrutura, medida aqui pela primeira vez em termos econômicos diretos (o que de fato importa pro triple-barrier real), **não mostra evidência forte de que bloquear entrada no bucket de stress melhoraria o resultado**. As 2 perguntas (AG-114: "tem estrutura?" e AG-118: "essa estrutura é útil como gate?") tinham respostas diferentes — e isso não foi decidido a priori, foi medido.

---

## 5. Verificação mecânica (o que já foi checado antes deste brief)

Todo código citado neste documento passou, sem violação: `ruff check`, `mypy --strict`, `banned_patterns.py --strict` (nenhum literal numérico fora de `constants.yaml`), `check_constants_referenced.py`, `check_unguarded_ratios.py`. 12 testes novos pra `gate_efficiency.py` (valor conhecido à mão — inclusive um caso de `lift=4,0` calculado manualmente —, casos degenerados de amostra zero/denominador zero, IO real de leitura de parquet). Nenhum commit feito ainda — pendente de decisão do Manager.

---

## 6. Achados colaterais desta rodada (não bloqueantes, registrados por transparência)

### 6.1 `AG-120` — 1 célula com desalinhamento de timestamp

`BNBUSDT`/janela `RECENTE`/resolução `R2` falhou com `ValueError` ("bars_df/baseline_df não estão alinhados por timestamp") — isolada com sucesso pelo isolamento de falha por célula do projeto (nenhuma outra célula afetada), mas é um gap de qualidade de dado real entre o pipeline de dollar-bar e o de regime, causa raiz não investigada nesta sessão.

### 6.2 `AG-121` — divergência de critério de canonicalização, PRD-vs-ADR-001

ADR-001 (§3.4) recomenda canonicalizar estado de regime por VOLATILIDADE ascendente (motivado por *label switching* em HMM — a mesma classe de problema estatístico documentada na literatura de mistura/HMM). A implementação real (`src/regime/canonicalization.py`) ordena por RETORNO ascendente — critério que vinha do PRD, hoje obsoleto.

**Não bloqueia nada em produção agora** — `AG-114`/`AG-118` evitam o problema por construção (nunca confiam em `canonical_id` cru como proxy de volatilidade, sempre derivam o bucket de stress via `identify_stress_state_by_volatility`, que mede volatilidade diretamente). Mas é uma migração real pendente antes de qualquer consumidor futuro que confie na ordem do `canonical_id` sem essa mesma cautela — candidato natural pra fazer junto da implementação de `src/io/artifact.py`/`regime()` formal (ADR-001 action item 3).

---

## 7. Perguntas que um auditor cético deveria fazer (lista de trabalho, não retórica)

### Sobre a regra do AG-114 e os limiares dos gates

1. **A faixa testada (25%/33%/40% pro Gate 1; 2×/2,5×/3× pro Gate 2) é ampla o suficiente pra confiar na robustez, ou foi escolhida de forma a já garantir que HMM k=4 passasse?** Nenhum dos 2 limiares foi ajustado depois de ver os números — mas a FAIXA em si foi escolhida por julgamento humano (não medida), e vale perguntar se uma faixa mais ampla (ex. 15%-50% pro Gate 1) mudaria a conclusão.
2. **O Gate 1 usa "occupancy contra o baseline" como âncora conceitual, mas o limiar real (~1/3) não é literalmente ancorado no valor do baseline (~3%) — é ancorado numa noção econômica de "minoria identificável".** Isso é fiel ao texto original da regra ("medir contra o baseline em produção")? Ou é uma reinterpretação que merece ser explicitada como tal (o que este brief já faz, mas vale checar se a reinterpretação é aceitável)?
3. **A métrica primária (I²/p-valor) usa 3 janelas com 5 símbolos e 2 janelas (LUNA/FTX) só com BTC — a agregação por mediana-de-medianas trata essas 5 janelas como igualmente informativas?** Um auditor pode questionar se BTC-only deveria pesar menos, ou se a estrutura de agregação já resolve isso adequadamente.
4. **O baseline deixar de ser significativo em R3 (p=0,075) enquanto os 3 HMM continuam significativos — isso é evidência de que HMM é genuinamente melhor, ou artefato de como cada um responde à granularidade mais grosseira de R3 (menos barras por episódio)?** Vale uma investigação dedicada de POR QUE isso acontece, não só reportar o fato.

### Sobre Jump Model / "Condição C"

5. **λ=0,02 foi escolhido por ser "o mais parcimonioso testado" — mas é literalmente o TOPO do grid testado (0,0001 a 0,02), nunca confirmado como um máximo real.** O teto de λ genuíno está acima de 0,02? Isso muda a conclusão sobre poder estatístico (λ maior = ainda menos episódios, então não ajudaria; mas um λ MENOR dentro do grid já testado teria dado mais poder — por que não foi escolhido esse em vez do maior?)
6. **A escolha de "maior λ testado que ainda é genuíno" prioriza parcimônia/regularização sobre poder estatístico — essa priorização foi decidida a priori (antes de ver que o poder ficaria baixo) ou é justificável só em retrospecto?** Isso tangencia B20 (nunca escolher hiperparâmetro depois de ver o resultado) — vale confirmar que a escolha de λ=0,02 não foi, na prática, uma escolha pós-hoc disfarçada.

### Sobre o AG-118 e o resultado de `lift`

7. **`identify_stress_state_by_volatility` identifica o bucket de stress UMA VEZ por (janela, resolução, símbolo), aplicado igual aos 2 lados (long/short).** Long e short podem ter dinâmicas de risco bem diferentes dentro do MESMO bucket de volatilidade — o gate deveria ser calibrado por lado separadamente? O dado já existe pra checar isso (`GateEfficiencySymbolDetail` já é por side), só não foi a pergunta que o `lift` agregado responde.
8. **O pooling de contagem SL/TP através das 5 janelas dentro de uma resolução — isso pode estar escondendo heterogeneidade real entre janelas?** Ex.: se `lift` fosse 2,0 em LUNA/FTX (choques abruptos) mas 0,5 nas outras 3 (mercado "normal"), o pooling produziria algo perto de 1,0 sem revelar que o gate FUNCIONA bem especificamente em crise. Vale abrir o `lift` por janela antes de descartar a hipótese "gate é útil só em crise".
9. **O bucket de stress ter tail loss LEVEMENTE MELHOR que o resto (−1,65 vs. −1,80) — isso é ruído de amostra pequena (só 100 células com `is_stress_bucket=True`) ou um sinal real de que "volatilidade elevada" não é o mesmo que "risco de cauda elevado" neste dado?** Merece um teste de significância dedicado (não feito neste brief — só reportada a mediana), ou é conclusivo o suficiente pra já pesar na decisão?
10. **`p05_return_atr`/`p80_holding_bars` usam percentis fixos (5%/80%) — o 80% vem de uma recomendação explícita do ADR-001, mas o 5% foi escolhido por convenção de mercado (VaR-style), não medido deste dado.** Um percentil diferente (ex. p01, mais extremo) mudaria a leitura de tail loss?
11. **Todo o pipeline de AG-118 depende de `RawLabels` persistidos por UMA rodada específica do AG-114 (2026-08-20) — se o M4 for re-rodado no futuro (nova config, nova janela), esses parquets são sobrescritos.** O relatório de AG-118 fica então amarrado a uma rodada específica, sem versionamento — isso é aceitável pra um artefato experimental (`experiments/`), ou deveria ter proveniência mais forte (hash da rodada de origem) dado que alimenta uma decisão de risco real?

### Sobre a hierarquia de documentos e AG-121

12. **A correção de framing do AG-121 (PRD obsoleto → ADR-001 é a única recomendação canônica sobre canonicalização) muda a URGÊNCIA da migração, ou só a JUSTIFICATIVA de manter o status quo?** Hoje ninguém está bloqueado (workaround em produção), mas o achado #1 (nenhum dos 2 documentos deliberou sobre isso EXPLICITAMENTE até agora) sugere que "não decidir" também é uma decisão implícita — quanto tempo é aceitável deixar essa divergência sem resolução formal?

---

## 8. O que pedimos exatamente

- Revisão cética das 12 perguntas do §7 — concordância, discordância fundamentada, ou "faltam dados pra responder, meça X primeiro" são todas respostas válidas.
- Validação (ou refutação) da leitura do §4.6: o resultado de `lift`/tail-loss/holding-time é fraco o suficiente pra pesar contra usar `hmm_gaussian_k4_v1` como gate de bloqueio de entrada, ou é consistente com o que a literatura de regime-switching aplicado a risco costuma encontrar (sinais econômicos fracos mesmo quando a estrutura estatística é forte)?
- Recomendação concreta sobre o próximo passo: (a) aceitar `lift`~1 como veredito (regime não vira gate de bloqueio nesta config), (b) investigar as perguntas 7/8 (calibração por side, quebra por janela) antes de decidir, ou (c) outra direção não considerada aqui.

---

## 9. Anexos técnicos — código citado

```python
# src/validation/regime_utility.py — identifica o bucket de stress sem
# confiar na ordem do canonical_id (evita o problema do AG-121)
def identify_stress_state_by_volatility(
    group_labels: IntArray, realized_vol_short: FloatArray
) -> int:
    finite_mask = np.isfinite(realized_vol_short)
    group_labels = group_labels[finite_mask]
    realized_vol_short = realized_vol_short[finite_mask]
    unique_states = np.unique(group_labels)
    mean_vol_by_state = {
        int(state): float(np.mean(realized_vol_short[group_labels == state]))
        for state in unique_states
    }
    return max(mean_vol_by_state, key=lambda state: mean_vol_by_state[state])
```

```python
# src/analysis/gate_efficiency.py — a métrica de remoção assimétrica
def _pool_asymmetric_removal(resolution_id, symbol, side, joined_by_window):
    pooled = pl.concat(joined_by_window)
    sl_df = pooled.filter(pl.col("barrier_hit") == "SL")
    tp_df = pooled.filter(pl.col("barrier_hit") == "TP")
    n_sl_in_stress = sl_df.filter(pl.col("_is_stress")).height
    n_tp_in_stress = tp_df.filter(pl.col("_is_stress")).height
    bad_event_capture_rate = n_sl_in_stress / sl_df.height if sl_df.height > 0 else float("nan")
    good_event_cost_rate = n_tp_in_stress / tp_df.height if tp_df.height > 0 else float("nan")
    lift = (
        bad_event_capture_rate / good_event_cost_rate
        if good_event_cost_rate not in (0, float("nan"))
        else float("nan")
    )
    ...
```

```python
# src/regime/hmm_gaussian.py — confirmação de decode causal (ADR-001 §3.4)
def predict_hmm_gaussian(fit: HMMFit, obs: Float2DArray) -> IntArray:
    """p(z_t | y_{1:t}), NUNCA smoother/Viterbi, que usariam observações
    [futuras] -- decodificação é uma recursão forward pura."""
```
