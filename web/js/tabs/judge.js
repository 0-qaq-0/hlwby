/* 判定页：粘一条评论，拿到每个选项的概率分布。
 *
 * 页面上所有百分比都是**未校准的条件概率**（上游措辞：
 * `conditional option score; uncalibrated as decision confidence`），
 * 所以文案里一律说「分布 / 排序」，不说「模型有多确定」。
 */

import { api } from "../api.js";
import { $, clamp, copyText, download, el, esc, pct, toast, toCSV } from "../util.js";
import { clearHistory, on, pushHistory, saveSettings, state } from "../state.js";

let busy = false;
let lastResult = null;

export function currentPermutations() {
  return Number(state.settings.permutations) || 5;
}

/* ------------------------------------------------------------------ 渲染 */

function renderEmptyBars(labels) {
  $("bars").innerHTML = "";
  for (const label of labels) {
    $("bars").append(
      el("div", { class: "bar", dataset: { id: label.id } }, [
        el("div", { class: "ch", text: label.id, title: label.id }),
        el("div", { class: "track" }, [el("div", { class: "fill" })]),
        el("div", { class: "pct", text: "—" }),
      ]),
    );
  }
}

function renderExamples(profile) {
  const box = $("chips");
  box.innerHTML = "";
  for (const example of profile.examples || []) {
    box.append(
      el("button", {
        class: "chip",
        title: example.text,
        html: `<span class="k">${esc(example.label)}</span>${esc(example.text.slice(0, 18))}${example.text.length > 18 ? "…" : ""}`,
        onclick: () => {
          $("text").value = example.text;
          updateCharCount();
          run();
        },
      }),
    );
  }
  if (!profile.examples?.length) {
    box.append(el("span", { class: "hint", text: "这套类型还没配页面示例。" }));
  }
}

function renderResult(result) {
  const ranking = result.ranking || [];
  const top = ranking[0];
  if (!top) return;
  const max = Math.max(...ranking.map((row) => row.probability), 0.0001);
  const byId = Object.fromEntries(ranking.map((row) => [row.id, row]));

  const big = $("big");
  big.textContent = top.id;
  big.style.background = (top.accent || "#6ea8fe") + "26";
  big.style.borderColor = top.accent || "#6ea8fe";
  big.style.color = top.accent || "#6ea8fe";

  $("conf").textContent = `${pct(top.probability)} ${top.id}`;
  $("conf").style.color = top.accent || "#6ea8fe";
  $("hint").textContent = top.hint || "（这套类型没写人话提示）";

  for (const node of $("bars").children) {
    const id = node.dataset.id;
    const row = byId[id];
    const probability = row ? row.probability : 0;
    node.classList.toggle("top", id === top.id);
    const fill = node.querySelector(".fill");
    // 概率条按「相对最大值」画：八艺上第一名常常只有 30%，
    // 按绝对值画的话整排都是短的，看不出形状。
    fill.style.width = clamp((probability / max) * 100, probability > 0 ? 2 : 0, 100) + "%";
    fill.style.background = (row?.accent) || "var(--muted)";
    node.querySelector(".pct").textContent = pct(probability);
  }

  const perms = result.permutations || 1;
  const asked = result.permutations_requested || perms;
  const mode = perms > 1
    ? `${perms} 种选项排列取平均`
    : (asked > 1 ? "输入较长，已自动降为单次前向" : "单次前向（有位置噪声）");
  $("stats").innerHTML =
    `<b>${result.forward_ms}</b> ms 推理 · <b>${result.total_ms}</b> ms 端到端` +
    (result.input_tokens ? ` · <b>${result.input_tokens}</b> token` : "") +
    ` · 领先 <b>${(result.margin * 100).toFixed(1)}</b> 个点 · ${mode}`;
  $("result-profile").textContent = result.profile_name ? `类型：${result.profile_name}` : "";
}

