# CLAUDE.md — Motor Quant Multi-Ativo

> Instruções persistentes para Claude Code neste repo. Só regras e diretrizes —
> nada de estado ou histórico aqui.
> Estado atual do projeto: `docs/SPRINT_LOG.md`. Histórico de mudança (o quê/por
> quê): `git log`. Histórico deste arquivo: `git log -- CLAUDE.md`.
> Documento mestre: `PLANO_MESTRE_PRINCE2.md` (governança + PBS, §11). Blueprint
> técnico: `PRD_V3_2_UNIFICADO.md` (arquitetura) + `PRD_V4_1.md` (escopo
> multi-ativo).
> Toda regra abaixo tem âncora §X.Y do PRD. Regra sem âncora é dívida técnica.

---

## Referência rápida — onde cada coisa mora

| procura por | caminho |
|---|---|
| Estado atual do projeto, sprint a sprint | `docs/SPRINT_LOG.md` |
| Governança, PBS, agenda por stage (Road Map Vivo §11.4) | `PLANO_MESTRE_PRINCE2.md` |
| Blueprint — arquitetura e contratos | `PRD_V3_2_UNIFICADO.md` |
| Blueprint — emenda de escopo multi-ativo | `PRD_V4_1.md` |
| Proveniência/classe de toda constante | `config/constants.yaml` |
| Furos de arquitetura/integração (AG-NNN) | `audit/architecture_gaps_log.yaml` |
| Orçamento de trials (multiple-testing) | `audit/n_lifetime.yaml` |
| Achados estatísticos medidos | `audit/evidence_ledger.yaml` |
| Skills disponíveis | `.claude/skills/` |
| Histórico de execução (o quê/por quê) | `git log` |

## Bootstrap — antes de qualquer decisão grande

1. `docs/SPRINT_LOG.md` — últimas seções, pra saber o estado real.
2. `PLANO_MESTRE_PRINCE2.md` §11.4 (Road Map Vivo) — o que já está agendado
   pra qual stage, antes de tratar algo como urgente.
3. `audit/architecture_gaps_log.yaml` — gaps abertos relevantes à tarefa.
4. `audit/n_lifetime.yaml` — orçamento de trials restante, se a tarefa
   envolver otimização/sweep/retreino.
5. `config/constants.yaml` — se a tarefa tocar em constante nova ou existente.

---

## Projeto

- Motor quant multi-timeframe (M15/M30/H1), multi-par (BTC/ETH/SOL/BNB/XRP),
  bidirecional (long/short), Binance USDⓈ-M, capital R$ 1.000, execução maker
  post-only. Definição completa: `PLANO_MESTRE_PRINCE2.md` §15.
- V1 existe pra construir infraestrutura de hipótese → teste → validação →
  execução → auditoria — não pra provar que BTC é previsível. Motivo:
  `PLANO_MESTRE_PRINCE2.md` §15.
- Capital é restrição estrutural do desenho, nunca parâmetro livre. Lote
  mínimo = 33% do equity. Motivo: `PLANO_MESTRE_PRINCE2.md` §0.

---

## As 5 restrições invioláveis (§0.2)

Código que as viole é rejeitado mesmo passando nos testes.

| # | restrição | valor operacional |
|---|---|---|
| R1 | erro de quantização ≤ `quantization_tolerance` **e** `N_req/unit ≥ 2` | stop ≤ 0,758% |
| R2 | custo round-trip ≤ `cost_stop_ratio_max` × stop | stop ≥ 0,275% |
| R3 | fees mensais ≤ `fee_budget_monthly` × equity | ~55 trades/mês |
| R4 | teto de features = medido, **nunca estipulado** | ver §0.2 R4 |
| R5 | alavancagem **não é** controle de risco; nocional é | `max_notional_multiple` |

Janela viável de stop: [0,275% ; 0,758%]. Teto de preço do BTC: US$ 107.568
(acima disso, Gate 0 contínuo bloqueia, §16.11).

