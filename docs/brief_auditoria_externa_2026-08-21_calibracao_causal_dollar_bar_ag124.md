# Brief para Auditoria Externa — Recalibração causal do threshold dollar-bar (AG-124)

### Da deriva medida (18x–42x) à janela de 7 dias — o que a medição mostra, e onde ela ainda pode estar errada

**Data:** 2026-08-21
**Para:** revisor externo (sem acesso ao repositório — este documento é a fonte completa)
**Documentos canônicos deste projeto (só 2, decisão do Manager 2026-08-20):** `PLANO_MESTRE_PRINCE2.md` (governança/decisões) e o ADR-001 completo (~1900 linhas — arquitetura de artefatos e contratos de dado). Documentos `PRD_*` são **OBSOLETOS** — citados aqui só quando relevantes pra explicar uma divergência histórica, nunca como justificativa de desenho atual.

---

## 0. Como usar este documento

Este brief cobre uma decisão única, mas ela é a porta de entrada pra uma ação cara e difícil de reverter: **reprocessar 6+ anos de histórico de trades, nos 5 ativos do motor, se a recalibração causal for confirmada como necessária.** Nada foi reprocessado ainda — o código está pronto e testado só com dado sintético, a medição foi feita só sobre dado bruto já existente (leitura, não reescrita). O pedido concreto (§9) é: valide se a decisão de desenho (janela de 7 dias) está bem sustentada pela medição, ANTES de autorizarmos a ação real.

Contexto do motor, pra quem não tem nenhum: **dollar bar** é uma barra de preço que fecha quando o volume monetário acumulado atinge um limiar (`threshold_usdt`), não quando um intervalo de tempo fixo passa (diferente de candle de 15 minutos, por exemplo). É a grade canônica de decisão deste projeto (decisão já ratificada, fora do escopo deste brief).

---

## 1. Contexto — o que é o vazamento, e por que "só um threshold" importa tanto

O motor constrói dollar bars calibrando `threshold_usdt` uma vez por símbolo, sobre TODA a janela histórica que depois é construída — a mesma função que calibra é a mesma janela que é convertida em barras. Isso significa: o threshold usado pra decidir onde uma barra de **janeiro/2020** fecha foi calibrado usando volume observado até **2026**.

**Por que isso é vazamento genuíno, não só "densidade muda com o tempo"**: o algoritmo de agregação em si é 100% causal dado um threshold fixo (processa trades estritamente em ordem cronológica, paridade lote↔streaming provada por 16 testes). O que não é causal é o VALOR do threshold — e como `bar_id = cum_value // threshold`, um threshold diferente reparticiona os MESMOS trades em barras diferentes. Isso muda o CONTEÚDO (open/high/low/close/volume) das barras antigas, não só sua contagem ou densidade.

Deriva medida na primeira rodada (janela estreita, só BTC, jan/2020–mar/2024): **18,18x**. Medição completa desta rodada (histórico inteiro, 5 símbolos, granularidade mensal): a deriva real é maior — BTCUSDT **42,7x**, ETHUSDT 10,4x, SOLUSDT 19,5x, BNBUSDT 14,6x, XRPUSDT 18,3x (verificado direto do JSON bruto de medição, não só reportado).

---

## 2. A solução de desenho — recalibração causal rolante

Decisão do Manager: em vez de UM threshold pra toda a história, recalibrar periodicamente, cada período usando só dado ESTRITAMENTE anterior a ele (`[app_start - trailing_window_days, app_start)`, nunca `app_start` em diante). Os dois parâmetros livres, `trailing_window_days` (quanto histórico passado usar pra calibrar) e `cadence_days` (de quanto em quanto tempo recalibrar), foram tratados como o MESMO parâmetro (`cadence == trailing_window`, blocos não sobrepostos) — não dois graus de liberdade independentes. Isso não foi decidido por conveniência; foi decidido porque testar os dois desacoplados multiplicaria o espaço de busca sem uma hipótese clara de que valeria a pena (ver §8, pergunta 5 — isso é justamente uma das coisas que pedimos pra revisar).

Nenhum valor de `trailing_window_days`/`cadence_days` foi escolhido antes de medir — a disciplina do projeto proíbe explicitamente estipular um número sem medição real (equivalente ao B23 deste projeto: nunca inventar faixa esperada).

---

## 3. A medição — 3 rodadas, granularidade decrescente

