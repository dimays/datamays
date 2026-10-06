import { api } from './api.js';
import { uid } from './util.js';
import { newCaseCode } from '../engine/rng.js';
import { ENGINE_VERSION, settingFor } from '../engine/generator.js';
import { SETTINGS } from '../engine/settings.js';

export const caseId = (code, difficulty, mode = 'cold') => mode === 'inquiry' ? `${code}-${difficulty}-inquiry` : `${code}-${difficulty}`;

export function generateInWorker(code, difficulty, mode = 'cold', onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const w = new Worker(new URL('../engine/worker.js', import.meta.url), { type: 'module' });
    w.onmessage = e => {
      const m = e.data;
      if (m.type === 'progress') onProgress(m);
      else { w.terminate(); m.type === 'done' ? resolve(m.caseData) : reject(new Error(m.message)); }
    };
    w.onerror = e => { w.terminate(); reject(new Error(e.message || 'Generator failed')); };
    w.postMessage({ code, difficulty, mode });
  });
}

/**
 * A fresh case number whose setting the player hasn't met lately: one they've
 * never had if any are left, otherwise one of the few they met longest ago.
 * So a player works through every setting before any repeats. The number
 * itself still decides everything, so it can be shared as before.
 */
export function freshCode(index, difficulty, mode = 'cold') {
  const last = new Map();
  // Games played, plus spare cases already waiting (older engines' spares are never dealt).
  for (const c of [...index.games, ...index.cases.filter(c => c.engine === ENGINE_VERSION)]) if (c.setting) last.set(c.setting, Math.max(last.get(c.setting) ?? 0, c.createdAt || 0));
  const ranked = SETTINGS.map(s => ({ id: s.id, at: last.get(s.id) ?? -1, tie: Math.random() })).sort((a, b) => a.at - b.at || a.tie - b.tie);
  const unseen = ranked.filter(s => s.at < 0);
  const fresh = new Set((unseen.length ? unseen : ranked.slice(0, Math.ceil(ranked.length / 4))).map(s => s.id));
  for (let t = 0; t < 2000; t++) {
    const code = newCaseCode();
    if (fresh.has(settingFor(code, difficulty, mode))) return code;
  }
  return newCaseCode();
}

/** Generate, validate and save a case. Players never do this by hand. */
export async function createCase(code, difficulty, mode, onProgress) {
  const data = await generateInWorker(code, difficulty, mode, onProgress);
  if (!data.validation.ok) throw new Error('The generated case failed validation.');
  const rec = { ...data, id: caseId(code, difficulty, mode), createdAt: Date.now() };
  await api.putCase(rec);
  return rec;
}

export function unusedCase(index, difficulty, mode = 'cold') {
  const used = new Set(index.games.map(g => g.caseId));
  return index.cases.filter(c => c.difficulty === difficulty && (c.mode || 'cold') === mode && c.valid && c.engine === ENGINE_VERSION && !used.has(c.id)).sort((a, b) => a.createdAt - b.createdAt)[0] || null;
}

/** A fresh game on a case. `extra` adds fields such as { daily: true }. */
export async function newGameFor(caseRec, extra = {}) {
  const now = Date.now();
  const g = {
    id: uid(), caseId: caseRec.id, title: caseRec.title, code: caseRec.code, difficulty: caseRec.difficulty,
    mode: caseRec.mode || 'cold', setting: caseRec.setting || null, revealed: caseRec.mode === 'inquiry' ? 1 : undefined,
    victim: caseRec.story?.victim ?? caseRec.victim, createdAt: now, updatedAt: now, ...extra,
    total: caseRec.names?.length || 26000,
    marks: '', remaining: (caseRec.names?.length || 26000) - 1, struck: 0, timePlayed: 0, solved: null, accusations: [], hints: 0,
  };
  await api.putGame(g);
  return g;
}

let spareBusy = false;
/** Quietly keep one fresh case of this difficulty and mode ready, so New Case is instant. */
export async function prepareSpare(difficulty, mode = 'cold', onStatus = () => {}) {
  if (spareBusy) return;
  spareBusy = true;
  try {
    const index = await api.index();
    if (unusedCase(index, difficulty, mode)) return onStatus('ready');
    onStatus('busy');
    await createCase(freshCode(index, difficulty, mode), difficulty, mode);
    onStatus('ready');
  } catch (e) {
    console.warn('Spare case not prepared:', e);
    onStatus('idle');
  } finally { spareBusy = false; }
}
