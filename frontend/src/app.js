import { searchReels, saveReel, getReelStatus, getPlatformStats, listRecentReels } from './api.js';

// Application State
let activeTab = 'search';
let pendingReelPollInterval = null;

// DOM Elements
const searchForm = document.getElementById('search-form');
const searchInput = document.getElementById('search-input');
const saveForm = document.getElementById('save-form');
const reelUrlInput = document.getElementById('reel-url-input');
const resultsSection = document.getElementById('results-section');
const resultsGrid = document.getElementById('results-grid');
const resultsTitle = document.getElementById('results-title');
const confidenceBadge = document.getElementById('confidence-badge');
const latencyTag = document.getElementById('latency-tag');
const emptyState = document.getElementById('empty-state');
const emptyTitle = document.getElementById('empty-title');
const emptyMsg = document.getElementById('empty-message');
const statsBadge = document.getElementById('stats-badge');

// Navigation Tabs
const tabSearchBtn = document.getElementById('tab-search');
const tabSaveBtn = document.getElementById('tab-save');
const tabExploreBtn = document.getElementById('tab-explore');
const searchView = document.getElementById('search-view');
const saveView = document.getElementById('save-view');
const exploreView = document.getElementById('explore-view');
const exploreGrid = document.getElementById('explore-grid');
const brandHomeLink = document.getElementById('brand-home-link');

// Modal Elements
const inspectorModal = document.getElementById('inspector-modal');
const modalReelTitle = document.getElementById('modal-reel-title');
const modalMetaRow = document.getElementById('modal-meta-row');
const modalInspectorGrid = document.getElementById('modal-inspector-grid');
const modalJsonViewer = document.getElementById('modal-json-viewer');
const closeModalBtn = document.getElementById('btn-close-modal');

const RECENT_QUERIES_KEY = 'reelsearch_recent_queries_v1';

function getRecentQueries() {
  try {
    return JSON.parse(localStorage.getItem(RECENT_QUERIES_KEY) || '[]');
  } catch {
    return [];
  }
}

function saveRecentQuery(q) {
  if (!q || q.trim().length < 2) return;
  const cleanQ = q.trim();
  const list = getRecentQueries().filter(item => item.toLowerCase() !== cleanQ.toLowerCase());
  list.unshift(cleanQ);
  localStorage.setItem(RECENT_QUERIES_KEY, JSON.stringify(list.slice(0, 6)));
  renderRecentQueries();
}

function renderRecentQueries() {
  const wrap = document.getElementById('recent-queries-wrap');
  const container = document.getElementById('recent-queries-chips');
  if (!wrap || !container) return;

  const queries = getRecentQueries();
  if (queries.length === 0) {
    wrap.classList.add('hidden');
    container.innerHTML = '';
    return;
  }

  wrap.classList.remove('hidden');
  container.innerHTML = queries.map(q => `
    <button class="query-chip recent-chip" data-query="${escapeHtml(q)}">
      🔍 ${escapeHtml(q)}
    </button>
  `).join('');

  container.querySelectorAll('.recent-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.dataset.query;
      if (searchInput) searchInput.value = q;
      performSearch(q);
    });
  });
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  renderRecentQueries();
  refreshStats();
  if (searchInput) searchInput.focus();
});

function setupEventListeners() {
  brandHomeLink?.addEventListener('click', () => switchTab('search'));

  tabSearchBtn?.addEventListener('click', () => switchTab('search'));
  tabSaveBtn?.addEventListener('click', () => switchTab('save'));
  tabExploreBtn?.addEventListener('click', () => {
    switchTab('explore');
    loadRecentReels();
  });

  searchForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = searchInput.value.trim();
    if (query) {
      await performSearch(query);
    }
  });

  saveForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = reelUrlInput.value.trim();
    if (url) {
      await handleSaveReel(url);
    }
  });

  // Global Keyboard Shortcuts
  window.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== searchInput && document.activeElement !== reelUrlInput) {
      e.preventDefault();
      switchTab('search');
      searchInput.focus();
    }
    if (e.key === 'Escape') {
      closeModal();
    }
  });

  closeModalBtn?.addEventListener('click', closeModal);
  inspectorModal?.addEventListener('click', (e) => {
    if (e.target === inspectorModal) closeModal();
  });
}

