# Protocolo de interrogatório — Fase 2 da refutação adversarial do "0/20"

**Complemento a:** `ADENDO_ADVERSARIAL_refutacao_0de20_20260831.md`
**Objetivo:** converter as refutações R1-R14 de argumentos em fatos verificáveis
contra o código e os artefatos reais.
**Regra de uso:** cada pergunta tem **interpretação pré-registrada** — o que cada
resposta possível implica está escrito ANTES de a resposta existir. Isso impede
racionalização post-hoc nas duas direções: várias perguntas abaixo podem
derrubar a minha refutação, não só o achado da ADR-008. Elas estão marcadas
com ⚑.

**Formato de resposta ideal:** número da pergunta + trecho literal de código
(`arquivo.py:linha`) ou valor do JSON. Se um campo não existir no artefato,
responder "não existe" é uma resposta válida e informativa.

---

## Bloco A — Seeds (R11). Prioridade máxima.

A Fase 4 rodou "10 runs (5 combos × 2 camadas), ~117s de treino, 0 falhas".
Isso é consistente com **uma única seed**. O ADR-007 inteiro foi construído em
cima da constatação de que a variância entre seeds é grande o bastante para
inverter a ordenação C1/C0 (Seção 2.2) e para mover o edge de `SOLUSDT/R3`
numa faixa de 16,6-39,3bps entre 10 seeds — **dispersão da mesma ordem de
grandeza do efeito que a Fase 4 alega ter medido (-17,00bps)**.

| # | Pergunta | Onde olhar | Interpretação pré-registrada |
|---|---|---|---|
| **A1** | Quantas seeds a campanha walk-forward da Fase 4 rodou por combo×camada? | `walk_forward.py` — assinatura da função de entrada; `n_seeds`/`seeds` em `constants.yaml`; contagem de entradas no JSON | **1 seed** → o veredito 0/20 tem barra de erro não medida e provavelmente maior que o próprio efeito. Refutação R11 confirmada. **≥5 seeds** → R11 cai, e o achado fica muito mais forte. |
| **A2** | O `random_state`/`seed` do LightGBM é fixo entre folds ou varia por fold? | `alpha.run_fold` / params do `LGBMClassifier` | Fixo entre folds → os 12-19 folds compartilham o mesmo sorteio de bagging/feature_fraction; a variância entre folds subestima a variância real. |
| **A3** | O JSON `alpha_walk_forward_*.json` grava a seed usada? Qual valor? | artefato, campo raiz | Se grava e é `alpha_random_seed` (a mesma do run canônico de produção), então o walk-forward herdou exatamente a seed que a Seção 2.2 já documentou como divergente da mediana de 10 seeds. |
| **A4** | `feature_fraction`/`bagging_fraction` < 1,0 nos hiperparâmetros confirmados dos 5 combos? | `constants.yaml::alpha_production_hyperparam_override` | Se sim, o modelo é estocástico e A1=1 seed é uma falha metodológica direta. Se ambos =1,0 e `num_threads` determinístico, a sensibilidade a seed vem só do `tau`/calibração — menos grave. |
| **A5** | Existe algum campo de dispersão (dp, IC, min/max entre seeds) em qualquer métrica da Fase 4? | JSON + `walk_forward.py` | Ausência total → todas as tabelas das Seções 5, 6, 7, 9 são estimativas pontuais sem erro-padrão, apresentadas como vereditos binários. |

---

## Bloco B — `tau` e calibração (R15, novo). Prioridade máxima.

O sintoma central da Fase 4 é "o modelo fica calado" (`n_signals=0` em 8/12
trimestres). Existem duas causas possíveis que produzem **exatamente o mesmo
sintoma**: (i) o sinal desapareceu; (ii) o `tau` e/ou o calibrador de
probabilidade não foram reajustados por fold e ficaram desalinhados com a
distribuição de `confidence` do fold. A ADR-008 assume (i) sem testar (ii).

| # | Pergunta | Onde olhar | Interpretação pré-registrada |
|---|---|---|---|
| **B1** | O `tau` é recalculado DENTRO de cada fold walk-forward, a partir do split de calibração daquele fold? Ou é carregado de `constants.yaml` / do artefato de produção? | `walk_forward.py` → chamada a `alpha.run_fold`; procurar onde `tau` é atribuído | **Carregado/fixo** → o achado de degeneração é indistinguível de um bug de calibração. Toda a Seção 5.5 fica sem base. **Refit por fold** → causa (ii) eliminada, R15 cai. |
| **B2** | Qual é o método de calibração (Platt / isotônica / nenhum) e ele é refitado por fold? | mesmo caminho; procurar `CalibratedClassifierCV`, `IsotonicRegression`, `sigmoid` | Isotônica refitada num split de calibração pequeno (folds trimestrais) é notoriamente instável e produz `confidence` quase constante — que é **exatamente** o `AUC=0,500 ±0,000` observado em 5 linhas da Seção 9.1. |
| **B3** | Como `tau` é derivado — quantil da distribuição de `confidence` no calib, ou valor absoluto? | idem | **Quantil** (ex. p90) → `n_signals=0` seria matematicamente impossível; se mesmo assim ocorre, há bug. **Absoluto** → `n_signals=0` é o resultado esperado sob qualquer deslocamento de distribuição, e não diz nada sobre alpha. |
| **B4** | Qual a estatística descritiva de `confidence` por fold (min/média/max/dp) nos 8 folds de `SOLUSDT/R2` com `n_signals=0`? Ela chega perto de `tau`? | JSON da Fase 4, por fold | Se `max(confidence) < tau` por margem larga e constante → calibração desalinhada, não ausência de sinal. Se `max(confidence)` oscila em torno de `tau` → sinal genuinamente fraco. **Esta é a única pergunta que separa (i) de (ii) de forma definitiva.** |
| **B5** | O split de calibração dentro de cada fold walk-forward tem quantas barras/trades? É fração fixa do treino? | `alpha.run_fold`, splits `fit`/`stop`/`calib` | Se `calib` cresce com o treino ancorado, o calibrador do fold 0 e do fold 18 têm regimes de amostra completamente diferentes — outro confundidor não medido. |
| **B6** | ⚑ O `tau` usado no walk-forward foi otimizado em algum momento sobre dados que incluem o período de teste? | rastrear a proveniência do `tau` até a campanha que o produziu | Se **sim**, o walk-forward está contaminado e o resultado negativo é ainda pior do que reportado. **Isto derruba a minha refutação, não a fortalece.** |

---

## Bloco C — Agregação e ponderação (R12, novo)

A Seção 5.2 define "Sharpe (usados)" como média sobre os folds usados. Média
simples entre folds trata um fold de 10 trades igual a um de 100, e maximiza
a variância do agregado.

| # | Pergunta | Onde olhar | Interpretação pré-registrada |
|---|---|---|---|
| **C1** | O "Sharpe (usados)" e o "Edge líq." da Seção 5.4 são média simples entre folds, ou ponderados por `n_trades`? | `walk_forward.py`, agregador | **Média simples** → recomputar ponderado por trade. Peço explicitamente o número reponderado dos 10 combo×camada. Pode mover vários sinais. |
| **C2** | `SOLUSDT/R2` tem **1** fold usado. O "-57,66bps / Sharpe -4,077" do combo é literalmente esse único fold? | JSON, fold a fold | Se sim: 2 das 20 linhas do veredito final são um único trimestre com ~10 trades, apresentado como evidência de não-generalização de um ativo. Isso não é uma medição, é uma anedota com casas decimais. |
| **C3** | Qual o `n_trades` de cada fold usado, por combo×camada×lado? (tabela completa) | JSON | Permite recomputar tudo ponderado por trade e calcular o erro-padrão real de cada agregado — que hoje não existe em lugar nenhum do documento. |
| **C4** | O piso `MIN_OCCURRENCES_ABOVE_TAU=10` é aplicado por fold×**lado** ou por fold (long+short somados)? | `walk_forward.py`, critério de degeneração | Se por fold somado, um lado pode entrar no agregado com 2 trades — o mesmo defeito n=2 que a Seção 12 corrigiu em `score_quality.py` sobreviveria no gate de degeneração. |
| **C5** | Como o Sharpe por fold é calculado — sobre retornos por trade ou por barra? Anualizado por qual fator? | fórmula exata | Necessário para saber se `-4,077` e `+0,992` são comparáveis entre folds de contagem de trade muito diferente. O `Sharpe=47.163,5` sugere divisão por dp≈0 sem piso. |

---

## Bloco D — Hiperparâmetro vs. tamanho de treino (R13, novo)

Walk-forward ancorado: o fold 0 de BTC treina com ~2 anos, o fold 18 com ~6,6
anos — variação de mais de 3× no `n` de treino. Os hiperparâmetros foram
confirmados uma única vez, sobre o histórico completo.

| # | Pergunta | Onde olhar | Interpretação pré-registrada |
|---|---|---|---|
| **D1** | `min_data_in_leaf` (ou `min_child_samples`) é valor absoluto ou fração de `n_train`? | `constants.yaml::alpha_production_hyperparam_override` | **Absoluto** → o modelo do fold 0 e do fold 18 têm complexidade efetiva muito diferente com o mesmo parâmetro. Os folds iniciais e finais não são o mesmo estimador; a variância entre folds (σ=0,16) incorpora isso e não é ruído puro. |
| **D2** | Quais os valores exatos de `num_leaves`, `min_data_in_leaf`, `n_estimators`, `learning_rate`, `lambda_l1/l2` dos 5 combos? | idem | Permite estimar se o modelo é grande demais para uma janela de 2 anos com 0,06-0,32 trades/dia. |
| **D3** | `n_estimators` é fixo, ou há `early_stopping` com split `stop` por fold? | `alpha.run_fold` | **Fixo, herdado do CPCV** → aplicar um número de árvores sintonizado em 6 anos a um fold de 2 anos é um mismatch estrutural que produz exatamente "confidence quase constante". |
| **D4** | O número de árvores efetivamente usadas (`best_iteration`) é gravado por fold? Qual a série? | JSON | Se cai/oscila muito entre folds, D3 está materializado. |
| **D5** | ⚑ O `initial_train_years=2` é aplicado sobre barras ou sobre calendário? Quantas barras (e quantos trades) tem o treino do fold 0 de cada combo? | `walk_forward.py`, splitter | Se o fold 0 treina com poucos milhares de barras e ~100 trades, os primeiros folds são estruturalmente inúteis e deveriam ter sido descartados por desenho — **o que reduz o `n` real e reforça a ADR-008, não a minha refutação.** |

