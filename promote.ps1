<#
.SYNOPSIS
SEOHYUN Promote Manager (PowerShell)

.DESCRIPTION
Promote WORK version folder to:   <RunRoot>\releases\<Version>
Flow: PreDiff -> (Backup optional) -> Staging Copy -> Verify (SHA256) -> Commit -> (SwitchCurrent optional)

P0 rules:
    - DryRun is stateless (NO mkdir/copy/delete/zip/log)
    - Concurrency lock
    - Path safety (no root, no traversal, must stay under RunRoot)
    - VerifyHashAfterCopy default ON
    - Exclude dangerous dirs (.venv/.vscode/.git/__pycache__ etc.)

.EXAMPLE
pwsh -ExecutionPolicy Bypass -File .\tools\promote.ps1 -RunRoot D:\SEOHYUN_SYSTEM\WORK -Src D:\SEOHYUN_SYSTEM\WORK\v2.3 -Version v2.3 -DryRun

.EXAMPLE
pwsh -ExecutionPolicy Bypass -File .\tools\promote.ps1 -RunRoot D:\SEOHYUN_SYSTEM\WORK -Src D:\SEOHYUN_SYSTEM\WORK\v2.3 -Version v2.3 -Backup -SwitchCurrent
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$RunRoot,

    [Parameter(Mandatory=$true)]
    [string]$Src,

    [string]$Version = "",

    [switch]$DryRun,

    # Backup은 기본 ON이어야 하므로 switch가 아니라 bool로 둔다
    [bool]$Backup = $true,

    [switch]$SwitchCurrent,

    [switch]$Force,

    [bool]$VerifyHashAfterCopy = $true,

    [switch]$PostCheck,

    [int]$PostCheckTimeoutSec = 120,

    # Required 체크는 "버전 폴더 구조가 고정이 아님"이 확정이므로 기본 OFF
    [bool]$SkipRequiredCheck = $true,

    # 기본은 빈 목록(체크 자체를 사실상 무력화)
    [string[]]$RequiredRelPaths = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------
# Safe init (catch에서 사용될 수 있으므로 선초기화)
# ---------------------------
$RunRootFull = $null
$SrcFull     = $null
$Stage       = "INIT"
$Reason      = ""
$RollbackSavedAt = ""
$PostCheckResult = $null

# ---------------------------
# Basic helpers
# ---------------------------
function NowStamp() { return (Get-Date).ToString("yyyy-MM-dd HH:mm:ss") }
function StampId()  { return (Get-Date).ToString("yyyyMMdd_HHmmss") }

function Write-Head([string]$msg) {
    Write-Host ""
    Write-Host ("=== {0} ===" -f $msg)
}

