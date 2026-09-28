#Requires -Version 5.1
<#
.SYNOPSIS
    帮你挑一个 —— 一键启动（Windows）。被仓库根目录的「一键启动.bat」调用。

.DESCRIPTION
    按顺序做五件事，每一步都打印中文进度；任何一步失败都给出**能照着做**的提示，
    而不是把 PowerShell 的原始报错甩给用户：

      1. 找 Python（py -3.10 / py -3 / python，要求 3.10+）
      2. 没有 .venv 就建，并装 requirements.txt
      3. 有 NVIDIA 显卡就装 CUDA 版 torch（已经能 import torch 就不重装）
      4. models\ 里没有权重就调 scripts\download_model.py 下载
      5. 起服务并打开浏览器

    为什么用 PowerShell 而不是 .bat 里堆命令：要判断的东西太多（Python 版本、
    显卡、依赖是否齐、模型在不在、端口占不占），cmd 的 if/for 写出来没人维护。

.PARAMETER Port
    服务端口，默认 8770。被占用时会报错并告诉你怎么换。

.PARAMETER Model
    基座：qwen3-0.6b（最小最快）/ qwen3.5-2b（默认）/ qwen3.5-4b（最大最准）。

.PARAMETER Device
    auto（默认，有 CUDA 就用）/ cuda / cpu。

.PARAMETER NoBrowser
    不自动打开浏览器。

.PARAMETER Mirror
    pip 走清华 TUNA 镜像（中国大陆网络慢时用）。

.PARAMETER HfMirror
    优先用 hf-mirror.com 下模型（默认是「先官方，失败自动换镜像」）。

.EXAMPLE
    .\scripts\launch.ps1
.EXAMPLE
    .\scripts\launch.ps1 -Mirror -Port 9000 -Model qwen3-0.6b
#>
[CmdletBinding()]
param(
    [int]$Port = 8770,
    [string]$Model = "qwen3.5-2b",
    [ValidateSet("auto", "cuda", "cpu")]
    [string]$Device = "auto",
    [switch]$NoBrowser,
    [switch]$Mirror,
    [switch]$HfMirror,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @()
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------- 输出

# 中文输出要能看见。两层：
#   * chcp 65001 改控制台代码页（.bat 里已经改过一次，这里兜底「直接跑 .ps1」的情况）
#   * PYTHONIOENCODING 让子进程 python 也用 UTF-8 输出，不然它的中文日志是乱码
try { chcp 65001 | Out-Null } catch { }
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"

function Write-Step([string]$Message) { Write-Host "[启动] $Message" -ForegroundColor Cyan }
function Write-Done([string]$Message) { Write-Host "[就绪] $Message" -ForegroundColor Green }
function Write-Note([string]$Message) { Write-Host "[注意] $Message" -ForegroundColor Yellow }

#: 失败时的统一出口：一句人话 + 若干条「照着做」的提示。
#: 不用 throw，因为 PowerShell 的异常堆栈对普通用户等于噪音。
function Fail([string]$Message, [string[]]$Hints = @()) {
    Write-Host ""
    Write-Host "[失败] $Message" -ForegroundColor Red
    foreach ($hint in $Hints) { Write-Host "       $hint" -ForegroundColor Yellow }
    Write-Host ""
    exit 1
}

# ---------------------------------------------------------------- 位置

$root = Split-Path -Parent $PSScriptRoot          # scripts/ 的上一级 = 项目根
$venvDir = Join-Path $root ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
$requirements = Join-Path $root "requirements.txt"
$PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
$TORCH_INDEX = "https://download.pytorch.org/whl/cu130"
$HF_MIRROR = "https://hf-mirror.com"

Write-Host ""
Write-Host "  帮你挑一个 —— 这条评论该回哪个字（一键启动）" -ForegroundColor White
Write-Host "  项目目录：$root" -ForegroundColor DarkGray
Write-Host ""

# 允许把服务参数直接透传过来（.bat 会把 %* 原样交给我们）：
# `一键启动.bat --port 9000` 里的 --port 不归 PowerShell 管，转发给 python。
# 既然用户显式写了，就不要再叠一个自己的默认值上去。
function Test-RestHas([string[]]$Items, [string]$Name) {
    foreach ($item in $Items) {
        if ($item -eq $Name -or $item -like "$Name=*") { return $true }
    }
    return $false
}
function Get-RestValue([string[]]$Items, [string]$Name) {
    for ($i = 0; $i -lt $Items.Count; $i++) {
        if ($Items[$i] -eq $Name -and ($i + 1) -lt $Items.Count) { return $Items[$i + 1] }
        if ($Items[$i] -like "$Name=*") { return $Items[$i].Substring($Name.Length + 1) }
    }
    return $null
}
$restPort = Get-RestValue $Rest "--port"
if ($restPort) { $Port = [int]$restPort }
$restModel = Get-RestValue $Rest "--model"
if ($restModel) { $Model = $restModel }

# 基座名先校验一遍。不校验的话要等到第 4 步才由 python 的 argparse 报错，
# 那时用户已经等了半天，而且报错是英文的、还夹着一堆 usage 噪音。
$knownModels = @("qwen3-0.6b", "qwen3.5-2b", "qwen3.5-4b")
if ($knownModels -notcontains $Model) {
    Fail "不认识的基座名：$Model" @(
        "可选：qwen3-0.6b（最小最快）/ qwen3.5-2b（默认）/ qwen3.5-4b（最准也最重）",
        "体积和实测准确率见 docs/EVAL.md 与 scripts/download_model.py",
        "不改的话直接双击「一键启动.bat」，默认就是 qwen3.5-2b"
    )
}

# ============================================================ 1. 找 Python

Write-Step "1/5 找 Python（需要 3.10 或更高）..."

function Find-Python {
    # 顺序有讲究：py -3.10 优先，因为项目就是按 3.10 验的；
    # py -3 和 python 是兜底（有些人只装了 3.12）。
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.10"); Label = "py -3.10" },
        @{ Exe = "py"; Args = @("-3"); Label = "py -3" },
        @{ Exe = "python"; Args = @(); Label = "python" }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        # 探测版本。失败时 py 会往 stderr 写「Requested Python version not installed」，
        # 那句英文对用户没意义，所以直接丢掉。
        $probe = & $candidate.Exe @($candidate.Args + @("-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])")) 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $probe) { continue }
        $text = ([string]($probe | Select-Object -First 1)).Trim()
        $parts = $text.Split(".")
        if ($parts.Count -lt 2) { continue }
        if (-not ($parts[0] -match '^\d+$' -and $parts[1] -match '^\d+$')) { continue }
        $major = [int]$parts[0]
        $minor = [int]$parts[1]
        if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
            return @{ Exe = $candidate.Exe; Args = $candidate.Args; Label = $candidate.Label; Version = $text }
        }
    }
    return $null
}