---

## Bloco E — Contaminação do hiperparâmetro (⚑ este bloco pode derrubar minha refutação)

| # | Pergunta | Onde olhar | Interpretação pré-registrada |
|---|---|---|---|
| **E1** | ⚑ Qual o intervalo de datas que a busca Optuna (ADR-007, Itens 1-2) usou para escolher os hiperparâmetros dos 5 combos? | `experiments/alpha_optuna_*`, ou o ADR-007 | Se a busca viu dados até 2026-08, então **os folds de teste do walk-forward estavam dentro da janela de seleção de hiperparâmetro**. O walk-forward não é OOS quanto ao HPO — e o resultado negativo passa a ser *mais* condenatório, não menos. |
| **E2** | ⚑ O walk-forward refaz a seleção de features / o cálculo de normalização por fold, ou usa estatísticas globais? | `alpha.run_fold`, pipeline de features | Estatísticas globais (média/dp de normalização calculadas no histórico inteiro) = vazamento clássico. Se existe, o walk-forward está otimisticamente enviesado e **os números negativos são um piso, não uma estimativa**. |
| **E3** | Os thresholds `alpha_gate_*` foram escolhidos DEPOIS de ver as tabelas das Seções 5-9? | timeline dos commits `b03109c..404a7dd` vs. Seção 10 | A Seção 10 admite que sim ("depois do cartão final fechado"). Confirmar em commit. Isso é garimpagem de limiar na direção conservadora — que a Seção 11.1 tentou neutralizar varrendo α, mas ver R3. |

---

## Bloco F — Cobertura de feature e distribuição de label por fold

O SHAP diz que as features que movem a predição são `E16f_global_ls_ratio` e
`E05f_time_to_funding_h`. A Seção 5.3 registra que `E14f_toptrader_ls_ratio`
ficou "quase 100% nulo num trimestre específico". As três são da mesma família
de dados (endpoints de posicionamento/funding da Binance), notoriamente
irregulares em histórico.

| # | Pergunta | Onde olhar | Interpretação pré-registrada |
|---|---|---|---|
| **F1** | Taxa de nulos de `E16f_global_ls_ratio` e `E05f_time_to_funding_h`, por fold, por combo. | audit de feature da Fase 2 (já construído: "mean/std/percentis por coluna") | Se as 2 features SHAP-dominantes têm cobertura ruim em folds específicos, os folds degenerados são **artefato de disponibilidade de dado**, não de ausência de sinal. Cruzar diretamente com a lista de folds degenerados. |
| **F2** | Como nulos são tratados — LightGBM nativo (`use_missing`), imputação, ou drop de linha? | pipeline de features | Imputação por média global = vazamento leve + `confidence` achatada nos períodos de cobertura ruim. |
| **F3** | Taxa-base do label positivo por fold, por lado. | audit de label da Fase 2 (já construído: "distribuição ternária/binária") | Se a taxa-base oscila muito entre folds e o `tau` é absoluto (ver B3), o colapso de sinalização é mecanicamente explicado pelo drift de taxa-base — sem qualquer perda de alpha. |
| **F4** | O label é recomputado por fold, ou pré-computado uma vez sobre o histórico inteiro? Se usa barreiras em ATR, o ATR é calculado com janela causal? | construtor de label | Pré-computado com estatística global = vazamento. |
| **F5** | `is_unbalance` / `scale_pos_weight` está ativo? É recalculado por fold? | params LightGBM | Se recalculado por fold, muda a escala de saída do `predict_proba` fold a fold — e um `tau` absoluto (B3) quebra por construção. |

---

## Bloco G — Fórmulas exatas (para poder recomputar de fora)

| # | Pergunta | Onde olhar |
|---|---|---|
| **G1** | Fórmula do "Edge líq." — inclui taxa, slippage e funding? Qual `bps` de custo por lado? | `constants.yaml`, modelo de custo |
| **G2** | O modelo de custo é constante ao longo de 2022-2026, ou usa spread/funding realizados do período? | idem |
| **G3** | AUC por fold é calculado sobre quais observações — todas as barras, ou só as que cruzaram `tau`? | `score_quality.py` |
| **G4** | Se for só acima de `tau` (o que o `n` pequeno sugere), o AUC está sendo medido num subconjunto **selecionado pelo próprio modelo** — restrição de amplitude que comprime o AUC em direção a 0,5 por construção. Confirmar. | idem |
| **G5** | O IC de Spearman é calculado sobre `confidence` vs. retorno realizado de trades filtrados, ou vs. retorno forward de todas as barras? | `score_quality.py` |

> **G3/G4 são potencialmente decisivas.** Se o AUC out-of-time é medido apenas
> sobre os trades que o modelo já selecionou (confidence > tau), o AUC ≈ 0,50
> é o resultado **esperado mesmo com alpha perfeito** — dentro do grupo
> selecionado, a variação residual de confidence é pequena e quase toda
> informação já foi consumida pelo filtro. Nesse caso o gate Model não mede
> poder discriminativo: mede a informação *marginal* remanescente acima do
> corte. Seria um erro de desenho mais grave que qualquer um da Seção 12.

---

## Bloco H — Desenho de fold e uma inconsistência factual no documento

| # | Pergunta | Onde olhar | Interpretação pré-registrada |
|---|---|---|---|
| **H1** | A Seção 5.1 afirma "1º trimestre testado (todos os combos) = 2023-10-01". Mas 19 folds trimestrais terminando em 2026-Q3 começam em **2022-Q1**, e o texto da mesma seção diz que BTC cobre "~4,6 anos de teste" (= 2022-01). Qual é o primeiro trimestre de teste real de `BTCUSDT/R2`? | JSON, `fold_id=0`, campo de data | Se for 2022-01, a linha da tabela 5.1 está errada e BTC/SOL/XRP **não** compartilham janela de teste — o que muda a análise de correlação transversal (R8) e a comparabilidade entre combos. |
| **H2** | SOL/XRP têm dado desde 2021-12-08; +2 anos = 2023-12-08. Mas o 1º fold de teste é 2023-10-01, ~2 meses antes. O `initial_train_years=2` foi respeitado, ou o fold 0 treina com ~1,81 anos? | splitter | Se não respeitado, o fold 0 de 4 dos 5 combos tem treino menor que o especificado. |
| **H3** | Há embargo/purga entre o fim do treino e o início do teste de cada fold? De quanto? | splitter | **Sem embargo** com features de janela 48-96 barras = vazamento na borda de cada fold, viés otimista. **Com embargo grande** = mais barras perdidas por fold, agravando a escassez de trades. |
| **H4** | O passo é trimestre civil fixo. Foi testado algum outro passo (semestral, ou por contagem de trades)? | commits, `constants.yaml` | Se nunca testado, o "0/20" nunca foi verificado quanto à sensibilidade à única dimensão que o determina (ver R3). |

---

## Bloco I — A ablação C0 vs C1

`XRPUSDT/R3` inverte completamente: C0 dá +26,34bps / Sharpe 1,503 e C1 dá
-34,54bps / Sharpe -5,322. O documento passa por isso sem comentar.

| # | Pergunta | Onde olhar | Interpretação pré-registrada |
|---|---|---|---|
| **I1** | Quais features têm restrição monotônica em C0, e em que direção (+1/-1)? Quem definiu e com que justificativa? | `monotonic.py`, `constants.yaml` | Se as restrições são economicamente fundamentadas e C0 vence em algum combo com folga, isso é evidência de que **C1 sobreajusta e a regularização estrutural funciona** — um achado acionável que a ADR-008 não extraiu. |
| **I2** | Em quantos dos 10 combo×camada C0 supera C1 em edge walk-forward? | Seção 5.4 (já dá: 1 de 5 claramente, `XRPUSDT/R3`) + JSON | Confirmar com números por fold. Se C0 > C1 de forma consistente em folds individuais, a recomendação muda de "podar tudo" para "promover C0". |
| **I3** | `SOLUSDT/R2` C1 e C0 são numericamente idênticos em todas as colunas. Confirmar no JSON que os dois runs produziram o MESMO array de predições (hash), e não apenas as mesmas métricas agregadas. | JSON, ou hash das predições | Se as predições são idênticas bit a bit, a "restrição monotônica" não teve efeito nenhum nesse combo — possível bug de aplicação da restrição, e 2 das 20 linhas são duplicatas confirmadas. |

---

## Bloco J — Reprodutibilidade das correções da Seção 12

