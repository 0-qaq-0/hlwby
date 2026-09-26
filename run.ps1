# 一键启动：建环境 -> 装依赖 -> 下模型 -> 起服务
#
# 用法：
#   .\run.ps1                                   # 默认 Qwen3.5-2B
#   .\run.ps1 --model qwen3-0.6b                # 换更小更快的基座
#   .\run.ps1 --port 9000                       # 换端口
param(
    [string]$Model = "qwen3.5-2b",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "[run] 创建虚拟环境..." -ForegroundColor Cyan
    py -3.10 -m venv (Join-Path $root ".venv")
    & $py -m pip install --upgrade pip
    & $py -m pip install -r (Join-Path $root "requirements.txt")
    Write-Host "[run] 安装 CUDA 版 torch（Blackwell 需要 cu128+）..." -ForegroundColor Cyan
    & $py -m pip install --force-reinstall "torch==2.14.0+cu130" `
        --index-url https://download.pytorch.org/whl/cu130
}

# 上游引擎（vendor/）不入 git，第一次跑需要先克隆
& (Join-Path $root "scripts\setup_vendor.ps1")

# 目录名 = 模型名，例如 qwen3.5-2b -> Qwen3.5-2B
$dirName = switch ($Model) {
    "qwen3-0.6b" { "Qwen3-0.6B" }
    "qwen3.5-2b" { "Qwen3.5-2B" }
    "qwen3.5-4b" { "Qwen3.5-4B" }
    default      { $Model }
}
$modelDir = Join-Path $root "models\$dirName"

$weights = Get-ChildItem -Path $modelDir -Filter "*.safetensors" -ErrorAction SilentlyContinue
if (-not $weights) {
    Write-Host "[run] 下载基座模型 $dirName 到项目内..." -ForegroundColor Cyan
    & $py (Join-Path $root "scripts\download_model.py") --model $Model
}

Write-Host "[run] 启动服务 http://127.0.0.1:8770/  (基座 $dirName)" -ForegroundColor Green
& $py -m jev_meme.server --model $Model @Rest
