# Quebra do briefing AG-427 / AG-428, após verificação contra o código

**Objeto:** `Mecanismo de threshold do modelo Alpha: matemática financeira e a
divergência AG-428` (2026-09-03).
**Modo:** adversarial. Consolida os 6 pontos de quebra levantados na leitura
inicial + 13 achados novos surgidos das respostas ao
`PROTOCOLO_INTERROGATORIO_AG428_threshold_e_custo.md` (45 perguntas, 5
investigações paralelas read-only, respostas com `arquivo:linha`).
**Regra que me obriga:** as interpretações foram registradas ANTES das
respostas, incluindo 7 testes de falsificação explícitos. Aplico-as sem
renegociar. Onde a resposta me derruba, está marcado ⚑.

---

# 0. Placar dos 6 pontos de quebra

| # | Quebra original | Pré-registro | Resposta | Veredito |
|---|---|---|---|---|
| **1** | Concorrência de posições estoura 3,0× | A2 hold <6h → retiro | A2: hold mediano ≈1 barra ≈33min. L cai de 5,06 para **0,12** | **MAGNITUDE DERRUBADA** ⚑ / estrutura sobrevive (A1, A3, A6) |
| **2** | `control_13` bloqueia o motor no dia 15 | B3 → enfraquece | B1: **`control_13` nunca roda**; não há motor vivo. `src/live/__init__.py` = stub de 2 linhas | **CAI COMO FORMULADO** — e vira algo pior (§N2) |
| **3** | Os 5 candidatos reprovaram 3 dias antes | — | I2: registrado no `SPRINT_LOG` ("continua 0/10"), **mas ausente do briefing** | **REBAIXADA** de governança para enquadramento |
| **4** | `TOTAL_COMMON_OOF` tem bug próprio | F1 → inferência recupera validade | F1/F2: "COMMON" = população de barras, não `tau` único. **Hipótese refutada** | **MECANISMO REFUTADO** ⚑ / conclusão sobrevive por F5 e por §N5 |
| **5** | `tau` in-sample, razão constante ≠ deriva | E1 exclui fit → retiro | E1: **não exclui**. Filtra só por tempo, nunca por índice de fit | **CONFIRMADA e reforçada** (§N5, §N3) |
| **6** | Assimetria long/short = deriva direcional | G2 → retiro se persistir em queda | G2: **não medido, não testável com artefato existente** | **ABERTA** — nem confirmada nem derrubada |

Dois dos meus seis pontos caíram na magnitude ou no mecanismo. Um sobreviveu e
ficou mais forte. Três achados novos são mais graves que os originais.

---

# PARTE I — Os pontos que caíram, sem atenuação

## ⚑ 1. A concorrência de posições não é o risco que eu disse que era

Usei hold de 1 dia por falta de dado. O real, combinando `n_bars_held`
(mediana=1, p75=3 barras — `constants.yaml:1637-1645`) com a duração real de
barra-dólar (`dollar_bar_duration_p99_by_resolution.json`, XRPUSDT/R3
p50=33,1min / p95=213min):

| Cenário | Hold | Posições concorrentes | × capital |
|---|---:|---:|---:|
| Mediana (1 barra × p50) | 0,6 h | **0,12** | 0,07× |
| p75 (3 barras × p50) | 1,7 h | 0,35 | 0,22× |
| p75 barras × p95 duração | 10,7 h | 2,24 | 1,40× |
| Cauda (5 barras × p95) | 17,8 h | 3,74 | 2,33× |

**Retiro o ataque #1 como risco imediato.** A 151,7 trades/mês com hold mediano
de 33 minutos, a carteira opera com muito menos de uma posição aberta em média.

O que sobrevive é estrutural e diferente: `control_11` recebe só um
`SizingResult` de uma ordem, sem parâmetro de portfólio
(`limits.py:288-294`); não existe `max_open_positions` (A3); e `compute_sizing`
não tem teto por trade — `floor_to_step` sem `min()`/`clip()`
(`sizing.py:184-186`). Combinado com **A5 não medido** (a distribuição de
`atr_at_t0` nunca foi percentilada), o risco de cauda de ATR baixo continua
aberto: `notional = risk_usd/(sl_atr_mult × atr_pct)` é inversamente
proporcional ao ATR, e ninguém sabe qual o p5.

## ⚑ 4. `TOTAL_COMMON_OOF` não tem o bug que eu supus