---

## Proveniência (§16.10)

Toda constante em `config/constants.yaml` segue este schema:

```yaml
cost_stop_ratio_max:
  value: 0.20
  provenance: ASSUMED        # MEASURED | DERIVED | LITERATURE | ASSUMED
  source: "sem base; escolhido por conveniência"
  class: A                   # A=invalida desenho | B=hiperparâmetro | C=guardrail | D=cosmético
  sweep_required: true
  sweep_range: [0.10, 0.40]
```

1. Nenhum literal numérico em código de pipeline. Enforcement:
   `tools/lint/banned_patterns.py`.
2. Constante classe A com `provenance: ASSUMED` bloqueia build de produção.
   Enforcement: CI.
3. Guardrails classe C são quantis (`p95(spread, 90d)`), nunca número redondo.
4. Classe A exige sweep de sensibilidade ±50% antes do Gate 3 — critério é
   robustez na vizinhança, não "Sharpe bom no valor escolhido".
5. `N_lifetime` (`audit/n_lifetime.yaml`) incrementa em toda otimização classe
   B, retreino, challenger — nunca decrementa. DSR usa `N_lifetime`, não o `N`
   de uma busca isolada.

Motivo histórico: `PLANO_MESTRE_PRINCE2.md` §16.10, PARTE XVIII do PRD.

---

## Banned patterns

Lint via `tools/lint/banned_patterns.py` em pre-commit. Build quebra se violado.

### Vazamento temporal

| # | proibido | correto | âncora |
|---|---|---|---|
| B01 | filtros de instrumento atuais em dado histórico | `load_filters_asof(t)` | §1.4 |
| B02 | quantil/z-score com índice ≥ `t` | janela expansiva estrita `< t` | §2.0 |
| B03 | scaler ajustado no dataset inteiro | expansivo ou por fold | §11.5 #8 |
| B04 | seleção de feature fora do fold | dentro de cada fold de treino | §11.5 #12 |
| B05 | HMM/regime ajustado na série toda e "predito" barra a barra | reajustar por fold com purge | §5.2 |
| B06 | usar a tabela de IC 7 anos (§17.2) para configurar modelo | triagem in-fold | §5.3 |

### Vazamento estrutural

| # | proibido | correto | âncora |
|---|---|---|---|
| B07 | treinar Meta em predição do Alpha sem `is_oof` | `assert df_meta.is_oof.all()` | §5.12 |
| B08 | calibrador ajustado sobre o próprio OOF | sub-split interno do treino | §5.9 passo 9 |
| B09 | split de CV sem purge por `t1` | purge + embargo 175 barras | §11.4 |
| B10 | treinar sem `sample_weight` de unicidade | sempre com peso | §3.5 |

### Label e execução

| # | proibido | correto | âncora |
|---|---|---|---|
| B11 | avaliar barreira em high/low da barra de 15m | `mark_1m`, primeiro toque cronológico | §3.4 |
| B12 | stop com `working_type: CONTRACT_PRICE` | `MARK_PRICE` | §9.1 |
| B13 | converter ordem limite em market no timeout | `on_timeout: CANCEL` | §9.1 |
| B14 | postar TP antes do SL após fill | SL **sempre** primeiro | §16.2 |
| B15 | `config_hash` do label ≠ o da execução | teste de CI | §3.4 |
| B16 | enviar ordem com outra em `UNKNOWN` | resolver antes | §9.7 |
| B17 | cache local de equity | reconciliação é a única fonte | §8.7 |

### Modelo

