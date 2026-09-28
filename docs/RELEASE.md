# 打包与发布（release）

这份文档讲三件事：**普通用户**怎么拿到并跑起来、包**里面有什么**、
**维护者**怎么切一个新版本。

面向用户的快速上手在 `README-启动.md`（release 包里也有一份），这里更偏「流程和校验」。

---

## 一、普通用户：两种拿法

### 方式 A：下载 release 包（推荐）

到 GitHub 的 Releases 页面下载对应平台的 zip：

| 文件名 | 平台 |
| --- | --- |
| `biaochi-<版本>-win64.zip` | Windows 10/11（x64） |
| `biaochi-<版本>-linux.zip` | Linux（x64） |

macOS 没有单独的包 —— `start.sh` 是通用的 bash 脚本，直接下 `linux` 那个包也能用
（见下面「macOS 与 CPU-only」）。

拿到之后：

1. **解压**（右键 → 全部解压缩 / `unzip`）。不要在压缩包里直接双击。
2. Windows 双击 `一键启动.bat`；Linux/macOS 执行 `./start.sh`。
3. 第一次会建环境、装依赖、下模型，等它走完，浏览器会自动打开。

模型权重不在包里（原因见文末），所以第一次启动要联网下几 GB。

### 方式 B：克隆源码

```bash
git clone https://github.com/0-qaq-0/hlwby.git
cd biaochi
```

然后同样双击 `一键启动.bat` / 执行 `./start.sh`。源码树和 release 包的区别只有一个：
源码树里多一个 `vendor/SemIf-OpenJev/` 的**完整上游仓库**（含约 30MB 的评测与 demo 资产），
包里只带运行必需的那几个文件。

---

## 二、包里有什么

```
biaochi-<版本>/
├── 一键启动.bat          Windows 双击入口（转调 scripts/launch.ps1）
├── start.sh              Linux / macOS 入口
├── run.ps1               环境已经配好时的极简启动脚本
├── README-启动.md        面向用户的中文快速上手
├── README.md             项目总览
├── VERSION               版本号（纯文本，内容是 biaochi/version.py 的 __version__）
├── release-manifest.json 文件清单 + 每个文件的字节数和 sha256
├── requirements.txt      运行时依赖
├── LICENSE               MIT
├── biaochi/             判定引擎、HTTP 服务、内置判断类型
├── web/                  页面（纯静态，无构建步骤）
├── scripts/              下载模型 / 评测 / 各类检查 / 本打包脚本
├── tests/                测试（不联网、不加载模型、不需要显卡）
├── data/                 评测集与评测结果
│   ├── eval_clean.jsonl / eval_overlap.jsonl / eval_result.json
│   ├── profiles/         你自己的判断类型放这里（包里只有一个 .gitkeep 占位）
│   └── eval_results/     按类型分开的评测结果（同样是占位）
├── docs/                 评测、API、自定义类型、出处、本文件
└── vendor/SemIf-OpenJev/ 上游引擎（MIT）的必需子集
```

### vendor 子集是怎么挑的

上游整个仓库都在源码树里，但运行时只 import `semif_phase1.core` 和 `semif_phase1.direct`
（见 `biaochi/engine.py` 顶部的 `sys.path` 注入）。所以包里只带：

* `vendor/SemIf-OpenJev/src/semif_phase1/*.py`（整个包目录，多带几个模块只多几十 KB，
  但能防止哪天 engine 多 import 一个模块就在用户机器上炸）
* `vendor/SemIf-OpenJev/LICENSE`、`README.md`、`pyproject.toml`（MIT 归属与出处）

排除掉的是 `results/ benchmarks/ webgpu-demo/ demo/ assets/ exl3-bridge/ manifests/
tests/ docs/ examples/` —— 那些是上游的评测证据和演示，加起来约 30MB，跑判定一个都用不到。

### 包里**没有**什么

