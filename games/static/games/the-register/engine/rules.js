import { beside, lineMates, isVowel, numberWord, bookIndex, occurrences, familySize } from './book.js';

// ---------------------------------------------------------------------------
// The clue library. Each family yields concrete clue instances (params), a
// test against an entry, and a precise statement. Flavor text is decoration;
// the statement is always the authority.
//
// Tiers run from coarse to fine, which is how a reader naturally works:
//   record     → stretches of the register, anchored to people in it
//                (struck in runs once you've found where they start and end)
//   name       → the name itself         connection → neighbours, family, the victim
//   reasoning  → two conditions joined by if / either / both, or a name
//                crossed with its position on the page
// Cases made before engine 7 also used registry (chapter), ledger (page
// number) and placement (column, line) clues — simple gates struck a whole
// page or column at a time. They are kept so those cases still read, but are
// no longer dealt.
// ---------------------------------------------------------------------------

export const TIERS = ['record', 'registry', 'ledger', 'placement', 'name', 'connection', 'reasoning'];
export const TIER_LABEL = {
  record: 'The Register', registry: 'The Chapter', ledger: 'The Page', placement: 'The Line',
  name: 'The Name', connection: 'The Company It Keeps', reasoning: 'Reasoning',
};

const L = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const STRAIGHT = 'AEFHIKLMNTVWXYZ';
const CURVED = 'BCDGJOPQRSU';
const PRIMES = new Set();
for (let n = 2; n < 2000; n++) { let p = true; for (let d = 2; d * d <= n; d++) if (n % d === 0) { p = false; break; } if (p) PRIMES.add(n); }
const LINE_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23];
const COLUMN_NAME = { 1: 'left-hand', 2: 'middle', 3: 'right-hand' };
const COLUMN_SIDE = { 1: 'left side', 2: 'middle', 3: 'right side' };
const digitSum = n => String(n).split('').reduce((s, d) => s + +d, 0);
const reversed = n => +String(n).split('').reverse().join('');
const listLetters = s => s.split('').join(', ').replace(/, ([^,]*)$/, ' or $1');
const listAnd = arr => arr.length < 2 ? String(arr[0]) : arr.slice(0, -1).join(', ') + ' and ' + arr[arr.length - 1];
const listOr = arr => arr.length < 2 ? String(arr[0]) : arr.slice(0, -1).join(', ') + ' or ' + arr[arr.length - 1];
const NUM = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
const INITIAL = e => (e.lower[0] || '').toUpperCase();

const WORDS = ['ALIBI', 'MOTIVE', 'POISON', 'DAGGER', 'CORPSE', 'WITNESS', 'MIDNIGHT', 'BUTLER', 'CELLAR', 'LANTERN', 'SHADOW', 'REVOLVER', 'LIBRARY', 'ARSENIC', 'BLACKMAIL', 'SCANDAL', 'CANDLE', 'FOGBOUND', 'VERDICT', 'CULPRIT', 'SUSPECT', 'GALLOWS', 'TRAPDOOR', 'INKWELL', 'SEANCE', 'MANOR', 'HEMLOCK', 'CIPHER', 'LOCKET', 'WALTZ', 'JUKEBOX', 'QUAY', 'FERRY', 'ATTIC', 'VAULT', 'CRYPT', 'BELFRY', 'OBITUARY', 'PARLOUR', 'ZEPHYR'];
const uniqLetters = w => [...new Set(w.split(''))].join('');

const LAST_DIGIT_SETS = [[2, 3, 5, 7], [0, 5], [1, 4, 7], [2, 5, 8], [3, 6, 9], [0, 3, 6, 9], [1, 2, 3], [4, 5, 6], [7, 8, 9], [0, 1, 2, 3, 4], [1, 3, 5], [6, 8, 0], [1, 9], [0, 4, 8]];
const COMMON_LETTERS = 'aeilnorstdmhcuy'.split('');
const LETTER_TRIOS = [['b', 'k', 'v'], ['g', 'p', 'w'], ['c', 'f', 'z'], ['d', 'g', 'm'], ['h', 'k', 'w'], ['b', 'c', 'p'], ['f', 'v', 'w'], ['t', 'd', 's'], ['m', 'n', 'r'], ['b', 'd', 'g'], ['c', 'h', 'k'], ['p', 's', 't'], ['l', 'm', 'v']];
const ENDINGS = [['a'], ['e'], ['n'], ['a', 'e'], ['a', 'o'], ['n', 's'], ['l', 'n', 'r'], ['e', 'y'], ['s', 't'], ['d', 'n'], ['a', 'e', 'i'], ['o', 'r', 's'], ['h', 'y'], ['i', 'o', 'u']];
const PAIRS = ['an', 'el', 'ar', 'er', 'in', 'on', 'ra', 'en', 'la', 'li', 'ri', 'or', 'al', 'na', 'ne', 'le', 'is', 'ia', 'ie', 'ro'];

