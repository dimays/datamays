import { Rng } from './rng.js';
import { validateNames, LETTERS } from './names.js';
import { SETTINGS } from './settings.js';
import { generatePeople, MAX_FULL_NAME } from './people.js';
import { layoutCase, layoutNovel, planChapters, CHAPTER_PAGES, letters, bookIndex } from './book.js';
import { DEALT_FAMILIES as FAMILIES, DEALT_TYPES, FAMILY, TYPES, TYPE, TIER_LABEL, describeRule } from './rules.js';
import { generateStory, caseTitle } from './story.js';
import { DIFFICULTIES, MIN_CLUES, TIER_QUOTA, BALANCE, SEARCH, STYLES, SECTION_CLUES, TYPE_DROPOUT, namesFor } from './config.js';

export const ENGINE_VERSION = 7;
export { DIFFICULTIES, STYLES, namesFor };

// Before engine 7 every Cold Case opened with one clue each about the chapter,
// page number, column and line. Kept for validating those cases.
const LEGACY_BROAD = ['chapter', 'page', 'column', 'line'];
// Engine 7 opens with "section" clues: stretches of the register anchored to people in it.
const SECTION = DEALT_TYPES.filter(t => t.tier === 'record').map(t => t.id);
const FINE_TIERS = ['name', 'connection', 'reasoning'];
const TYPE_ORDER = Object.fromEntries(TYPES.map((t, k) => [t.id, k]));

/** Seal the solution so a casual peek at the save file doesn't spoil it. */
export const seal = (i, code) => btoa(String((i + 7919) * 31) + '|' + code.split('').reverse().join(''));
export const unseal = (s) => +atob(s).split('|')[0] / 31 - 7919;

export function caseRng(code, difficulty, mode = 'cold') { return new Rng(`${code}|${difficulty}|${mode}|v${ENGINE_VERSION}`); }

export const maxClearFor = type => BALANCE.maxClearShareByType?.[type] ?? BALANCE.maxClearShare;

export const clueRange = difficulty => {
  const [lo, hi] = DIFFICULTIES[difficulty].clues;
  return [Math.max(MIN_CLUES, lo), Math.min(TYPES.length, Math.max(MIN_CLUES, lo, hi))];
};

// The Inquiry comes first: it's the default, and listed first wherever modes are offered.
export const DEFAULT_MODE = 'inquiry';
export const MODES = {
  inquiry: { label: 'The Inquiry', blurb: 'Witnesses come forward one at a time — each only when you have struck every name the evidence so far rules out.' },
  cold: { label: 'Cold Case', blurb: 'The whole file is in front of you: every piece of evidence, from the first page.' },
};

/**
 * Build a complete case from a code. Deterministic: same code + difficulty +
 * mode + engine version (+ config) → identical setting, names, clues and solution.
 */
export function generateCase(code, difficulty = 'classic', mode = 'cold', onProgress = () => {}) {
  if (typeof mode === 'function') { onProgress = mode; mode = 'cold'; }
  const t0 = Date.now();
  const diff = DIFFICULTIES[difficulty];
  if (!diff) throw new Error(`Unknown difficulty ${difficulty}`);
  if (!MODES[mode]) throw new Error(`Unknown mode ${mode}`);
  const root = caseRng(code, difficulty, mode);

  // The setting decides who these people are and how they're listed; the
  // difficulty decides how many of them there are.
  const setting = root.fork('setting').pick(SETTINGS);
  const total = namesFor(difficulty);
  const label = `Entering ${total.toLocaleString('en-US')} ${setting.people} into the ${setting.registerWord}`;
  onProgress({ phase: 'names', label, p: 0 });
  const names = generatePeople(root.fork('people'), setting, total);
  onProgress({ phase: 'names', label, p: 1 });
  const chapterPages = planChapters(root.fork('chapters'), names.length);
  const book = layoutNovel(names, chapterPages, { fullNames: true });

  onProgress({ phase: 'clues', label: mode === 'inquiry' ? 'Lining up the witnesses' : 'Gathering the evidence', p: 0 });
  const rng = root.fork('clues');
  const plan = casePlan(root.fork('plan'));
  const build = mode === 'inquiry' ? tryBuildInquiry : tryBuildCase;
  let solved = null, attempts = 0;
  while (!solved && attempts < SEARCH.attempts) {
    attempts++;
    // If this case's mix of clue types keeps failing, let it draw on all of them.
    solved = build(rng, book, difficulty, plan, attempts > SEARCH.attempts / 2);
    onProgress({ phase: 'clues', label: mode === 'inquiry' ? 'Lining up the witnesses' : 'Gathering the evidence', p: Math.min(0.95, attempts / 12) });
  }
  if (!solved) throw new Error(`Could not construct a balanced case in ${SEARCH.attempts} attempts — loosen BALANCE or raise SEARCH in config.js`);

  const { killer, victim, rules } = solved;
  const story = generateStory(root.fork('story'), book.entries[victim], setting);
  const ctx = { entries: book.entries, book, victim: book.entries[victim], registerWord: setting.registerWord };
  const finalRules = rules.map(r => ({ ...r, ...describeRule(r, ctx) }));

  onProgress({ phase: 'verify', label: 'Checking every alibi', p: 0.5 });
  const caseData = {
    engine: ENGINE_VERSION,
    code,
    difficulty,
    mode,
    setting: setting.id,
    style: plan.style,
    title: caseTitle(story),
    story,
    layout: 'novel',
    fullNames: true,
    names,
    chapterPages,
    victim,
    rules: finalRules,
    solution: seal(killer, code),
    stats: { pageCount: book.pageCount, attempts, iterations: solved.iterations, ms: 0, sectionSurvivors: solved.sectionSurvivors },
  };
  const v = validateCase(caseData);
  caseData.validation = { ok: v.ok, checks: v.checks };
  caseData.metrics = v.metrics;
  caseData.stats.ms = Date.now() - t0;
  if (!caseData.validation.ok) throw new Error('Case failed validation: ' + caseData.validation.checks.filter(c => !c.ok).map(c => c.label).join('; '));
  onProgress({ phase: 'done', label: 'The case is ready', p: 1 });
  return caseData;
}

