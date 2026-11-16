// Take-a-Loan wizard (task 00do07). Built against structural_design.md v1.0 (§7.4, §9, §11).
// Money is only ever a string; amount checks use BigInt cents, never floats.
const { h, $, busy, fail, submit, showErrors, icon } = UI;

/* ---------- constants (enum strings copied from §6 / §7.4 / §9) ---------- */
const STEPS = ['Select Type', 'Details', 'Documents', 'Apply', 'Approval'];
const STATUS = {
  DRAFT: ['Draft', ''], PENDING_REVIEW: ['Pending Review', 'warn'], APPROVED: ['Approved', 'success'], REJECTED: ['Rejected', 'danger'],
  CANCELLED: ['Cancelled', ''], ACTIVE: ['Active', 'success'], CLOSED: ['Closed', 'info'],
};
const DOC_LABEL = { INCOME_PROOF: 'Income proof', PAN_CARD: 'PAN card', AADHAR_CARD: 'Aadhar card' };
const REASONS = {
  LOW_INCOME: 'Your monthly income is below the minimum required for a personal loan.',
  EMI_TOO_HIGH: 'The monthly repayment would be more than half of your monthly income.',
  AMOUNT_EXCEEDS_LIMIT: 'The requested amount is more than 20 times your monthly income.',
  TOO_MANY_ACTIVE_LOANS: 'You already have two or more active loans.',
  GUARANTOR_SAME_AS_APPLICANT: 'The guarantor’s Aadhar number is the same as yours. A different person must act as guarantor.',
  MANUAL_REJECTION: 'The application was rejected by the loan officer.',
};
const DISCOUNTS = [['income_discount', 'Income discount'], ['guarantor_discount', 'Guarantor discount'], ['tenure_discount', 'Tenure discount'], ['loyalty_discount', 'Loyalty discount']];
const MISSING_LABEL = { details: 'Personal and loan details', income_details: 'Income details', guarantor: 'Guarantor details' };
const RETRYABLE = ['SIMULATED_NETWORK_FAILURE', 'TXN_RETRY_EXHAUSTED', 'NETWORK_TIMEOUT', 'NETWORK_ERROR']; // §11.7: same key is safe to resend
const INCOME_FIELDS = ['pan_number', 'aadhar_number', 'employment_type', 'monthly_income'];
const GUARANTOR_FIELDS = ['guarantor_name', 'guarantor_aadhar', 'guarantor_phone', 'relationship'];
const MASKED = ['aadhar_number', 'guarantor_aadhar'];

const missingText = (m) => MISSING_LABEL[m] || (m.startsWith('documents:') ? `${DOC_LABEL[m.slice(10)] || m.slice(10)} document` : m);
const missingStep = (m) => (m === 'details' ? 2 : m === 'guarantor' ? 4 : 3); // income_details + documents:* live on step 3

/* ---------- state ---------- */
const S = {
  cfg: null, user: null, accounts: [], loan: null, view: 1,
  vals: {},                         // every input's current text, so Back/Forward keeps what was typed
  dirty: { income: false, guarantor: false },
  uploading: {}, est: null, schedule: null, notice: null,
  acceptKey: null, accepted: false, newBalance: null, reviewing: false,
};

/* ---------- small helpers ---------- */
const badge = (s) => { const [t, tone] = STATUS[s] || [s, '']; return h`<span class="badge${tone ? ` badge-${tone}` : ''}">${t}</span>`; };
const pretty = (s) => { const t = String(s ?? '').replace(/_/g, ' ').toLowerCase(); return t.charAt(0).toUpperCase() + t.slice(1); };
const mask = (d) => (/^\d{12}$/.test(d || '') ? `**** **** ${d.slice(-4)}` : d || '');
// "100.5" -> 10050n (BigInt cents) or null when it is not a plain amount with <= 2 decimals.
const cents = (s) => (/^\d+(\.\d{1,2})?$/.test(s) ? BigInt(s.replace(/^(\d+)\.?(\d*)$/, (_, i, f) => i + f.padEnd(2, '0'))) : null);
const amountError = (v) => {
  const c = cents(v);
  return c === null || c < cents(S.cfg.min_amount) || c > cents(S.cfg.max_amount)
    ? `Enter an amount from ${App.formatMoney(S.cfg.min_amount)} to ${App.formatMoney(S.cfg.max_amount)}, with at most 2 decimals.` : '';
};
const val = (name, fallback) => (S.vals[name] ??= fallback ?? '');
const fld = (name, label, v, extra = h``) => h`<div class="form-group"><label>${label}<input class="form-input" name="${name}" value="${v}" ${extra}></label><small class="form-error" data-for="${name}"></small></div>`;
const sel = (name, label, options, selected, placeholder) => h`<div class="form-group"><label>${label}<select class="form-select" name="${name}">${placeholder ? h`<option value="">${placeholder}</option>` : ''}${options.map(([v, t]) =>
  h`<option value="${v}" ${String(v) === String(selected) ? h`selected` : ''}>${t}</option>`)}</select></label><small class="form-error" data-for="${name}"></small></div>`;
