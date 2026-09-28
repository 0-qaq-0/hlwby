# 克隆上游判定引擎到 vendor/SemIf-OpenJev，并固定到本项目验证过的 commit。
#
# 为什么不入库：上游代码原样使用、不修改，放在 git 里既膨胀仓库又模糊归属。
# 用脚本按 commit 克隆，既能保证可复现，也能一眼核对用的哪个版本。
#
# 用法：
#   .\scripts\setup_vendor.ps1                 # 用默认 commit
#   .\scripts\setup_vendor.ps1 -Ref <sha>      # 指定别的 commit
#
# 已就绪时再跑一次是无操作，不会重复克隆。

[CmdletBinding()]
param(
    [string]$Ref = "23cf1f39fc9534fe81437200959b6dfc7106e45a"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$vendor = Join-Path $root "vendor"
$repo = Join-Path $vendor "SemIf-OpenJev"

$upstream = "https://github.com/TheoLeeCJ/SemIf-OpenJev.git"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "需要 git，请先安装：https://git-scm.com/"
}

# 已克隆且 commit 对得上 -> 直接返回
if (Test-Path (Join-Path $repo ".git")) {
    $head = git -C $repo rev-parse HEAD 2>$null
    if ($head -eq $Ref) {
        Write-Host "[vendor] 上游引擎已就绪 @ $($head.Substring(0, 8))" -ForegroundColor DarkGray
        return
    }
    Write-Host "[vendor] commit 不一致（当前 $head），切到 $Ref ..." -ForegroundColor Yellow
}
else {
    New-Item -ItemType Directory -Force -Path $vendor | Out-Null
    Write-Host "[vendor] 克隆 $upstream ..." -ForegroundColor Cyan
    git clone --quiet $upstream $repo
    if ($LASTEXITCODE -ne 0) { throw "克隆失败，检查网络后重试" }
}

git -C $repo checkout --quiet $Ref
if ($LASTEXITCODE -ne 0) { throw "切到 $Ref 失败" }

$head = git -C $repo rev-parse HEAD
Write-Host "[vendor] 上游引擎就绪 @ $($head.Substring(0, 8))" -ForegroundColor Green
