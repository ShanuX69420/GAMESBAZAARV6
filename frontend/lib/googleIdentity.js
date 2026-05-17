import { GOOGLE_CLIENT_ID } from '@/lib/config';

export const GOOGLE_SCRIPT_SRC = 'https://accounts.google.com/gsi/client';
export const GOOGLE_STATE_KEY = '__opusGoogleIdentityState';

export function getGoogleIdentityState() {
  if (typeof window === 'undefined') return null;

  if (!window[GOOGLE_STATE_KEY]) {
    window[GOOGLE_STATE_KEY] = {
      scriptPromise: null,
      initializedClientId: null,
      credentialHandler: null,
    };
  }

  return window[GOOGLE_STATE_KEY];
}

export function loadGoogleIdentityScript(state) {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (state.scriptPromise) return state.scriptPromise;

  state.scriptPromise = new Promise((resolve, reject) => {
    let script = document.querySelector(`script[src="${GOOGLE_SCRIPT_SRC}"]`);

    function handleLoad() {
      resolve();
    }

    function handleError() {
      state.scriptPromise = null;
      reject(new Error('Unable to load Google sign-in. Please try again.'));
    }

    if (!script) {
      script = document.createElement('script');
      script.src = GOOGLE_SCRIPT_SRC;
      script.async = true;
      script.defer = true;
    }

    script.addEventListener('load', handleLoad, { once: true });
    script.addEventListener('error', handleError, { once: true });

    if (!script.parentNode) {
      document.head.appendChild(script);
    }
  });

  return state.scriptPromise;
}

export function initializeGoogleIdentity(state, clientId = GOOGLE_CLIENT_ID) {
  if (!window.google?.accounts?.id) {
    throw new Error('Google sign-in is not available yet.');
  }

  if (state.initializedClientId === clientId) return;

  window.google.accounts.id.initialize({
    client_id: clientId,
    callback: (response) => {
      state.credentialHandler?.(response);
    },
    auto_select: false,
    cancel_on_tap_outside: true,
  });

  state.initializedClientId = clientId;
}
