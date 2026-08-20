# Validação cruzada final — M4 Regime: as 2 auditorias brutas + V2 + código + literatura

**Data:** 2026-08-19
**Escopo:** cruzamento de `50da269f-auditoria_consolidada_regime_v2.md` (V2, que já cruzava "V1" — consolidação de duas auditorias de árvore — contra o grounding técnico de código produzido nesta sessão) com as **duas auditorias externas brutas** (`audit_1.docx`, estilo "árvore", 19 pontos + árvore revisada; `audit_2.docx`, estilo "Portfolio Manager/Lead Quant", 5 FALHAS + árvore revisada), mais leitura direta de código adicional e pesquisa de literatura (4 agentes em paralelo: BOCPD/Adams & MacKay, Jump Model/λ, microestrutura de dollar bars, block-bootstrap/multi-resolução/DSR).

Resultado: a V2 estava certa em quase tudo que já cobria. O valor novo está em **resolver as duas discordâncias diretas entre as auditorias brutas** (nenhuma delas concordava entre si em 2 pontos centrais) e em **7 gaps reais que nenhuma das 3 auditorias tinha identificado**, confirmados por leitura direta de código.

---

## 1. As duas discordâncias resolvidas

### 1.1 BOCPD "fit único" — auditoria 1 disse "ok, só troque o nome"; auditoria 2 disse "é a maior falha, precisa reiniciar por fold"

**Veredito: a auditoria 2 está refutada, com evidência forte (matemática + literatura + código).**

Releitura de `run_bocpd` (`src/regime/bocpd.py:188-218`): o laço é estritamente sequencial — cada iteração `t` só consome `obs[t]` + o estado carregado de `t-1`. Não há nenhum passo de otimização em lote. Isso bate exatamente com a Eq. 3 do paper original (Adams & MacKay 2007, arXiv:0710.3742) — `P(r_t|x_{1:t})` é, por definição matemática do método, uma *filtering distribution* (nunca smoothing) — mesma categoria formal do Kalman filter, onde é consenso que um filtro online não precisa ser "refeito" porque seu estado já é a estatística suficiente de todo o passado causal (Särkkä, *Bayesian Filtering and Smoothing*). Rodar uma vez sobre 2019-2026 e fatiar por fold produz, matematicamente, o mesmo resultado em cada `t` que reiniciar do zero no início de cada fold.

O erro da auditoria 2: generalizar "precisa refit por fold" do HMM/Jump Model (que usam EM/otimização em lote — aí sim, expandir a janela contaminaria) para o BOCPD, que usa atualização conjugada fechada, sem batch. **Pior: a "correção" proposta reintroduziria uma patologia já documentada e corrigida** — reiniciar o prior a cada fold reproduz o "488 segmentos espúrios numa série estacionária de 500 barras" que motivou a calibração atual do warmup (`bocpd.py:130-146`).

**Achado colateral valioso:** a auditoria 1 (ponto 4) já tinha alertado, antes da auditoria 2 existir, que chamar isso de "fit" (em vez de "online update") "pode não causar erro agora, mas evita um erro futuro" — foi exatamente essa confusão terminológica que produziu a "maior falha" da auditoria 2. Vale trocar a nomenclatura na árvore/docs — barato, e já provou prevenir um erro de leitura real.

**Nuance que sobrevive (não é rejeitada):** `hazard_lambda` foi calibrado 1x sobre o histórico completo 2019-2026 (que inclui as janelas de teste) — problema **diferente e real** (já era P5/N2 da V2). A pesquisa de literatura reforça isso: nem a prática original de Adams & MacKay (valores fixos a priori — os experimentos do paper usam λ=250/1000, escolhidos por domínio, sem estimação sobre o dado) nem a extensão que aprende o hazard do dado (Turner, Saatçi & Rasmussen 2009 — mantém-se estritamente sequencial/online) sustentam calibrar sobre histórico com teste embutido. Eleva a prioridade do teste de sensibilidade já recomendado (P5-i/ii da V2).

### 1.2 Jump Model λ — auditoria 1 propôs testar transferibilidade (Auditor A); auditoria 2 propôs BIC dinâmico por fold + defender a saturação (Auditor B)