F1/F2: "COMMON" é a **população de barras** comum aos dois lados, não um `tau`
partilhado. Cada lado mantém `tau_long ≠ tau_short`; o que é comum é o **nível
do quantil `q`**, resolvido por bisseção para bater a taxa total
(`resolve_joint_tau`, `alpha.py:641-713`). Minha explicação para o overshoot de
2,3-3,0× está morta.

Retiro o mecanismo. A conclusão de que a §3.4 não sustenta "rejeitada"
sobrevive por outra via — F5: **uma seed (42), um candidato, sem dispersão**, e
o próprio script reconhece que o item "≥5 seeds" do roadmap não foi aplicado.
Isso sustenta "não decidido", não "rejeitado".

## ⚑ A minha hipótese de que o AG-427 causou o AG-428 está refutada

Eu sugeri que a janela de 180 dias, ao encolher o pool de calibração, teria
piorado a transferência do limiar. **H2 diz o contrário:** sob o regime
pré-janela (nominal 0,0189, ADR-005), a razão realizado/nominal era **~25,6%**.
Sob a janela de 180 dias (nominal 0,0284-0,15), é **62,6-72,8%**.

A janela **melhorou a razão em 2,5×**. O AG-427 foi um acerto. Retiro.

## ⚑ A acusação de dupla contagem cai

C1: `ret_net = ret_gross − cost_entry − cost_exit − funding_frac`
(`triple_barrier.py:1653-1663`) — já é líquido. Mas a resposta tem razão no
ponto: `edge_bps` ("quanto sobra por trade") e a projeção de R$ 58,85/mês
("quanto sai do bolso em fee") respondem perguntas diferentes, e não localizei
nenhuma segunda subtração compondo um P&L final inválido. **Retiro a acusação.**

C2 também me corrige: existe termo de funding, medido de eventos reais via
`lake.query_funding`. Minha objeção de "omite funding" era sobre a fórmula da
§1.5 do briefing, não sobre o código — e no código está lá.

## ⚑ A precisão do "0,27% da união" era falsa

Derivei a interseção long/short por inclusão-exclusão dos três valores da §3.2:
0,0499 + 0,0243 − 0,0740 = 0,0002. A aritmética é exata, mas os três vêm
arredondados a 4 casas. Propagando o erro, a interseção está em
**[0,00005 ; 0,00035]**, ou **0,07% a 0,47% da união**.

O achado qualitativo sobrevive — os dois lados quase nunca concordam que a
mesma barra é oportunidade. A precisão de "0,27%" era minha, e não se sustenta.

## ⚑ E o briefing não escondeu o 0/10

I2: `SPRINT_LOG.md:6788/6836` registra a autorização **no mesmo texto** que
declara "ainda 0/10... continua 0/10 combo×camada". A divulgação existe no
ledger. **Rebaixo a crítica**: o briefing de auditoria externa não menciona
isso em lugar nenhum, o que é um problema de enquadramento do documento, não de
governança do projeto.

---

# PARTE II — O que sobreviveu, e ficou mais forte

## §N1. Existe um controle de risco agregado, e ele é permanentemente inerte

Eu escrevi "não existe controle agregado". Errado — **existe**, e é pior:

`control_19_risco_agregado` (`limits.py:495-533`) está desenhado exatamente
para isso. **Nenhum caller de produção monta as séries de posição/correlação
que ele exige**, então ele retorna sempre `NOT_COMPUTABLE`. E
`NOT_COMPUTABLE` **nunca bloqueia** (`evaluate_all`, `limits.py:686-688`).

Isso é um risk engine que **falha aberto**. Um controle que não consegue
calcular é tratado como aprovação. Num motor de risco, o default de "não sei"
deve ser "não passa".

E o PRD do próprio projeto já sabe:

> *"O Risk Engine hoje avalia cada posição isoladamente contra 0,50%. **Isso é
> falha de segurança, não de medição.**"* — `PRD_V4_1.md:224`

O mesmo documento calcula que 5 posições a ρ=0,91 dão σ=2,408%, **4,82× o risco
isolado** (ρ real remedido 0,70-0,83, AG-144). O número existe. O controle
existe. O caminho entre os dois não existe.

## §N2. Não há motor de execução. A afirmação de abertura do briefing é falsa

O sumário executivo diz que a taxa foi elevada *"sob um teto de custo mensal
medido diretamente contra o código de produção de risco (não uma estimativa)"*.

