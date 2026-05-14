param(
  [string]$DataRoot = "data\\proctoring"
)

$resolved = Resolve-Path -LiteralPath $DataRoot -ErrorAction SilentlyContinue
if (-not $resolved) {
  Write-Host "Path not found: $DataRoot"
  exit 0
}

Write-Host "Deleting local training data under: $($resolved.Path)"
Remove-Item -LiteralPath $resolved.Path -Recurse -Force
Write-Host "Done."