| 没有 | 为什么 |
| --- | --- |
| `models/`（模型权重） | 4.3 GB，且 GitHub Release 单个附件上限 2 GB；权重另有自己的许可 |
| `.venv/` | 虚拟环境不可移植（路径写死），而且几百 MB |
| `.git/`、`.github/` | 仓库元数据和 CI 配置，对使用者没用 |
| `__pycache__/`、`*.pyc` | 构建垃圾 |
| `data/profiles/*.json` | **用户数据**：那是别人自己存的判断类型，不该跟着发行包走 |

`data/profiles/` 和 `data/eval_results/` 会留一个 `.gitkeep` 占位 —— zip 不记录空目录，
不占位的话用户解压出来会以为目录不存在。

---

## 三、校验下载完整性

包里的 `release-manifest.json` 就是干这个的：

```json
{
  "name": "biaochi",
  "version": "4.1.0",
  "schema": 1,
  "platform": "win64",
  "built_at": "2026-01-01T00:00:00Z",
  "python": "3.10.11",
  "file_count": 74,
  "total_bytes": 697000,
  "files": [{ "path": "biaochi/engine.py", "bytes": 17101, "sha256": "…" }]
}
```

`files` 按路径排序，**不含 manifest 自己**（自指的话哈希永远不稳定），
也不含 `built_at` 之外的任何时间信息 —— 同一份源码构建两次，这个列表逐字节相同。

### 先校验 zip 本身

GitHub Release 页面上每个附件旁边就有 sha256（构建日志里也会打印）。
本地对一下：

```powershell
# Windows PowerShell
Get-FileHash -Algorithm SHA256 .\biaochi-4.1.0-win64.zip
```

```bash
# Linux / macOS
sha256sum biaochi-4.1.0-linux.zip
```

### 再逐个文件校验（推荐，能查出「解压坏了」和「被改过」）

解压之后，在包目录里跑：

```bash
cd biaochi-4.1.0
python3 - <<'PY'
import hashlib, json, pathlib
manifest = json.loads(pathlib.Path("release-manifest.json").read_text(encoding="utf-8"))
bad = []
for entry in manifest["files"]:
    digest = hashlib.sha256(pathlib.Path(entry["path"]).read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        bad.append(entry["path"])
print(f"共 {manifest['file_count']} 个文件，{len(bad)} 个不一致")
for path in bad:
    print("  不一致:", path)
raise SystemExit(1 if bad else 0)
PY
```

```powershell
# Windows PowerShell 版
$pkg = "biaochi-4.1.0"
$manifest = Get-Content "$pkg\release-manifest.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$bad = @()
foreach ($f in $manifest.files) {
    $hash = (Get-FileHash -Algorithm SHA256 -Path (Join-Path $pkg $f.path)).Hash.ToLower()
    if ($hash -ne $f.sha256) { $bad += $f.path }
}
Write-Host "共 $($manifest.file_count) 个文件，$($bad.Count) 个不一致"
$bad | ForEach-Object { Write-Host "  不一致: $_" }
if ($bad.Count -gt 0) { exit 1 }
```

全对就说明包是完整的。**换行符也被算进哈希**：包里 `.bat` / `.ps1` 是 CRLF、
其余文本是 LF（跟仓库的 `.gitattributes` 一致），所以别在解压后「顺手格式化」再校验。

---

## 四、维护者：怎么切一个新 release

版本号只有一个出处：`biaochi/version.py` 的 `__version__`。
`/api/health`、页面页脚、`VERSION` 文件、manifest 里的 `version` 全都读它。

```powershell
# 1. 改版本号（唯一一处）
#    biaochi/version.py -> __version__ = "4.0.1"
#    判断类型 / API / 页面这类用户可见的东西有变化才进版本位

# 2. 跑测试（几秒钟，不联网、不加载模型、不占显存）
.venv\Scripts\python.exe -m unittest discover -s tests -t .

# 3. 本地先构建一次，确认包没问题（打印文件数、体积、zip 的 sha256）
.venv\Scripts\python.exe scripts\build_release.py --out dist

# 4. 解压出来验一遍：结构对不对、能不能 import
#    （这一步是 vendor 子集够不够的唯一凭据）

# 5. 提交、打 tag、推上去
git add -A
git commit -m "发布 4.0.1"
git tag v4.0.1
git push origin main --tags
```

