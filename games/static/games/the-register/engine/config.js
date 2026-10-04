// ─────────────────────────────────────────────────────────────────────────
// Case-generation tuning. Everything that shapes a case lives here.
// After changing anything, run `npm run check` (or `node tools/check.mjs 30
// --stats`) to confirm cases still generate quickly and pass validation.
// Bump ENGINE_VERSION in generator.js when a change should alter which case a
// given case number produces.
// ─────────────────────────────────────────────────────────────────────────

/**
 * Difficulty = how many suspects survive the four broad clues (chapter, page
 * number, column, line), i.e. how much name-by-name checking the reader does.
 * `clues` is the [min, max] clue count — fewer, bigger clues for Cozy, more,
 * finer ones for Hard-boiled. There is at most one clue per type (see TYPES
 * in rules.js), and in Cold Case every clue must still be necessary.
 */
export const DIFFICULTIES = {
  cozy:       { label: 'Cozy',        blurb: 'A Sunday-afternoon mystery. Fewer suspects survive the broad clues.', band: [250, 500],   clues: [9, 10] },
  classic:    { label: 'Classic',     blurb: 'The intended experience: a few evenings with the Register.',          band: [600, 1200],  clues: [10, 12] },
  hardboiled: { label: 'Hard-boiled', blurb: 'Thousands survive the broad clues. Bring coffee.',                   band: [1400, 2800], clues: [12, 15] },
};

/** Absolute floor on clues per case, whatever a difficulty says. */
export const MIN_CLUES = 7;

/**
 * Of the fine (non-broad) clues, how many come from each tier.
 * name: clues about the name itself; connection: neighbours, victim, page-mates.
 */
export const TIER_QUOTA = {
  name: [2, 10],       // of 10 name types
  connection: [1, 7],  // of 9 connection types
};

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
  maxClearShareByType: { chapter: 0.35 },

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
};
