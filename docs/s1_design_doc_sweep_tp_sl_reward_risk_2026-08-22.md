# S1 — Design doc: sweep de sensibilidade `tp_atr_mult`/`sl_atr_mult` (reparametrização R×S)

> Fase 1-4 do `redesign_workflow`. Só desenho — nenhuma linha de código de
> produção escrita nesta rodada. Síntese de 2 agentes `code-architect`
> independentes (foco reuso mínimo / foco rigor de contrato) + decisão de
> arquitetura própria sobre o ponto em que divergiram. Antes de qualquer
> implementação: auditoria independente via `project_assurance` (meta-nível,
> auditando este documento, já que não há código ainda), depois aprovação
> explícita do Manager.
>
> **Revisado pós-auditoria `project_assurance` (2026-08-22)**: 4 achados
> HIGH corrigidos abaixo (marcados `[corrigido pós-auditoria]`) — nenhum
> invalida a decisão de arquitetura central (§6), todos eram erros que
> teriam quebrado a implementação na 1ª execução ou escondiam uma decisão
> que deveria ir para o Manager. 2 achados LOW também corrigidos.
>
> **RETRATAÇÃO 2026-08-22 (Manager)**: "S1 é a maior lacuna aberta do
> projeto" deixa de ser prioridade ACIONÁVEL. A lacuna continua sendo a
> maior (2 números herdados, `provenance: ASSUMED`, "nunca questionado",
> definindo a variável dependente de tudo) — mas não é acionável agora:
> a cadeia real é Data Layer 100% (0/9) ← reprocessamento dollar-bar ←
> B0/B1 (ambos JÁ FECHADOS, ver §4 abaixo) ← retreino do Alpha (NÃO
> entra agora — Alpha precisa de refatoração antes) ← V41-6 (rederivação
> por MFE, precisa da população que o Alpha dispara). `tp/sl` é o item
> mais a jusante dessa cadeia, não o item bloqueado. **Fase 5
> (implementação/execução do sweep de 9 células) NÃO prossegue.** O que
> prossegue: trabalho que não depende da população do Alpha (ver §6-bis
> abaixo) — prepara V41-6 pra ser barato quando destravar, sem fabricar
> um valor provisório com selo `DERIVED` falso.

## 1. Contexto e escopo

`config/constants.yaml` tem `tp_atr_mult` (2,0) e `sl_atr_mult` (1,5), ambas
classe A, `sweep_required: true`, `sweep_range` declarado desde Sprint 6,
nunca varridas. S1 é o sweep de sensibilidade ±50% (`CLAUDE.md` §16.10 regra
4) dessas duas constantes — maior lacuna aberta do projeto (define a
variável dependente de todo experimento de M4/AG-114/AG-118 já medido).

Decisões já travadas nesta sessão (diálogo extenso com auditor externo,
Fases 1-3 do `redesign_workflow` já resolvidas — não reabrir):

1. **Reparametrização obrigatória**: nunca varrer `tp_atr_mult`/`sl_atr_mult`
   crus/independentes. `R = tp_atr_mult/sl_atr_mult` (controla o breakeven
   implícito `p* = 1/(1+R)`) × `S = sl_atr_mult` (controla taxa de
   eventos/holding time/saturação da normalização por ATR). Motivo: mesmo
   erro de acoplamento que `trailing_window_days`/`cadence_days` (T/C) já
   custou 6 rodadas de auditoria externa pra descobrir neste mesmo projeto
   (`AG-124`, `§15.15` do `PLANO_MESTRE_PRINCE2.md`) — não repetir.
2. **Leitura primária**: EV por evento em unidades de ATR
   (`frac_tp·R − frac_sl`, múltiplos de `sl`), não "acima/abaixo do
   breakeven" isoladamente (só dá sinal, não magnitude).
3. **Grade inicial**: `R ∈ {1,0; 1,33; 2,0} × S ∈ {0,75; 1,5; 2,25}` = 9
   células. Célula central (R=4/3, S=3/2) converte pra (tp=2,0, sl=1,5) =
   valor de produção atual — a grade é verificação de robustez AO REDOR do
   ponto já escolhido, não busca de novo ótimo.
4. **Barreira vertical** interage com S — reportar fração de timeout por
   célula, não ignorar a interação.

## 2. Achado que muda o desenho: tensão S1 vs. V41-6/ADR-001 §5 item 10

`PLANO_MESTRE_PRINCE2.md:695` marca "sweep tp/sl" como **SUPERSEDIDO** por
`V41-6` (rederivação por distribuição de MFE — método diferente, ainda não
iniciado). `ADR-001 §5 item 10` desaconselha explicitamente sweep 2D de
TP×SL como evento de multiplicidade sem orçamento estatístico, recomendando
DERIVAR a geometria em vez de otimizá-la, registrar como 1 trial estrutural.