const docOf = (t) => S.loan.documents.find((d) => d.document_type === t);
const setLoan = (l) => { S.loan = l; };
const reload = async () => { setLoan((await api.get(`/loans/${S.loan.loan_id}`)).loan); };
const editable = () => !S.loan || S.loan.status === 'DRAFT';

// submit() wrapper: server field errors that have no input on this form are appended to the toast text.
const send = (form, fn) => submit(form, async (raw) => {
  try { await fn(raw); } catch (e) {
    const known = new Set([...form.querySelectorAll('[data-for]')].map((x) => x.dataset.for));
    const extra = Object.entries(e.details?.fields || {}).filter(([k]) => !known.has(k)).map(([k, m]) => `${k}: ${m}`);
    if (extra.length) e.message = `${e.message} (${extra.join('; ')})`;
    throw e;
  }
});
const trimmed = (raw) => Object.fromEntries(Object.entries(raw).map(([k, x]) => [k, String(x).trim()]));

/* ---------- read-only summary + schedule table ---------- */
const kv = (rows) => h`<dl class="kv">${rows.map(([k, v]) => h`<dt>${k}</dt><dd>${v}</dd>`)}</dl>`;
const summary = (L) => {
  const p = L.personal_details, i = L.income_details, g = L.guarantor;
  return h`${kv([
    ['Loan type', pretty(L.loan_type)], ['Disbursement account', L.account_number],
    ['Requested amount', App.formatMoney(L.requested_amount)], ['Tenure', L.tenure_months ? `${L.tenure_months} months` : '—'],
    ['Full name', p?.full_name ?? '—'], ['Phone', p?.phone ?? '—'], ['Address', p?.address ?? '—'], ['Date of birth', App.formatDate(p?.date_of_birth)],
    ['PAN', i?.pan_number ?? '—'], ['Aadhar', i ? mask(i.aadhar_number) : '—'], ['Employment', i ? pretty(i.employment_type) : '—'],
    ['Monthly income', i ? App.formatMoney(i.monthly_income) : '—'],
    ['Documents', L.documents.length ? L.documents.map((d) => `${DOC_LABEL[d.document_type] || d.document_type}: ${d.original_filename}`).join(' · ') : '—'],
    ['Guarantor', g?.guarantor_name ?? '—'], ['Guarantor Aadhar', g ? mask(g.guarantor_aadhar) : '—'],
    ['Guarantor phone', g?.guarantor_phone || '—'], ['Relationship', g ? pretty(g.relationship) : '—'],
  ])}`;
};
const scheduleTable = (rows) => h`<table class="table"><thead><tr><th>#</th><th>Due date</th><th>EMI</th><th>Principal</th><th>Interest</th><th>Balance</th><th>Status</th></tr></thead><tbody>${rows.map((r) => h`
  <tr class="${r.is_overdue ? 'overdue' : ''}"><td>${r.installment_no}</td><td>${App.formatDate(r.due_date)}</td><td>${App.formatMoney(r.emi_amount)}</td>
  <td>${App.formatMoney(r.principal_component)}</td><td>${App.formatMoney(r.interest_component)}</td><td>${App.formatMoney(r.balance_after)}</td>
  <td>${r.status === 'PAID' ? h`<span class="badge badge-success">Paid</span>` : r.is_overdue ? h`<span class="badge badge-danger">Overdue</span>` : h`<span class="badge">Pending</span>`}</td></tr>`)}</tbody></table>`;

/* ---------- stepper + approval panel ---------- */
const maxReach = () => (S.loan ? (S.loan.status === 'DRAFT' ? S.loan.current_step : 5) : 1);
const canGo = (n) => editable() && n !== S.view && n <= maxReach();
const renderStepper = () => {
  const ended = ['ACTIVE', 'CLOSED'].includes(S.loan?.status);
  $('stepper').innerHTML = h`${STEPS.map((t, i) => {
    const n = i + 1;
    const cls = [n === S.view ? 'active' : '', n < S.view || (n === 5 && ended) ? 'done' : '', canGo(n) ? 'go' : ''].join(' ').trim();
    return h`<li class="stepper-step ${cls}" data-step="${n}" ${n === S.view ? h`aria-current="step"` : ''}>${t}</li>`;
  })}`;
};

