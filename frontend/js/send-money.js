const { h, $ } = UI;
let blocked = '', holder = '', timer;

Money.form({
  title: 'Send Money', button: 'Send', path: '/transactions/transfer', from: 'from_account_number', max: '200000.00',
  extra: h`<div class="form-group"><label>To account number<input class="form-input" name="to_account_number" inputmode="numeric" maxlength="12" autocomplete="off"></label>
    <small class="form-error" data-for="to_account_number"></small><small id="hint"></small></div>`,
  check: (v) => !/^\d{12}$/.test(v.to_account_number) ? { to_account_number: 'Enter a 12-digit account number.' }
    : v.to_account_number === v.from_account_number ? { to_account_number: 'Choose a different account than the sender.' }
    : blocked ? { to_account_number: blocked } : {},
  ask: (v) => `Send ${App.formatMoney(v.amount)} to ${holder ? `${holder} (${v.to_account_number})` : `account ${v.to_account_number}`}?`,
  done: (d) => h`<h3>Payment sent</h3><p><b>${App.formatMoney(d.transaction.amount)}</b> to ${d.transaction.to_name} · Ref ${Money.short(d.transaction.txn_ref)}</p>
    <p>New balance: <b>${App.formatMoney(d.from_account.balance)}</b></p>`,
});

// Recipient lookup: debounced while typing, immediate on blur.
const to = document.querySelector('[name=to_account_number]'), hint = $('hint');
const lookup = async () => {
  const n = to.value.trim();
  blocked = holder = ''; hint.textContent = '';
  if (!/^\d{12}$/.test(n)) return;
  try {
    const r = await api.get('/accounts/lookup', { account_number: n });
    if (to.value.trim() !== n) return; // stale response
    blocked = r.status === 'ACTIVE' ? '' : `This account is ${r.status.toLowerCase()} and cannot receive money.`;
    holder = r.holder_name;
    hint.className = blocked ? 'form-error' : 'ok';
    hint.textContent = blocked || r.holder_name;
  } catch (e) {
    if (to.value.trim() !== n) return;
    hint.className = 'form-error';
    hint.textContent = e.code === 'ACCOUNT_NOT_FOUND' ? 'Account not found' : e.message;
  }
};
to.addEventListener('input', () => { blocked = holder = ''; hint.textContent = ''; clearTimeout(timer); timer = setTimeout(lookup, 400); });
to.addEventListener('change', () => { clearTimeout(timer); lookup(); });