Metodologia: para cada janela `W` testada, um esquema **rolling** — o bloco `[i, i+W)` calibra (`calib_rate = total_dollar/total_days` dentro do bloco), o bloco seguinte `[i+W, i+2W)` aplica essa taxa e mede o erro (`dollar_per_day` real de cada período do bloco de aplicação ÷ `calib_rate`), e a iteração seguinte começa em `i+W` — ou seja, o bloco de APLICAÇÃO de uma iteração vira o bloco de CALIBRAÇÃO da iteração seguinte, não um par fixo que calibra-aplica-e-pula. Isso é o que faz o método bater com o comportamento real de `build_dollar_bars_walkforward` em produção (cada período recalibra usando os `trailing_window_days` estritamente anteriores, avançando `cadence_days` por vez). Um período "erra" se a razão for ≥2x ou ≤0,5x. Metodologia validada ANTES de confiar nela: reproduziu exatamente 2 números já publicados de uma medição anterior mais estreita (XRPUSDT: 17,86%≈"17,9%" publicado; 41,67%="41,7%" publicado, exato) — confirma que o método reflete o desenho real (`cadence == trailing_window`, esquema rolling), não uma variante ingênua (que teria dado 25,49% em vez de 41,67% no mesmo teste). (Correção 2026-08-21: uma versão anterior deste parágrafo descrevia o mecanismo como "o primeiro bloco calibra, o segundo aplica", implicando um par fixo — imprecisão de prosa pega por auditoria externa, pergunta 9; o código sempre foi rolling, só o texto estava impreciso. Ver `AG-136`.)

Rodada 1 (mensal, 309 símbolo-mês), rodada 2 (semanal, 1.325 símbolo-semana), rodada 3 (diária, 9.256 símbolo-dia) — todas com histórico completo real, os 5 símbolos.

**Tabela comparativa — % de períodos com erro ≥2x ou ≤0,5x, por janela e símbolo:**

| janela | BTC | ETH | SOL | BNB | XRP |
|---|---|---|---|---|---|
| 1 dia | 16,42 | 16,32 | 11,64 | 14,21 | 15,50 |
| 2 dias | 20,71 | 19,32 | 14,17 | 17,21 | 19,50 |
| 4 dias | 17,69 | 17,25 | 16,43 | 19,72 | 20,83 |
| **7 dias** | **16,20** | **16,52** | 17,99 | 20,28 | 21,81 |
| 14 dias | 17,08 | 17,83 | 21,84 | 24,20 | 27,27 |
| 21 dias | 18,33 | 18,81 | 21,61 | 27,50 | 32,92 |
| 1 mês (granul. mensal)\* | 3,75 | 0,00 | 8,93 | 14,29 | 17,86 |
| 6 meses (granul. mensal)\* | 13,89 | 25,00 | 27,08 | 27,08 | 41,67 |

\* Linhas marcadas avaliam erro **1x por período inteiro** (escondem oscilação intra-período); as 4 primeiras linhas avaliam **1x por dia**, mesmo dentro de blocos maiores — por isso não são diretamente comparáveis entre si em valor absoluto, só em TENDÊNCIA dentro do mesmo bloco de granularidade de avaliação. Isso por si só é um ponto que merece ceticismo externo — ver §8, pergunta 2.

**Achado 1 — deriva secular**: dentro de qualquer granularidade de avaliação fixa, erro cresce com janela mais longa (ex. mensal: 1 mês 3,75%→6 meses 13,89% pra BTC). Volume de cripto tende a persistir na direção, não reverter à média — "suavizar" com mais histórico piora a calibração, não ajuda.

**Achado 2 — reversão em BTC/ETH abaixo de 7 dias**: dentro da granularidade diária (a mais fina, mais honesta), SOL/BNB/XRP melhoram monotonicamente até 1 dia — mas BTC/ETH **revertem**: erro pica em 2-4 dias, cai de novo só em 7.

---

## 4. O mecanismo por trás da reversão — sazonalidade de fim de semana

Investigado, não só observado. `dollar_per_day` de sábado cai pra **0,593x** a média geral em BTCUSDT (verificado por mim diretamente, recalculando do JSON bruto — bate com o número do agente que fez a medição original, ~0,57-0,59x). Domingo, ~0,70x. Segunda a sexta, todos >1,1x. O mesmo efeito existe nos outros 4 símbolos, mas mais fraco (sábado ~0,70-0,73x da média, não ~0,59x).

Qualquer bloco de calibração/aplicação MAIS CURTO que 7 dias corridos "sorteia" quais dias da semana específicos ele contém. Estratificando o erro por dia-da-semana do período de APLICAÇÃO (janela de 1 dia): segunda-feira concentra 32,0% de erro ruim em BTCUSDT (calibrada pelo domingo, volume baixo), sábado concentra 50,6% (calibrado pela sexta, volume alto) — ETHUSDT ainda mais extremo (segunda 29,9%, sábado 52,9%). Blocos de 7 dias (e múltiplos exatos: 14, 21...) garantem por construção exatamente 1 ocorrência de cada dia da semana dentro de si — elimina esse artefato de aliasing, não por sorte.

