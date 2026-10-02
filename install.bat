@echo off
REM AmazingDraw Windows bootstrap: Git Bash + matching x64 Python, then bash install.sh.
REM All PowerShell lives in this file after the marker (not a separate script).
cd /d "%~dp0"
set "AMAZINGDRAW_INSTALL_FROM_BAT=1"
set "AMAZINGDRAW_INSTALL_ROOT=%~dp0"
set "AMAZINGDRAW_BAT_FILE=%~f0"
set "AMAZINGDRAW_BAT_ARGS=%*"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$enc=New-Object System.Text.UTF8Encoding $true; $m=('########## AMAZINGDRAW'+'_PS_BODY ##########'); $p=[IO.File]::ReadAllText($env:AMAZINGDRAW_BAT_FILE,$enc); $i=$p.IndexOf($m); if($i -lt 0){throw 'install.bat missing PowerShell marker'}; iex $p.Substring($i+$m.Length); if($null -eq $LASTEXITCODE){exit 0}; exit $LASTEXITCODE"
exit /b %ERRORLEVEL%

########## AMAZINGDRAW_PS_BODY ##########
# AmazingDraw Windows bootstrap
# WANT_PY from native/*.pyd (cp312→3.12, cp39→3.9); mix or missing is fatal.
# Embedded in install.bat after the POWERSHELL marker. Requires Windows PowerShell 5.1+.

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {}

try {
    $null = cmd /c "chcp 65001 >nul"
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $OutputEncoding = [Console]::OutputEncoding
} catch {}