| # | Pergunta | Onde olhar | Interpretação pré-registrada |
|---|---|---|---|
| **J1** | O que exatamente foi "re-rodado contra os 10 combo×variant" após o commit `e812ab1`? Só a avaliação dos gates sobre os JSONs antigos, ou o recálculo de `score_quality`? | commit `e812ab1`, script de re-execução | A Seção 12 afirma as duas coisas em parágrafos consecutivos. Precisa de uma resposta única. |
| **J2** | Quantos fold×lado seriam ELIMINADOS pelo novo piso `n≥5` de `score_quality.py`? | rodar o filtro sobre os JSONs existentes — não exige retreino | Este é o cálculo mais barato de todo o protocolo e resolve R7 sozinho. Se elimina folds, os `n` da coluna "OOS folds" caem, os `n` do teste-t caem, e o MDE de R1 **sobe** — o gate fica ainda mais inatingível. |
| **J3** | As 5 linhas com `AUC=0,500` exato: quantos trades tinham? | JSON | Se `n_trades ∈ {2,3,4}`, são o bug de degeneração confirmado da Seção 12.1, e não "confidence constante" como o documento interpreta. |
| **J4** | O `apply_fdr_to_model_gates` novo foi aplicado no cálculo do "0/20" final, ou só existe no código? | `walk_forward_gates.py` + resultado | Se aplicado, o gate Model ficou ainda mais conservador **depois** de já ter poder de 8% — o que amplifica R2 em vez de corrigir nada. |

---

## Bloco K — O experimento de calibração de falso-negativo (R6)

| # | Pergunta | Onde olhar |
|---|---|---|
| **K1** | Existe no repo qualquer teste que injete sinal sintético e verifique que o stack Data∧Model∧Alpha o APROVA? | testes da Fase 6 |
| **K2** | Os 9 testes novos do commit `e812ab1` e os 131+ da ADR-008 testam corretude de implementação, ou também poder de detecção? | suíte de testes |
| **K3** | Qual o custo real (em segundos e em `n_lifetime`) de rodar a Fase 4 com um alvo sintético de AUC conhecido? | `walk_forward.py` |

> Se K1 = "não existe", então o ADR-007 calibrou o falso-positivo do seu gate
> (Item 3) e o ADR-008 não calibrou nada do seu — assimetria de rigor
> documentada, e o "0/20" perde o status de evidência até K3 ser executado.

---

## Prioridade, se houver tempo para responder só uma parte

| Ordem | Perguntas | Por quê |
|---:|---|---|
| 1 | **A1, B1, B4** | Decidem se "0/20" é uma medição ou um artefato de seed única + `tau` desalinhado. Três perguntas, três olhadas no código. |
| 2 | **G3, G4** | Se o AUC é medido só acima de `tau`, o gate Model é conceitualmente inválido, não apenas fraco. |
| 3 | **J2, J3** | Custo ≈ zero, resolvem R7 e podem mudar os `n` de todas as 20 linhas. |
| 4 | **C1, C2, C3** | Permitem recomputar tudo com peso por trade e produzir os erros-padrão que faltam. |
| 5 | **E1, E2** ⚑ | Podem derrubar minha refutação e endurecer o achado original. Perguntar mesmo assim. |

---

*Fim do protocolo. As perguntas marcadas ⚑ existem porque uma refutação que só
faz perguntas favoráveis a si mesma é advocacia, não auditoria.*

---

# Respostas verificadas contra o código de produção (2026-08-31)

**Método:** 5 agentes independentes, cada um cobrindo um subconjunto dos blocos
(A+B, C+D, E+F, G+H, I+J+K), leram o código-fonte real, os 5 artefatos
`experiments/alpha_walk_forward_{BTCUSDT_R2,SOLUSDT_R2,SOLUSDT_R3,XRPUSDT_R2,
XRPUSDT_R3}.json`, `config/constants.yaml` e o histórico de commits nesta
sessão — sem reusar nenhuma conclusão de conversas anteriores. Nenhum `.py`
foi executado (proibido por regra do projeto); toda verificação é leitura
estática de código, JSON e `git log`/`git show`. Formato por pergunta:
resposta factual + citação (`arquivo:linha`, trecho literal, ou campo do
JSON/commit). Sem avaliação de gravidade — isso fica para quem interpretar.

## Bloco A — Seeds

**A1.** Uma seed por combo×camada. `run_walk_forward_for_combo` recebe
`seed: int` (escalar, não lista) — `src/models/walk_forward.py:288-303`.
Não existe `n_seeds`/`seeds` em `config/constants.yaml` associado a esta
campanha (a única constante `*_seeds` do arquivo é `alpha_b1_n_seeds`,
linha 3204, do bootstrap nulo do B1 — sem relação). `audit/n_lifetime.yaml:1195-1211`
(id=42, registro da própria campanha) confirma "10/10 runs sem falha" —
5 combos × 2 camadas × 1 seed = 10. Nenhum script chamador de
`run_walk_forward_for_combo` está commitado no repositório fora de
`tests/unit/test_models_walk_forward_driver.py` — a invocação real que
gerou os 5 JSONs não está sob controle de versão.

**A2.** Varia por fold e por lado, de forma determinística a partir de uma
única seed base (não é reamostragem estocástica). `src/models/alpha.py:2143-2148`
(chamada dentro de `run_fold`):
```python
long_result = fit_side_model(
    train_long, side=1, variant=variant, hyper=hyper,
    seed=_derived_seed(seed, split.split_id),
```
Dentro de `fit_side_model`, `src/models/alpha.py:1602`:
```python
random_state=_derived_seed(seed, side, 2),
```
Função de derivação, `src/models/alpha.py:362-370`:
```python
def _derived_seed(base_seed: int, *parts: int) -> int:
    seed = base_seed
    for i, p in enumerate(parts):
        seed = (seed * 1_000_003 + (p + 1) * (i + 7)) % 2_147_483_647
    return seed
```
`random_state` efetivo = `_derived_seed(_derived_seed(seed_base, fold_id), side, 2)`.

**A3.** Não. Grep de `"seed"` nos 5 artefatos: 0 ocorrências em todos.
Confirmado por listagem exaustiva de chaves JSON únicas em
`alpha_walk_forward_BTCUSDT_R2.json` e `alpha_walk_forward_SOLUSDT_R2.json`
(52 chaves distintas cada) — nenhuma se chama `seed`.
`config/constants.yaml:2957-2962` define `alpha_random_seed: 42`, mas como
o artefato não grava a seed usada, não há como comparar diretamente.

**A4.** As 10 (5 combos × 2 camadas) têm `feature_fraction` e `subsample`
(alias de `bagging_fraction` — `src/models/alpha.py:1580-1581`,1587)
abaixo de 1,0:

| combo | camada1 (feature_fraction / subsample) | camada0 (feature_fraction / subsample) |
|---|---|---|
| BTCUSDT/R2 | 0,6304 / 0,5583 | 0,7412 / 0,7806 |
| SOLUSDT/R2 | 0,8807 / 0,9951 | 0,8807 / 0,9951 |
| SOLUSDT/R3 | 0,8633 / 0,6286 | 0,7320 / 0,9082 |
| XRPUSDT/R2 | 0,9944 / 0,7127 | 0,7783 / 0,8043 |
| XRPUSDT/R3 | 0,8399 / 0,8534 | 0,3011 / 0,5541 |

Fonte: `config/constants.yaml:2706-2712` (`alpha_production_hyperparam_override`)
→ `experiments/alpha_optuna_confirmation_{symbol}_{resolution_id}_{run_stamp}.json`,
campo `camada{1,0}.winner.hyper`. `subsample_freq` também é inteiro positivo
nos 10 casos (3,4,5,5,8,8,8,9,9,9).

**A5.** Existe dispersão ENTRE FOLDS do mesmo combo (não entre seeds — só há
1 seed) para 3 métricas agregadas (`sharpe`, `edge_bps`, `win_rate`).
Exemplo real, `experiments/alpha_walk_forward_BTCUSDT_R2.json:1-30`
(`camada0.aggregate`):
```json
"aggregate": {
  "max":    {"edge_bps": 13.448913264727155, "sharpe": 4.518149666089495, "win_rate": 0.6666666666666666},
  "mean":   {"edge_bps": 1.3479886487053636, "sharpe": 0.38034154746811893, "win_rate": 0.5542257839392682},
  "median": {"edge_bps": -1.7389817947493431, "sharpe": -0.7737585125591139, "win_rate": 0.5645161290322581},
  "min":    {"edge_bps": -13.15563725896173, "sharpe": -2.5576106738472184, "win_rate": 0.38095238095238093},
  "std":    {"edge_bps": 10.303233603014206, "sharpe": 2.5174993024194525, "win_rate": 0.10375700440559973}
}
```
Um `fold_result` completo (`experiments/alpha_walk_forward_BTCUSDT_R2.json:210-346`)
contém: `degenerado`, `edge_bps`, `fold_id`, `gain_by_column_by_side`,
`n_filled_trades`, `n_purged`, `n_signals`, `n_test_bars`, `n_train_bars`,
`score_quality_by_side` (`brier_score`, `ic_ir`, `ic_tstat`, `log_loss`,
`n_folds_com_ic`, `n_trades`, `pct_ic_positive`, `pearson_ic`, `pr_auc`,
`roc_auc`, `spearman_ic_mean/median/std_por_fold`, `q10_minus_q1_bps`),
`decile_profile_by_side`, `shap_mean_abs_by_side`, `sharpe`,
`test_start/end`, `train_start/end`, `win_rate`. Não há `confidence`,
`tau`, nem `seed` nesse objeto.

O campo `n_train_bars` (2 lados somados, pré-filtro por lado) é o nome
usado nos 5 artefatos. O código atual de `src/models/walk_forward.py:225-250`
já renomeou esse campo para `n_train_rows_candidatas` e adicionou
`n_train_long`/`n_train_short` — mudança posterior à última regeneração dos
5 artefatos (parados no commit `5ca3500`; o rename aparece só no commit
`e812ab1`). Os artefatos analisados não têm `n_train_long`/`n_train_short`.

