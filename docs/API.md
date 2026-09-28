# HTTP API 参考

这份文档解决一个问题：**要写脚本或者把判定接进自己的系统，该打哪个接口、传什么、会拿到什么、
出错长什么样。** 逐条对齐 `jev_meme/server.py`（服务端实现）和 `jev_meme/engine.py`（判定核心），
所有路由、参数上限、错误文案都是从代码里抄下来并且**实测跑过一遍**的。

> **以代码为准。** 这份文档如果和 `jev_meme/server.py` 打架，以代码为准 ——
> 但那种情况应该被当成 bug 报出来，而不是当成「文档就是这样写的」。
>
> 本文的示例假定服务在 **`http://127.0.0.1:8770`** 跑着：
> `.\.venv\Scripts\python.exe -m jev_meme.server`（模型在启动时加载一次并常驻，
> 之后每个请求就是一次前向传播）。

---

## 一、通用约定

| 项 | 值 | 出处 |
|---|---|---|
| 默认地址 | `http://127.0.0.1:8770`（`--host` / `--port` 可改） | `server.main()` |
| 服务实现 | Python 标准库 `ThreadingHTTPServer`，零 Web 框架依赖 | `server.py` |
| 请求/响应编码 | UTF-8；请求体必须是 **JSON 对象** | `_read_json()` |
| 响应类型 | `application/json; charset=utf-8`（导出接口也是） | `_json()` / `_send()` |
| 缓存 | 所有响应带 `Cache-Control: no-store` | `_send()` |
| 请求体上限 | **`MAX_BODY_BYTES = 262144`**（256 KiB） | `server.py` |
| 待判文本上限 | **`MAX_TEXT_CHARS = 20000`** 字 | `server.py` |
| 模型输入上限 | **4096 token**（`engine.MAX_TOKENS`），超限报错、**不截断** | `engine._build_prompt()` |
| `Content-Type` | **不校验**（`text/plain` 发 JSON 也认） | 实测确认 |
| `HEAD` | 等价于 `GET`，只是不写响应体 | `do_HEAD()` |
| 版本号 | 在 `GET /api/health` 的 `version` 字段里（`4.0.0`） | `jev_meme/version.py` |

### 请求体是怎么被检查的

顺序就是 `_read_json()` 里的顺序，任何一步不过就是 **HTTP 400**：

| 情况 | 返回的 `error` |
|---|---|
| `Content-Length` 头不是整数 | `Content-Length 不合法` |
| 缺 `Content-Length`、或值为 0（等于空请求体） | `请求体长度必须在 1 到 262144 字节之间` |
| `Content-Length` > 262144 | 先把已声明的请求体读掉（最多 8 MiB，`MAX_DRAIN_BYTES`）再回同一条错误 |
| 不是合法 JSON | `请求体不是合法 JSON：<解析器原文>` |
| 是合法 JSON 但不是对象（比如 `[1,2,3]`） | `请求体必须是一个 JSON 对象` |

> **为什么超限之前还要读一遍请求体**：客户端是按 `Content-Length` 一次性写过来的，
> 服务端不读就回响应，客户端可能还在写 —— Windows 上这会变成
> `ConnectionAbortedError (WinError 10053)`，测试会随机红。
> 有封顶（8 MiB）是为了不让一个巨大的 `Content-Length` 把连接拖住。

### 错误形状

所有错误都是同一个形状：

```json
{ "ok": false, "error": "中文说明" }
```

`/api/profiles*` 这几个接口的**校验类**错误还会多一个 `issues` 数组：

```json
{
  "ok": false,
  "error": "校验没通过：选项「甲」没有锚点描述 —— 它才是决定判定结果的那段文字",
  "issues": [
    { "level": "error", "field": "labels[0]", "message": "选项「甲」没有锚点描述 —— 它才是决定判定结果的那段文字" }
  ]
}
```

`level` 是 `error`（拦住保存）或 `warning`（只提示）。规则明细见
[CUSTOMIZE.md](CUSTOMIZE.md) 第六节。

---

## 二、接口一览