**Veredito: a literatura favorece claramente a auditoria 1 (Auditor A).**

Achado central: arXiv:2406.09578 ("Dynamic Asset Allocation with Asset-Specific Regime Forecasts") é quase um espelho do problema do projeto — alerta explicitamente contra "usar um mercado representativo tipo US LargeCap para representar toda a classe de ativos". BTC fazendo exatamente esse papel para ETH/SOL/BNB/XRP.

- Calibração **por ativo** é a norma na literatura de jump models (Nystrup, Bemporad, Cortese, Shu/Kolm/Mulvey — nenhum transplanta λ sem reteste).
- BIC dinâmico por fold **não tem precedente direto** — é extrapolação combinando duas práticas separadas (refit periódico por Sharpe + seleção informacional estática). Quando BIC foi comparado formalmente nesse exato tipo de modelo (Cortese et al. 2024, "Generalized Information Criteria for High-Dimensional Sparse Statistical Jump Models"), **perdeu para FTIC**.
- A tese "colapso = modelo sendo honesto" **não é citada por nenhum paper de jump models revisado**. O apoio indireto (literatura geral de changepoint) exige uma pré-condição — recalibração local do critério — que o setup atual não satisfaz.

**Ordem recomendada:** rodar o experimento de transferibilidade (Auditor A) primeiro; só depois, se a saturação persistir com λ localmente otimizado, a leitura "ausência real de regime" ganha sustentação.

---

## 2. Gaps reais confirmados por código, que nenhuma das 3 auditorias tinha (ou tinha errado)

| # | Gap | Evidência | Origem |
|---|---|---|---|
| G1 | "Distribuição condicional de retornos futuros" que a auditoria 2 pede como mudança nova **já existe** | `_anova_or_degenerate(labels, forward_return)` (`m4_regime_comparison.py:548-614`) já testa isso — Welch's F + ω² sobre `forward_return` por bucket. Welch é escolha até melhor que o Kruskal-Wallis sugerido (robusto à heterocedasticidade que regimes de vol violam por construção, já documentado no código). Gap real: (a) só h=1 barra à frente, nunca h=5/h=20; (b) só testa retorno, nunca **volatilidade futura**, apesar do regime ser construído com `log_return_1` E `realized_vol_short` | auditoria 2 FALHA2 (mal caracterizada) |
| G2 | "BTC conditional response" (`E[r_asset,t+h \| BTC_regime_t]`) está genuinamente ausente | `run_q3_common_factor_regime` (`m4_regime_comparison.py:1472-1604`) testa só concordância de RÓTULO (`adjusted_rand`), nunca retorno bruto condicional. `m6_common_factor_hypothesis.py` testa heterogeneidade de EDGE de trade entre símbolos — pergunta diferente. Barato de adicionar (reusa o as-of join já corrigido) | auditoria 1 pt7 |
| G3 | Estatística observada ponderada por trade, não por episódio | Nula já é episódio-aware (AG-092), mas `_q_statistic_from_bucket_codes` ainda pondera a estatística OBSERVADA por contagem de trade — episódio com 50 trades pesa 50x mais que um com 1 | auditoria 1 pt8 |
| G4 | `regime_persistence` não tem occupancy por estado, taxa de falso-transição nem delay de detecção | `regime_utility.py` só tem `median_duration_bars`/`switch_rate`/`n_segments` — nada de K efetivo, transition failure rate, detection delay | auditoria 1 pt6/11/12 |
| G5 | Block permutation por episódio (não bootstrap) está correto | Winkler et al. 2015/2016 ("multi-level block permutation") confirma que preservar duração/ordem do episódio e permutar o rótulo do bloco inteiro é desenho válido para a pergunta que o projeto faz (bucket carrega informação além da dependência temporal?); bootstrap em bloco resolve pergunta diferente (IC de métrica) | auditoria 1 pt9 (desnecessária, não errada) |
| G6 | Microestrutura é achado real mas incompleto | `count`/`taker_buy_volume`/`taker_buy_quote_volume` já existem na dollar bar persistida (`src/data/bars.py:125-179`); `_input_obs` (`m4_regime_comparison.py:374-395`) só usa `close` — decisão de desenho documentada (isolar teste de ortogonalidade), não descuido. `D06f_taker_imbalance_z_48` já é feature **T1 em produção** e não é usada em regime nenhum. VWAP diff/tick-count já existem como candidatas T2 nunca testadas por poder preditivo. Literatura de VPIN/toxicidade de fluxo é **contestada** (Andersen & Bondarenko 2014 vs. autores originais) — não é upgrade automático | auditoria 2 FALHA4 |
| G7 | Hierarquia multi-resolução tem apoio real na literatura recente (2025-2026) | "Adaptive Hierarchical HMM for Structural Market Change" (JRFM 2025) e framework triplo-timeframe explícito (arXiv 2606.06190) sustentam a proposta mais agressiva da auditoria 2 (R3 condicionando R1/R2), não só a versão diagnóstica da auditoria 1. Fronteira ativa (nada consolidado/muito citado ainda) — Estudo 2 com base real, não capricho de auditor | auditoria 1 pt2 vs auditoria 2 FALHA3 |

