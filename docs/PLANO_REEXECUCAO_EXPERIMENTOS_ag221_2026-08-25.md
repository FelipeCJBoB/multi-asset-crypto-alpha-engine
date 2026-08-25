# Plano ponta a ponta — re-execução dos experimentos após o relabel `AG-221`

**Data:** 2026-08-25 · **Status:** Camada 0 em execução; Camada 1 bloqueada por decisão
**Pedido do Manager:** *"Faça o inventário e me traga o plano ponta a ponta,
depois siga para CLI, mas pode pular run especificamente do alpha."*

---

## §1. Inventário medido

| | |
|---|---|
| JSON em `experiments/` | **112** |
| que derivam de `labels.parquet` | **78** (eram 67 antes; subiu com os artefatos desta investigação) |
| que **não** derivam (metadados, barras, código) | 34 |
| que embutem `config_hash` | **0** — ver `AG-226` |
| módulos de `analysis/` que escrevem em `experiments/` | **22** |

**Por que re-executar e não reler:** cada JSON é a *saída* de um pipeline que
consome `labels.parquet`. Trocar os labels não atualiza o JSON — ele fica
legível, plausível e obsoleto ao mesmo tempo. É o mecanismo exato do dano de
`AG-218`.

---

## §2. Camadas de dependência

### Camada 0 — só dependem de labels/bars → **executável agora** (16)

| módulo | CLI antes | artefato |
|---|---|---|
| `s1_tp_sl_sensitivity` | ❌ → ✅ | `s1_tp_sl_sensitivity_report.json` |
| `faixa2_e3_stability` | ❌ → ✅ | `faixa2_e3_stability.json` |
| `faixa2_dsr_and_b2_check` | ❌ → ✅ | `faixa2_dsr_and_b2_check.json` |
| `m6_common_factor_hypothesis` | ✅ | `m6_common_factor_hypothesis_report.json` |
| `m2_bar_comparison` | ✅ | `m2_bar_comparison_report.json` |
| `m3_timeframe_choice` | ✅ | `m3_timeframe_choice_report.json` |
| `m4_regime_comparison` | ✅ | `m4_regime_comparison_report.json` |
| `m4_critical_windows` | ✅ | `m4_critical_windows_report.json` |
| `gate_efficiency` | ✅ | `m4_critical_windows_report.json` |
| `cost_surface` | ✅ | `cost_surface_report.json` |
| `volatility_comparison` | ✅ | `volatility_rs_yz_vs_gk_report.json` + 1 |
| `volatility_operational_effect` | ✅ | `volatility_operational_effect_report.json` |
| `gk_vs_wilder_econ_regime_shift` | ✅ | `gk_vs_wilder_econ_regime_shift_report.json` |
| `faixa2_e2_research` | ✅ | `faixa2_e2_research.json` |
| `t2_ranking_ortogonalidade` | ✅ | por `{symbol}_{resolution_id}` |
| `t1_t2_orthogonality_by_combo` | ✅ | por `{symbol}_{resolution_id}` |

**Correção do inventário:** `m6_common_factor_hypothesis` foi classificado
inicialmente na Camada 1 por um grep que casou `predictions.parquet` — mas a
única ocorrência é a docstring dizendo que **não** precisa dele. É Camada 0, e
importa: é o teste que produziu `I² = 96–98%`.

---

### §2.1 — Qual grade cada módulo da Camada 0 realmente lê (`AG-233`)

**Descoberta que reordena todo o resto.** A grade canônica de produção é dollar
bar (R1/R2/R3) desde `AG-042` (2026-08-16). Mas **7 dos 16 módulos da Camada 0
leem a grade de relógio 15m**, que foi substituída:

| lê produção (dollar) | lê **legado 15m** | não lê labels |
|---|---|---|
| `m4_regime_comparison` | **`s1_tp_sl_sensitivity`** ⚠️ `AG-232` | `cost_surface` |
| `m4_critical_windows` (misto) | **`m6_common_factor_hypothesis`** ⚠️ | `faixa2_e3_stability` |
| `gate_efficiency` | `m2_bar_comparison` ✅ legítimo | `faixa2_dsr_and_b2_check` |
| `volatility_comparison` | `m3_timeframe_choice` ✅ legítimo | `t2_ranking_ortogonalidade` |
| `t1_t2_orthogonality_by_combo` | `volatility_operational_effect` ⚠️ | |
| | `gk_vs_wilder_econ_regime_shift` ⚠️ | |
| | `faixa2_e2_research` ⚠️ | |

