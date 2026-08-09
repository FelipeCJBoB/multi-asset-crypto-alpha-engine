# Auditoria — Divisões sem guarda de sinal do denominador

> Gerado em 2026-08-09. Escopo: `src/risk/limits.py`, `src/risk/kill_switch.py`,
> `src/models/decomposition.py`, `src/backtest/` (`fill_reconciliation.py`,
> `_paths.py`, `__init__.py`), `src/validation/` (`cpcv.py`, `leakage.py`).
>
> Motivação: `src/models/decomposition.py:125` calcula `carry_share = pnl_carry
> / pnl_total` sem verificar se `pnl_total` pode ser `<= 0` — e pode, e é, nos
> dados reais de hoje (`src/backtest/fill_reconciliation.py` documenta que
> direção+carry medidos na janela do bookTicker são negativos). Hipótese
> testada aqui: isto é uma CLASSE de bug (razão sem garantia de sinal do
> denominador), não um caso isolado. Esta auditoria é só levantamento — nenhum
> código foi alterado.
>
> Nota de concorrência: outro agente está, em paralelo, introduzindo
> `Metric`/`safe_ratio` em `src/core/metric.py` e aplicando nos mesmos
> arquivos. No momento em que cada arquivo foi lido para esta auditoria,
> `src/core/metric.py` **ainda não existia** e nenhum dos 8 arquivos-alvo
> referenciava `Metric`/`safe_ratio` — confirmado por grep imediatamente antes
> de escrever este relatório. Nenhum achado abaixo é `JA_CORRIGIDO`.

## Resumo

- **13 divisões** de razão variável encontradas nos arquivos em escopo
  (excluindo conversões de unidade por literal fixo, contadas à parte).
- **2 `RISCO REAL`** — `src/models/decomposition.py:125` (o achado original)
  e **`src/risk/limits.py:228`** (`control_10_risco_real`, achado novo desta
  auditoria — mesma classe de bug, denominador é o MESMO campo `equity` que
  `src/risk/kill_switch.py` guarda corretamente duas linhas acima na árvore
  de import).
- **8 `INOFENSIVO`** — denominador estruturalmente não-negativo (contagem de
  linhas/`DataFrame.height`, produto de duas constantes de exchange sempre
  positivas, ou combinatória validada a montante) ou corretamente guardado
  com `<= 0`.
- **3 `NAO_APLICAVEL`** — conversão de unidade por literal fixo (`/1e4`,
  `/Decimal(10000)`), sem denominador variável.
- **0 `JA_CORRIGIDO`**.
- **Sem teste cobrindo o caso degenerado (denominador `<=0`/negativo)**: 3 de
  13 — `control_09b` (`limits.py:211`), `control_10` (`limits.py:228`, o
  `RISCO REAL`), e `carry_share` (`decomposition.py:125`, parcialmente: existe
  um teste que exercita `pnl_total < 0`, mas ele fixa o comportamento atual
  como esperado em vez de questionar se o gate deveria ser avaliável nesse
  regime — ver linha da tabela para detalhe).

## Tabela