---

## 3. Lista final categorizada

### REDESENHO (muda arquitetura/lógica existente — Estudo 2, não agora)

| Item | Origem | Por quê |
|---|---|---|
| Hierarquia real R3→R1/R2 (regime lento como feature condicionante do modelo rápido) | auditoria 2 FALHA3 | Literatura dá suporte, mas exige reordenar computação entre resoluções e criar dependência nova |
| Features de microestrutura nativas (VWAP-por-barra persistido, tick-imbalance bars, D11f/D13f trade-level) | auditoria 2 FALHA4 | Engenharia de dado nova (trade-a-trade sobre bilhões de linhas), já adiada antes por custo |
| Multi-resolution R1/R2/R3 como estudo formal pré-registrado | V2 P11 | Sequenciamento já acordado |

### FIX MECÂNICO (extensão limitada, reusa infraestrutura já existente)

| Item | Origem |
|---|---|
| Separação de retorno futuro em múltiplos horizontes (h=5/h=20, hoje só h=1) | auditoria 2 FALHA2 (gap real) |
| Separação de volatilidade futura (só retorno é testado hoje) | achado direto — fecha circularidade da auditoria 1 pt3 |
| Teste "BTC conditional response" | auditoria 1 pt7 |
| Estatística observada agregada por episódio, não só por trade | auditoria 1 pt8 |
| `effective_number_of_states`/occupancy por estado | auditoria 1 pt6 |
| Transition failure rate (N=3/5/10) | auditoria 1 pt11 |
| Detection delay vs. eventos econômicos independentes | auditoria 1 pt12 |
| Coerência cross-resolution + matriz lead/lag (versão diagnóstica) | auditoria 1 pt2/10 |
| Recalibração de `hazard_lambda` restrita a dado pré-janela-de-teste + sensibilidade | V2 P5(i)/(ii), reforçado pela literatura |
| Experimento de transferibilidade de λ do Jump Model | auditoria 1 pt5 |
| Renomear "fit único" → "online update" na árvore/docs | auditoria 1 pt4 (validado) |
| Aggregação: median+IQR+%ativos positivos/significativos | auditoria 1 pt14/15 |
| p-valor ajustado por múltiplos testes (FDR/BH) + contagem de decisões testadas | auditoria 1 pt16 |
| Tabela mestre com `information_cutoff_timestamp` por linha | auditoria 1 pt21 |
| Decisão em 3 estados (VALIDATED/CONDITIONALLY USEFUL/NO EVIDENCE) | V2 P12 |

### HABILITAÇÃO (mecanismo já existe e já é correto — só falta rodar, expor na decisão, ou aplicar padrão já usado em outro lugar)

| Item | Origem |
|---|---|
| Excluir Jump Model do Estudo 1 (reusa o padrão AG-019 já existente) | V2 N3 |
| Wiring experimental de D06f (já T1)/D08f/D09f (já T2) na matriz de observação do regime, medindo IC antes de promover | auditoria 2 FALHA4 (parcial) |
| Congelar metodologia + locked holdout (infra de walk-forward já existe; falta a decisão) | auditoria 1 pt17/18, V2 P3 |
| Reconciliar N_lifetime com estimativa conservadora | V2 N2 |

