# 一键启动：真正的实现在 scripts/launch.ps1
#
# 这里刻意只做参数转译，不再自己写一遍 —— release 包里的「一键启动.bat」调的
# 也是同一个 launch.ps1。两份逻辑各自演化的话，就会出现「源码树里能跑、
# 下载包里不行」这种最难查的问题（历史上这种坑本项目踩过一次：页面上的数字
# 和 README 里的数字各说各话）。
#
# 用法：
#   .\run.ps1                                   # 默认 Qwen3.5-2B
#   .\run.ps1 -Model qwen3-0.6b                 # 换更小更快的基座
#   .\run.ps1 -Port 9000 -Mirror                # 换端口 + pip 走清华源
#   .\run.ps1 -Device cpu                       # 没显卡时
param(
    [string]$Model = "qwen3.5-2b",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$launcher = Join-Path $PSScriptRoot "scripts\launch.ps1"

if (-not (Test-Path $launcher)) {
    Write-Host "[失败] 找不到 $launcher" -ForegroundColor Red
    Write-Host "       如果是解压出来的包，确认 scripts\ 目录完整" -ForegroundColor Yellow
    exit 1
}

& $launcher -Model $Model @Rest
exit $LASTEXITCODE
