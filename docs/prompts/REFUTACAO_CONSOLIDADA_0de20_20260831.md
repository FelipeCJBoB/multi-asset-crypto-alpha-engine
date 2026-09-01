# Refutação adversarial consolidada do achado "0/20, nenhum sobrevive"

**Objeto:** `docs/AUDITORIA_EXTERNA_run_canonico_e_adr008_fases_0-8_2026-08-31.md`
(ADR-007 Run Canônico + ADR-008 Fases 0-8).
**Papel:** auditoria adversarial prevista na Seção 13 do documento auditado —
tentar REFUTAR a conclusão, não revisá-la. A Seção 12 já revisou implementação;
este documento ataca **inferência e desenho de instrumento**.
**Consolida:** `ADENDO_ADVERSARIAL_refutacao_0de20_20260831.md` (R1-R10, escrito
antes de qualquer acesso ao código) + `PROTOCOLO_INTERROGATORIO_codigo_refutacao_0de20.md`
(~50 perguntas com interpretação pré-registrada, respondidas com citação
`arquivo:linha`) + `VEREDITO_refutacao_apos_verificacao_codigo.md` + varredura
final (achados N1-N5, nunca publicados antes).
**Proveniência:** `DERIVED` (aritmética e simulação sobre `MEASURED` do projeto)
+ `LITERATURE` (Hanley-McNeil 1982 para SE(AUC), já adotado pela ADR-008).
**Regra que me obriga:** as interpretações foram registradas ANTES das respostas.
Aplico-as sem renegociar. Onde a resposta me derruba, está marcado ⚑ e a derrota
fica registrada com o mesmo destaque das vitórias.

---

# 0. Tese, em uma frase

**"0 de 20" não mediu ausência de alpha. Mediu um instrumento que não pode
aprovar nada.** O gate Model exige um AUC **populacional** entre 0,82 e o
matematicamente inatingível, dependendo da linha. O gate Data mede frequência
de trade, não generalização. O gate Alpha — o único conceitualmente válido — é
um ponto estimado comparado a zero, sem erro-padrão, cujo único veredito
"passa" tem **t = 0,35 e mediana negativa**. E a degeneração que esvaziou 11 a
19 folds por combo tem uma causa mecânica identificável em `alpha.py:1683-1685`
que não tem relação com alpha.

A direção do achado da ADR-008 provavelmente está certa — e duas respostas do
interrogatório (E1, H3) sugerem que a realidade é **pior** que o reportado. Mas
nenhuma das evidências apresentadas sustenta a conclusão, e a que mais parece
sustentá-la é uma tautologia aritmética.

---

# PARTE I — Refutação a priori (escrita antes de ver o código)

## R1. O gate Model é inatingível em 9 de 20 linhas

A Seção 10 mede e registra `SE(AUC|H0=0,5)` **por fold** entre 0,13 e 0,19, e
usa esse número corretamente para aposentar o limiar fixo de 0,52. O mesmo
número, aplicado ao teste-t que o substituiu, com o `n` real da coluna "OOS
folds" corrigida da Seção 9.1 (σ=0,16, ponto médio da faixa medida):

| `n` folds | Linhas | AUC mínimo exigido |
|---:|---:|---|
| 0 | 2 | indefinido — teste não existe |
| 1 | 2 | indefinido — teste não existe |
| 2 | 5 | **1,214** — impossível |
| 3 | 6 | 0,770 |
| 4 | 3 | 0,688 |
| 5 | 1 | 0,653 |
| 8 | 1 | 0,607 |

**9 de 20 linhas (45%) têm gate Model matematicamente impassável**, qualquer
que seja a qualidade do modelo. A barra mais baixa do painel inteiro é 0,607.
Alpha direcional real em perpétuos de cripto vive em 0,52-0,55.

## R2. Poder de 7% a 12% — "0/20" é o resultado esperado mesmo com alpha real

| `n` | AUC verd. 0,52 | 0,53 | 0,55 | 0,60 |
|---:|---:|---:|---:|---:|
| 2 | 6,2% | 6,8% | 8,2% | 12,3% |
| 3 | 6,8% | 7,9% | 10,5% | 18,8% |
| 4 | 7,4% | 8,9% | 12,6% | 25,4% |
| 8 | 9,3% | 12,2% | 19,9% | 48,0% |

Aplicando o `n` real de cada linha:

| Se TODAS as 20 tivessem AUC verdadeiro… | Esperado | P(observar 0/20 assim mesmo) |
|---|---:|---:|
| 0,50 (H0 pura) | 0,80 | 44,0% |
| 0,53 | 1,31 | **25,6%** |
| 0,55 | 1,76 | **15,4%** |
| 0,60 | 3,30 | 2,2% |

Razão de verossimilhança entre "nenhum alpha" e "alpha de AUC 0,53": **1,7**.
Um fator de Bayes de 1,7 não move crença racional. O documento trata isso como
conclusivo.

## R3. O sweep de sensibilidade varreu o eixo errado

A Seção 11.1 varreu `significance_level` ∈ {0,01…0,10} e leu a invariância como
robustez. Com poder de 8%, α é a dimensão de **menor** alavancagem: mesmo em
α=0,10 o MDE em n=3 cai de 0,770 para 0,687 — ainda inatingível. A dimensão que
determina o resultado é `n`, que não foi varrido porque é constante de desenho.
Invariância sob α é a assinatura de um instrumento sem poder, não de achado
robusto. O sweep, corretamente lido, é evidência **a favor** desta refutação.

*(H4 confirmou depois: o passo trimestral é hardcoded em
`volatility_walkforward.py:86`, vindo de `PRD_V4_1.md:370`, sem alternativa
jamais cogitada em `docs/`, `audit/` ou `git log`.)*

## R4. O gate Data mede frequência de trade, não generalização

Cruzando `trades/dia` da Seção 2.2 com trimestre civil de 91,25 dias e o piso de
10 trades/fold:

