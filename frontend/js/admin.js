const { h, $, icon, busy, fail } = UI;
if (!App.getUserId()) location.replace('index.html');
else if (!App.isOfficer()) location.replace('dashboard.html');

const TONE = { PENDING_REVIEW: 'warn', APPROVED: 'info', ACTIVE: 'success', CLOSED: '', REJECTED: 'danger', CANCELLED: '', DRAFT: '',
  COMPLETED: 'success', FAILED: 'danger', REVERSED: 'warn', PENDING: 'warn' };
const badge = (s) => h`<span class="badge${TONE[s] ? ` badge-${TONE[s]}` : ''}">${String(s).replace('_', ' ')}</span>`;
const empty = (t) => h`<p class="empty-state">${t}</p>`;
const money = (v) => (v == null ? '—' : App.formatMoney(v));
const kv = (rows) => h`<dl class="kv">${rows.map(([k, v]) => h`<dt>${k}</dt><dd>${v ?? '—'}</dd>`)}</dl>`;
const view = $('page-content');

const TABS = [['overview', 'Overview', 'layout-dashboard'], ['queue', 'Review Queue', 'file-text'], ['loans', 'All Loans', 'hand-coins'],
  ['customers', 'Customers', 'user'], ['txns', 'Transactions', 'arrow-left-right'], ['tools', 'Testing Tools', 'shield-check']];

$('nav').innerHTML = h`${TABS.map(([k, t, ic]) => h`<button type="button" data-tab="${k}">${icon(ic)}${t}</button>`)}`;
$('logo').innerHTML = h`${icon('landmark', 24)}ABC Bank · Staff`;
$('logout').onclick = (e) => { e.preventDefault(); App.logout(); };
$('nav').onclick = (e) => { const b = e.target.closest('[data-tab]'); if (b) show(b.dataset.tab); };

/* ---------- overview ---------- */
const overview = async () => {
  const [o, integ] = await Promise.all([api.get('/admin/overview'), api.get('/admin/integrity')]);
  const bad = Object.entries(integ.checks).flatMap(([k, c]) => c.violations.map((v) => `${k}: ${JSON.stringify(v)}`));
  view.innerHTML = h`<div class="grid">
    <section class="card"><h3>Customers</h3><p class="stat">${o.customers}</p></section>
    <section class="card"><h3>Awaiting review</h3><p class="stat">${o.pending_loans}</p>${o.pending_loans ? h`<button class="btn btn-primary" data-go="queue">Open queue</button>` : ''}</section>
    <section class="card"><h3>Active loans</h3><p class="stat">${o.active_loans}</p></section>
    <section class="card"><h3>Transactions</h3><p class="stat">${o.transactions}</p></section></div>
    <section class="card"><h3>System health</h3><ul class="list">
      <li><span>Database</span><b>${o.health.db}</b></li>
      <li><span>Status</span><b>${o.health.status.replace('_', ' ')}</b></li>
      <li><span>Failure mode</span><b>${o.health.simulation_mode}</b></li>
      <li><span>Failed transactions (24h)</span><b>${o.health.failed_txns_24h}</b></li>
      <li><span>Ledger integrity</span><b>${integ.ok ? 'All checks passed' : `${bad.length} violation(s)`}</b></li></ul>
      ${bad.length ? h`<ul class="list">${bad.map((b) => h`<li class="viol">${b}</li>`)}</ul>` : ''}</section>`;
  view.querySelectorAll('[data-go]').forEach((b) => { b.onclick = () => show(b.dataset.go); });
};

/* ---------- loans ---------- */
const loanTable = (loans, withCta) => (loans.length ? h`<table class="table"><thead><tr><th>#</th><th>Customer</th><th>Requested</th><th>Tenure</th><th>Submitted</th><th>Status</th><th></th></tr></thead><tbody>
  ${loans.map((l) => h`<tr><td>${l.loan_id}</td><td>${l.customer}<small> @${l.username}</small></td><td>${money(l.requested_amount)}</td>
    <td>${l.tenure_months ? `${l.tenure_months} mo` : '—'}</td><td>${App.formatDate(l.submitted_at || l.created_at)}</td><td>${badge(l.status)}</td>
    <td><button class="btn ${withCta ? 'btn-primary' : 'btn-secondary'}" type="button" data-loan="${l.loan_id}">${withCta ? 'Review' : 'View'}</button></td></tr>`)}</tbody></table>` : empty('Nothing here.'));

