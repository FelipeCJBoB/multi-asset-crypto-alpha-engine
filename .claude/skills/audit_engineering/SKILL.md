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
  FT tecnológica + FCN contrato negativo), com pesquisa web crítica antes
  de afirmar qualquer coisa sobre biblioteca/método, severidade
  classificada (CRITICAL/HIGH/MEDIUM/LOW), prioridade P0-P3, cross-check
  obrigatório contra os 32 banned patterns do CLAUDE.md + as 6 classes de
  bug já confirmadas nesta investigação (ver Contexto), e roda os dois
  scripts mecânicos (`check_constants_referenced.py`,
  `check_unguarded_ratios.py`) como parte do processo, não como
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

Cross-check obrigatório: CLAUDE.md B11, B15, B29; DoD "código de feature"/"código
de modelo"/"código de execução" do CLAUDE.md.

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

### Passo 4 — Scripts mecânicos (entregar comando, nunca rodar — CLAUDE.md "Protocolo de execução")

**Correção 2026-08-12 (AG-002, `audit/architecture_gaps_log.yaml`):** esta
seção, escrita em 2026-08-09, instruía "rodar" os scripts abaixo
diretamente. `CLAUDE.md` v1.2 (2026-08-10) — um dia depois — proibiu Claude
de executar qualquer `.py`/`uv run`/`pytest` via Bash/PowerShell, sem
exceção. Esta skill nunca foi atualizada pra refletir isso; quem a seguisse
ao pé da letra violaria o protocolo vigente. Corrigido agora: **Claude (e
qualquer agente/subagente, inclusive `project_assurance`) entrega o comando
exato pronto pra copiar/colar; só o usuário roda.** Isso vale mesmo dentro
de uma sessão de `Agent`/`Workflow` isolada — a restrição é sobre QUEM
executa Python, não sobre em qual contexto de conversa isso acontece.

Pra qualquer arquivo/pacote em `src/`, entregar ao usuário:

```bash
python tools/lint/banned_patterns.py --path <alvo> --strict
python tools/lint/check_constants_referenced.py --src <alvo>
python tools/lint/check_unguarded_ratios.py --path <alvo>
uv run ruff check <alvo>
uv run mypy <alvo>
```

O relatório da auditoria fica com essas linhas marcadas
**PENDENTE-DE-EXECUÇÃO-HUMANA** até o usuário colar o output de volta — não
se assume "limpo" nem se preenche a tabela do Passo 6 com resultado
inventado. Achados automatizados, quando o output chegar, entram no
relatório como evidência, não como substituto do julgamento das 4 lentes —
um script limpo não significa arquivo aprovado (`banned_patterns.py` mesmo
documenta isso: metade dos 32 padrões não é automatizável).

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
                     "Protocolo de execução — quem roda o quê". Agora entrega
                     comando copy-paste, marca PENDENTE-DE-EXECUÇÃO-HUMANA.
                     Achado AG-002 (audit/architecture_gaps_log.yaml), via
                     arquitetura de `project_assurance` (skill nova, revisão
                     independente por Agent fresco per PLANO_MESTRE_PRINCE2.md
                     §6.4).
```

Atualizar quando: novo banned pattern adicionado ao CLAUDE.md, nova classe de
bug confirmada (mesmo padrão desta tabela), novo script mecânico criado em
`tools/lint/`, refinamento após uso real desta skill.

## Sources (pesquisa que fundamenta o desenho, Passo 2 aplicado à própria skill)

- [Hidden Technical Debt in Machine Learning Systems (Sculley et al., NeurIPS 2015)](https://papers.neurips.cc/paper/5656-hidden-technical-debt-in-machine-learning-systems.pdf)
- [The ML Test Score: A Rubric for ML Production Readiness and Technical Debt Reduction (Breck et al., Google, IEEE Big Data 2017)](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/aad9f93b86b7addfea4c419b9100c6cdd26cacea.pdf)
- [Code Smells in Machine Learning Systems (arXiv 2203.00803)](https://arxiv.org/pdf/2203.00803)
- [Look-Ahead-Freedom as Temporal Non-Interference: A Verifiable Correctness Property for Backtesting and Agentic Trading Pipelines (arXiv 2607.04958)](https://arxiv.org/pdf/2607.04958)