### REJEITADO

| Item | Origem | Motivo |
|---|---|---|
| BOCPD deve reiniciar do zero a cada fold | auditoria 2 FALHA1 | Refutado matematicamente (Eq. 3 Adams & MacKay) + reintroduziria patologia já corrigida |
| Trocar block permutation por episódio para block bootstrap | auditoria 1 pt9 | Literatura confirma que permutação por bloco já é o método certo para essa hipótese |
| BIC dinâmico por fold para o Jump Model, como proposta primária | auditoria 2 FALHA5 | Sem precedente direto; BIC perdeu para FTIC no mesmo framework quando testado formalmente |
| "Colapso em 1 estado = modelo sendo honesto", sem investigar mais | auditoria 2 FALHA5 | Precondição (recalibração local) não satisfeita hoje |
| Kruskal-Wallis como substituto do Welch's F já em uso | auditoria 2 FALHA2 | Welch já é a escolha certa para a mesma heterocedasticidade; o teste em si já existe |

---

## 4. Encaminhamento (sequenciamento recomendado — 2026-08-19)

1. **Fase 1** — experimento de transferibilidade de λ do Jump Model + exclusão do candidato do Estudo 1; recalibração de `hazard_lambda` restrita a pré-teste + sensibilidade; reconciliação de `N_lifetime`.
2. **Fase 2** — bateria de fix mecânico (separação multi-horizonte + volatilidade, BTC conditional response, estatística por episódio, occupancy/transition-failure/detection-delay, coerência cross-resolution diagnóstica, camada de relatório).
3. **Fase 3** — congelar metodologia por inteiro, rodar holdout travado uma única vez, veredito final nos 3 estados.
4. **Estudo 2** (backlog, não bloqueia o veredito do Estudo 1) — hierarquia real R3→R1/R2, microestrutura nativa, Jump Model reimplementado online.

Esse sequenciamento está sendo revisitado em 2026-08-19 à luz de uma pergunta anterior — definir o **contrato downstream do regime** (horizonte econômico, consumidores, grade canônica, critérios de avaliação) antes de decidir entre HMM/BOCPD/Jump Model — ver documento complementar (validação de `PLANO_MESTRE_PRINCE2.md` contra o código, mesma data).

---

## 5. Fontes de literatura consultadas