// ── clue verdict bitmaps ──────────────────────────────────────────────────
// Each clue instance's verdict for every name, computed once per book (clues
// that mention the victim are recomputed per attempt).
// Families flagged `usesVictim` depend on who the victim is, so they're rebuilt per attempt.
// Families flagged `sampled` have too many forms to enumerate: each attempt draws
// a fresh sample that is true of its killer.
const VICTIM_FAMILIES = new Set(FAMILIES.filter(f => f.usesVictim && !f.sampled).map(f => f.id));
const bitmapCache = new WeakMap();

function bitmapsFor(f, list, book, ctx) {
  return list.map(params => {
    let bits;
    if (f.bitsFor) bits = f.bitsFor(params, ctx);
    else {
      bits = new Uint8Array(book.entries.length);
      // A clue about one part of the name gives the same verdict for every entry
      // with that first name (or surname), and names repeat a great deal: ask
      // once per distinct name, then copy the verdicts across.
      const part = f.tier === 'name' && !f.whole && params.part ? bookIndex(book).part[params.part] : null;
      if (part) {
        const verdict = part.reps.map(i => f.test(book.entries[i], params, ctx) ? 1 : 0);
        for (let i = 0; i < bits.length; i++) bits[i] = verdict[part.id[i]];
      } else for (const e of book.entries) if (f.test(e, params, ctx)) bits[e.i] = 1;
    }
    let keep = 0;
    for (let i = 0; i < bits.length; i++) keep += bits[i];
    return { family: f.id, tier: f.tier, type: f.type, params, bits, keep };
  });
}

function buildBitmaps(book, victimIdx, killer, rng) {
  const ctx = { entries: book.entries, book, victim: book.entries[victimIdx], victimIdx };
  if (!bitmapCache.has(book)) {
    bitmapCache.set(book, FAMILIES.filter(f => !f.sampled && !VICTIM_FAMILIES.has(f.id)).flatMap(f => bitmapsFor(f, f.instances(ctx), book, ctx)));
  }
  const victimClues = FAMILIES.filter(f => VICTIM_FAMILIES.has(f.id)).flatMap(f => bitmapsFor(f, f.instances(ctx), book, ctx));
  const sampled = FAMILIES.filter(f => f.sampled).flatMap(f => {
    const seen = new Set();
    const list = f.sample(rng, ctx, killer, SEARCH.sample).filter(p => { const k = JSON.stringify(p); return !seen.has(k) && seen.add(k); });
    return bitmapsFor(f, list, book, ctx);
  });
  return [...bitmapCache.get(book), ...victimClues, ...sampled];
}

/**
 * A case's style (which tiers its fine clues lean on) and the fine clue types
 * it sets aside, so no two cases draw on quite the same mix.
 */
function casePlan(rng) {
  const style = rng.pick(Object.keys(STYLES));
  const dropped = new Set();
  for (const tier of FINE_TIERS) {
    const types = DEALT_TYPES.filter(t => t.tier === tier).map(t => t.id);
    // Keep enough of each tier to meet the style's quota, with room to spare.
    const keep = Math.min(types.length, STYLES[style].quota[tier][1] + 2);
    let left = types.length;
    for (const t of rng.shuffle(types)) if (left > keep && rng.chance(TYPE_DROPOUT)) { dropped.add(t); left--; }
  }
  return { style, dropped };
}

