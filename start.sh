#!/usr/bin/env bash
# 标尺 —— 一键启动（Linux / macOS）
#
# 跟 Windows 的 scripts/launch.ps1 做同样五件事：
#   1. 找 Python（3.10+）
#   2. 没有 .venv 就建，并装 requirements.txt
#   3. 有 NVIDIA 显卡就装 CUDA 版 torch（macOS 没有 CUDA，走 CPU）
#   4. models/ 里没有权重就下载
#   5. 起服务
#
# 为什么不用 python 写这个启动器：用户可能连 python 都没有（要先装 Python
# 才能建 venv），所以第一层必须是最原始的东西 —— bash 和 .bat。
#
# 用法：
#   ./start.sh                          # 默认 Qwen3.5-2B
#   ./start.sh --port 9000 --model qwen3-0.6b
#   ./start.sh --mirror                 # pip 走清华 TUNA 镜像
#   ./start.sh --hf-mirror              # 优先用 hf-mirror.com 下模型
#   ./start.sh --device cpu             # 强制 CPU
#   ./start.sh --profiles-dir ~/mydir   # 不认识的参数原样转给服务

set -euo pipefail

# ---------------------------------------------------------------- 参数

PORT=8770
MODEL="qwen3.5-2b"
DEVICE="auto"
OPEN_BROWSER=1
PIP_MIRROR=0
HF_MIRROR_FIRST=0
EXTRA=()

while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="${2:?--port 后面要跟端口号}"; shift 2 ;;
        --port=*) PORT="${1#*=}"; shift ;;
        --model) MODEL="${2:?--model 后面要跟模型名}"; shift 2 ;;
        --model=*) MODEL="${1#*=}"; shift ;;
        --device) DEVICE="${2:?--device 后面要跟 auto/cuda/cpu}"; shift 2 ;;
        --device=*) DEVICE="${1#*=}"; shift ;;
        --no-browser) OPEN_BROWSER=0; shift ;;
        --mirror) PIP_MIRROR=1; shift ;;
        --hf-mirror) HF_MIRROR_FIRST=1; shift ;;
        -h|--help)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *)
            # 不认识的参数原样交给服务（例如 --host / --profiles-dir）。
            EXTRA+=("$1"); shift ;;
    esac
done

# ---------------------------------------------------------------- 输出

step() { printf '[启动] %s\n' "$1"; }
done_() { printf '[就绪] %s\n' "$1"; }
note() { printf '[注意] %s\n' "$1"; }

#: 失败统一出口：一句人话 + 若干条「照着做」的提示。
fail() {
    local message="$1"; shift
    printf '\n[失败] %s\n' "$message" >&2
    for hint in "$@"; do printf '       %s\n' "$hint" >&2; done
    printf '\n' >&2
    exit 1
}

#: 脚本自己所在目录 = 项目根（release 包里 start.sh 就在根目录）。
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"
REQUIREMENTS="$ROOT/requirements.txt"
PYPI_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
TORCH_INDEX="https://download.pytorch.org/whl/cu130"
HF_MIRROR="https://hf-mirror.com"

printf '\n  标尺 —— 这条评论该回哪个字（一键启动）\n'
printf '  项目目录：%s\n\n' "$ROOT"

# 基座名先校验一遍。不校验的话要等到第 4 步才由 python 的 argparse 报错，
# 那时用户已经等了半天，而且报错是英文的、还夹着一堆 usage 噪音。
case "$MODEL" in
    qwen3-0.6b|qwen3.5-2b|qwen3.5-4b) ;;
    *)
        fail "不认识的基座名：$MODEL" \
            "可选：qwen3-0.6b（最小最快）/ qwen3.5-2b（默认）/ qwen3.5-4b（最准也最重）" \
            "体积和实测准确率见 docs/EVAL.md 与 scripts/download_model.py"
        ;;
esac

# ============================================================ 1. 找 Python

step "1/5 找 Python（需要 3.10 或更高）..."

find_python() {
    # 3.10 排前面：项目就是按 3.10 验的。后面的都是兜底。
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        version="$("$candidate" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
        [ -n "$version" ] || continue
        major="${version%%.*}"
        rest="${version#*.}"
        minor="${rest%%.*}"
        if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; }; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

if ! BASE_PYTHON="$(find_python)"; then
    fail "没找到 Python 3.10 或更高版本。" \
        "Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip" \
        "Fedora/RHEL:   sudo dnf install python3 python3-pip" \
        "macOS(brew):   brew install python@3.12" \
        "装完重新执行 ./start.sh"
fi
done_ "找到 $BASE_PYTHON（$("$BASE_PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')）"

# ==================================================== 2. 虚拟环境 + 依赖

step "2/5 准备运行环境 .venv ..."

