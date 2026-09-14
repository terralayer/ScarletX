(() => {
  const dashboardTargets = {
    Scenes: 'scenes',
    Performers: 'performers',
    Studios: 'studios',
    Wanted: 'wanted',
    Storage: 'library',
  };

  function dashboardTarget(card) {
    const label = card.querySelector('small')?.textContent?.trim() || '';
    return dashboardTargets[label] || card.dataset.statGo || null;
  }

  function openDashboardTarget(target) {
    if (!target) return;
    if (['scenes', 'performers', 'studios'].includes(target)) {
      entityMode[target] = 'library';
    }
    view = target;
    nav();
    render();
  }

  // Capture the click before any late-loaded override can swallow or replace it.
  document.addEventListener('click', event => {
    const card = event.target.closest('#stats .dashboard-stat');
    if (!card) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    openDashboardTarget(dashboardTarget(card));
  }, true);

  // Explicitly restore the Performers column in every scene table, including
  // Recently Released Scenes on the dashboard.
  sceneTable = function(rows, inLibrary = false) {
    if (!rows.length) return empty('No scenes found.');
    return `<div class="tablewrap"><table class="table"><thead><tr><th>Scene</th><th>Studio</th><th>Performers</th><th>Status</th><th></th></tr></thead><tbody>${sceneRowsHtml(rows,inLibrary)}</tbody></table></div>`;
  };

  function compactStudioSrc(src) {
    try {
      const url = new URL(src, window.location.origin);
      const match = url.pathname.match(/^\/api\/artwork\/studios\/([^/]+)$/);
      if (!match) return null;
      return `/api/artwork/studios/${match[1]}/compact?v=v6`;
    } catch (_) {
      return null;
    }
  }

  function repairCompactStudioIcons(root = document) {
    root.querySelectorAll('.studio-logo img').forEach(img => {
      const replacement = compactStudioSrc(img.getAttribute('src') || img.src || '');
      if (replacement && img.getAttribute('src') !== replacement) {
        img.setAttribute('src', replacement);
      }
    });
  }

  // Keep newly rendered dashboard/scene rows on the transparent compact endpoint.
  const observer = new MutationObserver(mutations => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        if (node.matches?.('.studio-logo, .studio-logo img')) {
          repairCompactStudioIcons(node.parentElement || node);
        } else {
          repairCompactStudioIcons(node);
        }
      }
    }
  });

  observer.observe(document.documentElement, {childList: true, subtree: true});
  repairCompactStudioIcons();
})();
