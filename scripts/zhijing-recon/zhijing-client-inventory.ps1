# 浙警智治 · 终端与电子证书介质盘点（只读）
#
# 用途：回答三个问题
#   1) 终端能不能满足上架硬要求（Chrome80 及以上）/ 有没有证书客户端中间件；
#   2) 本机证书存储里到底装着哪些证书（签发者、主体、有效期、是否带私钥）——
#      据此判断民警手上"电子证书"的实际形态与 CA 来源；
#   3) 网络与时间环境（代理、hosts 映射、时钟同步）——令牌含毫秒时间戳，时钟偏移会直接导致认证失败。
#
# 红线（务必遵守）：
#   - 本脚本**只读**：只读证书的 Subject/Issuer/有效期/指纹/是否带私钥；
#     **绝不导出、不复制、不读取私钥内容**（不调用 Export-Certificate / certutil -exportPFX 等任何导出动作）。
#   - 不访问网络、不扫描端口、不探测平台地址（网络连通性请用 zhijing_recon.py check）。
#   - 产物含终端与人员证书标识，属敏感材料：**留在内网**，不要外发。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\zhijing-client-inventory.ps1 [-Out .\recon-out]
#
# 注意：文件必须保存为 UTF-8 with BOM，否则 Windows PowerShell 5.1 会把中文按 ANSI 解析并报语法错。
param(
    [string]$Out = ".\recon-out"
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not (Test-Path $Out)) { New-Item -ItemType Directory -Path $Out -Force | Out-Null }
$Out = (Resolve-Path $Out).Path

$script:Result = [ordered]@{
    "工具"          = "zhijing-client-inventory.ps1"
    "生成时间"      = (Get-Date).ToString("s")
    "计算机名"      = $env:COMPUTERNAME
    "当前用户"      = $env:USERNAME
    "是否管理员"    = $false
    "基础环境"      = $null
    "浏览器"        = @()
    "证书客户端"    = @()
    "证书存储"      = @()
    "网络配置"      = $null
    "问题清单"      = @()
}

function Add-Finding([string]$level, [string]$text) {
    $script:Result["问题清单"] += [pscustomobject]@{ 级别 = $level; 说明 = $text }
    $color = switch ($level) { "阻断" { "Red" } "警告" { "Yellow" } default { "Gray" } }
    Write-Host ("  [{0}] {1}" -f $level, $text) -ForegroundColor $color
}

# 从 DN 里取 CN，便于打印；必须在首次调用之前定义（PowerShell 按执行顺序生效）
function Get-ShortName([string]$dn) {
    if (-not $dn) { return "" }
    $m = [regex]::Match($dn, "CN=([^,]+)")
    if ($m.Success) { return $m.Groups[1].Value }
    return $dn
}

# 证书类软件判据：**不要用 "CA"/"KEY" 这类两字母关键词**——"CA" 会命中 Applic*ca*tion，
# 把 AMD/NVIDIA/Windows SDK 全捞进来（实测踩过）。用词组 + 常见公安 CA 厂商名。
function Test-CertSoftware([string]$name) {
    if (-not $name) { return $false }
    foreach ($k in @("证书", "密钥", "密匙", "令牌", "公安", "警务", "浙政钉",
            "UKey", "USBKey", "PKI", "SafeNet", "ePass", "eToken",
            "数字签名", "身份认证", "吉大正元", "格尔", "海泰", "握奇", "龙脉",
            "江南天安", "三未信安")) {
        if ($name -like ("*" + $k + "*")) { return $true }
    }
    return $false
}

# Windows 自带/厂商无关服务，避免把 CertPropSvc、TokenBroker 这类当成"证书客户端"
$script:BuiltinSvc = @("CertPropSvc", "IKEEXT", "KeyIso", "TokenBroker", "CryptSvc",
    "EapHost", "Wlansvc", "SCPolicySvc", "dot3svc", "SharedAccess", "AsusCertService",
    "LocalKdc")   # LocalKdc 显示名含"密钥发行中心"，会误命中"密钥"

