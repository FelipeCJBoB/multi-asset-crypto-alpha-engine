---
name: atualiza_ag
description: Protocolo pra sincronizar o artefato "Caixa-Preta do Motor" (explorador interativo dos AGs) com o estado atual de audit/architecture_gaps_log.yaml. Use quando o usuário disser "Atualiza ag" — reprocessa o YAML e republica no mesmo link, sem redesenhar nada.
---

# atualiza_ag — Protocolo "Atualiza ag"

O artefato **Caixa-Preta do Motor** (`https://claude.ai/code/artifact/795b322a-3201-410f-8dfa-56063bfa7118`)
é um explorador HTML autocontido dos 410+ furos de arquitetura registrados
em `audit/architecture_gaps_log.yaml` (busca, filtros, painel, linha do
tempo, rede de módulos, cadeias narrativas). Foi publicado em 2026-08-31
cobrindo AG-001…AG-393. O YAML é append-only e cresce a cada sessão —
este protocolo existe pra republicar o artefato **sem redesenhar nada**
toda vez que o usuário disser **"Atualiza ag"**.

## Arquitetura do artefato (por que dá pra atualizar sem redesenhar)

O HTML final é a concatenação de 4 peças. Só a 4ª muda numa atualização
de rotina:

| peça | arquivo | muda quando |
|---|---|---|
| título + CSS + markup | `templates/shell_head.html` | pedido explícito de mudança visual |
| abertura do `<script>` | `templates/shell_prefix.txt` | nunca (1 linha fixa) |
| lógica JS inteira (normalização, filtros, gráficos SVG, abas, eventos) | `templates/shell_app.js` | pedido explícito de nova feature/gráfico |
| `const AGS = [...]` | **gerado a cada rodada** a partir do YAML | toda vez |

Isso é deliberado: o design foi revisado e testado uma vez (ver sessão
2026-08-31); regenerar tudo do zero a cada "Atualiza ag" seria caro e
arriscaria regressão visual sem necessidade. `templates/` só se edita
quando o pedido for de design/feature, nunca como parte deste protocolo.

## Protocolo (passo a passo)

1. **Rodar o build** (PowerShell — não é execução de `.py`/pipeline, não
   precisa pedir autorização extra; ver `.claude/rules/execution-exceptions.md`):

   ```bash
   powershell -File ".claude/skills/atualiza_ag/scripts/build_artifact.ps1"
   ```

   Sem `-OutFile`, escreve em `%TEMP%\ag_explorer_build.html`. O script
   já imprime quantos AGs foram analisados e faz uma checagem cruzada
   barata (contagem via parser vs. `grep '^  - id: AG-'`).

2. **Se o script avisar divergência de contagem, PARAR.** Não publicar
   um parse quebrado. Investigar a entrada mais recente do YAML — o
   parser é line-based (ver "Por que line-based" abaixo), uma entrada
   com indentação fora do padrão pode ter passado batido.

3. **(Recomendado) Capturar o "antes" pra reportar o que mudou** — ler o
   artefato publicado atualmente ANTES de sobrescrever:

   ```
   Artifact(action="read", url="https://claude.ai/code/artifact/795b322a-3201-410f-8dfa-56063bfa7118")
   ```

   Extrair `id`/`status` do HTML devolvido via regex simples
   (`"id":\s*"(AG-[\w-]+)"` seguido do `"status":\s*"([^"]*)"` mais
   próximo) — não precisa reparsear o YAML todo, só comparar a lista de
   ids/status "antes" vs. a nova lista em `AGS` do build fresco. Isso dá
   a base pra dizer "N novos, M mudaram de status" no relatório final.
   Complementar (não substitui) com `git log --oneline -- audit/architecture_gaps_log.yaml`
   pra contexto de quando/por que.

4. **Publicar no MESMO link** — sempre passar `url`, nunca publicar sem
   ele (senão cria um artefato novo/duplicado em vez de atualizar):

   ```
   Artifact(action="publish", file_path="<saída do script>",
            url="https://claude.ai/code/artifact/795b322a-3201-410f-8dfa-56063bfa7118",
            title="Caixa-Preta do Motor", favicon="🛰️")
   ```

5. **Verificação pós-publish** (rápida, via `javascript_tool` num preview
   local ou perguntando à página publicada):
   - `AGS.length` bate com a contagem do passo 1;
   - abrir no mínimo 1 AG novo/alterado na aba Explorar e conferir que o
     texto renderizado bate com o YAML fonte (não só que não quebrou);
   - `read_console_messages(onlyErrors:true)` sem erros, se testado num
     preview local (ver "Testar antes de publicar" abaixo).

6. **Reportar ao usuário**: quantos AGs novos entraram (ids), quantos
   mudaram de status desde a última publicação (ex.: "AG-220 fechou"),
   e o novo total. Não precisa listar os 400+, só o delta.