/** Usable clues for this killer and victim: true of the killer, clearing a sensible share. */
function cluePool(rng, book, killer, victim, plan, relaxed) {
  const N = book.entries.length, others = N - 2, out = [];
  for (const c of buildBitmaps(book, victim, killer, rng)) {
    if (!c.bits[killer] || (!relaxed && plan.dropped.has(c.type))) continue;
    const cleared = (N - c.keep) - (c.bits[victim] ? 0 : 1);
    c.clear = cleared / others;
    if (c.clear >= BALANCE.minClearShare && c.clear <= maxClearFor(c.type)) out.push(c);
  }
  return out;
}

const pickPair = (rng, book) => {
  const N = book.entries.length, killer = rng.int(N);
  let victim;
  do { victim = rng.int(N); } while (victim === killer || book.entries[victim].ci === book.entries[killer].ci);
  return [killer, victim];
};

// ── the search ────────────────────────────────────────────────────────────
//
// 1. Pick a killer and a victim.
// 2. Keep only clue instances that are true of the killer and clear between
//    minClearShare and maxClearShare of suspects.
// 3. Choose one broad clue per broad type so the survivors land in the
//    difficulty band. These stay fixed.
// 4. Fill the remaining slots (one per type, tier quotas respected) at random,
//    then local-search: repeatedly swap one fine slot's clue for another of the
//    same type, or for a clue of an unused type in the same tier, keeping moves
//    that reduce the cost:
//       4 × extra survivors  +  2 × missing solo clears  +  overlap excess
//    Only names cleared by ≤ 2 clues can change those numbers with one swap,
//    so each move is scored on that small "active" set, not all 26,000.
// 5. When the cost is zero, order the fine clues greedily (biggest bite first)
//    and check every clue's marginal share in that order.
export const searchLog = {};
const why = r => { searchLog[r] = (searchLog[r] || 0) + 1; return null; };

