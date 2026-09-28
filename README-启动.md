# 帮你挑一个 · 启动说明（拿到 release 包先看这个）

把一条中文评论粘进来，它告诉你该回「典 / 孝 / 急 / 乐 / 蚌 / 批 / 赢 / 麻」里的哪个字。
模型不生成文字，只做一次前向传播读出概率，所以小模型也能做到百毫秒级。

这份文件是给**下载了 release 包**的人看的。只想最快跑起来的话，看下面三行就够了。

---

## 一、最快路径

**Windows**

1. 解压 zip（右键 → 全部解压缩；别在压缩包里直接双击）
2. 双击 `一键启动.bat`
3. 等它自己走完：建环境 → 装依赖 → 下模型 → 打开浏览器

**Linux / macOS**

```bash
unzip tiaoyige-4.2.0-linux.zip
cd tiaoyige-4.2.0
./start.sh            # 没有可执行位就：bash start.sh
```

第一次启动会花比较久（要下依赖和模型），**不要关窗口**。之后再启动就是几秒的事。

服务起来之后页面地址是 <http://127.0.0.1:8770/>（会自动打开）。
想停就回到那个窗口按 `Ctrl+C`。

---

## 二、第一次启动它到底在干什么

启动器按顺序做五件事，每步都会打印中文进度：

| 步骤 | 干什么 | 大概要多久 |
| --- | --- | --- |
| 1 | 找 Python（要 3.10 或更高） | 一秒 |
| 2 | 建 `.venv` 虚拟环境，装 `requirements.txt` | 几分钟（看网速） |
| 3 | 有 NVIDIA 显卡就装 CUDA 版 torch；没有就用 CPU | 几分钟（只在需要时做） |
| 4 | 把基座模型下到 `models/` | 很久（Qwen3.5-2B 约 4.3 GB） |
| 5 | 起服务、开浏览器 | 模型加载几十秒 |

第 2、3、4 步都是**幂等**的：环境在、依赖在、模型在，就直接跳过。
所以第二次启动只会做第 1 步和第 5 步。

### 需要准备什么

* **Python 3.10 或更高**（Windows 装的时候一定要勾上「Add python.exe to PATH」）
* **磁盘空间**：模型 Qwen3.5-2B 约 4.3 GB，加上依赖和虚拟环境，留 10 GB 比较稳
* **显卡**：有 NVIDIA 显卡会快很多；没有也能跑，就是慢（见下面「CPU 跑」）
* **网络**：第一次要下依赖和模型；之后可以完全离线用

---

## 三、常见问题

### 窗口一闪就没了 / 双击没反应

说明启动失败了，而 `pause` 那句没来得及看。打开 cmd，把 `一键启动.bat` 拖进去回车，
或者在该目录执行：

```bat
一键启动.bat
```

报错会留在窗口里。启动器的失败信息都是中文的，并且会直接告诉你怎么做。

### 装依赖太慢 / 超时（中国大陆常见）

```bat
一键启动.bat -Mirror
```

`-Mirror` 让 pip 走清华 TUNA 镜像。Linux/macOS 上是 `./start.sh --mirror`。

### 下模型太慢 / 连不上 huggingface.co

启动器**默认就是「先官方源，失败自动换 hf-mirror.com」**，所以你通常什么都不用做。
想直接走镜像（少等一次超时）：

```bat
一键启动.bat -HfMirror
```

Linux/macOS 是 `./start.sh --hf-mirror`。

也可以手动下：

```bat
.venv\Scripts\python.exe scripts\download_model.py --model qwen3.5-2b
```

> hf-mirror.com 是第三方镜像。权重按 `scripts/download_model.py` 里写死的 revision 拉取，
> 但如果你在意来源，就挂代理走官方源。

### 端口 8770 被占用

```bat
一键启动.bat -Port 8771
```

启动器在起服务**之前**就会检查端口，会告诉你占用它的进程名和 PID，不会让你等完模型加载才报错。

### 想换更小/更快的模型

```bat
一键启动.bat -Model qwen3-0.6b
```

