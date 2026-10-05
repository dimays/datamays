import { esc, fmt, h } from './util.js';
import { ROMAN_UP } from './model.js';
import { DIFFICULTIES, MODES } from '../engine/generator.js';
import { prologue, epilogue, shortTitle, registerWord, peopleWord } from '../engine/story.js';
import { readingGuide, clueLabel } from '../engine/rules.js';
import { thousandsWord } from '../engine/book.js';

const ORDINAL_WORDS = ['First', 'Second', 'Third', 'Fourth', 'Fifth', 'Sixth', 'Seventh', 'Eighth', 'Ninth', 'Tenth', 'Eleventh', 'Twelfth', 'Thirteenth', 'Fourteenth', 'Fifteenth', 'Sixteenth', 'Seventeenth', 'Eighteenth', 'Nineteenth', 'Twentieth', 'Twenty-First', 'Twenty-Second', 'Twenty-Third', 'Twenty-Fourth', 'Twenty-Fifth', 'Twenty-Sixth'];

/**
 * Render one page of the book. Used verbatim for the screen and for print.
 * opts: { side: 'recto'|'verso', marks, solved, forPrint, revealed, compact }
 * compact: the phone layout, which adds a heading to each column.
 */
export function renderPage(model, seqIdx, opts = {}) {
  const item = model.seq[seqIdx];
  const side = opts.side || (seqIdx % 2 === 0 ? 'recto' : 'verso');
  let inner = '';
  switch (item.kind) {
    case 'title': inner = titlePage(model); break;
    case 'case': inner = casePage(model); break;
    case 'evidence': inner = evidencePage(model, item, opts); break;
    case 'contents': inner = contentsPage(model); break;
    case 'blank': inner = '<div class="blank-note">This page intentionally left blank.</div>'; break;
    case 'register': inner = registerPage(model, item.page, opts); break;
  }
  const folio = item.kind === 'title' || item.kind === 'blank' ? '' : `<footer class="folio">${item.folio}</footer>`;
  const el = h(`<article class="page ${item.kind} ${side}" data-seq="${seqIdx}">${inner}${folio}</article>`);
  return el;
}

function titlePage(model) {
  const c = model.caseData, st = c.story;
  const t = st.titles || { top: 'The', big: st.town, bottom: 'Register' };
  const modeLabel = c.mode ? ` · ${MODES[c.mode].label}` : '';
  const blurb = st.premise
    ? `Being a complete record of ${st.premise}, together with the evidence gathered by ${st.inspector} in the matter of the death of ${st.victim}.`
    : `Being a complete record of every resident of ${st.town}${model.book.style === 'alpha' ? ', entered alphabetically' : ''}, together with the evidence gathered by ${st.inspector} in the matter of the death of ${st.victim}.`;
  return `<div class="title-wrap">
    <div class="tp-kicker">Case No. ${esc(c.code)}${modeLabel} · ${esc(DIFFICULTIES[c.difficulty].label)}</div>
    <div class="tp-rule"></div>
    <h1 class="tp-title"><small>${esc(t.top)}</small><span>${esc(t.big)}</span>${st.titles ? `<small>${esc(t.bottom)}</small>` : esc(t.bottom)}</h1>
    <div class="tp-sub">A Murder in ${thousandsWord(model.book.entries.length)} Names</div>
    <div class="tp-orn">❦</div>
    <p class="tp-blurb">${esc(blurb)}</p>
    <div class="tp-foot">${c.rules.length} ${c.mode === 'inquiry' ? 'witnesses' : 'clues'} · ${fmt(model.book.entries.length)} names · ${model.book.pageCount} pages</div>
  </div>`;
}

function casePage(model) {
  const c = model.caseData;
  const paras = prologue(c.story, model.book, model.victim, c.rules.length, model.mode);
  return `<h2 class="fm-heading"><span class="fm-kicker">The Case</span>The Death of ${esc(c.story.victim)}</h2>
    <div class="prose">${paras.map((p, i) => `<p${i === 0 ? ' class="dropcap"' : ''}>${esc(p)}</p>`).join('')}</div>
    <div class="guide"><h3>How to read the ${esc(model.word)}</h3><ul>${readingGuide({ word: model.word, fullNames: !!model.book.fullNames, alphabetical: model.book.style === 'alpha' }).map(g => `<li>${esc(g)}</li>`).join('')}</ul></div>`;
}

function evidencePage(model, item, opts = {}) {
  const inquiry = model.mode === 'inquiry';
  const revealed = inquiry ? (opts.revealed ?? model.caseData.rules.length) : Infinity;
  const head = item.part === 0
    ? `<h2 class="fm-heading"><span class="fm-kicker">${inquiry ? 'The Witnesses' : 'The Evidence'}</span>What ${esc(model.caseData.story.inspector)} Knows</h2>
       <p class="ev-intro">${inquiry ? 'Each witness’s statement is true of the killer. Witnesses come forward one at a time, once every name the evidence so far rules out has been struck.' : 'Every statement below is true of the killer. Any name for which even one statement is false is innocent — strike it out.'}</p>`
    : `<h2 class="fm-heading small"><span class="fm-kicker">${inquiry ? 'The Witnesses' : 'The Evidence'}, continued</span></h2>`;
  const clues = item.rules.map((r, k) => {
    const n = item.offset + k + 1;
    if (n > revealed) {
      return `<section class="clue sealed">
        <div class="clue-num">${ROMAN_UP(n)}</div>
        <div class="clue-body"><div class="clue-src">A witness yet to come forward</div><p class="clue-quote">Sealed. This statement will be opened once every name the earlier evidence rules out has been struck.</p></div>
      </section>`;
    }
    return `<section class="clue" data-tier="${r.tier}">
      <div class="clue-num">${ROMAN_UP(n)}</div>
      <div class="clue-body">
        <div class="clue-src">${esc(r.source)} <span>· ${esc(clueLabel(r))}</span></div>
        <p class="clue-quote">${esc(r.quote)}</p>
        <p class="clue-text">${esc(r.text)}</p>
      </div>
    </section>`;
  }).join('');
  return `${head}<div class="clues">${clues}</div>`;
}

