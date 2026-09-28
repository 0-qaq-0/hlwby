/* 后端接口的唯一入口。
 *
 * 所有 fetch 都从这里走，别在别处直接写 URL —— 这样「接口长什么样」
 * 只有一处需要跟 `jev_meme/server.py` 对齐。
 */

async function request(path, options = {}) {
  const response = await fetch(path, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`服务器返回的不是 JSON（HTTP ${response.status}）`);
  }
  if (!response.ok || payload.ok === false) {
    const error = new Error(payload.error || `HTTP ${response.status}`);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

const get = (path) => request(path);

const post = (path, body) =>
  request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const api = {
  health: () => get("/api/health"),

  profiles: () => get("/api/profiles"),
  profile: (id) => get(`/api/profiles/${encodeURIComponent(id)}`),
  profileExportUrl: (id) => `/api/profiles/${encodeURIComponent(id)}/export`,
  profileSave: (profile, overwrite = false) => post("/api/profiles", { profile, overwrite }),
  profileValidate: (profile) => post("/api/profiles/validate", { profile }),
  profileDelete: (id) => post("/api/profiles/delete", { id }),
  profileImport: (profile, overwrite = false) => post("/api/profiles/import", { profile, overwrite }),

  /** 评测数字。不传 profile 就是内置「八艺」那一套。 */
  eval: (profileId) => get(`/api/eval?profile=${encodeURIComponent(profileId)}`),

  /** 仓库里带了哪几套测试集、各多少条。 */
  datasets: () => get("/api/datasets"),

  /**
   * 判定。`inline` 用来试判**还没保存**的词表 —— 编辑器「改一句立刻看效果」靠它。
   */
  decide: ({ text, permutations = 5, profile, inline }) =>
    post("/api/decide", { text, permutations, ...(inline ? { inline } : { profile }) }),
};
