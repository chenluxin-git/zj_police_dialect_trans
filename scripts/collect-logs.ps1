<#
.SYNOPSIS
  内网部署一键收集日志（排障回传用）。

.DESCRIPTION
  把排障需要的全部信息打包成一个 zip，直接回传开发即可定位问题。

  收集内容：
    - 运行期自检      GET /api/diag?refresh=1（数据库/外部服务可达性/审计积压/日志大小）
    - 后端日志        startup / request / app / error .log + startup-report.json
    - nginx 日志      access.log / error.log
    - 容器状态        docker ps / inspect / 容器最近 2000 行 stdout
    - 环境与版本      系统、Python/Node/Docker、磁盘、监听端口、证书有效期
    - 配置快照        环境变量文件（**已脱敏**）+ 关键变量"配没配"

  注意：本文件含中文，必须保存为 **UTF-8 with BOM**，
  否则 Windows PowerShell 5.1 会按 ANSI 解码导致解析失败（Unexpected token）。

.PARAMETER BaseUrl
  应用访问地址，默认 http://127.0.0.1

.PARAMETER OutDir
  输出目录，默认 ./logpack

.PARAMETER Since
  docker logs 时间范围，默认 24h

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File ./scripts/collect-logs.ps1
  powershell -ExecutionPolicy Bypass -File ./scripts/collect-logs.ps1 -BaseUrl https://10.0.0.5 -Since 72h
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1",
    [string]$OutDir = "./logpack",
    [string]$Since = "24h"
)

$ErrorActionPreference = "Continue"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$work = Join-Path $OutDir "logpack-$stamp"

function Say([string]$m) { Write-Host "[collect] $m" }

