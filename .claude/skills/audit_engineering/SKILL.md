---
name: audit_engineering
description: |
  Use quando pedirem auditoria de engenharia de um arquivo, pacote ou do
  repo inteiro do BTCUSDT Quant Engine. Triggers: "audita esse arquivo",
  "audita src/X", "varredura de engenharia", "tem falha nisso?", "esse
  módulo está seguindo as regras do CLAUDE.md?", "acha os bugs classe
  <divisão sem guarda / diagnóstico descartado / número sem unidade>
  em Y", ou qualquer pedido de revisão crítica de código Python de
  produção (`src/`), configuração (`config/constants.yaml`), ou saída de
  pipeline (parquet/JSON em `experiments/`, `models/`, `data/`).

  Aplica lente quádrupla obrigatória (FS estatística + FI implementação +
  FT tecnológica + FCN contrato negativo) — mais uma 5ª lente CONDICIONAL,
  FE (Falha de Especificação Econômica: hiperparâmetro de feature/label
  derivado de convenção de mercado tradicional em vez de cripto M15/M30/
  H1, dispara só em 3 eventos de transição de escopo, não em toda
  auditoria) — com pesquisa web crítica antes de afirmar qualquer coisa
  sobre biblioteca/método, severidade classificada (CRITICAL/HIGH/MEDIUM/
  LOW), prioridade P0-P3, cross-check obrigatório contra os 32 banned
  patterns do CLAUDE.md + as 7 classes de bug já confirmadas nesta
  investigação (ver Contexto), e roda os scripts mecânicos
  (`check_constants_referenced.py`, `check_unguarded_ratios.py`,
  `check_constants_provenance.py`) como parte do processo, não como
  substituto dele.

  Pra varredura de mais de 1-2 arquivos, usa `Workflow` internamente
  (particiona por pacote canônico, um agente auditor por pacote em
  paralelo) — ver "Modo varredura" abaixo.

  NÃO use pra estilo cosmético (ruff/mypy já fazem). NÃO use pra "só uma
  olhada rápida" — a lente quádrupla é completa ou não roda.
load_policy:
  always:
    - CLAUDE.md
    - audit/division_guard_audit.md
    - docs/audit_discarded_diagnostics.md
  on_demand:
    - PRD_V3_2_UNIFICADO.md
    - docs/SPRINT_LOG.md
---

# audit_engineering — Auditoria de engenharia de software para ML, BTCUSDT Quant Engine

## Contexto e proveniência

Esta skill nasceu de um achado concreto, não de teoria: uma investigação encontrou 6
classes de bug no motor (Sprint 8/Alpha), **e uma delas reapareceu, de forma
independente, no Risk Engine (`src/risk/limits.py`, Sprint 12)** — prova de que a
classe de bug não é específica de onde a atenção passou a estar, é sistêmica. As
~6.900 linhas de `data/`, `labels/`, `exchange/`, `execution/`, `risk/sizing.py` e
`monitoring/` nunca passaram por esse checklist. Esta skill existe pra cobrir isso,
de forma repetível, não ad hoc.

**As 6 classes já confirmadas neste repo** (cada achado tem commit real, não é
hipotético):

| # | Classe | Instância real | Lente |
|---|---|---|---|
| 1 | Divisão com denominador variável sem guarda de sinal | `carry_share = pnl_carry/pnl_total` (`decomposition.py`); `control_10_risco_real` aprovava automaticamente com `equity` negativo (`risk/limits.py`) | FCN |
| 2 | Diagnóstico computado e descartado, nunca persistido | `gain_by_column`/`concentration` recalculado a cada run de `alpha.py`, nunca salvo — recuperar custou um retreino | FI |
| 3 | Número derivado sem unidade/proveniência | `-17,71` circulou numa análise sem se saber se era Sharpe, bps ou fração somada | FCN |
| 4 | Zero medido vs nunca medido conflados | R0 (0,81% da história) tinha zero trades — era warmup, não `tau`, mas não havia distinção explícita até ser investigado | FCN |
| 5 | Constante referenciada sem entrada em `constants.yaml` NO ÍNDICE do git | ~280 linhas de proveniência (Sprints 8/12) fora de commit por sessões inteiras | mecanizado (`check_constants_referenced.py`) |
| 6 | Hierarquia de camada violada | (nenhuma violação real encontrada até agora — os contratos existentes já protegem) | mecanizado (`import-linter`) |
| 7 | Parâmetro carrega escopo implícito (TF/ativo) nunca declarado nem testado | AG-004 (CPCV embargo 15m hardcoded) → AG-005 (TF hardcoded 3x em labels) → AG-017 (M2 `BASELINE_TF`) → AG-027 (8 janelas de feature em contagem de barra, Feature Engine hardcoded em 15m) — 4 ocorrências confirmadas, mesmo padrão | FE (nova, 2026-08-15) |

