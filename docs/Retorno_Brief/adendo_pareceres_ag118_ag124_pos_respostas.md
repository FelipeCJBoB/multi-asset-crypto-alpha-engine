# Adendo aos pareceres AG-118/AG-122 e AG-124

**Data:** 2026-08-21
**Motivo:** revisão após as respostas do desenvolvedor (9 perguntas técnicas) e do manager (8 perguntas de governança).
**Efeito:** duas retratações, três achados confirmados com número, quatro achados novos, e uma correção de leitura que muda a recomendação sobre `cadence_days`.

---

## 1. O que eu retiro

**1.1 — O HMM não é in-sample. Retirado.**
`fit_fn(obs_2d, split.train_end_idx)` com corte interno em `obs[:train_end_idx]` é walk-forward genuíno, refit por fold. Minha hipótese de vazamento de fit para explicar o achado de R3 está morta, e ela era a explicação mais barata disponível.

O que sobra é diferente e mais fraco, mas não vazio: a comparação continua sendo entre um estimador que se readapta a cada fold e um de threshold fixo que não se readapta. Isso é uma comparação **de engenharia** justa — em produção você implantaria o adaptativo — mas não é evidência sobre qual dos dois *detecta regime* melhor. Para a decisão em pauta (qual promover), a justiça de engenharia é a que importa. Então esse ponto agora pesa **a favor** de k=4, não contra.

**1.2 — `_calibration_errors_for_window` está correto. Retirado.**
O passo por `window` implementa rolling walk-forward, cada bloco de aplicação virando o de calibração seguinte, e isso bate com `build_dollar_bars_walkforward`. A reprodução dos 41,67% continua válida. O defeito era só a prosa do §3 do brief, que descreve pares fixos. Correção de texto, não de código.

---

## 2. O que se confirma, agora com número

**2.1 — A tautologia do AG-118 está quantificada.**
`sl_atr_mult=1.5` significa que a barreira de stop fica em **−1,5 ATR**. Os valores medidos de `p05_return_atr` são −1,65 (stress) e −1,80 (não-stress).

Ou seja: o percentil 5 não mede risco de cauda. Mede **excursão além da barreira**, e mede pouca — 0,15 ATR no bucket de stress contra 0,30 ATR fora dele. O bucket "de risco elevado" tem **metade** do overshoot do resto.

Isso não é ambíguo: sob volatilidade genuinamente elevada você espera *mais* transposição da barreira, não menos. Menos overshoot com barreira larga é a assinatura de ATR em t0 acima da volatilidade realizada durante o trade — reversão à média. O mecanismo que eu propus como hipótese agora tem os dois números que faltavam.

**2.2 — O piso de p-valor está confirmado.** 1.000 permutações → menor p não-zero ≈ 0,000999. Todo `p=0,001` do §2.1 do AG-114 está no piso de resolução. Combinado com a ausência de intervalo no I², a escolha de k=4 sobre k=3 (97,4 vs 97,4 em R1) não se apoia em nenhuma quantidade medível.

**2.3 — Todo o programa de medição do AG-124 custa minutos, não horas.** Os JSONs de deriva guardam `total_dollar`/`n_days`/`dollar_per_day` por período bruto, então sweep de corte, preenchimento de grid e estratificação por dia-da-semana são reprocessamento de JSON. E os três `RawLabels` (k2/k3/k4) estão em disco, então rodar o AG-118 nos outros dois candidatos custa zero refit. Nenhum item da minha lista anterior tem custo que justifique adiá-lo.

---

## 3. Achados novos — o maior deles não estava em nenhuma lista

### 3.1 `tp_atr_mult=2.0` e `sl_atr_mult=1.5` são ASSUMED e nunca varridos

Esta é, na minha leitura, a maior lacuna aberta do projeto — maior que qualquer pergunta sobre regime.

Essas duas constantes definem a **variável dependente de todo experimento já rodado**. `p_target`, `p_stop`, `e_return_atr`, `tail_loss`, `holding_time`, o `lift` do AG-118, a heterogeneidade do AG-114 — todos são condicionais à geometria de barreira. Se ela muda, nenhum desses números sobrevive.

