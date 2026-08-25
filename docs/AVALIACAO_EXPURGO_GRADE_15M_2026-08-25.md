# Avaliação ponta a ponta — expurgo da grade de relógio 15m

**Data:** 2026-08-25 · **Status:** AVALIAÇÃO, nenhuma execução
**Decisão do Manager:** *"Recomendo expurgar grade de 15m, mantendo somente as
canônicas de produção; quem ainda lê essas barras tem que passar a ler
multi-timeframe R1, R2 e R3. Não quero contaminar um motor que não opera com
essa barra. Avalie ponta a ponta antes de recomendar os próximos passos."*

---

## §0. Conclusão executiva

O objetivo do Manager está **correto e é alcançável**, mas o expurgo **não é
onde parece estar**. Três achados reordenam o trabalho:

1. **O core já está migrado.** `tf` não é "a grade 15m" — é o parâmetro de grade
   de *tempo*, em XOR com `resolution_id`. Produção passa `resolution_id`; o
   `tf` é ignorado no cálculo. **Não há contaminação do motor.**
2. **A contaminação está em 5 módulos de `analysis/`** — que produzem conclusões
   sobre produção medindo a grade substituída.
3. **Existe uma trava dura:** `tf` entra no `config_hash` incondicionalmente
   (medido). **Mexer no default de `tf` — ou removê-lo — muda o `config_hash` de
   TODOS os labels e invalida os 15 que acabaram de ser gerados.**

**Recomendação: expurgo cirúrgico em `analysis/`, com o core intocado.**

---

## §1. Inventário — o que "grade 15m" é, materialmente

| item | situação |
|---|---|
| **Barras 15m** | **não são persistidas** — reamostradas de `klines_1m` em memória (`load_bars_15m` → `lake.query_bars`). Expurgá-las = parar de chamar a função, não apagar dados |
| **Labels 15m** | 5 arquivos, **140 MB** (`data/labels/{symbol}/15m/v1/`) |
| **Predictions legadas** | 58 MB em `predictions/alpha/` (Alpha treinado sob 15m) |
| **Models legados** | 9,5 MB |

**Distância real entre as grades** (medido, não documentado):

| | doc no código | **medido** | desvio |
|---|---|---|---|
| R1 | ~15 min | **10,2 min** | −32% |
| R2 | ~30 min | **21,5 min** | −28% |
| R3 | ~60 min | **45,1 min** | −25% |

"15m ≈ R1" não é aproximação aceitável: são grades com ~47% de diferença de
duração. Isso sustenta a decisão do Manager.

---

## §2. Onde a contaminação está — e onde NÃO está

### NÃO está no core ✅

`LabelConfig.tf` / `CPCVConfig.tf` / `load_labels_v1(tf=)` /
`build_modeling_frame(tf=)` têm default `"15m"`, mas operam em **XOR** com
`resolution_id`:

- `resolution_id=None` → grade de relógio (caminho legado)
- `resolution_id="R1"` → dollar bar; **`tf` vira vestigial no cálculo**
  (`AG-042`, `AG-037`/`grade_id`)

Todo caminho de produção passa `resolution_id`. **O motor não opera sobre 15m.**

### ESTÁ em 5 módulos de `analysis/` ❌

| módulo | o que decide | gravidade |
|---|---|---|
| **`s1_tp_sl_sensitivity`** | `tp_atr_mult`/`sl_atr_mult` — **classe A** | 🔴 `AG-232` |
| **`m6_common_factor_hypothesis`** | `I² = 96–98%`, fator comum entre ativos | 🔴 citado em decisão de escopo |
| `volatility_operational_effect` | efeito operacional de volatilidade | 🟡 |
| `gk_vs_wilder_econ_regime_shift` | troca de estimador de vol | 🟡 |
| `faixa2_e2_research` | pesquisa E2 | 🟡 |

**Legítimos, manter como estão:** `m2_bar_comparison` e `m3_timeframe_choice` —
o propósito deles é *comparar* grades. Expurgar 15m deles destruiria a função.

*Evidência do padrão:* a docstring de `gk_vs_wilder` ainda afirma
*"DECISION_TF (15m, único TF de produção hoje)"* — verdade em 2026-08-14, falsa
desde `AG-042` (2026-08-16). Os cinco foram escritos antes da migração e nunca
revisados.

---

## §3. Trava dura — `tf` no `config_hash`

Medido:

```
config_hash (tf=15m + R1) : 1ea77697cdc403f9
config_hash (tf=30m + R1) : 06e92e0dd6589ea1
tf afeta o hash sob resolution_id? True
```

A documentação diz que `tf` é vestigial sob dollar bar — **e é, no cálculo**.
Mas ele entra no dict do `config_hash` incondicionalmente.

**Consequências:**

