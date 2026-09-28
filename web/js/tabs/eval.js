/* 评测页：这套判断类型的成绩是从哪来的、怎么自己量一遍。
 *
 * 这一页刻意做得很「啰嗦」：这个项目最容易翻的车不是判不准，而是**数字来源不清**。
 * 页面曾经硬编码「干净测试集 24 条实测 96%」，测试集换成 52 条之后没人记得改，
 * 一个作废的数字在首页挂了很久（见 docs/EVAL.md 第六节）。所以这里把
 * 「数字 → 文件 → 命令」整条链子摊开给人看。
 */

import { api } from "../api.js";
import { $, el, esc, pct } from "../util.js";
import { on, state } from "../state.js";

const DATASET_NOTES = {
  eval_clean: "干净集 —— 和锚点例句无字面重合，<b>判断泛化能力只看这套</b>。",
  eval_overlap: "对照集 —— 装着已知和锚点撞过车的句子，数字不代表泛化能力。",
};

function renderSummary(evalPayload) {
  const box = $("eval-summary");
  box.innerHTML = "";
  const profile = state.profile;

  if (!evalPayload?.available) {
    box.append(el("div", { class: "hint" }));
    box.lastChild.innerHTML = `
      <p style="margin:0 0 10px">
        <b>这套类型没有评测数字。</b>没有数字不等于不好用 —— 只是还没人拿干净测试集量过它。
        页面顶部那个成绩是内置「八艺」那一套的，<b>不能</b>算在它头上。
      </p>
      <p style="margin:0">
        自己量一遍：准备一份<b>标准答案正确、且句子不和锚点重合</b>的测试集（JSONL，
        每行 <code>{"id","text","label"}</code>，<code>label</code> 用这套类型自己的选项 id），然后跑
        <code>python scripts/evaluate.py --profile ${esc(profile?.id || "")} --data &lt;你的测试集&gt; --write-result</code>。
      </p>`;
    return;
  }

  const ci = evalPayload.ci95
    ? `${pct(evalPayload.ci95[0])} ~ ${pct(evalPayload.ci95[1])}`
    : "—";
  box.append(el("div", { class: "verdict" }, [
    el("div", { class: "big", style: "font-size:30px", text: pct(evalPayload.accuracy, 1) }),
    el("div", { class: "meta" }, [
      el("div", { class: "conf", text: `${evalPayload.correct} / ${evalPayload.total} 条判对` }),
      el("div", { class: "hint", text: `95% 置信区间 ${ci}` }),
    ]),
  ]));
  box.append(el("dl", { class: "kv" }, [
    el("dt", { text: "测试集" }), el("dd", { text: evalPayload.dataset || "—" }),
    el("dt", { text: "排列数" }), el("dd", { text: String(evalPayload.permutations) }),
    el("dt", { text: "端到端中位" }), el("dd", { text: evalPayload.median_ms ? `${Math.round(evalPayload.median_ms)} ms` : "—" }),
    el("dt", { text: "锚点版本" }), el("dd", { text: evalPayload.profile_version || profile?.version || "—" }),
  ]));
  box.append(el("div", { class: "hint", style: "margin-top:10px" }));
  box.lastChild.innerHTML = `
    <b>看区间，别只看点估计。</b>几十条样本上的百分比，一两条的差距在置信区间里就是噪声 ——
    实测三档速度（3/5/7 排列）的区间大面积重叠，所以「快档更准」这种说法在本项目里是不成立的。
    概率本身也未校准，只能当排序看。`;

  if (evalPayload.per_label) {
    box.append(el("h2", { style: "margin-top:18px", text: "分选项成绩" }));
    const table = el("table", { class: "grid" }, [
      el("tr", {}, [
        el("th", { text: "选项" }),
        el("th", { class: "num", text: "判对 / 总数" }),
        el("th", { class: "num", text: "比例" }),
      ]),
    ]);
    for (const [labelId, counts] of Object.entries(evalPayload.per_label)) {
      const rate = counts.total ? counts.correct / counts.total : 0;
      table.append(el("tr", { class: rate < 0.6 ? "top" : "" }, [
        el("td", { text: labelId }),
        el("td", { class: "num", text: `${counts.correct} / ${counts.total}` }),
        el("td", { class: "num", text: counts.total ? pct(rate, 0) : "—" }),
      ]));
    }
    box.append(table);
    box.append(el("div", { class: "hint", style: "margin-top:8px" }));
    box.lastChild.innerHTML =
      "高亮的是判对率低于六成的选项 —— 那是这套锚点最薄弱的边界，" +
      "但样本只有几条，别把它当成结论，当成「下一轮该补哪儿」的线索。";
  }
}

