# Resposta ao protocolo de interrogatório — AG-427/AG-428

**Responde a:** `PROTOCOLO_INTERROGATORIO_AG428_threshold_e_custo.md` (briefing
externo, objeto: mecanismo de threshold do Alpha e a divergência AG-428).
**Método:** 5 investigações paralelas, read-only, sobre o código de produção
e o histórico git real deste repositório (nenhum `.py` executado). Cada
resposta abaixo cita `arquivo:linha` ou commit real. "Não existe"/"não
medido" é mantido como resposta quando é o caso — não foi evitado.
**Formato:** espelha a numeração do protocolo (A1…I4), com a implicação
pré-registrada do protocolo confrontada explicitamente contra o achado.

---

## Veredito executivo sobre as 3 afirmações centrais

| Afirmação do briefing | Veredito | Por quê (resumo — detalhe nos blocos) |
|---|---|---|
| (i) "Nenhum risco financeiro imediato" | **PARCIALMENTE REFUTADA** | Confirmado em código: não existe controle de nocional/risco agregado ativo (A1, A3, A4, D4) — o próprio PRD do projeto já registra isso como *"falha de segurança, não de medição"*. O que fica indeciso é a magnitude (A2: hold time em horas não medido com rigor; A5: distribuição de ATR não percentilada). |
| (ii) "Causa-raiz confirmada: deriva de generalização" | **NÃO SUSTENTADA COM O RIGOR ALEGADO** | O gap nominal-vs-realizado já estava presente nos dados do PRÓPRIO commit que introduziu a janela de calibração, antes de qualquer "descoberta" do AG-428 (E3) — a narrativa de "achado novo" não se sustenta. O pool de calibração do tau NÃO garante exclusão do bloco de fit (E1). O ledger do projeto já registra essa causa como **"ABERTA"**, não fechada — se o briefing a apresentou como confirmada, isso é mais forte do que o próprio registro de origem afirma. |
| (iii) "Correção (TOTAL_COMMON_OOF) rejeitada por eliminação" | **METODOLOGICAMENTE FRACA, NÃO NECESSARIAMENTE ERRADA** | A hipótese específica de bug ("tau único entre lados") está refutada pelo código — o mecanismo é mais sofisticado que isso (F1/F2). Mas a rejeição em si repousa em 1 seed, 1 dos 5 candidatos, sem dispersão (F5) — não é evidência robusta o bastante para "rejeitar", é evidência de "não decidido". |

---

## BLOCO A — Concorrência de posições e alavancagem agregada

**A1** — `control_11_nocional_maximo` recebe só `SizingResult` de UMA ordem; não há parâmetro de portfólio. `src/risk/limits.py:288-294`. O único controle desenhado pra risco agregado (`control_19_risco_agregado`, `limits.py:495-533`) é **sempre `NOT_COMPUTABLE`** — nenhum caller de produção monta as séries de posição/correlação que ele precisa, e `NOT_COMPUTABLE` nunca bloqueia (`evaluate_all`, `limits.py:686-688`).
→ **Interpretação "por ordem" confirmada.** Nada no Risk Engine hoje soma exposição entre posições concorrentes.

**A2** — Não existe medição direta de hold time (horas) por trade nos artefatos mais recentes (`experiments/alpha_walk_forward_*_with_predictions.json` não trazem `entry_time`/`exit_time`). O que existe: `n_bars_held` com mediana=1, p75=3 barras (`config/constants.yaml:1637-1645`, ADR-006), **sem p95**; e duração REAL de barra (calendário, não trade) por combo, em `experiments/dollar_bar_duration_p99_by_resolution.json` (ex.: XRPUSDT/R3 p50=33,1min / p95=213min). Combinando os dois (extrapolação minha, não uma medição do repo): hold mediano da ordem de 1 barra (13-38min dependendo do combo); não há base para estimar p95 de hold com confiança.
→ **Não decidido com rigor.** A pergunta que o próprio protocolo elegeu como a mais decisiva do bloco não tem resposta medida diretamente — só uma extrapolação grosseira que aponta para holds curtos (minutos a poucas horas), não para o "≥24h" que sustentaria concorrência de 5+ posições. Isso pesa contra a gravidade do ataque #1, mas não o resolve.

