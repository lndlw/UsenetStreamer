#!/usr/bin/env python3
"""Applies the 3 anchored text insertions for the active-streams admin panel
on top of an already-v1-patched UsenetStreamer checkout. Run from the repo root.
Safe to re-run: each insertion is skipped if already present."""

import sys

def patch_file(path, anchor, insertion, label):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if insertion.strip() in content:
        print(f"[SKIP] {label}: already applied")
        return True
    count = content.count(anchor)
    if count != 1:
        print(f"[FAIL] {label}: anchor found {count} times in {path} (expected exactly 1) — no changes made to this file")
        return False
    content = content.replace(anchor, anchor + insertion, 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"[OK] {label}: inserted into {path}")
    return True


ok = True

# --- 0. admin/index.html: fix stale "~15 minutes" text left over from before the TTL was shortened ---
ttl_old = 'A crashed/orphaned connection is force-released after ~15 minutes of no data flow.'
ttl_new = 'A crashed/orphaned connection is force-released after ~3 minutes of no data flow (or release it immediately from the Active Streams panel below).'
with open('admin/index.html', 'r', encoding='utf-8') as f:
    idx_content = f.read()
if ttl_new in idx_content:
    print("[SKIP] admin/index.html TTL text: already applied")
elif ttl_old in idx_content:
    idx_content = idx_content.replace(ttl_old, ttl_new, 1)
    with open('admin/index.html', 'w', encoding='utf-8') as f:
        f.write(idx_content)
    print("[OK] admin/index.html: fixed stale TTL text")
else:
    print("[WARN] admin/index.html: expected TTL text not found — skipping (not a blocker, cosmetic only)")

# --- 1. server.js: two new admin API routes ---
server_anchor = """    console.error('[ADMIN] Failed to delete profile', error);
    res.status(500).json({ error: 'Failed to delete profile' });
  }
});
"""
server_insertion = """
// Live view of every concurrently-active stream session (see streamConcurrency.js),
// for the dashboard's "Active Streams" panel — lets an admin see what's holding a
// profile's NZB_STREAM_LIMIT slots and manually free one instead of waiting for a
// player's stuck connection to hit the TTL backstop.
adminApiRouter.get('/stream-sessions', (req, res) => {
  res.json({ sessions: streamConcurrency.listActive() });
});

adminApiRouter.post('/stream-sessions/release', (req, res) => {
  const body = req.body || {};
  const profileKey = typeof body.profileKey === 'string' ? body.profileKey : '';
  const sessionKey = typeof body.sessionKey === 'string' ? body.sessionKey : '';
  if (!profileKey || !sessionKey) {
    res.status(400).json({ error: 'profileKey and sessionKey are required' });
    return;
  }
  const released = streamConcurrency.forceRelease(profileKey, sessionKey);
  if (!released) {
    res.status(404).json({ error: 'No matching active session' });
    return;
  }
  res.json({ success: true });
});
"""
ok = patch_file('server.js', server_anchor, server_insertion, 'server.js admin routes') and ok

# --- 2. admin/index.html: Active Streams panel markup ---
html_anchor = """      <p class="support-note">If you like this addon, please consider <a href="https://github.com/sponsors/Sanket9225" target="_blank" rel="noopener">sponsoring on GitHub</a>.</p>
"""
html_insertion = """
      <div class="group" id="activeStreamsPanel">
        <h3>Active Streams</h3>
        <p class="field-hint">Titles currently counted against each profile's Concurrent Stream Limit. If a player's "stop" doesn't cleanly close its connection, the slot self-releases within ~3 minutes of no data flow — or release it immediately here.</p>
        <div id="activeStreamsList"><p class="field-hint">Enter your token above and load configuration to see active streams.</p></div>
      </div>
"""
ok = patch_file('admin/index.html', html_anchor, html_insertion, 'admin/index.html panel markup') and ok

# --- 3. admin/app.js: panel logic + init() wiring ---
app_anchor = """  // Initialization
  function init() {
    const storedToken = getStoredToken();
    if (storedToken) {
      tokenInput.value = storedToken;
    }

    if (loadButton) {
      loadButton.addEventListener('click', () => {
        setStoredToken(tokenInput.value);
        loadConfiguration().then(() => {
          setupPatternPreview(); // Init preview after load
        });
      });
    }

    // ... other listeners ...
    if (saveButton) saveButton.addEventListener('click', handleSave);

    setupSectionCollapsers();
  }"""
