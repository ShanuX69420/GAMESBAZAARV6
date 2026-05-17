import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  GOOGLE_SCRIPT_SRC,
  GOOGLE_STATE_KEY,
  getGoogleIdentityState,
  initializeGoogleIdentity,
  loadGoogleIdentityScript,
} from '../lib/googleIdentity';

function makeScript(src = '') {
  const listeners = {};

  return {
    src,
    async: false,
    defer: false,
    parentNode: null,
    addEventListener: vi.fn((event, handler) => {
      listeners[event] = handler;
    }),
    dispatch(event) {
      listeners[event]?.();
    },
  };
}

function setupDom({ existingScript = null, google = undefined } = {}) {
  const scripts = existingScript ? [existingScript] : [];
  const document = {
    head: {
      appendChild: vi.fn((script) => {
        script.parentNode = document.head;
        scripts.push(script);
      }),
    },
    createElement: vi.fn(() => makeScript()),
    querySelector: vi.fn(() => scripts.find((script) => script.src === GOOGLE_SCRIPT_SRC) || null),
  };
  if (existingScript) existingScript.parentNode = document.head;
  const window = { document };
  if (google !== undefined) window.google = google;

  vi.stubGlobal('window', window);
  vi.stubGlobal('document', document);

  return { document, scripts, window };
}

describe('Google Identity helpers', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('does not create browser state during server rendering', () => {
    expect(getGoogleIdentityState()).toBeNull();
  });

  it('creates one shared browser state object', () => {
    const { window } = setupDom();

    const first = getGoogleIdentityState();
    const second = getGoogleIdentityState();

    expect(first).toBe(second);
    expect(window[GOOGLE_STATE_KEY]).toBe(first);
    expect(first).toEqual({
      scriptPromise: null,
      initializedClientId: null,
      credentialHandler: null,
    });
  });

  it('loads the Google script once and reuses the pending promise', async () => {
    const { document, scripts } = setupDom();
    const state = { scriptPromise: null };

    const firstLoad = loadGoogleIdentityScript(state);
    const secondLoad = loadGoogleIdentityScript(state);

    expect(secondLoad).toBe(firstLoad);
    expect(document.createElement).toHaveBeenCalledWith('script');
    expect(document.head.appendChild).toHaveBeenCalledTimes(1);
    expect(scripts[0].src).toBe(GOOGLE_SCRIPT_SRC);
    expect(scripts[0].async).toBe(true);
    expect(scripts[0].defer).toBe(true);

    scripts[0].dispatch('load');

    await expect(firstLoad).resolves.toBeUndefined();
  });

  it('reuses an existing script tag and clears the cached promise on load failure', async () => {
    const existingScript = makeScript(GOOGLE_SCRIPT_SRC);
    const { document } = setupDom({ existingScript });
    const state = { scriptPromise: null };

    const loadFailure = loadGoogleIdentityScript(state);
    const rejection = expect(loadFailure).rejects.toThrow('Unable to load Google sign-in');

    expect(document.createElement).not.toHaveBeenCalled();
    expect(document.head.appendChild).not.toHaveBeenCalled();

    existingScript.dispatch('error');

    await rejection;
    expect(state.scriptPromise).toBeNull();
  });

  it('initializes once per client id and routes credentials through the current handler', () => {
    const initialize = vi.fn();
    setupDom({ google: { accounts: { id: { initialize } } } });
    const credentialHandler = vi.fn();
    const state = {
      initializedClientId: null,
      credentialHandler,
    };

    initializeGoogleIdentity(state, 'client-one');
    initializeGoogleIdentity(state, 'client-one');

    expect(initialize).toHaveBeenCalledTimes(1);
    expect(initialize.mock.calls[0][0]).toMatchObject({
      client_id: 'client-one',
      auto_select: false,
      cancel_on_tap_outside: true,
    });

    initialize.mock.calls[0][0].callback({ credential: 'token' });
    expect(credentialHandler).toHaveBeenCalledWith({ credential: 'token' });

    initializeGoogleIdentity(state, 'client-two');

    expect(initialize).toHaveBeenCalledTimes(2);
    expect(state.initializedClientId).toBe('client-two');
  });

  it('fails clearly when initialized before Google Identity is available', () => {
    setupDom();

    expect(() => initializeGoogleIdentity({ initializedClientId: null }, 'client-one'))
      .toThrow('Google sign-in is not available yet.');
  });
});