| Combo | trd/dia | trd/trimestre | P(fold usável) | Folds usáveis esperados |
|---|---:|---:|---:|---|
| `BTCUSDT/R2` | 0,32 | 29,2 | ~1,00 | 19,0 de 19 |
| `XRPUSDT/R2` | 0,25 | 22,8 | 0,999 | 12,0 de 12 |
| `XRPUSDT/R3` | 0,11 | 10,0 | 0,547 | 6,6 de 12 |
| `SOLUSDT/R2` | 0,10 | 9,1 | 0,429 | 5,1 de 12 |
| `SOLUSDT/R3` | 0,06 | 5,5 | **0,052** | **0,6 de 12** |

`SOLUSDT/R3` foi reprovado por um gate que sua própria taxa de trade torna
inatingível: o desenho prevê ~0,6 folds usáveis, o gate exige 10. **O gate pune
seletividade** — dois modelos com edge idêntico, um a 0,06 e outro a 0,32
trd/dia, recebem vereditos opostos.

A correção da Seção 10 (fração → piso absoluto) resolveu uma injustiça entre
combos de 12 e 19 folds e **introduziu** uma dependência direta na frequência de
trade que a forma em fração não tinha. "O achado ficou mais forte" descreve o
resultado; não valida a mudança.

## R5. O teste pooled — disponível, nunca executado

A Seção 10 declara "62 fold-lado medidos" e os usa só para calibrar limiares.
Efeito fixo sobre as 13 linhas com AUC não-degenerado (47 folds), ponderado por `n`:

| | |
|---|---:|
| AUC pooled | **0,5128** |
| SE (0,16/√47) | 0,0233 |
| z / p (unicaudal) | 0,547 / 0,292 |
| **IC 95%** | **[0,467 ; 0,559]** |

O IC **não exclui 0,53 nem 0,55**. O ponto estimado é positivo. Distribuição:
7 de 13 acima de 0,50, 6 abaixo — simétrico. A frase defensável é *"o AUC
agregado é 0,513 (IC95% 0,467-0,559); o desenho não distingue isso de 0,50 nem
de 0,55"*, não *"nenhum candidato demonstra edge robusto"*.

## R6. Assimetria de rigor: o instrumento novo nunca foi calibrado

O ADR-007 Item 3 mediu o **falso-positivo** do gate duplo sob ruído puro
(8,0%/0,0%/0,0%) e concluiu corretamente que "ZERO combos reflete ausência real
de sinal, não instrumento quebrado". O ADR-008 nunca fez o teste espelho —
nenhuma medição de **falso-negativo**, nenhuma injeção de sinal sintético. A
conclusão do Item 3 foi importada implicitamente sem que sua pré-condição fosse
reestabelecida para o novo mecanismo.

*(K1 confirmou depois, e piorou: existe `src/analysis/eixo1_power_diagnostic.py`
com sinal sintético de `rho_true` conhecido, 100 sorteios MC × 7 pontos × 15
células, medindo poder de 98-100% — para a **triagem de features**. O projeto
sabe fazer análise de poder, fez em outro estágio, e não fez nos gates que
produziram o veredito.)*

## R7. Os números do "0/20" nunca foram recomputados

A Seção 12.1 admite: os artefatos foram escritos pelo código ANTIGO, com dois
defeitos confirmados (bucketing não-determinístico; AUC com n=2 degenerada,
materializada em fold real). A caixa de veredito da mesma seção afirma
"re-rodado — mesma conclusão". As duas frases não podem ser ambas verdadeiras
no mesmo sentido. **"0/20 confirmado após as correções" é asserção, não medição.**

## R8. O denominador "20" está inflado

- `SOLUSDT/R2` C1 e C0 reportam valores idênticos em todas as colunas — 2
  observações duplicadas apresentadas como 4 linhas.
- Os 4 lados de `SOLUSDT/R2` testam um hiperparâmetro que o projeto **já havia
  classificado como ruído puro** (viés +8,356) antes do walk-forward rodar.
- Os 5 combos testam o mesmo período nos mesmos ativos; com ρ≈0,8 entre majors,
  os "62 fold-lado" carregam informação de uma a duas observações independentes
  de regime.

O `AG-392` item 1 mediu a dependência no eixo errado (autocorrelação lag-1
*dentro* de cada série); a que importa é **transversal, entre combos**. Este
argumento corta contra a minha própria análise pooled da R5 na mesma medida — o
que reforça a tese: o experimento tem pouquíssimo conteúdo informacional em
qualquer direção.

## R9. O achado de SHAP é a evidência mais forte do documento, lida como negativa

18 de 20 linhas (90%) têm SHAP-#1 ∈ {`E16f_global_ls_ratio`,
`E05f_time_to_funding_h`}, em modelos treinados independentemente, em 3 ativos,
2 grades de resolução, 2 camadas, 2 lados.

| Features efetivamente independentes | P(um par cobrir ≥18 de 20) |
|---|---:|
| 36 | < 10⁻¹⁵ |
| 12 | 1,3 × 10⁻¹² |
| 6 | 2,3 × 10⁻⁷ |
| 4 (ultraconservador) | **2,0 × 10⁻⁴** |

Modelo que ajusta ruído produz atribuição **divergente**. Este converge — e
converge para posicionamento e ciclo de funding, mecanismo documentado em
perpétuos, não para features de retorno de preço. O documento registra isso sob
"pouca diversificação de sinal". `A04_log_return_12` dominar o gain e nunca
vencer por SHAP é o comportamento **esperado** do gain nativo, e a razão pela
qual SHAP foi adicionado; os dois concordarem seria o resultado suspeito.

## R10. Conclusão sobre generalização com os campos de generalização marcados TBD

`regime_stability_pct` e `generalization_gap_pct` ficaram `TBD` — "nunca foram
medidos". A Fase 3 construiu `compute_train_val_test_gap` exatamente para isso e
não a aplicou. A conclusão foi tirada sobre a quantidade que o documento declara
não ter medido. Agravante: a janela de teste é **um único regime macro**, e as
features que o SHAP identifica como dominantes são as mais plausivelmente
condicionais a regime.

---

# PARTE II — Verificação contra o código: placar

