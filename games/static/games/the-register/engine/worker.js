import { generateCase } from './generator.js';

self.onmessage = (e) => {
  const { code, difficulty, mode = 'cold' } = e.data;
  try {
    const caseData = generateCase(code, difficulty, mode, p => self.postMessage({ type: 'progress', ...p }));
    self.postMessage({ type: 'done', caseData });
  } catch (err) {
    self.postMessage({ type: 'error', message: err.message });
  }
};