| 方法 | 路径 | 干什么 | 失败码 |
|---|---|---|---|
| GET | `/api/health` | 服务与模型状态、默认档、有哪些判断类型 | — |
| GET | `/api/profiles` | 列出所有判断类型（轻量摘要） | — |
| GET | `/api/profiles/<id>` | 读一套类型的完整定义 + 校验结果 + 统计 + 评测数字 | 404 |
| GET | `/api/profiles/<id>/export` | 导出一份可分享的 profile JSON | 404 |
| GET | `/api/labels` | 「八艺」的词表（老接口，等价于 bayi 那一套） | — |
| GET | `/api/eval[?profile=<id>]` | 某套类型的评测头条数字 | — |
| GET | `/api/datasets` | 仓库里带了哪几套测试集、各多少条 | — |
| GET | `/` `/index.html` 及其他静态文件 | 页面（限制在 `web/` 目录内） | 404 |
| POST | `/api/decide` | **判定** | 400 / 500 |
| POST | `/api/profiles/validate` | 只校验、不保存 | 400 |
| POST | `/api/profiles` | 保存一套类型（同 id 要 `overwrite`） | 400 |
| POST | `/api/profiles/import` | 从导出文件 / 手写 JSON 导入 | 400 |
| POST | `/api/profiles/delete` | 删除一套**用户**类型 | 400 / 404 |

> **没有 `GET /api/version`。** 版本号在 `GET /api/health` 的 `version` 字段里。
> 未知 GET 路径回 404 `{"ok": false, "error": "没有这个路径：<path>"}`，
> 未知 POST 路径回 404 `{"ok": false, "error": "没有这个接口：<path>"}` ——
> 注意**方法用错也算「没有这个路径」**：`GET /api/decide` 是 404，不是 405。

---

## 三、GET 接口

### `GET /api/health`

健康检查 + 服务自述。写客户端时先打它，确认模型已经加载好、默认档是多少。

```json
{
  "ok": true,
  "version": "4.0.0",
  "loaded": true,
  "device": "cuda:0",
  "dtype": "bfloat16",
  "model": "D:\\...\\models\\Qwen3.5-2B",
  "model_name": "Qwen3.5-2B",
  "load_seconds": 12.3,
  "default_permutations": 5,
  "prompt_version": "meme-direct-zh-v4",
  "labels": ["典", "孝", "急", "乐", "蚌", "批", "赢", "麻"],
  "default_profile": "bayi",
  "profiles": ["bayi", "content-triage", "support-router"],
  "user_profile_dir": "D:\\...\\data\\profiles"
}
```

| 字段 | 含义 |
|---|---|
| `version` | 服务版本（`jev_meme/version.py`） |
| `loaded` | 模型是否已加载（启动时加载完才开服务，正常恒为 `true`） |
| `device` / `dtype` | 实际跑在哪个设备、什么精度（`cuda` 是 bfloat16，`cpu` 是 float32） |
| `model` / `model_name` | 模型目录全路径 / 目录名 |
| `load_seconds` | 模型加载耗时（秒） |
| `default_permutations` | 默认排列数（`engine.DEFAULT_PERMUTATIONS = 5`） |
| `prompt_version` | **锚点版本** —— 改了锚点措辞就该改它，否则「这个数字是哪版锚点测的」说不清 |
| `labels` | 「八艺」八个字的 id |
| `default_profile` | 不指定类型时用哪套（`bayi`） |
| `profiles` | 当前所有可用类型的 id（内置在前、用户在后） |
| `user_profile_dir` | 用户类型存盘目录 |

### `GET /api/profiles`

列出所有判断类型，**不带锚点正文**（列表页不需要）。

```json
{
  "ok": true,
  "default": "bayi",
  "profiles": [
    {
      "id": "bayi", "name": "八艺", "summary": "八个字：典 孝 急 乐 蚌 批 赢 麻 —— 这条评论该回哪个字",
      "version": "meme-direct-zh-v4", "label_count": 8,
      "label_ids": ["典", "孝", "急", "乐", "蚌", "批", "赢", "麻"],
      "example_count": 8, "builtin": true, "evaluated": true, "updated_at": ""
    }
  ]
}
```

| 字段 | 含义 |
|---|---|
| `default` | 默认类型 id |
| `profiles[]` | 每项是 `Profile.to_summary()`：`id` / `name` / `summary` / `version` / `label_count` / `label_ids` / `example_count` / `builtin` / `evaluated` / `updated_at` |

内置在前、用户在后；**同 id 时用户版不会覆盖内置版**（内置只读）。

### `GET /api/profiles/<id>`

读一套类型的全部内容，顺带把它现在的校验结论、统计和评测数字一起给你 ——
页面编辑器打开一套类型时打的就是这个接口。

