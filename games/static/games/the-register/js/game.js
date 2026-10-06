import { $, $$, h, esc, fmt, debounce, bytesToB64, b64ToBytes, duration, toast, modal } from './util.js';
import { api, IN_BROWSER } from './api.js';
import { HUB, track, scoreFor, postScore, pending, signInUrl } from './hub.js';
import { buildModel, PAGE_W, PAGE_H, ROMAN_UP } from './model.js';
import { renderPage, renderSolution, columnName } from './pages.js';
import { PALETTE, PENCIL, hexOf, penCursor, penStyles, defaultPenColors } from './pens.js';
import { openPrintDialog } from './print.js';
import { DIFFICULTIES } from '../engine/generator.js';
import { clueLabel } from '../engine/rules.js';
import { letters } from '../engine/book.js';
import { prologue } from '../engine/story.js';

const UNDO_LIMIT = 300;
// Phones (and short landscape windows) get the compact layout: one reflowed
// page at a time, tap to strike, clues in a sheet. Everything else is shared.
const COMPACT = matchMedia('(max-width: 720px), (max-height: 520px) and (max-width: 1000px)');
const LONG_PRESS_MS = 500;
const ALIBIS = ['at the Drowned Bell playing dominoes', 'singing in the choir at evensong', 'stuck on the last ferry across the estuary', 'asleep in the waiting room at the station', 'at the picture house, in the front row', 'helping deliver a calf at Fenwick’s farm', 'in the cells, as it happens, for unpaid parking', 'at a séance on Pilgrim Street, holding hands with six witnesses'];

/** The line under a solved case once it's on the leaderboard. */
const postedNote = (p, url, of) => `<p class="posted-note">On the leaderboard: <b>${esc(p.time)}</b>${p.rank ? `, #${p.rank} today${of ? ` of ${of}` : ''}` : ''} · ${p.points} points${url ? ` · <a href="${esc(url)}">See the leaderboard</a>` : ''}</p>`;

export class Game {
  constructor(root, { game, caseData, onExit }) {
    this.root = root;
    this.g = game;
    this.onExit = onExit;
    // Save versioning: which server version this window built on, and who we are.
    this.baseUpdatedAt = game.updatedAt;
    this.writer = Math.random().toString(36).slice(2, 10);
    this.model = buildModel(caseData);
    this.rules = caseData.rules;
    // The Inquiry: witnesses are heard one at a time.
    this.inquiry = this.model.mode === 'inquiry';
    if (this.inquiry) this.g.revealed = Math.max(1, Math.min(this.rules.length, this.g.revealed || 1));
    const N = this.model.book.entries.length;
    this.marks = b64ToBytes(game.marks, N);
    this.g.penColors = { ...defaultPenColors(this.rules.length), ...(game.penColors || {}) };
    this.g.view = { mode: 'spread', strike: false, sidebar: true, tab: 'evidence', ...(game.view || {}) };
    if (!['evidence', 'case'].includes(this.g.view.tab)) this.g.view.tab = 'evidence';
    this.g.pos ??= 0;
    this.g.activePen ??= 1;
    this.g.hints ??= 0;
    this.g.accusations ??= [];
    this.g.timePlayed ??= 0;
    this.undoStack = [];
    this.redoStack = [];
    this.nodes = new Map();
    this.flagged = new Set();
    this.anchor = null;
    this.recount();
    this.save = debounce(() => this.persist(), 600);
    this.cleanup = [];
  }

  // ── setup ────────────────────────────────────────────────────────────────
  mount() {
    const c = this.model.caseData;
    this.root.innerHTML = '';
    this.root.append(h(`<div class="game">
      <header class="topbar">
        <button class="btn ghost" data-act="home" title="Back to Case Files">‹ <span class="d-only">Cases</span></button>
        <div class="tb-title"><span class="tb-name">${esc(c.title)}</span><span class="pill">${DIFFICULTIES[c.difficulty].label}</span><span class="save-state" title="Progress saves automatically"></span></div>
        <div class="tb-count"><span class="tb-num"></span><span class="tb-lbl">suspects remain</span></div>
        <div class="tb-actions">
          <button class="btn ghost icon" data-act="find" title="Find a name (/)" aria-label="Find a name">⌕ <span>Find</span></button>
          <button class="btn ghost icon m-only" data-act="undo" title="Undo" aria-label="Undo">↶</button>
          <button class="btn ghost d-only" data-act="mark-pages" title="Strike names by page, column and line (P)">Strike by position…</button>
          <button class="btn ghost d-only" data-act="sergeant" title="Ask the Sergeant for a hint">Sergeant</button>
          <button class="btn ghost d-only" data-act="print" title="Print the book">Print</button>
          <button class="btn ghost icon d-only" data-act="help" title="How to play (?)">?</button>
          <button class="btn ghost icon m-only" data-act="more" aria-label="More">⋯</button>
          <button class="btn primary" data-act="accuse">Accuse…</button>
        </div>
      </header>
      <button class="clue-strip m-only" data-act="sheet" aria-label="Show every clue"><i class="cs-bar"></i><span class="cs-body"><span class="cs-text"></span><span class="cs-next"></span></span><span class="cs-more">Clues ▾</span></button>
      <div class="desk">
        <aside class="casebook"></aside>
        <section class="stage">
          <div id="toast-slot" class="msg-slot" role="status" aria-live="polite"></div>
          <div class="scroller"><div class="book-wrap"><div class="book"></div></div></div>
          <div class="page-actions" aria-label="Page actions"></div>
          <button class="flip prev" data-act="prev" aria-label="Previous page">‹</button>
          <button class="flip next" data-act="next" aria-label="Next page">›</button>
          <nav class="thumbs" aria-label="Chapters"></nav>
        </section>
      </div>
      <div class="sheet-backdrop m-only" data-act="sheet-close"></div>
      <footer class="bottombar">
        <button class="btn ghost mnav-btn m-only" data-act="prev" aria-label="Previous page">‹</button>
        <div class="tray" role="toolbar" aria-label="Highlighters"></div>
        <button class="btn ghost mnav-btn m-only" data-act="next" aria-label="Next page">›</button>
        <div class="scrub d-only"><input type="range" min="0" step="1" aria-label="Page"><span class="scrub-label"></span></div>
        <div class="bb-right d-only">
          <div class="zoom" role="group" aria-label="Zoom">
            <button class="btn ghost small" data-act="zoom-out" title="Zoom out (−)">−</button>
            <button class="btn ghost small zoom-level" data-act="zoom-fit" title="Fit the page to the window (Z toggles)">Fit</button>
            <button class="btn ghost small" data-act="zoom-in" title="Zoom in (+) — or pinch on the trackpad">+</button>
          </div>
          <input class="goto" placeholder="Go to page" aria-label="Go to page" inputmode="numeric">
          <button class="btn ghost small" data-act="toggle-sidebar" title="Show or hide the Casebook (C)">Casebook</button>
          <button class="btn ghost small" data-act="toggle-view" title="Two pages or one (V)"></button>
          <button class="btn ghost small" data-act="toggle-strike" title="Also strike through struck names">S̶</button>
        </div>
      </footer>
      <style class="pen-css"></style>
    </div>`));
    this.el = {
      game: $('.game', this.root), book: $('.book', this.root), wrap: $('.book-wrap', this.root), stage: $('.stage', this.root),
      scroller: $('.scroller', this.root), actions: $('.page-actions', this.root), zoomLevel: $('.zoom-level', this.root),
      casebook: $('.casebook', this.root), thumbs: $('.thumbs', this.root), tray: $('.tray', this.root),
      range: $('.scrub input', this.root), scrubLabel: $('.scrub-label', this.root), goto: $('.goto', this.root),
      num: $('.tb-num', this.root), saveState: $('.save-state', this.root), penCss: $('.pen-css', this.root),
      strip: $('.clue-strip', this.root),
    };
    this.compact = COMPACT.matches;
    this.el.game.classList.toggle('compact', this.compact);
    this.el.range.max = this.model.seq.length - 1;
    this.bindEvents();
    this.applyPenColors();
    this.renderCasebook();
    this.renderTray();
    this.renderThumbs();
    this.applyView();
    this.updateCounts();
    if (this.inquiry) this.witnessTimer = setTimeout(() => this.checkWitnesses(), 400);
    this.setSaveState('saved');
    this.startClock();
    if (!this.g.seenIntro) { this.g.seenIntro = true; this.save(); setTimeout(() => this.showHelp(true), 300); }
    if (this.g.solved) this.el.game.classList.add('solved');
  }

  destroy() {
    this.save.cancel();
    clearTimeout(this.witnessTimer);
    this.persist(true);
    for (const off of this.cleanup) off();
    clearInterval(this.clock);
  }

  on(target, ev, fn, opts) {
    target.addEventListener(ev, fn, opts);
    this.cleanup.push(() => target.removeEventListener(ev, fn, opts));
  }

