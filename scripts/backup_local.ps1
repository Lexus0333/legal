# Ежедневная резервная копия локальной установки: база n8n (токены аккаунтов), настройки, расписание, журнал, приглашения и файл .env.
# Видео (inbox, done, failed, work, prepared, out) в копию не входят: они большие и лежат на диске как есть.
# Запуск вручную:  powershell -ExecutionPolicy Bypass -File scripts\backup_local.ps1 [-Dest D:\Backups\tt]
# Копия содержит секретные ключи (.env): храните её в надёжном месте и никому не передавайте.
param(
  [string]$Dest = '',
  [int]$Keep = 14
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$infra = Join-Path $root 'infra'
if (-not $Dest) { $Dest = Join-Path $infra 'backups' }
New-Item -ItemType Directory -Force $Dest | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$work = Join-Path $env:TEMP "tt-backup-$stamp"
New-Item -ItemType Directory -Force $work | Out-Null

try {
  # 1) База n8n: целостная копия через VACUUM INTO (работает, пока n8n запущен)
  $container = 'infra-n8n-1'
  $running = docker ps --filter "name=$container" --format '{{.Names}}'
  if ($running -eq $container) {
    $js = @'
const sqlite3 = require('/usr/local/lib/node_modules/n8n/node_modules/sqlite3');
const db = new sqlite3.Database('/home/node/.n8n/database.sqlite');
db.run("VACUUM INTO '/tmp/backup.sqlite'", e => { if (e) { console.error(e.message); process.exit(1); } db.close(); });
'@
    $jsDir = Join-Path $env:TEMP "tt-vac-$stamp"; New-Item -ItemType Directory -Force $jsDir | Out-Null; $jsPath = Join-Path $jsDir 'vac.js'
    Set-Content -Path $jsPath -Value $js -Encoding ascii
    docker exec $container sh -c 'rm -f /tmp/backup.sqlite 2>/dev/null; true' | Out-Null
    docker cp $jsPath "${container}:/tmp/vac.js" | Out-Null
    docker exec $container node /tmp/vac.js
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось сделать копию базы n8n' }
    docker cp "${container}:/tmp/backup.sqlite" (Join-Path $work 'database.sqlite') | Out-Null
    docker exec $container sh -c 'rm -f /tmp/backup.sqlite 2>/dev/null; true' | Out-Null; Remove-Item $jsDir -Recurse -Force -ErrorAction SilentlyContinue
  } else {
    Write-Warning 'Контейнер n8n не запущен: копия базы пропущена.'
  }

  # 2) Настройки и состояние (без больших видеопапок)
  $files = Join-Path $infra 'files'
  $skip = @('inbox','done','failed','work','prepared','out','in','removed','music','fonts')
  $dstFiles = Join-Path $work 'files'
  New-Item -ItemType Directory -Force $dstFiles | Out-Null
  Get-ChildItem $files -Force | Where-Object { $skip -notcontains $_.Name } | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $dstFiles $_.Name) -Recurse -Force
  }
  # 3) Файл с секретами
  foreach ($f in '.env') { $p = Join-Path $infra $f; if (Test-Path $p) { Copy-Item $p (Join-Path $work $f) -Force } }

  # 4) Архив и проверка
  $zip = Join-Path $Dest "tt-backup-$stamp.zip"
  Compress-Archive -Path (Join-Path $work '*') -DestinationPath $zip -Force
  if (-not (Test-Path $zip) -or (Get-Item $zip).Length -lt 1024) { throw 'Архив не создан или пустой' }
  Write-Output "Копия готова: $zip ($([math]::Round((Get-Item $zip).Length/1MB,2)) МБ)"

  # 5) Удаляем старые копии
  Get-ChildItem $Dest -Filter 'tt-backup-*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep | Remove-Item -Force
} finally {
  Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}