**B1:** `control_13` só é chamado dentro do próprio módulo de risco e em
testes. **Nenhum script do AG-428 importa `control_13` nem `compute_sizing`.**
A fórmula foi *replicada manualmente uma vez*. **B2:** o acumulador
`fees_mtd_usd` **não existe implementado** — é parâmetro injetado, com docstring
admitindo que *"o ledger que soma `fills.fee` do mês é responsabilidade de outra
camada, não existe em `risk/`"* (`limits.py:333-335`). **I4/B1:**
`src/live/__init__.py` é um stub vazio de 2 linhas.

O teto não foi medido contra o código de produção. Foi replicado à mão, de uma
fórmula, para um motor que não pode executar. As duas metades da frase do
sumário executivo — "medido diretamente contra o código" e "não uma estimativa"
— são as duas falsas.

Meu ataque #2 cai e é substituído por este, que é mais forte: não é que o
controle bloqueie no dia 15; é que **nenhum controle roda, e o número
autorizado nunca tocou o código que o documento cita como fonte**.

## §N3. A razão realizado/nominal é movida pelo mecanismo, não pelo mercado

Este é o argumento central que sobrevive, e agora está sustentado pelos dados do
próprio repositório.

| Regime | Nominal | Razão realizado/nominal |
|---|---|---:|
| Pré-janela (ADR-005) | 0,0189 | **~25,6%** |
| Pós-janela 180d (`tau_sweep_stage_B`) | 0,0284-0,15 | **62,6-72,8%** |

Dentro do regime pós-janela a razão é **estável em ~67%** numa faixa de 3,75×
de nominal (regressão realizado ~ nominal: inclinação 0,646, intercepto
+0,0017, **R² = 0,9981**). Entre regimes, ela salta **2,5×**.

**O nível nominal não move a razão. A janela de calibração move 2,5×.**

Um mecanismo capaz de mover a quantidade por 2,5× é um lar muito mais plausível
para os 32-37% de gap residual do que "deriva temporal genuína". A §3.3 do
briefing atribui o residual a deriva depois de já ter observado que uma
mudança de mecanismo explicava o dobro do que resta.

## §N4. O pool de `tau` continua contaminado — e o mecanismo correto já existe no código

**E1:** `_select_tau_calibration_pool` (`alpha.py:1945-2006`) filtra **só por
tempo** (`t0 >= max(t0) − 180 dias`), nunca por índice de fit/calib/stop. E
`calibrated_train_all` é a predição sobre **todo** `X_all`, incluindo as linhas
de `X_fit` (`alpha.py:1735-1736`). Se a janela de 180 dias corridos alcança o
bloco de fit — o que depende da densidade de barras — o pool herda score
in-sample.

**E2:** `n_in_window` é calculado (`alpha.py:1990`) mas **só logado no ramo de
falha**. No caminho de sucesso é descartado. **Ninguém pode saber se a janela
alcança o fit**, porque o número não é persistido.

E o contraste é o achado: `TOTAL_COMMON_OOF` (`_resolve_tau_on_common_bars`)
**exclui explicitamente os `t0` vistos no fit**. O mecanismo mais rigoroso já
está escrito, testado, e não é o de produção.

## §N5. A política que exclui in-sample muda a taxa realizada em 2,8× — na direção que eu previa

Com F1/F2 refutando minha explicação do overshoot, o dado passa a dizer algo
mais interessante:

| Política | Exclui fit? | Taxa realizada | vs. nominal |
|---|---|---:|---:|
| `LEGACY_PER_SIDE` (produção) | **não** (E1) | 0,0838 | 0,84× |
| `TOTAL_COMMON_OOF` C1 | **sim** (E1) | 0,2322 | 2,32× |
| `TOTAL_COMMON_OOF` C0 | **sim** (E1) | 0,2999 | 3,00× |

Na mesma célula, remover a contaminação in-sample move a taxa realizada em
**2,77×**. Isso é evidência direta de que a contaminação do pool de produção é
**material**, com magnitude grande — exatamente a direção do meu ataque #5.

O overshoot é um **segundo defeito sobreposto**, não uma refutação do primeiro.
E ele agora tem candidato: **F3** revela que "OOF" inclui *"NOFILL de qualquer
lado"* (`alpha.py:2033-2038,2057-2066`). Barras NOFILL são barras onde a entrada
não preencheu — população com distribuição de score sistematicamente diferente.
Se o pool de calibração é enriquecido com elas, o quantil sai baixo demais e a
taxa estoura. **Hipótese não verificada**, e é a próxima pergunta.