  bindEvents() {
    const r = this.root;
    this.on(r, 'click', e => this.onClick(e));
    this.on(window, 'resize', () => this.layout());
    this.on(document, 'keydown', e => this.onKey(e));
    this.on(this.el.book, 'pointerdown', e => this.onPointerDown(e));
    this.on(this.el.book, 'click', e => this.onBookTap(e));
    this.on(this.el.scroller, 'touchstart', e => this.onSwipeStart(e), { passive: true });
    this.on(this.el.scroller, 'touchend', e => this.onSwipeEnd(e), { passive: true });
    this.on(COMPACT, 'change', () => this.layout());
    this.on(window, 'pointermove', e => { this.lastPointer = { x: e.clientX, y: e.clientY }; this.cancelLongPress(e); this.onPointerMove(e); });
    this.on(window, 'pointerup', () => { this.cancelLongPress(); this.endStroke(); this.releaseTap(); });
    this.on(window, 'pointercancel', () => { this.cancelLongPress(); this.endStroke(); });
    this.on(this.el.book, 'contextmenu', e => this.onContext(e));
    this.on(this.el.thumbs, 'contextmenu', e => this.onThumbContext(e));
    this.on(this.el.range, 'input', () => this.updateScrubLabel(+this.el.range.value));
    this.on(this.el.range, 'change', () => { this.goTo(+this.el.range.value); this.el.range.blur(); });
    this.on(this.el.goto, 'keydown', e => {
      if (e.key !== 'Enter') return;
      const v = this.el.goto.value.trim().toLowerCase();
      const n = parseInt(v, 10);
      if (/^\d+$/.test(v) && n >= 1 && n <= this.model.book.pageCount) this.goTo(this.model.seqOfPage(n));
      else {
        const k = this.model.seq.findIndex((s, i) => i < this.model.frontCount && s.folio === v);
        if (k >= 0) this.goTo(k); else toast(`There is no page “${esc(v)}”. The Register runs from 1 to ${this.model.book.pageCount}.`);
      }
      this.el.goto.value = ''; this.el.goto.blur();
    });
    this.on(document, 'visibilitychange', () => { if (document.visibilityState === 'hidden') this.persist(true); });
    this.on(window, 'pagehide', () => this.persist(true));
    this.on(this.el.stage, 'wheel', e => {
      if (this.compact) return;
      // Pinch on a trackpad arrives as a ctrl-wheel in Chrome.
      if (e.ctrlKey) { e.preventDefault(); return this.setZoom(this.zoom * Math.exp(-e.deltaY * 0.01), e); }
      const pannable = this.el.scroller.scrollWidth > this.el.scroller.clientWidth + 1;
      if (!pannable && Math.abs(e.deltaX) > 40 && Math.abs(e.deltaX) > Math.abs(e.deltaY) * 1.5 && !this.wheelLock) {
        this.wheelLock = true; setTimeout(() => (this.wheelLock = false), 450);
        this.flip(e.deltaX > 0 ? 1 : -1);
      }
    }, { passive: false });
    // Safari reports pinches as gesture events.
    let gestureStart = 1;
    this.on(this.el.stage, 'gesturestart', e => { if (this.compact) return; e.preventDefault(); gestureStart = this.zoom; });
    this.on(this.el.stage, 'gesturechange', e => { if (this.compact) return; e.preventDefault(); this.setZoom(gestureStart * e.scale, e); });
  }

  // ── view & layout ────────────────────────────────────────────────────────
  get spreadMode() { return this.g.view.mode === 'spread' && !this.forceSingle; }

  applyView() {
    const v = this.g.view;
    this.el.game.classList.toggle('no-sidebar', !v.sidebar);
    this.el.game.classList.toggle('strike', !!v.strike);
    $('[data-act="toggle-strike"]', this.root).classList.toggle('on', !!v.strike);
    $('[data-act="toggle-sidebar"]', this.root).classList.toggle('on', !!v.sidebar);
    this.layout();
  }

  layout() {
    if (COMPACT.matches !== this.compact) this.setCompact(COMPACT.matches);
    this.applyScale();
    this.render();
  }

  /** Switch between the desk layout and the phone layout (on load, resize or rotation). */
  setCompact(on) {
    this.compact = on;
    this.el.game.classList.toggle('compact', on);
    this.closeSheet();
    $('.ctx-menu')?.remove();
    this.renderCasebook();
  }

  get zoom() { return this.g.view.zoom || 1; }

  /** Fit the book to the stage, then apply the reader's zoom on top. */
  applyScale() {
    if (this.compact) {
      // The phone layout reflows each page to the screen's width: no scaling, one page at a time.
      this.forceSingle = true;
      this.fitScale = this.scale = 1;
      this.el.book.classList.add('single');
      this.el.book.style.transform = '';
      this.el.wrap.style.width = this.el.wrap.style.height = '';
      this.el.stage.classList.remove('zoomed');
      this.renderPageActions();
      return;
    }
    const sc = this.el.scroller;
    const availW = sc.clientWidth - 112, availH = sc.clientHeight - 24;
    const spreadScale = Math.min(availW / (PAGE_W * 2), availH / PAGE_H);
    this.forceSingle = spreadScale < 0.42;
    const w = this.spreadMode ? PAGE_W * 2 : PAGE_W;
    this.fitScale = Math.max(0.2, Math.min(availW / w, availH / PAGE_H, 1.25));
    this.maxZoom = Math.max(1, 2.2 / this.fitScale);
    if (this.zoom > this.maxZoom) this.g.view.zoom = this.maxZoom;
    const s = this.fitScale * this.zoom;
    this.scale = s;
    this.el.book.classList.toggle('single', !this.spreadMode);
    this.el.book.style.transform = `scale(${s})`;
    this.el.wrap.style.width = `${w * s}px`;
    this.el.wrap.style.height = `${PAGE_H * s}px`;
    this.el.stage.classList.toggle('zoomed', this.zoom > 1.001);
    this.el.zoomLevel.textContent = this.zoom > 1.001 ? `${Math.round(s * 100)}%` : 'Fit';
    $('[data-act="toggle-view"]', this.root).textContent = this.spreadMode ? 'Two pages' : 'One page';
    this.renderPageActions();
  }

  /** Zoom to z × fit, keeping the point under the pointer (if any) in place. */
  setZoom(z, ev, { center = false } = {}) {
    z = Math.max(1, Math.min(this.maxZoom || 3, z));
    if (Math.abs(z - this.zoom) < 0.001) return;
    const sc = this.el.scroller, r = sc.getBoundingClientRect();
    const px = ev?.clientX !== undefined ? ev.clientX - r.left : sc.clientWidth / 2;
    const py = ev?.clientY !== undefined ? ev.clientY - r.top : sc.clientHeight / 3;
    const wr = this.el.wrap.getBoundingClientRect();
    const fx = (sc.scrollLeft + px - (wr.left - r.left + sc.scrollLeft)) / wr.width;
    const fy = (sc.scrollTop + py - (wr.top - r.top + sc.scrollTop)) / wr.height;
    this.g.view.zoom = z;
    this.applyScale();
    const nw = this.el.wrap.getBoundingClientRect();
    sc.scrollLeft += (nw.left - r.left) + fx * nw.width - (center ? sc.clientWidth / 2 : px);
    sc.scrollTop += (nw.top - r.top) + fy * nw.height - py;
    this.save();
  }
  zoomStep(dir) {
    const a = this.zoomAnchor();
    this.setZoom(dir > 0 ? Math.min(this.maxZoom, this.zoom * 1.25) : this.zoom / 1.25, a, { center: !a?.fromPointer });
  }

  /** Keyboard/button zoom centres on the page under the mouse, else the right-hand page. */
  zoomAnchor() {
    const lp = this.lastPointer;
    const r = this.el.scroller.getBoundingClientRect();
    if (lp && lp.x >= r.left && lp.x <= r.right && lp.y >= r.top && lp.y <= r.bottom) return { clientX: lp.x, clientY: lp.y, fromPointer: true };
    const pages = $$('.slot:not(.empty) .page', this.el.book);
    const target = pages.find(p => p.classList.contains('register')) || pages[pages.length - 1];
    if (!target) return undefined;
    const pr = target.getBoundingClientRect();
    return { clientX: pr.left + pr.width / 2, clientY: Math.max(r.top + 40, pr.top + pr.height * 0.3) };
  }

  /** Full-size buttons under each visible page — easy targets at any zoom. */
  renderPageActions() {
    if (!this.el.actions || !this.fitScale) return;
    if (this.compact) return this.renderCompactActions();
    const vis = this.visible();
    const pageW = PAGE_W * this.fitScale;
    const dot = `<i class="pen-dot" style="--c:${hexOf(this.g.penColors[this.g.activePen])}"></i>`;
    const victim = this.model.caseData.victim;
    const counts = ids => { let open = 0, marked = 0; for (const i of ids) { if (i === victim) continue; if (this.marks[i]) marked++; else open++; } return { open, marked }; };
    const dis = cond => cond ? ' disabled' : '';
    this.el.actions.innerHTML = vis.map(seq => {
      const item = seq === null ? null : this.model.seq[seq];
      if (!item || item.kind !== 'register') return `<div class="pa-group" style="width:${pageW}px"></div>`;
      const p = item.page;
      const pc = counts(this.pageIds(p.page));
      const cc = p.opener ? counts(this.chapterIds(p.ci)) : null;
      // On narrow stages, drop the page label and then the verbs so nothing is clipped.
      const compact = pageW < 430, tiny = pageW < 360;
      return `<div class="pa-group" style="width:${pageW}px">
        ${compact ? '' : `<span class="pa-label">p. ${p.page}</span>`}
        <span class="pa-pair"><button class="btn small" data-act="mark-page" data-page="${p.page}"${dis(!pc.open || this.g.solved)} title="Strike every unmarked name on this page with the current highlighter">${dot}${tiny ? 'Page' : 'Strike page'}</button><button class="btn ghost small" data-act="clear-page" data-page="${p.page}"${dis(!pc.marked || this.g.solved)} title="Clear every mark on page ${p.page}">Clear</button></span>
        ${cc ? `<span class="pa-pair"><button class="btn small" data-act="mark-chapter" data-ci="${p.ci}"${dis(!cc.open || this.g.solved)} title="Strike every unmarked name in ${this.model.book.chapters[p.ci].title}">${dot}${tiny ? 'Chapter' : 'Strike chapter'}</button><button class="btn ghost small" data-act="clear-chapter" data-ci="${p.ci}"${dis(!cc.marked || this.g.solved)} title="Clear every mark in ${this.model.book.chapters[p.ci].title}">Clear</button></span>` : ''}
      </div>`;
    }).join('');
  }

  /** Phone layout: the page's label (tap to jump), its strike buttons, and each column's. */
  renderCompactActions() {
    const item = this.model.seq[this.g.pos];
    const victim = this.model.caseData.victim;
    const counts = ids => { let open = 0, marked = 0; for (const i of ids) { if (i === victim) continue; if (this.marks[i]) marked++; else open++; } return { open, marked }; };
    const dis = cond => cond || this.g.solved ? ' disabled' : '';
    const dot = `<i class="pen-dot" style="--c:${hexOf(this.g.penColors[this.g.activePen])}"></i>`;
    const label = item.kind === 'register' ? `Page ${item.page.page} <span>of ${this.model.book.pageCount}</span>` : `${{ title: 'Title page', case: 'The Case', evidence: this.inquiry ? 'The Witnesses' : 'The Evidence', contents: 'Contents', blank: 'Blank page' }[item.kind]} <span>· ${item.folio}</span>`;
    let html = `<button class="pa-where" data-act="nav" title="Go to a page or chapter">${label} ▾</button>`;
    if (item.kind === 'register') {
      const p = item.page, pc = counts(this.pageIds(p.page));
      html += `<span class="pa-pair"><button class="btn small" data-act="mark-page" data-page="${p.page}"${dis(!pc.open)}>${dot}Page</button><button class="btn ghost small" data-act="clear-page" data-page="${p.page}"${dis(!pc.marked)}>Clear</button></span>`;
      if (p.opener) {
        const cc = counts(this.chapterIds(p.ci));
        html += `<span class="pa-pair"><button class="btn small" data-act="mark-chapter" data-ci="${p.ci}"${dis(!cc.open)}>${dot}Chapter</button><button class="btn ghost small" data-act="clear-chapter" data-ci="${p.ci}"${dis(!cc.marked)}>Clear</button></span>`;
      }
      p.cols.forEach((ids, k) => {
        const head = $(`.col-head[data-col="${k}"]`, this.el.book);
        if (!head) return;
        const c = counts(ids);
        $('.col-count', head).textContent = c.open ? `${c.open} standing` : 'all struck';
        $('[data-act="mark-col"]', head).disabled = !c.open || !!this.g.solved;
        $('[data-act="clear-col"]', head).disabled = !c.marked || !!this.g.solved;
        $('.pen-dot', head).style.setProperty('--c', hexOf(this.g.penColors[this.g.activePen]));
      });
    }
    this.el.actions.innerHTML = html;
  }