const loanList = (status, title) => async () => {
  const { loans } = await api.get('/admin/loans', { status });
  view.innerHTML = h`<section class="card"><h3>${title}</h3>${loanTable(loans, status === 'PENDING_REVIEW')}</section>`;
  view.querySelectorAll('[data-loan]').forEach((b) => { b.onclick = () => loanDetail(b.dataset.loan, status ? 'queue' : 'loans'); });
};

const loanDetail = async (id, back) => {
  const { loan: L } = await api.get(`/admin/loans/${id}`);
  const p = L.personal_details, i = L.income_details, g = L.guarantor;
  view.innerHTML = h`<p><button class="link-btn" id="back" type="button">← Back</button></p>
    <section class="card"><h3>Loan #${L.loan_id} ${badge(L.status)}</h3>
      ${kv([['Requested', money(L.requested_amount)], ['Tenure', L.tenure_months ? `${L.tenure_months} months` : null], ['Account', L.account_number],
        ['Approved amount', money(L.approved_amount)], ['Interest rate', L.interest_rate ? `${L.interest_rate} %` : null], ['EMI', money(L.emi_amount)]])}
      ${L.status === 'PENDING_REVIEW' ? h`<div class="decision">
        <input class="form-input" id="remarks" maxlength="255" placeholder="Remarks (optional)" aria-label="Remarks">
        <button class="btn btn-primary" type="button" data-d="AUTO">Run automatic review</button>
        <button class="btn btn-secondary" type="button" data-d="APPROVE">Approve</button>
        <button class="btn btn-danger" type="button" data-d="REJECT">Reject</button></div>` : ''}
      ${L.review.mode ? h`<p class="muted">Decision: ${L.review.mode}${L.review.remarks ? ` — ${L.review.remarks}` : ''}${L.review.rejection_codes.length ? ` (${L.review.rejection_codes.join(', ')})` : ''}</p>` : ''}</section>
    <div class="grid"><section class="card"><h3>Applicant</h3>${p ? kv([['Name', p.full_name], ['Phone', p.phone], ['Address', p.address], ['Date of birth', App.formatDate(p.date_of_birth)]]) : empty('Not provided')}</section>
    <section class="card"><h3>Income &amp; KYC</h3>${i ? kv([['PAN', i.pan_number], ['Aadhar', i.aadhar_number], ['Employment', i.employment_type], ['Monthly income', money(i.monthly_income)]]) : empty('Not provided')}</section>
    <section class="card"><h3>Guarantor</h3>${g ? kv([['Name', g.guarantor_name], ['Aadhar', g.guarantor_aadhar], ['Phone', g.guarantor_phone], ['Relationship', g.relationship]]) : empty('Not provided')}</section>
    <section class="card"><h3>Documents</h3>${L.documents.length ? h`<ul class="list">${L.documents.map((d) => h`<li><span>${d.document_type.replace('_', ' ')}<small>${d.original_filename}</small></span></li>`)}</ul>` : empty('None uploaded')}</section></div>`;
  $('back').onclick = () => show(back);
  view.querySelectorAll('[data-d]').forEach((b) => {
    b.onclick = () => busy(b, async () => {
      const body = { decision: b.dataset.d, remarks: $('remarks').value.trim() || undefined };
      await api.post(`/admin/loans/${id}/review`, body);
      App.toast(`Loan #${id}: ${b.dataset.d.toLowerCase()} decision recorded`, 'success');
      loanDetail(id, back);
    });
  });
};

/* ---------- customers / transactions ---------- */
const customers = async () => {
  const { customers: rows } = await api.get('/admin/customers');
  view.innerHTML = h`<section class="card"><h3>Customers</h3>${rows.length ? h`<table class="table"><thead><tr><th>Name</th><th>Username</th><th>Email</th><th>Phone</th><th>Account</th><th>Balance</th></tr></thead><tbody>
    ${rows.map((c) => h`<tr><td>${c.full_name}</td><td>${c.username}</td><td>${c.email}</td><td>${c.phone}</td><td>${c.account_number || '—'}</td><td>${money(c.balance)}</td></tr>`)}</tbody></table>` : empty('No customers.')}</section>`;
};

