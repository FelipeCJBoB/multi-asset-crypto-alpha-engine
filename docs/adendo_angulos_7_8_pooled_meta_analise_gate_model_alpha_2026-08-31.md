# Adendo — Ângulos 7 e 8: meta-análise pooled dos gates Model e Alpha
## (tentativa independente de refutar "0/20, nenhum candidato sobrevive")

**Data:** 2026-08-31
**Autor:** sessão de auditoria ML/Algo-Trading (Claude), a pedido do Manager —
"refutar um ângulo diferente do achado '0/20', não apenas confirmar".
**Escopo:** continuação direta da Seção 15 ("Adendo — Auditoria adversarial
do RESULTADO") de
`docs/AUDITORIA_EXTERNA_run_canonico_e_adr008_fases_0-8_2026-08-31.md` — os
6 ângulos daquela seção (vazamento temporal, viés de sobrevivência, inversão
de AUC, divergência CPCV-vs-WF, integridade de dado, recomputo
independente) já estavam testados; este documento cobre **2 ângulos
adicionais, genuinamente novos**, que aquela rodada não tinha coberto.
**Fontes primárias:** `experiments/alpha_walk_forward_{symbol}_{resolution_id}.json`
(5 arquivos, mesmos artefatos da Fase 4/ADR-008) · `src/models/score_quality.py` ·
`src/analysis/stability_matrix.py` · `src/analysis/walk_forward_gates.py` ·
`src/models/backtest_lite.py`.
**Método de execução:** só leitura dos artefatos JSON reais já materializados
em disco, via PowerShell (`ConvertFrom-Json` + aritmética) — nenhum código de
pipeline foi executado, nenhum retreino, nenhum trial novo gasto de
`n_lifetime`. Scripts completos em
`C:\Users\FELIPE~1\AppData\Local\Temp\claude\C--Robo-MT5-Forex-Cryptex-Binance-Futures\935703ce-0fc6-40e0-b511-b2984b6c2462\scratchpad\pooled_meta_analysis.ps1`
e `...\pooled_alpha_meta_analysis.ps1` (fora do repo, diretório de
scratchpad da sessão — não versionados; reproduzíveis a partir das fórmulas
documentadas abaixo).

---

## 0. Por que estes 2 ângulos são genuinamente diferentes dos 6 já testados

Os 6 ângulos da Seção 15 auditaram: vazamento, viés de exclusão de fold
degenerado, inversão de rótulo, causa da divergência CPCV-vs-WF, qualidade
de dado na janela de teste, e recomputo independente **do mesmo desenho de
teste já publicado**. Nenhum deles questionou o **desenho estatístico dos
próprios gates** — se o teste-t entre-fold do gate Model, e a ausência total
de teste no gate Alpha, têm poder estatístico suficiente para detectar sinal
real, caso ele exista. Essa é a pergunta que os Ângulos 7 e 8 respondem.

---

## 1. Ângulo 7 — o gate Model é anticonservador por *underpowering*?

### 1.1 A hipótese testada

O gate Model (`walk_forward_gates.py::model_gate_p_value`) testa
`H0: AUC_médio≤0,5` via teste-t de uma amostra sobre a **média das AUCs por
fold**, com `n=n_folds` (1 a 8) como grau de liberdade — cada fold pesa
igual, um fold com 2 trades pesa como um fold com 264. Hipótese cética
razoável: talvez "0/20" reflita só a falta de poder estatístico desse
desenho específico (poucos graus de liberdade), não ausência real de sinal.

### 1.2 Método

Meta-análise de efeito fixo, ponderada por variância inversa:

```
peso w_i = 1 / SE_i²
SE_i²    = (n_i + 1) / (3 · n_i²)     [Hanley-McNeil, aproximação classes balanceadas —
                                        MESMA fórmula que a Seção 10 do documento-fonte já usa
                                        para justificar o piso do gate Data, DERIVED]
AUC_pooled = Σ(w_i · AUC_i) / Σw_i
SE_pooled  = 1 / √(Σw_i)
z          = (AUC_pooled − 0,5) / SE_pooled
p (unicaudal) = P(Z > z), Z~N(0,1), aproximação Zelen & Severo (1964)
```

Filtro de fold: `degenerado=False` (mesmo critério de
`stability_matrix.build_stability_matrix`, linha 192-193) — a mesma
população de dados que já sustenta as tabelas oficiais da Seção 9.1 do
documento-fonte.

### 1.3 Validação de correção (pré-requisito antes de confiar no resultado)

Recomputação dos 20 fold-lado direto dos 5 artefatos reais reproduz
**exatamente** os 20 valores publicados na Seção 9.1 do documento-fonte
(AUC médio, desvio-padrão entre-fold, e "OOS folds" usados) — sem nenhuma
divergência, célula a célula. Confirma que o teste pooled abaixo roda sobre
a mesma população de dados do gate oficial, não uma reamostragem diferente.

### 1.4 Resultado — célula a célula (18 linhas com fold computável)

| Melhor caso entre as 18 | k folds | n pooled | AUC pooled | z | p (unicaudal) |
|---|---:|---:|---:|---:|---:|
| `BTCUSDT/R2` C0 short | 4 | 114 | 0,566 | 1,194 | 0,116 |
| `SOLUSDT/R3` C1 short | 3 | 70 | 0,543 | 0,611 | 0,270 |
| `XRPUSDT/R2` C1 long | 3 | 115 | 0,540 | 0,741 | 0,229 |

**0 de 18 células cruza p<0,05**, mesmo com muito mais poder estatístico
(SE efetivo caindo de ~0,13-0,27 entre-fold para ~0,04-0,09 pooled). O
melhor caso entre as 18 fica em p=0,116 — não passa nem a α=0,10.

### 1.5 Resultado — nível de PORTFÓLIO (os 5 candidatos agregados)

Pergunta institucional real: a família de modelos tem qualquer poder
discriminativo detectável, dado todo o capital de risco combinado?

| | k folds | n pooled | AUC pooled | z | p (unicaudal) |
|---|---:|---:|---:|---:|---:|
| **Camada1 (36 features, produção)**, ambos os lados | 29 | 948 | **0,5025** | 0,131 | 0,448 |
| Camada0 (baseline monotônico), ambos os lados | 26 | 732 | **0,4951** | -0,225 | 0,589 |

Com quase 1.000 trades pooled, o erro-padrão fica em ~0,019 — poder
suficiente para detectar com razoável confiança qualquer AUC verdadeiro
≥~0,54-0,55 (a ordem de grandeza necessária para sustentar edge líquido
depois de custo, dado o histórico de `cost_stop_ratio_max` e afins). O que
se observa é **0,5025** — indistinguível de moeda honesta.

### 1.6 Veredito do Ângulo 7

**Não refuta "0/20" — fecha uma saída de escape que nenhum dos 6 ângulos
anteriores tinha testado diretamente, e o faz na direção contrária à
esperada por quem levanta essa dúvida.** A crítica metodológica ("o teste
tem poucos graus de liberdade, pode estar mascarando sinal real") é válida
em princípio, mas testada contra o dado real dos 5 candidatos não se
sustenta: mesmo dando ao modelo uma ordem de grandeza a mais de poder
estatístico, o resultado agregado fica centrado quase exatamente em 0,50.

**Ressalvas:**
- Aproximação classes-balanceadas na fórmula de SE (mesma simplificação já
  usada na Seção 10 do documento-fonte) — sem `n_pos`/`n_neg` exato por
  fold, não é a fórmula completa de Hanley-McNeil.
- Pooling entre combos assume independência aproximada dos 5 candidatos —
  razoável (ativos diferentes) mas não perfeita (beta comum de mercado
  cripto entre BTC/SOL/XRP).
- Aproximação normal em vez de t-Student exata para os graus de liberdade
  pequenos de cada fold individual (afeta o passo 1, não o pooled final,
  que já tem `n` grande o bastante para a aproximação normal ser adequada).

---

## 2. Ângulo 8 — o gate Alpha não tem teste de significância nenhum: aplicando um, "0/20" sobrevive?

### 2.1 A lacuna real encontrada

`walk_forward_gates.py::alpha_gate_passes` decide só por
`edge_bps_mean > 0` — um limiar bruto, sem `t`, sem `p`, sem erro-padrão.
Isso é uma lacuna estrutural genuína (diferente do gate Model, que ao menos
tenta um teste-t): a maioria dos edges "negativos" na Fase 4 (Seção 5.4 do
documento-fonte) pode ser, na prática, estatisticamente indistinguível de
zero — e o pooling poderia revelar um portfólio com edge economicamente
significativo que a Fase 4 nunca testou.

### 2.2 Método — identidade algébrica exata, sem precisar dos trades brutos

`sharpe_naive = (mean/std) · √(trades_por_ano)` já está gravado por fold no
artefato (`backtest_lite.py:47`, `sharpe_naive` = mean(ret_net)/std(ret_net)
× √(trades/ano), anualizado pela frequência REAL observada, não um fator
fixo). Por identidade algébrica (não aproximação, já que
`trades_por_ano = N/span_years` por definição no próprio módulo):

```
t_stat_fold       = sharpe_naive_fold · √(span_years_fold)
SE(edge_bps)_fold = edge_bps_fold / t_stat_fold
```

`span_years_fold` aproximado por `(test_end − test_start)` do fold (campo
já presente no artefato) — aproximação, não o span exato dos `t0` dos
trades realizados (que não está gravado neste artefato), sinalizado como
limitação abaixo. Pooling por variância inversa idêntico ao Ângulo 7,
agora sobre `edge_bps` em vez de AUC.

### 2.3 Resultado — nível de PORTFÓLIO (produção real = Camada1)

| Camada | k folds | n pooled | edge pooled (bps) | z | p (H1: edge>0) |
|---|---:|---:|---:|---:|---:|
| **Camada1 (produção)** | 23 | 952 | **-3,32bps** | -1,805 | 0,964 |
| Camada0 (baseline) | 21 | 740 | -0,84bps | -0,377 | 0,647 |

Nenhuma evidência de edge positivo pooled. Pelo contrário: o `z` negativo
em Camada1 (a camada que roda em produção) sugere, se algo, inclinação para
edge **negativo** (p bilateral ≈0,07 — não conclusivo, mas na direção
oposta à hipótese que este ângulo tentava sustentar).

### 2.4 Resultado — célula a célula (10 combo×camada), com diagnóstico de concentração de peso

| Combo | Camada | k folds | n pooled | edge pooled (bps) | z | p (unicaudal) | Peso máx. de 1 fold |
|---|---|---:|---:|---:|---:|---:|---:|
| `BTCUSDT/R2` | C0 | 7 | 196 | +1,18 | 0,494 | 0,311 | 40% |
| `BTCUSDT/R2` | C1 | 8 | 403 | -0,19 | -0,097 | 0,538 | 36% |
| `SOLUSDT/R2` | C0 | 1 | 37 | -57,66 | -2,046 | 0,980 | 100% |
| `SOLUSDT/R2` | C1 | 1 | 37 | -57,66 | -2,046 | 0,980 | 100% |
| `SOLUSDT/R3` | C0 | 3 | 90 | -42,33 | -3,633 | 0,9999 | 63% |
| `SOLUSDT/R3` | C1 | 4 | 128 | -9,53 | -0,701 | 0,758 | 50% |
| `XRPUSDT/R2` | C0 | 4 | 317 | -12,35 | -1,350 | 0,912 | 50% |
| `XRPUSDT/R2` | C1 | 6 | 215 | -1,07 | -0,154 | 0,561 | 43% |
| `XRPUSDT/R3` | C0 | 6 | 100 | **+26,73** | **2,053** | **0,020** | 36% |
| `XRPUSDT/R3` | C1 | 4 | 169 | **-61,31** | **-6,945** | **≈1,000** | 44% |

`SOLUSDT/R2` tem peso 100% num único fold (k=1) — resultado sem
robustez nenhuma, mesmo achado já registrado no documento-fonte (Seção 5.4:
"só 1 de 12 folds usável nas DUAS camadas").

### 2.5 O achado que exige nota — `XRPUSDT/R3`

Única célula que cruza p<0,05 sem correção: `XRPUSDT/R3` **Camada0**
(baseline monotônico, não a camada de produção), pooled edge=+26,73bps,
p=0,02 — peso bem distribuído entre 6 folds (0,064 a 0,362, nenhum fold
isolado dominando por acaso; descartei a hipótese de "fold com variância
anormalmente baixa por sorte" checando a concentração de peso).

Duas razões para não tratar isso como refutação:

1. **Múltiplas comparações.** Sob 10 células testadas, ~0,5 achado a
   p<0,05 é o esperado só por acaso (mesma lógica FDR já usada no resto do
   documento-fonte, Seção 12/`AG-391`). Não sobrevive a nenhuma correção
   (Bonferroni: 0,05/10=0,005; BH/BY teriam o mesmo efeito com só 1 célula
   "positiva" entre 10).
2. **A mesma combinação, na camada que de fato importa economicamente
   (Camada1, produção), dá z=-6,945 (p≈1,0) — o resultado mais negativo e
   mais estatisticamente sólido de toda a campanha** (peso razoavelmente
   distribuído entre 2 folds relativamente grandes — n=101 e n=13, não um
   outlier isolado dominando). O modelo completo (36 features) fica PIOR
   que o baseline monotônico restrito no MESMO combo sob o MESMO mecanismo
   de teste — assinatura de *overfitting* relativo do C1 sobre o C0 nesse
   combo especificamente, não de edge escondido que o gate Alpha estaria
   perdendo.

### 2.6 Veredito do Ângulo 8

**Também não refuta "0/20" — reforça por um caminho independente do Ângulo
7 (poder estatístico via AUC), agora testando diretamente o P&L.** A única
célula "significativa" aponta na camada errada (baseline, não produção) e
não sobrevive a correção de múltiplas comparações; a camada que realmente
importa mostra, para o mesmo combo, o resultado mais negativo de toda a
campanha.

**Ressalvas:**
- `span_years` aproximado pelo intervalo `test_end−test_start` do fold, não
  pelo span exato dos `t0` dos trades realizados (não gravado no artefato)
  — pode subestimar levemente `trades_por_ano` se os trades se
  concentrarem numa fração do trimestre, o que infla `SE` e torna o teste
  mais CONSERVADOR (nunca menos), então não enfraquece a direção do
  veredito.
- Mesmas ressalvas de independência entre folds/combos do Ângulo 7.
- Teste de efeito fixo (não aleatório) — assume 1 média verdadeira por
  célula; sob heterogeneidade real de regime (plausível, ver `AG-392` item
  1 no documento-fonte), um modelo de efeitos aleatórios teria erro-padrão
  pooled maior (mais conservador ainda) — não testado aqui.

---

## 3. Síntese consolidada — 8 ângulos testados, "0/20" nunca refutado

| # | Ângulo | Tipo de teste | Refuta "0/20"? |
|---|---|---|---|
| 1 | Vazamento temporal (purge) | Auditoria de código/reprodução | Não — sustenta |
| 2 | Viés de sobrevivência (exclusão fold degenerado) | Reagregação sob convenção alternativa | Não — sustenta (exclusão é conservadora) |
| 3 | AUC≈0,50 (inversão de sinal) | Auditoria de código | Não — sustenta, acha achado colateral (AUC=0,500 exato = sinal indetectável, não "sem sinal") |
| 4 | Divergência CPCV vs walk-forward | Investigação de causa raiz | Não — sustenta, corrige explicação publicada (Seção 5.5) |
| 5 | Integridade de dado 2023-2026 | Auditoria de artefato | Não — sustenta na janela pedida, acha bug real fora dela (`AG-393`) |
| 6 | Recomputo independente do "0/20" | Reimplementação do zero | Não — sustenta, célula por célula |
| **7** | **Poder estatístico do gate Model (pooled AUC)** | **Meta-análise de variância inversa** | **Não — sustenta; AUC pooled portfólio = 0,5025, indistinguível de 0,50** |
| **8** | **Ausência de teste no gate Alpha (pooled edge_bps)** | **Meta-análise de variância inversa via identidade algébrica no `sharpe_naive`** | **Não — sustenta; edge pooled portfólio Camada1 = -3,32bps, tendendo negativo** |

**Nenhum dos 8 ângulos, testado com rigor real contra os artefatos reais,
reverteu ou enfraqueceu "0/20, nenhum dos 5 candidatos sobrevive"** — os
Ângulos 7 e 8 são particularmente informativos porque atacam o desenho do
TESTE em si (poder estatístico, ausência de significância), não a
implementação ou o dado, e mesmo assim convergem para a mesma conclusão por
um caminho estatístico independente.

---

## 4. Backlog — ângulos ainda não testados (propostos, não executados)

Registrados aqui para continuidade, caso o Manager peça para seguir:

1. **Q10-Q1 (spread de decil) pooled em portfólio** — métrica de rank
   não-linear; AUC/edge médio são lineares e podem não captar sinal
   concentrado só nos extremos de confiança.
2. **Bootstrap em bloco** (não paramétrico), respeitando a autocorrelação
   já medida em `AG-392` item 1 (lag-1 negativo, -0,216 média), em vez da
   aproximação normal usada nos Ângulos 7/8.
3. **Condicionamento por regime** — `E05f_time_to_funding_h`/
   `E16f_global_ls_ratio` (features dominantes por SHAP, Seção 8.2 do
   documento-fonte) como eixo de estratificação; sinal pode existir só num
   subconjunto de regime, mascarado na média incondicional.

---

## 5. Proveniência

| Item | Proveniência |
|---|---|
| Fórmula SE(AUC\|H0) (Hanley-McNeil, classes balanceadas) | `DERIVED` — mesma já usada em `docs/AUDITORIA_EXTERNA_..._2026-08-31.md` Seção 10 |
| Identidade `t_stat = sharpe_naive · √(span_years)` | `DERIVED` — álgebra exata a partir de `backtest_lite.py::sharpe_naive`, verificada nesta sessão |
| Todos os valores de AUC/edge/n por fold | `MEASURED` — lidos direto de `experiments/alpha_walk_forward_*.json`, validados contra Seção 9.1 do documento-fonte |
| Aproximação normal para p-valor (Zelen & Severo 1964) | `LITERATURE` |

*Fim do documento.*