let estTimer = null, estSeq = 0;
const runEstimate = async () => {
  const amount = (S.vals.requested_amount || '').trim(), tenure = S.vals.tenure_months, seq = ++estSeq;
  if (!S.cfg || amountError(amount) || !tenure) { S.est = null; return renderPanel(); }
  try {
    const e = await api.get('/loans/estimate', { amount, tenure_months: tenure, rate: S.cfg.base_rate });
    if (seq === estSeq) { S.est = e; renderPanel(); }
  } catch { if (seq === estSeq) { S.est = null; renderPanel(); } }
};
const scheduleEstimate = (now) => { clearTimeout(estTimer); estTimer = setTimeout(runEstimate, now ? 0 : 400); };
const seedEstimate = () => {
  const L = S.loan;
  if (L?.requested_amount && L.tenure_months) { S.vals.requested_amount ??= L.requested_amount; S.vals.tenure_months ??= String(L.tenure_months); }
  if (S.vals.requested_amount) runEstimate();
};

const renderPanel = () => {
  const L = S.loan, st = L?.status, c = S.cfg;
  const final = ['APPROVED', 'ACTIVE', 'CLOSED'].includes(st);
  const open = !L || st === 'DRAFT' || st === 'PENDING_REVIEW';
  const tenure = open ? S.vals.tenure_months || L?.tenure_months : L?.tenure_months;
  const range = `${c.best_rate} %–${c.base_rate} %`;
  const rate = final ? h`<b>${L.interest_rate} %</b>` : h`<b>${open ? range : '—'}</b>${open ? h`<small>Final rate ${range} decided at approval</small>` : ''}`;
  const emi = final ? h`<b>${App.formatMoney(L.emi_amount)}</b>`
    : open && S.est ? h`<b>${App.formatMoney(S.est.emi_amount)}</b><small>Estimated EMI (indicative @ ${c.base_rate} %)</small><small>Final rate ${range} decided at approval</small>`
      : h`<b>—</b>${open ? h`<small>Enter a valid amount and tenure to see an estimate.</small>` : ''}`;
  $('panel').innerHTML = h`<h3>Approval</h3>
    <div class="panel-item"><span>Approval Status</span>${L ? badge(st) : h`<span class="badge">Not started</span>`}</div>
    <div class="panel-item"><span>Interest Rate</span>${rate}</div>
    <div class="panel-item"><span>Estimated Monthly Repayment</span>${emi}</div>
    <div class="panel-item"><span>Repayment Schedule</span><b>${tenure ? `${tenure} months` : '—'}</b></div>`;
};

/* ---------- navigation ---------- */
const render = () => {
  renderStepper();
  renderPanel();
  $('notice').innerHTML = S.notice ? h`<section class="card notice"><b>Please complete the following before submitting:</b><ul>${S.notice.map((x) => h`<li>${x}</li>`)}</ul></section>` : '';
  S.notice = null;
  [null, step1, step2, step3, step4, step5][S.view]();
};
const go = (n) => { S.view = n; render(); $('stepper').scrollIntoView?.({ block: 'nearest' }); };

/* ---------- step 1: select type ---------- */
const step1 = () => {
  const L = S.loan, active = S.accounts.filter((a) => a.status === 'ACTIVE');
  const firstOn = S.cfg.loan_types.find((t) => t.enabled)?.code;
  $('wizard').innerHTML = h`<form class="card" id="f1" novalidate><h3>Select loan type</h3>
    <div class="form-group"><label>Loan type<select class="form-select" name="loan_type" ${L ? h`disabled` : ''}>${S.cfg.loan_types.map((t) =>
      h`<option value="${t.code}" ${t.enabled ? '' : h`disabled`} ${t.code === (L?.loan_type || firstOn) ? h`selected` : ''}>${t.label}${t.enabled ? '' : ' (Coming soon)'}</option>`)}</select></label><small class="form-error" data-for="loan_type"></small></div>
    <div class="form-group"><label>Disbursement account<select class="form-select" name="account_number" ${L ? h`disabled` : ''}>${L
      ? h`<option>${L.account_number}</option>`
      : active.length ? h`${active.map((a) => h`<option value="${a.account_number}">${a.account_number} · ${App.formatMoney(a.balance)}</option>`)}` : h`<option value="">No active account</option>`}</select></label>
      <small class="form-error" data-for="account_number">${!L && !active.length ? 'You need an active account to take a loan.' : ''}</small></div>
    <div class="step-actions"><span></span><button class="btn btn-primary" type="submit" ${!L && !active.length ? h`disabled` : ''}>Continue</button></div></form>`;
  send($('f1'), async (raw) => {
    if (L) return go(Math.max(2, L.current_step));
    if (!raw.account_number) return showErrors($('f1'), { account_number: 'Choose an active account.' });
    const d = await api.post('/loans', { loan_type: raw.loan_type, account_number: raw.account_number });
    setLoan(d.loan);
    history.replaceState(null, '', `?loan_id=${d.loan.loan_id}`);
    go(d.loan.current_step);
  });
};