let txnFilter = '';
const txns = async () => {
  const { transactions: rows } = await api.get('/admin/transactions', { status: txnFilter });
  view.innerHTML = h`<section class="card"><h3>Recent transactions</h3>
    <div class="chips-row">${[['', 'All'], ['COMPLETED', 'Completed'], ['FAILED', 'Failed'], ['REVERSED', 'Reversed']].map(([v, t]) =>
      h`<button class="btn btn-secondary" type="button" data-f="${v}" aria-pressed="${v === txnFilter}">${t}</button>`)}</div>
    ${rows.length ? h`<table class="table"><thead><tr><th>When</th><th>Type</th><th>From</th><th>To</th><th>Amount</th><th>Status</th></tr></thead><tbody>
    ${rows.map((t) => h`<tr><td>${App.formatDateTime(t.created_at)}</td><td>${t.txn_type.replace('_', ' ')}</td><td>${t.from_account || '—'}</td><td>${t.to_account || '—'}</td>
      <td>${money(t.amount)}</td><td>${badge(t.status)}${t.failure_code ? h`<small> ${t.failure_code}</small>` : ''}</td></tr>`)}</tbody></table>` : empty('No transactions.')}</section>`;
  view.querySelectorAll('[data-f]').forEach((b) => { b.onclick = () => { txnFilter = b.dataset.f; show('txns'); }; });
};

/* ---------- testing tools ---------- */
const tools = async () => {
  const s = await api.get('/admin/simulation');
  view.innerHTML = h`<section class="card tools-card"><h3>Failure simulation</h3>
    <p class="muted">Injects fake network failures into money movements so rollback and retry behaviour can be tested. Applies to every customer while active.</p>
    ${s.tools_enabled ? h`<div class="row"><select class="form-select" id="mode" aria-label="Simulation mode">${s.modes.map((m) => h`<option>${m}</option>`)}</select>
      <input class="form-input" id="prob" aria-label="Failure probability (0.00 to 1.00)" placeholder="0.00–1.00" size="6" value="${s.probability}" hidden>
      <button class="btn btn-primary" id="apply" type="button">Apply</button></div>` : h`<p><b>Testing tools are disabled on this server</b> (DEBUG_TOOLS=0).</p>`}</section>
    <section class="card tools-card"><h3>Ledger</h3><div class="row"><button class="btn btn-secondary" id="verify" type="button">Verify ledger</button></div><ul class="list" id="violations"></ul></section>
    ${s.tools_enabled ? h`<section class="card tools-card"><h3>Reset data</h3><p class="muted">Wipes every table and restores the starting data: the demo customer and the officer account.</p>
      <button class="btn btn-danger" id="reset" type="button">Reset all data</button></section>` : ''}`;
  if (s.tools_enabled) {
    $('mode').value = s.mode;
    $('mode').onchange = () => { $('prob').hidden = $('mode').value !== 'RANDOM'; };
    $('mode').onchange();
    $('apply').onclick = () => busy($('apply'), async () => {
      const mode = $('mode').value;
      await api.put('/admin/simulation', mode === 'RANDOM' ? { mode, probability: $('prob').value } : { mode });
      App.toast(`Failure mode: ${mode}`, 'success');
    });
    $('reset').onclick = () => busy($('reset'), async () => {
      if (!(await App.confirm('Wipe ALL data and restore the starting data?'))) return;
      await api.post('/admin/reset');
      App.toast('Data reset', 'success');
      show('overview');
    });
  }
  $('verify').onclick = () => busy($('verify'), async () => {
    const r = await api.get('/admin/integrity');
    const bad = Object.entries(r.checks).flatMap(([k, c]) => c.violations.map((v) => `${k}: ${JSON.stringify(v)}`));
    $('violations').innerHTML = h`${bad.map((b) => h`<li class="viol">${b}</li>`)}`;
    App.toast(r.ok ? 'Ledger OK: all checks passed' : `Ledger check failed: ${bad.length} violation(s)`, r.ok ? 'success' : 'error');
  });
};

const PAGES = { overview, queue: loanList('PENDING_REVIEW', 'Loans awaiting review'), loans: loanList(undefined, 'All loans'), customers, txns, tools };
function show(tab) {
  document.querySelectorAll('[data-tab]').forEach((b) => { if (b.dataset.tab === tab) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
  view.innerHTML = h`<p class="empty-state"><span class="spinner"></span></p>`;
  PAGES[tab]().catch((e) => { if (e.code === 'FORBIDDEN') App.logout(); else { view.innerHTML = empty(e.message); fail(e); } });
}
if (App.isOfficer()) show('overview');