## §N6. Triplicar a taxa nominal não resolveu a degeneração

**H3:** no run mais recente (`20260903T192150Z`, pós-Optuna sob 0,10),
**60 folds degenerados de 143 = 42,0%**. Na ADR-008 (nominal 0,0189), eram 44
de 106 entradas fold×lado abaixo de 5 trades = **41,5%**.

Elevar `target_signal_rate` em **5,29×** mudou a taxa de degeneração de 41,5%
para 42,0%. Praticamente nada.

Se a degeneração fosse consequência de um corte apertado demais, afrouxar o
corte 5× teria que resolvê-la. Não resolveu. Isso é evidência independente de
que o problema não está no nível do limiar, e sim no mecanismo que o resolve.

## §N7. O TP assume fill perfeito; o SL modela gap. Assimetria de otimismo, confirmada em código

**C4:** `exit_price = tp_price` literal, sem gap-through
(`triple_barrier.py:1046-1048`). O SL tem `_gap_aware_sl_fill` (linhas 981-1010)
porque é ordem a mercado; o TP é passiva e assume preenchimento exato sempre.

**As perdas modelam gap. Os ganhos não.** Em cripto, gap através do TP é comum.
Isso é um viés sistemático para cima em **todos** os `edge_bps` do projeto — não
só os deste briefing.

## §N8. Nenhum custo de spread existe em lugar nenhum

**C5:** zero ocorrências reais em `triple_barrier.py` e `sizing.py`. Existe só
como (a) guardrail pré-trade desligado por falta de feed ao vivo (Controle 17) e
(b) feature de regime desligada (`spread_pctile_expanding=None` hardcoded).
**Nunca é subtraído do retorno.** E **C1** confirma que
`adverse_selection_bps` (1,5bps, `ASSUMED`) é reportado e **não subtraído**.

Todo `edge_bps` do projeto é **bruto de spread e bruto de seleção adversa**.
Para o único sobrevivente da ADR-008 (`BTCUSDT/R2` C1, +7,90bps), esses dois
termos consomem uma fração material do edge.

## §N9. O walk-forward não quantiza posição — os `edge_bps` não são executáveis com R$ 1.000

**D3:** `floor_to_step` é usada em 3 arquivos, **nenhum de walk-forward ou
backtest**. `backtest_lite.py` reusa `ret_net` de `triple_barrier.py`, que
quantiza **preço** (tick) e nunca **quantidade** (`step_size`).

**D2:** o próprio `PRD_V4_1.md:202` documenta **erro de quantização de 16,2% em
BTC** sob capital de R$ 1.000 (0,3-1,4% nos demais). `minNotional` real: BTC 50
USDT, ETH 20, SOL/BNB/XRP 5.

Os `edge_bps` são retorno percentual teórico sobre nocional contínuo. Numa conta
real de R$ 1.000, o nocional de BTC erra 16,2% por quantização — e a §2.3 do
briefing tabula R$ 936,30 como se fosse executável.

## §N10. A janela de 180 dias foi escolhida com uma seed

**E4:** a fonte existe e é real (`scripts/sweep_tau_mechanism.py --stage A`,
artefato bate com `constants.yaml:895-932`). Retiro a acusação de `MEASURED` sem
base. Mas: **4 valores discretos** (None/90/180/270), **uma seed**, "vencedor
claro" lido de uma realização determinística. **E5:** nenhuma janela ≥365 dias
foi testada, e não houve segundo sweep depois de 180 ser fixado.

Uma constante classe A que move a razão realizado/nominal em 2,5× (§N3) foi
fixada num grid de 4 pontos com n=1.

## §N11. O edge por decil de confiança já foi medido, é não-monotônico, e está desatualizado

Esta era a lacuna que eu apontei como "o benefício nunca foi medido". **I1**
mostra que foi, uma vez (AG-407, `measure_q10_q1_pooled.py`, 2026-08-31):

| Célula | Q10−Q1 | Folds com sinal positivo |
|---|---:|---:|
| Camada1 short | **+45,55 bps** | 66,7% |
| Camada1 long | **−5,37 bps** | — |
| Camada0 short | **−9,80 bps** | 33,3% (maioria na direção **oposta**) |

