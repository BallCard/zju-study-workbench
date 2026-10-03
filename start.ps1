param([switch]$Demo, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$previousDirectory = Get-Location
try {
    Set-Location -LiteralPath $PSScriptRoot
    if (-not (Test-Path -LiteralPath 'dist/index.html')) {
        throw 'Build the UI first; follow the setup steps in README.md.'
    }
    $pythonExecutable = if (Test-Path -LiteralPath '.venv/Scripts/python.exe') { '.venv/Scripts/python.exe' } else { 'python' }
    $serverArguments = @('-m', 'server', '--port', "$Port", '--open')
    if ($Demo) { $serverArguments += '--demo' }
    & $pythonExecutable @serverArguments
    if ($LASTEXITCODE -ne 0) { throw 'Server failed. Check Python dependencies and the selected port.' }
} finally {
    Set-Location -LiteralPath $previousDirectory
}
