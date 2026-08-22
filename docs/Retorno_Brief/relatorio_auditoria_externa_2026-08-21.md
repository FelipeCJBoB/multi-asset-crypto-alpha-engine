# Relatório de Auditoria Externa Definitivo (Pós-Sabatina Técnica)

**Referência:** AG-124 — Recalibração Causal do Threshold Dollar-Bar  
**Data:** 2026-08-21  
**Para:** Comitê de Arquitetura e Engenharia Quantitativa / Manager do Projeto  
**Documentos Canônicos:** `PLANO_MESTRE_PRINCE2.md` e `ADR-001`  
**Documentos de Entrada:** `brief_auditoria_externa_2026-08-21_calibracao_causal_dollar_bar_ag124.md` e Respostas Técnicas da Equipe (2026-08-21)  
**Status do Parecer:** **APROVAÇÃO RATIFICADA PARA MODELO 7/7 COM REPROCESSAMENTO PROGRAMADO**

---

## 0. Resumo Executivo e Veredito Final Pós-Sabatina

A sabatina técnica com a engenharia e governança quantitativa trouxe clareza definitiva sobre as restrições reais de código e o cronograma do projeto:

```
                                  MATRIZ DE DECISÃO INTEGRADA
┌───────────────────────────────┬───────────────────────────────────┬──────────────────────────────────────────┐
│ Dimensão Analisada            │ Resposta Técnica / Fato de Código │ Veredito da Auditoria Externa            │
├───────────────────────────────┼───────────────────────────────────┼──────────────────────────────────────────┤
│ 1. Aliasing Semanal (W=7)     │ Confirmado (sábado ~0.59x em BTC) │ ✅ VALIDADO: 7 dias é o período ótimo.   │
│ 2. Cadência (7/7 vs 7/1)      │ `threshold_bars_finish` trunca    │ 🔒 RATIFICADO 7/7: Evita 365 micro-barras│
│ 3. Bad Prints / Outliers      │ Não filtrado antes da barra       │ ⚠️ NOVO TICKET (AG-125): Criar guarda.   │
│ 4. Cronograma de Reprocessar  │ Alpha retrain bloqueado no Data L.│ ⏳ AGUARDAR: Reprocessar com Data Layer. │
│ 5. Métrica Canônica Sucesso   │ Em aberto no Comitê Quant         │ 🎯 TRAVAR: Excesso de Curtose (κ) e CV(N)│
└───────────────────────────────┴───────────────────────────────────┴──────────────────────────────────────────┘
```

---

## 1. Análise Crítica dos 10 Pontos da Sabatina

### 🛠️ Eixo Engenharia & Microestrutura

#### 1. Gestão de Carry na Transição de Período (`threshold_bars_finish`)
* **Fato Revelado:** A função `build_dollar_bars_for_window` invoca `threshold_bars_finish(carry)` ao final de cada janela, forçando a emissão do resíduo como uma barra incompleta (*short bar*).
* **Impacto Arquitetural:** 
  - Se adotássemos cadência diária ($T_c = 1$), geraríamos **365 barras truncadas por ano por símbolo** (~2% do volume amostrado sob distorção de threshold).
  - Com o modelo **$T_w=7, T_c=7$**, esse efeito colateral é restrito a apenas **~52 ocorrências por ano**.
* **Decisão da Auditoria:** Este fato técnico de código **ratifica o modelo $7/7$ como a escolha mais segura e limpa** no estado atual da base de código, superando a alternativa diária sem necessidade de refatorar o acumulador de carry.

#### 2. Estresse de Memória em Rajadas de 14x–15x
* **Fato Revelado:** O benchmark mais próximo atingiu ~27GB RSS sob configuração multi-resolução, mas rajadas instantâneas de 14x no novo orquestrador ainda não foram testadas isoladamente.
* **Ação Obrigatória:** Executar um teste sintético de estresse simulando 15x a taxa média antes de disparar o lote histórico completo, garantindo que o chunking por período não exceda o limite de RAM do host.

#### 3. Paridade Lote vs. Streaming e Cold-Start
* **Fato Revelado:** O diretório `src/live/` está vazio; execução em tempo real é escopo futuro.
* **Recomendação:** Registrar no ADR-001 que o futuro módulo live deverá implementar warm-up causal via REST API cobrindo $[now - 7d, now)$ antes de subscrever aos WebSockets.

