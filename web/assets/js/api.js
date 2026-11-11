// Thin fetch wrapper: bearer token, tenant header for the platform team, friendly errors.
export const store = {
  token: null, me: null, inst: null, perms: new Set(), viewInst: null,
  can(p) { return this.perms.has(p); },
};

try {
  store.token = localStorage.getItem('rice.token');
  store.viewInst = localStorage.getItem('rice.viewInst');
} catch (e) { /* storage unavailable — stay signed out */ }

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

// Absolute address for an API path — same origin locally, the hosted API on GitHub Pages.
export const apiUrl = (path) => (path.startsWith('/api') ? (window.RICE_API || '') + path : path);

export async function api(path, { method = 'GET', body, form, raw } = {}) {
  path = apiUrl(path);
  const headers = {};
  if (store.token) headers.Authorization = 'Bearer ' + store.token;
  if (store.viewInst && store.me && store.me.user.role === 'platform_admin') headers['X-RICE-Inst'] = store.viewInst;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  let res;
  try {
    res = await fetch(path, { method, headers, body: payload });
  } catch (e) {
    throw new ApiError(0, "Can't reach the RICE server. Check that it is running.");
  }
  if (raw) return res;
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) {
    if (res.status === 401 && store.token) {
      setToken(null);
      location.hash = '#/login';
    }
    throw new ApiError(res.status, (data && (data.error || data.detail && (typeof data.detail === 'string' ? data.detail : data.detail[0]?.msg))) || `Request failed (${res.status})`);
  }
  return data;
}

export function setToken(t) {
  store.token = t;
  try { t ? localStorage.setItem('rice.token', t) : localStorage.removeItem('rice.token'); } catch (e) { /* ignore */ }
}

export function setViewInst(id) {
  store.viewInst = id ? String(id) : null;
  try { id ? localStorage.setItem('rice.viewInst', id) : localStorage.removeItem('rice.viewInst'); } catch (e) { /* ignore */ }
}

export function qs(params) {
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '' && v !== false) u.set(k, v); });
  const s = u.toString();
  return s ? '?' + s : '';
}

export async function download(path, filename) {
  const res = await api(path, { raw: true });
  if (!res.ok) throw new ApiError(res.status, 'Export failed.');
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
