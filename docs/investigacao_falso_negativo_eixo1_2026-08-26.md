# Investigação — o eixo 1 (critério de promoção L3→L2) está descartando sinal real?

> Documento DATADO de uma investigação pontual (2026-08-26), não documento vivo —
> não se atualiza a cada rodada. Nasce de uma pergunta direta do Manager: as
> features L2/L3 são promissoras, e a régua de medição pode estar rigorosa
> demais a ponto de invalidar sinal real (falso negativo sistemático), em vez
> das features não terem mecanismo. Cobre: (1) achados verificados diretamente
> nos dados reais, (2) pesquisa externa sobre metodologia real de produção,
> (3) auditoria adversarial independente (metodologia estatística/ML, não a
> lente de "gaps de arquitetura" usada no resto da sessão) do V14/V17
> (`Laplace_Quant`, projeto irmão) cruzada com o nosso motor, (4) síntese e
> recomendação, (5) decisão sobre a proposta de reestruturação L0-L4 → L0-L3.
>
> Ancoragem: `docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md` §2.2,
> §14.1; `src/analysis/feature_promotion_criterion.py` (`AG-294`);
> `src/analysis/feature_temporal_stability.py` (`AG-299`).

---

## 1. O que estava sendo perguntado

O critério de promoção de feature `L3 → L2` (ADR-005 §2.2) tem dois eixos:

- **Eixo 1 — significância cross-symbol.** Para cada feature: `pico_abs_t` =
  maior `|t|` entre 6 horizontes testados (`DEFAULT_HORIZONS = (1,2,4,8,16,32)`,
  `src/analysis/ic_by_horizon.py`) → vira p-valor via normal padrão → BH
  `q=0,10` dentro de cada célula (resolução×símbolo, 15 células, 72 features) →
  símbolo conta como "descoberta" se maioria (≥2/3) das resoluções concordam →
  testado contra `binomial(n_symbols=5, p_symbol_empírico=0,0667)`.
- **Eixo 2 — estabilidade temporal.** IC por semestre-calendário,
  `max|IC_sub|/mediana|IC_sub| ≤ 4` e direção consistente em `≥70%` dos
  semestres.

Medido contra os 3 relatórios reais (`experiments/feature_promotion_criterion_report.json`):
nenhuma feature nova passa o eixo 1 com folga — a única com 5/5 símbolos é
`E18f_taker_ls_vol_ratio`, **já marcada em quarentena por defeito de construção
conhecido** (mede artefato de fonte, `AG-266`). A pergunta: isso é o teste
funcionando corretamente (só o artefato passa porque só o artefato tem sinal
"real" nesse desenho), ou o teste está calibrado de um jeito que mata sinal
genuíno e só deixa passar o que é grande o bastante para ser um artefato?

---

## 2. Achados verificados diretamente nos dados reais (antes de qualquer pesquisa externa)

### 2.1 As 7 features JÁ EM PRODUÇÃO (T1) também zeram no eixo 1

`B01_rsi_14`, `E27f_cost_atr_ratio`, `C06_vol_ratio_12_96`,
`D06f_taker_imbalance_z_48` têm **0** símbolos-descoberta; `A05_ret_vol_norm_4`,
`A13_dist_ema48_atr`, `E10f_oi_change_z_48` têm **1**. Nenhuma das 7 features
que hoje treinam o Alpha (escolhidas por outro processo, presumivelmente com
utilidade real) passa no critério que está sendo usado para julgar as
candidatas novas. Isso é o achado mais incômodo do conjunto — um teste que não
consegue validar o que já é considerado útil é suspeito por si só.

### 2.2 A tabela `k≥` mostra um buraco exatamente no meio, não uma cauda que declina suavemente

| `k ≥` símbolos | esperado sob H₀ | observado |
|---|---|---|
| 1 | 21,01 | 19 |
| 2 | 2,79 | **2** |
| 3 | 0,19 | **1** |
| 4 | 0,007 | **1** |
| 5 | 9,5·10⁻⁵ | **1 (o artefato)** |

Em `k=2` e `k=3`, o observado está **abaixo ou igual** ao esperado por acaso —
ou seja, não há absolutamente nenhum excesso de "replicação moderada" (2-3 de
5 símbolos). O único excesso é no extremo absoluto (`k=5`, 10.000× o esperado)
— e é o artefato conhecido. A distribuição observada não tem massa no meio.

