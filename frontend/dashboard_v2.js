(() => {
  const icons = {
    performers: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="7" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></svg>',
    scenes: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8h18v12H3z"/><path d="m5 8 2-4h4l-2 4m4 0 2-4h4l-2 4"/><path d="m10 12 5 3-5 3z"/></svg>',
    studios: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 21h18M5 21V8l7-5 7 5v13M9 10h2m2 0h2M9 14h2m2 0h2M11 21v-4h2v4"/></svg>',
    calendar: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4m8-4v4M3 10h18"/></svg>',
    downloads: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 20h16"/></svg>'
  };

  function stat(icon, label, value, detail, target) {
    return `<button type="button" class="stat dashboard-stat" data-stat-go="${target}"><div class="stat-icon">${icon}</div><div><small>${label}</small><strong>${value}</strong><em>${detail}</em></div></button>`;
  }

  function studioName(scene) {
    if (!scene?.studio) return 'Unknown studio';
    return typeof scene.studio === 'string' ? scene.studio : (scene.studio.name || 'Unknown studio');
  }

  function recentSceneRows(scenes) {
    if (!scenes.length) return empty('No downloaded scenes yet.');
    return `<div class="approved-recent-list">${scenes.slice(0, 5).map((scene, index) => {
      const tpdbId = scene.tpdb_id || scene.id;
      const localId = scene.id || '';
      const title = scene.title || 'Untitled';
      const art = sceneImage(scene) ? `/api/artwork/scenes/${encodeURIComponent(tpdbId)}?size=card` : '';
      return `<div class="approved-recent-row" data-dashboard-scene="${esc(localId)}"><button type="button" class="approved-recent-thumb" data-dashboard-scene="${esc(localId)}" aria-label="Open ${esc(title)}">${art ? `<img src="${esc(art)}" alt="" loading="lazy" onerror="this.remove()">` : ''}</button><div class="approved-recent-copy"><button type="button" class="approved-recent-title" data-dashboard-scene="${esc(localId)}">${esc(title)}</button><div class="approved-recent-meta">${esc(studioName(scene))}</div></div><div class="approved-recent-date">${fmtDate(scene.release_date)}${index < 2 ? '<span class="approved-new-badge">NEW</span>' : ''}</div></div>`;
    }).join('')}</div>`;
  }

  function upcomingRows(rows) {
    if (!rows.length) return `<div class="row"><div class="rowicon">—</div><div><b>No upcoming releases</b><small>Monitored release dates will appear here.</small></div></div>`;
    return rows.slice(0, 5).map(item => {
      const day = String(item.date || '').slice(8, 10).replace(/^0/, '') || '—';
      return `<div class="row"><div class="rowicon">${esc(day)}</div><div><b>${esc(item.title || 'Upcoming scene')}</b><small>${fmtDate(item.date)}</small></div><span class="badge soft">Scene</span></div>`;
    }).join('');
  }

  dashboard = async function dashboard() {
    const app = $('#app');
    app.innerHTML = `
      <section class="dashboard-hero">
        <div class="dashboard-hero-copy">
          <h1>Welcome to <span>ScarletX</span></h1>
          <p>Discover. Monitor. Organize. Enjoy.</p>
        </div>
      </section>
      <div class="stats approved-stat-grid" id="stats">
        ${stat(icons.performers, 'Performers', '—', 'Monitored performers', 'performers')}
        ${stat(icons.scenes, 'Scenes', '—', 'In your library', 'library')}
        ${stat(icons.studios, 'Studios', '—', 'Tracked studios', 'studios')}
        ${stat(icons.calendar, 'Upcoming', '—', 'Scenes this month', 'calendar')}
        ${stat(icons.downloads, 'Downloads', '—', 'In progress', 'activity')}
      </div>
      <div class="approved-dashboard-grid">
        <section class="panel recent">
          <div class="panel-head"><h2>Recent Scenes</h2><button class="linkbtn" type="button" data-go="library">View All</button></div>
          <div id="recentScenes"></div>
        </section>
        <section class="panel approved-upcoming">
          <div class="panel-head"><h2>Upcoming Releases</h2><button class="linkbtn" type="button" data-go="calendar">View Calendar</button></div>
          <div class="rows" id="calendarRows"></div>
        </section>
      </div>`;

    bindDashboardStats();

    app.onclick = event => {
      const scene = event.target.closest('[data-dashboard-scene]');
      if (scene) {
        const localId = Number(scene.dataset.dashboardScene || 0);
        if (localId) openLocalScene(localId);
        return;
      }
      const go = event.target.closest('[data-go]');
      if (!go) return;
      const target = go.dataset.go;
      if (['scenes', 'performers', 'studios'].includes(target)) entityMode[target] = 'library';
      view = target;
      nav();
      render();
    };

    try {
      const [sys, recent, cal, queue] = await Promise.all([
        api('/api/system/status'),
        api('/api/dashboard/scenes?limit=8'),
        api('/api/calendar?limit=5'),
        api('/api/activity/queue').catch(() => ({tracked: []}))
      ]);
      if (view !== 'dashboard') return;

      const scenes = recent.items || [];
      const calendar = cal || [];
      const downloads = (queue.tracked || []).length;
      libraryCache = scenes;

      $('#stats').innerHTML = [
        stat(icons.performers, 'Performers', sys.performers || 0, 'Monitored performers', 'performers'),
        stat(icons.scenes, 'Scenes', recent.total || 0, 'In your library', 'library'),
        stat(icons.studios, 'Studios', sys.studios || 0, 'Tracked studios', 'studios'),
        stat(icons.calendar, 'Upcoming', calendar.length, 'Scenes this month', 'calendar'),
        stat(icons.downloads, 'Downloads', downloads, 'In progress', 'activity')
      ].join('');
      bindDashboardStats();

      $('#recentScenes').innerHTML = recentSceneRows(scenes);
      $('#calendarRows').innerHTML = upcomingRows(calendar);
      $('#queueBadge').textContent = downloads;
    } catch (error) {
      if (view !== 'dashboard') return;
      notify(error.message, 'error');
    }
  };
})();