## Bloco B — tau e calibração

**B1.** Recalculado dentro de cada fold, a partir do split de calibração
daquele fold — nunca carregado de `constants.yaml`/artefato de produção.
Cadeia: `run_walk_forward_for_combo` (`walk_forward.py:403-417`) → `alpha.run_fold`
por fold → `fit_side_model` por lado (`alpha.py:2143-2165` long,
`2166-2188` short) → dentro de `fit_side_model`, `src/models/alpha.py:1685`:
```python
tau = float(np.quantile(calibrated_train_all, 1.0 - target_signal_rate))
```
`calibrated_train_all` (linha 1684) vem de `calibrator.predict(raw_train_all)`;
`raw_train_all` (linha 1683) vem de `model.predict_proba(X_all)`; `X_all`
(linha 1362) é `build_design_matrix(train_side_df, ...)` — subconjunto de
TREINO do fold. De volta em `run_fold`, linha 2196: `tau_long, tau_short =
long_result.tau, short_result.tau`. Cada fold tem seu próprio `tau`.

**B2.** Isotônica (`sklearn.isotonic.IsotonicRegression`), refeita do zero
a cada fold e a cada lado — sem cache/reuso entre folds.
`src/models/alpha.py:48` (import), `1675`:
```python
calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
calibrator.fit(raw_calib, y_calib, sample_weight=w_calib_iso)
```
Instanciado localmente dentro de `fit_side_model`, chamada 1 vez por lado
por fold (linhas 2143 e 2166).

**B3.** Quantil (`tau = quantile(1 - target_signal_rate)`) sobre
`calibrated_train_all` — TODO o treino do fold (fit+calib), não só o
sub-bloco `calib`. `target_signal_rate` (0,0189) é constante fixa global
(`config/constants.yaml:755-762`) — o quantil-ALVO é fixo, mas o VALOR de
`tau` resultante muda por fold/lado porque a distribuição calibrada de
scores muda a cada fold. Fonte: `src/models/alpha.py:1685` (B1);
`target_signal_rate` chega via `run_fold:2130`:
`target_signal_rate = float(load_constant("target_signal_rate"))`.

**B4.** Não existe. Grep de `"confidence"` em
`experiments/alpha_walk_forward_SOLUSDT_R2.json` (e nos outros 4): 0
ocorrências. `run_fold` calcula `confidence = np.maximum(p_long, p_short)`
por linha de teste (`alpha.py:2224`) e inclui na coluna
`predictions["confidence"]` do `FoldResult` (`alpha.py:2316`) em memória —
mas `run_walk_forward_for_combo` nunca persiste `fold_result.predictions`
no JSON de saída; usa só como insumo intermediário para
`score_quality.compute_score_quality`/`compute_decile_profile`
(`walk_forward.py:437,442`).

Os 8 folds reais de `SOLUSDT/R2` com `n_signals=0` (idênticos em
camada1/camada0, mesmos splits temporais):

| n_test_bars | n_train_bars | n_purged | score_quality_by_side |
|---:|---:|---:|---|
| 2720 | 66608 | 2 | `{}` |
| 2069 | 86487 | 2 | `{}` |
| 2204 | 103261 | 0 | `{}` |
| 2297 | 112081 | 2 | `{}` |
| 2068 | 121391 | 0 | `{}` |
| 2166 | 129703 | 4 | `{}` |
| 2113 | 154827 | 12 | `{}` |
| 752 | 163339 | 8 | `{}` |

Todos com `n_filled_trades: 0`. Não há campo no artefato que permita
comparar `confidence` realizada contra o `tau` daquele fold.

**B5.** Cresce — proporcional (`holdout_frac` fixo em 0,25, `n` crescente).
`src/models/alpha.py:475-497` (`_temporal_purged_calib_split`):
```python
n = int(t0_ms.shape[0])
...
n_calib = round(n * holdout_frac)
n_calib = max(1, min(n_calib, n - 1))
```
`holdout_frac = alpha_calibration_holdout_frac = 0,25`
(`config/constants.yaml:2913-2919`). Essa função é a ativa no
walk-forward porque `run_walk_forward_for_combo` usa
`calib_split_mode: str = alpha.CALIB_SPLIT_TEMPORAL_PURGED` como default
(`walk_forward.py:298`) — split temporal puro (bloco contíguo final por
`t0`), sem dependência de seed.

A contagem exata de linhas do split `calib` por lado (pós-`side_subset`)
não é persistida em nenhum artefato nem log. O que o artefato mostra é o
total candidato de treino (2 lados somados, pré-filtro por lado):
`experiments/alpha_walk_forward_BTCUSDT_R2.json` fold_id=0 (linha 63):
`n_train_bars: 66015`; fold_id=18, último fold (linha 2981):
`n_train_bars: 217187`.

**B6.** Não, no caminho que a campanha real usa. `run_walk_forward_for_combo`
usa `tau_policy: str = alpha.TAU_POLICY_LEGACY_PER_SIDE` como default
(`walk_forward.py:297`); nenhum chamador de produção commitado sobrescreve
isso. Sob essa política, `run_fold` (`alpha.py:2196`) usa diretamente
`long_result.tau`/`short_result.tau`, calculados exclusivamente sobre
`train_side_df` (linhas 1362, 1683-1685), que vem de
`train_bars = df_all[split.train_idx]` (`alpha.py:2118`), e `split.train_idx`
é produzido por `walk_forward_split_to_cpcv_split` (`walk_forward.py:79-131`)
com purge explícito por `t1` contra o início do bloco de teste (linhas
111-119). Existe um caminho alternativo no código
(`TAU_POLICY_TOTAL_COMMON_OOF`, `alpha.py:2198-2205`, chama
`_resolve_tau_on_common_bars`), mas ele também recebe `train_bars`, não
`test_bars`, como entrada de fit.

## Bloco C — Agregação e ponderação

**C1.** Média simples (`np.mean`), não ponderada por trades.
`src/models/walk_forward.py:170-190` (`_aggregate_stats`) e `:512-519`:
```python
"mean": float(np.mean(finite)),                                                # 185
usaveis = [fm for fm in fold_metrics if not fm.degenerado]                     # 513
stat_lists = {name: [getattr(fm, name) for fm in usaveis] for name in _AGGREGATE_STAT_NAMES}  # 514
per_stat = {name: _aggregate_stats(values) for name, values in stat_lists.items()}  # 515
```
`n_filled_trades` só é usado como critério de inclusão/exclusão
(degenerado ou não), nunca como peso na média.

**C2.** Sim — bate exatamente, nas 2 camadas. `SOLUSDT/R2`:
`n_folds_usados: 1` em `camada0` (linha 1801) e `camada1` (linha 3606),
único fold não-degenerado = `fold_id=3` nos 2 casos.
camada0: `aggregate.mean.edge_bps = -57.65648862489353` (linha 10) ==
`fold_results[fold_id=3].edge_bps = -57.65648862489353` (linha 515);
`aggregate.mean.sharpe = -4.076684015374146` (linha 11) ==
`fold_results[fold_id=3].sharpe` (linha 684). camada1: mesmos valores
exatos no `fold_id=3` (linhas 2320-2321, 2489).

**C3.** `n_filled_trades` por fold usado (não-degenerado). **O campo NÃO
existe separado por lado** — `FoldResult.predictions` carrega um único
`side_hat` por barra (`side_hat[is_long]=1; side_hat[is_short]=-1`,
mutuamente exclusivo, `alpha.py:613-630`), e
`backtest_lite.backtest_by_path` (`src/models/backtest_lite.py:219-263`)
agrupa por `path_id == fold_id` (não por lado) — `n_filled_trades` já é
contagem COMBINADA long+short daquele fold.

| Combo | Camada | n_folds_usados | fold_id → n_filled_trades |
|---|---|---:|---|
| BTCUSDT/R2 | camada0 | 7 | 1→21, 6→23, 8→37, 10→24, 12→18, 15→11, 18→62 |
| BTCUSDT/R2 | camada1 | 8 | 1→12, 4→18, 5→19, 8→39, 9→185, 10→62, 12→27, 13→41 |
| SOLUSDT/R2 | camada0 | 1 | 3→37 |
| SOLUSDT/R2 | camada1 | 1 | 3→37 |
| SOLUSDT/R3 | camada0 | 3 | 0→22, 4→13, 9→55 |
| SOLUSDT/R3 | camada1 | 4 | 0→27, 4→11, 5→79, 9→11 |
| XRPUSDT/R2 | camada0 | 4 | 0→43, 1→33, 4→200, 8→41 |
| XRPUSDT/R2 | camada1 | 6 | 1→33, 2→42, 3→35, 4→25, 5→53, 8→27 |
| XRPUSDT/R3 | camada0 | 6 | 0→10, 2→20, 4→10, 5→18, 8→27, 9→15 |
| XRPUSDT/R3 | camada1 | 4 | 1→101, 3→21, 4→34, 9→13 |

**C4.** Por FOLD, somando os 2 lados — não por lado separadamente.
`src/models/walk_forward.py:463-469`:
```python
n_filled_trades = path_result.n_filled_trades if path_result else 0
degenerado = n_filled_trades < min_trades
```
`path_result` vem de `backtest_lite.backtest_by_path`, 1 caminho por FOLD
(`path_id == wf_split.fold_id`). Como em C3, `side_hat` já é exclusivo por
barra — o piso `min_trades_for_non_degenerate_fold()=10` é aplicado sobre
o total combinado do fold.

