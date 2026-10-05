import { layoutCase, toRoman } from '../engine/book.js';
import { unseal } from '../engine/generator.js';
import { FAMILY } from '../engine/rules.js';
import { registerWord } from '../engine/story.js';

// Page geometry, in CSS px at 96/in — exactly US Letter.
export const PAGE_W = 816, PAGE_H = 1056;

/** Everything the reader needs about one case: layout, front matter, solution. */
export function buildModel(caseData) {
  const book = layoutCase(caseData);
  const victim = book.entries[caseData.victim];
  const ctx = { entries: book.entries, book, victim, registerWord: registerWord(caseData.story) };
  const mode = caseData.mode || 'cold';
  // The Inquiry: for each name, the first witness (in order) whose evidence clears it.
  let firstFail = null;
  if (mode === 'inquiry') {
    firstFail = new Uint8Array(book.entries.length).fill(255);
    for (const e of book.entries) {
      for (let k = 0; k < caseData.rules.length; k++) {
        const r = caseData.rules[k];
        if (!FAMILY[r.family].test(e, r.params, ctx)) { firstFail[e.i] = k; break; }
      }
    }
  }
  const front = [{ kind: 'title' }, { kind: 'case' }];
  const ev = paginateEvidence(caseData.rules);
  ev.forEach((rules, part) => front.push({ kind: 'evidence', rules, part, parts: ev.length, offset: ev.slice(0, part).flat().length }));
  front.push({ kind: 'contents' });
  // Page 1 of the Register must fall on a right-hand page, as in any book.
  if (front.length % 2 === 1) front.push({ kind: 'blank' });
  const seq = [
    ...front.map((f, k) => ({ ...f, folio: toRoman(k + 1) })),
    ...book.pages.map(p => ({ kind: 'register', page: p, folio: String(p.page) })),
  ];
  return {
    caseData, book, victim, ctx, seq, mode, firstFail,
    word: ctx.registerWord,
    frontCount: front.length,
    killer: () => book.entries[unseal(caseData.solution)],
    seqOfPage: n => front.length + n - 1,
    seqOfEntry: i => front.length + book.entries[i].page - 1,
    clears: (ruleIdx, i) => !FAMILY[caseData.rules[ruleIdx].family].test(book.entries[i], caseData.rules[ruleIdx].params, ctx),
    firstFailingRule: i => caseData.rules.findIndex(r => !FAMILY[r.family].test(book.entries[i], r.params, ctx)),
  };
}

// Pack clues onto evidence pages using conservative height estimates, so the
// printed page and the on-screen page always hold the same clues.
function paginateEvidence(rules) {
  // Calibrated against the rendered page: clues start ~242px down on the first
  // evidence page (~160px on later ones) and must end above ~985px.
  const budgetFirst = 985 - 250;
  const budgetNext = 985 - 165;
  const est = r => 48 + Math.ceil(r.quote.length / 86) * 23 + Math.ceil(r.text.length / 66) * 26;
  const pages = [[]];
  let used = 0;
  for (const r of rules) {
    const hgt = est(r);
    const budget = pages.length === 1 ? budgetFirst : budgetNext;
    if (used + hgt > budget && pages[pages.length - 1].length) { pages.push([]); used = 0; }
    pages[pages.length - 1].push(r);
    used += hgt;
  }
  return pages;
}

export const ROMAN_UP = n => toRoman(n).toUpperCase();