function renderHow() {
  const box = $("eval-how");
  box.innerHTML = "";
  const profileId = state.profile?.id || "bayi";
  const lines = [
    ["1. 先确认测试集没抄锚点", "python scripts/leak_check.py"],
    ["2. 批量校验所有判断类型", "python scripts/profiles_check.py"],
    ["3. 在干净集上量一遍", `python scripts/evaluate.py --profile ${profileId} --perms 3,5,7`],
    ["4. 把头条数字落盘（页面从这里读）", `python scripts/evaluate.py --profile ${profileId} --perms 5 --write-result`],
    ["5. 改完锚点做消融：只改一处，比准确率", "python scripts/anchor_tune.py"],
  ];
  for (const [title, command] of lines) {
    box.append(el("div", { style: "margin-bottom:10px" }, [
      el("div", { class: "hint", text: title }),
      el("pre", { class: "code", style: "margin-top:4px", text: command }),
    ]));
  }
  box.append(el("div", { class: "hint" }));
  box.lastChild.innerHTML =
    "第 3 步要 GPU，几十秒到几分钟。第 1、2 步不占显存、秒回 —— <b>改完锚点先跑这两个</b>。";
}

function renderChain(evalPayload) {
  const profileId = state.profile?.id || "bayi";
  const source = profileId === "bayi" ? "data/eval_result.json" : `data/eval_results/${profileId}.json`;
  $("eval-chain").textContent =
    `scripts/evaluate.py --write-result\n` +
    `        └─ ${source}\n` +
    `              └─ GET /api/eval?profile=${profileId}\n` +
    `                    └─ 页面上的每个准确率数字\n\n` +
    (evalPayload?.available
      ? `当前读到：${evalPayload.correct}/${evalPayload.total} = ${pct(evalPayload.accuracy)}`
      : "当前读到：这个文件还不存在（available: false）");
}

async function renderDatasets() {
  const box = $("eval-datasets");
  try {
    const payload = await api.datasets();
    // 清空放在 await **之后**：`refresh()` 会被 profile-id 和 profile 两个事件
    // 各触发一次，两次并发时如果在 await 前清空，就会画出两张表。
    box.innerHTML = "";
    const table = el("table", { class: "grid" }, [
      el("tr", {}, [
        el("th", { text: "数据集" }),
        el("th", { class: "num", text: "条数" }),
        el("th", { text: "说明" }),
      ]),
    ]);
    for (const dataset of payload.datasets) {
      table.append(el("tr", {}, [
        el("td", {}, [el("code", { text: dataset.path })]),
        el("td", { class: "num", text: dataset.exists ? String(dataset.rows) : "缺失" }),
        el("td", { html: DATASET_NOTES[dataset.name] || dataset.note || "" }),
      ]));
    }
    box.append(table);
  } catch (error) {
    box.innerHTML = "";
    box.append(el("div", { class: "hint", text: "拿不到数据集清单：" + error.message }));
  }
}

/** 并发保护：`profile-id` 和 `profile` 两个事件会各触发一次 refresh，
 *  用一个自增的令牌让「旧的那次」自己退出，免得画出两份内容。 */
let generation = 0;

export async function refresh() {
  const token = ++generation;
  $("eval-profile-tag").textContent = state.profile ? state.profile.name : "";
  renderHow();
  await renderDatasets();
  if (token !== generation) return;
  try {
    const payload = await api.eval(state.profileId);
    if (token !== generation) return;
    renderSummary(payload);
    renderChain(payload);
  } catch (error) {
    $("eval-summary").innerHTML = "";
    $("eval-summary").append(el("div", { class: "hint", text: "拿不到评测数据：" + error.message }));
  }
}

export function init() {
  on("profile-id", refresh);
  on("profile", refresh);
}