Esta skill audita as classes 1-4 (não totalmente mecanizáveis — exigem julgamento
de domínio) e cross-referencia as classes 5-6 (já rodam sozinhas em CI, não
precisam de um agente relendo código).

**Pesquisa que fundamenta o desenho desta skill** (não é lente inventada, é
metodologia estabelecida adaptada a este repo — ver Sources no fim do arquivo):
"Hidden Technical Debt in Machine Learning Systems" (Sculley et al., NeurIPS 2015)
pra taxonomia de dívida técnica específica de ML; "The ML Test Score" (Breck et
al., Google, IEEE Big Data 2017) pra estrutura de rubrica Data/Model/Infra/
Monitoring por trás das 4 lentes; "Look-Ahead-Freedom as Temporal
Non-Interference" (2026) pra formalizar vazamento temporal como propriedade
verificável — a pergunta "output[t] depende de informação só disponível depois de
t?" (lente FS) vem direto dali, não é intuição.

## Workflow obrigatório (não pular passo)

### Passo 1 — Tipo de arquivo e escopo

- **Código de pipeline** (`.py` em `src/`) → 4 lentes completas
- **Testes** (`.py` em `tests/`) → FI + FCN (FS/FT geralmente não se aplicam, a
  menos que o teste em si implemente lógica estatística)
- **`tools/lint/*.py`** → FI + FCN (é código de produção da malha de CI, não
  cosmético)
- **`config/constants.yaml`** → não reaudite manualmente proveniência de entrada
  já existente — isso é `check_constants_provenance.py`. Audite só entradas NOVAS
  não cobertas ainda, e a pergunta "toda constante classe A tem
  `sweep_required: true`?"
- **`PRD_V3_2_UNIFICADO.md` / `CLAUDE.md` / `docs/*.md`** → consistência interna
  (referência cruzada §X.Y aponta pra seção real?), completude, números citados
  batem com o repo real (não confie em prosa — confira contra código/dado)
- **Saída de pipeline** (`experiments/*.json`, `models/*/diagnostics/*.json`,
  `data/quality_reports/*.json`) → schema, unidade dos campos, `generated_at`/
  hash de origem presente

Se o pedido não especificar, pergunte: auditoria isolada, ou em contexto (precisa
ler módulos relacionados)? Auditar `src/models/alpha.py` sem ler
`src/models/dataset.py`/`monotonic.py` perde a maior parte das falhas de FS.

**Lente FE (Falha de Especificação Econômica, ver Passo 3) é condicional, não
por tipo de arquivo** — não pertence a esta tabela porque não depende de QUAL
arquivo é, depende de QUANDO um dos 3 gatilhos de escopo dispara (Passo 3, FE).
Mesmo assim, arquivos em `src/features/`, `src/regime/`, `src/labels/` e
`config/constants.yaml::feature_*`/`regime_*` são o universo típico onde ela
se aplica quando disparada.

### Passo 2 — Pesquisa web crítica (obrigatória, não pule)

Antes de afirmar qualquer coisa sobre uma biblioteca ou método, busque:

- **CVEs / issues conhecidos** das libs que o arquivo importa, na versão pinada
  em `pyproject.toml` (`polars`, `duckdb`, `pyarrow`, `xgboost`, `scikit-learn`,
  `optuna`, `structlog`, `orjson`, `pydantic`, `requests`) — GitHub issues
  recentes (2025-2026), não só a documentação.
- **Best practices atualizadas** pro tipo de operação (ex.: o arquivo faz
  purged k-fold? busque se a formulação bate com a literatura mais recente de
  CPCV/purged CV, não só com o que o PRD já assume).
- **Se o arquivo implementa um método com nome próprio** (CPCV, triple-barrier
  labeling, calibração isotônica, participation ratio de autovalores pra
  concentração efetiva, GTX/post-only) — busque críticas ou refinamentos
  recentes da técnica.

Mínimo 2-3 queries. Documente no relatório mesmo se nada relevante for
encontrado — é registro forense, não decoração.

### Passo 3 — Lente quádrupla (sequencial, completa)

#### Lente FS — Falhas Estatísticas

- **Vazamento temporal?** `output[t]` depende de dado com timestamp `> t`,
  direto ou via `join`/`merge_asof`/janela rolante mal configurada? (B01-B06 do
  CLAUDE.md). Pergunta formal (framing de temporal non-interference): truncar
  o futuro da série muda `output[t]`? Se sim, há vazamento.
