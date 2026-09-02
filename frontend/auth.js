(() => {
  document.body.insertAdjacentHTML('afterbegin', `
<div class="sx-auth-gate" id="authGate" aria-live="polite">
  <section class="sx-auth-card" role="dialog" aria-modal="true" aria-labelledby="authTitle">
    <div class="sx-auth-brand">Scarlet<b>X</b></div>
    <h1 id="authTitle">Checking security…</h1>
    <p id="authSubtitle">Verifying the local ScarletX administrator session.</p>
    <form id="authForm" hidden>
      <div class="sx-auth-fields">
        <div class="sx-auth-field"><label for="authUsername">Username</label><input id="authUsername" name="username" autocomplete="username" maxlength="100" required></div>
        <div class="sx-auth-field" id="authSetupTokenField" hidden><label for="authSetupToken">First-run setup token</label><input id="authSetupToken" name="setup_token" autocomplete="off" maxlength="512"><span class="sx-auth-hint">Copy the token printed in the ScarletX backend startup log.</span></div>
        <div class="sx-auth-field"><label for="authPassword">Password</label><input id="authPassword" name="password" type="password" autocomplete="current-password" maxlength="1024" required></div>
        <div class="sx-auth-field" id="authConfirmField" hidden><label for="authPasswordConfirm">Confirm password</label><input id="authPasswordConfirm" name="password_confirm" type="password" autocomplete="new-password" maxlength="1024"></div>
      </div>
      <div class="sx-auth-error" id="authError"></div>
      <button class="sx-auth-submit" id="authSubmit" type="submit">Continue</button>
    </form>
  </section>
</div>
<div class="sx-auth-account" id="authAccount" hidden>
  <button id="authAccountButton" type="button">Administrator</button>
  <button id="authLogoutButton" type="button">Sign out</button>
</div>
<dialog class="sx-auth-dialog" id="authAccountDialog">
  <div class="sx-auth-dialog-inner">
    <div class="sx-auth-dialog-head"><h2>Administrator account</h2><button class="sx-auth-dialog-close" id="authAccountClose" type="button" aria-label="Close">×</button></div>
    <form id="authAccountForm">
      <div class="sx-auth-fields">
        <div class="sx-auth-field"><label for="authAccountUsername">Username</label><input id="authAccountUsername" autocomplete="username" maxlength="100" required></div>
        <div class="sx-auth-field"><label for="authAccountPassword">New password</label><input id="authAccountPassword" type="password" autocomplete="new-password" minlength="12" maxlength="1024" required><span class="sx-auth-hint">Use at least 12 characters.</span></div>
        <div class="sx-auth-field"><label for="authAccountPasswordConfirm">Confirm new password</label><input id="authAccountPasswordConfirm" type="password" autocomplete="new-password" minlength="12" maxlength="1024" required></div>
      </div>
      <div class="sx-auth-error" id="authAccountError"></div>
      <button class="sx-auth-submit" id="authAccountSave" type="submit">Update account</button>
    </form>
  </div>
</dialog>`);

const state = {setupRequired:false, username:'', appStarted:false, appBoot:null, queueSource:null, queueFailures:0, queueRetryTimer:null, queueLastEventId:0};
const el = id => document.getElementById(id);
const QUEUE_KINDS = ['snapshot','progress','transition','history','resync'];

function dispatchQueue(name, detail={}) {
  window.dispatchEvent(new CustomEvent(name, {detail}));
}

function stopQueueStream() {
  if (state.queueRetryTimer) {
    clearTimeout(state.queueRetryTimer);
    state.queueRetryTimer = null;
  }
  if (state.queueSource) {
    state.queueSource.close();
    state.queueSource = null;
  }
  state.queueLastEventId = 0;
}

function startQueueStream() {
  if (state.queueSource) return;
  if (!window.EventSource) {
    dispatchQueue('scarletx:queue-stream-fallback', {reason:'unsupported'});
    return;
  }
  const source = new EventSource('/api/activity/stream');
  state.queueSource = source;
  source.onopen = () => {
    if (state.queueSource !== source) return;
    state.queueFailures = 0;
    dispatchQueue('scarletx:queue-stream-healthy');
  };
  const handle = kind => event => {
    let payload = {};
    try { payload = event.data ? JSON.parse(event.data) : {}; } catch { return; }
    const eventId = Number(event.lastEventId || 0);
    if (kind !== 'resync' && eventId && eventId <= state.queueLastEventId) return;
    if (kind === 'resync') state.queueLastEventId = eventId;
    else if (eventId) state.queueLastEventId = eventId;
    dispatchQueue('scarletx:queue-event', {kind, id:eventId, payload});
  };
  QUEUE_KINDS.forEach(kind => source.addEventListener(kind, handle(kind)));
  source.onerror = () => {
    if (state.queueSource !== source) return;
    state.queueFailures += 1;
    if (state.queueFailures < 3) return;
    source.close();
    state.queueSource = null;
    dispatchQueue('scarletx:queue-stream-fallback', {reason:'repeated_failure'});
    state.queueRetryTimer = setTimeout(() => {
      state.queueRetryTimer = null;
      startQueueStream();
    }, 30000);
  };
}

  async function request(path, options={}) {
    const headers = {'Content-Type':'application/json', ...(options.headers || {})};
    const response = await fetch(path, {...options, headers, credentials:'same-origin'});
    if (response.status === 204) return null;
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!response.ok) throw new Error(data?.detail || data || `Request failed (${response.status})`);
    return data;
  }

  function setGate(mode, message='') {
    const setup = mode === 'setup';
    el('authGate').hidden = false;
    el('authForm').hidden = false;
    el('authSetupTokenField').hidden = !setup;
    el('authSetupToken').required = setup;
    el('authConfirmField').hidden = !setup;
    el('authPasswordConfirm').required = setup;
    el('authPassword').autocomplete = setup ? 'new-password' : 'current-password';
    el('authTitle').textContent = setup ? 'Create your administrator' : 'Sign in to ScarletX';
    el('authSubtitle').textContent = setup
      ? 'Create the single local administrator account before ScarletX can be used.'
      : 'Enter the local administrator credentials for this ScarletX server.';
    el('authSubmit').textContent = setup ? 'Create administrator' : 'Sign in';
    el('authError').textContent = message;
    el('authSetupToken').value = '';
    el('authPassword').value = '';
    el('authPasswordConfirm').value = '';
    setTimeout(() => el('authUsername').focus(), 0);
  }

  function showApp(status) {
    state.username = status.username || state.username || 'Administrator';
    el('authGate').hidden = true;
    el('authAccount').hidden = false;
    el('authAccountButton').textContent = state.username;
    el('authAccountUsername').value = state.username;
    startQueueStream();
    if (!state.appStarted && state.appBoot) {
      state.appStarted = true;
      Promise.resolve(state.appBoot()).catch(error => console.error('ScarletX boot failed', error));
    }
  }

  async function refresh() {
    el('authError').textContent = '';
    try {
      const status = await request('/api/auth/status');
      state.setupRequired = !!status.setup_required;
      if (status.setup_required) return setGate('setup');
      if (!status.authenticated) return setGate('login');
      showApp(status);
    } catch (error) {
      el('authTitle').textContent = 'ScarletX is unavailable';
      el('authSubtitle').textContent = 'The authentication service could not be reached.';
      el('authForm').hidden = true;
      el('authError').textContent = error.message;
    }
  }

  el('authForm').addEventListener('submit', async event => {
    event.preventDefault();
    const submit = el('authSubmit');
    submit.disabled = true;
    el('authError').textContent = '';
    try {
      const username = el('authUsername').value.trim();
      const password = el('authPassword').value;
      if (state.setupRequired) {
        const setupToken = el('authSetupToken').value.trim();
        const passwordConfirm = el('authPasswordConfirm').value;
        if (!setupToken) throw new Error('The first-run setup token is required.');
        if (password.length < 12) throw new Error('Password must be at least 12 characters.');
        if (password !== passwordConfirm) throw new Error('Passwords do not match.');
        await request('/api/setup/admin', {method:'POST', body:JSON.stringify({username, password, password_confirm:passwordConfirm, setup_token:setupToken})});
      } else {
        await request('/api/auth/login', {method:'POST', body:JSON.stringify({username, password})});
      }
      await refresh();
    } catch (error) {
      el('authError').textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });

  el('authLogoutButton').addEventListener('click', async () => {
    el('authLogoutButton').disabled = true;
    stopQueueStream();
    try { await request('/api/auth/logout', {method:'POST'}); } catch (error) { console.error(error); }
    location.reload();
  });

  el('authAccountButton').addEventListener('click', () => {
    el('authAccountUsername').value = state.username || '';
    el('authAccountPassword').value = '';
    el('authAccountPasswordConfirm').value = '';
    el('authAccountError').textContent = '';
    el('authAccountDialog').showModal();
  });
  el('authAccountClose').addEventListener('click', () => el('authAccountDialog').close());
  el('authAccountForm').addEventListener('submit', async event => {
    event.preventDefault();
    const save = el('authAccountSave');
    save.disabled = true;
    el('authAccountError').textContent = '';
    try {
      const username = el('authAccountUsername').value.trim();
      const password = el('authAccountPassword').value;
      const passwordConfirm = el('authAccountPasswordConfirm').value;
      if (password.length < 12) throw new Error('Password must be at least 12 characters.');
      if (password !== passwordConfirm) throw new Error('Passwords do not match.');
      const result = await request('/api/auth/admin', {method:'PATCH', body:JSON.stringify({username, password, password_confirm:passwordConfirm})});
      state.username = result.username;
      el('authAccountButton').textContent = state.username;
      el('authAccountDialog').close();
    } catch (error) {
      el('authAccountError').textContent = error.message;
    } finally {
      save.disabled = false;
    }
  });

  window.authGateBoot = function authGateBoot(appBoot) {
    state.appBoot = appBoot;
    refresh();
  };
})();
