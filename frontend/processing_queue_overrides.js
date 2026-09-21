(() => {
  const baseApplyLiveQueue = applyLiveQueue;

  function nativeRow(row) {
    return row?.native_job || row || {};
  }

  function attemptCount(row) {
    const native = nativeRow(row);
    const explicit = row?.attempts ?? native.attempts;
    if (explicit != null) return Math.max(0, Number(explicit) || 0);
    const retries = Number(row?.watchdog_retries ?? native.watchdog_retries ?? 0) || 0;
    return Math.max(0, retries + ((row?.started_at || native.started_at) ? 1 : 0));
  }

  function elapsedSeconds(row) {
    const native = nativeRow(row);
    const explicit = row?.elapsed_seconds ?? native.elapsed_seconds;
    if (explicit != null) return Math.max(0, Number(explicit) || 0);
    const started = row?.started_at || native.started_at || row?.created_at || native.created_at;
    if (!started) return 0;
    const finished = row?.completed_at || native.completed_at;
    const startMs = Date.parse(started);
    const endMs = finished ? Date.parse(finished) : Date.now();
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return 0;
    return Math.max(0, Math.floor((endMs - startMs) / 1000));
  }

  function formatElapsed(value) {
    const seconds = Math.max(0, Number(value) || 0);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = Math.floor(seconds % 60);
    if (hours) return `${hours}h ${minutes}m`;
    if (minutes) return `${minutes}m ${remainder}s`;
    return `${remainder}s`;
  }

  function speedText(value) {
    return value ? `${bytes(value)}/s` : '—';
  }

  function etaText(value) {
    if (value == null) return '—';
    const seconds = Math.max(0, Number(value) || 0);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = Math.floor(seconds % 60);
    return hours ? `${hours}h ${minutes}m` : `${minutes}m ${String(remainder).padStart(2, '0')}s`;
  }

  function queueState(row) {
    const native = nativeRow(row);
    return row?.client_status || row?.status || native.status || 'queued';
  }

  function queueStatusClass(state) {
    if (['downloading', 'importing'].includes(state)) return 'good';
    if (['failed', 'error'].includes(state)) return 'bad';
    if (['queued', 'postprocessing'].includes(state)) return 'warn';
    return '';
  }

  function queueStatusLabel(state) {
    return String(state || 'queued').replace(/(^|[-_ ])(\w)/g, (_, prefix, letter) => `${prefix}${letter.toUpperCase()}`);
  }

  function syncQueueSummary(rows) {
    const active = rows.filter(row => ['downloading', 'postprocessing', 'importing'].includes(queueState(row))).length;
    const queued = rows.filter(row => ['queued', 'paused'].includes(queueState(row))).length;
    const speed = rows.reduce((sum, row) => sum + Math.max(0, Number(row.speed_bps) || 0), 0);
    const remaining = rows.reduce((sum, row) => {
      const total = Math.max(0, Number(row.total_bytes) || 0);
      const done = Math.max(0, Number(row.downloaded_bytes) || 0);
      return sum + Math.max(0, total - done);
    }, 0);
    const connections = rows.reduce((sum, row) => sum + Math.max(0, Number(row.active_connections) || 0), 0);
    const capacity = rows.reduce((sum, row) => sum + liveConnectionCapacity(row), 0);
    const set = (id, value) => { const element = $(`#${id}`); if (element) element.textContent = value; };
    set('downloadActiveCount', String(active));
    set('downloadQueuedCount', String(queued));
    set('downloadSpeed', speedText(speed));
    set('downloadRemaining', bytes(remaining));
    set('downloadQueueSpeed', speedText(speed));
    set('downloadQueueConnections', capacity ? `${connections} / ${capacity}` : connections ? String(connections) : '—');
  }

  function stageText(row, state) {
    const native = nativeRow(row);
    return row?.stage || native.stage || row?.phase || native.phase ||
      (state === 'postprocessing' ? (row?.postprocess_note || native.postprocess_note || 'Preparing media…') : state);
  }

  function actionButtons(row, state) {
    const job = esc(row.external_id || row.id || '');
    if (['queued', 'downloading'].includes(state)) {
      return `<button class="btn small queue-action" data-native-act="pause" data-job="${job}" aria-label="Pause download" title="Pause">Ⅱ</button><button class="btn small danger queue-action" data-native-act="cancel" data-job="${job}" aria-label="Cancel download" title="Cancel">×</button>`;
    }
    if (state === 'postprocessing') {
      return `<button class="btn small danger queue-action" data-native-act="cancel" data-job="${job}" aria-label="Cancel download" title="Cancel">×</button>`;
    }
    if (state === 'paused') {
      return `<button class="btn small primary queue-action" data-native-act="resume" data-job="${job}" aria-label="Resume download" title="Resume">▶</button>`;
    }
    return '';
  }

  activityQueueHtml = function(rows) {
    if (!rows.length) return empty('No active downloads.');
    return `<div class="tablewrap download-queue-tablewrap" style="border:0;border-radius:0"><table class="table download-queue-table"><thead><tr><th>Download</th><th>Progress</th><th>Status</th><th>Speed / ETA</th><th></th></tr></thead><tbody>${rows.map(x => {
      const native = nativeRow(x);
      const state = queueState(x);
      const pct = x.progress == null ? '—' : `${Number(x.progress).toFixed(1)}%`;
      const speed = speedText(x.speed_bps);
      const eta = etaText(x.eta_seconds);
      const done = x.downloaded_bytes != null ? bytes(x.downloaded_bytes) : '—';
      const total = x.total_bytes ? bytes(x.total_bytes) : '—';
      const error = x.error || native.error || '';
      const studio = x.studio || '';
      const title = x.scene_title || x.release_title || x.title || 'Download';
      const detail = [studio, x.release_title && x.release_title !== title ? x.release_title : '', total !== '—' ? total : ''].filter(Boolean).join(' · ');
      const statusClass = queueStatusClass(state);
      const stateDetail = error || (state === 'postprocessing' ? (x.postprocess_note || 'Preparing media…') : '');
      return `<tr data-live-job="${esc(x.external_id || x.id || '')}"><td><div class="download-queue-item"><div class="download-queue-copy"><b class="live-title">${esc(title)}</b><small class="live-studio">${esc(detail)}</small></div></div></td><td><div class="download-progress"><div class="mini-progress"><i class="live-bar" style="width:${Math.min(100, Number(x.progress || 0))}%"></i></div><div class="download-progress-meta"><b class="live-pct">${pct}</b><small class="live-bytes">${done} / ${total}</small></div></div></td><td><span class="state ${statusClass} live-status">${esc(queueStatusLabel(state))}</span>${stateDetail ? `<small class="live-state-detail ${error ? 'live-error' : ''}">${esc(stateDetail)}</small>` : ''}</td><td><b class="live-speed">${speed}</b><small class="live-eta">${eta !== '—' ? `ETA ${eta}` : 'Waiting'}</small></td><td><div class="actions live-actions">${actionButtons(x, state)}</div></td></tr>`;
    }).join('')}</tbody></table></div>`;
  };

  function syncOperationalFields(rows) {
    const byId = new Map((rows || []).map(x => [String(x.external_id || x.id || ''), x]));
    document.querySelectorAll('[data-live-job]').forEach(row => {
      const item = byId.get(String(row.dataset.liveJob || ''));
      if (!item) return;
      const native = nativeRow(item);
      const state = queueState(item);
      const attempts = row.querySelector('.live-attempts');
      const elapsed = row.querySelector('.live-elapsed');
      const error = row.querySelector('.live-error');
      const stage = row.querySelector('.live-state-detail');
      const speed = row.querySelector('.live-speed');
      const status = row.querySelector('.live-status');
      if (attempts) attempts.textContent = String(attemptCount(item));
      if (elapsed) elapsed.textContent = formatElapsed(elapsedSeconds(item));
      if (error) error.textContent = item.error || native.error || '—';
      if (stage) stage.textContent = stageText(item, state);
      if (speed) speed.textContent = speedText(item.speed_bps);
      if (status) {
        status.textContent = queueStatusLabel(state);
        status.classList.remove('good', 'warn', 'bad');
        const statusClass = queueStatusClass(state);
        if (statusClass) status.classList.add(statusClass);
      }
    });
  }

  function syncQueueActions(rows) {
    const byId = new Map((rows || []).map(x => [String(x.external_id || x.id || ''), x]));
    document.querySelectorAll('[data-live-job]').forEach(row => {
      const item = byId.get(String(row.dataset.liveJob || ''));
      const actions = row.querySelector('.live-actions');
      if (item && actions) actions.innerHTML = actionButtons(item, queueState(item));
    });
  }

  applyLiveQueue = function(q) {
    baseApplyLiveQueue(q);
    const allRows = q?.tracked || [];
    const start = (activityQueuePage - 1) * ACTIVITY_QUEUE_PAGE_SIZE;
    const visibleRows = allRows.slice(start, start + ACTIVITY_QUEUE_PAGE_SIZE);
    syncOperationalFields(visibleRows);
    syncQueueActions(visibleRows);
    syncQueueSummary(allRows);
    syncDownloadPauseControl(q);
  };
})();