function tryBuildCase(rng, book, difficulty, plan, relaxed) {
  const diff = DIFFICULTIES[difficulty];
  const N = book.entries.length;
  const [killer, victim] = pickPair(rng, book);
  const others = N - 2;

  // ── 2. the pool of usable clues, by type
  const pool = {};
  for (const c of cluePool(rng, book, killer, victim, plan, relaxed)) (pool[c.type] ||= []).push(c);

  // ── 3. section clues, aimed so the survivors land in the difficulty band
  const kSec = rng.range(SECTION_CLUES[0], SECTION_CLUES[1]);
  const secTypes = SECTION.filter(t => pool[t]?.length);
  if (secTypes.length < kSec) return why('too few section clues');
  let broad = null, broadCount = 0;
  const bandMid = Math.sqrt(diff.band[0] * diff.band[1]);
  for (let t = 0; t < 12 && !broad; t++) {
    let alive = [];
    for (let i = 0; i < N; i++) if (i !== victim) alive.push(i);
    const pick = [];
    for (const [step, ty] of rng.shuffle([...secTypes]).slice(0, kSec).entries()) {
      // Each step aims for an even share of the remaining cut, on a log scale.
      const aim = alive.length * Math.pow(bandMid / alive.length, 1 / (kSec - step));
      const scored = [];
      for (const c of pool[ty]) {
        let n = 0;
        for (const i of alive) if (c.bits[i]) n++;
        if ((alive.length - n) / alive.length < BALANCE.minMarginalShare) continue;
        scored.push({ c, n, d: Math.abs(Math.log(n / aim)) });
      }
      if (!scored.length) break;
      scored.sort((x, y) => x.d - y.d);
      // The last section clue must land the survivors in the band; earlier ones just aim.
      const inBand = step === kSec - 1 ? scored.filter(x => x.n >= diff.band[0] && x.n <= diff.band[1]) : [];
      const c = rng.pick(inBand.length ? inBand : scored.slice(0, 3)).c;
      pick.push(c);
      alive = alive.filter(i => c.bits[i]);
    }
    if (pick.length === kSec && alive.length >= diff.band[0] && alive.length <= diff.band[1]) { broad = pick; broadCount = alive.length; }
  }
  if (!broad) return why('section band missed');

  // ── 4a. initial fine slots, within the case style's tier quotas
  const [cLo, cHi] = clueRange(difficulty);
  const total = rng.range(cLo, cHi);
  const fineN = total - broad.length;
  const typesIn = tier => rng.shuffle(DEALT_TYPES.filter(t => t.tier === tier && pool[t.id]?.length).map(t => t.id));
  const avail = Object.fromEntries(FINE_TIERS.map(t => [t, typesIn(t)]));
  const quota = STYLES[plan.style].quota;
  const splits = [];
  for (let a = quota.name[0]; a <= quota.name[1]; a++) for (let b = quota.connection[0]; b <= quota.connection[1]; b++) {
    const c = fineN - a - b;
    if (c >= quota.reasoning[0] && c <= quota.reasoning[1] && a <= avail.name.length && b <= avail.connection.length && c <= avail.reasoning.length) splits.push([a, b, c]);
  }
  if (!splits.length) return why('tier quota impossible');
  const split = rng.pick(splits);
  const slots = [...broad, ...FINE_TIERS.flatMap((tier, k) => avail[tier].slice(0, split[k]).map(t => rng.pick(pool[t])))];
  const fixed = broad.length;
  const R = slots.length;

  // ── 4b. state: how many slots clear each name, and XOR of their indices
  const VICTIM_FAIL = 200;
  const fail = new Uint8Array(N), xor = new Uint8Array(N);
  slots.forEach((c, j) => { for (let i = 0; i < N; i++) if (!c.bits[i]) { fail[i]++; xor[i] ^= j + 1; } });
  fail[victim] = VICTIM_FAIL;
  // Shallow overlap limits are optimised during the search; deep ones would
  // make every name "active", so they are checked once the search converges.
  const depth = BALANCE.overlap.clues;
  const overlapInSearch = depth <= 2;
  const activeCap = 2;
  const maxOverlap = Math.floor(BALANCE.overlap.maxShare * others);
  let active = [], overlap = 0;
  const refresh = () => {
    active = []; overlap = 0;
    for (let i = 0; i < N; i++) {
      if (i === killer || i === victim) continue;
      if (overlapInSearch && fail[i] >= depth) overlap++;
      if (fail[i] <= activeCap) active.push(i);
    }
  };
  refresh();

  const score = (j, c) => {
    const solo = new Int32Array(R);
    let extra = 0, ov = overlap;
    const oldB = c ? slots[j].bits : null, newB = c ? c.bits : null, tag = j + 1;
    for (const i of active) {
      let f = fail[i], x = xor[i];
      if (c) {
        const of = !oldB[i], nf = !newB[i];
        if (of !== nf) {
          f += nf ? 1 : -1; x ^= tag;
          if (overlapInSearch) { if (fail[i] >= depth && f < depth) ov--; else if (fail[i] < depth && f >= depth) ov++; }
        }
      }
      if (f === 0) extra++; else if (f === 1) solo[x - 1]++;
    }
    let weak = 0;
    for (let k = 0; k < R; k++) if (solo[k] < BALANCE.minSoloClears) weak += BALANCE.minSoloClears - solo[k];
    const cost = extra * 4 + weak * 2 + (overlapInSearch ? Math.max(0, ov - maxOverlap) / 25 : 0);
    return { cost, extra, solo };
  };

  const commit = (j, c) => {
    const oldB = slots[j].bits, newB = c.bits, tag = j + 1;
    for (let i = 0; i < N; i++) {
      if (i === victim) continue;
      const of = !oldB[i], nf = !newB[i];
      if (of !== nf) { fail[i] += nf ? 1 : -1; xor[i] ^= tag; }
    }
    slots[j] = c;
    refresh();
  };

  // Moves: slot j takes clue c — same type, or an unused type in the same tier.
  const movesFor = (j, keep) => {
    const out = [];
    const used = new Set(slots.map(s => s.type));
    const tier = slots[j].tier;
    for (const c of pool[slots[j].type]) if (c !== slots[j] && keep(c)) out.push([j, c]);
    for (const t of DEALT_TYPES) if (t.tier === tier && !used.has(t.id) && pool[t.id]) for (const c of pool[t.id]) if (keep(c)) out.push([j, c]);
    return out;
  };

  let cur = score(0, null);
  let it = 0;
  for (; it < SEARCH.iterations && cur.cost > 0; it++) {
    let cands = [];
    const extras = cur.extra ? active.filter(i => fail[i] === 0) : [];
    const weakSlots = [];
    for (let k = 0; k < R; k++) if (cur.solo[k] < BALANCE.minSoloClears) weakSlots.push(k);
    if (extras.length && (!weakSlots.length || rng.chance(0.6))) {
      // Someone besides the killer survives: find a clue that clears them.
      const s = rng.pick(extras);
      for (let j = fixed; j < R; j++) cands.push(...movesFor(j, c => !c.bits[s]));
    } else if (weakSlots.length) {
      // Clue r lacks names only it clears: loosen another clue so that a name
      // currently cleared by exactly r and one other is cleared by r alone.
      const r = rng.pick(weakSlots);
      const near = active.filter(i => fail[i] === 2 && !slots[r].bits[i] && ((xor[i] ^ (r + 1)) - 1) >= fixed);
      for (const i of rng.shuffle(near).slice(0, 4)) {
        const q = (xor[i] ^ (r + 1)) - 1;
        cands.push(...movesFor(q, c => !!c.bits[i]));
      }
    }
    if (!cands.length) {
      const j = fixed + rng.int(R - fixed);
      cands = movesFor(j, () => true);
    }
    rng.shuffle(cands);
    let best = null;
    for (const [j, c] of cands.slice(0, SEARCH.candidates)) {
      const sc = score(j, c);
      if (!best || sc.cost < best.sc.cost) best = { j, c, sc };
    }
    if (best && (best.sc.cost <= cur.cost || rng.chance(SEARCH.uphill))) {
      commit(best.j, best.c);
      cur = score(0, null);
    }
  }
  if (cur.cost > 0) { searchLog.lastCost = cur; return why('search did not converge'); }
  if (pairOverlap(slots.map(c => c.bits), killer, victim, N).max > BALANCE.maxPairOverlap) return why('two clues too alike');
  if (!overlapInSearch) {
    let deep = 0;
    for (let i = 0; i < N; i++) if (i !== killer && i !== victim && fail[i] >= depth) deep++;
    if (deep > maxOverlap) return why('overlap too high');
  }

  // ── 5. Casebook order: section clues first, then the biggest bite each time.
  const alive = new Uint8Array(N).fill(1);
  alive[killer] = 0; alive[victim] = 0;
  let standing = others;
  const order = [];
  const take = c => {
    let cleared = 0;
    for (let i = 0; i < N; i++) if (alive[i] && !c.bits[i]) { alive[i] = 0; cleared++; }
    if (cleared / standing < BALANCE.minMarginalShare) return false;
    standing -= cleared;
    order.push(c);
    return true;
  };
  for (const c of slots.slice(0, fixed)) if (!take(c)) return why('section marginal too small');
  const rest = slots.slice(fixed);
  while (rest.length) {
    let bestK = 0, bestN = -1;
    rest.forEach((c, k) => {
      let n = 0;
      for (let i = 0; i < N; i++) if (alive[i] && !c.bits[i]) n++;
      if (n > bestN || (n === bestN && TYPE_ORDER[c.type] < TYPE_ORDER[rest[bestK].type])) { bestN = n; bestK = k; }
    });
    if (!take(rest.splice(bestK, 1)[0])) return why('fine marginal too small');
  }

  return {
    killer, victim, sectionSurvivors: broadCount, iterations: it,
    rules: order.map(c => ({ family: c.family, tier: c.tier, type: c.type, params: c.params })),
  };
}