**Conclusão do time interno**: `trailing_window_days=7`, `cadence_days=7` — não é mais só "a janela empiricamente melhor testada", é "o menor múltiplo exato do ciclo sazonal semanal que ainda evita a deriva secular de janelas mais longas". Sugestão pronta pra travar, pendente desta revisão.

---

## 5. Arquitetura implementada (código já escrito e testado com dado sintético)

- **Schema**: cada barra passa a carregar `threshold_quote` (o threshold específico que a fechou) — antes, um único escalar valia pra todo um diretório de símbolo. Guarda antiga que rejeitava "threshold divergente" no mesmo diretório foi removida (deixou de fazer sentido sob threshold que varia por desenho).
- **Orquestrador** (`build_dollar_bars_walkforward`): particiona `[start, end]` em períodos de `cadence_days`, calibra cada um sobre `[app_start - trailing_window_days, app_start)` — reusa as funções de calibração/construção já existentes SEM modificá-las, só troca o argumento de janela. Primeiro período de cada símbolo é descartado (cold-start, sem histórico anterior suficiente pra calibrar causalmente).
- Nada disso rodou contra dado real de produção ainda.

---

## 6. Verificação mecânica (já feita, não precisa ser reconferida)

`ruff`, `mypy --strict`, verificador de literais numéricos fora de config (nenhum threshold/janela é hardcoded fora de parâmetro explícito), verificador de divisão sem guarda de sinal — todos limpos nos arquivos tocados. 184 testes novos/atualizados, todos verdes. 3 números da medição foram recomputados por mim independentemente, direto dos JSONs brutos, sem usar o script de análise — bateram exatos em todos os casos.

---

## 7. Achados colaterais (não bloqueantes, registrados por transparência)

- Uma tentativa anterior de reprocessar dado sob concorrência alta travou 9h+ sem log (bug de amplificação de memória num pipeline relacionado, não neste código) — já diagnosticado e corrigido numa rodada anterior, confirmado com um run real instrumentado (sem travar). Mitigação (chunk de processamento reduzido, caminho isolado) já é o comportamento padrão hoje — não é mais um risco em aberto, só uma precaução operacional já incorporada.
- O mecanismo de proteção do CPCV (partição de dado pra validação cruzada) contra vazamento entre janelas de treino/teste já opera inteiramente em timestamp, nunca em identificador de barra — confirmado que a recalibração periódica NÃO exige nenhuma mudança nesse mecanismo (achado que simplificou o desenho original).

---

## 8. Perguntas que um revisor cético deveria fazer

1. **O limiar "erro ruim" (razão ≥2x ou ≤0,5x) foi escolhido por convenção, nunca justificado contra uma consequência real medida no pipeline downstream.** Um erro de calibração de, digamos, 1,8x muda materialmente o resultado de algo que consome essas barras (ex. um modelo de detecção de regime, ou o cálculo de risco), ou é cosmético até passar de 2x? Sem essa ponte, o % reportado é uma métrica de PROCESSO (quão perto o threshold fica do "certo"), não necessariamente uma métrica de IMPACTO real.

2. **A metodologia nunca testou `cadence_days` desacoplado de `trailing_window_days`.** Um desenho com janela de calibração LONGA (mais estável, menos sujeita a ruído de curto prazo) mas cadência de aplicação CURTA (recalibra com frequência, mesmo que a fonte de calibração seja mais lenta) nunca foi medido — é uma região inteira do espaço de desenho inexplorada. Vale medir antes de travar `cadence == trailing_window` como definitivo?

3. **A explicação de sazonalidade de fim de semana é elegante e o mecanismo bate com o dado (verificamos: sábado ~0,59x em BTC) — mas é a explicação SUFICIENTE, ou só a mais visível?** Feriados de calendário tradicional (Natal, Ano Novo, datas de baixa liquidez em mercados tradicionais que ainda influenciam cripto) não foram testados separadamente. Se houver um segundo efeito de calendário sobreposto ao semanal, `W=7` resolve o aliasing semanal mas pode deixar um viés residual não capturado nesta medição.