  visible() {
    const pos = this.g.pos, n = this.model.seq.length;
    if (!this.spreadMode) return [pos];
    const k = pos === 0 ? 0 : Math.floor((pos + 1) / 2);
    return [k === 0 ? null : 2 * k - 1, 2 * k < n ? 2 * k : null];
  }

  render() {
    const vis = this.visible();
    this.el.book.innerHTML = '';
    this.nodes.clear();
    const solved = !!this.g.solved;
    vis.forEach((seq, slot) => {
      const holder = h(`<div class="slot ${this.spreadMode ? (slot === 0 ? 'left' : 'right') : 'only'}"></div>`);
      if (seq !== null) {
        const pg = renderPage(this.model, seq, { side: this.spreadMode ? (slot === 0 ? 'verso' : 'recto') : undefined, marks: this.marks, solved, revealed: this.shown, compact: this.compact });
        holder.append(pg);
      } else holder.classList.add('empty');
      this.el.book.append(holder);
    });
    for (const li of $$('.nm', this.el.book)) {
      const i = +li.dataset.i;
      this.nodes.set(i, li);
      if (this.flagged.has(i)) li.classList.add('flag');
    }
    this.renderPageActions();
    const shown = vis.filter(v => v !== null);
    const labelSeq = shown.find(v => this.model.seq[v].kind === 'register') ?? shown[0];
    this.el.range.value = labelSeq;
    this.updateScrubLabel(labelSeq);
    this.updateThumbActive();
    for (const b of $$('[data-act="prev"]', this.root)) b.disabled = shown[0] <= 0;
    for (const b of $$('[data-act="next"]', this.root)) b.disabled = Math.max(...shown) >= this.model.seq.length - 1;
    this.updateStrip();
  }

  goTo(seq, flashI) {
    seq = Math.max(0, Math.min(this.model.seq.length - 1, seq));
    const moved = this.g.pos !== seq;
    if (moved) { this.g.pos = seq; this.save(); }
    this.render();
    // A reflowed page is taller than the screen: start each new one at the top.
    if (this.compact && moved) this.el.scroller.scrollTop = 0;
    if (flashI !== undefined) {
      const li = this.nodes.get(flashI);
      if (li) {
        li.classList.remove('flash'); void li.offsetWidth; li.classList.add('flash');
        if (this.zoom > 1.001 || this.compact) li.scrollIntoView({ block: 'center', inline: 'center' });
      }
    }
  }

  flip(dir) {
    const n = this.model.seq.length;
    if (this.compact) {
      // One page at a time, skipping the blank page that only exists so print spreads line up.
      let to = this.g.pos + dir;
      if (this.model.seq[to]?.kind === 'blank') to += dir;
      return this.goTo(to);
    }
    if (!this.spreadMode) return this.goTo(this.g.pos + dir);
    const k = this.g.pos === 0 ? 0 : Math.floor((this.g.pos + 1) / 2);
    const nk = Math.max(0, Math.min(Math.ceil((n - 1) / 2), k + dir));
    this.goTo(nk === 0 ? 0 : 2 * nk - 1);
  }

  seqLabel(seq) {
    const s = this.model.seq[seq];
    if (s.kind !== 'register') return `Front matter · ${s.folio}`;
    return `Page ${s.page.page} of ${this.model.book.pageCount} · ${this.model.book.chapters[s.page.ci].title}`;
  }
  updateScrubLabel(seq) { this.el.scrubLabel.textContent = this.seqLabel(seq); }

  // ── marks ────────────────────────────────────────────────────────────────
  recount() {
    const { entries, chapters } = this.model.book;
    this.penCounts = {};
    this.chapterStruck = new Array(chapters.length).fill(0);
    this.struck = 0;
    for (const e of entries) {
      const p = this.marks[e.i];
      if (!p || e.i === this.model.caseData.victim) continue;
      this.penCounts[p] = (this.penCounts[p] || 0) + 1;
      this.chapterStruck[e.ci]++;
      this.struck++;
    }
    this.chapterSize = chapters.map(c => c.count - (this.model.victim.ci === c.ci ? 1 : 0));
  }

  get remaining() { return this.model.book.entries.length - 1 - this.struck; }

  /** Set one mark; returns a change record or null. */
  set(i, pen, changes) {
    const old = this.marks[i];
    if (old === pen || i === this.model.caseData.victim || this.g.solved) return;
    const ci = this.model.book.entries[i].ci;
    if (old) { this.penCounts[old]--; if (!pen) { this.struck--; this.chapterStruck[ci]--; } }
    else { this.struck++; this.chapterStruck[ci]++; }
    if (pen) this.penCounts[pen] = (this.penCounts[pen] || 0) + 1;
    this.marks[i] = pen;
    const li = this.nodes.get(i);
    if (li) {
      li.classList.toggle('m', !!pen);
      if (pen) li.dataset.pen = pen; else delete li.dataset.pen;
    }
    if (this.flagged.delete(i) && li) li.classList.remove('flag');
    changes?.push([i, old, pen]);
  }

  commit(changes, label) {
    if (!changes.length) return;
    this.undoStack.push(changes);
    if (this.undoStack.length > UNDO_LIMIT) this.undoStack.shift();
    this.redoStack = [];
    this.afterChange();
    if (label && changes.length > 1) toast(`${label} <span class="muted">(${fmt(changes.length)} name${changes.length > 1 ? 's' : ''})</span>`, { action: 'Undo', onAction: () => this.undo() });
  }

  afterChange() {
    this.updateCounts();
    this.renderPageActions();
    if (this.inquiry) this.checkWitnesses();
    this.save();
    if (this.remaining === 1 && !this.g.solved && !this.lonePrompted) {
      this.lonePrompted = true;
      const lone = this.model.book.entries.find(e => !this.marks[e.i] && e.i !== this.model.caseData.victim);
      toast(`Only one name is left standing: <b>${lone.name}</b> (page ${lone.page}).`, { action: 'Accuse', onAction: () => this.accuse(lone.i), ms: 9000 });
    }
    if (this.remaining !== 1) this.lonePrompted = false;
  }

  undo() {
    if (this.g.solved) return;
    const ch = this.undoStack.pop();
    if (!ch) return toast('Nothing to undo.');
    for (let k = ch.length - 1; k >= 0; k--) this.set(ch[k][0], ch[k][1]);
    this.redoStack.push(ch);
    this.afterChange();
    this.revealChange(ch);
  }
  redo() {
    if (this.g.solved) return;
    const ch = this.redoStack.pop();
    if (!ch) return toast('Nothing to redo.');
    for (const [i, , nw] of ch) this.set(i, nw);
    this.undoStack.push(ch);
    this.afterChange();
    this.revealChange(ch);
  }
  revealChange(ch) {
    if (ch.length && !this.nodes.has(ch[0][0])) this.goTo(this.model.seqOfEntry(ch[0][0]));
  }

  // ── pointer: highlighter strokes ─────────────────────────────────────────
  onPointerDown(e) {
    if (e.button !== 0) return;
    if (this.compact) return this.startLongPress(e);
    const toc = e.target.closest('[data-goto]');
    if (toc) { this.goTo(+toc.dataset.goto); return; }
    const li = e.target.closest('.nm');
    if (!li || this.g.solved) return;
    const i = +li.dataset.i;
    if (i === this.model.caseData.victim) { toast(`${this.model.victim.name} is the victim — not a suspect.`); return; }
    e.preventDefault();
    const pen = this.g.activePen;
    if (e.shiftKey && this.anchor !== null) return this.markRange(this.anchor, i);
    const erase = this.marks[i] === pen; // clicking your own mark clears it
    this.stroke = { erase, pen, overwrite: e.altKey, changes: [], seen: new Set([i]) };
    this.set(i, erase ? 0 : pen, this.stroke.changes);
    this.anchor = i;
  }

  onPointerMove(e) {
    if (!this.stroke) return;
    const li = document.elementFromPoint(e.clientX, e.clientY)?.closest?.('.nm');
    if (!li) return;
    const i = +li.dataset.i;
    if (i === this.anchor) return;
    // Pointer events arrive sparsely on a fast drag; fill in every name passed
    // over within the same column so nothing in between is skipped.
    const { entries } = this.model.book;
    const a = entries[this.anchor], b = entries[i];
    const between = a && a.page === b.page && a.col === b.col
      ? Array.from({ length: Math.abs(i - this.anchor) }, (_, k) => (i > this.anchor ? this.anchor + 1 + k : this.anchor - 1 - k))
      : [i];
    for (const j of between) this.strokeOver(j);
    this.anchor = i;
  }

  // ── phone: tap to strike, long-press for options, swipe to turn ─────────
  /** A tap, not a pointerdown: on a phone a touch that turns into a scroll must strike nothing. */
  onBookTap(e) {
    if (!this.compact) return;
    if (this.suppressTap) { this.suppressTap = false; return; }
    const toc = e.target.closest('[data-goto]');
    if (toc) return this.goTo(+toc.dataset.goto);
    const li = e.target.closest('.nm');
    if (!li || this.g.solved) return;
    const i = +li.dataset.i;
    if (i === this.model.caseData.victim) return toast(`${this.model.victim.name} is the victim — not a suspect.`);
    const pen = this.g.activePen, changes = [];
    this.set(i, this.marks[i] === pen ? 0 : pen, changes);
    this.anchor = i;
    this.commit(changes);
  }