**A3** — Não existe `max_open_positions` em `constants.yaml` nem controle correspondente em `limits.py`. Existe só como proposta de desenho não implementada (`PLANO_MESTRE_PRINCE2.md:1932-1998`, AG-096/101/102/105 — *"zero código de Decision Engine existe hoje"*, cap sugerido "2 posições" ainda `TBD — medir`).
→ Confirma A1: ausência de limite + controle por-ordem = nenhum mecanismo impede 5 posições a 3,1x, SE elas ocorrerem.

**A4** — Não é medido/gateado. Não há máquina de estados de posição implementada (`FLAT/LONG_PENDING/...` é só especificação em `PRD_V3_2_UNIFICADO.md §10.4`, nunca codificada); `get_position_risk` (`src/exchange/adapter.py:119`) existe como primitivo mas tem **zero callers** em todo `src/`.

**A5** — Não medido. A coluna `atr_at_t0` é produzida em `src/labels/triple_barrier.py`, mas não há relatório de percentis (p5/p25/mediana/p75/p95) por candidato em nenhum artefato do repo. Calcular isso exigiria ler `labels.parquet` diretamente, fora do escopo read-only desta resposta.

**A6** — Não existe teto por trade dentro de `compute_sizing` — só `floor_to_step` (arredondamento pra baixo, `src/risk/sizing.py:184-186`), sem `min()`/`clip()` sobre `notional_real`. O teto de 3,0x é aplicado DEPOIS, como rejeição binária via `control_11` — nunca recorta a ordem, só aceita ou recusa inteira.
→ Junto com A5 não-medido, o risco de cauda de ATR baixo (nocional explode) é um risco **aberto, não refutado nem confirmado**.

## BLOCO D — Sizing e quantização

**D1** — Os 5 símbolos confirmados: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT (`experiments/dollar_bar_duration_p99_by_resolution.json:5-11`). `step_size` em `constants.yaml` é **só BTC** (0,001) com aviso explícito contra reuso (linha 31-36, cita AG-165/AG-190: razão de até 1000x entre ativos). Valores reais por símbolo (snapshot `data/raw/snapshots/exchange_info/2026-08-08.json`): BTC 0.001 / ETH 0.001 / SOL 0.01 / BNB 0.01 / XRP 0.1. `floor_to_step` (`src/exchange/filters.py:81-88`) é chamado por `compute_sizing` (`sizing.py:185`) usando filtros "vigentes na data" via `load_filters_asof` — não o `step_size` genérico de `constants.yaml`.

**D2** — `minNotional` real por símbolo (mesmo snapshot): BTC 50 / ETH 20 / SOL 5 / BNB 5 / XRP 5 USDT. Existe discussão documentada de granularidade quebrando sob capital de R$1000 (`PRD_V4_1.md:202`, erro de quantização de 16,2% em BTC vs. 0,3-1,4% nos demais) — mas a causa apontada é **preço×step_size**, não especificamente "ATR alto"; não encontrei essa ligação exata no repo.

**D3** — O walk-forward (`src/models/walk_forward.py`/`backtest_lite.py`) **não** aplica `floor_to_step` — grep confirma que só 3 arquivos usam essa função e nenhum é de walk-forward/backtest. `backtest_lite.py` documenta explicitamente que reusa `ret_net` já materializado por `triple_barrier.py`, que só quantiza **preço** (tick), nunca **quantidade** (`step_size`).
→ **Os `edge_bps` medidos não passam pela granularidade discreta de posição que existiria numa conta real de R$1000** — são retorno percentual teórico, não simulação de execução com lote inteiro.

**D4** — `risk_per_trade = 0,005` (`constants.yaml:343-349`, classe A, `sweep_required`). O cálculo de risco agregado simultâneo EXISTE como análise: `PRD_V4_1.md:210-224` — 5 posições a ρ=0,91 dá σ=2,408% (4,82x o risco isolado), com nota que ρ real remedido é 0,70-0,83 (AG-144). Mas a linha seguinte é a admissão mais direta encontrada nesta investigação inteira:
> *"O Risk Engine hoje avalia cada posição isoladamente contra 0,50%. **Isso é falha de segurança, não de medição.**"* — `PRD_V4_1.md:224`

## BLOCO B — `control_13` e orçamento de fees

