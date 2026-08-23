# Núcleo Funcional, Casca Imperativa — Validação da Ideia e Arquitetura v1

**Status:** Fase 4 — validação + desenho, ZERO implementação de código nesta
sessão. Segue o framework da skill `/engineering:system-design` (Requirements
→ High-Level Design → Deep Dive → Scale/Reliability → Trade-offs).

**Pedido original (verbatim):** *"Leia o HTML @nucleo-casca.html dentro de
docs e use skill system-desing para validar a ideia e desenhar arquitetura e
implementação no nosso projeto."*

**Fonte avaliada:** `docs/nucleo-casca.html` — ensaio já escrito propondo o
padrão *Functional Core, Imperative Shell* (Gary Bernhardt, 2012), citando
*Hexagonal Architecture* (Cockburn, 2005) e *Hidden Technical Debt in ML
Systems* (Sculley et al., NeurIPS 2015 — *training-serving skew*), com
NautilusTrader como prova de existência no domínio quant. Propõe layout
`core/`+`scripts/run_*.py` e um par explícito `.batch(df)`/`.streaming(
buffer, novo_ponto)` com teste de paridade único.

**Achado que muda o enquadramento inteiro da tarefa:** esta não é uma decisão
de "adotar ou não um padrão novo" — é validar/fechar a lacuna de um padrão
que **já é a norma dominante do repo** (~25+ módulos seguem a disciplina),
nunca formalizado nos 2 documentos canônicos do projeto
(`ADR-001`/`PLANO_MESTRE_PRINCE2.md` têm zero menções). A pergunta real é:
formalizar o quê, exatamente como o repo já pratica (não como o HTML
idealiza em abstrato), e fechar quais violações reais.

---

## §1 — Validação da ideia (Requirements Gathering)

### 1.1 A ideia é sólida?

Sim, em três eixos independentes:

1. **Literatura real, não invenção.** As 3 citações do HTML checam —
   Bernhardt 2012 é o termo de origem; Cockburn 2005 é o padrão-irmão mais
   antigo (Hexagonal/Ports & Adapters); Sculley et al. 2015 nomeia
   formalmente o risco que a separação evita (*training-serving skew*).
2. **Prova de existência no domínio exato.** NautilusTrader (motor de
   trading algorítmico open-source) declara este desenho como objetivo de
   arquitetura — não é transposição de engenharia de software genérica pra
   um domínio onde não se aplica.
3. **Origem histórica NO PRÓPRIO PROJETO, nunca promovida.**
   `PRD_V3_2_UNIFICADO.md §2.0, Princípio 3` (documento hoje obsoleto, mas
   histórico real) já dizia, literalmente: *"Caminho único. O mesmo código
   gera features em lote e em streaming. Não existem duas implementações."*
   O requisito de paridade `<1e-8` já vive como item de DoD em `CLAUDE.md`
   (escopado só a "Código de feature") e como teste #14 de
   `src/validation/leakage.py`. A ideia não é nova pro projeto — é uma boa
   ideia antiga que nunca subiu de um PRD obsoleto pros 2 documentos que
   hoje mandam.

### 1.2 Mas a proposta LITERAL do HTML não é a que este repo já prova funcionar

O HTML propõe um par de métodos genérico, `.batch(df)`/`.streaming(buffer,
novo_ponto)`, com um layout `core/`+`scripts/` que não corresponde à árvore
real (`src/`, sem pasta `scripts/`). Investigação de código encontrou que o
repo já tem **dois idiomas diferentes, comprovadamente corretos**, nenhum
dos dois sendo literalmente esse par de métodos (ver §2.2). Adotar o
vocabulário do HTML ao pé da letra significaria abandonar convenção já
provada por uma genérica — decisão a evitar.

### 1.3 Urgência real: BAIXA, não é gate bloqueando nada hoje

`src/live/` está confirmado vazio (só `__init__.py` de 4 linhas). O caminho
real até qualquer coisa exercitar um modo streaming de verdade passa por
6-7 estágios inteiros, a maioria "ZERO implementado" (Data Layer 0/9,
retreino do Alpha, Meta-Model, Decision Engine, Execução ~0%).
`PLANO_MESTRE_PRINCE2.md §15.15` já registra isso explicitamente: falta um
processo contínuo + teste de paridade lote↔streaming "pra quando o Live
entrar em pauta... não é bug a corrigir agora." **Conclusão:** isto é
trabalho de disciplina/documentação + fechar violações reais que já
custam caro HOJE (teste difícil, cobertura zero em funções de produção) —
não uma corrida contra um prazo de live trading.