  startLongPress(e) {
    const li = e.target.closest('.nm');
    clearTimeout(this.press?.timer);
    if (!li) { this.press = null; return; }
    const x = e.clientX, y = e.clientY;
    this.press = { x, y, timer: setTimeout(() => {
      this.press = null;
      // However long the finger stays down, the tap that ends this press must not strike the name.
      this.suppressTap = true;
      navigator.vibrate?.(10);
      // Open just below the finger, so lifting it doesn't land on a menu button.
      this.nameMenu(+li.dataset.i, x - 40, y + 18);
    }, LONG_PRESS_MS) };
  }

  /** After a long press, let the click that follows its release go by, then accept taps again. */
  releaseTap() {
    if (this.suppressTap) setTimeout(() => (this.suppressTap = false), 400);
  }

  /** A press that moves (a scroll) or lifts early is a scroll or a tap, not a long press. */
  cancelLongPress(e) {
    if (!this.press) return;
    if (e && Math.hypot(e.clientX - this.press.x, e.clientY - this.press.y) < 10) return;
    clearTimeout(this.press.timer);
    this.press = null;
  }

  onSwipeStart(e) {
    if (!this.compact || e.touches.length !== 1) { this.swipe = null; return; }
    const t = e.touches[0];
    this.swipe = { x: t.clientX, y: t.clientY, at: Date.now() };
  }