function renderHistory() {
  const box = $("history");
  box.innerHTML = "";
  $("history-count").textContent = state.history.length ? `${state.history.length} 条` : "";
  if (!state.history.length) {
    box.append(el("div", { class: "empty", text: "还没有判定过。判定结果会存在浏览器本地。" }));
    return;
  }
  for (const item of state.history) {
    box.append(
      el("div", {
        class: "item",
        title: item.text,
        onclick: () => {
          $("text").value = item.text;
          updateCharCount();
          run();
        },
      }, [
        el("span", { class: "badge", style: `color:${item.accent || "inherit"}`, text: item.winner }),
        el("div", { class: "grow" }, [
          el("div", { class: "name", text: item.text.slice(0, 40) + (item.text.length > 40 ? "…" : "") }),
          el("div", { class: "sub", text: `${pct(item.confidence)} · ${item.profile_name || ""} · ${item.ms ?? "?"} ms` }),
        ]),
      ]),
    );
  }
}

function setStatus(message, isError = false, spinning = false) {
  const node = $("status");
  node.className = "status" + (isError ? " err" : "");
  node.innerHTML = (spinning ? '<span class="spin"></span>' : "") + esc(message);
}

function updateCharCount() {
  const length = $("text").value.trim().length;
  $("charcount").textContent = length ? `${length} 字` : "";
}

/* ------------------------------------------------------------------ 动作 */

export async function run() {
  const text = $("text").value.trim();
  if (!text) {
    setStatus("先输入一段文本", true);
    return;
  }
  if (busy) return;
  busy = true;
  $("go").disabled = true;
  setStatus("判定中…", false, true);

  const profileName = state.profile?.name || state.profileId;
  try {
    const result = await api.decide({
      text,
      permutations: currentPermutations(),
      profile: state.profileId,
    });
    lastResult = result;
    renderResult(result);
    setStatus(`就绪 · ${result.device || ""}`);
    const top = result.ranking[0];
    pushHistory({
      text,
      winner: top.id,
      accent: top.accent,
      confidence: top.probability,
      ms: result.total_ms,
      profile: state.profileId,
      profile_name: result.profile_name || profileName,
      at: new Date().toISOString(),
    });
  } catch (error) {
    setStatus("失败：" + error.message, true);
  } finally {
    busy = false;
    $("go").disabled = false;
  }
}

/* -------------------------------------------------------------- 批量模式 */

function renderBatch() {
  const box = $("batch-results");
  box.innerHTML = "";
  if (!state.batch.length) return;
  const header = ["#", "文本", "判定", "概率"];
  const table = el("table", { class: "grid" }, [
    el("tr", {}, header.map((name) => el("th", { text: name }))),
  ]);
  state.batch.forEach((row, index) => {
    table.append(
      el("tr", {}, [
        el("td", { class: "num", text: String(index + 1) }),
        el("td", { text: row.text.slice(0, 46) + (row.text.length > 46 ? "…" : ""), title: row.text }),
        el("td", {}, [
          row.ok
            ? el("span", { class: "badge", style: `color:${row.accent || "inherit"}`, text: row.winner })
            : el("span", { class: "badge bad", text: "失败" }),
        ]),
        el("td", { class: "num", text: row.ok ? pct(row.confidence) : (row.error || "") }),
      ]),
    );
  });
  box.append(table);
}

async function runBatch() {
  const lines = $("batch-input").value.split("\n").map((line) => line.trim()).filter(Boolean);
  if (!lines.length) {
    $("batch-state").textContent = "先输入几行文本";
    return;
  }
  $("batch-run").disabled = true;
  state.batch = [];
  const started = performance.now();
  for (const [index, text] of lines.entries()) {
    $("batch-state").textContent = `判定中 ${index + 1}/${lines.length}…`;
    try {
      const result = await api.decide({
        text,
        permutations: currentPermutations(),
        profile: state.profileId,
      });
      const top = result.ranking[0];
      state.batch.push({
        text, ok: true, winner: top.id, accent: top.accent,
        confidence: top.probability, margin: result.margin, ms: result.total_ms,
      });
    } catch (error) {
      state.batch.push({ text, ok: false, error: error.message });
    }
    renderBatch();
  }
  const seconds = ((performance.now() - started) / 1000).toFixed(1);
  $("batch-state").textContent = `完成 ${state.batch.length} 条，用时 ${seconds}s`;
  $("batch-run").disabled = false;
}