## Testar antes de publicar (opcional, recomendado se o YAML mudou muito)

Servir o HTML gerado localmente e abrir no Browser pane antes de
sobrescrever o artefato público:

```bash
node "C--...cdc9d6ae.../scratchpad/static_server.js" "." 8843
```

(ou qualquer static server — o arquivo é HTML+JS puro, sem build step).
Se não houver um static server à mão na sessão, publicar direto e
verificar pelo próprio link publicado é aceitável — o risco de regressão
é baixo porque `templates/` não muda neste protocolo.

## Por que line-based (não um parser YAML de verdade)

`architecture_gaps_log.yaml` usa um formato bem regular mas não é YAML
genérico: literais em bloco (`campo: >`) com corpo indentado, sem listas
aninhadas reais dentro dos campos textuais (bullets markdown dentro do
texto são só texto, tratados como conteúdo). Um parser YAML de verdade
resolveria isso de forma mais robusta, mas nenhuma lib YAML está
disponível sem rodar Python (proibido por padrão neste repo) ou puxar
dependência nova. O parser line-based em `build_artifact.ps1` cobre o
formato real observado em 410+ entradas (ver `AGS.length` de cada
rodada) — se o Manager mudar a convenção de indentação/campos do YAML,
ajustar o parser aqui, não presumir que ele generaliza sozinho.

## Gotchas conhecidos

- **IDs não são só `AG-NNN`** — existem `AG-NNN-ADDENDUM`,
  `AG-NNN-ADDENDUM-N`, entradas retificadas (`renumbered_from`), etc. O
  app (`shell_app.js`) já lida com isso via regex tolerante
  (`extractAgRefs`, `idNum`) — não precisa tratamento especial no build.
- **UTF-8 sem BOM em toda etapa.** `build_artifact.ps1` deliberadamente
  NUNCA usa `Out-File -Encoding utf8` do PowerShell 5.1 pra artefato
  intermediário (isso injeta BOM, que quebra `const AGS = <BOM>[...]`
  como token JS). A escrita final usa
  `[System.IO.File]::WriteAllText(..., (New-Object System.Text.UTF8Encoding($false)))`.
  Se algum dia precisar debugar "página em branco" ou erro de parse JS
  logo no início do arquivo, checar BOM primeiro:
  `head -c 5 arquivo.html | od -An -tx1` não deve começar com `ef bb bf`.
- **`severity`/`status`/`found_by` são texto livre, não enum.** O app
  normaliza por heurística de palavra-chave (`severityInfo`/`statusInfo`/
  `foundByInfo` em `shell_app.js`, seção NORMALIZATION) — pega o PIOR
  caso quando o texto combina mais de uma classificação (ex.: "alta
  (achado), média (correção)" → conta como alto). Se o Manager adotar
  vocabulário novo (outro idioma, sigla nova), a heurística pode
  classificar errado — isso é ajuste no `shell_app.js`, não no script de
  build; não é bug de parsing do YAML.
- **Rede de módulos agrega a cauda longa.** Entradas mais recentes têm
  `file`/`related_file` cada vez mais narrativos (lista de artefatos em
  prosa, não um caminho único) em vez de um path limpo — a rede satura
  em ~90 nós "módulo" se não filtrar. `shell_app.js` já cobre isso
  (`NET_TOP_N = 24`, resto agregado em "(outros módulos)") — se o nó
  "outros" crescer desproporcionalmente a cada atualização, é sinal de
  que `moduleOf()` precisa de um heurística melhor, não que o cap está
  errado.

## Quando NÃO é este protocolo

- **Pedido de mudança visual/feature** ("muda a cor de X", "adiciona um
  gráfico de Y", "quero uma aba nova") — isso é edição de `templates/`
  seguida de rebuild, tratado como qualquer pedido de design normal, não
  como "Atualiza ag" de rotina. Depois de editar `templates/`, o mesmo
  `build_artifact.ps1` incorpora a mudança automaticamente na próxima
  rodada (ele sempre lê a versão atual dos templates).
- **`audit/evidence_ledger.yaml` / outros ledgers** — fora de escopo;
  este protocolo é só sobre o artefato Caixa-Preta (que cobre
  especificamente `architecture_gaps_log.yaml`).
- **"Atualize governança"** — protocolo diferente, 7 documentos fixos,
  ver skill `update-governance`. `architecture_gaps_log.yaml` é item 4
  de lá (registrar o achado no YAML); publicar/atualizar o EXPLORADOR
  VISUAL desse mesmo YAML é este protocolo aqui. As duas coisas podem
  ser pedidas juntas ("atualize governança e atualiza ag") sem conflito.