| Refutação | Pré-registro | Resposta verificada | Veredito |
|---|---|---|---|
| **R11** seed única | A1=1 → barra de erro não medida | A1: 1 seed (`walk_forward.py:288-303`, `seed: int` escalar); A4: `feature_fraction` 0,30-0,99 e `subsample` 0,55-0,99 nos 10 | **CONFIRMADA, agravada** |
| **R15** `tau` congelado | Refit por fold → R15 cai | B1/B2/B3/B5: `tau` refit por fold (`alpha.py:1685`), isotônica refit por fold/lado (`:1675`), quantil, calib cresce (`holdout_frac=0,25`) | **REFUTADA — eu estava errado** |
| **R16** AUC medido só acima de `tau` | Confirmado → gate conceitualmente inválido | G3/G4/G5: sim (`score_quality.py:260-264` → `:316`) | **CONFIRMADA — peça decisiva** |
| **R12** agregação sem peso | Média simples → recomputar | C1: `np.mean` (`walk_forward.py:185,513-515`); C2: `SOLUSDT/R2` = 1 fold, 37 trades | **CONFIRMADA** |
| **R13** hiperparâmetro vs. tamanho | Absoluto → complexidade varia | D1: absoluto (29-94); **mas** D3: `n_estimators` é teto com early stopping por fold | **PARCIAL** |
| **R14** data inconsistente | — | H1: `BTCUSDT/R2` `test_start`=2022-01-01 (`..._BTCUSDT_R2.json:145`) | **CONFIRMADA** |
| **R7** correções não recomputadas | J1/J2 | J1: só gates re-rodados; J2: 44 de 106 entradas seriam suprimidas | **CONFIRMADA, agravada** |
| **E1** ⚑ HPO contaminado | Se sim → resultado negativo fica pior | E1: `t0_start=None, t0_end=None` (`hyperparams_optuna.py:299-307`) | **CONFIRMADA CONTRA MIM** |
| **E2** ⚑ vazamento de normalização | Se sim → viés otimista | E2: screen/calibração/`scale_pos_weight` refit por fold; features causais | **LIMPO — a favor da ADR-008** |
| **H3** ⚑ embargo | Sem embargo → viés otimista | H3: `n_embargoed = 0` hardcoded (`walk_forward.py:130`), deliberado | **CONTRA MIM** |
| **R6/K1** falso-negativo | K1="não existe" → não calibrado | K1: não existe | **CONFIRMADA** |

Três hipóteses minhas caíram. Duas respostas fortalecem o achado original contra
os candidatos. O que sobrou está verificado em `arquivo:linha`.

---

# PARTE III — O achado decisivo

## D1. O gate Model exige AUC populacional entre 0,82 e o inatingível

Duas respostas se compõem, e a composição é fatal.

**G3/G4** — `roc_auc_score` roda sobre a população já filtrada por
`side_hat == side_value`, que só existe onde `confidence > tau`
(`score_quality.py:260-264` → `:316`; filtro em `alpha.py:625-629`).
**B3** — `tau = quantile(calibrated_train_all, 1 - target_signal_rate)` com
`target_signal_rate = 0,0189` (`alpha.py:1685`, `constants.yaml:755-762`).

**O AUC do gate Model é medido dentro do top 1,89% do próprio score do modelo.**
Restrição de amplitude severa. Simulação binormal, 4M observações, taxa-base 0,35:

| AUC populacional | AUC medido no top 1,89% | perda |
|---:|---:|---:|
| 0,52 | 0,505 | 0,015 |
| 0,55 | 0,516 | 0,034 |
| 0,60 | 0,529 | 0,071 |
| 0,70 | 0,567 | 0,133 |
| 0,80 | 0,598 | 0,202 |

Invertendo contra as barras de MDE da R1:

| Barra real da linha | Linhas | AUC **populacional** necessário |
|---|---:|---|
| cauda ≥ 0,607 (n=8) | 1 | **≥ 0,820** |
| cauda ≥ 0,653 (n=5) | 1 | **≥ 0,900** |
| cauda ≥ 0,688 (n=4) | 3 | **≥ 0,950** |
| cauda ≥ 0,770 (n=3) | 6 | **inatingível com AUC populacional 0,99** |
| n ≤ 2 | 9 | impossível (R1) |

> O gate Model é impassável para qualquer modelo de trading que exista. A barra
> mais favorável das 20 exige AUC populacional de 0,82; 15 das 20 exigem ≥0,95
> ou são impossíveis. **O resultado "0/20" estava determinado antes de qualquer
> dado entrar no pipeline.**

**G5** confirma que o IC de Spearman usa a mesma população filtrada. Todas as
colunas "IC médio", "IC/IR" e "AUC médio" das Seções 6.2 e 9.1 medem informação
**marginal residual dentro da cauda que o modelo já selecionou** — não poder
preditivo. Para um modelo bem calibrado que colocou o corte no lugar certo,
IC≈0 e AUC≈0,5 ali dentro é o resultado *desejável*, reportado como falha.

**Seleção dupla, agravante não notado pela ADR-008:** `side_hat` é mutuamente
exclusivo por barra — `is_long = (p_long > tau_long) & (p_long > p_short)`
(`alpha.py:625-629`). A população "long" não passou só por um corte de
confiança; passou também por uma **competição contra o modelo short**. A
restrição de amplitude é mais severa que a simulada acima, que modela só o
primeiro filtro.

**Confirmação empírica em J3:** `roc_auc = 0,500` exato aparece **37 vezes**
nos artefatos, com `n_trades` de 2 até **160**. AUC exatamente 0,5 com 160
observações não ocorre por acaso — só por empate total no `confidence`. Minha
previsão em J3 (folds n=2, o bug da Seção 12) estava **errada**: o fenômeno é
mais sistemático que um defeito de amostra pequena.

## D2. A degeneração tem causa mecânica em `alpha.py:1683-1685`

*(Este é o achado da varredura final. Substitui a hipótese do "degrau isotônico"
que publiquei antes, que era mais frágil e não verificável.)*

**B3, literal:** o quantil é calculado sobre `calibrated_train_all` = **TODO o
treino do fold (fit + calib)**, não só o bloco `calib`. E `raw_train_all =
model.predict_proba(X_all)` (`alpha.py:1683`), onde `X_all =
build_design_matrix(train_side_df)` — **o mesmo dado em que o modelo foi
ajustado**.

`tau` é, portanto, um quantil de scores **in-sample**. Scores in-sample são
inflados pelo ajuste. O quantil de 98,11% herda a inflação. No teste, os scores
são sistematicamente menores, e a taxa de sinal realizada cai **abaixo** do alvo
de 1,89% — podendo chegar a zero.

