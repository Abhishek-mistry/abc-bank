// Shared helpers (UI) + the global App from design §11.6.
// Page scripts destructure what they need: const { h, $, busy, fail, field, submit } = UI;
const UI = (() => {
  class Safe { constructor(s) { this.s = s; } toString() { return this.s; } }
  const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  // Tagged template: every ${value} is HTML-escaped unless it is a nested h`` result; arrays are flattened.
  const h = (s, ...v) => new Safe(s.reduce((o, t, i) =>
    o + t + (i < v.length ? [].concat(v[i]).map((x) => (x instanceof Safe ? x : escapeHtml(x))).join('') : ''), ''));
  const $ = (id) => document.getElementById(id);
  // Inline Lucide icon (uses currentColor). Markup comes from js/icons.js, so it is trusted.
  const icon = (name, size = 20) => new Safe(`<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name] || ''}</svg>`);
  const fail = (e) => App.toast(e.message, 'error');
  // Disable + spinner while fn runs; any error becomes a toast.
  const busy = async (btn, fn) => {
    btn.disabled = true; btn.classList.add('loading');
    try { return await fn(); } catch (e) { fail(e); } finally { btn.disabled = false; btn.classList.remove('loading'); }
  };
  const field = (name, label, type = 'text', v = '') =>
    h`<div class="form-group"><label>${label}<input class="form-input" name="${name}" type="${type}" value="${v}"></label><small class="form-error" data-for="${name}"></small></div>`;
  const showErrors = (form, fields = {}) => form.querySelectorAll('[data-for]').forEach((e) => { e.textContent = fields[e.dataset.for] || ''; });
  // Submit handler: busy button + inline errors from details.fields.
  const submit = (form, fn) => form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const btn = form.querySelector('[type=submit]');
    if (btn.disabled) return; // already in flight (Enter key / requestSubmit bypass a disabled button)
    showErrors(form);
    busy(btn, async () => {
      try { await fn(Object.fromEntries(new FormData(form))); } catch (e) { showErrors(form, e.details?.fields); throw e; }
    });
  });
  return { escapeHtml, h, $, icon, fail, busy, field, showErrors, submit };
})();

