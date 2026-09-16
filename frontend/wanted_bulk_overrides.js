(() => {
  const BULK_LIMIT = 25;

  function selectedWantedIds() {
    return $$('[data-wanted-select]:checked')
      .map(node => Number(node.value || 0))
      .filter(Boolean)
      .slice(0, 25);
  }

  function updateBulkButtons() {
    const count = selectedWantedIds().length;
    const search = $('#searchWantedSelected');
    const unmonitor = $('#unmonitorWantedSelected');
    if (search) search.disabled = count === 0;
    if (unmonitor) unmonitor.disabled = count === 0;
    const label = $('#wantedSelectedCount');
    if (label) label.textContent = count ? `${count} selected` : `Select up to ${BULK_LIMIT}`;
  }

  async function runWantedBulk(action) {
    const sceneIds = selectedWantedIds();
    if (!sceneIds.length) return;
    try {
      const result = await api('/api/wanted/bulk', post({action, scene_ids: sceneIds}));
      const verb = action === 'search' ? 'searched' : 'unmonitored';
      notify(`${result.processed} scene${result.processed === 1 ? '' : 's'} ${verb}.`, 'ok');
      await wanted();
    } catch (error) {
      notify(error.message, 'error');
    }
  }

  wanted = async function wantedBulkOverride() {
    $('#app').innerHTML = pageHead(
      'Wanted',
      'Monitored scenes that are missing media files.',
      `<button class="btn" id="searchWantedSelected" disabled>Search Selected</button><button class="btn" id="unmonitorWantedSelected" disabled>Unmonitor Selected</button><button class="btn primary" id="searchWanted">Search Wanted</button>`
    ) + `<div class="muted" id="wantedSelectedCount">Select up to ${BULK_LIMIT}</div><div id="wantedBody"></div>`;

    $('#searchWanted').onclick = async () => {
      const button = $('#searchWanted');
      button.disabled = true;
      button.textContent = 'Searching…';
      try {
        const result = await api('/api/wanted/search?limit=25', post());
        notify(`Checked ${result.checked}; queued ${result.queued}.`, 'ok');
        await wanted();
      } catch (error) {
        notify(error.message, 'error');
      } finally {
        if (button.isConnected) button.disabled = false;
      }
    };
    $('#searchWantedSelected').onclick = () => runWantedBulk('search');
    $('#unmonitorWantedSelected').onclick = () => runWantedBulk('unmonitor');

    try {
      const rows = await api('/api/wanted/missing?limit=500');
      if (view !== 'wanted') return;
      if (!rows.length) {
        $('#wantedBody').innerHTML = empty('Nothing is wanted. All monitored scenes have files.');
        return;
      }
      $('#wantedBody').innerHTML = `<div class="tablewrap"><table class="table"><thead><tr><th><input type="checkbox" id="wantedSelectPage" aria-label="Select first 25 wanted scenes"></th><th>Scene</th><th>Release</th><th>Status</th></tr></thead><tbody>${rows.map(x => `<tr><td><input type="checkbox" data-wanted-select value="${esc(x.library_item_id)}" aria-label="Select ${esc(x.title || 'scene')}"></td><td><b>${esc(x.title)}</b></td><td>${fmtDate(x.release_date)}</td><td><span class="state warn">Missing</span></td></tr>`).join('')}</tbody></table></div>`;
      const boxes = $$('[data-wanted-select]');
      boxes.forEach(box => {
        box.onchange = () => {
          if (selectedWantedIds().length >= BULK_LIMIT) {
            boxes.filter(item => !item.checked).forEach(item => { item.disabled = true; });
          } else {
            boxes.forEach(item => { item.disabled = false; });
          }
          updateBulkButtons();
        };
      });
      $('#wantedSelectPage').onchange = event => {
        boxes.forEach((box, index) => {
          box.checked = event.currentTarget.checked && index < BULK_LIMIT;
          box.disabled = event.currentTarget.checked && index >= BULK_LIMIT;
        });
        updateBulkButtons();
      };
      updateBulkButtons();
    } catch (error) {
      if (view !== 'wanted') return;
      notify(error.message, 'error');
    }
  };
})();
