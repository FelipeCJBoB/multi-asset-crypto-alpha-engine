# Prompt de execução — ADR-004 ponta a ponta (Fases 1→3)

> Gerado 2026-08-25 por sessão paralela, **após validar cada afirmação
> abaixo contra o código real** (não contra memória nem contra o texto do
> ADR). Estado do repo no commit `10fbd78`.

---

Você vai continuar e **concluir o ADR-004 ponta a ponta**
(`docs/ADR-004_reformulacao_alvo_regra_decisao_e_inferencia_2026-08-25.md`).

## Antes de qualquer coisa: leia o addendum do §8

O §8 do ADR ganhou um **addendum em 2026-08-25** que corrige os dois números
que o parágrafo original usava. Se você planejar em cima do texto pré-adendo,
vai partir de premissas já refutadas:

- o `−2,2 bps` era **extrapolação**; hoje há medição — gap edge-custo
  **6,10 bps** após o relabel de `AG-229`;
- o `I² = 96–98%` estava medido na **grade errada** (relógio 15m); o real na
  grade de produção é **61–83%** (`AG-238`);
- **a leitura por lado INVERTE**: no 15m o SHORT era o lado de edge pooled
  ~nulo; na produção é o **pior**, nas três resoluções. Qualquer raciocínio
  que trate os dois lados como simétricos precisa ser relido.

## Estado real de cada fase — verificado no código, não presumido

**NÃO reimplemente o que já existe.** Isto foi conferido arquivo por arquivo:

| fase | estado real | onde |
|---|---|---|
| **0** — bootstrap por blocos | **implementada, 8 testes passam, NUNCA executada sobre dado real** | `src/validation/bootstrap_diff.py`, `backtest_lite.py::permanence_significance_by_path`, wireado em `pipeline.py:749` (`AG-241`) |
| **1** — alvo `μ` em unidade de retorno | **NÃO feita.** `objective="binary"` segue ativo | `src/models/alpha.py:685` (`AG-212`, `AG-213`) |
| **2** — regra lagrangiana | **mecanismo pronto e wireado; default NÃO flipado** | `alpha.py:340 decide_side`, `:368 resolve_joint_tau`, `_resolve_tau_on_common_bars`; `tau_policy` default `TAU_POLICY_LEGACY_PER_SIDE` (bit-exato) (`AG-210`) |
| **3** — ESS composto + PBO/CSCV | ESS **serial** fechado (`sum_uniqueness_train`, `AG-211`); ESS **transversal ABERTO** (`AG-216`); **PBO/CSCV não existem** | `src/validation/dsr.py`, `src/models/hhi.py` |

`N_lifetime` **não bloqueia**: `counter: 761`, `status:
descontinuado_2026_08_17 — não bloqueia mais trabalho` (`AG-077`). Continue
incrementando o log quando houver treino, mas não trate como gate.

## Ordem de execução

### Passo 1 — Fase 2 primeiro (é grátis e destrava a leitura de tudo)

O ADR põe a Fase 2 depois da 1, mas o mecanismo **já está construído**: só
falta flipar `tau_policy` e derivar o `λ`.

O próprio `AG-210` deixa uma instrução explícita que **não foi cumprida**:

> *"VERIFICAR PRIMEIRO, antes de flipar:
> `src/analysis/tau_diagnostics.py::tau_realization_diagnostic` JÁ mede a
> realização de tau OOS"*

Faça essa verificação **antes** de flipar. Existem dois `xfail` vivos em
`tests/unit/test_analysis_tau_diagnostics.py` dizendo que o `tau` in-fold
generaliza pior OOS do que o quantil nominal sugere
(`mean_ratio_to_target ≈ 0,24`). **Não ajuste o critério para passar** — esse
xfail é achado real, não teste desatualizado.

Falta ainda a parte lagrangiana propriamente dita: `λ = max(c, λ_B)`, com `c`
derivado do **custo** (`round_trip_cost_bps_maker_prob`, remedido três vezes,
hoje `0.4942`) e `λ_B` do orçamento de fees. Hoje `resolve_joint_tau` fecha o
grau de liberdade por **taxa de sinal orçada**, não por custo — são coisas
diferentes, e o ADR §4 pede a segunda.

### Passo 2 — Fase 0 executada de verdade

Ela roda dentro de `run_layer1_sprint`, sobre o `ret_net` daquele treino.
Ainda **não produziu nenhum resultado real** — só passou em teste sintético.