function Ensure-Dir([string]$p) {
    if ($DryRun) { return }
    if (-not (Test-Path -LiteralPath $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
}

function Resolve-FullPath([string]$p) { return (Resolve-Path -LiteralPath $p).Path }

function FullPathNoExist([string]$p) {
    return [System.IO.Path]::GetFullPath($p)
}

function Ensure-TrailingSlash([string]$p) {
    if ([string]::IsNullOrWhiteSpace($p)) { return $p }
    $sep = [System.IO.Path]::DirectorySeparatorChar
    if ($p.EndsWith($sep)) { return $p }
    return $p + $sep
}

function Assert-NotRootPath([string]$p, [string]$label) {
    $full = FullPathNoExist $p
    $root = [System.IO.Path]::GetPathRoot($full)
    if ((Ensure-TrailingSlash $full).Equals((Ensure-TrailingSlash $root), [StringComparison]::OrdinalIgnoreCase)) {
        throw "UNSAFE PATH ($label): root path not allowed => $full"
    }
}

function Assert-UnderBase([string]$base, [string]$child, [string]$label) {
    $baseFull  = Ensure-TrailingSlash (FullPathNoExist $base)
    $childFull = FullPathNoExist $child
    if (-not $childFull.StartsWith($baseFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "UNSAFE PATH ($label): must be under RunRoot. Base=$baseFull Child=$childFull"
    }
}

function Assert-SafeVersion([string]$v) {
    # allow: A-Z a-z 0-9 . _ -
    if ($v -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
        throw "UNSAFE VERSION: '$v' (allowed: A-Z a-z 0-9 . _ -)"
    }
}

function Get-RelativePath([string]$base, [string]$full) {
    $baseUri = [System.Uri]((Resolve-FullPath $base) + [IO.Path]::DirectorySeparatorChar)
    $fullUri = [System.Uri](Resolve-FullPath $full)
    return [System.Uri]::UnescapeDataString(
        $baseUri.MakeRelativeUri($fullUri).ToString().Replace('/', [IO.Path]::DirectorySeparatorChar)
    )
}

# ---------------------------
# Promote Logs (for Promote Center)
# ---------------------------
function Ensure-LogDir([string]$runRoot) {
    $d = Join-Path $runRoot "logs\promote"
    if ($DryRun) { return $d }
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
    return $d
}

function Write-PromoteEvent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$runRoot,
        [Parameter(Mandatory=$true)][ValidateSet("SUCCESS","FAIL")][string]$result,
        [string]$version = "",
        [string]$stage = "",
        [string]$reason = "",
        [string]$message = "",
        [string]$errorCode = "",
        [string]$rollbackSavedAt = "",
        [hashtable]$extra = $null
    )

    if ($DryRun) { return }

    $dir = Ensure-LogDir $runRoot
    $stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
    $tag = if ($result -eq "SUCCESS") { "success" } else { "fail" }
    $path = Join-Path $dir ("promote_{0}_{1}.json" -f $tag, $stamp)

    $obj = [ordered]@{
        time            = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        result          = $result
        version         = $version
        stage           = $stage
        reason          = $reason
        message         = $message
        error_code      = $errorCode
        src             = $Src
        target          = (Join-Path (Join-Path $runRoot "releases") $version)
        rollbackSavedAt = $rollbackSavedAt
        extra           = $extra
    }

    ($obj | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath $path -Encoding UTF8
    return $path
}

# =========================================================
# 사람이 읽는 오류 요약 (영어 몰라도 이해 가능)
# - 실패 시 logs\promote\최근오류_요약.txt 생성
# =========================================================
function Get-KR-ReasonText {
    param([string]$Stage,[string]$Reason,[string]$Message)

    $s = ($Stage  ?? "").Trim().ToUpper()
    $r = ($Reason ?? "").Trim().ToLower()

    switch ($r) {
        "force_required" { return "Force 옵션이 빠졌습니다" }
        "unsafe_path"    { return "경로가 위험해서 차단되었습니다" }
        "missing_in_staging" {
            if ($Message -match '(\d+)\s*') { return ("스테이징 누락: {0}개" -f $Matches[1]) }
            return "스테이징에 파일이 누락되었습니다"
        }
        default {
            if ($r) { return $r }
            if ($s) { return $s }
            return "원인 미상"
        }
    }
}

function Quote-Arg([string]$v) {
    if ($null -eq $v) { return '""' }
    if ($v -match '[\s"]') { return '"' + ($v -replace '"','""') + '"' }
    return $v
}


# =========================================================
# Error code (machine-friendly) for Promote Center (B안)
# - JSON에는 error_code로 저장
# - 센터에서 error_code를 한글로 매핑해서 보여줌
# =========================================================
function Get-ErrorCode {
    param([string]$Stage,[string]$Reason,[string]$Message)

    $m = ($Message ?? "").Trim()

    if ($m -like "Src not found:*")            { return "SRC_NOT_FOUND" }
    if ($m -like "RunRoot not found:*")        { return "RUNROOT_NOT_FOUND" }
    if ($m -like "Refusing drive root*")       { return "RUNROOT_IS_DRIVE_ROOT" }
    if ($m -like "*Path traversal*")           { return "PATH_TRAVERSAL" }
    if ($m -like "*outside RunRoot*")          { return "PATH_OUTSIDE_RUNROOT" }
    if ($m -like "*Another instance*")         { return "LOCKED" }
    if ($m -like "*lock*")                     { return "LOCKED" }
    if ($m -like "*SHA256*")                   { return "HASH_MISMATCH" }
    if ($m -like "*hash*")                     { return "HASH_MISMATCH" }
    if ($m -like "*Copy*failed*")              { return "COPY_FAILED" }
    if ($m -like "*Access is denied*")         { return "ACCESS_DENIED" }

    $r = ($Reason ?? "").Trim().ToLower()
    switch ($r) {
        "force_required" { return "FORCE_REQUIRED" }
        default          { return "EXCEPTION" }
    }
}


function Get-KR-NextAction {
    param([string]$Stage,[string]$Reason)

    $r = ($Reason ?? "").Trim().ToLower()
    switch ($r) {
        "force_required" { return "실승격이면 -Force를 붙여서 다시 실행하세요." }
        "unsafe_path"    { return "WORK 기준 경로로 이동한 뒤, RunRoot/Src/Version 값을 다시 확인하고 실행하세요." }
        "missing_in_staging" { return "소스 폴더에 누락 파일이 있는지 확인한 뒤 다시 실행하세요." }
        default { return "센터(View)에서 실패 항목의 요약/상세를 확인하고, 최신 fail 로그(json)를 확인하세요." }
    }
}

function Get-KR-NextCommand {
    param(
        [string]$Stage,
        [string]$Reason,
        [string]$RunRootArg,
        [string]$SrcArg,
        [string]$VersionArg
    )

    $r = ($Reason ?? "").Trim().ToLower()
    $force = if ($r -eq "force_required") { " -Force" } else { "" }
    $ver   = if ($VersionArg) { " -Version " + (Quote-Arg $VersionArg) } else { "" }

    $runRoot = Quote-Arg $RunRootArg
    $src     = Quote-Arg $SrcArg

    $lines = @()
    $lines += "cd D:\SEOHYUN_SYSTEM\WORK"
    $lines += ("pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\promote.ps1 -RunRoot {0} -Src {1}{2}{3}" -f $runRoot, $src, $ver, $force)

    return ($lines -join "`r`n")
}

function Write-KR-ErrorSummary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$RunRoot,
        [string]$Action = "승격(promote)",
        [string]$Stage = "",
        [string]$Reason = "",
        [string]$Message = "",
        [string]$Version = "",
        [string]$Src = ""
    )

    $dir = Join-Path $RunRoot "logs\promote"
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }

    $reasonKR = Get-KR-ReasonText -Stage $Stage -Reason $Reason -Message $Message
    $nextKR   = Get-KR-NextAction -Stage $Stage -Reason $Reason
    $cmdKR    = Get-KR-NextCommand -Stage $Stage -Reason $Reason -RunRootArg $RunRoot -SrcArg $Src -VersionArg $Version

    $p = Join-Path $dir "최근오류_요약.txt"
    $t = @()
    $t += "[언제] " + (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $t += "[무슨 작업] " + $Action
    if ($Version) { $t += "[버전] " + $Version }
    if ($Stage)   { $t += "[단계] " + $Stage }
    $t += "[결과] 실패"
    $t += ""
    $t += "[한 줄 요약]"
    $t += "→ " + $reasonKR
    $t += ""
    $t += "[에러 메시지(원문)]"
    $t += $Message
    $t += ""
    $t += "[다음 행동]"
    $t += "→ " + $nextKR
    $t += ""
    $t += "[다음 실행 명령(그대로 복사)]"
    $t += $cmdKR
    $t += ""
    $t += "[바로 확인할 파일]"
    $t += "→ logs\promote\promote_fail_*.json (가장 최신)"
    $t += "→ tools\CHECK_PROMOTE_SYNTAX.bat (문법 검사)"
    $t -join "`r`n" | Set-Content -LiteralPath $p -Encoding UTF8
}