**B1** — **Não está ativo em produção real.** `control_13` só é chamado dentro do próprio módulo de risco e em testes. Não há motor de execução ao vivo (`src/live/__init__.py` é um stub vazio de 2 linhas). A fórmula foi replicada MANUALMENTE uma vez, pra validar o teto econômico do AG-428 — não via chamada de código (nenhum script do AG-428 importa `control_13`/`compute_sizing`).

**B2** — O acumulador `fees_mtd_usd` **não existe implementado** — é só um parâmetro externo injetado (`src/risk/limits.py:317`), com docstring própria admitindo: *"o ledger que soma `fills.fee` do mês é responsabilidade de outra camada, não existe em `risk/`"* (linha 333-335).

**B3** — Híbrido: o nocional usado no custo estimado É pós-`floor_to_step` (`sizing.py:184-186`); mas o custo em si é sempre `estimated_cost_usd` — uma projeção teórica via `round_trip_cost_bps`, nunca fee de fato pago (porque B2 não existe implementado, isso nunca rodou contra dado real fora de teste).
→ Enfraquece o ataque #2 por um motivo mais forte do que o cogitado: não é que o fee realizado seja baixo demais para disparar o bloqueio — é que **o controle inteiro nunca roda em produção**, então a pergunta "quando ele bloquearia" é hoje contrafactual.

**B4** — Confirmado: walk-forward/backtest ignoram `control_11`/`control_13` inteiramente. Grep não encontra nenhuma referência a `risk.limits`/`evaluate_all`/`fee_budget` dentro de `walk_forward.py`/`backtest_lite.py`/`economic_gate.py`. Os módulos de `src/analysis/` que leem `fee_budget_monthly` usam só pra estimar capacidade teórica de trades/mês, nunca para interceptar a simulação.
→ **Os `edge_bps` reportados vêm de um mundo onde todo trade sempre executa**, sem nenhum orçamento de fee ou nocional máximo interferindo.

**B5** — `docs/SPRINT_LOG.md:6820-6825` e `audit/architecture_gaps_log.yaml:28130-28133` só apresentam a base MENSAL (5,88%/mês). Não há nenhuma conversão anual em nenhuma das duas fontes que registraram a autorização.

## BLOCO H — Rastreabilidade da constante e da projeção de custo

**H1** — Histórico real (`git log`/`git show`): `0,0189 → 0,0284` no commit `224a062` (2026-09-03 09:14, AG-427) — **e este mesmo commit criou `tau_calibration_window_days=180` simultaneamente**; depois `0,0284 → 0,10` no commit `947213b` (2026-09-03 14:01, AG-428, só mexeu na taxa/sweep_range, não na janela).
→ **Confirma o confundimento apontado no protocolo**: a correção do mecanismo de tau (janela) e a primeira mudança de taxa nominal entraram JUNTAS no mesmo commit — não há uma medição isolada de "só a janela, taxa constante" no histórico.

**H2** — Sob a taxa antiga (0,0189), a razão realizado/nominal medida em ADR-005 foi **~25,6%** (`tests/unit/test_analysis_tau_diagnostics.py`, xfail documentado). Sob a faixa nova (0,0284-0,15, mesmo commit `224a062`, `experiments/tau_sweep_stage_B.json`), a razão é **62,6%-72,8%**. **A razão NÃO é constante entre regimes — mudou de ~26% para ~65-70%.**
→ A premissa de "escalar linearmente pela razão das taxas nominais" está refutada pela própria medição do repositório — não é um fator fixo, é sensível ao mecanismo/nível.

**H3** — Distinção `n_folds_total`/`n_folds_degenerados`/`n_folds_usados` existe em código (`src/models/walk_forward.py:331-334`, piso `min_trades_threshold=10`). Contagem real no artefato mais recente (`run_stamp=20260903T192150Z`, pós-Optuna sob 0,10): **60 folds degenerados de 143 folds totais** nas 10 células (tabela completa por combo×camada disponível no relatório-fonte). *(Nota: isso é contagem por FOLD, não por CÉLULA — a métrica "6/10 → 7/10 células passam o gate Data" citada em relatórios anteriores é sobre quantas das 10 células combo×camada cruzam o piso de folds usados, um agregado diferente desta tabela.)*