| Local (arquivo:linha) | Expressão | Denominador pode ser `<=0`? Em que condição de mercado/dado real? | Denominador pode ser NaN? De onde viria? | O que acontece com a comparação contra limiar nesse caso (se houver)? | Existe teste cobrindo o caso degenerado? | Veredito |
|---|---|---|---|---|---|---|
| `src/risk/limits.py:211` (`control_09b_resolucao_sizing`) | `n_req_over_unit = sizing.notional_req / sizing.unit_notional` | Guarda só `unit_notional == 0` → `FAIL` (linha 209). `unit_notional = filters.step_size * mark_price` (`src/risk/sizing.py:132`, fora do escopo mas consultado para contexto): `step_size` é filtro de exchange, contratualmente > 0; `mark_price` é o preço de mark do BTC perpétuo, nunca observado `<= 0` em condição de mercado real (diferente de commodities tipo WTI). Só chegaria a `<=0` via corrupção de feed de dado (bug, não condição de mercado). | Não surge nativamente de aritmética `Decimal` normal; só se um `Decimal('NaN')` já viesse de uma divisão anterior em `sizing.py` (fora de escopo) e fluísse até aqui — não demonstrado no pipeline atual. | Sem `abs()` na comparação (`PASS if n_req_over_unit >= min_units else FAIL`). Um flip de sinal isolado no denominador (ex. `mark_price` corrompido) empurra `n_req_over_unit` para negativo, que já é `< min_units` (positivo) → `FAIL` corretamente, não mascara. Só mascararia (falso `PASS`) se numerador (via `equity`, injetado separadamente) E denominador (via `mark_price`) flipassem de sinal SIMULTANEAMENTE — duas fontes independentes corrompidas ao mesmo tempo, cenário implausível. | Não. `tests/unit/test_risk_limits.py` (`test_control_09b_*`) nunca passa `unit_notional<=0`. | **INOFENSIVO** — denominador estruturalmente positivo por construção (preço × step de exchange) sob dado real; mesmo num flip isolado, a ausência de `abs()` faz o controle falhar seguro, não passar mascarado. |
| `src/risk/limits.py:228` (`control_10_risco_real`) | `ratio = sizing.risk_real / sizing.equity` | Guarda só `equity == 0` → `FAIL` (linha 226) — **não** `<= 0`. `equity` é patrimônio de conta MEDIDO (não uma constante estrutural) — pode legitimamente cair a zero ou negativo em perda extrema, dado o capital do projeto (US$196,85, lote mínimo já é 33% do equity, R1). É o MESMO campo `equity` que `src/risk/kill_switch.py` (K01/K02) guarda com `<= 0` e testa explicitamente negativo. | Não surge nativamente; mesma observação de `Decimal` acima. | **`risk_real` é estruturalmente `>= 0`** (`notional_real * stop_pct`, produto de duas quantidades não-negativas, `src/risk/sizing.py:127`). Se `equity < 0`: `ratio = risk_real/equity <= 0` (não-negativo / negativo = não-positivo), que é **sempre** `<= max_ratio` (positivo, ~0,006) → **`PASS` automático**. O controle de "estouro de risco" aprova SILENCIOSAMENTE qualquer sizing quando a conta está com patrimônio negativo — mascara exatamente como o achado original. | **Não.** `tests/unit/test_risk_limits.py:242-249` (`test_control_10_passa_no_exemplo_do_prd`, `test_control_10_falha_acima_do_teto`) nunca passa `equity<=0`; nenhum teste equivalente ao `test_k01_not_computable_com_equity_nao_positivo` de `kill_switch.py` existe para `control_10`. | **RISCO REAL** — mesma classe do achado original, sobre o mesmo campo `equity`, no mesmo Sprint/módulo, com a assimetria de guarda entre `limits.py` (`==0`) e `kill_switch.py` (`<=0`, testado) como evidência de que é omissão, não desenho. |
| `src/risk/limits.py:274` (`control_13_orcamento_fees`) | `estimated_cost_usd = sizing.notional_real * _to_decimal(cost_bps) / Decimal(10000)` | Denominador é literal fixo `Decimal(10000)` (conversão bps→fração), não varia com dado nenhum. | N/A. | N/A. | N/A. | **NAO_APLICAVEL** — conversão de unidade, sem denominador variável. |
| `src/risk/limits.py:300` (`control_15_max_drawdown`) | `drawdown = (equity_peak_usd - sizing.equity) / equity_peak_usd` | Guarda `equity_peak_usd <= 0` → `NOT_COMPUTABLE` (linha 297) **antes** da divisão — cobre corretamente zero E negativo, qualquer que seja a causa. | Mesma observação Decimal; irrelevante pois o guard intercepta antes. | Divisão só executa com `equity_peak_usd > 0` garantido — sem caso degenerado a analisar. | Parcial. `test_control_15_not_computable_sem_pico_estabelecido` testa `equity_peak_usd==0`; negativo não é testado explicitamente, mas segue o mesmo caminho de código (`<=0`). | **INOFENSIVO** — guarda correta por construção; contraste direto (mesmo arquivo, controle vizinho) com o `RISCO REAL` de `control_10` acima. |
| `src/risk/kill_switch.py:107` (`k01_daily_loss`) | `ratio = daily_loss_usd / equity` | Guarda `equity <= 0` → `NOT_COMPUTABLE` (linha 104) — cobre zero e negativo. | Mesma observação Decimal; irrelevante, guard intercepta antes. | Divisão só executa com `equity > 0` garantido. | **Sim, explicitamente.** `test_k01_not_computable_com_equity_nao_positivo` (`tests/unit/test_risk_kill_switch.py:90-92`) testa `equity=Decimal("0")` **e** `equity=Decimal("-1")`. | **INOFENSIVO** — guardado e testado corretamente; é o par "certo" do mesmo campo `equity` que `control_10` erra em `limits.py`. |
| `src/risk/kill_switch.py:119` (`k02_max_drawdown`) | `drawdown = (equity_peak_usd - equity) / equity_peak_usd` | Guarda `equity_peak_usd <= 0` → `NOT_COMPUTABLE` (linha 116) — cobre zero e negativo. | Mesma observação Decimal; irrelevante. | Divisão só executa com `equity_peak_usd > 0` garantido. | Parcial. `test_k02_not_computable_sem_pico_estabelecido` testa só `equity_peak_usd==0`; negativo não testado explicitamente, mesmo caminho de código. | **INOFENSIVO** — guarda correta por construção. |
| `src/models/decomposition.py:99` | `funding_frac = trades["funding_bps"]...astype(np.float64) / _BPS_PER_UNIT` | Denominador é `_BPS_PER_UNIT = 10_000`, constante de módulo fixa (conversão bps→fração). | N/A. | N/A. | N/A. | **NAO_APLICAVEL** — conversão de unidade fixa. |
| `src/models/decomposition.py:103` | `cost_frac = (cost_entry_bps + cost_exit_bps) / _BPS_PER_UNIT` | Mesmo caso acima — literal fixo. | N/A. | N/A. | N/A. | **NAO_APLICAVEL**. |
| `src/models/decomposition.py:125` (`decompose`) | `carry_share = pnl_carry / pnl_total if pnl_total != 0.0 else float("nan")` | **Sim — e ocorre hoje.** `pnl_total = sum(ret_net)` sobre trades EXECUTADOS; soma de retorno líquido real, genuinamente negativa em regimes reais. O próprio `src/backtest/fill_reconciliation.py` (docstring do módulo + `limitations` do relatório, linhas 679-686) documenta que direção+carry medidos na janela real do bookTicker (2023-05..2024-03) **são negativos nos dois gates** — não é hipotético, é o dado de produção de hoje. Guarda cobre só `!= 0.0`, não o sinal. | `pnl_total` vem de `float(np.sum(ret_net))`; se algum `ret_net` não filtrado fosse `NaN` (não ocorre hoje — trades já vêm restritos a `barrier_hit != NOFILL` por quem chama), propagaria via `np.sum`. Via secundária, não a principal. | `gate3_carry_share_ok = abs(carry_share) < carry_share_max` usa `abs()` — não inverte trivialmente o sentido do gate por magnitude. Mas o problema é SEMÂNTICO, não só aritmético: quando `pnl_total<0`, "fração do lucro vindo de carry" deixa de ter sentido de negócio (não há lucro), e a razão pode ser dominada por ruído perto de `pnl_total≈0`. O teste existente (`test_decompose_carry_share_positivo_quando_funding_domina`) **assume e trava esse comportamento como correto** (`assert result.carry_share > 0.0` quando `pnl_carry<0` e `pnl_total<0`), sem questionar se `gate3_carry_share_ok` deveria sequer ser avaliado nesse regime. | Parcial — ver célula anterior. `pnl_total==0.0` exato (fora do caminho de `trades.is_empty()`) também não é exercitado por nenhum teste. | **RISCO REAL** — o achado original da task. Confirmado ainda presente no disco (linha 125, sem `Metric`/`safe_ratio`) no momento desta leitura. |
| `src/backtest/fill_reconciliation.py:327` (`_evaluate_gate`) | `fill_rate = float(n_filled) / float(n_base) if n_base > 0 else float("nan")` | `n_base = base.height` — contagem de linhas de um `pl.DataFrame` (`n_filled` idem, de um filtro do mesmo df). `DataFrame.height` é estruturalmente `>= 0` por definição (nunca negativo) — o guard `n_base > 0` cobre o único caso degenerado possível (`==0`). | Não — contagem inteira, nunca `NaN`. | Guard intercepta antes; sem caso a analisar. | Sim. `test_evaluate_gate_vazio_nao_quebra` (`tests/backtest/test_fill_reconciliation.py:217-239`) testa base vazia e verifica `np.isnan(result.fill_rate)`. | **INOFENSIVO** — denominador é uma contagem, estruturalmente não-negativa. |
| `src/backtest/fill_reconciliation.py:468` (`_fraction_true`) | `float(mask.sum()) / float(mask.len())` (guardado por `if mask.len()`) | `mask.len()` — comprimento de `pl.Series`, mesma garantia estrutural de não-negatividade que `.height`. | Não. | Guard intercepta `len()==0`. | Indireto — `test_compute_fill_selectivity_amostra_vazia_nao_quebra` exercita amostra vazia, que passa por esta função via `compute_fill_selectivity`. | **INOFENSIVO**. |
| `src/backtest/fill_reconciliation.py:489` (`_barrier_distribution`) | `float(row[1]) / float(total)` onde `total = df.height` | Função retorna `{}` antecipadamente se `df.height == 0` (linha 485-486) — divisão só executa com `total > 0` já garantido no corpo da função. | Não. | Guard estrutural antes da divisão. | Indireto — mesmo teste de amostra vazia acima. | **INOFENSIVO**. |
| `src/validation/leakage.py:393` (`_test_06_contaminacao_label`) | `round(total_purged / result.config.n_splits)` | `n_splits = comb(n_groups, n_test_groups)` (`cpcv.py:112`); `CPCVConfig.__post_init__` valida `n_groups >= 2` e `1 <= n_test_groups < n_groups`, levantando `CPCVError` caso contrário — logo `n_splits` é SEMPRE inteiro positivo (mínimo `comb(2,1)=2`), garantido por validação a montante antes de qualquer split ser gerado. | Não — resultado de `math.comb` com inputs inteiros validados. | N/A — nunca degenera. | Indireto — `_test_06_contaminacao_label` roda sobre `labels/v1/labels.parquet` real (via `run_all_leakage_tests`) e sobre fixture nos testes unitários; `n_splits` nunca chega a zero nesses caminhos nem em nenhum caminho possível dada a validação. | **INOFENSIVO** — combinatória garantida positiva por validação de configuração a montante, não por sorte de dado. |