```json
{
  "ok": true,
  "profile": { "...": "Profile.to_dict()，完整形式，含 labels/examples" },
  "issues": [{ "level": "warning", "field": "labels", "message": "锚点字数 99~241，极差 142 偏大（>70）……" }],
  "stats": {
    "label_count": 8, "example_count": 8,
    "description_chars": 1125, "description_min": 99, "description_max": 241,
    "anchor_examples": 48, "criterion_chars": 34, "prompt_chars": 1159
  },
  "eval": { "...": "同 GET /api/eval?profile=<id>" }
}
```

| 字段 | 含义 |
|---|---|
| `profile` | 完整定义（`schema`/`id`/`name`/`summary`/`criterion`/`version`/`note`/`labels`/`examples`/`builtin`/`evaluated`/`updated_at`） |
| `issues[]` | `validate()` 的结果，**error 和 warning 都在里面**（读的时候不拦人，只是告诉你） |
| `stats` | `profile_stats()`：锚点总字数、最短/最长锚点、引号例句数、问法字数、**进 prompt 的总字数** |
| `eval` | 该类型的评测数字，结构同 `/api/eval` |

`<id>` 会先做 URL 解码。类型不存在 → **404** `{"ok": false, "error": "没有这个判断类型：<id>"}`。

### `GET /api/profiles/<id>/export`

导出成一份**可以直接分享给别人导入**的文件。

* 返回的是**裸 profile JSON**（`Profile.to_dict()`），**不是** `{"ok": ...}` 信封；
* 带 `Content-Disposition: attachment; filename="<id>.json"`，浏览器点一下就是下载；
* 导出文件里带着 `"builtin": true/false`，但**导入时这个标记会被强制丢掉** ——
  否则「导入一份内置类型的副本」永远失败。

```json
{
  "schema": 1, "id": "bayi", "name": "八艺", "summary": "……", "criterion": "……",
  "version": "meme-direct-zh-v4", "note": "……",
  "labels": [{ "id": "典", "name": "典", "pinyin": "diǎn", "description": "……", "hint": "……", "accent": "#c2410c" }],
  "examples": [{ "label": "典", "text": "……" }],
  "builtin": true, "evaluated": true, "updated_at": ""
}
```

类型不存在 → **404**（同样走 `{"ok": false, "error": "没有这个判断类型：<id>"}`）。

### `GET /api/labels`

「八艺」的词表 —— 保留的老接口，等价于 `GET /api/profiles/bayi` 里的那三样，
但结构更简单（页面早期版本用的就是它）。

```json
{ "ok": true, "criterion": "下面这句网上的发言，最符合「八艺」里的哪一个？请选出最贴切的那一个。",
  "labels": [{ "id": "典", "pinyin": "diǎn", "name": "典", "description": "……", "hint": "……", "accent": "#c2410c" }],
  "examples": [{ "label": "典", "text": "……" }] }
```

### `GET /api/eval[?profile=<id>]`

某套类型的**评测头条数字**。网页副标题就是从这里读的 —— 数字只有一个出处，
页面才不会过期（`web/index.html` 曾经硬编码「24 条 96%」，测试集换成 52 条之后没人记得改）。

```json
{
  "ok": true, "profile": "bayi", "available": true,
  "profile_name": "八艺", "profile_version": "meme-direct-zh-v4",
  "dataset": "data/eval_clean.jsonl", "permutations": 5,
  "total": 52, "correct": 42, "accuracy": 0.8077,
  "ci95": [0.681, 0.892], "median_ms": 525.9,
  "per_label": { "典": { "correct": 6, "total": 7 }, "乐": { "correct": 3, "total": 6 } },
  "note": "由 scripts/evaluate.py --write-result 生成；网页和文档从这里读头条数字"
}
```

（上面的值就是当前 `data/eval_result.json` 里的内容，`per_label` 只列了两项。）

| 字段 | 含义 |
|---|---|
| `profile` | 查询的类型 id（默认 `bayi`） |
| `available` | 有没有评测结果文件 |
| `dataset` / `permutations` | 这个数字是在哪份测试集、几排列上测的 |
| `total` / `correct` / `accuracy` | 条数 / 判对条数 / 准确率（0~1） |
| `ci95` | Wilson 95% 置信区间 |
| `median_ms` | 端到端中位延迟（毫秒） |
| `per_label` | 每个选项的分标签成绩（`{correct, total}`），用来找短板 |
| `note` | 生成方式说明 |

**没跑过评测时**（HTTP 仍然是 200）：

```json
{ "ok": true, "profile": "support-router", "available": false,
  "note": "这套判断类型还没跑过评测",
  "how": "python scripts/evaluate.py --profile support-router --write-result" }
```

几件要知道的事：

