# Prompt de execução — implementar o design completo do Alpha (D-01 a D-18)

> Uso: copie o conteúdo abaixo (a partir de "## Tarefa") como mensagem inicial
> de uma sessão Claude Code nova, aberta neste mesmo repo. Este arquivo em si
> não é lido automaticamente por ninguém — é só o texto-fonte do prompt.

## Tarefa

Implemente o desenho **completo** de
`docs/alpha_model_design_doc_2026-08-22.md` (v3, Fase 4 — desenho travado,
ZERO código escrito ainda) — as 18 decisões, `D-01` a `D-18`. Leia o
documento INTEIRO (1089 linhas) antes de escrever qualquer linha — ele já
resolveu a maior parte das perguntas de design, incluindo uma pesquisa de
literatura (AFML + paper real de 2026) que justificou D-02; não redecida
nada que já está lá sem motivo novo.

## Pré-requisitos CRÍTICOS — resolva ANTES de tocar em qualquer arquivo

1. **`git pull` + `git log --oneline -10`.** Este repo tem histórico real
   de sessões paralelas colidindo no mesmo território no mesmo dia — confirme
   que está partindo do estado mais recente antes de começar.

2. **`AG-162` (CRITICAL) — RESOLVIDO 2026-08-23, não é mais decisão
   pendente.** D-05 prevalece como escrito: `tau_long`/`tau_short` crus (2
   colunas cruas) em `PREDICTIONS_SCHEMA_COLUMNS`. `AG-150` e
   `PLANO_MESTRE_PRINCE2.md §15.19-F`/`§15.20-E` já foram atualizados para
   refletir isso — não pergunte de novo ao usuário. `tau_alpha` NÃO é
   coluna física do Alpha; é coluna DERIVADA dentro do Meta
   (`meta_dataset.py::build_meta_signal_table`, `tau_alpha = tau_long if
   side_hat == 1 else tau_short`), já aplicado em
   `docs/meta_model_design_doc_2026-08-22.md` §3.2/§3.5/§21 — mesmo padrão
   que `p_alpha`/`score_alpha_raw` já usam no mesmo documento. Ao
   implementar `SideModelResult`/`PREDICTIONS_SCHEMA_COLUMNS`, use
   `tau_long`/`tau_short` diretamente, sem reabrir a discussão.

3. **Confirme que o gate "Alpha não retreina até Data Layer 100%" está
   realmente aberto hoje.** O design doc (§8) cita 4 blocantes específicos —
   todos os 4 estavam FECHADOS em 2026-08-23 (mesmo dia deste desenho, sessão
   posterior): `AG-138` (`01_BARRA`, commit `ef7f5d3`), `AG-139`
   (`03_FEATURES`, mesmo commit), `AG-140` (`07_LABEL`, commit `79f380f`), e a
   decisão de política do `08_SPLIT` (features `expanding` excluídas de
   `T1_FEATURE_IDS`, commit `78169df`, `AG-032`). **Isso NÃO significa que o
   gate está automaticamente livre agora** — (a) `06_BARREIRAS` segue
   deliberadamente represado (débito organizacional aceito, não bloqueante
   por decisão já confirmada); (b) pode ter surgido gap novo desde então. Leia
   `PLANO_MESTRE_PRINCE2.md §15.4` (tabela de 15 estágios) e `§15.27`/`§15.28`
   (estado mais recente) antes de assumir que pode treinar. Se o gate estiver
   mesmo livre, isso é uma mudança material desde que o design doc foi escrito
   — **confirme com o usuário antes de consumir orçamento de trial**, mesmo
   que o código esteja pronto.

4. **`AG-100`/`AG-124` já estão `status: "fechado"`** (confirmado por escrito
   2026-08-23, depois do design doc ter sido escrito) — a ressalva do §1/§2.2
   do design doc ("status formal ainda aberto") está desatualizada, pode
   tratar como fechada. A pergunta sobre escopo do reprocessamento
   (features/regime/CPCV incluídos) tem uma leitura arquitetural registrada em
   `AG-163` (não são artefato persistido em lote, recomputados on-the-fly a
   cada `build_modeling_frame` — refletem o dado novo por construção) — não é
   confirmação formal do Manager, mas é razão pra não tratar isso como
   bloqueante.

## Escopo — as 18 decisões (ler §3 do design doc para o texto completo de cada uma)

Resumo de orientação, não substitui a leitura do documento:

- **D-01** — Learner = LightGBM (`lgb.LGBMClassifier`), decisão herdada de
  `§15.14`, não reaberta. CatBoost descartado.