export const FAMILIES = [
  // ── registry ────────────────────────────────────────────────────────────
  {
    id: 'word', tier: 'registry',
    instances: () => WORDS.flatMap(word => [{ word, neg: false }, { word, neg: true }]),
    test: (e, p) => uniqLetters(p.word).includes(INITIAL(e)) !== p.neg,
    text: p => p.neg
      ? `The killer’s name does not begin with any letter of the word ${p.word} (${listLetters(uniqLetters(p.word))}).`
      : `The killer’s name begins with one of the letters of the word ${p.word}: ${listLetters(uniqLetters(p.word))}.`,
    source: 'The Registrar',
    quote: p => p.neg
      ? `“Someone scrawled ${p.word} across the blotter in the records office — and struck through every initial it contains.”`
      : `“Someone scrawled ${p.word} across the blotter in the records office, and circled each of its letters.”`,
  },
  {
    id: 'half', tier: 'registry',
    instances: () => [{ first: true }, { first: false }],
    test: (e, p) => (INITIAL(e) < 'N') === p.first,
    text: p => p.first ? 'The killer’s name begins with a letter from the first half of the alphabet (A to M).' : 'The killer’s name begins with a letter from the second half of the alphabet (N to Z).',
    source: 'The Registrar',
    quote: p => `“The monogram on the cufflink was from the ${p.first ? 'first' : 'second'} half of the alphabet. I polish enough silver to know.”`,
  },
  {
    id: 'straight', tier: 'registry',
    instances: () => [{ straight: true }, { straight: false }],
    test: (e, p) => STRAIGHT.includes(INITIAL(e)) === p.straight,
    text: p => p.straight
      ? `The killer’s initial, written as a capital, is made of straight lines only: ${listLetters(STRAIGHT)}.`
      : `The killer’s initial, written as a capital, has at least one curve in it: ${listLetters(CURVED)}.`,
    source: 'The Signwriter',
    quote: p => p.straight
      ? '“The initials stitched into the dropped handkerchief were all ruler-straight — not a curve on them.”'
      : '“There was a monogram pressed into the sealing wax, and it curled. Whatever the letter was, it had a curve.”',
  },
  {
    id: 'victimInitial', tier: 'registry', usesVictim: true,
    instances: () => [{ inside: true }, { inside: false }],
    test: (e, p, ctx) => (ctx.victim.full || ctx.victim).lower.includes(e.lower[0]) === p.inside,
    text: (p, ctx) => p.inside
      ? `The killer’s initial appears somewhere in the victim’s name, ${ctx.victim.name.toUpperCase()}.`
      : `The killer’s initial appears nowhere in the victim’s name, ${ctx.victim.name.toUpperCase()}.`,
    source: 'The Inspector',
    quote: (p, ctx) => p.inside
      ? `“${ctx.victim.name} traced a letter in the dust before the end. It was one of the letters of their own name.”`
      : `“${ctx.victim.name} kept a list of everyone they trusted — and the killer’s initial was missing from their own name, as if on purpose.”`,
  },
  {
    id: 'window', tier: 'registry',
    instances: () => {
      const out = [];
      for (let a = 0; a < 26; a += 2) for (const w of [6, 8, 10]) if (a + w <= 26) out.push({ from: L[a], to: L[a + w - 1], neg: false }, { from: L[a], to: L[a + w - 1], neg: true });
      return out;
    },
    test: (e, p) => (INITIAL(e) >= p.from && INITIAL(e) <= p.to) !== p.neg,
    text: p => p.neg
      ? `The killer’s name does not begin with any letter from ${p.from} to ${p.to}.`
      : `The killer’s name begins with a letter from ${p.from} to ${p.to} (inclusive).`,
    source: 'The Porter',
    quote: p => p.neg
      ? `“The initial on the luggage tag was smudged — but it was nothing between ${p.from} and ${p.to}, I’d swear to that.”`
      : `“The initial on the luggage tag was smudged, but it was somewhere between ${p.from} and ${p.to}.”`,
  },

  // ── ledger (page number) ────────────────────────────────────────────────
  {
    id: 'pagePrime', tier: 'ledger',
    instances: () => [{ is: true }, { is: false }],
    test: (e, p) => PRIMES.has(e.page) === p.is,
    text: p => p.is ? 'The killer’s page number is a prime number (2, 3, 5, 7, 11, 13 …; 1 is not prime).' : 'The killer’s page number is not a prime number (1 counts as not prime).',
    source: 'The Schoolmaster',
    quote: p => p.is ? '“The page had been dog-eared — a page number nothing divides but one and itself.”' : '“Whatever page it was, it could be shared out evenly some other way. Not a prime. I’d stake my chalk on it.”',
  },
  {
    id: 'pageParity', tier: 'ledger',
    instances: () => [{ even: true }, { even: false }],
    test: (e, p) => (e.page % 2 === 0) === p.even,
    text: p => `The killer’s page number is ${p.even ? 'even' : 'odd'}.`,
    source: 'The Night Porter',
    quote: p => `“The book lay open on the desk all night. The name I saw was on the ${p.even ? 'left-hand' : 'right-hand'} page — an ${p.even ? 'even' : 'odd'} one.”`,
  },
  {
    id: 'pageMultiple', tier: 'ledger',
    instances: () => [3, 4, 5, 6, 7].flatMap(k => [{ k, is: true }, { k, is: false }]),
    test: (e, p) => (e.page % p.k === 0) === p.is,
    text: p => p.is ? `The killer’s page number is a multiple of ${p.k}.` : `The killer’s page number is not a multiple of ${p.k}.`,
    source: 'The Clockmaker',
    quote: p => p.is ? `“The clock struck ${NUM[p.k]} and kept striking it — in multiples, you understand. It always means something.”` : `“Whatever page it was, you could not count to it in steps of ${NUM[p.k]}. I tried.”`,
  },
  {
    id: 'pageDigitSum', tier: 'ledger',
    instances: () => [{ even: true }, { even: false }],
    test: (e, p) => (digitSum(e.page) % 2 === 0) === p.even,
    text: p => `The digits of the killer’s page number add up to an ${p.even ? 'even' : 'odd'} number (for example, page 147 → 1 + 4 + 7 = 12).`,
    source: 'The Bank Clerk',
    quote: () => '“Old habit — I add up the digits of every number I see. That page number? I remember the total, if not the page.”',
  },
  {
    id: 'pageLastDigit', tier: 'ledger',
    instances: () => LAST_DIGIT_SETS.map(set => ({ set })),
    test: (e, p) => p.set.includes(e.page % 10),
    text: p => `The killer’s page number ends in ${p.set.length === 1 ? 'the digit ' : ''}${listOr(p.set)}.`,
    source: 'The Telegraph Clerk',
    quote: p => `“The telegram was torn; only the last digit of the page survived. It was ${listOr(p.set)} — the smudge could be any of them.”`,
  },
  {
    id: 'pageHasDigit', tier: 'ledger',
    instances: () => [1, 2, 3, 4, 5, 6, 7, 8, 9, 0].flatMap(d => [{ d, has: true }, { d, has: false }]),
    test: (e, p) => String(e.page).includes(String(p.d)) === p.has,
    text: p => p.has ? `The digit ${p.d} appears somewhere in the killer’s page number.` : `The digit ${p.d} does not appear anywhere in the killer’s page number.`,
    source: 'The Typesetter',
    quote: p => p.has ? `“The ${p.d} on my press was gummed with fresh ink. It had just been used to print that page number.”` : `“My ${p.d} type had gone missing that week. Whatever page it was, it was printed without one.”`,
  },
  {
    id: 'pageReversed', tier: 'ledger',
    instances: () => [{ larger: true }, { larger: false }],
    test: (e, p) => (reversed(e.page) > e.page) === p.larger,
    text: p => p.larger
      ? 'Written backwards, the killer’s page number becomes a larger number (for example, 148 → 841).'
      : 'Written backwards, the killer’s page number does not become larger (for example, 841 → 148; and 7 or 252 stay the same).',
    source: 'The Mirror-Maker',
    quote: () => '“I only ever saw the page number reflected in the glass — backwards, you see.”',
  },

  // ── placement ───────────────────────────────────────────────────────────
  {
    id: 'column', tier: 'placement',
    instances: () => [1, 2, 3].flatMap(col => [{ col, is: true }, { col, is: false }]),
    test: (e, p) => p.col !== undefined ? (e.col === p.col) === p.is : (e.col === 1) === p.left,
    text: p => p.col === undefined
      ? `The killer’s name is printed in the ${p.left ? 'left-hand' : 'right-hand'} column of its page.`
      : `The killer’s name is ${p.is ? '' : 'not '}printed in the ${COLUMN_NAME[p.col]} column of its page.`,
    source: 'The Housekeeper',
    quote: p => p.col === undefined
      ? `“The candle burned down the ${p.left ? 'left' : 'right'} side of the page. That’s where the finger was resting.”`
      : p.is ? `“The candle burned down the ${COLUMN_SIDE[p.col]} of the page. That’s where the finger was resting.”`
        : `“Wax had dripped all down the ${COLUMN_SIDE[p.col]} of the page. Whatever they were reading, it wasn’t there.”`,
  },
  {
    id: 'lineParity', tier: 'placement',
    instances: () => [{ odd: true }, { odd: false }],
    test: (e, p) => (e.line % 2 === 1) === p.odd,
    text: p => `The killer is on an ${p.odd ? 'odd' : 'even'}-numbered line.`,
    source: 'The Lamplighter',
    quote: p => `“I light every other lamp along the street — the ${p.odd ? 'odd' : 'even'} ones. The figure stood beneath a lit lamp.”`,
  },
  {
    id: 'lineHalf', tier: 'placement',
    instances: () => [{ top: true }, { top: false }],
    test: (e, p) => (e.line <= 12) === p.top,
    text: p => p.top ? 'The killer is on one of lines 1 to 12 of its column.' : 'The killer is on line 13 or a later line of its column.',
    source: 'The Café Owner',
    quote: p => `“There was a coffee ring on the page — on the ${p.top ? 'top' : 'bottom'} half. Lines ${p.top ? '1 to 12' : '13 and down'} were stained.”`,
  },
  {
    id: 'lineMultiple', tier: 'placement',
    instances: () => [3, 4, 5].flatMap(k => [{ k, is: true }, { k, is: false }]),
    test: (e, p) => (e.line % p.k === 0) === p.is,
    text: p => p.is ? `The killer’s line number is a multiple of ${p.k}.` : `The killer’s line number is not a multiple of ${p.k}.`,
    source: 'The Bell-Ringer',
    quote: p => p.is ? `“I ring the changes in ${NUM[p.k]}s. The line I heard called out fell right on the beat.”` : `“The line I heard called out never landed on a ${NUM[p.k]}-beat. Off-rhythm, it was.”`,
  },
  {
    id: 'linePrime', tier: 'placement',
    instances: () => [{ is: true }, { is: false }],
    test: (e, p) => LINE_PRIMES.includes(e.line) === p.is,
    text: p => p.is ? `The killer’s line number is prime: ${listOr(LINE_PRIMES)}.` : `The killer’s line number is not prime (it is not ${listOr(LINE_PRIMES)}).`,
    source: 'The Chess Champion',
    quote: p => p.is ? '“A prime line, of course. Murderers have no sense of humour.”' : '“Not a prime line. I checked twice, and I am never wrong twice.”',
  },

  // ── the name itself ─────────────────────────────────────────────────────
  {
    id: 'repeat', tier: 'name',
    instances: () => [{ has: true }, { has: false }],
    test: (e, p) => e.repeat === p.has,
    text: p => p.has ? 'At least one letter appears more than once in the killer’s name (as the A does in Ada; capitals count the same as small letters).' : 'No letter appears more than once in the killer’s name (capitals count the same as small letters — so Ada would not qualify).',
    source: 'The Crossword Setter',
    quote: p => p.has ? '“I tried to fit the name into my grid and it simply repeated itself.”' : '“It fitted my grid perfectly — not a single letter used twice.”',
  },
  {
    id: 'lengthEq', tier: 'name',
    instances: () => [4, 5, 6, 7, 8].map(k => ({ k })),
    test: (e, p) => e.len === p.k,
    text: p => `The killer’s name has exactly ${NUM[p.k]} letters.`,
    source: 'The Engraver',
    quote: p => `“I was paid to engrave a name on a silver cigarette case. ${NUM[p.k][0].toUpperCase() + NUM[p.k].slice(1)} letters, I charged by the letter.”`,
  },
  {
    id: 'lengthCmp', tier: 'name',
    instances: () => [5, 6, 7, 8].flatMap(k => [{ k, atLeast: true }, { k, atLeast: false }]),
    test: (e, p) => p.atLeast ? e.len >= p.k : e.len <= p.k,
    text: p => p.atLeast ? `The killer’s name has ${NUM[p.k]} or more letters.` : `The killer’s name has ${NUM[p.k]} or fewer letters.`,
    source: 'The Engraver',
    quote: p => p.atLeast ? `“They paid for at least ${NUM[p.k]} letters on the locket.”` : `“The locket only had room for ${NUM[p.k]} letters, and the name fitted.”`,
  },
  {
    id: 'lengthParity', tier: 'name',
    instances: () => [{ even: true }, { even: false }],
    test: (e, p) => (e.len % 2 === 0) === p.even,
    text: p => `The killer’s name has an ${p.even ? 'even' : 'odd'} number of letters.`,
    source: 'The Knitter',
    quote: p => `“I knitted the name into a scarf, two letters to a row. The last row came out ${p.even ? 'full' : 'with one letter on its own'}.”`,
  },
  {
    id: 'endsVowel', tier: 'name',
    instances: () => [{ vowel: true }, { vowel: false }],
    test: (e, p) => isVowel(e.lower[e.len - 1]) === p.vowel,
    text: p => p.vowel ? 'The killer’s name ends in a vowel (A, E, I, O or U).' : 'The killer’s name ends in a consonant (any letter but A, E, I, O or U — Y counts as a consonant).',
    source: 'The Parrot',
    quote: p => p.vowel ? '“…aaah-OOH! …eeee!” (The parrot only repeats the ends of names. These ended on a vowel.)' : '“…ck! …nd! …rrr!” (The parrot only repeats the ends of names. These ended hard.)',
  },
  {
    id: 'contains', tier: 'name',
    instances: () => COMMON_LETTERS.flatMap(c => [{ c, has: true }, { c, has: false }]),
    test: (e, p) => e.lower.includes(p.c) === p.has,
    text: p => p.has ? `The letter ${p.c.toUpperCase()} appears in the killer’s name (as a capital or small letter).` : `The letter ${p.c.toUpperCase()} does not appear anywhere in the killer’s name.`,
    source: 'The Locksmith',
    quote: p => p.has ? `“The key had a letter stamped on its bow: ${p.c.toUpperCase()}. Always a letter from the owner’s name.”` : `“The typewriter in the study has a broken ${p.c.toUpperCase()} key — the killer’s note was typed without one.”`,
  },
  {
    id: 'vowelCount', tier: 'name',
    instances: () => [1, 2, 3, 4].map(k => ({ k })),
    test: (e, p) => e.vowels === p.k,
    text: p => `The killer’s name contains exactly ${NUM[p.k]} vowel${p.k > 1 ? 's' : ''} (count every A, E, I, O and U; Y is not a vowel).`,
    source: 'The Singing Teacher',
    quote: p => `“I could hear them sing their own name through the wall — ${NUM[p.k]} open note${p.k > 1 ? 's' : ''}, no more.”`,
  },
  {
    id: 'double', tier: 'name',
    instances: () => [{ has: true }, { has: false }],
    test: (e, p) => e.double === p.has,
    text: p => p.has ? 'The killer’s name has a double letter — the same letter twice in a row, like the NN in Anna.' : 'The killer’s name has no double letters — no letter appears twice in a row.',
    source: 'The Stenographer',
    quote: p => p.has ? '“My shorthand for the name had a little doubling mark in it.”' : '“Clean shorthand, no doubling marks. I remember because it was the only easy one that day.”',
  },
  {
    id: 'secondVowel', tier: 'name',
    instances: () => [{ vowel: true }, { vowel: false }],
    test: (e, p) => e.len >= 2 && isVowel(e.lower[1]) === p.vowel,
    text: p => p.vowel ? 'The second letter of the killer’s name is a vowel (A, E, I, O or U).' : 'The second letter of the killer’s name is a consonant (Y counts as a consonant).',
    source: 'The Chimney Sweep',
    quote: () => '“The soot smudged the name on the envelope. I could only make out the second letter.”',
  },
  {
    id: 'lastHalf', tier: 'name',
    instances: () => [{ first: true }, { first: false }],
    test: (e, p) => (e.lower.charCodeAt(e.len - 1) - 97 < 13) === p.first,
    text: p => p.first ? 'The killer’s name ends with a letter from the first half of the alphabet (A to M).' : 'The killer’s name ends with a letter from the second half of the alphabet (N to Z).',
    source: 'The Archivist',
    quote: p => `“The last letter of the name was filed in my ${p.first ? 'A-to-M' : 'N-to-Z'} drawer. I never misfile.”`,
  },
  {
    id: 'balance', tier: 'name',
    instances: () => [{ more: 'consonants' }, { more: 'vowels' }, { more: 'equal' }],
    test: (e, p) => p.more === 'consonants' ? e.consonants > e.vowels : p.more === 'vowels' ? e.vowels > e.consonants : e.vowels === e.consonants,
    text: p => p.more === 'equal'
      ? 'The killer’s name has exactly as many vowels as consonants (vowels are A, E, I, O, U; Y is a consonant).'
      : `The killer’s name has more ${p.more} than ${p.more === 'vowels' ? 'consonants' : 'vowels'} (vowels are A, E, I, O, U; Y is a consonant).`,
    source: 'The Organist', // spelling-check: ignore (a church organist, not “organise”)
    quote: p => p.more === 'equal' ? '“A perfectly balanced name. Soft and hard in equal measure.”' : `“The name was all ${p.more === 'vowels' ? 'breath and air' : 'clicks and edges'} — more ${p.more} than anything.”`,
  },
  {
    id: 'pair', tier: 'name',
    instances: () => PAIRS.flatMap(pr => [{ pr, has: true }, { pr, has: false }]),
    test: (e, p) => e.lower.includes(p.pr) === p.has,
    text: p => p.has
      ? `The letters ${p.pr[0].toUpperCase()} and ${p.pr[1].toUpperCase()} appear side by side in the killer’s name, in that order (“${p.pr}”).`
      : `The letters ${p.pr[0].toUpperCase()} and ${p.pr[1].toUpperCase()} never appear side by side, in that order (“${p.pr}”), in the killer’s name.`,
    source: 'The Ferryman',
    quote: p => p.has ? `“Torn ticket stub. All that was left of the passenger’s name was ‘${p.pr}’.”` : `“I’ve a superstition about names with ‘${p.pr}’ in them. Never would’ve rowed one.”`,
  },

  // ── connections: neighbours in the register, and the victim ─────────────
  {
    id: 'prevLength', tier: 'connection',
    instances: () => [{ cmp: 'longer' }, { cmp: 'shorter' }, { cmp: 'same' }],
    test: (e, p, ctx) => {
      const prev = ctx.entries[e.i - 1];
      if (!prev) return false;
      return p.cmp === 'longer' ? prev.len > e.len : p.cmp === 'shorter' ? prev.len < e.len : prev.len === e.len;
    },
    text: p => `The name listed immediately before the killer’s in the Register ${p.cmp === 'same' ? 'has exactly as many letters as' : `has ${p.cmp === 'longer' ? 'more' : 'fewer'} letters than`} the killer’s name.`,
    source: 'The Neighbour',
    quote: p => p.cmp === 'same' ? '“Our names sit one above the other in the Register, and they’re the same length — I always thought that was a sign.”' : `“My name comes right before theirs in the Register, and mine’s the ${p.cmp === 'longer' ? 'longer' : 'shorter'} one. I’ve always resented that.”`,
  },
  {
    id: 'nextLast', tier: 'connection',
    instances: () => [{ same: true }, { same: false }],
    test: (e, p, ctx) => {
      const next = ctx.entries[e.i + 1];
      if (!next) return false;
      return (next.lower[next.len - 1] === e.lower[e.len - 1]) === p.same;
    },
    text: p => `The name listed immediately after the killer’s in the Register ends in ${p.same ? 'the same letter as' : 'a different letter from'} the killer’s name.`,
    source: 'The Poet',
    quote: p => p.same ? '“Their name rhymes with the next one in the Register — well, the last letters do. Close enough for poetry.”' : '“I tried to rhyme their name with the next one in the Register. Hopeless. Not even the last letters match.”',
  },
  {
    id: 'besideLength', tier: 'connection', legacy: true, // two-column books only
    instances: () => [{ cmp: 'longer' }, { cmp: 'shorter' }],
    test: (e, p, ctx) => {
      const b = beside(ctx.book, e);
      if (!b) return false;
      return p.cmp === 'longer' ? e.len > b.len : e.len < b.len;
    },
    text: p => `The killer’s name is ${p.cmp} than the name printed directly beside it — the other column, same line, same page. (If no name is beside it, this cannot be the killer.)`,
    source: 'The Tailor',
    quote: p => `“I measure everything. Their name, set against the one across from it on the page, came up ${p.cmp}.”`,
  },
  {
    id: 'victimShare', tier: 'connection', usesVictim: true,
    instances: () => [0, 1, 2, 3].map(k => ({ k })),
    test: (e, p, ctx) => popcount(e.mask & ctx.victim.mask) === p.k,
    text: (p, ctx) => p.k === 0
      ? `The killer’s name has no letters in common with the victim’s name, ${ctx.victim.name.toUpperCase()}.`
      : `The killer’s name shares exactly ${NUM[p.k]} different letter${p.k > 1 ? 's' : ''} with the victim’s name, ${ctx.victim.name.toUpperCase()} (count each shared letter once, however often it appears).`,
    source: 'The Medium',
    quote: (p, ctx) => `“${ctx.victim.name} spoke to me last night. They spelled out the killer with letters from their own name — ${p.k === 0 ? 'or tried to. None of them fit' : `${NUM[p.k]} of them, and no more`}.”`,
  },
  {
    id: 'victimLength', tier: 'connection', usesVictim: true,
    instances: () => [{ cmp: 'longer' }, { cmp: 'shorter' }, { cmp: 'same' }],
    test: (e, p, ctx) => p.cmp === 'longer' ? e.len > ctx.victim.len : p.cmp === 'shorter' ? e.len < ctx.victim.len : e.len === ctx.victim.len,
    text: (p, ctx) => `The killer’s name is ${p.cmp === 'same' ? 'exactly as long as' : `${p.cmp} than`} the victim’s name, ${ctx.victim.name.toUpperCase()} (${NUM[ctx.victim.len] || ctx.victim.len} letters).`,
    source: 'The Undertaker',
    quote: (p, ctx) => `“Two brass plates were ordered the same morning — one for ${ctx.victim.name}, and one that was ${p.cmp === 'same' ? 'exactly the same size' : p.cmp === 'longer' ? 'longer' : 'shorter'}. I wondered who the second was for.”`,
  },
  {
    id: 'pageFirstSecond', tier: 'connection',
    instances: () => [{ same: true }, { same: false }],
    test: (e, p, ctx) => {
      const first = ctx.entries[ctx.book.pages[e.page - 1].cols[0][0]];
      return (first.lower[1] === e.lower[1]) === p.same;
    },
    text: p => `The second letter of the killer’s name is ${p.same ? 'the same as' : 'different from'} the second letter of the first name on its page (top of the left-hand column).${p.same ? ' (If the killer is that first name, this is true.)' : ' (If the killer is that first name, this cannot be true.)'}`,
    source: 'The Printer’s Devil',
    quote: () => '“I set the first name on every page by hand. I remember thinking theirs looked like it belonged with it — or didn’t.”',
  },
  {
    id: 'neighbourEnds', tier: 'connection',
    instances: () => [{ vowel: true }, { vowel: false }],
    test: (e, p, ctx) => {
      const a = ctx.entries[e.i - 1], b = ctx.entries[e.i + 1];
      if (!a || !b) return false;
      return isVowel(a.lower[a.len - 1]) === p.vowel && isVowel(b.lower[b.len - 1]) === p.vowel;
    },
    text: p => `The names listed immediately before and immediately after the killer’s in the Register both end in a ${p.vowel ? 'vowel (A, E, I, O or U)' : 'consonant (Y counts as a consonant)'}.`,
    source: 'The Gossip',
    quote: () => '“I know both their neighbours in the Register, dear. Same sort of people. Their names even end alike.”',
  },

  // ── added with the one-clue-per-type system ─────────────────────────────
  {
    id: 'containsAny', tier: 'name',
    instances: () => LETTER_TRIOS.flatMap(set => [{ set, has: true }, { set, has: false }]),
    test: (e, p) => p.set.some(c => e.lower.includes(c)) === p.has,
    text: p => p.has
      ? `The killer’s name contains at least one of the letters ${listOr(p.set.map(c => c.toUpperCase()))}.`
      : `The killer’s name contains none of the letters ${listAnd(p.set.map(c => c.toUpperCase()))}.`,
    source: 'The Cryptographer',
    quote: p => p.has
      ? `“The cipher on the back of the photograph only used three letters: ${listAnd(p.set.map(c => c.toUpperCase()))}. At least one of them is in the name.”`
      : `“My cipher wheel is missing ${listAnd(p.set.map(c => c.toUpperCase()))}. It spelled the name perfectly well without them.”`,
  },
  {
    id: 'thirdVowel', tier: 'name',
    instances: () => [{ vowel: true }, { vowel: false }],
    test: (e, p) => e.len >= 3 && isVowel(e.lower[2]) === p.vowel,
    text: p => p.vowel ? 'The third letter of the killer’s name is a vowel (A, E, I, O or U).' : 'The third letter of the killer’s name is a consonant (Y counts as a consonant).',
    source: 'The Choirmaster',
    quote: p => `“They sang their name for me at choir practice. The third note was ${p.vowel ? 'open — a vowel' : 'clipped — a consonant'}.”`,
  },
  {
    id: 'secondHalf', tier: 'name',
    instances: () => [{ first: true }, { first: false }],
    test: (e, p) => e.len >= 2 && (e.lower.charCodeAt(1) - 97 < 13) === p.first,
    text: p => `The second letter of the killer’s name comes from the ${p.first ? 'first half of the alphabet (A to M)' : 'second half of the alphabet (N to Z)'}.`,
    source: 'The Filing Clerk',
    quote: p => `“I file by the second letter — don’t ask. Theirs went in the ${p.first ? 'A-to-M' : 'N-to-Z'} cabinet.”`,
  },
  {
    id: 'endsIn', tier: 'name',
    instances: () => ENDINGS.map(set => ({ set })),
    test: (e, p) => p.set.includes(e.lower[e.len - 1]),
    text: p => `The killer’s name ends in ${p.set.length === 1 ? 'the letter ' : ''}${listOr(p.set.map(c => c.toUpperCase()))}.`,
    source: 'The Night Watchman',
    quote: p => `“I shouted the name across the square and only the end came back off the church wall: ${listOr(p.set.map(c => c.toUpperCase()))}, or near enough.”`,
  },
  {
    id: 'firstVsLast', tier: 'name',
    instances: () => [{ cmp: 'earlier' }, { cmp: 'later' }],
    test: (e, p) => { const a = e.lower[0], z = e.lower[e.len - 1]; return p.cmp === 'earlier' ? a < z : a > z; },
    text: p => `The first letter of the killer’s name comes ${p.cmp} in the alphabet than its last letter. (If they are the same letter, it does not count.)`,
    source: 'The Librarian',
    quote: p => `“I shelve names by their first and last letters. Theirs ran ${p.cmp === 'earlier' ? 'forwards — A-ward to Z-ward' : 'backwards, which I find suspicious in a person'}.”`,
  },
  {
    id: 'secondVsFirst', tier: 'name',
    instances: () => [{ cmp: 'later' }, { cmp: 'earlier' }],
    test: (e, p) => { const a = e.lower[0], b = e.lower[1]; return p.cmp === 'later' ? b > a : b < a; },
    text: p => `The second letter of the killer’s name comes ${p.cmp} in the alphabet than the first letter. (If they are the same letter, it does not count.)`,
    source: 'The Indexer',
    quote: p => `“The first two letters of the name were in ${p.cmp === 'later' ? 'proper' : 'reverse'} alphabetical order. I notice these things. It is my curse.”`,
  },
  {
    id: 'vowelRun', tier: 'name',
    instances: () => [{ has: true }, { has: false }],
    test: (e, p) => /[aeiou]{2}/.test(e.lower) === p.has,
    text: p => p.has
      ? 'Somewhere in the killer’s name, two vowels stand side by side (like the EA in Sean; vowels are A, E, I, O and U).'
      : 'Nowhere in the killer’s name do two vowels stand side by side (vowels are A, E, I, O and U).',
    source: 'The Elocution Teacher',
    quote: p => p.has ? '“A name with a glide in it — two vowels running together. Very hard to say crossly.”' : '“Not one glide in the whole name. Every vowel stood on its own.”',
  },
  {
    id: 'consonantRun', tier: 'name',
    instances: () => [{ has: true }, { has: false }],
    test: (e, p) => /[^aeiou]{2}/.test(e.lower) === p.has,
    text: p => p.has
      ? 'Somewhere in the killer’s name, two consonants stand side by side (like the ND in Andrew; a double letter such as NN counts, and Y is a consonant).'
      : 'Nowhere in the killer’s name do two consonants stand side by side (a double letter such as NN would count; Y is a consonant).',
    source: 'The Elocution Teacher',
    quote: p => p.has ? '“There’s a knot in that name — two consonants jammed together. Trips the tongue.”' : '“Not one knot in the whole name — no two consonants ever stood together.”',
  },
  {
    id: 'prevLast', tier: 'connection',
    instances: () => [{ same: true }, { same: false }],
    test: (e, p, ctx) => {
      const prev = ctx.entries[e.i - 1];
      if (!prev) return false;
      return (prev.lower[prev.len - 1] === e.lower[e.len - 1]) === p.same;
    },
    text: p => `The name listed immediately before the killer’s in the Register ends in ${p.same ? 'the same letter as' : 'a different letter from'} the killer’s name.`,
    source: 'The Neighbour Upstairs',
    quote: p => p.same ? '“Our names end the same way. People mix up our post.”' : '“My name sits just above theirs in the Register. Nothing alike, thank heavens — not even the last letter.”',
  },
  {
    id: 'nextLength', tier: 'connection',
    instances: () => [{ cmp: 'longer' }, { cmp: 'shorter' }, { cmp: 'same' }],
    test: (e, p, ctx) => {
      const next = ctx.entries[e.i + 1];
      if (!next) return false;
      return p.cmp === 'longer' ? next.len > e.len : p.cmp === 'shorter' ? next.len < e.len : next.len === e.len;
    },
    text: p => `The name listed immediately after the killer’s in the Register ${p.cmp === 'same' ? 'has exactly as many letters as' : `has ${p.cmp === 'longer' ? 'more' : 'fewer'} letters than`} the killer’s name.`,
    source: 'The Neighbour Downstairs',
    quote: p => p.cmp === 'same' ? '“My name comes right after theirs, and it’s the very same length. We’ve never liked each other.”' : `“I come right after them in the Register. My name’s the ${p.cmp} one — always has been.”`,
  },
  {
    id: 'besideLast', tier: 'connection', legacy: true, // two-column books only
    instances: () => [{ same: true }, { same: false }],
    test: (e, p, ctx) => {
      const b = beside(ctx.book, e);
      if (!b) return false;
      return (b.lower[b.len - 1] === e.lower[e.len - 1]) === p.same;
    },
    text: p => `The killer’s name ends in ${p.same ? 'the same letter as' : 'a different letter from'} the name printed directly beside it — the other column, same line, same page. (If no name is beside it, this cannot be the killer.)`,
    source: 'The Proofreader',
    quote: p => p.same ? '“The two names on that line ended alike. I marked it as a possible misprint.”' : '“Two names side by side on the line, and their endings didn’t match. No misprint there.”',
  },
  {
    id: 'neighbourLength', tier: 'connection',
    instances: () => [{ cmp: 'longer' }, { cmp: 'shorter' }],
    test: (e, p, ctx) => {
      const a = ctx.entries[e.i - 1], b = ctx.entries[e.i + 1];
      if (!a || !b) return false;
      return p.cmp === 'longer' ? a.len > e.len && b.len > e.len : a.len < e.len && b.len < e.len;
    },
    text: p => `The names listed immediately before and immediately after the killer’s in the Register are both ${p.cmp} than the killer’s name.`,
    source: 'The Gossip',
    quote: p => p.cmp === 'longer' ? '“Hemmed in by grander names on both sides, poor thing. It does something to a person.”' : '“Their name looms over both its neighbours in the Register. It shows in the character.”',
  },
  {
    id: 'pageFirstLength', tier: 'connection',
    instances: () => [{ cmp: 'longer' }, { cmp: 'shorter' }],
    test: (e, p, ctx) => {
      const first = ctx.entries[ctx.book.pages[e.page - 1].cols[0][0]];
      return p.cmp === 'longer' ? e.len > first.len : e.len < first.len;
    },
    text: p => `The killer’s name is ${p.cmp} than the first name printed on its page (top of the left-hand column). (If the killer is that first name, this cannot be true.)`,
    source: 'The Printer’s Devil',
    quote: p => `“I measure every page against its first name. Theirs came up ${p.cmp}.”`,
  },

  // ── the novel layout: chapter numbers, and names sharing a line ─────────
  {
    id: 'chapterParity', tier: 'registry',
    instances: () => [{ even: true }, { even: false }],
    test: (e, p) => ((e.ci + 1) % 2 === 0) === p.even,
    text: p => `The killer appears in an ${p.even ? 'even' : 'odd'}-numbered chapter.`,
    source: 'The Bookbinder',
    quote: p => `“Every ${p.even ? 'second' : 'other'} chapter of the Register was rebound last spring — the ${p.even ? 'even' : 'odd'} ones. Theirs still smells of fresh glue.”`,
  },
  {
    id: 'chapterPrime', tier: 'registry',
    instances: () => [{ is: true }, { is: false }],
    test: (e, p) => PRIMES.has(e.ci + 1) === p.is,
    text: p => p.is ? 'The killer’s chapter number is prime (Two, Three, Five, Seven, Eleven, Thirteen, …; One is not prime).' : 'The killer’s chapter number is not prime (One counts as not prime).',
    source: 'The Mathematics Tutor',
    quote: p => p.is ? '“A prime chapter. Of course it was. Indivisible, like a guilty conscience.”' : '“Not a prime chapter. I’d have noticed — I always notice.”',
  },
  {
    id: 'chapterMultiple', tier: 'registry',
    instances: () => [3, 4].flatMap(k => [{ k, is: true }, { k, is: false }]),
    test: (e, p) => ((e.ci + 1) % p.k === 0) === p.is,
    text: p => p.is ? `The killer’s chapter number is a multiple of ${p.k}.` : `The killer’s chapter number is not a multiple of ${p.k}.`,
    source: 'The Metronome Seller',
    quote: p => p.is ? `“The chapter chimed with my ${NUM[p.k]}-beat clock. They always do, the guilty ones.”` : `“The chapter never fell on my ${NUM[p.k]}-beat clock. Not once.”`,
  },
  {
    id: 'chapterRange', tier: 'registry',
    // Only ranges inside the book's real chapters; the balance caps pick sensible widths.
    instances: ctx => {
      const n = ctx.book.chapters.length, out = [];
      for (let a = 1; a <= n; a++) for (let b = a + 1; b <= n; b++) if (!(a === 1 && b === n)) out.push({ from: a, to: b, neg: false }, { from: a, to: b, neg: true });
      return out;
    },
    test: (e, p) => ((e.ci + 1) >= p.from && (e.ci + 1) <= p.to) !== p.neg,
    text: p => p.neg
      ? `The killer does not appear anywhere in Chapters ${numberWord(p.from)} through ${numberWord(p.to)}.`
      : `The killer appears somewhere in Chapters ${numberWord(p.from)} through ${numberWord(p.to)}.`,
    source: 'The Shelver',
    quote: p => p.neg
      ? `“Chapters ${numberWord(p.from)} to ${numberWord(p.to)} were out on loan that week. The killer never had them.”`
      : `“Only Chapters ${numberWord(p.from)} to ${numberWord(p.to)} show fresh thumbprints on their edges.”`,
  },
  {
    id: 'chapterSpelled', tier: 'registry',
    instances: () => 'etnviorfuwxsh'.split('').flatMap(c => [{ c, has: true }, { c, has: false }]),
    test: (e, p) => numberWord(e.ci + 1).toLowerCase().includes(p.c) === p.has,
    text: p => `The killer’s chapter number, spelled out as in its heading (Seven, Twenty-One, …), ${p.has ? 'contains' : 'does not contain'} the letter ${p.c.toUpperCase()}.`,
    source: 'The Sign Painter',
    quote: p => p.has ? `“I painted the chapter numbers on the shelf ends. Theirs used up the last of my ${p.c.toUpperCase()} stencil.”` : `“I painted the chapter numbers on the shelf ends. Never needed my ${p.c.toUpperCase()} stencil for theirs.”`,
  },
  {
    id: 'pageInChapter', tier: 'registry',
    instances: () => [2, 3, 4, 5, 6, 8, 10].flatMap(k => [{ k, end: 'first' }, { k, end: 'notFirst' }, { k, end: 'last' }, { k, end: 'notLast' }]),
    test: (e, p, ctx) => {
      const ch = ctx.book.chapters[e.ci];
      const fromStart = e.page - ch.firstPage + 1, fromEnd = ch.lastPage - e.page + 1;
      return p.end === 'first' ? fromStart <= p.k : p.end === 'notFirst' ? fromStart > p.k : p.end === 'last' ? fromEnd <= p.k : fromEnd > p.k;
    },
    text: p => p.end === 'first' ? `The killer is on one of the first ${NUM[p.k]} pages of its chapter (the chapter’s opening page counts as the first).`
      : p.end === 'notFirst' ? `The killer is not on any of the first ${NUM[p.k]} pages of its chapter (the chapter’s opening page counts as the first).`
      : p.end === 'last' ? `The killer is on one of the last ${NUM[p.k]} pages of its chapter (the chapter’s final page counts as the last).`
      : `The killer is not on any of the last ${NUM[p.k]} pages of its chapter (the chapter’s final page counts as the last).`,
    source: 'The Bookmark',
    quote: p => p.end === 'last' ? '“A ribbon bookmark was left near the end of a chapter — the killer was nearly through it.”' : p.end === 'notLast' ? '“The closing pages of the chapter were still stuck together. The killer never got that far.”' : p.end === 'first' ? '“A ribbon bookmark was left just past a chapter heading — the killer had barely begun.”' : '“The opening pages of the chapter were uncut. The killer had skipped straight past them.”',
  },
  {
    id: 'lineLength', tier: 'connection',
    instances: () => [{ cmp: 'longest' }, { cmp: 'shortest' }, { cmp: 'neither' }],
    test: (e, p, ctx) => {
      const m = lineMates(ctx.book, e);
      if (!m.length) return false;
      const longest = m.every(x => e.len > x.len), shortest = m.every(x => e.len < x.len);
      return p.cmp === 'longest' ? longest : p.cmp === 'shortest' ? shortest : !longest && !shortest;
    },
    text: p => p.cmp === 'neither'
      ? 'Among the names on the killer’s line (same page, all columns), the killer’s name is neither strictly the longest nor strictly the shortest. (If no other name shares the line, this cannot be the killer.)'
      : `The killer’s name is ${p.cmp === 'longest' ? 'longer' : 'shorter'} than every other name on the same line (same page, all columns). (If no other name shares the line, this cannot be the killer.)`,
    source: 'The Tailor',
    quote: p => p.cmp === 'neither' ? '“I measured every name on that line. Theirs was middling — not the longest, not the shortest.”' : `“I measure everything. Of all the names on that line, theirs was the ${p.cmp}.”`,
  },
  {
    id: 'lineLast', tier: 'connection',
    instances: () => [{ shared: true }, { shared: false }],
    test: (e, p, ctx) => {
      const m = lineMates(ctx.book, e);
      if (!m.length) return false;
      return m.some(x => x.lower[x.len - 1] === e.lower[e.len - 1]) === p.shared;
    },
    text: p => p.shared
      ? 'At least one other name on the killer’s line (same page, any column) ends in the same letter as the killer’s name.'
      : 'No other name on the killer’s line (same page, any column) ends in the same letter as the killer’s name. (If no other name shares the line, this cannot be the killer.)',
    source: 'The Proofreader',
    quote: p => p.shared ? '“Two names on that line ended alike. I marked it as a possible misprint.”' : '“Every name on that line ended differently. A clean line — no misprints.”',
  },
  {
    id: 'lineInitial', tier: 'connection',
    instances: () => [{ shared: true }, { shared: false }],
    test: (e, p, ctx) => {
      const m = lineMates(ctx.book, e);
      if (!m.length) return false;
      return m.some(x => x.lower[0] === e.lower[0]) === p.shared;
    },
    text: p => p.shared
      ? 'At least one other name on the killer’s line (same page, any column) begins with the same letter as the killer’s name.'
      : 'No other name on the killer’s line (same page, any column) begins with the same letter as the killer’s name. (If no other name shares the line, this cannot be the killer.)',
    source: 'The Typesetter’s Apprentice',
    quote: p => p.shared ? '“I ran short of one capital setting that line — two names on it wanted the same letter.”' : '“Every name on that line wanted a different capital. I remember because I had them all.”',
  },

  // ── families and namesakes (full-name registers only) ───────────────────
  {
    id: 'familyNeighbour', tier: 'connection',
    instances: ctx => ctx?.book?.fullNames ? [{ has: true }, { has: false }] : [],
    test: (e, p, ctx) => {
      const same = x => !!x && x.last.lower === e.last.lower;
      return (same(ctx.entries[e.i - 1]) || same(ctx.entries[e.i + 1])) === p.has;
    },
    text: p => p.has
      ? 'The person listed immediately before or immediately after the killer in the Register shares the killer’s surname.'
      : 'Neither the person listed immediately before nor the one immediately after the killer in the Register shares the killer’s surname.',
    source: 'The Ticket Clerk',
    quote: p => p.has ? '“They came through with family, by the look of them — the same name on the next line.”' : '“Came through on their own, that one. Nobody either side of them shared the name.”',
  },
  {
    id: 'familyPosition', tier: 'connection',
    instances: ctx => ctx?.book?.fullNames ? [{ at: 'head' }, { at: 'tail' }] : [],
    test: (e, p, ctx) => {
      const same = x => !!x && x.last.lower === e.last.lower;
      const a = same(ctx.entries[e.i - 1]), b = same(ctx.entries[e.i + 1]);
      return p.at === 'head' ? !a && b : a && !b;
    },
    text: p => p.at === 'head'
      ? 'The killer is listed first in a family group: the person immediately before has a different surname, and the person immediately after shares the killer’s surname.'
      : 'The killer is listed last in a family group: the person immediately before shares the killer’s surname, and the person immediately after has a different one.',
    source: 'The Clerk of the Register',
    quote: p => p.at === 'head' ? '“Whoever signs for a family writes their own name first. This one did.”' : '“Last of the family to be written down — the one nobody waited for.”',
  },
  {
    id: 'pageNamesake', tier: 'connection',
    instances: ctx => ctx?.book?.fullNames ? ['first', 'last'].flatMap(part => [{ part, has: true }, { part, has: false }]) : [],
    test: (e, p, ctx) => {
      const key = x => (p.part === 'last' ? x.last : x.first).lower, k = key(e);
      for (const col of ctx.book.pages[e.page - 1].cols) for (const j of col) if (j !== e.i && key(ctx.entries[j]) === k) return p.has;
      return !p.has;
    },
    text: p => `${p.has ? 'Someone else' : 'No one else'} on the killer’s page has the same ${p.part === 'last' ? 'surname' : 'first name'} as the killer (accents don’t count).`,
    source: 'The Copyist',
    quote: p => p.has ? '“I had to write that name twice on the same page. It made my hand ache.”' : '“Not a single repeat of that name on the whole page — I would have noticed.”',
  },
  {
    id: 'columnNamesake', tier: 'connection',
    instances: ctx => ctx?.book?.fullNames ? ['first', 'last'].flatMap(part => [{ part, has: true }, { part, has: false }]) : [],
    test: (e, p, ctx) => {
      const key = x => (p.part === 'last' ? x.last : x.first).lower, k = key(e);
      for (const j of ctx.book.pages[e.page - 1].cols[e.col - 1]) if (j !== e.i && key(ctx.entries[j]) === k) return p.has;
      return !p.has;
    },
    text: p => `${p.has ? 'Someone else' : 'No one else'} in the killer’s column (same page) has the same ${p.part === 'last' ? 'surname' : 'first name'} as the killer (accents don’t count).`,
    source: 'The Proof Reader’s Assistant',
    quote: p => p.has ? '“That column had the same name in it twice. I flagged it as a possible error.”' : '“Every name in that column was different. A tidy column.”',
  },

  // ── engine 7: sections of the register, anchored to people in it ──────────
  // These have too many possible forms to list, so each search attempt draws
  // a fresh sample that fits its killer (`sample`); `test` and `text` need only
  // the params. Anchors are people whose full name appears exactly once.
  {
    id: 'span', tier: 'record', sampled: true,
    sample: (rng, ctx, k, n) => {
      const U = uniqueAnchors(ctx.book), N = ctx.entries.length, out = [];
      for (let t = 0; t < n * 4 && out.length < n; t++) {
        const inside = rng.chance(0.5);
        const len = Math.round(N * (inside ? 0.2 + rng.next() * 0.66 : 0.12 + rng.next() * 0.5));
        const lo = inside ? Math.max(0, k - rng.int(len)) : rng.int(Math.max(1, N - len));
        const a = U[lowerBound(U, lo)], b = U[lowerBound(U, Math.min(N - 1, lo + len) + 1) - 1];
        if (a === undefined || b === undefined || b - a < N * 0.05 || a === k || b === k || a === ctx.victimIdx || b === ctx.victimIdx) continue;
        if ((k >= a && k <= b) === inside) out.push({ a, b, inside });
      }
      return out;
    },
    test: (e, p) => (e.i >= p.a && e.i <= p.b) === p.inside,
    text: (p, ctx) => p.inside
      ? `The killer is listed between ${who(ctx, p.a)} and ${who(ctx, p.b)} in the Register, or is one of them. (Each of those two names appears only once.)`
      : `The killer is not listed between ${who(ctx, p.a)} and ${who(ctx, p.b)} in the Register, and is neither of them. (Each of those two names appears only once.)`,
    source: 'The Archivist',
    quote: (p, ctx) => p.inside
      ? `“Someone tore the pages out of my copy — everything from ${who(ctx, p.a)} on, up to ${who(ctx, p.b)}. Why those, unless they were looking for someone?”`
      : `“I read the Register aloud to the Inspector, from ${who(ctx, p.a)} right through to ${who(ctx, p.b)}. Not one of those had been anywhere near.”`,
  },
  {
    id: 'landmark', tier: 'record', sampled: true,
    sample: (rng, ctx, k, n) => {
      const out = [], N = ctx.entries.length;
      for (let t = 0; t < n * 6 && out.length < n; t++) {
        const r = ctx.entries[rng.int(N)], part = rng.chance(0.5) ? 'first' : 'last';
        const value = r[part].lower, occ = occurrences(ctx.book, part, value);
        if (occ.length < 3 || occ.length > 15) continue;
        const which = rng.chance(0.5) ? 'first' : 'last', dir = rng.chance(0.5) ? 'after' : 'before';
        const at = which === 'first' ? occ[0] : occ[occ.length - 1];
        if (at === k || (dir === 'after' ? k > at : k < at)) out.push({ part, value, which, dir, at });
      }
      return out;
    },
    test: (e, p) => p.dir === 'after' ? e.i > p.at : e.i < p.at,
    text: (p, ctx) => `The killer is listed ${p.dir} the ${p.which} person in the Register whose ${PART_WORD[p.part]} is ${partName(ctx, p)}.`,
    source: 'The Bookseller',
    quote: (p, ctx) => p.dir === 'after'
      ? `“I always look up the ${p.which} ${partName(ctx, p)} in a new Register — call it a hobby. The killer’s name was further on.”`
      : `“I always look up the ${p.which} ${partName(ctx, p)} in a new Register. The killer’s name came before it; I noticed it on the way.”`,
  },
  {
    id: 'victimSpan', tier: 'record', sampled: true,
    sample: (rng, ctx, k, n) => {
      const out = [], v = ctx.victim, ke = ctx.entries[k], pages = ctx.book.pageCount;
      for (let t = 0; t < n * 4 && out.length < n; t++) {
        const mode = rng.pick(['within', 'within', 'beyond', 'side']);
        if (mode === 'side') { out.push({ mode, after: ke.i > v.i }); continue; }
        const d = 2 + rng.int(Math.max(3, Math.floor(pages * 0.45)));
        const near = Math.abs(ke.page - v.page) <= d;
        if (near === (mode === 'within')) out.push({ mode, d });
      }
      return out;
    },
    test: (e, p, ctx) => p.mode === 'side' ? (e.i > ctx.victim.i) === p.after
      : (Math.abs(e.page - ctx.victim.page) <= p.d) === (p.mode === 'within'),
    text: (p, ctx) => p.mode === 'side'
      ? `The killer is listed ${p.after ? 'after' : 'before'} the victim, ${ctx.victim.name}, in the Register.`
      : p.mode === 'within'
        ? `The killer’s page is no more than ${p.d} pages from the victim’s page, counting either way (so the victim’s own page, and the ${p.d} pages either side of it).`
        : `The killer’s page is more than ${p.d} pages from the victim’s page, counting either way.`,
    source: 'The Inspector', usesVictim: true,
    quote: (p, ctx) => p.mode === 'side'
      ? `“${ctx.victim.name} was entered ${p.after ? 'before' : 'after'} the killer. People are creatures of habit: they queue in the order they arrive.”`
      : p.mode === 'within' ? '“The killer had been watching the victim for weeks. They’d have signed in close by.”' : '“Whoever did it made very sure to be entered nowhere near the victim.”',
  },
  {
    id: 'chapterCompany', tier: 'record', sampled: true,
    sample: (rng, ctx, k, n) => {
      const out = [], N = ctx.entries.length;
      for (let t = 0; t < n * 6 && out.length < n; t++) {
        const r = ctx.entries[rng.int(N)], part = rng.chance(0.5) ? 'first' : 'last';
        const value = r[part].lower, occ = occurrences(ctx.book, part, value);
        if (occ.length < 2 || occ.length > 8) continue;
        const p = { part, value, at: occ[0], has: rng.chance(0.6) };
        if (chapterHas(ctx, ctx.entries[k], p) === p.has) out.push(p);
      }
      return out;
    },
    test: (e, p, ctx) => chapterHas(ctx, e, p) === p.has,
    text: (p, ctx) => `${p.has ? 'Someone else' : 'No one else'} in the killer’s chapter has the ${PART_WORD[p.part]} ${partName(ctx, p)}.`,
    source: 'The Census Taker',
    quote: (p, ctx) => p.has
      ? `“I took that chapter’s names door to door. I remember a ${partName(ctx, p)} on the same round as the killer.”`
      : `“Not one ${partName(ctx, p)} on the killer’s round — I’d have remembered the name.”`,
  },

  // ── engine 7: the first name and surname together ─────────────────────────
  {
    id: 'initialsOrder', tier: 'name', whole: true,
    instances: () => [{ cmp: 'ascending' }, { cmp: 'descending' }],
    test: (e, p) => { const a = e.first.lower[0], b = e.last.lower[0]; return p.cmp === 'ascending' ? a < b : a > b; },
    text: p => `The killer’s initials are in ${p.cmp === 'ascending' ? '' : 'reverse '}alphabetical order: the first letter of their first name comes ${p.cmp === 'ascending' ? 'earlier' : 'later'} in the alphabet than the first letter of their surname. (Matching initials don’t count.)`,
    source: 'The Monogrammer',
    quote: p => `“I stitched the initials on a handkerchief. They ran ${p.cmp === 'ascending' ? 'A-ward to Z-ward, the natural way' : 'backwards, which I thought rather sinister'}.”`,
  },
  {
    id: 'initialsKind', tier: 'name', whole: true,
    instances: () => [{ kind: 'consonants' }, { kind: 'mixed' }],
    test: (e, p) => { const a = isVowel(e.first.lower[0]), b = isVowel(e.last.lower[0]); return p.kind === 'consonants' ? !a && !b : a !== b; },
    text: p => p.kind === 'consonants'
      ? 'Both of the killer’s initials are consonants (Y counts as a consonant).'
      : 'Exactly one of the killer’s initials is a vowel (A, E, I, O or U); the other is a consonant.',
    source: 'The Monogrammer',
    quote: p => p.kind === 'consonants' ? '“Two hard initials on the signet ring. No vowels at all.”' : '“One soft initial and one hard one, on the signet ring. A vowel and a consonant.”',
  },
  {
    id: 'initialsWord', tier: 'name', whole: true,
    instances: () => WORDS.flatMap(word => [{ word, has: true }, { word, has: false }]),
    test: (e, p) => { const w = p.word.toLowerCase(); return (w.includes(e.first.lower[0]) && w.includes(e.last.lower[0])) === p.has; },
    text: p => p.has
      ? `Both of the killer’s initials are letters of the word ${p.word} (${listLetters(uniqLetters(p.word))}).`
      : `The killer’s initials are not both letters of the word ${p.word} (${listLetters(uniqLetters(p.word))}) — at least one of them is missing from it.`,
    source: 'The Registrar',
    quote: p => p.has ? `“The ink blot on the ledger spelled ${p.word}, if you squinted. Both initials were in it.”` : `“The ink blot on the ledger spelled ${p.word}. The killer’s initials didn’t both fit.”`,
  },
  {
    id: 'mirrorLength', tier: 'name', whole: true,
    instances: () => [{ cmp: 'longer' }, { cmp: 'shorter' }, { cmp: 'same' }],
    test: (e, p) => p.cmp === 'longer' ? e.first.len > e.last.len : p.cmp === 'shorter' ? e.first.len < e.last.len : e.first.len === e.last.len,
    text: p => p.cmp === 'same' ? 'The killer’s first name and surname have exactly the same number of letters.' : `The killer’s first name is ${p.cmp} than their surname (count the letters).`,
    source: 'The Sign Painter',
    quote: p => p.cmp === 'same' ? '“I painted the name on a door in two lines, and the lines came out exactly even.”' : `“I painted the name on a door in two lines. The top line — the first name — came out ${p.cmp}.”`,
  },
  {
    id: 'mirrorShared', tier: 'name', whole: true,
    instances: () => [0, 1, 2, 3].map(k => ({ k })).concat([{ k: 4, atLeast: true }]),
    test: (e, p) => { const n = popcount(e.first.mask & e.last.mask); return p.atLeast ? n >= p.k : n === p.k; },
    text: p => p.k === 0 ? 'The killer’s first name and surname have no letters in common.'
      : `The killer’s first name and surname have ${p.atLeast ? `${NUM[p.k]} or more` : `exactly ${NUM[p.k]}`} different letter${p.k > 1 ? 's' : ''} in common (count each shared letter once, however often it appears).`,
    source: 'The Cryptographer',
    quote: () => '“I set the first name above the surname and struck out every letter they share. I remember what was left.”',
  },
  {
    id: 'mirrorOrder', tier: 'name', whole: true,
    instances: () => [{ surnameFirst: true }, { surnameFirst: false }],
    test: (e, p) => (e.last.lower < e.first.lower) === p.surnameFirst,
    text: p => p.surnameFirst
      ? 'In a dictionary, the killer’s surname would come before their first name (as Baker would come before Tom).'
      : 'In a dictionary, the killer’s first name would come before their surname (as Tom would come before Wilson).',
    source: 'The Lexicographer',
    quote: p => p.surnameFirst ? '“I file people under whichever of their names comes first in the alphabet. This one I filed under the surname.”' : '“I file people under whichever of their names comes first in the alphabet. This one I filed under the first name.”',
  },
  {
    id: 'mirrorLink', tier: 'name', whole: true,
    instances: () => [{ has: true }, { has: false }],
    test: (e, p) => e.last.lower.includes(e.first.lower[e.first.len - 1]) === p.has,
    text: p => `The last letter of the killer’s first name ${p.has ? 'appears somewhere in' : 'does not appear anywhere in'} their surname.`,
    source: 'The Calligrapher',
    quote: p => p.has ? '“I joined the first name to the surname with a single flourish — the same letter carried straight across.”' : '“I tried to join the two names with one flourish, but the letter at the end of the first name was nowhere in the second.”',
  },

  // ── engine 7: family groups ───────────────────────────────────────────────
  {
    id: 'familySize', tier: 'connection',
    instances: ctx => ctx?.book?.fullNames ? [2, 3, 4].flatMap(k => [{ k, cmp: 'exactly' }, { k, cmp: 'atLeast' }]).concat([{ k: 2, cmp: 'atMost' }]) : [],
    test: (e, p, ctx) => { const n = familySize(ctx.book, e); return p.cmp === 'exactly' ? n === p.k : p.cmp === 'atLeast' ? n >= p.k : n <= p.k; },
    text: p => `The killer is listed in a family group of ${p.cmp === 'exactly' ? 'exactly' : p.cmp === 'atLeast' ? 'at least' : 'at most'} ${NUM[p.k]}. (A family group is a run of consecutive entries sharing a surname; someone whose neighbours both have other surnames is a group of one.)`,
    source: 'The Boarding-House Keeper',
    quote: p => p.cmp === 'atMost' ? '“Never more than a couple of them, that lot. Small family.”' : `“They came as a party of ${p.cmp === 'atLeast' ? `${NUM[p.k]} or more` : NUM[p.k]}, all one name. I counted the coats.”`,
  },

  // ── engine 7: reasoning — names crossed with numbers ──────────────────────
  {
    id: 'lineVsLength', tier: 'reasoning',
    instances: () => ['first', 'last'].flatMap(part => [{ part, cmp: 'greater' }, { part, cmp: 'less' }]),
    test: (e, p) => p.cmp === 'greater' ? e.line > e[p.part].len : e.line < e[p.part].len,
    text: p => `The killer’s line number is ${p.cmp === 'greater' ? 'greater' : 'smaller'} than the number of letters in their ${PART_WORD[p.part]}.`,
    source: 'The Bank Clerk',
    quote: () => '“I count everything twice: the letters in a name, and the line it sits on. That one didn’t balance.”',
  },
  {
    id: 'parityMatch', tier: 'reasoning',
    instances: () => ['first', 'last'].flatMap(part => [{ part, same: true }, { part, same: false }]),
    test: (e, p) => ((e.line % 2) === (e[p.part].len % 2)) === p.same,
    text: p => p.same
      ? `The killer’s line number and the number of letters in their ${PART_WORD[p.part]} are either both odd or both even.`
      : `Of the killer’s line number and the number of letters in their ${PART_WORD[p.part]}, one is odd and the other even.`,
    source: 'The Croupier',
    quote: p => p.same ? '“Odd and odd, or even and even. The house always notices a matched pair.”' : '“One odd, one even. Rouge et noir. I never forget a split.”',
  },

  // ── engine 7: reasoning — two conditions joined ───────────────────────────
  ...['implies', 'xor', 'or', 'iff'].map(op => ({
    id: `compound_${op}`, tier: 'reasoning', sampled: true,
    sample: (rng, ctx, k, n) => {
      const out = [], ke = ctx.entries[k];
      for (let t = 0; t < n * 4 && out.length < n; t++) {
        const A = rng.pick(ATOMS), B = rng.pick(ATOMS);
        if (A.id === B.id || (!A.name && !B.name)) continue;
        const a = { id: A.id, ...A.make(rng) }, b = { id: B.id, ...B.make(rng) };
        const p = { a, b };
        if (COMPOUND[op](atom(a, ke, ctx), atom(b, ke, ctx))) out.push(p);
      }
      return out;
    },
    test: (e, p, ctx) => COMPOUND[op](atom(p.a, e, ctx), atom(p.b, e, ctx)),
    // Fast path for the search: combine the two conditions' cached bitmaps.
    bitsFor: (p, ctx) => {
      const A = atomBits(p.a, ctx), B = atomBits(p.b, ctx), f = COMPOUND[op], out = new Uint8Array(A.length);
      for (let i = 0; i < A.length; i++) out[i] = f(A[i] === 1, B[i] === 1) ? 1 : 0;
      return out;
    },
    text: p => COMPOUND_TEXT[op](say(p.a), say(p.b)),
    source: { implies: 'The Logician', xor: 'The Bookmaker', or: 'The Barrister', iff: 'The Twins’ Nanny' }[op],
    quote: () => ({
      implies: '“It follows, Inspector. It always follows. Take the first part as given and the second is inevitable.”',
      xor: '“I’d lay odds on one of those being true. Not both — I don’t take mug’s bets.”',
      or: '“One or the other, m’lud — and the defence won’t say which.”',
      iff: '“They’re like my twins, those two facts. Where one goes, the other goes; where one stays home, so does the other.”',
    })[op],
  })),
];

