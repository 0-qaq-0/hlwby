# 来源与归属（Provenance）

这份文档回答一个问题：**这个项目里，哪些东西是别人做的，哪些是自己做的。**

它存在的理由很直接 —— 本项目一度在 README 和代码注释里把自己用的引擎写成
「Jev 的开源版」。那是错的。一份把来源写清楚的文档，比一句口头承诺管用。

---

## 1. 三个名字，别混

| 名字 | 是什么 | 谁做的 | 本项目的角色 |
|---|---|---|---|
| **Jev** | TypeSafe 的**闭源托管服务**，做「运行时可定义的语义判定」。没有可下载的模型 | TypeSafe AI | 本项目用的是它**公开描述过的接口形态**，不是它的代码或权重 |
| **SemIf**（原名 **OpenJev**） | **独立**开源项目，用开放模型复现上面那个**接口形态** | [TheoLeeCJ](https://github.com/TheoLeeCJ) | 本项目**直接用它的判定机制**（原样引用，未修改） |
| **Qwen3.5-2B** | 通用基座模型 | 阿里通义千问团队 | 本项目**用它当底座**，判定靠 prompt 而不是微调 |

### 上游自己怎么说的

`vendor/SemIf-OpenJev/README.md` 的原话，这段是唯一依据：

> **Independent project; not affiliated with Jev or TypeSafe.**
>
> Jev is TypeSafe's closed service for runtime-defined semantic decisions.
> This project reproduces that **interface pattern** with open models;
> **it does not reproduce Jev's undisclosed model or training.**

翻成一句话：**SemIf 复现的是「接口形态」，不是 Jev 本身，也不含 Jev 未公开的模型与训练。**

所以下面这些说法都是错的，别用：

| ❌ 错的说法 | 为什么错 |
|---|---|
| 「Jev 的开源版」/「Jev 模型开源版」 | SemIf 不是 Jev 发布的任何东西，两者没有隶属关系 |
| 「Jev 模型」 | Jev 是服务，不是模型；没有可下载的权重 |
| 「Jev 官方开源实现」 | 官方没有开源实现 |
| 「我们复现了 Jev」 | 复现的是接口形态，不是它的模型或训练 |

✅ 能说的：

> 本项目用的是**独立开源项目 SemIf-OpenJev** 的判定机制（复现 Jev 公开描述过的
> 「决策模型」接口形态），基座是 **Qwen3.5-2B**。与 Jev / TypeSafe AI **无隶属关系**。

---

## 2. 引擎的确切版本

| | |
|---|---|
| 仓库 | <https://github.com/TheoLeeCJ/SemIf-OpenJev> |
| commit | `23cf1f39fc9534fe81437200959b6dfc7106e45a` |
| commit 日期 | 2026-09-24 |
| commit 标题 | `Add explicit Torch CPU scoring` |
| 许可 | MIT（`vendor/SemIf-OpenJev/LICENSE`） |
| 位置 | `vendor/SemIf-OpenJev/`，**整棵树入库** |

**上游代码一个字都没改。** 校验方式：

```powershell
git -C vendor\SemIf-OpenJev status --short   # 应为空
git -C vendor\SemIf-OpenJev rev-parse HEAD  # 应等于上面那个 commit
```

> 为什么整棵树入库而不是按需克隆：README 承诺「离线可跑」。
> 想换成按需克隆，跑 `scripts\setup_vendor.ps1`（它会 checkout 到同一个 commit），
> 再把 `.gitignore` 里的 `# vendor/` 取消注释。
>
> **注意**：`vendor/SemIf-OpenJev/.git` 是上游仓库自己的 git 目录，
> 上传到本项目仓库前要删掉，否则 Git 会把它记成一个坏的 submodule（gitlink）。

### 本项目在哪几个地方包了它

上游代码不动，本项目在**外面**包了四层（都在 `jev_meme/engine.py`）：

1. 中文 system prompt（上游是英文，payload 结构完全一致）；
2. 把选项槽位的概率映射回八个汉字；
3. 多种选项排列取平均（修位置偏置，见 `docs/EVAL.md` 第 5 节）；
4. 按 prompt 长度自适应降档（`TOKEN_BUDGET`）。

---

## 3. 基座模型

| | |
|---|---|
| 模型 | `Qwen/Qwen3.5-2B` |
| 许可 | Apache-2.0 |
| revision | `15852e8c16360a2fea060d615a32b45270f8a8fc` |
| 体积 | 4.26 GB（本地实测） |
| 位置 | `models/Qwen3.5-2B/`，**不入库**（用 `scripts/download_model.py` 拉） |

权重不随本项目分发，只记录 revision。`jev_meme/engine.py` 的 `MODEL_CHOICES`
里还有 `qwen3-0.6b` 和 `qwen3.5-4b` 两个备选，各自带 revision。

---

## 4. 本项目的原创部分

* `jev_meme/labels.py` —— 八个字的锚点描述（**这套系统的全部「训练」**，纯运行时数据）
* `jev_meme/engine.py` 里的四层包装（见上）
* `jev_meme/server.py` —— 标准库 HTTP 服务
* `web/index.html` —— 判定页面
* `data/*.jsonl` —— 测试集（自己标的，见 `docs/EVAL.md` 第 10 节的局限说明）
* `scripts/*` —— 评测、泄漏检查、偏置诊断、实验脚本

「八艺」这套说法来自网络社区，本项目只是把它做成了**可判定的标签集**。

---

## 5. 名称与商标

「Jev」「TypeSafe」及其他名称和标记归其各自所有者。本项目与 TypeSafe AI、
SemIf 作者**均无隶属关系**，也未获得其背书。

---

## 6. 许可

* 本项目：**MIT**，见 [`LICENSE`](../LICENSE)
* 上游引擎：MIT，见 `vendor/SemIf-OpenJev/LICENSE`（随树分发）
* 基座模型：Apache-2.0，权重不随本项目分发
