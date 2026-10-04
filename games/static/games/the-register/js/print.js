import { $, esc, fmt, modal, toast } from './util.js';
import { renderPage } from './pages.js';
import { penStyles } from './pens.js';

/** Fill #print-root with real Letter-sized pages for the given sequence indices. */
export function buildPrintRoot(model, seqs, { marks = null, penColors = {}, solved = false, strike = false, revealed } = {}) {
  const root = $('#print-root');
  root.classList.toggle('print-strike', !!strike && !!marks);
  root.innerHTML = `<style>${penStyles(penColors)}</style>`;
  const frag = document.createDocumentFragment();
  for (const s of seqs) frag.append(renderPage(model, s, { marks, solved, revealed, forPrint: true }));
  root.append(frag);
  return root;
}

export function openPrintDialog(model, opts) {
  const total = model.seq.length;
  const maxPage = model.book.pageCount;
  modal({
    title: 'Print the Register',
    body: `<div class="print-opts">
      <label class="radio"><input type="radio" name="what" value="all" checked> The whole book <span class="muted">— ${fmt(total)} pages</span></label>
      <label class="radio"><input type="radio" name="what" value="front"> The case and the evidence only <span class="muted">— ${model.frontCount} pages</span></label>
      <label class="radio"><input type="radio" name="what" value="range"> Register pages <input class="input tiny" name="from" value="1" inputmode="numeric"> to <input class="input tiny" name="to" value="${Math.min(maxPage, 40)}" inputmode="numeric"></label>
      <label class="radio"><input type="radio" name="what" value="current"> The pages open now</label>
      <hr>
      <label class="check"><input type="checkbox" name="marks" checked> Include my highlights</label>
      <div class="print-tip">
        <b>In the print dialog:</b> choose <b>US Letter</b>, portrait, scale <b>100%</b>. Turn <b>headers and footers off</b>, and turn <b>background graphics on</b> so highlights print. In Chrome, set Margins to <b>None</b>; the pages carry their own margins. Each screen page then prints as exactly one sheet.
      </div>
    </div>`,
    actions: [{ label: 'Cancel' }, {
      label: 'Print…', primary: true, onClick: (close, root) => {
        const what = $('input[name=what]:checked', root).value;
        let seqs;
        if (what === 'all') seqs = [...Array(total).keys()];
        else if (what === 'front') seqs = [...Array(model.frontCount).keys()];
        else if (what === 'current') seqs = opts.currentSeq;
        else {
          const a = parseInt($('input[name=from]', root).value, 10), b = parseInt($('input[name=to]', root).value, 10);
          if (!(a >= 1 && b <= maxPage && a <= b)) return toast(`Choose pages between 1 and ${maxPage}.`);
          seqs = [];
          for (let p = a; p <= b; p++) seqs.push(model.seqOfPage(p));
        }
        const withMarks = $('input[name=marks]', root).checked;
        close();
        printPages(model, seqs, { marks: withMarks ? opts.marks : null, penColors: opts.penColors, solved: opts.solved && withMarks, strike: opts.strike, revealed: opts.revealed });
      },
    }],
  });
}

function printPages(model, seqs, opts) {
  toast(`Setting ${fmt(seqs.length)} pages in type…`, { ms: 2500 });
  setTimeout(() => {
    buildPrintRoot(model, seqs, opts);
    document.body.classList.add('printing');
    const done = () => { document.body.classList.remove('printing'); $('#print-root').innerHTML = ''; window.removeEventListener('afterprint', done); };
    window.addEventListener('afterprint', done);
    requestAnimationFrame(() => requestAnimationFrame(() => window.print()));
  }, 50);
}

export const printSummary = model => `${esc(model.caseData.title)} — ${model.seq.length} pages`;