  onSwipeEnd(e) {
    const s = this.swipe;
    this.swipe = null;
    if (!s || !this.compact || $('.modal-backdrop')) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - s.x, dy = t.clientY - s.y;
    // A deliberate sideways swipe: long enough, mostly horizontal, and quick.
    if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 2 && Date.now() - s.at < 700) this.flip(dx < 0 ? 1 : -1);
  }

  openSheet(tab) {
    if (tab && tab !== this.g.view.tab) { this.g.view.tab = tab; this.renderCasebook(); }
    this.el.game.classList.add('sheet-open');
  }
  closeSheet() { this.el.game.classList.remove('sheet-open'); }

  /** The active clue, always in view on a phone; tap it for the whole Casebook. */
  updateStrip() {
    if (!this.el.strip) return;
    const pen = this.g.activePen;
    this.el.strip.style.setProperty('--c', hexOf(this.g.penColors[pen]));
    $('.cs-text', this.el.strip).innerHTML = pen === PENCIL
      ? '<b>✎</b> Pencil: struck, but you haven’t decided which clue clears them.'
      : `<b>${ROMAN_UP(pen)}</b> ${esc(this.rules[pen - 1].text)}`;
    const next = $('.cs-next', this.el.strip);
    if (this.inquiry && !this.g.solved && this.g.revealed < this.rules.length) {
      const left = this.outstanding();
      next.textContent = left ? `Witness ${this.g.revealed + 1} comes forward after ${fmt(left)} more name${left === 1 ? '' : 's'}` : 'Every name is struck — the next witness is coming…';
    } else next.textContent = '';
  }

  /** Phone: jump to a page, the front matter or a chapter. */
  navSheet() {
    const { chapters, pageCount } = this.model.book;
    const front = this.model.seq.slice(0, this.model.frontCount).map((s, k) => ({ s, k })).filter(({ s }) => s.kind === 'case' || s.kind === 'contents' || (s.kind === 'evidence' && s.part === 0));
    const frontLabel = s => s.kind === 'case' ? 'The Case' : s.kind === 'contents' ? 'Contents' : this.inquiry ? 'The Witnesses' : 'The Evidence';
    modal({
      title: 'Go to…',
      className: 'nav-sheet',
      body: `<form class="row nav-go"><input class="input" type="number" inputmode="numeric" min="1" max="${pageCount}" placeholder="Page 1–${pageCount}" aria-label="Page number"><button class="btn primary">Go</button></form>
        <div class="nav-front">${front.map(({ s, k }) => `<button class="btn small" data-seq="${k}">${frontLabel(s)}</button>`).join('')}</div>
        <ul class="nav-chapters">${chapters.map(ch => {
          const frac = this.chapterStruck[ch.ci] / this.chapterSize[ch.ci];
          return `<li><button data-seq="${this.model.seqOfPage(ch.firstPage)}" style="--done:${frac}" class="${frac >= 1 ? 'cleared' : ''}"><b>${ch.title}</b><span>pp. ${ch.firstPage}–${ch.lastPage} · ${frac >= 1 ? 'all struck' : `${Math.round(frac * 100)}% struck`}</span><i></i></button></li>`;
        }).join('')}</ul>`,
      actions: [{ label: 'Close' }],
      onOpen: (root, close) => {
        $('.nav-go', root).addEventListener('submit', ev => {
          ev.preventDefault();
          const n = parseInt($('input', root).value, 10);
          if (n >= 1 && n <= pageCount) { close(); this.goTo(this.model.seqOfPage(n)); }
          else toast(`The ${esc(this.model.word)} runs from page 1 to ${pageCount}.`);
        });
        root.addEventListener('click', ev => { const b = ev.target.closest('[data-seq]'); if (b) { close(); this.goTo(+b.dataset.seq); } });
        // Bring the current chapter into view.
        const s = this.model.seq[this.g.pos];
        if (s.kind === 'register') $$('.nav-chapters li', root)[s.page.ci]?.scrollIntoView({ block: 'center' });
      },
    });
  }

  /** Phone: everything that doesn't fit in the top bar. */
  moreMenu(anchor) {
    const r = anchor.getBoundingClientRect();
    this.menu(r.right - 240, r.bottom + 4, `
      <button class="cm-item" data-cm="mark-pages">Strike by position…</button>
      <button class="cm-item" data-cm="redo">Redo</button>
      <button class="cm-item" data-cm="case">The Case and your progress</button>
      <button class="cm-item" data-cm="sergeant">Ask the Sergeant for a hint</button>
      <button class="cm-item" data-cm="strike">${this.g.view.strike ? 'Hide' : 'Show'} a line through struck names</button>
      <button class="cm-item" data-cm="help">How to play</button>`, (b, close) => {
      close();
      const cm = b.dataset.cm;
      if (cm === 'mark-pages') this.markPagesDialog();
      else if (cm === 'redo') this.redo();
      else if (cm === 'case') this.openSheet('case');
      else if (cm === 'sergeant') this.sergeant();
      else if (cm === 'strike') { this.g.view.strike = !this.g.view.strike; this.save(); this.applyView(); }
      else if (cm === 'help') this.showHelp();
    });
  }

  strokeOver(i) {
    if (this.stroke.seen.has(i)) return;
    this.stroke.seen.add(i);
    const cur = this.marks[i];
    if (this.stroke.erase) {
      if (cur === this.stroke.pen) this.set(i, 0, this.stroke.changes);
    } else if (!cur || this.stroke.overwrite) this.set(i, this.stroke.pen, this.stroke.changes);
  }

  endStroke() {
    if (!this.stroke) return;
    const s = this.stroke;
    this.stroke = null;
    this.commit(s.changes);
  }

  /** Unmarked suspects from entry a to entry b, inclusive, in Register order. */
  runCount(a, b) {
    const [lo, hi] = a < b ? [a, b] : [b, a];
    let n = 0;
    for (let i = lo; i <= hi; i++) if (!this.marks[i] && i !== this.model.caseData.victim) n++;
    return n;
  }

  markRange(a, b) {
    const [lo, hi] = a < b ? [a, b] : [b, a];
    const changes = [];
    const pen = this.g.activePen;
    for (let i = lo; i <= hi; i++) if (!this.marks[i]) this.set(i, pen, changes);
    this.anchor = b;
    this.commit(changes, `Struck a run of names with ${this.penName(pen)}`);
  }

  strikeIndices(ids, label) {
    if (this.g.solved) return;
    const changes = [];
    const pen = this.g.activePen;
    for (const i of ids) if (!this.marks[i]) this.set(i, pen, changes);
    this.commit(changes, label);
    if (!changes.length) toast('Every name there is already struck.');
  }
  clearIndices(ids, label) {
    const changes = [];
    for (const i of ids) this.set(i, 0, changes);
    this.commit(changes, label);
  }
  pageIds(pageNo) { return this.model.book.pages[pageNo - 1].cols.flat(); }
  columnIds(pageNo, col) { return this.model.book.pages[pageNo - 1].cols[col]; }
  chapterIds(ci) { return this.model.book.entries.filter(e => e.ci === ci).map(e => e.i); }

  // ── clicks ───────────────────────────────────────────────────────────────
  onClick(e) {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const act = b.dataset.act;
    const pg = +b.dataset.page, ci = +b.dataset.ci;
    switch (act) {
      case 'home': return this.onExit();
      case 'prev': return this.flip(-1);
      case 'next': return this.flip(1);
      case 'find': return this.find();
      case 'mark-pages': return this.markPagesDialog();
      case 'sergeant': return this.sergeant();
      case 'print': return this.print();
      case 'help': return this.showHelp();
      case 'accuse': return this.accuse();
      case 'toggle-sidebar': this.g.view.sidebar = !this.g.view.sidebar; this.save(); return this.applyView();
      case 'toggle-view': this.g.view.mode = this.spreadMode ? 'single' : 'spread'; if (this.forceSingle) toast('The window is too narrow for two pages — widen it or close the Casebook.'); this.save(); return this.layout();
      case 'toggle-strike': this.g.view.strike = !this.g.view.strike; this.save(); return this.applyView();
      case 'mark-page': return this.strikeIndices(this.pageIds(pg), `Struck page ${pg}`);
      case 'mark-col': return this.strikeIndices(this.columnIds(pg, +b.dataset.col), `Struck the ${columnName(+b.dataset.col, this.model.book.cols).toLowerCase()} column of page ${pg}`);
      case 'clear-col': return this.clearIndices(this.columnIds(pg, +b.dataset.col), `Cleared the ${columnName(+b.dataset.col, this.model.book.cols).toLowerCase()} column of page ${pg}`);
      case 'undo': return this.undo();
      case 'more': return this.moreMenu(b);
      case 'nav': return this.navSheet();
      case 'sheet': return this.openSheet();
      case 'sheet-close': return this.closeSheet();
      case 'clear-page': return this.clearIndices(this.pageIds(pg), `Cleared page ${pg}`);
      case 'mark-chapter': return this.strikeIndices(this.chapterIds(ci), `Struck ${this.model.book.chapters[ci].title}`);
      case 'clear-chapter': return this.clearIndices(this.chapterIds(ci), `Cleared ${this.model.book.chapters[ci].title}`);
      case 'zoom-in': return this.zoomStep(1);
      case 'zoom-out': return this.zoomStep(-1);
      case 'zoom-fit': return this.setZoom(1);
      case 'pen': this.setPen(+b.dataset.pen); if (this.compact && b.closest('.casebook')) this.closeSheet(); return;
      case 'swatch': e.stopPropagation(); return this.colorPicker(+b.dataset.pen, b);
      case 'tab': this.g.view.tab = b.dataset.tab; this.save(); return this.renderCasebook();
      case 'thumb': return this.goTo(this.model.seqOfPage(this.model.book.chapters[+b.dataset.ci].firstPage));
      case 'goto-victim': return this.goTo(this.model.seqOfEntry(this.model.victim.i), this.model.victim.i);
      case 'goto-seq': return this.goTo(+b.dataset.seq);
    }
  }

  setPen(pen) {
    this.g.activePen = pen;
    this.save();
    // Update the selection in place so the Casebook keeps its scroll position.
    $$('.ev', this.el.casebook).forEach(li => li.classList.toggle('active', +li.dataset.ev === pen));
    $$('.chip', this.el.tray).forEach(c => c.classList.toggle('on', +c.dataset.pen === pen));
    this.applyPenColors();
    this.updateStrip();
    if (this.compact) $('.chip.on', this.el.tray)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
  penName(pen) { return pen === PENCIL ? 'the pencil' : `clue ${ROMAN_UP(pen)}`; }

  applyPenColors() {
    this.renderPageActions();
    this.el.penCss.textContent = penStyles(this.g.penColors);
    const cursor = penCursor(hexOf(this.g.penColors[this.g.activePen]));
    this.el.book.style.setProperty('--pen-cursor', cursor);
  }

  // ── casebook sidebar ─────────────────────────────────────────────────────
  renderCasebook() {
    const tab = this.g.view.tab;
    const c = this.model.caseData;
    const tabs = ['evidence', 'case'].map(t => `<button class="cb-tab ${t === tab ? 'on' : ''}" data-act="tab" data-tab="${t}">${{ evidence: 'Evidence', case: 'The Case' }[t]}</button>`).join('');
    let body = '';
    if (tab === 'evidence') {
      const row = (pen, num, src, text, label) => {
        const active = this.g.activePen === pen;
        return `<li class="ev ${active ? 'active' : ''}" data-ev="${pen}">
          <button class="swatch" data-act="swatch" data-pen="${pen}" style="--c:${hexOf(this.g.penColors[pen])}" title="Change this highlighter’s color"></button>
          <button class="ev-main" data-act="pen" data-pen="${pen}" title="Use this highlighter${pen <= 10 ? ` (${pen % 10})` : pen <= 20 ? ` (⇧${pen - 10})` : ''}">
            <span class="ev-head"><b>${num}</b><span class="ev-src">${esc(src)}</span>${label ? `<span class="ev-tier">${esc(label)}</span>` : ''}<span class="ev-count">${fmt(this.penCounts[pen] || 0)}</span></span>
            <span class="ev-text">${esc(text)}</span>
          </button>
        </li>`;
      };
      const next = this.inquiry && this.shown < this.rules.length
        ? `<li class="ev next-witness"><div class="nw-num">${ROMAN_UP(this.shown + 1)}</div><div class="nw-body"><b>The next witness is waiting</b><span>They’ll come forward once every name the evidence so far rules out has been struck.</span><span class="nw-count"></span></div></li>` : '';
      body = `<p class="cb-hint">${this.inquiry ? `Witness ${this.shown} of ${this.rules.length}. ` : ''}${this.compact ? 'Tap a clue to use its highlighter, then tap names to strike them. Tap a struck name again to clear it.' : 'Choose a clue, then click or drag across names to strike them. Each clue has its own highlighter. Click a struck name again to clear it.'}</p>
        <ol class="ev-list">${this.rules.slice(0, this.shown).map((r, k) => row(k + 1, ROMAN_UP(k + 1), r.source, r.text, clueLabel(r))).join('')}
        ${next}
        ${row(PENCIL, '✎', 'Pencil', 'Struck, but you haven’t decided which clue clears them.', null)}</ol>`;
    } else {
      const paras = prologue(c.story, this.model.book, this.model.victim, this.rules.length, this.model.mode);
      body = `<div class="cb-case">${paras.map(p => `<p>${esc(p)}</p>`).join('')}
        <button class="btn small" data-act="goto-victim">Find ${esc(this.model.victim.name)} in the ${esc(this.model.word)}</button>
        <h4>Progress</h4>
        <dl class="stats"><dt>Names struck</dt><dd>${fmt(this.struck)}</dd><dt>Time on the case</dt><dd class="time-played">${duration(this.g.timePlayed)}</dd><dt>Accusations</dt><dd>${this.g.accusations.length}</dd><dt>Hints taken</dt><dd>${this.g.hints}</dd><dt>Case number</dt><dd>${esc(c.code)}</dd></dl></div>`;
    }
    // Keep the reader's place in the list across re-renders.
    const prev = $('.cb-body', this.el.casebook);
    const keep = prev && this.lastTab === tab ? prev.scrollTop : 0;
    this.el.casebook.innerHTML = `<div class="cb-tabs">${tabs}${this.compact ? '<button class="cb-close" data-act="sheet-close">Done</button>' : ''}</div><div class="cb-body">${body}</div>`;
    $('.cb-body', this.el.casebook).scrollTop = keep;
    this.lastTab = tab;
    this.applyPenColors();
    if (this.penCounts) this.updateCounts();
  }

  renderTray() {
    const chip = (pen, label) => `<button class="chip ${this.g.activePen === pen ? 'on' : ''}" data-act="pen" data-pen="${pen}" style="--c:${hexOf(this.g.penColors[pen])}" title="${pen === PENCIL ? 'Pencil — struck, reason undecided' : `Clue ${label}: ${esc(this.rules[pen - 1].text)}`}">${label}</button>`;
    this.el.tray.innerHTML = this.rules.slice(0, this.shown).map((_, k) => chip(k + 1, ROMAN_UP(k + 1))).join('') + chip(PENCIL, '✎');
    this.applyPenColors();
    this.updateStrip();
  }

  colorPicker(pen, anchor) {
    $('.palette-pop')?.remove();
    const pop = h(`<div class="palette-pop" role="dialog"><div class="pp-title">${pen === PENCIL ? 'Pencil' : `Clue ${ROMAN_UP(pen)}`} highlighter</div><div class="pp-grid">${PALETTE.map(p => `<button style="--c:${p.hex}" data-color="${p.id}" class="${this.g.penColors[pen] === p.id ? 'on' : ''}" title="${p.name}"></button>`).join('')}</div></div>`);
    document.body.append(pop);
    const r = anchor.getBoundingClientRect();
    pop.style.left = `${Math.min(window.innerWidth - 230, r.left)}px`;
    pop.style.top = `${Math.min(window.innerHeight - 160, r.bottom + 6)}px`;
    const close = ev => { if (!pop.contains(ev.target)) { pop.remove(); document.removeEventListener('pointerdown', close, true); } };
    setTimeout(() => document.addEventListener('pointerdown', close, true));
    pop.addEventListener('click', ev => {
      const b = ev.target.closest('[data-color]');
      if (!b) return;
      this.g.penColors[pen] = b.dataset.color;
      this.save();
      pop.remove();
      this.renderCasebook();
      this.renderTray();
      this.renderThumbs();
    });
  }

  // ── thumb index ──────────────────────────────────────────────────────────
  renderThumbs() {
    this.el.thumbs.innerHTML = this.model.book.chapters.map(ch => `<button class="thumb" data-act="thumb" data-ci="${ch.ci}" title="${ch.title} — ${fmt(ch.count)} names, pages ${ch.firstPage}–${ch.lastPage}"><span>${ch.label}</span><i></i></button>`).join('');
    this.updateThumbs();
  }
  updateThumbs() {
    $$('.thumb', this.el.thumbs).forEach((t, ci) => {
      const frac = this.chapterStruck[ci] / this.chapterSize[ci];
      t.style.setProperty('--done', frac);
      t.classList.toggle('cleared', frac >= 1);
    });
  }
  updateThumbActive() {
    const s = this.model.seq[this.visible().filter(v => v !== null).pop()];
    const ci = s?.kind === 'register' ? s.page.ci : -1;
    $$('.thumb', this.el.thumbs).forEach((t, k) => t.classList.toggle('here', k === ci));
    // When the tabs don't all fit, keep the current chapter's tab in view.
    const here = $('.thumb.here', this.el.thumbs), box = this.el.thumbs;
    if (here && box.scrollHeight > box.clientHeight && (here.offsetTop < box.scrollTop || here.offsetTop + here.offsetHeight > box.scrollTop + box.clientHeight)) {
      box.scrollTop = here.offsetTop - box.clientHeight / 2;
    }
  }

  updateCounts() {
    this.el.num.textContent = fmt(this.remaining);
    this.updateStrip();
    if (this.inquiry) {
      const left = this.outstanding();
      const el = $('.nw-count', this.el.casebook);
      if (el) el.textContent = left ? `${fmt(left)} name${left === 1 ? '' : 's'} still to strike.` : 'Every name is struck — here they come…';
    }
    for (const el of $$('.ev-count', this.el.casebook)) {
      const pen = +el.closest('.ev').querySelector('[data-pen]').dataset.pen;
      el.textContent = fmt(this.penCounts[pen] || 0);
    }
    this.updateThumbs();
  }

  // ── keyboard ─────────────────────────────────────────────────────────────
  onKey(e) {
    if ($('.modal-backdrop')) return;
    const ae = document.activeElement;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(ae?.tagName) && ae.type !== 'range';
    const mod = e.metaKey || e.ctrlKey;
    if (mod && !typing && e.key.toLowerCase() === 'z') { e.preventDefault(); return e.shiftKey ? this.redo() : this.undo(); }
    if (mod && !typing && e.key.toLowerCase() === 'y') { e.preventDefault(); return this.redo(); }
    if (mod && e.key.toLowerCase() === 'f') { e.preventDefault(); return this.find(); }
    if (mod && e.key.toLowerCase() === 'p') { e.preventDefault(); return this.print(); }
    if (typing || mod || e.altKey) return;
    const k = e.key;
    if (k === 'ArrowRight' || k === 'PageDown' || k === ' ') { e.preventDefault(); this.flip(e.shiftKey && k === ' ' ? -1 : 1); }
    else if (k === 'ArrowLeft' || k === 'PageUp') { e.preventDefault(); this.flip(-1); }
    else if (k === 'Home') this.goTo(0);
    else if (k === 'End') this.goTo(this.model.seq.length - 1);
    else if (/^Digit[0-9]$/.test(e.code) && e.shiftKey && !/^[0-9]$/.test(k)) { const d = +e.code.slice(5); const pen = 10 + (d === 0 ? 10 : d); if (pen <= this.shown) this.setPen(pen); }
    else if (/^[0-9]$/.test(k)) { const pen = k === '0' ? 10 : +k; if (pen <= this.shown) this.setPen(pen); }
    else if (k === '`' || k === '.') this.setPen(PENCIL);
    else if (k === '=' || k === '+') { e.preventDefault(); this.zoomStep(1); }
    else if (k === '-' || k === '_') { e.preventDefault(); this.zoomStep(-1); }
    else if (k === 'z' || k === 'Z') { const a = this.zoomAnchor(); this.setZoom(this.zoom > 1.001 ? 1 : Math.min(this.maxZoom, 1.8), a, { center: !a?.fromPointer }); }
    else if (k === '/') { e.preventDefault(); this.find(); }
    else if (k === 'g' || k === 'G') { e.preventDefault(); this.el.goto.focus(); }
    else if (k === 'c' || k === 'C') { this.g.view.sidebar = !this.g.view.sidebar; this.applyView(); this.save(); }
    else if (k === 'v' || k === 'V') { this.g.view.mode = this.spreadMode ? 'single' : 'spread'; if (this.forceSingle) toast('The window is too narrow for two pages — widen it or close the Casebook.'); this.layout(); this.save(); }
    else if (k === 'p' || k === 'P') { e.preventDefault(); this.markPagesDialog(); }
    else if (k === '?') { e.preventDefault(); this.showHelp(); }
    else if (k === '[' || k === ']') this.jumpChapter(k === ']' ? 1 : -1);
  }

  jumpChapter(dir) {
    // Judge "this chapter" by the last register page on view (in a spread, the right-hand page).
    const reg = this.visible().filter(v => v !== null && this.model.seq[v].kind === 'register').pop();
    const ci = reg === undefined ? -1 : this.model.seq[reg].page.ci;
    const next = Math.max(0, Math.min(this.model.book.chapters.length - 1, ci + dir));
    this.goTo(this.model.seqOfPage(this.model.book.chapters[next].firstPage));
  }

  // ── context menus ────────────────────────────────────────────────────────
  onContext(e) {
    const li = e.target.closest('.nm');
    if (!li) return;
    e.preventDefault();
    // Phones open the same menu on a long press (startLongPress); don't open it twice.
    if (this.compact) return;
    this.nameMenu(+li.dataset.i, e.clientX, e.clientY);
  }

  nameMenu(i, x, y) {
    const ent = this.model.book.entries[i];
    if (i === this.model.caseData.victim) return toast(`${ent.name} is the victim — not a suspect.`);
    const pens = [...this.rules.slice(0, this.shown).map((_, k) => k + 1), PENCIL];
    const run = this.runStart ?? null;
    this.menu(x, y, `<div class="cm-title">${ent.name} <span>p. ${ent.page}, line ${ent.line}</span></div>
      <div class="cm-label">Strike with</div>
      <div class="cm-pens">${pens.map(p => `<button data-pen="${p}" style="--c:${hexOf(this.g.penColors[p])}" class="${this.marks[i] === p ? 'on' : ''}">${p === PENCIL ? '✎' : ROMAN_UP(p)}</button>`).join('')}</div>
      ${this.marks[i] ? '<button class="cm-item" data-cm="clear">Clear this mark</button>' : ''}
      ${run !== null && run !== i ? `<button class="cm-item" data-cm="run-end">Strike everyone from ${this.model.book.entries[run].name} to here <span>${fmt(this.runCount(run, i))} unmarked, ${this.penName(this.g.activePen)}</span></button>` : ''}
      <button class="cm-item" data-cm="run-start">${run === i ? 'A run starts here — open another name to end it' : 'Start a run of names here'}</button>
      <button class="cm-item" data-cm="accuse">Accuse ${ent.name}…</button>`, (b, close) => {
      if (b.dataset.pen) { const ch = []; this.set(i, +b.dataset.pen, ch); this.commit(ch); close(); }
      else if (b.dataset.cm === 'clear') { const ch = []; this.set(i, 0, ch); this.commit(ch); close(); }
      else if (b.dataset.cm === 'run-start') { close(); this.runStart = i; toast(`A run starts at ${ent.name} (page ${ent.page}, line ${ent.line}). Go to the last name of the run and ${this.compact ? 'long-press' : 'right-click'} it.`, { ms: 6000 }); }
      else if (b.dataset.cm === 'run-end') { close(); this.runStart = null; this.markRange(run, i); }
      else if (b.dataset.cm === 'accuse') { close(); this.accuse(i); }
    });
  }

  onThumbContext(e) {
    const t = e.target.closest('.thumb');
    if (!t) return;
    e.preventDefault();
    const ci = +t.dataset.ci;
    const L = this.model.book.chapters[ci].title;
    this.menu(e.clientX - 200, e.clientY, `<div class="cm-title">${L}</div>
      <button class="cm-item" data-cm="strike">Strike every unmarked name in ${L} with ${this.penName(this.g.activePen)}</button>
      <button class="cm-item" data-cm="clear">Clear every mark in ${L}</button>`, (b, close) => {
      close();
      if (b.dataset.cm === 'strike') { this.strikeIndices(this.chapterIds(ci), `Struck ${L}`); }
      else this.clearIndices(this.chapterIds(ci), `Cleared ${L}`);
    });
  }

  menu(x, y, html, onPick) {
    $('.ctx-menu')?.remove();
    const m = h(`<div class="ctx-menu">${html}</div>`);
    document.body.append(m);
    m.style.left = `${Math.max(8, Math.min(window.innerWidth - m.offsetWidth - 8, x))}px`;
    m.style.top = `${Math.max(8, Math.min(window.innerHeight - m.offsetHeight - 8, y))}px`;
    const close = () => { m.remove(); document.removeEventListener('pointerdown', outside, true); };
    const outside = ev => { if (!m.contains(ev.target)) close(); };
    setTimeout(() => document.addEventListener('pointerdown', outside, true));
    m.addEventListener('click', ev => { const b = ev.target.closest('button'); if (b) onPick(b, close); });
  }

  // ── the Inquiry ──────────────────────────────────────────────────────────
  /** How many clues the reader can see (all of them in Cold Case). */
  get shown() { return this.inquiry && !this.g.solved ? this.g.revealed : this.rules.length; }

  /** Names the witnesses heard so far rule out, but that aren't struck yet. */
  outstanding() {
    const ff = this.model.firstFail, r = this.g.revealed, victim = this.model.caseData.victim;
    let n = 0;
    for (let i = 0; i < ff.length; i++) if (ff[i] < r && !this.marks[i] && i !== victim) n++;
    return n;
  }

  /** Once every name the evidence rules out is struck, call the next witness(es). */
  checkWitnesses() {
    if (this.g.solved || this.g.revealed >= this.rules.length || this.outstanding()) return;
    const heard = [];
    while (this.g.revealed < this.rules.length && !this.outstanding()) heard.push(this.g.revealed++);
    this.save();
    this.renderCasebook();
    this.renderTray();
    this.render();
    this.setPen(heard[heard.length - 1] + 1);
    const done = this.g.revealed >= this.rules.length;
    modal({
      title: heard.length > 1 ? 'Witnesses come forward' : 'A witness comes forward',
      body: heard.map(k => {
        const r = this.rules[k];
        return `<div class="witness-card" style="--c:${hexOf(this.g.penColors[k + 1])}"><div class="wc-head"><b>${ROMAN_UP(k + 1)}</b> ${esc(r.source)} <span>· ${esc(clueLabel(r))}</span></div><p class="wc-quote">${esc(r.quote)}</p><p class="wc-text">${esc(r.text)}</p></div>`;
      }).join('') + `<p class="muted">${done ? 'That is the last of the witnesses.' : `Witness ${this.g.revealed} of ${this.rules.length}.`} Their highlighter is ready.</p>`,
      actions: [{ label: `Back to the ${this.model.word}`, primary: true }],
    });
  }

  // ── find ─────────────────────────────────────────────────────────────────
  /** Entries whose first name, surname or full name starts with the query (accents ignored), in Register order. */
  searchNames(q, limit = 20) {
    q = letters(q);
    if (!q) return { list: [], total: 0 };
    const list = [];
    let total = 0;
    for (const e of this.model.book.entries) {
      if (e.first.lower.startsWith(q) || e.last.lower.startsWith(q) || e.full.lower.startsWith(q)) { total++; if (list.length < limit) list.push(e); }
    }
    return { list, total };
  }

  find() {
    modal({
      title: 'Find a name',
      body: `<input class="input" autofocus placeholder="A first name, a surname, or both…" spellcheck="false" autocomplete="off"><ul class="results"></ul><p class="muted results-more"></p><p class="muted small-print">People are listed in the order they appear in the ${esc(this.model.word)}.</p>`,
      onOpen: (root, close) => {
        const inp = $('input', root), ul = $('.results', root), more = $('.results-more', root);
        let res = [];
        const draw = () => {
          const r = this.searchNames(inp.value);
          res = r.list;
          ul.innerHTML = res.map((e, k) => `<li><button data-k="${k}" class="${k === 0 ? 'first' : ''}"><b>${e.name}</b><span>page ${e.page} · line ${e.line}${this.marks[e.i] ? ' · struck' : ''}${e.i === this.model.caseData.victim ? ' · the victim' : ''}</span></button></li>`).join('') ||
            (inp.value.trim() ? `<li class="none">No one by that name is in the ${esc(this.model.word)}.</li>` : '');
          more.textContent = r.total > res.length ? `Showing ${res.length} of ${fmt(r.total)} — keep typing to narrow it down.` : '';
        };
        inp.addEventListener('input', draw);
        const go = e => { close(); this.goTo(this.model.seqOfEntry(e.i), e.i); };
        inp.addEventListener('keydown', ev => { if (ev.key === 'Enter' && res[0]) go(res[0]); });
        ul.addEventListener('click', ev => { const b = ev.target.closest('[data-k]'); if (b) go(res[+b.dataset.k]); });
      },
    });
  }

  // ── strike by position: pages, columns and lines ────────────────────────
  markPagesDialog() {
    if (this.g.solved) return toast('This case is closed.');
    const { pageCount, cols } = this.model.book;
    const parse = (s, max, what) => {
      const out = new Set();
      for (const part of s.replace(/\s*[-–]\s*/g, '-').split(/[,\s]+/).filter(Boolean)) {
        const m = part.match(/^(\d+)(?:[-–](\d+))?$/);
        if (!m) return { error: `“${part}” isn’t a ${what} or a range like 12–15.` };
        const a = +m[1], b = m[2] ? +m[2] : a;
        if (a < 1 || b > max || a > b) return { error: `${what[0].toUpperCase() + what.slice(1)}s run from 1 to ${max}.` };
        for (let p = a; p <= b; p++) out.add(p);
      }
      return { set: out.size ? out : null };
    };
    const pen = this.g.activePen;
    const colNames = cols === 3 ? ['Left', 'Middle', 'Right'] : ['Left', 'Right'];
    const read = root => {
      const pages = parse($('.pos-pages', root).value, pageCount, 'page');
      const lines = parse($('.pos-lines', root).value, 25, 'line');
      const colSet = new Set($$('.pos-col:checked', root).map(c => +c.value));
      const error = pages.error || lines.error || (!colSet.size ? 'Choose at least one column.' : null);
      if (error) return { error };
      const ids = this.model.book.entries.filter(e => (!pages.set || pages.set.has(e.page)) && (!lines.set || lines.set.has(e.line)) && colSet.has(e.col)).map(e => e.i);
      return { ids, any: !!(pages.set || lines.set || colSet.size < cols) };
    };
    modal({
      title: 'Strike by position',
      body: `<p class="muted">Leave a box empty to mean “all”. Every unmarked name that matches is struck with <b class="pen-inline" style="--c:${hexOf(this.g.penColors[pen])}">${this.penName(pen)}</b>; names already struck keep their color.</p>
        <label class="pos-field"><span>Pages</span><input class="input pos-pages" autofocus placeholder="e.g. 2, 3, 5, 7, 11–13" spellcheck="false"></label>
        <label class="pos-field"><span>Lines</span><input class="input pos-lines" placeholder="e.g. 4, 8, 12, 16, 20, 24" spellcheck="false"></label>
        <div class="pos-field"><span>Columns</span><div class="pos-cols">${colNames.map((n, k) => `<label class="check"><input type="checkbox" class="pos-col" value="${k + 1}" checked> ${n}</label>`).join('')}</div></div>
        <p class="pages-preview muted"></p>
        <label class="check"><input type="checkbox" class="clear-mode"> Clear these names instead</label>`,
      actions: [{ label: 'Cancel' }, {
        label: 'Apply', primary: true, onClick: (close, root) => {
          const r = read(root);
          if (r.error || !r.any) { $('.pages-preview', root).textContent = r.error || 'Give some pages, lines or columns first.'; return; }
          close();
          if ($('.clear-mode', root).checked) this.clearIndices(r.ids, 'Cleared by position');
          else this.strikeIndices(r.ids, 'Struck by position');
        },
      }],
      onOpen: root => {
        const pv = $('.pages-preview', root);
        const update = () => {
          const r = read(root);
          const clear = $('.clear-mode', root).checked;
          if (r.error) { pv.textContent = r.error; return; }
          if (!r.any) { pv.textContent = ''; return; }
          const victim = this.model.caseData.victim;
          const n = r.ids.filter(i => i !== victim && (clear ? this.marks[i] : !this.marks[i])).length;
          pv.textContent = `${fmt(n)} ${clear ? 'marked' : 'unmarked'} name${n === 1 ? '' : 's'} match.`;
        };
        root.addEventListener('input', update);
        root.addEventListener('change', update);
      },
    });
  }

  // ── the Sergeant (hints) ─────────────────────────────────────────────────
  sergeant() {
    const killer = this.model.killer();
    modal({
      title: 'Sergeant Pruitt clears their throat',
      body: `<p class="muted">The Sergeant has read the evidence too. Each question counts as a hint taken.</p>
        <div class="sg-options">
          <button class="btn" data-q="killer">“Have I struck out the killer by mistake?”</button>
          <button class="btn" data-q="audit">“Check my markings against the clues I tagged them with.”</button>
        </div><div class="sg-answer"></div>`,
      actions: [{ label: 'Thank you, Sergeant', primary: true }],
      onOpen: (root, close) => {
        const ans = $('.sg-answer', root);
        root.addEventListener('click', ev => {
          const b = ev.target.closest('[data-q]');
          if (!b) return;
          this.g.hints++; this.save();
          if (b.dataset.q === 'killer') {
            ans.innerHTML = this.marks[killer.i]
              ? '<p class="verdict bad">“I’m afraid so. One of the names you’ve struck is the killer. Somewhere, a clue was misread.”</p>'
              : `<p class="verdict good">“No — the killer is still standing among your ${fmt(this.remaining)} remaining names.”</p>`;
          } else {
            const bad = [];
            this.marks.forEach((p, i) => { if (p && p !== PENCIL && i !== this.model.caseData.victim && p <= this.rules.length && !this.model.clears(p - 1, i)) bad.push(i); });
            const pencil = this.penCounts[PENCIL] || 0;
            ans.innerHTML = bad.length
              ? `<p class="verdict bad">“${fmt(bad.length)} name${bad.length > 1 ? 's are' : ' is'} struck with a clue that doesn’t actually clear them.${pencil ? ` (I can’t vouch for the ${fmt(pencil)} in pencil.)` : ''}”</p>
                 <button class="btn small" data-show>Outline them in the book</button>`
              : `<p class="verdict good">“Every tagged mark checks out.${pencil ? ` The ${fmt(pencil)} in pencil I can’t vouch for.` : ''}”</p>`;
            const show = $('[data-show]', ans);
            if (show) show.onclick = () => {
              this.flagged = new Set(bad);
              close();
              this.goTo(this.model.seqOfEntry(bad[0]));
              toast(`Outlined ${fmt(bad.length)} doubtful mark${bad.length > 1 ? 's' : ''}, starting on page ${this.model.book.entries[bad[0]].page}. Re-mark them to clear the outline.`, { ms: 7000 });
            };
          }
        });
      },
    });
  }

  // ── accusation ───────────────────────────────────────────────────────────
  accuse(preset) {
    if (this.g.solved) return this.showSolved();
    const entries = this.model.book.entries;
    const standing = this.remaining <= 40 ? entries.filter(e => !this.marks[e.i] && e.i !== this.model.caseData.victim) : null;
    let chosen = preset !== undefined ? entries[preset] : (standing?.length === 1 ? standing[0] : null);
    modal({
      title: 'Make an accusation',
      className: 'accuse-modal',
      body: `<p class="muted">Name the killer. ${this.g.accusations.length ? `You have made ${this.g.accusations.length} accusation${this.g.accusations.length > 1 ? 's' : ''} so far.` : 'A wrong accusation is not fatal — but it goes on the record.'}</p>
        ${standing ? `<div class="standing"><div class="cm-label">Still standing (${standing.length})</div>${standing.map(e => `<button data-i="${e.i}">${e.name}<span>p. ${e.page}, l. ${e.line}</span></button>`).join('')}</div>` : ''}
        <input class="input" placeholder="${this.compact ? 'Type a name…' : 'Type a name, then pick the right page and line…'}" spellcheck="false" autocomplete="off" ${standing ? '' : 'autofocus'}>
        <ul class="results"></ul>
        <div class="accused"></div>`,
      actions: [{ label: 'Not yet' }, {
        label: 'I accuse…', primary: true, onClick: close => {
          if (!chosen) return toast('Choose a name first.');
          close(); this.resolveAccusation(chosen);
        },
      }],
      onOpen: root => {
        const inp = $('input', root), ul = $('.results', root), acc = $('.accused', root);
        const pick = e => {
          chosen = e;
          acc.innerHTML = e ? `<div class="accused-card"><span class="ac-name">${e.name}</span><span>page ${e.page}, line ${e.line}${this.marks[e.i] ? ' — <em>you have struck this name</em>' : ''}</span></div>` : '';
          $$('.standing button', root).forEach(b => b.classList.toggle('on', e && +b.dataset.i === e.i));
        };
        pick(chosen);
        let res = [];
        inp.addEventListener('input', () => {
          res = this.searchNames(inp.value, 9).list.filter(e => e.i !== this.model.caseData.victim).slice(0, 8);
          ul.innerHTML = res.map(e => `<li><button data-i="${e.i}"><b>${e.name}</b><span>page ${e.page}, line ${e.line}${this.marks[e.i] ? ' · struck' : ''}</span></button></li>`).join('');
          // A single match is the pick; otherwise choose a page and line from the list.
          pick(res.length === 1 ? res[0] : null);
        });
        inp.addEventListener('keydown', ev => { if (ev.key === 'Enter' && res[0]) { pick(res[0]); ul.innerHTML = ''; inp.value = res[0].name; } });
        root.addEventListener('click', ev => {
          const b = ev.target.closest('[data-i]');
          if (b) { pick(entries[+b.dataset.i]); ul.innerHTML = ''; inp.value = entries[+b.dataset.i].name; }
        });
      },
    });
  }

  resolveAccusation(e) {
    const killer = this.model.killer();
    const correct = e.i === killer.i;
    this.g.accusations.push({ i: e.i, at: Date.now(), correct });
    if (correct) {
      this.g.solved = { at: Date.now() };
      this.save.flush();
      track('case_solved', this.g);
      this.el.game.classList.add('solved');
      // Case closed: every witness's statement is now on the record.
      this.renderCasebook();
      this.renderTray();
      this.render();
      return this.showSolved(true);
    }
    this.save();
    const alibi = ALIBIS[(e.i * 7 + this.g.accusations.length) % ALIBIS.length];
    modal({
      title: 'An alibi',
      body: `<p class="lead">${e.name} was ${alibi} that night. The Inspector releases them with an apology.</p>
        <p class="muted">At least one clue clears ${e.name}. Want to know which?</p><div class="alibi-hint"></div>`,
      actions: [{ label: this.inquiry ? 'Which witness clears them? (hint)' : 'Show me the clue (hint)', onClick: (close, root) => {
        const k = this.model.firstFailingRule(e.i);
        this.g.hints++; this.save();
        $('.modal-actions .btn', root)?.remove();
        if (k >= this.shown) {
          // Don't spoil a witness who hasn't been heard yet.
          $('.alibi-hint', root).innerHTML = `<div class="clue-mini" style="--c:var(--line-2)"><b>A witness yet to come forward</b> will clear ${e.name}. Keep striking.</div>`;
          return;
        }
        const pen = k + 1;
        $('.alibi-hint', root).innerHTML = `<div class="clue-mini" style="--c:${hexOf(this.g.penColors[pen])}"><b>Clue ${ROMAN_UP(pen)}</b> ${esc(this.rules[k].text)}</div>
          <button class="btn small" data-strike>Strike ${e.name} with clue ${ROMAN_UP(pen)}</button>`;
        $('[data-strike]', root).onclick = () => { const ch = []; this.set(e.i, pen, ch); this.commit(ch); close(); this.goTo(this.model.seqOfEntry(e.i), e.i); };
      } }, { label: `Back to the ${this.model.word}`, primary: true }],
    });
  }

  showSolved(fresh = false) {
    const k = this.model.killer();
    const paras = renderSolution(this.model);
    const g = this.g;
    modal({
      title: fresh ? 'Case closed' : 'This case is closed',
      wide: true,
      className: 'solved-modal',
      body: `<div class="solved-name">${k.name}</div>
        ${paras.map(p => `<p>${esc(p)}</p>`).join('')}
        <dl class="stats inline"><dt>Time on the case</dt><dd>${duration(g.timePlayed)}</dd><dt>Accusations</dt><dd>${g.accusations.length}</dd><dt>Hints</dt><dd>${g.hints}</dd><dt>Names struck</dt><dd>${fmt(this.struck)}</dd></dl>`,
      actions: [
        ...(HUB && !g.posted ? [{ label: 'Post to the leaderboard', primary: true, onClick: (close, root) => this.postToLeaderboard(close, root) }] : []),
        { label: 'View the Register', value: 'view' },
        { label: 'Back to Case Files', primary: !HUB || !!g.posted, value: 'home' },
      ],
      onOpen: root => { if (HUB && g.posted) $('.modal-body', root).insertAdjacentHTML('beforeend', postedNote(g.posted)); },
    }).then(v => { if (v === 'home') this.onExit(); else this.goTo(this.model.seqOfEntry(k.i), k.i); });
  }

  /** Hub only: post this solve; if signed out, keep it and send the player to sign in. */
  async postToLeaderboard(close, root) {
    const btn = [...root.querySelectorAll('.modal-actions .btn')].find(b => /^(Post|Try posting)/.test(b.textContent));
    if (btn) { btn.disabled = true; btn.textContent = 'Posting…'; }
    const score = scoreFor(this.g, this.model.killer().i, this.model.caseData.engine);
    const res = await postScore(score);
    if (res.status === 401) {
      pending.set(score);
      close();
      return modal({
        title: 'Sign in to post your time',
        body: `<p>Your time on this case is saved here. Sign in, or create an account, and it goes up on the leaderboard as soon as you’re back.</p>`,
        actions: [{ label: 'Not now' }, { label: 'Create an account', onClick: () => { location.href = signInUrl('signup'); } }, { label: 'Sign in', primary: true, onClick: () => { location.href = signInUrl('login'); } }],
      });
    }
    if (!res.ok) {
      // 202: the hub is still checking this case; the same button tries again.
      if (btn) { btn.disabled = false; btn.textContent = res.status === 202 ? 'Try posting again' : 'Post to the leaderboard'; }
      return toast(esc(res.error || 'That score couldn’t be posted.'));
    }
    this.g.posted = { time: res.time, points: res.points, rank: res.rank ?? null };
    this.save.flush();
    btn?.remove();
    $('.modal-body', root).insertAdjacentHTML('beforeend', postedNote(this.g.posted, res.url, res.of));
  }

  // ── help ─────────────────────────────────────────────────────────────────
  showHelp(first = false) {
    if (this.compact) return this.showTouchHelp(first);
    modal({
      title: first ? 'Welcome to the Register' : 'How to play',
      wide: true,
      body: `<div class="help">
        <ol class="howto">
          <li><b>Read the evidence.</b> The Casebook on the left lists ${this.inquiry ? 'the witnesses heard so far — in a Live Investigation, the next one comes forward only once you’ve struck every name the evidence so far rules out' : 'every clue'}. Each statement is true of the killer, so any name that breaks even one is innocent.</li>
          <li><b>Strike the innocent.</b> Pick a clue’s highlighter, then click or drag across names to strike them. Start with the clues about stretches of the Register: find the people they name, then strike the run between them. Then work name by name.</li>
          <li><b>Accuse.</b> When one name is left standing, accuse them by page and line — names repeat. A wrong accusation costs nothing but your pride.</li>
        </ol>
        <div class="keys">
          <div><kbd>←</kbd> <kbd>→</kbd> turn pages</div><div><kbd>[</kbd> <kbd>]</kbd> previous / next chapter</div>
          <div><kbd>1</kbd>–<kbd>0</kbd> clues I–X · <kbd>⇧1</kbd>–<kbd>⇧7</kbd> clues XI–XVII</div><div><kbd>&#96;</kbd> or <kbd>.</kbd> pencil (reason undecided)</div>
          <div>Click a struck name again to clear it</div><div><kbd>⇧</kbd>-click strike a whole run of names</div>
          <div><kbd>⌥</kbd>-drag recolor marks you drag over</div><div>Right-click a name to start or end a run, and more</div>
          <div><kbd>⌘Z</kbd> / <kbd>⇧⌘Z</kbd> undo / redo</div><div><kbd>/</kbd> find a name · <kbd>G</kbd> go to page</div>
          <div><kbd>P</kbd> strike by page, column and line</div><div><kbd>C</kbd> Casebook · <kbd>V</kbd> one or two pages</div>
          <div><kbd>+</kbd> / <kbd>−</kbd> zoom · <kbd>Z</kbd> zoom in / fit</div><div>Pinch the trackpad to zoom; scroll to pan</div>
        </div>
        <p class="muted">Your progress saves itself after every mark. You can close the window at any time and pick up where you left off.</p>
      </div>`,
      actions: [{ label: first ? 'Open the Register' : 'Back to work', primary: true }],
    });
  }

  showTouchHelp(first) {
    modal({
      title: first ? 'Welcome to the Register' : 'How to play',
      body: `<div class="help">
        <ol class="howto">
          <li><b>Read the evidence.</b> The active clue sits above the page; tap it to see ${this.inquiry ? 'every witness heard so far. The next one comes forward only once you’ve struck every name the evidence so far rules out' : 'every clue'}. Each statement is true of the killer, so any name that breaks even one is innocent.</li>
          <li><b>Strike the innocent.</b> Choose a clue’s highlighter from the row at the bottom, then tap names to strike them; tap again to clear. Start with the clues about stretches of the Register: find the people they name, then strike the run between them. <b>Strike</b> buttons take a whole column or page at once.</li>
          <li><b>Accuse.</b> When one name is left standing, accuse them by page and line — names repeat.</li>
        </ol>
        <ul class="touch-tips"><li>Swipe sideways, or use ‹ ›, to turn pages. Tap the page number to jump.</li><li>Long-press a name to strike it with any clue, to start or finish a run of names (even across pages), or to accuse.</li><li>↶ undoes; ⋯ has Strike by position, the Sergeant’s hints and more.</li></ul>
        <p class="muted">Your progress saves itself after every mark. A bigger screen shows the pages as printed, two at a time.</p>
      </div>`,
      actions: [{ label: first ? 'Open the Register' : 'Back to work', primary: true }],
    });
  }

  // ── print ────────────────────────────────────────────────────────────────
  print() {
    openPrintDialog(this.model, { marks: this.marks, penColors: this.g.penColors, revealed: this.shown, solved: !!this.g.solved, strike: !!this.g.view.strike, currentSeq: this.visible().filter(v => v !== null) });
  }

  // ── persistence & clock ──────────────────────────────────────────────────
  snapshot() {
    this.g.marks = bytesToB64(this.marks);
    this.g.remaining = this.remaining;
    this.g.total = this.model.book.entries.length;
    this.g.struck = this.struck;
    this.g.updatedAt = Date.now();
    this.g.baseUpdatedAt = this.baseUpdatedAt;
    this.g.writer = this.writer;
    return this.g;
  }

  async persist(keepalive = false) {
    if (keepalive) {
      // visibilitychange and pagehide both fire on close; one exit save is enough.
      if (Date.now() - (this.lastKeepalive || 0) < 1500) return;
      this.lastKeepalive = Date.now();
    } else if (this.saving) { this.saveAgain = true; return; }
    this.saving = true;
    this.setSaveState('saving');
    try {
      const snap = this.snapshot();
      const stamp = snap.updatedAt;
      await api.putGame(snap, { keepalive });
      this.baseUpdatedAt = Math.max(this.baseUpdatedAt || 0, stamp);
      this.setSaveState('saved');
    } catch (e) {
      this.setSaveState(e.status === 409 ? 'conflict' : 'offline');
    } finally {
      this.saving = false;
      if (this.saveAgain) { this.saveAgain = false; this.save(); }
    }
  }

  setSaveState(s) {
    if (!this.el?.saveState) return;
    this.el.saveState.dataset.state = s;
    this.el.saveState.textContent = { saved: 'Saved', saving: 'Saving…', offline: IN_BROWSER ? 'Couldn’t save to this browser — kept in this window' : 'Server unreachable — kept in this window', conflict: 'Another window saved newer progress — reload to continue from it' }[s];
  }

  startClock() {
    let last = Date.now();
    const bump = () => (last = Date.now());
    for (const ev of ['pointerdown', 'keydown', 'wheel']) this.on(window, ev, bump, { passive: true });
    this.clock = setInterval(() => {
      if (this.g.solved || document.visibilityState !== 'visible' || Date.now() - last > 180000) return;
      this.g.timePlayed += 5;
      const tp = $('.time-played', this.root);
      if (tp) tp.textContent = duration(this.g.timePlayed);
      if (this.g.timePlayed % 60 === 0) this.save();
    }, 5000);
  }
}
