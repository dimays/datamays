// ─────────────────────────────────────────────────────────────────────────
// People: fills a setting's register with 26,000 full names, in the order a
// clerk would have entered them — households (or parties of friends) listed
// together, each person named from their culture's bank with realistic
// popularity, so common names repeat just as they do in real records.
// ─────────────────────────────────────────────────────────────────────────
import { BANKS } from './names/index.js';

export const MAX_FULL_NAME = 20;   // characters, so a name fits a three-column line

// Name banks hold ~100–250 names each, far fewer than a real population, so
// their popularity skew is softened: otherwise one surname would cover 15–30%
// of a town. Lewis still ends up dominated by MacLeods — as it really was.
const SURNAME_SKEW = 0.6, FIRST_SKEW = 0.9;

// Real names that read as jokes or celebrities in English.
const AVOID = new Set(['mike hunt', 'rob banks', 'robin banks', 'hugh jass', 'ben dover', 'seymour butts', 'phil mccracken', 'barry white', 'doris day',
  'joan collins', 'fanny hill', 'fanny adams', 'long dong', 'phuc do', 'phuc bui', 'dung do', 'jack frost', 'paige turner', 'sue yu', 'crystal ball',
  'holly wood', 'rusty nail', 'marsha mellow']);

/** Popularity-weighted picker over a most-common-first list (Zipf by rank). */
function zipfPicker(list, s) {
  const cum = [];
  let t = 0;
  list.forEach((_, r) => { t += 1 / Math.pow(r + 1, s); cum.push(t); });
  return rng => {
    const x = rng.next() * t;
    let lo = 0, hi = cum.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cum[mid] < x) lo = mid + 1; else hi = mid; }
    return list[lo];
  };
}

const pickers = new Map();
function culture(id) {
  if (!pickers.has(id)) {
    const b = BANKS[id];
    if (!b) throw new Error(`Unknown name bank "${id}"`);
    pickers.set(id, {
      female: zipfPicker(b.female, (b.zipf?.first ?? 1) * FIRST_SKEW),
      male: zipfPicker(b.male, (b.zipf?.first ?? 1) * FIRST_SKEW),
      surname: zipfPicker(b.surnames, (b.zipf?.surname ?? 0.9) * SURNAME_SKEW),
    });
  }
  return pickers.get(id);
}

function firstName(rng, c, surname, taken) {
  for (let t = 0; t < 30; t++) {
    const f = (rng.chance(0.5) ? c.female : c.male)(rng);
    // Families don't give two children the same name; fits a three-column line.
    if (f.length + 1 + surname.length <= MAX_FULL_NAME && !taken?.has(f) && f !== surname && !AVOID.has(`${f} ${surname}`.toLowerCase())) return f;
  }
  return null;
}

/** Returns `total` full names ("First Surname") in register order. */
export function generatePeople(rng, setting, total = 26000) {
  const cultureOf = () => rng.weighted(setting.cultures, ([, w]) => w)[0];
  const sizeOf = () => rng.weighted(setting.grouping.sizes, ([, w]) => w)[0];
  const out = [];
  while (out.length < total) {
    const size = Math.min(sizeOf(), total - out.length);
    if (setting.grouping.kind === 'households') {
      // A household: one surname, one culture.
      const c = culture(cultureOf());
      let surname, members = [];
      for (let t = 0; t < 10 && members.length < size; t++) {
        surname = c.surname(rng);
        members = [];
        const taken = new Set();
        for (let m = 0; m < size; m++) { const f = firstName(rng, c, surname, taken); if (f) { taken.add(f); members.push(`${f} ${surname}`); } }
      }
      out.push(...members);
    } else {
      // A party of friends: mixed backgrounds; couples and siblings sometimes share a surname.
      let shared = null;
      for (let m = 0; m < size; m++) {
        const c = culture(cultureOf());
        const surname = shared && rng.chance(setting.grouping.sharedSurname) ? shared : c.surname(rng);
        const f = firstName(rng, c, surname);
        if (!f) continue;
        out.push(`${f} ${surname}`);
        shared = surname;
      }
    }
  }
  return out.slice(0, total);
}
