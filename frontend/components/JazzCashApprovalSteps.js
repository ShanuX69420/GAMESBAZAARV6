// The one place that explains how a JazzCash MWallet request reaches the
// buyer. JazzCash delivers it two different ways and buyers kept waiting for
// the wrong one (support confusion, 2026-09):
//
//   - Jazz / Warid SIM: a USSD-style pop-up on the phone screen itself (not
//     inside the app). Only shows while the phone is unlocked. Enter MPIN.
//   - Any other network (Telenor, Zong, Ufone...): a JazzCash APP notification.
//     Tap it, or find it under Account -> Payment Requests -> Pending, then
//     approve with the MPIN.
//
// Used by the listing checkout and the wallet top-up form while a payment is
// pending, so both say exactly the same thing. The SIM guess from the number
// prefix only reorders the two paths — number portability means a 0300 number
// can live on Telenor — so both are always shown.

import { looksLikeJazzNumber } from '@/lib/jazzcashNetwork';

const STEP_STYLE = { marginTop: '6px', fontWeight: 400 };

function JazzStep({ likely }) {
  return (
    <div style={STEP_STYLE}>
      <strong>Jazz or Warid SIM{likely ? ' (looks like your number)' : ''}:</strong>{' '}
      a JazzCash pop-up appears on your phone screen itself — not inside the app.
      Unlock your phone and type your 4-digit MPIN there. Locked phones don&apos;t
      show the pop-up.
    </div>
  );
}

function OtherNetworkStep({ likely }) {
  return (
    <div style={STEP_STYLE}>
      <strong>Telenor, Zong, Ufone or any other SIM{likely ? ' (looks like your number)' : ''}:</strong>{' '}
      you get a JazzCash <em>app</em> notification. Tap it, or open the JazzCash app
      and go to Account → Payment Requests → Pending, choose this request and approve
      it with your MPIN.
    </div>
  );
}

export default function JazzCashApprovalSteps({ mobile, amountLabel, className = 'alert alert-success', style }) {
  const isJazz = looksLikeJazzNumber(mobile);
  const steps = isJazz === false
    ? [<OtherNetworkStep key="other" likely />, <JazzStep key="jazz" />]
    : [<JazzStep key="jazz" likely={isJazz === true} />, <OtherNetworkStep key="other" />];

  return (
    <div className={className} style={style}>
      <strong>Approve the {amountLabel ? `${amountLabel} ` : ''}payment on your phone</strong>
      <div style={{ marginTop: '4px', fontWeight: 400 }}>
        JazzCash has just sent a request to the number you entered. Approve it within
        the next couple of minutes — the request expires quickly.
      </div>
      {steps}
      <div style={{ marginTop: '8px', fontWeight: 400 }}>
        Nothing arrived? Unlock your phone, then check Payment Requests in the JazzCash
        app. Keep this page open — it updates automatically once you approve.
      </div>
    </div>
  );
}
