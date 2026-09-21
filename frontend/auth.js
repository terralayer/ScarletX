(() => {
  document.body.insertAdjacentHTML('afterbegin', `
<div class="sx-auth-gate" id="authGate" aria-live="polite">
  <section class="sx-auth-card" role="dialog" aria-modal="true" aria-labelledby="authTitle">
    <div class="sx-auth-brand"><img src="/scarletx-wordmark.webp?v=approved-20260915-6" alt="ScarletX"></div>
    <h1 id="authTitle">Sign in to ScarletX</h1>
    <p id="authSubtitle">Checking your installation…</p>
    <section class="sx-agreement" id="authAgreement" hidden aria-labelledby="authAgreementTitle">
      <div class="sx-agreement-scroll" id="authAgreementScroll" tabindex="0">
        <h2 id="authAgreementTitle">ScarletX Usage Agreement</h2>
        <p>ScarletX is self-hosted software for organizing and automating an adult media library. Before creating the administrator account, review the responsibilities that come with operating it.</p>
        <h3>Adult-content responsibility</h3>
        <p>By continuing, you confirm that you are legally permitted to access, possess, and manage the adult material you add to ScarletX in your jurisdiction. You are responsible for the content stored on your system and for who can access your installation.</p>
        <h3>Connected services and downloads</h3>
        <p>ScarletX can connect to metadata, indexer, Usenet, and other third-party services that you configure. You are responsible for your accounts, credentials, searches, downloads, and compliance with the terms and laws that apply to those services and content.</p>
        <h3>Local control</h3>
        <p>ScarletX is designed to run on systems you control. You are responsible for securing the host, backups, storage permissions, network exposure, and administrator credentials for your installation.</p>
        <h3>Software terms</h3>
        <p>The software is provided under the project license and without a guarantee that every external service, file, or item of metadata is accurate, available, safe, or lawful for your use.</p>
        <p class="sx-agreement-links">Review the <a href="https://github.com/terralayer/ScarletX/blob/main/LICENSE" target="_blank" rel="noopener noreferrer">project license</a> and <a href="https://github.com/terralayer/ScarletX" target="_blank" rel="noopener noreferrer">ScarletX source</a>.</p>
        <p><strong>Agreement version:</strong> 2026-09-21</p>
      </div>
      <p class="sx-agreement-instruction" id="authAgreementInstruction">Scroll to the bottom to enable acceptance.</p>
      <label class="sx-agreement-check"><input id="authAgreementAccept" type="checkbox" disabled><span>I have read and agree to the ScarletX Usage Agreement.</span></label>
      <div class="sx-auth-error" id="authAgreementError" role="status"></div>
      <button class="sx-auth-submit" id="authAgreementContinue" type="button" disabled>Continue</button>
    </section>
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
`);

const AGREEMENT_VERSION = '2026-09-21';
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

function updateAgreementGate() {
  const scroller = el('authAgreementScroll');
  const checkbox = el('authAgreementAccept');
  const button = el('authAgreementContinue');
  const reachedBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 4;
  if (reachedBottom && checkbox.disabled) {
    checkbox.disabled = false;
    el('authAgreementInstruction').textContent = 'You reached the end. Check the box to continue.';
  }
  button.disabled = checkbox.disabled || !checkbox.checked;
}

function resetAgreementGate() {
  const scroller = el('authAgreementScroll');
  const checkbox = el('authAgreementAccept');
  scroller.scrollTop = 0;
  checkbox.checked = false;
  checkbox.disabled = true;
  el('authAgreementContinue').disabled = true;
  el('authAgreementError').textContent = '';
  el('authAgreementInstruction').textContent = 'Scroll to the bottom to enable acceptance.';
  requestAnimationFrame(updateAgreementGate);
}

function showAgreement() {
  state.setup = true;
  el('authTitle').textContent = 'Before you create an administrator';
  el('authTitle').classList.remove('sx-visually-hidden');
  el('authSubtitle').textContent = 'Review the ScarletX Usage Agreement. Acceptance is recorded once for this installation.';
  el('authForm').hidden = true;
  el('authAgreement').hidden = false;
  resetAgreementGate();
  el('authAgreementScroll').focus();
}

async function showSetupForm() {
  state.setup = true;
  el('authAgreement').hidden = true;
  el('authTitle').textContent = 'Initial setup';
  el('authTitle').classList.add('sx-visually-hidden');
  el('authSubtitle').textContent = 'Create your administrator account to get started. Next, we will open Settings to connect your services.';
  el('authForm').hidden = false;
  el('authSetupFields').hidden = false;
  el('authPasswordConfirm').required = true;
  el('authPassword').autocomplete = 'new-password';
  el('authPassword').minLength = 12;
  el('authSubmit').textContent = 'Finish setup & open Settings';
  if (!el('authApiKey').value) await generateKey();
  el('authUsername').focus();
}

function showLoginForm() {
  state.setup = false;
  el('authAgreement').hidden = true;
  el('authTitle').textContent = 'Sign in to ScarletX';
  el('authTitle').classList.remove('sx-visually-hidden');
  el('authSubtitle').textContent = 'Sign in with your administrator account.';
  el('authForm').hidden = false;
  el('authSetupFields').hidden = true;
  el('authPasswordConfirm').required = false;
  el('authPassword').autocomplete = 'current-password';
  el('authPassword').minLength = 1;
  el('authSubmit').textContent = 'Sign in';
  el('authUsername').focus();
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
  window.scarletxUsername = state.username;
  el('authPassword').value = '';
  el('authPasswordConfirm').value = '';
  el('authApiKey').value = '';
  bootApp();
  dispatchQueue('scarletx:app-open');
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
el('authAgreementScroll').addEventListener('scroll', updateAgreementGate);
el('authAgreementAccept').addEventListener('change', updateAgreementGate);
el('authAgreementContinue').onclick = async () => {
  if (el('authAgreementAccept').disabled || !el('authAgreementAccept').checked) return;
  const button = el('authAgreementContinue');
  button.disabled = true;
  el('authAgreementError').textContent = '';
  try {
    const result = await request('/api/setup/agreement', {method:'POST', body:JSON.stringify({accepted:true, version:AGREEMENT_VERSION})});
    if (!result?.accepted) throw new Error('Agreement acceptance was not saved.');
    await showSetupForm();
  } catch (error) {
    el('authAgreementError').textContent = error.message;
    updateAgreementGate();
  }
};
window.addEventListener('scarletx:session-expired', () => {
  const gate = document.getElementById('authGate');
  if (gate && !gate.hidden) return;
  location.reload();
});
window.authGateBoot = async function authGateBoot(appBoot) {
  state.appBoot = appBoot;
  try {
    const status = await request('/api/auth/status');
    if (status.authenticated) { state.username = status.username; showOpenApp(); return; }
    state.setup = status.setup_required;
    if (state.setup) {
      if (status.agreement_required) showAgreement();
      else await showSetupForm();
    } else {
      showLoginForm();
    }
  } catch (error) {
    el('authSubtitle').textContent = 'Could not connect to ScarletX. Reload this page to try again.';
    el('authError').textContent = error.message;
  }
};
})();