**C5.** Por TRADE, anualizada pela frequência real observada.
`src/models/backtest_lite.py:47-61` (`sharpe_naive`):
```python
def sharpe_naive(trade_returns: FloatArray, *, span_seconds: float) -> tuple[float, float]:
    n = trade_returns.shape[0]
    if n < _MIN_TRADES_FOR_SHARPE or span_seconds <= 0.0:
        return float("nan"), float("nan")
    span_years = span_seconds / (DAYS_PER_YEAR * SECONDS_PER_DAY)
    trades_per_year = n / span_years if span_years > 0 else float("nan")
    mean = float(np.mean(trade_returns))
    std = float(np.std(trade_returns, ddof=1))
    if std == 0.0 or not np.isfinite(trades_per_year):
        return float("nan"), trades_per_year
    return mean / std * float(np.sqrt(trades_per_year)), trades_per_year
```
Piso é só `_MIN_TRADES_FOR_SHARPE = 2` (linha 44) e `std == 0.0` exato —
nenhum piso de proporção std/mean nem piso de contagem maior que 2.
`experiments/alpha_walk_forward_SOLUSDT_R2.json` linha 1531, `fold_id=9`,
`n_filled_trades=2` (linha 1428), `degenerado: true` (linha 1370) — 2
trades quase-idênticos produzem `std` perto de zero sem zerar, e
`mean/std` explode. O piso `min_trades_for_non_degenerate_fold()=10`
(`walk_forward.py:134-167`) é aplicado DEPOIS, na agregação — exclui esse
fold do `aggregate`, mas o valor pathológico continua gravado no
artefato, marcado `degenerado: true`.

## Bloco D — Hiperparâmetro vs. tamanho de treino

**D1.** Valor ABSOLUTO (contagem de linhas), não fração de `n_train`.
`src/models/alpha.py:226`: `min_child_samples: int` (campo tipado `int`).
`config/constants.yaml:2428-2434` (`alpha_lgbm_min_child_samples`):
`sweep_range: [10, 100]` — faixa de contagem absoluta. Valores reais por
combo: ver D2 (29 a 94).

**D2.** `lambda_l1` **não existe** no projeto — grep em `src/` inteiro só
encontra `lambda_l1` em 2 arquivos de `docs/`, nunca em código de
produção nem em `LGBMHyperparams` (`src/models/alpha.py:219-271`, que só
declara `lambda_l2`).

| Combo | run_stamp | Camada | num_leaves | min_child_samples | n_estimators | learning_rate | lambda_l2 |
|---|---|---|---:|---:|---:|---:|---:|
| BTCUSDT/R2 | 20260830T143204Z | camada1 | 4 | 29 | 787 | 0,02904190716480244 | 0,45416143071998777 |
| BTCUSDT/R2 | " | camada0 | 4 | 77 | 729 | 0,04091133234890739 | 0,2153323969880206 |
| SOLUSDT/R2 | 20260830T143204Z | camada1 | 22 | 77 | 540 | 0,02131114821993712 | 37,71371694516766 |
| SOLUSDT/R2 | " | camada0 | 22 | 77 | 540 | 0,02131114821993712 | 37,71371694516766 |
| XRPUSDT/R2 | 20260830T143204Z | camada1 | 22 | 94 | 597 | 0,04782027707436277 | 11,771805418088192 |
| XRPUSDT/R2 | " | camada0 | 6 | 52 | 721 | 0,0360147834353049 | 1,1243715863270765 |
| XRPUSDT/R3 | 20260830T143204Z | camada1 | 5 | 42 | 103 | 0,057532041236250865 | 0,15843250684388685 |
| XRPUSDT/R3 | " | camada0 | 10 | 61 | 776 | 0,02904190716480243 | 14,976721371136712 |
| SOLUSDT/R3 | 20260831T024607Z | camada1 | 18 | 71 | 391 | 0,01772937250809802 | 9,304526873468204 |
| SOLUSDT/R3 | " | camada0 | 32 | 77 | 441 | 0,08391674662592284 | 5,0744782214796444 |

`SOLUSDT/R2` camada0 e camada1 têm o MESMO `winner.hyper` (linhas 29-39 e
162-172 do JSON idênticas).

**D3.** `n_estimators` é TETO, não fixo — early stopping (`three_way`)
decide a contagem real por fold. Default de produção:
`early_stopping_mode: str = EARLY_STOPPING_THREE_WAY`
(`src/models/alpha.py:270`), confirmado no artefato de confirmação
(`"early_stopping_mode": "three_way"` em todo `winner.hyper`).
`src/models/alpha.py:1644-1666`:
```python
# `n_estimators` de `hyper` vira TETO de iterações, não contagem exata --
# `LGBMClassifier.predict_proba` já usa `best_iteration_` automaticamente
# quando o early stopping disparou
...
if early_stopping_mode == EARLY_STOPPING_THREE_WAY:
    stopping_rounds = int(load_constant("alpha_early_stopping_rounds"))
    fit_kwargs["eval_X"] = X_stop
    fit_kwargs["eval_y"] = y_stop
    fit_kwargs["eval_sample_weight"] = [w_stop]
    fit_kwargs["callbacks"] = [lgb.early_stopping(stopping_rounds=stopping_rounds, verbose=False)]
```
Contagem real fica em `model.best_iteration_`, capturada em
`SideModelResult.best_iteration` (`alpha.py:1762-1766`).

**D4.** Não existe no JSON de walk-forward. Grep de `"best_iteration"` nos
5 artefatos: 0 ocorrências em todos. `WalkForwardFoldMetrics`
(`src/models/walk_forward.py:218-272`, o dataclass serializado) não tem
`best_iteration` nem `n_train_long`/`n_train_short`/`n_train_rows_candidatas`
— só `n_train_bars` (nome antigo; ver nota em A5). `SideModelResult.best_iteration`
existe no código (`alpha.py:1170`) mas nunca é propagado para
`WalkForwardFoldMetrics`/o JSON.

**D5.** Calendário (trimestre civil), não contagem de barras.
`src/validation/volatility_walkforward.py:84-93`
(`generate_anchored_walk_forward_splits`):
```python
dates = pl.from_epoch(pl.Series(open_time_ms), time_unit="ms").dt.date()
period = (dates.dt.year() * 4 + dates.dt.quarter()).to_numpy()
unique_periods = np.unique(period)
n_initial_periods = initial_train_years * 4
```
`n_initial_periods` é `initial_train_years * 4` trimestres civis, nunca
contagem de barras. Barras de treino (`n_train_bars`, 2 lados somados,
pré-filtro por lado) do `fold_id=0`:

| Combo | train_start | train_end | n_train_bars (fold_id=0) |
|---|---|---|---:|
| BTCUSDT/R2 | 2020-01-07T01:33:16 | 2021-12-31T23:45:47 | 66015 |
| SOLUSDT/R2 | 2021-12-08T20:57:16 | 2023-09-30T23:41:54 | 66608 |
| SOLUSDT/R3 | 2021-12-09T20:31:49 | 2023-09-30T22:56:19 | 33281 |
| XRPUSDT/R2 | 2021-12-08T13:39:16 | 2023-09-30T23:41:48 | 69273 |
| XRPUSDT/R3 | 2021-12-08T20:01:13 | 2023-09-30T23:41:48 | 34176 |

`n_train_long`/`n_train_short` (contagem real por lado) não existem
nesses artefatos (ver D4).

## Bloco E — Contaminação do hiperparâmetro

**E1.** A busca Optuna (ADR-007 Itens 1-2) usa o histórico de dado
INTEIRO disponível, sem restrição de data — os mesmos anos (2022-2026)
que o walk-forward trata como fora-da-amostra estão DENTRO do dado que a
busca de hiperparâmetro viu. `src/models/hyperparams_optuna.py:299-307`
(`build_search_frame` chama `ds.build_modeling_frame(symbol=symbol,
tf="15m", resolution_id=resolution_id, vol_estimator_id=vol_estimator_id_effective,
t0_start=None, t0_end=None, extra_feature_ids=extra_feature_ids)`).
`src/models/dataset.py:285-286`: "Janela `None`/`None` (default) preserva
o comportamento anterior byte a byte" — sem filtro, histórico completo.
Nenhuma restrição de data em `src/validation/cpcv.py` (grep por
`t0_start|t0_end|date_bounds|cutoff_date` = 0 ocorrências). Confirmação
empírica: `experiments/alpha_walk_forward_BTCUSDT_R2.json` mostra
`train_start` fixo em `"2020-01-07T01:33:16.134000+00:00"` em TODOS os 19
folds e `test_end` chegando a `"2026-08-07T18:14:11.886000+00:00"` — a
mesma fonte de dado (`ds.build_modeling_frame`, mesmo `labels.parquet`)
que a busca Optuna consome sem corte de data.

**E2.** Depende da etapa. Seleção de feature (monotone screen),
calibração isotônica e balanceamento de classe são recalculados por
fold, usando só o treino daquele fold: `src/models/alpha.py:2118`
(`train_bars = df_all[split.train_idx]`), `:2126-2129`
(`train_long`/`train_short` via `ds.side_subset`), `:1181-1221`
(`compute_monotone_screen` recebe `train_side_df` como argumento, sem
estado global), `:1679` (`calibrator.fit(raw_calib, y_calib, ...)`),
`:1463-1472` (`scale_pos_weight` de `y_fit` local ao fold). Em
`src/models/walk_forward.py:403-417`, `alpha.run_fold` é chamado sem
`monotone_screen_override_by_side`, então cada fold recalcula sua própria
seleção de feature do zero.

Os VALORES BRUTOS das features (`E16f_global_ls_ratio` etc.) são
computados UMA VEZ sobre o frame inteiro (`ds.build_modeling_frame` →
`features_build.build_t1_features`), antes de qualquer split existir; o
walk-forward só fatia esse frame já pronto por `train_idx`/`test_idx`.
Essas features usam janelas rolling/expanding causais (ex.
`B09_zscore_close_48`, `src/features/build.py:1030`, janela de 48
barras), não normalização global fixa. Nenhum `mean()`/`std()` global
(não-rolling) aplicado a features de treino foi encontrado em
`src/features/build.py`.

