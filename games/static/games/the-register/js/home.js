import { $, $$, h, esc, fmt, duration, timeAgo, modal, toast } from './util.js';
import { api, IN_BROWSER } from './api.js';
import { DIFFICULTIES, ENGINE_VERSION, MODES, STYLES, DEFAULT_MODE } from '../engine/generator.js';
import { SETTING } from '../engine/settings.js';
import { clueLabel } from '../engine/rules.js';
import { ROMAN_UP } from './model.js';
import { normalizeCaseCode, newCaseCode } from '../engine/rng.js';
import { createCase, unusedCase, newGameFor, caseId, prepareSpare } from './cases.js';

// Where saves live, for messages that would otherwise blame a server the player doesn't have.
const UNREACHABLE = IN_BROWSER ? 'Can’t open this browser’s storage. Is it in private browsing mode?' : 'Can’t reach the local server. Is it running?';
const RETRY_HINT = IN_BROWSER ? 'Try again in a moment.' : 'Is the local server still running?';
const BACKUP_KIND = 'the-register/backup';

/** Suspects in a saved game: everyone but the victim. Games before engine 7 had 26,000 names. */
const suspects = g => (g.total || 26000) - 1;

export class Home {
  constructor(root, { openGame, showLoading, hideLoading }) {
    Object.assign(this, { root, openGame, showLoading, hideLoading });
  }

  async mount() {
    this.root.innerHTML = '';
    let index = { cases: [], games: [] };
    try { index = await api.index(); } catch { toast(UNREACHABLE); }
    this.index = index;
    const games = [...index.games].sort((a, b) => b.updatedAt - a.updatedAt);
    const current = games.find(g => !g.solved);
    this.root.append(h(`<div class="home">
      <div class="home-grid">
        <div class="brand">
          <div class="brand-kicker">A murder mystery in 26,000 to 52,000 names</div>
          <h1 class="brand-title">The Register</h1>
          <p class="brand-sub">Somewhere among tens of thousands of names — on a liner’s manifest, in a mining town’s census, at a sold-out festival — is a killer. You have the register and a handful of clues. Strike out the innocent, one clue at a time, until a single name is left.</p>
          <div class="home-actions">
            ${current ? `<button class="continue-card" data-open="${current.id}">
                <span class="cc-kicker">Continue</span>
                <span class="cc-title">${esc(current.title)}</span>
                <span class="cc-meta">${MODES[current.mode || 'cold'].label} · ${DIFFICULTIES[current.difficulty]?.label} · ${fmt(current.remaining ?? suspects(current))} suspects remain · ${duration(current.timePlayed)} on the case · opened ${timeAgo(current.updatedAt)}</span>
                <span class="cc-bar"><i style="--p:${((current.struck || 0) / suspects(current)).toFixed(4)}"></i></span>
              </button>` : ''}
            <button class="btn ${current ? '' : 'primary'} big" data-act="new">${games.length ? 'Open a new case' : 'Open your first case'}</button>
          </div>
          <p class="credit">Inspired by <cite>The Killer Isn’t Alice</cite> by Iris Starling, the puzzle book that started it all. The Register is a free fan game. It is unofficial, and is not affiliated with, endorsed by or connected to the book, its author or its publisher.</p>
        </div>
        <div class="cover" aria-hidden="true"><div class="cover-inner"><div class="cv-rule"></div><div class="cv-kicker">One register</div><div class="cv-title">The<br>Register</div><div class="cv-num">One killer</div><div class="cv-rule"></div></div></div>
      </div>
      <section class="files">
        <div class="files-head"><h2>Case files</h2><div class="files-tools"><button class="btn ghost small" data-act="by-code">Open a case by number…</button><button class="btn ghost small" data-act="backup" title="Save every case file to a file you keep">Back up</button><button class="btn ghost small" data-act="restore" title="Bring case files back from a backup file">Restore…</button></div></div>
        ${games.length ? `<ul class="file-list">${games.map(g => this.fileRow(g)).join('')}</ul>` : '<p class="muted empty">No cases yet. Open your first one above. A register of 26,000 people will be written for you in a second or two.</p>'}
      </section>
      <footer class="home-foot"><span class="spare-status"></span><span>${IN_BROWSER ? 'Saved automatically in this browser. Nothing is sent anywhere — use Back up to keep a copy or move to another device.' : 'Saved automatically to this computer. Nothing leaves it.'}</span>${document.documentElement.dataset.back ? `<a class="home-back" href="${esc(document.documentElement.dataset.back)}">← More games</a>` : ''}</footer>
    </div>`));
    this.root.addEventListener('click', this.onClick = e => this.click(e));
    this.spareStatus(unusedCase(index, 'classic', DEFAULT_MODE) ? 'ready' : 'idle');
  }

