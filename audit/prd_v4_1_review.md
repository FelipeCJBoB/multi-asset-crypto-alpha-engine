# Auditoria — PRD V4.1 (Reabertura Estrutural Multi-Ativo e Multi-Timeframe)

> Gerado em 2026-08-09. Escopo: `PRD_V4_1.md` (740 linhas) completo, cruzado contra
> `experiments/code_discovery.json` (`ddc0362`), `audit/evidence_ledger.yaml` (160
> entradas), `audit/n_lifetime.yaml`, `config/constants.yaml`, `pyproject.toml`, e
> `git ls-files` (o que está de fato versionado no repo).
>
> **Postura declarada:** validação de risco de modelo independente, padrão SR 11-7.
> Presunção de culpa — todo número em V4.1 é `ASSUMED` até provar o contrário com
> arquivo:linha ou artefato rastreável. "Está documentado" não é veredito de
> correção. Contradição interna do próprio documento é CRITICAL por padrão, mais
> grave que divergência com o código. Nenhuma linha de código foi alterada nesta
> rodada — isto é achado, não correção.

## Resumo executivo

V4.1 é, na parte que audita o V3.2 (Camada 0, T0.4, as 54 divergências, o
`evidence_ledger`), **rigoroso e bem ancorado** — os números que cita desses dois
artefatos batem exatamente. Mas o documento constrói, em cima dessa base sólida,
uma segunda camada de afirmações — o caso multi-ativo inteiro (§0.1–§2.9) e duas
reaberturas arquiteturais maiores do projeto (HMM de regime, Meta-Model, §0.3) —
**sem nenhum artefato correspondente neste repositório**. Não há um único arquivo
em `experiments/`, `audit/` ou `config/constants.yaml` para ETHUSDT, SOLUSDT,
BNBUSDT ou XRPUSDT. É a mesma classe de erro que o projeto já cometeu três vezes
(ATR presumido, fórmula de concorrência, "≥3 unidades" inventado) — só que desta
vez a mise-en-scène e o rigor do resto do documento tornam mais fácil não notar.

| severidade | achados |
|---|---|
| CRITICAL | 4 |
| HIGH | 3 |
| MEDIUM | 2 |
| **Confirmado correto** (controle de qualidade positivo) | 4 |

---

## CRITICAL

### C1 — Todo o caso multi-ativo não tem um único artefato no repositório

`git ls-files` não retorna nenhum arquivo para `ethusdt`, `solusdt`, `bnbusdt`,
`xrpusdt`, `exchangeinfo`, nem qualquer variante de "multi-ativo". `experiments/`
tem 17 arquivos — todos BTCUSDT. `audit/` tem 3 arquivos — nenhum cross-asset.

Isso significa que **todas** as tabelas de §0.1 (quantização por ativo), §0.2
(ATR/custo/breakeven por ativo), §2.1–§2.9 (metrics/BVOL/bookTicker/volume/
correlação por ativo) e §5.2 (filtros ETH/SOL/BNB/XRP) são afirmações sem
artefato correspondente neste repo. A única linha da tabela de §5.2 que bate com
algo já commitado é a do **BTCUSDT** (`config/constants.yaml:31-43`, `step_size:
0.001`, `min_notional: 50.0`, provenance `MEASURED`, `source: "exchangeInfo
BTCUSDT... snapshot 2026-08-08"`) — as outras quatro linhas não têm equivalente.