# 默认官方源：海外用户不用绕路；大陆用户失败了会看到「加 --mirror」的提示。
PIP_INDEX_ARGS=()
if [ "$PIP_MIRROR" -eq 1 ]; then
    PIP_INDEX_ARGS=(-i "$PYPI_MIRROR")
    note "pip 使用清华 TUNA 镜像：$PYPI_MIRROR"
fi

if [ ! -x "$VENV_PY" ]; then
    step "第一次启动：创建虚拟环境（.venv）..."
    # Debian/Ubuntu 上 python3-venv 没装时这一步会失败，所以提示写得很具体。
    if ! "$BASE_PYTHON" -m venv "$VENV_DIR"; then
        fail "创建虚拟环境失败。" \
            "Debian/Ubuntu 常见原因：缺 python3-venv —— sudo apt install python3-venv" \
            "确认磁盘有空间，并且目录可写：$VENV_DIR"
    fi
    done_ "虚拟环境建好了：$VENV_DIR"
fi

# 依赖齐不齐靠 import 试，而不是靠标记文件 —— 用户可能手动删过包。
if "$VENV_PY" -c "import torch, transformers, safetensors, huggingface_hub" >/dev/null 2>&1; then
    done_ "依赖已经齐了（跳过安装）"
else
    step "安装依赖（第一次要下几百 MB，慢慢等）..."
    "$VENV_PY" -m pip install --upgrade pip "${PIP_INDEX_ARGS[@]+"${PIP_INDEX_ARGS[@]}"}"
    if ! "$VENV_PY" -m pip install -r "$REQUIREMENTS" "${PIP_INDEX_ARGS[@]+"${PIP_INDEX_ARGS[@]}"}"; then
        if [ "$PIP_MIRROR" -eq 1 ]; then
            fail "安装依赖失败。" \
                "镜像也失败了，可能是网络本身不通，或者 TUNA 暂时抽风" \
                "手动重试：$VENV_PY -m pip install -r requirements.txt"
        fi
        fail "安装依赖失败。" \
            "确认网络能访问 pypi.org（公司网络 / 代理要额外配置）" \
            "大陆网络慢或超时很常见：./start.sh --mirror  （走清华 TUNA 镜像）"
    fi
    done_ "依赖装好了"
fi

# ==================================================== 3. torch 与显卡

step "3/5 检查显卡和 torch ..."

torch_ok=0
if "$VENV_PY" -c "import torch" >/dev/null 2>&1; then torch_ok=1; fi

has_nvidia=0
if command -v nvidia-smi >/dev/null 2>&1; then
    # 有 nvidia-smi 不等于有能用的卡（驱动坏掉时它也会失败）。
    if nvidia-smi >/dev/null 2>&1; then has_nvidia=1; fi
fi

if [ "$(uname -s)" = "Darwin" ]; then
    note "macOS 没有 CUDA：引擎会走 CPU（pick_device 只认 cuda / cpu）"
    note "torch 的 MPS 加速标尺用不上，所以判一条要几秒，不是零点几秒"
elif [ "$has_nvidia" -eq 1 ]; then
    cuda_ok=0
    if [ "$torch_ok" -eq 1 ]; then
        if [ "$("$VENV_PY" -c 'import torch; print(1 if torch.cuda.is_available() else 0)' 2>/dev/null || echo 0)" = "1" ]; then
            cuda_ok=1
        fi
    fi
    if [ "$cuda_ok" -eq 1 ]; then
        done_ "NVIDIA 显卡可用，torch 已经是 CUDA 版（跳过重装）"
    else
        step "检测到 NVIDIA 显卡，装 CUDA 版 torch（wheel 有好几个 GB，慢）..."
        note "pytorch 的 wheel 只在官方源上，这一步不走 TUNA 镜像"
        # --force-reinstall 是必要的：requirements.txt 装的是 CPU 版，
        # pip 认为「torch==2.14.0 已满足」不会替换，CUDA 就永远用不上。
        if ! "$VENV_PY" -m pip install --force-reinstall "torch==2.14.0+cu130" --index-url "$TORCH_INDEX"; then
            note "CUDA 版 torch 没装上。不影响使用 —— 可以先用 CPU 跑：./start.sh --device cpu"
            note "（CPU 能出结果，就是慢很多；想用显卡就检查网络后重跑一次）"
        else
            done_ "CUDA 版 torch 装好了"
        fi
    fi
else
    note "没检测到可用的 NVIDIA 显卡（nvidia-smi 不存在或跑不起来）"
    note "会用 CPU 跑：功能完全一样，但速度慢很多（每判一条从零点几秒变成几秒）"
fi

# ============================================================ 4. 模型