**E3.** Os artefatos de resultado da Fase 4 foram gerados e commitados
ANTES das constantes de gate assumirem seus valores atuais. Hashes/datas
reais (`git log`):
- `experiments/alpha_walk_forward_*.json`, primeiro commit
  (`--diff-filter=A`): `c836435` | **2026-08-31 16:05:03 -0300** |
  "ADR-008 Fase 4: campanha real de walk-forward nos 5 candidatos
  (n_lifetime id=42)". Regenerado depois em `5ca3500` | 2026-08-31
  17:16:20 -0300 (Fase 7, campo SHAP, mesma numeração de resultado).
- `config/constants.yaml`:
  - `a821801` | 2026-08-31 16:46:51 -0300 — introduz os gates com
    nomes/valores `ASSUMED` originais: `alpha_gate_data_min_frac_folds_usados=0.5`,
    `alpha_gate_model_min_auc=0.52` (`git show a821801:config/constants.yaml`).
  - `42a859f` | 2026-08-31 18:34:51 -0300 — substitui pelos nomes/valores
    atuais: `alpha_gate_data_min_folds_usados=10` (DERIVED),
    `alpha_gate_model_significance_level=0.05` (LITERATURE)
    (`git show 42a859f:config/constants.yaml`).
  - `d2ca606` | 2026-08-31 19:45:10 -0300 — trava final (mesmos valores
    10/0,05, documentação de sweep ±50%+, `review_by: "2026-08-31 --
    decidido"`).

Ordem: resultados do walk-forward existiram primeiro (16:05); o primeiro
código de gate com thresholds `ASSUMED` veio depois (16:46); os valores
atuais (10/0,05) foram fixados às 18:34 — ~2h30 depois dos resultados
existirem; trava final às 19:45. A mensagem do commit `d2ca606` declara a
metodologia usada nesse intervalo: sweep de sensibilidade rodado "contra
os 10 combo × variant reais" em grade `min_folds∈{5,8,10,15,20} ×
significance_level∈{0,01;0,025;0,05;0,075;0,10}`, concluindo veredito
composto 0/10 em toda a grade testada.

## Bloco F — Cobertura de feature e distribuição de label por fold

**F1.** Existe artefato de nulos por coluna
(`experiments/feature_null_census.json`, `src/analysis/feature_null_census.py`),
mas SEM granularidade por fold — é por célula (symbol × resolution_id)
sobre o histórico inteiro. Valores medidos:
- `E16f_global_ls_ratio`: BTCUSDT/R1 `frac_null=0,1166`, BTCUSDT/R2
  `0,1127`, BTCUSDT/R3 `0,1114` — mais alto que os outros 4 símbolos
  (~0,010-0,018 em todas as resoluções, ex. XRPUSDT/R2 `0,0113`,
  SOLUSDT/R3 `0,0164`).
- `E05f_time_to_funding_h`: uniformemente baixo em todos os 15 combos,
  `n_null=200` fixo (warmup) em cada célula, `frac_null` entre 0,0009
  (BTCUSDT/R1) e 0,0050 (várias R3).

Este artefato foi commitado em `048af80` | 2026-08-26 15:53:47 -0300 —
antes da promoção do vetor `T1_FEATURE_IDS` atual (`AG-372`, 2026-08-28,
ambas as 2 colunas pedidas estão nesse vetor, `src/features/build.py:132,137`)
e antes da campanha walk-forward (2026-08-31). Não foi regenerado depois.
Não foi possível cruzar com a lista de folds degenerados da Seção 5.4 do
`docs/AUDITORIA_EXTERNA_run_canonico_e_adr008_fases_0-8_2026-08-31.md` —
os dois artefatos usam granularidades incompatíveis (um por célula sobre
histórico inteiro, outro por fold trimestral); não existe artefato que
combine as duas dimensões.

**F2.** Descarta a linha inteira (complete-case) quando qualquer feature
do vetor ativo é nula — não usa suporte nativo de missing do LightGBM
(`use_missing`) nem faz imputação. Grep de `use_missing`/`fill_null` em
`src/models/alpha.py`/`src/models/dataset.py`: 0 ocorrências para ambos.
`src/models/dataset.py:760-762` (dentro de `side_subset`, usado por todo
caminho de treino):
```python
for fid in feature_ids:
    out = out.filter(pl.col(fid).is_not_null())
```
Equivalente no lado de teste/inferência, `src/models/alpha.py:1832-1836`
(`unique_test_bars`):
```python
out = test_bars_all_sides.filter(
    (pl.col("side") == 1) & pl.col(feature_ids[0]).is_not_null()
)
for fid in feature_ids[1:]:
    out = out.filter(pl.col(fid).is_not_null())
