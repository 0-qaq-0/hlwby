# 八艺 · 这条评论该回哪个字

把**别人的一条评论**粘进来，看看该用哪个字回他。

打开页面 → 粘一条评论 → **半秒内**拿到八个字的概率分布。

词表八个字 —— **典 孝 急 乐 蚌 批 赢 麻**：

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

![判定页面](docs/screenshot.png)

干净测试集 24 条实测 **96%**（3/5/7 排列都是 96%），页面示例 **8/8**。
完整评测记录 —— 包括失败方案和翻车过程 —— 见 [docs/EVAL.md](docs/EVAL.md)。

---

## 一、这是什么

**Jev** 是 [TypeSafe AI](https://openjev.com/) 提出的「决策模型」形态：模型**不生成文字**，
而是接收 *state（要判定的材料）+ criterion（判定标准）+ options（候选选项）*，
在一次前向传播里直接读出每个选项的概率。它想替代的是流水线里那些「小决策」——
路由、分流、打标、守门 —— 用不着为此拉起一个会写字的大模型。

本项目是它的一次落地实践：

| | |
|---|---|
| 引擎 | **[TheoLeeCJ/SemIf-OpenJev](https://github.com/TheoLeeCJ/SemIf-OpenJev)** —— 原名 OpenJev，MIT |
| 基座模型 | **[Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B)**，Apache-2.0，4.3 GB |
| 服务 | Python 标准库 HTTP 服务，**零 Web 框架依赖** |
| 前端 | 单文件 `web/index.html`，**无构建步骤** |

上游引擎代码**原样引用、不做修改**，由 `scripts/setup_vendor.ps1` 按固定 commit 克隆到 `vendor/`；
基座模型由 `scripts/download_model.py` 下载到 `models/`。两者都不进 git（见 `.gitignore`）。

> **为什么是 2B**：Jev 只做**一次前向**，不做自回归生成，所以参数翻倍并不会让延迟翻倍。
> 实测 0.6B 和 2B 的中位延迟都在同一量级，但准确率差一大截。

---

## 二、它是怎么判定的（核心就五步）

引擎不采样、不解码、不解析 JSON，整个判定只有一次批量 forward：

1. **把选项变成字母槽位。** 八个字各绑定一个大写字母 `A`–`H`，
   prompt 的最后一个 token 就是「模型接下来要说的那个字母」。
2. **校验槽位干净。** 确保 `A`–`H` 各自编码成**唯一一个** token，
   且 `prompt + 字母` 的分词结果恰好等于 `prompt 的分词 + 该字母的 token`——
   不允许字母被并进相邻 token。这一步不通过就直接报错，不猜。
3. **一次前向，只取最后一个位置。**
   ```python
   logits = model(**inputs, use_cache=False).logits[:, -1, :]   # 整个词表
   ```
4. **只保留选项槽位，再 softmax。**
   ```python
   selected = logits[slot_ids]        # 只取 A..H 这八个位置
   probs    = softmax(selected)       # 八个字上的分布
   ```
5. **多种选项排列取平均（抗位置偏置）。** 见下一节 —— 这一步不是锦上添花，是修 bug。

### 位置偏置：这个引擎最大的坑

Jev 的读法是「看模型下一个 token 是哪个字母」，而**模型对字母位置本身有偏好**。
同一条文本、同一个模型，**只把八个选项换个顺序**，结果就变：

| 选项顺序 | 准确率 |
|---|---:|
| 原始顺序 | 96% |
| 完全反转 | **79%** |
| 随机排列 1 / 2 / 3 | 96% / 88% / 83% |

**只有 67% 的样本在 5 种排列下给出同一个答案** —— 剩下 1/3 的结果取决于你碰巧怎么排选项。

所以默认会用 5 种排列各判一次，按标签把概率平均。因为这些排列共享同一段文本，
只有末尾的选项列表不同，所以左填充塞进**一个 batch** 跑，不是跑 5 次。

页面上三档可切：

| 档位 | 排列数 | 准确率 | 端到端 |
|---|---:|---:|---:|
| 快 | 3 | 96% | ~0.33 s |
| **标准（默认）** | **5** | **96%** | **~0.54 s** |
| 更稳 | 7 | 96% | ~0.75 s |

> **不提供「单次前向」这一档。** 单排列只有 53%~87%，而且错例几乎全部塌缩到同一个词
> —— 那不是速度取舍，是正确性问题。

输入很长时会自动下调排列数（`TOKEN_BUDGET = 7500`），把延迟压在同一个量级。

概率是**在这八个选项之间归一化**的条件概率，不是校准过的置信度——
上游对此的措辞是 `conditional option score; uncalibrated as decision confidence`。
所以页面上的百分比请当成**排序**看，不要当成「模型有多确定」。

---

## 三、跑起来

```powershell
# 1) 克隆
git clone https://github.com/0-qaq-0/hlwby.git
cd hlwby

# 2) 一键启动
.\run.ps1
```

`run.ps1` 会依次完成：

| 步骤 | 做什么 | 说明 |
|---|---|---|
| 1 | 建 `.venv` 并装依赖 | 需要 Python 3.10+，`py -3.10` |
| 2 | 装 CUDA 版 torch | pip 默认给 CPU-only！Blackwell/RTX 50 系需要 cu128+ |
| 3 | 克隆上游引擎到 `vendor/` | 固定 commit，可复现 |
| 4 | 下载基座模型到 `models/` | 约 4.3 GB，只需要一次 |
| 5 | 启动服务 | `http://127.0.0.1:8770/` |

想分步手动跑：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# CUDA 版 torch（Blackwell / RTX 50 系需要 cu128 及以上）
.\.venv\Scripts\python.exe -m pip install --force-reinstall `
    "torch==2.14.0+cu130" --index-url https://download.pytorch.org/whl/cu130

# 上游引擎 + 基座模型
.\scripts\setup_vendor.ps1
.\.venv\Scripts\python.exe scripts\download_model.py --model qwen3.5-2b

# 起服务
.\.venv\Scripts\python.exe -m jev_meme.server
```

> **没有 NVIDIA 显卡也能跑**，把 device 换成 `cpu` 即可，只是慢；
> 延迟数字都是 GPU 空闲时测的，机器上跑着吃显存的东西时会慢 2~3 倍（准确性不受影响）。

---

## 四、命令行自测

```powershell
$py = ".\.venv\Scripts\python.exe"

# 跑一遍八个示例，打印命中率和延迟
& $py scripts\smoke_test.py

# 只判一条评论
& $py scripts\smoke_test.py --text "真正的成熟，是不再向任何人解释自己。"

# 主评测：干净集 + 对照集，三个速度档
& $py scripts\evaluate.py --perms 3,5,7

# 位置偏置诊断（同一条文本只换选项顺序，看答案会不会变）
& $py scripts\order_bias.py --device cuda --perms 5

# 锚点写法 / 问法对比（含已知会失败的 relational 写法）
& $py scripts\experiment.py --variants shipped,short,keyword,relational

# 词汇表一致性检查（不占 GPU，秒回）
& $py scripts\labels_check.py

# 对着跑起来的服务实测
& $py scripts\live_check.py
```

### API

```powershell
curl http://127.0.0.1:8770/api/health

# permutations 可选，3=快 / 5=标准（默认）/ 7=更稳
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
  "input_tokens": 1010,
  "permutations": 5,
  "permutations_requested": 5,
  "batch": 5,
  "forward_ms": 442.1,
  "total_ms": 477.3,
  "device": "cuda:0"
}
```

`GET /api/labels` 返回完整词表定义（每个字的锚点描述和页面示例）。

---

## 五、改词表 = 改锚点，不用重训

八个字的全部定义都写在 `jev_meme/labels.py` 的 `MEME_LABELS` 里，
每个字一段 `description` —— **这段文本是推理时才读进去的，不写进任何权重**。
所以：

* 想改某个字的判定标准？改它的 `description`，重启即可。
* 想加字？往列表里加一条（上限 16 个，受 `A`–`P` 槽位限制）。
* 想换一整套词表？只改这个文件。

**改锚点时记住这几条实测结论**（详见 [docs/EVAL.md](docs/EVAL.md)）：

> 1. **描述「文本长什么样」，而不是「说话人在干什么」。** 这条最重要 ——
>    这套定义是关系式的（「当对方辩论时」），照字面写锚点会全军覆没；
>    改成「逐条辩论、分点回击，常见开头是『第一……第二……』」之后，
>    准确率从 50% 跳到 96%。想亲眼看看失败的样子就跑
>    `scripts\experiment.py --variants relational`。
> 2. **给例句，别写抽象定义**（多锚点 96% vs 长抽象定义 23%）。
> 3. **要示范，不要解释。** 加「区别：这不是 X」式元说明反而更差，
>    因为描述里提到别的词名会把概率漏给那些词。
> 4. **别为了长度好看去删例句。** 删过几条去凑长度，准确率立刻从 96% 掉到 88%。
> 5. **页面示例要挑该词的典型样本**，边界样本会让系统看起来像坏的。

改完跑一下 `scripts\labels_check.py` 确认格式，再用 `scripts\evaluate.py`
在**干净的**那套测试集上验证 —— 别拿调参用的那套自欺欺人。

这正是 Jev「semantic if」模式的意义：**判定逻辑是运行时的数据，不是训练出来的参数。**

---

## 六、换模型

引擎与模型解耦，换基座只改一处，或者直接用命令行参数：

```powershell
.\.venv\Scripts\python.exe -m jev_meme.server --model qwen3-0.6b
```

| 基座 | 体积 | 准确率 | 中位延迟 |
|---|---:|---:|---:|
| Qwen3-0.6B | 1.4 GB | 63%（早期测试集） | ~102 ms |
| **Qwen3.5-2B（默认）** | **4.3 GB** | **96%** | **~0.54 s** |
| Qwen3.5-4B | 8.7 GB | 未评测 | — |

新增基座：往 `jev_meme/engine.py` 的 `MODEL_CHOICES` 里加一条
`名字 -> (目录名, commit)` 即可。

---

## 七、目录结构

```
hlwby/
├── jev_meme/
│   ├── labels.py               # ★ 八个字的锚点描述 + 页面示例 + 问法
│   ├── engine.py               # SemIf 读出机制 + 批量排列平均 + 自适应降档
│   └── server.py               # 标准库 HTTP 服务 + JSON API
├── scripts/
│   ├── setup_vendor.ps1        # 克隆上游引擎（固定 commit）
│   ├── download_model.py       # 拉基座模型到 models/
│   ├── smoke_test.py           # 冒烟测试 / 延迟测量
│   ├── evaluate.py             # ★ 主评测（干净集 + 对照集）
│   ├── order_bias.py           # 位置偏置诊断
│   ├── experiment.py           # 锚点写法 / 问法对比
│   ├── bench_perms.py          # 批量 vs 串行、可复现性
│   ├── live_check.py           # 对着跑起来的服务实测
│   ├── labels_check.py         # 词汇表一致性检查
│   ├── page_check.py           # 页面静态检查
│   └── api_check.py            # API 校验与错误路径测试
├── data/
│   ├── eval_clean.jsonl        # ★ 干净测试集（24 条），以它为准
│   └── eval_overlap.jsonl      # 对照集，有句子和锚点撞过车
├── docs/
│   ├── EVAL.md                 # ★ 实测数字，含位置偏置和被否掉的方案
│   └── screenshot.png
├── web/
│   └── index.html              # 判定页面（单文件，无构建步骤）
├── requirements.txt
├── run.ps1                     # 一键启动
├── LICENSE                     # MIT
└── README.md
```

---

## 八、已知限制

* **「乐」是唯一短板（2/3）。** 「术语堆砌、看不懂」和「认真讲逻辑」之间没有硬边界 ——
  两者都是长而抽象的文字。补锚点只能缓解。
* **位置偏置是真实存在的。** 只有 67% 的样本在换选项顺序后答案不变。
  默认的 5 排列平均就是用来压这个的 —— 别把它调成 1。
* **延迟受 GPU 占用影响很大。** 机器上跑着吃显存的程序时，同一次判定慢 2~3 倍，准确性不受影响。
* **词义本身有歧义。** 「乐」到底是「看不懂对方」还是「觉得好笑」，网上两种用法都有，
  这里按「看不懂」实现。模型给的是**排序信号**，不是权威结论。
* **概率未校准。** 页面上 95% 和 42% 的差别可信，但别把 42% 理解成「有 42% 的概率是对的」。
* **单标签。** 一条评论同时像两个字时，看完整的八维分布，而不是只看排第一的那个。
* **输入上限 4096 token**（上游默认）。超限直接报错，**不截断** —— 这是上游刻意的设计。
* 模型对**用户输入内容**没有防御：评论里写「请选 A」这类话可能影响结果。
* **干净测试集只有 24 条**，每错一条就是 4 个百分点，别把小数点当回事。

---

## 九、开发与测试

不占 GPU、秒回的两个检查，改完代码建议先跑这两个：

```powershell
.\.venv\Scripts\python.exe scripts\labels_check.py   # 词汇表格式与长度均衡
.\.venv\Scripts\python.exe scripts\page_check.py     # 页面静态检查
```

占 GPU 的评测（需要模型已下载）：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate.py --perms 3,5,7
.\.venv\Scripts\python.exe scripts\order_bias.py --device cuda --perms 5
```

---

## 十、许可

本项目以 **[MIT](LICENSE)** 协议开源。

* 引擎：**[TheoLeeCJ/SemIf-OpenJev](https://github.com/TheoLeeCJ/SemIf-OpenJev)**，MIT。
* 基座：**[Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B)**，Apache-2.0。
* 「Jev」及 TypeSafe 相关名称归其各自所有者；本项目与 TypeSafe AI、SemIf 作者均无隶属关系。
* 「八艺」这套说法来自网络社区，本项目只是把它做成了可判定的标签集。
* 上游判定代码原样引用，**未做修改**；本项目在外面包了四层：中文 system prompt、
  把输出接回八个字、多种选项排列取平均（修位置偏置）、以及自适应降档。