**H4** — `scripts/ag428_signal_rate_decomposition.py` inclui as **duas camadas de TODOS os 5 combos** (10 arquivos parquet) e as concatena verticalmente (`pl.concat(..., how="vertical_relaxed")`) **sem nenhuma deduplicação**. Isso é factual — mas a implicação de "dado duplicado" do protocolo (referenciando AG-393, camadas byte-idênticas em 4 folds) não está confirmada aqui: o script não testou se as linhas concatenadas são de fato idênticas entre camadas, só que não há proteção contra isso se fossem. Fica como risco não descartado, não como dedup confirmado.

**H5** — `fee_budget_monthly` é `provenance: ASSUMED`, `source: "sem base; inventado (§18.5.1)"` (`constants.yaml:235-242`), inalterado desde antes do AG-427/428. Com a mudança de `target_signal_rate` de `DERIVED` (dessa constante) para `MEASURED` própria, **o teto de 3%/mês ficou desconectado do valor que hoje custa 5,88%/mês** — quase o dobro de um teto nunca revisado.

## BLOCO C — Reconciliação bruto/líquido

**C1** — `ret_net` (`src/labels/triple_barrier.py:1653-1663`) **JÁ é líquido**: `ret_net = ret_gross − cost_entry − cost_exit − funding_frac`. Não é bruto.
→ A hipótese "bruto" cai. Mas a implicação de "dupla contagem" do protocolo precisa de uma ressalva: `edge_bps` (retorno esperado por trade, já líquido) e a projeção de R$58,85/mês (fluxo de caixa total de fee esperado) respondem perguntas diferentes — uma é "quanto sobra", a outra é "quanto sai do bolso em fee" — usar o mesmo `round_trip_cost_bps` nas duas contas não é necessariamente contar o mesmo evento duas vezes, seria dupla contagem só se a projeção de custo fosse subtraída DE NOVO de um edge que já a descontou pra compor um P&L líquido final. Não encontrei essa segunda subtração em nenhum artefato — os dois números coexistem como métricas distintas (retorno esperado vs. orçamento de custo), não como uma soma inválida.
**Ressalva mais importante que a de dupla contagem:** `adverse_selection_bps` (1,5bps, `ASSUMED`) é **reportado mas não subtraído** de `ret_net` (docstring explícita, `triple_barrier.py:46-53`) — e não há termo de spread nenhum (ver C5). Ou seja: "líquido" aqui é líquido de fee+funding, **não líquido de todos os custos reais de transação**.

**C2** — Tem termo de funding, e é **medido de dado real** (não placeholder): `funding_frac` soma eventos reais de `lake.query_funding` entre `t_entry` e `t1` (`triple_barrier.py:1657-1663`). `grep -i funding src/` retorna 49 arquivos — não é ausência.

**C3** — `round_trip_cost_bps_maker_prob=0,4942` é medido sobre **todas as barras rotuladas** (`P(TP|preenchido)=TP/(TP+SL+TIME)`, `tools/diagnostics/measure_barrier_touch_probability.py:86-120`), **sem filtro por `confidence`/`tau`**.
→ Confirma a leitura desfavorável: é uma propriedade da geometria de barreira/mercado, medida na população geral, não na população de trades que o modelo de fato seleciona.

**C4** — Confirmado: TP assume fill exato sempre (`triple_barrier.py:1046-1048`, `exit_price = tp_price` literal, sem gap-through). Contraste real: SL TEM fill gap-aware (`_gap_aware_sl_fill`, linhas 981-1010) porque é ordem a mercado, TP é ordem passiva. É uma assimetria de otimismo real, não hipotética.

**C5** — **Não existe termo de spread na cadeia de custo** (`triple_barrier.py`/`sizing.py`: 0 ocorrências reais; `group_e.py` tem 1 ocorrência, falso positivo — `e17f_retail_vs_top_spread` é posicionamento long/short, não bid-ask). Spread existe só como (a) guardrail pré-trade desligado por falta de feed ao vivo (Controle 17, `src/risk/limits.py`) e (b) feature de regime desligada (S2 `stress.py`, `spread_pctile_expanding=None` hardcoded). **Nunca é subtraído do retorno do trade.**
→ Confirma a leitura mais grave do protocolo: todo `edge_bps` do projeto é bruto-de-spread.

## BLOCO I — Lacunas de medição