- **Vazamento estrutural?** Meta usa predição do Alpha sem `is_oof`?
  Calibrador ajustado sobre o próprio OOF em vez de sub-split interno? Split de
  CV sem purge por `t1`? Treino sem `sample_weight` de unicidade? (B07-B10)
- **Threshold escolhido por métrica OOS** em vez de a priori pelo orçamento de
  fees? (B20)
- **Concentração/importância suspeita?** Uma feature/fator dominando —
  heurística geral de leakage é >50% de importância isolada; neste repo os
  limiares formais são HHI nominal <0,25, HHI efetivo (corrigido por
  correlação, achado da Fase D), maior share <0,30 (§5.8). AUC/acurácia
  suspeitosamente alta (>0,90), ou treino≈teste igualmente bons, é o sinal
  clássico inverso — sempre confira os dois extremos, não só concentração alta.
- **Multiple testing controlado?** Toda otimização/busca de hiperparâmetro
  incrementa `audit/n_lifetime.yaml`? Restrição forçada por identidade
  contábil (ex. `E27f_cost_atr_ratio`, `E02f_funding_z` — Fase T0) é
  explicitamente ISENTA disso — confirme que a isenção está documentada, não
  assumida.
- **Regime/HMM ajustado na série toda e "predito" retroativamente?** (B05)
- **Constante classe A sem sweep de sensibilidade** antes do Gate 3? (§16.10)

Cross-check obrigatório: CLAUDE.md banned patterns B01-B10, B18-B25; PRD Gate 3
(`§16.1`); `audit/n_lifetime.yaml`.

#### Lente FI — Falhas de Implementação

- **Paridade batch↔streaming quebrada?** Tolerância `< 1e-8` (padrão do Sprint
  4, DoD de "código de feature" no CLAUDE.md).
- **Escrita não-atômica?** `open(arquivo, "w")` direto em vez de
  `.tmp`→`fsync`→`rename` (B29).
- **Determinismo assumido, nunca testado?** Mesma seed deveria dar mesmo
  resultado bit-a-bit — existe um teste golden-file (padrão da Fase G) ou é só
  suposição?
- **Edge cases não tratados?** `NaN`, `Inf`, DataFrame vazio, linha única,
  warmup insuficiente, denominador zero (ver também FCN abaixo — a mesma
  pergunta, duas lentes, propositalmente).
- **Off-by-one em janela rolante / limite de warmup?**
- **Invariante causal — prefix-invariance E alinhamento decisão-execução**
  (checagem dupla, a segunda é a mais fácil de perder): (a) a função em si só
  usa dado `≤ t`? (b) SE o arquivo é um orquestrador que colhe um valor
  (sinal/feature/regime) num índice de EXECUÇÃO a partir de uma série
  computada num índice de DECISÃO — o valor usado é o da barra ANTERIOR à
  execução, nunca o da própria barra? Um único índice reusado pros dois papéis
  é o padrão de risco. Pergunta obrigatória em qualquer arquivo de
  `src/labels/`, `src/regime/`, `src/execution/`, e em qualquer runner que
  orquestre essas camadas — é a classe de bug mais cara já vista num projeto
  irmão (inflou win rate de 36%→83%, invisível ao purged k-fold porque o leak
  era idêntico em fold IS e OOS).
