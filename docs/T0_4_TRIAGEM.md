# T0.4 — Triagem das 54 divergências PRD↔código

> PRD_V4_1.md §3.1 T0.4, Gate G-C0-5. Fonte: `docs/CODE_DISCOVERY.md` (leitura de código,
> `code_version: ddc0362`) + `experiments/code_discovery.json::estagios.*.divergencias_prd`
> (54 entradas, reconciliado item a item contra o PRD_V3_2_UNIFICADO.md).
>
> **Regra de classificação:** por padrão o código é a verdade (Regra de verdade do próprio
> `CODE_DISCOVERY.md`) — a maioria das 54 já é comportamento deliberado, testado e
> autodocumentado no código, com o texto do PRD desatualizado ou ambíguo por trás. Só vira
> `corrigir-código` onde o código não tem justificativa registrada e o gap parece
> omissão, não decisão.
>
> - **corrigir-PRD** — código está certo/deliberado; o texto do PRD precisa ser atualizado
>   para descrever o estado real (ou marcar como TBD/roadmap futuro).
> - **corrigir-código** — o código tem um gap real sem decisão documentada por trás; vale
>   avaliar implementar/corrigir.
> - **ambiguidade-de-vocabulário** — não há divergência de comportamento; é rótulo/nome/
>   enquadramento textual que pode ser lido de duas formas. Nenhum lado está "errado".
>
> Triagem não é correção — nenhuma mudança de PRD ou código foi feita aqui. É o inventário
> que a Camada 1 (M1-M6) precisa para não herdar ambiguidade não resolvida.

## Resumo

| classificação | n | % |
|---|---|---|
| corrigir-PRD | 40 | 74% |
| ambiguidade-de-vocabulário | 12 | 22% |
| corrigir-código | 2 | 4% |
| **total** | **54** | 100% |

Nenhum dos 54 é um bug de comportamento incorreto — todos os itens fora de
`ambiguidade-de-vocabulário` são o PRD descrevendo um estado que o código não tem (texto
desatualizado, prospectivo, ou uma versão anterior do desenho) ou uma decisão de engenharia
documentada que o PRD ainda não absorveu. Os 2 `corrigir-código` são os únicos onde o gap não
tem uma decisão explícita por trás.

---

## BARRA (7)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | Layout Data Lake — `data/raw/{fonte}/{yyyy}/{mm}/` + `data/processed/` (PRD) vs `data/capacity/{source}/{symbol}/{yyyy-mm-dd}.parquet` real, `PROCESSED_DIR` nunca usado | corrigir-PRD | §1.2 precisa descrever o layout provisório real, não o alvo nunca construído |
| 2 | Bloco INVARIANTES §1.3 lista `assert effective_start` como gate do relatório | corrigir-PRD | código resolve corretamente uma inconsistência do próprio exemplo do PRD |
| 3 | Check 2 (checksum) não implementado | corrigir-PRD | **já resolvido nesta sessão** — `src/data/download.py` (T0.3/download multi-ativo) agora grava e verifica SHA256; §1.3 check 2 pode ser atualizado para refletir isso |
| 4 | Check 6 (UTC) sem computação real, só nota descritiva | corrigir-código | único dos 7 sem decisão documentada por trás — é um gap de verificação real, não uma escolha |
| 5 | Check 9 (grade completa) não reprova o gate | corrigir-PRD | resolvido de forma consistente com o próprio exemplo do PRD, só não declarado em prosa |
| 6 | Cobertura por feature (PRD) vs por fonte T1 (código) | corrigir-PRD | documentado como provisório até `registry.yaml` existir como fonte de verdade |
| 7 | Nomenclatura `mark_price_1m`/`premium_index_1m` (PRD) vs `mark_price_klines_1m`/`premium_index_klines_1m` (código) | ambiguidade-de-vocabulário | puro nome de diretório, zero diferença de comportamento |

## VOLATILIDADE (4)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | TF 30m (PRD §2.4) vs 15m (código) | corrigir-PRD | já autodocumentado em `registry.yaml` como resíduo textual da migração 30m→15m |
| 2 | Convenção de nomes `{grupo}{nn}_{nome}_{parametro}_{tf}` não seguida (`C01_atr_20` sem sufixo `_tf`) | corrigir-PRD | renomear quebraria os 135 pontos de fan-in catalogados; mais barato atualizar o exemplo da convenção |
| 3 | Janelas de barra (C06 12/96, C07 48) calibradas implicitamente para 30m, aplicadas literalmente a 15m | corrigir-PRD | pendência de medição, não de texto — já registrada como pergunta em aberto pro Sprint 8; PRD deveria marcar como TBD explícito em vez de implicar que os números atuais têm base |
| 4 | Rótulo "ATR_20" genérico em A05 vs A13 (PRD) sem distinguir absoluto/percentual | ambiguidade-de-vocabulário | código resolve por análise dimensional, confirmado por teste; PRD só precisa de um adendo de notação |

