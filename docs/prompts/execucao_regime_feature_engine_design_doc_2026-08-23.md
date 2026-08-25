# Prompt de execução — implementar D-01/D-02 do design doc Regime/Feature Engine

> Uso: copie o conteúdo abaixo (a partir de "## Tarefa") como mensagem inicial
> de uma sessão Claude Code nova, aberta neste mesmo repo. Este arquivo em si
> não é lido automaticamente por ninguém — é só o texto-fonte do prompt.

## Tarefa

Implemente as decisões **D-01** e **D-02** de
`docs/regime_feature_engine_design_doc_2026-08-23.md` (v3, Fase 4 — desenho
completo, ZERO código escrito ainda). Leia o documento INTEIRO antes de
escrever qualquer linha — ele já resolveu a maior parte das perguntas de
design; não redecida nada que já está lá sem motivo novo.

**Antes de tocar em qualquer arquivo**, rode `git pull` e `git log --oneline
-5`. Este repo teve pelo menos uma sessão paralela mexendo neste MESMO
território no dia 2026-08-23 (commits `72e02c7`/`9719031`/`ba8cf13`/`c1df1c7`)
— confirme que está partindo do estado mais recente antes de começar.

## Escopo — o que implementar

### D-01 — `bar_source` threading real, S6 causal/expansivo

Ver §3/D-01 do design doc para o texto completo. Resumo do que muda:

- `src/regime/stress.py`: `StressInputs` ganha `bar_source: str =
  "time_15m"` e `close_time_ms: TimeArray | None = None`. Nova função
  `s06_bar_gap_dollar(close_time_ms: TimeArray) -> TriggerArray`.
  `compute_stress_triggers` valida `close_time_ms` obrigatório quando
  `bar_source != "time_15m"` (fail-fast, `ValueError` explícito) e despacha
  S6 pra `s06_bar_gap_dollar` nesse caso.
