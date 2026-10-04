// The in-browser store, used when the Register is served as plain files (on a
// website) rather than by its local server. It answers the same requests the
// server does, from IndexedDB, with the same save rules (records.js).

import { caseSummary, gameSummary, saveConflict } from './records.js';

const DB = 'the-register';
const STORES = ['cases', 'caseIndex', 'games', 'deleted'];
let dbp = null;

function open() {
  return dbp ||= new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => { for (const s of STORES) if (!r.result.objectStoreNames.contains(s)) r.result.createObjectStore(s, { keyPath: 'id' }); };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => { dbp = null; reject(r.error || new Error('This browser’s storage is unavailable.')); };
  });
}

const done = tx => new Promise((resolve, reject) => {
  tx.oncomplete = () => resolve();
  tx.onerror = tx.onabort = () => reject(tx.error || new Error('Couldn’t save to this browser’s storage.'));
});
const result = r => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });

function fail(status, message) { const e = new Error(message); e.status = status; return e; }

let askedToPersist = false;
function persist() {
  // Ask once that the browser not evict saves to free space. It may decline; backups still work.
  if (askedToPersist) return;
  askedToPersist = true;
  navigator.storage?.persist?.().catch(() => {});
}

export async function storeRequest(method, url, body) {
  const [kind, id] = url.replace(/^.*\/api\//, '').split('/');
  const db = await open();
  if (kind === 'index' && method === 'GET') {
    const tx = db.transaction(['caseIndex', 'games']);
    const [cases, games] = await Promise.all([result(tx.objectStore('caseIndex').getAll()), result(tx.objectStore('games').getAll())]);
    return { cases, games: games.map(gameSummary) };
  }
  if (kind !== 'cases' && kind !== 'games') throw fail(404, 'Unknown collection');
  if (method === 'GET') {
    const obj = await result(db.transaction(kind).objectStore(kind).get(id));
    if (!obj) throw fail(404, 'Not found');
    return obj;
  }
  if (method === 'PUT') {
    if (!body || body.id !== id) throw fail(400, 'Id mismatch');
    persist();
    if (kind === 'cases') {
      const tx = db.transaction(['cases', 'caseIndex'], 'readwrite');
      tx.objectStore('cases').put(body);
      tx.objectStore('caseIndex').put(caseSummary(body));
      await done(tx);
      return { ok: true };
    }
    // Check and write in one transaction, so two tabs can't interleave.
    const tx = db.transaction(['games', 'deleted'], 'readwrite');
    const games = tx.objectStore('games');
    const [prev, gone] = await Promise.all([result(games.get(id)), result(tx.objectStore('deleted').get(id))]);
    // A tab still open on a game deleted elsewhere must not bring it back.
    const conflict = gone ? 'Deleted' : saveConflict(prev, body);
    if (conflict) { tx.abort(); throw fail(409, conflict); }
    games.put(body);
    await done(tx);
    return { ok: true };
  }
  if (method === 'DELETE') {
    const tx = db.transaction(['games', 'deleted'], 'readwrite');
    tx.objectStore('games').delete(id);
    tx.objectStore('deleted').put({ id });
    await done(tx);
    return { ok: true };
  }
  throw fail(405, 'Method not allowed');
}
