/* 词表页：判断类型的增删改查。
 *
 * 这一页是「高度可自定义」的落点 —— 选项、锚点描述、判定问法、页面示例
 * 全部可改，改完**不用重启服务**（锚点是推理时才读进去的）。
 *
 * 两个设计决定：
 *   1. 编辑器改的是 `state.draft`，不是 `state.profile`。这样才能「改了不保存
 *      也能试判」，也才能在离开时提醒「有未保存的改动」。
 *   2. 校验走服务端的 `/api/profiles/validate`，**不在前端重写一套规则** ——
 *      规则只有一份，页面和命令行 `scripts/profiles_check.py` 报的才是同一件事。
 */

import { api } from "../api.js";
import { $, confirmDialog, debounce, download, el, esc, pct, toast } from "../util.js";
import { emit, on, setProfileId, state } from "../state.js";

const ACCENTS = ["#c2410c", "#b91c1c", "#dc2626", "#ca8a04", "#7c3aed", "#be185d", "#15803d", "#0f766e", "#2563eb", "#6ea8fe"];

let dirty = false;
let issues = [];

/* ------------------------------------------------------------------ 列表 */

function renderProfileList() {
  const box = $("profile-list");
  box.innerHTML = "";
  $("profiles-count").textContent = `${state.profiles.length} 套`;
  $("tab-labels-count").textContent = String(state.profiles.length);

  for (const summary of state.profiles) {
    const badges = [
      summary.builtin ? el("span", { class: "badge", text: "内置" }) : el("span", { class: "badge", text: "我的" }),
      summary.evaluated
        ? el("span", { class: "badge good", text: "已评测" })
        : el("span", { class: "badge warn", text: "未评测" }),
    ];
    const item = el("div", {
      class: "item" + (summary.id === state.profileId ? " on" : ""),
      onclick: () => selectProfile(summary.id),
    }, [
      el("div", { class: "grow" }, [
        el("div", { class: "name", text: summary.name }),
        el("div", { class: "sub", text: `${summary.id} · ${summary.label_ids.join(" ")}` }),
      ]),
      ...badges,
    ]);
    if (!summary.builtin) {
      item.append(el("div", { class: "acts" }, [
        el("button", {
          class: "btn sm danger", text: "删", title: "删除这套类型",
          onclick: async (event) => {
            event.stopPropagation();
            const ok = await confirmDialog("删除判断类型",
              `确定删掉「${esc(summary.name)}」？<br>文件 <code>data/profiles/${esc(summary.id)}.json</code> 会被删除，不能撤销。`);
            if (!ok) return;
            try {
              await api.profileDelete(summary.id);
              toast(`已删除「${summary.name}」`, "ok");
              await refreshProfiles();
              if (state.profileId === summary.id) await selectProfile("bayi");
            } catch (error) {
              toast("删除失败：" + error.message, "err");
            }
          },
        }),
      ]));
    }
    box.append(item);
  }
}

async function refreshProfiles() {
  const payload = await api.profiles();
  state.profiles = payload.profiles;
  emit("profiles", state.profiles);
  renderProfileList();
}

/* ------------------------------------------------------------------ 载入 */

export async function selectProfile(profileId) {
  try {
    const payload = await api.profile(profileId);
    state.profile = payload.profile;
    state.draft = structuredClone(payload.profile);
    issues = payload.issues || [];
    dirty = false;
    setProfileId(profileId);
    fillForm();
    renderProfileList();
    renderEditorEval(payload.eval);
    emit("profile", state.profile);
  } catch (error) {
    toast("载入失败：" + error.message, "err");
  }
}

function fillForm() {
  const draft = state.draft;
  const readOnly = Boolean(draft.builtin);
  $("ed-id").value = draft.id;
  $("ed-name").value = draft.name;
  $("ed-summary").value = draft.summary || "";
  $("ed-criterion").value = draft.criterion || "";
  $("ed-version").value = draft.version || "";
  $("ed-note").value = draft.note || "";
  $("ed-id").disabled = true; // id 是文件名，存下来就不能改
  for (const id of ["ed-name", "ed-summary", "ed-criterion", "ed-version", "ed-note"]) {
    $(id).disabled = readOnly;
  }
  $("ed-badge").textContent = readOnly ? "内置 · 只读" : "我的类型";
  $("ed-save").disabled = readOnly;
  $("ed-delete").disabled = readOnly;
  $("ed-add-label").disabled = readOnly;
  $("ed-add-example").disabled = readOnly;
  $("ed-state").textContent = readOnly ? "内置类型只读，想改就「另存为副本」" : "已载入";
  renderLabels();
  renderExamples();
  renderPayload();
  renderIssues();
  renderStats();
}