/* ---------- step 2: details ---------- */
const step2 = () => {
  const L = S.loan, pd = L.personal_details, u = S.user;
  $('wizard').innerHTML = h`<form class="card" id="f2" novalidate><h3>Personal Details</h3><div class="form-cols">
    ${fld('full_name', 'Full name', val('full_name', pd?.full_name ?? u.full_name), h`maxlength="100" autocomplete="name"`)}
    ${fld('phone', 'Phone number', val('phone', pd?.phone ?? u.phone), h`inputmode="tel" data-digits="15" autocomplete="tel"`)}
    ${fld('address', 'Current address', val('address', pd?.address ?? u.address), h`maxlength="255" autocomplete="street-address"`)}
    ${fld('date_of_birth', 'Date of birth', val('date_of_birth', pd?.date_of_birth ?? u.date_of_birth), h`type="date"`)}</div>
    <h3>Loan Details</h3><div class="form-cols">
    ${fld('requested_amount', 'Requested loan amount (₹)', val('requested_amount', L.requested_amount), h`inputmode="decimal" autocomplete="off"`)}
    ${sel('tenure_months', 'Tenure', S.cfg.tenure_options.map((n) => [n, `${n} months`]), val('tenure_months', String(L.tenure_months || (S.cfg.tenure_options.includes(12) ? 12 : S.cfg.tenure_options[0]))))}</div>
    <div class="step-actions"><button class="btn btn-secondary" type="button" id="back2">Back</button><button class="btn btn-primary" type="submit">Continue</button></div></form>`;
  scheduleEstimate(true);
  $('back2').onclick = () => go(1);
  send($('f2'), async (raw) => {
    const v = trimmed(raw);
    Object.assign(S.vals, v);
    const errs = {};
    if (!v.full_name || v.full_name.length > 100) errs.full_name = 'Enter your full name (up to 100 characters).';
    if (!/^\d{10,15}$/.test(v.phone)) errs.phone = 'Phone must be 10 to 15 digits.';
    if (!v.address || v.address.length > 255) errs.address = 'Enter your current address (up to 255 characters).';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v.date_of_birth)) errs.date_of_birth = 'Enter your date of birth.';
    const ae = amountError(v.requested_amount);
    if (ae) errs.requested_amount = ae;
    if (!S.cfg.tenure_options.map(String).includes(v.tenure_months)) errs.tenure_months = 'Choose a tenure.';
    if (Object.keys(errs).length) return showErrors($('f2'), errs);
    const d = await api.put(`/loans/${L.loan_id}/details`, {
      full_name: v.full_name, phone: v.phone, address: v.address, date_of_birth: v.date_of_birth,
      requested_amount: v.requested_amount, tenure_months: parseInt(v.tenure_months, 10), // tenure is a small integer, not money
    });
    setLoan(d.loan);
    go(3);
  });
};

