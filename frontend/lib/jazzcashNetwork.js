// Which network a JazzCash number probably lives on. JazzCash delivers the
// MPIN request two ways — a USSD pop-up on Jazz/Warid SIMs, an app
// notification on every other network — and the checkout copy leads with the
// path that matches the number. Number portability makes this a guess, so
// callers must still show both paths.
//
// 030x = Jazz, 032x = Warid (merged into Jazz). 031x Zong, 033x Ufone,
// 034x Telenor, 035x SCOM.
const JAZZ_PREFIX = /^03[02]\d/;

// true = Jazz/Warid prefix, false = another network's prefix,
// null = not enough digits typed yet to tell.
export function looksLikeJazzNumber(mobile) {
  const digits = (mobile || '').replace(/\D/g, '');
  if (digits.length < 4) return null;
  return JAZZ_PREFIX.test(digits);
}