function popcount(x) { let c = 0; while (x) { x &= x - 1; c++; } return c; }

// ── helpers for the engine-7 families ────────────────────────────────────
const who = (ctx, i) => ctx.entries[i].name;
const partName = (ctx, p) => ctx.entries[p.at][p.part].name;
/** Does anyone else in e's chapter have this first name / surname? */
const chapterHas = (ctx, e, p) => occurrences(ctx.book, p.part, p.value).some(j => j !== e.i && ctx.entries[j].ci === e.ci);
const anchorCache = new WeakMap();
/** Indices of people whose full name appears exactly once, in register order. */
function uniqueAnchors(book) {
  let a = anchorCache.get(book);
  if (!a) { a = []; for (const [, ids] of bookIndex(book).byFull) if (ids.length === 1) a.push(ids[0]); a.sort((x, y) => x - y); anchorCache.set(book, a); }
  return a;
}
const lowerBound = (arr, x) => { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < x) lo = m + 1; else hi = m; } return lo; };

// Atoms: the simple conditions that compound clues join. `name` atoms are
// about the name; the rest about its place on the page (a compound always
// includes at least one name atom, so none can be struck by position alone).
const PW = { first: 'first name', last: 'surname' };
const ATOMS = [
  { id: 'start', name: true, kind: 'start', make: r => ({ part: r.pick(['first', 'last']), vowel: r.chance(0.5) }), test: (e, p) => isVowel(e[p.part].lower[0]) === p.vowel, say: p => `the killer’s ${PW[p.part]} begins with a ${p.vowel ? 'vowel' : 'consonant'}` },
  { id: 'end', name: true, kind: 'end', make: r => ({ part: r.pick(['first', 'last']), vowel: r.chance(0.5) }), test: (e, p) => isVowel(e[p.part].lower[e[p.part].len - 1]) === p.vowel, say: p => `the killer’s ${PW[p.part]} ends in a ${p.vowel ? 'vowel' : 'consonant'}` },
  { id: 'len', name: true, kind: 'len', make: r => { const part = r.pick(['first', 'last']); return { part, k: part === 'first' ? r.range(5, 7) : r.range(6, 8) }; }, test: (e, p) => e[p.part].len >= p.k, say: p => `the killer’s ${PW[p.part]} has ${NUM[p.k]} or more letters` },
  { id: 'has', name: true, kind: 'has', make: r => ({ part: r.pick(['first', 'last']), c: r.pick('aeinorlst'.split('')) }), test: (e, p) => e[p.part].lower.includes(p.c), say: p => `the killer’s ${PW[p.part]} contains the letter ${p.c.toUpperCase()}` },
  { id: 'dbl', name: true, kind: 'dbl', make: r => ({ part: r.pick(['first', 'last']) }), test: (e, p) => e[p.part].double, say: p => `the killer’s ${PW[p.part]} has a double letter (the same letter twice in a row)` },
  { id: 'half', name: true, kind: 'half', make: r => ({ part: r.pick(['first', 'last']) }), test: (e, p) => e[p.part].lower[0] < 'n', say: p => `the killer’s ${PW[p.part]} begins with a letter from A to M` },
  { id: 'longer', name: true, kind: 'longer', make: () => ({}), test: e => e.first.len > e.last.len, say: () => 'the killer’s first name is longer than their surname' },
  { id: 'odd', kind: 'odd', make: () => ({}), test: e => e.line % 2 === 1, say: () => 'the killer is on an odd-numbered line' },
  { id: 'top', kind: 'top', make: () => ({}), test: e => e.line <= 12, say: () => 'the killer is on one of lines 1 to 12' },
  { id: 'evenPage', kind: 'evenPage', make: () => ({}), test: e => e.page % 2 === 0, say: () => 'the killer’s page number is even' },
  { id: 'left', kind: 'left', make: () => ({}), test: e => e.col === 1, say: () => 'the killer is in the left-hand column of their page' },
];
const ATOM = Object.fromEntries(ATOMS.map(a => [a.id, a]));
const atom = (p, e, ctx) => ATOM[p.id].test(e, p, ctx);
const atomCache = new WeakMap();
/** One condition's verdict for every entry, cached per book. */
function atomBits(p, ctx) {
  let m = atomCache.get(ctx.book);
  if (!m) atomCache.set(ctx.book, m = new Map());
  const key = JSON.stringify(p);
  let bits = m.get(key);
  if (!bits) { bits = new Uint8Array(ctx.entries.length); for (const e of ctx.entries) bits[e.i] = atom(p, e, ctx) ? 1 : 0; m.set(key, bits); }
  return bits;
}
const say = p => ATOM[p.id].say(p);
const COMPOUND = { implies: (a, b) => !a || b, xor: (a, b) => a !== b, or: (a, b) => a || b, iff: (a, b) => a === b };
const COMPOUND_TEXT = {
  implies: (a, b) => `If ${a}, then ${b}. (So it clears only people for whom the first part is true and the second is not.)`,
  xor: (a, b) => `Exactly one of these is true of the killer, not both: (a) ${a}; (b) ${b}.`,
  or: (a, b) => `At least one of these is true of the killer, perhaps both: (a) ${a}; (b) ${b}.`,
  iff: (a, b) => `Either both of these are true of the killer, or neither is: (a) ${a}; (b) ${b}.`,
};