$basePython = Find-Python
if ($null -eq $basePython) {
    Fail "没找到 Python 3.10 或更高版本。" @(
        "去 https://www.python.org/downloads/windows/ 下载 3.10 以上的版本（3.12 也行）",
        "安装时**务必勾选**「Add python.exe to PATH」，否则这个窗口还是找不到它",
        "装完把本窗口关掉，重新双击「一键启动.bat」"
    )
}
Write-Done "找到 $($basePython.Label)（Python $($basePython.Version)）"

# ==================================================== 2. 虚拟环境 + 依赖

Write-Step "2/5 准备运行环境 .venv ..."

# 镜像只影响 pip 的包索引。默认走官方源：海外用户不用绕路，
# 大陆用户失败了会看到「加 -Mirror」的提示（见下面的 catch）。
$pipIndex = @()
if ($Mirror) {
    $pipIndex = @("-i", $PYPI_MIRROR)
    Write-Note "pip 使用清华 TUNA 镜像：$PYPI_MIRROR"
}

if (-not (Test-Path $venvPy)) {
    Write-Step "第一次启动：创建虚拟环境（.venv）..."
    & $basePython.Exe @($basePython.Args + @("-m", "venv", $venvDir))
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) {
        Fail "创建虚拟环境失败。" @(
            "确认磁盘有空间，并且当前目录可写：$venvDir",
            "也可以手动建：$($basePython.Label) -m venv .venv"
        )
    }
    Write-Done "虚拟环境建好了：$venvDir"
}

# 依赖齐不齐：靠 import 试，而不是靠标记文件 —— 用户可能手动删过包。
# 注意这里**不 import torch 之外的重活**，只是判断能不能跑。
$depsOk = $false
& $venvPy -c "import torch, transformers, safetensors, huggingface_hub" 2>$null
if ($LASTEXITCODE -eq 0) { $depsOk = $true }

