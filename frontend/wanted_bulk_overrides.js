(() => {
  const BULK_LIMIT = 25;
  let wantedPageRequest = 0;

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

  function wantedHostCurrent(body) {
    return view === 'wanted' && body?.isConnected && $('#wantedBody') === body;
  }

  function bindWantedSelection() {
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
    const selectPage = $('#wantedSelectPage');
    if (selectPage) {
      selectPage.onchange = event => {
        boxes.forEach((box, index) => {
          box.checked = event.currentTarget.checked && index < BULK_LIMIT;
          box.disabled = event.currentTarget.checked && index >= BULK_LIMIT;
        });
        updateBulkButtons();
      };
    }
    updateBulkButtons();
  }

  function bindWantedPager(body, hasMore) {
    const move = targetPage => changeListPage({
      host: body,
      page: targetPage,
      getPage: () => wantedPage + 1,
      setPage: page => { wantedPage = page - 1; },
      load: () => loadWantedPage(body),
      current: () => wantedHostCurrent(body),
    });
    const previous = $('#wantedPrevious');
    const next = $('#wantedNext');
    if (previous) previous.onclick = () => move(Math.max(1, wantedPage));
    if (next) next.onclick = () => hasMore ? move(wantedPage + 2) : false;
  }

  async function loadWantedPage(body, {resetEmpty = false, requestedPage = wantedPage, expectedPage = wantedPage} = {}) {
    const requestId = ++wantedPageRequest;
    const offset = requestedPage * WANTED_PAGE_SIZE;
    const results = await api(`/api/wanted/missing?limit=${WANTED_PAGE_SIZE + 1}&offset=${offset}`);
    if (!wantedHostCurrent(body) || requestId !== wantedPageRequest || wantedPage !== expectedPage) return false;
    const rows = results.slice(0, WANTED_PAGE_SIZE), hasMore = results.length > WANTED_PAGE_SIZE;
    if (!rows.length && requestedPage > 0) {
      if (!resetEmpty) return false;
      return loadWantedPage(body, {requestedPage: 0, expectedPage});
    }
    wantedPage = requestedPage;
    if (!rows.length) {
      body.innerHTML = empty('Nothing is wanted. All monitored scenes have files.');
      updateBulkButtons();
      return true;
    }
    body.innerHTML = `<div class="tablewrap"><table class="table"><thead><tr><th><input type="checkbox" id="wantedSelectPage" aria-label="Select first 25 wanted scenes"></th><th>Scene</th><th>Release</th><th>Status</th></tr></thead><tbody>${rows.map(x => `<tr><td><input type="checkbox" data-wanted-select value="${esc(x.library_item_id)}" aria-label="Select ${esc(x.title || 'scene')}"></td><td><b>${esc(x.title)}</b></td><td>${fmtDate(x.release_date)}</td><td><span class="state warn">Missing</span></td></tr>`).join('')}</tbody></table></div><div class="pager"><button class="btn small" id="wantedPrevious" ${requestedPage === 0 ? 'disabled' : ''}>Previous</button><span>Page ${requestedPage + 1} · Showing ${offset + 1}–${offset + rows.length}</span><button class="btn small" id="wantedNext" ${hasMore ? '' : 'disabled'}>Next</button></div>`;
    bindWantedPager(body, hasMore);
    bindWantedSelection();
    return true;
  }

  async function refreshWantedPage(body) {
    return loadWantedPage(body, {resetEmpty: true});
  }

  async function runWantedBulk(action) {
    const sceneIds = selectedWantedIds();
    if (!sceneIds.length) return;
    const body = $('#wantedBody');
    try {
      const result = await api('/api/wanted/bulk', post({action, scene_ids: sceneIds}));
      const verb = action === 'search' ? 'searched' : 'unmonitored';
      notify(`${result.processed} scene${result.processed === 1 ? '' : 's'} ${verb}.`, 'ok');
      if (wantedHostCurrent(body)) await refreshWantedPage(body);
    } catch (error) {
      notify(error.message, 'error');
    }
  }

  wanted = async function wantedBulkOverride() {
    const requestId = ++wantedRequest;
    $('#app').innerHTML = pageHead(
      'Wanted',
      'Monitored scenes that are missing media files.',
      `<button class="btn" id="searchWantedSelected" disabled>Search Selected</button><button class="btn" id="unmonitorWantedSelected" disabled>Unmonitor Selected</button><button class="btn primary" id="searchWanted">Search Wanted</button>`
    ) + `<div class="muted" id="wantedSelectedCount">Select up to ${BULK_LIMIT}</div><div id="wantedBody" aria-live="polite">Loading…</div>`;

    const body = $('#wantedBody');
    $('#searchWanted').onclick = async () => {
      const button = $('#searchWanted');
      button.disabled = true;
      button.textContent = 'Searching…';
      try {
        const result = await api('/api/wanted/search?limit=25', post());
        notify(`Checked ${result.checked}; queued ${result.queued}.`, 'ok');
        if (wantedHostCurrent(body)) await refreshWantedPage(body);
      } catch (error) {
        notify(error.message, 'error');
      } finally {
        if (button.isConnected) {
          button.disabled = false;
          button.textContent = 'Search Wanted';
        }
      }
    };
    $('#searchWantedSelected').onclick = () => runWantedBulk('search');
    $('#unmonitorWantedSelected').onclick = () => runWantedBulk('unmonitor');

    try {
      const loaded = await loadWantedPage(body, {resetEmpty: true});
      if (requestId !== wantedRequest || !wantedHostCurrent(body)) return false;
      return loaded;
    } catch (error) {
      if (requestId !== wantedRequest || !wantedHostCurrent(body)) return false;
      body.textContent = 'Could not load wanted scenes. Open Wanted to retry.';
      notify(error.message, 'error');
      return false;
    }
  };
})();