/* ---------- step 3: income + documents ---------- */
const step3Ready = () => !!S.loan.income_details && !S.dirty.income && S.cfg.document_types.every((t) => docOf(t));
const refreshNext3 = () => { if ($('next3')) $('next3').disabled = !step3Ready(); };
const fileError = (f) => {
  if (!S.cfg.allowed_mime_types.includes(f.type)) return 'Only PDF, PNG or JPEG files are allowed.';
  if (f.size === 0) return 'This file is empty.';
  if (f.size > S.cfg.max_upload_bytes) return `File is too large (maximum ${Math.round(S.cfg.max_upload_bytes / 1048576)} MB).`;
  return '';
};
const step3 = () => {
  const L = S.loan, inc = L.income_details;
  const acceptAttr = `${S.cfg.allowed_mime_types.join(',')},.pdf,.png,.jpg,.jpeg`;
  $('wizard').innerHTML = h`<form class="card" id="f3" novalidate><h3>Income Details</h3><div class="form-cols">
    ${fld('pan_number', 'PAN number', val('pan_number', inc?.pan_number), h`maxlength="10" autocapitalize="characters" autocomplete="off" spellcheck="false"`)}
    ${fld('aadhar_number', 'Aadhar number', mask(val('aadhar_number', inc?.aadhar_number)), h`data-mask="1" data-digits="12" inputmode="numeric" autocomplete="off"`)}
    ${sel('employment_type', 'Employment type', S.cfg.employment_types.map((t) => [t, pretty(t)]), val('employment_type', inc?.employment_type), 'Select…')}
    ${fld('monthly_income', 'Monthly income (₹)', val('monthly_income', inc?.monthly_income), h`inputmode="decimal" autocomplete="off"`)}</div>
    <button class="btn btn-secondary" type="submit">Save income details</button> ${inc && !S.dirty.income ? h`<span class="doc-ok">${icon('circle-check', 16)} Saved</span>` : ''}</form>
    <section class="card"><h3>Upload Income Documents</h3><p><small>PDF, PNG or JPEG, up to ${Math.round(S.cfg.max_upload_bytes / 1048576)} MB each. Choosing a file again replaces the old one.</small></p>
    ${S.cfg.document_types.map((t) => { const d = docOf(t); return h`<div class="doc-item"><div><b>${icon('file-text', 16)} ${DOC_LABEL[t] || t}</b>
      <div>${S.uploading[t] ? h`<small>Uploading…</small>` : d ? h`<span class="doc-ok">${icon('circle-check', 16)} ${d.original_filename}</span>` : h`<small>Not uploaded</small>`}</div>
      <small class="form-error" data-for="doc_${t}"></small></div>
      <input type="file" data-doc="${t}" accept="${acceptAttr}" aria-label="${d ? 'Replace' : 'Upload'} ${DOC_LABEL[t] || t}" ${S.uploading[t] ? h`disabled` : ''}></div>`; })}</section>
    <div class="step-actions"><button class="btn btn-secondary" type="button" id="back3">Back</button>
    <small id="hint3">Save your income details and upload all documents to continue.</small>
    <button class="btn btn-primary" type="button" id="next3" disabled>Continue</button></div>`;
  refreshNext3();
  $('back3').onclick = () => go(2);
  $('next3').onclick = () => { if (step3Ready()) go(4); };
  send($('f3'), async () => {
    const v = { ...trimmed(Object.fromEntries(new FormData($('f3')))), aadhar_number: S.vals.aadhar_number || '' };
    Object.assign(S.vals, v);
    const errs = {};
    if (!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(v.pan_number)) errs.pan_number = 'PAN must look like ABCDE1234F.';
    if (!/^\d{12}$/.test(v.aadhar_number)) errs.aadhar_number = 'Aadhar must be exactly 12 digits.';
    if (!S.cfg.employment_types.includes(v.employment_type)) errs.employment_type = 'Choose your employment type.';
    const c = cents(v.monthly_income);
    if (c === null || c <= 0n) errs.monthly_income = 'Enter your monthly income, with at most 2 decimals.';
    if (Object.keys(errs).length) return showErrors($('f3'), errs);
    const d = await api.put(`/loans/${L.loan_id}/income-details`, { pan_number: v.pan_number, aadhar_number: v.aadhar_number, employment_type: v.employment_type, monthly_income: v.monthly_income });
    setLoan(d.loan);
    S.dirty.income = false;
    App.toast('Income details saved', 'success');
    step3();
  });
};
const upload = async (input) => {
  const type = input.dataset.doc, file = input.files[0], slot = document.querySelector(`[data-for="doc_${type}"]`);
  if (!file || S.uploading[type]) return;
  const err = fileError(file);
  if (slot) slot.textContent = err;
  if (err) { input.value = ''; return; }
  S.uploading[type] = true;
  step3();
  try {
    const fd = new FormData();
    fd.append('document_type', type);
    fd.append('file', file);
    setLoan((await api.upload(`/loans/${S.loan.loan_id}/documents`, fd)).loan);
    App.toast(`${DOC_LABEL[type] || type} uploaded`, 'success');
  } catch (e) {
    fail(e);
    S.uploadError = { type, message: e.details?.fields?.file || e.details?.fields?.document_type || e.message };
  } finally {
    S.uploading[type] = false;
    if (S.view === 3) {
      step3();
      if (S.uploadError) { const s = document.querySelector(`[data-for="doc_${S.uploadError.type}"]`); if (s) s.textContent = S.uploadError.message; S.uploadError = null; }
    }
  }
};