## REGIME (6)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | R5 tem precedência sobre tudo (PRD §4.3) vs R0/warmup vence R5 (código) | corrigir-PRD | deliberado, testado (`test_r0_tem_precedencia_sobre_r5_durante_warmup`) |
| 2 | Schema de saída — 10 colunas (PRD §4.6) vs 12 (código, +`cost_atr_ratio`/`econ_regime`) | corrigir-PRD | extensão documentada como tal no próprio código |
| 3 | `bars_in_regime` dtype `int16` (PRD) vs `Int32` (código) | corrigir-PRD | overflow real medido em >32.767 barras sobre 6,6 anos de histórico |
| 4 | Denominador de consistência — "6 de 7" (§5.3, não corrigido) vs "6 de 6" (§5.4 + `constants.yaml`, já corrigido) | corrigir-PRD | o PRD se contradiz internamente; §5.3 precisa da mesma correção que §5.4 já recebeu |
| 5 | R1..R4 (regime de reporte) vs 6 ambientes (RANGE/TREND × tercil de custo) — eixos ortogonais nunca cruzados | ambiguidade-de-vocabulário | dois conceitos distintos share vocabulário de "regime"; não é conflito, é dois sistemas paralelos |
| 6 | Regra econômica — "cost_atr_ratio < p33 expansivo" (PRD, comparação de valor) vs comparação de posto percentil (código) | ambiguidade-de-vocabulário | equivalente por definição; método (Fenwick tree/rank) diferente do que a redação sugere |

## META-LABEL (6)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | TF decisão 30m (PRD prosa §3.1/§3.3/§3.4/§3.6) vs 15m (PRD YAML §3.3 + código) | corrigir-PRD | inconsistência interna do PRD; YAML+código são a fonte consistente |
| 2 | `t_post = t0 + latência_decisão` (PRD) vs `t_post = t0` sempre (código) | corrigir-PRD | simplificação explícita — nenhuma constante de latência existe ainda; PRD deveria marcar como TBD |
| 3 | Coluna `t_exit` no schema (PRD §3.5) ausente no código | corrigir-código | único dos 6 sem decisão documentada — "parece simplesmente não implementada", não uma escolha registrada |
| 4 | `adverse_selection_bps` "markout medido" (PRD) vs constante fixa 1,5bps em toda linha (código) | corrigir-PRD | decisão conservadora documentada; medição real (`fill_simulator.py`) reservada pra calibração futura (§9.5, Sprint 15-16) |
| 5 | Coluna `mfe_atr_units` existe no código, ausente do schema §3.5 do PRD | corrigir-PRD | código à frente da documentação, adicionar ao schema |
| 6 | `side` domínio "−1/0/+1" `int8` (PRD) vs só `+1`/`-1` (código, `ValueError` em 0) | corrigir-PRD | artefato de copy-paste da coluna `label` adjacente, documentado explicitamente no código |

## PESOS (1)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | §0.2 R4 armadilha 1 — PRD contrasta "concorrência pontual" vs "vizinhança de sobreposição" e rejeita a segunda | ambiguidade-de-vocabulário | não é divergência real — código implementa fielmente a fórmula que o próprio PRD elege como correta; confirmação de conformidade, catalogado só por instrução de grep exaustivo |

## BARREIRAS (2)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | Vetorização "pendente" (PRD §18.7.1/§18.7.2, tom prospectivo) vs já implementada e testada (`barrier_sweep.py`) | corrigir-PRD | texto desatualizado, não erro de comportamento |
| 2 | Varredura `tp_atr_mult`/`sl_atr_mult` "pendente" (PRD) vs em andamento (`constants.yaml::sweep_required` + `faixa2_caminho_b.py` já roda grid 3x3) | corrigir-PRD | mesmo item de pendência do PRD sendo fechado pelo código atual |

