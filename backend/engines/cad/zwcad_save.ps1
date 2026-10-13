param([Parameter(Mandatory=$true)][string]$JobPath)
$ErrorActionPreference = 'Stop'
$job = Get-Content -LiteralPath $JobPath -Raw -Encoding UTF8 | ConvertFrom-Json
$cad = $null
$doc = $null
$previous = $null
$result = @{success=$false}
function Invoke-CadCall([scriptblock]$Action) {
    for ($attempt=0; $attempt -lt 120; $attempt++) {
        try { return (& $Action) }
        catch {
            if ($_.Exception.HResult -notin @(-2147418111, -2147417846)) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
    throw 'ZWCAD is busy. Close modal dialogs and retry.'
}
try {
    if (Test-Path -LiteralPath $job.target) { throw 'Output already exists.' }
    try { $cad = [Runtime.InteropServices.Marshal]::GetActiveObject($job.progid) }
    catch { $cad = New-Object -ComObject $job.progid; $cad.Visible = $true }
    try { $previous = $cad.ActiveDocument } catch {}
    foreach ($opened in $cad.Documents) {
        if ($opened.FullName -and [IO.Path]::GetFullPath($opened.FullName) -eq [IO.Path]::GetFullPath($job.source)) {
            throw 'The input DXF is already open in ZWCAD. Close that drawing before retrying.'
        }
    }
    $doc = Invoke-CadCall { $cad.Documents.Open($job.source, $true) }
    $result.source_entities = Invoke-CadCall { $doc.ModelSpace.Count }
    $result.zwcad_version = $cad.Version
    Invoke-CadCall { $doc.SaveAs($job.target) } | Out-Null
    Invoke-CadCall { $doc.Close($false) } | Out-Null
    $doc = $null
    $doc = Invoke-CadCall { $cad.Documents.Open($job.target, $true) }
    $result.saved_entities = Invoke-CadCall { $doc.ModelSpace.Count }
    $result.success = $true
} catch {
    $result.error = $_.Exception.Message
} finally {
    if ($null -ne $doc) { try { $doc.Close($false) } catch { $result.success=$false; $result.error=$_.Exception.Message } }
    if ($null -ne $previous) { try { $previous.Activate() } catch {} }
    # Never quit a user's CAD session or close any document we did not open.
    $result | ConvertTo-Json | Set-Content -LiteralPath $job.result -Encoding UTF8
}
if (-not $result.success) { exit 1 }
