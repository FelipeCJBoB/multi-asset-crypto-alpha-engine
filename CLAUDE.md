# CLAUDE.md — Motor Quant Multi-Ativo

> Só regras vigentes — zero estado, zero histórico de decisão.
> Estado atual: `docs/SPRINT_LOG.md`. Histórico de mudança: `git log`.
> Histórico deste arquivo: `git log -- CLAUDE.md`.

**Documentos canônicos — só 2:** `PLANO_MESTRE_PRINCE2.md` (governança,
decisões, PBS) e `docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md`
completo (Partes I/II — não o resumo de 222 linhas). `PRD_V3_2_UNIFICADO.md` /
`PRD_V4_1.md` são **obsoletos**: nunca base de decisão de produção, só
recebem ponteiro de 1 linha do Plano Mestre, nunca o inverso.

Toda regra abaixo com âncora `§X.Y` do PRD é rastreabilidade histórica — a
âncora não torna o PRD autoritativo de novo. Regra sem âncora é dívida de
documentação, não de arquitetura.

## Onde cada coisa mora

| procura por | caminho |
|---|---|
| Estado atual, sprint a sprint | `docs/SPRINT_LOG.md` |
| Governança, PBS, Road Map Vivo (§11.4) | `PLANO_MESTRE_PRINCE2.md` |
| Arquitetura de artefatos/contratos (canônico) | `docs/ADR-001_arquitetura_artefatos_e_contratos_2026-08-19_base.md` |
| Blueprint histórico — **obsoleto**, não decidir por ele | `PRD_V3_2_UNIFICADO.md` / `PRD_V4_1.md` |
| Proveniência/classe de toda constante | `config/constants.yaml` |
| Furos de arquitetura/integração (AG-NNN) | `audit/architecture_gaps_log.yaml` |
| Orçamento de trials (multiple-testing) | `audit/n_lifetime.yaml` |
| Achados estatísticos medidos | `audit/evidence_ledger.yaml` |
| Roadmap visual (M1-M6/V41-N + 15 estágios) | Road Map Vivo v2 — link em `PLANO_MESTRE_PRINCE2.md` §14 |
| Skills disponíveis | `.claude/skills/` |
| Protocolo "atualize governança" | skill `update-governance` |
| Exceções de execução (comandos que Claude roda direto) | `.claude/rules/execution-exceptions.md` |
| Contexto/exemplos de diretrizes de comportamento | `.claude/rules/behavior-notes.md` |

## Bootstrap — antes de qualquer decisão grande

1. `docs/SPRINT_LOG.md` — últimas seções, estado real.
2. `PLANO_MESTRE_PRINCE2.md` §11.4 — o que já está agendado, antes de tratar algo como urgente.
3. `audit/architecture_gaps_log.yaml` — gaps abertos relevantes à tarefa.
4. `audit/n_lifetime.yaml` — orçamento de trials restante, se a tarefa envolver otimização/sweep/retreino.
5. `config/constants.yaml` — se a tarefa tocar em constante nova ou existente.

## Projeto

- Motor quant multi-timeframe (R1, R2, R3), multi-par (BTC/ETH/SOL/BNB/XRP),
  bidirecional (long/short), Binance USDⓈ-M, capital R$ 1.000, execução
  maker post-only. Definição completa: `PLANO_MESTRE_PRINCE2.md` §15.
  "M15/M30/H1" é identidade de MISSÃO, não o tipo de barra em produção:
  `canonical_bar_type: dollar`; `resolution_id` (R1/R2/R3) substitui os
  nomes M15/M30/H1 como identidade de grade. Não presuma equivalência de
  tempo entre resolução e TF de relógio (`AG-042`).
- V1 existe pra construir infraestrutura hipótese → teste → validação →
  execução → auditoria — não pra provar que BTC é previsível. §15.
- Capital é restrição estrutural, nunca parâmetro livre. Lote mínimo = 33%
  do equity. §0.

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

- Nenhum literal numérico em código de pipeline — enforcement: `tools/lint/banned_patterns.py`.
- Classe A com `provenance: ASSUMED` bloqueia build de produção — enforcement: CI.
- Guardrails classe C são quantis (`p95(spread, 90d)`), nunca número redondo.
- Classe A exige sweep de sensibilidade ±50% antes do Gate 3.
- `N_lifetime` incrementa em toda otimização classe B, retreino, challenger —
  nunca decrementa. DSR usa `N_lifetime`, não o `N` de uma busca isolada.

Motivo histórico: `PLANO_MESTRE_PRINCE2.md` §16.10, PARTE XVIII do PRD.

## Stack 2026