Write-Host "=== 浙警智治 · 终端与电子证书介质盘点（只读）===" -ForegroundColor Cyan
Write-Host "输出目录：$Out`n"

# --------------------------------------------------------------------------- #
# 0) 权限
# --------------------------------------------------------------------------- #
$isAdmin = $false
try {
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = (New-Object System.Security.Principal.WindowsPrincipal($id)).IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { }
$script:Result["是否管理员"] = $isAdmin
Write-Host ("管理员权限：{0}" -f $(if ($isAdmin) { "是（可读本机计算机证书存储）" } else { "否（仅读当前用户证书存储）" }))

# --------------------------------------------------------------------------- #
# 1) 基础环境与时钟
# --------------------------------------------------------------------------- #
Write-Host "`n--- 1) 基础环境与时钟 ---" -ForegroundColor Cyan
$os = $null
try { $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue } catch { }
$tz = try { (Get-TimeZone) } catch { $null }

# 操作系统名：优先注册表（不依赖 WMI 权限，WMI 被策略拒绝时仍能报出来）
$osName = ""
if ($os -and $os.Caption) { $osName = "$($os.Caption) $($os.Version)" }
if (-not $osName) {
    try {
        $cv = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -ErrorAction Stop
        $ubr = if ($cv.PSObject.Properties.Name -contains "UBR") { $cv.UBR } else { "" }
        $osName = "$($cv.ProductName) $($cv.DisplayVersion) (Build $($cv.CurrentBuild).$ubr)"
    } catch { $osName = "未知（WMI 与注册表均读取失败）" }
}

$w32 = ""
try { $w32 = (w32tm /query /status 2>&1 | Out-String) } catch { $w32 = "w32tm 不可用" }
$lastSync = ""
$srcLine = ($w32 -split "`r?`n" | Where-Object { $_ -match "上次成功同步时间|Last Successful Sync" } | Select-Object -First 1)
if ($srcLine) { $lastSync = $srcLine.Trim() }

$timeOffset = $null
try {
    if ($tz) { $timeOffset = $tz.BaseUtcOffset.TotalMinutes }
} catch { }

$script:Result["基础环境"] = [ordered]@{
    "操作系统"     = $osName
    "系统架构"     = $env:PROCESSOR_ARCHITECTURE
    "时区"         = if ($tz) { $tz.Id } else { "未知" }
    "UTC偏移分钟"  = $timeOffset
    "本机时间"     = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "时间同步"     = $lastSync
    "时间同步原文" = $w32.Trim()
}
Write-Host ("  OS：{0}" -f $script:Result["基础环境"]["操作系统"])
Write-Host ("  时区：{0}（UTC{1} 分钟）  本机时间：{2}" -f `
        $script:Result["基础环境"]["时区"], $timeOffset, $script:Result["基础环境"]["本机时间"])
if ($lastSync) { Write-Host ("  {0}" -f $lastSync) }

if ($timeOffset -ne $null -and $timeOffset -ne 480) {
    Add-Finding "警告" ("时区 UTC 偏移 {0} 分钟，非中国时区(+480)；平台令牌/审计时间戳按中国时区，建议统一为 China Standard Time" -f $timeOffset)
}
if ($lastSync -match "从未|Never|错误|error") {
    Add-Finding "警告" "本机从未成功同步过时间；令牌含毫秒时间戳，时钟偏移会导致认证/续期失败，请先同步 NTP"
} else {
    Write-Host "  提示：脚本只报告同步状态，不判断偏差；若认证报令牌类错误，请先核对时钟。" -ForegroundColor DarkGray
}

# --------------------------------------------------------------------------- #
# 2) 浏览器版本（上架硬要求：Chrome80 及以上；最低 Chromium 49）
# --------------------------------------------------------------------------- #
Write-Host "`n--- 2) 浏览器版本（硬要求 Chrome80+）---" -ForegroundColor Cyan

function Get-ExeVersion([string]$exe) {
    foreach ($root in @(
            "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
            "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths")) {
        $key = Join-Path $root $exe
        if (Test-Path $key) {
            try {
                $p = (Get-ItemProperty -Path $key -ErrorAction Stop)."(default)"
                if ($p) {
                    $p = $p.Trim('"')
                    if (Test-Path $p) { return (Get-Item $p).VersionInfo.ProductVersion }
                }
            } catch { }
        }
    }
    return ""
}

$chromeVer = Get-ExeVersion "chrome.exe"
$edgeVer = Get-ExeVersion "msedge.exe"
$ieVer = ""
try {
    $ieVer = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Internet Explorer" -ErrorAction Stop).svcVersion
} catch { }

foreach ($br in @(
        [pscustomobject]@{ 名称 = "Chrome"; 版本 = $chromeVer },
        [pscustomobject]@{ 名称 = "Edge"; 版本 = $edgeVer },
        [pscustomobject]@{ 名称 = "IE"; 版本 = $ieVer })) {
    if (-not $br.版本) { continue }
    $script:Result["浏览器"] += $br
    $major = 0
    if ($br.版本 -match "^(\d+)") { $major = [int]$Matches[1] }
    $verdict = ""
    if ($br.名称 -eq "Chrome" -or $br.名称 -eq "Edge") {
        if ($major -ge 80) { $verdict = "满足上架要求(>=80)" }
        elseif ($major -ge 49) { $verdict = "低于上架要求：需升级到 Chrome80+" }
        else { $verdict = "远低于最低内核要求(Chromium 49)" }
        if ($major -lt 80) { Add-Finding "警告" ("{0} 版本 {1} 低于上架硬要求 Chrome80，需升级" -f $br.名称, $br.版本) }
    } else { $verdict = "已淘汰，不应作为访问入口" }
    Write-Host ("  {0}：{1} —— {2}" -f $br.名称, $br.版本, $verdict)
}
if (-not $chromeVer) { Write-Host "  未检测到 Chrome（可能未安装或注册表无 App Paths 项）" -ForegroundColor DarkGray }

# --------------------------------------------------------------------------- #
# 3) 证书客户端 / 中间件（电子证书的"介质驱动"通常在这里）
# --------------------------------------------------------------------------- #
Write-Host "`n--- 3) 证书客户端 / 中间件 / 相关终端软件 ---" -ForegroundColor Cyan
$uninstallRoots = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
$apps = @()
foreach ($r in $uninstallRoots) {
    try {
        $apps += Get-ItemProperty $r -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName } |
            Select-Object DisplayName, DisplayVersion, Publisher
    } catch { }
}
$apps = $apps | Sort-Object DisplayName -Unique