`m2_bar_comparison` e `m3_timeframe_choice` são **legítimos** — o propósito
deles é justamente *comparar* grades entre si. Os outros cinco não: produzem
conclusões sobre produção medindo a grade que deixou de ser produção.

**Consequência direta:** o relabel de `AG-221` (que só tocou R1/R2/R3) **não
afeta 7 dos 16 módulos**. Re-executá-los não muda nada, porque eles não leem o
dado relabelado.

### §2.2 — Tabela ANTES × DEPOIS dos módulos concluídos

**Ressalva de atribuição, obrigatória.** O snapshot `experiments/pre_ag221_relabel_c0/`
**não é um baseline causal**: contém artefatos de datas variadas (o M6 "antes" é
de 2026-08-14, onze dias antes do relabel), não um estado consistente medido
imediatamente antes. Além disso, os cinco `labels.parquet` da grade 15m foram
regravados às 14:46–14:47 de 2026-08-25 **por processo externo a esta sessão**.
Portanto: mudanças observadas em módulos que leem 15m **não podem ser atribuídas
ao relabel** — misturam pelo menos três causas (labels 15m regravados por
terceiros, remedição de `round_trip_cost_bps_maker_prob`, e o relabel).

| módulo | rodou | grade | mudou? | veredito técnico | atribuição |
|---|---|---|---|---|---|
| `s1_tp_sl_sensitivity` | ✅ | **15m** | sim | ❌ **inválido para decisão** — as 7 células deram edge idêntico até a 5ª casa; só `r2_floor_stop_pct` mudou | constante (`AG-222`), **não** labels |
| `m6_common_factor_hypothesis` | ✅ | **15m** | sim | ⚠️ **números melhoraram, atribuição ambígua** — edge LONG −0,0465→−0,0328, SHORT −0,0048→−0,0009, I² 96,09→93,92, Q 102,3→65,7 | 15m regravado + constante; **não** o relabel |
| `m2_bar_comparison` | ✅ | 15m (legítimo) | **idêntico** | ✅ **correto não mudar** — lê barras, não labels | n/a |
| `m3_timeframe_choice` | 🔄 | 15m (legítimo) | — | pendente | — |
| demais (11) | 🔄 | ver §2.1 | — | pendente | — |

**Leitura honesta do que se aprendeu até aqui:** dos três módulos concluídos,
**nenhum mede a grade de produção**. O único resultado tecnicamente limpo é o
`m2_bar_comparison`, e ele é limpo justamente por *não* depender de labels. A
melhora aparente do M6 é real nos números mas não é atribuível ao relabel — e o
S1 está inválido para decisão.

### Camada 1 — dependem de `predictions.parquet` → **bloqueada** (6)

`faixa1_5_prerequisites` · `faixa1_6_reconciliation` · `faixa1_7_edge_or_beta` ·
`faixa2_caminho_b` · `faixa2_vol_accelerator_test` · `summary`

Todos exigem o retreino do Alpha (`run_layer1_sprint`), que o Manager pediu
para pular nesta rodada. Custo estimado quando for disparado: **~10 min × 15
combinações ≈ 2,5 h**, mais os 6 módulos acima.

---

## §3. CLIs criadas (`AG-231`)

Três módulos da Camada 0 tinham `run_and_save_*` mas **nenhum bloco de
entrada** — só eram chamáveis via `python -c "from ... import ... as r; r()"`,
o que os deixava fora de qualquer orquestração reproduzível:

```
uv run python -m src.analysis.s1_tp_sl_sensitivity
uv run python -m src.analysis.faixa2_e3_stability
uv run python -m src.analysis.faixa2_dsr_and_b2_check
```

O `s1_tp_sl_sensitivity` é o mais crítico dos três — é a medição que decide a
geometria de barreira (ver §5).

---

## §4. Preservação (lado ANTES)

| snapshot | conteúdo |
|---|---|
| `data/labels_pre_ag221_relabel/` | 20 `labels.parquet`, 363 MB |
| `experiments/pre_ag221_relabel/` | 67 JSON com métrica econômica |
| `experiments/pre_ag221_relabel_c0/` | snapshot imediatamente antes da Camada 0 |
| `experiments/ag221_baseline_labels_antes.json` | resumo numérico + `config_hash` por combinação |

Cópia, nunca movimentação — há leitores hardcoded (`alpha_layer1_report.json`
tem 5 call sites).

---

## §5. Tarefa acoplada — geometria de barreira