第 5 步推上去之后，`.github/workflows/release.yml` 会自动：

1. 在 `windows-latest` 和 `ubuntu-latest` 上各跑一次
   `python scripts/build_release.py --platform <win64|linux> --expect-tag <tag>`；
2. 把两个 zip 作为 artifact 上传；
3. 用 `gh release create` 建一个 GitHub Release，把两个 zip 挂上去。

**tag 必须和 `version.py` 一致**，否则构建会直接失败：

```
[build] 失败：tag「v4.0.1」和 biaochi/version.py 里的版本号「4.1.0」不一致。
[build] 请先把 version.py 的 __version__ 改成 4.0.1 再打 tag，或者把 tag 改成 v4.1.0。
```

这条检查在 `build_release.py --expect-tag` 里，CI 里唯一的防线就是它 ——
Release 页面写着 v4.0.1、包里却是 4.1.0 的代码，是那种发出去之后才发现的错误。

发布说明：仓库里有 `docs/RELEASE_NOTES.md` 就用它（人工写的更准），
没有就让 GitHub 用 `--generate-notes` 按 commit 自动生成。

### 手动触发 / 补发布

Actions 页面点 `release` → `Run workflow`，`tag` 留空就是「用当前 ref」；
从分支手动跑时会自动取 `version.py` 里的版本号拼成 `v<版本>`。

命令行等价写法：

```bash
gh workflow run release.yml -f tag=v4.0.1
```

如果 release 已经存在（比如想重跑一次），工作流会改成 `gh release upload --clobber`
补传附件，不会报错退出。

---

## 五、手动构建（不走 CI）

```bash
python scripts/build_release.py --out dist          # 产出 dist/biaochi-4.1.0-win64.zip
python scripts/build_release.py --list              # 只看包里会有什么，不写文件
python scripts/build_release.py --no-zip            # 铺成目录，方便自己再压一次
python scripts/build_release.py --platform linux    # 换个平台标签（只影响文件名）
python scripts/build_release.py --name biaochi --version 4.1.0
python scripts/build_release.py --expect-tag v4.1.0 # 校验 tag 与版本号一致
python scripts/build_release.py --print-version     # 只吐版本号（CI 拼 tag 用）
```

构建脚本**只用标准库**，不需要装 torch / transformers —— CI 上也就不装，
省下每次几分钟的依赖下载。

`--with-model` 会把 `models/` 里已有的权重也打进包：

```bash
python scripts/build_release.py --with-model
```

只在局域网 / 离线分发时用。两个坑：

* **别用它发 GitHub Release**：单文件 2 GB 上限，Qwen3.5-2B 就 4.3 GB，传不上去。
* **打包时文件内容要读进内存**（算 sha256 + 写 zip），所以内存占用跟包体积同量级。
  8 GB 内存的机器打 4.3 GB 的模型包有被 OOM 杀掉的风险 —— 构建脚本会打印这条警告。

---

## 六、离线 / 无网环境

包本身不需要联网才能「解开」，但第一次启动要下依赖和模型。离线机器上的做法：

1. 在**有网**的机器上跑一次启动器，让它把 `.venv/` 和 `models/` 都建好；
2. 整个目录拷过去（`.venv/` 里的路径是写死的，两台机器路径最好一致）；
3. 离线机器上直接启动。

路径不一致就删掉 `.venv` 重建，依赖走本地 wheel 缓存：

```bash
# 有网机器上
pip download -r requirements.txt -d wheels
# 离线机器上
python -m venv .venv
.venv/bin/python -m pip install --no-index --find-links wheels -r requirements.txt
```

模型目录 `models/Qwen3.5-2B/` 是可以直接拷贝的普通文件（`*.safetensors` + config + tokenizer）。

