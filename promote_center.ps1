[CmdletBinding()]
param(
  [ValidateSet("View","Rollback","Undo")]
  [string]$Mode = "View",

  # Undo 모드에서 최근 N개만 보여줌 (선택 안 하면 최신 자동)
  [int]$UndoLast = 3,

  # 자동 정리: 최근 N개 유지
  [int]$KeepLast = 10
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ==========================================================
# Utils
# ==========================================================
function Resolve-FullPath([string]$Path) { (Resolve-Path -LiteralPath $Path).Path }
function Ensure-Dir([string]$Path) { if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Path $Path | Out-Null } }
function Ensure-TrailingSlash([string]$p) {
  if (-not $p) { return $p }
  $sep = [IO.Path]::DirectorySeparatorChar
  if ($p.EndsWith($sep)) { return $p }
  return $p + $sep
}
function Get-FullPathNoExist([string]$Path, [string]$Base = $null) {
  if ($Base -and -not [IO.Path]::IsPathRooted($Path)) { $Path = Join-Path $Base $Path }
  return [IO.Path]::GetFullPath($Path)
}
function Assert-UnderBase([string]$Base, [string]$Child, [string]$Label) {
  $b = Ensure-TrailingSlash (Get-FullPathNoExist $Base)
  $c = Get-FullPathNoExist $Child
  if (-not $c.StartsWith($b, [StringComparison]::OrdinalIgnoreCase)) {
    throw "UNSAFE PATH ($Label): $Child"
  }
}
function Assert-SafeVersion([string]$v) {
  if ($v -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') { throw "UNSAFE VERSION: $v" }
}
function Get-Prop([object]$o, [string]$name, $default = $null) {
  if (-not $o) { return $default }
  if ($o.PSObject.Properties.Name -contains $name) {
    $val = $o.$name
    if ($null -ne $val -and "$val".Trim() -ne "") { return $val }
  }
  return $default
}

# ==========================================================
# Auto cleanup (keep last N dirs)
# ==========================================================
function Cleanup-KeepLastN([string]$dir, [int]$keep = 10) {
  if (-not (Test-Path -LiteralPath $dir)) { return }
  $items = Get-ChildItem -LiteralPath $dir -Directory -Force | Sort-Object LastWriteTimeUtc -Descending
  $drop = $items | Select-Object -Skip $keep
  foreach ($d in $drop) { try { Remove-Item -LiteralPath $d.FullName -Recurse -Force } catch {} }
}

# ==========================================================
# Lock (shared with promote)
# ==========================================================
function Acquire-Lock([string]$ReleasesDir, [string]$Mode) {
  $lock = Join-Path $ReleasesDir ".promote.lock"
  if (Test-Path -LiteralPath $lock) { throw "다른 승격/롤백 작업이 진행 중입니다: $lock" }
  Ensure-Dir $ReleasesDir
  Set-Content -LiteralPath $lock -Value (@{
    time=(Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    pid=$PID
    mode=$Mode
  } | ConvertTo-Json -Depth 5) -Encoding UTF8 -NoNewline
  return $lock
}
function Release-Lock($lock) { if ($lock -and (Test-Path -LiteralPath $lock)) { try { Remove-Item -LiteralPath $lock -Force } catch {} } }

# ==========================================================
# Diff Preview (fast: path+size)
# ==========================================================
function Get-DiffPreviewSummary([string]$CurrentDir, [string]$RollbackDir) {
  if (-not (Test-Path -LiteralPath $CurrentDir)) { throw "대상 폴더 없음: $CurrentDir" }
  if (-not (Test-Path -LiteralPath $RollbackDir)) { throw "비교 폴더 없음: $RollbackDir" }

  $a = Get-ChildItem -LiteralPath $CurrentDir -File -Recurse -Force | ForEach-Object { $_.FullName.Substring($CurrentDir.Length) }
  $b = Get-ChildItem -LiteralPath $RollbackDir -File -Recurse -Force | ForEach-Object { $_.FullName.Substring($RollbackDir.Length) }

  $sa = New-Object 'System.Collections.Generic.HashSet[string]'
  foreach ($x in $a) { [void]$sa.Add($x) }
  $sb = New-Object 'System.Collections.Generic.HashSet[string]'
  foreach ($x in $b) { [void]$sb.Add($x) }

  $added   = ($sb | Where-Object { -not $sa.Contains($_) }).Count
  $removed = ($sa | Where-Object { -not $sb.Contains($_) }).Count
  $changed = 0

  foreach ($p in $sa) {
    if ($sb.Contains($p)) {
      $fa = Join-Path $CurrentDir $p
      $fb = Join-Path $RollbackDir $p
      try {
        if ((Get-Item -LiteralPath $fa).Length -ne (Get-Item -LiteralPath $fb).Length) { $changed++ }
      } catch {}
    }
  }

  return @{ Added=$added; Removed=$removed; Changed=$changed }
}

# ==========================================================
# One-line summary for FAIL (사람용)
# ==========================================================
function Make-OneLineSummary([string]$stage, [string]$reason, [string]$message) {
  $s = ($stage ?? "").Trim().ToUpper()
  $r = ($reason ?? "").Trim().ToLower()
  $m = ($message ?? "").Trim()

  # 사람용(한국어) 우선 매핑
  if ($r -eq "force_required") { return "Force 옵션이 빠졌습니다" }
  if ($r -eq "unsafe_path") { return "경로가 위험해서 차단되었습니다" }
  if ($r -eq "src_not_found") { return "소스 폴더를 찾을 수 없습니다" }
  if ($r -eq "target_exists") { return "대상 폴더가 이미 존재합니다" }
  if ($r -eq "lock_exists") { return "다른 작업이 진행 중입니다(LOCK)" }

  if ($s -eq "VERIFY" -and $r -eq "missing_in_staging") {
    if ($m -match 'Missing count:\s*(\d+)') { return ("스테이징 누락: {0}개" -f $Matches[1]) }
    if ($m -match 'missing\s*:\s*(\d+)') { return ("스테이징 누락: {0}개" -f $Matches[1]) }
    return "스테이징 누락"
  }

  # 메시지 기반(영어 몰라도)
  if ($m -match "Missing closing '\}'" -or $m -match "Unexpected token '\}'" -or $m -match "ParserError") {
    return "스크립트 문법 오류(중괄호/구문 깨짐)"
  }
  if ($m -match "not found" -and $m -match "run\.bat") { return "run.bat 없음(헬스체크 실패)" }
  if ($m -match "Access is denied") { return "권한 문제(Access denied)" }

  # fallback
  if ($r) { return $r }
  if ($s) { return $s }
  return "알 수 없음"
}

# ==========================================================
# Load promote logs (SAFE)
# ==========================================================
function Read-JsonSafe([string]$p) { try { Get-Content -LiteralPath $p -Raw | ConvertFrom-Json } catch { $null } }


function Get-KR-ErrorMessage {
  param([string]$ErrorCode,[string]$Message,[string]$Stage,[string]$Reason)

  $c = ($ErrorCode ?? "").Trim().ToUpper()
  switch ($c) {
    "SRC_NOT_FOUND"         { return "소스 폴더가 없습니다. (선택한 버전 폴더/경로 확인)" }
    "RUNROOT_NOT_FOUND"     { return "RunRoot 폴더가 없습니다. (폴더 위치/이동 여부 확인)" }
    "RUNROOT_IS_DRIVE_ROOT" { return "RunRoot가 드라이브 루트로 잡혔습니다. (D:\\ 같은 루트 금지)" }
    "PATH_TRAVERSAL"        { return "경로 침범(상위 이동/.. 등) 의심이 감지되어 차단했습니다." }
    "PATH_OUTSIDE_RUNROOT"  { return "RunRoot 바깥으로 접근 시도가 감지되어 차단했습니다." }
    "LOCKED"                { return "이미 다른 Promote가 실행 중입니다. (잠시 후 재시도)" }
    "HASH_MISMATCH"         { return "복사 후 SHA256 검증 실패입니다. (파일 손상/복사 오류)" }
    "COPY_FAILED"           { return "파일 복사 단계에서 실패했습니다. (권한/잠금/경로 확인)" }
    "ACCESS_DENIED"         { return "권한이 부족합니다. (관리자 권한/폴더 권한 확인)" }
    "FORCE_REQUIRED"        { return "보호장치가 차단했습니다. (의도된 작업이면 -Force 필요)" }
    "EXCEPTION"             { return "예외가 발생했습니다. (원문 메시지 참고)" }
    default                 { return "오류가 발생했습니다. (원문 메시지 참고)" }
  }
}

function Load-PromoteEvents([string]$LogDir) {
  $files = Get-ChildItem -LiteralPath $LogDir -File -Filter "*.json" -Force |
           Where-Object { $_.Name -like "promote_success_*" -or $_.Name -like "promote_fail_*" } |
           Sort-Object LastWriteTimeUtc -Descending

  $list = @()
  foreach ($f in $files) {
    $o = Read-JsonSafe $f.FullName
    if (-not $o) { continue }

    $isFailFile = ($f.Name -like "promote_fail_*")

    $resRaw = Get-Prop $o "result" $null
    if (-not $resRaw) { $resRaw = if ($isFailFile) { "FAIL" } else { "" } }

    $krResult = if ($resRaw -eq "SUCCESS") { "성공" } elseif ($resRaw -eq "FAIL") { "실패" } else { $resRaw }

    $time = Get-Prop $o "time" $null
    if (-not $time) { $time = $f.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss") }

    $ver = Get-Prop $o "version" ""
    if (-not $ver -and $isFailFile) { $ver = "-" }

    $stage = Get-Prop $o "stage" ""
    $reason = Get-Prop $o "reason" ""
    $msg = Get-Prop $o "message" ""
    $code = Get-Prop $o "error_code" ""
    $krMsg = if ($resRaw -eq "FAIL") { Get-KR-ErrorMessage -ErrorCode $code -Message $msg -Stage $stage -Reason $reason } else { "" }

    $list += [PSCustomObject]@{
      시간     = $time
      결과     = $krResult
      버전     = $ver
      요약     = Make-OneLineSummary -stage $stage -reason $reason -message $msg
      단계     = $stage
      원인     = $reason
      오류코드 = $code
      상세     = $krMsg
      원문     = $msg
      되돌리기 = Get-Prop $o "rollbackSavedAt" ""
      로그파일 = $f.FullName
    }
  }
  return $list
}

# ==========================================================
# Undo candidates (from _rollback_current)
# ==========================================================
function Load-UndoCandidates([string]$RunRoot) {
  $root = Join-Path $RunRoot "releases\_rollback_current"
  if (-not (Test-Path -LiteralPath $root)) { return @() }

  Get-ChildItem -LiteralPath $root -Directory -Force |
    Sort-Object LastWriteTimeUtc -Descending |
    ForEach-Object {
      $ver = $_.Name
      if ($_.Name -match '^(?<v>.+)_(\d{8}_\d{6})$') { $ver = $Matches.v }
      [PSCustomObject]@{
        시간     = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        버전     = $ver
        원본폴더 = $_.FullName
      }
    }
}

# ==========================================================
# Health check (after rollback/undo)
# ==========================================================
function HealthCheck-Target([string]$TargetDir) {
  $must = @("run.bat","scripts\create_worklog.py")
  $missing = @()
  foreach ($m in $must) {
    if (-not (Test-Path -LiteralPath (Join-Path $TargetDir $m))) { $missing += $m }
  }
  return $missing
}

# ==========================================================
# Rollback / Undo (Move-based, safe)
# ==========================================================
function Run-Rollback([string]$RunRoot,[string]$Version,[string]$RollbackDir) {
  Assert-SafeVersion $Version

  $rel = Join-Path $RunRoot "releases"
  $target = Join-Path $rel $Version
  Assert-UnderBase $RunRoot $target "TargetDir"

  # RollbackDir safety: must be under releases\_backups (promote.ps1에서 백업 저장)
  $rbFull = Resolve-FullPath $RollbackDir
  $allowedRoots = @(
    (Join-Path $rel "_backups"),
    (Join-Path $rel "_rollback") # 예전 구조 호환
  ) | ForEach-Object { Resolve-FullPath $_ } | ForEach-Object { Ensure-TrailingSlash $_ }

  $ok = $false
  foreach ($ar in $allowedRoots) {
    if ($rbFull.StartsWith($ar, [StringComparison]::OrdinalIgnoreCase)) { $ok = $true; break }
  }
  if (-not $ok) { throw "되돌리기 폴더가 허용 범위 밖입니다: $rbFull" }

  $lock = $null
  try {
    $lock = Acquire-Lock $rel "ROLLBACK"

    $saveRoot = Join-Path $rel "_rollback_current"
    Ensure-Dir $saveRoot
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $saved = Join-Path $saveRoot ("{0}_{1}" -f $Version,$stamp)

    if (Test-Path -LiteralPath $target) { Move-Item -LiteralPath $target -Destination $saved -Force }
    Move-Item -LiteralPath $rbFull -Destination $target -Force

    Write-Host ""
    Write-Host "✅ 롤백 완료"
    Write-Host "복구된 대상: $target"
    Write-Host "이전 대상 백업: $saved"

    $miss = HealthCheck-Target $target
    if ($miss.Count -gt 0) {
      Write-Host ("⚠️ 헬스체크 실패(필수 누락): {0}" -f ($miss -join ", "))
    } else {
      Write-Host "✅ 헬스체크 OK"
    }
  }
  finally { Release-Lock $lock }
}

function Run-UndoRollback([string]$RunRoot,[string]$Version,[string]$SavedDir) {
  Assert-SafeVersion $Version

  $rel = Join-Path $RunRoot "releases"
  $target = Join-Path $rel $Version
  Assert-UnderBase $RunRoot $target "TargetDir"

  $savedFull = Resolve-FullPath $SavedDir
  $savedRoot = Resolve-FullPath (Join-Path $rel "_rollback_current")
  if (-not $savedFull.StartsWith((Ensure-TrailingSlash $savedRoot), [StringComparison]::OrdinalIgnoreCase)) {
    throw "UNDO 원본폴더가 허용 범위 밖입니다: $savedFull"
  }

  $lock = $null
  try {
    $lock = Acquire-Lock $rel "UNDO"

    $undoRoot = Join-Path $rel "_undo_backup"
    Ensure-Dir $undoRoot
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $saved = Join-Path $undoRoot ("{0}_{1}" -f $Version,$stamp)

    if (Test-Path -LiteralPath $target) { Move-Item -LiteralPath $target -Destination $saved -Force }
    Move-Item -LiteralPath $savedFull -Destination $target -Force

    Write-Host ""
    Write-Host "✅ UNDO 완료(롤백 취소)"
    Write-Host "복구된 대상: $target"
    Write-Host "현재본 백업: $saved"

    $miss = HealthCheck-Target $target
    if ($miss.Count -gt 0) {
      Write-Host ("⚠️ 헬스체크 실패(필수 누락): {0}" -f ($miss -join ", "))
    } else {
      Write-Host "✅ 헬스체크 OK"
    }
  }
  finally { Release-Lock $lock }
}

# ==========================================================
# MAIN
# ==========================================================
$RunRoot = Resolve-FullPath "."
$ReleasesDir = Join-Path $RunRoot "releases"

# 자동 정리 (사람이 쓰기 쉬운 유지보수)
Cleanup-KeepLastN (Join-Path $ReleasesDir "_rollback_current") $KeepLast
Cleanup-KeepLastN (Join-Path $ReleasesDir "_undo_backup")      $KeepLast

$LogDir  = Join-Path $RunRoot "logs\promote"

# --------------------------
# UNDO MODE
# --------------------------
if ($Mode -eq "Undo") {
  $undos = Load-UndoCandidates -RunRoot $RunRoot
  if (-not $undos -or $undos.Count -eq 0) {
    # 빈 상태도 UI로 보여준다
    @([PSCustomObject]@{ 시간="-"; 버전="-"; 원본폴더=""; 안내="UNDO 대상 없음 (먼저 롤백을 한 번 해야 생성됨)" }) |
      Out-GridView -Title "롤백 취소 센터 - 현재 UNDO 없음" | Out-Null
    exit 0
  }

  $undosN = $undos | Select-Object -First $UndoLast
  $picked = $undosN | Out-GridView -Title ("롤백 취소 센터 - 최근 {0}개 (선택 안 하면 최신 자동)" -f $UndoLast) -PassThru
  $selected = if ($picked) { $picked } else { $undosN[0] }

  # 실행 비활성(원본폴더 필수)
  if (-not $selected.원본폴더 -or $selected.원본폴더.Trim() -eq "" -or -not (Test-Path -LiteralPath $selected.원본폴더)) {
    Write-Host ""
    Write-Host "⛔ 실행 불가: UNDO 원본폴더가 없습니다."
    Read-Host "Enter"
    exit 0
  }

  $target = Join-Path $RunRoot ("releases\{0}" -f $selected.버전)
  $sum = Get-DiffPreviewSummary -CurrentDir $target -RollbackDir $selected.원본폴더

  Write-Host ""
  Write-Host ("[미리보기] 파일: +{0} / -{1} / 변경 {2}" -f $sum.Added, $sum.Removed, $sum.Changed)

  $big = ($sum.Removed -ge 20) -or ($sum.Changed -ge 200) -or ($sum.Added -ge 500)
  if ($big) { Write-Host "⚠️ 대규모 변경 감지: 실수 가능성 높음. 반드시 확인하고 진행하세요." }

  Write-Host ""
  if ((Read-Host "진짜 UNDO 하려면 UNDO 입력") -ne "UNDO") { Write-Host "취소"; exit 0 }
  Run-UndoRollback -RunRoot $RunRoot -Version $selected.버전 -SavedDir $selected.원본폴더
  exit 0
}

# --------------------------
# VIEW / ROLLBACK MODE
# --------------------------
if (-not (Test-Path -LiteralPath $LogDir)) {
  # 로그 폴더 자체가 없으면 안내 UI
  @([PSCustomObject]@{
    시간="-"; 결과="없음"; 버전="-"; 요약="로그 폴더 없음"; 단계="-"; 원인="-"; 상세="logs\promote 폴더가 아직 없습니다"; 되돌리기=""; 로그파일=""
  }) | Out-GridView -Title "승격 관리 센터 - 로그 없음" | Out-Null
  exit 0
}

$events = Load-PromoteEvents -LogDir $LogDir
if (-not $events -or $events.Count -eq 0) {
  @([PSCustomObject]@{
    시간="-"; 결과="없음"; 버전="-"; 요약="표시할 로그 없음"; 단계="-"; 원인="-"; 상세="아직 promote 성공/실패 로그가 없습니다"; 되돌리기=""; 로그파일=""
  }) | Out-GridView -Title "승격 관리 센터 - 로그 없음" | Out-Null
  exit 0
}

# 최신이 위로 (기본 정렬)
$events = $events | Sort-Object 시간 -Descending

# Rollback 모드: 되돌릴 수 있는 성공만 (없어도 UI 유지)
if ($Mode -eq "Rollback") {
  $rb = $events | Where-Object { $_.결과 -eq "성공" -and $_.되돌리기 -and $_.되돌리기.Trim() -ne "" }
  if (-not $rb -or $rb.Count -eq 0) {
    $events = @([PSCustomObject]@{
      시간="-"; 결과="없음"; 버전="-"; 요약="되돌릴 수 있는 성공 없음"; 단계="-"; 원인="되돌릴 수 있는 성공 항목이 아직 없습니다";
      상세="성공 승격(Backup=ON) 후 rollbackSavedAt가 기록되면 여기에 표시됩니다"; 되돌리기=""; 로그파일=""
    })
  } else {
    $events = $rb
  }
}

$title = if ($Mode -eq "Rollback") { "되돌리기 센터 - 되돌릴 수 있는 성공만 (더블클릭)" } else { "승격 관리 센터 - 전체 보기 (더블클릭)" }

while ($true) {
  $sel = $events | Out-GridView -Title $title -PassThru
  if (-not $sel) { exit 0 }

  if ($Mode -ne "Rollback" -and $Mode -ne "Undo") {
    # View 모드: 사람이 바로 이해할 수 있게 콘솔에 요약을 크게 출력 + 선택 로그 열기 옵션
    Write-Host ""
    Write-Host ("[시간] {0}" -f $sel.시간)
    Write-Host ("[결과] {0}" -f $sel.결과)
    Write-Host ("[버전] {0}" -f $sel.버전)
    Write-Host ("[요약] {0}" -f $sel.요약)
    if ($sel.상세 -and $sel.상세.Trim() -ne "") { Write-Host ("[상세] {0}" -f $sel.상세) }
    Write-Host ""

    $log = $sel.로그파일
    if ($log -and (Test-Path -LiteralPath $log)) {
      Write-Host ("[로그] {0}" -f $log)
      $a = Read-Host "1=로그열기  2=폴더열기  Enter=종료"
      if ($a -eq "1") { Start-Process -FilePath "notepad.exe" -ArgumentList @($log) | Out-Null }
      elseif ($a -eq "2") { Start-Process -FilePath "explorer.exe" -ArgumentList @("/select,`"$log`"") | Out-Null }
    } else {
      Read-Host "Enter=종료"
    }
    exit 0
  }


  # Rollback 실행 비활성(되돌리기 경로 필수)
  if (-not $sel.되돌리기 -or $sel.되돌리기.Trim() -eq "") {
    Write-Host ""
    Write-Host "⛔ 실행 불가: 되돌리기 경로가 없습니다."
    Write-Host "이 상태는 정상입니다. (아직 되돌릴 성공이 없는 상태)"
    Read-Host "Enter"
    continue
  }

  # 미리보기
  $target = Join-Path $RunRoot ("releases\{0}" -f $sel.버전)
  $sum = Get-DiffPreviewSummary -CurrentDir $target -RollbackDir $sel.되돌리기

  Write-Host ""
  Write-Host ("[미리보기] 파일: +{0} / -{1} / 변경 {2}" -f $sum.Added, $sum.Removed, $sum.Changed)

  $big = ($sum.Removed -ge 20) -or ($sum.Changed -ge 200) -or ($sum.Added -ge 500)
  if ($big) { Write-Host "⚠️ 대규모 변경 감지: 실수 가능성 높음. 반드시 확인하고 진행하세요." }

  Write-Host ""
  if ((Read-Host "진짜 ROLLBACK 하려면 ROLLBACK 입력") -ne "ROLLBACK") { Write-Host "취소"; exit 0 }

  Run-Rollback -RunRoot $RunRoot -Version $sel.버전 -RollbackDir $sel.되돌리기
  exit 0
}