if (-not $depsOk) {
    Write-Step "安装依赖（第一次要下几百 MB，慢慢等）..."
    & $venvPy -m pip install --upgrade pip @pipIndex
    & $venvPy -m pip install -r $requirements @pipIndex
    if ($LASTEXITCODE -ne 0) {
        $hints = @(
            "确认网络能访问 pypi.org；公司网络 / 代理可能需要额外配置",
            "大陆网络慢或超时很常见：重新双击「一键启动.bat」改跑一次",
            "或者在 cmd 里执行：一键启动.bat -Mirror    （走清华 TUNA 镜像）"
        )
        if ($Mirror) {
            $hints = @(
                "镜像也失败了，可能是网络本身不通，或者 TUNA 暂时抽风",
                "换个时间再试，或者手动跑：$venvPy -m pip install -r requirements.txt"
            )
        }
        Fail "安装依赖失败。" $hints
    }
    Write-Done "依赖装好了"
} else {
    Write-Done "依赖已经齐了（跳过安装）"
}

# ==================================================== 3. torch 与显卡

Write-Step "3/5 检查显卡和 torch ..."

# 先看 torch 本身能不能 import —— 这一步是「别每次启动都重装 torch」的关键。
$torchOk = $false
& $venvPy -c "import torch" 2>$null
if ($LASTEXITCODE -eq 0) { $torchOk = $true }

$hasNvidia = $false
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    # 有 nvidia-smi 不等于有能用的卡（驱动坏掉 / 卡被独占时它也会失败）。
    & nvidia-smi 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $hasNvidia = $true }
}

if ($hasNvidia) {
    $cudaOk = $false
    if ($torchOk) {
        $probe = & $venvPy -c "import torch; print(1 if torch.cuda.is_available() else 0)" 2>$null
        if (([string]($probe | Select-Object -First 1)).Trim() -eq "1") { $cudaOk = $true }
    }
    if ($cudaOk) {
        Write-Done "NVIDIA 显卡可用，torch 已经是 CUDA 版（跳过重装）"
    } else {
        Write-Step "检测到 NVIDIA 显卡，装 CUDA 版 torch（wheel 有好几个 GB，慢）..."
        Write-Note "pytorch 的 wheel 只在官方源上，所以这一步不走 TUNA 镜像"
        # --force-reinstall 是必要的：requirements.txt 里装的是 CPU 版，
        # pip 认为「torch==2.14.0 已满足」不会替换，于是 CUDA 永远用不上。
        & $venvPy -m pip install --force-reinstall "torch==2.14.0+cu130" --index-url $TORCH_INDEX
        if ($LASTEXITCODE -ne 0) {
            Write-Note "CUDA 版 torch 没装上。不影响使用 —— 可以先用 CPU 跑："
            Write-Note "  一键启动.bat -Device cpu"
            Write-Note "（CPU 能出结果，就是慢很多；想用显卡就检查网络后重跑一次）"
        } else {
            Write-Done "CUDA 版 torch 装好了"
        }
    }
} else {
    Write-Note "没检测到可用的 NVIDIA 显卡（nvidia-smi 不存在或跑不起来）"
    Write-Note "会用 CPU 跑：功能完全一样，但速度慢很多（每判一条从零点几秒变成几秒）"
    Write-Note "macOS / AMD 显卡同理，引擎只认 CUDA 和 CPU 两种设备"
}

# ============================================================ 4. 模型

Write-Step "4/5 检查基座模型 ..."

# 目录名 = 模型名（qwen3.5-2b -> Qwen3.5-2B），跟 engine.py 的 MODEL_CHOICES 对齐。
$dirName = switch ($Model) {
    "qwen3-0.6b" { "Qwen3-0.6B" }
    "qwen3.5-2b" { "Qwen3.5-2B" }
    "qwen3.5-4b" { "Qwen3.5-4B" }
    default { $Model }
}
$modelDir = Join-Path $root "models\$dirName"
$weights = @(Get-ChildItem -Path $modelDir -Filter "*.safetensors" -ErrorAction SilentlyContinue)

