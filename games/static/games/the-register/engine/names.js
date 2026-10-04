import { CORPUS } from './corpus.js';

export const TOTAL_NAMES = 26000;
export const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

// Relative share of first names by initial — common letters get long chapters,
// X and Q get short ones, the way a real town register would look.
const LETTER_WEIGHT = {
  A: 70, B: 45, C: 55, D: 50, E: 42, F: 25, G: 30, H: 30, I: 20, J: 50, K: 45, L: 55, M: 66,
  N: 30, O: 18, P: 28, Q: 8, R: 45, S: 60, T: 45, U: 8, V: 18, W: 22, X: 6, Y: 12, Z: 15,
};
const MIN_PER_CHAPTER = 260;

const VOWELS = new Set(['a', 'e', 'i', 'o', 'u', 'y']);
const OK_TRIPLE_CONSONANTS = new Set(['chr', 'str', 'sch', 'tch', 'ght', 'nst', 'ndr', 'ntr', 'mbr', 'rth', 'nch', 'lph', 'phr', 'thr', 'shr', 'spr', 'scr', 'rst', 'rch', 'ldr', 'ndl', 'ckl', 'rtl', 'stl', 'rgr', 'lfr', 'ngst', 'nth', 'mpt', 'rdr', 'rnh', 'xth', 'nds', 'lls', 'ffr', 'ttr', 'ssl', 'mpl', 'ngl', 'ngr', 'rkl', 'wyn', 'lyn', 'ryn', 'dry', 'ndy', 'rly', 'sly', 'tly', 'nny', 'lly']);
const OK_FINAL_PAIRS = new Set(['nd', 'rd', 'rt', 'st', 'th', 'sh', 'ck', 'ld', 'lt', 'nt', 'rn', 'rk', 'rl', 'll', 'ss', 'tt', 'nn', 'rr', 'ff', 'ng', 'ph', 'gh', 'ch', 'rg', 'ms', 'ns', 'ls', 'rs', 'ts', 'ks', 'lf', 'lm', 'rm', 'rc', 'rv', 'nz', 'lk', 'sk', 'ft', 'pt', 'ct', 'xt', 'mb', 'rf', 'rh', 'nk', 'zz', 'ds', 'mn', 'rb']);
const BLOCKED = ['fuck', 'shit', 'cunt', 'nigg', 'nigr', 'fag', 'slut', 'whor', 'dick', 'cock', 'piss', 'rape', 'nazi', 'kike', 'spic', 'chink', 'twat', 'bitch', 'penis', 'vagin', 'anal', 'anus', 'tits', 'porn', 'jizz', 'cum', 'sex', 'dyke', 'homo', 'poop', 'turd', 'puke', 'butt', 'boob', 'crap', 'wank', 'damn', 'hell', 'kill', 'dead', 'die', 'gook', 'coon', 'paki', 'retard', 'pube', 'scrot', 'smeg', 'semen', 'feces', 'fart', 'arse', 'bum', 'shag', 'slag', 'tard', 'wog', 'jap', 'gyp', 'hoe', 'pee', 'vomit', 'urin', 'snot', 'shat', 'clit', 'tit', 'nob', 'jew', 'pedo', 'perv', 'kkk', 'hitler', 'satan', 'lucif', 'prick', 'dong', 'boner', 'moron', 'harlot', 'gash', 'wop', 'wang', 'dildo', 'skank', 'thot', 'idiot', 'stupid', 'dumb'];

function buildModel() {
  const tables = [new Map(), new Map(), new Map()]; // order 1..3
  for (const raw of CORPUS) {
    const s = '^^^' + raw.toLowerCase() + '$';
    for (let i = 3; i < s.length; i++) {
      for (let k = 1; k <= 3; k++) {
        const ctx = s.slice(i - k, i);
        const t = tables[k - 1];
        if (!t.has(ctx)) t.set(ctx, new Map());
        const m = t.get(ctx);
        m.set(s[i], (m.get(s[i]) || 0) + 1);
      }
    }
  }
  // freeze into arrays for deterministic weighted sampling
  return tables.map(t => {
    const out = new Map();
    for (const [ctx, m] of t) {
      const entries = [...m.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1));
      out.set(ctx, { entries, total: entries.reduce((s, e) => s + e[1], 0) });
    }
    return out;
  });
}

let MODEL = null;

function sampleNext(rng, ctx, looseness) {
  // Usually the longest known context; occasionally back off for variety.
  for (let k = 3; k >= 1; k--) {
    const dist = MODEL[k - 1].get(ctx.slice(-k));
    if (!dist) continue;
    if (k > 1 && dist.total < 2 && k !== 1) continue;
    if (k > 1 && rng.chance(looseness * (k === 3 ? 1 : 0.5))) continue;
    let r = rng.next() * dist.total;
    for (const [ch, w] of dist.entries) { r -= w; if (r <= 0) return ch; }
    return dist.entries[dist.entries.length - 1][0];
  }
  return '$';
}

