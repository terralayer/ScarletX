(() => {
  let queued = false;

  const icons = {
    performers: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="7" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></svg>',
    scenes: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8h18v12H3z"/><path d="m5 8 2-4h4l-2 4m4 0 2-4h4l-2 4"/><path d="m10 12 5 3-5 3z"/></svg>',
    studios: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 21h18M5 21V8l7-5 7 5v13M9 10h2m2 0h2M9 14h2m2 0h2M11 21v-4h2v4"/></svg>',
    calendar: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4m8-4v4M3 10h18"/></svg>',
    downloads: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 20h16"/></svg>'
  };

  function statValueByLabel(label) {
    const card = [...document.querySelectorAll('#stats .stat')].find((node) => node.querySelector('small')?.textContent?.trim() === label);
    return card?.querySelector('strong')?.textContent?.trim() || '0';
  }

  function approvedStat(icon, label, value, sub, target) {
    return `<button type="button" class="stat dashboard-stat" data-stat-go="${target}"><div class="stat-icon">${icon}</div><div><small>${label}</small><strong>${value}</strong><em>${sub}</em></div></button>`;
  }

  function buildRecentList() {
    const root = document.querySelector('#recentScenes');
    if (!root || root.querySelector('.approved-recent-list')) return;
    const rows = [...root.querySelectorAll('tbody tr')].slice(0, 5);
    if (!rows.length) return;
    root.innerHTML = `<div class="approved-recent-list">${rows.map((row, index) => {
      const title = row.querySelector('.scene-title')?.textContent?.trim() || 'Untitled';
      const sceneId = row.dataset.sceneId || '';
      const localId = row.dataset.localId || '';
      const img = row.querySelector('.scene-thumb img')?.getAttribute('src') || '';
      const studio = row.querySelector('td:nth-child(2)')?.textContent?.trim() || 'Unknown studio';
      const release = row.querySelector('.dashboard-release-date')?.textContent?.trim() || '';
      return `<div class="approved-recent-row" data-scene-id="${sceneId}" data-local-id="${localId}"><button class="approved-recent-thumb" data-scene-detail aria-label="Open ${title.replaceAll('"','&quot;')}">${img ? `<img src="${img}" alt="" loading="lazy">` : ''}</button><div class="approved-recent-copy"><button class="approved-recent-title" data-scene-detail>${title}</button><div class="approved-recent-meta">${studio}</div></div><div class="approved-recent-date">${release}${index < 2 ? '<span class="approved-new-badge">NEW</span>' : ''}</div></div>`;
    }).join('')}</div>`;
  }

  function wireShortcutNavigation() {
    const discover = document.querySelector('[data-approved-nav="discover"]');
    if (discover && !discover.dataset.bound) {
      discover.dataset.bound = '1';
      discover.addEventListener('click', () => {
        view = 'scenes';
        entityMode.scenes = 'search';
        nav();
        renderEntities('scenes');
      });
    }

    const indexers = document.querySelector('[data-approved-nav="indexers"]');
    if (indexers && !indexers.dataset.bound) {
      indexers.dataset.bound = '1';
      indexers.addEventListener('click', async () => {
        view = 'settings';
        nav();
        await render();
        requestAnimationFrame(() => {
          const candidates = [...document.querySelectorAll('#app button')];
          const target = candidates.find((button) => /indexer/i.test(button.textContent || ''));
          if (target) target.click();
        });
      });
    }
  }

  function applyApprovedDashboardLayout() {
    wireShortcutNavigation();
    const app = document.querySelector('#app');
    if (!app || typeof view === 'undefined' || view !== 'dashboard') return;

    const pagehead = app.querySelector('.pagehead');
    if (pagehead) pagehead.classList.add('dashboard-pagehead');

    if (!app.querySelector('.dashboard-hero')) {
      const hero = document.createElement('section');
      hero.className = 'dashboard-hero';
      hero.innerHTML = '<div class="dashboard-hero-copy"><h1>Welcome to <span>ScarletX</span></h1><p>Discover. Monitor. Organize. Enjoy.</p></div>';
      const stats = app.querySelector('#stats');
      if (stats) stats.before(hero); else app.prepend(hero);
    }

    const stats = app.querySelector('#stats');
    if (stats && !stats.classList.contains('approved-stat-grid') && stats.children.length) {
      const performers = statValueByLabel('Performers');
      const scenes = statValueByLabel('Scenes');
      const studios = statValueByLabel('Studios');
      const upcoming = String(app.querySelectorAll('#calendarRows .row').length || 0);
      const downloads = document.querySelector('#queueBadge')?.textContent?.trim() || '0';
      stats.classList.add('approved-stat-grid');
      stats.innerHTML = [
        approvedStat(icons.performers, 'Performers', performers, 'Monitored performers', 'performers'),
        approvedStat(icons.scenes, 'Scenes', scenes, 'In your library', 'library'),
        approvedStat(icons.studios, 'Studios', studios, 'Tracked studios', 'studios'),
        approvedStat(icons.calendar, 'Upcoming', upcoming, 'Scenes this month', 'calendar'),
        approvedStat(icons.downloads, 'Downloads', downloads, 'In progress', 'activity')
      ].join('');
      if (typeof bindDashboardStats === 'function') bindDashboardStats();
    }

    const dashgrid = app.querySelector('.dashgrid');
    const recent = app.querySelector('.panel.recent');
    const upcomingPanel = dashgrid?.querySelector('.panel:nth-child(3)');
    if (dashgrid && recent && upcomingPanel && !app.querySelector('.approved-dashboard-grid')) {
      const grid = document.createElement('div');
      grid.className = 'approved-dashboard-grid';
      dashgrid.before(grid);
      grid.append(recent, upcomingPanel);
      upcomingPanel.classList.add('approved-upcoming');
      dashgrid.classList.add('dashboard-secondary-panels');
      const recentTitle = recent.querySelector('.panel-head h2');
      const recentLink = recent.querySelector('.linkbtn');
      const upcomingTitle = upcomingPanel.querySelector('.panel-head h2');
      const upcomingLink = upcomingPanel.querySelector('.linkbtn');
      if (recentTitle) recentTitle.textContent = 'Recent Scenes';
      if (recentLink) recentLink.textContent = 'View All';
      if (upcomingTitle) upcomingTitle.textContent = 'Upcoming Releases';
      if (upcomingLink) upcomingLink.textContent = 'View Calendar';
    }

    buildRecentList();
  }

  function scheduleApprovedDashboardLayout() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      applyApprovedDashboardLayout();
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    wireShortcutNavigation();
    const tagline = document.querySelector('.header-tagline');
    if (tagline) tagline.textContent = 'Your Adult Media Library, Automated.';
    const app = document.querySelector('#app');
    if (app) new MutationObserver(scheduleApprovedDashboardLayout).observe(app, {childList:true, subtree:true, characterData:true});
    scheduleApprovedDashboardLayout();
  });
})();