* 结果文件按类型分：`bayi` 读 `data/eval_result.json`（历史文件，不能挪），
  其他类型读 `data/eval_results/<id>.json`（`profiles.eval_result_path()`）；
* **这个接口不校验 `profile` 是否存在**，也不做 id 白名单 —— 它只是把
  `<id>` 拼进路径找文件。找不到就当「还没评测」回 `available: false`。
  要把它暴露给不可信调用方的话，自己先挡一层；
* 返回体是 `{"ok", "profile", "available", ...文件内容}` 摊平的结果，
  所以**字段取决于文件里写了什么** —— 老的结果文件可能没有 `per_label`，
  新跑出来的会有。要拿某个字段之前先判一下存在性。

### `GET /api/datasets`

仓库里带了哪几套测试集、各多少条。**只报条数，不报准确率** ——
准确率只有一个出处（`data/eval_results/*.json`），页面不能自己算一份出来。

```json
{
  "ok": true,
  "datasets": [
    { "name": "eval_clean", "path": "data/eval_clean.jsonl", "exists": true, "rows": 52,
      "note": "干净集：与锚点例句无字面重合，判断泛化能力以它为准" },
    { "name": "eval_overlap", "path": "data/eval_overlap.jsonl", "exists": true, "rows": 39,
      "note": "对照集：装着已知和锚点撞过车的句子，数字不代表泛化能力" }
  ]
}
```

名单是写死的两条（`eval_clean` / `eval_overlap`），没有参数。
文件不在时 `exists: false`、`rows: 0`。**你自己的测试集不会出现在这里** ——
它是你机器上的文件，跟这套接口无关。

### 静态文件与 404

`GET /` 和 `/index.html` 返回页面；其余路径按静态文件处理，**限制在 `web/` 目录内**
（`(WEB_DIR / path).resolve()` 必须真的在 `WEB_DIR` 下面，挡目录穿越）。
文件不存在或越界 → **404** `{"ok": false, "error": "没有这个路径：<path>"}`。
`/` 和 `/index.html` 是直接读 `web/index.html` 的，那个文件不在时回的是另一条：
**404** `{"ok": false, "error": "缺少文件：<绝对路径>"}`。

---

## 四、`POST /api/decide` —— 判定

### 请求参数

| 字段 | 类型 | 必填 | 默认 | 约束 |
|---|---|---|---|---|
| `text` | string | **是** | — | 非空（`strip()` 后不能是空白）；长度 ≤ **20000** 字 |
| `permutations` | int | 否 | **5** | 整数（`true` 这种 bool 会被拒），**1~16** |
| `profile` | string | 否 | `"bayi"` | 类型必须存在，否则 400 |
| `inline` | object | 否 | — | 页面上**还没保存**的词表，见下 |

### 三种词表来源与优先级

```
inline  ──有就只用它───────────►  最高优先级
   │ 没有
   ▼
profile ──给了就用它───────────►  必须已存在（内置或 data/profiles/ 里的）
   │ 没给
   ▼
bayi    ──默认「八艺」─────────►  DEFAULT_PROFILE_ID
```

代码就一句 `if inline is not None:` —— **只要请求体里出现 `inline` 且不是 `null`，
`profile` 字段就被完全忽略**（哪怕它是个不存在的 id，也不会报错）。

#### `inline` 的约束

`inline` 是给页面编辑器用的：改一句锚点要能**立刻**看效果，所以判定接口得吃得下未保存的数据。
它只挡会炸引擎的东西，经验性的检查交给 `/api/profiles/validate` —— 试判本来就是用来试错的。

| 约束 | 不满足时 |
|---|---|
| 必须是一个 JSON 对象 | `inline 必须是一个对象` |
| `criterion` 非空 | `inline.criterion 不能为空` |
| `labels` 是 **2~16** 个选项 | `inline.labels 必须是 2~16 个选项，现在 N 个` |
| 选项 `id` 不能重复 | `inline.labels 的选项 id 有重复` |
| 每个选项都要有非空 `description` | `inline.labels 里「X」没有锚点描述` |

`inline` 里的 `id` 缺省是 `"inline"`（返回体里的 `profile` 就是它）；
没给 `name` 时 `profile_name` 是**空串**。`inline` **不校验** `id` 是否符合文件名规则、
也不跑 `validate()` 的那些经验规则。

### 返回