Simulação do deslocamento in-sample/out-of-sample:

| Deslocamento (desvios-padrão) | Taxa de sinal realizada | (alvo 1,890%) |
|---:|---:|---|
| 0,00 | 1,961% | limiar transfere |
| 0,10 | 1,538% | |
| 0,25 | 1,033% | |
| 0,50 | 0,509% | |
| 0,75 | 0,239% | |
| **1,00** | **0,100%** | ≈2 sinais em 2.200 barras → **DEGENERADO** |

**Isto explica a degeneração nos 10 combo×camada, não só em `SOLUSDT/R2`**, e
não depende de nenhuma hipótese não verificada.

A magnitude do problema é medida pelos próprios dados. B4 mostra 8 folds de
`SOLUSDT/R2` com `n_signals=0`:

| n_test_bars | sinais esperados sob transferência correta | P(0 sinais \| p=0,0189) |
|---:|---:|---:|
| 2.720 | 51,4 | 2,9 × 10⁻²³ |
| 2.297 | 43,4 | 9,2 × 10⁻²⁰ |
| 2.204 | 41,7 | 5,5 × 10⁻¹⁹ |
| 2.166 | 40,9 | 1,1 × 10⁻¹⁸ |
| 2.113 | 39,9 | 3,1 × 10⁻¹⁸ |
| 2.069 | 39,1 | 7,2 × 10⁻¹⁸ |
| 2.068 | 39,1 | 7,3 × 10⁻¹⁸ |
| 752 | 14,2 | 5,9 × 10⁻⁷ |

**P(os 8 simultaneamente com zero sinais) ≈ 1,5 × 10⁻¹³⁶.**

Nenhuma quantidade de "sinal fraco" produz esse número. `tau` é um quantil, não
um critério de qualidade: um modelo sem alpha nenhum ainda sinalizaria ~1,89%
das barras. Zero sinais em 2.720 barras é um fato sobre o **limiar**, não sobre
o alpha.

**Não verificável hoje:** B4 confirma que `fold_result.predictions` (que contém
`confidence`, `alpha.py:2316`) **nunca é persistido** — `walk_forward.py:437,442`
usa só como insumo intermediário. Ninguém pode comparar `confidence` contra
`tau` nos artefatos existentes.

*(Nota de honestidade: testei correlação `lambda_l2` × fração de folds usáveis
nos 10 casos — Spearman = -0,29, p = 0,42. **Não sustenta** generalização.
`SOLUSDT/R2` é outlier isolado, não tendência. Descartei a hipótese.)*

---

# PARTE IV — Achados novos da varredura final

## N1. O gate Alpha — que eu tinha dado como o único informativo — também não tem erro-padrão

Único agregado completo transcrito (A5), `BTCUSDT/R2` camada0:

| | |
|---|---:|
| mean `edge_bps` | **+1,348** |
| **median `edge_bps`** | **−1,739** |
| std | 10,303 |
| n folds | 7 |
| min / max | −13,156 / +13,449 |
| SE | 3,894 |
| **t / p (unicaudal)** | **0,346 / 0,371** |
| IC 95% | **[−8,18 ; +10,88]** |

O mesmo padrão no Sharpe: mean = 0,380, **median = −0,774**.

O gate Alpha usa a **média**, com comparação estrita `> 0`, **sem teste
estatístico algum**. O veredito "passa (+1,35bps)" da Seção 7.1 é um ponto
estimado com t = 0,35 cuja mediana é negativa.

**Consequência:** eu havia concedido que "o gate Alpha é o único dos três que
carrega informação real". Retiro parcialmente. Ele mede a coisa certa
(edge líquido) mas a testa errado — comparação de ponto estimado contra zero,
sem dispersão, sobre média simples entre folds. **Nenhum dos três gates da
ADR-008 tem barra de erro em lugar nenhum do documento.**

## N2. Buscas Optuna de combos diferentes produzem valores idênticos

| Combo/camada | `learning_rate` |
|---|---|
| `BTCUSDT/R2` C1 | `0.02904190716480244` |
| `XRPUSDT/R3` C0 | `0.02904190716480243` |

Diferença relativa: **3,6 × 10⁻¹⁶**. Idênticos até a 16ª casa significativa, em
duas buscas sobre combos, resoluções e camadas diferentes.

`min_child_samples` nos 10 vencedores: 29, **77**, **77**, **77**, 94, 52, 42,
61, 71, **77**. O valor 77 aparece **4 vezes em 10**, num `sweep_range=[10,100]`
(91 valores possíveis).

| | |
|---|---:|
| P(≥4 de 10 num valor específico, uniforme) | 2,9 × 10⁻⁶ |
| P(≥4 de 10 em **algum** valor comum) | 2,6 × 10⁻⁴ |

`num_leaves`: 4 aparece 2×, 22 aparece 3×.

**Compatível com sampler TPE compartilhando seed ou estado entre studies, não
com 10 buscas independentes.** Se confirmado, os "1.800 trials" do ADR-007
exploram muito menos espaço do que o número sugere — e o `n_lifetime`, que é o
controle de múltiplas comparações do projeto inteiro, está contando trials
correlacionados como se fossem independentes. Isso afeta retroativamente toda a
correção de viés de seleção do ADR-007.

Não verifiquei o código do sampler; registro como achado de alta prioridade
para verificação, não como fato estabelecido.

## N3. `n_better` (C1>C0) não mede o que o documento diz que mede

O glossário afirma: *"a diferença entre C1 e C0 é uma ablação de restrição
monotônica, não de conjunto de features"*. **D2 mostra que os hiperparâmetros
também diferem, em 4 dos 5 combos:**

| Combo | C1 (leaves/mcs/n_est/λ₂) | C0 (leaves/mcs/n_est/λ₂) |
|---|---|---|
| `BTCUSDT/R2` | 4 / 29 / 787 / 0,454 | 4 / 77 / 729 / 0,215 |
| `SOLUSDT/R3` | 18 / 71 / 391 / 9,305 | 32 / 77 / 441 / 5,074 |
| `XRPUSDT/R2` | 22 / 94 / 597 / 11,772 | 6 / 52 / 721 / 1,124 |
| **`XRPUSDT/R3`** | **5 / 42 / 103 / 0,158** | **10 / 61 / 776 / 14,977** |
| `SOLUSDT/R2` | 22 / 77 / 540 / 37,714 | idêntico |