### 2.3 12 de 16 "descobertas de 1 símbolo" (75%) caem todas no mesmo ativo — BNBUSDT

Contagem direta do `por_feature` do relatório: `A01`, `A02`, `A03`, `A05`,
`A07`, `A10`, `A13`, `A14`, `B10`, `B11`, `K01_hour_cos` → todas BNBUSDT (11);
mais `K04_session_europe` → BNBUSDT (12/16). Restam `E05f`/`K01_hour_sin`
(XRPUSDT, 2), `E10f` (ETHUSDT, 1), `E16f` (SOLUSDT, 1). Nenhuma em BTCUSDT.

O teste binomial trata os 5 símbolos como ensaios de Bernoulli intercambiáveis.
Esse padrão — quase todo "ruído que parece descoberta" caindo no mesmo ativo —
é inconsistente com essa premissa. BNBUSDT tem histórico mais curto e uma
migração de chain conhecida (BEP2→BEP20, 2019) que os outros 4 símbolos não
têm; é mais plausível que o padrão seja idiossincrasia do ativo (menos dado,
regime de listagem diferente) do que 12 features "quase descobrindo" sinal
genuíno coincidentemente no mesmo símbolo.

---

## 3. Pesquisa externa — metodologia real de produção (relatório completo do agente de pesquisa em anexo às notas da sessão; condensado abaixo)

### 3.1 Peak-hunting entre 6 horizontes infla p-valores individuais — na direção ERRADA para explicar o zero

Escolher o pico de `|t|` entre 6 horizontes e testar esse pico sem correção é
o mesmo problema descrito por três literaturas independentes sob nomes
diferentes — *winner's curse* (genômica), *look-elsewhere effect* (física de
partículas), *data snooping* em regras de trading (White 2000, Hansen 2005,
Romano & Wolf 2005). Em TODOS os casos o efeito é **inflar** a significância
aparente da observação individual — o `pico_abs_t` sem correção produz um
p-valor artificialmente **pequeno demais**, não grande demais.

Isso importa de um jeito específico: **não é essa a causa do "zerou tudo"** —
pelo contrário, esse viés deveria fazer MAIS coisas passarem, não menos. O que
isso realmente quebra é a garantia formal do BH da camada seguinte: BH exige
p-valores válidos (uniformes sob H0) para controlar FDR≤10% de verdade — e os
p-valores de entrada aqui já vêm sistematicamente pequenos demais. **A camada
2 (BH) não é uma correção válida em cima de uma entrada que já violou a
premissa que a torna calibrada** — o pipeline empilha uma correção
corretamente calibrada sobre uma entrada mal calibrada, sem saber.

### 3.2 `binomial(5, p)` tratando símbolos correlacionados a 0,7–0,9 como i.i.d. é estruturalmente inválido — e o modo de falha é bimodal

Literatura de "número efetivo de testes" (`Meff`, Li & Ji 2005; Galwey 2009 —
originalmente genômica de SNPs correlacionados) e de erro-padrão duplamente
clusterizado (Fama-MacBeth/GLS, Robust Variance Estimation — Hedges, Tipton &
Pustejovsky) documentam a prática padrão quando testes são correlacionados:
não se trata `n` observações correlacionadas como `n` ensaios independentes —
usa-se um `n` efetivo menor (via autovalores da correlação) ou residualiza-se
o fator comum antes de testar o componente idiossincrático.

Consequência não-intuitiva, e a que mais bate com o que medimos: correlação
positiva entre os 5 símbolos não torna o teste "uniformemente mais difícil" —
torna a distribuição nula da contagem **bimodal** (ou nenhum símbolo
"descobre" junto sob um choque comum, ou quase todos ao mesmo tempo) e
**esvazia exatamente o meio** (2-3 de 5) onde um sinal econômico real, mas
modesto e replicável, mais provavelmente cairia. Isso é *exatamente* o buraco
observado na tabela §2.2 acima.

### 3.3 Como diferenciar "teste sem poder" de "domínio sem sinal" — heurística concreta, não intuição

A literatura de validação de ensaio (genômica: positive/negative controls)
sugere uma leitura direta dos próprios dados: `E18f` (artefato) passando é um
**controle positivo que funcionou** — prova que o teste tem poder para efeitos
do tamanho de um artefato de dado. As 7 features T1 zerando é evidência de que
a curva de poder do teste é **essencialmente um degrau**: dispara só para
efeitos do porte do artefato, poder ≈ zero para o porte de efeito que uma
feature econômica real e modesta (IC ~0,02–0,05, a faixa que a indústria trata
como "útil", ver §3.4) plausivelmente tem.