/* ---------- step 4: guarantor + review + submit ---------- */
const step4 = () => {
  const L = S.loan, g = L.guarantor, saved = !!g && !S.dirty.guarantor;
  $('wizard').innerHTML = h`<form class="card" id="f4" novalidate><h3>Guarantor Details</h3><div class="form-cols">
    ${fld('guarantor_name', 'Guarantor name', val('guarantor_name', g?.guarantor_name), h`maxlength="100" autocomplete="off"`)}
    ${fld('guarantor_aadhar', 'Guarantor Aadhar', mask(val('guarantor_aadhar', g?.guarantor_aadhar)), h`data-mask="1" data-digits="12" inputmode="numeric" autocomplete="off"`)}
    ${fld('guarantor_phone', 'Guarantor phone (optional)', val('guarantor_phone', g?.guarantor_phone), h`inputmode="tel" data-digits="15" autocomplete="off"`)}
    ${sel('relationship', 'Relationship', S.cfg.relationships.map((r) => [r, pretty(r)]), val('relationship', g?.relationship), 'Select…')}</div>
    <button class="btn btn-secondary" type="submit">Save guarantor</button> ${saved ? h`<span class="doc-ok">${icon('circle-check', 16)} Saved</span>` : ''}</form>
    ${saved ? h`<section class="card"><h3>Review your application</h3>${summary(L)}
      <label><input type="checkbox" id="confirm"> I confirm the details are correct</label>
      <div class="step-actions"><button class="btn btn-secondary" type="button" id="back4">Back</button>
      <button class="btn btn-primary" type="button" id="submit-app" disabled>Submit Application</button></div></section>`
    : h`<div class="step-actions"><button class="btn btn-secondary" type="button" id="back4">Back</button><small>Save the guarantor details to review and submit.</small></div>`}`;
  $('back4').onclick = () => go(3);
  send($('f4'), async () => {
    const v = { ...trimmed(Object.fromEntries(new FormData($('f4')))), guarantor_aadhar: S.vals.guarantor_aadhar || '' };
    Object.assign(S.vals, v);
    const errs = {};
    if (!v.guarantor_name || v.guarantor_name.length > 100) errs.guarantor_name = 'Enter the guarantor’s name.';
    if (!/^\d{12}$/.test(v.guarantor_aadhar)) errs.guarantor_aadhar = 'Aadhar must be exactly 12 digits.';
    if (v.guarantor_phone && !/^\d{10,15}$/.test(v.guarantor_phone)) errs.guarantor_phone = 'Phone must be 10 to 15 digits.';
    if (!S.cfg.relationships.includes(v.relationship)) errs.relationship = 'Choose the relationship.';
    if (Object.keys(errs).length) return showErrors($('f4'), errs);
    const body = { guarantor_name: v.guarantor_name, guarantor_aadhar: v.guarantor_aadhar, relationship: v.relationship };
    if (v.guarantor_phone) body.guarantor_phone = v.guarantor_phone;
    setLoan((await api.put(`/loans/${L.loan_id}/guarantor`, body)).loan);
    S.dirty.guarantor = false;
    App.toast('Guarantor saved', 'success');
    step4();
  });
  if (saved) {
    $('confirm').onchange = () => { $('submit-app').disabled = !$('confirm').checked; };
    $('submit-app').onclick = (ev) => ev.currentTarget.disabled ? undefined : busy(ev.currentTarget, async () => {
      try {
        setLoan((await api.post(`/loans/${L.loan_id}/submit`)).loan);
      } catch (e) {
        if (e.code === 'LOAN_INCOMPLETE') return incomplete(e);
        if (e.code === 'INVALID_STATE') { await reload(); App.toast(e.message, 'error'); return go(S.loan.status === 'DRAFT' ? S.loan.current_step : 5); }
        throw e;
      }
      App.refreshShell().catch(() => {});
      go(5);
    });
  }
};
const incomplete = async (e) => {
  const missing = e.details?.missing || [];
  await reload();
  S.notice = missing.length ? missing.map(missingText) : ['Some required parts are missing.'];
  go(missing.length ? Math.min(...missing.map(missingStep)) : Math.max(2, S.loan.current_step));
};

