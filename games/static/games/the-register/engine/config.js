// ─────────────────────────────────────────────────────────────────────────
// Case-generation tuning. Everything that shapes a case lives here.
// After changing anything, run `npm run check` (or `node tools/check.mjs 30
// --stats`) to confirm cases still generate quickly and pass validation.
// Bump ENGINE_VERSION in generator.js when a change should alter which case a
// given case number produces.
// ─────────────────────────────────────────────────────────────────────────

/**
 * Difficulty sets three things:
 *   names — how many people are in the register (26,000 for Cozy, rising to
 *           52,000 for Noir, whose id is still 'hardboiled');
 *   band  — how many suspects survive the "section" clues (the ones about
 *           stretches of the register, struck in runs), i.e. how much
 *           name-by-name checking the reader does;
 *   clues — the [min, max] clue count.
 * There is at most one clue per type (see TYPES in rules.js), and in Cold Case
 * every clue must still be necessary.
 */
export const DIFFICULTIES = {
  cozy:       { label: 'Cozy',        blurb: 'A Sunday-afternoon mystery. A smaller register, and few suspects left once the sections are struck.', names: 26000, band: [300, 600],   clues: [9, 10] },
  classic:    { label: 'Classic',     blurb: 'The intended experience: a few evenings with the Register.',                                         names: 39000, band: [700, 1400],  clues: [10, 12] },
  hardboiled: { label: 'Noir',        blurb: 'Fifty-two thousand names, and thousands still standing after the sections. Bring coffee.',          names: 52000, band: [1500, 3000], clues: [12, 15] },
};

/** How many names a case of this difficulty has. Cases before engine 7 always had 26,000. */
export const namesFor = (difficulty, engine) => (engine && engine < 7) ? 26000 : DIFFICULTIES[difficulty]?.names ?? 26000;

/** Absolute floor on clues per case, whatever a difficulty says. */
export const MIN_CLUES = 7;

/**
 * Of the fine clues (everything but the section clues), how many come from
 * each tier, for cases made before engine 7. Newer cases take their quotas
 * from their style (below).
 */
export const TIER_QUOTA = {
  name: [2, 10],       // of 10 name types
  connection: [1, 7],  // of 9 connection types
};

/**
 * How many section clues (stretches of the register: between two named
 * people, after a landmark name, near the victim, the chapter a name appears
 * in) a Cold Case uses. They are struck in runs, so they open the case.
 */
export const SECTION_CLUES = [2, 4];

/**
 * How readily each kind of section clue is dealt. The strongest kinds (a
 * span between two names, a window around the victim) land a case in its
 * band most easily, so left alone they'd open nearly every case; these
 * weights tilt the draw toward the others.
 */
export const SECTION_WEIGHT = { span: 0.5, nearVictim: 0.7, landmark: 1.6, chapterCompany: 1.4, nearPerson: 0.5, chapterRelative: 1.0 };

/**
 * Case styles: every case leans a different way, so no two feel alike. Each
 * style sets the tier quotas for the fine clues — name (the name itself),
 * connection (neighbours, family, the victim) and reasoning (clues built from
 * two conditions, or that cross a name with its position) — and how many fine
 * types it may draw from at all. The reader sees the style in the case report.
 */
export const STYLES = {
  wordsmith:   { label: 'The Wordsmith',   blurb: 'Most of the evidence is about the names themselves.',           quota: { name: [4, 9], connection: [1, 3], reasoning: [0, 2] } },
  gossip:      { label: 'The Gossip',      blurb: 'Most of the evidence is about who sits near whom, and family.', quota: { name: [2, 5], connection: [3, 6], reasoning: [0, 2] } },
  logician:    { label: 'The Logician',    blurb: 'Expect evidence that hangs on “if”, “either” and “both”.',     quota: { name: [2, 5], connection: [1, 3], reasoning: [2, 4] } },
  generalist:  { label: 'The Generalist',  blurb: 'A little of everything.',                                     quota: { name: [2, 6], connection: [2, 4], reasoning: [1, 3] } },
};
/** Each case also sets aside this share of the fine types it could use, so the mix differs every time. */
export const TYPE_DROPOUT = 0.4;

/**
 * Balance thresholds. "Suspects" means everyone except the killer and the
 * victim (25,998 names). A clue "clears" a name when the name breaks it.
 */
export const BALANCE = {
  // (2) No single clue may clear more than this share of suspects — no clue
  // does the whole job. Also a floor, so no clue is a near no-op.
  maxClearShare: 0.80,
  minClearShare: 0.12,
  // Tighter caps for clue types that are applied in bulk with a few clicks.
  // A chapter clue struck with "Strike chapter" shouldn't wipe out half the
  // town — it should trim the book, leaving the real work to the other clues.
  // (Engine 7 has no chapter clues; chapterCompany is the nearest relative.)
  maxClearShareByType: { chapter: 0.35, chapterCompany: 0.6 },

  // (1) Overlap: at most `maxShare` of suspects may be cleared by `clues` or
  // more clues.
  //
  // Measured on typical cases, the share of suspects cleared by at least k clues:
  //     k:   2      4      6      8      10     12
  //        99.7%  95.5%  78%    46%    14%    1.7%
  // "Cleared by 2+" is pinned near 99.7% by arithmetic: every suspect must be
  // cleared, and the only names cleared by exactly one clue are the near-misses
  // that make each clue necessary — with one solution allowed there can only be
  // a few dozen. So the literal { clues: 2 } can only be set to ~0.999 and
  // barely bites. The default caps pile-ups instead: no more than 22% of the
  // town may be struck by 10 or more clues.
  overlap: { clues: 10, maxShare: 0.22 },

  // Every clue must be the *only* clue clearing at least this many names.
  // 1 = every clue is strictly necessary. Higher = each clue does more
  // unique work (and the case is more forgiving of a misread clue elsewhere).
  minSoloClears: 1,

  // Read in Casebook order, every clue must newly clear at least this share
  // of the suspects still standing when the reader reaches it. Keeps late
  // clues from feeling like busywork.
  minMarginalShare: 0.08,

  // No two clues may clear nearly the same names: if the smaller of two clues'
  // cleared sets lies this much inside the other's, they read as a repeat.
  maxPairOverlap: 0.85,
};

/** Search effort. Raise if cases start failing to generate; lower for speed. */
export const SEARCH = {
  attempts: 300,       // fresh killer/victim picks before giving up (a failed
                       // attempt is cheap; most fail fast on an awkward killer)
  iterations: 1500,    // local-search steps per attempt (more rarely helps:
                       // a stuck attempt is usually a hard killer — re-pick)
  candidates: 32,      // moves scored per step
  uphill: 0.04,        // chance of accepting a worse move (escapes dead ends)
  perType: 6,          // candidate moves per clue type per step, so a type with
                       // hundreds of forms is no likelier to be tried than one with two
  sample: 40,          // clues drawn per attempt for each sampled family (the
                       // section clues and compound clues have too many
                       // possible forms to enumerate, so each attempt draws
                       // fresh ones that fit its killer)
};