function collect() {
  const draft = state.draft;
  draft.name = $("ed-name").value.trim();
  draft.summary = $("ed-summary").value.trim();
  draft.criterion = $("ed-criterion").value.trim();
  draft.version = $("ed-version").value.trim();
  draft.note = $("ed-note").value.trim();
  return draft;
}

/* -------------------------------------------------------------- 选项编辑 */

function renderLabels() {
  const box = $("ed-labels");
  box.innerHTML = "";
  const readOnly = Boolean(state.draft.builtin);
  const labels = state.draft.labels || [];
  $("ed-label-count").textContent = `${labels.length} / 16`;

  labels.forEach((label, index) => {
    const row = el("div", { class: "label-row" });
    row.append(
      el("div", { class: "head" }, [
        el("input", {
          class: "idbox", type: "text", value: label.id, placeholder: "典",
          disabled: readOnly, title: "选项 id（显示在概率条左边）",
          oninput: (event) => { label.id = event.target.value; onDraftChanged(); },
        }),
        el("input", {
          type: "text", value: label.pinyin || "", placeholder: "拼音（可空）",
          disabled: readOnly, style: "width:110px",
          oninput: (event) => { label.pinyin = event.target.value; },
        }),
        el("input", {
          type: "color", class: "color", value: label.accent || ACCENTS[index % ACCENTS.length],
          disabled: readOnly, title: "配色",
          oninput: (event) => { label.accent = event.target.value; },
        }),
        el("span", { class: "spacer", style: "flex:1" }),
        el("button", {
          class: "btn icon", text: "↑", title: "上移", disabled: readOnly || index === 0,
          onclick: () => move(labels, index, index - 1),
        }),
        el("button", {
          class: "btn icon", text: "↓", title: "下移", disabled: readOnly || index === labels.length - 1,
          onclick: () => move(labels, index, index + 1),
        }),
        el("button", {
          class: "btn icon danger", text: "×", title: "删掉这一项",
          disabled: readOnly || labels.length <= 2,
          onclick: () => { labels.splice(index, 1); onDraftChanged(true); },
        }),
      ]),
    );
    row.append(el("textarea", {
      value: label.description || "",
      placeholder: "锚点描述：写「这段话长什么样」+ 几条例句。例：「……」",
      disabled: readOnly,
      oninput: (event) => { label.description = event.target.value; onDraftChanged(); },
    }));
    row.append(el("input", {
      type: "text", value: label.hint || "", placeholder: "人话提示：判定结果下面显示的那句",
      disabled: readOnly, style: "margin-top:8px",
      oninput: (event) => { label.hint = event.target.value; },
    }));
    box.append(row);
  });
}

function move(list, from, to) {
  const [item] = list.splice(from, 1);
  list.splice(to, 0, item);
  onDraftChanged(true);
}

/* -------------------------------------------------------------- 示例编辑 */

function renderExamples() {
  const box = $("ed-examples");
  box.innerHTML = "";
  const readOnly = Boolean(state.draft.builtin);
  const examples = state.draft.examples || [];
  const labelIds = (state.draft.labels || []).map((label) => label.id);
  $("ed-example-count").textContent = `${examples.length} 条`;

  if (!examples.length) {
    box.append(el("div", { class: "empty", text: "还没有示例。示例是给用户点着试的，别用锚点里的原句（那是自问自答）。" }));
  }

  examples.forEach((example, index) => {
    const select = el("select", {
      disabled: readOnly, style: "width:110px",
      onchange: (event) => { example.label = event.target.value; onDraftChanged(); },
    }, labelIds.map((id) => el("option", { value: id, text: id, selected: id === example.label })));
    box.append(
      el("div", { class: "row tight", style: "margin-bottom:8px;flex-wrap:nowrap" }, [
        select,
        el("input", {
          type: "text", value: example.text, disabled: readOnly, placeholder: "示例文本",
          oninput: (event) => { example.text = event.target.value; onDraftChanged(); },
        }),
        el("button", {
          class: "btn icon danger", text: "×", disabled: readOnly,
          onclick: () => { examples.splice(index, 1); onDraftChanged(true); },
        }),
      ]),
    );
  });
}

/* ---------------------------------------------------------------- 校验 */

const validateSoon = debounce(() => validateNow(), 350);

