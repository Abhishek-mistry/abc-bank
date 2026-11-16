const { h, $, busy, fail, field, submit } = UI;
const FIELDS = [['full_name', 'Full name'], ['email', 'Email', 'email'], ['phone', 'Phone', 'tel'], ['address', 'Address'], ['date_of_birth', 'Date of birth', 'date']];
const BADGE = { ACTIVE: 'success', FROZEN: 'warn', CLOSED: 'danger' };
const ACTIONS = { ACTIVE: [['Freeze', 'FROZEN'], ['Close', 'CLOSED']], FROZEN: [['Unfreeze', 'ACTIVE'], ['Close', 'CLOSED']], CLOSED: [] };

const loadAccounts = async () => {
  const { accounts } = await api.get('/accounts');
  $('accounts').innerHTML = h`${accounts.map((a) => h`<tr><td>${a.account_number}</td><td>${a.account_type}</td><td>${App.formatMoney(a.balance)}</td>
    <td><span class="badge badge-${BADGE[a.status]}">${a.status}</span></td>
    <td class="row">${ACTIONS[a.status].map(([label, to]) => h`<button class="btn btn-secondary" data-id="${a.account_id}" data-num="${a.account_number}" data-to="${to}">${label}</button>`)}</td></tr>`)}`;
};

App.renderShell('profile').then(() => Promise.all([
  api.get('/users/me').then(({ user }) => {
    $('profile').innerHTML = h`${FIELDS.map(([n, l, t]) => field(n, l, t, user[n]))}<button class="btn btn-primary" type="submit">Save changes</button>`;
  }),
  loadAccounts(),
])).catch(fail);

submit($('profile'), async (v) => { await api.put('/users/me', v); App.toast('Profile saved', 'success'); });
submit($('open'), async (v) => { await api.post('/accounts', v); App.toast('Account opened', 'success'); await loadAccounts(); });

$('accounts').onclick = (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  busy(b, async () => {
    const { id, num, to } = b.dataset;
    if (!(await App.confirm(`${b.textContent} account ${num}?`))) return;
    await api.patch(`/accounts/${id}/status`, { status: to });
    App.toast('Account updated', 'success');
    await Promise.all([loadAccounts(), App.refreshShell()]);
  });
};
