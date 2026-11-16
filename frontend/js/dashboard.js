const { h, $, fail } = UI;
const BADGE = { FAILED: 'danger', REVERSED: 'warn' };
const SIGN = { OUT: '-', IN: '+' };

const txRow = (t) => h`<li>
  <div>${(t.direction === 'IN' ? t.from_name : t.to_name) || t.description || t.txn_type}<small>${App.formatDate(t.created_at)}</small></div>
  <div>${BADGE[t.status] ? h`<span class="badge badge-${BADGE[t.status]}">${t.status}</span> ` : ''}<b data-dir="${t.direction}">${SIGN[t.direction] || ''}${App.formatMoney(t.amount)}</b></div></li>`;

const paint = (d) => {
  const n = d.next_installment;
  $('promo').innerHTML = h`<h2>${d.promo.headline}</h2><p>${d.promo.subtext}</p>`;
  $('cards').innerHTML = h`
    <section class="card"><h3>Recent Transactions</h3>${d.recent_transactions.length
      ? h`<ul class="list">${d.recent_transactions.map(txRow)}</ul>` : h`<p class="empty-state">No transactions yet.</p>`}</section>
    <section class="card"><h3>Loans</h3>
      <p class="big">${d.active_loans} active</p>
      ${n ? h`<p>Next installment: <b>${App.formatMoney(n.emi_amount)}</b> due ${App.formatDate(n.due_date)}</p>` : h`<p class="muted">No upcoming installments.</p>`}</section>`;
};
App.renderShell('dashboard').then(paint).catch(fail);