// ── clue types: at most one clue of each type per case ───────────────────
// `broad` types are always present; they set the difficulty. Families listed
// under a type are interchangeable ways of saying something about one subject.
export const TYPES = [
  // Engine 7 sections: stretches of the register, anchored to people in it.
  { id: 'span',         tier: 'record',     label: 'Between Two Names',       families: ['span'] },
  { id: 'landmark',     tier: 'record',     label: 'A Landmark Name',         families: ['landmark'] },
  { id: 'nearVictim',   tier: 'record',     label: 'Near the Victim',         families: ['victimSpan'] },
  { id: 'chapterCompany', tier: 'record',   label: 'The Chapter’s Company',   families: ['chapterCompany'] },
  // Before engine 7: simple structural gates, struck a page or column at a time. No longer dealt.
  { id: 'chapter',      tier: 'registry',   legacy: true, label: 'The Chapter',            families: ['chapterParity', 'chapterPrime', 'chapterMultiple', 'chapterRange', 'chapterSpelled', 'pageInChapter'] },
  { id: 'page',         tier: 'ledger',     legacy: true, label: 'The Page Number',        families: ['pagePrime', 'pageParity', 'pageMultiple', 'pageDigitSum', 'pageLastDigit', 'pageHasDigit', 'pageReversed'] },
  { id: 'column',       tier: 'placement',  legacy: true, label: 'The Column',             families: ['column'] },
  { id: 'line',         tier: 'placement',  legacy: true, label: 'The Line Number',        families: ['lineParity', 'lineHalf', 'lineMultiple', 'linePrime'] },
  { id: 'initial',      tier: 'name',       label: 'The Initial',             families: ['word', 'half', 'straight', 'window', 'victimInitial'] },
  { id: 'length',       tier: 'name',       label: 'Length',                  families: ['lengthEq', 'lengthCmp', 'lengthParity'] },
  { id: 'presence',     tier: 'name',       label: 'Letters Present',         families: ['contains', 'containsAny'] },
  { id: 'position',     tier: 'name',       label: 'Letter Positions',        families: ['secondVowel', 'thirdVowel', 'secondHalf'] },
  { id: 'ending',       tier: 'name',       label: 'The Last Letter',         families: ['endsVowel', 'lastHalf', 'endsIn'] },
  { id: 'vowels',       tier: 'name',       label: 'Vowels',                  families: ['vowelCount', 'balance'] },
  { id: 'repetition',   tier: 'name',       label: 'Repeated Letters',        families: ['repeat', 'double'] },
  { id: 'pairs',        tier: 'name',       label: 'Letter Pairs',            families: ['pair'] },
  { id: 'order',        tier: 'name',       label: 'Alphabetical Order',      families: ['firstVsLast', 'secondVsFirst'] },
  { id: 'runs',         tier: 'name',       label: 'Vowel & Consonant Runs',  families: ['vowelRun', 'consonantRun'] },
  { id: 'before',       tier: 'connection', label: 'The Name Before',         families: ['prevLength', 'prevLast'] },
  { id: 'after',        tier: 'connection', label: 'The Name After',          families: ['nextLast', 'nextLength'] },
  { id: 'lineMates',    tier: 'connection', label: 'The Same Line',           families: ['lineLength', 'lineLast', 'lineInitial'] },
  { id: 'neighbours',   tier: 'connection', label: 'Both Neighbours',         families: ['neighbourEnds', 'neighbourLength'] },
  { id: 'victimLetters', tier: 'connection', label: 'The Victim’s Letters',   families: ['victimShare'] },
  { id: 'victimLength', tier: 'connection', label: 'The Victim’s Length',     families: ['victimLength'] },
  { id: 'pageCompany',  tier: 'connection', label: 'The Top of the Page',     families: ['pageFirstSecond', 'pageFirstLength'] },
  { id: 'household',    tier: 'connection', label: 'The Family',              families: ['familyNeighbour', 'familyPosition'] },
  { id: 'namesakes',    tier: 'connection', label: 'Namesakes',               families: ['pageNamesake', 'columnNamesake'] },
  // Engine 7: more ways to read a name, its family, and reasoning puzzles.
  { id: 'initials',     tier: 'name',       label: 'The Initials',            families: ['initialsOrder', 'initialsKind', 'initialsWord'] },
  { id: 'mirror',       tier: 'name',       label: 'First Name & Surname',    families: ['mirrorLength', 'mirrorShared', 'mirrorOrder', 'mirrorLink'] },
  { id: 'familySize',   tier: 'connection', label: 'The Size of the Family',  families: ['familySize'] },
  { id: 'numbers',      tier: 'reasoning',  label: 'Names & Numbers',         families: ['lineVsLength', 'parityMatch'] },
  { id: 'ifThen',       tier: 'reasoning',  label: 'If… Then…',               families: ['compound_implies'] },
  { id: 'eitherOr',     tier: 'reasoning',  label: 'Either… Or…',             families: ['compound_xor', 'compound_or'] },
  { id: 'bothOrNeither', tier: 'reasoning', label: 'Both or Neither',         families: ['compound_iff'] },
];
export const TYPE = Object.fromEntries(TYPES.map(t => [t.id, t]));
export const TYPE_LABEL = Object.fromEntries(TYPES.map(t => [t.id, t.label]));
for (const t of TYPES) for (const fid of t.families) {
  const f = FAMILIES.find(x => x.id === fid);
  if (!f) throw new Error(`Type ${t.id} lists unknown family ${fid}`);
  if (f.type) throw new Error(`Family ${fid} is in two types`);
  f.type = t.id;
  f.tier = t.tier;
  if (t.legacy) f.retired = true;
}
for (const f of FAMILIES) if (!f.type && !f.legacy) throw new Error(`Family ${f.id} has no type`);
// Families kept only so old cases still evaluate: the two-column `beside`
// families (no type at all) and, since engine 7, the structural gates.
export const ACTIVE_FAMILIES = FAMILIES.filter(f => !f.legacy);
export const DEALT_FAMILIES = ACTIVE_FAMILIES.filter(f => !f.retired);
export const DEALT_TYPES = TYPES.filter(t => !t.legacy);