- **D-02** — Grão de treino independente por `(symbol, resolution_id)` — 15
  modelos, sem pooling cross-ativo em v1 (evita `AG-151` por construção, não
  por sorte — ver a pesquisa de literatura em §3/D-02, decisão já
  fundamentada, não redecida).
- **D-03** — `symbol`/`resolution_id` viram colunas explícitas do schema de
  `predictions.parquet` (hoje só vivem na convenção de nome/caminho).
- **D-04** — `DESIGN_COLUMNS` continua SEM regime — não reabra essa remoção
  (ver "Fora de escopo" abaixo).
- **D-05/D-06** — `tau_long`/`tau_short` persistidos (crus, sem seleção de
  lado no Alpha) + manifesto/versão — decisão já resolvida (pré-requisito
  2 acima), implemente diretamente.
- **D-07/D-09/D-10** — `monotone_constraints`, calibração isotônica, CPCV:
  reuso sem mudança de arquitetura.
- **D-08** — extração de importância reescrita pra API do LightGBM
  (`booster_.feature_importance`/`feature_name()` em vez de
  `booster.get_score()`) — ver tabela completa de API em §4.
- **D-11** — hiperparâmetros LightGBM: conjunto único v1, `ASSUMED` até
  sweep (`min_child_samples`/`num_leaves` são conceitos NOVOS sem
  equivalente 1:1 no XGBoost — não invente conversão numérica, declare
  `ASSUMED` com `sweep_required: true`, B23).
- **D-12** — persistência: formato texto (`booster_.save_model`, não mais
  binário `.ubj`) + `model_dir` chaveado também por `(symbol,
  resolution_id)` — fecha `AG-158`. Ver §6.
- **D-13** — orquestração: loop sobre as 15 combinações, sem mudar
  assinatura de `build_modeling_frame`/`generate_splits` — `report_path`
  precisa de tag único por combinação (fecha `AG-160`, senão as 15 chamadas
  se sobrescrevem).
- **D-14** — `N_lifetime`: multiplicador 15× declarado explicitamente, não
  escondido (mesmo que `N_lifetime` não seja mais gate vinculante, `AG-077`
  — registre o número real mesmo assim).
- **D-15** — contrato com Meta-model v3 preservado; a derivação de
  `tau_alpha` (`tau_long`/`tau_short` → seleção por `side_hat`) já vive no
  Meta (`meta_dataset.py::build_meta_signal_table`, `AG-162` resolvido),
  não no Alpha — não precisa nota de sincronismo nova.
- **D-18** — treino em GPU obrigatório (`device_type="cuda"`) — **confirme
  infraestrutura real (GPU/CUDA disponível, mecanismo de instalação do
  LightGBM GPU-enabled via `uv`) com o usuário antes de escrever código que
  assume isso** — pré-requisito de infraestrutura não verificado, item 7 de
  §13 do design doc, `Claude não roda `.py`/`uv`` pra testar isso sozinho.

Fix mecânicos pra sequenciar JUNTO desta implementação (já registrados,
severidade baixa/média, não blocantes isoladamente): `AG-157` (docstrings
dizendo "R2/R3 são só pesquisa", desatualizado).

## Fora de escopo — NÃO implemente, NÃO reabra

- **D-04**: regime SAIU do vetor de treino do Alpha (ADR-001 §2.7,
  ratificado) — o Meta-model v3 depende estruturalmente dessa remoção
  (§2.2 do doc do Meta chama isso de "a vantagem informacional"). Reabrir
  isso desmorona a premissa central do Meta v3 — fora do escopo deste
  documento, sem motivo técnico levantado.
- **D-16** (pooling cross-ativo): evolução futura explícita, gated no
  fechamento de `AG-151` (que segue aberto). Não implemente pooling em v1.
- **D-17** (combinação de sinais R1/R2/R3): responsabilidade do Decision
  Engine, que não existe ainda (`AG-143`, decisão do Manager pendente antes
  do 1º commit). Fora de escopo aqui.
- **`docs/meta_model_design_doc_2026-08-22.md`**: já foi patchado (§3.2,
  §3.5, §21) na reconciliação de `AG-162` — não toque nele de novo aqui,
  a menos que a implementação real de `build_meta_signal_table` revele algo
  que a prosa não previu.
- **`AG-155`** (cadência de retreino): decisão do Manager pendente,
  separada, não deste desenho.

## Testes (ver §11 do design doc pra tabela completa de impacto)