function onDraftChanged(rerender = false) {
  dirty = true;
  $("ed-state").textContent = "有未保存的改动";
  collect();
  if (rerender) {
    renderLabels();
    renderExamples();
  }
  renderPayload();
  renderStats();
  validateSoon();
}

async function validateNow() {
  collect();
  try {
    const payload = await api.profileValidate(state.draft);
    issues = payload.issues || [];
    renderIssues(payload);
  } catch (error) {
    $("ed-issues").innerHTML = "";
    $("ed-issues").append(el("div", { class: "issue error" }, [
      el("span", { class: "lv", text: "!" }),
      el("span", { text: "校验请求失败：" + error.message }),
    ]));
  }
}

function renderIssues(payload = null) {
  const box = $("ed-issues");
  box.innerHTML = "";
  const errors = issues.filter((issue) => issue.level === "error");
  const warnings = issues.filter((issue) => issue.level === "warning");
  $("ed-issue-count").textContent = errors.length
    ? `${errors.length} 个错误`
    : (warnings.length ? `${warnings.length} 条提示` : "通过");

  if (!issues.length) {
    box.append(el("div", { class: "empty", text: "没有发现问题。" }));
    return;
  }
  for (const issue of [...errors, ...warnings]) {
    box.append(el("div", { class: "issue " + issue.level, title: "点一下跳到对应字段" }, [
      el("span", { class: "lv", text: issue.level === "error" ? "错误" : "提示" }),
      el("span", {}, [
        el("span", { class: "fld", text: `[${issue.field}] ` }),
        el("span", { text: issue.message }),
      ]),
    ]));
  }
  if (payload?.stats) renderStats(payload.stats);
}

function renderStats(stats = null) {
  const box = $("ed-stats");
  box.innerHTML = "";
  const data = stats || statsOf(state.draft);
  const rows = [
    ["选项", `${data.label_count} 个`],
    ["锚点字数", `${data.description_chars} 字（最短 ${data.description_min} / 最长 ${data.description_max}）`],
    ["锚点例句", `约 ${data.anchor_examples} 条`],
    ["页面示例", `${data.example_count} 条`],
    ["判定问法", `${data.criterion_chars} 字`],
    ["每次判定读入", `约 ${data.prompt_chars} 字`],
  ];
  for (const [key, value] of rows) {
    box.append(el("dt", { text: key }));
    box.append(el("dd", { text: value }));
  }
}

/** 本地粗算，只为了让编辑器在等服务端回话时不空着。 */
function statsOf(profile) {
  const labels = profile.labels || [];
  const lengths = labels.map((label) => (label.description || "").length);
  const quotes = labels.reduce((sum, label) => {
    const text = label.description || "";
    return sum + Math.floor((text.split("「").length - 1 + text.split("」").length - 1) / 2);
  }, 0);
  return {
    label_count: labels.length,
    description_chars: lengths.reduce((a, b) => a + b, 0),
    description_min: lengths.length ? Math.min(...lengths) : 0,
    description_max: lengths.length ? Math.max(...lengths) : 0,
    anchor_examples: quotes,
    example_count: (profile.examples || []).length,
    criterion_chars: (profile.criterion || "").length,
    prompt_chars: lengths.reduce((a, b) => a + b, 0) + (profile.criterion || "").length,
  };
}

/* -------------------------------------------------- 模型实际读到的内容 */

function renderPayload() {
  const draft = state.draft;
  const payload = {
    evidence: "（这里是待判定的那条评论）",
    criterion: draft.criterion || "",
    options: (draft.labels || []).map((label, index) => ({
      letter: String.fromCharCode(65 + index),
      description: label.description || "",
    })),
  };
  $("ed-payload").textContent = JSON.stringify(payload, null, 2);
}

/* ------------------------------------------------------------ 保存 / 导出 */

async function save(overwrite = false) {
  collect();
  const errors = issues.filter((issue) => issue.level === "error");
  if (errors.length) {
    toast(`还有 ${errors.length} 个错误没修，先看下面的校验结论`, "err");
    return;
  }
  try {
    await api.profileSave(state.draft, overwrite);
    dirty = false;
    toast(`已保存「${state.draft.name}」`, "ok");
    await refreshProfiles();
    await selectProfile(state.draft.id);
  } catch (error) {
    if (error.payload?.issues?.length) {
      issues = error.payload.issues;
      renderIssues();
    }
    if (/覆盖/.test(error.message)) {
      const ok = await confirmDialog("覆盖已有的类型", esc(error.message));
      if (ok) await save(true);
      return;
    }
    toast("保存失败：" + error.message, "err");
  }
}