// ── full names ────────────────────────────────────────────────────────────
// In a full-name register, every clue about "the name" is asked of either the
// first name or the surname. The family's own test runs on that part's stats.
const PART_WORD = { first: 'first name', last: 'surname' };
const partText = (s, part) => s
  .replace(/The killer’s initial/g, `The first letter of the killer’s ${PART_WORD[part]}`)
  .replace(/The killer’s name/g, `The killer’s ${PART_WORD[part]}`)
  .replace(/the killer’s name/g, `the killer’s ${PART_WORD[part]}`);
for (const f of ACTIVE_FAMILIES) {
  if (f.tier !== 'name' || f.whole) continue;
  const { instances, test, text } = f;
  f.instances = ctx => { const base = instances(ctx); return ctx?.book?.fullNames ? base.flatMap(p => [{ ...p, part: 'first' }, { ...p, part: 'last' }]) : base; };
  f.test = (e, p, ctx) => test(p.part === 'last' ? e.last : p.part === 'first' ? e.first : e, p, ctx);
  f.text = (p, ctx) => p.part ? partText(text(p, ctx), p.part) : text(p, ctx);
}

// Connection clues compare first names; in a full-name register they say so.
const VNAME = ctx => (ctx.victim.first?.name || ctx.victim.name).toUpperCase();
const FULL_TEXT = {
  prevLength: p => `The person listed immediately before the killer in the Register has a first name with ${p.cmp === 'same' ? 'exactly as many letters as' : p.cmp === 'longer' ? 'more letters than' : 'fewer letters than'} the killer’s first name.`,
  nextLength: p => `The person listed immediately after the killer in the Register has a first name with ${p.cmp === 'same' ? 'exactly as many letters as' : p.cmp === 'longer' ? 'more letters than' : 'fewer letters than'} the killer’s first name.`,
  prevLast: p => `The first name of the person listed immediately before the killer in the Register ends in ${p.same ? 'the same letter as' : 'a different letter from'} the killer’s first name.`,
  nextLast: p => `The first name of the person listed immediately after the killer in the Register ends in ${p.same ? 'the same letter as' : 'a different letter from'} the killer’s first name.`,
  neighbourEnds: p => `The first names of the people listed immediately before and immediately after the killer in the Register both end in a ${p.vowel ? 'vowel (A, E, I, O or U)' : 'consonant (Y counts as a consonant)'}.`,
  neighbourLength: p => `The people listed immediately before and immediately after the killer in the Register both have ${p.cmp} first names than the killer.`,
  lineLength: p => p.cmp === 'neither'
    ? 'Among the first names on the killer’s line (same page, all columns), the killer’s is neither strictly the longest nor strictly the shortest. (If no other name shares the line, this cannot be the killer.)'
    : `The killer’s first name is ${p.cmp === 'longest' ? 'longer' : 'shorter'} than every other first name on the same line (same page, all columns). (If no other name shares the line, this cannot be the killer.)`,
  lineLast: p => p.shared
    ? 'At least one other person on the killer’s line (same page, any column) has a first name ending in the same letter as the killer’s first name.'
    : 'No other person on the killer’s line (same page, any column) has a first name ending in the same letter as the killer’s first name. (If no other name shares the line, this cannot be the killer.)',
  lineInitial: p => p.shared
    ? 'At least one other person on the killer’s line (same page, any column) has a first name beginning with the same letter as the killer’s first name.'
    : 'No other person on the killer’s line (same page, any column) has a first name beginning with the same letter as the killer’s first name. (If no other name shares the line, this cannot be the killer.)',
  pageFirstSecond: p => `The second letter of the killer’s first name is ${p.same ? 'the same as' : 'different from'} the second letter of the first name of the person listed first on its page (top of the left-hand column).${p.same ? ' (If the killer is that person, this is true.)' : ' (If the killer is that person, this cannot be true.)'}`,
  pageFirstLength: p => `The killer’s first name is ${p.cmp} than the first name of the person listed first on its page (top of the left-hand column). (If the killer is that person, this cannot be true.)`,
  victimShare: (p, ctx) => p.k === 0
    ? `The killer’s first name has no letters in common with the victim’s first name, ${VNAME(ctx)}.`
    : `The killer’s first name shares exactly ${NUM[p.k]} different letter${p.k > 1 ? 's' : ''} with the victim’s first name, ${VNAME(ctx)} (count each shared letter once, however often it appears).`,
  victimLength: (p, ctx) => `The killer’s first name is ${p.cmp === 'same' ? 'exactly as long as' : `${p.cmp} than`} the victim’s first name, ${VNAME(ctx)} (${NUM[ctx.victim.len] || ctx.victim.len} letters).`,
};