```
`src/models/dataset.py:742-759` levanta `DeadFeatureColumnError` se uma
coluna estiver 100% nula naquele lado, antes do filtro.

**F3.** Não existe artefato persistido com taxa-base do label positivo
por fold. O módulo `src/analysis/label_audit.py` (Fase 2) calcula esse
número (`LabelDistributionStats.frac_positive`, `label==1` vs. resto) mas
é "núcleo puro, sem IO" — a função `compute_label_distribution_stats` só
é referenciada no próprio módulo e em seu teste unitário; nenhum
CLI/writer a chama contra dado real, nenhum `experiments/*.json` tem esse
conteúdo. O mais próximo disponível é `win_rate` por fold no walk-forward
(`fold_results[i].win_rate`), mas isso é taxa de acerto de TRADES
REALIZADOS (`ret_net>0`, população pós-`confidence>tau`+fill) — diferente
e muito menor que a taxa-base do label de treino (todas as linhas de
treino, antes de qualquer filtro de sinal/tau). Os dois números não são
intercambiáveis; o artefato de walk-forward não reporta o segundo.

**F4.** O label é pré-computado UMA VEZ sobre o histórico inteiro e
gravado em parquet; o walk-forward só fatia esse artefato por índice de
fold, nunca recomputa `triple_barrier`/labels por fold.
`src/validation/cpcv.py:868-882` (`load_labels_v1`) lê diretamente
`data/labels/{symbol}/{resolution_id}/{version}/labels.parquet` do disco.
`src/models/walk_forward.py:304-308` (docstring de
`run_walk_forward_for_combo`): `mf_data` (que carrega esse
`labels.parquet` via `build_modeling_frame`) "fica FORA desta função de
propósito, pra ser chamado 1 vez só" — o walk-forward recebe o frame já
pronto e só aplica `walk_forward_split_to_cpcv_split` para gerar
`train_idx`/`test_idx` sobre esse mesmo frame. O ATR usado na barreira
(`src/labels/triple_barrier.py:81-82`, `ATRWilderEstimator`) é janela
rolling causal, não estatística global — cada barra usa só as N barras
anteriores. O purge de vazamento por `t1` é tratado em
`walk_forward_split_to_cpcv_split` (`walk_forward.py:111-119`).

**F5.** `is_unbalance` não é usado; `scale_pos_weight` está ativo e é
recalculado POR FOLD, POR LADO, a partir da população de treino daquele
fold — não é valor fixo. `src/models/alpha.py:1463-1472` (dentro de
`fit_side_model`, que recebe `train_side_df` = subconjunto do fold):
```python
n_pos = int(y_fit.sum())
n_neg = int(y_fit.shape[0] - n_pos)
scale_pos_weight_count = float(n_neg) / float(n_pos) if n_pos > 0 else 1.0
w_pos = float(w_fit[y_fit == 1].sum())
w_neg = float(w_fit[y_fit == 0].sum())
scale_pos_weight_weight = (w_neg / w_pos) if w_pos > 0.0 else 1.0
```
Passado ao LightGBM em `alpha.py:1601` (`scale_pos_weight=scale_pos_weight_param`).
O default de produção usado pelo walk-forward é
`class_balance_basis=alpha.CLASS_BALANCE_WEIGHT` (`walk_forward.py:298`)
— usa a razão `w_neg/w_pos` ponderada por `uniqueness`, não a contagem
simples — mas em ambos os casos o número vem de `y_fit`/`w_fit` daquele
fold, não de constante global nem de média entre folds.

## Bloco G — Fórmulas exatas

**G1.** `edge_bps = mean_trade_ret * 10_000` sobre os trades REALIZADOS
(não `NOFILL`) do fold. O custo é aplicado rio-acima, em
`src/labels/triple_barrier.py`, no momento de gerar o label:
- `ret_net = ret_gross - cost_entry_frac - cost_exit_frac - funding_frac`
  — `src/labels/triple_barrier.py:1663`.
- `cost_entry_frac = cfg.maker_fee`; `cost_exit_frac = cfg.maker_fee if
  barrier == "TP" else cfg.taker_fee` — `src/labels/triple_barrier.py:1654-1655`.
- Constantes: `maker_fee: value: 0.0002` (2bps), `provenance: MEASURED`,
  `source: "tabela de fees Binance USDⓈ-M, VIP 0"` —
  `config/constants.yaml:45-50`; `taker_fee: value: 0.0005` (5bps),
  mesma proveniência — `:52-57`. Custo por lado não é um único número:
  entrada sempre 2bps (maker/post-only); saída 2bps se TP, 5bps se
  SL/TIME.
- `adverse_selection_bps` é REPORTADO como coluna informativa mas
  explicitamente NÃO subtraído de `ret_net` — docstring literal:
  "`adverse_selection_bps` é reportado, NÃO subtraído de `ret_net`...
  Escolha conservadora: reportar o placeholder (`constants.yaml
  adverse_selection_bps`, classe A ASSUMED) como coluna informativa, não
  fabricar um desconto que a Label Engine não pode medir sozinha" —
  `src/labels/triple_barrier.py:46-51`.
- Funding: incluído (ver G2). Não há termo de spread aplicado em nenhum
  lugar de `triple_barrier.py` (busca por `"spread"` no arquivo: 0
  ocorrências).
- Em `backtest_lite.py`: só consome o `ret_net` já pronto —
  `rets = filled["ret_net"].to_numpy()...; mean_ret = float(np.mean(rets))`
  (`src/models/backtest_lite.py:236,238`); propagado a `edge_bps` em
  `src/models/walk_forward.py:485-487`.

**G2.** Misto entre as duas pernas: a taxa (`maker_fee`/`taker_fee`) é
CONSTANTE fixa (um único valor em `constants.yaml`, aplicado igual em
qualquer trade de 2022 a 2026 — não há tabela histórica de fee por
data). O funding é REALIZADO/histórico: soma dos eventos reais de
funding rate na janela `[t_entry, t1]` daquele trade:
```python
f_lo = np.searchsorted(fund_time, t_entry, side="left")
f_hi = np.searchsorted(fund_time, t1, side="right")
events_rate = fund_rate[f_lo:f_hi]
funding_frac = float(np.nansum(events_rate)) * side
```
— `src/labels/triple_barrier.py:1657-1661`, `fund_time`/`fund_rate`
vindos do DataFrame `funding` real passado à função (linha 1468-1470).

**G3.** O AUC é calculado SÓ sobre a população que já cruzou `tau`
(`side_hat != 0`), não sobre todas as barras de teste. Cadeia:
1. `predictions` (antes de filtro) tem 1 linha por barra única de teste —
   `n_rows = len(p_long)` (`alpha.py:2297`), `p_long`/`p_short` vêm de
   `predict_proba` sobre `test_bars_unique` (toda a população de teste).
2. `side_hat = decide_side(...)`, `confidence = np.maximum(p_long,
   p_short)` calculados para TODA essa população (`alpha.py:2223-2224`),
   persistidos em `predictions` (`alpha.py:2315-2316`).
3. `decide_side` só marca `side_hat != 0` quando `p > tau` do lado
   correspondente: `is_long = (p_long > tau_long) & (p_long > p_short);
   side_hat[is_long] = 1` — `alpha.py:625-629`.
4. `score_quality._join_oof_predictions_to_labels` filtra exatamente essa
   população: `predictions.filter(pl.col("is_oof") & (pl.col("side_hat")
   == side_value))` — `src/models/score_quality.py:260-264`. `side_value`
   percorre só `{1: "long", -1: "short"}` — nunca inclui `side_hat==0`.
5. `roc_auc_score(y_true, y_score)` roda sobre `joined` (resultado desse
   filtro): `auc, pr_auc, ll, brier = _classification_metrics(y_true,
   confidence)` — `score_quality.py:316`, onde `confidence`/`ret_net` vêm
   de `joined = _join_oof_predictions_to_labels(...)` (linhas 303,
   309-310).

**G4.** Sim. O filtro `side_hat == side_value` (que só existe onde
`confidence > tau`, ver G3 itens 3-4) já é aplicado ANTES do
`roc_auc_score` — a variância de `confidence` abaixo de `tau` nunca entra
na métrica. Linha que prova: `score_quality.py:260-264` (o filtro)
alimenta diretamente `score_quality.py:316` (`_classification_metrics`,
que chama `roc_auc_score`).

**G5.** Mesma população filtrada de G3/G4, não todas as barras de teste.
`spearman_pooled = _spearman_ic(confidence, ret_net)` —
`score_quality.py:318` — onde `confidence`/`ret_net` são extraídos de
`joined` (linha 309-310), o mesmo join filtrado por `side_hat ==
side_value` de G3. O IC por fold (linhas 322-329) também itera sobre
`joined`, não sobre a população total de barras.

## Bloco H — Desenho de fold e possível inconsistência factual

**H1.** A alegação do documento `docs/AUDITORIA_EXTERNA_run_canonico_e_adr008_fases_0-8_2026-08-31.md`
(Seção 5.1, tabela) de que "1º trimestre testado (todos os combos) =
2023-10-01" é factualmente incorreta para `BTCUSDT/R2`. Valor real:
```json
"test_start": "2022-01-01T00:14:06.268000+00:00"
```
— `experiments/alpha_walk_forward_BTCUSDT_R2.json:145` (`fold_id: 0`,
dentro de `camada0`). É ~2022-01-01, não 2023-10-01 — valor consistente
com "19 folds trimestrais, ~4,6 anos de teste, terminando em 2026-Q3",
que o mesmo documento afirma na sequência da mesma seção. `train_start`
do fold 0 de BTCUSDT/R2 = `"2020-01-07T01:33:16.134000+00:00"` (linha
147); `n_folds_total: 19` (linha 3090); último `test_end` (fold_id=18) =
`"2026-08-07T18:14:11.886000+00:00"` (linha 3081) — janela test_start→test_end
real ≈ 2022-01-01 a 2026-08-07 (~4,6 anos), batendo com o texto da seção,
não com a célula da tabela.

**H2.** Para os 4 combos restantes, `test_start` do `fold_id=0` é
2023-10-01 em todos:
- `experiments/alpha_walk_forward_SOLUSDT_R2.json:141` →
  `"test_start": "2023-10-01T00:07:42.521000+00:00"`, `train_start` do
  mesmo fold = `"2021-12-08T20:57:16.730000+00:00"` (linha 143)
- `experiments/alpha_walk_forward_SOLUSDT_R3.json:247` →
  `"test_start": "2023-10-01T00:07:42.521000+00:00"`
- `experiments/alpha_walk_forward_XRPUSDT_R2.json:299` →
  `"test_start": "2023-10-01T00:02:26.627000+00:00"`
- `experiments/alpha_walk_forward_XRPUSDT_R3.json:249` →
  `"test_start": "2023-10-01T00:41:36.023000+00:00"`

2023-10-01, não 2023-12-08 — a diferença de ~2 meses vem do splitter
alinhar o início do teste ao PRÓXIMO fechamento de trimestre civil após
`train_start + 2 anos` (`initial_train_years * 4` períodos civis,
`src/validation/volatility_walkforward.py:89-93`), não a uma contagem de
dias corridos a partir da data exata de início do histórico.

**H3.** Não existe embargo, além do purge por `t1` já documentado.
`n_embargoed=0` é literal, hardcoded, nunca calculado a partir de
constante nenhuma — `src/models/walk_forward.py:130`. Docstring confirma
que é deliberado: "walk-forward ancorado tem só 1 fronteira...
test_groups=(), train_groups=(), n_embargoed=0" (`walk_forward.py:36-41`).
O único filtro treino/teste é o purge por `t1` (linhas 111-113). O campo
`n_embargoed` é interno ao adaptador `CPCVSplit` e não é serializado no
schema de saída `WalkForwardFoldMetrics` — confirmado por busca de
`"n_embargoed"` nos 5 JSONs: 0 ocorrências.

**H4.** Não existe passo configurável em lugar nenhum — nem cogitado.
`generate_anchored_walk_forward_splits(open_time_ms, *,
initial_train_years)` (`src/validation/volatility_walkforward.py:61-63`)
não recebe parâmetro de passo; o trimestre é hardcoded (`period =
(dates.dt.year() * 4 + dates.dt.quarter()).to_numpy()`, linha 86). A
especificação original já fixava isso sem alternativa: "Protocolo:
walk-forward ancorado, treino inicial 2 anos, passo trimestral." —
`PRD_V4_1.md:370`, reiterado na docstring do código (`volatility_walkforward.py:64`).
Busca por menção de passo alternativo (semestral/mensal/por-contagem-de-trades)
em `docs/*.md`, `audit/architecture_gaps_log.yaml` e `git log` não
retornou ocorrência.

## Bloco I — A ablação C0 vs C1

**I1.** Só 1 feature tem restrição monotônica FIXA (forçada) em todo o
pipeline — as demais features T1 recebem `+1`/`-1`/`0` DINAMICAMENTE por
fold/lado, via IC de Spearman medido contra `ret_net` em 6 ambientes
(`screen_monotone_constraints`), não uma lista estática. A única entrada
forçada: `E27f_cost_atr_ratio: -1` (mesmo sinal nos dois lados) —
`src/models/monotonic.py:53`:
`_ECONOMIC_FORCED_CONSTRAINT: dict[str, int] = {"E27f_cost_atr_ratio": -1}`.
Justificativa no código (linhas 21-22): "custo alto nunca pode melhorar o
resultado esperado, MESMO sinal (-1) nos dois lados". Existe um segundo
mecanismo, `_ECONOMIC_FORCED_CONSTRAINT_BY_SIDE` (linha 72), vazio hoje
(`{}`) — a única entrada histórica (`E02f_funding_z_expanding`) "saiu do
conjunto ativo de treino, AG-032, 2026-08-23" (linhas 65-71).

**I2.** `aggregate.mean.edge_bps`/`sharpe` de C0 vs. C1, extraído dos 5
artefatos:

| combo | C0 edge_bps / sharpe | C1 edge_bps / sharpe | quem supera |
|---|---:|---:|---|
| BTCUSDT/R2 | 1,348 / 0,380 | 7,896 / 0,992 | C1 nos 2 |
| SOLUSDT/R2 | -57,656 / -4,077 | -57,656 / -4,077 | empate byte-idêntico |
| SOLUSDT/R3 | -32,822 / -3,657 | -16,997 / -0,924 | C1 nos 2 |
| XRPUSDT/R2 | -17,551 / -1,459 | -28,252 / -1,271 | misto: C0 em edge_bps, C1 em sharpe |
| XRPUSDT/R3 | 26,341 / 1,503 | -34,536 / -5,322 | C0 nos 2 |

C0 supera C1 nos 2 eixos em 1 de 5 combos (XRPUSDT/R3); 1 empate
(SOLUSDT/R2, ver I3); 1 caso misto (XRPUSDT/R2).

**I3.** Confirmado — para `SOLUSDT/R2`, `camada0` e `camada1` são
byte-idênticos em todo campo de resultado de trade (`edge_bps`,
`sharpe`, `win_rate`, `score_quality_by_side`, `decile_profile_by_side`,
`n_filled_trades`, `n_train_bars`, boundaries de fold), diferindo apenas
em `gain_by_column_by_side` e `shap_mean_abs_by_side`. Verificado por
diff linha-a-linha dos 2 blocos completos
(`experiments/alpha_walk_forward_SOLUSDT_R2.json` linhas 2-1804 vs.
1806-3609). A byte-identidade se repete nos 4 folds onde
`score_quality_by_side` existe em ambas as camadas (`fold_id` 1, 3, 8,
9). Não existe array/hash de predição bruta no artefato (grep por
`"*predictions*"`: 0 resultados). Este achado já está registrado em
`audit/architecture_gaps_log.yaml`, entrada `AG-393` item 3 (mais
restrito ali, só fold 3/short) — status "ABERTO... não corrigido ainda";
a verificação aqui mostra que a byte-identidade não se limita ao fold 3,
ocorre nos 4 folds com dado suficiente nesse combo.

## Bloco J — Reprodutibilidade das correções do commit `e812ab1`

**J1.** `git show e812ab1 --stat` mostra 10 arquivos tocados (5 `src` +
5 `tests`). A mensagem completa do commit (`git log e812ab1 -1
--format=%B`) resolve a pergunta:

> "Re-rodado contra os 10 combo x variant reais
> (rodar_gates_v2.py/montar_model_cards_v2.py, artefatos existentes em
> experiments/): 0/20 ... continua REPROVADO ... Nota importante: o fix
> de score_quality.py (piso n=5, sort deterministico) so afeta PROXIMOS
> retreinos -- os artefatos JSON reais em disco ja foram escritos pelo
> codigo ANTIGO, nao foram retreinados nesta rodada (fora do escopo de
> correcao de auditoria, exigiria nova campanha real)."

Confirma: só reavaliação dos 3 gates sobre os JSONs de walk-forward já
existentes — `score_quality` (incluindo o piso `n>=5`) não foi
recomputado. Corroborado por `docs/SPRINT_LOG.md:6183`: "Veredito final
não muda (0/20), mas fica mais rigoroso". Os scripts citados no commit
(`rodar_gates_v2.py`, `montar_model_cards_v2.py`) não existem no
repositório — nem no working tree atual, nem em nenhum commit do
histórico (`git log --all --diff-filter=A` para esses nomes: 0
resultados). A confirmação acima vem da prosa do commit + SPRINT_LOG, não
de leitura direta desses 2 scripts.

**J2.** Contando `n_trades` dentro de `score_quality_by_side` (todo
fold×lado com pelo menos 1 trade computado) nos 5 artefatos: **44 de
106** entradas têm `n_trades < 5` — seriam suprimidas (→NaN) pelo piso
`_MIN_OBS_FOR_SMALL_SAMPLE_METRICS=5` se reaplicado aos JSONs já
existentes:

| combo | camada0 (<5) | camada1 (<5) | total (<5) / total entradas |
|---|---:|---:|---|
| BTCUSDT/R2 | 3 | 7 | 10/32 |
| SOLUSDT/R2 | 4 | 4 | 8/10 |
| SOLUSDT/R3 | 4 | 11 | 15/25 |
| XRPUSDT/R2 | 3 | 3 | 6/21 |
| XRPUSDT/R3 | 4 | 1 | 5/18 |
| TOTAL | 18 | 26 | 44/106 |

**J3.** Ocorrências de `"roc_auc": 0.5,` exato (grep nos 5 JSONs) e o
`n_trades` correspondente no mesmo objeto `score_quality_by_side`:
- BTCUSDT_R2: n_trades = 20, 8, 10, 6, 11, 4, 18, 19, 3
- SOLUSDT_R2: n_trades = 36, 2, 36, 2
- SOLUSDT_R3: n_trades = 22, 13, 3, 7, 42, 13, 27, 11, 29, 50, 3
- XRPUSDT_R2: n_trades = 27, 16, 8, 3, 160, 35, 7
- XRPUSDT_R3: n_trades = 2, 25, 15, 9, 21, 34, 13

37 ocorrências totais — inclui `n_trades` pequenos (2, 3, 4) e grandes
(160, 50, 42, 36).

**J4.** `apply_fdr_to_model_gates` é definida em
`src/analysis/walk_forward_gates.py:258` e testada em
`tests/unit/test_analysis_walk_forward_gates.py` (3 testes), mas grep
por import/chamada em todo `src/**/*.py` mostra que nenhum outro arquivo
de produção a importa ou chama — `model_card.py:63` importa só
`GateVerdict` do mesmo módulo. O próprio módulo documenta isso,
`walk_forward_gates.py:73-76`: "`evaluate_gates` continua operando célula
a célula (é uma auditoria pós-hoc, sem caller de produção ainda,
AG-391), mas quem for consolidar um lote real deve usar
`apply_fdr_to_model_gates`, não o veredito bruto por célula." A função
existe mas não é chamada em nenhum lugar de produção — o veredito "0/20"
documentado foi computado célula-a-célula, sem correção FDR aplicada
sobre o lote.

## Bloco K — Calibração de falso-negativo

**K1.** Não existe teste que injete sinal sintético conhecido através do
pipeline de walk-forward e verifique que os 3 gates (Data ∧ Model ∧
Alpha) aprovam. Busca em `tests/unit/test_models_walk_forward*.py`,
`test_analysis_walk_forward_gates*.py`, `test_analysis_model_card*.py` —
todos usam valores fixados à mão (`_stability_result`,
`_walk_forward_payload`, `monkeypatch`), não sinal sintético com
correlação real conhecida. Existe teste de poder estatístico com sinal
sintético para um estágio DIFERENTE e anterior do pipeline —
`tests/unit/test_analysis_eixo1_power_diagnostic.py` +
`src/analysis/eixo1_power_diagnostic.py` (`AG-327`): constrói
`synthetic_correlated_series` com `rho_true` conhecido e verifica
`synthetic_is_discovered` sob o BH da triagem de features (Eixo 1), não
sob os 3 gates do walk-forward. Segundo
`audit/architecture_gaps_log.yaml:21894-21904` (AG-327, addendum
2026-08-26c), esse diagnóstico foi executado (100 sorteios MC × 7 pontos
de grade × 15 células), medindo poder de 98-100% de detecção para IC
pequeno — mas mede a etapa de seleção de feature, não os gates
Data/Model/Alpha do veredito "0/20".

**K2.** Os 23 testes de `tests/unit/test_analysis_walk_forward_gates.py`
(321 linhas) — todos categorizados como CORRETUDE, zero como PODER:
`test_data_gate_passa_acima_do_piso`, `test_data_gate_fronteira_exata_passa`,
`test_data_gate_falha_abaixo_do_piso`, `test_data_gate_zero_folds_usados_falha`,
`test_model_gate_nan_auc_mean_sempre_falha`, `test_model_gate_nan_auc_std_sempre_falha`,
`test_model_gate_menos_de_2_folds_sempre_falha`,
`test_model_gate_std_zero_sempre_falha_mesmo_com_media_acima_de_0_5`,
`test_model_gate_p_value_std_zero_e_nan_nao_zero_nem_um`,
`test_model_gate_p_value_menos_de_2_folds_e_nan`,
`test_model_gate_p_value_conferido_a_mao_contra_scipy_t_sf`,
`test_model_gate_conferido_a_mao_contra_scipy_t_ppf`,
`test_model_gate_conferido_a_mao_caso_que_deve_falhar`,
`test_model_gate_significance_level_maior_facilita_passagem`,
`test_alpha_gate_passa_com_edge_positivo`,
`test_alpha_gate_fronteira_exata_falha_comparacao_estrita`,
`test_alpha_gate_falha_com_edge_negativo`, `test_alpha_gate_nan_sempre_falha`,
`test_evaluate_gates_composicao_real_conferida_a_mao`,
`test_evaluate_gates_zero_folds_totais_frac_nan_data_gate_falha`,
`test_apply_fdr_to_model_gates_exclui_nan_da_familia`,
`test_apply_fdr_to_model_gates_p_valor_bruto_e_bilateral_2x_o_unicaudal`,
`test_apply_fdr_to_model_gates_lista_vazia_devolve_dict_vazio`. Docstring
do arquivo (linhas 1-6): "Núcleo puro (Idioma A): passa nos dois lados da
fronteira, falha em cada critério isoladamente, fronteira exata" — sem
menção a poder de detecção sob sinal real.

**K3.** Não foi encontrada estimativa de custo (segundos/`N_lifetime`) de
rodar a Fase 4 com alvo sintético de AUC conhecido, em `docs/`, `audit/`
ou comentário de `src/models/walk_forward.py`. Busca por
`custo|segundos|N_lifetime` em `walk_forward.py` retorna 3 ocorrências,
todas sobre custo de SHAP (linha 203: "0,005s — custo desprezível"), não
relacionadas a alvo sintético. A pergunta K3 está listada como pergunta
em aberto no próprio protocolo de origem (linha 177 deste documento) —
não existe resposta pré-existente no repositório.
