# ADR-006 — Momentum/reversão/impacto reconstruídos em torno do H real, sob dollar bar

Status: decidido e implementado (2026-08-28). Decisão do Manager, autorização
explícita "focar no plano ponta a ponta" — `/feature-dev:feature-dev`.

## Contexto

Auditoria de `audit/feature_thesis/fichas_69_2026-08-25.yaml` (70 fichas,
25/08) reprovou (`SEM_MECANISMO`/`INCOERENTE_DIMENSIONAL`) as 5 features de
candlestick single-bar (A07-A11) e as 8 de momentum/reversão do grupo B
(B02-B11) então em T2. Duas classes de defeito distintas, não uma só:

1. **Redundância algébrica/matemática** — independe de bar type. `A08+|A07|
   +A09=1` (identidade exata); `A09≡A10` em barra de baixa; `B03=exp(A04)-1`
   (bijeção monotônica de A04); `B06=A03(t)-A03(t-4)` (combinação linear de
   A03); `B10/B11/B09/A10` medem o mesmo conceito ("posição do close na
   distribuição recente") sob 4 janelas diferentes.
2. **Parâmetro nunca calibrado contra o horizonte real do motor** — B02
   (RSI-48, `h/H=6,65`), B09 (z-score-48, `h/H=9,6`), B04 (MACD 12/26/9,
   convenção de ações dos anos 1970), B05 (EMA-slope, 2 janelas ASSUMED
   nunca varridas). Herança de PRD de barra de relógio, nunca recalibrada
   pro dollar bar.

A11 (`TR/close`) tem uma nuance própria: mecanismo real disponível e nunca
reclamado — sob dollar bar, `quote_volume` por barra é quase constante
(`quote_volume ≈ threshold_quote`, `AG-321`), então `TR/close` mede
deslocamento de preço sob atividade monetária aproximadamente fixa, uma
leitura de impacto de preço. Ficha original não credita essa tese (não
escrita) e reprova A11 por `SEM_MECANISMO` sob o gate marginal antigo
(ADR-005 §1.3, 5/15 células).

## Medição nova desta sessão — H real do motor

`n_bars_held` (`labels.parquet`, população completa exceto NOFILL, 2 lados),
BTCUSDT/SOLUSDT × R1/R2/R3: **mediana=1, p25∈{0,1}, p75=3**, estável entre
resoluções (R1 tem ~4x mais barras que R3 pro mesmo símbolo/período, mas o
holding em CONTAGEM DE BARRAS não muda) — achado em si, não esperado a
priori. `H` usado nas features novas = 3 (p75, não a mediana — captura o
holding típico incluindo a cauda mais lenta, não só o caso mais curto).

Ressalva: mede a população de LABEL inteira (geometria de barreira), não o
holding condicionado às linhas onde o Alpha de fato sinaliza — pode divergir
um pouco, não há razão forte pra divergir em ordem de grandeza.

## Decisão — 7 features, direto a T1 (autorização explícita do Manager)

| id | família | fórmula | substitui/consolida |
|---|---|---|---|
| `A11_true_range_pct` (reativada) | impacto | `TR_t/C_{t-1}` | tese nova, formula igual |
| `A16_return_3` | momentum | `ln(C_t/C_{t-3})` | preenche gap A02(2)/A03(4) |
| `A17_log_tr_per_overshoot_ratio` | impacto | `ln1p((TR_t/C_{t-1})/(overshoot_t/threshold_quote_t))` — v2, ver addendum AG-373 abaixo | — |
| `B12_close_location_h3` | reversão | posição no range min-max(3), `[-1,1]` | A10+B09+B10+B11 |
| `B13_extension_h3` | reversão | `\|ret_3\|/realized_vol_3` | — |
| `B14_rejection_after_extension` | reversão | `-sign(ret_3(t-1))×ret_1(t)/atr_pct(t)` | — (exaustão, novo conceito) |
| `B15_efficiency_ratio_h3` | momentum | `efficiency_ratio(close,3)` | janela de B07/B08 na escala certa |

**A11 e A17 testadas lado a lado, deliberadamente**: A11 normaliza por preço
(evita confundidor de nível entre símbolos), A17 normaliza por atividade
monetária bruta (overshoot). Mesmo fenômeno, duas leituras — deixa o
LightGBM/medição decidir qual carrega mais informação, não decidido aqui.

**A11 não é promoção de rotina**: estava `layer: L4` (aposentada, já
reprovada uma vez). A anistia de `AG-362` cobre só `L3`. Reativação é
override deliberado, registrado em `AG-372`, com tese nova declarada — não
uma rehidratação automática.

**B09/B10/B11/A10 permanecem `layer: L4`**, não reativadas — anotadas como
"supersedidas por B12" no registry, não apagadas (limpeza de código morto é
tarefa separada, sem consequência de leakage).

## Princípio de gate (nota curta, não ADR formal — decisão do Manager)

Sequência aplicada nesta rodada, antes de qualquer leitura de importância:

```
auditoria algébrica → auditoria de mecanismo → alinhamento de horizonte (H)
→ eliminação de redundância → [walk-forward/incremental, PENDENTE] → LightGBM → SHAP
```

Os 3 primeiros passos foram feitos nesta sessão (ver acima). Os 2 últimos —
medir se o Alpha sob CPCV purgado ganha algo com as 7 novas — são o mesmo
trabalho pendente que `AG-362` já deixou registrado como não feito para as
15 anteriores (cai do lado `src/models/`, sessão de ML). Nota permanente
adicionada ao cabeçalho de `src/features/registry.yaml`.

## Consequência

`T1_FEATURE_IDS` vai de 22 para 29. Nenhuma medição de valor incremental
real foi feita ainda — mesma ressalva que `AG-362` já registrou pras 15
anteriores ("abre elegibilidade, não prova o ganho"). Decisão de retreinar
sob o vetor de 29 é separada, do Manager.

## Addendum — Lote D2 (2026-08-28, mesma sessão): candle features validadas por raciocínio próprio + spec do usuário

Depois da entrega do Lote D acima, o usuário perguntou diretamente por que
nenhuma feature de candlestick tinha sido desenvolvida "pelo potencial de
raciocínio" próprio (não só reativação/reconsolidação das antigas), e em
seguida forneceu uma especificação técnica externa de ~20 famílias de
"Candle Features" (código Pandas/numpy, pipeline de 8 gates), com
autorização condicional explícita: "você pode criar mais se validado".

**Validação (rigor obrigatório, não aceitação automática do spec externo):**

- **Pandas rejeitado de saída** — spec inteiro escrito em Pandas, viola B26
  (Pandas só em interop de borda, núcleo é Polars lazy/numpy). Reimplementado
  no idioma do repo (Idioma A, `FloatArray` in/out).
- **`candle_open_gap` (gap de abertura) — já removida.** É exatamente
  `A12_gap_pct`, removida por `AG-316`: "gap de sessão" pressupõe fechamento/
  abertura de mercado, mecanismo que não existe em cripto 24/7. Não
  reimplementada.
- **Família wick/position do spec re-deriva a identidade algébrica de
  A07-A10** (mesmo defeito já documentado no corpo principal deste ADR) —
  incluindo uma redundância NOVA que o próprio spec do usuário não tinha
  percebido: `open_location = close_location − A07` (upper_wick/lower_wick
  reescritos em função de `close_location` e do body já existente são
  combinação linear exata, não informação nova). Não reimplementada como
  família própria — motivo registrado para não repetir o erro de "aceitar
  spec externo sem auditar mecanicamente".
- **Família Z-score (`N ∈ {5,10,20,50}`) repete o erro de janela nunca
  calibrada contra `H`** — mesmo defeito de B02/B09/B04/B05 no corpo
  principal deste ADR. Rejeitada como está; não existe versão "calibrada"
  óbvia sem medição nova (fora de escopo desta rodada).
- **Engolfo (`B18`) veio de raciocínio próprio**, anterior ao spec do
  usuário — motivado pela pergunta "nenhuma de candlestick... para dollar
  bar cripto?" — não do documento externo.

**7 features genuinamente novas, validadas e implementadas** (`T1_FEATURE_
IDS` 29→36):

| id | família | fórmula | tese |
|---|---|---|---|
| `A18_body_log` | candle | `ln(C_t/O_t)` | corpo em log-retorno, simétrico e comparável entre símbolos (diferente de `A07`, que é linear `[-1,1]`) |
| `A19_log_range` | candle | `ln(H_t/L_t)` | amplitude em log — mesma lógica de simetria/comparabilidade de A18, mede dispersão intrabarra não capturada por A07-A11 |
| `A20_log_duration` | dollar bar | `ln1p((close_time−open_time)/1000)` | duração real da barra em segundos — só varia sob `dollar_r{1,2,3}` (constante por construção sob `time_15m`, tratado explicitamente nos testes) |
| `A21_log_dollar_velocity` | dollar bar | `ln1p(quote_volume/duration_s)` | velocidade de fluxo monetário — só computável sob dollar bar (`quote_volume`/`threshold_quote` são `NaN` sob `time_15m`) |
| `B16_log_range_ratio_1` | volatilidade/candle | `ln(range_t/range_{t-1})` | expansão/contração de range barra-a-barra, lag=1 (granularidade mais fina do lote, não `H`) |
| `B17_directional_pressure_h3` | momentum | `Σbody(H)/Σ\|body\|(H)` | pressão direcional acumulada em `H=3`, robusta a reversões intra-janela (diferente de `B12`, que só olha posição, não direção acumulada) |
| `B18_engulfing_atr` | candle/reversão | `-sign(body_atr_{t-1})×body_atr_t` | engolfo contínuo (não binário como o padrão clássico) normalizado por ATR — raciocínio próprio, sinaliza reversão de corpo maior que o anterior em direção oposta |

**Achado técnico no caminho — `A20_log_duration` é CONSTANTE (não `NaN`) sob
`time_15m`**, diferente de A17/A21 que são `NaN` sob esse `bar_source`
(grade de relógio fixo dá duração fixa ~15min por definição, o que zera o
desvio-padrão da coluna). Quebrou `test_t1_ortogonalidade_spearman_2anos`
(matriz de correlação deixa de ser simétrica por `NaN != NaN` na divisão por
`stddev=0`) — corrigido excluindo `A20_log_duration` do teste de correlação
(não do vetor real, que roda sob dollar bar) junto com A17/A21.

9 testes de causalidade/edge-case novos (`tests/unit/test_features_groups.
py`). `T1_FEATURE_IDS` (36) confirmado idêntico a `layer2_feature_ids()`
via execução real (`uv run python`, autorizado pelo Manager). Suíte alvo de
features: 196 passed. Suíte completa: 2524 passed, 2 skipped, 3 failed —
as 3 falhas são em `tests/unit/test_analysis_tau_diagnostics.py`
(`src/analysis/tau_diagnostics.py`, `TypeError` sobre `trades_per_year=None`
num `experiments/alpha_layer1_report.json` real, modificado por retreino
anterior desta sessão), módulo não tocado por este lote — reportado como
achado separado, não bloqueia este ADR.

## Addendum — `AG-373` (2026-08-28, mesma sessão): A17 redesenhada por defeito dimensional real, achado por auditoria independente

Agente `feature-dev:code-reviewer` sob persona de ML Feature Engineer
(autorizado pelo Manager pra validar ponta a ponta a matemática
financeira das 14 features do Lote D/D2) achou que `A17_true_range_per_
overshoot` (v1, `TR_t/overshoot_t` cru) era a ÚNICA das 14 sem ser
adimensional — `TR_t` tem unidade de preço (`$/coin`, via `support.
true_range`), `overshoot_t = quote_volume_t - threshold_quote_t` tem
unidade de notional em dólar puro (`price*quantity` somado por trade,
`src/data/bars.py`). A razão crua tem unidade residual `1/coin`, o que
todas as OUTRAS 13 features do lote evitam por desenho (log-retornos,
razões preço/preço, normalizadas por ATR). Confirmado por leitura direta
do código (Claude, sessão principal) antes de virar `AG-373`.

**Risco real, não hipotético**: como o preço nominal de cada símbolo
varia por ordens de grandeza ao longo do histórico de treino (2021-12 a
2026-08+), `TR_t` cresce sistematicamente com o nível de preço do
próprio ativo ao longo do calendário, enquanto `overshoot_t` segue um
processo distinto (tamanho típico do trade que fecha a barra) — risco de
deriva DENTRO do histórico de um único símbolo, eixo diferente do
confundidor "nível de preço ENTRE símbolos" (esse já mitigado por
treinar por `(symbol, resolution_id)`, não pooled).

**Resolução — v2, sem remediação cosmética, correção estrutural**:
normalizar os DOIS lados contra sua própria escala de referência ANTES
de dividir, em vez de só trocar o numerador/denominador por outra coisa:

```
v1 (defeituosa): TR_t / overshoot_t                          -- unidade 1/coin
v2 (corrigida):  ln1p( (TR_t/C_{t-1}) / (overshoot_t/threshold_quote_t) )
                 = ln1p( A11_t × threshold_quote_t / overshoot_t )        -- adimensional
```

`TR_t/C_{t-1}` é exatamente `A11_true_range_pct` (retorno relativo,
adimensional); `overshoot_t/threshold_quote_t` é a fração de quanto a
barra passou do alvo (adimensional, cancela qualquer recalibração de
`threshold_quote` ao longo do tempo). A razão de duas quantidades
adimensionais tem unidade final = nenhuma — corrigido por construção,
não por medição empírica (dimensional analysis não precisa de dado pra
decidir, só de aritmética — `Meça antes de afirmar` do `CLAUDE.md` não
se aplica aqui, o defeito é de FÓRMULA, não de magnitude a estimar).

`ln1p` no final não é estético: overshoot pequeno relativo ao threshold
é o caso ECONOMICAMENTE ESPERADO sob dollar bar (`AG-321` — a barra
fecha quase exatamente no threshold), não um evento raro — o denominador
interno (`overshoot/threshold_quote`) é tipicamente pequeno, produzindo
valores grandes com cauda pesada à direita. Mesmo tratamento que
A18/A19/A20/A21/B16 já aplicam no mesmo lote, por CONSISTÊNCIA com o
resto do batch, não por escolha isolada.

**Verificação**: novo teste `test_a17_invariante_a_nivel_de_preco`
(`tests/unit/test_features_groups.py`) prova a correção diretamente —
escala `high`/`low`/`close` por 37× (simulando outra época de preço do
mesmo ativo) e confirma que a saída NÃO muda; sob v1 esse teste teria
FALHADO (a saída mudaria proporcionalmente à escala). 3 testes de A17 no
total (causalidade, guarda `overshoot<=0`/`threshold_quote<=0`,
invariância de nível de preço) — suíte alvo de features 199 passed,
`banned_patterns`/`ruff`/`mypy`/`check_unguarded_ratios` limpos nos
arquivos tocados (1 falso positivo esperado no ratio checker — guarda via
variável `valid` intermediária, não reconhecida pela heurística atual,
revisado e confirmado seguro).

`nan_policy`/`sources`/`causal_proof` atualizados em `registry.yaml`
(`version: v2`). Achado secundário corrigido no caminho: `build.py` não
definia `threshold_quote` no branch `else` (sob `bar_source=time_15m`) —
`quote_volume`/`overshoot` já eram postos a `NaN` nesse branch, mas
`threshold_quote` nunca tinha sido referenciado fora do `if` até A17 v2
precisar dele como parâmetro explícito; corrigido (agora os 3 saem `NaN`
juntos sob a grade legada, consistente).

Detalhe completo: `audit/architecture_gaps_log.yaml::AG-373`.

## Referências

`audit/architecture_gaps_log.yaml::AG-372`, `AG-373`, `audit/feature_
thesis/fichas_69_2026-08-25.yaml` (vereditos originais citados acima),
`docs/ADR-005_arquitetura_do_feature_engine_2026-08-26.md` §1.3/§2/§15,
`audit/architecture_gaps_log.yaml::AG-321` (degenerescência de
`quote_volume`), `AG-362` (reversão do gate de promoção),
`audit/architecture_gaps_log.yaml::AG-316` (remoção de `A12_gap_pct`,
mecanismo de gap de sessão inexistente em cripto 24/7).
