$path = Resolve-Path ".\promote.ps1"
$errs = @()
[System.Management.Automation.Language.Parser]::ParseFile($path,[ref]$null,[ref]$errs) | Out-Null
Write-Host "ParseErrors=$($errs.Count)"
$errs | ForEach-Object { Write-Host $_.Message }