step "4/5 检查基座模型 ..."

# 目录名 = 模型名（qwen3.5-2b -> Qwen3.5-2B），跟 engine.py 的 MODEL_CHOICES 对齐。
case "$MODEL" in
    qwen3-0.6b) DIR_NAME="Qwen3-0.6B" ;;
    qwen3.5-2b) DIR_NAME="Qwen3.5-2B" ;;
    qwen3.5-4b) DIR_NAME="Qwen3.5-4B" ;;
    *) DIR_NAME="$MODEL" ;;
esac
MODEL_DIR="$ROOT/models/$DIR_NAME"

has_weights=0
if [ -d "$MODEL_DIR" ] && compgen -G "$MODEL_DIR/*.safetensors" >/dev/null; then
    has_weights=1
fi

if [ "$has_weights" -eq 1 ]; then
    done_ "模型在本地：models/$DIR_NAME（$(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1 || echo '?')）"
else
    step "本地没有 $DIR_NAME，开始下载（几 GB，第一次要等挺久）..."

    # 策略：**先官方，失败自动换 hf-mirror.com**。理由 ——
    #   目标用户主要在中国大陆，huggingface.co 经常直接连不上；
    #   但海外用户走镜像反而绕远。自动回退两头都不吃亏，
    #   而且用户不需要知道 HF_ENDPOINT 是什么。
    #   --hf-mirror 是给「知道自己要走镜像」的人用的（先镜像，少等一次超时）。
    # 注意 hf-mirror.com 是第三方镜像：权重按 download_model.py 里写死的
    # revision 拉取，在意来源的话请走官方源（挂代理）。
    download_model() {
        local endpoint="$1"
        if [ -n "$endpoint" ]; then
            HF_ENDPOINT="$endpoint" "$VENV_PY" "$ROOT/scripts/download_model.py" --model "$MODEL"
        else
            env -u HF_ENDPOINT "$VENV_PY" "$ROOT/scripts/download_model.py" --model "$MODEL"
        fi
    }

    ok=0
    if [ "$HF_MIRROR_FIRST" -eq 1 ]; then
        note "按 --hf-mirror 先走镜像：$HF_MIRROR"
        if download_model "$HF_MIRROR"; then
            ok=1
        else
            note "镜像没成功，换官方源再试一次..."
            if download_model ""; then ok=1; fi
        fi
    else
        if download_model ""; then
            ok=1
        else
            note "官方源没成功（大陆网络很常见），自动换镜像 $HF_MIRROR 再试一次..."
            if download_model "$HF_MIRROR"; then ok=1; fi
        fi
    fi

    if [ "$ok" -ne 1 ]; then
        fail "模型下载失败。" \
            "确认网络能访问 huggingface.co 或 hf-mirror.com" \
            "也可以手动下：$VENV_PY scripts/download_model.py --model $MODEL" \
            "磁盘要留够空间（Qwen3.5-2B 约 4.3 GB）"
    fi
    done_ "模型下载完成：models/$DIR_NAME"
fi

# ============================================================ 5. 起服务

step "5/5 启动服务 ..."

# 端口占用提前查：等模型加载完（几十秒）再报「端口被占」是最气人的。
# 用 venv 里的 python 查，不依赖 ss / lsof / nc 这些各家发行版不一定有的工具。
if "$VENV_PY" -c "
import socket, sys
sock = socket.socket()
sock.settimeout(0.5)
sys.exit(0 if sock.connect_ex(('127.0.0.1', $PORT)) == 0 else 1)
" 2>/dev/null; then
    fail "端口 $PORT 已经被别的程序占用。" \
        "办法一：换端口 —— ./start.sh --port $((PORT + 1))" \
        "办法二：找出占用者 —— lsof -i :$PORT  或  ss -ltnp | grep $PORT" \
        "办法三：如果那就是上次的标尺服务，直接打开 http://127.0.0.1:$PORT/ 就行"
fi

SERVER_ARGS=(-m biaochi.server --model "$MODEL" --device "$DEVICE" --port "$PORT")
if [ "$OPEN_BROWSER" -eq 1 ]; then SERVER_ARGS+=(--open-browser); fi
if [ "${#EXTRA[@]}" -gt 0 ]; then SERVER_ARGS+=("${EXTRA[@]}"); fi

done_ "环境就绪：基座 $DIR_NAME / 设备 $DEVICE"
printf '\n  页面地址：http://127.0.0.1:%s/\n' "$PORT"
printf '  模型第一次加载要几十秒，页面会自动打开；等不及就手动刷新。\n'
printf '  停止服务：在这个终端按 Ctrl+C。\n\n'

"$VENV_PY" "${SERVER_ARGS[@]}"
printf '[结束] 服务已停止。\n'