**Dois riscos que precisam ser medidos antes de confiar no primeiro
veredito** (encontrados na revisão, não hipotéticos):

1. **Zero-filling × block length — risco de FALSO POSITIVO.** A casca monta
   a série pareada sobre o universo completo de barras, com zero fora de
   sinal. A ACF de uma série majoritariamente zero decai depressa, então
   `select_block_length` devolve bloco **curto**, o IC fica **estreito
   demais** e o teste declara significância que não existe. É exatamente o
   erro que a Fase 0 existe para evitar.
   **Medição:** compare `select_block_length` sobre a série zero-filled
   contra a mesma medida só sobre as barras com sinal. Se divergirem muito,
   o zero-filling está diluindo a dependência e o block length precisa vir
   da subsérie com sinal.

2. **Custo O(n × n_boot) em Python puro.** `_stationary_bootstrap_indices`
   tem um loop Python de `n` iterações, chamado `n_boot` vezes. Os 8 testes
   passam em 5,81s porque usam séries curtas; sobre o universo completo de
   barras com `n_boot` na casa do milhar são ~10⁸ iterações **dentro do
   treino**. Vetorize antes de rodar em produção.

### Passo 3 — Fase 3, começando pela reconciliação

**Antes de escrever PBO/CSCV**, resolva uma duplicação que já existe:

| | `dsr.py:202 sharpe_difference_block_bootstrap` | `bootstrap_diff.py stationary_bootstrap_ci` |
|---|---|---|
| bloco | **fixo** (moving block) | **estacionário geométrico** (Politis-Romano) |
| comprimento | **estipulado pelo chamador** — B23 latente | **medido via ACF** |
| estatística | diferença de **Sharpe** | diferença de **média** |

São dois caminhos de cálculo para a mesma pergunta de fundo ("a diferença
entre duas estratégias é real?") — o risco que `AG-009`/`AG-129` catalogam.
Não são idênticos (Sharpe ≠ média), então **não force um merge cego**.
Decida e registre: ou `sharpe_difference_block_bootstrap` passa a usar
`select_block_length` (fecha o B23 latente e mantém as duas estatísticas),
ou fica documentado por que os dois coexistem.

Depois:

- **ESS transversal** (`AG-216`) — o próprio gap já diz **reusar, não
  reescrever**: `src/models/hhi.py::compute_effective_concentration`
  (participation ratio) sobre o espectro da matriz de correlação de `ret_net`
  entre os 5 símbolos alinhados por `t0`.
- **PBO/CSCV** — não existe nada; escrever do zero.

### Passo 4 — Fase 1 por último

É a única que exige **retreino real** e a única que toca o objetivo do
modelo. Faça depois que 0/2/3 estiverem dando leitura confiável — senão você
retreina sem instrumento para saber se o resultado mudou por sinal ou por
ruído, que é o problema que o ADR inteiro tenta resolver.

## Regras de coordenação (há outra sessão neste mesmo working tree)

Isto **já causou dano real hoje**: duas entradas do gaps log receberam IDs já
ocupados e precisaram ser renumeradas (`AG-239`/`AG-240`), e o Road Map Vivo
ficou dessincronizado.

- **Reserve a faixa `AG-250+`** para os achados desta linha de trabalho.
- `config/constants.yaml` e `audit/*.yaml` — **uma sessão por vez**. Avise
  antes de tocar.
- Commite em unidades coerentes e faça push; o working tree é compartilhado.

## Definition of done

- [ ] Fases 0, 2 e 3 com **resultado medido**, não só código que roda
- [ ] `AG-210`, `AG-212`, `AG-213`, `AG-214`, `AG-216` com `status` real
- [ ] Toda constante nova com `provenance` (§16.10); classe A com
      `sweep_range` **e** `sweep_required` coerentes — `AG-237` aconteceu
      exatamente por remover isso
- [ ] Nenhuma faixa esperada inventada — `TBD — medir no Sprint N` (B23)
- [ ] `uv run pytest -m "not slow and not integration"` verde
      (baseline atual: **1933 passed, 0 failed**)
- [ ] Se algum resultado contradisser o ADR-004, o ADR ganha **addendum**,
      nunca reescrita silenciosa

## O padrão a repetir

O achado mais valioso das últimas 24h não veio de escrever código novo: veio
de perguntar **"esta medição foi feita sobre a grade que produção usa?"**. A
resposta era não em sete módulos, e um deles decidia constante classe A
(`AG-232`). Aplique a mesma pergunta a cada número que você usar como base de
decisão aqui.
