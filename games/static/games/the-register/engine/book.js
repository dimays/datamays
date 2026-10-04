// Lays the register out into fixed pages. The same layout drives the screen,
// the clues and the printout, so "page 147, line 9" means one thing everywhere.

export const ROWS_FULL = 25;     // lines per column on an ordinary page
export const ROWS_OPENER = 15;   // lines per column on a chapter's opening page
export const NOVEL_COLS = 3;     // columns per page in the novel layout
export const CHAPTER_PAGES = [10, 30];  // allowed chapter length, in pages

const ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen'];
const TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty'];
/** 7 → "Seven", 21 → "Twenty-One" — exactly as the chapter headings print it. */
export const numberWord = n => n < 20 ? ONES[n] : TENS[Math.floor(n / 10)] + (n % 10 ? '-' + ONES[n % 10] : '');

/** Lay out either kind of case: legacy alphabetical, or the novel layout. */
export function layoutCase(caseData) {
  return caseData.layout === 'novel'
    ? layoutNovel(caseData.names, caseData.chapterPages, { fullNames: !!caseData.fullNames })
    : layoutBook(caseData.chapters);
}

/**
 * Novel layout: names in the given (shuffled) reading order, three columns,
 * chapters of `chapterPages[c]` pages each. Every chapter but the last fills
 * its pages exactly; the book's final page splits its names evenly.
 */
export function layoutNovel(names, chapterPages, { fullNames = false } = {}) {
  const entries = [], pages = [], chapterInfo = [];
  let k = 0, pageNo = 0;
  chapterPages.forEach((count, ci) => {
    const firstPage = pageNo + 1, start = k;
    for (let pg = 0; pg < count && k < names.length; pg++) {
      const opener = pg === 0;
      const rows = opener ? ROWS_OPENER : ROWS_FULL;
      const onPage = Math.min(names.length - k, rows * NOVEL_COLS);
      const perCol = onPage === rows * NOVEL_COLS ? [rows, rows, rows] : balance(onPage, NOVEL_COLS);
      pageNo++;
      const page = { page: pageNo, ci, opener, rows, cols: perCol.map(() => []) };
      let s = 0;
      perCol.forEach((n, c) => {
        for (let line = 1; line <= n; line++, s++) {
          const i = entries.length;
          entries.push({ i, name: names[k + s], ci, page: pageNo, col: c + 1, line });
          page.cols[c].push(i);
        }
      });
      pages.push(page);
      k += onPage;
    }
    chapterInfo.push({ ci, label: String(ci + 1), title: `Chapter ${numberWord(ci + 1)}`, word: numberWord(ci + 1), firstPage, lastPage: pageNo, count: k - start });
  });
  for (const e of entries) decorate(e);
  return { entries, pages, chapters: chapterInfo, pageCount: pageNo, cols: NOVEL_COLS, style: 'novel', fullNames };
}

const balance = (n, cols) => {
  const out = [];
  for (let c = 0; c < cols; c++) { const v = Math.ceil(n / (cols - c)); out.push(v); n -= v; }
  return out;
};

/** Split 26,000 names into chapters of 10–30 pages (mostly 12–26), novel-style. */
export function planChapters(rng, total) {
  const full = ROWS_FULL * NOVEL_COLS, open = ROWS_OPENER * NOVEL_COLS;
  const cap = p => open + (p - 1) * full;
  const pagesFor = n => 1 + Math.ceil(Math.max(0, n - open) / full);
  const plan = [];
  let left = total;
  while (left > 0) {
    const p = rng.range(12, 26);
    if (left <= cap(p)) {
      const need = pagesFor(left);
      if (need >= CHAPTER_PAGES[0] || !plan.length) plan.push(need);
      else {
        // Too short for a chapter: fold it into the previous one, or split the two evenly.
        const merged = plan.pop();
        const namesInBoth = cap(merged) + left;
        const both = pagesFor(namesInBoth) + 1; // two openers instead of one
        if (pagesFor(namesInBoth) <= CHAPTER_PAGES[1]) plan.push(pagesFor(namesInBoth));
        else { const a = Math.ceil(both / 2); plan.push(a, pagesFor(namesInBoth - cap(a))); }
      }
      left = 0;
    } else { plan.push(p); left -= cap(p); }
  }
  return plan;
}