if ($weights.Count -gt 0) {
    $sizeGb = [math]::Round((($weights | Measure-Object -Property Length -Sum).Sum / 1GB), 2)
    Write-Done "模型在本地：models\$dirName（$sizeGb GB）"
} else {
    Write-Step "本地没有 $dirName，开始下载（几 GB，第一次要等挺久）..."

    # 下载走 huggingface_hub，它认 HF_ENDPOINT 环境变量。
    # 策略：**先官方，失败自动换 hf-mirror.com**。理由 ——
    #   目标用户主要在中国大陆，huggingface.co 经常直接连不上；
    #   但海外用户走镜像反而绕远。自动回退两头都不吃亏，
    #   而且用户不需要知道 HF_ENDPOINT 是什么东西。
    #   -HfMirror 是给「知道自己要走镜像」的人用的（直接先镜像，少等一次超时）。
    # 注意 hf-mirror.com 是第三方镜像：权重按 download_model.py 里写死的
    # revision 拉取，在意来源的话请用官方源（去掉 -HfMirror，或挂代理）。
    function Invoke-ModelDownload([string]$Endpoint) {
        if ($Endpoint) { $env:HF_ENDPOINT = $Endpoint } else { Remove-Item Env:HF_ENDPOINT -ErrorAction SilentlyContinue }
        & $venvPy (Join-Path $root "scripts\download_model.py") --model $Model
        return ($LASTEXITCODE -eq 0)
    }

    $ok = $false
    if ($HfMirror) {
        Write-Note "按 -HfMirror 先走镜像：$HF_MIRROR"
        $ok = Invoke-ModelDownload $HF_MIRROR
        if (-not $ok) {
            Write-Note "镜像没成功，换官方源再试一次..."
            $ok = Invoke-ModelDownload $null
        }
    } else {
        $ok = Invoke-ModelDownload $null
        if (-not $ok) {
            Write-Note "官方源没成功（大陆网络很常见），自动换镜像 $HF_MIRROR 再试一次..."
            $ok = Invoke-ModelDownload $HF_MIRROR
        }
    }

    if (-not $ok) {
        Fail "模型下载失败。" @(
            "确认网络能访问 huggingface.co 或 hf-mirror.com",
            "也可以手动下：$venvPy scripts\download_model.py --model $Model",
            "磁盘要留够空间（Qwen3.5-2B 约 4.3 GB）"
        )
    }
    Write-Done "模型下载完成：models\$dirName"
}

# ============================================================ 5. 起服务

Write-Step "5/5 启动服务 ..."

# 端口占用提前查：等模型加载完（几十秒）再报「端口被占」是最气人的。
function Test-PortInUse([int]$TargetPort) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $TargetPort)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if (Test-PortInUse $Port) {
    $owner = "（查不到是哪个进程）"
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($conn) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) { $owner = "（占用进程：$($proc.ProcessName).exe，PID $($conn.OwningProcess)）" }
        }
    } catch { }
    Fail "端口 $Port 已经被别的程序占用$owner" @(
        "办法一：换个端口启动 —— 在 cmd 里执行：一键启动.bat -Port $($Port + 1)",
        "办法二：关掉占用的进程 —— 任务管理器里结束上面那个 PID，或执行 Stop-Process -Id <PID>",
        "办法三：如果那个进程其实就是上次的帮你挑一个服务，直接在浏览器打开 http://127.0.0.1:$Port/ 就行"
    )
}

$serverArgs = @("-m", "tiaoyige.server")
if (-not (Test-RestHas $Rest "--model") -and -not (Test-RestHas $Rest "--model-dir")) {
    $serverArgs += @("--model", $Model)
}
if (-not (Test-RestHas $Rest "--device")) { $serverArgs += @("--device", $Device) }
if (-not (Test-RestHas $Rest "--port")) { $serverArgs += @("--port", "$Port") }
if (-not $NoBrowser) { $serverArgs += "--open-browser" }
$serverArgs += $Rest

Write-Done "环境就绪：基座 $dirName / 设备 $Device"
Write-Host ""
Write-Host "  页面地址：http://127.0.0.1:$Port/" -ForegroundColor White
Write-Host "  模型第一次加载要几十秒，页面会自动打开；等不及就手动刷新。" -ForegroundColor DarkGray
Write-Host "  停止服务：在这个窗口按 Ctrl+C，或者直接关掉窗口。" -ForegroundColor DarkGray
Write-Host ""

& $venvPy @serverArgs
$code = $LASTEXITCODE
if ($code -ne 0) {
    Fail "服务退出，退出码 $code。" @(
        "上面几行是 python 打印的原因",
        "如果是显存不够（CUDA out of memory），换小一点的基座：一键启动.bat -Model qwen3-0.6b",
        "如果是端口问题，换端口：一键启动.bat -Port $($Port + 1)"
    )
}
Write-Host "[结束] 服务已停止。" -ForegroundColor DarkGray
exit 0