---

## 七、CPU-only 与 macOS

引擎的设备选择只认 `cuda` 和 `cpu`（`biaochi/engine.py` 的 `pick_device`）。
所以：

* **没有 NVIDIA 显卡**：启动器会打印一句「用 CPU 跑，会慢很多」然后继续。
  判一条从零点几秒变成几秒，功能完全一样。
* **macOS**：torch 的 MPS 后端**标尺用不上** —— `pick_device` 不会返回 `mps`。
  Mac 上就是 CPU 跑。想强制指定用 `--device cpu` / `-Device cpu`。
* **AMD 显卡**：同理，走 CPU。

强制 CPU（比如显卡被别的任务占着）：

```bash
./start.sh --device cpu
```

```bat
一键启动.bat -Device cpu
```

---

## 八、中国大陆网络慢

三个开关，按需要叠加：

| 慢在哪一步 | 用什么 | 说明 |
| --- | --- | --- |
| pip 装依赖 | `-Mirror` / `--mirror` | 走清华 TUNA 镜像 |
| 下模型 | `-HfMirror` / `--hf-mirror` | 优先走 hf-mirror.com |
| 装 CUDA 版 torch | 没有镜像 | pytorch 的 wheel 只在官方源上；实在不行用 `--device cpu` |

下模型**默认就是「先官方源，失败自动换 hf-mirror.com」**，所以通常什么都不用加；
`-HfMirror` 只是省掉那次必然超时的等待。

> hf-mirror.com 是第三方镜像。权重按 `scripts/download_model.py` 里写死的 revision 拉取，
> 但如果你在意来源，就挂代理走官方源。

---

## 九、为什么模型权重不进包

三个原因，任何一个单独成立就够了：

1. **GitHub Release 单个附件上限 2 GB**，而默认基座 Qwen3.5-2B 约 4.3 GB，4B 更大。
   超了根本传不上去。
2. **包会变得没法用**：一个几百 KB 的包变成几 GB，每次发版都要重传、用户每次都要重下，
   而权重其实一个版本里很少变。
3. **许可是分开的**：代码是 MIT，模型权重是各自模型自己的许可条款。
   把权重塞进代码包，等于把两套许可混在一起分发。

所以权重走 `scripts/download_model.py` 在首次启动时按**写死的 revision** 下载到 `models/`，
下载源可以换（官方 / 镜像），revision 不能随便动 —— 换了基座版本，`docs/EVAL.md` 里的
实测数字就不再适用。

---

## 十、排错

**构建失败：包里缺少必需文件**

```
[build] 失败：包里缺少必需文件：
[build]   - README-启动.md
```

`build_release.py` 里有一份 `REQUIRED_FILES` 底线清单，缺一个就拒绝出包。
真删了某个文件的话，改清单的时候顺便想清楚用户拿到包会不会跑不起来。

**构建出来的包特别大**

```bash
python scripts/build_release.py --list | sort -k1 -n | tail
```

多半是 `--with-model` 打开了，或者有二进制资产混进了 `docs/`。
排除规则集中在 `build_release.py` 顶部那一段，改那里，别在别处加第二套判断。

**用户反馈「双击没反应」**

`一键启动.bat` 出错时会 `pause`，但用户可能已经把窗口关了。让他在 cmd 里跑一遍：

```bat
一键启动.bat
```

启动器的失败信息都是中文的，并且会直接给出下一步该做什么。

**Windows 上中文变成乱码**

`scripts/launch.ps1` 必须是 **UTF-8 with BOM + CRLF**：Windows PowerShell 5.1 读没有 BOM 的
UTF-8 脚本会按系统 ANSI 解码，中文提示全变天书。`一键启动.bat` 反过来必须是**无 BOM** 的
（cmd 会把 BOM 当成第一条命令的一部分）。这两条都有测试钉着（`tests/test_release.py`
的 `TestLineEndings`），构建时也会统一换行符。