4. **Dado que TODO resultado já medido sobre a grade atual (não-causal) vira provisório se a recalibração for confirmada como necessária — o custo de reabrir/reconfirmar cada um desses resultados foi pesado contra o benefício de corrigir agora, versus esperar um momento mais próximo do treino real de produção?** O motor já tem um histórico de resultados que precisaram ser revistos múltiplas vezes na mesma sessão (não é hipotético — aconteceu com outra decisão de arquitetura deste mesmo projeto, mesma semana). Vale considerar se corrigir a grade agora, antes do próximo retreino real, é estritamente melhor do que esperar e corrigir uma vez só, mais perto do consumo real?

5. **O mecanismo de proteção contra "estouro de trades acumulados" (circuit breaker) foi calibrado usando estimativas de cauda de uma medição menos granular (mensal) — a medição diária revelou razões de pico bem mais altas (até ~14x numa única semana) do que a medição mensal original via.** Isso foi propagado de volta pra confirmar que o circuit breaker ainda cobre esses casos extremos com a mesma margem de segurança, ou é uma checagem pendente?

6. **A deriva secular (achado 1, §3) e o aliasing semanal (achado 2, §4) foram tratados como dois fenômenos independentes que "empurram" a janela ótima em direções opostas (secular empurra pra mais curto, aliasing empurra pra múltiplo de 7) — mas eles foram genuinamente decompostos, ou é possível que parte do que parece "aliasing" seja na verdade deriva secular disfarçada** (ex. se o período de medição mais recente coincidir sistematicamente com dias específicos da semana por algum motivo de amostragem)? Vale um teste que controle os dois fatores simultaneamente antes de aceitar a explicação como definitiva.

---

## 9. O que pedimos exatamente

- Validar OU refutar a leitura do §4: a reversão em BTC/ETH abaixo de 7 dias é genuinamente explicada por aliasing de dia-da-semana, e `W=7` é a escolha estruturalmente correta (não só empiricamente conveniente)?
- Avaliar se a pergunta 2 (§8) — desacoplar `trailing_window_days` de `cadence_days` — é uma lacuna real de desenho que vale medir antes de prosseguir, ou uma otimização de segunda ordem que pode ficar pra depois.
- Recomendação concreta: (a) travar `7/7` e autorizar o reprocessamento real dos 5 símbolos agora; (b) medir mais uma dimensão específica antes (qual, das perguntas do §8); ou (c) esperar um momento mais próximo do consumo real de produção antes de reprocessar, aceitando o risco documentado por mais tempo.
- Se possível, uma leitura sobre a pergunta 1 (§8) — o limiar de "erro ruim" em si — mesmo sem acesso ao pipeline downstream completo: existe uma forma padrão na literatura de barras de volume/dólar de ancorar esse limiar numa consequência prática, em vez de convenção?

---

## 10. Anexos técnicos — código citado

```python
# Janela de calibração ESTRITAMENTE anterior ao período de aplicação --
# nunca inclui app_start em diante (isso reproduziria o vazamento original).
def _trailing_calibration_window(app_start: str, *, trailing_window_days: int) -> tuple[str, str]:
    app_start_date = date.fromisoformat(app_start)
    calib_end = app_start_date - timedelta(days=1)
    calib_start = app_start_date - timedelta(days=trailing_window_days)
    return calib_start.isoformat(), calib_end.isoformat()
```

```python
# Metodologia de medição de erro -- blocos NAO sobrepostos, cadence ==
# trailing_window (mesmo par que build_dollar_bars_walkforward usa).
# O bloco de aplicação final incompleto é DESCARTADO (confirmado contra
# número já publicado: contá-lo dava 43,14%, descartar deu 41,67%, que
# bate com o valor de referência).
def _calibration_errors_for_window(rows: list[dict], window: int) -> list[float]:
    ratios: list[float] = []
    n = len(rows)
    block_start = 0
    while block_start + 2 * window <= n:
        calib_block = rows[block_start : block_start + window]
        apply_block = rows[block_start + window : block_start + 2 * window]
        calib_dollar = sum(r["total_dollar"] for r in calib_block)
        calib_days = sum(r["n_days"] for r in calib_block)
        calib_rate = calib_dollar / calib_days
        for r in apply_block:
            ratios.append(r["dollar_per_day"] / calib_rate)
        block_start += window
    return ratios
```

```python
# ThresholdBarsCarry nunca cruza fronteira de período -- cada período
# recomeça do zero, o que limita o pico de memória ao tamanho de 1
# período (mais conservador que qualquer coisa já testada antes).
# (assinatura real, corpo interno reusa funções de calibração/construção
# já existentes sem modificação, só troca o argumento de janela)
def build_dollar_bars_walkforward(
    symbol: str, start: str, end: str, *,
    resolution_id: str, trailing_window_days: int, cadence_days: int,
    dest_root: Path | None = None,
) -> WalkforwardBarsStats: ...
```