#### 4. Filtragem de *Bad Prints* e Outliers (Vulnerabilidade Descoberta)
* **Fato Revelado:** `build_dollar_bars_for_window` consome os trades brutos direto do lake (`query_agg_trades`) sem validação prévia. O `check_price_deviation` roda apenas *a posteriori* no Data Quality Engine.
* **Risco Real:** Um único trade corrompido com volume aberrante (ex: $1B falso) fragmenta e fecha dezenas de barras fantasmas instantaneamente.
* **Ação Recomendada:** **Abrir ticket imediato (sugestão: `AG-125`)** para incluir um filtro de sanidade de preço/volume antes da chamada a `threshold_bars_step`.

#### 5. Eficiência de Armazenamento da Coluna `threshold_quote`
* **Fato Revelado:** A escrita usa compressão `zstd` padrão do Polars/Arrow sem dictionary encoding explícito.
* **Parecer:** Como o valor de `threshold_quote` é estritamente constante ao longo de cada período de 7 dias, o compressor `zstd` atinge taxa de entropia próxima de zero para essa coluna, tornando o overhead de disco desprezível.

---

### 📊 Eixo Governança & Modelagem

#### 1. Modelos Downstream e Tempo de Informação (AG-036)
* **Fato Revelado:** O ticket `AG-036` documenta um contrato legado de estimador de volatilidade que ainda exige `horizon_minutes == bars.timeframe_minutes`.
* **Parecer:** Como a remediação do AG-036 ocorrerá quando o Learner remedir M1 sob a grade nova, a migração para dollar bars causais isola a grade de dados e prepara o terreno para o ajuste do estimador.

#### 2. Parametrização Global vs. Específica por Ativo
* **Decisão Ratificada:** Recomenda-se formalmente **adotar o hiperparâmetro global rígido de 7 dias ($T_w=7, T_c=7$) para todos os 5 ativos**. Isso blinda o pipeline contra *data snooping* e preserva o orçamento de testes da disciplina $N_{lifetime}$.

#### 3. Interação com o Embargo do CPCV
* **Fato Revelado:** O embargo atual (~4 dias) protege a autocorrelação do rótulo, mas não foi desenhado pensando na dependência induzida pela janela de calibração de 7 dias.
* **Parecer:** Como a calibração é estritamente passada ($[t-7d, t-1d]$), não há vazamento do futuro para o passado. Contudo, para folds de validação cruzada contíguos, recomenda-se que o embargo entre treino e teste seja ajustado para $\ge 7$ dias quando a nova grade estiver ativa.

#### 4. Cronograma de Reprocessamento (Timing Ótimo)
* **Fato Revelado:** O retreino do Alpha está condicionado à finalização de todos os 9 estágios do Data Layer, sem urgência de prazo imediata.
* **Recomendação Estratégica:** **Não reprocessar os 6+ anos isoladamente hoje.** A decisão de desenho $7/7$ deve ser travada e o código congelado, executando o reprocessamento pesado em conjunto com o fechamento do Data Layer e o ticket de Bad Prints.

#### 5. Métrica Canônica de Sucesso Pós-Migração
Recomenda-se ao Comitê Quant registrar como critérios formais de aceitação:
1. **Redução do Excesso de Curtose ($\kappa$):** $\kappa_{\text{retornos}}(\text{dollar}) < \kappa_{\text{retornos}}(\text{time 15m})$.
2. **Estabilidade Amostral:** Coeficiente de variação diário da contagem de barras $CV_N = \frac{\sigma(N)}{\mu(N)} \le 0.40$.

---

## 2. Síntese do Desenho Técnico Travado

```python
# Configuração Canônica Ratificada pela Auditoria Externa (AG-124)
CALIBRATION_CONFIG = {
    "trailing_window_days": 7,      # Neutraliza 100% da sazonalidade semanal (SMA-7 notch filter)
    "cadence_days": 7,              # Minimiza truncamento de carry (apenas ~52 short-bars/ano)
    "carry_handling": "finish_bar", # threshold_bars_finish em cada fronteira de período
    "asset_scope": "GLOBAL_ALL_5",  # BTC, ETH, SOL, BNB, XRP sem overfitting individual
    "compression": "zstd",          # Polars/Arrow Parquet writer
}
```

---

## 3. Insights Estruturais e Brainstorming de Engenharia Quantitativa

Abaixo estão 5 insights aprofundados desenvolvidos durante o processo de auditoria que agregam valor preventivo e estratégico ao motor de trading:

### 💡 Insight 1: O Fenômeno dos "Mega-Trades" e Barras de Retorno Zero
* **Cenário:** Ocorrência de um trade individual institucional ou liquidação em cascata cujo volume é maior que o próprio `threshold_usdt` do período (ex: ordem de \$2.5M sob threshold de \$500k).
* **Comportamento do Acumulador:** O operador `cum_value // threshold` emitirá múltiplas barras no mesmo microsegundo com $O=H=L=C$ e retorno $\Delta p = 0$.
* **Recomendação:** Incluir no `AG-125` uma regra de microestrutura para marcar barras originadas de subdivisão de um único trade (`is_subdivided_trade=True`), evitando que estimadores de volatilidade e filtros CUSUM sofram com colapso de variância temporal ($\Delta t = 0$).

### 💡 Insight 2: *Lead-In Padding* para Eliminar a Perda de Histórico no Cold-Start
* **Cenário:** O descarte do primeiro bloco $[start, start + 7d)$ no `build_dollar_bars_walkforward` resulta na perda da primeira semana de janeiro/2020.
* **Solução:** Configurar a query de ingestão de trades brutos para iniciar com um *lead-in buffer* de 7 dias antes do marco oficial (ex: buscar trades desde `2019-12-25`). O período $[2019\text{-}12\text{-}25, 2019\text{-}12\text{-}31]$ é usado exclusivamente para calibrar a primeira semana de 2020, permitindo que a base útil comece exatamente em `2020-01-01 00:00:00 UTC` com 100% de dados aproveitados.

```
Ingestão de Trades: [--- 2019-12-25 a 2019-12-31 (Lead-In) ---] [=== 2020-01-01 em diante ===]
Aplicação:          |------------ Calibra a 1ª Semana ---------->| Grava Barras (Zero Perda)
```

### 💡 Insight 3: Protocolo de Healthcheck Estatístico Automatizado
Script de validação automatizado para ser executado imediatamente após o reprocessamento de 6+ anos:
```python
def validate_reprocessed_dollar_bars(df_bars: pl.DataFrame, df_time_bars_15m: pl.DataFrame) -> dict:
    return {
        # 1. Normalidade: Curtose das dollar bars deve ser inferior à das time bars
        "kurtosis_pass": kurtosis(df_bars["log_ret"]) < kurtosis(df_time_bars_15m["log_ret"]),
        
        # 2. Estacionariedade da Densidade: Contagem diária de barras deve ser estacionária (ADF p < 0.05)
        "density_stationary": adfuller(df_bars.group_by_day().count())[1] < 0.05,
        
        # 3. Integridade de Schema: Nenhuma barra com threshold_quote nulo ou não-positivo
        "schema_intact": df_bars["threshold_quote"].null_count() == 0 and (df_bars["threshold_quote"] > 0).all(),
        
        # 4. Gaps Anômalos: Nenhum intervalo entre trades > 24h sem evento catalogado
        "max_gap_hours": df_bars["duration_seconds"].max() / 3600 < 24.0,
    }
```

### 💡 Insight 4: Sincronização do *Triple Barrier Method* com o Tempo de Informação
* **Cenário:** O método de rotulagem por Tripla Barreira (López de Prado) usa uma barreira vertical de expiração temporal.
* **Recomendação:** A barreira vertical deve ser parametrizada em **número de dollar bars** (ex: `holding_bars = 20`) em vez de minutos físicos fixos. Isso garante que trades abertos em períodos de calmaria de volume não expirem prematuramente por falta de fluxo de ordens.

### 💡 Insight 5: A Série de `threshold_quote` como Feature Macro de Regime
* **Insight de Alpha:** A evolução histórica de `threshold_quote` representa a profundidade estrutural do mercado. O ratio $\frac{\text{Volume\_Intradiário}}{\text{threshold\_quote}}$ opera como um z-score de liquidez instantânea em tempo real, servindo como feature preditiva para modelos de meta-labeling e dimensionamento de posição (*bet sizing*).

---

## 4. Plano de Ação e Próximos Passos

1. **Formalização de Decisão:** Registrar no `PLANO_MESTRE_PRINCE2.md` o encerramento da decisão AG-124 com a trava em $7/7$ global.
2. **Abertura de Ticket de Mitigação (`AG-125`):** Implementar filtro de sanidade para trades brutos antes de `threshold_bars_step` e flag para *Mega-Trades*.
3. **Inclusão do Lead-In Buffer:** Ajustar a query de ingestão para `start_date - 7 days` a fim de preservar o início de 2020.
4. **Execução Programada:** Rodar o reprocessamento histórico de 6+ anos em conjunto com a conclusão dos 9 estágios do Data Layer.
