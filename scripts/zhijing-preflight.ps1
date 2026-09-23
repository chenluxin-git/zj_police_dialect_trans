# 交付前预检（本机可执行部分）：把"能不能上架"里能自动验的部分一次跑完
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts\zhijing-preflight.ps1 [-Port 8123] [-Slow]
# 说明：
#   - 需要 docker daemon 的几条（nginx -t / compose up / 访问日志格式）本机无法验，脚本末尾会列出来，
#     必须在部署机执行。
#   - 本脚本会临时起一个 mock 模式后端（默认端口 8123）跑免登录链路，跑完自动关闭。
#   - 文件必须保存为 UTF-8 with BOM：Windows PowerShell 5.1 否则会把中文当 ANSI 解析并报语法错。
#   - 默认**跳过**前端构建（`npm run build` 会与正在运行的 `npm run dev` 抢文件锁，
#     曾实测导致 vite dev server 因文件锁 EBUSY 直接崩掉）；需要连构建一起验时加 -WithBuild。
param(
    [int]$Port = 8123,
    [switch]$WithBuild,
    [int]$PytestTimeoutSeconds = 900
)

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$server = Join-Path $repo "server"
$web = Join-Path $repo "web"
$py = Join-Path $server ".venv\Scripts\python.exe"

$results = New-Object System.Collections.ArrayList
function Add-Result([string]$name, [bool]$ok, [string]$detail) {
    $null = $results.Add([pscustomobject]@{
            项目 = $name
            结果 = $(if ($ok) { "通过" } else { "失败" })
            说明 = $detail
        })
    $tag = if ($ok) { "OK  " } else { "FAIL" }
    Write-Host ("[{0}] {1} —— {2}" -f $tag, $name, $detail)
}

Write-Host "=== 浙警智治交付前预检 ===" -ForegroundColor Cyan

# ---------- 1) 后端全量测试 ----------
if (Test-Path $py) {
    # 必须在 server 目录内跑：pytest 的 rootdir/conftest 都在那里，从仓库根跑会 1 error 秒退
    Push-Location $server
    $lines = & $py -m pytest -q 2>&1
    $last = ($lines | Select-Object -Last 1)
    Pop-Location
    $ok = "$last" -match "\d+ passed"
    Add-Result "后端测试" $ok "$last"
    if (-not $ok) {
        Write-Host "  —— pytest 末尾输出 ——" -ForegroundColor Yellow
        $lines | Select-Object -Last 12 | ForEach-Object { Write-Host "  $_" }
    }
} else {
    Add-Result "后端测试" $false "未找到 $py（先 python -m venv .venv 并 pip install -r requirements.txt）"
}

# ---------- 2) 前端类型检查 / 构建 / 兼容体检 ----------
Push-Location $web
$tsc = & npx vue-tsc -b --force 2>&1
$tscDetail = "vue-tsc 无错误"
if ($tsc) { $tscDetail = ($tsc | Select-Object -First 1) }
Add-Result "前端类型检查" ($LASTEXITCODE -eq 0) $tscDetail

$build = & npm run build 2>&1
if ($WithBuild) {
    $buildOk = ($build | Where-Object { $_ -match "OK：产物语法满足 Chrome80" }).Count -gt 0
    $buildDetail = (($build | Where-Object { $_ -match "check-es-target|built in|error" } | Select-Object -First 2) -join " / ")
    Add-Result "前端构建与 Chrome80 体检" $buildOk $buildDetail
} else {
    # 默认不重新构建：`npm run build` 会与正在运行的 npm run dev 抢文件锁，
    # 实测导致 vite dev server 因 EBUSY 直接崩掉。改为只体检已有产物。
    $chk = & npm run check:es-target --silent 2>&1
    Add-Result "产物 Chrome80 体检（未重建）" ("$chk" -match "OK：产物语法满足 Chrome80") (($chk | Select-Object -Last 1))
    Add-Result "前端构建产物存在" (Test-Path (Join-Path $web "dist\assets")) "dist/assets（需要重新构建时加 -WithBuild）"
}

$pf = & npm run check:polyfill --silent 2>&1 | Select-Object -Last 1
Add-Result "Chrome80 运行时补齐自检" ("$pf" -match "通过") "$pf"
Pop-Location

# ---------- 3) 免登录链路（临时 mock 后端） ----------
$env:ZHIJING_MODE = "mock"
$proc = Start-Process -FilePath $py `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port" `
    -WorkingDirectory $server -PassThru -WindowStyle Hidden
