$ErrorActionPreference = 'Stop'
$coinApp = $PSScriptRoot
$coinIcon = Join-Path $coinApp 'bitcoin.ico'
$coinLauncher = Join-Path $coinApp 'launch.pyw'
$coinPython = Join-Path $coinApp '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $coinIcon)) { throw 'bitcoin.ico 파일이 없습니다.' }
if (-not (Test-Path -LiteralPath $coinLauncher)) { throw 'launch.pyw 파일이 없습니다.' }
$coinShell = New-Object -ComObject WScript.Shell
$coinLink = $coinShell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '업비트 자동매매.lnk'))
if (Test-Path -LiteralPath $coinPython) {
    $coinLink.TargetPath = $coinPython
    $coinLink.Arguments = '"' + $coinLauncher + '"'
} else {
    $coinLink.TargetPath = Join-Path $coinApp '실행.vbs'
    $coinLink.Arguments = ''
}
$coinLink.WorkingDirectory = $coinApp
$coinLink.IconLocation = $coinIcon + ',0'
$coinLink.Description = '업비트 v1.8 가상매매 · 약세장 보호'
$coinLink.Save()
Write-Output '바탕화면 비트코인 아이콘 설정 완료'