$hits = @()
foreach ($a in $apps) {
    if (Test-CertSoftware $a.DisplayName) { $hits += $a }
}
# 驱动/服务形态的介质支持
$svcHits = @()
try {
    $svcHits = Get-Service -ErrorAction SilentlyContinue |
        Where-Object {
            $script:BuiltinSvc -notcontains $_.Name -and
            ((Test-CertSoftware $_.DisplayName) -or (Test-CertSoftware $_.Name))
        } |
        Select-Object Name, DisplayName, Status
} catch { }

if ($hits) {
    foreach ($h in $hits) {
        $script:Result["证书客户端"] += [pscustomobject]@{
            名称 = $h.DisplayName; 版本 = $h.DisplayVersion; 发布者 = $h.Publisher; 类型 = "已安装程序"
        }
        Write-Host ("  [程序] {0} {1} —— {2}" -f $h.DisplayName, $h.DisplayVersion, $h.Publisher)
    }
}
foreach ($s in $svcHits) {
    $script:Result["证书客户端"] += [pscustomobject]@{
        名称 = $s.DisplayName; 版本 = ""; 发布者 = $s.Name; 类型 = "服务"
    }
    Write-Host ("  [服务] {0} ({1}) —— {2}" -f $s.DisplayName, $s.Name, $s.Status)
}
if (-not $hits -and -not $svcHits) {
    Write-Host "  未发现证书类客户端/介质服务。" -ForegroundColor DarkGray
    Add-Finding "警告" "本机未检测到证书客户端/介质服务：若民警实际是插 UKey/证书介质登录，请在其他终端复核，或确认登录确由平台侧完成（免二次登录）"
}