# ---------------------------
# Exclusions
# ---------------------------
$ExcludeDirNames = @(
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode"
)

function Should-ExcludeRel([string]$rel) {
    $segs = $rel -split "[\\/]"

    if ($segs.Length -ge 2) {
        $dirSegs = $segs[0..($segs.Length-2)]
        foreach ($d in $dirSegs) {
            if ($ExcludeDirNames -contains $d) { return $true }
        }
    }
    return $false
}

# ---------------------------
# Index / diff
# ---------------------------
function Get-FileIndex([string]$baseDir) {
    $base = Resolve-FullPath $baseDir
    $idx = @{}
    $files = Get-ChildItem -LiteralPath $base -File -Recurse -Force

    foreach ($f in $files) {
        $rel = Get-RelativePath $base $f.FullName
        if (Should-ExcludeRel $rel) { continue }
        $idx[$rel] = [PSCustomObject]@{
            Rel = $rel
            Len = [int64]$f.Length
            LastWriteUtc = $f.LastWriteTimeUtc.ToString("o")
        }
    }
    return $idx
}

function Get-TotalBytes($Index) {
    if (-not $Index) { return 0 }
    $sum = [int64]0
    foreach ($k in $Index.Keys) { $sum += [int64]$Index[$k].Len }
    return $sum
}