---

## §2 — Estado real (auditoria de código, não suposição)

### 2.1 O padrão já é a norma dominante

Confirmado por leitura direta: `src/features/`, `src/regime/` (incluindo os
3 modelos de regime candidatos — HMM, Jump Model, BOCPD, todos com par
`fit_*`/`predict_*` puro), `src/labels/`, `src/models/` (`alpha.py`,
`backtest_lite.py`, `hhi.py`, `monotonic.py`, `stability.py`,
`environments.py` — confirmado sem nenhuma chamada de IO), `src/validation/`
(3 módulos 100% puros: `dsr.py`, `regime_utility.py`,
`volatility_walkforward.py`), `src/risk/` (`limits.py`/`kill_switch.py`
100% puros — a demonstração mais limpa do repo) e `src/data/` (`bars.py` —
ver 2.2) seguem a disciplina. Vocabulário compartilhado real: a palavra
"Núcleo" abre docstrings de módulo em pelo menos 6 arquivos.

### 2.2 Dois idiomas já provados — não um par `.batch()`/`.streaming()`

**Idioma A — "recompute sobre prefixo crescente"** (`src/features/
build.py`): uma função pura só (`compute_t1_features`), causal por
construção; "lote" = 1 chamada sobre a série inteira, "streaming" = N
chamadas sobre prefixos crescentes da mesma série. Simples, é o padrão
dominante hoje. Custo real, não resolvido (§2.5): recomputa do zero a cada
chamada — `support.expanding_percentile_rank_strict` reconstrói uma Fenwick
tree inteira por chamada, `ema`/`wilder_smooth` recalculam a série toda.
Paridade provada por `tests/parity/test_features_parity.py` (tolerância
`1e-8`, 5 símbolos, últimas 500 barras + ponto isolado).

**Idioma B — "carry/step/finish"** (`src/data/bars.py`, o padrão-ouro do
repo): `<tipo>_bars_carry()` (estado inicial) + `<tipo>_bars_step(carry,
chunk)` (processa 1 chunk, muta `carry`) + `<tipo>_bars_finish(carry)`
(fecha o stream). A função de conveniência de lote (`dollar_bars`,
`volume_bars`) é um wrapper fino que chama carry→step→finish com 1 chunk
só — **lote e streaming são literalmente o mesmo caminho de código**, não
"duas coisas testadas iguais". Docstring do módulo já diz isso: "garante
paridade por CONSTRUÇÃO, não só por teste". Paridade provada sob
particionamento de chunk ARBITRÁRIO (incluindo chunk vazio no meio),
`tests/unit/test_data_bars.py` — o teste mais exigente do repo.

**A diferença que importa pra decisão:** Idioma A é simples mas O(n) por
chamada; Idioma B é O(1) por barra nova mas exige um objeto de estado
(`carry`) explícito. Nenhum dos dois é o `.batch()`/`.streaming()` genérico
do HTML — são duas soluções já adaptadas ao problema real de cada caso.

### 2.3 Nunca formalizado nos documentos canônicos — achado de doc-drift

`docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md`
(canônico): zero menções a "núcleo funcional"/"functional core"/"caminho
único"/"paridade lote". `PLANO_MESTRE_PRINCE2.md`: 2 menções pontuais de
rastreamento de gap, não um enunciado de princípio. `CLAUDE.md`: só o item
de DoD já citado, escopado apenas a "Código de feature" — sem item
equivalente pra "Código de modelo"/"Código de execução"/"Código de regime".
`docs/nucleo-casca.html` nomeia o padrão e cita a literatura corretamente,
mas é **órfão**: nenhum outro arquivo do repo o referencia, não está
commitado, sem AG, sem seção no `PLANO_MESTRE`.

