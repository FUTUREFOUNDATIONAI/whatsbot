// ── Avatar URL (with cache-busting version) ──────────────────────
// `v` is the cached file's mtime (avatar_v from the API); appending it makes
// the browser re-fetch when the photo changes instead of using the stale image.
// `v` is 0 when no photo is cached for the contact yet: there is nothing to
// download, so return null and let the silhouette stand in (asking for it would
// only produce a 404). Once the photo is fetched the server sends `avatar_v`
// (list refresh or `avatar_updated`) and the image appears.
export function avatarUrl(phone, v) {
  if (!phone || !v) return null;
  return `/statics/avatars/${phone}.jpg?v=${v}`;
}

// ── Phone formatting ─────────────────────────────────────────────

// 5585973605591 → +55 (85) 97360-5591
export function formatPhoneDisplay(phone) {
  if (!phone || phone.length < 12) return phone;
  return `+${phone.slice(0, 2)} (${phone.slice(2, 4)}) ${phone.slice(4, 9)}-${phone.slice(9)}`;
}

// ── Time formatting ──────────────────────────────────────────────

// Building an Intl formatter is far more expensive than using one, and
// `toLocale*String(locale, opts)` builds a fresh one on every call. A chat with
// hundreds of bubbles formats hundreds of times per render, so the formatters
// are created once per option set and reused (same output as the old calls).
const _dtfCache = new Map();
function _dtf(opts) {
  const key = JSON.stringify(opts);
  let f = _dtfCache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat('pt-BR', opts);
    _dtfCache.set(key, f);
  }
  return f;
}
const _TIME = { hour: '2-digit', minute: '2-digit' };

export function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  const diffDays = Math.floor((now - d) / 86400000);
  if (diffDays === 0) return _dtf(_TIME).format(d);
  if (diffDays === 1) return 'Ontem';
  if (diffDays < 7) return _dtf({ weekday: 'short' }).format(d);
  return _dtf({ day: '2-digit', month: '2-digit' }).format(d);
}

export function formatBubbleTime(ts) {
  if (!ts) return '';
  return _dtf(_TIME).format(new Date(ts * 1000));
}

export function isSameDay(tsA, tsB) {
  if (!tsA || !tsB) return false;
  const a = new Date(tsA * 1000);
  const b = new Date(tsB * 1000);
  return a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate();
}

// ── Messages ─────────────────────────────────────────────────────

// True when two messages are the same logical message — used to dedupe a
// WebSocket-delivered message against an optimistic/already-loaded bubble.
export function isSameMessage(a, b) {
  if (!a || !b || a.role !== b.role) return false;
  if (a.ts === b.ts) return true;
  return a.content === b.content && Math.abs((a.ts || 0) - (b.ts || 0)) < 30;
}

export function formatDateSeparator(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const diffDays = Math.round((startOfDay(now) - startOfDay(d)) / 86400000);
  if (diffDays === 0) return 'HOJE';
  if (diffDays === 1) return 'ONTEM';
  if (diffDays >= 2 && diffDays <= 6) {
    return _dtf({ weekday: 'long' }).format(d);
  }
  const sameYear = d.getFullYear() === now.getFullYear();
  return _dtf(sameYear
    ? { day: 'numeric', month: 'long' }
    : { day: 'numeric', month: 'long', year: 'numeric' }).format(d);
}