// ── The Inquiry: clues revealed one at a time ─────────────────────────────
//
// Uniqueness only needs the final clue to clear whoever is left, so the
// sequence is built forward, one witness at a time:
//   • each step aims to clear an even share of what's left (on a log scale),
//     so the case thins out steadily rather than all at once or all at the end;
//   • section clues (stretches of the register, struck in runs) come first,
//     until the field is down to the difficulty's working size; only then do
//     name-by-name clues arrive, alternating tiers so no two in a row feel
//     alike, and leaning toward the case's style;
//   • the second-to-last witness must leave a group the last one can clear
//     entirely, so the case always ends on a clean final line-up.
const BULK_TYPES = new Set(SECTION);

function tryBuildInquiry(rng, book, difficulty, plan, relaxed) {
  const N = book.entries.length;
  const [killer, victim] = pickPair(rng, book);
  const cands = cluePool(rng, book, killer, victim, plan, relaxed);
  // The case's style tilts which tier each witness comes from.
  const q = STYLES[plan.style].quota, mid = t => (q[t][0] + q[t][1]) / 2;
  const meanMid = FINE_TIERS.reduce((s, t) => s + mid(t), 0) / FINE_TIERS.length;
  const lean = Object.fromEntries(FINE_TIERS.map(t => [t, Math.sqrt(mid(t) / meanMid)]));
  const [lo, hi] = clueRange(difficulty);
  const n = rng.range(lo, hi);
  let alive = [];
  for (let i = 0; i < N; i++) if (i !== killer && i !== victim) alive.push(i);
  const seq = [], used = new Set();
  const clearsAll = (c, ids) => ids.every(i => !c.bits[i]);
  for (let step = 0; step < n; step++) {
    const left = n - step, standing = alive.length;
    const target = left === 1 ? 1 : 1 - Math.pow(1 / standing, 1 / left);
    // Phase 1: bulk clues (struck by chapter, page, column or line with the
    // Strike tools) until the field is down to this difficulty's working size.
    // Phase 2: name-by-name clues, alternating name and connection clues, with
    // an occasional bulk clue as a breather.
    const band = DIFFICULTIES[difficulty].band[1];
    const bulkPhase = standing > band;
    const prev = seq[seq.length - 1];
    // Bulk clues still unused; aim each one so the last of them gets under the band.
    const bulkLeft = [...BULK_TYPES].filter(t => !used.has(t) && cands.some(c => c.type === t)).length;
    if (bulkPhase && !bulkLeft) return why('bulk clues ran out before the field was small enough');
    const bulkTarget = bulkPhase ? 1 - Math.pow(band / standing, 1 / bulkLeft) : 0;
    const scored = [];
    for (const c of cands) {
      if (used.has(c.type)) continue;
      let k = 0;
      for (const i of alive) if (!c.bits[i]) k++;
      if (!k) continue;
      if (left === 1 ? k !== standing : k === standing || k / standing < BALANCE.minMarginalShare) continue;
      const bulk = BULK_TYPES.has(c.type);
      const pace = bulkPhase ? (bulk ? 1 : 0.02)
        : bulk ? 0.35
        : (prev && !BULK_TYPES.has(prev.type) && prev.tier === c.tier ? 0.55 : 1) * (lean[c.tier] || 1);
      const aim = bulkPhase && bulk ? Math.max(target, bulkTarget) : target;
      scored.push({ c, k, w: pace / (0.04 + Math.abs(k / standing - aim)) });
    }
    if (!scored.length) return null;
    scored.sort((a, b) => b.w - a.w);
    let pick = null;
    for (const s of rng.shuffle(scored.slice(0, 6)).sort((a, b) => b.w - a.w + (rng.next() - 0.5) * a.w * 0.6)) {
      if (left === 2) {
        // Leave a line-up the final witness can clear in one go.
        const rest = alive.filter(i => s.c.bits[i]);
        if (!cands.some(d => d.type !== s.c.type && !used.has(d.type) && clearsAll(d, rest))) continue;
      }
      pick = s; break;
    }
    if (!pick) return null;
    seq.push(pick.c); used.add(pick.c.type);
    alive = alive.filter(i => pick.c.bits[i]);
  }
  if (alive.length) return null;
  if (pairOverlap(seq.map(c => c.bits), killer, victim, N).max > BALANCE.maxPairOverlap) return why('two clues too alike');
  return {
    killer, victim, sectionSurvivors: null, iterations: n,
    rules: seq.map(c => ({ family: c.family, tier: c.tier, type: c.type, params: c.params })),
  };
}

