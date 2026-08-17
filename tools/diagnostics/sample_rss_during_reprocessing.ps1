# Instrumentação de RSS pra tentativa real de reprocessamento (AG-034
# addendum, 2026-08-16, recomendação item 3: "instrumentação de RSS real
# por processo continua sendo o passo humano central... PENDENTE-DE-
# EXECUCAO-HUMANA" -- este script É esse passo, não substitui a
# recomendação original, só a torna executável sem precisar ficar
# olhando o Gerenciador de Tarefas manualmente).
#
# Roda em um terminal SEPARADO, em paralelo ao `uv run python -m
# src.analysis.m2_bar_comparison ...` real -- amostra RSS (WorkingSet64)
# de todo processo `python` a cada 5s, soma o agregado (a hipótese de
# AG-034 é sobre SOMA de até 12 processos concorrentes, não 1 processo
# isolado -- `SET memory_limit` do DuckDB só governa o buffer interno de
# CADA conexão, não a RSS total do host) + memória disponível do sistema
# (pra distinguir "Python cresceu" de "SO inteiro sob pressão").
#
# Uso:
#   powershell -File tools\diagnostics\sample_rss_during_reprocessing.ps1 `
#     -OutPath experiments\rss_sample_btc_2020.csv -IntervalSeconds 5
#
# Ctrl+C pra parar quando o run real terminar (ou travar -- os dados já
# gravados até o ponto do travamento são o achado mais importante:
# tendência de crescimento vs. plato vs. salto abrupto).

param(
    [Parameter(Mandatory = $true)]
    [string]$OutPath,

    [int]$IntervalSeconds = 5
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $OutPath)) {
    "timestamp,n_python_processes,total_rss_mb,per_process_rss_mb,available_memory_mb" |
        Out-File -FilePath $OutPath -Encoding utf8
}

Write-Host "Amostrando RSS a cada $IntervalSeconds s -> $OutPath (Ctrl+C pra parar)"

while ($true) {
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    $procs = Get-Process python -ErrorAction SilentlyContinue
    $n = if ($procs) { @($procs).Count } else { 0 }
    $totalMb = if ($procs) { [math]::Round(($procs | Measure-Object -Property WorkingSet64 -Sum).Sum / 1MB, 1) } else { 0 }
    $perProcess = if ($procs) { ($procs | ForEach-Object { [math]::Round($_.WorkingSet64 / 1MB, 1) }) -join ";" } else { "" }
    $availableMb = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB, 1)

    "$timestamp,$n,$totalMb,""$perProcess"",$availableMb" | Out-File -FilePath $OutPath -Append -Encoding utf8

    Start-Sleep -Seconds $IntervalSeconds
}