**BOCPD / Adams & MacKay:**
[arXiv:0710.3742](https://arxiv.org/abs/0710.3742) · [PDF](https://arxiv.org/pdf/0710.3742) · [Turner, Saatçi & Rasmussen 2009](https://mlg.eng.cam.ac.uk/pub/pdf/TurSaaRas09.pdf) · [Särkkä, Bayesian Filtering and Smoothing](https://www.cambridge.org/core/books/bayesian-filtering-and-smoothing/C372FB31C5D9A100F8476C1B23721A67) · [BOCPD for Financial Time Series (ACM)](https://dl.acm.org/doi/10.1145/3795154.3795291) · [ocp CRAN package doc](https://cran.r-project.org/web/packages/ocp/ocp.pdf)

**Jump Model / λ:**
[Downside Risk Reduction (arXiv:2402.05272)](https://arxiv.org/html/2402.05272v2) · [Dynamic Asset Allocation with Asset-Specific Regime Forecasts (arXiv:2406.09578)](https://arxiv.org/pdf/2406.09578) · [Dynamic Factor Allocation (arXiv:2410.14841)](https://arxiv.org/pdf/2410.14841) · [Extending the SJM for regime identification](https://link.springer.com/article/10.1007/s10479-024-06035-z) · [Generalized Information Criteria for Sparse SJM](https://link.springer.com/article/10.1007/s10182-026-00554-9) · [What drives crypto returns? SJM approach](https://link.springer.com/article/10.1007/s42521-023-00085-x) · [GIC SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4774429) · [What Drives Crypto Returns SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4330421) · [Nystrup/Lindström/Madsen — Learning HMM with persistent states](https://orbit.dtu.dk/en/publications/learning-hidden-markov-models-with-persistent-states-by-penalizin) · [GitHub jump-models](https://github.com/Yizhan-Oliver-Shu/jump-models) · [example.py](https://github.com/Yizhan-Oliver-Shu/jump-models/blob/master/examples/nasdaq/example.py) · [PyPI jumpmodels](https://pypi.org/project/jumpmodels/) · [Feature selection in jump models](https://www.sciencedirect.com/science/article/pii/S0957417421009647) · [Imperial College thesis — Regularised Jump Models](https://www.imperial.ac.uk/media/imperial-college/faculty-of-natural-sciences/department-of-mathematics/math-finance/239237545---Edward-Selig---SELIG_EDWARD_02442425.pdf) · [Changepoint Detection As Model Selection (arXiv:2601.22481)](https://arxiv.org/abs/2601.22481)

**Block permutation / bootstrap / multi-resolução / DSR:**
[Multi-level block permutation (PMC4644991)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4644991/) · [Faster permutation inference in brain imaging (PMC5035139)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5035139/) · [Monte Carlo Permutation Tests for Strategy Significance](https://www.susanpotter.net/quant/monte-carlo-permutation-tests-strategy-significance/) · [Randomization/Permutation/Bootstrap: What's the Difference?](https://vsni.co.uk/randomization-permutation-and-bootstrap-tests-whats-the-difference/) · [bootRanges (PMC10159650)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10159650/) · [Politis — impact of bootstrap methods](https://mathweb.ucsd.edu/~politis/impactBOOT.pdf) · [Multi-Scale Markov-Switching GARCH (arXiv 2606.06190)](https://arxiv.org/html/2606.06190v1) · [Adaptive Hierarchical HMM (JRFM 2025)](https://www.mdpi.com/1911-8074/19/1/15) · [Detecting bearish/bullish markets with hierarchical HMM (arXiv 2007.14874)](https://arxiv.org/abs/2007.14874) · [Investor behavior and multiscale cross-correlations (arXiv 2408.17200)](https://arxiv.org/html/2408.17200v1) · [Volatility regime detection — signal agreement](https://volatilitybox.com/research/volatility-regime-detection/) · [Bailey & López de Prado — DSR](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) · [Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) · [Harvey & Liu — Backtesting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2345489) · [White's RC / Hansen's SPA re-exam](https://www.researchgate.net/publication/256066609_Re-Examining_the_Profitability_of_Technical_Analysis_with_White's_Reality_Check_and_Hansen's_SPA_Test) · [quantstrat SharpeRatio.deflated docs](https://rdrr.io/github/braverock/quantstrat/man/SharpeRatio.deflated.html) · [Deflated Sharpe Ratio — Balaena Quant Insights](https://medium.com/balaena-quant-insights/deflated-sharpe-ratio-dsr-33412c7dd464)

**Microestrutura de dollar bars:**
[Information-driven bars for financial ML](https://medium.com/data-science/information-driven-bars-for-financial-machine-learning-imbalance-bars-dda9233058f0) · [Advances in Financial ML — Reasonable Deviations notes](https://reasonabledeviations.com/notes/adv_fin_ml/) · [Alternative Bars in Alpaca](https://alpaca.markets/learn/alternative-bars-01) · [Order-Flow Imbalance (Emergent Mind)](https://www.emergentmind.com/topics/order-flow-imbalance-ofi-7dff1686-44cf-4cf4-a602-b24df2b7c56e) · [Cross-impact of OFI in equity markets](https://www.tandfonline.com/doi/full/10.1080/14697688.2023.2236159) · [Explainable Patterns in Crypto Microstructure](https://arxiv.org/html/2602.00776v1) · [VPIN and the flash crash — Andersen & Bondarenko](https://www.sciencedirect.com/science/article/abs/pii/S1386418113000189) · [VPIN and the Flash Crash — SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1881731) · [VPIN and Information Asymmetry study](https://www.researchgate.net/publication/334320585_A_Study_on_Volume-Synchronized_Probability_of_Informed_Trading_VPIN_and_Information_Asymmetry) · [VPIN original paper](https://www.quantresearch.org/VPIN.pdf)
