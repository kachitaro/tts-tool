// Gọi API của tool. Mọi lỗi thành ApiError; errors.js đổi sang lời thường.
export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(url, opts) {
  let res;
  try { res = await fetch(url, opts); }
  catch (e) { throw new ApiError(0, String(e && e.message || e)); }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error || msg; } catch { /* không phải JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res;
}

export const getJSON = async (url) => (await api(url)).json();
export const sendJSON = async (url, body, method = "POST") =>
  (await api(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) })).json();
export const sendForm = async (url, fields, method = "POST") => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v != null) fd.append(k, v);
  return api(url, { method, body: fd });
};