function Compare-Index($SrcIndex, $DstIndex) {
    $srcKeys = @($SrcIndex.Keys)
    $dstKeys = if ($DstIndex) { @($DstIndex.Keys) } else { @() }

    $dstSet = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($k in $dstKeys) { [void]$dstSet.Add($k) }

    $added   = New-Object 'System.Collections.Generic.List[string]'
    $removed = New-Object 'System.Collections.Generic.List[string]'
    $changed = New-Object 'System.Collections.Generic.List[string]'

    foreach ($k in $srcKeys) {
        if (-not $dstSet.Contains($k)) {
            [void]$added.Add($k)
        } else {
            $a = $SrcIndex[$k]
            $b = $DstIndex[$k]
            if ($a.Len -ne $b.Len -or $a.LastWriteUtc -ne $b.LastWriteUtc) {
                [void]$changed.Add($k)
            }
        }
    }

    $srcSet = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($k in $srcKeys) { [void]$srcSet.Add($k) }

    foreach ($k in $dstKeys) {
        if (-not $srcSet.Contains($k)) { [void]$removed.Add($k) }
    }

    return [PSCustomObject]@{
        Added   = $added
        Removed = $removed
        Changed = $changed
    }
}

# ---------------------------
# Verify (SHA256)
# ---------------------------
function Get-HashMap([string]$baseDir) {
    $base = Resolve-FullPath $baseDir
    $map = @{}
    $files = Get-ChildItem -LiteralPath $base -File -Recurse -Force
    foreach ($f in $files) {
        $rel = Get-RelativePath $base $f.FullName
        if (Should-ExcludeRel $rel) { continue }
        $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
        $map[$rel] = $h
    }
    return $map
}

function Assert-HashEqual([string]$srcDir, [string]$dstDir) {
    Write-Host ("[VERIFY] SHA256 compare: {0} <-> {1}" -f $srcDir, $dstDir)
    $a = Get-HashMap $srcDir
    $b = Get-HashMap $dstDir

    if ($a.Count -ne $b.Count) {
        throw "VERIFY FAIL: file count mismatch (Src=$($a.Count) Dst=$($b.Count))"
    }

    foreach ($k in $a.Keys) {
        if (-not $b.ContainsKey($k)) { throw "VERIFY FAIL: missing in dst => $k" }
        if ($a[$k] -ne $b[$k]) { throw "VERIFY FAIL: hash mismatch => $k" }
    }
}

# ---------------------------
# Copy
# ---------------------------
function Copy-Tree([string]$srcDir, [string]$dstDir) {
    $src = Resolve-FullPath $srcDir
    Ensure-Dir $dstDir

    $files = Get-ChildItem -LiteralPath $src -File -Recurse -Force
    foreach ($f in $files) {
        $rel = Get-RelativePath $src $f.FullName
        if (Should-ExcludeRel $rel) { continue }

        $to = Join-Path $dstDir $rel
        $toParent = Split-Path -Parent $to
        Ensure-Dir $toParent

        if ($DryRun) {
            Write-Host ("[DRYRUN] COPY {0} -> {1}" -f $rel, $to)
        } else {
            Copy-Item -LiteralPath $f.FullName -Destination $to -Force
        }
    }
}

