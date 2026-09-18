(() => {
  document.body.insertAdjacentHTML('afterbegin', `
<div class="sx-auth-gate" id="authGate" aria-live="polite">
  <section class="sx-auth-card" role="dialog" aria-modal="true" aria-labelledby="authTitle">
    <div class="sx-auth-brand"><img src="/scarletx-wordmark.webp?v=approved-20260915-6" alt="ScarletX"></div>
    <h1 id="authTitle">Sign in to ScarletX</h1>
    <p id="authSubtitle">Checking your installation…</p>
    <form id="authForm" hidden>
      <div class="sx-auth-fields">
        <div class="sx-auth-field"><label for="authUsername">Username</label><input id="authUsername" name="username" autocomplete="username" maxlength="100" required></div>
        <div class="sx-auth-field"><label for="authPassword">Password</label><input id="authPassword" name="password" type="password" autocomplete="current-password" maxlength="1024" required></div>
      </div>
      <div id="authSetupFields" hidden>
        <div class="sx-auth-field"><label for="authPasswordConfirm">Confirm password</label><input id="authPasswordConfirm" type="password" autocomplete="new-password" maxlength="1024"></div>
        <div class="sx-auth-field"><label for="authApiKey">ScarletX API key</label><input id="authApiKey" readonly spellcheck="false" autocomplete="off"><span class="sx-auth-hint">Use this key to connect integrations to ScarletX. Your TPDB key is added separately in Settings.</span></div>
        <div class="sx-auth-key-actions"><button id="authCopyKey" type="button">Copy key</button><button id="authRefreshKey" type="button">Regenerate key</button></div>
      </div>
      <div class="sx-auth-error" id="authError" role="status"></div>
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

const state = {setup:false, username:'', appStarted:false, appBoot:null, queueSource:null, queueFailures:0, queueRetryTimer:null, queueLastEventId:0};
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

function bootApp() {
  startQueueStream();
  if (!state.appStarted && state.appBoot) {
    state.appStarted = true;
    Promise.resolve(state.appBoot()).catch(error => console.error('ScarletX boot failed', error));
  }
}

function showOpenApp() {
  el('authGate').hidden = true;
  el('authAccount').hidden = false;
  el('authAccountButton').textContent = state.username || 'Administrator';
  window.scarletxUsername = state.username;
  el('authPassword').value = '';
  el('authPasswordConfirm').value = '';
  el('authApiKey').value = '';
  bootApp();
}

el('authForm').addEventListener('submit', async event => {
  event.preventDefault();
  const submit = el('authSubmit');
  submit.disabled = true;
  el('authRefreshKey').disabled = true;
  el('authCopyKey').disabled = true;
  el('authError').textContent = '';
  try {
    const username = el('authUsername').value.trim();
    const password = el('authPassword').value;
    let result;
    if (state.setup) {
      const passwordConfirm = el('authPasswordConfirm').value;
      if (password.length < 12) throw new Error('Use at least 12 characters for your password.');
      if (password !== passwordConfirm) throw new Error('Passwords do not match.');
      const apiKey = el('authApiKey').value;
      if (!apiKey) throw new Error('Generate an API key before continuing.');
      result = await request('/api/setup/admin', {method:'POST', body:JSON.stringify({username,password,password_confirm:passwordConfirm,api_key:apiKey})});
      window.scarletxInitialView = 'settings';
      state.setup = false;
    } else {
      result = await request('/api/auth/login', {method:'POST', body:JSON.stringify({username, password})});
    }
    state.username = result.username;
    showOpenApp();
  } catch (error) {
    el('authError').textContent = error.message;
  } finally {
    submit.disabled = false;
    el('authRefreshKey').disabled = false;
    el('authCopyKey').disabled = false;
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
    window.scarletxUsername = state.username;
    el('authAccountButton').textContent = state.username;
    el('authAccountDialog').close();
  } catch (error) {
    el('authAccountError').textContent = error.message;
  } finally {
    save.disabled = false;
  }
});

async function generateKey() {
  el('authRefreshKey').disabled = true;
  el('authSubmit').disabled = true;
  el('authError').textContent = '';
  try {
    const result = await request('/api/setup/api-key');
    el('authApiKey').value = result.api_key;
  } catch (error) { el('authError').textContent = error.message; }
  finally { el('authRefreshKey').disabled = false; el('authSubmit').disabled = false; }
}
el('authRefreshKey').onclick = generateKey;
el('authCopyKey').onclick = async () => {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(el('authApiKey').value);
    else { el('authApiKey').select(); if (!document.execCommand('copy')) throw new Error('Select the key and copy it manually.'); }
    el('authError').textContent = 'API key copied.';
  } catch { el('authApiKey').select(); el('authError').textContent = 'Select the key and copy it manually.'; }
};
window.addEventListener('scarletx:session-expired', () => location.reload());
window.authGateBoot = async function authGateBoot(appBoot) {
  state.appBoot = appBoot;
  try {
    const status = await request('/api/auth/status');
    if (status.authenticated) { state.username = status.username; showOpenApp(); return; }
    state.setup = status.setup_required;
    el('authTitle').textContent = state.setup ? 'Initial setup' : 'Sign in to ScarletX';
    el('authTitle').classList.toggle('sx-visually-hidden', state.setup);
    el('authSubtitle').textContent = state.setup ? 'Create your administrator account to get started. Next, we will open Settings to connect your services.' : 'Sign in with your administrator account.';
    el('authForm').hidden = false;
    el('authSetupFields').hidden = !state.setup;
    el('authPasswordConfirm').required = state.setup;
    el('authPassword').autocomplete = state.setup ? 'new-password' : 'current-password';
    el('authPassword').minLength = state.setup ? 12 : 1;
    el('authSubmit').textContent = state.setup ? 'Finish setup & open Settings' : 'Sign in';
    if (state.setup) await generateKey();
    el('authUsername').focus();
  } catch (error) {
    el('authSubtitle').textContent = 'Could not connect to ScarletX. Reload this page to try again.';
    el('authError').textContent = error.message;
  }
};
})();