O Manager pediu (item 1) investigar a melhor geometria para as novas labels.
A análise teórica e a re-execução do S1 são a **mesma** tarefa.

**Validação que o relabel entregou:** sob martingale, a ruína do apostador
prevê `P(TP) = b/(a+b)`. Para `a=b=1,5`, teoria = 0,5000:

| | medido | desvio |
|---|---|---|
| pré-relabel | 0,4597 | 4,03 pp |
| **pós-relabel** | **0,4942** | **0,58 pp** |

**Consequência teórica forte:** sob martingale o edge bruto é
`p·a − (1−p)·b` com `p = b/(a+b)`, que é **exatamente zero para qualquer
geometria**. Nenhuma escolha de `tp/sl` cria edge. O que a geometria muda é o
**custo** e o **lift** que o sinal precisa entregar.

**Lift exigido** (quanto o modelo precisa mover `P(TP)` acima do martingale):

| a / b | lift | stop % | restrições |
|---|---|---|---|
| 1,5 / 1,5 **(atual)** | 0,0709 | 0,373 | OK |
| 2,0 / 2,0 | 0,0537 | 0,497 | OK |
| **3,0 / 3,0** | **0,0362** | 0,745 | OK (no limite de R1) |
| qualquer / 1,0 | — | 0,248 | **R2 violada** |

Barreiras mais largas exigem ~metade do lift, porque o custo é ~fixo por trade
e o payoff escala com a largura. `R1` limita `b ≤ 3,02`; `R2` limita `b ≥ 1,10`.

**Por que isto NÃO é uma proposta de mudar para 3,0/3,0:** a ruína do apostador
assume horizonte infinito, e a fórmula só vale enquanto `P(TIME) ≈ 0` — hoje
0,001 com 1,5 ATR e 32 barras. **Com 3,0 ATR a barreira vertical passa a
morder**, `P(TIME)` sobe e a tabela deixa de valer (TIME tem retorno arbitrário,
quebra o payoff binário). Some-se `AG-219`: a vertical está inativa hoje
justamente por estar larga demais para as horizontais atuais.

**A otimização é conjunta em três dimensões — `(tp_mult, sl_mult,
horizon_bars)` — não duas.** Propor 3,0/3,0 mantendo `horizon_bars=32` trocaria
um viés conhecido por um desconhecido.

**Medição proposta:** re-rodar o S1 sob as labels novas medindo por célula
`P(TP)` real, **`P(TIME)` real**, ESS (Σ uniqueness), trades/ano e lift
efetivo, com `horizon_bars` como terceiro eixo. A teoria dá a direção; a
medição decide o ponto.

---

## §6. Ordem de execução

1. ✅ relabel das 15 (`AG-229`, 998 s)
2. ✅ tabela antes×depois dos **labels** (`ag221_relabel_antes_depois.md`)
3. ✅ 2ª remedição de `round_trip_cost_bps_maker_prob` (0,4597 → 0,4942)
4. ✅ CLIs dos 3 módulos sem entrada (`AG-231`)
5. 🔄 **Camada 0** — 14 módulos em execução
6. ⬜ tabela antes×depois dos **experimentos** da Camada 0
7. ⬜ **decisão do Manager**: sweep S1 tridimensional para a geometria
8. ⬜ **decisão do Manager**: retreino do Alpha → desbloqueia Camada 1 (~2,5 h)
9. ⬜ Camada 1 + tabela final

---

## §7. Ressalva que acompanha toda a tabela (`AG-230`)

O relabel perdeu **0,48 %** das linhas no agregado, mas a perda **não é
uniforme**: concentra-se em **BTCUSDT** (−1,6 % a −1,9 %), e dentro dele em
**jan–fev 2021**. Os outros quatro símbolos ficam em ruído (−0,07 % a +0,05 %).

Causa (`n_empty_mark_window`: 0 → 6.149 no período): com `agg_trades` o
`t_entry` cai no meio de um candle de 1 m, e `searchsorted(..., "left")` avança
para o próximo — a janela de avaliação de barreira encolhe em um candle. Em
rajada de dollar bar (bull run de 2021, 32 barras em poucos minutos) a janela
zera e a barra é descartada.

**É causalmente correto** — usar o candle inteiro incluiria o high/low de
*antes* do fill, que seria vazamento. Mas o efeito colateral é um viés de
amostra: remove justamente barras de rajada extrema, e só em BTCUSDT. Qualquer
comparação BTC antes×depois carrega isso.