$rootEnv = [string]$env:AMAZINGDRAW_INSTALL_ROOT
if (-not $rootEnv) { $rootEnv = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $rootEnv) { $rootEnv = (Get-Location).Path }
$Root = [System.IO.Path]::GetFullPath($rootEnv.TrimEnd('\'))

$Yes = $false
$WithWebUI = $false
$OpenDownloadPage = $false
$ForwardArgs = New-Object System.Collections.Generic.List[string]
$rawArgs = [string]$env:AMAZINGDRAW_BAT_ARGS
if (-not $rawArgs -and $args) { $rawArgs = ($args | ForEach-Object { [string]$_ }) -join ' ' }
foreach ($a in @($rawArgs -split '\s+' | Where-Object { $_ })) {
    $s = [string]$a
    if ($s -match '^(?i)(-|/)?Yes$') { $Yes = $true; continue }
    if ($s -match '^(?i)-OpenDownloadPage$') { $OpenDownloadPage = $true; continue }
    if ($s -match '^(?i)-WithWebUI$') { $WithWebUI = $true; continue }
    [void]$ForwardArgs.Add($s)
}
$yesEnv = [string]$env:AMAZINGDRAW_INSTALL_YES
if ($yesEnv -eq '1' -or $yesEnv -eq 'true' -or $yesEnv -eq 'yes') {
    $Yes = $true
}
$webEnv = [string]$env:AMAZINGDRAW_WITH_WEBUI
if ($webEnv -eq '1' -or $webEnv -eq 'true' -or $webEnv -eq 'yes') {
    $WithWebUI = $true
}

$FromBat = $true
$ScriptExit = 1
$NativeDir = Join-Path $Root 'card_engine_core\native'
$BootstrapDir = Join-Path $env:TEMP 'AmazingDraw-bootstrap'
$WantPy = $null
$NeedGit = $true
$NeedPy = $true
$IsArm64Os = $false

$GitWingetId = 'Git.Git'
$PyWingetId = $null
$PyFtpCandidates = @()
$GitDownloadPage = 'https://git-scm.com/download/win'
$PyDownloadPage = 'https://www.python.org/downloads/windows/'

function Write-Info([string]$Msg) { Write-Host $Msg }
function Write-Warn([string]$Msg) { Write-Host $Msg -ForegroundColor Yellow }
function Write-ErrLine([string]$Msg) { Write-Host $Msg -ForegroundColor Red }

function Test-IsInteractive {
    try {
        if ([Console]::IsInputRedirected) { return $false }
    } catch {}
    return [Environment]::UserInteractive
}

function Pause-IfNeeded {
    param([int]$Code)
    if ($FromBat -and -not $Yes -and (Test-IsInteractive)) {
        Write-Host ""
        try { [void](Read-Host "按 Enter 关闭此窗口") } catch {}
    }
    exit $Code
}

function Fail([string]$Msg) {
    Write-ErrLine ""
    Write-ErrLine "== 引导失败 =="
    Write-ErrLine $Msg
    $Script:ScriptExit = 1
    Pause-IfNeeded 1
}

function ConvertTo-BashQuoted([string]$Value) {
    $q = $Value -replace "'", "'\''"
    return "'" + $q + "'"
}

function ConvertTo-GitBashPath([string]$WinPath) {
    $full = [System.IO.Path]::GetFullPath($WinPath)
    $full = $full -replace '\\', '/'
    if ($full -match '^([A-Za-z]):(.*)$') {
        return '/' + $Matches[1].ToLowerInvariant() + $Matches[2]
    }
    return $full
}

function Test-IsArm64Windows {
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { return $true }
    if ($env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { return $true }
    try {
        $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
        if ("$arch" -match 'Arm') { return $true }
    } catch {}
    return $false
}

function Refresh-ProcessPath {
    try {
        $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $user = [Environment]::GetEnvironmentVariable('Path', 'User')
        $parts = @()
        if ($machine) { $parts += $machine }
        if ($user) { $parts += $user }
        if ($parts.Count -gt 0) {
            $env:Path = ($parts -join ';')
        }
    } catch {}
    $extras = @(
        'C:\Program Files\Git\cmd',
        'C:\Program Files\Git\bin',
        'C:\Program Files\Git\usr\bin',
        (Join-Path $env:LocalAppData 'Programs\Python\Python312'),
        (Join-Path $env:LocalAppData 'Programs\Python\Python312\Scripts'),
        (Join-Path $env:LocalAppData 'Programs\Python\Python39'),
        (Join-Path $env:LocalAppData 'Programs\Python\Python39\Scripts'),
        'C:\Program Files\Python312',
        'C:\Program Files\Python39',
        'C:\Python312',
        'C:\Python39'
    )
    foreach ($p in $extras) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            if ($env:Path -notlike "*$p*") {
                $env:Path = "$p;$env:Path"
            }
        }
    }
}

function Get-WantPythonFromPyds {
    if (-not (Test-Path -LiteralPath $NativeDir -PathType Container)) {
        Fail "缺少目录 $NativeDir（内核）。请从 GitHub Releases 下载完整的 AmazingDraw-windows-cp39 或 cp312 压缩包。"
    }
    $pyds = @(Get-ChildItem -LiteralPath $NativeDir -Filter *.pyd -File -ErrorAction SilentlyContinue)
    if ($pyds.Count -eq 0) {
        Fail "native/ 内没有 .pyd。Windows 包必须含 win_amd64 内核；请重新下载 AmazingDraw-windows-cp39.zip 或 AmazingDraw-windows-cp312.zip。"
    }
    $has39 = $false
    $has312 = $false
    $unknown = New-Object System.Collections.Generic.List[string]
    foreach ($f in $pyds) {
        $n = $f.Name
        if ($n -match 'cp312|cpython-312') { $has312 = $true }
        elseif ($n -match 'cp39|cpython-39') { $has39 = $true }
        else { [void]$unknown.Add($n) }
    }
    if ($has39 -and $has312) {
        Fail "native/ 同时含 Python 3.9 与 3.12 的 .pyd，禁止混装。请只保留与本包标签一致的一套。"
    }
    if ($unknown.Count -gt 0 -and -not $has39 -and -not $has312) {
        Fail ("无法从 native/*.pyd 文件名解析 Python 版本（需要 cp39 / cp312）。示例: " + $unknown[0])
    }
    if ($has312) { return '3.12' }
    if ($has39) { return '3.9' }
    Fail "无法从 native/*.pyd 判定所需 Python 版本。"
}

function Get-PythonInfo([string]$Exe) {
    if (-not $Exe) { return $null }
    if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { return $null }
    if ($Exe -match '(?i)\\WindowsApps\\') { return $null }
    $code = 'import sys,sysconfig; print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1])); print(sysconfig.get_platform()); print(64 if sys.maxsize>2**32 else 32); print(sys.executable)'
    try {
        $raw = & $Exe -c $code 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
        $lines = @($raw | ForEach-Object { [string]$_ } | Where-Object { $_ -ne '' })
        if ($lines.Count -lt 3) { return $null }
        return @{
            Version = $lines[0].Trim()
            Platform = $lines[1].Trim()
            Bits = [int]$lines[2].Trim()
            Executable = $(if ($lines.Count -ge 4) { $lines[3].Trim() } else { $Exe })
        }
    } catch {
        return $null
    }
}

function Test-PythonMatches($Info, [string]$Want) {
    if (-not $Info) { return $false }
    if ($Info.Version -ne $Want) { return $false }
    if ($Info.Bits -ne 64) { return $false }
    $plat = [string]$Info.Platform
    if ($plat -match '(?i)arm') { return $false }
    if ($plat -notmatch '(?i)amd64') { return $false }
    return $true
}

function Find-MatchingPython([string]$Want) {
    $cands = New-Object System.Collections.Generic.List[string]
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $flag = switch ($Want) { '3.12' { '-3.12' } '3.9' { '-3.9' } default { $null } }
        if ($flag) {
            try {
                $exe = & py $flag -c "import sys; print(sys.executable)" 2>$null
                if ($exe) { [void]$cands.Add(([string]$exe).Trim()) }
            } catch {}
        }
    }
    $names = @()
    if ($Want -eq '3.12') { $names = @('python3.12', 'python312', 'python3', 'python') }
    elseif ($Want -eq '3.9') { $names = @('python3.9', 'python39', 'python3', 'python') }
    else { $names = @('python3', 'python') }
    foreach ($n in $names) {
        $cmd = Get-Command $n -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { [void]$cands.Add($cmd.Source) }
    }
    $rel = if ($Want -eq '3.12') { @('Python312', 'Python3.12') } else { @('Python39', 'Python3.9') }
    $roots = @(
        (Join-Path $env:LocalAppData 'Programs\Python'),
        ${env:ProgramFiles},
        ${env:ProgramFiles(x86)},
        'C:\'
    )
    foreach ($root in $roots) {
        if (-not $root) { continue }
        foreach ($r in $rel) {
            $p = Join-Path $root "$r\python.exe"
            [void]$cands.Add($p)
        }
    }
    $seen = @{}
    foreach ($c in $cands) {
        if (-not $c) { continue }
        $key = $c.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $info = Get-PythonInfo $c
        if (Test-PythonMatches $info $Want) { return $info }
        if ($info -and $info.Platform -match '(?i)arm') {
            Write-Warn ("  跳过 ARM64 Python（不足以加载 win_amd64 .pyd）: " + $info.Executable)
        }
    }
    return $null
}