**I1** — Existe medição real do edge por decil de confiança (AG-407, `scripts/measure_q10_q1_pooled.py`, artefato pooled 2026-08-31): resultado é **misto, não monotônico** — Camada1 short +45,55bps (66,7% folds com sinal positivo, o único caso com maioria clara), mas Camada1 long −5,37bps e Camada0 short −9,80bps (33,3% positivos, maioria na direção OPOSTA à hipótese). Veredito do próprio AG-407: não há sinal consistente forte em nenhuma célula.
**Ressalva crítica de proveniência:** essa medição é do regime **anterior** ao AG-427/428 (pré-janela-de-180-dias, pré-`target_signal_rate=0,10`). **Não encontrei recomputação desse Q10-Q1 pooled sob o regime atual.** A pergunta "os trades marginais entre tau(0,0284) e tau(0,10) têm edge pior?" segue **não medida no regime vigente** — é a lacuna real que o protocolo aponta, só que parcialmente coberta por uma medição desatualizada, não zero.

**I2** — Sim, reconhecido explicitamente na MESMA entrada, não em decisões separadas e desconectadas: `docs/SPRINT_LOG.md:6737/6777` (AG-427: *"ainda 0/20... Resultado: continua 0/20"*) e `:6788/6836` (AG-428: *"ainda 0/10... Resultado: continua 0/10 combo×camada"*) — a autorização de subir a taxa foi registrada no mesmo texto que declara o veredito 0/10, não escondida em documento separado.
**Achado colateral relevante:** os 4 edges citados no protocolo (+16,81/+12,59/+10,23/+14,41bps) **não são uma série homogênea** — os dois primeiros são da política de produção (`LEGACY_PER_SIDE`); os dois últimos são da mesma célula sob `TOTAL_COMMON_OOF`, política experimental **nunca promovida** e cujo próprio texto de origem alerta *"NÃO PROMOVER a produção sem investigar"* (`constants.yaml:853`). Se o briefing os apresentou lado a lado sem essa distinção, mistura produção real com experimento descartado.

**I3** — Confirmado: `compute_score_quality` (o gate Model original da ADR-008) calcula AUC só sobre a população que já cruzou `tau` E venceu a competição long/short (`side_hat != 0`, `score_quality.py:266-296`). Existe uma função separada, criada depois por auditoria adversarial (AG-394), `compute_score_quality_full_population`, cuja própria docstring admite: *"esta função mede... a pergunta que o gate Model da ADR-008 tentava responder e, por medir a população errada, não respondia"* (`score_quality.py:393-407`) — mas ela é reportada como campo adicional, **não substitui** o gate original.
→ Mudar `target_signal_rate` de fato alarga a população selecionada 3,5x — os AUCs do gate Model mudam por razão mecânica quando isso acontece, não necessariamente por mudança de sinal real.

**I4** — Não existe. `grep signal_rate` fora de `models/`/`analysis/` retorna zero; `src/live/` está vazio; `src/monitoring/` só tem drift de dollar bar e logging estruturado. Todo `signal_rate_realized` citado nos achados vem de walk-forward sobre histórico OOF, nunca de operação viva — porque não há caminho de execução viva implementado.

## BLOCO E — Pool de calibração do tau

**E1** — **Não exclui garantidamente o `fit`.** `_select_tau_calibration_pool` (`alpha.py:1945-2006`) filtra só por TEMPO (`t0 >= max(t0) - 180 dias`), nunca por índice de fit/calib/stop. Como `calibrated_train_all` é a predição do modelo sobre TODO `X_all` (incluindo as próprias linhas de `X_fit`, `alpha.py:1735-1736`), se a janela de 180 dias corridos alcançar o bloco de fit (o que depende de densidade de barras, não medido — ver E2), o pool herda score in-sample.
→ Confirma a leitura desfavorável do protocolo: a janela de 180 dias resolve um problema de tempo, não garante ausência de contaminação in-sample. Contraste: a política experimental `TOTAL_COMMON_OOF` (`_resolve_tau_on_common_bars`) **essa sim** exclui explicitamente `t0` vistos no fit — ou seja, o mecanismo mais rigoroso já existe no código, só não é o de produção.

**E2** — Não medido/persistido. `n_in_window` é calculado (`alpha.py:1990`) mas só logado no ramo de FALHA (amostra insuficiente); no caminho normal de sucesso, é descartado sem registro. A cifra "66k-217k barras de treino" citada no protocolo **não foi localizada em nenhum artefato deste repositório** — pode vir de um documento externo ao repo que não pude auditar.