async function duplicate() {
  const copy = structuredClone(collect());
  copy.id = `${copy.id}-copy`;
  copy.name = `${copy.name} 副本`;
  copy.builtin = false;
  state.draft = copy;
  dirty = true;
  $("ed-id").disabled = true;
  $("ed-badge").textContent = "我的类型";
  for (const id of ["ed-name", "ed-summary", "ed-criterion", "ed-version", "ed-note", "ed-add-label", "ed-add-example", "ed-save", "ed-delete"]) {
    $(id).disabled = false;
  }
  fillFormFieldsOnly();
  renderLabels();
  renderExamples();
  renderPayload();
  await validateNow();
  toast("已复制成新草稿，改完点保存", "ok");
}

/** 另存为副本时只刷输入框的值，不动 disabled 状态。 */
function fillFormFieldsOnly() {
  $("ed-name").value = state.draft.name;
  $("ed-summary").value = state.draft.summary || "";
  $("ed-criterion").value = state.draft.criterion || "";
  $("ed-version").value = state.draft.version || "";
  $("ed-note").value = state.draft.note || "";
}

async function tryDecide() {
  const text = $("ed-try-text").value.trim();
  if (!text) { toast("先填一句要试判的文本", "warn"); return; }
  collect();
  const box = $("ed-try-result");
  box.innerHTML = "";
  box.append(el("div", { class: "hint", text: "试判中…" }));
  try {
    const result = await api.decide({ text, permutations: 5, inline: state.draft });
    box.innerHTML = "";
    box.append(el("div", { class: "hint", text: "未保存的内容也能试判 —— 判定用的就是你现在看到的锚点：" }));
    const bars = el("div", { class: "bars raw", style: "margin-top:8px" });
    const max = Math.max(...result.ranking.map((row) => row.probability), 0.0001);
    for (const row of result.ranking) {
      bars.append(el("div", { class: "bar" + (row.id === result.winner ? " top" : "") }, [
        el("div", { class: "ch", text: row.id, title: row.id }),
        el("div", { class: "track" }, [
          el("div", {
            class: "fill",
            style: `width:${Math.max((row.probability / max) * 100, 2)}%;background:${row.accent || "var(--muted)"};opacity:1`,
          }),
        ]),
        el("div", { class: "pct", text: pct(row.probability) }),
      ]));
    }
    box.append(bars);
    box.append(el("div", { class: "hint num", style: "margin-top:8px",
      text: `${result.forward_ms} ms 推理 · ${result.permutations} 排列 · ${result.input_tokens} token` }));
  } catch (error) {
    box.innerHTML = "";
    box.append(el("div", { class: "issue error" }, [el("span", { text: error.message })]));
  }
}

/* ------------------------------------------------------------ 评测小结 */

function renderEditorEval(evalPayload) {
  const box = $("editor-eval");
  box.innerHTML = "";
  if (!evalPayload?.available) {
    box.append(el("div", { class: "hint" }));
    box.lastChild.innerHTML =
      "这套类型还没评测过。<b>没有评测数字 ≠ 不好用</b>，只是没人量过 —— " +
      "页面上（包括「评测」页）显示的成绩是「八艺」那一套的，别拿来当它的成绩。<br>" +
      `自己量一遍：<code>python scripts/evaluate.py --profile ${esc(state.draft.id)} --data &lt;你的测试集&gt; --write-result</code>`;
    return;
  }
  box.append(el("div", { class: "kv" }, [
    el("dt", { text: "准确率" }),
    el("dd", { text: `${pct(evalPayload.accuracy)}（${evalPayload.correct}/${evalPayload.total}）` }),
    el("dt", { text: "95% 置信区间" }),
    el("dd", { text: evalPayload.ci95 ? `${pct(evalPayload.ci95[0])} ~ ${pct(evalPayload.ci95[1])}` : "—" }),
    el("dt", { text: "测试集" }),
    el("dd", { text: evalPayload.dataset || "—" }),
  ]));
  box.append(el("div", { class: "hint", style: "margin-top:8px",
    text: "区间才是重点：几十条样本上的百分比，一两条的差距说明不了什么。" }));
}

/* ------------------------------------------------------------------ 装配 */

