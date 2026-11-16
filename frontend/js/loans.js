// My Loans (task 00do07). Built against structural_design.md v1.0 (§7.4, §11).
// Money values are strings; formatting only via App.formatMoney. No money arithmetic.
const { h, $, busy, fail, icon } = UI;

const CHIPS = [['', 'All'], ['DRAFT', 'Draft'], ['PENDING_REVIEW', 'Pending'], ['APPROVED', 'Approved'], ['ACTIVE', 'Active'], ['CLOSED', 'Closed'], ['REJECTED', 'Rejected'], ['CANCELLED', 'Cancelled']];
const STATUS = {
  DRAFT: ['Draft', ''], PENDING_REVIEW: ['Pending Review', 'warn'], APPROVED: ['Approved', 'success'], REJECTED: ['Rejected', 'danger'],
  CANCELLED: ['Cancelled', ''], ACTIVE: ['Active', 'success'], CLOSED: ['Closed', 'info'],
};
const RETRYABLE = ['SIMULATED_NETWORK_FAILURE', 'TXN_RETRY_EXHAUSTED', 'NETWORK_TIMEOUT', 'NETWORK_ERROR']; // §11.7: resending with the same key is safe
const badge = (s) => { const [t, tone] = STATUS[s] || [s, '']; return h`<span class="badge${tone ? ` badge-${tone}` : ''}">${t}</span>`; };
const pretty = (s) => { const t = String(s ?? '').replace(/_/g, ' ').toLowerCase(); return t.charAt(0).toUpperCase() + t.slice(1); };
const friendly = (e) => (e.code === 'FORBIDDEN' ? 'That loan belongs to another account.' : e.code === 'NOT_FOUND' ? 'That loan could not be found.' : e.message);
let filter = '';

/* ---------- list ---------- */
const action = (l) => (['DRAFT', 'PENDING_REVIEW', 'APPROVED'].includes(l.status)
  ? h`<a class="btn btn-secondary" href="take-loan.html?loan_id=${l.loan_id}">Continue</a><button class="btn btn-secondary" type="button" data-cancel="${l.loan_id}">Cancel</button>`
  : l.status === 'ACTIVE' ? h`<button class="btn btn-primary" type="button" data-open="${l.loan_id}">View schedule / Repay</button>`
    : l.status === 'CLOSED' ? h`<button class="btn btn-secondary" type="button" data-open="${l.loan_id}">View schedule</button>` : '');

const row = (l) => h`<tr><td>${pretty(l.loan_type)}<small>#${l.loan_id}</small></td>
  <td>${App.formatMoney(l.approved_amount ?? l.requested_amount)}</td>
  <td>${l.interest_rate ? `${l.interest_rate} %` : '—'}</td>
  <td>${l.emi_amount ? App.formatMoney(l.emi_amount) : '—'}</td>
  <td>${l.installments_total ? h`<progress class="loan-progress" value="${l.installments_paid}" max="${l.installments_total}"></progress><small>${l.installments_paid} / ${l.installments_total} paid</small>` : '—'}</td>
  <td>${App.formatDate(l.next_due_date)}</td><td>${badge(l.status)}</td><td class="cell-actions">${action(l)}</td></tr>`;

const paintChips = () => {
  $('chips').innerHTML = h`${CHIPS.map(([v, t]) => h`<button type="button" class="chip" data-status="${v}" aria-pressed="${v === filter ? 'true' : 'false'}">${t}</button>`)}`;
};
const load = async () => {
  const { loans } = await api.get('/loans', { status: filter });
  $('rows').innerHTML = loans.length ? h`${loans.map(row)}`
    : h`<tr><td colspan="8" class="empty-state">${filter ? 'No loans with this status.' : 'You have no loans yet.'} <a href="take-loan.html">Take a loan</a></td></tr>`;
};

/* ---------- detail modal ---------- */
const scheduleTable = (rows) => (rows.length ? h`<table class="table"><thead><tr><th>#</th><th>Due date</th><th>EMI</th><th>Principal</th><th>Interest</th><th>Balance</th><th>Status</th></tr></thead><tbody>${rows.map((r) => h`
  <tr class="${r.is_overdue ? 'overdue' : ''}"><td>${r.installment_no}</td><td>${App.formatDate(r.due_date)}</td><td>${App.formatMoney(r.emi_amount)}</td>
  <td>${App.formatMoney(r.principal_component)}</td><td>${App.formatMoney(r.interest_component)}</td><td>${App.formatMoney(r.balance_after)}</td>
  <td>${r.status === 'PAID' ? h`<span class="badge badge-success">Paid</span>` : r.is_overdue ? h`<span class="badge badge-danger">Overdue</span>` : h`<span class="badge">Pending</span>`}</td></tr>`)}</tbody></table>`
  : h`<p class="empty-state">No repayment schedule yet.</p>`);

