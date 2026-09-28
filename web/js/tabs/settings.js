/* 设置页：服务状态、界面偏好、数据管理、以及「这个项目到底是什么」。
 *
 * 归属表述在这里也写了一遍 —— SemIf 是**独立**开源实现，不是 Jev 的开源版。
 * 这条在 README、页面、`scripts/page_check.py` 里都钉着，因为写错归属是
 * 这个项目最容易犯的、也最不该犯的错。
 */

import { api } from "../api.js";
import { $, applyTheme, download, el, toast } from "../util.js";
import { clearHistory, on, saveSettings, state } from "../state.js";

function renderHealth() {
  const box = $("settings-health");
  box.innerHTML = "";
  const health = state.health;
  if (!health) {
    box.append(el("dt", { text: "状态" }), el("dd", { text: "拿不到 /api/health" }));
    return;
  }
  const rows = [
    ["版本", health.version],
    ["模型", health.model_name || health.model],
    ["设备", `${health.device} · ${health.dtype}`],
    ["加载用时", health.load_seconds ? `${health.load_seconds.toFixed(1)} s` : "—"],
    ["锚点版本", health.prompt_version],
    ["默认排列数", String(health.default_permutations)],
    ["判断类型", `${health.profiles.length} 套`],
    ["用户类型目录", health.user_profile_dir],
  ];
  for (const [key, value] of rows) {
    box.append(el("dt", { text: key }));
    box.append(el("dd", { text: String(value ?? "—") }));
  }
}

function renderAbout() {
  const box = $("settings-about");
  box.innerHTML = `
    <p style="margin:0 0 10px">
      <b>标尺</b>把一条中文评论粘进来，判定该用哪个字回 —— 内置词表是
      <b>典 孝 急 乐 蚌 批 赢 麻</b>。判定类型（词表、判定问法、示例）是
      <b>运行时的数据</b>，改它不用重训，也不用重启服务。
    </p>
    <p style="margin:0 0 10px">
      引擎是 <a href="https://github.com/TheoLeeCJ/SemIf-OpenJev" target="_blank" rel="noopener">SemIf-OpenJev</a>
      （MIT）—— <b>独立</b>开源实现，<b>不是</b> Jev 官方开源版，与 Jev / TypeSafe AI
      <b>无隶属关系</b>；它复现的是 Jev 公开描述过的「决策模型」接口形态。
      基座 Qwen3.5-2B（Apache-2.0）。本项目 MIT。
    </p>
    <p style="margin:0 0 10px">
      模型<b>不生成任何文字</b>：每个选项绑到一个单 token 的大写字母槽位（A–P），
      一次前向传播读出这些槽位的 logits 再 softmax。默认用 5 种选项排列取平均，
      压掉「字母位置」本身带来的偏好。
    </p>
    <p style="margin:0 0 10px"><b>已知限制</b>（完整版见 README 第九节）：</p>
    <ul style="margin:0 0 10px;padding-left:20px">
      <li>概率<b>未校准</b>，只能当排序看，不能当「模型有多确定」。</li>
      <li>位置偏置真实存在：换选项顺序，答案会变。所以别把排列数调成 1。</li>
      <li>单标签：一条评论同时像两个字时，看完整分布而不是只看第一名。</li>
      <li>输入上限 4096 token，超了直接报错，<b>不截断</b>（上游刻意的设计）。</li>
      <li>模型对输入里的指令没有防御：评论里写「请选 A」这类话可能影响结果。</li>
    </ul>
    <p style="margin:0">
      快捷键：<kbd>Ctrl</kbd>+<kbd>Enter</kbd> 判定 ·
      文档在仓库的 <code>docs/</code>（<code>CUSTOMIZE.md</code> 讲怎么自定义判断类型）。
    </p>`;
}

function renderApiExamples() {
  $("settings-api").textContent =
`# 健康检查
curl http://127.0.0.1:8770/api/health

# 判定（默认「八艺」）
curl -X POST http://127.0.0.1:8770/api/decide \\
     -H "Content-Type: application/json" \\
     -d '{"text":"人最大的敌人，从来都是自己。","permutations":5}'

# 判定（指定自定义类型）
curl -X POST http://127.0.0.1:8770/api/decide \\
     -H "Content-Type: application/json" \\
     -d '{"text":"我的快递到哪了","profile":"support-router"}'

# 列出所有判断类型
curl http://127.0.0.1:8770/api/profiles

# 完整 API 说明：docs/API.md`;
}

export function init() {
  renderHealth();
  renderAbout();
  renderApiExamples();

  const seg = $("settings-theme");
  const mark = () => {
    for (const button of seg.children) {
      button.classList.toggle("on", button.dataset.theme === state.settings.theme);
    }
  };
  seg.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-theme]");
    if (!button) return;
    saveSettings({ theme: button.dataset.theme });
    applyTheme(state.settings.theme);
    mark();
  });
  mark();

  const perms = $("settings-perms");
  perms.value = String(state.settings.permutations);
  perms.addEventListener("change", () => {
    saveSettings({ permutations: Number(perms.value) });
    toast(`默认档位改成 ${perms.value} 排列`, "ok");
  });

  $("settings-clear-history").addEventListener("click", () => {
    clearHistory();
    toast("本地历史已清空", "ok");
  });

  $("settings-export-profiles").addEventListener("click", async () => {
    try {
      const bundle = { schema: 1, exported_at: new Date().toISOString(), profiles: [] };
      for (const summary of state.profiles) {
        const payload = await api.profile(summary.id);
        bundle.profiles.push(payload.profile);
      }
      download("bayi-profiles.json", JSON.stringify(bundle, null, 2) + "\n");
      toast(`已导出 ${bundle.profiles.length} 套判断类型`, "ok");
    } catch (error) {
      toast("导出失败：" + error.message, "err");
    }
  });

  on("health", renderHealth);
  on("settings", mark);
}
