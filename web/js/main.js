/* 页面入口：装配四个标签页、拉初始状态、管路由。
 *
 * 路由用 URL hash（`#judge` / `#labels` / `#eval` / `#settings`），
 * 这样「把词表页发给别人」是一条能直接打开的链接。
 */

import { api } from "./api.js";
import { $, applyTheme, el, esc, pct, toast } from "./util.js";
import { emit, on, setProfileId, state } from "./state.js";
import * as editor from "./tabs/editor.js";
import * as evalTab from "./tabs/eval.js";
import * as judge from "./tabs/judge.js";
import * as settings from "./tabs/settings.js";

const TABS = ["judge", "labels", "eval", "settings"];

/* ------------------------------------------------------------------ 路由 */

function showTab(name, push = true) {
  const tab = TABS.includes(name) ? name : "judge";
  for (const button of $("tabs").children) {
    button.classList.toggle("on", button.dataset.tab === tab);
  }
  for (const panel of document.querySelectorAll(".panel-tab")) {
    panel.classList.toggle("on", panel.dataset.panel === tab);
  }
  if (push && location.hash !== `#${tab}`) {
    history.replaceState(null, "", `#${tab}`);
  }
  if (tab === "eval") evalTab.refresh();
}

/* ------------------------------------------------------------ 头部状态 */

function renderHeader(health) {
  state.health = health;
  state.version = health.version || "";
  $("version").textContent = health.version ? `v${health.version}` : "";
  $("glyphs").innerHTML = (health.labels || []).map((id) => `<span>${esc(id)}</span>`).join("");
  const pill = $("health-pill");
  pill.className = "pill " + (health.loaded ? "ok" : "bad");
  $("health-text").innerHTML =
    `<b>${esc(health.model_name || "模型未加载")}</b> · ${esc(health.device || "?")}`;
  emit("health", health);
}

function renderFooterEval(payload) {
  const accuracy = $("eval-accuracy");
  const detail = $("eval-detail");
  if (!accuracy || !detail) return;
  if (!payload?.available) {
    accuracy.textContent = "—";
    detail.textContent = "（还没跑过评测）";
    return;
  }
  accuracy.textContent = pct(payload.accuracy);
  const ci = payload.ci95
    ? `，95% 区间 ${pct(payload.ci95[0])}~${pct(payload.ci95[1])}`
    : "";
  detail.textContent = `（${payload.total} 条 · ${payload.permutations} 排列 · 中位 ${Math.round(payload.median_ms)} ms${ci}）`;
}

/* -------------------------------------------------------------- 类型选择 */

function renderProfileSelect() {
  const select = $("judge-profile");
  select.innerHTML = "";
  for (const summary of state.profiles) {
    select.append(el("option", {
      value: summary.id,
      text: `${summary.name}${summary.evaluated ? "" : "（未评测）"} · ${summary.label_ids.join("")}`,
      selected: summary.id === state.profileId,
    }));
  }
}

async function selectProfile(profileId) {
  await editor.selectProfile(profileId);
  renderProfileSelect();
}

/* ------------------------------------------------------------------ 启动 */

async function boot() {
  applyTheme(state.settings.theme);

  $("tabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-tab]");
    if (button) showTab(button.dataset.tab);
  });
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1), false));

  $("theme-btn").addEventListener("click", () => {
    const next = (document.documentElement.dataset.theme === "dark") ? "light" : "dark";
    state.settings.theme = next;
    applyTheme(next);
    toast(next === "dark" ? "已切到深色" : "已切到浅色");
  });

  $("judge-profile").addEventListener("change", (event) => selectProfile(event.target.value));

  // 有未保存的改动就拦一下 —— 编辑器里的东西不会自动存。
  window.addEventListener("beforeunload", (event) => {
    if (editor.hasUnsavedChanges()) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  // 先装配各页（它们要读 state），再拉数据。
  judge.init();
  editor.init();
  evalTab.init();
  settings.init();
  on("profile-id", renderProfileSelect);

  let health = null;
  try {
    health = await api.health();
    renderHeader(health);
  } catch (error) {
    $("health-pill").className = "pill bad";
    $("health-text").textContent = "连不上服务";
    toast("拿不到服务状态：" + error.message, "err");
  }

  try {
    const payload = await api.profiles();
    state.profiles = payload.profiles;
    const ids = state.profiles.map((summary) => summary.id);
    // 分享链接里带的类型优先；上次选中的类型可能已经被删了（或者是从别的
    // 浏览器过来的），那就退回默认那套。
    const shared = new URLSearchParams(location.search).get("profile");
    const wanted = [shared, state.profileId].find((id) => id && ids.includes(id)) || payload.default;
    state.profileId = wanted;
    renderProfileSelect();
    await selectProfile(wanted);
  } catch (error) {
    toast("拿不到判断类型列表：" + error.message, "err");
    return;
  }

  // 分享链接 / 截图用：`?t=<文本>&auto=1[&profile=<id>]`
  const params = new URLSearchParams(location.search);
  const sharedText = params.get("t");
  if (sharedText) {
    $("text").value = sharedText;
    $("text").dispatchEvent(new Event("input"));
    if (params.get("auto") === "1") await judge.run();
  }

  try {
    renderFooterEval(await api.eval("bayi"));
  } catch {
    renderFooterEval(null);
  }

  showTab(location.hash.slice(1) || "judge", false);
}

boot().catch((error) => {
  console.error(error);
  toast("页面初始化失败：" + error.message, "err");
});

export { setProfileId, selectProfile };
