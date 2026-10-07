// Enrolled-user search on /search. Extracted from the inline script that used
// to be embedded in src/main.py.
async function searchUsers(query) {
  const list = document.querySelector('#search-results-list');
  if (!list) return;
  const trimmed = (query || '').trim().toLowerCase();
  if (!trimmed) {
    list.innerHTML = '';
    return;
  }
  try {
    const res = await fetch('/api/presence');
    if (!res.ok) return;
    const data = await res.json();
    const matches = (data.people || []).filter((p) => p.name.toLowerCase().includes(trimmed));
    if (matches.length === 0) {
      list.innerHTML = '<p style="color: var(--display-muted);">No enrolled users found.</p>';
      return;
    }
    list.innerHTML = matches
      .map(
        (m) => `
          <div style="padding: 12px 16px; border-bottom: 1px solid var(--display-border); display: flex; justify-content: space-between; align-items: center;">
              <span style="font-weight: 500;">${m.name}</span>
              <span style="color: var(--display-muted); font-size: 0.875rem;">${(m.access || []).join(', ')}</span>
          </div>
      `,
      )
      .join('');
  } catch (e) {}
}

function initSearch() {
  const input = document.querySelector('#search-user-input');
  const list = document.querySelector('#search-results-list');
  if (!input || !list) {
    window.requestAnimationFrame(initSearch);
    return;
  }
  input.addEventListener('input', () => searchUsers(input.value));
}

initSearch();