const VOWEL = c => c === 'a' || c === 'e' || c === 'i' || c === 'o' || c === 'u';

export function layoutBook(chapters) {
  const entries = [];
  const pages = [];
  const chapterInfo = [];
  let pageNo = 0;
  chapters.forEach((names, ci) => {
    const firstPage = pageNo + 1;
    let k = 0;
    let opener = true;
    while (k < names.length) {
      const rows = opener ? ROWS_OPENER : ROWS_FULL;
      const remaining = names.length - k;
      const onPage = Math.min(remaining, rows * 2);
      // A chapter's final page splits its names evenly between the columns.
      const left = onPage === rows * 2 ? rows : Math.ceil(onPage / 2);
      pageNo++;
      const page = { page: pageNo, ci, opener, rows, cols: [[], []] };
      for (let s = 0; s < onPage; s++) {
        const col = s < left ? 0 : 1;
        const line = col === 0 ? s + 1 : s - left + 1;
        const i = entries.length;
        entries.push({ i, name: names[k + s], ci, page: pageNo, col: col + 1, line });
        page.cols[col].push(i);
      }
      pages.push(page);
      k += onPage;
      opener = false;
    }
    const letter = String.fromCharCode(65 + ci);
    chapterInfo.push({ ci, letter, label: letter, title: `Chapter ${letter}`, firstPage, lastPage: pageNo, count: names.length });
  });
  for (const e of entries) decorate(e);
  return { entries, pages, chapters: chapterInfo, pageCount: pageNo, cols: 2, style: 'alpha' };
}

// Letters only, accents folded (É → e), apostrophes/hyphens/spaces dropped.
export const letters = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z]/g, '');

function stats(part) {
  const n = letters(part);
  let vowels = 0, mask = 0, repeat = false, dbl = false;
  for (let j = 0; j < n.length; j++) {
    const c = n[j];
    if (VOWEL(c)) vowels++;
    const bit = 1 << (c.charCodeAt(0) - 97);
    if (mask & bit) repeat = true;
    mask |= bit;
    if (j && n[j - 1] === c) dbl = true;
  }
  return { name: part, lower: n, len: n.length, vowels, consonants: n.length - vowels, mask, repeat, double: dbl };
}

// Every entry carries stats for its first name and surname; the top-level
// fields mirror the first name (legacy one-word books: the whole name).
function decorate(e) {
  const sp = e.name.indexOf(' ');
  const first = stats(sp < 0 ? e.name : e.name.slice(0, sp));
  e.first = first;
  e.last = sp < 0 ? first : stats(e.name.slice(sp + 1));
  e.full = sp < 0 ? first : stats(e.name);
  const { name, ...top } = first;
  Object.assign(e, top);
}

export const isVowel = VOWEL;

/** The other names printed on the same line of the same page. */
export function lineMates(book, e) {
  const p = book.pages[e.page - 1];
  const out = [];
  p.cols.forEach((col, c) => { if (c !== e.col - 1 && col[e.line - 1] !== undefined) out.push(book.entries[col[e.line - 1]]); });
  return out;
}

export function beside(book, e) {
  const p = book.pages[e.page - 1];
  const other = p.cols[e.col === 1 ? 1 : 0];
  const j = other[e.line - 1];
  return j === undefined ? null : book.entries[j];
}

export const toRoman = n => {
  const map = [[10, 'x'], [9, 'ix'], [5, 'v'], [4, 'iv'], [1, 'i']];
  let s = '';
  for (const [v, r] of map) while (n >= v) { s += r; n -= v; }
  return s;
};