Resumo do que quebra/precisa reescrita, não substitui a leitura:

- `tests/unit/test_models_persistence.py` — reescrita substancial (todos os
  11 testes usam `xgb.XGBClassifier`/`xgb.Booster` diretamente na fixture
  `_fit_real_side_model()`).
- `tests/golden/test_sprint8_reproducibility.py` — baseline fica inválido
  (determinismo bit-exato do XGBoost não se transfere pro LightGBM) —
  commitar novo baseline "Fase A" sob LightGBM.
- `tests/unit/test_models_persistence.py::test_read_model_bundle_formato_de_
  booster_desconhecido_levanta_erro` — a premissa do teste se inverte
  (`"lightgbm_txt_v1"` deixa de ser "formato futuro desconhecido", vira o
  formato real).
- `tests/unit/test_models_alpha.py` — `XGBHyperparams.from_constants()`
  citado em ≥4 testes; decida rename vs. nome genérico na implementação
  (D-11 não decide isso).
- `tests/unit/test_models_alpha.py::test_predictions_parquet_real_schema_e_
  invariantes` — quebra contra os `predictions.parquet` legados em disco
  quando o schema for de 17→21 colunas — regenere os artefatos (ver D-06).

## Protocolo de execução (CLAUDE.md, já carregado no seu contexto de sessão)

Você não executa `.py`/`pytest`/`uv run` diretamente — escreva o código,
entregue o comando exato pronto pra colar, e espere o usuário rodar e colar
o output de volta antes de prosseguir. Os 7 comandos mecânicos de auditoria
(`banned_patterns.py`, `check_constants_referenced.py`,
`check_constants_provenance.py`, `check_unguarded_ratios.py`,
`check_sprint_log_references.py`, `ruff check`, `mypy`) você PODE rodar
direto. Escopo é grande (18 decisões, múltiplos arquivos) — considere
quebrar em unidades de trabalho menores (ex. D-01/D-07/D-08/D-09 = troca de
learner isolada; D-03/D-05/D-06 = schema; D-12/D-13 = persistência/
orquestração; D-18 = GPU por último, depende de infra confirmada) em vez de
uma única entrega monolítica — cada unidade fechando com verificação
mecânica + testes antes de passar pra próxima.

## Revisão antes de considerar fechado

`src/models/` está entre os pacotes de maior materialidade do repo (4 eixos:
exposição financeira real — é o modelo que decide sinal —, peso da decisão,
complexidade da mudança de schema, múltiplos consumidores — Meta-model,
pipeline, persistência). Depois dos testes confirmados verdes pelo usuário,
rode `project_assurance` (revisão de integração independente, PRINCE2 §6.4)
sobre `alpha.py`/`persistence.py`/`pipeline.py` — o próprio design doc já
passou por 2 rodadas disso (auditoria adversarial + `project_assurance`) e
achou 1 CRITICAL + 6 IMPORTANT/MODERATE antes de qualquer código existir;
não pule a mesma disciplina na implementação.

## Governança ao final

Depois de implementado + testado + revisado:

1. `audit/architecture_gaps_log.yaml` — feche (ou atualize `status`) de
   `AG-150` (tau, conforme a decisão do pré-requisito 2), `AG-154`
   (manifesto, via D-06), `AG-157`/`AG-158`/`AG-160` (fixes mecânicos
   sequenciados), `AG-162`/`AG-163` (decisões escaladas, resolvidas), com
   `resolved_by_commit` real em cada um. `AG-151`/`AG-155` continuam
   abertos — não feche esses (são fora de escopo por desenho).
2. `PLANO_MESTRE_PRINCE2.md §15.20` já existe (`AG-161` fechado) — adicione
   subseção datada (mesmo padrão de `§15.21.1`/`§15.21.2`) registrando o que
   foi implementado vs. o que o design doc previa, `N_lifetime` real
   consumido (D-14), e achados novos da revisão independente.
3. `docs/SPRINT_LOG.md` — narrativa + linha da tabela "Estado atual"
   atualizada. Rode `check_sprint_log_references.py` antes de commitar.
4. Road Map Vivo v2 (artefato publicado) — só republique se puder ler o
   conteúdo completo atual primeiro (via `WebFetch`/`Artifact` read) e fizer
   uma edição cirúrgica; NÃO reconstrua do zero.
5. Commit(s) + push — um commit por unidade de trabalho fechada (não um
   monólito de 18 decisões), título curto imperativo + corpo com o quê/por
   quê + âncora `D-NN`/`AG-NNN`.
