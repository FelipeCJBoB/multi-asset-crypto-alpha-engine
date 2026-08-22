# ADR-001 — Camada de Artefatos e Contratos de Dado do Motor Quant Multi-Ativo

**Status:** Proposed
**Data:** 2026-08-19
**Deciders:** Manager (ratificação), autor do parecer (proponente)
**Supersede:** `auditoria_externa_resposta_2026-08-19_contratos_e_contestacao.md` e `auditoria_externa_2026-08-19_anexo_layout_fisico_artefatos.md` — este arquivo é a fonte única; os dois anteriores ficam como histórico.
**Nota de processo:** este ADR toca fonte-canônica, gates e SPEC. Pelo protocolo do projeto isso é decisão arquitetural major e deveria ser registrado como `D-###` via effective_challenge formal antes de ratificação.

---

## Contexto

O motor está em refatoração simultânea em dois eixos (multi-ativo: 5 símbolos; multi-resolução: 3 tiers de dollar bar) e a cadeia Features→Label→Pesos→Split→Learner→Calibração→Validação→Meta→Decision→Risk→Execução **não tem contrato de dado em nenhuma fronteira**. A auditoria anterior (Partes I-IV deste documento) propôs 11 contratos e um layout físico de artefatos.

Forças em jogo, todas declaradas nos documentos de origem:

| Força | Valor | Consequência de projeto |
|---|---|---|
| Amostra efetiva | `n_eff ≈ T/H ≈ 1.095` rótulos independentes/ano/linha | Orçamento estatístico minúsculo; cada estágio ajustado sobre dados consome dele |
| Espaço de busca | 15 linhas (5 símbolos × 3 resoluções) | Artefatos multiplicam por 15; comparação entre linhas exige folds comuns |
| Capital | R$ 1.000 ≈ 193 USDT | Sizing quantizado; a camada de execução tem restrições que o backtest precisa replicar |
| Reprodutibilidade | Paridade treino-live bit-exact é requisito declarado do projeto | Proveniência não pode ser convenção; tem de ser estrutural |
| Operação | Solo, single-node, Windows 10 | Ferramenta de infraestrutura pesada é custo puro; concorrência de escrita é local |
| Cadência | Rodadas periódicas de re-seleção com eliminação | Artefatos de rodadas anteriores precisam coexistir, não ser sobrescritos |

**O problema que a arquitetura tem de resolver, em uma frase:** garantir que *qualquer* resultado de validação seja atribuível, sem ambiguidade, ao conjunto exato de dados, features, rótulos, pesos, splits e código que o produziu — num projeto onde o orçamento estatístico é pequeno demais para tolerar um único vazamento não detectado.

---

## Decisão

Adotar um **data lake local endereçado por conteúdo**, com artefatos imutáveis, manifestos encadeados por hash e contratos de schema validados na escrita e na leitura — construído sob medida, com quatro invariantes globais (INV-A a INV-D) em vez de contratos ad hoc por fronteira.

Não adotar ferramenta externa de versionamento de dados. Justificativa na análise de trade-off.

---

## Opções consideradas

### Opção A — Lake local endereçado por conteúdo, construído sob medida *(escolhida)*

Parquet particionado + `manifest.json` com cadeia de hash + `schema.json` validado nos dois sentidos + `config.json` congelado. Detalhamento na Parte III.

| Dimensão | Avaliação |
|---|---|
| Complexidade | **Média** — dois módulos centrais (`src/io/artifact.py`, `src/io/schema.py`), ~600-900 linhas; o resto é aplicação |
| Custo | Disco (ver V-02/V-11) + ~1 semana de engenharia inicial |
| Escalabilidade | Suficiente e com folga: 15 linhas × ~350k barras é dado pequeno; o gargalo é CPU de fit, não I/O |
| Familiaridade | Alta — polars/parquet/JSON já são o stack declarado |
| Aderência ao requisito | **Alta** — é a única opção que expressa causalidade por coluna e paridade bit-exact, que são requisitos de domínio, não de infra |

**Prós:** contratos de domínio (causalidade, `availability_lag_ns`, unidade, paridade) são cidadãos de primeira classe; zero dependência operacional; endereçamento por conteúdo dá cache de validação de graça.
**Contras:** é código para manter; GC e retenção precisam ser escritos; erros de projeto são seus (e há 12 deles listados abaixo).

### Opção B — Convenção leve: parquet + nomes de arquivo, sem manifesto

| Dimensão | Avaliação |
|---|---|
| Complexidade | Baixa |
| Custo | Quase zero |
| Escalabilidade | Boa |
| Aderência | **Insuficiente** |

**Prós:** entrega hoje.
**Contras:** é o estado atual, e é o que produziu os 10 gaps de arquitetura. Sem manifesto não há cadeia de invalidação, então "esse modelo foi validado com esses rótulos?" volta a ser respondido por memória. Num projeto cujo risco dominante é vazamento silencioso, isso é o modo de falha, não uma economia.

### Opção C — DVC (ou lakeFS / Delta Lake) para versionamento e linhagem

| Dimensão | Avaliação |
|---|---|
| Complexidade | Média-alta (nova ferramenta, novo modelo mental, CI própria) |
| Custo | Licença zero (DVC), mas cerimônia por comando e cache duplicado em disco |
| Escalabilidade | Excelente — muito além do necessário |
| Aderência | **Parcial** |