**A relação confiança→edge não é monotônica.** Em duas das quatro células
medidas ela é negativa. E a medição é do regime **anterior** ao AG-427/428 —
nunca recomputada sob a janela de 180 dias nem sob `target_signal_rate=0,10`.

Retiro "nunca medido" e substituo por algo pior: **foi medido, deu não-monotônico,
e a decisão de afrouxar o corte 5,29× foi tomada mesmo assim, sem recomputar.**
Afrouxar um limiar adiciona os trades de menor confiança; a melhor evidência
disponível diz que o edge desses trades não é previsivelmente pior nem melhor —
é imprevisível. O briefing calcula o custo desses trades com precisão de
centavos e não recomputa o benefício.

## §N12. O AG-428 não é um achado novo — e a proveniência afirma que é

**E3:** o gap de 62,6-72,8% **já estava em `experiments/tau_sweep_stage_B.json`,
gerado pelo próprio commit `224a062` (AG-427)**, antes de qualquer commit do
AG-428 existir. A alegação registrada em `constants.yaml:801-804` —
*"ACHADO NOVO (não visto na rodada 1, sweep_range antigo não alcançava esta
faixa)"* — **está contradita pelos dados do próprio repositório**.

O fenômeno estava nos dados da rodada 1. Não foi comparado contra o nominal
porque o critério de leitura da rodada 1 era outro. Isso é um erro de
proveniência num campo `MEASURED` — a mesma classe de erro que o commit
`f9bea25` ("correção de proveniência stale") acabou de corrigir noutro campo.

## §N13. O gate corrigido existe e não substituiu o gate quebrado

**I3:** `compute_score_quality_full_population` foi criada em resposta ao AG-394
(achado da auditoria adversarial anterior), e sua própria docstring admite que
mede *"a pergunta que o gate Model da ADR-008 tentava responder e, por medir a
população errada, não respondia"* (`score_quality.py:393-407`).

**Ela é reportada como campo adicional. Não substitui o gate original.** O gate
que decide promoção continua sendo o que mede AUC na população pós-`tau`.

E o efeito colateral que eu previa está confirmado: elevar `target_signal_rate`
alarga a população selecionada em 3,5×, e **os AUCs do gate Model mudam por
razão mecânica**. Se alguém re-rodar os gates agora e vir melhora, ela não é
sinal.

---

# PARTE III — Veredito reformulado sobre as 3 afirmações do briefing

| Afirmação | Veredito |
|---|---|
| **(i) "Nenhum risco financeiro imediato"** | **Verdadeira por um motivo que o briefing não dá.** Não há risco imediato porque **não há motor de execução** (§N2), não porque os controles funcionem. Os controles não rodam (B1, B2), o agregado é permanentemente inerte (§N1), e o próprio PRD chama isso de *"falha de segurança, não de medição"*. A frase certa é "nenhum risco imediato porque nada opera", não "nenhum risco identificado". |
| **(ii) "Causa-raiz confirmada: deriva de generalização"** | **Não sustentada.** O ledger do projeto diz **ABERTA** (`architecture_gaps_log.yaml:28254-28256`); o briefing diz confirmada. Duas alavancas de mecanismo movem a quantidade mais do que o residual que sobra: a janela move **2,5×** (§N3) e excluir in-sample move **2,8×** (§N5). "Deriva temporal" é o que resta depois de duas alavancas maiores que o resto. E o gap não é achado novo (§N12). |
| **(iii) "Correção rejeitada por eliminação"** | **Não decidida.** Meu mecanismo de bug foi refutado (F1/F2), mas a rejeição repousa em **uma seed (42), um dos cinco candidatos, sem dispersão** (F5), e o overshoot tem candidato não testado (pool OOF enriquecido com NOFILL, §N5). Isso sustenta "não medido com poder suficiente", não "rejeitada". |

**O que os fatos sustentam:**

> O AG-428 mede um resíduo de calibração, não deriva de mercado. A janela de
> 180 dias (AG-427) melhorou a razão realizado/nominal de ~26% para ~67% — um
> acerto real — e excluir dados in-sample do pool move a mesma quantidade em
> 2,8×. Sobra um resíduo de ~33% que foi atribuído a deriva temporal sem que
> nenhuma das duas alavancas de mecanismo tenha sido esgotada, sem medição
> temporal (G2/G3 não medidos), e contra o registro do próprio ledger, que diz
> ABERTA. A elevação da taxa nominal de 0,0189 para 0,10 (**5,29× em um dia,
> em dois commits, com apenas a segunda perna apresentada para autorização** —
> H1) não alterou a taxa de degeneração (41,5% → 42,0%), foi decidida sem
> recomputar a relação confiança→edge que a última medição mostrou
> não-monotônica, e seu teto de custo foi validado por replicação manual de
> fórmula contra um motor que não existe.