export function isReadable(n) {
  if (n.length < 3 || n.length > 11) return false;
  if (!/^[a-z]+$/.test(n)) return false;
  if (/(.)\1\1/.test(n)) return false;
  if (/^(.)\1/.test(n)) return false;
  if (/[aeiou]{3}/.test(n) && !/(eau|iou|oui|aia|eia|uia|aio|eio)/.test(n)) return false;
  if (n.includes('q') && !/q(u|a|i|e|o)/.test(n)) return false;
  if (/q[^u]/.test(n.slice(1))) return false;
  if (/[xjqvwhk]$/.test(n) && !/(x|h|k)$/.test(n)) return false;
  if (/[jqvwx][^aeiouy]/.test(n.slice(1)) && !/(wn|wl|wr|ws|wy|xt|xw)/.test(n)) return false;
  let run = 0;
  for (let i = 0; i < n.length; i++) {
    if (VOWELS.has(n[i])) { run = 0; continue; }
    run++;
    if (run >= 4) return false;
    if (run === 3 && !OK_TRIPLE_CONSONANTS.has(n.slice(i - 2, i + 1))) return false;
  }
  if (![...n].some(c => VOWELS.has(c))) return false;
  const last2 = n.slice(-2);
  if (!VOWELS.has(last2[0]) && !VOWELS.has(last2[1]) && !OK_FINAL_PAIRS.has(last2)) return false;
  if (!VOWELS.has(n[0]) && !VOWELS.has(n[1]) && !/^(bl|br|ch|cl|cr|dr|fl|fr|gl|gr|kl|kr|ph|pl|pr|sc|sh|sk|sl|sm|sn|sp|st|sw|th|tr|tw|wh|wr|zh|kh|dw|gw|sv|zw)/.test(n)) return false;
  for (const b of BLOCKED) if (n.includes(b)) return false;
  return true;
}

function chapterSizes(rng) {
  const jittered = LETTERS.map(L => LETTER_WEIGHT[L] * (0.88 + rng.next() * 0.24));
  const sum = jittered.reduce((a, b) => a + b, 0);
  const spare = TOTAL_NAMES - MIN_PER_CHAPTER * LETTERS.length;
  const exact = jittered.map(w => MIN_PER_CHAPTER + spare * w / sum);
  const sizes = exact.map(Math.floor);
  let short = TOTAL_NAMES - sizes.reduce((a, b) => a + b, 0);
  const byRemainder = exact.map((x, i) => [x - Math.floor(x), i]).sort((a, b) => b[0] - a[0] || a[1] - b[1]);
  for (let k = 0; short > 0; k++, short--) sizes[byRemainder[k % 26][1]]++;
  return sizes;
}

const cap = n => n[0].toUpperCase() + n.slice(1);

// Ordinary words the model occasionally coins; they read as typos, not names.
const COMMON_WORDS = new Set('nerd dork dunce dolt tart lard fatt peni fork verse wand dough rebel slob snob brat lout oaf twit nitwit dope sleaze trash scum aller also away band bank barn bear beer bell belt bend bent best bill bird bite blue boat body bone book born boss both bread brick bring burn busy cake call came camp care cart case cast city coat cold come cone cook cool core corn cost dare dark date dead deal dear deny desk dine dish does done door dose down drag draw drop dust each earn east easy else even ever fact fail fair fall fame fare farm fast fate fear feed feel fell felt file fill film find fine fire fish fist flat fold folk food foot fore form fort four free from full fund gain game gate gave gift give glad goes gold gone good gown gray grow hall hand hang hard harm hate have head hear heat held help here hide high hill hint hire hold hole home hope horn host hour huge hung hunt idea inch into iron item join just keep kept kind king knew know lack laid lake land lane last late lead lean left lend less lest life lift like line link list live load loan lock long look lord lose loss lost loud love made mail main make male mall many mare mark mass meal mean meat meet mend menu mere mess mild mile milk mind mine miss mode more most move much must name near neck need nest news next nice none nose note once only onto open over pace pack page paid pain pair pale palm park part pass past path peak pick pile pine pink pipe plan play plot plus poll pond pool poor port pose post pour pull pure push race rail rain rank rare rate read real rely rent rest rice rich ride ring rise risk road rock role roll roof room root rope rose rule rush safe said sale salt same sand save seat seed seek seem seen self sell send sent ship shoe shop shot show shut side sign silk sing sink site size skin slip slow snow soft soil sold sole some song soon sort soul spot star stay step stop such suit sure take tale talk tall tank tape task team tell tend tent term test text than that them then they thin this thus tide tile till time tiny told tone took tool tore torn tour town tree trip true tube tune turn twin type unit upon used user vary vast very view vote wage wait wake walk wall want ward warm wash wave weak wear week well went were west what when wide wife wild will wind wine wing wire wise wish with wood word wore work yard yarn year your zone zero alone among anger angle apple badge baker basin beach began begin being below bench birth black blade blame blank blast blend blind block board bonus boost brain brand brave brick bride brief bring broad brown brush build built bunch cabin cable candy cargo carry catch cause chain chair chalk charm chart chase cheap check chess chest chief child china civil claim class clean clear clerk climb clock close cloth cloud coast count court cover crane crash cream crime cross crowd crown cycle daily dance delay depth diary dinner dozen draft drama dream dress drink drive eager early earth eaten elder empty enemy enjoy enter entry equal error event exact exist extra faith false fancy fault fence fever field fifty fight final first flame flash fleet flesh float floor flour fluid focus force forth forty forum found frame fresh front fruit funny giant given glass globe glory grace grade grain grand grant grass grave great green greet grief gross group guard guess guest guide habit happy harsh heart heavy hello hence honey horse hotel house human humor ideal image index inner input issue joint judge juice knife label labor large later laugh layer learn lease least leave legal lemon level light limit liver local lodge logic loose lover lower loyal lucky lunch magic major maker manor march match maybe mayor medal media mercy merit metal meter might minor model money month moral motor mount mouse mouth movie music naked nerve never night noble noise north novel nurse ocean offer often order other outer owner paint panel paper party paste patch peace pearl penny phase phone photo piano piece pilot pitch place plain plane plant plate point pound power press price pride prime print prior prize proof proud prove queen quick quiet quite radio raise range rapid ratio reach ready realm refer relax reply rider ridge rifle right rigid rival river robin robot rough round route royal rural salad sauce scale scene scope score sense serve seven shade shake shall shape share sharp sheep sheet shelf shell shift shine shirt shock shoot shore short shown sight silly since sixth sixty skill sleep slide small smart smell smile smoke snake solid solve sorry sound south space spare speak speed spend spent spice spine spite split spoke sport staff stage stake stand start state steam steel steep stern stick still stock stone stood store storm story stove strap straw strip stuck study stuff style sugar suite sunny super sweet swing sword table taken taste teach tears thank theme there thick thief thing think third those three threw throw tight timer tired title toast today token tooth topic total touch tough tower toxic trace track trade trail train trait treat trend trial tribe trick tried troop truck truly trust truth twice uncle under union unity until upper upset urban usage usual valid value video visit vital vocal voice waste watch water wheel where which while white whole whose woman women world worry worse worst worth would wound write wrong wrote young youth'.split(' '));
// How often a coined name of each length is kept; skews toward 5–7 letters.
const KEEP_BY_LENGTH = [0, 0, 0, 0, 0.55, 1, 1, 1, 0.75, 0.4];