function switchTab(tab) {
  activeTab = tab;
  [tabSearchBtn, tabSaveBtn, tabExploreBtn].forEach(b => b?.classList.remove('active'));
  [searchView, saveView, exploreView].forEach(v => v?.classList.add('hidden'));

  if (tab === 'search') {
    tabSearchBtn?.classList.add('active');
    searchView?.classList.remove('hidden');
    searchInput?.focus();
  } else if (tab === 'save') {
    tabSaveBtn?.classList.add('active');
    saveView?.classList.remove('hidden');
    reelUrlInput?.focus();
  } else if (tab === 'explore') {
    tabExploreBtn?.classList.add('active');
    exploreView?.classList.remove('hidden');
  }
}

async function performSearch(query) {
  setLoadingState(true);
  try {
    saveRecentQuery(query);
    const data = await searchReels(query, 4);
    renderSearchResults(data);
  } catch (err) {
    showToast(err.message, 'error');
    renderEmptyState("Search Error", err.message);
  } finally {
    setLoadingState(false);
  }
}

function renderSearchResults(data) {
  const { results, count, confidence, latency_ms, query } = data;
  resultsSection.classList.remove('hidden');
  resultsTitle.textContent = `Results for "${query}"`;
  latencyTag.textContent = `${latency_ms || 0}ms latency`;

  // Confidence Pill Styling
  confidenceBadge.textContent = `${confidence.toUpperCase()} CONFIDENCE`;
  confidenceBadge.className = `confidence-badge confidence-${confidence}`;

  if (!results || results.length === 0) {
    renderEmptyState(
      "No High-Confidence Matches",
      "Candidates were evaluated, but none passed the minimum precision threshold. Try searching for specific cars, cities, recipes, or actions."
    );
    return;
  }

  emptyState.classList.add('hidden');
  resultsGrid.innerHTML = '';

  // Strictly Max 4 Results
  const displayResults = results.slice(0, 4);

  displayResults.forEach((reel, index) => {
    const card = document.createElement('div');
    card.className = 'reel-card';

    const scorePct = Math.min(100, Math.round((reel.score || 0) * 100));

    const entitiesHtml = (reel.entities || []).slice(0, 3)
      .map(e => `<span class="context-chip entity">🏷️ ${escapeHtml(e)}</span>`).join('');
    const actionsHtml = (reel.actions || []).slice(0, 2)
      .map(a => `<span class="context-chip action">⚡ ${escapeHtml(a)}</span>`).join('');
    const topicsHtml = (reel.topics || []).slice(0, 2)
      .map(t => `<span class="context-chip topic">🌐 ${escapeHtml(t)}</span>`).join('');

    card.innerHTML = `
      <div>
        <div class="reel-card-header">
          <span class="rank-tag">#${index + 1} MATCH</span>
          <div class="match-score-pill">
            <div class="score-bar-bg">
              <div class="score-bar-fill" style="width: ${scorePct}%"></div>
            </div>
            <span>${scorePct}% MATCH</span>
          </div>
        </div>

        <h3 class="reel-title">${escapeHtml(reel.title || "Instagram Reel")}</h3>
        <p class="reel-summary">${escapeHtml(reel.summary || "Machine-indexed structured representation.")}</p>

        <div class="context-chips-wrap">
          ${entitiesHtml}
          ${actionsHtml}
          ${topicsHtml}
        </div>
      </div>

      <div class="reel-card-actions">
        <div style="display: flex; gap: 6px;">
          <button class="btn-inspect-act" data-reel-id="${reel.reel_id}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
              <line x1="8" y1="21" x2="16" y2="21"></line>
              <line x1="12" y1="17" x2="12" y2="21"></line>
            </svg>
            <span>Inspect Context</span>
          </button>
          <button class="btn-copy-link" data-url="${escapeHtml(reel.canonical_url)}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            <span>Copy</span>
          </button>
        </div>

        <a href="${reel.canonical_url}" target="_blank" rel="noopener noreferrer" class="btn-open-ig">
          <span>Instagram</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
            <polyline points="15 3 21 3 21 9"></polyline>
            <line x1="10" y1="14" x2="21" y2="3"></line>
          </svg>
        </a>
      </div>
    `;

    card.querySelector('.btn-inspect-act').addEventListener('click', () => {
      openInspector(reel.reel_id, reel.title);
    });

    card.querySelector('.btn-copy-link').addEventListener('click', () => {
      navigator.clipboard.writeText(reel.canonical_url).then(() => {
        showToast("Instagram URL copied to clipboard", "success");
      });
    });

    resultsGrid.appendChild(card);
  });
}