# ---------------------------
# Backup (folder copy)
# ---------------------------
function Backup-Folder([string]$folder, [string]$backupRoot, [string]$name) {
    if ($DryRun) {
        Write-Host ("[DRYRUN] BACKUP folder => {0}" -f $folder)
        return
    }
    Ensure-Dir $backupRoot
    $dst = Join-Path $backupRoot $name
    if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force }
    Copy-Item -LiteralPath $folder -Destination $dst -Recurse -Force
    Write-Host ("[BACKUP] {0} -> {1}" -f $folder, $dst)
    return $dst
}

# ---------------------------
# Lock (P0)
# ---------------------------
$LockDir  = Join-Path $RunRoot "locks"
$LockFile = Join-Path $LockDir "promote.lock"

function Acquire-Lock() {
    if ($DryRun) {
        Write-Host "[DRYRUN] lock skipped"
        return
    }
    Ensure-Dir $LockDir
    if (Test-Path -LiteralPath $LockFile) {
        $age = (Get-Date) - (Get-Item -LiteralPath $LockFile).LastWriteTime
        throw "LOCK EXISTS: $LockFile (age: $([int]$age.TotalMinutes) min). Another promote may be running."
    }
    Set-Content -LiteralPath $LockFile -Value ("{0} {1}" -f (NowStamp), $PID) -Encoding UTF8
}

function Release-Lock() {
    if ($DryRun) { return }
    if (Test-Path -LiteralPath $LockFile) { Remove-Item -LiteralPath $LockFile -Force }
}

# ---------------------------
# SwitchCurrent: junction releases\current -> releases\<version>
# ---------------------------
function Ensure-Junction([string]$linkPath, [string]$targetPath) {
    if ($DryRun) {
        Write-Host ("[DRYRUN] JUNCTION {0} -> {1}" -f $linkPath, $targetPath)
        return
    }

    if (Test-Path -LiteralPath $linkPath) {
        Remove-Item -LiteralPath $linkPath -Recurse -Force
    }

    $args = "/c mklink /J `"$linkPath`" `"$targetPath`""
    $p = Start-Process -FilePath "cmd.exe" -ArgumentList $args -NoNewWindow -PassThru -Wait
    if ($p.ExitCode -ne 0) {
        throw "SWITCH FAIL: mklink exitcode=$($p.ExitCode)"
    }
    Write-Host ("[SWITCH] current -> {0}" -f $targetPath)
}