/* ---------- step 5: approval ---------- */
const summaryCard = (L) => h`<details class="card"><summary>Application summary</summary>${summary(L)}</details>`;
const refreshStatus = async (btn) => btn.disabled ? undefined : busy(btn, async () => {
  await reload();
  App.refreshShell().catch(() => {});
  render();
  if (S.loan.status === 'PENDING_REVIEW') App.toast('Still under review', 'info');
});
const accept = (btn) => btn.disabled ? undefined : busy(btn, async () => { // disabled = an accept is already in flight
  const L = S.loan, out = $('out');
  S.acceptKey ||= App.uuid(); // one key per accept attempt; reused by Retry, dropped on success
  out.innerHTML = '';
  try {
    const d = await Money.post(`/loans/${L.loan_id}/accept`, { idempotency_key: S.acceptKey }, (m) => { out.textContent = m; });
    S.acceptKey = null;
    setLoan(d.loan);
    S.schedule = d.schedule;
    S.accepted = true;
    try {
      const [{ accounts }] = await Promise.all([api.get('/accounts'), App.refreshShell()]);
      S.accounts = accounts;
      S.newBalance = accounts.find((a) => a.account_number === d.loan.account_number)?.balance ?? null;
    } catch { S.newBalance = null; } // the loan is already disbursed: a refresh problem must not look like a failure
    render();
  } catch (e) {
    if (e.code === 'INVALID_STATE') { await reload().catch(() => {}); App.toast(e.message, 'error'); return render(); }
    out.innerHTML = h`<p class="form-error">${Money.explain(e)}</p>${RETRYABLE.includes(e.code)
      ? h`<button type="button" class="btn btn-secondary" data-retry="1">Retry</button>` : ''}`;
  }
});
const cancelLoan = (btn) => btn.disabled ? undefined : busy(btn, async () => {
  if (!(await App.confirm('Cancel this loan application? This cannot be undone.'))) return;
  setLoan((await api.post(`/loans/${S.loan.loan_id}/cancel`)).loan);
  App.toast('Application cancelled', 'success');
  App.refreshShell().catch(() => {});
  render();
});
const newApplication = () => { location.href = 'take-loan.html'; };

const step5 = () => {
  const L = S.loan, st = L.status, w = $('wizard');
  if (st === 'PENDING_REVIEW') {
    w.innerHTML = h`<section class="card"><h3>Application submitted</h3><p>Status: ${badge(st)} — your application is waiting for the loan officer. You will get a notification as soon as a decision is made.</p>
      <div class="step-actions"><button class="btn btn-danger" type="button" id="cancel-app">Cancel Application</button>
      <button class="btn btn-secondary" type="button" id="refresh-status">Check status</button></div></section>${summaryCard(L)}`;
    $('refresh-status').onclick = (ev) => refreshStatus(ev.currentTarget);
    $('cancel-app').onclick = (ev) => cancelLoan(ev.currentTarget);
  } else if (st === 'APPROVED') {
    const rb = L.review?.rate_breakdown;
    w.innerHTML = h`<section class="card"><h3>Your loan is approved</h3><p>${badge(st)}</p>
      ${kv([['Approved amount', App.formatMoney(L.approved_amount)], ['Interest rate', `${L.interest_rate} %`], ['Monthly EMI', App.formatMoney(L.emi_amount)],
        ['Total interest', App.formatMoney(L.total_interest)], ['Total payable', App.formatMoney(L.total_payable)], ['Tenure', `${L.tenure_months} months`], ['Credited to account', L.account_number]])}
      ${rb ? h`<h3>How your rate was decided</h3><table class="table"><tbody><tr><td>Base rate</td><td>${rb.base} %</td></tr>${DISCOUNTS.map(([k, t]) =>
        h`<tr><td>${t}</td><td>${rb[k] === '0.00' ? '' : '− '}${rb[k]} %</td></tr>`)}<tr><td><b>Final rate</b></td><td><b>${rb.final_rate} %</b></td></tr></tbody></table>` : ''}
      <div class="step-actions"><button class="btn btn-danger" type="button" id="cancel-app">Cancel Application</button>
      <button class="btn btn-primary" type="button" id="accept">Accept &amp; Disburse</button></div><div id="out" aria-live="polite"></div></section>${summaryCard(L)}`;
    $('accept').onclick = (ev) => accept(ev.currentTarget);
    $('cancel-app').onclick = (ev) => cancelLoan(ev.currentTarget);
    $('out').onclick = (ev) => { if (ev.target.dataset.retry) accept($('accept')); };
  } else if (st === 'REJECTED') {
    const codes = L.review?.rejection_codes || [];
    w.innerHTML = h`<section class="card"><h3>Application not approved</h3><p>${badge(st)}</p>
      ${codes.length ? h`<p>Reasons:</p><ul class="reason-list">${codes.map((c) => h`<li>${REASONS[c] || c}</li>`)}</ul>` : ''}
      ${L.review?.remarks ? h`<p><b>Officer remarks:</b> ${L.review.remarks}</p>` : ''}
      <button class="btn btn-primary" type="button" id="new-app">Start a new application</button></section>${summaryCard(L)}`;
    $('new-app').onclick = newApplication;
  } else if (st === 'CANCELLED') {
    w.innerHTML = h`<section class="card"><h3>Application cancelled</h3><p>${badge(st)}</p><button class="btn btn-primary" type="button" id="new-app">Start a new application</button></section>${summaryCard(L)}`;
    $('new-app').onclick = newApplication;
  } else { // ACTIVE / CLOSED
    const title = S.accepted ? 'Loan disbursed' : st === 'CLOSED' ? 'Loan closed' : 'Loan is active';
    w.innerHTML = h`<section class="card"><h3>${title}</h3><p>${badge(st)}</p>
      ${S.accepted ? h`<div class="banner-ok">${App.formatMoney(L.approved_amount)} has been credited to account ${L.account_number}.${S.newBalance ? ` New balance: ${App.formatMoney(S.newBalance)}` : ''}</div>` : ''}
      ${kv([['Interest rate', `${L.interest_rate} %`], ['Monthly EMI', App.formatMoney(L.emi_amount)], ['Total interest', App.formatMoney(L.total_interest)], ['Total payable', App.formatMoney(L.total_payable)]])}
      <h3>Repayment schedule</h3><div id="sched"><p class="empty-state"><span class="spinner"></span></p></div>
      <a class="btn btn-primary" href="loans.html">Go to My Loans</a></section>`;
    const paint = () => { if ($('sched')) $('sched').innerHTML = scheduleTable(S.schedule); };
    if (S.schedule) paint();
    else api.get(`/loans/${L.loan_id}/schedule`).then((d) => { S.schedule = d.schedule; paint(); }).catch(fail);
  }
};