## Achado lateral (fora do escopo pedido, registrado para não se perder)

`src/risk/sizing.py` (não está na lista de arquivos desta rodada, mas é a
FONTE de `equity`/`unit_notional`/`notional_req` consumidos por `limits.py`
acima) tem duas divisões da mesma família, ambas guardadas só por `!= 0`, sem
checagem de sinal:

- linha 129: `quant_error = abs(notional_real - notional_req) / notional_req
  if notional_req != 0 else Decimal("0")` — o numerador tem `abs()`, mas o
  denominador não é protegido contra sinal; se `notional_req` for negativo
  (possível se `equity` for negativo, já que `risk_usd = equity * risk_per_trade`
  alimenta `notional_req`), `quant_error` sai negativo, que é `<= tolerance`
  (positiva) — passaria `control_09a_erro_quantizacao` silenciosamente no
  mesmo cenário de `equity` negativo já flagueado acima para `control_10`.
- linha 131: `leverage_eff = notional_real / equity_d if equity_d != 0 else
  Decimal("0")` — mesmo padrão, consumido por `control_11_nocional_maximo`.

Não incluído na tabela principal (fora do escopo de arquivos desta task) e
não modificado — sinalizado aqui para uma rodada futura de auditoria olhar
`src/risk/sizing.py` explicitamente, já que é a origem comum de `equity`
para vários dos controles acima.