  destroy() { this.root.removeEventListener('click', this.onClick); }

  fileRow(g) {
    const pct = Math.min(1, (g.struck || 0) / suspects(g));
    return `<li class="file ${g.solved ? 'is-solved' : ''}">
      <button class="file-main" data-open="${g.id}">
        <span class="f-title">${esc(g.title)}</span>
        <span class="f-meta"><span class="pill">${MODES[g.mode || 'cold'].label}</span> <span class="pill">${DIFFICULTIES[g.difficulty]?.label}</span>${g.setting && SETTING[g.setting] ? ` ${esc(SETTING[g.setting].label)} ·` : ''} No. ${esc(g.code)} · ${g.solved ? `Solved ✓ in ${duration(g.timePlayed)}` : `${fmt(g.remaining ?? suspects(g))} suspects remain · ${duration(g.timePlayed)}`} · ${timeAgo(g.updatedAt)}</span>
        <span class="f-bar"><i style="--p:${g.solved ? 1 : pct.toFixed(4)}"></i></span>
      </button>
      <button class="btn ghost small" data-report="${g.caseId}" title="How this case was built and checked">Case report</button>
      <button class="btn ghost small danger-text" data-delete="${g.id}" title="Delete this game">Delete</button>
    </li>`;
  }

  spareStatus(s) {
    const el = $('.spare-status', this.root);
    if (el) el.textContent = { ready: 'A fresh case is waiting on the desk.', busy: 'Preparing the next case in the background…', idle: '' }[s];
  }