app_replacement = """  // Active Streams panel: shows what's currently holding each profile's
  // NZB_STREAM_LIMIT slots, with a manual Release action for a session stuck
  // by a player that didn't cleanly close its connection (see
  // src/services/streamConcurrency.js — this is the same TTL/grace mechanism,
  // just surfaced so an admin doesn't have to wait it out or restart the addon).
  function fmtIdle(ms) {
    const s = Math.round(ms / 1000);
    if (s < 60) return s + 's';
    return Math.round(s / 60) + 'm';
  }

  async function refreshActiveStreams() {
    const listEl = document.getElementById('activeStreamsList');
    if (!listEl) return;
    if (!getToken()) return; // not loaded/authenticated yet
    let data;
    try {
      data = await apiRequest('/admin/api/stream-sessions');
    } catch (error) {
      listEl.innerHTML = `<p class="field-hint">Could not load active streams: ${error.message || 'request failed'}</p>`;
      return;
    }
    const sessions = (data && data.sessions) || [];
    if (sessions.length === 0) {
      listEl.innerHTML = '<p class="field-hint">No active streams right now.</p>';
      return;
    }
    listEl.innerHTML = '';
    const table = document.createElement('table');
    table.className = 'info-table';
    const thead = document.createElement('thead');
    thead.innerHTML = '<tr><th>Profile</th><th>Title</th><th>Connections</th><th>Status</th><th></th></tr>';
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    sessions.forEach((s) => {
      const tr = document.createElement('tr');
      const tdProfile = document.createElement('td');
      tdProfile.textContent = s.profileKey;
      const tdTitle = document.createElement('td');
      tdTitle.textContent = s.sessionKey;
      const tdConn = document.createElement('td');
      tdConn.textContent = String(s.openConnections);
      const tdStatus = document.createElement('td');
      tdStatus.textContent = s.openConnections > 0 ? 'streaming' : `idle ${fmtIdle(s.idleMs)} (grace)`;
      const tdAction = document.createElement('td');
      const releaseBtn = document.createElement('button');
      releaseBtn.type = 'button';
      releaseBtn.className = 'secondary';
      releaseBtn.textContent = 'Release';
      releaseBtn.addEventListener('click', async () => {
        releaseBtn.disabled = true;
        releaseBtn.textContent = 'Releasing\\u2026';
        try {
          await apiRequest('/admin/api/stream-sessions/release', {
            method: 'POST',
            body: JSON.stringify({ profileKey: s.profileKey, sessionKey: s.sessionKey }),
          });
        } catch (error) {
          // fall through to refresh either way \\u2014 the row will reflect current state
        }
        refreshActiveStreams();
      });
      tdAction.appendChild(releaseBtn);
      tr.append(tdProfile, tdTitle, tdConn, tdStatus, tdAction);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    listEl.appendChild(table);
  }

  // Initialization
  function init() {
    const storedToken = getStoredToken();
    if (storedToken) {
      tokenInput.value = storedToken;
    }

    if (loadButton) {
      loadButton.addEventListener('click', () => {
        setStoredToken(tokenInput.value);
        loadConfiguration().then(() => {
          setupPatternPreview(); // Init preview after load
          refreshActiveStreams();
        });
      });
    }

    // ... other listeners ...
    if (saveButton) saveButton.addEventListener('click', handleSave);

    setupSectionCollapsers();
    if (getToken()) refreshActiveStreams();
    setInterval(refreshActiveStreams, 15000);
  }"""

with open('admin/app.js', 'r', encoding='utf-8') as f:
    app_content = f.read()
if 'refreshActiveStreams' in app_content and 'function refreshActiveStreams' in app_content:
    print("[SKIP] admin/app.js: already applied")
else:
    count = app_content.count(app_anchor)
    if count != 1:
        print(f"[FAIL] admin/app.js init(): anchor found {count} times (expected exactly 1) — no changes made to this file")
        ok = False
    else:
        app_content = app_content.replace(app_anchor, app_replacement, 1)
        with open('admin/app.js', 'w', encoding='utf-8') as f:
            f.write(app_content)
        print("[OK] admin/app.js: panel logic + init() wiring inserted")

sys.exit(0 if ok else 1)