function renderEmptyState(title, message) {
  resultsGrid.innerHTML = '';
  emptyState.classList.remove('hidden');
  emptyTitle.textContent = title;
  emptyMsg.textContent = message;
}

function setLoadingState(isLoading) {
  const searchBtn = document.getElementById('search-btn');
  if (searchBtn) {
    searchBtn.disabled = isLoading;
    searchBtn.innerHTML = isLoading 
      ? '<span class="pulse-dot"></span> Searching...'
      : '<span>Search</span><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>';
  }
}

async function handleSaveReel(url) {
  const saveBtn = document.getElementById('save-btn');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Validating & Indexing...';

  try {
    const { data, status } = await saveReel(url);
    reelUrlInput.value = '';
    
    if (status === 200) {
      showToast('Reel already indexed and ready in search!', 'success');
      showSaveStatusCard(data, 'READY IN INDEX');
    } else {
      showToast('Reel accepted! Machine context worker is processing...', 'info');
      showSaveStatusCard(data, 'PROCESSING CONTEXT...');
      pollReelStatus(data.reel_id);
    }
    refreshStats();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    saveBtn.disabled = false;
    saveBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg><span>Save & Index Reel</span>';
  }
}

function showSaveStatusCard(reelData, statusLabel) {
  const statusContainer = document.getElementById('save-status-container');
  statusContainer.classList.remove('hidden');
  const isReady = statusLabel.includes('READY');
  statusContainer.innerHTML = `
    <div class="save-status-box ${isReady ? 'ready' : 'processing'}">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <span style="font-weight: 700;">Canonical URL:</span>
        <span id="save-status-badge" style="font-size: 11px; font-weight: 700; font-family: var(--font-mono);">
          ${statusLabel}
        </span>
      </div>
      <div style="font-family: var(--font-mono); font-size: 12px; word-break: break-all; color: var(--text-white);">
        ${escapeHtml(reelData.canonical_url)}
      </div>
      <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px; font-family: var(--font-mono);">
        ID: ${reelData.reel_id}
      </div>
    </div>
  `;
}

function pollReelStatus(reelId) {
  if (pendingReelPollInterval) clearInterval(pendingReelPollInterval);

  let attempts = 0;
  pendingReelPollInterval = setInterval(async () => {
    attempts++;
    try {
      const reel = await getReelStatus(reelId);
      const badge = document.getElementById('save-status-badge');
      if (badge) {
        badge.textContent = `STATUS: ${reel.status.toUpperCase()}`;
      }
      if (reel.status === 'ready') {
        clearInterval(pendingReelPollInterval);
        if (badge) {
          badge.textContent = 'READY IN INDEX';
          badge.style.color = '#34d399';
        }
        showToast('Enrichment and embeddings complete! Now searchable.', 'success');
        refreshStats();
      } else if (reel.status === 'failed' || attempts > 25) {
        clearInterval(pendingReelPollInterval);
        if (badge) {
          badge.textContent = 'FAILED';
          badge.style.color = '#f87171';
        }
      }
    } catch (e) {
      clearInterval(pendingReelPollInterval);
    }
  }, 2000);
}