| # | proibido | correto | âncora |
|---|---|---|---|
| B18 | `multi:softprob` | dois binários `M_long`/`M_short` | §5.2 |
| B19 | `colsample_bytree < 1.0` com bagging por grupo ativo | `1.0` — camada 3 substitui | §5.10 |
| B20 | threshold escolhido por métrica OOS | a priori pelo orçamento de fees | §5.6 |
| B21 | `hmmlearn` | determinístico por quantis; `dynamax` na V1.1 | §14.1 |
| B22 | retreinar após sequência de perdas | cadência fixa declarada a priori | §16.4 |
| B23 | faixa esperada inventada em doc ou teste | `TBD — medir no Sprint N` | §16.10 M4 |
| B24 | `N_eff = n/h` ou `1+s(2h−1)` como constante | medir `Σ uniqueness` | §0.2 R4 |
| B25 | presumir ATR de volatilidade anualizada | medir dos klines | §0.4 |

### Stack e operação

| # | proibido | correto | âncora |
|---|---|---|---|
| B26 | Pandas no core | Polars lazy; Pandas só em interop de borda | §14.1 |
| B27 | `pip`/`venv`/`conda` | `uv` + lockfile | §14.1 |
| B28 | `print()` | `structlog` + orjson | §14.1 |
| B29 | escrita não-atômica | `.tmp` → `fsync` → rename | §1.2 |
| B30 | `enable_withdraw: true` na chave de API | jamais, em nenhuma circunstância | §16.7 |
| B31 | chave em código, config versionada, log ou mensagem de erro | env fora do repo + mascaramento | §16.7 |
| B32 | assinar REST sem percent-encode antes | ordem correta, senão `-1022` | §9.4 |

---

## Layer hierarchy

```
exchange → data → features → labels → regime → models → validation
                                                    ↓
                          backtest ← risk ← execution ← live
```

Verificada estaticamente (`pyproject.toml::[tool.importlinter]`). Violações
quebram o build:

- `features/` não pode importar `labels/`.
- `models/` não pode importar `execution/`.
- Só `models/`, `validation/`, `backtest/`, `analysis/` leem `labels/`.
  `analysis/` fica fora do contrato `importlinter` de propósito — é medição
  pós-hoc, nunca pode virar insumo de treino/seleção de feature.
- `alpha` não pode importar `meta` (zero realimentação, §5.8).

---

## Stack 2026

**Obrigatório:** Python 3.12+ · `uv` · Polars (lazy, Arrow) · DuckDB ·
Parquet+zstd · XGBoost `binary:logistic` · scikit-learn (calibração isotônica)
· Optuna com orçamento declarado · structlog+orjson · Pydantic+YAML ·
pytest+hypothesis · ruff · mypy strict

**Avaliar antes de escrever motor próprio:** NautilusTrader (backtest
event-driven) · `binance-futures-connector` oficial atrás de interface própria

**Proibido:** `hmmlearn` · Pandas no core · pip/venv/conda · `print()`

---

## Definition of Done por tipo de tarefa

### Código de feature
- [ ] Entrada em `features/registry.yaml` (fórmula, fonte, lookback, `causal_proof`)
- [ ] Teste de causalidade: nenhum índice ≥ `t0`
- [ ] Teste de paridade lote↔streaming < 1e-8 nas últimas 500 barras
- [ ] Teste de determinismo: mesmo input → mesmo hash
- [ ] Warmup declarado e respeitado

### Código de modelo
- [ ] `sample_weight` de unicidade aplicado
- [ ] Predições marcadas com `is_oof`
- [ ] `monotone_constraints` derivadas in-fold
- [ ] HHI de importância < 0,25, maior share < 0,30
- [ ] Métricas estratificadas por regime R1..R4 e por regime econômico

### Código de execução
- [ ] `time_in_force: GTX` na entrada
- [ ] SL antes de TP no handler de fill, timeout de 2s
- [ ] `client_order_id` determinístico e idempotente
- [ ] Teste de fill parcial na entrada e na saída
- [ ] Teste de reinício com posição aberta