function Find-GitBash {
    $cands = @(
        'C:\Program Files\Git\bin\bash.exe',
        'C:\Program Files\Git\usr\bin\bash.exe',
        (Join-Path $env:LocalAppData 'Programs\Git\bin\bash.exe')
    )
    $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $cands = @($cmd.Source) + $cands }
    $gitCmd = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($gitCmd -and $gitCmd.Source) {
        $bin = Join-Path (Split-Path (Split-Path $gitCmd.Source -Parent) -Parent) 'bin\bash.exe'
        $cands += $bin
        $usr = Join-Path (Split-Path (Split-Path $gitCmd.Source -Parent) -Parent) 'usr\bin\bash.exe'
        $cands += $usr
    }
    $seen = @{}
    foreach ($c in $cands) {
        if (-not $c) { continue }
        $key = $c.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if ($c -match '(?i)Program Files \(x86\)') { continue }
        if (Test-Path -LiteralPath $c -PathType Leaf) { return $c }
    }
    return $null
}

function Test-WingetAvailable {
    $w = Get-Command winget -ErrorAction SilentlyContinue
    return [bool]$w
}

function Install-WithWinget([string]$PackageId) {
    if (-not (Test-WingetAvailable)) { return $false }
    Write-Info "  winget install $PackageId （x64）..."
    $wingetArgs = @(
        'install', '--id', $PackageId, '-e',
        '--source', 'winget',
        '--accept-package-agreements', '--accept-source-agreements',
        '--disable-interactivity',
        '--architecture', 'x64'
    )
    try {
        & winget @wingetArgs
        if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335189) {
            # 0 = ok; -1978335189 = already installed (APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE-ish / found existing)
            return $true
        }
        Write-Warn ("  winget 退出码 " + $LASTEXITCODE + "，改试官方静默安装包。")
        return $false
    } catch {
        Write-Warn ("  winget 调用失败: " + $_.Exception.Message)
        return $false
    }
}

