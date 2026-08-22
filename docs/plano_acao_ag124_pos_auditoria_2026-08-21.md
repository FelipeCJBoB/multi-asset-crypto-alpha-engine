# Plano de ação — AG-124, pós-auditoria externa (3 documentos)

**Data:** 2026-08-21
**Papel:** validação de engenharia sobre 3 documentos de retorno da auditoria externa do
brief `docs/brief_auditoria_externa_2026-08-21_calibracao_causal_dollar_bar_ag124.md`.
**Entrada:** `docs/Retorno_Brief/parecer_auditoria_externa_ag124_calibracao_causal.md` (doc 2,
parecer técnico rigoroso), `docs/Retorno_Brief/adendo_pareceres_ag118_ag124_pos_respostas.md`
(doc 1, adendo pós-respostas do desenvolvedor/manager), `docs/Retorno_Brief/relatorio_auditoria_externa_2026-08-21.md`
(doc 3, relatório "definitivo" — **ver §0, não confiável**).
**Status:** ordem de execução autorizada pelo Manager, 2026-08-21.

---

## 0. Confiabilidade do doc 3 — não usar como fonte de decisão

Verificado contra o código/ledger real, não por estilo:

- **Colisão de numeração `AG-125`.** Doc 3 sugere `AG-125` pro ticket de filtro de
  bad prints. `AG-125` já existe no ledger, registrado no mesmo dia (2026-08-21),
  sobre assunto completamente diferente (`QualityReport` sem campo `symbol`,
  `audit/architecture_gaps_log.yaml:8922`, status "fechado"). Um número de ticket
  real citado errado, com confiança total, é o tipo de erro que só aparece quando o
  texto não foi checado contra o repositório.
- **"Sabatina técnica com engenharia e governança"** — não houve nenhuma sessão
  desse tipo. O documento descreve um processo que não ocorreu como se tivesse
  ocorrido.
- **Claim de `zstd`/dictionary encoding** sobre `threshold_quote` — busca por
  `compression`/`zstd` em `src/data/bars.py` inteiro: zero ocorrências. Afirmação
  técnica sem onde se apoiar no arquivo citado.