const openDetail = async (id) => {
  let st;
  try {
    const [{ loan }, sched, { accounts }] = await Promise.all([api.get(`/loans/${id}`), api.get(`/loans/${id}/schedule`), api.get('/accounts')]);
    st = { loan, sched, accounts, flash: '' };
  } catch (e) { return App.toast(friendly(e), 'error'); }

  const m = Object.assign(document.createElement('div'), { className: 'modal-backdrop' });
  const q = (s) => m.querySelector(s);
  let key = App.uuid(); // one idempotency key per payment attempt; new after success or when the account changes

  const paint = () => {
    const { loan: L, sched: S, accounts: A } = st;
    const s = S.summary, next = S.schedule.find((i) => i.status === 'PENDING');
    m.innerHTML = h`<div class="modal loan-modal" role="dialog" aria-modal="true" aria-label="Loan details">
      <div class="loan-head"><h3>Loan #${L.loan_id} · ${pretty(L.loan_type)} ${badge(L.status)}</h3><button class="btn btn-secondary" type="button" data-close="1">Close</button></div>
      ${L.status === 'CLOSED' ? h`<div class="banner-ok">${icon('badge-check', 18)} Loan fully repaid</div>` : ''}
      ${st.flash ? h`<div class="banner-ok">${st.flash}</div>` : ''}
      <dl class="kv"><dt>Amount</dt><dd>${App.formatMoney(L.approved_amount ?? L.requested_amount)}</dd><dt>Interest rate</dt><dd>${L.interest_rate ? `${L.interest_rate} %` : '—'}</dd>
        <dt>Monthly EMI</dt><dd>${App.formatMoney(L.emi_amount)}</dd><dt>Tenure</dt><dd>${L.tenure_months} months</dd>
        <dt>Total interest</dt><dd>${App.formatMoney(L.total_interest)}</dd><dt>Total payable</dt><dd>${App.formatMoney(L.total_payable)}</dd>
        <dt>Progress</dt><dd>${s.paid_count} / ${s.total_count} paid</dd><dt>Outstanding principal</dt><dd>${App.formatMoney(s.outstanding_principal)}</dd>
        <dt>Total paid</dt><dd>${App.formatMoney(s.total_paid)}</dd><dt>Total remaining</dt><dd>${App.formatMoney(s.total_remaining)}</dd></dl>
      <h3>Repayment schedule</h3>${scheduleTable(S.schedule)}
      ${L.status === 'ACTIVE' && next ? h`<div class="pay-box"><div class="form-group"><label>Pay from account<select class="form-select" id="pay-account">
        <option value="">Loan account (${L.account_number})</option>${A.filter((a) => a.status === 'ACTIVE' && a.account_number !== L.account_number).map((a) =>
          h`<option value="${a.account_number}">${a.account_number} · ${App.formatMoney(a.balance)}</option>`)}</select></label></div>
        <button class="btn btn-primary" type="button" id="pay-btn" data-pay="1">Pay next installment (${App.formatMoney(next.emi_amount)})</button></div>` : ''}
      <div id="pay-out" aria-live="polite"></div></div>`;
    q('[data-close]').focus();
  };

  const refresh = async () => {
    const [{ loan }, sched] = await Promise.all([api.get(`/loans/${id}`), api.get(`/loans/${id}/schedule`)]);
    Object.assign(st, { loan, sched });
  };

  const pay = (btn) => btn.disabled ? undefined : busy(btn, async () => { // disabled = a payment is already in flight
    const out = q('#pay-out'), acct = q('#pay-account').value;
    out.innerHTML = '';
    try {
      const d = await Money.post(`/loans/${id}/repay`, { idempotency_key: key, ...(acct ? { account_number: acct } : {}) }, (msg) => { out.textContent = msg; });
      key = App.uuid();
      st.loan = d.loan;
      st.flash = d.idempotent_replay ? `Installment ${d.installment.installment_no} paid — confirmed, no duplicate charge.` : `Installment ${d.installment.installment_no} paid.`;
      App.toast(st.flash, 'success');
      try { await refresh(); } catch (e) { fail(e); } // the payment itself succeeded
      paint();
      App.refreshShell().catch(() => {});
      load().catch(fail);
    } catch (e) {
      out.innerHTML = h`<p class="form-error">${Money.explain(e)}</p>${RETRYABLE.includes(e.code)
        ? h`<button type="button" class="btn btn-secondary" data-retry="1">Retry</button>` : ''}`;
      if (e.code === 'INVALID_STATE') { await refresh().catch(() => {}); paint(); load().catch(fail); }
    }
  });

  const close = () => { m.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  m.onclick = (e) => {
    if (e.target === m || e.target.closest('[data-close]')) return close();
    if (e.target.closest('[data-pay]')) return pay(e.target.closest('[data-pay]'));
    if (e.target.dataset.retry) pay(q('#pay-btn') || e.target);
  };
  m.addEventListener('change', (e) => { if (e.target.id === 'pay-account') key = App.uuid(); });
  document.addEventListener('keydown', onKey);
  paint();
  document.body.append(m);
  q('[data-close]').focus();
};

/* ---------- wiring ---------- */
App.renderShell('loans').then(async () => { paintChips(); await load(); }).catch(fail);

$('chips').onclick = (e) => {
  const b = e.target.closest('[data-status]');
  if (!b) return;
  filter = b.dataset.status;
  paintChips();
  load().catch(fail);
};
$('rows').onclick = (e) => {
  const open = e.target.closest('[data-open]'), cancel = e.target.closest('[data-cancel]');
  if (open) openDetail(open.dataset.open);
  if (cancel && !cancel.disabled) busy(cancel, async () => {
    if (!(await App.confirm('Cancel this loan application? This cannot be undone.'))) return;
    try { await api.post(`/loans/${cancel.dataset.cancel}/cancel`); } catch (err) {
      if (err.code === 'INVALID_STATE' || err.code === 'FORBIDDEN' || err.code === 'NOT_FOUND') { App.toast(friendly(err), 'error'); return load(); }
      throw err;
    }
    App.toast('Application cancelled', 'success');
    await Promise.all([load(), App.refreshShell()]);
  });
};
