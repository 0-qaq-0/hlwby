/* 通用工具：DOM、转义、提示、弹层、下载、本地存储。
 *
 * 刻意不引任何框架 —— 这个页面没有构建步骤，`web/` 里就是最终产物。
 * 服务器直接把这些文件发出去，改一行刷新就见效。
 */

export const $ = (id) => document.getElementById(id);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** 建元素。`attrs` 里 `class`/`text`/`html`/`value`/`on*` 有特殊含义。 */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    // textarea 没有 value 这个**内容属性** —— 它的值是子文本节点，
    // `setAttribute("value", ...)` 在 textarea 上什么都不会发生（坑过一次：
    // 词表编辑器里所有锚点描述都显示成空的）。所以这里必须走 property。
    else if (key === "value") {
      if (tag === "textarea") node.value = value;
      else node.setAttribute("value", value);
    }
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** HTML 转义。凡是把用户输入拼进 innerHTML 的地方都必须过它。 */
export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function pct(value, digits = 1) {
  return (Number(value) * 100).toFixed(digits) + "%";
}

export function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

export function debounce(fn, wait = 300) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

/* ------------------------------------------------------------------ 提示 */

export function toast(message, kind = "", ms = 3200) {
  const box = $("toasts");
  if (!box) return;
  const node = el("div", { class: `toast ${kind}`, text: message });
  box.append(node);
  setTimeout(() => {
    node.style.opacity = "0";
    node.style.transition = "opacity .25s";
    setTimeout(() => node.remove(), 260);
  }, ms);
}

/** 简单的确认框。返回 Promise<boolean> —— 比原生 confirm 好排版，也能换行。 */
export function confirmDialog(title, body, okText = "确定") {
  return new Promise((resolve) => {
    const close = (value) => { back.remove(); resolve(value); };
    const back = el("div", { class: "modal-back", onclick: (e) => { if (e.target === back) close(false); } }, [
      el("div", { class: "modal" }, [
        el("h3", { text: title }),
        el("div", { class: "hint", html: body }),
        el("div", { class: "row end" }, [
          el("button", { class: "btn", text: "取消", onclick: () => close(false) }),
          el("button", { class: "btn primary", text: okText, onclick: () => close(true) }),
        ]),
      ]),
    ]);
    document.body.append(back);
  });
}

/* ------------------------------------------------------------ 剪贴板 / 下载 */

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // http://127.0.0.1 是安全上下文，正常都走得到上面那条；
    // 万一浏览器不给，退回 textarea + execCommand。
    const area = el("textarea", { style: "position:fixed;opacity:0" });
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export function download(filename, text, mime = "application/json;charset=utf-8") {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** 把数组导成 CSV。带 BOM，否则 Excel 打开中文是乱码。 */
export function toCSV(rows) {
  const cell = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  return "\ufeff" + rows.map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

/* ------------------------------------------------------------ 本地存储 */

export const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem(`bayi.${key}`);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(`bayi.${key}`, JSON.stringify(value));
    } catch {
      /* 隐私模式下写不进去，不影响使用 */
    }
  },
  remove(key) {
    try { localStorage.removeItem(`bayi.${key}`); } catch { /* 同上 */ }
  },
};

/* ------------------------------------------------------------ 主题 */

export function applyTheme(mode) {
  const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
  const theme = mode === "auto" ? (prefersLight ? "light" : "dark") : mode;
  document.documentElement.dataset.theme = theme;
  store.set("theme", mode);
  return theme;
}