Recomendação de diagnóstico concreto (não fazer sem medir — B23): injetar
features SINTÉTICAS com IC realista (~0,02–0,05, não do porte do artefato) e
checar se o pipeline atual as detecta na multiplicidade exigida. Isso decide
empiricamente a questão, em vez de inferir por analogia.

### 3.4 Alphalens/Qlib/WorldQuant não usam "descoberta binária cross-symbol" — usam pontuação contínua, e isso é uma discordância estrutural de desenho, não só de calibração

Alphalens (Quantopian) e Qlib (Microsoft) avaliam fator por IC médio + ICIR
(estabilidade temporal do IC, não pico único) + curva de decaimento por
horizonte (a curva INTEIRA, não o pico) + turnover. IC ~0,02–0,05 já é tratado
como útil em baixo turnover. WorldQuant (`101 Formulaic Alphas`) admite um
alpha fraco individualmente se a correlação PAR-A-PAR com os outros alphas do
portfólio for baixa (~15,9% médio no paper) — o valor vem do ensemble, não da
blindagem estatística individual.

**Isso é uma resposta direta a "por que zerou tudo":** o desenho atual exige
que CADA feature, sozinha, seja uma "descoberta" blindada por hipótese antes
de entrar no vetor de treino do LightGBM. Nenhuma das três referências de
produção real exige isso de um fator individual — o modelo (ensemble de 72+
candidatas) é o mecanismo que extrai valor de sinais fracos mas coletivamente
informativos, desde que o IC não seja ruído puro e a correlação entre
features seja baixa o suficiente para agregar. O eixo 1 está respondendo à
pergunta "isso é uma anomalia digna de paper" quando a pergunta que interessa
para promoção de feature de modelo é "isso carrega informação incremental que
o LightGBM consegue explorar".

### 3.5 Westfall-Young max-T (1993) — o precedente do V17, e por que ele resolve as duas dependências (horizonte E símbolo) ao mesmo tempo

Confirmado por literatura de otimidade formal (`Optimality of the
Westfall-Young permutation procedure... under dependence`): sob dependência
real entre testes, max-T via permutação tende a dominar em poder correções
fechadas (Bonferroni/BH) que ignoram ou simplificam demais essa dependência —
porque a permutação PRESERVA empiricamente a estrutura de dependência real, em
vez de assumi-la por fórmula. O nosso próprio projeto irmão (`Laplace_Quant
V17`, `pipeline/features/leakage_gate.py`) já passou por esse ciclo: um
"Bonferroni" fechado (`2/√N × √K`) foi refutado empiricamente (FWER real
0,0016 contra alpha nominal 0,05 já em K=3 — absurdamente conservador) e
substituído por Westfall-Young max-T com null por permutação de sessão.

O nosso caso tem dependência em DUAS dimensões simultâneas — entre os 6
horizontes (correlacionados por sobreposição temporal de retorno futuro) E
entre os 5 símbolos (correlacionados 0,7–0,9 por fator de mercado cripto
comum). O eixo 1 atual trata a primeira informalmente (peak-hunting cru) e a
segunda incorretamente (binomial i.i.d.). Um max-T conjunto sobre a grade
completa (72 features × 6 horizontes × 5 símbolos, com bootstrap em blocos
para preservar autocorrelação temporal) resolveria as duas dentro de um único
framework coerente.

---

## 4. Auditoria adversarial independente (V14/V17 cruzado com o nosso motor)

Agente com lente estatística/engenharia de ML — deliberadamente diferente da
lente de "gaps de arquitetura/integração" usada no resto desta sessão — leu
diretamente no disco: `feature_promotion_criterion.py`,
`feature_temporal_stability.py`, `ic_by_horizon.py`, os 3 relatórios reais,
`fichas_69_2026-08-25.yaml`, `registry.yaml`, `test_features_parity.py`, e os
4 arquivos-chave do `Laplace_Quant_V17`. Duas correções factuais às minhas
notas: `pico_abs_t` é máximo sobre **6** horizontes (não ~7); os dois únicos
candidatos que passam `k≥2` no eixo 1 (`E18f`, `K04_session_us`) têm **ambos**
veredito de defeito confirmado na ficha (`ERRO_CATEGORICO` e
`INCOERENTE_DIMENSIONAL`, respectivamente) — zero sobreviventes com tese
limpa, não "um artefato e uma dummy inócua".