### Qualquer PR
- [ ] Nenhum literal numérico novo fora de `constants.yaml`
- [ ] `provenance` declarada para toda constante nova
- [ ] `N_lifetime` incrementado se houve otimização
- [ ] Âncora §X.Y do PRD no commit message

---

## Protocolo de execução — quem roda o quê

Claude nunca executa `.py` nem comando que rode código Python (`uv run
quant ...`, `uv run pytest`, `python -m ...`) via Bash/PowerShell. Só o
usuário executa. Fluxo:

1. Claude escreve/edita código normalmente (Write/Edit não é execução).
2. Comando pra rodar: entregue exato, pronto pra copiar/colar, sem variação.
3. Claude não avança pro próximo passo até o usuário colar o output.

Consequência: output de script novo precisa ser autoexplicativo
(`structlog`, erro com contexto suficiente, resumo legível) — parte do DoD.

Liberado sem restrição (não é execução de Python): `git`, leitura/listagem
de arquivo, `grep`/`rg`.

**Exceção nomeada — 7 comandos mecânicos de auditoria** (só leitura, sem
efeito em dado/exchange/trial), autorização do Manager, 2026-08-12:

```bash
python tools/lint/banned_patterns.py --path <alvo> --strict
python tools/lint/check_constants_referenced.py --src <alvo>
python tools/lint/check_constants_provenance.py
python tools/lint/check_unguarded_ratios.py --path <alvo>
python tools/lint/check_sprint_log_references.py
uv run ruff check <alvo>
uv run mypy <alvo>
```

NÃO se estende a `pytest` (mesmo `-m "not slow"`), a `uv run quant
<subcomando>`, nem a qualquer script fora desta lista — exaustiva, não um
padrão a extrapolar. Se um dos 7 falhar de um jeito que sugira efeito
colateral real (erro de permissão de escrita, traceback tocando `data/`),
parar e reportar, não presumir que a exceção ainda vale. Motivo/detalhe:
`CLAUDE.md` histórico em `git log -- CLAUDE.md`, usado por
`.claude/skills/audit_engineering/` e `.claude/skills/project_assurance/`.

---

## Comandos

**ATENÇÃO (2026-08-16): esta CLI `quant` é a interface PRETENDIDA, ainda
NÃO implementada.** `pyproject.toml` não tem `[project.scripts]`, não
existe módulo/pacote `quant` no repo — `uv run quant <qualquer coisa>`
falha com `error: Failed to spawn: quant`. Achado real: citei este bloco
como se existisse antes de verificar, o usuário tentou rodar e recebeu o
erro. Até essa CLI ser construída (sprint não definido), os pipelines
reais são invocados direto por módulo, ex. `uv run python -m
src.labels.backfill_multi_symbol`, `uv run python -m
src.analysis.m2_bar_comparison`, `uv run python -m
src.analysis.calibration_diagnostics` — cada um com seu próprio
`if __name__ == "__main__":`. Nem todo pipeline tem um desses hoje
(Feature/Regime Engine não persistem artefato em lote, são recomputados
on-the-fly a cada chamada de `build_modeling_frame` — ver docstring de
`src/models/dataset.py`). Antes de citar um comando `quant` como "rode
isto", confirme que ele existe de verdade.

```bash
uv run quant feasibility          # Gate 0 — roda em segundos, ANTES de tudo
uv run quant data download        # 15 fontes, checksums
uv run quant data validate        # → quality_report.json
uv run quant features build       # + paridade
uv run quant regime build
uv run quant labels build         # → t1, uniqueness, NOFILL
uv run quant validation leakage   # 14 testes
uv run quant models train         # camadas 1→5 com ablação
uv run quant validation cpcv
uv run quant validation walkforward   # G-WF-1..6, mede meia-vida
uv run quant backtest run         # + reconciliação vs ret_net
uv run quant validation dsr       # com N_lifetime
uv run quant stress run           # 19 cenários
uv run quant testnet run
uv run quant paper run
uv run quant live run
```

---