---

# PARTE IV — Ações, ordenadas por razão informação/custo

| # | Ação | Custo | Decide |
|---:|---|---|---|
| 1 | **Persistir `n_in_window` no caminho de sucesso** (`alpha.py:1990`) e reportar a fração do pool de 180d que cai dentro do bloco `fit` | 1 linha | Sem isso, §N4 é insolúvel. É a métrica que diz se a produção está contaminada. |
| 2 | **Rodar `_resolve_tau_on_common_bars` sem o componente NOFILL** e medir a taxa realizada | 1 flag | Separa os dois defeitos sobrepostos de §N5. Se a taxa cair de 2,32× para ~1,0×, a causa do overshoot é o NOFILL e a política vira promovível. |
| 3 | **G1/G3: decompor `rate_long_alone`/`rate_short_alone` por trimestre × retorno do ativo** | script de agregação; dados já em disco | A resposta confirma que os parquets com `t0` e as séries de preço existem, e que há `stratified_by_time` pronto (`calibration_diagnostics.py:456-485`), nunca exercitado em dado real. Fecha o bloco G quase inteiro. |
| 4 | **Recomputar Q10-Q1 por decil sob o regime atual** (janela 180d, taxa 0,10) | reusar `measure_q10_q1_pooled.py` | §N11. A decisão de afrouxar 5,29× foi tomada com uma medição do regime anterior que deu não-monotônica. |
| 5 | **Trocar o default de `NOT_COMPUTABLE` para bloqueio**, ou cabear `control_19` | decisão + wiring | §N1. Risk engine que falha aberto. |
| 6 | **Percentilar `atr_at_t0`** (p5/p25/p50/p75/p95) por candidato | uma leitura de `labels.parquet` | A5. Sem o p5 ninguém sabe o nocional máximo de um único trade. |
| 7 | **Adicionar gap-through ao fill de TP**, espelhando `_gap_aware_sl_fill` | simétrico ao que já existe | §N7. Enquanto não houver, todo edge do projeto tem viés para cima. |
| 8 | **Aplicar `floor_to_step` no `backtest_lite`** | — | §N9. Com erro de quantização de 16,2% em BTC, os edges não são executáveis. |
| 9 | **Corrigir a proveniência de `constants.yaml:801-804`** ("ACHADO NOVO") | trivial | §N12. Contradita pelo `tau_sweep_stage_B.json` do próprio commit. |
| 10 | **Repetir o sweep de `tau_calibration_window_days` com ≥5 seeds e incluindo ≥365 dias** | ~1 campanha | §N10. Constante classe A que move a razão 2,5×, fixada com n=1 em 4 pontos. |
| 11 | **Substituir o gate Model por `compute_score_quality_full_population`**, não reportá-la ao lado | decisão | §N13. O gate que decide continua sendo o quebrado. |
| 12 | **Registrar a conversão anual (51,7%/ano) junto do mensal** nas autorizações | trivial | B5. Só a base mensal está no `SPRINT_LOG` e no ledger. |

**Sequência mínima:** 1 → 2 → 3. Nenhuma exige retreino. As três juntas
resolvem ou derrubam o AG-428 inteiro.

---

# PARTE V — Entradas sugeridas para o `architecture_gaps_log`