# --------------------------------------------------------------------------- #
# 4) 证书存储（只读；绝不导出私钥）
# --------------------------------------------------------------------------- #
Write-Host "`n--- 4) 证书存储盘点（只读，不导出任何私钥）---" -ForegroundColor Cyan
$stores = @("Cert:\CurrentUser\My")
if ($isAdmin) { $stores += "Cert:\LocalMachine\My" }
$storeRows = @()
$anyStoreError = $false
foreach ($store in $stores) {
    if (-not (Test-Path $store)) { continue }
    $certs = @()
    $storeErr = ""
    # 读失败必须区分于"真的 0 张"，否则会误报"没有带私钥的证书"
    try { $certs = @(Get-ChildItem -Path $store -ErrorAction Stop) }
    catch { $storeErr = $_.Exception.Message; $anyStoreError = $true }
    $thisStore = @()
    if ($storeErr) {
        Write-Host ("  {0}：读取失败 —— {1}" -f $store, $storeErr) -ForegroundColor Yellow
        Add-Finding "警告" ("{0} 读取失败（{1}）：本机证书情况未知，必要时以管理员身份重跑" -f $store, $storeErr)
    } else {
        Write-Host ("  {0}：共 {1} 张证书" -f $store, $certs.Count)
    }
    foreach ($c in $certs) {
        $row = [pscustomobject]@{
            存储    = $store
            主体    = $c.Subject
            签发者  = $c.Issuer
            生效    = if ($c.NotBefore) { $c.NotBefore.ToString("yyyy-MM-dd") } else { "" }
            失效    = if ($c.NotAfter) { $c.NotAfter.ToString("yyyy-MM-dd") } else { "" }
            是否过期 = if ($c.NotAfter) { ($c.NotAfter -lt (Get-Date)) } else { $null }
            带私钥  = $c.HasPrivateKey
            指纹    = $c.Thumbprint
            友好名  = $c.FriendlyName
        }
        $thisStore += $row
        # 只打印摘要，避免刷屏；完整内容在 JSON/Markdown 里
        Write-Host ("    - {0} | 签发者={1} | 有效期至 {2} | 私钥={3}" -f `
                (Get-ShortName $c.Subject), (Get-ShortName $c.Issuer), $row.失效, $row.带私钥)
    }
    $storeRows += $thisStore
    $script:Result["证书存储"] += [pscustomobject]@{
        存储 = $store; 证书数 = $certs.Count; 读取错误 = $storeErr; 证书 = $thisStore
    }
}

# 汇总：签发者分布 + 过期/无密钥提示
$allCerts = @($storeRows)
if ($allCerts.Count -gt 0) {
    Write-Host "`n  -- 签发者分布（判断证书由谁签发）--"
    $allCerts | Group-Object 签发者 | Sort-Object Count -Descending | ForEach-Object {
        Write-Host ("    {0}  ×{1}" -f (Get-ShortName $_.Name), $_.Count)
    }
    $expired = @($allCerts | Where-Object { $_.是否过期 -eq $true })
    if ($expired.Count -gt 0) {
        Add-Finding "警告" ("当前证书存储中有 {0} 张已过期证书（上架/联调前应清理或更换）" -f $expired.Count)
    }
    $withKey = @($allCerts | Where-Object { $_.带私钥 -eq $true })
    $noKey = @($allCerts | Where-Object { $_.带私钥 -eq $false })
    Write-Host ("    带私钥（可用于签名/认证）：{0} 张；不带私钥：{1} 张" -f $withKey.Count, $noKey.Count)
    if ($withKey.Count -eq 0 -and -not $anyStoreError) {
        Add-Finding "警告" '本机证书存储中没有"带私钥"的个人证书：若本机需承担证书登录，说明介质/证书未正确安装'
    }
} elseif (-not $anyStoreError) {
    Write-Host "  证书存储为空。" -ForegroundColor DarkGray
    Add-Finding "提示" "本机证书存储为空：若登录由平台侧完成（免二次登录）属正常；若本机需插证书介质登录，则介质未安装"
}

# --------------------------------------------------------------------------- #
# 5) 网络配置（代理 / hosts 映射，不发起任何连接）
# --------------------------------------------------------------------------- #
Write-Host "`n--- 5) 网络配置（只读；不发起连接）---" -ForegroundColor Cyan
$proxyEnable = $null; $proxyServer = ""; $bypass = ""; $autoCfg = ""
try {
    $ie = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction Stop
    $proxyEnable = $ie.ProxyEnable
    $proxyServer = $ie.ProxyServer
    $bypass = $ie.ProxyOverride
    $autoCfg = $ie.AutoConfigURL
} catch { }

$hostsHits = @()
$hostsPath = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"
if (Test-Path $hostsPath) {
    try {
        $hostsHits = Get-Content $hostsPath -ErrorAction SilentlyContinue |
            Where-Object { $_ -match "gat\.zj|data\.zj|zhiZhi|警|police" -and $_ -notmatch "^\s*#" }
    } catch { }
}

$script:Result["网络配置"] = [ordered]@{
    "代理启用"   = $proxyEnable
    "代理服务器" = $proxyServer
    "代理例外"   = $bypass
    "自动配置"   = $autoCfg
    "hosts路径"  = $hostsPath
    "hosts平台相关行" = @($hostsHits)
}
Write-Host ("  代理：{0} {1}" -f $(if ($proxyEnable -eq 1) { "启用" } else { "未启用" }), $proxyServer)
if ($hostsHits.Count -gt 0) {
    Write-Host "  hosts 中与平台相关的映射："
    $hostsHits | ForEach-Object { Write-Host ("    {0}" -f $_.Trim()) }
} else {
    Write-Host "  hosts 中无平台相关映射"
}
if ($proxyEnable -eq 1) {
    Add-Finding "提示" ("系统启用了代理 {0}：内网平台域名（*.gat.zj / *.data.zj）必须在代理例外中直连，否则回调与令牌校验会被代理劫持或超时" -f $proxyServer)
}

# --------------------------------------------------------------------------- #
# 6) 产出
# --------------------------------------------------------------------------- #
$jsonPath = Join-Path $Out ("client-inventory-{0}.json" -f $stamp)
$mdPath = Join-Path $Out ("client-inventory-{0}.md" -f $stamp)
$script:Result | ConvertTo-Json -Depth 8 | Out-File -FilePath $jsonPath -Encoding UTF8

$L = New-Object System.Collections.Generic.List[string]
$L.Add("# 浙警智治 · 终端与电子证书介质盘点（只读）")
$L.Add("")
$L.Add("> 生成时间：$($script:Result['生成时间'])")
$L.Add("> 计算机：$($script:Result['计算机名'])　用户：$($script:Result['当前用户'])　管理员：$($script:Result['是否管理员'])")
$L.Add("")
$L.Add("## 1. 基础环境与时钟")
$L.Add("")
$b = $script:Result["基础环境"]
$L.Add("| 项 | 值 |")
$L.Add("| --- | --- |")
$L.Add("| 操作系统 | $($b['操作系统']) |")
$L.Add("| 时区 | $($b['时区'])（UTC$($b['UTC偏移分钟']) 分钟） |")
$L.Add("| 本机时间 | $($b['本机时间']) |")
$syncDisp = $b['时间同步']
if (-not $syncDisp) { $syncDisp = "未取到（w32tm 不可用/权限不足，请手工核对时钟）" }
$L.Add("| 时间同步 | $syncDisp |")
$L.Add("")
$L.Add("## 2. 浏览器版本（上架硬要求 Chrome80+）")
$L.Add("")
$L.Add("| 浏览器 | 版本 |")
$L.Add("| --- | --- |")
foreach ($x in $script:Result["浏览器"]) { $L.Add("| $($x.名称) | $($x.版本) |") }
$L.Add("")
$L.Add("## 3. 证书客户端 / 中间件")
$L.Add("")
if ($script:Result["证书客户端"].Count -gt 0) {
    $L.Add("| 类型 | 名称 | 版本/服务名 | 发布者 |")
    $L.Add("| --- | --- | --- | --- |")
    foreach ($x in $script:Result["证书客户端"]) { $L.Add("| $($x.类型) | $($x.名称) | $($x.版本) | $($x.发布者) |") }
} else { $L.Add("未检测到证书类客户端/介质服务。") }
$L.Add("")
$L.Add("## 4. 证书存储（只读；未导出任何私钥）")
$L.Add("")
foreach ($s in $script:Result["证书存储"]) {
    $L.Add("### $($s.存储)（$($s.证书数) 张）")
    $L.Add("")
    if ($s.证书数 -gt 0) {
        $L.Add("| 主体 | 签发者 | 生效 | 失效 | 是否过期 | 带私钥 | 指纹 |")
        $L.Add("| --- | --- | --- | --- | --- | --- | --- |")
        foreach ($c in $s.证书) {
            $L.Add("| $($c.主体) | $($c.签发者) | $($c.生效) | $($c.失效) | $($c.是否过期) | $($c.带私钥) | $($c.指纹) |")
        }
    } else { $L.Add("（空）") }
    $L.Add("")
}
$L.Add("## 5. 网络配置（未发起任何连接）")
$L.Add("")
$n = $script:Result["网络配置"]
$L.Add("- 代理启用：$($n['代理启用'])　代理服务器：$($n['代理服务器'])")
$L.Add("- 代理例外：$($n['代理例外'])")
$L.Add("- 自动配置脚本：$($n['自动配置'])")
if (@($n['hosts平台相关行']).Count -gt 0) {
    $L.Add("- hosts 平台相关映射：")
    foreach ($h in $n['hosts平台相关行']) { $L.Add("  - ``$($h.Trim())``") }
} else { $L.Add("- hosts 无平台相关映射") }
$L.Add("")
$L.Add("## 6. 问题清单")
$L.Add("")
if ($script:Result["问题清单"].Count -gt 0) {
    $L.Add("| 级别 | 说明 |")
    $L.Add("| --- | --- |")
    foreach ($f in $script:Result["问题清单"]) { $L.Add("| $($f.级别) | $($f.说明) |") }
} else { $L.Add("无。") }
$L.Add("")
$L.Add("---")
$L.Add("")
$L.Add("**本脚本只读、不联网、不扫描、不导出私钥。产物含终端与证书标识，属敏感材料，请留在内网。**")
$L -join "`r`n" | Out-File -FilePath $mdPath -Encoding UTF8

Write-Host "`n=== 完成 ===" -ForegroundColor Green
Write-Host ("问题清单：{0} 项" -f $script:Result["问题清单"].Count)
Write-Host "已写出：$jsonPath"
Write-Host "已写出：$mdPath"
Write-Host "`n提醒：网络连通性与服务端证书链请用 zhijing_recon.py check；本脚本只做终端侧只读盘点。" -ForegroundColor DarkGray