```json
{
  "ok": true,
  "mode": "choice",
  "winner": "赢",
  "confidence": 0.99,
  "margin": 0.98,
  "ranking": [
    { "id": "赢", "pinyin": "yíng", "hint": "自己说了一句自认为一针见血的金句。",
      "accent": "#15803d", "probability": 0.99, "logit": 14.2 },
    { "id": "典", "pinyin": "diǎn", "hint": "对方在陈述观点、分析原因 —— 一律回典。",
      "accent": "#c2410c", "probability": 0.004, "logit": 8.1 }
  ],
  "input_tokens": 1010,
  "permutations": 5,
  "permutations_requested": 5,
  "batch": 5,
  "forward_ms": 442.1,
  "total_ms": 477.3,
  "server_ms": 477.6,
  "model": "D:\\...\\models\\Qwen3.5-2B",
  "device": "cuda:0",
  "prompt_version": "meme-direct-zh-v4",
  "profile": "bayi",
  "profile_name": "八艺",
  "profile_version": "meme-direct-zh-v4"
}
```

> 上面这些**数字是示例**（随输入、机器、GPU 占用变化），字段名和结构是实测的。
> `ranking` 里是**全部**选项（八艺就是 8 条），上面只列了前两条。

| 字段 | 含义 |
|---|---|
| `mode` | 恒为 `"choice"`（单选模式） |
| `winner` | 概率最高的选项 id —— **这就是判定结果** |
| `confidence` | `ranking[0].probability`。**未校准**，见下 |
| `margin` | 第一名减第二名。差得越小说明越「同时像好几个」 |
| `ranking[]` | **全部**选项，按 `probability` 降序。每项：`id` / `pinyin` / `hint` / `accent` / `probability` / `logit` |
| `probability` | 该选项的概率，**已按选项排列平均**（见下）。所有选项加起来等于 1 |
| `logit` | 该选项槽位上的 logit，**同样是多排列平均后的值**，不是某一次的原始 logit |
| `input_tokens` | **prompt 的 token 数**（含 system、锚点、待判文本），不是待判文本的长度 —— 八个字的锚点本身就有约 950 token，所以一句话评论也有 1000 左右 |
| `permutations` | **实际**参与平均的排列数（自动降档后） |
| `permutations_requested` | 请求里要的排列数。**两个值不一样就说明降档了** |
| `batch` | 批量前向的行数，等于 `permutations` |
| `forward_ms` | 一次批量前向的耗时 |
| `total_ms` | 引擎内部总耗时（量 prompt 长度 + 前向），不含 HTTP 层 |
| `server_ms` | 服务端从进入处理函数到出结果的耗时，**包含** `total_ms` 那一段 |
| `model` / `device` | 模型目录 / 实际设备 |
| `prompt_version` | 锚点（prompt）版本 |
| `profile` / `profile_name` / `profile_version` | 用的是哪套类型、显示名、该类型的 `version` |

#### 概率未校准：只能当排序看

`probability` 是**在这几个选项之间归一化**的条件概率。上游 SemIf 对它的措辞是：

> `conditional option score; uncalibrated as decision confidence`

也就是说：**95% 和 42% 的差别可信，但别把 42% 理解成「有 42% 的概率是对的」。**
页面上的百分比请当成**排序**看，不要当成「模型有多确定」。
想要「有多确定」，得自己在干净测试集上做校准 —— 本项目没做。

#### 为什么要多种排列取平均

引擎读的是「下一个 token 是哪个字母」，而**模型对字母位置本身有偏好**。
同一条文本、同一个模型，只把选项换个顺序，52 条干净集上的实测：
原始顺序 71% / 完全反转 60% / 随机排列 67%、62%、52% —— **极差 19 个百分点**，
纯粹是位置噪声；**只有 33%（17/52）的样本在 5 种排列下给出同一个答案**。

所以默认跑 5 种排列（原始顺序 + 完全反转 + 3 个固定 seed 的随机排列），
按选项 id 把概率平均。因为这些排列共享同一段文本，只有末尾的选项列表不同，
所以左填充塞进**一个 batch** 跑，不是跑 5 次。

* 固定 seed（`permutations_of(labels, count, seed=0)`）→ **同一个输入永远得到同一个答案**；
* `permutations: 1` 只有原始顺序、不做平均。**别用它** —— 单排列实测只有 52%~71%，
  会塌缩到描述最长、位置占便宜的那个选项。这不是性能取舍，是正确性问题。

#### 长输入自动降档

prompt 本身就不短（八个字的锚点约 950 token），所以预算按 **prompt 长度**算，
不是按评论长度算（这个 bug 项目里犯过一次）：

```python
TOKEN_BUDGET = 7500
adaptive_permutations(tokens, requested) = max(1, min(requested, TOKEN_BUDGET // max(tokens, 1)))
```

