// The case's narrative dressing, drawn from its setting (settings.js).
// Pronoun-neutral throughout: residents are names first, and the reader
// decides who they are.
import { CLINCHERS } from './settings.js';

export function generateStory(rng, victim, setting) {
  const place = setting.place(rng);
  return {
    setting: setting.id,
    place,
    titles: setting.titles(place),
    premise: setting.premise(place),
    registerWord: setting.registerWord,
    people: setting.people,
    role: rng.pick(setting.roles),
    scene: rng.pick(setting.scenes),
    weapon: rng.pick(setting.weapons),
    night: rng.pick(setting.nights),
    inspector: rng.pick(setting.inspectors),
    motive: rng.pick(setting.motives),
    clincher: rng.pick(CLINCHERS).replace(/\bregister\b/g, setting.registerWord.toLowerCase()),
    victim: victim.name,
  };
}

export const caseTitle = story => story.titles?.full || `The ${story.town} Register`;
export const shortTitle = story => story.titles?.short || `The ${story.town} Register`;
export const registerWord = story => story.registerWord || 'Register';
export const peopleWord = story => story.people || 'residents';
const cap = s => s[0].toUpperCase() + s.slice(1);

export function prologue(story, book, victimEntry, ruleCount, mode = 'cold') {
  const total = book.entries.length.toLocaleString('en-US');
  const where = `listed on page ${victimEntry.page}, line ${victimEntry.line}, marked with a †`;
  const evidence = mode === 'inquiry'
    ? `${story.inspector} has ${ruleCount} witnesses to hear. They come forward one at a time — each only once you have struck every name the evidence so far rules out.`
    : `${story.inspector} has gathered ${ruleCount} pieces of evidence. Each one, on its own, clears a great many people. Together, they clear everyone but one.`;
  if (!story.titles) {
    // Cases made before settings existed.
    return [
      `${cap(story.night)}, ${story.victim}, ${story.role} of ${story.town}, was found ${story.scene}. Beside the body lay ${story.weapon}.`,
      `Every soul in ${story.town} — all ${total} of them — is entered in the Register, the great ledger of names kept at the Town Hall. The killer is among them. So, now, is the victim: ${story.victim} is ${where}.`,
      evidence,
      'Work through the Register. Strike out every name that the evidence rules out. When a single name remains, you have your killer.',
    ];
  }
  const word = registerWord(story);
  return [
    `${cap(story.night)}, ${story.victim}, ${story.role}, was found ${story.scene}. Beside the body lay ${story.weapon}.`,
    `The ${word} records ${story.premise} — ${total} names in all, families and companions entered together. The killer is among them. So, now, is the victim: ${story.victim} is ${where}.`,
    evidence,
    `Work through the ${word}. Strike out every name the evidence rules out. When a single name remains, you have your killer. Names repeat — accuse by page and line, not by name alone.`,
  ];
}

export function epilogue(story, killer) {
  const book = shortTitle(story).replace(/^The /, 'the ');
  return [
    `It was ${killer.name} — page ${killer.page}, line ${killer.line} of ${book}.`,
    `The motive, when it finally came out, was ${story.motive}. ${story.clincher}`,
    `${story.inspector} closed the ${registerWord(story)} with a soft thump. Out of ${(26000).toLocaleString('en-US')} names, only one had nowhere left to hide.`,
  ];
}