`XRPUSDT/R3` é o extremo: C0 tem 7,5× mais árvores e **95× mais regularização
L2** que C1. A diferença de +26,34bps (C0) contra −34,54bps (C1) — **60bps num
único combo** — não mede o valor da restrição monotônica. Mede a distância entre
dois modelos distintos, sob uma seed.

Note ainda que C1 de `XRPUSDT/R3` tem `n_estimators=103` contra 391-787 nos
demais: é o menor teto de árvores do painel, e é o pior resultado do painel.

**Consequência retroativa:** `n_better` foi metade do gate duplo do ADR-007 e a
base do critério de promoção da Seção 1.4. A métrica é comparação entre dois
modelos independentemente sintonizados, não ablação.

## N4. O piso de trades protege o fold, não o lado

**C4:** `degenerado = n_filled_trades < min_trades` com `n_filled_trades` contado
por **fold**, somando long+short (`walk_forward.py:463-469`; `backtest_lite`
agrupa por `path_id == fold_id`). Um fold com 10 trades pode ter 8 long e 2
short — e o lado short entra no agregado com n=2. É exatamente o defeito que a
Seção 12.1 corrigiu em `score_quality.py`, sobrevivendo intacto no gate de
degeneração.

## N5. Sharpe anualizado com piso de 2 trades; custo sem spread

**C5:** `sharpe_naive` anualiza por `√(trades_per_year)` com
`_MIN_TRADES_FOR_SHARPE = 2` e piso de `std == 0.0` exato
(`backtest_lite.py:47-61`). Para um fold trimestral com 37 trades o fator é
√148 ≈ 12,2. O "−4,077" de `SOLUSDT/R2` é um SR por trade de −0,335 sobre 37
observações — **IC 95% aproximado [−8,1 ; −0,05]** — reportado com 3 casas
decimais e sem barra de erro.

**G1:** `edge_bps` desconta `maker_fee` (2bps) na entrada, `maker_fee`/`taker_fee`
(2/5bps) na saída, e funding realizado. **Não desconta spread** (0 ocorrências de
`"spread"` em `triple_barrier.py`) e `adverse_selection_bps` é explicitamente
reportado mas **não subtraído**. Para o único sobrevivente (`BTCUSDT/R2` C1,
+7,90bps), 2-4bps de spread/seleção adversa consomem metade do edge.

**H2:** `initial_train_years=2` é contado em **trimestres civis** (`8` períodos),
e o trimestre de início conta como completo mesmo tendo 23 dias. `SOLUSDT`/`XRP`
começam em 2021-12-08 e testam a partir de 2023-10-01 — **1,81 anos de treino,
não 2**. Discrepância de ~9,5% em 4 dos 5 combos.

## N6. A campanha não é reproduzível

- **A1:** nenhum script chamador de `run_walk_forward_for_combo` está commitado
  fora de `tests/unit/test_models_walk_forward_driver.py`. **A invocação que
  gerou os 5 JSONs não está sob controle de versão.**
- **A3:** os artefatos não gravam a seed (grep `"seed"`: 0 ocorrências em 5).
- **J1:** `rodar_gates_v2.py` e `montar_model_cards_v2.py`, citados na mensagem
  do commit `e812ab1`, **não existem no repositório em nenhum commit do
  histórico**. A frase "re-rodado contra os 10 combo×variant" não tem artefato
  que a sustente.

Um veredito de produção sobre 5 candidatos repousa numa execução que não pode
ser repetida nem auditada por terceiros.

## N7. A correção da Seção 12 tornaria o gate ainda mais impassável

**J2:** 44 de 106 entradas fold×lado (**41,5%**) têm `n_trades < 5` e seriam
suprimidas pelo piso novo:

| | Antes | Depois do piso `n≥5` |
|---|---:|---:|
| Linhas com gate Model matematicamente impossível | 9/20 | **18/20** |

A ADR-008 afirmou que a correção não muda o veredito. Tecnicamente verdade —
porque o gate passa de "quase impassável" a "impassável em 18 de 20". **Isso é
saturação, não robustez.**

## N8. A função de FDR existe, é testada, e nunca é chamada

**J4:** `apply_fdr_to_model_gates` (`walk_forward_gates.py:258`), 3 testes,
nenhum arquivo de produção a importa. O próprio módulo documenta em `:73-76`:
*"quem for consolidar um lote real deve usar `apply_fdr_to_model_gates`, não o
veredito bruto por célula"*. O "0/20" foi consolidado célula a célula, contra a
instrução escrita no próprio código.

## N9. A auditoria de label da Fase 2 nunca foi executada

**F3:** `compute_label_distribution_stats` (`src/analysis/label_audit.py`)
existe, é testada, e **nunca é chamada contra dado real** — nenhum CLI, nenhum
`experiments/*.json`. A taxa-base do label por fold, insumo direto para saber se
a distribuição de score derivou entre folds (§D2), nunca foi medida. A Fase 2
foi entregue como infraestrutura, não como medição.

**F1:** o censo de nulos (`experiments/feature_null_census.json`) é de
2026-08-26 — anterior à promoção do vetor de features atual (AG-372, 2026-08-28)
e anterior à campanha walk-forward (2026-08-31). Nunca regenerado. **F2** confirma
exclusão complete-case: qualquer nulo em qualquer das 36 features descarta a
linha inteira (`dataset.py:760-762`). Com `E16f_global_ls_ratio` em
`frac_null=0,1127` para BTCUSDT, isso remove ~11% das linhas, de períodos
desconhecidos — na feature que o SHAP aponta como dominante.

---

# PARTE V — O que me derrubou, sem atenuação

**E1 é a resposta mais importante contra mim.** A busca Optuna usa
`t0_start=None, t0_end=None` (`hyperparams_optuna.py:299-307` →
`dataset.py:285-286`), sem restrição de data; `cpcv.py` não tem corte algum
(grep `t0_start|t0_end|cutoff_date`: 0 ocorrências). Os anos 2022-2026 que o
walk-forward trata como fora-da-amostra estavam **dentro** do dado que escolheu
os hiperparâmetros. **O walk-forward é otimisticamente enviesado quanto ao HPO.**