| 输入 | prompt token | 请求 3 / 5 / 7 时实际用的排列数 |
|---|---:|---|
| 一句话评论 | ~1000 | 3 / 5 / 7 |
| 长评论 | ~2000 | 3 / 3 / 3 |
| 长文 | ~3400 | 2 / 2 / 2 |
| 接近上限 | 4000+ | 1 / 1 / 1 |

**实际用了几个看返回里的 `permutations`。** 这样延迟基本被压在同一个量级，
不会随输入长度线性膨胀。

### 错误码

| 情况 | HTTP | `error` |
|---|---:|---|
| `text` 缺失 / 不是字符串 / 全空白 | 400 | `字段 text 必须是非空字符串` |
| `text` 超过 20000 字 | 400 | `文本太长，最多 20000 字` |
| `permutations` 不是整数（含 `true`） | 400 | `permutations 必须是整数` |
| `permutations` 不在 1~16 | 400 | `permutations 必须在 1 到 16 之间` |
| `profile` 不是非空字符串 | 400 | `profile 必须是字符串` |
| `profile` 不存在 | 400 | `没有这个判断类型：<id>` |
| `inline` 不合法 | 400 | 见上一节的表 |
| 输入超过 4096 token | 400 | `输入 N token，超过上限 4096；按上游约定不做截断` |
| 其它 `ValueError`（如文本为空） | 400 | 原始消息 |
| 未预期的异常 | 500 | `判定失败：<异常>`（同时往 stderr 打 traceback） |
| 请求体问题 | 400 | 见第一节的表 |

---

## 五、判断类型管理接口

这四个接口是页面词表编辑器的全部后端 —— **没有第二套逻辑**。

### `POST /api/profiles/validate` —— 只校验，不保存

编辑器每敲几下就调一次它。

```json
{ "profile": { "id": "code-review", "name": "评审意见", "criterion": "……", "labels": ["…"] } }
```

请求体可以直接是 profile，也可以是 `{"profile": {...}}`（两种都认）。
返回：

```json
{
  "ok": true,
  "issues": [{ "level": "warning", "field": "evaluated", "message": "这套类型还没有在干净测试集上评测过。……" }],
  "error_count": 0,
  "warning_count": 1,
  "stats": { "label_count": 3, "example_count": 3, "description_chars": 264,
             "description_min": 80, "description_max": 96, "anchor_examples": 11,
             "criterion_chars": 31, "prompt_chars": 295 }
}
```

**HTTP 永远是 200**（除非请求体本身不合法）—— 校验不过是通过 `error_count` 表达的。
`profile` 不是对象时 400 `profile 必须是一个 JSON 对象`。

### `POST /api/profiles` —— 保存

```json
{ "profile": { "...": "完整 profile" }, "overwrite": false }
```

* 请求体可以直接是 profile，也可以是 `{"profile": {...}}`；
* `overwrite` 缺省 `false`：同 id 已存在时回 400
  「已经存在同 id 的类型「xxx」，确认要覆盖再重试。」（`issues` 里带
  `{"level": "error", "field": "id", "message": "同 id 已存在"}`）；
* 有 `error` 级问题时回 400，`error` 文案是「校验没通过：」+ 各条 message 用「；」拼起来，
  `issues` 里是全部明细；
* `id` 是内置的 `bayi` 时回 400
  「bayi 是内置类型的 id（它永远在，只读），换一个，比如 bayi-2」——
  想改八艺的锚点就另存为一份新的；
* 保存时会做三件你看不见的事：`builtin` 强制改回 `false`、
  `updated_at` 写成当前 UTC 时间、文件落到 `<user_profile_dir>/<id>.json`。

成功返回（比导入多一个 `issues`）：

```json
{ "ok": true, "profile": { "...": "Profile.to_dict()" },
  "summary": { "...": "Profile.to_summary()" },
  "issues": [{ "level": "warning", "field": "evaluated", "message": "……" }] }
```

### `POST /api/profiles/import` —— 导入

参数和 `/api/profiles` **完全一样**（`profile` / `overwrite`），区别只有返回体少了 `issues`：

```json
{ "ok": true, "profile": { "...": "Profile.to_dict()" }, "summary": { "...": "Profile.to_summary()" } }
```

导出文件可以直接喂进来。文件里没有 `id` → 400 `导入的文件里没有 id`。

### `POST /api/profiles/delete` —— 删除

```json
{ "id": "code-review" }
```