**Achado colateral de vocabulário:** o termo "Núcleo" é usado de forma
inconsistente — `src/regime/build.py:35` (ou linha próxima) usa a frase
"Núcleo com IO" pra descrever a camada que LÊ do disco, diluindo o sentido
técnico do termo (que deveria significar especificamente "sem efeito
colateral"). Vale corrigir junto da formalização.

### 2.4 Violações reais encontradas, priorizadas

Sweep confirmou: entrelaçamento **não é a norma**, é concentrado e
findável. 5 violações reais, por severidade (números de linha do
levantamento — confirme antes de editar, podem ter mudado):

1. **`src/labels/triple_barrier.py` (~linha 1186-1201, dentro de
   `build_labels_with_stats`) — a mais grave, por ser código de
   segurança/correção de label.** O loop que calcula TP/SL/toque de
   barreira chama `_resolve_filters_cached` → `load_filters_asof` — leitura
   real de disco — por dentro do "núcleo". Diferente de `src/risk/
   sizing.py` (que separa `compute_sizing`, puro, de `compute_sizing_asof`,
   o wrapper de IO), `LabelConfig`/`build_labels_with_stats` não expõem
   ponto de injeção pra `snapshots_dir`/filtros pré-resolvidos. Custo real
   já pago: o teste unitário (`tests/unit/test_labels_triple_barrier.py`)
   precisa fixar a data sintética pra bater com o único snapshot real em
   disco, em vez de poder injetar um filtro arbitrário.
2. **`src/analysis/faixa2_caminho_b.py::run_fase2_e1` (~linha 786-900+) —
   a mais severa em termos de cobertura.** Mistura `lake.query_bars`/
   `lake.query_funding` (IO real) com uma grade de busca real (18 células,
   TP/SL/lado) chamando `resolve_barriers_vectorized` — cálculo genuíno,
   não só leitura. **Zero testes** — grep por `run_fase2_e1` em `tests/`
   não retorna nada.
3. **`src/analysis/faixa1_5_prerequisites.py::run_faixa1_5` (~linha
   781-799) — violação silenciosa.** A assinatura (`predictions`,
   `mf_data`, `splits`) sugere pureza, mas chama `_hhi_by_fold_side()`
   (zero-arg) que faz glob+leitura de `models/{model_id}/diagnostics/
   *.json` por dentro — invisível na assinatura. `run_faixa1_5` nunca é
   testado como unidade (só suas sub-peças são, isoladamente) — evidência
   empírica de que o entrelaçamento tem custo real, não só estético.
4. **`src/analysis/attribution.py::_aggregate_side` (~linha 387-424).**
   Leitura de JSON de disco na mesma função que a agregação estatística
   real (`np.mean`/`np.std` sobre `gain_by_column`). Testável via
   `tmp_path` hoje, então menos grave que os 3 acima, mas ainda acoplado.
5. **`src/models/pipeline.py::run_layer1_sprint` — menor, observação, não
   violação dura.** É o orquestrador esperado (IO é o papel dele) — mas 2
   decisões reais (fórmula de tamanho de amostra do baseline B1; regra de
   pass/fail do Gate 3.4, `mean_hhi_effective < 0.25`) estão inline, sem
   função nomeada testável fora do pipeline CPCV completo. Mesmo tipo de
   achado que `AG-114`/`AG-118` já ensinaram sobre critério de gate
   precisar de definição operacional independente do momento de aplicação.

### 2.5 Gap de desempenho — registrado, NÃO resolvido aqui

Idioma A (`support.py`) prova corretude sob paridade, mas não tem desenho
pra custo O(1) por barra nova — um motor live real chamando essas
primitivas a cada candle pagaria o custo de recomputar a série inteira
toda vez. **Não é bug hoje** (não existe `src/live/` ainda, §1.3) — é uma
lacuna de desempenho a considerar SE/QUANDO o caminho streaming de verdade
for construído. Registrar (§6), não resolver — bloquearia decisões que só
fazem sentido quando o motor live tiver requisito de latência real medido.

### 2.6 `docs/nucleo-casca.html` — órfão, autoria a confirmar

Arquivo modificado hoje (2026-08-23, mesmo dia), não commitado, não
referenciado em nenhum documento canônico. **Não sei se este arquivo é seu,
de uma sessão sua anterior hoje, ou de outra fonte** — dado o padrão real
de sessões paralelas trabalhando neste mesmo repo hoje (confirmado
diretamente: a governança do trabalho anterior desta sessão colidiu com
achados de uma sessão paralela real, reconciliados via `AG-177`). Vale
confirmar antes de decidir o destino dele (§3/D-05) — não bloqueia o resto
deste documento.

---

## §3 — Decisões de arquitetura

### D-01 — Formalizar o princípio nos documentos canônicos, com vocabulário preciso

**Decisão:** promover o princípio (não a proposta literal do HTML) pra
`CLAUDE.md` (regra operacional, o que já funciona como "instruções vivas"
lidas toda sessão) e `PLANO_MESTRE_PRINCE2.md` (registro de decisão,
mesmo padrão das seções `§15.NN` já usadas neste projeto o dia inteiro).

- **`CLAUDE.md`**: nova entrada curta nas "Diretrizes de comportamento" ou
  seção própria — nomeia o padrão ("núcleo funcional, casca imperativa"),
  cita Bernhardt 2012 como origem, referencia `docs/nucleo-casca.html`
  como leitura de apoio (não como spec a seguir literalmente — ver D-05).
  Vocabulário fixado: **"núcleo"** = zero I/O, zero rede, zero
  paralelismo, recebe/devolve dado em memória — nunca usado pra descrever
  uma camada que toca disco (corrige a diluição achada em `regime/
  build.py`). Camada de IO/orquestração: **"ponto de entrada com IO"**
  (termo já em uso real em `cost_surface.py`/`m4_regime_comparison.py`/
  `features/build.py`/`labels/triple_barrier.py` — reusar, não inventar
  termo novo).
- **DoD ampliado**: o item de paridade lote↔streaming (`<1e-8`, últimas
  500 barras) hoje só existe pra "Código de feature" — estender o
  PRINCÍPIO (não necessariamente o teste formal, que só se aplica quando
  existe segundo caminho real) pra "Código de modelo"/"Código de labels"/
  "Código de regime": todo núcleo novo PRECISA ser 100% puro; teste de
  paridade formal só é exigido quando um segundo ponto de entrada
  (streaming) realmente existir — mesma disciplina que
  `leakage.py::_test_14` já pratica (PASS por ausência genuína de escopo,
  não FAIL, não teste inventado).
- **`PLANO_MESTRE_PRINCE2.md`**: nova seção `§15.NN` registrando a decisão,
  citando os 2 idiomas (D-02) como as formas SANCIONADAS de implementar o
  princípio neste repo — não a proposta genérica do HTML.

### D-02 — Dois idiomas sancionados, critério de quando usar qual

**Decisão:** não adotar um único par `.batch()`/`.streaming()` genérico.
Formalizar os 2 idiomas já provados como as opções oficiais:

- **Idioma A (recompute sobre prefixo)** — default. Use quando a
  computação é barata o suficiente pra recomputar do zero a cada chamada
  (a maioria dos casos hoje) OU quando ainda não existe requisito de
  latência medido que justifique o custo de manter estado.
- **Idioma B (carry/step/finish)** — use quando a computação é
  genuinamente estatal/acumulativa por natureza (ex. barras que fecham por
  condição acumulada, como `bars.py`) OU quando um requisito de latência
  real (medido, não hipotético) tornar o custo O(n) do Idioma A
  proibitivo.

Critério explícito evita a "3ª opção" nunca cogitada: inventar um par de
métodos novo por módulo sem seguir nenhum dos dois idiomas já provados.

### D-03 — Fechar as 5 violações de §2.4, por prioridade

1. `triple_barrier.py` — extrair um núcleo puro que recebe filtros
   PRÉ-RESOLVIDOS (dict `date -> Filters`, ou similar), mais um wrapper de
   IO que resolve `snapshots_dir`+datas antes de chamar — mesmo padrão já
   usado em `sizing.py::compute_sizing`/`compute_sizing_asof`. Reusar o
   padrão existente, não inventar um novo.
2. `faixa2_caminho_b.py::run_fase2_e1` — separar em núcleo puro (recebe
   `bars`/`funding`/`mf_data`/`predictions`/`splits`/grid já em memória,
   devolve resultado da grade) + wrapper que resolve `lake.query_bars`/
   `lake.query_funding` a partir dos bounds de `mf_data`.
3. `faixa1_5_prerequisites.py::run_faixa1_5` — `_hhi_by_fold_side` ganha
   parâmetro explícito (`model_id`/`diagnostics_dir`) injetado pela casca
   (`run_and_save_faixa1_5`), em vez de resolver globbing sozinha —
   mesmo padrão que o resto do MESMO arquivo já usa corretamente.
4. `attribution.py::_aggregate_side` — separar `_load_payloads(files) ->
   list[dict]` de uma `_aggregate_payloads(payloads, ...)` pura.
5. `pipeline.py::run_layer1_sprint` — extrair a fórmula de tamanho de
   amostra B1 pra `baselines.py` e a regra do Gate 3.4 pra `alpha.py`/
   `hhi.py`, como funções nomeadas e testáveis.

Cada um desses é um Pacote de Trabalho pequeno e independente — não
precisam ser feitos juntos nem na mesma ordem. `1` e `2` são as únicas com
severidade real (segurança de label; zero cobertura de teste); `3`-`5` são
qualidade/manutenibilidade.

### D-04 — Gap de desempenho das primitivas (§2.5): registrar, não resolver

B23: não inventar um redesenho de `support.py` pra um requisito de
latência que ainda não existe (`src/live/` vazio). Registrar como achado
de arquitetura pra quando o motor live entrar em pauta de verdade.

### D-05 — Destino de `docs/nucleo-casca.html`

Proposta: manter como documento de APOIO/justificativa (a citação de
literatura e o argumento "isso é padrão reconhecido, não gosto pessoal"
continuam valiosos), referenciado a partir de `CLAUDE.md`/`PLANO_MESTRE`,
mas **não tratado como spec de implementação** — a arquitetura real (2
idiomas, não um par genérico; violações concretas a fechar) vem deste
documento, informado por leitura de código real, não do ensaio abstrato.
Commitar o HTML junto da formalização (D-01), com uma nota de rodapé
esclarecendo essa relação. **Pendente confirmação sua sobre a autoria/
origem antes disso** (§2.6).

---

## §4 — Plano de implementação (ordem sugerida)

1. D-01 (formalização em CLAUDE.md/PLANO_MESTRE) — baixo risco, alto valor,
   pode ir primeiro e sozinho.
2. D-03 item 1 (`triple_barrier.py`) — maior severidade real, mas mexe em
   código de produção ativo (label engine) — precisa de testes de
   regressão antes/depois confirmando bit-exatidão do output pros dados já
   existentes.
3. D-03 item 2 (`faixa2_caminho_b.py`) — zero teste hoje, então qualquer
   refatoração PRECISA vir acompanhada dos testes que faltam, não só do
   split estrutural.
4. D-03 itens 3-5 — baixo risco, podem ser feitos em qualquer ordem,
   inclusive em paralelo por sessões diferentes.
5. D-04/D-05 — não são "implementação", são decisões de registro/curadoria.

## §5 — Trade-offs

- **Formalizar agora vs. esperar o live ficar próximo**: formalizar agora
  custa pouco (documentação + fechar 2 violações reais que já doem hoje em
  teste/cobertura) e evita a formalização ficar pra quando o live for
  urgente e a pressão de prazo incentivar atalho. Contra: burocracia
  adicional em CLAUDE.md que só paga dividendo quando o live existir.
  **Decisão deste documento: formalizar agora, é barato.**
- **Idioma A como default vs. Idioma B como default**: A é mais simples de
  escrever e é o que a maioria dos autores já produz organicamente; B é
  mais caro de implementar mas paga em produção quando o custo O(n) real
  importa. Escolher A como default, B só quando justificado, evita
  over-engineering prematuro (mesmo racional de D-04).
- **Corrigir as 5 violações de uma vez vs. uma de cada vez**: uma de cada
  vez, como Pacotes de Trabalho independentes — item 1/2 já têm risco real
  suficiente pra merecer revisão independente própria (`src/labels/` e
  `src/analysis/` — este último não está na lista de pacotes que exigem
  `project_assurance` sempre, mas `src/labels/` está).

## §6 — Governança proposta (não aplicada nesta sessão)

- Novo item de decisão em `PLANO_MESTRE_PRINCE2.md` (D-01/D-02 deste
  documento).
- Novo achado registrável em `audit/architecture_gaps_log.yaml`: as 5
  violações de §2.4, cada uma com severidade própria (a de
  `triple_barrier.py` merece `project_assurance` antes de fechar, dado que
  `src/labels/` está na lista de pacotes que exigem revisão independente
  sempre).
- O gap de desempenho de §2.5/D-04 — registrar como achado de baixa
  prioridade, sem prazo.

## §7 — Referências

- `docs/nucleo-casca.html` (fonte avaliada).
- `src/data/bars.py`, `tests/unit/test_data_bars.py` (Idioma B, padrão-ouro).
- `src/features/build.py`, `tests/parity/test_features_parity.py` (Idioma A).
- `src/risk/sizing.py` (único lugar do repo que documenta em prosa o motivo
  da separação núcleo/wrapper).
- `src/validation/leakage.py::_test_14_paridade_lote_streaming` (registro
  oficial do alcance real hoje do padrão).
- `PRD_V3_2_UNIFICADO.md §2.0` Princípio 3 (origem histórica, citação de 1
  linha apenas — documento obsoleto, não base de decisão).
- `docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md`
  (confirma, por ausência, que o princípio nunca foi escrito no lugar que
  manda).
- `src/labels/triple_barrier.py`, `src/analysis/faixa2_caminho_b.py`,
  `src/analysis/faixa1_5_prerequisites.py`, `src/analysis/attribution.py`,
  `src/models/pipeline.py` (violações, §2.4).
