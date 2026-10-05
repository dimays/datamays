import { api } from './api.js';
import { uid } from './util.js';
import { newCaseCode } from '../engine/rng.js';
import { ENGINE_VERSION } from '../engine/generator.js';

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

export async function newGameFor(caseRec) {
  const now = Date.now();
  const g = {
    id: uid(), caseId: caseRec.id, title: caseRec.title, code: caseRec.code, difficulty: caseRec.difficulty,
    mode: caseRec.mode || 'cold', setting: caseRec.setting || null, revealed: caseRec.mode === 'inquiry' ? 1 : undefined,
    victim: caseRec.story?.victim ?? caseRec.victim, createdAt: now, updatedAt: now,
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
    await createCase(newCaseCode(), difficulty, mode);
    onStatus('ready');
  } catch (e) {
    console.warn('Spare case not prepared:', e);
    onStatus('idle');
  } finally { spareBusy = false; }
}