可选：`qwen3-0.6b`（最小最快）/ `qwen3.5-2b`（默认）/ `qwen3.5-4b`（最准也最重）。
体积和实测准确率见 `docs/EVAL.md`。

### 没有 NVIDIA 显卡 / 是 macOS

能跑，走 CPU。判一条从零点几秒变成几秒，功能完全一样。

macOS 上注意：torch 的 MPS 加速**帮你挑一个用不上** —— 引擎的设备选择只认 `cuda` 和 `cpu`
（`tiaoyige/engine.py` 的 `pick_device`），所以在 Mac 上就是 CPU 跑。

### 显存不够（CUDA out of memory）

```bat
一键启动.bat -Model qwen3-0.6b
```

或者 `-Device cpu` 退回 CPU。两个参数可以一起用。

### 浏览器没自动打开

手动访问 <http://127.0.0.1:8770/>。也可以用 `-NoBrowser` 关掉自动打开。

### 想完全离线用

在**有网**的机器上先把包和模型准备好，然后把整个目录拷过去：

1. 有网机器上跑一次启动器，让它把 `.venv` 和 `models/` 都建好
2. 把整个目录（含 `.venv/`、`models/`）拷到离线机器
3. 离线机器上直接双击 `一键启动.bat`

注意 `.venv` 里的路径是写死的，两台机器的目录路径最好一致；
路径不一致就在离线机器上删掉 `.venv` 重新跑一次（依赖 wheel 得先在有网机器上缓存好：
`pip download -r requirements.txt -d wheels`，然后 `pip install --no-index --find-links wheels -r requirements.txt`）。

### 我下载的包是不是坏的？

包里有一份 `release-manifest.json`，列出每个文件的字节数和 sha256。校验方法见
`docs/RELEASE.md` 的「校验下载完整性」一节。

### 我的自定义判断类型（词表）在哪

在 `data/profiles/` 里，一个类型一个 JSON。**这个目录里的东西不会被上传、也不会进 release 包**，
删掉就等于清空自定义类型。内置的三套类型（八艺 / 内容处置 / 客服分流）写在代码里，删不掉。

### 怎么彻底卸载

删掉整个目录就行 —— 帮你挑一个不在系统里装任何东西（不写注册表、不装全局包）。
唯一在系统里的东西是 Python 本身。

---

## 四、包里有什么

```
tiaoyige-4.2.0/
├── 一键启动.bat          Windows 双击入口
├── start.sh              Linux / macOS 入口
├── run.ps1               给已经配好环境的人用的极简启动脚本
├── README-启动.md        本文件
├── README.md             项目总览
├── VERSION               版本号（纯文本）
├── release-manifest.json 文件清单 + sha256，用来校验下载完整性
├── requirements.txt      运行时依赖
├── tiaoyige/             判定引擎 + HTTP 服务 + 内置判断类型
├── web/                  页面（纯静态，无构建步骤）
├── scripts/              下载模型 / 评测 / 各种检查脚本
├── tests/                测试（不需要显卡，不联网）
├── data/                 评测集与评测结果；data/profiles/ 是你自己的词表目录
├── docs/                 评测报告、API、自定义类型、release 流程
└── vendor/SemIf-OpenJev/ 上游判定引擎（MIT）的必需子集
```

**模型权重不在包里**（Qwen3.5-2B 约 4.3 GB，超过 GitHub Release 单个附件的 2 GB 上限，
而且权重有自己的许可）。第一次启动时由 `scripts/download_model.py` 下载到 `models/`。
`models/` 和 `.venv/` 都不属于包的内容，删掉可以重来。

---

## 五、想跑测试 / 想看细节

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

测试不联网、不加载模型、不需要显卡，几秒就跑完。

* 项目总览与原理：`README.md`
* 打包与发布流程：`docs/RELEASE.md`
* 准确率怎么测出来的：`docs/EVAL.md`
* HTTP 接口：`docs/API.md`
* 自定义判断类型：`docs/CUSTOMIZE.md`
* 上游引擎的出处与版本：`docs/PROVENANCE.md`
