// Tracks concurrently PLAYING titles per profile, so NZB_STREAM_LIMIT caps how
// many streams a profile can have active at once — not how many stream options
// Stremio lists.
//
// A "session" is one profile watching one title (type:id). A single title can
// have many overlapping HTTP requests in flight at once (Stremio/mpv opens a
// new Range request on every seek, and re-requests on brief reconnects), so we
// count DISTINCT (profile, type:id) pairs, not raw HTTP connections. Multiple
// connections for the same title share one slot.
//
// A slot is normally freed a short grace period after the LAST open connection
// for that session closes (see GRACE_MS), so a seek — which briefly closes one
// Range request before opening the next — never lets a different title sneak
// into the freed slot mid-watch.
//
// That path relies on the HTTP response actually emitting 'close'/'finish'. If
// a client crashes, or a player's "stop" doesn't cleanly abort the underlying
// HTTP request (common — many players just stop reading rather than closing
// the connection), or the network drops without a clean TCP close, that event
// can be delayed indefinitely (or, in rare proxy/keep-alive configurations,
// never arrive), which would pin a slot forever. HARD_TTL_MS is the backstop:
// every open connection is expected to touch its session periodically via real
// data flow (see touch()); a session that goes quiet for longer than the TTL
// is force-expired by the sweep below, regardless of what openConnections says.
// Kept short (a few minutes, not tens of minutes) so a profile — especially
// one with a tight limit like 1 — self-heals from a stuck "stop" at
// interactive speed instead of leaving someone locked out. See also
// listActive()/forceRelease() for an immediate manual override.

const GRACE_MS = 45 * 1000;
const HARD_TTL_MS = 3 * 60 * 1000; // no data flow for this long => treat as dead
const SWEEP_INTERVAL_MS = 30 * 1000;

// profileKey -> Map<sessionKey, { openConnections: number, graceTimer: Timeout|null, lastActivity: number }>
const activeByProfile = new Map();

function sessionsFor(profileKey) {
  let sessions = activeByProfile.get(profileKey);
  if (!sessions) {
    sessions = new Map();
    activeByProfile.set(profileKey, sessions);
  }
  return sessions;
}

// Attempts to start (or join) a streaming session for sessionKey under profileKey.
// Returns { allowed, release }. If allowed is false, no slot was taken — the
// caller should reject the request without calling release(). If allowed is
// true, the caller MUST call release() exactly once when its connection to the
// client ends (on 'close', 'finish', or error), regardless of outcome, and
// SHOULD call touch(profileKey, sessionKey) periodically while bytes are still
// flowing (e.g. on every res.write) so the hard-TTL sweep doesn't mistake an
// active stream for a stalled one.
function acquire(profileKey, sessionKey, limit) {
  const sessions = sessionsFor(profileKey);
  let entry = sessions.get(sessionKey);

  if (!entry) {
    // A new title for this profile only needs a free slot; reconnects/seeks on
    // an already-active title never get blocked by the limit.
    if (Number.isFinite(limit) && limit > 0 && sessions.size >= limit) {
      return { allowed: false, release: () => {} };
    }
    entry = { openConnections: 0, graceTimer: null, lastActivity: Date.now() };
    sessions.set(sessionKey, entry);
  }

  if (entry.graceTimer) {
    clearTimeout(entry.graceTimer);
    entry.graceTimer = null;
  }
  entry.openConnections += 1;
  entry.lastActivity = Date.now();

  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    entry.openConnections = Math.max(0, entry.openConnections - 1);
    if (entry.openConnections === 0) {
      entry.graceTimer = setTimeout(() => {
        const current = sessions.get(sessionKey);
        if (current === entry && entry.openConnections === 0) {
          sessions.delete(sessionKey);
        }
        if (sessions.size === 0) {
          activeByProfile.delete(profileKey);
        }
      }, GRACE_MS);
      if (typeof entry.graceTimer.unref === 'function') entry.graceTimer.unref();
    }
  };

  return { allowed: true, release };
}

// Refreshes a session's last-activity timestamp. Call this on real data flow
// (e.g. each res.write) for an open connection — NOT on a fixed timer — so the
// hard TTL only forgives sessions that are genuinely still moving bytes.
function touch(profileKey, sessionKey) {
  const sessions = activeByProfile.get(profileKey);
  const entry = sessions && sessions.get(sessionKey);
  if (entry) entry.lastActivity = Date.now();
}

// True if sessionKey already has an active (or grace-window) slot for profileKey.
// Used to exempt resuming/re-listing the SAME title from a capacity check meant
// for NEW titles.
function isSessionActive(profileKey, sessionKey) {
  const sessions = activeByProfile.get(profileKey);
  return Boolean(sessions && sessions.has(sessionKey));
}

// Number of distinct titles currently active (or in their grace window) for a profile.
function activeCount(profileKey) {
  const sessions = activeByProfile.get(profileKey);
  return sessions ? sessions.size : 0;
}

// Snapshot of every active session across all profiles, for the admin dashboard.
// Returns plain objects (no live references) so callers can't mutate internal state.
function listActive() {
  const now = Date.now();
  const out = [];
  activeByProfile.forEach((sessions, profileKey) => {
    sessions.forEach((entry, sessionKey) => {
      out.push({
        profileKey,
        sessionKey,
        openConnections: entry.openConnections,
        idleMs: now - entry.lastActivity,
      });
    });
  });
  return out;
}

// Manually frees a session immediately, regardless of openConnections or the
// TTL — used by the admin dashboard's "Release" action so a stuck session
// (e.g. a player's "stop" that didn't cleanly close the connection) doesn't
// have to wait out the TTL sweep. Returns true if a session was actually
// removed, false if there was nothing to release.
function forceRelease(profileKey, sessionKey) {
  const sessions = activeByProfile.get(profileKey);
  const entry = sessions && sessions.get(sessionKey);
  if (!entry) return false;
  if (entry.graceTimer) clearTimeout(entry.graceTimer);
  sessions.delete(sessionKey);
  if (sessions.size === 0) activeByProfile.delete(profileKey);
  console.log(`[STREAM-LIMIT] Manually released session "${sessionKey}" for profile "${profileKey}"`);
  return true;
}

// Backstop sweep: force-expire any session that's had zero data flow for
// longer than HARD_TTL_MS, even if we never saw its connection(s) close. This
// only fires for genuinely stuck/orphaned sessions — any session with real
// playback traffic gets touch()'d far more often than the TTL window.
function sweepExpired() {
  const now = Date.now();
  activeByProfile.forEach((sessions, profileKey) => {
    sessions.forEach((entry, sessionKey) => {
      if (now - entry.lastActivity > HARD_TTL_MS) {
        console.warn(`[STREAM-LIMIT] Force-expiring stale session "${sessionKey}" for profile "${profileKey}" — no activity for over ${Math.round(HARD_TTL_MS / 60000)} min (likely a crashed/orphaned connection)`);
        if (entry.graceTimer) clearTimeout(entry.graceTimer);
        sessions.delete(sessionKey);
      }
    });
    if (sessions.size === 0) activeByProfile.delete(profileKey);
  });
}

const sweepTimer = setInterval(sweepExpired, SWEEP_INTERVAL_MS);
if (typeof sweepTimer.unref === 'function') sweepTimer.unref();

module.exports = { acquire, touch, isSessionActive, activeCount, listActive, forceRelease, sweepExpired, GRACE_MS, HARD_TTL_MS };