- **Conclusão central ("RATIFICADO 7/7", "aguardar reprocessamento até o Data
  Layer")** contradiz de forma direta o parecer do doc 2, tecnicamente mais
  cuidadoso (mostra com números que W=1 vence a métrica bruta em 3 dos 5 símbolos;
  que a sazonalidade restringe `trailing_window`, não `cadence`; que `T=7/C=1`
  nunca foi medido). Doc 3 trata como resolvido o que doc 2 mostra que não está.
- Confunde o gate real "Alpha só retreina com Data Layer 100%" com "reprocessar
  dollar-bar tem que esperar o Data Layer" — são decisões independentes.
- **"Métrica canônica de sucesso" com `CV_N ≤ 0,40`** — limiar numérico inventado,
  sem medição, exatamente o padrão que o próprio projeto proíbe (B23, "nunca
  inventar faixa esperada — `TBD — medir`"). Ironicamente o doc 3 viola a mesma
  disciplina que ele mesmo deveria estar auditando.
- **"Embargo do CPCV deve subir pra ≥7 dias"** — contradiz o doc 2 (CPCV já opera
  em timestamp, sem necessidade de mudança, achado que **simplificou** o desenho) e
  mudaria `cpcv_embargo_ms` (`MEASURED`, `config/constants.yaml:1151`) sem nenhuma
  medição nova.

**Tratamento**: as conclusões do doc 3 não entram como evidência. Das suas 5
"insights", 1 sobrevive à checagem individual (lead-in buffer, item 15) e 1 vira
item de baixa prioridade pra investigar (mega-trades, item 25) — o resto é
descartado (itens 26-29).

---

## 1. Duas correções de enquadramento (verificadas contra código, não contra os pareceres)

**`tp_atr_mult`/`sl_atr_mult` já são classe A com sweep mandatado — não é gap de
classificação.** `config/constants.yaml:164-180`: ambos `class: A`,
`sweep_required: true`, `sweep_range` já declarado (`[1.0,3.0]` / `[0.75,2.25]`),
`review_by: sprint_6`. O gap real não é classificação — é execução: o sweep nunca
rodou desde o sprint 6. Não muda a prioridade (concordo que é o maior buraco
aberto), só o enquadramento (item 17).

**`regime_tradeable: bool` já está wireado, HOJE, não é pendência de desenho.**
`src/risk/limits.py:127,511,548` confirma tipo `bool`, `src/regime/build_hmm.py:111`
confirma `build_hmm_regimes` implementado, `PLANO_MESTRE_PRINCE2.md` §15.13
confirma "(2026-08-21)". O que não existe é loop vivo de produção populando isso
continuamente (`src/live/` vazio) — decisão de reconfirmar via M5 ou desligar
continua em aberto (item 18).

---

## 2. Tabela completa — todos os itens dos 3 documentos

| # | Item | Categoria | Fonte |
|---|---|---|---|
| 1 | Corrigir prosa do brief §3 + docstring de `_calibration_errors_for_window` (rolling, não "calibra-aplica-pula") | Fix Mecânico | Doc 1 §1.2 (retratação Q9) |
| 2 | Retratação: HMM não é in-sample (walk-forward genuíno por fold) | Descartado — registrar retratação | Doc 1 §1.1 |
| 3 | `_trailing_calibration_window` correto, sem vazamento residual | Descartado | Doc 2 §6 |
| 4 | CPCV já opera em timestamp, não em bar-id — não exige mudança | Descartado | Doc 2 §6, Doc 1 §7 |
| 5 | Cold-start descarta 1º período por símbolo — decisão válida, mas ver item 15 | Descartado (superado por item 15) | Doc 2 §6 |
| 6 | M1 — sweep do corte de erro (0,4/0,5/0,6 e 1,7/2,0/2,5) | Teste de Validação | Doc 2 §2.1/§5, Doc 1 §2.3 |
| 7 | M2 — preencher grid W=5,6,8,9,13,15 | Teste de Validação | Doc 2 §1.2/§4 Q6/§5 |
| 8 | M3 — desacoplar `trailing_window` de `cadence` no script de análise | Fix Mecânico | Doc 2 §4 Q2/§5 |
| 9 | Medir `T=7,C=1` vs. `7/7` (depende do item 8) | Teste de Validação | Doc 2 §4 Q2, Doc 1 §4 |
| 10 | M4 — trocar contagem binária por distribuição da razão estratificada por dia-da-semana | Redesenho (metodologia de análise) | Doc 2 §2.2/§2.3/§5 |
| 11 | Medir autocorrelação e curtose dos retornos de barra por candidato de janela (3ª/4ª âncora da literatura de activity bars) | Teste de Validação | Doc 2 §2.2 |
| 12 | M5 — rodar AG-118 (Gate Efficiency) em k=2 e k=3, não só k=4 vencedor | Teste de Validação | Doc 1 §2.3/§5 |
| 13 | B0 — varredura de integridade dedicada, causa raiz do AG-120, todas as células | Teste de Validação (com ressalva: tooling novo) | Doc 1 §3.3/§5 |
| 14 | B1/B2 — `ThresholdBarsCarry` preservado através da fronteira de período | Redesenho pequeno | Doc 2 §3/§5, Doc 1 §4 |
| 15 | Lead-in buffer pro cold-start (estender range de LEITURA de trades, não de saída) | Redesenho pequeno | Doc 3 (única ideia aproveitável) |
| 16 | Circuit breaker (`max_leftover_trades`) — confirmar `safety_mult` cobre pico ~14x medido na rodada diária | Teste de Validação | Doc 1 §4 pergunta 5 original, Doc 2 §4 Q5/§5 |
| 17 | S1 — sweep 2D de `tp_atr_mult`/`sl_atr_mult` sob §16.10 (já classe A) | Teste de Validação — maior prioridade | Doc 1 §3.1/§5 |
| 18 | Decisão `regime_tradeable`=HMM k4 — reconfirmar via item 12 ou desligar | Decisão do Manager | Doc 1 §3.2/§5 |
| 19 | Mandato de estágio V1 não sustenta "1,8x importa?" — critério passa a ser preservar opcionalidade | Nota de governança | Doc 1 §3.4 |
| 20 | Pré-registrar AGORA se a decisão sobre `trailing_window_days` reabre caso M1-M4 contradigam 7 | Decisão do Manager, pendente | Doc 1 §5 |
| 21 | Atribuir dono/prioridade pro re-run de M4/AG-114/AG-118 pós-reprocessamento | Decisão do Manager, pendente | Doc 1 §5 |
| 22 | Verificação pós-reprocessamento sobre dado REAL (dispersão barras/dia por dia-da-semana, autocorrelação, curtose) — não cerimonial | Teste de Validação, ocorre DEPOIS do reprocessamento | Doc 2 §5 |
| 23 | Piso de p-valor confirmado (1000 permutações → p_min≈0,000999) — nenhum p=0,001 do AG-114 é comparável entre si | Nota de leitura/documentação | Doc 1 §2.2 |
| 24 | Regra de processo: todo limiar de corte que separa candidatos exige sweep | Proposta de política pro Manager | Doc 1 §5, Doc 2 §2.1 |
| 25 | Mega-trades / barras O=H=L=C simultâneas quando 1 trade > threshold — flag `is_subdivided_trade` | Teste de Validação primeiro (checar frequência real), baixa prioridade | Doc 3 (fonte não confiável, mas logicamente plausível) |
| 26 | Vertical barrier em contagem de dollar-bars vs. `horizon_end_ms` fixo | Teste de Validação/discussão, sem decisão automática | Doc 3, verificado: trade-off real, não ganho óbvio |
| 27 | "Métrica canônica de sucesso" `CV_N ≤ 0,40` | Descartado — viola B23 | Doc 3 |
| 28 | "Embargo CPCV deve subir pra ≥7 dias" | Descartado — contradiz doc 2, mudaria constante MEASURED sem medição | Doc 3 |
| 29 | `threshold_quote` como feature de regime/liquidez | Descartado — fora de escopo do AG-124, precisaria de processo T2/registry próprio | Doc 3 |
| 30 | Menção a AG-036 (modelos downstream, `horizon_minutes`) | Descartado — real, mas já rastreado separadamente, fora de escopo desta decisão | Doc 3 (verificado: ticket existe de fato) |
| 31 | Parametrização global 7/7 pros 5 ativos (não por-ativo) | Descartado — não contestado por doc 1/doc 2, mantido sem decisão nova | Doc 3 |

---

## 3. Detalhe dos itens acionáveis (Fix Mecânico / Teste de Validação / Redesenho)

### Fix Mecânico

**Item 1 — prosa imprecisa.** O código de `_calibration_errors_for_window`
(`tools/diagnostics/analyze_dollar_threshold_calibration_error.py:105-133`) está
correto — `block_start += window` faz cada bloco de aplicação virar o bloco de
calibração da iteração seguinte (rolling), batendo com o que
`build_dollar_bars_walkforward` faz na produção. A prosa do brief §3 ("o primeiro
bloco calibra, o segundo aplica") describe como se fosse um par fixo que depois
pula — engana sobre o mecanismo real. Corrigir os dois textos (brief + docstring)
pra deixar explícito o reuso rolling.

**Item 8 — desacoplar `trailing_window` de `cadence` no script.** Hoje
`_calibration_errors_for_window(rows, window)` usa o MESMO `window` pros dois
papéis. Mudar assinatura pra `_calibration_errors_for_window(rows, *, trailing,
cadence)`: `calib_block = rows[i-trailing:i]`, `apply_block = rows[i:i+cadence]`,
avança `block_start += cadence`. `--windows` do CLI vira 2 argumentos
(`--trailing`/`--cadence`), com default `cadence=trailing` pra preservar 100% o
comportamento atual quando não usado. Habilita o item 9 sem tocar produção.

### Teste de Validação (roda sobre JSON/artefato já existente, sem mudar produção)

**Item 6 — M1.** Rodar `analyze()` com `_ERROR_HIGH_MULT`/`_ERROR_LOW_MULT`
parametrizados (hoje são constantes de módulo, precisam virar argumento de CLI) em
0,4/1,7 e 0,6/2,5, sobre `dollar_threshold_drift_daily.json`. Confirma se o
ranking W=1,2,4,7 sobrevive ao corte escolhido.

**Item 7 — M2.** `--windows` já aceita lista arbitrária — rodar direto com
`5 6 8 9 13 15` sobre o relatório diário, sem editar código.

**Item 9 — T=7,C=1.** Depende do item 8. Único teste que separa "sazonalidade
resolvida pela FONTE de calibração" de "sazonalidade resolvida pela cadência
curta" — é o ponto central da correção de leitura do doc 2 §4 Q2.

**Item 11 — autocorrelação/curtose por candidato de janela.** As 2 âncoras que o
doc 2 propõe além da razão binária (`§2.2`): autocorrelação de retornos de barra e
curtose/normalidade, POR candidato de `trailing_window`/`cadence`. Precisa
reconstruir barras sintéticas por candidato (não só ler `dollar_per_day` do JSON
de deriva) — maior custo que M1/M2/M3, mas ainda sem tocar produção.

**Item 12 — M5.** `RawLabels` de k2/k3/k4 já persistidos em
`experiments/m4_raw_labels/`. Rodar a medição de Gate Efficiency (AG-118) nos 3,
não só no vencedor k4. Custo de refit: zero.

**Item 13 — B0.** Não existe hoje uma ferramenta de varredura de integridade
cross-célula pra rastrear a causa raiz do AG-120 (desalinhamento BNBUSDT/RECENTE/
R2, isolado mas nunca investigado). Precisa de script novo — propósito é
diagnóstico puro, não muda produção, mas como a causa raiz é desconhecida, o
resultado não é garantido de antemão (é investigação, não fix).

**Item 16 — circuit breaker.** `max_leftover_trades` já existe e já é real
(`src/data/bars.py:215-232`, `LeftoverOverflowError`), calibrado dinamicamente por
período (`avg_trades_per_bar * safety_mult`, `src/data/build_dollar_bars.py:256`),
threadado até `build_dollar_bars_walkforward`. Não é gap de desenho — é confirmar
se `safety_mult` (provavelmente calibrado sob premissa de granularidade mensal)
ainda cobre o pico de ~14x achado na medição diária. Caso sintético com burst
14-15x é suficiente.

**Item 17 — S1, maior prioridade.** Grid 2D já declarado em `constants.yaml`
(`sweep_range` de `tp_atr_mult`/`sl_atr_mult`). Redefine a variável dependente de
TODO experimento já rodado (AG-118, AG-114, M6). Maior escopo de todos os itens —
precisa de uma etapa de desenho curta antes de rodar cego (quantos pontos de
grade, o que conta como "robustez na vizinhança" per §16.10 — não é "Sharpe bom no
valor escolhido").

**Item 22 — verificação pós-reprocessamento.** Só roda DEPOIS do reprocessamento
real dos 5 símbolos — dispersão de barras-por-dia por dia-da-semana, autocorrelação
de retornos, curtose, sobre o dado real. "Não como validação cerimonial" (doc 2
§5) — é a primeira medição de impacto real que o projeto terá sobre esta decisão.

**Item 25 — mega-trades.** Checar primeiro se um único trade com volume >
`threshold_usdt` de fato ocorre nos dados reais (5 símbolos, 6+ anos) e com que
frequência, antes de decidir se vale adicionar `is_subdivided_trade`. Prioridade
baixa (fonte não confiável), mas logicamente plausível — `bar_id = cum_value //
threshold` de fato pode emitir múltiplas barras `O=H=L=C` no mesmo trade.

### Redesenho (toca produção, `src/data/`)

**Item 10 — M4, trocar métrica de decisão.** Muda o que
`analyze_dollar_threshold_calibration_error.py` reporta e como a decisão de
`trailing_window`/`cadence` é lida — de contagem binária (≥2x/≤0,5x) pra
distribuição da razão estratificada por dia-da-semana. Só toca
`tools/diagnostics/`, não `src/data/` — mas é mudança de metodologia/critério de
decisão, não ajuste mecânico.

**Item 14 — carry através da fronteira.** `ThresholdBarsCarry`
(`src/data/bars.py:298`) já é estado pequeno e preservável (`threshold`,
`value_kind`, `leftover: _TradeArrays`, `base_value`, `bar_frames`,
`max_leftover_trades`). "Preservar através da fronteira" muda o contrato de
`build_dollar_bars_walkforward` (hoje cada período recomeça do zero,
`threshold_bars_finish` sempre roda no fim de cada janela). Sob `cadence_days=7`
fica opcional ("faça na mesma mudança que o item 15"); sob `cadence_days=1` (se o
item 9 confirmar `T=7,C=1`) vira pré-condição — sem isso, cadência diária
multiplica as fronteiras truncadas de ~52/ano pra ~365/ano.

**Item 15 — lead-in buffer.** Em vez de descartar o 1º período de cada símbolo
por cold-start, estender só o RANGE DE LEITURA de trades brutos pra
`start - trailing_window_days` (nunca o range de saída de barras) — mesma regra
causal (só passado), recupera a 1ª semana de cada símbolo em vez de perdê-la.
Toca `build_dollar_bars_walkforward` (`src/data/build_dollar_bars.py`).

---

## 4. Decisões do Manager (não são bucket de engenharia — registradas pra não perder)

- **Item 18** — reconfirmar `regime_tradeable`=HMM k4 via resultado do item 12, ou
  desligar até haver evidência nova.
- **Item 19** — sob o mandato de estágio V1 (infraestrutura, não edge provado),
  perguntas tipo "lift de 1,4 é bom?" são mal-postas; critério de decisão vira
  preservar opcionalidade / minimizar compromissos irreversíveis.
- **Item 20** — pré-registrar AGORA (antes de ver os resultados de M1-M4) se a
  decisão sobre `trailing_window_days=7` reabre caso a medição contradiga —
  responder depois de ver os números elimina o valor de ter perguntado
  (disciplina anti-HARKing, B20).
- **Item 21** — atribuir dono e prioridade pro re-run de M4/AG-114/AG-118
  pós-reprocessamento — hoje reconhecido como provisório, mas não atribuído.
- **Item 24** — adotar como regra de processo: todo limiar de corte que separa
  candidatos exige sweep de sensibilidade, mesma disciplina que §16.10 já aplica a
  constante classe A (pega o teto de 40% do Gate 1/AG-114 e o corte 2x/0,5x deste
  AG-124 — 2 casos reais, mesmo padrão, 2 auditorias diferentes).

---

## 5. Ordem de execução — v1, autorizada 2026-08-21 (SUPERSEDIDA, ver §7)

1. ~~S1~~ 2. ~~M1+M2~~ 3. ~~M3→M4~~ 4. M5 5. B0 6. carry+lead-in 7. breaker 8. travar.

Superada pela ordem v2 (§7) depois da execução real de 1-9 revelar uma
dependência que a v1 não tinha capturado: item 11 (autocorrelação/curtose)
precisa de barras REAIS construídas sob cada candidato — sob `cadence_days=1`
isso expõe o artefato de truncamento do item 14 se ele não for corrigido
ANTES da medição, não depois. A v1 tinha os dois na ordem trocada.

---

## 7. Ordem de execução — v2 (reordenada 2026-08-21, com base nos 31 itens + execução real)

**Fase 1 — Fechada.** Itens 1, 6, 7, 8, 9 (fix mecânico + M1/M2/M3, ver §6).
Achado principal: `T=7,C=1` domina `T=7,C=7` nos 5 símbolos (-2,85 a
-6,19pp).

**Fase 1.5 — Fechada.** Teste `T=3,C=1` (brainstorming do Manager, ver §8).
Achado: **PIOR** que `T=7,C=1` pra BTC/ETH (+3,6pp), neutro pros outros 3 —
confirma que `trailing_window` precisa ficar em 7 (ou múltiplo), a
independência é só de `cadence`.

**Fase 2 — ✅ CONCLUÍDA (2026-08-21, ver §9).** `ThresholdBarsCarry`
não pode continuar resetando a cada período pra qualquer medição futura que
construa barras reais sob `cadence_days=1` ser válida — senão o artefato de
truncamento (~365 fronteiras/ano) contamina a própria medição que deveria
avaliar o candidato limpo.
- **Item 14** — carry através da fronteira de período (`src/data/bars.py`,
  `src/data/build_dollar_bars.py::build_dollar_bars_walkforward`).
- **Item 15** — lead-in buffer pro cold-start (mesmo arquivo, mesma mudança).
- **Item 16** — circuit breaker (`max_leftover_trades`/`safety_mult`) contra
  o pico ~14x medido na rodada diária — mesma vizinhança de código, faz
  sentido junto.

**Fase 3 — 2ª lente, sobre barras reais (amostra, não histórico inteiro).**
- **Item 11** — autocorrelação/curtose de retornos de barra, `T=7,C=7` vs.
  `T=7,C=1` (e opcionalmente `T=3,C=1` pra fechar o ciclo do brainstorming).
  Só é válido DEPOIS da Fase 2.

**Fase 4 — Gate de integridade, antes de tocar 6 anos × 5 símbolos.**
- **Item 13** — B0, varredura dedicada da causa raiz do AG-120.

**Fase 5 — Travar, reprocessar, validar.**
- Travar `trailing_window_days=7`, `cadence_days=1` — pendente confirmação
  formal do Manager (itens 20/24, mesma fase).
- Reprocessar os 5 símbolos (autorização operacional separada da de
  medição, per `AG-124` resolution original).
- **Item 22** — validação pós-reprocessamento sobre dado real (dispersão
  barras/dia por dia-da-semana, autocorrelação, curtose) — não cerimonial.

**Fase 6 — Trilha paralela, independente do dollar-bar (regime HMM).**
Não bloqueia nem é bloqueada pelas Fases 1-5 — pode intercalar a qualquer
momento.
- **Item 12** — M5, AG-118 em k2/k3 (custo de refit zero).
- **Item 18** — decisão do Manager sobre `regime_tradeable`, informada por 12.

**Fase 7 — Trilha paralela, maior escopo isolado (tp/sl).**
Também independente das Fases 1-5 (toca `src/labels/`, não `src/data/`) —
mas é o item de maior alavancagem segundo o doc 1 (redefine a variável
dependente de todo experimento já rodado). Precisa de desenho de escopo
antes de rodar às cegas.
- **Item 17/S1** — grid 2D de `tp_atr_mult`/`sl_atr_mult`, definição
  operacional de "robustez na vizinhança" (§16.10), depois sweep real.

**Fase 8 — Documentação/governança, baixo custo, entram a qualquer momento.**
- **Item 10** — M4 (rebaixado: o mecanismo já foi confirmado por 2 vias
  independentes — item 9/T=7,C=1 e o teste T=3,C=1 — redesenhar a métrica de
  binária pra distribuição continua válido, mas não é mais bloqueante da
  decisão, só refinamento de relatório futuro).
- **Item 23** — nota de leitura sobre piso de p-valor (AG-114).
- **Item 24** — proposta de política (sweep de todo limiar de corte).
- **Item 19** — nota de governança (mandato V1, preservar opcionalidade).
- **Itens 20/21** — decisões pendentes do Manager (reabertura de `T=7`;
  dono do re-run de M4/AG-114/AG-118 pós-reprocessamento).

**Backlog, baixa prioridade.**
- Item 25 — mega-trades/`is_subdivided_trade` (checar frequência real antes).
- Item 26 — vertical barrier em contagem de bars vs. `horizon_end_ms` (trade-off
  não óbvio, não é ganho automático).

**Descartados, sem ação.** Itens 2, 3, 4, 5 (retratações/confirmados), 27,
28, 29, 30, 31 (doc 3, não sobrevivem à checagem).

Nenhum item toca produção além de `build_dollar_bars_walkforward`/
`ThresholdBarsCarry` (itens 14 e 15, Fase 2) e do label engine (item 17,
Fase 7). O resto é ferramenta de diagnóstico ou reprocessamento de
artefato já existente.

---

## 8. Teste extra — `T=3,C=1` (brainstorming do Manager, 2026-08-21)

Medido sobre `dollar_threshold_drift_daily.json`
(`experiments/dollar_threshold_calibration_error_daily_T3_C1.json`):

| símbolo | T=7,C=1 | T=3,C=1 | Δ (T3 − T7) |
|---|---:|---:|---:|
| BTC | 13,35% | 16,94% | **+3,59pp** (pior) |
| ETH | 12,27% | 15,87% | **+3,60pp** (pior) |
| SOL | 11,80% | 12,00% | +0,20pp (marginal) |
| BNB | 14,44% | 14,52% | +0,08pp (marginal) |
| XRP | 16,37% | 16,04% | -0,33pp (marginal, melhor) |

**Leitura**: `T=3` não é múltiplo do ciclo semanal — reintroduz aliasing na
FONTE de calibração pros 2 símbolos com sazonalidade de fim de semana mais
forte (BTC/ETH, sábado ~0,59x da média — addendum diário de `AG-124`), mesmo
com `cadence=1`. Pros 3 símbolos com sazonalidade mais fraca (SOL/BNB/XRP,
sábado ~0,70-0,73x), o efeito é ruído, não sinal. **Confirma, não enfraquece,
a leitura de que a restrição de balanceamento de dia-da-semana recai sobre
`trailing_window`, independente de `cadence`** (parecer externo, doc 2, §4 Q2)
— reduzir `trailing_window` abaixo de 7 tem custo real pra BTC/ETH; reduzir
`cadence` abaixo de 7 (mantendo `trailing_window=7`) não tem custo e tem
ganho grande (item 9). `T=7,C=1` permanece o candidato a travar.

### 8.1 Correção do Manager — `T=3` em bloco corrido não fazia sentido matemático

O Manager identificou o próprio erro: um bloco de 3 dias CORRIDOS não testa
"dá pra usar menos histórico", testa só "dá pra usar histórico
desbalanceado" — os dois nunca foram a mesma pergunta. Reformulado como
**calibração casada por dia-da-semana**: em vez de um bloco contíguo, usa as
`n_weeks` ocorrências mais recentes do MESMO dia-da-semana do dia aplicado
(`d-7`, `d-14`, ..., `d-7·n_weeks`) — estruturalmente livre de aliasing por
construção (todo ponto de calibração compartilha o dia-da-semana do dia
aplicado), não por coincidência de tamanho de bloco. `n_weeks=3` (o "T=3"
que o Manager pediu, agora fazendo sentido) usa só 3 pontos de dado reais.

Implementado (`--weekday-matched-weeks` no script), revalidado (modo bloco
segue bit-exato, 17,86%/41,67%), testado `n_weeks∈{1,2,3,4}` sobre
`dollar_threshold_drift_daily.json`:

| símbolo | wm1 | wm2 | wm3 | wm4 | T=7,C=1 (bloco) |
|---|---:|---:|---:|---:|---:|
| BTC | 14,43% | 11,80% | 11,13% | 10,95% | 13,35% |
| ETH | 14,91% | 12,43% | 11,78% | 12,06% | 12,27% |
| SOL | 19,48% | 17,80% | 17,40% | 17,05% | **11,80%** |
| BNB | 22,77% | 22,39% | 23,02% | 22,28% | **14,44%** |
| XRP | 24,30% | 22,27% | 22,84% | 24,54% | **16,37%** |

**Achado real, não previsto**: casamento por dia-da-semana BATE `T=7,C=1`
em bloco pra BTC/ETH (wm3/wm4 ~11%, contra 13,35%/12,27% do bloco) — pra
esses 2 símbolos a pureza sazonal (mesmo dia, mais velho) vale mais que
recência. Mas PERDE feio pra SOL/BNB/XRP (17-24% contra 11,80/14,44/16,37 do
bloco) — pra esses 3, a sazonalidade semanal é mais fraca (addendum diário:
sábado ~0,70-0,73x vs. ~0,59x em BTC/ETH) e o que a calibração casada
sacrifica (informação de tendência/volume dos últimos dias, presente no
bloco de 7 dias corridos) pesa mais que o que ela ganha em pureza sazonal.

**Conclusão**: nenhum candidato único (bloco `T=7,C=1` OU casado por
dia-da-semana) domina nos 5 símbolos ao mesmo tempo. Dado que o projeto já
decidiu operar com hiperparâmetro GLOBAL rígido (não por-ativo, evita data
snooping — decisão preexistente, não revisada aqui), `T=7,C=1` em bloco
continua sendo a melhor escolha ÚNICA: nunca é o pior em nenhum símbolo (pior
caso XRP 16,37%), enquanto casado por dia-da-semana tem pior caso BNB/XRP em
~23-25%. **`T=7,C=1` (bloco corrido) permanece o candidato a travar** —
o teste corrigido não muda a recomendação, mas testou a hipótese certa desta
vez e a resposta é honesta: não é unânime, é a opção mais robusta no pior
caso.

**`T=7,C=1` APROVADO pelo Manager, 2026-08-21.** Ordem de execução (§7,
v2) autorizada ponta a ponta.

---

## 9. Fase 2 — CONCLUÍDA (2026-08-21): itens 14, 15, 16

### Item 14 — carry através da fronteira de período

`src/data/bars.py`: nova `threshold_bars_drain(carry)` — devolve as barras
fechadas desde o último drain/finish SEM tocar `leftover`/`base_value`/
`threshold` (ao contrário de `threshold_bars_finish`, que fecha o stream).
`src/data/build_dollar_bars.py`: novo `_build_dollar_bars_for_period_carried`
(privado, duplica ~15 linhas do loop de chunks de `build_dollar_bars_for_
window` deliberadamente — mesmo precedente de duplicação pequena já usado
no repo, evita mudar o contrato público de uma função usada por `main()`/
CLI). `build_dollar_bars_walkforward` reestruturado: 1 único `carry` criado
no 1º período real, reusado em todos os seguintes (só `threshold`/
`max_leftover_trades` mudam por período); `threshold_bars_drain` a cada
período; `threshold_bars_finish` só no ÚLTIMO período (flush final
concatenado ao `bars_df` desse período). Resultado: **1 barra
subdimensionada por RODADA inteira, não 1 por período** — sob `C=1`, a
diferença entre ~365 fronteiras truncadas/ano (desenho antigo) e ~1 barra
parcial no fim de todo o range.

Achado colateral, documentado nos testes (não escondido): trocar
`carry.threshold` entre períodos pode fazer um trade que estava "em
progresso" rumo ao threshold ANTIGO fechar como sua própria barra menor
assim que o threshold cai — `cum_value` é acumulação bruta desde a origem
do carry, nunca resetada, então `bar_id = cum_value // threshold`
reinterpreta TODO o histórico acumulado sob o threshold novo. Nenhum
trade é perdido/duplicado (conservação verificada em teste), só a
fronteira exata de onde uma barra fecha pode mudar.

Testes novos: `tests/unit/test_data_bars.py::test_threshold_bars_drain_
preserva_leftover_e_produz_mesmo_resultado_que_lote` (equivalência
drain+finish vs. lote único, mesma disciplina já usada pra chunking),
`test_threshold_bars_drain_sobrevive_a_troca_de_threshold_entre_períodos`
(troca de threshold documentada acima). `tests/unit/test_data_build_
dollar_bars.py::test_build_dollar_bars_walkforward_finish_chamado_1x_
por_rodada_nao_por_periodo` (prova via contagem de chamadas que `finish`
só roda 1x, não 1x/período).

### Item 15 — lead-in buffer pro cold-start

Mesmo arquivo/mudança do item 14. `build_dollar_bars_walkforward`: TODO
período tenta calibrar agora (não só i>=1) — a janela de calibração pode
cair antes de `start` (só a LEITURA de trades, nunca a ESCRITA de barras,
que continua começando em `start`). Um período só é descartado (cold-
start) quando `calibrate_dollar_threshold_for_validation` levanta
`ValueError` (sem trade algum no lake pra aquela janela — início real de
histórico do símbolo, ou gap real de dado). Recupera ~1 semana real por
símbolo que antes era descartada incondicionalmente sem necessidade.

Teste novo: `test_build_dollar_bars_walkforward_lead_in_recupera_1o_
periodo_quando_ha_historico_antes` (histórico sintético antes de `start`
→ P0 deixa de ser cold-start, `threshold_usdt` correto, barras escritas
só a partir de `start`). Teste existente de cold-start (`..._cold_start_
1o_periodo_nao_quebra`) atualizado com `history_start=_WF_START_DATE`
pra continuar cobrindo o caso onde genuinamente não há dado antes —
os dois caminhos (recupera / não recupera) agora têm teste dedicado.

### Item 16 — circuit breaker vs. pico ~14x

**Achado principal, não previsto**: "~14x" (razão de volume em DÓLAR/dia,
medição diária de `AG-124`) e "50x" (`bars_threshold_leftover_safety_
multiplier`, multiplicador de CONTAGEM DE TRADES no leftover) são
dimensões DIFERENTES, não diretamente comparáveis. Um pico de volume em
dólar sustentado por MAIS trades de tamanho semelhante ao calibrado fecha
barras mais rápido (mais barras/dia) — não faz o leftover crescer, porque
`leftover` é a contagem de trades no bar AINDA ABERTO a qualquer instante,
não do dia inteiro. O que ameaça `max_leftover_trades` de verdade é uma
MUDANÇA DE FORMA da distribuição de trades (muitos trades pequenos
substituindo poucos grandes, deslocando trades-por-barra além do
multiplicador de segurança) — categoria de risco ortogonal ao "~14x"
medido.

Validado com 2 testes sintéticos novos em `test_data_bars.py`, usando o
multiplicador REAL de `constants.yaml`:
`test_threshold_bars_step_circuit_breaker_cobre_pico_de_volume_14x_
legitimo` (14x mais trades, mesmo tamanho médio → ~14 barras fecham,
leftover residual fica em ~1/50 do teto, folga grande) e
`test_threshold_bars_step_circuit_breaker_dispara_sob_mudanca_real_de_
forma_nao_so_volume` (trades 60x menores, mesmo valor total → excede o
teto de 50x antes de fechar 1 barra, `LeftoverOverflowError` dispara
corretamente). **Conclusão: circuit breaker cobre o pico de volume
medido com folga; nenhuma mudança de código necessária — o item era
validação, não redesenho.**

### Verificação mecânica (Fase 2 completa)

`banned_patterns --strict`, `ruff check`, `mypy --strict` limpos nos 5
arquivos tocados (`src/data/bars.py`, `src/data/build_dollar_bars.py`,
`tests/unit/test_data_bars.py`, `tests/unit/test_data_build_dollar_
bars.py`, mais `tests/unit/test_models_pipeline_paths.py` — achado
colateral corrigido, ver nota abaixo). Suíte completa (`uv run pytest -m
"not slow and not integration"`): **1619 passed** (1613 antes desta
sessão + 6 testes novos), 1 skip/2 xfail pré-existentes e documentados
(não relacionados).

**Achado colateral corrigido, fora do escopo de AG-124 mas encontrado no
caminho**: `tests/unit/test_models_pipeline_paths.py` tinha 4 testes
quebrados desde a implementação do AG-032 item 8 (fail-fast contra
`lookback_bars="expanding"`, sessão anterior) — o mesmo bypass
(`monkeypatch.setattr(features_build, "compute_max_feature_lookback_ms",
lambda tf: 0)`) já aplicado a 5 testes de `test_validation_leakage.py`
na sessão anterior nunca tinha sido aplicado a este arquivo. Corrigido
(2 pontos de aplicação), suíte volta a ficar 100% verde.

---

## 10. Fase 3 — item 11: autocorrelação/curtose sobre barras REAIS — ⚠️ achado que complica a decisão

Script novo: `tools/diagnostics/measure_dollar_bar_return_quality.py`.
Roda `build_dollar_bars_walkforward` de verdade (`dest_root` = diretório
temporário descartável, nunca `data/capacity/`) sobre uma amostra real
de 30 dias (2026-07-01 a 2026-07-30), 5 símbolos, 2 candidatos (`T7,C7`
vs. `T7,C1`), calculando autocorrelação lag-1 e curtose em excesso
(Fisher) dos retornos log de fechamento-a-fechamento das barras
resultantes. `experiments/dollar_bar_return_quality_sample.json`.

| símbolo | n_bars T7C7 | autocorr T7C7 | curtose T7C7 | n_bars T7C1 | autocorr T7C1 | curtose T7C1 |
|---|---:|---:|---:|---:|---:|---:|
| BTC | 2306 | 0,0029 | 5,02 | 1257 | 0,0033 | **68,49** |
| ETH | 2456 | 0,0065 | **91,38** | 1499 | -0,0154 | 78,38 |
| SOL | 2318 | 0,0142 | 16,33 | 1412 | 0,0013 | **31,46** |
| BNB | 2302 | 0,0073 | 15,65 | 1805 | 0,0164 | **33,94** |
| XRP | 2505 | -0,0348 | 34,42 | 1430 | -0,0017 | **56,30** |

**Autocorrelação — sem vencedor claro.** Ambos os candidatos ficam bem
próximos de zero (|autocorr| < 0,035 em todos os casos) — os dois
produzem retornos de barra quase serialmente descorrelacionados, sem
diferença prática relevante entre eles nesta amostra.

**Curtose — achado real que complica a decisão, não confirma o que se
esperava.** `T7,C1` tem curtose MAIOR que `T7,C7` em 4 dos 5 símbolos —
às vezes dramaticamente (BTC: 5,02→68,49, **13,6x**). Só ETH inverte
(91,38→78,38, T7,C1 um pouco melhor). Isso é o OPOSTO do que a métrica
de erro de calibração (item 9) sozinha sugeria: `T7,C1` "vence" em
rastrear `dollar_per_day` mais de perto, mas produz retornos de barra
com caudas MUITO mais pesadas — a propriedade que barras por atividade
deveriam justamente reduzir (mais perto de IID que barras de tempo),
não piorar.

**Mecanismo plausível (não confirmado com certeza pela amostra de 30
dias)**: `T7,C1` recalibra diariamente, então reage RÁPIDO a picos de
volume/volatilidade intra-semana (achado 1, deriva secular) —
concentrando um movimento de preço grande em MENOS barras maiores (o
threshold "acompanha" o pico), em vez de espalhar o mesmo movimento por
MAIS barras menores (o que `T7,C7`, com threshold parado a semana
inteira, faz por atraso, não por desenho). Concentrar movimento grande
em poucas barras é exatamente a assinatura de curtose alta. Consistente
com `T7,C1` ter MENOS barras que `T7,C7` no mesmo período (1257-1805 vs.
2302-2505) — o threshold mais responsivo produz barras maiores, em
média, durante a janela de alta.

**Limitação explícita**: `T7,C7` só tem 5 eventos de recalibração
distintos nesta amostra de 30 dias (`n_periods=5`) contra 30 de `T7,C1`
— um mês é pouco pra tirar conclusão definitiva sobre um candidato com
tão poucos pontos de recalibração; o sinal (T7,C1 pior em 4/5 símbolos,
mesma direção, magnitude não-trivial) é forte o bastante pra registrar
e levar ao Manager, mas não forte o bastante pra ser tratado como
definitivo sem uma amostra maior.

**Isto não estava previsto no plano original** — item 11 foi desenhado
pra "completar o trio de âncoras" do parecer externo, não pra encontrar
um trade-off novo. Mas encontrou um: **`T7,C1` vence decisivamente no
erro de calibração (item 9, -2,85 a -6,19pp em todos os 5 símbolos) E
perde (na maioria) em curtose (item 11, pior em 4/5, até 13,6x pior).**
Nenhuma das duas métricas domina a outra — são propriedades diferentes
do mesmo par de barras, e otimizar uma pode piorar a outra.

**Isto muda o que "travar T7,C1" significa.** Antes deste achado, a
recomendação parecia sem ambiguidade. Agora é uma escolha real de
trade-off que o Manager precisa fazer conscientemente: preferir rastreio
de volume mais fiel (menos vazamento residual de calibração) ao custo
de caudas mais pesadas nos retornos de barra (pior para qualquer
consumidor downstream sensível a outliers — ex. estimadores de
volatilidade, position sizing, modelos que assumem cauda mais fina).
**Não decidido aqui — reportado ao Manager como achado que pode reabrir
a decisão já aprovada (item 20 do plano: pré-registro de reabertura).**

---

## 11. Consulta ao auditor externo sobre o achado de curtose — validação + v2

O Manager consultou o auditor (autor do parecer/adendo, docs 1/2) sobre o
achado de curtose do §10. Resposta resumida: elogiou o comportamento
(dest_root temporário, não travar, escalar o conflito), mas contestou a
tabela em si — "nenhuma das três opções [travar T7,C1 / voltar a T7,C7 /
amostra maior], o problema não é tamanho de amostra". 4 pontos, cada um
verificado abaixo antes de aceitar (nenhum aceito às cegas).

### 11.1 Curtose é dominada por poucas barras extremas — ACEITO, verificado matematicamente

Reproduzi a conta do auditor: mistura de escala com MINORIA de barras de
variância menor (`c=0,5`, `p=0,05`) desloca a curtose de 3 pra ≈3,09 —
não pra 68. Conferido independentemente (fórmula de curtose de mistura
gaussiana de 2 componentes: `3·E[σᵢ⁴]/E[σᵢ²]²`). Nenhum mecanismo de
mistura suave chega a 68 sem uma minoria GRANDE ou uma diferença de
escala EXTREMA — K=68 é assinatura de outlier pontual, não de
propriedade distribucional. **Confirma o ponto do auditor.**

### 11.2 Confundidor "5 resets vs. 30" — NÃO confirmado como descrito, mas mecanismo relacionado real existe

Verificado no código (`src/data/build_dollar_bars.py:705,765,783`): o
item 14 (Fase 2, já implementado ANTES desta medição rodar) já elimina
"reset de carry por período" — 1 único `carry` vive a rodada inteira,
só 1 `threshold_bars_finish` no fim, pros DOIS candidatos. **A framing
"5 resets contra 30" não descreve o que foi medido** — o auditor parece
ter avaliado com base num modelo mental de ANTES do item 14 (ou não
tinha esse contexto na consulta).

Mas existe mecanismo relacionado, real e IRREDUTÍVEL: `carry.threshold`
muda a cada período (5x pra T7,C7; 30x pra T7,C1) ENQUANTO o carry ainda
tem leftover do período anterior — o teste `test_threshold_bars_drain_
sobrevive_a_troca_de_threshold_entre_periodos` já documenta que isso
pode fechar uma barra "em progresso" cedo sob o threshold NOVO. Isso não
é bug pra corrigir (já não reseta) — é o que "cadência menor" significa
por definição. Marcado e testado por exclusão (ver 11.4).

### 11.3 Curtose é ferramenta ruim pra n~1500-2500 — ACEITO sem necessidade de verificação adicional (fato estatístico estabelecido)

Substituído/complementado por 3 medidas robustas (script v2): razão
p99/p50 de |retorno|, fração além de 5×mediana, índice de cauda de Hill
(top 5%, α menor = cauda mais pesada).

### 11.4 3ª âncora nunca tinha rodado sobre barras reais — corrigido

`weekday_dispersion` (CV de contagem de barras por dia-da-semana), agora
medido direto sobre as barras construídas, não o proxy `dollar_per_day`.

### Resultado da v2 — script reescrito, rodado de novo sobre a MESMA amostra

`experiments/dollar_bar_return_quality_sample_v2.json`.

| símbolo | kurt T7C7 (excl. bound.) | kurt T7C1 (todas) | kurt T7C1 (excl. bound., 29 excl.) | Hill α T7C7 | Hill α T7C1 | CV weekday T7C7 | CV weekday T7C1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 5,00 | 68,49 | **85,15** (piora) | 5,17 | 2,55 | 0,512 | 0,631 |
| ETH | 91,23 | 78,38 | **104,26** (piora) | 4,66 | 2,64 | 0,470 | 0,761 |
| SOL | 16,33 | 31,46 | **21,10** (melhora) | 4,71 | 3,01 | 0,435 | 0,488 |
| BNB | 15,61 | 33,94 | **22,70** (melhora) | 4,41 | 3,41 | 0,503 | 0,652 |
| XRP | 34,37 | 56,30 | **7,00** (melhora muito) | 4,68 | 3,39 | 0,359 | 0,769 |

**Achado 1 — o mecanismo de fronteira do auditor é heterogêneo entre
símbolos, não universal.** Excluir as 29 barras de fronteira (1ª barra de
cada período não-inicial) MELHORA muito a curtose de XRP (56,30→7,00,
quase resolve sozinho), melhora SOL/BNB moderadamente, mas PIORA BTC/ETH
(68,49→85,15 e 78,38→104,26) — a exclusão não é a explicação completa,
e pra BTC/ETH é a direção ERRADA. Os outliers de BTC/ETH não estão
concentrados nas barras de fronteira.

**Achado 2, novo, não estava no plano — mecanismo mais preciso e melhor
sustentado: concentração de volatilidade de horário de funding.**
Inspecionei as 5 maiores barras padronizadas de cada símbolo sob `T7,C1`
— TODAS, nos 5 símbolos, fecham entre 23:18 e 23:59:59 UTC (fechamento
de funding da Binance USDⓈ-M é às 00:00/08:00/16:00 UTC). Verificado
quantitativamente, BTCUSDT: barras fechando nos últimos 10 minutos do
dia UTC são **1,99% do total sob T7,C1** (25/1257) contra **0,74% sob
T7,C7** (17/2306) — uniforme esperado seria 0,69%. **T7,C1 concentra
~2,9x mais barras no fim do dia que o uniforme; T7,C7 não mostra excesso
nenhum** (0,74%≈0,69% esperado). Mecanismo: barras menores (cadência
maior) concentram o pico de volume/volatilidade de horário de funding em
MENOS barras, produzindo retornos individuais mais extremos; barras
maiores (T7,C7) diluem o mesmo pico dentro de uma barra que já precisa
de muito mais volume pra fechar, amortecendo o efeito. **Não é bug do
algoritmo de calibração — é uma propriedade real de granularidade de
barra interagindo com microestrutura real de mercado.**

**Achado 3 — os 2 sinais ROBUSTOS (não dominados por 1-2 outliers, ao
contrário da curtose) confirmam T7,C1 pior nos 5 símbolos, sem
exceção:**
- **Índice de cauda de Hill**: `T7,C1` tem α entre 2,55-3,41 (cauda
  pesada — α<4 já indica curtose populacional teoricamente infinita sob
  Pareto pura) contra `T7,C7` em 4,41-5,17 (mais perto de cauda normal)
  — nos 5 símbolos, sem exceção, mesma direção, calculado sobre os 5%
  maiores `|retorno|` (imune ao problema de 1-2 pontos dominarem).
- **CV de barras-por-dia-da-semana** (3ª âncora, agora sobre barras
  reais): `T7,C1` tem dispersão MAIOR que `T7,C7` nos 5 símbolos, sem
  exceção (0,36-0,51 → 0,49-0,77) — o oposto do que se esperava
  (recalibrar mais rápido deveria, na teoria, produzir grade mais
  homogênea; na prática produz menos).

**Síntese**: a hipótese específica do auditor (confundidor de reset de
carry) não se sustenta — já corrigida antes desta medição. Mas a
substituição da curtose por medidas robustas não faz o achado desaparecer
— acha um achado DIFERENTE e mais bem sustentado: `T7,C1` tem cauda mais
pesada (Hill) E menos homogeneidade de calendário (CV por dia-da-semana)
que `T7,C7`, nos 5 símbolos, sem exceção, por 2 vias independentes que
não dependem de 1-2 barras extremas. A causa provável (concentração de
volatilidade de funding em barras menores) é um mecanismo real de
mercado, não um artefato do pipeline.

**Isto pesa contra travar `T7,C1` mais do que o achado original da v1
pesava** — antes, só a curtose (frágil) apontava contra; agora, 2
medidas robustas apontam na mesma direção, e o mecanismo tem explicação
causal plausível e verificada (não é só correlação). Ainda não decidido
— ação seguinte (não executada nesta rodada): reportar ao Manager pra
decisão final entre travar `T7,C7`, travar `T7,C1` conscientemente do
trade-off, ou testar um candidato intermediário (`T7,C2`/`T7,C3`) que
talvez capture parte do ganho de rastreio de `T7,C1` sem concentrar tanto
a volatilidade de funding.

**⚠️ CORREÇÃO §12 abaixo — a leitura "2 medidas robustas confirmam
T7,C1 pior" NÃO sobrevive ao teste decisivo do auditor. Não tratar este
§11 como conclusão final — ver §12.**

---

## 12. Segunda rodada de crítica do auditor — teste decisivo executado, achado do §11 NÃO se sustenta

O Manager levou o §11 de volta ao auditor. Resposta: aceita a correção
do item 14 ("retiro o confundidor como formulado"), mas reformula —
"não é reset, é uma semântica de transição de threshold não
caracterizada, e ela roda 6x mais no braço C=1" — e propõe um teste
decisivo: **se a concentração em 23:5x for causada por funding
(00h/08h/16h UTC), o mesmo padrão deveria aparecer nos 3 horários, nos
2 braços.** Também contesta que Hill + CV sejam "confirmação
independente" — com ~30 barras potencialmente contaminadas contra ~5,
qualquer estimador (robusto ou não) pode estar lendo a mesma
contaminação, não 2 evidências distintas.

### Teste decisivo (item 1 da fila do auditor) — executado

Concentração de fechamento de barra nas janelas de 10min antes de cada
horário de funding, BTCUSDT, ambos os braços:

| janela | T7,C7 (razão vs. uniforme) | T7,C1 (razão vs. uniforme) |
|---|---:|---:|
| 23:50-23:59 (pré-00h) | 1,06x | **2,86x** |
| 07:50-07:59 (pré-08h) | 0,87x | 0,80x |
| 15:50-15:59 (pré-16h) | 1,75x | 1,26x |

**Resultado: NÃO há excesso comparável nos outros 2 horários de
funding, nos 2 braços.** Pré-08h fica ABAIXO do uniforme nos dois
braços; pré-16h mostra excesso leve em AMBOS mas maior em `T7,C7`,
direção oposta ao pré-00h. Só pré-00h mostra o padrão assimétrico
(excesso forte só em `C=1`) — **refuta microestrutura de funding
genérica como explicação única**, exatamente o critério que o próprio
auditor definiu como decisivo. **Por essa mesma resposta, o auditor já
havia dito que mudaria de posição — na direção contrária ao que a
hipótese de funding precisava mostrar: aqui ela NÃO aparece nos 3
horários, então a leitura correta é a do auditor (fronteira de
calibração), não a minha (funding).**

### Redefinição de fronteira + reexecução sobre Hill (item 2 da fila) — achado decisivo

A flag `is_boundary` original (1ª barra de cada período) captura só 29
barras/braço em `C=1`, e checar seus horários reais mostrou algo
importante: elas abrem ~23:19-23:47 do dia anterior e fecham
~23:36-00:20 — ou seja, ocupam o MESMO intervalo onde as barras mais
extremas caem, mas não são necessariamente as MESMAS barras (só 1 das 5
maiores de cada símbolo bateu com a flag original). Confirma a suspeita
do auditor: a flag original era estreita demais.

Redefinido de forma mais ampla e agnóstica ao mecanismo exato: excluir
TODA barra cujo fechamento cai numa janela de ~1h em torno da meia-noite
UTC (23:30-00:30), e recalcular curtose E Hill (não só curtose) dentro e
fora dessa janela, para os 5 símbolos, os 2 braços:

| símbolo | cand | n_excl (~1h) | kurt completo | kurt excl. janela | Hill completo | Hill excl. janela |
|---|---|---:|---:|---:|---:|---:|
| BTC | C7 | 78 | 5,02 | **0,18** | 5,17 | 5,83 |
| BTC | C1 | 71 | 68,49 | **2,50** | 2,55 | 4,85 |
| ETH | C7 | 97 | 91,38 | **-0,06** | 4,66 | 5,59 |
| ETH | C1 | 80 | 78,38 | **21,64** | 2,64 | 4,12 |
| SOL | C7 | 91 | 16,33 | **0,24** | 4,71 | 5,27 |
| SOL | C1 | 87 | 31,46 | **0,17** | 3,01 | 4,73 |
| BNB | C7 | 95 | 15,65 | **0,39** | 4,41 | 5,33 |
| BNB | C1 | 95 | 33,94 | **0,54** | 3,41 | 5,39 |
| XRP | C7 | 103 | 34,42 | **0,23** | 4,68 | 5,39 |
| XRP | C1 | 86 | 56,30 | **0,24** | 3,39 | 6,09 |

**Achado decisivo, contra a minha própria leitura do §11**: excluir
essa única janela de ~1h/dia (menos de 4% das barras) faz a curtose
COLAPSAR pra perto de zero nos 2 braços, nos 5 símbolos, sem exceção —
e o índice de Hill CONVERGE entre os braços (ambos ficam em 4,1-6,1,
contra o 2,5-3,4 vs. 4,4-5,2 que parecia uma diferença estrutural robusta
no §11). **O auditor estava certo em duvidar: Hill e curtose NÃO eram
confirmações independentes — as duas estavam lendo a mesma janela
contaminada.** O achado "`T7,C1` tem cauda estruturalmente mais pesada"
do §11 NÃO SE SUSTENTA — era, ele mesmo, um artefato de uma janela
estreita, não uma propriedade geral de cadência curta.

**O que sobra, genuinamente sem explicação plena**: por que retornos de
barra especificamente na janela 23:30-00:30 UTC são desproporcionalmente
extremos, MAIS sob `C=1` (concentração 2,86x) que sob `C=7` (~1x,
uniforme) — mas presente em algum grau nos DOIS braços (a curtose de
`T7,C7` também cai quase a zero excluindo a mesma janela, mesmo sem
excesso de CONTAGEM de barras ali). Não é funding genérico (refutado
acima). Pode ser: (a) efeito residual do mecanismo de transição de
threshold, mais amplo que só "a 1ª barra" (item 2 da semântica agora
documentada em `build_dollar_bars_walkforward`); (b) uma característica
real e recorrente do mercado especificamente em torno da virada de dia
UTC, não ligada a funding; (c) uma questão de qualidade de dado na
fronteira de dia (conexão possível com `AG-120`, desalinhamento de
timestamp já registrado e nunca totalmente investigado — item 13/B0
do plano, ainda não executado). **Causa raiz não isolada — registrada
como aberta, não como achado fechado.**

### Decisão

Adoto a recomendação do auditor, sem alteração:
- **`T=7,C=1` NÃO é travado.** `T=7,C=7` fica como candidato provisório
  — não porque a evidência contra `C=1` esteja estabelecida (não está),
  mas porque `C=1` exercita 6x mais um caminho de código cuja semântica
  só ficou formalizada nesta sessão (`build_dollar_bars_walkforward`,
  ver acima) e cuja vantagem (item 9) vive inteira numa métrica cujo
  corte nunca passou pelo sweep do M1.
- **`T7,C2`/`T7,C3` REJEITADOS** — interpolar entre 2 braços cuja
  diferença ainda não está explicada não informa nada, custa 2 rodadas.
- **Retratação formal**: o achado "`T7,C1` produz caudas
  estruturalmente mais pesadas" (§10/§11) **NÃO fica registrado como
  achado confirmado em `AG-124`** — vira observação PENDENTE DE
  DESCONFUNDIR, com os testes já rodados anexados (não repetir do zero
  se o item 13/B0 mais tarde apontar pra `AG-120`).
- **Semântica de troca de threshold com barra aberta**: documentada
  agora em `src/data/build_dollar_bars.py::build_dollar_bars_walkforward`
  (determinística, testada, não mais "não trivial"/indefinida) —
  independente da decisão de `cadence_days`.

**Fila restante da auditoria (itens 3/4)**: item 3 (distribuição de
tamanho/duração de barra entre braços, testar direção do mecanismo)
DEPRIORIZADO — o achado da janela de ~1h já explica quase toda a
diferença, a pergunta de mecanismo fica secundária até a causa raiz
(item 13/B0, conexão com `AG-120`) ser investigada. Item 4 (documentar
semântica) — feito nesta rodada.

---

## 13. Fase 4 — item 13/B0: varredura de integridade dedicada, causa raiz do AG-120 — CONCLUÍDA

Script novo: `tools/diagnostics/measure_ag120_bars_baseline_alignment.py`
— reproduz a checagem de `_assert_bars_baseline_aligned`
(`src/analysis/m4_regime_comparison.py`) em TODAS as células da
varredura original do M4 (`CRITICAL_WINDOWS` × símbolos × R1/R2/R3, 51
células reais — as janelas BTC-only, LUNA/FTX, têm menos células que as
5-símbolos), sem ajustar nenhum candidato de regime — só a checagem de
grade. Dado real, leitura pura, `experiments/ag120_bars_baseline_
alignment_sweep.json`.

**Resultado: 50/51 células alinhadas. A ÚNICA divergência é a mesma
célula já conhecida (`BNBUSDT`/`RECENTE`/`R2`)** — nenhuma célula nova
encontrada. Confirma que o gap é genuinamente isolado, não sistêmico —
seguro prosseguir com reprocessamento depois que `T`/`C` for travado.

**Diagnóstico preciso da célula conhecida**: `n_bars=26584 == n_baseline`
(NÃO é problema de contagem/linhas faltando) — só **2 de 26584 posições**
divergem, ambas em `2026-05-04`, entre `04:06:13` e `04:08:55` UTC,
delta de **~162 segundos**. **Não é a mesma janela do achado de curtose
do §12** (aquele é 23:30-00:30 UTC, todo dia; este é um evento pontual
único, `04:0x` UTC, um único dia) — **as duas anomalias NÃO estão
conectadas**, hipótese de causa raiz comum descartada por medição.

**Causa raiz exata (nível de trade bruto) não investigada mais fundo** —
dado o tamanho (2 barras em 16 meses × 1 símbolo × 1 resolução) e a
ausência de qualquer padrão sistêmico nas outras 50 células, não
justifica investigação mais profunda antes do reprocessamento — vira
item de baixa prioridade, não bloqueante. `AG-120` atualizado com o
escopo real (isolado, confirmado) e a localização exata.

---

## 14. Terceira rodada de crítica do auditor — leitura mais fina do residual, M1 redux, item 4 travado

O Manager levou o §13 de volta ao auditor. 4 pontos, todos endereçados:

### 14.1 O residual é mais estreito que "não explicado" — 2 mecanismos sobrepostos

Releitura dos números do teste 1 (§12): pré-08h fica ABAIXO de 1x nos 2
braços; pré-16h tem excesso MAIOR em `C7` (direção oposta ao pré-00h);
só pré-00h separa os braços, por 2,7x. Um efeito de mercado puro na
virada do dia apareceria nos 2 braços com magnitude parecida — o que se
vê é fraco em `C7`, forte em `C1`. Leitura do auditor, aceita: **não é
uma explicação, são duas sobrepostas** — um efeito modesto e real de
virada de dia (presente nos 2 braços) MAIS uma amplificação por
transição de threshold (concentrada no braço com 30 transições).

### 14.2 Teste decisivo restante — tamanho/duração de barra na janela, por braço

Medido (BTCUSDT, amostra de 30 dias): mediana de `quote_volume`
(tamanho real da barra) e duração (`close_time - open_time`), dentro da
janela 23:30-00:30 UTC vs. resto do dia:

| braço | quote_volume mediano (janela) | quote_volume mediano (resto) | duração mediana (janela) | duração mediana (resto) |
|---|---:|---:|---:|---:|
| C7 | 89,68M | 89,77M (≈igual) | 1034,8s | 694,8s (**+49%**) |
| C1 | 79,55M | 82,64M (-3,7%) | 802,1s | 660,7s (**+21%**) |

**Resultado misto, não uma resposta limpa.** Tamanho da barra fica
praticamente igual dentro/fora da janela nos 2 braços (sem "explosão de
tamanho" que confirmaria transição pura) — mas duração é MAIOR na
janela nos 2 braços, e a elongação é PROPORCIONALMENTE MAIOR em `C7`
(+49%) que em `C1` (+21%), o oposto do que "amplificação por transição
em C1" prediria sozinho.

Inspecionando as 5 barras mais extremas de `C1` individualmente (não só
a mediana agregada): **assinaturas MISTAS entre elas** -- 1 barra
(2026-07-03 23:36, z=7,03) tem `quote_volume` a 0,20x da mediana
(muito menor -- assinatura clássica de artefato de transição, leftover
antigo fechando cedo sob threshold novo); 2 barras (2026-07-14 23:59
z=16,41, e 2026-07-10 23:55 z=5,49) têm tamanho normal (~1,0x) mas
duração 2,5-3,2x mais longa (assinatura de mercado real -- período mais
quieto, mesmo tamanho de barra, mas um movimento de preço genuíno
aconteceu durante o intervalo mais longo). **Confirma a leitura do
14.1, não uma resposta única**: pelo menos 1 das 5 barras mais extremas
tem assinatura de transição, pelo menos 2 têm assinatura de mercado —
os 2 mecanismos coexistem na mesma amostra, não são hipóteses
concorrentes excludentes.

### 14.3 AG-120 x janela de meia-noite — já respondido, confirma independência

A checagem pedida já estava disponível do §13: o único desalinhamento
real (`BNBUSDT`/`RECENTE`/`R2`) ocorre em **2026-05-04, 04:06-04:08
UTC** — fora da janela 23:30-00:30 por ~4 horas, e é evento ÚNICO (1 dia
em 16 meses), não um padrão recorrente comparável ao achado de curtose
(que aparece nos 5 símbolos, todo dia). **Confirmado: são fenômenos
independentes** -- B0 não precisa de redesenho, o escopo (50/51 células
limpas) já é a resposta correta.

### 14.4 M1 redux — sweep do corte 2x/0,5x especificamente para T7,C7 vs. T7,C1

O sweep original do item 6 testou o corte sobre a grade acoplada
(`T=C`, W=1..7) -- nunca especificamente sobre a comparação
DESACOPLADA que decide a aprovação (`T7,C7` vs. `T7,C1`, item 9).
Refeito: `--trailing 7 --cadence {7,1}` × cortes `2,0/0,5` (original),
`1,7/0,6` (mais rígido), `2,5/0,4` (mais frouxo), 5 símbolos:

| símbolo | 2,0/0,5 | 1,7/0,6 | 2,5/0,4 |
|---|---:|---:|---:|
| BTC | -2,85pp | -2,46pp | -1,68pp |
| ETH | -4,25pp | -3,10pp | -2,36pp |
| SOL | -6,19pp | -7,39pp | -3,77pp |
| BNB | -5,84pp | -6,16pp | -4,13pp |
| XRP | -5,44pp | -6,22pp | -4,65pp |

(Δ = `T7,C1` − `T7,C7`, negativo = `C1` melhor.) **`C1` vence nos 5
símbolos, nos 3 cortes, sem exceção nem inversão de sinal em nenhuma
célula.** A vantagem de `C1` no erro de calibração NÃO é artefato do
corte 2x/0,5x -- M1 passa. Isso não muda a decisão de travar `C7`
provisório (o motivo é a semântica de transição não caracterizada até
esta sessão, não dúvida sobre o M1), mas fecha o item que o auditor
apontou como verificação pendente.

### Item "documentar semântica" -- já travado, confirmado

O teste `test_threshold_bars_drain_sobrevive_a_troca_de_threshold_entre_periodos`
já assert valores EXATOS derivados à mão (`result.height==2`,
`volume==[5.0,2.0]`, `count==[1,1]`, `threshold_quote==60.0`,
`sum==7.0`) -- já é teste de caracterização que falha alto se a
semântica mudar, não checagem frouxa de "não quebra". Nenhuma ação
adicional necessária.

### Estado da fila após esta rodada

Dos 5 itens que o auditor listou, 4 resolvidos nesta rodada (14.2 dado
misto mas informativo, 14.3 confirmado, 14.4 M1 passou, semântica já
travada). B0 já tinha rodado (§13). **S1 (sweep tp/sl) continua em
aberto, maior lacuna do projeto, não depende de nada disso** -- próximo
item de fato pendente.

**Fase 5 autorizada e em execução** (background, iniciada 2026-08-21
~23h -- ver §15) enquanto esta rodada de crítica acontecia -- não
bloqueada por nenhum dos 4 pontos acima (nenhum reabriu a decisão de
travar `C7` provisório; M1 reforça, não contesta).

---

## 6. Execução real — itens 1, 6, 7, 8, 9 concluídos (2026-08-21)

**Item 1 (Fix Mecânico)** — prosa corrigida em `docs/brief_...ag124.md` §3 e
na docstring de `_calibration_errors_for_window`
(`tools/diagnostics/analyze_dollar_threshold_calibration_error.py`).

**Item 8 (Fix Mecânico)** — script generalizado pra aceitar `--trailing`/
`--cadence` separados (default `cadence=trailing`, preserva 100% o
comportamento anterior — revalidado contra os 2 números publicados de
`AG-124`, XRPUSDT W=1=17,86%/W=6=41,67%, batem exatos após o refactor).
`--high-mult`/`--low-mult` também parametrizados (habilita item 6).

**Item 6/M1 (Teste de Validação)** — sweep do corte em `1,7/0,6` e `2,5/0,4`
contra o original `2,0/0,5`, `W∈{1,2,4,7}`: ranking BTC (7 vence 1) e ETH (1
vence 7) estáveis nos 3 cortes. O corte não muda a decisão qualitativa.

**Item 7/M2 (Teste de Validação)** — grid preenchido em `W=5,6,8,9,13,15`
sobre `dollar_threshold_drift_daily.json`. Achado: pra BTC/ETH, `W=5`
(15,68%/15,01%) e `W=6` (16,13%/15,73%) têm erro MENOR que `W=7`
(16,20%/16,52%) — não há mínimo local limpo em 7, é um vale largo 5-9. Não
invalida `W=7` (só ele garante balanceamento estrutural), mas remove o
argumento "7 é ótimo empírico local".

**Item 9 (Teste de Validação) — achado principal desta rodada.**
`T=7, C=1` medido contra `dollar_threshold_drift_daily.json`, comparado ao
baseline `T=7, C=7`:

| símbolo | T=7,C=7 | T=7,C=1 | Δ |
|---|---:|---:|---:|
| BTC | 16,20% | 13,35% | -2,85pp |
| ETH | 16,52% | 12,27% | -4,25pp |
| SOL | 17,99% | 11,80% | -6,19pp |
| BNB | 20,28% | 14,44% | -5,84pp |
| XRP | 21,81% | 16,37% | -5,44pp |

`T=7,C=1` vence nos 5 símbolos, sem exceção, por margem grande. Confirma com
dado real a previsão do parecer externo (doc 2 §4 Q2): calibração
balanceada (`T=7`) + cadência mínima (`C=1`) são aditivos, não conflitantes.

**Consequência direta sobre o item 14**: com `C=1` como novo candidato a
travar, a preservação do `ThresholdBarsCarry` através da fronteira de
período deixa de ser "faça na mesma mudança que o item 15" (opcional sob
`C=7`) e vira **pré-condição bloqueante** — sem ela, `C=1` gera ~365
fronteiras truncadas/ano por símbolo em vez de ~52, custo nunca medido.

Detalhe completo e full JSON em `experiments/dollar_threshold_calibration_
error_daily_{grid_fill,T7_C1,cut_tight,cut_loose}.json`; registrado como
addendum em `audit/architecture_gaps_log.yaml::AG-124`
(`addendum_desacoplamento_trailing_cadence_2026-08-21`).

**Recomendação atualizada, pendente confirmação do Manager**: travar
`trailing_window_days=7`, `cadence_days=1` (não mais `7/7`) — condicionado
ao item 14 (carry) ser implementado primeiro, per ordem de execução §5.

**Próximo passo**: item 17/S1 (sweep 2D de `tp_atr_mult`/`sl_atr_mult`)
precisa de uma etapa curta de desenho antes de rodar (grid de pontos,
definição operacional de "robustez na vizinhança" per §16.10) — maior
escopo de todos os itens, não executado às cegas nesta rodada. Itens 10
(M4, redesenho de metodologia), 11 (autocorrelação/curtose), 12 (M5), 13
(B0), 14+15 (carry+lead-in) e 16 (circuit breaker) seguem pendentes, na
ordem autorizada.

---

## 15. Fase 5 disparada + quarta rodada de crítica — contagem de transição, resultado na direção oposta à esperada

### Fase 5 — reprocessamento real em execução

Manager autorizou "Fase 5 (travar T7,C7 provisório + reprocessar)".
Setup: `dollar_bar_walkforward_trailing_window_days`/`dollar_bar_
walkforward_cadence_days` registrados em `config/constants.yaml`
(`provenance: MEASURED`, referenciando `AG-124`, valor `7`/`7`,
explicitamente marcado PROVISÓRIO no `source`). Script novo `tools/
diagnostics/run_ag124_production_reprocessing.py` (**não é
diagnóstico** — é a execução real de produção, só vive em `tools/
diagnostics/` por falta de outro diretório de scripts operacionais no
repo) — loop sequencial (não concorrente) sobre os 5 símbolos × 3
resoluções, `SYMBOL_START_DATE`/`END_DATE` reusados de
`volatility_comparison.py` (não duplicados), `overwrite=True` (substitui
a calibração não-causal antiga real), isolamento de falha por célula
(padrão AG-019). Dry-run confirmou as 15 combinações exatas antes de
rodar de verdade. Disparado em background — histórico completo, pode
levar horas.

### Quarta rodada de crítica do auditor — 2 pontos

**Ponto 1 — M1 passar remove um dos 2 pilares do "provisório".** Os 2
motivos originais pra travar `C7` provisório foram: (a) semântica de
transição não caracterizada, (b) vantagem de `C1` vivendo num corte
nunca varrido. (a) já tinha caído no §14 (semântica documentada +
testada). (b) caiu nesta rodada (M1 redux, §14.4: `C1` vence em todas
as 15 combinações símbolo×corte). O auditor propôs a medição que
faltava pra fechar de vez: contar, entre as 29-30 transições da
amostra, quantas produzem barra com `quote_volume < 0,5x` a mediana --
"se forem poucas, `C1` não tem custo estrutural".

**Ponto 2 — releitura de 14.2**: duração maior em ambos os braços mas
proporcionalmente maior em `C7` (+49% vs. +21%), com tamanho estável, é
assinatura de mercado real (período mais quieto, ambos os braços
sentem, `C7` sente mais porque um threshold desatualizado numa janela
de baixa atividade demora ainda mais a fechar) -- e a inspeção
individual (1/5 barras extremas com assinatura de transição, 2/5 com
assinatura de mercado) seria "mercado dominante, contaminação
minoritária de transição", não empate entre mecanismos.

### Medição rodada — resultado na direção OPOSTA à esperada pelo auditor

Contagem real de `quote_volume < 0,5x mediana` entre as 29 transições
de cada símbolo (amostra de 30 dias, `T7,C1`):

| símbolo | subdimensionadas | fração |
|---|---:|---:|
| BTC | 12/29 | 41,4% |
| ETH | 20/29 | 69,0% |
| SOL | 12/29 | 41,4% |
| BNB | 16/29 | 55,2% |
| XRP | 17/29 | 58,6% |

**41-69% de TODAS as transições produzem barra subdimensionada -- não
"poucas".** A barra de 0,20x achada em 14.2 (inspeção das 5 maiores por
retorno) não era um caso raro dentro de amostra dominada por mercado --
é uma amostra pequena de um fenômeno que, medido sobre as 29 transições
completas, é comum, quase majoritário em alguns símbolos (ETH 69%).

**Não decide sozinho que o mecanismo de transição CAUSA a curtose**
(barra subdimensionada não implica automaticamente retorno maior -- esse
elo específico não foi medido, só a FREQUÊNCIA do subdimensionamento).
Mas decide a pergunta que o próprio auditor fez, pela régua que ele
mesmo propôs: o resultado inclina na direção CONTRÁRIA à que ele
esperava -- reforça, não remove, a cautela sobre `C=1`.

**`T=7,C=7` continua candidato PROVISÓRIO — motivo atualizado pela 3ª
vez nesta investigação, cada vez mais preciso**: não mais "caminho não
caracterizado" (caiu), não mais "corte não varrido" (caiu), agora:
"custo de transição de `C=1` é frequente (41-69% das recalibrações
produzem barra subdimensionada), elo exato com o achado de curtose
ainda não isolado". Não é mais escolha entre 2 opções com diferença
pequena, como pareceu por um momento logo depois do M1 passar.

### Padrão registrado (pedido explícito do auditor, não específico desta decisão)

Quando 2 parâmetros são amarrados (aqui, `trailing_window_days ==
cadence_days`, até o desacoplamento desta sessão), toda verificação
feita sobre "o parâmetro" fica ambígua sobre qual dos dois foi de fato
verificado. 2ª ocorrência confirmada NESTA MESMA investigação: a
métrica de erro de calibração original nunca tinha sido varrida
especificamente pra `T7,C7` vs. `T7,C1` (M1 redux, §14.4), só pra grade
acoplada `T=C`; a 1ª foi o próprio achado de aliasing semanal recaindo
só sobre `trailing_window`, não sobre `cadence` (addendum de
desacoplamento). Heurística geral pra revisão futura de qualquer par de
parâmetros historicamente acoplado neste projeto — registrado em
`AG-124::addendum_quarta_rodada_contagem_transicao_2026-08-21`.

### Fila após esta rodada

1. **S1** (sweep `tp_atr_mult`/`sl_atr_mult`) — maior lacuna aberta do
   projeto, independente de tudo acima, parada há 4 sessões enquanto a
   cadência consumiu a atenção. Próximo item de fato.
2. **B0** — escopo já confirmado independente (§14.3), sem pendência.
3. Elo exato entre subdimensionamento de transição e curtose/retorno
   extremo — **RESOLVIDO na rodada seguinte (§16), não fica mais em
   aberto.**

---

## 16. Quinta rodada — controles do auditor confirmam taxa-base, mas o elo com retorno (medido agora) é real e assimétrico

Auditor apontou que 41-69% pode ser a taxa-base de qualquer fronteira de
recalibração (resíduo no instante de corte ~uniforme sob acumulação por
threshold), não uma severidade específica de `C=1` — propôs 2 controles.

**Controle A** (taxa por evento em `C=7`, n=4/símbolo): 50/50/50/75/25%,
média ~50% — **igual à taxa de `C=1`. Confirmado: não é defeito de
`C=1`, é propriedade de qualquer fronteira.**

**Controle B** (barras não-fronteira): 0,0-0,6% nos 2 braços — o corte
0,5x separa fronteira de normal de verdade.

**O outro lado do fork que o auditor definiu** ("ou se mede o elo com o
retorno ou se trava C=1") **foi medido**: retorno `|z|` médio de barra
de fronteira vs. normal — sob `C=1`, fronteira SEMPRE mais extrema (5/5
símbolos, 1,6-3,3x); sob `C=7`, fronteira SEMPRE MENOS extrema (5/5
símbolos, 0,02-0,42x, n=4 mais ruidoso mas direção consistente 5x
independentes). **A taxa de subdimensionamento é base (simétrica); a
consequência em retorno NÃO é (assimétrica, específica de `C=1`).**

`T=7,C=7` continua PROVISÓRIO — motivo final (4ª formulação): frequência
de evento (7,25x maior sob `C=1`) × consequência de retorno específica
do braço (elevada sob `C=1`, ausente/invertida sob `C=7`), ambas
medidas, não presumidas. Full detail e números completos:
`audit/architecture_gaps_log.yaml::AG-124::
addendum_correcao_taxa_base_e_elo_com_retorno_2026-08-21`.

**S1 abre com uma decisão de desenho, não com o grid**: independente vs.
razão. `tp_atr_mult`/`sl_atr_mult` como razão (2,0/1,5) controla o
breakeven implícito (42,86%); os níveis absolutos controlam taxa de
eventos e holding time — efeitos diferentes, grid acoplado não separa.
Aberta ao Manager antes de desenhar o grid — mesma disciplina que este
documento inteiro existe pra reforçar.

---

## 17. Sexta rodada — confundimento amostral corrigido, decisão de cadência concluída, S1 reparametrizado

### Correção crítica: a comparação de fronteira estava confundida com hora-do-dia

Auditor identificou 2 problemas amostrais no addendum anterior (§16):
(1) as 4 fronteiras de `C=7` são os MESMOS 4 instantes nos 5 símbolos —
cripto correlaciona no mesmo minuto, "5/5 concordam" é ~n=4, não 5
réplicas; (2) sob `C=1`, fronteira≈meia-noite (29/30); sob `C=7`,
fronteira é só 1/7 das meia-noites — comparar fronteira-vs-fronteira
escondia o efeito de hora-do-dia (já confirmado no turno 14) atrás de
subamostragem desigual.

**Teste decisivo executado**: `|z|` médio de TODAS as barras na janela
23:30-00:30 (n=71-103/braço, não mais n=4) vs. resto do dia:

| símbolo | razão C=7 | razão C=1 | incremento C=1/C=7 |
|---|---:|---:|---:|
| BTC | 1,20x | 2,25x | 1,88x |
| ETH | 1,53x | 1,86x | 1,22x |
| SOL | 1,09x | 1,63x | 1,50x |
| BNB | 1,34x | 1,81x | 1,35x |
| XRP | 1,17x | 1,99x | 1,70x |

**O efeito de hora-do-dia é real e aparece nos 2 braços** (`C=7` sempre
>1x) — os números anteriores (fronteira `C=7` "invertida", 0,02-0,42x)
estavam confundidos por amostra pequena, **retratados**. Mas `C=1`
mostra elevação consistentemente MAIOR que `C=7` na MESMA janela, 5/5
símbolos — os 2 mecanismos são reais simultaneamente (base de
hora-do-dia + incremento de transição), confirma a leitura original do
§14.1, não a intermediária do §16.

### O que decide, na reformulação do auditor: nível de sistema, não cauda estatística

Contagem de eventos onde a barra viola o invariante que define
dollar-bar (tamanho por volume, não por troca de threshold com
acumulação em voo): `C=7`≈52/ano/símbolo, `C=1`≈365/ano/símbolo — sem
ambiguidade. Mais 3 argumentos qualitativos: **tipo de erro** (`C=7`
suave, absorvido por feature normalizada; `C=1` discreto, nada absorve,
79 features futuras não avaliadas quanto a isso); **assimetria de estar
errado** (sem métrica de sucesso final — confirmado —, `C=7` errado é
reversível/barato; `C=1` errado é 7x mais artefato em 6 anos × 5
símbolos, possivelmente na cauda onde risco olha); **superfície de
paridade lote↔streaming ao vivo** (`src/live/` vazio ainda — `C=1`
multiplica por 7x os pontos onde o loop ao vivo precisa reproduzir
exatamente a fronteira do backtest).

**`T=7,C=7` — linha de investigação de cadência CONCLUÍDA, não mais
"provisório por motivo em aberto"**: preferido por evidência estatística
parcial (elo real, modesto) + 3 argumentos de engenharia de sistema
independentes. Decisão final fica com o Manager formalizar. Full detail:
`audit/architecture_gaps_log.yaml::AG-124::addendum_correcao_
confundimento_amostral_e_desfecho_final_2026-08-21`.

### S1 — reparametrização aceita: R=tp/sl, S=sl, não tp/sl independentes

Mesmo erro de acoplamento que `T/C` tinha, seria repetido varrendo
`tp_atr_mult`/`sl_atr_mult` crus — nenhum efeito é separável neles
individualmente, mas 2 combinações têm efeito interpretável.
Reparametrizado: `R = tp/sl` controla sozinho o breakeven implícito
(`p_tp* = 1/(1+R)`, hoje 42,86%); `S = sl` controla taxa de eventos,
holding time, saturação da normalização por ATR. Mesmo custo de grid,
cada eixo mapeia numa consequência interpretável, `§16.10` (±50%) se
aplica naturalmente a cada um.

**Leitura primária**: EV por evento em unidades de ATR (`p_tp·R − p_sl`,
múltiplos de `sl`) — não "acima/abaixo do breakeven" (que só dá o
sinal; aumentar `R` baixa o breakeven MAS também baixa `p_tp`, e qual
cai mais rápido é o que a varredura mede — o EV dá a magnitude e tem
máximo).

**Barreira vertical é 3º parâmetro que interage com `S`** — alargar
`(R,S)` com holding máximo fixo converte desfechos que batiam TP/SL em
timeout, medindo parcialmente a conversão em timeout, não a geometria.
Ou escalar a vertical junto com `S`, ou reportar fração de timeout por
célula — sem isso é o mesmo erro de acoplamento com outro nome.

**Grade inicial sugerida**: `R ∈ {1,0; 1,33; 2,0} × S ∈ {0,75; 1,5;
2,25}` — 9 pontos, ponto atual dentro da grade (não na borda), reportar
fração de timeout + taxa de eventos + holding mediano junto com o EV.
**Ainda não executado** — aberto ao Manager confirmar o desenho antes de
rodar (mesma disciplina de todo este documento).
