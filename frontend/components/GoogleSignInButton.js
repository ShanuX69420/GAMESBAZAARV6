'use client';

import { useEffect, useRef, useCallback } from 'react';
import { GOOGLE_CLIENT_ID } from '@/lib/config';
import { useAuth } from '@/lib/auth';

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
  const initializedRef = useRef(false);
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
    if (!GOOGLE_CLIENT_ID || initializedRef.current) return;

    let script = document.querySelector('script[src="https://accounts.google.com/gsi/client"]');
    let listenerAttached = false;

    function initializeGoogle() {
      if (!window.google?.accounts?.id || initializedRef.current) return;
      initializedRef.current = true;

      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleCredentialResponse,
        auto_select: false,
        cancel_on_tap_outside: true,
      });

      if (buttonRef.current) {
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
      }
    }

    if (script) {
      if (window.google?.accounts?.id) {
        initializeGoogle();
      } else {
        script.addEventListener('load', initializeGoogle);
        listenerAttached = true;
      }
    } else {
      script = document.createElement('script');
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      script.defer = true;
      script.addEventListener('load', initializeGoogle);
      listenerAttached = true;
      document.head.appendChild(script);
    }

    return () => {
      if (listenerAttached && script) {
        script.removeEventListener('load', initializeGoogle);
      }
      initializedRef.current = false;
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
      <div ref={buttonRef} className="google-signin-btn" id="google-signin-button" />
    </div>
  );
}