**H3 me derruba de novo.** `n_embargoed = 0` hardcoded (`walk_forward.py:130`),
deliberado; só há purge por `t1`. Features com janela de 48-96 barras atravessam
a fronteira treino/teste na borda de cada fold. Mais viés otimista.

Somados: **os números negativos da Seção 5.4 são um teto, não uma estimativa
neutra.** A realidade fora-da-amostra é pior que +7,90bps para `BTCUSDT/R2`.

**E2 me derruba numa terceira direção:** o pipeline é mais limpo do que suspeitei.
Monotone screen, calibração e `scale_pos_weight` refit por fold
(`alpha.py:2118, 1181-1221, 1679, 1463-1472`); features com janelas rolling
causais; ATR das barreiras causal (**F4**); nenhuma normalização global. Não há
o vazamento clássico que eu procurava.

**R15 caiu inteira.** `tau` é refit por fold, isotônica refit por fold e lado sem
cache, calib cresce proporcionalmente. Minha hipótese de "calibração congelada"
era falsa. O defeito real (§D2) é outro e mais sutil: `tau` refit corretamente,
mas sobre a população errada.

---

# PARTE VI — Veredito

| | ADR-008 | Após esta refutação |
|---|---|---|
| **Gate Data** | 0/10, cobertura insuficiente | **Nulo.** Mede frequência de trade (R4); piso aplicado ao fold combinado, não ao lado (N4). |
| **Gate Model** | 0/20, AUC indistinguível de moeda honesta | **Nulo e impassável.** Exige AUC populacional de 0,82 a inatingível (§D1). Mede informação marginal na cauda duplamente selecionada. |
| **Gate Alpha** | 8/10 falham em edge líquido | **Mede a coisa certa, testa errado.** Ponto estimado vs. zero, sem SE; único "passa" tem t=0,35 e mediana negativa (N1); média simples entre folds (R12); sem spread (N5); e com viés otimista conhecido (E1+H3). |
| **Degeneração** | "o modelo fica calado" = ausência de sinal | **Defeito de limiar.** `tau` é quantil de scores in-sample (§D2). P(8 folds com 0 sinais sob transferência correta) ≈ 1,5×10⁻¹³⁶. |
| **Composto** | 0 de 20, nenhum generaliza | **O experimento não testou generalização.** |

**A frase que os fatos sustentam:**

> Os gates Data e Model não mediram nada: o primeiro mede frequência de trade, o
> segundo exige por construção um AUC populacional de 0,82 a 0,99+. O gate Alpha
> mede edge líquido de verdade, mas sem erro-padrão, sem peso por trade, sem
> spread, sob seed única, sem embargo, com hiperparâmetros escolhidos vendo o
> período de teste, e sobre uma população de trades cujo limiar de entrada foi
> calibrado em scores in-sample. `BTCUSDT/R2` é o único com edge positivo nas
> duas camadas — e é também o único que testa 2022 (H1), comparação não pareada
> com os outros quatro; seu resultado em camada0 tem t=0,35 e mediana negativa.

**Sobre a direção:** E1 e H3 sugerem que a realidade fora-da-amostra é pior que
o reportado. Não estou argumentando que os 5 candidatos têm alpha. Estou
argumentando que **este experimento não sabe**, e que o número "0/20" que ele
produziu era inevitável.

---

# PARTE VII — Ações, ordenadas por razão informação/custo

| # | Ação | Custo | Decide |
|---:|---|---|---|
| 1 | **Persistir `confidence`, `tau`, `n_signals` e a taxa de sinal realizada por fold** no artefato | 3 linhas em `walk_forward.py` | Sem isso, §D2 não é verificável. O dado existe em memória (`alpha.py:2316`) e é descartado. |
| 2 | **Calcular `tau` sobre o bloco `calib` puro** (out-of-fit), não sobre `fit+calib` — `alpha.py:1683-1685` | 1 linha + re-rodar | Testa §D2 diretamente. Se a taxa de sinal realizada subir para perto de 1,89%, a Seção 5.5 do documento auditado precisa ser reescrita e a Fase 4 inteira refeita. |
| 3 | **Medir AUC/IC sobre a população COMPLETA de teste**, não só `side_hat != 0` — `score_quality.py:260-264` | filtro | Único caminho para o gate Model voltar a significar algo. Manter as duas métricas com nomes distintos. |
| 4 | **Rodar a Fase 4 com ≥5 seeds**, reportar mediana e dispersão | ~10 min | A1+A4: o número atual é amostra de tamanho 1 de uma distribuição com `feature_fraction` de até 0,30. |
| 5 | **Adicionar erro-padrão a TODOS os agregados** e testar o gate Alpha, não comparar ponto a zero | trivial | N1. O único "passa" do painel tem t=0,35. |
| 6 | **Verificar se os studies Optuna compartilham seed/estado de sampler** | leitura de código | N2. Se sim, `n_lifetime` conta trials correlacionados como independentes — afeta toda a correção de múltiplas comparações do projeto. |
| 7 | **Commitar o script chamador; gravar seed no artefato** | trivial | A1/A3/J1. Sem isso a campanha não é auditável. |
| 8 | **Aplicar `min_trades` por LADO** — `walk_forward.py:463-469` | 2 linhas | N4. Mesmo defeito que a Seção 12 corrigiu em outro módulo. |
| 9 | **Chamar `apply_fdr_to_model_gates` ou remover a função** | trivial | N8. Produção contradiz a própria docstring. |
| 10 | **Injetar alvo sintético de AUC conhecido pelos 3 gates** | ~117s | K1. Reusar o padrão de `eixo1_power_diagnostic.py`, que o projeto já tem. |
| 11 | **Descontar spread e `adverse_selection_bps`** ou declarar o edge como bruto-de-spread | modelo de custo | N5. Afeta o único sobrevivente. |
| 12 | **Cortar a busca Optuna por data** (`t0_end` = início do walk-forward) e refazer | campanha nova | E1. Mais cara e mais importante para qualquer conclusão sobre generalização. |
| 13 | **Corrigir a Seção 5.1** do documento auditado | trivial | H1. `BTCUSDT/R2` testa desde 2022-01-01. |

