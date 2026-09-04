# Exceções de execução — comandos que Claude pode rodar direto

Referenciado por `CLAUDE.md` §"Execução — quem roda o quê". Claude nunca
executa `.py` nem comando que rode código Python (`uv run quant ...`,
`uv run pytest`, `python -m ...`) via Bash/PowerShell, exceto autorização
explícita do Manager na sessão, ou a exceção nomeada abaixo.

Liberado sem restrição (não é execução de Python): `git`, leitura/listagem
de arquivo, `grep`/`rg`.

## Exceção nomeada — 7 comandos mecânicos de auditoria

Só leitura, sem efeito em dado/exchange/trial. Autorização do Manager,
2026-08-12.

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
parar e reportar, não presumir que a exceção ainda vale.

Motivo/detalhe: histórico em `git log -- CLAUDE.md`, usado por
`.claude/skills/audit_engineering/` e `.claude/skills/project_assurance/`.

## Adendo 2026-09-04 — 8º comando liberado

`python tools/lint/check_provenance_numbers.py` entra na lista das exceções
mecânicas de auditoria (AG-440). Mesma categoria dos outros 7: só leitura,
sem efeito em dado/exchange/trial — lê `config/constants.yaml` e compara
números citados na prosa de `source:` contra o `value:` vigente.