export const FAMILY = Object.fromEntries(FAMILIES.map(f => [f.id, f]));

/** Display label for a clue — its type, falling back to tier for old cases. */
export const clueLabel = r => r.typeLabel || TYPE_LABEL[FAMILY[r.family]?.type] || TIER_LABEL[r.tier];

export function testRule(rule, e, ctx) { return FAMILY[rule.family].test(e, rule.params, ctx); }

export function describeRule(rule, ctx) {
  const f = FAMILY[rule.family];
  const word = ctx.registerWord || 'Register';
  const say = s => s.replace(/\bRegister\b/g, word).replace(/\bregister\b/g, word.toLowerCase());
  const text = ctx.book?.fullNames && FULL_TEXT[f.id] ? FULL_TEXT[f.id](rule.params, ctx) : f.text(rule.params, ctx);
  return { text: say(text), source: say(f.source), quote: say(f.quote(rule.params, ctx)), type: f.type, typeLabel: TYPE_LABEL[f.type] };
}

export const readingGuide = ({ word = 'Register', fullNames = false, alphabetical = false } = {}) => [
  `Names run down each column in turn, from left to right, then on to the next page. That is the order of the ${word} — “before”, “after” and “between” follow it, across pages and chapters.`,
  alphabetical ? 'Names are in alphabetical order, in chapters by initial letter.' : `The ${word} is not in alphabetical order. To look someone up, use Find: it lists people in ${word} order.`,
  'A name’s page is the number printed at the foot of its page. Its line is the small number printed beside it; names on the same line of a page share a line number.',
  ...(fullNames ? [
    'Each entry is a first name and a surname, and each clue says which it means. Names repeat, as they do in real records — every entry is a different person.',
    'Families are entered together: a family group is a run of consecutive entries sharing a surname (a lone entry is a group of one).',
    'Accented letters count as plain letters (É is E, Ñ is N). Apostrophes and hyphens are ignored when counting or comparing letters.',
  ] : []),
  'Vowels are A, E, I, O and U. Y is always a consonant.',
  'Capital and small letters count as the same letter.',
  `The victim is listed in the ${word} like everyone else (marked †), but is not a suspect.`,
];
export const READING_GUIDE = readingGuide();
