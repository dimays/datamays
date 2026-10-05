// Rules shared by both stores — the local server (server.js) and the
// in-browser store (store.js) — so a save behaves the same in either.

/** Small headers so the home screen never parses whole books. */
export function caseSummary(c) {
  return { id: c.id, engine: c.engine, mode: c.mode || 'cold', setting: c.setting || null, style: c.style || null, names: c.names?.length || 26000, code: c.code, difficulty: c.difficulty, title: c.title, createdAt: c.createdAt, clues: c.rules?.length, pages: c.stats?.pageCount, valid: c.validation?.ok, victim: c.story?.victim, town: c.story?.town };
}

export function gameSummary(g) {
  const { marks, notes, ...rest } = g;
  return rest;
}

/** Why a game save must be refused, or null if it may be written over `prev`. */
export function saveConflict(prev, obj) {
  if (!prev) return null;
  // Never let a stale tab overwrite newer progress.
  if (obj.updatedAt < prev.updatedAt) return 'Stale save';
  // Another window saved since this one last loaded or saved: don't let it overwrite.
  if (obj.writer && prev.writer && obj.writer !== prev.writer && obj.baseUpdatedAt !== undefined && prev.updatedAt > obj.baseUpdatedAt) return 'Saved elsewhere';
  return null;
}