function Get-GitForWindows64Url {
    $api = 'https://api.github.com/repos/git-for-windows/git/releases/latest'
    try {
        $headers = @{ 'User-Agent' = 'AmazingDraw-bootstrap'; 'Accept' = 'application/vnd.github+json' }
        $rel = Invoke-RestMethod -Uri $api -Headers $headers
        foreach ($asset in $rel.assets) {
            $n = [string]$asset.name
            if ($n -match '^Git-.*-64-bit\.exe$' -and $n -notmatch '(?i)arm64|MinGit|Portable|BusyBox') {
                return [string]$asset.browser_download_url
            }
        }
    } catch {
        Write-Warn ("  查询 GitHub Git 发行版失败: " + $_.Exception.Message)
    }
    return $null
}

function Test-UrlExists([string]$Url) {
    try {
        $req = [System.Net.WebRequest]::Create($Url)
        $req.Method = 'HEAD'
        $req.UserAgent = 'AmazingDraw-bootstrap'
        $req.Timeout = 20000
        $resp = $req.GetResponse()
        $ok = $true
        $resp.Close()
        return $ok
    } catch {
        return $false
    }
}

function Get-PythonAmd64InstallerUrl([string]$Want) {
    foreach ($v in $PyFtpCandidates) {
        $url = "https://www.python.org/ftp/python/$v/python-$v-amd64.exe"
        if (Test-UrlExists $url) { return $url }
    }
    return $null
}

function Save-UrlToFile([string]$Url, [string]$Dest) {
    Write-Info "  下载: $Url"
    $tmp = "$Dest.partial"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -UserAgent 'AmazingDraw-bootstrap'
    if (-not (Test-Path -LiteralPath $tmp)) { throw "下载未生成文件: $Url" }
    Move-Item -LiteralPath $tmp -Destination $Dest -Force
}

function Invoke-SilentInstaller([string]$ExePath, [string[]]$InstArgs) {
    Write-Info ("  静默安装: " + (Split-Path $ExePath -Leaf))
    $p = Start-Process -FilePath $ExePath -ArgumentList $InstArgs -Wait -PassThru
    return $p.ExitCode
}

function Open-PageIfRequested([string]$Url) {
    if (-not $OpenDownloadPage) { return }
    try {
        Start-Process $Url | Out-Null
        Write-Info "  已打开下载页: $Url"
    } catch {
        Write-Warn ("  无法打开浏览器: " + $_.Exception.Message)
    }
}