- **`config_hash` do label idêntico ao da execução?** (B15)
- **`sample_weight` de unicidade sempre aplicado, não opcional?**
- **TF hardcoded num módulo que deveria ser multi-timeframe?** (AG-017,
  2026-08-15 — `src/analysis/m2_bar_comparison.py` escrito com
  `BASELINE_TF = "15m"` fixo, apesar de `TIMEFRAMES = ("15m", "30m", "1h")`
  já existir em `src.analysis.volatility_comparison` e já ser consumido
  corretamente por `m3_timeframe_choice.py` — e apesar de
  `PLANO_MESTRE_PRINCE2.md` §15.6 item 1 já ter previsto esse risco por
  nome, antes do módulo existir. Pergunta obrigatória em todo módulo NOVO
  de `src/analysis/`, `src/features/`, `src/labels/`, `src/regime/`,
  `src/validation/`: itera `TIMEFRAMES` (import de
  `src.analysis.volatility_comparison`, ou `_TF_TO_MINUTES`/`step_ms` de
  `src.data.resample` pra conversão de unidade), ou hardcoda um TF único?
  Se hardcoda, há uma constante/comentário explicando POR QUE esse módulo
  é exceção (ex. `TIME_STOP_REFERENCE_TF` em `m2_bar_comparison.py` —
  intencional, não um TF de comparação, ver docstring do módulo), ou é só
  a mesma lacuna se repetindo? PRD_V4_1.md §0.4 ("Três timeframes... —
  obrigatórios ponta a ponta") é a referência pra julgar se TF único é
  aceitável nesse módulo específico.

Cross-check obrigatório: CLAUDE.md B11, B15, B29; DoD "código de feature"/"código
de modelo"/"código de execução" do CLAUDE.md; `PRD_V4_1.md` §0.4 (escopo
multi-TF); `audit/architecture_gaps_log.yaml` AG-017.

#### Lente FT — Falhas Tecnológicas

- **Stack banido?** `hmmlearn` (B21), Pandas no core (B26), `pip`/`venv`/
  `conda` (B27), `print()` (B28).
- **`working_type: CONTRACT_PRICE`** em vez de `MARK_PRICE` em stop? (B12)
- **Ordem convertida pra mercado no timeout** em vez de `CANCEL`? (B13)
- **CVE/issue conhecido** nas libs pinadas — ver Passo 2, não pule esta lente
  sem ter feito a pesquisa.
- **System smells de Sculley et al.**: glue code acumulando entre camadas?
  Pipeline jungle (fluxo de dado confuso demais pra seguir sem desenhar)?
  Caminho de código experimental morto, nunca removido? "Plain-old-datatype
  smell" — um `float`/`dict` cru circulando onde o módulo já adotou `Metric`
  (`src.core.metric`) pra isso, ou seja, alguém contornou a proteção?
- **Logging fora do padrão?** `structlog`+`orjson` sempre, nunca stdlib puro.

Cross-check obrigatório: CLAUDE.md B12, B13, B21, B26-B28; `pyproject.toml`
(`[tool.mypy.overrides]` pra saber quais libs já são conhecidas como carentes
de stubs, não reportar isso como achado novo).

#### Lente FCN — Falhas de Contrato Negativo

Cobre comportamento em failure mode (negative path) — a lente mais nova pro
repo, mas o repo já tem disciplina parcial pra ela (sentinela `NOT_COMPUTABLE`
em Regime/Risk, `Metric.valid`/`not_computable()` em `src.core.metric`).

- **Divisão com denominador variável sem guarda de sinal?** Rode
  `python tools/lint/check_unguarded_ratios.py --path <arquivo ou pacote>`
  como parte OBRIGATÓRIA desta lente, não substitua por leitura manual — mas
  toda saída UNGUARDED do script exige julgamento humano/agente antes de virar
  finding (o script erra tanto pra mais quanto pra menos, ver a docstring
  dele). Pergunta de domínio pra cada achado real: o denominador pode ser
  `<=0`/`NaN`/`Inf` numa condição de mercado ou dado real, não só
  teoricamente?
- **Zero medido vs nunca medido conflados?** Uma tabela agregada (regime,
  gatilho de stress, controle de risco) reporta "0" onde deveria reportar
  "não computável"? Sentinela explícito existe, ou é `False`/`0.0` silencioso?
- **Diagnóstico calculado e descartado?** Uma função computa algo internamente
  (score, distribuição, contagem) que nunca sai da memória — se uma
  investigação futura precisar disso, o custo é retreinar/reprocessar do
  zero?
- **Número derivado sem `Metric`** num módulo que já foi convertido
  (`src/models/decomposition.py`, `src/backtest/*`, `src/models/hhi.py`) —
  ou, em módulo AINDA não convertido, um número que sai de uma função pública
  sem unidade/tamanho de amostra/origem documentados em algum lugar (docstring
  no mínimo, `Metric` no ideal)?
- **Falha silenciosa?** `except:` nu, `except Exception: pass`, log sem
  `raise` onde a invariante quebrada deveria parar o pipeline.
- **Escrita atômica em TODO caminho, incluindo o de exceção?** Um `finally`
  ausente que deixa um `.tmp` órfão não é atomicidade completa.
- **Recursos não liberados?** Arquivo/conexão/lock não fechado em todo path
  (incluindo o de exceção).

Cross-check obrigatório: `audit/division_guard_audit.md` (achados já
catalogados — não reaudite os 5 arquivos já cobertos do zero, CONFIRA se a
situação mudou); `docs/audit_discarded_diagnostics.md`; `src/core/metric.py`
(padrão de referência).

#### Lente FE — Falha de Especificação Econômica (condicional, não roda em toda auditoria)

**Diferente de FS/FI/FT/FCN, a lente FE NÃO é obrigatória em toda auditoria de
`src/`** — é cara demais (exige julgamento de domínio quant, não só leitura de
código) pra rodar em arquivo que não parametriza sinal/feature/label. Dispara
SÓ nestes 3 eventos de transição de escopo (achado 2026-08-15, Manager, ver
`PLANO_MESTRE_PRINCE2.md` §6.1/AG-027):

| gatilho | o que dispara | por quê este ponto |
|---|---|---|
| Feature Engine ganha o 1º TF além de 15m (`build_t1_features`/`_sources.load_bars_15m` deixa de ser hardcoded) | mudança de escopo TEMPORAL | decisão bar-count×clock-time precisa existir ANTES do 1º commit multi-TF, não depois (mesmo erro de AG-004/005/017 se repetir pela 5ª vez) |
| Constante `class: B, provenance: ASSUMED` entra no vetor de treino de um modelo promovido além de research (Gate 3/4) | mudança de escopo de USO (pesquisa → produção) | `check_constants_provenance.py` já lista essas constantes com `review_by` (AG-028) — rode-o antes de aprovar a promoção |
| Antes de `12_RISK_ENGINE`/`13_EXECUCAO` ganharem o 1º caller real | mudança de escopo (research → capital real) | toda constante ainda `ASSUMED` nesse ponto vira bloqueio de Gate, não nota de rodapé |

**Regra de segurança orçamentária (v1.5, achado 2026-08-15 — Manager, "a
auditoria está correta, mas executá-la ingenuamente dispara o critério de
encerramento #5"):** as 10 perguntas abaixo são, por desenho, **0 trials** —
leem `constants.yaml`, código-fonte já escrito, e artefato já persistido
(`labels.parquet`, `experiments/*.json`). Nenhuma resposta a elas autoriza,
sozinha, abrir um sweep/Optuna/retreino pra "corrigir" o parâmetro
encontrado. `audit/n_lifetime.yaml::counter` tem teto declarado em
`PRD_V4_1.md` (critério de encerramento 5: `N_lifetime > 60 sem Camada 2
fechada → encerrar`); interpretar "N janelas ASSUMED encontradas" como "varra
as N" pode consumir o orçamento restante inteiro numa única sessão e disparar
o encerramento do projeto sem nenhuma decisão do Manager ter sido tomada
sobre isso. Sequência obrigatória, sempre nesta ordem:
1. Responda as 10 perguntas (0 trials).
2. Se a resposta sugerir viés/erro, meça DESCRITIVAMENTE onde possível, sem
   sweep — contagem direta em dado já existente (achado-modelo: `AG-027`
   Q2, `round_trip_cost_bps` corrigido por contagem em `labels.parquet`
   já gravado, não por experimento novo).
3. Registre o achado em `architecture_gaps_log.yaml` com a magnitude medida.
4. Só se (2) mostrar diferença material E a correção exigir otimização de
   verdade, escale ao Manager pedindo autorização — citando explicitamente
   `N_lifetime` restante na própria pergunta (não deixe o Manager decidir às
   cegas do orçamento). Nunca abra um sweep por conta própria a partir de um
   achado desta lente.

Aplique as 10 perguntas a CADA parâmetro numérico que parametriza uma
feature/indicador/label/regra de regime no escopo do Pacote de Trabalho (não
só a que motivou o gatilho):

1. **Bar-count fixo ou clock-time fixo entre TFs, pra esta janela específica?**
   A decisão está registrada em algum lugar (comentário, `constants.yaml`), ou
   é implícita? (achado-modelo: AG-027, 8 janelas de feature em contagem de
   barra sem essa decisão)
2. **A premissa embutida na fórmula é medível no dado real já existente?**
   (achado-modelo: `round_trip_cost_bps` assumia 50/50 de qual barreira toca
   primeiro — `labels.parquet` já registra qual tocou, contagem direta, sem
   experimento novo — e a aproximação analítica de 1ª ordem, ruína do
   apostador com barreiras assimétricas, já mostrava viés de ~4% antes até de
   medir)
3. **O método/estimador tem premissa estrutural que cripto 24/7 viola
   conceitualmente** (ex. "overnight"/sessão de mercado em Yang-Zhang/
   Rogers-Satchell)? Cite literatura que confirme a incompatibilidade, não só
   o resultado empírico de qual estimador "ganhou" — resultado ruim pode ser
   sintoma de premissa errada, não de janela errada.
4. **A mesma janela/threshold é aplicada uniformemente a todos os N ativos do
   universo?** Alguém MEDIU se a estrutura de autocorrelação difere o
   bastante entre ativos (maturidade/liquidez diferentes) pra justificar
   parametrização por ativo, ou é suposição de conveniência?
5. **Corte de threshold/regime: sobre valor bruto ou sobre posto percentil?**
   Se sobre posto percentil (`expanding_percentile_rank_strict` ou
   equivalente), desequilíbrio populacional NÃO é o risco (percentil
   equilibra por construção) — o risco é INSTABILIDADE DE FRONTEIRA: meça a
   distância real entre os percentis de corte vizinhos (ex. p33/p66) EM
   UNIDADE BRUTA, não em percentil. Sob distribuição enviesada, threshold
   populacionalmente "limpo" pode trocar de rótulo com variação econômica
   desprezível.
6. **Duas features com a mesma janela medem conceitos matematicamente
   distintos, ou uma é redundante da outra?** Verifique a FÓRMULA antes de
   supor redundância (posição vs. trajeto, nível vs. variação são
   frequentemente confundidos) — e meça correlação empírica real (o pipeline
   de HHI/importância do projeto já serve pra isso).
7. **Constante de warmup/lookback em contagem de barras interage desigual com
   ativos de histórico mais curto?** Medido em % de dados descartados POR
   ATIVO, não só globalmente?
8. **Um parâmetro faz DOIS papéis simultâneos** (ex. dimensiona a geometria do
   LABEL e também alimenta uma FEATURE, mesmo ATR)? Isso não é vazamento
   temporal, mas é acoplamento de design — erro de calibração se propaga
   correlacionado pros dois lados, risco de correlação espúria feature↔label
   que parece sinal sem ser.
9. **A justificativa registrada é derivação real ou estética pós-hoc?**
   Frases-alerta pra buscar no próprio `source:` de `constants.yaml`: "janela
   de funding", "número redondo", "convenção de mercado", "soa razoável" —
   sem medição citada por trás.
10. **`review_by` já foi alcançado pelo estado atual do projeto?** Rode
    `python tools/lint/check_constants_provenance.py` (agora lista toda
    constante `class: B` `ASSUMED` com seu `review_by`, achado AG-028) — se o
    sprint já passou, a revisão foi feita de verdade ou só passou
    despercebido?

Cross-check obrigatório: `config/constants.yaml` (toda entrada citada tem
`provenance`/`source` que resiste às 10 perguntas acima, não só existe);
`audit/architecture_gaps_log.yaml` AG-004/AG-005/AG-017/AG-027 (mesma classe
de defeito, não trate achado novo como isolado se bater no padrão);
`tools/lint/check_constants_provenance.py` (rodar, ver Passo 4).

### Passo 4 — Scripts mecânicos (Claude roda direto — exceção nomeada, CLAUDE.md v1.5)

**Histórico da correção:** esta seção, escrita em 2026-08-09, instruía
"rodar" os scripts abaixo diretamente. `CLAUDE.md` v1.2 (2026-08-10)
proibiu Claude de executar qualquer `.py`/`uv run`/`pytest`, sem exceção —
esta skill não tinha sido atualizada pra refletir isso (achado AG-002,
`audit/architecture_gaps_log.yaml`), e por um dia (2026-08-12, entre a
correção de AG-002 e esta reversão) o Passo 4 exigiu comando copy-paste
por causa disso. **`CLAUDE.md` v1.5 (2026-08-12) abriu uma exceção nomeada
exatamente para estes 5 scripts** (autorização explícita do Manager: sem
rodar, a skill não audita de verdade) — Claude volta a rodar direto, mas
SÓ estes 7 comandos, nenhum outro `.py`/`uv run` fora desta lista.

Pra qualquer arquivo/pacote em `src/`, rodar via Bash/PowerShell:

```bash
python tools/lint/banned_patterns.py --path <alvo> --strict
python tools/lint/check_constants_referenced.py --src <alvo>
python tools/lint/check_unguarded_ratios.py --path <alvo>
uv run ruff check <alvo>
uv run mypy <alvo>
```

Achados automatizados entram no relatório como evidência, não como
substituto do julgamento das 4 lentes — um script limpo não significa
arquivo aprovado (`banned_patterns.py` mesmo documenta isso: metade dos 32
padrões não é automatizável). Se algum destes comandos falhar de um jeito
que sugira efeito colateral fora do esperado (leitura pura), parar e
reportar — não presumir que a exceção cobre o que aconteceu.

### Passo 5 — Classificação de severidade

**CRITICAL (P0)** — bloqueia. Não pode ser commitado/usado assim.
- Vazamento temporal ou estrutural confirmado
- Banned pattern violado (qualquer um dos 32)
- Controle de risco que aprovaria incorretamente em produção (classe
  `control_10` — FCN, divisão sem guarda em caminho de decisão de risco real)
- Assinatura de request sem percent-encode (B32) — erro -1022 em produção real
- TP postado antes do SL confirmado (B14)

**HIGH (P1)** — corrige antes de promover o módulo.
- Paridade batch↔streaming quebrada
- Escrita não-atômica em I/O persistente
- Determinismo assumido sem teste golden-file
- Diagnóstico com valor de auditoria futura sendo descartado
- Número derivado sem unidade num módulo que já deveria ter migrado pra
  `Metric`

**MEDIUM (P2)** — corrige na próxima iteração, não bloqueia.
- Divisão sem guarda mas denominador provavelmente seguro (precisa de
  `# noqa: unguarded-ratio` com justificativa, não silêncio)
- Falta de teste do caso degenerado
- Stack subótimo mas não banido

**LOW (P3)** — sugestão, backlog.

### Passo 6 — Output formal

Segue o template em `audit_report_template.md` (mesmo diretório desta skill).
Destino sugerido: `audit/code_reviews/{YYYY-MM-DD}_{modulo}_audit.md` — **sempre
pergunte antes de salvar** se não foi pedido explicitamente "arquiva"; rascunho
exploratório pode ficar só na conversa.

## Modo varredura — mais de 1-2 arquivos

Pra "audita `src/data/` inteiro" ou "audita o repo", **não leia tudo você
mesmo em série** — dispare `Workflow`, particionando por pacote canônico
(`exchange/`, `data/`, `features/`, `regime/`, `labels/`, `validation/`,
`risk/`, `execution/`, `models/`, `backtest/`, `analysis/`, `core/`,
`monitoring/`), um agente auditor por pacote em paralelo, cada um aplicando os
Passos 1-5 completos ao seu pacote. Converge num único relatório
(`audit/code_reviews/{data}_sweep_{pacotes}.md`) com um resumo executivo no
topo (total de findings por severidade, por pacote) antes do detalhe.

Ordem de prioridade sugerida pro primeiro sweep (maior raio de explosão
primeiro, ver `docs/SPRINT_LOG.md`): `exchange/` (assina requisição com
dinheiro real) → `data/` (alimenta tudo a jusante) → `labels/` (calcula os
mesmos tipos de bps/custo que já erraram em `models/`) → `execution/` →
`risk/sizing.py` → `monitoring/`.

## Anti-patterns (recusar)

- "Audita rapidinho, só uma olhada" → recusa, lente quádrupla completa ou nada
- "Foca só no óbvio" → recusa
- "Pula a pesquisa web" → recusa, a menos que o pedido justifique
  explicitamente (ex. arquivo sem nenhuma dependência externa nem método
  nomeado)
- "Não precisa de relatório formal" → OK inline, mas as 4 lentes continuam
  completas

## Escalonamento

- **Achado revela padrão sistêmico novo** (uma instância a mais da mesma
  classe já catalogada, ou uma classe nova de todo) → sugerir estender
  `check_unguarded_ratios.py`/criar script mecânico novo em `tools/lint/`, não
  só reportar em prosa
- **Achado revela banned pattern candidato** (algo que devia ser B33+) →
  sugerir adicionar a `CLAUDE.md`, com a mesma âncora §X.Y do PRD
- **Achado revela necessidade de refator estrutural** → NÃO implementar
  durante o audit — reportar e sugerir sessão dedicada
- **Achado é sobre um arquivo que Gate 3/4 já reprovaram por outro motivo**
  (ver `docs/SPRINT_LOG.md`) → cite o gate reprovado, não trate como
  descoberta nova isolada

## Versionamento

```
v1.0 — 2026-08-09 — Criação. Adapta a metodologia de lente quádrupla
                     (FS/FI/FT/FCN) de um projeto irmão às 6 classes de bug
                     confirmadas nesta investigação (Fases A-H, T0-T5, ver
                     docs/SPRINT_LOG.md) + pesquisa de metodologia
                     estabelecida (Sculley et al. 2015, Breck et al. 2017,
                     temporal non-interference 2026). Inclui os dois scripts
                     mecânicos como parte obrigatória do Passo 4.
v1.1 — 2026-08-12 — Corrige Passo 4: instruía "rodar" scripts mecânicos
                     diretamente, o que contradiz CLAUDE.md v1.2
                     (2026-08-10, um dia posterior à criação desta skill) —
                     "Protocolo de execução — quem roda o quê". Passa a
                     entregar comando copy-paste, marca
                     PENDENTE-DE-EXECUÇÃO-HUMANA. Achado AG-002
                     (audit/architecture_gaps_log.yaml), via arquitetura de
                     `project_assurance` (skill nova, revisão independente
                     por Agent fresco per PLANO_MESTRE_PRINCE2.md §6.4).
v1.2 — 2026-08-12 — Reverte parcialmente v1.1: CLAUDE.md v1.5 abre exceção
                     nomeada pros 5 scripts mecânicos do Passo 4 (+ ruff/
                     mypy), autorização explícita do Manager. Passo 4 volta
                     a rodar direto — só estes 7 comandos, nada além.
v1.3 — 2026-08-15 — Adiciona pergunta de TF hardcoded à Lente FI. Achado
                     AG-017: `m2_bar_comparison.py`, escrito DEPOIS desta
                     skill existir, foi implementado com TF único
                     hardcoded apesar de `TIMEFRAMES` já existir num
                     import vizinho e de `PLANO_MESTRE_PRINCE2.md` §15.6
                     item 1 já ter previsto esse risco por nome — a skill
                     não tinha pergunta explícita pra pegar essa classe,
                     só as adjacentes (causalidade, config_hash). Não
                     teria pego sozinha (a auditoria só roda quando
                     pedida, e o módulo nunca foi auditado antes de
                     "pronto") — registra o critério pra quando alguém
                     pedir auditoria de um módulo novo desse tipo.
v1.4 — 2026-08-15 — Adiciona 5ª lente CONDICIONAL, FE (Falha de
                     Especificação Econômica) — hiperparâmetro de feature/
                     indicador/label herdado de convenção de mercado
                     tradicional sem validação pra cripto M15/M30/H1.
                     Achado AG-027 (Manager, lente Feature/Alpha/Signal
                     Researcher, validado por revisão adversarial própria +
                     verificação de código/rederivação matemática): 8
                     janelas de feature ASSUMED/nunca testadas, expressas
                     em contagem de barra enquanto o Feature Engine roda
                     hardcoded em 15m; round_trip_cost_bps assume 50/50 de
                     qual barreira toca primeiro (viés quantificado ~4%,
                     não hipótese); tercil econômico opera sobre posto
                     percentil (desequilíbrio populacional não é risco;
                     instabilidade de fronteira é). 4ª ocorrência confirmada
                     da mesma classe de defeito de AG-004/AG-005/AG-017 —
                     promovida a classe própria (#7) na tabela de Contexto.
                     Diferente de FS/FI/FT/FCN, NÃO roda em toda auditoria —
                     dispara só em 3 eventos de transição de escopo (Feature
                     Engine ganha TF além de 15m; constante classe B
                     ASSUMED entra em modelo promovido; antes do 1º caller
                     real de risk/execution), porque exige julgamento de
                     domínio quant caro demais pra rodar sempre. AG-028
                     (achado irmão, mesma sessão): check_constants_
                     provenance.py nunca lia `review_by` de constantes
                     classe B — corrigido, script agora lista visibilidade
                     (não enforcement) de toda classe B ASSUMED com
                     review_by declarado.
v1.5 — 2026-08-15 — Adiciona "Regra de segurança orçamentária" à lente FE
                     (achado do Manager, "Continuando Ultrathink" ponto 1):
                     a lente é 100% 0-trial por desenho (só lê constants.yaml/
                     código/labels.parquet já existentes), mas nada nela
                     autoriza abrir sweep/Optuna a partir de um achado — só
                     escalar ao Manager, citando N_lifetime restante
                     explicitamente. Risco real, não hipotético: AG-027
                     interpretado ingenuamente como "varra as 8 janelas"
                     gastaria os 15 trials restantes (counter=45, teto=60,
                     PRD_V4_1.md critério de encerramento 5) e poderia
                     disparar o encerramento do projeto sem decisão do
                     Manager. Sequência agora explícita: 10 perguntas →
                     medição descritiva (0 trials) → registro em
                     architecture_gaps_log.yaml → só então, se material,
                     escalar pedindo trial com orçamento visível. AG-030
                     registrado no mesmo achado (features expansivas desde a
                     origem do ativo — C07/D03f/E02f — confundem H0 do M6,
                     decisão necessária antes do M6 rodar).
```

Atualizar quando: novo banned pattern adicionado ao CLAUDE.md, nova classe de
bug confirmada (mesmo padrão desta tabela), novo script mecânico criado em
`tools/lint/`, refinamento após uso real desta skill.

## Sources (pesquisa que fundamenta o desenho, Passo 2 aplicado à própria skill)

- [Hidden Technical Debt in Machine Learning Systems (Sculley et al., NeurIPS 2015)](https://papers.neurips.cc/paper/5656-hidden-technical-debt-in-machine-learning-systems.pdf)
- [The ML Test Score: A Rubric for ML Production Readiness and Technical Debt Reduction (Breck et al., Google, IEEE Big Data 2017)](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/aad9f93b86b7addfea4c419b9100c6cdd26cacea.pdf)
- [Code Smells in Machine Learning Systems (arXiv 2203.00803)](https://arxiv.org/pdf/2203.00803)
- [Look-Ahead-Freedom as Temporal Non-Interference: A Verifiable Correctness Property for Backtesting and Agentic Trading Pipelines (arXiv 2607.04958)](https://arxiv.org/pdf/2607.04958)
