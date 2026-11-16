// Thin fetch wrapper (design §11.5). Paths are relative to /api.
class ApiClientError extends Error {
  constructor(code, message, status = 0, details = {}) {
    super(message);
    Object.assign(this, { name: 'ApiClientError', code, status, details });
  }
}

const api = (() => {
  const BASE = '/api';
  const send = async (method, path, body, params) => {
    const qs = new URLSearchParams(Object.entries(params || {}).filter(([, v]) => v != null && v !== '')).toString();
    const headers = {};
    const uid = localStorage.getItem('abc_user_id');
    if (uid) headers['X-User-Id'] = uid;
    if (body !== undefined && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    let res, json;
    try {
      res = await fetch(BASE + path + (qs ? '?' + qs : ''), { method, headers, body });
      json = await res.json();
    } catch {
      throw new ApiClientError('NETWORK_ERROR', 'Cannot reach the server. Check your connection and try again.');
    }
    if (json?.success) return json.data;
    const e = json?.error || {};
    if (res.status === 401 && e.code === 'AUTH_REQUIRED') { localStorage.clear(); location.href = 'index.html'; }
    throw new ApiClientError(e.code || 'INTERNAL_ERROR', e.message || 'Unexpected server error', res.status, e.details || {});
  };
  return {
    get: (p, q) => send('GET', p, undefined, q),
    post: (p, b = {}) => send('POST', p, b),
    put: (p, b = {}) => send('PUT', p, b),
    patch: (p, b = {}) => send('PATCH', p, b),
    delete: (p) => send('DELETE', p),
    upload: (p, fd) => send('POST', p, fd),
  };
})();
