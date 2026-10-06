// Extras when the Register is served by the Unnecessary Obstacles hub
// (its page sets data-hub="1"): today's daily cases, posting a solve to the
// leaderboard, and counting cases started and solved. Anywhere else — the
// desktop app, other sites — none of this runs and nothing is sent.

import { api } from './api.js';
import { esc, toast } from './util.js';
import { ENGINE_VERSION } from '../engine/generator.js';

const page = document.documentElement.dataset;
export const HUB = page.hub === '1';
const API = page.api || '/api/';
export const hubUser = () => page.user || '';
export const leaderboardUrl = () => page.leaderboard || '/leaderboard/';
export const accountUrl = () => page.account || '';
const PENDING = 'uo:pending';

/** A random id this browser keeps so the hub can count players, not plays. Not a cookie; nothing about the person. */
function visitor() {
  try {
    let v = localStorage.getItem('uo:visitor');
    if (!v) {
      v = [...crypto.getRandomValues(new Uint8Array(8))].map(b => b.toString(16).padStart(2, '0')).join('');
      localStorage.setItem('uo:visitor', v);
    }
    return v;
  } catch { return ''; }
}

/**
 * Count a case started or solved: mode, difficulty and whether it was a daily
 * case. A start also names the case, so the hub's referee can check it
 * before the player finishes.
 */
export function track(kind, g) {
  if (!HUB) return;
  const body = JSON.stringify({ kind, game: 'the-register', mode: g.mode || 'cold', difficulty: g.difficulty, daily: !!g.daily, visitor: visitor(), code: g.code, engine: ENGINE_VERSION });
  try {
    if (!navigator.sendBeacon?.(API + 'events/', new Blob([body], { type: 'application/json' }))) {
      fetch(API + 'events/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {});
    }
  } catch { /* counting must never get in the way of playing */ }
}

/** Today's daily cases: { date, cases: [{ mode, difficulty, code }] }. */
export async function dailyCases() {
  const r = await fetch(API + 'daily/', { credentials: 'same-origin' });
  if (!r.ok) throw new Error('No daily cases right now.');
  return r.json();
}

const csrf = () => document.cookie.split('; ').find(c => c.startsWith('csrftoken='))?.slice(10) || page.csrf || '';

/** What a solved game posts. */
export function scoreFor(g, killer, engine) {
  return {
    code: g.code, difficulty: g.difficulty, mode: g.mode || 'cold', engine, accused: killer,
    seconds: Math.round(g.timePlayed || 0), wrong: (g.accusations || []).filter(a => !a.correct).length, hints: g.hints || 0,
    gameId: g.id, title: g.title,
  };
}

/** Post a solve. Resolves to { status, ok, time, points, daily, rank, of, url } or { status, ok: false, error, login, signup }. */
export async function postScore(score) {
  let r;
  try {
    r = await fetch(API + 'scores/', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(score) });
  } catch {
    return { status: 0, ok: false, error: 'Couldn’t reach the leaderboard. Check your connection and try again.' };
  }
  const out = await r.json().catch(() => ({ ok: false, error: 'The leaderboard didn’t answer properly. Try again in a moment.' }));
  return { status: r.status, ...out };
}

/** A solve waiting for its player to sign in, kept in this browser until then. */
export const pending = {
  get() { try { return JSON.parse(localStorage.getItem(PENDING)); } catch { return null; } },
  set(score) { try { localStorage.setItem(PENDING, JSON.stringify(score)); } catch { /* storage blocked */ } },
  clear() { try { localStorage.removeItem(PENDING); } catch { /* storage blocked */ } },
};

/** Where to sign in or sign up so as to come straight back here. */
export const signInUrl = (kind = 'login') => `${kind === 'signup' ? page.signup : page.login}?next=${encodeURIComponent(location.pathname + location.hash)}`;

/**
 * A solve held while its player signed in goes up as soon as they're back.
 * Runs once on load, before any game opens, so marking the saved game as
 * posted can't collide with an open game window's own saves.
 */
export async function flushPending() {
  const p = HUB && hubUser() ? pending.get() : null;
  if (!p) return;
  const res = await postScore(p);
  // Still signed out, offline, or the case is still being checked: try again next time.
  if (res.status === 401 || res.status === 0 || res.status === 202) return;
  pending.clear();
  if (!res.ok) return toast(esc(res.error || 'That score couldn’t be posted.'));
  const g = p.gameId ? await api.getGame(p.gameId).catch(() => null) : null;
  if (g) {
    g.posted = { time: res.time, points: res.points, rank: res.rank ?? null };
    g.updatedAt = Date.now();
    await api.putGame(g).catch(() => {});
  }
  setTimeout(() => toast(`Posted ${esc(p.title || 'your case')}: ${esc(res.time)}${res.rank ? `, #${res.rank} today` : ''}.`, { action: 'Leaderboard', onAction: () => { location.href = res.url; }, ms: 9000 }), 600);
}
