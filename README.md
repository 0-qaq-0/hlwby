# 帮你挑一个

给它一段文本、再给它一组**你自己定的选项**，它帮你挑一个。

模型不生成文字：每个选项绑到一个单字母槽位，一次前向传播读出概率，所以小模型也能半秒出结果。
**判定标准（锚点）是运行时的数据** —— 页面上就能改，改完不用重训、不用重启。

![判定页面](docs/screenshot.png)

内置的词表是网络梗「八艺」—— 把别人的一条评论粘进来，看看该用哪个字回他。
干净测试集 **52 条实测 80.8%**（5 排列，95% CI 68.1%~89.2%），页面示例 8/8。
评测是怎么做的、哪些写法会翻车，见 [docs/EVAL.md](docs/EVAL.md)。

---

## 一、跑起来

### 方式一：下载即用（推荐）

去 [Releases](https://github.com/0-qaq-0/hlwby/releases) 下载 `tiaoyige-<版本>-win64.zip`，
解压，双击 **`一键启动.bat`**。Linux / macOS 用 `./start.sh`。

启动器会自己做完这五件事，每步都打印中文进度：

| 步骤 | 干什么 |
|---|---|
| 1 | 找 Python（要 3.10 或更高；没有会告诉你去哪装） |
| 2 | 建 `.venv`、装依赖（国内网络慢就加 `-Mirror` 走清华源） |
| 3 | 有 NVIDIA 显卡就装 CUDA 版 torch，没有就按 CPU 跑 |
| 4 | 下载基座模型（Qwen3.5-2B，约 4.3 GB） |
| 5 | 起服务、打开浏览器 |

第一次要下载几个 GB，**别关窗口**；之后每次启动十几秒。服务地址 <http://127.0.0.1:8770/>，
在那个窗口按 `Ctrl+C` 停。

> 模型权重不在包里：它是 Qwen 的 Apache-2.0 权重（4.3 GB），不该由本项目转分发，
> GitHub Release 单文件也放不下。启动器会按 pinned revision 自己拉。

### 方式二：从源码跑

```powershell
git clone https://github.com/0-qaq-0/hlwby.git
cd hlwby

py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# CUDA 版 torch 要单独装 —— pip 默认给的是 CPU-only
.\.venv\Scripts\python.exe -m pip install --force-reinstall `
    "torch==2.14.0+cu130" --index-url https://download.pytorch.org/whl/cu130

# 下基座模型（约 4.3 GB）
.\.venv\Scripts\python.exe scripts\download_model.py --model qwen3.5-2b

# 起服务
.\.venv\Scripts\python.exe -m tiaoyige.server --open-browser
```

`.\run.ps1` 等价于上面全部（它会自己检查每一步、缺什么补什么）。

上游判定引擎已经随仓库分发（`vendor/SemIf-OpenJev/`），**不需要额外克隆**。

### 启动参数

| 参数 | 说明 |
|---|---|
| `--model qwen3.5-2b` | 换基座：`qwen3-0.6b`（最小最快）/ `qwen3.5-2b`（默认）/ `qwen3.5-4b`（最准最重） |
| `--device auto` | `auto`（有 CUDA 就用）/ `cuda` / `cpu`。没有 NVIDIA 显卡也能跑，就是慢 |
| `--port 8770` | 换端口（被占用时启动器会提前报出来） |
| `--open-browser` | 模型就绪后自动开浏览器 |
| `--profiles-dir <目录>` | 自定义判断类型的存放目录（默认 `data/profiles`） |

---

## 二、页面怎么用

四个标签页。URL 带 hash（`#judge` / `#labels` / `#eval` / `#settings`），可以直接发给别人。

### 判定

1. 选**判定类型**（下拉框，默认「八艺」）
2. 把评论粘进去
3. 选档位：**快**（3 排列，约 0.3 s）/ **标准**（5，约 0.5 s）/ **更稳**（7，约 0.7 s）
4. 点「判定」，或者按 <kbd>Ctrl</kbd>+<kbd>Enter</kbd>

结果区左边的大字就是**最贴切的那个选项**，下面是每个选项的概率分布，再下面是领先幅度和耗时。

几个顺手的：

* **示例**：点一下就用那条示例跑一遍（示例挑的是这套类型的典型样本）
* **批量模式**：一行一条，跑完可以导出 CSV / JSON
* **历史**：判定过的都在浏览器本地，点一条能重跑；「设置」页可以清空
* **复制结果** / **复制分享链接**：分享链接形如 `?t=<文本>&auto=1`，对方打开就能看到同一次判定
* **清空**：清输入框

> 概率是**在这几个选项之间归一化**的条件概率，不是校准过的置信度。
> 请当**排序**看，不要当「模型有多确定」。

### 词表（改判定类型）

左边列出所有判断类型（内置的标「内置」，没评测过的标「未评测」），右边是编辑器：

* 改**判定问法**、每个选项的**锚点描述**、**页面示例**
* 加 / 删 / 上移下移选项（2~16 个）
* 实时**校验**：已知会翻车的写法当场报出来（见第三节）
* **未保存也能试判**：在「用当前内容试判一条」里敲一句话，立刻看到结果怎么变
* 下面还摊着**模型实际读到的 payload** —— 想知道到底喂了什么，看它
* 保存 / 另存为副本 / 导出 JSON / 删除

内置类型只读：想改就先「另存为副本」，改自己那份。

### 评测

显示当前类型的成绩：准确率、95% 置信区间、测试集、分选项成绩。

没有评测数字的类型会明说「未评测」——**那不是不好用，是没人量过**；
页面上那个头条数字是「八艺」的，不能算在别的类型头上。

### 设置

服务与模型状态、深浅色、默认档位、清空本地历史、导出全部类型、API 示例。

---

## 三、自己定一套判断类型

这是这个工具真正的用法：**判定标准是你自己的数据。**

### 一套类型长什么样

| 字段 | 是什么 | 改了会怎样 |
|---|---|---|
| `criterion` | 判定问法，模型读的就是这句话 | 直接改变判定结果 |
| `labels[]` | 选项：id + **锚点描述** + 人话提示 + 配色 | 直接改变判定结果 |
| `examples[]` | 页面示例（点一下就能试） | 只影响体验 |
| `id` / `name` / `summary` | 身份 | 只是标签 |
| `version` | 锚点版本 | 改了措辞就该改它，否则说不清数字是哪版测的 |
| `evaluated` | 有没有在干净测试集上评测过 | 页面上会显示「未评测」徽标 |

选项 **2~16 个**（上游把选项绑在 `A`–`P` 这 16 个单 token 槽位上）。

### 三种改法

1. **页面上改**（推荐）：`词表` 标签页 → 新建 / 选一套 → 改锚点 → 保存。
   改完**不用重启服务**，判定页立刻就是新词表。
2. **直接写文件**：`data/profiles/<id>.json`，格式照抄
   [`tiaoyige/builtin_profiles/`](tiaoyige/builtin_profiles/) 里那两份。
3. **导入导出**：页面上的「导出 JSON」发给别人，对方「导入」即可。

![词表编辑器](docs/screenshot-labels.png)

### 写锚点的六条规则

这些不是拍脑袋定的，每条都有实测依据（细节见 [docs/EVAL.md](docs/EVAL.md)）：

| 规则 | 依据 |
|---|---|
| **描述「文本长什么样」，不要描述「说话人在干什么」** | 关系式写法（「当对方辩论时」）实测只有 50%，改成描述文本形态后到 96% |
| **给例句，别写抽象定义** | 多锚点 96% vs 长抽象定义 23% |
| **要示范，不要解释** | 描述里提到别的选项名，概率会漏给那个选项 |
| **别写泛化的形状描述** | 「一段不长不短的普通论述」这类话对什么文本都成立，会把概率全吸过去；实测删掉它准确率 +7.7 个百分点 |
| **别为了长度好看去删例句** | 删过几条去凑长度，准确率立刻从 96% 掉到 88% |
| **页面示例不能是锚点例句的复制品** | 那是自问自答，必对，没有信息量 |

### 校验会拦什么

页面改锚点时实时跑的就是这套规则（命令行是 `scripts/profiles_check.py`）：

**错误**拦住保存：

* 选项数量不在 2~16
* 选项 id 为空、重复、或含空白
* 某个选项没有锚点描述
* 页面示例指向了不存在的选项
* id 不是合法 slug（小写字母数字下划线连字符，2~48 位）

**提示**只提醒，不拦人（这些是经验，不是定理）：

* 描述里有泛化短语 / 写成关系式 / 提到别的选项名 / 几乎没有例句
* 页面示例和锚点例句字面重合（会给出重合度）
* 锚点字数极差偏大
* 这套类型还没评测过

### 改完怎么验证

```powershell
$py = ".\.venv\Scripts\python.exe"

& $py scripts\profiles_check.py            # 所有类型逐条校验（含你自己加的）
& $py scripts\leak_check.py                # 页面示例 / 测试集 有没有抄锚点
& $py scripts\evaluate.py --profile <id> --data <你的测试集> --write-result
```

**别拿页面示例自测。** 示例和锚点如果逐字重合，测出来的是自问自答 ——
句子就在 prompt 里，模型当然选得对。要量就得另准备一份干净测试集：
JSONL，每行 `{"id","text","label"}`，`label` 用这套类型自己的选项 id。

### 分享给别人

「导出 JSON」→ 对方「导入」。用户类型存在 `data/profiles/`，**不进 git、也不进 release 包**。

---

## 四、内置的三套类型

| id | 名字 | 选项 | 评测 |
|---|---|---|---|
| `bayi` | **八艺** | 典 孝 急 乐 蚌 批 赢 麻 | 干净集 52 条实测 80.8% |
| `support-router` | 客服分流 | 退款 物流 咨询 投诉 转人工 | 示例，**未评测** |
| `content-triage` | 内容处置 | 放行 折叠 删除 移交人工 | 示例，**未评测** |

后两套是**示例**（内置、只读、未评测）—— 它们存在的意义是证明「换一套判断类型不用动模型」。
准确率请自己拿真实数据量一遍再信。

### 八艺

| 字 | 什么时候回 | 视角 |
|---|---|---|
| **典** | 对方在陈述观点、分析原因 | 对方做了什么 |
| **孝** | 对方在维护、吹捧一个你不支持的人或事 | 对方做了什么 |
| **急** | 对方在辩论、分点论述、逐条回击 | 对方做了什么 |
| **乐** | 对方术语堆砌、故弄玄虚，你看不懂 | 我处于什么处境 |
| **蚌** | 对方把球踢给你，要你表态、拿方案 | 我处于什么处境 |
| **批** | 对方一刀切地批判、扣帽子、下判决 | 对方做了什么 |
| **赢** | 自己说了一句自认为一针见血的金句 | 我处于什么处境 |
| **麻** | 反驳不了也不想争了，敷衍一句认输 | 我处于什么处境 |

「客服分流」跑起来是这样（注意标题区那串字跟着类型变了）：

![用自定义类型判定](docs/screenshot-custom-type.png)

---

## 五、命令行

不占 GPU、秒回的检查 —— **改完锚点先跑这几个**：

| 命令 | 干什么 |
|---|---|
| `python -m unittest discover -s tests -t .` | 204 个单元测试（不联网、不加载模型） |
| `python scripts\profiles_check.py` | 所有判断类型逐条过校验规则 |
| `python scripts\leak_check.py` | 测试集 / 页面示例 与锚点的字面泄漏检查 |
| `python scripts\labels_check.py` | 「八艺」词表格式一致性 |
| `python scripts\page_check.py` | 页面：文件齐不齐、id 对不对、有没有硬编码数字 |
| `python scripts\docs_check.py` | 文档：README 里的数字和路径有没有过期 |

要 GPU 的：

| 命令 | 干什么 |
|---|---|
| `python scripts\evaluate.py --perms 3,5,7` | 主评测：干净集 + 对照集，三个速度档 |
| `python scripts\evaluate.py --profile <id> --data <测试集> --write-result` | 评一套自定义类型，并把头条数字落盘 |
| `python scripts\smoke_test.py --text "…"` | 只判一条，顺便量延迟 |
| `python scripts\live_check.py` | 对着跑起来的服务实测（页面示例 + 干净集） |
| `python scripts\order_bias.py` | 位置偏置诊断：同一条文本只换选项顺序，看答案变不变 |
| `python scripts\anchor_tune.py` | 锚点消融：找出把判定吸走的那个词 |
| `python scripts\experiment.py --variants shipped,short,keyword,relational` | 锚点写法 / 问法对比 |
| `python scripts\bench_perms.py` | 批量 vs 串行、可复现性 |

其他：

| 命令 | 干什么 |
|---|---|
| `python scripts\download_model.py --model qwen3-0.6b` | 拉基座模型到 `models/` |
| `python scripts\api_check.py` | API 校验与错误路径测试 |
| `python scripts\build_release.py --out dist` | 打 release 包（含 sha256 清单） |
| `powershell -File scripts\launch.ps1 -Mirror` | 一键启动（`一键启动.bat` 调的就是它） |
| `powershell -File scripts\setup_vendor.ps1` | 按 pinned commit 重新克隆上游引擎（可选） |

---

## 六、HTTP API

```powershell
curl http://127.0.0.1:8770/api/health

# permutations: 3=快 / 5=标准（默认）/ 7=更稳
curl -X POST http://127.0.0.1:8770/api/decide `
     -H "Content-Type: application/json" `
     -d '{"text":"人最大的敌人，从来都是自己。","permutations":5}'
```

返回：

```json
{
  "ok": true,
  "winner": "赢",
  "confidence": 0.99,
  "margin": 0.98,
  "ranking": [{"id": "赢", "probability": 0.99, "logit": 14.2, "...": "..."}],
  "input_tokens": 870,
  "permutations": 5,
  "permutations_requested": 5,
  "batch": 5,
  "forward_ms": 442.1,
  "total_ms": 477.3,
  "device": "cuda:0",
  "profile": "bayi",
  "profile_name": "八艺"
}
```

判定用哪套类型，三种来源（优先级从高到低）：

| 来源 | 写法 | 用途 |
|---|---|---|
| 内联词表 | `{"inline": {"criterion": "…", "labels": [...]}}` | 页面上**还没保存**的改动也能试判 |
| 指定类型 | `{"profile": "support-router"}` | 内置或 `data/profiles/` 里的任意一套 |
| 默认 | 不传 | 内置的「八艺」 |

其余接口：

| 接口 | 干什么 |
|---|---|
| `GET /api/profiles` | 列出所有判断类型（摘要） |
| `GET /api/profiles/<id>` | 一套类型的完整数据 + 校验结论 + 统计 |
| `GET /api/profiles/<id>/export` | 导出成可下载的 JSON |
| `POST /api/profiles` | 新建 / 覆盖保存（`{"profile": {…}, "overwrite": false}`） |
| `POST /api/profiles/validate` | 只校验不保存（页面的实时校验走它） |
| `POST /api/profiles/import` | 从导出文件导入 |
| `POST /api/profiles/delete` | 删一套用户类型（内置的删不掉） |
| `GET /api/labels` | 「八艺」的词表定义（老接口，等价于 `profiles/bayi`） |
| `GET /api/eval?profile=<id>` | 这套类型的头条数字；没有就返回 `available: false` |
| `GET /api/datasets` | 仓库里带了哪几套测试集、各多少条 |

完整参数、错误码和可粘贴运行的示例见 **[docs/API.md](docs/API.md)**。

---

## 七、它是怎么工作的

一次判定只有一次批量前向，不采样、不解码、不解析 JSON：

1. **把选项变成字母槽位** —— 每个选项绑一个大写字母 `A`–`P`，
   prompt 最后一个 token 就是「模型接下来要说的那个字母」
2. **校验槽位干净** —— 字母必须各自编码成唯一一个 token，且不会被并进相邻 token；不通过直接报错
3. **一次前向，只取最后一个位置** 的 logits
4. **只保留选项那几个槽位，再 softmax** —— 得到选项上的分布
5. **多种选项排列取平均** —— 见下

### 为什么要选档位

模型对**字母位置本身**有偏好。同一条文本、只把选项换个顺序，52 条干净集上的准确率在
**52%~71%** 之间摆动，只有 33% 的样本在 5 种排列下给出同一个答案。

所以默认用 5 种排列各判一次、按标签把概率平均。这些排列共享同一段文本，只是末尾的选项列表不同，
所以塞进**一个 batch** 跑，不是跑 5 次。页面上三档就是这个：

| 档位 | 排列数 | 准确率 | 95% CI | 端到端中位 |
|---|---:|---:|---|---:|
| 快 | 3 | 86.5% | 74.7%~93.3% | ~0.31 s |
| **标准（默认）** | **5** | **80.8%** | **68.1%~89.2%** | **~0.52 s** |
| 更稳 | 7 | 82.7% | 70.3%~90.6% | ~0.73 s |

> **三档的差异不显著**：52 条样本上 86.5% 和 80.8% 只差 3 条，置信区间大面积重叠。
> 别把「快档更准」当结论。单排列那一档倒是明确不行（52%~71%），所以不提供。

输入很长时会自动下调排列数，把延迟压在同一个量级。

---

## 八、换模型与性能

| 基座 | 体积 | 准确率 | 中位延迟 |
|---|---:|---:|---:|
| Qwen3-0.6B | 1.41 GB | 未在当前干净集上评测 | — |
| **Qwen3.5-2B（默认）** | **4.26 GB** | **80.8%** | **~0.52 s** |
| Qwen3.5-4B | 8.7 GB | 未评测 | — |

```powershell
& $py -m tiaoyige.server --model qwen3-0.6b
```

想加新基座：往 `tiaoyige/engine.py` 的 `MODEL_CHOICES` 里加一条 `名字 -> (目录名, commit)`。

延迟受 GPU 占用影响很大：表里的数字是 GPU 空闲时测的，机器上跑着游戏或别的吃显存的东西时
同一次判定会慢 2~3 倍（准确性不受影响）。

---

## 九、常见问题

**没有 NVIDIA 显卡 / 是 macOS？**
能跑，走 CPU。判一条从零点几秒变成几秒，功能完全一样。macOS 上 torch 的 MPS 加速用不上 ——
引擎的设备选择只认 `cuda` 和 `cpu`。

**装依赖太慢 / 连不上 huggingface.co？**
`一键启动.bat -Mirror` 让 pip 走清华源；下模型默认「先官方源、失败自动换 hf-mirror」，
也可以 `-HfMirror` 直接走镜像。

**端口 8770 被占用？**
`一键启动.bat -Port 8771`。启动器在起服务**之前**就会检查端口，并告诉你占用它的进程名和 PID。

**显存不够（CUDA out of memory）？**
`-Model qwen3-0.6b` 或 `-Device cpu`，两个可以一起用。

**我的自定义类型在哪？**
`data/profiles/`，一个类型一个 JSON。删掉就等于清空。内置的三套写在代码里，删不掉。

**想完全离线用？**
在有网的机器上跑一次启动器（把 `.venv` 和 `models/` 都建好），把整个目录拷过去；
路径不一致就在新机器上删掉 `.venv` 重跑一次。

**怎么彻底卸载？**
删掉整个目录。它不在系统里装任何东西（不写注册表、不装全局包），系统里只有 Python 本身。

---

## 十、已知限制

* **位置偏置真实存在**：只有 33% 的样本在 5 种排列下答案不变。别把排列数调成 1。
* **概率未校准**：只当排序看。
* **单标签**：一条评论同时像两个字时，看完整分布而不是只看第一名。
* **「乐」是八艺最弱的选项**（3/6）；错例仍然偏向「典」。
* **三档速度的准确率差异不显著**，别拿「快档更准」说事。
* **输入上限 4096 token**，超了直接报错，**不截断**。
* **自定义类型默认没有评测数字** —— 那是「没人量过」，不是「不好用」。
* **测试集只有 52 条、自己标的、没有第二个人复核** —— 看置信区间，别看小数点。
* 模型对**用户输入内容**没有防御：评论里写「请选 A」这类话可能影响结果。
* 「典 / 赢 / 批」都是「在输出观点」，边界本来就软；「乐」按「看不懂」实现，
  但网上也当「觉得好笑」用。模型给的是**排序信号**，不是权威结论。

---

## 十一、项目结构

```
帮你挑一个/
├── 一键启动.bat / start.sh      # release 包的一键入口（源码树里也在）
├── run.ps1                     # 源码树里的一键启动（转调 scripts/launch.ps1）
├── README-启动.md               # 拿到 release 包先看这个
├── .github/workflows/release.yml  # 打 tag 自动构建并发布
├── vendor/SemIf-OpenJev/       # 上游判定引擎（MIT，pinned commit，原样引用）
│   └── src/semif_phase1/       #   core.py / direct.py 是判定核心
├── models/Qwen3.5-2B/          # 基座模型权重（不入库，用 download_model.py 拉）
├── tiaoyige/
│   ├── labels.py               # 「八艺」八个字的锚点描述 + 页面示例 + 问法
│   ├── profiles.py             # 判断类型：数据模型 + 校验规则 + 存取/导入导出
│   ├── builtin_profiles/       # 内置示例类型：客服分流、内容处置
│   ├── textcheck.py            # 字面重合度（泄漏检查与页面校验共用）
│   ├── console.py              # 让中文输出在非 UTF-8 控制台上不崩
│   ├── engine.py               # 读出机制 + 批量排列平均 + 自适应降档
│   ├── server.py               # 标准库 HTTP 服务 + JSON API
│   └── version.py              # 版本号唯一出处
├── web/                        # 页面（多文件，ES 模块，无构建步骤）
│   ├── index.html              #   四个标签页的骨架
│   ├── style.css               #   设计系统（深/浅色）
│   └── js/                     #   api / util / state + tabs/{judge,labels,eval,settings}
├── tests/                      # ★ 204 个单元测试，只用标准库 unittest
├── data/
│   ├── eval_clean.jsonl        # 干净测试集（52 条），判断泛化能力以它为准
│   ├── eval_overlap.jsonl      # 对照集：页面示例变体 + 已知泄漏样本
│   ├── eval_result.json        # 头条数字的唯一出处，网页从 /api/eval 读它
│   ├── profiles/               # 你自己加的判断类型（不入库）
│   └── eval_results/           # 自定义类型的评测结果
├── docs/
│   ├── EVAL.md                 # 实测数字、位置偏置、失败方案
│   ├── CUSTOMIZE.md            # 自定义判断类型完全指南
│   ├── API.md                  # HTTP API 参考
│   ├── RELEASE.md              # 怎么切一个 release、包里有什么
│   ├── RELEASE_NOTES.md        # 发布说明（Actions 发版时读它）
│   ├── PROVENANCE.md           # 来源与归属：哪些是别人的，哪些是自己的
│   └── screenshot.png          # 页面截图（另有 -custom-type / -labels / -eval 三张）
├── scripts/                    # 见「五、命令行」那张表
├── LICENSE                     # MIT
└── requirements.txt
```

---

## 十二、许可与致谢

本项目以 **[MIT](LICENSE)** 协议开源。

* 引擎：**[TheoLeeCJ/SemIf-OpenJev](https://github.com/TheoLeeCJ/SemIf-OpenJev)**，MIT。
  上游判定代码原样引用，**未做修改**；本项目在外面包了几层：中文 system prompt、
  把输出接回选项、多种选项排列取平均（修位置偏置）、自适应降档，
  以及把「判什么」变成可编辑的运行时数据。
* 基座：**[Qwen/Qwen3.5-2B](https://github.com/QwenLM)**，Apache-2.0。权重不随本项目分发。
* 「Jev」及 TypeSafe 相关名称归其各自所有者；本项目与 TypeSafe AI、SemIf 作者
  **均无隶属关系**。详见 [docs/PROVENANCE.md](docs/PROVENANCE.md)。
* 「八艺」这套说法来自网络社区，本项目只是把它做成了可判定的标签集。