export function init() {
  $("profile-new").addEventListener("click", () => {
    state.draft = {
      id: "my-profile",
      name: "新判断类型",
      summary: "",
      criterion: "下面这句话最符合哪一类？请选出最贴切的那一个。",
      version: "v1",
      note: "",
      labels: [
        { id: "甲", name: "甲", pinyin: "", description: "例：「」「」", hint: "", accent: ACCENTS[0] },
        { id: "乙", name: "乙", pinyin: "", description: "例：「」「」", hint: "", accent: ACCENTS[1] },
      ],
      examples: [],
      builtin: false,
      evaluated: false,
    };
    dirty = true;
    $("ed-id").disabled = false;
    $("ed-id").value = state.draft.id;
    for (const id of ["ed-name", "ed-summary", "ed-criterion", "ed-version", "ed-note", "ed-add-label", "ed-add-example", "ed-save", "ed-delete"]) {
      $(id).disabled = false;
    }
    $("ed-badge").textContent = "新草稿";
    $("ed-state").textContent = "还没保存";
    fillFormFieldsOnly();
    renderLabels();
    renderExamples();
    renderPayload();
    validateNow();
    toast("新建了一套类型：先改 id 和锚点，再保存", "ok");
  });

  $("ed-id").addEventListener("input", (event) => {
    state.draft.id = event.target.value.trim();
    onDraftChanged();
  });
  for (const id of ["ed-name", "ed-summary", "ed-criterion", "ed-version", "ed-note"]) {
    $(id).addEventListener("input", () => onDraftChanged());
  }

  $("ed-add-label").addEventListener("click", () => {
    if ((state.draft.labels || []).length >= 16) {
      toast("最多 16 个选项 —— 上游把选项绑在 A–P 这 16 个单 token 槽位上", "warn");
      return;
    }
    state.draft.labels.push({
      id: `选项${state.draft.labels.length + 1}`, name: "", pinyin: "",
      description: "", hint: "", accent: ACCENTS[state.draft.labels.length % ACCENTS.length],
    });
    onDraftChanged(true);
  });

  $("ed-add-example").addEventListener("click", () => {
    const first = state.draft.labels[0]?.id || "";
    state.draft.examples.push({ label: first, text: "" });
    onDraftChanged(true);
  });

  $("ed-save").addEventListener("click", () => save(false));
  $("ed-duplicate").addEventListener("click", duplicate);
  $("ed-try").addEventListener("click", tryDecide);

  $("ed-export").addEventListener("click", () => {
    collect();
    download(`${state.draft.id}.json`, JSON.stringify(state.draft, null, 2) + "\n");
    toast("已导出（可以发给别人导入）", "ok");
  });

  $("ed-delete").addEventListener("click", async () => {
    if (state.draft.builtin) { toast("内置类型删不掉，那是仓库的一部分", "warn"); return; }
    const ok = await confirmDialog("删除判断类型",
      `确定删掉「${esc(state.draft.name)}」？不能撤销。`);
    if (!ok) return;
    try {
      await api.profileDelete(state.draft.id);
      toast("已删除", "ok");
      await refreshProfiles();
      await selectProfile("bayi");
    } catch (error) {
      toast("删除失败：" + error.message, "err");
    }
  });

  $("profile-import").addEventListener("click", () => {
    const input = el("input", { type: "file", accept: ".json,application/json", style: "display:none" });
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const raw = JSON.parse(await file.text());
        const payload = await api.profileImport(raw, false);
        toast(`已导入「${payload.profile.name}」`, "ok");
        await refreshProfiles();
        await selectProfile(payload.profile.id);
      } catch (error) {
        if (/覆盖|已存在/.test(error.message)) {
          const ok = await confirmDialog("已经存在同 id 的类型", esc(error.message));
          if (ok) {
            try {
              const raw = JSON.parse(await file.text());
              const payload = await api.profileImport(raw, true);
              await refreshProfiles();
              await selectProfile(payload.profile.id);
              toast("已覆盖导入", "ok");
            } catch (inner) {
              toast("导入失败：" + inner.message, "err");
            }
          }
          return;
        }
        toast("导入失败：" + error.message, "err");
      } finally {
        input.remove();
      }
    });
    document.body.append(input);
    input.click();
  });

  $("profile-export-all").addEventListener("click", async () => {
    try {
      const bundle = { schema: 1, exported_at: new Date().toISOString(), profiles: [] };
      for (const summary of state.profiles) {
        const payload = await api.profile(summary.id);
        bundle.profiles.push(payload.profile);
      }
      download("bayi-profiles.json", JSON.stringify(bundle, null, 2) + "\n");
      toast(`已导出 ${bundle.profiles.length} 套类型`, "ok");
    } catch (error) {
      toast("导出失败：" + error.message, "err");
    }
  });

  on("profiles", renderProfileList);
}

export function hasUnsavedChanges() {
  return dirty;
}
