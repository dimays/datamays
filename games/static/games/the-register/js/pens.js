// Highlighter pens. Pen n (1…clues) belongs to clue n; PENCIL is "struck,
// reason unrecorded". A mark stores the pen, so recoloring a clue recolors
// every name it struck.
export const PENCIL = 250;

export const PALETTE = [
  { id: 'yellow', name: 'Canary', hex: '#ffd84a' },
  { id: 'pink', name: 'Flamingo', hex: '#ff8ab3' },
  { id: 'green', name: 'Fern', hex: '#86dc6e' },
  { id: 'blue', name: 'Cornflower', hex: '#78c2ff' },
  { id: 'orange', name: 'Marmalade', hex: '#ffa95a' },
  { id: 'violet', name: 'Heliotrope', hex: '#bf9bff' },
  { id: 'teal', name: 'Seaglass', hex: '#4fd8c4' },
  { id: 'red', name: 'Pillar-box', hex: '#ff7366' },
  { id: 'lime', name: 'Greengage', hex: '#cdeb4f' },
  { id: 'rose', name: 'Orchid', hex: '#f2a6e6' },
  { id: 'sky', name: 'Duck-egg', hex: '#9fe3ff' },
  { id: 'sand', name: 'Biscuit', hex: '#e2c08a' },
  { id: 'graphite', name: 'Graphite', hex: '#b8b2a7' },
];

export function defaultPenColors(clueCount) {
  const c = {};
  for (let k = 1; k <= clueCount; k++) c[k] = PALETTE[(k - 1) % 12].id;
  c[PENCIL] = 'graphite';
  return c;
}

export const hexOf = id => (PALETTE.find(p => p.id === id) || PALETTE[12]).hex;

/** A highlighter-shaped cursor in the pen's color. */
export function penCursor(hex) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28"><g transform="rotate(-35 14 14)"><rect x="9" y="2" width="10" height="16" rx="2" fill="${hex}" stroke="#4a3b30" stroke-width="1.5"/><path d="M10 18h8l-2 6h-4z" fill="${hex}" stroke="#4a3b30" stroke-width="1.5"/></g></svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}") 19 22, crosshair`;
}

/** CSS that maps each pen's marks to its current color. */
export function penStyles(penColors) {
  return Object.entries(penColors).map(([pen, id]) => `.nm[data-pen="${pen}"]{--mc:${hexOf(id)}}`).join('\n');
}
