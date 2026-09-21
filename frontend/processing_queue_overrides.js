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

  function speedMbps(value) {
    const bits = Math.max(0, Number(value) || 0) * 8;
    return `${(bits / 1000 / 1000).toFixed(1)} Mbps`;
  }

  function stageText(row, state) {
    const native = nativeRow(row);
    return row?.stage || native.stage || row?.phase || native.phase ||
      (state === 'postprocessing' ? (row?.postprocess_note || native.postprocess_note || 'Preparing media…') : state);
  }

  function actionButtons(row, state) {
    const job = esc(row.external_id || row.id || '');
    if (['queued', 'downloading'].includes(state)) {
      return `<button class="btn small" data-native-act="pause" data-job="${job}">Pause</button><button class="btn small danger" data-native-act="cancel" data-job="${job}">Cancel</button>`;
    }
    if (state === 'postprocessing') {
      return `<button class="btn small danger" data-native-act="cancel" data-job="${job}">Cancel</button>`;
    }
    if (state === 'paused') {
      return `<button class="btn small primary" data-native-act="resume" data-job="${job}">Resume</button>`;
    }
    return '';
  }

  activityQueueHtml = function(rows) {
    if (!rows.length) return empty('No active downloads.');
    return `<div class="tablewrap" style="border:0;border-radius:0"><table class="table"><thead><tr><th>Scene</th><th>Stage</th><th>Progress</th><th>Attempts</th><th>Elapsed</th><th>Error</th><th></th></tr></thead><tbody>${rows.map(x => {
      const native = nativeRow(x);
      const state = x.client_status || x.status || native.status || 'queued';
      const pct = x.progress == null ? '—' : `${Number(x.progress).toFixed(1)}%`;
      const speed = x.speed_bps ? speedMbps(x.speed_bps) : '—';
      const eta = x.eta_seconds != null ? `${Math.floor(x.eta_seconds / 60)}m ${x.eta_seconds % 60}s` : '—';
      const done = x.downloaded_bytes != null ? bytes(x.downloaded_bytes) : '—';
      const total = x.total_bytes ? bytes(x.total_bytes) : '—';
      const error = x.error || native.error || '';
      const studio = x.studio || '';
      return `<tr data-live-job="${esc(x.external_id || x.id || '')}"><td><b class="live-title">${esc(x.scene_title || x.release_title || x.title || 'Download')}</b><small class="live-studio" style="display:block;margin-top:2px">${esc(studio)}</small></td><td><span class="state warn live-status">${esc(state)}</span></td><td><b class="live-pct">${pct}</b><small class="live-speed">${speed}</small><small class="live-bytes">${done} / ${total}</small><small class="live-eta">${eta !== '—' ? `ETA ${eta}` : ''}</small><div class="mini-progress" ${x.progress == null ? 'style="display:none"' : ''}><i class="live-bar" style="width:${Math.min(100, Number(x.progress || 0))}%"></i></div></td><td><b class="live-attempts">${attemptCount(x)}</b></td><td><b class="live-elapsed">${formatElapsed(elapsedSeconds(x))}</b></td><td><small class="live-error">${error ? esc(error) : '—'}</small></td><td><div class="actions live-actions">${actionButtons(x, state)}</div></td></tr>`;
    }).join('')}</tbody></table></div>`;
  };

  function syncOperationalFields(rows) {
    const byId = new Map((rows || []).map(x => [String(x.external_id || x.id || ''), x]));
    document.querySelectorAll('[data-live-job]').forEach(row => {
      const item = byId.get(String(row.dataset.liveJob || ''));
      if (!item) return;
      const native = nativeRow(item);
      const state = item.client_status || item.status || native.status || 'queued';
      const attempts = row.querySelector('.live-attempts');
      const elapsed = row.querySelector('.live-elapsed');
      const error = row.querySelector('.live-error');
      const stage = row.querySelector('.live-stage-detail');
      const speed = row.querySelector('.live-speed');
      if (attempts) attempts.textContent = String(attemptCount(item));
      if (elapsed) elapsed.textContent = formatElapsed(elapsedSeconds(item));
      if (error) error.textContent = item.error || native.error || '—';
      if (stage) stage.textContent = stageText(item, state);
      if (speed) speed.textContent = item.speed_bps ? speedMbps(item.speed_bps) : '—';
    });
  }

  applyLiveQueue = function(q) {
    baseApplyLiveQueue(q);
    const allRows = q?.tracked || [];
    const start = (activityQueuePage - 1) * ACTIVITY_QUEUE_PAGE_SIZE;
    syncOperationalFields(allRows.slice(start, start + ACTIVITY_QUEUE_PAGE_SIZE));
    syncDownloadPauseControl(q);
  };
})();
