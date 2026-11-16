const { h, $, icon, field, submit } = UI;
if (App.getUserId()) location.replace(App.home());

$('page-content').innerHTML = h`
  <h2 class="brand">${icon('landmark', 28)}ABC Bank</h2>
  <div class="tabs" role="tablist">
    <button class="btn btn-secondary" role="tab" data-tab="login">Login</button>
    <button class="btn btn-secondary" role="tab" data-tab="register">Register</button>
  </div>
  <form id="login">${field('username', 'Username')}${field('password', 'Password', 'password')}
    <button class="btn btn-primary" type="submit">Log in</button></form>
  <form id="register" hidden>${field('username', 'Username')}${field('password', 'Password', 'password')}${field('full_name', 'Full name')}
    ${field('email', 'Email', 'email')}${field('phone', 'Phone')}${field('address', 'Address (optional)')}${field('date_of_birth', 'Date of birth (optional)', 'date')}
    <button class="btn btn-primary" type="submit">Create account</button></form>`;

document.querySelectorAll('[data-tab]').forEach((tab, _, all) => {
  tab.onclick = () => {
    all.forEach((t) => t.setAttribute('aria-selected', t === tab));
    document.querySelectorAll('form').forEach((f) => { f.hidden = f.id !== tab.dataset.tab; });
  };
});
document.querySelector('[data-tab]').click();

const enter = ({ user }) => {
  localStorage.setItem('abc_user_id', user.user_id);
  localStorage.setItem('abc_username', user.username);
  localStorage.setItem('abc_role', user.role || 'CUSTOMER');
  location.href = App.home();
};
submit($('login'), async (v) => enter(await api.post('/auth/login', v)));
// Register auto-logs-in; blank optional fields are omitted.
submit($('register'), async (v) => enter(await api.post('/auth/register', Object.fromEntries(Object.entries(v).filter(([, x]) => x !== '')))));