| 情况 | HTTP | 返回 |
|---|---:|---|
| 成功 | 200 | `{"ok": true, "deleted": "code-review"}` |
| `id` 缺失/非字符串/空 | 400 | `{"ok": false, "error": "字段 id 必须是非空字符串"}` |
| `id` 不存在 | 404 | `{"ok": false, "error": "没有这个判断类型：<id>"}` |
| `id` 是内置类型 | 400 | `{"ok": false, "error": "「bayi」是内置类型，删不掉 —— 内置类型只读"}` |

**只删用户类型**（`data/profiles/<id>.json`）。内置类型在代码里
（`jev_meme/labels.py` + `jev_meme/builtin_profiles/*.json`），接口删不掉。

---

## 六、PowerShell 示例（可直接粘贴）

下面每一段都在 Windows PowerShell 7 上**对着跑在 `127.0.0.1:8770` 的服务实跑过**，
语法和字段名可以直接用。中文请求体统一用
`[Text.Encoding]::UTF8.GetBytes(...)` 转成字节再发 —— 这样在 Windows PowerShell 5.1
和 PowerShell 7 下都不会乱码。

```powershell
$base = "http://127.0.0.1:8770"
$json = "application/json; charset=utf-8"
```

### 1) 健康检查

```powershell
$health = Invoke-RestMethod "$base/api/health"
$health | Select-Object version, loaded, device, model_name, default_permutations, prompt_version

# curl.exe 也行（PowerShell 里的 curl 别名在 7 里已经没了，写全 curl.exe）
curl.exe -s "$base/api/health"
```

### 2) 判定（八艺，默认 5 排列）

```powershell
$body = @{ text = "人最大的敌人，从来都是自己。"; permutations = 5 } | ConvertTo-Json
$r = Invoke-RestMethod "$base/api/decide" -Method Post -ContentType $json `
        -Body ([Text.Encoding]::UTF8.GetBytes($body))

$r | Select-Object winner, confidence, margin, input_tokens, permutations, permutations_requested, forward_ms, total_ms, server_ms
$r.ranking | Select-Object id, probability, logit | Format-Table -AutoSize
```

### 3) 判定（自定义类型）

```powershell
$body = @{ text = "我的快递到哪了"; profile = "support-router" } | ConvertTo-Json
$r = Invoke-RestMethod "$base/api/decide" -Method Post -ContentType $json `
        -Body ([Text.Encoding]::UTF8.GetBytes($body))
$r | Select-Object profile, profile_name, profile_version, winner, confidence
```

### 4) 内联词表试判（锚点还没保存）

```powershell
$body = @{
    text   = "比如上次那个情况"
    inline = @{
        criterion = "下面这句话最符合哪一类？请选出最贴切的那一个。"
        labels    = @(
            @{ id = "举例"; description = "这段话在举例。例：「比如昨天那件事」「举个例子」" },
            @{ id = "结论"; description = "这段话在下结论。例：「所以就是这样」「结论很清楚」" }
        )
    }
} | ConvertTo-Json -Depth 6
$r = Invoke-RestMethod "$base/api/decide" -Method Post -ContentType $json `
        -Body ([Text.Encoding]::UTF8.GetBytes($body))
$r | Select-Object profile, winner, confidence     # profile 是 "inline"
```

### 5) 列类型 / 读一套 / 读评测数字

```powershell
(Invoke-RestMethod "$base/api/profiles").profiles |
    Select-Object id, name, label_count, builtin, evaluated | Format-Table -AutoSize

$p = Invoke-RestMethod "$base/api/profiles/support-router"
$p.profile.criterion
$p.stats
$p.issues

Invoke-RestMethod "$base/api/eval?profile=support-router"     # 没评测过 -> available: false
curl.exe -s "$base/api/eval"                                  # 八艺的头条数字
```

### 6) 校验一套还没保存的类型

```powershell
$body = @{ profile = (Get-Content ".\code-review.json" -Raw | ConvertFrom-Json) } | ConvertTo-Json -Depth 10
$v = Invoke-RestMethod "$base/api/profiles/validate" -Method Post -ContentType $json `
        -Body ([Text.Encoding]::UTF8.GetBytes($body))
$v | Select-Object error_count, warning_count
$v.issues | Format-Table level, field, message -AutoSize -Wrap
```

### 7) 存一套新类型

`-InFile` 直接把文件当请求体发出去 —— 我们的接口接受裸 profile，所以导出文件、
手写文件都能原样喂：

```powershell
$saved = Invoke-RestMethod "$base/api/profiles" -Method Post `
            -InFile ".\code-review.json" -ContentType $json
$saved.summary