### 4.1 O eixo 1 é análogo ao "√K" já refutado no V17?

**Parcialmente — mesma família de erro (pilha de correções não auditada como
sistema), mecanismo e direção diferentes.** O √K do V17 era erro de **fórmula
fechada**, superconservador por construção matemática errada. O eixo 1 daqui
é uma pilha de 3 camadas com direções de viés DIFERENTES: (1) peak-hunting
não corrigido (`pico_abs_t` = máximo de 6 horizontes tratado como teste
único) — **anti-conservador**, direção oposta ao √K, o próprio docstring do
módulo já admite isso sem quantificar a consequência; (2) BH q=0,10 —
implementado corretamente; (3) `binomial(5, p_symbol)` com `p_symbol` medido
empiricamente — o viés da camada 1 contamina numerador E denominador, então o
teste se autocalibra parcialmente. Onde a analogia realmente pega, e é mais
grave do que a pergunta original supõe: o binomial trata os 5 símbolos como
i.i.d. — exatamente o MESMO tipo de erro que `AG-270` já corrigiu uma vez
(célula tratada como independente quando 72% dos blocos símbolo×resolução
são concordantes) — só que dessa vez entre símbolos, nunca testado, e
**factualmente falso** nos próprios dados (ver §4.3).

### 4.2 Zerar T1 é teste mal calibrado ou produção sem base?

