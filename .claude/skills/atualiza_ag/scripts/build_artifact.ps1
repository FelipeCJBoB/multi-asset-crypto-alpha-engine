<#
.SYNOPSIS
  Reconstrói o artefato "Caixa-Preta do Motor" a partir do estado ATUAL de
  audit/architecture_gaps_log.yaml, usando o shell (HTML/CSS/JS) versionado
  em .claude/skills/atualiza_ag/templates/ -- só o DADO é regerado, o
  design/app não muda a menos que os templates sejam editados à parte.

.PARAMETER RepoRoot
  Raiz do repositório. Default: diretório atual.

.PARAMETER OutFile
  Caminho do HTML final montado. Default: %TEMP%\ag_explorer_build.html.

.EXAMPLE
  powershell -File .claude/skills/atualiza_ag/scripts/build_artifact.ps1
#>
param(
    [string]$RepoRoot = (Get-Location).Path,
    [string]$OutFile = "$env:TEMP\ag_explorer_build.html"
)

$ErrorActionPreference = 'Stop'

$yamlPath   = Join-Path $RepoRoot "audit/architecture_gaps_log.yaml"
$skillDir   = Join-Path $RepoRoot ".claude/skills/atualiza_ag"
$headPath   = Join-Path $skillDir "templates/shell_head.html"
$prefixPath = Join-Path $skillDir "templates/shell_prefix.txt"
$appPath    = Join-Path $skillDir "templates/shell_app.js"

foreach ($p in @($yamlPath, $headPath, $prefixPath, $appPath)) {
    if (-not (Test-Path $p)) { throw "Arquivo esperado não encontrado: $p" }
}

# ============================================================
# 1. Parser YAML -> lista de entries (schema architecture_gaps_log.yaml)
#    Line-based, não um parser YAML genérico -- depende do formato fixo
#    "  - id: AG-NNN" + campos "    campo: valor" / "    campo: >" com
#    corpo em bloco indentado 6 espaços. Ver SKILL.md secao "Por que
#    line-based" antes de trocar por um parser YAML de verdade.
# ============================================================
$lines = Get-Content -Path $yamlPath -Encoding UTF8

$entries  = New-Object System.Collections.Generic.List[object]
$current  = $null
$curField = $null
$buffer   = New-Object System.Collections.Generic.List[string]

function Flush-Field($entry, $field, $buf) {
    if ($null -ne $field) {
        $text = ($buf -join "`n").Trim()
        $entry[$field] = $text
    }
}

foreach ($line in $lines) {
    if ($line -match '^  - id:\s*(.+)\s*$') {
        if ($null -ne $current -and $null -ne $curField) { Flush-Field $current $curField $buffer }
        if ($null -ne $current) { $entries.Add($current) }
        $current = [ordered]@{}
        $current["id"] = $matches[1].Trim().Trim('"')
        $curField = $null
        $buffer = New-Object System.Collections.Generic.List[string]
        continue
    }
    if ($line -match '^    ([a-zA-Z_]+):\s?(.*)$') {
        if ($null -ne $curField) { Flush-Field $current $curField $buffer }
        $fname = $matches[1]
        $rest = $matches[2].TrimEnd()
        if ($rest -eq '' -or $rest -eq '>' -or $rest -eq '|' -or $rest -eq '>-' -or $rest -eq '|-' -or $rest -eq '>+' -or $rest -eq '|+') {
            $curField = $fname
            $buffer = New-Object System.Collections.Generic.List[string]
        } else {
            $val = $rest.Trim()
            if ($val.Length -ge 2 -and $val.StartsWith('"') -and $val.EndsWith('"')) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            if ($val -eq 'null') { $val = $null }
            if ($null -ne $current) { $current[$fname] = $val }
            $curField = $null
        }
        continue
    }
    if ($null -ne $curField -and $null -ne $current) {
        if ($line -match '^\s*$') { $buffer.Add('') }
        elseif ($line -match '^      (.*)$') { $buffer.Add($matches[1]) }
        else { $buffer.Add($line.TrimStart()) }
    }
}
if ($null -ne $current) {
    if ($null -ne $curField) { Flush-Field $current $curField $buffer }
    $entries.Add($current)
}

$parsedCount = $entries.Count
Write-Host "[1/3] AGs analisados no YAML: $parsedCount"

# checagem cruzada barata contra o próprio arquivo -- se divergir, o
# parser line-based provavelmente quebrou num formato novo de entrada
$grepCount = (Select-String -Path $yamlPath -Pattern '^  - id: AG-').Count
if ($grepCount -ne $parsedCount) {
    Write-Warning "Contagem via parser ($parsedCount) != contagem via grep de '- id: AG-' ($grepCount). Investigar antes de publicar -- ver SKILL.md 'Verificação pós-build'."
}

$json = $entries | ConvertTo-Json -Depth 6

# ============================================================
# 2. Monta o HTML final em memória (sem BOM em nenhum passo)
# ============================================================
$head   = Get-Content -Path $headPath   -Raw -Encoding UTF8
$prefix = Get-Content -Path $prefixPath -Raw -Encoding UTF8
$app    = Get-Content -Path $appPath    -Raw -Encoding UTF8

$final = $head + $prefix + $json + "`n;`n" + $app + "`n</script>`n"

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($OutFile, $final, $utf8NoBom)

$sizeMB = [Math]::Round((Get-Item $OutFile).Length / 1MB, 2)
Write-Host "[2/3] Artefato montado: $OutFile ($sizeMB MB)"
Write-Host "[3/3] Próximo passo: abrir/publicar $OutFile com a ferramenta Artifact usando a URL salva em SKILL.md (campo 'Artifact URL')."