## Marcadores pytest

`golden`/`slow`/`integration` (`pyproject.toml::[tool.pytest.ini_options]`),
eixos independentes — um teste pode carregar mais de um.

| marcador | significa | quando aplicar |
|---|---|---|
| `golden` | reprodutibilidade bit-a-bit contra artefato versionado | retreina algo de verdade e compara contra `.json` commitado |
| `slow` | custa sozinho mais que ~2s | reconstrói série/frame real completo, não fixture sintética |
| `integration` | lê artefato real do disco via skip-if-ausente | chama `_skip_if_*`/`pytest.skip(...)` condicionado a backfill local |

Todo teste novo que reconstrói dado real ganha `integration`; se passar de
~2s, ganha `slow` também.

```bash
uv run pytest                        # tudo, inclusive slow/integration
uv run pytest -m "not slow"          # ciclo rápido, < 30s
uv run pytest -m "not integration"   # sem backfill local
uv run pytest -m golden              # só reprodutibilidade
```

---

## Git

Repositório `github.com/FelipeCJBoB/btcusdt-quant-engine` (privado). Branch
única `master`, trunk-based — sem PR pro dia a dia.

- Commitar ao fechar unidade de trabalho coerente (tarefa, decisão, achado,
  sprint) — não por sessão inteira, não por arquivo isolado.
- Mensagem: título curto imperativo (~70 char) + corpo (o quê/por quê, o
  diff já mostra o como) + âncora §X.Y do PRD quando aplicável + achado
  relevante, mesmo negativo.
- Tag `sprint-N-done` / `gate-M-pass` ao fechar sprint/gate, com `git push
  --tags`.
- `docs/SPRINT_LOG.md` atualizado ao fechar sprint, ANTES de tagear — é o
  documento de estado atual pra humano, não este arquivo.
- Push direto pra `origin/master` após commit significativo — autorizado
  por padrão, sem pedir a cada vez. Force-push/reset/rewrite/branch
  protegida exigem confirmação explícita, sempre, sem exceção.

Motivo/detalhe completo: `PLANO_MESTRE_PRINCE2.md` §11.

---

## Diretrizes de comportamento

- Mandato: entregar edge real, não só código que roda — "terminar" é o
  código rodar E o resultado ser honesto sobre edge real. Escopo/prioridade
  são do Manager; como perseguir dentro do escopo é de Claude. Motivo:
  diretriz do Manager, `git log` (2026-08-11).
- Meça antes de afirmar. Nunca invente faixa esperada — escreva `TBD —
  medir no Sprint N` (B23). Histórico de erros por não medir:
  `PRD_V3_2_UNIFICADO.md` PARTE XIX (9 erros corrigidos, mapa de
  rastreabilidade).
- Declare proveniência (`MEASURED`/`DERIVED`/`LITERATURE`/`ASSUMED`) em todo
  número novo. Sem base conhecida → `ASSUMED` + classificar.
- Lote mínimo é restrição física, não arredondamento. Mudança de parâmetro
  que viola R1/R2 está errada — a restrição não é o problema.
- Nunca reparametrize de volta um valor `DERIVED` como grau de liberdade
  livre (ex. `risk_per_trade`).
- Discorde do Manager quando o dado discordar — apresente a medição, não
  acomode a instrução.
- Avalie stack de prateleira antes de escrever motor próprio (backtest
  engine é o maior risco caseiro do projeto).
- Pare na primeira camada que atender o critério de parada declarado (§5.11)
  — cada camada extra custa `N_lifetime` e uma fonte de bug a mais.
- Nunca silencie warning sem achar a causa raiz, mesmo "cosmético"
  (`np.errstate` em cima do sintoma é remediação, não solução). A pergunta
  é sempre "o que essa operação está tentando dizer sobre o dado". Exemplo
  real: `docs/SPRINT_LOG.md` (M1, `diebold_mariano`).