| Entrada | Conteúdo | Severidade |
|---|---|---|
| **AG-429** | `control_19_risco_agregado` sempre `NOT_COMPUTABLE`; `evaluate_all` trata `NOT_COMPUTABLE` como aprovação (`limits.py:686-688`). Risk engine falha aberto. `PRD_V4_1.md:224` já classifica como falha de segurança. | ALTA |
| **AG-430** | Pool de calibração de `tau` filtra só por tempo, nunca por índice de fit (`alpha.py:1945-2006` + `:1735-1736`). `n_in_window` não persistido no caminho de sucesso — contaminação não verificável. Mecanismo correto já existe em `_resolve_tau_on_common_bars` e não é o de produção. | ALTA |
| **AG-431** | Proveniência falsa em `constants.yaml:801-804`: "ACHADO NOVO (sweep_range antigo não alcançava esta faixa)" contradito por `experiments/tau_sweep_stage_B.json`, gerado pelo próprio commit `224a062`. | ALTA |
| **AG-432** | Fill de TP sem gap-through (`triple_barrier.py:1046-1048`) enquanto SL tem `_gap_aware_sl_fill`. Viés sistemático para cima em todo `edge_bps` do projeto. | ALTA |
| **AG-433** | Walk-forward/backtest não aplicam `floor_to_step` (D3). Com erro de quantização documentado de 16,2% em BTC sob R$ 1.000 (`PRD_V4_1.md:202`), os `edge_bps` não correspondem a execução real. | MÉDIA |
| **AG-434** | Nenhum custo de spread nem `adverse_selection_bps` subtraído do retorno (C1, C5). Todo edge do projeto é bruto desses dois termos. | MÉDIA |
| **AG-435** | `tau_calibration_window_days=180` fixado com 4 valores discretos e 1 seed (E4/E5), sendo a constante que move a razão realizado/nominal em 2,5× (§N3). Nenhuma janela ≥365d testada. | MÉDIA |
| **AG-436** | `target_signal_rate` foi de 0,0189 a 0,10 (5,29×) em dois commits no mesmo dia; só a segunda perna (3,52×) foi apresentada para autorização (H1). Teto de custo validado por replicação manual, sem chamar `control_13`/`compute_sizing` (B1). | MÉDIA |

---

# PARTE VI — Validação ponto a ponto

| # | Afirmação | Status | Fonte | O que a derrubaria |
|---:|---|---|---|---|
| 1 | Concorrência ≈0,12 posições no hold mediano | **DERIVADO** | A2 (`constants.yaml:1637-1645` + `dollar_bar_duration_*.json`) | `n_bars_held` é de ADR-006, regime anterior; barreiras não mudaram, mas não foi remedido |
| 2 | `control_11` é por ordem, sem estado de portfólio | **VERIFICADO** | `limits.py:288-294` | — |
| 3 | `control_19` sempre `NOT_COMPUTABLE`; isso nunca bloqueia | **VERIFICADO** | `limits.py:495-533`, `:686-688` | — |
| 4 | Não há motor de execução vivo | **VERIFICADO** | B1, I4 (`src/live/__init__.py` stub de 2 linhas) | — |
| 5 | Teto de custo replicado à mão, sem chamar o código citado | **VERIFICADO** | B1 (nenhum script AG-428 importa `control_13`/`compute_sizing`) | — |
| 6 | `fees_mtd_usd` não implementado | **VERIFICADO** | `limits.py:317`, docstring `:333-335` | — |
| 7 | Razão salta de ~25,6% para 62,6-72,8% com a janela | **CITADO** | H2 (ADR-005 xfail + `tau_sweep_stage_B.json`) | as duas medições têm nominais diferentes; a atribuição à janela assume que o nominal não move a razão — o que o R²=0,9981 dentro do stage_B sustenta, mas não prova entre regimes |
| 8 | Razão constante ~67%, R²=0,9981 | **DERIVADO** | regressão sobre a tabela §3.1 do briefing | 4 pontos apenas |
| 9 | `_select_tau_calibration_pool` filtra só por tempo | **VERIFICADO** | E1 (`alpha.py:1945-2006`, `:1735-1736`) | — |
| 10 | `n_in_window` descartado no sucesso | **VERIFICADO** | E2 (`alpha.py:1990`) | — |
| 11 | Excluir in-sample move a taxa 2,77× na mesma célula | **ARITMÉTICO** | 0,2322/0,0838, tabela §3.4 do briefing | 1 seed, 1 candidato — a magnitude tem barra de erro desconhecida |
| 12 | NOFILL no pool OOF como causa do overshoot | **HIPÓTESE NÃO VERIFICADA** | F3 (`alpha.py:2033-2038,2057-2066`) | é a próxima pergunta, não um achado |
| 13 | Degeneração 41,5% → 42,0% após 5,29× de taxa | **CITADO** | H3 (60/143, run `20260903T192150Z`) vs. ADR-008 J2 (44/106) | **as duas métricas não são a mesma unidade** — 60/143 é por fold, 44/106 é por fold×lado. A comparação é indicativa, não pareada. Marco como fraca |
| 14 | TP sem gap-through, SL com | **VERIFICADO** | C4 (`triple_barrier.py:1046-1048` vs `:981-1010`) | — |
| 15 | Nenhum spread; `adverse_selection` não subtraído | **VERIFICADO** | C5, C1 (`triple_barrier.py:46-53`) | — |
| 16 | Walk-forward não quantiza quantidade | **VERIFICADO** | D3 | — |
| 17 | Erro de quantização de 16,2% em BTC | **CITADO** | `PRD_V4_1.md:202` | é documento do projeto, não remedido por mim |
| 18 | Q10-Q1 não-monotônico, regime anterior | **CITADO** | I1 (AG-407, `measure_q10_q1_pooled.py`) | — |
| 19 | Gap já presente no `tau_sweep_stage_B` do commit `224a062` | **VERIFICADO** | E3 | — |
| 20 | Janela escolhida com 4 pontos e 1 seed | **VERIFICADO** | E4/E5 | — |
| 21 | `compute_score_quality_full_population` não substitui o gate | **VERIFICADO** | I3 (`score_quality.py:393-407`) | — |
| 22 | 0,0189 → 0,10 em dois commits no mesmo dia | **VERIFICADO** | H1 (`224a062` 09:14, `947213b` 14:01) | — |
| 23 | `fee_budget_monthly` = *"sem base; inventado"* | **VERIFICADO (literal)** | H5 (`constants.yaml:235-242`) | — |
| 24 | Interseção long/short ≈0 | **DERIVADO, precisão corrigida** | inclusão-exclusão sobre §3.2 | faixa real [0,07%; 0,47%] da união, não "0,27%" |
| 25 | Concorrência de 5,06 posições | **REFUTADO POR MIM** | A2 | retirado |
| 26 | `control_13` bloqueia no dia 15 | **REFUTADO POR MIM** | B1 | retirado — o controle não roda |
| 27 | "COMMON" = `tau` único partilhado | **REFUTADO** | F1/F2 (`alpha.py:641-713`) | retirado |
| 28 | AG-427 causou o AG-428 | **REFUTADO** | H2 (a janela melhorou 2,5×) | retirado |
| 29 | Dupla contagem edge × projeção de custo | **REFUTADO** | C1 | retirado |
| 30 | Briefing omite funding | **PARCIAL** | C2 (código tem; a fórmula da §1.5 do briefing não) | crítica ao documento, não ao código |
| 31 | O briefing esconde o 0/10 | **REBAIXADO** | I2 (`SPRINT_LOG.md:6788/6836` registra) | crítica de enquadramento do briefing, não de governança |

