from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

AUTH_UI_MARKER = 'id="authGate"'
_BOOT_MARKER = "\nboot();\n"

_AUTH_STYLE = r"""
<style id="scarletxAuthStyles">
.sx-auth-gate{position:fixed;inset:0;z-index:10000;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at 50% 10%,rgba(239,35,60,.18),transparent 42%),#070a0f;color:#f3f5f8;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}.sx-auth-gate[hidden],.sx-auth-account[hidden]{display:none!important}.sx-auth-card{width:min(430px,100%);background:#11151c;border:1px solid #2b323d;border-radius:18px;box-shadow:0 28px 90px rgba(0,0,0,.55);padding:30px}.sx-auth-brand{display:flex;align-items:center;gap:10px;font-size:29px;font-weight:800;letter-spacing:-1px;margin-bottom:8px}.sx-auth-brand b{color:#ef233c}.sx-auth-card h1{font-size:20px;margin:20px 0 7px}.sx-auth-card p{margin:0 0 20px;color:#8b95a3;font-size:13px;line-height:1.55}.sx-auth-fields{display:grid;gap:13px}.sx-auth-field{display:grid;gap:6px}.sx-auth-field label{font-size:11px;color:#aeb7c2;font-weight:650}.sx-auth-field input{width:100%;border:1px solid #303743;border-radius:9px;background:#0b0f14;color:#f3f5f8;padding:11px 12px;outline:none}.sx-auth-field input:focus{border-color:#ef233c;box-shadow:0 0 0 3px rgba(239,35,60,.14)}.sx-auth-error{min-height:18px;margin:12px 0 0;color:#ff7a89;font-size:11px}.sx-auth-submit{width:100%;margin-top:16px;border:0;border-radius:9px;padding:11px 14px;background:#ef233c;color:#fff;font-weight:750}.sx-auth-submit:disabled{opacity:.55;cursor:wait}.sx-auth-account{position:fixed;right:18px;bottom:18px;z-index:9000;display:flex;gap:7px;padding:7px;border:1px solid #2a313b;background:rgba(17,21,28,.95);box-shadow:0 12px 36px rgba(0,0,0,.32);border-radius:12px;backdrop-filter:blur(8px)}.sx-auth-account button{border:1px solid #333b47;background:#171c24;color:#dce2e9;border-radius:8px;padding:8px 10px;font-size:11px;font-weight:700}.sx-auth-account button:hover{border-color:#ef233c;color:#fff}.sx-auth-dialog{border:1px solid #303743;border-radius:16px;background:#11151c;color:#f3f5f8;width:min(430px,calc(100% - 32px));padding:0;box-shadow:0 28px 90px rgba(0,0,0,.6)}.sx-auth-dialog::backdrop{background:rgba(2,4,7,.78);backdrop-filter:blur(6px)}.sx-auth-dialog-inner{padding:24px}.sx-auth-dialog-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.sx-auth-dialog-head h2{margin:0;font-size:18px}.sx-auth-dialog-close{border:1px solid #303743;background:#171c24;color:#b8c0ca;border-radius:8px;width:32px;height:32px}.sx-auth-hint{color:#798492;font-size:10px;margin-top:4px}
@media(max-width:620px){.sx-auth-card{padding:24px 20px}.sx-auth-account{left:12px;right:12px;bottom:12px;justify-content:flex-end}}
</style>
"""

_AUTH_MARKUP = r"""
<div class="sx-auth-gate" id="authGate" aria-live="polite">
  <section class="sx-auth-card" role="dialog" aria-modal="true" aria-labelledby="authTitle">
    <div class="sx-auth-brand">Scarlet<b>X</b></div>
    <h1 id="authTitle">Checking security…</h1>
    <p id="authSubtitle">Verifying the local ScarletX administrator session.</p>
    <form id="authForm" hidden>
      <div class="sx-auth-fields">
        <div class="sx-auth-field"><label for="authUsername">Username</label><input id="authUsername" name="username" autocomplete="username" maxlength="100" required></div>
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
</dialog>
"""

_AUTH_SCRIPT = r"""
<script id="scarletxAuthScript">
(() => {
  const state = {setupRequired:false, username:'', appStarted:false, appBoot:null};
  const el = id => document.getElementById(id);
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
    el('authConfirmField').hidden = !setup;
    el('authPasswordConfirm').required = setup;
    el('authPassword').autocomplete = setup ? 'new-password' : 'current-password';
    el('authTitle').textContent = setup ? 'Create your administrator' : 'Sign in to ScarletX';
    el('authSubtitle').textContent = setup
      ? 'Create the single local administrator account before ScarletX can be used.'
      : 'Enter the local administrator credentials for this ScarletX server.';
    el('authSubmit').textContent = setup ? 'Create administrator' : 'Sign in';
    el('authError').textContent = message;
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
        const passwordConfirm = el('authPasswordConfirm').value;
        if (password.length < 12) throw new Error('Password must be at least 12 characters.');
        if (password !== passwordConfirm) throw new Error('Passwords do not match.');
        await request('/api/setup/admin', {method:'POST', body:JSON.stringify({username, password, password_confirm:passwordConfirm})});
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
</script>
"""


def render_auth_shell(html: str) -> str:
    """Inject the authentication shell and delay the legacy SPA boot until login succeeds."""
    if AUTH_UI_MARKER in html:
        return html
    if _BOOT_MARKER not in html:
        raise ValueError("ScarletX web shell boot marker was not found")
    rendered = html.replace("</head>", f"{_AUTH_STYLE}\n</head>", 1)
    rendered = rendered.replace("<body>", f"<body>\n{_AUTH_MARKUP}\n{_AUTH_SCRIPT}", 1)
    return rendered.replace(_BOOT_MARKER, "\nauthGateBoot(boot);\n", 1)


def install_auth_ui(app: FastAPI, *, html_path: Path) -> None:
    """Serve the existing ScarletX SPA through the authentication shell at the root path."""
    source = Path(html_path)

    @app.middleware("http")
    async def scarletx_auth_ui(request: Request, call_next):
        if request.method == "GET" and request.url.path == "/":
            rendered = render_auth_shell(source.read_text(encoding="utf-8"))
            return HTMLResponse(
                rendered,
                headers={"Cache-Control": "no-store"},
            )
        return await call_next(request)
