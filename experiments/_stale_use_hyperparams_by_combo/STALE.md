# Artefatos stale de `use_hyperparams_by_combo` (AG-227)

**Achado 2026-08-27 (handoff de `src/models/`), validado nesta sessão.**

`_smoketest_production_wiring_BNBUSDT_R3.json` foi gerado pelo smoke test
end-to-end de `AG-227` ("FECHADO 2026-08-25") — a primeira aplicação real
de `use_hyperparams_by_combo`. Confirmado por comparação direta contra o
`config_hash` REAL de hoje (`data/labels/BNBUSDT/R3/v1/labels.parquet` ->
`ff8dcb98fa579975`): o artefato guarda `labels_config_hash =
a554e71d5437efdc`, que não bate com o hash atual. O label config mudou
desde que este artefato foi gerado (relabel `AG-221`, purge remedido
`AG-298`, ou ambos — não confirmado qual isoladamente; o que É confirmado
é que o número não é mais válido).

**Não trate os números deste arquivo como representativos do motor de
hoje.** Re-rodar `BNBUSDT/R3` sob `use_hyperparams_by_combo=True` com os
labels/purge atuais produz um `labels_config_hash` diferente deste — é
assim que se confirma que a remediação está completa (ver `AG-260`
addendum / handoff `AG-296`-`AG-297`, item 4).

**Sobre o artefato equivalente de `BTCUSDT/R3` citado no handoff
original:** não localizado nesta sessão. O texto de `AG-227` registra que
a primeira tentativa (`BTCUSDT/R3`) colidiu de propósito com um artefato
já existente (`ArtifactExistsError`, guarda de imutabilidade) — é
possível que nenhum artefato NOVO tenha sido persistido por essa
tentativa específica. `models/BTCUSDT/R3/alpha_c1_v1/diagnostics/`
existe em disco, mas não guarda `config_hash` por fold (verificado) e não
foi possível atribuí-lo com confiança a esta rodada específica vs. um
retreino posterior válido — não movido/marcado por precaução (risco de
esconder trabalho real se a atribuição estiver errada). Revisão manual
recomendada antes de confiar nesses diagnostics também.

**Ação real de remediação**: re-rodar os combos afetados sob
`use_hyperparams_by_combo=True` com o label config atual — previsto para
acontecer como parte do retreino real das 15 combinações já autorizado
pelo Manager (ver `AG-298`/`AG-207`), não uma ação isolada.