function EnsureDir([string]$p) {
    if ($p -and -not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

# 敏感值掩码（PS 5.1 安全写法：不用 [regex]::Replace 的 scriptblock 重载）
function Mask-Secrets([string]$text) {
    if ([string]::IsNullOrEmpty($text)) { return $text }
    $names = @(
        'app_?secret', 'securekey', 'secret_?key', 'password',
        'mysql_root_password', 'mysql_password',
        'rzzx-usertoken', 'rzzx-apptoken', 'authorization',
        'token', 'callersign', 'sign'
    )
    foreach ($n in $names) {
        $pattern = '(?i)(' + $n + ')(\s*[=:]\s*)([^\s"''&,}]+)'
        $evaluator = {
            param($m)
            $v = $m.Groups[3].Value
            if ($v.Length -le 4) {
                return $m.Groups[1].Value + $m.Groups[2].Value + '****'
            }
            return $m.Groups[1].Value + $m.Groups[2].Value + $v.Substring(0, 2) + '****' + $v.Substring($v.Length - 2)
        }
        $text = [regex]::Replace($text, $pattern, $evaluator)
    }
    return $text
}

function Save-Text([string]$content, [string]$path, [string]$label) {
    EnsureDir (Split-Path $path -Parent)
    try {
        Set-Content -Path $path -Value (Mask-Secrets $content) -Encoding UTF8
        Say "  OK  $label"
    } catch {
        Say "  FAIL $label -> $($_.Exception.Message)"
    }
}

EnsureDir $work
Say "out dir: $work"

# ---------------------------------------------------------------- 0) 汇总头
$header = New-Object System.Collections.Generic.List[string]
$header.Add("收集时间 : " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$header.Add("主机名   : " + $env:COMPUTERNAME)
$header.Add("访问地址 : " + $BaseUrl)
$header.Add("日志范围 : " + $Since)
$header.Add("")
$header.Add("== 建议按顺序看 ==")
$header.Add("  1. backend/startup.log     启动自检（配置齐备性 + 外部服务可达性）")
$header.Add("  2. backend/request.log     一行一请求；搜 REQ-EXC / SLOW / 401 / 502")
$header.Add("  3. nginx/error.log         upstream 连接失败、DNS 解析、TLS 握手")
$header.Add("  4. nginx/access.log        搜 trace= 对齐后端；rz=1 表示平台带了令牌")
$header.Add("  5. diag.json               当前数据库与外部服务状态")
$header.Add("  6. config/                 环境变量是否配全（已脱敏）")
Save-Text ($header -join "`r`n") (Join-Path $work "00-read-me-first.txt") "00-read-me-first.txt"

# ---------------------------------------------------------------- 1) 运行期自检
Say "1/6 runtime self-check"
try {
    $diag = Invoke-RestMethod -Uri "$BaseUrl/api/diag?refresh=1" -TimeoutSec 60 -ErrorAction Stop
    Save-Text ($diag | ConvertTo-Json -Depth 8) (Join-Path $work "diag.json") "diag.json"
} catch {
    Save-Text ("调用 " + $BaseUrl + "/api/diag 失败`r`n" + $_.Exception.Message + "`r`n（若后端未起或端口不通，这本身就是关键线索）") `
        (Join-Path $work "diag.json") "diag.json (failed)"
    try {
        $h = Invoke-WebRequest -Uri "$BaseUrl/api/health" -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
        Save-Text ("health " + $h.StatusCode + " : " + $h.Content) (Join-Path $work "health.txt") "health.txt"
    } catch {
        Save-Text ("health 也不通：" + $_.Exception.Message) (Join-Path $work "health.txt") "health.txt (failed)"
    }
}

# ---------------------------------------------------------------- 2) 日志文件
Say "2/6 log files"
$candidateLogs = @(
    "logs/backend/startup.log", "logs/backend/startup-report.json",
    "logs/backend/request.log", "logs/backend/app.log", "logs/backend/error.log",
    "logs/nginx/access.log", "logs/nginx/error.log",
    "server/logs/startup.log", "server/logs/startup-report.json",
    "server/logs/request.log", "server/logs/app.log", "server/logs/error.log"
)
$foundAny = $false
foreach ($rel in $candidateLogs) {
    if (Test-Path $rel) {
        $foundAny = $true
        $norm = $rel -replace '^\./', ''
        $norm = $norm -replace '^server/', 'backend/'
        $dest = Join-Path $work ($norm -replace '/', '\')
        EnsureDir (Split-Path $dest -Parent)
        Copy-Item $rel $dest -Force
        Say "  OK  $rel -> $dest"
    }
}
if (-not $foundAny) {
    Say "  WARN no log files found; if running in container check ./logs mount"
}

# ---------------------------------------------------------------- 3) 容器状态
Say "3/6 docker state"
$hasDocker = $null -ne (Get-Command docker -ErrorAction SilentlyContinue)
if ($hasDocker) {
    try {
        $ps = (docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1 | Out-String)
        Save-Text $ps (Join-Path $work "docker\ps.txt") "docker ps"
    } catch { Say "  FAIL docker ps" }

    foreach ($c in @("zjpdt-backend", "zjpdt-web", "zjpdt-mysql")) {
        try {
            $insp = (docker inspect $c 2>&1 | Out-String)
            Save-Text $insp (Join-Path $work "docker\inspect-$c.json") "inspect $c"
        } catch { }
        try {
            $lg = (docker logs --since $Since --tail 2000 $c 2>&1 | Out-String)
            Save-Text $lg (Join-Path $work "docker\logs-$c.txt") "logs $c"
        } catch { Say "  WARN container $c not found / not running" }
    }
    try {
        $cfg = (docker compose config 2>&1 | Out-String)
        Save-Text $cfg (Join-Path $work "docker\compose-config.yaml") "compose config"
    } catch { }
} else {
    Say "  WARN docker not installed, skipped"
}

# ---------------------------------------------------------------- 4) 环境与版本
Say "4/6 env and versions"
$e = New-Object System.Collections.Generic.List[string]
$e.Add("== OS ==")
try { $e.Add((Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber | Format-List | Out-String)) } catch { }
$e.Add("== PowerShell ==")
$e.Add($PSVersionTable.PSVersion.ToString())
$e.Add("== Python ==")
try { $e.Add((& python --version 2>&1 | Out-String)) } catch { $e.Add("python unavailable") }
$e.Add("== Node ==")
try { $e.Add((& node --version 2>&1 | Out-String)) } catch { $e.Add("node unavailable") }
$e.Add("== Docker ==")
if ($hasDocker) { try { $e.Add((docker version 2>&1 | Out-String)) } catch { } }
$e.Add("== Disk ==")
try {
    $e.Add((Get-PSDrive -PSProvider FileSystem |
        Select-Object Name, @{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}}, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}} |
        Format-Table | Out-String))
} catch { }
$e.Add("== Listening ports (80/443/8000/3306) ==")
try {
    $e.Add((Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in 80,443,8000,3306 } |
        Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table | Out-String))
} catch { $e.Add("(no permission)") }
$e.Add("== Certificates ==")
foreach ($cert in @("deploy/certs/cert.pem", "deploy/certs/key.pem")) {
    if (Test-Path $cert) {
        try {
            $c = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2((Resolve-Path $cert).Path)
            $e.Add("$cert : NotBefore=$($c.NotBefore) NotAfter=$($c.NotAfter) Subject=$($c.Subject)")
        } catch { $e.Add("$cert : read failed $($_.Exception.Message)") }
    } else {
        $e.Add("$cert : NOT FOUND")
    }
}
Save-Text ($e -join "`r`n") (Join-Path $work "env-system.txt") "env-system.txt"

# ---------------------------------------------------------------- 5) 配置快照
Say "5/6 config snapshot (masked)"
$foundEnv = $false
foreach ($rel in @("server/.env", "server/.env.docker", "server/.env.zhijing.docker", ".env")) {
    if (Test-Path $rel) {
        $foundEnv = $true
        $name = ($rel -replace '[/\\]', '_') + ".masked"
        Save-Text (Get-Content $rel -Raw -Encoding UTF8) (Join-Path $work "config\$name") "config $rel"
    }
}
if (-not $foundEnv) { Say "  WARN no .env found" }

# 关键变量存在性（只记"配没配"+长度，不记值）
$presence = New-Object System.Collections.Generic.List[string]
$keys = @(
    "ZHIJING_MODE", "ZHIJING_LOGIN_SOURCE", "ZHIJING_LEGACY_LOGIN", "ZHIJING_SYS_ID",
    "ZHIJING_APP_KEY", "ZHIJING_APP_SECRET", "ZHIJING_AUTH_BUTTON", "ZHIJING_DQXTBS",
    "ZHIJING_RZ_URL", "ZHIJING_QX_URL", "ZHIJING_AUDIT_URL", "ZHIJING_AUDIT_ENABLED",
    "ZHIJING_ORG_SYNC_ENABLED", "ZHIJING_ORG_BASE_URL",
    "DATABASE_URL", "FRONTEND_BASE", "SECRET_KEY", "SCAN_ROOT", "CORS_ORIGINS"
)
foreach ($k in $keys) {
    $v = [Environment]::GetEnvironmentVariable($k)
    if ([string]::IsNullOrEmpty($v)) { $presence.Add("$k = <NOT SET>") }
    else { $presence.Add("$k = <set, len=$($v.Length)>") }
}
Save-Text ($presence -join "`r`n") (Join-Path $work "config\env-var-presence.txt") "env-var-presence.txt"

# ---------------------------------------------------------------- 6) 打包
Say "6/6 packaging"
$zip = "$work.zip"
try {
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $work "*") -DestinationPath $zip -Force
    Write-Host ""
    Write-Host "DONE. Send this file back:" -ForegroundColor Green
    Write-Host ("  " + (Resolve-Path $zip).Path) -ForegroundColor Green
    Write-Host ""
    Write-Host "Before sending: if logs contain personal data (ID card / police no / phone)," -ForegroundColor Yellow
    Write-Host "handle per your confidentiality rules." -ForegroundColor Yellow
} catch {
    Say "  FAIL packaging: $($_.Exception.Message); dir kept at $work"
}