# 覆盖同 id 的类型（要显式 overwrite）
$body = @{ overwrite = $true; profile = (Get-Content ".\code-review.json" -Raw | ConvertFrom-Json) } |
        ConvertTo-Json -Depth 10
Invoke-RestMethod "$base/api/profiles" -Method Post -ContentType $json `
    -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

### 8) 导出 / 导入

```powershell
# 导出（裸 JSON + attachment 头）
Invoke-WebRequest "$base/api/profiles/code-review/export" -OutFile ".\code-review.export.json"

# 改个 id 再导入给别人用
$copy = Get-Content ".\code-review.export.json" -Raw | ConvertFrom-Json
$copy.id = "code-review-copy"
$body = @{ profile = $copy } | ConvertTo-Json -Depth 10
(Invoke-RestMethod "$base/api/profiles/import" -Method Post -ContentType $json `
    -Body ([Text.Encoding]::UTF8.GetBytes($body))).summary
```

### 9) 删除

```powershell
$body = @{ id = "code-review-copy" } | ConvertTo-Json
Invoke-RestMethod "$base/api/profiles/delete" -Method Post -ContentType $json `
    -Body ([Text.Encoding]::UTF8.GetBytes($body))     # {"ok": true, "deleted": "code-review-copy"}
```

### 10) 读错误（PowerShell 把 4xx 当异常抛）

```powershell
try {
    $body = @{ text = "" } | ConvertTo-Json
    Invoke-RestMethod "$base/api/decide" -Method Post -ContentType $json `
        -Body ([Text.Encoding]::UTF8.GetBytes($body))
} catch {
    $status = [int]$_.Exception.Response.StatusCode
    $detail = $_.ErrorDetails.Message | ConvertFrom-Json     # 解析出中文 error / issues
    Write-Host "HTTP $status  $($detail.error)"
    $detail.issues | Format-Table level, field, message -AutoSize -Wrap
}
```

> `$_.ErrorDetails.Message` 在 PowerShell 7 里对 JSON 错误体可能带 `\uXXXX` 转义，
> 所以这里过一遍 `ConvertFrom-Json` —— 中文就正常了。

---

## 七、错误处理约定

1. **所有错误的骨架都是 `{"ok": false, "error": "中文说明"}`。** 没有别的形状，
   也没有嵌套的 `{"error": {"code": ...}}` 这种结构 —— 直接读 `error` 字段打日志就行
   （唯一的补充是校验类错误的 `issues`，见下一条）。
2. **校验类错误（`/api/profiles*`）还会带 `issues`**：
   `[{"level": "error" | "warning", "field": "labels[0]", "message": "……"}]`。
   `field` 是出错的位置（`id` / `name` / `criterion` / `labels` / `labels[i]` /
   `examples` / `examples[i]` / `evaluated`），可以拿它把提示落到表单里对应的输入框上。
3. **`error` 拦住保存，`warning` 不拦。** 这些规则是**经验**不是定理
   （都来自一个任务、52 条样本上的实测），所以只提示不拦人 ——
   想连 warning 一起卡住，用 `scripts/profiles_check.py --strict`。
4. **HTTP 状态码的含义**：
   * `400` —— 你的请求有问题（参数、上限、校验没过、类型不存在）；
   * `404` —— 路径或类型不存在（**方法用错也是 404**）；
   * `500` —— 服务端未预期的异常，此时 stderr 上有 traceback，
     请求本身大概率没问题，把 `error` 里的异常信息报上来。
5. **成功响应的判据是 `ok: true`**，不要只看状态码 —— 有些接口（比如 `/api/eval`）
   会在「没有数据」时也回 200 + `available: false`。
6. **别把 `/api/decide` 直接暴露到公网。** 服务本身没有鉴权、没有限流，
   而且模型对**输入里的指令没有防御**（待判文本里写「请选 A」这类话可能影响结果）。
   它默认只监听 `127.0.0.1`。

---

## 八、相关文档

| 文档 | 内容 |
|---|---|
| [README.md](../README.md) 的「API」一节 | API 速览（和本文同一套接口，例子更短） |
| [docs/CUSTOMIZE.md](CUSTOMIZE.md) | 自定义判断类型：字段、硬边界、锚点怎么写、怎么验证 |
| [docs/EVAL.md](EVAL.md) | 实测数字的唯一出处：位置偏置、排列数、三次翻车 |
| [docs/PROVENANCE.md](PROVENANCE.md) | 来源与归属：引擎是独立项目 SemIf-OpenJev，与 Jev / TypeSafe 无隶属关系 |