**Obrigatório:** Python 3.12+ · `uv` · Polars (lazy, Arrow) · DuckDB ·
Parquet+zstd · LightGBM `objective="binary"` · scikit-learn (calibração
isotônica) · Optuna com orçamento declarado · structlog+orjson ·
Pydantic+YAML · pytest+hypothesis · ruff · mypy strict

**Avaliar antes de escrever motor próprio:** NautilusTrader (backtest
event-driven) · `binance-futures-connector` oficial atrás de interface própria

## Execução — quem roda o quê

Claude **nunca** executa `.py` nem comando que rode código Python (`uv run
quant ...`, `uv run pytest`, `python -m ...`) via Bash/PowerShell. Só o
usuário executa. Exceto autorização do Manager.

1. Claude escreve/edita código normalmente (Write/Edit não é execução).
2. Entrega o comando exato, pronto pra copiar/colar, sem variação.
3. Não avança pro próximo passo até o usuário colar o output.

Consequência: output de script novo precisa ser autoexplicativo
(`structlog`, erro com contexto, resumo legível) — parte do DoD.

Liberado sem restrição (não é execução Python): `git`, leitura/listagem de
arquivo, `grep`/`rg`. As 7 exceções de lint/type-check só-leitura estão em
`.claude/rules/execution-exceptions.md`.

## Marcadores pytest

`golden` / `slow` / `integration` (`pyproject.toml::[tool.pytest.ini_options]`),
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

## Git

Repositório privado. Branch única `master`, trunk-based — sem PR pro dia a dia.

- Commitar ao fechar unidade de trabalho coerente (tarefa, decisão, achado,
  sprint) — não por sessão inteira, não por arquivo isolado.
- Mensagem: título curto imperativo (~70 char) + corpo (o quê/por quê) +
  âncora §X.Y do PRD quando aplicável + achado relevante, mesmo negativo.
- Tag `sprint-N-done` / `gate-M-pass` ao fechar sprint/gate, com `git push --tags`.
- `docs/SPRINT_LOG.md` atualizado ao fechar sprint, ANTES de tagear.
- Push direto pra `origin/master` após commit significativo — autorizado
  por padrão, sem pedir a cada vez. Force-push/reset/rewrite/branch
  protegida exigem confirmação explícita, sempre, sem exceção.

Detalhe completo: `PLANO_MESTRE_PRINCE2.md` §11.

## Diretrizes de comportamento

- **Correção pedida pelo Manager é o comportamento DEFAULT a partir do
  commit que a aplica — nunca atrás de flag opt-in "por via das dúvidas".**
  Não vale quando a MEDIÇÃO (não a falta de ordem) recomenda contra a
  mudança, nem pra comparação lado-a-lado pedida explicitamente pelo
  Manager. Isto não elimina teste real, proveniência declarada, nem nenhum
  item do DoD. Contexto/exemplo do porquê: `.claude/rules/behavior-notes.md`.
- Mandato: entregar edge real, não só código que roda. Escopo/prioridade
  são do Manager; como perseguir dentro do escopo é de Claude.
- Meça antes de afirmar. Nunca invente faixa esperada — escreva
  `TBD — medir no Sprint N` (B23).
- Declare proveniência (`MEASURED`/`DERIVED`/`LITERATURE`/`ASSUMED`) em todo
  número novo. Sem base conhecida → `ASSUMED` + classificar.
- Lote mínimo é restrição física, não arredondamento — se um parâmetro
  viola R1/R2, o parâmetro está errado, não a restrição.
- Nunca reparametrize de volta um valor `DERIVED` como grau de liberdade livre.
- Discorde do Manager quando o dado discordar — apresente a medição, não
  acomode a instrução.
- Avalie stack de prateleira antes de escrever motor próprio (backtest
  engine é o maior risco caseiro do projeto).
- Pare na primeira camada que atender o critério de parada declarado
  (§5.11) — cada camada extra custa `N_lifetime` e é fonte de bug a mais.
- Nunca silencie warning sem achar a causa raiz, mesmo "cosmético". A
  pergunta é sempre "o que essa operação está tentando dizer sobre o dado".
- Toda regra de decisão travada *a priori* (gates, limiares, critério de
  desempate) precisa de DEFINIÇÃO OPERACIONAL de cada termo ("empate" =
  diferença menor que quanto? o limiar opera sobre mediana ou máximo?), não
  só a métrica e o valor — senão a decisão real é tomada por julgamento na
  hora de aplicar, exatamente o viés que travar a priori existe pra evitar
  (`AG-114`/`AG-118`/`AG-122`).

### Protocolo "atualizar governança"

Quando o usuário pedir "atualize governança" ou "busque nos docs de
governança": carregar o skill `update-governance`
(`.claude/skills/update-governance/SKILL.md`). Lista fixa de 7 itens,
definida pelo Manager (2026-08-17) — não improvisar a lista de memória.