  async click(e) {
    const open = e.target.closest('[data-open]');
    if (open) return this.openGame(open.dataset.open);
    const del = e.target.closest('[data-delete]');
    if (del) return this.deleteGame(del.dataset.delete);
    const rep = e.target.closest('[data-report]');
    if (rep) return this.caseReport(rep.dataset.report);
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'new') return this.newCase();
    if (act === 'by-code') return this.byCode();
    if (act === 'backup') return this.backup();
    if (act === 'restore') return this.restore();
  }

  async newCase() {
    // The Inquiry by default; after that, whichever mode the player chose last.
    let mode = DEFAULT_MODE;
    try { mode = localStorage.getItem('register:mode') || DEFAULT_MODE; } catch { /* storage blocked */ }
    if (!MODES[mode]) mode = DEFAULT_MODE;
    const choice = await modal({
      title: 'Open a new case',
      wide: true,
      body: `<div class="mode-grid">${Object.entries(MODES).map(([k, m]) => `<button class="mode ${k === mode ? 'on' : ''}" data-mode="${k}"><span class="d-name">${m.label}</span><span class="d-blurb">${m.blurb}</span></button>`).join('')}</div>
        <div class="diff-grid">${Object.entries(DIFFICULTIES).map(([k, d]) => `<button class="diff ${k === 'classic' ? 'rec' : ''}" data-diff="${k}"><span class="d-name">${d.label}</span><span class="d-blurb">${d.blurb}</span><span class="d-meta">${fmt(d.names)} names · ${d.clues[0] === d.clues[1] ? d.clues[0] : `${d.clues[0]}–${d.clues[1]}`} clues</span></button>`).join('')}</div>
        <p class="muted small-print">Each case is set somewhere new — a liner’s manifest, a mining-town census, a festival’s wristband register — and leans on its own mix of evidence, so no two read alike.</p>`,
      onOpen: (root, close) => root.addEventListener('click', ev => {
        const m = ev.target.closest('[data-mode]');
        if (m) { mode = m.dataset.mode; $$('[data-mode]', root).forEach(b => b.classList.toggle('on', b === m)); return; }
        const b = ev.target.closest('[data-diff]');
        if (b) close({ difficulty: b.dataset.diff, mode });
      }),
    });
    if (!choice) return;
    try { localStorage.setItem('register:mode', choice.mode); } catch { /* storage blocked */ }
    this.startCase(choice.difficulty, null, choice.mode);
  }

  async startCase(difficulty, code = null, mode = 'cold') {
    try {
      const index = await api.index();
      let rec = null;
      if (code) {
        const id = caseId(code, difficulty, mode);
        const stored = index.cases.find(c => c.id === id);
        if (stored && stored.engine !== ENGINE_VERSION) {
          // Replacing it would break games already played on it.
          return modal({ title: 'An older edition of that case', body: `<p>Case ${esc(code)} (${DIFFICULTIES[difficulty].label}) was written by an earlier version of the Register, so it differs from what that number produces today. Your copy is kept as it was. Ask your friend for a newer case number to compare notes.</p>`, actions: [{ label: 'OK', primary: true }] });
        }
        if (stored) rec = await api.getCase(id);
      } else {
        const spare = unusedCase(index, difficulty, mode);
        if (spare) rec = await api.getCase(spare.id);
      }
      if (!rec) {
        this.showLoading('Preparing the case', 'Choosing a setting');
        rec = await createCase(code || newCaseCode(), difficulty, mode, p => this.showLoading(null, p.label, p.phase === 'names' ? p.p * 0.6 : 0.6 + (p.p || 0) * 0.4));
      }
      const g = await newGameFor(rec);
      this.hideLoading();
      this.openGame(g.id);
      setTimeout(() => prepareSpare(difficulty, mode), 4000);
    } catch (err) {
      this.hideLoading();
      modal({ title: 'The presses jammed', body: `<p>${esc(err.message)}</p><p class="muted">${RETRY_HINT}</p>`, actions: [{ label: 'OK', primary: true }] });
    }
  }

  async byCode() {
    const res = await modal({
      title: 'Open a case by number',
      body: `<p class="muted">Every case has a number, such as <code>B7K2-QX9M</code>. Anyone running this same version of the Register who enters the number, mode and difficulty gets the identical case: the same names, clues and killer. That makes it easy to race a friend.</p>
        <div class="row"><input class="input code-input" autofocus placeholder="XXXX-XXXX" spellcheck="false" autocomplete="off" maxlength="9">
        <select class="input mode-select">${Object.entries(MODES).map(([k, m]) => `<option value="${k}">${m.label}</option>`).join('')}</select>
        <select class="input diff-select">${Object.entries(DIFFICULTIES).map(([k, d]) => `<option value="${k}" ${k === 'classic' ? 'selected' : ''}>${d.label}</option>`).join('')}</select></div>
        <p class="code-err bad"></p>`,
      actions: [{ label: 'Cancel' }, { label: 'Open case', primary: true, onClick: (close, root) => {
        const code = normalizeCaseCode($('.code-input', root).value);
        if (!code) { $('.code-err', root).textContent = 'Case numbers are eight letters and digits, like B7K2-QX9M.'; return; }
        close({ code, difficulty: $('.diff-select', root).value, mode: $('.mode-select', root).value });
      } }],
    });
    if (res) this.startCase(res.difficulty, res.code, res.mode);
  }

  async deleteGame(id) {
    const g = this.index.games.find(x => x.id === id);
    const ok = await modal({
      title: 'Delete this game?',
      body: `<p>Your progress on <b>${esc(g.title)}</b> will be permanently deleted: ${fmt(g.struck || 0)} struck names and your time. You can't undo this. You can still replay the same case later using its number, <code>${esc(g.code)}</code>.</p>`,
      actions: [{ label: 'Keep it', value: false }, { label: 'Delete', danger: true, value: true }],
    });
    if (!ok) return;
    try { await api.deleteGame(id); } catch { return toast(`Couldn’t delete it. ${RETRY_HINT}`); }
    this.destroy();
    this.mount();
  }

  async caseReport(id) {
    let c;
    try { c = await api.getCase(id); } catch { return toast('That case file is missing from the archive.'); }
    modal({
      title: `Case report · ${esc(c.code)}`,
      wide: true,
      body: `<p class="muted">${esc(c.title)} · ${MODES[c.mode || 'cold'].label} · ${DIFFICULTIES[c.difficulty].label} · ${fmt(c.names?.length || 26000)} names${c.style && STYLES[c.style] ? ` · ${esc(STYLES[c.style].label)}: ${esc(STYLES[c.style].blurb)}` : ''} · generated ${new Date(c.createdAt).toLocaleString()}${c.stats ? ` in ${(c.stats.ms / 1000).toFixed(1)}s (${c.stats.attempts} attempt${c.stats.attempts > 1 ? 's' : ''})` : ''}.</p>
        <ul class="checks">${(c.validation?.checks || []).map(k => `<li class="${k.ok ? 'ok' : 'bad'}"><span>${k.ok ? '✓' : '✗'}</span><div><b>${esc(k.label)}</b>${k.detail ? `<em>${esc(k.detail)}</em>` : ''}</div></li>`).join('')}</ul>
        ${c.stats ? `<p class="muted">${c.rules.length} ${c.mode === 'inquiry' ? 'witnesses, in the order they come forward' : 'clues'} · ${c.stats.pageCount} pages${c.stats.sectionSurvivors ? ` · ${fmt(c.stats.sectionSurvivors)} suspects survive the section clues` : c.stats.broadSurvivors ? ` · ${fmt(c.stats.broadSurvivors)} suspects survive the four broad clues` : ''}.</p>` : ''}
        ${c.metrics ? `<table class="balance"><thead><tr><th></th><th>Type</th><th title="Share of all suspects this clue clears">Clears</th><th title="Names that no other clue clears">Only clue for</th><th title="Read in Casebook order: names newly cleared, and their share of those still standing">In order</th></tr></thead><tbody>
          ${c.rules.map((r, k) => { const p = c.metrics.perClue[k]; return `<tr><td>${ROMAN_UP(k + 1)}</td><td>${esc(clueLabel(r))}</td><td>${(p.clearShare * 100).toFixed(1)}%</td><td>${fmt(p.solo)}</td><td>${fmt(p.marginal)} <span class="muted">(${(p.marginalShare * 100).toFixed(0)}%)</span></td></tr>`; }).join('')}
        </tbody></table>
        <p class="muted">On average each suspect is cleared by ${c.metrics.meanClears.toFixed(1)} clues; ${(c.metrics.overlapShare * 100).toFixed(1)}% are cleared by ${c.metrics.overlapDepth} or more.</p>` : ''}`,
      actions: [
        ...(IN_BROWSER ? [{ label: 'Copy share link', onClick: () => this.copyShareLink(c) }] : []),
        { label: 'Close', primary: true },
      ],
    });
  }

  /** A link that opens this same case (same number, mode and difficulty) for anyone. */
  shareLink(c) {
    return `${location.origin}${location.pathname}#/open/${c.code}/${c.difficulty}/${c.mode || 'cold'}`;
  }

  async copyShareLink(c) {
    const link = this.shareLink(c);
    try { await navigator.clipboard.writeText(link); toast('Link copied. Anyone who opens it gets this exact case.'); }
    catch { modal({ title: 'Share this case', body: `<p class="muted">Anyone who opens this link gets this exact case.</p><input class="input share-link" readonly value="${esc(link)}">`, onOpen: root => $('.share-link', root).select(), actions: [{ label: 'Done', primary: true }] }); }
  }

  /** Arrived by a share link: pick up the game already on that case, or offer to open it. */
  async openShared(rawCode, difficulty, mode) {
    const code = normalizeCaseCode(rawCode || '');
    if (!code || !DIFFICULTIES[difficulty] || !MODES[mode]) return toast('That case link is incomplete.');
    const id = caseId(code, difficulty, mode);
    const mine = this.index.games.filter(g => g.caseId === id).sort((a, b) => b.updatedAt - a.updatedAt)[0];
    if (mine) return this.openGame(mine.id);
    const ok = await modal({
      title: `Case No. ${esc(code)}`,
      body: `<p>Someone has shared a case with you: <b>${MODES[mode].label}</b>, <b>${DIFFICULTIES[difficulty].label}</b>. You’ll get the same register, clues and killer they have.</p>`,
      actions: [{ label: 'Not now', value: false }, { label: 'Open the case', primary: true, value: true }],
    });
    if (ok) this.startCase(difficulty, code, mode);
  }

  async backup() {
    let games, cases;
    try {
      const index = await api.index();
      games = await Promise.all(index.games.map(g => api.getGame(g.id)));
      const ids = new Set(games.map(g => g.caseId));
      cases = await Promise.all([...ids].map(id => api.getCase(id).catch(() => null)));
    } catch { return toast(UNREACHABLE); }
    if (!games.length) return toast('No case files to back up yet.');
    const data = { kind: BACKUP_KIND, version: 1, savedAt: Date.now(), games, cases: cases.filter(Boolean) };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: `the-register-backup-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast(`Backed up ${games.length} case file${games.length > 1 ? 's' : ''}. Keep the file somewhere safe.`);
  }

  restore() {
    const input = Object.assign(document.createElement('input'), { type: 'file', accept: '.json,application/json' });
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      let data;
      try { data = JSON.parse(await file.text()); } catch { data = null; }
      if (data?.kind !== BACKUP_KIND || !Array.isArray(data.games) || !Array.isArray(data.cases)) return toast('That isn’t a Register backup file.');
      const index = await api.index().catch(() => null);
      if (!index) return toast(UNREACHABLE);
      const haveCase = new Set(index.cases.map(c => c.id));
      const have = new Map(index.games.map(g => [g.id, g]));
      let added = 0, kept = 0;
      for (const c of data.cases) if (c?.id && !haveCase.has(c.id)) await api.putCase(c).catch(() => {});
      for (const g of data.games) {
        if (!g?.id || !g.caseId) continue;
        // Never roll back progress: a game already here is replaced only by a newer copy of itself.
        if (have.has(g.id) && have.get(g.id).updatedAt >= g.updatedAt) { kept++; continue; }
        try { await api.putGame(g); added++; } catch { kept++; }
      }
      toast(added ? `Restored ${added} case file${added > 1 ? 's' : ''}${kept ? ` (${kept} already up to date)` : ''}.` : 'Everything in that backup is already here.');
      this.destroy();
      this.mount();
    };
    input.click();
  }
}