**E3** — **Achado mais forte desta investigação.** O gap nominal-vs-realizado (62,6%-72,8%, a mesma ordem de grandeza que o AG-428 chamou de "achado novo") **já estava presente em `experiments/tau_sweep_stage_B.json`, gerado pelo PRÓPRIO commit `224a062` (AG-427)**, ANTES de qualquer commit do AG-428 existir. A alegação registrada em `constants.yaml:801-804` — *"ACHADO NOVO (não visto na rodada 1, sweep_range antigo não alcançava esta faixa)"* — está **contradita pelos dados do próprio repositório**: o fenômeno não estava fora de alcance, estava nos dados da rodada 1 e simplesmente não foi comparado explicitamente contra o nominal, porque o critério de leitura da rodada 1 era só fração de folds usáveis/desvio-padrão, não essa razão.

**E4** — Tem fonte real: `scripts/sweep_tau_mechanism.py --stage A`, artefato `experiments/tau_sweep_stage_A.json` existe e bate com os números citados na proveniência (`constants.yaml:895-932`). Não é `MEASURED` sem base. **Ressalva real:** só 4 candidatos discretos (`None/90/180/270`), **1 seed única**, "vencedor claro" lido de uma realização determinística, não de uma distribuição.

**E5** — Sim, existe (o mesmo sweep de E4). Não há segundo sweep depois de 180 fixado; nenhuma janela ≥365 dias foi testada.

## BLOCO F — `TAU_POLICY_TOTAL_COMMON_OOF`

**F1/F2** — "COMMON" = população de **barras** comum aos dois lados, não um tau único. Cada lado mantém seu próprio `tau_long`≠`tau_short` (quantis de seus próprios vetores de score); o que é comum é o **nível do quantil `q`**, resolvido por bisseção pra bater a taxa total (`resolve_joint_tau`, `alpha.py:641-713,696-700`).
→ **A hipótese específica de F1 (bug de "tau único partilhado") não se sustenta** — o mecanismo é mais sofisticado do que "quantil sobre a união aplicado a cada lado".

**F3** — "OOF" = fora do **fit** dentro do MESMO fold (bloco `calib`/`stop` do treino desse fold, ou NOFILL de qualquer lado) — não é out-of-fold do walk-forward real (`alpha.py:2033-2038,2057-2066`). É uma garantia mais fraca do que "OOF" sugere à primeira leitura, mas não é o bug ("scores do próprio fit") que a interpretação cética cogitava.

**F4** — Confirmado, mesmo `target_signal_rate=0,10` de produção (`experiments/..._total_common_oof.json`, texto de `constants.yaml:842-843` cita "nominal (0,10)" explicitamente). Comparação é pareada nesse quesito.

**F5** — **1 seed única (42)**, sem dispersão, testado **só em XRPUSDT/R3** (não nos 5 candidatos). O próprio script reconhece a lacuna: *"Item 4 do roadmap 'Caso 0/20' (≥5 seeds)"* ainda não aplicado a este teste especificamente.
→ **A rejeição de `TOTAL_COMMON_OOF` repousa numa única realização determinística de 1 candidato.** Não sustenta "rejeitada" com o rigor que uma decisão de não-promoção deveria ter — sustenta "não decidido com poder estatístico suficiente".

## BLOCO G — Assimetria long/short

**G1** — Granularidade real do script (`scripts/ag428_signal_rate_decomposition.py`): por combo (10 combos symbol×resolution×camada) e pooled — **sem nenhuma granularidade temporal** (trimestre/mês). **A cifra "sobreposição = 0,27% da união" citada no protocolo não foi localizada em nenhum artefato deste repositório** — o script nem calcula interseção (`AND` dos dois lados), só união (`rate_naive_or`). Se esse número existe, não está neste script nem em nenhum artefato auditável por mim.