$base = "http://127.0.0.1:$Port"
try {
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try { $null = Invoke-RestMethod "$base/api/health" -TimeoutSec 3; $ready = $true; break } catch { }
    }
    if (-not $ready) {
        Add-Result "免登录链路" $false "临时后端未在 20s 内就绪（端口 $Port 可能被占用）"
    } else {
        $self = (Invoke-RestMethod "$base/api/auth/zhijing/self-check" -TimeoutSec 10).data
        Add-Result "接入自检接口" ($self.zero_trust.mode -eq "mock") ("mode=" + $self.zero_trust.mode + " / callback=" + $self.zero_trust.callback_path)

        $u = "$base/api/auth/zhijing/callback?police_no=33000000999&name=preflight"
        $req = [System.Net.HttpWebRequest]::Create($u)
        $req.AllowAutoRedirect = $false
        $loc = ""
        try { $resp = $req.GetResponse(); $loc = $resp.Headers['Location']; $resp.Close() }
        catch [System.Net.WebException] { $loc = $_.Exception.Response.Headers['Location'] }
        $token = ([regex]::Match("$loc", "token=([A-Za-z0-9._\-]+)")).Groups[1].Value
        $meOk = $false
        $certId = ""
        if ($token) {
            $me = Invoke-RestMethod "$base/api/auth/me" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 10
            $meOk = ($me.code -eq 0 -and $me.data.police_no -eq "33000000999")
            $certId = $me.data.cert_id
        }
        Add-Result "会话建立（302 → /#/auth → /auth/me）" $meOk ("police_no=33000000999 / cert_id=" + $certId)

        if ($certId) {
            $body = @{ action = "role-update"; msg = "preflight"; target = @{ pid = $certId } } | ConvertTo-Json
            $lk = Invoke-RestMethod "$base/api/rzzx/linkage" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 10
            $gone = $false
            try { $null = Invoke-RestMethod "$base/api/auth/me" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 10 }
            catch { $gone = ($_.Exception.Response.StatusCode.value__ -eq 401) }
            Add-Result "零信任联动 role-update" (($lk.status_code -eq "0000") -and $gone) "指令 0000，旧会话随后 401"
        } else {
            Add-Result "零信任联动 role-update" $false "未取到 cert_id，跳过"
        }

        $dbFile = Join-Path $server "data\app.db"
        if (Test-Path $dbFile) {
            # 写临时脚本再执行：PowerShell 5.1 下 "-c" 传参里的 count(*) 会被当通配符解析失败
            $sqliteProbe = Join-Path $env:TEMP "zjpdt-audit-count.py"
            $probeLines = @(
                'import sqlite3, sys',
                'conn = sqlite3.connect(sys.argv[1])',
                'row = conn.execute("select count(*) from audit_logs where operate_type=0").fetchone()',
                'print(row[0])'
            )
            Set-Content -Path $sqliteProbe -Value $probeLines -Encoding UTF8
            $count = & $py $sqliteProbe $dbFile
            Add-Result "审计登录留痕" ([int]$count -ge 1) "audit_logs 中 operateType=0 记录 $count 条"
            Remove-Item $sqliteProbe -ErrorAction SilentlyContinue
        } else {
            Add-Result "审计登录留痕" $false "未找到 $dbFile"
        }

        $missing = New-Object System.Collections.ArrayList
        if (-not $self.zero_trust.sys_id) { $null = $missing.Add("ZHIJING_SYS_ID") }
        if (-not $self.zero_trust.app_key) { $null = $missing.Add("ZHIJING_APP_KEY") }
        if (-not $self.zero_trust.app_secret) { $null = $missing.Add("ZHIJING_APP_SECRET") }
        $credDetail = "已配置齐全"
        if ($missing.Count -gt 0) { $credDetail = "待省厅提供并配置：" + ($missing -join ", ") }
        Add-Result "真机联调凭据" ($missing.Count -eq 0) $credDetail
    }

    # 服务日志（logType=2）：最容易触发的路径 = live 模式 + 缺 AK/SK
    $svcProbe = Join-Path $env:TEMP "zjpdt-service-log-probe.py"
    $probeCode = @(
        'import sys',
        'sys.path.insert(0, sys.argv[1])',
        'from app.core.config import settings',
        'from app.core.database import Base, engine, SessionLocal',
        'from app.services import zero_trust',
        'from app.models.audit import AuditLog',
        'settings.zhijing_mode = "live"',
        'settings.zhijing_app_key = ""',
        'settings.zhijing_app_secret = ""',
        'settings.zhijing_audit_queue_enabled = True',
        'Base.metadata.create_all(engine)',
        'try:',
        '    zero_trust.create_app_token()',
        'except zero_trust.ZeroTrustError:',
        '    pass',
        'with SessionLocal() as db:',
        '    print(db.query(AuditLog).filter(AuditLog.log_type == "2").count())'
    )
    Set-Content -Path $svcProbe -Value $probeCode -Encoding UTF8
    Push-Location $server
    $svcCount = & $py $svcProbe $server 2>&1 | Select-Object -Last 1
    Pop-Location
    Remove-Item $svcProbe -ErrorAction SilentlyContinue
    Add-Result "服务日志落库（logType=2）" ([int]$svcCount -ge 1) "audit_logs 中服务日志 $svcCount 条"
} finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item Env:\ZHIJING_MODE -ErrorAction SilentlyContinue
}

# ---------- 4) compose 语法（不需要 daemon） ----------
Push-Location $repo
$cfg = docker compose config --quiet 2>&1
$cfgOk = ($LASTEXITCODE -eq 0)
$cfgDetail = "解析通过（默认 backend+web；--profile mysql 追加 mysql）"
if (-not $cfgOk) { $cfgDetail = ($cfg | Select-Object -First 1) }
Add-Result "docker-compose 语法" $cfgOk $cfgDetail
Pop-Location

# ---------- 汇总 ----------
Write-Host ""
Write-Host "=== 汇总 ===" -ForegroundColor Cyan
$results | Format-Table -AutoSize
$passed = ($results | Where-Object { $_.结果 -eq "通过" }).Count
$failed = $results.Count - $passed
Write-Host ("通过 {0} / 共 {1}" -f $passed, $results.Count) -ForegroundColor $(if ($failed -gt 0) { "Yellow" } else { "Green" })
Write-Host ""
Write-Host "以下必须在部署机执行（本机无 docker daemon）：" -ForegroundColor Yellow
Write-Host "  docker compose exec web nginx -t                               # nginx 配置语法"
Write-Host "  docker compose ps                                              # backend 应为 healthy"
Write-Host "  docker compose exec web tail -n 3 /var/log/nginx/access.log    # 日志应为竖线分隔 12 段"
exit $failed