E o projeto já tem a regra: §16.10 exige sweep de ±50% para constante classe A. A disciplina não precisa ser adotada — **precisa ser aplicada onde mais importa e não está sendo.** Se `tp_atr_mult`/`sl_atr_mult` não estão classificadas como classe A, a classificação está errada.

Uma consequência concreta da assimetria 2,0/1,5, computada a partir das contagens do §4.5 do brief anterior: o TP exige 33% mais movimento que o SL, então o ponto de equilíbrio é `p_tp = 1,5/3,5 = 42,86%`. As proporções observadas entre eventos resolvidos:

| célula | p_tp observado | vs. 42,86% |
|---|---:|---|
| R1 BTC short | 42,16% | abaixo |
| R1 BTC long | 41,79% | abaixo |
| R1 XRP long | 38,38% | bem abaixo |
| R1 SOL short | 43,38% | pouco acima |
| R2 BNB short | 43,12% | pouco acima |
| R3 ETH long | 42,40% | abaixo |

Todas orbitam o breakeven implícito pela geometria, quatro abaixo dele, **antes de custos**. Isso exclui desfechos por barreira vertical, então não é o quadro completo — mas sugere que o conjunto de labels, na configuração atual, é aproximadamente de edge nulo *por construção da barreira*, não por propriedade do mercado ou dos modelos. Procurar sinal econômico de regime em cima disso é procurar melhora marginal sobre um alvo centrado em zero por escolha de duas constantes que ninguém varreu.

### 3.2 `hmm_gaussian_k4_v1` já está wireado no Risk Engine

O brief do AG-118 apresenta a medição do `lift` como a evidência que *justificaria* ligar o campo `tradeable`, e diz que o campo formal pertence a uma camada ainda não construída. O manager informa que k=4 já está wireado como `regime_tradeable` (§15.13).

Então a sequência real foi: wiring primeiro, medição depois — e a medição voltou nula. O `src/live/` vazio significa que nada executa hoje, mas o wiring codifica uma decisão que nenhuma medição sustenta, e ele executa silenciosamente quando o loop subir.

Isso precisa de decisão explícita agora: reconfirmar com evidência nova (rodar o AG-118 nos 3 candidatos, custo zero) ou desligar até haver. O que não deve acontecer é continuar wireado por inércia enquanto a medição que o justificaria segue negativa.

### 3.3 O AG-120 não tem causa raiz, e isso é bloqueante de forma diferente do que eu pensava

O desalinhamento de timestamp entre o pipeline de dollar-bar e o de regime foi isolado com sucesso numa célula, mas nunca rastreado. O isolamento por célula é uma boa proteção **para experimentos**; é uma proteção ruim para um reprocessamento de 6 anos × 5 símbolos, onde a mesma classe de falha pode aparecer em N células e ser descoberta no meio da execução.

Recomendo uma **varredura de integridade dedicada antes do reprocessamento** — não o run de reprocessamento com isolamento ligado, mas uma passagem barata que responda "quantas células teriam esse problema, e por quê". O desenvolvedor concorda com isso.

### 3.4 O mandato de estágio não sustenta as decisões que estão sendo pedidas

Não existe métrica de sucesso final registrada; existe o mandato do V1 de "construir infraestrutura de hipótese→teste→validação". Isso é uma resposta legítima e muda a leitura de várias coisas:

- O `lift ≈ 1` do AG-118 **não é fracasso sob esse mandato**. A infraestrutura funcionou: ela detectou que o proxy do AG-114 não transferia para a economia. Esse é exatamente o produto que o mandato pede.
- Mas o mandato também torna insolúveis, e portanto mal-postas, as perguntas do tipo "1,8x importa?" e "lift de 1,4 é bom?". Elas exigem um objetivo final que não existe. Não force respostas para elas.
- Sob mandato de infraestrutura, o critério de decisão correto passa a ser **preservar opcionalidade e minimizar compromissos irreversíveis** — o que favorece corrigir a grade agora (§4) e desfavorece manter wiring não sustentado (§3.2).
- E torna a §3.1 ainda mais central: uma infraestrutura de validação cuja variável dependente é definida por duas constantes não varridas tem fundação não validada.

---

## 4. Correção de leitura — o desenvolvedor entendeu `cadence=1` como `trailing=1`

A resposta 4 diz: *"o problema de cadence=1 não é o agregador, é o efeito de aliasing de dia-da-semana já medido."*

