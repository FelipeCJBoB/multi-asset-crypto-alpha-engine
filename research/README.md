# research/

**Grau de pesquisa. Sem `registry.yaml`, sem `causal_proof`, sem teste de
paridade lote↔streaming. Não usar em produção.**

Arquivado aqui em 2026-08-09 (movido de `src/features/`), critério do
Manager: "se sumisse, quanto custaria refazer" — não "isto foi útil".
Refazer custaria dias, não semanas, porque as fórmulas das ~70 candidatas
T2 já estão documentadas no PRD (§2.2-2.12); mesmo assim, custa, e o
código já existe e já foi verificado manualmente contra dado real
(2024, `n_finite` plausível), então fica.

## Conteúdo

- `research_t2.py` — as ~70 candidatas T2 computáveis (grupos A/B/C/D/E/H/K),
  passe de pesquisa da Faixa 2 E2. Toda janela é causal (rolante com `t`
  incluído, ou expansiva estrita `< t`), reusando primitivos de
  `src.features.support` — essa parte não é cerimônia, é correção, e se
  preserva mesmo fora de produção.
- `_sources_research.py` — carregadores de fonte aditivos (metrics com
  posicionamento, BVOL, CSV on-chain) que `src/features/_sources.py` de
  produção não usa.

## Por que não está em `src/features/`

Está fora de `root_packages = ["src"]` do `import-linter` de propósito —
este código nunca foi pensado pra obedecer a hierarquia de camadas de
produção (§14.2), e forçá-lo pra dentro só pra "ficar arrumado" esconderia
que ele não passou pela cerimônia completa (`registry.yaml`,
`causal_proof`, paridade). Quem usa isto hoje: `src/analysis/
faixa2_e2_research.py` (passe de pesquisa, `experiments/
faixa2_e2_research.json`) e `tests/unit/test_features_research_t2.py`.

## Se uma candidata for promovida

Ela sai daqui, ganha implementação em `src/features/groups/`, entrada em
`src/features/registry.yaml` com `causal_proof`, e o teste de paridade
lote↔streaming do Definition of Done (`CLAUDE.md`). Não se edita o
arquivo aqui no lugar — o research-grade original fica, como registro do
que foi tentado.