/** Returns 26 arrays of capitalised names, one per initial, each sorted A→Z. */
export function generateNames(rng, onProgress) {
  if (!MODEL) MODEL = buildModel();
  const sizes = chapterSizes(rng);
  const used = new Set();
  const chapters = [];
  LETTERS.forEach((L, ci) => {
    const want = sizes[ci];
    const l = L.toLowerCase();
    const list = [];
    // A share of genuine names, so familiar faces turn up among the strangers.
    const real = rng.shuffle(CORPUS.filter(n => n[0] === L));
    for (const n of real.slice(0, Math.ceil(real.length * 0.7))) {
      if (list.length >= want) break;
      used.add(n.toLowerCase()); list.push(n);
    }
    let tries = 0, looseness = 0.08;
    while (list.length < want) {
      tries++;
      if (tries % 20000 === 0) looseness = Math.min(0.6, looseness + 0.08);
      if (tries > 2_000_000) throw new Error(`Could not fill chapter ${L}`);
      let s = '^^' + l;
      while (s.length < 14) {
        const ch = sampleNext(rng, s, looseness);
        if (ch === '$') break;
        s += ch;
      }
      const n = s.slice(2);
      if (s.length >= 14 || n.length > 9 || used.has(n) || COMMON_WORDS.has(n) || !isReadable(n)) continue;
      if (!rng.chance(KEEP_BY_LENGTH[n.length])) continue;
      used.add(n); list.push(cap(n));
    }
    list.sort(compareNames);
    chapters.push(list);
    onProgress?.((ci + 1) / 26);
  });
  return chapters;
}

export function compareNames(a, b) {
  const x = a.toLowerCase(), y = b.toLowerCase();
  return x < y ? -1 : x > y ? 1 : 0;
}

export function validateNames(chapters) {
  const problems = [];
  const all = chapters.flat();
  if (chapters.length !== 26) problems.push(`Expected 26 chapters, found ${chapters.length}`);
  if (all.length !== TOTAL_NAMES) problems.push(`Expected ${TOTAL_NAMES} names, found ${all.length}`);
  const seen = new Set();
  chapters.forEach((list, ci) => {
    list.forEach((n, i) => {
      if (!/^[A-Z][a-z]{2,10}$/.test(n)) problems.push(`Malformed name "${n}"`);
      if (n[0] !== LETTERS[ci]) problems.push(`"${n}" filed under ${LETTERS[ci]}`);
      if (i && compareNames(list[i - 1], n) >= 0) problems.push(`Out of order: ${list[i - 1]} / ${n}`);
      const k = n.toLowerCase();
      if (seen.has(k)) problems.push(`Duplicate "${n}"`);
      seen.add(k);
    });
  });
  return { ok: problems.length === 0, problems: problems.slice(0, 20), count: all.length, unique: seen.size };
}