/* ---------- wiring ---------- */
const problem = (msg) => {
  $('stepper').hidden = true;
  $('panel').hidden = true;
  $('wizard').innerHTML = h`<section class="card"><p class="form-error">${msg}</p><a class="btn btn-secondary" href="loans.html">Back to My Loans</a></section>`;
};
const init = async () => {
  const id = new URLSearchParams(location.search).get('loan_id');
  const [cfg, { user }, { accounts }] = await Promise.all([api.get('/loans/config'), api.get('/users/me'), api.get('/accounts')]);
  Object.assign(S, { cfg, user, accounts });
  if (id !== null) {
    if (!/^\d+$/.test(id)) return problem('That loan link is not valid.');
    try { setLoan((await api.get(`/loans/${id}`)).loan); } catch (e) {
      return problem(e.code === 'FORBIDDEN' ? 'This application belongs to another account.' : e.code === 'NOT_FOUND' ? 'We couldn’t find that loan application.' : e.message);
    }
    seedEstimate();
    S.view = S.loan.status === 'DRAFT' ? S.loan.current_step : 5;
  }
  render();
};

const onEdit = (e) => {
  const t = e.target;
  if (!t.name) return;
  if (t.name === 'pan_number') t.value = t.value.toUpperCase();
  if (t.dataset.digits) t.value = t.value.replace(/\D/g, '').slice(0, parseInt(t.dataset.digits, 10));
  S.vals[t.name] = t.value;
  if (S.view === 2 && (t.name === 'requested_amount' || t.name === 'tenure_months')) scheduleEstimate(false);
  if (S.view === 3 && INCOME_FIELDS.includes(t.name)) { S.dirty.income = true; refreshNext3(); }
  if (S.view === 4 && GUARANTOR_FIELDS.includes(t.name) && !S.dirty.guarantor) { S.dirty.guarantor = true; step4Dirty(); }
};
// Editing the guarantor invalidates the saved copy: hide the review/submit block until saved again.
const step4Dirty = () => {
  $('wizard').querySelector('#confirm')?.closest('section')?.remove();
  $('wizard').querySelector('#f4 .doc-ok')?.remove();
};

App.renderShell('loans').then(() => {
  const w = $('wizard');
  w.addEventListener('input', onEdit);
  w.addEventListener('change', (e) => { if (e.target.dataset?.doc) upload(e.target); else onEdit(e); });
  w.addEventListener('focusin', (e) => { if (e.target.dataset?.mask) e.target.value = S.vals[e.target.name] || ''; });
  w.addEventListener('focusout', (e) => { if (e.target.dataset?.mask) e.target.value = mask(S.vals[e.target.name] || ''); });
  $('stepper').onclick = (e) => {
    const li = e.target.closest('[data-step]'), n = li ? parseInt(li.dataset.step, 10) : 0;
    if (n && canGo(n)) go(n);
  };
  return init();
}).catch(fail);
