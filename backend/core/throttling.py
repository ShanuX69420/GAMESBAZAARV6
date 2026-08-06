"""
Throttle classes for endpoints where a rejected request isn't an abuse signal.

DRF's throttles record every request that reaches the view, so a form the
serializer rejected costs the caller the same allowance as one it accepted.
On signup that is backwards: the people who burn the limit are the ones who
mistyped a password or picked a taken name, and Pakistani carriers put
thousands of subscribers behind a single NAT'd IP, so one person fumbling
the form locks out everyone else on that IP too.
"""

from rest_framework.throttling import ScopedRateThrottle


class SuccessScopedRateThrottle(ScopedRateThrottle):
    """
    A scoped throttle that only counts requests the view actually accepted.

    The allowance is still checked up front, but nothing is written to the
    cache until the view calls `record()` (see `SuccessCountedThrottleMixin`).
    Pair it with an `AttemptScopedRateThrottle` so scripted floods are still
    capped — on its own this class would let a bot retry forever.
    """

    def throttle_success(self):
        # Defer the write until the view reports success.
        return True

    def record(self):
        """Count one accepted request against the allowance."""
        # allow_request() returns early — before setting these — when the view
        # has no scope or the request isn't throttled at all.
        if getattr(self, 'key', None) is None or not hasattr(self, 'history'):
            return
        self.history.insert(0, self.now)
        self.cache.set(self.key, self.history, self.duration)


class AttemptScopedRateThrottle(ScopedRateThrottle):
    """
    Counts every attempt, reading its rate from `attempt_throttle_scope`.

    The separate scope attribute lets one view carry both a tight
    success limit and a loose attempt ceiling.
    """

    scope_attr = 'attempt_throttle_scope'