async function openInspector(reelId, title) {
  inspectorModal.classList.add('open');
  inspectorModal.classList.add('active');
  modalReelTitle.textContent = title || "Machine Context Inspector";
  modalJsonViewer.textContent = "Loading structured representation from PostgreSQL...";
  modalInspectorGrid.innerHTML = '';
  modalMetaRow.innerHTML = `<span>Loading Reel ID ${reelId}...</span>`;

  try {
    const data = await getReelStatus(reelId);
    const ctx = data.context || {};

    modalMetaRow.innerHTML = `
      <span>Shortcode: <strong>${escapeHtml(data.instagram_shortcode || 'N/A')}</strong></span>
      <span>Status: <strong style="color: var(--accent-green-text);">${escapeHtml(data.status)}</strong></span>
      <span>Updated: ${escapeHtml(data.updated_at || 'Just now')}</span>
    `;

    // Render structured tags
    const renderCard = (label, items) => {
      const safeItems = Array.isArray(items) ? items : [];
      if (safeItems.length === 0) return '';
      const tags = safeItems.map(i => `<span class="inspector-tag">${escapeHtml(i)}</span>`).join('');
      return `
        <div class="inspector-card">
          <div class="inspector-card-label">${label}</div>
          <div class="inspector-tags-list">${tags}</div>
        </div>
      `;
    };

    modalInspectorGrid.innerHTML = `
      ${renderCard('Entities Detected', ctx.entities)}
      ${renderCard('Actions & Movements', ctx.actions)}
      ${renderCard('Objects in Scene', ctx.objects)}
      ${renderCard('Environments & Lighting', ctx.environments)}
      ${renderCard('Topics & Categories', ctx.topics)}
      ${renderCard('Visual Style', ctx.visual_style)}
    `;

    modalJsonViewer.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    modalJsonViewer.textContent = `Failed to load context: ${err.message}`;
  }
}

function closeModal() {
  inspectorModal.classList.remove('open');
  inspectorModal.classList.remove('active');
}

async function loadRecentReels() {
  exploreGrid.innerHTML = '<div style="color: var(--text-muted); padding: 20px;">Loading indexed Reels...</div>';
  try {
    const res = await listRecentReels(12);
    if (!res.reels || res.reels.length === 0) {
      exploreGrid.innerHTML = '<div style="color: var(--text-muted); padding: 20px;">No Reels indexed yet. Save one in the "Save Reel" tab!</div>';
      return;
    }
    exploreGrid.innerHTML = '';
    res.reels.forEach(r => {
      const card = document.createElement('div');
      card.className = 'reel-card';
      card.innerHTML = `
        <div>
          <div style="font-size: 11px; font-weight: 700; color: var(--accent-green-text); font-family: var(--font-mono); margin-bottom: 6px;">
            ${r.status === 'ready' ? 'READY IN INDEX' : 'PROCESSING'}
          </div>
          <h4 style="font-size: 15px; font-weight: 700; color: var(--text-white); margin-bottom: 8px;">
            ${escapeHtml(r.summary)}
          </h4>
          <div style="font-size: 12px; color: var(--text-muted); font-family: var(--font-mono); word-break: break-all;">
            ${escapeHtml(r.canonical_url)}
          </div>
        </div>
        <div class="reel-card-actions" style="margin-top: 14px;">
          <button class="btn-inspect-act btn-explore-inspect" data-id="${r.reel_id}">
            Inspect
          </button>
          <a href="${r.canonical_url}" target="_blank" rel="noopener noreferrer" class="btn-open-ig">
            Open on Instagram ↗
          </a>
        </div>
      `;
      card.querySelector('.btn-explore-inspect').addEventListener('click', () => {
        openInspector(r.reel_id, r.summary);
      });
      exploreGrid.appendChild(card);
    });
  } catch (e) {
    exploreGrid.innerHTML = `<div style="color: var(--accent-red-text); padding: 20px;">Error: ${e.message}</div>`;
  }
}

async function refreshStats() {
  try {
    const stats = await getPlatformStats();
    if (statsBadge) {
      const count = stats.ready_reels || 0;
      statsBadge.textContent = `${count} Indexed Reel${count === 1 ? '' : 's'}`;
    }
  } catch (e) {
    console.debug('Failed to load stats:', e);
  }
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type === 'error' ? 'toast-error' : type === 'success' ? 'toast-success' : ''}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 250);
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
