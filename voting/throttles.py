"""
Voting rate-limit throttles (DRF SimpleRateThrottle subclasses).

1. What is limited:
   - POST /api/vote/           : per authenticated user pk    (scope: auth_user)
   - POST /api/vote/link/<t>/  : per sha256(token) hex digest (scope: link_token)
                                 + per client REMOTE_ADDR IP  (scope: link_ip)

2. Where enforced:
   Throttle classes are listed in each view's throttle_classes attribute:
   AuthenticatedVoteView: [AuthenticatedUserThrottle]
   LinkVoteView: [LinkTokenThrottle, LinkIpThrottle]
   DRF runs throttles before view mutation logic, after authentication/permissions.

3. Response when exceeded:
   HTTP 429 Too Many Requests with a clean DRF JSON body {"detail": "..."}
   and a Retry-After header. Never returns 500.

4. How to test:
   - Default test CACHES uses DummyCache for the "throttle" alias under `manage.py test`,
     so throttling is inert during the normal test suite and existing tests are unaffected.
   - Throttle tests opt in via @override_settings(CACHES={"throttle": ...})
     with a real LocMemCache, and clear it in setUp.
   - Patch the throttle timer / time.time to advance time without sleeping.

5. History-based throttling concurrency:
   DRF's history-based throttling is not atomic under concurrency.

6. DB constraints guarantee:
   Database constraints (unique_vote_per_user, unique_vote_per_token, etc.)
   remain the authoritative integrity guarantee. Rate limiting does NOT replace them.

7. LocMemCache is per-process:
   LocMemCache stores throttle history in memory within a single process.

8. Acceptable for single-process Docker:
   This is completely acceptable and effective for the single-process Docker runserver.

9. Multi-worker shared cache:
   Multi-worker deployments in production would require a shared cache backend (e.g. Redis).
"""
import hashlib

from django.conf import settings
from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class _VoteThrottleBase(SimpleRateThrottle):
    """
    Base throttle that:
    - reads its rate from settings.VOTE_RATE_LIMITS[scope] at request time
    - uses the dedicated "throttle" cache alias resolved at access time
    - uses REMOTE_ADDR only (ignores X-Forwarded-For)
    """

    @property
    def cache(self):
        """Resolve the 'throttle' cache alias dynamically at access time."""
        return caches["throttle"]

    def get_rate(self):
        """Read rate from settings at request time so tests can override."""
        limits = getattr(settings, "VOTE_RATE_LIMITS", {})
        return limits.get(self.scope, None)

    def get_ident(self, request):
        """
        Use REMOTE_ADDR only. DRF's default get_ident trusts
        X-Forwarded-For when NUM_PROXIES is configured, which allows
        clients to evade rate limits by spoofing that header.
        """
        return request.META.get("REMOTE_ADDR", "")

    def allow_request(self, request, view):
        """
        Ensure rate is resolved at request time from settings before checking,
        and allow unconditionally if no rate is set for this scope.
        """
        self.rate = self.get_rate()
        if self.rate is None:
            return True
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)


class AuthenticatedUserThrottle(_VoteThrottleBase):
    """Per-authenticated-user throttle for POST /api/vote/."""
    scope = "auth_user"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None  # unauthenticated requests handled by permissions
        return self.cache_format % {
            "scope": self.scope,
            "ident": str(request.user.pk),
        }


AuthUserThrottle = AuthenticatedUserThrottle


class LinkTokenThrottle(_VoteThrottleBase):
    """Per-token throttle for POST /api/vote/link/<token>/."""
    scope = "link_token"

    def get_cache_key(self, request, view):
        token = view.kwargs.get("token", "")
        if not token:
            return None
        # Never put the raw token in a cache key
        hashed = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return self.cache_format % {
            "scope": self.scope,
            "ident": hashed,
        }


class LinkIpThrottle(_VoteThrottleBase):
    """Per-IP throttle for POST /api/vote/link/<token>/."""
    scope = "link_ip"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        if not ident:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


LinkIPThrottle = LinkIpThrottle
