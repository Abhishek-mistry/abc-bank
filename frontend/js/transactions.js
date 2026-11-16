const { h, $, busy, fail } = UI;
const BADGE = { COMPLETED: 'success', FAILED: 'danger', REVERSED: 'warn' };
const SIGN = { OUT: '-', IN: '+' };
const keys = {}; // one idempotency key per reversal target until it succeeds
let page = 1, pages = 1;

const canReverse = (t) => t.txn_type === 'TRANSFER' && t.status === 'COMPLETED' && t.direction === 'OUT'
  && Date.now() - Date.parse(t.completed_at) < 864e5; // 24 h in ms, no money math

const row = (t) => h`<tr class="click" data-ref="${t.txn_ref}">
  <td>${App.formatDateTime(t.created_at)}</td>
  <td><span class="badge badge-info">${t.txn_type}</span></td>
  <td>${(t.direction === 'IN' ? t.from_name : t.to_name) || t.to_name || t.from_name || '—'}</td>
  <td>${t.description}${t.status === 'FAILED' ? h`<small class="form-error" title="${t.failure_reason}">${t.failure_code}</small>` : ''}</td>
  <td><b data-dir="${t.direction}">${SIGN[t.direction] || ''}${App.formatMoney(t.amount)}</b></td>
  <td><span class="badge badge-${BADGE[t.status]}">${t.status}</span></td>
  <td>${canReverse(t) ? h`<button class="btn btn-secondary" data-reverse="${t.txn_ref}">Reverse</button>` : ''}</td></tr>`;

const load = async () => {
  const d = await api.get('/transactions', { ...Object.fromEntries(new FormData($('filters'))), page, page_size: 10 });
  pages = d.total_pages || 1;
  $('rows').innerHTML = d.items.length ? h`${d.items.map(row)}` : h`<tr><td colspan="7" class="empty-state">No transactions found.</td></tr>`;
  $('pg').textContent = `Page ${page} of ${pages}`;
  $('prev').disabled = page <= 1;
  $('next').disabled = page >= pages;
};

const fmt = (k, v) => (k === 'amount' ? App.formatMoney(v) : k.endsWith('_at') ? App.formatDateTime(v) : v);
const detail = async (ref) => {
  const { transaction: t, ledger_entries: le } = await api.get(`/transactions/${ref}`);
  const m = Object.assign(document.createElement('div'), { className: 'modal-backdrop' });
  m.innerHTML = h`<div class="modal wide" role="dialog" aria-modal="true"><h3>Transaction</h3>
    <table class="table">${Object.entries(t).filter(([, v]) => v != null).map(([k, v]) => h`<tr><th>${k}</th><td>${fmt(k, v)}</td></tr>`)}</table>
    <h3>Ledger entries</h3>${le.length
      ? h`<table class="table"><tr><th>Account</th><th>Type</th><th>Amount</th><th>Balance after</th></tr>${le.map((l) =>
        h`<tr><td>${l.account_number}</td><td>${l.entry_type}</td><td>${App.formatMoney(l.amount)}</td><td>${App.formatMoney(l.balance_after)}</td></tr>`)}</table>`
      : h`<p class="empty-state">No ledger entries.</p>`}
    <button class="btn btn-secondary">Close</button></div>`;
  m.onclick = (e) => { if (e.target === m || e.target.closest('button')) m.remove(); };
  document.body.append(m);
};

const reverse = (btn) => busy(btn, async () => {
  const ref = btn.dataset.reverse;
  if (!(await App.confirm('Reverse this transfer? The money returns to your account if the recipient still has it.'))) return;
  keys[ref] ||= App.uuid();
  try {
    const d = await Money.post(`/transactions/${ref}/reverse`, { idempotency_key: keys[ref] }, (m) => App.toast(m, 'info'));
    delete keys[ref];
    App.toast(d.idempotent_replay ? 'Already reversed — no duplicate refund' : 'Transfer reversed', 'success');
    await Promise.all([load(), App.refreshShell()]);
  } catch (e) {
    App.toast(Money.explain(e), 'error'); // key kept: pressing Reverse again is a safe retry
    if (e.code === 'TXN_NOT_REVERSIBLE') await load();
  }
});

App.renderShell('transactions').then(async () => {
  const { accounts } = await api.get('/accounts');
  $('account').insertAdjacentHTML('beforeend', h`${accounts.map((a) => h`<option value="${a.account_id}">${a.account_number} (${a.status})</option>`)}`);
  $('account').value = new URLSearchParams(location.search).get('account_id') || '';
  await load();
}).catch(fail);

$('filters').onsubmit = (e) => { e.preventDefault(); page = 1; busy($('apply'), load); };
$('filters').onreset = () => setTimeout(() => { page = 1; load().catch(fail); });
$('prev').onclick = () => { page--; load().catch(fail); };
$('next').onclick = () => { page++; load().catch(fail); };
$('rows').onclick = (e) => {
  const b = e.target.closest('[data-reverse]');
  if (b) return reverse(b);
  const tr = e.target.closest('tr[data-ref]');
  if (tr) detail(tr.dataset.ref).catch(fail);
};
