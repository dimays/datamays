export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function h(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const fmt = n => Number(n).toLocaleString('en-US');

export function debounce(fn, ms) {
  let t;
  const d = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  d.flush = (...a) => { clearTimeout(t); fn(...a); };
  d.cancel = () => clearTimeout(t);
  return d;
}

export function bytesToB64(u8) {
  let s = '';
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
}
export function b64ToBytes(b64, len) {
  const out = new Uint8Array(len);
  if (!b64) return out;
  const s = atob(b64);
  for (let i = 0; i < Math.min(len, s.length); i++) out[i] = s.charCodeAt(i);
  return out;
}

export function duration(sec) {
  sec = Math.round(sec || 0);
  const hh = Math.floor(sec / 3600), mm = Math.floor(sec % 3600 / 60);
  if (hh) return `${hh}h ${mm}m`;
  if (mm) return `${mm}m`;
  return `${sec}s`;
}

export function timeAgo(ts) {
  const s = (Date.now() - ts) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} hr ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? 'yesterday' : `${d} days ago`;
}

export const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

let toastTimer;
export function toast(html, { action, onAction, ms = 3800 } = {}) {
  // Inside a case, messages go in a reserved strip above the book so they never
  // cover names or buttons; elsewhere they float at the bottom of the window.
  const el = document.getElementById('toast-slot') || $('#toast');
  el.innerHTML = `<span>${html}</span>${action ? `<button class="btn small">${esc(action)}</button>` : ''}`;
  el.classList.add('show');
  if (action) el.querySelector('button').onclick = () => { el.classList.remove('show'); onAction?.(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}

/** A modal dialog. Resolves with the value passed to close(). */
export function modal({ title, body, actions = [], wide = false, onOpen, dismissable = true, className = '' }) {
  return new Promise(resolve => {
    const root = h(`<div class="modal-backdrop"><div class="modal ${wide ? 'wide' : ''} ${className}" role="dialog" aria-modal="true">
      ${title ? `<h2 class="modal-title">${title}</h2>` : ''}
      <div class="modal-body"></div>
      <div class="modal-actions"></div>
    </div></div>`);
    const bodyEl = root.querySelector('.modal-body');
    if (typeof body === 'string') bodyEl.innerHTML = body; else if (body) bodyEl.append(body);
    const close = v => { root.remove(); document.removeEventListener('keydown', onKey, true); resolve(v); };
    const onKey = e => { if (e.key === 'Escape' && dismissable) { e.stopPropagation(); close(null); } };
    for (const a of actions) {
      const b = h(`<button class="btn ${a.primary ? 'primary' : ''} ${a.danger ? 'danger' : ''}">${a.label}</button>`);
      b.onclick = () => a.onClick ? a.onClick(close, root) : close(a.value);
      root.querySelector('.modal-actions').append(b);
    }
    if (!actions.length) root.querySelector('.modal-actions').remove();
    if (dismissable) root.addEventListener('pointerdown', e => { if (e.target === root) close(null); });
    document.addEventListener('keydown', onKey, true);
    document.body.append(root);
    onOpen?.(root, close);
    (root.querySelector('[autofocus]') || root.querySelector('.btn.primary'))?.focus();
  });
}
