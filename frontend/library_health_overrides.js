(() => {
  const baseMediaLibrary = window.mediaLibrary;
  if (typeof baseMediaLibrary !== 'function') return;

  function healthState(kind) {
    if (kind === 'missing') return ['Missing', 'bad'];
    if (kind === 'unmatched') return ['Unmatched', 'warn'];
    return ['Needs probe', 'warn'];
  }

  function renderLibraryHealth(health) {
    const panel = document.querySelector('#libraryHealth');
    if (!panel) return;
    const body = panel.querySelector('#libraryHealthBody');
    const summary = panel.querySelector('#libraryHealthSummary');
    if (!body || !summary) return;

    if (health?.error) {
      summary.textContent = 'Unavailable';
      body.innerHTML = `<div class="empty">Library health could not be loaded.</div>`;
      return;
    }

    const counts = health?.counts || {};
    const total = Number(counts.total || 0);
    summary.textContent = total
      ? `${total} issue${total === 1 ? '' : 's'}`
      : 'Healthy';

    if (!total) {
      body.innerHTML = `<div class="rows"><div class="row"><div><b>Healthy</b><small>No local library issues detected.</small></div></div></div>`;
      return;
    }

    const issues = health?.issues || [];
    const countLine = `<div class="rows"><div class="row"><div><b>${Number(counts.missing || 0)} missing · ${Number(counts.unmatched || 0)} unmatched · ${Number(counts.unprobed || 0)} needs probe</b><small>Showing up to 50 actionable local-library issues.</small></div></div></div>`;
    const table = issues.length
      ? `<div class="tablewrap" style="border:0;border-radius:0"><table class="table"><thead><tr><th>Issue</th><th>Item</th><th>Details</th></tr></thead><tbody>${issues.map(item => {
          const [label, stateClass] = healthState(item.kind);
          return `<tr><td><span class="state ${stateClass}">${label}</span></td><td><b>${esc(item.title || 'Media item')}</b>${item.size_bytes ? `<small>${bytes(item.size_bytes)}</small>` : ''}</td><td>${esc(item.detail || '')}</td></tr>`;
        }).join('')}</tbody></table></div>`
      : empty('No issue details are available.');
    body.innerHTML = countLine + table;
  }

  window.mediaLibrary = async function mediaLibraryWithHealth() {
    const healthRequest = api('/api/media-library/health').catch(error => ({error: error.message}));
    await baseMediaLibrary();
    if (view !== 'library') return;

    const stats = document.querySelector('#libraryStats');
    if (!stats) return;
    const panel = document.createElement('div');
    panel.id = 'libraryHealth';
    panel.className = 'panel library-health';
    panel.style.marginBottom = '14px';
    panel.innerHTML = `<div class="panel-head"><h2>Library Health</h2><small id="libraryHealthSummary">Loading…</small></div><div id="libraryHealthBody"><div class="empty">Checking local library health…</div></div>`;
    stats.insertAdjacentElement('afterend', panel);

    const health = await healthRequest;
    if (view !== 'library') return;
    renderLibraryHealth(health);
  };
})();
