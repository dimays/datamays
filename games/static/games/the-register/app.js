import { $, esc, modal, b64ToBytes } from './js/util.js';
import { defaultPenColors } from './js/pens.js';
import { api } from './js/api.js';
import { Home } from './js/home.js';
import { Game } from './js/game.js';
import { buildModel } from './js/model.js';
import { buildPrintRoot } from './js/print.js';
import { prepareSpare } from './js/cases.js';
import { DEFAULT_MODE } from './engine/generator.js';

const root = $('#app');
let screen = null;

function showLoading(title, label, p) {
  const el = $('#loading');
  el.hidden = false;
  if (title) $('.ld-title', el).textContent = title;
  if (label) $('.ld-label', el).textContent = label + '…';
  $('.ld-bar i', el).style.setProperty('--p', p ?? 0.05);
}
function hideLoading() { $('#loading').hidden = true; }

async function route() {
  screen?.destroy?.();
  screen = null;
  document.body.classList.remove('printing');
  const [, kind, id, extra] = location.hash.replace(/^#\/?/, '#/').split('/');
  if (kind === 'case' && id) return openGame(id);
  if (kind === 'print-test' && id) return printTest(id, extra);
  screen = new Home(root, { openGame: gid => { location.hash = `#/case/${gid}`; }, showLoading, hideLoading });
  document.title = 'The Register';
  await screen.mount();
  // A shared case link: #/open/<code>/<difficulty>/<mode>. Drop it from the address first so a reload doesn't re-ask.
  if (kind === 'open') {
    const [, , , , mode] = location.hash.split('/');
    history.replaceState(null, '', location.pathname + location.search + '#/');
    screen.openShared(id, extra, mode || 'cold');
  }
  // Keep a spare case ready so "New Case" never waits.
  setTimeout(() => prepareSpare('classic', DEFAULT_MODE, s => screen?.spareStatus?.(s)), 1500);
}

async function openGame(id) {
  showLoading('Opening the Register', 'Finding your place', 0.3);
  try {
    const game = await api.getGame(id);
    const caseData = await api.getCase(game.caseId);
    hideLoading();
    root.innerHTML = '';
    screen = new Game(root, { game, caseData, onExit: () => { location.hash = '#/'; } });
    screen.mount();
    document.title = `${caseData.title} · The Register`;
  } catch (e) {
    hideLoading();
    await modal({ title: 'That case file is missing', body: `<p>${esc(e.message)}</p>`, actions: [{ label: 'Back to Case Files', primary: true }] });
    location.hash = '#/';
  }
}

// Hidden route used to verify print layout: #/print-test/<caseId>[/<gameId>]
async function printTest(caseId, gameId) {
  const model = buildModel(await api.getCase(caseId));
  const seqs = [...model.seq.keys()];
  let opts = {};
  if (gameId) {
    const g = await api.getGame(gameId);
    opts = { marks: b64ToBytes(g.marks, model.book.entries.length), penColors: { ...defaultPenColors(model.caseData.rules.length), ...g.penColors }, solved: !!g.solved };
  }
  buildPrintRoot(model, seqs, opts);
  document.body.classList.add('printing');
  document.body.dataset.ready = String(seqs.length);
}

window.addEventListener('hashchange', route);
route();