Isso não procede, e o equívoco é exatamente o que a pergunta 2 do §8 do brief identifica como lacuna. O aliasing semanal é propriedade da **fonte de calibração**, não da frequência de aplicação. O erro medido em `W=1` vem de calibrar sobre 1 dia — sortear qual dia da semana serve de base. Calibrando sobre os 7 dias anteriores (balanceado por construção) e aplicando por 1 dia, **não existe aliasing**: toda aplicação usa uma base que contém exatamente uma ocorrência de cada dia da semana.

`T=7, C=1` não foi medido. Ele não está em nenhuma linha da tabela do §3, porque a tabela varre um parâmetro só. O fato de o próprio desenvolvedor ler minha recomendação como se fosse `W=1` é a melhor evidência de que amarrar os dois parâmetros está causando confusão ativa, não só perda de espaço de busca.

E as respostas 3 e 4 se encaixam aqui: `C=1` é implementável sem tocar o agregador (só mais carries), mas multiplica as fronteiras de período de ~52 para ~365 por ano. **Por isso preservar o carry deixa de ser cosmético e vira precondição de `C=1`** — com o carry preservado, as duas objeções desaparecem de uma vez.

**Ajuste de severidade, com retratação parcial:** classifiquei o reset de carry como bloqueante. Com a informação de que não há perda de dado (todo trade entra em alguma barra; a última de cada período é subdimensionada, não truncada) e que são ~52 barras/símbolo/ano, **rebaixo de bloqueante para "faça na mesma mudança"** sob `C=7`. O que permanece é que essas ~52 barras/ano caem sempre no mesmo dia da semana — um marcador periódico determinístico na exata frequência que a correção existe para remover. Pequeno, evitável, e barato. Sob `C=1`, volta a ser precondição.

---

## 5. Recomendação revisada

### Antes de reprocessar — bloqueantes

- **B0 — Varredura de integridade** rastreando a causa raiz do AG-120 em todas as células (§3.3). *Novo, e agora o primeiro da fila.*
- **B1 — Circuit breaker contra os picos de ~14x** da medição diária. Inalterado.
- **B2 — Preservar o carry** (§4). Bloqueante se `C=1`; "mesma mudança" se `C=7`.

### Medições antes de travar o par — todas em minutos (§2.3)

- **M1** — sweep do corte de erro (0,4/0,5/0,6 e 1,7/2,0/2,5).
- **M2** — preencher o grid em 5, 6, 8, 9, 13, 15.
- **M3** — desacoplar `T` e `C`, com `T=7, C=1` explicitamente na grade (§4).
- **M4** — substituir a contagem binária pela distribuição da razão estratificada por dia-da-semana.
- **M5** — rodar o AG-118 em k=2 e k=3. *Custo zero confirmado, e é o que dá base empírica ao §3.2.*

### Item que subiu ao topo

- **S1 — Sweep de `tp_atr_mult` e `sl_atr_mult` sob a regra §16.10 que já existe** (§3.1). Não bloqueia o reprocessamento da grade, mas bloqueia qualquer leitura econômica de qualquer experimento. Se houver capacidade para uma coisa só nesta sessão, é esta.

### Decisões que são do manager, não minhas

- **Pré-registrar agora**, antes de rodar M1/M2, se a decisão sobre `W` reabre caso os resultados contradigam `7`. Responder depois de ver os números elimina o valor de ter perguntado.
- **Decidir sobre `regime_tradeable`** (§3.2): reconfirmar com M5 ou desligar até haver evidência.
- **Atribuir dono e prioridade** para o re-run de M4/AG-114/AG-118 pós-reprocessamento. Hoje está reconhecido mas não atribuído, e "não atribuído" é como esse tipo de item costuma virar dívida silenciosa.
- **Classificar `tp_atr_mult`/`sl_atr_mult` como classe A** ou justificar por escrito por que não são.

Sobre o timing: com o Data Layer em 0/9 e sem gate de calendário, não há argumento de prazo contra corrigir a grade agora, e o custo de reabertura é menor do que o brief temia — o que se invalida são experimentos (`experiments/`), não artefatos de produção, que não existem. A única exceção é o wiring do §3.2, que precisa ser tratado como decisão, não como reprocessamento.