## FEATURES (4)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | Invariante 6 (ortogonalidade T1 ≤0,70) é `assert` rígido no PRD §2.15, mas o teste só reporta, nunca falha o build | corrigir-PRD | deferido deliberadamente pra Sprint 6+ (resolução por permutação); PRD deveria marcar como não-gating até lá em vez de implicar enforcement já ativo |
| 2 | Nome do arquivo `registry_v{n}.yaml` (PRD) vs `registry.yaml` sem sufixo (código); exemplo de schema do PRD usa `tf: 30m` | corrigir-PRD | resíduo de versionamento e do mesmo TF residual do estágio VOLATILIDADE |
| 3 | Ambiguidade de unidade `ATR_20` em A05/A13 (mesmo item do estágio VOLATILIDADE #4) | ambiguidade-de-vocabulário | duplicata do mesmo achado, catalogada nos dois estágios por escopo de leitura |
| 4 | Lookback A05 — "4+20" (PRD, retorno+ATR embutido) vs `lookback_bars: 4` no registry (só o retorno) | ambiguidade-de-vocabulário | "lookback" não tem definição clara de escopo próprio vs transitivo através de inputs |

## LEARNER (6)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | Cronograma completo §5.9/§5.11 (Camadas 2-5 + Meta) vs só Camada 0/1 implementadas | corrigir-PRD | escopo deliberado do V1 MVP; PRD deveria marcar Camadas 2-5 como roadmap futuro explícito |
| 2 | "CPCV interno, 6 grupos" pra calibração (PRD passo 5) vs split estratificado simples sobre o treino externo (código) | corrigir-PRD | implementação interina atual; CPCV interno purgado é trabalho futuro |
| 3 | Walk-forward ancorado 14 janelas (PRD §5.9) vs harness CPCV do Sprint 7 reusado como substituto (código, Sprint 11 citado como alvo) | corrigir-PRD | já autodocumentado no docstring do módulo |
| 4 | `E02f_funding_z` sem restrição (0) no exemplo do PRD §5.3 vs restrição forçada ±1 por lado (código) | corrigir-PRD | mudança de leitura documentada explicitamente em `monotonic.py` |
| 5 | 3 features com −1 fixo citando tabela de IC de 7 anos (exemplo do PRD §5.3) — mas o PRD, 2 linhas abaixo, proíbe usar essa tabela | corrigir-PRD | o PRD se contradiz consigo mesmo; código segue a proibição (correto), o exemplo precisa de correção |
| 6 | `colsample_bytree: 0,8` (PRD §18.5.2, inventário histórico) vs `1.0` em uso (§5.10, já corrigido) | corrigir-PRD | §18.5.2 é registro retrospectivo, não spec vigente — precisa de nota cruzada explícita pra não confundir leitor |

## CALIBRAÇÃO (3)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | `confidence_rank` coluna oficial do schema (PRD §5.12) vs só função de pós-processamento sobre cópia em memória, nunca persistida (código) | corrigir-PRD | não é bug escondido — o próprio código documenta que está fora do parquet oficial (`n_lifetime += 1`); PRD deveria remover do schema oficial até ser formalmente produtizado |
| 2 | `ensemble_std`/`n_models_agree` — discordância real entre 12 modelos (PRD) vs placeholders `None`/`1` (código, Camada 3 ausente) | corrigir-PRD | mesmo padrão do item LEARNER #1 — Camada 3 é trabalho futuro |
| 3 | Fórmula de `confidence_rank` "por fold" — onde existe, bate exatamente com o PRD | ambiguidade-de-vocabulário | não há divergência de fórmula, só de localização/persistência (já coberta no item 1) |

## VALIDAÇÃO (11)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | Purge com margem fixa `min_bars: 16` (PRD §11.4 YAML) vs purge por `t1` real de cada linha (código) | corrigir-PRD | melhoria deliberada sobre o spec, autodocumentada; PRD YAML também diverge do próprio `time_stop_bars=32` atual |
| 2 | Embargo "175 barras ≈ 88h" (comentário YAML do PRD) vs 43,75h reais a 15m (código) | corrigir-PRD | comentário residual de quando o TF de decisão era 30m; já autodocumentado em `constants.yaml` |
| 3 | Nome da feature-alvo do teste 4 — `funding_next_est` (PRD §11.5) vs `E02f_funding_z_expanding` (código) | ambiguidade-de-vocabulário | nome diferente, mesma garantia causal, o próprio teste já documenta a diferença de nome |
| 4 | `walk_forward.py` especificado com módulo/CLI/6 gates (PRD §11.4.1) — não existe | corrigir-PRD | ausência já confirmada e documentada em `src/validation/__init__.py`, marcar como roadmap |
| 5 | PBO via CSCV listado como métrica obrigatória (PRD §11.6) — não existe em código | corrigir-PRD | mesma classe do item 4, já autodocumentado |
| 6 | `N_effective = 960` estático a priori (PRD §11.6) vs `N_lifetime` medido real = 45 (`audit/n_lifetime.yaml`) | corrigir-PRD | o número do PRD é uma estimativa a priori nunca reconciliada com o ledger real medido — é exatamente o tipo de gap que a Regra Zero existe pra evitar |
| 7 | `n_splits`/`n_backtest_paths` como config solta no YAML (PRD) vs `@property` derivada via `math.comb` (código) | ambiguidade-de-vocabulário | mesmos valores numéricos (15, 5); só enquadramento diferente (config vs derivação matemática) |
| 8 | Docstring de `baselines.py` cita "5 baselines — §16.1" quando §16.1 só define 4 (B5 está em §16.6) | corrigir-código | é uma citação errada dentro do próprio código (docstring), não do PRD — fix de uma linha em `baselines.py:1` |
| 9 | HHI nominal `Σ share²` (PRD §5.8, único critério descrito) vs HHI efetivo é o que de fato decide o gate em produção (código) | corrigir-PRD | extensão pós-PRD (achado D1 Sprint 4); §5.8 precisa descrever explicitamente que o efetivo é o critério real |
| 10 | `carry_share = PnL_carry/PnL_total` divisão simples (PRD §16.6) vs guardado contra denominador negativo, `NaN` quando inválido (código) — mais uma segunda fórmula informal circulando em `attribution.py` | corrigir-PRD | guard é fix documentado e correto; PRD precisa descrever o guard. A segunda fórmula informal é debt separado — vale considerar oficializá-la numa rodada futura, não coberto por esta triagem |
| 11 | `sample_size_b1` = contagem real de trades preenchidos (PRD §16.1 + docstring da própria função) vs média entre os 5 caminhos de CPCV (call-site de produção) | corrigir-PRD | não é bug — variantes exatas já existem (`run_b1_per_path`); docstring devia qualificar que o call-site de produção usa a média |

## EXECUÇÃO (4)

| # | divergência | classificação | nota |
|---|---|---|---|
| 1 | Tabela §8.3 do PRD mostra arredondamento pra cima (1 unidade) em stop=2% | corrigir-PRD | código (`floor_to_step`, ROUND_FLOOR) nunca arredonda pra cima — segue §8.2, não a leitura implícita da tabela §8.3; já documentado e testado pelo próprio autor |
| 2 | `t0` "fechamento de barra de 30m" (PRD §3.1/§3.3) vs grade de 15m (código) | corrigir-PRD | mesmo resíduo textual do TF em outros estágios |
| 3 | "Decrementa por cancelamentos estimados, taxa calibrada" (PRD §9.5) vs cancelamento não modelado (código) | corrigir-PRD | decisão estrutural documentada — `p_fill` medido é limite inferior pessimista por design; PRD deveria descrever essa limitação explicitamente |
| 4 | `adverse_selection_bps` escalar único (PRD §9.5 outputs) vs 3 horizontes separados (1m/5m/30m), nunca escrito de volta em `constants.yaml` (código) | corrigir-PRD | schema deveria refletir os 3 horizontes; write-back de calibração é Sprint 15-16 |

---

## Achados que atravessam múltiplos estágios (não recontados na tabela de 54)

- **TF 30m→15m residual** aparece em pelo menos 5 estágios (BARRA implícito, VOLATILIDADE #1, FEATURES #2, META-LABEL #1, EXECUÇÃO #2) — é o MESMO resíduo textual da migração `decision_tf` v3.0→v3.1, não 5 achados independentes. Uma única correção de texto no PRD (busca global por "30m"/"barra de 30m" nas seções §0.1/§0.4/§0.5/§2.2-2.6/§3.1/§3.3/§3.4/§3.6/§9.5) resolveria todos de uma vez.
- **Ambiguidade de unidade `ATR_20`** aparece em VOLATILIDADE #4 e FEATURES #3 — mesmo achado, duplicado por estarem em escopos de leitura diferentes.

## Itens fora da contagem de 54, catalogados como "confirmação de ausência" (não divergência)

META-MODEL (12º estágio): as três fontes (CLAUDE.md, PRD §6.1/§6.3/§6.8, código) concordam que o Meta está fora da V1 — sem divergência a reportar.

---

## Próximos passos sugeridos (não executados nesta triagem)

1. Os **2 `corrigir-código`** são baratos e baixo risco — `t_exit` (avaliar se é necessário ou remover do schema) e a citação `§16.1`→`§16.1/§16.6` em `baselines.py:1`.
2. **N_effective 960 vs 45** (VALIDAÇÃO #6) é o achado com maior peso decisório real — qualquer leitura de DSR que ainda cite 960 do PRD em vez do `N_lifetime` medido está usando um denominador ~21× menor que o real.
3. A correção de PRD em massa do **resíduo TF 30m→15m** é mecânica (busca-substituição orientada) e fecha 5 dos 40 itens `corrigir-PRD` de uma vez.