/** Largest overlap between two clues' cleared sets, as a share of the smaller set. */
function pairOverlap(bitsList, killer, victim, N) {
  const cleared = bitsList.map(b => { const out = []; for (let i = 0; i < N; i++) if (!b[i] && i !== killer && i !== victim) out.push(i); return out; });
  let max = 0, pair = null;
  for (let a = 0; a < cleared.length; a++) for (let b = a + 1; b < cleared.length; b++) {
    const [small, bigBits] = cleared[a].length <= cleared[b].length ? [cleared[a], bitsList[b]] : [cleared[b], bitsList[a]];
    let both = 0;
    for (const i of small) if (!bigBits[i]) both++;
    const share = small.length ? both / small.length : 0;
    if (share > max) { max = share; pair = [a, b]; }
  }
  return { max, pair };
}

// ── validation ────────────────────────────────────────────────────────────

function validateNameList(names, fullNames, expected = 26000) {
  const problems = [];
  const seen = new Set();
  if (names.length !== expected) problems.push(`Expected ${expected.toLocaleString('en-US')} names, found ${names.length}`);
  const plain = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  for (const n of names) {
    if (fullNames) {
      // "First Surname": real names, repeats allowed, short enough for a line.
      const parts = n.split(' ');
      if (parts.length !== 2 || parts.some(p => !/^[A-Z][A-Za-z]*(['-][A-Za-z]+)?$/.test(plain(p)) || letters(p).length < 2) || n.length > MAX_FULL_NAME) problems.push(`Malformed name "${n}"`);
    } else {
      if (!/^[A-Z][a-z]{2,10}$/.test(n)) problems.push(`Malformed name "${n}"`);
      if (seen.has(n.toLowerCase())) problems.push(`Duplicate "${n}"`);
    }
    seen.add(n.toLowerCase());
  }
  return { ok: !problems.length, problems: problems.slice(0, 20), unique: seen.size };
}

/** Balance metrics for a set of clues, computed straight from the clue tests. */
export function caseMetrics(book, rules, victimIdx, killerIdx) {
  const N = book.entries.length;
  const ctx = { entries: book.entries, book, victim: book.entries[victimIdx] };
  const R = rules.length;
  const bits = rules.map(r => {
    const f = FAMILY[r.family];
    const b = new Uint8Array(N);
    for (const e of book.entries) b[e.i] = f.test(e, r.params, ctx) ? 1 : 0;
    return b;
  });
  const fail = new Uint8Array(N), xor = new Uint8Array(N);
  bits.forEach((b, k) => { for (let i = 0; i < N; i++) if (!b[i]) { fail[i]++; xor[i] ^= k + 1; } });
  const suspects = [];
  for (let i = 0; i < N; i++) if (i !== victimIdx) suspects.push(i);
  const others = suspects.filter(i => i !== killerIdx);
  const survivors = suspects.filter(i => fail[i] === 0);
  const clears = bits.map(b => others.reduce((n, i) => n + (b[i] ? 0 : 1), 0));
  const solo = new Array(R).fill(0);
  const hist = new Array(R + 1).fill(0);
  for (const i of others) { hist[fail[i]]++; if (fail[i] === 1) solo[xor[i] - 1]++; }
  const alive = new Uint8Array(N);
  for (const i of others) alive[i] = 1;
  let standing = others.length;
  const marginal = bits.map(b => {
    let n = 0;
    for (let i = 0; i < N; i++) if (alive[i] && !b[i]) { alive[i] = 0; n++; }
    const share = standing ? n / standing : 0;
    standing -= n;
    return { cleared: n, share };
  });
  const depth = BALANCE.overlap.clues;
  const deep = others.reduce((n, i) => n + (fail[i] >= depth ? 1 : 0), 0);
  const po = pairOverlap(bits, killerIdx, victimIdx, N);
  return {
    survivors,
    pairOverlap: po.max, pairOverlapClues: po.pair && po.pair.map(k => k + 1),
    perClue: rules.map((r, k) => ({ clears: clears[k], clearShare: clears[k] / others.length, solo: solo[k], marginal: marginal[k].cleared, marginalShare: marginal[k].share })),
    overlapShare: deep / others.length,
    overlapDepth: depth,
    meanClears: others.reduce((s, i) => s + fail[i], 0) / others.length,
    histogram: hist,
  };
}

const pct = x => `${(x * 100).toFixed(1)}%`;

/** Independent re-check of a stored case: names, layout, uniqueness, balance. */
export function validateCase(caseData) {
  const checks = [];
  const add = (label, ok, detail = '') => checks.push({ label, ok: !!ok, detail });
  const inquiry = caseData.mode === 'inquiry';
  const engine = caseData.engine || 0, legacy = engine < 7;
  const expected = namesFor(caseData.difficulty, engine), many = expected.toLocaleString('en-US');
  if (caseData.layout === 'novel') {
    const nv = validateNameList(caseData.names, caseData.fullNames, expected);
    add(caseData.fullNames ? `${many} well-formed full names` : `${many} names, all unique and well formed`, nv.ok, nv.ok ? `${nv.unique.toLocaleString('en-US')} distinct ${caseData.fullNames ? 'full names (repeats are realistic)' : 'names'}` : nv.problems.join('; '));
  } else {
    const nv = validateNames(caseData.chapters);
    add('26,000 names, all unique, correctly filed and sorted', nv.ok, nv.ok ? `${nv.unique.toLocaleString('en-US')} unique names` : nv.problems.join('; '));
  }

  const book = layoutCase(caseData);
  const pagesOk = book.pages.every((p, i) => p.page === i + 1) && book.entries.length === expected;
  add('Every name has exactly one page, column and line', pagesOk, `${book.pageCount} pages · ${book.cols} columns`);
  if (book.style === 'novel') {
    const lens = book.chapters.map(c => c.lastPage - c.firstPage + 1);
    add(`Every chapter is ${CHAPTER_PAGES[0]}–${CHAPTER_PAGES[1]} pages long`, lens.every(n => n >= CHAPTER_PAGES[0] && n <= CHAPTER_PAGES[1]), `${book.chapters.length} chapters of ${Math.min(...lens)}–${Math.max(...lens)} pages`);
  }

  const rules = caseData.rules;
  const killer = unseal(caseData.solution);
  const m = caseMetrics(book, rules, caseData.victim, killer);
  add('Exactly one name satisfies every clue', m.survivors.length === 1, `${m.survivors.length} survivor(s)`);
  add('That name is the sealed solution', m.survivors.length === 1 && m.survivors[0] === killer);
  add('The victim is not the solution', caseData.victim !== killer);

  const [lo, hi] = clueRange(caseData.difficulty);
  add(`Between ${lo} and ${hi} clues`, rules.length >= lo && rules.length <= hi, `${rules.length} clues`);
  const types = rules.map(r => FAMILY[r.family].type);
  const dupes = types.filter((t, k) => t && types.indexOf(t) !== k);
  add('No two clues of the same type', !dupes.length, dupes.length ? `repeated: ${[...new Set(dupes)].map(t => TYPE[t]?.label || t).join(', ')}` : `${new Set(types).size} distinct types`);
  const tierCount = tier => types.filter(t => TYPE[t]?.tier === tier).length;
  if (legacy && !inquiry) {
    const missingBroad = LEGACY_BROAD.filter(t => !types.includes(t));
    add('Chapter, page number, column and line are all covered', !missingBroad.length, missingBroad.map(t => TYPE[t].label).join(', '));
    const quotaOk = Object.entries(TIER_QUOTA).every(([tier, [a, b]]) => tierCount(tier) >= a && tierCount(tier) <= b);
    add('Name and connection clues within their quotas', quotaOk, `${tierCount('name')} about the name · ${tierCount('connection')} about connections`);
  }
  if (!legacy) {
    const retired = rules.filter(r => FAMILY[r.family].retired || FAMILY[r.family].legacy);
    add('No simple page, column, line or chapter gates', !retired.length, retired.length ? `retired: ${retired.map(r => r.typeLabel).join(', ')}` : '');
    if (!inquiry) {
      const sec = types.filter(t => TYPE[t]?.tier === 'record').length;
      const secFirst = types.slice(0, sec).every(t => TYPE[t]?.tier === 'record');
      add(`${SECTION_CLUES[0]}–${SECTION_CLUES[1]} clues about sections of the register, listed first`, sec >= SECTION_CLUES[0] && sec <= SECTION_CLUES[1] && secFirst, `${sec} section clues`);
      const st = STYLES[caseData.style];
      const quotaOk = !!st && FINE_TIERS.every(tier => tierCount(tier) >= st.quota[tier][0] && tierCount(tier) <= st.quota[tier][1]);
      add(`Clue mix fits the case’s style${st ? ` (${st.label})` : ''}`, quotaOk, `${tierCount('name')} about the name · ${tierCount('connection')} about connections · ${tierCount('reasoning')} reasoning`);
    }
  }

  const tooBig = m.perClue.map((c, k) => c.clearShare > maxClearFor(FAMILY[rules[k].family]?.type) + 1e-9 ? k + 1 : 0).filter(Boolean);
  const tooSmall = m.perClue.map((c, k) => c.clearShare < BALANCE.minClearShare - 1e-9 ? k + 1 : 0).filter(Boolean);
  const shares = m.perClue.map(c => c.clearShare);
  const typeCaps = Object.entries(BALANCE.maxClearShareByType || {}).map(([t, v]) => `${TYPE[t]?.label.replace(/^The /, '').toLowerCase() || t} clues ${pct(v)}`).join(', ');
  add(`No clue clears more than ${pct(BALANCE.maxClearShare)}${typeCaps ? ` (${typeCaps})` : ''} or less than ${pct(BALANCE.minClearShare)} of suspects`, !tooBig.length && !tooSmall.length,
    tooBig.length || tooSmall.length ? `out of range: clue ${[...tooBig, ...tooSmall].join(', ')}` : `range ${pct(Math.min(...shares))} – ${pct(Math.max(...shares))}`);
  if (!inquiry) {
    add(`At most ${pct(BALANCE.overlap.maxShare)} of suspects cleared by ${BALANCE.overlap.clues}+ clues`, m.overlapShare <= BALANCE.overlap.maxShare + 1e-9,
      `${pct(m.overlapShare)} · on average each suspect is cleared by ${m.meanClears.toFixed(1)} clues`);
    const minSolo = Math.min(...m.perClue.map(c => c.solo));
    add(`Every clue is the only clue clearing at least ${BALANCE.minSoloClears} name${BALANCE.minSoloClears > 1 ? 's' : ''} (so every clue is necessary)`, minSolo >= BALANCE.minSoloClears, `fewest: ${minSolo}`);
  }
  const minMarg = Math.min(...m.perClue.map(c => c.marginalShare));
  const minCleared = Math.min(...m.perClue.map(c => c.marginal));
  add(inquiry ? `Every witness, in turn, clears at least ${pct(BALANCE.minMarginalShare)} of those still standing` : `Read in order, every clue clears at least ${pct(BALANCE.minMarginalShare)} of those still standing`,
    minMarg >= BALANCE.minMarginalShare - 1e-9 && minCleared >= 1, `weakest: ${pct(minMarg)}`);
  add(`No two clues clear nearly the same names (at most ${pct(BALANCE.maxPairOverlap)} overlap)`, m.pairOverlap <= BALANCE.maxPairOverlap + 1e-9,
    `closest pair: clues ${m.pairOverlapClues ? m.pairOverlapClues.join(' & ') : '—'} at ${pct(m.pairOverlap)}`);
  add('Clue statements are present and distinct', new Set(rules.map(r => r.text)).size === rules.length);
  return { ok: checks.every(c => c.ok), checks, metrics: { ...m, survivors: undefined } };
}

export { LETTERS, TIER_LABEL };