**Sequência mínima para um veredito honesto:** 1 → 2 → 3 → 4 → 5. Abaixo de 30
minutos de compute. Só depois disso "os 5 candidatos generalizam?" volta a ser
uma pergunta respondível.

**Recomendação sobre os 5 candidatos:** nenhuma mudança agora. Não porque
sobrevivam — E1 e H3 sugerem que a realidade é pior — mas porque podar produção
com base num instrumento que não pode aprovar nada estabelece o precedente
errado. Conserte o instrumento primeiro; a decisão de poda fica trivial depois,
em qualquer direção que os números apontem.

---

# PARTE VIII — Registro sugerido para o `architecture_gaps_log`

| Entrada | Conteúdo | Severidade |
|---|---|---|
| **AG-394** | Gate Model estruturalmente impassável: AUC medido sobre população pós-`tau` (`score_quality.py:260-264`) com `target_signal_rate=0,0189` exige AUC populacional ≥0,82 na linha mais favorável, inatingível em 15 de 20. Bloqueia uso do gate como critério de promoção. | ALTA |
| **AG-395** | `tau` calculado sobre scores in-sample (`alpha.py:1683-1685`, `calibrated_train_all` = fit+calib). Taxa de sinal realizada colapsa sob gap in/out. P(8 folds de `SOLUSDT/R2` com 0 sinais sob transferência correta) ≈ 1,5×10⁻¹³⁶. Não verificável: `confidence` não é persistida. | ALTA |
| **AG-396** | Campanha da Fase 4 não reproduzível: script chamador não commitado (A1), seed não gravada (A3), scripts de re-execução do `e812ab1` inexistentes (J1). | ALTA |
| **AG-397** | `n_better` (C1>C0) não mede ablação monotônica: hiperparâmetros diferem entre camadas em 4 dos 5 combos (D2). Afeta retroativamente o gate duplo do ADR-007 e a promoção da Seção 1.4. | ALTA |
| **AG-398** | HPO contaminado pelo período de teste (`t0_start=None, t0_end=None`) e `n_embargoed=0` hardcoded. Ambos enviesam o walk-forward para OTIMISTA — o achado negativo é um teto. | MÉDIA |
| **AG-399** | Possível compartilhamento de seed/estado entre studies Optuna: `learning_rate` idêntico até 10⁻¹⁶ entre combos diferentes; `min_child_samples=77` em 4 de 10 (p≈2,6×10⁻⁴). Se confirmado, `n_lifetime` conta trials correlacionados como independentes. | A VERIFICAR |
| **AG-400** | Nenhum agregado da ADR-008 tem erro-padrão. Gate Alpha compara ponto estimado a zero; único "passa" tem t=0,35 e mediana negativa. | MÉDIA |
| **AG-401** | `min_trades` de degeneração aplicado por fold combinado, não por lado (`walk_forward.py:463-469`) — permite lado com n=2 no agregado. | MÉDIA |

---

# PARTE IX — Validação ponto a ponto

Cada afirmação deste documento, com status, fonte e o que a derrubaria.