- **Requisito de correção não-negociável, achado pelo `project_assurance`
  nesta mesma sessão de design (não pule esta parte):** `s06_bar_gap_dollar`
  precisa calcular mediana/MAD de forma **EXPANSIVA** (só gaps
  estritamente anteriores à barra `t` sendo avaliada) — NUNCA sobre a série
  inteira. O precedente citado no design doc (`src/regime/
  hmm_gap_check.py::check_bars_gap_before_hmm`) calcula sobre a série
  inteira, e isso é CORRETO lá (diagnóstico único, não-causal por natureza)
  mas INTRODUZIRIA VAZAMENTO TEMPORAL (banned pattern B02) se portado sem
  adaptação pra uma função por-barra plugada em `compute_stress_triggers`
  → `_run_state_machine` → `regime[t]`, que viola o contrato causal
  explícito do `RegimeClassifier` Protocol (`classifier.py:419-420`, "barra
  t usa apenas índices < t"). Use a mesma disciplina causal de
  `support.expanding_percentile_rank_strict` (já usada no mesmo módulo pra
  `vol_pctile`/`er_quantile`) como referência de como uma estatística
  expansiva já é implementada neste repo.
- Casos de borda (ver §3/D-01 do design doc pro texto exato): menos de 3
  gaps ANTERIORES disponíveis na barra `t` → `NOT_COMPUTABLE`
  (`_not_computable`, convenção dominante de `stress.py`). Gap
  não-monotônico (`<=0`) → `TRIGGERED` incondicional, independente do
  z-score.
- `src/regime/classifier.py`: `QuantileRegimeClassifier` ganha campo
  `bar_source: str = "time_15m"`. `classify()` extrai `close_time` de
  `features` (já presente no DataFrame — `ALL_OUTPUT_COLUMNS` de
  `src/features/build.py` já inclui `close_time`) e propaga
  `bar_source`/`close_time_ms` pra `StressInputs`.
- `src/regime/build.py::build_regimes`: passa `bar_source=bar_source` no
  construtor de `QuantileRegimeClassifier` — hoje não passa nada.

### D-02 — CPCV purge lookback resolution-aware (fecha `AG-159`, 2 call sites)

Ver §3/D-02 do design doc. Resumo:

- `src/features/build.py::compute_max_feature_lookback_ms` ganha parâmetro
  keyword-only `resolution_id: str | None = None`. Quando setado, a
  duração de barra usada no cálculo passa de `step_ms(tf)` pra
  `int(load_constant("label_prefetch_p99_bar_duration_ms"))` (constante já
  `MEASURED` em `config/constants.yaml`, não invente número novo).
- **Os DOIS call sites precisam mudar na MESMA unidade de trabalho, não um
  de cada vez:** `src/models/pipeline.py:427` E `src/validation/
  leakage.py:792` (dentro de `run_all_leakage_tests`, que já recebe
  `resolution_id` como parâmetro sem repassá-lo — confirme a linha exata
  antes de editar, número de linha pode ter mudado desde o desenho). Se só
  um dos dois for corrigido, a suíte de vazamento (testes 6/7/12) passa a
  reportar PASS falso sob R2/R3 enquanto o pipeline real de treino já usa
  proteção diferente — exatamente o risco que o comentário já existente em
  `leakage.py` (citando `AG-032`/`AG-009`) descreve.
- Efeito prático de D-02 hoje é ZERO em produção — `assert_no_expanding_
  lookback_in_active_set` já bloqueia incondicionalmente pro conjunto ativo
  de features T1 (C07/D03f/E02f são `expanding`). Implemente mesmo assim
  (o fix de unidade precisa estar pronto pra quando esse gate for resolvido
  pelo Manager) — não é trabalho desperdiçado, é pré-requisito.

## Fora de escopo — NÃO implemente

- **D-04** (histerese em contagem de barra — `regime_confirmation_bars`/
  `regime_stress_exit_confirmation_bars`/`min_warmup_bars`): gap real,
  registrado (`AG-180`), mas **sem valor medido pra corrigir** — B23
  proíbe inventar uma conversão numérica não medida. Não toque nessas
  constantes.
- **§11 do design doc** (caminho de troca pro HMM): decisão explícita do
  documento é NÃO andar por esse caminho agora. Não implemente o parâmetro
  `regime_engine_id` nem qualquer dispatch pra `build_hmm_regimes` em
  `dataset.py`.
- Qualquer coisa em `§2.3`/`D-03` do documento (itens já confirmados
  corretos) — não mexa no que já está certo.

## Testes (ver §10 do design doc pra lista completa)

- Novo teste: `s06_bar_gap_dollar` — determinismo, MAD=0 (mesmo achado real
  documentado em `hmm_gap_check.py`), `n<3` gaps anteriores, não-
  monotonicidade. **Teste de não-vazamento explícito**: construa uma série
  sintética onde um gap anômalo aparece SÓ no futuro (barras tardias) e
  confirme que a classificação de barras ANTERIORES a esse gap não muda
  entre "com" e "sem" esse gap futuro presente na série — prova direta de
  causalidade.
- Novo teste: `compute_stress_triggers` levanta `ValueError` quando
  `bar_source != "time_15m"` e `close_time_ms is None`.
- Novo teste: `QuantileRegimeClassifier(bar_source="dollar_r1")` +
  inspeção real de `stress_triggers`/`regime`/`regime_raw` sob dado
  sintético com um gap conhecido — não só `tradeable`.
- `compute_max_feature_lookback_ms(resolution_id="R2")` — teste de unidade
  correta, pros DOIS call sites (`pipeline.py`, `leakage.py`).
- Fixtures existentes que quebram por `resolution_id` ser keyword-only:
  `tests/unit/test_models_pipeline_paths.py` e
  `tests/unit/test_validation_leakage.py` têm `monkeypatch.setattr(...,
  lambda tf: 0)` (assinatura posicional de 1 arg) — atualize pra `lambda
  tf, **_: 0` ou equivalente. Confirme os números de linha atuais antes de
  editar (podem ter mudado).
- Considere também (recomendação do `project_assurance`, não obrigatório
  antes de fechar a unidade de trabalho, mas registre se pular): teste de
  estabilidade de `src/models/environments.py`/`src/models/monotonic.py`
  sob `resolution_id="R2"`/`"R3"`, antes/depois desta mudança — mede o raio
  de explosão real em `monotone_constraints` que §7 item 6 do design doc
  identifica.

## Protocolo de execução (CLAUDE.md, já carregado no seu contexto de sessão)

Você não executa `.py`/`pytest`/`uv run` diretamente — escreva o código,
entregue o comando exato pronto pra colar, e espere o usuário rodar e colar
o output de volta antes de prosseguir. Os 7 comandos mecânicos de auditoria
(`banned_patterns.py`, `check_constants_referenced.py`,
`check_constants_provenance.py`, `check_unguarded_ratios.py`,
`check_sprint_log_references.py`, `ruff check`, `mypy`) você PODE rodar
direto.

## Revisão antes de considerar fechado

`src/regime/` está na lista de pacotes que exigem revisão independente
"sempre que um Pacote de Trabalho terminar" (`.claude/skills/
project_assurance/SKILL.md`, critério de materialidade). Depois dos testes
confirmados verdes pelo usuário, rode `/project_assurance` (ou, se preferir
o fluxo mais leve, `audit_engineering`) sobre `stress.py`/`classifier.py`
antes de aplicar governança — mesmo padrão que a implementação de
`fill_simulator.py` já seguiu neste repo no mesmo dia (commit `72e02c7`,
3 auditores paralelos, achou 2 CRITICAL reais).

## Governança ao final

Depois de implementado + testado + revisado:

1. `audit/architecture_gaps_log.yaml` — feche (ou atualize `status`) de
   `AG-177` (S6 cego a `bar_source`) e da parte de `AG-159` relativa ao
   escopo D-02, com `resolved_by_commit` real. `AG-180` (D-04) e o caminho
   HMM (§11) continuam abertos — não feche esses.
2. `PLANO_MESTRE_PRINCE2.md` — nova subseção datada (mesmo padrão de
   `§15.21.1`) registrando o que foi implementado vs. o que o design doc
   previa, e quaisquer achados novos da revisão independente.
3. `docs/SPRINT_LOG.md` — narrativa + linha da tabela "Estado atual"
   atualizada. Rode `check_sprint_log_references.py` antes de commitar.
4. Road Map Vivo — só republique se puder ler o conteúdo completo atual
   primeiro (via `WebFetch`/`Artifact` read) e fizer uma edição cirúrgica;
   NÃO reconstrua do zero. Se não conseguir ler por inteiro, siga a mesma
   disciplina já registrada no próprio artefato ("Nota de transparência —
   sessões concorrentes") e pule a republicação, deixando registrado o
   motivo.
5. Commit(s) + push — siga o padrão de mensagem já usado nos commits
   `ba8cf13`/`c1df1c7` deste mesmo dia (título curto imperativo + corpo
   com o quê/por quê + âncora de decisão).
