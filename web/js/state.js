/* 全局状态：判断类型列表、当前类型、界面设置、本地历史。
 *
 * 状态变化靠一个极小的发布订阅广播（`on`/`emit`），各标签页自己订阅自己关心的
 * 那部分。不引框架是因为这个页面只有四个标签页，而框架的体积和构建步骤
 * 都不值得为它引入。
 */

import { store } from "./util.js";

const listeners = new Map();

export function on(event, handler) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(handler);
  return () => listeners.get(event).delete(handler);
}

export function emit(event, payload) {
  for (const handler of listeners.get(event) || []) {
    try {
      handler(payload);
    } catch (error) {
      console.error(`[state] ${event} 的处理函数炸了`, error);
    }
  }
}

export const state = {
  version: "",
  health: null,
  /** 类型摘要列表（不含锚点正文）。 */
  profiles: [],
  /** 当前选中的类型 id。判定页和评测页共用。 */
  profileId: store.get("profile", "bayi"),
  /** 当前类型的完整数据（含锚点）。 */
  profile: null,
  /** 编辑器里正在改的草稿 —— 和 `profile` 分开，才能「改了不保存也能试判」。 */
  draft: null,
  settings: {
    theme: store.get("theme", "dark"),
    permutations: store.get("permutations", 5),
  },
  history: store.get("history", []),
  batch: [],
};

export const MAX_HISTORY = 30;

export function saveSettings(patch) {
  Object.assign(state.settings, patch);
  store.set("theme", state.settings.theme);
  store.set("permutations", state.settings.permutations);
  emit("settings", state.settings);
}

export function setProfileId(profileId) {
  state.profileId = profileId;
  store.set("profile", profileId);
  emit("profile-id", profileId);
}

export function pushHistory(entry) {
  // 同一条文本重复判定只保留最新一次 —— 否则历史会被同一个句子刷屏。
  state.history = [entry, ...state.history.filter((item) => item.text !== entry.text)]
    .slice(0, MAX_HISTORY);
  store.set("history", state.history);
  emit("history", state.history);
}

export function clearHistory() {
  state.history = [];
  store.set("history", state.history);
  emit("history", state.history);
}

/** 当前类型是不是内置的（内置只读，只能另存为副本）。 */
export function isBuiltin(profileId = state.profileId) {
  const summary = state.profiles.find((item) => item.id === profileId);
  return Boolean(summary?.builtin);
}
