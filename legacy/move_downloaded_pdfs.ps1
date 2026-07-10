<#
.SYNOPSIS
  Capital IQ에서 다운로드된 earnings transcript PDF를 표준 폴더 구조로 이동한다.

.DESCRIPTION
  Downloads 폴더에서 -Since 이후 생성된 "*_Earnings Call_*.pdf" 파일을 찾아
  " (n)" 중복 접미사를 정리하고, 동일 크기의 중복 파일을 제거한 뒤
  E:\Earnings\transcripts\[회사명 (티커)]\ 로 이동하고 manifest.csv에 기록한다.

.EXAMPLE
  .\move_downloaded_pdfs.ps1 -Company "Trip.com Group" -Ticker "TCOM" -Since "2026-07-09T10:00:00+09:00"
#>
param(
    [Parameter(Mandatory = $true)][string]$Company,
    [Parameter(Mandatory = $true)][string]$Ticker,
    [Parameter(Mandatory = $true)][string]$Since,
    [string]$DownloadsDir = "$env:USERPROFILE\Downloads",
    [string]$DestRoot = "E:\Earnings\transcripts",
    [string]$FilePattern = "*_Earnings Call_*.pdf"
)

$ErrorActionPreference = "Stop"
$sinceTime = [datetime]::Parse($Since)

$destDir = Join-Path $DestRoot ("{0} ({1})" -f $Company, $Ticker)
New-Item -ItemType Directory -Force $destDir | Out-Null
$manifestPath = Join-Path $destDir "manifest.csv"

# 다운로드가 아직 진행 중인 파일(.crdownload)이 있으면 대기
$deadline = (Get-Date).AddSeconds(60)
while ((Get-ChildItem $DownloadsDir -Filter "*.crdownload" -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
}

$candidates = Get-ChildItem $DownloadsDir -Filter $FilePattern -File |
    Where-Object { $_.LastWriteTime -gt $sinceTime } |
    Sort-Object LastWriteTime

if (-not $candidates) {
    Write-Output "NO_FILES: '$FilePattern' matching files newer than $Since in $DownloadsDir"
    exit 0
}

# " (1)", " (2)" 접미사를 제거한 정규 이름 기준으로 그룹핑, 같은 크기는 중복으로 간주
$groups = $candidates | Group-Object {
    ($_.BaseName -replace ' \(\d+\)$', '') + $_.Extension
}

$moved = @()
$skipped = @()

foreach ($g in $groups) {
    $canonicalName = $g.Name
    # 같은 정규 이름 내에서 크기별로 하나만 남긴다 (재다운로드 중복 제거)
    $unique = @($g.Group | Sort-Object Length -Unique)
    $g.Group | Where-Object { $unique.FullName -notcontains $_.FullName } | ForEach-Object {
        $skipped += [pscustomobject]@{ File = $_.Name; Reason = "duplicate download (same size)" }
        Remove-Item $_.FullName -Confirm:$false
    }

    foreach ($f in $unique) {
        $destPath = Join-Path $destDir $canonicalName

        if (Test-Path $destPath) {
            $existing = Get-Item $destPath
            if ($existing.Length -eq $f.Length) {
                $skipped += [pscustomobject]@{ File = $canonicalName; Reason = "already exists (same size)" }
                Remove-Item $f.FullName -Confirm:$false
                continue
            }
            # 같은 이름, 다른 크기 → 버전 접미사를 붙여 보존
            $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
            $destPath = Join-Path $destDir ("{0}_{1}{2}" -f [IO.Path]::GetFileNameWithoutExtension($canonicalName), $stamp, $f.Extension)
        }

        Move-Item $f.FullName $destPath
        $item = Get-Item $destPath
        $moved += [pscustomobject]@{
            File         = $item.Name
            OriginalName = $f.Name
            SizeBytes    = $item.Length
            MovedAt      = (Get-Date -Format o)
        }
    }
}

if ($moved) {
    $writeHeader = -not (Test-Path $manifestPath)
    $csv = $moved | ConvertTo-Csv -NoTypeInformation
    if (-not $writeHeader) { $csv = $csv | Select-Object -Skip 1 }
    $csv | Out-File -Append -Encoding utf8 $manifestPath
}

Write-Output ("MOVED: {0}  SKIPPED: {1}  DEST: {2}" -f $moved.Count, $skipped.Count, $destDir)
if ($moved) { $moved | Format-Table File, SizeBytes -AutoSize | Out-String | Write-Output }
if ($skipped) { $skipped | Format-Table File, Reason -AutoSize | Out-String | Write-Output }