function exportBatch(kind) {
  if (!state.batch.length) {
    toast("还没有批量结果", "warn");
    return;
  }
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  if (kind === "csv") {
    const rows = [["文本", "判定", "概率", "领先", "毫秒", "错误"]];
    for (const row of state.batch) {
      rows.push(row.ok
        ? [row.text, row.winner, row.confidence.toFixed(4), row.margin.toFixed(4), row.ms, ""]
        : [row.text, "", "", "", "", row.error]);
    }
    download(`bayi-batch-${stamp}.csv`, toCSV(rows), "text/csv;charset=utf-8");
  } else {
    download(`bayi-batch-${stamp}.json`,
      JSON.stringify({ profile: state.profileId, results: state.batch }, null, 2));
  }
}

/* ------------------------------------------------------------------ 装配 */

export function init() {
  renderEmptyBars(state.profile?.labels || []);
  updateCharCount();
  renderHistory();

  $("text").addEventListener("input", updateCharCount);
  $("text").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      run();
    }
  });
  $("go").addEventListener("click", run);
  $("clear-btn").addEventListener("click", () => {
    $("text").value = "";
    updateCharCount();
    setStatus("就绪");
  });

  $("speeds").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-perms]");
    if (!button) return;
    // 档位是**一个**设置，判定页和设置页改的是同一个值 —— 否则会出现
    // 「按钮亮着『更稳』，实际按 5 排列在跑」这种看不出来的错。
    saveSettings({ permutations: Number(button.dataset.perms) });
    if ($("text").value.trim()) run();
  });
  markSpeed(currentPermutations());

  $("copy-btn").addEventListener("click", async () => {
    if (!lastResult) { toast("还没有判定结果", "warn"); return; }
    const ranking = lastResult.ranking
      .map((row) => `${row.id} ${pct(row.probability)}`).join("  ");
    const top = lastResult.ranking[0];
    const ok = await copyText(`${top.id}（${pct(top.probability)}）\n${ranking}`);
    toast(ok ? "结果已复制" : "复制失败，手动选吧", ok ? "ok" : "err");
  });

  $("batch-toggle").addEventListener("change", (event) => {
    $("batch-panel").style.display = event.target.checked ? "" : "none";
  });

  // 分享链接：把文本和类型塞进 query，对方打开就能看到同一次判定。
  // `auto=1` 让页面自己跑一遍 —— 截图、发群里都靠它。
  $("share-btn").addEventListener("click", async () => {
    const text = $("text").value.trim();
    if (!text) { toast("先输入一段文本", "warn"); return; }
    const url = new URL(location.origin + "/");
    url.searchParams.set("t", text);
    url.searchParams.set("profile", state.profileId);
    url.searchParams.set("auto", "1");
    url.hash = "judge";
    const ok = await copyText(url.toString());
    toast(ok ? "分享链接已复制" : "复制失败，手动复制地址栏吧", ok ? "ok" : "err");
  });
  $("batch-run").addEventListener("click", runBatch);
  $("batch-csv").addEventListener("click", () => exportBatch("csv"));
  $("batch-json").addEventListener("click", () => exportBatch("json"));

  $("history-clear").addEventListener("click", () => {
    clearHistory();
    toast("本地历史已清空", "ok");
  });

  on("profile", (profile) => {
    state.profile = profile;
    renderEmptyBars(profile.labels || []);
    renderExamples(profile);
    $("judge-profile-note").textContent = profile.evaluated ? "已评测" : "未评测";
    setStatus("就绪");
  });
  on("history", renderHistory);
  on("settings", (settings) => markSpeed(Number(settings.permutations) || 5));
}

function markSpeed(perms) {
  for (const button of $("speeds").children) {
    button.classList.toggle("on", Number(button.dataset.perms) === perms);
  }
}