**G2/G3** — Não medido — nenhum artefato cruza `rate_long_alone`/`rate_short_alone` com direção de preço por período. O ledger admite isso: *"Investigação da deriva temporal permanece ABERTA -- causa exata não isolada quantitativamente, só inferida por eliminação"* (`architecture_gaps_log.yaml:28254-28256`). Os ingredientes brutos para fazer esse cruzamento existem em disco (parquets com `t0` real, séries de preço diário reais desde 2020) e há até um mecanismo genérico de estratificação temporal (`stratified_by_time`, `src/analysis/calibration_diagnostics.py:456-485`) — mas nunca foi exercitado sobre dado de produção real, só em teste sintético.
→ **G2 é a pergunta de falsificação mais crítica do protocolo inteiro e continua sem resposta** — nem confirma nem derruba a hipótese de deriva direcional de mercado.

**G4** — Parcialmente confirmado: mesmas COLUNAS de feature nos dois lados (`build_design_matrix`, sem transformação condicional a side, `alpha.py:329,1396`), mas a POPULAÇÃO de linhas treinadas por lado **não é garantidamente a mesma** — cada lado filtra seu próprio `labels.parquet` por `side==valor` e por `NOFILL`/R2 daquele lado (`src/models/dataset.py:713-745`), que podem divergir entre long e short.

**G5** — `src/analysis/label_audit.py` existe, mede exatamente `P(TP)` por lado (`compute_label_distribution_stats`, linhas 69-149) — mas **nunca foi executado contra dado real de produção**, só validado com dados sintéticos em teste unitário (nenhum artefato/output em `experiments/`, zero menção em `SPRINT_LOG.md`).

---

## Testes de falsificação — resolução

| Teste | Resultado | O que isso faz com a crítica original |
|---|---|---|
| A2 hold < 6h | **Não medido com rigor** (só extrapolação grosseira, aponta pra holds curtos) | Nem confirma nem derruba o ataque #1 — mas A1/A3/A4 (ausência estrutural de controle) seguem válidos independente do resultado de A2 |
| A1 control_11 agrega | **Não agrega — por ordem** | Ataque #1 permanece de pé estruturalmente |
| E1 pool exclui fit | **Não exclui garantidamente** | Ataque #5 (in-sample) permanece de pé — "deriva temporal" não ganha força adicional por aqui |
| G2 assimetria persiste em queda | **Não testável com dado existente** | Nem confirma nem derruba a hipótese de deriva direcional — fica aberto |
| C1 edge_bps é bruto | **É líquido** (de fee+funding, não de spread/seleção adversa) | Acusação de dupla contagem não se sustenta como formulada; mas "líquido" é incompleto (falta spread, confirmado em C5) |
| B3 fee realizado + nocional quantiza pra baixo | **Parcial** — nocional é pós-quantização, mas fee é sempre projetado (B1: controle nunca roda em produção) | Ataque #2 cai por um motivo mais forte: o controle não existe em produção nenhuma, não é questão de fee ficar abaixo do limiar |
| F1 "COMMON" ≠ tau único | **Confirmado, COMMON é população de barras, não tau único** | A inferência por eliminação da §3.4 recupera parte da validade quanto a ESSA hipótese específica — mas F3/F5 (OOF fraco, 1 seed) seguem limitando a força da conclusão "rejeitada" |

---

## Recomendações objetivas (fora do escopo de pergunta-resposta, mas decorrentes)

1. **I1 refeito sob o regime atual** (`target_signal_rate=0,10`, mecanismo de janela): sem isso, a pergunta "os trades marginais têm edge pior" segue sem resposta atualizada — é a lacuna de maior alavancagem sobre a decisão já tomada.
2. **G2/G3 são baratos de responder** com dado já existente (parquets de predição + séries de preço diário já em disco) — não exigem retreino, só um script novo de agregação. Resolveria o bloco G quase por completo.
3. **F5 com múltiplas seeds e nos 5 candidatos**, não só XRPUSDT/R3, antes de qualquer reafirmação de "rejeitado" para `TOTAL_COMMON_OOF`.
4. **`fee_budget_monthly` (ASSUMED, 3%) está desconectado do custo real (5,88%/mês) desde que `target_signal_rate` virou `MEASURED` independente** — ou o teto é revisto com base real, ou o motor está operando sob um orçamento que ninguém validou e que já excede em quase 2x.
5. A ausência de qualquer controle de risco agregado ativo (A1/A3/D4) e de execução viva que rode `control_11`/`control_13` (B1/B4) não é um achado NOVO desta investigação — é uma lacuna já registrada em `PRD_V4_1.md §5.3` como "falha de segurança, não de medição". Vale reafirmar prioridade antes de qualquer promoção a capital real.