1. **Não mexer em `tf`.** Mudar o default ou remover o campo altera o
   `config_hash` de todos os labels — inclusive os 15 recém-relabelados
   (`AG-229`), que passariam a falhar em `verify_config_hash` e exigiriam
   **novo relabel completo** (~17 min + revalidação de tudo).
2. Há um defeito de proveniência latente: o hash distingue duas configs que
   produzem resultado **idêntico** (sob `resolution_id`, `tf` não muda cálculo
   nenhum). Isso pode causar falha espúria de `verify_config_hash`. Registrar,
   **não corrigir agora** — corrigir muda o hash, mesmo problema do item 1.

---

## §4. O que "multi-TF R1/R2/R3" significa, por módulo

Não é substituição 1:1. Um módulo que hoje roda sobre uma grade passa a rodar
sobre três, e isso exige uma **decisão de desenho por módulo**:

| módulo | pergunta que ele responde | multi-TF significa | custo |
|---|---|---|---|
| `s1_tp_sl_sensitivity` | qual geometria de barreira? | a geometria pode ser **diferente por resolução** — 3 resultados, ou 1 pooled com R como estrato | 3× |
| `m6_common_factor_hypothesis` | há fator comum entre os 5 ativos? | heterogeneidade **por resolução**; o `I²` atual perde sentido se pooled entre grades | 3× |
| `volatility_operational_effect` | efeito operacional de vol | provavelmente por resolução | 3× |
| `gk_vs_wilder_econ_regime_shift` | qual estimador de vol? | por resolução | 3× |
| `faixa2_e2_research` | pesquisa E2 | avaliar se ainda é relevante | 3× |

**Alerta de desenho:** agregar métricas *entre* resoluções é perigoso — R1/R2/R3
têm janelas de feature em **contagem de barra**, então "48 barras" significa
horizontes de tempo diferentes em cada uma (`AG-043`, débito já registrado).
Pooling entre grades mistura horizontes. **O default deve ser reportar por
resolução, não pooled.**

---

## §5. Riscos

| risco | magnitude | mitigação |
|---|---|---|
| Mexer em `tf` invalida os 15 labels | 🔴 **alto** | não tocar no core (§3) |
| Deletar labels 15m quebra testes | 🟡 médio | **26 arquivos de teste** citam 15m; 42 têm `skip-if-ausente` e degradam bem. Deletar **só depois** de migrar os 5 módulos e rodar a suíte |
| Perder capacidade de comparar grades | 🟡 médio | manter `m2`/`m3` e os labels 15m em `data/labels_pre_ag221_relabel/` como arquivo morto |
| Custo 3× nas re-execuções | 🟢 baixo | são módulos de análise, minutos cada |
| Artefatos legados (`predictions/` 58 MB, `models/` 9,5 MB) | 🟢 baixo | são do Alpha sob 15m; ficam obsoletos no retreino de qualquer forma |

---

## §6. Recomendação — 4 fases, nesta ordem

**Fase 1 — migrar o S1 (`AG-232`).** É o único que decide constante classe A e
bloqueia a escolha de geometria. 4 pontos no módulo: caminho dos labels,
`query_dollar_bars`, `LabelConfig(resolution_id=)` + estimator, e
`decision_bar_close_time_ms`. Sai reportando **por resolução**.

**Fase 2 — migrar o M6.** O `I² = 96–98%` é citado como evidência em decisão de
escopo multi-ativo, e foi medido na grade errada. Sem isso, a conclusão
"multi-ativo é diversificação real" não está suportada pela grade de produção.

**Fase 3 — guardrail antes dos outros três.** Um teste que falha se módulo de
`analysis/` que não seja `m2`/`m3` referenciar `/15m/v1/labels`, `load_bars_15m`
ou `DECISION_TF = "15m"`. Transforma o padrão inteiro em **erro de build**, não
em achado de auditoria. Barato e impede regressão.

**Fase 4 — só então avaliar deletar os artefatos 15m.** Depois que nenhum
consumidor legítimo restar e a suíte passar. Mover para `data/labels_pre_ag221_relabel/`
(já existe) em vez de apagar — 140 MB é barato frente a perder a capacidade de
reconstruir uma comparação histórica.

**O que NÃO fazer:** mexer no default de `tf` no core, ou removê-lo. O ganho é
cosmético e o custo é invalidar os 15 labels e todo o trabalho de hoje.

---

## §7. Nota sobre a Camada 0

Interrompida em 2026-08-25 17:07 após travar no `m3_timeframe_choice` (28 min
sem progresso). Decisão deliberada: dos 14 módulos da fila, vários leem 15m e
serão migrados — re-executá-los antes da migração produziria artefatos que
seriam refeitos. Concluíram: `s1` (inválido), `m6` (atribuição ambígua),
`m2_bar_comparison` (correto, idêntico). Ver
`PLANO_REEXECUCAO_EXPERIMENTOS_ag221_2026-08-25.md` §2.2.
