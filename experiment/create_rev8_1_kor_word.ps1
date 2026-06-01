$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = "C:\Users\morophi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Source = Join-Path $Root "experiment\lacp_ijibc_rev8.1.docx"
$Output = Join-Path $Root "experiment\lacp_ijibc_rev8.1_kor.docx"
$PayloadScript = Join-Path $Root "experiment\export_rev8_1_kor_payload.py"

$env:PYTHONIOENCODING = "utf-8"
$payloadJson = & $Python $PayloadScript
$payload = $payloadJson | ConvertFrom-Json

Copy-Item -LiteralPath $Source -Destination $Output -Force

function Split-MarkedText {
    param([string]$Text)

    $segments = New-Object System.Collections.Generic.List[object]
    $plain = New-Object System.Text.StringBuilder
    $i = 0

    while ($i -lt $Text.Length) {
        $start = $Text.IndexOf("**", $i)
        if ($start -lt 0) {
            [void]$plain.Append($Text.Substring($i))
            break
        }

        if ($start -gt $i) {
            [void]$plain.Append($Text.Substring($i, $start - $i))
        }

        $end = $Text.IndexOf("**", $start + 2)
        if ($end -lt 0) {
            [void]$plain.Append($Text.Substring($start))
            break
        }

        $boldText = $Text.Substring($start + 2, $end - $start - 2)
        $boldStart = $plain.Length
        [void]$plain.Append($boldText)
        $segments.Add([pscustomobject]@{ Start = $boldStart; Length = $boldText.Length }) | Out-Null
        $i = $end + 2
    }

    [pscustomobject]@{ Plain = $plain.ToString(); Bold = $segments }
}

function Set-WordRangeText {
    param(
        [object]$Document,
        [object]$Range,
        [string]$Text
    )

    $parsed = Split-MarkedText -Text $Text
    $Range.Text = $parsed.Plain
    $Range.Font.NameFarEast = "Malgun Gothic"

    foreach ($segment in $parsed.Bold) {
        if ($segment.Length -le 0) { continue }
        $boldRange = $Document.Range($Range.Start + $segment.Start, $Range.Start + $segment.Start + $segment.Length)
        $boldRange.Font.Bold = 1
    }
}

$word = $null
$document = $null

try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3

    $document = $word.Documents.Open($Output, $false, $false, $false)

    $bodyParagraphs = New-Object System.Collections.Generic.List[object]
    foreach ($p in $document.Paragraphs) {
        if (-not $p.Range.Information(12)) {
            $bodyParagraphs.Add($p) | Out-Null
        }
    }

    foreach ($prop in $payload.PARA.PSObject.Properties) {
        $idx = [int]$prop.Name
        $paragraph = $bodyParagraphs[$idx]
        $range = $paragraph.Range
        $range.End = $range.End - 1
        Set-WordRangeText -Document $document -Range $range -Text ([string]$prop.Value)
    }

    foreach ($tableProp in $payload.TABLES.PSObject.Properties) {
        $tableIndex = [int]$tableProp.Name
        $table = $document.Tables.Item($tableIndex + 1)
        $rows = $tableProp.Value

        for ($r = 0; $r -lt $rows.Count; $r++) {
            for ($c = 0; $c -lt $rows[$r].Count; $c++) {
                $cell = $table.Cell($r + 1, $c + 1)
                $range = $cell.Range
                $range.End = $range.End - 1
                Set-WordRangeText -Document $document -Range $range -Text ([string]$rows[$r][$c])
            }
        }
    }

    $document.SaveAs2($Output, 12)
    $document.Close($false)
    $word.Quit()
    Write-Output $Output
}
finally {
    if ($document -ne $null) {
        try { $document.Close($false) | Out-Null } catch {}
    }
    if ($word -ne $null) {
        try { $word.Quit() | Out-Null } catch {}
    }
}