DVC é o candidato mais próximo do caso: é orientado a arquivo, centrado em Git, e liga cada artefato de modelo aos dados, parâmetros e pipeline que o produziram — linhagem completa ([lakeFS, DVC vs Git vs Dolt vs lakeFS](https://lakefs.io/blog/dvc-vs-git-vs-dolt-vs-lakefs/); [DeviDevs, Data Versioning for ML](https://devidevs.com/blog/data-versioning-ml-dvc-lakefs-delta-lake)). lakeFS resolve isolamento por branch em lakes grandes com múltiplos times, e Delta Lake faz sentido quando o dado de treino vive num lakehouse — nenhum dos dois descreve este projeto.

**Prós:** GC, retenção, remote sync e time-travel resolvidos por terceiros; menos código seu.
**Contras decisivos:** a granularidade de linhagem do DVC é **o arquivo**. As garantias de que este projeto precisa são **de coluna** — `causality_class`, `availability_lag_ns`, unidade declarada, paridade bit-exact por feature. DVC não expressa nenhuma delas, então você construiria a camada de manifesto de qualquer forma e ainda pagaria a cerimônia. Trocar "código próprio" por "código próprio + DVC" não é simplificação.

### Opção D — Catálogo em banco (DuckDB/SQLite) + parquet no disco

| Dimensão | Avaliação |
|---|---|
| Complexidade | Média |
| Custo | Baixo |
| Escalabilidade | Boa |
| Aderência | Alta para consulta, média para imutabilidade |

**Prós:** consultar "quais artefatos dependem deste config_hash" vira SQL em vez de varredura de diretório; o `trial_registry` ganha índice de graça e o problema de escrita concorrente (V-06) some.
**Contras:** o catálogo vira estado mutável fora do lake, e pode divergir do disco — exatamente o problema que a cadeia de hash existe para eliminar. Se divergir, qual dos dois é verdade?

**Recomendação sobre D:** adotar como **índice derivado**, nunca como fonte de verdade. Um `catalog.duckdb` reconstruível a partir da varredura dos `manifest.json` dá a ergonomia de consulta sem criar uma segunda fonte. Reconstrução completa deve ser um comando idempotente. Isso é aditivo à Opção A e recomendo fazer — mas depois de A funcionar.

---

## Análise de trade-off

**A vs C é a decisão real, e ela se resolve por granularidade.** O risco dominante deste projeto não é perder um artefato nem colidir versões — é **vazamento causal não detectado numa coluna**, num sistema com ~1.095 amostras efetivas por ano onde um único vazamento produz um resultado bonito e falso. Ferramentas de versionamento de dados resolvem o primeiro problema e são cegas ao segundo. O contrato de causalidade por coluna (INV-C) e o teste de paridade (INV-D) são código de domínio de qualquer maneira. Uma vez que você os escreveu, o que falta para chegar em A é o manifesto — algumas centenas de linhas — enquanto o que falta para chegar em C é o manifesto **mais** a integração.

**A vs B se resolve por assimetria de custo.** B economiza uma semana. O custo de B é que a pergunta "esse número de validação corresponde a esse modelo?" volta a depender de disciplina humana num processo que já demonstrou, quatro vezes, achar erro real em cada rodada de escrutínio. A economia é real e pequena; o risco é raro e caro.

**O que A pede em troca:** disciplina de imutabilidade (nunca sobrescrever) e um GC de verdade. As duas coisas que projetos assim tipicamente não escrevem, e que estão como V-11 abaixo.

---

## Validação de engenharia — 12 defeitos na proposta original

Esta seção é a resposta ao pedido de validação. São defeitos que encontrei **na minha própria proposta** (Partes II e III deste documento), relidos como se fossem de terceiro. Todos já estão corrigidos no corpo abaixo, marcados com `⟲ V-NN`.

| # | Severidade | Defeito | Correção |
|---|---|---|---|
| **V-01** | **CRÍTICO** | `bar_id` como única chave de join é seguro **dentro** de um `config_hash` de `bars/` e inseguro fora dele. Se `threshold_quote` for recalibrado, toda a numeração muda e o `t1_bar_id` de rótulos antigos passa a apontar para outra barra — silenciosamente | Todo artefato chaveado por `bar_id` carrega `bar_close_ts_ns` obrigatoriamente; `bars.config_hash` é explícito no `upstream` de todos os downstream; referência cross-config só por timestamp. `bar_id` é declarado como chave **local a um `bars.config_hash`** |
| **V-02** | **CRÍTICO** | `design/` materializado por `(split_id, fold_id)` duplica a matriz de ~92 colunas por fold. Com CPCV `C(6,2)=15` partições, são ~15× a matriz por linha (≈251 MB/linha bruto → ≈3,8 GB/linha → ≈56 GB nas 15 linhas), só no `design/` | `design/` guarda a matriz **uma vez** por `(linha, design_hash)`. Pertencimento a fold vive em `splits/` e `w_final` em `weights/`; ambos entram por join no fit |
| **V-03** | **CRÍTICO** | `validation_key = hash(design_hash, label_config_hash, learner_config_hash, calibrator_config_hash, split_id)` **omite** as configs de `weights/` e `regime/`. Mudar `concurrency_scope` altera o treino e não altera a chave ⇒ validação obsoleta é reusada — exatamente a falha que o mecanismo existia para impedir | `validation_key = blake2b(content_hash(calibrated_scores) ‖ split_id)`. O `content_hash` já é transitivo sobre todo o DAG upstream, então a omissão vira impossível por construção |
| **V-04** | ALTO | INV-D com `assert == ` em float64 é spec que falha de forma intermitente e acaba desativada com `@pytest.mark.skip` — o pior desfecho possível para um teste de vazamento | Duas classes declaradas no registry: `parity_class: exact` (índices, postos, Fenwick, contagens — comparação `==`) e `parity_class: tolerance` com orçamento em ULP declarado por feature (reduções em ponto flutuante) |
| **V-05** | ALTO | Escrita atômica por rename de diretório **não é garantida no Windows**: `MOVEFILE_REPLACE_EXISTING` não se aplica a diretórios, e `MoveFileEx` pode cair silenciosamente para `CopyFile` não-atômico. Além disso `exists()` seguido de rename é TOCTOU | Não depender de atomicidade do rename: **`_SUCCESS` é a autoridade**, e leitor ignora diretório sem ele. Rename com captura de exceção em vez de pré-checagem, e retry com backoff (antivírus e indexador do Windows seguram handles) |
| **V-06** | ALTO | `trials.jsonl` com append concorrente corrompe: append atômico no Windows exige **uma única chamada** à API nativa, o que io bufferizado de Python não garante. Fits paralelos por fold produzem linhas interleaved | Um arquivo por trial (`trials/{trial_id}.json`, escrita atômica de arquivo) + compactação periódica para `trials.parquet`. Zero lock, zero corrupção |
| **V-07** | ALTO | `{config_hash}/` como nível de diretório sem `chave=` quebra a convenção hive; polars extrai partição de componentes no padrão `key=value` | `{stage}/config_hash={h}/symbol={S}/resolution={R}/part-*.parquet`. Com `config_hash` **acima** das partições, uma única `scan_parquet` cobre as 15 linhas da rodada — que é literalmente a operação da seleção |
| **V-08** | MÉDIO | `schema_version` está no manifesto mas **fora** do payload do `config_hash`. Uma mudança de schema reusa artefato antigo em silêncio | `schema_version` entra no payload do hash |
| **V-09** | MÉDIO | `column_stats` declarado como "gate" sem baseline, sem banda de tolerância e sem dono. Ou nunca dispara, ou dispara sempre e é ignorado | Comparação contra o artefato anterior da mesma `(stage, linha)`, bandas no `config.json`, e override explícito `accept_drift=true` que grava nota assinada no manifesto |
| **V-10** | MÉDIO | `fsync` por linha crítica no caminho de envio de ordem conflita com o requisito de latência que o próprio documento declara | Durabilidade forte só em `intents.jsonl` (é o que garante idempotência após crash). `orders/fills/account` são reconstruíveis da exchange; `position_ledger` é derivado |
| **V-11** | MÉDIO | Imutabilidade + "nunca sobrescrever" **sem política de retenção** = crescimento ilimitado. O documento original não menciona GC | GC de artefatos não referenciados por modelo promovido nem pelo `trial_registry`; diretórios sem `_SUCCESS` colhidos imediatamente; e um comando `impact --dry-run` que mostra quantos artefatos uma mudança de config invalida **antes** de fazer a mudança |
| **V-12** | BAIXO | `n_eff` no manifesto de `weights/` é escalar, mas pesos são por fold — então `n_eff` também é | Bloco `effective_sample` por fold + agregado |

**Padrão nos defeitos.** V-01, V-02 e V-03 têm a mesma raiz: eu especifiquei o **conteúdo** de cada artefato com cuidado e fui descuidado com a **identidade** deles — o que é chave, o que é escopo de uma chave, e o que a chave de cache precisa cobrir. É o mesmo tipo de erro que o parecer acusa nos documentos originais (contrato de dado bem descrito, fronteira de sistema não checada), aplicado um nível acima. V-03 em particular era um mecanismo anti-obsolescência com um buraco de obsolescência dentro.

---

## Validação cruzada contra 3 auditorias externas independentes

Três auditorias externas (`Auditoria externa cética.md` = **A**; `fundamentar as recomendações.pdf` = **B**; `relatorio_auditoria_externa_2026-08-19.md` = **C**) foram confrontadas ponto a ponto com este ADR. Documento completo: [`validacao_cruzada_ADR-001_vs_3_auditorias_2026-08-19.md`](validacao_cruzada_ADR-001_vs_3_auditorias_2026-08-19.md).

| Categoria | Qtd | Efeito |
|---|---|---|
| Convergência 3-4 vias | 8 | Confirma posições já tomadas |
| Insight aceito (eles acharam, eu não) | 12 | Entram abaixo, tag `⟳ X-NN` |
| Refutação (eles erraram) | 18 | Documentadas no anexo |
| Autocorreção (eles me refutaram) | 2 | Aplicadas inline, tag `⟳ AC-NN` |
| Achado meu que os 3 não viram | 5 | Continuam de pé |

**Os 12 insights incorporados:**

| Tag | Origem | Insight |
|---|---|---|
| **X-01** | A §22 | **As-Of Snapshot.** Falta a entidade universal de "o que estava disponível naquele instante" no lado *online*. O `trade_intent` carrega valores, não uma referência a um objeto imutável — logo a decisão não é replayable. Regra: *toda decisão consome exatamente um `snapshot_id` imutável* |
| **X-02** | A §24, C Ach.1 | **PromotionManifest.** O ADR especificou a cadência da rodada e o `trial_registry`, mas não o artefato que **congela** o resultado e que a produção carrega. Sem ele, "linha promovida" é estado implícito |
| **X-03** | A §23 | **Bundle de compatibilidade.** A cadeia de hash prova cada artefato isoladamente; nada impede o runtime de carregar Alpha novo + regime antigo + calibração antiga, cada peça com manifesto válido e o conjunto inválido |
| **X-04** | A §2 | **LineState é máquina de estados, não booleano:** `FLAT \| ENTRY_PENDING \| OPEN \| EXIT_PENDING \| RECONCILIATION`. `EXIT_PENDING` é um estado que eu não tinha; `RECONCILIATION` dá nome ao modo degradado do §2.1. **Com a chave corrigida** — ver N-01 abaixo |
| **X-05** | B, C | **Colisão intra-barra** no triple-barrier: se `high ≥ tp_px` e `low ≤ sl_px` na mesma barra, a ordem é indeterminada sem tick. Convenção precisa ser declarada — ela desloca a taxa-base do rótulo |
| **X-06** | C Ach.3 | **Dollar bars de símbolos diferentes não são contemporâneas.** Corrige um erro meu — ver `⟳ AC-01` |
| **X-07** | C Ach.4 | **Razão de margem de manutenção** como trava: é o número sobre o qual a exchange de fato liquida, e nenhum dos meus 4 invariantes o media |
| **X-08** | C §5.3(A) | **Taxonomia de descarte.** Eu registrava `reason_codes` no intent que **existe**; falta registrar quem vetou o sinal que **não** virou trade. Sem isso há viés de sobrevivência de sinal, e não se distingue "Alpha fraco" de "gates superdimensionados" |
| **X-09** | A §28 | **`holdout_touched`.** Eu tinha contador de desbloqueios; A tem um flag que **muda o que é permitido** (proíbe inspeção de feature, tuning, ranking, otimização de threshold) |
| **X-10** | A §5 | **Shadow mode** para (D), com telemetria contrafactual. Gera o dado de calibração em vez de só medir histórico. **Ressalva minha:** shadow contra rótulos de 8h continua medindo o evento errado — rótulo condicional a regime **primeiro** |
| **X-11** | A §15 | **`WeightBasis` separado de `FoldWeights`.** Melhor que remendar com campo de escopo: o basis são fatos do rótulo, os pesos só existem dado um fold. Torna o erro inexprimível |
| **X-12** | A §6.1 | **`stale_after` medido:** `max(2 × P99(event_age), mínimo_configurado)`. Eu deixei `STALENESS_MAX` sem valor e sem método — uma estipulação, num projeto cujo princípio é "medido, nunca estipulado". *Ressalva:* o P99 desloca sob rajada; a janela de medição precisa incluir stress |

**Também adotados, vindos das refutações:** a estrutura de 4 gates rígidos de C (DSR `p<0,05` · PBO `<0,30` · monotonicidade de folds `≥70%` · Brier `<` climatológico) no lugar do meu gate único; decomposição espectral para `N_eff` em vez de clustering ONC (determinística e sem hiperparâmetro), com a citação corrigida — a fórmula de Li & Ji (2005) soma autovalores substituindo por 1 os maiores que 1, **não** é a razão de participação que C escreve; e o invariante de A: *"Risk pode dizer APPROVE / RESIZE / REJECT / KILL, mas não deve descobrir uma nova tese direcional."*

**Posição refinada sobre regime no Meta (§2.7).** A e C recomendam "sim" sem engajar com o resultado nulo da Trilha A. Mas devo uma concessão: a Trilha A testou heterogeneidade da resposta do **Alpha** (direção); o alvo do Meta é `ret_net > 0` **líquido de custos**, e o custo varia com regime por mecanismo (spread alarga sob stress), não por hipótese. **Posição final:** regime entra no Meta **através das features de execução que ele governa** (Grupo J), que já estão no contrato; o **estado** como one-hot permanece desligado até um teste de resposta condicional passar.

**Os 5 achados que passaram por três auditorias sem serem reencontrados nem contestados** — e dois deles refutam o desenho central de A e C:

| # | Achado | Status |
|---|---|---|
| **N-01** | `(símbolo, resolução)` não é entidade portadora de posição na Binance | **Refuta A e C.** `LineState.line_id = symbol + resolution` (A) e `positions: dict[SymbolResolution, PositionState]` (C) não têm contraparte na exchange |
| **N-02** | Granularidade de lote vs. capital: ~3 níveis de sizing em BTC; precisão difere ~24× entre símbolos | C chega perto, com `minNotional` errado por 14× e sem notar a assimetria entre símbolos |
| **N-03** | Hurdle de custo `p* = (sl+c)/(tp+sl)` e o pré-filtro que custa 1 trial | Nenhum dos três calculou um breakeven |
| **N-04** | Entradas maker adversamente selecionadas ⇒ população rotulada ≠ executável | Nenhum dos três; C tem a feature no Meta, não o viés no Alpha |
| **N-05** | `n_eff ≈ T/H`, invariante à resolução | C afirma o oposto **e se contradiz** (define `ū_i` corretamente na Fronteira 2) |

A síntese de N-01 com X-04 é o desenho correto:

```
LineState      (lógico,  chave = line_id) : FLAT | ENTRY_PENDING | OPEN | EXIT_PENDING | RECONCILIATION
SymbolExposure (físico,  chave = symbol)  : net_qty, entry_px, margem — o que a exchange reporta

INVARIANTE: no máximo UMA linha por símbolo em estado ≠ FLAT,
            salvo se existir SymbolAggregator com atribuição e roteamento líquido.
```

**Mudança de severidade.** O furo da **saída maker inexecutável** (§1.4, problema 2) sobe para o item **#1 isolado** da lista de prioridade: C o encontrou de forma independente, com a mesma cadeia causal — *"ordens maker de saída não são preenchidas... o trade continua aberto até ser estopado no SL físico ou liquidado"*. Convergência independente entre revisores sem contato é o sinal mais forte disponível de que um achado é real.

---

## Consequências

**Fica mais fácil**
- Responder "esse resultado veio de quê" sem depender de memória: é a cadeia de `manifest.json`.
- Rodada de re-seleção periódica: artefatos de rodadas anteriores coexistem por construção, e a comparação entre 15 linhas vira uma `scan_parquet` (após V-07).
- Detectar deriva de custo, de taxa de barreira e de schema: `column_stats` vira gate (após V-09).
- Trocar a política de features: é troca de `feature_manifest`, não edição de código.

**Fica mais difícil**
- Iterar rápido em exploração: cada execução exige config congelado e hash. Mitigação: um modo `scratch/` fora do lake, explicitamente não-promovível, para exploração.
- Consumo de disco: mesmo após V-02, imutabilidade custa. Sem V-11 implementado, isso vira problema em meses, não anos.
- Mudanças no modelo de custo: invalidam a cadeia inteira nas 15 linhas. Isso é **correto** — mas precisa do `impact --dry-run` para não ser uma surpresa.

**O que vai precisar ser revisitado**
- O orçamento de ULP de V-04, depois que houver medição real de quais features são exatamente reproduzíveis.
- A escolha de não adotar catálogo em banco (Opção D): revisitar quando a varredura de manifestos passar de ~2s.
- A decisão de uma resolução por símbolo (Parte I, §1.2): se duas resoluções sobreviverem com edge descorrelacionado, o `SymbolAggregator` volta à mesa.

---

## Action items

1. [ ] Ratificar este ADR como `D-###` pelo protocolo de effective_challenge do projeto.
2. [ ] Implementar `src/io/artifact.py` e `src/io/schema.py` — INV-A a INV-D, com V-01, V-05, V-07, V-08 já embutidos. **Antes de qualquer outro módulo.**
3. [ ] Implementar `impact --dry-run` e o GC (V-11) junto com o writer, não depois.
4. [ ] Migrar `weights.py` e `src/features/build.py` para o writer novo (são os dois artefatos que já existem).
5. [ ] `src/registry/trials.py` no formato um-arquivo-por-trial (V-06).
6. [ ] `src/validation/pbo.py` + `pbo_matrix.parquet` — a perna capenga admitida no material de apoio.
7. [ ] Declarar `parity_class` por feature no `registry.yaml` (V-04) e escrever o teste parametrizado único.
8. [ ] Rodar o pré-filtro de custo das 15 linhas (Parte I, §2.6) — não depende de nada acima e pode eliminar a maior parte do trabalho.
9. [ ] ⟳ X-01/X-02/X-03 — `snapshot/`, `promotion/` e `bundle/` como artefatos de primeira classe. O `bundle/compatibility` roda antes de qualquer ordem.
10. [ ] ⟳ X-04 + N-01 — `LineState` (5 estados, chave `line_id`) **e** `SymbolExposure` (chave `symbol`), com o invariante de uma linha ativa por símbolo.
11. [ ] ⟳ X-05 — declarar `barrier_collision_rule` e **reportar `collision_rate`** antes de confiar em qualquer taxa-base de rótulo.
12. [ ] ⟳ X-08 — `dropped_signals.jsonl` com taxonomia fechada, desde o primeiro sinal gerado (retroativar depois é impossível).
13. [ ] ⟳ AC-01 — reestimar ρ entre símbolos em relógio comum ≥ 1h (ou Hayashi-Yoshida) antes de qualquer decisão de cap.

---
---

# Parte I — Parecer de auditoria externa

*(corpo do parecer de auditoria externa, 2026-08-19, incorporado sem alteração de conteúdo)*

## 0. Sumário executivo — os 7 vereditos que mudam decisão

| # | Veredito | Impacto |
|---|---|---|
| 1 | **§5.3(B) não é implementável como está escrito.** `(símbolo, resolução)` não é entidade portadora de posição na Binance USDⓈ-M. Em One-way mode existe **uma** posição por símbolo, conta inteira; em Hedge mode existem duas (LONG/SHORT), nunca uma por resolução. O gate "posição no MESMO (símbolo, resolução) ≠ FLAT" não tem resposta derivável do estado da exchange. | Bloqueia B. Força escolha: 1 resolução por símbolo, ou ledger sintético de atribuição + roteamento de ordem líquida. |
| 2 | **§5.3(D) quebra paridade treino-live no rótulo.** O classificador foi treinado sobre barreira vertical de 8h. Encurtar o horizonte ao vivo faz `p` ser a probabilidade de um evento (barreira 8h) usada para tomar outro evento (barreira 4h). Calibração e Brier do Meta ficam inválidos exatamente no regime onde mais importam. | O mecanismo revisado repete o defeito estrutural da versão refutada, em outra camada. |
| 3 | **Nenhuma das duas versões de (D) — nem apertar stop, nem encurtar horizonte — é executável sob a política de execução declarada.** Post-only GTX que nunca converte a mercado não tem caminho de saída garantido. Isso atinge o **stop-loss do próprio triple-barrier**, que os rótulos assumem executado ao preço da barreira. | Furo mais grave do conjunto, e anterior a (D). Toda a geometria de payoff assume uma saída que a política de execução proíbe. |
| 4 | **§5.3(C) conta trials errado nas duas direções.** 15 linhas com ρ(BTC,ETH)≈0,94 não são 15 trials independentes — são da ordem de 2. E `n_trials` por rodada torna o DSR de uma linha função da cardinalidade da rodada (um 16º símbolo muda retroativamente o DSR de linhas já promovidas). | A convenção aprovada é incoerente sem contador vitalício — que foi descomissionado. |
| 5 | **§6.1 é um falso dilema.** Nem cache-TTL nem aceitar-defasagem: o estado de posição chega por **push** (`ACCOUNT_UPDATE`/`ORDER_TRADE_UPDATE`), que não consome `REQUEST_WEIGHT`. REST vira reconciliação. O gate opera **fail-closed**: stream velho ⇒ bloqueia entrada nova, nunca bloqueia saída. Sob rajada, negar entrada é o comportamento desejado. | Dissolve a decisão pendente inteira. |
| 6 | **Barreira vertical em milissegundos sobre relógio de dollar bar é erro de unidade.** `time_stop_ms = 28.800.000` sobre barras amostradas por volume faz cada rótulo cobrir um número diferente de barras — desfaz parte do motivo de usar dollar bar. Deve ser `time_stop_bars`. | Corrige §2.1, §6.5 e a fronteira Features→Label de uma vez. |
| 7 | **A amostra efetiva é ~1.100 rótulos independentes por ano, e isso independe da resolução** (`n_eff ≈ T/H`). O eixo multi-resolução **não compra estatística** — compra custo/turnover. O hurdle de custo difere ~2,8pp de win-rate de breakeven entre R1 e R3. Existe pré-filtro grátis que elimina linhas antes de qualquer backtest. | Responde §6.6 e §6.8 com aritmética, não com preferência. |

---

## 1. §5.3 — Ataque às 4 propostas já aprovadas

### 1.0 O padrão de ponto cego que encontrei

As 4 rodadas adversariais atacaram **o interior do mecanismo** ("essa regra, do jeito que está escrita, tem furo lógico?"). Nenhum dos 5 achados de §5.2 atravessa uma **fronteira de sistema**: exchange ↔ motor, ou rótulo ↔ execução. Os quatro achados foram: dependência de módulo inexistente, prioridade de rate-limit, violação de garantia codificada, inutilidade da opção. Todos internos ao software.

O viés sistemático não é "raciocínio superficial" — é **fechamento de fronteira**. Um revisor da mesma família raciocina dentro do universo descrito pelo documento que está lendo, e o documento descreve o motor, não a Binance nem a distribuição de payoff dos rótulos. Os quatro achados abaixo vêm todos de fora dessa fronteira. É por isso que 4 rodadas não os pegaram, e é a categoria que vale a pena procurar deliberadamente nas próximas.

---

### 1.1 (A) Decision Engine no inventário — **discordo do "pular esta"**

Colocar o Decision Engine no inventário sem definir de quem é a **identidade e a idempotência da intenção de trade** é como se produz double-send. Duas consequências concretas:

1. **É o único ponto onde múltiplas linhas competem por um recurso escalar** (o cap de posições, a margem cruzada). Sem ordenação determinística das intenções dentro do mesmo batch de fechamento de barra, o sistema não é *replayable* — dois replays do mesmo dado podem promover linhas diferentes. Isso quebra reprodutibilidade de backtest antes de quebrar qualquer coisa em produção. É também exatamente o item que o material de apoio já identificou como faltante ("regra de priorização entre linhas aprovadas concorrentes") — ele não é um item solto, é uma cláusula do contrato do Decision Engine.
2. **A tabela de §7 para em Validação→Meta-Model.** As fronteiras Meta→Decision, Decision→Risk, Risk→Execução e Execução→Ledger — as únicas que tocam dinheiro — não aparecem nem como lacuna. Adicionar a caixa sem adicionar as setas deixa o inventário formalmente completo e materialmente incompleto. Proponho os 4 contratos faltantes em §3.8.

---

### 1.2 (B) Gate por linha — **refutado como especificado**

**Veredito: a resolução aprovada não é implementável na Binance USDⓈ-M. Precisa ser reescrita.**

**Evidência 1 — modelo de posição da exchange.** O position mode é definido **por conta, não por símbolo**: *"In One-Way Mode, you can open only one position (long or short) per symbol at a time. Opening a position in the opposite direction will close the existing one."* Em Hedge Mode existem exatamente dois buckets por símbolo (LONG e SHORT), não um por resolução. E *"Binance Futures position mode is applied account-wide, so it's either Hedge Mode or One-Way Mode for all symbols"* — [Binance, What Is Hedge Mode](https://www.binance.com/en/support/faq/what-is-hedge-mode-and-how-to-use-it-360041513552); [Altrady, Hedge Mode and One-way Mode](https://support.altrady.com/en/article/futures-hedge-mode-and-one-way-mode-urbl8u/).

Consequência dura: se `BTCUSDT:R1` e `BTCUSDT:R3` sobreviverem ambas à seleção — cenário explicitamente desejado pelo mandato ("os PARES que entregarem mais edge", plural) — elas **compartilham uma única posição BTCUSDT**. A pergunta "a posição de `BTCUSDT:R3` está FLAT?" não tem resposta no estado da exchange. Pior: quando `R1` fecha, a posição de `R3` fecha junto, porque é a mesma posição. O gate aprovado preserva a proteção original apenas se o universo tiver no máximo uma linha por símbolo — condição que ninguém declarou.

**Evidência 2 — ordens de linhas opostas se matam.** Com `timeInForce=GTX`, uma ordem que cruzaria o book é rejeitada/expirada em vez de virar taker; e *"Self-Trade Prevention (STP) won't take effect for timeInForce FOK or GTX"* ([Binance STP FAQ](https://developers.binance.com/docs/derivatives/usds-margined-futures/faq/stp-faq); [Binance, Post Only / TIF](https://www.binance.com/en/support/faq/what-are-maker-post-only-order-time-in-force-order-and-iceberg-order-5d3fa5e5709f47e0b5f186b350da1655)). Se `BTCUSDT:R1` posta compra no bid e `BTCUSDT:R3` posta venda no bid, a segunda é rejeitada. Duas linhas concorrentes no mesmo símbolo produzem cancelamentos **sistemáticos e correlacionados com o desacordo entre resoluções** — isto é, com o momento em que o sinal é mais ambíguo. Não é ruído aleatório; é um viés de execução com estrutura.

**Evidência 3 — o gate ignora ordens pendentes.** "posição ≠ FLAT ⇒ bloqueia entrada" não cobre a janela em que a posição está FLAT mas existe uma GTX resting. Com cancelamento por timeout, essa janela é a regra, não a exceção. Dois fechamentos de barra consecutivos dentro dela ⇒ duas ordens resting ⇒ fill duplo.

**Reescrita proposta:**

```
gate_entrada(line) := PERMITE  sse
    net_exposure(symbol(line)) == 0            # granularidade real da exchange
    AND open_orders(line_id)      == ∅
    AND reserved_intents(line_id) == ∅         # reserva LOCAL, antes do envio
    AND position_ledger_fresh()                # ver §2.1 — fail-closed
```

Três mudanças em relação ao aprovado:

1. O teste de **exposição** é por símbolo; o teste de **duplicação** é por linha e roda contra o ledger local de intenções, não contra o estado da exchange.
2. Idempotência ancorada na exchange: `newClientOrderId = intent_id`. Reenvio do mesmo intent é rejeitado pela própria Binance, não pela lógica local. Isso elimina a classe de double-send sem depender do rastreador de posição — e portanto sem depender da decisão §6.1.
3. Política de conflito no mesmo símbolo — escolha explícita necessária, ambas defensáveis:
   - **(i) uma resolução por símbolo na seleção.** Reduz o espaço simultâneo de 15 para 5 linhas e, de quebra, *reduz a multiplicidade* (bom para o DSR).
   - **(ii) `SymbolAggregator`.** As linhas do mesmo símbolo emitem intenções; um agregador as combina numa **posição-alvo líquida** e emite o delta. O gate por linha vira contabilidade interna e a exchange só vê a rede. Custa um módulo real.

**Recomendo (i) na primeira rodada**, e (ii) só se a rodada mostrar duas resoluções do mesmo símbolo sobrevivendo com edge descorrelacionado — o que, dado o resultado nulo da Trilha A e a redundância entre resoluções, considero improvável.

---

### 1.3 (C) Convenção de contagem de trials — **errada nas duas direções**

**Veredito: o conserto da circularidade resolveu o sintoma e manteve a doença.**

**Problema 1 — sobre-contagem por correlação.** A convenção conta 15 linhas como 15 trials. Mas o DSR deflaciona pelo número **efetivo** de trials independentes: *"the effective number of independent trials N is not always equal to the literal count of backtests if many are highly correlated"*, e a técnica recomendada é agrupar trials por clustering (ONC, clustering hierárquico como cota inferior conservadora, métodos espectrais) sobre as séries de retorno dos próprios trials ([Deflated Sharpe Ratio, Wikipedia](https://en.wikipedia.org/wiki/Deflated_Sharpe_Ratio); [Bailey & López de Prado, SSRN 2460551](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)).

Aritmética do seu universo — número efetivo de apostas sob equicorrelação `ρ`: `N_eff = N / (1 + (N−1)ρ)`. Com ρ ≈ 0,8 (fontes reportam ρ(BTC,ETH) ≈ 0,94 e ρ(alt,BTC) tipicamente > 0,7, convergindo para 1 sob stress — [FXStreet, correlation cheat sheet](https://www.fxstreet.com/cryptocurrencies/news/bitcoin-correlation-cheat-sheet-for-portfolio-diversification-202309141858)): `5/(1+4×0,8) = 1,19`. As 3 resoluções do mesmo símbolo são ainda mais redundantes entre si do que os símbolos entre si. **N efetivo da ordem de 2, não 15.** Contar 15 deixa o DSR conservador demais e mata edge real.

**Problema 2 — a circularidade não foi eliminada, foi movida.** O conserto removeu a dependência do *resultado*. Mas `n_trials` continua sendo a **cardinalidade da rodada**. Se a próxima rodada incluir um 16º par, o DSR de toda linha já promovida muda retroativamente: a significância da linha X passa a depender de uma decisão administrativa sobre a linha Y. Não é o mesmo furo, é da mesma família.

**Problema 3 — convenção sem consumidor.** `N_lifetime` foi descomissionado como orçamento vinculante e nada o substituiu (admitido em §4 do material de apoio). (C) define como contar um número que hoje não bloqueia nada. Convenção de contagem sem gate é documentação, não controle.

**Correção proposta (as três juntas):**

- `n_trials` **vitalício e cumulativo**, e **subproduto automático do pipeline**, não ledger manual: cada `fit` grava linha append-only no `trial_registry` com `(config_hash, split_id, série de retorno OOS)`. Substitui o `N_lifetime` sem reintroduzir o que foi "mal implementado desde o começo" — porque ninguém digita nada.
- `N_eff` **calculado**, não lembrado: clustering das séries de retorno OOS do registry.
- Gate primário deixa de ser DSR e passa a ser **PBO/CSCV**, que mede overfitting **sem precisar contar trials**. O material de apoio registra que PBO não está implementado neste repo — essa é a peça concreta faltante, e é mais barata do que resolver a filosofia de contagem.

**O que preservo de (C):** o critério estrutural ("exige backtest novo por candidata = 1 trial; passe de ranking que reusa artefato = 1 trial") está certo e é útil — é ele que torna o pré-filtro de custo de §2.6 **gratuito** no orçamento de multiplicidade. Não jogue fora.

---

### 1.4 (D) Gatilho de proteção — **a versão revisada tem o mesmo defeito da refutada, deslocado**

**Veredito: discordo do mecanismo aprovado. Quatro problemas independentes; o primeiro e o segundo são bloqueantes.**

**Problema 1 (fatal) — quebra de paridade no rótulo.** O `M_long`/`M_short` foi treinado sobre rótulos com `time_stop = 8h`. `p = P(toca TP antes de SL, dentro de 8h)`. Se o motor encurta o horizonte ao vivo sob stress, ele usa `p` de um evento para decidir outro evento. Não é aproximação — é troca de variável aleatória. Consequências:

- A calibração (`p_cal`) deixa de valer, e o **Brier score é uma das 5 condições de entrada do Meta** — passa a ser medido contra uma distribuição que não é a operada.
- O efeito é assimétrico: com TP=2,0×ATR e SL=1,5×ATR, a barreira de perda está mais perto e é tocada mais cedo em média. Truncar o horizonte remove desproporcionalmente o bucket **vertical/time-stop**, que é o de menor informação — mas também o que continha as recuperações lentas. Sem medição, o **sinal** do efeito é indeterminado. Adotar um mecanismo cujo sinal você não conhece, sob stress, é a definição de risco não gerenciado.

**Correção:** se o horizonte é condicional a regime ao vivo, ele tem de ser condicional a regime **no rótulo**. `horizon_bars(regime_t0)` vira parâmetro da geometria de rotulagem, o modelo é retreinado sobre esses rótulos, e o "gatilho ao vivo" some — vira a aplicação da mesma regra que gerou o rótulo. Relabelar é barato; descobrir em produção que a calibração não vale sob stress, não.

**Problema 2 (bloqueante) — não há caminho de saída executável.** A política declarada é maker post-only (GTX), cancela no timeout, **nunca converte a mercado**. Uma GTX que cruzaria o book é rejeitada, não executada. Então "encurtar o horizonte máximo de holding" significa, operacionalmente: no bar `t0+H'`, postar uma ordem passiva e torcer. Isso não é uma saída — é uma intenção de saída.

E isto não atinge só (D). Atinge **o stop-loss do triple-barrier**. Os rótulos assumem que tocar `sl_px` significa sair a `sl_px`. Sob post-only sem conversão a mercado, tocar `sl_px` significa que o preço atravessou o seu nível enquanto a sua ordem passiva ficava do lado errado do movimento. **A geometria de payoff inteira (2,0 / 1,5 / 8h) descreve uma estratégia que a política de execução declarada não consegue executar.** Este é o furo mais grave que encontrei nos dois documentos, e é anterior a (D).

Note o padrão: a rodada 4 refutou "apertar o stop" com um argumento de execução ("uma vez disparado, o stop vira ordem sujeita ao mesmo book fino"), e então aprovou um substituto que **também** depende de saída executável, sem reaplicar o mesmo invariante. Ponto cego correlacionado em estado puro: o argumento certo foi usado uma vez e não foi generalizado.

**Escolha necessária (premissa do projeto, não detalhe):**
- **(a)** a política admite `reduceOnly` a mercado para **saídas**, mantendo post-only apenas para **entradas**. A assimetria é justificada e é prática padrão de maker: paciente para entrar, impaciente para sair.
- **(b)** os rótulos passam a refletir saída passiva com modelo de fila, e `ret_net` de cada rótulo vira condicional a fill.

(a) é ordens de magnitude mais barato e é o que recomendo. (b) só se justifica se houver uma razão de custo específica para nunca pagar taker — e, com taker a 0,05% vs maker a 0,02%, o diferencial é 3 bps por perna, contra perdas de cauda ilimitadas por não sair.

**Problema 3 — a economia de (D) está justificada pelo motivo errado.** Funding BTCUSDT medido agora: `lastFundingRate = 0,00008286` por 8h = **0,83 bps por período de 8h**. Round-trip maker-maker VIP0 = 2 × 0,0200% = **4,0 bps** ([fee schedule 2026](https://binancemakertakerfee.org/)). Cortar o horizonte de 8h para 4h economiza ~0,4 bps de funding contra 4 bps de custo de transação. O benefício de (D) **não é custo** — é exclusivamente redução de janela de exposição. Isso precisa estar escrito, senão alguém calibra o parâmetro contra a métrica errada.

**Problema 4 — parte do efeito desejado já é grátis.** As barras são dollar bars: sob stress o volume monetário acelera, as barras chegam mais rápido, e um horizonte expresso **em barras** já encurta sozinho em tempo de relógio. Meça `barras/hora` sob R5 vs R1-R4 antes de escolher qualquer parâmetro — é possível que o gatilho seja redundante com a própria amostragem.

---

## 2. §6 — Recomendação fundamentada para cada uma das 9

### 2.1 Cache-TTL vs. aceitar-defasagem — **nenhum dos dois: push + fail-closed**

**Recomendação: ledger local de posição alimentado pelo WebSocket user data stream; REST só como reconciliação; o gate falha fechado.**

O dilema pressupõe que o estado de posição precisa ser **puxado** por REST. Não precisa.

- O user data stream entrega `ACCOUNT_UPDATE` e `ORDER_TRADE_UPDATE` por push, com ordenação estrita garantida: *"messages of the same event type (e.g. ACCOUNT_UPDATE, ORDER_TRADE_UPDATE) are strictly ordered by both T (transaction time from Matching Engine) and E (event time)"* ([Binance, User Data Streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams)).
- O consumo de `REQUEST_WEIGHT` é do handshake (peso 5) e do keepalive do `listenKey` (a cada < 60 min), não do fluxo de mensagens. O orçamento medido agora na `exchangeInfo` é `REQUEST_WEIGHT 2400/min`, `ORDERS 1200/min`, `ORDERS 300/10s`. Um keepalive a cada 50 minutos é ruído nesse orçamento.
- Logo a chamada de baixa prioridade **sai do caminho quente**. REST (`positionRisk`) vira heartbeat: a cada N segundos ociosos, após todo reconnect, e após qualquer gap de sequência.

**A parte que resolve o stress, independente do transporte:** o rastreador só é consultado para **permitir** uma ação. O comportamento sob incerteza é assimétrico e trivial:

```
stale_after = max( 2 × P99(event_age), mínimo_configurado )     # ⟳ X-12: MEDIDO

se agora() − last_stream_event_ts > stale_after:
      BLOQUEIA entrada nova                       # custo: perder uma oportunidade
      NÃO bloqueia saída / cancel / kill-switch   # nunca dependem do ledger
```

⟳ **X-12:** a versão anterior deixava `STALENESS_MAX` sem valor e sem método — uma estipulação, num projeto cujo princípio declarado é "teto medido, nunca estipulado". A fórmula acima vem de A. **Ressalva que acrescento:** o P99 medido em tráfego normal desloca sob rajada, que é exatamente quando o limiar importa; a janela de medição precisa incluir períodos de stress, ou o limiar fica apertado justamente quando deveria ser tolerante.

Sob rajada — exatamente o cenário do dilema — o comportamento correto é não abrir posição nova. **O modo degradado do rastreador coincide com a política de risco desejada.** Isso torna a escolha entre TTL curto e defasagem irrelevante: qualquer defasagem detectada vira bloqueio, e bloqueio é seguro.

**Sobre "correto no papel, nunca exercitado sob carga" (§4 do material de apoio):** concordo que é categoria de risco própria. Teste barato e disponível hoje, sem `place_order` implementado: rodar o cliente contra o **testnet** USDⓈ-M com um gerador de rajadas sintéticas de ordens/cancelamentos, verificando que (i) `X-MBX-USED-WEIGHT-1m` nunca cruza o limite e (ii) sob saturação artificial, a fila de prioridade drena execução/kill-switch antes de qualquer leitura. Exercita o invariante sem exigir a camada de execução real.

---

### 2.2 Valor do cap de posições concorrentes — **2, mas o cap por contagem é o controle errado**

**Recomendação: contagem = 2 como backstop; controle vinculante é risco agregado; tamanho por posição escalado por `1/n_abertas`.**

Três justificativas independentes que convergem em ~2:

**(a) Diversificação inexistente.** `N_eff = 5/(1+4×0,8) ≈ 1,19`. Duas posições concorrentes não são duas apostas — são **uma aposta de tamanho 2×**. As fontes convergem: a diversificação intra-cripto colapsa sob stress, e altcoins mostram correlação com BTC ainda mais forte do que com ações.

**(b) Margem cruzada e capital real.** `USDTBRL = 5,1812` ⇒ R$ 1.000 ≈ **193 USDT**. Com risco-alvo ~0,65%/trade e stop de 1,5×ATR, o notional por posição em BTC fica em 200–280 USDT (aritmética em §4.2). Duas posições ⇒ ~2,5× de alavancagem sobre equity cruzada; cinco ⇒ ~6×. Com ρ→1 sob stress, 6× correlacionado num movimento adverso simultâneo de 10% consome ~62% do equity. **O cap de 2 é defensável pela margem sozinha**, sem invocar correlação.

**(c) O cap por contagem não controla o que precisa ser controlado.** Duas posições de tamanhos diferentes carregam riscos diferentes. Substitua por:

```
INV_1 (risco):       Σ_i [ notional_i × stop_dist_i ]  ≤  R_max × equity     # R_max ≈ 1,0%
INV_2 (alavancagem): Σ_i notional_i                    ≤  L_max × equity     # L_max ≈ 3
INV_3 (backstop):    n_posicoes_abertas                ≤  2
INV_4 (correlação):  risco_por_posicao = R_max / n_abertas_apos_entrada
```

`INV_4` é o que impede que "cap 2" signifique silenciosamente "risco 2×". Sem ele, o cap por contagem é uma autorização para dobrar exposição.

**Medição pendente (barata, antes de congelar) — ⟳ AC-01, autocorreção:** a versão anterior deste parágrafo recomendava medir ρ **sobre os retornos das próprias dollar bars**. Isso está errado, e erra na direção perigosa. Dollar bars de símbolos diferentes fecham em instantes de relógio distintos (uma barra de BTC às 14:02:15, uma de XRP às 14:11:40 — achado de C), e correlação estimada sobre séries em relógios não alinhados sofre viés **para baixo**: é o Epps effect, cujas causas primárias são assincronia, lead-lag e discretização de tick, com a correlação amostral tendendo a zero conforme o intervalo encolhe ([The Epps effect under alternative sampling schemes](https://arxiv.org/html/2011.11281)). Como o meu próprio critério era "se ρ < 0,6, o cap pode subir para 3", o artefato de amostragem **liberaria mais posições concorrentes**.

Correção: ρ estimada (i) sobre retornos reamostrados num **relógio comum ≥ 1h**, ou (ii) com estimador robusto a assincronia (Hayashi-Yoshida, que usa apenas retornos com intervalos sobrepostos). Nunca sobre dollar bars cruas de símbolos diferentes. O critério de elevação do cap para 3 só vale sobre ρ medida assim.

**Quinto invariante — ⟳ X-07:** os quatro acima são *ex ante* sobre risco desejado. Falta o *ex post* sobre a distância até o evento que a exchange de fato executa:

```
INV_5 (liquidação): maintenance_margin / margin_balance ≤ 0,30  ⇒ senão BLOCK_NEW_ENTRIES
```

Alimentado por `ACCOUNT_UPDATE`, sem custo de REST.

---

### 2.3 Denominador da perda diária — **equity total da conta, ancorada em 00:00 UTC**

**Recomendação: `equity_now = wallet_balance + unrealized_pnl` contra `equity_at_day_open` capturado em 00:00 UTC. Nada de nocional alocado por linha.**

1. **A exchange liquida a conta, não a linha.** Em margem cruzada a margem é fungível por construção — a própria exchange não segrega. Um denominador por linha é um número que nenhum evento da exchange pode validar, o que garante deriva de reconciliação: seu controle e a realidade divergem e não há árbitro.
2. **A prática de mercado usa equity, incluindo não-realizado.** Nas regras de risco de mesas/prop: *"breaches are always applied based on open trades (unrealized losses) and, therefore, on the account's current equity value"*, com o teto diário ancorado *"to your starting balance or your starting equity at that exact millisecond of the reset"* ([Alpha Capital](https://help.alphacapitalgroup.uk/en/articles/6934210-what-are-the-daily-risk-limits-and-how-do-they-work); [CrossTrade](https://crosstrade.io/learn/risk-management/daily-loss-limits)).
3. **Custos e funding entram de graça.** `wallet_balance` já absorve fees e funding realizados; `unrealized_pnl` absorve o resto. Um denominador sintético teria de reimplementar essa contabilidade — que é justamente onde vive o custo de 19,4% de ATR.
4. **Âncora em 00:00 UTC**, não hora local nem rolling 24h, porque é o mesmo relógio do settlement de funding (`nextFundingTime` observado: `1787212800000` = 00:00 UTC). Alinhar reset e settlement evita que um pagamento de funding caia em dois dias contábeis conforme a hora do corte.

**Atribuição por linha:** mantenha como **observabilidade** (`pnl_attrib(line_id)` responde "qual linha está sangrando" para a próxima rodada), nunca como denominador de controle.

**Escala que muda a conversa:** 2% de 193 USDT = **3,86 USDT ≈ R$ 20**. Ver §4.2: sob stress, isso comporta ~3 stops de uma posição BTC de **tamanho mínimo**, e não há como reduzir mais o tamanho.

---

### 2.4 Adotar (D) agora ou adiar? — **terceira opção: adotar como decisão de rotulagem, adiar como controle ao vivo**

A pergunta é binária no brief e as duas opções falham pelo mesmo motivo (§1.4, problema 1). Sequência recomendada:

1. **Agora, custo ~zero:** dos rótulos existentes, extraia a distribuição de `tempo até a primeira barreira` condicional a (regime em t0, símbolo, resolução, lado). É um `groupby` sobre artefato existente. Responde empiricamente se o horizonte de 8h sequer é vinculante sob stress — suspeita: sob R5 quase nada chega ao time-stop, e o gatilho não faz nada.
2. **Agora, custo baixo:** meça `barras/hora` por regime (problema 4 de §1.4).
3. **Depois de (1) e (2):** se sobrar efeito, `horizon_bars` vira função do regime **na geometria de rotulagem** e o modelo é retreinado.
4. **Depois de (3), e não antes — ⟳ X-10, shadow mode.** A propõe implementar o mecanismo e rodá-lo em modo sombra, registrando `stress_trigger_ts`, `normal_deadline`, `stress_deadline_candidates`, `actual_exit_ts`, `counterfactual_outcome`. Isso é estritamente melhor que a minha versão para a parte prospectiva: o histórico responde "o horizonte de 8h era vinculante?", o shadow responde "o que teria acontecido se eu tivesse cortado?", que é a pergunta de calibração. **Ressalva que mantém a ordem:** um contrafactual medido contra rótulos de 8h continua medindo o evento errado (§1.4, problema 1). Rótulo condicional a regime **primeiro**, shadow **depois**.
5. **Independente de tudo:** resolva a saída executável (§1.4, problema 2). É maior que (D), é pré-existente à expansão multi-ativo, e não depende de medição nenhuma para ser decidido.

O risco que o brief propõe "aceitar e adiar" não é o risco de não ter (D) — é o risco de não ter saída. Adiar (D) é barato; adiar a saída é o que zera a conta.

---

### 2.5 Heurística de partida para o encurtamento — **percentil empírico em barras, não número de relógio**

**Primeira escolha (empírica, disponível hoje):**

```
horizon_bars(regime r, símbolo s, resolução R) = percentil_80( tempo_até_primeira_barreira | r, s, R )
```

medido **só no fold de treino**. O percentil 80 cobre a massa dos eventos que resolvem e corta a cauda que só acumula exposição sem informação. Não é chute: é a mesma quantidade que a barreira vertical deveria ter estimado desde o início.

**Segunda escolha (se precisar de número antes de medir): horizonte constante em tempo-de-volatilidade.**

```
H_stress = H_base × (σ_base / σ_stress)
```

Com `σ_stress/σ_base ≈ 2`, isso dá `H_stress ≈ H_base/2`. A justificativa é a mesma da literatura de volatility scaling em futuros, onde boa parte do alfa de momentum é atribuível ao escalonamento por volatilidade e não ao sinal cru ([Time series momentum and volatility scaling](https://www.sciencedirect.com/science/article/abs/pii/S1386418116301379)). Registre como `ASSUMED`, com sweep pendente — igual a TP/SL e pelo mesmo motivo.

**O que não recomendo:** um número em milissegundos. A unidade está errada antes do valor (§4.3).

---

### 2.6 Resoluções lentas agora, ou só a mais rápida? — **pré-filtro de custo primeiro; ele provavelmente decide sozinho**

**Recomendação: (a) rode agora o pré-filtro de custo, que não exige rótulo nem backtest; (b) gere histórico de rótulo para a resolução mais LENTA, não só para a mais rápida; (c) rodada 1 com 5 símbolos × {R1, R3}, pulando R2.**

Isso contraria a opção "barata" do brief, e o argumento é aritmético.

**Peça 1 — a resolução não compra amostra.** Com barreira vertical `H` e histórico `T`:

```
n_eff = n_barras × unicidade_média ≈ (T / dur_barra) × (dur_barra / H) = T / H
```

Com `H = 8h` e `T = 1 ano`: `n_eff ≈ 8.760/8 ≈ 1.095`, **em qualquer resolução**. R1 dá ~35.000 barras com unicidade ~1/32; R3 dá ~8.700 barras com unicidade ~1/8. Mesmo número efetivo. E a literatura de concorrência de rótulo é explícita sobre por que a contagem bruta engana: *"Models trained on concurrent observations often show inflated in-sample performance (because they're learning the same patterns multiple times) but poor out-of-sample performance"* ([MQL5, Label Concurrency](https://www.mql5.com/en/articles/19850)). **Rodar na resolução rápida não dá mais dado; dá mais linhas na tabela.**

**Peça 2 — a resolução compra (ou destrói) hurdle de custo.** Com TP=2,0×ATR, SL=1,5×ATR e custo round-trip `c` em unidades de ATR, o win-rate de breakeven é

```
p* = (1,5 + c) / 3,5
```

| `c` (custo/ATR) | `p*` | Comentário |
|---|---|---|
| 0,000 | 42,9% | sem custo |
| 0,110 | 46,0% | custo/ATR de 2021 |
| 0,194 | 48,4% | custo/ATR de 2026 (`E27f`) |
| ~0,097 | 45,6% | mesmo custo, resolução ~4× mais lenta (ATR escala ~√4 = 2×) |

A degradação de custo que a `E27f_cost_atr_ratio` capturou **já consumiu 2,4pp da acurácia exigida**. E operar na resolução mais lenta devolve **2,8pp de hurdle**, de graça. Para um classificador marginal, 2,8pp de acurácia é a diferença entre existir e não existir.

**Peça 3 — o pré-filtro é grátis no orçamento de multiplicidade.** Calcular `c(símbolo, resolução) = custo_round_trip_bps / ATR_bps` para as 15 linhas é aritmética sobre dado existente: não exige ajuste de modelo nem backtest novo. Pela **sua própria convenção (C)**, isso é **1 trial** (passe de ranking que reusa artefato), não 15. Rode primeiro, elimine toda linha cujo `p*` implicado esteja acima do que o Alpha já demonstrou historicamente, e entre na rodada cara só com o que sobrar.

**Consequência:** "rodar só na mais rápida porque é a que tem histórico" otimiza custo de engenharia contra a dimensão com o pior hurdle econômico. Gerar histórico de rótulo para R3 é trabalho mecânico e determinístico; descobrir depois de uma rodada inteira que R1 nunca teve chance contra 48,4% de breakeven é caro.

**Por que pular R2:** com R1 e R3 medidos, R2 é interpolação — triplica trials e não responde nada que os extremos não respondam. Inclua-o só se R1 e R3 divergirem em direção (aí sim é informativo).

---

### 2.7 Meta consome regime? De qual candidato/resolução? — **de nenhum, por ora; se consumir, da mesma linha**

**Recomendação: regime NÃO entra como feature do Meta na primeira versão. Permanece exclusivamente como gate de risco. Se um dia entrar, obrigatoriamente do mesmo `(símbolo, resolução)` e mesmo `method_id` do Alpha que ele filtra.**

Justificativa vinda do seu próprio resultado: os 18 p-valores de permutação ficaram entre 0,30 e 0,85 — **nenhuma célula mostrou heterogeneidade significativa**, incluindo o líder anterior sob I², que se revelou artefato de autocorrelação intra-regime. Esse resultado tem leitura assimétrica que vale tornar explícita:

- **Como feature**, regime precisa de evidência de poder condicional. Você tem evidência de ausência de efeito detectável. Adicioná-lo ao Meta gasta dimensão e multiplicidade num regressor sem sustentação — e o Meta é a camada com **menos** amostra (só os trades que o Alpha propôs).
- **Como gate**, regime não precisa de significância. "Não operar sob stress extremo" é **política de risco**, justificável por preferência do operador e por argumento de cauda, não por p-valor. Um gate não precisa prever; precisa evitar.

Mantenha o `QuantileRegimeClassifier` de produção como fonte de `tradeable` (papel 2) e deixe o papel 1 fora do Meta até existir um teste de resposta condicional positivo — que já é um dos "fix mecânicos" catalogados em §4 do brief.

**As 5 condições de entrada do Meta não mencionarem regime está certo, não é lacuna.** Não adicione uma sexta: amarrar duas decisões independentes torna as duas mais difíceis de reverter.

**Se e quando entrar:** mesma linha, mesmo método, `decode_mode = filter`, identidade de estado canonicalizada (§3.4). Consumir regime de outra resolução cria uma segunda superfície de alinhamento temporal — e o material de apoio registra que um bug de timestamp de join já aconteceu uma vez neste projeto.

---

### 2.8 Redundância entre ~92 features — **clustering hierárquico + importância por cluster dentro do CPCV**

**Recomendação: substitua o corte pareado por um pipeline de 4 passos, e rejeite explicitamente "deixar pro L1/L2 do XGBoost".**

**Por que "deixar pro XGBoost" é a resposta errada:**

- `alpha`/`lambda` no XGBoost regularizam **pesos de folha**, não inclusão de feature. Não existe seleção esparsa de feature em gradient boosting da forma que existe em Lasso.
- Árvores lidam com colinearidade por **substituição arbitrária**: entre duas features quase idênticas, cada split escolhe uma, diluindo a importância de ambas. É o efeito de substituição, e afeta MDI e MDA igualmente: *"Both MDI and MDA are susceptible to substitution effects in the presence of correlated features, and may make both correlated features appear to be irrelevant even if they are critical"* ([mlfinlab, Feature Clusters](https://random-docs.readthedocs.io/en/latest/implementations/feature_clusters.html)).
- Consequência: você não perde só interpretabilidade — perde o **critério de eliminação**, porque a métrica que decidiria quem sai é justamente a que a colinearidade corrompe.

**Por que o corte pareado |Spearman| > 0,70 não escala:** 92 features = 4.186 pares; "sai a de menor importância" é ambíguo quando 3+ features formam cluster mútuo (A~B, B~C, A≁C); e são 4.186 decisões sobre estimativas ruidosas calculadas sobre ~1.100 amostras efetivas.

**Pipeline proposto:**

```
1. MÉTRICA DE DEPENDÊNCIA
   linear:     d(i,j) = sqrt( 0,5 × (1 − ρ_spearman(i,j)) )
   não-linear: variação de informação / informação mútua normalizada
   → calculada SÓ no fold de treino, nunca sobre o dado completo

2. CLUSTERING
   hierárquico sobre d; nº de clusters por ONC
   restrição de domínio obrigatória: features de granularidade diária
   (Grupo H, on-chain, 11 features) formam UM cluster por construção —
   365 valores únicos/ano não sustentam 11 dimensões independentes

3. IMPORTÂNCIA POR CLUSTER (cMDA), dentro do CPCV
   permutar o CLUSTER inteiro, não a feature individual
   → robusto a substituição linear E não-linear

4. DIMENSIONALIDADE EFETIVA
   o modelo é descrito por n_clusters, não por n_features
   gate declarado: n_clusters / n_eff ≤ limiar
```

**A restrição que amarra tudo:** `n_eff ≈ 1.095` rótulos independentes por ano por linha. Com 92 features, ~12 amostras efetivas por feature por ano. Com ~15 clusters, ~73 por cluster. **A política "todas canônicas" está certa em princípio** — o material de apoio tem razão, T1=10 era estipulação, não medição — **mas ela transfere o problema de "quantas features" para "quantos graus de liberdade efetivos", e esse número precisa virar métrica de primeira classe do artefato**, não subproduto.

**Sobre o HHI que o projeto já usa:** mantenha como **diagnóstico de concentração de importância** ("o modelo está apoiado em 3 features ou espalhado em 40?"), não como critério de eliminação. HHI mede concentração, não redundância.

---

### 2.9 A delegação de seleção muda a contagem de trials do DSR? — **reduz a contagem, não reduz o viés**

**Veredito: só move a busca para dentro do modelo. Multiplicidade explícita vira variância de seleção implícita, que o DSR não enxerga.**

Mecanismo:

- Na metodologia antiga, cada `k` testado era um ajuste separado com métrica OOS própria. A busca era **visível**, contável, e o DSR podia deflacionar por ela.
- Na nova, a seleção acontece dentro de um treino regularizado. O número de configurações efetivamente exploradas **não cai** — o boosting continua avaliando splits sobre 92 features em cada nó. O que cai é a **observabilidade** da busca.
- O viés de seleção não desaparece por não ter sido contado. Ele reaparece como otimismo do erro in-sample, invisível para uma métrica que só conhece o `N` que você digitou.

**O que fazer, concretamente:**

1. **Toda busca dentro dos folds.** Seleção de cluster/feature e de hiperparâmetro têm de acontecer **dentro** de cada fold do CPCV (aninhadas), com purge e embargo. Se acontecem uma vez sobre o dado todo e "cada fold usa o resultado", vazou — e nenhuma contagem conserta isso.
2. **Pare de contar `N` à mão; calcule `N_eff`** (registry + clustering das séries OOS, §1.3).
3. **Promova PBO/CSCV a gate primário** — mede overfitting sem exigir contagem de trials, e está confirmadamente não implementado.
4. **Registre a própria mudança de política como trial.** T1-fixo → todas-canônicas é uma decisão tomada sobre dado observado; se os dois regimes forem comparados, são 2 configurações no registry.

**Honestidade sobre o líquido:** a política nova é metodologicamente mais defensável **e** aumenta o risco de overfitting não observável. As duas coisas são verdade simultaneamente. A mitigação não é voltar ao portão humano — é instrumentar a busca.

---

## 3. §7 — Contratos de dado concretos

### 3.0 Espinha dorsal comum (vale para as 11 fronteiras)

Antes dos contratos individuais: quase todo problema que os dois documentos relatam — bug de timestamp de join, `T1_FEATURE_IDS` travado, `REGIME_ONEHOT_LEVELS` hard-coded, paridade treino-live, reprodutibilidade — é resolvido por **quatro invariantes globais**, não por sete contratos separados. Desenhe estes primeiro; os contratos por fronteira ficam curtos depois.

**INV-A — Chave canônica.** Toda tabela é chaveada por `(symbol, resolution, bar_id)`, onde `bar_id` é inteiro monótono por linha. **`bar_id` é a única chave de join; timestamps são payload, nunca chave.** Isso mata por construção a classe de bug de "timestamp de join" que já custou uma execução da Trilha A. Timestamps aparecem como `bar_open_ts_ns` / `bar_close_ts_ns` (int64, UTC, nanossegundos) para auditoria e alinhamento cross-linha, e o mapeamento `ts → bar_id` vive num único módulo.

**INV-B — Proveniência por hash, artefatos imutáveis.** Toda saída de estágio carrega:

```
schema_version    : str     # semver do schema
producer_version  : str     # git sha do código que produziu
config_hash       : str     # blake2b do subtree de config congelado
input_manifest_hash: str    # hash do manifest do estágio anterior
created_at_ns     : int64
```

Caminho: `{stage}/config_hash={h}/symbol={S}/resolution={R}/part-*.parquet` (⟲ V-07 — `config_hash` como chave hive e **acima** das partições, para que uma varredura cubra as 15 linhas da rodada), escrita atômica com `_SUCCESS` como autoridade, nunca sobrescrita. Cada artefato tem `manifest.json` com contagem de linhas, `min/max bar_id`, nulos por coluna e o hash do manifest upstream. **O conjunto forma uma cadeia de hashes — reprodutibilidade vira propriedade estrutural, não disciplina.** É também o que permite o disparo automático de validação (§3.6).

**INV-C — Contrato de causalidade declarado por coluna.** Toda coluna de feature declara:

```
feature_id           : str
formula_version      : str
source_id            : str      # D01..D14, E01, E04...
lookback_bars        : int
availability_lag_ns  : int64    # atraso de publicação da FONTE
causality_class      : {strict_past, at_close, forward_looking}
```

Regras: só `strict_past` e `at_close` podem entrar em matriz de design; `forward_looking` só existe em rótulo. **`availability_lag_ns` não é decorativo** — é o item que a mudança "todas canônicas" torna urgente: o Grupo H (on-chain, granularidade diária) tem lag de publicação real, e juntá-lo ao fechamento da barra sem lag é look-ahead. Hoje nenhum documento especifica esse lag; sob a política nova, 11 features novas entram dependendo dele.

**INV-D — Teste de paridade como CI, não como boa intenção.** Para toda coluna: recomputar `valor(t)` sobre dado truncado em `bar_close_ts(t)` deve bater com o valor armazenado, sob a classe de paridade declarada da coluna. ⟲ **V-04:** exigir `==` em float64 para tudo é uma spec que falha de forma intermitente e acaba desativada — o pior desfecho para um teste de vazamento. Duas classes, declaradas no `registry.yaml` por feature: **`parity_class: exact`** (índices, postos, contagens, o percentil expansivo via Fenwick — comparação `==`, sem tolerância) e **`parity_class: tolerance`** (reduções em ponto flutuante, cuja ordem de agregação varia com chunking e número de threads) com **orçamento em ULP declarado por feature**. Uma feature sem `parity_class` declarada não entra no `feature_manifest`. Um único teste genérico parametrizado sobre o `feature_manifest` cobre as 92 features e todas as fronteiras. É a mesma disciplina que os feature stores de produção formalizam: *"failing to implement proper point-in-time retrieval introduces future data leakage into training features"*, e o objetivo do store é servir em produção exatamente os valores usados no treino ([apxml, Diagnosing and Mitigating Online/Offline Skew](https://apxml.com/courses/feature-stores-for-ml/chapter-3-data-consistency-quality/diagnosing-mitigating-skew)).

> **Nota de escopo honesta:** os schemas abaixo são desenho a partir de prática padrão + restrições declaradas nos seus documentos, não auditoria do seu código (que não vi). Onde eu precisaria de informação do repositório para ser preciso, marco `[PRECISO SABER]`.

---

### 3.1 Features → Label

**Problema real da fronteira:** hoje é "loosely acoplado" — o Label Engine lê ATR do Feature Engine sem contrato. O risco não é o acoplamento; é que features e rótulos passam a **co-evoluir**: mexer numa feature invalida rótulos sem que nada detecte.

**Regra central: o Label Engine consome uma *view* declarada, não a tabela de features.**

```
label_inputs(
  symbol, resolution, bar_id, bar_close_ts_ns,
  open, high, low, close,          # do bar builder, NÃO do feature engine
  atr_value,                       # o ÚNICO escalar de feature admitido
  atr_feature_id, atr_config_hash  # proveniência do escalar
)
```

Por que exatamente uma feature: se o Label Engine puder ler o catálogo inteiro, você perde a capacidade de trocar features sem re-rotular. Com a política "todas canônicas", isso passaria a acontecer o tempo todo.

**Saída:**

```
labels(
  symbol, resolution, bar_id,           # = t0, evento
  side              : {long, short},
  t1_bar_id         : int,              # barra de saída
  t1_ts_ns          : int64,
  barrier           : {tp, sl, vertical},
  entry_ref_px      : float,
  tp_px, sl_px      : float,
  atr_value         : float,
  horizon_bars_used : int,
  ret_gross         : float,
  cost_bps_assumed  : float,            # <-- entra no hash do rótulo
  ret_net           : float,
  y                 : int8,             # 1 sse barrier == tp
  fill_model        : {assumed_immediate, queue_model},
  label_config_hash : str
)
```

**Cinco cláusulas que mudam decisão:**

1. **`horizon_bars`, não `time_stop_ms`.** A barreira vertical é contada em barras da própria resolução. `time_stop_ms` sobrevive só como diagnóstico derivado. Motivo em §4.3; a prática recomendada em rotulagem sobre barras de informação é definir a vertical como número fixo de barras, alinhando o rótulo com a **chegada de informação** e não com o relógio.
2. **`cost_bps_assumed` dentro do rótulo, e dentro do hash.** Assim, mudar o modelo de custo **invalida os rótulos** — que é o comportamento correto. É a automação da história `E27f` (custo/ATR 11% → 19,4%): hoje essa deriva foi descoberta por análise humana; com o custo no hash, ela vira quebra de cadeia detectada pelo pipeline.
3. **`y` explicitamente definido, e time-stop declarado.** `y = 1` sse `barrier == tp`. Rótulos `vertical` recebem `y = 0` — mas registre também `y_ternary` para análise, porque essa escolha muda a taxa-base materialmente e ninguém deve descobrir isso lendo código.
4. **`entry_ref_px` + `fill_model` desde o dia 1.** Fase 1 usa `assumed_immediate`. A coluna existe para que, quando o modelo de fila chegar (é pré-requisito do Meta), a re-derivação sob `queue_model` não seja migração de schema. Ver §4.4 para por que isso não é preciosismo.
5. **Causalidade:** `atr_value(t)` é `at_close(t)`; barreiras derivam de `close(t)` e `atr_value(t)`; a **avaliação** das barreiras percorre `(t, t+H]` usando `high/low` de barras estritamente posteriores. `labels` é a única tabela do sistema com `causality_class = forward_looking`.
6. **Regra de colisão intra-barra — ⟳ AC-02 / X-05, lacuna real na versão anterior deste contrato.** Se numa mesma barra `high ≥ tp_px` **e** `low ≤ sl_px`, qual barreira foi tocada primeiro é **indeterminado sem dados de tick**. Isto não é detalhe: com TP a 2,0×ATR e SL a 1,5×ATR sobre barras de ~15min-equivalente, colisão é comum sob stress, e a convenção escolhida desloca a taxa-base — que é exatamente a quantidade comparada contra o breakeven de 48,4% (§2.6). Contrato: campo `barrier_collision_rule ∈ {conservative_sl, tick_resolved}` no `config.json` (dentro do hash), coluna `collision: Boolean!` na tabela, e `collision_rate` em `column_stats` como gate de deriva. Default `conservative_sl` (pior caso), **e a taxa é reportada** — se for alta, a geometria precisa de dados de tick, não de convenção.

---

### 3.2 Label → Pesos

```
weights(
  symbol, resolution, bar_id,
  concurrency        : int,
  avg_uniqueness     : float,
  w_return_attrib    : float,
  w_time_decay       : float,
  w_final            : float,
  concurrency_scope  : {line, symbol, pooled},
  weights_scope      : {fold}          # recomputado DENTRO de cada fold
)
```

**A resposta à pergunta de §7 ("verificar se está alinhado com todas-canônicas"): está — os pesos dependem de rótulos, não de features. O acoplamento real é outro, e é mais importante.**

Duas cláusulas novas exigidas pela mudança multi-linha:

1. **`concurrency_scope`.** Concorrência é calculada sobre a união dos intervalos `[t0, t1]` abertos. Quando mais de uma resolução do **mesmo símbolo** está no pool de treino, a união tem de ser **por símbolo** — senão você conta o mesmo caminho de preço duas vezes e infla a amostra efetiva exatamente onde ela é mais escassa. Default recomendado: `symbol`.
2. ⟳ **X-11 — separar `WeightBasis` de `FoldWeights`.** A tem razão de que a ordem desenhada (Label → Pesos → Split) contradiz o invariante `weights_scope = fold`, e de que remendar com um campo de escopo é pior do que separar os dois objetos:

```
Label  →  WeightBasis   (event_start_ts, event_end_ts, return_magnitude — fatos do RÓTULO,
                         independentes do split)
       →  Split
       →  FoldWeights   (concurrency, avg_uniqueness, w_final — quantidades que só existem
                         DADO um fold; concorrência contada só sobre eventos de TREINO)
```

A separação torna o erro inexprimível, em vez de proibido por convenção. `concurrency_scope` permanece, agora como campo de `FoldWeights`.

3. **`n_eff` como métrica de primeira classe do artefato.**

```
n_eff = (Σ w_final)² / Σ w_final²
```

Este é o número que amarra a política de features à realidade: o Learner deve **recusar treinar** quando `n_clusters_features / n_eff` cruzar um limiar declarado. É assim, concretamente, que "todas canônicas" toca esta fronteira — não pela lista de features, mas pelo orçamento de graus de liberdade contra uma amostra efetiva que **não cresce** quando você adiciona features nem quando muda de resolução (§2.6).

---

### 3.3 Pesos → Split

```
splits(
  split_id           : str,        # IDÊNTICO em todas as linhas da rodada
  fold_id            : int,
  group              : {train, test, purged, embargo, holdout},
  t_start_ns, t_end_ns : int64,    # definidos no CALENDÁRIO MESTRE
  symbol, resolution,
  bar_id_start, bar_id_end : int,  # projeção do intervalo na linha
  purge_basis        : {t1},
  embargo_bars       : int,
  holdout_locked_until_ts : int64
)
```

**A cláusula que hoje falta e que invalida comparação entre linhas:** as fronteiras de fold têm de ser definidas num **calendário mestre em UTC**, único, e depois **projetadas** para `bar_id` de cada linha. Se cada linha define seus folds sobre o próprio índice de barras, o fold 3 de `BTCUSDT:R1` cobre um período diferente do fold 3 de `ETHUSDT:R3` — e comparar os DSRs deles é comparar períodos diferentes, não estratégias diferentes. Como o mandato é **selecionar entre linhas**, essa é a cláusula que torna a seleção estatisticamente válida. Ela não existe hoje em lugar nenhum dos dois documentos.

Outras cláusulas:

- **Purge sobre `t1`** (fim do rótulo), não sobre `t0`; embargo **em barras**, com piso `embargo_bars ≥ max(horizon_bars)` mais uma fração fixa. O propósito é o padrão de CPCV: remover observações sobrepostas e adicionar buffer temporal ([Purged cross-validation](https://en.wikipedia.org/wiki/Purged_cross-validation)).
- **Pesos recomputados dentro do fold** (`weights_scope = fold`): a concorrência muda na fronteira do fold, e usar pesos globais reintroduz informação do teste.
- **Holdout travado** é parte do artefato de split, não convenção verbal: `holdout_locked_until_ts` e um contador de desbloqueios. Todo desbloqueio é um evento no `trial_registry`.
- **Purge cross-símbolo quando houver pool.** Se linhas de símbolos diferentes forem treinadas juntas, rótulos de BTC e ETH que se sobrepõem no tempo compartilham o mesmo choque de mercado; o purge tem de ser aplicado sobre o intervalo temporal, não por símbolo isoladamente.

> **Nota factual (2026-08-21):** o desenho de embargo acima — campo `embargo_bars` no pseudocódigo de `splits(...)`, e a frase "embargo **em barras**, com piso `embargo_bars ≥ max(horizon_bars)`" — é o texto original deste parecer (2026-08-19) e ficou **SUPERSEDIDO** pela implementação real desde `AG-032`/E1 (2026-08-16): `embargo_ms`, relógio fixo **medido** (não derivado de `horizon_bars`), valor de produção `347.010.000 ms` (≈96,39h), deliberadamente invariante a `tf`/densidade de barra — ver `config/constants.yaml::cpcv_embargo_ms` e `src/validation/cpcv.py`. Mantido acima sem edição por rastreabilidade do parecer original; não é o desenho implementado.

---

### 3.4 Split → Learner (inclui o contrato de Regime, que §7 não lista)

**Matriz de design:**

```
design_matrix(
  symbol, resolution, bar_id, side,
  <colunas de feature, ordem definida pelo feature_manifest>,
  regime_dummy_1..K-1,
  design_hash : str      # hash da lista ORDENADA de feature_id@version + níveis de regime
)
```

**Cláusula 1 — nada de lista hard-coded.** As colunas vêm de um `feature_manifest` versionado; o artefato carrega `design_hash`. Isso resolve, de uma vez, `T1_FEATURE_IDS` travado nas 10 antigas e `DESIGN_COLUMNS` montado a partir de tupla literal. A política "todas canônicas" vira uma troca de manifest, não uma edição de código — que é o que a torna reversível.

**Cláusula 2 — o contrato de Regime, que precisa existir e não existe:**

```
regime(
  symbol, resolution, bar_id,
  method_id          : str,       # baseline_quantile | hmm_k3 | bocpd | ...
  method_config_hash : str,
  state_id           : int,       # 0..K-1, CANONICALIZADO (ver abaixo)
  K                  : int,
  state_label        : str,       # rótulo legível, derivado, nunca chave
  tradeable          : bool,      # papel 2 — o GATE
  p_state            : float[K] | null,
  state_age_bars     : int,
  decode_mode        : {filter, smooth}
)
```

Duas regras duras:

- **`decode_mode` obrigatório e verificado.** Só `filter` pode ser consumido pelo Learner ou pelo Gate. Isso transforma a discussão sobre o Jump Model (`.predict()` faz DP com traceback a partir da última barra do fold) de argumento em **falha de contrato**: ele simplesmente não consegue emitir `filter`, e é rejeitado mecanicamente. Muito melhor do que depender de um revisor lembrar do problema.
- **Identidade de estado canonicalizada.** Antes do one-hot, os estados são ordenados por uma estatística monótona declarada — por exemplo, volatilidade realizada média dos membros do estado **no fold de treino**, ascendente. Sem isso, `state_id = 2` significa coisas diferentes em folds diferentes: modelos de mistura/HMM são invariantes a permutação de rótulos, *"the permutation invariance of hidden state labels means different state labelings yield the same likelihood value"*, e a solução padrão é uma **restrição de ordenação** sobre os parâmetros de estado ([label switching em HMM, ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0378375808004217); [Springer, identifiability in HMM](https://link.springer.com/article/10.1007/s40300-019-00156-3)). **Isto não está tratado em nenhum dos dois documentos e afeta HMM k=2/3/4 diretamente, além dos `n_canonical_buckets=3` do BOCPD.** Sem canonicalização, a coluna one-hot de regime é ruído estruturado — o que, aliás, é uma explicação candidata para parte do resultado nulo da Trilha A que vale testar antes de arquivar o estudo.

**Cláusula 3 — codificação one-hot com nível de referência declarado.** `K−1` dummies e `reference_level` explícito no manifest. Defeito concreto no código citado no §10 do brief:

```python
REGIME_ONEHOT_LEVELS: tuple[str, ...] = ("R2", "R3", "R4", "R5")
```

com regimes `R0..R5` e `R1-R4` tradeable, isso deixa **R0 (warmup) e R1 (tradeable) colapsados no mesmo nível de referência**. Se as linhas R0 não forem excluídas do treino, o modelo não consegue distinguir warmup de um regime operável — e o coeficiente de referência mistura os dois. `[PRECISO SABER]`: as linhas R0 são filtradas antes do fit? Se sim, é inofensivo e vale um comentário; se não, é viés real. Independentemente disso, a tupla literal quebra assim que o método vencedor não for o baseline (HMM k=3 não tem "R2").

**Cláusula 4 — quantas camadas? Recomendo 3, não 5.**

```
1. classificador primário binário   (por lado, por linha)
2. calibração                       (estágio próprio, §3.5)
3. meta-label                       (§3.7)
```

Tudo o mais — seleção de cluster de feature, hiperparâmetros — é **busca aninhada dentro dos folds**, não camada de pipeline. Justificativa quantitativa: cada estágio ajustado sobre dados adiciona uma superfície de multiplicidade contra a **mesma** amostra efetiva de ~1.095 rótulos/ano. Cinco camadas empilhadas não são identificáveis com esse orçamento. A pergunta de §7 ("quantas camadas são realmente necessárias sob todas-canônicas") tem resposta invertida em relação à intuição: a política nova de features **reduz** o número de camadas justificáveis, porque consome graus de liberdade que antes sobravam.

---

### 3.5 Learner → Calibração — **separar. Não manter inline.**

```
calibrated_scores(
  symbol, resolution, split_id, fold_id, bar_id, side,
  p_raw               : float,
  p_cal               : float,
  calibrator_id       : {platt, beta, isotonic},
  calibrator_config_hash : str,
  n_cal_eff           : float,      # amostra EFETIVA usada na calibração
  inner_fold_id       : int
)
```

**Três razões para separar, em ordem de força:**

1. Calibração inline quase sempre acaba reusando o fold de treino (otimista) ou tocando o fold de teste (vazamento). Como estágio próprio com **fold interno dedicado** (CPCV aninhado, purgado e embargado contra treino e teste externos), a regra fica verificável.
2. O **Brier score é condição de entrada do Meta**. Uma condição de gate precisa de artefato auditável, não de um número calculado dentro de outro estágio.
3. O mandato é **rodadas periódicas de re-seleção**. Separar permite recalibrar sobre dado novo sem refitar o learner — que é a operação mais frequente e mais barata do ciclo.

**Método recomendado: Platt/sigmoid (ou beta), não isotônica.** Motivo direto de amostra: a isotônica *"is more prone to overfitting, and thus performs worse than Platt Scaling, when data is scarce"*; a regra prática usual é Platt abaixo de ~1k rótulos, isotônica acima de ~10k ([scikit-learn, Probability calibration](https://scikit-learn.org/stable/modules/calibration.html)). Com `n_eff ≈ 1.095/ano/linha` e a calibração usando um subconjunto disso, você está estruturalmente no regime "escasso". Torne isso um gate: `if n_cal_eff < limiar: proibir isotonic`.

---

### 3.6 Calibração → Validação — **validação é função sobre artefatos, disparada por hash, não script agendado**

```
validation_report(
  line_id, split_id,
  design_hash, label_config_hash, learner_config_hash, calibrator_config_hash,
  metrics {
    sharpe_oos, dsr, pbo, brier, logloss,
    n_eff, turnover, cost_bps_realized, breakeven_wr_implicito
  },
  trials {
    n_trials_registered, n_eff_trials, cluster_assignment
  },
  verdict : {PASS, FAIL, INCONCLUSIVE},
  reasons : [str],
  drop_rate_by_reason : {str: float}     # ⟳ X-08
)
```

**Gates de promoção — quatro, rígidos e pré-registrados (⟳ adotado de C):**

| Métrica | Aprovação | Falha |
|---|---|---|
| DSR (ajustado por `N_eff` dos retornos OOS) | `p < 0,05` | rejeição da linha |
| PBO (CSCV) | `< 0,30` | rejeição da linha |
| Monotonicidade de folds | `Sharpe_OOS > 0` em `≥ 70%` dos caminhos | rejeição por instabilidade |
| Brier calibrado | `< Brier_climatológico` | bloqueio na calibração |

Quatro gates rígidos, e **nenhum nível intermediário**: um `MARGINAL` que entra com peso reduzido é um limiar negociável depois de ver o resultado, o que reintroduz a seleção que os gates existem para conter.

**`N_eff` por decomposição espectral (⟳ adotado de C, com a citação corrigida):** estimar o número efetivo de trials independentes dos autovalores da matriz de correlação das séries de retorno OOS do `trial_registry` é determinístico e sem hiperparâmetro — preferível ao clustering ONC que eu havia proposto. Atenção à fonte: Li & Ji (2005) somam os autovalores **substituindo por 1 os maiores que 1** ([Heredity 95:221-227](https://www.nature.com/articles/6800717)); a razão de participação `(Σλ)²/Σλ²` é um estimador **diferente**, e dá número diferente na mesma matriz. Reporte os dois lado a lado e declare qual governa o gate.

**A resposta à pergunta "quando/como a validação roda automaticamente":** ela é **endereçada por conteúdo**, não agendada. ⟲ **V-03 — e aqui a primeira versão desta proposta tinha um buraco:** enumerar hashes (`design_hash`, `label_config_hash`, `learner_config_hash`, `calibrator_config_hash`) **omite** os configs de `weights/` e de `regime/`. Trocar `concurrency_scope` de `line` para `symbol` muda os pesos, muda o treino, e **não** mudaria a chave — validação obsoleta seria reusada, que é exatamente a falha que este mecanismo existe para impedir. A chave correta é transitiva, não enumerada:

```
validation_key = blake2b( content_hash(calibrated_scores) ‖ split_id )
```

`content_hash` já encadeia todo o DAG upstream via `input_manifest_hash`, então nenhuma config pode ficar de fora por esquecimento. Regra geral que vale além deste caso: **chave de cache derivada de enumeração de dependências apodrece; chave derivada do conteúdo, não.**

O orquestrador calcula a chave; se não existe `validation_report` com ela, **a promoção fica bloqueada** e a validação roda. Consequências desejáveis:

- Impossível promover um modelo cuja validação corresponde a outra configuração.
- Mudar o modelo de custo (`cost_bps_assumed`) invalida o rótulo, que invalida o treino, que invalida a validação — automaticamente, pela cadeia de hashes de INV-B.
- Reexecutar sem mudar nada é gratuito (cache hit), o que remove o incentivo a pular validação.

**Cláusula acoplada — `trial_registry` append-only.** Todo `fit` grava `(config_hash, split_id, timestamp, série de retorno OOS)`. É o substituto automático do `N_lifetime` descomissionado, e é o que permite calcular `n_eff_trials` por clustering (§1.3, §2.9) em vez de lembrar um número.

**`breakeven_wr_implicito` como métrica de primeira classe:** `p* = (sl_mult + c)/(tp_mult + sl_mult)`, com `c` medido, não assumido. Uma linha cujo `p*` está acima da acurácia que ela mesma atingiu é reprovada por aritmética, antes de qualquer discussão sobre DSR.

---

### 3.7 Validação → Meta-Model — **desenho completo**

```
meta_training_set(
  line_id, bar_id, side,
  p_cal              : float,   # OUT-OF-FOLD, obrigatoriamente
  exec {
    spread_bps, book_imbalance, dist_to_touch_ticks,
    queue_pos_est, fill_prob_est, cost_est_bps, adverse_sel_est
  },
  regime_state_id    : int | null,   # default: null (ver §2.7)
  state_age_bars     : int | null,
  fill_assumed       : bool,
  y_meta             : int8
)
```

**Seis cláusulas:**

1. **`p_cal` tem de ser out-of-fold.** O Meta nunca pode ver probabilidades in-sample do primário. É a forma mais comum de vazamento em meta-labeling e merece ser cláusula, não convenção.
2. **`y_meta = 1` sse `ret_net > 0`** — líquido de fees, funding e slippage. Com custo/ATR em 19,4%, um meta treinado sobre retorno bruto aprende a aprovar trades que perdem depois de custos. Não é academicismo: é 5,5pp de win-rate.
3. **O Meta dimensiona ou veta; nunca inverte lado.** Meta-labeling clássico. Se ele pudesse inverter, seria um segundo primário e a contagem de trials dobraria.
4. **`fill_assumed` explícito.** Enquanto o modelo de fila não existe, a população é "todos os sinais", não "os sinais que teriam sido preenchidos". A coluna torna a diferença auditável e a migração posterior verificável — ver §4.4, que é a razão pela qual isso importa mais do que parece.
5. **Regime default `null`** (§2.7). Se ativado: mesma linha, mesmo `method_id`, `decode_mode = filter`, `state_id` canonicalizado.
6. **Amostra:** o Meta treina só sobre eventos em que o primário sinalizou. Com `n_eff ≈ 1.095/ano` e uma taxa de sinal de, digamos, 20%, o Meta tem `n_eff ≈ 220/ano`. **Isso precisa aparecer explicitamente na condição "amostra efetiva mínima" das 5 condições de entrada** — e sugere que o Meta só se torna viável com pool cross-símbolo, o que por sua vez exige o purge cross-símbolo de §3.3. `[PRECISO SABER]`: a condição de amostra mínima do Meta está expressa em número de trades ou em amostra efetiva? Se for em trades brutos, está superestimando em ~5×.

---

### 3.8 As fronteiras que §7 não lista — as que tocam dinheiro

**(a) Meta → Decision Engine**

```
trade_intent(
  intent_id        : uuid,    # chave de idempotência; vira newClientOrderId
  snapshot_id      : uuid,    # ⟳ X-01 — a ÚNICA âncora de linhagem da decisão
  bundle_id        : str,     # ⟳ X-03 — qual conjunto de artefatos produziu isto
  line_id, symbol, side,
  target_notional  : float,
  entry_ref_px, limit_px : float,
  tif              : "GTX",
  expires_at_ns    : int64,   # o timeout de cancelamento
  max_horizon_bars : int,
  sl_px, tp_px     : float,
  p_cal, p_meta    : float,
  regime_state_id  : int | null,
  risk_budget_bps  : float,
  reason_codes     : [str]
)
```

**(b) Decision Engine → Risk.** O Risk devolve `{approve | resize | reject | kill}` + `reason_code`, e deve ser **função pura** de `(intent, portfolio_state_snapshot, config)`. Pureza aqui não é elegância: é o que permite replay determinístico e teste offline da camada de risco sem exchange.

⟳ Invariante adotado de A, que o formula melhor do que eu: **o Risk pode dizer APPROVE / RESIZE / REJECT / KILL, mas não pode descobrir uma nova tese direcional.** Isso também refuta a proposta de B de inverter a seta (Risk → Decision): não se aprova o que ainda não existe. A estrutura é de duas fases — Decision propõe, Risk aprova/redimensiona/rejeita, Decision finaliza.

**Estado de linha vs. exposição de símbolo (⟳ X-04 + N-01).** A máquina de estados de A é superior ao meu booleano de reserva, mas a chave dela está errada:

```
LineState      (lógico, chave = line_id): FLAT | ENTRY_PENDING | OPEN | EXIT_PENDING | RECONCILIATION
SymbolExposure (físico, chave = symbol) : net_qty, entry_px, margem — o que a exchange reporta

INVARIANTE: no máximo UMA linha por símbolo em estado ≠ FLAT
            (salvo com SymbolAggregator — §1.2 opção ii)
```

`EXIT_PENDING` é um estado que eu não tinha e que importa sob post-only: a saída também fica pendente, e uma entrada nova durante ela é um erro de classe diferente de uma entrada durante `ENTRY_PENDING`.

**Regra de priorização entre linhas concorrentes** (o achado do material de apoio, aqui resolvido): dentro de um mesmo batch de fechamento de barra, as intenções são ordenadas por **edge líquido esperado por unidade de risco**

```
score = (p_meta × payoff_esperado_liquido) / stop_dist
```

com desempate determinístico por `line_id` (ordem lexicográfica). Duas propriedades importantes: é replayable (mesma entrada ⇒ mesma ordem) e não é first-come-first-served (que dependeria de latência de rede e tornaria o backtest não reproduzível). **Melhor ainda:** se `INV_4` de §2.2 estiver ativo (risco dividido por número de posições), a corrida perde a maior parte da importância — as duas linhas entram, cada uma com metade do risco, e não há disputa binária.

**(c) Risk → Execução.** `order_request` com campos nativos da exchange + o invariante: o **mesmo `intent_id` nunca produz duas ordens vivas**, garantido por `newClientOrderId = intent_id` (a Binance rejeita o duplicado). É a implementação concreta da cláusula 2 de §1.2.

**(d) Execução → Ledger/Label (o loop que fecha).** `fill_events` alimenta duas coisas:

1. o ledger local de posição (§2.1);
2. a série de **custo realizado**, que é comparada continuamente com `cost_bps_assumed` gravado nos rótulos (§3.1). Divergência acima de um limiar dispara invalidação da cadeia de hashes. **Isto automatiza exatamente o achado que produziu a `E27f`** (custo/ATR de 11,0% → 19,4% entre 2021-2026): hoje esse tipo de deriva é descoberto por análise humana esporádica; com o loop fechado, ele vira alarme.

---

### 3.9 Cadência da rodada de seleção (achado do material de apoio, aqui respondido)

**Recomendação: cadência dirigida por acúmulo de amostra efetiva, não por calendário.**

```
disparar nova rodada quando QUALQUER uma:
  (i)  n_eff_novo_desde_ultima_rodada  ≥  0,25 × n_eff_treino_da_rodada_vigente
  (ii) breach de um invariante de risco (INV_1..INV_4) em janela móvel
  (iii) divergência custo_realizado vs cost_bps_assumed acima do limiar (§3.8d)
  (iv)  teto: 12 meses desde a última rodada
```

Com `n_eff ≈ 1.095/ano`, o critério (i) dá aproximadamente uma rodada por **trimestre** — mas deriva do dado, não de um número escolhido. E cada rodada é registrada como um **lote de trials** no registry, o que faz a cadência entrar automaticamente no orçamento de multiplicidade: rodar mais vezes custa poder estatístico, e o custo fica visível em vez de implícito.

---

## 4. Achados não cobertos por nenhum dos dois documentos

O material de apoio pede explicitamente por esta categoria e cita 2 exemplos próprios (cadência da rodada, priorização entre linhas — ambos respondidos em §3.9 e §3.8b). Os abaixo são novos.

### 4.1 O modelo de posição da exchange é incompatível com a abstração "linha" — **P0**

Já detalhado em §1.2. Registro aqui porque é achado, não só contestação: **nenhum dos dois documentos menciona position mode, netting, ou o fato de que `(símbolo, resolução)` não existe do lado da Binance.** A abstração central da refatoração multi-ativo não tem contraparte no sistema onde o dinheiro vive.

---

### 4.2 Capital de R$ 1.000 vs. granularidade de lote — **P0, e muda o desenho do Risk Engine**

Nenhum dos dois documentos menciona `minNotional`, `stepSize` ou tamanho mínimo de ordem. Dados medidos ao vivo (2026-08-19):

| Símbolo | Preço | `minNotional` | `stepSize` | Notional por 1 step | Ordem mínima viável |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 69.262,40 | 50 USDT | 0,001 BTC | **69,26 USDT** | 69,26 USDT |
| ETHUSDT | 2.253,54 | 20 USDT | 0,001 ETH | 2,25 USDT | 20,28 USDT |
| BNBUSDT | 626,17 | 5 USDT | 0,01 BNB | 6,26 USDT | 6,26 USDT |
| SOLUSDT | 84,71 | 5 USDT | 0,01 SOL | 0,85 USDT | 5,08 USDT |
| XRPUSDT | 1,1107 | 5 USDT | 0,1 XRP | 0,11 USDT | 5,11 USDT |

Capital: R$ 1.000 ÷ 5,1812 = **193 USDT**.

**Premissas declaradas para a aritmética** (não medi seus dados; troque pelos reais): ATR de uma barra R1 ≈ 0,35% do preço em regime normal, ≈ 1,2% sob stress. Risco-alvo por trade 0,65% do equity (⅓ do teto diário de 2%).

**(a) A grade de sizing em BTC tem ~3 níveis.** Risco-alvo = 1,25 USDT; stop = 1,5 × 0,35% = 0,525%; notional necessário = 239 USDT = **3,45 steps de BTC**. Você pode operar 3 steps (risco 1,09) ou 4 (risco 1,45) — erro de ±15% no alvo de risco. Em termos de risco, **1 step de BTC = 0,19% de equity**, então entre 0 e o alvo de 0,65% existem 3,4 níveis discretos. Qualquer regra de vol-targeting, Kelly fracionário ou risco-paridade colapsa nesses 3 níveis. **Um backtest que assume sizing contínuo não é reproduzível ao vivo em BTC.** Isso é quebra de paridade treino-live na camada de sizing, e o §7 não tem contrato para ela.

**(b) A precisão de sizing difere ~24× entre símbolos.** 1 step de risco: BTC = 0,19% do equity; SOL = 0,008%. O mesmo algoritmo de sizing entrega risco efetivo muito mais preciso em SOL/XRP do que em BTC. Numa rodada de seleção que compara linhas, isso é um **viés sistemático a favor dos símbolos de grade fina**, não uma diferença de edge. Precisa entrar como covariável ou como ajuste, senão a seleção mede granularidade de lote.

**(c) Sob stress, a posição BTC mínima já consome um terço do orçamento diário.** Stop = 1,5 × 1,2% = 1,8%; perda na posição mínima = 69,26 × 1,8% = **1,25 USDT = 0,65% do equity**. Teto diário = 3,86 USDT ⇒ **~3 stops de tamanho mínimo esgotam o dia**, e **não existe tamanho menor**. O Risk Engine precisa de um estado explícito "símbolo intratável no orçamento atual" — hoje ele não tem, e sem ele o comportamento é rejeitar a ordem no envio (erro da exchange), o que é a pior forma de descobrir isso.

**(d) Alavancagem implícita do cap.** 239 USDT de notional por posição sobre 193 de equity = 1,24×; duas posições = 2,5×; cinco = 6,2× em margem cruzada com ρ ≈ 0,8. Corrobora §2.2 por um caminho independente.

**Recomendação:** o Risk Engine deve **quantizar antes de decidir**, não depois — calcular `qty` factível, recalcular o risco real dessa `qty`, e só então aprovar/rejeitar. E o backtest tem de aplicar exatamente a mesma quantização, pelo mesmo código.

---

### 4.3 Barreira vertical em milissegundos sobre relógio de dollar bar — **P1**

`time_stop_ms = 28.800.000` é tempo de relógio. As barras são amostradas por volume monetário. Consequência: cada rótulo cobre um **número diferente de barras**, e portanto uma quantidade diferente de informação — que é precisamente o que a amostragem por dollar bar existe para normalizar. Em períodos calmos, 8h pode ser 8 barras; sob stress, 60. O rótulo deixa de ser homogêneo justamente ao longo da dimensão que o resto do sistema trata como eixo (regime).

A prática recomendada em rotulagem sobre barras de informação é definir a vertical como número fixo de barras, alinhando o rótulo com a **chegada de informação** e não com o relógio arbitrário. Correção: `time_stop_bars` é canônico; `time_stop_ms` vira diagnóstico derivado. Isso também resolve §6.5 de graça (§2.5) e é uma das cláusulas do contrato Features→Label (§3.1).

Nota adicional: o brief classifica `time_stop_ms` como `DERIVED` ("reexpressão de unidade de um valor original também `ASSUMED`"). A reexpressão de unidade foi feita **na direção errada** — de barras (ou de dias) para milissegundos. `DERIVED` está formalmente correto e materialmente enganoso, porque sugere que o valor foi obtido de algo medido.

---

### 4.4 As entradas maker são adversamente selecionadas — a população rotulada ≠ população executável — **P1**

Nenhum dos dois documentos trata disso, e ele contamina o Alpha, não só o Meta.

Com entrada post-only, sua ordem é preenchida **quando o preço vem até você** — o que é negativamente correlacionado com o movimento favorável imediato. Evidência direta, e sobre o mesmo mercado que você opera (perpétuo de Bitcoin na Binance): *"We document a fundamental trade-off: a negative correlation between maker fill likelihood and post-fill returns. This dictates that viable maker strategies often require a contrarian approach, counter-trading the prevailing order book imbalance."* ([The Market Maker's Dilemma, arXiv 2502.18625](https://arxiv.org/abs/2502.18625)). E o viés de estimação também é conhecido: *"if a buy limit order doesn't get filled, the price has typically moved higher by time h"*.

Consequência concreta: os rótulos são computados sobre **todos** os eventos `t0`, assumindo entrada. Ao vivo, você só participa do subconjunto que preencheu — e esse subconjunto é enviesado contra você. O Alpha é treinado numa população que não é a que ele vai operar. Isso não é o que o Grupo J / modelo de fila resolve: o Grupo J é feature do **Meta**; aqui o problema está na **definição da amostra do primário**.

**O que fazer sem construir o modelo de fila agora:** (i) a coluna `fill_model` / `fill_assumed` existe desde o dia 1 (§3.1, §3.7), então a mudança futura é auditável e não é migração; (ii) mais barato e imediato — meça a taxa de fill histórica implícita: para cada `t0`, verifique se `limit_px` foi tocado dentro da janela de timeout usando `low/high` das barras subsequentes. Isso é computável hoje sobre dados que você já tem, dá um `fill_flag` aproximado, e permite **reponderar ou filtrar a amostra de treino** antes de qualquer modelo de fila existir. Se a taxa de fill for baixa e correlacionada com o sinal, esse é um achado maior do que qualquer coisa em §5.3.

---

### 4.5 `n_eff` é invariante à resolução — **P1, muda a estratégia de rodada**

Detalhado em §2.6. Registro como achado porque o brief trata multi-resolução como eixo de busca com custo de engenharia, sem notar que ele **não adiciona amostra efetiva**. O eixo compra: escala de medição das features, turnover e hurdle de custo. Não compra estatística. Isso reordena a prioridade entre §6.6 e o resto.

---

### 4.6 Identidade de estado do regime não é canonicalizada — **P1**

Detalhado em §3.4, cláusula 2. HMM e modelos de mistura são invariantes a permutação de rótulos; refits por fold de walk-forward podem trocar a numeração dos estados. Se as dummies de regime são construídas a partir de `state_id` sem ordenação imposta, a mesma coluna significa coisas diferentes em folds diferentes — ruído estruturado apresentado ao modelo como feature. **Hipótese testável e barata: parte do resultado nulo da Trilha A pode ser artefato disso.** Vale verificar antes de arquivar o Estudo 1: para cada fold, ordene os estados por volatilidade realizada média e cheque se a atribuição de índice muda entre folds. Se mudar, os testes de heterogeneidade foram feitos sobre rótulos embaralhados.

---

### 4.7 Nível de referência do one-hot de regime mistura warmup com regime operável — **P2**

`REGIME_ONEHOT_LEVELS = ("R2","R3","R4","R5")` com regimes `R0..R5` deixa R0 (warmup) e R1 (tradeable) no mesmo nível de referência. `[PRECISO SABER]` se as linhas R0 são filtradas antes do fit. Se não forem, é viés real e silencioso. Independentemente disso, a tupla literal quebra assim que o método vencedor não for o baseline.

---

### 4.8 Funding não aparece no modelo de custo — **P2**

Nenhum dos dois documentos menciona funding. Ele é proporcional ao **tempo de holding**, e portanto é a única componente de custo que o gatilho (D) de fato altera. Medido agora em BTCUSDT: 0,83 bps por período de 8h, contra 4,0 bps de round-trip maker. É ~17% do custo de transação num holding de 8h — pequeno, mas não desprezível, e com sinal variável (pode ser crédito). Precisa entrar em `cost_bps_assumed` (§3.1) com o horizonte como multiplicador, senão o `ret_net` dos rótulos está sistematicamente deslocado por um valor que depende da própria variável que (D) quer mudar.

---

### 4.9 Não há contrato de qualidade/frescor de dado em §7 — **P2**

As 7 fronteiras listadas cobrem forma e semântica, nenhuma cobre **disponibilidade**. Com 5 símbolos × 3 resoluções × 4+ fontes de dado (D01-D14, E01, E04), a probabilidade de pelo menos uma fonte estar atrasada num instante qualquer não é pequena. Cláusula faltante, aplicável a toda fronteira:

```
data_health(source_id, symbol, last_update_ts_ns, staleness_ns, completeness_pct)

regra: se QUALQUER fonte de que uma coluna do design_matrix depende estiver
       stale além do seu availability_lag declarado ⇒ a linha não produz
       intenção de trade naquela barra (fail-closed, mesmo princípio de §2.1)
```

Sem isso, um feed on-chain travado (Grupo H, granularidade diária — o caso mais provável) produz features silenciosamente constantes, e o modelo continua opinando.

---

### 4.10 Dependência da `E27f` em spread quebrado por RPI — **decidir, não continuar em aberto**

O material de apoio marca isso honestamente como "não verificado". Não posso verificar sem o repositório, mas posso dar a regra de decisão, que é o que falta:

- Se `custo_round_trip_bps` deriva de **spread observado do book**, então `E27f` herda a quebra de definição de 2025-11-20 (RPI oculto) e a série tem uma descontinuidade não modelada bem no meio do período que motivou sua inclusão. Nesse caso, `E27f` precisa da mesma coluna `rpi_regime` que o Grupo F precisaria, ou de truncamento da série.
- Se deriva de **taxa de exchange (constante, conhecida) + slippage estimado por outro caminho**, está limpa.

`[PRECISO SABER]`: a fórmula de `custo_round_trip_bps`. É uma checagem de 5 minutos e resolve um item que está aberto há duas rodadas. O ponto que quero enfatizar: essa é a **única** feature que capta a degradação estrutural de custo, e é a variável que define o hurdle de breakeven (§2.6). Ela ser suspeita não é detalhe.

---

### 4.11 Teste de sensibilidade do `hazard_lambda` — desenho concreto

O material de apoio registra a recomendação sem desenho. Proposta: para cada janela de teste `w`, recalcular a duração mediana de segmento do classificador baseline **usando só dado anterior a `inicio(w)`**, derivar `hazard_lambda_w = 5 × mediana_w`, e comparar com o valor fixo de 65,0. Reporte `max_w |hazard_lambda_w − 65| / 65`. Critério: abaixo de ~20%, o caveat vira nota de rodapé; acima, o BOCPD precisa ser reexecutado com `hazard_lambda` walk-forward. Custo: uma passada sobre a série de segmentos que já existe.

---

## 5. Prioridade sugerida

Ordenei por (dano se ignorado) × (custo de resolver agora), não pela ordem dos documentos.

| # | Item | Onde | Por quê agora |
|---|---|---|---|
| 1 | **Definir o caminho de saída executável** (post-only para entrada, `reduceOnly` a mercado para saída — ou assumir saída passiva no rótulo) | §1.4 P2 | Todo o payoff assume uma saída que a política proíbe. É premissa, não feature. Zero medição necessária para decidir. |
| 2 | **Resolver a colisão linha ↔ posição de símbolo** (uma resolução por símbolo, ou `SymbolAggregator`) | §1.2 | Bloqueia (B), bloqueia o cap, bloqueia o rastreador. Decisão de arquitetura, barata agora, cara depois. |
| 3 | **Pré-filtro de custo `p*` nas 15 linhas** | §2.6 | Custo ~zero, 1 trial pela sua própria convenção, pode eliminar a maior parte do espaço antes de qualquer engenharia. |
| 4 | **`horizon_bars` no lugar de `time_stop_ms`** + distribuição empírica de tempo-até-barreira por regime | §4.3, §2.4 | Corrige unidade, responde §6.5, e provavelmente torna (D) desnecessário. |
| 5 | **Ledger de posição por user data stream + fail-closed** | §2.1 | Dissolve §6.1, destrava o cap, e é pré-requisito de qualquer operação real. |
| 6 | **Canonicalização de identidade de estado do regime** + checagem retroativa nos folds da Trilha A | §4.6 | Pode reabrir um resultado que foi arquivado como nulo. Barato. |
| 7 | **`fill_flag` aproximado por toque de `limit_px`** | §4.4 | Mede o viés de seleção da entrada maker sem construir modelo de fila. |
| 8 | **PBO/CSCV implementado + `trial_registry` automático** | §1.3, §2.9 | É a perna capenga admitida no material de apoio. Sem ela, nenhuma outra métrica sustenta promoção. |
| 9 | **Quantização de lote dentro do Risk Engine e do backtest, mesmo código** | §4.2 | Paridade treino-live no sizing. |
| 10 | Sweep de geometria TP/SL | §2.1 do brief | Ver ressalva abaixo. |

**Ressalva sobre a prioridade do sweep TP/SL (discordo parcialmente do material de apoio).** O companion argumenta que a geometria é ortogonal ao contrato e portanto paralela, não bloqueante. Concordo com a lógica **e discordo do peso**: a geometria determina `p* = (sl_mult + c)/(tp_mult + sl_mult)`, que é o número que decide se qualquer linha é viável. Um sistema com breakeven em 48,4% e um classificador que atinge 51% tem 2,6pp de margem — dentro do erro de estimação de `n_eff ≈ 1.095`. **A geometria não é um hiperparâmetro entre outros; é o hurdle.**

Mas acrescento uma ressalva na direção oposta: um sweep 2D de TP × SL sobre o mesmo dado é um **evento de multiplicidade grande**, e você não tem orçamento estatístico para ele. Recomendo **derivar** a geometria em vez de otimizá-la:

- escolher `tp_mult`/`sl_mult` que maximizem a razão entre payoff esperado e hurdle de custo, dado `c` medido e a distribuição empírica de tempo-até-barreira — não que maximizem Sharpe de backtest;
- registrar o resultado como **1 trial estrutural**, não como N variantes;
- confirmar num holdout travado, uma vez.

---

## 6. O que eu diria numa reunião de comitê, em quatro frases

1. A arquitetura de conexão entre estágios está sendo desenhada sobre três premissas que não foram checadas contra a exchange: que existe uma posição por `(símbolo, resolução)`, que existe uma saída executável, e que existe sizing contínuo. **Nenhuma das três é verdade.**
2. O orçamento estatístico real é de ~1.100 rótulos independentes por linha por ano, e ele não cresce com resolução, nem com features, nem com símbolos correlacionados — **o projeto está expandindo em três eixos que não compram poder estatístico e compram multiplicidade**.
3. As 4 propostas aprovadas são boas engenharia dentro do universo do documento; **duas delas (B e D) morrem na fronteira com o mundo real**, e (C) está incoerente enquanto não houver um contador vitalício automático.
4. O maior ganho disponível hoje não é desenhar mais contrato — é o pré-filtro de custo de §2.6, que custa uma tarde, consome 1 trial, e provavelmente elimina a maior parte de um espaço de busca de 15 linhas antes de você gastar uma rodada inteira nele.

---

## 7. Fontes

**Exchange (dados vivos, coletados 2026-08-19)**
- `GET https://fapi.binance.com/fapi/v1/exchangeInfo` — filtros `MIN_NOTIONAL`/`LOT_SIZE` dos 5 símbolos e `rateLimits` (`REQUEST_WEIGHT 2400/min`, `ORDERS 1200/min`, `ORDERS 300/10s`)
- `GET /fapi/v1/ticker/price` — preços dos 5 símbolos
- `GET /fapi/v1/premiumIndex?symbol=BTCUSDT` — `lastFundingRate = 0,00008286`, `nextFundingTime = 1787212800000`
- `GET https://api.binance.com/api/v3/ticker/price?symbol=USDTBRL` — 5,1812

**Documentação Binance**
- [What Is Hedge Mode and How to Use It](https://www.binance.com/en/support/faq/what-is-hedge-mode-and-how-to-use-it-360041513552) · [Hedge vs One-way (Altrady)](https://support.altrady.com/en/article/futures-hedge-mode-and-one-way-mode-urbl8u/) — uma posição por símbolo em One-way; modo aplicado por conta
- [Self Trade Prevention FAQ](https://developers.binance.com/docs/derivatives/usds-margined-futures/faq/stp-faq) — GTX expira/é rejeitada se cruzaria; STP não se aplica a GTX
- [Maker (Post Only) / Time in Force](https://www.binance.com/en/support/faq/what-are-maker-post-only-order-time-in-force-order-and-iceberg-order-5d3fa5e5709f47e0b5f186b350da1655)
- [User Data Streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams) — ordenação estrita de `ACCOUNT_UPDATE`/`ORDER_TRADE_UPDATE`
- [Minimum notional BTCUSDT/ETHUSDT (2023-11-02)](https://www.binance.com/en/support/announcement/updates-on-minimum-notional-value-for-btcusdt-and-ethusdt-perpetual-contracts-2023-11-02-e4384cba297a4bd2a154be644d5d76f9) — histórico do limite (valor corrente medido acima)
- [Fee schedule 2026](https://binancemakertakerfee.org/) — maker 0,02% / taker 0,05% VIP0

**Metodologia quant**
- [The Market Maker's Dilemma (arXiv 2502.18625)](https://arxiv.org/abs/2502.18625) — correlação negativa entre probabilidade de fill e retorno pós-fill, experimento ao vivo no perpétuo de BTC da Binance
- [Deep Learning Approach to Estimating Fill Probabilities in a LOB (Columbia)](https://business.columbia.edu/sites/default/files-efs/citation_file_upload/deep-lob-2021.pdf) — viés de estimação de fill condicionado à decisão do trader
- [Bailey & López de Prado, The Deflated Sharpe Ratio (SSRN 2460551)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) · [DSR — Wikipedia](https://en.wikipedia.org/wiki/Deflated_Sharpe_Ratio) — número **efetivo** de trials via clustering (ONC / hierárquico / espectral)
- [López de Prado, Clustered Feature Importance (SSRN 3517595)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3517595) · [mlfinlab Feature Clusters](https://random-docs.readthedocs.io/en/latest/implementations/feature_clusters.html) — efeito de substituição em MDI/MDA, cMDA
- [Purged cross-validation](https://en.wikipedia.org/wiki/Purged_cross-validation) — purge sobre `t1` + embargo
- [MQL5, Label Concurrency](https://www.mql5.com/en/articles/19850) — unicidade média, inflação in-sample por rótulos concorrentes
- [scikit-learn, Probability calibration](https://scikit-learn.org/stable/modules/calibration.html) — isotônica sobreajusta em amostra escassa; Platt em conjunto pequeno
- [Label switching em HMM (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0378375808004217) · [Identifiability in HMM (Springer)](https://link.springer.com/article/10.1007/s40300-019-00156-3) — invariância a permutação, restrição de ordenação como solução
- [Time series momentum and volatility scaling (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S1386418116301379) — escalonamento por volatilidade
- [Fundamental Law of Active Management (ReSolve)](https://investresolve.com/tactical-alpha-theory-practice-pt-i-fundamental-law-of-active-management/) — breadth = apostas **independentes**; correlação reduz breadth efetivo
- [FXStreet, Bitcoin correlation cheat sheet](https://www.fxstreet.com/cryptocurrencies/news/bitcoin-correlation-cheat-sheet-for-portfolio-diversification-202309141858) · [Beyond Bitcoin, 2025](https://markets.financialcontent.com/wral/article/breakingcrypto-2025-10-15-beyond-bitcoin-why-altcoins-are-essential-for-a-diversified-crypto-portfolio-in-late-2025) — ρ(BTC,ETH) ≈ 0,94; colapso de diversificação sob stress
- [Alpha Capital, daily risk limits](https://help.alphacapitalgroup.uk/en/articles/6934210-what-are-the-daily-risk-limits-and-how-do-they-work) · [CrossTrade, daily loss limits](https://crosstrade.io/learn/risk-management/daily-loss-limits) — teto diário sobre equity incluindo não-realizado, âncora no reset
- [apxml, Online/Offline Skew](https://apxml.com/courses/feature-stores-for-ml/chapter-3-data-consistency-quality/diagnosing-mitigating-skew) — point-in-time correctness, paridade treino-serving

---

## 8. Limites desta revisão

- Não tenho acesso ao repositório. Tudo marcado `[PRECISO SABER]` é pergunta genuína, não retórica: fórmula de `custo_round_trip_bps` (§4.10), filtragem de linhas R0 antes do fit (§4.7), unidade da condição de amostra mínima do Meta (§3.7), e o position mode configurado na conta (§1.2).
- Os números de ATR em §4.2 são **premissas declaradas**, não medições suas. A estrutura do argumento (grade discreta, assimetria entre símbolos, piso sob stress) não depende do valor exato; as conclusões numéricas dependem.
- Não reabri a Trilha A, exceto por §4.6, que propõe uma verificação específica capaz de afetar a interpretação do resultado nulo. Se essa verificação passar, o resultado nulo fica de pé.
- Não avaliei a qualidade do código — só o que os dois documentos declaram sobre ele e os 3 trechos citados no §10 do brief.

---
---

# Parte II — Layout Físico dos Artefatos

*(anexo técnico, incorporado. As 12 correções da validação de engenharia estão **aplicadas inline** e marcadas com `⟲ V-NN`; a tabela de origem está na seção de validação do ADR, acima.)*

## 0. Convenção de diretório — um artefato é um diretório, nunca um arquivo solto

```
{ARTIFACT_ROOT}/
  {stage}/
    config_hash={HASH}/            # ⟲ V-07: chave hive, e ACIMA das partições
      symbol={SYMBOL}/
        resolution={RES}/
          _SUCCESS                 # marcador, escrito por último — a AUTORIDADE (⟲ V-05)
          manifest.json            # proveniência + estatísticas + hashes
          config.json              # subtree de config CONGELADO que gerou config_hash
          schema.json              # schema Arrow serializado, para validar antes de ler
          part-0000.parquet        # dados
          part-0001.parquet
          ...
```

Cinco decisões embutidas nesse layout, cada uma resolvendo um problema específico do seu projeto:

| Decisão | Problema que resolve |
|---|---|
| Particionamento hive `symbol=/resolution=` | Uma linha `(símbolo, resolução)` é lida sem varrer as outras 14; e um `scan_parquet` com filtro faz *partition pruning* automático |
| `config_hash={h}` **acima** das partições | Duas configurações coexistem sem sobrescrever — o que o mandato de "eliminação periódica" exige. E como é chave hive (`key=value`), uma única `scan_parquet` cobre as 15 linhas de uma rodada com *partition pruning*: é literalmente a operação da seleção de linha. `{config_hash}/` sem `chave=` quebraria a descoberta hive do polars (⟲ **V-07**) |
| `bar_id` é chave **local a um `bars.config_hash`** | Se `threshold_quote` for recalibrado, a numeração de barras muda e `t1_bar_id` de rótulos antigos passa a apontar para outra barra. Por isso todo artefato chaveado por `bar_id` carrega `bar_close_ts_ns` obrigatoriamente, e referência cross-config só é feita por timestamp (⟲ **V-01**) |
| `_SUCCESS` escrito por último | Leitor nunca consome artefato parcial. Diretório sem `_SUCCESS` é lixo de escrita interrompida e pode ser coletado |
| `manifest.json` com hash do manifest upstream | A cadeia de hashes de INV-B. É o que dispara revalidação automática (§3.6 do parecer) |
| `schema.json` separado do parquet | O leitor valida contrato **antes** de materializar. Falha de schema vira erro no load, não `KeyError` três estágios adiante |

**Escrita atômica — cuidado específico de Windows (⟲ V-05).** Rename de diretório **não é atômico garantido no Windows**: `MOVEFILE_REPLACE_EXISTING` não se aplica a diretórios, e `MoveFileEx` pode cair silenciosamente para uma `CopyFile` não-atômica ([MoveFileExA, Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexa); [bugs.python.org/issue1704547](https://bugs.python.org/issue1704547)). A consequência de projeto é que **a corretude não pode depender do rename** — ela depende do `_SUCCESS`:

```python
def write_artifact_atomic(final_dir: Path, write_fn, *, retries: int = 5) -> None:
    tmp = final_dir.parent / f".tmp-{uuid4().hex}"   # MESMO volume que o destino
    tmp.mkdir(parents=True, exist_ok=False)
    write_fn(tmp)                                   # parquet + config + schema
    (tmp / "manifest.json").write_text(...)
    (tmp / "_SUCCESS").touch()                      # SEMPRE por último
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        try:
            os.rename(tmp, final_dir)               # sem pré-checagem: TOCTOU
            return
        except FileExistsError:
            raise ArtifactExistsError(final_dir)    # imutável: nunca sobrescreve
        except OSError:
            if attempt == retries - 1:
                raise
            time.sleep(0.1 * 2**attempt)            # antivírus/indexer seguram handles
```

Quatro cláusulas não-negociáveis:

1. **`_SUCCESS` é a autoridade, não o rename.** Leitor ignora qualquer diretório sem `_SUCCESS`. Mesmo que o rename seja parcialmente visível, o artefato incompleto é invisível ao consumidor. É isso que torna o desenho correto **apesar** de o Windows não garantir atomicidade.
2. **`ArtifactExistsError` em vez de sobrescrita** — artefato é imutável; mesmo `config_hash` ⇒ mesmo conteúdo, então reescrever é sempre erro ou desperdício.
3. **Sem pré-checagem `exists()`** — é TOCTOU. Deixe o `rename` falhar e capture a exceção.
4. **`tmp` no mesmo volume** que o destino, senão o rename degrada para cópia; e **retry com backoff**, porque no Windows antivírus e indexador seguram handles de forma intermitente.

---

## 1. `manifest.json` — o arquivo que faz a cadeia funcionar

Conteúdo completo, campo a campo:

```json
{
  "artifact_id": "labels/BTCUSDT/R1/b3f2a1c8d94e6072",
  "stage": "labels",
  "schema_version": "1.3.0",
  "producer_version": "git:4f1c9ae2",
  "producer_entrypoint": "src.labels.triple_barrier:build",

  "symbol": "BTCUSDT",
  "resolution": "R1",

  "config_hash": "b3f2a1c8d94e6072...",
  "input_manifest_hash": "7ac0913ef5d2...",
  "upstream": [
    {"stage": "bars",     "config_hash": "9de1...", "manifest_hash": "7ac0..."},
    {"stage": "features", "config_hash": "22b7...", "manifest_hash": "c410..."}
  ],

  "created_at_ns": 1787188632288000000,
  "rows": 341227,
  "bar_id_min": 0,
  "bar_id_max": 341226,
  "ts_min_ns": 1609459200000000000,
  "ts_max_ns": 1787184000000000000,
  "sorted_by": ["bar_id"],
  "partition_keys": ["symbol", "resolution"],

  "files": [
    {"path": "part-0000.parquet", "rows": 200000, "bytes": 18442112, "sha256": "ab34..."},
    {"path": "part-0001.parquet", "rows": 141227, "bytes": 13001984, "sha256": "cd91..."}
  ],
  "content_hash": "blake2b-256 dos sha256 dos arquivos, ordenados por path",

  "column_stats": {
    "ret_net":  {"nulls": 0,   "nan": 0, "min": -0.0412, "max": 0.0388},
    "y":        {"nulls": 0,   "nan": 0, "value_counts": {"0": 197431, "1": 143796}},
    "barrier":  {"nulls": 0,   "value_counts": {"tp": 143796, "sl": 151022, "vertical": 46409}},
    "t1_bar_id":{"nulls": 812, "min": 3, "max": 341226}
  },

  "causality": {
    "atr_value": {"class": "at_close", "availability_lag_ns": 0,           "lookback_bars": 48},
    "t1_ts_ns":  {"class": "forward_looking", "availability_lag_ns": null, "lookback_bars": null}
  },

  "determinism": {"global_seed": 20260819, "jax_x64": true, "thread_count_pinned": true}
}
```

**Os cinco campos que valem discussão:**

- **`content_hash`** — hash dos hashes dos arquivos, em ordem estável de `path`. É o que permite dizer "esse artefato é bit-idêntico ao de ontem" sem reler os dados. Não use o hash do diretório (ordem de listagem varia por sistema de arquivos).
- **`input_manifest_hash` + `upstream[]`** — o `upstream` é a lista legível; o `input_manifest_hash` é o hash canônico da lista. A revalidação automática de §3.6 do parecer compara **este** campo, não a lista.
- **`column_stats`** — não é telemetria, é **gate**. `nulls`, `nan` e `value_counts` de colunas categóricas viram asserções: um dia em que `barrier.vertical` pula de 13% para 40% é deriva de dado ou bug de horizonte, e o pipeline deve parar. Isso é barato e pega mais bug do que qualquer teste unitário. **Mas gate precisa de referência e de dono (⟲ V-09):** a comparação é contra o artefato **anterior da mesma `(stage, símbolo, resolução)`**, com bandas de tolerância declaradas em `config.json` (`drift_bands`), e um override explícito `accept_drift: true` que grava no manifesto quem aceitou e por quê. Sem referência declarada o gate nunca dispara; sem override ele dispara e é contornado com `--force`, que é pior.
- **`causality`** — projeção por artefato do INV-C. Redundante com o registry global de propósito: se alguém alterar `lookback_bars` de uma feature sem regerar o artefato, o manifest antigo denuncia a divergência.
- **`determinism`** — `global_seed`, `jax_x64` e pin de threads. Sem pin de threads, redução em ponto flutuante muda por ordem de agregação e a paridade bit-exact de INV-D falha de forma intermitente — que é o pior modo de falha possível.

---

## 2. `config.json` — e a regra de hash canônico

Contém **apenas o subtree de configuração resolvido que este estágio consumiu**, já com defaults aplicados e referências expandidas. Não o config global.

```json
{
  "stage": "labels",
  "tp_atr_mult": "2.0",
  "sl_atr_mult": "1.5",
  "horizon_bars": 32,
  "atr_feature_id": "C03_atr_48",
  "atr_feature_version": "2.1.0",
  "cost_model": {
    "maker_fee_bps": "2.0",
    "taker_fee_bps": "5.0",
    "slippage_model": "half_spread",
    "funding_included": true
  },
  "side_policy": "both",
  "y_definition": "tp_touch_first",
  "vertical_label": 0,
  "fill_model": "assumed_immediate"
}
```

**A regra de hash, que é onde a maioria dos pipelines quebra reprodutibilidade sem perceber:**

```python
def config_hash(cfg: dict) -> str:
    payload = json.dumps(
        cfg,
        sort_keys=True,        # ordem de chave não pode influenciar
        separators=(",", ":"), # sem espaço
        ensure_ascii=True,
        allow_nan=False,       # NaN/Infinity em JSON não é padrão
    ).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).hexdigest()
```

**Floats são serializados como string** (`"2.0"`, não `2.0`). Motivo: `repr(0.1 + 0.2)` e a formatação de float de bibliotecas JSON diferentes não coincidem, e um dígito a mais no décimo-sétimo lugar gera um `config_hash` diferente para configurações idênticas — o que faz o pipeline recomputar tudo e, pior, quebra o cache de validação de §3.6. Se preferir manter float nativo no YAML, normalize com `Decimal(str(x))` antes de hashear.

**O que TAMBÉM entra no hash (⟲ V-08):** `schema_version`. Sem isso, uma mudança de schema reusa o artefato antigo em silêncio — o manifesto registra a versão nova, o conteúdo é o antigo, e nada denuncia.

**O que NÃO entra no hash:** caminho de disco, número de workers, nível de log, timestamps. Só o que altera o **conteúdo** do artefato. Um artefato produzido com 4 threads e outro com 8 têm o mesmo `config_hash` — e o teste de INV-D exige que tenham o mesmo `content_hash` também.

---

## 3. `schema.json` — contrato verificado antes do load

```json
{
  "schema_version": "1.3.0",
  "arrow_schema_b64": "<pyarrow.Schema serializado>",
  "columns": [
    {"name": "bar_id",      "dtype": "int64",   "nullable": false, "unit": null,   "role": "key"},
    {"name": "side",        "dtype": "enum",    "nullable": false, "categories": ["long","short"], "role": "key"},
    {"name": "t1_bar_id",   "dtype": "int64",   "nullable": true,  "unit": "bars", "role": "label"},
    {"name": "ret_net",     "dtype": "float64", "nullable": false, "unit": "frac", "role": "label"},
    {"name": "y",           "dtype": "int8",    "nullable": false, "unit": null,   "role": "target"}
  ],
  "primary_key": ["bar_id", "side"],
  "checks": ["unique(primary_key)", "monotonic_increasing(bar_id)", "t1_bar_id > bar_id"]
}
```

Três detalhes que importam em polars especificamente:

- **`Enum`, não `Categorical`.** `pl.Categorical` tem ordenação de categoria dependente da ordem de aparição no frame — dois frames concatenados podem discordar sobre o que é a categoria 0. `pl.Enum(["long","short"])` fixa as categorias no schema. Isso vale para `side`, `barrier`, `causality_class`, `group`, `decode_mode` e para as dummies de regime.
- **`unit` explícito.** `"frac"` vs `"bps"` vs `"pct"` é a classe de bug mais barata de evitar e mais cara de achar. `time_stop_ms` vs `horizon_bars` (§4.3 do parecer) é exatamente esse bug em escala maior.
- **`checks`** são executados no writer **e** no reader. O writer garante que o artefato nasce válido; o reader garante que ninguém editou o parquet à mão.

---

## 4. Schemas por estágio — o `part-*.parquet` de cada artefato

Notação: `dtype nullable?` — `!` = não-nulo obrigatório.

### 4.1 `bars/` — dollar bars (upstream, provavelmente já existe)

| Coluna | dtype | Nota |
|---|---|---|
| `bar_id` | `Int64!` | monótono por `(symbol, resolution)`, sem buracos |
| `bar_open_ts_ns`, `bar_close_ts_ns` | `Int64!` | UTC ns. **Não** `Datetime` — evita ambiguidade de tz na serialização |
| `open, high, low, close` | `Float64!` | |
| `volume_base, volume_quote` | `Float64!` | `volume_quote` é o que fecha a barra |
| `n_trades` | `Int64!` | |
| `taker_buy_base, taker_buy_quote` | `Float64!` | insumo do Grupo D |
| `bar_duration_ns` | `Int64!` | **derivado, mas persistido** — é o insumo direto do "barras/hora por regime" de §1.4/§2.4 do parecer |
| `threshold_quote` | `Float64!` | o limiar de dólar usado; se ele for recalibrado ao longo do histórico, esta coluna é a única prova |

### 4.2 `features/`

| Coluna | dtype | Nota |
|---|---|---|
| `bar_id` | `Int64!` | |
| `bar_close_ts_ns` | `Int64!` | payload, não chave |
| `<feature_id>` × ~92 | `Float64` | nome = `feature_id` do `registry.yaml`, sem renomear |
| `<feature_id>__valid` | `Boolean!` | máscara de warmup por feature — **uma por feature, não uma global** |

**A coluna `__valid` é o detalhe que resolve um problema real seu.** Features têm lookbacks diferentes (`C07_vol_pctile_expanding` é expansivo; `D06f_taker_imbalance_z_48` precisa de 48 barras). Uma máscara global de warmup usa o pior caso e joga fora amostra que a maioria das features já tinha. Com máscara por feature, o Learner decide: ou exige todas válidas, ou treina com imputação declarada. Com `n_eff ≈ 1.095/ano`, jogar fora 200 barras iniciais desnecessariamente não é gratuito.

**Não** persistir `feature_id` como linha (formato longo). Formato **largo**, uma coluna por feature: o design matrix é largo, o join é O(1), e o parquet comprime melhor colunas homogêneas. O registry (`registry.yaml`) já é a fonte de verdade do catálogo — o parquet não deve duplicá-la.

### 4.3 `regime/`

| Coluna | dtype | Nota |
|---|---|---|
| `bar_id` | `Int64!` | |
| `method_id` | `Enum!` | `baseline_quantile \| hmm_k2 \| hmm_k3 \| hmm_k4 \| bocpd \| jump` |
| `state_id` | `Int8!` | **canonicalizado** — ver §5 |
| `K` | `Int8!` | |
| `state_label` | `Enum` | legível, derivado de `state_id`; **nunca** chave de join |
| `tradeable` | `Boolean!` | papel 2, o gate |
| `p_state_0..p_state_{K-1}` | `Float64` | null para métodos sem posterior |
| `state_age_bars` | `Int32!` | |
| `decode_mode` | `Enum!` | `filter \| smooth` — **só `filter` é consumível** |
| `canonical_order_stat` | `Float64!` | a estatística usada para ordenar os estados (ver §5) |

### 4.4 `labels/`

| Coluna | dtype | Nota |
|---|---|---|
| `bar_id`, `side` | `Int64!`, `Enum!` | chave primária composta |
| `t1_bar_id`, `t1_ts_ns` | `Int64` | null se a barreira não resolveu dentro do histórico (cauda do dataset) |
| `barrier` | `Enum!` | `tp \| sl \| vertical \| unresolved` |
| `collision` | `Boolean!` | ⟳ X-05 — `high ≥ tp_px` E `low ≤ sl_px` na mesma barra; ordem indeterminada sem tick. Resolvida por `barrier_collision_rule` (no hash); `collision_rate` vira gate de deriva |
| `entry_ref_px`, `tp_px`, `sl_px` | `Float64!` | |
| `atr_value` | `Float64!` | copiado do input, para o rótulo ser auto-contido |
| `horizon_bars_used` | `Int32!` | |
| `ret_gross`, `cost_bps_assumed`, `ret_net` | `Float64!` | os três, sempre — `ret_net` sozinho não é auditável |
| `funding_bps_assumed` | `Float64!` | separado de `cost_bps_assumed`: escala com holding, o resto não (§4.8 do parecer) |
| `y` | `Int8!` | `1` sse `barrier == tp` |
| `y_ternary` | `Int8!` | `-1/0/+1` para análise; nunca alvo de treino sem decisão explícita |
| `fill_model` | `Enum!` | `assumed_immediate \| queue_model` |
| `fill_flag_approx` | `Boolean` | §4.4 do parecer — `limit_px` foi tocado dentro do timeout? Computável hoje |

`barrier = unresolved` importa: as últimas ~`horizon_bars` linhas de todo dataset não têm rótulo. Tratá-las como `vertical` contamina a base — e é um erro clássico, silencioso e que só aparece como otimismo no fold mais recente, que é justamente o que a rodada de seleção olha.

### 4.5 `weights/`

| Coluna | dtype | Nota |
|---|---|---|
| `bar_id`, `side` | `Int64!`, `Enum!` | |
| `split_id`, `fold_id` | `Utf8!`, `Int16!` | **pesos são por fold** (INV de §3.3) |
| `concurrency` | `Int32!` | |
| `avg_uniqueness` | `Float64!` | ∈ (0, 1] |
| `w_return_attrib`, `w_time_decay`, `w_final` | `Float64!` | os três fatores separados, não só o produto |
| `concurrency_scope` | `Enum!` | `line \| symbol \| pooled` |

E no `manifest.json` deste estágio, um bloco extra que não é coluna:

```json
"effective_sample": {
  "aggregate": {"n_rows": 341227, "n_eff": 1103.4, "n_eff_per_year": 1095.2,
                "mean_avg_uniqueness": 0.0312},
  "by_fold": [
    {"split_id": "S3", "fold_id": 0, "group": "train", "n_rows": 227484, "n_eff": 735.1},
    {"split_id": "S3", "fold_id": 0, "group": "test",  "n_rows": 113743, "n_eff": 361.8}
  ]
}
```

⟲ **V-12:** `n_eff` é **por fold**, porque os pesos são por fold — a concorrência muda na fronteira. O agregado sozinho esconde folds pequenos demais para treinar, que é exatamente o que o gate precisa pegar.

`n_eff` **tem que ser campo de manifest**, não número calculado ad hoc num notebook: é ele que alimenta o gate `n_clusters / n_eff` de §3.2 do parecer, e é o número que o parecer inteiro usa como orçamento.

### 4.6 `splits/`

| Coluna | dtype | Nota |
|---|---|---|
| `split_id` | `Utf8!` | idêntico entre todas as linhas da rodada |
| `fold_id` | `Int16!` | |
| `group` | `Enum!` | `train \| test \| purged \| embargo \| holdout` |
| `t_start_ns`, `t_end_ns` | `Int64!` | **calendário mestre UTC** — a fronteira canônica |
| `symbol`, `resolution` | partição | |
| `bar_id_start`, `bar_id_end` | `Int64!` | projeção do intervalo nesta linha |
| `purge_basis` | `Enum!` | `t1` |
| `embargo_bars` | `Int32!` | **[SUPERSEDIDO 2026-08-21]** campo do parecer original (Parte I §3.3); a implementação real usa `embargo_ms` (`Int64!`), relógio fixo **medido**, valor de produção `347.010.000 ms` (≈96,39h), deliberadamente invariante a `tf`/densidade de barra — desde `AG-032`/E1 (2026-08-16), ver `config/constants.yaml::cpcv_embargo_ms` |

Mais, no manifest: `holdout_locked_until_ts`, `holdout_unlock_count`, `holdout_touched`, `master_calendar_hash`.

⟳ **X-09 — holdout governado, não apenas travado.** Eu tinha um contador de desbloqueios, que **registra** o fato. A acrescenta a peça que **impede a consequência**: um booleano `holdout_touched` que, uma vez verdadeiro, proíbe inspeção de feature, tuning de parâmetro, ranking de linha, otimização de threshold e tuning da própria frequência de seleção. A frase que resolve: *"caso o holdout seja consultado e uma decisão seja tomada com base nele, aquele holdout deixa de ser holdout."* O flag propaga para cada linha do `trial_registry` e é checado pelo gate de promoção. O `master_calendar_hash` é o que prova que 15 linhas usaram o mesmo calendário — sem ele, a cláusula central de §3.3 do parecer é uma intenção, não uma garantia.

### 4.7 `design/` — matriz de design

| Coluna | dtype | Nota |
|---|---|---|
| `bar_id`, `side` | `Int64!`, `Enum!` | |
| `<feature_id>` × N | `Float64!` | ordem **fixada pelo `feature_manifest`**, não pela ordem do dicionário |
| `regime__{level}` × (K−1) | `Int8!` | dummies; nível de referência declarado no manifest |
| `y` | `Int8!` | |

⟲ **V-02 — correção estrutural.** A versão anterior materializava `split_id`, `fold_id`, `group` e `w_final` dentro do `design/`. Isso significa **uma cópia da matriz por partição de fold**: com CPCV de `C(6,2)=15` partições, a matriz de ~92 colunas × ~341k linhas (≈251 MB por linha, bruto) vira ≈3,8 GB por linha e ≈**56 GB** nas 15 linhas — só neste estágio, e crescendo com cada `design_hash` novo, num esquema que é imutável por princípio.

Correção: **`design/` guarda a matriz uma única vez por `(linha, design_hash)`**. O pertencimento a fold vive em `splits/` (tabela de intervalos, ~centenas de linhas) e `w_final` vive em `weights/` (que já é por fold). O fit faz o join `design ⋈ splits ⋈ weights` em memória — barato, porque `splits` é intervalar e `weights` é uma coluna. O custo de disco cai de O(n_folds) para O(1) sem perder nenhuma garantia: a proveniência continua na cadeia de hash, e o `w_final` que entra no `sample_weight` continua rastreável até o artefato que o produziu.

No manifest:

```json
"design": {
  "design_hash": "e91b...",
  "feature_manifest": [
    {"feature_id": "A05_ret_vol_norm_4", "version": "1.2.0", "cluster_id": 3},
    {"feature_id": "C07_vol_pctile_expanding", "version": "2.0.1", "cluster_id": 7}
  ],
  "regime": {"method_id": "baseline_quantile", "levels": ["R2","R3","R4","R5"],
             "reference_level": "R1", "excluded_states": ["R0"]},
  "n_features": 92, "n_clusters": 15, "n_eff": 1103.4, "ratio_gate": 0.0136
}
```

`reference_level` e `excluded_states` **separados** é o conserto direto do achado §4.7 do parecer: hoje a tupla literal `("R2","R3","R4","R5")` deixa implícito que R0 e R1 são a mesma coisa. Aqui é impossível expressar isso sem escrever, e escrever força a decisão.

### 4.8 `models/` — não é parquet

```
models/config_hash={h}/symbol=BTCUSDT/resolution=R1/
  _SUCCESS
  manifest.json
  config.json
  fold=00/model.ubj          # XGBoost formato binário universal (NÃO pickle)
  fold=00/feature_names.json # ordem exata das colunas no treino
  fold=00/booster_meta.json  # best_iteration, n_trees, base_score
  fold=01/...
  oof_predictions.parquet    # p_raw out-of-fold, chave (bar_id, side, fold_id)
```

Três cláusulas:

- **`.ubj` (UBJSON) ou `.json`, nunca pickle.** Pickle amarra a versão exata de Python e de xgboost e não é auditável. O formato nativo do XGBoost é estável entre versões e legível.
- **`feature_names.json` ao lado do modelo**, mesmo que o booster já guarde nomes. É a verificação cruzada que pega reordenação de coluna — a falha de paridade treino-live mais comum e mais silenciosa, porque o modelo aceita o vetor errado sem reclamar e só entrega predição ruim.
- **`oof_predictions.parquet` é artefato de primeira classe.** É o insumo obrigatório da calibração e do Meta (§3.5 e §3.7 do parecer: `p_cal` tem de ser out-of-fold). Se ele não existir como arquivo, alguém vai reconstruir isso na memória e a regra de out-of-fold vira convenção verbal.

### 4.9 `calibration/`

```
calibration/config_hash={h}/symbol={S}/resolution={R}/
  _SUCCESS  manifest.json  config.json
  fold=00/calibrator.json     # coeficientes, não objeto serializado
  calibrated_scores.parquet
```

`calibrator.json` para Platt são dois números:

```json
{"kind": "platt", "A": -1.8421, "B": 0.2277,
 "n_cal": 3411, "n_cal_eff": 214.7, "fitted_on": {"split_id":"S3","inner_fold":2}}
```

Salvar **coeficientes**, não `pickle` do `CalibratedClassifierCV`, tem uma consequência prática direta: a aplicação ao vivo é `1/(1+exp(A*p+B))` — três linhas, sem sklearn no runtime de produção, e trivialmente verificável bit-exact contra o treino (INV-D).

`calibrated_scores.parquet`: `bar_id, side, split_id, fold_id, inner_fold_id, p_raw, p_cal, calibrator_id, n_cal_eff`.

E o gate de §3.5 do parecer vive no writer:

```python
if calibrator_id == "isotonic" and n_cal_eff < ISOTONIC_MIN_NEFF:
    raise CalibratorNotPermitted(n_cal_eff=n_cal_eff, min=ISOTONIC_MIN_NEFF)
```

> **[PONTEIRO, 2026-08-22, `AG-141`/`PLANO_MESTRE_PRINCE2.md §15.18`]**
> O código real (`src.models.alpha.fit_side_model`) usa
> `sklearn.isotonic.IsotonicRegression`, não Platt — não reduz a 2
> coeficientes `{A, B}`. `src/models/persistence.py` persiste como os
> arrays `X_thresholds_`/`y_thresholds_` fitted, reconstrução em
> produção via `np.interp` — verificado empiricamente bit-exato contra
> `IsotonicRegression.predict`, ainda sem sklearn no runtime. O gate
> `ISOTONIC_MIN_NEFF`/`CalibratorNotPermitted` acima segue **não
> implementado** em nenhum lugar do repo — decisão de escopo/negócio
> ainda não ratificada, não bug de `persistence.py`. Texto original
> acima preservado como registro do desenho proposto.

### 4.10 `validation/`

```
validation/validation_key={k}/symbol={S}/resolution={R}/
  _SUCCESS  manifest.json
  report.json          # o validation_report de §3.6 do parecer
  metrics.parquet      # métricas por fold, para agregação e para o PBO
  pbo_matrix.parquet   # ranking in-sample × out-of-sample de cada combinação CSCV
  report.md            # renderização humana, gerada, nunca editada à mão
```

`{validation_key}` **não é um `config_hash` novo** — é `blake2b(content_hash(calibrated_scores) ‖ split_id)` (⟲ **V-03**: a versão anterior enumerava quatro hashes e omitia `weights/` e `regime/`). O orquestrador calcula a chave, checa se o diretório existe, e se não existir a promoção fica bloqueada.

`pbo_matrix.parquet` é o que falta hoje: `combination_id, is_rank, oos_rank, is_metric, oos_metric` — uma linha por partição CSCV. O PBO é a fração de combinações em que a vencedora in-sample fica abaixo da mediana out-of-sample; com a matriz persistida, ele é um `groupby`, e fica auditável em vez de ser um escalar produzido por um script.

### 4.11 `meta/`

`meta_training_set.parquet`: `line_id, bar_id, side, p_cal (out-of-fold!), spread_bps, book_imbalance, dist_to_touch_ticks, queue_pos_est, fill_prob_est, cost_est_bps, adverse_sel_est, regime_state_id?, state_age_bars?, fill_assumed, y_meta`.

No manifest, o bloco que §3.7 do parecer exige:

```json
"meta_sample": {
  "n_signals": 6832, "n_eff_signals": 219.4,
  "signal_rate": 0.020, "pool_scope": "cross_symbol",
  "y_meta_definition": "ret_net > 0",
  "positive_rate": 0.463
}
```

`n_eff_signals` no manifest é o que impede a condição de entrada do Meta ("amostra efetiva mínima") de ser lida como contagem bruta de trades — o erro de ~5× que apontei em §3.7 do parecer.

### 4.12 `trial_registry/` — append-only, não é diretório versionado

```
trial_registry/
  trials/{trial_id}.json       # UM ARQUIVO POR TRIAL (⟲ V-06)
  returns/{trial_id}.parquet   # série de retorno OOS do trial
  trials.parquet               # compactação periódica, derivada — nunca fonte
```

⟲ **V-06 — por que não é um `trials.jsonl` append-only.** Append atômico existe (`O_APPEND` / `FILE_APPEND_DATA`), mas no Windows só vale se a escrita for **uma única chamada** à API nativa — o que io bufferizado de runtime não garante ([Atomic shared log file writes with FILE_APPEND_DATA](https://nblumhardt.com/2016/08/atomic-shared-log-file-writes/)). Com fits de fold em paralelo, o resultado é linha truncada no meio e o registry inteiro fica ilegível — e o registry é justamente o que sustenta o `N_eff` do DSR. Um arquivo por trial, escrito com o mesmo `write_atomic` do resto, elimina a classe de falha sem lock e sem processo escritor único. `trials.parquet` é compactação derivada e reconstruível.

Conteúdo de `trials/{trial_id}.json`:

```json
{"trial_id":"t-000417","created_at_ns":1787188632288000000,
 "line_id":"BTCUSDT:R1","kind":"model_fit",
 "config_hash":"b3f2...","design_hash":"e91b...","split_id":"S3",
 "returns_path":"returns/t-000417.parquet",
 "n_eff":1103.4,"sharpe_oos":0.41,"note":"rodada Q3-2026"}
```

`kind` distingue os dois casos da convenção (C): `model_fit` (exige backtest novo → 1 trial) e `ranking_pass` (reusa artefato → 1 trial para o passe inteiro, não por candidata). É assim que o pré-filtro de custo de §2.6 do parecer entra como **um** registro em vez de quinze.

`returns/{trial_id}.parquet` é o que torna `N_eff` **calculável**: o clustering de §1.3 do parecer roda sobre essas séries. Sem persistir a série, `N_eff` volta a ser um número que alguém lembra.

### 4.13 Ledgers de runtime — JSONL append-only, não parquet

```
runtime/{date}/intents.jsonl     # trade_intent (§3.8a do parecer)
runtime/{date}/orders.jsonl      # order_request + resposta da exchange
runtime/{date}/fills.jsonl       # ORDER_TRADE_UPDATE bruto + normalizado
runtime/{date}/account.jsonl     # ACCOUNT_UPDATE bruto
runtime/{date}/position_ledger.jsonl   # estado derivado, reconstruível dos anteriores
```

Parquet é errado aqui: escrita é linha a linha e latência importa. JSONL, compactado para parquet no fim do dia.

⟲ **V-10 — durabilidade seletiva.** A versão anterior pedia `fsync` por linha crítica, o que colide com o requisito de latência no caminho de envio de ordem (`fsync` custa ~ms em SSD, e ele está entre a decisão e a ordem). A durabilidade forte é necessária em **exatamente um** arquivo: `intents.jsonl`. Motivo: o `intent_id` é a chave de idempotência; se o processo morre entre gravar a intenção e enviar a ordem, é o registro em disco que impede o reenvio duplicado no restart. `orders`, `fills` e `account` são reconstruíveis da própria exchange (`GET /fapi/v1/allOrders`, `userTrades`) e `position_ledger` é derivado dos dois — nenhum precisa de `fsync` por linha, basta flush em lote.

**Cláusula de preço e quantidade que amarra em §4.2 do parecer:**

```
px_ticks : Int64!    # preço em múltiplos inteiros de tickSize
qty_steps: Int64!    # quantidade em múltiplos inteiros de stepSize
tick_size, step_size : Utf8!   # strings decimais, como vêm do exchangeInfo
```

No runtime, preço e quantidade são **inteiros de tick/step**, não float. Os filtros da Binance são múltiplos exatos (`stepSize` 0,001 BTC, `tickSize` 0,10 USDT), e float64 introduz erro de arredondamento que a exchange rejeita com `-1111 Precision is over the maximum`. Guardar `tick_size`/`step_size` como string decimal, junto do evento, também congela o filtro vigente no momento — eles mudam sem aviso, e um backtest reexecutado meses depois usaria os filtros novos sobre dado antigo.

O `position_ledger.jsonl` guarda estado derivado **e** é reconstruível a partir de `account.jsonl` + `fills.jsonl`. Essa redundância é intencional: é ela que permite o `position_ledger_fresh()` de §2.1 do parecer detectar divergência entre o que ele acredita e o que a exchange reportou.

---

### 4.14 `snapshot/` — ⟳ X-01, o artefato que torna a decisão replayable

```
snapshot/config_hash={h}/symbol={S}/resolution={R}/
  _SUCCESS  manifest.json
  snapshots.parquet
```

```
snapshots(
  snapshot_id      : Utf8!,      # uuid — a ÚNICA âncora de linhagem da decisão
  line_id, bar_id, decision_ts_ns,
  bundle_id        : Utf8!,      # ver 4.16
  feature_vector   : List[Float64]!,   # ordem = feature_manifest do design_hash
  design_hash      : Utf8!,
  regime_state_id, regime_p_state, state_age_bars,
  p_cal, p_meta    : Float64,
  portfolio { equity, open_positions, margin_ratio, risk_budget_remaining },
  source_versions  : Struct!,    # {D01: v, D03: v, E01: v, ...}
  data_health      : Struct!     # staleness por fonte no instante da decisão
)
```

**A regra que justifica o artefato inteiro:** *toda decisão a jusante consome exatamente um `snapshot_id` imutável*. Em vez de perguntar "qual era o regime às 14:31:02?" — pergunta que exige reconstruir de várias fontes e que portanto não é auditoria — pergunta-se "qual `snapshot_id` originou esta ordem?" e percorre-se a linhagem. Sem isso, cada estágio inventa sua própria interpretação de "dados disponíveis naquele instante", que é o risco arquitetural dominante numa cadeia com 11 fronteiras.

`data_health` embutido resolve de quebra a lacuna do §4.9: a decisão carrega a prova de que nenhuma fonte estava obsoleta quando foi tomada.

---

### 4.15 `promotion/` — ⟳ X-02, o artefato que congela a rodada

```
promotion/selection_run_id={id}/
  _SUCCESS  manifest.json
  promotion_manifest.json
```

```json
{
  "selection_run_id": "SEL-2026Q3-001",
  "effective_from_ns": 1789000000000000000,
  "effective_until_ns": null,
  "promoted_lines": [
    {"line_id": "SOLUSDT:R3", "bundle_id": "BND-2026-08-19-004", "rank": 1,
     "selection_metric": "dsr", "dsr_p": 0.021, "pbo": 0.18,
     "validation_key": "a91c...", "holdout_touched": false}
  ],
  "rejected_lines": [
    {"line_id": "BTCUSDT:R1", "reason_code": "COST_HURDLE_ABOVE_ACHIEVED_WR"},
    {"line_id": "XRPUSDT:R1", "reason_code": "PBO_ABOVE_THRESHOLD"}
  ],
  "n_trials_registered": 41, "n_eff_trials": 2.3,
  "portfolio_policy_version": "RK-009",
  "decision_policy_version": "DE-005"
}
```

**A regra:** produção carrega **este arquivo**, e nada mais decide o que está ativo. Nunca `if model.score > threshold: active = True` em runtime — seleção é offline por mandato, e sem um manifesto congelado "linha promovida" é estado implícito espalhado pelo código. `rejected_lines` com `reason_code` é o que permite a próxima rodada saber o que já foi eliminado e por quê, sem recontar como trial novo.

---

### 4.16 `bundle/` — ⟳ X-03, compatibilidade de conjunto

```json
{
  "bundle_id": "BND-2026-08-19-004",
  "feature_manifest_hash": "e91b...", "label_config_hash": "b3f2...",
  "weights_config_hash": "77aa...", "split_id": "S3",
  "regime_bundle": {"method_id": "baseline_quantile", "config_hash": "9c31..."},
  "alpha_model": {"model_id": "...", "content_hash": "..."},
  "calibration": {"calibrator_config_hash": "..."},
  "meta_model": null,
  "decision_policy": "DE-005", "risk_policy": "RK-009", "execution_policy": "EX-003",
  "dependency_graph_complete": true
}
```

**A regra:** *produção só carrega um bundle cujo grafo de dependências esteja completo e cujos hashes casem com os declarados no `PromotionManifest`*. A cadeia de hash (INV-B) prova cada artefato **isoladamente**; o `validation_key` (V-03) cobre a combinação **offline**. Nada cobria a combinação em **runtime** — Alpha novo + regime antigo + schema de feature parcialmente novo + calibração antiga é um conjunto em que cada peça tem manifesto válido e o todo é inválido. `bundle/compatibility` rejeita isso **antes de qualquer ordem chegar à Binance**.

---

### 4.17 `runtime/{date}/dropped_signals.jsonl` — ⟳ X-08

```
{"ts_ns":..., "snapshot_id":"...", "line_id":"SOLUSDT:R3", "side":"long",
 "p_cal":0.61, "p_meta":0.54,
 "drop_reason":"DROPPED_BY_RISK_CAP"}
```

`drop_reason` é `pl.Enum` fechado: `DROPPED_BY_REGIME_GATE | DROPPED_BY_LINE_GATE | DROPPED_BY_SYMBOL_EXPOSURE | DROPPED_BY_RISK_CAP | DROPPED_BY_MARGIN_RATIO | DROPPED_BY_DAILY_LOSS | DROPPED_BY_STALE_LEDGER | DROPPED_BY_MIN_NOTIONAL | DROPPED_BY_META_VETO | TIMEOUT_MAKER_UNFILLED | REJECTED_GTX_WOULD_CROSS`.

Sem esta tabela existe **viés de sobrevivência de sinal**: o backtest e o monitoramento veem apenas os trades que aconteceram, e é impossível distinguir "o Alpha é fraco" de "os gates estão superdimensionados". `drop_rate_by_reason` entra no `validation_report` como métrica de primeira classe. Custo próximo de zero; sem ela, atribuição de performance é impossível.

Note que `DROPPED_BY_MIN_NOTIONAL` e `REJECTED_GTX_WOULD_CROSS` são categorias que só existem por causa dos achados N-02 e §1.2 — nenhuma das três auditorias externas as teria previsto.

---

## 5. A canonicalização de estado, em código

Referenciada em §3.4 e §4.6 do parecer, e a única parte deste anexo que é algoritmo e não schema:

```python
def canonicalize_states(
    raw_states: np.ndarray,      # saída do decoder, índices arbitrários
    train_features: np.ndarray,  # espaço de observação DO FOLD DE TREINO
    order_stat: Callable = lambda x: np.std(x, axis=0)[1],  # vol realizada
) -> tuple[np.ndarray, np.ndarray, dict[int, int]]:
    """Reindexação determinística de estados por estatística monótona ascendente.

    Sem isto, state_id=2 significa coisas diferentes em folds diferentes:
    HMM e modelos de mistura são invariantes a permutação de rótulos.
    """
    stats = np.array([
        order_stat(train_features[raw_states == k]) if (raw_states == k).any() else np.inf
        for k in range(raw_states.max() + 1)
    ])
    perm = np.argsort(stats, kind="stable")        # stable: empate resolve por índice
    remap = {int(old): int(new) for new, old in enumerate(perm)}
    return np.array([remap[s] for s in raw_states]), stats[perm], remap
```

`remap` vai para o `manifest.json` do artefato de regime. Se o `remap` mudar entre folds, isso é visível — e a verificação retroativa que proponho em §4.6 do parecer é exatamente: extrair `remap` de cada fold da Trilha A e ver se ele é constante. Se não for, os testes de heterogeneidade rodaram sobre rótulos embaralhados.

`order_stat` é volatilidade realizada por default porque é a dimensão em que os regimes de vocês são mais separáveis e porque é monótona e interpretável. Para o BOCPD, a estatística natural é a run-length média do bucket, não a vol.

---

## 6. Mapa código → artefato

Quem escreve o quê. Caminhos são **proposta**, exceto os quatro que os seus documentos citam.

| Módulo | Artefato produzido | Status |
|---|---|---|
| `src/bars/dollar_bars.py` | `bars/` | `[PRECISO SABER]` caminho real |
| `src/features/build.py` | `features/` | **existe** — é onde `T1_FEATURE_IDS` está travado (linhas 29-40) |
| `src/features/registry.py` | lê `registry.yaml`, deriva `feature_manifest` | novo; o registry já é a fonte de verdade declarada (§2.14 do PRD), este módulo só o projeta |
| `src/regime/classifier.py`, `hmm_gaussian.py`, `jump_model.py`, `bocpd.py` | `regime/` | **existem**; falta o adaptador de schema comum + `canonicalize_states` |
| `src/regime/contract.py` | valida `decode_mode`, aplica canonicalização | novo — é onde o Jump Model é rejeitado mecanicamente |
| `src/labels/triple_barrier.py` | `labels/` | `[PRECISO SABER]` |
| `weights.py` | `weights/` | **existe** — falta `concurrency_scope` e `n_eff` no manifest |
| `src/splits/cpcv.py` | `splits/` | falta o calendário mestre |
| `src/design/assemble.py` | `design/` | novo — substitui `DESIGN_COLUMNS` literal |
| `src/learner/xgb_fit.py` | `models/` + `oof_predictions.parquet` | |
| `src/calibration/fit.py` | `calibration/` | hoje inline no Learner (§3.5 do parecer: separar) |
| `src/validation/run.py` | `validation/` | existe como código, não conectado (§7 do brief) |
| `src/validation/pbo.py` | `pbo_matrix.parquet` | **não existe** — a perna capenga |
| `src/registry/trials.py` | `trial_registry/` | novo — substitui `N_lifetime` manual |
| `src/snapshot/build.py` | `snapshot/` | novo — ⟳ X-01 |
| `src/promotion/manifest.py` | `promotion/` | novo — ⟳ X-02 |
| `src/bundle/compatibility.py` | `bundle/` | novo — ⟳ X-03; roda **antes** de qualquer ordem |
| `src/decision/line_state.py` | máquina de estados + `SymbolExposure` | novo — ⟳ X-04 + N-01 |
| `src/io/artifact.py` | escrita atômica, manifest, hash canônico | **é o módulo central**; escrever primeiro |
| `src/io/schema.py` | `schema.json`, validação no writer e no reader | idem |

**Ordem de construção sugerida:** `src/io/artifact.py` + `src/io/schema.py` antes de qualquer outro. Todo o resto é uma aplicação desses dois. Construí-los depois significa retrofitar proveniência em artefatos já existentes, que é o tipo de trabalho que nunca acontece.

---

## 7. Os testes que cada artefato obriga

Um teste parametrizado por invariante, varrendo todos os artefatos — não um teste por estágio:

```python
@pytest.mark.parametrize("artifact", all_artifacts())
def test_inv_a_chave_unica(artifact):
    df = read(artifact)
    assert df.select(artifact.primary_key).is_unique().all()
    assert df["bar_id"].is_sorted()

@pytest.mark.parametrize("artifact", all_artifacts())
def test_inv_b_cadeia_de_hash(artifact):
    m = artifact.manifest
    assert m["content_hash"] == recompute_content_hash(artifact)
    for up in m["upstream"]:
        assert load_manifest(up).hash() == up["manifest_hash"]

@pytest.mark.parametrize("col", all_feature_columns())
def test_inv_c_causalidade_declarada(col):
    assert col.causality_class in {"strict_past", "at_close"}
    assert col.availability_lag_ns is not None

@pytest.mark.parametrize("col,t", sample_feature_timepoints(n=200))
def test_inv_d_paridade(col, t):                        # ⟲ V-04
    truncado = compute_online(col, data_until=bar_close_ts(t))
    armazenado = read_stored(col, t)
    if col.parity_class == "exact":
        assert truncado == armazenado                   # sem tolerância
    else:
        assert ulp_distance(truncado, armazenado) <= col.ulp_budget
```

O quarto é o mais importante e o mais barato de escrever uma vez: **um único teste parametrizado sobre o `feature_manifest` cobre as ~92 features e todas as 11 fronteiras**. É a diferença entre paridade treino-live ser uma propriedade verificada e ser uma intenção documentada.

Dois testes adicionais que não são invariante mas pegam bug real:

```python
def test_labels_sem_unresolved_tratado_como_vertical(labels):
    tail = labels.filter(pl.col("bar_id") > labels["bar_id"].max() - HORIZON_BARS)
    assert (tail["barrier"] == "unresolved").all()   # a cauda NÃO pode virar vertical

def test_regime_remap_estavel_entre_folds(regime_artifacts):
    remaps = [a.manifest["canonicalization"]["remap"] for a in regime_artifacts]
    assert len(set(map(json.dumps, remaps))) == 1    # §4.6 do parecer
```

---

## 8. Retenção e coleta de lixo — ⟲ V-11

Imutabilidade sem política de retenção é crescimento ilimitado. A proposta original não tinha esta seção; sem ela, o desenho é correto e insustentável.

**Regra de retenção (três classes):**

```
PERMANENTE   artefatos referenciados por um modelo PROMOVIDO
             + todo o trial_registry (trials/ e returns/)
             + todo validation/ com verdict != INCONCLUSIVE
             → nunca coletados; são a memória estatística do projeto

RETIDO       artefatos da rodada de seleção vigente + da rodada anterior
             → coletados na promoção da rodada seguinte

EFÊMERO      diretórios sem _SUCCESS (escrita interrompida)
             + qualquer coisa sob scratch/
             → coletados imediatamente, sem confirmação
```

O `trial_registry` é permanente e é barato: uma linha JSON e uma série de retorno por trial. Ele é o que impede a contagem de trials de voltar a ser um número que alguém lembra — e o custo de guardá-lo para sempre é irrisório perto do custo de perdê-lo.

**O comando que torna o desenho utilizável:**

```
$ pipeline impact --dry-run --change cost_model.maker_fee_bps=2.5

Invalida 4 estágios × 15 linhas = 312 artefatos (48,2 GB)
  labels/      15 artefatos    3,1 GB
  weights/     15 artefatos    0,4 GB
  design/      15 artefatos   41,0 GB
  models/     135 artefatos    2,9 GB   (9 folds × 15 linhas)
  validation/ 132 artefatos    0,8 GB
Recomputação estimada: ~6,4 h
Modelos promovidos afetados: 2 (BTCUSDT:R3, SOLUSDT:R3) → exigem revalidação
```

Sem isso, a invalidação em cascata — que é a propriedade **desejada** do desenho — vira uma surpresa desagradável na primeira vez que alguém ajusta o modelo de custo, e a reação natural é contornar o mecanismo. Um desenho correto que as pessoas contornam é pior do que um desenho frouxo que elas seguem. `impact --dry-run` deve ser escrito junto com o writer, não depois.

---

## 9. Resumo em uma tela

| Arquivo | Existe em | Contém |
|---|---|---|
| `part-*.parquet` | todo artefato tabular | os dados, schema fixo, ordenado por `bar_id`, particionado por `symbol/resolution` |
| `manifest.json` | todo artefato | proveniência (`producer_version`, `config_hash`, `upstream`), estatísticas por coluna (que viram gates), `content_hash`, bloco de causalidade, bloco de determinismo |
| `config.json` | todo artefato | o subtree de config resolvido que gerou o `config_hash`; floats como string |
| `schema.json` | todo artefato | schema Arrow + `primary_key` + `checks`, validado no writer **e** no reader |
| `_SUCCESS` | todo artefato | marcador vazio, escrito por último; ausência = artefato inválido |
| `model.ubj` | `models/` | booster XGBoost em formato nativo, nunca pickle |
| `feature_names.json` | `models/` | ordem exata das colunas no fit — pega reordenação silenciosa |
| `oof_predictions.parquet` | `models/` | `p_raw` out-of-fold; insumo obrigatório de calibração e Meta |
| `calibrator.json` | `calibration/` | coeficientes A/B do Platt + `n_cal_eff`; aplicação ao vivo sem sklearn |
| `report.json` / `pbo_matrix.parquet` | `validation/` | veredito + a matriz CSCV que hoje não existe |
| `trials/{id}.json` + `returns/*.parquet` | `trial_registry/` | um arquivo por trial (⟲ V-06 — append concorrente corrompe no Windows); é o que torna `N_eff` calculável em vez de lembrado |
| `*.jsonl` | `runtime/{date}/` | intents, orders, fills, account; preço/qty em **inteiros de tick/step**, com os filtros vigentes congelados no evento |
