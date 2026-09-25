$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot
$version = (Get-Content "VERSION" -Raw).Trim()
$buildDir = Join-Path $projectRoot "build\windows-release"
$packageDir = Join-Path $buildDir "package"
$asset = Join-Path $buildDir "FirmMatterCodeManagement-win-x64.zip"

if (Test-Path $packageDir) { Remove-Item $packageDir -Recurse -Force }
New-Item -ItemType Directory -Force $packageDir | Out-Null

python -m PyInstaller --noconfirm --clean --onefile --name BackendServer `
  --paths backend --paths windows `
  --add-data "frontend/dist;static" --add-data "VERSION;." `
  --collect-all pypinyin --collect-all openpyxl `
  --collect-submodules uvicorn --collect-submodules passlib.handlers `
  windows/server_entry.py
if ($LASTEXITCODE -ne 0) { throw "BackendServer.exe 构建失败" }

python -m PyInstaller --noconfirm --clean --onefile --windowed --name Manager `
  --paths windows windows/manager.py
if ($LASTEXITCODE -ne 0) { throw "Manager.exe 构建失败" }

Copy-Item "VERSION" "dist\VERSION" -Force
$smokeData = Join-Path $projectRoot "dist\data"
New-Item -ItemType Directory -Force $smokeData | Out-Null
$smokeConfig = '{"bind_host":"127.0.0.1","port":18741,"public_host":""}'
[System.IO.File]::WriteAllText((Join-Path $smokeData "server.json"), $smokeConfig, [System.Text.UTF8Encoding]::new($false))
$serverStdout = Join-Path $buildDir "backend-stdout.log"
$serverStderr = Join-Path $buildDir "backend-stderr.log"
$server = Start-Process -FilePath (Join-Path $projectRoot "dist\BackendServer.exe") `
  -WorkingDirectory (Join-Path $projectRoot "dist") `
  -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr -PassThru
try {
  $ready = $false
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 1
    try {
      $status = Invoke-RestMethod -Uri "http://127.0.0.1:18741/api/setup/status" -TimeoutSec 2
      $page = Invoke-WebRequest -Uri "http://127.0.0.1:18741/setup" -TimeoutSec 2
      $schema = Invoke-RestMethod -Uri "http://127.0.0.1:18741/openapi.json" -TimeoutSec 2
      if ($null -ne $status.initialized -and $page.StatusCode -eq 200 -and $schema.info.version -eq $version) {
        $ready = $true
        break
      }
    } catch { }
    if ($server.HasExited) { break }
  }
  if (-not $ready) {
    Write-Host "BackendServer.exe exit code: $($server.ExitCode)"
    if (Test-Path $serverStdout) { Get-Content $serverStdout -Tail 80 }
    if (Test-Path $serverStderr) { Get-Content $serverStderr -Tail 80 }
    throw "BackendServer.exe 启动或前端静态文件检查失败"
  }
} finally {
  if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}

$managerTest = Start-Process -FilePath (Join-Path $projectRoot "dist\Manager.exe") -ArgumentList "--self-test" -Wait -PassThru
if ($managerTest.ExitCode -ne 0) { throw "Manager.exe 自检失败" }

Copy-Item "dist\Manager.exe", "dist\BackendServer.exe", "VERSION" $packageDir -Force
Copy-Item "windows\FirmMatterService.xml", "windows\README-Windows.txt", "windows\安装与初始化.html" $packageDir -Force

$winsw = Join-Path $packageDir "FirmMatterService.exe"
Invoke-WebRequest -Uri "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe" -OutFile $winsw
$winswHash = (Get-FileHash $winsw -Algorithm SHA256).Hash.ToLowerInvariant()
if ($winswHash -ne "05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da") {
  throw "WinSW 下载文件哈希不匹配：$winswHash"
}
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/winsw/winsw/v2.12.0/LICENSE.txt" -OutFile (Join-Path $packageDir "LICENSE-WinSW.txt")

$serviceSmokeDir = Join-Path $buildDir "service-smoke"
New-Item -ItemType Directory -Force $serviceSmokeDir | Out-Null
Copy-Item (Join-Path $packageDir "BackendServer.exe"), $winsw, `
  (Join-Path $packageDir "FirmMatterService.xml"), (Join-Path $packageDir "VERSION") $serviceSmokeDir -Force
$serviceWrapper = Join-Path $serviceSmokeDir "FirmMatterService.exe"
$serviceData = Join-Path $serviceSmokeDir "data"
New-Item -ItemType Directory -Force $serviceData, (Join-Path $serviceData "logs") | Out-Null
$serviceConfig = '{"bind_host":"127.0.0.1","port":18742,"public_host":""}'
[System.IO.File]::WriteAllText((Join-Path $serviceData "server.json"), $serviceConfig, [System.Text.UTF8Encoding]::new($false))
$serviceInstalled = $false
try {
  & $serviceWrapper install | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Windows 服务安装失败" }
  $serviceInstalled = $true
  & $serviceWrapper start | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Windows 服务启动失败" }
  $serviceReady = $false
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 1
    try {
      $status = Invoke-RestMethod -Uri "http://127.0.0.1:18742/api/setup/status" -TimeoutSec 2
      $schema = Invoke-RestMethod -Uri "http://127.0.0.1:18742/openapi.json" -TimeoutSec 2
      if ($null -ne $status.initialized -and $schema.info.version -eq $version) {
        $serviceReady = $true
        break
      }
    } catch { }
  }
  if (-not $serviceReady) { throw "Windows 服务未能提供当前版本 API" }
} finally {
  if ($serviceInstalled) {
    & $serviceWrapper stop | Out-Null
    & $serviceWrapper uninstall | Out-Null
  }
}

if (Test-Path $asset) { Remove-Item $asset }
Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $asset -CompressionLevel Optimal
python -c "import sys; sys.path.insert(0, 'windows'); from pathlib import Path; from manager_core import validate_package; validate_package(Path(sys.argv[1]), sys.argv[2])" $asset $version
if ($LASTEXITCODE -ne 0) { throw "Windows 安装包内容校验失败" }
Write-Host "Windows 安装包已生成：$asset"
