const { h } = UI;

Money.form({
  title: 'Deposit Money', button: 'Deposit', path: '/transactions/deposit', from: 'account_number', max: '100000.00',
  check: () => ({}),
  ask: (v) => `Deposit ${App.formatMoney(v.amount)} into account ${v.account_number}?`,
  done: (d) => h`<h3>Deposit complete</h3><p><b>${App.formatMoney(d.transaction.amount)}</b> · Ref ${Money.short(d.transaction.txn_ref)}</p>
    <p>New balance: <b>${App.formatMoney(d.account.balance)}</b></p>`,
});
