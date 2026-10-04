/**
 * ReelSearch API Client
 */

const API_BASE = window.location.origin.includes('8000') 
  ? '' 
  : 'http://localhost:8000';

export async function searchReels(query, limit = 4) {
  const url = `${API_BASE}/api/v1/search?q=${encodeURIComponent(query)}&limit=${limit}`;
  const res = await fetch(url);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.error?.message || `Search failed with status ${res.status}`);
  }
  return await res.json();
}

export async function saveReel(rawUrl) {
  const url = `${API_BASE}/api/v1/reels`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: rawUrl })
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error?.message || `Failed to save Reel (${res.status})`);
  }
  return { data, status: res.status };
}

export async function getReelStatus(reelId) {
  const url = `${API_BASE}/api/v1/reels/${reelId}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to check reel status: ${res.status}`);
  }
  return await res.json();
}

export async function getSystemReadiness() {
  const url = `${API_BASE}/ready`;
  const res = await fetch(url);
  return await res.json();
}

export async function getPlatformStats() {
  const url = `${API_BASE}/api/v1/stats`;
  const res = await fetch(url);
  return await res.json();
}

export async function listRecentReels(limit = 12) {
  const url = `${API_BASE}/api/v1/reels?limit=${limit}`;
  const res = await fetch(url);
  return await res.json();
}

export async function recordSearchEvent(eventPayload) {
  try {
    await fetch(`${API_BASE}/api/v1/search/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(eventPayload)
    });
  } catch (e) {
    console.debug('Failed to record search event:', e);
  }
}
