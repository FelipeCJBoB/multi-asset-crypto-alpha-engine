# Mapeamento — constantes ASSUMED e literais hardcoded que afetam o Alpha

Data: 2026-08-24. Escopo: `src/features/`, `src/labels/`, `src/regime/`,
`src/models/`, `src/validation/cpcv.py`. Metodologia: 3 agentes em
paralelo, cada um lendo o pacote inteiro + `config/constants.yaml` +
cruzando com o lint (`tools/lint/banned_patterns.py`). Meta-model
confirmado sem nenhuma linha de código real neste repo — nada a mapear
lá.

Este documento é insumo pra auditoria conjunta (pergunta: "esse
parâmetro é o melhor pro motor cripto?") — não é veredito, é inventário.

## Achados de maior risco — mesma classe do bug já corrigido em `round_trip_cost_bps`

Constante declarada corretamente em `constants.yaml`, código não lê (ou
lê só parcialmente) — ou fração/probabilidade redonda hardcoded sem
medição, escondida do lint pela whitelist de literais permitidos.

| # | onde | o que é | por que é preocupante |
|---|---|---|---|
| 1 | `src/features/groups/group_a.py:46` vs `constants.yaml::feature_a05_vol_norm_divisor` | `A05_ret_vol_norm_4` tem o divisor `2.0` **hardcoded**; `A06_ret_vol_norm_12` lê a mesma constante nominal corretamente | Se alguém mudar a constante achando que afeta as duas features, só A06 muda — mesmo padrão exato do bug do `round_trip_cost_bps` (constante certa no YAML, código errado) |
| 2 | `src/models/baselines.py:621` | `long_prob = 0.5` — probabilidade de LONG no nulo B1' (side-shuffle) | Decisão metodológica real sobre a distribuição do nulo, passa 100% ileso pelo lint porque `0.5` está entre os 5 literais sempre permitidos |
| 3 | `src/regime/bocpd.py:59-60` | `_DEFAULT_PRIOR_KAPPA0=1.0` / `_DEFAULT_PRIOR_ALPHA0=1.0` — parâmetros de concentração do prior Normal-Inverse-Gamma do BOCPD | `1.0` também está na whitelist — aqui não é estrutural, é o FORMATO do prior conjugado, premissa estatística real |
| 4 | `src/models/hhi.py:352,364` | `gate3_4_passes(threshold=0.25)` / `gate3_4_max_share_passes(threshold=0.30)` — **o Gate 3.4 real de produção**, citado literalmente no DoD do `CLAUDE.md` ("HHI < 0,25") | Nunca declarado em `constants.yaml` — vive como default de parâmetro Python. Contradiz a própria "Regra Zero" que `src/models/_constants.py` declara |

## Class A (`provenance: ASSUMED`) — maior severidade por definição

| constante | arquivo | value | controla |
|---|---|---|---|
| `atr_window` | `features/build.py:248` | 20 | Janela do ATR de Wilder — insumo de metade do vetor T1 (A05,A13,A14,A15,B04,B05,C02,E27f) |
| `adverse_selection_bps` | `labels/triple_barrier.py:1225` | 1,5 | Placeholder de seleção adversa — **reportado na coluna, nunca subtraído de `ret_net`** (achado do agente 2, vale conferir se isso é intencional) |
| `regime_er_cutoff` / `_exit` | `regime/classifier.py:96-97` | 0,60 / 0,55 | Corte de entrada/saída do eixo tendência (histerese) — divide toda a partição estrutural de regime |
| `regime_vol_cutoff` / `_exit` | `regime/classifier.py:98-99` | 0,70 / 0,65 | Corte de entrada/saída do eixo volatilidade (HIGH_VOL/LOW_VOL) |
| `alpha_stability_screen_limiar` | `models/stability.py:102` | 0,02 | Piso de `estabilidade = força×consistência²` — decide se uma feature T1 sobrevive à Camada 2 |
| `alpha_t2_orthogonality_spearman_max` | `analysis/t2_ranking_ortogonalidade.py` | 0,70 | Regra de ortogonalidade — corrigida hoje (`sweep_required` estava mal declarado) |

(`tp_atr_mult`/`sl_atr_mult` já corrigidas hoje para `MEASURED`, fora desta lista.)

## Blind spot do lint, achado pelo agente 2 (não específico de nenhuma constante)

`tools/lint/banned_patterns.py` só examina literais `float` (`isinstance(node.value, float)`).
**Nenhum literal `int` em nenhum lugar do repo é verificado automaticamente** —
classe de risco maior que os "5 literais permitidos" que motivaram esta
varredura. Exemplo real, produção: `src/regime/hmm_gaussian.py`:
- `_DEFAULT_STICKY_CONCENTRATION = 10.0` (linha 166) — prior sticky de
  Dirichlet do HMM canônico (k=4), nunca calibrado contra dado real,
  `build_hmm.py` (o builder de produção) nunca passa outro valor.
- `_DEFAULT_NUM_EM_ITERS = 100` (linha 156, `int`) — nº de iterações do
  EM do mesmo HMM de produção, invisível ao lint por ser `int`.

## Outros candidatos suspeitos, por pacote

**Features** (`src/features/`): otimizadores EGARCH/ACD (`volatility_models.py`,
`acd.py`) têm ~16 hiperparâmetros de bounds/x0 fora de `constants.yaml`
— risco baixo hoje porque nenhum dos dois candidatos está wired em
produção (só ATR Wilder/Parkinson alimentam features reais).

**Regime** (`src/regime/`): `classifier.py:333`, `max(run, 2)` duplica o
valor de `regime_confirmation_bars` (2) como literal solto — se a
constante mudar, esse piso não acompanha, dessincroniza silenciosamente.

**Models** (`src/models/`): expoente `**2` em
`estabilidade = forca * consistencia**2` (`stability.py:84`) — sem
constante nomeada, sem `noqa`, sem justificativa registrada de por que é
quadrático em vez de linear.

## O que NÃO é problema (checado e descartado)

- Thresholds de `vol_expansion`/`vol_compression` (C10/C11) — declarados
  corretamente, lidos via `load_constant`, sem literal escondido.
- Transformações `2×ratio-1` e `(RSI-50)/50` — estruturais/definicionais,
  não hiperparâmetros de negócio.
- `_ALLOWED_NUMERIC_LITERALS` em si não é o bug — é um whitelist razoável
  pra literais matemáticos genéricos (confirmado: `-0.5` em log-likelihood
  Gaussiano, `0.5` na fórmula de Garman-Klass, `2.0` em Bollinger Bands —
  todos legítimos). O risco real são os poucos casos onde um desses 5
  valores esconde uma premissa de DOMÍNIO, não um valor matemático — os
  itens #2/#3 da primeira tabela são exatamente isso.
