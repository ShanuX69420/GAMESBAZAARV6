'use client';

import { useEffect, useRef, useCallback } from 'react';
import { GOOGLE_CLIENT_ID } from '@/lib/config';
import { useAuth } from '@/lib/auth';
import {
  getGoogleIdentityState,
  initializeGoogleIdentity,
  loadGoogleIdentityScript,
} from '@/lib/googleIdentity';

/**
 * Renders Google's "Sign in with Google" button using the GSI library.
 * Only renders when GOOGLE_CLIENT_ID is configured.
 *
 * @param {Object} props
 * @param {function} props.onSuccess - Called with user data after successful login
 * @param {function} props.onError - Called with error message on failure
 */
export default function GoogleSignInButton({ onSuccess, onError }) {
  const { googleLogin } = useAuth();
  const buttonRef = useRef(null);
  const latestHandlersRef = useRef({ googleLogin, onSuccess, onError });

  useEffect(() => {
    latestHandlersRef.current = { googleLogin, onSuccess, onError };
  }, [googleLogin, onSuccess, onError]);

  const handleCredentialResponse = useCallback(async (response) => {
    const {
      googleLogin: signInWithGoogle,
      onSuccess: handleSuccess,
      onError: handleError,
    } = latestHandlersRef.current;

    if (!response?.credential) {
      handleError?.('Google sign-in did not return a credential');
      return;
    }

    try {
      const userData = await signInWithGoogle(response.credential);
      handleSuccess?.(userData);
    } catch (err) {
      handleError?.(err.message || 'Google sign-in failed');
    }
  }, []);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;

    const state = getGoogleIdentityState();
    if (!state) return;

    let isMounted = true;
    state.credentialHandler = handleCredentialResponse;

    loadGoogleIdentityScript(state)
      .then(() => {
        if (!isMounted) return;
        initializeGoogleIdentity(state);

        if (!window.google?.accounts?.id) return;
        if (!buttonRef.current) return;

        buttonRef.current.replaceChildren();
        window.google.accounts.id.renderButton(buttonRef.current, {
          type: 'standard',
          theme: 'outline',
          size: 'large',
          width: buttonRef.current.offsetWidth || 360,
          text: 'continue_with',
          shape: 'pill',
          logo_alignment: 'left',
        });
      })
      .catch((err) => {
        if (!isMounted) return;
        latestHandlersRef.current.onError?.(err.message || 'Google sign-in failed to load');
      });

    return () => {
      isMounted = false;
      if (state.credentialHandler === handleCredentialResponse) {
        state.credentialHandler = null;
      }
      if (buttonRef.current) {
        buttonRef.current.replaceChildren();
      }
    };
  }, [handleCredentialResponse]);

  if (!GOOGLE_CLIENT_ID) return null;

  return (
    <div className="google-signin-wrapper">
      <div className="auth-divider">
        <span className="auth-divider-line" />
        <span className="auth-divider-text">or</span>
        <span className="auth-divider-line" />
      </div>
      <div ref={buttonRef} className="google-signin-btn" />
    </div>
  );
}