function Test-WebUIDepsPresent([string]$Exe) {
    try {
        & $Exe -c "import fastapi, uvicorn" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Invoke-WebUIPip([string]$Exe) {
    Write-Info ("  执行: `"$Exe`" -m pip install fastapi uvicorn")
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Exe -m pip install fastapi uvicorn
    $code = $LASTEXITCODE
    $ErrorActionPreference = $old
    if ($code -ne 0) {
        Write-Warn "  pip 安装 fastapi / uvicorn 失败（不中断本次安装）。以后可手动执行："
        Write-Warn ("    `"$Exe`" -m pip install fastapi uvicorn")
        return
    }
    Write-Info "  ✓ 已安装 fastapi、uvicorn"
}

function Invoke-OptionalWebUISetup([string]$Exe) {
    Write-Host ""
    Write-Host "== WebUI（可选）=="
    Write-Host "  WebUI 不是必须的：只用 Skill / CLI / Agent 时不必安装。"
    Write-Host "  WebUI 进程只需 fastapi/uvicorn（本步 pip 只装这两样）。"
    Write-Host "  完整对话抽卡 / AI 连抽还需本机 OpenClaw；本引导不自动安装 OpenClaw。"
    Write-Host "  install.sh 可能探测并写入路径，也可稍后在 WebUI 配置里填写 openclaw_home / openclaw_bin。"
    Write-Host "  出图另需 ComfyUI+模型（不自动装）。"
    if (Test-WebUIDepsPresent $Exe) {
        Write-Info "  该 Python 已能 import fastapi、uvicorn，跳过 pip。"
        return
    }
    $want = $false
    if ($WithWebUI) {
        $want = $true
    } elseif ($Yes) {
        Write-Info "  非交互（-Yes）默认跳过 WebUI pip。需要时加 -WithWebUI 或 AMAZINGDRAW_WITH_WEBUI=1。"
        Write-Info ("  稍后: `"$Exe`" -m pip install fastapi uvicorn")
        Write-Info "  （仍不含 OpenClaw；对话/连抽需自备。）"
        return
    } elseif (-not (Test-IsInteractive)) {
        Write-Info ("  无交互终端，跳过 WebUI pip。稍后: `"$Exe`" -m pip install fastapi uvicorn")
        return
    } else {
        $ans = ""
        try { $ans = Read-Host "  现在安装 WebUI 依赖（仅 fastapi/uvicorn，不含 OpenClaw）吗？(Y=是 / N=否，回车=否)" } catch {}
        if ([string]$ans -match '^(?i)(y|yes|是)$') { $want = $true }
    }
    if ($want) {
        Invoke-WebUIPip $Exe
    } else {
        Write-Info ("  已跳过。以后要用 WebUI: `"$Exe`" -m pip install fastapi uvicorn")
        Write-Info "  对话/连抽另需本机 OpenClaw（不随 pip 安装）。"
    }
}

function Write-ManualCommands {
    Write-ErrLine ""
    Write-ErrLine "自动安装未成功。可手动执行（均为 x64，不要装 ARM64 Python）："
    Write-ErrLine "  winget install --id $GitWingetId -e --architecture x64 --accept-package-agreements --accept-source-agreements"
    Write-ErrLine "  winget install --id $PyWingetId -e --architecture x64 --accept-package-agreements --accept-source-agreements"
    Write-ErrLine "或下载官方安装包："
    Write-ErrLine "  Git: $GitDownloadPage"
    Write-ErrLine "  Python ${WantPy} x64: $PyDownloadPage"
    Write-ErrLine "装好后重新运行 install.bat。"
    if ($OpenDownloadPage) {
        Open-PageIfRequested $GitDownloadPage
        Open-PageIfRequested $PyDownloadPage
    } else {
        Write-Info "默认不会打开浏览器。若要打开官网下载页，请加 -OpenDownloadPage。"
    }
}

# ── main ──
if ($env:OS -ne 'Windows_NT') {
    Fail "install.bat 仅用于 Windows。macOS / Linux 请运行: bash install.sh"
}

$WantPy = Get-WantPythonFromPyds
$PyWingetId = if ($WantPy -eq '3.12') { 'Python.Python.3.12' } else { 'Python.Python.3.9' }
$PyFtpCandidates = if ($WantPy -eq '3.12') {
    @('3.12.11', '3.12.10', '3.12.9', '3.12.8', '3.12.7')
} else {
    @('3.9.13', '3.9.12')
}

$IsArm64Os = Test-IsArm64Windows

Write-Host "== AmazingDraw Windows 引导 =="
Write-Host "  目录: $Root"
Write-Host "  本包内核: Python $WantPy / win_amd64 .pyd"
if ($IsArm64Os) {
    Write-Warn "  当前是 ARM64 Windows。发行内核是 win_amd64 .pyd，将安装 **x64** Git 与 Python，经 Windows on ARM 模拟运行。"
    Write-Warn "  ARM64 原生 Python 无法加载这些 .pyd，会被视为无效。"
}

Refresh-ProcessPath
$bashNow = Find-GitBash
$pyNow = Find-MatchingPython $WantPy
$NeedGit = -not [bool]$bashNow
$NeedPy = -not [bool]$pyNow

if ($bashNow) { Write-Info "  已找到 Git Bash: $bashNow" } else { Write-Warn "  未找到 Git Bash（需要 Git for Windows x64）" }
if ($pyNow) { Write-Info ("  已找到匹配 Python: " + $pyNow.Executable + " (" + $pyNow.Version + " " + $pyNow.Platform + ")") }
else { Write-Warn "  未找到 64 位 Python $WantPy (win-amd64)" }

Write-Host ""
Write-Host "本引导只补齐 Git Bash 与匹配的 x64 Python，然后交给 install.sh。"
Write-Host "不会自动安装 ComfyUI 或模型。"
Write-Host ""

if ($NeedGit -or $NeedPy) {
    Write-Host "将尝试安装："
    if ($NeedGit) { Write-Host "  - Git for Windows（x64，提供 Git Bash）" }
    if ($NeedPy) { Write-Host "  - Python $WantPy（x64 / amd64，Add to PATH）" }
    Write-Host "顺序：winget → 官方安装包静默下载到 %TEMP%\AmazingDraw-bootstrap\"
    if (-not $Yes) {
        if (Test-IsInteractive) {
            Write-Host ""
            try { [void](Read-Host "按 Enter 继续，Ctrl+C 取消") } catch {}
        } else {
            Fail "需要安装依赖，但当前无交互终端。请加 -Yes，或设置 AMAZINGDRAW_INSTALL_YES=1。"
        }
    }
} else {
    Write-Host "依赖已齐，跳过安装，直接运行 install.sh。"
}

$failed = New-Object System.Collections.Generic.List[string]

if ($NeedGit) {
    Write-Host ""
    Write-Host "-- Git for Windows --"
    $ok = Install-WithWinget $GitWingetId
    Refresh-ProcessPath
    if (-not $ok -or -not (Find-GitBash)) {
        try {
            if (-not (Test-Path -LiteralPath $BootstrapDir)) {
                New-Item -ItemType Directory -Path $BootstrapDir | Out-Null
            }
            $url = Get-GitForWindows64Url
            if (-not $url) { throw "无法解析 Git for Windows 64-bit 安装包地址" }
            $dest = Join-Path $BootstrapDir 'Git-64-bit.exe'
            Save-UrlToFile $url $dest
            $code = Invoke-SilentInstaller $dest @('/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-')
            if ($code -ne 0) { throw "Git 安装器退出码 $code" }
        } catch {
            Write-Warn ("  Git 静默安装失败: " + $_.Exception.Message)
            [void]$failed.Add('Git for Windows x64')
        }
    }
    Refresh-ProcessPath
}

if ($NeedPy) {
    Write-Host ""
    Write-Host "-- Python $WantPy (x64) --"
    $ok = Install-WithWinget $PyWingetId
    Refresh-ProcessPath
    if (-not $ok -or -not (Find-MatchingPython $WantPy)) {
        try {
            if (-not (Test-Path -LiteralPath $BootstrapDir)) {
                New-Item -ItemType Directory -Path $BootstrapDir | Out-Null
            }
            $url = Get-PythonAmd64InstallerUrl $WantPy
            if (-not $url) { throw "无法解析 Python $WantPy amd64 安装包地址" }
            $leaf = Split-Path $url -Leaf
            $dest = Join-Path $BootstrapDir $leaf
            Save-UrlToFile $url $dest
            $pyArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_pip=1')
            $code = Invoke-SilentInstaller $dest $pyArgs
            if ($code -ne 0) { throw "Python 安装器退出码 $code" }
        } catch {
            Write-Warn ("  Python 静默安装失败: " + $_.Exception.Message)
            [void]$failed.Add("Python $WantPy x64")
        }
    }
    Refresh-ProcessPath
}

$bashExe = Find-GitBash
$pyInfo = Find-MatchingPython $WantPy

if ($failed.Count -gt 0 -or -not $bashExe -or -not $pyInfo) {
    if (-not $bashExe) { [void]$failed.Add('Git Bash (bash.exe)') }
    if (-not $pyInfo) { [void]$failed.Add("Python $WantPy win-amd64") }
    Write-ManualCommands
    Fail ("仍缺少: " + ($failed -join '、'))
}

Write-Host ""
Write-Host "✓ Git Bash: $bashExe"
Write-Host ("✓ Python: " + $pyInfo.Executable + " (" + $pyInfo.Version + " " + $pyInfo.Platform + ")")

Invoke-OptionalWebUISetup $pyInfo.Executable

$installSh = Join-Path $Root 'install.sh'
if (-not (Test-Path -LiteralPath $installSh -PathType Leaf)) {
    Fail "未找到 install.sh（应与 install.bat 同目录）。请确认解压完整。"
}

$posix = ConvertTo-GitBashPath $Root
$argStr = ''
if ($ForwardArgs.Count -gt 0) {
    $quoted = $ForwardArgs | ForEach-Object { ConvertTo-BashQuoted $_ }
    $argStr = ' ' + ($quoted -join ' ')
}
$bashCmd = 'cd ' + (ConvertTo-BashQuoted $posix) + ' && ./install.sh' + $argStr

Write-Host ""
Write-Host "== 交给 install.sh =="
Write-Host "  bash -lc $bashCmd"

$oldEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $bashExe -lc $bashCmd
$ScriptExit = $LASTEXITCODE
$ErrorActionPreference = $oldEap
if ($null -eq $ScriptExit) { $ScriptExit = 1 }

if ($ScriptExit -ne 0) {
    Write-ErrLine ""
    Write-ErrLine "install.sh 退出码 $ScriptExit"
} else {
    Write-Host ""
    Write-Host "install.sh 已完成。"
}

Pause-IfNeeded $ScriptExit