**Terceira leitura que ninguém tinha considerado: o eixo 1 testa a pergunta
errada para pelo menos uma feature do T1.** `E27f_cost_atr_ratio` — na
própria ficha, veredito `TESE_OK` — é descrita como "honesta como FILTRO de
viabilidade e enganosa como preditor direcional". Testar isso com "há IC
direcional replicado em ≥3 símbolos?" mede a coisa errada para uma feature
que nunca alegou ter esse tipo de base. Isso NÃO significa que o zero de
`B01_rsi_14`/`D06f_taker_imbalance_z_48` tenha a mesma desculpa — não há
leitura de papel-não-direcional evidente para elas. As duas leituras
("teste mede a pergunta errada para papel filtro/custo" vs. "produção não
tem base para papel gatilho/confirmação") não são intercambiáveis — tratá-las
como se fossem é o erro a evitar.

### 4.3 A concentração em BNBUSDT — confirmado e mais forte do que eu tinha medido

Contagem sobre TODOS os pares (feature,símbolo)-descoberta (24 no total, não
só os 16 de k=1 que eu tinha contado): **15/24 (62,5%) são BNBUSDT**, contra
20% esperado por simetria. Taxa de descoberta de BNBUSDT ≈20,8% das 72
features; a soma dos outros 4 símbolos ≈3,1% — **BNBUSDT descobre a uma taxa
~6,7× maior**. **Correção à minha hipótese original:** contagem de barras por
símbolo é COMPARÁVEL entre os 5 (R1: BTC 152.926/ETH 156.788/SOL
165.023/BNB 163.200/XRP 171.098) — "histórico mais curto" **não se sustenta**
como explicação. Leitura mais parcimoniosa: um fator/regime comum não
modelado, específico de BNB, na janela medida (não identificado qual) — não
13 mecanismos econômicos distintos, genuínos e replicáveis, que por
coincidência só aparecem nesse símbolo. Consequência dupla: não muda a
decisão de hoje (nenhuma feature nova bate `k≥2` mesmo considerando isso),
mas invalida a premissa i.i.d. por trás do `p_symbol=0,0667` usado para
calibrar toda a tabela `k≥1..5`.

### 4.4 O que do V17 é diretamente aplicável

Três mecanismos concretos, não uma lista genérica: **(a)** Westfall-Young
max-T (`leakage_gate.py:26,36-47`) — remédio direto para o peak-hunting: null
por permutação/circular-shift (unidade = sessão/estrutura real da grade, não
dia de calendário) em vez de fórmula fechada sobre um estatístico que já é
máximo de 6 horizontes. **(b)** Separação `_ALPHA_BLACKLIST`/`_META_BLACKLIST`
(`feature_sets.py:204-214`) — mas achado importante: o V17 **não resolve** o
problema que o ADR-005 tenta resolver (existe sinal reproduzível?); resolve
um problema mais estreito (vaza o alvo?). Vale importar a MÁQUINA
(permutação com null respeitando estrutura temporal real), não a arquitetura
L0-L4 inteira — o V17 nunca precisou de um conceito equivalente. **(c)**
`MIN_REAL_BARS_FRACTION` fail-loud floor — o idioma equivalente já existe no
nosso `feature_temporal_stability.py` (`min_semesters`, corrigido pelo
`project_assurance` depois de achar que 1 semestre passa trivialmente) —
já importado de fato, independente do V17. **Paridade lote/streaming: real,
não aspiracional** — `tests/parity/test_features_parity.py:56-114` roda de
fato, 500 barras, tolerância `1e-8`, skip individual por símbolo se faltar
backfill; usa "Idioma A" (recompute sobre prefixo) em vez do "Idioma B"
carry/step/finish do V17, mas ambos são formas sancionadas pelo próprio
`CLAUDE.md`, e o teste de A executa a comparação de verdade.

### 4.5 A promoção mecânica faz sentido hoje?

**Não — por dois motivos independentes, um de processo e um estatístico.**
**Processo:** as 5 features de "momentum reconhecido" (`A01`-`A04`, `A06`)
têm veredito `SEM_MECANISMO` na ficha REAL — a justificativa "momentum é
mecanismo reconhecido" existe só na prosa do ADR, nunca virou emenda formal
à ficha que o próprio processo declara como fonte de verdade. Isso é
recorrência nomeada do padrão `AG-114`/`AG-122` (regra a priori sem definição
operacional → decisão real vira julgamento ad-hoc no momento de aplicar —
exatamente o que travar critério existe para evitar). **Estatístico:** sob o
eixo 1 já implementado e rodado, `L2={}`, e os dois únicos candidatos em
`k≥2` têm AMBOS defeito de construção confirmado — zero features com tese
limpa passam em qualquer nível acima do ruído esperado sob H0.

---

## 5. Síntese — os três fios convergem, com uma discordância honesta registrada

Pesquisa externa, dados verificados diretamente e auditoria adversarial
independente concordam no essencial, apesar de terem sido produzidos sem
contato entre si:

1. **`L2={}` provavelmente NÃO é uma medição limpa hoje** — não porque as
   features careçam de mecanismo econômico (isso é uma pergunta diferente,
   respondida pelas fichas), mas porque o instrumento que mede "há sinal
   estatístico replicável" tem pelo menos dois problemas de desenho
   nomeáveis e concretos: peak-hunting não corrigido dentro de cada feature
   (§3.1/§4.1) e um modelo binomial pooled cuja premissa de independência
   entre símbolos é factualmente falsa (§2.3/§3.2/§4.3, confirmado por
   contagem direta nos dois lados independentemente).
2. **Isso NÃO significa "o sinal está lá, só a régua é ruim".** Os dois
   candidatos que sobrevivem a qualquer réplica acima do ruído (`E18f`,
   `K04_session_us`) têm AMBOS defeito de construção confirmado na ficha —
   o instrumento, mesmo mal calibrado, não está cego: ele reage a efeitos do
   tamanho de um artefato de dado. O que ele não prova é ter poder para
   detectar um efeito do tamanho que uma feature econômica real e modesta
   (IC ~0,02-0,05, a faixa que a indústria — Alphalens/Qlib/WorldQuant —
   trata como útil, §3.4) plausivelmente teria.
3. **Discordância honesta a registrar, não resolvida por nenhum dos três
   fios:** é impossível hoje separar "teste sem poder" de "domínio
   genuinamente fraco" sem um diagnóstico direto — o próprio pesquisador
   propôs o teste que resolveria isso (injeção de features sintéticas com
   IC realista, verificar se o pipeline as detecta) e ele NÃO foi rodado
   nesta investigação (fora de escopo — seria uma nova medição, não uma
   leitura do que já existe, B23).
4. **Achado novo, só a auditoria viu:** pelo menos 1 feature do T1
   (`E27f_cost_atr_ratio`) nunca foi desenhada para ter IC direcional — o
   eixo 1 mede a pergunta errada para o papel dela. Isso significa que
   "T1 zera" não é uma frase homogênea — precisa ser lida por papel
   declarado (gatilho/confirmação vs. filtro/custo), não como um bloco só.

---

## 6. Decisão sobre a proposta de reestruturação L0-L4 → L0-L3

**A instrução era condicional ("se fizer sentido, promova...") — a validação
acima conclui que NÃO faz sentido hoje, e a proposta não foi executada.**

Promover mecanicamente as L3 `TESE_OK`/"momentum reconhecido" para `L2` e
rebaixar as L3 em quarentena para `L4` — reestruturando `L0-L4` em `L0-L3`
(`L2` = núcleo de sinal + promovidas; `L3` = aposentada, herda L4 + as
quarentenas rebaixadas) — teria dois problemas concretos e verificados, não
uma objeção genérica:

- **Ignoraria uma medição já feita sem justificar por que ela estaria
  errada.** O eixo 1 (`AG-294`, já em código, já rodado contra os 3
  relatórios reais) diz `L2={}` hoje. Promover por cima disso sem antes
  corrigir OU refutar formalmente essa medição contraria diretamente o
  mandato do projeto ("Meça antes de afirmar", "Discorde do Manager quando o
  dado discordar — apresente a medição, não acomode a instrução").
- **Repetiria o padrão `AG-114`/`AG-122`** — promover `A01`-`A06` citando
  "momentum reconhecido" sem antes emendar a ficha que hoje diz
  `SEM_MECANISMO` é decidir por julgamento ad-hoc no momento de aplicar,
  exatamente o que travar critério a priori existe para evitar.
- **Rebaixar `E18f` (quarentena) para uma nova `L3`="aposentada" já fundida
  com `L4` apagaria a distinção que o próprio ADR-005 §2.3 declara
  proposital:** quarentena é "sinal forte e suspeito" (o problema é o sinal
  ser grande demais para ser real), `L4` é "sem sinal e sem mecanismo" — são
  populações diferentes por desenho; fundir as duas nomenclaturas perderia
  informação que hoje é rastreada de propósito.

**Nenhuma reestruturação de camadas foi aplicada.** `L0-L4` continuam como
estavam (`docs/ADR-005...md` §14.4): `L0`=2, `L1`=4, `L2`=7 (`T1`), `L3`=17,
`L4`=42 (contagem já corrigida nesta sessão — ver conversa anterior sobre
`K08`/`A13`/`E10f`). `T1_FEATURE_IDS`, `registry.yaml`, `constants.yaml` —
nenhum tocado por esta investigação.

---

## 7. O que foi mapeado e atualizado nesta investigação

- **4 entradas novas no log de arquitetura** (`audit/architecture_gaps_log.yaml`):
  `AG-327` (peak-hunting não corrigido, ALTA), `AG-328` (binomial pooled
  com premissa i.i.d. falsa — BNBUSDT ~6,7× os demais, ALTA), `AG-329`
  (ficha `A01`-`A06` nunca emendada para "momentum reconhecido" —
  recorrência `AG-114`/`AG-122`, MÉDIA-ALTA), `AG-330` (eixo 1 mede a
  pergunta errada para features de papel filtro/custo como `E27f`, MÉDIA).
  Todas com `status: aberto — aguarda decisão do Manager` (mudança de
  metodologia de critério, não fix mecânico — fora do escopo desta
  investigação executar sozinha).
- **Este documento** (`docs/investigacao_falso_negativo_eixo1_2026-08-26.md`)
  — investigação datada, não documento vivo, per convenção do repo.
- **Nada em `src/analysis/`, `registry.yaml`, `constants.yaml`,
  `fichas_69...yaml` ou `ADR-005...md` foi editado** — toda mudança de
  metodologia real (corrigir o binomial, adotar max-T, emendar fichas)
  fica pendente de decisão explícita do Manager sobre prioridade, porque
  são mudanças de DESENHO de critério, não fixes mecânicos.
- **`src/models/` (§13, escopo de outra sessão) não foi tocado.**

## 8. Próximo passo recomendado, se o Manager priorizar isto

Ordem sugerida por ambos os agentes independentemente (pesquisa e auditoria
convergiram na mesma sequência): (1) diagnóstico de poder por injeção de
features sintéticas com IC realista (decide empiricamente "teste sem poder"
vs. "domínio fraco", sem isso qualquer correção seguinte é às cegas); (2)
testar homogeneidade entre as 5 taxas de símbolo antes de decidir se
`binomial` pooled é sequer o modelo certo; (3) se a decisão for redesenhar,
migrar para max-T tipo Westfall-Young sobre a grade horizonte×feature×símbolo
inteira, unidade de shift respeitando a estrutura real de dollar bar; (4) só
depois disso, reavaliar promoção — como leitura de um critério corrigido, não
como bypass do critério atual.

---

## 9. Execução real (2026-08-27) — o resultado que revisa a leitura da §3.3/§4.2/§5

Itens 1 e 2 acima foram implementados e RODADOS contra dado real nesta
sessão (Manager autorizou execução direta). Código:
`src/analysis/eixo1_power_diagnostic.py`,
`src/analysis/eixo1_symbol_homogeneity.py`; detalhe de implementação e
revisão independente do código: `docs/ADR-005_arquitetura_do_feature_
engine_2026-08-26.md` §14.9-§14.10.

### 9.1 Item 2 — homogeneidade entre símbolos: REJEITADA, formalmente

`uv run python -m src.analysis.eixo1_symbol_homogeneity`:
`chi2_statistic=30,09`, `p_value=4,69e-06`, `gl=4`. Taxas: `BTCUSDT=1,39%`,
`ETHUSDT=2,78%`, `SOLUSDT=2,78%`, `BNBUSDT=20,83%`, `XRPUSDT=5,56%`.
Confirma numericamente o achado do §2.3/§4.3 — a premissa i.i.d. do
`binomial(5, p_symbol)` de `AG-294` é factualmente falsa, agora com teste
formal, não só leitura visual da tabela.

### 9.2 Item 1 — diagnóstico de poder: resultado NÃO esperado, revisa a hipótese central desta investigação

`uv run python -m src.analysis.eixo1_power_diagnostic --start 2022-01-01
--end 2026-08-07` (100 sorteios de Monte Carlo por ponto, 7 pontos de
grade, 15 células reais):

| `rho_true` | Spearman alcançado | detecção `k≥1` | `k≥2` | `k≥3` |
|---|---|---|---|---|
| 0,00 | −0,0008 | 0% | 0% | 0% |
| 0,01 | 0,0068 | **98%** | 87% | 66% |
| 0,02 | 0,0191 | **100%** | 100% | 100% |
| 0,03-0,10 | 0,028-0,097 | 100% | 100% | 100% |

**A hipótese central desta investigação — que o eixo 1 pudesse ser
"essencialmente uma função degrau", com poder só para efeito do tamanho de
um artefato de dado (§3.3, §4.2) — NÃO SE SUSTENTA sob medição direta.** O
pipeline detecta com quase certeza (98%) um Spearman de apenas `~0,007`, e
com certeza total a partir de `~0,02` — precisamente a base da faixa que a
indústria (§3.4, Alphalens/Qlib/WorldQuant) trata como "IC útil". Controle
negativo (`rho_true=0`) não produziu nenhum falso positivo em 100 sorteios.

**Isso NÃO refuta `AG-327`/`AG-328` como defeitos de desenho** — peak-
hunting não corrigido e o binomial pooled com premissa i.i.d. rejeitada
(§9.1) continuam reais, e valem correção por corretude/precisão. **Mas
muda qual é a explicação mais provável para `L2={}`:** não "o teste está
cego para sinal modesto", e sim "as 72 features candidatas genuinamente não
carregam nem um IC marginal univariado modesto contra o retorno futuro".
Isso é consistente com a leitura mais sóbria já registrada em §3.3 como
possibilidade — a medição agora pesa claramente para ELA, não para a
hipótese de teste mal calibrado que motivou a pesquisa/auditoria.

### 9.3 O que isso muda na recomendação da §5/§8

A ordem de prioridade original (poder → homogeneidade → max-T → reavaliar)
continua correta como MÉTODO — mas o resultado do item 1 reduz a urgência
do item 3 (max-T conjunto): não há mais evidência de que o pipeline atual
esteja descartando sinal real por falta de poder na faixa que importaria.
`AG-328` (homogeneidade rejeitada) segue como um defeito de calibração real
do `binomial` — vale corrigir por corretude — mas a decisão de promoção não
está mais bloqueada pela pergunta "isso é falso negativo sistemático?": a
resposta medida é não, ao menos não no sentido que este diagnóstico testou.
`L2={}` como leitura honesta do domínio ganha peso; decisão final de
promoção continua com o Manager.

### 9.4 `AG-328` corrigido — Meff mede ~2,4 símbolos efetivamente independentes

Executado 2026-08-27: `src/analysis/eixo1_effective_symbol_count.py`
(Galwey 2009, `M_eff` sobre a matriz de correlação `5×5` de `pico_abs_t`
entre símbolos, `R1`). **`n_eff = 2,43` (`floor=2`), correlação média entre
pares `= 0,848`.** Confirma numericamente — e mais alto que — a estimativa
informal "0,7-0,9" citada em §3.2: os 5 símbolos não são 5 ensaios
independentes, são efetivamente ~2,4.

Tabela corrigida (`n_eff=2`) vs. naive (`n=5`, `AG-294`):

| `k≥` | naive (`n=5`) | corrigido (`n_eff=2`) | observado |
|---|---|---|---|
| 1 | 21,01 | 9,28 | 19 |
| 2 | 2,79 | 0,32 | 2 |
| 3 | 0,19 | 0,00* | 1 |

`*` `k>n_eff_floor` — o binomial de 2 ensaios não tem massa em `k≥3` por
construção (ver ressalva de interpretação abaixo, não é "impossível").

**Achado que pede leitura cuidadosa:** sob o modelo naive, `k=1`/`k=2`
pareciam "dentro do acaso". Sob o corrigido, os MESMOS observados (19, 2)
ficam bem acima do esperado (9,28, 0,32). Isso NÃO é uma correção que torna
tudo "menos significativo" — na direção de `k=1`/`k=2` faz o oposto.
Ressalva honesta: substituir `n_symbols=5` por `n_eff=2` no mesmo binomial
é uma aproximação (a contagem observada continua medida nos 5 símbolos
reais; só o "esperado sob H0" muda de modelo), não uma transformação
distribucional exata — documentado como tal no próprio módulo. O que é
robusto a essa ressalva: `n_eff≈2,4` em si já estabelece que a tabela de
`AG-294` usa um `n` medido como errado por `>2×`, independente de qual
correção final for adotada (Meff vs. residualizar fator comum,
Fama-MacBeth/GLS — decisão do Manager).

### 9.5 Outros itens do backlog de metodologia (§14.8 do ADR) — tratativa 2026-08-27

Instrução do Manager: tratar `AG-329`/`AG-332`/`AG-333`/`AG-334`, parar e
notificar qualquer um que não fizesse sentido para produção.

- **`AG-329` (ficha `A01`-`A06` nunca emendada) — FECHADO.** Ficha emendada
  formalizando a decisão já tomada em `ADR-005 §14.2` (não um julgamento
  novo): `mecanismo_economico`/`quem_esta_do_outro_lado` populados,
  `veredito` de `SEM_MECANISMO` para `TESE_OK`, com ressalva explícita de
  que isso não é evidência de sinal — o diagnóstico de poder (`§9.2`) já
  mostrou que essas colunas continuam com 0-1 símbolo de descoberta.
- **`AG-332` (teste de perturbação no-lookahead) — FECHADO, achado original
  REFUTADO.** Investigação encontrou que o mecanismo já existe e é
  extensivamente aplicado (`test_features_support.py::_assert_causal`,
  reaproveitado em 15 testes de primitiva + 27 testes de feature em
  `test_features_groups.py`). Auditoria completa (script, não amostra): 65
  das 71 features têm `causal_proof` citando um teste real verificado
  (0 quebradas), as 6 restantes são trivialmente causais (sem janela). Fix
  real aplicado: 3 citações incompletas (`C03`/`C04`/`C05`, apontavam só
  pro arquivo, não a função) corrigidas.
- **`AG-333` (piso fail-loud único) — PARADO, não se aplica.** O mecanismo
  do V17 resolve barras SINTÉTICAS de uma grade de relógio (gaps de fim de
  semana) — problema que não existe por construção em barra dollar (uma
  dollar bar só existe quando há volume real). A preocupação adjacente real
  (piso de histórico comum entre símbolos) já tem mecanismo E já é
  rastreada sob `AG-030` (aberto desde 2026-08-17) — tratar como item novo
  duplicaria a dívida sob dois nomes.
- **`AG-334` (gate de versão treino-live) — PARADO, confirmado prematuro.**
  Achado original impreciso: o campo `version` por feature já existe no
  registry. O que falta é o GATE de validação — e não há caminho de
  serving ao vivo no repo hoje (`src/execution/` só tem simulador de
  backtest; `src/live/` vazio) para o gate proteger. Construir agora seria
  infraestrutura sem consumidor real.