| # | Afirmação | Status | Fonte | O que a derrubaria |
|---:|---|---|---|---|
| 1 | MDE do gate Model = 0,607 a impossível por linha | **DERIVADO, sólido** | σ=0,16 (Seção 10, `MEASURED`) + `n` da Seção 9.1 + t não-central | σ real fora da faixa 0,13-0,19 que a própria ADR mediu |
| 2 | 9 de 20 linhas com gate impassável (`n≤2`) | **ARITMÉTICO** | Seção 9.1 | erro na coluna "OOS folds" corrigida |
| 3 | Poder 7-12%; P(0/20 \| AUC 0,55)=15,4% | **DERIVADO, sólido** | mesma base do #1 | idem #1 |
| 4 | Sweep de α é o eixo de menor alavancagem | **DERIVADO** | MDE em α=0,10 vs 0,05 | — |
| 5 | Gate Data mede frequência de trade | **DERIVADO + VERIFICADO** | Seção 2.2 (trd/dia) + C4 (`walk_forward.py:463-469`) | Poisson é aproximação; a direção não depende dela |
| 6 | AUC pooled 0,5128, IC95% [0,467;0,559] | **DERIVADO** | 13 linhas da Seção 9.1, σ=0,16 | assume folds independentes — **eu mesmo enfraqueço isso em R8** |
| 7 | Nenhum teste de falso-negativo dos 3 gates | **VERIFICADO** | K1, K2 (23 testes, todos de corretude) | — |
| 8 | Correções da Seção 12 nunca recomputadas | **VERIFICADO** | J1 (mensagem do commit `e812ab1`) | — |
| 9 | SHAP: 18/20 em 2 features, p≤2×10⁻⁴ | **DERIVADO, conservador** | Seção 8.1/8.2 | se as 20 linhas não forem ajustes independentes — mas são 5 combos × 2 camadas × 2 lados |
| 10 | `regime_stability`/`generalization_gap` = TBD | **CITADO** | Seção 9 do documento auditado | — |
| 11 | 1 seed; `feature_fraction` até 0,30 | **VERIFICADO** | A1 (`walk_forward.py:288-303`), A4 | — |
| 12 | AUC medido só acima de `tau` | **VERIFICADO** | G3/G4 (`score_quality.py:260-264` → `:316`) | — |
| 13 | Barra do gate = AUC populacional 0,82 a inatingível | **SIMULADO** | binormal 4M obs, taxa-base 0,35, TSR=0,0189 | taxa-base muito diferente de 0,35 muda a magnitude, **não o sinal** — a restrição de amplitude é estrutural |
| 14 | Seleção dupla agrava a restrição | **VERIFICADO, não quantificado** | `alpha.py:625-629` (`& (p_long > p_short)`) | — |
| 15 | `roc_auc=0,5` exato 37×, até n=160 → empate total | **VERIFICADO** | J3 | — |
| 16 | `tau` é quantil de scores **in-sample** | **VERIFICADO** | B3 + `alpha.py:1683-1685` (`X_all` = mesmo dado do fit) | — |
| 17 | Gap in/out de 1 sd → taxa de sinal 0,10% → degenerado | **SIMULADO** | modelo normal | o gap real não foi medido (**F3**: nunca executado). É mecanismo plausível, **não fato estabelecido** |
| 18 | P(8 folds com 0 sinais) ≈ 1,5×10⁻¹³⁶ | **ARITMÉTICO** | B4 (`n_test_bars` reais) + TSR=0,0189 | assume independência entre barras; mesmo com forte autocorrelação o expoente continua absurdo |
| 19 | Hipótese do degrau isotônico | **DESCARTADA POR MIM** | simulação produziu degraus de 0,1-0,3%, insuficientes | substituída por #16, que é verificado em código |
| 20 | `lambda_l2` × degeneração | **NÃO SUSTENTADA** | Spearman −0,29, p=0,42, n=10 | descartada; `SOLUSDT/R2` é outlier isolado |
| 21 | Gate Alpha: t=0,35, mediana negativa | **ARITMÉTICO** | A5 (mean/median/std/n literais do JSON) | é 1 dos 10 agregados — **os outros 9 não foram transcritos**; ver pendência P1 |
| 22 | `learning_rate` idêntico até 10⁻¹⁶ entre combos | **VERIFICADO (dado)** / **HIPÓTESE (causa)** | D2 | a causa (seed compartilhada) **não foi verificada no código do sampler** |
| 23 | `min_child_samples=77` em 4/10, p≈2,6×10⁻⁴ | **ARITMÉTICO** | D2 | TPE converge; o cálculo assume uniforme. Sinaliza, não prova |
| 24 | C1/C0 diferem em hiperparâmetro, não só monotonicidade | **VERIFICADO** | D2 | — |
| 25 | `min_trades` por fold combinado, não por lado | **VERIFICADO** | C4 | — |
| 26 | Sharpe: piso 2 trades, √(trades/ano) | **VERIFICADO** | C5 (`backtest_lite.py:47-61`) | — |
| 27 | Custo sem spread; `adverse_selection` não subtraído | **VERIFICADO** | G1 (`triple_barrier.py:46-51`, 0 ocorrências de `spread`) | — |
| 28 | Treino do fold 0 = 1,81 anos, não 2 | **DERIVADO** | H2 + `volatility_walkforward.py:89-93` | — |
| 29 | Campanha não reproduzível | **VERIFICADO** | A1, A3, J1 | — |
| 30 | 41,5% das entradas suprimidas → 18/20 impassáveis | **VERIFICADO (44/106) + DERIVADO (projeção)** | J2 | a projeção é uniforme; a supressão real varia por combo (tabela J2) |
| 31 | FDR existe e nunca é chamada | **VERIFICADO** | J4 + `walk_forward_gates.py:73-76` | — |
| 32 | Label audit nunca executada; censo de nulos obsoleto | **VERIFICADO** | F3, F1 | — |
| 33 | E1: HPO viu o período de teste | **VERIFICADO** | `hyperparams_optuna.py:299-307`, `dataset.py:285-286` | — |
| 34 | H3: sem embargo | **VERIFICADO** | `walk_forward.py:130` | — |
| 35 | E2/F4: pipeline sem vazamento clássico | **VERIFICADO — contra mim** | `alpha.py:2118, 1181-1221, 1679, 1463-1472`; `triple_barrier.py:81-82` | — |
| 36 | R15 (`tau` congelado) era falsa | **REFUTADA — contra mim** | B1, B2, B3, B5 | — |
| 37 | `BTCUSDT/R2` testa desde 2022-01-01 | **VERIFICADO** | H1 (`..._BTCUSDT_R2.json:145`) | — |

### Pendências que eu não consegui fechar

| | O que falta | Por quê |
|---|---|---|
| **P1** | `mean`/`median`/`std`/`n` dos outros **9** agregados combo×camada | só `BTCUSDT/R2` C0 foi transcrito literalmente (A5). Sem eles não dá para dizer se o padrão "média positiva, mediana negativa" é geral. **É a lacuna mais importante deste documento.** |
| **P2** | `edge_bps` e `sharpe` **por fold** (tenho só `n_filled_trades`, C3) | sem isso não recomputo os agregados ponderados por trade que a R12 exige |
| **P3** | Gap in-sample/out-of-sample real por fold | `compute_train_val_test_gap` da Fase 3 existe e nunca rodou (F3). É o que confirma ou derruba §D2 |
| **P4** | Código do sampler Optuna (seed/estado entre studies) | N2 fica como sinal, não como achado |
| **P5** | Taxa de nulos das 2 features SHAP-dominantes **por fold** | F1: granularidades incompatíveis; nenhum artefato combina as dimensões |

### Autocrítica: onde esta refutação é mais frágil

1. **§D2 é mecanismo, não medição.** Verifiquei que `tau` usa scores in-sample
   (código, B3). **Não** medi o gap in/out real, porque o projeto nunca o mediu
   (F3). A simulação mostra que o mecanismo é suficiente; não prova que é a
   causa. P3 resolve.
2. **O AUC pooled da R5 usa uma premissa que eu mesmo ataco na R8.** Se ρ≈0,8
   entre combos, o IC [0,467;0,559] é otimista e o intervalo real é mais largo —
   o que reforça "inconclusivo" e enfraquece qualquer leitura positiva.
3. **A simulação de restrição de amplitude assume taxa-base 0,35 e binormalidade.**
   A magnitude exata depende disso. A **direção** não: selecionar o top 1,89% e
   medir AUC ali dentro comprime rumo a 0,5 sob qualquer distribuição contínua.
4. **N2 é o achado mais especulativo do documento.** A coincidência numérica é
   real e verificada; a explicação (seed compartilhada) não foi confirmada em
   código. Está marcado A VERIFICAR no AG-399, não como fato.
5. **Não refutei a direção do achado, e não tentei.** E1 e H3 indicam que os
   candidatos provavelmente são piores que o reportado. Minha tese é sobre a
   validade do instrumento, não sobre a qualidade do alpha.

---

*Fim. Três das dez refutações originais caíram na verificação e duas das
respostas fortalecem o achado da ADR-008 contra os candidatos. A conclusão
"0/20" continua não sustentada — não porque os candidatos sejam bons, mas
porque o instrumento que os reprovou não conseguiria aprovar nada.*
