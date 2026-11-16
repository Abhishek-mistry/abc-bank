const { h, $, busy, fail } = UI;
let page = 1, pages = 1;

const load = async () => {
  const d = await api.get('/notifications', { unread_only: $('unread').checked || '', page, page_size: 10 });
  pages = d.total_pages || 1;
  if (!d.items.length && page > 1) { page--; return load(); } // last item of a page was just read
  $('list').innerHTML = d.items.length
    ? h`${d.items.map((n) => h`<li class="${n.is_read ? '' : 'unread'}" data-id="${n.notification_id}"><div><b>${n.title}</b><p>${n.message}</p><small>${App.formatDateTime(n.created_at)}</small></div></li>`)}`
    : h`<li class="empty-state">No notifications.</li>`;
  $('pg').textContent = `Page ${page} of ${pages}`;
  $('prev').disabled = page <= 1;
  $('next').disabled = page >= pages;
};
const refresh = () => Promise.all([load(), App.refreshShell()]);

App.renderShell('notifications').then(load).catch(fail);
$('unread').onchange = () => { page = 1; load().catch(fail); };
$('prev').onclick = () => { page--; load().catch(fail); };
$('next').onclick = () => { page++; load().catch(fail); };
$('readall').onclick = () => busy($('readall'), async () => { await api.post('/notifications/read-all'); await refresh(); });
$('list').onclick = (e) => {
  const li = e.target.closest('li.unread');
  if (li) api.post(`/notifications/${li.dataset.id}/read`).then(refresh).catch(fail);
};