function contentsPage(model) {
  const fm = model.seq.slice(0, model.frontCount).map((s, k) => ({ s, k })).filter(({ s }) => s.kind === 'case' || (s.kind === 'evidence' && s.part === 0));
  const label = s => s.kind === 'case' ? 'The Case' : model.mode === 'inquiry' ? 'The Witnesses' : 'The Evidence';
  const row = (name, pg, seq, cls = '') => `<li class="${cls}" data-goto="${seq}"><span class="toc-name">${name}</span><span class="toc-dots"></span><span class="toc-pg">${pg}</span></li>`;
  const chapters = model.book.chapters.map(ch =>
    model.book.style === 'novel'
      ? row(`${ch.title} <em>· ${fmt(ch.count)} names</em>`, ch.firstPage, model.seqOfPage(ch.firstPage), 'toc-ch novel')
      : row(`<b>${ch.letter}</b><em>Chapter ${ROMAN_UP(ch.ci + 1)} · ${fmt(ch.count)} names</em>`, ch.firstPage, model.seqOfPage(ch.firstPage), 'toc-ch')).join('');
  return `<h2 class="fm-heading small"><span class="fm-kicker">Contents</span></h2>
    <ol class="toc">${fm.map(({ s, k }) => row(label(s), s.folio, k)).join('')}</ol>
    <h3 class="toc-sub">The Register</h3>
    <ol class="toc chapters${model.book.chapters.length > 26 ? ' two' : ''}">${chapters}</ol>`;
}


function registerPage(model, page, opts) {
  const { book, caseData } = model;
  const ch = book.chapters[page.ci];
  const novel = book.style === 'novel';
  const killerI = opts.solved ? model.killer().i : -1;
  const col = ids => ids.map(i => {
    const e = book.entries[i];
    const pen = opts.marks ? opts.marks[i] : 0;
    const cls = ['nm'];
    let style = '';
    if (i === caseData.victim) cls.push('victim');
    else if (pen) { cls.push('m'); style = ` data-pen="${pen}"`; }
    if (i === killerI) cls.push('culprit');
    return `<li class="${cls.join(' ')}" data-i="${i}"${style}><span class="ln">${e.line}</span><span class="tx">${e.name}${i === caseData.victim ? '<i class="dagger">†</i>' : ''}</span></li>`;
  }).join('');
  const town = esc(caseData.story.town || '');
  let header, opener = '';
  if (novel) {
    // Running heads like a novel: book title on the left, chapter on the right.
    const st = caseData.story, people = peopleWord(st), word = registerWord(st);
    header = `<header class="rh novel ${page.opener ? 'hidden' : ''}"><span class="gw">${esc(shortTitle(st))}</span><span class="rh-mid">❦</span><span class="gw r">${ch.title}</span></header>`;
    if (page.opener) {
      const last = page.ci === book.chapters.length - 1;
      const which = page.ci === 0 ? `the first ${fmt(ch.count)} ${people}` : last ? `the last ${fmt(ch.count)} ${people}` : `${fmt(ch.count)} more ${people}`;
      opener = `<div class="opener novel">
        <div class="ch-kicker">Chapter</div>
        <div class="ch-word">${ch.word}</div>
        <div class="ch-orn">❦</div>
        <p class="ch-blurb">In which ${which}${st.titles ? '' : ` of ${town}`} are entered into the ${esc(word)}.</p>
      </div>`;
    }
  } else {
    // Legacy alphabetical books: dictionary-style guide words.
    const first = book.entries[page.cols[0][0]].name;
    const lastCol = page.cols[1].length ? page.cols[1] : page.cols[0];
    const last = book.entries[lastCol[lastCol.length - 1]].name;
    header = `<header class="rh"><span class="gw">${first}</span><span class="rh-mid">${ch.letter}</span><span class="gw r">${last}</span></header>`;
    if (page.opener) opener = `<div class="opener">
      <div class="ch-kicker">Chapter the ${ORDINAL_WORDS[page.ci]}</div>
      <div class="ch-letter">${ch.letter}</div>
      <p class="ch-blurb">In which ${fmt(ch.count)} residents of ${town} whose names begin with ${ch.letter} are entered into the Register.</p>
    </div>`;
  }
  return `${header}
    ${opener}
    <div class="cols c${page.cols.length}${book.fullNames ? ' full' : ''}" style="--rows:${page.rows}">
      ${page.cols.map((c, k) => opts.compact
        // Phones read one column at a time, each under a heading with its own strike buttons.
        ? `<section class="col-wrap"><div class="col-head" data-col="${k}"><span class="col-name">${columnName(k, page.cols.length)} column</span><span class="col-count"></span><span class="pa-pair"><button class="btn small" data-act="mark-col" data-page="${page.page}" data-col="${k}"><i class="pen-dot"></i>Strike</button><button class="btn ghost small" data-act="clear-col" data-page="${page.page}" data-col="${k}">Clear</button></span></div><ol class="col">${col(c)}</ol></section>`
        : `<ol class="col">${col(c)}</ol>`).join('')}
    </div>`;
}

export const columnName = (k, n) => (n === 3 ? ['Left', 'Middle', 'Right'] : ['Left', 'Right'])[k];

/** The solution page shown (and printable) once the case is closed. */
export function renderSolution(model) {
  const k = model.killer();
  return epilogue(model.caseData.story, k, model.book.entries.length);
}