### Autocrítica: onde esta quebra é mais frágil

1. **O item 13 é o mais fraco do documento.** Comparo 60/143 (folds) contra
   44/106 (fold×lado) — unidades diferentes. A conclusão "afrouxar não resolveu
   a degeneração" é plausível mas não está pareada. Precisa da contagem
   fold×lado do run novo para valer.
2. **O item 7 assume que o nominal não move a razão entre regimes.** Sustento
   isso com R²=0,9981 *dentro* do stage_B, mas os dois pontos comparados
   (0,0189 pré-janela vs. 0,0284-0,15 pós) diferem em duas variáveis. A
   atribuição à janela é a leitura mais provável, não a única.
3. **§N5 (excluir in-sample move 2,77×) vem de uma seed e um candidato.**
   A direção é forte; a magnitude não tem barra de erro. Mesmo defeito que eu
   critico em F5.
4. **A hipótese do NOFILL (item 12) é especulação estruturada.** Está marcada
   como tal e é a próxima medição, não um achado.
5. **Cinco dos meus pontos foram retirados.** Dois por magnitude (concorrência,
   `control_13`), dois por mecanismo (`COMMON`, AG-427 como causa), um por
   aritmética (dupla contagem). O núcleo que sobrevive — §N3 e §N4/§N5 — é
   menor que a crítica original, e é o único que eu defenderia numa reunião.

---

*Fim. Cinco dos meus seis ataques originais foram retirados ou rebaixados. O que
sobrou não é que o briefing esteja errado nos números — os números conferem. É
que ele declara confirmada uma causa que o próprio ledger do projeto registra
como ABERTA, depois de duas alavancas de mecanismo que movem a quantidade mais
do que o resíduo que ele atribui à deriva.*