# ---------------------------
# MAIN
# ---------------------------
try {
    Write-Head "SEOHyun Promote"

    $Stage = "INIT"

    # Resolve and validate base paths
    Assert-NotRootPath $RunRoot "RunRoot"
    Assert-NotRootPath $Src "Src"

    if (-not (Test-Path -LiteralPath $RunRoot)) { throw "RunRoot not found: $RunRoot" }
    if (-not (Test-Path -LiteralPath $Src))     { throw "Src not found: $Src" }

    $RunRootFull = Resolve-FullPath $RunRoot
    $SrcFull     = Resolve-FullPath $Src

    # Version default: src folder name
    if ([string]::IsNullOrWhiteSpace($Version)) {
        $Version = (Split-Path -Leaf $SrcFull)
    }
    Assert-SafeVersion $Version

    # critical: Src must be under RunRoot (헌법 기준: 승격은 같은 시스템 트리 내에서만)
    Assert-UnderBase $RunRootFull $SrcFull "Src"

    # derived paths must be under RunRoot too
    $ReleasesDir = Join-Path $RunRootFull "releases"
    $TargetDir   = Join-Path $ReleasesDir $Version
    Assert-UnderBase $RunRootFull $TargetDir "Target"

    $StagingRoot = Join-Path $ReleasesDir "_staging"
    $StagingDir  = Join-Path $StagingRoot ("{0}_{1}" -f $Version, (StampId))
    Assert-UnderBase $RunRootFull $StagingDir "Staging"

    $BackupRoot  = Join-Path $ReleasesDir "_backups"
    Assert-UnderBase $RunRootFull $BackupRoot "BackupRoot"

    $CurrentLink = Join-Path $ReleasesDir "current"
    Assert-UnderBase $RunRootFull $CurrentLink "CurrentLink"

    # Print config
    Write-Host ("RunRoot  : {0}" -f $RunRootFull)
    Write-Host ("Src      : {0}" -f $SrcFull)
    Write-Host ("Version  : {0}" -f $Version)
    Write-Host ("Target   : {0}" -f $TargetDir)
    Write-Host ("DryRun   : {0}" -f [bool]$DryRun)
    Write-Host ("Backup   : {0}" -f [bool]$Backup)
    Write-Host ("SwitchCur: {0}" -f [bool]$SwitchCurrent)
    Write-Host ("Force    : {0}" -f [bool]$Force)
    Write-Host ("Verify   : {0}" -f [bool]$VerifyHashAfterCopy)

    # Required check (Src)
    if (-not $SkipRequiredCheck) {
        foreach ($rp in $RequiredRelPaths) {
            $p = Join-Path $SrcFull $rp
            if (-not (Test-Path -LiteralPath $p)) {
                throw "REQUIRED MISSING in Src: $rp (path: $p)"
            }
        }
        Write-Host "[OK] required paths exist in Src"
    } else {
        Write-Host "[SKIP] required check"
    }

    # Pre-diff summary
    Write-Head "PRE-PROMOTE DIFF SUMMARY"
    $srcIdx = Get-FileIndex $SrcFull

    $dstIdx = $null
    if (Test-Path -LiteralPath $TargetDir) {
        $dstIdx = Get-FileIndex $TargetDir
    }

    $cmp = Compare-Index $srcIdx $dstIdx
    $srcBytes = Get-TotalBytes $srcIdx
    $dstBytes = Get-TotalBytes $dstIdx

    $dstCount = if ($dstIdx) { $dstIdx.Count } else { 0 }

    Write-Host ("Files: Src={0}  Dst={1}" -f $srcIdx.Count, $dstCount)
    Write-Host ("Size : Src={0} bytes  Dst={1} bytes" -f $srcBytes, $dstBytes)
    Write-Host ("Added   : {0}" -f $cmp.Added.Count)
    Write-Host ("Removed : {0}" -f $cmp.Removed.Count)
    Write-Host ("Changed : {0}" -f $cmp.Changed.Count)

    if ($DryRun) {
        Write-Host ""
        Write-Host "[DRYRUN] Stateless exit (no staging/backup/copy/verify/commit/log)."
        exit 0
    }

    # Acquire lock
    Acquire-Lock

    # Ensure releases folder exists
    Ensure-Dir $ReleasesDir
    Ensure-Dir $StagingRoot

    # Backup existing target
    if ((Test-Path -LiteralPath $TargetDir) -and $Backup) {
        $Stage = "BACKUP"
        Write-Head "BACKUP"
        $name = "{0}_{1}" -f $Version, (StampId)
        $RollbackSavedAt = Backup-Folder $TargetDir $BackupRoot $name
    }

    # Stage copy
    $Stage = "STAGING_COPY"
    Write-Head "STAGING COPY"
    if (Test-Path -LiteralPath $StagingDir) { Remove-Item -LiteralPath $StagingDir -Recurse -Force }
    Copy-Tree $SrcFull $StagingDir

    # Verify after copy
    if ($VerifyHashAfterCopy) {
        $Stage = "VERIFY"
        Write-Head "VERIFY AFTER COPY"
        Assert-HashEqual $SrcFull $StagingDir
        Write-Host "[OK] staging verified"
    } else {
        Write-Host "[SKIP] verify after copy disabled"
    }

    # Commit
    $Stage = "COMMIT"
    Write-Head "COMMIT"
    $OldDir = $null
    if (Test-Path -LiteralPath $TargetDir) {
        $OldDir = Join-Path $ReleasesDir ("_old_{0}_{1}" -f $Version, (StampId))
        Assert-UnderBase $RunRootFull $OldDir "OldDir"
        Move-Item -LiteralPath $TargetDir -Destination $OldDir
    }

    Move-Item -LiteralPath $StagingDir -Destination $TargetDir

    # Post-commit verify
    if ($VerifyHashAfterCopy) {
        $Stage = "POST_VERIFY"
        Write-Head "POST-COMMIT VERIFY"
        Assert-HashEqual $SrcFull $TargetDir
        Write-Host "[OK] target verified"
    }

    # SwitchCurrent
    if ($SwitchCurrent) {
        $Stage = "SWITCH_CURRENT"
        Write-Head "SWITCH CURRENT"
        Ensure-Junction $CurrentLink $TargetDir
    }

    # Cleanup old dir
    if ($OldDir -and (Test-Path -LiteralPath $OldDir)) {
        if (-not $Force) {
            Write-Host ("[KEEP] old target kept at: {0} (use -Force to auto-delete)" -f $OldDir)
        } else {
            Write-Host ("[DELETE] removing old target: {0}" -f $OldDir)
            Remove-Item -LiteralPath $OldDir -Recurse -Force
        }
    }

    $Stage = "DONE"
    Write-Head "DONE"
    Write-Host ("[OK] Promoted to: {0}" -f $TargetDir)

    # PostCheck (optional)
    if ($PostCheck) {
        $Stage = "POSTCHECK"
        Write-Head "POSTCHECK"
        $bat = Join-Path $TargetDir "run.bat"
        if (-not (Test-Path -LiteralPath $bat)) {
            $PostCheckResult = "FAIL"
            Write-Host ("[POSTCHECK] run.bat not found: {0}" -f $bat)
        } else {
            try {
                $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$bat`"" -WorkingDirectory $TargetDir -NoNewWindow -PassThru
                if (-not $p.WaitForExit($PostCheckTimeoutSec * 1000)) {
                    try { $p.Kill() } catch {}
                    $PostCheckResult = "TIMEOUT"
                    Write-Host ("[POSTCHECK] TIMEOUT > {0}s" -f $PostCheckTimeoutSec)
                } else {
                    $PostCheckResult = if ($p.ExitCode -eq 0) { "OK" } else { "FAIL" }
                    Write-Host ("[POSTCHECK] ExitCode={0}" -f $p.ExitCode)
                }
            } catch {
                $PostCheckResult = "FAIL"
                Write-Host ("[POSTCHECK] Exception: {0}" -f $_.Exception.Message)
            }
        }
    }

    # SUCCESS LOG
    Write-PromoteEvent `
        -runRoot $RunRootFull `
        -result "SUCCESS" `
        -version $Version `
        -stage $Stage `
        -reason "ok" `
        -message "OK" `
        -errorCode "" `
        -rollbackSavedAt $RollbackSavedAt `
        -extra @{ postcheck = $PostCheckResult }

    exit 0
}
catch {
    Write-Host ""
    Write-Host "[ERROR] promote failed"

    $Reason = "exception"
    $msg = $_.Exception.Message
    $ErrorCode = Get-ErrorCode -Stage $Stage -Reason $Reason -Message $msg
    # 한국어 요약 파일 생성 (영어 몰라도 확인 가능)
    try {
        Write-KR-ErrorSummary -RunRoot $RunRootFull -Action "승격(promote)" -Stage $Stage -Reason $Reason -Message $msg -Version $Version -Src $Src
    } catch {
        Write-Host ("[WARN] kr summary write failed: {0}" -f $_.Exception.Message)
    }

    Write-Host $msg

    # FAIL LOG (RunRootFull이 아직 없을 수도 있으므로 안전 처리)
    try {
        $rr = if ($RunRootFull) { $RunRootFull } else { $RunRoot }
        if ($rr -and (Test-Path -LiteralPath $rr)) {
            Write-PromoteEvent `
                -runRoot $rr `
                -result "FAIL" `
                -version $Version `
                -stage $Stage `
                -reason $Reason `
                -message $msg `
                -errorCode $ErrorCode `
                -rollbackSavedAt "" `
                -extra @{ postcheck = $PostCheckResult }
        }
    } catch {
        Write-Host ("[WARN] fail log write failed: {0}" -f $_.Exception.Message)
    }

    exit 1
}
finally {
    Release-Lock
}
