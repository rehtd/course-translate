# 被 启动同传课堂.vbs / .bat 调用。不要写死某台机器的 Python 路径。
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms | Out-Null

function Show-Fail([string]$Msg) {
    [void][System.Windows.Forms.MessageBox]::Show(
        $Msg, "同传课堂",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Warning)
    exit 1
}

function Invoke-VenvPython([string]$Code) {
    & $script:Py -c $Code
    return $LASTEXITCODE
}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if (-not (Test-Path -LiteralPath (Join-Path $Root "main.py"))) {
    Show-Fail "仓库根目录找不到 main.py。请把启动器放在 course-translate 文件夹里。"
}

$script:Py = Join-Path $Root ".venv\Scripts\python.exe"
$Pyw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $script:Py)) {
    Show-Fail "还没有虚拟环境。请先安装 Python 3.11 或 3.12（64 位），在本文件夹打开终端执行：`r`n`r`npy -3.12 -m venv .venv`r`n.venv\Scripts\activate`r`npython -m pip install -U pip`r`npip install -r requirements.txt"
}

if ((Invoke-VenvPython "import PySide6") -ne 0) {
    Show-Fail "当前虚拟环境还没装依赖。请执行：`r`n.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

$EnvFile = Join-Path $Root ".env"
$Example = Join-Path $Root ".env.example"
if (-not (Test-Path -LiteralPath $EnvFile)) {
    if (-not (Test-Path -LiteralPath $Example)) {
        Show-Fail "缺少 .env 和 .env.example。"
    }
    Copy-Item -LiteralPath $Example -Destination $EnvFile
    Start-Process notepad.exe -ArgumentList $EnvFile
    Show-Fail "已复制 .env.example 为 .env。请至少填一种翻译 Key（腾讯 / 百度 / 阿里 / 百炼 / DeepSeek），保存后再双击启动。上课不必用 DeepSeek。"
}

# 只判断有没有可用引擎，不打印 .env
$CheckCode = "from app.translate import resolve_provider; import sys; sys.exit(0 if resolve_provider() else 1)"
if ((Invoke-VenvPython $CheckCode) -ne 0) {
    Start-Process notepad.exe -ArgumentList $EnvFile
    Show-Fail "还没有可用的翻译配置。上课不必用 DeepSeek，在 .env 填一种真实 Key（不要用占位符），保存后再启动。"
}

function New-TongchuanShortcut([string]$LnkPath) {
    $Vbs = Join-Path $Root "启动同传课堂.vbs"
    $Ws = New-Object -ComObject WScript.Shell
    $Sc = $Ws.CreateShortcut($LnkPath)
    $Sc.TargetPath = Join-Path $env:SystemRoot "System32\wscript.exe"
    $Sc.Arguments = "`"$Vbs`""
    $Sc.WorkingDirectory = $Root
    $Sc.WindowStyle = 7
    $Sc.Description = "同传课堂"
    if (Test-Path -LiteralPath $Pyw) {
        $Sc.IconLocation = "$Pyw,0"
    }
    $Sc.Save()
}

$VbsLauncher = Join-Path $Root "启动同传课堂.vbs"
if (Test-Path -LiteralPath $VbsLauncher) {
    $Desktop = [Environment]::GetFolderPath("Desktop")
    if ($Desktop) {
        $DeskLnk = Join-Path $Desktop "同传课堂.lnk"
        if (-not (Test-Path -LiteralPath $DeskLnk)) {
            New-TongchuanShortcut $DeskLnk
        }
    }
    $RepoLnk = Join-Path $Root "同传课堂.lnk"
    if (-not (Test-Path -LiteralPath $RepoLnk)) {
        New-TongchuanShortcut $RepoLnk
    }
}

$Launch = $Pyw
if (-not (Test-Path -LiteralPath $Launch)) {
    $Launch = $script:Py
}
Start-Process -FilePath $Launch -ArgumentList "main.py" -WorkingDirectory $Root
exit 0