const App = {
  state: { dashboard: null },
  getUserId: () => localStorage.getItem('abc_user_id'),
  isOfficer: () => localStorage.getItem('abc_role') === 'OFFICER',
  home: () => (App.isOfficer() ? 'admin.html' : 'dashboard.html'),
  requireLogin() {
    if (!App.getUserId()) { location.replace('index.html'); return false; }
    if (App.isOfficer()) { location.replace('admin.html'); return false; } // staff use the officer dashboard
    return true;
  },
  logout() { localStorage.clear(); location.href = 'index.html'; },

  renderShell(active) {
    if (!App.requireLogin()) return new Promise(() => {}); // redirecting: never render or fetch
    const { h, $, icon } = UI;
    const nav = [['dashboard', 'Dashboard', 'layout-dashboard'], ['loans', 'Loans', 'hand-coins'], ['transactions', 'Transactions', 'arrow-left-right'], ['profile', 'Profile', 'user'], ['notifications', 'Notifications', 'bell']];
    const shell = document.createElement('div');
    shell.className = 'shell';
    shell.innerHTML = h`<nav class="sidebar">${nav.map(([k, label, ic]) =>
      h`<a href="${k}.html" class="${k === active ? 'active' : ''}">${icon(ic)}${label}${k === 'notifications' ? h`<i class="dot" id="dot" hidden></i>` : ''}</a>`)}</nav>
      <div class="main"><header class="topbar"><b id="balance">…</b><span class="logo">${icon('landmark', 24)}ABC Bank</span><a href="index.html" id="logout">Log out</a></header></div>`;
    shell.querySelector('.main').append($('page-content'));
    shell.querySelector('#logout').onclick = (e) => { e.preventDefault(); App.logout(); };
    document.body.prepend(shell);
    return App.refreshShell();
  },
  async refreshShell() {
    const d = (App.state.dashboard = await api.get('/dashboard'));
    UI.$('balance').textContent = App.formatMoney(d.primary_account ? d.primary_account.balance : d.total_balance);
    UI.$('dot').hidden = !d.unread_notifications;
    return d;
  },

  // String in, string out. Indian digit grouping via BigInt so no float ever touches a money value.
  formatMoney(s) {
    const m = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(s);
    return m ? `${m[1]}₹${BigInt(m[2]).toLocaleString('en-IN')}.${(m[3] || '').padEnd(2, '0')}` : '—';
  },
  formatDate: (d) => d ? new Date(d).toLocaleDateString('en-IN', { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' }) : '—',
  formatDateTime: (d) => d ? new Date(d).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—',

  toast(message, type = 'info') {
    if (!UI.$('toasts')) document.body.insertAdjacentHTML('beforeend', '<div id="toasts" aria-live="polite"></div>');
    const t = Object.assign(document.createElement('div'), { className: `toast ${type}`, textContent: message });
    UI.$('toasts').append(t);
    setTimeout(() => t.remove(), 4500);
  },
  confirm: (message) => new Promise((resolve) => {
    const m = Object.assign(document.createElement('div'), { className: 'modal-backdrop' });
    m.innerHTML = UI.h`<div class="modal" role="alertdialog" aria-modal="true"><p>${message}</p><div class="row"><button class="btn btn-secondary">Cancel</button><button class="btn btn-danger" value="1">Confirm</button></div></div>`;
    m.onclick = (e) => { const b = e.target.closest('button'); if (b || e.target === m) { m.remove(); resolve(!!b?.value); } };
    document.body.append(m);
    m.querySelector('button').focus();
  }),
  uuid: () => crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`,
};

// Shared money-movement UX (design §11.7), used by send-money, deposit and transactions.
const Money = (() => {
  const { h, $, field, showErrors, submit } = UI;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const SAFE_RETRY = ['SIMULATED_NETWORK_FAILURE', 'TXN_RETRY_EXHAUSTED', 'NETWORK_TIMEOUT', 'NETWORK_ERROR'];
  const ROLLED_BACK = 'Transaction rolled back. Your money is safe.';
  const MESSAGES = {
    SIMULATED_NETWORK_FAILURE: () => ROLLED_BACK,
    TXN_RETRY_EXHAUSTED: () => ROLLED_BACK,
    NETWORK_TIMEOUT: () => "We couldn't confirm this payment. Check Transactions before sending again; retrying is safe and never charges twice.",
    INSUFFICIENT_FUNDS: (e) => `Insufficient funds. Available: ${App.formatMoney(e.details.available)}.`,
    REVERSAL_FUNDS_UNAVAILABLE: () => 'The recipient no longer has enough balance.',
  };
  const explain = (e) => (MESSAGES[e.code] || (() => e.message))(e);
  const short = (ref) => ref.slice(0, 8).toUpperCase();

  // "100.5" -> 10050n (BigInt cents), or null when not a plain amount with <= 2 decimals. No floats.
  const cents = (s) => /^\d+(\.\d{1,2})?$/.test(s) ? BigInt(s.replace(/^(\d+)\.?(\d*)$/, (_, i, f) => i + f.padEnd(2, '0'))) : null;

  // POST that auto-retries NETWORK_TIMEOUT up to 3x, 1 s apart (caller must send the same idempotency_key).
  const post = async (path, body, wait) => {
    for (let i = 0; ; i++) {
      try { return await api.post(path, body); } catch (e) {
        if (e.code !== 'NETWORK_TIMEOUT' || i >= 3) throw e;
        wait('Connection lost — checking your payment…');
        await sleep(1000);
      }
    }
  };

  // Renders a full "pay from one of my accounts" form into #page-content.
  //   from: name of the account <select> (API field); max: amount ceiling as string; extra: html placed under the select
  //   check(v) -> {field: message}; ask(v) -> confirm text; done(data) -> html for the success card
  const form = ({ title, button, path, from, max, extra = '', check, ask, done }) => {
    $('page-content').innerHTML = h`<form class="card" id="pay" novalidate><h2>${title}</h2>
      <div class="form-group"><label>From account<select class="form-select" name="${from}"></select></label><small class="form-error" data-for="${from}"></small></div>
      ${extra}${field('amount', 'Amount (₹)')}${field('note', 'Note (optional)')}
      <button class="btn btn-primary" type="submit">${button}</button><div id="out" aria-live="polite"></div></form>`;
    const f = $('pay'), out = $('out'), maxCents = cents(max);
    let key = App.uuid(), retrying = false;

    const loadAccounts = async () => {
      const sel = f.elements[from], keep = sel.value;
      const { accounts } = await api.get('/accounts');
      const active = accounts.filter((a) => a.status === 'ACTIVE');
      sel.innerHTML = active.length
        ? h`${active.map((a) => h`<option value="${a.account_number}">${a.account_number} · ${App.formatMoney(a.balance)}</option>`)}`
        : h`<option value="">No active account</option>`;
      if (keep) sel.value = keep;
    };

    f.addEventListener('input', () => { key = App.uuid(); }); // any edit = a new payment = a new key
    out.addEventListener('click', (e) => { if (e.target.dataset.retry) { retrying = true; f.requestSubmit(); } });

    submit(f, async (raw) => {
      const skipConfirm = retrying; retrying = false;
      const v = Object.fromEntries(Object.entries(raw).map(([k, x]) => [k, x.trim()]));
      const errs = { ...check(v) };
      const c = cents(v.amount);
      if (!v[from]) errs[from] = 'Choose an active account.';
      if (c === null || c < 100n || c > maxCents) errs.amount = `Enter an amount from ₹1.00 to ${App.formatMoney(max)}, with at most 2 decimals.`;
      if (v.note.length > 100) errs.note = 'Note can be at most 100 characters.';
      if (Object.keys(errs).length) return showErrors(f, errs);
      if (!skipConfirm && !(await App.confirm(ask(v)))) return;

      out.innerHTML = '';
      try {
        const body = Object.fromEntries(Object.entries(v).filter(([, x]) => x !== ''));
        const d = await post(path, { ...body, idempotency_key: key }, (m) => { out.textContent = m; });
        key = App.uuid();
        f.elements.amount.value = f.elements.note.value = '';
        out.innerHTML = h`<div class="card ok-card">${done(d)}${d.idempotent_replay ? h`<p><b>This payment was already processed — no duplicate charge.</b></p>` : ''}</div>`;
        await Promise.all([loadAccounts(), App.refreshShell()]).catch(UI.fail); // payment already succeeded: a refresh error must not look like a payment error
      } catch (e) {
        if (e.code === 'VALIDATION_ERROR') throw e; // submit() maps details.fields onto the inputs
        out.innerHTML = h`<p class="form-error">${explain(e)}</p>${SAFE_RETRY.includes(e.code)
          ? h`<button type="button" class="btn btn-secondary" data-retry="1">Retry</button> <a href="transactions.html">View history</a>` : ''}`;
      }
    });
    return App.renderShell('transactions').then(loadAccounts).catch(UI.fail);
  };

  return { form, post, explain, short, sleep };
})();
