// Talks to the local server — or, when the Register is served as plain files
// from a website, to the browser's own storage (store.js). Games are also
// mirrored to localStorage so a crash or a stopped server never costs
// progress; the newer copy wins.
import { storeRequest } from './store.js';

/** True when saves live in this browser rather than with a local server. */
export const IN_BROWSER = document.documentElement.dataset.storage === 'browser';

async function serverReq(method, url, body, opts = {}) {
  const r = await fetch(url, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined, ...opts,
    // Browsers refuse keepalive bodies over 64KB; big saves go normally (localStorage keeps a copy regardless).
    keepalive: !!opts.keepalive && (body ? JSON.stringify(body).length : 0) < 60000,
  });
  if (!r.ok) { const e = new Error(`${method} ${url} → ${r.status}`); e.status = r.status; throw e; }
  return r.json();
}

const req = IN_BROWSER ? storeRequest : serverReq;

const LS = 'register:game:';
const lsGet = id => { try { return JSON.parse(localStorage.getItem(LS + id)); } catch { return null; } };
const lsSet = g => { try { localStorage.setItem(LS + g.id, JSON.stringify(g)); } catch { /* storage full or blocked */ } };
const lsDel = id => { try { localStorage.removeItem(LS + id); } catch { /* ignore */ } };

export const api = {
  index: () => req('GET', '/api/index'),
  getCase: id => req('GET', `/api/cases/${id}`),
  putCase: c => req('PUT', `/api/cases/${c.id}`, c),

  async getGame(id) {
    const local = lsGet(id);
    let remote = null;
    try { remote = await req('GET', `/api/games/${id}`); } catch (e) { if (!local) throw e; }
    // The local backup wins only if it is newer AND descends from the server's copy
    // (same window, or built on that version) — never a stale second window's copy.
    const descends = l => l.writer === remote.writer || l.baseUpdatedAt === undefined || l.baseUpdatedAt >= remote.updatedAt;
    if (local && (!remote || (local.updatedAt > remote.updatedAt && descends(local)))) return local;
    return remote;
  },
  async putGame(g, { keepalive = false } = {}) {
    lsSet(g);
    await req('PUT', `/api/games/${g.id}`, g, { keepalive });
  },
  async deleteGame(id) {
    lsDel(id);
    await req('DELETE', `/api/games/${id}`);
  },
};
