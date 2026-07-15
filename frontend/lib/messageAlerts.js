// Incoming-message alerts: the notification ding and the "(3) GamesBazaar"
// unread counter in the browser tab title. Used by the navbar, which is the
// single place that reacts to inbox socket events on every page.

// ── Tab title unread counter ──────────────────────────────────────────────

const UNREAD_PREFIX_RE = /^\(\d{1,2}\+?\)\s/;

/**
 * Return `title` with the unread-chats counter applied: "(4) GamesBazaar".
 * Strips any existing counter first so repeated calls never stack prefixes;
 * a count of 0 just returns the bare title.
 */
export function withUnreadCount(title, count) {
  const base = title.replace(UNREAD_PREFIX_RE, '');
  if (!count || count <= 0) return base;
  return `(${count > 99 ? '99+' : count}) ${base}`;
}

// ── Message sound ─────────────────────────────────────────────────────────

// One ding per conversation per cooldown window: a spammer's burst gives a
// single sound, while a message from a different chat still dings instantly.
// Reading or replying to a chat resets its cooldown (see
// resetMessageSoundCooldown), so an active back-and-forth dings every time.
// Stamps live in localStorage so the cooldown is shared across open tabs.
const SOUND_COOLDOWN_MS = 5 * 60 * 1000;
const SOUND_STAMP_KEY = 'gamesbazaar:message-sound-stamps';
const SOUND_URL = '/sounds/message.mp3';
const SOUND_VOLUME = 0.8;

let audioCtx = null;
let soundBuffer = null;
let soundBufferPromise = null;

function getAudioContext() {
  if (typeof window === 'undefined') return null;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  if (!audioCtx) {
    try {
      audioCtx = new Ctx();
    } catch {
      return null;
    }
  }
  return audioCtx;
}

function loadSoundBuffer(ctx) {
  if (soundBuffer) return Promise.resolve(soundBuffer);
  if (!soundBufferPromise) {
    soundBufferPromise = fetch(SOUND_URL)
      .then(res => (res.ok ? res.arrayBuffer() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then(data => ctx.decodeAudioData(data))
      .then(buffer => {
        soundBuffer = buffer;
        return buffer;
      })
      .catch(() => {
        soundBufferPromise = null; // allow a retry on the next ding
        return null;
      });
  }
  return soundBufferPromise;
}

/**
 * Browsers keep audio suspended until the page sees a user gesture. Call
 * this from a gesture handler (any click/keypress) so later dings can play
 * even while the tab sits in the background.
 */
export function unlockMessageSound() {
  const ctx = getAudioContext();
  if (!ctx) return;
  if (ctx.state === 'suspended') {
    ctx.resume().catch(() => {});
  }
  // Warm the sound file so the first real ding plays without a fetch delay.
  loadSoundBuffer(ctx);
}

/**
 * Pure cooldown step: given the per-conversation stamp map, return the
 * pruned/updated map if this conversation may ding at `now`, or null while
 * it is still cooling down. Exported for tests.
 */
export function nextSoundStamps(stamps, conversationId, now, cooldownMs = SOUND_COOLDOWN_MS) {
  const key = String(conversationId);
  if (key in stamps && now - Number(stamps[key]) < cooldownMs) return null;
  const next = {};
  for (const [id, ts] of Object.entries(stamps)) {
    if (now - Number(ts) < cooldownMs) next[id] = ts; // drop expired entries
  }
  next[key] = now;
  return next;
}

function readSoundStamps() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SOUND_STAMP_KEY));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeSoundStamps(stamps) {
  try {
    window.localStorage.setItem(SOUND_STAMP_KEY, JSON.stringify(stamps));
  } catch {
    // Private mode etc. — the sound just won't dedupe across tabs.
  }
}

/**
 * Forget a conversation's cooldown — call when the user reads or replies to
 * it, so its next incoming message dings immediately again.
 */
export function resetMessageSoundCooldown(conversationId) {
  const stamps = readSoundStamps();
  const key = String(conversationId);
  if (!(key in stamps)) return;
  delete stamps[key];
  writeSoundStamps(stamps);
}

/**
 * Play the incoming-message ding for a conversation, at most once per
 * cooldown window per conversation (silently no-op if audio is blocked).
 */
export function playMessageSound(conversationId) {
  const ctx = getAudioContext();
  if (!ctx) return;
  const stamps = nextSoundStamps(readSoundStamps(), conversationId, Date.now());
  if (!stamps) return;
  writeSoundStamps(stamps);
  if (ctx.state === 'suspended') {
    // Only succeeds if the browser already saw a gesture; otherwise stay quiet.
    ctx.resume().then(() => ding(ctx)).catch(() => {});
    return;
  }
  ding(ctx);
}

function ding(ctx) {
  loadSoundBuffer(ctx).then(buffer => {
    if (!buffer) return;
    try {
      const source = ctx.createBufferSource();
      const gain = ctx.createGain();
      source.buffer = buffer;
      gain.gain.value = SOUND_VOLUME;
      source.connect(gain);
      gain.connect(ctx.destination);
      source.start();
    } catch {
      // A failed ding must never break the app.
    }
  });
}