O cabeçalho do documento declara "**Base factual verificada:** `exchangeInfo` (5
símbolos) · catálogo `data.binance.vision` por fonte × ativo". Se essa verificação
aconteceu, o artefato que a materializa não está no repositório que estou
auditando — o que, pela própria Regra Zero do projeto (`CLAUDE.md`, "Meça antes
de afirmar"), torna a palavra "verificada" não sustentável a partir daqui. Isto
não é uma dúvida sobre se os números estão certos — é a ausência do rastro que
permitiria a qualquer pessoa, inclusive o próprio Manager em 6 meses, refazer a
verificação.

**Ação exigida antes de qualquer coisa em §0–§2 ser tratada como fato:** os
mesmos artefatos que existem para BTCUSDT (`data/capacity/`, quality reports,
`experiments/*.json`) precisam existir para os outros 4 ativos, versionados,
antes que uma decisão de arquitetura (5 ativos, 3 TFs, reabertura de HMM/Meta)
seja tomada em cima deles.

### C2 — `N_eff = 32.608` (regime) e `N_eff ≈ 13.000` (Meta-Model) não existem em nenhum lugar do repositório

`grep -rn "32.608\|32608\|13.000\|13000"` no repo inteiro (excluindo `.venv`) não
retorna nenhuma ocorrência fora do próprio `PRD_V4_1.md`. Estes dois números são
o argumento inteiro de §0.3 para reabrir **duas** decisões arquiteturais que o
V3.2 havia fechado por medição (HMM de regime rejeitado por `N_eff` insuficiente;
Meta-Model adiado por `N_eff` insuficiente, §6.1/§6.3 do V3.2). Reverter as duas
com um número que não tem cálculo, script, nem arquivo de saída localizável é
estrutural, não cosmético — é o *DSR ao contrário*: ao invés de um Sharpe sem
piso de significância, é uma decisão de arquitetura sem numerador nem denominador
auditáveis.

Se o cálculo existe fora deste repositório (planilha, notebook, sessão
separada), a ação mínima é: persistir o script/artefato que produz esses dois
números, com a mesma disciplina de `provenance` que qualquer constante nova
exige. Sem isso, ambas as reaberturas são `ASSUMED`, classe A, e deveriam estar
marcadas como tal — não apresentadas como "a descoberta que reabre o projeto".

### C3 — "Learner é o estágio com 0% de verde" (§4.3) é mecanicamente impossível de derivar dos dois artefatos que o documento cita, e o próprio documento já avisou sobre exatamente este erro duas seções antes

Verificado diretamente: `audit/evidence_ledger.yaml` **não tem campo `estagio`**
em nenhuma das 160 entradas — só `fase` (Faixa 1, Faixa 1.5, Faixa 1.6, Faixa
1.7, Faixa 2...), que é um eixo cronológico de sessão de pesquisa, não a
taxonomia de 12 estágios de `code_discovery.json`. E `code_discovery.json` não
tem `status: verde/amarelo/vermelho/cinza` nenhum — seu campo `status` é só
`presente`/`ausente` por estágio. **Não existe, hoje, nenhuma junção mecânica
entre os dois arquivos que produza uma "% de verde por estágio de pipeline".**

O próprio V4.1, em T0.6 (§3.1), já nomeia esse exato problema: *"A classificação
por estágio usada na análise preliminar **não existe no inventário** — foi
produzida por regex sobre `feature_ou_filtro`. Os percentuais por estágio são
**indicativos, não medição**."* Isso é uma confissão precisa e correta. Mas §4.3
usa esse mesmo tipo de estatística — não reconhecida em nenhum lugar como
regex/indicativa — como justificativa de peso real para uma decisão de
orçamento (excluir o Learner dos 15 trials, exigir emenda para reabrir). Um
documento que nomeia a armadilha e cai nela quatro parágrafos depois é uma falha
de processo, não de intenção — e é exatamente o tipo de erro que a Regra Zero
existe para prevenir mecanicamente, não por vigilância manual.

### C4 — `inventario_master.json`, citado no cabeçalho como um dos três pilares da "base factual verificada", não é um arquivo versionado neste repositório

`git ls-files | grep inventario_master` não retorna nada. O artefato canônico e
commitado equivalente é `audit/evidence_ledger.yaml` (mesmas 160 entradas,
mesmo conteúdo, formato YAML em vez de JSON, com regra de append-only
documentada). Citar um arquivo que só existe como artefato de sessão — não
como parte do histórico do repositório — na abertura de um documento que se
define pela precedência de `N_lifetime` e rastreabilidade (a própria razão de
ser da nota "Emenda, não substituição" logo abaixo) é uma inconsistência entre
o que o documento *promete* sobre proveniência e o que o documento *faz* na sua
própria primeira citação de fonte.

---

## HIGH

### H1 — O fator de redundância transversal (`N_trial ≈ 1,7`, §6.2) não aparece em nenhum lugar da aritmética do orçamento real (§6.1)

§6.2 declara a fórmula `N_trial = fatores_efetivos(ativos) × fatores_efetivos(TFs)
≈ 1,15 × ~1,5 ≈ 1,7` e trata isso como o multiplicador correto para descontar o
custo de uma hipótese testada nas 15 combinações. Mas a tabela de orçamento em
§6.1 (M4 regime = 6, barreiras = 4, pesos = 2, features = 1, Meta-Model = 2,
soma 15) não mostra esse desconto sendo aplicado em nenhuma linha — são inteiros
simples. Não há como saber, lendo o documento, se "M4 ≤ 6 trials" já é *líquido*
do fator 1,7 ou se é *bruto* e o fator ainda precisa ser aplicado depois. A
"condição dura" que o próprio §6.2 registra — *"se em qualquer momento a melhor
combinação for escolhida, `N_trial = 15` e o piso do DSR salta para além do
orçamento"* — mostra que os autores sabem que o erro aqui é caro. Um documento
que declara essa fórmula como parte da governança do projeto e não a amarra à
tabela de orçamento que ela deveria descontar deixa a ambiguidade exatamente
onde ela é mais perigosa: entre a promessa e o gasto real.

### H2 — "94% em tendência de alta, lift 1,82x" (§2.10) não bate com a medição correspondente em `evidence_ledger.yaml`

A entrada mais próxima no ledger é `faixa17-q1-r3-alta-trivial`: **85,8%** do
book long em R3 (não 94%), e `f2-d1-long-r3-lift`: lift **1,72** (p≈0), não
1,82. A diferença não é arredondamento (85,8 → 94 é 8 pontos percentuais; 1,72 →
1,82 é uma casa decimal inteira de diferença). Ou V4.1 está citando um número de
uma medição diferente e não referenciada, ou há um erro de transcrição — nos
dois casos, o número usado para caracterizar "o viés de beta long que dominou a
V3" precisa reconciliar com a fonte de registro antes de ancorar a decisão de
janela comum de §2.10.

### H3 — `confidence_rank` descrita como "existe... nunca foi avaliada" (§4.4) subestima a lacuna real, que é de engenharia, não de avaliação

O `code_discovery.json` (estágio `09_CALIBRAÇÃO`, já auditado nesta mesma sessão)
encontrou que `confidence_rank` **não está** em `PREDICTIONS_SCHEMA_COLUMNS` —
não é gravada em `predictions.parquet` de produção, só calculada ad-hoc, em
memória, num script de análise (`src/analysis/faixa1_5_prerequisites.py`). "Existe
(§5.12) e nunca foi avaliada" (§4.4 de V4.1) lê como "a coluna está lá, falta só
rodar um teste nela" — quando na verdade falta primeiro **persistir a coluna em
produção**, um passo de engenharia anterior a qualquer avaliação. A Camada 3
(§4.4) que planeja avaliá-la precisa incluir esse passo explicitamente, ou vai
descobrir o furo tarde.

---

## MEDIUM

### M1 — O piso do DSR (§6.1, tabela `SR_0` por `N`) herda, sem ressalva, a mesma incerteza metodológica de `sigma_SR` já registrada no `SPRINT_LOG` como não-consensual

A tabela (`N=45 → SR_0=0,874`, até `N=60 → SR_0=0,917`) é aritmeticamente
consistente com `src/validation/dsr.py` e com o cálculo já feito nesta sessão
(DSR do "long+C07" = 0,167). Mas essa mesma sessão já registrou explicitamente
que a escolha de proxy para `sigma_SR` (erro-padrão do próprio Sharpe observado,
sem consenso único na literatura quando a distribuição real por trial não foi
rastreada) é uma decisão metodológica, não um número definitivo — e o V4.1 usa a
tabela sem repetir essa ressalva, no documento que vai governar decisões de
"encerrar" (§6.5, critério 6: "DSR final < 0,50 → encerrar"). Não invalida a
tabela; mas um critério de encerramento binário apoiado num número com incerteza
de método não declarada merece a mesma nota de cautela que o resto do documento
aplica em outros lugares (ex. §0.2, a ressalva sobre ATR de 4 meses).

### M2 — Dependência de ordem entre T0.4 (triagem das 54 divergências, Camada 0) e §6 (Governança, que já assume `N_lifetime`/ledger como método resolvido)

T0.4 lista, como trabalho ainda a fazer, classificar cada uma das 54 divergências
em `corrigir-PRD`/`corrigir-código`/`ambiguidade-de-vocabulário` — e uma delas
(catalogada nesta mesma auditoria como divergência #45, `N_effective` estático de
960 do PRD vs. `N_lifetime` do ledger) é precisamente o método que §6.1 já usa
como se estivesse decidido. Não é um erro — é plausível que a decisão já esteja
tomada informalmente — mas o roadmap (Parte VIII) não declara essa dependência
explicitamente, e um documento este rigoroso sobre precedência causal entre
camadas (§3.0: "nenhuma camada abre antes da anterior fechar com resultado
registrado") deveria aplicar a mesma disciplina à própria seção de governança.

---

## Confirmado correto (controle de qualidade positivo)

Para não desequilibrar o relatório só para o lado do achado — o que foi checado
e bateu:

- **BTCUSDT em §5.2** — `step_size 0.001`, `min_notional 50` batem exatamente com
  `config/constants.yaml:31-43`, incluindo a mudança 100→50 em 2026-04-14.
- **`pyproject.toml:159`** (§4.5) — a linha citada é exatamente o TODO
  `"alpha não pode importar meta"`, correto caractere a caractere.
- **"19 parâmetros" do Learner (§4.3)** — bate exatamente com a contagem de
  `parametros` do estágio `08_LEARNER` em `code_discovery.json` (19).
- **`N_lifetime = 45`, "54 divergências", "160" entradas do ledger** — todos
  batem exatamente com `audit/n_lifetime.yaml::counter`, `code_discovery.json`
  (54 `divergencias_prd` somadas) e `audit/evidence_ledger.yaml` (160 `entries`).
  A parte do V4.1 que audita o próprio trabalho desta sessão é rigorosa.

---

## Adendo (2026-08-10) — inventário de filesystem sobre `data/capacity/`/`data/raw/`, C1 confirmado E aprofundado

Levantamento mecânico (nomes/contagem de arquivo, sem abrir parquet) sobre os 5
símbolos, feito para decidir o que falta baixar antes de qualquer medição
multi-ativo. Duas correções concretas às tabelas do V4.1, ambas verificáveis
por qualquer pessoa via `ls`/`dir`:

**A1 — a "janela comum" real dos 4 alts começa em 2023-01-01, não 2021-12-01.**
`klines_1m`, `metrics` e `funding` para ETHUSDT/SOLUSDT/BNBUSDT/XRPUSDT existem
**uniformemente e sem gaps** de 2023-01-01 até 2026-08-07 — mas **zero arquivos
existem antes disso**, para qualquer um dos 4, em qualquer fonte. O V4.1 §2.1
(F1) declara que `metrics` dos 4 não-BTC "começa 15 meses depois" do BTC, citando
início em **2021-12** para os quatro — e usa esse número para fixar a "janela
comum" do projeto em 2021-12-01→2026-08-01 (§2.1, decisão; §0.4 escopo; roadmap
V41-1). Isso não bate com o que está no disco: a lacuna real é de **~25 meses**
(2021-12→2023-01), não zero. Ou o catálogo `data.binance.vision` upstream tem
esse histórico e só não foi baixado (mais provável, dado que o download em si
não deixou rastro de proveniência — ver A3), ou o número "2021-12" do V4.1 está
errado. De qualquer forma, **toda medição multi-ativo que assumir a janela
2021-12→2026-08 hoje vai rodar sobre um subconjunto vazio pros 4 alts antes de
2023-01** — isso precisa ser resolvido (baixar o histórico que falta, ou
corrigir a janela declarada) antes de M1–M6 da Camada 1 rodarem cross-asset.

> **Resolução (2026-08-11).** Gap fechado: `src/data/download.py` (novo,
> commit `9b12cdd`) baixou `klines_1m`/`metrics`/`funding` de
> `data.binance.vision` pros 4 alts, 2021-12-01→2022-12-31, com verificação
> SHA256 (0 `checksum_mismatch` em 3.316 arquivos escritos). Confirmado em
> disco: `klines_1m`/`metrics` agora cobrem 2021-12-01→2026-08-07 nos 4
> símbolos (ETH/BNB completos, 1711/1711 dias; SOL/XRP com 5 gaps genuínos
> — 2022-02-26/27/28 e 2022-04-01/02, `missing_upstream` confirmado, não
> falha de download — mesmas datas em que `book_depth` já tinha gap pros 5
> símbolos simultaneamente, ver auditoria original, seção "book_depth"
> acima, provável outage upstream). `funding` completo, 56/56 meses. A
> "janela comum" 2021-12→2026-08 do §2.1 agora tem lastro real em disco
> pros 5 ativos — deixa de ser bloqueio pra M1–M6. Achado lateral: o
> primeiro run crashou em `count_long_short_ratio`/colunas de razão vazias
> (`""`) nos primeiros dias de `metrics` — bug de cast estrito em
> `download.py`, corrigido no commit `2e60060` (nulls agora atravessam
> colunas que `schemas.py` já declarava nullable, em vez de derrubar o
> processo).

**A2 — `bookTicker` NÃO é "idêntica nos cinco" nem cobre até 2025-11 (§2.4, F4).**
O V4.1 afirma textualmente: *"Janela útil de microestrutura: 2023-05 → 2025-11,
~30 meses, idêntica nos cinco."* O filesystem mostra o oposto: `data/raw/
book_ticker/` só tem pasta para **BTCUSDT** — nenhuma para os outros 4 — e a
janela real em disco é **2023-05-16 → 2024-03-30 (~10,5 meses)**, não até
2025-11. `agg_trades` (fonte separada, também citada como base do Grupo F) é
igualmente BTC-only, isso o V4.1 não erra. Mas a alegação central de F4 —
microestrutura disponível e comparável nos 5 ativos — está factualmente errada
pelo que existe hoje neste repo. Se a fonte com a janela completa existe em
algum lugar (backfill não commitado, sessão separada), o artefato correspondente
precisa aparecer no repo antes de qualquer decisão sobre o Grupo F se apoiar
nela — mesmo padrão de C1/C2 acima.

**A3 — `data/capacity/_download_log/*.jsonl` não serve como prova de
proveniência por símbolo.** Nenhum dos 8 arquivos de log tem campo `symbol`;
a maioria está truncada em 2022-12 enquanto o filesystem real vai até
2026-08; todos os timestamps `ts` são do mesmo dia (2026-08-08), sugerindo
regeneração recente, não um log cumulativo real. Não dá pra reconstruir quando/
como os dados dos 4 alts foram baixados a partir disso — só o filesystem em si
(contagem e range de datas de arquivo) é confiável hoje.

**Não é achado novo de severidade C1–C4** (já cobertos acima) — é a
**quantificação concreta** do que C1 já apontava em abstrato ("nenhum artefato
para os 4 símbolos"): agora sabemos exatamente que cobertura existe (2023-01→
2026-08, sem gaps, para klines/metrics/funding), o que falta (25 meses de
histórico anterior, mais todo o book_ticker dos 4 alts), e que duas alegações
factuais específicas do V4.1 (§2.1 data de início, §2.4 cobertura de
bookTicker) não sobrevivem à checagem contra o filesystem local.

---

## Veredito

V4.1 aplica ao V3.2 exatamente o escrutínio que este projeto diz valorizar — e
onde audita artefatos que já existem no repo, o faz bem. O problema não é o
método; é que o mesmo documento usa esse método com uma mão e o abandona com a
outra assim que o assunto vira o caso multi-ativo. **C1–C4 não são achados sobre
se os números estão certos — são sobre se existe, hoje, algum jeito de verificar
que estão**, o que é uma barra mais baixa e mais urgente. Nenhuma decisão de
arquitetura (5 ativos, 3 TFs, reabertura de HMM, reabertura de Meta-Model)
deveria se apoiar nesses números até C1 e C2 estarem resolvidos.