**Minha leitura, registrada explicitamente (não decisão automática — ver
risco #4 em §11)**: S1 é verificação de robustez de um valor JÁ escolhido
(§16.10 regra 4) — resultado é "produção sobrevive/não sobrevive à faixa
testada", nunca "achamos R/S melhor". Isso não é o "grid sweep de busca"
que os dois textos desaconselham, desde que o registro (ledger, relatório,
veredito) deixe essa distinção explícita e nunca ambígua. `PLANO_MESTRE`
ganha uma linha NOVA na mesma tabela do `§11.4`, não uma reescrita da linha
existente — as duas convivem, propósitos diferentes.

## 3. Nomenclatura

O projeto já tem TRÊS namespaces de "R" convivendo: R1-R4 (regimes,
`src/risk/limits.py`), R1/R2 (restrições invioláveis §0.2), e o `R` deste
sweep. Nos identificadores de código: **`reward_risk_ratio`** (nunca
`r`/`R` isolado) e **`sl_mult`** (nunca `s`/`S` isolado). Nos
relatórios/JSON: `reward_risk_ratio`, `sl_atr_mult`. Evita reintroduzir
exatamente a classe de erro de colisão de nome que já gerou confusão real
nesta sessão (`AG-124` vs. `AG-125`, doc de auditoria não-confiável).

## 4. Infraestrutura existente confirmada por leitura direta (reuso, zero modificação)

- `src/labels/barrier_sweep.py::resolve_barriers_vectorized` — resolve
  TP/SL/TIME vetorizado pra um `(side, tp_atr_mult, sl_atr_mult,
  time_stop_ms, maker_fee, taker_fee)` fixo, devolve `barrier_hit`,
  `ret_gross`/`ret_net`, `n_bars_held`, **`tie_break_used`** (=
  semanticamente o campo `collision: Boolean!` que o `ADR-001 §4.4`
  especifica pro schema futuro de `labels/` — já existe, só precisa de
  mapeamento de nome no relatório, não lógica nova).
- `src/analysis/feasibility.py` — `edge_bruto_atr(*, frac_tp, frac_sl,
  tp_atr_mult, sl_atr_mult)` (keyword-only — chamar posicional quebra, ver
  §8) já é exatamente `frac_tp·R·S − frac_sl·S`
  depois da reparametrização; `breakeven_win_rate(atr_pct, tp_atr_mult,
  sl_atr_mult, maker_fee, taker_fee)` dá o breakeven COM custo (não só o
  `1/(1+R)` frictionless); `frac_tp_sl_from_labels(labels) ->
  BarrierFractions` agrega com `n` explícito e `NaN` (não `0,0`) se vazio.
  As três, zero modificação.
- **S1 não precisa de dollar-bar/`resolution_id`**: a TF de decisão de
  produção continua `15m` (retreino sob R1 dollar-bar represado, gated em
  Data Layer 100%). `LabelConfig.from_constants()` default (`tf="15m"`) é
  o que gerou `data/labels/{symbol}/15m/v1/labels.parquet` — S1 lê esse
  artefato direto.
- **S1 não precisa de Feature Engine/Regime Engine/CPCV/`build_modeling_
  frame`**: a tabela de saída pedida não estratifica por regime; o schema
  de `filled` que `resolve_barriers_vectorized` consome (`t0`, `t_entry`,
  `entry_price_fill`, `atr_at_t0`) não exige nenhum dos dois. Isso bypassa
  toda a cadeia que `faixa2_caminho_b.py::run_fase2_e1` carrega hoje — S1 é
  mais barato que o precedente `id=10` do `n_lifetime.yaml` porque não
  precisa estratificar por regime.
- **`[corrigido pós-auditoria]` `_filled_side_population` NÃO é promovível
  como está** — a versão existente (`faixa2_caminho_b.py:653-661`) opera
  sobre `mf_data` (saída de `build_modeling_frame`, que tem coluna
  `regime` via join com o Regime Engine) e seleciona
  `t0,t_entry,entry_price_fill,atr_at_t0,regime`. `labels.parquet` bruto
  (`LABEL_COLUMNS`, `triple_barrier.py`) não tem `regime` — chamar a
  função promovida sobre o labels bruto lançaria `ColumnNotFoundError` na
  1ª execução. Correto: `filled_side_population()` em
  `barrier_geometry.py` é uma função NOVA, mínima, que seleciona
  `t0,t_entry,entry_price_fill,atr_at_t0` direto de `LABEL_COLUMNS` (sem
  `regime`, coerente com a decisão de bypassar o Regime Engine) — não uma
  "promoção" da privada existente. Ver §7.
- `src/labels/backfill_multi_symbol.py::ALL_SYMBOLS` — reuso direto (é
  `labels/`, import legal de `analysis/`).
- Idioma de escrita atômica (`tmp` → `fsync` → `os.replace`, B29) e
  `report_provenance()` — copiado de `run_and_save_fase2_e1`, não o módulo
  inteiro (Faixa 2 está amarrada a CPCV/predictions que S1 não usa).

## 5. Achado crítico do 2º arquiteto — precisão numérica da célula central

`Fraction(4,3) * Fraction(3,2) == Fraction(2,1)` exato, mas
`(4/3) * 1.5` em `float64` = `1,9999999999999998`, **não** `2,0`. A
checagem de sanidade "célula central reproduz produção" só vale alguma
coisa se a resolução R,S→(tp,sl) for exata — não pode depender de
tolerância (`max_abs_diff`) pra um requisito que deveria ser identidade.

**Decisão**: grid declarado como `fractions.Fraction`, resolução exata:

```python
from fractions import Fraction
from typing import Final

REWARD_RISK_GRID: Final[tuple[Fraction, ...]] = (
    Fraction(1, 1), Fraction(4, 3), Fraction(2, 1),
)  # noqa: magic-number -- grid declarado a priori, §16.10 regra 4, ver docs/s1_design_doc_...md
SL_MULT_GRID: Final[tuple[Fraction, ...]] = (
    Fraction(3, 4), Fraction(3, 2), Fraction(9, 4),
)  # noqa: magic-number

def resolve_geometry(reward_risk_ratio: Fraction, sl_mult: Fraction) -> tuple[float, float]:
    """(R,S) -> (tp_atr_mult, sl_atr_mult) via aritmética Fraction exata --
    nunca R*S em float (verificado: (4/3)*1.5 em float64 != 2.0 exato)."""
    tp_atr_mult = reward_risk_ratio * sl_mult
    return float(tp_atr_mult), float(sl_mult)
```

Grid resultante (`tp = R·S`, `sl = S`):

| R \ S | 0,75 | 1,5 | 2,25 |
|---|---|---|---|
| 1,0 | **tp=0,75 sl=0,75 ⚠️** | tp=1,5 sl=1,5 | tp=2,25 sl=2,25 |
| 4/3 | tp=1,0 sl=0,75 | **tp=2,0 sl=1,5 (produção)** | tp=3,0 sl=2,25 |
| 2,0 | tp=1,5 sl=0,75 | tp=3,0 sl=1,5 | **tp=4,5 sl=2,25 ⚠️** |

`[corrigido pós-auditoria]` **DUAS** células excedem o `sweep_range`
declarado de `tp_atr_mult` (`[1,0; 3,0]`, `constants.yaml`), não uma:
`R=2,0×S=2,25→tp=4,5` (acima do teto) **e** `R=1,0×S=0,75→tp=0,75` (abaixo
do piso) — o achado original (§ arquiteto B) só capturou a primeira. Ver
risco #2 em §11.

## 6. Decisão de arquitetura — persistência (o ponto onde os 2 arquitetos divergiram)

**Arquiteto A (reuso mínimo)**: nenhuma persistência além de
`experiments/s1_barrier_geometry_sensitivity.json` — S1 é terminal,
humano-consumido, nada relê o artefato depois pra reprocessar.

**Arquiteto B (rigor/contrato)**: implementar a maquinária real do
`ADR-001` Parte II (`config_hash` canônico blake2b-16/floats-como-string,
`trial_registry/`, `promotion/`, layout hive particionado) — argumenta que
seria a 1ª implementação real do contrato, embrião de `src/io/artifact.py`.

**Achado que decide isso**: o Arquiteto B confirmou por `Glob` que **nada**
do `ADR-001` Parte II (`trial_registry/`, `promotion/`, `src/registry/`,
`src/io/artifact.py`/`schema.py`) existe em NENHUM lugar do repo hoje — é
documento de arquitetura "Proposed", não ratificado (`ADR-001` Action item
1), com implementação explicitamente represada até a ratificação formal.
`LabelConfig.config_hash` (o único hash real em produção) é um STOPGAP
declarado na própria docstring, com convenção DIFERENTE da que o ADR
propõe (floats nativos + sha256, não floats-string + blake2b).

**Decisão**: sigo o Arquiteto A — **sem lake/`config_hash`/`trial_registry`/
`promotion` nesta rodada**. Motivos:

1. Construir a maquinária do `ADR-001` Parte II agora, fora de ordem (antes
   da ratificação formal e antes de `src/io/artifact.py` existir),
   criaria uma SEGUNDA convenção de "artefato exploratório" divergente da
   que o resto do repo já usa (`experiments/*.json` git-commitado — `E1`,
   `m4_critical_windows_report.json`, `volatility_comparison_report.json`,
   todos o mesmo padrão). Isso é dívida técnica nova, não rigor — o
   `src/io/artifact.py` real, quando construído, teria que reconciliar ou
   migrar essa implementação paralela.
2. Nenhum consumidor downstream real lê o output de S1 programaticamente —
   é lido por um humano (Manager) decidindo se o valor de produção
   sobrevive. Não há reprocessamento em cadeia a proteger.
3. Princípio geral do projeto (`CLAUDE.md`): não desenhar para requisito
   hipotético futuro; 3 linhas parecidas > abstração prematura. 4 módulos
   novos (`artifact_contract.py`, `trial_registry.py`, `promotion.py`,
   `s1_tp_sl_sensitivity.py`) pra uma verificação de robustez de 9 células
   é desproporcional ao problema.

**Incorporado do Arquiteto B, apesar da decisão acima** (correto e barato,
independente de qual arquitetura de persistência vence):

- Resolução `Fraction` exata (§5).
- Mapear `tie_break_used` → `collision_rate` no relatório (vocabulário
  `ADR-001`, zero lógica nova).
- Checagem de identidade `edge_atr_units == sl_mult · edge_per_sl_unit`
  (dentro de `1e-9`) no gerador do relatório, não só documentação —
  **`[corrigido pós-auditoria]`** com guarda de `NaN` explícita (ver §8) —
  a álgebra é exata (`edge_bruto_atr = frac_tp·(R·S) − frac_sl·S =
  S·(frac_tp·R − frac_sl) = S·edge_per_sl_unit`), mas `frac_tp`/`frac_sl`
  podem ser `NaN` quando um estrato (symbol, side) tem 0 trades preenchidos
  (`frac_tp_sl_from_labels` já devolve `NaN` nesse caso, por design —
  "não computável ≠ medido zero"). Um `assert` puro sem guarda dispararia
  `AssertionError` e abortaria a execução inteira na 1ª stratum vazia
  (plausível pra altcoins de histórico mais curto) — contradiz a própria
  convenção que `feasibility.py` já estabelece.
- Distinção operacional explícita "trial ≠ chamada de função": 1 trial =
  1 célula `(R,S)` que exige recálculo de barreira; símbolo e lado são
  ESTRATOS de robustez reportados dentro da mesma célula, nunca dimensão
  nova de busca. Fica escrita literalmente no docstring do módulo e na
  entrada do `n_lifetime.yaml` — não uma convenção implícita.
- O achado do corner-cell fora de faixa (§5/§8 risco #2) — o Arquiteto A
  não pegou isso.

## 6-bis. O que fazer agora, sem depender da população do Alpha (2026-08-22)

3 itens, nenhum bloqueado pela cadeia Data Layer→retreino→V41-6:

1. **`[CORRIGIDO 2026-08-22]` Escrever o procedimento de derivação
   recomendado pelo `ADR-001` (não o de MFE do `PRD_V4_1.md §4.1` —
   os dois documentos propõem métodos DIFERENTES, ver abaixo), como
   código testável — não como fonte de valor.**
2. **Medir a distância entre as duas populações assim que houver como**
   (Alpha retreinado). Fica como gatilho registrado, não executável
   agora — não fabrica número, só o teste que fecha a dúvida quando for
   possível.
3. **`[FEITO 2026-08-22]`** Aplicar o filtro R2 ao espaço de `sl` — ver
   risco #3 acima, não depende da população do Alpha, medido sobre ATR
   real dos 5 símbolos.

### Correção de precisão (2026-08-22, a pedido do Manager): ADR-001 ≠ PRD_V4_1.md §4.1

**O `PRD_V4_1.md §4.1`** propõe "recalcular `tp_mult`/`sl_mult` a partir
da distribuição de MFE" — percentil de excursão favorável máxima. Foi
essa a leitura que motivou o item 1 original (e o achado de que não
existe `mae_atr_units` persistido pro lado SL).

**O `ADR-001 §5` (item 10) propõe outra coisa, verificado por leitura
direta — NÃO menciona MFE/MAE em nenhum lugar**: "escolher `tp_mult`/
`sl_mult` que maximizem a razão entre **payoff esperado e hurdle de
custo**, dado `c` medido e a **distribuição empírica de tempo-até-
barreira** — não que maximizem Sharpe de backtest". `c` (custo
round-trip) já é medido (`feasibility.py::custo_atr`); a distribuição
de tempo-até-barreira já é persistida (`n_bars_held`, a MESMA
distribuição que já resolveu `AG-116`/`horizon_bars`) — **nenhum dado
novo precisa ser adicionado ao Label Engine**. A pergunta do MAE
(§ anterior) fica sem objeto seguindo o ADR-001: não é derivação por
excursão simétrica, é uma OTIMIZAÇÃO de razão EV/custo sobre `(tp_mult,
sl_mult)` conjunto, usando o maquinário que já existe em
`feasibility.py`/`barrier_sweep.py` (o mesmo que S1 já ia usar). O
próprio ADR-001 já dá 2 disciplinas extras: registrar o resultado como
**1 trial estrutural**, não N variantes; confirmar num holdout travado,
uma vez.

**Decisão (Manager, 2026-08-22): usar a recomendação do ADR-001, não a
do PRD_V4_1.md.** A ressalva de população (§4 acima — rodar sobre a
população que o Alpha dispara, não a incondicional) continua valendo
igualmente aqui — o ADR-001 não resolve essa parte, só muda QUAL
estatística é otimizada, não SOBRE QUAL população.

### Escopo real do item 1, sob o ADR-001

O que falta especificar não é mais "percentil de MFE" — é a forma exata
da razão a maximizar: `edge_bruto_atr` (já existe, `frac_tp·tp_mult −
frac_sl·sl_mult`) é o candidato natural pra "payoff esperado";
`breakeven_win_rate`/`custo_atr` (já existem) dão o "hurdle de custo".
A forma exata da razão (`edge_bruto_atr / custo_atr`? outra
normalização?) e o método de otimização (busca em grade fina sobre o
maquinário existente — não confundir com o sweep de 9 células original,
que era verificação de robustez, não busca — vs. uma forma fechada) NÃO
decidido aqui — delegado a um agente com skill de desenho, ver Fase 4-bis
abaixo. O que já está travado, não precisa de nova decisão: usar
`feasibility.py`/`barrier_sweep.py` existentes, população-condicionada
quando disponível, registrar como 1 trial estrutural.

**`[medido 2026-08-22]` Diagnóstico rodado**:
`tools/diagnostics/measure_mfe_distribution_for_barrier_derivation.py`,
`experiments/mfe_distribution_for_barrier_derivation.json` — mediana de
MFE (pooled, 2 lados) notavelmente consistente entre os 5 símbolos:
BTCUSDT 1,363 ATR, ETHUSDT 1,387, SOLUSDT 1,412, BNBUSDT 1,418, XRPUSDT
1,405 — bate com o achado histórico do V3 (`PRD_V4_1.md §4.1`, "MFE
mediana medida no V3: 1,27-1,40 ATR"), agora confirmado nos 5 símbolos
atuais. Só ~38-40% dos trades preenchidos alcançam MFE >= 2,0 ATR (o
`tp_atr_mult` de produção) em qualquer símbolo — consistente e uniforme.
Confirma, com dado real e atual, que `tp=2,0` está fora de alcance pra
maioria da população incondicional — mesmo achado do V3, não um
artefato antigo. Fixture de validação, não valor candidato (aviso
explícito no próprio JSON).

## 7. Arquivos novos (2, não 1 nem 4)

| arquivo | papel | camada |
|---|---|---|
| `src/labels/barrier_geometry.py` | `REWARD_RISK_GRID`/`SL_MULT_GRID` (`Fraction`), `resolve_geometry()`, `filled_side_population()` — **`[corrigido pós-auditoria]`** função NOVA e mínima (seleciona `t0,t_entry,entry_price_fill,atr_at_t0` de `LABEL_COLUMNS`), NÃO promoção de `_filled_side_population` de `faixa2_caminho_b.py` (aquela exige coluna `regime`, ausente no labels.parquet bruto — ver §4) | `labels/` — lido por `analysis/`, nunca o contrário |
| `src/analysis/s1_tp_sl_sensitivity.py` | orquestração: loop 5 símbolos × 9 células × 2 lados, monta e escreve o relatório | `analysis/` — importa de `labels/`, `core/`; nunca de `models/`/`regime/`/`execution/` |

Saída: `experiments/s1_tp_sl_sensitivity_report.json` (escrita atômica,
B29 — `tmp` → `fsync` → `os.replace`).

## 8. Fluxo de dado ponta a ponta

Para cada `symbol in ALL_SYMBOLS` (loop externo, sequencial — volume
pequeno, 90 resoluções vetoriais sub-segundo cada, dominado por I/O de
`mark_1m`/`funding`, não por cômputo; não justifica paralelismo):

1. `labels = pl.read_parquet(f"data/labels/{symbol}/15m/v1/labels.parquet")`.
2. Carregar `mark_1m`/`funding`/`bars_15m` uma vez (±3 dias de buffer,
   mesmo padrão de `run_fase2_e1`); `bars_15m` dá
   `decision_bar_close_time_ms` exato (melhoria sobre a aproximação
   documentada em `AG-031`/B1, mesmo custo de I/O que já seria pago).
3. `cfg = LabelConfig.from_constants()` uma vez (time_stop_ms/fees fixos).
4. Para `side in (1, -1)`:
   - `filled_side = filled_side_population(labels, side=side)`.
   - `frac_nofill_side` calculado uma vez — não depende de tp/sl.
   - `atr_median_side` calculado uma vez — ATR não depende de tp/sl.
   - Para `(reward_risk_ratio, sl_mult) in product(REWARD_RISK_GRID, SL_MULT_GRID)`:
     - `tp_atr_mult, sl_atr_mult = resolve_geometry(reward_risk_ratio, sl_mult)`.
     - `resolved = resolve_barriers_vectorized(filled_side, mark_1m, funding, side=side, tp_atr_mult=tp_atr_mult, sl_atr_mult=sl_atr_mult, time_stop_ms=cfg.time_stop_ms, maker_fee=cfg.maker_fee, taker_fee=cfg.taker_fee, decision_bar_close_time_ms=...)`.
     - `frac = frac_tp_sl_from_labels(...)` (denominador = todo trade
       preenchido do lado: TP+SL+TIME; **`n=0` → `frac_tp`/`frac_sl` =
       `NaN`**, não `0,0` — convenção já existente do módulo, propagar).
     - `[corrigido pós-auditoria]` `edge_atr_units =
       edge_bruto_atr(frac_tp=frac.frac_tp, frac_sl=frac.frac_sl,
       tp_atr_mult=tp_atr_mult, sl_atr_mult=sl_atr_mult)` — **chamada
       obrigatoriamente por keyword**, a função real é keyword-only
       (`def edge_bruto_atr(*, frac_tp, frac_sl, ...)`); posicional
       lançaria `TypeError` na 1ª execução.
     - `edge_per_sl_unit = frac.frac_tp * float(reward_risk_ratio) - frac.frac_sl` (leitura primária).
     - `breakeven_wr_frictionless = 1.0 / (1.0 + float(reward_risk_ratio))`.
     - `breakeven_wr_cost_adjusted = breakeven_win_rate(atr_pct=atr_median_side, tp_atr_mult=tp_atr_mult, sl_atr_mult=sl_atr_mult, maker_fee=cfg.maker_fee, taker_fee=cfg.taker_fee)`.
     - `collision_rate = mean(resolved.tie_break_used)`.
     - `holding_mediano_bars = median(resolved.n_bars_held)`.
     - `stop_pct_cell = sl_mult * atr_median_side`; flag informativo
       `dentro_janela_r1_r2 = 0.00275 <= stop_pct_cell <= 0.00758` (não
       recomputa o controle real de Risk Engine — camada errada e caro
       demais pra 90 células; só sinaliza).
     - `[corrigido pós-auditoria]` checagem de identidade **com guarda de
       `NaN`**: `if not (math.isnan(frac.frac_tp) or
       math.isnan(frac.frac_sl)): assert abs(edge_atr_units -
       float(sl_mult) * edge_per_sl_unit) < 1e-9` — se o estrato for
       `NaN` (0 trades preenchidos), pula a checagem e propaga `NaN` no
       relatório dessa célula, nunca aborta a execução inteira.

## 9. Schema do relatório (`experiments/s1_tp_sl_sensitivity_report.json`)

```json
{
  "task": "s1_tp_sl_sensitivity",
  "grid_declared_before_search": {
    "reward_risk_ratio": ["1/1", "4/3", "2/1"],
    "sl_atr_mult": ["3/4", "3/2", "9/4"]
  },
  "production_cell": {"reward_risk_ratio": "4/3", "sl_atr_mult": "3/2", "tp_atr_mult_equivalente": 2.0},
  "n_lifetime_delta": "TBD -- decisão do Manager entre 9/18/1, ver risco #8 em §11",
  "grid_out_of_declared_range": [
    "R=2/1,S=9/4 -> tp_atr_mult=4.5 excede teto do sweep_range=[1.0,3.0] de constants.yaml",
    "R=1/1,S=3/4 -> tp_atr_mult=0.75 abaixo do piso do sweep_range=[1.0,3.0] de constants.yaml"
  ],
  "by_symbol": {"BTCUSDT": {"by_side": {"long": {"cells": {"R1.0_S0.75": {"...": "..."}}}, "short": {"cells": {}}}}},
  "aggregate_by_cell": {
    "R1.0_S0.75": {
      "reward_risk_ratio": 1.0, "sl_atr_mult": 0.75, "tp_atr_mult": 0.75,
      "edge_atr_units_pooled_5_symbols": "...",
      "edge_per_sl_unit_pooled_5_symbols": "...",
      "breakeven_wr_frictionless": 0.5,
      "breakeven_wr_cost_adjusted_mean": "...",
      "frac_tp": "...", "frac_sl": "...", "frac_timeout": "...",
      "frac_events_measured": "...",
      "holding_mediano_bars_mean": "...",
      "collision_rate_mean": "...",
      "dentro_janela_r1_r2_por_simbolo": {"BTCUSDT": true}
    }
  },
  "sanidade_centro_da_grade": {"reproduz_producao_exato": true},
  "veredito": "TBD -- medir; enum fechado: producao_sobrevive_a_faixa | producao_nao_sobrevive_a_faixa | inconclusivo (critério operacional pendente, ver risco #1)"
}
```

Tabela humana: 9 células (linhas) × EV-ATR/breakeven(2)/frac_timeout/
collision_rate/holding mediano (colunas), por símbolo + agregado pooled.

## 10. Registro

- **`audit/n_lifetime.yaml`**: nova entrada. `[corrigido pós-auditoria]`
  **`delta` NÃO decidido neste documento — proposta com 3 leituras
  concorrentes, ver risco #8 em §11, decisão fica com o Manager.** A
  proposta original (`delta=9`, símbolo e lado como estratos não-
  multiplicativos) foi apresentada como já decidida — a auditoria
  encontrou que isso não confronta a regra MECÂNICA já escrita no
  cabeçalho do próprio `n_lifetime.yaml` ("N trials = combinações que
  exigem recálculo de backtest por combinação"): `resolve_barriers_
  vectorized` É chamado separadamente por `side` (recálculo real de
  barreira por lado), exatamente o critério mecânico que o precedente
  `id=10` usou para contar `delta=18` (3×3 POR LADO). A mesma citação de
  `ADR-001 §5 item 10` ("registrar como 1 trial estrutural") sugere ainda
  uma 3ª leitura, `delta=1`. As três não são reconciliadas aqui de
  propósito — fica para o Manager escolher, com a tensão exposta, não
  escondida atrás de uma decisão silenciosa do autor do desenho.
- **`PLANO_MESTRE_PRINCE2.md` §11.4**: linha NOVA na mesma tabela (não
  reescreve a linha "SUPERSEDIDO" existente) — "S1 (verificação de
  robustez §16.10 regra 4, NÃO redefine o valor — isso é V41-6, se e
  quando rodar)".
- **`audit/evidence_ledger.yaml`**: achado ESTATÍSTICO medido (as 90
  linhas de EV-ATR) entra aqui quando o relatório real existir — regra 6
  do comando "Atualize governança" (estatístico ≠ arquitetura).
- **`audit/architecture_gaps_log.yaml`**: só se a execução real revelar um
  gap de integração/arquitetura (ex. algo em `resolve_barriers_vectorized`
  que não se comporta como esperado sob multi-símbolo real) — não
  antecipar um `AG-NNN` que não existe ainda.

## 11. Riscos e decisões que ficam explicitamente com o Manager (não decidido sozinho)

1. **Definição operacional de "sobrevive à faixa" — não travada.** Os 2
   arquitetos, independentemente, recusaram decidir isso sozinhos. É
   estruturalmente a mesma lacuna que gerou `AG-114`/`AG-118` (Gate 1 sem
   critério declarado antes de rodar). Precisa, ANTES de qualquer
   execução: quantos dos 5 símbolos precisam concordar; qual margem conta
   como "empate" vs. "dominado"; se o critério aplica sobre `edge_atr_units`
   pooled ou por símbolo mediana.
2. **`[corrigido 2026-08-22 — decisão do Manager]` DUAS células cortadas
   da grade, não reportadas nem com flag**: R=2,0×S=2,25→tp=4,5 (acima
   do teto do `sweep_range` — "não é sensibilidade, é outra geometria")
   e R=1,0×S=0,75→tp=0,75 (abaixo do piso — E, medido acima no risco #3,
   estruturalmente inviável por R2 pra BTCUSDT/BNBUSDT de qualquer
   forma). Grade efetiva: 7 células (não 9) pros 5 símbolos — exceto
   BTCUSDT/BNBUSDT, que perdem também `R=4/3,S=0,75`/`R=2,0,S=0,75`
   (viola R2 independente do corte do `sweep_range`), ficando com 6
   células válidas.
3. **`[medido 2026-08-22]` `sl_mult=0,75` viola R2 para BTCUSDT e BNBUSDT
   especificamente, não para os outros 3.** ATR% mediano medido sobre a
   população preenchida real (`labels.parquet`, 5 símbolos):
   BTCUSDT 0,3547% (S mínimo viável 0,7752), ETHUSDT 0,4294% (0,6405),
   SOLUSDT 0,6232% (0,4412), BNBUSDT 0,3614% (0,7609), XRPUSDT 0,4740%
   (0,5802). `S=0,75` fica ABAIXO do piso pra BTCUSDT/BNBUSDT (margem
   pequena, ~2-3%) — célula estruturalmente inexistente pra esses 2
   símbolos, não um ponto fraco a reportar com flag. Válida pra ETH/SOL/
   XRP. `S=1,5` (produção) passa em todos os 5 com folga. **Decisão**:
   exclusão é por (símbolo, célula), não por célula inteira da grade —
   `dentro_janela_r1_r2` deixa de ser só um flag informativo, vira
   critério de exclusão (célula que viola R2 não aparece na saída pra
   aquele símbolo, nem com flag — ponto inexistente, não ponto fraco).
4. **`[RESOLVIDO 2026-08-22]` Nem verificação de robustez (Caminho A puro)
   nem "1 trial estrutural derivado" agora (Caminho B).** `tp_atr_mult`/
   `sl_atr_mult` são `provenance: ASSUMED`, "herdado do PRD V2, nunca
   questionado" (`constants.yaml`, verificado) — não há valor derivado
   pra verificar robustez ao redor, só um número nunca examinado. Mas
   Caminho B (derivar 1 ponto agora sobre a população INCONDICIONAL de
   `labels.parquet`) tem um defeito direcional, não neutro: `PRD_V4_1.md
   §4.1` já registra que "a rederivação roda sobre a população que o
   Alpha dispara" e que a varredura incondicional da Faixa 2 foi "erro de
   desenho registrado" — a distribuição de MFE incondicional é
   sistematicamente diferente da condicionada ao sinal do Alpha, então
   um valor derivado agora mudaria de forma previsível quando V41-6 rodar
   de verdade. Pior: `provenance: DERIVED` em `constants.yaml` é lido por
   todo consumidor como "isso foi examinado" — um valor com esse selo
   herdando o defeito catalogado é PIOR que o `ASSUMED` atual, que pelo
   menos é honesto sobre não ter sido examinado.

   **Terceira via, adotada**: fazer o trabalho que NÃO depende da
   população agora (§6-bis), sem fabricar um valor provisório e sem
   esperar a cadeia inteira (Data Layer 100% → retreino Alpha, que nem
   entra nesta fase → V41-6). Ver §6-bis.
5. **Decisão de persistência (§6)** — decidi seguir o Arquiteto A
   (sem lake/`trial_registry`/`promotion`) com justificativa explícita.
   Se o Manager preferir a via do Arquiteto B (embrião do `ADR-001` Parte
   II), o custo é 2 módulos novos a mais (`src/core/artifact_contract.py`,
   `src/core/trial_registry.py`) — viável, só não é o que recomendo agora.
6. **Sem estratificação por regime** — deliberado (tabela pedida não exige,
   evita reintroduzir a dependência de Regime Engine que o desenho
   minimalista evita). Extensão barata depois, se necessário.
7. **Escopo de resolução**: só `tf="15m"` (produção atual), não R1/R2/R3
   dollar-bar (retreino represado, Data Layer não fechado). Decidir se
   S1-dollar-bar é item de follow-up agendado ou fica fora de escopo.
8. **`[adicionado pós-auditoria]` `n_lifetime.yaml` delta — 3 leituras
   concorrentes, nenhuma travada.** `delta=9` (proposta original — símbolo
   e lado como estratos, não dimensões de busca) tensiona diretamente com
   a regra MECÂNICA escrita no cabeçalho do próprio `n_lifetime.yaml`
   ("recálculo de backtest por combinação" — `resolve_barriers_vectorized`
   É recalculado por lado, mesmo critério que o precedente `id=10` usou
   pra contar `delta=18`, 3×3 POR LADO). A citação do próprio §2 deste
   documento de `ADR-001 §5 item 10` ("registrar como 1 trial estrutural")
   sugere ainda `delta=1`. Três leituras defensáveis (9/18/1), nenhuma
   reconciliada — decisão do Manager, não do autor do desenho.

## 12. Fora de escopo desta rodada

- Implementação real (Fase 5 do `redesign_workflow`) — só após aprovação
  explícita do Manager e resposta aos riscos #1/#2/#4 acima.
- `PromotionManifest`/decisão final travada — função separada, offline,
  chamada manualmente pelo Manager depois de ler o relatório (mesmo
  princípio de "produção só carrega o que foi congelado offline").
- Qualquer alteração em `V41-6` (rederivação por MFE) — trilha
  independente, não tocada aqui.

## 13. Fase 4-bis — recomendação de forma exata da otimização ADR-001 (2026-08-22)

> **`[EM ABERTO — decisão adiada, Manager 2026-08-22]`** Isto é uma
> RECOMENDAÇÃO de um agente de desenho, não uma decisão travada. Fica
> registrada aqui e no Road Map Vivo como pendência explícita, pra
> retomar quando a cadeia Data Layer→Alpha→V41-6 destravar — não decidir
> por omissão, não fechar por default.

**Forma da razão a maximizar** — não `edge_bruto_atr / custo_atr` cru
(achado do agente: `custo_atr` não depende de `tp_atr_mult`/
`sl_atr_mult`, é constante em relação às variáveis de decisão pra um
ATR/população fixos — dividir por uma constante degeneraria a razão em
maximizar só o numerador). Recomendação: construir numerador e
denominador dos campos REALIZADOS de `ResolvedBarriers`
(`resolve_barriers_vectorized`), não das fórmulas fechadas —
`cost_exit_bps` já varia por outcome (`maker` se TP, `taker` se
SL/TIME), então o hurdle de custo genuinamente muda com a geometria:

```
edge_liq_atr    = mean(ret_gross_i/atr_at_t0_i) - mean(custo_i/atr_at_t0_i)
cost_hurdle_atr = mean(custo_i/atr_at_t0_i)          # REALIZADO, não custo_atr() fixo
objetivo(tp,sl) = edge_liq_atr / cost_hurdle_atr      # 0=breakeven exato
```

**Papel de `n_bars_held`** (distribuição de tempo-até-barreira) — não
funde num único escalar com o edge (mesma classe de erro que gerou
`AG-114`/`AG-118`, critério misturado sem definição operacional).
Entra como RESTRIÇÃO de viabilidade (mesmo papel que R1/R2 já ocupam no
risco #3 acima): throughput implícito de `n_bars_held` testado contra
R3 (`fee_budget_monthly`), do mesmo jeito que ATR mediano já testa
R1/R2. Candidato que viola R1, R2 OU R3 é penalizado (rejeitado), nunca
aceito com edge alto às custas de holding time inviável.

**Método**: `scipy.optimize.minimize(method="Nelder-Mead")` sobre
`(reward_risk_ratio, sl_mult)` — `frac_tp`/`frac_sl` mudam em DEGRAUS
conforme `(tp,sl)` cruza o caminho de preço de cada trade (função não-
diferenciável), descarta métodos baseados em gradiente. Bounds reusam
`sl_atr_mult.sweep_range`/`tp_atr_mult.sweep_range` já declarados (zero
número novo). Multi-start (produção atual + 2-3 cantos da caixa) como
verificação interna de ótimo local — 1 procedimento declarado a priori,
não N hipóteses candidatas.

**Onde viveria**: 3 funções puras novas em `feasibility.py`
(`edge_liq_atr_realized`/`cost_hurdle_atr_realized`/
`net_edge_to_cost_ratio`) + módulo novo
`src/analysis/barrier_geometry_derivation.py`. `n_lifetime.yaml`: nada
registrado ao escrever/testar contra fixture — só ao rodar contra
população real (gated pela mesma cadeia).

**5 riscos que o agente não resolveu sozinho** (delegados de volta):
1. Contagem de trial da execução real — Nelder-Mead chama a resolução
   de barreira dezenas de vezes por convergência; não está claro se
   conta como "1 fit iterativo" ou "N trials" pela regra mecânica do
   `n_lifetime.yaml` — mesma tensão do risco #8 acima, agora também
   aqui.
2. Definição de consenso entre símbolos se o objetivo roda pooled mas o
   gate R1/R2/R3 é por símbolo (mesmo achado do risco #3: `sl=0,75`
   inviável só pra BTCUSDT/BNBUSDT).
3. Funding excluído do hurdle de custo por desenho — tem sinal
   (pode ser receita, não custo, dependendo do lado), não resolvido.
4. Nenhum guardrail técnico impede alguém de rodar isto sobre a
   população incondicional e gravar `provenance: DERIVED` como se
   fosse examinado — falta um campo tipo `population_kind` obrigatório.
5. Nelder-Mead não garante ótimo global — mitigado por multi-start, não
   eliminado.
